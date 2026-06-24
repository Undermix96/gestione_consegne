/**
 * main.js — Entry point dell'applicazione
 */

import { initTheme, toggleTheme }       from './theme.js';
import { loadData, ping, pollData }     from './sync.js';
import {
  renderAll, switchView, selectGiornata,
  renderGiornata, renderSidebar, renderLista,
} from './render.js';
import {
  db, serverOnline, setCurrentUser,
} from './store.js';
import {
  initAuthUI, showLoginOverlay, isLoggedIn,
  getUsername, getUserId, getNegozioId,
  getPermessi, isSuperadmin, logout,
  showChangePasswordOverlay,
} from './auth.js';
import { hasPermesso } from './permessi.js';

import {
  openNewConsegnaModal, openEditConsegnaModal,
  saveConsegna, deleteCurrentConsegna,
  addArticoloRow, removeArticoloRow, updateCounter,
} from './modal-consegna.js';

import {
  openNewGiornataModal, saveNuovaGiornata,
  removeFromGiornata, segnaConsegnata, deleteGiornata,
} from './giornate.js';

import {
  openSelectModal, renderSelectList, confirmAddToGiornata,
} from './modal-select.js';

import {
  addSquadra, renameSquadra, setSquadraColor, deleteSquadra,
} from './squadre.js';

import {
  renderPannelloAdmin,
  openNuovoUtente, salvaNuovoUtente,
  openCambioPasswordUtente, salvaCambioPasswordUtente,
  openCambioTipoAccount, salvaCambioTipoAccount,
  eliminaUtente,
} from './modal-utenti.js';

import { stampaPDF } from './stampa.js';
import { openModal, closeModal, toast } from './utils.js';

// ── Init ─────────────────────────────────────────

window.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  initAuthUI();
  _aggiornaHeaderUtente();

  if (!isLoggedIn()) {
    showLoginOverlay();
    return;
  }

  await _initApp();
});

window._initApp = async function () {
  const username     = getUsername();
  const userId       = getUserId();
  const negozioId    = getNegozioId();
  const permessi     = getPermessi();
  const superadmin   = isSuperadmin();

  setCurrentUser({ id: userId, username, negozio_id: negozioId, permessi, is_superadmin: superadmin });
  _aggiornaHeaderUtente();

  if (superadmin) {
    _avviaSuperadmin();
    return;
  }

  _applicaPermessiUI();

  const ok = await loadData();
  if (ok) renderAll();

  // Ping ogni 2 secondi (1 fallito → overlay)
  setInterval(ping, 2000);

  // Polling ogni 8 secondi basato su timestamp
  setInterval(pollData, 8000);

  // Callback chiamata da sync.js quando il poll trova cambiamenti
  window._onPollUpdate = () => renderAll();

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
};

function _avviaSuperadmin() {
  document.querySelector('.app-body').style.display = 'none';
  document.querySelector('.nav-tabs').style.display = 'none';
  document.getElementById('superadminPanel').style.display = '';

  // Importazione dinamica per non caricare modal-admin a tutti gli utenti
  import('./modal-admin.js').then(m => {
    m.renderPannelloSuperadmin('superadminPanel');
  });
}

function _applicaPermessiUI() {
  // Tab Impostazioni: visibile solo con squadre.gestisci
  const tabImpostazioni = document.querySelector('.nav-tab[data-view="impostazioni"]');
  if (tabImpostazioni) {
    tabImpostazioni.style.display = hasPermesso('squadre.gestisci') ? '' : 'none';
  }

  // Link gestione utenti nell'header: visibile con utenti.leggi
  const linkUtenti = document.getElementById('btnGestioneUtenti');
  if (linkUtenti) {
    linkUtenti.style.display = hasPermesso('utenti.leggi') ? '' : 'none';
  }

  // Bottone nuova consegna
  const btnNuovaConsegna = document.getElementById('btnNuovaConsegna');
  if (btnNuovaConsegna) {
    btnNuovaConsegna.style.display = hasPermesso('consegne.scrivi') ? '' : 'none';
  }

  // Bottone nuova giornata (sidebar + barra vista)
  const btnNuovaGiornata = document.getElementById('btnNuovaGiornata');
  if (btnNuovaGiornata) {
    btnNuovaGiornata.style.display = hasPermesso('giornate.crea') ? '' : 'none';
  }
  const btnNuovaGiornataBar = document.getElementById('btnNuovaGiornataBar');
  if (btnNuovaGiornataBar) {
    btnNuovaGiornataBar.style.display = hasPermesso('giornate.crea') ? '' : 'none';
  }

  // Bottone stampa PDF
  const btnStampa = document.getElementById('btnStampaPDF');
  if (btnStampa) {
    btnStampa.style.display = hasPermesso('stampa.pdf') ? '' : 'none';
  }
}

function _aggiornaHeaderUtente() {
  const el = document.getElementById('headerUsername');
  if (!el) return;
  el.textContent = getUsername() ?? '';
}

// ── Esponi funzioni globali ───────────────────────

Object.assign(window, {
  switchView,
  selectGiornata,
  toggleTheme,
  renderGiornata,
  renderSidebar,
  renderLista,

  openNewConsegnaModal,
  openEditConsegnaModal,
  saveConsegna,
  deleteCurrentConsegna,
  addArticoloRow,
  removeArticoloRow,
  updateCounter,
  closeModal,
  openModal,

  openNewGiornataModal,
  saveNuovaGiornata,
  removeFromGiornata,
  segnaConsegnata,
  deleteGiornata,

  openSelectModal,
  renderSelectList,
  confirmAddToGiornata,

  addSquadra,
  renameSquadra,
  setSquadraColor,
  deleteSquadra,

  stampaPDF,

  // Gestione utenti (utenti con permessi utenti.*)
  renderPannelloAdmin,
  openNuovoUtente,
  salvaNuovoUtente,
  openCambioPasswordUtente,
  salvaCambioPasswordUtente,
  openCambioTipoAccount,
  salvaCambioTipoAccount,
  eliminaUtente,

  logout: async () => {
    await logout();
    sessionStorage.clear();
    location.reload();
  },
  apriCambioPasswordProprio: () => showChangePasswordOverlay(''),
});
