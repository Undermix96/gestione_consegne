# Gestione Consegne

Sistema completo per la gestione di consegne e installazioni, progettato per team di lavoro in ambiente locale. Permette di pianificare le attività, assegnarle a squadre e monitorare lo stato delle consegne.

## 📋 Funzionalità principali

### Gestione Consegne
- **Creazione e modifica consegne** con dettagli completi (cliente, indirizzo, prodotto, note)
- **Stati consegna**: In attesa, Da confermare, Programmata, Completata, Annullata, Da riprogrammare
- **Tipologie**: Solo consegna, Installazione semplice, Installazione a incasso/muro
- **Ricerca e filtri** per nome cliente, città e stato consegna

### Pianificazione Giornate
- **Organizzazione per date** con drag & drop delle consegne
- **Assegnazione a squadre** con colori distintivi
- **Statistiche giornaliere** (totale consegne, completate)
- **Stampa PDF** delle liste giornaliere

### Multi-utente e Sincronizzazione
- **Accesso concorrente** da più PC nella stessa rete locale
- **Sincronizzazione automatica** ogni 8 secondi
- **Contatore utenti connessi** in tempo reale
- **Gestione disconnessioni** con schermata di blocco

### Sicurezza e Affidabilità
- **Server unico** in rete tramite lock file
- **Backup automatico** (20 snapshot giornalieri)
- **Logging avanzato** con rotazione a 7 giorni
- **Firewall automatico** per accesso da altri PC

## 🚀 Installazione

### Prerequisiti
- Windows 10/11
- Python embedded incluso nel pacchetto con:
  - `pystray` per l'icona nella system tray
  - `Pillow` per la gestione delle immagini

### Avvio rapido
1. Scarica il pacchetto completo
2. Esegui `configura_firewall.bat` **una sola volta** come amministratore
3. Avvia l'applicazione con `avvia.bat`

### Per gli utenti
- Esegui `avvia.bat` per aprire l'applicazione nel browser
- Il server si avvia automaticamente se non è già attivo

### Per lo sviluppo
```bash
# Avvio server Python
python server.py

# Oppure con PowerShell
.\avvia.ps1
```

## 🛠️ Tecnologie

### Backend
- **Python 3** — Server HTTP integrato
- **JSON** — Persistenza dati locale
- **PowerShell/Batch** — Script di avvio e configurazione

### Frontend
- **HTML5 / CSS3** — Struttura e stile, senza build step
- **JavaScript ES Modules (nativi)** — Logica modulare, importata direttamente dal browser
- **Tema chiaro/scuro** — Adattabile alle preferenze dell'utente

> **Nota tecnica:** il frontend usa `<script type="module">`, supportato da tutti i browser moderni (Chrome, Firefox, Edge, Safari). Non è necessario alcun bundler (Vite, Webpack, ecc.) né Node.js sul server.

## 📁 Struttura del progetto

```
gestione_consegne/
├── server.py               # Server HTTP e logica backend (invariato)
├── index.html              # Shell HTML: struttura, modali, nav
│
├── css/
│   ├── theme.css           # Variabili CSS, palette squadre, temi chiaro/scuro
│   ├── layout.css          # Reset, header, sidebar, struttura app
│   └── components.css      # Bottoni, pill, badge, tabella, card, modal, form, toast
│
├── js/
│   ├── main.js             # Entry point: init, polling, espone globali per onclick HTML
│   ├── store.js            # Stato globale condiviso (db, currentView, flags, setter)
│   ├── api.js              # Layer HTTP: fetchData, postData, ping, remoteLog
│   ├── sync.js             # loadData, saveData, markDirty, ping, overlay disconnessione
│   ├── render.js           # renderAll, switchView, renderLista, renderSidebar, renderGiornata
│   ├── utils.js            # uid, fmtDate, statoPill, tipoBadge, sqBadgeHtml, toast, openModal
│   ├── theme.js            # initTheme, applyTheme, toggleTheme
│   ├── dragdrop.js         # Drag & drop ordinamento card giornata
│   ├── giornate.js         # removeFromGiornata, segnaConsegnata, deleteGiornata, modal nuova giornata
│   ├── modal-consegna.js   # Modal creazione/modifica consegna, gestione articoli
│   ├── modal-select.js     # Modal selezione consegne da aggiungere a giornata
│   ├── squadre.js          # CRUD squadre: add, rename, color, delete
│   └── stampa.js           # Stampa PDF giornata
│
├── avvia.bat / avvia.ps1   # Script di avvio (invariati)
├── configura_firewall.bat  # Configurazione rete (invariato)
├── dati.json               # Dati principali (generato dal server)
├── backup/                 # Snapshot automatici
├── python_embed/           # Python embedded (opzionale)
└── README.md
```

### Grafo delle dipendenze JS (semplificato)

```
main.js
  ├── store.js          (no deps)
  ├── api.js → store
  ├── sync.js → api
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

Nessuna dipendenza circolare. `main.js` importa tutto e registra le funzioni su `window` per gli handler `onclick` inline nell'HTML.

## ⚙️ Configurazione

### Porta di rete
Il server utilizza la porta **8742** per le comunicazioni HTTP.

### Firewall
Esegui `configura_firewall.bat` una sola volta per abilitare l'accesso da altri PC.

## 👥 Gestione Squadre

Il sistema supporta fino a 8 squadre con colori assegnabili:

| Indice | Colore default |
|--------|----------------|
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

| Stato | Significato | Visibile nel popup "Aggiungi a giornata"? |
|-------|-------------|-------------------------------------------|
| `in_attesa` | Non ancora assegnata | ✅ Sì |
| `da_riprogrammare` | Era assegnata, da rifare | ✅ Sì |
| `da_confermare` | Assegnata, in attesa conferma cliente | ❌ No (già in giornata) |
| `programmata` | Confermata | ❌ No |
| `completata` | Consegnata | ❌ No |
| `annullata` | Cancellata | ❌ No |

### Temi
- **Chiaro/Scuro automatico** basato sul sistema operativo
- **Cambio manuale** con bottone nell'header

## 🛡️ Sicurezza

### Server Lock
- Solo un'istanza server attiva nella rete
- Controllo tramite file `server.lock`

### Dati
- Scrittura atomica per evitare corruzioni
- Backup automatico a ogni modifica
- Rotazione log settimanale

## 🔧 Linee guida per il team

### Aggiungere una nuova funzionalità
1. Se tocca solo la UI di una vista → modifica il file `render.js` o crea un nuovo file in `js/`
2. Se aggiunge un nuovo tipo di dato → aggiorna `store.js` con il setter
3. Se aggiunge una chiamata HTTP → aggiungila in `api.js`
4. Se la funzione deve essere chiamabile da un `onclick` nell'HTML → registrala su `window` in `main.js`

### Aggiungere un nuovo modal
1. Aggiungi l'HTML del modal in `index.html`
2. Crea un file `js/modal-nomefeature.js`
3. Importa e registra le funzioni in `main.js`

### Modificare il CSS
- Nuove variabili di colore/tema → `css/theme.css`
- Struttura/layout globale → `css/layout.css`
- Componenti UI (bottoni, card, form) → `css/components.css`

### Caricare questa codebase in una nuova sessione AI
Per una **modifica puntuale** a una feature esistente, carica:
- Il file JS della feature interessata (es. `js/modal-select.js`)
- `js/store.js` (stato globale)
- `js/utils.js` (se usi helper)

Per una **modifica strutturale o nuova feature**, carica:
- `README.md` (architettura)
- I file JS coinvolti
- `index.html` (solo se tocchi la struttura HTML)

Non è mai necessario caricare tutto insieme grazie alla separazione modulare.

## 📞 Supporto

In caso di problemi:
1. Verifica che Python sia installato
2. Controlla le impostazioni firewall
3. Riavvia l'applicazione con `avvia.bat`

## 📄 Licenza

Software proprietario per uso interno. Non redistribuibile.
