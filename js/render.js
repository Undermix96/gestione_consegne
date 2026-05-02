/**
 * render.js — Funzioni di rendering delle view principali
 *
 * Contiene: renderAll, switchView, renderLista,
 *           renderSidebar, renderGiornata, renderSquadreSettings
 */

import {
  db, currentView, currentGiornataId, expandedRowId,
  setCurrentView, setCurrentGiornataId, setExpandedRowId, SQ_COLORS,
} from './store.js';
import { markDirty } from './sync.js';
import {
  fmtDate, today, isPast, statoPill, tipoBadge,
  sqBadgeHtml, articoliLabel, tipiConsegnaBadges,
  squadraBadgeForConsegna, escHtml, toast,
} from './utils.js';
import { initDragDrop } from './dragdrop.js';

// ── renderAll ────────────────────────────────────

export function renderAll() {
  autoCompleteStati();
  renderLista();
  renderSidebar();
  if (currentGiornataId) renderGiornata(currentGiornataId);
  updateCittaFilter();
  populateSquadreSelect();
  if (currentView === 'impostazioni') renderSquadreSettings();
}

function autoCompleteStati() {
  let changed = false;
  db.consegne.forEach(c => {
    if (c.stato === 'attesa') { c.stato = 'in_attesa'; changed = true; }
  });
  if (changed) markDirty();
}

// ── Navigation ───────────────────────────────────

export function switchView(v) {
  setCurrentView(v);
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  document.getElementById('view' + v.charAt(0).toUpperCase() + v.slice(1)).classList.add('active');
  event.currentTarget.classList.add('active');

  const sidebar = document.getElementById('sidebar');
  if (v === 'giornate') {
    sidebar.classList.remove('hidden');
    renderSidebar();
    if (currentGiornataId) renderGiornata(currentGiornataId);
  } else if (v === 'impostazioni') {
    sidebar.classList.add('hidden');
    renderSquadreSettings();
  } else {
    sidebar.classList.add('hidden');
    renderLista();
  }
}

// ── Lista ────────────────────────────────────────

export function renderLista() {
  const search      = document.getElementById('searchInput')?.value?.toLowerCase() || '';
  const filterStato = document.getElementById('filterStato')?.value || '';
  const filterCitta = document.getElementById('filterCitta')?.value || '';

  let rows = [...db.consegne];
  if (search)      rows = rows.filter(c => `${c.nome} ${c.cognome}`.toLowerCase().includes(search));
  if (filterStato) rows = rows.filter(c => c.stato === filterStato);
  if (filterCitta) rows = rows.filter(c => c.citta === filterCitta);
  rows.sort((a, b) => (b.dataPrenotazione || '').localeCompare(a.dataPrenotazione || ''));

  const tbody = document.getElementById('listaBody');
  document.getElementById('listaCount').textContent = `${rows.length} consegn${rows.length === 1 ? 'a' : 'e'}`;
  tbody.innerHTML = '';

  if (rows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center;padding:40px;color:var(--muted);">Nessuna consegna trovata.</td></tr>`;
    return;
  }

  rows.forEach(c => {
    const stato = c.stato || 'attesa';
    const tr    = document.createElement('tr');
    tr.dataset.stato = stato;
    if (c.id === expandedRowId) tr.classList.add('expanded');
    tr.innerHTML = `
      <td>▶</td>
      <td>${statoPill(stato)}</td>
      <td class="muted" style="font-family:'DM Mono',monospace">${fmtDate(c.dataPrenotazione)}</td>
      <td><strong>${c.cognome || ''} ${c.nome || ''}</strong></td>
      <td class="muted">${c.citta || '—'}</td>
      <td>${tipiConsegnaBadges(c)}</td>
      <td class="muted">${articoliLabel(c)}</td>
      <td>${squadraBadgeForConsegna(c.id)}</td>
      <td class="muted" style="font-family:'DM Mono',monospace">${fmtDate(c.giornoConsegna)}</td>
      <td class="muted">${c.preferenzePeriodo || '—'}</td>
    `;
    tr.addEventListener('click', () => toggleRowDetail(c.id, tr));
    tbody.appendChild(tr);

    const detail = document.createElement('tr');
    detail.className = 'row-detail';
    detail.id = `detail-${c.id}`;
    detail.innerHTML = `<td colspan="10">
      <div class="detail-grid">
        <div class="detail-field"><label>Indirizzo</label><span>${c.indirizzo || '—'}</span></div>
        <div class="detail-field"><label>Telefono 1</label><span>${c.tel1 || '—'}</span></div>
        <div class="detail-field"><label>Telefono 2</label><span>${c.tel2 || '—'}</span></div>
        <div class="detail-field"><label>Piano</label><span>${c.piano || '—'}</span></div>
        <div class="detail-field"><label>RAEE</label><span class="${c.raee === 'si' ? 'raee-yes' : 'raee-no'}">${c.raee === 'si' ? '✅ Sì' : '✗ No'}</span></div>
        <div class="detail-field" style="grid-column:1/-1"><label>Articoli</label><span>${_articoliDetailHtml(c)}</span></div>
        <div class="detail-field"><label>Note abitazione</label><span>${c.noteAbitazione || '—'}</span></div>
        <div class="detail-field"><label>Preferenze periodo</label><span>${c.preferenzePeriodo || '—'}</span></div>
        <div class="detail-field"><label>Note</label><span>${c.note || '—'}</span></div>
      </div>
      <div class="detail-actions">
        <button class="btn btn-ghost" onclick="openEditConsegnaModal('${c.id}')">✏️ Modifica</button>
      </div>
    </td>`;
    tbody.appendChild(detail);
    if (c.id === expandedRowId) {
      detail.classList.add('open');
      tr.querySelector('td:first-child').textContent = '▼';
    }
  });
}

function _articoliDetailHtml(c) {
  const arts = c.articoli && c.articoli.length > 0 ? c.articoli
    : (c.tipoProdotto || c.codiceProdotto ? [{ tipoConsegna: c.tipoConsegna, tipo: c.tipoProdotto, codice: c.codiceProdotto, desc: c.descrizioneProdotto }] : []);
  if (arts.length === 0) return '—';
  return arts.map(a => {
    const parts = [a.tipo, a.codice, a.desc].filter(Boolean).join(' · ') || '—';
    return `<span class="articolo-pill">${tipoBadge(a.tipoConsegna || 'consegna')} 📦 ${parts}</span>`;
  }).join(' ');
}

function toggleRowDetail(id, tr) {
  const detail = document.getElementById(`detail-${id}`);
  if (!detail) return;
  const isOpen = detail.classList.contains('open');
  document.querySelectorAll('.row-detail.open').forEach(el => {
    el.classList.remove('open');
    el.previousElementSibling.querySelector('td:first-child').textContent = '▶';
  });
  if (!isOpen) {
    detail.classList.add('open');
    tr.querySelector('td:first-child').textContent = '▼';
    setExpandedRowId(id);
  } else {
    setExpandedRowId(null);
  }
}

export function updateCittaFilter() {
  const cities = [...new Set(db.consegne.map(c => c.citta).filter(Boolean))].sort();
  const sel = document.getElementById('filterCitta');
  const cur = sel.value;
  sel.innerHTML = '<option value="">Tutte le città</option>';
  cities.forEach(c => {
    const o = document.createElement('option');
    o.value = c; o.textContent = c;
    if (c === cur) o.selected = true;
    sel.appendChild(o);
  });
}

// ── Sidebar ──────────────────────────────────────

export function renderSidebar() {
  const list   = document.getElementById('sidebarList');
  list.innerHTML = '';
  const sorted = [...db.giornate].sort((a, b) => a.data.localeCompare(b.data));

  if (sorted.length === 0) {
    list.innerHTML = '<div style="padding:12px 10px;color:var(--muted);font-size:12px;">Nessuna giornata.</div>';
    return;
  }
  sorted.forEach(g => {
    const past  = isPast(g.data);
    const count = (g.consegneIds || []).length;
    const item  = document.createElement('div');
    item.className = 'sidebar-item' + (g.id === currentGiornataId ? ' active' : '');
    item.innerHTML = `
      <span class="day-dot" style="background:${past ? 'var(--done)' : 'var(--sched)'}"></span>
      <span>${fmtDate(g.data)}</span>
      ${g.squadra ? sqBadgeHtml(g.squadra) : ''}
      <span class="day-badge">${count}</span>
    `;
    item.addEventListener('click', () => selectGiornata(g.id));
    list.appendChild(item);
  });
}

export function selectGiornata(id) {
  setCurrentGiornataId(id);
  renderSidebar();
  renderGiornata(id);
  document.getElementById('noGiornata').style.display   = 'none';
  document.getElementById('giornataWrap').style.display = '';
  document.getElementById('btnStampaPDF').style.display = '';
}

// ── Giornata ─────────────────────────────────────

export function renderGiornata(id) {
  const g = db.giornate.find(x => x.id === id);
  if (!g) return;
  const wrap     = document.getElementById('giornataWrap');
  const past     = isPast(g.data);
  const consegne = (g.consegneIds || []).map(cid => db.consegne.find(c => c.id === cid)).filter(Boolean);
  const totale   = consegne.length;
  const completate = consegne.filter(c => c.stato === 'completata').length;

  document.getElementById('giornataTitle').innerHTML =
    `Giornata del ${fmtDate(g.data)}${g.squadra ? ' &nbsp;' + sqBadgeHtml(g.squadra) : ''}`;

  wrap.innerHTML = `
    <div class="giornata-header">
      <h3>${fmtDate(g.data)}</h3>
      ${past
        ? '<span class="pill pill-done"><span class="dot"></span>✅ Giornata passata</span>'
        : '<span class="pill pill-sched"><span class="dot"></span>📌 Programmata</span>'}
      <div class="g-stats">
        <div class="g-stat"><span class="val">${totale}</span><span class="lbl">Consegne</span></div>
        <div class="g-stat"><span class="val">${completate}</span><span class="lbl">Completate</span></div>
      </div>
      <button class="btn btn-danger" onclick="deleteGiornata('${g.id}')" style="margin-left:8px">🗑 Elimina giornata</button>
    </div>
    <div class="delivery-list" id="deliveryList">
      ${consegne.length === 0
        ? `<div class="empty-state"><div class="icon">📭</div><p>Nessuna consegna in questa giornata.</p></div>`
        : consegne.map((c, i) => _deliveryCardHtml(c, i + 1, g.id)).join('')}
    </div>
    <div class="add-delivery-zone" onclick="openSelectModal('${g.id}')">
      ＋ Aggiungi consegna da lista in attesa
    </div>
  `;
  initDragDrop(g.id);
}

function _deliveryCardHtml(c, num, gid) {
  const arts = c.articoli && c.articoli.length > 0 ? c.articoli
    : (c.tipoProdotto ? [{ tipoConsegna: c.tipoConsegna, tipo: c.tipoProdotto, codice: c.codiceProdotto, desc: c.descrizioneProdotto }] : []);
  const artHtml = arts.length > 0
    ? arts.map(a => {
        const label = [a.tipo, a.codice, a.desc].filter(Boolean).join(' · ') || '—';
        return `<span class="articolo-pill">${tipoBadge(a.tipoConsegna || 'consegna')} ${label}</span>`;
      }).join(' ')
    : '<span style="color:var(--muted)">—</span>';
  const isCompletata = c.stato === 'completata';
  const noteHtml = c.note
    ? `<div class="card-sub card-note" style="margin-top:5px;">📝 ${c.note}</div>`
    : '';
  return `
  <div class="delivery-card${isCompletata ? ' card-completata' : ''}" draggable="true" data-id="${c.id}" data-gid="${gid}">
    <span class="drag-handle">⠿</span>
    <span class="card-num">${num}</span>
    <div class="card-body">
      <div class="card-name">${c.cognome || ''} ${c.nome || ''}${isCompletata ? ' <span class="badge-completata">✅ Consegnata</span>' : ''}</div>
      <div class="card-sub">📍 ${c.citta || ''}${c.indirizzo ? ', ' + c.indirizzo : ''} &nbsp;·&nbsp; 📞 ${c.tel1 || '—'} &nbsp;·&nbsp; 🕐 ${c.fasciaOraria || 'orario n.d.'}</div>
      <div class="card-sub" style="margin-top:4px;display:flex;flex-wrap:wrap;gap:4px;">${artHtml}</div>
      ${noteHtml}
    </div>
    <div class="card-actions">
      ${!isCompletata ? `<button class="icon-btn done" title="Segna come consegnata" onclick="segnaConsegnata('${c.id}','${gid}')">✅</button>` : ''}
      <button class="icon-btn edit" title="Modifica" onclick="openEditConsegnaModal('${c.id}')">✏️</button>
      <button class="icon-btn" title="Rimuovi dalla giornata" onclick="removeFromGiornata('${c.id}','${gid}')">✕</button>
    </div>
  </div>`;
}

// ── Impostazioni / Squadre ────────────────────────

export function renderSquadreSettings() {
  const list = document.getElementById('squadreList');
  if (!list) return;
  if (!db.squadre || db.squadre.length === 0) {
    list.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:8px 0;">Nessuna squadra. Aggiungine una qui sotto.</div>';
    return;
  }
  list.innerHTML = db.squadre.map(s => {
    const ci = s.colorIdx ?? 0;
    const swatches = Array.from({ length: SQ_COLORS }, (_, i) =>
      `<span class="color-swatch sq-c${i}${i === ci ? ' selected' : ''}" onclick="setSquadraColor('${s.id}',${i})" title="Colore ${i + 1}"></span>`
    ).join('');
    return `
    <div class="squadra-row" id="sqrow-${s.id}">
      <span class="sq-badge sq-c${ci}" style="min-width:10px;width:12px;height:12px;padding:0;border-radius:50%;flex-shrink:0;"></span>
      <input type="text" value="${s.nome}" id="sqinput-${s.id}"
        onblur="renameSquadra('${s.id}', this.value)"
        onkeydown="if(event.key==='Enter') this.blur()"/>
      <div class="color-picker" id="cpicker-${s.id}">${swatches}</div>
      <button class="icon-btn" title="Elimina squadra" onclick="deleteSquadra('${s.id}')">🗑</button>
    </div>`;
  }).join('');
}

export function populateSquadreSelect() {
  const sel = document.getElementById('f_nuovaGiornataSquadra');
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">— Nessuna squadra —</option>';
  (db.squadre || []).forEach(s => {
    const o = document.createElement('option');
    o.value = s.nome; o.textContent = s.nome;
    if (s.nome === cur) o.selected = true;
    sel.appendChild(o);
  });
}
