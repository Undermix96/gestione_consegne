/**
 * squadre.js — Gestione squadre (CRUD + colori)
 */

import { db, SQ_COLORS, currentGiornataId } from './store.js';
import { applyServerResponse, setSaving, syncOk, syncError } from './sync.js';
import { createSquadra, updateSquadra, deleteSquadra as apiDeleteSquadra } from './api.js';
import { renderSquadreSettings, renderSidebar, renderLista, populateSquadreSelect, renderGiornata } from './render.js';
import { toast } from './utils.js';

export async function addSquadra() {
  const input = document.getElementById('newSquadraInput');
  const nome  = input.value.trim();
  if (!nome) { toast('Inserisci un nome per la squadra'); return; }

  setSaving();
  try {
    const result = await createSquadra(nome);
    applyServerResponse(result);
    input.value = '';
    renderSquadreSettings();
    populateSquadreSelect();
    toast('Squadra aggiunta');
    syncOk();
  } catch (e) {
    syncError();
    if (e.status === 409) toast('Squadra già esistente');
    else toast(`Errore: ${e.message}`);
  }
}

export async function renameSquadra(id, nuovoNome) {
  nuovoNome = nuovoNome.trim();
  const s = db.squadre.find(x => x.id === id);
  if (!s || !nuovoNome || nuovoNome === s.nome) {
    renderSquadreSettings();
    return;
  }
  setSaving();
  try {
    const result = await updateSquadra(id, { nome: nuovoNome });
    applyServerResponse(result);
    renderSquadreSettings();
    renderSidebar();
    populateSquadreSelect();
    toast('Squadra rinominata');
    syncOk();
  } catch (e) {
    syncError();
    renderSquadreSettings();
    toast(`Errore: ${e.message}`);
  }
}

export async function setSquadraColor(id, idx) {
  setSaving();
  try {
    const result = await updateSquadra(id, { colorIdx: idx });
    applyServerResponse(result);
    renderSquadreSettings();
    renderSidebar();
    renderLista();
    if (currentGiornataId) renderGiornata(currentGiornataId);
    syncOk();
  } catch (e) {
    syncError();
    toast(`Errore: ${e.message}`);
  }
}

export async function deleteSquadra(id) {
  const s = db.squadre.find(x => x.id === id);
  if (!s) return;
  if (!confirm(`Eliminare la squadra "${s.nome}"? Le giornate assegnate perderanno la squadra.`)) return;

  setSaving();
  try {
    const result = await apiDeleteSquadra(id);
    applyServerResponse(result);
    renderSquadreSettings();
    renderSidebar();
    populateSquadreSelect();
    toast('Squadra eliminata');
    syncOk();
  } catch (e) {
    syncError();
    toast(`Errore: ${e.message}`);
  }
}
