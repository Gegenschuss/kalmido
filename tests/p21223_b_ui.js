// 2.122.3 UI tests, part B (jsdom), fresh DB:
// - #2334: ONE task (no selection) dragged onto the middle of another becomes its subtask: the target row says "As a
//   subtask of this task" instead of the insert line, the drop is ONE batch request, ONE Undo puts it back; the upper part
//   of a row still moves it before (the old way, no parent); a milestone and the task's own subtask are no middle target
//   (the insert line instead), the server refuses both too; a row without a size (no layout) keeps the old halves
// - phone (390 px): the finger's drag (long press, move) has the same middle; the long press selection's menu offers
//   "Subtasks of…" for one task
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const st = async (ck = CK) => call('GET', '/api/state', null, ck);
const taskOf = async (id, ck = CK) => (await st(ck)).tasks.find(t => t.id === id);
const toastText = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';
// a synthetic drag event (jsdom has no DataTransfer); o: altKey, clientY
const dnd = (w, el, type, o = {}) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: '', setDragImage() {}}; e.clientY = o.clientY ?? 10; e.altKey = !!o.altKey; el.dispatchEvent(e); return e; };
const touch = (w, el, type, y = 120) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' || type === 'touchcancel' ? [] : [{clientX: 40, clientY: y}]; el.dispatchEvent(e); return e; };
const spy = w => { const calls = []; const of = w.fetch; w.fetch = (u, o = {}) => { calls.push([(o.method || 'GET').toUpperCase(), String(u)]); return of(u, o); }; return calls; };
// jsdom lays nothing out: a row gets a height so its upper / middle / lower part can be hit
const rowBox = el => { el.getBoundingClientRect = () => ({top: 100, bottom: 140, height: 40, left: 0, right: 390, width: 390}); return el; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  const mk = async (title, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: P, ...extra})).id;
  const T1 = await mk('Design'), T2 = await mk('Build'), T3 = await mk('Ship'), MS = await mk('Go live');
  const KID = await mk('Wireframes', {parent_id: T1});
  await call('PATCH', '/api/tasks/' + MS, {ms: 1});
  // the server refuses the same targets (the client only hides the middle)
  let r = await call('PATCH', '/api/tasks/' + T1, {parent_id: KID});
  check(!(await taskOf(T1)).parent_id, '#2334: server: a task under its own subtask is refused: ' + r.status);
  r = await call('PATCH', '/api/tasks/' + T2, {parent_id: MS});
  check(!(await taskOf(T2)).parent_id, '#2334: server: a milestone as parent is refused: ' + r.status);

  // ================= desktop
  let w = await boot({user: 'alice', hash: 'l/' + P, ls: {hintsSeen: ['dgalt', 'dgmulti']}}); let d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  check(await until(() => row(T1) && row(T2) && row(T3) && row(MS) && row(KID)), 'the project list renders (with the subtask)');
  check(w.eval('isMs(S.tasks.get(' + MS + '))'), 'Go live is a milestone');
  let calls = spy(w);
  dnd(w, row(T2), 'dragstart'); await sleep(50);
  let ov = dnd(w, rowBox(row(T3)), 'dragover', {clientY: 120});
  check(ov.defaultPrevented && row(T3).classList.contains('dgonto') && /As a subtask of this task/.test(row(T3).dataset.dg || '') && !row(T3).classList.contains('dropbefore') && !row(T3).classList.contains('dropafter'), '#2334: the middle of a row: "As a subtask of this task" instead of the insert line');
  ov = dnd(w, row(T3), 'dragover', {clientY: 104});
  check(ov.defaultPrevented && !row(T3).classList.contains('dgonto') && row(T3).classList.contains('dropbefore'), '#2334: the upper part: the insert line again');
  dnd(w, row(T3), 'dragover', {clientY: 136});
  check(!row(T3).classList.contains('dgonto') && row(T3).classList.contains('dropafter'), '#2334: the lower part: the line after it');
  dnd(w, row(T3), 'dragover', {clientY: 120});
  dnd(w, row(T3), 'drop', {clientY: 120}); dnd(w, row(T2), 'dragend');
  check(await until(async () => (await taskOf(T2)).parent_id === T3), '#2334: Build is now a subtask of Ship');
  check(calls.filter(c => c[0] === 'POST' && /\/api\/tasks\/batch/.test(c[1])).length === 1 && !calls.some(c => /reorder/.test(c[1]) || c[0] === 'PATCH'), '#2334: ONE batch request, no reordering');
  check(await until(() => /1 task is now a subtask of “Ship”/.test(toastText(d)) && d.querySelector('#toast button')), '#2334: the message with Undo: ' + toastText(d));
  check(!d.querySelector('.dgonto') && !d.querySelector('.dragging'), '#2334: no mark left after the drop');
  d.querySelector('#toast button').click();
  check(await until(async () => !(await taskOf(T2)).parent_id), '#2334: ONE Undo puts it back');
  check(await until(() => w.eval('!HIST.busy && HIST.undo.length === 0') && row(T2)), '#2334: the undo was one history step');

  // upper part: moved before as before (no parent)
  await w.eval('load().then(render)'); await sleep(300);
  calls = spy(w);
  dnd(w, row(T3), 'dragstart');
  dnd(w, rowBox(row(T1)), 'dragover', {clientY: 102}); dnd(w, row(T1), 'drop', {clientY: 102}); dnd(w, row(T3), 'dragend');
  check(await until(async () => { const s = (await st()).tasks, g = id => s.find(t => t.id === id); return !g(T3).parent_id && g(T3).sort < g(T1).sort; }), '#2334: the upper part moves Ship before Design (no subtask)');
  check(!calls.some(c => /\/api\/tasks\/batch/.test(c[1])), '#2334: the old way (no batch)');

  // a milestone: no middle
  await w.eval('load().then(render)'); await sleep(300);
  dnd(w, row(T2), 'dragstart');
  dnd(w, rowBox(row(MS)), 'dragover', {clientY: 120});
  check(!row(MS).classList.contains('dgonto') && (row(MS).classList.contains('dropbefore') || row(MS).classList.contains('dropafter')), '#2334: a milestone: the insert line, no middle');
  dnd(w, row(T2), 'dragend');
  // the own subtask: no middle
  dnd(w, row(T1), 'dragstart');
  dnd(w, rowBox(row(KID)), 'dragover', {clientY: 120});
  check(!row(KID).classList.contains('dgonto'), '#2334: the own subtask: no middle');
  dnd(w, row(T1), 'dragend');
  // a milestone dragged: no middle either
  dnd(w, row(MS), 'dragstart');
  dnd(w, rowBox(row(T2)), 'dragover', {clientY: 120});
  check(!row(T2).classList.contains('dgonto'), '#2334: a dragged milestone: no middle');
  dnd(w, row(MS), 'dragend');
  // a row without a size (no layout): the old halves, no middle
  dnd(w, row(T2), 'dragstart');
  dnd(w, row(T1), 'dragover', {clientY: 10});
  check(!row(T1).classList.contains('dgonto') && row(T1).classList.contains('dropbefore'), '#2334: no layout: the insert line as before');
  dnd(w, row(T2), 'dragend');
  check(errs.length === 0, 'no script errors (desktop): ' + errs.join(' | '));
  w.close();

  // ================= phone (390 px): the finger's drag
  w = await boot({user: 'alice', hash: 'l/' + P, mobile: true, media: {'(hover: none)': true}}); d = w.document;
  check(await until(() => row(T2) && row(T3)), 'phone: the list renders');
  let under = null;
  d.elementFromPoint = () => under;
  if (!w.visualViewport) w.visualViewport = {height: 844};  // jsdom has none (the edge scroll of the finger's drag reads it)
  calls = spy(w);
  touch(w, row(T2), 'touchstart'); await sleep(420);
  check(row(T2).classList.contains('dragging'), 'phone: the long press lifts the row');
  under = rowBox(row(T3)); touch(w, row(T2), 'touchmove', 120); await sleep(80);
  check(row(T3).classList.contains('dgonto') && /As a subtask of this task/.test(row(T3).dataset.dg || '') && !row(T3).classList.contains('dropbefore'), 'phone: the middle of a row: "As a subtask of this task"');
  touch(w, row(T2), 'touchmove', 103); await sleep(80);
  check(!row(T3).classList.contains('dgonto') && row(T3).classList.contains('dropbefore'), 'phone: the upper part: the insert line');
  touch(w, row(T2), 'touchmove', 121); await sleep(80);
  touch(w, row(T2), 'touchend', 121); under = null;
  check(await until(async () => (await taskOf(T2)).parent_id === T3), 'phone: Build is now a subtask of Ship');
  check(calls.filter(c => c[0] === 'POST' && /\/api\/tasks\/batch/.test(c[1])).length === 1 && !calls.some(c => /reorder/.test(c[1])), 'phone: ONE batch request');
  check(!d.querySelector('.dgonto') && !d.querySelector('.ghost-drag'), 'phone: no mark / ghost left');
  check(await until(() => d.querySelector('#toast button')), 'phone: Undo offered');
  d.querySelector('#toast button').click();
  check(await until(async () => !(await taskOf(T2)).parent_id), 'phone: Undo puts it back');
  // the long press selection: "Subtasks of…" for one task
  await w.eval('load().then(render)'); await sleep(300);
  w.eval(`(() => { S.multiMode = true; S.multi.add(${T3}); renderMultiBar(); render(); })()`); await sleep(150);
  d.querySelector('#mbar [data-act="mb-menu"]').click(); await sleep(100);
  const sub = [...d.querySelectorAll('#pop:not(.hidden) button')].find(b => /Subtasks of…/.test(b.textContent));
  check(!!sub, 'phone: "Subtasks of…" in the menu of one selected task');
  if (sub) {
    sub.click(); await sleep(100);
    const md = d.querySelector('.dgpick');
    check(md && !md.querySelector(`[data-pick="${MS}"]`) && !md.querySelector(`[data-pick="${T3}"]`), 'phone: the search leaves out the milestone and the task itself');
    md?.querySelector(`[data-pick="${T1}"]`)?.click();
    check(await until(async () => (await taskOf(T3)).parent_id === T1), 'phone: Ship under Design');
  }
  check(errs.length === 0, 'no script errors (phone): ' + errs.join(' | '));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
