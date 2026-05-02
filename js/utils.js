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
  const [y, m, g] = d.split('-');
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
  return (str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
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
    consegna:      ['tipo-consegna',  '📦 Solo consegna'],
    installazione: ['tipo-installaz', '🔧 Installaz. semplice'],
    incasso:       ['tipo-incasso',   '🔩 Incasso/muro'],
  };
  const [cls, label] = map[tipo] || ['tipo-consegna', tipo || '—'];
  return `<span class="tipo-badge ${cls}">${label}</span>`;
}

export function getSquadraColorIndex(nome) {
  if (!nome) return -1;
  const sq = (db.squadre || []).find(s => s.nome === nome);
  return sq ? (sq.colorIdx ?? 0) : 0;
}

export function sqBadgeHtml(nome) {
  if (!nome) return '';
  const idx = getSquadraColorIndex(nome);
  return `<span class="sq-badge sq-c${idx}">${nome}</span>`;
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
    const order = ['incasso', 'installazione', 'consegna'];
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
  if (!g || !g.squadra) return '<span style="color:var(--muted);font-size:11px;">—</span>';
  return sqBadgeHtml(g.squadra);
}

// ── Toast ────────────────────────────────────────

export function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2800);
}

// ── Modal helpers ────────────────────────────────

export function openModal(id)  { document.getElementById(id).classList.add('open'); }
export function closeModal(id) { document.getElementById(id).classList.remove('open'); }
