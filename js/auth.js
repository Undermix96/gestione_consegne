/**
 * auth.js — Autenticazione lato client
 *
 * Challenge-Response SHA-256, token in sessionStorage,
 * header X-Session-Token, overlay login/cambio password.
 */

import { sha256 } from './sha256.js';
import { API }    from './store.js';

const KEY_TOKEN        = 'gc_token';
const KEY_USERNAME     = 'gc_username';
const KEY_USER_ID      = 'gc_user_id';
const KEY_NEGOZIO_ID   = 'gc_negozio_id';
const KEY_PERMESSI     = 'gc_permessi';
const KEY_SUPERADMIN   = 'gc_superadmin';

// ── Getters ──────────────────────────────────────

export function getToken()       { return sessionStorage.getItem(KEY_TOKEN); }
export function getUsername()    { return sessionStorage.getItem(KEY_USERNAME); }
export function getUserId()      { return sessionStorage.getItem(KEY_USER_ID); }
export function getNegozioId()   { return sessionStorage.getItem(KEY_NEGOZIO_ID); }
export function getPermessi()    { return JSON.parse(sessionStorage.getItem(KEY_PERMESSI) || '[]'); }
export function isSuperadmin()   { return sessionStorage.getItem(KEY_SUPERADMIN) === 'true'; }
export function isLoggedIn()     { return !!getToken(); }

export function getAuthHeaders() {
  const token = getToken();
  return token ? { 'X-Session-Token': token } : {};
}

function saveSession(data) {
  sessionStorage.setItem(KEY_TOKEN,      data.token);
  sessionStorage.setItem(KEY_USERNAME,   data.username);
  sessionStorage.setItem(KEY_USER_ID,    data.user_id);
  sessionStorage.setItem(KEY_NEGOZIO_ID, data.negozio_id ?? '');
  sessionStorage.setItem(KEY_PERMESSI,   JSON.stringify(data.permessi ?? []));
  sessionStorage.setItem(KEY_SUPERADMIN, String(!!data.is_superadmin));
}

function clearSession() {
  [KEY_TOKEN, KEY_USERNAME, KEY_USER_ID, KEY_NEGOZIO_ID, KEY_PERMESSI, KEY_SUPERADMIN]
    .forEach(k => sessionStorage.removeItem(k));
}

// ── Challenge-Response ───────────────────────────

async function getChallenge() {
  const r = await fetch(`${API}/auth/challenge`, { cache: 'no-store' });
  if (!r.ok) throw new Error('Impossibile ottenere challenge dal server');
  const { challenge } = await r.json();
  return challenge;
}

function buildResponse(password, challenge) {
  const h1 = sha256(password);
  return { h1, response: sha256(h1 + challenge) };
}

// ── Login ────────────────────────────────────────

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
    if (!r.ok) return { ok: false, error: data.error || 'Credenziali non valide' };

    saveSession(data);
    return { ok: true, must_change_password: !!data.must_change_password };

  } catch {
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

// ── Cambio password proprio account ──────────────

export async function changePassword(passwordVecchia, passwordNuova) {
  try {
    const challenge    = await getChallenge();
    const { response } = buildResponse(passwordVecchia, challenge);
    const nuova_hash   = sha256(passwordNuova);

    const r = await fetch(`${API}/auth/change-password`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body:    JSON.stringify({ challenge, response, nuova_hash }),
    });

    const data = await r.json();
    if (!r.ok) return { ok: false, error: data.error || 'Errore cambio password' };
    clearSession();
    return { ok: true };
  } catch {
    return { ok: false, error: 'Server non raggiungibile' };
  }
}

// ── Intercettazione 401 ──────────────────────────

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

// ── Overlay cambio password ───────────────────────

export function showChangePasswordOverlay(msg = '') {
  const overlay = document.getElementById('changePasswordOverlay');
  overlay.classList.add('show');
  document.getElementById('cpError').textContent = msg;
  document.getElementById('cpVecchia').value     = '';
  document.getElementById('cpNuova').value       = '';
  document.getElementById('cpConferma').value    = '';
  document.getElementById('cpVecchia').focus();
}

export function hideChangePasswordOverlay() {
  document.getElementById('changePasswordOverlay').classList.remove('show');
}

// ── Init auth UI ─────────────────────────────────

export function initAuthUI() {
  // Form login
  document.getElementById('loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    const errEl    = document.getElementById('loginError');
    const btnEl    = document.getElementById('loginBtn');

    if (!username || !password) { errEl.textContent = 'Inserisci username e password'; return; }

    btnEl.disabled    = true;
    btnEl.textContent = 'Accesso in corso…';
    errEl.textContent = '';

    const result = await login(username, password);

    btnEl.disabled    = false;
    btnEl.textContent = 'Accedi';

    if (!result.ok) { errEl.textContent = result.error; return; }

    hideLoginOverlay();
    if (result.must_change_password) {
      showChangePasswordOverlay('Devi cambiare la password prima di continuare.');
      return;
    }
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

    if (!vecchia || !nuova || !conferma) { errEl.textContent = 'Compila tutti i campi'; return; }
    if (nuova !== conferma)              { errEl.textContent = 'Le due password non coincidono'; return; }
    if (nuova.length < 8)               { errEl.textContent = 'La password deve essere di almeno 8 caratteri'; return; }

    btnEl.disabled    = true;
    btnEl.textContent = 'Salvataggio…';
    errEl.textContent = '';

    const result = await changePassword(vecchia, nuova);

    btnEl.disabled    = false;
    btnEl.textContent = 'Cambia password';

    if (!result.ok) { errEl.textContent = result.error; return; }

    hideChangePasswordOverlay();
    showLoginOverlay();
    const loginErr = document.getElementById('loginError');
    loginErr.textContent = '✅ Password cambiata. Accedi con la nuova password.';
    loginErr.style.color = 'var(--done)';
  });
}
