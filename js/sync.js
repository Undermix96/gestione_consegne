/**
 * sync.js — Caricamento/salvataggio dati, ping, gestione disconnessione
 */

import { fetchData, postData, pingServer as apiPing, remoteLog } from './api.js';
import {
  db, setDb, isDirty, setIsDirty,
  serverOnline, setServerOnline,
  pingFailCount, setPingFailCount,
  PING_FAIL_THRESHOLD,
} from './store.js';

let saveTimer = null;

// ── Sync UI ──────────────────────────────────────

export function setSaving() {
  document.getElementById('syncDot').className = 'sync-dot saving';
  document.getElementById('syncLabel').textContent = 'salvataggio…';
}
export function syncOk() {
  document.getElementById('syncDot').className = 'sync-dot';
  document.getElementById('syncLabel').textContent = 'connesso';
}
export function syncError() {
  document.getElementById('syncDot').className = 'sync-dot error';
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

// ── Data load / save ─────────────────────────────

export async function loadData() {
  try {
    const data = await fetchData();
    setDb(data);
    if (!db.consegne) db.consegne = [];
    if (!db.giornate) db.giornate = [];
    if (!db.squadre)  db.squadre  = [];
    if (db._connectedClients !== undefined) {
      document.getElementById('clientsCount').textContent = db._connectedClients;
    }
    syncOk();
    return true;
  } catch {
    syncError();
    return false;
  }
}

export async function saveData() {
  if (!serverOnline) return;
  setSaving();
  try {
    await postData(db);
    setIsDirty(false);
    syncOk();
  } catch {
    syncError();
  }
}

export function markDirty() {
  setIsDirty(true);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveData, 600);
}

// ── Ping ─────────────────────────────────────────

export async function ping() {
  try {
    const data = await apiPing();
    setPingFailCount(0);
    if (!serverOnline) {
      setServerOnline(true);
      hideDisconnectOverlay();
    }
    if (data.clients !== undefined) {
      document.getElementById('clientsCount').textContent = data.clients;
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
