#!/usr/bin/env python3
"""
backup.py — backup dei database (pg_dump / mysqldump) e utilità comuni a tutti i backup

Da riga di comando esegue un backup immediato del backend configurato (stesse variabili d'ambiente
del server) ed esce con 0 se è riuscito, con 1 altrimenti:

    docker exec <container> python backup.py          # es. attività pianificata di Synology DSM
    docker compose exec app python backup.py

Dove finiscono i file: DATA_DIR/backup/ — la stessa cartella dei backup del backend json. Con un
database serve quindi una cartella montata su /data (con compose c'è già il volume app_data).

  json      snapshot dei file JSON (lo fa storage.py)
  postgres  <backend>-<database>.<AAAA-MM-GG_hh-mm-ss>.sql.gz   da pg_dump
  mysql     <backend>-<database>.<AAAA-MM-GG_hh-mm-ss>.sql.gz   da mysqldump

Si conservano gli ultimi BACKUP_KEEP file per tipo (default 30). BACKUP_INTERVAL (secondi, default
21600 = 6 ore, 0 = nessun backup automatico) regola la pianificazione del server.

Ripristino (SQL, nel database di destinazione VUOTO; stessi strumenti che sono nell'immagine):
    gunzip -c FILE.sql.gz | PGPASSWORD=... psql -h HOST -U UTENTE -d DATABASE -v ON_ERROR_STOP=1
    gunzip -c FILE.sql.gz | MYSQL_PWD=...  mysql -h HOST -u UTENTE DATABASE

Le versioni di pg_dump e mysqldump nell'immagine coincidono con quelle dei database di compose.yaml
(vedi il Dockerfile e tests/test_backup.py). Solo libreria standard.
"""

import gzip
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
from datetime import datetime

log = logging.getLogger(__name__)

DUMP_TIMEOUT = int(os.environ.get("BACKUP_TIMEOUT", 900))     # secondi
# comando dello strumento (può avere argomenti: lo si divide come una riga di shell); sostituibile nei test
TOOL = {"postgres": "pg_dump", "mysql": "mysqldump"}
TRAILER = {"postgres": b"-- PostgreSQL database dump complete", "mysql": b"-- Dump completed"}
TS_FORMAT = "%Y-%m-%d_%H-%M-%S"

_lock = threading.Lock()      # un solo dump alla volta nel processo

_SQL_RE = re.compile(r"^(postgres|mysql)-(.+)\.(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})(?:-(\d+))?\.sql\.gz$")
_JSON_RE = re.compile(r"^[a-z_]+\.(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.json$")


def _fail(msg):
    log.error(f"[BACKUP] {msg}")
    return {"ok": False, "file": None, "error": msg}


def _command(backend, cfg):
    """Argomenti dello strumento e variabili d'ambiente (la password mai tra gli argomenti: si vedrebbe in ps)."""
    if backend == "postgres":
        args = [*shlex.split(TOOL["postgres"]), "--host", cfg["host"], "--port", str(cfg["port"]), "--username", cfg["user"],
                "--dbname", cfg["database"], "--no-owner", "--no-acl", "--no-password"]
        return args, {"PGPASSWORD": cfg["password"]}
    args = [*shlex.split(TOOL["mysql"]), "--host", cfg["host"], "--port", str(cfg["port"]), "--user", cfg["user"],
            "--single-transaction", "--routines", "--triggers", "--events", "--no-tablespaces",
            "--default-character-set=utf8mb4", "--set-gtid-purged=OFF", cfg["database"]]
    return args, {"MYSQL_PWD": cfg["password"]}


def _tool_major(backend):
    """Versione dello strumento ('16', '8.4') o None se non eseguibile."""
    try:
        out = subprocess.run([*shlex.split(TOOL[backend]), "--version"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    # "pg_dump (PostgreSQL) 16.15 (...)"  ·  "mysqldump  Ver 8.4.13 for Linux on x86_64 (...)"
    m = re.search(r"\) (\d+)\.", out) if backend == "postgres" else re.search(r"Ver (\d+\.\d+)", out)
    return m.group(1) if m else None


def version_warning(backend, server_version):
    """Avviso se lo strumento non coincide con la versione del server ('' se coincide o non verificabile)."""
    tool = _tool_major(backend)
    if tool is None or not server_version:
        return ""
    m = re.match(r"(\d+)\.(\d+)", str(server_version))
    if not m:
        return ""
    server = m.group(1) if backend == "postgres" else f"{m.group(1)}.{m.group(2)}"
    if tool != server:
        return f"{TOOL[backend]} {tool} non coincide con il server {server}: usare un'immagine con gli strumenti della stessa versione"
    return ""


def run_dump(backend, cfg, dest_dir, keep):
    """Dump del database in dest_dir. Ritorna {"ok": bool, "file": nome|None, "error": str|None, "avvisi": [str]}.
    Non solleva eccezioni; il file compare con il suo nome definitivo solo a dump concluso e verificato."""
    if backend not in TOOL:
        return _fail(f"backend non supportato dal dump: {backend}")
    if not _lock.acquire(blocking=False):
        return _fail("un backup è già in corso")
    partial = None
    try:
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError as e:
            return _fail(f"cartella dei backup non utilizzabile ({dest_dir}): {e}. Con un database serve una cartella "
                         f"montata su /data scrivibile dall'utente del container")
        ts = datetime.now().strftime(TS_FORMAT)
        base = f"{backend}-{cfg['database']}.{ts}"
        # più backup nello stesso secondo: numero progressivo MAGGIORE di quelli presenti (mai riusare un numero già
        # eliminato dalla conservazione, o il backup nuovo risulterebbe il più vecchio e verrebbe cancellato)
        presenti = [int(m.group(4) or 1) for m in map(_SQL_RE.match, os.listdir(dest_dir))
                    if m and m.group(1) == backend and m.group(2) == cfg["database"] and m.group(3) == ts]
        n = max(presenti) + 1 if presenti else 1
        final = os.path.join(dest_dir, base + (".sql.gz" if n == 1 else f"-{n}.sql.gz"))
        partial = final + ".partial"
        args, extra_env = _command(backend, cfg)
        err = tempfile.TemporaryFile()
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=err, env={**os.environ, **extra_env})
        except FileNotFoundError:
            return _fail(f"{TOOL[backend]} non trovato: l'immagine deve contenere gli strumenti di dump")
        except OSError as e:
            return _fail(f"{TOOL[backend]} non eseguibile: {e}")
        timed_out = []
        watchdog = threading.Timer(DUMP_TIMEOUT, lambda: (timed_out.append(1), proc.kill()))
        watchdog.start()
        tail, size = b"", 0
        try:
            with gzip.open(partial, "wb", compresslevel=6) as gz:
                while True:
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        break
                    gz.write(chunk)
                    size += len(chunk)
                    tail = (tail + chunk)[-4096:]
            rc = proc.wait()
        finally:
            watchdog.cancel()
            proc.stdout.close()
        err.seek(0)
        msg = err.read().decode("utf-8", "replace").strip()
        err.close()
        if timed_out:
            return _fail(f"{TOOL[backend]} interrotto: superato il tempo massimo di {DUMP_TIMEOUT}s")
        if rc != 0:
            return _fail(f"{TOOL[backend]} terminato con codice {rc}: {msg.splitlines()[-1] if msg else 'nessun messaggio'}")
        if size == 0 or TRAILER[backend] not in tail:
            return _fail(f"{TOOL[backend]}: dump incompleto (manca la riga di chiusura), file scartato")
        os.replace(partial, final)
        partial = None
        avvisi = [msg] if msg and "warning" in msg.lower() else []
        _prune(dest_dir, f"{backend}-{cfg['database']}.", keep)
        log.info(f"[BACKUP] Creato {os.path.basename(final)} ({os.path.getsize(final)} byte)")
        return {"ok": True, "file": os.path.basename(final), "error": None, "avvisi": avvisi}
    except Exception as e:                     # un backup non deve mai far cadere chi lo chiama
        return _fail(f"errore imprevisto: {e}")
    finally:
        if partial and os.path.exists(partial):
            try:
                os.remove(partial)
            except OSError:
                pass
        _lock.release()


def _prune(dest_dir, prefix, keep):
    """Conserva gli ultimi `keep` dump con questo prefisso (i nomi contengono la data: ordine alfabetico)."""
    # ordine cronologico: prima la data, poi il numero progressivo degli eventuali backup nello stesso secondo
    files = sorted((f for f in os.listdir(dest_dir) if f.startswith(prefix) and _SQL_RE.match(f)),
                   key=lambda f: (_SQL_RE.match(f).group(3), int(_SQL_RE.match(f).group(4) or 1)))
    for old in files[:max(0, len(files) - keep)]:
        try:
            os.remove(os.path.join(dest_dir, old))
        except OSError as e:
            log.warning(f"[BACKUP] Impossibile eliminare il vecchio backup {old}: {e}")


def list_backups(dest_dir):
    """Backup presenti in dest_dir, dal più recente: [{nome, creato (ISO), dimensione, tipo}].
    SQL: un file per dump ('dump'). json: uno snapshot raggruppa i file creati nello stesso istante ('snapshot')."""
    out, snaps = [], {}
    try:
        names = os.listdir(dest_dir)
    except OSError:
        return []
    for f in names:
        p = os.path.join(dest_dir, f)
        m = _SQL_RE.match(f)
        if m:
            out.append({"nome": f, "creato": datetime.strptime(m.group(3), TS_FORMAT).isoformat(timespec="seconds"),
                        "dimensione": os.path.getsize(p), "tipo": "dump", "_n": int(m.group(4) or 1)})
            continue
        m = _JSON_RE.match(f)
        if m:
            s = snaps.setdefault(m.group(1), {"nome": f"snapshot-{m.group(1)}", "dimensione": 0, "file": 0,
                                              "creato": datetime.strptime(m.group(1), TS_FORMAT).isoformat(timespec="seconds"),
                                              "tipo": "snapshot"})
            s["dimensione"] += os.path.getsize(p)
            s["file"] += 1
    out.extend(snaps.values())
    out.sort(key=lambda b: (b["creato"], b.get("_n", 1)), reverse=True)
    for b in out:
        b.pop("_n", None)
    return out


def last_backup_time(dest_dir):
    """Istante (epoch) del backup più recente, o None."""
    items = list_backups(dest_dir)
    return datetime.fromisoformat(items[0]["creato"]).timestamp() if items else None


def main():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    import storage
    try:
        storage.init_storage_v2()
    except storage.StorageError as e:
        log.error(f"[BACKUP] storage non utilizzabile: {e}")
        return 1
    r = storage.backup_run()
    if r["ok"]:
        log.info(f"[BACKUP] ESITO: OK — {r['file']}")
        return 0
    log.error(f"[BACKUP] ESITO: FALLITO — {r['error']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
