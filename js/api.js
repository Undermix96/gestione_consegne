/**
 * api.js — Comunicazione con il server Python
 *
 * Tutte le chiamate HTTP sono centralizzate qui.
 * Aggiunge automaticamente X-Session-Token ad ogni richiesta autenticata.
 * Intercetta i 401 e reindirizza al login.
 */

import { API } from './store.js';
import { getAuthHeaders, handleUnauthorized } from './auth.js';

async function _fetch(url, options = {}) {
  const r = await fetch(url, {
    ...options,
    headers: { ...getAuthHeaders(), ...(options.headers || {}) },
  });
  if (r.status === 401) {
    handleUnauthorized();
    throw new Error('Non autenticato');
  }
  return r;
}

export async function fetchData() {
  const r = await _fetch(`${API}/data`, { cache: 'no-store' });
  if (!r.ok) throw new Error('Risposta non OK dal server');
  return r.json();
}

export async function postData(payload) {
  const r = await _fetch(`${API}/data`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(payload),
  });
  if (!r.ok) throw new Error('Salvataggio fallito');
}

export async function pingServer() {
  const r = await _fetch(`${API}/ping`, { cache: 'no-store' });
  if (!r.ok) throw new Error('Ping fallito');
  return r.json();
}

export async function remoteLog(msg) {
  try {
    const username = sessionStorage.getItem('gc_username') ?? 'unknown';
    await _fetch(`${API}/log`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ msg: `${username} — ${msg}` }),
    });
  } catch { /* non critico */ }
}
