// 2.223.0 B UI tests (#2819, #2822): link base rule, one empty-state pattern, small desktop fixes, own container (start.sh), jsdom.
// freelancer-matrix: n/a (no new route; alice has no organisation, every check runs without one)
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, json: await r.json().catch(() => null)}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const src = f => fs.readFileSync(path.join(__dirname, '..', 'static', f), 'utf8');

(async () => {
  // ---- static: the rules live where the page always has them
  const css = src('app.css'), off = src('css/office.css');
  check(/^a\{color:var\(--accent\);text-decoration:none\}/m.test(css), '#2819: app.css has the base rule for links');
  check(/^\.oimlink a\{color:var\(--muted\)/m.test(css) && /^\.oimlink\.e a\{color:var\(--accent\)\}/m.test(css), '#2819: the .oimlink rules are in app.css');
  check(!/\.oimlink/.test(off), '#2819: office.css has no .oimlink rule any more');
  check(/\.fwhen\.rvwhen\{font-family:var\(--sans\)/.test(css), '#2822: review dates in plain type');
  check(/\.abcrumbs \.linkbtn\{color:var\(--muted\);text-decoration:none\}/.test(css) && /\.lnlock\{text-decoration:none\}/.test(css), '#2822: path line and quiet link rows without underline');
  check(/\.srb \.srbn\{[^}]*white-space:normal[^}]*line-clamp:2/.test(css), '#2822: area bar labels wrap to two lines');
  check(/<span>\$\{tr\('Add'\)\}<\/span>/.test(src('js/bookmarks.js')) && /<span>\$\{tr\('Add'\)\}<\/span>/.test(src('js/readlater.js')), '#2822: bookmarks and read-later button says Add');
  check(/lifeWhen/.test(src('js/life.js')) && /rvwhen/.test(src('js/life.js')), '#2822: review rows use the plain date');

  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const l = (await call('POST', '/api/lists', {name: 'Harbour', kind: 'project'})).json;

  // ---- computer: an empty project list shows the symbol pattern, not the bot figure
  let w = await boot({user: 'alice', hash: 'l/' + l.id}), d = w.document;
  const em = await until(() => d.querySelector('#view .empty.nempty'));
  check(em && em.querySelector('svg.i') && !em.querySelector('svg.bot') && /No tasks/.test(em.textContent), '#2822: "No tasks." = symbol + sentence, no bot ' + em?.outerHTML?.slice(0, 120));
  check(w.eval(`symEmpty('note', 'X', 'Y')`).includes('nempty') && !w.eval(`symEmpty('note', 'X')`).includes('<span>'), '#2822: symEmpty draws symbol, title, optional hint');
  // the all-done moment keeps the bot figure
  check(w.eval(`o3c_empty('All done for today.', '', 'erledigt')`).includes('class="bot'), '#2822: all-done keeps the bot figure');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
