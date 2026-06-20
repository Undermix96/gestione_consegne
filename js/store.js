/**
 * store.js — Stato globale dell'applicazione
 */

export const API = `http://${window.location.hostname}:8742/api`;

export let db = { consegne: [], giornate: [], squadre: [] };
export let currentView       = 'lista';
export let currentGiornataId = null;
export let editingConsegnaId = null;
export let expandedRowId     = null;
export let serverOnline      = true;
export let pingFailCount     = 0;

// Timestamps locali per polling efficiente
export let localTimestamps = { consegne: 0, giornate: 0, squadre: 0 };

// Utente corrente (popolato dopo il login)
export let currentUser = {
  id:            null,
  username:      null,
  negozio_id:    null,
  permessi:      [],
  is_superadmin: false,
};

export const PING_FAIL_THRESHOLD = 1;  // 1 ping fallito → overlay immediato
export const SQ_COLORS = 8;

// ── Setters ─────────────────────────────────────

export function setDb(val)                  { db = val; }
export function setCurrentView(val)         { currentView = val; }
export function setCurrentGiornataId(val)   { currentGiornataId = val; }
export function setEditingConsegnaId(val)   { editingConsegnaId = val; }
export function setExpandedRowId(val)       { expandedRowId = val; }
export function setServerOnline(val)        { serverOnline = val; }
export function setPingFailCount(val)       { pingFailCount = val; }
export function setCurrentUser(val)         { currentUser = val; }
export function setLocalTimestamps(val)     { localTimestamps = val; }
