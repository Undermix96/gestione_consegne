/**
 * api.js — Comunicazione con il server Python
 *
 * Tutte le chiamate HTTP sono centralizzate qui.
 * I moduli consumano queste funzioni, mai fetch() direttamente.
 */

import { API } from './store.js';

export async function fetchData() {
  const r = await fetch(`${API}/data`, { cache: 'no-store' });
  if (!r.ok) throw new Error('Risposta non OK dal server');
  return r.json();
}

export async function postData(payload) {
  const r = await fetch(`${API}/data`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error('Salvataggio fallito');
}

export async function pingServer() {
  const r = await fetch(`${API}/ping`, { cache: 'no-store' });
  if (!r.ok) throw new Error('Ping fallito');
  return r.json();
}

export async function remoteLog(msg) {
  try {
    await fetch(`${API}/log`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ msg }),
    });
  } catch { /* non critico */ }
}
