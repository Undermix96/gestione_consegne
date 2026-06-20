# AGENTS.md — Gestione Consegne

Documento di contesto per agenti AI. Descrive lo stato attuale del progetto, l'architettura, le decisioni prese e le convenzioni adottate.

---

## 1. Descrizione del progetto

**Gestione Consegne** è un gestionale web locale per organizzare le consegne di prodotti di elettronica effettuate da squadre. È utilizzato da un'azienda su LAN wireless + cablata con dispositivi personali dei dipendenti connessi — rete non completamente trusted.

### Utenti
- Numero variabile di operatori che accedono da PC diversi sulla stessa LAN
- Uso sporadico: 5–10 minuti alla volta, alcune volte al giorno
- Raramente due utenti lavorano contemporaneamente
- I PC vengono accesi e spenti in ordine casuale

### Vincoli fondamentali (NON modificare senza approvazione esplicita)
- **Nessuna installazione** di programmi, librerie o ambienti di runtime sui PC client
- **Nessun cloud**: dati privati, non possono uscire dalla rete locale
- **Nessun server centrale fisso**: qualsiasi PC può fare da server
- **Integrità dei dati assoluta**: il programma è usato per lavoro
- **Windows 11** come unico OS target
- **Python embedded** incluso nella cartella — nessuna dipendenza di sistema
- **HTTP puro** (no HTTPS) — la sicurezza delle credenziali è garantita dal sistema Challenge-Response

---

## 2. Sistema di autenticazione e permessi

### Account superadmin (hardcoded)
- Unico, non eliminabile, non modificabile da nessuno (tranne la propria password)
- `tipo_account_id: null`, `negozio_id: null` — marker dell'account speciale
- Permessi hardcoded nel server: gestione negozi, tipi account, utenti
- Non ha accesso ai dati operativi (consegne, giornate, squadre)
- Vista esclusiva: pannello admin con tre sezioni (Negozi, Tipi account, Utenti)

### Tipi account (dinamici, creati dal superadmin)
- Ogni tipo ha un nome e un set di permessi assegnabili
- Globali: condivisi tra tutti i negozi
- Non eliminabili se hanno utenti associati

### Permessi assegnabili ai tipi account

```
consegne.leggi          giornate.leggi          squadre.leggi
consegne.scrivi         giornate.crea           squadre.gestisci
consegne.elimina        giornate.elimina        stampa.pdf
                        giornate.assegna        tipi_account.leggi
                        giornate.riordina       utenti.leggi
                        giornate.segna_completata utenti.crea
                                                utenti.modifica
                                                utenti.elimina
```

Permessi hardcoded superadmin (non assegnabili): `tipi_account.gestisci`, `negozi.gestisci`, + tutti i permessi utenti e `tipi_account.leggi`.

### Dipendenze permessi (avvisi visivi nel frontend, NO selezione automatica)

```
consegne.scrivi            → consegne.leggi
consegne.elimina           → consegne.leggi
giornate.crea              → giornate.leggi, squadre.leggi
giornate.elimina           → giornate.leggi
giornate.assegna           → giornate.leggi, consegne.leggi
giornate.riordina          → giornate.leggi
giornate.segna_completata  → giornate.leggi
squadre.gestisci           → squadre.leggi
stampa.pdf                 → giornate.leggi, consegne.leggi
utenti.crea                → utenti.leggi, tipi_account.leggi
utenti.modifica            → utenti.leggi, tipi_account.leggi
utenti.elimina             → utenti.leggi
```

### Multi-tenancy (negozi)
- Ogni utente (escluso superadmin) appartiene a un negozio
- Ogni entità operativa (consegna, giornata, squadra) ha `negozio_id`
- Il server filtra per `negozio_id` della sessione su ogni endpoint operativo
- Il superadmin può creare utenti per qualsiasi negozio; gli altri creano solo per il proprio

### Challenge-Response (SHA-256)

```
1. GET  /api/auth/challenge  →  { challenge: "a3f9..." }  (hex 32 byte, monouso, TTL 60s)
2. Client: h1 = sha256(password), response = sha256(h1 + challenge)
3. POST /api/auth/login  →  { username, challenge, response }
4. Server: expected = sha256(stored_h1 + challenge)
           confronta con secrets.compare_digest
```

### Sessioni in memoria

```python
sessions = {
    "token_abc": {
        "user_id":              "u_abc",
        "username":             "mario.rossi",
        "negozio_id":           "n_abc123",   # null per superadmin
        "permessi":             ["consegne.leggi", "..."],
        "is_superadmin":        False,
        "last_seen":            1718528400.0,
        "expires":              1718535600.0,
        "must_change_password": False
    }
}
```

I permessi vengono copiati nella sessione al login. Modifiche ai permessi di un tipo account hanno effetto al login successivo (sessioni attive non invalidate). **Eccezione:** cambio tipo account invalida immediatamente le sessioni dell'utente.

### Utente senza tipo account
Un utente con `tipo_account_id: null` viene bloccato al login con messaggio "Account non configurato. Contatta l'amministratore." (escluso superadmin).

---

## 3. Struttura dei file

```
gestione_consegne/
├── server.py               ← Server HTTP, auth, sessioni, utenti, permessi, log
├── migrazione_v2.py        ← Script one-shot migrazione da v1 a v2 (eseguire una volta)
├── index.html              ← Shell HTML: struttura, overlay login/cambio-pwd, modali
│
├── css/
│   ├── theme.css           ← Variabili CSS, palette squadre, temi chiaro/scuro
│   ├── layout.css          ← Reset, header, sidebar, struttura app
│   └── components.css      ← Bottoni, badge, form, modal, overlay, pannello admin
│
├── js/
│   ├── main.js             ← Entry point: check auth, init app per ruolo, espone globali
│   ├── store.js            ← Stato globale: db, currentUser, timestamps, setters
│   ├── permessi.js         ← Lista permessi, dipendenze, hasPermesso(), getPermessiPerGruppo()
│   ├── sha256.js           ← SHA-256 puro (challenge-response su HTTP)
│   ├── auth.js             ← login(), logout(), changePassword(), getAuthHeaders()
│   ├── api.js              ← Chiamate REST con X-Session-Token + intercept 401
│   ├── sync.js             ← loadData, applyServerResponse, pollData, ping
│   ├── render.js           ← renderAll, switchView, renderLista, renderGiornata
│   ├── utils.js            ← uid, fmtDate, statoPill, toast, openModal
│   ├── theme.js            ← initTheme, applyTheme, toggleTheme
│   ├── dragdrop.js         ← Drag & drop card giornata
│   ├── giornate.js         ← Azioni giornate (REST) e modal nuova giornata
│   ├── modal-consegna.js   ← Modal creazione/modifica consegna (REST)
│   ├── modal-select.js     ← Modal selezione consegne → giornata (REST)
│   ├── modal-utenti.js     ← Pannello gestione utenti per account con permessi utenti.*
│   ├── modal-admin.js      ← Pannello superadmin: Negozi, Tipi account, Utenti
│   ├── squadre.js          ← CRUD squadre (REST)
│   └── stampa.js           ← Stampa PDF giornata
│
├── dati.json               ← Dati operativi con negozio_id su ogni entità
├── utenti.json             ← Utenti con tipo_account_id e negozio_id
├── tipi_account.json       ← Tipi account con permessi
├── negozi.json             ← Negozi
├── server.lock             ← Presenza server
├── gestionale.log          ← Log con rotazione 7 giorni
├── migrazione_v2.done      ← Flag: migrazione eseguita (creato da migrazione_v2.py)
├── backup/                 ← Snapshot automatici (max 20) + backup pre-migrazione
├── avvia.bat / avvia.ps1  ← Script di avvio
├── configura_firewall.bat  ← Configurazione rete (eseguire una sola volta)
└── python_embed/           ← Python 3.13 embedded (portabile)
```

---

## 4. Grafo dipendenze JS

```
main.js
  ├── store.js          (no deps)
  ├── sha256.js         (no deps)
  ├── permessi.js → store
  ├── auth.js → sha256, store
  ├── api.js → store, auth
  ├── sync.js → api, store
  ├── utils.js → store
  ├── theme.js          (no deps)
  ├── render.js → sync, utils, store, dragdrop, permessi
  │     └── dragdrop.js → store, sync, api, permessi
  ├── giornate.js → store, sync, api, render, utils, permessi
  ├── modal-consegna.js → store, sync, api, render, utils
  ├── modal-select.js → store, sync, api, render, utils
  ├── modal-utenti.js → api, auth, utils, sha256, permessi
  ├── modal-admin.js → api, permessi, utils, sha256  [caricato dinamicamente solo per superadmin]
  ├── squadre.js → store, sync, api, render, utils
  └── stampa.js → store, utils
```

Nessuna dipendenza circolare.

---

## 5. Endpoint HTTP (completo)

| Metodo | Path | Auth | Permesso richiesto | Descrizione |
|--------|------|------|--------------------|-------------|
| GET | `/api/auth/challenge` | No | — | Genera challenge monouso |
| POST | `/api/auth/login` | No | — | Login → token + permessi |
| POST | `/api/auth/logout` | Token | — | Invalida sessione |
| POST | `/api/auth/change-password` | Token | — | Cambia propria password |
| GET | `/api/ping` | Opzionale | — | Heartbeat + contatore client |
| GET | `/api/stato` | Token | — (no superadmin) | Timestamp categorie per polling |
| GET | `/api/negozi` | Token | superadmin | Lista negozi |
| POST | `/api/negozi` | Token | superadmin | Crea negozio |
| PUT | `/api/negozi/:id` | Token | superadmin | Rinomina negozio |
| DELETE | `/api/negozi/:id` | Token | superadmin | Elimina negozio (solo se senza utenti) |
| GET | `/api/tipi-account` | Token | `tipi_account.leggi` | Lista tipi account |
| POST | `/api/tipi-account` | Token | superadmin | Crea tipo account |
| PUT | `/api/tipi-account/:id` | Token | superadmin | Modifica tipo account |
| DELETE | `/api/tipi-account/:id` | Token | superadmin | Elimina tipo (solo se senza utenti) |
| GET | `/api/utenti` | Token | `utenti.leggi` | Lista utenti (filtrata per negozio) |
| POST | `/api/utenti` | Token | `utenti.crea` | Crea utente |
| PUT | `/api/utenti/:id/password` | Token | `utenti.modifica` | Cambia password utente |
| PUT | `/api/utenti/:id/tipo` | Token | `utenti.modifica` | Cambia tipo account utente |
| DELETE | `/api/utenti/:id` | Token | `utenti.elimina` | Elimina utente |
| GET | `/api/consegne` | Token | `consegne.leggi` | Lista consegne del negozio |
| POST | `/api/consegne` | Token | `consegne.scrivi` | Crea consegna |
| PUT | `/api/consegne/:id` | Token | `consegne.scrivi` | Modifica consegna |
| DELETE | `/api/consegne/:id` | Token | `consegne.elimina` | Elimina consegna |
| GET | `/api/giornate` | Token | `giornate.leggi` | Lista giornate del negozio |
| POST | `/api/giornate` | Token | `giornate.crea` | Crea giornata |
| DELETE | `/api/giornate/:id` | Token | `giornate.elimina` | Elimina giornata |
| POST | `/api/giornate/:id/assegna` | Token | `giornate.assegna` | Aggiunge consegne |
| DELETE | `/api/giornate/:id/assegna/:cid` | Token | `giornate.assegna` | Rimuove consegna |
| PUT | `/api/giornate/:id/riordina` | Token | `giornate.riordina` | Riordina consegne |
| PUT | `/api/giornate/:id/consegne/:cid/completa` | Token | `giornate.segna_completata` | Segna completata |
| GET | `/api/squadre` | Token | `squadre.leggi` | Lista squadre del negozio |
| POST | `/api/squadre` | Token | `squadre.gestisci` | Crea squadra |
| PUT | `/api/squadre/:id` | Token | `squadre.gestisci` | Modifica squadra |
| DELETE | `/api/squadre/:id` | Token | `squadre.gestisci` | Elimina squadra |

### Verifica permessi — ordine server
1. Token valido → 401
2. `is_superadmin` → accesso garantito solo agli endpoint superadmin, 403 su operativi
3. Permesso specifico in `session.permessi` → 403
4. `negozio_id` risorsa == `session.negozio_id` → 403

### Risposta endpoint di scrittura
Ogni endpoint di scrittura risponde con il db aggiornato del negozio:
```json
{ "consegne": [...], "giornate": [...], "squadre": [...], "_connectedClients": N }
```
Il client aggiorna lo stato locale con `applyServerResponse()`.

---

## 6. `utenti.json` — struttura

```json
{
  "utenti": [
    {
      "id": "u_superadmin",
      "username": "superadmin",
      "password_hash": "hex64chars (sha256(password))",
      "tipo_account_id": null,
      "negozio_id": null,
      "primo_login": true,
      "creato_da": null,
      "creato_il": "2026-06-18T10:00:00",
      "ultimo_accesso": null
    },
    {
      "id": "u_abc123",
      "username": "mario.rossi",
      "password_hash": "hex64chars",
      "tipo_account_id": "ta_xyz789",
      "negozio_id": "n_abc123",
      "primo_login": false,
      "creato_da": "u_superadmin",
      "creato_il": "2026-06-18T10:00:00",
      "ultimo_accesso": "2026-06-18T14:30:00"
    }
  ]
}
```

`tipo_account_id: null` + `negozio_id: null` = superadmin (marker hardcoded).
`tipo_account_id: null` su utente normale = account non configurato, login bloccato.

---

## 7. `tipi_account.json` — struttura

```json
{
  "tipi_account": [
    {
      "id": "ta_abc123",
      "nome": "Amministratore",
      "permessi": ["consegne.leggi", "utenti.leggi", "utenti.crea", "tipi_account.leggi"],
      "creato_il": "2026-06-18T10:00:00",
      "modificato_il": "2026-06-18T10:00:00"
    }
  ]
}
```

---

## 8. `negozi.json` — struttura

```json
{
  "negozi": [
    {
      "id": "n_abc123",
      "nome": "Negozio principale",
      "creato_il": "2026-06-18T10:00:00"
    }
  ]
}
```

---

## 9. Log — formato e categorie

```
2026-06-18 10:00:00 [INFO]  [AUTH]         superadmin ha effettuato il login da 192.168.1.15
2026-06-18 10:05:00 [INFO]  [NEGOZI]       Negozio 'Sede principale' creato da 'superadmin'
2026-06-18 10:06:00 [INFO]  [TIPI_ACCOUNT] Tipo 'Admin' creato da 'superadmin'
2026-06-18 10:10:00 [INFO]  [UTENTI]       Utente 'mario.rossi' (Admin) creato per negozio 'Sede principale' da 'superadmin'
2026-06-18 10:15:00 [INFO]  [DATI]         'mario.rossi' — Nuova consegna: Rossi Mario
2026-06-18 10:30:00 [WARN]  [AUTH]         Login fallito — password errata per 'pippo' da 192.168.1.33
```

Categorie: `[AUTH]`, `[UTENTI]`, `[DATI]`, `[NEGOZI]`, `[TIPI_ACCOUNT]`.
Tutti i log generati lato server — nessun `POST /api/log` dal client.

---

## 10. Struttura dati operativi (`dati.json`)

```json
{
  "consegne": [{
    "id": "c_abc123",
    "negozio_id": "n_abc123",
    "versione": 1,
    "dataPrenotazione": "2024-03-22",
    "stato": "in_attesa | da_confermare | programmata | completata | annullata | da_riprogrammare",
    "nome": "Mario", "cognome": "Rossi",
    "citta": "Vicenza", "indirizzo": "Via Roma 1",
    "tel1": "+39 333 …", "tel2": "",
    "raee": "no | si",
    "articoli": [
      { "tipoConsegna": "consegna | installazione | incasso", "tipo": "TV", "codice": "SONY-X90L", "desc": "…" }
    ],
    "piano": "2", "noteAbitazione": "…", "preferenzePeriodo": "…",
    "giornoConsegna": "2024-03-25", "fasciaOraria": "9:00-12:00", "note": ""
  }],
  "giornate": [{
    "id": "g_def456",
    "negozio_id": "n_abc123",
    "versione": 1,
    "data": "2024-03-25",
    "squadra": "Squadra A",
    "consegneIds": ["c_abc123"]
  }],
  "squadre": [{
    "id": "sq_001",
    "negozio_id": "n_abc123",
    "versione": 1,
    "nome": "Squadra A",
    "colorIdx": 0
  }]
}
```

Il campo `versione` è usato per l'optimistic locking: il client invia la versione che conosce, il server risponde 409 se non coincide.

---

## 11. Optimistic locking

- Ogni entità ha `versione` (intero, parte da 1)
- Il client include `versione` nelle richieste PUT
- Server: se `client_versione != server_versione` → risponde 409 Conflict
- Messaggio: "la consegna/giornata è stata modificata da un altro utente. Ricarica e riprova."
- Il server incrementa `versione` ad ogni scrittura andata a buon fine

---

## 12. Polling e sincronizzazione

- **Ping**: ogni 2 secondi, 1 fallimento consecutivo → overlay disconnessione (era 2, abbassato per risposta rapida)
- **Polling**: ogni 8 secondi via `GET /api/stato` → confronta timestamp → scarica solo le categorie cambiate → render solo se necessario (nessun render inutile)
- **Operazioni di scrittura**: la risposta contiene già il db aggiornato → `applyServerResponse()` aggiorna lo stato locale immediatamente, senza attendere il prossimo ciclo di polling
- **Offline**: overlay bloccante, modifiche locali perse (comportamento invariato rispetto a v1)

---

## 13. Migrazione da v1

File: `migrazione_v2.py` — eseguire **una sola volta** prima del primo avvio del nuovo server.

Operazioni:
1. Backup in `backup/pre-migrazione/`
2. Crea `negozi.json` con negozio "Negozio principale"
3. Aggiunge `negozio_id` + `versione: 1` a ogni entità in `dati.json`
4. Riscrive `utenti.json`: rimuove `ruolo`, aggiunge `tipo_account_id: null` e `negozio_id: null`
5. Crea `tipi_account.json` vuoto
6. Crea `migrazione_v2.done` (flag: non rieseguibile)

Dopo la migrazione, gli utenti non-superadmin hanno `tipo_account_id: null` e non possono accedere fino a che il superadmin non assegna loro un tipo account.

---

## 14. Regole lato server (hardcoded, non aggirabili dal frontend)

- Superadmin non eliminabile, non modificabile tranne propria password
- Superadmin: `tipo_account_id` e `negozio_id` sempre `null`, non modificabili
- Utente con `tipo_account_id: null` non può fare login (escluso superadmin)
- Tipo account non eliminabile se ha utenti associati
- Negozio non eliminabile se ha utenti associati
- Modifica permessi tipo account: effettiva al login successivo (sessioni attive non invalidate)
- Cambio tipo account: invalida immediatamente le sessioni dell'utente
- Superadmin riceve 403 su tutti gli endpoint operativi (`/api/consegne`, `/api/giornate`, `/api/squadre`, `/api/stato`)
- Il server filtra sempre per `negozio_id` su tutti gli endpoint operativi
- Un utente non può eliminare se stesso

---

## 15. Decisioni progettuali già prese (non riaprire)

| Decisione | Motivazione |
|-----------|-------------|
| Challenge-Response SHA-256 | `crypto.subtle` non disponibile su HTTP su IP LAN |
| `sha256(password)` come password_hash | Coerente con challenge-response, non invertibile |
| `sessionStorage` invece di `localStorage` | Auto-cancellato alla chiusura del browser |
| Superadmin senza operatività | Separazione netta; l'admin di sistema non tocca i dati aziendali |
| JSON come database (no SQLite) | SQLite su NFS/SMB è inaffidabile |
| Server unico con `server.lock` | Multi-server causa corruzione dati |
| Scrittura atomica (tmp + rename) | Protezione da corruzione a metà scrittura |
| Cognome Nome (non Nome Cognome) | Richiesta esplicita del cliente — definitivo |
| `articoli[]` invece di 3 campi singoli | Supporto a più prodotti per consegna — retrocompatibile |
| Tipi account globali (non per negozio) | Semplicità gestione; solo il superadmin li crea |
| `tipi_account.gestisci` solo superadmin | Non assegnabile ad altri account |
| Dipendenze permessi come avvisi, no auto-selezione | Più trasparente; chi configura deve essere consapevole |
| Optimistic locking con campo `versione` | Protegge da scritture concorrenti su LAN con utenti elevati |
| Polling via timestamp | Evita render inutili; scarica solo ciò che è cambiato |
| Risposta scritture = db aggiornato | Client sempre in sync dopo ogni operazione propria |
| Log 100% server-side | Non aggirabile dal client; auditabilità reale |
| `modal-admin.js` caricato dinamicamente | Non caricato per utenti normali; separazione netta |
| `negozi.gestisci` solo superadmin | Coerente con `tipi_account.gestisci` |

---

## 16. Note per modifiche future

- **Non usare `crypto.subtle`** — non disponibile su `http://IP:8742` da browser moderni
- **Non aggiungere dipendenze npm/pip** — i client non hanno internet, Python embedded non si aggiorna
- **Non cambiare la struttura di `dati.json`** senza aggiornare `migrazione_v2.py` o creare un nuovo script di migrazione
- **Non cambiare `utenti.json`** senza aggiornare `init_users()`, `find_user_by_*`, e tutti gli endpoint utenti
- **La porta 8742 non deve cambiare** — configurata nel firewall di ogni PC server
- **Non ripristinare `f_tipoProdotto` / `f_codiceProdotto` / `f_tipoConsegna` nel DOM** — non esistono più
- **`expandedRowId`** viene resettato a `null` se la riga viene eliminata
- L'ordine **Cognome Nome** è intenzionale e definitivo
- Il campo `password_hash` in `utenti.json` contiene `sha256(password)` — se si cambia schema bisogna resettare tutte le password
- La struttura post-migrazione è quella definitiva; `migrazione_v2.py` è one-shot e non reversibile
- Se si aggiungono nuovi negozi, farlo tramite il pannello superadmin — non editare `negozi.json` a mano in produzione

---

## 17. Istruzioni operative per l'agente AI

### 17.1 Pianifica prima di agire — autorizzazione obbligatoria

**Non modificare mai file senza autorizzazione esplicita dell'utente.**

1. Analizza la richiesta e identifica tutti i file coinvolti
2. Esponi il piano: cosa cambia, dove, perché
3. Attendi conferma esplicita prima di scrivere qualsiasi file

### 17.2 Preferisci modifiche chirurgiche al refactoring

- Usa `str_replace` per porzioni specifiche invece di riscrivere l'intero file
- Riscrivi un file intero solo se la modifica tocca più del 60% del contenuto
- Quando riscrivi un file intero, segnalalo e spiega perché

### 17.3 Revisione obbligatoria dopo ogni modifica

1. Rileggi ogni blocco modificato nel contesto del file completo
2. Cerca attivamente errori di sintassi, logica, coerenza
3. Verifica nomi di funzioni, variabili, endpoint tra tutti i file toccati
4. Se non trovi errori, dillo esplicitamente

### 17.4 Non inventare — chiedi o cerca

- Non inventare risposte plausibili e presentarle come certe
- Chiedi se il dubbio riguarda una scelta progettuale
- Cerca online se il dubbio riguarda un fatto tecnico verificabile

### 17.5 File critici — attenzione massima

| File | Rischio |
|---|---|
| `server.py` | Un errore di sintassi blocca il server per tutti |
| `utenti.json` (struttura) | Un'incompatibilità invalida tutti gli account |
| `js/auth.js` + `js/sha256.js` | Un errore blocca il login per tutti |
| `dati.json` (struttura) | Un'incompatibilità corrompe i dati operativi |
| `avvia.bat` / `avvia.ps1` | Un errore impedisce l'avvio del server |

### 17.6 Aggiorna la documentazione insieme al codice

Ogni volta che una modifica cambia endpoint, strutture dati, o decisioni progettuali, aggiorna le sezioni corrispondenti di questo file.

### 17.7 Commit message

```
tipo(ambito): descrizione breve in italiano (max 72 caratteri)

- dettaglio 1
- dettaglio 2
```

Tipi: `feat`, `fix`, `refactor`, `docs`, `style`, `chore`.
