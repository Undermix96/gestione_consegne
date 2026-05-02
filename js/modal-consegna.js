/**
 * modal-consegna.js — Modal creazione / modifica consegna
 */

import { db, currentGiornataId, setEditingConsegnaId, editingConsegnaId } from './store.js';
import { markDirty } from './sync.js';
import { remoteLog } from './api.js';
import { renderAll, renderLista, renderGiornata, renderSidebar } from './render.js';
import { today, fmtDate, escHtml, toast, openModal, closeModal } from './utils.js';

// ── Open modal ───────────────────────────────────

export function openNewConsegnaModal() {
  setEditingConsegnaId(null);
  document.getElementById('modalConsegnaTitle').textContent  = 'Nuova consegna';
  document.getElementById('btnDeleteConsegna').style.display = 'none';
  clearConsegnaForm();
  document.getElementById('f_dataPrenotazione').value        = today();
  document.getElementById('f_stato').value                   = 'in_attesa';
  document.getElementById('f_giornataAssegnata_display').textContent = '—';
  openModal('modalConsegna');
}

export function openEditConsegnaModal(id) {
  const c = db.consegne.find(x => x.id === id);
  if (!c) return;
  setEditingConsegnaId(id);
  document.getElementById('modalConsegnaTitle').textContent  = 'Modifica consegna';
  document.getElementById('btnDeleteConsegna').style.display = '';
  fillConsegnaForm(c);
  resetCounters();
  openModal('modalConsegna');
}

// ── Form helpers ─────────────────────────────────

function clearConsegnaForm() {
  ['dataPrenotazione','stato','nome','cognome','citta','indirizzo','tel1','tel2',
   'raee','piano','noteAbitazione','preferenzePeriodo','fasciaOraria','note'
  ].forEach(f => {
    const el = document.getElementById('f_' + f);
    if (!el) return;
    if (el.tagName === 'SELECT') el.value = el.options[0].value;
    else el.value = '';
  });
  document.getElementById('articoliList').innerHTML = '';
  addArticoloRow();
}

function fillConsegnaForm(c) {
  ['dataPrenotazione','stato','nome','cognome','citta','indirizzo','tel1','tel2',
   'raee','piano','noteAbitazione','preferenzePeriodo','fasciaOraria','note'
  ].forEach(f => {
    const el = document.getElementById('f_' + f);
    if (!el) return;
    if (el.tagName === 'SELECT') el.value = c[f] || el.options[0].value;
    else el.value = c[f] || '';
  });

  const list = document.getElementById('articoliList');
  list.innerHTML = '';
  if (c.articoli && c.articoli.length > 0) {
    c.articoli.forEach(a => addArticoloRow(a.tipo, a.codice, a.desc, a.tipoConsegna || 'consegna'));
  } else if (c.tipoProdotto || c.codiceProdotto || c.descrizioneProdotto) {
    addArticoloRow(c.tipoProdotto, c.codiceProdotto, c.descrizioneProdotto, c.tipoConsegna || 'consegna');
  } else {
    addArticoloRow();
  }

  if (c.giornoConsegna) {
    const g = db.giornate.find(x => x.data === c.giornoConsegna && (x.consegneIds || []).includes(c.id));
    const squadra = g && g.squadra ? ` — ${g.squadra}` : '';
    document.getElementById('f_giornataAssegnata_display').textContent = fmtDate(c.giornoConsegna) + squadra;
  } else {
    document.getElementById('f_giornataAssegnata_display').textContent = '—';
  }
}

export function resetCounters() {
  updateCounter('f_noteAbitazione', 170);
  updateCounter('f_preferenzePeriodo', 90);
  updateCounter('f_note', 170);
}

export function updateCounter(fieldId, max) {
  const el      = document.getElementById(fieldId);
  const counter = document.getElementById('counter_' + fieldId);
  if (!el || !counter) return;
  const len = el.value.length;
  counter.textContent = len + ' / ' + max;
  counter.className   = 'char-counter';
  if (len >= max)            counter.classList.add('danger');
  else if (len >= max * 0.85) counter.classList.add('warn');
}

// ── Articoli ─────────────────────────────────────

export function addArticoloRow(tipo = '', codice = '', desc = '', tipoConsegna = 'consegna') {
  const list = document.getElementById('articoliList');
  const row  = document.createElement('div');
  row.className = 'articolo-row';
  const opts = [
    ['consegna',      '📦 Solo consegna'],
    ['installazione', '🔧 Installaz. semplice'],
    ['incasso',       '🔩 Incasso/muro'],
  ];
  const selectHtml = opts.map(([v, l]) =>
    `<option value="${v}"${v === tipoConsegna ? ' selected' : ''}>${l}</option>`
  ).join('');
  row.innerHTML = `
    <select data-art="tipoConsegna">${selectHtml}</select>
    <input type="text" placeholder="es. Lavatrice, TV…" value="${escHtml(tipo)}" data-art="tipo"/>
    <input type="text" placeholder="SKU / Codice" value="${escHtml(codice)}" data-art="codice"/>
    <input type="text" placeholder="Descrizione estesa…" value="${escHtml(desc)}" data-art="desc"/>
    <button type="button" class="icon-btn" style="color:var(--cancel)" onclick="removeArticoloRow(this)" title="Rimuovi">✕</button>
  `;
  list.appendChild(row);
}

export function removeArticoloRow(btn) {
  const list = document.getElementById('articoliList');
  if (list.children.length <= 1) {
    btn.closest('.articolo-row').querySelectorAll('input').forEach(i => i.value = '');
    const sel = btn.closest('.articolo-row').querySelector('select[data-art="tipoConsegna"]');
    if (sel) sel.value = 'consegna';
    return;
  }
  btn.closest('.articolo-row').remove();
}

function getArticoliFromForm() {
  const rows   = document.querySelectorAll('#articoliList .articolo-row');
  const result = [];
  rows.forEach(row => {
    const tipoConsegna = row.querySelector('[data-art="tipoConsegna"]')?.value || 'consegna';
    const tipo         = row.querySelector('[data-art="tipo"]').value.trim();
    const codice       = row.querySelector('[data-art="codice"]').value.trim();
    const desc         = row.querySelector('[data-art="desc"]').value.trim();
    if (tipo || codice || desc) result.push({ tipoConsegna, tipo, codice, desc });
  });
  return result;
}

// ── Save / Delete ────────────────────────────────

export function saveConsegna() {
  const nome    = document.getElementById('f_nome').value.trim();
  const cognome = document.getElementById('f_cognome').value.trim();
  if (!nome && !cognome) { toast('Inserisci almeno nome o cognome'); return; }

  const editableFields = ['dataPrenotazione','stato','nome','cognome','citta','indirizzo','tel1','tel2',
    'raee','piano','noteAbitazione','preferenzePeriodo','fasciaOraria','note'];
  const data = {};
  editableFields.forEach(f => {
    const el = document.getElementById('f_' + f);
    data[f]  = el ? el.value.trim() : '';
  });
  data.articoli = getArticoliFromForm();
  delete data.tipoProdotto;
  delete data.codiceProdotto;
  delete data.descrizioneProdotto;

  if (editingConsegnaId) {
    const c = db.consegne.find(x => x.id === editingConsegnaId);
    if (c) {
      data.giornoConsegna = c.giornoConsegna;
      Object.assign(c, data);
      markDirty();
      remoteLog(`Modificata consegna ${c.nome} ${c.cognome}`);
      closeModal('modalConsegna');
      renderLista();
      renderGiornata(currentGiornataId);
      renderSidebar();
      toast('Consegna modificata');
    }
    return;
  }

  data.id          = 'c' + Date.now();
  data.giornoConsegna = '';
  db.consegne.push(data);
  markDirty();
  remoteLog(`Aggiunta nuova consegna ${data.nome} ${data.cognome}`);
  closeModal('modalConsegna');
  renderLista();
  renderGiornata(currentGiornataId);
  renderSidebar();
  toast('Consegna aggiunta');
}

export function deleteCurrentConsegna() {
  if (!editingConsegnaId) return;
  if (!confirm("Eliminare definitivamente questa consegna? L'operazione non è reversibile.")) return;
  const c = db.consegne.find(x => x.id === editingConsegnaId);
  db.giornate.forEach(g => {
    g.consegneIds = (g.consegneIds || []).filter(id => id !== editingConsegnaId);
  });
  db.consegne = db.consegne.filter(x => x.id !== editingConsegnaId);
  markDirty();
  remoteLog(`Eliminata consegna: ${c ? c.nome + ' ' + c.cognome : editingConsegnaId}`);
  closeModal('modalConsegna');
  renderAll();
  toast('Consegna eliminata');
}
