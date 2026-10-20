/**
 * giornate.js — Azioni sulle giornate e modal nuova giornata
 */

import { db, currentGiornataId, setCurrentGiornataId } from './store.js';
import { applyServerResponse, setSaving, syncOk, reportError } from './sync.js';
import { createGiornata, deleteGiornata as apiDeleteGiornata, rimuoviConsegna, segnaCompletata as apiSegna } from './api.js';
import { renderGiornata, renderSidebar, renderLista, populateSquadreSelect } from './render.js';
import { today, toast, openModal, closeModal } from './utils.js';
import { hasPermesso } from './permessi.js';

// ── Rimuovi consegna dalla giornata ──────────────

export async function removeFromGiornata(cid, gid) {
  setSaving();
  try {
    const result = await rimuoviConsegna(gid, cid);
    applyServerResponse(result);
    renderGiornata(gid);
    renderSidebar();
    renderLista();
    toast('Consegna rimossa dalla giornata → tornata in attesa');
    syncOk();
  } catch (e) {
    reportError(e);
  }
}

// ── Segna consegna come completata ───────────────

export async function segnaConsegnata(cid, gid) {
  setSaving();
  try {
    const result = await apiSegna(gid, cid);
    applyServerResponse(result);
    renderGiornata(gid);
    renderLista();
    toast('Consegna segnata come completata ✅');
    syncOk();
  } catch (e) {
    reportError(e);
  }
}

// ── Elimina giornata ─────────────────────────────

export async function deleteGiornata(gid) {
  const g = db.giornate.find(x => x.id === gid);
  if (!g) return;
  if (g.consegneIds && g.consegneIds.length > 0) {
    toast('Impossibile eliminare la giornata: contiene consegne assegnate. Rimuovi prima le consegne.');
    return;
  }
  if (!confirm('Eliminare questa giornata?')) return;

  setSaving();
  try {
    const result = await apiDeleteGiornata(gid);
    applyServerResponse(result);

    if (currentGiornataId === gid) {
      setCurrentGiornataId(null);
      document.getElementById('noGiornata').style.display   = '';
      document.getElementById('giornataWrap').style.display = 'none';
      document.getElementById('giornataTitle').textContent  = 'Giornate di consegna';
      document.getElementById('btnStampaPDF').style.display = 'none';
    }
    renderSidebar();
    renderLista();
    toast('Giornata eliminata');
    syncOk();
  } catch (e) {
    reportError(e);
  }
}

// ── Modal nuova giornata ─────────────────────────

export function openNewGiornataModal() {
  document.getElementById('f_nuovaGiornata').value = today();
  populateSquadreSelect();
  openModal('modalGiornata');
}

export async function saveNuovaGiornata() {
  const data    = document.getElementById('f_nuovaGiornata').value;
  if (!data) { toast('Inserisci una data'); return; }
  const squadra_id = document.getElementById('f_nuovaGiornataSquadra').value;
  if (!squadra_id) { toast('Crea prima almeno una squadra (Impostazioni)'); return; }

  setSaving();
  try {
    const result = await createGiornata({ data, squadra_id });

    // Salva gli id esistenti PRIMA di aggiornare lo store,
    // così possiamo identificare quale giornata è quella appena creata.
    const idsPrecedenti = new Set(db.giornate.map(g => g.id));
    applyServerResponse(result);

    // La giornata nuova è quella presente nella risposta ma non nel db precedente
    const nuova = result.giornate?.find(g => !idsPrecedenti.has(g.id));
    const newId = nuova?.id;

    closeModal('modalGiornata');
    renderSidebar();

    if (newId) {
      setCurrentGiornataId(newId);
      renderGiornata(newId);
      document.getElementById('noGiornata').style.display   = 'none';
      document.getElementById('giornataWrap').style.display = '';
      if (hasPermesso('stampa.pdf')) {
        document.getElementById('btnStampaPDF').style.display = '';
      }
    }

    // Switcha alla tab giornate se non già attiva
    const tabGiornate = document.querySelector('.nav-tab[data-view="giornate"]');
    if (tabGiornate) tabGiornate.click();

    toast(`Giornata del ${data} aggiunta`);
    syncOk();
  } catch (e) {
    reportError(e);
  }
}
