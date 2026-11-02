// kalmido-suite: fresh
// 2.477.0 (#3938) UI test (jsdom), own container (start.sh): the number of points of the bottom bar follows the width --
// below 600 CSS px 5 (4 + "More"), from 600 px 7 (6 + "More"), from 900 px 9 (8 + "More"); the extra places take the next
// points of the person's own order (nav_menus.tabbar); the hint in Settings names the number of this device.
// freelancer-matrix: settings (alice without an organisation arranges her own bar)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const ORDER = ['s:inbox', 's:today', 's:tomorrow', 's:week', 's:doable', 's:pinned', 's:waiting', 's:all', 's:done', 's:trash', 'search', 'lists'];
const W600 = '(min-width: 600px)', W900 = '(min-width: 900px)';

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', nav_menus: JSON.stringify({tabbar: {order: ORDER}})});

  const bar = async (media, what, n) => {
    const w = await boot({user: 'alice', mobile: true, hash: 'today', media}), d = w.document;
    const ids = () => [...d.querySelectorAll('#tabs button')].map(b => b.dataset.go || b.dataset.act || b.id || b.textContent.trim());
    check(await until(() => d.querySelectorAll('#tabs button').length === n), `${what}: ${n} points (${ids().length}: ${ids().join(' | ')})`);
    check(/More/.test(d.querySelector('#tabs button:last-child')?.textContent || ''), `${what}: the last one is "More"`);
    check(w.eval('tabOverflow().shown.map(t => t.id).join()') === ORDER.slice(0, n - 1).join(), `${what}: the first ${n - 1} of the own order`);
    return w;
  };
  (await bar({}, 'phone (below 600 px)', 5)).close();
  (await bar({[W600]: true}, 'tablet upright (600 px)', 7)).close();
  const w = await bar({[W600]: true, [W900]: true}, 'tablet across (900 px)', 9);
  check(w.eval(`tr('This device fits {0} tabs, the rest goes under “More”.', tabMax())`).includes('9'), 'the hint names the number of this device (9)');
  w.close();

  console.log(`p2477_tabbar_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
