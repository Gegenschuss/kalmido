// 2.199.0 M (#2768): "Tomorrow" moves a task one more day on every click. jsdom, own container (start.sh).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const task = async id => (await call('GET', '/api/state')).tasks.find(t => t.id === id);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const T = (await call('POST', '/api/tasks', {list_id: L, title: 'Pay the rent', due_time: '09:30'})).id;
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`openDetail(${T})`); await sleep(400);
  const tom = () => d.querySelector('#detail [data-act="due-q"][data-d="1"]');
  const set = async (due, start = null) => { await call('PATCH', `/api/tasks/${T}`, {due, start}); w.eval(`putTask(${JSON.stringify(await task(T))})`); w.eval('render()'); await sleep(100); };
  const step = async (want, what) => { click(w, tom()); check(await until(async () => (await task(T)).due === want), what + ' -> ' + want); };
  check(/each further click/.test(tom().title) && /each further click/.test(tom().getAttribute('aria-label')), 'tooltip names the extra click');
  await step(day(1), 'empty'); // no date yet
  await step(day(2), 'tomorrow'); // 1 -> 2
  check((await task(T)).due_time === '09:30', 'time stays');
  check(/Date: /.test(d.body.textContent) && d.body.textContent.includes(w.eval(`dayLabel('${day(2)}')`)), 'notice shows the new date');
  await set(day(0)); await step(day(1), 'today');
  await set(day(-3)); await step(day(1), 'overdue');
  await set(day(5)); await step(day(6), 'in 5 days');
  await set(day(1), day(1)); await step(day(2), 'start on the old date');
  check((await task(T)).start === day(1), 'start before the new date stays');
  // undo
  await set(day(1)); await step(day(2), 'before undo');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await task(T)).due === day(1)), 'undo restores the old date');
  // menu entry and Shift+T
  await set(day(3));
  w.eval(`quickDueRow(${T}).row[1].fn()`);
  check(await until(async () => (await task(T)).due === day(4)), 'menu entry moves one more day');
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'T', shiftKey: true, bubbles: true, cancelable: true}));
  check(await until(async () => (await task(T)).due === day(5)), 'Shift+T moves one more day');
  // Today unchanged
  await set(day(4)); w.eval(`quickDue(${T}, 0)`);
  check(await until(async () => (await task(T)).due === day(0)), 'Today still sets today');
  w.close();
  console.log(`p2199_m_tomorrow_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
