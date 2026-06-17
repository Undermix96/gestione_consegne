/**
 * modal-utenti.js — Gestione utenti (pannello admin/superadmin)
 *
 * Admin:       vede e gestisce utenti standard + crea admin
 * Superadmin:  vede e gestisce tutti (standard + admin), declassa admin
 *
 * Il superadmin non ha accesso ai dati operativi: questo pannello
 * è la sua unica vista dopo il login.
 */

import { API }                              from './store.js';
import { getAuthHeaders, getRuolo,
         getUsername, setPasswordUtente }   from './auth.js';
import { toast }                            from './utils.js';
import { sha256 }                           from './sha256.js';

// ── Fetch utenti ─────────────────────────────────

async function fetchUtenti() {
  const r = await fetch(`${API}/utenti`, {
    headers: { ...getAuthHeaders() },
    cache: 'no-store',
  });
  if (!r.ok) throw new Error('Impossibile caricare la lista utenti');
  return r.json(); // { utenti: [...] }
}

// ── Render pannello utenti ────────────────────────

export async function renderPannelloUtenti() {
  const container = document.getElementById('pannelloUtenti');
  if (!container) return;

  container.innerHTML = '<div style="padding:24px;color:var(--muted)">Caricamento…</div>';

  let data;
  try {
    data = await fetchUtenti();
  } catch (e) {
    container.innerHTML = `<div style="padding:24px;color:var(--cancel)">${e.message}</div>`;
    return;
  }

  const myRuolo    = getRuolo();
  const myUsername = getUsername();
  const utenti     = data.utenti || [];

  // Superadmin vede tutti; admin vede solo standard e admin (non superadmin)
  const visibili = myRuolo === 'superadmin'
    ? utenti.filter(u => u.ruolo !== 'superadmin')
    : utenti.filter(u => u.ruolo === 'standard' || u.ruolo === 'admin');

  const ruoloLabel = { standard: 'Standard', admin: 'Admin', superadmin: 'Super Admin' };
  const ruoloBadge = {
    standard:   'badge-standard',
    admin:      'badge-admin',
    superadmin: 'badge-superadmin',
  };

  const righe = visibili.map(u => {
    const isSelf    = u.username === myUsername;
    const isAdmin   = u.ruolo === 'admin';
    const canDelete = !isSelf && (myRuolo === 'superadmin' || u.ruolo === 'standard');
    const canPwd    = !isSelf && (myRuolo === 'superadmin' || u.ruolo === 'standard');
    const canDeclass = myRuolo === 'superadmin' && isAdmin;

    return `
    <tr>
      <td><strong>${u.username}</strong>${isSelf ? ' <span class="self-badge">tu</span>' : ''}</td>
      <td><span class="ruolo-badge ${ruoloBadge[u.ruolo]}">${ruoloLabel[u.ruolo]}</span></td>
      <td class="muted" style="font-family:'DM Mono',monospace;font-size:12px;">${u.ultimo_accesso ? fmtDatetime(u.ultimo_accesso) : '—'}</td>
      <td class="muted" style="font-family:'DM Mono',monospace;font-size:12px;">${u.creato_il ? fmtDatetime(u.creato_il) : '—'}</td>
      <td>
        <div style="display:flex;gap:6px;justify-content:flex-end;">
          ${canPwd    ? `<button class="btn btn-ghost btn-sm" onclick="openCambioPasswordUtente('${u.id}','${u.username}')">🔑 Password</button>` : ''}
          ${canDeclass ? `<button class="btn btn-ghost btn-sm" onclick="declassaAdmin('${u.id}','${u.username}')">⬇ Declassa</button>` : ''}
          ${canDelete  ? `<button class="btn btn-danger btn-sm" onclick="eliminaUtente('${u.id}','${u.username}')">🗑 Elimina</button>` : ''}
        </div>
      </td>
    </tr>`;
  }).join('');

  const vuoto = `<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--muted)">Nessun utente.</td></tr>`;

  container.innerHTML = `
    <div class="utenti-toolbar">
      <h3>Gestione utenti</h3>
      <div style="display:flex;gap:8px;">
        <button class="btn btn-primary" onclick="openNuovoUtente('standard')">+ Nuovo utente standard</button>
        <button class="btn btn-primary" onclick="openNuovoUtente('admin')">+ Nuovo admin</button>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Username</th><th>Ruolo</th><th>Ultimo accesso</th><th>Creato il</th><th></th>
        </tr></thead>
        <tbody>${visibili.length > 0 ? righe : vuoto}</tbody>
      </table>
    </div>
  `;
}

// ── Modal nuovo utente ────────────────────────────

export function openNuovoUtente(ruoloDefault = 'standard') {
  document.getElementById('nuovoUtenteRuolo').value    = ruoloDefault;
  document.getElementById('nuovoUtenteUsername').value = '';
  document.getElementById('nuovoUtentePassword').value = '';
  document.getElementById('nuovoUtenteError').textContent = '';
  document.getElementById('modalNuovoUtente').classList.add('open');
  document.getElementById('nuovoUtenteUsername').focus();
}

export async function salvaNuovoUtente() {
  const username = document.getElementById('nuovoUtenteUsername').value.trim();
  const password = document.getElementById('nuovoUtentePassword').value;
  const ruolo    = document.getElementById('nuovoUtenteRuolo').value;
  const errEl    = document.getElementById('nuovoUtenteError');

  if (!username) { errEl.textContent = 'Inserisci username'; return; }
  if (!password) { errEl.textContent = 'Inserisci password'; return; }
  if (password.length < 8) { errEl.textContent = 'Password minimo 8 caratteri'; return; }

  const password_hash = sha256(password);

  try {
    const r = await fetch(`${API}/utenti`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body:    JSON.stringify({ username, password_hash, ruolo }),
    });
    const data = await r.json();
    if (!r.ok) { errEl.textContent = data.error || 'Errore creazione utente'; return; }

    document.getElementById('modalNuovoUtente').classList.remove('open');
    toast(`Utente ${username} creato`);
    renderPannelloUtenti();
  } catch {
    errEl.textContent = 'Server non raggiungibile';
  }
}

// ── Cambio password utente ────────────────────────

let _pwdTargetId = null;

export function openCambioPasswordUtente(userId, username) {
  _pwdTargetId = userId;
  document.getElementById('cpuTitle').textContent    = `Cambia password: ${username}`;
  document.getElementById('cpuNuova').value          = '';
  document.getElementById('cpuConferma').value       = '';
  document.getElementById('cpuError').textContent   = '';
  document.getElementById('modalCambioPasswordUtente').classList.add('open');
  document.getElementById('cpuNuova').focus();
}

export async function salvaCambioPasswordUtente() {
  const nuova    = document.getElementById('cpuNuova').value;
  const conferma = document.getElementById('cpuConferma').value;
  const errEl    = document.getElementById('cpuError');

  if (!nuova)            { errEl.textContent = 'Inserisci la nuova password'; return; }
  if (nuova.length < 8)  { errEl.textContent = 'Password minimo 8 caratteri'; return; }
  if (nuova !== conferma){ errEl.textContent = 'Le password non coincidono'; return; }

  const result = await setPasswordUtente(_pwdTargetId, nuova);
  if (!result.ok) { errEl.textContent = result.error; return; }

  document.getElementById('modalCambioPasswordUtente').classList.remove('open');
  toast('Password aggiornata');
}

// ── Declassa admin → standard ─────────────────────

export async function declassaAdmin(userId, username) {
  if (!confirm(`Declassare "${username}" da Admin a Standard?\nL'utente perderà i permessi di gestione.`)) return;
  try {
    const r = await fetch(`${API}/utenti/${userId}/ruolo`, {
      method:  'PUT',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body:    JSON.stringify({ ruolo: 'standard' }),
    });
    const data = await r.json();
    if (!r.ok) { toast(`Errore: ${data.error}`); return; }
    toast(`${username} declassato a Standard`);
    renderPannelloUtenti();
  } catch {
    toast('Server non raggiungibile');
  }
}

// ── Elimina utente ────────────────────────────────

export async function eliminaUtente(userId, username) {
  if (!confirm(`Eliminare definitivamente l'utente "${username}"?\nL'operazione non è reversibile.`)) return;
  try {
    const r = await fetch(`${API}/utenti/${userId}`, {
      method:  'DELETE',
      headers: { ...getAuthHeaders() },
    });
    const data = await r.json();
    if (!r.ok) { toast(`Errore: ${data.error}`); return; }
    toast(`Utente ${username} eliminato`);
    renderPannelloUtenti();
  } catch {
    toast('Server non raggiungibile');
  }
}

// ── Helpers ──────────────────────────────────────

function fmtDatetime(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  if (isNaN(d)) return isoStr;
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getDate())}/${pad(d.getMonth()+1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
