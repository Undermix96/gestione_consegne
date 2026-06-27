# Gestione Consegne

Sistema completo per la gestione di consegne e installazioni, progettato per team di lavoro. Permette di pianificare le attività, assegnarle a squadre e monitorare lo stato delle consegne.

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

Se possiedi un `dati.json` proveniente dalla versione Windows, importalo così:

```bash
docker compose run --rm \
  -v ./dati.json:/import/dati.json:ro \
  app python import_data.py
```

Lo script è protetto da doppia esecuzione: dopo la prima importazione riuscita crea il file `/data/import_done`. Per forzare una reimportazione, rimuovere quel file dal volume prima di rieseguire.

### Healthcheck

Docker verifica automaticamente che il server risponda su `/api/ping` ogni 15 secondi. Puoi monitorare lo stato con:

```bash
docker inspect --format='{{.State.Health.Status}}' gestione-consegne-app-1
```

## 🛠️ Tecnologie

### Backend
- **Python 3.13** — Server HTTP integrato (stdlib pura, nessun framework)
- **Backend dati selezionabile**: file JSON separati, MySQL 8.4, PostgreSQL 16
- **Log su stdout** — catturati e gestiti da Docker

### Frontend
- **HTML5 / CSS3** — Struttura e stile, senza build step
- **JavaScript ES Modules (nativi)** — Logica modulare, importata direttamente dal browser
- **Tema chiaro/scuro** — Adattabile alle preferenze dell'utente

> **Nota tecnica:** il frontend usa `<script type="module">`, supportato da tutti i browser moderni. Non è necessario alcun bundler (Vite, Webpack, ecc.) né Node.js.

## 📁 Struttura del progetto

```
gestione_consegne/
├── server.py               # Server HTTP e logica backend
├── storage.py              # Astrazione backend dati (json/mysql/postgres)
├── import_data.py          # Script importazione one-shot da dati.json legacy
├── requirements.txt        # Dipendenze Python (mysql-connector, psycopg2)
├── Dockerfile              # Immagine Docker
├── compose.yaml            # Orchestrazione container e profili DB
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
    └── stampa.js           # Stampa PDF giornata
```

## ⚙️ Variabili d'ambiente

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `PORT` | `8080` | Porta interna del server |
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

### Logica stati consegna

| Stato | Significato | Nel popup "Aggiungi a giornata"? |
|-------|-------------|----------------------------------|
| `in_attesa` | Non ancora assegnata | ✅ Sì |
| `da_riprogrammare` | Era assegnata, da rifare | ✅ Sì |
| `da_confermare` | Assegnata, in attesa conferma | ❌ No |
| `programmata` | Confermata | ❌ No |
| `completata` | Consegnata | ❌ No |
| `annullata` | Cancellata | ❌ No |

## 🛡️ Sicurezza

- Utente non-root (`appuser:1001`) nel container
- Filesystem container in sola lettura (`read_only: true`)
- Database non esposto sull'host (solo rete interna Docker)
- Scrittura atomica dei dati (tmp + rename)
- Protezione path traversal nel file server
- Healthcheck attivo su `/api/ping`

## 🔧 Linee guida per sviluppatori

### Aggiungere una nuova funzionalità
1. Se tocca solo la UI di una vista → modifica `render.js` o crea un nuovo file in `js/`
2. Se aggiunge un nuovo tipo di dato → aggiorna `store.js` con il setter
3. Se aggiunge una chiamata HTTP → aggiungila in `api.js`
4. Se la funzione deve essere chiamabile da un `onclick` → registrala su `window` in `main.js`

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
