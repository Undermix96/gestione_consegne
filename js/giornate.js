/**
 * giornate.js — Azioni sulle giornate e modal nuova giornata
 */

import { db, currentGiornataId, setCurrentGiornataId } from './store.js';
import { markDirty } from './sync.js';
import { remoteLog } from './api.js';
import { renderGiornata, renderSidebar, renderLista, populateSquadreSelect } from './render.js';
import { today, toast, openModal, closeModal } from './utils.js';
import { uid } from './utils.js';

// ── Azioni card ──────────────────────────────────

export function removeFromGiornata(cid, gid) {
  const g = db.giornate.find(x => x.id === gid);
  if (!g) return;
  g.consegneIds = (g.consegneIds || []).filter(id => id !== cid);
  const c = db.consegne.find(x => x.id === cid);
  if (c && (c.stato === 'programmata' || c.stato === 'da_confermare')) {
    c.stato = 'in_attesa';
    c.giornoConsegna = '';
    c.fasciaOraria   = '';
  }
  markDirty();
  remoteLog(`Rimossa consegna ${c ? c.nome + ' ' + c.cognome : cid} dalla giornata ${g.data}`);
  renderGiornata(gid);
  renderSidebar();
  renderLista();
  toast('Consegna rimossa dalla giornata → tornata in attesa');
}

export function segnaConsegnata(cid, gid) {
  const c = db.consegne.find(x => x.id === cid);
  if (!c) return;
  c.stato = 'completata';
  markDirty();
  remoteLog(`Consegna completata: ${c.cognome || ''} ${c.nome || ''}`);
  renderGiornata(gid);
  renderLista();
  toast('Consegna segnata come completata ✅');
}

export function deleteGiornata(gid) {
  const g = db.giornate.find(x => x.id === gid);
  if (!g) return;

  if (g.consegneIds && g.consegneIds.length > 0) {
    toast('Impossibile eliminare la giornata: contiene consegne assegnate. Rimuovi prima le consegne.');
    return;
  }
  if (!confirm('Eliminare questa giornata? Le consegne assegnate torneranno "In attesa".')) return;

  (g.consegneIds || []).forEach(cid => {
    const c = db.consegne.find(x => x.id === cid);
    if (c && (c.stato === 'programmata' || c.stato === 'da_confermare')) {
      c.stato = 'in_attesa';
      c.giornoConsegna = '';
    }
  });
  db.giornate = db.giornate.filter(x => x.id !== gid);

  if (currentGiornataId === gid) {
    setCurrentGiornataId(null);
    document.getElementById('noGiornata').style.display   = '';
    document.getElementById('giornataWrap').style.display = 'none';
    document.getElementById('giornataTitle').textContent  = 'Giornate di consegna';
    document.getElementById('btnStampaPDF').style.display = 'none';
  }
  markDirty();
  remoteLog(`Eliminata giornata ${g.data}`);
  renderSidebar();
  renderLista();
  toast('Giornata eliminata');
}

// ── Modal nuova giornata ─────────────────────────

export function openNewGiornataModal() {
  document.getElementById('f_nuovaGiornata').value = today();
  populateSquadreSelect();
  openModal('modalGiornata');
}

export function saveNuovaGiornata() {
  const data    = document.getElementById('f_nuovaGiornata').value;
  if (!data) { toast('Inserisci una data'); return; }
  const squadra = document.getElementById('f_nuovaGiornataSquadra').value;
  const g = { id: uid(), data, squadra, consegneIds: [] };
  db.giornate.push(g);
  markDirty();
  remoteLog(`Aggiunta giornata ${data}`);
  closeModal('modalGiornata');
  renderSidebar();

  // Seleziona la nuova giornata e passa alla vista giornate
  setCurrentGiornataId(g.id);
  renderGiornata(g.id);
  document.getElementById('noGiornata').style.display   = 'none';
  document.getElementById('giornataWrap').style.display = '';
  document.getElementById('btnStampaPDF').style.display = '';

  // Switcha alla tab giornate se non già attiva
  const tabGiornate = document.querySelector('.nav-tab:nth-child(2)');
  if (tabGiornate) tabGiornate.click();

  toast(`Giornata del ${data} aggiunta`);
}
