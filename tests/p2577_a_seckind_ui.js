// kalmido-suite: fresh
// 2.577.0 B (#3354) UI tests, own container (start.sh), jsdom: the column menu and the filter; the behaviour as a person
// without an organisation is in p2577_a_seckind_api_test.py. Invented names only.
// - the column menu of the board offers "Meaning…", the choice reaches the server, Undo takes it back
// - a saved filter by meaning: the dialog offers it once a column has one (a condition row, 2.521.0), filterMatch follows status and column
// - a drop on a done column (taskToSection, the same request as a drag): the card leaves the open tasks
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login, errs, until, undoToast} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ck = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['kanban', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const l = await call('POST', '/api/lists', {name: 'Board', view: 'kanban'});
  await call('PATCH', '/api/lists/' + l.id, {view: 'kanban'});
  const a = await call('POST', '/api/sections', {list_id: l.id, name: 'Doing'});
  const b = await call('POST', '/api/sections', {list_id: l.id, name: 'Finished'});
  const t = await call('POST', '/api/tasks', {title: 'Card', list_id: l.id, section_id: a.id});
  const w = await boot({user: 'alice', hash: 'l/' + l.id}), d = w.document;
  const head = await until(() => d.querySelector(`.khead[data-ksec="${b.id}"] [data-act="section-menu"]`));
  check(!!head, 'the column head has its menu');
  click(w, head);
  const items = () => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')];
  const it = await until(() => items().find(x => x.textContent.includes('Meaning…')));
  check(!!it, 'the menu offers Meaning…');
  click(w, it);
  const done = await until(() => items().find(x => x.textContent.includes('Done')));
  check(!!done && items().length === 6, 'five meanings and none ' + items().length);
  click(w, done);
  check(await until(async () => (await call('GET', '/api/state')).sections.find(s => s.id === b.id)?.kind === 'done'), 'the server has the meaning');
  check(await until(() => w.eval(`S.sections.find(s => s.id === ${b.id}).kind === 'done'`)), 'the client too');
  await undoToast(w, /Meaning of/);
  check(await until(async () => (await call('GET', '/api/state')).sections.find(s => s.id === b.id)?.kind === ''), 'Undo takes it back');
  // 2.997.0 (#5620): the Undo is the server's step (#5255 stage 7); the app learns the old meaning by its reload (histRedraw) -
  // wait for that end state before setting it again, else sk_set still sees 'done' and sends nothing (the drop below then
  // does not complete the card)
  check(await until(() => w.eval(`!HIST.busy && S.sections.find(s => s.id === ${b.id}).kind === ''`)), 'the client shows it taken back');
  await w.eval(`sk_set(${b.id}, 'done')`);
  check(await until(async () => (await call('GET', '/api/state')).sections.find(s => s.id === b.id)?.kind === 'done'), 'set again: the server has it');  // 2.997.0 (#5620)
  // ---- the filter
  check(w.eval(`filterMatch(S.tasks.get(${t.id}), {kinds: ['open']})`), 'an open task in a column without a meaning counts as open');
  check(!w.eval(`filterMatch(S.tasks.get(${t.id}), {kinds: ['done']})`), '... not as done');
  await w.eval(`sk_set(${a.id}, 'progress')`);
  check(w.eval(`filterMatch(S.tasks.get(${t.id}), {kinds: ['progress']})`), 'the column counts');
  // 2.577.0 (#3354): the dialog of condition rows (fltdlg.js, 2.521.0) offers the meaning as a "what" with its five values
  w.eval('filterModal()');
  const fmd = await until(() => d.querySelector('.modal [data-m="cond-add"]')?.closest('.modal'));
  click(w, fmd && fmd.querySelector('[data-m="cond-add"]'));
  const fsel = fmd && fmd.querySelector('.fcond .fc-f');
  check(fsel && [...fsel.options].some(o => o.value === 'kind'), 'the filter dialog offers the meanings');
  if (fsel) { fsel.value = 'kind'; fsel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  click(w, fmd && fmd.querySelector('.fcond .fc-v'));
  const kp = await until(() => d.querySelector('#pop:not(.hidden) [role="menuitemcheckbox"]') && d.querySelector('#pop'));
  const kv = kp ? [...kp.querySelectorAll('[role="menuitemcheckbox"]')].map(x => x.textContent.trim()) : [];
  check(kv.length === 5 && kv.includes('In progress'), 'five meanings to choose ' + kv);
  click(w, kp && [...kp.querySelectorAll('[role="menuitemcheckbox"]')].find(x => x.textContent.trim() === 'In progress'));
  check(await until(() => /1 task matches/.test(fmd.querySelector('#f-count').textContent)), 'the count follows the meaning ' + fmd?.querySelector('#f-count')?.textContent);
  check(w.eval(`filterMatch(S.tasks.get(${t.id}), {op: 'and', conds: [{f: 'kind', op: 'nin', v: ['progress']}]})`) === false, '"is none of" a meaning');
  d.querySelector('.modal [data-m="close"]')?.click();
  // ---- a drop on the done column
  await w.eval(`taskToSection(${t.id}, ${b.id})`);
  check(await until(() => w.eval(`S.tasks.get(${t.id})?.status === 2 || !openTasks().some(x => x.id === ${t.id})`)), 'the card is completed');
  check((await call('GET', '/api/tasks/' + t.id)).status === 2, 'the server says completed');
  check(w.eval(`filterMatch(S.tasks.get(${t.id}) || {status: 2}, {kinds: ['done']})`), 'filterMatch follows the status');
  check(!errs.length, 'no script errors ' + errs.slice(0, 2));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack); process.exit(1); });
