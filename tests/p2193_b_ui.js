// 2.193.0 B UI tests (#2219; fresh DB on the test container, jsdom): the timeline and the roadmap drag on drag.js.
// - mouse: a bar moves by days, its right end changes the due date only, below the threshold it is a click (the task
//   opens), the click after a drag is swallowed, Esc cancels (the bar back, nothing saved)
// - finger: hold a bar, then drag = moved; a swipe during the hold scrolls (nothing moves, no menu); held and let go =
//   the bar menu without a click
// - drawing: a new task across empty days of a section row (hold, then drag: the title field with that range); a swipe
//   over the empty track starts nothing and keeps the page's scroll; an undated task gets its day by a quick tap, a range
//   by hold + drag
// - drag.js scrollX: at the right edge of #tlscroll it scrolls sideways every frame while the pointer stays still, the
//   bar follows the scrolled days; a press inside the edge zone without moving that way does not scroll
// - roadmap: a summary bar dragged with the mouse, Esc puts it back (no shift on the server); finger: a swipe cancels the
//   long press, the hold opens "Move project by…"
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    return r.json().catch(() => ({}));
  }
};
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const ptr = (w, el, type, x = 0, extra = {}) => {  // jsdom has no PointerEvent: a MouseEvent with pointerType / pointerId
  const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, button: 0, clientX: x, clientY: 10, ...extra});
  Object.defineProperty(e, 'pointerType', {value: extra.pointerType || 'mouse'}); Object.defineProperty(e, 'pointerId', {value: 1});
  el.dispatchEvent(e); return e;
};
const touch = (w, el, type, x = 10, y = 10) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' || type === 'touchcancel' ? [] : [{clientX: x, clientY: y}]; el.dispatchEvent(e); return e; };
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const frames = (w, n) => new Promise(r => { const f = () => (n-- <= 0 ? r() : w.requestAnimationFrame(f)); f(); });
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ALL.split(',').filter(x => x !== 'collab')});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Relaunch', kind: 'project', view: 'timeline', dep_shift: false})).id;
  const SD = (await call('POST', '/api/sections', {list_id: P, name: 'Design'})).id;
  const mk = async (title, start, due, sid = SD) => (await call('POST', '/api/tasks', {title, list_id: P, section_id: sid, ...(start != null ? {start: day(start)} : {}), ...(due != null ? {due: day(due)} : {})})).id;
  const A = await mk('Sketches', 0, 2), U = await mk('Undated idea', null, null);
  const taskOf = async id => (await call('GET', '/api/state')).tasks.find(t => t.id === id);
  const reset = async () => { await call('PATCH', `/api/tasks/${A}`, {start: day(0), due: day(2)}); await call('PATCH', `/api/tasks/${U}`, {due: null, start: null}); };
  check(A > 0 && U > 0, 'setup: a project with a dated and an undated task');

  // ================= mouse (desktop)
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  const bar = id => d.querySelector(`.tl-bar[data-id="${id}"]`);
  check(await until(() => bar(A)), 'timeline: the bar is drawn');
  const DW = w.eval('tlDW()');
  ptr(w, bar(A), 'pointerdown', 100); ptr(w, d, 'pointermove', 100 + 2 * DW);
  check(bar(A).classList.contains('drag'), 'mouse: the bar is dragged');
  ptr(w, d, 'pointerup', 100 + 2 * DW);
  bar(A).dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));  // the click that follows the pointerup
  check(await until(async () => (await taskOf(A)).due === day(4) && (await taskOf(A)).start === day(2)), 'mouse: moved by two days (start + due)');
  check(w.eval('S.sel') !== A, 'the click right after the drag does not open the task');
  await w.eval('load()'); w.eval('render()'); await sleep(450);
  // the right end: due only
  ptr(w, bar(A).querySelector('.h.r'), 'pointerdown', 100); ptr(w, d, 'pointermove', 100 + DW); ptr(w, d, 'pointerup', 100 + DW);
  check(await until(async () => (await taskOf(A)).due === day(5) && (await taskOf(A)).start === day(2)), 'mouse: the right end changes the due date only');
  await sleep(450);
  // below the threshold: a click opens the task
  ptr(w, bar(A), 'pointerdown', 100); ptr(w, d, 'pointermove', 102); ptr(w, d, 'pointerup', 102);
  check(!bar(A).classList.contains('drag'), 'mouse: 2 px is no drag');
  bar(A).dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await sleep(200);
  check(w.eval('S.sel') === A, 'below the threshold the click opens the task');
  w.eval('closeDetail?.()'); await sleep(100);
  // Esc cancels
  const left0 = bar(A).style.left;
  ptr(w, bar(A), 'pointerdown', 100); ptr(w, d, 'pointermove', 100 + 3 * DW);
  check(bar(A).style.left !== left0, 'the bar follows the mouse');
  key(w, d.body, 'Escape'); await sleep(150);
  ptr(w, d, 'pointerup', 100 + 3 * DW); await sleep(300);
  check((await taskOf(A)).due === day(5) && !d.querySelector('.tl-bar.drag'), 'Esc: nothing saved, the bar is no longer dragged');
  check(!bar(A) || bar(A).style.left === left0, 'Esc: the bar back where it was');

  // drag.js scrollX: the timeline scrolls sideways at the right edge while the mouse stays still
  const sc = d.querySelector('#tlscroll');
  let sl = 0, steps = 0;
  Object.defineProperty(sc, 'scrollLeft', {configurable: true, get: () => sl, set: v => { sl = v; }});
  sc.scrollBy = (x) => { steps++; sl = Math.max(0, Math.min(2000, sl + x)); };
  sc.getBoundingClientRect = () => ({left: 0, right: 600, top: 0, bottom: 500, width: 600, height: 500});
  ptr(w, bar(A), 'pointerdown', 580); ptr(w, d, 'pointermove', 585);
  await frames(w, 6);
  check(steps === 0, 'a press inside the edge zone without moving that way does not scroll');
  ptr(w, d, 'pointerup', 585); await sleep(450);
  ptr(w, bar(A), 'pointerdown', 300); ptr(w, d, 'pointermove', 590);
  await frames(w, 8);
  const s1 = steps;
  check(s1 >= 4 && sl > 0, `at the right edge it scrolls every frame while the mouse stays still (${s1} steps, ${sl} px)`);
  const n = Math.round((590 - 300 + sl) / DW);
  ptr(w, d, 'pointerup', 590);
  check(await until(async () => (await taskOf(A)).due === day(5 + n)), `the bar follows the scrolled days (+${n}): ${(await taskOf(A)).due} / ${day(5 + n)}`);
  await sleep(150);
  check(steps === s1 || steps === s1 + 1, 'scrolling stops with the drop');
  delete sc.scrollLeft; delete sc.scrollBy; delete sc.getBoundingClientRect;
  check(errs.length === 0, 'no script errors (mouse): ' + errs.join(' | '));
  w.close();
  await reset();

  // ================= finger (phone)
  w = await boot({user: 'alice', hash: 'l/' + P, mobile: true, media: {'(hover: none)': true}}); d = w.document;
  check(await until(() => bar(A)), 'phone: timeline');
  const DWm = w.eval('tlDW()');
  // a swipe during the hold: nothing moves, no menu
  touch(w, bar(A), 'touchstart', 50); const sw = touch(w, bar(A), 'touchmove', 80);
  check(!sw.defaultPrevented, 'a swipe on a bar during the hold stays the page\'s scroll');
  await sleep(380); touch(w, bar(A), 'touchend'); await sleep(150);
  check(!d.querySelector('#pop:not(.hidden) .menu-list') && (await taskOf(A)).due === day(2), 'a swipe: no menu, nothing moved');
  // hold, then drag
  touch(w, bar(A), 'touchstart', 50); await sleep(380);
  const mv = touch(w, bar(A), 'touchmove', 50 + 2 * DWm);
  check(mv.defaultPrevented, 'after the hold the move is the drag\'s (the page does not scroll)');
  touch(w, bar(A), 'touchend');
  check(await until(async () => (await taskOf(A)).due === day(4)), 'finger: hold + drag moves the bar by two days');
  await sleep(450);
  // held and let go: the bar menu, no click
  touch(w, bar(A), 'touchstart', 50); await sleep(380);
  const up = touch(w, bar(A), 'touchend'); await sleep(150);
  check(up.defaultPrevented && /Open/.test(d.querySelector('#pop:not(.hidden)')?.textContent || ''), 'held and let go: the bar menu, no click after it');
  w.eval('closePop()'); await sleep(100);

  // a new task drawn into the empty days of the "Design" row
  const track = k => d.querySelector(`.tl-track.tl-cr[data-k="${k}"]`);
  const k = 'tlsec:' + SD;
  check(track(k), 'the section row has an empty track');
  touch(w, track(k), 'touchstart', 10 * DWm + 5); const sw2 = touch(w, track(k), 'touchmove', 10 * DWm + 40);
  await sleep(520); touch(w, track(k), 'touchend'); await sleep(150);
  check(!sw2.defaultPrevented && !track(k).querySelector('.tl-ghost') && !d.querySelector('#tl-new-in'), 'a swipe over the empty track starts nothing (it scrolls)');
  touch(w, track(k), 'touchstart', 10 * DWm + 5);
  check(await until(() => track(k)?.querySelector('.tl-ghost'), 2000), 'the hold shows the ghost bar');
  // 2.358 (#3402): the live follow-up and a stale view during the hold leave the held ghost alone (drawn after letting go)
  const gh = track(k)?.querySelector('.tl-ghost');
  w.eval('lpFollow(); td_renderSoon(); S.viewStale = true; viewSafeRender(); lpViewSafe()'); await sleep(450);
  check(gh?.isConnected && w.eval('S.viewStale === true'), 'a redraw during the hold keeps the ghost bar (the view stays stale until let go)');
  touch(w, track(k), 'touchmove', 13 * DWm + 5); touch(w, track(k), 'touchend'); await sleep(200);
  const N = w.eval('S.tlNew && [S.tlNew.d0, S.tlNew.d1]');
  check(d.querySelector('#tl-new-in') && N && N[0] === w.eval('addDays(S.tlStart, 10)') && N[1] === w.eval('addDays(S.tlStart, 13)'), 'hold + drag: the title field for that range: ' + JSON.stringify(N));
  w.eval('tlNewEnd()'); await sleep(150);

  // an undated task: a quick tap sets the day, hold + drag a range
  const nd = () => d.querySelector(`.tl-track.ndt.ed[data-nd="${U}"]`);
  check(await until(() => nd()), 'the undated task has an empty track');
  const ndDw = +(nd().dataset.dw || DWm), at = i => w.eval(`addDays(ndGeo(document.querySelector('.tl-track.ndt.ed[data-nd="${U}"]')).s0, ${i})`);
  const t5 = at(5), t7 = at(7);
  touch(w, nd(), 'touchstart', 5 * ndDw + 3); touch(w, nd(), 'touchend');
  check(await until(async () => (await taskOf(U)).due === t5), 'undated: a quick tap sets that day: ' + t5);
  await call('PATCH', `/api/tasks/${U}`, {due: null, start: null}); await w.eval('load()'); w.eval('render()'); await sleep(300);
  touch(w, nd(), 'touchstart', 5 * ndDw + 3); touch(w, nd(), 'touchmove', 5 * ndDw + 40); touch(w, nd(), 'touchend'); await sleep(400);
  check(!(await taskOf(U)).due, 'undated: a swipe sets nothing');
  touch(w, nd(), 'touchstart', 5 * ndDw + 3); await sleep(380);
  touch(w, nd(), 'touchmove', 7 * ndDw + 3); touch(w, nd(), 'touchend');
  check(await until(async () => { const t = await taskOf(U); return t.start === t5 && t.due === t7; }), 'undated: hold + drag = a range');
  check(errs.length === 0, 'no script errors (finger): ' + errs.join(' | '));
  w.close();

  // ================= roadmap
  await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline'})});
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  const sum = () => d.querySelector(`.rm-sum[data-lid="${P}"]`);
  check(await until(() => sum()), 'roadmap: the summary bar');
  const G = w.eval('S.rmV.G.dw'), a0 = (await taskOf(A)).due;
  ptr(w, sum(), 'pointerdown', 100); ptr(w, d, 'pointermove', 100 + 3 * G);
  check(sum().classList.contains('drag') && /3 days later/.test(d.querySelector('.rm-delta')?.textContent || ''), 'mouse: the project slides, the label counts the days');
  key(w, d.body, 'Escape'); await sleep(100);
  check(!sum().classList.contains('drag') && !sum().style.transform, 'Esc: the project back');
  ptr(w, d, 'pointerup', 100 + 3 * G); await sleep(500);
  check((await taskOf(A)).due === a0, 'Esc: nothing shifted on the server');
  w.close();
  w = await boot({user: 'alice', hash: 'all', mobile: true, media: {'(hover: none)': true}}); d = w.document;
  check(await until(() => sum()), 'phone: roadmap');
  touch(w, sum(), 'touchstart'); await sleep(200); touch(w, sum(), 'touchmove', 40); await sleep(400); touch(w, sum(), 'touchend');
  check(!d.querySelector('.rmmodal'), 'phone: a swipe cancels the long press');
  touch(w, sum(), 'touchstart'); await sleep(520);
  check(d.querySelector('.rmmodal'), 'phone: the hold opens "Move project by…"');
  const ue = touch(w, sum(), 'touchend');
  check(ue.defaultPrevented, 'no click after the hold');
  check(errs.length === 0, 'no script errors (roadmap): ' + errs.join(' | '));
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
