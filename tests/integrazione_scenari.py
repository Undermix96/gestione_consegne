"""
Scenari di integrazione: il sistema vero, tutto insieme.

  sorgente V1 (json | postgres | mysql | dati.json) → migrate.py (rapporto, poi esecuzione) → server.py vero
  su un backend (json | postgres | mysql) → superadmin, tipo account, utenti → i dati migrati sono visibili
  e corretti → operatività → secondo negozio → riavvio del server → controllo di integrità.

12 combinazioni sorgente × destinazione, più la catena V2 → V2 tra i tre backend (andata e ritorno).
Servono i tre database di test (compose.test.yaml). Si saltano con TEST_INTEGRATION=0.
"""
import os
import shutil
import tempfile
import unittest

import integrazione_lib as L

SALTA = os.environ.get("TEST_INTEGRATION", "1") == "0"


def tmpdir(test):
    d = tempfile.mkdtemp(prefix="gc_int_")
    test.addCleanup(shutil.rmtree, d, True)
    return d


def senza_versione(rows):
    return [{k: v for k, v in r.items() if k != "versione"} for r in rows]


@unittest.skipIf(SALTA, "TEST_INTEGRATION=0")
class Matrice(unittest.TestCase):
    """Un test per ogni combinazione (generati in fondo al file)."""

    def check_dati_migrati(self, api, tok, data):
        cons = api.must("GET", "/api/consegne", token=tok)["consegne"]
        sq = api.must("GET", "/api/squadre", token=tok)["squadre"]
        gio = api.must("GET", "/api/giornate", token=tok)["giornate"]
        self.assertEqual([c["id"] for c in cons], [c["id"] for c in data["consegne"]])   # ordine e id conservati
        byid = {c["id"]: c for c in cons}
        for e in data["consegne"]:
            for k, v in e.items():
                self.assertEqual(byid[e["id"]].get(k), v, f"consegna {e['id']} campo {k}")
            self.assertEqual(byid[e["id"]]["versione"], 1)
        nomi = {s["id"]: s["nome"] for s in sq}
        self.assertEqual(sorted(nomi.values()), ["Ghost", "Non assegnata", "Squadra A", "Squadra B"])
        self.assertEqual((nomi["sq1"], nomi["sq2"]), ("Squadra A", "Squadra B"))        # id V1 conservati
        gid = {g["id"]: g for g in gio}
        self.assertEqual(sorted(gid), sorted(g["id"] for g in data["giornate"]))
        for e in data["giornate"]:
            g = gid[e["id"]]
            self.assertEqual(nomi[g["squadra_id"]], L.SQUADRA_ATTESA[e["squadra"]], f"giornata {e['id']}")
            self.assertEqual(g["consegneIds"], e["consegneIds"])                         # ordine conservato
            self.assertEqual(g["data"], e["data"])
            self.assertNotIn("squadra", g)
        return cons, sq, gio

    def scenario(self, src, dst):
        tmp = tmpdir(self)
        data = L.v1_dataset(n_cons=10, n_giorn=4, per=2)
        senv = L.prepare_v1_source(src, tmp, data)
        denv = L.fresh_dest(dst, tmp)
        env = {**denv, **senv, "MIGRATE_OUT": os.path.join(tmp, "export.json")}

        # 1. rapporto: non scrive nulla
        rc, out = L.migrate(env)
        self.assertEqual(rc, 0, out)
        self.assertIn("Nulla è stato scritto", out)
        self.assertEqual(L.tables(denv), [], "il rapporto ha creato qualcosa nella destinazione")
        # 2. esecuzione; una seconda sulla stessa destinazione è rifiutata
        rc, out = L.migrate(env, MIGRATE_EXECUTE="1")
        self.assertEqual(rc, 0, out)
        self.assertIn("Verifica superata", out)
        rc, out = L.migrate(env, MIGRATE_EXECUTE="1")
        self.assertEqual(rc, 2, out)

        # 3. server vero, primo accesso del superadmin
        srv = L.ServerProc(denv, tmp).start()
        self.addCleanup(srv.stop)
        api = L.Api(srv.port)
        sa = api.superadmin()
        negozi = api.must("GET", "/api/negozi", token=sa)["negozi"]
        self.assertEqual([n["nome"] for n in negozi], ["Negozio principale"])
        nid = negozi[0]["id"]
        tipo = api.tipo(sa, "Operatore", L.OPS)
        api.utente(sa, "op1", tipo, nid)
        api.utente(sa, "op2", tipo, nid)
        t1, t2 = api.token("op1", "op1#Pw1"), api.token("op2", "op2#Pw1")

        # 4. i dati migrati sono tutti lì, e giusti
        cons, sq, gio = self.check_dati_migrati(api, t1, data)

        # 5. operatività sui dati migrati
        nuova = api.must("POST", "/api/squadre", {"nome": "Nuova"}, t1)["squadre"][-1]["id"]
        gnew = [g for g in api.must("POST", "/api/giornate", {"data": "2026-12-24", "squadra_id": nuova}, t1)["giornate"]
                if g["data"] == "2026-12-24"][0]["id"]
        cnew = [c for c in api.must("POST", "/api/consegne", {"cognome": "Nuovo", "nome": "Cliente", "citta": "X",
                                                                "articoli": []}, t1)["consegne"] if c["cognome"] == "Nuovo"][0]["id"]
        attesa = [c["id"] for c in cons if c["stato"] == "in_attesa"][0]                  # una consegna migrata
        r = api.must("POST", f"/api/giornate/{gnew}/assegna", {"consegna_ids": [cnew, attesa]}, t1)
        self.assertEqual([g for g in r["giornate"] if g["id"] == gnew][0]["consegneIds"], [cnew, attesa])
        self.assertEqual({c["id"]: c["stato"] for c in r["consegne"]}[attesa], "da_confermare")
        r = api.must("PUT", f"/api/giornate/{gnew}/riordina", {"consegna_ids": [attesa, cnew]}, t1)
        self.assertEqual([g for g in r["giornate"] if g["id"] == gnew][0]["consegneIds"], [attesa, cnew])
        r = api.must("PUT", f"/api/giornate/{gnew}/consegne/{cnew}/completa", token=t1)
        self.assertEqual({c["id"]: c["stato"] for c in r["consegne"]}[cnew], "completata")
        # conflitto di versione tra due utenti sulla stessa consegna migrata
        c0 = [c for c in api.must("GET", "/api/consegne", token=t1)["consegne"] if c["id"] == "c3"][0]
        self.assertEqual(api.call("PUT", "/api/consegne/c3", {"versione": c0["versione"], "citta": "Uno"}, t1)[0], 200)
        self.assertEqual(api.call("PUT", "/api/consegne/c3", {"versione": c0["versione"], "citta": "Due"}, t2)[0], 409)
        # rimuovere dalla giornata riporta in attesa
        r = api.must("DELETE", f"/api/giornate/{gnew}/assegna/{attesa}", token=t1)
        self.assertEqual({c["id"]: c["stato"] for c in r["consegne"]}[attesa], "in_attesa")
        # le squadre usate da giornate non si eliminano (anche quelle create dalla migrazione)
        self.assertEqual(api.call("DELETE", f"/api/squadre/{nuova}", token=t1)[0], 409)
        non_ass = [s["id"] for s in sq if s["nome"] == "Non assegnata"][0]
        self.assertEqual(api.call("DELETE", f"/api/squadre/{non_ass}", token=t1)[0], 409)
        # svuotata e eliminata la giornata, la squadra si elimina
        api.must("DELETE", f"/api/giornate/{gnew}/assegna/{cnew}", token=t1)
        api.must("DELETE", f"/api/giornate/{gnew}", token=t1)
        api.must("DELETE", f"/api/squadre/{nuova}", token=t1)

        # 6. secondo negozio: isolamento
        nb = api.must("POST", "/api/negozi", {"nome": "Negozio B"}, sa)["negozio"]["id"]
        api.utente(sa, "opb", tipo, nb)
        tb = api.token("opb", "opb#Pw1")
        for coll in ("consegne", "giornate", "squadre"):
            self.assertEqual(api.must("GET", f"/api/{coll}", token=tb)[coll], [])
        self.assertEqual(api.call("PUT", "/api/consegne/c3", {"versione": 1, "citta": "X"}, tb)[0], 403)
        sqb = api.must("POST", "/api/squadre", {"nome": "SqB"}, tb)["squadre"][0]["id"]
        self.assertEqual(api.call("POST", "/api/giornate", {"data": "2026-01-01", "squadra_id": "sq1"}, tb)[0], 403)
        self.assertEqual(api.call("POST", "/api/giornate", {"data": "2026-01-01", "squadra_id": sqb}, t1)[0], 403)

        # 7. riavvio: i dati restano, le sessioni no
        antes = {c: len(api.must("GET", f"/api/{c}", token=t1)[c]) for c in ("consegne", "giornate", "squadre")}
        srv.restart()
        api = L.Api(srv.port)
        self.assertEqual(api.call("GET", "/api/consegne", token=t1)[0], 401)
        t1 = api.token("op1", "op1#Pw1")
        dopo = {c: len(api.must("GET", f"/api/{c}", token=t1)[c]) for c in ("consegne", "giornate", "squadre")}
        self.assertEqual(dopo, antes)
        api.token("superadmin", "Super#Pass2026")                                         # la nuova password è salva

        # 8. integrità dell'archivio
        srv.stop()
        self.assertEqual(L.check_integrity(L.dump_v2(denv)), [])


for _src in ("json", "postgres", "mysql", "file"):
    for _dst in L.BACKENDS:
        setattr(Matrice, f"test_{_src}_verso_{_dst}", (lambda s, d: lambda self: self.scenario(s, d))(_src, _dst))


@unittest.skipIf(SALTA, "TEST_INTEGRATION=0")
class CatenaV2(unittest.TestCase):
    """V2 → V2 tra i tre backend, andata e ritorno, su un sistema già in uso (utenti, tipi, dati operativi
    creati dal server vero): la copia deve essere identica e funzionante."""

    def percorso(self, ordine):
        tmp = tmpdir(self)
        data = L.v1_dataset(n_cons=10, n_giorn=4, per=2)
        s = L.bring_up(ordine[0], data, os.path.join(tmp, "0"))
        self.addCleanup(s["srv"].stop)
        api, t1 = s["api"], s["t1"]
        # un po' di vita in più rispetto ai dati migrati
        sqn = api.must("POST", "/api/squadre", {"nome": "Dopo la migrazione"}, t1)["squadre"][-1]["id"]
        api.must("POST", "/api/giornate", {"data": "2027-01-10", "squadra_id": sqn}, t1)
        api.must("POST", "/api/consegne", {"cognome": "Nuovo", "nome": "Dopo", "citta": "Y", "articoli": []}, t1)
        s["srv"].stop()
        prev = s["denv"]
        for n, kind in enumerate(ordine[1:], start=1):
            ref = L.dump_v2(prev)          # stato della sorgente di QUESTO passo (gli accessi aggiornano ultimo_accesso)
            self.assertEqual(L.check_integrity(ref), [])
            sub = os.path.join(tmp, str(n))
            os.makedirs(sub, exist_ok=True)
            dest = L.fresh_dest(kind, sub)
            rc, out = L.migrate({**dest, **L.as_source(prev, "v2"), "MIGRATE_OUT": os.path.join(sub, "export.json"),
                                 "MIGRATE_EXECUTE": "1"})
            self.assertEqual(rc, 0, f"{ordine[n - 1]} → {kind}:\n{out[-2500:]}")
            copia = L.dump_v2(dest)
            for coll in ref:
                self.assertEqual(senza_versione(copia[coll]), senza_versione(ref[coll]), f"{ordine[n - 1]} → {kind}: {coll}")
            self.assertEqual(L.check_integrity(copia), [])
            # la copia funziona: server vero, stesse credenziali (nessun reset), stessi dati
            srv = L.ServerProc(dest, sub).start()
            self.addCleanup(srv.stop)
            a = L.Api(srv.port)
            a.token("superadmin", "Super#Pass2026")
            tok = a.token("op1", "op1#Pw1")
            self.assertEqual(len(a.must("GET", "/api/consegne", token=tok)["consegne"]), len(ref["consegne"]))
            self.assertEqual(len(a.must("GET", "/api/giornate", token=tok)["giornate"]), len(ref["giornate"]))
            srv.stop()
            prev = dest

    def test_json_postgres_mysql_json(self):
        self.percorso(("json", "postgres", "mysql", "json"))

    def test_json_mysql_postgres_json(self):
        self.percorso(("json", "mysql", "postgres", "json"))
