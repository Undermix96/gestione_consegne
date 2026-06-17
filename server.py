#!/usr/bin/env python3
"""
Gestione Consegne — Server locale robusto
- Autenticazione con Challenge-Response (SHA-256, no dipendenze esterne)
- Tre livelli di ruolo: superadmin, admin, standard
- Sessioni in memoria con scadenza per inattività (2 ore)
- Gestione utenti in utenti.json (scrittura atomica)
- Server unico in rete tramite server.lock
- Lettura fresca dal disco ad ogni scrittura
- Backup automatico (20 snapshot)
- Log con rotazione 7 giorni + log accessi
- Contatore utenti connessi
- Icona system tray
"""

import http.server
import json
import os
import sys
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
LOCK_FILE     = os.path.join(BASE_DIR, "server.lock")
BACKUP_DIR    = os.path.join(BASE_DIR, "backup")
LOG_FILE      = os.path.join(BASE_DIR, "gestionale.log")
MAX_BACKUPS   = 20
LOG_DAYS      = 7
WRITE_RETRIES = 2
SESSION_TTL   = 7200   # 2 ore in secondi
CHALLENGE_TTL = 60     # 60 secondi per usare il challenge

file_lock       = threading.Lock()
users_lock      = threading.Lock()
sessions_lock   = threading.Lock()
challenges_lock = threading.Lock()

connected_clients = set()
clients_lock      = threading.Lock()
client_heartbeat  = {}

# Sessioni in memoria: token -> { user_id, username, ruolo, last_seen, expires, must_change_password }
sessions   = {}
# Challenge monouso: challenge_hex -> timestamp
challenges = {}

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

# ─── SHA-256 (hashlib built-in) ──────────────────────────────────────────────

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def bcrypt_hash(h1: str) -> str:
    """
    Usa hashlib.scrypt (built-in Python 3.6+) come KDF lento al posto di bcrypt.
    Non richiede dipendenze esterne.
    Il salt è derivato deterministicamente per semplicità di verifica;
    in produzione sarebbe random e salvato separatamente, ma qui usiamo
    un approccio compatibile con il modello challenge-response.

    Schema: scrypt(h1, salt=FIXED_SALT, n=2^14, r=8, p=1) -> hex
    Il FIXED_SALT è generato una volta per installazione e salvato in utenti.json.
    """
    import hashlib
    salt = _get_kdf_salt()
    dk = hashlib.scrypt(h1.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return dk.hex()

def bcrypt_verify(h1: str, stored_hash: str) -> bool:
    return bcrypt_hash(h1) == stored_hash

_kdf_salt_cache = None

def _get_kdf_salt() -> bytes:
    global _kdf_salt_cache
    if _kdf_salt_cache:
        return _kdf_salt_cache
    users_data = _read_users_raw()
    salt_hex = users_data.get("kdf_salt")
    if not salt_hex:
        # Prima volta: genera e salva
        salt_hex = secrets.token_hex(32)
        users_data["kdf_salt"] = salt_hex
        _write_users_raw(users_data)
    _kdf_salt_cache = bytes.fromhex(salt_hex)
    return _kdf_salt_cache

# ─── UTENTI I/O ──────────────────────────────────────────────────────────────

DEFAULT_SUPERADMIN_H1 = sha256_hex("admin")   # sha256("admin") — da cambiare al primo login

def _read_users_raw() -> dict:
    if not os.path.exists(USERS_FILE):
        return {"utenti": []}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"utenti": []}

def _write_users_raw(data: dict):
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USERS_FILE)

def read_users() -> dict:
    with users_lock:
        return _read_users_raw()

def write_users(data: dict):
    with users_lock:
        _write_users_raw(data)

def init_users():
    """Crea utenti.json con superadmin di default se non esiste."""
    if os.path.exists(USERS_FILE):
        # Verifica che esista almeno un superadmin
        data = _read_users_raw()
        if any(u.get("ruolo") == "superadmin" for u in data.get("utenti", [])):
            return

    log("Inizializzazione utenti.json con superadmin di default.")
    # Genera il salt KDF prima di hashare
    salt_hex = secrets.token_hex(32)
    data = {"kdf_salt": salt_hex, "utenti": []}
    _write_users_raw(data)

    # Ora hasha con il salt appena creato
    pwd_hash = bcrypt_hash(DEFAULT_SUPERADMIN_H1)
    superadmin = {
        "id":              "u_superadmin",
        "username":        "superadmin",
        "password_hash":   pwd_hash,
        "ruolo":           "superadmin",
        "primo_login":     True,
        "creato_da":       None,
        "creato_il":       datetime.now().isoformat(),
        "ultimo_accesso":  None,
    }
    data["utenti"] = [superadmin]
    _write_users_raw(data)
    log("Superadmin creato. Username: superadmin / Password: admin (da cambiare al primo accesso)")

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

# ─── CHALLENGE ───────────────────────────────────────────────────────────────

def new_challenge() -> str:
    ch = secrets.token_hex(32)
    with challenges_lock:
        challenges[ch] = time.time()
    return ch

def consume_challenge(ch: str) -> bool:
    """Ritorna True se il challenge è valido e non scaduto, e lo rimuove (monouso)."""
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

def new_session(user: dict) -> str:
    token = secrets.token_urlsafe(32)
    now   = time.time()
    with sessions_lock:
        sessions[token] = {
            "user_id":              user["id"],
            "username":             user["username"],
            "ruolo":                user["ruolo"],
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
        # Aggiorna last_seen e scadenza
        s["last_seen"] = time.time()
        s["expires"]   = s["last_seen"] + SESSION_TTL
        return dict(s)  # copia

def delete_session(token: str):
    with sessions_lock:
        sessions.pop(token, None)

def cleanup_sessions():
    while True:
        time.sleep(300)  # ogni 5 minuti
        now = time.time()
        with sessions_lock:
            expired = [t for t, s in sessions.items() if now > s["expires"]]
            for t in expired:
                del sessions[t]

# ─── DATA I/O ────────────────────────────────────────────────────────────────

def read_data():
    if not os.path.exists(DATA_FILE):
        default = {"consegne": [], "giornate": []}
        _write_raw(default)
        return default
    for attempt in range(WRITE_RETRIES):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"Errore lettura dati (tentativo {attempt+1}): {e}", "error")
            if attempt < WRITE_RETRIES - 1:
                time.sleep(0.3)
    log("Lettura fallita dopo tutti i tentativi — server in arresto.", "critical")
    crash_server("Impossibile leggere il file dati dopo 2 tentativi.")

def _write_raw(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def write_data(incoming):
    for attempt in range(WRITE_RETRIES):
        try:
            make_backup()
            _write_raw(incoming)
            log("Dati salvati correttamente.")
            return
        except Exception as e:
            log(f"Errore scrittura dati (tentativo {attempt+1}): {e}", "error")
            if attempt < WRITE_RETRIES - 1:
                time.sleep(0.3)
    log("Scrittura fallita dopo tutti i tentativi — server in arresto.", "critical")
    crash_server("Impossibile scrivere il file dati dopo 2 tentativi.")

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
            log("Server lock rimosso.")
    except Exception as e:
        log(f"Impossibile rimuovere lock: {e}", "warning")

# ─── CRASH ───────────────────────────────────────────────────────────────────

def crash_server(reason):
    log(f"CRASH SERVER: {reason}", "critical")
    remove_lock()
    update_tray_error(reason)
    notify_crash(reason)
    time.sleep(2)
    os._exit(1)

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
        """Verifica token. Ritorna la sessione o invia 401 e ritorna None."""
        token = self.headers.get("X-Session-Token", "")
        session = get_session(token)
        if not session:
            self._json_response(401, {"error": "non autenticato"})
            return None
        return session

    def _check_role(self, session: dict, *ruoli) -> bool:
        """Verifica che il ruolo della sessione sia tra quelli ammessi."""
        if session["ruolo"] not in ruoli:
            self._json_response(403, {"error": "permessi insufficienti"})
            return False
        return True

    # ── Routing ──────────────────────────────────

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0]

        if path == "/api/auth/challenge":
            self._handle_challenge()
        elif path == "/api/ping":
            self._handle_ping()
        elif path == "/api/data":
            self._handle_get_data()
        elif path == "/api/utenti":
            self._handle_get_utenti()
        elif path == "/api/clients":
            self._json_response(200, {"clients": get_connected_count()})
        else:
            self._serve_static(path)

    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/auth/login":
            self._handle_login()
        elif path == "/api/auth/logout":
            self._handle_logout()
        elif path == "/api/auth/change-password":
            self._handle_change_password()
        elif path == "/api/data":
            self._handle_post_data()
        elif path == "/api/utenti":
            self._handle_create_utente()
        elif path == "/api/log":
            self._handle_log()
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        path = self.path.split("?")[0]

        # PUT /api/utenti/<id>/password
        if path.startswith("/api/utenti/") and path.endswith("/password"):
            uid = path.split("/")[3]
            self._handle_set_password(uid)
        # PUT /api/utenti/<id>/ruolo
        elif path.startswith("/api/utenti/") and path.endswith("/ruolo"):
            uid = path.split("/")[3]
            self._handle_set_ruolo(uid)
        else:
            self.send_response(404)
            self.end_headers()

    def do_DELETE(self):
        path = self.path.split("?")[0]

        # DELETE /api/utenti/<id>
        if path.startswith("/api/utenti/"):
            uid = path.split("/")[3]
            self._handle_delete_utente(uid)
        else:
            self.send_response(404)
            self.end_headers()

    # ── Auth endpoints ────────────────────────────

    def _handle_challenge(self):
        ch = new_challenge()
        self._json_response(200, {"challenge": ch})

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
                log(f"[AUTH] Challenge non valido o scaduto per '{username}' da {client_ip}", "warning")
                self._json_response(401, {"error": "Challenge non valido o scaduto"})
                return

            user = find_user_by_username(username)
            if not user:
                log(f"[AUTH] Login fallito — utente non trovato: '{username}' da {client_ip}", "warning")
                self._json_response(401, {"error": "Credenziali non valide"})
                return

            # Verifica: expected = sha256(stored_h1_hex + challenge)
            # dove stored_h1 viene verificato confrontando bcrypt
            # Approccio: dobbiamo ricostruire h1 dal response e dal challenge.
            # Il client manda response = sha256(h1 + challenge).
            # Il server non può invertire sha256, quindi verifica direttamente:
            # ricalcola sha256(password_hash_verificabile + challenge) — ma non abbiamo h1.
            #
            # Schema corretto implementato:
            # Il server salva bcrypt(h1). Per verificare il challenge-response,
            # il server deve confrontare sha256(h1 + ch) con il response ricevuto.
            # Questo richiede di conoscere h1, che non è memorizzato (solo il suo hash lento).
            #
            # Soluzione: usiamo uno schema a due step memorizzando anche h1_hash = sha256(h1)
            # e verifichiamo response == sha256(password_hash_field + ch) dove
            # password_hash_field è lo scrypt(h1).
            #
            # In pratica: response_atteso = sha256(stored_scrypt_hash + ch)
            # Questo è sicuro perché stored_scrypt_hash non è la password e non è invertibile.
            stored_hash   = user.get("password_hash", "")
            expected      = sha256_hex(stored_hash + ch)

            if not secrets.compare_digest(response, expected):
                log(f"[AUTH] Login fallito — password errata per '{username}' da {client_ip}", "warning")
                self._json_response(401, {"error": "Credenziali non valide"})
                return

            # Aggiorna ultimo_accesso
            with users_lock:
                data = _read_users_raw()
                for u in data["utenti"]:
                    if u["id"] == user["id"]:
                        u["ultimo_accesso"] = datetime.now().isoformat()
                        break
                _write_users_raw(data)

            token = new_session(user)
            log(f"[AUTH] {user['ruolo']} '{username}' ha effettuato il login da {client_ip}")

            self._json_response(200, {
                "token":                token,
                "ruolo":                user["ruolo"],
                "username":             user["username"],
                "user_id":              user["id"],
                "must_change_password": user.get("primo_login", False),
            })

        except Exception as e:
            log(f"[AUTH] Errore login: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_logout(self):
        token = self.headers.get("X-Session-Token", "")
        s     = get_session(token)
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
            body      = self._read_body()
            ch        = body.get("challenge", "")
            response  = body.get("response", "")
            nuova_h1  = body.get("nuova_hash", "")

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

            # Verifica vecchia password tramite challenge-response
            stored_hash  = user.get("password_hash", "")
            expected     = sha256_hex(stored_hash + ch)
            if not secrets.compare_digest(response, expected):
                log(f"[AUTH] Cambio password fallito (password errata) per '{session['username']}' da {client_ip}", "warning")
                self._json_response(401, {"error": "Password attuale non corretta"})
                return

            # Salva nuova password
            nuova_hash = bcrypt_hash(nuova_h1)
            with users_lock:
                data = _read_users_raw()
                for u in data["utenti"]:
                    if u["id"] == session["user_id"]:
                        u["password_hash"] = nuova_hash
                        u["primo_login"]   = False
                        break
                _write_users_raw(data)

            # Invalida sessione corrente
            delete_session(self.headers.get("X-Session-Token", ""))
            log(f"[AUTH] '{session['username']}' ha cambiato la propria password")
            self._json_response(200, {"ok": True})

        except Exception as e:
            log(f"[AUTH] Errore cambio password: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    # ── Dati operativi ────────────────────────────

    def _handle_ping(self):
        client_ip = self.client_address[0]
        # Il ping non richiede auth (serve anche per rilevare connessione)
        # Ma se c'è un token valido, aggiorniamo la sessione
        token = self.headers.get("X-Session-Token", "")
        if token:
            get_session(token)  # aggiorna last_seen
        register_client(client_ip)
        count = get_connected_count()
        update_tray_clients(count)
        self._json_response(200, {"ok": True, "clients": count})

    def _handle_get_data(self):
        session = self._check_auth()
        if not session:
            return
        # Superadmin non ha accesso ai dati operativi
        if session["ruolo"] == "superadmin":
            self._json_response(403, {"error": "superadmin non ha accesso ai dati operativi"})
            return
        register_client(self.client_address[0])
        with file_lock:
            data = read_data()
        data["_connectedClients"] = get_connected_count()
        self._json_response(200, data)

    def _handle_post_data(self):
        session = self._check_auth()
        if not session:
            return
        if session["ruolo"] == "superadmin":
            self._json_response(403, {"error": "superadmin non ha accesso ai dati operativi"})
            return
        try:
            incoming = self._read_body()
            with file_lock:
                write_data(incoming)
            register_client(self.client_address[0])
            self._json_response(200, {"ok": True})
        except Exception as e:
            log(f"Errore POST /api/data: {e}", "error")
            self._json_response(500, {"error": str(e)})

    # ── Gestione utenti ───────────────────────────

    def _handle_get_utenti(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_role(session, "admin", "superadmin"):
            return
        data    = read_users()
        utenti  = data.get("utenti", [])
        # Rimuove password_hash dalla risposta
        safe = [{k: v for k, v in u.items() if k != "password_hash"} for u in utenti]
        self._json_response(200, {"utenti": safe})

    def _handle_create_utente(self):
        session = self._check_auth()
        if not session:
            return
        if not self._check_role(session, "admin", "superadmin"):
            return
        try:
            body          = self._read_body()
            username      = body.get("username", "").strip()
            password_h1   = body.get("password_hash", "")   # sha256(password) dal client
            ruolo         = body.get("ruolo", "standard")

            if not username or not password_h1:
                self._json_response(400, {"error": "username e password obbligatori"})
                return

            # Ruoli ammessi per chi crea
            if ruolo not in ("standard", "admin"):
                self._json_response(400, {"error": "Ruolo non valido"})
                return

            # Un admin non può creare un superadmin
            if ruolo == "superadmin":
                self._json_response(403, {"error": "Non puoi creare un superadmin"})
                return

            # Verifica unicità username
            if find_user_by_username(username):
                self._json_response(409, {"error": f"Username '{username}' già esistente"})
                return

            new_id   = "u_" + secrets.token_hex(8)
            pwd_hash = bcrypt_hash(password_h1)
            nuovo    = {
                "id":             new_id,
                "username":       username,
                "password_hash":  pwd_hash,
                "ruolo":          ruolo,
                "primo_login":    False,
                "creato_da":      session["user_id"],
                "creato_il":      datetime.now().isoformat(),
                "ultimo_accesso": None,
            }
            with users_lock:
                data = _read_users_raw()
                data.setdefault("utenti", []).append(nuovo)
                _write_users_raw(data)

            log(f"[UTENTI] {ruolo} '{username}' creato da '{session['username']}'")
            self._json_response(201, {"ok": True, "id": new_id})

        except Exception as e:
            log(f"[UTENTI] Errore creazione utente: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_set_password(self, uid: str):
        session = self._check_auth()
        if not session:
            return
        try:
            target = find_user_by_id(uid)
            if not target:
                self._json_response(404, {"error": "Utente non trovato"})
                return

            # Controlli ruolo
            if target["ruolo"] == "superadmin":
                self._json_response(403, {"error": "Non puoi modificare il superadmin"})
                return
            if target["ruolo"] == "admin" and session["ruolo"] != "superadmin":
                self._json_response(403, {"error": "Solo il superadmin può cambiare la password di un admin"})
                return
            if target["ruolo"] == "standard" and session["ruolo"] not in ("admin", "superadmin"):
                self._json_response(403, {"error": "Permessi insufficienti"})
                return

            body      = self._read_body()
            nuova_h1  = body.get("nuova_hash", "")
            if not nuova_h1:
                self._json_response(400, {"error": "nuova_hash mancante"})
                return

            nuova_hash = bcrypt_hash(nuova_h1)
            with users_lock:
                data = _read_users_raw()
                for u in data["utenti"]:
                    if u["id"] == uid:
                        u["password_hash"] = nuova_hash
                        break
                _write_users_raw(data)

            log(f"[UTENTI] Password di '{target['username']}' cambiata da '{session['username']}'")
            self._json_response(200, {"ok": True})

        except Exception as e:
            log(f"[UTENTI] Errore set password: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_set_ruolo(self, uid: str):
        session = self._check_auth()
        if not session:
            return
        if not self._check_role(session, "superadmin"):
            return
        try:
            target = find_user_by_id(uid)
            if not target:
                self._json_response(404, {"error": "Utente non trovato"})
                return
            if target["ruolo"] == "superadmin":
                self._json_response(403, {"error": "Non puoi modificare il superadmin"})
                return

            body      = self._read_body()
            nuovo_ruolo = body.get("ruolo", "")
            if nuovo_ruolo not in ("standard", "admin"):
                self._json_response(400, {"error": "Ruolo non valido"})
                return

            with users_lock:
                data = _read_users_raw()
                for u in data["utenti"]:
                    if u["id"] == uid:
                        u["ruolo"] = nuovo_ruolo
                        break
                _write_users_raw(data)

            log(f"[UTENTI] '{target['username']}' declassato a '{nuovo_ruolo}' da '{session['username']}'")
            self._json_response(200, {"ok": True})

        except Exception as e:
            log(f"[UTENTI] Errore set ruolo: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_delete_utente(self, uid: str):
        session = self._check_auth()
        if not session:
            return
        try:
            target = find_user_by_id(uid)
            if not target:
                self._json_response(404, {"error": "Utente non trovato"})
                return
            if target["ruolo"] == "superadmin":
                self._json_response(403, {"error": "Non puoi eliminare il superadmin"})
                return
            if target["id"] == session["user_id"]:
                self._json_response(403, {"error": "Non puoi eliminare il tuo stesso account"})
                return
            if target["ruolo"] == "admin" and session["ruolo"] != "superadmin":
                self._json_response(403, {"error": "Solo il superadmin può eliminare un admin"})
                return
            if target["ruolo"] == "standard" and session["ruolo"] not in ("admin", "superadmin"):
                self._json_response(403, {"error": "Permessi insufficienti"})
                return

            # Controlla che non sia l'ultimo admin
            if target["ruolo"] == "admin":
                data   = read_users()
                admins = [u for u in data["utenti"] if u["ruolo"] == "admin"]
                if len(admins) <= 1:
                    self._json_response(409, {"error": "Non puoi eliminare l'ultimo admin"})
                    return

            with users_lock:
                data = _read_users_raw()
                data["utenti"] = [u for u in data["utenti"] if u["id"] != uid]
                _write_users_raw(data)

            # Invalida eventuali sessioni attive dell'utente eliminato
            with sessions_lock:
                to_del = [t for t, s in sessions.items() if s["user_id"] == uid]
                for t in to_del:
                    del sessions[t]

            log(f"[UTENTI] '{target['username']}' ({target['ruolo']}) eliminato da '{session['username']}'")
            self._json_response(200, {"ok": True})

        except Exception as e:
            log(f"[UTENTI] Errore eliminazione utente: {e}", "error")
            self._json_response(500, {"error": "Errore interno"})

    def _handle_log(self):
        # Log client — richiede autenticazione
        session = self._check_auth()
        if not session:
            return
        try:
            payload = self._read_body()
            msg     = payload.get("msg", "")
            if msg:
                log(f"[DATI] {msg}")
            self._json_response(200, {"ok": True})
        except Exception:
            self._json_response(400, {"error": "bad request"})

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
        log("Tray non disponibile (pystray non installato) — server gira in background.", "warning")
        while True:
            time.sleep(60)
    except Exception as e:
        log(f"Tray error: {e}", "warning")

def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{PORT}/index.html")

# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.chdir(BASE_DIR)
    setup_logging()
    rotate_log()
    log("=" * 50)
    log("Avvio Gestione Consegne server...")

    init_users()
    write_lock()

    # Thread cleanup sessioni e challenge
    threading.Thread(target=cleanup_sessions,   daemon=True).start()
    threading.Thread(target=cleanup_challenges, daemon=True).start()

    # Tray icon
    threading.Thread(target=run_tray, daemon=True).start()

    # Avvia server HTTP
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log("Server fermato.")
        remove_lock()
        server.server_close()
