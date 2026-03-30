#!/usr/bin/env python3
"""
Gestione Consegne — Server locale robusto
- Server unico in rete tramite server.lock
- Lettura fresca dal disco ad ogni scrittura
- Backup automatico (20 snapshot)
- Log con rotazione 7 giorni
- Contatore utenti connessi
- Icona system tray
- Gestione errori NAS (2 tentativi poi crash)
- Ping HTTP per rilevamento disconnessione
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
from datetime import datetime, timedelta

PORT = 8742
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_FILE   = os.path.join(BASE_DIR, "dati.json")
LOCK_FILE   = os.path.join(BASE_DIR, "server.lock")
BACKUP_DIR  = os.path.join(BASE_DIR, "backup")
LOG_FILE    = os.path.join(BASE_DIR, "gestionale.log")
MAX_BACKUPS = 20
LOG_DAYS    = 7
WRITE_RETRIES = 2

file_lock = threading.Lock()
connected_clients = set()   # set di indirizzi IP attivi
clients_lock = threading.Lock()
client_heartbeat = {}       # ip -> ultimo timestamp heartbeat

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
    """Elimina le righe di log più vecchie di LOG_DAYS giorni."""
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

# ─── DATA I/O ────────────────────────────────────────────────────────────────

def read_data():
    """Legge sempre dal disco (mai da cache)."""
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
    """Scrittura atomica: scrive su .tmp poi rinomina."""
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)

def write_data(incoming):
    """
    Lettura fresca + merge + backup + scrittura atomica.
    incoming: dict ricevuto dal client con le modifiche complete.
    """
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
    """Salva uno snapshot prima di ogni scrittura, mantiene MAX_BACKUPS."""
    try:
        if not os.path.exists(DATA_FILE):
            return
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dst = os.path.join(BACKUP_DIR, f"dati.{ts}.json")
        with open(DATA_FILE, "r", encoding="utf-8") as src_f:
            content = src_f.read()
        with open(dst, "w", encoding="utf-8") as dst_f:
            dst_f.write(content)
        # Elimina i backup in eccesso (mantieni solo i più recenti)
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
    ip = get_local_ip()
    info = {"ip": ip, "port": PORT, "pid": os.getpid(), "started": datetime.now().isoformat()}
    tmp = LOCK_FILE + ".tmp"
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
            update_tray_clients(count)
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
            # Forza no-cache per i file statici così il browser non usa versioni vecchie
            self.send_response(200)
            path = self.translate_path(self.path)
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

# ─── TRAY ICON ───────────────────────────────────────────────────────────────

tray_icon = None
tray_label_ref = [None]  # mutable ref per aggiornare il tooltip

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
    # 1. Notifica tray
    try:
        if tray_icon:
            tray_icon.notify(
                title="Gestione Consegne — Server arrestato",
                message=f"Il server si e' arrestato:\n{reason}\n\nRiavvia avvia.bat per riprendere."
            )
    except Exception:
        pass

    # 2. Popup bloccante PowerShell
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

        # Crea icona semplice 64x64 con colore accent
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], fill=(79, 138, 255, 255))
        draw.rectangle([28, 18, 36, 40], fill=(255, 255, 255, 255))
        draw.ellipse([27, 44, 37, 54], fill=(255, 255, 255, 255))

        menu = pystray.Menu(
            pystray.MenuItem("Apri gestionale", lambda: open_browser_action()),
            pystray.MenuItem("Ferma server", lambda: stop_server_action()),
        )
        tray_icon = pystray.Icon(
            "gestione_consegne",
            img,
            "Gestione Consegne — server attivo",
            menu
        )
        tray_icon.run()
    except ImportError:
        # pystray non disponibile (Python embedded senza pystray)
        # fallback: nessuna tray, il server gira comunque
        log("Tray non disponibile (pystray non installato) — server gira in background.", "warning")
        while True:
            time.sleep(60)
    except Exception as e:
        log(f"Tray error: {e}", "warning")

# ─── OPEN BROWSER ────────────────────────────────────────────────────────────

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

    write_lock()

    # Tray icon in thread separato
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
