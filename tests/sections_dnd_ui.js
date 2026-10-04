// D3 UI tests (jsdom), fresh DB: drag and drop for sections. A task dropped on a section header lands at the top of
// that section (a subtask becomes standalone there), an empty section shows a drop zone only while a task is dragged,
// sections are reordered by their handle (list view and kanban columns) in one request with one undo, "Move up / down"
// in the section menu uses the same request, a view-only member gets no handles and a notice, and on a phone a
// long-press on a task opens "Move to section…" and a long-press on a section header "Move section up / down".
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const st = async (ck = CK) => call('GET', '/api/state', null, ck);
const taskOf = async (id, ck = CK) => (await st(ck)).tasks.find(t => t.id === id);
const secOrder = async (lid, ck = CK) => (await st(ck)).sections.filter(s => s.list_id === lid).map(s => s.id);
const toastText = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';
const dnd = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: ''}; e.clientY = 10; el.dispatchEvent(e); return e; };
const touch = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' ? [] : [{clientX: 20, clientY: 20}]; el.dispatchEvent(e); return e; };
const spy = w => { const calls = []; const of = w.fetch; w.fetch = (u, o = {}) => { calls.push([(o.method || 'GET').toUpperCase(), String(u)]); return of(u, o); }; return calls; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const BK = await login('bob'), CKc = await login('carol');
  await call('PATCH', '/api/settings', {lang: 'de'}, BK);
  const L = (await call('POST', '/api/lists', {name: 'Office'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: CAROL, role: 'view'});
  const sec = async name => (await call('POST', '/api/sections', {name, list_id: L})).id;
  const A = await sec('Doing'), Bs = await sec('Next'), C = await sec('Later');
  const mk = async (title, section_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: L, section_id, ...extra})).id;
  const t1 = await mk('Invoice', A), t2 = await mk('Call bank', A), t4 = await mk('Order paper', Bs), t5 = await mk('Loose end', null);
  const s1 = await mk('Scan receipts', A, {parent_id: t1});

  // ================= desktop (alice)
  let w = await boot({user: 'alice', hash: 'l/' + L, ls: {['tasks.sort2.l:' + L]: '"date"'}}); let d = w.document;
  const head = sid => d.querySelector(`#view .ghead[data-section="${sid}"]`);
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  check(head(A)?.querySelector('.shandle[draggable="true"]') && head(C)?.querySelector('.shandle') && !head('')?.querySelector('.shandle'), 'a drag handle on every named section header');
  check(d.querySelector(`.sdrop[data-section="${C}"]`) && !d.body.classList.contains('tdrag'), 'empty section: drop zone rendered, hidden until a task is dragged');
  // ---- a task onto a header: top of that section
  dnd(w, row(t4), 'dragstart'); await sleep(20);  // 2.19.0 (#667): set right after dragstart, not inside it
  check(d.body.classList.contains('tdrag'), 'while dragging: body.tdrag (drop zones show)');
  const ov = dnd(w, head(A), 'dragover');
  check(ov.defaultPrevented && head(A).classList.contains('drop'), 'section header is a drop target with a highlight');
  dnd(w, head(A), 'drop'); dnd(w, row(t1) || d.body, 'dragend');
  check(await until(async () => (await taskOf(t4)).section_id === A), 'dropped on "Doing": moved into that section (server)');
  const tA = (await st()).tasks.filter(t => t.section_id === A && !t.parent_id);
  check((await taskOf(t4)).sort < Math.min(...tA.filter(t => t.id !== t4).map(t => t.sort)), 'at the top of the section');
  check(w.eval(`LS.get('sort2.l:${L}')`) === 'prio', 'a manual drop switches date sorting back to manual order');
  check(await until(() => /Moved to section Doing/.test(toastText(d)) && d.querySelector('#toast button')), `toast with Undo: ${toastText(d)}`);
  d.querySelector('#toast button').click();
  check(await until(async () => (await taskOf(t4)).section_id === Bs), 'undo: back in "Next"');
  // ---- into an empty section via its drop zone
  await sleep(200);
  dnd(w, row(t5), 'dragstart');
  const zone = d.querySelector(`.sdrop[data-section="${C}"]`);
  check(dnd(w, zone, 'dragover').defaultPrevented && zone.classList.contains('drop'), 'empty section: the drop zone accepts the task');
  dnd(w, zone, 'drop');
  check(await until(async () => (await taskOf(t5)).section_id === C), 'dropped into the empty section "Later"');
  check(!d.body.classList.contains('tdrag'), 'drop zones hidden again');
  // ---- a subtask onto a header: standalone in that section
  await until(() => row(s1));
  dnd(w, row(s1), 'dragstart'); dnd(w, head(Bs), 'dragover'); dnd(w, head(Bs), 'drop');
  check(await until(async () => { const x = await taskOf(s1); return x.parent_id === null && x.section_id === Bs; }), 'subtask dropped on a header: standalone task in that section');
  check(await until(() => /Subtask is now standalone/.test(toastText(d))), 'toast says so');
  // ---- reorder sections by the handle
  const calls = spy(w);
  await until(() => head(C));
  dnd(w, head(C).querySelector('.shandle'), 'dragstart');
  check(dnd(w, head(A), 'dragover').defaultPrevented && head(A).classList.contains('dropbefore'), 'section drag: insert mark above the target');
  dnd(w, head(A), 'drop');
  check(await until(async () => JSON.stringify(await secOrder(L)) === JSON.stringify([C, A, Bs])), 'Later moved before Doing (server)');
  check(calls.filter(c => c[0] === 'POST' && /sections\/order/.test(c[1])).length === 1 && !calls.some(c => c[0] === 'PATCH' && /sections/.test(c[1])), 'one request for the new order');
  check(await until(() => /Sections reordered/.test(toastText(d))), 'toast');
  d.querySelector('#toast button').click();
  check(await until(async () => JSON.stringify(await secOrder(L)) === JSON.stringify([A, Bs, C])), 'undo: old order back');
  // ---- section menu: move down = the same request
  await w.eval('load()'); calls.length = 0;
  w.eval(`moveSection(${A}, 1)`);
  check(await until(async () => JSON.stringify(await secOrder(L)) === JSON.stringify([Bs, A, C])), 'menu "Move right / down"');
  check(calls.filter(c => c[0] !== 'GET').length === 1, 'moveSection: one request (was one PATCH per section)');
  await call('POST', `/api/lists/${L}/sections/order`, {ids: [A, Bs, C]});
  // ---- kanban columns
  await call('PATCH', `/api/lists/${L}`, {view: 'kanban'});
  await w.eval('load().then(() => render())'); await sleep(300);
  const col = sid => d.querySelector(`.kcol[data-kcol="${sid}"]`);
  check(col(Bs)?.querySelector('.khead .shandle'), 'kanban: handle on the column header');
  dnd(w, col(Bs).querySelector('.shandle'), 'dragstart'); dnd(w, col(A), 'dragover');
  check(col(A).classList.contains('dropbefore'), 'kanban: insert mark on the column');
  dnd(w, col(A), 'drop');
  check(await until(async () => JSON.stringify(await secOrder(L)) === JSON.stringify([Bs, A, C])), 'kanban: column moved before "Doing"');
  await call('PATCH', `/api/lists/${L}`, {view: 'list'});
  // server: wrong ids refused
  const bad = await call('POST', `/api/lists/${L}/sections/order`, {ids: [A, Bs]});
  check(bad.status === 400, `order: every section exactly once (${bad.status})`);
  check(errs.length === 0, 'no script errors (desktop): ' + errs.join(' | '));
  w.close();

  // ================= view-only member
  w = await boot({user: 'carol', hash: 'l/' + L}); d = w.document;
  check(d.querySelector(`#view .ghead[data-section="${A}"]`) && !d.querySelector('.shandle') && !d.querySelector('.sdrop'), 'view-only: no handles, no drop zones');
  w.eval(`taskToSection(${t2}, ${C})`); await sleep(200);
  check(/View only/.test(toastText(d)), 'view-only: a move gives the notice');
  check((await taskOf(t2)).section_id === A, 'nothing moved');
  const r = await call('POST', `/api/lists/${L}/sections/order`, {ids: [C, A, Bs]}, CKc);
  check(r.status === 403, `view-only: the server refuses the order too (${r.status})`);
  const cmob = await boot({user: 'carol', hash: 'l/' + L, mobile: true, media: {'(hover: none)': true}});
  const hc = cmob.document.querySelector(`#view .ghead[data-section="${A}"]`);
  touch(cmob, hc, 'touchstart'); await sleep(520); touch(cmob, hc, 'touchend'); await sleep(100);
  check(/Nur ansehen|View only/.test(cmob.document.querySelector('#toast:not(.hidden)')?.textContent || ''), 'view-only: long-press on a header gives the notice');
  cmob.close(); w.close();

  await call('POST', `/api/lists/${L}/sections/order`, {ids: [A, Bs, C]});
  // ================= phone (bob, German): long-press task -> "Move to section…", long-press header -> up / down
  w = await boot({user: 'bob', hash: 'l/' + L, mobile: true, media: {'(hover: none)': true}}); d = w.document;
  touch(w, row(t2), 'touchstart'); await sleep(450);
  const te = touch(w, row(t2), 'touchend'); await sleep(150);
  // 2.13.0 (#453 A14): a long press without moving selects the task in a list (Kanban keeps "Move to column…"); the
  // section picker itself is the same
  check(te.defaultPrevented && w.eval('S.multiMode') && w.eval(`S.multi.has(${t2})`), 'long-press on a task without moving: selects it (2.13.0)');
  w.eval('S.multi.clear(); S.multiMode = false; render()');
  w.eval(`sectionPicker(document.querySelector('#view .trow[data-id="${t2}"]'), ${t2})`); await sleep(150);
  let pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Nicht zugeordnet/.test(pop.textContent) && /Later/.test(pop.textContent), 'section picker (German)');
  [...pop.querySelectorAll('button')].find(b => b.textContent.trim() === 'Later').click();
  check(await until(async () => (await taskOf(t2, BK)).section_id === C), 'picked: moved to "Later"');
  check(await until(() => /In Abschnitt „Later“ verschoben/.test(toastText(d))), `German toast: ${toastText(d)}`);
  const hb = () => d.querySelector(`#view .ghead[data-section="${Bs}"]`);
  touch(w, hb(), 'touchstart'); await sleep(520);
  const he = touch(w, hb(), 'touchend'); await sleep(150);
  pop = d.querySelector('#pop:not(.hidden)');
  check(he.defaultPrevented && pop && /Abschnitt nach oben/.test(pop.textContent) && /Abschnitt nach unten/.test(pop.textContent), 'long-press on a section header: move up / down');
  [...pop.querySelectorAll('button')].find(b => /Abschnitt nach oben/.test(b.textContent)).click();
  check(await until(async () => JSON.stringify(await secOrder(L, BK)) === JSON.stringify([Bs, A, C])), 'moved up (one request, same as the menu)');
  check(!d.querySelector(`#view .ghead[data-section="${A}"]`)?.classList.contains('closed'), 'the long-press did not also collapse the section');
  check(errs.length === 0, 'no script errors (phone): ' + errs.join(' | '));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
