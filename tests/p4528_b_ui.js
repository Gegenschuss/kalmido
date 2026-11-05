// kalmido-suite:
// 2.550.0 (#4528) UI, own container (start.sh). jsdom: deleting a field in its dialog says it goes into the trash, the toast's
// Undo brings it back with its value; the project settings list a deleted field with "Restore"; the share dialog shows the
// way back for a member added again after a removal, and its question restores the assignment.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P4528BUI_RUNNING) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,fields';
const btn = (d, txt) => [...([...d.querySelectorAll('.modal')].pop()?.querySelectorAll('button') || [])].find(x => x.textContent.trim() === txt);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: false})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const L = (await call('POST', '/api/lists', {name: 'Garden plan', kind: 'project'})).id;
  const FD = (await call('POST', `/api/lists/${L}/fields`, {name: 'Budget', type: 'number'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Order seeds', list_id: L})).id;
  await call('PATCH', `/api/tasks/${T}`, {fields: {[FD]: '12'}});
  const fval = async () => (await call('GET', `/api/tasks/${T}`)).fields?.[FD];
  const hasField = async () => (await call('GET', '/api/state')).fields.some(f => f.id === FD);

  let w = await boot({user: 'alice'}), d = w.document;
  await until(() => d.querySelector('#side'));
  // ---- the field dialog: delete, the toast's Undo
  w.eval(`fieldModal(${L}, fieldById(${FD}), null)`);
  click(w, await until(() => d.querySelector('.modal [data-m="del"]')));
  await until(() => btn(d, 'Delete'));
  check(/goes into the trash with its values/.test([...d.querySelectorAll('.modal')].pop().textContent), 'the question says the field goes into the trash');
  click(w, btn(d, 'Delete'));
  check(await until(async () => !(await hasField())), 'deleted');
  const undo = await until(() => !d.querySelector('#toast').classList.contains('hidden') && /Field deleted/.test(d.querySelector('#toast').textContent) && d.querySelector('#toast button'));
  check(undo && /Undo/.test(undo.textContent), 'the toast offers Undo');
  click(w, undo);
  check(await until(async () => await hasField() && String(await fval()) === '12'), 'Undo: the field and its value are back');
  // ---- the project settings: the deleted field with "Restore"
  await call('DELETE', `/api/fields/${FD}`);
  await w.eval('load().then(() => render())');
  w.eval(`listModal(${L})`);
  const rest = await until(() => d.querySelector('#l-ftrash [data-ftrest]'));
  check(rest && /Budget/.test(d.querySelector('#l-ftrash').textContent) && !d.querySelector('#l-ftrash').hidden, 'the settings list the deleted field');
  click(w, rest);
  check(await until(async () => await hasField() && String(await fval()) === '12'), 'Restore in the settings: back with its value');
  check(await until(() => /Field restored/.test(d.querySelector('#toast').textContent)), 'the toast says so');
  check(await until(() => !d.querySelector('#l-ftrash [data-ftrest]')), 'the trash list is empty again');
  d.querySelectorAll('.modal').forEach(x => x.remove());
  // ---- the share dialog: the way back for a member added again
  await call('PUT', `/api/lists/${L}/members`, {user_id: bob, role: 'edit'});
  await call('PATCH', `/api/tasks/${T}`, {assignee_id: bob});
  await call('DELETE', `/api/lists/${L}/members/${bob}`);
  await call('PUT', `/api/lists/${L}/members`, {user_id: bob, role: 'edit'});
  await w.eval('load().then(() => render())');
  w.eval(`shareModal(${L})`);
  const mm = await until(() => d.querySelector(`.shmodal [data-mmrest="${bob}"]`));
  check(mm && /Restore what Bob had/.test(mm.getAttribute('aria-label') || ''), 'the member row offers the way back');
  click(w, mm);
  await until(() => btn(d, 'Restore'));
  check(/1 assignment/.test([...d.querySelectorAll('.modal')].pop().textContent), 'the question names what comes back');
  click(w, btn(d, 'Restore'));
  check(await until(async () => (await call('GET', `/api/tasks/${T}`)).assignee_id === bob), 'restored: bob is the assignee again');
  check(await until(() => !d.querySelector(`.shmodal [data-mmrest="${bob}"]`)), 'the button is gone after the restore');
  w.close();
  console.log(F.length ? `FAILED ${F.length}` : `p4528_b_ui: ${ok} ok`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
