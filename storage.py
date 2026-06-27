"""
storage.py — Astrazione backend dati

Seleziona il backend in base alla variabile d'ambiente DB_BACKEND:
  json     (default) — file JSON separati sotto DATA_DIR
  mysql              — MySQL 8.x
  postgres           — PostgreSQL 16+

Variabili d'ambiente:
  DB_BACKEND   json | mysql | postgres          (default: json)
  DATA_DIR     directory dei file JSON          (default: /data)
  DB_HOST      host del DB                      (default: db)
  DB_PORT      porta del DB                     (default: 3306 mysql / 5432 postgres)
  DB_NAME      nome del database                (default: gestione_consegne)
  DB_USER      utente del database
  DB_PASSWORD  password del database

Interfaccia pubblica:
  init_storage()          — chiamata una volta all'avvio
  read_data()             — restituisce dict {consegne, giornate, squadre}
  write_data(data)        — salva il dict completo
  make_backup()           — snapshot JSON (solo backend json, no-op per DB)
"""

import json
import logging
import os
import time
import glob
from datetime import datetime

log = logging.getLogger(__name__)

BACKEND       = os.environ.get("DB_BACKEND", "json").lower()
DATA_DIR      = os.environ.get("DATA_DIR", "/data")
WRITE_RETRIES = 2
MAX_BACKUPS   = 20

# ─── INIT ────────────────────────────────────────────────────────────────────

def init_storage():
    """Inizializza il backend scelto. Chiamata una volta all'avvio del server."""
    if BACKEND == "json":
        _json_init()
    elif BACKEND == "mysql":
        _mysql_init()
    elif BACKEND == "postgres":
        _pg_init()
    else:
        raise ValueError(f"DB_BACKEND non valido: '{BACKEND}'. Valori accettati: json, mysql, postgres")
    log.info(f"[STORAGE] Backend attivo: {BACKEND}")

# ─── PUBLIC API ──────────────────────────────────────────────────────────────

def read_data():
    """Legge e restituisce {consegne: [], giornate: [], squadre: []}."""
    if BACKEND == "json":
        return _json_read()
    elif BACKEND == "mysql":
        return _mysql_read()
    elif BACKEND == "postgres":
        return _pg_read()

def write_data(data):
    """Salva il dict completo {consegne, giornate, squadre}."""
    if BACKEND == "json":
        _json_write(data)
    elif BACKEND == "mysql":
        _mysql_write(data)
    elif BACKEND == "postgres":
        _pg_write(data)

def make_backup():
    """Snapshot prima di ogni scrittura. No-op per backend DB."""
    if BACKEND == "json":
        _json_backup()

# ═══════════════════════════════════════════════════════════════════════════════
# BACKEND JSON
# ═══════════════════════════════════════════════════════════════════════════════

_JSON_FILES = {
    "consegne": "consegne.json",
    "giornate":  "giornate.json",
    "squadre":   "squadre.json",
}
_BACKUP_DIR = os.path.join(DATA_DIR, "backup")


def _json_path(key):
    return os.path.join(DATA_DIR, _JSON_FILES[key])


def _json_init():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(_BACKUP_DIR, exist_ok=True)
    for key, default in [("consegne", []), ("giornate", []), ("squadre", [])]:
        p = _json_path(key)
        if not os.path.exists(p):
            _json_write_file(p, default)
            log.info(f"[STORAGE] Creato {p} (vuoto)")


def _json_read_file(path, default):
    for attempt in range(WRITE_RETRIES):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.error(f"[STORAGE] Errore lettura {path} (tentativo {attempt+1}): {e}")
            if attempt < WRITE_RETRIES - 1:
                time.sleep(0.3)
    log.critical(f"[STORAGE] Lettura fallita su {path} dopo {WRITE_RETRIES} tentativi")
    raise IOError(f"Impossibile leggere {path}")


def _json_write_file(path, data):
    """Scrittura atomica: scrive su .tmp poi rinomina."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _json_read():
    return {
        "consegne": _json_read_file(_json_path("consegne"), []),
        "giornate":  _json_read_file(_json_path("giornate"),  []),
        "squadre":   _json_read_file(_json_path("squadre"),   []),
    }


def _json_write(data):
    for attempt in range(WRITE_RETRIES):
        try:
            make_backup()
            for key in ("consegne", "giornate", "squadre"):
                _json_write_file(_json_path(key), data.get(key, []))
            log.info("[STORAGE] Dati salvati (json)")
            return
        except Exception as e:
            log.error(f"[STORAGE] Errore scrittura json (tentativo {attempt+1}): {e}")
            if attempt < WRITE_RETRIES - 1:
                time.sleep(0.3)
    raise IOError("Scrittura JSON fallita dopo tutti i tentativi")


def _json_backup():
    """Snapshot di tutti e tre i file in backup/, mantiene MAX_BACKUPS per tipo."""
    try:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        for key, fname in _JSON_FILES.items():
            src = _json_path(key)
            if not os.path.exists(src):
                continue
            dst = os.path.join(_BACKUP_DIR, f"{key}.{ts}.json")
            with open(src, "r", encoding="utf-8") as f:
                content = f.read()
            with open(dst, "w", encoding="utf-8") as f:
                f.write(content)
            # Rotazione: mantieni solo i MAX_BACKUPS più recenti per tipo
            pattern = os.path.join(_BACKUP_DIR, f"{key}.*.json")
            old = sorted(glob.glob(pattern))
            while len(old) > MAX_BACKUPS:
                os.remove(old.pop(0))
    except Exception as e:
        log.warning(f"[STORAGE] Backup fallito (non critico): {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKEND MYSQL
# ═══════════════════════════════════════════════════════════════════════════════

def _db_env(default_port):
    return {
        "host":     os.environ.get("DB_HOST", "db"),
        "port":     int(os.environ.get("DB_PORT", default_port)),
        "database": os.environ.get("DB_NAME", "gestione_consegne"),
        "user":     os.environ.get("DB_USER", ""),
        "password": os.environ.get("DB_PASSWORD", ""),
    }


_MYSQL_DDL = """
CREATE TABLE IF NOT EXISTS consegne (
    id              VARCHAR(36)  NOT NULL PRIMARY KEY,
    nome            VARCHAR(255),
    cognome         VARCHAR(255),
    indirizzo       TEXT,
    citta           VARCHAR(255),
    telefono        VARCHAR(50),
    tipo_prodotto   TEXT,
    tipo_consegna   VARCHAR(50),
    stato           VARCHAR(50)  NOT NULL DEFAULT 'in_attesa',
    note            TEXT,
    giorno_consegna VARCHAR(10),
    fascia_oraria   VARCHAR(50),
    data_prenotaz   VARCHAR(10),
    articoli        JSON,
    extra           JSON
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS squadre (
    id        VARCHAR(36)  NOT NULL PRIMARY KEY,
    nome      VARCHAR(255) NOT NULL,
    color_idx INT          NOT NULL DEFAULT 0
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS giornate (
    id       VARCHAR(36) NOT NULL PRIMARY KEY,
    data     VARCHAR(10) NOT NULL,
    squadra  VARCHAR(255),
    extra    JSON
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS giornata_consegne (
    giornata_id  VARCHAR(36) NOT NULL,
    consegna_id  VARCHAR(36) NOT NULL,
    completata   TINYINT(1)  NOT NULL DEFAULT 0,
    ordine       INT         NOT NULL DEFAULT 0,
    PRIMARY KEY (giornata_id, consegna_id),
    FOREIGN KEY (giornata_id) REFERENCES giornate(id)  ON DELETE CASCADE,
    FOREIGN KEY (consegna_id) REFERENCES consegne(id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
"""


def _mysql_connect():
    import mysql.connector
    cfg = _db_env(3306)
    return mysql.connector.connect(
        host=cfg["host"], port=cfg["port"],
        database=cfg["database"],
        user=cfg["user"], password=cfg["password"],
        charset="utf8mb4",
    )


def _mysql_init():
    import mysql.connector
    cfg = _db_env(3306)
    # Attendi che il DB sia pronto (il healthcheck del compose non è abbastanza —
    # può passare qualche secondo tra "pronto" e "accetta connessioni")
    for attempt in range(10):
        try:
            conn = mysql.connector.connect(
                host=cfg["host"], port=cfg["port"],
                database=cfg["database"],
                user=cfg["user"], password=cfg["password"],
                charset="utf8mb4",
            )
            cur = conn.cursor()
            for stmt in _MYSQL_DDL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            conn.commit()
            cur.close()
            conn.close()
            log.info("[STORAGE] Schema MySQL inizializzato")
            return
        except Exception as e:
            log.warning(f"[STORAGE] MySQL non ancora pronto (tentativo {attempt+1}/10): {e}")
            time.sleep(3)
    raise RuntimeError("Impossibile connettersi a MySQL dopo 10 tentativi")


def _mysql_read():
    conn = _mysql_connect()
    cur = conn.cursor(dictionary=True)

    cur.execute("SELECT * FROM consegne")
    consegne_rows = cur.fetchall()
    consegne = []
    for row in consegne_rows:
        c = {k: v for k, v in row.items() if k not in ("articoli", "extra")}
        c["articoli"] = json.loads(row["articoli"]) if row["articoli"] else []
        if row["extra"]:
            c.update(json.loads(row["extra"]))
        consegne.append(c)

    cur.execute("SELECT * FROM squadre")
    squadre = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM giornate")
    giornate_rows = cur.fetchall()
    giornate = []
    for row in giornate_rows:
        g = {k: v for k, v in row.items() if k != "extra"}
        if row["extra"]:
            g.update(json.loads(row["extra"]))
        # Carica consegneIds con ordine
        cur.execute(
            "SELECT consegna_id, completata FROM giornata_consegne "
            "WHERE giornata_id = %s ORDER BY ordine",
            (row["id"],)
        )
        links = cur.fetchall()
        g["consegneIds"] = [l["consegna_id"] for l in links]
        g["consegneCompletate"] = {l["consegna_id"]: bool(l["completata"]) for l in links}
        giornate.append(g)

    cur.close()
    conn.close()
    return {"consegne": consegne, "giornate": giornate, "squadre": squadre}


def _mysql_write(data):
    conn = _mysql_connect()
    cur = conn.cursor()
    try:
        # Consegne
        cur.execute("DELETE FROM consegne")
        for c in data.get("consegne", []):
            c = dict(c)
            articoli = json.dumps(c.pop("articoli", []), ensure_ascii=False)
            # Campi noti; tutto il resto va in extra
            known = {"id","nome","cognome","indirizzo","citta","telefono",
                     "tipo_prodotto","tipo_consegna","stato","note",
                     "giorno_consegna","fascia_oraria","data_prenotaz"}
            extra = {k: v for k, v in c.items() if k not in known}
            cur.execute(
                "INSERT INTO consegne "
                "(id,nome,cognome,indirizzo,citta,telefono,tipo_prodotto,"
                "tipo_consegna,stato,note,giorno_consegna,fascia_oraria,"
                "data_prenotaz,articoli,extra) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (c.get("id"), c.get("nome"), c.get("cognome"),
                 c.get("indirizzo"), c.get("citta"), c.get("telefono"),
                 c.get("tipoProdotto") or c.get("tipo_prodotto"),
                 c.get("tipoConsegna") or c.get("tipo_consegna"),
                 c.get("stato","in_attesa"), c.get("note"),
                 c.get("giornoConsegna") or c.get("giorno_consegna"),
                 c.get("fasciaOraria") or c.get("fascia_oraria"),
                 c.get("dataPrenotazione") or c.get("data_prenotaz"),
                 articoli,
                 json.dumps(extra, ensure_ascii=False) if extra else None)
            )

        # Squadre
        cur.execute("DELETE FROM squadre")
        for s in data.get("squadre", []):
            cur.execute(
                "INSERT INTO squadre (id, nome, color_idx) VALUES (%s, %s, %s)",
                (s["id"], s["nome"], s.get("colorIdx", s.get("color_idx", 0)))
            )

        # Giornate
        cur.execute("DELETE FROM giornata_consegne")
        cur.execute("DELETE FROM giornate")
        for g in data.get("giornate", []):
            g = dict(g)
            consegne_ids   = g.pop("consegneIds", [])
            consegne_compl = g.pop("consegneCompletate", {})
            known_g = {"id", "data", "squadra"}
            extra_g = {k: v for k, v in g.items() if k not in known_g}
            cur.execute(
                "INSERT INTO giornate (id, data, squadra, extra) VALUES (%s, %s, %s, %s)",
                (g["id"], g.get("data"), g.get("squadra"),
                 json.dumps(extra_g, ensure_ascii=False) if extra_g else None)
            )
            for idx, cid in enumerate(consegne_ids):
                completata = int(consegne_compl.get(cid, False))
                cur.execute(
                    "INSERT INTO giornata_consegne "
                    "(giornata_id, consegna_id, completata, ordine) VALUES (%s, %s, %s, %s)",
                    (g["id"], cid, completata, idx)
                )

        conn.commit()
        log.info("[STORAGE] Dati salvati (mysql)")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# BACKEND POSTGRES
# ═══════════════════════════════════════════════════════════════════════════════

_PG_DDL = """
CREATE TABLE IF NOT EXISTS consegne (
    id              VARCHAR(36)  NOT NULL PRIMARY KEY,
    nome            VARCHAR(255),
    cognome         VARCHAR(255),
    indirizzo       TEXT,
    citta           VARCHAR(255),
    telefono        VARCHAR(50),
    tipo_prodotto   TEXT,
    tipo_consegna   VARCHAR(50),
    stato           VARCHAR(50)  NOT NULL DEFAULT 'in_attesa',
    note            TEXT,
    giorno_consegna VARCHAR(10),
    fascia_oraria   VARCHAR(50),
    data_prenotaz   VARCHAR(10),
    articoli        JSONB,
    extra           JSONB
);

CREATE TABLE IF NOT EXISTS squadre (
    id        VARCHAR(36)  NOT NULL PRIMARY KEY,
    nome      VARCHAR(255) NOT NULL,
    color_idx INTEGER      NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS giornate (
    id      VARCHAR(36) NOT NULL PRIMARY KEY,
    data    VARCHAR(10) NOT NULL,
    squadra VARCHAR(255),
    extra   JSONB
);

CREATE TABLE IF NOT EXISTS giornata_consegne (
    giornata_id  VARCHAR(36) NOT NULL REFERENCES giornate(id)  ON DELETE CASCADE,
    consegna_id  VARCHAR(36) NOT NULL REFERENCES consegne(id) ON DELETE CASCADE,
    completata   BOOLEAN     NOT NULL DEFAULT FALSE,
    ordine       INTEGER     NOT NULL DEFAULT 0,
    PRIMARY KEY (giornata_id, consegna_id)
);
"""


def _pg_connect():
    import psycopg2
    import psycopg2.extras
    cfg = _db_env(5432)
    return psycopg2.connect(
        host=cfg["host"], port=cfg["port"],
        dbname=cfg["database"],
        user=cfg["user"], password=cfg["password"],
    )


def _pg_init():
    import psycopg2
    for attempt in range(10):
        try:
            conn = _pg_connect()
            cur = conn.cursor()
            cur.execute(_PG_DDL)
            conn.commit()
            cur.close()
            conn.close()
            log.info("[STORAGE] Schema PostgreSQL inizializzato")
            return
        except Exception as e:
            log.warning(f"[STORAGE] PostgreSQL non ancora pronto (tentativo {attempt+1}/10): {e}")
            time.sleep(3)
    raise RuntimeError("Impossibile connettersi a PostgreSQL dopo 10 tentativi")


def _pg_read():
    import psycopg2.extras
    conn = _pg_connect()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT * FROM consegne")
    consegne = []
    for row in cur.fetchall():
        c = dict(row)
        c["articoli"] = c.get("articoli") or []
        extra = c.pop("extra", None) or {}
        c.update(extra)
        consegne.append(c)

    cur.execute("SELECT * FROM squadre")
    squadre = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM giornate")
    giornate = []
    for row in cur.fetchall():
        g = dict(row)
        extra = g.pop("extra", None) or {}
        g.update(extra)
        cur.execute(
            "SELECT consegna_id, completata FROM giornata_consegne "
            "WHERE giornata_id = %s ORDER BY ordine",
            (row["id"],)
        )
        links = cur.fetchall()
        g["consegneIds"] = [l["consegna_id"] for l in links]
        g["consegneCompletate"] = {l["consegna_id"]: bool(l["completata"]) for l in links}
        giornate.append(g)

    cur.close()
    conn.close()
    return {"consegne": consegne, "giornate": giornate, "squadre": squadre}


def _pg_write(data):
    conn = _pg_connect()
    cur = conn.cursor()
    try:
        import psycopg2.extras
        cur.execute("DELETE FROM consegne")
        for c in data.get("consegne", []):
            c = dict(c)
            articoli = json.dumps(c.pop("articoli", []), ensure_ascii=False)
            known = {"id","nome","cognome","indirizzo","citta","telefono",
                     "tipo_prodotto","tipo_consegna","stato","note",
                     "giorno_consegna","fascia_oraria","data_prenotaz"}
            extra = {k: v for k, v in c.items() if k not in known}
            cur.execute(
                "INSERT INTO consegne "
                "(id,nome,cognome,indirizzo,citta,telefono,tipo_prodotto,"
                "tipo_consegna,stato,note,giorno_consegna,fascia_oraria,"
                "data_prenotaz,articoli,extra) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)",
                (c.get("id"), c.get("nome"), c.get("cognome"),
                 c.get("indirizzo"), c.get("citta"), c.get("telefono"),
                 c.get("tipoProdotto") or c.get("tipo_prodotto"),
                 c.get("tipoConsegna") or c.get("tipo_consegna"),
                 c.get("stato","in_attesa"), c.get("note"),
                 c.get("giornoConsegna") or c.get("giorno_consegna"),
                 c.get("fasciaOraria") or c.get("fascia_oraria"),
                 c.get("dataPrenotazione") or c.get("data_prenotaz"),
                 articoli,
                 json.dumps(extra, ensure_ascii=False) if extra else None)
            )

        cur.execute("DELETE FROM squadre")
        for s in data.get("squadre", []):
            cur.execute(
                "INSERT INTO squadre (id, nome, color_idx) VALUES (%s, %s, %s)",
                (s["id"], s["nome"], s.get("colorIdx", s.get("color_idx", 0)))
            )

        cur.execute("DELETE FROM giornata_consegne")
        cur.execute("DELETE FROM giornate")
        for g in data.get("giornate", []):
            g = dict(g)
            consegne_ids   = g.pop("consegneIds", [])
            consegne_compl = g.pop("consegneCompletate", {})
            known_g = {"id", "data", "squadra"}
            extra_g = {k: v for k, v in g.items() if k not in known_g}
            cur.execute(
                "INSERT INTO giornate (id, data, squadra, extra) VALUES (%s, %s, %s, %s::jsonb)",
                (g["id"], g.get("data"), g.get("squadra"),
                 json.dumps(extra_g, ensure_ascii=False) if extra_g else None)
            )
            for idx, cid in enumerate(consegne_ids):
                completata = consegne_compl.get(cid, False)
                cur.execute(
                    "INSERT INTO giornata_consegne "
                    "(giornata_id, consegna_id, completata, ordine) VALUES (%s, %s, %s, %s)",
                    (g["id"], cid, completata, idx)
                )

        conn.commit()
        log.info("[STORAGE] Dati salvati (postgres)")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()
