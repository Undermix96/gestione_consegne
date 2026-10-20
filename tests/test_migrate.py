"""
Test di migrate.py: migrazione V1 → V2 e tra backend, convalida, protezioni, verifica.

Parte "pura" (senza database, solo con DB_BACKEND=json) e parte da un capo all'altro: migrate.py viene
lanciato come processo, con variabili d'ambiente diverse per sorgente e destinazione, come fa
l'utente da compose, da `docker run` o dalla GUI. La destinazione "di processo" è il backend scelto con
DB_BACKEND (json in una cartella temporanea, oppure il database di test); le sorgenti e le destinazioni
json sono sempre cartelle temporanee.

ATTENZIONE: con i backend DB la suite SVUOTA le tabelle del database di test (DB_NAME deve finire per _test).
Solo libreria standard.
"""
import copy
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

os.environ["STORAGE_ALLOW_TEST_RESET"] = "1"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

import storage as st  # noqa: E402
import migrate  # noqa: E402

BACKEND = st.BACKEND
MIGRATE = os.path.join(ROOT, "migrate.py")
SQL = BACKEND in ("mysql", "postgres")


def setUpModule():
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)


# ─── fixture V1 ───────────────────────────────────────────────────────────────

V1 = {
    "squadre": [
        {"id": "sq1", "nome": "Squadra A", "colorIdx": 2},
        {"id": "sq2", "nome": "Squadra B", "colorIdx": 5},
    ],
    "consegne": [
        {"id": "c1", "dataPrenotazione": "2026-03-22", "stato": "programmata", "nome": "Mario", "cognome": "Rossi",
         "citta": "Vicenza", "indirizzo": "Via Roma 1", "tel1": "+39 333 1234567", "tel2": "", "raee": "no",
         "articoli": [{"tipoConsegna": "ins_incasso", "tipo": "TV", "codice": "SONY-X90L", "desc": 'TV 55" àèìòù €'}],
         "piano": "2", "noteAbitazione": "Scala stretta", "preferenzePeriodo": "Solo mattina",
         "giornoConsegna": "2026-03-25", "fasciaOraria": "9:00-12:00", "note": "", "campoFuturo": {"x": [1, 2]}},
        {"id": "c2", "dataPrenotazione": "2026-03-23", "stato": "da_confermare", "nome": "Anna", "cognome": "Verdi",
         "citta": "Padova", "indirizzo": "Via Po 3", "articoli": [], "giornoConsegna": "2026-03-25"},
        {"id": "c3", "dataPrenotazione": "2026-03-24", "stato": "in_attesa", "nome": "Luca", "cognome": "Bianchi",
         "citta": "Verona", "articoli": []},
    ],
    "giornate": [
        {"id": "g1", "data": "2026-03-25", "squadra": "Squadra A", "consegneIds": ["c2", "c1"]},
        {"id": "g2", "data": "2026-03-26", "squadra": "", "consegneIds": []},
    ],
}


def write_v1_dir(path, data=None):
    data = V1 if data is None else data
    os.makedirs(path, exist_ok=True)
    for coll in migrate.COLLECTIONS_V1:
        with open(os.path.join(path, f"{coll}.json"), "w", encoding="utf-8") as f:
            json.dump(data[coll], f, ensure_ascii=False)


def dir_digest(path):
    h = hashlib.sha256()
    for root, _, files in sorted(os.walk(path)):
        for name in sorted(files):
            p = os.path.join(root, name)
            h.update(os.path.relpath(p, path).encode())
            with open(p, "rb") as f:
                h.update(f.read())
    return h.hexdigest()


def read_json_dir(path):
    out = {}
    for coll in migrate.COLLECTIONS_V2:
        p = os.path.join(path, f"{coll}.json")
        with open(p, "r", encoding="utf-8") as f:
            out[coll] = json.load(f)
    with open(os.path.join(path, "meta.json"), "r", encoding="utf-8") as f:
        out["_meta"] = json.load(f)
    return out


def strip_versione(recs):
    return [{k: v for k, v in r.items() if k != "versione"} for r in recs]


# ─── parte pura ───────────────────────────────────────────────────────────────

@unittest.skipUnless(BACKEND == "json", "logica pura: non dipende dal backend")
class TestPure(unittest.TestCase):

    def test_normalize_sql_v1(self):
        raw = {"consegne": [{"id": "c", "tipo_prodotto": None, "giorno_consegna": "2026-01-02", "fascia_oraria": "9-12",
                              "data_prenotaz": "2026-01-01", "tipo_consegna": "consegna", "telefono": None, "note": "",
                              "articoli": [{"a": 1}], "tel1": "1"}],
               "squadre": [{"id": "s", "nome": "S", "color_idx": 4}],
               "giornate": [{"id": "g", "data": "2026-01-02", "squadra": None, "consegneIds": ["c"],
                             "consegneCompletate": {"c": False}}]}
        out = migrate.normalize_sql_v1(raw)
        self.assertEqual(out["consegne"], [{"id": "c", "giornoConsegna": "2026-01-02", "fasciaOraria": "9-12",
                                            "dataPrenotazione": "2026-01-01", "tipoConsegna": "consegna", "note": "",
                                            "articoli": [{"a": 1}], "tel1": "1"}])
        self.assertEqual(out["squadre"], [{"id": "s", "nome": "S", "colorIdx": 4}])
        self.assertEqual(out["giornate"], [{"id": "g", "data": "2026-01-02", "consegneIds": ["c"]}])

    def plan(self, data=None, drop=True, kind="v1"):
        rep = migrate.Report()
        plan = migrate.build_plan(kind, copy.deepcopy(V1 if data is None else data), "Negozio principale", drop, rep)
        return plan, rep

    def test_build_plan_v1(self):
        plan, rep = self.plan()
        nid = plan["negozi"][0]["id"]
        self.assertEqual(plan["negozi"][0]["nome"], "Negozio principale")
        self.assertEqual([u["id"] for u in plan["utenti"]], ["u_superadmin"])
        self.assertTrue(plan["utenti"][0]["is_superadmin"])
        for coll in migrate.COLLECTIONS_V1:
            self.assertTrue(all(r["negozio_id"] == nid for r in plan[coll]), coll)
        self.assertEqual([c["id"] for c in plan["consegne"]], ["c1", "c2", "c3"])       # id conservati, ordine invariato
        self.assertEqual(plan["giornate"][0]["consegneIds"], ["c2", "c1"])
        self.assertEqual(plan["giornate"][0]["squadra_id"], "sq1")                       # il nome diventa l'id
        self.assertNotIn("squadra", plan["giornate"][0])
        self.assertEqual([s["nome"] for s in plan["squadre"]], ["Squadra A", "Squadra B", "Non assegnata"])
        na = plan["squadre"][2]
        self.assertEqual(plan["giornate"][1]["squadra_id"], na["id"])                    # g2 non aveva squadra
        self.assertEqual((na["negozio_id"], na["colorIdx"]), (nid, 2))
        self.assertEqual(rep.errors, [])

    def test_orfani_e_doppioni(self):
        data = copy.deepcopy(V1)
        data["giornate"][0]["consegneIds"] = ["c1", "ghost", "c1", "c2"]
        plan, rep = self.plan(data)
        self.assertEqual(plan["giornate"][0]["consegneIds"], ["c1", "c2"])
        self.assertEqual(len(rep.warnings), 2)
        self.assertEqual(rep.errors, [])
        plan, rep = self.plan(data, drop=False)
        self.assertEqual(len(rep.errors), 1)

    def test_non_assegnata_solo_se_necessaria(self):
        data = copy.deepcopy(V1)
        data["giornate"][1]["squadra"] = "Squadra B"
        plan, rep = self.plan(data)
        self.assertEqual([s["nome"] for s in plan["squadre"]], ["Squadra A", "Squadra B"])    # nessuna squadra in più
        self.assertEqual([g["squadra_id"] for g in plan["giornate"]], ["sq1", "sq2"])
        self.assertTrue(any("nessuna squadra 'non assegnata'" in n for n in rep.notes))
        # senza giornate non serve nemmeno
        data["giornate"] = []
        plan, rep = self.plan(data)
        self.assertEqual(len(plan["squadre"]), 2)

    def test_non_assegnata_per_nome_assente_o_vuoto_e_riuso(self):
        data = copy.deepcopy(V1)
        data["giornate"] = [{"id": "ga", "data": "2026-01-01", "consegneIds": []},                 # chiave assente
                            {"id": "gb", "data": "2026-01-02", "squadra": "   ", "consegneIds": []},
                            {"id": "gc", "data": "2026-01-03", "squadra": None, "consegneIds": []}]
        plan, rep = self.plan(data)
        self.assertEqual(len([s for s in plan["squadre"] if s["nome"] == "Non assegnata"]), 1)  # una sola, creata una volta
        self.assertEqual(len({g["squadra_id"] for g in plan["giornate"]}), 1)
        self.assertTrue(any("3 giornate senza squadra" in n for n in rep.notes))
        # se esiste già una squadra con quel nome (anche con maiuscole diverse) si riusa
        data["squadre"].append({"id": "sq9", "nome": "NON ASSEGNATA", "colorIdx": 0})
        plan, rep = self.plan(data)
        self.assertEqual(len(plan["squadre"]), 3)
        self.assertEqual({g["squadra_id"] for g in plan["giornate"]}, {"sq9"})
        # nome personalizzato
        rep2 = migrate.Report()
        plan = migrate.build_plan("v1", copy.deepcopy(V1), "N", True, rep2, non_assegnata="Da definire")
        self.assertEqual(plan["squadre"][-1]["nome"], "Da definire")

    def test_nomi_squadra_ambigui_o_mancanti(self):
        data = copy.deepcopy(V1)
        data["squadre"].append({"id": "sq3", "nome": "Squadra A", "colorIdx": 1})               # nome doppio
        data["giornate"] = [{"id": "g1", "data": "2026-01-01", "squadra": "Squadra A", "consegneIds": []},
                            {"id": "g2", "data": "2026-01-02", "squadra": " squadra b ", "consegneIds": []},
                            {"id": "g3", "data": "2026-01-03", "squadra": "Squadra Fantasma", "consegneIds": []}]
        plan, rep = self.plan(data)
        ids = {g["id"]: g["squadra_id"] for g in plan["giornate"]}
        self.assertEqual(ids["g1"], "sq1")                                                      # la prima
        self.assertEqual(ids["g2"], "sq2")                                                      # senza maiuscole/spazi
        creata = [s for s in plan["squadre"] if s["nome"] == "Squadra Fantasma"]
        self.assertEqual(len(creata), 1)                                                        # mancante: creata
        self.assertEqual(ids["g3"], creata[0]["id"])
        text = "\n".join(rep.warnings)
        self.assertIn("stesso nome", text)
        self.assertIn("maiuscole o spazi", text)
        self.assertIn("creata", text)
        self.assertFalse(any(s["nome"] == "Non assegnata" for s in plan["squadre"]))
        migrate.validate_plan(plan, rep)
        self.assertEqual(rep.errors, [])

    def test_squadra_non_testo(self):
        data = copy.deepcopy(V1)
        data["giornate"][0]["squadra"] = 5
        plan, rep = self.plan(data)
        self.assertTrue(any("non è un testo" in e for e in rep.errors))

    def test_v2_giornata_senza_squadra_id_o_con_vecchio_campo(self):
        data = {c: [] for c in migrate.COLLECTIONS_V2}
        data["negozi"] = [{"id": "n1", "nome": "N"}]
        data["giornate"] = [{"id": "g1", "negozio_id": "n1", "data": "2026-01-01", "consegneIds": []},
                            {"id": "g2", "negozio_id": "n1", "data": "2026-01-02", "squadra": "A", "consegneIds": []}]
        plan, rep = self.plan(data, kind="v2")
        migrate.validate_plan(plan, rep)
        text = "\n".join(rep.errors)
        self.assertIn("squadra_id", text)
        self.assertIn("vecchio campo 'squadra'", text)

    def test_validazione_riporta_tutti_i_problemi(self):
        data = copy.deepcopy(V1)
        data["consegne"][0]["nome"] = 5                        # tipo sbagliato
        data["consegne"][1]["id"] = "c1"                       # id duplicato
        data["squadre"].append({"nome": "senza id"})
        data["consegne"][2]["stato"] = "boh"                   # solo avviso
        plan, rep = self.plan(data)
        migrate.validate_plan(plan, rep)
        text = "\n".join(rep.errors)
        self.assertIn("nome", text)
        self.assertIn("duplicato", text)
        self.assertIn("senza 'id'", text)
        self.assertEqual(len(rep.errors), 3)
        self.assertTrue(any("boh" in w for w in rep.warnings))

    def test_validazione_ok_sui_dati_di_prova(self):
        plan, rep = self.plan()
        migrate.validate_plan(plan, rep)
        self.assertEqual(rep.errors, [])

    def test_plan_v2_toglie_versione_e_none(self):
        data = {c: [] for c in migrate.COLLECTIONS_V2}
        data["negozi"] = [{"id": "n1", "nome": "N", "creato_il": None, "versione": 7}]
        plan, rep = self.plan(data, kind="v2")
        self.assertEqual(plan["negozi"], [{"id": "n1", "nome": "N"}])

    def test_validazione_v2_riferimenti_e_unicita(self):
        data = {c: [] for c in migrate.COLLECTIONS_V2}
        data["negozi"] = [{"id": "n1", "nome": "N"}]
        data["utenti"] = [{"id": "u1", "username": "Mario", "password_hash": "h", "negozio_id": "n1"},
                          {"id": "u2", "username": "mario", "password_hash": "h", "negozio_id": "nX"}]
        data["consegne"] = [{"id": "c1", "negozio_id": "n1"}]
        data["giornate"] = [{"id": "g1", "data": "2026-01-01", "negozio_id": "nZ", "consegneIds": ["c1"]}]
        plan, rep = self.plan(data, kind="v2")
        migrate.validate_plan(plan, rep)
        text = "\n".join(rep.errors)
        self.assertIn("duplicato per 'username'", text)
        self.assertIn("negozio_id='nX'", text)
        self.assertIn("negozio_id='nZ'", text)
        self.assertIn("appartiene a un altro negozio", text)


# ─── da un capo all'altro ─────────────────────────────────────────────────────

def sql_wipe():
    """Svuota il database di test (anche le tabelle V1): solo se il nome finisce per _test."""
    name = os.environ.get("DB_NAME", "")
    assert name.endswith("_test"), "rifiuto di cancellare un database che non è di test"
    if BACKEND == "postgres":
        conn = st._pg_connect()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("DROP SCHEMA public CASCADE")
        cur.execute("CREATE SCHEMA public")
    else:
        conn = st._mysql_connect()
        cur = conn.cursor()
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute("SHOW TABLES")
        for (t,) in cur.fetchall():
            cur.execute(f"DROP TABLE `{t}`")
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
    cur.close()
    conn.close()


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gc_mig_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = os.path.join(self.tmp, "src")          # sorgente V1 json
        write_v1_dir(self.src)
        self.mig = os.path.join(self.tmp, "migration")    # file di esportazione
        self.old_dir = st.DATA_DIR
        self.addCleanup(setattr, st, "DATA_DIR", self.old_dir)
        if SQL:
            st.init_storage_v2()
            st._test_reset()                              # destinazione di processo: V2 vuota
            self.dest = None
        else:
            self.dest = os.path.join(self.tmp, "dest")
            os.makedirs(self.dest)
            st.DATA_DIR = self.dest

    # ── esecuzione ──
    def env(self, **over):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("SRC_", "MIGRATE_"))}
        e.update({"SRC_BACKEND": "json", "SRC_DATA_DIR": self.src, "MIGRATE_OUT": os.path.join(self.mig, "exp.json")})
        if not SQL:
            e.update({"DB_BACKEND": "json", "DATA_DIR": self.dest})
        e.update(over)
        return {k: v for k, v in e.items() if v is not None}

    def migrate(self, *args, **over):
        p = subprocess.run([sys.executable, "-B", MIGRATE, *args], env=self.env(**over),
                           capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def json_dest(self, name="dest2"):
        """Destinazione json indipendente dal backend di processo."""
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        return d, {"DB_BACKEND": "json", "DATA_DIR": d}

    def read_dest(self):
        """Contenuto della destinazione di processo (storage V2)."""
        st.init_storage_v2()
        return {c: st.list_records(c) for c in migrate.COLLECTIONS_V2}

    # ── controlli ──
    def assert_v1_migrated(self, data, check_flag=True):
        neg = data["negozi"]
        self.assertEqual([n["nome"] for n in neg], ["Negozio principale"])
        nid = neg[0]["id"]
        self.assertEqual([u["id"] for u in data["utenti"]], ["u_superadmin"])
        self.assertEqual(data["tipi_account"], [])
        for coll in migrate.COLLECTIONS_V1:
            exp = V1[coll]
            got = {r["id"]: r for r in data[coll]}
            self.assertEqual([r["id"] for r in data[coll]][:len(exp)], [r["id"] for r in exp], coll)   # ordine di inserimento
            for e in exp:
                g = got[e["id"]]
                for k, v in e.items():
                    if coll == "giornate" and k == "squadra":
                        continue                                           # diventa squadra_id (controllato sotto)
                    self.assertEqual(g.get(k), v, f"{coll} {e['id']} campo {k}")
                if coll == "giornate":
                    self.assertNotIn("squadra", g)
                self.assertEqual(g["negozio_id"], nid)
                if coll != "giornate" or "versione" in g:
                    self.assertEqual(g.get("versione"), 1)
        g = {r["id"]: r for r in data["giornate"]}
        self.assertEqual(g["g1"]["consegneIds"], ["c2", "c1"])             # ordine delle consegne conservato
        # la squadra è un riferimento: g1 → sq1 (per nome); g2 non ne aveva → "Non assegnata", creata apposta
        sq = {s["nome"]: s for s in data["squadre"]}
        self.assertEqual(sorted(sq), ["Non assegnata", "Squadra A", "Squadra B"])
        self.assertEqual(g["g1"]["squadra_id"], "sq1")
        self.assertEqual(g["g2"]["squadra_id"], sq["Non assegnata"]["id"])
        self.assertEqual(sq["Non assegnata"]["negozio_id"], nid)


class TestMigrazioneV1(Base):

    def test_senza_execute_non_scrive_nulla(self):
        digest = dir_digest(self.src)
        code, out = self.migrate()
        self.assertEqual(code, 0, out)
        self.assertIn("Nulla è stato scritto", out)
        self.assertIn("ESITO: OK", out)
        self.assertEqual(dir_digest(self.src), digest)
        if SQL:
            self.assertEqual({c: n for c, n in migrate.classify_destination(st)["counts"].items() if n}, {})
        else:
            self.assertEqual(os.listdir(self.dest), [])                    # nemmeno il marcatore
        self.assertTrue(os.path.exists(os.path.join(self.mig, "exp.json")))   # il backup viene comunque scritto

    def test_migrazione_completa(self):
        digest = dir_digest(self.src)
        code, out = self.migrate(MIGRATE_EXECUTE="1")
        self.assertEqual(code, 0, out)
        self.assertIn("Verifica superata", out)
        self.assertIn("ESITO: OK — migrazione completata", out)
        self.assertEqual(dir_digest(self.src), digest)                     # la sorgente non è mai modificata
        data = self.read_dest()                                            # l'avvio del server riesce (flag spento)
        self.assert_v1_migrated(data)
        self.assertFalse(st.get_meta(migrate.FLAG))
        with open(os.path.join(self.mig, "exp.json"), encoding="utf-8") as f:
            exp = json.load(f)
        self.assertEqual((exp["format"], exp["kind"]), (migrate.EXPORT_FORMAT, "v1"))
        self.assertEqual(exp["dati"]["consegne"], V1["consegne"])          # il file è il backup fedele
        import server as srv
        srv.ensure_superadmin()                                            # il server non ne crea un secondo
        self.assertEqual(len(st.list_records("utenti")), 1)

    def test_nessuna_squadra_non_assegnata_se_non_serve(self):
        data = copy.deepcopy(V1)
        data["giornate"][1]["squadra"] = "Squadra B"
        write_v1_dir(self.src, data)
        code, out = self.migrate("--execute")
        self.assertEqual(code, 0, out)
        self.assertIn("nessuna squadra 'non assegnata' necessaria", out)
        d = self.read_dest()
        self.assertEqual(sorted(s["nome"] for s in d["squadre"]), ["Squadra A", "Squadra B"])
        self.assertEqual({g["id"]: g["squadra_id"] for g in d["giornate"]}, {"g1": "sq1", "g2": "sq2"})

    def test_nome_personalizzato_della_squadra_non_assegnata(self):
        code, out = self.migrate("--execute", MIGRATE_SQUADRA_NON_ASSEGNATA="Da definire")
        self.assertEqual(code, 0, out)
        self.assertIn("Da definire", out)
        self.assertEqual(sorted(s["nome"] for s in self.read_dest()["squadre"]), ["Da definire", "Squadra A", "Squadra B"])

    def test_argomenti_al_posto_delle_variabili(self):
        code, out = self.migrate("run", "--execute", "--negozio-nome", "Sede di prova")
        self.assertEqual(code, 0, out)
        self.assertEqual([n["nome"] for n in self.read_dest()["negozi"]], ["Sede di prova"])

    def test_seconda_esecuzione_rifiutata(self):
        self.assertEqual(self.migrate(MIGRATE_EXECUTE="1")[0], 0)
        before = self.read_dest()
        code, out = self.migrate(MIGRATE_EXECUTE="1")
        self.assertEqual(code, 2, out)
        self.assertIn("non è vuota", out)
        self.assertIn("ESITO: FALLITO", out)
        self.assertEqual(self.read_dest(), before)
        code, out = self.migrate()                                         # anche nel solo rapporto (senza --execute)
        self.assertEqual(code, 2, out)
        self.assertIn("non è vuota", out)

    def test_esporta_poi_importa(self):
        code, out = self.migrate("export")
        self.assertEqual(code, 0, out)
        exp = os.path.join(self.mig, "exp.json")
        self.assertTrue(os.path.exists(exp))
        if SQL:
            self.assertEqual({c: n for c, n in migrate.classify_destination(st)["counts"].items() if n}, {})
        else:
            self.assertEqual(os.listdir(self.dest), [])
        code, out = self.migrate("import", "--execute", "--in", exp)
        self.assertEqual(code, 0, out)
        self.assert_v1_migrated(self.read_dest())
        code, out = self.migrate("import")                                # senza file
        self.assertEqual(code, 3, out)

    def test_sorgente_uguale_alla_destinazione(self):
        if SQL:
            code, out = self.migrate(SRC_BACKEND=BACKEND, SRC_DB_NAME=os.environ["DB_NAME"],
                                     SRC_DB_HOST=os.environ.get("DB_HOST"), SRC_DB_PORT=os.environ.get("DB_PORT"))
        else:
            code, out = self.migrate(SRC_DATA_DIR=self.dest)
        self.assertEqual(code, 2, out)
        self.assertIn("coincide con la destinazione", out)

    def test_destinazione_con_dati_v1_rifiutata(self):
        d, e = self.json_dest("v1dest")
        write_v1_dir(d)
        digest = dir_digest(d)
        code, out = self.migrate("--execute", **e)
        self.assertEqual(code, 2, out)
        self.assertIn("V2 vuota", out)
        self.assertEqual(dir_digest(d), digest)

    def test_destinazione_non_vuota_rifiutata(self):
        d, e = self.json_dest("v2dest")
        self.assertEqual(self.migrate("--execute", **e)[0], 0)
        digest = dir_digest(d)
        code, out = self.migrate("--execute", **e)
        self.assertEqual(code, 2, out)
        self.assertEqual(dir_digest(d), digest)

    def test_rapporto_con_tutti_i_problemi(self):
        bad = copy.deepcopy(V1)
        bad["consegne"][0]["nome"] = 5
        bad["consegne"][1]["id"] = "c1"
        bad["squadre"][1].pop("id")
        write_v1_dir(self.src, bad)
        code, out = self.migrate("--execute")
        self.assertEqual(code, 2, out)
        self.assertEqual(out.count("PROBLEMI"), 1)
        self.assertIn("duplicato", out)
        self.assertIn("senza 'id'", out)
        self.assertIn("nome", out)
        if SQL:
            self.assertEqual({c: n for c, n in migrate.classify_destination(st)["counts"].items() if n}, {})
        else:
            self.assertEqual(os.listdir(self.dest), [])

    def test_riferimenti_orfani(self):
        bad = copy.deepcopy(V1)
        bad["giornate"][0]["consegneIds"] = ["c2", "fantasma", "c1"]
        write_v1_dir(self.src, bad)
        code, out = self.migrate("--execute")
        self.assertEqual(code, 0, out)
        self.assertIn("fantasma", out)                                    # riportato nel rapporto
        self.assert_v1_migrated(self.read_dest())                         # ma scartato dai dati
        if not SQL:
            shutil.rmtree(self.dest)
            os.makedirs(self.dest)
        else:
            st.init_storage_v2()
            st._test_reset()
        code, out = self.migrate("--execute", MIGRATE_KEEP_ORPHANS="1")
        self.assertEqual(code, 2, out)
        self.assertIn("fantasma", out)

    def test_dati_json_della_versione_windows(self):
        legacy = os.path.join(self.tmp, "windows", "dati.json")
        os.makedirs(os.path.dirname(legacy))
        with open(legacy, "w", encoding="utf-8") as f:
            json.dump(V1, f, ensure_ascii=False)
        code, out = self.migrate("--execute", "--source-kind", "file", SRC_FILE=legacy)
        self.assertEqual(code, 0, out)
        self.assert_v1_migrated(self.read_dest())

    def test_sorgente_v2_scambiata_per_v1(self):
        d, e = self.json_dest("v2src")
        self.assertEqual(self.migrate("--execute", **e)[0], 0)
        code, out = self.migrate(SRC_DATA_DIR=d)                          # kind v1 su un archivio V2
        self.assertEqual(code, 2, out)
        self.assertIn("V2", out)

    def test_sorgente_inesistente_o_vuota(self):
        code, out = self.migrate(SRC_DATA_DIR=os.path.join(self.tmp, "non-esiste"))
        self.assertEqual(code, 3, out)
        os.makedirs(os.path.join(self.tmp, "vuota"))
        code, out = self.migrate(SRC_DATA_DIR=os.path.join(self.tmp, "vuota"))
        self.assertEqual(code, 3, out)
        self.assertIn("nessun dato V1", out)
        code, out = self.migrate("--source-kind", "file", SRC_FILE=os.path.join(self.tmp, "no.json"))
        self.assertEqual(code, 3, out)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "come root ogni cartella è scrivibile")
    def test_cartella_non_scrivibile(self):
        code, out = self.migrate("--execute", MIGRATE_OUT="/proc/non-scrivibile/exp.json")
        self.assertEqual(code, 3, out)
        self.assertIn("non è scrivibile", out)
        d = {"DB_BACKEND": "json", "DATA_DIR": "/proc/non-scrivibile"}
        code, out = self.migrate(**d)                                      # anche nel solo rapporto
        self.assertEqual(code, 3, out)
        self.assertIn("non è scrivibile", out)


class TestScambioTraBackend(Base):

    def test_v2_andata_e_ritorno(self):
        self.assertEqual(self.migrate("--execute")[0], 0)
        # arricchisce la V2 con dati che la V1 non ha: un tipo account e un utente
        st.init_storage_v2()
        neg = st.list_records("negozi")[0]
        st.insert_record("tipi_account", {"id": "ta_x", "nome": "Operatore", "permessi": ["consegne.leggi"]})
        st.insert_record("utenti", {"id": "u_mario", "username": "Mario", "password_hash": "a" * 64,
                                    "tipo_account_id": "ta_x", "negozio_id": neg["id"], "primo_login": False})
        original = self.read_dest()
        # V2 (backend di processo) → V2 json in un'altra cartella
        d, e = self.json_dest("copia")
        if SQL:
            src = {"SRC_BACKEND": BACKEND, "SRC_DB_NAME": os.environ["DB_NAME"]}
        else:
            src = {"SRC_BACKEND": "json", "SRC_DATA_DIR": self.dest}
        code, out = self.migrate("--execute", "--source-kind", "v2", **src, **e)
        self.assertEqual(code, 0, out)
        copy_ = read_json_dir(d)
        for coll in migrate.COLLECTIONS_V2:
            self.assertEqual(strip_versione(copy_[coll]), strip_versione(original[coll]), coll)
        self.assertFalse(copy_["_meta"].get(migrate.FLAG))
        # ... e di nuovo nel backend di processo (svuotato)
        if SQL:
            st.init_storage_v2()
            st._test_reset()
        else:
            shutil.rmtree(self.dest)
            os.makedirs(self.dest)
        code, out = self.migrate("--execute", "--source-kind", "v2", SRC_BACKEND="json", SRC_DATA_DIR=d)
        self.assertEqual(code, 0, out)
        back = self.read_dest()
        for coll in migrate.COLLECTIONS_V2:
            self.assertEqual(strip_versione(back[coll]), strip_versione(original[coll]), coll)

    def test_sorgente_v2_inesistente(self):
        code, out = self.migrate("--source-kind", "v2", SRC_DATA_DIR=self.src)   # è una V1, non una V2
        self.assertEqual(code, 2, out)
        self.assertIn("non è un archivio V2", out)

    @unittest.skipUnless(SQL, "sorgente V1 su database: solo con i backend SQL")
    def test_sorgente_v1_su_database(self):
        sql_wipe()
        self.addCleanup(sql_wipe)                                          # le altre suite ripartono da un database vuoto
        code_src = ("import json, sys, storage as s; s.init_storage(); "
                    "s.write_data(json.loads(sys.stdin.read()))")
        p = subprocess.run([sys.executable, "-B", "-c", code_src], input=json.dumps(V1), text=True,
                           capture_output=True, cwd=ROOT, env=dict(os.environ))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        d, e = self.json_dest("da_sql")
        code, out = self.migrate("--execute", SRC_BACKEND=BACKEND, SRC_DB_NAME=os.environ["DB_NAME"], **e)
        self.assertEqual(code, 0, out)
        data = read_json_dir(d)
        self.assert_v1_migrated({k: v for k, v in data.items() if k != "_meta"})

    @unittest.skipUnless(SQL, "creazione del database: solo con i backend SQL")
    def test_database_di_destinazione_mancante(self):
        name = "gestione_consegne_nuovo_test"
        code, out = self.migrate("--execute", DB_NAME=name)
        self.assertEqual(code, 3, out)
        self.assertIn("MIGRATE_CREATE_DB", out)
        code, out = self.migrate("--execute", "--create-db", DB_NAME=name)
        if BACKEND == "postgres":                                          # l'utente di test può creare database
            self.assertEqual(code, 0, out)
            conn = st._pg_connect()
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(f'DROP DATABASE "{name}"')
            conn.close()
        else:                                                              # su MySQL l'utente di test non può
            self.assertEqual(code, 3, out)
            self.assertIn("creazione del database", out)


class TestInterruzioni(Base):
    """Scrittura interrotta o verifica fallita: la destinazione resta marcata e il server non parte."""

    def payload(self):
        return {"format": migrate.EXPORT_FORMAT, "kind": "v1", "dati": copy.deepcopy(V1)}

    def reset_flagged(self):
        if SQL:
            st.init_storage_v2(ignore_migration=True)
            st.set_meta(migrate.FLAG, False)
            st._test_reset()

    def test_scrittura_interrotta(self):
        self.addCleanup(self.reset_flagged)
        orig = st.insert_records

        def failing(coll, recs):
            if coll == "giornate":
                raise st.StorageError("disco pieno (simulato)")
            return orig(coll, recs)
        st.insert_records = failing
        try:
            with self.assertRaises(migrate.MigrateError):
                migrate.run_import(self.payload(), True, "Negozio principale", True, False)
        finally:
            st.insert_records = orig
        with self.assertRaises(st.SchemaError):                           # il server si rifiuta di partire
            st.init_storage_v2()
        code, out = self.migrate("--execute")                              # e una nuova migrazione è rifiutata
        self.assertEqual(code, 2, out)
        self.assertIn("interrotta", out)

    def test_verifica_che_trova_una_differenza(self):
        self.addCleanup(self.reset_flagged)
        orig = migrate.write_plan

        def corrupting(plan):
            orig(plan)
            st.update_record("consegne", "c1", {"citta": "ALTRA CITTÀ"})
        migrate.write_plan = corrupting
        try:
            with self.assertRaises(migrate.MigrateError) as cm:
                migrate.run_import(self.payload(), True, "Negozio principale", True, False)
        finally:
            migrate.write_plan = orig
        self.assertIn("verifica fallita", str(cm.exception))
        with self.assertRaises(st.SchemaError):
            st.init_storage_v2()


if __name__ == "__main__":
    unittest.main()
