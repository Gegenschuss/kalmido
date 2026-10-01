// Package D2 UI tests (jsdom), fresh DB on the test container: the timeline as a Gantt chart. Dependency arrows
// (normal, conflict, completed blocker, off-view stub) in the list timeline and the calendar's timeline mode, the
// conflict / waiting marks on the bars, linking by dragging the dot (synthetic pointer events: rubber band, valid /
// invalid targets, the server's error as a toast, "already linked"), removing via the arrow's popover, the touch path
// (long-press menu -> "Connect to…" -> tap), the keyboard path (C, Enter, Escape, context menu key), "Move dependent
// tasks along" (list dialog, drag a bar, one undo for the whole chain), a view-only member (no linking, no remove),
// the modules "deps" / "fields" switched off, German texts.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const ds = n => { const d = new Date(Date.now() + n * 864e5); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const ptr = (w, el, type, x = 0, extra = {}) => {  // jsdom has no PointerEvent: a MouseEvent with pointerType / pointerId
  const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, button: 0, clientX: x, clientY: 10, ...extra});
  Object.defineProperty(e, 'pointerType', {value: extra.pointerType || 'mouse'}); Object.defineProperty(e, 'pointerId', {value: 1});
  el.dispatchEvent(e);
};
const touch = (w, el, type, x = 10) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' ? [] : [{clientX: x, clientY: 10}]; el.dispatchEvent(e); return e; };
const key = (w, el, k, extra = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...extra}));
const blockers = async (id, ck = CK) => ((await call('GET', '/api/state', null, ck)).tasks.find(t => t.id === id) || {}).blockers || [];
const taskOf = async (id, ck = CK) => (await call('GET', '/api/state', null, ck)).tasks.find(t => t.id === id);
const toastText = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const BK = await login('bob'), CKc = await login('carol');
  await call('PATCH', '/api/settings', {lang: 'de'}, BK);
  const PRJ = (await call('POST', '/api/lists', {name: 'Relaunch', view: 'timeline', kind: 'project'})).id;
  const HOME = (await call('POST', '/api/lists', {name: 'Home', kind: 'project'})).id;
  await call('PUT', `/api/lists/${PRJ}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${PRJ}/members`, {user_id: CAROL, role: 'view'});
  const mk = async (title, start, due, list = PRJ) => (await call('POST', '/api/tasks', {title, list_id: list, ...(start != null ? {start: ds(start)} : {}), due: ds(due)})).id;
  const A = await mk('Design', 0, 2), Bt = await mk('Build', 1, 4), Cc = await mk('Launch', 6, 7), E = await mk('Copy', null, 3), Dn = await mk('Research', null, 0);
  const X = await mk('Budget ok', null, 3, HOME);
  const dep = (w, b) => call('POST', '/api/deps', {task_id: w, blocker_id: b});
  await dep(Bt, A); await dep(Cc, Bt); await dep(Bt, Dn); await dep(Cc, X);
  await call('POST', `/api/tasks/${Dn}/complete`);

  // ================= arrows in the list timeline (alice, desktop)
  let w = await boot({user: 'alice', hash: 'l/' + PRJ}); let d = w.document;
  check(await until(() => d.querySelector('#tl-deps g.dep.done')), 'list timeline: SVG overlay with arrows (completed blockers loaded from GET /api/deps)');
  const g = k => d.querySelector(`#tl-deps g.dep[data-dep="${k}"]`);
  check(g(`${Bt}:${A}`) && g(`${Bt}:${A}`).classList.contains('conf'), 'Build starts before Design is due: conflict arrow');
  check(g(`${Cc}:${Bt}`) && g(`${Cc}:${Bt}`).classList.contains('ok') && !g(`${Cc}:${Bt}`).classList.contains('stub'), 'Launch after Build: normal arrow between two bars');
  check(g(`${Bt}:${Dn}`)?.classList.contains('done') && g(`${Bt}:${Dn}`).classList.contains('stub'), 'completed blocker: muted stub arrow');
  check(g(`${Cc}:${X}`)?.classList.contains('stub') && /outside this view/.test(g(`${Cc}:${X}`).querySelector('title').textContent), 'blocker in another list: stub with tooltip');
  check(/“Build” starts before “Design” is due/.test(g(`${Bt}:${A}`).querySelector('title').textContent), 'conflict tooltip on the arrow');
  check(g(`${Cc}:${Bt}`).querySelector('path.ln').getAttribute('marker-end') === 'url(#tl-ah-ok)' && d.querySelector('#tl-ah-conf') && d.querySelector('#tl-ah-done'), 'arrowheads (markers per state)');
  check(/^M[\d.]+,[\d.]+(L|Q)/.test(g(`${Cc}:${Bt}`).querySelector('path.ln').getAttribute('d')), 'orthogonal path with elbows');
  const bar = id => d.querySelector(`.tl-bar[data-id="${id}"]`);
  check(bar(Bt).classList.contains('wait') && bar(Bt).classList.contains('conf') && bar(Bt).querySelector('.tl-lk'), 'waiting + conflicting bar: hatch class, lock mark, conflict edge');
  check(/Starts before “Design” is due/.test(bar(Bt).title) && /Waiting on/.test(bar(Bt).title), 'bar tooltip names the conflict and what it waits on');
  check(bar(Cc).classList.contains('wait') && !bar(Cc).classList.contains('conf'), 'waiting without conflict: no conflict mark');
  check(!bar(A).classList.contains('wait') && bar(A).getAttribute('tabindex') === '0' && bar(A).getAttribute('role') === 'button', 'free bar: focusable, no waiting mark');
  check(d.querySelectorAll('.tl-knob').length === 4, 'a link dot per bar I can change');
  check(/Drag the dot at the end of a bar onto another bar/.test(d.querySelector('.tl-foot').textContent), 'hint for linking');

  // ---- drag to link: dot of "Copy" onto "Launch"
  const knob = id => d.querySelector(`.tl-knob[data-knob="${id}"]`);
  ptr(w, knob(E), 'pointerdown', 0);
  check(d.querySelector('.tl.linking') && bar(Cc).classList.contains('tl-ok') && bar(E).classList.contains('tl-from'), 'drag started: valid targets marked');
  check(bar(A).classList.contains('tl-ok') && !bar(Bt).classList.contains('tl-no'), 'unrelated tasks are valid targets');
  ptr(w, bar(Cc), 'pointermove', 60);
  check(bar(Cc).classList.contains('hot') && /^M[\d.]+,[\d.]+L/.test(d.querySelector('#tl-deps .rubber').getAttribute('d')), 'rubber band to the hovered target');
  ptr(w, bar(Cc), 'pointerup', 60);
  check(await until(async () => (await blockers(Cc)).includes(E)), 'drop: Launch now waits on Copy (server)');
  check(await until(() => /“Launch” now waits on “Copy”/.test(toastText(d))), 'toast after linking');
  check(await until(() => g(`${Cc}:${E}`)), 'new arrow drawn');
  check(!d.querySelector('.tl.linking') && !d.querySelector('.tl-bar.tl-ok'), 'link marks cleared');
  // invalid: Launch -> Design would be a loop (Launch waits on Build waits on Design)
  ptr(w, knob(Cc), 'pointerdown', 0);
  check(bar(A).classList.contains('tl-no') && bar(Bt).classList.contains('tl-no'), 'a target that would create a loop is marked not allowed');
  ptr(w, bar(A), 'pointermove', 40);
  check(d.querySelector('#tl-deps .rubber').classList.contains('no'), 'rubber band turns red over an invalid target');
  ptr(w, bar(A), 'pointerup', 40);
  check(await until(() => /circular/.test(toastText(d))), `server error as a toast: ${toastText(d)}`);
  check(!(await blockers(A)).includes(Cc), 'no loop created');
  // already linked
  ptr(w, knob(A), 'pointerdown', 0); ptr(w, bar(Bt), 'pointermove', 40); ptr(w, bar(Bt), 'pointerup', 40);
  check(await until(() => /already waits on/.test(toastText(d))), 'already linked: toast');
  // a click on the dot (no movement) starts "Connect to…"
  ptr(w, knob(A), 'pointerdown', 0); ptr(w, knob(A), 'pointerup', 0);
  check(await until(() => d.querySelector('.tl-pick')), 'click on the dot: "Connect to…" mode');
  key(w, d.body, 'Escape');
  check(!d.querySelector('.tl-pick'), 'Escape leaves the mode');

  // ---- remove via the arrow's popover
  g(`${Cc}:${E}`).querySelector('.hit').dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  await sleep(100);
  let pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Remove dependency/.test(pop.textContent) && /Open “Copy”/.test(pop.textContent) && /Open “Launch”/.test(pop.textContent), 'arrow click: popover with remove + open both tasks');
  [...pop.querySelectorAll('button')].find(b => /Remove dependency/.test(b.textContent)).click();
  check(await until(async () => !(await blockers(Cc)).includes(E)), 'popover: dependency removed on the server');
  check(await until(() => !g(`${Cc}:${E}`) && /Dependency removed/.test(toastText(d))), 'arrow gone + toast');

  // ---- keyboard: focus a bar, C, then Enter on the target; context menu key
  bar(E).focus(); key(w, bar(E), 'c');
  check(d.querySelector('.tl-pick') && /Tap the task that waits on “Copy”/.test(d.querySelector('.tl-pick').textContent) && d.activeElement === bar(E), 'C: "Connect to…" mode, focus stays on the bar');
  check(bar(Cc).classList.contains('tl-ok') && !d.querySelector('.tl-knob'), 'mode: targets marked, no dots');
  key(w, bar(E), 'ArrowDown');
  check(d.activeElement && d.activeElement.classList.contains('tl-bar'), 'arrow keys move between bars');
  key(w, bar(Cc), 'Enter');
  check(await until(async () => (await blockers(Cc)).includes(E)), 'Enter on the target links it');
  check(await until(() => !d.querySelector('.tl-pick')), 'mode ends after linking');
  await until(() => /“Launch” now waits on “Copy”/.test(toastText(d)));  // the state is reloaded before the toast
  bar(Cc).focus(); key(w, bar(Cc), 'F10', {shiftKey: true}); await sleep(100);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Connect to…/.test(pop.textContent) && /Pick from a list…/.test(pop.textContent) && /Stop waiting on “Copy”/.test(pop.textContent), 'Shift+F10: bar menu with connect, list picker and remove');
  [...pop.querySelectorAll('button')].find(b => /Stop waiting on “Copy”/.test(b.textContent)).click();
  check(await until(async () => !(await blockers(Cc)).includes(E)), 'bar menu: remove');
  bar(A).focus(); key(w, bar(A), 'Enter'); await sleep(300);
  check(w.eval('S.sel') === A, 'Enter opens the task');
  w.eval('closeDetail()');
  check(errs.length === 0, 'no script errors (desktop): ' + errs.join(' | '));
  w.close();

  // ================= touch: long-press + let go -> menu -> "Connect to…" -> tap the target (bob, phone)
  w = await boot({user: 'bob', hash: 'l/' + PRJ, mobile: true, media: {'(hover: none)': true}}); d = w.document;
  await until(() => d.querySelector('#tl-deps g.dep'));
  check(/Einen Balken lange drücken/.test(d.querySelector('.tl-foot').textContent), 'German touch hint');
  touch(w, bar(E), 'touchstart'); await sleep(380);
  const te = touch(w, bar(E), 'touchend');
  check(te.defaultPrevented, 'no click after the hold');
  await sleep(100);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Verbinden mit…/.test(pop.textContent) && /Aus einer Liste wählen…/.test(pop.textContent), 'long-press: action sheet (German)');
  [...pop.querySelectorAll('button')].find(b => /Verbinden mit/.test(b.textContent)).click(); await sleep(100);
  check(d.querySelector('.tl-pick') && /Tippe auf die Aufgabe, die auf „Copy“ wartet/.test(d.querySelector('.tl-pick').textContent), 'connect mode banner (German)');
  bar(A).dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  check(await until(async () => (await blockers(A, BK)).includes(E)), 'tap on the target links it (Design waits on Copy)');
  check(await until(() => /„Design“ wartet jetzt auf „Copy“/.test(toastText(d))), 'German toast');
  // "Pick from a list…": the searchable picker
  touch(w, bar(E), 'touchstart'); await sleep(380); touch(w, bar(E), 'touchend'); await sleep(100);
  [...d.querySelectorAll('#pop button')].find(b => /Aus einer Liste/.test(b.textContent)).click(); await sleep(200);
  const pm = lastModal(d);
  check(pm && pm.querySelector('#dp-q') && pm.querySelector('[data-pick]'), 'list picker with search');
  pm.remove();
  // long-press and drag still moves the bar (no menu)
  const dueE = (await taskOf(E, BK)).due;
  touch(w, bar(E), 'touchstart', 10); await sleep(380);
  touch(w, bar(E), 'touchmove', 10 + 2 * 30); touch(w, bar(E), 'touchend');
  check(await until(async () => (await taskOf(E, BK)).due !== dueE), 'long-press + drag moves the bar');
  check(!d.querySelector('#pop:not(.hidden) .menu-list') || !/Verbinden/.test(d.querySelector('#pop').textContent), 'no menu after a drag');
  check(errs.length === 0, 'no script errors (touch): ' + errs.join(' | '));
  w.close();
  await call('DELETE', `/api/deps/${A}/${E}`);
  await call('PATCH', `/api/tasks/${E}`, {due: ds(3)});

  // ================= "Move dependent tasks along": list dialog + drag a bar + one undo
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  w.eval(`listModal(${PRJ})`); await sleep(200);
  let md = lastModal(d);
  check(md.querySelector('#l-depshift') && !md.querySelector('#l-depshift').checked && /Move dependent tasks along/.test(md.textContent), 'list dialog: setting, off by default');
  md.querySelector('#l-depshift').checked = true; md.querySelector('#l-depshift').dispatchEvent(new w.Event('change', {bubbles: true}));  // 1.5.1: saves itself
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === PRJ).dep_shift === 1), 'setting saved');
  await until(() => bar(A));
  const DW = w.eval('tlDW()');
  const b0 = await taskOf(Bt), c0 = await taskOf(Cc), a0 = await taskOf(A);
  ptr(w, bar(A), 'pointerdown', 0); ptr(w, d, 'pointermove', 3 * DW);
  ptr(w, d, 'pointerup', 3 * DW);
  check(await until(async () => (await taskOf(A)).due === ds(5)), 'drag: Design due +3 days');
  check(await until(async () => (await taskOf(Bt)).start === ds(4) && (await taskOf(Bt)).due === ds(7)), 'Build moved along by 3 days (duration kept)');
  check((await taskOf(Cc)).start === ds(9), 'Launch moved along too (second level)');
  check(await until(() => /2 dependent tasks moved/.test(toastText(d)) && d.querySelector('#toast button')), `toast "2 dependent tasks moved" with Undo: ${toastText(d)}`);
  d.querySelector('#toast button').click();
  check(await until(async () => (await taskOf(A)).due === a0.due && (await taskOf(Bt)).start === b0.start && (await taskOf(Bt)).due === b0.due && (await taskOf(Cc)).start === c0.start), 'one undo takes the whole chain back');
  check(errs.length === 0, 'no script errors (auto-shift): ' + errs.join(' | '));
  w.close();

  // ================= view-only member: arrows yes, linking / removing no
  w = await boot({user: 'carol', hash: 'l/' + PRJ}); d = w.document;
  check(await until(() => d.querySelector('#tl-deps g.dep')), 'view-only: arrows shown');
  check(!d.querySelector('.tl-knob') && bar(A).classList.contains('ro'), 'view-only: no link dots, bars read-only');
  bar(A).focus(); key(w, bar(A), 'c');
  check(!d.querySelector('.tl-pick'), 'view-only: C does nothing');
  g(`${Bt}:${A}`).querySelector('.hit').dispatchEvent(new w.MouseEvent('click', {bubbles: true})); await sleep(100);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && !/Remove dependency/.test(pop.textContent) && /Open “Design”/.test(pop.textContent), 'view-only: popover without remove');
  w.eval('closePop()');
  const r = await call('POST', '/api/deps', {task_id: A, blocker_id: E}, CKc);
  check(r.error, 'view-only: the server refuses linking too');
  w.close();

  // ================= calendar "Timeline" mode
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"timeline"'}}); d = w.document;
  check(await until(() => g(`${Bt}:${A}`) && g(`${Cc}:${X}`) && !g(`${Cc}:${X}`).classList.contains('stub')), 'calendar timeline: arrows across lists (Budget ok is a bar here)');
  check(errs.length === 0, 'no script errors (calendar): ' + errs.join(' | '));
  w.close();

  // ================= list types: selector, badge, hidden controls, sidebar menu, progress "x"
  const PL = (await call('POST', '/api/lists', {name: 'Groceries'})).id;
  const pt = (await call('POST', '/api/tasks', {title: 'Milk', list_id: PL})).id;
  w = await boot({user: 'alice', hash: 'l/' + PL}); d = w.document;
  check(!d.querySelector('#top .kbadge'), 'plain list: no Project badge');
  w.eval(`openDetail(${pt})`); await sleep(300);
  check(!d.querySelector('#d-time') && !d.querySelector('[data-act="timer-toggle"]') && !d.querySelector('#d-deps'), 'plain list: no timer, no time, no waiting on in the details');
  w.eval(`openDetail(${E})`); await sleep(300);
  check(d.querySelector('#d-time') && d.querySelector('[data-act="timer-toggle"]') && d.querySelector('#d-deps'), 'project list: timer, time and dependencies in the details');
  w.eval('closeDetail()');
  w.eval('listModal()'); await sleep(200);
  md = lastModal(d);
  check(md.querySelector('#l-kind').value === 'list' && [...md.querySelectorAll('#l-kind option')].map(o => o.value).join() === 'list,checklist,project', 'new list dialog: type selector, default List');
  check(md.querySelector('.kproj').hidden, 'type List: project settings hidden');
  change(w, md.querySelector('#l-kind'), 'project');
  check(!md.querySelector('.kproj').hidden && /time tracking, dependencies with the Gantt timeline, custom fields, progress and status/.test(md.querySelector('#l-khint').textContent), 'type Project: hint names the features that are on');
  change(w, md.querySelector('#l-kind'), 'checklist');
  check(/shopping and packing/i.test(md.querySelector('#l-khint').textContent) && /stays at the bottom and comes back with one tap/.test(md.querySelector('#l-khint').textContent), 'type Shopping & packing list (2.7.0): its hint');
  md.remove();
  const srow = d.querySelector(`#side .srow[data-list="${PL}"]`);
  srow.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true})); await sleep(100);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Shopping & packing list/.test(pop.textContent) && /Project/.test(pop.textContent) && /Edit list…/.test(pop.textContent), 'sidebar context menu: the types');
  [...pop.querySelectorAll('button')].find(b => b.textContent.trim() === 'Project').click();
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === PL).kind === 'project'), 'context menu: type changed on the server');
  check(await until(() => d.querySelector('#top .kbadge') && /Project/.test(d.querySelector('#top .kbadge').textContent)), 'Project badge in the header');
  w.eval(`openDetail(${pt})`); await sleep(300);
  check(d.querySelector('[data-act="timer-toggle"]'), 'after switching to Project: timer button there');
  w.eval('closeDetail()');
  w.close();
  // progress "x": per user and list, server-side, back via the list menu and the list dialog
  w = await boot({user: 'alice', hash: 'l/' + HOME}); d = w.document;
  check(d.querySelector('.lhead .lprog') && d.querySelector('.lhead .lpx[aria-label="Hide progress"]'), 'project list: progress bar with an x');
  d.querySelector('.lhead .lpx').click();
  check(await until(async () => (await call('GET', '/api/state')).settings.hide_progress.split(',').includes(String(HOME))) && !d.querySelector('.lhead .lprog'), 'x: bar hidden, stored for the user');
  d.querySelector('#top [data-act="top-more"]').click(); await sleep(100);  // 1.5: the list menu is part of the header's "…"
  pop = d.querySelector('#pop:not(.hidden)');
  const sp = [...pop.querySelectorAll('button')].find(b => /Show progress/.test(b.textContent));
  check(sp, 'list menu: Show progress');
  sp.click();
  check(await until(() => d.querySelector('.lhead .lprog')), 'Show progress brings it back');
  w.eval(`listModal(${HOME})`); await sleep(200);
  md = lastModal(d);
  check(md.querySelector('#l-showprog') && md.querySelector('#l-showprog').checked, 'list dialog: progress toggle');
  md.querySelector('#l-showprog').checked = false; md.querySelector('#l-showprog').dispatchEvent(new w.Event('change', {bubbles: true}));  // 1.5.1: saves itself
  check(await until(() => !d.querySelector('.lhead .lprog')), 'list dialog: hides it too');
  const bw = await boot({user: 'bob', hash: 'l/' + PRJ});
  check(!bw.eval(`progHidden(${HOME})`), 'hiding is per user');
  bw.close();
  await call('PATCH', '/api/settings', {hide_progress: ''});
  check(errs.length === 0, 'no script errors (list types): ' + errs.join(' | '));
  w.close();

  // ================= modules off: no arrows, no dots, no waiting marks, no dependency section / custom fields
  const st = await call('GET', '/api/state');
  const full = st.settings.features;
  await call('PATCH', '/api/settings', {features: full.split(',').filter(f => f !== 'deps' && f !== 'fields').join(',')});
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  check(bar(A) && !d.querySelector('#tl-deps') && !d.querySelector('.tl-knob') && !d.querySelector('.tl-bar.wait'), 'deps off: plain timeline');
  check(!/Drag the dot/.test(d.querySelector('.tl-foot').textContent), 'deps off: no linking hint');
  w.eval(`openDetail(${Bt})`); await sleep(300);
  check(!d.querySelector('#d-deps'), 'deps off: no dependency section in the details');
  w.eval(`listModal(${PRJ})`); await sleep(200);
  md = lastModal(d);
  check(!md.querySelector('#l-depshift') && !md.querySelector('#l-fields'), 'deps + fields off: no auto-shift setting, no custom fields in the list dialog');
  md.remove();
  w.eval(`settingsModal('layout')`); await sleep(300);
  const fg = d.querySelector('[data-feat="deps"]'), ff = d.querySelector('[data-feat="fields"]');
  check(fg && ff && !fg.checked && !ff.checked && /Dependencies/.test(fg.closest('label').textContent), 'Settings: both modules listed with descriptions, unticked');
  check(errs.length === 0, 'no script errors (modules off): ' + errs.join(' | '));
  w.close();
  await call('PATCH', '/api/settings', {features: full});

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });

