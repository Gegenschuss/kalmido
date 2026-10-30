// 2.46.1 UI tests, lead (#1634 subtasks typed fast), own container (start.sh). jsdom:
// - three subtasks typed without a pause while the server answers slowly: all three arrive complete and in order
// - what is typed while a subtask is being saved stays in the (rebuilt) field, nothing is cut off
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Flat'})).id;
  const P = (await call('POST', '/api/tasks', {title: 'Kitchen', list_id: L})).id;

  // #1634: the field is rebuilt by renderDetail() after each save; a slow POST used to swallow what was typed meanwhile
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const f0 = w.fetch;
  w.fetch = (u, o = {}) => String(u).includes('/api/tasks') && o.method === 'POST' ? sleep(450).then(() => f0(u, o)) : f0(u, o);
  w.eval(`openDetail(${P})`); await until(() => d.querySelector('#d-sub'));
  const type = (v) => { const f = d.querySelector('#d-sub'); f.focus(); f.value = v; f.dispatchEvent(new w.Event('input', {bubbles: true})); return f; };
  key(w, type('Change the bulb'), 'Enter');
  await sleep(60);
  key(w, type('Fix the switch'), 'Enter');  // second Enter while the first is still saving
  await sleep(60);
  type('Paint the wall');  // typed, no Enter yet: must survive the re-render(s)
  await sleep(700);
  check(d.querySelector('#d-sub')?.value === 'Paint the wall', '#1634: text typed while saving stays in the rebuilt field: ' + d.querySelector('#d-sub')?.value);
  key(w, d.querySelector('#d-sub'), 'Enter');
  await until(async () => (await call('GET', '/api/state')).tasks?.filter(t => t.parent_id === P).length >= 3, 60);
  const subs = (await call('GET', '/api/state')).tasks.filter(t => t.parent_id === P).sort((a, b) => a.id - b.id).map(t => t.title);
  check(JSON.stringify(subs) === JSON.stringify(['Change the bulb', 'Fix the switch', 'Paint the wall']), '#1634: three subtasks, complete and in order: ' + JSON.stringify(subs));
  await sleep(700);
  check(d.querySelector('#d-sub')?.value === '' && d.activeElement === d.querySelector('#d-sub'), '#1634: the field is empty again and keeps the focus');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
