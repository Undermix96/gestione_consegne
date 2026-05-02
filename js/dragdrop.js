/**
 * dragdrop.js — Gestione drag & drop delle card nella giornata
 *
 * Nota: renderGiornata e renderSidebar sono chiamati via window
 * per evitare dipendenze circolari con render.js.
 */

import { db } from './store.js';
import { markDirty } from './sync.js';
import { remoteLog } from './api.js';

let dragSrcId = null;

export function initDragDrop(gid) {
  const list = document.getElementById('deliveryList');
  if (!list) return;

  list.querySelectorAll('.delivery-card').forEach(card => {
    card.addEventListener('dragstart', e => {
      dragSrcId = card.dataset.id;
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    });
    card.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      list.querySelectorAll('.delivery-card').forEach(c => c.classList.remove('drag-over'));
    });
    card.addEventListener('dragover', e => {
      e.preventDefault();
      list.querySelectorAll('.delivery-card').forEach(c => c.classList.remove('drag-over'));
      card.classList.add('drag-over');
    });
    card.addEventListener('drop', e => {
      e.preventDefault();
      if (dragSrcId && dragSrcId !== card.dataset.id) {
        reorderGiornata(gid, dragSrcId, card.dataset.id);
      }
      card.classList.remove('drag-over');
    });
  });
}

function reorderGiornata(gid, srcId, targetId) {
  const g = db.giornate.find(x => x.id === gid);
  if (!g) return;
  const ids = g.consegneIds || [];
  const si  = ids.indexOf(srcId);
  const ti  = ids.indexOf(targetId);
  if (si === -1 || ti === -1) return;
  ids.splice(si, 1);
  ids.splice(ti, 0, srcId);
  g.consegneIds = ids;
  markDirty();
  remoteLog(`Riordinata giornata ${g.data}`);
  // chiamata via window per evitare circolare con render.js
  window.renderGiornata(gid);
  window.renderSidebar();
}
