// Controlli statici del frontend e test di sha256.js. Girano con Node in Docker (compose.test.yaml,
// servizio "jstests"): Node serve solo ai test, l'app non ne ha bisogno.
//
//   docker compose -f compose.test.yaml run --rm jstests
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = process.env.APP_ROOT || '/app';
const JS_DIR = join(ROOT, 'js');
const files = readdirSync(JS_DIR).filter(f => f.endsWith('.js')).sort();
const html = readFileSync(join(ROOT, 'index.html'), 'utf8');
const src = Object.fromEntries(files.map(f => [f, readFileSync(join(JS_DIR, f), 'utf8')]));

let failures = 0;
const fail = msg => { failures++; console.log('  ✗ ' + msg); };
const ok = msg => console.log('  ✓ ' + msg);
const section = t => console.log('\n' + t);

// ── 1. sintassi (moduli ES) ──────────────────────────────────────────────────
section('Sintassi dei moduli');
const tmp = mkdtempSync(join(tmpdir(), 'gc_js_'));
writeFileSync(join(tmp, 'package.json'), '{"type":"module"}');
mkdirSync(join(tmp, 'js'));
let syntaxOk = true;
for (const f of files) {
  copyFileSync(join(JS_DIR, f), join(tmp, 'js', f));
  try {
    execFileSync(process.execPath, ['--check', join(tmp, 'js', f)], { stdio: 'pipe' });
  } catch (e) {
    syntaxOk = false;
    fail(`${f}: ${String(e.stderr || e.message).split('\n').slice(0, 4).join(' | ')}`);
  }
}
if (syntaxOk) ok(`${files.length} file senza errori di sintassi`);

// ── 2. import/export coerenti e nessun ciclo ─────────────────────────────────
section('Import, export e dipendenze');
const stripComments = s => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1');
const exportsOf = {};
for (const f of files) {
  const s = stripComments(src[f]);
  const names = new Set();
  for (const m of s.matchAll(/export\s+(?:async\s+)?(?:function\*?|class)\s+(\w+)/g)) names.add(m[1]);
  for (const m of s.matchAll(/export\s+(?:const|let|var)\s+(\w+)/g)) names.add(m[1]);
  for (const m of s.matchAll(/export\s*\{([^}]*)\}/g)) {
    for (const n of m[1].split(',')) { const a = n.trim().split(/\s+as\s+/).pop(); if (a) names.add(a); }
  }
  exportsOf[f] = names;
}
const deps = {};
let importsOk = true;
for (const f of files) {
  deps[f] = new Set();
  const s = stripComments(src[f]);
  for (const m of s.matchAll(/import\s*\{([\s\S]*?)\}\s*from\s*['"]\.\/([\w.-]+)['"]/g)) {
    const target = m[2];
    if (!exportsOf[target]) { importsOk = false; fail(`${f}: importa da ${target}, che non esiste`); continue; }
    deps[f].add(target);
    for (const n of m[1].split(',')) {
      const name = n.trim().split(/\s+as\s+/)[0];
      if (name && !exportsOf[target].has(name)) { importsOk = false; fail(`${f}: ${target} non esporta '${name}'`); }
    }
  }
}
if (importsOk) ok('ogni nome importato esiste nel modulo di origine');
const state = {};
const cycles = [];
const visit = (f, path) => {
  if (state[f] === 2) return;
  if (state[f] === 1) { cycles.push([...path.slice(path.indexOf(f)), f].join(' → ')); return; }
  state[f] = 1;
  for (const d of deps[f] || []) visit(d, [...path, f]);
  state[f] = 2;
};
files.forEach(f => visit(f, []));
if (cycles.length) cycles.forEach(c => fail('dipendenza circolare: ' + c));
else ok('nessuna dipendenza circolare');

// ── 3. funzioni chiamate da onclick & co. esposte su window ──────────────────
section('Gestori inline (onclick, onchange, ...)');
const exposed = new Set();
const assign = src['main.js'].match(/Object\.assign\(window,\s*\{([\s\S]*?)\n\}\);/);
if (assign) {
  for (const line of assign[1].split('\n')) {
    const t = line.replace(/\/\/.*$/, '').trim();
    for (const m of t.matchAll(/(?:^|,)\s*(\w+)\s*(?=,|:|$)/g)) exposed.add(m[1]);
  }
}
for (const f of files) for (const m of src[f].matchAll(/window\.(\w+)\s*=/g)) exposed.add(m[1]);
for (const m of html.matchAll(/(?:^|\n)\s*(?:async\s+)?function\s+(\w+)/g)) exposed.add(m[1]);   // script inline
const handlerRe = /\son(?:click|change|input|blur|focus|submit|keydown|keyup)\s*=\s*"([^"]*)"/g;
const called = new Map();
for (const [name, text] of [['index.html', html], ...files.map(f => [f, src[f]])]) {
  for (const m of text.matchAll(handlerRe)) {
    // le interpolazioni ${...} dei template sono valutate al momento del rendering, non al click
    const corpo = m[1].replace(/\$\{[^}]*\}/g, '');
    for (const c of corpo.matchAll(/(?<![\w.$'])([A-Za-z_]\w*)\s*\(/g)) {
      if (!['if', 'return', 'function', 'confirm', 'alert', 'prompt'].includes(c[1]) && !called.has(c[1])) {
        called.set(c[1], name);
      }
    }
  }
}
let handlersOk = true;
for (const [fn, where] of called) {
  if (!exposed.has(fn)) { handlersOk = false; fail(`${where}: un gestore inline chiama ${fn}(), non esposta su window`); }
}
if (handlersOk) ok(`${called.size} funzioni usate nei gestori inline, tutte esposte su window`);

// ── 4. id richiesti dal codice presenti nell'HTML ────────────────────────────
section('Elementi DOM');
const htmlIds = new Set([...html.matchAll(/\sid\s*=\s*"([^"]+)"/g)].map(m => m[1]));
const dynamicIds = new Set();   // id creati a runtime nei template dei moduli
for (const f of files) for (const m of src[f].matchAll(/\sid\s*=\s*["'`]([^"'`$]+)["'`]/g)) dynamicIds.add(m[1]);
let idsOk = true;
for (const f of files) {
  for (const m of src[f].matchAll(/getElementById\(\s*'([^']+)'\s*\)/g)) {
    if (!htmlIds.has(m[1]) && !dynamicIds.has(m[1])) { idsOk = false; fail(`${f}: getElementById('${m[1]}') non esiste in index.html né nei template`); }
  }
}
if (idsOk) ok('ogni getElementById con id letterale trova un elemento');

// ── 5. sha256.js identico a SHA-256 di riferimento (e quindi a quello di Python) ──
section('sha256.js');
const { sha256 } = await import(pathToFileURL(join(JS_DIR, 'sha256.js')).href);
const campioni = ['', 'abc', 'admin', 'a'.repeat(55), 'a'.repeat(56), 'a'.repeat(63), 'a'.repeat(64), 'a'.repeat(65),
  'x'.repeat(1000), 'password con spazi', 'àèìòù ÀÈÌÒÙ €', 'Zażółć gęślą jaźń', '日本語パスワード', '🔐🙂 emoji',
  'á (combinante)', 'á (precomposto)', 'tab\tnewline\n', 'x'.repeat(100000)];
let shaOk = true;
for (const c of campioni) {
  const atteso = createHash('sha256').update(c, 'utf8').digest('hex');
  if (sha256(c) !== atteso) { shaOk = false; fail(`sha256 diverso da quello di riferimento per ${JSON.stringify(c.slice(0, 20))}`); }
}
for (let i = 0; i < 300; i++) {
  const len = Math.floor(Math.random() * 200);
  let s = '';
  for (let j = 0; j < len; j++) s += String.fromCodePoint(1 + Math.floor(Math.random() * 0xD000));
  if (sha256(s) !== createHash('sha256').update(s, 'utf8').digest('hex')) {
    shaOk = false; fail('sha256 diverso su stringa casuale ' + JSON.stringify(s.slice(0, 20))); break;
  }
}
// il flusso Challenge-Response del server parte da sha256(password): per "admin" deve essere questo
if (sha256('admin') !== '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918') {
  shaOk = false; fail('hash di "admin" diverso da quello atteso dal server');
}
if (shaOk) ok(`${campioni.length} campioni fissi e 300 casuali coincidono con SHA-256 di riferimento`);

console.log(failures ? `\nFALLITO: ${failures} problemi` : '\nESITO: OK');
process.exit(failures ? 1 : 0);
