# Gestione Consegne

Sistema completo per la gestione di consegne e installazioni, progettato per team di lavoro. Permette di pianificare le attività, assegnarle a squadre e monitorare lo stato delle consegne.

> 🚧 **V2 in sviluppo (branch `v2-docker`):** login multi-utente, permessi per tipo di account e multi-negozio. Le sezioni marcate **🚧 V2** descrivono la versione in sviluppo e **non sono ancora disponibili** su `main`. Stato e fasi di avanzamento: `AGENTS.md`, §11. Al momento sono pronti lo storage (fase 1), il server (fase 2) e il frontend (fase 3); anche la migrazione dei dati (`migrate.py`, fase 4) è pronta. Il collaudo integrato (fase 5) è stato eseguito: vedi `AGENTS.md` §11.

## 📋 Funzionalità principali

### Gestione Consegne
- **Creazione e modifica consegne** con dettagli completi (cliente, indirizzo, prodotto, note)
- **Stati consegna**: In attesa, Da confermare, Programmata, Completata, Annullata, Da riprogrammare
- **Articoli multipli per consegna** con tipologie indipendenti per articolo
- **Ricerca e filtri** per nome cliente, città e stato consegna

### Pianificazione Giornate
- **Organizzazione per date** con drag & drop delle consegne
- **Assegnazione a squadre** con colori distintivi (ogni giornata ha una squadra; una squadra con giornate non si può eliminare)
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
- Modificare i permessi di un tipo account o cambiare il tipo account di un utente ha effetto immediato: le sessioni interessate vengono chiuse e gli utenti devono rifare il login. Una sessione dura al massimo 12 ore.

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

> **Limiti noti:** chi accedesse al database o al volume dati potrebbe usare l'hash memorizzato per autenticarsi (è intrinseco a questo schema); i tentativi di login sono limitati ma, se il server vede sempre lo stesso IP (NAT), vedi sotto. Dettagli in `AGENTS.md`, §5.

### Tentativi di accesso e IP dei client (NAT)
- Dopo 10 password errate sullo stesso username in 5 minuti (e dopo 20 dallo stesso IP) il server risponde 429 per qualche minuto.
- Oltre 10 errori di login in un minuto, da chiunque, **tutte** le risposte di errore del login si fanno attendere sempre di più (fino a 3 secondi): rallenta chi prova una password su molti username, senza bloccare nessuno. Chi ha la password giusta non aspetta.
- **Se il server vede sempre lo stesso IP** (Docker Desktop, alcuni NAS, NAT): i limiti per IP sarebbero condivisi da tutti i client. Si risolve in uno di due modi, da `.env`:
  - `LOGIN_MAX_FAIL_IP=0` e `CHALLENGE_MAX_IP=0`: restano il limite per username e il rallentamento globale;
  - se davanti all'app c'è un reverse proxy, `TRUSTED_PROXIES=<ip del proxy>`: i limiti usano l'IP reale del client letto da `X-Forwarded-For`. L'header è ignorato se la richiesta non arriva da un proxy elencato (altrimenti chiunque potrebbe falsificarlo).

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

### Backup 🚧 V2

I dati si salvano **in automatico ogni 6 ore, solo se ci sono state modifiche** (`BACKUP_INTERVAL` in secondi, `0` = disattivato), conservando gli ultimi 30 (`BACKUP_KEEP`). Vale per tutti i backend:

| Backend | Cosa viene salvato | File |
|---|---|---|
| JSON | snapshot dei file dei dati | `backup/<collezione>.<data>.json` |
| PostgreSQL | dump con `pg_dump` (versione 16, come il database del compose) | `backup/postgres-<database>.<data>.sql.gz` |
| MySQL | dump con `mysqldump` (versione 8.4, come il database del compose) | `backup/mysql-<database>.<data>.sql.gz` |

- **Dove:** nella cartella `backup` dei dati, cioè dentro `/data` del container. **Con un database serve una cartella montata su `/data`** (con compose c'è già il volume `app_data`; su DSM mappare una cartella del NAS su `/data`), altrimenti il backup fallisce con un avviso nei log e l'app continua a funzionare. La cartella deve essere scrivibile dall'utente 1001 del container.
- **Dal pannello:** l'account `superadmin` ha la scheda **Backup**: elenco dei file e pulsante **Esegui backup ora**.
- **Da riga di comando:** `docker exec <container> python backup.py` (codice di uscita 0 se riesce, 1 altrimenti): utile per un'attività pianificata di DSM o di cron. Dopo una migrazione la destinazione ha già un backup iniziale.
- **Fuori dal server:** i file vanno copiati altrove con i propri strumenti (copia su un altro disco o NAS): un backup nello stesso posto dei dati non protegge da un guasto del disco.
- **Ripristino** (in un database **vuoto**, con gli stessi strumenti che sono nell'immagine; fermare prima l'app):
  - PostgreSQL: `gunzip -c backup/postgres-NOME.DATA.sql.gz | psql -h HOST -U UTENTE -d DATABASE -v ON_ERROR_STOP=1` (password in `PGPASSWORD`)
  - MySQL: `gunzip -c backup/mysql-NOME.DATA.sql.gz | mysql -h HOST -u UTENTE DATABASE` (password in `MYSQL_PWD`)
  - JSON: copiare i file di uno snapshot (stessa data nel nome) in una cartella dati nuova, togliendo la data dal nome (`consegne.2026-…json` → `consegne.json`, compreso `meta.json`).
  - Con `docker run`/compose (esempio PostgreSQL, rete del database): `docker run --rm --network RETE -v CARTELLA_DATI:/data:ro -e PGPASSWORD=... IMMAGINE sh -c 'gunzip -c /data/backup/FILE.sql.gz | psql -h HOST -U UTENTE -d DATABASE -v ON_ERROR_STOP=1'`; su DSM lo stesso comando si lancia dalla scheda *Terminale* del container, oppure con un container temporaneo come per la migrazione.
  - Poi avviare l'app sul database ripristinato: utenti, password e dati sono quelli del momento del backup.

### Healthcheck

Docker verifica automaticamente che il server risponda su `/api/ping` ogni 15 secondi. Puoi monitorare lo stato con:

```bash
docker inspect --format='{{.State.Health.Status}}' gestione-consegne-app-1
```

### Migrazione dei dati verso la V2 (`migrate.py`)

Porta i dati V1 (json, MySQL o PostgreSQL), il `dati.json` della versione Windows, oppure un archivio V2 (per cambiare backend) in un archivio V2 **nuovo**. Funziona allo stesso modo con `docker compose`, con `docker run` e dalla GUI di Docker (Synology DSM 7.1, Portainer): è configurato solo con variabili d'ambiente, cartelle montate e comando del container.

**Principi**
- **Senza `MIGRATE_EXECUTE=1` non scrive nulla.** Il primo avvio produce solo un rapporto (cosa trova, cosa farebbe, quali problemi ci sono). Si legge nei log del container; se è tutto a posto si rilancia con `MIGRATE_EXECUTE=1`.
- **La sorgente non viene mai modificata.** Il file di esportazione (`/migration/export-<data>.json`) è una copia completa dei dati di partenza: **conservarlo** (contiene i dati dei clienti).
- **La destinazione deve essere nuova e completamente vuota**: un'altra cartella dati, un altro volume o un altro database. Il server V2 si rifiuta comunque di partire su dati V1. I dati V1 restano dove sono, intatti, fino a quando decidi di eliminarli.
- Alla fine ogni record viene **riletto dalla destinazione e confrontato** con l'originale. Se la scrittura o la verifica falliscono, la destinazione resta marcata come "migrazione in corso" e il server V2 non parte: si ricrea la destinazione (nuova cartella o database vuoto) e si rilancia.
- **Squadre:** nella V2 ogni giornata ha una squadra obbligatoria (`squadra_id`). La migrazione trasforma il nome della squadra di ogni giornata nella squadra corrispondente, crea le squadre mancanti e segnala tutto nel rapporto; le giornate senza squadra vengono assegnate a una squadra "Non assegnata", creata solo se serve.
- Dopo la migrazione esiste solo l'account `superadmin` (password `admin`, da cambiare al primo accesso): gli altri utenti vanno creati dal pannello.

**Variabili d'ambiente** (ogni opzione ha anche un argomento: `python migrate.py --help`)

| Variabile | Significato |
|---|---|
| `DB_BACKEND`, `DATA_DIR`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | **Destinazione**: gli stessi valori che userà il server V2 (con `json`: la cartella montata su `/data`) |
| `MIGRATE_SOURCE_KIND` | `v1` (default), `file` (il `dati.json` di Windows) o `v2` (cambio di backend) |
| `SRC_BACKEND` | Backend della sorgente: `json` (default), `mysql`, `postgres` |
| `SRC_DATA_DIR` | Cartella dati della sorgente json (default `/source`, montarla in sola lettura) |
| `SRC_FILE` | Percorso del `dati.json` (default `/source/dati.json`) |
| `SRC_DB_HOST`, `SRC_DB_PORT`, `SRC_DB_USER`, `SRC_DB_PASSWORD` | Connessione alla sorgente SQL (se omessi valgono quelli della destinazione) |
| `SRC_DB_NAME` | Nome del database sorgente (obbligatorio per mysql/postgres; deve essere diverso da `DB_NAME` se il server è lo stesso) |
| `MIGRATE_EXECUTE` | `1` = scrive davvero (altrimenti solo rapporto) |
| `MIGRATE_CREATE_DB` | `1` = crea il database di destinazione se non esiste (mysql/postgres; l'utente deve poter creare database) |
| `MIGRATE_NEGOZIO_NOME` | Nome del negozio creato per i dati V1 (default `Negozio principale`) |
| `MIGRATE_SQUADRA_NON_ASSEGNATA` | Nome della squadra per le giornate V1 senza squadra (default `Non assegnata`): viene creata **solo se almeno una giornata ne ha bisogno** |
| `MIGRATE_KEEP_ORPHANS` | `1` = i riferimenti a consegne inesistenti bloccano la migrazione (default: vengono scartati e riportati nel rapporto) |
| `MIGRATE_OUT` | File di esportazione (default `/migration/export-<data>.json`) |

Cartelle da montare nel container: `/source` (sorgente json o `dati.json`, **sola lettura**), `/data` (destinazione json), `/migration` (file di esportazione). Devono essere scrivibili dall'utente 1001 del container (la sorgente no: è in sola lettura). Per un database come sorgente o destinazione il container deve poter raggiungere il database (stessa rete Docker). Il comando del container è `python migrate.py` (senza altri argomenti).

**Con docker compose** (destinazione = backend configurato in `.env`; con un database aggiungere il suo profilo)
```bash
# 1. rapporto: nulla viene scritto
SRC_HOST_DIR=/percorso/dati-v1 docker compose --profile migrate run --rm migrate
# 2. migrazione vera
SRC_HOST_DIR=/percorso/dati-v1 MIGRATE_EXECUTE=1 docker compose --profile migrate run --rm migrate
# sorgente su un database (es. destinazione json, sorgente postgres):
SRC_BACKEND=postgres SRC_DB_HOST=... SRC_DB_NAME=... SRC_DB_USER=... SRC_DB_PASSWORD=... \
  docker compose --profile migrate run --rm migrate
# destinazione su un database: --profile postgres (o mysql) in più, e DB_BACKEND nel .env
docker compose --profile postgres --profile migrate run --rm migrate
```

**Con docker (senza compose)**
```bash
docker run --rm \
  -v /percorso/dati-v1:/source:ro \
  -v /percorso/nuova-cartella-v2:/data \
  -v /percorso/migration:/migration \
  -e SRC_BACKEND=json \
  undermix/gestione-consegne:latest python migrate.py          # rapporto
# aggiungere  -e MIGRATE_EXECUTE=1  per eseguirla davvero
```
Altri scenari (sostituire/aggiungere le variabili):
- **json → PostgreSQL:** `-e DB_BACKEND=postgres -e DB_HOST=<host> -e DB_NAME=<nuovo-db> -e DB_USER=... -e DB_PASSWORD=... -e MIGRATE_CREATE_DB=1 --network <rete-del-db>` (senza `-v ...:/data`).
- **PostgreSQL/MySQL V1 → json:** `-e SRC_BACKEND=postgres -e SRC_DB_HOST=<host> -e SRC_DB_NAME=<db-v1> -e SRC_DB_USER=... -e SRC_DB_PASSWORD=... --network <rete-del-db>`, senza `/source`.
- **`dati.json` di Windows → V2:** `-v /cartella/con/dati.json:/source:ro -e MIGRATE_SOURCE_KIND=file`.
- **Cambio di backend V2 → V2:** `-e MIGRATE_SOURCE_KIND=v2` e le variabili `SRC_*` della V2 di partenza.

**Da Portainer:** creare uno *stack* dal file `compose.migrate.yaml` (funziona anche dove non c'è il plugin compose), compilare le variabili nella sezione *Environment variables* (`SRC_HOST_DIR`, `DATA_HOST_DIR`, `MIGRATE_HOST_DIR`, `DB_*`, `SRC_*`, `MIGRATE_*`; `DB_NETWORK` è il nome della rete Docker del database), avviare e leggere i *Logs* del container. Per eseguire: impostare `MIGRATE_EXECUTE=1` e ridistribuire lo stack.

**Da Synology DSM 7.1 (app Docker, interfaccia grafica)** — i nomi esatti delle voci possono variare leggermente tra le versioni del pacchetto:
1. *Registro/Immagine*: scaricare `undermix/gestione-consegne:latest` (se non c'è già).
2. Creare **due cartelle nuove** in *File Station* (es. `docker/gestione-consegne-v2/data` e `docker/gestione-consegne-v2/migration`) e **concedere la scrittura** (clic destro → Proprietà → Permessi) in modo che l'utente del container (UID 1001) possa scriverci. Con un database come destinazione non serve la cartella `data`.
3. *Container → Crea* dall'immagine. Nome a piacere (es. `gestione-consegne-migrazione`). **Non** abilitare il riavvio automatico.
4. *Impostazioni avanzate → Comando di esecuzione*: `python migrate.py`. (Il controllo di salute dell'immagine non è applicabile a un container che si ferma da solo: può comparire "unhealthy", è innocuo.)
5. *Impostazioni del volume → Aggiungi cartella*:
   - la cartella dei dati **V1** → `/source`, spuntare **sola lettura**;
   - la cartella nuova `data` → `/data`;
   - la cartella `migration` → `/migration`.
6. *Ambiente → Aggiungi*: le variabili della tabella (almeno `SRC_BACKEND`; con un database anche `DB_*`/`SRC_*`). Per mettere il container nella stessa rete del database: *Rete* → scegliere la rete del container del database (o, per i database sulla rete bridge predefinita, usare l'indirizzo IP del NAS e la porta pubblicata come `DB_HOST`/`SRC_DB_HOST`).
7. Avviare il container e aprire *Dettagli → Log*: deve comparire il rapporto, che termina con `ESITO: OK — rapporto senza problemi (nulla scritto)`. Un problema nei dati o nei percorsi è spiegato in chiaro (`ESITO: FALLITO` e il motivo).
8. Per migrare davvero: fermare il container, aggiungere la variabile `MIGRATE_EXECUTE` = `1` (modifica del container), avviarlo e controllare il log: `Verifica superata` e `ESITO: OK — migrazione completata`.
9. Creare il container V2 (immagine `undermix/gestione-consegne:latest`, comando predefinito) con **la nuova cartella `data` su `/data`** (o `DB_BACKEND` e `DB_*` del nuovo database) e la porta desiderata.
10. Conservare il file `export-....json` della cartella `migration`: è il backup completo dei dati di partenza.

Se il container di migrazione si riavvia per errore, non fa danni: la destinazione, ormai piena, viene rifiutata.

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
├── migrate.py              # 🚧 V2: migrazione V1→V2 e tra backend (da compose, docker o GUI) ✅
├── backup.py               # 🚧 V2: backup dei database (pg_dump / mysqldump), anche `python backup.py` ✅
├── requirements.txt        # Dipendenze Python (mysql-connector, psycopg2)
├── Dockerfile              # Immagine Docker
├── compose.yaml            # Orchestrazione container e profili DB
├── compose.migrate.yaml    # 🚧 V2: migrazione come stack autonomo (Portainer, DSM): vedi "Migrazione dei dati"
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
| `BACKUP_INTERVAL` | `21600` | Secondi tra due backup automatici (6 ore), solo se ci sono state modifiche; `0` = nessun backup automatico |
| `BACKUP_KEEP` | `30` | Quanti backup conservare (per tipo), con qualsiasi backend |
| `LOG_FILE_MAX_BYTES` | `5242880` | Dimensione massima di `/data/log/server.log` prima della rotazione; `0` = nessun log su file |
| `LOG_FILE_KEEP` | `10` | File di log ruotati conservati |
| `LOGIN_MAX_FAIL_IP` | `20` | Tentativi di login falliti per IP in 5 minuti prima del blocco (429); `0` = limite per IP disattivato (restano quelli per username) |
| `CHALLENGE_MAX_IP` | `50` | Challenge di login vivi per IP; `0` = nessun limite per IP |
| `TRUSTED_PROXIES` | _(vuoto)_ | IP o reti (CIDR) dei reverse proxy fidati, separati da virgola: solo per le richieste che arrivano da lì si usa l'IP reale dei client (`X-Forwarded-For`) |
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

Categorie: `[AUTH]`, `[UTENTI]`, `[DATI]`, `[NEGOZI]`, `[TIPI_ACCOUNT]`, `[BACKUP]`, `[LOG]`.

Oltre che nel log di Docker, il log è salvato in `/data/log/server.log` (ruotato a 5 MB, ultimi 10 file: `LOG_FILE_MAX_BYTES`, `LOG_FILE_KEEP`; `LOG_FILE_MAX_BYTES=0` lo disattiva). L'account `superadmin` ha la scheda **Log**: elenco dei file e download di ciascuno o di tutti in un `.zip`. I log contengono nomi utente e indirizzi IP. In Docker l'IP registrato può essere quello del gateway/NAT e non quello reale del client.

## 🛡️ Sicurezza

- Utente non-root (`appuser:1001`) nel container
- Filesystem container in sola lettura (`read_only: true`)
- Database non esposto sull'host (solo rete interna Docker)
- Scrittura atomica dei dati (tmp + rename)
- Protezione path traversal nel file server
- Healthcheck attivo su `/api/ping`
- 🚧 **V2:** autenticazione obbligatoria, permessi per tipo account, isolamento dei dati per negozio, log degli accessi (vedi sezioni dedicate sopra)
- 🚧 **V2:** timeout di 15 s sui socket e limite di 2 MB alle richieste; chi gestisce gli utenti non può assegnare o toccare permessi che non possiede
- 🚧 **V2:** tentativi di accesso limitati (20 falliti per IP e 10 per username in 5 minuti, poi 429) e sessioni chiuse alla revoca dei permessi; limiti noti (HTTP puro, ecc.): elenco completo nell'audit di sicurezza in `AGENTS.md` §5
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
5. Test dello storage e del server (in Docker, con database temporanei separati dalla produzione): `docker compose -f compose.test.yaml up --build --exit-code-from tests`, poi `docker compose -f compose.test.yaml down`. Controlli statici del frontend e test di `sha256.js` (Node nell'immagine `node:22-alpine`, solo per i test): `docker compose -f compose.test.yaml run --rm jstests`. Il collaudo integrato (sistema vero: migrazione, server, tutti i backend, concorrenza) gira alla fine di `run_all.sh` (`TEST_INTEGRATION=0` lo salta); la prova con le immagini vere dello stack (compose, `docker run`, stack Portainer) è `bash tests/stack.sh`, da lanciare sull'host con Docker. Dettagli in `AGENTS.md` §6 e §11

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
