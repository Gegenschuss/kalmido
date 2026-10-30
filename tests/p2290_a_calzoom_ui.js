// 2.290.0 A UI tests (#3144 the calendar zooms sideways too: the number of days; own container, start.sh). jsdom, phone (touch):
// - two fingers side by side in the week change the number of days live (the columns 1/nf wide, the last one cut) and
//   leave the hour height; on release whole days, kept on the device (tasks.calDays), from the day under the fingers
// - one above the other = only the hours, diagonal = both; the arrows turn by the number of days
// - after a reload the days and the hours are back; 1 day = the day view, 7 = the week from its first weekday
// - Ctrl + Shift + wheel and a sideways Ctrl + wheel = the days; Safari's gesture events (no direction) = the hours only
// - spread to one day = the day view, together in the day = 2 days; the tabs "Week" / "Day" = 7 / 1 days
// - together beyond 14 days = the month (reduced motion: without the give / the grow animation); spread in the month = the week
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
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const open = async ls => {
    const w = await boot({user: 'alice', hash: 'cal', mobile: true, ls, setup: x => {
      x.ontouchstart = null; x.navigator.maxTouchPoints = 5;
      // jsdom lays nothing out: the day columns share 320 px right of a 34 px gutter (as on a phone)
      const GB = x.HTMLElement.prototype.getBoundingClientRect;
      x.HTMLElement.prototype.getBoundingClientRect = function () {
        if (!this.classList.contains('wcol')) return GB.call(this);
        const cs = [...this.parentNode.querySelectorAll('.wcol')], i = cs.indexOf(this), cw = 320 / cs.length;
        return {left: 34 + i * cw, right: 34 + (i + 1) * cw, x: 34 + i * cw, top: 0, y: 0, bottom: 1056, width: cw, height: 1056};
      };
    }});
    await until(() => w.document.querySelector('#view #wbody'));
    return w;
  };
  let w = await open({'tasks.calMode': '"week"'});
  let d = w.document, e = s => w.eval(s);
  const touch = (el, x, y) => ({clientX: x, clientY: y, target: el});
  const T = (el, type, pts) => { const ev = new w.Event(type, {bubbles: true, cancelable: true}); ev.touches = pts; ev.changedTouches = pts; el.dispatchEvent(ev); return ev; };
  // ax: 'x' side by side, 'y' one above the other, 'xy' diagonal; k = the factor of their distance
  const pinch = async (k, x, ax = 'x', end = true, y = 400, r = 50) => {  // r = half the fingers' distance at the start
    const el = d.querySelector('#view #wbody') || d.querySelector('#view .cal .cell');
    const at = f => { const hx = ax.includes('x') ? r * f : 0, hy = ax.includes('y') ? r * f : 0; return [touch(el, x - hx, y - hy), touch(el, x + hx, y + hy)]; };
    T(el, 'touchstart', [at(1)[0]]); T(el, 'touchstart', at(1));
    for (const f of [(1 + k) / 2, k]) { T(d.querySelector('#view #wbody') || el, 'touchmove', at(f)); await sleep(40); }
    if (end) { const t = d.querySelector('#view #wbody') || el; T(t, 'touchend', [at(k)[0]]); T(t, 'touchend', []); }
    await sleep(350);
  };
  const cols = () => [...d.querySelectorAll('#view .week .wcol')].map(c => c.dataset.day);
  const xOf = i => 34 + (i + .5) * 320 / cols().length;  // the middle of column i
  const seq = a => a.every((x, i) => !i || x === e(`addDays(${JSON.stringify(a[i - 1])}, 1)`));
  check(!!e(`typeof cgs_setDays === 'function'`) && cols().length === 7, 'the week: 7 days');
  const ws = cols()[0], thu = cols()[3];

  // ================= side by side: the days live, the hours stay
  await pinch(2, xOf(3), 'x', false);
  const wk = d.querySelector('#view .week');
  check(wk.classList.contains('cgs-dz') && /^3\.9/.test(wk.style.getPropertyValue('--nf')) && cols().length === 4, 'spread sideways: live 3.9 days, 4 columns drawn (the last cut) ' + wk.style.getPropertyValue('--nf') + ' ' + cols().length);
  check(wk.style.getPropertyValue('--h') === '44px' && cols().includes(thu), 'the hours stay, the day under the fingers stays in view');
  const wbl = d.querySelector('#view #wbody');
  T(wbl, 'touchend', [touch(wbl, 100, 400)]); T(wbl, 'touchend', []); await sleep(350);
  let c = cols();
  check(c.length === 4 && seq(c) && c[0] === e(`addDays(${JSON.stringify(ws)}, 1)`) && c.includes(thu), 'released: 4 whole days around the day under the fingers ' + c.join(','));
  check(e('S.calMode') === 'week' && w.__store['tasks.calDays'] === '4' && e('weekH()') === 44 && !d.querySelector('#view .week.cgs-dz'), 'kept on the device: 4 days, the hours unchanged');
  check(d.querySelectorAll('#view .whead .wh').length === 4 && [...d.querySelectorAll('#view .wad')].map(x => x.dataset.day).join() === c.join(), 'head and all-day row have the same 4 days (drops go by data-day)');
  d.querySelector('#view [data-act="cal-next"]').click(); await sleep(200);
  check(cols()[0] === e(`addDays(${JSON.stringify(c[0])}, 4)`) && cols().length === 4, 'the arrow turns by 4 days');
  d.querySelector('#view [data-act="cal-prev"]').click(); await sleep(200);
  check(cols()[0] === c[0], '... and back');

  // ================= one above the other: only the hours; diagonal: both
  await pinch(1.5, xOf(1), 'y');
  check(e('weekH()') === 66 && cols().length === 4, 'spread up / down: the hours (66), the days stay ' + e('weekH()') + ' ' + cols().length);
  await pinch(1.5, xOf(1), 'xy');
  check(cols().length === 3 && e('weekH()') === 99, 'diagonal: fewer days and higher hours ' + cols().length + ' ' + e('weekH()'));
  c = cols();

  // ================= kept after a reload
  const ls = {'tasks.calMode': w.__store['tasks.calMode'], 'tasks.calDays': w.__store['tasks.calDays'], 'tasks.calHourH': w.__store['tasks.calHourH']};
  w.close();
  w = await open(ls); d = w.document; e = s => w.eval(s);
  e(`S.calSel = ${JSON.stringify(c[0])}; renderView()`); await sleep(200);
  check(cols().join() === c.join() && e('weekH()') === 99, 'after a reload: the same 3 days and the height ' + cols().join());

  // ================= trackpad / mouse
  const wheel = async (n, o) => { for (let i = 0; i < n; i++) { d.querySelector('#view #wbody').dispatchEvent(new w.WheelEvent('wheel', {bubbles: true, cancelable: true, ctrlKey: true, clientX: xOf(1), clientY: 400, ...o})); await sleep(30); } await sleep(400); };
  await wheel(8, {shiftKey: true, deltaY: 10});
  c = cols();
  check(c.length === 7 && c[0] === e(`weekStartOf(${JSON.stringify(c[3])})`) && e('weekH()') === 99, 'Ctrl + Shift + wheel: the days (7 = the week from its first weekday), not the hours ' + c.length);
  await wheel(4, {deltaX: -10, deltaY: 1});
  check(cols().length === 5 && e('weekH()') === 99, 'a sideways Ctrl + wheel: the days too ' + cols().length);
  await wheel(4, {deltaY: -10});
  check(cols().length === 5 && e('weekH()') > 99, 'Ctrl + wheel (a trackpad pinch): only the hours ' + e('weekH()'));
  const h2 = e('weekH()'), gw = d.querySelector('#view #wbody');
  const G = (type, scale) => { const ev = new w.Event(type, {bubbles: true, cancelable: true}); Object.assign(ev, {clientX: xOf(1), clientY: 400, scale}); gw.dispatchEvent(ev); };
  G('gesturestart', 1); G('gesturechange', .8); await sleep(60); G('gestureend', .8); await sleep(300);
  check(cols().length === 5 && e('weekH()') < h2, 'Safari gesture (no direction): only the hours ' + e('weekH()'));

  // ================= 1 day = the day view and back
  await pinch(8, xOf(2));
  check(e('S.calMode') === 'day' && !!d.querySelector('#view .week.oneday') && cols().length === 1 && w.__store['tasks.calMode'] === '"day"', 'spread sideways to one day: the day view');
  const dd = cols()[0];
  await pinch(.5, 200);
  c = cols();
  check(e('S.calMode') === 'week' && c.length === 2 && c.includes(dd) && w.__store['tasks.calDays'] === '2', 'together in the day: 2 days ' + c.join(','));
  d.querySelector('#view [data-act="cal-mode"][data-k="week"]').click(); await sleep(200);
  check(cols().length === 7 && w.__store['tasks.calDays'] === '7', 'the tab "Week": 7 days again');
  d.querySelector('#view [data-act="cal-mode"][data-k="day"]').click(); await sleep(200);
  check(cols().length === 1 && e('S.calMode') === 'day', 'the tab "Day": one day');
  d.querySelector('#view [data-act="cal-mode"][data-k="week"]').click(); await sleep(200);

  // ================= beyond 14 days: the month (reduced motion: no give), spread in the month: the week
  w.matchMedia = q => ({matches: /reduce/.test(q), media: q, addEventListener() {}, removeEventListener() {}});
  await pinch(.3, xOf(3), 'x', false, 400, 120);  // (fingers wide apart: an axis counts from 48 px)
  check(cols().length === 14 && !d.querySelector('#view .week').style.transform && d.querySelector('#view .week').classList.contains('cgs-arm'), 'together: 14 days, beyond them it says "month" (reduced motion: no give) ' + cols().length + ' ' + d.querySelector('#view .week').style.transform + ' ' + d.querySelector('#view .week').className);
  const wb2 = d.querySelector('#view #wbody');
  T(wb2, 'touchend', [touch(wb2, 100, 400)]); T(wb2, 'touchend', []); await sleep(350);
  check(e('S.calMode') === 'month' && !!d.querySelector('#view .cal') && !d.querySelector('#view.cgs-zo'), 'released beyond 14 days: the month, without the animation');
  check(w.__store['tasks.calDays'] === '7', 'the month keeps the last number of days');
  await pinch(1.6, 200);
  check(e('S.calMode') === 'week' && cols().length === 7, 'spread in the month: the week');

  w.close();
  console.log(`p2290_a_calzoom_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
