"""
Robustezza sul sistema vero (server.py come processo, backend vero): concorrenza, protezioni all'avvio,
base dati grande. Ogni classe gira su json, PostgreSQL e MySQL. Si salta con TEST_INTEGRATION=0.
"""
import os
import shutil
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

import integrazione_lib as L

SALTA = os.environ.get("TEST_INTEGRATION", "1") == "0"


def tmpdir(test):
    d = tempfile.mkdtemp(prefix="gc_int_")
    test.addCleanup(shutil.rmtree, d, True)
    return d


def parallelo(fn, args, workers=8):
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, args))


@unittest.skipIf(SALTA, "TEST_INTEGRATION=0")
class Concorrenza(unittest.TestCase):

    def avvia(self, dst):
        tmp = tmpdir(self)
        self.s = L.bring_up(dst, L.v1_dataset(n_cons=10, n_giorn=4, per=2), tmp)
        self.addCleanup(self.s["srv"].stop)
        self.api, self.t1, self.t2 = self.s["api"], self.s["t1"], self.s["t2"]

    def lista(self, coll, tok=None):
        return self.api.must("GET", f"/api/{coll}", token=tok or self.t1)[coll]

    def senza_errori_nel_log(self):
        log = self.s["srv"].log_tail(400)
        self.assertNotIn("Traceback", log)
        self.assertNotIn("Errore interno", log)

    def conflitto_sulla_stessa_consegna(self, dst):
        self.avvia(dst)
        c = [x for x in self.lista("consegne") if x["id"] == "c8"][0]

        def put(i):
            tok = (self.t1, self.t2)[i % 2]
            return i, self.api.call("PUT", "/api/consegne/c8", {"versione": c["versione"], "citta": f"Citta{i}"}, tok)[0]
        esiti = parallelo(put, range(10), workers=10)
        vincitori = [i for i, code in esiti if code == 200]
        self.assertEqual(len(vincitori), 1, esiti)                                 # ne vince una sola
        self.assertEqual(sorted(code for _, code in esiti if code != 200), [409] * 9)
        finale = [x for x in self.lista("consegne") if x["id"] == "c8"][0]
        self.assertEqual(finale["versione"], c["versione"] + 1)
        self.assertEqual(finale["citta"], f"Citta{vincitori[0]}")                  # e il valore è quello del vincitore
        self.senza_errori_nel_log()

    def creazioni_parallele(self, dst):
        self.avvia(dst)
        prima = len(self.lista("consegne"))

        def crea(i):
            return self.api.call("POST", "/api/consegne", {"cognome": f"Par{i}", "nome": "X", "citta": "Z", "articoli": []},
                                 (self.t1, self.t2)[i % 2])[0]
        self.assertEqual(parallelo(crea, range(30), workers=10), [201] * 30)
        dopo = self.lista("consegne")
        self.assertEqual(len(dopo), prima + 30)
        self.assertEqual(len({c["id"] for c in dopo}), prima + 30)                 # nessun id doppio, nessuna perdita
        self.assertEqual(len([c for c in dopo if c["cognome"].startswith("Par")]), 30)
        self.senza_errori_nel_log()

    def assegnazioni_parallele(self, dst):
        self.avvia(dst)
        sq = self.lista("squadre")[0]["id"]
        gid = [g for g in self.api.must("POST", "/api/giornate", {"data": "2027-03-03", "squadra_id": sq}, self.t1)["giornate"]
               if g["data"] == "2027-03-03"][0]["id"]
        nuove = []
        for i in range(20):
            r = self.api.must("POST", "/api/consegne", {"cognome": f"As{i}", "nome": "X", "citta": "Z", "articoli": []}, self.t1)
            nuove.append([c for c in r["consegne"] if c["cognome"] == f"As{i}"][0]["id"])

        def assegna(k):
            return self.api.call("POST", f"/api/giornate/{gid}/assegna", {"consegna_ids": nuove[k * 2:k * 2 + 2]},
                                 (self.t1, self.t2)[k % 2])[0]
        self.assertEqual(parallelo(assegna, range(10), workers=10), [200] * 10)
        g = [x for x in self.lista("giornate") if x["id"] == gid][0]
        self.assertEqual(sorted(g["consegneIds"]), sorted(nuove))                  # tutte, una volta sola
        self.assertEqual(len(g["consegneIds"]), 20)
        stati = {c["id"]: c["stato"] for c in self.lista("consegne")}
        self.assertEqual({stati[c] for c in nuove}, {"da_confermare"})
        self.senza_errori_nel_log()

    def eliminazioni_parallele(self, dst):
        self.avvia(dst)
        cid = [c for c in self.api.must("POST", "/api/consegne", {"cognome": "Del", "nome": "X", "citta": "Z", "articoli": []},
                                        self.t1)["consegne"] if c["cognome"] == "Del"][0]["id"]
        esiti = parallelo(lambda i: self.api.call("DELETE", f"/api/consegne/{cid}", token=(self.t1, self.t2)[i % 2])[0],
                          range(8), workers=8)
        self.assertTrue(set(esiti) <= {200, 404}, esiti)                           # mai un errore del server
        self.assertIn(200, esiti)
        self.assertNotIn(cid, [c["id"] for c in self.lista("consegne")])
        self.senza_errori_nel_log()

    def login_paralleli(self, dst):
        self.avvia(dst)
        risultati = parallelo(lambda i: self.api.login(("op1", "op2")[i % 2], ("op1#Pw1", "op2#Pw1")[i % 2]), range(12))
        self.assertEqual({code for code, _ in risultati}, {200})
        self.assertEqual(len({d["token"] for _, d in risultati}), 12)
        self.senza_errori_nel_log()

    def letture_durante_le_scritture(self, dst):
        self.avvia(dst)
        stop = []

        def scrivi(i):
            return self.api.call("POST", "/api/consegne", {"cognome": f"W{i}", "nome": "X", "citta": "Z", "articoli": []}, self.t1)[0]

        def leggi(_):
            visti, errori = [], 0
            while not stop:
                code, d = self.api.call("GET", "/api/consegne", token=self.t2)
                if code != 200:
                    errori += 1
                else:
                    visti.append(len(d["consegne"]))
            return visti, errori
        with ThreadPoolExecutor(max_workers=8) as ex:
            lettori = [ex.submit(leggi, i) for i in range(3)]
            esiti = list(ex.map(scrivi, range(25)))
            stop.append(1)
            risultati = [f.result() for f in lettori]
        self.assertEqual(set(esiti), {201})
        for visti, errori in risultati:
            self.assertEqual(errori, 0)
            self.assertEqual(visti, sorted(visti), "una lettura ha visto meno consegne di una precedente")
        self.assertEqual(len(self.lista("consegne")), 10 + 25)
        self.senza_errori_nel_log()


for _d in L.BACKENDS:
    for _n in ("conflitto_sulla_stessa_consegna", "creazioni_parallele", "assegnazioni_parallele",
               "eliminazioni_parallele", "login_paralleli", "letture_durante_le_scritture"):
        setattr(Concorrenza, f"test_{_n}_{_d}", (lambda n, d: lambda self: getattr(self, n)(d))(_n, _d))


@unittest.skipIf(SALTA, "TEST_INTEGRATION=0")
class Protezioni(unittest.TestCase):
    """Il server e la migrazione si rifiutano di toccare ciò che non sono una V2 valida e vuota."""

    def v1_nella_destinazione(self, dst):
        tmp = tmpdir(self)
        denv = L.fresh_dest(dst, tmp)
        data = L.v1_dataset(n_cons=4, n_giorn=2, per=2)
        if dst == "json":
            L.write_v1_dir(denv["DATA_DIR"], data)
        else:
            L.dbtool("v1-write", denv, data)
        rc, log = L.ServerProc.exit_code(denv, tmp)
        self.assertEqual(rc, 2, log)                                               # il server non parte
        self.assertIn("migrate.py", log)
        src = L.prepare_v1_source("json", tmp, data)
        rc, out = L.migrate({**denv, **src, "MIGRATE_EXECUTE": "1", "MIGRATE_OUT": os.path.join(tmp, "e.json")})
        self.assertEqual(rc, 2, out)                                               # e la migrazione non ci scrive
        self.assertIn("V2 vuota", out)

    def migrazione_interrotta(self, dst):
        tmp = tmpdir(self)
        s = L.bring_up(dst, L.v1_dataset(n_cons=4, n_giorn=2, per=2), tmp)
        s["srv"].stop()
        L.dbtool("set-flag", s["denv"])                                            # come dopo una migrazione interrotta
        rc, log = L.ServerProc.exit_code(s["denv"], tmp)
        self.assertEqual(rc, 2, log)
        self.assertIn("igrazione", log)
        src = L.prepare_v1_source("json", tmp, L.v1_dataset(n_cons=4, n_giorn=2, per=2))
        rc, out = L.migrate({**s["denv"], **src, "MIGRATE_EXECUTE": "1", "MIGRATE_OUT": os.path.join(tmp, "e2.json")})
        self.assertEqual(rc, 2, out)
        self.assertIn("interrotta", out)

    def destinazione_gia_usata_dal_server(self, dst):
        tmp = tmpdir(self)
        denv = L.fresh_dest(dst, tmp)
        s = L.ServerProc(denv, tmp).start()                                        # un avvio di prova crea il superadmin
        s.stop()
        src = L.prepare_v1_source("json", tmp, L.v1_dataset(n_cons=4, n_giorn=2, per=2))
        rc, out = L.migrate({**denv, **src, "MIGRATE_EXECUTE": "1", "MIGRATE_OUT": os.path.join(tmp, "e3.json")})
        self.assertEqual(rc, 2, out)
        self.assertIn("non è vuota", out)
        self.assertEqual([u["id"] for u in L.dump_v2(denv)["utenti"]], ["u_superadmin"])     # intatta


for _d in L.BACKENDS:
    for _n in ("v1_nella_destinazione", "migrazione_interrotta", "destinazione_gia_usata_dal_server"):
        setattr(Protezioni, f"test_{_n}_{_d}", (lambda n, d: lambda self: getattr(self, n)(d))(_n, _d))


@unittest.skipIf(SALTA, "TEST_INTEGRATION=0")
class BaseDatiGrande(unittest.TestCase):
    """5.000 consegne e 500 giornate: la migrazione (con la verifica di ogni record), il server e l'integrità."""

    N_CONS, N_GIORN, PER = 5000, 500, 10

    def grande(self, dst):
        tmp = tmpdir(self)
        data = L.v1_dataset(n_cons=self.N_CONS, n_giorn=self.N_GIORN, per=self.PER)
        s = L.bring_up(dst, data, tmp)
        self.addCleanup(s["srv"].stop)
        self.assertIn("Verifica superata", s["migrate_out"])
        api, t1 = s["api"], s["t1"]
        t0 = time.time()
        cons = api.must("GET", "/api/consegne", token=t1)["consegne"]
        gio = api.must("GET", "/api/giornate", token=t1)["giornate"]
        t_lettura = time.time() - t0
        self.assertEqual(len(cons), self.N_CONS)
        self.assertEqual(len(gio), self.N_GIORN)
        self.assertEqual(sum(len(g["consegneIds"]) for g in gio), self.N_CONS)
        sq = api.must("GET", "/api/squadre", token=t1)["squadre"]
        self.assertEqual(sorted(s_["nome"] for s_ in sq), ["Ghost", "Non assegnata", "Squadra A", "Squadra B"])
        t0 = time.time()
        r = api.must("POST", "/api/consegne", {"cognome": "Dopo", "nome": "X", "citta": "Z", "articoli": []}, t1)
        t_scrittura = time.time() - t0
        self.assertEqual(len(r["consegne"]), self.N_CONS + 1)
        s["srv"].stop()
        self.assertEqual(L.check_integrity(L.dump_v2(s["denv"])), [])
        print(f"\n[prestazioni {dst}] migrazione {s['migrate_seconds']:.1f}s · lettura di consegne+giornate {t_lettura:.2f}s · "
              f"scrittura con risposta completa {t_scrittura:.2f}s", flush=True)
        self.assertLess(s["migrate_seconds"], 600)


for _d in L.BACKENDS:
    setattr(BaseDatiGrande, f"test_grande_{_d}", (lambda d: lambda self: self.grande(d))(_d))
