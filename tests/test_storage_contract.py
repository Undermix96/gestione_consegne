"""
Suite di contratto per storage.py V2 (accesso per singolo record).

Gli STESSI test devono passare su tutti i backend: è ciò che garantisce la stessa
semantica su json / mysql / postgres.

Esecuzione (dalla radice del progetto):
    DB_BACKEND=json python -m unittest discover -s tests -v
    DB_BACKEND=postgres DB_HOST=... DB_USER=... DB_PASSWORD=... python -m unittest discover -s tests -v

ATTENZIONE: con i backend DB la suite SVUOTA le tabelle. Usare un database di test.
Solo libreria standard (nessuna dipendenza aggiuntiva).
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest

os.environ["STORAGE_ALLOW_TEST_RESET"] = "1"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import storage as st  # noqa: E402

BACKEND = st.BACKEND


# ─── fixture ──────────────────────────────────────────────────────────────────

def consegna(cid="c1", nid="n1", **over):
    """Consegna V1 completa (AGENTS.md §8) + un campo 'futuro' sconosciuto allo schema."""
    c = {
        "id": cid, "negozio_id": nid,
        "dataPrenotazione": "2026-03-22", "stato": "programmata",
        "nome": "Mario", "cognome": "Rossi", "citta": "Vicenza",
        "indirizzo": "Via Roma 1", "tel1": "+39 333 1234567", "tel2": "",
        "raee": "no",
        "articoli": [
            {"tipoConsegna": "ins_incasso", "tipo": "TV", "codice": "SONY-X90L",
             "desc": 'TV Sony 55" OLED'},
            {"tipoConsegna": "consegna", "tipo": "Frigo", "codice": "F-1", "desc": "àèìòù €"},
        ],
        "piano": "2", "noteAbitazione": "Scala stretta", "preferenzePeriodo": "Solo mattina",
        "giornoConsegna": "2026-03-25", "fasciaOraria": "9:00-12:00", "note": "",
        "campoFuturo": {"x": [1, 2, 3]},
    }
    c.update(over)
    return c

def squadra(sid="sq1", nid="n1", **over):
    s = {"id": sid, "negozio_id": nid, "nome": "Squadra A", "colorIdx": 3}
    s.update(over)
    return s

def giornata(gid="g1", nid="n1", **over):
    g = {"id": gid, "negozio_id": nid, "data": "2026-03-25", "squadra_id": f"sqg_{nid}"}
    g.update(over)
    return g

def ins_g(rec):
    """Inserisce una giornata creando prima (se serve) la sua squadra, obbligatoria."""
    sid = rec.get("squadra_id")
    if sid and st.get_record("squadre", sid) is None and st.get_record("negozi", rec["negozio_id"]) is not None:
        st.insert_record("squadre", {"id": sid, "negozio_id": rec["negozio_id"], "nome": f"Squadra {sid}"})
    return st.insert_record("giornate", rec)

def utente(uid="u1", username="mario", nid="n1", tid=None, **over):
    u = {"id": uid, "username": username, "password_hash": "a" * 64,
         "negozio_id": nid, "tipo_account_id": tid,
         "is_superadmin": False, "primo_login": False,
         "creato_da": "u_superadmin", "creato_il": "2026-06-18T10:00:00"}
    u.update(over)
    return u


class StorageContract(unittest.TestCase):

    def setUp(self):
        self._tmp = None
        if BACKEND == "json":
            self._tmp = tempfile.mkdtemp(prefix="gc_test_")
            st.DATA_DIR = self._tmp
        st.init_storage_v2()
        st._test_reset()
        st.insert_record("negozi", {"id": "n1", "nome": "Negozio 1"})
        st.insert_record("negozi", {"id": "n2", "nome": "Negozio 2"})

    def tearDown(self):
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)

    # ── round-trip e normalizzazione ───────────────────────────────────────────

    def test_roundtrip_consegna_completa(self):
        c = consegna()
        out = st.insert_record("consegne", c)
        expected = dict(c, versione=1)
        self.assertEqual(out, expected)
        self.assertEqual(st.get_record("consegne", "c1"), expected)
        self.assertEqual(st.list_records("consegne"), [expected])

    def test_roundtrip_squadra_colorIdx_camelCase(self):
        # Regressione del bug V1 sui backend SQL: color_idx al posto di colorIdx
        st.insert_record("squadre", squadra())
        got = st.get_record("squadre", "sq1")
        self.assertEqual(got["colorIdx"], 3)
        self.assertNotIn("color_idx", got)

    def test_roundtrip_senza_chiavi_snake_case_duplicate(self):
        st.insert_record("consegne", consegna())
        got = st.get_record("consegne", "c1")
        for k in ("giorno_consegna", "fascia_oraria", "data_prenotaz", "tipo_prodotto",
                  "tipo_consegna", "telefono"):
            self.assertNotIn(k, got)

    def test_roundtrip_giornata_con_consegne(self):
        st.insert_record("consegne", consegna("c1"))
        st.insert_record("consegne", consegna("c2"))
        out = ins_g(giornata(consegneIds=["c2", "c1"],
                                                    consegneCompletate={"c1": True}))
        self.assertEqual(out["consegneIds"], ["c2", "c1"])
        self.assertNotIn("consegneCompletate", out)
        self.assertEqual(st.get_record("giornate", "g1")["consegneIds"], ["c2", "c1"])

    def test_roundtrip_utente_booleani_e_null(self):
        st.insert_record("tipi_account", {"id": "t1", "nome": "Admin", "permessi": ["consegne.leggi"]})
        st.insert_record("utenti", utente(tid="t1"))
        got = st.get_record("utenti", "u1")
        self.assertIs(got["primo_login"], False)
        self.assertIs(got["is_superadmin"], False)
        sa = st.insert_record("utenti", {"id": "u_superadmin", "username": "superadmin",
                                         "password_hash": "b" * 64, "is_superadmin": True})
        self.assertIs(st.get_record("utenti", "u_superadmin")["is_superadmin"], True)
        self.assertNotIn("negozio_id", sa)
        self.assertNotIn("tipo_account_id", sa)

    def test_roundtrip_tipo_account_permessi_lista(self):
        perms = ["consegne.leggi", "consegne.scrivi", "stampa.pdf"]
        st.insert_record("tipi_account", {"id": "t1", "nome": "Operatore", "permessi": perms})
        self.assertEqual(st.get_record("tipi_account", "t1")["permessi"], perms)

    def test_default_applicati(self):
        c = st.insert_record("consegne", {"id": "c1", "negozio_id": "n1", "nome": "A"})
        self.assertEqual(c["stato"], "in_attesa")
        s = st.insert_record("squadre", {"id": "s1", "negozio_id": "n1", "nome": "S"})
        self.assertEqual(s["colorIdx"], 0)

    def test_none_non_viene_memorizzato(self):
        c = st.insert_record("consegne", consegna(note=None, tel2=None))
        self.assertNotIn("note", c)
        self.assertNotIn("tel2", st.get_record("consegne", "c1"))

    def test_stringhe_unicode_e_vuote(self):
        st.insert_record("consegne", consegna(nome="Ünïcödé 日本 🚚", note=""))
        got = st.get_record("consegne", "c1")
        self.assertEqual(got["nome"], "Ünïcödé 日本 🚚")
        self.assertEqual(got["note"], "")

    def test_get_inesistente_none_e_ordine_inserimento(self):
        self.assertIsNone(st.get_record("consegne", "nope"))
        for i in (5, 1, 9, 3, 7, 2):
            st.insert_record("consegne", consegna(f"c{i}"))
        self.assertEqual([c["id"] for c in st.list_records("consegne")],
                         ["c5", "c1", "c9", "c3", "c7", "c2"])

    # ── versione / optimistic locking ──────────────────────────────────────────

    def test_versione_iniziale_ignora_valore_fornito(self):
        c = st.insert_record("consegne", consegna(versione=99))
        self.assertEqual(c["versione"], 1)

    def test_update_merge_e_incremento_versione(self):
        st.insert_record("consegne", consegna())
        out = st.update_record("consegne", "c1", {"note": "Nuova", "stato": "completata"})
        self.assertEqual(out["versione"], 2)
        self.assertEqual(out["note"], "Nuova")
        self.assertEqual(out["nome"], "Mario")            # invariato
        self.assertEqual(out["campoFuturo"], {"x": [1, 2, 3]})
        self.assertEqual(st.get_record("consegne", "c1"), out)

    def test_update_none_rimuove_il_campo(self):
        st.insert_record("consegne", consegna())
        out = st.update_record("consegne", "c1", {"piano": None})
        self.assertNotIn("piano", out)
        self.assertNotIn("piano", st.get_record("consegne", "c1"))

    def test_occ_versione_corretta_ok_e_errata_conflict(self):
        st.insert_record("consegne", consegna())
        st.update_record("consegne", "c1", {"note": "a"}, expected_versione=1)       # ok → v2
        with self.assertRaises(st.ConflictError):
            st.update_record("consegne", "c1", {"note": "b"}, expected_versione=1)    # stale
        got = st.get_record("consegne", "c1")
        self.assertEqual((got["note"], got["versione"]), ("a", 2))                   # invariato

    def test_occ_atomico_sotto_concorrenza(self):
        # Si rallenta il punto tra "leggo la versione" e "scrivo": senza un vero lock
        # (lock di riga su SQL, lock del file su json) tutti i thread passerebbero il controllo.
        original = st._apply_changes

        def slow_apply(*args, **kwargs):
            time.sleep(0.05)
            return original(*args, **kwargs)

        st._apply_changes = slow_apply
        try:
            st.insert_record("consegne", consegna())
            n = 12
            barrier = threading.Barrier(n)
            results = []
            lock = threading.Lock()

            def worker(i):
                barrier.wait()
                try:
                    st.update_record("consegne", "c1", {"note": f"w{i}"}, expected_versione=1)
                    r = "ok"
                except st.ConflictError:
                    r = "conflict"
                with lock:
                    results.append(r)

            ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        finally:
            st._apply_changes = original
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("conflict"), n - 1)
        self.assertEqual(st.get_record("consegne", "c1")["versione"], 2)

    def test_update_concorrenti_senza_versione_si_serializzano(self):
        # Senza expected_versione ogni update vince, ma la versione deve contarli TUTTI (nessun update perso)
        original = st._apply_changes
        st._apply_changes = lambda *a, **k: (time.sleep(0.02), original(*a, **k))[1]
        try:
            st.insert_record("consegne", consegna())
            n = 8
            ts = [threading.Thread(target=lambda i=i: st.update_record("consegne", "c1", {"note": f"w{i}"}))
                  for i in range(n)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        finally:
            st._apply_changes = original
        self.assertEqual(st.get_record("consegne", "c1")["versione"], 1 + n)

    def test_update_campi_non_modificabili(self):
        st.insert_record("consegne", consegna())
        for bad in ({"id": "x"}, {"versione": 5}, {"negozio_id": "n2"}):
            with self.assertRaises(ValueError):
                st.update_record("consegne", "c1", bad)
        ins_g(giornata())
        with self.assertRaises(ValueError):
            st.update_record("giornate", "g1", {"consegneIds": ["c1"]})

    def test_update_inesistente_e_campo_obbligatorio(self):
        with self.assertRaises(st.NotFoundError):
            st.update_record("consegne", "nope", {"note": "x"})
        st.insert_record("squadre", squadra())
        with self.assertRaises(ValueError):
            st.update_record("squadre", "sq1", {"nome": None})
        self.assertEqual(st.get_record("squadre", "sq1")["nome"], "Squadra A")

    # ── validazione input ──────────────────────────────────────────────────────

    def test_input_non_validi(self):
        with self.assertRaises(ValueError):
            st.list_records("inesistente")
        with self.assertRaises(ValueError):
            st.insert_record("consegne", {"negozio_id": "n1"})                # manca id
        with self.assertRaises(ValueError):
            st.insert_record("consegne", {"id": "c1"})                        # manca negozio_id
        with self.assertRaises(ValueError):
            st.insert_record("squadre", {"id": "s", "negozio_id": "n1"})      # manca nome
        with self.assertRaises(ValueError):
            st.update_record("consegne", "c1", {})

    # ── unicità ────────────────────────────────────────────────────────────────

    def test_id_duplicato(self):
        st.insert_record("consegne", consegna())
        with self.assertRaises(st.DuplicateError):
            st.insert_record("consegne", consegna())

    def test_username_univoco_case_insensitive(self):
        st.insert_record("utenti", utente("u1", "Mario"))
        for dup in ("mario", "MARIO", "Mario"):
            with self.assertRaises(st.DuplicateError):
                st.insert_record("utenti", utente("u2", dup))
        self.assertEqual(len(st.list_records("utenti")), 1)

    def test_username_update_in_conflitto(self):
        st.insert_record("utenti", utente("u1", "mario"))
        st.insert_record("utenti", utente("u2", "luca"))
        with self.assertRaises(st.DuplicateError):
            st.update_record("utenti", "u2", {"username": "MARIO"})
        st.update_record("utenti", "u1", {"username": "MARIO"})               # sé stesso: ok

    def test_filtro_username_case_insensitive(self):
        st.insert_record("utenti", utente("u1", "Mario"))
        got = st.list_records("utenti", {"username": "mARIO"})
        self.assertEqual([u["id"] for u in got], ["u1"])

    def test_nome_tipo_account_univoco(self):
        st.insert_record("tipi_account", {"id": "t1", "nome": "Admin", "permessi": []})
        with self.assertRaises(st.DuplicateError):
            st.insert_record("tipi_account", {"id": "t2", "nome": "Admin", "permessi": []})

    # ── integrità referenziale ─────────────────────────────────────────────────

    def test_fk_negozio_inesistente(self):
        with self.assertRaises(st.IntegrityError):
            st.insert_record("consegne", consegna(nid="n_nope"))
        with self.assertRaises(st.IntegrityError):
            st.insert_record("squadre", squadra(nid="n_nope"))
        with self.assertRaises(st.IntegrityError):
            ins_g(giornata(nid="n_nope"))

    def test_giornata_richiede_squadra_esistente_dello_stesso_negozio(self):
        with self.assertRaises(ValueError):                                   # obbligatoria
            st.insert_record("giornate", {"id": "g1", "negozio_id": "n1", "data": "2026-03-25"})
        with self.assertRaises(st.IntegrityError):                            # inesistente
            st.insert_record("giornate", giornata(squadra_id="sq_nope"))
        st.insert_record("squadre", squadra("sq_n2", "n2"))
        with self.assertRaises(ValueError):                                   # di un altro negozio
            st.insert_record("giornate", giornata(squadra_id="sq_n2"))
        self.assertEqual(st.list_records("giornate"), [])
        ins_g(giornata())
        with self.assertRaises(ValueError):                                   # non si può togliere
            st.update_record("giornate", "g1", {"squadra_id": None})
        with self.assertRaises(st.IntegrityError):                            # né puntare a una squadra inesistente
            st.update_record("giornate", "g1", {"squadra_id": "sq_nope"})
        with self.assertRaises(ValueError):                                   # né a una di un altro negozio
            st.update_record("giornate", "g1", {"squadra_id": "sq_n2"})
        st.insert_record("squadre", squadra("sq_b", "n1", nome="B"))
        self.assertEqual(st.update_record("giornate", "g1", {"squadra_id": "sq_b"})["squadra_id"], "sq_b")
        self.assertEqual(st.get_record("giornate", "g1")["squadra_id"], "sq_b")
        self.assertEqual(st.get_record("giornate", "g1")["versione"], 2)

    def test_squadra_con_giornate_non_eliminabile(self):
        ins_g(giornata())
        with self.assertRaises(st.IntegrityError):
            st.delete_record("squadre", "sqg_n1")
        self.assertIsNotNone(st.get_record("squadre", "sqg_n1"))
        self.assertEqual(st.get_record("giornate", "g1")["squadra_id"], "sqg_n1")
        st.insert_record("squadre", squadra("libera", "n1", nome="Libera"))
        self.assertTrue(st.delete_record("squadre", "libera"))                # senza giornate si elimina
        self.assertTrue(st.delete_record("giornate", "g1"))
        self.assertTrue(st.delete_record("squadre", "sqg_n1"))                # dopo le giornate, anche questa

    def test_filtro_per_squadra_id(self):
        ins_g(giornata("g1"))
        st.insert_record("squadre", squadra("sq_b", "n1", nome="B"))
        st.insert_record("giornate", giornata("g2", squadra_id="sq_b"))
        self.assertEqual([g["id"] for g in st.list_records("giornate", {"squadra_id": "sq_b"})], ["g2"])
        self.assertEqual(st.list_records("giornate", {"squadra_id": "nessuna"}), [])

    def test_fk_utente(self):
        with self.assertRaises(st.IntegrityError):
            st.insert_record("utenti", utente(tid="t_nope"))
        with self.assertRaises(st.IntegrityError):
            st.insert_record("utenti", utente(nid="n_nope"))
        st.insert_record("utenti", {"id": "sa", "username": "sa", "password_hash": "c" * 64})  # null ok
        with self.assertRaises(st.IntegrityError):
            st.update_record("utenti", "sa", {"tipo_account_id": "t_nope"})

    def test_restrict_negozio_e_tipo_account(self):
        st.insert_record("tipi_account", {"id": "t1", "nome": "Admin", "permessi": []})
        st.insert_record("utenti", utente(tid="t1"))
        with self.assertRaises(st.IntegrityError):
            st.delete_record("negozi", "n1")                                  # ha utenti
        with self.assertRaises(st.IntegrityError):
            st.delete_record("tipi_account", "t1")                            # ha utenti
        st.delete_record("utenti", "u1")
        self.assertTrue(st.delete_record("tipi_account", "t1"))
        st.insert_record("consegne", consegna())
        with self.assertRaises(st.IntegrityError):
            st.delete_record("negozi", "n1")                                  # ha consegne
        st.delete_record("consegne", "c1")
        self.assertTrue(st.delete_record("negozi", "n1"))

    def test_delete_inesistente_false(self):
        self.assertFalse(st.delete_record("consegne", "nope"))

    def test_delete_consegna_la_toglie_dalle_giornate(self):
        for c in ("c1", "c2", "c3"):
            st.insert_record("consegne", consegna(c))
        ins_g(giornata("g1", consegneIds=["c1", "c2", "c3"]))
        ins_g(giornata("g2", consegneIds=["c2"]))
        self.assertTrue(st.delete_record("consegne", "c2"))
        self.assertEqual(st.get_record("giornate", "g1")["consegneIds"], ["c1", "c3"])
        self.assertEqual(st.get_record("giornate", "g2")["consegneIds"], [])

    def test_delete_giornata_non_elimina_le_consegne(self):
        st.insert_record("consegne", consegna("c1"))
        ins_g(giornata(consegneIds=["c1"]))
        self.assertTrue(st.delete_record("giornate", "g1"))
        self.assertIsNotNone(st.get_record("consegne", "c1"))

    # ── isolamento per negozio ─────────────────────────────────────────────────

    def test_isolamento_per_negozio(self):
        st.insert_record("consegne", consegna("c1", "n1"))
        st.insert_record("consegne", consegna("c2", "n2"))
        st.insert_record("squadre", squadra("s1", "n1"))
        st.insert_record("squadre", squadra("s2", "n2"))
        self.assertEqual([c["id"] for c in st.list_records("consegne", {"negozio_id": "n1"})], ["c1"])
        self.assertEqual([c["id"] for c in st.list_records("consegne", {"negozio_id": "n2"})], ["c2"])
        self.assertEqual([s["id"] for s in st.list_records("squadre", {"negozio_id": "n2"})], ["s2"])
        self.assertEqual(st.list_records("consegne", {"negozio_id": "n3"}), [])
        # filtri combinati
        self.assertEqual(len(st.list_records("consegne", {"negozio_id": "n1", "stato": "programmata"})), 1)
        self.assertEqual(len(st.list_records("consegne", {"negozio_id": "n1", "stato": "annullata"})), 0)

    # ── giornate ↔ consegne ────────────────────────────────────────────────────

    def test_giornata_assegna_ordine_e_idempotenza(self):
        for c in ("c1", "c2", "c3"):
            st.insert_record("consegne", consegna(c))
        ins_g(giornata())
        g = st.giornata_assegna("g1", ["c2", "c1"])
        self.assertEqual(g["consegneIds"], ["c2", "c1"])
        g = st.giornata_assegna("g1", ["c1", "c3"])                           # c1 già presente
        self.assertEqual(g["consegneIds"], ["c2", "c1", "c3"])
        self.assertEqual(st.get_record("giornate", "g1")["consegneIds"], ["c2", "c1", "c3"])

    def test_giornata_ops_non_toccano_versione(self):
        for c in ("c1", "c2"):
            st.insert_record("consegne", consegna(c))
        ins_g(giornata())
        st.giornata_assegna("g1", ["c1", "c2"])
        st.giornata_riordina("g1", ["c2", "c1"])
        g = st.giornata_rimuovi("g1", "c1")
        self.assertEqual(g["versione"], 1)

    def test_giornata_assegna_errori(self):
        st.insert_record("consegne", consegna("c1", "n1"))
        st.insert_record("consegne", consegna("cx", "n2"))
        ins_g(giornata())
        with self.assertRaises(st.NotFoundError):
            st.giornata_assegna("g1", ["c_nope"])
        with self.assertRaises(ValueError):                                   # altro negozio
            st.giornata_assegna("g1", ["cx"])
        with self.assertRaises(st.NotFoundError):
            st.giornata_assegna("g_nope", ["c1"])
        self.assertEqual(st.get_record("giornate", "g1")["consegneIds"], [])  # nulla è cambiato

    def test_giornata_assegna_atomico_se_una_invalida(self):
        st.insert_record("consegne", consegna("c1"))
        ins_g(giornata())
        with self.assertRaises(st.NotFoundError):
            st.giornata_assegna("g1", ["c1", "c_nope"])
        self.assertEqual(st.get_record("giornate", "g1")["consegneIds"], [])

    def test_giornata_rimuovi(self):
        st.insert_record("consegne", consegna("c1"))
        ins_g(giornata(consegneIds=["c1"]))
        self.assertEqual(st.giornata_rimuovi("g1", "c1")["consegneIds"], [])
        self.assertEqual(st.giornata_rimuovi("g1", "c1")["consegneIds"], [])  # idempotente
        self.assertIsNotNone(st.get_record("consegne", "c1"))
        with self.assertRaises(st.NotFoundError):
            st.giornata_rimuovi("g_nope", "c1")

    def test_giornata_riordina(self):
        for c in ("c1", "c2", "c3"):
            st.insert_record("consegne", consegna(c))
        ins_g(giornata(consegneIds=["c1", "c2", "c3"]))
        self.assertEqual(st.giornata_riordina("g1", ["c3", "c1", "c2"])["consegneIds"], ["c3", "c1", "c2"])
        self.assertEqual(st.get_record("giornate", "g1")["consegneIds"], ["c3", "c1", "c2"])
        for bad in (["c1", "c2"], ["c1", "c2", "c3", "c3"], ["c1", "c2", "cx"], []):
            with self.assertRaises(ValueError):
                st.giornata_riordina("g1", bad)
        self.assertEqual(st.get_record("giornate", "g1")["consegneIds"], ["c3", "c1", "c2"])

    def test_insert_giornata_consegne_invalide(self):
        with self.assertRaises(st.NotFoundError):
            ins_g(giornata(consegneIds=["c_nope"]))
        self.assertIsNone(st.get_record("giornate", "g1"))
        with self.assertRaises(ValueError):
            ins_g(giornata(consegneIds=["a", "a"]))

    # ── insert_records ─────────────────────────────────────────────────────────

    def test_insert_records_ok_e_ordine(self):
        out = st.insert_records("consegne", [consegna("c2"), consegna("c1"), consegna("c3")])
        self.assertEqual([c["id"] for c in out], ["c2", "c1", "c3"])
        self.assertEqual([c["id"] for c in st.list_records("consegne")], ["c2", "c1", "c3"])
        self.assertEqual(st.insert_records("consegne", []), [])

    def test_insert_records_tutto_o_niente(self):
        st.insert_record("consegne", consegna("c0"))
        for bad_batch in ([consegna("c1"), consegna("c0")],                    # duplicato nel DB
                          [consegna("c1"), consegna("c1")],                    # duplicato nel batch
                          [consegna("c1"), consegna("c2", nid="n_nope")]):     # FK
            with self.assertRaises(st.StorageError):
                st.insert_records("consegne", bad_batch)
            self.assertEqual([c["id"] for c in st.list_records("consegne")], ["c0"])


    # ── tipi, lunghezze, filtri (stesse regole su tutti i backend) ────────────

    def test_campi_con_default_non_rimovibili(self):
        st.insert_record("consegne", consegna())
        st.insert_record("squadre", squadra())
        st.insert_record("utenti", utente())
        for coll, rid, field in (("consegne", "c1", "stato"), ("squadre", "sq1", "colorIdx"),
                                 ("utenti", "u1", "primo_login"), ("utenti", "u1", "is_superadmin")):
            with self.assertRaises(ValueError):
                st.update_record(coll, rid, {field: None})
        self.assertEqual(st.get_record("consegne", "c1")["versione"], 1)      # nulla è cambiato

    def test_tipi_di_dato_errati(self):
        bad = [("consegne", consegna(nome=5)), ("consegne", consegna(articoli={"a": 1})),
               ("squadre", squadra(colorIdx="3")), ("squadre", squadra(colorIdx=True)),
               ("utenti", utente(primo_login="si")), ("utenti", utente(is_superadmin=1)),
               ("tipi_account", {"id": "t", "nome": "x", "permessi": "consegne.leggi"}),
               ("giornate", giornata(data=20260325))]
        for coll, rec in bad:
            with self.assertRaises(ValueError, msg=f"{coll} {rec}"):
                st.insert_record(coll, rec)
        st.insert_record("squadre", squadra())
        with self.assertRaises(ValueError):
            st.update_record("squadre", "sq1", {"colorIdx": "7"})
        self.assertEqual(st.get_record("squadre", "sq1")["colorIdx"], 3)

    def test_lunghezze_e_caratteri_nul(self):
        for coll, rec in (("consegne", consegna(cid="x" * 37)),
                          ("utenti", utente(username="u" * 151)),
                          ("tipi_account", {"id": "t", "nome": "n" * 256, "permessi": []}),
                          ("consegne", consegna(nome="a\x00b")),
                          ("consegne", consegna(campoFuturo={"k": ["ok", "x\x00y"]}))):
            with self.assertRaises(ValueError, msg=coll):
                st.insert_record(coll, rec)
        st.insert_record("consegne", consegna(nome="n" * 5000))               # testo libero: nessun limite
        self.assertEqual(len(st.get_record("consegne", "c1")["nome"]), 5000)
        st.insert_record("utenti", utente("u1", "u" * 150))                   # limite incluso
        st.insert_record("consegne", consegna("c" * 36))

    def test_filtri_non_supportati(self):
        for coll, flt in (("consegne", {"tel1": "x"}), ("consegne", {"articoli": []}),
                          ("squadre", {"colorIdx": "3"}), ("consegne", {"versione": "1"}),
                          ("negozi", {"versione": 1}), ("consegne", {"stato": 5})):
            with self.assertRaises(ValueError, msg=f"{coll} {flt}"):
                st.list_records(coll, flt)

    def test_filtro_none_trova_campo_assente(self):
        st.insert_record("consegne", consegna("c1", note=None))
        st.insert_record("consegne", consegna("c2", note="x"))
        self.assertEqual([c["id"] for c in st.list_records("consegne", {"note": None})], ["c1"])
        self.assertEqual([c["id"] for c in st.list_records("consegne", {"note": "x"})], ["c2"])
        self.assertEqual([c["id"] for c in st.list_records("consegne", {"id": "c2"})], ["c2"])
        self.assertEqual([c["id"] for c in st.list_records("consegne", {"versione": 1})], ["c1", "c2"])

    def test_filtri_esatti_maiuscole_e_accenti(self):
        st.insert_record("consegne", consegna("c1", citta="Vicenza"))
        st.insert_record("consegne", consegna("c2", citta="vicenza"))
        st.insert_record("consegne", consegna("c3", citta="Pádova"))
        self.assertEqual([c["id"] for c in st.list_records("consegne", {"citta": "Vicenza"})], ["c1"])
        self.assertEqual([c["id"] for c in st.list_records("consegne", {"citta": "Padova"})], [])

    def test_username_ci_non_confonde_accenti(self):
        st.insert_record("utenti", utente("u1", "mario"))
        st.insert_record("utenti", utente("u2", "márió"))                     # diverso: nessun conflitto
        self.assertEqual([u["id"] for u in st.list_records("utenti", {"username": "MÁRIÓ"})], ["u2"])

    def test_username_casefold_che_si_allunga(self):
        st.insert_record("utenti", utente("u1", "ß" * 75))                    # casefold → "ss" * 75
        with self.assertRaises(st.DuplicateError):
            st.insert_record("utenti", utente("u2", "SS" * 75))
        st.insert_record("utenti", utente("u3", "ß" * 150))                   # casefold lungo 300: ammesso
        self.assertEqual([u["id"] for u in st.list_records("utenti", {"username": "SS" * 150})], ["u3"])

    def test_spazi_finali_e_confronti_esatti(self):
        st.insert_record("utenti", utente("u1", "mario"))
        st.insert_record("utenti", utente("u2", "mario "))                    # diverso: nessun conflitto
        self.assertEqual([u["id"] for u in st.list_records("utenti", {"username": "mario "})], ["u2"])
        st.insert_record("consegne", consegna("c1", citta="Vicenza"))
        self.assertEqual(st.list_records("consegne", {"citta": "Vicenza "}), [])

    def test_testo_molto_lungo(self):
        big = "x" * 100_000                                                    # oltre i 64 KB di un TEXT MySQL
        st.insert_record("consegne", consegna(note=big))
        self.assertEqual(st.get_record("consegne", "c1")["note"], big)

    def test_nome_tipo_account_case_sensitive(self):
        st.insert_record("tipi_account", {"id": "t1", "nome": "Admin", "permessi": []})
        st.insert_record("tipi_account", {"id": "t2", "nome": "admin", "permessi": []})   # ammesso
        self.assertEqual(len(st.list_records("tipi_account")), 2)

    def test_valori_json_annidati_e_numeri(self):
        extra = {"n": 2 ** 40, "neg": -7, "f": 1.5, "b": True, "nul": None, "lista": [1, "a", None],
                 "vuoto": {}, "emoji": "🚚"}
        st.insert_record("consegne", consegna(campoFuturo=extra))
        self.assertEqual(st.get_record("consegne", "c1")["campoFuturo"], extra)
        st.insert_record("consegne", consegna("c2", articoli=[]))
        self.assertEqual(st.get_record("consegne", "c2")["articoli"], [])

    def test_lista_vuota_e_chiavi_riservate_nel_campo_extra(self):
        st.insert_record("consegne", consegna(extra="x", seq=5, id_ext=1))     # nomi ambigui con le colonne
        got = st.get_record("consegne", "c1")
        self.assertEqual((got["extra"], got["seq"], got["id_ext"]), ("x", 5, 1))

    def test_stesso_record_dopo_piu_update(self):
        st.insert_record("consegne", consegna())
        for i in range(5):
            st.update_record("consegne", "c1", {"note": f"n{i}", "campoFuturo": {"i": i}})
        got = st.get_record("consegne", "c1")
        self.assertEqual((got["note"], got["campoFuturo"], got["versione"]), ("n4", {"i": 4}, 6))
        self.assertEqual(st.list_records("consegne"), [got])

    def test_ordine_di_inserimento_stabile_dopo_update(self):
        for i in range(1, 7):
            st.insert_record("consegne", consegna(f"c{i}"))
        for cid in ("c1", "c1", "c3", "c1"):
            st.update_record("consegne", cid, {"note": "x"})
        self.assertEqual([c["id"] for c in st.list_records("consegne")],
                         ["c1", "c2", "c3", "c4", "c5", "c6"])
        st.insert_record("squadre", squadra("s1"))
        st.insert_record("squadre", squadra("s2", nome="B"))
        st.update_record("squadre", "s1", {"nome": "A2"})
        self.assertEqual([s["id"] for s in st.list_records("squadre")], ["s1", "s2"])

    def test_giornata_ordine_dopo_rimozione_e_nuova_assegnazione(self):
        for c in ("c1", "c2", "c3", "c4"):
            st.insert_record("consegne", consegna(c))
        ins_g(giornata(consegneIds=["c1", "c2", "c3"]))
        st.giornata_rimuovi("g1", "c2")
        g = st.giornata_assegna("g1", ["c4", "c2"])
        self.assertEqual(g["consegneIds"], ["c1", "c3", "c4", "c2"])
        self.assertEqual(st.list_records("giornate")[0]["consegneIds"], ["c1", "c3", "c4", "c2"])

    def test_list_giornate_con_molte_consegne_e_filtri(self):
        ids = [f"c{i:03d}" for i in range(60)]
        st.insert_records("consegne", [consegna(i) for i in ids])
        ins_g(giornata("g1", consegneIds=ids))
        ins_g(giornata("g2", nid="n2"))
        self.assertEqual(st.get_record("giornate", "g1")["consegneIds"], ids)
        self.assertEqual([g["id"] for g in st.list_records("giornate", {"negozio_id": "n2"})], ["g2"])
        self.assertEqual(st.list_records("giornate", {"negozio_id": "n2"})[0]["consegneIds"], [])

    # ── meta ───────────────────────────────────────────────────────────────────

    def test_meta(self):
        self.assertIsNone(st.get_meta("chiave_prova"))
        self.assertEqual(st.get_meta("chiave_prova", 0), 0)
        st.set_meta("chiave_prova", 2)
        self.assertEqual(st.get_meta("chiave_prova"), 2)
        st.set_meta("chiave_prova", 3)
        self.assertEqual(st.get_meta("chiave_prova"), 3)
        st.set_meta("migrazione", {"ok": True, "n": [1, 2]})
        self.assertEqual(st.get_meta("migrazione"), {"ok": True, "n": [1, 2]})
        st.set_meta("nullo", None)                                            # null ≠ chiave mancante
        self.assertIsNone(st.get_meta("nullo", "default"))
        st.set_meta("testo", "abc")
        self.assertEqual(st.get_meta("testo"), "abc")

    def test_marcatore_di_schema_presente_e_reset_lo_conserva(self):
        self.assertEqual(st.get_meta("schema_version"), st.SCHEMA_VERSION)
        st.set_meta("altro", 1)
        st._test_reset()
        self.assertEqual(st.get_meta("schema_version"), st.SCHEMA_VERSION)
        self.assertIsNone(st.get_meta("altro"))


# ─── controllo dello schema all'avvio (passo 1d) ──────────────────────────────

_SQL_TABLES = ["giornata_consegne", "giornate", "consegne", "squadre", "utenti",
               "tipi_account", "negozi", "meta"]


def _raw(statements):
    """SQL grezzo sul database di test (solo backend SQL). Rifiuta DB che non finiscono per _test."""
    assert os.environ.get("DB_NAME", "").endswith("_test")
    conn = st._pg_connect() if BACKEND == "postgres" else st._mysql_connect()
    try:
        cur = conn.cursor()
        out = None
        for q in statements:
            cur.execute(q)
            if cur.description:
                out = cur.fetchall()
        conn.commit()
        return out
    finally:
        conn.close()


def _drop_all_sql():
    drop = "DROP TABLE IF EXISTS " + ", ".join(_SQL_TABLES)
    if BACKEND == "postgres":
        return [drop + " CASCADE"]
    return ["SET FOREIGN_KEY_CHECKS=0", drop, "SET FOREIGN_KEY_CHECKS=1"]


class _GuardBase(unittest.TestCase):
    """Base (senza test): preparazione degli stati di partenza e confronti per i test dello schema."""

    V1_DATA = {
        "consegne": [{"id": "c1", "nome": "Mario", "stato": "in_attesa", "articoli": []}],
        "giornate": [{"id": "g1", "data": "2026-01-01", "squadra": "S", "consegneIds": ["c1"]}],
        "squadre": [{"id": "s1", "nome": "S", "colorIdx": 2}],
    }

    def setUp(self):
        self.tmp = None
        st._v2 = None
        if BACKEND == "json":
            self.tmp = tempfile.mkdtemp(prefix="gc_test_")
            st.DATA_DIR = self.tmp
        else:
            _raw(_drop_all_sql())

    def tearDown(self):
        st._v2 = None
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
        else:
            _raw(_drop_all_sql())
            st.init_storage_v2()                                              # schema V2 pulito per le classi successive

    # ── stati di partenza e confronti ─────────────────────────────────────────
    def _v1_state(self, with_data=True):
        """Archivio V1 autentico: file scritti a mano (json) o funzioni V1 reali (SQL)."""
        if BACKEND == "json":
            for name, rows in self.V1_DATA.items():
                with open(os.path.join(self.tmp, f"{name}.json"), "w", encoding="utf-8") as f:
                    json.dump(rows if with_data else [], f)
        else:
            st.init_storage()
            if with_data:
                st.write_data(self.V1_DATA)

    def _snapshot(self):
        if BACKEND == "json":
            snap = {}
            for root, dirs, files in os.walk(self.tmp):
                snap[os.path.relpath(root, self.tmp)] = "dir"
                for fn in files:
                    with open(os.path.join(root, fn), "rb") as f:
                        snap[os.path.relpath(os.path.join(root, fn), self.tmp)] = f.read()
            return snap
        expr = "current_schema()" if BACKEND == "postgres" else "DATABASE()"
        cols = _raw([f"SELECT table_name, column_name FROM information_schema.columns "
                     f"WHERE table_schema = {expr} ORDER BY 1, 2"])
        tables = sorted({r[0] if isinstance(r[0], str) else r[0].decode() for r in cols})
        counts = {t: _raw([f"SELECT COUNT(*) FROM {t}"])[0][0] for t in tables}
        return [(str(a), str(b)) for a, b in cols], counts

    def _remove_marker(self):
        if BACKEND == "json":
            with open(os.path.join(self.tmp, "meta.json"), "w") as f:
                json.dump({}, f)
        else:
            _raw(["DELETE FROM meta WHERE chiave = 'schema_version'"])

    def _assert_rifiuta(self, *frammenti):
        before = self._snapshot()
        with self.assertRaises(st.SchemaError) as cm:
            st.init_storage_v2()
        for fr in frammenti:
            self.assertIn(fr, str(cm.exception))
        self.assertEqual(self._snapshot(), before, "l'archivio è stato modificato")
        with self.assertRaises(st.StorageError):                              # nessun backend rimasto attivo
            st.list_records("negozi")
        return str(cm.exception)


class SchemaGuard(_GuardBase):
    """init_storage_v2() deve rifiutare, senza modificare nulla, ciò che non è uno schema V2 valido.
    Casi comuni a tutti i backend."""

    def test_archivio_vuoto_viene_inizializzato_e_marcato(self):
        st.init_storage_v2()
        self.assertEqual(st.get_meta("schema_version"), st.SCHEMA_VERSION)
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        self.assertEqual(st.get_record("negozi", "n1")["nome"], "N1")

    def test_riavvio_su_archivio_v2_valido_non_perde_dati(self):
        st.init_storage_v2()
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        for _ in range(3):
            st.init_storage_v2()
        self.assertEqual([n["id"] for n in st.list_records("negozi")], ["n1"])
        self.assertEqual(st.get_meta("schema_version"), st.SCHEMA_VERSION)

    def test_dati_v1_rifiutati_senza_modificare_nulla(self):
        self._v1_state()
        msg = self._assert_rifiuta("migrate.py")
        self.assertIn("V1", msg)
        if BACKEND != "json":
            self.assertEqual(st.read_data()["consegne"][0]["id"], "c1")       # i dati V1 sono intatti

    def test_marcatore_assente_con_dati_v2_rifiutato(self):
        st.init_storage_v2()
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        self._remove_marker()
        self._assert_rifiuta("marcatore")

    def test_versione_di_schema_sconosciuta_rifiutata(self):
        st.init_storage_v2()
        st.set_meta("schema_version", 3)
        self._assert_rifiuta("3", "non supportata")

    def test_migrazione_in_corso_blocca_l_avvio(self):
        st.init_storage_v2()
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        st.set_meta("migrazione_in_corso", True)
        self._assert_rifiuta("migrazione", "migrate.py")
        st.init_storage_v2(ignore_migration=True)                             # riservato a migrate.py
        self.assertEqual(st.get_record("negozi", "n1")["nome"], "N1")
        st.set_meta("migrazione_in_corso", False)
        st.init_storage_v2()                                                  # flag spento: si parte

    def test_dopo_un_errore_di_avvio_nessun_backend_resta_attivo(self):
        st.init_storage_v2()
        st.set_meta("schema_version", 99)
        with self.assertRaises(st.SchemaError):
            st.init_storage_v2()
        with self.assertRaises(st.StorageError):
            st.insert_record("negozi", {"id": "n1", "nome": "N1"})

    def test_schema_error_e_uno_storage_error(self):
        self.assertTrue(issubclass(st.SchemaError, st.StorageError))



@unittest.skipUnless(BACKEND == "json", "specifico del backend json")
class SchemaGuardJson(_GuardBase):

    def test_giornate_con_vecchio_campo_squadra_rifiutate(self):
        # archivio V2 di un'edizione precedente: la squadra era un nome, non un riferimento
        st.init_storage_v2()
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        path = os.path.join(st.DATA_DIR, "giornate.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([{"id": "g1", "negozio_id": "n1", "data": "2026-01-01", "squadra": "A",
                        "consegneIds": [], "versione": 1}], f)
        msg = self._assert_rifiuta("squadra_id", "g1")
        self.assertIn("cartella dati nuova", msg)

    def test_file_v1_vuoti_equivalgono_ad_archivio_vuoto(self):
        self._v1_state(with_data=False)
        st.init_storage_v2()
        self.assertEqual(st.get_meta("schema_version"), st.SCHEMA_VERSION)

    def test_meta_corrotto_e_un_errore_di_storage_e_non_viene_toccato(self):
        with open(os.path.join(self.tmp, "meta.json"), "w") as f:
            f.write("{ non json")
        before = self._snapshot()
        with self.assertLogs(st.log, level="ERROR"):
            with self.assertRaises(st.StorageError) as cm:
                st.init_storage_v2()
        self.assertNotIsInstance(cm.exception, st.SchemaError)
        self.assertEqual(self._snapshot(), before)

    def test_collezione_v2_mancante_viene_ricreata_vuota(self):
        st.init_storage_v2()
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        os.remove(os.path.join(self.tmp, "squadre.json"))
        st.init_storage_v2()
        self.assertEqual(st.list_records("squadre"), [])
        self.assertEqual(len(st.list_records("negozi")), 1)


@unittest.skipIf(BACKEND == "json", "specifico dei backend SQL")
class SchemaGuardSql(_GuardBase):

    def test_tabelle_v1_vuote_rifiutate(self):
        self._v1_state(with_data=False)                                       # decisione: nessuna eccezione
        self._assert_rifiuta("V1", "database nuovo")

    def test_tabelle_v1_con_dati_indicano_le_righe(self):
        self._v1_state()
        msg = self._assert_rifiuta("V1")
        self.assertIn("consegne: 1 righe", msg)

    def test_colonna_mancante_rifiutata(self):
        st.init_storage_v2()
        _raw(["ALTER TABLE consegne DROP COLUMN note"])
        self._assert_rifiuta("consegne", "mancano", "note")

    def test_colonna_in_piu_rifiutata(self):
        st.init_storage_v2()
        _raw(["ALTER TABLE squadre ADD COLUMN colore_extra INTEGER"])
        self._assert_rifiuta("squadre", "in più", "colore_extra")

    def test_tabella_mancante_rifiutata(self):
        st.init_storage_v2()
        _raw(["DROP TABLE giornata_consegne"])
        self._assert_rifiuta("incompleto", "giornata_consegne")

    def test_tabella_meta_mancante_rifiutata(self):
        st.init_storage_v2()
        _raw(["DROP TABLE meta"])
        self._assert_rifiuta("V1 o di uno schema sconosciuto")


@unittest.skipIf(BACKEND == "json", "specifico dei backend SQL")
class SqlSpecific(unittest.TestCase):

    def setUp(self):
        st.init_storage_v2()
        st._test_reset()

    def test_init_idempotente_non_perde_dati(self):
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        st.init_storage_v2()
        st.init_storage_v2()
        self.assertEqual(st.get_record("negozi", "n1")["nome"], "N1")

    def test_reset_rifiutato_se_db_non_di_test(self):
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        old = os.environ["DB_NAME"]
        os.environ["DB_NAME"] = "gestione_consegne"
        try:
            with self.assertRaises(st.StorageError):
                st._test_reset()
        finally:
            os.environ["DB_NAME"] = old
        self.assertIsNotNone(st.get_record("negozi", "n1"))                   # dati intatti

    def test_connessione_persa_solleva_storage_error(self):
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        old = os.environ.get("DB_PORT")
        os.environ["DB_PORT"] = "1"                                           # nessun server in ascolto
        try:
            with self.assertLogs(st.log, level="ERROR"):                      # errore atteso: non stampato
                with self.assertRaises(st.StorageError):
                    st.list_records("negozi")
                with self.assertRaises(st.StorageError):
                    st.insert_record("negozi", {"id": "n2", "nome": "N2"})
        finally:
            if old is None:
                os.environ.pop("DB_PORT", None)
            else:
                os.environ["DB_PORT"] = old
        self.assertEqual([n["id"] for n in st.list_records("negozi")], ["n1"])

    def test_backup_now_non_fa_nulla_e_non_fallisce(self):
        self.assertTrue(st.backup_now())

    def test_errore_in_transazione_non_lascia_scritture_parziali(self):
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        st.insert_record("consegne", consegna("c1"))
        with self.assertRaises(st.NotFoundError):                             # giornata con consegna inesistente
            ins_g(giornata(consegneIds=["c1", "c_nope"]))
        self.assertEqual(st.list_records("giornate"), [])                     # nemmeno la giornata esiste

    def test_scritture_concorrenti_su_record_diversi(self):
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})
        errors = []

        def worker(i):
            try:
                for j in range(5):
                    st.insert_record("consegne", consegna(f"c{i}_{j}"))
            except Exception as e:                                            # pragma: no cover
                errors.append(e)
        ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errors, [])
        self.assertEqual(len(st.list_records("consegne")), 40)


@unittest.skipUnless(BACKEND == "json", "specifico del backend json")
class JsonSpecific(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gc_test_")
        st.DATA_DIR = self.tmp
        st.init_storage_v2()
        st.insert_record("negozi", {"id": "n1", "nome": "N1"})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_persistenza_dopo_riavvio(self):
        st.insert_record("consegne", consegna())
        st.update_record("consegne", "c1", {"note": "x"})
        st.init_storage_v2()                                                  # nuova istanza = riavvio
        self.assertEqual(st.get_record("consegne", "c1")["note"], "x")
        self.assertEqual(st.get_record("consegne", "c1")["versione"], 2)

    def test_file_corrotto_solleva_errore_e_non_viene_sovrascritto(self):
        st.insert_record("consegne", consegna())
        path = os.path.join(self.tmp, "consegne.json")
        with open(path, "w") as f:
            f.write("{ questo non è json")
        with self.assertLogs(st.log, level="ERROR"):                          # errore atteso: non stampato
            with self.assertRaises(st.StorageError):
                st.list_records("consegne")
            with self.assertRaises(st.StorageError):
                st.insert_record("consegne", consegna("c2"))
        with open(path) as f:
            self.assertEqual(f.read(), "{ questo non è json")                 # intatto

    def test_scrittura_atomica_nessun_tmp_residuo(self):
        st.insert_record("consegne", consegna())
        self.assertFalse([f for f in os.listdir(self.tmp) if f.endswith(".tmp")])

    def test_file_su_disco_e_array_semplice(self):
        st.insert_record("consegne", consegna())
        with open(os.path.join(self.tmp, "consegne.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["id"], "c1")

    def test_backup_throttling(self):
        bdir = os.path.join(self.tmp, "backup")
        count = lambda: len([f for f in os.listdir(bdir) if f.startswith("consegne.")])
        st.insert_record("consegne", consegna("c1"))                          # primo write: snapshot
        self.assertEqual(count(), 1)
        for i in range(2, 6):
            st.insert_record("consegne", consegna(f"c{i}"))                   # entro 5 min: nessuno
        self.assertEqual(count(), 1)
        st._be()._last_backup = time.time() - st.BACKUP_MIN_INTERVAL - 1      # simula 5 minuti dopo
        time.sleep(1.1)                                                       # nome file diverso (secondi)
        st.insert_record("consegne", consegna("c9"))
        self.assertEqual(count(), 2)

    def test_backup_now_forza_snapshot_e_contiene_tutte_le_collezioni(self):
        st.insert_record("consegne", consegna())
        self.assertTrue(st.backup_now())
        names = os.listdir(os.path.join(self.tmp, "backup"))
        for key in st._COLL:
            self.assertTrue(any(n.startswith(key + ".") for n in names), key)
        self.assertTrue(any(n.startswith("meta.") for n in names))

    def test_backup_rotazione(self):
        bdir = os.path.join(self.tmp, "backup")
        for i in range(st.MAX_BACKUPS + 5):
            with open(os.path.join(bdir, f"consegne.2020-01-01_00-00-{i:02d}.json"), "w") as f:
                f.write("[]")
        st.backup_now()
        self.assertEqual(len([f for f in os.listdir(bdir) if f.startswith("consegne.")]), st.MAX_BACKUPS)

    def test_test_reset_protetto(self):
        os.environ["STORAGE_ALLOW_TEST_RESET"] = "0"
        try:
            with self.assertRaises(st.StorageError):
                st._test_reset()
        finally:
            os.environ["STORAGE_ALLOW_TEST_RESET"] = "1"


if __name__ == "__main__":
    unittest.main(verbosity=2)
