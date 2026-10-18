// 2.89.0 part A UI smoke test (#1916), own container (start.sh): part A builds no screen (the tables view is part B), so this
// only checks that the logged-in app loads without script errors with the module "sheets" on, and that the app's own session
// reaches the tables API (create, read a formula's value, the area counter of /api/version moves). P289A_NOSTART=1 = running.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P289A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,sheets'});
  const v0 = await call('GET', '/api/version');
  const s = await call('POST', '/api/sheets', {title: 'Smoke', space: 'private'});
  check(s.status === 201 && s.columns.length === 3 && s.rows.length === 10, 'a private table with 3 columns, 10 rows ' + JSON.stringify(s).slice(0, 200));
  const r = await call('PUT', `/api/sheets/${s.id}/cells`, {cells: [{cell: 'A1', raw: '2'}, {cell: 'A2', raw: '=A1*21'}]});
  check(r.status === 200 && r.cells.some(c => c.addr === 'A2' && c.value === 42 && c.display === '42'), 'a formula answers its value ' + JSON.stringify(r).slice(0, 300));
  const v1 = await call('GET', '/api/version');
  check(v1.a && v0.a && v1.a.sheets > (v0.a.sheets || 0), 'the area counter "sheets" moves ' + JSON.stringify({v0: v0.a, v1: v1.a}));
  const list = await call('GET', '/api/sheets?space=private');
  check(list.sheets && list.sheets.some(x => x.id === s.id && x.title === 'Smoke'), 'the index lists it');

  const w = await boot({user: 'alice'});
  await sleep(500);
  check(!!w.document.querySelector('#side'), 'the app loads with the module on');
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
