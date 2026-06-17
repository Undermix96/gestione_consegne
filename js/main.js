/**
 * main.js — Entry point dell'applicazione
 *
 * 1. Inizializza auth UI
 * 2. Controlla sessione → se assente mostra overlay login
 * 3. In base al ruolo, avvia l'app operativa o il pannello superadmin
 * 4. Espone le funzioni necessarie agli handler inline dell'HTML su window
 */

import { initTheme, toggleTheme }         from './theme.js';
import { loadData, ping, markDirty }      from './sync.js';
import { renderAll, switchView, selectGiornata, renderGiornata, renderSidebar, renderLista } from './render.js';
import { db, serverOnline, isDirty, setCurrentUser } from './store.js';

import {
  initAuthUI, showLoginOverlay, isLoggedIn,
  getRuolo, getUsername, getUserId, logout,
  showChangePasswordOverlay, changePassword,
} from './auth.js';

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
  renderPannelloUtenti, openNuovoUtente, salvaNuovoUtente,
  openCambioPasswordUtente, salvaCambioPasswordUtente,
  declassaAdmin, eliminaUtente,
} from './modal-utenti.js';

import { stampaPDF }                      from './stampa.js';
import { openModal, closeModal, toast }   from './utils.js';

// ── Init ─────────────────────────────────────────

window.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  initAuthUI();

  // Mostra nome utente nell'header se presente
  _aggiornaHeaderUtente();

  if (!isLoggedIn()) {
    showLoginOverlay();
    return;
  }

  await _initApp();
});

/**
 * Avvia l'app dopo il login.
 * Esposto su window per essere chiamato da auth.js dopo login riuscito.
 */
window._initApp = async function () {
  const ruolo    = getRuolo();
  const username = getUsername();
  const userId   = getUserId();

  setCurrentUser({ id: userId, username, ruolo });
  _aggiornaHeaderUtente();

  if (ruolo === 'superadmin') {
    _avviaSuperadmin();
    return;
  }

  // Mostra/nascondi tab in base al ruolo
  _applicaPermessiUI(ruolo);

  // Avvia app operativa
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
};

function _avviaSuperadmin() {
  // Nasconde tutta l'interfaccia operativa
  document.querySelector('.app-body').style.display  = 'none';
  document.querySelector('.nav-tabs').style.display  = 'none';

  // Mostra il pannello utenti dedicato
  document.getElementById('superadminPanel').style.display = '';
  renderPannelloUtenti('pannelloUtentiSuperadmin');
}

function _applicaPermessiUI(ruolo) {
  if (ruolo === 'standard') {
    // Nasconde la tab Impostazioni
    const tabImpostazioni = document.querySelector('.nav-tab[data-view="impostazioni"]');
    if (tabImpostazioni) tabImpostazioni.style.display = 'none';
  }
  // Mostra/nasconde il link "Gestione utenti" nell'header
  const linkUtenti = document.getElementById('btnGestioneUtenti');
  if (linkUtenti) {
    linkUtenti.style.display = (ruolo === 'admin') ? '' : 'none';
  }
}

function _aggiornaHeaderUtente() {
  const el = document.getElementById('headerUsername');
  if (!el) return;
  const username = getUsername();
  el.textContent = username ? username : '';
}

// ── Esponi funzioni globali per gli onclick HTML ──

Object.assign(window, {
  // Navigation
  switchView,
  selectGiornata,
  toggleTheme,

  // Render
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

  // Utenti (admin/superadmin)
  renderPannelloUtenti,
  openNuovoUtente,
  salvaNuovoUtente,
  openCambioPasswordUtente,
  salvaCambioPasswordUtente,
  declassaAdmin,
  eliminaUtente,

  // Auth
  logout: async () => {
    await logout();
    sessionStorage.clear();
    location.reload();
  },
  apriCambioPasswordProprio: () => {
    showChangePasswordOverlay('');
  },
});
