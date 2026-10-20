/**
 * permessi.js — Lista permessi, dipendenze, helper hasPermesso
 */

import { currentUser } from './store.js';

// Lista completa dei permessi assegnabili con label leggibile
export const PERMESSI = [
  // CONSEGNE
  { id: 'consegne.leggi',             label: 'Consegne — Visualizza',                gruppo: 'Consegne' },
  { id: 'consegne.scrivi',            label: 'Consegne — Crea e modifica',           gruppo: 'Consegne' },
  { id: 'consegne.elimina',           label: 'Consegne — Elimina',                   gruppo: 'Consegne' },
  // GIORNATE
  { id: 'giornate.leggi',             label: 'Giornate — Visualizza',                gruppo: 'Giornate' },
  { id: 'giornate.crea',              label: 'Giornate — Crea',                      gruppo: 'Giornate' },
  { id: 'giornate.elimina',           label: 'Giornate — Elimina',                   gruppo: 'Giornate' },
  { id: 'giornate.assegna',           label: 'Giornate — Assegna/rimuovi consegne',  gruppo: 'Giornate' },
  { id: 'giornate.riordina',          label: 'Giornate — Riordina consegne',         gruppo: 'Giornate' },
  { id: 'giornate.segna_completata',  label: 'Giornate — Segna consegna completata', gruppo: 'Giornate' },
  // SQUADRE
  { id: 'squadre.leggi',              label: 'Squadre — Visualizza',                 gruppo: 'Squadre' },
  { id: 'squadre.gestisci',           label: 'Squadre — Gestisci (CRUD)',            gruppo: 'Squadre' },
  // STAMPA
  { id: 'stampa.pdf',                 label: 'Stampa PDF giornata',                  gruppo: 'Stampa' },
  // TIPI ACCOUNT
  { id: 'tipi_account.leggi',         label: 'Tipi account — Visualizza',            gruppo: 'Tipi account' },
  // UTENTI
  { id: 'utenti.leggi',               label: 'Utenti — Visualizza',                  gruppo: 'Utenti' },
  { id: 'utenti.crea',                label: 'Utenti — Crea',                        gruppo: 'Utenti' },
  { id: 'utenti.modifica',            label: 'Utenti — Modifica (password, tipo)',    gruppo: 'Utenti' },
  { id: 'utenti.elimina',             label: 'Utenti — Elimina',                     gruppo: 'Utenti' },
];

// Dipendenze: permesso → lista permessi richiesti
export const DIPENDENZE = {
  'consegne.scrivi':           ['consegne.leggi'],
  'consegne.elimina':          ['consegne.leggi'],
  'giornate.crea':             ['giornate.leggi', 'squadre.leggi'],
  'giornate.elimina':          ['giornate.leggi'],
  'giornate.assegna':          ['giornate.leggi', 'consegne.leggi'],
  'giornate.riordina':         ['giornate.leggi'],
  'giornate.segna_completata': ['giornate.leggi'],
  'squadre.gestisci':          ['squadre.leggi'],
  'stampa.pdf':                ['giornate.leggi', 'consegne.leggi'],
  'utenti.crea':               ['utenti.leggi', 'tipi_account.leggi'],
  'utenti.modifica':           ['utenti.leggi', 'tipi_account.leggi'],
  'utenti.elimina':            ['utenti.leggi'],
};

/**
 * Verifica se l'utente corrente ha un dato permesso.
 * Il superadmin bypassa sempre.
 */
export function hasPermesso(permesso) {
  if (currentUser.is_superadmin) return true;
  return currentUser.permessi.includes(permesso);
}

/**
 * Ritorna la lista dei permessi mancanti (dipendenze non soddisfatte)
 * per un dato permesso, dato un set di permessi attualmente selezionati.
 */
export function getMissingDeps(permessoId, permessiSelezionati) {
  const deps = DIPENDENZE[permessoId] || [];
  return deps.filter(d => !permessiSelezionati.includes(d));
}

/**
 * Raggruppa i permessi per gruppo.
 */
export function getPermessiPerGruppo() {
  const gruppi = {};
  for (const p of PERMESSI) {
    if (!gruppi[p.gruppo]) gruppi[p.gruppo] = [];
    gruppi[p.gruppo].push(p);
  }
  return gruppi;
}
