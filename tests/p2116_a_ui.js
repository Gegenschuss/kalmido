// 2.116.0 UI test, part A (#2063): the trash period in the trash view, own container (start.sh). jsdom:
// - the trash says the period from the server ("Tasks in the trash are deleted for good after 30 days.")
// - every row says the days left (deleted now: 30, deleted 10 days ago: 20)
// P2116A_NOSTART=1 = the container is running.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2116A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const sql = (q, args = []) => execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(args)]);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments'});
  const L = (await call('POST', '/api/lists', {name: 'Home', org_id: null})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Deleted now', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Deleted ten days ago', list_id: L})).id;
  for (const t of [T1, T2]) await call('DELETE', `/api/tasks/${t}`);
  const ago = new Date(Date.now() - 10 * 864e5).toISOString().replace(/\.\d+Z$/, '+00:00');
  sql('UPDATE tasks SET deleted_at=? WHERE id=?', [ago, T2]);
  const j = await call('GET', '/api/tasks?scope=trash');
  check(j.days === 30 && j.tasks.length === 2, '#2063: the trash page says the period ' + JSON.stringify({days: j.days, n: (j.tasks || []).length}));

  const w = await boot({user: 'alice'});
  const d = w.document;
  w.location.hash = '#trash';
  await until(() => w.eval('S.route.key') === 'trash' && (w.eval('S.extra || []')).length === 2 && d.querySelector('#view .ttphint'));
  const hint = d.querySelector('#view .ttphint');
  check(hint && /deleted for good after 30 days/.test(hint.textContent), '#2063: the hint with the period: ' + (hint ? hint.textContent : 'none'));
  const left = id => (d.querySelector(`#view [data-id="${id}"] .ttpleft`) || {}).textContent || '';
  check(/\b30 days left/.test(left(T1)), '#2063: deleted now = 30 days left: ' + left(T1));
  check(/\b20 days left/.test(left(T2)), '#2063: deleted 10 days ago = 20 days left: ' + left(T2));
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
