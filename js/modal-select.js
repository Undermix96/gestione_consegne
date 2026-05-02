/**
 * modal-select.js — Modal "Aggiungi consegne alla giornata"
 */

import { db } from './store.js';
import { markDirty } from './sync.js';
import { remoteLog } from './api.js';
import { renderGiornata, renderSidebar, renderLista } from './render.js';
import { fmtDate, toast, openModal, closeModal } from './utils.js';

let selectGiornataId = null;

export function openSelectModal(gid) {
  selectGiornataId = gid;
  document.getElementById('selectSearch').value = '';
  renderSelectList();
  openModal('modalSelect');
}

export function renderSelectList() {
  const search   = document.getElementById('selectSearch').value.toLowerCase();
  const g        = db.giornate.find(x => x.id === selectGiornataId);
  const assigned = new Set(g ? g.consegneIds : []);

  // Mostra solo le consegne disponibili: in attesa e da riprogrammare
  // Le consegne "da_confermare" sono già assegnate a una giornata
  let candidates = db.consegne.filter(c =>
    (c.stato === 'attesa' || c.stato === 'in_attesa' || c.stato === 'da_riprogrammare')
    && !assigned.has(c.id)
  );
  if (search) candidates = candidates.filter(c =>
    `${c.nome} ${c.cognome}`.toLowerCase().includes(search)
  );

  const list = document.getElementById('selectList');
  if (candidates.length === 0) {
    list.innerHTML = '<div style="text-align:center;padding:24px;color:var(--muted)">Nessuna consegna disponibile.</div>';
    return;
  }
  list.innerHTML = candidates.map(c => `
    <label class="select-item">
      <input type="checkbox" value="${c.id}"/>
      <div>
        <div class="si-name">${c.cognome || ''} ${c.nome || ''}</div>
        <div class="si-sub">📍 ${c.citta || '—'} · ${c.tipoProdotto || '—'} · Pren. ${fmtDate(c.dataPrenotazione)}</div>
      </div>
    </label>
  `).join('');
}

export function confirmAddToGiornata() {
  const g = db.giornate.find(x => x.id === selectGiornataId);
  if (!g) return;
  const checked = [...document.querySelectorAll('#selectList input[type=checkbox]:checked')];
  if (checked.length === 0) { toast('Seleziona almeno una consegna'); return; }

  checked.forEach(cb => {
    const cid = cb.value;
    if (!g.consegneIds.includes(cid)) g.consegneIds.push(cid);
    const c = db.consegne.find(x => x.id === cid);
    if (c) {
      c.stato          = 'da_confermare';
      c.giornoConsegna = g.data;
    }
  });
  markDirty();
  remoteLog(`Aggiunte ${checked.length} consegne alla giornata ${g.data}`);
  closeModal('modalSelect');
  renderGiornata(selectGiornataId);
  renderSidebar();
  renderLista();
  toast(`${checked.length} consegna/e aggiunta/e alla giornata`);
}
