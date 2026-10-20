/**
 * clientid.js — Identificatore univoco di questa scheda/finestra browser
 *
 * Il server lo usa (header X-Client-ID) per contare correttamente gli utenti connessi anche
 * dietro NAT (es. Docker), dove più client reali condividono lo stesso IP sorgente.
 * sessionStorage: azzerato alla chiusura del tab (coerente con una "sessione").
 *
 * Nota: crypto.randomUUID() richiede un secure context (HTTPS o localhost) e NON è
 * disponibile quando l'app è servita via HTTP semplice su IP LAN, che è lo scenario normale
 * di questo progetto. Si usa quindi crypto.getRandomValues() (disponibile anche in contesti
 * non sicuri) per generare un ID hex casuale.
 *
 * Modulo senza dipendenze: lo importano sia api.js sia auth.js (evita un ciclo api → auth → api).
 */

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

/** Header da inviare su OGNI richiesta al server. */
export function clientHeaders() {
  return { 'X-Client-ID': CLIENT_ID };
}
