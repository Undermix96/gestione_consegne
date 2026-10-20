"""
Backup sul sistema vero: pianificazione del server (ogni N secondi, solo se ci sono modifiche), conservazione,
backup iniziale dopo la migrazione, `python backup.py`, e RIPRISTINO completo con gli stessi strumenti
dell'immagine (psql / mysql). Ogni test gira su json, PostgreSQL e MySQL. Si salta con TEST_INTEGRATION=0.
"""
import os
import shutil
import subprocess
import tempfile
import time
import unittest

import integrazione_lib as L

import sys
sys.path.insert(0, L.ROOT)
import backup  # noqa: E402

SALTA = os.environ.get("TEST_INTEGRATION", "1") == "0"


def tmpdir(test):
    d = tempfile.mkdtemp(prefix="gc_int_")
    test.addCleanup(shutil.rmtree, d, True)
    return d


def attendi(condizione, secondi, passo=0.5):
    fine = time.time() + secondi
    while time.time() < fine:
        if condizione():
            return True
        time.sleep(passo)
    return condizione()


@unittest.skipIf(SALTA, "TEST_INTEGRATION=0")
class BackupSistema(unittest.TestCase):

    def avvia(self, kind, extra=None):
        tmp = tmpdir(self)
        s = L.bring_up(kind, L.v1_dataset(n_cons=6, n_giorn=3, per=2), tmp, extra=extra)
        self.addCleanup(s["srv"].stop)
        s["tmp"] = tmp
        s["dir"] = os.path.join(s["denv"]["DATA_DIR"], "backup")
        return s

    def elenco(self, s):
        return backup.list_backups(s["dir"])

    # ── la migrazione lascia un backup iniziale ──
    def backup_iniziale(self, kind):
        s = self.avvia(kind)
        self.assertIn("Backup iniziale della destinazione", s["migrate_out"])
        self.assertEqual(len(self.elenco(s)), 1)
        self.assertEqual(self.elenco(s)[0]["tipo"], "snapshot" if kind == "json" else "dump")

    # ── pianificazione del server ──
    def pianificazione(self, kind):
        s = self.avvia(kind, {"BACKUP_INTERVAL": "3", "BACKUP_KEEP": "4"})
        api, sa = s["api"], s["sa"]
        # al riavvio non si sa se è cambiato qualcosa dall'ultimo backup: ne basta uno; poi, a riposo, nessun altro
        self.assertTrue(attendi(lambda: len(self.elenco(s)) >= 2, 20), "nessun backup automatico dopo l'avvio")
        time.sleep(1.5)
        n = len(self.elenco(s))
        time.sleep(9)                                                    # tre intervalli senza modifiche
        self.assertEqual(len(self.elenco(s)), n, "backup a riposo: non ce ne devono essere")
        # una modifica → entro un intervallo (più il tick di controllo) compare un nuovo backup
        api.must("POST", "/api/squadre", {"nome": "Nuova squadra"}, s["t1"])
        self.assertTrue(attendi(lambda: len(self.elenco(s)) > n, 20), "nessun backup dopo una modifica")
        # il log del server lo dice, senza errori
        log = s["srv"].log_tail(400)
        self.assertIn("[BACKUP] Backup automatico ogni 3s", log)
        self.assertNotIn("Traceback", log)

    # ── backup dal pannello e conservazione degli ultimi N ──
    def manuale_e_conservazione(self, kind):
        s = self.avvia(kind, {"BACKUP_INTERVAL": "0", "BACKUP_KEEP": "3"})   # 0: nessun automatico
        api, sa = s["api"], s["sa"]
        prima = len(self.elenco(s))
        nomi = []
        for _ in range(5):
            r = api.must("POST", "/api/backup", {}, sa)
            nomi.append(r["file"])
            time.sleep(1.1)                                              # snapshot json: un nome per secondo
        elenco = api.must("GET", "/api/backup", token=sa)
        self.assertEqual(elenco["conservati"], 3)
        self.assertEqual(elenco["intervallo"], 0)
        self.assertLessEqual(len(elenco["backups"]), 3)
        self.assertEqual([b["nome"] for b in elenco["backups"]], nomi[::-1][:len(elenco["backups"])])   # i più recenti
        self.assertGreater(prima, 0)
        self.assertEqual(api.call("POST", "/api/backup", {}, s["t1"])[0], 403)                          # l'operatore no
        self.assertIn("disattivato", s["srv"].log_tail(400))

    # ── python backup.py ──
    def riga_di_comando(self, kind):
        s = self.avvia(kind, {"BACKUP_INTERVAL": "0"})
        s["srv"].stop()
        prima = len(self.elenco(s))
        time.sleep(1.1)
        p = L.run([os.path.join(L.ROOT, "backup.py")], s["denv"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("ESITO: OK", p.stdout)
        self.assertGreaterEqual(len(self.elenco(s)), prima + 1 if kind != "json" else prima)
        # errori: cartella non utilizzabile e (SQL) password sbagliata → codice 1
        if not (hasattr(os, "geteuid") and os.geteuid() == 0):
            p = L.run([os.path.join(L.ROOT, "backup.py")], {**s["denv"], "DATA_DIR": "/proc/non-scrivibile"} if kind != "json"
                      else {**s["denv"], "DATA_DIR": "/proc/non-scrivibile"})
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        if kind != "json":
            p = L.run([os.path.join(L.ROOT, "backup.py")], {**s["denv"], "DB_PASSWORD": "sbagliata"})
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertNotIn("sbagliata", p.stdout + p.stderr)

    # ── ripristino completo ──
    def ripristino(self, kind):
        s = self.avvia(kind, {"BACKUP_INTERVAL": "0"})
        api = s["api"]
        api.must("POST", "/api/squadre", {"nome": "Dopo la migrazione"}, s["t1"])
        api.must("POST", "/api/consegne", {"cognome": "Ultimo", "nome": "Cliente", "citta": "X", "articoli": []}, s["t1"])
        s["srv"].stop()
        time.sleep(1.1)
        p = L.run([os.path.join(L.ROOT, "backup.py")], s["denv"])
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        originale = L.dump_v2(s["denv"])
        ultimo = self.elenco(s)[0]
        sub = tmpdir(self)

        if kind == "json":
            # lo snapshot è un insieme di file con la data nel nome: si ricopiano senza data in una cartella nuova
            nuovo = os.path.join(sub, "ripristinato")
            os.makedirs(nuovo)
            ts = ultimo["nome"].replace("snapshot-", "")
            for f in os.listdir(s["dir"]):
                if f.endswith(f".{ts}.json"):
                    shutil.copy(os.path.join(s["dir"], f), os.path.join(nuovo, f.replace(f".{ts}", "")))
            renv = {"DB_BACKEND": "json", "DATA_DIR": nuovo}
        else:
            renv = L.backend_env(kind, "src", sub)                      # database vuoto di ripristino (diverso dall'originale)
            L.dbtool("wipe", renv)
            f = os.path.join(s["dir"], ultimo["nome"])
            if kind == "postgres":
                cmd = ('gunzip -c "$F" | psql -q -h "$H" -U "$U" -d "$D" -v ON_ERROR_STOP=1 ' +
                       ('-p "$P"' if "DB_PORT" in renv else ""))
                env = {"PGPASSWORD": renv["DB_PASSWORD"]}
            else:
                cmd = 'gunzip -c "$F" | mysql -h "$H" -u "$U" ' + ('-P "$P" ' if "DB_PORT" in renv else "") + '"$D"'
                env = {"MYSQL_PWD": renv["DB_PASSWORD"]}
            r = subprocess.run(["sh", "-c", cmd], capture_output=True, text=True, timeout=300,
                               env={**L.base_env(), **env, "F": f, "H": renv["DB_HOST"], "U": renv["DB_USER"],
                                    "D": renv["DB_NAME"], "P": renv.get("DB_PORT", "")})
            self.assertEqual(r.returncode, 0, f"ripristino fallito: {r.stdout}{r.stderr}")

        # il ripristinato è identico all'originale (compresi versioni e ultimo accesso) e funziona
        ripristinato = L.dump_v2(renv)
        self.assertEqual(ripristinato, originale)
        self.assertEqual(L.check_integrity(ripristinato), [])
        srv = L.ServerProc({**renv, "DATA_DIR": renv.get("DATA_DIR", sub)}, sub).start()
        self.addCleanup(srv.stop)
        a = L.Api(srv.port)
        a.token("superadmin", "Super#Pass2026")                           # le credenziali sono quelle di prima
        tok = a.token("op1", "op1#Pw1")
        cognomi = [c["cognome"] for c in a.must("GET", "/api/consegne", token=tok)["consegne"]]
        self.assertIn("Ultimo", cognomi)
        self.assertIn("Dopo la migrazione", [x["nome"] for x in a.must("GET", "/api/squadre", token=tok)["squadre"]])


for _d in L.BACKENDS:
    for _n in ("backup_iniziale", "pianificazione", "manuale_e_conservazione", "riga_di_comando", "ripristino"):
        setattr(BackupSistema, f"test_{_n}_{_d}", (lambda n, d: lambda self: getattr(self, n)(d))(_n, _d))
