/**
 * dragdrop.js — Gestione drag & drop delle card nella giornata
 */

import { db } from './store.js';
import { applyServerResponse, setSaving, syncOk, syncError } from './sync.js';
import { riordinaGiornata } from './api.js';
import { hasPermesso } from './permessi.js';

let dragSrcId = null;

export function initDragDrop(gid) {
  const list = document.getElementById('deliveryList');
  if (!list) return;

  // Se l'utente non ha il permesso di riordinare, disabilita drag
  const canRiordina = hasPermesso('giornate.riordina');

  list.querySelectorAll('.delivery-card').forEach(card => {
    if (!canRiordina) {
      card.setAttribute('draggable', 'false');
      const handle = card.querySelector('.drag-handle');
      if (handle) handle.style.opacity = '0.2';
      return;
    }

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
    card.addEventListener('drop', async e => {
      e.preventDefault();
      if (dragSrcId && dragSrcId !== card.dataset.id) {
        await reorderGiornata(gid, dragSrcId, card.dataset.id);
      }
      card.classList.remove('drag-over');
    });
  });
}

async function reorderGiornata(gid, srcId, targetId) {
  const g = db.giornate.find(x => x.id === gid);
  if (!g) return;
  const ids = [...(g.consegneIds || [])];
  const si  = ids.indexOf(srcId);
  const ti  = ids.indexOf(targetId);
  if (si === -1 || ti === -1) return;
  ids.splice(si, 1);
  ids.splice(ti, 0, srcId);

  setSaving();
  try {
    const result = await riordinaGiornata(gid, ids);
    // Aggiorna localmente senza re-render completo (evita interruzione drag)
    g.consegneIds = ids;
    if (result) {
      applyServerResponse(result);
    }
    syncOk();
    // Re-render via window per evitare dipendenza circolare
    window.renderGiornata?.(gid);
    window.renderSidebar?.();
  } catch (e) {
    syncError();
    window.renderGiornata?.(gid); // ripristina ordine dal server
  }
}
