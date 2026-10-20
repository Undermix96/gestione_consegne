"""
Test dei backup: dump con pg_dump / mysqldump (postgres, mysql), snapshot (json), elenco, conservazione,
errori, versioni degli strumenti. Per i backend SQL servono i database di test (compose.test.yaml);
con i backend DB la suite SVUOTA le tabelle (DB_NAME deve finire per _test).
"""
import glob
import gzip
import logging
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest

os.environ["STORAGE_ALLOW_TEST_RESET"] = "1"
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)

import backup  # noqa: E402
import storage as st  # noqa: E402

BACKEND = st.BACKEND
SQL = BACKEND in ("mysql", "postgres")
NOME_RE = re.compile(rf"^{BACKEND}-{re.escape(os.environ.get('DB_NAME', ''))}\.\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}}(-\d+)?\.sql\.gz$")


class Base(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gc_bk_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.old = (st.DATA_DIR, st.MAX_BACKUPS, backup.DUMP_TIMEOUT, dict(backup.TOOL))
        self.addCleanup(self.ripristina)
        st.DATA_DIR = self.tmp
        st.init_storage_v2()
        st._test_reset()
        st.insert_record("negozi", {"id": "n1", "nome": "Negozio di prova àèìòù"})
        st.insert_record("squadre", {"id": "s1", "negozio_id": "n1", "nome": "Squadra A", "colorIdx": 1})
        self.dir = os.path.join(self.tmp, "backup")
        shutil.rmtree(self.dir, ignore_errors=True)       # le scritture di preparazione possono aver fatto uno snapshot (json)
        st._be()._last_backup = 0.0

    def ripristina(self):
        st.DATA_DIR, st.MAX_BACKUPS, backup.DUMP_TIMEOUT = self.old[0], self.old[1], self.old[2]
        backup.TOOL.clear()
        backup.TOOL.update(self.old[3])

    def files(self):
        return sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []

    def finto(self, corpo):
        """Sostituisce lo strumento di dump con uno script di prova (sh)."""
        p = os.path.join(self.tmp, "finto.sh")
        with open(p, "w") as f:
            f.write("#!/bin/sh\n" + corpo)
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        backup.TOOL[BACKEND] = f"sh {p}"          # /tmp dei container è montata noexec: si esegue con sh
        return p


@unittest.skipUnless(SQL, "dump SQL: solo con i backend postgres e mysql")
class DumpSql(Base):

    def test_backup_riuscito(self):
        r = st.backup_run()
        self.assertTrue(r["ok"], r)
        self.assertRegex(r["file"], NOME_RE)
        self.assertEqual(self.files(), [r["file"]])                               # niente file parziali
        with gzip.open(os.path.join(self.dir, r["file"]), "rt", encoding="utf-8") as f:
            testo = f.read()
        self.assertIn("Negozio di prova àèìòù", testo)                           # i dati ci sono (e l'unicode è integro)
        self.assertIn("Squadra A", testo)
        self.assertIn("giornate", testo)
        self.assertTrue(st.backup_now())
        elenco = st.backup_list()
        self.assertEqual(len(elenco), 2)
        self.assertEqual({b["tipo"] for b in elenco}, {"dump"})
        self.assertGreater(elenco[0]["dimensione"], 100)
        self.assertEqual(st.backup_last_time() is not None, True)

    def test_conservazione_degli_ultimi_n(self):
        st.MAX_BACKUPS = 3
        nomi = [st.backup_run()["file"] for _ in range(5)]                        # nello stesso secondo: numerati
        self.assertEqual(len(set(nomi)), 5)
        self.assertEqual(len(self.files()), 3)
        self.assertEqual(set(self.files()), set(nomi[-3:]))                       # restano i più recenti, non i più vecchi

    def test_il_conteggio_delle_scritture_cresce(self):
        a = st.write_count()
        st.insert_record("squadre", {"id": "s2", "negozio_id": "n1", "nome": "B", "colorIdx": 2})
        st.update_record("squadre", "s2", {"nome": "B2"})
        st.delete_record("squadre", "s2")
        st.set_meta("chiave", 1)
        self.assertEqual(st.write_count(), a + 4)
        st.list_records("squadre")
        st.get_record("squadre", "s1")
        self.assertEqual(st.write_count(), a + 4)                                 # le letture non contano

    def test_password_errata(self):
        vecchia = os.environ["DB_PASSWORD"]
        os.environ["DB_PASSWORD"] = "pw-sbagliata-segretissima"
        try:
            with self.assertLogs(level="DEBUG") as cm:
                r = st.backup_run()
        finally:
            os.environ["DB_PASSWORD"] = vecchia
        self.assertFalse(r["ok"])
        self.assertIn(BACKEND == "postgres" and "pg_dump" or "mysqldump", r["error"])
        self.assertEqual(self.files(), [])                                        # nessun file, nemmeno parziale
        self.assertNotIn("pw-sbagliata-segretissima", "\n".join(cm.output))       # la password non finisce nei log
        self.assertNotIn("pw-sbagliata-segretissima", r["error"])

    def test_strumento_mancante(self):
        backup.TOOL[BACKEND] = "/non/esiste/dump"
        r = st.backup_run()
        self.assertFalse(r["ok"])
        self.assertIn("non trovato", r["error"])
        self.assertEqual(self.files(), [])

    def test_dump_incompleto_scartato(self):
        self.finto('echo "dati parziali senza la riga di chiusura"\nexit 0\n')
        r = st.backup_run()
        self.assertFalse(r["ok"])
        self.assertIn("incompleto", r["error"])
        self.assertEqual(self.files(), [])

    def test_dump_con_errore_scartato(self):
        self.finto('echo "-- PostgreSQL database dump complete"\necho "-- Dump completed"\necho "boom: disco pieno" >&2\nexit 3\n')
        r = st.backup_run()
        self.assertFalse(r["ok"])
        self.assertIn("codice 3", r["error"])
        self.assertIn("boom: disco pieno", r["error"])
        self.assertEqual(self.files(), [])

    def test_tempo_massimo(self):
        backup.DUMP_TIMEOUT = 1
        self.finto("sleep 20\n")
        r = st.backup_run()
        self.assertFalse(r["ok"])
        self.assertIn("tempo massimo", r["error"])
        self.assertEqual(self.files(), [])

    def test_un_solo_backup_alla_volta(self):
        with backup._lock:
            r = st.backup_run()
        self.assertFalse(r["ok"])
        self.assertIn("già in corso", r["error"])
        self.assertTrue(st.backup_run()["ok"])                                    # e il blocco si libera

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "come root ogni cartella è scrivibile")
    def test_cartella_non_scrivibile(self):
        st.DATA_DIR = "/proc/non-scrivibile"
        r = st.backup_run()
        self.assertFalse(r["ok"])
        self.assertIn("/data", r["error"])                                        # spiega cosa montare

    def test_la_password_passa_dall_ambiente_non_dagli_argomenti(self):
        out_args, out_env = os.path.join(self.tmp, "args.txt"), os.path.join(self.tmp, "env.txt")
        self.finto(f'printf "%s\\n" "$@" > {out_args}\necho "$PGPASSWORD$MYSQL_PWD" > {out_env}\n'
                   f'echo "-- PostgreSQL database dump complete"\necho "-- Dump completed"\n')
        r = st.backup_run()
        self.assertTrue(r["ok"], r)
        with open(out_args) as f:
            args = f.read()
        with open(out_env) as f:
            env = f.read().strip()
        self.assertEqual(env, os.environ["DB_PASSWORD"])
        if os.environ["DB_PASSWORD"] not in ("test",):      # con una password banale il controllo sugli argomenti non è significativo
            self.assertNotIn(os.environ["DB_PASSWORD"], args)
        self.assertIn(os.environ["DB_NAME"], args)
        self.assertNotIn("-p", args.split())
        self.assertNotIn("--password", args)


class SnapshotJson(Base):

    @unittest.skipUnless(BACKEND == "json", "specifico del backend json")
    def test_snapshot_elenco_e_conservazione(self):
        r = st.backup_run()
        self.assertTrue(r["ok"])
        self.assertTrue(r["file"].startswith("snapshot-"))
        elenco = st.backup_list()
        self.assertEqual([b["tipo"] for b in elenco], ["snapshot"])
        self.assertEqual(elenco[0]["nome"], r["file"])
        self.assertGreater(elenco[0]["file"], 5)                                  # un file per collezione + meta
        # conservazione: con N=2 e quattro snapshot vecchi già presenti restano i due più recenti, compreso il nuovo
        for giorno in range(1, 5):
            for nome in ("negozi", "squadre", "meta"):
                with open(os.path.join(self.dir, f"{nome}.2026-01-0{giorno}_00-00-00.json"), "w") as f:
                    f.write("[]")
        st.MAX_BACKUPS = 2
        nuovo = st.backup_run()["file"]
        per_tipo = sorted(f for f in os.listdir(self.dir) if f.startswith("negozi."))
        self.assertEqual(len(per_tipo), 2)
        self.assertIn(nuovo.replace("snapshot-", "negozi.") + ".json", per_tipo)
        self.assertIn("negozi.2026-01-04_00-00-00.json", per_tipo)

    def test_impostazioni_predefinite(self):
        # 6 ore tra i backup automatici e ultimi 30 file, per tutti i tipi di storage
        if "BACKUP_INTERVAL" not in os.environ:
            self.assertEqual(st.BACKUP_MIN_INTERVAL, 21600)
        if "BACKUP_KEEP" not in os.environ:
            self.assertEqual(self.old[1], 30)

    @unittest.skipUnless(BACKEND == "json", "specifico del backend json")
    def test_intervallo_zero_disattiva_il_backup_prima_delle_scritture(self):
        vecchio = st.BACKUP_MIN_INTERVAL
        self.addCleanup(setattr, st, "BACKUP_MIN_INTERVAL", vecchio)
        be = st._be()
        be._last_backup = 0.0
        st.BACKUP_MIN_INTERVAL = 0
        st.insert_record("squadre", {"id": "s9", "negozio_id": "n1", "nome": "Z", "colorIdx": 0})
        self.assertEqual(st.backup_list(), [])                                    # nessuno snapshot automatico
        st.BACKUP_MIN_INTERVAL = 3600
        st.insert_record("squadre", {"id": "s10", "negozio_id": "n1", "nome": "Y", "colorIdx": 0})
        self.assertEqual(len(st.backup_list()), 1)                                # con un intervallo, sì
        st.insert_record("squadre", {"id": "s11", "negozio_id": "n1", "nome": "X", "colorIdx": 0})
        self.assertEqual(len(st.backup_list()), 1)                                # ma non più di uno per intervallo


class Elenco(unittest.TestCase):
    """backup.list_backups / last_backup_time sulle cartelle (senza database)."""

    def test_elenco_ordine_e_tipi(self):
        with tempfile.TemporaryDirectory() as d:
            def mk(nome, n=10):
                with open(os.path.join(d, nome), "wb") as f:
                    f.write(b"x" * n)
            mk("postgres-db.2026-03-01_10-00-00.sql.gz", 100)
            mk("postgres-db.2026-03-01_10-00-00-2.sql.gz", 200)       # stesso secondo: più recente
            mk("mysql-db.2026-02-01_09-00-00.sql.gz", 50)
            mk("consegne.2026-04-01_08-00-00.json", 5)
            mk("meta.2026-04-01_08-00-00.json", 7)
            mk("postgres-db.2026-03-05_10-00-00.sql.gz.partial", 9)   # parziale: ignorato
            mk("estraneo.txt", 3)
            elenco = backup.list_backups(d)
            self.assertEqual([b["nome"] for b in elenco], [
                "snapshot-2026-04-01_08-00-00",
                "postgres-db.2026-03-01_10-00-00-2.sql.gz",
                "postgres-db.2026-03-01_10-00-00.sql.gz",
                "mysql-db.2026-02-01_09-00-00.sql.gz"])
            self.assertEqual(elenco[0]["dimensione"], 12)
            self.assertEqual(elenco[0]["file"], 2)
            self.assertEqual(elenco[1]["creato"], "2026-03-01T10:00:00")
            self.assertEqual(backup.list_backups(os.path.join(d, "non-esiste")), [])
            self.assertIsNone(backup.last_backup_time(os.path.join(d, "non-esiste")))
            self.assertIsNotNone(backup.last_backup_time(d))

    def test_conservazione_per_prefisso(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(1, 6):
                open(os.path.join(d, f"mysql-db.2026-01-0{i}_00-00-00.sql.gz"), "w").close()
            open(os.path.join(d, "mysql-altro.2026-01-01_00-00-00.sql.gz"), "w").close()   # altro database: intoccato
            backup._prune(d, "mysql-db.", 2)
            self.assertEqual(sorted(os.listdir(d)), ["mysql-altro.2026-01-01_00-00-00.sql.gz",
                                                     "mysql-db.2026-01-04_00-00-00.sql.gz",
                                                     "mysql-db.2026-01-05_00-00-00.sql.gz"])

    def test_avviso_di_versione(self):
        vecchio = backup._tool_major
        try:
            backup._tool_major = lambda b: "15"
            self.assertIn("non coincide", backup.version_warning("postgres", "16.4 (Debian 16.4-1)"))
            backup._tool_major = lambda b: "16"
            self.assertEqual(backup.version_warning("postgres", "16.4 (Debian 16.4-1)"), "")
            backup._tool_major = lambda b: "8.4"
            self.assertEqual(backup.version_warning("mysql", "8.4.3"), "")
            self.assertIn("non coincide", backup.version_warning("mysql", "8.0.36"))
            backup._tool_major = lambda b: None                                   # strumento non eseguibile: nessun avviso
            self.assertEqual(backup.version_warning("mysql", "8.4.3"), "")
        finally:
            backup._tool_major = vecchio


class VersioniStrumenti(unittest.TestCase):
    """Gli strumenti nell'immagine devono essere della versione dei database di compose.yaml."""

    def immagini(self, nome_file):
        p = os.path.join(ROOT, nome_file)
        if not os.path.exists(p):
            self.skipTest(f"{nome_file} non disponibile (montato solo nel container dei test)")
        with open(p, encoding="utf-8") as f:
            testo = f.read()
        pg = re.search(r"image:\s*postgres:(\d+)", testo)
        my = re.search(r"image:\s*mysql:(\d+\.\d+)", testo)
        self.assertIsNotNone(pg, f"{nome_file}: immagine postgres non trovata")
        self.assertIsNotNone(my, f"{nome_file}: immagine mysql non trovata")
        return pg.group(1), my.group(1)

    def test_strumenti_installati(self):
        self.assertIsNotNone(backup._tool_major("postgres"), "pg_dump non eseguibile")
        self.assertIsNotNone(backup._tool_major("mysql"), "mysqldump non eseguibile")

    def test_coincidono_con_compose_yaml(self):
        pg, my = self.immagini("compose.yaml")
        self.assertEqual(backup._tool_major("postgres"), pg, "pg_dump non coincide con postgres di compose.yaml (Dockerfile: PG_MAJOR)")
        self.assertEqual(backup._tool_major("mysql"), my, "mysqldump non coincide con mysql di compose.yaml (Dockerfile: MYSQL_*)")

    def test_i_database_di_test_hanno_le_stesse_versioni(self):
        self.assertEqual(self.immagini("compose.test.yaml"), self.immagini("compose.yaml"))


if __name__ == "__main__":
    unittest.main()
