/**
 * modal-utenti.js — Gestione utenti per account con permessi utenti.*
 *
 * Mostra la lista utenti del proprio negozio.
 * Permette: creare utenti, cambiare password, cambiare tipo account, eliminare.
 */

import { fetchUtenti, createUtente, setPasswordUtente, setTipoAccount, deleteUtente as apiDeleteUtente, fetchTipiAccount } from './api.js';
import { getUsername, getUserId } from './auth.js';
import { toast } from './utils.js';
import { sha256 } from './sha256.js';
import { hasPermesso } from './permessi.js';

let _containerId = 'pannelloUtenti';
let _tipi        = [];

// ── Render pannello ───────────────────────────────

export async function renderPannelloAdmin(containerId = _containerId) {
  _containerId = containerId;
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = '<div style="padding:24px;color:var(--muted)">Caricamento…</div>';

  try {
    const [dataUtenti, dataTipi] = await Promise.all([
      fetchUtenti(),
      hasPermesso('tipi_account.leggi') ? fetchTipiAccount() : Promise.resolve({ tipi_account: [] }),
    ]);
    _tipi = dataTipi.tipi_account || [];
    _renderUtentiTable(container, dataUtenti.utenti || []);
  } catch (e) {
    container.innerHTML = `<div style="padding:24px;color:var(--cancel)">${e.message}</div>`;
  }
}

function _renderUtentiTable(container, utenti) {
  const myUsername = getUsername();
  const myId       = getUserId();

  const canCrea    = hasPermesso('utenti.crea');
  const canModifica = hasPermesso('utenti.modifica');
  const canElimina = hasPermesso('utenti.elimina');

  const righe = utenti.map(u => {
    const isSelf  = u.id === myId;
    const tipo    = _tipi.find(t => t.id === u.tipo_account_id);
    const nomeT   = tipo ? tipo.nome : (u.tipo_account_id ? '(sconosciuto)' : '—');

    return `
    <tr>
      <td><strong>${u.username}</strong>${isSelf ? ' <span class="self-badge">tu</span>' : ''}</td>
      <td><span class="ruolo-badge badge-tipo">${nomeT}</span></td>
      <td class="muted" style="font-family:'DM Mono',monospace;font-size:12px;">${u.ultimo_accesso ? _fmtDatetime(u.ultimo_accesso) : '—'}</td>
      <td class="muted" style="font-family:'DM Mono',monospace;font-size:12px;">${u.creato_il ? _fmtDatetime(u.creato_il) : '—'}</td>
      <td>
        <div style="display:flex;gap:6px;justify-content:flex-end;">
          ${canModifica && !isSelf ? `<button class="btn btn-ghost btn-sm" onclick="openCambioPasswordUtente('${u.id}','${u.username}')">🔑 Password</button>` : ''}
          ${canModifica && !isSelf ? `<button class="btn btn-ghost btn-sm" onclick="openCambioTipoAccount('${u.id}','${u.username}')">🏷 Tipo</button>` : ''}
          ${canElimina  && !isSelf ? `<button class="btn btn-danger btn-sm" onclick="eliminaUtente('${u.id}','${u.username}')">🗑</button>` : ''}
        </div>
      </td>
    </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="utenti-toolbar">
      <h3>Gestione utenti</h3>
      ${canCrea ? `<button class="btn btn-primary" onclick="openNuovoUtente()">+ Nuovo utente</button>` : ''}
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Username</th><th>Tipo account</th><th>Ultimo accesso</th><th>Creato il</th><th></th>
        </tr></thead>
        <tbody>${utenti.length > 0 ? righe : '<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--muted)">Nessun utente.</td></tr>'}</tbody>
      </table>
    </div>
  `;
}

// ── Modal nuovo utente ────────────────────────────

export function openNuovoUtente() {
  const sel = document.getElementById('nuovoUtenteTipo');
  sel.innerHTML = _tipi.map(t => `<option value="${t.id}">${t.nome}</option>`).join('');
  document.getElementById('nuovoUtenteUsername').value    = '';
  document.getElementById('nuovoUtentePassword').value    = '';
  document.getElementById('nuovoUtenteError').textContent = '';
  document.getElementById('modalNuovoUtente').classList.add('open');
  document.getElementById('nuovoUtenteUsername').focus();
}

export async function salvaNuovoUtente() {
  const username        = document.getElementById('nuovoUtenteUsername').value.trim();
  const password        = document.getElementById('nuovoUtentePassword').value;
  const tipo_account_id = document.getElementById('nuovoUtenteTipo').value;
  const errEl           = document.getElementById('nuovoUtenteError');

  if (!username)          { errEl.textContent = 'Inserisci username'; return; }
  if (!password)          { errEl.textContent = 'Inserisci password'; return; }
  if (password.length < 8){ errEl.textContent = 'Password minimo 8 caratteri'; return; }
  if (!tipo_account_id)   { errEl.textContent = 'Seleziona un tipo account'; return; }

  try {
    await createUtente({ username, password_hash: sha256(password), tipo_account_id });
    document.getElementById('modalNuovoUtente').classList.remove('open');
    toast(`Utente ${username} creato`);
    renderPannelloAdmin(_containerId);
  } catch (e) {
    errEl.textContent = e.data?.error || e.message || 'Errore creazione utente';
  }
}

// ── Cambio password ───────────────────────────────

let _pwdTargetId = null;

export function openCambioPasswordUtente(userId, username) {
  _pwdTargetId = userId;
  document.getElementById('cpuTitle').textContent  = `Cambia password: ${username}`;
  document.getElementById('cpuNuova').value        = '';
  document.getElementById('cpuConferma').value     = '';
  document.getElementById('cpuError').textContent  = '';
  document.getElementById('modalCambioPasswordUtente').classList.add('open');
  document.getElementById('cpuNuova').focus();
}

export async function salvaCambioPasswordUtente() {
  const nuova    = document.getElementById('cpuNuova').value;
  const conferma = document.getElementById('cpuConferma').value;
  const errEl    = document.getElementById('cpuError');

  if (!nuova)             { errEl.textContent = 'Inserisci la nuova password'; return; }
  if (nuova.length < 8)   { errEl.textContent = 'Password minimo 8 caratteri'; return; }
  if (nuova !== conferma) { errEl.textContent = 'Le password non coincidono'; return; }

  try {
    await setPasswordUtente(_pwdTargetId, sha256(nuova));
    document.getElementById('modalCambioPasswordUtente').classList.remove('open');
    toast('Password aggiornata');
  } catch (e) {
    errEl.textContent = e.data?.error || e.message || 'Errore';
  }
}

// ── Cambio tipo account ───────────────────────────

let _tipoTargetId = null;

export function openCambioTipoAccount(userId, username) {
  _tipoTargetId = userId;
  const sel = document.getElementById('cambioTipoSelect');
  sel.innerHTML = _tipi.map(t => `<option value="${t.id}">${t.nome}</option>`).join('');
  document.getElementById('cambioTipoTitle').textContent = `Tipo account: ${username}`;
  document.getElementById('cambioTipoError').textContent = '';
  document.getElementById('modalCambioTipo').classList.add('open');
}

export async function salvaCambioTipoAccount() {
  const tipo_account_id = document.getElementById('cambioTipoSelect').value;
  const errEl           = document.getElementById('cambioTipoError');
  if (!tipo_account_id) { errEl.textContent = 'Seleziona un tipo'; return; }

  try {
    await setTipoAccount(_tipoTargetId, tipo_account_id);
    document.getElementById('modalCambioTipo').classList.remove('open');
    toast('Tipo account aggiornato');
    renderPannelloAdmin(_containerId);
  } catch (e) {
    errEl.textContent = e.data?.error || e.message || 'Errore';
  }
}

// ── Elimina utente ────────────────────────────────

export async function eliminaUtente(userId, username) {
  if (!confirm(`Eliminare definitivamente l'utente "${username}"?\nL'operazione non è reversibile.`)) return;
  try {
    await apiDeleteUtente(userId);
    toast(`Utente ${username} eliminato`);
    renderPannelloAdmin(_containerId);
  } catch (e) {
    toast(`Errore: ${e.data?.error || e.message}`);
  }
}

// ── Helpers ──────────────────────────────────────

function _fmtDatetime(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  if (isNaN(d)) return isoStr;
  const p = n => String(n).padStart(2, '0');
  return `${p(d.getDate())}/${p(d.getMonth()+1)}/${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}
