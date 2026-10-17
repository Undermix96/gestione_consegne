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

Interfaccia pubblica V1 (legacy: import_data.py e sorgente di migrate.py):
  init_storage()          — chiamata una volta all'avvio
  read_data()             — restituisce dict {consegne, giornate, squadre}
  write_data(data)        — salva il dict completo
  make_backup()           — snapshot JSON (solo backend json, no-op per DB)

Interfaccia pubblica V2 (accesso per singolo record) — vedi sezione "V2" in fondo:
  init_storage_v2(), list_records(), get_record(), insert_record(), insert_records(),
  update_record(), delete_record(), giornata_assegna/_rimuovi/_riordina(),
  get_meta(), set_meta(), backup_now()
  Eccezioni: StorageError, ConflictError, NotFoundError, DuplicateError, IntegrityError
"""

import copy
import json
import logging
import os
import threading
import time
import glob
from datetime import datetime

log = logging.getLogger(__name__)

BACKEND       = os.environ.get("DB_BACKEND", "json").lower()
DATA_DIR      = os.environ.get("DATA_DIR", "/data")
WRITE_RETRIES = 2
MAX_BACKUPS   = 20
BACKUP_MIN_INTERVAL = 300   # V2 (backend json): al massimo 1 snapshot ogni 5 minuti

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


# ═══════════════════════════════════════════════════════════════════════════════
# V2 — ACCESSO PER SINGOLO RECORD
# ═══════════════════════════════════════════════════════════════════════════════
#
# Principi (vedi AGENTS.md §6):
#  - ogni operazione agisce su un solo record (nessuna riscrittura dell'intera tabella)
#  - optimistic locking atomico nel layer di storage (`versione`)
#  - stessa semantica su json / mysql / postgres: la validazione comune sta qui,
#    i backend implementano solo la persistenza (e i vincoli equivalenti)
#  - un valore None NON viene memorizzato: inserire/aggiornare un campo con None
#    significa "campo assente" (identico su tutti i backend, SQL NULL ≡ chiave mancante)
#  - `id` e `negozio_id` sono forniti dal chiamante; `versione` è gestita dallo storage
#
# Le funzioni V1 (read_data/write_data/...) restano invariate per import_data.py
# e come sorgente di migrate.py.

class StorageError(Exception):
    """Errore di persistenza (I/O, DB non raggiungibile, dati illeggibili)."""

class ConflictError(StorageError):
    """Optimistic locking: la `versione` attesa non coincide con quella salvata (→ 409)."""

class NotFoundError(StorageError):
    """Record o riferimento inesistente (→ 404)."""

class DuplicateError(StorageError):
    """Violazione di unicità (id già presente, username/nome duplicato)."""

class IntegrityError(StorageError):
    """Violazione di integrità referenziale (riferimento inesistente o record ancora referenziato)."""


# Specifica dichiarativa delle collezioni. Una sola fonte di verità per tutti i backend.
#   versioned : ha il campo `versione` (gestito dallo storage)
#   tenant    : appartiene a un negozio (`negozio_id` obbligatorio e immutabile)
#   required  : campi obbligatori (non None) all'inserimento e dopo ogni update
#   defaults  : valori applicati all'inserimento se il campo manca
#   unique    : campi con vincolo di unicità
#   ci        : sottoinsieme dei campi confrontati senza distinguere maiuscole/minuscole
#               (valido per unicità E per i filtri)
#   fks       : {campo: collezione_referenziata}; None è ammesso per i campi non `tenant`
#   reserved  : campi gestiti solo da operazioni dedicate (non modificabili con update_record)
_COLL = {
    "consegne":     dict(versioned=True, tenant=True, defaults={"stato": "in_attesa"}),
    "giornate":     dict(versioned=True, tenant=True, required=("data",),
                         reserved=("consegneIds",)),
    "squadre":      dict(versioned=True, tenant=True, required=("nome",),
                         defaults={"colorIdx": 0}),
    "negozi":       dict(required=("nome",)),
    "tipi_account": dict(required=("nome", "permessi"), unique=("nome",)),
    "utenti":       dict(required=("username", "password_hash"),
                         unique=("username",), ci=("username",),
                         defaults={"is_superadmin": False, "primo_login": True},
                         fks={"negozio_id": "negozi", "tipo_account_id": "tipi_account"}),
}
for _n, _s in _COLL.items():
    _s.setdefault("versioned", False)
    _s.setdefault("tenant", False)
    _s.setdefault("required", ())
    _s.setdefault("defaults", {})
    _s.setdefault("unique", ())
    _s.setdefault("ci", ())
    _s.setdefault("fks", {})
    _s.setdefault("reserved", ())
    if _s["tenant"]:
        _s["fks"] = {**_s["fks"], "negozio_id": "negozi"}

# Chi referenzia cosa (comportamento RESTRICT: non si elimina un record ancora referenziato)
_REFERRERS = {
    "negozi":       [("consegne", "negozio_id"), ("giornate", "negozio_id"),
                     ("squadre", "negozio_id"), ("utenti", "negozio_id")],
    "tipi_account": [("utenti", "tipo_account_id")],
}

# Un campo con default non è rimovibile: è come se fosse obbligatorio (colonna NOT NULL su SQL)
for _n, _s in _COLL.items():
    _s["mandatory"] = tuple(dict.fromkeys(list(_s["required"]) + list(_s["defaults"])))

# Campi tipizzati: (campo, colonna SQL, tipo). Tipi: text | int | bool | json (lista).
# Tutto ciò che NON è elencato (campi "futuri" del frontend) è conservato in `extra`.
# Le colonne SQL sono sempre snake_case; fuori dallo storage le chiavi sono sempre camelCase.
_COLS = {
    "consegne": [("negozio_id", "negozio_id", "text"), ("nome", "nome", "text"),
                 ("cognome", "cognome", "text"), ("indirizzo", "indirizzo", "text"),
                 ("citta", "citta", "text"), ("stato", "stato", "text"), ("note", "note", "text"),
                 ("giornoConsegna", "giorno_consegna", "text"),
                 ("fasciaOraria", "fascia_oraria", "text"),
                 ("dataPrenotazione", "data_prenotaz", "text"), ("articoli", "articoli", "json")],
    "giornate": [("negozio_id", "negozio_id", "text"), ("data", "data", "text"),
                 ("squadra", "squadra", "text")],
    "squadre":  [("negozio_id", "negozio_id", "text"), ("nome", "nome", "text"),
                 ("colorIdx", "color_idx", "int")],
    "negozi":   [("nome", "nome", "text"), ("creato_il", "creato_il", "text")],
    "tipi_account": [("nome", "nome", "text"), ("permessi", "permessi", "json"),
                     ("creato_il", "creato_il", "text"), ("modificato_il", "modificato_il", "text")],
    "utenti":   [("username", "username", "text"), ("password_hash", "password_hash", "text"),
                 ("tipo_account_id", "tipo_account_id", "text"), ("negozio_id", "negozio_id", "text"),
                 ("is_superadmin", "is_superadmin", "bool"), ("primo_login", "primo_login", "bool"),
                 ("creato_da", "creato_da", "text"), ("creato_il", "creato_il", "text"),
                 ("ultimo_accesso", "ultimo_accesso", "text")],
}
_PY_TYPES = {"text": str, "int": int, "bool": bool, "json": list}
_FIELD_TYPES = {c: {f: _PY_TYPES[t] for f, _, t in cols} for c, cols in _COLS.items()}
# Lunghezze massime (le colonne SQL corrispondenti sono VARCHAR(n): servono per indici/unicità).
# Validate dallo storage per TUTTI i backend, così json e SQL accettano gli stessi valori.
_MAXLEN = {"id": 36, "negozio_id": 36, "tipo_account_id": 36, "creato_da": 36,
           "username": 150, "password_hash": 64, "tipi_account.nome": 255}

def _has_nul(v):
    if isinstance(v, str):
        return "\x00" in v
    if isinstance(v, (list, tuple)):
        return any(_has_nul(x) for x in v)
    if isinstance(v, dict):
        return any(_has_nul(k) or _has_nul(x) for k, x in v.items())
    return False

def _check_value(collection, field, value, length=True):
    """Controlli di tipo, lunghezza e NUL, identici per tutti i backend."""
    if value is None:
        return
    exp = _FIELD_TYPES.get(collection, {}).get(field)
    if exp is not None and not (isinstance(value, exp) and (exp is bool or not isinstance(value, bool))):
        raise ValueError(f"{collection}.{field}: atteso {exp.__name__}, ricevuto {type(value).__name__}")
    if length and isinstance(value, str):
        n = _MAXLEN.get(f"{collection}.{field}") or _MAXLEN.get(field)
        if n is not None and len(value) > n:
            raise ValueError(f"{collection}.{field}: lunghezza massima {n} caratteri")
    if _has_nul(value):
        raise ValueError(f"{collection}.{field}: carattere NUL non ammesso")

def _spec(collection):
    try:
        return _COLL[collection]
    except (KeyError, TypeError):
        raise ValueError(f"Collezione sconosciuta: {collection!r}. Valide: {', '.join(_COLL)}")

def _same(spec, field, a, b):
    """Uguaglianza di valori per un campo (case-insensitive se il campo è in `ci`)."""
    if field in spec["ci"] and isinstance(a, str) and isinstance(b, str):
        return a.casefold() == b.casefold()
    return a == b

def _norm_insert(collection, record):
    """Validazione e normalizzazione comuni a tutti i backend. Ritorna una copia pulita."""
    spec = _spec(collection)
    if not isinstance(record, dict):
        raise ValueError("record deve essere un dict")
    rec = {k: copy.deepcopy(v) for k, v in record.items() if v is not None}
    rid = rec.get("id")
    if not isinstance(rid, str) or not rid:
        raise ValueError("record['id'] obbligatorio (stringa non vuota)")
    for k, v in rec.items():
        _check_value(collection, k, v)
    for k, v in spec["defaults"].items():
        rec.setdefault(k, v)
    if collection == "giornate":
        rec.pop("consegneCompletate", None)   # V1: flag mai usato da frontend/server
        ids = rec.get("consegneIds", [])
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("consegneIds deve essere una lista di id distinti")
        rec["consegneIds"] = list(ids)
    if spec["versioned"]:
        rec["versione"] = 1
    for f in spec["mandatory"]:
        if rec.get(f) is None:
            raise ValueError(f"Campo obbligatorio mancante: {f}")
    if spec["tenant"] and not rec.get("negozio_id"):
        raise ValueError("negozio_id obbligatorio")
    return rec

def _norm_changes(collection, changes):
    spec = _spec(collection)
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes deve essere un dict non vuoto")
    forbidden = {"id", "versione"} | set(spec["reserved"])
    if spec["tenant"]:
        forbidden.add("negozio_id")
    bad = forbidden & set(changes)
    if bad:
        raise ValueError(f"Campi non modificabili con update_record: {sorted(bad)}")
    if collection == "giornate" and "consegneCompletate" in changes:
        raise ValueError("consegneCompletate non è più supportato")
    for k, v in changes.items():
        _check_value(collection, k, v)
    return {k: copy.deepcopy(v) for k, v in changes.items()}

def _apply_changes(collection, cur, changes):
    """Merge di `changes` sul record corrente `cur` (None rimuove il campo), controllo dei campi
    obbligatori e incremento di `versione`. Condiviso da TUTTI i backend: la logica di merge
    è scritta una volta sola."""
    spec = _spec(collection)
    new = dict(cur)
    for k, v in changes.items():
        if v is None:
            new.pop(k, None)
        else:
            new[k] = v
    for f in spec["mandatory"]:
        if new.get(f) is None:
            raise ValueError(f"Campo obbligatorio mancante: {f}")
    if spec["versioned"]:
        new["versione"] = cur.get("versione", 1) + 1
    return new

def _norm_filters(collection, filters):
    spec = _spec(collection)
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters deve essere un dict {campo: valore}")
    # Filtrabili: id, versione (se prevista) e i campi tipizzati scalari. I campi "extra" no:
    # su SQL non sono colonne, e json e SQL devono accettare gli stessi filtri.
    allowed = {"id"} | {f for f, t in _FIELD_TYPES[collection].items() if t is not list}
    if spec["versioned"]:
        allowed.add("versione")
    for k, v in filters.items():
        if k not in allowed:
            raise ValueError(f"Filtro non supportato su '{k}' (ammessi: {', '.join(sorted(allowed))})")
        if v is not None:
            if k == "versione":
                if not isinstance(v, int) or isinstance(v, bool):
                    raise ValueError("filtro 'versione': atteso int")
            elif k == "id":
                if not isinstance(v, str):
                    raise ValueError("filtro 'id': atteso str")
            else:
                _check_value(collection, k, v, length=False)
    return dict(filters)


class _JsonV2:
    """Backend JSON V2: un file `<collezione>.json` (array di record) per collezione + meta.json.

    Lock unico (RLock) per tutte le operazioni: il carico è minimo e un solo lock esclude
    i deadlock tra collezioni. Scrittura atomica (.tmp + fsync + os.replace). Un file
    illeggibile solleva StorageError: non si restituisce mai un default che verrebbe
    poi riscritto sopra i dati.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._last_backup = 0.0
        os.makedirs(self._dir(), exist_ok=True)
        os.makedirs(os.path.join(self._dir(), "backup"), exist_ok=True)
        for name in _COLL:
            if not os.path.exists(self._path(name)):
                self._write_file(self._path(name), [])
                log.info(f"[STORAGE] Creato {self._path(name)} (vuoto)")
        if not os.path.exists(self._meta_path()):
            self._write_file(self._meta_path(), {})

    # ── file ────────────────────────────────────────────────────────────────
    def _dir(self):              return DATA_DIR            # letto a ogni uso (testabile)
    def _path(self, name):       return os.path.join(self._dir(), f"{name}.json")
    def _meta_path(self):        return os.path.join(self._dir(), "meta.json")

    def _read_file(self, path, default, kind):
        last = None
        for attempt in range(WRITE_RETRIES):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, kind):
                    raise ValueError(f"contenuto inatteso ({type(data).__name__})")
                return data
            except FileNotFoundError:
                return default
            except Exception as e:
                last = e
                log.error(f"[STORAGE] Errore lettura {path} (tentativo {attempt+1}): {e}")
                if attempt < WRITE_RETRIES - 1:
                    time.sleep(0.3)
        raise StorageError(f"Impossibile leggere {path}: {last}")

    def _write_file(self, path, data):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    def _read(self, name):
        return self._read_file(self._path(name), [], list)

    def _write(self, name, rows):
        self._write_with_retry(self._path(name), rows)

    def _write_with_retry(self, path, data):
        last = None
        for attempt in range(WRITE_RETRIES):
            try:
                self._write_file(path, data)
                return
            except Exception as e:
                last = e
                log.error(f"[STORAGE] Errore scrittura {path} (tentativo {attempt+1}): {e}")
                if attempt < WRITE_RETRIES - 1:
                    time.sleep(0.3)
        raise StorageError(f"Scrittura fallita su {path}: {last}")

    # ── backup ──────────────────────────────────────────────────────────────
    def backup_now(self):
        """Snapshot di tutte le collezioni e di meta.json. Non critico: logga e prosegue."""
        try:
            bdir = os.path.join(self._dir(), "backup")
            os.makedirs(bdir, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            for key in list(_COLL) + ["meta"]:
                src = os.path.join(self._dir(), f"{key}.json")
                if not os.path.exists(src):
                    continue
                with open(src, "r", encoding="utf-8") as f:
                    content = f.read()
                with open(os.path.join(bdir, f"{key}.{ts}.json"), "w", encoding="utf-8") as f:
                    f.write(content)
                old = sorted(glob.glob(os.path.join(bdir, f"{key}.*.json")))
                while len(old) > MAX_BACKUPS:
                    os.remove(old.pop(0))
            self._last_backup = time.time()
            return True
        except Exception as e:
            log.warning(f"[STORAGE] Backup fallito (non critico): {e}")
            return False

    def _maybe_backup(self):
        if time.time() - self._last_backup >= BACKUP_MIN_INTERVAL:
            self.backup_now()

    # ── controlli di integrità ──────────────────────────────────────────────
    def _check_fks(self, name, rec, only=None):
        for field, target in _spec(name)["fks"].items():
            if only is not None and field not in only:
                continue
            val = rec.get(field)
            if val is None:
                continue
            if not any(r.get("id") == val for r in self._read(target)):
                raise IntegrityError(f"{name}.{field}: {target} '{val}' inesistente")

    def _check_unique(self, name, rows, rec, exclude_id=None):
        spec = _spec(name)
        for f in spec["unique"]:
            val = rec.get(f)
            if val is None:
                continue
            for r in rows:
                if r.get("id") != exclude_id and _same(spec, f, r.get(f), val):
                    raise DuplicateError(f"{name}.{f}: valore già presente ('{val}')")

    # ── lettura ─────────────────────────────────────────────────────────────
    def list(self, name, filters):
        spec = _spec(name)
        with self._lock:
            rows = self._read(name)
        return [r for r in rows
                if all(_same(spec, k, r.get(k), v) for k, v in filters.items())]

    def get(self, name, rid):
        with self._lock:
            for r in self._read(name):
                if r.get("id") == rid:
                    return r
        return None

    # ── scrittura ───────────────────────────────────────────────────────────
    def insert_many(self, name, recs):
        with self._lock:
            rows = self._read(name)
            seen = {r.get("id") for r in rows}
            staged = list(rows)
            for rec in recs:
                if rec["id"] in seen:
                    raise DuplicateError(f"{name}: id '{rec['id']}' già presente")
                self._check_fks(name, rec)
                self._check_unique(name, staged, rec)
                if name == "giornate":
                    self._check_giornata_members(rec, rec["consegneIds"])
                seen.add(rec["id"])
                staged.append(rec)
            self._maybe_backup()
            self._write(name, staged)
        return [copy.deepcopy(r) for r in recs]

    def update(self, name, rid, changes, expected_versione):
        with self._lock:
            rows = self._read(name)
            idx = next((i for i, r in enumerate(rows) if r.get("id") == rid), None)
            if idx is None:
                raise NotFoundError(f"{name}: id '{rid}' inesistente")
            cur = rows[idx]
            if expected_versione is not None and cur.get("versione") != expected_versione:
                raise ConflictError(
                    f"{name} '{rid}': versione attesa {expected_versione}, salvata {cur.get('versione')}")
            new = _apply_changes(name, cur, changes)
            self._check_fks(name, new, only=set(changes))
            self._check_unique(name, rows, new, exclude_id=rid)
            rows[idx] = new
            self._maybe_backup()
            self._write(name, rows)
            return copy.deepcopy(new)

    def delete(self, name, rid):
        with self._lock:
            rows = self._read(name)
            idx = next((i for i, r in enumerate(rows) if r.get("id") == rid), None)
            if idx is None:
                return False
            for rname, field in _REFERRERS.get(name, []):
                if any(r.get(field) == rid for r in self._read(rname)):
                    raise IntegrityError(f"{name} '{rid}' è ancora referenziato da {rname}.{field}")
            self._maybe_backup()
            if name == "consegne":
                # Equivalente di ON DELETE CASCADE sul collegamento giornata↔consegna.
                # Si scrivono prima le giornate: se si interrompe qui resta una consegna
                # non assegnata (recuperabile), mai un riferimento orfano.
                giornate = self._read("giornate")
                changed = False
                for g in giornate:
                    if rid in g.get("consegneIds", []):
                        g["consegneIds"] = [c for c in g["consegneIds"] if c != rid]
                        changed = True
                if changed:
                    self._write("giornate", giornate)
            del rows[idx]
            self._write(name, rows)
            return True

    # ── giornate ↔ consegne ─────────────────────────────────────────────────
    def _check_giornata_members(self, giornata, consegna_ids):
        if not consegna_ids:
            return
        consegne = {r["id"]: r for r in self._read("consegne")}
        for cid in consegna_ids:
            c = consegne.get(cid)
            if c is None:
                raise NotFoundError(f"consegna '{cid}' inesistente")
            if c.get("negozio_id") != giornata.get("negozio_id"):
                raise ValueError(f"consegna '{cid}' appartiene a un altro negozio")

    def _giornata_op(self, gid, fn):
        with self._lock:
            rows = self._read("giornate")
            idx = next((i for i, r in enumerate(rows) if r.get("id") == gid), None)
            if idx is None:
                raise NotFoundError(f"giornate: id '{gid}' inesistente")
            g = dict(rows[idx])
            g["consegneIds"] = list(g.get("consegneIds", []))
            fn(g)
            rows[idx] = g
            self._maybe_backup()
            self._write("giornate", rows)
            return copy.deepcopy(g)

    def giornata_assegna(self, gid, consegna_ids):
        def op(g):
            self._check_giornata_members(g, consegna_ids)
            for cid in consegna_ids:
                if cid not in g["consegneIds"]:
                    g["consegneIds"].append(cid)
        return self._giornata_op(gid, op)

    def giornata_rimuovi(self, gid, consegna_id):
        def op(g):
            g["consegneIds"] = [c for c in g["consegneIds"] if c != consegna_id]
        return self._giornata_op(gid, op)

    def giornata_riordina(self, gid, ordered_ids):
        def op(g):
            if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(g["consegneIds"]):
                raise ValueError("riordina richiede una permutazione esatta delle consegne della giornata")
            g["consegneIds"] = list(ordered_ids)
        return self._giornata_op(gid, op)

    # ── meta ────────────────────────────────────────────────────────────────
    def get_meta(self, key, default):
        with self._lock:
            return self._read_file(self._meta_path(), {}, dict).get(key, default)

    def set_meta(self, key, value):
        with self._lock:
            meta = self._read_file(self._meta_path(), {}, dict)
            meta[key] = value
            self._write_with_retry(self._meta_path(), meta)

    # ── solo test ───────────────────────────────────────────────────────────
    def reset_for_tests(self):
        with self._lock:
            for name in _COLL:
                self._write_file(self._path(name), [])
            self._write_file(self._meta_path(), {})
            self._last_backup = 0.0


# ─── BACKEND SQL V2: base comune + PostgreSQL ────────────────────────────────

def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class _Tbl:
    """Metadati di una tabella, derivati dalla specifica (_COLL + _COLS)."""
    def __init__(self, name):
        self.name = name
        self.spec = _spec(name)
        self.cols = _COLS[name]                           # [(campo, colonna, tipo)]
        self.fieldcol = {f: c for f, c, _ in self.cols}
        self.known = {f for f, _, _ in self.cols} | {"id"}
        if self.spec["versioned"]:
            self.known.add("versione")
        if name == "giornate":
            self.known.add("consegneIds")                 # vive nella tabella di join
        self.select = (["id"] + [c for _, c, _ in self.cols]
                       + (["versione"] if self.spec["versioned"] else []) + ["extra"])


class _SqlV2:
    """Logica comune ai backend SQL. Le sottoclassi forniscono solo il dialetto (connessione,
    tipi, adattamento JSON, mappatura errori, upsert dei metadati).

    Concorrenza: ogni operazione è una transazione. L'optimistic locking è atomico perché
    la riga viene bloccata (SELECT ... FOR UPDATE) prima di confrontare `versione` e
    aggiornare; il merge dei campi è lo stesso codice del backend json (_apply_changes).
    Le chiavi in uscita sono sempre camelCase, nessuna chiave snake_case esce da qui.
    """
    T_ID = "VARCHAR(36)"
    T_JSON = None
    SEQ_DEF = None
    FOR_UPDATE = " FOR UPDATE"
    FOR_SHARE = " FOR SHARE"
    _TABLE_ORDER = ["negozi", "tipi_account", "utenti", "consegne", "giornate", "squadre"]

    def __init__(self):
        self.T = {n: _Tbl(n) for n in _COLL}
        self._init_schema()

    # ── da implementare nel dialetto ───────────────────────────────────────
    def _connect(self):               raise NotImplementedError
    def _adapt_json(self, obj):       raise NotImplementedError
    def _parse_json(self, v):         raise NotImplementedError
    def _map_error(self, e):          raise NotImplementedError
    def _upsert_meta(self, cur, k, v): raise NotImplementedError
    def _extra_ddl(self):             return []

    # ── connessione / transazione ──────────────────────────────────────────
    def _open(self):
        last = None
        for attempt in range(WRITE_RETRIES):
            try:
                return self._connect()
            except Exception as e:
                last = e
                log.error(f"[STORAGE] Connessione DB fallita (tentativo {attempt+1}): {e}")
                if attempt < WRITE_RETRIES - 1:
                    time.sleep(0.3)
        raise StorageError(f"Connessione al database fallita: {last}")

    def _tx(self, fn):
        conn = self._open()
        try:
            cur = conn.cursor()
            res = fn(cur)
            conn.commit()
            return res
        except (StorageError, ValueError):
            self._safe_rollback(conn)
            raise
        except Exception as e:
            self._safe_rollback(conn)
            raise self._map_error(e) from e
        finally:
            try:
                conn.close()
            except Exception:
                pass

    @staticmethod
    def _safe_rollback(conn):
        try:
            conn.rollback()
        except Exception:
            pass

    # ── schema ─────────────────────────────────────────────────────────────
    def _sqltype(self, name, field, tipo):
        if tipo == "int":
            return "INTEGER"
        if tipo == "bool":
            return "BOOLEAN"
        if tipo == "json":
            return self.T_JSON
        n = _MAXLEN.get(f"{name}.{field}") or _MAXLEN.get(field)
        return f"VARCHAR({n})" if n else "TEXT"

    def _ddl_statements(self):
        stmts = []
        for name in self._TABLE_ORDER:
            t, spec = self.T[name], self.T[name].spec
            lines = [f"id {self.T_ID} PRIMARY KEY", f"seq {self.SEQ_DEF}"]
            for field, col, tipo in t.cols:
                notnull = field in spec["mandatory"] or (field == "negozio_id" and spec["tenant"])
                lines.append(f"{col} {self._sqltype(name, field, tipo)}{' NOT NULL' if notnull else ''}")
            for f in spec["ci"]:
                lines.append(f"{f}_ci {self._sqltype(name, f, 'text')} NOT NULL UNIQUE")
            if spec["versioned"]:
                lines.append("versione INTEGER NOT NULL DEFAULT 1")
            lines.append(f"extra {self.T_JSON}")
            for f in spec["unique"]:
                if f not in spec["ci"]:
                    lines.append(f"UNIQUE ({t.fieldcol[f]})")
            for f, target in spec["fks"].items():
                lines.append(f"FOREIGN KEY ({t.fieldcol[f]}) REFERENCES {target}(id) ON DELETE RESTRICT")
            stmts.append(f"CREATE TABLE IF NOT EXISTS {name} (\n    " + ",\n    ".join(lines) + "\n)")
        stmts.append(
            f"CREATE TABLE IF NOT EXISTS giornata_consegne (\n"
            f"    giornata_id {self.T_ID} NOT NULL,\n    consegna_id {self.T_ID} NOT NULL,\n"
            f"    ordine INTEGER NOT NULL,\n    PRIMARY KEY (giornata_id, consegna_id),\n"
            f"    FOREIGN KEY (giornata_id) REFERENCES giornate(id) ON DELETE CASCADE,\n"
            f"    FOREIGN KEY (consegna_id) REFERENCES consegne(id) ON DELETE CASCADE\n)")
        stmts.append(f"CREATE TABLE IF NOT EXISTS meta (\n    chiave VARCHAR(100) PRIMARY KEY,\n"
                     f"    valore {self.T_JSON} NOT NULL\n)")
        return stmts + self._extra_ddl()

    def _init_schema(self):
        last = None
        for attempt in range(10):
            try:
                conn = self._connect()
                break
            except Exception as e:
                last = e
                log.warning(f"[STORAGE] DB non pronto (tentativo {attempt+1}/10): {e}")
                time.sleep(3)
        else:
            raise StorageError(f"Impossibile connettersi al database dopo 10 tentativi: {last}")
        try:
            cur = conn.cursor()
            for stmt in self._ddl_statements():
                cur.execute(stmt)
            conn.commit()
            log.info("[STORAGE] Schema V2 verificato/creato")
        except Exception as e:
            self._safe_rollback(conn)
            raise self._map_error(e) from e
        finally:
            conn.close()

    # ── conversione record ↔ riga ──────────────────────────────────────────
    def _row_values(self, t, rec):
        vals = {"id": rec["id"]}
        for field, col, tipo in t.cols:
            v = rec.get(field)
            vals[col] = self._adapt_json(v) if (tipo == "json" and v is not None) else v
        for f in t.spec["ci"]:
            v = rec.get(f)
            vals[f"{f}_ci"] = v.casefold() if isinstance(v, str) else v
        if t.spec["versioned"]:
            vals["versione"] = rec["versione"]
        extra = {k: v for k, v in rec.items() if k not in t.known}
        vals["extra"] = self._adapt_json(extra) if extra else None
        return vals

    def _from_row(self, t, row):
        rec = {"id": row[0]}
        i = 1
        for field, _, tipo in t.cols:
            v = row[i]
            i += 1
            if v is None:
                continue
            if tipo == "json":
                v = self._parse_json(v)
            elif tipo == "bool":
                v = bool(v)
            elif tipo == "int":
                v = int(v)
            rec[field] = v
        if t.spec["versioned"]:
            rec["versione"] = row[i]
            i += 1
        if row[i]:
            rec.update(self._parse_json(row[i]))
        return rec

    def _select_sql(self, t):
        return f"SELECT {', '.join(t.select)} FROM {t.name}"

    def _attach_links(self, cur, recs):
        byid = {r["id"]: r for r in recs}
        for r in recs:
            r["consegneIds"] = []
        for chunk in _chunks(list(byid), 500):
            ph = ",".join(["%s"] * len(chunk))
            cur.execute(f"SELECT giornata_id, consegna_id FROM giornata_consegne "
                        f"WHERE giornata_id IN ({ph}) ORDER BY giornata_id, ordine", chunk)
            for gid, cid in cur.fetchall():
                byid[gid]["consegneIds"].append(cid)

    def _check_members(self, cur, negozio_id, ids):
        if not ids:
            return
        ph = ",".join(["%s"] * len(ids))
        cur.execute(f"SELECT id, negozio_id FROM consegne WHERE id IN ({ph}){self.FOR_SHARE}", list(ids))
        found = {r[0]: r[1] for r in cur.fetchall()}
        for cid in ids:
            if cid not in found:
                raise NotFoundError(f"consegna '{cid}' inesistente")
            if found[cid] != negozio_id:
                raise ValueError(f"consegna '{cid}' appartiene a un altro negozio")

    # ── lettura ────────────────────────────────────────────────────────────
    def list(self, name, filters):
        t = self.T[name]

        def fn(cur):
            where, params = [], []
            for k, v in filters.items():
                if k in t.spec["ci"]:
                    col = f"{k}_ci"
                    v = v.casefold() if isinstance(v, str) else v
                elif k in ("id", "versione"):
                    col = k
                else:
                    col = t.fieldcol[k]
                if v is None:
                    where.append(f"{col} IS NULL")
                else:
                    where.append(f"{col} = %s")
                    params.append(v)
            sql = self._select_sql(t) + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY seq"
            cur.execute(sql, params)
            recs = [self._from_row(t, r) for r in cur.fetchall()]
            if name == "giornate":
                self._attach_links(cur, recs)
            return recs
        return self._tx(fn)

    def get(self, name, rid):
        t = self.T[name]

        def fn(cur):
            cur.execute(self._select_sql(t) + " WHERE id = %s", (rid,))
            row = cur.fetchone()
            if row is None:
                return None
            rec = self._from_row(t, row)
            if name == "giornate":
                self._attach_links(cur, [rec])
            return rec
        return self._tx(fn)

    # ── scrittura ──────────────────────────────────────────────────────────
    def insert_many(self, name, recs):
        t = self.T[name]

        def fn(cur):
            for rec in recs:
                if name == "giornate":
                    self._check_members(cur, rec["negozio_id"], rec["consegneIds"])
                vals = self._row_values(t, rec)
                cols = list(vals)
                cur.execute(f"INSERT INTO {name} ({', '.join(cols)}) "
                            f"VALUES ({', '.join(['%s'] * len(cols))})", list(vals.values()))
                if name == "giornate":
                    for i, cid in enumerate(rec["consegneIds"]):
                        cur.execute("INSERT INTO giornata_consegne (giornata_id, consegna_id, ordine) "
                                    "VALUES (%s, %s, %s)", (rec["id"], cid, i))
            return [copy.deepcopy(r) for r in recs]
        return self._tx(fn)

    def update(self, name, rid, changes, expected_versione):
        t = self.T[name]

        def fn(cur):
            cur.execute(self._select_sql(t) + " WHERE id = %s" + self.FOR_UPDATE, (rid,))
            row = cur.fetchone()
            if row is None:
                raise NotFoundError(f"{name}: id '{rid}' inesistente")
            current = self._from_row(t, row)
            if name == "giornate":
                self._attach_links(cur, [current])
            if expected_versione is not None and current.get("versione") != expected_versione:
                raise ConflictError(f"{name} '{rid}': versione attesa {expected_versione}, "
                                    f"salvata {current.get('versione')}")
            new = _apply_changes(name, current, changes)
            vals = self._row_values(t, new)
            vals.pop("id")
            cur.execute(f"UPDATE {name} SET {', '.join(c + ' = %s' for c in vals)} WHERE id = %s",
                        list(vals.values()) + [rid])
            return new
        return self._tx(fn)

    def delete(self, name, rid):
        def fn(cur):
            cur.execute(f"DELETE FROM {name} WHERE id = %s", (rid,))
            return cur.rowcount > 0
        return self._tx(fn)

    # ── giornate ↔ consegne ────────────────────────────────────────────────
    def _giornata_tx(self, gid, apply):
        t = self.T["giornate"]

        def fn(cur):
            cur.execute("SELECT id, negozio_id FROM giornate WHERE id = %s" + self.FOR_UPDATE, (gid,))
            row = cur.fetchone()
            if row is None:
                raise NotFoundError(f"giornate: id '{gid}' inesistente")
            cur.execute("SELECT consegna_id FROM giornata_consegne WHERE giornata_id = %s ORDER BY ordine", (gid,))
            apply(cur, row[1], [r[0] for r in cur.fetchall()])
            cur.execute(self._select_sql(t) + " WHERE id = %s", (gid,))
            rec = self._from_row(t, cur.fetchone())
            self._attach_links(cur, [rec])
            return rec
        return self._tx(fn)

    def giornata_assegna(self, gid, consegna_ids):
        def apply(cur, negozio_id, ids):
            self._check_members(cur, negozio_id, consegna_ids)
            cur.execute("SELECT COALESCE(MAX(ordine), -1) FROM giornata_consegne WHERE giornata_id = %s", (gid,))
            nxt = cur.fetchone()[0] + 1
            present = set(ids)
            for cid in consegna_ids:
                if cid not in present:
                    cur.execute("INSERT INTO giornata_consegne (giornata_id, consegna_id, ordine) "
                                "VALUES (%s, %s, %s)", (gid, cid, nxt))
                    present.add(cid)
                    nxt += 1
        return self._giornata_tx(gid, apply)

    def giornata_rimuovi(self, gid, consegna_id):
        def apply(cur, negozio_id, ids):
            cur.execute("DELETE FROM giornata_consegne WHERE giornata_id = %s AND consegna_id = %s",
                        (gid, consegna_id))
        return self._giornata_tx(gid, apply)

    def giornata_riordina(self, gid, ordered_ids):
        def apply(cur, negozio_id, ids):
            if len(ordered_ids) != len(set(ordered_ids)) or set(ordered_ids) != set(ids):
                raise ValueError("riordina richiede una permutazione esatta delle consegne della giornata")
            for i, cid in enumerate(ordered_ids):
                cur.execute("UPDATE giornata_consegne SET ordine = %s WHERE giornata_id = %s AND consegna_id = %s",
                            (i, gid, cid))
        return self._giornata_tx(gid, apply)

    # ── meta ───────────────────────────────────────────────────────────────
    def get_meta(self, key, default):
        def fn(cur):
            cur.execute("SELECT valore FROM meta WHERE chiave = %s", (key,))
            row = cur.fetchone()
            return default if row is None else self._parse_json(row[0])
        return self._tx(fn)

    def set_meta(self, key, value):
        self._tx(lambda cur: self._upsert_meta(cur, key, value))

    # ── manutenzione / test ────────────────────────────────────────────────
    def backup_now(self):
        return True            # i backend DB non fanno snapshot JSON (usare gli strumenti del DB)

    def reset_for_tests(self):
        if not os.environ.get("DB_NAME", "").endswith("_test"):
            raise StorageError("reset per i test rifiutato: DB_NAME deve terminare con '_test'")

        def fn(cur):
            for tbl in ["giornata_consegne", "giornate", "consegne", "squadre", "utenti",
                        "tipi_account", "negozi", "meta"]:
                cur.execute(f"DELETE FROM {tbl}")
        self._tx(fn)


class _PgV2(_SqlV2):
    """PostgreSQL (psycopg2). JSONB per i campi lista e per `extra`."""
    T_JSON = "JSONB"
    SEQ_DEF = "BIGSERIAL NOT NULL UNIQUE"

    def _connect(self):
        return _pg_connect()

    def _adapt_json(self, obj):
        from psycopg2.extras import Json
        return Json(obj, dumps=lambda o: json.dumps(o, ensure_ascii=False))

    def _parse_json(self, v):
        return v                      # psycopg2 decodifica già JSONB in oggetti Python

    def _extra_ddl(self):
        stmts = []
        for name in self._TABLE_ORDER:
            t = self.T[name]
            for field in t.spec["fks"]:
                col = t.fieldcol[field]
                stmts.append(f"CREATE INDEX IF NOT EXISTS ix_{name}_{col} ON {name} ({col})")
        stmts.append("CREATE INDEX IF NOT EXISTS ix_giornata_consegne_consegna ON giornata_consegne (consegna_id)")
        return stmts

    def _upsert_meta(self, cur, key, value):
        cur.execute("INSERT INTO meta (chiave, valore) VALUES (%s, %s) "
                    "ON CONFLICT (chiave) DO UPDATE SET valore = EXCLUDED.valore",
                    (key, self._adapt_json(value)))

    def _map_error(self, e):
        code = getattr(e, "pgcode", None)
        lines = str(e).strip().splitlines()
        msg = lines[0] if lines else repr(e)
        if code == "23505":
            return DuplicateError(msg)
        if code == "23503":
            return IntegrityError(msg)
        if code and (code.startswith("22") or code in ("23502", "23514")):
            return ValueError(msg)
        return StorageError(f"Errore database: {msg}")


# ─── API PUBBLICA V2 ─────────────────────────────────────────────────────────

_v2 = None

def init_storage_v2():
    """Inizializza il backend V2 (da chiamare una volta all'avvio; il server V2 usa questa
    al posto di init_storage()). Marcatore di schema e rifiuto di dati V1: passo 1d."""
    global _v2
    if BACKEND == "json":
        _v2 = _JsonV2()
    elif BACKEND == "postgres":
        _v2 = _PgV2()
    elif BACKEND == "mysql":
        raise NotImplementedError("Backend V2 'mysql' non ancora implementato (passo 1c)")
    else:
        raise ValueError(f"DB_BACKEND non valido: '{BACKEND}'. Valori accettati: json, mysql, postgres")
    log.info(f"[STORAGE] Backend V2 attivo: {BACKEND}")

def _be():
    if _v2 is None:
        raise StorageError("Storage V2 non inizializzato: chiamare init_storage_v2()")
    return _v2

def list_records(collection, filters=None):
    """Lista dei record, in ordine di inserimento. `filters`: uguaglianza campo→valore
    (case-insensitive per i campi `ci`, es. utenti.username)."""
    return _be().list(collection, _norm_filters(collection, filters))

def get_record(collection, rid):
    """Il record con quell'id, oppure None."""
    _spec(collection)
    return _be().get(collection, rid)

def insert_record(collection, record):
    """Inserisce un record (con `id` fornito). Imposta versione=1 dove prevista.
    Raises: DuplicateError, IntegrityError, ValueError."""
    return _be().insert_many(collection, [_norm_insert(collection, record)])[0]

def insert_records(collection, records):
    """Inserimento di più record di una collezione in un'unica operazione tutto-o-niente."""
    recs = [_norm_insert(collection, r) for r in records]
    if not recs:
        return []
    return _be().insert_many(collection, recs)

def update_record(collection, rid, changes, expected_versione=None):
    """Aggiorna (merge) i campi indicati. Un valore None RIMUOVE il campo.
    Se `expected_versione` è dato e non coincide → ConflictError. Incrementa `versione`.
    Raises: NotFoundError, ConflictError, DuplicateError, IntegrityError, ValueError."""
    return _be().update(collection, rid, _norm_changes(collection, changes), expected_versione)

def delete_record(collection, rid):
    """Elimina un record. True se eliminato, False se non esisteva.
    consegne: viene tolta da tutte le giornate. negozi/tipi_account ancora referenziati → IntegrityError."""
    _spec(collection)
    return _be().delete(collection, rid)

def giornata_assegna(giornata_id, consegna_ids):
    """Aggiunge consegne in coda alla giornata (idempotente). NON modifica `versione`.
    Raises: NotFoundError (giornata/consegna), ValueError (consegna di un altro negozio)."""
    if not isinstance(consegna_ids, list) or not all(isinstance(c, str) for c in consegna_ids):
        raise ValueError("consegna_ids deve essere una lista di id")
    return _be().giornata_assegna(giornata_id, consegna_ids)

def giornata_rimuovi(giornata_id, consegna_id):
    """Toglie la consegna dalla giornata (nessun errore se non c'era). NON modifica `versione`."""
    return _be().giornata_rimuovi(giornata_id, consegna_id)

def giornata_riordina(giornata_id, ordered_ids):
    """Imposta l'ordine delle consegne; deve essere una permutazione esatta. NON modifica `versione`."""
    if not isinstance(ordered_ids, list):
        raise ValueError("ordered_ids deve essere una lista")
    return _be().giornata_riordina(giornata_id, ordered_ids)

def get_meta(key, default=None):
    """Valore di metadati (es. schema_version, flag migrazione)."""
    return _be().get_meta(key, default)

def set_meta(key, value):
    _be().set_meta(key, value)

def backup_now():
    """Snapshot immediato (backend json); no-op per i backend DB. Usato prima di una migrazione."""
    be = _be()
    return be.backup_now() if hasattr(be, "backup_now") else True

def _test_reset():
    """SOLO PER I TEST: svuota tutto. Rifiuta di agire se STORAGE_ALLOW_TEST_RESET != 1."""
    if os.environ.get("STORAGE_ALLOW_TEST_RESET") != "1":
        raise StorageError("_test_reset non consentito (STORAGE_ALLOW_TEST_RESET != 1)")
    _be().reset_for_tests()
