#!/usr/bin/env python3
"""
Gestione Consegne — Server Docker
- Log su stdout (catturati da Docker)
- Backend dati configurabile via DB_BACKEND (json | mysql | postgres)
- Ping HTTP per rilevamento disconnessione e healthcheck
- Contatore utenti connessi
"""

import http.server
import json
import os
import sys
import threading
import time
import logging

PORT      = int(os.environ.get("PORT", 8080))
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))

file_lock = threading.Lock()
connected_clients = set()   # set di indirizzi IP attivi
clients_lock = threading.Lock()
client_heartbeat = {}       # ip -> ultimo timestamp heartbeat

# ─── LOGGING ────────────────────────────────────────────────────────────────

def setup_logging():
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def log(msg, level="info"):
    getattr(logging, level)(msg)

# ─── DATA I/O ────────────────────────────────────────────────────────────────
# Delegato a storage.py — read_data/write_data/make_backup importati da lì.

from storage import init_storage, read_data, write_data, make_backup

# ─── CRASH ───────────────────────────────────────────────────────────────────

def crash_server(reason):
    log(f"CRASH SERVER: {reason}", "critical")
    time.sleep(2)
    os._exit(1)

# ─── CONNECTED CLIENTS ───────────────────────────────────────────────────────

def register_client(ip):
    with clients_lock:
        client_heartbeat[ip] = time.time()
        connected_clients.add(ip)

def get_connected_count():
    """Conta i client con heartbeat negli ultimi 15 secondi."""
    now = time.time()
    with clients_lock:
        active = {ip for ip, ts in client_heartbeat.items() if now - ts < 15}
        connected_clients.intersection_update(active)
        return len(active)

# ─── HTTP HANDLER ─────────────────────────────────────────────────────────────

class Handler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # silenzia log HTTP standard

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        client_ip = self.client_address[0]

        if self.path == "/api/ping":
            register_client(client_ip)
            count = get_connected_count()
            self._json_response(200, {"ok": True, "clients": count})

        elif self.path == "/api/data":
            register_client(client_ip)
            with file_lock:
                data = read_data()
            data["_connectedClients"] = get_connected_count()
            self._json_response(200, data)

        elif self.path == "/api/clients":
            self._json_response(200, {"clients": get_connected_count()})

        else:
            # Serve file statici direttamente da BASE_DIR (mai da cwd)
            # Rimuove query string e frammenti, poi normalizza il path
            url_path = self.path.split('?')[0].split('#')[0]
            # Redirect root -> index.html (i client LAN aprono spesso solo l'IP)
            if url_path in ('', '/', '.'):
                self.send_response(302)
                self.send_header('Location', '/index.html')
                self.end_headers()
                return
            # Sicurezza: impedisce path traversal (es. ../../etc/passwd)
            safe_rel = os.path.normpath(url_path.lstrip('/'))
            if safe_rel.startswith('..') or safe_rel == '.':
                self.send_response(403)
                self.end_headers()
                return
            path = os.path.join(BASE_DIR, safe_rel)
            if not os.path.isfile(path):
                self.send_response(404)
                self.end_headers()
                return
            ext = os.path.splitext(path)[1].lower()
            mime = {
                '.html': 'text/html; charset=utf-8',
                '.js':   'application/javascript; charset=utf-8',
                '.css':  'text/css; charset=utf-8',
            }.get(ext, 'application/octet-stream')
            with open(path, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self):
        if self.path == "/api/data":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            client_ip = self.client_address[0]
            try:
                incoming = json.loads(raw.decode("utf-8"))
                with file_lock:
                    write_data(incoming)
                register_client(client_ip)
                self._json_response(200, {"ok": True})
            except Exception as e:
                log(f"Errore POST /api/data: {e}", "error")
                self._json_response(500, {"error": str(e)})

        elif self.path == "/api/log":
            # Il client manda un evento di log
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
                msg = payload.get("msg", "")
                if msg:
                    log(f"[CLIENT] {msg}")
                self._json_response(200, {"ok": True})
            except Exception:
                self._json_response(400, {"error": "bad request"})
        else:
            self.send_response(404)
            self.end_headers()

# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_logging()
    log("=" * 50)
    log(f"Avvio Gestione Consegne server (porta {PORT}, backend {os.environ.get('DB_BACKEND', 'json')})...")

    init_storage()

    # Avvia server HTTP
    server = http.server.HTTPServer(("0.0.0.0", PORT), Handler)
    log(f"Server in ascolto su 0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        log("Server fermato.")
        server.server_close()
