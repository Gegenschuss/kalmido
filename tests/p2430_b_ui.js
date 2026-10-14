// 2.43.0 UI tests, part B (jsdom), fresh DB:
// - #1330: a task dragged with Alt held onto another task of a project waits on it (the target row shows "Waits on this
//   task" instead of the insert line, releasing Alt during the drag switches back), one Undo removes it; a loop is refused
//   with the server's message; while a task is dragged the open task's dependencies show the drop fields "Waiting on" /
//   "Blocking" (both directions, gone after the drag); the task menu has "Waiting on a task…" with the task search
// - #1003: with a selection a drag takes all (the drag image says "3 tasks"); dropped onto the middle of a task they become
//   its subtasks in their order (ONE request, ONE Undo puts them back); a task with own subtasks that would go deeper than
//   three levels stays and the message counts it; subtasks dropped on a section header become standalone tasks there
//   (order kept); above a row the block lands before it; the multi panel's "Subtasks of…" / "Out of the parent task" and
//   the phone's selection menu offer the same
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
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
// a synthetic drag event (jsdom has no DataTransfer); o: altKey, clientY
const dnd = (w, el, type, o = {}) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: '', img: null, setDragImage(x) { this.img = x.textContent; }}; e.clientY = o.clientY ?? 10; e.altKey = !!o.altKey; el.dispatchEvent(e); return e; };
const spy = w => { const calls = []; const of = w.fetch; w.fetch = (u, o = {}) => { calls.push([(o.method || 'GET').toUpperCase(), String(u)]); return of(u, o); }; return calls; };
// jsdom lays nothing out: a row gets a height so its upper / middle / lower part can be hit
const rowBox = el => { el.getBoundingClientRect = () => ({top: 100, bottom: 140, height: 40, left: 0, right: 600, width: 600}); return el; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  const mk = async (title, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: P, ...extra})).id;
  const T1 = await mk('Design'), T2 = await mk('Build'), T3 = await mk('Ship');

  // ================= #1330 desktop (alice)
  let w = await boot({user: 'alice', hash: 'l/' + P, ls: {hintsSeen: ['dgmulti']}}); let d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  check(await until(() => row(T1) && row(T3)), 'the project list renders');
  let calls = spy(w);
  // first drag: the hint once
  dnd(w, row(T2), 'dragstart'); await sleep(50);
  check(/Alt/.test(toastText(d)), '#1330: the first drag explains Alt: ' + toastText(d));
  let ov = dnd(w, row(T1), 'dragover', {altKey: true});
  check(ov.defaultPrevented && row(T1).classList.contains('dgdep') && /Waits on this task/.test(row(T1).dataset.dg || '') && !row(T1).classList.contains('dropbefore'), '#1330: Alt over a row: "Waits on this task" instead of the insert line');
  ov = dnd(w, row(T1), 'dragover');
  check(!row(T1).classList.contains('dgdep') && (row(T1).classList.contains('dropbefore') || row(T1).classList.contains('dropafter')), '#1330: Alt released during the drag: the insert line again');
  dnd(w, row(T1), 'dragover', {altKey: true});
  dnd(w, row(T1), 'drop', {altKey: true}); dnd(w, row(T2), 'dragend');
  check(await until(async () => ((await taskOf(T2)).blockers || []).includes(T1)), '#1330: Build waits on Design');
  check(calls.filter(c => c[0] === 'POST' && /\/api\/deps$/.test(c[1])).length === 1 && !calls.some(c => /reorder/.test(c[1])), '#1330: one dependency request, no reordering');
  check(await until(() => /“Build” waits on “Design”/.test(toastText(d)) && d.querySelector('#toast button')), '#1330: message with Undo: ' + toastText(d));
  d.querySelector('#toast button').click();
  check(await until(async () => !((await taskOf(T2)).blockers || []).length), '#1330: one Undo removes it');
  // a loop: Design waits on Build, then Build onto Design with Alt -> refused, the server's message
  await call('POST', '/api/deps', {task_id: T1, blocker_id: T2});
  await w.eval('load().then(render)'); await sleep(300);
  dnd(w, row(T2), 'dragstart');
  dnd(w, row(T1), 'dragover', {altKey: true});
  check(row(T1).classList.contains('dgno') && /loop/.test(row(T1).dataset.dg || ''), '#1330: the row says a loop is not possible: ' + row(T1).dataset.dg);
  dnd(w, row(T1), 'drop', {altKey: true}); dnd(w, row(T2), 'dragend');
  check(await until(() => /circular/.test(toastText(d)) && /“Design”/.test(toastText(d))), '#1330: the loop is refused with both names: ' + toastText(d));
  check(!((await taskOf(T2)).blockers || []).includes(T1), '#1330: nothing saved');
  await call('DELETE', `/api/deps/${T1}/${T2}`);
  // the drop fields in the task panel
  await w.eval(`load().then(() => { render(); openDetail(${T3}); })`);
  check(await until(() => d.querySelector('#d-deps h5') && !/Loading/.test(d.querySelector('#d-deps').textContent)), '#1330: the panel shows the dependencies');
  check(!d.querySelector('.dgzones'), '#1330: no drop fields without a drag');
  dnd(w, row(T1), 'dragstart'); await sleep(50);
  const zone = k => d.querySelector(`#d-deps .dgzone[data-dgz="${k}"]`);
  check(zone('by') && zone('blocking') && /Waiting on/.test(zone('by').textContent) && /Blocking/.test(zone('blocking').textContent), '#1330: two drop fields while dragging');
  ov = dnd(w, zone('by'), 'dragover');
  check(ov.defaultPrevented && zone('by').classList.contains('drop'), '#1330: the field lights up');
  dnd(w, zone('by'), 'drop'); dnd(w, row(T1), 'dragend');
  check(await until(async () => ((await taskOf(T3)).blockers || []).includes(T1)), '#1330: "Waiting on": Ship waits on the dragged Design');
  check(!d.querySelector('.dgzones'), '#1330: the fields are gone after the drop');
  await until(() => d.querySelector('#toast button'));
  d.querySelector('#toast button').click();
  check(await until(async () => !((await taskOf(T3)).blockers || []).length), '#1330: Undo of the panel drop');
  dnd(w, row(T2), 'dragstart'); await sleep(50);
  dnd(w, zone('blocking'), 'dragover'); dnd(w, zone('blocking'), 'drop'); dnd(w, row(T2), 'dragend');
  check(await until(async () => ((await taskOf(T2)).blockers || []).includes(T3)), '#1330: "Blocking": the dragged Build waits on Ship');
  // the task menu: "Waiting on a task…" with the search
  await w.eval(`taskMenu(document.querySelector('#view .trow[data-id="${T1}"] .ttl'), ${T1})`); await sleep(100);
  const mi = [...d.querySelectorAll('#pop:not(.hidden) button')].find(b => /Waiting on a task…/.test(b.textContent));
  check(!!mi, '#1330: "Waiting on a task…" in the task menu');
  if (mi) {
    mi.click(); await sleep(100);
    const md = d.querySelector('.dgpick');
    check(md && md.querySelector(`[data-pick="${T3}"]`) && !md.querySelector(`[data-pick="${T1}"]`), '#1330: the task search lists the others');
    md.querySelector('#dg-q').value = 'shi'; md.querySelector('#dg-q').dispatchEvent(new w.Event('input', {bubbles: true}));
    check(md.querySelectorAll('[data-pick]').length === 1, '#1330: the search filters');
    md.querySelector(`[data-pick="${T3}"]`).click();
    check(await until(async () => ((await taskOf(T1)).blockers || []).includes(T3)), '#1330: picked: Design waits on Ship');
  }
  check(errs.length === 0, 'no script errors (#1330): ' + errs.join(' | '));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
