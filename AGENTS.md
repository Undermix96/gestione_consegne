# AGENTS.md — Gestione Consegne

Documento di contesto per agenti AI. Descrive lo stato attuale del progetto, l'architettura, le decisioni prese e le convenzioni adottate.

---

## 1. Descrizione del progetto

**Gestione Consegne** è un gestionale web locale per organizzare le consegne di prodotti di elettronica effettuate da squadre. È utilizzato da un'azienda su LAN wireless + cablata con dispositivi personali dei dipendenti connessi — rete non completamente trusted.

### Utenti
- 4+ operatori che accedono da PC diversi sulla stessa LAN
- Uso sporadico: 5-10 minuti alla volta, alcune volte al giorno
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

## 2. Sistema di autenticazione

### Tre ruoli

| Ruolo | Operatività consegne/giornate | Squadre | Gestione utenti |
|---|---|---|---|
| **standard** | ✅ | ❌ | ❌ |
| **admin** | ✅ | ✅ | Solo utenti standard + crea admin |
| **superadmin** | ❌ | ❌ | Tutto (tranne toccare se stesso) |

Il **superadmin** è un account puramente amministrativo. Non ha accesso a `/api/data`. Vede solo il pannello di gestione utenti come vista esclusiva.

### Challenge-Response (SHA-256)

Lo schema protegge le password su HTTP puro, dove `crypto.subtle` non è disponibile (bloccata dai browser su IP non-localhost):

```
1. GET  /api/auth/challenge  →  { challenge: "a3f9..." }  (hex 32 byte, monouso, TTL 60s)
2. Client: h1 = sha256(password), response = sha256(h1 + challenge)
3. POST /api/auth/login  →  { username, challenge, response }
4. Server: expected = sha256(stored_h1 + challenge)  ← stored_h1 = sha256(password)
           confronta con secrets.compare_digest
```

- La password in chiaro non lascia mai il browser
- Il challenge è monouso: rimosso immediatamente dopo il consumo
- Replay attack impossibile: il challenge scade in 60 secondi
- Sul server le password sono memorizzate come `h1 = sha256(password)` — non invertibile, non è la password in chiaro

**File chiave:**
- `js/sha256.js` — implementazione SHA-256 pura (~80 righe), no dipendenze, stabile
- `js/auth.js` — login, logout, cambio password, token, overlay
- `server.py` — funzioni `sha256_hex`, `store_password`, `verify_password`, `new_challenge`, `consume_challenge`

### Sessioni in memoria

```python
sessions = {
    "token_abc": {
        "user_id": "u_abc",
        "username": "mario.rossi",
        "ruolo": "admin",
        "last_seen": 1718528400.0,
        "expires": 1718535600.0,   # last_seen + 7200s
        "must_change_password": False
    }
}
```

- Token: `secrets.token_urlsafe(32)` inviato come header `X-Session-Token`
- Scadenza: 2 ore di inattività — ogni richiesta aggiorna `last_seen` e `expires`
- Cleanup: thread ogni 5 minuti rimuove sessioni scadute
- Al riavvio del server: sessioni perse → login obbligatorio per tutti
- Lato client: token in `sessionStorage` (auto-cancellato alla chiusura del browser)

### Primo avvio

Se `utenti.json` non esiste, il server lo crea con un superadmin di default:
- Username: `superadmin` / Password: `admin`
- `primo_login: true` → il server restituisce `must_change_password: true`
- Il frontend blocca qualsiasi azione finché la password non viene cambiata

---

## 3. Struttura dei file

```
gestione_consegne/
├── server.py               ← Server HTTP, auth, sessioni, utenti, log
├── index.html              ← Shell HTML: struttura, overlay login/cambio-pwd, modali
│
├── css/
│   ├── theme.css           ← Variabili CSS, palette squadre, temi chiaro/scuro
│   ├── layout.css          ← Reset, header, sidebar, struttura app
│   └── components.css      ← Bottoni, badge, form, modal, overlay auth, pannello utenti
│
├── js/
│   ├── main.js             ← Entry point: check auth, init app per ruolo, espone globali
│   ├── store.js            ← Stato globale: db, currentUser, flags, setter
│   ├── sha256.js           ← SHA-256 puro (challenge-response su HTTP)
│   ├── auth.js             ← login(), logout(), changePassword(), getAuthHeaders()
│   ├── api.js              ← fetch con X-Session-Token + intercept 401
│   ├── sync.js             ← loadData, saveData, markDirty, ping, overlay disconnessione
│   ├── render.js           ← renderAll, switchView, renderLista, renderGiornata
│   ├── utils.js            ← uid, fmtDate, statoPill, toast, openModal
│   ├── theme.js            ← initTheme, applyTheme, toggleTheme
│   ├── dragdrop.js         ← Drag & drop card giornata
│   ├── giornate.js         ← CRUD giornate e assegnazione consegne
│   ├── modal-consegna.js   ← Modal creazione/modifica consegna
│   ├── modal-select.js     ← Modal selezione consegne → giornata
│   ├── modal-utenti.js     ← Pannello gestione utenti (admin/superadmin)
│   ├── squadre.js          ← CRUD squadre
│   └── stampa.js           ← Stampa PDF giornata
│
├── dati.json               ← Dati operativi (generato dal server)
├── utenti.json             ← Utenti e hash password (generato al primo avvio)
├── server.lock             ← Presenza server (creato/rimosso automaticamente)
├── gestionale.log          ← Log con rotazione 7 giorni
├── backup/                 ← Snapshot automatici (max 20)
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

Nessuna dipendenza circolare.

---

## 5. Endpoint HTTP (completo)

| Metodo | Path | Auth | Ruoli | Descrizione |
|--------|------|------|-------|-------------|
| GET | `/api/auth/challenge` | No | — | Genera challenge monouso |
| POST | `/api/auth/login` | No | — | Login → token |
| POST | `/api/auth/logout` | Token | tutti | Invalida sessione |
| POST | `/api/auth/change-password` | Token | tutti | Cambia propria password |
| GET | `/api/ping` | Opzionale | — | Heartbeat + contatore client |
| GET | `/api/data` | Token | standard, admin | Legge dati operativi |
| POST | `/api/data` | Token | standard, admin | Scrive dati operativi |
| POST | `/api/log` | Token | tutti | Log client → file log |
| GET | `/api/utenti` | Token | admin, superadmin | Lista utenti |
| POST | `/api/utenti` | Token | admin, superadmin | Crea utente |
| DELETE | `/api/utenti/:id` | Token | regole ruolo | Elimina utente |
| PUT | `/api/utenti/:id/password` | Token | regole ruolo | Cambia password utente |
| PUT | `/api/utenti/:id/ruolo` | Token | superadmin | Declassa admin → standard |

Il superadmin riceve 403 su `GET/POST /api/data`.

---

## 6. `utenti.json` — struttura

```json
{
  "utenti": [
    {
      "id": "u_abc123",
      "username": "mario.rossi",
      "password_hash": "hex64chars (sha256 di sha256(password))",
      "ruolo": "standard | admin | superadmin",
      "primo_login": false,
      "creato_da": "u_xyz",
      "creato_il": "2026-06-16T10:00:00",
      "ultimo_accesso": "2026-06-16T14:30:00"
    }
  ]
}
```

Struttura semplice, nessun salt separato. `password_hash` contiene `sha256(password)` (h1). Scrittura atomica (`.tmp` → rename), stesso pattern di `dati.json`.

---

## 7. Log — formato e categorie

```
2026-06-16 10:00:00 [INFO]  [AUTH]   superadmin ha effettuato il login da 192.168.1.15
2026-06-16 10:01:00 [INFO]  [AUTH]   superadmin ha cambiato la propria password
2026-06-16 10:05:00 [INFO]  [UTENTI] admin mario.rossi creato da superadmin
2026-06-16 10:10:00 [INFO]  [AUTH]   mario.rossi ha effettuato il login da 192.168.1.22
2026-06-16 10:11:00 [INFO]  [DATI]   mario.rossi — aggiunta nuova consegna: Rossi Mario
2026-06-16 10:30:00 [WARN]  [AUTH]   login fallito per utente 'pippo' da 192.168.1.33
2026-06-16 11:00:00 [INFO]  [UTENTI] luca.bianchi (standard) eliminato da mario.rossi
```

Categorie: `[AUTH]`, `[UTENTI]`, `[DATI]`. Il log `[DATI]` è generato dal client via `POST /api/log` con username già incluso nel messaggio.

---

## 8. Flusso avvio frontend (con auth)

```
DOMContentLoaded
  → initTheme()
  → initAuthUI()         ← collega i form login/cambio-pwd ai loro handler
  → isLoggedIn()?
      NO  → showLoginOverlay()  [fine, aspetta submit]
      SÌ  → _initApp()

_initApp()
  → setCurrentUser({ id, username, ruolo })
  → ruolo === 'superadmin'?
      SÌ  → nasconde app-body e nav-tabs
           → mostra #superadminPanel
           → renderPannelloUtenti()
      NO  → _applicaPermessiUI(ruolo)
           → loadData() → renderAll()
           → avvia polling e ping
```

---

## 9. `store.js` — stato globale

```javascript
export let db = { consegne: [], giornate: [], squadre: [] };
export let currentView       = 'lista';
export let currentGiornataId = null;
export let editingConsegnaId = null;
export let expandedRowId     = null;
export let isDirty           = false;
export let serverOnline      = true;
export let pingFailCount     = 0;
export let currentUser = { id: null, username: null, ruolo: null };
```

`currentUser` viene popolato in `main.js` dopo il login da `sessionStorage`.

---

## 10. Struttura dati operativi (`dati.json`)

```json
{
  "consegne": [{
    "id": "abc123",
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
    "id": "def456", "data": "2024-03-25",
    "squadra": "Squadra A", "consegneIds": ["abc123"]
  }],
  "squadre": [{ "id": "sq001", "nome": "Squadra A", "colorIdx": 0 }]
}
```

⚠️ `tipoConsegna` NON esiste come campo di primo livello — è esclusivamente per-articolo.

---

## 11. Regole lato server (hardcoded, non aggirabili dal frontend)

- Superadmin non eliminabile, non declassabile, non modificabile da nessuno (tranne propria password)
- Non può esistere più di un superadmin
- Un admin non può toccare un altro admin
- L'ultimo admin non può essere eliminato
- Il superadmin riceve 403 su qualsiasi accesso a `/api/data`
- Ogni endpoint verifica ruolo lato server indipendentemente dal frontend

---

## 12. Decisioni progettuali già prese (non riaprire)

| Decisione | Motivazione |
|-----------|-------------|
| Challenge-Response SHA-256 invece di HTTPS | `crypto.subtle` non disponibile su IP LAN via HTTP; nessuna libreria installabile |
| `sha256(password)` come password_hash | Schema coerente con challenge-response: il server può verificare `sha256(h1 + challenge)` senza KDF separato; h1 non è invertibile |
| Salt KDF globale in `utenti.json` | Semplifica il modello challenge-response; il salt è comunque segreto e non in chiaro sulla rete |
| `sessionStorage` invece di `localStorage` | Auto-cancellato alla chiusura del browser → sessioni più sicure |
| Superadmin senza operatività | Separazione netta dei ruoli; l'admin di sistema non deve toccare i dati aziendali |
| JSON come database utenti (non SQLite) | SQLite su NFS/SMB è inaffidabile; stesso pattern già usato per `dati.json` |
| Server unico con `server.lock` | Multi-server su SMB causa corruzione dati |
| Scrittura atomica (tmp + rename) | Protezione da corruzione a metà scrittura |
| 2 tentativi poi crash | Preferibile perdere l'ultima modifica che corrompere i dati |
| Cognome Nome (non Nome Cognome) | Richiesta esplicita del cliente — definitivo |
| `articoli[]` invece di 3 campi singoli | Supporto a più prodotti per consegna — retrocompatibile |

---

## 13. Note per modifiche future

- **Non usare `crypto.subtle`** — non disponibile su `http://IP:8742` da browser moderni
- **Non aggiungere dipendenze npm/pip** — i client non hanno internet, il Python embedded non può aggiornarsi
- **Non cambiare la struttura di `dati.json`** senza garantire retrocompatibilità — usare `|| []` / `|| ''` per nuovi campi
- **Non cambiare `utenti.json`** senza aggiornare `init_users()`, `find_user_by_*`, e tutti gli endpoint utenti
- **La porta 8742 non deve cambiare** — configurata nel firewall di ogni PC server
- **Non ripristinare `f_tipoProdotto` / `f_codiceProdotto` / `f_tipoConsegna` nel DOM** — non esistono più
- **`expandedRowId`** viene resettato a `null` se la riga viene eliminata
- L'ordine **Cognome Nome** è intenzionale e definitivo
- Il campo `password_hash` in `utenti.json` contiene `sha256(password)` — se si cambia schema di hashing bisogna resettare tutte le password

---

## 14. Istruzioni operative per l'agente AI

Questa sezione definisce il comportamento atteso dell'agente in ogni sessione di lavoro su questo progetto. Seguire queste istruzioni in ordine di priorità, senza eccezioni.

### 14.1 Pianifica prima di agire — autorizzazione obbligatoria

**Non modificare mai file senza autorizzazione esplicita dell'utente.**

Prima di qualsiasi modifica:
1. Analizza la richiesta e identifica tutti i file coinvolti
2. Esponi il piano in modo chiaro: cosa cambia, dove, perché
3. Se la modifica tocca più file, elenca ognuno con una riga di descrizione
4. Attendi conferma esplicita ("ok", "vai", "procedi" o simile) prima di scrivere qualsiasi file
5. Se la conferma non arriva o è ambigua, chiedi di nuovo — non interpretare il silenzio come consenso

Questo vale anche per modifiche apparentemente banali o "ovvie". L'utente ha sempre l'ultima parola.

### 14.2 Preferisci modifiche chirurgiche al refactoring

**Modifica il meno possibile per ottenere il risultato richiesto.**

- Usa `str_replace` per cambiare porzioni specifiche di file invece di riscrivere l'intero file
- Se una funzione va corretta, correggi quella funzione — non riscrivere il modulo
- Riscrivi un file intero solo se: (a) la struttura è irrecuperabile, oppure (b) la modifica richiesta tocca più del 60% del contenuto
- Quando riscrivi un file intero, segnalalo esplicitamente all'utente e spiega perché era necessario

Riscrivere grandi porzioni di codice funzionante introduce regressioni invisibili. Il codice che non viene toccato non si rompe.

### 14.3 Revisione obbligatoria dopo ogni modifica

**Dopo aver applicato ogni modifica, rileggila prima di consegnarla.**

Processo di revisione:
1. Rileggi ogni blocco modificato nel contesto del file completo
2. Cerca attivamente almeno un errore — di sintassi, logica, o coerenza con il resto del codice
3. Verifica che i nomi di funzioni, variabili e endpoint siano coerenti tra tutti i file toccati
4. Controlla che le importazioni siano corrette e complete
5. Se trovi un errore, correggilo prima di consegnare — mai lasciare errori noti all'utente

Se dopo la revisione non trovi errori, dillo esplicitamente: "ho riletto e non ho trovato problemi". Non omettere questo passaggio.

### 14.4 Non inventare — chiedi o cerca

**In caso di dubbio su qualsiasi fatto tecnico, comportamento di una libreria, o dettaglio implementativo:**

- **Non inventare** una risposta plausibile e presentarla come certa
- **Chiedi all'utente** se il dubbio riguarda una scelta progettuale o un requisito ("preferisci X o Y?")
- **Cerca online** se il dubbio riguarda un fatto tecnico verificabile (API, comportamento di Python/browser, standard di protocollo)
- Quando citi una fonte o un comportamento tecnico, distingui chiaramente tra "so con certezza" e "ho trovato online" e "suppongo"

Questo progetto gira su hardware reale in produzione. Un'assunzione sbagliata può rompere qualcosa per utenti reali.

### 14.5 Gestione dei dubbi progettuali

Prima di procedere, chiedi chiarimenti se:
- La richiesta è ambigua su *dove* o *come* implementare qualcosa
- La modifica richiesta potrebbe confliggere con una decisione già presa (vedi sezione 12)
- La feature richiesta ha più di un'implementazione ragionevole con trade-off diversi
- Non è chiaro se la modifica deve toccare solo il frontend, solo il backend, o entrambi

Formula le domande in modo specifico e binario quando possibile ("vuoi X o Y?") invece di domande aperte che costringono l'utente a ri-progettare da zero.

### 14.6 File critici — attenzione massima

Questi file richiedono cautela extra perché un errore può rendere il sistema inutilizzabile:

| File | Rischio |
|---|---|
| `server.py` | Un errore di sintassi blocca il server per tutti gli utenti |
| `utenti.json` (struttura) | Un'incompatibilità invalida tutti gli account |
| `js/auth.js` + `js/sha256.js` | Un errore blocca il login per tutti |
| `dati.json` (struttura) | Un'incompatibilità corrode i dati operativi |
| `avvia.bat` / `avvia.ps1` | Un errore impedisce l'avvio del server |

Per questi file: pianifica con più dettaglio, preferisci modifiche minime, e rileggi due volte dopo la modifica.

### 14.7 Aggiorna la documentazione insieme al codice

Ogni volta che una modifica cambia:
- Un endpoint API → aggiorna la tabella endpoint in questa sezione 5
- Una struttura dati → aggiorna le sezioni 6 o 10
- Una funzione chiave → aggiorna il grafo delle dipendenze (sezione 4) se necessario
- Una decisione progettuale → aggiorna la sezione 12
- Qualcosa che "non fare" → aggiorna la sezione 13

README.md e AGENTS.md devono sempre rispecchiare lo stato reale del codice. Documentazione obsoleta è peggio di nessuna documentazione.

### 14.8 Commit message

Alla fine di ogni sessione di modifiche, genera un commit message seguendo questo formato:

```
tipo(ambito): descrizione breve in italiano (max 72 caratteri)

- dettaglio 1
- dettaglio 2
- dettaglio N (solo se rilevante)
```

Tipi ammessi: `feat`, `fix`, `refactor`, `docs`, `style`, `chore`.
Esempio di ambito: `auth`, `server`, `ui`, `dati`, `utenti`.
