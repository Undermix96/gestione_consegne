/**
 * main.js — Entry point dell'applicazione
 *
 * 1. Inizializza tema, carica dati, avvia polling
 * 2. Espone le funzioni necessarie agli handler inline dell'HTML
 *    (onclick="...", oninput="...") come proprietà di window,
 *    poiché i moduli ES hanno scope chiuso.
 */

import { initTheme, toggleTheme }         from './theme.js';
import { loadData, ping, markDirty }      from './sync.js';
import { renderAll, switchView, selectGiornata, renderGiornata, renderSidebar, renderLista }          from './render.js';
import { db, serverOnline, isDirty }      from './store.js';

import {
  openNewConsegnaModal,
  openEditConsegnaModal,
  saveConsegna,
  deleteCurrentConsegna,
  addArticoloRow,
  removeArticoloRow,
  updateCounter,
} from './modal-consegna.js';

import {
  openNewGiornataModal,
  saveNuovaGiornata,
  removeFromGiornata,
  segnaConsegnata,
  deleteGiornata,
} from './giornate.js';

import {
  openSelectModal,
  renderSelectList,
  confirmAddToGiornata,
} from './modal-select.js';

import {
  addSquadra,
  renameSquadra,
  setSquadraColor,
  deleteSquadra,
} from './squadre.js';

import { stampaPDF }                      from './stampa.js';
import { openModal, closeModal, toast }   from './utils.js';

// ── Init ─────────────────────────────────────────

window.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  await loadData();
  renderAll();

  // Ping ogni 2 secondi
  setInterval(ping, 2000);

  // Polling dati ogni 8 secondi
  setInterval(async () => {
    if (serverOnline && !isDirty) {
      const ok = await loadData();
      if (ok) renderAll();
    }
  }, 8000);

  // Chiudi modal su click overlay o ESC
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape')
      document.querySelectorAll('.modal-overlay.open').forEach(el => el.classList.remove('open'));
  });
});

// ── Esponi funzioni globali per gli onclick HTML ──
// (necessario con ES modules: lo scope è locale al modulo)

Object.assign(window, {
  // Navigation
  switchView,
  selectGiornata,
  toggleTheme,

  // Render (usate anche da dragdrop.js via window)
  renderGiornata,
  renderSidebar,
  renderLista,

  // Lista
  openNewConsegnaModal,
  openEditConsegnaModal,

  // Modal consegna
  saveConsegna,
  deleteCurrentConsegna,
  addArticoloRow,
  removeArticoloRow,
  updateCounter,
  closeModal,
  openModal,

  // Giornate
  openNewGiornataModal,
  saveNuovaGiornata,
  removeFromGiornata,
  segnaConsegnata,
  deleteGiornata,

  // Modal select
  openSelectModal,
  renderSelectList,
  confirmAddToGiornata,

  // Squadre
  addSquadra,
  renameSquadra,
  setSquadraColor,
  deleteSquadra,

  // Stampa
  stampaPDF,
});
