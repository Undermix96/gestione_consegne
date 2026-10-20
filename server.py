#!/usr/bin/env python3
"""
Gestione Consegne — Server V2 (Docker)
- Autenticazione Challenge-Response SHA-256, sessioni in memoria
- API REST per singola operazione, permessi per tipo account, multi-negozio
- Dati esclusivamente tramite storage.py (json | mysql | postgres), optimistic locking per record
- Log su stdout (catturati da Docker)
"""

import hashlib
import http.server
import ipaddress
import json
import logging
import os
import re
import secrets
import socketserver
import sys
import threading
import time
from datetime import datetime
from urllib.parse import unquote

import storage
from storage import (ConflictError, DuplicateError, IntegrityError, NotFoundError,
                     SchemaError, StorageError)

PORT     = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SESSION_TTL     = 7200   # 2 ore di inattività
SESSION_MAX_AGE = 43200  # 12 ore: durata massima assoluta, anche con attività continua (SEC-07)
CHALLENGE_TTL   = 60     # secondi
MAX_CHALLENGES  = 1000   # challenge contemporanei (protezione della memoria)
MAX_BODY        = 2 * 1024 * 1024
# Limiti sui tentativi di accesso (SEC-06). Contatori in memoria, come sessioni e challenge.
LOGIN_WINDOW        = 300    # finestra in secondi
LOGIN_MAX_FAIL_USER = 10     # fallimenti per username nella finestra
MAX_TRACKED         = 10000  # chiavi tracciate al massimo (protezione della memoria)
# Rallentamento globale delle risposte di errore (contro lo spray di password: una password su molti username,
# che i limiti per username non fermano). Non blocca nessuno: oltre la soglia ogni errore di login risponde
# con un ritardo crescente. Vale per tutti i client insieme, quindi non dipende dall'IP.
LOGIN_DELAY_WINDOW    = 60     # secondi
LOGIN_DELAY_THRESHOLD = 10     # fallimenti (di tutti) nella finestra oltre i quali scatta il ritardo
LOGIN_DELAY_STEP      = 0.25   # secondi di ritardo per ogni fallimento oltre la soglia
LOGIN_DELAY_MAX       = 3.0

def _env_int(name, default):
    """Intero da variabile d'ambiente; vuota o non valida → default (compose passa le variabili vuote)."""
    try:
        return max(0, int(os.environ.get(name, "").strip()))
    except ValueError:
        return default

# Limiti per IP: 0 li disattiva. Se il server vede sempre lo stesso IP (NAT, Docker Desktop, alcuni NAS) tutti i
# client condividono questi contatori: alzare le soglie, o disattivarle e restare con i limiti per username,
# oppure indicare il reverse proxy in TRUSTED_PROXIES per usare l'IP reale dei client.
LOGIN_MAX_FAIL_IP = _env_int("LOGIN_MAX_FAIL_IP", 20)   # fallimenti per IP nella finestra
CHALLENGE_MAX_IP  = _env_int("CHALLENGE_MAX_IP", 50)    # challenge vivi per IP

def parse_trusted_proxies(value):
    """Elenco di IP o reti (CIDR) separati da virgola → lista di ip_network. Voci non valide ignorate."""
    nets = []
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logging.getLogger().warning("TRUSTED_PROXIES: voce non valida ignorata: %r", part)
    return nets

TRUSTED_PROXIES = parse_trusted_proxies(os.environ.get("TRUSTED_PROXIES", ""))
HEALTHCHECK_IPS = {"127.0.0.1", "::1"}

SUPERADMIN_ID = "u_superadmin"
SUPERADMIN_DEFAULT_HASH = hashlib.sha256(b"admin").hexdigest()

# Permessi hardcoded del superadmin (non assegnabili ai tipi account)
SUPERADMIN_PERMESSI = {
    "tipi_account.leggi", "tipi_account.gestisci", "negozi.gestisci",
    "utenti.leggi", "utenti.crea", "utenti.modifica", "utenti.elimina",
}

# Permessi assegnabili ai tipi account
PERMESSI_VALIDI = {
    "consegne.leggi", "consegne.scrivi", "consegne.elimina",
    "giornate.leggi", "giornate.crea", "giornate.elimina", "giornate.assegna",
    "giornate.riordina", "giornate.segna_completata",
    "squadre.leggi", "squadre.gestisci",
    "stampa.pdf",
    "tipi_account.leggi",
    "utenti.leggi", "utenti.crea", "utenti.modifica", "utenti.elimina",
}

STATI_CONSEGNA = {"in_attesa", "da_confermare", "programmata", "completata",
                  "annullata", "da_riprogrammare"}
STATI_ASSEGNATI = ("programmata", "da_confermare")
SQ_COLORS = 8

HASH_RE = re.compile(r"[0-9a-f]{64}")
DATA_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# ─── LOGGING ────────────────────────────────────────────────────────────────

def setup_logging():
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        stream=sys.stdout,
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def log(msg, level="info"):
    getattr(logging, level)(msg)

# ─── UTILITÀ ────────────────────────────────────────────────────────────────

def sha256_hex(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def new_id(prefix):
    return prefix + secrets.token_hex(8)

class HttpError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

# ─── BACKUP AUTOMATICO ───────────────────────────────────────────────────────

backup_stop = threading.Event()
backup_seen = {"scritture": None}   # write_count() al momento dell'ultimo backup riuscito (None: ignoto)

def backup_loop():
    """Ogni BACKUP_INTERVAL secondi (default 6 ore) salva i dati, SE ci sono state modifiche dall'ultimo backup
    (o se non ne esiste nessuno). Gira in un thread a parte: non rallenta le richieste. Vale per tutti i backend."""
    intervallo = storage.BACKUP_MIN_INTERVAL
    if intervallo <= 0:
        log("[BACKUP] Backup automatico disattivato (BACKUP_INTERVAL=0)")
        return
    log(f"[BACKUP] Backup automatico ogni {intervallo}s se ci sono modifiche; si conservano gli ultimi {storage.MAX_BACKUPS}")
    inizio = time.time()
    attesa = min(60, intervallo)                       # il primo backup non parte durante l'avvio
    tick = max(1, min(60, intervallo // 6))
    riprova = 0.0
    while not backup_stop.wait(tick):
        try:
            adesso = time.time()
            ultimo = storage.backup_last_time()
            if adesso < riprova or (ultimo is not None and adesso - ultimo < intervallo):
                continue
            if ultimo is None and adesso - inizio < attesa:
                continue
            scritture = storage.write_count()
            if ultimo is not None and backup_seen["scritture"] == scritture:
                continue                               # nessuna modifica dall'ultimo backup
            r = storage.backup_run()
            if r["ok"]:
                backup_seen["scritture"] = scritture
                log(f"[BACKUP] Backup automatico: {r['file']}")
            else:
                log(f"[BACKUP] Backup automatico non riuscito: {r['error']}", "error")
                riprova = time.time() + min(intervallo, 600)
        except Exception:
            logging.exception("[BACKUP] Errore imprevisto nel backup automatico")
            riprova = time.time() + 600

# ─── CLIENT CONNESSI ─────────────────────────────────────────────────────────

clients_lock = threading.Lock()
client_heartbeat = {}   # chiave (X-Client-ID o IP) -> ultimo heartbeat

def register_client(ip, client_id=None):
    """Le richieste dell'healthcheck Docker (localhost, senza X-Client-ID) non si contano."""
    if client_id is None and ip in HEALTHCHECK_IPS:
        return
    with clients_lock:
        client_heartbeat[client_id or ip] = time.time()

def get_connected_count():
    now = time.time()
    with clients_lock:
        for k in [k for k, ts in client_heartbeat.items() if now - ts >= 15]:
            del client_heartbeat[k]
        return len(client_heartbeat)

# ─── TIMESTAMP DI POLLING (per negozio, in memoria) ──────────────────────────

timestamps_lock = threading.Lock()
timestamps = {}   # negozio_id -> {"consegne": t, "giornate": t, "squadre": t}
_BOOT_TS = time.time()

def touch(negozio_id, *categorie):
    with timestamps_lock:
        t = timestamps.setdefault(negozio_id, {"consegne": _BOOT_TS, "giornate": _BOOT_TS, "squadre": _BOOT_TS})
        now = time.time()
        for c in categorie:
            # strettamente crescente anche per scritture nello stesso istante
            t[c] = max(now, t[c] + 1e-6)

def get_timestamps(negozio_id):
    with timestamps_lock:
        return dict(timestamps.get(negozio_id) or {"consegne": _BOOT_TS, "giornate": _BOOT_TS, "squadre": _BOOT_TS})

# ─── CHALLENGE E SESSIONI (in memoria) ───────────────────────────────────────

challenges_lock = threading.Lock()
challenges = {}   # challenge -> timestamp

sessions_lock = threading.Lock()
sessions = {}     # token -> dict sessione

def _trusted(addr):
    try:
        a = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(a in n for n in TRUSTED_PROXIES if n.version == a.version)

def client_ip(peer, forwarded):
    """IP del client. Se la connessione arriva da un proxy fidato (TRUSTED_PROXIES) si usa X-Forwarded-For,
    letto da destra verso sinistra: il primo indirizzo non fidato è quello che il proxy ha visto davvero,
    quelli più a sinistra li può scrivere il client e non contano. Senza proxy fidati l'header è ignorato."""
    if not TRUSTED_PROXIES or not _trusted(peer) or not forwarded:
        return peer
    for part in reversed([p.strip() for p in forwarded.split(",")]):
        try:
            addr = ipaddress.ip_address(part)
        except ValueError:
            return peer                      # header malformato: non ci si fida
        if not _trusted(str(addr)):
            return str(addr)
    return peer

def new_challenge(ip=None):
    now = time.time()
    with challenges_lock:
        # un solo IP non può occupare tutti i challenge (altrimenti nessun altro potrebbe fare il login)
        if CHALLENGE_MAX_IP > 0:
            propri = sum(1 for ts, cip in challenges.values() if cip == ip and now - ts <= CHALLENGE_TTL)
            if propri >= CHALLENGE_MAX_IP:
                raise HttpError(429, "Troppe richieste, riprova tra qualche secondo")
        if len(challenges) >= MAX_CHALLENGES:
            for c in [c for c, (ts, _) in challenges.items() if now - ts > CHALLENGE_TTL]:
                del challenges[c]
            while len(challenges) >= MAX_CHALLENGES:
                # pieno di challenge ancora validi: si scarta il più vecchio invece di rifiutare chi arriva.
                # Chi inonda il server non può così bloccare i login (servirebbero migliaia di richieste
                # nel breve tempo che passa tra challenge e login di un utente vero).
                del challenges[next(iter(challenges))]
        ch = secrets.token_hex(32)
        challenges[ch] = (now, ip)
        return ch

def consume_challenge(ch):
    with challenges_lock:
        entry = challenges.pop(ch, None)
    return entry is not None and (time.time() - entry[0]) < CHALLENGE_TTL

# ─── LIMITE DEI TENTATIVI DI ACCESSO (in memoria) ────────────────────────────

fails_lock = threading.Lock()
fails = {}   # ("ip", ip) | ("user", username in minuscolo) -> [istanti dei fallimenti]
all_fails = []   # istanti dei fallimenti di tutti, per il rallentamento globale
_sleep = time.sleep   # sostituibile nei test

def _user_key(username):
    return ("user", str(username).strip().casefold()[:150])

def _recent_fails(key, now):
    lst = [t for t in fails.get(key, ()) if now - t < LOGIN_WINDOW]
    if lst:
        fails[key] = lst
    else:
        fails.pop(key, None)
    return lst

def check_login_allowed(ip, user_key):
    """429 se da questo IP o su questo username ci sono stati troppi fallimenti di recente."""
    now = time.time()
    with fails_lock:
        if (LOGIN_MAX_FAIL_IP > 0 and len(_recent_fails(("ip", ip), now)) >= LOGIN_MAX_FAIL_IP) or \
                len(_recent_fails(user_key, now)) >= LOGIN_MAX_FAIL_USER:
            raise HttpError(429, "Troppi tentativi di accesso falliti: riprova tra qualche minuto")

def record_login_failure(ip, user_key):
    """Registra un fallimento e, se in questo momento ce ne sono troppi in giro (da chiunque), fa attendere
    la risposta di errore: un ritardo crescente rende inutile lo spray di password senza bloccare nessuno."""
    now = time.time()
    with fails_lock:
        all_fails[:] = [t for t in all_fails if now - t < LOGIN_DELAY_WINDOW]
        all_fails.append(now)
        eccesso = len(all_fails) - LOGIN_DELAY_THRESHOLD
        if len(fails) >= MAX_TRACKED:
            for k in list(fails):
                _recent_fails(k, now)
        fails.setdefault(("ip", ip), []).append(now)
        if user_key in fails or len(fails) < MAX_TRACKED:     # a memoria piena l'IP resta comunque tracciato
            fails.setdefault(user_key, []).append(now)
    if eccesso > 0 and LOGIN_DELAY_STEP > 0:
        _sleep(min(LOGIN_DELAY_MAX, eccesso * LOGIN_DELAY_STEP))     # fuori dal lock

def clear_login_failures(user_key):
    with fails_lock:
        fails.pop(user_key, None)

def new_session(user, permessi):
    token = secrets.token_urlsafe(32)
    now = time.time()
    with sessions_lock:
        for t in [t for t, s in sessions.items() if now > s["expires"] or now > s["created"] + SESSION_MAX_AGE]:
            del sessions[t]
        sessions[token] = {
            "user_id":              user["id"],
            "username":             user["username"],
            "negozio_id":           user.get("negozio_id"),
            "permessi":             permessi,
            "is_superadmin":        bool(user.get("is_superadmin")),
            "created":              now,
            "last_seen":            now,
            "expires":              now + SESSION_TTL,
            "must_change_password": bool(user.get("primo_login")),
        }
    return token

def get_session(token, renew=True):
    """Sessione valida oppure None. Ritorna una copia. Con renew=True prolunga la scadenza:
    le richieste di fondo del client (ping, polling) usano renew=False, così la scadenza
    misura l'inattività dell'utente e non la sola presenza di una scheda aperta."""
    if not token:
        return None
    with sessions_lock:
        s = sessions.get(token)
        if s is None:
            return None
        now = time.time()
        if now > s["expires"] or now > s["created"] + SESSION_MAX_AGE:
            del sessions[token]
            return None
        if renew:
            s["last_seen"] = now
            s["expires"] = now + SESSION_TTL
        return dict(s)

def delete_session(token):
    with sessions_lock:
        sessions.pop(token, None)

def invalidate_user_sessions(user_id):
    with sessions_lock:
        for t in [t for t, s in sessions.items() if s["user_id"] == user_id]:
            del sessions[t]

# ─── ACCESSO AI DATI (helper sopra storage.py) ───────────────────────────────

def find_user_by_username(username):
    found = storage.list_records("utenti", {"username": username})
    return found[0] if found else None

def resolve_permessi(user):
    if user.get("is_superadmin"):
        return sorted(SUPERADMIN_PERMESSI)
    tipo_id = user.get("tipo_account_id")
    tipo = storage.get_record("tipi_account", tipo_id) if tipo_id else None
    if not tipo:
        return []
    return [p for p in tipo.get("permessi", []) if p in PERMESSI_VALIDI]

def rec_or_404(collection, rid, label):
    rec = storage.get_record(collection, rid)
    if rec is None:
        raise HttpError(404, f"{label} non trovato/a")
    return rec

LETTURA_CATEGORIA = {"consegne": "consegne.leggi", "giornate": "giornate.leggi", "squadre": "squadre.leggi"}

def db_negozio(ctx):
    """Dati del negozio della sessione, limitati alle categorie che l'utente può leggere."""
    f = {"negozio_id": ctx.nid}
    out = {cat: storage.list_records(cat, f)
           for cat, perm in LETTURA_CATEGORIA.items() if perm in ctx.session["permessi"]}
    out["_connectedClients"] = get_connected_count()
    return out

def superadmin_record():
    """Record del superadmin con la password di default (cambio obbligatorio al primo accesso).
    Usato anche da migrate.py: la definizione è una sola."""
    return {
        "id": SUPERADMIN_ID, "username": "superadmin",
        "password_hash": SUPERADMIN_DEFAULT_HASH,
        "is_superadmin": True, "primo_login": True,
        "creato_il": now_iso(),
    }

def ensure_superadmin():
    """Primo avvio: crea il superadmin con la password di default (cambio obbligatorio)."""
    if storage.get_record("utenti", SUPERADMIN_ID) is not None:
        return
    try:
        storage.insert_record("utenti", superadmin_record())
        log("[AUTH] Creato l'account 'superadmin' con la password di default: cambiarla al primo accesso", "warning")
    except DuplicateError:
        pass   # creato in parallelo da un altro avvio

# ─── CONTESTO DI RICHIESTA, ROUTING E PERMESSI ───────────────────────────────

PUBLIC, AUTH, SUPER, OPER = "public", "auth", "superadmin", "operativo"

class Ctx:
    def __init__(self, handler, token, session, params):
        self.handler = handler
        self.token = token
        self.session = session
        self.params = params
        self.ip = client_ip(handler.client_address[0], ", ".join(handler.headers.get_all("X-Forwarded-For") or []))
        self._body = None

    @property
    def username(self):
        return self.session["username"] if self.session else "-"

    @property
    def nid(self):
        return self.session["negozio_id"]

    def body(self):
        if self._body is None:
            self._body = self.handler.read_json_body()
        return self._body

    def dlog(self, msg):
        log(f"[DATI] '{self.username}' — {msg}")

ROUTES = []   # (metodo, regex, requisito, ammesso_con_cambio_password, rinnova_sessione, funzione)

def route(method, pattern, requirement, pending_ok=False, renew=True):
    rx = re.compile("^" + re.sub(r":(\w+)", r"(?P<\1>[^/]+)", pattern) + "$")
    def deco(fn):
        ROUTES.append((method, rx, requirement, pending_ok, renew, fn))
        return fn
    return deco

def authorize(session, requirement):
    """403 se la sessione non soddisfa il requisito."""
    if requirement == AUTH:
        return
    if requirement == SUPER:
        if not session["is_superadmin"]:
            raise HttpError(403, "Riservato al superadmin")
    elif requirement == OPER:
        if session["is_superadmin"]:
            raise HttpError(403, "Il superadmin non ha accesso ai dati operativi")
    else:
        allowed = SUPERADMIN_PERMESSI if session["is_superadmin"] else session["permessi"]
        if requirement not in allowed:
            raise HttpError(403, f"Permesso mancante: {requirement}")

def check_tenant(ctx, rec):
    if rec.get("negozio_id") != ctx.nid:
        raise HttpError(403, "Accesso negato: negozio non corrispondente")

def need_text(body, key, label=None):
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise HttpError(400, f"{label or key} obbligatorio")
    return v.strip()

def need_hash(body, key):
    v = body.get(key)
    if not isinstance(v, str) or not HASH_RE.fullmatch(v):
        raise HttpError(400, f"{key} non valido")
    return v

def need_versione(body):
    v = body.get("versione")
    if not isinstance(v, int) or isinstance(v, bool):
        raise HttpError(400, "versione obbligatoria")
    return v

def need_id_list(body, key):
    v = body.get(key)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise HttpError(400, f"{key} deve essere una lista di id")
    return v

def label_consegna(c):
    return f"{c.get('cognome', '')} {c.get('nome', '')}".strip() or c["id"]

# ─── ENDPOINT: auth ──────────────────────────────────────────────────────────

@route("GET", "/api/auth/challenge", PUBLIC)
def h_challenge(ctx):
    return 200, {"challenge": new_challenge(ctx.ip)}

@route("GET", "/api/ping", PUBLIC)
def h_ping(ctx):
    # senza token (healthcheck Docker) è sempre 200; con un token non più valido → 401, così
    # il client scopre la scadenza anche senza polling (superadmin). Non rinnova la sessione.
    if ctx.token and not get_session(ctx.token, renew=False):
        raise HttpError(401, "Non autenticato")
    register_client(ctx.ip, ctx.handler.headers.get("X-Client-ID"))
    return 200, {"ok": True, "clients": get_connected_count()}

@route("POST", "/api/auth/login", PUBLIC)
def h_login(ctx):
    b = ctx.body()
    username, ch, response = b.get("username"), b.get("challenge"), b.get("response")
    if not all(isinstance(x, str) and x for x in (username, ch, response)):
        raise HttpError(400, "Dati mancanti")
    username = username.strip()
    ukey = _user_key(username)
    try:
        check_login_allowed(ctx.ip, ukey)
    except HttpError:
        log(f"[AUTH] Login rifiutato (troppi tentativi falliti) per '{username}' da {ctx.ip}", "warning")
        raise
    if not consume_challenge(ch):
        log(f"[AUTH] Challenge non valido per '{username}' da {ctx.ip}", "warning")
        raise HttpError(401, "Challenge non valido o scaduto")
    user = find_user_by_username(username)
    # confronto eseguito anche per utenti inesistenti: stessa risposta e tempi simili
    stored = user["password_hash"] if user else SUPERADMIN_DEFAULT_HASH
    ok = secrets.compare_digest(response.encode("utf-8"), sha256_hex(stored + ch).encode("utf-8"))
    if not user:
        record_login_failure(ctx.ip, ukey)
        log(f"[AUTH] Login fallito — utente non trovato: '{username}' da {ctx.ip}", "warning")
        raise HttpError(401, "Credenziali non valide")
    if not ok:
        record_login_failure(ctx.ip, ukey)
        log(f"[AUTH] Login fallito — password errata per '{username}' da {ctx.ip}", "warning")
        raise HttpError(401, "Credenziali non valide")
    clear_login_failures(ukey)
    if not user.get("is_superadmin") and not (user.get("tipo_account_id") and user.get("negozio_id")):
        log(f"[AUTH] Login bloccato — account non configurato: '{username}' da {ctx.ip}", "warning")
        raise HttpError(403, "Account non configurato. Contatta l'amministratore.")
    permessi = resolve_permessi(user)
    try:
        storage.update_record("utenti", user["id"], {"ultimo_accesso": now_iso()})
    except StorageError as e:
        log(f"[AUTH] ultimo_accesso non aggiornato per '{username}': {e}", "warning")
    token = new_session(user, permessi)
    log(f"[AUTH] '{user['username']}' ha effettuato il login da {ctx.ip}")
    return 200, {
        "token": token,
        "username": user["username"],
        "user_id": user["id"],
        "negozio_id": user.get("negozio_id"),
        "permessi": permessi,
        "is_superadmin": bool(user.get("is_superadmin")),
        "must_change_password": bool(user.get("primo_login")),
    }

@route("POST", "/api/auth/logout", AUTH, pending_ok=True)
def h_logout(ctx):
    delete_session(ctx.token)
    log(f"[AUTH] '{ctx.username}' ha effettuato il logout")
    return 200, {"ok": True}

@route("POST", "/api/auth/change-password", AUTH, pending_ok=True)
def h_change_password(ctx):
    b = ctx.body()
    ch, response = b.get("challenge"), b.get("response")
    if not all(isinstance(x, str) and x for x in (ch, response)):
        raise HttpError(400, "Dati mancanti")
    nuova = need_hash(b, "nuova_hash")
    ukey = _user_key(ctx.username)
    check_login_allowed(ctx.ip, ukey)
    if not consume_challenge(ch):
        raise HttpError(401, "Challenge non valido o scaduto")
    user = rec_or_404("utenti", ctx.session["user_id"], "Utente")
    stored = user["password_hash"]
    if not secrets.compare_digest(response.encode("utf-8"), sha256_hex(stored + ch).encode("utf-8")):
        record_login_failure(ctx.ip, ukey)
        log(f"[AUTH] Cambio password fallito (password errata) per '{ctx.username}' da {ctx.ip}", "warning")
        raise HttpError(401, "Password attuale non corretta")
    if nuova == stored:
        raise HttpError(400, "La nuova password deve essere diversa da quella attuale")
    storage.update_record("utenti", user["id"], {"password_hash": nuova, "primo_login": False})
    invalidate_user_sessions(user["id"])
    log(f"[AUTH] '{ctx.username}' ha cambiato la propria password")
    return 200, {"ok": True}

@route("GET", "/api/stato", OPER, renew=False)
def h_stato(ctx):
    register_client(ctx.ip, ctx.handler.headers.get("X-Client-ID"))
    return 200, get_timestamps(ctx.nid)

# ─── ENDPOINT: backup (superadmin) ───────────────────────────────────────────

def backup_info():
    return {"backups": storage.backup_list(), "intervallo": storage.BACKUP_MIN_INTERVAL,
            "conservati": storage.MAX_BACKUPS, "backend": os.environ.get("DB_BACKEND", "json").lower()}

@route("GET", "/api/backup", SUPER)
def h_get_backup(ctx):
    return 200, backup_info()

@route("POST", "/api/backup", SUPER)
def h_run_backup(ctx):
    """Backup immediato (snapshot json, oppure pg_dump/mysqldump). Sincrono: ritorna a backup concluso."""
    scritture = storage.write_count()
    r = storage.backup_run()
    if not r["ok"]:
        log(f"[BACKUP] Backup richiesto da '{ctx.username}' non riuscito: {r['error']}", "error")
        raise HttpError(409 if "già in corso" in (r["error"] or "") else 500, f"Backup non riuscito: {r['error']}")
    backup_seen["scritture"] = scritture
    log(f"[BACKUP] Backup creato da '{ctx.username}': {r['file']}")
    return 200, {"ok": True, "file": r["file"], "avvisi": r.get("avvisi", []), **backup_info()}

# ─── ENDPOINT: negozi (superadmin) ───────────────────────────────────────────

@route("GET", "/api/negozi", SUPER)
def h_get_negozi(ctx):
    return 200, {"negozi": storage.list_records("negozi")}

@route("POST", "/api/negozi", SUPER)
def h_create_negozio(ctx):
    nome = need_text(ctx.body(), "nome", "Nome")
    rec = storage.insert_record("negozi", {"id": new_id("n_"), "nome": nome, "creato_il": now_iso()})
    log(f"[NEGOZI] Negozio '{nome}' creato da '{ctx.username}'")
    return 201, {"ok": True, "negozio": rec}

@route("PUT", "/api/negozi/:nid", SUPER)
def h_update_negozio(ctx, nid):
    nome = need_text(ctx.body(), "nome", "Nome")
    rec_or_404("negozi", nid, "Negozio")
    storage.update_record("negozi", nid, {"nome": nome})
    log(f"[NEGOZI] Negozio {nid} rinominato '{nome}' da '{ctx.username}'")
    return 200, {"ok": True}

@route("DELETE", "/api/negozi/:nid", SUPER)
def h_delete_negozio(ctx, nid):
    neg = rec_or_404("negozi", nid, "Negozio")
    try:
        storage.delete_record("negozi", nid)
    except IntegrityError:
        raise HttpError(409, "Impossibile eliminare: il negozio ha utenti o dati associati")
    log(f"[NEGOZI] Negozio '{neg['nome']}' eliminato da '{ctx.username}'")
    return 200, {"ok": True}

# ─── ENDPOINT: tipi account ──────────────────────────────────────────────────

def clean_permessi(value):
    if not isinstance(value, list):
        raise HttpError(400, "permessi deve essere una lista")
    out = []
    for p in value:
        if isinstance(p, str) and p in PERMESSI_VALIDI and p not in out:
            out.append(p)
    return out

@route("GET", "/api/tipi-account", "tipi_account.leggi")
def h_get_tipi(ctx):
    return 200, {"tipi_account": storage.list_records("tipi_account")}

@route("POST", "/api/tipi-account", SUPER)
def h_create_tipo(ctx):
    b = ctx.body()
    nome = need_text(b, "nome", "Nome")
    permessi = clean_permessi(b.get("permessi", []))
    now = now_iso()
    try:
        rec = storage.insert_record("tipi_account", {
            "id": new_id("ta_"), "nome": nome, "permessi": permessi,
            "creato_il": now, "modificato_il": now})
    except DuplicateError:
        raise HttpError(409, f"Esiste già un tipo account '{nome}'")
    log(f"[TIPI_ACCOUNT] Tipo '{nome}' creato da '{ctx.username}'")
    return 201, {"ok": True, "tipo": rec}

@route("PUT", "/api/tipi-account/:tid", SUPER)
def h_update_tipo(ctx, tid):
    b = ctx.body()
    changes = {}
    if "nome" in b:
        changes["nome"] = need_text(b, "nome", "Nome")
    if "permessi" in b:
        changes["permessi"] = clean_permessi(b["permessi"])
    if not changes:
        raise HttpError(400, "Nessuna modifica indicata")
    tipo = rec_or_404("tipi_account", tid, "Tipo account")
    changes["modificato_il"] = now_iso()
    try:
        storage.update_record("tipi_account", tid, changes)
    except DuplicateError:
        raise HttpError(409, f"Esiste già un tipo account '{changes['nome']}'")
    if set(changes.get("permessi", tipo.get("permessi", []))) != set(tipo.get("permessi", [])):
        # i permessi sono copiati nella sessione al login: senza questo una revoca non varrebbe per chi
        # è già connesso (la scadenza scorre a ogni richiesta). Gli utenti del tipo devono rifare il login.
        utenti = storage.list_records("utenti", {"tipo_account_id": tid})
        for u in utenti:
            invalidate_user_sessions(u["id"])
        log(f"[TIPI_ACCOUNT] Permessi di '{tipo['nome']}' cambiati: sessioni chiuse per {len(utenti)} utenti")
    log(f"[TIPI_ACCOUNT] Tipo '{tipo['nome']}' modificato da '{ctx.username}'")
    return 200, {"ok": True}

@route("DELETE", "/api/tipi-account/:tid", SUPER)
def h_delete_tipo(ctx, tid):
    tipo = rec_or_404("tipi_account", tid, "Tipo account")
    try:
        storage.delete_record("tipi_account", tid)
    except IntegrityError:
        raise HttpError(409, "Impossibile eliminare: il tipo account è assegnato a degli utenti")
    log(f"[TIPI_ACCOUNT] Tipo '{tipo['nome']}' eliminato da '{ctx.username}'")
    return 200, {"ok": True}

# ─── ENDPOINT: utenti ────────────────────────────────────────────────────────

def public_user(u):
    return {k: v for k, v in u.items() if k != "password_hash"}

def check_not_escalating(ctx, permessi):
    """Chi non è superadmin può assegnare o toccare solo ciò che è contenuto nei propri permessi."""
    if ctx.session["is_superadmin"]:
        return
    if not set(permessi) <= set(ctx.session["permessi"]):
        raise HttpError(403, "Non puoi assegnare o modificare permessi che non possiedi")

def target_user(ctx, uid):
    """Utente su cui si agisce: esiste, non è il superadmin, non è chi agisce, è del negozio giusto."""
    u = rec_or_404("utenti", uid, "Utente")
    if u.get("is_superadmin"):
        raise HttpError(403, "Non puoi modificare il superadmin")
    if not ctx.session["is_superadmin"] and u.get("negozio_id") != ctx.nid:
        raise HttpError(403, "Accesso negato: negozio non corrispondente")
    check_not_escalating(ctx, resolve_permessi(u))   # non si agisce su chi ha più permessi di noi
    return u

@route("GET", "/api/utenti", "utenti.leggi")
def h_get_utenti(ctx):
    f = None if ctx.session["is_superadmin"] else {"negozio_id": ctx.nid}
    utenti = [public_user(u) for u in storage.list_records("utenti", f) if not u.get("is_superadmin")]
    return 200, {"utenti": utenti}

@route("POST", "/api/utenti", "utenti.crea")
def h_create_utente(ctx):
    b = ctx.body()
    username = need_text(b, "username", "Username")
    pwd_hash = need_hash(b, "password_hash")
    tipo = storage.get_record("tipi_account", b.get("tipo_account_id")) if isinstance(b.get("tipo_account_id"), str) else None
    if not tipo:
        raise HttpError(400, "Tipo account non valido")
    check_not_escalating(ctx, [p for p in tipo.get("permessi", []) if p in PERMESSI_VALIDI])
    if ctx.session["is_superadmin"]:
        nid = b.get("negozio_id")
        neg = storage.get_record("negozi", nid) if isinstance(nid, str) else None
        if not neg:
            raise HttpError(400, "negozio_id non valido")
    else:
        nid = ctx.nid
        neg = storage.get_record("negozi", nid)
    try:
        rec = storage.insert_record("utenti", {
            "id": new_id("u_"), "username": username, "password_hash": pwd_hash,
            "tipo_account_id": tipo["id"], "negozio_id": nid,
            "is_superadmin": False, "primo_login": False,
            "creato_da": ctx.session["user_id"], "creato_il": now_iso()})
    except DuplicateError:
        raise HttpError(409, f"Username '{username}' già esistente")
    log(f"[UTENTI] Utente '{username}' ({tipo['nome']}) creato per negozio '{neg['nome'] if neg else nid}' da '{ctx.username}'")
    return 201, {"ok": True, "id": rec["id"]}

@route("PUT", "/api/utenti/:uid/password", "utenti.modifica")
def h_set_password(ctx, uid):
    nuova = need_hash(ctx.body(), "nuova_hash")
    u = target_user(ctx, uid)
    if u["id"] == ctx.session["user_id"]:
        raise HttpError(403, "Per la tua password usa il cambio password personale")
    # primo_login: l'utente deve scegliere una password sua al prossimo accesso
    storage.update_record("utenti", uid, {"password_hash": nuova, "primo_login": True})
    invalidate_user_sessions(uid)
    log(f"[UTENTI] Password di '{u['username']}' reimpostata da '{ctx.username}'")
    return 200, {"ok": True}

@route("PUT", "/api/utenti/:uid/tipo", "utenti.modifica")
def h_set_tipo(ctx, uid):
    tid = ctx.body().get("tipo_account_id")
    tipo = storage.get_record("tipi_account", tid) if isinstance(tid, str) else None
    if not tipo:
        raise HttpError(400, "tipo_account_id non valido")
    u = target_user(ctx, uid)
    if u["id"] == ctx.session["user_id"]:
        raise HttpError(403, "Non puoi modificare il tuo stesso account")
    check_not_escalating(ctx, [p for p in tipo.get("permessi", []) if p in PERMESSI_VALIDI])
    storage.update_record("utenti", uid, {"tipo_account_id": tid})
    invalidate_user_sessions(uid)
    log(f"[UTENTI] Tipo account di '{u['username']}' cambiato in '{tipo['nome']}' da '{ctx.username}'")
    return 200, {"ok": True}

@route("DELETE", "/api/utenti/:uid", "utenti.elimina")
def h_delete_utente(ctx, uid):
    u = target_user(ctx, uid)
    if u["id"] == ctx.session["user_id"]:
        raise HttpError(403, "Non puoi eliminare il tuo stesso account")
    storage.delete_record("utenti", uid)
    invalidate_user_sessions(uid)
    log(f"[UTENTI] Utente '{u['username']}' eliminato da '{ctx.username}'")
    return 200, {"ok": True}

# ─── ENDPOINT: consegne ──────────────────────────────────────────────────────

TIPI_CONSEGNA = {"consegna", "installazione", "incasso", "ins_incasso", "ins_muro", "ins_sbs"}
# Campi noti di una consegna (inviati dal frontend, più i campi legacy V1 ancora letti da render/stampa): di testo
CONSEGNA_CAMPI = {
    "dataPrenotazione", "stato", "nome", "cognome", "citta", "indirizzo", "tel1", "tel2", "raee", "piano",
    "noteAbitazione", "preferenzePeriodo", "giornoConsegna", "fasciaOraria", "note", "articoli",
    "tipoProdotto", "codiceProdotto", "descrizioneProdotto", "tipoConsegna",
}
ARTICOLO_CAMPI = {"tipoConsegna", "tipo", "codice", "desc"}
MAX_TESTO = 2000      # caratteri per campo di testo di una consegna
MAX_ARTICOLI = 50
MAX_EXTRA = 20        # campi sconosciuti (conservati come extra) per richiesta
MAX_TESTO_ARTICOLO = 500

def clean_articoli(v):
    """Struttura di `articoli`: il frontend la dà per scontata, un elemento malformato (null, tipo
    sconosciuto) romperebbe il rendering per tutti gli utenti del negozio."""
    if not isinstance(v, list) or len(v) > MAX_ARTICOLI:
        raise HttpError(400, "articoli non valido")
    for a in v:
        if not isinstance(a, dict) or not set(a) <= ARTICOLO_CAMPI:
            raise HttpError(400, "articolo non valido")
        if a.get("tipoConsegna", "consegna") not in TIPI_CONSEGNA:
            raise HttpError(400, "tipoConsegna non valido")
        for k in ("tipo", "codice", "desc"):
            x = a.get(k, "")
            if not isinstance(x, str) or len(x) > MAX_TESTO_ARTICOLO:
                raise HttpError(400, f"articolo.{k} non valido")
    return v

def consegna_fields(body):
    f = {k: v for k, v in body.items() if k not in ("id", "negozio_id", "versione") and not k.startswith("_")}
    # campi sconosciuti: ammessi (lo storage li conserva come "extra" per i campi futuri) ma limitati
    sconosciuti = set(f) - CONSEGNA_CAMPI
    if len(sconosciuti) > MAX_EXTRA or any(len(k) > 50 or len(json.dumps(f[k])) > MAX_TESTO for k in sconosciuti):
        raise HttpError(400, "Troppi campi aggiuntivi o troppo grandi")
    if "stato" in f and f["stato"] not in STATI_CONSEGNA:
        raise HttpError(400, "stato non valido")
    if "tipoConsegna" in f and f["tipoConsegna"] not in TIPI_CONSEGNA:
        raise HttpError(400, "tipoConsegna non valido")
    for k, v in f.items():
        if k in CONSEGNA_CAMPI and k != "articoli" and (not isinstance(v, str) or len(v) > MAX_TESTO):
            raise HttpError(400, f"{k} deve essere un testo di al massimo {MAX_TESTO} caratteri")
    if "articoli" in f:
        clean_articoli(f["articoli"])
    return f

@route("GET", "/api/consegne", "consegne.leggi")
def h_get_consegne(ctx):
    return 200, {"consegne": storage.list_records("consegne", {"negozio_id": ctx.nid})}

@route("POST", "/api/consegne", "consegne.scrivi")
def h_create_consegna(ctx):
    rec = {**consegna_fields(ctx.body()), "id": new_id("c_"), "negozio_id": ctx.nid}
    storage.insert_record("consegne", rec)
    touch(ctx.nid, "consegne")
    ctx.dlog(f"Nuova consegna: {label_consegna(rec)}")
    return 201, db_negozio(ctx)

@route("PUT", "/api/consegne/:cid", "consegne.scrivi")
def h_update_consegna(ctx, cid):
    b = ctx.body()
    ver = need_versione(b)
    changes = consegna_fields(b)
    cur = rec_or_404("consegne", cid, "Consegna")
    check_tenant(ctx, cur)
    try:
        storage.update_record("consegne", cid, changes, expected_versione=ver)
    except ConflictError:
        raise HttpError(409, "La consegna è stata modificata da un altro utente. Ricarica e riprova.")
    touch(ctx.nid, "consegne")
    ctx.dlog(f"Modificata consegna: {label_consegna({**cur, **changes})}")
    return 200, db_negozio(ctx)

@route("DELETE", "/api/consegne/:cid", "consegne.elimina")
def h_delete_consegna(ctx, cid):
    cur = rec_or_404("consegne", cid, "Consegna")
    check_tenant(ctx, cur)
    storage.delete_record("consegne", cid)   # la toglie da tutte le giornate
    touch(ctx.nid, "consegne", "giornate")
    ctx.dlog(f"Eliminata consegna: {label_consegna(cur)}")
    return 200, db_negozio(ctx)

# ─── ENDPOINT: giornate ──────────────────────────────────────────────────────

def giornata_del_negozio(ctx, gid):
    g = rec_or_404("giornate", gid, "Giornata")
    check_tenant(ctx, g)
    return g

@route("GET", "/api/giornate", "giornate.leggi")
def h_get_giornate(ctx):
    return 200, {"giornate": storage.list_records("giornate", {"negozio_id": ctx.nid})}

@route("POST", "/api/giornate", "giornate.crea")
def h_create_giornata(ctx):
    b = ctx.body()
    data = need_text(b, "data", "data")
    if not DATA_RE.fullmatch(data):
        raise HttpError(400, "data non valida (atteso AAAA-MM-GG)")
    # la squadra è obbligatoria: deve esistere ed essere del negozio della sessione
    sid = b.get("squadra_id")
    if not isinstance(sid, str) or not sid:
        raise HttpError(400, "squadra_id obbligatorio")
    sq = storage.get_record("squadre", sid)
    if sq is None:
        raise HttpError(400, "squadra non valida")
    check_tenant(ctx, sq)
    storage.insert_record("giornate", {"id": new_id("g_"), "negozio_id": ctx.nid,
                                       "data": data, "squadra_id": sid})
    touch(ctx.nid, "giornate")
    ctx.dlog(f"Aggiunta giornata {data}")
    return 201, db_negozio(ctx)

@route("DELETE", "/api/giornate/:gid", "giornate.elimina")
def h_delete_giornata(ctx, gid):
    g = giornata_del_negozio(ctx, gid)
    if g.get("consegneIds"):
        raise HttpError(409, "La giornata contiene consegne assegnate: rimuovile prima")
    storage.delete_record("giornate", gid)
    touch(ctx.nid, "giornate")
    ctx.dlog(f"Eliminata giornata {g['data']}")
    return 200, db_negozio(ctx)

@route("POST", "/api/giornate/:gid/assegna", "giornate.assegna")
def h_giornata_assegna(ctx, gid):
    g = giornata_del_negozio(ctx, gid)
    cids = need_id_list(ctx.body(), "consegna_ids")
    for cid in cids:
        check_tenant(ctx, rec_or_404("consegne", cid, "Consegna"))
    storage.giornata_assegna(gid, cids)
    for cid in cids:
        storage.update_record("consegne", cid, {"stato": "da_confermare", "giornoConsegna": g["data"]})
    touch(ctx.nid, "giornate", "consegne")
    ctx.dlog(f"Aggiunte {len(cids)} consegne alla giornata {g['data']}")
    return 200, db_negozio(ctx)

@route("DELETE", "/api/giornate/:gid/assegna/:cid", "giornate.assegna")
def h_giornata_rimuovi(ctx, gid, cid):
    g = giornata_del_negozio(ctx, gid)
    storage.giornata_rimuovi(gid, cid)
    c = storage.get_record("consegne", cid)
    if c is not None and c.get("negozio_id") == ctx.nid and c.get("stato") in STATI_ASSEGNATI:
        storage.update_record("consegne", cid, {"stato": "in_attesa", "giornoConsegna": "", "fasciaOraria": ""})
    touch(ctx.nid, "giornate", "consegne")
    ctx.dlog(f"Rimossa consegna {cid} dalla giornata {g['data']}")
    return 200, db_negozio(ctx)

@route("PUT", "/api/giornate/:gid/riordina", "giornate.riordina")
def h_giornata_riordina(ctx, gid):
    g = giornata_del_negozio(ctx, gid)
    storage.giornata_riordina(gid, need_id_list(ctx.body(), "consegna_ids"))
    touch(ctx.nid, "giornate")
    ctx.dlog(f"Riordinata giornata {g['data']}")
    return 200, db_negozio(ctx)

@route("PUT", "/api/giornate/:gid/consegne/:cid/completa", "giornate.segna_completata")
def h_segna_completata(ctx, gid, cid):
    g = giornata_del_negozio(ctx, gid)
    if cid not in g.get("consegneIds", []):
        raise HttpError(404, "Consegna non presente nella giornata")
    c = rec_or_404("consegne", cid, "Consegna")
    check_tenant(ctx, c)
    storage.update_record("consegne", cid, {"stato": "completata"})
    touch(ctx.nid, "consegne")
    ctx.dlog(f"Consegna completata: {label_consegna(c)}")
    return 200, db_negozio(ctx)

# ─── ENDPOINT: squadre ───────────────────────────────────────────────────────

def nome_squadra_libero(ctx, nome, escludi_id=None):
    for s in storage.list_records("squadre", {"negozio_id": ctx.nid}):
        if s["id"] != escludi_id and s["nome"].casefold() == nome.casefold():
            raise HttpError(409, "Squadra già esistente")

@route("GET", "/api/squadre", "squadre.leggi")
def h_get_squadre(ctx):
    return 200, {"squadre": storage.list_records("squadre", {"negozio_id": ctx.nid})}

@route("POST", "/api/squadre", "squadre.gestisci")
def h_create_squadra(ctx):
    nome = need_text(ctx.body(), "nome", "Nome")
    nome_squadra_libero(ctx, nome)
    n = len(storage.list_records("squadre", {"negozio_id": ctx.nid}))
    storage.insert_record("squadre", {"id": new_id("sq_"), "negozio_id": ctx.nid,
                                      "nome": nome, "colorIdx": n % SQ_COLORS})
    touch(ctx.nid, "squadre")
    ctx.dlog(f"Aggiunta squadra '{nome}'")
    return 201, db_negozio(ctx)

@route("PUT", "/api/squadre/:sid", "squadre.gestisci")
def h_update_squadra(ctx, sid):
    b = ctx.body()
    ver = need_versione(b)
    cur = rec_or_404("squadre", sid, "Squadra")
    check_tenant(ctx, cur)
    changes = {}
    if "nome" in b:
        changes["nome"] = need_text(b, "nome", "Nome")
    if "colorIdx" in b:
        ci = b["colorIdx"]
        if not isinstance(ci, int) or isinstance(ci, bool) or not 0 <= ci < SQ_COLORS:
            raise HttpError(400, "colorIdx non valido")
        changes["colorIdx"] = ci
    if not changes:
        raise HttpError(400, "Nessuna modifica indicata")
    if "nome" in changes and changes["nome"] != cur["nome"]:
        nome_squadra_libero(ctx, changes["nome"], escludi_id=sid)
    if cur.get("versione") != ver:
        raise HttpError(409, "La squadra è stata modificata da un altro utente. Ricarica e riprova.")
    try:
        storage.update_record("squadre", sid, changes, expected_versione=ver)
    except ConflictError:
        raise HttpError(409, "La squadra è stata modificata da un altro utente. Ricarica e riprova.")
    touch(ctx.nid, "squadre")      # le giornate la referenziano per id: la rinomina non le tocca
    ctx.dlog(f"Aggiornata squadra '{cur['nome']}'")
    return 200, db_negozio(ctx)

@route("DELETE", "/api/squadre/:sid", "squadre.gestisci")
def h_delete_squadra(ctx, sid):
    cur = rec_or_404("squadre", sid, "Squadra")
    check_tenant(ctx, cur)
    msg = "La squadra ha giornate assegnate: eliminale prima"
    if storage.list_records("giornate", {"negozio_id": ctx.nid, "squadra_id": sid}):
        raise HttpError(409, msg)
    try:
        storage.delete_record("squadre", sid)
    except IntegrityError:     # una giornata è stata creata nel frattempo: il vincolo dello storage vince
        raise HttpError(409, msg)
    touch(ctx.nid, "squadre")
    ctx.dlog(f"Eliminata squadra '{cur['nome']}'")
    return 200, db_negozio(ctx)

# ─── HTTP HANDLER ────────────────────────────────────────────────────────────

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js":   "application/javascript; charset=utf-8",
    ".css":  "text/css; charset=utf-8",
}
STATIC_DIRS = ("css", "js")

# Header di sicurezza su ogni risposta. 'unsafe-inline' serve agli script e ai gestori inline di index.html.
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Content-Security-Policy",
     "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
     "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
     "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
)

class Handler(http.server.BaseHTTPRequestHandler):

    def end_headers(self):
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)
        super().end_headers()

    timeout = 15   # secondi di inattività del socket: chiude connessioni mute o inviate a pezzi (slowloris)

    def log_message(self, format, *args):
        log(format % args, "debug")

    def log_error(self, format, *args):
        log(format % args, "error")

    # -- risposte --
    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise HttpError(400, "Content-Length non valido")
        if length < 0:
            raise HttpError(400, "Content-Length non valido")
        if length > MAX_BODY:
            raise HttpError(413, "Richiesta troppo grande")
        if length == 0:
            return {}
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HttpError(400, "JSON non valido")
        if not isinstance(body, dict):
            raise HttpError(400, "Il corpo deve essere un oggetto JSON")
        return body

    # -- metodi --
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):    self._dispatch("GET")
    def do_POST(self):   self._dispatch("POST")
    def do_PUT(self):    self._dispatch("PUT")
    def do_DELETE(self): self._dispatch("DELETE")

    def _dispatch(self, method):
        path = self.path.split("?")[0].split("#")[0]
        if len(path) > 1:
            path = path.rstrip("/")
        if not path.startswith("/api/"):
            if method == "GET":
                return self._serve_static(path)
            return self.send_json(404, {"error": "Risorsa non trovata"})
        try:
            self._dispatch_api(method, path)
        except HttpError as e:
            self.send_json(e.code, {"error": e.message})
        except ConflictError:
            self.send_json(409, {"error": "Il dato è stato modificato da un altro utente. Ricarica e riprova."})
        except NotFoundError:
            self.send_json(404, {"error": "Risorsa non trovata"})
        except (DuplicateError, IntegrityError) as e:
            log(f"[DATI] Vincolo violato: {e}", "warning")
            self.send_json(409, {"error": "Operazione non consentita dai vincoli dei dati"})
        except ValueError as e:
            log(f"[DATI] Dati non validi: {e}", "warning")
            self.send_json(400, {"error": f"Dati non validi: {e}"})
        except Exception:
            logging.exception("Errore interno su %s %s", method, path)
            self.send_json(500, {"error": "Errore interno"})

    def _dispatch_api(self, method, path):
        for m, rx, requirement, pending_ok, renew, fn in ROUTES:
            if m != method:
                continue
            match = rx.match(path)
            if not match:
                continue
            params = {k: unquote(v) for k, v in match.groupdict().items()}
            token = self.headers.get("X-Session-Token", "")
            session = None
            if requirement != PUBLIC:
                session = get_session(token, renew=renew)
                if not session:
                    raise HttpError(401, "Non autenticato")
                if session["must_change_password"] and not pending_ok:
                    raise HttpError(403, "Cambio password obbligatorio")
                authorize(session, requirement)
            code, payload = fn(Ctx(self, token, session, params), **params)
            return self.send_json(code, payload)
        raise HttpError(404, "Risorsa non trovata")

    def _serve_static(self, url_path):
        if url_path in ("", "/", "."):
            self.send_response(302)
            self.send_header("Location", "/index.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        safe_rel = os.path.normpath(unquote(url_path).lstrip("/"))
        first = safe_rel.replace("\\", "/").split("/")[0]
        # solo il frontend: mai il codice del server o altri file dell'immagine
        if safe_rel.startswith("..") or not (safe_rel == "index.html" or first in STATIC_DIRS):
            return self._plain(404)
        path = os.path.join(BASE_DIR, safe_rel)
        if not os.path.isfile(path):
            return self._plain(404)
        mime = STATIC_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _plain(self, code):
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

# ─── MAIN ────────────────────────────────────────────────────────────────────

def init_data_layer():
    """Inizializza lo storage V2. Esce con codice 2 se l'archivio non è uno schema V2 valido."""
    try:
        storage.init_storage_v2()
        ensure_superadmin()
    except SchemaError as e:
        log(f"AVVIO RIFIUTATO — archivio dati non valido per la V2: {e}", "critical")
        log("Migrare i dati con migrate.py oppure usare un database/cartella dati nuovi.", "critical")
        sys.exit(2)
    except StorageError as e:
        log(f"AVVIO FALLITO — storage non disponibile: {e}", "critical")
        sys.exit(1)

def make_server(port):
    return Server(("0.0.0.0", port), Handler)

if __name__ == "__main__":
    setup_logging()
    log("=" * 50)
    log(f"Avvio Gestione Consegne V2 (porta {PORT}, backend {os.environ.get('DB_BACKEND', 'json')})...")
    init_data_layer()
    threading.Thread(target=backup_loop, name="backup", daemon=True).start()
    server = make_server(PORT)
    log(f"Server in ascolto su 0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        backup_stop.set()
        log("Server fermato.")
        server.server_close()
