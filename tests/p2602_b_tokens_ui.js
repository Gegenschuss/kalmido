// kalmido-suite: after=p2420_badges_ui nodata
// 2.602.0 (#4816): surfaces use tokens only. No browser, no server: the stylesheets are read as they are.
// - cards and surfaces: radius var(--r-l), border var(--line2), background var(--bg2) where the rule sets one
// - hints, fields, chips: var(--radius) / var(--r-s); no literal radii in the touched rules
// - the undefined var(--r, var(--r-m and var(--hover are gone; calendar month and week share one frame
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

for (const c of ['.abview', '.ablist', '.odban', '.stcard', '.povs', '.arow', '.sttiles div', '.dkbox', '.rkv-sec', '.rkv-card', '.bwcard', '.dpjdoc', '.vdrrow', '.fxk', '.week', '.cal']) {
  const r = rule(c);
  check(r['border-radius'] === 'var(--r-l)', `card ${c}: radius var(--r-l) (${r['border-radius']})`);
  const b = r.border || r['border-top'] || '';
  check(!b || /var\(--line2\)/.test(b) || /dashed/.test(b), `card ${c}: border var(--line2) (${b})`);
}
for (const c of ['.onehint', '.dun-hint', '.bwdlg .bwlocked', '.ofdlocked', '.ofdlnote', '.ltm-pick', '.avlrow', '.abopen', '.vdrtl']) {
  const r = rule(c);
  check(r['border-radius'] === 'var(--radius)' || r['border-radius'] === 'var(--r-s)', `field/hint ${c}: radius token (${r['border-radius']})`);
}
for (const c of ['.pvpct', '.dpvtab', '.dpvag', '.dpvtwrap', '.vdrtc', '.vdrat', '.cal .ev', '.week .ev']) {
  const r = rule(c);
  check(r['border-radius'] === 'var(--r-s)', `chip ${c}: radius var(--r-s) (${r['border-radius']})`);
}
check(!/var\(--(r|r-m|hover)\s*[,)]/.test(css), 'no var(--r / var(--r-m / var(--hover left');
check(/--radius:/.test(css) && /--r-s:/.test(css) && /--r-l:/.test(css) && /--line2:/.test(css) && /--bg3:/.test(css) && /--shadow:/.test(css), 'tokens defined in :root');
// 2.1012.0 (#5690): the budget menu is the shared menu() now (.bgmenul is gone)
console.log(`${ok} ok, ${F.length} failed`);
process.exit(F.length ? 1 : 0);
