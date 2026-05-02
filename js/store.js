/**
 * store.js — Stato globale dell'applicazione
 *
 * Esporta le variabili di stato condivise tra tutti i moduli.
 * Modificare sempre tramite le funzioni esportate, mai direttamente.
 */

export const API = `http://${window.location.hostname}:8742/api`;

export let db = { consegne: [], giornate: [], squadre: [] };
export let currentView      = 'lista';
export let currentGiornataId = null;
export let editingConsegnaId = null;
export let expandedRowId     = null;
export let isDirty           = false;
export let serverOnline      = true;
export let pingFailCount     = 0;

export const PING_FAIL_THRESHOLD = 2;
export const SQ_COLORS = 8;

// ── Setters ─────────────────────────────────────

export function setDb(val)                 { db = val; }
export function setCurrentView(val)        { currentView = val; }
export function setCurrentGiornataId(val)  { currentGiornataId = val; }
export function setEditingConsegnaId(val)  { editingConsegnaId = val; }
export function setExpandedRowId(val)      { expandedRowId = val; }
export function setIsDirty(val)            { isDirty = val; }
export function setServerOnline(val)       { serverOnline = val; }
export function setPingFailCount(val)      { pingFailCount = val; }
