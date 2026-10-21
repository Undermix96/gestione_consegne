"""
Test del server V2 (server.py): auth, permessi, multi-negozio, REST, optimistic locking.

Il server gira in-process su una porta effimera, sullo storage del backend scelto con DB_BACKEND
(stesso meccanismo di test_storage_contract.py). Solo libreria standard.

ATTENZIONE: con i backend DB la suite SVUOTA le tabelle. Usare un database di test.
"""
import gzip
import hashlib
import http.client
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import unittest

os.environ["STORAGE_ALLOW_TEST_RESET"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import storage as st  # noqa: E402
import server as srv  # noqa: E402

BACKEND = st.BACKEND

OPS = ["consegne.leggi", "consegne.scrivi", "consegne.elimina",
       "giornate.leggi", "giornate.crea", "giornate.elimina", "giornate.assegna",
       "giornate.riordina", "giornate.segna_completata",
       "squadre.leggi", "squadre.gestisci"]
ADMIN = ["utenti.leggi", "utenti.crea", "utenti.modifica", "utenti.elimina", "tipi_account.leggi"]


def setUpModule():
    logging.disable(logging.CRITICAL)


def tearDownModule():
    logging.disable(logging.NOTSET)


def h1(password):
    return hashlib.sha256(password.encode()).hexdigest()


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # cartella dati temporanea per tutti i backend: con json contiene i dati, con i database i backup
        cls._tmp = tempfile.mkdtemp(prefix="gc_srv_test_")
        st.DATA_DIR = cls._tmp
        st.init_storage_v2()
        cls.httpd = srv.make_server(0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if cls._tmp:
            shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        st.init_storage_v2()
        st._test_reset()
        srv.ensure_superadmin()
        with srv.sessions_lock:
            srv.sessions.clear()
        with srv.challenges_lock:
            srv.challenges.clear()
        with srv.fails_lock:
            srv.fails.clear()
            srv.all_fails.clear()
        self.slept = []
        srv._sleep = self.slept.append          # i ritardi non si aspettano davvero: si registrano
        self._salvati = (srv.LOGIN_MAX_FAIL_IP, srv.CHALLENGE_MAX_IP, srv.TRUSTED_PROXIES)
        with srv.timestamps_lock:
            srv.timestamps.clear()

    def tearDown(self):
        srv.LOGIN_MAX_FAIL_IP, srv.CHALLENGE_MAX_IP, srv.TRUSTED_PROXIES = self._salvati
        srv._sleep = srv.time.sleep

    # ── client HTTP ──
    def call(self, method, path, body=None, token=None, raw=None, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if raw is not None:
            data = raw
        if token:
            headers["X-Session-Token"] = token
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        payload = r.read()
        c.close()
        try:
            return r.status, json.loads(payload.decode()) if payload else None
        except ValueError:
            return r.status, payload

    def login(self, username, password):
        _, ch = self.call("GET", "/api/auth/challenge")
        challenge = ch["challenge"]
        resp = hashlib.sha256((h1(password) + challenge).encode()).hexdigest()
        return self.call("POST", "/api/auth/login",
                         {"username": username, "challenge": challenge, "response": resp})

    def token(self, username, password):
        code, d = self.login(username, password)
        self.assertEqual(code, 200, d)
        return d["token"]

    def change_password(self, token, current, new):
        _, ch = self.call("GET", "/api/auth/challenge")
        challenge = ch["challenge"]
        resp = hashlib.sha256((h1(current) + challenge).encode()).hexdigest()
        return self.call("POST", "/api/auth/change-password",
                         {"challenge": challenge, "response": resp, "nuova_hash": h1(new)}, token)

    def superadmin(self):
        t = self.token("superadmin", "admin")
        code, d = self.change_password(t, "admin", "nuova")
        self.assertEqual(code, 200, d)
        return self.token("superadmin", "nuova")

    def mk_negozio(self, sa, nome):
        code, d = self.call("POST", "/api/negozi", {"nome": nome}, sa)
        self.assertEqual(code, 201, d)
        return d["negozio"]["id"]

    def mk_tipo(self, sa, nome, permessi):
        code, d = self.call("POST", "/api/tipi-account", {"nome": nome, "permessi": permessi}, sa)
        self.assertEqual(code, 201, d)
        return d["tipo"]["id"]

    def mk_utente(self, sa, username, tipo, negozio):
        code, d = self.call("POST", "/api/utenti", {
            "username": username, "password_hash": h1(username + "pw"),
            "tipo_account_id": tipo, "negozio_id": negozio}, sa)
        self.assertEqual(code, 201, d)
        return d["id"]

    def world(self):
        """Due negozi, tre tipi e quattro utenti (a1, a2 admin, r1 sola lettura nel negozio A; b1 in B)."""
        sa = self.superadmin()
        w = {"sa": sa}
        w["nA"] = self.mk_negozio(sa, "Negozio A")
        w["nB"] = self.mk_negozio(sa, "Negozio B")
        w["full"] = self.mk_tipo(sa, "Operatore", OPS)
        w["admin"] = self.mk_tipo(sa, "Responsabile", OPS + ADMIN)
        w["reader"] = self.mk_tipo(sa, "Lettore", ["consegne.leggi"])
        w["uid"] = {
            "a1": self.mk_utente(sa, "a1", w["full"], w["nA"]),
            "a2": self.mk_utente(sa, "a2", w["admin"], w["nA"]),
            "r1": self.mk_utente(sa, "r1", w["reader"], w["nA"]),
            "b1": self.mk_utente(sa, "b1", w["full"], w["nB"]),
        }
        for u in ("a1", "a2", "r1", "b1"):
            w[u] = self.token(u, u + "pw")
        return w

    def mk_consegna(self, token, **over):
        body = {"nome": "Mario", "cognome": "Rossi", "citta": "Vicenza", "articoli": []}
        body.update(over)
        code, d = self.call("POST", "/api/consegne", body, token)
        self.assertEqual(code, 201, d)
        return d["consegne"][-1]

    def mk_squadra(self, token, nome="Squadra"):
        code, d = self.call("POST", "/api/squadre", {"nome": nome}, token)
        self.assertEqual(code, 201, d)
        return [s for s in d["squadre"] if s["nome"] == nome][0]["id"]

    def mk_giornata(self, token, data="2026-05-01", squadra_id=None):
        sid = squadra_id or self.mk_squadra(token, f"Sq {data}")
        code, d = self.call("POST", "/api/giornate", {"data": data, "squadra_id": sid}, token)
        self.assertEqual(code, 201, d)
        return [g for g in d["giornate"] if g["data"] == data and g["squadra_id"] == sid][-1]["id"]


class TestAuth(Base):

    def test_ping_pubblico(self):
        code, d = self.call("GET", "/api/ping")
        self.assertEqual(code, 200)
        self.assertTrue(d["ok"])

    def test_challenge_monouso(self):
        _, ch = self.call("GET", "/api/auth/challenge")
        challenge = ch["challenge"]
        resp = hashlib.sha256((h1("admin") + challenge).encode()).hexdigest()
        body = {"username": "superadmin", "challenge": challenge, "response": resp}
        self.assertEqual(self.call("POST", "/api/auth/login", body)[0], 200)
        self.assertEqual(self.call("POST", "/api/auth/login", body)[0], 401)   # riuso

    def test_challenge_inventato_rifiutato(self):
        resp = hashlib.sha256((h1("admin") + "xx").encode()).hexdigest()
        code, _ = self.call("POST", "/api/auth/login",
                            {"username": "superadmin", "challenge": "xx", "response": resp})
        self.assertEqual(code, 401)

    def test_credenziali_errate_stessa_risposta(self):
        c1, d1 = self.login("superadmin", "sbagliata")
        c2, d2 = self.login("nessuno", "admin")
        self.assertEqual((c1, c2), (401, 401))
        self.assertEqual(d1, d2)

    def test_login_dati_mancanti_o_di_tipo_errato(self):
        self.assertEqual(self.call("POST", "/api/auth/login", {})[0], 400)
        self.assertEqual(self.call("POST", "/api/auth/login",
                                   {"username": 1, "challenge": 2, "response": 3})[0], 400)
        self.assertEqual(self.call("POST", "/api/auth/login", raw=b"{non json")[0], 400)
        self.assertEqual(self.call("POST", "/api/auth/login", raw=b"[1,2]")[0], 400)

    def test_primo_login_superadmin_cambio_obbligatorio(self):
        code, d = self.login("superadmin", "admin")
        self.assertEqual(code, 200)
        self.assertTrue(d["must_change_password"])
        self.assertTrue(d["is_superadmin"])
        self.assertIsNone(d["negozio_id"])
        t = d["token"]
        # finché non cambia la password il server blocca tutto il resto
        code, e = self.call("GET", "/api/negozi", token=t)
        self.assertEqual(code, 403)
        self.assertIn("password", e["error"].lower())
        self.assertEqual(self.call("GET", "/api/ping", token=t)[0], 200)
        # password invariata rifiutata
        self.assertEqual(self.change_password(t, "admin", "admin")[0], 400)
        self.assertEqual(self.change_password(t, "sbagliata", "nuova")[0], 401)
        self.assertEqual(self.change_password(t, "admin", "nuova")[0], 200)
        # la vecchia sessione non vale più; si rientra con la nuova password
        self.assertEqual(self.call("GET", "/api/negozi", token=t)[0], 401)
        self.assertEqual(self.login("superadmin", "admin")[0], 401)
        code, d = self.login("superadmin", "nuova")
        self.assertEqual(code, 200)
        self.assertFalse(d["must_change_password"])

    def test_superadmin_creato_una_volta_sola(self):
        srv.ensure_superadmin()
        srv.ensure_superadmin()
        utenti = st.list_records("utenti")
        self.assertEqual([u["id"] for u in utenti], ["u_superadmin"])
        self.assertTrue(utenti[0]["is_superadmin"])
        self.assertIsNone(utenti[0].get("negozio_id"))

    def test_nuova_hash_validata(self):
        t = self.token("superadmin", "admin")
        _, ch = self.call("GET", "/api/auth/challenge")
        resp = hashlib.sha256((h1("admin") + ch["challenge"]).encode()).hexdigest()
        code, _ = self.call("POST", "/api/auth/change-password",
                            {"challenge": ch["challenge"], "response": resp, "nuova_hash": "corta"}, t)
        self.assertEqual(code, 400)

    def test_logout_invalida_il_token(self):
        sa = self.superadmin()
        self.assertEqual(self.call("GET", "/api/negozi", token=sa)[0], 200)
        self.assertEqual(self.call("POST", "/api/auth/logout", token=sa)[0], 200)
        self.assertEqual(self.call("GET", "/api/negozi", token=sa)[0], 401)

    def test_token_assente_o_falso(self):
        self.assertEqual(self.call("GET", "/api/consegne")[0], 401)
        self.assertEqual(self.call("GET", "/api/consegne", token="falso")[0], 401)
        self.assertEqual(self.call("GET", "/api/stato")[0], 401)

    def test_sessione_scaduta(self):
        sa = self.superadmin()
        with srv.sessions_lock:
            srv.sessions[sa]["expires"] = 0
        self.assertEqual(self.call("GET", "/api/negozi", token=sa)[0], 401)

    def test_ping_con_token_non_rinnova_e_segnala_la_scadenza(self):
        sa = self.superadmin()
        with srv.sessions_lock:
            srv.sessions[sa]["expires"] = srv.time.time() + 100
            prima = srv.sessions[sa]["expires"]
        self.assertEqual(self.call("GET", "/api/ping", token=sa)[0], 200)
        with srv.sessions_lock:
            self.assertEqual(srv.sessions[sa]["expires"], prima)        # nessun rinnovo
            srv.sessions[sa]["expires"] = 0
        self.assertEqual(self.call("GET", "/api/ping", token=sa)[0], 401)
        self.assertEqual(self.call("GET", "/api/ping", token="falso")[0], 401)
        self.assertEqual(self.call("GET", "/api/ping")[0], 200)          # senza token (healthcheck)

    def test_utente_non_configurato_bloccato(self):
        sa = self.superadmin()
        nid = self.mk_negozio(sa, "N")
        st.insert_record("utenti", {"id": "u_x", "username": "x", "password_hash": h1("xpw"),
                                    "negozio_id": nid, "primo_login": False})
        code, d = self.login("x", "xpw")
        self.assertEqual(code, 403)
        self.assertIn("non configurato", d["error"].lower())


class TestPermessi(Base):

    def test_superadmin_non_accede_ai_dati_operativi(self):
        sa = self.superadmin()
        for method, path in [("GET", "/api/consegne"), ("GET", "/api/giornate"),
                             ("GET", "/api/squadre"), ("GET", "/api/stato"),
                             ("POST", "/api/consegne"), ("POST", "/api/squadre")]:
            self.assertEqual(self.call(method, path, {}, sa)[0], 403, f"{method} {path}")

    def test_non_superadmin_non_amministra(self):
        w = self.world()
        for method, path, body in [("GET", "/api/negozi", None), ("POST", "/api/negozi", {"nome": "X"}),
                                   ("POST", "/api/tipi-account", {"nome": "X", "permessi": []}),
                                   ("PUT", f"/api/negozi/{w['nA']}", {"nome": "X"}),
                                   ("DELETE", f"/api/tipi-account/{w['full']}", None)]:
            self.assertEqual(self.call(method, path, body, w["a2"])[0], 403, f"{method} {path}")

    def test_permesso_mancante(self):
        w = self.world()
        self.assertEqual(self.call("GET", "/api/consegne", token=w["r1"])[0], 200)
        self.assertEqual(self.call("POST", "/api/consegne", {"nome": "x"}, w["r1"])[0], 403)
        self.assertEqual(self.call("GET", "/api/giornate", token=w["r1"])[0], 403)
        self.assertEqual(self.call("GET", "/api/squadre", token=w["r1"])[0], 403)
        self.assertEqual(self.call("GET", "/api/utenti", token=w["a1"])[0], 403)

    def test_permessi_non_validi_filtrati(self):
        sa = self.superadmin()
        code, d = self.call("POST", "/api/tipi-account", {
            "nome": "T", "permessi": ["consegne.leggi", "negozi.gestisci", "inventato", "consegne.leggi", 5]}, sa)
        self.assertEqual(code, 201)
        self.assertEqual(d["tipo"]["permessi"], ["consegne.leggi"])

    def test_risposta_delle_scritture_solo_categorie_leggibili(self):
        w = self.world()
        t = self.mk_tipo(w["sa"], "Solo scrittura", ["consegne.scrivi", "giornate.crea"])
        self.mk_utente(w["sa"], "s1", t, w["nA"])
        tok = self.token("s1", "s1pw")
        code, d = self.call("POST", "/api/consegne", {"nome": "x"}, tok)
        self.assertEqual(code, 201)
        self.assertEqual(set(d), {"_connectedClients"})                 # niente da leggere
        self.mk_consegna(w["a1"])
        t2 = self.mk_tipo(w["sa"], "Lettura consegne", ["consegne.leggi", "consegne.scrivi"])
        self.mk_utente(w["sa"], "s2", t2, w["nA"])
        code, d = self.call("POST", "/api/consegne", {"nome": "y"}, self.token("s2", "s2pw"))
        self.assertEqual(set(d), {"consegne", "_connectedClients"})
        self.assertEqual(len(d["consegne"]), 3)

    def test_modifica_permessi_chiude_le_sessioni_del_tipo(self):
        w = self.world()
        self.assertEqual(self.call("POST", "/api/consegne", {"nome": "x"}, w["r1"])[0], 403)
        # rinominare senza toccare i permessi non chiude le sessioni
        self.assertEqual(self.call("PUT", f"/api/tipi-account/{w['reader']}", {"nome": "Lettore 2"}, w["sa"])[0], 200)
        self.assertEqual(self.call("GET", "/api/consegne", token=w["r1"])[0], 200)
        # cambiando i permessi gli utenti di quel tipo devono rifare il login, gli altri no
        code, _ = self.call("PUT", f"/api/tipi-account/{w['reader']}",
                            {"permessi": ["consegne.leggi", "consegne.scrivi"]}, w["sa"])
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", "/api/consegne", token=w["r1"])[0], 401)
        self.assertEqual(self.call("GET", "/api/consegne", token=w["a1"])[0], 200)
        t = self.token("r1", "r1pw")
        self.assertEqual(self.call("POST", "/api/consegne", {"nome": "x"}, t)[0], 201)

    def test_revoca_permessi_immediata(self):
        w = self.world()
        self.assertEqual(self.call("POST", "/api/consegne", {"nome": "x"}, w["a1"])[0], 201)
        ridotti = [p for p in OPS if p != "consegne.scrivi"]
        self.assertEqual(self.call("PUT", f"/api/tipi-account/{w['full']}", {"permessi": ridotti}, w["sa"])[0], 200)
        self.assertEqual(self.call("POST", "/api/consegne", {"nome": "x"}, w["a1"])[0], 401)
        t = self.token("a1", "a1pw")
        self.assertEqual(self.call("POST", "/api/consegne", {"nome": "x"}, t)[0], 403)

    def test_durata_massima_della_sessione(self):
        w = self.world()
        with srv.sessions_lock:
            srv.sessions[w["a1"]]["created"] = srv.time.time() - srv.SESSION_MAX_AGE - 1
        # anche con attività recente la sessione non vive oltre il limite assoluto
        self.assertEqual(self.call("GET", "/api/consegne", token=w["a1"])[0], 401)
        self.assertEqual(self.call("GET", "/api/consegne", token=w["a2"])[0], 200)

    def test_limite_tentativi_di_login(self):
        self.world()
        for _ in range(srv.LOGIN_MAX_FAIL_USER):
            self.assertEqual(self.login("a1", "sbagliata")[0], 401)
        # l'utente è bloccato anche con la password giusta; gli altri utenti no
        code, d = self.login("a1", "a1pw")
        self.assertEqual(code, 429, d)
        self.assertEqual(self.login("a2", "a2pw")[0], 200)
        # username in maiuscolo: stessa chiave
        self.assertEqual(self.login("A1", "a1pw")[0], 429)
        # scaduta la finestra si può riprovare
        with srv.fails_lock:
            srv.fails[srv._user_key("a1")] = [srv.time.time() - srv.LOGIN_WINDOW - 1] * srv.LOGIN_MAX_FAIL_USER
        self.assertEqual(self.login("a1", "a1pw")[0], 200)
        # un login riuscito azzera il contatore
        for _ in range(srv.LOGIN_MAX_FAIL_USER - 1):
            self.login("a1", "x")
        self.assertEqual(self.login("a1", "a1pw")[0], 200)
        with srv.fails_lock:
            self.assertNotIn(srv._user_key("a1"), srv.fails)

    def test_limite_tentativi_per_ip_con_utenti_inesistenti(self):
        self.world()
        with srv.fails_lock:
            srv.fails.clear()
        for i in range(srv.LOGIN_MAX_FAIL_IP):
            self.assertEqual(self.login(f"fantasma{i}", "x")[0], 401)
        self.assertEqual(self.login("a1", "a1pw")[0], 429)     # l'IP è bloccato per tutti

    def test_limiti_per_ip_disattivabili(self):
        # dietro un NAT tutti i client hanno lo stesso IP: con 0 restano solo i limiti per username
        srv.LOGIN_MAX_FAIL_IP = 0
        srv.CHALLENGE_MAX_IP = 0
        self.world()
        for i in range(srv.LOGIN_MAX_FAIL_IP + 40):
            self.assertEqual(self.login(f"fantasma{i}", "x")[0], 401)
        self.assertEqual(self.login("a1", "a1pw")[0], 200)
        for _ in range(60):
            self.assertEqual(self.call("GET", "/api/auth/challenge")[0], 200)
        for _ in range(srv.LOGIN_MAX_FAIL_USER):
            self.login("a2", "sbagliata")
        self.assertEqual(self.login("a2", "a2pw")[0], 429)          # il limite per username resta

    def test_env_int(self):
        os.environ["PROVA_X"] = ""
        self.assertEqual(srv._env_int("PROVA_X", 7), 7)
        os.environ["PROVA_X"] = "abc"
        self.assertEqual(srv._env_int("PROVA_X", 7), 7)
        os.environ["PROVA_X"] = "0"
        self.assertEqual(srv._env_int("PROVA_X", 7), 0)
        os.environ["PROVA_X"] = "-3"
        self.assertEqual(srv._env_int("PROVA_X", 7), 0)
        del os.environ["PROVA_X"]
        self.assertEqual(srv._env_int("PROVA_X", 7), 7)

    def test_ip_reale_solo_da_proxy_fidato(self):
        self.world()
        xff = {"X-Forwarded-For": "6.6.6.6, 9.9.9.9"}
        # nessun proxy fidato: l'header è ignorato (altrimenti basterebbe falsificarlo per aggirare i limiti)
        self.call("POST", "/api/auth/login", {"username": "zz"}, headers=xff)   # dati mancanti: nessun fallimento
        self.login("a1", "x")
        with srv.fails_lock:
            self.assertIn(("ip", "127.0.0.1"), srv.fails)
            srv.fails.clear()
        # proxy fidato: vale l'ultimo indirizzo non fidato, non quello scritto dal client
        srv.TRUSTED_PROXIES = srv.parse_trusted_proxies("127.0.0.1, 10.0.0.0/8, non-valido")
        self.assertEqual(len(srv.TRUSTED_PROXIES), 2)
        _, ch = self.call("GET", "/api/auth/challenge")
        resp = hashlib.sha256((h1("x") + ch["challenge"]).encode()).hexdigest()
        self.call("POST", "/api/auth/login", {"username": "a1", "challenge": ch["challenge"], "response": resp},
                  headers={"X-Forwarded-For": "6.6.6.6, 9.9.9.9, 10.1.2.3"})
        with srv.fails_lock:
            self.assertIn(("ip", "9.9.9.9"), srv.fails)
            self.assertNotIn(("ip", "6.6.6.6"), srv.fails)

    def test_client_ip_casi_limite(self):
        srv.TRUSTED_PROXIES = srv.parse_trusted_proxies("172.18.0.0/16,::1")
        self.assertEqual(srv.client_ip("172.18.0.2", "1.2.3.4"), "1.2.3.4")
        self.assertEqual(srv.client_ip("172.18.0.2", "1.2.3.4, 172.18.0.5"), "1.2.3.4")
        self.assertEqual(srv.client_ip("172.18.0.2", "1.2.3.4, spazzatura"), "172.18.0.2")   # malformato
        self.assertEqual(srv.client_ip("172.18.0.2", ""), "172.18.0.2")
        self.assertEqual(srv.client_ip("172.18.0.2", "172.18.0.9"), "172.18.0.2")            # tutti fidati
        self.assertEqual(srv.client_ip("8.8.8.8", "1.2.3.4"), "8.8.8.8")                      # peer non fidato
        self.assertEqual(srv.client_ip("::1", "2001:db8::1"), "2001:db8::1")                  # IPv6
        self.assertEqual(srv.client_ip("nonip", "1.2.3.4"), "nonip")

    def test_ritardo_globale_contro_lo_spray_di_password(self):
        srv.LOGIN_MAX_FAIL_IP = 0
        self.world()
        # ogni username sbaglia una volta sola: nessun limite per username scatta, ma il ritardo sì
        for i in range(srv.LOGIN_DELAY_THRESHOLD):
            self.assertEqual(self.login(f"u{i}", "x")[0], 401)
        self.assertEqual(self.slept, [])                         # sotto la soglia nessun ritardo
        for i in range(4):
            self.assertEqual(self.login(f"v{i}", "x")[0], 401)
        self.assertEqual(self.slept, [srv.LOGIN_DELAY_STEP * k for k in (1, 2, 3, 4)])   # crescente
        for i in range(40):
            self.login(f"w{i}", "x")
        self.assertEqual(max(self.slept), srv.LOGIN_DELAY_MAX)                            # con un tetto
        # chi ha la password giusta non aspetta (e non è bloccato)
        n = len(self.slept)
        self.assertEqual(self.login("a1", "a1pw")[0], 200)
        self.assertEqual(len(self.slept), n)

    def test_challenge_pieni_scartano_il_piu_vecchio(self):
        srv.CHALLENGE_MAX_IP = 0
        vecchio = self.call("GET", "/api/auth/challenge")[1]["challenge"]
        with srv.challenges_lock:
            srv.challenges.update({f"x{i}": (srv.time.time(), "1.1.1.1") for i in range(srv.MAX_CHALLENGES - 1)})
        self.assertEqual(self.call("GET", "/api/auth/challenge")[0], 200)     # non 503
        with srv.challenges_lock:
            self.assertLessEqual(len(srv.challenges), srv.MAX_CHALLENGES)
            self.assertNotIn(vecchio, srv.challenges)

    def test_cambio_password_con_password_errata_e_limitato(self):
        w = self.world()
        for _ in range(srv.LOGIN_MAX_FAIL_USER):
            self.assertEqual(self.change_password(w["a1"], "sbagliata", "nuova123")[0], 401)
        self.assertEqual(self.change_password(w["a1"], "a1pw", "nuova123")[0], 429)

    def test_challenge_per_ip_limitati(self):
        for _ in range(srv.CHALLENGE_MAX_IP):
            self.assertEqual(self.call("GET", "/api/auth/challenge")[0], 200)
        self.assertEqual(self.call("GET", "/api/auth/challenge")[0], 429)
        with srv.challenges_lock:       # scaduti, tornano disponibili
            for c in list(srv.challenges):
                srv.challenges[c] = (0, srv.challenges[c][1])
        self.assertEqual(self.call("GET", "/api/auth/challenge")[0], 200)


class TestNegoziTipi(Base):

    def test_crud_negozi(self):
        sa = self.superadmin()
        nid = self.mk_negozio(sa, "Uno")
        self.assertEqual(self.call("PUT", f"/api/negozi/{nid}", {"nome": "Due"}, sa)[0], 200)
        _, d = self.call("GET", "/api/negozi", token=sa)
        self.assertEqual([n["nome"] for n in d["negozi"]], ["Due"])
        self.assertEqual(self.call("POST", "/api/negozi", {"nome": "  "}, sa)[0], 400)
        self.assertEqual(self.call("PUT", "/api/negozi/inesistente", {"nome": "X"}, sa)[0], 404)
        self.assertEqual(self.call("DELETE", f"/api/negozi/{nid}", token=sa)[0], 200)
        self.assertEqual(self.call("DELETE", f"/api/negozi/{nid}", token=sa)[0], 404)

    def test_negozio_con_utenti_non_eliminabile(self):
        w = self.world()
        code, d = self.call("DELETE", f"/api/negozi/{w['nA']}", token=w["sa"])
        self.assertEqual(code, 409)
        self.assertEqual(len(self.call("GET", "/api/negozi", token=w["sa"])[1]["negozi"]), 2)

    def test_tipo_con_utenti_non_eliminabile_e_nome_univoco(self):
        w = self.world()
        self.assertEqual(self.call("DELETE", f"/api/tipi-account/{w['full']}", token=w["sa"])[0], 409)
        self.assertEqual(self.call("POST", "/api/tipi-account",
                                   {"nome": "Operatore", "permessi": []}, w["sa"])[0], 409)
        libero = self.mk_tipo(w["sa"], "Libero", [])
        self.assertEqual(self.call("DELETE", f"/api/tipi-account/{libero}", token=w["sa"])[0], 200)

    def test_lista_tipi_con_permesso_leggi(self):
        w = self.world()
        code, d = self.call("GET", "/api/tipi-account", token=w["a2"])
        self.assertEqual(code, 200)
        self.assertEqual(len(d["tipi_account"]), 3)


class TestUtenti(Base):

    def test_lista_filtrata_per_negozio_senza_hash(self):
        w = self.world()
        _, d = self.call("GET", "/api/utenti", token=w["a2"])
        self.assertEqual(sorted(u["username"] for u in d["utenti"]), ["a1", "a2", "r1"])
        self.assertTrue(all("password_hash" not in u for u in d["utenti"]))
        _, d = self.call("GET", "/api/utenti", token=w["sa"])
        self.assertEqual(sorted(u["username"] for u in d["utenti"]), ["a1", "a2", "b1", "r1"])

    def test_creazione_nel_proprio_negozio(self):
        w = self.world()
        code, d = self.call("POST", "/api/utenti", {
            "username": "nuovo", "password_hash": h1("p"), "tipo_account_id": w["full"],
            "negozio_id": w["nB"]}, w["a2"])      # il negozio indicato viene ignorato
        self.assertEqual(code, 201, d)
        self.assertEqual(st.get_record("utenti", d["id"])["negozio_id"], w["nA"])

    def test_creazione_validazioni(self):
        w = self.world()
        ok = {"username": "u9", "password_hash": h1("p"), "tipo_account_id": w["full"]}
        self.assertEqual(self.call("POST", "/api/utenti", {**ok, "negozio_id": w["nA"], "username": "A1"},
                                   w["sa"])[0], 409)                                  # maiuscole ignorate
        self.assertEqual(self.call("POST", "/api/utenti", {**ok, "negozio_id": "no"}, w["sa"])[0], 400)
        self.assertEqual(self.call("POST", "/api/utenti", {**ok, "negozio_id": w["nA"],
                                                           "tipo_account_id": "no"}, w["sa"])[0], 400)
        self.assertEqual(self.call("POST", "/api/utenti", {**ok, "negozio_id": w["nA"],
                                                           "password_hash": "x"}, w["sa"])[0], 400)

    def test_reset_password_forza_cambio_e_invalida_sessioni(self):
        w = self.world()
        code, _ = self.call("PUT", f"/api/utenti/{w['uid']['a1']}/password",
                            {"nuova_hash": h1("temp")}, w["a2"])
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", "/api/consegne", token=w["a1"])[0], 401)
        code, d = self.login("a1", "temp")
        self.assertEqual(code, 200)
        self.assertTrue(d["must_change_password"])

    def test_cambio_tipo_invalida_sessioni(self):
        w = self.world()
        code, _ = self.call("PUT", f"/api/utenti/{w['uid']['a1']}/tipo",
                            {"tipo_account_id": w["reader"]}, w["a2"])
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", "/api/consegne", token=w["a1"])[0], 401)
        t = self.token("a1", "a1pw")
        self.assertEqual(self.call("POST", "/api/consegne", {"nome": "x"}, t)[0], 403)

    def test_eliminazione_invalida_sessioni(self):
        w = self.world()
        self.assertEqual(self.call("DELETE", f"/api/utenti/{w['uid']['a1']}", token=w["a2"])[0], 200)
        self.assertEqual(self.call("GET", "/api/consegne", token=w["a1"])[0], 401)
        self.assertEqual(self.login("a1", "a1pw")[0], 401)

    def test_limiti_sugli_utenti_bersaglio(self):
        w = self.world()
        uid = w["uid"]
        # altro negozio
        self.assertEqual(self.call("DELETE", f"/api/utenti/{uid['b1']}", token=w["a2"])[0], 403)
        self.assertEqual(self.call("PUT", f"/api/utenti/{uid['b1']}/password",
                                   {"nuova_hash": h1("x")}, w["a2"])[0], 403)
        # se stessi
        self.assertEqual(self.call("DELETE", f"/api/utenti/{uid['a2']}", token=w["a2"])[0], 403)
        self.assertEqual(self.call("PUT", f"/api/utenti/{uid['a2']}/password",
                                   {"nuova_hash": h1("x")}, w["a2"])[0], 403)
        self.assertEqual(self.call("PUT", f"/api/utenti/{uid['a2']}/tipo",
                                   {"tipo_account_id": w["full"]}, w["a2"])[0], 403)
        # superadmin intoccabile, anche per il superadmin stesso
        self.assertEqual(self.call("DELETE", "/api/utenti/u_superadmin", token=w["sa"])[0], 403)
        self.assertEqual(self.call("PUT", "/api/utenti/u_superadmin/password",
                                   {"nuova_hash": h1("x")}, w["sa"])[0], 403)
        self.assertEqual(self.call("DELETE", "/api/utenti/inesistente", token=w["sa"])[0], 404)

    def test_nessuna_escalation_di_privilegi(self):
        w = self.world()
        sa, uid = w["sa"], w["uid"]
        # "Capo": gestisce gli utenti ma ha meno permessi del Responsabile (a2)
        capo = self.mk_tipo(sa, "Capo", ["consegne.leggi", "utenti.leggi", "utenti.crea",
                                         "utenti.modifica", "utenti.elimina", "tipi_account.leggi"])
        self.mk_utente(sa, "c1", capo, w["nA"])
        c1 = self.token("c1", "c1pw")
        new = {"username": "x1", "password_hash": h1("p")}
        # non può creare utenti con un tipo più potente del suo (né assegnarlo a un altro)
        self.assertEqual(self.call("POST", "/api/utenti", {**new, "tipo_account_id": w["admin"]}, c1)[0], 403)
        self.assertEqual(self.call("POST", "/api/utenti", {**new, "tipo_account_id": w["full"]}, c1)[0], 403)
        self.assertEqual(self.call("PUT", f"/api/utenti/{uid['r1']}/tipo",
                                   {"tipo_account_id": w["admin"]}, c1)[0], 403)
        # non può toccare chi ha più permessi di lui: reset password, cambio tipo, eliminazione
        self.assertEqual(self.call("PUT", f"/api/utenti/{uid['a2']}/password",
                                   {"nuova_hash": h1("x")}, c1)[0], 403)
        self.assertEqual(self.call("PUT", f"/api/utenti/{uid['a1']}/tipo",
                                   {"tipo_account_id": w["reader"]}, c1)[0], 403)
        self.assertEqual(self.call("DELETE", f"/api/utenti/{uid['a2']}", token=c1)[0], 403)
        self.assertEqual(self.login("a2", "a2pw")[0], 200)      # nulla è stato modificato
        # ciò che è contenuto nei suoi permessi resta consentito
        code, d = self.call("POST", "/api/utenti", {**new, "tipo_account_id": w["reader"]}, c1)
        self.assertEqual(code, 201, d)
        self.assertEqual(self.call("PUT", f"/api/utenti/{uid['r1']}/password",
                                   {"nuova_hash": h1("y")}, c1)[0], 200)
        self.assertEqual(self.call("DELETE", f"/api/utenti/{d['id']}", token=c1)[0], 200)
        # il superadmin non ha limiti
        self.assertEqual(self.call("PUT", f"/api/utenti/{uid['r1']}/tipo",
                                   {"tipo_account_id": w["admin"]}, sa)[0], 200)



class TestConsegne(Base):

    def test_crud_e_optimistic_locking(self):
        w = self.world()
        c = self.mk_consegna(w["a1"], campoFuturo={"x": 1})
        self.assertEqual(c["versione"], 1)
        self.assertEqual(c["negozio_id"], w["nA"])
        self.assertEqual(c["stato"], "in_attesa")
        code, d = self.call("PUT", f"/api/consegne/{c['id']}", {"versione": 1, "citta": "Padova"}, w["a1"])
        self.assertEqual(code, 200)
        got = [x for x in d["consegne"] if x["id"] == c["id"]][0]
        self.assertEqual((got["citta"], got["versione"]), ("Padova", 2))
        self.assertEqual(got["campoFuturo"], {"x": 1})
        # secondo utente con versione vecchia
        code, e = self.call("PUT", f"/api/consegne/{c['id']}", {"versione": 1, "citta": "Roma"}, w["a2"])
        self.assertEqual(code, 409)
        self.assertIn("modificata da un altro utente", e["error"])
        self.assertEqual(st.get_record("consegne", c["id"])["citta"], "Padova")

    def test_versione_obbligatoria_e_campi_protetti(self):
        w = self.world()
        c = self.mk_consegna(w["a1"])
        self.assertEqual(self.call("PUT", f"/api/consegne/{c['id']}", {"citta": "X"}, w["a1"])[0], 400)
        self.assertEqual(self.call("PUT", f"/api/consegne/{c['id']}",
                                   {"versione": "1", "citta": "X"}, w["a1"])[0], 400)
        code, d = self.call("PUT", f"/api/consegne/{c['id']}", {
            "versione": 1, "id": "altro", "negozio_id": w["nB"], "_connectedClients": 5, "citta": "X"}, w["a1"])
        self.assertEqual(code, 200, d)
        rec = st.get_record("consegne", c["id"])
        self.assertEqual(rec["negozio_id"], w["nA"])
        self.assertNotIn("_connectedClients", rec)
        self.assertIsNone(st.get_record("consegne", "altro"))

    def test_campi_e_articoli_validati(self):
        w = self.world()
        t = w["a1"]
        base = {"nome": "Mario", "cognome": "Rossi"}
        cattivi = [
            {"articoli": [None]}, {"articoli": ["x"]}, {"articoli": "x"}, {"articoli": [{}] * 51},
            {"articoli": [{"tipoConsegna": "constructor"}]}, {"articoli": [{"tipoConsegna": "__proto__"}]},
            {"articoli": [{"tipo": 5}]}, {"articoli": [{"desc": "x" * 501}]}, {"articoli": [{"altro": "x"}]},
            {"tipoConsegna": "constructor"}, {"campo_enorme": "x" * 2001}, {f"k{i}": 1 for i in range(21)}, {"note": 5}, {"note": ["a"]},
            {"note": "x" * 2001},
        ]
        for extra in cattivi:
            self.assertEqual(self.call("POST", "/api/consegne", {**base, **extra}, t)[0], 400, extra)
        ok = {**base, "articoli": [{"tipoConsegna": "ins_muro", "tipo": "TV", "codice": "A1", "desc": "x"}],
              "tel1": "333", "raee": "si", "piano": "2"}
        c = self.mk_consegna(t, **ok)
        # anche in modifica
        code, _ = self.call("PUT", f"/api/consegne/{c['id']}",
                            {"versione": c["versione"], "articoli": [None]}, t)
        self.assertEqual(code, 400)
        self.assertEqual(self.call("PUT", f"/api/consegne/{c['id']}",
                                   {"versione": c["versione"], "note": "ok"}, t)[0], 200)

    def test_stato_non_valido(self):
        w = self.world()
        self.assertEqual(self.call("POST", "/api/consegne", {"stato": "boh"}, w["a1"])[0], 400)

    def test_isolamento_tra_negozi(self):
        w = self.world()
        c = self.mk_consegna(w["a1"])
        _, d = self.call("GET", "/api/consegne", token=w["b1"])
        self.assertEqual(d["consegne"], [])
        self.assertEqual(self.call("PUT", f"/api/consegne/{c['id']}", {"versione": 1, "citta": "X"}, w["b1"])[0], 403)
        self.assertEqual(self.call("DELETE", f"/api/consegne/{c['id']}", token=w["b1"])[0], 403)
        self.assertIsNotNone(st.get_record("consegne", c["id"]))
        self.assertEqual(self.call("PUT", "/api/consegne/inesistente", {"versione": 1}, w["a1"])[0], 404)

    def test_la_risposta_e_il_db_del_negozio(self):
        w = self.world()
        self.mk_consegna(w["b1"])
        code, d = self.call("POST", "/api/consegne", {"nome": "A"}, w["a1"])
        self.assertEqual(code, 201)
        self.assertEqual(len(d["consegne"]), 1)
        self.assertEqual(set(d), {"consegne", "giornate", "squadre", "_connectedClients"})

    def test_elimina_toglie_dalle_giornate(self):
        w = self.world()
        c = self.mk_consegna(w["a1"])
        gid = self.mk_giornata(w["a1"])
        self.call("POST", f"/api/giornate/{gid}/assegna", {"consegna_ids": [c["id"]]}, w["a1"])
        code, d = self.call("DELETE", f"/api/consegne/{c['id']}", token=w["a1"])
        self.assertEqual(code, 200)
        self.assertEqual(d["consegne"], [])
        self.assertEqual(d["giornate"][0]["consegneIds"], [])


class TestGiornate(Base):

    def setUp(self):
        super().setUp()
        self.w = w = self.world()
        self.c1 = self.mk_consegna(w["a1"], cognome="Uno")
        self.c2 = self.mk_consegna(w["a1"], cognome="Due")
        self.sid = self.mk_squadra(w["a1"], "Sq")
        self.gid = self.mk_giornata(w["a1"], "2026-05-01", self.sid)

    def assegna(self, *cids, token=None):
        return self.call("POST", f"/api/giornate/{self.gid}/assegna",
                         {"consegna_ids": list(cids)}, token or self.w["a1"])

    def test_assegna_imposta_stato_e_giorno(self):
        code, d = self.assegna(self.c1["id"], self.c2["id"])
        self.assertEqual(code, 200)
        self.assertEqual(d["giornate"][0]["consegneIds"], [self.c1["id"], self.c2["id"]])
        for c in d["consegne"]:
            self.assertEqual((c["stato"], c["giornoConsegna"]), ("da_confermare", "2026-05-01"))
        self.assertEqual(self.assegna(self.c1["id"])[0], 200)            # idempotente
        self.assertEqual(len(st.get_record("giornate", self.gid)["consegneIds"]), 2)

    def test_assegna_consegna_di_altro_negozio_o_inesistente(self):
        altra = self.mk_consegna(self.w["b1"])
        self.assertEqual(self.assegna(altra["id"])[0], 403)
        self.assertEqual(self.assegna("inesistente")[0], 404)
        self.assertEqual(st.get_record("giornate", self.gid)["consegneIds"], [])
        self.assertEqual(self.assegna(self.c1["id"], token=self.w["b1"])[0], 403)   # giornata di altri
        self.assertEqual(self.call("POST", f"/api/giornate/{self.gid}/assegna", {"consegna_ids": "x"},
                                   self.w["a1"])[0], 400)

    def test_riordina(self):
        self.assegna(self.c1["id"], self.c2["id"])
        ids = [self.c2["id"], self.c1["id"]]
        code, d = self.call("PUT", f"/api/giornate/{self.gid}/riordina", {"consegna_ids": ids}, self.w["a1"])
        self.assertEqual(code, 200)
        self.assertEqual(d["giornate"][0]["consegneIds"], ids)
        self.assertEqual(self.call("PUT", f"/api/giornate/{self.gid}/riordina",
                                   {"consegna_ids": [self.c1["id"]]}, self.w["a1"])[0], 400)

    def test_rimuovi_riporta_in_attesa(self):
        self.assegna(self.c1["id"])
        self.call("PUT", f"/api/consegne/{self.c1['id']}", {"versione": 2, "fasciaOraria": "9-12"}, self.w["a1"])
        code, d = self.call("DELETE", f"/api/giornate/{self.gid}/assegna/{self.c1['id']}", token=self.w["a1"])
        self.assertEqual(code, 200)
        c = [x for x in d["consegne"] if x["id"] == self.c1["id"]][0]
        self.assertEqual((c["stato"], c["giornoConsegna"], c["fasciaOraria"]), ("in_attesa", "", ""))
        self.assertEqual(d["giornate"][0]["consegneIds"], [])

    def test_segna_completata(self):
        self.assegna(self.c1["id"])
        url = f"/api/giornate/{self.gid}/consegne/{self.c1['id']}/completa"
        code, d = self.call("PUT", url, token=self.w["a1"])
        self.assertEqual(code, 200)
        self.assertEqual([c["stato"] for c in d["consegne"] if c["id"] == self.c1["id"]], ["completata"])
        # una consegna non presente nella giornata → 404
        self.assertEqual(self.call("PUT", f"/api/giornate/{self.gid}/consegne/{self.c2['id']}/completa",
                                   token=self.w["a1"])[0], 404)
        # una consegna completata non torna in attesa se viene rimossa
        _, d = self.call("DELETE", f"/api/giornate/{self.gid}/assegna/{self.c1['id']}", token=self.w["a1"])
        self.assertEqual([c["stato"] for c in d["consegne"] if c["id"] == self.c1["id"]], ["completata"])

    def test_elimina_giornata(self):
        self.assegna(self.c1["id"])
        self.assertEqual(self.call("DELETE", f"/api/giornate/{self.gid}", token=self.w["a1"])[0], 409)
        self.call("DELETE", f"/api/giornate/{self.gid}/assegna/{self.c1['id']}", token=self.w["a1"])
        self.assertEqual(self.call("DELETE", f"/api/giornate/{self.gid}", token=self.w["b1"])[0], 403)
        code, d = self.call("DELETE", f"/api/giornate/{self.gid}", token=self.w["a1"])
        self.assertEqual((code, d["giornate"]), (200, []))

    def test_crea_validazioni(self):
        self.assertEqual(self.call("POST", "/api/giornate", {}, self.w["a1"])[0], 400)
        self.assertEqual(self.call("POST", "/api/giornate", {"data": "domani"}, self.w["a1"])[0], 400)
        a = self.w["a1"]
        ok = {"data": "2026-05-01", "squadra_id": self.sid}
        self.assertEqual(self.call("POST", "/api/giornate", {"data": "2026-05-01"}, a)[0], 400)           # squadra obbligatoria
        self.assertEqual(self.call("POST", "/api/giornate", {**ok, "squadra_id": ""}, a)[0], 400)
        self.assertEqual(self.call("POST", "/api/giornate", {**ok, "squadra_id": 3}, a)[0], 400)
        self.assertEqual(self.call("POST", "/api/giornate", {**ok, "squadra_id": "inesistente"}, a)[0], 400)
        altra = self.mk_squadra(self.w["b1"], "DiB")                                                      # di un altro negozio
        self.assertEqual(self.call("POST", "/api/giornate", {**ok, "squadra_id": altra}, a)[0], 403)
        self.assertEqual(len(st.list_records("giornate")), 1)
        # stessa data con squadre diverse: ammessa
        code, d = self.call("POST", "/api/giornate", {**ok, "squadra_id": self.mk_squadra(a, "Altra")}, a)
        self.assertEqual((code, len(d["giornate"])), (201, 2))
        self.assertEqual(d["giornate"][0]["squadra_id"], self.sid)


class TestSquadre(Base):

    def setUp(self):
        super().setUp()
        self.w = self.world()

    def test_crea_colori_e_duplicati(self):
        a, b = self.w["a1"], self.w["b1"]
        for i, nome in enumerate(["Uno", "Due", "Tre"]):
            _, d = self.call("POST", "/api/squadre", {"nome": nome}, a)
            self.assertEqual(d["squadre"][-1]["colorIdx"], i)
        self.assertEqual(self.call("POST", "/api/squadre", {"nome": "uno"}, a)[0], 409)
        self.assertEqual(self.call("POST", "/api/squadre", {"nome": "Uno"}, b)[0], 201)   # altro negozio
        self.assertEqual(self.call("POST", "/api/squadre", {"nome": " "}, a)[0], 400)

    def test_rinomina_non_tocca_le_giornate_e_conflitti(self):
        a = self.w["a1"]
        sid = self.mk_squadra(a, "Uno")
        self.mk_giornata(a, "2026-05-01", sid)
        sq = st.get_record("squadre", sid)
        giornate_prima = st.list_records("giornate")
        self.assertEqual(self.call("PUT", f"/api/squadre/{sq['id']}", {"nome": "Nuova"}, a)[0], 400)  # versione
        code, d = self.call("PUT", f"/api/squadre/{sq['id']}", {"versione": 1, "nome": "Nuova", "colorIdx": 5}, a)
        self.assertEqual(code, 200, d)
        self.assertEqual((d["squadre"][0]["nome"], d["squadre"][0]["colorIdx"]), ("Nuova", 5))
        self.assertEqual(d["giornate"][0]["squadra_id"], sid)                 # la giornata la referenzia per id
        self.assertEqual(st.list_records("giornate"), giornate_prima)         # e non è stata riscritta
        # versione superata: 409
        code, _ = self.call("PUT", f"/api/squadre/{sq['id']}", {"versione": 1, "nome": "Ancora"}, a)
        self.assertEqual(code, 409)
        self.assertEqual(st.get_record("squadre", sid)["nome"], "Nuova")
        self.assertEqual(self.call("PUT", f"/api/squadre/{sq['id']}", {"versione": 2, "colorIdx": 9}, a)[0], 400)
        self.assertEqual(self.call("PUT", f"/api/squadre/{sq['id']}", {"versione": 2, "nome": "x"},
                                   self.w["b1"])[0], 403)

    def test_elimina_bloccata_se_ha_giornate(self):
        a = self.w["a1"]
        sid = self.mk_squadra(a, "Uno")
        gid = self.mk_giornata(a, "2026-05-01", sid)
        self.assertEqual(self.call("DELETE", f"/api/squadre/{sid}", token=self.w["b1"])[0], 403)
        code, d = self.call("DELETE", f"/api/squadre/{sid}", token=a)
        self.assertEqual(code, 409)
        self.assertIn("giornate", d["error"])
        self.assertIsNotNone(st.get_record("squadre", sid))
        self.assertEqual(st.get_record("giornate", gid)["squadra_id"], sid)
        # eliminate le giornate, la squadra si può eliminare
        self.assertEqual(self.call("DELETE", f"/api/giornate/{gid}", token=a)[0], 200)
        code, d = self.call("DELETE", f"/api/squadre/{sid}", token=a)
        self.assertEqual(code, 200)
        self.assertEqual([s["id"] for s in d["squadre"] if s["id"] == sid], [])

    def test_elimina_squadra_senza_giornate_tocca_solo_squadre(self):
        a = self.w["a1"]
        sid = self.mk_squadra(a, "Uno")
        _, before = self.call("GET", "/api/stato", token=a)
        self.assertEqual(self.call("DELETE", f"/api/squadre/{sid}", token=a)[0], 200)
        _, after = self.call("GET", "/api/stato", token=a)
        self.assertGreater(after["squadre"], before["squadre"])
        self.assertEqual((after["giornate"], after["consegne"]), (before["giornate"], before["consegne"]))


class TestStato(Base):

    def test_timestamp_per_negozio(self):
        w = self.world()
        _, a0 = self.call("GET", "/api/stato", token=w["a1"])
        _, b0 = self.call("GET", "/api/stato", token=w["b1"])
        self.assertEqual(set(a0), {"consegne", "giornate", "squadre"})
        self.mk_consegna(w["a1"])
        _, a1 = self.call("GET", "/api/stato", token=w["a1"])
        _, b1 = self.call("GET", "/api/stato", token=w["b1"])
        self.assertGreater(a1["consegne"], a0["consegne"])
        self.assertEqual(a1["giornate"], a0["giornate"])
        self.assertEqual(b1, b0)

    def test_stato_non_rinnova_la_sessione(self):
        w = self.world()
        with srv.sessions_lock:
            srv.sessions[w["a1"]]["expires"] = srv.time.time() + 100
            prima = srv.sessions[w["a1"]]["expires"]
        self.assertEqual(self.call("GET", "/api/stato", token=w["a1"])[0], 200)
        with srv.sessions_lock:
            self.assertEqual(srv.sessions[w["a1"]]["expires"], prima)
        self.assertEqual(self.call("GET", "/api/consegne", token=w["a1"])[0], 200)   # un'azione rinnova
        with srv.sessions_lock:
            self.assertGreater(srv.sessions[w["a1"]]["expires"], prima)

    def test_modifiche_incrociate(self):
        w = self.world()
        c = self.mk_consegna(w["a1"])
        _, before = self.call("GET", "/api/stato", token=w["a1"])
        self.call("DELETE", f"/api/consegne/{c['id']}", token=w["a1"])
        _, after = self.call("GET", "/api/stato", token=w["a1"])
        self.assertGreater(after["consegne"], before["consegne"])
        self.assertGreater(after["giornate"], before["giornate"])
        self.assertEqual(after["squadre"], before["squadre"])


class TestBackup(Base):
    """Backup dal pannello del superadmin: elenco e backup immediato (snapshot json o dump SQL)."""

    def setUp(self):
        super().setUp()
        shutil.rmtree(os.path.join(st.DATA_DIR, "backup"), ignore_errors=True)
        st._be()._last_backup = srv.time.time()      # json: nessuno snapshot automatico prima delle scritture di prova

    def test_solo_il_superadmin(self):
        w = self.world()
        for method in ("GET", "POST"):
            self.assertEqual(self.call(method, "/api/backup", {} if method == "POST" else None, w["a2"])[0], 403, method)
            self.assertEqual(self.call(method, "/api/backup", {} if method == "POST" else None, w["r1"])[0], 403, method)
            self.assertEqual(self.call(method, "/api/backup", {} if method == "POST" else None)[0], 401, method)

    def test_elenco_e_backup_immediato(self):
        sa = self.superadmin()
        code, d = self.call("GET", "/api/backup", token=sa)
        self.assertEqual(code, 200)
        self.assertEqual(d["backups"], [])
        self.assertEqual((d["intervallo"], d["conservati"], d["backend"]), (st.BACKUP_MIN_INTERVAL, st.MAX_BACKUPS, BACKEND))
        code, r = self.call("POST", "/api/backup", {}, sa)
        self.assertEqual(code, 200, r)
        self.assertTrue(r["ok"])
        self.assertEqual([b["nome"] for b in r["backups"]], [r["file"]])             # la risposta contiene già l'elenco aggiornato
        self.assertEqual(r["backups"][0]["tipo"], "snapshot" if BACKEND == "json" else "dump")
        self.assertGreater(r["backups"][0]["dimensione"], 0)
        code, d = self.call("GET", "/api/backup", token=sa)
        self.assertEqual([b["nome"] for b in d["backups"]], [r["file"]])
        if BACKEND != "json":
            with gzip.open(os.path.join(st.DATA_DIR, "backup", r["file"]), "rt", encoding="utf-8") as f:
                self.assertIn("superadmin", f.read())                                 # il dump contiene i dati veri

    def test_backup_non_riuscito(self):
        sa = self.superadmin()
        shutil.rmtree(os.path.join(st.DATA_DIR, "backup"), ignore_errors=True)
        with open(os.path.join(st.DATA_DIR, "backup"), "w") as f:                    # un file al posto della cartella
            f.write("x")
        self.addCleanup(lambda: os.path.exists(os.path.join(st.DATA_DIR, "backup")) and os.path.isfile(
            os.path.join(st.DATA_DIR, "backup")) and os.remove(os.path.join(st.DATA_DIR, "backup")))
        code, d = self.call("POST", "/api/backup", {}, sa)
        self.assertEqual(code, 500)
        self.assertIn("Backup non riuscito", d["error"])
        self.assertEqual(self.call("GET", "/api/ping")[0], 200)                       # il server resta in piedi


class TestLogScaricabili(Base):
    """Log su file in DATA_DIR/log, elenco e download (singolo file o zip) riservati al superadmin."""

    def setUp(self):
        super().setUp()
        self.dir = os.path.join(st.DATA_DIR, "log")
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir)
        for nome, testo in (("server.log", "riga attiva\n"), ("server.log.2", "vecchia\n"), ("server.log.1", "media\n"),
                            ("altro.txt", "non va esposto\n")):
            with open(os.path.join(self.dir, nome), "w", encoding="utf-8") as f:
                f.write(testo)
        self.addCleanup(shutil.rmtree, self.dir, True)

    def get_raw(self, path, token):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        c.request("GET", path, headers={"X-Session-Token": token} if token else {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, dict(r.getheaders()), body

    def test_solo_il_superadmin(self):
        w = self.world()
        for path in ("/api/log", "/api/log/download/server.log", "/api/log/download/tutti"):
            self.assertEqual(self.call("GET", path, token=w["a2"])[0], 403, path)
            self.assertEqual(self.call("GET", path, token=w["r1"])[0], 403, path)
            self.assertEqual(self.call("GET", path)[0], 401, path)

    def test_elenco_ordinato_e_solo_i_file_di_log(self):
        sa = self.superadmin()
        code, d = self.call("GET", "/api/log", token=sa)
        self.assertEqual(code, 200)
        self.assertEqual([f["nome"] for f in d["files"]], ["server.log", "server.log.1", "server.log.2"])
        self.assertEqual(d["files"][0]["dimensione"], len("riga attiva\n"))
        self.assertTrue(d["attivo"])

    def test_download_singolo(self):
        sa = self.superadmin()
        code, h, body = self.get_raw("/api/log/download/server.log.1", sa)
        self.assertEqual(code, 200)
        self.assertEqual(body, b"media\n")
        self.assertIn('attachment; filename="server.log.1"', h["Content-Disposition"])
        self.assertTrue(h["Content-Type"].startswith("text/plain"))
        self.assertEqual(h["Cache-Control"], "no-store")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_download_zip(self):
        import io
        import zipfile
        sa = self.superadmin()
        code, h, body = self.get_raw("/api/log/download/tutti", sa)
        self.assertEqual(code, 200)
        self.assertEqual(h["Content-Type"], "application/zip")
        self.assertIn(".zip", h["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(body)) as zf:
            self.assertEqual(sorted(zf.namelist()), ["server.log", "server.log.1", "server.log.2"])
            self.assertEqual(zf.read("server.log.2"), b"vecchia\n")

    def test_nomi_non_ammessi(self):
        sa = self.superadmin()
        for nome in ("altro.txt", "server.log.x", "server.log.", "server.log.1234", "nulla", "..%2Fmeta.json",
                     "%2e%2e%2fstorage.py", "server.log%00", "server.log.9"):
            code, _, _ = self.get_raw("/api/log/download/" + nome, sa)
            self.assertEqual(code, 404, nome)

    def test_senza_cartella(self):
        sa = self.superadmin()
        shutil.rmtree(self.dir)
        code, d = self.call("GET", "/api/log", token=sa)
        self.assertEqual((code, d["files"]), (200, []))
        self.assertEqual(self.get_raw("/api/log/download/tutti", sa)[0], 200)     # zip vuoto, non un errore
        self.assertEqual(self.get_raw("/api/log/download/server.log", sa)[0], 404)

    def test_handler_file_ruotato_e_privato(self):
        import logging
        saved = (srv.LOG_FILE_MAX_BYTES, srv.LOG_FILE_KEEP)
        root = logging.getLogger()
        h = None
        try:
            srv.LOG_FILE_MAX_BYTES, srv.LOG_FILE_KEEP = 300, 2
            shutil.rmtree(self.dir)
            h = srv.setup_file_logging()
            self.assertIsNotNone(h)
            for i in range(30):
                h.emit(logging.LogRecord("t", logging.INFO, __file__, 1, f"riga {i} " + "x" * 40, None, None))
            h.flush()
            nomi = sorted(os.listdir(self.dir))
            self.assertEqual(nomi, ["server.log", "server.log.1", "server.log.2"])      # mai più di KEEP file ruotati
            if os.name == "posix":
                self.assertEqual(os.stat(os.path.join(self.dir, "server.log")).st_mode & 0o777, 0o600)
            with open(os.path.join(self.dir, "server.log"), encoding="utf-8") as f:
                self.assertRegex(f.readline(), r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[INFO\] riga \d+")
        finally:
            if h:
                root.removeHandler(h)
                h.close()
            srv.LOG_FILE_MAX_BYTES, srv.LOG_FILE_KEEP = saved

    def test_disattivato_o_cartella_non_scrivibile(self):
        saved = srv.LOG_FILE_MAX_BYTES
        try:
            srv.LOG_FILE_MAX_BYTES = 0
            self.assertIsNone(srv.setup_file_logging())
            srv.LOG_FILE_MAX_BYTES = 1000
            shutil.rmtree(self.dir)
            with open(self.dir, "w") as f:                                          # un file al posto della cartella
                f.write("x")
            self.assertIsNone(srv.setup_file_logging())                              # nessuna eccezione: si resta su stdout
        finally:
            srv.LOG_FILE_MAX_BYTES = saved
            if os.path.isfile(self.dir):
                os.remove(self.dir)


class TestLogEOperazioniComposte(Base):

    # ── SEC-08 ──
    def test_log_su_una_riga_sola(self):
        logging.disable(logging.NOTSET)
        try:
            with self.assertLogs(level="DEBUG") as cm:
                self.login("falso\n2026-10-20 10:00:00 [INFO] [AUTH] 'superadmin' ha effettuato il login\r\x1b[2J", "x")
                w = self.world()
                self.mk_consegna(w["a1"], cognome="Rossi\nFalso [WARN] riga inventata", nome="Mario")
        finally:
            logging.disable(logging.CRITICAL)
        for riga in cm.output:
            self.assertEqual(len(riga.splitlines()), 1, riga)
            self.assertNotIn("\x1b", riga)
        self.assertTrue(any("falso?2026-10-20" in r for r in cm.output))
        self.assertTrue(any("Rossi?Falso" in r for r in cm.output))
        self.assertEqual(len(srv._CTRL_RE.sub("?", "x" * 5000)[:srv.MAX_LOG_LEN]), srv.MAX_LOG_LEN)

    def test_client_id_non_valido_non_si_conta(self):
        with srv.clients_lock:
            srv.client_heartbeat.clear()
        for cid in ("abc", "x" * 65, "con spazio!", "aè" * 8, "valido-12345678"):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/api/ping", headers={"X-Client-ID": cid})
            c.getresponse().read()
            c.close()
        with srv.clients_lock:
            chiavi = set(srv.client_heartbeat)
        self.assertEqual(chiavi, {"valido-12345678"})      # gli altri cadono sull'IP (qui localhost: non conta)
        with srv.clients_lock:
            srv.client_heartbeat.clear()
            for i in range(srv.MAX_CLIENTS):
                srv.client_heartbeat[f"id-{i:08d}"] = srv.time.time()
        srv.register_client("1.1.1.1", "nuovo-id-12345")
        with srv.clients_lock:
            self.assertEqual(len(srv.client_heartbeat), srv.MAX_CLIENTS)
            srv.client_heartbeat.clear()

    # ── SEC-10 ──
    def test_errori_di_validazione_senza_dettagli_interni(self):
        sa = self.superadmin()
        code, d = self.call("POST", "/api/tipi-account", {"nome": "x" * 300, "permessi": []}, sa)
        self.assertEqual(code, 400)
        self.assertEqual(d, {"error": "Dati non validi"})

    def test_completata_richiede_segna_completata(self):
        w = self.world()
        sa = w["sa"]
        t = self.mk_tipo(sa, "Senza completa", [p for p in OPS if p != "giornate.segna_completata"])
        self.mk_utente(sa, "s1", t, w["nA"])
        s1 = self.token("s1", "s1pw")
        self.assertEqual(self.call("POST", "/api/consegne", {"nome": "x", "stato": "completata"}, s1)[0], 403)
        c = self.mk_consegna(s1)
        v = c["versione"]
        self.assertEqual(self.call("PUT", f"/api/consegne/{c['id']}", {"versione": v, "stato": "completata"}, s1)[0], 403)
        self.assertEqual(self.call("PUT", f"/api/consegne/{c['id']}", {"versione": v, "stato": "annullata"}, s1)[0], 200)
        # chi ha il permesso può
        c2 = self.mk_consegna(w["a1"])
        self.assertEqual(self.call("PUT", f"/api/consegne/{c2['id']}",
                                   {"versione": c2["versione"], "stato": "completata"}, w["a1"])[0], 200)
        # già completata: modificare altro (o rimandare lo stesso stato) non richiede il permesso
        c3 = self.mk_consegna(w["a1"], stato="completata")
        _, d = self.call("GET", "/api/consegne", token=s1)
        ver = [x for x in d["consegne"] if x["id"] == c3["id"]][0]["versione"]
        self.assertEqual(self.call("PUT", f"/api/consegne/{c3['id']}",
                                   {"versione": ver, "stato": "completata", "note": "ok"}, s1)[0], 200)

    def test_assegna_annullata_se_un_passaggio_fallisce(self):
        w = self.world()
        t = w["a1"]
        gid = self.mk_giornata(t)
        c1, c2 = self.mk_consegna(t, cognome="A"), self.mk_consegna(t, cognome="B")
        originale = st.update_record
        chiamate = []

        def guasto(coll, rid, changes, expected_versione=None):
            if coll == "consegne":
                chiamate.append(rid)
                if len(chiamate) == 2:
                    raise st.StorageError("guasto simulato")
            return originale(coll, rid, changes, expected_versione=expected_versione)
        srv.storage.update_record = guasto
        try:
            code, _ = self.call("POST", f"/api/giornate/{gid}/assegna", {"consegna_ids": [c1["id"], c2["id"]]}, t)
        finally:
            srv.storage.update_record = originale
        self.assertEqual(code, 500)
        self.assertEqual(st.get_record("giornate", gid).get("consegneIds", []), [])
        for c in (c1, c2):
            self.assertEqual(st.get_record("consegne", c["id"])["stato"], "in_attesa")
            self.assertFalse(st.get_record("consegne", c["id"]).get("giornoConsegna"))

    def test_squadre_con_lo_stesso_nome_in_parallelo(self):
        from concurrent.futures import ThreadPoolExecutor
        w = self.world()
        with ThreadPoolExecutor(max_workers=8) as ex:
            codici = list(ex.map(lambda _: self.call("POST", "/api/squadre", {"nome": "Doppia"}, w["a1"])[0], range(8)))
        self.assertEqual(sorted(codici), [201] + [409] * 7)

    def test_elimina_giornata_e_assegna_in_parallelo(self):
        from concurrent.futures import ThreadPoolExecutor
        w = self.world()
        t = w["a1"]
        sid = self.mk_squadra(t)
        for i in range(8):
            gid = self.mk_giornata(t, data=f"2026-06-{i + 1:02d}", squadra_id=sid)
            c = self.mk_consegna(t, cognome=f"P{i}")
            with ThreadPoolExecutor(max_workers=2) as ex:
                a = ex.submit(self.call, "POST", f"/api/giornate/{gid}/assegna", {"consegna_ids": [c["id"]]}, t)
                d = ex.submit(self.call, "DELETE", f"/api/giornate/{gid}", None, t)
                ca, cd = a.result()[0], d.result()[0]
            g = st.get_record("giornate", gid)
            stato = st.get_record("consegne", c["id"])["stato"]
            if g is None:                      # eliminata prima: nessuna consegna "assegnata" senza giornata
                self.assertEqual((cd, ca, stato), (200, 404, "in_attesa"))
            else:                              # assegnata prima: l'eliminazione è stata rifiutata
                self.assertEqual((ca, cd, stato), (200, 409, "da_confermare"))
                self.assertEqual(g["consegneIds"], [c["id"]])


class TestVarie(Base):

    def test_file_statici_solo_frontend(self):
        code, body = self.call("GET", "/index.html")
        self.assertEqual(code, 200)
        self.assertEqual(self.call("GET", "/")[0], 302)
        for p in ("/server.py", "/storage.py", "/Dockerfile", "/AGENTS.md", "/../storage.py",
                  "/js/../server.py", "/%2e%2e/server.py", "/js/inesistente.js"):
            self.assertEqual(self.call("GET", p)[0], 404, p)

    def test_endpoint_sconosciuti_e_v1_rimossi(self):
        sa = self.superadmin()
        self.assertEqual(self.call("GET", "/api/data", token=sa)[0], 404)
        self.assertEqual(self.call("POST", "/api/log", {"msg": "x"}, sa)[0], 404)
        self.assertEqual(self.call("GET", "/api/nulla", token=sa)[0], 404)

    def test_id_con_caratteri_strani(self):
        w = self.world()
        self.assertIn(self.call("DELETE", "/api/consegne/%00", token=w["a1"])[0], (400, 404))   # mai 500
        self.assertEqual(self.call("DELETE", "/api/consegne/" + "x" * 300, token=w["a1"])[0], 404)

    def test_content_length_negativo_o_enorme(self):
        # prima del fix un valore negativo faceva leggere il socket fino alla chiusura (thread bloccato)
        for cl, atteso in (("-1", 400), (str(srv.MAX_BODY + 1), 413), ("abc", 400)):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            c.putrequest("POST", "/api/auth/login")
            c.putheader("Content-Length", cl)
            c.endheaders()
            self.assertEqual(c.getresponse().status, atteso, cl)
            c.close()

    def test_header_di_sicurezza(self):
        for path in ("/index.html", "/api/ping", "/api/nulla", "/js/main.js", "/server.py", "/"):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            c.request("GET", path)
            r = c.getresponse()
            r.read()
            self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff", path)
            self.assertEqual(r.getheader("X-Frame-Options"), "DENY", path)
            self.assertEqual(r.getheader("Referrer-Policy"), "no-referrer", path)
            csp = r.getheader("Content-Security-Policy")
            self.assertIn("frame-ancestors 'none'", csp, path)
            self.assertIn("default-src 'self'", csp, path)
            c.close()
        # niente risorse esterne nel frontend (vincolo di progetto e CSP)
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        for rel in ("index.html", "css/layout.css", "css/components.css", "css/theme.css"):
            with open(os.path.join(base, rel), encoding="utf-8") as f:
                txt = f.read()
            self.assertNotIn("googleapis", txt, rel)
            self.assertNotRegex(txt, r"(src|href)=[\"']https?://", rel)

    def test_timeout_sui_socket(self):
        self.assertTrue(srv.Handler.timeout and srv.Handler.timeout > 0)

    def test_contatore_client(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        for cid in ("client-a", "client-b"):
            c.request("GET", "/api/ping", headers={"X-Client-ID": cid})
            c.getresponse().read()
        c.close()
        self.assertGreaterEqual(srv.get_connected_count(), 2)


@unittest.skipUnless(BACKEND == "json", "scenario provato sul solo backend json")
class TestAvvio(unittest.TestCase):

    def test_archivio_v1_rifiutato_con_codice_2(self):
        tmp = tempfile.mkdtemp(prefix="gc_srv_v1_")
        old = st.DATA_DIR
        try:
            with open(os.path.join(tmp, "consegne.json"), "w") as f:
                json.dump([{"id": "c1", "nome": "V1"}], f)
            st.DATA_DIR = tmp
            with self.assertRaises(SystemExit) as cm:
                srv.init_data_layer()
            self.assertEqual(cm.exception.code, 2)
            with open(os.path.join(tmp, "consegne.json")) as f:
                self.assertEqual(json.load(f), [{"id": "c1", "nome": "V1"}])   # nulla modificato
        finally:
            st.DATA_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)

    def test_archivio_vuoto_inizializzato_con_superadmin(self):
        tmp = tempfile.mkdtemp(prefix="gc_srv_new_")
        old = st.DATA_DIR
        try:
            st.DATA_DIR = tmp
            srv.init_data_layer()
            self.assertEqual([u["id"] for u in st.list_records("utenti")], ["u_superadmin"])
        finally:
            st.DATA_DIR = old
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
