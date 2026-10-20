/**
 * sync.js — Ping, caricamento e polling a timestamp, gestione errori e disconnessione
 */

import { pingServer, fetchStato, fetchConsegne, fetchGiornate, fetchSquadre } from './api.js';
import {
  db, setDb,
  serverOnline, setServerOnline,
  pingFailCount, setPingFailCount,
  localTimestamps, setLocalTimestamps,
  PING_FAIL_THRESHOLD,
} from './store.js';
import { hasPermesso } from './permessi.js';
import { toast } from './utils.js';

// Categorie di dati, il permesso che ne consente la lettura e la funzione che le scarica.
// Il server risponde 403 se manca il permesso: si scarica solo ciò che l'utente può leggere.
const CATEGORIE = [
  { key: 'consegne', permesso: 'consegne.leggi', fetch: fetchConsegne },
  { key: 'giornate', permesso: 'giornate.leggi', fetch: fetchGiornate },
  { key: 'squadre',  permesso: 'squadre.leggi',  fetch: fetchSquadre },
];

function leggibili() {
  return CATEGORIE.filter(c => hasPermesso(c.permesso));
}

// ── Sync UI ──────────────────────────────────────

export function setSaving() {
  document.getElementById('syncDot').className   = 'sync-dot saving';
  document.getElementById('syncLabel').textContent = 'salvataggio…';
}
export function syncOk() {
  document.getElementById('syncDot').className   = 'sync-dot';
  document.getElementById('syncLabel').textContent = 'connesso';
}
export function syncError() {
  document.getElementById('syncDot').className   = 'sync-dot error';
  document.getElementById('syncLabel').textContent = 'errore server';
}

function showClients(n) {
  const el = document.getElementById('clientsCount');
  if (el && n !== undefined) el.textContent = n;
}

// ── Disconnect overlay ───────────────────────────

export function showDisconnectOverlay() {
  document.getElementById('disconnectOverlay').classList.add('show');
  document.querySelectorAll('.modal-overlay.open').forEach(el => el.classList.remove('open'));
}
export function hideDisconnectOverlay() {
  document.getElementById('disconnectOverlay').classList.remove('show');
}

// ── Caricamento dati ─────────────────────────────

/**
 * Scarica le categorie leggibili dall'utente.
 * I timestamp si leggono PRIMA dei dati: se qualcosa cambia nel frattempo, il prossimo
 * polling vede un timestamp più recente e riscarica (nessuna modifica va persa).
 */
export async function loadData() {
  try {
    const stato = await fetchStato();
    const next = { consegne: [], giornate: [], squadre: [] };
    const risposte = await Promise.all(leggibili().map(c => c.fetch()));
    leggibili().forEach((c, i) => { next[c.key] = risposte[i][c.key] || []; });
    setDb(next);
    setLocalTimestamps({
      consegne: stato.consegne || 0,
      giornate: stato.giornate || 0,
      squadre:  stato.squadre  || 0,
    });
    syncOk();
    return true;
  } catch {
    syncError();
    return false;
  }
}

/** Ricarica tutto e ridisegna (dopo un conflitto o un errore che lascia dubbi sullo stato). */
export async function refreshData() {
  if (await loadData()) window._onPollUpdate?.();
}

// ── Errori delle operazioni di scrittura ─────────

/**
 * 409 = qualcun altro ha modificato lo stesso dato (o un vincolo lo impedisce): si mostra il
 * messaggio del server e si ricaricano i dati, così l'utente vede lo stato attuale.
 */
export function reportError(e) {
  syncError();
  if (e && e.status === 409) {
    toast(`⚠️ ${e.message}`, 5000);
    refreshData();
  } else {
    toast(`Errore: ${e && e.message ? e.message : e}`);
  }
}

// ── Applica risposta server allo store ───────────

/**
 * Ogni endpoint di scrittura risponde con le categorie del negozio che l'utente può leggere.
 * Le categorie assenti dalla risposta restano invariate.
 */
export function applyServerResponse(data) {
  if (!data) return;
  const newDb = { ...db };
  if (data.consegne !== undefined) newDb.consegne = data.consegne;
  if (data.giornate !== undefined) newDb.giornate  = data.giornate;
  if (data.squadre  !== undefined) newDb.squadre   = data.squadre;
  setDb(newDb);
  showClients(data._connectedClients);
}

// ── Polling basato su timestamp ──────────────────

export async function pollData() {
  if (!serverOnline) return;
  try {
    const stato = await fetchStato();
    let changed = false;
    // Accumula tutti i cambiamenti prima di fare un unico setDb: db è uno snapshot al
    // momento dell'import, usarlo dopo ogni await sovrascriverebbe i cambiamenti precedenti.
    const newDb = { ...db };
    const newTs = { ...localTimestamps };

    for (const c of leggibili()) {
      if (stato[c.key] > (localTimestamps[c.key] || 0)) {
        const r = await c.fetch();
        newDb[c.key] = r[c.key] || [];
        newTs[c.key] = stato[c.key];
        changed = true;
      }
    }

    if (changed) {
      setDb(newDb);
      setLocalTimestamps(newTs);
      window._onPollUpdate?.();
    }
  } catch {
    // Errore silenzioso nel polling — il ping gestisce il disconnect
  }
}

// ── Ping ─────────────────────────────────────────

export async function ping() {
  try {
    const data = await pingServer();
    setPingFailCount(0);
    if (!serverOnline) {
      setServerOnline(true);
      hideDisconnectOverlay();
    }
    showClients(data.clients);
    syncOk();
  } catch {
    setPingFailCount(pingFailCount + 1);
    if (pingFailCount >= PING_FAIL_THRESHOLD) {
      setServerOnline(false);
      showDisconnectOverlay();
    }
  }
}
