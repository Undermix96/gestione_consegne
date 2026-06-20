/**
 * modal-admin.js — Pannello superadmin (Negozi, Tipi account, Utenti)
 *
 * Caricato dinamicamente solo per il superadmin.
 */

import {
  fetchNegozi, createNegozio, updateNegozio, deleteNegozio,
  fetchTipiAccount, createTipoAccount, updateTipoAccount, deleteTipoAccount,
  fetchUtenti, createUtente, setPasswordUtente, setTipoAccount, deleteUtente,
} from './api.js';
import { PERMESSI, DIPENDENZE, getPermessiPerGruppo, getMissingDeps } from './permessi.js';
import { toast } from './utils.js';
import { sha256 } from './sha256.js';

let _containerId = 'superadminPanel';
let _negozi      = [];
let _tipi        = [];
let _utenti      = [];
let _sezione     = 'negozi';

// ── Entry point ───────────────────────────────────

export async function renderPannelloSuperadmin(containerId = _containerId) {
  _containerId = containerId;
  const container = document.getElementById(containerId);
  if (!container) return;

  container.innerHTML = `
    <div class="admin-panel">
      <div class="admin-tabs">
        <button class="admin-tab active" data-tab="negozi"       onclick="_adminTab('negozi')">🏪 Negozi</button>
        <button class="admin-tab"         data-tab="tipi"         onclick="_adminTab('tipi')">🏷 Tipi account</button>
        <button class="admin-tab"         data-tab="utenti"       onclick="_adminTab('utenti')">👥 Utenti</button>
      </div>
      <div id="adminContent" class="admin-content"></div>
    </div>
  `;

  window._adminTab = _adminTab;
  await _adminTab('negozi');
}

async function _adminTab(tab) {
  _sezione = tab;
  document.querySelectorAll('.admin-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.tab === tab);
  });

  const content = document.getElementById('adminContent');
  content.innerHTML = '<div style="padding:24px;color:var(--muted)">Caricamento…</div>';

  try {
    if (tab === 'negozi') {
      const data = await fetchNegozi();
      _negozi    = data.negozi || [];
      _renderNegozi(content);
    } else if (tab === 'tipi') {
      const data = await fetchTipiAccount();
      _tipi      = data.tipi_account || [];
      _renderTipi(content);
    } else if (tab === 'utenti') {
      const [du, dn, dt] = await Promise.all([fetchUtenti(), fetchNegozi(), fetchTipiAccount()]);
      _utenti = du.utenti || [];
      _negozi = dn.negozi || [];
      _tipi   = dt.tipi_account || [];
      _renderUtentiAdmin(content);
    }
  } catch (e) {
    content.innerHTML = `<div style="padding:24px;color:var(--cancel)">Errore: ${e.message}</div>`;
  }
}

// ── NEGOZI ────────────────────────────────────────

function _renderNegozi(container) {
  const righe = _negozi.map(n => `
    <tr>
      <td><strong>${n.nome}</strong></td>
      <td class="muted" style="font-size:12px;font-family:'DM Mono',monospace">${n.id}</td>
      <td class="muted" style="font-size:12px;">${n.creato_il ? n.creato_il.slice(0,10) : '—'}</td>
      <td>
        <div style="display:flex;gap:6px;justify-content:flex-end;">
          <button class="btn btn-ghost btn-sm" onclick="_editNegozio('${n.id}','${n.nome.replace(/'/g,"\\'")}')">✏️ Rinomina</button>
          <button class="btn btn-danger btn-sm" onclick="_deleteNegozio('${n.id}','${n.nome.replace(/'/g,"\\'")}')">🗑</button>
        </div>
      </td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="admin-section-header">
      <h3>Negozi</h3>
      <button class="btn btn-primary" onclick="_newNegozio()">+ Nuovo negozio</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Nome</th><th>ID</th><th>Creato il</th><th></th></tr></thead>
        <tbody>${_negozi.length > 0 ? righe : '<tr><td colspan="4" style="text-align:center;padding:32px;color:var(--muted)">Nessun negozio.</td></tr>'}</tbody>
      </table>
    </div>
    <div id="negozioFormWrap" style="display:none;margin-top:16px;" class="inline-form">
      <input id="negozioFormInput" type="text" placeholder="Nome negozio" style="flex:1"/>
      <input type="hidden" id="negozioFormId"/>
      <button class="btn btn-primary" onclick="_saveNegozio()">Salva</button>
      <button class="btn btn-ghost" onclick="document.getElementById('negozioFormWrap').style.display='none'">Annulla</button>
    </div>
  `;

  window._newNegozio   = _newNegozio;
  window._editNegozio  = _editNegozio;
  window._deleteNegozio = _deleteNegozio;
  window._saveNegozio  = _saveNegozio;
}

function _newNegozio() {
  document.getElementById('negozioFormInput').value = '';
  document.getElementById('negozioFormId').value    = '';
  document.getElementById('negozioFormWrap').style.display = '';
  document.getElementById('negozioFormInput').focus();
}

function _editNegozio(id, nome) {
  document.getElementById('negozioFormInput').value = nome;
  document.getElementById('negozioFormId').value    = id;
  document.getElementById('negozioFormWrap').style.display = '';
  document.getElementById('negozioFormInput').focus();
}

async function _saveNegozio() {
  const nome = document.getElementById('negozioFormInput').value.trim();
  const id   = document.getElementById('negozioFormId').value;
  if (!nome) { toast('Inserisci un nome'); return; }

  try {
    if (id) {
      await updateNegozio(id, nome);
      toast('Negozio aggiornato');
    } else {
      await createNegozio(nome);
      toast('Negozio creato');
    }
    await _adminTab('negozi');
  } catch (e) {
    toast(`Errore: ${e.data?.error || e.message}`);
  }
}

async function _deleteNegozio(id, nome) {
  if (!confirm(`Eliminare il negozio "${nome}"?\nSolo se non ha utenti associati.`)) return;
  try {
    await deleteNegozio(id);
    toast('Negozio eliminato');
    await _adminTab('negozi');
  } catch (e) {
    toast(e.data?.error || e.message || 'Errore');
  }
}

// ── TIPI ACCOUNT ─────────────────────────────────

function _renderTipi(container) {
  const righe = _tipi.map(t => {
    const nPerm = t.permessi?.length || 0;
    return `
    <tr>
      <td><strong>${t.nome}</strong></td>
      <td class="muted">${nPerm} permess${nPerm === 1 ? 'o' : 'i'}</td>
      <td class="muted" style="font-size:12px;">${t.modificato_il ? t.modificato_il.slice(0,10) : '—'}</td>
      <td>
        <div style="display:flex;gap:6px;justify-content:flex-end;">
          <button class="btn btn-ghost btn-sm" onclick="_editTipo('${t.id}')">✏️ Modifica</button>
          <button class="btn btn-danger btn-sm" onclick="_deleteTipo('${t.id}','${t.nome.replace(/'/g,"\\'")}')">🗑</button>
        </div>
      </td>
    </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="admin-section-header">
      <h3>Tipi account</h3>
      <button class="btn btn-primary" onclick="_newTipo()">+ Nuovo tipo</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Nome</th><th>Permessi</th><th>Modificato</th><th></th></tr></thead>
        <tbody>${_tipi.length > 0 ? righe : '<tr><td colspan="4" style="text-align:center;padding:32px;color:var(--muted)">Nessun tipo account.</td></tr>'}</tbody>
      </table>
    </div>
    <div id="tipoFormWrap" style="display:none;margin-top:16px;" class="tipo-form"></div>
  `;

  window._newTipo    = _newTipo;
  window._editTipo   = _editTipo;
  window._deleteTipo = _deleteTipo;
  window._saveTipo   = _saveTipo;
}

function _buildTipoForm(tipo = null) {
  const wrap    = document.getElementById('tipoFormWrap');
  const nomeVal = tipo ? tipo.nome : '';
  const selezionati = tipo ? tipo.permessi || [] : [];
  const gruppi  = getPermessiPerGruppo();

  const gruppiHtml = Object.entries(gruppi).map(([gruppo, perms]) => {
    const permsHtml = perms.map(p => {
      const mancanti = getMissingDeps(p.id, selezionati);
      const disabled = false; // non auto-select, solo avviso
      const checked  = selezionati.includes(p.id) ? 'checked' : '';
      const warnHtml = mancanti.length > 0
        ? `<span class="perm-dep-warn" title="Richiede: ${mancanti.join(', ')}">⚠️ Richiede: ${mancanti.map(d => {
            const found = PERMESSI.find(x => x.id === d);
            return found ? found.label : d;
          }).join(', ')}</span>`
        : '';
      return `
        <label class="perm-row" data-perm="${p.id}">
          <input type="checkbox" value="${p.id}" ${checked} onchange="_aggiornaDepsWarning()"/>
          <span class="perm-label">${p.label}</span>
          <span class="perm-warn-slot" id="warn_${p.id.replace(/\./g,'_')}">${warnHtml}</span>
        </label>`;
    }).join('');
    return `
      <div class="perm-gruppo">
        <div class="perm-gruppo-label">${gruppo}</div>
        ${permsHtml}
      </div>`;
  }).join('');

  wrap.innerHTML = `
    <h4>${tipo ? 'Modifica tipo account' : 'Nuovo tipo account'}</h4>
    <div style="margin-bottom:12px;">
      <label>Nome</label>
      <input id="tipoFormNome" type="text" value="${nomeVal}" placeholder="es. Amministratore" style="width:100%;margin-top:4px;"/>
      <input type="hidden" id="tipoFormId" value="${tipo ? tipo.id : ''}"/>
    </div>
    <div class="perm-grid">${gruppiHtml}</div>
    <div class="perm-note">⚠️ I permessi evidenziati richiedono dipendenze non ancora selezionate.</div>
    <div style="display:flex;gap:8px;margin-top:16px;">
      <button class="btn btn-primary" onclick="_saveTipo()">Salva</button>
      <button class="btn btn-ghost" onclick="document.getElementById('tipoFormWrap').style.display='none'">Annulla</button>
    </div>
  `;
  wrap.style.display = '';

  // Aggiorna warnings al cambio checkbox
  window._aggiornaDepsWarning = _aggiornaDepsWarning;
}

function _aggiornaDepsWarning() {
  const checked = [...document.querySelectorAll('.perm-row input[type=checkbox]:checked')].map(el => el.value);
  PERMESSI.forEach(p => {
    const slot     = document.getElementById(`warn_${p.id.replace(/\./g,'_')}`);
    if (!slot) return;
    const mancanti = getMissingDeps(p.id, checked);
    const isChecked = checked.includes(p.id);
    if (isChecked && mancanti.length > 0) {
      slot.innerHTML = `<span class="perm-dep-warn">⚠️ Richiede: ${mancanti.map(d => {
        const found = PERMESSI.find(x => x.id === d);
        return found ? found.label : d;
      }).join(', ')}</span>`;
    } else {
      slot.innerHTML = '';
    }
  });
}

function _newTipo() { _buildTipoForm(null); }

function _editTipo(id) {
  const tipo = _tipi.find(t => t.id === id);
  if (!tipo) return;
  _buildTipoForm(tipo);
}

async function _saveTipo() {
  const nome = document.getElementById('tipoFormNome').value.trim();
  const id   = document.getElementById('tipoFormId').value;
  if (!nome) { toast('Inserisci un nome'); return; }

  const permessi = [...document.querySelectorAll('.perm-row input[type=checkbox]:checked')].map(el => el.value);

  try {
    if (id) {
      await updateTipoAccount(id, { nome, permessi });
      toast('Tipo account aggiornato');
    } else {
      await createTipoAccount(nome, permessi);
      toast('Tipo account creato');
    }
    await _adminTab('tipi');
  } catch (e) {
    toast(`Errore: ${e.data?.error || e.message}`);
  }
}

async function _deleteTipo(id, nome) {
  if (!confirm(`Eliminare il tipo account "${nome}"?\nImpossibile se ha utenti associati.`)) return;
  try {
    await deleteTipoAccount(id);
    toast('Tipo account eliminato');
    await _adminTab('tipi');
  } catch (e) {
    toast(e.data?.error || e.message || 'Errore');
  }
}

// ── UTENTI (superadmin) ───────────────────────────

function _renderUtentiAdmin(container) {
  const negozioNome = id => _negozi.find(n => n.id === id)?.nome || id || '—';
  const tipoNome    = id => _tipi.find(t => t.id === id)?.nome   || (id ? '(sconosciuto)' : '—');

  const righe = _utenti.map(u => `
    <tr>
      <td><strong>${u.username}</strong></td>
      <td>${tipoNome(u.tipo_account_id)}</td>
      <td>${negozioNome(u.negozio_id)}</td>
      <td class="muted" style="font-size:12px;">${u.ultimo_accesso ? u.ultimo_accesso.slice(0,10) : '—'}</td>
      <td>
        <div style="display:flex;gap:6px;justify-content:flex-end;">
          <button class="btn btn-ghost btn-sm" onclick="_adminPwd('${u.id}','${u.username.replace(/'/g,"\\'")}')">🔑</button>
          <button class="btn btn-ghost btn-sm" onclick="_adminTipo('${u.id}','${u.username.replace(/'/g,"\\'")}')">🏷</button>
          <button class="btn btn-danger btn-sm" onclick="_adminDelete('${u.id}','${u.username.replace(/'/g,"\\'")}')">🗑</button>
        </div>
      </td>
    </tr>
  `).join('');

  container.innerHTML = `
    <div class="admin-section-header">
      <h3>Utenti</h3>
      <button class="btn btn-primary" onclick="_adminNuovoUtente()">+ Nuovo utente</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Username</th><th>Tipo</th><th>Negozio</th><th>Ultimo accesso</th><th></th></tr></thead>
        <tbody>${_utenti.length > 0 ? righe : '<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--muted)">Nessun utente.</td></tr>'}</tbody>
      </table>
    </div>
    <!-- Modali inline -->
    <div id="adminUtenteForm" style="display:none;margin-top:16px;" class="inline-form-block"></div>
  `;

  window._adminNuovoUtente = _adminNuovoUtente;
  window._adminPwd         = _adminPwd;
  window._adminTipo        = _adminTipo;
  window._adminDelete      = _adminDelete;
}

function _adminNuovoUtente() {
  const wrap = document.getElementById('adminUtenteForm');
  wrap.innerHTML = `
    <h4>Nuovo utente</h4>
    <div class="form-grid-2">
      <div><label>Username</label><input id="auUsername" type="text" placeholder="Username"/></div>
      <div><label>Password</label><input id="auPassword" type="password" placeholder="Min. 8 caratteri"/></div>
      <div>
        <label>Tipo account</label>
        <select id="auTipo">${_tipi.map(t => `<option value="${t.id}">${t.nome}</option>`).join('')}</select>
      </div>
      <div>
        <label>Negozio</label>
        <select id="auNegozio">${_negozi.map(n => `<option value="${n.id}">${n.nome}</option>`).join('')}</select>
      </div>
    </div>
    <div id="auError" style="color:var(--cancel);margin-top:8px;"></div>
    <div style="display:flex;gap:8px;margin-top:12px;">
      <button class="btn btn-primary" onclick="_adminSalvaUtente()">Crea utente</button>
      <button class="btn btn-ghost" onclick="document.getElementById('adminUtenteForm').style.display='none'">Annulla</button>
    </div>
  `;
  wrap.style.display = '';
  window._adminSalvaUtente = _adminSalvaUtente;
}

async function _adminSalvaUtente() {
  const username        = document.getElementById('auUsername').value.trim();
  const password        = document.getElementById('auPassword').value;
  const tipo_account_id = document.getElementById('auTipo').value;
  const negozio_id      = document.getElementById('auNegozio').value;
  const errEl           = document.getElementById('auError');

  if (!username)           { errEl.textContent = 'Inserisci username'; return; }
  if (!password)           { errEl.textContent = 'Inserisci password'; return; }
  if (password.length < 8) { errEl.textContent = 'Password minimo 8 caratteri'; return; }
  if (!tipo_account_id)    { errEl.textContent = 'Seleziona tipo account'; return; }
  if (!negozio_id)         { errEl.textContent = 'Seleziona negozio'; return; }

  try {
    await createUtente({ username, password_hash: sha256(password), tipo_account_id, negozio_id });
    toast(`Utente ${username} creato`);
    await _adminTab('utenti');
  } catch (e) {
    errEl.textContent = e.data?.error || e.message || 'Errore';
  }
}

async function _adminPwd(userId, username) {
  const nuova = prompt(`Nuova password per "${username}" (min. 8 caratteri):`);
  if (!nuova) return;
  if (nuova.length < 8) { toast('Password troppo corta (min. 8 caratteri)'); return; }
  try {
    await setPasswordUtente(userId, sha256(nuova));
    toast(`Password di ${username} aggiornata`);
  } catch (e) {
    toast(`Errore: ${e.data?.error || e.message}`);
  }
}

async function _adminTipo(userId, username) {
  const wrap = document.getElementById('adminUtenteForm');
  wrap.innerHTML = `
    <h4>Cambia tipo account: ${username}</h4>
    <select id="adminTipoSel">${_tipi.map(t => `<option value="${t.id}">${t.nome}</option>`).join('')}</select>
    <div id="adminTipoErr" style="color:var(--cancel);margin-top:8px;"></div>
    <div style="display:flex;gap:8px;margin-top:12px;">
      <button class="btn btn-primary" onclick="_adminSalvaTipo('${userId}')">Salva</button>
      <button class="btn btn-ghost" onclick="document.getElementById('adminUtenteForm').style.display='none'">Annulla</button>
    </div>
  `;
  wrap.style.display = '';

  window._adminSalvaTipo = async (uid) => {
    const tipo_account_id = document.getElementById('adminTipoSel').value;
    try {
      await setTipoAccount(uid, tipo_account_id);
      toast('Tipo account aggiornato');
      await _adminTab('utenti');
    } catch (e) {
      document.getElementById('adminTipoErr').textContent = e.data?.error || e.message;
    }
  };
}

async function _adminDelete(userId, username) {
  if (!confirm(`Eliminare definitivamente l'utente "${username}"?\nL'operazione non è reversibile.`)) return;
  try {
    await deleteUtente(userId);
    toast(`Utente ${username} eliminato`);
    await _adminTab('utenti');
  } catch (e) {
    toast(e.data?.error || e.message || 'Errore');
  }
}
