# AGENTS.md — Gestione Consegne

Documento di contesto per agenti AI. Descrive in dettaglio lo stato attuale del progetto, l'architettura, le decisioni prese e le convenzioni adottate.

---

## 1. Descrizione del progetto

**Gestione Consegne** è un gestionale web locale per organizzare le consegne di prodotti di elettronica effettuate da squadre di consegna. È utilizzato da un'azienda con più squadre operative.

### Utenti
- 4+ operatori che accedono da PC diversi sulla stessa LAN
- Uso sporadico: 5-10 minuti alla volta, alcune volte al giorno
- Raramente due utenti lavorano contemporaneamente
- I PC vengono accesi e spenti in ordine casuale, nessuno è sempre attivo

### Vincoli fondamentali (NON modificare senza approvazione esplicita)
- **Nessuna installazione** di programmi, librerie o ambienti di runtime sui PC client
- **Nessun cloud**: dati privati, non possono uscire dalla rete locale
- **Nessun server centrale fisso**: qualsiasi PC può fare da server
- **Integrità dei dati assoluta**: il programma è usato per lavoro
- **Windows 11** come unico OS target
- **Python embedded** incluso nella cartella — nessuna dipendenza di sistema

---

## 2. Struttura dei file

```
cartella_gestionale/          ← cartella condivisa su rete Windows (SMB)
├── index.html                ← intera applicazione frontend (single file)
├── server.py                 ← server HTTP Python
├── avvia.bat                 ← launcher (doppio click per avviare)
├── avvia.ps1                 ← launcher PowerShell (chiamato dal bat)
├── configura_firewall.bat    ← one-shot, eseguire SOLO la prima volta sul PC server
├── dati.json                 ← database principale (JSON)
├── server.lock               ← file di presenza server (creato/rimosso automaticamente)
├── gestionale.log            ← log operazioni (rotazione 7 giorni)
├── python_embed/             ← Python 3.13 embeddable (portabile, no installazione)
│   ├── python.exe
│   ├── pythonw.exe
│   ├── python313.zip
│   ├── Lib/site-packages/    ← pystray + Pillow installati qui
│   └── ...
└── backup/                   ← snapshot automatici del dati.json
    ├── dati.2024-03-22_14-35-00.json
    └── ... (max 20 file, i più vecchi vengono eliminati)
```

---

## 3. Architettura

### Modello server unico con auto-discovery

Un solo server alla volta può essere attivo. Il meccanismo si basa su `server.lock`:

1. `avvia.bat` lancia `avvia.ps1`
2. `avvia.ps1` controlla se `server.lock` esiste nella cartella condivisa
3. Se esiste → legge l'IP dal lock → testa `http://{IP}:8742/api/ping`
   - Se risponde → apre il browser su `http://{IP}:8742/index.html` e termina
   - Se non risponde → lock stale, lo elimina, procede al punto 4
4. Se non esiste → cerca Python (priorità: `python_embed/python.exe` → PATH → MS Store → installazioni standard) → avvia `server.py` in background (invisibile, nessuna finestra nera) → attende max 10s che il server risponda → apre il browser

### Porta
`8742` — non standard, scelta per evitare conflitti. Il server ascolta su `0.0.0.0` (tutte le interfacce), quindi accetta connessioni da tutta la LAN.

### Firewall
La porta 8742 deve essere aperta in ingresso sul PC che fa da server. Si usa `configura_firewall.bat` (eseguito una volta sola con UAC). Il codice UAC è stato rimosso da `avvia.ps1` intenzionalmente — non deve richiedere UAC ad ogni avvio.

### Client (browser)
I client non usano `avvia.bat`. Aprono direttamente il browser su `http://{IP-server}:8742/index.html`. L'URL dell'API è dinamico: `http://${window.location.hostname}:8742/api` — si adatta automaticamente all'IP da cui è stata caricata la pagina.

---

## 4. Server Python (`server.py`)

### Costanti
```python
PORT = 8742
DATA_FILE   = BASE_DIR + "/dati.json"
LOCK_FILE   = BASE_DIR + "/server.lock"
BACKUP_DIR  = BASE_DIR + "/backup"
LOG_FILE    = BASE_DIR + "/gestionale.log"
MAX_BACKUPS = 20
LOG_DAYS    = 7
WRITE_RETRIES = 2
```

### Endpoint HTTP
| Metodo | Path | Descrizione |
|--------|------|-------------|
| GET | `/api/ping` | Health check. Risponde `{"ok": true, "clients": N}`. Registra il client. |
| GET | `/api/data` | Legge `dati.json` dal disco (mai da cache) e restituisce tutto il DB con `_connectedClients` aggiunto. |
| POST | `/api/data` | Riceve il DB completo, fa backup, scrive atomicamente su disco. |
| POST | `/api/log` | Riceve `{"msg": "..."}` dal client e lo scrive su `gestionale.log`. |
| GET | `/*` | File statici (serve `index.html` e altri file dalla cartella). |

### Scrittura atomica
Ogni salvataggio: scrive su `dati.json.tmp` → `os.replace()` → rinomina atomicamente. Questo garantisce che il file originale non venga mai corrotto a metà scrittura.

### Lettura fresca
Prima di ogni scrittura, il server rilegge sempre `dati.json` dal disco (non usa cache in memoria). Questo previene sovrascritture in caso di accesso contemporaneo da più sessioni browser.

### Retry e crash
Ogni operazione di lettura/scrittura viene tentata `WRITE_RETRIES = 2` volte. Se entrambi i tentativi falliscono (es. NAS offline, cartella condivisa smontata), `crash_server()` viene chiamato:
1. Scrive nel log
2. Rimuove `server.lock`
3. Mostra notifica tray
4. Mostra popup bloccante PowerShell sul PC server con il motivo del crash e istruzione di riavviare `avvia.bat`
5. `os._exit(1)` — termina immediatamente

### Contatore client connessi
Il server traccia i client tramite heartbeat (timestamp dell'ultimo ping). Un client è considerato "attivo" se ha fatto ping negli ultimi 15 secondi. Il contatore viene aggiornato ad ogni ping e incluso in ogni risposta `/api/data`.

### System tray
Usa `pystray` + `Pillow` (installati in `python_embed/Lib/site-packages/`). Icona blu con punto esclamativo bianco (64x64 RGBA, disegnata programmaticamente). Menu contestuale: "Apri gestionale" e "Ferma server". Se `pystray` non è disponibile, il server gira comunque senza icona tray (fallback silenzioso).

### Logging
File `gestionale.log`, rotazione automatica a 7 giorni (le righe più vecchie vengono eliminate all'avvio). Ogni salvataggio, ogni connessione client, ogni errore, ogni azione dell'utente (inviata dal browser via `/api/log`) viene registrata.

---

## 5. Frontend (`index.html`)

Single-page application in HTML/CSS/JS puro. Nessun framework, nessuna dipendenza esterna tranne Google Fonts (caricati dalla CDN, opzionali se offline).

### Font
- **DM Sans** — body, UI generale
- **DM Mono** — date, codici, contatori

### Sistema temi
Due temi: scuro (default) e chiaro. Gestito tramite `data-theme` attribute sull'elemento `<html>`.

```css
:root, [data-theme="dark"] { /* variabili tema scuro */ }
[data-theme="light"]       { /* variabili tema chiaro */ }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) { /* auto light */ } }
```

La preferenza manuale viene salvata in `localStorage` con chiave `gc_theme`. Al caricamento, `initTheme()` legge `localStorage` oppure rileva la preferenza OS. Il pulsante ☀️/🌙 nell'header chiama `toggleTheme()`.

### Variabili CSS principali (tema scuro)
```css
--bg: #0f1117          /* sfondo pagina */
--surface: #181c27     /* header, sidebar */
--surface2: #1e2333    /* card, righe espanse */
--border: #2a2f42
--text: #e4e8f5
--muted: #6b7394
--accent: #4f8aff      /* blu primario */
--accent2: #7c5cfc     /* viola secondario */
--wait: #f59e0b        /* arancio = in attesa */
--sched: #3b82f6       /* blu = programmata */
--done: #22c55e        /* verde = completata */
--cancel: #ef4444      /* rosso = annullata */
```

### Palette colori squadre (8 colori, indipendenti dal tema)
```css
--sq0: #4f8aff  /* blu */
--sq1: #22c55e  /* verde */
--sq2: #f59e0b  /* ambra */
--sq3: #ef4444  /* rosso */
--sq4: #a855f7  /* viola */
--sq5: #06b6d4  /* ciano */
--sq6: #f97316  /* arancio */
--sq7: #ec4899  /* rosa */
```
Ogni colore ha anche `--sqN-bg` per il background del badge. Le classi CSS `.sq-c0` ... `.sq-c7` applicano il colore corrispondente.

### Stato globale JS
```javascript
let db = { consegne: [], giornate: [], squadre: [] }; // tutto il database
let currentView = 'lista';          // vista attiva: 'lista' | 'giornate' | 'impostazioni'
let currentGiornataId = null;       // ID giornata selezionata nella sidebar
let editingConsegnaId = null;       // ID consegna in modifica nel modal
let saveTimer = null;               // timer debounce salvataggio (600ms)
let isDirty = false;                // modifiche non ancora salvate
let serverOnline = true;            // stato connessione server
let pingFailCount = 0;              // contatore ping falliti consecutivi
const PING_FAIL_THRESHOLD = 2;      // ping falliti prima di mostrare overlay
let expandedRowId = null;           // ID riga espansa nella lista (preservato ai re-render)
const SQ_COLORS = 8;                // numero colori disponibili per squadre
```

### Ciclo di vita dei dati
1. Al caricamento: `loadData()` → GET `/api/data` → popola `db` → `renderAll()`
2. Ogni 8 secondi: se `serverOnline && !isDirty` → `loadData()` (polling)
3. Ogni 2 secondi: `pingServer()` → GET `/api/ping` → se 2 fallimenti consecutivi → `showDisconnectOverlay()`
4. Ogni modifica utente: `markDirty()` → dopo 600ms debounce → `saveData()` → POST `/api/data`
5. Ogni `saveData()` aspetta conferma dal server. Se fallisce → `syncError()` (il ping rileverà eventuale disconnessione)

### Viste (tab)
| ID | Tab | Descrizione |
|----|-----|-------------|
| `viewLista` | 📋 Lista Consegne | Tabella principale con tutte le consegne |
| `viewGiornate` | 📅 Giornate | Vista giornata con sidebar, card drag&drop |
| `viewImpostazioni` | ⚙️ Impostazioni | Gestione squadre |

### Vista Lista
- Tabella con colonne: (expand), Stato, Prenotazione, Cliente, Città, Squadra, Tipo consegna, Prodotto, Preferenze periodo
- **Ordine nominativo: COGNOME Nome** (non Nome Cognome — questo è intenzionale e definitivo)
- Ordinata per data prenotazione decrescente (più recenti in cima)
- Filtri: ricerca per nome/cognome, stato, città
- Click su riga → espande dettaglio con tutti i campi (inclusi quelli non visibili in tabella)
- `expandedRowId` viene preservato ai re-render automatici (il polling non chiude la riga aperta)
- Colori bordo sinistro per stato: arancio=attesa, blu=programmata, verde=completata, rosso=annullata
- Badge squadra: classe `.sq-badge .sq-cN` dove N è `colorIdx` della squadra

### Vista Giornate
- Sidebar sinistra: lista giornate ordinate per data, con dot colorato (verde=passata, blu=futura), badge con numero consegne, badge squadra colorato
- Header giornata: data + badge squadra
- Card consegne: drag&drop per riordinare (HTML5 Drag API), pulsante ✕ per rimuovere dalla giornata (la consegna torna "in attesa"), pulsante ✏️ per modificare
- Pulsante "🖨️ Stampa PDF" appare nella view-bar quando una giornata è selezionata
- Pulsante "+ Aggiungi consegna" apre modal di selezione con lista filtrata dei clienti "in attesa"
- Pulsante "🗑 Elimina giornata" — le consegne tornano "in attesa"
- Più giornate con la stessa data sono permesse (squadre diverse)

### Vista Impostazioni
- Lista squadre con nome editabile (blur/Enter per salvare), dot colore, selettore colore (8 pallini), pulsante elimina
- Campo input + pulsante per aggiungere nuova squadra
- Rinominare una squadra aggiorna automaticamente tutte le giornate che la usano

### Stampa PDF
Funzione `stampaPDF()`:
- Apre una nuova finestra del browser con HTML generato al volo
- Layout A4, font Arial, nessuna dipendenza esterna
- Intestazione: "Giornata del GG/MM/AAAA — Nome Squadra" + conteggio consegne
- Una `.cons-block` per ogni consegna con: numero progressivo, Cognome Nome, tipo consegna, griglia di tutti i campi, checkbox "Consegnato / Non consegnato" in fondo
- `setTimeout(() => win.print(), 600)` — apre il dialogo di stampa automaticamente

### Modal consegna
Campi del form (tutti in `f_[nome]`):
- `f_dataPrenotazione` (date), `f_stato` (select), `f_nome`, `f_cognome`, `f_citta`, `f_indirizzo`
- `f_tel1`, `f_tel2`, `f_tipoConsegna` (select: consegna/installazione/incasso), `f_raee` (select: si/no)
- `f_tipoProdotto`, `f_codiceProdotto`, `f_descrizioneProdotto`, `f_piano`
- `f_noteAbitazione` (textarea, max 170 caratteri), `f_preferenzePeriodo` (textarea, max 90 caratteri)
- `f_giornoConsegna` (date), `f_fasciaOraria` (text), `f_note` (textarea, max 170 caratteri)

I tre textarea hanno contatori caratteri in tempo reale: gialli all'85% del limite, rossi al limite.

### Schermata bloccante disconnessione
`#disconnectOverlay` — `position: fixed; inset: 0; z-index: 99999`. Appare dopo 2 ping falliti consecutivi. Non può essere chiusa dall'utente. Messaggio: "Connessione al server persa — Il server non è raggiungibile — I dati salvati sono al sicuro. Attendi che il server venga riavviato oppure contatta il responsabile." Non contiene istruzioni su `avvia.bat` perché i client non usano il bat.

---

## 6. Struttura dati (`dati.json`)

```json
{
  "consegne": [
    {
      "id": "abc123",
      "dataPrenotazione": "2024-03-22",
      "stato": "attesa",
      "nome": "Mario",
      "cognome": "Rossi",
      "citta": "Vicenza",
      "indirizzo": "Via Roma 1",
      "tel1": "+39 333 1234567",
      "tel2": "",
      "tipoConsegna": "consegna",
      "raee": "no",
      "tipoProdotto": "Lavatrice",
      "codiceProdotto": "LG-WM001",
      "descrizioneProdotto": "Lavatrice LG 7kg bianca",
      "piano": "2",
      "noteAbitazione": "Scala stretta, no ascensore",
      "preferenzePeriodo": "Solo mattina",
      "giornoConsegna": "2024-03-25",
      "fasciaOraria": "9:00-12:00",
      "note": ""
    }
  ],
  "giornate": [
    {
      "id": "def456",
      "data": "2024-03-25",
      "squadra": "Squadra A",
      "consegneIds": ["abc123", "ghi789"]
    }
  ],
  "squadre": [
    {
      "id": "sq001",
      "nome": "Squadra A",
      "colorIdx": 0
    }
  ]
}
```

### Valori enum
- `stato`: `"attesa"` | `"programmata"` | `"completata"` | `"annullata"`
- `tipoConsegna`: `"consegna"` | `"installazione"` | `"incasso"`
- `raee`: `"si"` | `"no"`
- `colorIdx`: `0`..`7` (indice nella palette `--sqN`)

### Logica stati automatica
Al caricamento (`autoCompleteStati()`): se una consegna ha `stato === "programmata"` e `giornoConsegna` è nel passato → `stato` viene aggiornato a `"completata"` automaticamente e salvato.

### Campo `_connectedClients`
Aggiunto dal server solo nelle risposte HTTP, **mai scritto su disco**. Il client lo legge per aggiornare il contatore nell'header.

---

## 7. Flusso operativo tipico

### Aggiungere una consegna
1. Vista Lista → "Nuova consegna" → compila form → Salva
2. La consegna appare in lista con stato "In attesa"

### Programmare una consegna
1. Vista Giornate → seleziona o crea una giornata → "Aggiungi consegna"
2. La modal mostra solo le consegne con stato "attesa"
3. Seleziona → Aggiungi → la consegna diventa "programmata", `giornoConsegna` viene impostato alla data della giornata

### Rimuovere da una giornata
Click ✕ sulla card → la consegna torna "attesa", `giornoConsegna` e `fasciaOraria` vengono svuotati

### Riprogrammare una consegna fallita
La consegna è "completata" (giorno passato). Aprire il modal di modifica → cambiare stato a "attesa" manualmente → salvare → la consegna torna disponibile per essere assegnata a una nuova giornata.

---

## 8. Launcher (`avvia.bat` + `avvia.ps1`)

`avvia.bat` contiene solo:
```bat
@echo off
PowerShell -NoProfile -ExecutionPolicy Bypass -File "%~dp0avvia.ps1"
```

`avvia.ps1` gestisce tutto:
1. Cerca `server.lock` nella cartella dello script
2. Se trovato e server risponde → apre browser sull'IP del server esistente → exit
3. Se non trovato (o lock stale) → cerca Python (ordine: `python_embed/`, PATH, MS Store, installazioni standard) → avvia `server.py` nascosto → attende max 10s → apre browser su localhost

**Non chiede mai UAC** (il codice UAC/firewall è stato rimosso intenzionalmente).

---

## 9. Configurazione firewall (`configura_firewall.bat`)

Da eseguire **una sola volta sul PC server**. Richiede UAC. Aggiunge una regola in ingresso per TCP porta 8742. Può essere eliminato dopo l'uso.

---

## 10. Python embedded

Cartella `python_embed/` contiene Python 3.13 embeddable (Windows 64-bit).
- `python313._pth` modificato: riga `import site` decommentata (necessario per pip e librerie)
- Librerie installate: `pystray`, `Pillow` (in `Lib/site-packages/`)
- `pip` installato tramite `get-pip.py` (il file può essere eliminato dopo l'uso)

---

## 11. Decisioni progettuali già prese (non riaprire)

| Decisione | Motivazione |
|-----------|-------------|
| Server unico con `server.lock` | Multi-server su SMB causa corruzione dati |
| JSON come database | Leggibile, portabile, backup semplici. SQLite su SMB è inaffidabile |
| Scrittura atomica (tmp + rename) | Protezione da corruzione a metà scrittura |
| Lettura fresca prima di ogni scrittura | Previene sovrascritture con accesso quasi-contemporaneo |
| 2 tentativi poi crash | Preferibile perdere l'ultima modifica che avere dati corrotti |
| Ping HTTP (non ICMP) | ICMP bloccato dal firewall Windows di default |
| Python embedded nella cartella | Nessuna installazione sui PC, portabilità totale |
| `avvia.bat` → `avvia.ps1` | PowerShell vede correttamente le variabili utente (PATH MS Store) |
| No UAC in `avvia.ps1` | UAC gestito una tantum da `configura_firewall.bat` |
| Cognome Nome (non Nome Cognome) | Richiesta esplicita del cliente, non modificare |
| Stessa data permessa con squadre diverse | Richiesta esplicita per gestire più squadre parallele |
| Schermata bloccante senza istruzioni bat | I client non usano il bat, solo il browser diretto |
| Tema auto da OS + switch manuale | Usabilità su monitor diversi, salvato in localStorage |

---

## 12. Funzionalità in lista (non ancora implementate)

- **Esportazione PDF** della giornata (implementata con `stampaPDF()`) ✅
- **Esportazione CSV/Excel** — non richiesta
- Nessuna altra funzionalità pendente al momento della stesura di questo documento

---

## 13. Note per modifiche future

- **Non usare `innerHTML` con dati utente non sanitizzati** — attualmente i dati vengono inseriti direttamente. Se si aggiunge autenticazione o dati da fonti esterne, aggiungere sanitizzazione XSS.
- **Non aggiungere dipendenze NPM/pip** senza aggiornare anche `python_embed/` — i PC non hanno accesso a internet durante l'uso (o comunque non si deve assumere che ce l'abbiano).
- **Non cambiare la struttura di `dati.json`** senza garantire retrocompatibilità — i file esistenti devono continuare a funzionare. Usare valori di default con `|| []` / `|| ''` per i nuovi campi.
- **La porta 8742 non deve cambiare** — è configurata nel firewall di ogni PC server.
- **Il file `server.lock`** non deve mai rimanere orfano — `crash_server()` e il blocco `finally` in `main` lo rimuovono sempre. In caso di kill forzato del processo, il lock stale viene rilevato e rimosso al prossimo avvio da `avvia.ps1`.
- **`expandedRowId`** viene resettato a `null` se la riga viene eliminata — gestirlo in `deleteCurrentConsegna()` se necessario.
- L'ordine **Cognome Nome** è intenzionale e definitivo. Non invertire.
