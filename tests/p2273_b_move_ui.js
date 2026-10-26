// 2.273.0 B (#3042): moving a task to a project where its people have no access - the toast names what is not carried over
// (and keeps its Undo); Undo brings the person coming along back. A person without an organisation (freelancer-matrix: tasks);
// own container (start.sh, isolated test database).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,family'});
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const L1 = (await call('POST', '/api/lists', {name: 'Shared'})).id, L2 = (await call('POST', '/api/lists', {name: 'Mine'})).id;
  await call('PUT', `/api/lists/${L1}/members`, {email: 'bob@example.com', role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Picnic', list_id: L1})).id;
  const p = await call('PATCH', `/api/tasks/${T}`, {people: [bob.id]});
  check((p.people || []).includes(bob.id), 'setup: bob comes along');
  const w = await boot({user: 'alice', hash: 'l/' + L1}), d = w.document;
  await until(() => d.querySelector(`.trow[data-id="${T}"]`));
  w.eval(`patchUndoable(${T}, {list_id: ${L2}}, tr('Moved to {0}', 'Mine'))`);
  const txt = await until(() => { const t = d.querySelector('#toast:not(.hidden)')?.textContent || ''; return /Not carried over/.test(t) ? t : ''; });
  check(/1 person coming along/.test(txt) && /Undo brings it back/.test(txt), `the toast names what is not carried over: ${txt}`);
  check(!!d.querySelector('#toast:not(.hidden) button'), 'the toast keeps its Undo');
  w.eval('histStep("undo")');
  const back = await until(async () => { const t = await call('GET', `/api/tasks/${T}`); return t.list_id === L1 && (t.people || []).includes(bob.id) ? t : null; });
  check(!!back, 'Undo: the task is back with bob coming along');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
