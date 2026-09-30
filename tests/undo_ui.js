// D4 UI tests (jsdom), fresh DB: the undo / redo history. The ← / → buttons in the top bar (disabled when empty, labels
// "Undo: …" / "Redo: …"), several steps back and forth across action types (complete, field edits, moves, create, delete,
// sections, list type / folder / order, batch, roadmap shift, custom fields), the keyboard (Ctrl+Z, Ctrl+Shift+Z, Ctrl+Y,
// never inside text fields), redo cleared by a new action, one step per text editing session, the conflict skip (a
// second session changes a field in between), the offline outbox (cancel, queue, pending state), the view-only refusal,
// the trash guard, and the history menu (right-click / long-press) that jumps several steps.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, ms = 5000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const get = (id, ck = CK) => call('GET', `/api/tasks/${id}`, null, ck);
const st = async (ck = CK) => call('GET', '/api/state', null, ck);
const toastText = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const addD = (s, n) => { const [y, m, d] = s.split('-').map(Number); const x = new Date(y, m - 1, d + n); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {features: 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields'});
  const WORK = (await call('POST', '/api/lists', {name: 'Work'})).id, HOME = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const SH = (await call('POST', '/api/lists', {name: 'Shared', kind: 'project'})).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: BOB, role: 'edit'});
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const t1 = await mk('Pay invoice', WORK), t2 = await mk('Call bank', WORK), t3 = await mk('Order paper', WORK);
  const s1 = await mk('Plan trip', SH, {priority: 1}), s2 = await mk('Book hotel', SH);
  const FLD = (await call('POST', `/api/lists/${SH}/fields`, {name: 'Budget', type: 'text'})).id;

  let w = await boot({user: 'alice', hash: 'l/' + WORK}); let d = w.document;
  const btn = dir => d.querySelector(`#top [data-act="hist-${dir}"]`);
  const idle = () => until(() => !w.eval('HIST.busy'));
  const key = async (k, o = {}) => { const e = new w.KeyboardEvent('keydown', {key: k, ctrlKey: true, bubbles: true, cancelable: true, ...o}); (o.target || d).dispatchEvent(e); await sleep(50); await idle(); return e; };
  const hl = dir => w.eval(`HIST.${dir}.length`);

  // ================= the buttons
  check(btn('undo') && btn('redo'), '← / → buttons in the top bar');
  check(btn('undo').disabled && btn('redo').disabled, 'both disabled while the history is empty');
  check(btn('undo').getAttribute('aria-label') === 'Nothing to undo' && btn('redo').getAttribute('aria-label') === 'Nothing to redo', 'empty labels');

  // ================= several steps across action types, back and forth
  await w.eval(`toggleTask(${t1})`); await sleep(200);                        // 1 complete
  await w.eval(`patchTask(${t2}, {priority: 5})`); await sleep(100);          // 2 field edit
  await w.eval(`patchUndoable(${t3}, {list_id: ${HOME}}, 'moved')`);         // 3 move
  const created = await w.eval(`createTask({title: 'Fresh idea', list_id: ${WORK}})`); const tn = created.id;  // 4 create
  await w.eval(`sectionCreate(${WORK}, 'Later')`);                             // 5 section
  await w.eval(`setListKind(${WORK}, 'project')`);                            // 6 list type
  check(hl('undo') === 6, `six steps recorded (${hl('undo')})`);
  check(!btn('undo').disabled && btn('undo').getAttribute('aria-label') === 'Undo: Type of “Work”: Project', `undo label: ${btn('undo').getAttribute('aria-label')}`);
  check(/Undo: Type of “Work”: Project \((Ctrl\+Shift\+Z|Ctrl\+Z)/.test(btn('undo').title) || btn('undo').title.startsWith('Undo: Type of “Work”: Project'), 'tooltip names the step');
  const secL = async () => (await st()).sections.find(s => s.list_id === WORK && s.name === 'Later');
  btn('undo').click(); await sleep(50); await idle();
  check((await st()).lists.find(l => l.id === WORK).kind === 'list', '← undid the list type');
  check(/Undone: Type of “Work”: Project/.test(toastText(d)), `toast "Undone: …": ${toastText(d)}`);
  check(btn('redo').getAttribute('aria-label') === 'Redo: Type of “Work”: Project' && !btn('redo').disabled, '→ now offers the step');
  await key('z');
  check(!(await secL()), 'Ctrl+Z undid the new section');
  await key('z');
  check((await get(tn)).status === 404, 'Ctrl+Z undid the new task (to the trash)');
  check(hl('undo') === 3 && hl('redo') === 3, 'three back, three forward');
  await key('z', {shiftKey: true});
  check((await get(tn)).deleted_at === null, 'Ctrl+Shift+Z redid the new task (from the trash)');
  await key('y');
  check(!!(await secL()), 'Ctrl+Y redid the section (re-created)');
  const e2 = await key('y', {metaKey: true, ctrlKey: false});
  check(!e2.defaultPrevented && hl('redo') === 1, 'Cmd+Y is not redo (only Ctrl+Y)');
  await key('z', {metaKey: true, ctrlKey: false, shiftKey: true});
  check((await st()).lists.find(l => l.id === WORK).kind === 'project', 'Cmd+Shift+Z redid the list type');
  for (let i = 0; i < 6; i++) await key('z');
  const [a1, a2, a3, a4] = await Promise.all([get(t1), get(t2), get(t3), get(tn)]);
  check(a1.status === 0 && a2.priority === 0 && a3.list_id === WORK && a4.status === 404 && !(await secL()) && (await st()).lists.find(l => l.id === WORK).kind === 'list',
    'all six undone: reopened, priority, list, trash, section, type');
  check(btn('undo').disabled && hl('redo') === 6, '← disabled at the start, six steps forward');
  for (let i = 0; i < 3; i++) btn('redo').click(), await sleep(50), await idle();
  const [b1, b2, b3] = await Promise.all([get(t1), get(t2), get(t3)]);
  check(b1.status === 2 && b2.priority === 5 && b3.list_id === HOME, 'redo x3: completed again, priority again, moved again');

  // ================= a new action clears the steps forward
  await w.eval(`patchTask(${t2}, {priority: 3})`); await sleep(100);
  check(hl('redo') === 0 && btn('redo').disabled, 'a new action clears the redo steps');
  await key('z');
  check((await get(t2)).priority === 5, 'undo of the new action');

  // ================= keyboard never inside text fields (the browser's own text undo)
  const n0 = hl('undo');
  const qi = d.querySelector('#qinput'); qi.focus();
  const ke = await key('z', {target: qi});
  check(!ke.defaultPrevented && hl('undo') === n0, 'Ctrl+Z in an input: not taken over');
  const ke2 = await key('y', {target: qi});
  check(!ke2.defaultPrevented, 'Ctrl+Y in an input: not taken over');
  qi.blur();
  const ce = d.createElement('div'); ce.contentEditable = 'true'; d.body.appendChild(ce);
  Object.defineProperty(ce, 'isContentEditable', {value: true});
  const ke3 = await key('z', {target: ce});
  check(!ke3.defaultPrevented && hl('undo') === n0, 'Ctrl+Z in contenteditable: not taken over'); ce.remove();

  // ================= text edits: one step per field and editing session
  w.eval(`openDetail(${t2})`); await sleep(400);
  let ti = d.querySelector('#d-title');
  ti.focus(); ti.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true}));
  const type = async (el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(750); };
  const n1 = hl('undo');
  await type(ti, 'Call the bank'); await type(ti, 'Call the bank today'); await type(ti, 'Call the bank today!');
  ti.blur(); ti.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true})); await sleep(400);
  for (let i = 0; i < 20 && (await get(t2)).title !== 'Call the bank today!'; i++) await sleep(250);  // slow CI runners
  await sleep(300);
  check((await get(t2)).title === 'Call the bank today!', 'three saves while typing');
  check(hl('undo') === n1 + 1, `one history step for the whole session (${hl('undo') - n1})`);
  check(btn('undo').getAttribute('aria-label') === 'Undo: Renamed “Call the bank today!”', `label: ${btn('undo').getAttribute('aria-label')}`);
  ti = d.querySelector('#d-title'); ti.focus(); ti.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true}));
  await type(ti, 'Call the bank tomorrow');
  ti.blur(); ti.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true})); await sleep(400);
  await until(async () => (await get(t2)).title === 'Call the bank tomorrow'); await sleep(300);
  check(hl('undo') === n1 + 2, 'a new focus is a new step');
  const ta = d.querySelector('#d-content'); ta.focus(); ta.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true}));
  await type(ta, 'IBAN'); await type(ta, 'IBAN DE00');
  ta.blur(); ta.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true})); await sleep(400);
  check(hl('undo') === n1 + 3 && /Description of/.test(btn('undo').getAttribute('aria-label')), 'description: its own step');
  await key('z');
  check(((await get(t2)).content || '') === '', 'undo description: empty again');
  await key('z');
  check((await get(t2)).title === 'Call the bank today!', 'undo second session');
  await key('z');
  check((await get(t2)).title === 'Call bank', 'undo first session: the title before typing');
  check(d.querySelector('#d-title')?.value === 'Call bank', 'the open detail shows it');
  // native text undo still works: the history does not touch the field while it has the focus
  ti = d.querySelector('#d-title'); ti.focus();
  const nk = await key('z', {target: ti});
  check(!nk.defaultPrevented && (await get(t2)).title === 'Call bank', 'Ctrl+Z while typing in the title is left to the browser');
  ti.blur();
  w.eval('closeDetail()'); await sleep(200);

  // ================= conflict: a second session changes the field in between
  await w.eval(`patchTask(${t2}, {priority: 1})`); await sleep(100);
  await call('PATCH', `/api/tasks/${t2}`, {priority: 3});  // the same user on another device (API)
  await key('z');
  check((await get(t2)).priority === 3, 'undo does not overwrite the change made elsewhere');
  check(/Changed elsewhere, not undone: “Call bank”: Priority/.test(toastText(d)), `conflict reported: ${toastText(d)}`);
  // redo after a conflict: again only if the value is still the expected one
  check(hl('redo') >= 1, 'the step went to the redo side (partly done)');
  await key('y');
  check((await get(t2)).priority === 3 && /Changed elsewhere, not redone/.test(toastText(d)), 'redo respects the conflict too');
  // another member: title in a shared list
  await w.eval(`go('l/${SH}')`); await sleep(300);
  await w.eval(`patchTask(${s1}, {title: 'Plan the trip'})`); await sleep(100);
  await call('PATCH', `/api/tasks/${s1}`, {title: 'Plan trip to Rome'}, BK);
  await key('z');
  check((await get(s1)).title === 'Plan trip to Rome' && /not undone/.test(toastText(d)), "bob's title stays");
  // custom field values (per field id)
  await w.eval(`patchTask(${s2}, {fields: {${FLD}: '500'}})`); await sleep(100);
  check(btn('undo').getAttribute('aria-label') === 'Undo: Budget of “Book hotel”', `field step label: ${btn('undo').getAttribute('aria-label')}`);
  await key('z');
  check(!(await get(s2)).fields?.[FLD], 'undo custom field value');
  await key('y');
  check((await get(s2)).fields?.[FLD] === '500', 'redo custom field value');
  await call('PATCH', `/api/tasks/${s2}`, {fields: {[FLD]: '700'}}, BK);
  await key('z');
  check((await get(s2)).fields?.[FLD] === '700' && /Budget/.test(toastText(d)), `custom field changed by bob stays: ${toastText(d)}`);

  // ================= trash guard: someone else changed the task after the undo
  await w.eval(`deleteTask(${s2})`); await sleep(200);
  await key('z');
  check((await get(s2)).deleted_at === null, 'delete undone');
  await sleep(1100);
  await call('PATCH', `/api/tasks/${s2}`, {title: 'Book the hotel'}, BK);
  await key('y');
  check((await get(s2)).deleted_at === null && /changed by someone else/.test(toastText(d)), `redo delete refused: ${toastText(d)}`);
  check(hl('redo') === 0, 'the refused step left the history');
  const cr = await w.eval(`createTask({title: 'Rent car', list_id: ${SH}})`);
  await sleep(1100);
  await call('PATCH', `/api/tasks/${cr.id}`, {priority: 5}, BK);
  await key('z');
  check((await get(cr.id)).deleted_at === null, 'undo of a create does not trash what another member changed');

  // ================= sections: rename, delete with its tasks, order
  const secs = async () => (await st()).sections.filter(s => s.list_id === SH);
  const A = (await call('POST', '/api/sections', {list_id: SH, name: 'Todo'})).id, Bsec = (await call('POST', '/api/sections', {list_id: SH, name: 'Done'})).id;
  await call('PATCH', `/api/tasks/${s1}`, {section_id: A});
  await w.eval('load().then(render)'); await sleep(200);
  await w.eval(`sectionRename(${A}, 'Open')`);
  await key('z');
  check((await secs()).find(s => s.id === A).name === 'Todo', 'section rename undone');
  await key('y');
  check((await secs()).find(s => s.id === A).name === 'Open', 'section rename redone');
  await w.eval(`sectionDelete(${A})`); await sleep(200);
  check(!(await secs()).some(s => s.id === A) && (await get(s1)).section_id === null, 'section deleted, its task stays');
  await key('z');
  const back = (await secs()).find(s => s.name === 'Open');
  check(back && (await get(s1)).section_id === back.id, 'undo: the section is back with its task');
  check((await secs())[0]?.name === 'Open', 'at its old place');
  await key('y');
  check(!(await secs()).some(s => s.name === 'Open'), 'redo: deleted again');
  await key('z');
  const back2 = (await secs()).find(s => s.name === 'Open');
  check(back2 && (await get(s1)).section_id === back2.id, 'undo again (the re-created id is followed)');
  await w.eval(`saveSectionOrder(${SH}, [${Bsec}, ${back2.id}])`);
  check((await secs()).map(s => s.id).join() === [Bsec, back2.id].join(), 'sections reordered');
  await key('z');
  check((await secs()).map(s => s.id).join() === [back2.id, Bsec].join(), 'section order undone');

  // ================= lists: folder, order, settings
  const lst = async id => (await st()).lists.find(l => l.id === id);
  await w.eval(`setListFolder(${HOME}, 'Private')`);
  check((await lst(HOME)).folder === 'Private', 'list into a folder');
  check(btn('undo').getAttribute('aria-label') === 'Undo: Moved “Home” to folder Private', `folder label: ${btn('undo').getAttribute('aria-label')}`);
  await key('z');
  check((await lst(HOME)).folder === '', 'undo: out of the folder again');
  await key('y');
  check((await lst(HOME)).folder === 'Private', 'redo: in the folder again');
  await w.eval(`setListFolder(${HOME}, '')`); await sleep(100);
  const ord = async () => (await st()).lists.filter(l => !l.is_inbox).sort((a, b) => a.sort - b.sort || a.id - b.id).map(l => l.id);
  const o0 = await ord();
  await w.eval(`moveList(${o0[1]}, -1)`); await sleep(300);
  check((await ord())[0] === o0[1], 'list moved up');
  await key('z');
  check((await ord()).join() === o0.join(), 'list order undone');
  await w.eval(`listPatch(${WORK}, {color: '#f87171', name: 'Office'})`);
  check((await lst(WORK)).name === 'Office', 'list settings saved');
  await key('z');
  const lw = await lst(WORK);
  check(lw.name === 'Work' && lw.color === '', 'list settings undone (name + colour)');

  // ================= batch
  await w.eval(`go('l/${WORK}')`); await sleep(300);
  const u1 = await mk('Batch one', WORK), u2 = await mk('Batch two', WORK);
  await w.eval('load().then(render)'); await sleep(200);
  w.eval(`S.multi = new Set([${u1}, ${u2}])`);
  await w.eval(`batch('patch', {list_id: ${HOME}}, true)`); await sleep(200);
  check(btn('undo').getAttribute('aria-label') === 'Undo: Moved 2 tasks to Home', `batch label: ${btn('undo').getAttribute('aria-label')}`);
  await key('z');
  check((await get(u1)).list_id === WORK && (await get(u2)).list_id === WORK, 'batch move undone (one request)');
  await key('y');
  check((await get(u1)).list_id === HOME && (await get(u2)).list_id === HOME, 'batch move redone');
  w.eval(`S.multi = new Set([${u1}, ${u2}])`);
  await w.eval(`batch('complete', {}, true)`); await sleep(200);
  await key('z');
  check((await get(u1)).status === 0 && (await get(u2)).status === 0, 'batch complete undone');
  await key('y');
  check((await get(u1)).status === 2 && (await get(u2)).status === 2, 'batch complete redone');

  // ================= roadmap: moving a whole project
  const P = (await call('POST', '/api/lists', {name: 'Campaign', kind: 'project'})).id;
  const p1 = await mk('Brief', P, {due: addD(today(), 3)}), p2 = await mk('Launch', P, {start: addD(today(), 5), due: addD(today(), 9)});
  await w.eval('load().then(render)'); await sleep(200);
  await w.eval(`rmShift(${P}, 7)`); await sleep(200);
  check((await get(p1)).due === addD(today(), 10) && (await get(p2)).start === addD(today(), 12), 'project moved by 7 days');
  check(btn('undo').getAttribute('aria-label') === 'Undo: Shifted project “Campaign” by 7 days', `shift label: ${btn('undo').getAttribute('aria-label')}`);
  await key('z');
  check((await get(p1)).due === addD(today(), 3) && (await get(p2)).due === addD(today(), 9), 'project shift undone');
  await key('y');
  check((await get(p1)).due === addD(today(), 10) && (await get(p2)).due === addD(today(), 16), 'project shift redone');

  // ================= history menu: jump several steps
  await w.eval(`go('l/${WORK}')`); await sleep(300);
  const j1 = await mk('Jump', WORK); await w.eval('load().then(render)'); await sleep(200);
  for (const p of [1, 3, 5, 0]) { await w.eval(`patchTask(${j1}, {priority: ${p}})`); await sleep(60); }
  btn('undo').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  await sleep(100);
  const items = [...d.querySelectorAll('#pop:not(.hidden) .menu-list button[data-i]')];
  check(items.length === 10 && d.querySelector('#pop .hhead')?.textContent === 'Undo up to here', `right-click: the last 10 steps (${items.length})`);
  check(/Priority of “Jump”: None/.test(items[0]?.textContent) && /Priority of “Jump”: High/.test(items[1]?.textContent), 'newest first');
  const before = hl('undo');
  items[2].click(); await sleep(50); await idle();
  check((await get(j1)).priority === 1 && hl('undo') === before - 3 && hl('redo') >= 3, 'third entry: three steps undone in order');
  check(/3 steps undone/.test(toastText(d)), `toast counts the steps: ${toastText(d)}`);
  // long-press (touch) opens the same menu
  const tev = type2 => { const e = new w.Event(type2, {bubbles: true, cancelable: true}); e.touches = type2 === 'touchend' ? [] : [{clientX: 5, clientY: 5}]; btn('redo').dispatchEvent(e); return e; };
  w.eval('closePop()');
  tev('touchstart'); await sleep(600);
  check(!!d.querySelector('#pop:not(.hidden) .menu-list button[data-i]') && d.querySelector('#pop .hhead')?.textContent === 'Redo up to here', 'long-press on → lists the redo steps');
  tev('touchend'); await sleep(50);
  const nb = hl('redo'); btn('redo').click(); await sleep(50); await idle();
  check(hl('redo') === nb, 'the click that ends a long-press does not also redo');
  w.eval('closePop()'); await sleep(500);

  // ================= offline: cancel a queued step, queue an undo / redo, pending state
  w.__offline = true;
  const o1 = await mk('Offline one', WORK); await sleep(10);
  w.__offline = false; await w.eval('load().then(render)'); await sleep(200); w.__offline = true;
  await w.eval(`toggleTask(${o1})`); await sleep(200);
  check(w.eval('OUT.q.length') === 1 && btn('undo').classList.contains('pend') && /waiting for the connection/.test(btn('undo').title), 'queued step: ← shows it is pending');
  await key('z');
  check(w.eval('OUT.q.length') === 0 && w.eval(`S.tasks.get(${o1}).status`) === 0, 'undo before sync: taken out of the queue');
  await key('y');
  check(w.eval('OUT.q.length') === 1 && w.eval(`S.tasks.get(${o1}).status`) === 2 && btn('undo').classList.contains('pend'), 'redo offline: queued again');
  w.__offline = false; await w.eval('flush()'); await sleep(300);
  check((await get(o1)).status === 2, 'synced: completed on the server');
  await w.eval(`patchTask(${o1}, {priority: 5})`); await sleep(100);
  w.__offline = true;
  await key('z');
  check(w.eval('OUT.q.length') === 1 && w.eval(`S.tasks.get(${o1}).priority`) === 0 && btn('redo').classList.contains('pend'), 'undo offline: the reverse is queued, → pending');
  check(/sent as soon as you are online/.test(toastText(d)), 'toast says it waits');
  check((await get(o1)).priority === 5, 'not on the server yet');
  w.__offline = false; await w.eval('flush()'); await sleep(300);
  check((await get(o1)).priority === 0 && !btn('redo').classList.contains('pend'), 'online: the queued undo arrived');
  // sections need a connection: offline they stay in the history
  const nu = hl('undo');
  await w.eval(`sectionCreate(${WORK}, 'Offline test')`);
  w.__offline = true;
  await key('z');
  check(hl('undo') === nu + 1 && /Offline/.test(toastText(d)), 'offline: a section step stays (needs a connection)');
  w.__offline = false; await key('z');
  check(!(await st()).sections.some(s => s.name === 'Offline test'), 'online again: undone');
  w.close();

  // ================= view-only: the list became view-only in the meantime (bob)
  let wb = await boot({user: 'bob', hash: 'l/' + SH}); const db = wb.document;
  await wb.eval(`patchTask(${s1}, {priority: 5})`); await sleep(100);
  check(wb.eval('HIST.undo.length') === 1, 'bob: step recorded');
  await call('PUT', `/api/lists/${SH}/members`, {user_id: BOB, role: 'view'});
  await wb.eval('load().then(render)'); await sleep(200);
  db.dispatchEvent(new wb.KeyboardEvent('keydown', {key: 'z', ctrlKey: true, bubbles: true, cancelable: true})); await sleep(400);
  check((await get(s1)).priority === 5, 'view-only: nothing changed on the server');
  check(/View only/.test(db.querySelector('#toast:not(.hidden)')?.textContent || '') && wb.eval('HIST.undo.length') === 0, 'refused with a toast, the step leaves the history');
  wb.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
