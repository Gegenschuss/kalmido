// kalmido-suite:
// 2.757.0 UI test (#4501: more folder defaults), own container (start.sh), jsdom. Invented data only.
// - the folder settings have View, Columns / Custom fields / Project tags ("Take from project…"), Repeat reminders, Hours
//   per day, Hourly rate and Show the progress bar; a change saves the folder default
// - "Take from project…" stores the project's columns and shows the new state; "Not set" removes it again
// - "New project" in the folder starts with the folder's view
// P4: a person without an organisation gets the same (freelancer-matrix: lists)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2757U_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEAT = 'kanban,timeline,collab,time,progress,fields';

(async () => {
  await until(() => fetch(B + 'api/health').then(r => r.status < 500, () => false));  // 2.757.0 (#4501): wait for the server, not a fixed time
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: FEAT.split(',')});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'frida: no organisation');

  for (const [u, ck] of [['alice', CA], ['frida', CF]]) {
    const src = await call(ck, 'POST', '/api/lists', {name: 'Source'});
    await call(ck, 'PATCH', `/api/lists/${src.id}`, {columns: ['due', 'prio']});
    await call(ck, 'POST', '/api/lists', {name: 'Seed', folder: 'Clients'});
    const w = await boot({user: u, hash: 'today'}), d = w.document;
    const fp = async () => (await call(ck, 'GET', '/api/folders/props?folder=Clients')).props || {};
    w.eval(`folderPropsModal('Clients')`);
    const vw = await until(() => d.querySelector('#fs-vw'));
    const rows = ['#fs-vw', '#fs-cols', '#fs-flds', '#fs-tags', '#fs-nag', '#fs-dayh', '#fs-rate', '#fs-pg'].filter(s => !d.querySelector(s));
    check(vw && !rows.length, `${u}: the folder settings have the new defaults (missing: ${rows.join(', ')})`);
    if (vw) change(w, vw, 'kanban');
    check(await until(async () => (await fp()).view === 'kanban'), `${u}: the folder default View is saved`);
    const cols = d.querySelector('#fs-cols');
    if (cols) change(w, cols, String(src.id));
    check(await until(async () => JSON.stringify((await fp()).columns) === '["due","prio"]'), `${u}: Take from project… stores the project's columns`);
    const st = await until(() => /2/.test(d.querySelector('[data-fcpst="columns"]')?.textContent || '') && d.querySelector('[data-fcp="columns"] .fsclr:not([hidden])'));
    check(!!st, `${u}: the row shows the new state and "Not set" ` + JSON.stringify(d.querySelector('[data-fcpst="columns"]')?.textContent));
    const rate = d.querySelector('#fs-rate');
    if (rate) change(w, rate, '80');
    check(await until(async () => (await fp()).rate === 80), `${u}: the hourly rate is saved`);
    const clr = d.querySelector('[data-fcp="columns"] .fsclr');
    if (clr) clr.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
    check(await until(async () => !('columns' in await fp())), `${u}: "Not set" removes the columns default`);
    const seed = ((await call(ck, 'GET', '/api/state')).lists || []).find(l => l.name === 'Seed');
    check(seed && seed.view === 'kanban' && seed.rate === 80, `${u}: the project in the folder follows ` + JSON.stringify(seed && {view: seed.view, rate: seed.rate}));
    await until(() => w.eval(`(S.folderProps || {})['Clients']?.view === 'kanban'`));
    w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove())`);
    w.eval(`listModal(0, 'Clients')`);
    const lv = await until(() => d.querySelector('.modal #l-view'));
    check(lv && lv.value === 'kanban', `${u}: New project in the folder starts with the folder's view ${lv && lv.value}`);
    w.close();
  }

  console.log(`p2757_a_folderdefs_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
