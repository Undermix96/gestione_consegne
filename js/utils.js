/**
 * utils.js — Funzioni di utilità generica e rendering UI atomico
 *
 * Nessuna dipendenza da store o api: funzioni pure o
 * funzioni che toccano solo il DOM in modo isolato.
 */

import { db, SQ_COLORS } from './store.js';

// ── ID & Date ────────────────────────────────────

export function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

export function fmtDate(d) {
  if (!d) return '—';
  // I dati arrivano dal server e finiscono spesso in innerHTML: un valore che non è una data
  // AAAA-MM-GG viene mostrato come testo semplice (escapato), mai interpretato come HTML.
  if (typeof d !== 'string' || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}/.test(d)) return escHtml(d);
  const [y, m, g] = d.slice(0, 10).split('-');
  return `${g}/${m}/${y}`;
}

export function today() {
  return new Date().toISOString().slice(0, 10);
}

export function isPast(dateStr) {
  if (!dateStr) return false;
  return dateStr < today();
}

// ── HTML escaping ────────────────────────────────

export function escHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Badge / Pill HTML ────────────────────────────

export function statoPill(stato) {
  const map = {
    attesa:           ['pill-wait',   '⏳', 'In attesa'],
    in_attesa:        ['pill-wait',   '⏳', 'In attesa'],
    da_confermare:    ['pill-wait',   '📞', 'Da confermare'],
    programmata:      ['pill-sched',  '📌', 'Programmata'],
    completata:       ['pill-done',   '✅', 'Completata'],
    annullata:        ['pill-cancel', '✕',  'Annullata'],
    da_riprogrammare: ['pill-cancel', '🔄', 'Da riprogrammare'],
  };
  const [cls, icon, label] = map[stato] || map['attesa'];
  return `<span class="pill ${cls}"><span class="dot"></span>${icon} ${label}</span>`;
}

export function tipoBadge(tipo) {
  const map = {
    consegna:        ['tipo-consegna',    '📦 Solo consegna'],
    installazione:   ['tipo-installaz',   '🔧 Installaz. semplice'],
    // ⚠️ 'incasso' mantenuto solo per retrocompatibilità — non più selezionabile dall'utente
    incasso:         ['tipo-incasso',     '🔩 Incasso - Muro - SBS'],
    // nuovi tipi (da versione con articoli separati per tipo installazione)
    ins_incasso:     ['tipo-ins-incasso', '🔩 Installazione ad Incasso'],
    ins_muro:        ['tipo-ins-muro',    '🧱 Installazione a Muro'],
    ins_sbs:         ['tipo-ins-sbs',     '↔️ Installazione Side-by-Side'],
  };
  const [cls, label] = map[tipo] || ['tipo-consegna', escHtml(tipo || '—')];
  return `<span class="tipo-badge ${cls}">${label}</span>`;
}

// Le giornate referenziano la squadra per id (giornata.squadra_id): nome e colore si cercano in db.squadre.
// Senza il permesso squadre.leggi la lista è vuota: il badge semplicemente non si mostra.
export function findSquadra(squadraId) {
  return squadraId ? (db.squadre || []).find(s => s.id === squadraId) || null : null;
}

export function getSquadraColorIndex(squadraId) {
  const sq = findSquadra(squadraId);
  return sq ? (sq.colorIdx ?? 0) : -1;
}

export function sqBadgeHtml(squadraId) {
  const sq = findSquadra(squadraId);
  if (!sq) return '';
  return `<span class="sq-badge sq-c${sq.colorIdx ?? 0}">${escHtml(sq.nome)}</span>`;
}

// ── Articoli helpers ─────────────────────────────

export function articoliLabel(c) {
  if (c.articoli && c.articoli.length > 0) {
    return c.articoli.map(a => a.tipo || a.codice || a.desc || '—').join(', ');
  }
  return c.tipoProdotto || '—';
}

export function tipiConsegnaBadges(c) {
  let tipi;
  if (c.articoli && c.articoli.length > 0) {
    // ordine per "peso" decrescente: i tipi di installazione specifica prima, poi semplice, poi consegna
    const order = ['incasso', 'ins_incasso', 'ins_muro', 'ins_sbs', 'installazione', 'consegna'];
    const seen  = new Set(c.articoli.map(a => a.tipoConsegna || 'consegna'));
    tipi = order.filter(t => seen.has(t));
  } else if (c.tipoConsegna) {
    tipi = [c.tipoConsegna];
  } else {
    tipi = ['consegna'];
  }
  return tipi.map(t => tipoBadge(t)).join(' ');
}

export function squadraBadgeForConsegna(cid) {
  const g = db.giornate.find(x => (x.consegneIds || []).includes(cid));
  return (g && sqBadgeHtml(g.squadra_id)) || '<span style="color:var(--muted);font-size:11px;">—</span>';
}

// ── Toast ────────────────────────────────────────

let _toastTimer = null;

export function toast(msg) {
  const el = document.getElementById('toast');
  // Cancella il timer precedente: ogni nuovo toast reimposta il countdown
  if (_toastTimer) {
    clearTimeout(_toastTimer);
    _toastTimer = null;
  }
  el.textContent = msg;
  el.classList.add('show');
  _toastTimer = setTimeout(() => {
    el.classList.remove('show');
    _toastTimer = null;
  }, 2800);
}

// ── Modal helpers ────────────────────────────────

export function openModal(id)  { document.getElementById(id).classList.add('open'); }
export function closeModal(id) { document.getElementById(id).classList.remove('open'); }
