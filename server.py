#!/usr/bin/env python3
"""
Gestione Consegne — Server v2
- Autenticazione Challenge-Response (SHA-256)
- Permessi granulari per tipo di account
- Multi-tenancy (negozi)
- API REST per ogni operazione
- Optimistic locking (campo versione)
- Log generati server-side
- Polling via timestamp per categoria
"""

import http.server
import json
import os
import socket
import threading
import time
import webbrowser
import glob
import logging
import hashlib
import secrets
from datetime import datetime, timedelta

PORT          = 8742
BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
DATA_FILE     = os.path.join(BASE_DIR, "dati.json")
USERS_FILE    = os.path.join(BASE_DIR, "utenti.json")
TIPI_FILE     = os.path.join(BASE_DIR, "tipi_account.json")
NEGOZI_FILE   = os.path.join(BASE_DIR, "negozi.json")
LOCK_FILE     = os.path.join(BASE_DIR, "server.lock")
BACKUP_DIR    = os.path.join(BASE_DIR, "backup")
LOG_FILE      = os.path.join(BASE_DIR, "gestionale.log")
MAX_BACKUPS   = 20
LOG_DAYS      = 7
SESSION_TTL   = 7200   # 2 ore
CHALLENGE_TTL = 60     # 60 secondi

file_lock       = threading.Lock()
users_lock      = threading.Lock()
tipi_lock       = threading.Lock()
negozi_lock     = threading.Lock()
sessions_lock   = threading.Lock()
challenges_lock = threading.Lock()
timestamps_lock = threading.Lock()

connected_clients = set()
clients_lock      = threading.Lock()
client_heartbeat  = {}

sessions   = {}
challenges = {}

# Timestamp ultima modifica per categoria (per polling efficiente)
data_timestamps = {
    "consegne": 0.0,
    "giornate":  0.0,
    "squadre":   0.0,
}

# Permessi hardcoded superadmin
SUPERADMIN_PERMESSI = {
    "tipi_account.leggi",
    "tipi_account.gestisci",
    "negozi.gestisci",
    "utenti.leggi",
    "utenti.crea",
    "utenti.modifica",
    "utenti.elimina",
}

# Tutti i permessi assegnabili ai tipi account
PERMESSI_VALIDI = {
    "consegne.leggi",
    "consegne.scrivi",
    "consegne.elimina",
    "giornate.leggi",
    "giornate.crea",
    "giornate.elimina",
    "giornate.assegna",
    "giornate.riordina",
    "giornate.segna_completata",
    "squadre.leggi",
    "squadre.gestisci",
    "stampa.pdf",
    "tipi_account.leggi",
    "utenti.leggi",
    "utenti.crea",
    "utenti.modifica",
    "utenti.elimina",
}

# ─── LOGGING ────────────────────────────────────────────────────────────────

def setup_logging():
    os.makedirs(BASE_DIR, exist_ok=True)
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        encoding="utf-8"
    )

def log(msg, level="info"):
    getattr(logging, level)(msg)

def rotate_log():
    if not os.path.exists(LOG_FILE):
        return
    try:
        cutoff = datetime.now() - timedelta(days=LOG_DAYS)
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        kept = []
        for line in lines:
            try:
                ts_str = line.split(" [")[0]
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                if ts >= cutoff:
                    kept.append(line)
            except Exception:
                kept.append(line)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(kept)
    except Exception as e:
        print(f"[WARN] Rotazione log fallita: {e}")

# ─── SHA-256 ─────────────────────────────────────────────────────────────────

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def store_password(h1: str) -> str:
    return h1

# ─── TIMESTAMPS ──────────────────────────────────────────────────────────────

def touch_timestamp(categoria: str):
    with timestamps_lock:
        data_timestamps[categoria] = time.time()

def get_timestamps() -> dict:
    with timestamps_lock:
        return dict(data_timestamps)

# ─── FILE I/O GENERICI ───────────────────────────────────────────────────────

def _read_json(path: str, default: dict) -> dict:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path: str, data: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

# ─── UTENTI I/O ──────────────────────────────────────────────────────────────

DEFAULT_SUPERADMIN_H1 = sha256_hex("admin")

def _read_users_raw() -> dict:
    return _read_json(USERS_FILE, {"utenti": []})

def _write_users_raw(data: dict):
    _write_json(USERS_FILE, data)

def read_users() -> dict:
    with users_lock:
        return _read_users_raw()

def write_users(data: dict):
    with users_lock:
        _write_users_raw(data)

def init_users():
    if os.path.exists(USERS_FILE):
        data = _read_users_raw()
        if any(u.get("id") == "u_superadmin" for u in data.get("utenti", [])):
            return

    log("Inizializzazione utenti.json con superadmin di default.")
    superadmin = {
        "id":              "u_superadmin",
        "username":        "superadmin",
        "password_hash":   store_password(DEFAULT_SUPERADMIN_H1),
        "tipo_account_id": None,
        "negozio_id":      None,
        "primo_login":     True,
        "creato_da":       None,
        "creato_il":       datetime.now().isoformat(),
        "ultimo_accesso":  None,
    }
    _write_users_raw({"utenti": [superadmin]})
    log("Superadmin creato. Username: superadmin / Password: admin")

def find_user_by_username(username: str) -> dict | None:
    data = read_users()
    for u in data.get("utenti", []):
        if u.get("username", "").lower() == username.lower():
            return u
    return None

def find_user_by_id(user_id: str) -> dict | None:
    data = read_users()
    for u in data.get("utenti", []):
        if u.get("id") == user_id:
            return u
    return None

# ─── TIPI ACCOUNT I/O ────────────────────────────────────────────────────────

def read_tipi() -> dict:
    with tipi_lock:
        return _read_json(TIPI_FILE, {"tipi_account": []})

def write_tipi(data: dict):
    with tipi_lock:
        _write_json(TIPI_FILE, data)

def init_tipi():
    if not os.path.exists(TIPI_FILE):
        _write_json(TIPI_FILE, {"tipi_account": []})

def find_tipo_by_id(tipo_id: str) -> dict | None:
    data = read_tipi()
    for t in data.get("tipi_account", []):
        if t.get("id") == tipo_id:
            return t
    return None

# ─── NEGOZI I/O ──────────────────────────────────────────────────────────────

def read_negozi() -> dict:
    with negozi_lock:
        return _read_json(NEGOZI_FILE, {"negozi": []})

def write_negozi(data: dict):
    with negozi_lock:
        _write_json(NEGOZI_FILE, data)

def init_negozi():
    if not os.path.exists(NEGOZI_FILE):
        _write_json(NEGOZI_FILE, {"negozi": []})

def find_negozio_by_id(negozio_id: str) -> dict | None:
    data = read_negozi()
    for n in data.get("negozi", []):
        if n.get("id") == negozio_id:
            return n
    return None

# ─── CHALLENGE ───────────────────────────────────────────────────────────────

def new_challenge() -> str:
    ch = secrets.token_hex(32)
    with challenges_lock:
        challenges[ch] = time.time()
    return ch

def consume_challenge(ch: str) -> bool:
    with challenges_lock:
        ts = challenges.pop(ch, None)
    if ts is None:
        return False
    return (time.time() - ts) < CHALLENGE_TTL

def cleanup_challenges():
    while True:
        time.sleep(30)
        now = time.time()
        with challenges_lock:
            expired = [c for c, ts in challenges.items() if now - ts > CHALLENGE_TTL]
            for c in expired:
                del challenges[c]

# ─── SESSIONI ────────────────────────────────────────────────────────────────

def new_session(user: dict, permessi: list) -> str:
    token = secrets.token_urlsafe(32)
    now   = time.time()
    with sessions_lock:
        sessions[token] = {
            "user_id":              user["id"],
            "username":             user["username"],
            "negozio_id":           user.get("negozio_id"),
            "permessi":             permessi,
            "is_superadmin":        user.get("id") == "u_superadmin",
            "last_seen":            now,
            "expires":              now + SESSION_TTL,
            "must_change_password": user.get("primo_login", False),
        }
    return token

def get_session(token: str) -> dict | None:
    with sessions_lock:
        s = sessions.get(token)
        if s is None:
            return None
        if time.time() > s["expires"]:
            del sessions[token]
            return None
        s["last_seen"] = time.time()
        s["expires"]   = s["last_seen"] + SESSION_TTL
        return dict(s)

def delete_session(token: str):
    with sessions_lock:
        sessions.pop(token, None)

def cleanup_sessions():
    while True:
        time.sleep(300)
        now = time.time()
        with sessions_lock:
            expired = [t for t, s in sessions.items() if now > s["expires"]]
            for t in expired:
                del sessions[t]

def _resolve_permessi(user: dict) -> list:
    """Ritorna la lista permessi per la sessione in base al tipo account."""
    if user.get("id") == "u_superadmin":
        return list(SUPERADMIN_PERMESSI)
    tipo_id = user.get("tipo_account_id")
    if not tipo_id:
        return []
    tipo = find_tipo_by_id(tipo_id)
    if not tipo:
        return []
    return list(tipo.get("permessi", []))

# ─── DATA I/O ────────────────────────────────────────────────────────────────

def read_data() -> dict:
    with file_lock:
        return _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})

def _write_data_raw(data: dict):
    make_backup()
    _write_json(DATA_FILE, data)

def make_backup():
    try:
        if not os.path.exists(DATA_FILE):
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts  = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dst = os.path.join(BACKUP_DIR, f"dati.{ts}.json")
        with open(DATA_FILE, "r", encoding="utf-8") as src_f:
            content = src_f.read()
        with open(dst, "w", encoding="utf-8") as dst_f:
            dst_f.write(content)
        backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "dati.*.json")))
        while len(backups) > MAX_BACKUPS:
            os.remove(backups.pop(0))
    except Exception as e:
        log(f"Backup fallito (non critico): {e}", "warning")

def _db_for_negozio(negozio_id: str) -> dict:
    """Ritorna consegne/giornate/squadre filtrate per negozio."""
    data = read_data()
    return {
        "consegne": [c for c in data.get("consegne", []) if c.get("negozio_id") == negozio_id],
        "giornate": [g for g in data.get("giornate", []) if g.get("negozio_id") == negozio_id],
        "squadre":  [s for s in data.get("squadre",  []) if s.get("negozio_id") == negozio_id],
    }

# ─── SERVER LOCK ─────────────────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def write_lock():
    ip   = get_local_ip()
    info = {"ip": ip, "port": PORT, "pid": os.getpid(), "started": datetime.now().isoformat()}
    tmp  = LOCK_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(info, f)
    os.replace(tmp, LOCK_FILE)
    log(f"Server avviato su {ip}:{PORT} (PID {os.getpid()})")

def remove_lock():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception as e:
        log(f"Impossibile rimuovere lock: {e}", "warning")

# ─── CRASH ───────────────────────────────────────────────────────────────────

# ─── CONNECTED CLIENTS ───────────────────────────────────────────────────────

def register_client(ip):
    with clients_lock:
        client_heartbeat[ip] = time.time()
        connected_clients.add(ip)

def get_connected_count():
    now = time.time()
    with clients_lock:
        active = {ip for ip, ts in client_heartbeat.items() if now - ts < 15}
        connected_clients.intersection_update(active)
        return len(active)

# ─── HTTP HANDLER ─────────────────────────────────────────────────────────────

class Handler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-Token")

    def _json_response(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _check_auth(self) -> dict | None:
        token   = self.headers.get("X-Session-Token", "")
        session = get_session(token)
        if not session:
            self._json_response(401, {"error": "non autenticato"})
            return None
        return session

    def _check_superadmin(self, session: dict) -> bool:
        if not session.get("is_superadmin"):
            self._json_response(403, {"error": "riservato al superadmin"})
            return False
        return True

    def _check_permesso(self, session: dict, permesso: str) -> bool:
        if session.get("is_superadmin"):
            return True
        if permesso not in session.get("permessi", []):
            self._json_response(403, {"error": f"permesso mancante: {permesso}"})
            return False
        return True

    def _check_negozio(self, session: dict, negozio_id: str) -> bool:
        """Verifica che la risorsa appartenga al negozio della sessione."""
        if session.get("is_superadmin"):
            return True
        if negozio_id != session.get("negozio_id"):
            self._json_response(403, {"error": "accesso negato: negozio non corrispondente"})
            return False
        return True

    def _session_negozio(self, session: dict) -> str | None:
        return session.get("negozio_id")

    # ── Routing ──────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0].rstrip("/")
        parts = [p for p in path.split("/") if p]

        if path == "/api/auth/challenge":
            self._handle_challenge()
        elif path == "/api/ping":
            self._handle_ping()
        elif path == "/api/stato":
            self._handle_stato()
        elif path == "/api/clients":
            self._json_response(200, {"clients": get_connected_count()})

        # Negozi
        elif path == "/api/negozi":
            self._handle_get_negozi()

        # Tipi account
        elif path == "/api/tipi-account":
            self._handle_get_tipi()

        # Utenti
        elif path == "/api/utenti":
            self._handle_get_utenti()

        # Dati operativi
        elif path == "/api/consegne":
            self._handle_get_consegne()
        elif path == "/api/giornate":
            self._handle_get_giornate()
        elif path == "/api/squadre":
            self._handle_get_squadre()

        else:
            self._serve_static(path)

    # do_POST, do_PUT, do_DELETE definiti dopo le squadre (unica definizione pulita)

    # ── Auth ─────────────────────────────────────

    def _handle_challenge(self):
        self._json_response(200, {"challenge": new_challenge()})

    def _handle_ping(self):
        token = self.headers.get("X-Session-Token", "")
        if token:
            get_session(token)
        register_client(self.client_address[0])
        count = get_connected_count()
        update_tray_clients(count)
        self._json_response(200, {"ok": True, "clients": count})

    def _handle_stato(self):
        session = self._check_auth()
        if not session:
            return
        if session.get("is_superadmin"):
            self._json_response(403, {"error": "superadmin non ha accesso ai dati operativi"})
            return
        self._json_response(200, get_timestamps())

    def _handle_login(self):
        client_ip = self.client_address[0]
        try:
            body     = self._read_body()
            username = body.get("username", "").strip()
            ch       = body.get("challenge", "")
            response = body.get("response", "")

            if not username or not ch or not response:
                self._json_response(400, {"error": "Dati mancanti"})
                return

            if not consume_challenge(ch):
                log(f"[AUTH] Challenge non valido per '{username}' da {client_ip}", "warning")
                self._json_response(401, {"error": "Challenge non valido o scaduto"})
                return

            user = find_user_by_username(username)
            if not user:
                log(f"[AUTH] Login fallito — utente non trovato: '{username}' da {client_ip}", "warning")
                self._json_response(401, {"error": "Credenziali non valide"})
                return

            stored_h1 = user.get("password_hash", "")
            expected  = sha256_hex(stored_h1 + ch)
            if not secrets.compare_digest(response, expected):
                log(f"[AUTH] Login fallito — password errata per '{username}' da {client_ip}", "warning")
                self._json_response(401, {"error": "Credenziali non valide"})
                return

            # Blocca utenti senza tipo account (escluso superadmin)
            if user.get("id") != "u_superadmin" and not user.get("tipo_account_id"):
                log(f"[AUTH] Login bloccato — account non configurato: '{username}' da {client_ip}", "warning")
                self._json_response(403, {"error": "Account non configurato. Contatta l'amministratore."})
                return

            permessi = _resolve_permessi(user)

            with users_lock:
                data = _read_users_raw()
                for u in data["utenti"]:
                    if u["id"] == user["id"]:
                        u["ultimo_accesso"] = datetime.now().isoformat()
                        break
                _write_users_raw(data)

            token = new_session(user, permessi)
            log(f"[AUTH] '{username}' ha effettuato il login da {client_ip}")

            self._json_response(200, {
                "token":                token,
                "username":             user["username"],
                "user_id":              user["id"],
                "negozio_id":           user.get("negozio_id"),
                "permessi":             permessi,
                "is_superadmin":        user.get("id") == "u_superadmin",
                "must_change_password": user.get("primo_login", False),
            })

        except Exception as e:
            log(f"[AUTH] Errore login: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_logout(self):
        token = self.headers.get("X-Session-Token", "")
        s = get_session(token)
        if s:
            log(f"[AUTH] '{s['username']}' ha effettuato il logout")
        delete_session(token)
        self._json_response(200, {"ok": True})

    def _handle_change_password(self):
        session = self._check_auth()
        if not session:
            return
        client_ip = self.client_address[0]
        try:
            body     = self._read_body()
            ch       = body.get("challenge", "")
            response = body.get("response", "")
            nuova_h1 = body.get("nuova_hash", "")

            if not ch or not response or not nuova_h1:
                self._json_response(400, {"error": "Dati mancanti"})
                return

            if not consume_challenge(ch):
                self._json_response(401, {"error": "Challenge non valido o scaduto"})
                return

            user = find_user_by_id(session["user_id"])
            if not user:
                self._json_response(404, {"error": "Utente non trovato"})
                return

            stored_h1 = user.get("password_hash", "")
            expected  = sha256_hex(stored_h1 + ch)
            if not secrets.compare_digest(response, expected):
                log(f"[AUTH] Cambio password fallito (password errata) per '{session['username']}' da {client_ip}", "warning")
                self._json_response(401, {"error": "Password attuale non corretta"})
                return

            with users_lock:
                data = _read_users_raw()
                for u in data["utenti"]:
                    if u["id"] == session["user_id"]:
                        u["password_hash"] = store_password(nuova_h1)
                        u["primo_login"]   = False
                        break
                _write_users_raw(data)

            delete_session(self.headers.get("X-Session-Token", ""))
            log(f"[AUTH] '{session['username']}' ha cambiato la propria password")
            self._json_response(200, {"ok": True})

        except Exception as e:
            log(f"[AUTH] Errore cambio password: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    # ── Negozi (solo superadmin) ──────────────────

    def _handle_get_negozi(self):
        session = self._check_auth()
        if not session or not self._check_superadmin(session):
            return
        data = read_negozi()
        self._json_response(200, data)

    def _handle_create_negozio(self):
        session = self._check_auth()
        if not session or not self._check_superadmin(session):
            return
        try:
            body = self._read_body()
            nome = body.get("nome", "").strip()
            if not nome:
                self._json_response(400, {"error": "Nome obbligatorio"})
                return
            nuovo = {
                "id":        "n_" + secrets.token_hex(8),
                "nome":      nome,
                "creato_il": datetime.now().isoformat(),
            }
            with negozi_lock:
                data = _read_json(NEGOZI_FILE, {"negozi": []})
                data["negozi"].append(nuovo)
                _write_json(NEGOZI_FILE, data)
            log(f"[NEGOZI] Negozio '{nome}' creato da '{session['username']}'")
            self._json_response(201, {"ok": True, "negozio": nuovo})
        except Exception as e:
            log(f"[NEGOZI] Errore creazione: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_update_negozio(self, nid: str):
        session = self._check_auth()
        if not session or not self._check_superadmin(session):
            return
        try:
            body = self._read_body()
            nome = body.get("nome", "").strip()
            if not nome:
                self._json_response(400, {"error": "Nome obbligatorio"})
                return
            with negozi_lock:
                data = _read_json(NEGOZI_FILE, {"negozi": []})
                target = next((n for n in data["negozi"] if n["id"] == nid), None)
                if not target:
                    self._json_response(404, {"error": "Negozio non trovato"})
                    return
                vecchio = target["nome"]
                target["nome"] = nome
                _write_json(NEGOZI_FILE, data)
            log(f"[NEGOZI] Negozio '{vecchio}' → '{nome}' da '{session['username']}'")
            self._json_response(200, {"ok": True})
        except Exception as e:
            log(f"[NEGOZI] Errore update: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_delete_negozio(self, nid: str):
        session = self._check_auth()
        if not session or not self._check_superadmin(session):
            return
        try:
            # Verifica che nessun utente appartenga a questo negozio
            utenti_data = read_users()
            if any(u.get("negozio_id") == nid for u in utenti_data.get("utenti", [])):
                self._json_response(409, {"error": "Impossibile eliminare: il negozio ha utenti associati"})
                return
            with negozi_lock:
                data = _read_json(NEGOZI_FILE, {"negozi": []})
                target = next((n for n in data["negozi"] if n["id"] == nid), None)
                if not target:
                    self._json_response(404, {"error": "Negozio non trovato"})
                    return
                data["negozi"] = [n for n in data["negozi"] if n["id"] != nid]
                _write_json(NEGOZI_FILE, data)
            log(f"[NEGOZI] Negozio '{target['nome']}' eliminato da '{session['username']}'")
            self._json_response(200, {"ok": True})
        except Exception as e:
            log(f"[NEGOZI] Errore delete: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    # ── Tipi account (solo superadmin) ───────────

    def _handle_get_tipi(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "tipi_account.leggi"):
            return
        self._json_response(200, read_tipi())

    def _handle_create_tipo(self):
        session = self._check_auth()
        if not session or not self._check_superadmin(session):
            return
        try:
            body     = self._read_body()
            nome     = body.get("nome", "").strip()
            permessi = body.get("permessi", [])
            if not nome:
                self._json_response(400, {"error": "Nome obbligatorio"})
                return
            # Filtra permessi non validi
            permessi = [p for p in permessi if p in PERMESSI_VALIDI]
            now = datetime.now().isoformat()
            nuovo = {
                "id":           "ta_" + secrets.token_hex(8),
                "nome":         nome,
                "permessi":     permessi,
                "creato_il":    now,
                "modificato_il": now,
            }
            with tipi_lock:
                data = _read_json(TIPI_FILE, {"tipi_account": []})
                data["tipi_account"].append(nuovo)
                _write_json(TIPI_FILE, data)
            log(f"[TIPI_ACCOUNT] Tipo '{nome}' creato da '{session['username']}'")
            self._json_response(201, {"ok": True, "tipo": nuovo})
        except Exception as e:
            log(f"[TIPI_ACCOUNT] Errore creazione: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_update_tipo(self, tid: str):
        session = self._check_auth()
        if not session or not self._check_superadmin(session):
            return
        try:
            body = self._read_body()
            with tipi_lock:
                data   = _read_json(TIPI_FILE, {"tipi_account": []})
                target = next((t for t in data["tipi_account"] if t["id"] == tid), None)
                if not target:
                    self._json_response(404, {"error": "Tipo account non trovato"})
                    return
                if "nome" in body:
                    nome = body["nome"].strip()
                    if nome:
                        target["nome"] = nome
                if "permessi" in body:
                    target["permessi"] = [p for p in body["permessi"] if p in PERMESSI_VALIDI]
                target["modificato_il"] = datetime.now().isoformat()
                _write_json(TIPI_FILE, data)
            log(f"[TIPI_ACCOUNT] Tipo '{target['nome']}' aggiornato da '{session['username']}'")
            self._json_response(200, {"ok": True})
        except Exception as e:
            log(f"[TIPI_ACCOUNT] Errore update: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_delete_tipo(self, tid: str):
        session = self._check_auth()
        if not session or not self._check_superadmin(session):
            return
        try:
            # Verifica che nessun utente usi questo tipo
            utenti_data = read_users()
            if any(u.get("tipo_account_id") == tid for u in utenti_data.get("utenti", [])):
                self._json_response(409, {"error": "Impossibile eliminare: il tipo account è assegnato a degli utenti"})
                return
            with tipi_lock:
                data   = _read_json(TIPI_FILE, {"tipi_account": []})
                target = next((t for t in data["tipi_account"] if t["id"] == tid), None)
                if not target:
                    self._json_response(404, {"error": "Tipo account non trovato"})
                    return
                data["tipi_account"] = [t for t in data["tipi_account"] if t["id"] != tid]
                _write_json(TIPI_FILE, data)
            log(f"[TIPI_ACCOUNT] Tipo '{target['nome']}' eliminato da '{session['username']}'")
            self._json_response(200, {"ok": True})
        except Exception as e:
            log(f"[TIPI_ACCOUNT] Errore delete: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    # ── Utenti ────────────────────────────────────

    def _handle_get_utenti(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "utenti.leggi"):
            return
        data   = read_users()
        utenti = data.get("utenti", [])
        # Superadmin vede tutti tranne sé stesso; altri vedono solo il proprio negozio
        if session.get("is_superadmin"):
            visibili = [u for u in utenti if u.get("id") != "u_superadmin"]
        else:
            visibili = [u for u in utenti if u.get("negozio_id") == session.get("negozio_id") and u.get("id") != "u_superadmin"]
        safe = [{k: v for k, v in u.items() if k != "password_hash"} for u in visibili]
        self._json_response(200, {"utenti": safe})

    def _handle_create_utente(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "utenti.crea"):
            return
        try:
            body            = self._read_body()
            username        = body.get("username", "").strip()
            password_h1     = body.get("password_hash", "")
            tipo_account_id = body.get("tipo_account_id", "")
            negozio_id      = body.get("negozio_id", "")

            if not username or not password_h1 or not tipo_account_id:
                self._json_response(400, {"error": "username, password_hash e tipo_account_id obbligatori"})
                return

            # Verifica tipo account esiste
            if not find_tipo_by_id(tipo_account_id):
                self._json_response(400, {"error": "Tipo account non valido"})
                return

            # Negozio: superadmin sceglie, altri usano il proprio
            if session.get("is_superadmin"):
                if not negozio_id or not find_negozio_by_id(negozio_id):
                    self._json_response(400, {"error": "negozio_id non valido"})
                    return
            else:
                negozio_id = session.get("negozio_id")

            if find_user_by_username(username):
                self._json_response(409, {"error": f"Username '{username}' già esistente"})
                return

            nuovo = {
                "id":              "u_" + secrets.token_hex(8),
                "username":        username,
                "password_hash":   store_password(password_h1),
                "tipo_account_id": tipo_account_id,
                "negozio_id":      negozio_id,
                "primo_login":     False,
                "creato_da":       session["user_id"],
                "creato_il":       datetime.now().isoformat(),
                "ultimo_accesso":  None,
            }
            with users_lock:
                data = _read_users_raw()
                data.setdefault("utenti", []).append(nuovo)
                _write_users_raw(data)

            negozio = find_negozio_by_id(negozio_id)
            nome_negozio = negozio["nome"] if negozio else negozio_id
            tipo = find_tipo_by_id(tipo_account_id)
            nome_tipo = tipo["nome"] if tipo else tipo_account_id
            log(f"[UTENTI] Utente '{username}' ({nome_tipo}) creato per negozio '{nome_negozio}' da '{session['username']}'")
            self._json_response(201, {"ok": True, "id": nuovo["id"]})

        except Exception as e:
            log(f"[UTENTI] Errore creazione: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_set_password(self, uid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "utenti.modifica"):
            return
        try:
            target = find_user_by_id(uid)
            if not target:
                self._json_response(404, {"error": "Utente non trovato"})
                return
            if target.get("id") == "u_superadmin":
                self._json_response(403, {"error": "Non puoi modificare il superadmin"})
                return
            # Verifica negozio (non superadmin)
            if not session.get("is_superadmin") and target.get("negozio_id") != session.get("negozio_id"):
                self._json_response(403, {"error": "Accesso negato"})
                return

            body     = self._read_body()
            nuova_h1 = body.get("nuova_hash", "")
            if not nuova_h1:
                self._json_response(400, {"error": "nuova_hash mancante"})
                return

            with users_lock:
                data = _read_users_raw()
                for u in data["utenti"]:
                    if u["id"] == uid:
                        u["password_hash"] = store_password(nuova_h1)
                        break
                _write_users_raw(data)

            log(f"[UTENTI] Password di '{target['username']}' cambiata da '{session['username']}'")
            self._json_response(200, {"ok": True})

        except Exception as e:
            log(f"[UTENTI] Errore set password: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_set_tipo_account(self, uid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "utenti.modifica"):
            return
        try:
            target = find_user_by_id(uid)
            if not target:
                self._json_response(404, {"error": "Utente non trovato"})
                return
            if target.get("id") == "u_superadmin":
                self._json_response(403, {"error": "Non puoi modificare il superadmin"})
                return
            if not session.get("is_superadmin") and target.get("negozio_id") != session.get("negozio_id"):
                self._json_response(403, {"error": "Accesso negato"})
                return

            body            = self._read_body()
            tipo_account_id = body.get("tipo_account_id", "")
            if not tipo_account_id or not find_tipo_by_id(tipo_account_id):
                self._json_response(400, {"error": "tipo_account_id non valido"})
                return

            with users_lock:
                data = _read_users_raw()
                for u in data["utenti"]:
                    if u["id"] == uid:
                        u["tipo_account_id"] = tipo_account_id
                        break
                _write_users_raw(data)

            tipo = find_tipo_by_id(tipo_account_id)
            log(f"[UTENTI] Tipo account di '{target['username']}' → '{tipo['nome']}' da '{session['username']}'")
            # Invalida sessioni attive dell'utente (cambio permessi immediato al prossimo login)
            with sessions_lock:
                to_del = [t for t, s in sessions.items() if s["user_id"] == uid]
                for t in to_del:
                    del sessions[t]
            self._json_response(200, {"ok": True})

        except Exception as e:
            log(f"[UTENTI] Errore set tipo: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_delete_utente(self, uid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "utenti.elimina"):
            return
        try:
            target = find_user_by_id(uid)
            if not target:
                self._json_response(404, {"error": "Utente non trovato"})
                return
            if target.get("id") == "u_superadmin":
                self._json_response(403, {"error": "Non puoi eliminare il superadmin"})
                return
            if target.get("id") == session.get("user_id"):
                self._json_response(403, {"error": "Non puoi eliminare il tuo stesso account"})
                return
            if not session.get("is_superadmin") and target.get("negozio_id") != session.get("negozio_id"):
                self._json_response(403, {"error": "Accesso negato"})
                return

            with users_lock:
                data = _read_users_raw()
                data["utenti"] = [u for u in data["utenti"] if u["id"] != uid]
                _write_users_raw(data)

            with sessions_lock:
                to_del = [t for t, s in sessions.items() if s["user_id"] == uid]
                for t in to_del:
                    del sessions[t]

            log(f"[UTENTI] '{target['username']}' eliminato da '{session['username']}'")
            self._json_response(200, {"ok": True})

        except Exception as e:
            log(f"[UTENTI] Errore eliminazione: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    # ── Consegne ──────────────────────────────────

    def _db_risposta(self, negozio_id: str) -> dict:
        """Ritorna il db filtrato per negozio + connectedClients."""
        db = _db_for_negozio(negozio_id)
        db["_connectedClients"] = get_connected_count()
        return db

    def _handle_get_consegne(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "consegne.leggi"):
            return
        nid  = self._session_negozio(session)
        data = read_data()
        consegne = [c for c in data.get("consegne", []) if c.get("negozio_id") == nid]
        self._json_response(200, {"consegne": consegne})

    def _handle_create_consegna(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "consegne.scrivi"):
            return
        try:
            body = self._read_body()
            nid  = self._session_negozio(session)
            nuova = {
                "id":        "c_" + secrets.token_hex(8),
                "negozio_id": nid,
                "versione":  1,
                **{k: v for k, v in body.items() if k not in ("id", "negozio_id", "versione")},
            }
            with file_lock:
                data = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                data.setdefault("consegne", []).append(nuova)
                _write_data_raw(data)
            touch_timestamp("consegne")
            log(f"[DATI] '{session['username']}' — Nuova consegna: {nuova.get('cognome','')} {nuova.get('nome','')}")
            self._json_response(201, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore create consegna: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_update_consegna(self, cid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "consegne.scrivi"):
            return
        try:
            body = self._read_body()
            nid  = self._session_negozio(session)
            with file_lock:
                data   = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                target = next((c for c in data.get("consegne", []) if c.get("id") == cid), None)
                if not target:
                    self._json_response(404, {"error": "Consegna non trovata"})
                    return
                if not self._check_negozio(session, target.get("negozio_id", "")):
                    return
                # Optimistic locking
                client_ver = body.get("versione")
                if client_ver is not None and client_ver != target.get("versione", 1):
                    self._json_response(409, {"error": "Conflitto: la consegna è stata modificata da un altro utente. Ricarica e riprova."})
                    return
                target.update({k: v for k, v in body.items() if k not in ("id", "negozio_id", "versione")})
                target["versione"] = target.get("versione", 1) + 1
                _write_data_raw(data)
            touch_timestamp("consegne")
            log(f"[DATI] '{session['username']}' — Modificata consegna: {target.get('cognome','')} {target.get('nome','')}")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore update consegna: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_delete_consegna(self, cid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "consegne.elimina"):
            return
        try:
            nid = self._session_negozio(session)
            with file_lock:
                data   = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                target = next((c for c in data.get("consegne", []) if c.get("id") == cid), None)
                if not target:
                    self._json_response(404, {"error": "Consegna non trovata"})
                    return
                if not self._check_negozio(session, target.get("negozio_id", "")):
                    return
                data["consegne"] = [c for c in data["consegne"] if c["id"] != cid]
                # Rimuovi dai consegneIds di tutte le giornate
                for g in data.get("giornate", []):
                    g["consegneIds"] = [x for x in g.get("consegneIds", []) if x != cid]
                _write_data_raw(data)
            touch_timestamp("consegne")
            touch_timestamp("giornate")
            log(f"[DATI] '{session['username']}' — Eliminata consegna: {target.get('cognome','')} {target.get('nome','')}")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore delete consegna: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    # ── Giornate ──────────────────────────────────

    def _handle_get_giornate(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "giornate.leggi"):
            return
        nid  = self._session_negozio(session)
        data = read_data()
        giornate = [g for g in data.get("giornate", []) if g.get("negozio_id") == nid]
        self._json_response(200, {"giornate": giornate})

    def _handle_create_giornata(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "giornate.crea"):
            return
        try:
            body  = self._read_body()
            nid   = self._session_negozio(session)
            data_g = body.get("data", "")
            if not data_g:
                self._json_response(400, {"error": "data obbligatoria"})
                return
            nuova = {
                "id":          "g_" + secrets.token_hex(8),
                "negozio_id":  nid,
                "versione":    1,
                "data":        data_g,
                "squadra":     body.get("squadra", ""),
                "consegneIds": [],
            }
            with file_lock:
                data = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                data.setdefault("giornate", []).append(nuova)
                _write_data_raw(data)
            touch_timestamp("giornate")
            log(f"[DATI] '{session['username']}' — Aggiunta giornata {data_g}")
            self._json_response(201, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore create giornata: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_delete_giornata(self, gid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "giornate.elimina"):
            return
        try:
            nid = self._session_negozio(session)
            with file_lock:
                data   = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                target = next((g for g in data.get("giornate", []) if g.get("id") == gid), None)
                if not target:
                    self._json_response(404, {"error": "Giornata non trovata"})
                    return
                if not self._check_negozio(session, target.get("negozio_id", "")):
                    return
                # Rimetti in attesa le consegne assegnate
                for cid in target.get("consegneIds", []):
                    c = next((x for x in data.get("consegne", []) if x["id"] == cid), None)
                    if c and c.get("stato") in ("programmata", "da_confermare"):
                        c["stato"]          = "in_attesa"
                        c["giornoConsegna"] = ""
                data["giornate"] = [g for g in data["giornate"] if g["id"] != gid]
                _write_data_raw(data)
            touch_timestamp("giornate")
            touch_timestamp("consegne")
            log(f"[DATI] '{session['username']}' — Eliminata giornata {target.get('data','')}")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore delete giornata: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_giornata_assegna(self, gid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "giornate.assegna"):
            return
        try:
            body  = self._read_body()
            cids  = body.get("consegna_ids", [])
            nid   = self._session_negozio(session)
            with file_lock:
                data   = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                giornata = next((g for g in data.get("giornate", []) if g.get("id") == gid), None)
                if not giornata:
                    self._json_response(404, {"error": "Giornata non trovata"})
                    return
                if not self._check_negozio(session, giornata.get("negozio_id", "")):
                    return
                for cid in cids:
                    c = next((x for x in data.get("consegne", []) if x["id"] == cid), None)
                    if c and cid not in giornata.get("consegneIds", []):
                        giornata.setdefault("consegneIds", []).append(cid)
                        c["stato"]          = "da_confermare"
                        c["giornoConsegna"] = giornata["data"]
                _write_data_raw(data)
            touch_timestamp("giornate")
            touch_timestamp("consegne")
            log(f"[DATI] '{session['username']}' — Aggiunte {len(cids)} consegne alla giornata {giornata.get('data','')}")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore assegna: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_giornata_rimuovi(self, gid: str, cid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "giornate.assegna"):
            return
        try:
            nid = self._session_negozio(session)
            with file_lock:
                data     = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                giornata = next((g for g in data.get("giornate", []) if g.get("id") == gid), None)
                if not giornata:
                    self._json_response(404, {"error": "Giornata non trovata"})
                    return
                if not self._check_negozio(session, giornata.get("negozio_id", "")):
                    return
                giornata["consegneIds"] = [x for x in giornata.get("consegneIds", []) if x != cid]
                c = next((x for x in data.get("consegne", []) if x["id"] == cid), None)
                if c and c.get("stato") in ("programmata", "da_confermare"):
                    c["stato"]          = "in_attesa"
                    c["giornoConsegna"] = ""
                    c["fasciaOraria"]   = ""
                _write_data_raw(data)
            touch_timestamp("giornate")
            touch_timestamp("consegne")
            log(f"[DATI] '{session['username']}' — Rimossa consegna {cid} dalla giornata {giornata.get('data','')}")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore rimuovi: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_giornata_riordina(self, gid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "giornate.riordina"):
            return
        try:
            body  = self._read_body()
            ids   = body.get("consegna_ids", [])
            nid   = self._session_negozio(session)
            with file_lock:
                data     = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                giornata = next((g for g in data.get("giornate", []) if g.get("id") == gid), None)
                if not giornata:
                    self._json_response(404, {"error": "Giornata non trovata"})
                    return
                if not self._check_negozio(session, giornata.get("negozio_id", "")):
                    return
                giornata["consegneIds"] = ids
                _write_data_raw(data)
            touch_timestamp("giornate")
            log(f"[DATI] '{session['username']}' — Riordinata giornata {giornata.get('data','')}")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore riordina: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_segna_completata(self, gid: str, cid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "giornate.segna_completata"):
            return
        try:
            nid = self._session_negozio(session)
            with file_lock:
                data     = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                giornata = next((g for g in data.get("giornate", []) if g.get("id") == gid), None)
                if not giornata:
                    self._json_response(404, {"error": "Giornata non trovata"})
                    return
                if not self._check_negozio(session, giornata.get("negozio_id", "")):
                    return
                c = next((x for x in data.get("consegne", []) if x["id"] == cid), None)
                if not c:
                    self._json_response(404, {"error": "Consegna non trovata"})
                    return
                c["stato"] = "completata"
                _write_data_raw(data)
            touch_timestamp("consegne")
            log(f"[DATI] '{session['username']}' — Consegna completata: {c.get('cognome','')} {c.get('nome','')}")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore segna completata: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    # ── Squadre ───────────────────────────────────

    def _handle_get_squadre(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "squadre.leggi"):
            return
        nid  = self._session_negozio(session)
        data = read_data()
        squadre = [s for s in data.get("squadre", []) if s.get("negozio_id") == nid]
        self._json_response(200, {"squadre": squadre})

    def do_POST_squadra(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "squadre.gestisci"):
            return
        try:
            body = self._read_body()
            nome = body.get("nome", "").strip()
            if not nome:
                self._json_response(400, {"error": "Nome obbligatorio"})
                return
            nid = self._session_negozio(session)
            with file_lock:
                data = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                if any(s["nome"].lower() == nome.lower() and s.get("negozio_id") == nid for s in data.get("squadre", [])):
                    self._json_response(409, {"error": "Squadra già esistente"})
                    return
                color_idx = len([s for s in data.get("squadre", []) if s.get("negozio_id") == nid]) % 8
                nuova = {"id": "sq_" + secrets.token_hex(8), "negozio_id": nid, "versione": 1, "nome": nome, "colorIdx": color_idx}
                data.setdefault("squadre", []).append(nuova)
                _write_data_raw(data)
            touch_timestamp("squadre")
            log(f"[DATI] '{session['username']}' — Aggiunta squadra '{nome}'")
            self._json_response(201, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore create squadra: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def do_PUT_squadra(self, sid):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "squadre.gestisci"):
            return
        try:
            body = self._read_body()
            nid  = self._session_negozio(session)
            with file_lock:
                data   = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                target = next((s for s in data.get("squadre", []) if s.get("id") == sid), None)
                if not target:
                    self._json_response(404, {"error": "Squadra non trovata"})
                    return
                if not self._check_negozio(session, target.get("negozio_id", "")):
                    return
                vecchio_nome = target["nome"]
                if "nome" in body:
                    nuovo_nome = body["nome"].strip()
                    if nuovo_nome and nuovo_nome != vecchio_nome:
                        # Aggiorna riferimenti nelle giornate
                        for g in data.get("giornate", []):
                            if g.get("squadra") == vecchio_nome:
                                g["squadra"] = nuovo_nome
                        target["nome"] = nuovo_nome
                if "colorIdx" in body:
                    target["colorIdx"] = body["colorIdx"]
                target["versione"] = target.get("versione", 1) + 1
                _write_data_raw(data)
            touch_timestamp("squadre")
            touch_timestamp("giornate")
            log(f"[DATI] '{session['username']}' — Aggiornata squadra '{vecchio_nome}'")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore update squadra: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def do_DELETE_squadra(self, sid):
        session = self._check_auth()
        if not session:
            return
        if not self._check_permesso(session, "squadre.gestisci"):
            return
        try:
            nid = self._session_negozio(session)
            with file_lock:
                data   = _read_json(DATA_FILE, {"consegne": [], "giornate": [], "squadre": []})
                target = next((s for s in data.get("squadre", []) if s.get("id") == sid), None)
                if not target:
                    self._json_response(404, {"error": "Squadra non trovata"})
                    return
                if not self._check_negozio(session, target.get("negozio_id", "")):
                    return
                # Rimuovi riferimento dalle giornate
                for g in data.get("giornate", []):
                    if g.get("squadra") == target["nome"]:
                        g["squadra"] = ""
                data["squadre"] = [s for s in data["squadre"] if s["id"] != sid]
                _write_data_raw(data)
            touch_timestamp("squadre")
            touch_timestamp("giornate")
            log(f"[DATI] '{session['username']}' — Eliminata squadra '{target['nome']}'")
            self._json_response(200, self._db_risposta(nid))
        except Exception as e:
            log(f"[DATI] Errore delete squadra: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    # ── Routing unificato ────────────────────────────

    def do_POST(self):
        path  = self.path.split("?")[0].rstrip("/")
        parts = [p for p in path.split("/") if p]

        if path == "/api/auth/login":             self._handle_login();              return
        if path == "/api/auth/logout":            self._handle_logout();             return
        if path == "/api/auth/change-password":   self._handle_change_password();    return
        if path == "/api/negozi":                 self._handle_create_negozio();     return
        if path == "/api/tipi-account":           self._handle_create_tipo();        return
        if path == "/api/utenti":                 self._handle_create_utente();      return
        if path == "/api/consegne":               self._handle_create_consegna();    return
        if path == "/api/giornate":               self._handle_create_giornata();    return
        if path == "/api/squadre":                self.do_POST_squadra();            return
        if len(parts)==4 and parts[1]=="giornate" and parts[3]=="assegna":
            self._handle_giornata_assegna(parts[2]); return
        self._json_response(404, {"error": "not found"})

    def do_PUT(self):
        path  = self.path.split("?")[0].rstrip("/")
        parts = [p for p in path.split("/") if p]

        if len(parts)==3 and parts[1]=="negozi":     self._handle_update_negozio(parts[2]);   return
        if len(parts)==3 and parts[1]=="tipi-account": self._handle_update_tipo(parts[2]);    return
        if len(parts)==3 and parts[1]=="consegne":   self._handle_update_consegna(parts[2]);  return
        if len(parts)==3 and parts[1]=="squadre":    self.do_PUT_squadra(parts[2]);           return
        if len(parts)==4 and parts[1]=="utenti" and parts[3]=="password":
            self._handle_set_password(parts[2]); return
        if len(parts)==4 and parts[1]=="utenti" and parts[3]=="tipo":
            self._handle_set_tipo_account(parts[2]); return
        if len(parts)==4 and parts[1]=="giornate" and parts[3]=="riordina":
            self._handle_giornata_riordina(parts[2]); return
        if len(parts)==6 and parts[1]=="giornate" and parts[3]=="consegne" and parts[5]=="completa":
            self._handle_segna_completata(parts[2], parts[4]); return
        self._json_response(404, {"error": "not found"})

    def do_DELETE(self):
        path  = self.path.split("?")[0].rstrip("/")
        parts = [p for p in path.split("/") if p]

        if len(parts)==3 and parts[1]=="negozi":      self._handle_delete_negozio(parts[2]);  return
        if len(parts)==3 and parts[1]=="tipi-account": self._handle_delete_tipo(parts[2]);    return
        if len(parts)==3 and parts[1]=="utenti":      self._handle_delete_utente(parts[2]);   return
        if len(parts)==3 and parts[1]=="consegne":    self._handle_delete_consegna(parts[2]); return
        if len(parts)==3 and parts[1]=="giornate":    self._handle_delete_giornata(parts[2]); return
        if len(parts)==3 and parts[1]=="squadre":     self.do_DELETE_squadra(parts[2]);       return
        if len(parts)==5 and parts[1]=="giornate" and parts[3]=="assegna":
            self._handle_giornata_rimuovi(parts[2], parts[4]); return
        self._json_response(404, {"error": "not found"})

    # ── File statici ──────────────────────────────

    def _serve_static(self, url_path):
        if url_path in ("", "/", "."):
            self.send_response(302)
            self.send_header("Location", "/index.html")
            self.end_headers()
            return
        safe_rel = os.path.normpath(url_path.lstrip("/"))
        if safe_rel.startswith("..") or safe_rel == ".":
            self.send_response(403)
            self.end_headers()
            return
        path = os.path.join(BASE_DIR, safe_rel)
        if not os.path.isfile(path):
            self.send_response(404)
            self.end_headers()
            return
        ext  = os.path.splitext(path)[1].lower()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".js":   "application/javascript; charset=utf-8",
            ".css":  "text/css; charset=utf-8",
        }.get(ext, "application/octet-stream")
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


# ─── TRAY ICON ───────────────────────────────────────────────────────────────

tray_icon = None

def update_tray_clients(count):
    if tray_icon is None:
        return
    try:
        tray_icon.title = f"Gestione Consegne — {count} utent{'e' if count == 1 else 'i'} connesso/i"
    except Exception:
        pass

def update_tray_error(reason):
    if tray_icon is None:
        return
    try:
        tray_icon.title = f"Gestione Consegne — ERRORE: {reason}"
    except Exception:
        pass

def notify_crash(reason):
    try:
        if tray_icon:
            tray_icon.notify(
                title="Gestione Consegne — Server arrestato",
                message=f"Il server si e' arrestato:\n{reason}\n\nRiavvia avvia.bat per riprendere."
            )
    except Exception:
        pass
    try:
        import subprocess
        msg = (
            f"Il server Gestione Consegne si e' arrestato.\n\n"
            f"Motivo: {reason}\n\n"
            f"Riavvia avvia.bat per riprendere."
        )
        ps_cmd = (
            f'Add-Type -AssemblyName System.Windows.Forms; '
            f'[System.Windows.Forms.MessageBox]::Show('
            f'"{msg}", '
            f'"Gestione Consegne - Server arrestato", '
            f'[System.Windows.Forms.MessageBoxButtons]::OK, '
            f'[System.Windows.Forms.MessageBoxIcon]::Error)'
        )
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Normal", "-Command", ps_cmd])
        time.sleep(0.5)
    except Exception as e:
        log(f"Impossibile mostrare popup crash: {e}", "warning")

def open_browser_action():
    webbrowser.open(f"http://localhost:{PORT}/index.html")

def stop_server_action():
    log("Server fermato dall'utente tramite tray.")
    remove_lock()
    os._exit(0)

def run_tray():
    global tray_icon
    try:
        import pystray
        from PIL import Image, ImageDraw
        img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill=(79, 138, 255, 255))
        draw.rectangle([28, 18, 36, 40], fill=(255, 255, 255, 255))
        draw.ellipse([27, 44, 37, 54], fill=(255, 255, 255, 255))
        menu = pystray.Menu(
            pystray.MenuItem("Apri gestionale", lambda: open_browser_action()),
            pystray.MenuItem("Ferma server",    lambda: stop_server_action()),
        )
        tray_icon = pystray.Icon("gestione_consegne", img, "Gestione Consegne — server attivo", menu)
        tray_icon.run()
    except ImportError:
        log("Tray non disponibile — server gira in background.", "warning")
        while True:
            time.sleep(60)
    except Exception as e:
        log(f"Tray error: {e}", "warning")

# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    setup_logging()
    rotate_log()
    log("=" * 50)
    log("Avvio Gestione Consegne server v2...")

    init_users()
    init_tipi()
    init_negozi()
    write_lock()

    threading.Thread(target=cleanup_sessions,   daemon=True).start()
    threading.Thread(target=cleanup_challenges, daemon=True).start()
    threading.Thread(target=run_tray,           daemon=True).start()

    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log("Server fermato.")
        remove_lock()
        server.server_close()
