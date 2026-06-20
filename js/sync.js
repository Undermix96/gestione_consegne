/**
 * sync.js — Ping, polling basato su timestamp, gestione disconnessione
 */

import { pingServer, fetchStato, fetchConsegne, fetchGiornate, fetchSquadre } from './api.js';
import {
  db, setDb,
  serverOnline, setServerOnline,
  pingFailCount, setPingFailCount,
  localTimestamps, setLocalTimestamps,
  PING_FAIL_THRESHOLD,
} from './store.js';

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

// ── Disconnect overlay ───────────────────────────

export function showDisconnectOverlay() {
  document.getElementById('disconnectOverlay').classList.add('show');
  document.querySelectorAll('.modal-overlay.open').forEach(el => el.classList.remove('open'));
}
export function hideDisconnectOverlay() {
  document.getElementById('disconnectOverlay').classList.remove('show');
}

// ── Caricamento dati iniziale ────────────────────

export async function loadData() {
  try {
    const [rc, rg, rs] = await Promise.all([
      fetchConsegne(),
      fetchGiornate(),
      fetchSquadre(),
    ]);
    setDb({
      consegne: rc.consegne || [],
      giornate: rg.giornate || [],
      squadre:  rs.squadre  || [],
    });
    // Aggiorna clientsCount se presente
    if (rc._connectedClients !== undefined) {
      const el = document.getElementById('clientsCount');
      if (el) el.textContent = rc._connectedClients;
    }
    syncOk();
    return true;
  } catch {
    syncError();
    return false;
  }
}

// ── Applica risposta server allo store ───────────

/**
 * Ogni endpoint di scrittura risponde con il db aggiornato del negozio.
 * Questa funzione aggiorna lo store locale e fa un render selettivo.
 */
export function applyServerResponse(data) {
  if (!data) return;
  const newDb = { ...db };
  if (data.consegne !== undefined) newDb.consegne = data.consegne;
  if (data.giornate !== undefined) newDb.giornate  = data.giornate;
  if (data.squadre  !== undefined) newDb.squadre   = data.squadre;
  setDb(newDb);
  if (data._connectedClients !== undefined) {
    const el = document.getElementById('clientsCount');
    if (el) el.textContent = data._connectedClients;
  }
}

// ── Polling basato su timestamp ──────────────────

export async function pollData() {
  if (!serverOnline) return;
  try {
    const stato = await fetchStato();
    let changed = false;

    if (stato.consegne > (localTimestamps.consegne || 0)) {
      const r = await fetchConsegne();
      setDb({ ...db, consegne: r.consegne || [] });
      setLocalTimestamps({ ...localTimestamps, consegne: stato.consegne });
      changed = true;
    }
    if (stato.giornate > (localTimestamps.giornate || 0)) {
      const r = await fetchGiornate();
      setDb({ ...db, giornate: r.giornate || [] });
      setLocalTimestamps({ ...localTimestamps, giornate: stato.giornate });
      changed = true;
    }
    if (stato.squadre > (localTimestamps.squadre || 0)) {
      const r = await fetchSquadre();
      setDb({ ...db, squadre: r.squadre || [] });
      setLocalTimestamps({ ...localTimestamps, squadre: stato.squadre });
      changed = true;
    }

    if (changed) {
      // Notifica main.js di fare un render
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
    if (data.clients !== undefined) {
      const el = document.getElementById('clientsCount');
      if (el) el.textContent = data.clients;
    }
    syncOk();
  } catch {
    setPingFailCount(pingFailCount + 1);
    if (pingFailCount >= PING_FAIL_THRESHOLD) {
      setServerOnline(false);
      showDisconnectOverlay();
    }
  }
}
