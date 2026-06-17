# Gestione Consegne

Sistema completo per la gestione di consegne e installazioni, progettato per team di lavoro in ambiente locale (LAN). Permette di pianificare le attività, assegnarle a squadre e monitorare lo stato delle consegne, con un sistema di autenticazione multi-ruolo.

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

### Autenticazione e Gestione Utenti
- **Tre livelli di ruolo**: Superadmin, Admin, Standard
- **Login sicuro** con Challenge-Response (SHA-256 puro, compatibile HTTP)
- **Sessioni con scadenza** per inattività (2 ore)
- **Log degli accessi** con IP e timestamp

## 👥 Ruoli e permessi

| Azione | Standard | Admin | Superadmin |
|---|---|---|---|
| Operatività consegne/giornate | ✅ | ✅ | ❌ |
| Creare/gestire squadre | ❌ | ✅ | ❌ |
| Creare utenti standard | ❌ | ✅ | ✅ |
| Eliminare utenti standard | ❌ | ✅ | ✅ |
| Creare utenti admin | ❌ | ✅ | ✅ |
| Eliminare/declassare admin | ❌ | ❌ | ✅ |
| Toccare il superadmin | ❌ | ❌ | ❌ |

**Il superadmin** è un account puramente amministrativo: non ha accesso ai dati operativi (consegne, giornate). Vede solo il pannello di gestione utenti.

## 🔐 Sicurezza in rete locale (HTTP)

Il sistema usa **Challenge-Response con SHA-256** per proteggere le credenziali su reti HTTP non cifrate:

1. Il client richiede un **challenge** monouso al server (TTL 60s)
2. Calcola `response = SHA-256(SHA-256(password) + challenge)` in JS puro (no `crypto.subtle`, compatibile con IP LAN)
3. Il server verifica senza mai ricevere la password in chiaro
4. **Replay attack impossibile**: il challenge è monouso e scade in 60 secondi
5. Le password sono memorizzate come `sha256(password)` — non invertibile, non è la password in chiaro

### Primo accesso
- Username: `superadmin` — Password: `admin`
- Il cambio password è **obbligatorio** al primo login

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
- Effettua il login con le credenziali ricevute dall'amministratore

### Per lo sviluppo
```bash
python server.py
```

## 🛠️ Tecnologie

### Backend
- **Python 3** — Server HTTP integrato (`http.server` stdlib)
- **hashlib.sha256** — Hash password (h1) e verifica challenge-response (built-in)
- **secrets** — Generazione token e challenge crittograficamente sicuri
- **JSON** — Persistenza dati (`dati.json`) e utenti (`utenti.json`)

### Frontend
- **HTML5 / CSS3** — Struttura e stile, senza build step
- **JavaScript ES Modules (nativi)** — Logica modulare, importata direttamente dal browser
- **SHA-256 in JS puro** (`js/sha256.js`) — Per il challenge-response senza dipendenze
- **sessionStorage** — Token di sessione (auto-cancellato alla chiusura del browser)
- **Tema chiaro/scuro** — Adattabile alle preferenze dell'utente

> **Nota tecnica:** il frontend usa `<script type="module">`, supportato da tutti i browser moderni. Non è necessario alcun bundler né Node.js.

## 📁 Struttura del progetto

```
gestione_consegne/
├── server.py               # Server HTTP, auth, sessioni, utenti, log
├── index.html              # Shell HTML: struttura, overlay login, modali
│
├── css/
│   ├── theme.css           # Variabili CSS, palette, temi chiaro/scuro
│   ├── layout.css          # Reset, header, sidebar, struttura app
│   └── components.css      # Bottoni, badge, form, modal, overlay login/auth
│
├── js/
│   ├── main.js             # Entry point: check auth, init app, espone globali
│   ├── store.js            # Stato globale (db, currentUser, flags, setter)
│   ├── api.js              # Layer HTTP con auth header + intercept 401
│   ├── auth.js             # Login, logout, cambio password, token, overlay
│   ├── sha256.js           # SHA-256 puro (per challenge-response su HTTP)
│   ├── sync.js             # loadData, saveData, markDirty, ping, disconnect
│   ├── render.js           # renderAll, switchView, renderLista, renderGiornata
│   ├── utils.js            # uid, fmtDate, statoPill, toast, openModal
│   ├── theme.js            # initTheme, applyTheme, toggleTheme
│   ├── dragdrop.js         # Drag & drop ordinamento card giornata
│   ├── giornate.js         # CRUD giornate e assegnazione consegne
│   ├── modal-consegna.js   # Modal creazione/modifica consegna
│   ├── modal-select.js     # Modal selezione consegne → giornata
│   ├── modal-utenti.js     # Pannello gestione utenti (admin/superadmin)
│   ├── squadre.js          # CRUD squadre
│   └── stampa.js           # Stampa PDF giornata
│
├── dati.json               # Dati operativi (generato dal server)
├── utenti.json             # Utenti e hash password (generato al primo avvio)
├── backup/                 # Snapshot automatici (max 20)
├── gestionale.log          # Log con rotazione 7 giorni
├── avvia.bat / avvia.ps1   # Script di avvio
├── configura_firewall.bat  # Configurazione rete
└── python_embed/           # Python embedded (opzionale)
```

### Grafo delle dipendenze JS

```
main.js
  ├── store.js          (no deps)
  ├── sha256.js         (no deps)
  ├── auth.js → sha256, store
  ├── api.js → store, auth
  ├── sync.js → api, store
  ├── utils.js → store
  ├── theme.js          (no deps)
  ├── render.js → sync, utils, store, dragdrop
  │     └── dragdrop.js → store, sync
  ├── giornate.js → store, sync, render, utils
  ├── modal-consegna.js → store, sync, render, utils
  ├── modal-select.js → store, sync, render, utils
  ├── modal-utenti.js → store, auth, utils, sha256
  ├── squadre.js → store, sync, render, utils
  └── stampa.js → store, utils
```

## ⚙️ Configurazione

### Porta di rete
Il server usa la porta **8742**.

### Firewall
Esegui `configura_firewall.bat` una sola volta per abilitare l'accesso da altri PC.

## 📊 Log e Audit

Il file `gestionale.log` registra tutte le operazioni con utente e IP:

```
2026-06-16 10:00:00 [INFO]  [AUTH]   superadmin ha effettuato il login da 192.168.1.15
2026-06-16 10:05:00 [INFO]  [UTENTI] admin mario.rossi creato da superadmin
2026-06-16 10:11:00 [INFO]  [DATI]   mario.rossi — aggiunta nuova consegna: Rossi Mario
2026-06-16 10:30:00 [WARN]  [AUTH]   login fallito per utente 'pippo' da 192.168.1.33
```

Categorie: `[AUTH]`, `[UTENTI]`, `[DATI]`. Rotazione automatica ogni 7 giorni.

## 👥 Gestione Squadre

Il sistema supporta fino a 8 squadre con colori assegnabili (solo Admin e Superadmin):

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

## 🔧 Linee guida per il team di sviluppo

### Aggiungere una nuova feature
1. Logica UI → nuovo file `js/modal-*.js` o aggiorna `render.js`
2. Nuovo dato → aggiorna setter in `store.js`
3. Nuova chiamata HTTP → aggiungila in `api.js`
4. Funzione callable da `onclick` HTML → registrala su `window` in `main.js`
5. Nuovo endpoint → aggiungilo in `server.py` con verifica token e ruolo

### Aggiungere un nuovo modal
1. HTML in `index.html`
2. Logica in `js/modal-nomefeature.js`
3. Import + registrazione su `window` in `main.js`

### Modificare il CSS
- Nuove variabili → `css/theme.css`
- Layout → `css/layout.css`
- Componenti → `css/components.css`

### Caricare questa codebase in una nuova sessione AI
Per una **modifica puntuale**: carica il file JS interessato + `store.js` + `utils.js`.
Per una **modifica strutturale**: carica `README.md` + i file JS coinvolti + `index.html` se tocchi l'HTML.
Per modifiche all'**autenticazione**: carica `server.py` + `js/auth.js` + `js/sha256.js`.

## 📄 Licenza

Software proprietario per uso interno. Non redistribuibile.
