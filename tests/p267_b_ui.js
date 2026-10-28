// 2.67.0 UI tests, part B (#1865): the dependency chain moves along in the timeline (jsdom, fresh DB). Dragging a bar
// later: the waiting bars slide along as a preview (transform, class dch-ghost), the server moves the chain, the toast
// "2 dependent tasks moved" with one Undo for all; dragging earlier: the chain stays, the toast says so (with Undo);
// the bar menu and the task panel offer it too (one undo step); the list setting (on by default in a new project list,
// off in a plain list; off = no preview, nothing moves). Invented names only.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
// 2.80.1: calendar days, not n * 24 h (shortly after midnight in the week before the clock change, +8 * 24 h landed a day early)
const ds = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const ptr = (w, el, type, x = 0) => {  // jsdom has no PointerEvent: a MouseEvent with pointerType / pointerId
  const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, button: 0, clientX: x, clientY: 10});
  Object.defineProperty(e, 'pointerType', {value: 'mouse'}); Object.defineProperty(e, 'pointerId', {value: 1});
  el.dispatchEvent(e);
};
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const taskOf = async id => (await call('GET', '/api/state')).tasks.find(t => t.id === id);
const toastText = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';
const dates = async id => { const t = await taskOf(id); return `${t.start || ''}..${t.due}`; };
const span = (s, e) => `${ds(s)}..${ds(e)}`;

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const PRJ = (await call('POST', '/api/lists', {name: 'Film shoot', view: 'timeline', kind: 'project'})).id;
  const PLAIN = (await call('POST', '/api/lists', {name: 'Errands'})).id;
  const mk = async (title, start, due) => (await call('POST', '/api/tasks', {title, list_id: PRJ, ...(start != null ? {start: ds(start)} : {}), due: ds(due)})).id;
  const A = await mk('Location scout', 0, 2), Bt = await mk('Set build', 3, 4), Cc = await mk('Shoot day', 6, 7);
  await call('POST', '/api/deps', {task_id: Bt, blocker_id: A});
  await call('POST', '/api/deps', {task_id: Cc, blocker_id: Bt});

  let w = await boot({user: 'alice', hash: 'l/' + PRJ}); let d = w.document;
  const bar = id => d.querySelector(`.tl-bar[data-id="${id}"]`);
  check(await until(() => bar(A) && bar(Bt) && bar(Cc)), 'timeline: three bars');
  const DW = w.eval('tlDW()');

  // ================= drag later: preview, the server moves the chain, one undo
  ptr(w, bar(A), 'pointerdown', 0); ptr(w, d, 'pointermove', 2 * DW);
  check(bar(Bt).classList.contains('dch-ghost') && bar(Bt).style.transform === `translateX(${2 * DW}px)` && bar(Cc).classList.contains('dch-ghost'),
        `preview: the waiting bars slide along (${bar(Bt).style.transform})`);
  ptr(w, d, 'pointermove', 0);
  check(!bar(Bt).classList.contains('dch-ghost') && !bar(Bt).style.transform, 'back to the start: the preview is gone');
  ptr(w, d, 'pointermove', 2 * DW); ptr(w, d, 'pointerup', 2 * DW);
  check(await until(async () => await dates(Bt) === span(5, 6) && await dates(Cc) === span(8, 9)), 'drop: the whole chain moved 2 days (server) ' + `A ${await dates(A)} B ${await dates(Bt)} C ${await dates(Cc)} want B ${span(5, 6)} C ${span(8, 9)}`);
  check(await until(() => /2 dependent tasks moved/.test(toastText(d)) && d.querySelector('#toast button')), `toast with the number and Undo: ${toastText(d)}`);
  d.querySelector('#toast button').click();
  check(await until(async () => await dates(A) === span(0, 2) && await dates(Bt) === span(3, 4) && await dates(Cc) === span(6, 7)), 'one undo takes the whole chain back');
  await until(() => bar(A) && !bar(A).classList.contains('dch-ghost'));

  // ================= drag earlier: nothing slides back, the toast says so; pull in
  await sleep(300);
  ptr(w, bar(A), 'pointerdown', 0); ptr(w, d, 'pointermove', -DW);
  check(!bar(Bt).classList.contains('dch-ghost'), 'earlier: no preview (the chain stays)');
  ptr(w, d, 'pointerup', -DW);
  check(await until(async () => (await taskOf(A)).due === ds(1)), 'drop: the task is one day earlier');
  check(await dates(Bt) === span(3, 4), 'earlier: the waiting task stays');
  // 2.67.0 (#1865, review): one toast keeps its Undo; "Pull the chain in" lives in the bar menu / task panel
  check(await until(() => /The waiting tasks stay where they are/.test(toastText(d)) && /Undo/.test(d.querySelector('#toast button')?.textContent || '')),
        `toast says the chain stays, with Undo: ${toastText(d)}`);
  w.dch_pull(A);
  check(await until(async () => await dates(Bt) === span(2, 3) && await dates(Cc) === span(5, 6)), 'pulled in: the chain follows right after (gaps kept)');
  check(await until(() => /2 tasks pulled in/.test(toastText(d)) && /Undo/.test(d.querySelector('#toast button')?.textContent || '')), `toast "2 tasks pulled in" with Undo: ${toastText(d)}`);
  d.querySelector('#toast button').click();
  check(await until(async () => await dates(Bt) === span(3, 4) && await dates(Cc) === span(6, 7)), 'undo of the pull: the chain is back');

  // ================= the bar menu
  await until(() => bar(A));
  bar(A).focus(); key(w, bar(A), 'ContextMenu');
  const item = () => [...d.querySelectorAll('#pop [role="menuitem"]')].find(x => /Pull the chain in/.test(x.textContent));
  check(await until(() => item()), 'bar menu: Pull the chain in');
  item()?.click();
  check(await until(async () => await dates(Bt) === span(2, 3)), 'bar menu: pulled in');
  await until(() => bar(Cc));
  bar(Cc).focus(); key(w, bar(Cc), 'ContextMenu');
  await sleep(200);
  check(!item(), 'a bar nothing waits on: no Pull the chain in');
  key(w, d.body, 'Escape');

  // ================= the task panel
  w.eval(`openDetail(${A})`);
  check(await until(() => d.querySelector('#d-deps [data-dch-pull]')), 'task panel: Pull the chain in under Blocking');
  d.querySelector('#d-deps [data-dch-pull]').click();
  check(await until(() => /Nothing to pull in/.test(toastText(d))), `task panel: nothing to do (gap 0) is said: ${toastText(d)}`);
  w.eval(`openDetail(${Cc})`);
  await sleep(500);
  check(!d.querySelector('#d-deps [data-dch-pull]'), 'task panel of a task nothing waits on: no button');
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();

  // ================= the list setting: on by default in a project list and (2.352.0, #2752: every list is a project) in a
  // list made without kind; off = nothing moves
  w = await boot({user: 'alice', hash: 'l/' + PLAIN}); d = w.document;
  await sleep(300);
  w.eval(`listModal(${PLAIN})`); await sleep(300);
  check(lastModal(d)?.querySelector('#l-depshift') && lastModal(d).querySelector('#l-depshift').checked, 'a list without kind: the setting is on (2.352.0)');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  check(await until(() => bar(A)), 'timeline again');
  w.eval(`listModal(${PRJ})`); await sleep(300);
  const md = lastModal(d), cb = md?.querySelector('#l-depshift');
  check(cb && cb.checked && /Move dependent tasks along/.test(md.textContent), 'project list: the setting is on by default');
  cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === PRJ).dep_shift === 0), 'switched off: saved');
  md.querySelector('.close, [data-close], .x')?.click(); key(w, d.body, 'Escape');
  await sleep(500);
  const b0 = await dates(Bt);
  ptr(w, bar(A), 'pointerdown', 0); ptr(w, d, 'pointermove', 3 * DW);
  check(!bar(Bt).classList.contains('dch-ghost'), 'setting off: no preview');
  ptr(w, d, 'pointerup', 3 * DW);
  check(await until(async () => (await taskOf(A)).due === ds(4)), 'setting off: the task itself moves');
  await sleep(300);
  check(await dates(Bt) === b0, 'setting off: the waiting task stays');
  check(errs.length === 0, 'no script errors (setting): ' + errs.join(' | '));
  w.close();

  console.log(`p267_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
