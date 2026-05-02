/**
 * stampa.js — Stampa PDF della giornata
 */

import { db, currentGiornataId } from './store.js';
import { fmtDate } from './utils.js';

export function stampaPDF() {
  const g = db.giornate.find(x => x.id === currentGiornataId);
  if (!g) return;

  const tipoLabel = {
    consegna:      'Solo consegna',
    installazione: 'Installazione semplice',
    incasso:       'Installazione a incasso/muro',
  };

  const consegne = (g.consegneIds || [])
    .map(cid => db.consegne.find(c => c.id === cid))
    .filter(Boolean);

  const righe = consegne.map((c, i) => {
    const arts = c.articoli && c.articoli.length > 0 ? c.articoli
      : (c.tipoProdotto || c.codiceProdotto
          ? [{ tipoConsegna: c.tipoConsegna, tipo: c.tipoProdotto, codice: c.codiceProdotto, desc: c.descrizioneProdotto }]
          : []);

    const artsHtml = arts.length === 0
      ? `<tr><td colspan="5" style="color:#888;font-style:italic;text-align:center;padding:6px;">Nessun articolo</td></tr>`
      : arts.map((a, j) => `
        <tr>
          <td style="text-align:center;font-weight:700;color:#555;">${arts.length > 1 ? j + 1 : '—'}</td>
          <td>${a.tipo || '—'}</td>
          <td style="font-family:monospace;font-size:10px;">${a.codice || '—'}</td>
          <td>${a.desc || '—'}</td>
          <td style="text-align:center;">${tipoLabel[a.tipoConsegna] || 'Consegna'}</td>
        </tr>`).join('');

    const noteExtra = [
      c.noteAbitazione    ? `<div class="nota"><span class="nota-label">Note abitazione:</span> ${c.noteAbitazione}</div>` : '',
      c.preferenzePeriodo ? `<div class="nota"><span class="nota-label">Preferenze periodo:</span> ${c.preferenzePeriodo}</div>` : '',
      c.note              ? `<div class="nota"><span class="nota-label">Note aggiuntive:</span> ${c.note}</div>` : '',
    ].filter(Boolean).join('');

    return `
    <div class="cons-block">
      <div class="cons-header">
        <div class="cons-num">${i + 1}</div>
        <div class="cons-cliente">
          <div class="cons-nome">${c.cognome || ''} ${c.nome || ''}</div>
          <div class="cons-addr">${c.citta || ''}${c.indirizzo ? ', ' + c.indirizzo : ''}${c.piano ? ' \u2014 Piano: ' + c.piano : ''}</div>
        </div>
        <div class="cons-meta">
          <div><span class="ml">Tel:</span> ${c.tel1 || '—'}${c.tel2 ? ' / ' + c.tel2 : ''}</div>
          <div><span class="ml">Orario:</span> ${c.fasciaOraria || '—'} &nbsp;&nbsp; <span class="ml">RAEE:</span> <strong>${c.raee === 'si' ? 'Si' : 'No'}</strong></div>
        </div>
      </div>
      <table class="art-table">
        <thead>
          <tr>
            <th style="width:28px;">#</th>
            <th>Tipologia</th>
            <th style="width:110px;">Codice</th>
            <th>Descrizione</th>
            <th style="width:105px;">Tipo consegna</th>
          </tr>
        </thead>
        <tbody>${artsHtml}</tbody>
      </table>
      ${noteExtra ? `<div class="note-box">${noteExtra}</div>` : ''}
      <div class="cons-check">
        <span class="chk-item">&#9744; &nbsp;Consegnato</span>
        <span class="chk-item">&#9744; &nbsp;Non consegnato &mdash; Motivo: <span class="motivo-line"></span></span>
      </div>
    </div>`;
  }).join('');

  const html = `<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8"/>
<title>Giornata ${fmtDate(g.data)}${g.squadra ? ' \u2014 ' + g.squadra : ''}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; font-size: 11px; color: #111; background: #fff; }
  .pdf-header { padding: 12px 16px 10px; border-bottom: 3px solid #111; margin-bottom: 14px; display:flex; align-items:baseline; gap:14px; }
  .pdf-header h1 { font-size: 16px; font-weight: 700; }
  .pdf-header .sub { font-size: 11px; color: #555; }
  .pdf-header .sub-right { margin-left:auto; font-size:10px; color:#888; }
  .cons-block { border: 2px solid #555; border-radius: 4px; margin: 0 14px 14px; page-break-inside: avoid; overflow: hidden; }
  .cons-header { display: flex; align-items: stretch; background: #2c2c2c; color: #fff; border-bottom: 2px solid #555; }
  .cons-num { font-size: 22px; font-weight: 700; color: #fff; min-width: 42px; display:flex; align-items:center; justify-content:center; border-right: 2px solid #555; padding: 8px 10px; background: #111; }
  .cons-cliente { flex: 1; padding: 7px 12px; border-right: 2px solid #555; }
  .cons-nome { font-size: 13px; font-weight: 700; color: #fff; }
  .cons-addr { font-size: 10px; color: #ccc; margin-top: 3px; }
  .cons-meta { padding: 7px 12px; font-size: 10px; color: #ddd; display: flex; flex-direction: column; justify-content: center; gap: 4px; min-width: 200px; }
  .ml { font-weight: 700; color: #aaa; }
  .art-table { width: 100%; border-collapse: collapse; font-size: 10.5px; }
  .art-table thead tr { background: #3b4fc8; }
  .art-table th { padding: 5px 8px; text-align: left; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .6px; color: #fff; border-bottom: 2px solid #2a3ab0; }
  .art-table td { padding: 5px 8px; border-bottom: 1px solid #ddd; vertical-align: top; }
  .art-table tbody tr:last-child td { border-bottom: none; }
  .art-table tbody tr:nth-child(even) { background: #f0f2ff; }
  .note-box { padding: 5px 12px; border-top: 2px solid #e6c200; font-size: 10px; color: #333; background: #fffbe6; }
  .nota { margin: 2px 0; }
  .nota-label { font-weight: 700; color: #7a6000; }
  .cons-check { display: flex; gap: 24px; padding: 7px 12px; border-top: 2px solid #555; font-size: 11px; color: #111; background: #e8e8e8; font-weight: 600; }
  .chk-item { display: inline-flex; align-items: center; gap: 4px; }
  .motivo-line { display: inline-block; border-bottom: 1.5px solid #333; min-width: 160px; margin-left: 4px; font-weight: 400; }
  @media print {
    body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .cons-block { break-inside: avoid; }
  }
</style>
</head>
<body>
<div class="pdf-header">
  <h1>Giornata del ${fmtDate(g.data)}${g.squadra ? ' \u2014 ' + g.squadra : ''}</h1>
  <div class="sub">${consegne.length} consegn${consegne.length === 1 ? 'a' : 'e'} programmat${consegne.length === 1 ? 'a' : 'e'}</div>
  <div class="sub-right">Stampato il ${new Date().toLocaleDateString('it-IT')}</div>
</div>
${righe}
</body>
</html>`;

  const win = window.open('', '_blank');
  win.document.write(html);
  win.document.close();
  win.focus();
  setTimeout(() => win.print(), 600);
}
