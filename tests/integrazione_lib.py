"""
Libreria dei test di integrazione: processi veri (migrate.py, server.py), HTTP vero, backend veri.

Nessun test qui dentro. Gli scenari sono in integrazione_scenari.py e integrazione_robustezza.py.
Ogni operazione su un backend avviene in un PROCESSO dedicato (storage.py legge l'ambiente una volta
sola), quindi un solo test può usare json, PostgreSQL e MySQL insieme.
"""
import hashlib
import http.client
import json
import os
import socket
import subprocess
import subprocess as sp
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PY = sys.executable
BACKENDS = ("json", "postgres", "mysql")
DB_DEST = "gestione_consegne_test"
DB_SRC = "gestione_consegne_src_test"

OPS = ["consegne.leggi", "consegne.scrivi", "consegne.elimina",
       "giornate.leggi", "giornate.crea", "giornate.elimina", "giornate.assegna",
       "giornate.riordina", "giornate.segna_completata",
       "squadre.leggi", "squadre.gestisci", "stampa.pdf"]


# ─── ambiente e processi ─────────────────────────────────────────────────────

def base_env():
    """Ambiente pulito: niente variabili di sorgente, migrazione o backend ereditate dal test."""
    drop = ("SRC_", "MIGRATE_", "DB_", "DATA_DIR", "PORT")
    e = {k: v for k, v in os.environ.items() if not k.startswith(drop)}
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e["STORAGE_ALLOW_TEST_RESET"] = "1"
    return e

def backend_env(kind, role, tmp):
    """Variabili DB_* per un backend. role 'dest' o 'src': due database diversi sullo stesso server."""
    if kind == "json":
        d = os.path.join(tmp, f"{role}_data")
        os.makedirs(d, exist_ok=True)
        return {"DB_BACKEND": "json", "DATA_DIR": d}
    pg = kind == "postgres"
    env = {"DB_BACKEND": kind,
           "DB_HOST": os.environ.get("TEST_PG_HOST" if pg else "TEST_MYSQL_HOST", "postgres" if pg else "mysql"),
           "DB_NAME": DB_DEST if role == "dest" else DB_SRC,
           "DB_USER": os.environ.get("DB_USER", "test"),
           "DB_PASSWORD": os.environ.get("DB_PASSWORD", "test")}
    port = os.environ.get("TEST_PG_PORT" if pg else "TEST_MYSQL_PORT")
    if port:
        env["DB_PORT"] = port
    return env

def as_source(env, kind="v1"):
    """Le variabili SRC_* che puntano allo stesso backend di `env`."""
    if env["DB_BACKEND"] == "json":
        s = {"SRC_BACKEND": "json", "SRC_DATA_DIR": env["DATA_DIR"]}
    else:
        s = {"SRC_BACKEND": env["DB_BACKEND"], "SRC_DB_HOST": env["DB_HOST"], "SRC_DB_NAME": env["DB_NAME"],
             "SRC_DB_USER": env["DB_USER"], "SRC_DB_PASSWORD": env["DB_PASSWORD"]}
        if "DB_PORT" in env:
            s["SRC_DB_PORT"] = env["DB_PORT"]
    if kind != "v1":
        s["MIGRATE_SOURCE_KIND"] = kind
    return s

def run(args, env, input=None, timeout=900):
    return sp.run([PY, "-B", *args], env={**base_env(), **env}, input=input, capture_output=True,
                  text=True, timeout=timeout, cwd=ROOT)

def dbtool(cmd, env, data=None):
    p = run([os.path.join(ROOT, "tests", "dbtool.py"), cmd], env, input=json.dumps(data) if data is not None else None)
    if p.returncode not in (0, 2):
        raise AssertionError(f"dbtool {cmd} fallito ({p.returncode}): {p.stdout}{p.stderr}")
    return p.returncode, p.stdout, p.stderr

def dump_v2(env):
    rc, out, err = dbtool("v2-dump", env)
    if rc != 0:
        raise AssertionError(f"archivio V2 non valido: {err}")
    return json.loads(out)

def tables(env):
    return json.loads(dbtool("tables", env)[1])

def migrate(env, *args, **extra):
    """Esegue migrate.py: env = destinazione + sorgente + opzioni. Ritorna (codice, output)."""
    p = run([os.path.join(ROOT, "migrate.py"), *args], {**env, **extra})
    return p.returncode, p.stdout + p.stderr

def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ServerProc:
    """Il vero server.py come processo, su una porta libera."""

    def __init__(self, env, tmp):
        self.env = {**base_env(), **env}
        self.tmp = tmp
        self.proc = None
        self.port = None
        self.n = 0

    def start(self, timeout=60):
        self.port = free_port()
        self.n += 1
        self.logpath = os.path.join(self.tmp, f"server-{self.port}-{self.n}.log")
        self.log = open(self.logpath, "wb")
        self.proc = subprocess.Popen([PY, "-B", os.path.join(ROOT, "server.py")], cwd=ROOT, stdout=self.log,
                                     stderr=subprocess.STDOUT, env={**self.env, "PORT": str(self.port)})
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"server terminato all'avvio (codice {self.proc.returncode}):\n{self.log_tail()}")
            try:
                c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
                c.request("GET", "/api/ping")
                if c.getresponse().status == 200:
                    return self
            except OSError:
                pass
            time.sleep(0.2)
        self.stop()
        raise AssertionError(f"server non pronto entro {timeout}s:\n{self.log_tail()}")

    def log_tail(self, n=25):
        try:
            self.log.flush()
            with open(self.logpath, "r", encoding="utf-8", errors="replace") as f:
                return "".join(f.readlines()[-n:])
        except OSError:
            return ""

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if getattr(self, "log", None):
            self.log.close()
            self.log = None

    def restart(self):
        self.stop()
        return self.start()

    @staticmethod
    def exit_code(env, tmp, timeout=40):
        """Avvia il server e ritorna (codice, log) quando si ferma da solo (rifiuto dell'avvio)."""
        s = ServerProc(env, tmp)
        s.port = free_port()
        path = os.path.join(tmp, f"server-exit-{s.port}.log")
        with open(path, "wb") as log:
            p = subprocess.Popen([PY, "-B", os.path.join(ROOT, "server.py")], cwd=ROOT, stdout=log,
                                 stderr=subprocess.STDOUT, env={**s.env, "PORT": str(s.port)})
            try:
                rc = p.wait(timeout)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                rc = None
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return rc, f.read()


class Api:
    """Client HTTP del server vero, con il Challenge-Response come lo fa il browser."""

    def __init__(self, port):
        self.port = port

    def call(self, method, path, body=None, token=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if token:
            headers["X-Session-Token"] = token
        c.request(method, path, body=json.dumps(body).encode() if body is not None else None, headers=headers)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw.decode()) if raw else None
        except ValueError:
            return r.status, raw

    @staticmethod
    def h1(password):
        return hashlib.sha256(password.encode()).hexdigest()

    def login(self, user, password):
        ch = self.call("GET", "/api/auth/challenge")[1]["challenge"]
        resp = hashlib.sha256((self.h1(password) + ch).encode()).hexdigest()
        return self.call("POST", "/api/auth/login", {"username": user, "challenge": ch, "response": resp})

    def token(self, user, password):
        code, d = self.login(user, password)
        assert code == 200, f"login di {user} fallito: {code} {d}"
        return d["token"]

    def change_password(self, token, old, new):
        ch = self.call("GET", "/api/auth/challenge")[1]["challenge"]
        resp = hashlib.sha256((self.h1(old) + ch).encode()).hexdigest()
        return self.call("POST", "/api/auth/change-password",
                         {"challenge": ch, "response": resp, "nuova_hash": self.h1(new)}, token)

    def superadmin(self, new="Super#Pass2026"):
        """Primo accesso: password di default, cambio obbligatorio, nuovo login."""
        code, d = self.login("superadmin", "admin")
        assert code == 200 and d["must_change_password"], (code, d)
        t = d["token"]
        assert self.call("GET", "/api/negozi", token=t)[0] == 403          # finché non cambia la password
        code, d = self.change_password(t, "admin", new)
        assert code == 200, (code, d)
        return self.token("superadmin", new)

    def must(self, method, path, body=None, token=None, expect=(200, 201)):
        code, d = self.call(method, path, body, token)
        assert code in expect, f"{method} {path} → {code} {d}"
        return d

    def tipo(self, sa, nome, permessi):
        return self.must("POST", "/api/tipi-account", {"nome": nome, "permessi": permessi}, sa)["tipo"]["id"]

    def utente(self, sa, username, tipo_id, negozio_id, password=None):
        return self.must("POST", "/api/utenti", {"username": username, "password_hash": self.h1(password or username + "#Pw1"),
                                                  "tipo_account_id": tipo_id, "negozio_id": negozio_id}, sa)["id"]


# ─── dati V1 e controlli ─────────────────────────────────────────────────────

COGNOMI = ["Rossi", "Bianchi", "Verdi", "Ferrari", "Esposito", "Zanè", "Dall'Olio", "Müller", "Nuñez", 'O"Brien']
# nome della squadra come lo scriveva la V1 → nome che deve avere dopo la migrazione
SQUADRA_ATTESA = {"Squadra A": "Squadra A",              # corrispondenza esatta
                  "": "Non assegnata",                   # giornata senza squadra
                  "squadra b ": "Squadra B",             # maiuscole e spazi diversi
                  "Ghost": "Ghost"}                      # nessuna squadra con questo nome: viene creata
RAW_SQUADRE = list(SQUADRA_ATTESA)

def v1_dataset(n_cons=8, n_giorn=4, per=2):
    """Dati V1 realistici. Le giornate ruotano sui quattro casi di SQUADRA_ATTESA; ogni giornata ha
    `per` consegne assegnate, le altre restano in attesa."""
    squadre = [{"id": "sq1", "nome": "Squadra A", "colorIdx": 0}, {"id": "sq2", "nome": "Squadra B", "colorIdx": 3}]
    giornate = []
    for j in range(n_giorn):
        ids = [f"c{j * per + k}" for k in range(per) if j * per + k < n_cons]
        giornate.append({"id": f"g{j}", "data": f"2026-{1 + j % 12:02d}-{1 + j % 27:02d}",
                         "squadra": RAW_SQUADRE[j % 4], "consegneIds": ids})
    assigned = {cid: g for g in giornate for cid in g["consegneIds"]}
    consegne = []
    for i in range(n_cons):
        g = assigned.get(f"c{i}")
        c = {"id": f"c{i}", "dataPrenotazione": "2026-02-10",
             "stato": ("programmata" if i % 2 else "da_confermare") if g else ("in_attesa" if i % 3 else "da_riprogrammare"),
             "nome": f"Nome{i}", "cognome": COGNOMI[i % len(COGNOMI)], "citta": ["Vicenza", "Padova", "Verona"][i % 3],
             "indirizzo": f"Via Roma {i}", "tel1": f"+39 333 {1000000 + i}", "tel2": "", "raee": "no" if i % 2 else "si",
             "articoli": [{"tipoConsegna": "consegna", "tipo": "TV", "codice": f"X{i}", "desc": '55" àèìòù €'}],
             "piano": str(i % 5), "noteAbitazione": "", "preferenzePeriodo": "", "fasciaOraria": "9:00-12:00",
             "note": "", "campoFuturo": {"i": i}}
        if g:
            c["giornoConsegna"] = g["data"]
        consegne.append(c)
    return {"squadre": squadre, "consegne": consegne, "giornate": giornate}

def write_v1_dir(path, data):
    os.makedirs(path, exist_ok=True)
    for coll in ("squadre", "consegne", "giornate"):
        with open(os.path.join(path, f"{coll}.json"), "w", encoding="utf-8") as f:
            json.dump(data[coll], f, ensure_ascii=False)

def prepare_v1_source(kind, tmp, data):
    """Crea la sorgente V1 nel backend `kind` (o dati.json con kind 'file') e ritorna le variabili SRC_*."""
    if kind == "file":
        p = os.path.join(tmp, "windows", "dati.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return {"MIGRATE_SOURCE_KIND": "file", "SRC_FILE": p}
    senv = backend_env(kind, "src", tmp)
    if kind == "json":
        write_v1_dir(senv["DATA_DIR"], data)
    else:
        dbtool("wipe", senv)
        dbtool("v1-write", senv, data)
    return as_source(senv)

def fresh_dest(kind, tmp, name="dest"):
    """Destinazione vuota nel backend `kind`."""
    d = backend_env(kind, "dest", tmp)
    if kind != "json":
        dbtool("wipe", d)
    return d

def check_integrity(dump):
    """Nessun riferimento orfano o incoerente in un archivio V2. Ritorna l'elenco dei problemi."""
    errs = []
    ids = {c: {r["id"] for r in rows} for c, rows in dump.items()}
    sq = {s["id"]: s for s in dump["squadre"]}
    cons = {c["id"]: c for c in dump["consegne"]}
    for coll in ("squadre", "consegne", "giornate"):
        for r in dump[coll]:
            if r.get("negozio_id") not in ids["negozi"]:
                errs.append(f"{coll} {r['id']}: negozio inesistente")
            if r.get("versione", 0) < 1:
                errs.append(f"{coll} {r['id']}: versione non valida")
    for g in dump["giornate"]:
        s = sq.get(g.get("squadra_id"))
        if s is None:
            errs.append(f"giornata {g['id']}: squadra {g.get('squadra_id')!r} inesistente")
        elif s["negozio_id"] != g["negozio_id"]:
            errs.append(f"giornata {g['id']}: squadra di un altro negozio")
        if len(set(g["consegneIds"])) != len(g["consegneIds"]):
            errs.append(f"giornata {g['id']}: consegne doppie")
        for cid in g["consegneIds"]:
            c = cons.get(cid)
            if c is None:
                errs.append(f"giornata {g['id']}: consegna {cid} inesistente")
            elif c["negozio_id"] != g["negozio_id"]:
                errs.append(f"giornata {g['id']}: consegna {cid} di un altro negozio")
    seen = set()
    for u in dump["utenti"]:
        k = u["username"].casefold()
        if k in seen:
            errs.append(f"utente {u['username']}: username doppio")
        seen.add(k)
        for f, coll in (("negozio_id", "negozi"), ("tipo_account_id", "tipi_account")):
            if u.get(f) is not None and u[f] not in ids[coll]:
                errs.append(f"utente {u['username']}: {f} inesistente")
    if sum(1 for u in dump["utenti"] if u.get("is_superadmin")) != 1:
        errs.append("deve esistere un solo superadmin")
    return errs


def bring_up(dst, data, tmp, src="json", extra=None):
    """Sistema completo come in produzione: sorgente V1 → migrazione → server vero → superadmin, tipo
    account e due utenti nel negozio migrato. Ritorna un dizionario con tutto ciò che serve ai test.
    `extra`: altre variabili d'ambiente (es. BACKUP_INTERVAL). Con un database c'è anche una cartella
    dati (DATA_DIR) in cui finiscono i backup."""
    senv = prepare_v1_source(src, tmp, data)
    denv = {**fresh_dest(dst, tmp), **(extra or {})}
    if "DATA_DIR" not in denv:
        denv["DATA_DIR"] = os.path.join(tmp, "data")
        os.makedirs(denv["DATA_DIR"], exist_ok=True)
    mig_env = {**denv, **senv, "MIGRATE_OUT": os.path.join(tmp, "export.json"), "MIGRATE_EXECUTE": "1"}
    t0 = time.time()
    rc, out = migrate(mig_env)
    elapsed = time.time() - t0
    assert rc == 0, f"migrazione fallita ({rc}):\n{out[-3000:]}"
    srv = ServerProc(denv, tmp).start()
    api = Api(srv.port)
    sa = api.superadmin()
    neg = api.must("GET", "/api/negozi", token=sa)["negozi"]
    assert [n["nome"] for n in neg] == ["Negozio principale"], neg
    tipo = api.tipo(sa, "Operatore", OPS)
    api.utente(sa, "op1", tipo, neg[0]["id"])
    api.utente(sa, "op2", tipo, neg[0]["id"])
    return {"srv": srv, "api": api, "denv": denv, "sa": sa, "neg": neg[0]["id"], "tipo": tipo,
            "t1": api.token("op1", "op1#Pw1"), "t2": api.token("op2", "op2#Pw1"),
            "migrate_seconds": elapsed, "migrate_out": out}
