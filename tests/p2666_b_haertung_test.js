// kalmido-suite: after=p2368_c_api nodata
// 2.666.0 part B (#4074 point 8): tr() for HTML with escaped values, no browser and no server: static/i18n.js as it is runs
// in node with a German dictionary (markup in the translation):
// - trh / trnh escape every inserted value (a name with <img onerror>, quotes, &), the translation keeps its own <b> / <code>;
//   numbers stay as they are; tr / trn stay unchanged (values that are HTML already keep working)
// - the calendar subscription dialog puts the stored link's host into its placeholder through trh (an attribute)
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const read = f => fs.readFileSync(path.join(SRC, 'static', f), 'utf8');

// one top-level declaration of a source file: from `start` to the end of its line (one-liners) or its closing "}" line
function piece(f, start, need = true) {
  const s = read(f), i = s.indexOf('\n' + start);
  if (i < 0) { if (need) throw new Error(`${f}: ${start} not found`); return ''; }
  const one = s.indexOf('\n', i + 1), end = /\{\s*$/.test(s.slice(i + 1, one)) ? s.indexOf('\n}', i + 1) + 2 : one;
  return s.slice(i + 1, end);
}
const code = [
  piece('i18n.js', 'const i18nFmt ='), piece('i18n.js', 'const i18nKey ='), piece('i18n.js', 'function tr('), piece('i18n.js', 'function plOne('),
  piece('i18n.js', 'function trn('), piece('i18n.js', 'const i18nEsc =', false), piece('i18n.js', 'function trh(', false), piece('i18n.js', 'function trnh(', false),
].join('\n');
const ctx = {I18N: {code: 'de', dict: {'{0} invites you': '<b>{0}</b> lädt dich ein', '{0} file': ['{0} Datei von {1}', '{0} Dateien von {1}'],
  'saved ({0}), empty = keep': 'gespeichert ({0}), leer = behalten'}}, I18N_PL: null, i18nPyAsk() {}, LOCALE: () => 'de-DE'};
vm.createContext(ctx);
vm.runInContext(`${code}
globalThis.__t = {tr, trn, trh: typeof trh === 'function' ? trh : null, trnh: typeof trnh === 'function' ? trnh : null};`, ctx);
const T = ctx.__t;
const evil = '<img src=x onerror="alert(1)">&\'';
check(T.trh && T.trnh, '#4074 8: trh and trnh exist');
if (T.trh) {
  const h = T.trh('{0} invites you', evil);
  check(h === '<b>&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;</b> lädt dich ein', `#4074 8: trh escapes the value, keeps the translation's <b> (${h})`);
  check(T.trh('{0} invites you', 42) === '<b>42</b> lädt dich ein', '#4074 8: a number stays as it is');
  check(T.trh('{0} invites you') === '<b>{0}</b> lädt dich ein', '#4074 8: no value = the text as tr gives it');
  const n = T.trnh('{0} file', '{0} files', 2, '<i>Ana</i>');
  check(n === '2 Dateien von &lt;i&gt;Ana&lt;/i&gt;', `#4074 8: trnh escapes the values, the count stays (${n})`);
  check(T.trnh('{0} file', '{0} files', 1, 'Ben') === '1 Datei von Ben', '#4074 8: trnh one form');
}
check(T.tr('{0} invites you', '<b>Ana</b>') === '<b><b>Ana</b></b> lädt dich ein', '#4074 8: tr itself is unchanged (HTML values of callers that escaped them)');

const cal = read('js/calview.js');
check(/placeholder="\$\{trh\('saved \(\{0\}\), empty = keep', x\.url_hint\)\}"/.test(cal), '#4074 8: the subscription dialog puts the link host through trh');
check(!/\$\{tr\('saved \(\{0\}\), empty = keep'/.test(cal), '#4074 8: no unescaped placeholder with the link host left');

console.log(`p2666_b_haertung: ${ok} ok, ${F.length} failed`);
process.exit(F.length ? 1 : 0);
