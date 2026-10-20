# Gestione Consegne

Sistema completo per la gestione di consegne e installazioni, progettato per team di lavoro. Permette di pianificare le attività, assegnarle a squadre e monitorare lo stato delle consegne.

> 🚧 **V2 in sviluppo (branch `v2-docker`):** login multi-utente, permessi per tipo di account e multi-negozio. Le sezioni marcate **🚧 V2** descrivono la versione in sviluppo e **non sono ancora disponibili** su `main`. Stato e fasi di avanzamento: `AGENTS.md`, §11. Al momento sono pronti lo storage (fase 1), il server (fase 2) e il frontend (fase 3); manca `migrate.py` (fase 4), quindi i dati V1 esistenti non si possono ancora portare nella V2.

## 📋 Funzionalità principali

### Gestione Consegne
- **Creazione e modifica consegne** con dettagli completi (cliente, indirizzo, prodotto, note)
- **Stati consegna**: In attesa, Da confermare, Programmata, Completata, Annullata, Da riprogrammare
- **Articoli multipli per consegna** con tipologie indipendenti per articolo
- **Ricerca e filtri** per nome cliente, città e stato consegna

### Pianificazione Giornate
- **Organizzazione per date** con drag & drop delle consegne
- **Assegnazione a squadre** con colori distintivi
- **Statistiche giornaliere** (totale consegne, completate)
- **Stampa PDF** delle liste giornaliere

### Multi-utente e Sincronizzazione
- **Accesso concorrente** da più client nella stessa rete
- **Sincronizzazione automatica** ogni 8 secondi
- **Contatore utenti connessi** in tempo reale
- **Gestione disconnessioni** con schermata di blocco

> **Nota tecnica sul contatore:** il conteggio si basa su un identificatore univoco per scheda browser (header `X-Client-ID`, generato con `crypto.getRandomValues()` e salvato in `sessionStorage`), non sull'indirizzo IP. Questo è necessario perché in Docker più client reali possono condividere lo stesso IP sorgente (NAT). Le richieste dell'healthcheck interno di Docker non vengono conteggiate.

### Autenticazione e multi-negozio 🚧 V2
- **Login multi-utente** con Challenge-Response SHA-256 (compatibile con HTTP su rete locale)
- **Tipi account configurabili** con permessi granulari, definiti dal superadmin
- **Multi-negozio**: ogni utente appartiene a un negozio e vede solo i dati del proprio negozio
- **Sessioni con scadenza** dopo 2 ore di inattività (ping e aggiornamento automatico in background non la prolungano: conta solo l'attività dell'utente)
- **Protezione dalle modifiche concorrenti**: se due utenti modificano la stessa consegna, il secondo riceve un avviso e deve ricaricare
- **Log degli accessi e delle operazioni** con utente e IP

## 👥 Tipi account e permessi 🚧 V2

- Il **superadmin** è un account puramente amministrativo: gestisce **negozi**, **tipi account** e **utenti**, ma **non ha accesso ai dati operativi** (consegne, giornate, squadre).
- I **tipi account** sono creati dal superadmin, sono globali (condivisi da tutti i negozi) e contengono un insieme di permessi. Un utente ha un tipo account e un negozio.
- Un utente senza tipo account assegnato non può accedere.
- Modificare i permessi di un tipo account ha effetto al login successivo degli utenti; cambiare il tipo account di un utente ha effetto immediato (sessioni invalidate).

| Gruppo | Permessi assegnabili |
|--------|----------------------|
| Consegne | `consegne.leggi`, `consegne.scrivi`, `consegne.elimina` |
| Giornate | `giornate.leggi`, `giornate.crea`, `giornate.elimina`, `giornate.assegna`, `giornate.riordina`, `giornate.segna_completata` |
| Squadre | `squadre.leggi`, `squadre.gestisci` |
| Stampa | `stampa.pdf` |
| Tipi account | `tipi_account.leggi` |
| Utenti | `utenti.leggi`, `utenti.crea`, `utenti.modifica`, `utenti.elimina` |

Riservati al superadmin (non assegnabili): `tipi_account.gestisci`, `negozi.gestisci`. Le dipendenze tra permessi (es. `consegne.scrivi` richiede `consegne.leggi`) sono segnalate con avvisi nel pannello, senza selezione automatica.

## 🔐 Sicurezza in rete locale (HTTP) 🚧 V2

Il sistema usa **Challenge-Response con SHA-256** per proteggere le credenziali su reti HTTP non cifrate:

1. Il client richiede un **challenge** monouso al server (valido 60 secondi)
2. Calcola `response = SHA-256(SHA-256(password) + challenge)` in JS puro (senza `crypto.subtle`, che non è disponibile su HTTP via IP LAN)
3. Il server verifica la risposta senza mai ricevere la password in chiaro
4. Il challenge è monouso e scade in 60 secondi, quindi una risposta intercettata non è riutilizzabile
5. Le password sono memorizzate come `sha256(password)`

> **Limiti noti:** chi accedesse al database o al volume dati potrebbe usare l'hash memorizzato per autenticarsi (è intrinseco a questo schema); non c'è un limite ai tentativi di login. Dettagli in `AGENTS.md`, §5.

### Primo accesso
- Username: `superadmin` — Password: `admin`
- Il cambio password è **obbligatorio** al primo login. Eseguirlo subito dopo il primo avvio.
- Poi, dal pannello: crea un **negozio** → un **tipo account** → un **utente** con quel negozio e quel tipo.

## 🚀 Deploy con Docker

### Prerequisiti
- Docker Engine 25+ e Docker Compose V2
- Accesso al registry `undermix/gestione-consegne`

### Configurazione

Crea un file `.env` nella stessa directory di `compose.yaml`:

```env
APP_PORT=8080

# Backend dati: json | mysql | postgres
DB_BACKEND=json

# Solo per mysql/postgres:
DB_NAME=gestione_consegne
DB_USER=gcuser
DB_PASSWORD=cambiami_con_password_sicura
```

### Avvio

**Backend JSON (default):**
```bash
docker compose up -d
```

**Backend MySQL:**
```bash
docker compose --profile mysql up -d
```

**Backend PostgreSQL:**
```bash
docker compose --profile postgres up -d
```

### Importazione dati esistenti (one-shot)

Se possiedi un `dati.json` proveniente dalla versione Windows, importalo prima di avviare l'app.

**Backend JSON:**
```bash
docker compose run --rm \
  -v ./dati.json:/import/dati.json:ro \
  app python import_data.py

docker compose up -d
```

**Backend MySQL o PostgreSQL:** il database deve essere già avviato e pronto (`service_healthy`) prima di eseguire l'importazione, perché lo script inizializza lo schema e scrive i dati al suo interno. `docker compose run` avvia automaticamente le dipendenze dichiarate (`depends_on`), quindi il DB parte da solo se non è già attivo:

```bash
# 1. Importa (avvia automaticamente anche il DB, se non è già up)
docker compose --profile mysql run --rm \
  -v ./dati.json:/import/dati.json:ro \
  app python import_data.py

# 2. Avvia l'app
docker compose --profile mysql up -d
```
Sostituire `mysql` con `postgres` per il backend PostgreSQL.

Lo script è protetto da doppia esecuzione: dopo la prima importazione riuscita crea il file `/data/import_done`. Per forzare una reimportazione, rimuovere quel file dal volume prima di rieseguire.

### Healthcheck

Docker verifica automaticamente che il server risponda su `/api/ping` ogni 15 secondi. Puoi monitorare lo stato con:

```bash
docker inspect --format='{{.State.Health.Status}}' gestione-consegne-app-1
```

### Migrazione dei dati V1 → V2 🚧

Per portare i dati esistenti (V1) allo schema V2 è prevista la **migrazione con `migrate.py`**, che funzionerà con tutti e tre i backend (JSON, MySQL, PostgreSQL) sia come sorgente sia come destinazione. Lo script non è ancora disponibile (fase 4, `AGENTS.md` §11). **Il server V2 si rifiuta di partire** (con un messaggio nel log, senza modificare nulla) se trova dati V1 o uno schema non valido: con `restart: unless-stopped` Docker lo riavvia in ciclo finché non si migra o si usa un database/cartella dati nuovi. La migrazione scrive sempre su una destinazione nuova. Dopo la migrazione esiste solo il superadmin: gli altri utenti vanno creati dal pannello.

## 🛠️ Tecnologie

### Backend
- **Python 3.13** — Server HTTP integrato (stdlib pura, nessun framework)
- **Backend dati selezionabile**: file JSON separati, MySQL 8.4, PostgreSQL 16
- **Log su stdout** — catturati e gestiti da Docker
- 🚧 **V2:** accesso ai dati per singolo record (su tutti i backend) con controllo di concorrenza (`versione`); autenticazione Challenge-Response SHA-256 con sessioni in memoria

### Frontend
- **HTML5 / CSS3** — Struttura e stile, senza build step
- **JavaScript ES Modules (nativi)** — Logica modulare, importata direttamente dal browser
- **Tema chiaro/scuro** — Adattabile alle preferenze dell'utente

> **Nota tecnica:** il frontend usa `<script type="module">`, supportato da tutti i browser moderni. Non è necessario alcun bundler (Vite, Webpack, ecc.) né Node.js.

## 📁 Struttura del progetto

```
gestione_consegne/
├── server.py               # Server HTTP e logica backend (V2: auth, sessioni, REST, permessi)
├── storage.py              # Astrazione backend dati (json/mysql/postgres): V1 legacy + V2 per singolo record ✅
├── import_data.py          # Script importazione one-shot da dati.json legacy
├── migrate.py              # 🚧 V2: migrazione V1→V2 e tra backend (non ancora presente)
├── requirements.txt        # Dipendenze Python (mysql-connector, psycopg2)
├── Dockerfile              # Immagine Docker
├── compose.yaml            # Orchestrazione container e profili DB
├── compose.test.yaml       # 🚧 V2: database temporanei per i test dello storage (separato dalla produzione)
├── tests/                  # 🚧 V2: suite di contratto di storage.py e test di server.py (non inclusi nell'immagine); controlli statici del frontend (tests/js)
├── index.html              # Shell HTML: struttura, modali, nav
│
├── css/
│   ├── theme.css           # Variabili CSS, palette squadre, temi chiaro/scuro
│   ├── layout.css          # Reset, header, sidebar, struttura app
│   └── components.css      # Bottoni, pill, badge, tabella, card, modal, form, toast
│
└── js/
    ├── main.js             # Entry point: init, polling, espone globali per onclick HTML
    ├── store.js            # Stato globale condiviso (db, currentView, flags, setter)
    ├── api.js              # Layer HTTP: fetchData, postData, ping, remoteLog
    ├── sync.js             # loadData, saveData, markDirty, ping, overlay disconnessione
    ├── render.js           # renderAll, switchView, renderLista, renderSidebar, renderGiornata
    ├── utils.js            # uid, fmtDate, statoPill, tipoBadge, sqBadgeHtml, toast, openModal
    ├── theme.js            # initTheme, applyTheme, toggleTheme
    ├── dragdrop.js         # Drag & drop ordinamento card giornata
    ├── giornate.js         # removeFromGiornata, segnaConsegnata, deleteGiornata, modal nuova giornata
    ├── modal-consegna.js   # Modal creazione/modifica consegna, gestione articoli
    ├── modal-select.js     # Modal selezione consegne da aggiungere a giornata
    ├── squadre.js          # CRUD squadre: add, rename, color, delete
    ├── stampa.js           # Stampa PDF giornata
    ├── clientid.js         # 🚧 V2: identificatore X-Client-ID della scheda
    ├── sha256.js           # 🚧 V2: SHA-256 puro JS per il Challenge-Response
    ├── auth.js             # 🚧 V2: login, logout, cambio password, token di sessione
    ├── permessi.js         # 🚧 V2: lista permessi, dipendenze, hasPermesso()
    ├── modal-utenti.js     # 🚧 V2: gestione utenti (permessi utenti.*)
    └── modal-admin.js      # 🚧 V2: pannello superadmin (caricato solo per il superadmin)
```

In V2 i file `api.js`, `sync.js`, `store.js`, `render.js`, `giornate.js`, `squadre.js`, `modal-consegna.js` e `modal-select.js` passano a chiamate REST e polling a timestamp (dettagli in `AGENTS.md`, §3 e §7).

## ⚙️ Variabili d'ambiente

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `PORT` | `8080` | Porta interna del server |
| `LOG_LEVEL` | `INFO` | Livello di log: `DEBUG` (include ogni richiesta HTTP) \| `INFO` \| `WARNING` \| `ERROR` |
| `DB_BACKEND` | `json` | Backend dati: `json` \| `mysql` \| `postgres` |
| `DATA_DIR` | `/data` | Directory file JSON (ignorata per mysql/postgres) |
| `DB_HOST` | `db` | Host del database |
| `DB_PORT` | `3306` / `5432` | Porta del database |
| `DB_NAME` | `gestione_consegne` | Nome del database |
| `DB_USER` | — | Utente del database |
| `DB_PASSWORD` | — | Password del database |
| `IMPORT_SOURCE` | `/import/dati.json` | Path del file sorgente per import_data.py |

## 👥 Gestione Squadre

Il sistema supporta fino a 8 squadre con colori assegnabili:

| Indice | Colore |
|--------|--------|
| 0 | Blu `#4f8aff` |
| 1 | Verde `#22c55e` |
| 2 | Arancione `#f59e0b` |
| 3 | Rosso `#ef4444` |
| 4 | Viola `#a855f7` |
| 5 | Azzurro `#06b6d4` |
| 6 | Arancio scuro `#f97316` |
| 7 | Rosa `#ec4899` |

## 📱 Interfaccia Utente

### Viste principali
1. **Lista Consegne** — Visualizzazione tabellare con filtri per stato e città
2. **Giornate** — Pianificazione per date con drag & drop e sidebar
3. **Impostazioni** — Gestione squadre con rinomina e selezione colore
4. 🚧 **V2 — Gestione utenti** — per gli account con permessi `utenti.*`
5. 🚧 **V2 — Pannello superadmin** — Negozi, Tipi account, Utenti (il superadmin vede solo questo)

In V2 le voci visibili dipendono dai permessi del tipo account dell'utente.

### Logica stati consegna

| Stato | Significato | Nel popup "Aggiungi a giornata"? |
|-------|-------------|----------------------------------|
| `in_attesa` | Non ancora assegnata | ✅ Sì |
| `da_riprogrammare` | Era assegnata, da rifare | ✅ Sì |
| `da_confermare` | Assegnata, in attesa conferma | ❌ No |
| `programmata` | Confermata | ❌ No |
| `completata` | Consegnata | ❌ No |
| `annullata` | Cancellata | ❌ No |

## 📊 Log e Audit

I log vengono scritti su **stdout** e gestiti da Docker (`docker compose logs -f app`); il livello si imposta con `LOG_LEVEL`.

🚧 **V2:** ogni operazione viene registrata lato server con utente e IP, per categoria:

```
2026-06-18 10:00:00 [INFO]  [AUTH]         superadmin ha effettuato il login da 192.168.1.15
2026-06-18 10:05:00 [INFO]  [NEGOZI]       Negozio 'Sede principale' creato da 'superadmin'
2026-06-18 10:10:00 [INFO]  [UTENTI]       Utente 'mario.rossi' (Admin) creato per negozio 'Sede principale' da 'superadmin'
2026-06-18 10:15:00 [INFO]  [DATI]         'mario.rossi' — Nuova consegna: Rossi Mario
2026-06-18 10:30:00 [WARN]  [AUTH]         Login fallito — password errata per 'pippo' da 192.168.1.33
```

Categorie: `[AUTH]`, `[UTENTI]`, `[DATI]`, `[NEGOZI]`, `[TIPI_ACCOUNT]`. In Docker l'IP registrato può essere quello del gateway/NAT e non quello reale del client.

## 🛡️ Sicurezza

- Utente non-root (`appuser:1001`) nel container
- Filesystem container in sola lettura (`read_only: true`)
- Database non esposto sull'host (solo rete interna Docker)
- Scrittura atomica dei dati (tmp + rename)
- Protezione path traversal nel file server
- Healthcheck attivo su `/api/ping`
- 🚧 **V2:** autenticazione obbligatoria, permessi per tipo account, isolamento dei dati per negozio, log degli accessi (vedi sezioni dedicate sopra)
- 🚧 **V2:** istanza applicativa unica (sessioni in memoria): un riavvio del container disconnette gli utenti

## 🔧 Linee guida per sviluppatori

### Aggiungere una nuova funzionalità
1. Se tocca solo la UI di una vista → modifica `render.js` o crea un nuovo file in `js/`
2. Se aggiunge un nuovo tipo di dato → aggiorna `store.js` con il setter
3. Se aggiunge una chiamata HTTP → aggiungila in `api.js`
4. Se la funzione deve essere chiamabile da un `onclick` → registrala su `window` in `main.js`

### 🚧 V2 — Regole per i nuovi endpoint e per lo schema
1. Un nuovo endpoint operativo verifica nell'ordine: token valido (401) → permesso (403) → `negozio_id` della risorsa (403)
2. Filtra sempre per `negozio_id` e registra l'operazione nel log con categoria `[DATI]`
3. Le modifiche allo schema vanno fatte in `storage.py` su **tutti e tre** i backend e riportate in `migrate.py`
4. Prima di iniziare una fase di sviluppo V2 leggi `AGENTS.md` §11 (stato, metodo, punti aperti)
5. Test dello storage e del server (in Docker, con database temporanei separati dalla produzione): `docker compose -f compose.test.yaml up --build --exit-code-from tests`, poi `docker compose -f compose.test.yaml down`. Controlli statici del frontend e test di `sha256.js` (Node nell'immagine `node:22-alpine`, solo per i test): `docker compose -f compose.test.yaml run --rm jstests`. Dettagli in `AGENTS.md` §6 e §11

### Build e push dell'immagine
```bash
docker build -t undermix/gestione-consegne:latest .
docker push undermix/gestione-consegne:latest
```

### Build con UID/GID personalizzato
```bash
docker build --build-arg APP_UID=1500 --build-arg APP_GID=1500 \
  -t undermix/gestione-consegne:latest .
```

## 📄 Licenza

Software proprietario per uso interno. Non redistribuibile.
