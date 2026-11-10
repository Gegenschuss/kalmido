// 2.876.0 A UI test (#5559): the shared row swipe (static/js/rowswipe.js rsw_attach), jsdom against an own container, a phone
// kalmido-suite: fresh
// (390 px, touch). Invented data only. The person with the task rows has no organisation (freelancer parity).
// - task row (dnd.js on the shared swipe), used as a person does: a short swipe springs back and changes nothing, a swipe from
//   the screen's edge (the phone's Back) and an up / down move are no swipe and let the page scroll, the click right after a
//   swipe opens nothing but a plain tap still opens the task, left past the threshold = the short menu naming the task
//   (Completed, Delete), right past it = the row glides out and the task is completed; a finger on a row holds the view's
//   live redraw (rsw_busy / lpHold) until it is up
// - news (collab.js on the shared swipe): a short swipe keeps the item, right and left past the threshold remove it (also on
//   the server)
// - the rules of the helper on a stand-in row: one side only (can), rubber band past the threshold (max), one vibration per
//   crossing, a touchcancel does nothing, a finger held still first belongs to the long press, rsw_later keeps a redraw for
//   the moment the finger is up, reduced motion = no gliding
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, n = 100) => require('./boot').until(fn, {timeout: n * 150, step: 150});
const passed = (w, ms) => new Promise(r => w.setTimeout(r, ms));
const TOUCH = {'(hover: none)': true, '(pointer: coarse)': true};
let CK = '';
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
// a touch event (jsdom has no Touch constructor): the touch list as plain objects
const tc = (w, el, type, x, y) => {
  const e = new w.Event(type, {bubbles: true, cancelable: true}), t = [{identifier: 1, target: el, clientX: x, clientY: y}];
  Object.defineProperty(e, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : t});
  Object.defineProperty(e, 'changedTouches', {value: t});
  el.dispatchEvent(e); return e;
};
// one finger from (x0, 300) by dx / dy in four steps; out.mid = the row's transform before the finger is up, out.prev = a move
// was prevented (the page did not scroll)
const swipe = async (w, el, row, dx, dy = 0, {x0 = 150, end = 'touchend', hold = 0} = {}) => {
  const out = {prev: false};
  tc(w, el, 'touchstart', x0, 300);
  if (hold) await passed(w, hold);
  for (const f of [.25, .5, .75, 1]) out.prev = tc(w, el, 'touchmove', x0 + dx * f, 300 + dy * f).defaultPrevented || out.prev;
  out.mid = row.style.transform; out.op = row.style.opacity;
  tc(w, el, end, x0 + dx, 300 + dy);
  out.end = row.style.transform;
  return out;
};
const width = (w, px) => Object.defineProperty(w, 'innerWidth', {configurable: true, value: px});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Builder', password: 'password123', email: 'bob@example.com'})).id;
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});

  // ================= task rows (frida, no organisation)
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'setup: frida has no organisation');
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id, T = [];
  for (const t of ['Water the roses', 'Cut the hedge', 'Sow the beans', 'Rake the leaves']) T.push((await call('POST', '/api/tasks', {title: t, list_id: L})).id);
  const status = async id => (await call('GET', `/api/tasks/${id}`)).status;

  let w = await boot({user: 'frida', hash: 'l/' + L, mobile: true, media: TOUCH, setup: x => width(x, 390)}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`), grip = id => row(id)?.querySelector('.tmain') || row(id);
  check(await until(() => T.every(id => row(id))) && w.eval('isTouch()'), 'tasks: the four rows are there on a touch phone');
  check(!errs.length, 'tasks: boots without errors ' + errs.join(' | ')); errs.splice(0);

  // a short swipe springs back and changes nothing
  let r = row(T[0]), s = await swipe(w, grip(T[0]), r, 50);
  // the click the browser sends right after the swipe opens nothing; a plain tap later opens the task
  grip(T[0]).click(); await passed(w, 50);
  check(w.eval('S.sel') !== T[0], 'tasks: the click right after a swipe does not open the task');
  check(s.mid === 'translateX(50px)' && s.prev, 'tasks: the row follows the finger sideways and the page does not scroll ' + JSON.stringify(s));
  check(await until(() => !row(T[0])?.style.transform && !row(T[0])?.style.background) && await status(T[0]) === 0, 'tasks: a short swipe springs back, the task stays open');
  await passed(w, 450); grip(T[0]).click();
  check(await until(() => w.eval('S.sel') === T[0], 40), 'tasks: a plain tap afterwards opens it as before');
  w.eval("typeof closeDetail === 'function' && closeDetail()"); w.location.hash = '#l/' + L; await until(() => row(T[1]), 40);

  // the screen's edge (the phone's Back) and up / down are no swipe
  r = row(T[1]); s = await swipe(w, grip(T[1]), r, 200, 0, {x0: 10});
  check(!s.mid && !s.prev, 'tasks: a swipe from the left edge stays the phone\'s Back gesture ' + JSON.stringify(s));
  s = await swipe(w, grip(T[1]), r, 50, 120);
  check(!s.mid && !s.prev, 'tasks: an up / down move scrolls, the row stays ' + JSON.stringify(s));
  check(await status(T[1]) === 0, 'tasks: neither changed the task');

  // a finger on a row holds the view's live redraw until it is up
  tc(w, grip(T[1]), 'touchstart', 150, 300);
  const held = w.eval('[rsw_busy(), lpHold()]');
  tc(w, grip(T[1]), 'touchend', 150, 300);
  check(held[0] && held[1] && !w.eval('rsw_busy()'), 'tasks: while the finger is on the row the live redraw waits, after it not ' + JSON.stringify(held));

  // a touchcancel past the threshold (the system took the gesture) does nothing
  s = await swipe(w, grip(T[1]), row(T[1]), 200, 0, {end: 'touchcancel'});
  check(s.mid === 'translateX(200px)' && s.end === '', 'tasks: a cancelled swipe springs back ' + JSON.stringify(s));
  await passed(w, 400);
  check(await status(T[1]) === 0 && !d.querySelector('#pop:not(.hidden), .tsheet'), 'tasks: a cancelled swipe completes nothing and opens no menu');

  // left past the threshold = the short menu naming the task
  s = await swipe(w, grip(T[2]), row(T[2]), -150);
  const menu = await until(() => { const p = [...d.querySelectorAll('#pop:not(.hidden), .tsheet')].map(x => x.textContent).join(' '); return /Completed/.test(p) && /Delete/.test(p) ? p : ''; }, 40);
  check(!!menu && /Sow the beans/.test(menu), 'tasks: a swipe to the left opens the short menu of that task (Completed, Delete) ' + String(menu).slice(0, 160));
  w.eval("typeof closePop === 'function' && closePop()"); await passed(w, 300);

  // right past the threshold = the row glides out and the task is completed
  r = row(T[3]); s = await swipe(w, grip(T[3]), r, 160);
  check(s.end === 'translateX(110%)', 'tasks: a swipe to the right carries the row out ' + JSON.stringify(s));
  check(await until(async () => (await status(T[3])) > 0, 40), 'tasks: and completes the task');
  check(!errs.length, 'tasks: no errors ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // ================= news (bob gets three: alice assigns him tasks of a shared project)
  CK = CA;
  const SH = (await call('POST', '/api/lists', {name: 'Shared yard'})).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: bob, role: 'edit'});
  for (const t of ['Paint the fence', 'Fix the gate', 'Clean the shed']) await call('POST', '/api/tasks', {title: t, list_id: SH, assignee_id: bob});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CB);
  const news = async () => ((await call('GET', '/api/news', null, CB)).items || []).length;
  const n0 = await news();
  check(n0 >= 3, 'news: bob has the news of his three tasks (' + n0 + ')');
  w = await boot({user: 'bob', hash: 'news', mobile: true, media: TOUCH, setup: x => width(x, 390)}); d = w.document;
  // jsdom lays nothing out: an item 360 px wide (the threshold is 35 % of it, at most 120 px)
  const items = () => [...d.querySelectorAll('#view .nitem')].map(n => (Object.defineProperty(n, 'offsetWidth', {configurable: true, value: 360}), n));
  check(await until(() => items().length >= 3, 60), 'news: the items are shown');
  let it = items()[0]; s = await swipe(w, it, it, -40);
  check(s.mid === 'translateX(-40px)' && s.op && +s.op < 1, 'news: the item follows the finger and fades ' + JSON.stringify(s));
  check(await until(() => !it.style.transform && !it.style.opacity, 20) && items().length === n0, 'news: a short swipe keeps it');
  it = items()[0]; s = await swipe(w, it, it, 200);
  check(s.end === 'translateX(110%)' && await until(() => items().length === n0 - 1, 40), 'news: a swipe to the right removes the item ' + JSON.stringify(s));
  it = items()[0]; s = await swipe(w, it, it, -200);
  check(s.end === 'translateX(-110%)' && await until(() => items().length === n0 - 2, 40), 'news: a swipe to the left removes it too ' + JSON.stringify(s));
  check(await until(async () => (await news()) === n0 - 2, 40), 'news: removed on the server too');

  // ================= the helper's rules on a stand-in row (one side, rubber band, vibration, cancel, hold, rsw_later)
  w.eval(`(() => {
    const el = document.createElement('div'); el.className = 'rswtest'; el.textContent = 'stand-in'; document.body.appendChild(el);
    window.__rs = {go: 0, vib: 0, look: [], later: 0}; navigator.vibrate = () => { __rs.vib++; return true; };
    rsw_attach({at: e => e.target.closest?.('.rswtest') || null, can: dir => dir > 0, min: () => 56, max: 88,
      look: (el, dx, on) => __rs.look.push(on), go: () => { __rs.go++; }});
    return 1; })()`);
  const st = d.querySelector('.rswtest'), rs = () => w.eval('JSON.parse(JSON.stringify(__rs))');
  s = await swipe(w, st, st, -150);
  check(!s.mid && !s.prev && rs().go === 0, 'helper: the side that does nothing is no swipe ' + JSON.stringify(s));
  tc(w, st, 'touchstart', 100, 300); tc(w, st, 'touchmove', 170, 300);
  const band = st.style.transform; tc(w, st, 'touchmove', 400, 300);
  const top = st.style.transform; tc(w, st, 'touchmove', 130, 300); tc(w, st, 'touchmove', 180, 300);
  const v = rs().vib; tc(w, st, 'touchend', 180, 300);
  check(band === 'translateX(61px)' && top === 'translateX(88px)', `helper: a rubber band past the threshold (70 px -> ${band}), at most max (${top})`);
  check(v === 2 && rs().go === 1, 'helper: one vibration per crossing of the threshold, the action once at the end ' + JSON.stringify(rs()));
  await passed(w, 250);
  s = await swipe(w, st, st, 150, 0, {end: 'touchcancel'});
  check(rs().go === 1, 'helper: a touchcancel past the threshold does nothing');
  await passed(w, 250);
  s = await swipe(w, st, st, 150, 0, {hold: 600});
  check(!s.mid && rs().go === 1, 'helper: a finger held still first belongs to the long press, no swipe ' + JSON.stringify(s));
  tc(w, st, 'touchstart', 100, 300);
  const kept = w.eval(`rsw_later('t', () => { __rs.later++; })`), early = rs().later;
  tc(w, st, 'touchend', 100, 300);
  check(kept && early === 0 && await until(() => rs().later === 1, 20), 'helper: rsw_later keeps a redraw until the finger is up, then it comes');
  check(!w.eval(`rsw_later('t2', () => 0)`), 'helper: without a finger on a row rsw_later draws at once (false)');
  // reduced motion: the row stands again at once, no gliding
  const mm = w.matchMedia; w.matchMedia = q => ({matches: /reduced-motion/.test(q), addEventListener() {}, addListener() {}});
  tc(w, st, 'touchstart', 100, 300); tc(w, st, 'touchmove', 140, 300); tc(w, st, 'touchend', 140, 300);
  check(st.style.transition === 'none' && st.style.transform === '', 'helper: reduced motion = back in place at once, no gliding');
  w.matchMedia = mm;
  check(!errs.length, 'news / helper: no errors ' + errs.join(' | '));
  w.close();

  console.log(`p2876_a_rowswipe_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2876_a_rowswipe_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
