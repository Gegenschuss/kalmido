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
  check(await until(() => row(T1) && row(T2) && row(T3)), 'the project list renders');  // 2.46.1: T2 too (it is dragged next; slow CI runners)
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
  await until(() => w.eval('!HIST.busy') && row(T2));  // 2.46.1: the undo redraw is over (slow CI runners)
  dnd(w, row(T2), 'dragstart'); await until(() => zone('blocking'));
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

  // ================= #1003 desktop: several tasks at once
  const L = (await call('POST', '/api/lists', {name: 'Office'})).id;
  const sec = async name => (await call('POST', '/api/sections', {name, list_id: L})).id;
  const SA = await sec('Doing'), SB = await sec('Later');
  const mo = async (title, section_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: L, section_id, ...extra})).id;
  const PARENT = await mo('Quarterly report', SA);
  const A1 = await mo('Collect numbers', SA), A2 = await mo('Draw charts', SA), A3 = await mo('Write summary', SA);
  const DEEP = await mo('Appendix', SA);
  await mo('Tables', SA, {parent_id: DEEP});
  const MID = await mo('Chapter one', SA, {parent_id: PARENT});
  w = await boot({user: 'alice', hash: 'l/' + L, ls: {hintsSeen: ['dgalt'], ['tasks.sort2.l:' + L]: '"prio"'}}); d = w.document;
  check(await until(() => row(A1) && row(A3)), 'the office list renders');
  const ttl = id => row(id).querySelector('.ttl');
  click(w, ttl(A1), {ctrlKey: true}); await sleep(100);
  click(w, ttl(A2), {ctrlKey: true}); await sleep(100);
  click(w, ttl(A3), {ctrlKey: true}); await sleep(150);
  check(w.eval('S.multi.size') === 3, '#1003: three selected');
  const seen = [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).filter(i => [A1, A2, A3].includes(i));
  calls = spy(w);
  let ds = dnd(w, row(A2), 'dragstart'); await sleep(50);
  check(ds.dataTransfer.img === '3 tasks', '#1003: the drag image says "3 tasks": ' + ds.dataTransfer.img);
  check(/middle of a task/.test(toastText(d)), '#1003: the first multi drag explains the middle: ' + toastText(d));
  ov = dnd(w, rowBox(row(PARENT)), 'dragover', {clientY: 120});
  check(ov.defaultPrevented && row(PARENT).classList.contains('dgonto') && /3 tasks become its subtasks/.test(row(PARENT).dataset.dg || ''), '#1003: the middle of a row: "3 tasks become its subtasks"');
  dnd(w, row(PARENT), 'drop', {clientY: 120}); dnd(w, row(A2), 'dragend');
  const kidsOf = async pid => (await st()).tasks.filter(t => t.parent_id === pid).sort((a, b) => a.sort - b.sort).map(t => t.id);
  check(await until(async () => JSON.stringify(await kidsOf(PARENT)) === JSON.stringify([MID, ...seen])), '#1003: subtasks of the report in the order on screen, after its own one: ' + JSON.stringify(seen));
  check(calls.filter(c => c[0] === 'POST' && /\/api\/tasks\/batch/.test(c[1])).length === 1 && !calls.some(c => c[0] === 'PATCH'), '#1003: ONE batch request');
  check(await until(() => /3 tasks are now subtasks of “Quarterly report”/.test(toastText(d))), '#1003: the message: ' + toastText(d));
  d.querySelector('#toast button').click();
  check(await until(async () => !(await kidsOf(PARENT)).includes(A1) && !(await taskOf(A3)).parent_id), '#1003: ONE Undo puts all three back');
  check(w.eval('HIST.undo.length') === 0, '#1003: the undo was one history step');
  // depth: onto "Chapter one" (level 2): Appendix has a subtask -> stays, the others move
  await w.eval('load().then(render)'); await sleep(300);
  w.eval(`(() => { S.multi.clear(); [${A1}, ${DEEP}].forEach(i => S.multi.add(i)); renderMultiBar(); render(); })()`); await sleep(150);
  dnd(w, row(A1), 'dragstart');
  dnd(w, rowBox(row(MID)), 'dragover', {clientY: 120}); dnd(w, row(MID), 'drop', {clientY: 120}); dnd(w, row(A1), 'dragend');
  check(await until(async () => (await taskOf(A1)).parent_id === MID), '#1003: Collect numbers is now on level 3');
  check(!(await taskOf(DEEP)).parent_id, '#1003: Appendix (own subtasks) stays');
  check(await until(() => /1 task stays: its own subtasks would go deeper than 3 levels/.test(toastText(d))), '#1003: the message counts it: ' + toastText(d));
  // out onto a section header: standalone in "Later", order kept
  await w.eval('load().then(render)'); await sleep(300);
  await call('PATCH', '/api/tasks/' + A1, {parent_id: PARENT}); await call('PATCH', '/api/tasks/' + A2, {parent_id: PARENT});
  await w.eval('load().then(render)'); await sleep(300);
  w.eval(`(() => { S.multi.clear(); [${A2}, ${A1}].forEach(i => S.multi.add(i)); renderMultiBar(); render(); })()`); await sleep(150);
  const head = sid => d.querySelector(`#view .ghead[data-section="${sid}"]`);
  check(row(A1) && head(SB), '#1003: subtasks and the section header are shown');
  dnd(w, row(A1), 'dragstart');
  dnd(w, head(SB), 'dragover'); dnd(w, head(SB), 'drop'); dnd(w, row(A1), 'dragend');
  check(await until(async () => { const a = await taskOf(A1), b = await taskOf(A2); return !a.parent_id && !b.parent_id && a.section_id === SB && b.section_id === SB && a.sort < b.sort; }), '#1003: standalone in "Later", order kept');
  // a block before a row (upper part)
  await w.eval('load().then(render)'); await sleep(300);
  w.eval(`(() => { S.multi.clear(); [${A1}, ${A2}].forEach(i => S.multi.add(i)); renderMultiBar(); render(); })()`); await sleep(150);
  dnd(w, row(A1), 'dragstart');
  ov = dnd(w, rowBox(row(A3)), 'dragover', {clientY: 102});
  check(row(A3).classList.contains('dropbefore') && !row(A3).classList.contains('dgonto'), '#1003: the upper part: the insert line');
  dnd(w, row(A3), 'drop', {clientY: 102}); dnd(w, row(A1), 'dragend');
  check(await until(async () => { const s = (await st()).tasks, g = id => s.find(t => t.id === id); return g(A1).section_id === SA && g(A2).section_id === SA && g(A1).sort < g(A2).sort && g(A2).sort < g(A3).sort; }), '#1003: the block lands before "Write summary" in "Doing"');
  // the multi panel: "Subtasks of…" and "Out of the parent task"
  await w.eval('load().then(render)'); await sleep(300);
  w.eval(`(() => { S.multi.clear(); [${A1}, ${A2}].forEach(i => S.multi.add(i)); renderMultiBar(); render(); })()`);
  check(await until(() => d.querySelector('#detail.multi [data-act="dg-sub"]')), '#1003: the multi panel has "Subtasks of…"');
  check(!d.querySelector('#detail.multi [data-act="dg-out"]'), '#1003: no "Out of the parent task" without subtasks');
  d.querySelector('#detail [data-act="dg-sub"]').click(); await sleep(100);
  let md = d.querySelector('.dgpick');
  check(md && md.querySelector(`[data-pick="${A3}"]`) && !md.querySelector(`[data-pick="${A1}"]`), '#1003: the search lists others, not the selection');
  calls = spy(w);
  md.querySelector(`[data-pick="${A3}"]`).click();
  check(await until(async () => (await taskOf(A1)).parent_id === A3 && (await taskOf(A2)).parent_id === A3), '#1003: both are subtasks of "Write summary"');
  check(calls.filter(c => /\/api\/tasks\/batch/.test(c[1])).length === 1, '#1003: one batch');
  await sleep(200);
  check(await until(() => d.querySelector('#detail.multi [data-act="dg-out"]')), '#1003: now "Out of the parent task" is offered');
  d.querySelector('#detail [data-act="dg-out"]').click();
  check(await until(async () => { const a = await taskOf(A1), b = await taskOf(A2), c = await taskOf(A3); return !a.parent_id && !b.parent_id && a.sort > c.sort && a.sort < b.sort; }), '#1003: standalone right after their parent, order kept');
  check(errs.length === 0, 'no script errors (#1003): ' + errs.join(' | '));
  w.close();

  // ================= #1003 phone: the selection menu
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + L}); d = w.document;
  check(await until(() => row(A1)), 'phone: the list renders');
  w.eval(`(() => { S.multiMode = true; [${A1}, ${A2}].forEach(i => S.multi.add(i)); renderMultiBar(); render(); })()`); await sleep(150);
  d.querySelector('#mbar [data-act="mb-menu"]').click(); await sleep(100);
  const sub = [...d.querySelectorAll('#pop:not(.hidden) button')].find(b => /Subtasks of…/.test(b.textContent));
  check(!!sub, 'phone: "Subtasks of…" in the selection menu');
  if (sub) {
    sub.click(); await sleep(100);
    md = d.querySelector('.dgpick');
    md?.querySelector(`[data-pick="${PARENT}"]`)?.click();
    check(await until(async () => (await taskOf(A1)).parent_id === PARENT && (await taskOf(A2)).parent_id === PARENT), 'phone: both under the report');
  }
  check(errs.length === 0, 'no script errors (phone): ' + errs.join(' | '));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
