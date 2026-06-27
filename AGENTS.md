# AGENTS.md — Gestione Consegne

Documento di contesto per agenti AI. Descrive stato attuale del progetto, architettura, decisioni prese, convenzioni adottate, piano di upgrade V2 e istruzioni operative per l'agente.

---

## Indice

1. [Istruzioni operative per l'agente AI](#1-istruzioni-operative)
2. [Descrizione del progetto](#2-descrizione-del-progetto)
3. [Struttura dei file](#3-struttura-dei-file)
4. [Architettura Docker](#4-architettura-docker)
5. [Server Python](#5-server-python)
6. [Storage layer](#6-storage-layer)
7. [Frontend](#7-frontend)
8. [Struttura dati](#8-struttura-dati)
9. [Flusso operativo tipico](#9-flusso-operativo-tipico)
10. [Decisioni progettuali già prese](#10-decisioni-progettuali-già-prese)
11. [Piano upgrade V2](#11-piano-upgrade-v2)
12. [Commit message convention](#12-commit-message-convention)

---

## 1. Istruzioni operative per l'agente AI

### 1.1 Pianifica prima di agire — autorizzazione obbligatoria

**Non modificare mai file senza autorizzazione esplicita dell'utente.**

1. Analizza la richiesta e identifica tutti i file coinvolti
2. Esponi il piano: cosa cambia, dove, perché
3. Attendi conferma esplicita prima di scrivere qualsiasi file

### 1.2 Preferisci modifiche chirurgiche al refactoring

- Usa `str_replace` per porzioni specifiche invece di riscrivere l'intero file
- Riscrivi un file intero solo se la modifica tocca più del 60% del contenuto
- Quando riscrivi un file intero, segnalalo e spiega perché

### 1.3 Revisione obbligatoria dopo ogni modifica

1. Rileggi ogni blocco modificato nel contesto del file completo
2. Cerca attivamente errori di sintassi, logica, coerenza
3. Verifica nomi di funzioni, variabili, endpoint tra tutti i file toccati
4. Se non trovi errori, dillo esplicitamente

### 1.4 Non inventare — chiedi o cerca

- Non inventare risposte plausibili e presentarle come certe
- Chiedi se il dubbio riguarda una scelta progettuale
- Cerca online se il dubbio riguarda un fatto tecnico verificabile

### 1.5 File critici — attenzione massima

| File | Rischio |
|---|---|
| `server.py` | Un errore di sintassi blocca il server per tutti |
| `storage.py` | Un errore rompe la persistenza dei dati per tutti i backend |
| `js/api.js` + `js/sync.js` | Un errore blocca la comunicazione client-server |
| `js/store.js` | Un errore rompe lo stato globale dell'intera app |
| `Dockerfile` | Un errore impedisce il build dell'immagine |
| `compose.yaml` | Un errore impedisce l'avvio dei container |

### 1.6 Aggiorna la documentazione insieme al codice

Ogni volta che una modifica cambia endpoint, strutture dati, o decisioni progettuali, aggiorna le sezioni corrispondenti di questo file e di `README.md`.

---

## 2. Descrizione del progetto

**Gestione Consegne** è un gestionale web per organizzare le consegne di prodotti di elettronica effettuate da squadre di consegna. Distribuito come container Docker, accessibile via browser da qualsiasi client nella stessa rete.

### Utenti (V1 attuale)
- Accesso anonimo: chiunque sulla LAN può leggere e scrivere
- Uso sporadico: 5-10 minuti alla volta, alcune volte al giorno
- Raramente due utenti lavorano contemporaneamente

### Versione corrente: V1 (Docker)
- Nessuna autenticazione
- Backend dati selezionabile: JSON / MySQL / PostgreSQL
- API: due endpoint unici (`GET /api/data`, `POST /api/data`)
- Frontend invariato rispetto all'originale Windows

---

## 3. Struttura dei file

```
gestione_consegne/
├── server.py               # Server HTTP e logica backend
├── storage.py              # Astrazione backend dati (json/mysql/postgres)
├── import_data.py          # Importazione one-shot da dati.json legacy
├── requirements.txt        # Dipendenze Python
├── Dockerfile              # Immagine Docker (python:3.13-slim-bookworm)
├── compose.yaml            # Orchestrazione (profili: mysql, postgres)
├── index.html              # Shell HTML
├── css/
│   ├── theme.css
│   ├── layout.css
│   └── components.css
└── js/
    ├── main.js             # Entry point
    ├── store.js            # Stato globale
    ├── api.js              # Layer HTTP
    ├── sync.js             # Sync dati e ping
    ├── render.js           # Rendering viste
    ├── utils.js            # Helper puri
    ├── theme.js            # Gestione tema
    ├── dragdrop.js         # Drag & drop
    ├── giornate.js         # Logica giornate
    ├── modal-consegna.js   # Modal consegna
    ├── modal-select.js     # Modal selezione
    ├── squadre.js          # CRUD squadre
    └── stampa.js           # Stampa PDF
```

---

## 4. Architettura Docker

### Immagine base
`python:3.13-slim-bookworm` — Debian Bookworm minimal, glibc (necessario per psycopg2-binary e mysql-connector).

### Sicurezza container
- Utente non-root: `appuser` (UID 1001, GID 1001, shell `/bin/false`)
- `read_only: true` nel compose (filesystem in sola lettura)
- `/tmp` come tmpfs
- DB non esposto sull'host (solo rete interna Docker)
- `DB_PASSWORD` obbligatorio tramite `.env`, mai hardcoded

### Porta
`8080` interna. Mappata sull'host tramite `APP_PORT` nel `.env` (default `8080`).

### Healthcheck
```
GET http://localhost:8080/api/ping → 200 OK
interval: 15s | timeout: 5s | start-period: 15s | retries: 3
```
Implementato in Python puro (stdlib `urllib.request`) — nessuna dipendenza da curl.

### Profili compose
| Comando | Backend |
|---------|---------|
| `docker compose up -d` | JSON |
| `docker compose --profile mysql up -d` | MySQL 8.4 |
| `docker compose --profile postgres up -d` | PostgreSQL 16-alpine |

### Importazione dati legacy
```bash
docker compose run --rm \
  -v ./dati.json:/import/dati.json:ro \
  app python import_data.py
```
Protetto da file flag `/data/import_done`.

### Variabili d'ambiente
| Variabile | Default | Note |
|-----------|---------|------|
| `PORT` | `8080` | Porta interna |
| `DB_BACKEND` | `json` | `json` \| `mysql` \| `postgres` |
| `DATA_DIR` | `/data` | Directory JSON |
| `DB_HOST` | `db` | Host DB |
| `DB_PORT` | `3306`/`5432` | Porta DB |
| `DB_NAME` | `gestione_consegne` | Nome DB |
| `DB_USER` | — | Utente DB |
| `DB_PASSWORD` | — | Password DB |
| `IMPORT_SOURCE` | `/import/dati.json` | Sorgente import |

---

## 5. Server Python (`server.py`)

### Costanti
```python
PORT     = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
```

### Endpoint HTTP V1
| Metodo | Path | Descrizione |
|--------|------|-------------|
| GET | `/api/ping` | Healthcheck. Risponde `{"ok": true, "clients": N}`. Registra il client. |
| GET | `/api/data` | Legge tutto il DB via `storage.read_data()`. Aggiunge `_connectedClients`. |
| POST | `/api/data` | Scrive tutto il DB via `storage.write_data()`. |
| POST | `/api/log` | Riceve `{"msg": "..."}` dal client e lo scrive nel log. |
| GET | `/*` | File statici dalla directory `BASE_DIR`. |

### Logging
Tutto su stdout (catturato da Docker). Formato: `YYYY-MM-DD HH:MM:SS [LEVEL] messaggio`.

### Contatore client connessi
Heartbeat per IP tramite `client_heartbeat{}`. Un client è "attivo" se ha fatto ping negli ultimi 15 secondi.

### Crash
`crash_server(reason)` → logga su stdout + `os._exit(1)`. Nessun popup, nessun lock file (rimossi in fase di dockerizzazione).

### Rimosso rispetto alla versione Windows
- System tray (`pystray`, `Pillow`)
- Popup PowerShell crash
- `server.lock` / `write_lock()` / `remove_lock()`
- `rotate_log()` (Docker gestisce la rotazione dei log)
- `open_browser()`
- File `avvia.bat`, `avvia.ps1`, `configura_firewall.bat`

---

## 6. Storage layer (`storage.py`)

### Interfaccia pubblica
```python
init_storage()       # chiamata una volta all'avvio del server
read_data()          # → {"consegne": [], "giornate": [], "squadre": []}
write_data(data)     # salva il dict completo
make_backup()        # snapshot JSON (no-op per DB)
```

### Backend JSON
File separati: `consegne.json`, `giornate.json`, `squadre.json` in `DATA_DIR`.
Scrittura atomica (`.tmp` + `os.replace()`). Backup in `DATA_DIR/backup/` (max 20 per tipo).

### Backend MySQL / PostgreSQL
Schema nativo (non blob JSON). Tabelle:

| Tabella | Descrizione |
|---------|-------------|
| `consegne` | Record consegna con campi reali + `articoli` (JSON/JSONB) + `extra` (JSON/JSONB) per campi futuri |
| `squadre` | Squadre con `id`, `nome`, `color_idx` |
| `giornate` | Giornate con `id`, `data`, `squadra` (nome stringa in V1), `extra` |
| `giornata_consegne` | Join giornata↔consegna con `ordine` e `completata` |

Il campo `extra` (JSONB in Postgres, JSON in MySQL) cattura eventuali campi aggiuntivi del frontend senza rompere lo schema. È pienamente leggibile da chiunque acceda al DB.

I campi camelCase del frontend (`giornoConsegna`, `fasciaOraria`, ecc.) vengono normalizzati a snake_case al salvataggio e riconvertiti alla lettura.

### Retry e attesa DB
`init_storage()` tenta la connessione al DB fino a 10 volte (3 secondi di pausa tra un tentativo e l'altro) per gestire il caso in cui il container DB non sia ancora pronto al momento dell'avvio dell'app.

---

## 7. Frontend

Il frontend V1 è **invariato** rispetto alla versione Windows. Tutti i dettagli di implementazione restano validi.

### Costante API
```javascript
// store.js
export const API = `http://${window.location.hostname}:8080/api`;
```
⚠️ La porta è cambiata da `8742` (Windows) a `8080` (Docker). Già aggiornata in `store.js`.

### Stato globale (`store.js`)
```javascript
let db              = { consegne: [], giornate: [], squadre: [] };
let currentView     = 'lista';
let currentGiornataId    = null;
let editingConsegnaId    = null;
let expandedRowId        = null;
let isDirty              = false;
let serverOnline         = true;
let pingFailCount        = 0;
const PING_FAIL_THRESHOLD = 2;
const SQ_COLORS = 8;
```

### Ciclo di vita dei dati
1. Al caricamento: `loadData()` → GET `/api/data` → popola `db` → `renderAll()`
2. Ogni 8 secondi: polling se `serverOnline && !isDirty`
3. Ogni 2 secondi: ping → se 2 fallimenti → `showDisconnectOverlay()`
4. Ogni modifica: `markDirty()` → 600ms debounce → `saveData()` → POST `/api/data`

### Grafo dipendenze JS
```
main.js
  ├── store.js          (no deps)
  ├── api.js → store
  ├── sync.js → api, store
  ├── utils.js → store
  ├── theme.js          (no deps)
  ├── render.js → sync, utils, store, dragdrop
  │     └── dragdrop.js → store, sync, api
  ├── giornate.js → store, sync, api, render, utils
  ├── modal-consegna.js → store, sync, api, render, utils
  ├── modal-select.js → store, sync, api, render, utils
  ├── squadre.js → store, sync, api, render, utils
  └── stampa.js → store, utils
```

---

## 8. Struttura dati

### `consegne` (array)
```json
{
  "id": "abc123",
  "dataPrenotazione": "2024-03-22",
  "stato": "in_attesa",
  "nome": "Mario",
  "cognome": "Rossi",
  "citta": "Vicenza",
  "indirizzo": "Via Roma 1",
  "tel1": "+39 333 1234567",
  "tel2": "",
  "raee": "no",
  "articoli": [
    { "tipoConsegna": "ins_incasso", "tipo": "TV", "codice": "SONY-X90L", "desc": "TV Sony 55\" OLED" }
  ],
  "piano": "2",
  "noteAbitazione": "Scala stretta",
  "preferenzePeriodo": "Solo mattina",
  "giornoConsegna": "2024-03-25",
  "fasciaOraria": "9:00-12:00",
  "note": ""
}
```

### `giornate` (array)
```json
{
  "id": "def456",
  "data": "2024-03-25",
  "squadra": "Squadra A",
  "consegneIds": ["abc123"]
}
```
⚠️ In V1 `squadra` è una **stringa (nome)**. In V2 diventerà `squadra_id` (FK). Vedere sezione 11.

### `squadre` (array)
```json
{ "id": "sq001", "nome": "Squadra A", "colorIdx": 0 }
```

### Valori enum
- `stato`: `in_attesa` | `da_confermare` | `programmata` | `completata` | `annullata` | `da_riprogrammare`
- `tipoConsegna` (per articolo): `consegna` | `installazione` | `ins_incasso` | `ins_muro` | `ins_sbs` | ~~`incasso`~~ *(deprecato — solo retrocompatibilità)*
- `raee`: `si` | `no`
- `colorIdx`: `0`..`7`

### Campo `_connectedClients`
Aggiunto dal server nelle risposte HTTP. **Mai scritto su disco o nel DB.**

---

## 9. Flusso operativo tipico

### Aggiungere una consegna
Lista → "Nuova consegna" → compila form → aggiungi articoli → Salva

### Programmare una consegna
Giornate → seleziona o crea giornata → "Aggiungi consegna" → seleziona dalla lista "in attesa" → Aggiungi

### Rimuovere da una giornata
Click ✕ sulla card → la consegna torna "in_attesa", `giornoConsegna` e `fasciaOraria` svuotati

---

## 10. Decisioni progettuali già prese

### Architettura generale
| Decisione | Motivazione |
|-----------|-------------|
| Docker come target esclusivo | Eliminata dipendenza da Windows, deployment riproducibile |
| Porta `8080` interna | Standard HTTP alternativo; mappabile a qualsiasi porta sull'host |
| Immagine `python:3.13-slim-bookworm` | glibc (necessario per psycopg2-binary), superficie minimale, LTS |
| Unica immagine per tutti i backend | Semplicità deploy; dipendenze DB importate condizionalmente |
| Utente non-root `appuser:1001` | Best practice sicurezza container |
| `read_only: true` nel compose | Filesystem container in sola lettura; solo `/data` e `/tmp` scrivibili |
| DB non esposto sull'host | Sicurezza: raggiungibile solo dalla rete interna Docker |
| File separati per JSON (non unico `dati.json`) | Scritture atomiche indipendenti per entità, preparazione V2 |
| Schema DB nativo (non blob) | Leggibilità diretta nel DB, query possibili, preparazione V2 |
| Campo `extra` JSONB/JSON | Absorbe campi futuri senza migration dello schema |
| `squadra` come stringa in V1 | Retrocompatibilità; diventerà `squadra_id` in V2 |
| Healthcheck Python puro | Nessuna dipendenza da curl/wget nell'immagine |

### Frontend e dati
| Decisione | Motivazione |
|-----------|-------------|
| Scrittura atomica (tmp + rename) | Protezione da corruzione a metà scrittura |
| Lettura fresca prima di ogni scrittura | Previene sovrascritture con accesso quasi-contemporaneo |
| 2 tentativi poi crash | Preferibile perdere l'ultima modifica che avere dati corrotti |
| Ping HTTP (non ICMP) | ICMP bloccato dai firewall di default |
| Cognome Nome (non Nome Cognome) | Richiesta esplicita del cliente — **non invertire mai** |
| Stessa data permessa con squadre diverse | Richiesta esplicita per gestire squadre parallele |
| Schermata bloccante senza istruzioni specifiche | I client usano solo il browser |
| Tema auto da OS + switch manuale | Usabilità su monitor diversi, salvato in `localStorage` |
| `articoli[]` invece di 3 campi singoli | Più prodotti per consegna, retrocompatibile |
| `tipoConsegna` per-articolo | Consegne miste con tipi installazione diversi per articolo |

---

## 11. Piano upgrade V2

Questa sezione documenta il piano completo per il prossimo upgrade. **Non implementare nulla di questa sezione senza esplicita autorizzazione.**

### Panoramica V2
La V2 introduce autenticazione, permessi granulari, multi-tenancy (negozi), API REST complete e polling efficiente basato su timestamp.

### 11.1 Modifiche `server.py`

Aggiungere (senza riscrivere la struttura esistente):
- Strutture in memoria: `sessions = {}`, `challenges = {}`, `category_timestamps = {}`
- Thread daemon per cleanup sessioni/challenges scaduti (ogni 60s)
- Metodo `_check_auth(required_permission)` nell'Handler
- Tutti i nuovi endpoint REST (vedere tabella sotto)
- Rimozione di `POST /api/data` e `GET /api/data` come endpoint unici
- Rimozione di `POST /api/log`
- `GET /api/ping` resta invariato (nessuna auth, usato dall'healthcheck)

**Endpoint V2 completi:**

| Metodo | Path | Permesso | Descrizione |
|--------|------|----------|-------------|
| GET | `/api/auth/challenge` | No auth | Genera challenge monouso |
| POST | `/api/auth/login` | No auth | Login → token + permessi |
| POST | `/api/auth/logout` | Token | Invalida sessione |
| POST | `/api/auth/change-password` | Token | Cambia propria password |
| GET | `/api/ping` | No auth | Healthcheck (invariato) |
| GET | `/api/stato` | Token (no superadmin) | Timestamp per polling |
| GET/POST | `/api/negozi` | superadmin | Lista/Crea negozi |
| PUT/DELETE | `/api/negozi/:id` | superadmin | Modifica/Elimina negozio |
| GET/POST | `/api/tipi-account` | `tipi_account.leggi` / superadmin | Lista/Crea tipi account |
| PUT/DELETE | `/api/tipi-account/:id` | superadmin | Modifica/Elimina tipo account |
| GET/POST | `/api/utenti` | `utenti.leggi` / `utenti.crea` | Lista/Crea utenti |
| PUT | `/api/utenti/:id/password` | `utenti.modifica` | Cambia password utente |
| PUT | `/api/utenti/:id/tipo` | `utenti.modifica` | Cambia tipo account utente |
| DELETE | `/api/utenti/:id` | `utenti.elimina` | Elimina utente |
| GET/POST | `/api/consegne` | `consegne.leggi` / `consegne.scrivi` | Lista/Crea |
| PUT/DELETE | `/api/consegne/:id` | `consegne.scrivi` / `consegne.elimina` | Modifica/Elimina |
| GET/POST | `/api/giornate` | `giornate.leggi` / `giornate.crea` | Lista/Crea |
| DELETE | `/api/giornate/:id` | `giornate.elimina` | Elimina |
| POST | `/api/giornate/:id/assegna` | `giornate.assegna` | Aggiunge consegne |
| DELETE | `/api/giornate/:id/assegna/:cid` | `giornate.assegna` | Rimuove consegna |
| PUT | `/api/giornate/:id/riordina` | `giornate.riordina` | Riordina consegne |
| PUT | `/api/giornate/:id/consegne/:cid/completa` | `giornate.segna_completata` | Segna completata |
| GET/POST | `/api/squadre` | `squadre.leggi` / `squadre.gestisci` | Lista/Crea |
| PUT/DELETE | `/api/squadre/:id` | `squadre.gestisci` | Modifica/Elimina |

### 11.2 Modifiche `storage.py`

Schema DB ampliato per V2. Le tabelle V1 (`consegne`, `squadre`, `giornate`, `giornata_consegne`) vengono estese, non sostituite:

```sql
-- NUOVE tabelle
CREATE TABLE negozi (
    id        VARCHAR(36) PRIMARY KEY,
    nome      VARCHAR(255) NOT NULL,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tipi_account (
    id        VARCHAR(36) PRIMARY KEY,
    nome      VARCHAR(255) NOT NULL UNIQUE,
    permessi  TEXT NOT NULL,   -- JSON array: '["consegne.leggi","stampa.pdf"]'
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE utenti (
    id               VARCHAR(36) PRIMARY KEY,
    username         VARCHAR(150) NOT NULL UNIQUE,
    password_hash    VARCHAR(64) NOT NULL,   -- sha256(sha256(password))
    tipo_account_id  VARCHAR(36) REFERENCES tipi_account(id) ON DELETE SET NULL,
    negozio_id       VARCHAR(36) REFERENCES negozi(id) ON DELETE SET NULL,
    is_superadmin    BOOLEAN NOT NULL DEFAULT FALSE,
    primo_login      BOOLEAN NOT NULL DEFAULT TRUE,
    creato_da        VARCHAR(36),
    creato_il        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultimo_accesso   TIMESTAMP
);

-- MODIFICHE alle tabelle esistenti
ALTER TABLE consegne ADD COLUMN negozio_id VARCHAR(36) REFERENCES negozi(id);
ALTER TABLE consegne ADD COLUMN versione INTEGER NOT NULL DEFAULT 1;
ALTER TABLE squadre  ADD COLUMN negozio_id VARCHAR(36) REFERENCES negozi(id);
ALTER TABLE squadre  ADD COLUMN versione INTEGER NOT NULL DEFAULT 1;
-- squadre.squadra_id (FK) sostituisce squadre.squadra (stringa) in giornate
ALTER TABLE giornate ADD COLUMN negozio_id VARCHAR(36) REFERENCES negozi(id);
ALTER TABLE giornate ADD COLUMN squadra_id VARCHAR(36) REFERENCES squadre(id);
ALTER TABLE giornate ADD COLUMN versione INTEGER NOT NULL DEFAULT 1;
-- giornate.squadra (stringa) va rimossa dopo migrazione
```

⚠️ Per il backend JSON in V2, `squadra_id` (non il nome stringa) viene usato nelle giornate, coerentemente con lo schema DB.

### 11.3 Nuovo `migrate.py`

Script one-shot per la migrazione V1 → V2. Deve:
1. Verificare il file flag `migrazione_v2.done` (o tabella `migrazioni` per DB) — bloccarsi se già eseguito
2. Fare backup completo di tutti i file/tabelle
3. Creare negozio "Negozio principale"
4. Aggiungere `negozio_id` e `versione: 1` a tutte le entità
5. Convertire `giornate.squadra` (stringa) → `giornate.squadra_id` (FK)
6. Creare superadmin con password di default `admin` (hash pre-calcolato)
7. Creare `tipi_account` vuoto
8. Aggiornare `utenti` (se esistono): rimuovere `ruolo`, aggiungere `tipo_account_id: null` e `negozio_id`
9. Scrivere il file flag

### 11.4 File frontend nuovi

| File | Contenuto |
|------|-----------|
| `js/sha256.js` | SHA-256 puro JS (no `crypto.subtle` — non disponibile su HTTP su IP LAN) |
| `js/auth.js` | Login overlay, challenge-response, sessionStorage, logout, cambio password |
| `js/permessi.js` | Lista permessi, dipendenze tra permessi, `hasPermesso(id)` |
| `js/admin-superadmin.js` | Pannello superadmin (caricato dinamicamente solo per superadmin) |
| `js/admin-utenti.js` | Pannello gestione utenti (per account con permessi `utenti.*`) |

### 11.5 File frontend modificati

| File | Tipo modifica |
|------|---------------|
| `js/store.js` | Aggiunta `currentUser`, `localTimestamps`; rimozione `isDirty`, `pingFailCount`; soglia ping → 1 |
| `js/api.js` | Riscrittura: layer HTTP con header `X-Session-Token` e intercettazione 401 |
| `js/sync.js` | Riscrittura: polling basato su timestamp, `applyServerResponse`, rimozione `markDirty`/`saveData` |
| `js/main.js` | Modifica: init condizionale (verifica token → superadmin vs utente normale) |
| `js/squadre.js` | Chirurgica: operazioni → REST, rimozione `remoteLog` e `markDirty` |
| `js/giornate.js` | Chirurgica: idem |
| `js/render.js` | Modifica: `hasPermesso()` per mostrare/nascondere UI, `squadra_id` invece di nome |
| `js/modal-consegna.js` | Chirurgica: operazioni → REST |
| `js/modal-select.js` | Chirurgica: operazioni → REST |
| `index.html` | Aggiunta overlay login, overlay cambio password obbligatorio, sezione pannello utenti |

### 11.6 Autenticazione V2 — dettagli

**Challenge-Response con SHA-256:**
1. `GET /api/auth/challenge` → server genera token casuale (TTL 60s), lo restituisce
2. Client calcola: `h1 = sha256(password)`, poi `response = sha256(h1 + challenge)`
3. `POST /api/auth/login` con `{username, challenge, response}`
4. Server confronta con `sha256(h1_memorizzato + challenge)` a tempo costante
5. Challenge invalidato dopo l'uso (protezione replay)

**Sessioni (solo in memoria):**
```
{ user_id, username, negozio_id, permessi[], is_superadmin, last_seen, expires, must_change_password }
```
- TTL: 2 ore dall'ultimo accesso
- Invalida immediatamente le sessioni se cambia `tipo_account_id` dell'utente

**Token lato client:** salvato in `sessionStorage` (cancellato alla chiusura del browser). Header: `X-Session-Token`.

### 11.7 Permessi V2

| Gruppo | Permessi |
|--------|----------|
| Consegne | `consegne.leggi`, `consegne.scrivi`, `consegne.elimina` |
| Giornate | `giornate.leggi`, `giornate.crea`, `giornate.elimina`, `giornate.assegna`, `giornate.riordina`, `giornate.segna_completata` |
| Squadre | `squadre.leggi`, `squadre.gestisci` |
| Stampa | `stampa.pdf` |
| Tipi account | `tipi_account.leggi` |
| Utenti | `utenti.leggi`, `utenti.crea`, `utenti.modifica`, `utenti.elimina` |

Riservati al superadmin (non assegnabili): `tipi_account.gestisci`, `negozi.gestisci`.

**Verifica backend nell'ordine:**
1. Token valido → altrimenti 401
2. Se `is_superadmin`: accesso garantito solo agli endpoint admin, 403 su endpoint operativi
3. Permesso specifico presente in `session.permessi` → altrimenti 403
4. `negozio_id` della risorsa coincide con `session.negozio_id` → altrimenti 403

### 11.8 Regole rigide V2 (server-side, non aggirabili)

- Il superadmin non è eliminabile né modificabile da altri
- Un utente con `tipo_account_id: null` non può fare login (escluso superadmin)
- Un tipo account non è eliminabile se ha utenti associati
- Un negozio non è eliminabile se ha utenti associati
- Il cambio `tipo_account_id` invalida immediatamente tutte le sessioni attive dell'utente
- Il superadmin riceve 403 su tutti gli endpoint operativi
- Il server filtra sempre per `negozio_id` su tutti gli endpoint operativi
- Un utente non può eliminare se stesso

### 11.9 Ordine consigliato di implementazione V2

1. `migrate.py` — eseguire subito per struttura dati corretta
2. Backend: nuovi file dati e I/O (negozi, tipi_account, utenti aggiornato)
3. Backend: SHA-256 e sistema Challenge-Response (`/api/auth/*`)
4. Backend: sessioni e verifica token (middleware riusabile)
5. Backend: timestamp e `/api/stato`
6. Backend: endpoint REST operativi (consegne, giornate, squadre) con permessi e filtro negozio
7. Backend: endpoint admin (negozi, tipi account, utenti)
8. Frontend: `js/sha256.js`
9. Frontend: `js/auth.js` (login, logout, cambio password, sessionStorage)
10. Frontend: layer HTTP (`js/api.js`) — header auth, intercettazione 401
11. Frontend: `js/store.js` — aggiungi `currentUser`, `localTimestamps`; rimuovi `isDirty`
12. Frontend: `js/sync.js` — polling timestamp, `applyServerResponse`
13. Frontend: `js/permessi.js` — `hasPermesso()`
14. Frontend: `js/main.js` — init condizionale
15. Frontend: `js/admin-superadmin.js` (caricato dinamicamente)
16. Frontend: `js/admin-utenti.js`
17. Test integrato: migrazione → primo login superadmin → creazione negozio → tipo account → utente → login → operatività

---

## 12. Commit message convention

```
tipo(ambito): descrizione breve in italiano (max 72 caratteri)

- dettaglio 1
- dettaglio 2
```

Tipi: `feat`, `fix`, `refactor`, `docs`, `style`, `chore`.

Esempi:
```
feat(docker): aggiungi Dockerfile e compose.yaml con profili DB

chore(server): rimuovi dipendenze Windows (tray, lock, browser)

docs(agents): aggiorna architettura e piano V2
```
