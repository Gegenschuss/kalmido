// 2.208.0 UI tests (#2771): the area "Tasks" is called "Projects", own container (start.sh), jsdom.
// freelancer-matrix: n/a (no new route; alice has no organisation)
// - the bar of the areas, the panel's head, the phone's drawer row, the tab bar item and the start page choice say Projects,
//   the area's icon is the folder with a tick (proj), not the tick of a single task
// - single entries stay tasks: the key Tasks keeps its text (German: Aufgaben), the area takes Projects (Projekte)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/lists', {name: 'Harbour', kind: 'project'});

  // ================= computer: the bar and the panel
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  const btn = await until(() => d.querySelector('#srail [data-sbb="tasks"]'));
  check(btn?.querySelector('.srbn')?.textContent === 'Projects', 'the bar: the area is called Projects ' + btn?.textContent);
  check(w.eval(`P.proj`) && btn?.querySelector('svg')?.innerHTML === w.eval(`P.proj`) && btn.querySelector('svg').innerHTML !== w.eval(`P.done`), 'the bar: icon proj, not the tick');
  check(await until(() => d.querySelector('#side .sbbpt')?.textContent.trim() === 'Projects'), 'the panel head: Projects ' + d.querySelector('#side .sbbpt')?.textContent);
  check(w.eval(`tabItem('m:tasks').label`) === 'Projects' && w.eval(`MODS[0][1]`) === 'proj', 'the tab bar item of the area: Projects with icon proj');
  check(w.eval(`tr('Tasks')`) === 'Tasks', 'the key Tasks stays for real tasks');

  // ================= German: Projekte for the area, Aufgaben for the rest
  await call('PATCH', '/api/settings', {lang: 'de'});
  w.close();
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  check(await until(() => d.querySelector('#srail [data-sbb="tasks"] .srbn')?.textContent === 'Projekte'), 'German bar: Projekte ' + d.querySelector('#srail [data-sbb="tasks"] .srbn')?.textContent);
  check(w.eval(`tr('Tasks')`) === 'Aufgaben' && w.eval(`tr('Projects')`) === 'Projekte', 'German: Tasks stays Aufgaben, the area is Projekte');
  w.close();

  // ================= phone: the drawer's row of the areas
  w = await boot({user: 'alice', hash: 'inbox', mobile: true}); d = w.document;
  const mb = await until(() => d.querySelector('#side .sbmr [data-sbb="tasks"]'));
  check(mb && /Projekte/.test(mb.textContent) && mb.querySelector('svg')?.innerHTML === w.eval(`P.proj`), 'phone drawer: Projekte with icon proj ' + mb?.textContent);
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
