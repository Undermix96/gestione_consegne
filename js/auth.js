/**
 * auth.js — Gestione autenticazione lato client
 *
 * Responsabilità:
 * - Flusso login con Challenge-Response (SHA-256 puro, no crypto.subtle)
 * - Gestione token in sessionStorage
 * - Header X-Session-Token per tutte le richieste API
 * - Intercettazione 401 → overlay login
 * - Cambio password (proprio account o forzato al primo login)
 */

import { sha256 }  from './sha256.js';
import { API }     from './store.js';

// ── Chiavi sessionStorage ────────────────────────
const KEY_TOKEN    = 'gc_token';
const KEY_RUOLO    = 'gc_ruolo';
const KEY_USERNAME = 'gc_username';
const KEY_USER_ID  = 'gc_user_id';

// ── Getters sessionStorage ───────────────────────

export function getToken()    { return sessionStorage.getItem(KEY_TOKEN); }
export function getRuolo()    { return sessionStorage.getItem(KEY_RUOLO); }
export function getUsername() { return sessionStorage.getItem(KEY_USERNAME); }
export function getUserId()   { return sessionStorage.getItem(KEY_USER_ID); }

export function isLoggedIn()  { return !!getToken(); }

export function getAuthHeaders() {
  const token = getToken();
  return token ? { 'X-Session-Token': token } : {};
}

function saveSession({ token, ruolo, username, user_id }) {
  sessionStorage.setItem(KEY_TOKEN,    token);
  sessionStorage.setItem(KEY_RUOLO,    ruolo);
  sessionStorage.setItem(KEY_USERNAME, username);
  sessionStorage.setItem(KEY_USER_ID,  user_id);
}

function clearSession() {
  sessionStorage.removeItem(KEY_TOKEN);
  sessionStorage.removeItem(KEY_RUOLO);
  sessionStorage.removeItem(KEY_USERNAME);
  sessionStorage.removeItem(KEY_USER_ID);
}

// ── Challenge-Response helpers ───────────────────

async function getChallenge() {
  const r = await fetch(`${API}/auth/challenge`, { cache: 'no-store' });
  if (!r.ok) throw new Error('Impossibile ottenere challenge dal server');
  const { challenge } = await r.json();
  return challenge;
}

/**
 * Costruisce la response per il challenge:
 *   h1       = sha256(password)
 *   response = sha256(h1 + challenge)
 */
function buildResponse(password, challenge) {
  const h1 = sha256(password);
  return { h1, response: sha256(h1 + challenge) };
}

// ── Login ────────────────────────────────────────

/**
 * Esegue il login completo.
 * @returns {{ ok: boolean, must_change_password: boolean, error?: string }}
 */
export async function login(username, password) {
  try {
    const challenge = await getChallenge();
    const { response } = buildResponse(password, challenge);

    const r = await fetch(`${API}/auth/login`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ username, challenge, response }),
    });

    const data = await r.json();

    if (!r.ok) {
      return { ok: false, error: data.error || 'Credenziali non valide' };
    }

    saveSession({
      token:    data.token,
      ruolo:    data.ruolo,
      username: data.username,
      user_id:  data.user_id,
    });

    return { ok: true, must_change_password: !!data.must_change_password };

  } catch (e) {
    return { ok: false, error: 'Server non raggiungibile' };
  }
}

// ── Logout ───────────────────────────────────────

export async function logout() {
  try {
    await fetch(`${API}/auth/logout`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    });
  } catch { /* non critico */ }
  clearSession();
}

// ── Cambio password ──────────────────────────────

/**
 * Cambia la propria password.
 * @returns {{ ok: boolean, error?: string }}
 */
export async function changePassword(passwordVecchia, passwordNuova) {
  try {
    const challenge = await getChallenge();
    const { response } = buildResponse(passwordVecchia, challenge);
    const nuova_hash   = sha256(passwordNuova);

    const r = await fetch(`${API}/auth/change-password`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body:    JSON.stringify({ challenge, response, nuova_hash }),
    });

    const data = await r.json();
    if (!r.ok) return { ok: false, error: data.error || 'Errore cambio password' };

    // Invalida sessione locale → forza nuovo login
    clearSession();
    return { ok: true };

  } catch {
    return { ok: false, error: 'Server non raggiungibile' };
  }
}

/**
 * Imposta la password di un altro utente (admin su standard, superadmin su admin).
 * Non richiede la vecchia password — azione privilegiata.
 * @returns {{ ok: boolean, error?: string }}
 */
export async function setPasswordUtente(userId, passwordNuova) {
  try {
    const nuova_hash = sha256(passwordNuova);
    const r = await fetch(`${API}/utenti/${userId}/password`, {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body:    JSON.stringify({ nuova_hash }),
    });
    const data = await r.json();
    if (!r.ok) return { ok: false, error: data.error || 'Errore cambio password' };
    return { ok: true };
  } catch {
    return { ok: false, error: 'Server non raggiungibile' };
  }
}

// ── Intercettazione 401 ──────────────────────────

/**
 * Da chiamare quando una risposta API restituisce 401.
 * Pulisce la sessione e mostra l'overlay di login.
 */
export function handleUnauthorized() {
  clearSession();
  showLoginOverlay();
}

// ── Overlay login ────────────────────────────────

export function showLoginOverlay() {
  document.getElementById('loginOverlay').classList.add('show');
  document.getElementById('loginError').textContent  = '';
  document.getElementById('loginUsername').value     = '';
  document.getElementById('loginPassword').value     = '';
  document.getElementById('loginUsername').focus();
}

export function hideLoginOverlay() {
  document.getElementById('loginOverlay').classList.remove('show');
}

// ── Overlay cambio password obbligatorio ─────────

export function showChangePasswordOverlay(msg = '') {
  const overlay = document.getElementById('changePasswordOverlay');
  overlay.classList.add('show');
  document.getElementById('cpError').textContent  = msg;
  document.getElementById('cpVecchia').value      = '';
  document.getElementById('cpNuova').value        = '';
  document.getElementById('cpConferma').value     = '';
  document.getElementById('cpVecchia').focus();
}

export function hideChangePasswordOverlay() {
  document.getElementById('changePasswordOverlay').classList.remove('show');
}

// ── Init auth UI ─────────────────────────────────

/**
 * Collega i form di login e cambio password ai loro handler.
 * Da chiamare una sola volta in DOMContentLoaded.
 */
export function initAuthUI() {
  // Form login
  document.getElementById('loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const errEl    = document.getElementById('loginError');
    const btnEl    = document.getElementById('loginBtn');

    if (!username || !password) {
      errEl.textContent = 'Inserisci username e password';
      return;
    }

    btnEl.disabled     = true;
    btnEl.textContent  = 'Accesso in corso…';
    errEl.textContent  = '';

    const result = await login(username, password);

    btnEl.disabled    = false;
    btnEl.textContent = 'Accedi';

    if (!result.ok) {
      errEl.textContent = result.error;
      return;
    }

    hideLoginOverlay();

    if (result.must_change_password) {
      showChangePasswordOverlay('Devi cambiare la password prima di continuare.');
      return;
    }

    // Avvia l'app
    window._initApp();
  });

  // Form cambio password
  document.getElementById('changePasswordForm').addEventListener('submit', async e => {
    e.preventDefault();
    const vecchia  = document.getElementById('cpVecchia').value;
    const nuova    = document.getElementById('cpNuova').value;
    const conferma = document.getElementById('cpConferma').value;
    const errEl    = document.getElementById('cpError');
    const btnEl    = document.getElementById('cpBtn');

    if (!vecchia || !nuova || !conferma) {
      errEl.textContent = 'Compila tutti i campi';
      return;
    }
    if (nuova !== conferma) {
      errEl.textContent = 'Le due password non coincidono';
      return;
    }
    if (nuova.length < 8) {
      errEl.textContent = 'La password deve essere di almeno 8 caratteri';
      return;
    }

    btnEl.disabled    = true;
    btnEl.textContent = 'Salvataggio…';
    errEl.textContent = '';

    const result = await changePassword(vecchia, nuova);

    btnEl.disabled    = false;
    btnEl.textContent = 'Cambia password';

    if (!result.ok) {
      errEl.textContent = result.error;
      return;
    }

    // Sessione invalidata → torna al login
    hideChangePasswordOverlay();
    showLoginOverlay();
    document.getElementById('loginError').textContent = '✅ Password cambiata. Accedi con la nuova password.';
    document.getElementById('loginError').style.color = 'var(--done)';
  });
}
