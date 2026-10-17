# AGENTS.md — Gestione Consegne

Documento di contesto per agenti AI. Descrive stato attuale del progetto, architettura, decisioni prese, convenzioni adottate, stato di implementazione V2 e istruzioni operative per l'agente.

---

> **Stato del branch `v2-docker`:** questo documento descrive la **V2** (obiettivo del branch). Il codice è ancora V1 finché le fasi in [§11](#11-stato-di-implementazione-v2) non sono completate. Le parti non ancora implementate sono marcate **🚧 V2**. Il design V2 proviene dal branch `dev` (versione Windows, mai andata in produzione) ed è stato adattato a Docker e allo storage a più backend.

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
11. [Stato di implementazione V2](#11-stato-di-implementazione-v2)
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
| `js/auth.js` + `js/sha256.js` (V2) | Un errore blocca il login di tutti gli utenti |
| `migrate.py` (V2) | Un errore può corrompere o duplicare i dati in produzione |

### 1.6 Aggiorna la documentazione insieme al codice

Ogni volta che una modifica cambia endpoint, strutture dati, o decisioni progettuali, aggiorna le sezioni corrispondenti di questo file e di `README.md`.

---

## 2. Descrizione del progetto

**Gestione Consegne** è un gestionale web per organizzare le consegne di prodotti di elettronica effettuate da squadre di consegna. Distribuito come container Docker, accessibile via browser da qualsiasi client nella stessa rete.

### Utenti
- Uso sporadico: 5-10 minuti alla volta, alcune volte al giorno
- Raramente due utenti lavorano contemporaneamente (la V2 protegge comunque dalle scritture concorrenti con l'optimistic locking)
- Rete aziendale LAN wireless + cablata con dispositivi personali dei dipendenti connessi: **rete non completamente trusted** (motivo dell'autenticazione V2)

### Vincoli fondamentali (NON modificare senza approvazione esplicita)
- **Nessuna installazione sui client**: si usa solo il browser
- **Nessun cloud**: dati privati, non possono uscire dalla rete locale
- **Integrità dei dati assoluta**: il programma è usato per lavoro
- **HTTP puro (no HTTPS)**: la sicurezza delle credenziali è garantita dal sistema Challenge-Response (§5)
- **Frontend senza dipendenze esterne né build step**: i client non hanno internet; solo JS ES Modules nativi
- **Docker** come unico ambiente di esecuzione (sviluppo e produzione)

### Versione corrente: V1 (Docker) — branch `main`
- Nessuna autenticazione: chiunque sulla LAN può leggere e scrivere
- Backend dati selezionabile: JSON / MySQL / PostgreSQL
- API: due endpoint unici (`GET /api/data`, `POST /api/data`)
- Frontend invariato rispetto all'originale Windows

### Versione obiettivo: V2 🚧 — branch `v2-docker`
- **Login multi-utente** con Challenge-Response SHA-256 e sessioni in memoria
- **Tipi account dinamici** con permessi granulari, creati dal superadmin
- **Multi-tenancy**: ogni entità operativa appartiene a un negozio; ogni utente vede solo il proprio negozio
- **Superadmin** solo amministrativo (negozi, tipi account, utenti): nessun accesso ai dati operativi
- **API REST** per singola operazione, al posto di `GET/POST /api/data`
- **Storage per singolo record** (`storage.py`) su tutti e tre i backend, con **optimistic locking** (`versione`)
- Polling a timestamp, log 100% server-side
- Utenti, negozi e tipi account sono gestiti dallo stesso layer `storage.py` delle entità operative

---

## 3. Struttura dei file

```
gestione_consegne/
├── server.py               # Server HTTP e logica backend (V2: auth, sessioni, REST, permessi)
├── storage.py              # Astrazione backend dati (json/mysql/postgres) (V2: API per singolo record)
├── import_data.py          # Importazione one-shot da dati.json legacy (V1)
├── migrate.py              # 🚧 V2: migrazione V1→V2 e tra backend (vedi §11, fase 4)
├── tests/                  # 🚧 V2: suite di contratto di storage.py (non inclusa nell'immagine)
├── requirements.txt        # Dipendenze Python
├── Dockerfile              # Immagine Docker (python:3.13-slim-bookworm)
├── compose.yaml            # Orchestrazione (profili: mysql, postgres)
├── index.html              # Shell HTML (V2: + overlay login e cambio password, pannelli utenti/admin)
├── css/
│   ├── theme.css
│   ├── layout.css
│   └── components.css      # (V2: + overlay login, pannello admin)
└── js/
    ├── main.js             # Entry point (V2: init condizionale dopo verifica token)
    ├── store.js            # Stato globale (V2: currentUser, localTimestamps)
    ├── api.js              # Layer HTTP (V2: X-Session-Token, intercept 401; sempre X-Client-ID)
    ├── sync.js             # Sync dati e ping (V2: polling a timestamp, applyServerResponse)
    ├── render.js           # Rendering viste (V2: hasPermesso())
    ├── utils.js            # Helper puri
    ├── theme.js            # Gestione tema
    ├── dragdrop.js         # Drag & drop
    ├── giornate.js         # Logica giornate (V2: REST)
    ├── modal-consegna.js   # Modal consegna (V2: REST)
    ├── modal-select.js     # Modal selezione (V2: REST)
    ├── squadre.js          # CRUD squadre (V2: REST)
    ├── stampa.js           # Stampa PDF
    ├── sha256.js           # 🚧 V2: SHA-256 puro JS (no crypto.subtle)
    ├── auth.js             # 🚧 V2: login, logout, cambio password, token in sessionStorage
    ├── permessi.js         # 🚧 V2: lista permessi, dipendenze, hasPermesso()
    ├── modal-utenti.js     # 🚧 V2: gestione utenti (account con permessi utenti.*)
    └── modal-admin.js      # 🚧 V2: pannello superadmin (caricato dinamicamente solo per il superadmin)
```

**Dati a runtime:** nel volume `/data` (backend JSON) un file per collezione (`consegne.json`, `giornate.json`, `squadre.json` e, in V2, `negozi.json`, `tipi_account.json`, `utenti.json`) più `meta.json` e `backup/`; con i backend MySQL/PostgreSQL le stesse collezioni sono tabelle. **Nessun dato applicativo è scritto fuori da `storage.py`** (il container è `read_only`).

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
# Backend JSON: import poi avvio
docker compose run --rm \
  -v ./dati.json:/import/dati.json:ro \
  app python import_data.py
docker compose up -d

# Backend MySQL/Postgres: import avvia automaticamente anche il DB
# (depends_on), poi si avvia l'app
docker compose --profile mysql run --rm \
  -v ./dati.json:/import/dati.json:ro \
  app python import_data.py
docker compose --profile mysql up -d
```
Protetto da file flag `/data/import_done`. Per i backend DB il container DB deve essere pronto (`service_healthy`) prima della scrittura: `docker compose run` avvia le dipendenze automaticamente grazie a `depends_on`.

### Variabili d'ambiente
| Variabile | Default | Note |
|-----------|---------|------|
| `PORT` | `8080` | Porta interna |
| `LOG_LEVEL` | `INFO` | `DEBUG` mostra anche ogni richiesta HTTP (`log_message`) |
| `DB_BACKEND` | `json` | `json` \| `mysql` \| `postgres` |
| `DATA_DIR` | `/data` | Directory JSON |
| `DB_HOST` | `db` | Host DB |
| `DB_PORT` | `3306`/`5432` | Porta DB |
| `DB_NAME` | `gestione_consegne` | Nome DB |
| `DB_USER` | — | Utente DB |
| `DB_PASSWORD` | — | Password DB |
| `IMPORT_SOURCE` | `/import/dati.json` | Sorgente import |

### Implicazioni della V2 su Docker 🚧
- **Istanza `app` unica, niente repliche:** sessioni e challenge sono in memoria del processo. Un riavvio del container disconnette tutti gli utenti (devono rifare il login).
- **Primo avvio:** se non esiste il superadmin, il server lo crea (`superadmin` / `admin`, `primo_login = true`: cambio password obbligatorio). Vedi §5.
- **Nessun file applicativo fuori da `storage.py`:** utenti, negozi e tipi account seguono lo stesso backend scelto con `DB_BACKEND` (nessun JSON "speciale" accanto al codice: il filesystem del container è in sola lettura).
- **Migrazione:** `migrate.py` (🚧, §11 fase 4) porta i dati V1 allo schema V2 e permette di passare da un backend all'altro. `import_data.py` resta lo strumento per il solo `dati.json` legacy Windows.
- **Variabili d'ambiente:** nessuna nuova variabile prevista per la V2 (da riconfermare in fase 1/4).

---

## 5. Server Python (`server.py`)

### Costanti
```python
PORT     = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 🚧 V2
SESSION_TTL   = 7200   # 2 ore di inattività
CHALLENGE_TTL = 60     # secondi
```

### Endpoint HTTP — V1 (attuale su `main`, rimossi in V2)
| Metodo | Path | Descrizione |
|--------|------|-------------|
| GET | `/api/ping` | Healthcheck. Risponde `{"ok": true, "clients": N}`. Registra il client. |
| GET | `/api/data` | Legge tutto il DB via `storage.read_data()`. Aggiunge `_connectedClients`. |
| POST | `/api/data` | Scrive tutto il DB via `storage.write_data()`. |
| POST | `/api/log` | Riceve `{"msg": "..."}` dal client e lo scrive nel log. |
| GET | `/*` | File statici dalla directory `BASE_DIR`. |

### Endpoint HTTP — V2 🚧
Sostituiscono `GET/POST /api/data` e `POST /api/log`. `GET /api/ping` resta senza autenticazione obbligatoria (usato dall'healthcheck Docker); se il client invia `X-Session-Token` valido la sessione viene rinnovata. `GET /*` (file statici) invariato.

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

### Account superadmin
- Unico, non eliminabile, non modificabile da nessuno (tranne la propria password)
- Identificato dalla colonna **`is_superadmin = true`** (non da un marker implicito); `id` fisso `u_superadmin`; `tipo_account_id` e `negozio_id` sono sempre `null`
- Permessi hardcoded nel server (non assegnabili): `tipi_account.gestisci`, `negozi.gestisci`, più tutti i permessi `utenti.*` e `tipi_account.leggi`
- **Non ha accesso ai dati operativi** (consegne, giornate, squadre): 403 su quegli endpoint
- Vista esclusiva: pannello admin con tre sezioni (Negozi, Tipi account, Utenti)
- Creato al primo avvio con password di default `admin`; **cambio password obbligatorio** al primo login (`must_change_password`)
- Un utente con `tipo_account_id: null` che non sia superadmin è "non configurato" e non può accedere

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

### Regole lato server (hardcoded, non aggirabili dal frontend) 🚧
- Superadmin non eliminabile, non modificabile tranne la propria password
- Utente con `tipo_account_id: null` non può fare login (escluso superadmin)
- Tipo account non eliminabile se ha utenti associati
- Negozio non eliminabile se ha utenti associati
- Modifica dei permessi di un tipo account: effettiva al login successivo (sessioni attive non invalidate)
- Cambio del tipo account di un utente: invalida immediatamente le sessioni di quell'utente
- Superadmin riceve 403 su tutti gli endpoint operativi (`/api/consegne`, `/api/giornate`, `/api/squadre`, `/api/stato`)
- Il server filtra sempre per `negozio_id` su tutti gli endpoint operativi
- Un utente non può eliminare se stesso
- Gli errori di concorrenza (`versione` non coincidente) rispondono **409 Conflict**; token mancante/scaduto **401**; permesso o negozio non coerente **403**

### Optimistic locking 🚧
- Ogni entità operativa ha `versione` (intero, parte da 1)
- Il client include `versione` nelle richieste `PUT`
- Se `client_versione != versione` salvata → **409 Conflict** con messaggio "la consegna/giornata è stata modificata da un altro utente. Ricarica e riprova."
- La `versione` viene incrementata a ogni scrittura riuscita
- **Il confronto è atomico nel layer `storage.py`** (su DB: `UPDATE ... WHERE id = ? AND versione = ?`; su JSON: sotto lock di collezione). Il server non fa read-then-write separati.

### Polling e sincronizzazione 🚧
- **Ping**: ogni 2 secondi, 1 fallimento consecutivo → overlay disconnessione (in V1 la soglia è 2)
- **Polling**: ogni 8 secondi via `GET /api/stato` → confronta i timestamp per categoria (`consegne`, `giornate`, `squadre`) → scarica solo le categorie cambiate → render solo se necessario
- **Scritture**: la risposta contiene già il db aggiornato del negozio → `applyServerResponse()` aggiorna lo stato locale subito, senza attendere il polling
- **Offline**: overlay bloccante, modifiche locali perse (comportamento invariato rispetto a V1)
- I timestamp di polling sono **in memoria e globali** (non per negozio): una scrittura in un negozio può far riscaricare i dati agli altri negozi (le risposte restano comunque filtrate per negozio). Si azzerano al riavvio. Vedi punti aperti in §11.

### Logging
Tutto su stdout (catturato da Docker). Formato: `YYYY-MM-DD HH:MM:SS [LEVEL] messaggio`. Livello configurabile via `LOG_LEVEL` (default `INFO`). `log_message`/`log_error` di `BaseHTTPRequestHandler` sono agganciati al logger: le richieste HTTP finiscono a livello `DEBUG` (visibili solo con `LOG_LEVEL=DEBUG`), gli errori HTTP a livello `ERROR`.

**V2 🚧 — categorie e formato:** tutti i log sono generati lato server, nessun `POST /api/log` dal client.
```
2026-06-18 10:00:00 [INFO]  [AUTH]         superadmin ha effettuato il login da 192.168.1.15
2026-06-18 10:05:00 [INFO]  [NEGOZI]       Negozio 'Sede principale' creato da 'superadmin'
2026-06-18 10:06:00 [INFO]  [TIPI_ACCOUNT] Tipo 'Admin' creato da 'superadmin'
2026-06-18 10:10:00 [INFO]  [UTENTI]       Utente 'mario.rossi' (Admin) creato per negozio 'Sede principale' da 'superadmin'
2026-06-18 10:15:00 [INFO]  [DATI]         'mario.rossi' — Nuova consegna: Rossi Mario
2026-06-18 10:30:00 [WARN]  [AUTH]         Login fallito — password errata per 'pippo' da 192.168.1.33
```
Categorie: `[AUTH]`, `[UTENTI]`, `[DATI]`, `[NEGOZI]`, `[TIPI_ACCOUNT]`. L'IP nei log di autenticazione è quello visto dal container (in Docker può essere quello del gateway, vedi "Contatore client connessi").

### Contatore client connessi
Heartbeat tramite `client_heartbeat{}`, chiave = header `X-Client-ID` (UUID-like generato dal browser con `crypto.getRandomValues()`, salvato in `sessionStorage`), con fallback sull'IP se l'header manca (retrocompatibilità, es. richieste esterne senza frontend). Un client è "attivo" se ha fatto una richiesta (ping o data) negli ultimi 15 secondi.

**Perché non l'IP:** in Docker, il traffico dei client reali arriva spesso dietro NAT/gateway, quindi più browser distinti possono condividere lo stesso IP sorgente — con l'IP come chiave il contatore li conterebbe come un solo client (o, nel caso dell'healthcheck su `127.0.0.1`, ne aggiungerebbe uno fittizio). L'header `X-Client-ID` risolve entrambi i problemi.

Le richieste dell'healthcheck Docker interno (`127.0.0.1`/`::1`, nessun header `X-Client-ID`) sono escluse esplicitamente dal conteggio tramite `HEALTHCHECK_IPS`.

### Crash
`crash_server(reason)` → logga su stdout + `os._exit(1)`. Nessun popup, nessun lock file (rimossi in fase di dockerizzazione).

### Rimosso rispetto alla versione Windows
- System tray (`pystray`, `Pillow`)
- Popup PowerShell crash
- `server.lock` / `write_lock()` / `remove_lock()`
- `rotate_log()` (Docker gestisce la rotazione dei log)
- `open_browser()`
- File `avvia.bat`, `avvia.ps1`, `configura_firewall.bat`


### Limiti noti della sicurezza V2 🚧
- **Hash memorizzato = credenziale equivalente.** Nel Challenge-Response il server deve conoscere `sha256(password)` per calcolare la risposta attesa; chi leggesse quel valore dal DB/volume potrebbe autenticarsi senza conoscere la password. Il DB non è esposto sull'host e il volume `/data` è raggiungibile solo da chi amministra l'host Docker; il rischio è accettato per poter proteggere le credenziali su HTTP senza `crypto.subtle`. Da non cambiare senza una decisione esplicita.
- **Password di default del superadmin (`admin`) finché non viene cambiata al primo accesso:** chiunque sulla LAN che la conosca potrebbe entrare nel pannello admin. Cambiarla subito dopo il primo avvio.
- **Rate limiting dei tentativi di login:** non previsto in questa versione (i tentativi falliti sono solo loggati).
- **Sessioni e challenge in memoria:** perse a ogni riavvio; incompatibili con più repliche (vedi §4).

---

## 6. Storage layer (`storage.py`)

### Stato attuale (V1)
```python
init_storage()       # chiamata una volta all'avvio del server
read_data()          # → {"consegne": [], "giornate": [], "squadre": []}
write_data(data)     # salva il dict completo
make_backup()        # snapshot JSON (no-op per DB)
```
In V2 `read_data()`/`write_data()` **non sono più usate dal server**: restano solo come strumenti per `import_data.py` e per leggere i dati V1 in `migrate.py`.

### Principi V2 🚧
- **Accesso per singolo record**, su tutti i backend: nessuna scrittura "tutta la tabella". I backend SQL non fanno più `DELETE` + reinserimento di tutto: una scrittura fallita non può toccare i dati degli altri negozi.
- **Optimistic locking atomico nel layer di storage:** l'aggiornamento è condizionato a `versione` e la incrementa; se non coincide si solleva un errore di conflitto (che il server traduce in 409).
- **Il filtro per `negozio_id` si applica nella query/lettura**, non dopo aver caricato tutto.
- **Operazioni multi-riga in transazione** (backend SQL): assegnazione, rimozione e riordino delle consegne di una giornata.
- **Stessa semantica su json/mysql/postgres:** un comportamento si considera corretto solo se identico sui tre backend (suite di test condivisa, fase 1).
- Nessun dato applicativo fuori da `storage.py`: anche `utenti`, `negozi`, `tipi_account` passano da qui.

### Collezioni V2 🚧
`consegne`, `giornate`, `squadre`, `negozi`, `tipi_account`, `utenti` (+ tabella di join `giornata_consegne` sui backend SQL).

### Interfaccia pubblica V2 🚧 (implementata per il backend json — fase 1, passo 1a)
```python
init_storage_v2()                       # il server V2 usa questa al posto di init_storage()
list_records(collection, filters=None)  # ordine di inserimento; filtri di uguaglianza
get_record(collection, id)              # → dict | None
insert_record(collection, record)       # `id` fornito dal chiamante; versione=1 dove prevista
insert_records(collection, records)     # una collezione, tutto-o-niente (usata da migrate.py)
update_record(collection, id, changes, expected_versione=None)   # merge; incrementa versione
delete_record(collection, id)           # → True | False (non esisteva)
giornata_assegna(giornata_id, consegna_ids)       # aggiunge in coda, idempotente
giornata_rimuovi(giornata_id, consegna_id)        # idempotente
giornata_riordina(giornata_id, ordered_ids)       # permutazione esatta
get_meta(key, default=None) / set_meta(key, value)   # schema_version, flag migrazione
backup_now()                            # snapshot immediato (json); no-op per i backend DB
```
Collezioni: `consegne`, `giornate`, `squadre`, `negozi`, `tipi_account`, `utenti`. La specifica (campi obbligatori, default, unicità, riferimenti) è dichiarata una sola volta nel codice (`_COLL`) e vale per tutti i backend.

**Eccezioni** (tutte derivano da `StorageError`; il server le traduce in HTTP): `ConflictError` → 409, `NotFoundError` → 404, `DuplicateError`, `IntegrityError`. Gli errori di programmazione (collezione sconosciuta, campo obbligatorio mancante, campo non modificabile) sono `ValueError`. Il comportamento del server su `StorageError` generico (crash o 500) resta un punto aperto (§11).

**Semantica comune a tutti i backend:**
- **`None` = campo assente.** Un valore `None` non viene memorizzato né restituito; `update_record(..., {"campo": None})` rimuove il campo. (Su SQL, NULL ≡ chiave mancante: è ciò che rende identici i risultati.)
- **Chiavi sempre camelCase** come nel frontend (`colorIdx`, `giornoConsegna`, ...): nessuna chiave snake_case esce dallo storage. I campi sconosciuti allo schema sono conservati e restituiti invariati.
- **`id` e `negozio_id` forniti dal chiamante**; `negozio_id` e `id` non sono modificabili; `versione` è gestita solo dallo storage (valore fornito all'inserimento ignorato).
- **Default:** `consegne.stato = in_attesa`, `squadre.colorIdx = 0`, `utenti.is_superadmin = false`, `utenti.primo_login = true`.
- **Unicità:** `id`; `utenti.username` e `tipi_account.nome`. `utenti.username` è confrontato **senza distinguere maiuscole/minuscole** (anche nei filtri), come fa `dev`, su tutti i backend.
- **Riferimenti (come `RESTRICT`):** `negozio_id` deve esistere; `utenti.tipo_account_id` e `utenti.negozio_id` possono essere assenti (superadmin). Eliminare un negozio ancora usato (da utenti, consegne, giornate o squadre) o un tipo account con utenti → `IntegrityError`.
- **Eliminare una consegna la toglie da tutte le giornate** (equivale a `ON DELETE CASCADE`), anche su JSON.
- **Operazioni sulle giornate:** le consegne assegnate devono esistere (`NotFoundError`) e appartenere allo stesso negozio della giornata (`ValueError`); l'operazione è tutto-o-niente. **Non modificano `versione`** (come in `dev`).
- **`giornata_completa` non esiste:** in `dev` "segna completata" imposta solo `stato = completata` sulla consegna; il flag per singola consegna nella giornata (`consegneCompletate`, colonna `completata`) non è mai stato usato né dal frontend né dal server. Viene ignorato in inserimento e non è più restituito.

### Test (suite di contratto)
`tests/test_storage_contract.py` contiene gli **stessi test per tutti i backend**: round-trip dei record, optimistic locking (anche sotto concorrenza), unicità, riferimenti, isolamento per negozio, operazioni sulle giornate, `insert_records` tutto-o-niente, metadati; più test specifici del backend json (persistenza, file corrotto, backup).
```bash
DB_BACKEND=json python -m unittest discover -s tests -v
```
⚠️ Con i backend DB la suite **svuota le tabelle**: va usata solo su un database di test, mai su quello di produzione. Solo libreria standard, nessuna dipendenza aggiuntiva.

### Backend JSON
File separati in `DATA_DIR`, ciascuno **un array di record**: `consegne.json`, `giornate.json`, `squadre.json` e 🚧 V2 `negozi.json`, `tipi_account.json`, `utenti.json`, più `meta.json` (metadati). Formato invariato rispetto a V1: i file V1 restano leggibili.
- **Lock unico** per tutte le operazioni (un solo `RLock`): il carico è minimo e si escludono i deadlock tra collezioni. (Sostituisce il "lock per collezione" ipotizzato inizialmente.)
- **Scrittura atomica** (`.tmp` + `fsync` + `os.replace()`), 2 tentativi come in V1.
- **File illeggibile → `StorageError`**: non si restituisce mai un valore di default che verrebbe poi riscritto sopra i dati.
- **Backup** in `DATA_DIR/backup/` di tutte le collezioni e di `meta.json`: **al massimo uno ogni 5 minuti** (`BACKUP_MIN_INTERVAL = 300`, non più uno a ogni scrittura) e sempre su richiesta con `backup_now()` (prima di una migrazione). Si conservano gli ultimi 20 per file.
- L'API è per record, ma internamente il backend JSON riscrive il file della collezione: adatto a installazioni piccole (scelta consapevole, vedi §10).
- Eliminare una consegna scrive prima le giornate e poi la consegna: un'interruzione lascia al più una consegna non assegnata, mai un riferimento orfano.

### Backend MySQL / PostgreSQL
Schema nativo (non blob JSON). Tabelle V1:

| Tabella | Descrizione |
|---------|-------------|
| `consegne` | Record consegna con campi reali + `articoli` (JSON/JSONB) + `extra` (JSON/JSONB) per campi futuri |
| `squadre` | Squadre con `id`, `nome`, `color_idx` |
| `giornate` | Giornate con `id`, `data`, `squadra` (nome stringa in V1), `extra` |
| `giornata_consegne` | Join giornata↔consegna con `ordine` e `completata` |

Il campo `extra` (JSONB in Postgres, JSON in MySQL) cattura eventuali campi aggiuntivi del frontend senza rompere lo schema. È pienamente leggibile da chiunque acceda al DB.

I campi camelCase del frontend (`giornoConsegna`, `fasciaOraria`, ecc.) vengono normalizzati a snake_case al salvataggio e riconvertiti alla lettura.

### Schema DB V2 🚧
Le tabelle V1 vengono **estese, non sostituite**. Sintassi MySQL; su PostgreSQL: `JSONB` al posto di `JSON`, `BOOLEAN` nativo.

```sql
-- NUOVE tabelle
CREATE TABLE negozi (
    id        VARCHAR(36) PRIMARY KEY,
    nome      VARCHAR(255) NOT NULL,
    creato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tipi_account (
    id            VARCHAR(36) PRIMARY KEY,
    nome          VARCHAR(255) NOT NULL UNIQUE,
    permessi      TEXT NOT NULL,           -- JSON array: '["consegne.leggi","stampa.pdf"]'
    creato_il     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    modificato_il TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE utenti (
    id               VARCHAR(36) PRIMARY KEY,
    username         VARCHAR(150) NOT NULL UNIQUE,
    password_hash    VARCHAR(64) NOT NULL,   -- sha256(password), hex (vedi "Limiti noti" in §5)
    tipo_account_id  VARCHAR(36) REFERENCES tipi_account(id),
    negozio_id       VARCHAR(36) REFERENCES negozi(id),
    is_superadmin    BOOLEAN NOT NULL DEFAULT FALSE,
    primo_login      BOOLEAN NOT NULL DEFAULT TRUE,
    creato_da        VARCHAR(36),
    creato_il        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ultimo_accesso   TIMESTAMP
);

-- MODIFICHE alle tabelle esistenti
ALTER TABLE consegne ADD COLUMN negozio_id VARCHAR(36) REFERENCES negozi(id);
ALTER TABLE consegne ADD COLUMN versione   INTEGER NOT NULL DEFAULT 1;
ALTER TABLE squadre  ADD COLUMN negozio_id VARCHAR(36) REFERENCES negozi(id);
ALTER TABLE squadre  ADD COLUMN versione   INTEGER NOT NULL DEFAULT 1;
ALTER TABLE giornate ADD COLUMN negozio_id VARCHAR(36) REFERENCES negozi(id);
ALTER TABLE giornate ADD COLUMN versione   INTEGER NOT NULL DEFAULT 1;
```
- **`giornate.squadra` resta una stringa (nome)** in questa iterazione. Il passaggio a `giornate.squadra_id` (FK verso `squadre`) è la **fase 6** (§11): tocca server, 5 file frontend, migrazione e schema, e si fa solo dopo che la V2 funziona.
- Per il backend JSON la struttura dei record è la stessa (§8).
- **Decisioni per lo schema SQL (passi 1b/1c):** `ON DELETE RESTRICT` da `utenti` verso `tipi_account` e `negozi` (e dalle tabelle operative verso `negozi`); `ON DELETE CASCADE` da `giornata_consegne` verso giornate e consegne; `NOT NULL` su `negozio_id` delle tabelle operative; indici su `negozio_id`; colonna di sequenza per garantire l'ordine di inserimento; `giornata_consegne` senza la colonna `completata` (non usata, vedi sopra). Chiavi in lettura sempre camelCase (nessuna chiave snake_case esce dallo storage).

### Retry e attesa DB
`init_storage()` tenta la connessione al DB fino a 10 volte (3 secondi di pausa tra un tentativo e l'altro) per gestire il caso in cui il container DB non sia ancora pronto al momento dell'avvio dell'app.

---

## 7. Frontend

Il frontend V1 è sostanzialmente invariato rispetto alla versione Windows, salvo le modifiche minime descritte in questa sezione (`api.js`: identificatore client; `render.js`: ordinamento sidebar). La V2 🚧 riscrive il layer di comunicazione e aggiunge login e pannelli di amministrazione.

### Costante API
```javascript
// store.js — stato attuale su main
export const API = `http://${window.location.hostname}:8742/api`;
```
⚠️ **Incongruenza nota su `main`:** questa documentazione indicava 8080 come "già aggiornata", ma nel codice di `store.js` c'è ancora `8742`. Funziona solo se la porta pubblicata (`APP_PORT`) è 8742.

**Decisione V2 🚧 (da applicare in fase 3):** percorso relativo `export const API = '/api';` — stessa origine del server, nessuna porta hardcoded, valido con qualsiasi `APP_PORT` o reverse proxy.

### Identificatore client (`api.js`)
```javascript
// api.js — generato una volta per sessione browser, salvato in sessionStorage
const CLIENT_ID = generateClientId(); // via crypto.getRandomValues(), NON crypto.randomUUID()
```
⚠️ **Non usare `crypto.randomUUID()`**: richiede un secure context (HTTPS o `localhost`) ed è **indisponibile** quando l'app è servita via HTTP semplice su IP LAN — lo scenario normale di questo progetto. `crypto.getRandomValues()` non ha questa limitazione ed è usato per generare un ID esadecimale a 16 byte. In V1 è inviato come header `X-Client-ID` su `fetchData`, `postData`, `pingServer` (non su `remoteLog`). In V2 🚧 va inviato su **ogni** richiesta REST (nel wrapper `_fetch` di `api.js`).

### Stato globale (`store.js`)
```javascript
// V1 (attuale)
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
**V2 🚧:** si aggiungono `currentUser` e `localTimestamps`; si rimuovono `isDirty` e `pingFailCount`; `PING_FAIL_THRESHOLD` diventa 1.

### Ciclo di vita dei dati
**V1 (attuale)**
1. Al caricamento: `loadData()` → GET `/api/data` → popola `db` → `renderAll()`
2. Ogni 8 secondi: polling se `serverOnline && !isDirty`
3. Ogni 2 secondi: ping → se 2 fallimenti → `showDisconnectOverlay()`
4. Ogni modifica: `markDirty()` → 600ms debounce → `saveData()` → POST `/api/data`

**V2 🚧**
1. Al caricamento: si cerca il token in `sessionStorage`; se assente o scaduto (401) → overlay di login
2. Login: `GET /api/auth/challenge` → calcolo Challenge-Response (`sha256.js`) → `POST /api/auth/login` → token + permessi in `sessionStorage`
3. Se `must_change_password` → overlay di cambio password obbligatorio
4. Superadmin → solo pannello admin (`modal-admin.js` caricato dinamicamente); altri utenti → app operativa, UI condizionata da `hasPermesso()`
5. Ogni 8 secondi: `GET /api/stato` → si scaricano solo le categorie cambiate
6. Ogni 2 secondi: ping → 1 fallimento → `showDisconnectOverlay()`
7. Ogni modifica: chiamata REST immediata → la risposta contiene il db aggiornato → `applyServerResponse()`. In caso di 409 si mostra "modificata da un altro utente. Ricarica e riprova."
8. 401 su qualunque chiamata → logout e ritorno al login

**Token lato client:** `sessionStorage` (cancellato alla chiusura del browser), inviato con header `X-Session-Token`.

### Grafo dipendenze JS
```
V1 (attuale)
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

V2 🚧
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
  ├── modal-admin.js → api, permessi, utils, sha256  [caricato dinamicamente solo per il superadmin]
  ├── squadre.js → store, sync, api, render, utils
  └── stampa.js → store, utils
```
Nessuna dipendenza circolare.

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

**Ordinamento sidebar:** `renderSidebar()` in `render.js` mostra le giornate in ordine cronologico **decrescente** (più recente in cima): `sorted.sort((a, b) => b.data.localeCompare(a.data))`. L'ordine è solo di presentazione, non ha impatto sui dati né sulla vista giornata selezionata.

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

### Campi e collezioni aggiunti in V2 🚧
Valido per tutti i backend. **Gli ID V2 sono generati dal server** con prefisso (`c_` consegne, `g_` giornate, `sq_` squadre, `n_` negozi, `ta_` tipi account, `u_` utenti, es. `c_b2095b436467ec09`). Gli ID V1 esistenti vengono **conservati** dalla migrazione, non riscritti.

**`consegne`, `giornate`, `squadre`:** ogni record guadagna due campi.
```json
{ "id": "c_abc123", "negozio_id": "n_abc123", "versione": 1, "...": "campi V1 invariati" }
```
`giornate.squadra` resta una stringa (nome) fino alla fase 6 (§11).

**`negozi`**
```json
{ "id": "n_abc123", "nome": "Negozio principale", "creato_il": "2026-06-18T10:00:00" }
```

**`tipi_account`** (globali, condivisi da tutti i negozi)
```json
{
  "id": "ta_abc123",
  "nome": "Amministratore",
  "permessi": ["consegne.leggi", "utenti.leggi", "utenti.crea", "tipi_account.leggi"],
  "creato_il": "2026-06-18T10:00:00",
  "modificato_il": "2026-06-18T10:00:00"
}
```

**`utenti`**
```json
{
  "id": "u_abc123",
  "username": "mario.rossi",
  "password_hash": "hex64chars (sha256(password))",
  "tipo_account_id": "ta_xyz789",
  "negozio_id": "n_abc123",
  "is_superadmin": false,
  "primo_login": false,
  "creato_da": "u_superadmin",
  "creato_il": "2026-06-18T10:00:00",
  "ultimo_accesso": "2026-06-18T14:30:00"
}
```
Il superadmin è `{"id": "u_superadmin", "username": "superadmin", "tipo_account_id": null, "negozio_id": null, "is_superadmin": true, ...}`.

---

## 9. Flusso operativo tipico

### Aggiungere una consegna
Lista → "Nuova consegna" → compila form → aggiungi articoli → Salva

### Programmare una consegna
Giornate → seleziona o crea giornata → "Aggiungi consegna" → seleziona dalla lista "in attesa" → Aggiungi

### Rimuovere da una giornata
Click ✕ sulla card → la consegna torna "in_attesa", `giornoConsegna` e `fasciaOraria` svuotati

### Setup iniziale V2 🚧
1. Primo avvio: login come `superadmin` / `admin` → cambio password obbligatorio
2. Pannello superadmin → **Negozi** → crea il primo negozio
3. **Tipi account** → crea un tipo (es. "Amministratore") scegliendo i permessi
4. **Utenti** → crea un utente assegnandogli negozio e tipo account
5. Logout; login con il nuovo utente → operatività sul proprio negozio

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
| `squadra` come stringa in V1 | Retrocompatibilità; diventerà `squadra_id` (fase 6 della V2, vedi §11) |
| Healthcheck Python puro | Nessuna dipendenza da curl/wget nell'immagine |
| Log HTTP agganciati al logger (`LOG_LEVEL`) | Log richieste utili in debug, silenziosi di default in produzione |
| Contatore client per `X-Client-ID` (non IP) | In Docker più browser condividono lo stesso IP (NAT); l'IP da solo sottostima/sovrastima il conteggio |
| `crypto.getRandomValues()` invece di `crypto.randomUUID()` | `randomUUID()` richiede secure context, indisponibile su HTTP semplice via IP LAN (scenario normale del progetto) |
| Sidebar giornate in ordine cronologico decrescente | Le giornate più recenti/imminenti sono quelle consultate più spesso |

### Frontend e dati
| Decisione | Motivazione |
|-----------|-------------|
| Scrittura atomica (tmp + rename) | Protezione da corruzione a metà scrittura |
| Lettura fresca prima di ogni scrittura | Previene sovrascritture con accesso quasi-contemporaneo (V1; in V2 sostituita dall'optimistic locking per record) |
| 2 tentativi poi crash | Preferibile perdere l'ultima modifica che avere dati corrotti (V2: comportamento da rivalutare con lo storage per record, vedi §11) |
| Ping HTTP (non ICMP) | ICMP bloccato dai firewall di default |
| Cognome Nome (non Nome Cognome) | Richiesta esplicita del cliente — **non invertire mai** |
| Stessa data permessa con squadre diverse | Richiesta esplicita per gestire squadre parallele |
| Schermata bloccante senza istruzioni specifiche | I client usano solo il browser |
| Tema auto da OS + switch manuale | Usabilità su monitor diversi, salvato in `localStorage` |
| `articoli[]` invece di 3 campi singoli | Più prodotti per consegna, retrocompatibile |
| `tipoConsegna` per-articolo | Consegne miste con tipi installazione diversi per articolo |

### Autenticazione, permessi e multi-tenancy (V2) 🚧
| Decisione | Motivazione |
|-----------|-------------|
| Challenge-Response SHA-256 | `crypto.subtle` non disponibile su HTTP su IP LAN |
| `password_hash` = `sha256(password)` | Coerente con il Challenge-Response; limiti documentati in §5 |
| Token in `sessionStorage` (non `localStorage`) | Auto-cancellato alla chiusura del browser |
| Sessioni e challenge in memoria | Semplicità; implica istanza unica (§4) e logout al riavvio |
| Superadmin senza operatività | Separazione netta: l'admin di sistema non tocca i dati aziendali |
| Superadmin identificato da colonna `is_superadmin` | Esplicito e leggibile nel DB (id comunque fisso `u_superadmin`) |
| Tipi account globali (non per negozio) | Semplicità di gestione; solo il superadmin li crea |
| `tipi_account.gestisci` e `negozi.gestisci` solo superadmin | Non assegnabili ad altri account |
| Dipendenze tra permessi come avvisi, senza auto-selezione | Più trasparente: chi configura deve essere consapevole |
| Optimistic locking con `versione` | Protegge da scritture concorrenti; atomico nel layer di storage |
| **Storage per singolo record su tutti i backend** | Un layer di astrazione con più DB perde utilità se si riscrive l'intera tabella a ogni salvataggio; su DB permette `UPDATE ... WHERE versione = ?` atomico e non rischia i dati degli altri negozi |
| Utenti, negozi e tipi account dentro `storage.py` | Nessun dato fuori dal layer di storage; container `read_only`; stesso backend per tutto |
| Polling via timestamp | Evita render inutili; scarica solo ciò che è cambiato |
| Risposta delle scritture = db aggiornato del negozio | Il client è sempre in sync dopo ogni operazione propria |
| Log 100% server-side | Non aggirabile dal client; auditabilità reale |
| `modal-admin.js` caricato dinamicamente | Non caricato per utenti normali; separazione netta |
| `migrate.py` con tutti e 3 i backend come sorgente e destinazione | Il cliente può cambiare backend; la migrazione V1→V2 non deve dipendere dal backend in uso |
| `squadra_id` rimandato (fase 6) | Cambia server, 5 file frontend, schema e migrazione: farlo insieme al resto aumenta il rischio di bug |

### Note per modifiche future (V2) 🚧
- **Non usare `crypto.subtle`**: non disponibile su `http://IP:porta` da browser moderni
- **Non cambiare lo schema** (campi, tabelle) senza aggiornare `storage.py` su **tutti e tre** i backend e `migrate.py`
- **Non cambiare il significato di `password_hash`** (`sha256(password)`): richiederebbe di resettare tutte le password
- **Non ripristinare `f_tipoProdotto` / `f_codiceProdotto` / `f_tipoConsegna` nel DOM**: non esistono più (tipo e codice sono per articolo)
- **`expandedRowId`** viene resettato a `null` se la riga viene eliminata
- L'ordine **Cognome Nome** è intenzionale e definitivo
- I **negozi** si creano dal pannello superadmin: non modificare i dati a mano in produzione
- Nuovo endpoint operativo: verificare token → permesso → `negozio_id` (ordine in §5), filtrare per negozio, loggare con categoria `[DATI]`

---

## 11. Stato di implementazione V2

Questa sezione traccia l'avanzamento della V2 sul branch `v2-docker` (partito da `main`). **Non implementare una fase senza esplicita autorizzazione.** Il design (endpoint, auth, permessi, schema) è descritto nelle sezioni §5-§8; qui ci sono fasi, metodo e punti aperti.

### Fasi
| Fase | Contenuto | Stato |
|------|-----------|-------|
| 0 | Documentazione (`AGENTS.md`, `README.md`) | ✅ completata, in revisione |
| 1 | `storage.py`: schema V2 e API per singolo record su json/mysql/postgres, con suite di test condivisa | 🔶 in corso — 1a ✅ (API, backend json, suite) · 1b PostgreSQL ⬜ · 1c MySQL ⬜ · 1d marcatore schema ⬜ · 1e documentazione finale ⬜ |
| 2 | `server.py`: Challenge-Response, sessioni, endpoint REST, permessi, filtro `negozio_id`, `/api/stato`, creazione superadmin | ⬜ |
| 3 | Frontend V2 (vedi metodo sotto) | ⬜ |
| 4 | `migrate.py` | ⬜ |
| 5 | Test integrato: migrazione → primo login superadmin → negozio → tipo account → utente → login → operatività, su tutti e 3 i backend | ⬜ |
| 6 | `squadra_id` al posto del nome squadra nelle giornate (server, `render.js`, `giornate.js`, `stampa.js`, `utils.js`, `modal-consegna.js`, schema, migrazione) | ⬜ rimandata |

Ogni fase è un commit separato (o gruppo di commit) rivisto prima di passare alla successiva.

### Metodo e regole
- **Non riscrivere a memoria il codice del branch `dev`:** si parte dai file di `dev` (`git show origin/dev:<file>`) e si adattano.
- **Fase 2:** la logica auth/REST di `dev` si porta mantenendo i nomi di funzioni ed endpoint; cambia solo lo strato dati (da `_read_json`/`_write_json` a `storage.py`). Rimuovere ciò che `dev` aveva e Docker non vuole (tray, `server.lock`, file accanto al codice).
- **Fase 3:** i file frontend modificati sia su `main` sia su `dev` (`api.js`, `render.js`, `utils.js`, `modal-consegna.js`, `stampa.js`, `components.css`) vanno uniti **con merge a tre vie file per file** (base `9da9f00`), non copiati. Interventi di `main` da conservare: `X-Client-ID` su ogni richiesta, sidebar giornate in ordine decrescente, nuovi tipi di installazione (`ins_incasso`, `ins_muro`, `ins_sbs`). Fix di `dev` da conservare: `a0c9bbb` (5 bug core), `552682a` (form inline per cambio password), `f05bf13` (timer toast), `6b2b0be` (pulizia codice morto), `b19ba3a` (modal utenti per admin). Applicare la decisione `API = '/api'` (§7).
- **Fase 1:** ogni comportamento si verifica su tutti e tre i backend; un test non è valido se passa solo su JSON.
- Dopo ogni fase: rilettura dei blocchi modificati, verifica di coerenza nomi funzioni/endpoint (§1.3) e aggiornamento di questa tabella.

### Requisiti di `migrate.py` (fase 4) 🚧
- **Sorgente e destinazione**: ciascuno dei tre backend (json, mysql, postgres), in qualsiasi combinazione, selezionabili da configurazione/argomenti (interfaccia da definire).
- Trasformazione V1 → V2: crea il negozio "Negozio principale"; aggiunge `negozio_id` e `versione: 1` a tutte le consegne, giornate e squadre; crea il superadmin (`is_superadmin = true`, password di default `admin` con hash pre-calcolato, `primo_login = true`); crea `tipi_account` vuoto. Gli ID V1 non vengono modificati; `giornate.squadra` resta stringa.
- **Protezioni** (proposte): backup completo della sorgente prima di scrivere; blocco contro la doppia esecuzione (file flag nel volume o tabella `migrazioni`); sorgente mai modificata; verifica finale con conteggio record per collezione tra sorgente e destinazione.
- Dopo la migrazione nessun utente oltre al superadmin esiste: vanno creati dal pannello (§9).

### Punti aperti (da decidere prima o durante la fase indicata)
| # | Punto | Fase |
|---|-------|------|
| 1 | ~~Firma dell'API di `storage.py`~~ definita e implementata per json (§6); da riconfermare a fine fase 1 | 1 |
| 2 | ~~Vincoli SQL~~ deciso: `RESTRICT`, `NOT NULL` su `negozio_id`, indici, colonna di sequenza (§6); da applicare in 1b/1c | 1 |
| 3 | Comportamento del server su `StorageError`: crash (V1: "2 tentativi poi crash") oppure risposta 500 mantenendo il server attivo | 1-2 |
| 4 | Timestamp di polling per negozio invece che globali | 2 |
| 5 | `migrate.py`: migrazione sullo stesso backend (in-place o su nuova destinazione), eventuali dati dell'era `dev` da preservare, rapporto con `import_data.py` (resta separato o viene assorbito) | 4 |
| 6 | Ambiente di sviluppo Docker isolato dalla produzione (es. `compose.dev.yaml` con progetto, volume e porta separati) | prima della fase 1 |

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
