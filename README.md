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

### Dipendenze Python
Il progetto utilizza Python embedded con le seguenti librerie:
- `pystray` - Per l'icona nella system tray
- `Pillow` - Per la generazione dell'icona dell'applicazione

L'installazione delle dipendenze è inclusa nel pacchetto.

## 🛠️ Tecnologie

### Backend
- **Python 3** - Server HTTP integrato
- **JSON** - Persistenza dati locale
- **PowerShell/Batch** - Script di avvio e configurazione

### Frontend
- **HTML5/CSS3** - Interfaccia responsive
- **JavaScript ES6** - Logica applicativa
- **Tema chiaro/scuro** - Adattabile alle preferenze

## 📁 Struttura del progetto

```
gestione_consegne/
├── server.py          # Server HTTP e logica backend
├── index.html         # Interfaccia utente principale
├── avvia.bat/ps1      # Script di avvio
├── configura_firewall.bat  # Configurazione rete
├── dati.json          # Dati principali (generato)
├── backup/            # Snapshot automatici
├── python_embed/      # Python embedded (opzionale)
└── README.md
```

## ⚙️ Configurazione

### Porta di rete
Il server utilizza la porta **8742** per le comunicazioni HTTP.

### Firewall
Esegui `configura_firewall.bat` una sola volta per abilitare l'accesso da altri PC.

## 👥 Gestione Squadre

Il sistema supporta fino a 8 squadre con colori distintivi:
- Squadra 0: Blu (#4f8aff)
- Squadra 1: Verde (#22c55e)
- Squadra 2: Arancione (#f59e0b)
- Squadra 3: Rosso (#ef4444)
- Squadra 4: Viola (#a855f7)
- Squadra 5: Azzurro (#06b6d4)
- Squadra 6: Arancio scuro (#f97316)
- Squadra 7: Rosa (#ec4899)

## 📱 Interfaccia Utente

### Viste principali
1. **Lista Consegne** - Visualizzazione tabellare completa
2. **Giornate** - Pianificazione per date con drag & drop
3. **Impostazioni** - Gestione squadre e configurazioni

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

## 📞 Supporto

In caso di problemi:
1. Verifica che Python sia installato
2. Controlla le impostazioni firewall
3. Riavvia l'applicazione con `avvia.bat`

## 📄 Licenza

Software proprietario per uso interno. Non redistribuibile.