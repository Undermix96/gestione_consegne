#!/usr/bin/env python3
"""
migrate.py — Migrazione dei dati verso la V2 (e tra backend)

Porta i dati in un archivio V2 NUOVO (cartella dati o database vuoti):
  - sorgente V1 (json | mysql | postgres)         --source-kind v1   (default)
  - dati.json della versione Windows              --source-kind file
  - sorgente V2 (cambio di backend, json | mysql | postgres)   --source-kind v2

La destinazione è sempre il backend configurato per l'app (DB_BACKEND, DATA_DIR, DB_HOST, DB_PORT,
DB_NAME, DB_USER, DB_PASSWORD): lo stesso che userà il server V2. La sorgente si indica con le
variabili SRC_* (vedi sotto), mai come argomenti (le password non devono comparire in `ps`).

Tutto è configurabile con variabili d'ambiente, così funziona allo stesso modo con docker compose,
con `docker run` e dalla GUI di Docker (DSM, Portainer): ogni opzione ha un equivalente MIGRATE_*.
Senza argomenti esegue il comando `run`.

SICUREZZA: senza --execute (MIGRATE_EXECUTE=1) NON scrive nulla nella destinazione: legge la
sorgente, convalida tutto e stampa un rapporto. La sorgente non viene mai modificata.

Comandi
  run      esporta la sorgente in un file e importa nella destinazione (default)
  export   solo esportazione (il file è anche il backup completo della sorgente)
  import   solo importazione, da un file prodotto da `export`

Variabili d'ambiente della SORGENTE
  SRC_BACKEND      json | mysql | postgres          (default: json)    [kind v1 e v2]
  SRC_DATA_DIR     cartella dei file json           (default: /source) [backend json]
  SRC_DB_HOST/PORT/NAME/USER/PASSWORD               [backend mysql/postgres; host, porta, utente e
                   password, se omessi, valgono quelli della destinazione (DB_*); il nome no]
  SRC_FILE         dati.json                        (default: /source/dati.json) [kind file]

Opzioni (argomento / variabile)
  --source-kind     MIGRATE_SOURCE_KIND   v1 | file | v2                  (default v1)
  --execute         MIGRATE_EXECUTE       1 = scrive davvero              (default: solo rapporto)
  --out FILE        MIGRATE_OUT           file di esportazione            (default /migration/export-<data>.json)
  --in FILE         MIGRATE_IN            file da importare (comando import)
  --negozio-nome    MIGRATE_NEGOZIO_NOME  nome del negozio creato da V1   (default "Negozio principale")
  --non-assegnata  MIGRATE_SQUADRA_NON_ASSEGNATA  nome della squadra per le giornate V1 senza squadra, creata
                                          SOLO se serve (default "Non assegnata")
  --create-db       MIGRATE_CREATE_DB     1 = crea il database di destinazione se non esiste (mysql/postgres)
  --keep-orphans    MIGRATE_KEEP_ORPHANS  1 = i riferimenti a consegne inesistenti bloccano la migrazione
                                          (default: vengono scartati e riportati nel rapporto)

Codici di uscita: 0 ok · 1 errore · 2 dati non validi o destinazione non utilizzabile · 3 ambiente
(cartella non scrivibile, database non raggiungibile).
"""

import argparse
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime

log = logging.getLogger("migrate")

EXPORT_FORMAT = "gestione-consegne-export"
COLLECTIONS_V1 = ("squadre", "consegne", "giornate")
# ordine di inserimento: i riferimenti (negozio, tipo account) vengono prima di chi li usa
COLLECTIONS_V2 = ("negozi", "tipi_account", "utenti", "squadre", "consegne", "giornate")
STATI = {"in_attesa", "da_confermare", "programmata", "completata", "annullata", "da_riprogrammare"}
FLAG = "migrazione_in_corso"
MAX_SHOWN = 25   # righe mostrate per ogni elenco del rapporto


class MigrateError(Exception):
    code = 1

class Refused(MigrateError):          # dati non validi o destinazione non utilizzabile
    code = 2

class PreflightError(MigrateError):   # ambiente: cartelle, database
    code = 3


# ─── CONFIGURAZIONE ──────────────────────────────────────────────────────────

def truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "si", "sì", "on")

def env(name, default=None):
    v = os.environ.get(name)
    return default if v is None or v == "" else v

def setup_logging():
    logging.basicConfig(stream=sys.stdout, level=getattr(logging, env("LOG_LEVEL", "INFO").upper(), logging.INFO),
                        format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

def default_port(backend):
    return 3306 if backend == "mysql" else 5432

def dest_identity():
    """Identità della destinazione (per rifiutare sorgente == destinazione)."""
    b = env("DB_BACKEND", "json").lower()
    if b == "json":
        return ("json", os.path.realpath(env("DATA_DIR", "/data")))
    return (b, env("DB_HOST", "db").lower(), int(env("DB_PORT", default_port(b))), env("DB_NAME", "gestione_consegne"))

def source_env():
    """Variabili d'ambiente del processo che legge la sorgente (DB_* ← SRC_*) e identità della sorgente."""
    b = env("SRC_BACKEND", "json").lower()
    if b not in ("json", "mysql", "postgres"):
        raise PreflightError(f"SRC_BACKEND non valido: '{b}' (valori ammessi: json, mysql, postgres)")
    e = dict(os.environ)
    e["DB_BACKEND"] = b
    if b == "json":
        d = env("SRC_DATA_DIR", "/source")
        e["DATA_DIR"] = d
        ident = ("json", os.path.realpath(d))
    else:
        name = env("SRC_DB_NAME")
        if not name:
            raise PreflightError("SRC_DB_NAME mancante: indicare il database della sorgente")
        host = env("SRC_DB_HOST", env("DB_HOST", "db"))
        port = int(env("SRC_DB_PORT", env("DB_PORT", default_port(b))))
        e.update({"DB_HOST": host, "DB_PORT": str(port), "DB_NAME": name,
                  "DB_USER": env("SRC_DB_USER", env("DB_USER", "")),
                  "DB_PASSWORD": env("SRC_DB_PASSWORD", env("DB_PASSWORD", ""))})
        ident = (b, host.lower(), port, name)
    return e, ident

def check_writable_dir(path, what):
    """La cartella esiste (o si può creare) ed è scrivibile da chi esegue: il caso tipico su un NAS è
    una cartella montata che appartiene a un altro utente."""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, f".scrivibile-{os.getpid()}")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
    except OSError as e:
        uid = f"utente {os.getuid()}" if hasattr(os, "getuid") else "l'utente del container"
        raise PreflightError(
            f"{what}: la cartella {path} non è scrivibile dal processo ({uid}): {e}. "
            f"Se è una cartella del NAS montata nel container, concedere la scrittura (permessi della cartella).")

def check_dest_dir_writable(path):
    """Come check_writable_dir ma senza creare nulla (usato dal rapporto senza --execute)."""
    p = path
    while p and not os.path.exists(p):
        p = os.path.dirname(p)
    if not p or not os.access(p, os.W_OK):
        uid = f"utente {os.getuid()}" if hasattr(os, "getuid") else "l'utente del container"
        raise PreflightError(f"destinazione: la cartella {p or path} non è scrivibile dal processo ({uid}). "
                             f"Concedere la scrittura sulla cartella montata.")


# ─── LETTURA DELLA SORGENTE (processo dedicato: lo storage legge l'ambiente una volta sola) ──────

SQL_V1_RENAMES = {   # colonne snake_case della V1 su SQL → chiavi del frontend
    "consegne": {"tipo_prodotto": "tipoProdotto", "tipo_consegna": "tipoConsegna",
                 "giorno_consegna": "giornoConsegna", "fascia_oraria": "fasciaOraria",
                 "data_prenotaz": "dataPrenotazione"},
    "squadre":  {"color_idx": "colorIdx"},
}

def normalize_sql_v1(data):
    """La V1 su SQL restituisce chiavi snake_case e NULL (difetto noto): si riportano al formato del
    frontend, che è quello dei file json V1."""
    out = {}
    for coll in COLLECTIONS_V1:
        ren = SQL_V1_RENAMES.get(coll, {})
        recs = []
        for r in data.get(coll, []):
            n = {}
            for k, v in r.items():
                if v is None or k == "consegneCompletate":
                    continue
                n[ren.get(k, k)] = v
            recs.append(n)
        out[coll] = recs
    return out

def read_v1(st):
    if st.BACKEND == "json":
        d = st.DATA_DIR
        if not os.path.isdir(d):
            raise PreflightError(f"sorgente: la cartella {d} non esiste")
        if os.path.exists(os.path.join(d, "meta.json")):
            raise Refused(f"sorgente: {d} contiene meta.json, quindi è un archivio V2: usare --source-kind v2")
        if not any(os.path.exists(os.path.join(d, f"{c}.json")) for c in COLLECTIONS_V1):
            raise PreflightError(f"sorgente: nessun dato V1 in {d} (mancano consegne.json, giornate.json, squadre.json)")
    try:
        data = st.read_data()
    except Exception as e:
        raise PreflightError(f"sorgente: lettura dei dati V1 fallita: {e}")
    if st.BACKEND != "json":
        data = normalize_sql_v1(data)
    for coll in COLLECTIONS_V1:
        for r in data.get(coll, []):
            if isinstance(r, dict) and ("negozio_id" in r or "versione" in r or "seq" in r):
                raise Refused("sorgente: i record hanno già 'negozio_id' o 'versione': è un archivio V2, "
                              "usare --source-kind v2")
    return {c: data.get(c, []) for c in COLLECTIONS_V1}

def read_v2(st):
    state = classify_destination(st)
    if state["state"] == "assente":
        raise PreflightError("sorgente: il database non esiste")
    if state["state"] != "v2":
        raise Refused("sorgente: non è un archivio V2 (usare --source-kind v1 per i dati V1)")
    if state["flag"]:
        raise Refused("sorgente: migrazione interrotta (flag 'migrazione_in_corso'): archivio non affidabile")
    try:
        st.init_storage_v2()
    except st.SchemaError as e:
        raise Refused(f"sorgente: archivio V2 non valido: {e}")
    return {c: st.list_records(c) for c in COLLECTIONS_V2}

def read_legacy_file(path):
    if not os.path.isfile(path):
        raise PreflightError(f"sorgente: file {path} non trovato")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise PreflightError(f"sorgente: {path} non è un JSON leggibile: {e}")
    if not isinstance(data, dict):
        raise Refused(f"sorgente: {path} non contiene un oggetto JSON con consegne, giornate e squadre")
    for c in COLLECTIONS_V1:
        if not isinstance(data.get(c, []), list):
            raise Refused(f"sorgente: '{c}' in {path} non è una lista")
    return {c: data.get(c, []) for c in COLLECTIONS_V1}

def write_export(path, kind, source_desc, data):
    payload = {"format": EXPORT_FORMAT, "kind": kind, "creato": datetime.now().isoformat(timespec="seconds"),
               "sorgente": source_desc, "dati": data}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)   # contiene i dati dei clienti (e, per la V2, gli hash delle password)
    except OSError:
        pass
    return payload

def worker_read_source(kind, out):
    """Eseguito in un processo figlio con l'ambiente della sorgente (DB_*)."""
    import storage as st
    data = read_v1(st) if kind == "v1" else read_v2(st)
    desc = {"backend": st.BACKEND}
    write_export(out, kind, desc, data)
    log.info("Sorgente %s (%s) letta: %s", kind.upper(), st.BACKEND,
             ", ".join(f"{len(v)} {k}" for k, v in data.items()))


def default_out_path():
    d = "/migration" if os.path.isdir("/migration") else None
    name = f"export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    if d:
        return os.path.join(d, name)
    p = os.path.join(os.environ.get("TMPDIR", "/tmp"), name)
    log.warning("La cartella /migration non è montata: il file di esportazione (backup della sorgente) "
                "verrà salvato in %s e andrà perso con il container.", p)
    return p

def do_export(kind, out):
    """Legge la sorgente e scrive il file di esportazione. Ritorna il payload."""
    check_writable_dir(os.path.dirname(os.path.abspath(out)), "file di esportazione")
    if kind == "file":
        path = env("SRC_FILE", "/source/dati.json")
        data = read_legacy_file(path)
        payload = write_export(out, "v1", {"backend": "file", "file": path}, data)
        log.info("Sorgente dati.json (%s) letta: %s", path, ", ".join(f"{len(v)} {k}" for k, v in data.items()))
    else:
        senv, ident = source_env()
        if ident == dest_identity():
            raise Refused("la sorgente coincide con la destinazione: la destinazione deve essere un archivio nuovo "
                          "(altra cartella dati o altro database)")
        cmd = [sys.executable, os.path.abspath(__file__), "_read-source", "--source-kind", kind, "--out", out]
        r = subprocess.run(cmd, env=senv)
        if r.returncode != 0:
            raise (Refused if r.returncode == 2 else PreflightError if r.returncode == 3 else MigrateError)(
                "lettura della sorgente fallita (dettagli sopra)")
        with open(out, "r", encoding="utf-8") as f:
            payload = json.load(f)
    log.info("File di esportazione (backup completo della sorgente): %s", out)
    return payload


# ─── DESTINAZIONE: sonda, database, controllo di vuoto ───────────────────────

def sql_connect(st, attempts=10, pause=3):
    """Connessione con nuovi tentativi (il database può essere ancora in avvio). Un database
    inesistente non si riprova: ritorna None."""
    last = None
    for i in range(attempts):
        try:
            return st._pg_connect() if st.BACKEND == "postgres" else st._mysql_connect()
        except Exception as e:
            m = str(e).lower()
            # MySQL non rivela se un database esiste: "1044 access denied ... to database" vale come "mancante"
            if "does not exist" in m or "unknown database" in m or "1049" in m or "1044" in m:
                return None
            if "1045" in m or "password authentication failed" in m or "access denied" in m \
                    or "authentication failed" in m or "no pg_hba.conf entry" in m:
                raise PreflightError(f"database: credenziali rifiutate (utente/password): {e}")
            last = e
            log.warning("Database non raggiungibile (tentativo %d/%d): %s", i + 1, attempts, e)
            time.sleep(pause)
    raise PreflightError(f"database non raggiungibile: {last}")

def create_database(st):
    cfg = st._db_env(5432 if st.BACKEND == "postgres" else 3306)
    name = cfg["database"]
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise PreflightError(f"nome database '{name}' non ammesso per la creazione automatica (solo lettere, cifre, _)")
    try:
        if st.BACKEND == "postgres":
            import psycopg2
            conn = psycopg2.connect(host=cfg["host"], port=cfg["port"], dbname="postgres",
                                    user=cfg["user"], password=cfg["password"])
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(f'CREATE DATABASE "{name}"')
        else:
            import mysql.connector
            conn = mysql.connector.connect(host=cfg["host"], port=cfg["port"], user=cfg["user"],
                                           password=cfg["password"], charset="utf8mb4")
            cur = conn.cursor()
            cur.execute(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4")
        cur.close()
        conn.close()
    except Exception as e:
        raise PreflightError(f"creazione del database '{name}' fallita (l'utente ha il permesso?): {e}")
    log.info("Database '%s' creato.", name)

def _count_rows(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]

def classify_destination(st):
    """Stato della destinazione SENZA modificarla: vuota | v2 (con conteggi e flag) | altro (dati V1 o sconosciuti)
    | assente (database inesistente)."""
    res = {"state": "vuota", "counts": {}, "flag": False, "detail": ""}
    if st.BACKEND == "json":
        d = st.DATA_DIR
        def rd(name):
            p = os.path.join(d, name)
            if not os.path.exists(p):
                return None
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        try:
            meta = rd("meta.json")
            counts = {c: len(rd(f"{c}.json") or []) for c in COLLECTIONS_V2}
        except Exception as e:
            raise PreflightError(f"impossibile leggere i file in {d}: {e}")
        res["counts"] = counts
        if isinstance(meta, dict) and meta.get("schema_version") is not None:
            res["state"] = "v2" if meta.get("schema_version") == 2 else "altro"
            res["flag"] = bool(meta.get(FLAG))
        elif any(counts.values()):
            res["state"] = "altro"
            res["detail"] = "contiene dati senza marcatore V2 (probabile V1)"
        return res
    conn = sql_connect(st)
    if conn is None:
        res["state"] = "assente"
        return res
    try:
        cur = conn.cursor()
        if st.BACKEND == "postgres":
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
        else:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()")
        tables = {str(r[0]).lower() for r in cur.fetchall()}
        if not tables:
            return res
        if "meta" in tables:
            cur.execute("SELECT valore FROM meta WHERE chiave = 'schema_version'")
            row = cur.fetchone()
            ver = row[0] if row else None
            if isinstance(ver, (str, bytes)):
                ver = json.loads(ver)
            res["state"] = "v2" if ver == 2 else "altro"
            cur.execute(f"SELECT valore FROM meta WHERE chiave = '{FLAG}'")
            row = cur.fetchone()
            f = row[0] if row else None
            if isinstance(f, (str, bytes)):
                f = json.loads(f)
            res["flag"] = bool(f)
            for c in COLLECTIONS_V2:
                if c in tables:
                    res["counts"][c] = _count_rows(cur, c)
        else:
            res["state"] = "altro"
            res["detail"] = f"contiene tabelle ({', '.join(sorted(tables))}) senza il marcatore V2 (probabile V1)"
        return res
    finally:
        conn.close()

def check_destination(st, execute, create_db):
    """Verifica che la destinazione sia un archivio nuovo. Ritorna l'esito per il rapporto."""
    if st.BACKEND == "json":
        if execute:
            check_writable_dir(st.DATA_DIR, "destinazione")
        else:
            check_dest_dir_writable(st.DATA_DIR)
    state = classify_destination(st)
    if state["state"] == "assente":
        if not create_db:
            raise PreflightError(
                f"destinazione: il database '{env('DB_NAME', 'gestione_consegne')}' non esiste (o l'utente non può accedervi): crearlo oppure "
                f"impostare MIGRATE_CREATE_DB=1 (--create-db)")
        if execute:
            create_database(st)
            return classify_destination(st)
        state["detail"] = "il database non esiste e verrebbe creato"
        return state
    if state["state"] == "altro":
        raise Refused("destinazione: contiene già dati che non sono una V2 vuota"
                      + (f" ({state['detail']})" if state["detail"] else "")
                      + ". La migrazione scrive solo in un archivio nuovo: usare un'altra cartella dati o un altro database.")
    if state["state"] == "v2":
        if state["flag"]:
            raise Refused("destinazione: una migrazione precedente è rimasta interrotta (flag 'migrazione_in_corso'). "
                          "Ricreare la destinazione (nuova cartella dati o database vuoto) e rilanciare l'importazione.")
        if any(state["counts"].values()):
            filled = ", ".join(f"{n} {c}" for c, n in state["counts"].items() if n)
            raise Refused(f"destinazione: non è vuota ({filled}). La migrazione scrive solo in un archivio completamente "
                          f"vuoto: usare un'altra cartella dati o un altro database.")
    return state


# ─── TRASFORMAZIONE E CONVALIDA ──────────────────────────────────────────────

class Report:
    def __init__(self):
        self.errors, self.warnings, self.notes = [], [], []

    def error(self, msg):   self.errors.append(msg)
    def warn(self, msg):    self.warnings.append(msg)
    def note(self, msg):    self.notes.append(msg)

    def emit(self):
        for title, items, level in (("PROBLEMI (la migrazione non può procedere)", self.errors, log.error),
                                    ("AVVISI", self.warnings, log.warning), ("NOTE", self.notes, log.info)):
            if not items:
                continue
            level("%s: %d", title, len(items))
            for m in items[:MAX_SHOWN]:
                level("  - %s", m)
            if len(items) > MAX_SHOWN:
                level("  ... e altri %d (stesso tipo)", len(items) - MAX_SHOWN)

def clean(rec):
    return {k: v for k, v in rec.items() if v is not None and not k.startswith("_")}

def fix_giornata_refs(g, ids, rep, drop_orphans, label):
    """consegneIds: senza doppioni; i riferimenti a consegne inesistenti si scartano (o bloccano)."""
    seen, out = set(), []
    for cid in g.get("consegneIds") or []:
        if cid in seen:
            rep.warn(f"{label}: consegna {cid} presente due volte, tenuta una sola volta")
            continue
        seen.add(cid)
        if cid not in ids:
            if drop_orphans:
                rep.warn(f"{label}: riferimento a una consegna inesistente ({cid}), scartato")
            else:
                rep.error(f"{label}: riferimento a una consegna inesistente ({cid})")
            continue
        out.append(cid)
    g["consegneIds"] = out

def resolve_squadre(plan, nid, non_assegnata, rep):
    """V1: la giornata indica la squadra con il NOME; in V2 la squadra è obbligatoria e si indica con l'id.
    Ordine delle regole: nome uguale → quello senza maiuscole e spazi (avviso) → squadra mancante creata
    (avviso); nome vuoto → squadra `non_assegnata`, creata SOLO se almeno una giornata ne ha bisogno."""
    squadre = plan["squadre"]
    exact, folded = {}, {}
    for s in squadre:
        nome = s.get("nome")
        if not isinstance(nome, str):
            continue
        if nome in exact:
            rep.warn(f"due squadre con lo stesso nome '{nome}': le giornate usano la prima ({exact[nome]['id']})")
            continue
        exact[nome] = s
        folded.setdefault(nome.strip().casefold(), s)

    def create(nome):
        s = {"id": "sq_" + secrets.token_hex(8), "negozio_id": nid, "nome": nome, "colorIdx": len(squadre) % 8}
        squadre.append(s)
        exact[nome] = s
        folded.setdefault(nome.strip().casefold(), s)
        return s

    senza, non_ass = 0, None
    for g in plan["giornate"]:
        nome = g.pop("squadra", None)
        if nome is not None and not isinstance(nome, str):
            rep.error(f"giornata {g.get('id')!r}: la squadra non è un testo ({type(nome).__name__})")
            continue
        label = f"giornata {g.get('id')} ({g.get('data')})"
        if not nome or not nome.strip():
            if non_ass is None:
                non_ass = folded.get(non_assegnata.strip().casefold())
                if non_ass is None:
                    non_ass = create(non_assegnata)
                    rep.note(f"verrà creata la squadra '{non_assegnata}' ({non_ass['id']}) per le giornate senza squadra")
                else:
                    rep.note(f"le giornate senza squadra usano la squadra già esistente '{non_ass['nome']}'")
            senza += 1
            g["squadra_id"] = non_ass["id"]
            continue
        s = exact.get(nome)
        if s is None:
            s = folded.get(nome.strip().casefold())
            if s is not None:
                rep.warn(f"{label}: la squadra '{nome}' corrisponde a '{s['nome']}' (maiuscole o spazi diversi)")
        if s is None:
            s = create(nome.strip())
            rep.warn(f"{label}: la squadra '{nome}' non esiste tra le squadre: creata ({s['id']})")
        g["squadra_id"] = s["id"]
    if senza:
        rep.note(f"{senza} giornate senza squadra assegnate a '{non_ass['nome']}'")
    else:
        rep.note("tutte le giornate hanno già una squadra: nessuna squadra 'non assegnata' necessaria")

def build_plan(kind, data, negozio_nome, drop_orphans, rep, non_assegnata="Non assegnata"):
    """Dati dell'esportazione → record V2 per collezione (nell'ordine di inserimento)."""
    plan = {c: [] for c in COLLECTIONS_V2}
    if kind == "v1":
        import server as srv
        nid = "n_" + secrets.token_hex(8)
        plan["negozi"].append({"id": nid, "nome": negozio_nome, "creato_il": datetime.now().isoformat(timespec="seconds")})
        plan["utenti"].append(srv.superadmin_record())
        rep.note(f"verrà creato il negozio '{negozio_nome}' ({nid}) e l'account 'superadmin' con la password di default")
        for coll in COLLECTIONS_V1:
            for r in data.get(coll, []):
                if not isinstance(r, dict):
                    rep.error(f"{coll}: voce che non è un record ({type(r).__name__})")
                    continue
                n = clean(r)
                n.pop("consegneCompletate", None)
                n["negozio_id"] = nid
                plan[coll].append(n)
        resolve_squadre(plan, nid, non_assegnata, rep)
    else:
        for coll in COLLECTIONS_V2:
            for r in data.get(coll, []):
                if not isinstance(r, dict):
                    rep.error(f"{coll}: voce che non è un record ({type(r).__name__})")
                    continue
                n = clean(r)
                n.pop("versione", None)    # la gestisce lo storage (riparte da 1)
                if coll == "giornate" and "squadra" in n:
                    rep.error(f"giornata {n.get('id')!r}: ha il vecchio campo 'squadra' (archivio V2 di un'edizione "
                              f"precedente, senza 'squadra_id')")
                plan[coll].append(n)
    ids = {c.get("id") for c in plan["consegne"]}
    for g in plan["giornate"]:
        fix_giornata_refs(g, ids, rep, drop_orphans, f"giornata {g.get('id')} ({g.get('data')})")
    return plan

def validate_plan(plan, rep):
    """Gli stessi controlli che farebbe lo storage, ma su TUTTI i record e con un rapporto completo."""
    import storage as st
    ids = {}
    for coll in COLLECTIONS_V2:
        spec = st._COLL[coll]
        seen, uniq = set(), {f: set() for f in spec["unique"]}
        for r in plan[coll]:
            rid = r.get("id")
            label = f"{coll} {rid!r}"
            if not isinstance(rid, str) or not rid:
                rep.error(f"{coll}: record senza 'id' valido")
                continue
            if rid in seen:
                rep.error(f"{label}: id duplicato")
                continue
            seen.add(rid)
            try:
                st._norm_insert(coll, r)
            except (ValueError, TypeError) as e:
                rep.error(f"{label}: {e}")
            for f in spec["unique"]:
                v = r.get(f)
                if isinstance(v, str):
                    key = v.casefold() if f in spec["ci"] else v
                    if key in uniq[f]:
                        rep.error(f"{label}: valore duplicato per '{f}' ({v!r})")
                    uniq[f].add(key)
        ids[coll] = seen
    for coll in COLLECTIONS_V2:
        for field, target in st._COLL[coll]["fks"].items():
            for r in plan[coll]:
                v = r.get(field)
                if v is not None and v not in ids.get(target, set()):
                    rep.error(f"{coll} {r.get('id')!r}: {field}={v!r} non esiste in {target}")
    consegne_neg = {c["id"]: c.get("negozio_id") for c in plan["consegne"] if "id" in c}
    for g in plan["giornate"]:
        for cid in g.get("consegneIds", []):
            if consegne_neg.get(cid) != g.get("negozio_id"):
                rep.error(f"giornata {g.get('id')!r}: la consegna {cid!r} appartiene a un altro negozio")
    for c in plan["consegne"]:
        if c.get("stato") is not None and c.get("stato") not in STATI:
            rep.warn(f"consegna {c.get('id')!r}: stato '{c.get('stato')}' non previsto (conservato com'è)")

def expected_records(plan):
    """Forma attesa dei record dopo la scrittura (come li restituirebbe lo storage, senza 'versione')."""
    import storage as st
    out = {}
    for coll in COLLECTIONS_V2:
        recs = []
        for r in plan[coll]:
            n = st._norm_insert(coll, r)
            n.pop("versione", None)
            recs.append(n)
        out[coll] = recs
    return out


# ─── SCRITTURA E VERIFICA ────────────────────────────────────────────────────

def write_plan(plan):
    import storage as st
    for coll in COLLECTIONS_V2:
        if plan[coll]:
            st.insert_records(coll, plan[coll])
            log.info("  scritti %d record in %s", len(plan[coll]), coll)

def verify(plan):
    """Rilegge dalla destinazione ogni record e lo confronta con quello atteso."""
    import storage as st
    exp = expected_records(plan)
    problems = []
    for coll in COLLECTIONS_V2:
        actual = []
        for r in st.list_records(coll):
            r = dict(r)
            r.pop("versione", None)
            actual.append(r)
        if len(actual) != len(exp[coll]):
            problems.append(f"{coll}: attesi {len(exp[coll])} record, trovati {len(actual)}")
            continue
        for i, (a, e) in enumerate(zip(actual, exp[coll])):
            if a != e:
                diff = sorted(k for k in set(a) | set(e) if a.get(k) != e.get(k))
                problems.append(f"{coll} {e.get('id')!r} (posizione {i + 1}): campi diversi {diff}")
    return problems

def run_import(payload, execute, negozio_nome, drop_orphans, create_db, non_assegnata="Non assegnata"):
    import storage as st
    kind = payload["kind"]
    data = payload["dati"]
    log.info("Destinazione: %s", "json in " + st.DATA_DIR if st.BACKEND == "json"
             else f"{st.BACKEND} {env('DB_HOST', 'db')}/{env('DB_NAME', 'gestione_consegne')}")
    rep = Report()
    plan = build_plan(kind, data, negozio_nome, drop_orphans, rep, non_assegnata)
    validate_plan(plan, rep)
    log.info("Record da scrivere: %s", ", ".join(f"{len(plan[c])} {c}" for c in COLLECTIONS_V2 if plan[c]) or "nessuno")
    dest = check_destination(st, execute, create_db)
    if dest.get("detail"):
        rep.note(f"destinazione: {dest['detail']}")
    rep.emit()
    if rep.errors:
        raise Refused(f"{len(rep.errors)} problemi nei dati: correggere la sorgente (o il file di esportazione) e rilanciare")
    if not execute:
        log.info("RAPPORTO COMPLETATO: nessun problema bloccante. Nulla è stato scritto nella destinazione.")
        log.info("Per eseguire la migrazione impostare MIGRATE_EXECUTE=1 (--execute).")
        return plan
    # ── scrittura ──
    try:
        st.init_storage_v2()
    except st.SchemaError as e:
        raise Refused(f"destinazione: {e}")
    filled = [c for c in COLLECTIONS_V2 if st.list_records(c)]
    if filled:   # riverifica con lo storage aperto (corsa con un avvio del server)
        raise Refused(f"destinazione: non è vuota ({', '.join(filled)})")
    st.set_meta(FLAG, {"iniziata": datetime.now().isoformat(timespec="seconds"), "sorgente": kind})
    log.info("Scrittura nella destinazione (il server V2 non parte finché la migrazione non è conclusa)...")
    try:
        write_plan(plan)
    except Exception as e:
        log.error("SCRITTURA INTERROTTA: %s", e)
        log.error("La destinazione è rimasta marcata come 'migrazione in corso' e il server V2 non partirà. "
                  "Ricreare la destinazione (nuova cartella dati o database vuoto) e rilanciare l'importazione.")
        raise MigrateError(f"scrittura interrotta: {e}")
    log.info("Verifica: ogni record viene riletto dalla destinazione e confrontato...")
    problems = verify(plan)
    if problems:
        for p in problems[:MAX_SHOWN]:
            log.error("  - %s", p)
        log.error("VERIFICA FALLITA: la destinazione resta marcata come 'migrazione in corso'.")
        raise MigrateError(f"verifica fallita ({len(problems)} differenze)")
    st.set_meta(FLAG, False)
    log.info("Verifica superata: %s", ", ".join(f"{len(plan[c])} {c}" for c in COLLECTIONS_V2 if plan[c]))
    # backup iniziale della destinazione (non critico: la migrazione è già riuscita e verificata)
    r = st.backup_run()
    if r["ok"]:
        log.info("Backup iniziale della destinazione: %s", r["file"])
    else:
        log.warning("Backup iniziale della destinazione non eseguito (%s). La migrazione è comunque riuscita; "
                    "con un database serve una cartella montata su /data per i backup.", r["error"])
    return plan


# ─── COMANDI ─────────────────────────────────────────────────────────────────

def load_export(path):
    if not os.path.isfile(path):
        raise PreflightError(f"file di esportazione non trovato: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise PreflightError(f"file di esportazione illeggibile ({path}): {e}")
    if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT or payload.get("kind") not in ("v1", "v2") \
            or not isinstance(payload.get("dati"), dict):
        raise Refused(f"{path} non è un file prodotto da 'migrate.py export'")
    return payload

def cmd_run(a):
    out = a.out or default_out_path()
    payload = do_export(a.source_kind, out)
    run_import(payload, a.execute, a.negozio_nome, not a.keep_orphans, a.create_db, a.non_assegnata)

def cmd_export(a):
    do_export(a.source_kind, a.out or default_out_path())
    log.info("ESPORTAZIONE COMPLETATA. La sorgente non è stata modificata.")

def cmd_import(a):
    if not a.input:
        raise PreflightError("indicare il file da importare (--in o MIGRATE_IN)")
    run_import(load_export(a.input), a.execute, a.negozio_nome, not a.keep_orphans, a.create_db, a.non_assegnata)

def build_parser():
    p = argparse.ArgumentParser(prog="migrate.py", description="Migrazione dei dati verso la V2 (vedi l'intestazione del file).")
    p.add_argument("command", nargs="?", default="run", choices=["run", "export", "import", "_read-source"])
    p.add_argument("--source-kind", default=env("MIGRATE_SOURCE_KIND", "v1"), choices=["v1", "file", "v2"])
    p.add_argument("--execute", action="store_true", default=truthy(env("MIGRATE_EXECUTE")))
    p.add_argument("--out", default=env("MIGRATE_OUT"))
    p.add_argument("--in", dest="input", default=env("MIGRATE_IN"))
    p.add_argument("--negozio-nome", default=env("MIGRATE_NEGOZIO_NOME", "Negozio principale"))
    p.add_argument("--non-assegnata", default=env("MIGRATE_SQUADRA_NON_ASSEGNATA", "Non assegnata"))
    p.add_argument("--create-db", action="store_true", default=truthy(env("MIGRATE_CREATE_DB")))
    p.add_argument("--keep-orphans", action="store_true", default=truthy(env("MIGRATE_KEEP_ORPHANS")))
    return p

def main(argv=None):
    setup_logging()
    a = build_parser().parse_args(argv)
    if a.command == "_read-source":
        try:
            worker_read_source(a.source_kind, a.out)
            return 0
        except MigrateError as e:
            log.error("%s", e)
            return e.code
    log.info("=" * 60)
    log.info("migrate.py — comando '%s'%s", a.command, "" if a.execute or a.command == "export"
             else " (solo rapporto: nulla viene scritto nella destinazione)")
    try:
        {"run": cmd_run, "export": cmd_export, "import": cmd_import}[a.command](a)
    except MigrateError as e:
        log.error("%s", e)
        log.error("ESITO: FALLITO")
        return e.code
    except Exception:
        log.exception("Errore imprevisto")
        log.error("ESITO: FALLITO")
        return 1
    if a.command == "export":
        log.info("ESITO: OK")
    elif a.execute:
        log.info("ESITO: OK — migrazione completata. Avviare il server V2 sulla destinazione; il primo accesso è "
                 "'superadmin' / 'admin' (cambio password obbligatorio)." if a.source_kind != "v2"
                 else "ESITO: OK — migrazione completata. Avviare il server V2 sulla destinazione.")
    else:
        log.info("ESITO: OK — rapporto senza problemi (nulla scritto)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
