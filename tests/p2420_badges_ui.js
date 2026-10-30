// kalmido-suite: after=appearance_ui nodata
// 2.420.0 A (#3498): badges and empty states follow one rule each. No browser, no server: the stylesheets are read as they are
// (static/app.css + static/css/*.css) and the declarations of the rules are checked:
// - tag level (small labels): font-size var(--fs-xs), min height 1.125rem, radius var(--r-s)
// - chip level (pills, clickable): font-size var(--fs-s), radius 99rem (no 9999px / 62rem / 1.25rem)
// - empty state in a page: .empty centred, var(--fs-m), 3rem; in a side part / popup (.empty.sm and the special classes): 1.5rem
const fs = require('fs');
const path = require('path');
const SRC = process.env.KALMIDO_SRC || path.join(__dirname, '..');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const st = path.join(SRC, 'static');
const css = [fs.readFileSync(path.join(st, 'app.css'), 'utf8'), ...fs.readdirSync(path.join(st, 'css')).filter(f => f.endsWith('.css')).map(f => fs.readFileSync(path.join(st, 'css', f), 'utf8'))].join('\n').replace(/\/\*[\s\S]*?\*\//g, '');
// the declarations of the LAST plain rule whose selector list is exactly `.name` (or the given selector)
const rule = sel => {
  const esc = sel.replace(/[.\[\]()]/g, '\\$&');
  const all = [...css.matchAll(new RegExp('(?:^|[}\\s,])' + esc + '\\s*\\{([^}]*)\\}', 'g'))].map(m => m[1]);
  const o = {};
  for (const body of all) for (const d of body.split(';')) { const i = d.indexOf(':'); if (i > 0) o[d.slice(0, i).trim()] = d.slice(i + 1).trim(); }
  return o;
};
const size = (o, k) => o[k] || (o.font || '').split(/\s+/).find(x => x.startsWith('var(--fs-'));

for (const c of ['tpo-tag', 'abtag', 'orr-tag', 'dc-tag', 'devtag', 'rotag', 'nwl-tag', 'abo-tag', 'kz-tag']) {
  const r = rule('.' + c);
  check(size(r, 'font-size') === 'var(--fs-xs)' || /var\(--fs-xs\)/.test(r.font || ''), `tag .${c}: font-size var(--fs-xs) (${r['font-size'] || r.font})`);
  check(r['min-height'] === '1.125rem' || r.height === '1.125rem', `tag .${c}: height 1.125rem`);
  check(r['border-radius'] === undefined || r['border-radius'] === 'var(--r-s)', `tag .${c}: radius var(--r-s) (${r['border-radius']})`);
}
for (const c of ['aichip', 'ppchip', 'evchip', 'bmtag', 'vdrchip', 'cfpill', 'linkchip', 'nchip', 'kz-chip']) {
  const r = rule('.' + c);
  check(r['font-size'] === 'var(--fs-s)', `chip .${c}: font-size var(--fs-s) (${r['font-size']})`);
  check(r['border-radius'] === '99rem', `chip .${c}: radius 99rem (${r['border-radius']})`);
}
check(!/border-radius:\s*(9999px|999rem|62rem|62\.5rem)/.test(css), 'no 9999px / 999rem / 62rem radius left');

const emp = rule('.empty');
check(/3rem/.test(emp.padding || '') && emp['text-align'] === 'center' && emp['font-size'] === 'var(--fs-m)', 'page empty state: 3rem, centred, --fs-m');
check(rule('.empty.sm').padding === '1.5rem 1rem', '.empty.sm: 1.5rem');
for (const c of ['pempty', 'bpempty', 'fempty', 'cmempty', 'stempty', 'povempty', 'vdrempty', 'abscempty']) {
  const r = rule('.' + c);
  check(r.padding === '1.5rem 1rem' && r['font-size'] === 'var(--fs-m)', `side/popup empty .${c}: 1.5rem, --fs-m (${r.padding} / ${r['font-size']})`);
}
for (const c of ['rm-empty', 'abo-empty']) {
  const r = rule('.' + c);
  check(r.padding === '3rem 1rem' && r['font-size'] === 'var(--fs-m)' && !/dashed/.test(r.border || ''), `page empty .${c}: 3rem, --fs-m, no dashed frame`);
}
console.log(`${ok} ok, ${F.length} failed`);
process.exit(F.length ? 1 : 0);
