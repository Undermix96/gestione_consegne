/**
 * squadre.js — Gestione squadre (CRUD + colori)
 */

import { db, SQ_COLORS } from './store.js';
import { markDirty } from './sync.js';
import { remoteLog } from './api.js';
import { renderSquadreSettings, renderSidebar, renderLista, populateSquadreSelect } from './render.js';
import { uid, toast } from './utils.js';
import { renderGiornata } from './render.js';
import { currentGiornataId } from './store.js';

export function addSquadra() {
  const input = document.getElementById('newSquadraInput');
  const nome  = input.value.trim();
  if (!nome) { toast('Inserisci un nome per la squadra'); return; }
  if (db.squadre.find(s => s.nome.toLowerCase() === nome.toLowerCase())) {
    toast('Squadra già esistente'); return;
  }
  const colorIdx = db.squadre.length % SQ_COLORS;
  db.squadre.push({ id: uid(), nome, colorIdx });
  input.value = '';
  markDirty();
  remoteLog('Aggiunta squadra: ' + nome);
  renderSquadreSettings();
  populateSquadreSelect();
  toast('Squadra aggiunta');
}

export function renameSquadra(id, nuovoNome) {
  nuovoNome = nuovoNome.trim();
  if (!nuovoNome) { renderSquadreSettings(); return; }
  const s = db.squadre.find(x => x.id === id);
  if (!s) return;
  const vecchioNome = s.nome;
  if (vecchioNome === nuovoNome) return;
  db.giornate.forEach(g => { if (g.squadra === vecchioNome) g.squadra = nuovoNome; });
  s.nome = nuovoNome;
  markDirty();
  remoteLog(`Rinominata squadra: ${vecchioNome} → ${nuovoNome}`);
  renderSquadreSettings();
  renderSidebar();
  populateSquadreSelect();
  toast('Squadra rinominata');
}

export function setSquadraColor(id, idx) {
  const s = db.squadre.find(x => x.id === id);
  if (!s) return;
  s.colorIdx = idx;
  markDirty();
  renderSquadreSettings();
  renderSidebar();
  renderLista();
  if (currentGiornataId) renderGiornata(currentGiornataId);
}

export function deleteSquadra(id) {
  const s = db.squadre.find(x => x.id === id);
  if (!s) return;
  if (!confirm(`Eliminare la squadra "${s.nome}"? Le giornate assegnate perderanno la squadra.`)) return;
  db.giornate.forEach(g => { if (g.squadra === s.nome) g.squadra = ''; });
  db.squadre = db.squadre.filter(x => x.id !== id);
  markDirty();
  remoteLog('Eliminata squadra: ' + s.nome);
  renderSquadreSettings();
  renderSidebar();
  populateSquadreSelect();
  toast('Squadra eliminata');
}
