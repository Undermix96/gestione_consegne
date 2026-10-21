# AGENTS.md — Gestione Consegne

Documento di contesto per agenti AI. Descrive stato attuale del progetto, architettura, decisioni prese, convenzioni adottate, stato di implementazione V2 e istruzioni operative per l'agente.

---

> **Stato del branch `v2-docker`:** questo documento descrive la **V2** (obiettivo del branch). **`storage.py` è già V2** (fase 1) e lo è anche **`server.py`** (fase 2, collaudato con `tests/test_server.py` su json, PostgreSQL e MySQL); anche il **frontend** (fase 3, collaudato con controlli statici in Node e con un giro completo nel browser contro il server V2). Tutte le fasi sono completate, compreso il collaudo integrato (fase 5), la `squadra_id` obbligatoria (fase 6) e il backup dei database (fase 7), vedi [§11](#11-stato-di-implementazione-v2). **🚧 V2** indica una funzionalità della V2 non ancora presente su `main`; dove è già implementata e collaudata su questo branch il titolo lo dice (es. "implementata", ✅). Il design V2 proviene dal branch `dev` (versione Windows, mai andata in produzione) ed è stato adattato a Docker e allo storage a più backend.

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
├── storage.py              # Astrazione backend dati (json/mysql/postgres): V1 legacy + V2 per singolo record ✅
├── import_data.py          # Importazione one-shot da dati.json legacy (V1)
├── migrate.py              # 🚧 V2: migrazione V1→V2 e tra backend (vedi §11, fase 4) ✅
├── backup.py               # 🚧 V2: backup dei database (pg_dump / mysqldump), elenco, `python backup.py` (fase 7) ✅
├── compose.migrate.yaml    # 🚧 V2: la migrazione come stack autonomo (Portainer, DSM)
├── tests/                  # 🚧 V2: suite di contratto di storage.py (non inclusa nell'immagine)
│   ├── test_storage_contract.py
│   ├── js/run.mjs          # 🚧 V2: controlli statici del frontend e test di sha256.js (Node, solo nei test) ✅
│   ├── test_migrate.py     # 🚧 V2: test di migrate.py (logica pura e da un capo all'altro) ✅
│   ├── test_backup.py      # 🚧 V2: test di backup.py (dump veri su postgres/mysql, errori, versioni degli strumenti) ✅
│   ├── integrazione_*.py   # 🚧 V2: collaudo integrato sul sistema vero (processi, HTTP, tutti i backend, backup e ripristino) ✅
│   ├── dbtool.py           # strumento dei test di integrazione (opera su un backend per processo)
│   ├── db-init/            # script che creano il secondo database di test (sorgente V1)
│   ├── stack.sh            # prova con le immagini vere (compose, docker, stack): da lanciare sull'host ✅
│   ├── test_server.py      # 🚧 V2: test del server (auth, permessi, multi-negozio, REST) ✅
│   └── run_all.sh          # esegue la suite su ogni backend (TEST_BACKENDS)
├── compose.test.yaml       # 🚧 V2: database temporanei per i test (separato dalla produzione)
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
    ├── clientid.js         # 🚧 V2: X-Client-ID di questa scheda (modulo senza dipendenze) ✅
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
| `BACKUP_INTERVAL` | `21600` | Secondi tra due backup automatici (6 ore), solo se ci sono state modifiche; `0` = nessun backup automatico (fase 7) |
| `BACKUP_KEEP` | `30` | Backup conservati per tipo, per tutti i backend (fase 7) |
| `LOG_FILE_MAX_BYTES` | `5242880` | Dimensione massima di `DATA_DIR/log/server.log` prima della rotazione (5 MB); `0` = nessun log su file (resta solo stdout) |
| `LOG_FILE_KEEP` | `10` | File di log ruotati conservati (`server.log.1` … `.10`) |
| `LOGIN_MAX_FAIL_IP` | `20` | Tentativi di login falliti per IP in 5 minuti prima del blocco (429); `0` = limite per IP disattivato (restano quelli per username) |
| `CHALLENGE_MAX_IP` | `50` | Challenge di login vivi per IP; `0` = nessun limite per IP (SEC-06) |
| `TRUSTED_PROXIES` | _(vuoto)_ | IP o reti (CIDR) dei reverse proxy fidati, separati da virgola: solo per le richieste che arrivano da lì si usa l'IP reale dei client (`X-Forwarded-For`) |
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
- **Dati V1 → il container V2 non parte:** `init_storage_v2()` rifiuta archivi V1 o schemi non validi (§6). Con `restart: unless-stopped` Docker riavvia il container in ciclo e il motivo compare nel log: si risolve migrando (`migrate.py`) o puntando a un archivio nuovo.
- **Migrazione:** `migrate.py` (✅, §11 fase 4) porta i dati V1 (o il `dati.json` di Windows) allo schema V2 e permette di passare da un backend all'altro; si configura solo con variabili d'ambiente, cartelle montate e comando, quindi gira da compose, da `docker run` e dalla GUI di Docker (DSM 7.1, Portainer). `import_data.py` resta intatto, solo per le immagini V1.
- **Variabili d'ambiente:** lo storage V2 non introduce nuove variabili per l'app (le `TEST_*` riguardano solo i test); da riconfermare in fase 4.

---

## 5. Server Python (`server.py`)

### Costanti
```python
PORT     = int(os.environ.get("PORT", 8080))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 🚧 V2
SESSION_TTL   = 7200   # 2 ore di inattività
SESSION_MAX_AGE = 43200  # 12 ore: durata massima assoluta della sessione (SEC-07)
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

### Endpoint HTTP — V2 (implementati in `server.py`, fase 2 ✅)
Sostituiscono `GET/POST /api/data` e `POST /api/log`. `GET /api/ping` resta senza autenticazione obbligatoria (usato dall'healthcheck Docker); se il client invia `X-Session-Token` la sessione non viene rinnovata e, se non è più valida, la risposta è 401 (così il client scopre la scadenza). Anche `GET /api/stato` non rinnova la sessione: la scadenza (2 ore) misura l'inattività dell'utente, non la presenza di una scheda aperta; ogni altra richiesta la rinnova. `GET /*` (file statici) invariato.

| Metodo | Path | Auth | Permesso richiesto | Descrizione |
|--------|------|------|--------------------|-------------|
| GET | `/api/auth/challenge` | No | — | Genera challenge monouso |
| POST | `/api/auth/login` | No | — | Login → token + permessi |
| POST | `/api/auth/logout` | Token | — | Invalida sessione |
| POST | `/api/auth/change-password` | Token | — | Cambia propria password |
| GET | `/api/ping` | Opzionale | — | Heartbeat + contatore client |
| GET | `/api/stato` | Token | — (no superadmin) | Timestamp categorie per polling |
| GET | `/api/backup` | Token | superadmin | Elenco dei backup (nome, tipo, data, dimensione), intervallo e numero conservati |
| POST | `/api/backup` | Token | superadmin | Backup immediato (snapshot json o dump SQL); risponde a backup concluso con l'elenco aggiornato (409 se uno è già in corso, 500 se fallisce) |
| GET | `/api/log` | Token | superadmin | Elenco dei file di log (nome, dimensione, ultima modifica), `attivo`, `max_bytes`, `conservati` |
| GET | `/api/log/download/:nome` | Token | superadmin | Scarica un file di log (`server.log`, `server.log.N`: lista bianca) come allegato `text/plain`, oppure `tutti` per uno zip; 404 per ogni altro nome |
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
| POST | `/api/giornate` | Token | `giornate.crea` | Crea giornata (richiede `squadra_id`: obbligatorio, del proprio negozio) |
| DELETE | `/api/giornate/:id` | Token | `giornate.elimina` | Elimina giornata |
| POST | `/api/giornate/:id/assegna` | Token | `giornate.assegna` | Aggiunge consegne |
| DELETE | `/api/giornate/:id/assegna/:cid` | Token | `giornate.assegna` | Rimuove consegna |
| PUT | `/api/giornate/:id/riordina` | Token | `giornate.riordina` | Riordina consegne |
| PUT | `/api/giornate/:id/consegne/:cid/completa` | Token | `giornate.segna_completata` | Segna completata |
| GET | `/api/squadre` | Token | `squadre.leggi` | Lista squadre del negozio |
| POST | `/api/squadre` | Token | `squadre.gestisci` | Crea squadra |
| PUT | `/api/squadre/:id` | Token | `squadre.gestisci` | Modifica squadra |
| DELETE | `/api/squadre/:id` | Token | `squadre.gestisci` | Elimina squadra (409 se ha giornate) |

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
giornate.leggi             → squadre.leggi   (il nome della squadra si legge da squadre)
giornate.crea              → giornate.leggi, squadre.leggi
giornate.elimina           → giornate.leggi
giornate.assegna           → giornate.leggi, consegne.leggi
giornate.riordina          → giornate.leggi
giornate.segna_completata  → giornate.leggi
squadre.gestisci           → squadre.leggi
stampa.pdf                 → giornate.leggi, consegne.leggi, squadre.leggi
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

I permessi vengono copiati nella sessione al login. Se i permessi di un tipo account cambiano, le sessioni di tutti i suoi utenti vengono chiuse subito (devono rifare il login: SEC-07); rinominare il tipo non le tocca. Anche il **cambio tipo account** di un utente invalida immediatamente le sessioni dell'utente.

### Utente senza tipo account
Un utente con `tipo_account_id: null` viene bloccato al login con messaggio "Account non configurato. Contatta l'amministratore." (escluso superadmin).

### Regole lato server (hardcoded, non aggirabili dal frontend) 🚧
- Superadmin non eliminabile, non modificabile tranne la propria password
- Utente con `tipo_account_id: null` non può fare login (escluso superadmin)
- Tipo account non eliminabile se ha utenti associati
- Negozio non eliminabile se ha utenti associati
- Modifica dei permessi di un tipo account: invalida subito le sessioni dei suoi utenti (SEC-07); la sessione dura al massimo `SESSION_MAX_AGE` (12 ore) anche con attività continua
- Cambio del tipo account di un utente: invalida immediatamente le sessioni di quell'utente
- Superadmin riceve 403 su tutti gli endpoint operativi (`/api/consegne`, `/api/giornate`, `/api/squadre`, `/api/stato`)
- Il server filtra sempre per `negozio_id` su tutti gli endpoint operativi
- Un utente non può eliminare se stesso
- **Nessuna escalation di privilegi (SEC-02):** chi non è superadmin può creare un utente o cambiargli il tipo solo con un tipo i cui permessi sono contenuti nei propri, e può reimpostare la password, cambiare il tipo o eliminare solo utenti i cui permessi attuali sono contenuti nei propri (403 altrimenti). Funzione `check_not_escalating()` in `server.py`, usata da `h_create_utente`, `h_set_tipo` e `target_user()`
- **Validazione delle consegne (SEC-03):** i campi noti sono testi ≤ 2000 caratteri; `articoli` è una lista di ≤ 50 oggetti con solo `tipoConsegna` (valore dell'elenco), `tipo`, `codice`, `desc`; i campi sconosciuti restano ammessi (conservati come `extra`) ma al massimo 20 per richiesta e ≤ 2000 caratteri ciascuno
- **Header di sicurezza (SEC-04):** ogni risposta porta CSP (`default-src 'self'`, `frame-ancestors 'none'`, `unsafe-inline` solo per gli script/stili inline di `index.html`), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`. Non caricare risorse esterne dal frontend
- **Challenge (SEC-06):** al massimo `CHALLENGE_MAX_IP` (50) vivi per IP (429 oltre; `0` = nessun limite). Se i 1000 totali sono tutti vivi si scarta il più vecchio invece di rifiutare (503): chi inonda il server non può bloccare i login
- **Log su una riga (SEC-08):** `log()` sostituisce con `?` ogni carattere di controllo (a capo, ESC, U+2028/9) e tronca a 1000 caratteri: username, nomi e note arrivano dai client e non devono poter falsificare righe di audit. Usare sempre `log()`/`ctx.dlog()` per messaggi con dati dei client
- **`X-Client-ID` (SEC-08):** conta solo se è `[0-9A-Za-z_-]{8,64}` (il frontend manda 32 esadecimali); altrimenti si usa l'IP. Al massimo 10.000 client tracciati
- **Operazioni composte in mutua esclusione (SEC-10):** gli handler che leggono, controllano e poi scrivono su più record (`@serialized`: eliminare consegne, creare/eliminare giornate, assegnare, rimuovere, riordinare, completare, creare/modificare/eliminare squadre) girano sotto un lock di processo (`ops_lock`), con il corpo della richiesta letto prima. Funziona perché l'istanza è unica (§4); con più repliche servirebbe un controllo nello storage. Così non si elimina una giornata mentre le si assegnano consegne e non nascono due squadre con lo stesso nome
- **Assegnazione annullata se fallisce a metà (SEC-10):** se dopo `giornata_assegna` l'aggiornamento di stato di una consegna fallisce, le consegne appena assegnate vengono tolte dalla giornata e ripristinate (risposta 500). `giornata_rimuovi` + cambio di stato non ha questa compensazione
- **`stato: completata` (SEC-10):** impostarlo con `POST/PUT /api/consegne` richiede `giornate.segna_completata`, come l'endpoint dedicato (non serve se la consegna è già completata)
- **Errori di validazione (SEC-10):** i `ValueError` dello storage rispondono 400 `Dati non validi` senza dettagli; il motivo è solo nel log
- **Limiti del socket (SEC-01):** `Handler.timeout = 15` s (connessioni mute o inviate a pezzi vengono chiuse); `Content-Length` negativo o non numerico → 400, oltre `MAX_BODY` → 413
- Gli errori di concorrenza (`versione` non coincidente) rispondono **409 Conflict**; token mancante/scaduto **401**; permesso o negozio non coerente **403**

### Optimistic locking 🚧
- Ogni entità operativa ha `versione` (intero, parte da 1)
- Il client include `versione` nelle richieste `PUT`
- Se `client_versione != versione` salvata → **409 Conflict** con messaggio "la consegna/giornata è stata modificata da un altro utente. Ricarica e riprova."
- La `versione` viene incrementata a ogni scrittura riuscita
- **Il confronto è atomico nel layer `storage.py`** (su SQL: lock di riga `SELECT ... FOR UPDATE`, confronto di `versione` e `UPDATE` nella stessa transazione; su JSON: sotto il lock unico del backend). Il server non fa read-then-write separati.

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
Categorie: `[AUTH]`, `[UTENTI]`, `[DATI]`, `[NEGOZI]`, `[TIPI_ACCOUNT]`, `[BACKUP]`, `[LOG]`.

**Log su file e download (superadmin):** oltre che su stdout, il log va in `DATA_DIR/log/server.log` (stesso formato, `RotatingFileHandler`, `LOG_FILE_MAX_BYTES` × `LOG_FILE_KEEP`, permessi `0600`; richiede il volume `/data`, come i backup). Se la cartella non è scrivibile o `LOG_FILE_MAX_BYTES=0` si prosegue solo con stdout. Il superadmin vede l'elenco e scarica i file dalla scheda "Log" del pannello (nessuna anteprima): il download usa `fetch` con `X-Session-Token` e salva il blob (il token non va mai nell'URL). Il server accetta solo i nomi `server.log[.N]` (nessun path traversal) e registra ogni download con `[LOG]`. Le risposte non JSON passano da `FileResponse`/`Handler.send_file()`. I log contengono username e IP. L'IP nei log di autenticazione è quello visto dal container (in Docker può essere quello del gateway, vedi "Contatore client connessi").

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
- **Rate limiting dei tentativi di login (SEC-06):** per username (`LOGIN_MAX_FAIL_USER` = 10 fallimenti in 5 minuti, senza distinzione di maiuscole) e per IP (`LOGIN_MAX_FAIL_IP` = 20, `0` = disattivato) → 429, anche con la password giusta finché la finestra non scade; vale anche per il cambio password con password attuale errata. Un login riuscito azzera il contatore dell'username. Contatori in memoria (azzerati al riavvio). Conseguenza accettata: chi conosce un username può bloccarlo per 5 minuti (anche il superadmin).
  - **IP dei client (NAT):** `ctx.ip` è l'IP della connessione, oppure — solo se la connessione arriva da un indirizzo in `TRUSTED_PROXIES` — il primo indirizzo non fidato di `X-Forwarded-For` letto da destra (`client_ip()`); un header malformato o senza proxy fidati è ignorato. Se in produzione tutti i client appaiono con lo stesso IP (Docker Desktop, alcuni NAS) impostare `LOGIN_MAX_FAIL_IP=0` e `CHALLENGE_MAX_IP=0`, oppure `TRUSTED_PROXIES` se c'è un reverse proxy. `X-Client-ID` non si usa per i limiti: lo sceglie il client.
  - **Rallentamento globale:** oltre `LOGIN_DELAY_THRESHOLD` (10) fallimenti in 60 s, da chiunque, ogni risposta di errore del login (e del cambio password) attende `0.25 s × fallimenti in eccesso`, al massimo 3 s. Non blocca nessuno e non dipende dall'IP: contrasta lo spray di password (una password su molti username), che i limiti per username non fermano. Chi ha la password giusta non aspetta. L'attesa tiene occupato il thread della richiesta, ma non c'è un tetto ai thread: un attacco massiccio resta un limite noto
- **Sessioni e challenge in memoria:** perse a ogni riavvio; incompatibili con più repliche (vedi §4).

### Audit di sicurezza (2026-10-20) — esito e stato 🚧
Revisione del codice di `v2-docker` (server, storage, frontend, Docker). Non sono emerse SQL injection, path traversal, deserializzazione insicura né XSS sfruttabili; CSRF non applicabile (token in header custom, non cookie). Problemi trovati e stato:

| ID | Sev. | Problema | Stato |
|----|------|----------|-------|
| SEC-01 | Alta | DoS non autenticato: `Content-Length: -1` bloccava un thread su `rfile.read(-1)`; nessun timeout sul socket (slowloris) | ✅ corretto |
| SEC-02 | Alta | Escalation di privilegi: `utenti.crea/modifica/elimina` permettevano di assegnare tipi più potenti o di reimpostare/eliminare utenti con più permessi | ✅ corretto |
| SEC-03 | Media | `articoli` e `tipoConsegna` non validati: un dato malformato (`[null]`, `"constructor"`) rompe il rendering per tutto il negozio; nessun limite ai campi extra | ✅ corretto (server: struttura di `articoli`, `tipoConsegna`, testo ≤ 2000 caratteri, max 20 campi extra; client: `Object.hasOwn` in `tipoBadge`/`statoPill`) |
| SEC-04 | Media | Mancano gli header di sicurezza (CSP, `X-Frame-Options`, `nosniff`, `Referrer-Policy`); `css/layout.css` importa i font da Google (contrario al vincolo "nessuna dipendenza esterna") | ✅ corretto (header in `Handler.end_headers`, `@import` rimosso: font di sistema) |
| SEC-05 | Media | Credenziali su HTTP: `password_hash` e `nuova_hash` viaggiano in chiaro, SHA-256 senza salt (attacco a dizionario sul challenge osservato), token in chiaro; la lunghezza minima della password è solo lato client | accettato (vincolo HTTP, vedi "Limiti noti"); valutare HTTPS o KDF |
| SEC-06 | Media | Nessun rate limiting su login e `/api/auth/challenge` (1000 challenge vive bloccano i login con 503); password iniziale `admin` | ✅ corretto (limiti per IP e username, rallentamento globale, challenge per IP; configurabile per chi sta dietro un NAT; la password iniziale `admin` resta fino al primo accesso) |
| SEC-07 | Media | La revoca di permessi di un tipo account non vale per le sessioni attive (scadenza scorrevole, nessun limite assoluto) | ✅ corretto (sessioni chiuse al cambio dei permessi del tipo, durata massima 12 ore) |
| SEC-08 | Bassa | Log injection (username e campi consegna nei log senza sanificazione); `X-Client-ID` arbitrario sul `/api/ping` pubblico | ✅ corretto (log sanificati, `X-Client-ID` validato e limitato) |
| SEC-09 | Bassa | Handler inline `onclick="f('${escHtml(id)}')"`: l'entità `&#39;` torna `'` prima del JS; non sfruttabile finché gli id sono generati dal server | 🔲 latente |
| SEC-10 | Bassa | Race minori: assegnazione consegne non atomica, eliminazione giornata concorrente con assegnazione, nome squadra duplicato, `stato: completata` via `PUT` senza `giornate.segna_completata`, testo degli errori di validazione al client | ✅ corretto (lock di processo sulle operazioni composte, assegnazione annullata se fallisce a metà, `completata` con permesso dedicato, errori senza dettagli); resta senza compensazione il rimuovi + cambio stato |

Carenze architetturali annotate: nessun limite di risorse né `cap_drop`/`no-new-privileges` nel compose; porta pubblicata su tutte le interfacce; immagine `:latest`; chiavi GPG dei repository PGDG/MySQL scaricate senza verifica dell'impronta; nessun `pip-audit`; file di dati e backup json con umask predefinita (contengono gli hash); i 403 non sono loggati.

---

## 6. Storage layer (`storage.py`)

### Stato attuale (V1)
```python
init_storage()       # chiamata una volta all'avvio del server
read_data()          # → {"consegne": [], "giornate": [], "squadre": []}
write_data(data)     # salva il dict completo
make_backup()        # snapshot JSON (no-op per DB)
```
Con il server V2 (fase 2) `read_data()`/`write_data()` **non saranno più usate dal server** (oggi `server.py` è ancora V1 e le usa): restano solo come strumenti per `import_data.py` e per leggere i dati V1 in `migrate.py`.

### Principi V2 🚧
- **Accesso per singolo record**, su tutti i backend: nessuna scrittura "tutta la tabella". I backend SQL non fanno più `DELETE` + reinserimento di tutto: una scrittura fallita non può toccare i dati degli altri negozi.
- **Optimistic locking atomico nel layer di storage:** confronto di `versione`, scrittura e incremento avvengono in un'unica sezione atomica (lock di riga su SQL, lock del backend su json); se la versione non coincide si solleva `ConflictError` (che il server traduce in 409).
- **Il filtro per `negozio_id` si applica nella query/lettura**, non dopo aver caricato tutto.
- **Operazioni multi-riga in transazione** (backend SQL): assegnazione, rimozione e riordino delle consegne di una giornata.
- **Stessa semantica su json/mysql/postgres:** un comportamento si considera corretto solo se identico sui tre backend (suite di test condivisa, fase 1).
- Nessun dato applicativo fuori da `storage.py`: anche `utenti`, `negozi`, `tipi_account` passano da qui.

### Collezioni V2 🚧
`consegne`, `giornate`, `squadre`, `negozi`, `tipi_account`, `utenti` (+ tabella di join `giornata_consegne` sui backend SQL).

### Interfaccia pubblica V2 🚧 (implementata e collaudata su json, PostgreSQL e MySQL — fase 1)
```python
init_storage_v2(ignore_migration=False) # il server V2 usa questa al posto di init_storage(); verifica lo schema
list_records(collection, filters=None)  # ordine di inserimento; filtri di uguaglianza
get_record(collection, rid)             # → dict | None
insert_record(collection, record)       # `id` fornito dal chiamante; versione=1 dove prevista
insert_records(collection, records)     # una collezione, tutto-o-niente (usata da migrate.py)
update_record(collection, rid, changes, expected_versione=None)  # merge; incrementa versione
delete_record(collection, rid)          # → True | False (non esisteva)
giornata_assegna(giornata_id, consegna_ids)       # aggiunge in coda, idempotente
giornata_rimuovi(giornata_id, consegna_id)        # idempotente
giornata_riordina(giornata_id, ordered_ids)       # permutazione esatta
get_meta(key, default=None) / set_meta(key, value)   # metadati; chiavi riservate: schema_version, migrazione_in_corso
backup_now() / backup_run()             # backup immediato: snapshot (json) o dump pg_dump/mysqldump (postgres/mysql) in DATA_DIR/backup;
                                        # backup_run() → {"ok", "file", "error", "avvisi"}; non solleva eccezioni (fase 7)
backup_list() / backup_last_time()      # backup presenti su disco (dal più recente) / istante dell'ultimo
write_count()                           # scritture fatte dal processo (il server decide se c'è qualcosa di nuovo da salvare)
```
Collezioni: `consegne`, `giornate`, `squadre`, `negozi`, `tipi_account`, `utenti`. La specifica (campi obbligatori, default, unicità, riferimenti) è dichiarata una sola volta nel codice (`_COLL`) e vale per tutti i backend.

**Eccezioni** (tutte derivano da `StorageError`; il server le traduce in HTTP): `ConflictError` → 409, `NotFoundError` → 404, `DuplicateError`, `IntegrityError`; `SchemaError` solo all'avvio (vedi sotto). Gli errori di programmazione o di validazione (collezione sconosciuta, campo obbligatorio mancante o non modificabile, tipo o lunghezza non validi, carattere NUL, filtro non supportato, `riordina` che non è una permutazione, consegna di un altro negozio) sono `ValueError`. Il comportamento del server su `StorageError` generico (crash o 500) resta un punto aperto (§11).

**Semantica comune a tutti i backend:**
- **`None` = campo assente.** Un valore `None` non viene memorizzato né restituito; `update_record(..., {"campo": None})` rimuove il campo. (Su SQL, NULL ≡ chiave mancante: è ciò che rende identici i risultati.)
- **Chiavi sempre camelCase** come nel frontend (`colorIdx`, `giornoConsegna`, ...): nessuna chiave snake_case esce dallo storage. I campi sconosciuti allo schema sono conservati e restituiti invariati.
- **`id` e `negozio_id` forniti dal chiamante**; `negozio_id` e `id` non sono modificabili; `versione` è gestita solo dallo storage (valore fornito all'inserimento ignorato).
- **Default:** `consegne.stato = in_attesa`, `squadre.colorIdx = 0`, `utenti.is_superadmin = false`, `utenti.primo_login = true`.
- **Unicità:** `id`; `utenti.username` e `tipi_account.nome`. `utenti.username` è confrontato **senza distinguere maiuscole/minuscole** (anche nei filtri), come fa `dev`, su tutti i backend.
- **Riferimenti (come `RESTRICT`):** `negozio_id` deve esistere; `utenti.tipo_account_id` e `utenti.negozio_id` possono essere assenti (superadmin). Eliminare un negozio ancora usato (da utenti, consegne, giornate o squadre), un tipo account con utenti o **una squadra con giornate** → `IntegrityError`. `giornate.squadra_id` è **obbligatorio**, deve esistere e appartenere allo stesso negozio della giornata (altrimenti `ValueError`); non si può rimuovere né modificare in una squadra di un altro negozio.
- **Eliminare una consegna la toglie da tutte le giornate** (equivale a `ON DELETE CASCADE`), anche su JSON.
- **Operazioni sulle giornate:** le consegne assegnate devono esistere (`NotFoundError`) e appartenere allo stesso negozio della giornata (`ValueError`); l'operazione è tutto-o-niente. **Non modificano `versione`** (come in `dev`).
- **`giornata_completa` non esiste:** in `dev` "segna completata" imposta solo `stato = completata` sulla consegna; il flag per singola consegna nella giornata (`consegneCompletate`, colonna `completata`) non è mai stato usato né dal frontend né dal server. Viene ignorato in inserimento e non è più restituito.
- **Tipi, lunghezze, caratteri:** i campi noti hanno un tipo (testo, intero, booleano, lista) e un valore di tipo diverso è un `ValueError` (nessuna conversione silenziosa: `colorIdx="3"` viene rifiutato). `id` e riferimenti max 36 caratteri, `username` 150, `tipi_account.nome` 255, `password_hash` 64. Il carattere NUL è rifiutato ovunque. I controlli sono nel livello comune: tutti i backend accettano e rifiutano gli stessi valori.
- **Campi con default non rimovibili:** `consegne.stato`, `squadre.colorIdx`, `utenti.is_superadmin`, `utenti.primo_login` sono come obbligatori (`update_record(..., {"stato": None})` → `ValueError`).
- **Filtri:** solo uguaglianza su `id`, `versione` (se prevista) e campi tipizzati scalari; un filtro `None` trova i record senza quel campo. Un filtro su un campo "extra" o su una lista è un `ValueError` (su SQL non sarebbe una colonna). Confronti esatti (maiuscole e accenti contano), tranne `utenti.username`.
- **Ordine:** `list_records` restituisce sempre l'ordine di inserimento, anche dopo gli update.

### Test del server (`tests/test_server.py`)
Avvia `server.py` in-process su una porta effimera, sullo storage del backend scelto con `DB_BACKEND`, e lo interroga via HTTP. Copre: Challenge-Response (monouso, utente inesistente e password errata indistinguibili), cambio password obbligatorio (anche l'enforcement lato server), sessioni (scadenza, logout, invalidazione), ordine dei controlli 401 → 403 → negozio, superadmin senza accesso ai dati operativi, isolamento tra negozi, optimistic locking (409), operazioni su giornate e squadre, regole sugli utenti, timestamp di polling per negozio, file statici (solo frontend), rifiuto di un archivio V1 all'avvio (codice di uscita 2). Gira insieme alla suite dello storage con gli stessi comandi del paragrafo successivo (`unittest discover` raccoglie entrambi i file).

### Test (suite di contratto)
`tests/test_storage_contract.py` contiene gli **stessi test per tutti i backend**: round-trip dei record, optimistic locking (anche sotto concorrenza, con una pausa forzata tra lettura e scrittura per rendere la corsa deterministica), unicità, riferimenti, tipi e lunghezze, filtri, ordine di inserimento, isolamento per negozio, operazioni sulle giornate, `insert_records` tutto-o-niente, metadati; i test del controllo dello schema all'avvio (marcatore, dati V1, versione, flag di migrazione, colonne e tabelle alterate: sempre con verifica che nulla sia stato modificato), più test specifici del backend json (persistenza, file corrotto, backup) e dei backend SQL (schema idempotente, connessione persa, reset rifiutato). La qualità dei test è stata verificata introducendo bug intenzionali nel codice (mutation check): ogni bug reale è stato rilevato.

Tutto si esegue **in Docker** (sul server non serve Python). Database di test temporanei, separati dalla produzione (per limitare i backend provati, ad esempio `TEST_BACKENDS="json postgres" docker compose -f compose.test.yaml up --build --exit-code-from tests`):
```bash
docker compose -f compose.test.yaml up --build --exit-code-from tests
docker compose -f compose.test.yaml down
```
`compose.test.yaml` avvia PostgreSQL 16 e MySQL 8.4 senza volumi né porte pubblicate e un container `tests` (immagine compilata dal `Dockerfile`, `tests/` montata in sola lettura) che lancia `tests/run_all.sh` su ogni backend elencato in `TEST_BACKENDS`. Con `TEST_VERBOSE=1` si ottiene l'elenco dei singoli test. Solo json, senza database:
```bash
docker run --rm -v "$PWD":/app:ro -w /app -e DB_BACKEND=json python:3.13-slim-bookworm python -B -m unittest discover -s tests
```
⚠️ Con i backend DB la suite **svuota le tabelle**: rifiuta di agire se `DB_NAME` non termina con `_test`, ma non va mai puntata a un database di produzione. Solo libreria standard, nessuna dipendenza aggiuntiva.

### Controllo dello schema all'avvio 🚧 (passo 1d)
`init_storage_v2()` decide cosa fare **prima di creare o modificare qualsiasi cosa**; se l'archivio non è uno schema V2 valido solleva `SchemaError` e **non lascia alcun backend attivo** (le operazioni successive danno `StorageError`). Marcatore: `schema_version = 2` nei metadati (`meta.json` o tabella `meta`).

| Situazione trovata | Esito |
|---|---|
| Archivio vuoto (nessun dato, nessuna tabella) | Viene inizializzato e marcato `schema_version = 2` |
| Marcatore 2 e struttura valida | Si parte; nessuna modifica |
| Dati V1 senza marcatore (file json non vuoti; tabelle V1 su SQL) | `SchemaError` → eseguire `migrate.py` o usare un archivio nuovo |
| Dati V2 senza marcatore | `SchemaError` |
| Marcatore di altra versione | `SchemaError` |
| Flag `migrazione_in_corso` attivo | `SchemaError` (salvo `ignore_migration=True`, riservato a `migrate.py`) |
| SQL: tabella mancante, o colonne diverse da quelle attese (mancanti **o in più**) | `SchemaError` con le colonne indicate |
| File di metadati json illeggibile | `StorageError` (non è uno `SchemaError`), file intatto |

Regole e limiti:
- **Mai una modifica automatica:** nessun `ALTER`, nessuna "riparazione". Per ripartire da zero serve un database nuovo o una cartella dati nuova.
- **Tabelle V1 vuote su SQL → rifiutate** comunque (le tabelle sono incompatibili e `CREATE TABLE IF NOT EXISTS` non le correggerebbe). **File json V1 vuoti → accettati** (equivalgono a un archivio vuoto).
- **Si verificano i nomi delle colonne, non i tipi** né il contenuto dei record (su json non c'è schema da verificare).
- **MySQL:** il DDL non è transazionale; un'inizializzazione interrotta a metà lascia uno schema parziale, che al riavvio viene rifiutato (eliminare le tabelle e ripartire). Su PostgreSQL schema e marcatore sono nella stessa transazione.
- Il reset usato dai test **conserva** il marcatore.
- Con `restart: unless-stopped` un container che trova dati V1 **si riavvia in ciclo** finché non si interviene; il motivo è nel log. È voluto: meglio un server fermo che uno che serve dati incompatibili.

### Backend JSON
File separati in `DATA_DIR`, ciascuno **un array di record**: `consegne.json`, `giornate.json`, `squadre.json` e 🚧 V2 `negozi.json`, `tipi_account.json`, `utenti.json`, più `meta.json` (metadati). Stesso formato dei file V1, ma **un archivio con dati V1 e senza marcatore `schema_version` viene rifiutato all'avvio** finché non è migrato (vedi "Controllo dello schema all'avvio"): i file V1 non vanno semplicemente riutilizzati.
- **Lock unico** per tutte le operazioni (un solo `RLock`): il carico è minimo e si escludono i deadlock tra collezioni.
- **Scrittura atomica** (`.tmp` + `fsync` + `os.replace()`), 2 tentativi come in V1.
- **File illeggibile → `StorageError`**: non si restituisce mai un valore di default che verrebbe poi riscritto sopra i dati.
- **Backup** in `DATA_DIR/backup/` di tutte le collezioni e di `meta.json` (snapshot `<collezione>.<data>.json`): prima di una scrittura **al massimo uno ogni `BACKUP_INTERVAL` (6 ore)**, più quelli del thread del server e quelli su richiesta con `backup_now()` (dopo una migrazione, dal pannello del superadmin). Si conservano gli ultimi `BACKUP_KEEP` (30) per file. Più snapshot nello stesso secondo si sovrascrivono (stesso nome).
- L'API è per record, ma internamente il backend JSON riscrive il file della collezione: adatto a installazioni piccole (scelta consapevole, vedi §10).
- Eliminare una consegna scrive prima le giornate e poi la consegna: un'interruzione lascia al più una consegna non assegnata, mai un riferimento orfano.

### Backend SQL V1 (attuale su `main`)
Schema nativo (non blob JSON). Tabelle V1:

| Tabella | Descrizione |
|---------|-------------|
| `consegne` | Record consegna con campi reali + `articoli` (JSON/JSONB) + `extra` (JSON/JSONB) per campi futuri |
| `squadre` | Squadre con `id`, `nome`, `color_idx` |
| `giornate` | Giornate con `id`, `data`, `squadra` (nome stringa in V1), `extra` |
| `giornata_consegne` | Join giornata↔consegna con `ordine` e `completata` |

Il campo `extra` (JSONB in Postgres, JSON in MySQL) cattura eventuali campi aggiuntivi del frontend senza rompere lo schema.

⚠️ **Difetto noto della V1 sui backend SQL** (rilevato leggendo il codice, non eseguito su un DB reale): i campi camelCase noti vengono scritti in colonne snake_case ma **non vengono riconvertiti in lettura**. Le squadre tornano con `color_idx` invece di `colorIdx` (il frontend usa solo `colorIdx`: i colori andrebbero persi dopo un ricaricamento) e le consegne restituiscono sia le chiavi snake_case sia quelle camelCase salvate in `extra`. La V2 non ha questo difetto (le chiavi in uscita sono sempre camelCase). `main` non è stato modificato.

### Backup dei database (fase 7 ✅)
`backup.py` + `storage.backup_run()`. La stessa cartella dei backup json, **`DATA_DIR/backup/`**: con un database serve quindi una cartella montata su `/data` (con compose c'è `app_data`); se non è scrivibile il backup fallisce con un avviso e l'app continua.
- **Strumenti nell'immagine, alla versione dei database di `compose.yaml`:** `pg_dump` 16 (repository PGDG) e `mysqldump` 8.4 (repository MySQL, chiave GPG 2025: una rotazione della chiave può far fallire la build) installati nel `Dockerfile` con gli argomenti `PG_MAJOR`, `MYSQL_COMPONENT`, `MYSQL_SERIES`; la build verifica la versione e `tests/test_backup.py` controlla che coincida con le immagini `postgres:` e `mysql:` di `compose.yaml` e `compose.test.yaml`. I pacchetti di Debian non vanno bene: `pg_dump` rifiuta un server più nuovo di lui (Debian 12 ha la 15) e `mariadb-client` non è `mysqldump` 8.4. A ogni backup si confronta anche la versione del server con quella dello strumento (avviso nel log e nella risposta).
- **Formato:** SQL testuale compresso `<backend>-<database>.<AAAA-MM-GG_hh-mm-ss>[-n].sql.gz` (`pg_dump --no-owner --no-acl`; `mysqldump --single-transaction --routines --triggers --events --no-tablespaces --default-character-set=utf8mb4 --set-gtid-purged=OFF`, quindi funziona con l'utente dell'app e la copia è coerente).
- **Sicurezza e robustezza:** password solo da variabile d'ambiente (`PGPASSWORD`, `MYSQL_PWD`), mai negli argomenti né nei log; scrittura in `.partial` e rinomina solo a dump concluso con codice 0 **e** riga di chiusura presente (altrimenti scartato); timeout (`BACKUP_TIMEOUT`, 900 s); un solo backup alla volta; più backup nello stesso secondo ricevono un numero progressivo maggiore di quelli presenti (mai riusato: la conservazione cancellerebbe il nuovo); ultimi `BACKUP_KEEP` (30) per database.
- **Pianificazione (tutti i backend):** il thread `backup_loop()` di `server.py` salva ogni `BACKUP_INTERVAL` secondi (default 21600 = 6 ore), **solo se** ci sono state modifiche dall'ultimo backup (`write_count()`); un processo appena avviato non sa cosa è cambiato mentre era fermo, quindi ne fa uno solo se l'ultimo ha più di un intervallo; se non esiste nessun backup ne fa uno dopo 60 s dall'avvio. Se fallisce riprova dopo al massimo 10 minuti. `BACKUP_INTERVAL=0` lo disattiva (anche gli snapshot json prima delle scritture). Gira fuori dalle richieste e non le rallenta.
- **Altri modi:** dopo una migrazione (`migrate.py`: backup iniziale della destinazione, non critico), dal pannello del superadmin (scheda "Backup": elenco e "Esegui backup ora", `GET/POST /api/backup`), e `python backup.py` (codice 0/1; per un'attività pianificata di DSM: `docker exec <container> python backup.py`). Le copie fuori dal NAS sono a carico di strumenti esterni.
- **Ripristino:** non c'è uno strumento (operazione rischiosa): si ripristina in un database VUOTO con gli stessi strumenti dell'immagine, `gunzip -c FILE.sql.gz | psql -h HOST -U UTENTE -d DB -v ON_ERROR_STOP=1` (PostgreSQL, con `PGPASSWORD`) oppure `gunzip -c FILE.sql.gz | mysql -h HOST -u UTENTE DB` (MySQL, con `MYSQL_PWD`); per json si ricopiano i file di uno snapshot togliendo la data dal nome. `pg_dump` 16.10+ scrive righe `\restrict`/`\unrestrict`: ripristinare con lo `psql` dell'immagine (stessa versione). Provato nei test su entrambi i database e su json (identico all'originale, il server parte e le credenziali valgono).

### Backend PostgreSQL V2 🚧 (passo 1b — implementato)
Implementazione in `storage.py`: la classe `_SqlV2` contiene tutta la logica comune ai database SQL, `_PgV2` solo il dialetto (connessione, `JSONB`, mappatura errori, upsert dei metadati). Il backend MySQL (`_MysqlV2`, passo 1c) usa la stessa base.
- **Schema generato dalla specifica** (`_COLL` + `_COLS`): tabelle e colonne non sono scritte a mano due volte, quindi non possono divergere dal codice. Creato **solo su un database vuoto**; se esistono già tabelle vengono soltanto verificate (vedi "Controllo dello schema all'avvio"): un database con schema V1 o alterato viene rifiutato, mai modificato.
- **Una transazione per operazione**, con una connessione dedicata (come V1: robusta ai riavvii del DB), 2 tentativi di connessione.
- **Optimistic locking atomico tramite lock di riga:** `SELECT ... FOR UPDATE`, confronto di `versione`, `UPDATE` nella stessa transazione. Il merge dei campi è lo stesso codice del backend json (`_apply_changes`).
- **Errori:** violazione di unicità → `DuplicateError`; violazione di riferimento (inesistente o ancora referenziato) → `IntegrityError`; errori sui dati → `ValueError`; il resto → `StorageError`.
- **Ordine di inserimento garantito** dalla colonna `seq` (`ORDER BY seq`).
- **`utenti.username`:** unicità e filtri tramite la colonna derivata `username_ci = casefold(username)`, calcolata in Python con la stessa funzione del backend json (non `lower()` di PostgreSQL, che darebbe risultati diversi su caratteri particolari). `tipi_account.nome` è univoco **con distinzione di maiuscole**.
- **`JSONB`** per `articoli`, `permessi` e `extra` (campi sconosciuti allo schema, restituiti invariati).
- **Backup (fase 7):** `backup_now()` lancia `pg_dump` (vedi "Backup dei database" in §6).
- La funzione di reset usata dai test rifiuta di agire se `DB_NAME` non termina con `_test`.

### Backend MySQL V2 🚧 (passo 1c — implementato)
Classe `_MysqlV2`: stessa logica comune di PostgreSQL (`_SqlV2`), cambia solo il dialetto. Verificato con la stessa suite di contratto di json e PostgreSQL.
- **Collation `utf8mb4_0900_bin` su tutte le tabelle.** Il default di MySQL (`utf8mb4_0900_ai_ci`) ignora maiuscole, accenti e spazi finali: `Mario` = `mario` = `márió`, sia nei filtri sia nei vincoli di unicità, a differenza di json e PostgreSQL. `0900_bin` (senza padding) rende i confronti esatti; `username` resta senza distinzione di maiuscole solo tramite la colonna derivata `username_ci` (stessa regola degli altri backend).
- **`LONGTEXT` per il testo libero** (un `TEXT` MySQL si ferma a 64 KB); **`JSON`** per liste ed `extra` (restituito come testo e decodificato); **`BOOLEAN`** è `TINYINT(1)` e viene riconvertito in `bool`; `seq` è `BIGINT AUTO_INCREMENT UNIQUE`.
- **Isolamento `READ COMMITTED`** impostato a ogni connessione, come PostgreSQL (il default InnoDB è `REPEATABLE READ`). Ogni operazione parte con una lettura bloccante (`FOR UPDATE`/`FOR SHARE`), quindi oggi il comportamento osservabile è identico: l'impostazione è precauzionale (stesso modello di concorrenza, meno blocchi su intervalli di indice).
- **Errori:** 1062 → `DuplicateError`; 1451/1452 → `IntegrityError`; errori sui dati (NULL non ammesso, valore troppo lungo/fuori intervallo) → `ValueError`; il resto → `StorageError`.
- La colonna `username_ci` ha lunghezza `3 × 150`: `casefold()` può allungare una stringa fino a 3 volte (`ß` → `ss`).
- Upsert dei metadati con `INSERT ... AS new ... ON DUPLICATE KEY UPDATE`; indici sulle chiavi esterne creati automaticamente da InnoDB.
- **Prestazioni:** ogni operazione apre una connessione. Misurato in sviluppo (MySQL 8.0 locale): ~32 ms per operazione contro ~4 ms di PostgreSQL, quasi tutto handshake TLS e autenticazione. In Docker la suite completa richiede circa 50 s su MySQL contro circa 9 s su PostgreSQL. Irrilevante per l'uso previsto; riuso delle connessioni o disattivazione di TLS su rete Docker privata restano valutabili (punto aperto in §11).
- **Backup (fase 7):** `backup_now()` lancia `mysqldump` (vedi "Backup dei database" in §6). Collaudato con la suite completa su `mysql:8.4` in Docker (e su 8.0 in sviluppo).

### Schema DB V2 🚧 (generato da `storage.py`, dialetto PostgreSQL)
Per le installazioni V2 lo schema è **nuovo** (non si estendono le tabelle V1). Fa fede il codice: questo elenco è l'output di `_PgV2._ddl_statements()`. Su MySQL cambiano solo i tipi (`JSON`, `LONGTEXT`, `BIGINT AUTO_INCREMENT`), la clausola `DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin` e l'assenza degli `CREATE INDEX` espliciti.

```sql
CREATE TABLE negozi (
    id VARCHAR(36) PRIMARY KEY,
    seq BIGSERIAL NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    creato_il TEXT,
    extra JSONB
);
CREATE TABLE tipi_account (
    id VARCHAR(36) PRIMARY KEY,
    seq BIGSERIAL NOT NULL UNIQUE,
    nome VARCHAR(255) NOT NULL,
    permessi JSONB NOT NULL,
    creato_il TEXT,
    modificato_il TEXT,
    extra JSONB,
    UNIQUE (nome)
);
CREATE TABLE utenti (
    id VARCHAR(36) PRIMARY KEY,
    seq BIGSERIAL NOT NULL UNIQUE,
    username VARCHAR(150) NOT NULL,
    password_hash VARCHAR(64) NOT NULL,
    tipo_account_id VARCHAR(36),
    negozio_id VARCHAR(36),
    is_superadmin BOOLEAN NOT NULL,
    primo_login BOOLEAN NOT NULL,
    creato_da VARCHAR(36),
    creato_il TEXT,
    ultimo_accesso TEXT,
    username_ci VARCHAR(450) NOT NULL UNIQUE,
    extra JSONB,
    FOREIGN KEY (negozio_id) REFERENCES negozi(id) ON DELETE RESTRICT,
    FOREIGN KEY (tipo_account_id) REFERENCES tipi_account(id) ON DELETE RESTRICT
);
CREATE TABLE consegne (
    id VARCHAR(36) PRIMARY KEY,
    seq BIGSERIAL NOT NULL UNIQUE,
    negozio_id VARCHAR(36) NOT NULL,
    nome TEXT,
    cognome TEXT,
    indirizzo TEXT,
    citta TEXT,
    stato TEXT NOT NULL,
    note TEXT,
    giorno_consegna TEXT,
    fascia_oraria TEXT,
    data_prenotaz TEXT,
    articoli JSONB,
    versione INTEGER NOT NULL DEFAULT 1,
    extra JSONB,
    FOREIGN KEY (negozio_id) REFERENCES negozi(id) ON DELETE RESTRICT
);
CREATE TABLE squadre (
    id VARCHAR(36) PRIMARY KEY,
    seq BIGSERIAL NOT NULL UNIQUE,
    negozio_id VARCHAR(36) NOT NULL,
    nome TEXT NOT NULL,
    color_idx INTEGER NOT NULL,
    versione INTEGER NOT NULL DEFAULT 1,
    extra JSONB,
    FOREIGN KEY (negozio_id) REFERENCES negozi(id) ON DELETE RESTRICT
);
CREATE TABLE giornate (
    id VARCHAR(36) PRIMARY KEY,
    seq BIGSERIAL NOT NULL UNIQUE,
    negozio_id VARCHAR(36) NOT NULL,
    data TEXT NOT NULL,
    squadra_id VARCHAR(36) NOT NULL,
    versione INTEGER NOT NULL DEFAULT 1,
    extra JSONB,
    FOREIGN KEY (squadra_id) REFERENCES squadre(id) ON DELETE RESTRICT,
    FOREIGN KEY (negozio_id) REFERENCES negozi(id) ON DELETE RESTRICT
);
CREATE TABLE giornata_consegne (
    giornata_id VARCHAR(36) NOT NULL,
    consegna_id VARCHAR(36) NOT NULL,
    ordine INTEGER NOT NULL,
    PRIMARY KEY (giornata_id, consegna_id),
    FOREIGN KEY (giornata_id) REFERENCES giornate(id) ON DELETE CASCADE,
    FOREIGN KEY (consegna_id) REFERENCES consegne(id) ON DELETE CASCADE
);
CREATE TABLE meta (
    chiave VARCHAR(100) PRIMARY KEY,
    valore JSONB NOT NULL
);
CREATE INDEX ix_utenti_negozio_id ON utenti (negozio_id);
CREATE INDEX ix_utenti_tipo_account_id ON utenti (tipo_account_id);
CREATE INDEX ix_consegne_negozio_id ON consegne (negozio_id);
CREATE INDEX ix_giornate_squadra_id ON giornate (squadra_id);
CREATE INDEX ix_giornate_negozio_id ON giornate (negozio_id);
CREATE INDEX ix_squadre_negozio_id ON squadre (negozio_id);
CREATE INDEX ix_giornata_consegne_consegna ON giornata_consegne (consegna_id);
```
- **`giornate.squadra_id` (obbligatorio, FK verso `squadre`, `RESTRICT`)** al posto del nome della squadra (fase 6 ✅): una squadra si elimina solo se non ha giornate; la rinomina non tocca le giornate. Le tabelle sono create con `squadre` prima di `giornate`. **Un archivio V2 di un'edizione precedente** (con `giornate.squadra` come nome) viene rifiutato all'avvio: i database per le colonne diverse, i file json con un errore dedicato (`SchemaError`, nessun file modificato). Il marcatore `schema_version` resta 2 (la V2 non è mai andata in produzione): gli archivi di sviluppo vanno ricreati.
- Per il backend JSON la struttura dei record è la stessa (§8).
- **Regole dello schema:** `ON DELETE RESTRICT` da `utenti` verso `tipi_account` e `negozi` e dalle tabelle operative verso `negozi`; `ON DELETE CASCADE` da `giornata_consegne` verso giornate e consegne; `negozio_id` `NOT NULL` sulle tabelle operative; indici sulle chiavi esterne; `giornata_consegne` senza la colonna `completata` (non usata).
- `seq` serve solo a ordinare per inserimento: non esce mai dallo storage. `username_ci` è una colonna interna derivata (`casefold(username)`, lunga 3 × 150), anch'essa mai restituita.
- Lunghezze: `VARCHAR(n)` solo per chiavi e campi indicizzati (`id`/riferimenti 36, `username` 150, `tipi_account.nome` 255, `password_hash` 64); il testo libero è `TEXT` senza limite.

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

**Decisione V2 (applicata in fase 3 ✅):** percorso relativo `export const API = '/api';` — stessa origine del server, nessuna porta hardcoded, valido con qualsiasi `APP_PORT` o reverse proxy.

### Identificatore client (`clientid.js`)
```javascript
// clientid.js — generato una volta per sessione browser, salvato in sessionStorage
const CLIENT_ID = generateClientId(); // via crypto.getRandomValues(), NON crypto.randomUUID()
```
⚠️ **Non usare `crypto.randomUUID()`**: richiede un secure context (HTTPS o `localhost`) ed è **indisponibile** quando l'app è servita via HTTP semplice su IP LAN — lo scenario normale di questo progetto. `crypto.getRandomValues()` non ha questa limitazione ed è usato per generare un ID esadecimale a 16 byte. In V1 è inviato come header `X-Client-ID` su `fetchData`, `postData`, `pingServer` (non su `remoteLog`). In V2 è inviato su **ogni** richiesta (`clientHeaders()` di `clientid.js`, usato dal wrapper `_fetch` di `api.js` e dalle chiamate di `auth.js`).

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
  ├── clientid.js       (no deps)
  ├── auth.js → sha256, store, clientid
  ├── api.js → store, auth, clientid
  ├── sync.js → api, store, permessi, utils
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
In V1 `squadra` è una **stringa (nome)**. In V2 è `squadra_id` (**obbligatorio**, id di una squadra dello stesso negozio): `"squadra_id": "sq_abc123"`. La migrazione trasforma il nome in id (§11, fase 6).

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
`giornate` ha inoltre `squadra_id` (obbligatorio) al posto di `squadra`.

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
  "tipo_account_id": "ta_abc123",
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
Giornate → seleziona o crea giornata (la squadra è obbligatoria) → "Aggiungi consegna" → seleziona dalla lista "in attesa" → Aggiungi

### Rimuovere da una giornata
Click ✕ sulla card → la consegna torna "in_attesa", `giornoConsegna` e `fasciaOraria` svuotati

### Setup iniziale V2 🚧
1. Primo avvio: login come `superadmin` / `admin` → cambio password obbligatorio
2. Pannello superadmin → **Negozi** → crea il primo negozio
3. **Tipi account** → crea un tipo (es. "Amministratore") scegliendo i permessi
4. **Utenti** → crea un utente assegnandogli negozio e tipo account
5. Logout; login con il nuovo utente → Impostazioni → **crea almeno una squadra** (senza squadre non si può creare nessuna giornata)
6. Da qui l'operatività del proprio negozio: consegne, giornate (ogni giornata ha una squadra obbligatoria)

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
| `squadra` come stringa in V1 | Retrocompatibilità con i dati esistenti; in V2 è `squadra_id` (obbligatorio, fase 6 ✅) |
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
| **Storage per singolo record su tutti i backend** | Un layer di astrazione con più DB perde utilità se si riscrive l'intera tabella a ogni salvataggio; su DB il controllo di versione è atomico (lock di riga) e una scrittura fallita non rischia i dati degli altri negozi |
| Utenti, negozi e tipi account dentro `storage.py` | Nessun dato fuori dal layer di storage; container `read_only`; stesso backend per tutto |
| Polling via timestamp | Evita render inutili; scarica solo ciò che è cambiato |
| Risposta delle scritture = db aggiornato del negozio | Il client è sempre in sync dopo ogni operazione propria |
| Log 100% server-side | Non aggirabile dal client; auditabilità reale |
| `modal-admin.js` caricato dinamicamente | Non caricato per utenti normali; separazione netta |
| `migrate.py` con tutti e 3 i backend come sorgente e destinazione | Il cliente può cambiare backend; la migrazione V1→V2 non deve dipendere dal backend in uso |
| `squadra_id` obbligatorio, anticipato prima della migrazione di produzione (fase 6 ✅) | La migrazione dei dati si fa una sola volta: schema, server, frontend e migrazione cambiano insieme. Squadra obbligatoria: ogni giornata ha sempre una squadra (alla migrazione, "Non assegnata" solo se serve); una squadra con giornate non si elimina |

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
| 1 | `storage.py`: schema V2 e API per singolo record su json/mysql/postgres, con suite di test condivisa | ✅ completata — API per record, backend json/PostgreSQL/MySQL, marcatore e controllo dello schema, `compose.test.yaml`; collaudata in Docker (json, `postgres:16`, `mysql:8.4`) |
| 2 | `server.py`: Challenge-Response, sessioni, endpoint REST, permessi, filtro `negozio_id`, `/api/stato`, creazione superadmin | ✅ completata — vedi "Scelte implementative della fase 2" sotto; 52 test del server su json, `postgres:16`, `mysql:8.4` |
| 3 | Frontend V2 (vedi metodo sotto) | ✅ completata — vedi "Scelte implementative della fase 3"; controlli statici e `sha256.js` in Node (`tests/js/run.mjs`), giro completo nel browser contro il server V2 (a mano, non automatizzato) |
| 4 | `migrate.py` | ✅ completata — vedi "Scelte implementative della fase 4"; 27 test (logica pura e da un capo all'altro su json, `postgres:16`, `mysql:8.4`), provata anche con `docker run`, `docker compose` e uno stack in stile Portainer |
| 5 | Test integrato: migrazione → primo login superadmin → negozio → tipo account → utente → login → operatività, su tutti e 3 i backend | ✅ completata — vedi "Collaudo integrato della fase 5" |
| 6 | `squadra_id` al posto del nome squadra nelle giornate (storage, server, frontend, migrazione) | ✅ completata (anticipata prima della fase 5) — vedi "Scelte implementative della fase 6" |
| 7 | Backup dei database: `pg_dump` / `mysqldump` nell'immagine (stessa versione dei database di compose), `backup_now()` sui database, pianificazione ogni 6 ore per tutti i backend (ultimi 30), backup dal pannello del superadmin, `python backup.py`, ripristino provato | ✅ completata — vedi "Backup dei database" in §6; test sul sistema vero (pianificazione, conservazione, ripristino identico) su json, PostgreSQL e MySQL |

Ogni fase è un commit separato (o gruppo di commit) rivisto prima di passare alla successiva.

### Scelte implementative della fase 2 (`server.py`)
Dove il design di §5 lasciava margine, o dove `dev` è stato migliorato:
- **Struttura:** un solo file; tabella delle rotte (`@route(metodo, pattern, requisito)`) con dispatcher unico che applica 401 → 403 (cambio password pendente) → requisito (`public`, `auth`, `superadmin`, `operativo` = non superadmin, oppure un permesso). Il controllo del `negozio_id` della risorsa è nell'handler (`check_tenant`). Server `ThreadingHTTPServer`; challenge, sessioni, timestamp e contatore client hanno lock separati.
- **Errori:** `HttpError` → codice indicato; `ConflictError` → 409; `NotFoundError` → 404; `DuplicateError`/`IntegrityError` → 409; `ValueError` → 400; qualunque altra eccezione (anche `StorageError` generico) → 500 con messaggio generico (dettaglio nel log), il server resta attivo.
- **`must_change_password` imposto dal server:** con la sessione in quello stato sono ammessi solo `change-password`, `logout` e `ping` (403 sul resto). Il cambio password invalida tutte le sessioni dell'utente.
- **Login:** il challenge si consuma sempre; utente inesistente e password errata danno la stessa risposta (401, `Credenziali non valide`), distinguibili solo nel log. Al massimo 1000 challenge contemporanei (503 oltre). Gli hash in ingresso devono essere 64 caratteri esadecimali minuscoli. Un utente senza tipo account **o senza negozio** (non superadmin) è "non configurato".
- **Utenti:** nessuno può reimpostare la password, cambiare il tipo o eliminare **se stesso** tramite gli endpoint di gestione (per la propria password c'è `change-password`); il reset della password di un altro utente imposta `primo_login = true` (deve sceglierne una sua al prossimo accesso); cambio tipo, reset password ed eliminazione invalidano subito le sessioni dell'utente. Un utente creato da un admin ha `primo_login = false`.
- **`versione` obbligatoria** (intero) nei `PUT` di consegne e squadre: se manca → 400, se non coincide → 409. Le altre operazioni (assegna, rimuovi, riordina, completa, rinomina delle giornate) non richiedono `versione` e incrementano quella dei record che toccano, quindi un'altra modifica in corso su quella consegna riceverà 409.
- **Giornate:** eliminare una giornata con consegne assegnate → 409 (come già fa l'interfaccia V1; `dev` le rimetteva in attesa). Assegnare imposta `stato = da_confermare` e `giornoConsegna`; rimuovere riporta `in_attesa` (solo se `programmata`/`da_confermare`) e svuota `giornoConsegna`/`fasciaOraria`. `data` deve essere `AAAA-MM-GG`.
- **Squadre:** nome univoco per negozio (senza distinzione di maiuscole), `colorIdx` 0-7 (alla creazione: numero di squadre del negozio modulo 8). Rinominare tocca solo la squadra (le giornate la referenziano per id, fase 6); eliminare è bloccato (409) se ha giornate.
- **Risposte delle scritture filtrate per permessi di lettura:** includono solo le categorie (`consegne`, `giornate`, `squadre`) che la sessione può leggere.
- **Polling:** timestamp **per negozio**, in memoria; partono dall'ora di avvio e sono strettamente crescenti. Eliminare una consegna e assegnare/rimuovere consegne aggiornano più categorie; rinominare o eliminare una squadra solo `squadre`.
- **File statici:** serviti solo `index.html`, `css/`, `js/` (V1 serviva qualunque file dell'immagine, compreso il codice Python).
- **Rimossi:** `GET/POST /api/data`, `POST /api/log`, `/api/clients`, CORS (`/api` è sulla stessa origine).
- **Avvio:** `init_storage_v2()` + creazione del superadmin; `SchemaError` → log leggibile e uscita con codice 2; altro `StorageError` → codice 1.
- **Forma delle risposte** (da rispettare nel frontend, fase 3): `GET /api/negozi` → `{"negozi": [...]}`, `GET /api/tipi-account` → `{"tipi_account": [...]}`, `GET /api/utenti` → `{"utenti": [...]}` (senza `password_hash`, senza il superadmin), `POST /api/negozi` → `{"ok": true, "negozio": {...}}`, `POST /api/tipi-account` → `{"ok": true, "tipo": {...}}`, `POST /api/utenti` → `{"ok": true, "id": "..."}`, le altre scritture amministrative `{"ok": true}`; le scritture operative rispondono con il db del negozio (§5).

### Scelte implementative della fase 3 (frontend)
- **Base:** i file di `dev` (`git show origin/dev:<file>`), uniti a tre vie con gli interventi di `main` (`X-Client-ID`, sidebar decrescente, nuovi tipi di installazione); un solo conflitto reale, in `api.js`. Nuovo `clientid.js` (senza dipendenze) perché `api.js` e `auth.js` inviino `X-Client-ID` su **ogni** richiesta senza un ciclo `api → auth → api`.
- **Caricamento e polling per permessi:** si scaricano solo le categorie (`consegne`, `giornate`, `squadre`) per cui l'utente ha il permesso di lettura (il server risponderebbe 403). `/api/stato` si legge **prima** dei dati: se qualcosa cambia nel frattempo il polling successivo lo riscarica. Le schede delle viste senza permesso di lettura sono nascoste.
- **`versione` nei `PUT`** di consegne (dal record locale, già in `dev`) e di squadre (rinomina e colore).
- **Conflitti (409):** `reportError()` in `sync.js` mostra il messaggio del server e ricarica i dati; il form della consegna si chiude così non si sovrascrivono alla cieca le modifiche dell'altro utente (riaprendo si vede la versione aggiornata). Altri errori: toast `Errore: ...`.
- **Sessione:** token in `sessionStorage`; il flag `must_change_password` è salvato anch'esso, così dopo un ricaricamento riappare l'overlay di cambio password. Un 401 su qualunque chiamata (sessione scaduta o invalidata, server riavviato) pulisce la sessione e **ricarica la pagina** (fermando ping e polling), con il messaggio "Sessione terminata: accedi di nuovo." Il ping gira anche per il superadmin.
- **Giornate:** l'interfaccia blocca l'eliminazione di una giornata con consegne assegnate, come il server.
- **Sicurezza (XSS):** ogni dato proveniente dal server inserito in `innerHTML`, nella finestra di stampa o negli attributi passa da `escHtml()` (che ora esegue l'escape anche di `'` e accetta qualsiasi valore); `fmtDate()` mostra come testo un valore che non è una data `AAAA-MM-GG`. I gestori inline dei pannelli (`modal-utenti.js`, `modal-admin.js`) ricevono **solo gli id** e ricavano nomi e username dalla lista in memoria, mai da stringhe inserite nell'attributo. Motivo: con più utenti e il token in `sessionStorage`, un nome con codice HTML inserito da un operatore sarebbe eseguito nel browser di un amministratore (XSS memorizzato).
- **Test:** `docker compose -f compose.test.yaml run --rm jstests` (Node in `node:22-alpine`, mai nell'app): sintassi dei moduli, ogni nome importato esiste, nessuna dipendenza circolare, ogni funzione usata in `onclick`/`onchange`/... è esposta su `window`, ogni `getElementById` letterale trova un elemento, `sha256.js` identico a SHA-256 di riferimento (accenti, emoji, lunghezze di confine). Il controllo è stato verificato introducendo errori intenzionali. Non c'è una suite automatica nel browser: il giro completo (primo login, cambio password obbligatorio anche dopo un ricaricamento, creazione di negozi/tipi/utenti, operatività, conflitto 409, polling tra due utenti, sessione invalidata, server fermato e riavviato, stampa) è stato eseguito a mano nel browser integrato di Claude, con nomi contenenti HTML.

### Scelte implementative della fase 4 (`migrate.py`)
- **Architettura a due passi:** `storage.py` legge l'ambiente una volta sola (all'import), quindi due backend non possono coesistere in un processo. L'esportazione gira in un **processo figlio** con l'ambiente della sorgente (`SRC_*` mappate su `DB_*`) e scrive un file JSON (`format: gestione-consegne-export`, `kind: v1|v2`); l'importazione, nel processo principale, usa l'ambiente della destinazione (`DB_*`, quello dell'app). Comandi: `run` (default, entrambi i passi), `export`, `import`. Il file di esportazione è anche il backup completo della sorgente.
- **Configurazione solo da ambiente, cartelle e comando** (per compose, `docker run` e GUI di DSM 7.1/Portainer): ogni opzione ha una variabile `MIGRATE_*`/`SRC_*` e un argomento; senza argomenti esegue `run`. Cartelle: `/source` (sola lettura), `/data`, `/migration`. Le password si danno solo per variabile (mai in `ps`).
- **Sicura per default:** senza `MIGRATE_EXECUTE=1` legge, convalida e stampa il rapporto, **senza scrivere nulla** nella destinazione (nemmeno il marcatore di schema); scrive solo il file di esportazione. La sorgente non viene mai modificata (per i json V1 e le tabelle V1 si usa `read_data()` senza `init_storage()`, che creerebbe file e tabelle).
- **Sorgenti:** V1 su json/mysql/postgres (le chiavi snake_case e i NULL della V1 su SQL, difetto noto, vengono riportati al formato del frontend: `normalize_sql_v1`), `dati.json` di Windows (`--source-kind file`: assorbe il ruolo di `import_data.py` per la V2, che resta intatto per le immagini V1) e V2 su qualunque backend (cambio di backend, con utenti, tipi account e negozi). Una V1 scambiata per V2 (o viceversa) e una sorgente V2 vuota sono rifiutate.
- **Trasformazione V1 → V2:** crea il negozio (`MIGRATE_NEGOZIO_NOME`, default "Negozio principale"), aggiunge `negozio_id` a squadre/consegne/giornate (gli id V1 restano), crea il superadmin con `server.superadmin_record()` (definizione unica con `ensure_superadmin()`), non crea altri utenti. Il nome della squadra delle giornate diventa `squadra_id` (vedi "Scelte implementative della fase 6").
- **Convalida con rapporto completo:** prima di scrivere si controllano **tutti** i record con le stesse regole dello storage (`_norm_insert`: tipi, lunghezze, NUL), id duplicati o mancanti, unicità (username senza distinzione di maiuscole, nome del tipo account), riferimenti (negozio, tipo account) e coerenza di negozio delle giornate; i riferimenti a consegne inesistenti si **scartano** e si riportano (con `MIGRATE_KEEP_ORPHANS=1` bloccano); gli `stato` fuori elenco sono solo un avviso. Se ci sono problemi bloccanti si esce con codice 2 senza scrivere.
- **Destinazione:** deve essere completamente vuota (nessun record, nessun dato V1, nessuna migrazione interrotta). Un database mancante si crea con `MIGRATE_CREATE_DB=1` (su MySQL il permesso dipende dall'utente; MySQL non rivela se un database esiste, quindi "accesso negato al database" vale come "mancante"). Le credenziali rifiutate non si riprovano; gli altri errori di connessione sì (10 tentativi, 3 s).
- **Scrittura e verifica:** `init_storage_v2()` → flag `migrazione_in_corso` → `insert_records` per collezione nell'ordine negozi, tipi account, utenti, squadre, consegne, giornate → ogni record viene **riletto e confrontato** (ignorando `versione`, che riparte da 1) → flag spento. Se la scrittura o la verifica falliscono il flag resta e il server V2 non parte; non c'è una ripresa automatica (si ricrea la destinazione e si rilancia `import` sullo stesso file).
- **Controlli preliminari** con messaggi chiari: cartelle non scrivibili dall'utente del container (tipico sui NAS), database non raggiungibile, sorgente e destinazione coincidenti (codice 3 o 2). Codici di uscita: 0 ok, 1 errore, 2 dati/destinazione non utilizzabili, 3 ambiente.
- **File di compose:** servizio `migrate` (profilo `migrate`) in `compose.yaml` per chi usa compose; `compose.migrate.yaml` autonomo per Portainer (stack) e simili, con `network_mode: ${DB_NETWORK:-bridge}` per raggiungere il database. Guida passo per passo anche per la GUI di Synology DSM 7.1 nel README.
- **Correzione in `compose.yaml`:** l'app (`DB_HOST: db`) non poteva raggiungere i database perché i servizi si chiamano `db_mysql`/`db_postgres`: aggiunto l'alias di rete `db` ai due servizi (rilevato provando il profilo `postgres` con la migrazione).
- **Test:** `tests/test_migrate.py` (logica pura, solo con json; da un capo all'altro come sottoprocessi con ambienti diversi: V1 json → V2 su ogni backend, V1 su postgres/mysql → V2 json, V2 → V2 andata e ritorno, `dati.json`, esporta poi importa, rapporto senza scritture, seconda esecuzione, destinazione con dati V1, sorgente = destinazione, rapporto con tutti i problemi, orfani, cartella non scrivibile, creazione del database, scrittura interrotta, verifica che trova una differenza). Controllati con bug intenzionali (verifica sempre ok, destinazione piena accettata, orfani non scartati, flag mai impostato, rapporto che scrive).

### Scelte implementative della fase 6 (`squadra_id`)
- **Perché ora:** la migrazione di produzione si farà una sola volta; schema, server, frontend e migrazione cambiano quindi insieme, prima del collaudo integrato (fase 5).
- **Campo obbligatorio:** `giornate.squadra_id` (`NOT NULL`, FK `RESTRICT` verso `squadre`, stesso negozio). Una giornata non può esistere senza squadra; un negozio non può creare giornate finché non ha almeno una squadra (il modal avvisa e disattiva il salvataggio).
- **Eliminazione bloccata:** una squadra con giornate non si elimina: il server risponde 409 ("La squadra ha giornate assegnate: eliminale prima") dopo un controllo esplicito, e lo storage la rifiuta comunque (`IntegrityError`, rete di sicurezza per due richieste in contemporanea); la UI la blocca prima di chiamare il server. Per togliere una squadra vanno eliminate le sue giornate, e una giornata con consegne si elimina solo dopo averne tolto le consegne (regola già in vigore).
- **Rinomina:** tocca solo la squadra; nome e colore dei badge si cercano per id in `db.squadre`. Senza `squadre.leggi` il nome non è disponibile e il badge non si mostra (avvisi di dipendenza: `giornate.leggi` e `stampa.pdf` → `squadre.leggi`).
- **Non è previsto cambiare la squadra di una giornata già creata** (come in V1): servirebbe un endpoint e un permesso nuovi. Se si sbaglia squadra, si elimina e si ricrea la giornata.
- **Migrazione (V1 → V2), regole sul nome della squadra:** (1) nome uguale a una squadra → quella; altrimenti confronto senza maiuscole e spazi (avviso); (2) squadre con lo stesso nome → la prima (avviso); (3) nome senza squadra corrispondente → la squadra viene **creata** (avviso); (4) nome vuoto o assente → squadra "Non assegnata" (`MIGRATE_SQUADRA_NON_ASSEGNATA`), creata **solo se almeno una giornata ne ha bisogno** e riusata se esiste già una squadra con quel nome. Il rapporto elenca avvisi e note. Il file di esportazione resta nel formato V1 (con i nomi). Un archivio V2 con giornate senza `squadra_id` o con il vecchio `squadra` viene rifiutato dalla convalida.
- **Test:** storage (obbligatorietà, esistenza, negozio, eliminazione bloccata e poi consentita, filtro, rifiuto dei vecchi archivi json) su json, PostgreSQL e MySQL; server (richiesta di `squadra_id`, 403/400, rinomina che non tocca le giornate, 409 e sblocco, polling); migrazione (le quattro regole, nessuna squadra in più se non serve, nome personalizzato, archivio V2 vecchio); frontend con i controlli statici e un giro nel browser (modal senza squadre, badge, rinomina, blocco e sblocco, utente senza `squadre.leggi`).

### Collaudo integrato della fase 5
Prova del **sistema vero** (processi, HTTP, database reali), non dei singoli pezzi. Tre livelli:

**1. Test di integrazione nei container di test** (`tests/integrazione_*.py`, girano una volta sola alla fine di `run_all.sh`; `TEST_INTEGRATION=0` li salta). Ogni operazione su un backend avviene in un processo dedicato (`tests/dbtool.py`, `integrazione_lib.py`), così un solo test usa json, PostgreSQL e MySQL insieme; `compose.test.yaml` crea un secondo database di test (`tests/db-init/`) per usare un database sia come sorgente sia come destinazione sullo stesso server.
- **Matrice** (`integrazione_scenari.py`): 4 sorgenti V1 (json, PostgreSQL, MySQL, `dati.json`) × 3 destinazioni = 12 scenari identici: rapporto senza scritture → migrazione con verifica → seconda migrazione rifiutata → il vero `server.py` parte → primo accesso del superadmin con cambio password obbligatorio → tipo account e utenti → i dati migrati sono tutti presenti e corretti (campi, ordine, squadre risolte per nome, "Non assegnata", "Ghost" creata, id V1 conservati) → operatività (squadra, giornata, consegna, assegna, riordina, completa, conflitto 409 tra due utenti, rimozione, eliminazione di squadre bloccata e poi consentita) → secondo negozio isolato → riavvio del server (dati sì, sessioni no) → controllo di integrità dell'archivio.
- **Catena V2 → V2** su un sistema già in uso (con utenti, tipi e dati creati dal server): json → PostgreSQL → MySQL → json e json → MySQL → PostgreSQL → json; ogni copia è identica (ignorando `versione`) e funziona con le stesse credenziali.
- **Concorrenza** (`integrazione_robustezza.py`, su ogni backend): 10 scritture sulla stessa consegna con la stessa `versione` → ne riesce una sola, le altre 409, valore finale del vincitore; creazioni, assegnazioni, eliminazioni e login in parallelo senza perdite né doppioni; letture durante le scritture mai errate né "all'indietro"; nessun `Traceback` nei log del server.
- **Protezioni:** il server e la migrazione rifiutano (codice 2) dati V1 nella destinazione, una migrazione interrotta e una destinazione già usata, senza modificarla.
- **Base dati grande:** 5.000 consegne e 500 giornate. Tempi misurati in Docker su questa macchina: migrazione con verifica di ogni record json ≈ 24 s (la ricerca delle chiavi esterne è lineare: adatto a installazioni piccole, §10), PostgreSQL ≈ 5 s, MySQL ≈ 7 s; lettura di consegne e giornate 0,1-0,4 s; una scrittura con risposta completa 0,2-0,6 s.
- Controllati con bug intenzionali (conflitto di versione ignorato dal server).

**2. Stack con le immagini vere** (`tests/stack.sh`, da lanciare sull'host con Docker): compila l'immagine e, per json, PostgreSQL e MySQL, usa `compose.yaml` con il profilo del database (rapporto, migrazione, seconda migrazione rifiutata, avvio dell'app, `healthcheck` dell'immagine `healthy`, giro HTTP nel container, porta pubblicata), poi la migrazione "alla maniera della GUI di Docker" (`docker run`, senza `read_only` né `tmpfs`, con e senza cartella di migrazione montata) e `compose.migrate.yaml` con un database in una rete Docker a parte (creazione del database compresa). Usa progetto, immagine e porte proprie (`gc-stack-test`): non tocca l'installazione.

**3. Giro nel browser** (manuale, nel browser integrato di Claude, contro il sistema migrato da json a PostgreSQL): primo login e cambio password obbligatorio (anche dopo un ricaricamento), pannelli superadmin, operatività, conflitto 409, sessione invalidata, riavvio e disconnessione, stampa, nomi con HTML. Eseguito anche in questa fase sul sistema migrato con container veri (migrazione json → PostgreSQL con squadre risolte e creata "Non assegnata", login con cambio password obbligatorio anche dopo un ricaricamento, dati e badge delle giornate, stampa, blocco dell'eliminazione della squadra, conflitto 409 con un secondo utente, riavvio del server con ritorno al login e dati intatti; nella console solo gli errori HTTP provocati apposta). Non è automatizzato (richiederebbe un browser automatico solo per i test).

**Cosa il collaudo non copre:** la GUI di Synology DSM 7.1 (nessun NAS disponibile: le istruzioni in README seguono gli stessi parametri provati con `docker run`/compose, ma i nomi delle voci vanno verificati sul NAS); i dati reali di produzione (solo quelli possono rivelare incoerenze: **prima della migrazione vera eseguire il solo rapporto — senza `MIGRATE_EXECUTE` — su una copia dei dati**, che elenca problemi, avvisi e squadre che verrebbero create senza scrivere nulla); l'architettura ARM (il NAS è x64 e l'immagine è compilata per x64).

### Metodo e regole
- **Non riscrivere a memoria il codice del branch `dev`:** si parte dai file di `dev` (`git show origin/dev:<file>`) e si adattano.
- **Fase 2:** la logica auth/REST di `dev` si porta mantenendo i nomi di funzioni ed endpoint; cambia solo lo strato dati (da `_read_json`/`_write_json` a `storage.py`). Rimuovere ciò che `dev` aveva e Docker non vuole (tray, `server.lock`, file accanto al codice).
- **Fase 3:** i file frontend modificati sia su `main` sia su `dev` (`api.js`, `render.js`, `utils.js`, `modal-consegna.js`, `stampa.js`, `components.css`) vanno uniti **con merge a tre vie file per file** (base `9da9f00`), non copiati. Interventi di `main` da conservare: `X-Client-ID` su ogni richiesta, sidebar giornate in ordine decrescente, nuovi tipi di installazione (`ins_incasso`, `ins_muro`, `ins_sbs`). Fix di `dev` da conservare: `a0c9bbb` (5 bug core), `552682a` (form inline per cambio password), `f05bf13` (timer toast), `6b2b0be` (pulizia codice morto), `b19ba3a` (modal utenti per admin). Applicare la decisione `API = '/api'` (§7).
- **Fase 1:** ogni comportamento si verifica su tutti e tre i backend; un test non è valido se passa solo su JSON.
- Dopo ogni fase: rilettura dei blocchi modificati, verifica di coerenza nomi funzioni/endpoint (§1.3) e aggiornamento di questa tabella.

### Requisiti di `migrate.py` (fase 4) 🚧
- **Sorgente e destinazione**: ciascuno dei tre backend (json, mysql, postgres), in qualsiasi combinazione, selezionabili da configurazione/argomenti (interfaccia da definire).
- Trasformazione V1 → V2: crea il negozio "Negozio principale"; aggiunge `negozio_id` e `versione: 1` a tutte le consegne, giornate e squadre; crea il superadmin (`is_superadmin = true`, password di default `admin` con hash pre-calcolato, `primo_login = true`); crea `tipi_account` vuoto. Gli ID V1 non vengono modificati; il nome della squadra delle giornate diventa `squadra_id` (fase 6).
- **Protezioni** (proposte): backup completo della sorgente prima di scrivere; blocco contro la doppia esecuzione (file flag nel volume o tabella `migrazioni`); sorgente mai modificata; verifica finale con conteggio record per collezione tra sorgente e destinazione.
- **La destinazione deve essere un archivio vuoto** (database nuovo o cartella dati nuova): il controllo dello schema (§6) impedisce di migrare "sul posto" sopra tabelle o file V1. `init_storage_v2()` marca la destinazione V2 appena la inizializza; subito dopo `migrate.py` imposta il flag `migrazione_in_corso` e lo toglie solo a verifica conclusa: una migrazione interrotta lascia così una destinazione che il server si rifiuta di avviare. La sorgente V1 si legge con le funzioni V1 (`read_data`).
- Dopo la migrazione nessun utente oltre al superadmin esiste: vanno creati dal pannello (§9).

### Punti aperti (da decidere prima o durante la fase indicata)
| # | Punto | Fase |
|---|-------|------|
| 1 | ~~Firma dell'API di `storage.py`~~ definitiva, implementata e collaudata sui tre backend (§6) | 1 ✅ |
| 2 | ~~Vincoli SQL~~ deciso e applicato su PostgreSQL e MySQL (§6) | 1 ✅ |
| 3 | ~~Comportamento del server su `StorageError`~~ deciso: risposta 500 senza far cadere il server (il motivo del crash di V1, evitare di scrivere dati corrotti, non esiste più con lo storage per record). All'avvio: `SchemaError` → uscita con codice 2, altro `StorageError` → codice 1 | 2 ✅ |
| 4 | ~~Timestamp di polling per negozio~~ deciso e implementato (in memoria, per negozio) | 2 ✅ |
| 5 | ~~`migrate.py`~~ decisi: destinazione sempre nuova; `import_data.py` resta intatto (solo V1), `migrate.py` legge anche il `dati.json` di Windows. Dati dell'era `dev` da preservare: non necessario (`dev` non è mai andato in produzione) | 4 ✅ |
| 6 | ~~Ambiente di sviluppo isolato dalla produzione~~ non necessario: la produzione sta su un altro server e i test usano `compose.test.yaml` (progetto separato, nessun volume né porta pubblicata) | ✅ |
| 7 | Connessione per operazione: ~32 ms su MySQL (TLS + autenticazione) contro ~4 ms su PostgreSQL. Ogni scrittura del server V2 fa ~4 letture (risposta con il db del negozio) più la scrittura: ~150 ms su MySQL, accettabile. Da rivalutare solo se serve (riuso delle connessioni, TLS disattivato su rete Docker privata) | rimandato |
| 8 | ~~Il server V2 traduce `SchemaError` in un errore di avvio leggibile~~ fatto (messaggio nel log, uscita con codice 2) | 2 ✅ |

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
