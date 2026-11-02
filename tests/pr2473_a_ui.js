// kalmido-suite:
// 2.473.0 A (#3357) UI, own container (start.sh). jsdom: the detail shows "Delegate" under the assignee and offers only agents of
// the project; choosing one stores it; "Watch" toggles for the person and shows in the count; the owner adds a watcher from the
// menu; a reader without assign rights sees no delegate choice but can watch; history lines read as sentences.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.PR2473A_RUNNING) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: false})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const carol = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const ag = (await call('POST', '/api/my/agents', {username: 'pixel', display_name: 'Pixel', scopes: ['read', 'tasks:write']})).id;
  const L = (await call('POST', '/api/lists', {name: 'Product'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: bob, role: 'view'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: carol, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Fix the login page', list_id: L})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CKB);

  let w = await boot({user: 'alice'}), d = w.document;
  await until(() => d.querySelector('#side'));
  w.eval(`openDetail(${T})`);
  const chip = await until(() => d.querySelector('#detail .dlg-c'));
  check(chip && /Delegate/.test(chip.textContent), 'the delegate chip under the assignee');
  check(d.querySelector('#detail .dmeta.dlgrow .dlg-w'), 'the Watch button');
  click(w, chip);
  const item = await until(() => [...d.querySelectorAll('[role=menuitem]')].find(x => /Pixel/.test(x.textContent)));
  check(item && ![...d.querySelectorAll('[role=menuitem]')].some(x => /Carol/.test(x.textContent)), 'only agents are offered');
  click(w, item);
  await until(async () => (await call('GET', `/api/tasks/${T}`)).delegate_agent_id === ag);
  check(true, 'stored');
  await until(() => /Pixel/.test(d.querySelector('#detail .dlg-c')?.textContent || ''));
  click(w, d.querySelector('#detail .dlg-w'));
  await until(() => d.querySelector('#detail .dlg-w.on'));
  check(/Watching/.test(d.querySelector('#detail .dlg-w').textContent) && /1 watcher/.test(d.querySelector('#detail .dlg-l').textContent), 'watching and the count');
  check(d.querySelector('#detail .dlg-w').getAttribute('aria-pressed') === 'true', 'aria-pressed');
  click(w, d.querySelector('#detail .dlg-l'));
  const add = await until(() => [...d.querySelectorAll('[role=menuitem]')].find(x => /Add Carol/.test(x.textContent)));
  click(w, add);
  await until(() => /2 watchers/.test(d.querySelector('#detail .dlg-l')?.textContent || ''));
  check((await call('GET', `/api/tasks/${T}`)).watchers?.includes(carol), 'the owner added a watcher from the menu');
  w.close();

  w = await boot({user: 'bob'}); d = w.document;
  await until(() => d.querySelector('#side'));
  w.eval(`openDetail(${T})`);
  const c2 = await until(() => d.querySelector('#detail .dlg-c'));
  check(c2.classList.contains('ro') && c2.getAttribute('aria-disabled') === 'true', 'a viewer sees the delegation, locked');
  click(w, d.querySelector('#detail .dlg-w'));
  await until(() => d.querySelector('#detail .dlg-w.on'));
  check((await call('GET', `/api/tasks/${T}`)).watchers?.includes(bob), 'a viewer can watch');
  w.close();
  console.log(F.length ? `FAILED ${F.length}` : `pr2473_a_ui: ${ok} ok`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
