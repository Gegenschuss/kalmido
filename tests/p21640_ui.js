// 2.164.0 UI tests (#2625 the calendar on the phone: swipe and pinch; own container, start.sh). jsdom, phone (touch):
// - one finger sideways turns the page in month / week / day (left = next, right = previous), up / down, a short swipe and
//   a swipe from the screen's edge do not; the page follows the finger and is back in place after a short one
// - two fingers in week / day zoom the hour height without steps (live on the grid's --h, taken over on release, kept in
//   tasks.calHourH, inside its bounds); pinched on beyond a bound the view changes (week -> day, week -> month); spread in
//   the month = the week, pinched together without a year view = stays
// - Ctrl + wheel (trackpad pinch) zooms the hours too, a sideways wheel (two-finger swipe) turns the page once
// - a double tap on a day of the month opens it; a single tap still only selects it
// - a pending long press (caldrag.js) is dropped by a second finger; while a drag runs no swipe starts
// freelancer-matrix: n/a (no route; the gestures run in the client only, tested as alice without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const w = await boot({user: 'alice', hash: 'cal', mobile: true, ls: {'tasks.calMode': '"month"'}, setup: x => { x.ontouchstart = null; x.navigator.maxTouchPoints = 5; }});
  const d = w.document, e = s => w.eval(s);
  await until(() => d.querySelector('#view .cal .cell'));
  check(!!e(`typeof cgs_pzStart === 'function'`), 'calgest.js is loaded with the calendar');
  const touch = (el, x, y) => ({clientX: x, clientY: y, target: el});
  const T = (el, type, pts) => { const ev = new w.Event(type, {bubbles: true, cancelable: true}); ev.touches = pts; ev.changedTouches = pts; el.dispatchEvent(ev); return ev; };
  const swipe = async (el, dx, dy = 0, x0 = 300, y0 = 400) => {
    T(el, 'touchstart', [touch(el, x0, y0)]);
    T(el, 'touchmove', [touch(el, x0 + dx / 4, y0 + dy / 4)]);
    await sleep(30);
    const mv = T(el, 'touchmove', [touch(el, x0 + dx, y0 + dy)]);
    T(el, 'touchend', []);
    await sleep(400);
    return mv;
  };
  const pinch = async (el, k, x = 200, y = 400, end = true) => {
    const a = touch(el, x - 50, y), b = touch(el, x + 50, y);
    T(el, 'touchstart', [a]); T(el, 'touchstart', [a, b]);
    for (const f of [(1 + k) / 2, k]) { T(el, 'touchmove', [touch(el, x - 50 * f, y), touch(el, x + 50 * f, y)]); await sleep(40); }
    if (end) { T(el, 'touchend', [touch(el, x - 50 * k, y)]); T(el, 'touchend', []); }
    await sleep(350);
  };
  const month = () => e('S.calMonth');

  // ================= swipe in the month
  const m0 = month();
  const mv = await swipe(d.querySelector('#view .cal .cell'), -200);
  check(mv.defaultPrevented, 'a sideways swipe holds back the page (no scroll)');
  check(month() > m0, `left: the next month (${m0} -> ${month()})`);
  await swipe(d.querySelector('#view .cal .cell'), 200);
  check(month() === m0, 'right: back to the month before');
  await swipe(d.querySelector('#view .cal .cell'), -24);
  check(month() === m0 && [...d.querySelectorAll('#view > .calbar ~ *')].every(x => !x.style.transform), 'a short swipe: same month, the page back in place');
  await swipe(d.querySelector('#view .cal .cell'), -40, -220);
  check(month() === m0, 'up / down: the page scrolls, the month stays');
  await swipe(d.querySelector('#view .cal .cell'), 200, 0, 8);
  check(month() === m0, 'a swipe from the screen edge (the phone\'s Back) does not turn the page');

  // ================= double tap on a day
  const cell = [...d.querySelectorAll('#view .cal .cell:not(.out)')][10], day = cell.dataset.day;
  cell.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, clientX: 100, clientY: 300}));
  await sleep(120);
  check(e('S.calMode') === 'month' && e('S.calSel') === day, 'one tap selects the day, the month stays');
  d.querySelector(`#view .cal .cell[data-day="${day}"]`).dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, clientX: 102, clientY: 301}));
  await sleep(200);
  check(e('S.calMode') === 'day' && e('S.calSel') === day && !!d.querySelector('#view .week.oneday'), 'a double tap opens that day');

  // ================= swipe in the day / week
  await swipe(d.querySelector('#view #wbody'), -200);
  check(e('S.calSel') === e(`addDays(${JSON.stringify(day)}, 1)`), 'day: left = the next day');
  e(`S.calMode = 'week'; renderView()`); await sleep(200);
  const s0 = e('S.calSel');
  await swipe(d.querySelector('#view #wbody'), 200);
  check(e('S.calSel') === e(`addDays(${JSON.stringify(s0)}, -7)`), 'week: right = the week before');

  // ================= pinch in the week: the hour height without steps
  check(e('weekH()') === 44, 'the hour height starts at 44 px');
  let wb = d.querySelector('#view #wbody');
  await pinch(wb, 1.5, 200, 400, false);
  check(d.querySelector('#view .week').style.getPropertyValue('--h') === '66px', 'the hours follow the fingers live: ' + d.querySelector('#view .week').style.getPropertyValue('--h'));
  check([...d.querySelectorAll('#view #wbody .wtime')].some(x => /var\(--h\)/.test(x.style.top)), 'the blocks hang on the height during the gesture');
  T(wb, 'touchend', [touch(wb, 100, 400)]); T(wb, 'touchend', []); await sleep(350);
  check(e('weekH()') === 66 && w.__store['tasks.calHourH'] === '66' && e('S.calMode') === 'week', 'released: 66 px taken over and kept, still the week');
  check(d.querySelector('#view .week').style.getPropertyValue('--h') === '66px' && !d.querySelector('#view #wbody [style*="var(--h)"]'), 'drawn anew with the new height');
  await pinch(d.querySelector('#view #wbody'), 2.5);
  check(e('weekH()') === 160 && e('S.calMode') === 'week', 'spread to the upper bound (160): stays the week ' + e('weekH()'));
  await pinch(d.querySelector('#view #wbody'), 1.5);
  check(e('S.calMode') === 'day', 'pinched on beyond the upper bound: the day');
  await pinch(d.querySelector('#view #wbody'), 0.05);
  check(e('S.calMode') === 'week' && e('weekH()') === 160, 'together beyond the lower bound in the day: the week, the height kept from before ' + e('weekH()'));
  await pinch(d.querySelector('#view #wbody'), 0.05);
  check(e('S.calMode') === 'month' && !!d.querySelector('#view .cal'), 'together beyond the lower bound in the week: the month');
  // 2.164.0 (#2625): the year view (2.155.0 C, calyear.js) is live now - together in the month goes on to the year
  await pinch(d.querySelector('#view .cal .cell'), 0.5);
  check(e('S.calMode') === 'year' && !!d.querySelector('#view #cyear'), 'together in the month: the year');
  await pinch(d.querySelector('#view #cyear .cymon'), 1.6);
  check(e('S.calMode') === 'month' && !!d.querySelector('#view .cal') && !d.querySelector('#view .cal').style.transform, 'spread in the year on a month: that month');
  await pinch(d.querySelector('#view .cal .cell'), 1.6);
  check(e('S.calMode') === 'week', 'spread in the month: the week');

  // ================= trackpad: Ctrl + wheel zooms, sideways turns the page
  e(`LS.set('calHourH', 44); renderView()`); await sleep(200);
  wb = d.querySelector('#view #wbody');
  for (let i = 0; i < 4; i++) { const ev = new w.WheelEvent('wheel', {bubbles: true, cancelable: true, deltaY: -10, ctrlKey: true, clientX: 200, clientY: 400}); wb.dispatchEvent(ev); if (!i) check(ev.defaultPrevented, 'Ctrl + wheel: not the page zoom'); await sleep(30); }
  await sleep(400);
  const h1 = e('weekH()');
  check(h1 > 44 && h1 < 160 && e('S.calMode') === 'week', 'Ctrl + wheel: the hours larger without steps ' + h1);
  const s1 = e('S.calSel');
  for (let i = 0; i < 8; i++) { wb.dispatchEvent(new w.WheelEvent('wheel', {bubbles: true, cancelable: true, deltaX: 40, deltaY: 2})); await sleep(20); }
  await sleep(500);
  check(e('S.calSel') === e(`addDays(${JSON.stringify(s1)}, 7)`), 'a sideways wheel (two-finger swipe) turns exactly one week');
  wb = d.querySelector('#view #wbody');
  wb.dispatchEvent(new w.WheelEvent('wheel', {bubbles: true, cancelable: true, deltaY: 60}));
  await sleep(300);
  check(e('S.calSel') === e(`addDays(${JSON.stringify(s1)}, 7)`), 'a plain wheel up / down scrolls only');

  // ================= the long press stays
  const col = d.querySelector('#view .week .wcol');
  e(`CG.st = {kind: 'new', touch: true, active: false, timer: setTimeout(() => { window.__held = 1; }, 400)}`);
  T(col, 'touchstart', [touch(col, 150, 400)]); T(col, 'touchstart', [touch(col, 150, 400), touch(col, 250, 400)]);
  await sleep(500);
  check(!e('window.__held') && !e('CG.st'), 'a second finger drops a pending long press');
  T(col, 'touchend', []); await sleep(100);
  const s2 = e('S.calSel');
  d.body.classList.add('cgdrag');  // an event is being dragged (caldrag.js)
  await swipe(d.querySelector('#view .week .wcol'), -200);
  check(e('S.calSel') === s2, 'while a drag runs a sideways move is no swipe');
  d.body.classList.remove('cgdrag');

  w.close();
  console.log(`p21640_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
