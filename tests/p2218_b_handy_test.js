// 2.218.0 B (#2801, #2805): phone messages and hit areas; static check of the shipped code and rules (no app start).
const fs = require('fs'), path = require('path'), vm = require('vm');
const rd = f => fs.readFileSync(path.join(__dirname, '..', f), 'utf8');
const app = rd('static/app.css'), ev = rd('static/js/events.js'), und = rd('static/js/undo.js');
let ok = 0; const F = [];
const check = (c, w) => { if (c) ok++; else { F.push(w); console.log('FAIL:', w); } };
// --- #2801
const m = ev.match(/function toastClip\(s, n = 28\) \{[^\n]*\}/);
check(!!m, '#2801: toastClip exists');
if (m) {
  const ctx = {}; vm.runInNewContext(m[0] + ';this.f = toastClip', ctx);
  check(ctx.f('Rechnung schreiben') === 'Rechnung schreiben', '#2801: short title stays');
  const c = ctx.f('Rechnung fuer das grosse Projekt schreiben');
  check(c.length === 28 && c.endsWith('…'), '#2801: long title cut to 28 characters with an ellipsis');
}
check(/toastClip\(tt\)/.test(ev), '#2801: quick-add message cuts the title');
check(/qn\(toastClip\(t\.title\)\)/.test(und), '#2801: swipe / tick message cuts the title, not the verb');
check(/#toast\.one>span\{display:-webkit-box;[^}]*line-clamp:2/.test(app), '#2801: up to two lines');
check(/addEventListener\('hashchange'[^]*?dataset\.page/.test(ev) && /dataset\.page = undo && !label \? toastPage\(\) \|\| '#' : ''/.test(ev), '#2801: undo message ends with its page');  // 2.350.0 D (#3242): an empty hash is '#'
check(/\^#t\\\//.test(ev.slice(ev.indexOf('function toastPage'))), '#2801: an open detail is not another page');
// --- #2805
const off = rd('static/css/office.css'), od = rd('static/js/office_docs.js'), pp = rd('static/js/popovers.js');
check(/\.ofdkinds button\{min-height:2\.75rem\}/.test(off), '#2805: document kind tabs 2.75rem on phones');
check(/\.trow > \.caret::after\{[^}]*inset/.test(app) && /\.qchip:not\(\.dsxwho\)::after\{[^}]*height:2\.75rem/.test(app), '#2805: subtask arrow + recognised words have a 2.75rem area');
check(/\.tsbar \.iconbtn\{min-width:2\.75rem;min-height:2\.75rem\}/.test(app) && /\.chath button\.chmode[^}]*min-height:2\.75rem/.test(app) && /\.chath \.avb::before/.test(app), '#2805: time close, agent chat head areas');
check(/time,\.meta \.dt,[^{]*\{font-family:inherit;font-variant-numeric:tabular-nums\}/.test(app), '#2805: dates and times in the normal font with tabular digits');
check(/f\.matches\('\.numin'\)[^\n]*f\.select\(\)/.test(od), '#2805: number fields select on focus');
check(/data-d="\$\{d\}" aria-label="\$\{esc\(pd\(d\)\.toLocaleDateString\(LOCALE\(\), \{weekday: 'long'/.test(pp), '#2805: date sheet days carry the full date');
console.log(F.length ? `FAILED ${F.length}` : `p2218_b_handy: ${ok} checks passed`); process.exit(F.length ? 1 : 0);
