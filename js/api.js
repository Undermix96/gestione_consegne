/**
 * api.js — Comunicazione con il server Python
 *
 * Tutte le chiamate HTTP sono centralizzate qui.
 * I moduli consumano queste funzioni, mai fetch() direttamente.
 */

import { API } from './store.js';

// Identificatore univoco di questa scheda/finestra browser, usato dal server
// per contare correttamente gli utenti connessi anche dietro NAT (es. Docker),
// dove più client reali condividono lo stesso IP sorgente.
// sessionStorage: azzerato alla chiusura del tab (coerente con una "sessione").
//
// Nota: crypto.randomUUID() richiede un secure context (HTTPS o localhost) e
// NON è disponibile quando l'app è servita via HTTP semplice su IP LAN, che è
// lo scenario normale di questo progetto. Usiamo quindi crypto.getRandomValues()
// (disponibile anche in contesti non sicuri) per generare un ID hex casuale.
function generateClientId() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

const CLIENT_ID = sessionStorage.getItem('clientId') || (() => {
  const id = generateClientId();
  sessionStorage.setItem('clientId', id);
  return id;
})();

export async function fetchData() {
  const r = await fetch(`${API}/data`, { cache: 'no-store', headers: { 'X-Client-ID': CLIENT_ID } });
  if (!r.ok) throw new Error('Risposta non OK dal server');
  return r.json();
}

export async function postData(payload) {
  const r = await fetch(`${API}/data`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Client-ID': CLIENT_ID },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error('Salvataggio fallito');
}

export async function pingServer() {
  const r = await fetch(`${API}/ping`, { cache: 'no-store', headers: { 'X-Client-ID': CLIENT_ID } });
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
