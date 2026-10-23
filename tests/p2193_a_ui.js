// 2.193.0 part A UI tests (#2219 the calendar and the mind map drag through drag.js; own container, start.sh). jsdom:
// - calendar (day view): a finger held 0.4 s and dragged over free time leaves a block "New event" on the 15-minute grid,
//   Enter saves it there; a quick swipe makes nothing; a held event dragged by a finger is moved (saved, length kept); the
//   mouse moves an event from a few pixels and makes it longer at its lower edge; Esc cancels a mouse drag (no ghost, no
//   block); the click after a drag is swallowed
// - mind map (zoom != 1, panned): the mouse drags a branch onto another (it hangs there, the drop target in map
//   coordinates), the map does not move under it; Esc cancels; a finger held 0.45 s lifts a branch and rehangs it; two
//   fingers zoom and start no drag; one finger without the hold moves the map
// freelancer-matrix: n/a (no route; the gestures run in the client only, tested as alice without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2193A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const frame = w => new Promise(r => w.requestAnimationFrame(() => w.requestAnimationFrame(r)));
// a pointer event (jsdom may lack PointerEvent: a MouseEvent with pointerId / pointerType)
const pe = (w, el, type, x, y, {id = 1, kind = 'mouse'} = {}) => {
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, pointerId: id, pointerType: kind});
  if (ev.pointerId !== id) Object.defineProperty(ev, 'pointerId', {value: id});
  if (ev.pointerType !== kind) Object.defineProperty(ev, 'pointerType', {value: kind});
  el.dispatchEvent(ev); return ev;
};
// a touch event (jsdom has no Touch constructor): touches as plain objects
const te = (w, el, type, pts) => {
  const ev = new w.Event(type, {bubbles: true, cancelable: true});
  const list = pts.map(([x, y], i) => ({identifier: i + 1, target: el, clientX: x, clientY: y}));
  Object.defineProperty(ev, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : list});
  Object.defineProperty(ev, 'changedTouches', {value: list});
  el.dispatchEvent(ev); return ev;
};
const esc = w => w.document.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
// jsdom lays nothing out: an event block's box from its own top / height inside the column (the column starts at 0)
const rects = w => {
  const g0 = w.Element.prototype.getBoundingClientRect;
  w.Element.prototype.getBoundingClientRect = function () {
    if (this.classList?.contains('wcev') || this.classList?.contains('cgghost')) {
      const top = parseFloat(this.style.top) || 0, h = parseFloat(this.style.height) || 0;
      return {top, bottom: top + h, left: 0, right: 300, width: 300, height: h, x: 0, y: top};
    }
    return g0.call(this);
  };
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events'});
  const Wk = await call('POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  check(Wk.id > 0, 'setup: a calendar');

  // ================================================================ calendar, phone (touch)
  let w = await boot({user: 'alice', hash: 'cal', mobile: true, setup: x => { x.ontouchstart = null; x.navigator.maxTouchPoints = 5; rects(x); }});
  let d = w.document, e = s => w.eval(s);
  await until(() => d.querySelector('#view .calbar'));
  check(e(`typeof cg_down === 'function' && typeof drg_attach === 'function'`), 'caldrag.js and drag.js are loaded');
  const D = e(`addDays(ds(new Date()), 2)`), TZ = e('evTz()');
  const find = async title => (await call('GET', `/api/events?from=${e(`addDays(ds(new Date()), -3)`)}&to=${e(`addDays(ds(new Date()), 10)`)}`)).items?.find(x => x.title === title);
  const get = async id => (await fetch(B + `api/events/${id}`, {headers: {...H, Cookie: CK}})).json();
  const day = () => e(`(() => { S.calMode = 'day'; S.calSel = '${D}'; calInvalidate(); renderView(); return 1; })()`);
  await day();
  await until(() => d.querySelector(`#view .wcol[data-day="${D}"]`));
  const Hh = e('weekH()'), col = () => d.querySelector(`#view .wcol[data-day="${D}"]`);
  check(Hh > 0 && !!col(), 'the day view with its hour grid');
  // a quick swipe: nothing
  te(w, col(), 'touchstart', [[150, 13 * Hh + 4]]); te(w, col(), 'touchmove', [[150, 13 * Hh + 40]]); te(w, col(), 'touchend', []);
  await sleep(500);
  check(!e('CG.st') && !d.querySelector('#view .evghost, #view .cgnew') && !d.body.classList.contains('cgdrag'), 'touch: a quick swipe makes nothing (the page scrolls)');
  // hold 0.4 s, then drag: a block "New event" 13:00-14:30 on the 15-minute grid
  te(w, col(), 'touchstart', [[150, 13 * Hh + 4]]);
  await sleep(550);
  check(d.body.classList.contains('cgdrag') && !!d.querySelector('#view .evghost'), 'touch: after the hold the block shows before the finger moves');
  const mv = te(w, col(), 'touchmove', [[150, 14 * Hh]]); await frame(w);
  te(w, col(), 'touchmove', [[150, 14.5 * Hh + 3]]); await frame(w);
  check(mv.defaultPrevented, 'touch: the page does not scroll under the drag');
  const end = te(w, col(), 'touchend', []);
  check(end.defaultPrevented, 'touch: no click / mouse events follow the drag');
  const blk = await until(() => d.querySelector('#view .wcol .cgnew'));
  check(!!blk && /13:00.14:30/.test(blk.textContent), 'touch: hold and drag = a block 13:00-14:30 ' + (blk && blk.textContent));
  if (blk) { const i = blk.querySelector('.cgin'); i.value = 'Call'; i.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); }
  const CA = await until(() => find('Call'));
  let ca = CA && await get(CA.eid);
  check(ca && ca.start === `${D}T13:00` && ca.end === `${D}T14:30`, 'touch: saved at 13:00-14:30 ' + JSON.stringify(ca && [ca.start, ca.end]));
  // hold the event and drag it an hour down: moved, the length kept
  await day();
  const cev = await until(() => [...d.querySelectorAll('#view .wcev')].find(x => x.textContent.includes('Call')));
  const y0 = parseFloat(cev.style.top) + 5;
  te(w, cev, 'touchstart', [[150, y0]]);
  await sleep(550);
  check(!!d.querySelector('#view .cgghost') && cev.classList.contains('cgsrc'), 'touch: a held event lifts (ghost)');
  te(w, cev, 'touchmove', [[150, y0 + Hh / 2]]); await frame(w);
  te(w, cev, 'touchmove', [[150, y0 + Hh]]); await frame(w);
  te(w, cev, 'touchend', []);
  ca = await until(async () => { const x = await get(CA.eid); return x.start !== `${D}T13:00` ? x : null; });
  check(ca && ca.start === `${D}T14:00` && ca.end === `${D}T15:30`, 'touch: a held event dragged by an hour: moved, length kept ' + JSON.stringify(ca && [ca.start, ca.end]));
  // a second finger drops a pending long press
  await day(); await until(() => [...d.querySelectorAll('#view .wcev')].some(x => x.textContent.includes('Call')));
  te(w, col(), 'touchstart', [[150, 18 * Hh]]); te(w, col(), 'touchstart', [[150, 18 * Hh], [250, 18 * Hh]]);
  await sleep(550);
  check(!e('CG.st') && !d.body.classList.contains('cgdrag'), 'touch: a second finger drops the long press');
  te(w, col(), 'touchend', []);
  w.close();

  // ================================================================ calendar, desktop (mouse)
  w = await boot({user: 'alice', hash: 'cal', setup: rects}); d = w.document; e = s => w.eval(s);
  await until(() => d.querySelector('#view .calbar'));
  await day();
  let ev = await until(() => [...d.querySelectorAll('#view .wcev')].find(x => x.textContent.includes('Call')));
  let top = parseFloat(ev.style.top);
  // moved down by 1.5 hours (snapped to 15 minutes)
  pe(w, ev, 'pointerdown', 150, top + 6); pe(w, d, 'pointermove', 150, top + 10); await frame(w);
  check(d.body.classList.contains('cgdrag'), 'mouse: a few pixels start the drag (no hold)');
  pe(w, d, 'pointermove', 150, top + 6 + 1.5 * Hh + 4); await frame(w);
  pe(w, d, 'pointerup', 150, top + 6 + 1.5 * Hh + 4);
  const clk = new w.MouseEvent('click', {bubbles: true, cancelable: true}); col().dispatchEvent(clk);
  check(clk.defaultPrevented, 'mouse: the click after the drag is swallowed');
  ca = await until(async () => { const x = await get(CA.eid); return x.start !== `${D}T14:00` ? x : null; });
  check(ca && ca.start === `${D}T15:30` && ca.end === `${D}T17:00`, 'mouse: moved by 1.5 hours ' + JSON.stringify(ca && [ca.start, ca.end]));
  // longer at the lower edge: the end 17:00 -> 18:00
  await day();
  ev = await until(() => [...d.querySelectorAll('#view .wcev')].find(x => x.textContent.includes('Call') && parseFloat(x.style.top) > top + Hh));
  top = parseFloat(ev.style.top); const bot = top + parseFloat(ev.style.height);
  pe(w, ev, 'pointerdown', 150, bot - 2); pe(w, d, 'pointermove', 150, bot + 10); await frame(w);
  pe(w, d, 'pointermove', 150, 18 * Hh + 2); await frame(w);
  pe(w, d, 'pointerup', 150, 18 * Hh + 2);
  ca = await until(async () => { const x = await get(CA.eid); return x.end !== `${D}T17:00` ? x : null; });
  check(ca && ca.start === `${D}T15:30` && ca.end === `${D}T18:00`, 'mouse: the lower edge makes it longer ' + JSON.stringify(ca && [ca.start, ca.end]));
  // Esc cancels a drag over free time: no ghost, no block, nothing saved
  await day(); await until(() => d.querySelector('#view .wcev'));
  pe(w, col(), 'pointerdown', 150, 20 * Hh + 2); pe(w, d, 'pointermove', 150, 20 * Hh + 20); await frame(w);
  pe(w, d, 'pointermove', 150, 21 * Hh); await frame(w);
  check(!!d.querySelector('#view .evghost'), 'mouse: a drag over free time shows the ghost');
  esc(w);
  check(!d.querySelector('#view .evghost') && !e('CG.st') && !d.body.classList.contains('cgdrag'), 'mouse: Esc cancels the drag');
  pe(w, d, 'pointerup', 150, 21 * Hh); await sleep(300);
  check(!d.querySelector('#view .cgnew'), 'mouse: after Esc the release makes no block');
  w.close();

  // ================================================================ mind map
  const L = (await call('POST', '/api/lists', {name: 'Brainstorm'})).id;
  await call('PATCH', '/api/lists/' + L, {view: 'mindmap'});
  const mk = async title => (await call('POST', '/api/tasks', {title, list_id: L})).id;
  const T1 = await mk('Alpha'), T2 = await mk('Beta'), T3 = await mk('Gamma'), T4 = await mk('Delta');
  const parent = async id => ((await call('GET', '/api/state')).tasks.find(t => t.id === id) || {}).parent_id || null;
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document; e = s => w.eval(s);
  await until(() => d.querySelector('#view .mmstage [data-mmn]'));
  // zoomed in and moved: the drop target must be found in map coordinates
  e(`MM.pan = {k: 1.5, x: 40, y: -30}; mm_applyPan()`);
  const pan = () => JSON.stringify(e('MM.pan'));
  const at = id => e(`(() => { const n = MM.last.L.nodes.find(n => n.id === 't${id}'), p = MM.pan; return {x: p.x + (n.x + 16 + n.w / 2) * p.k, y: p.y + (n.y + 16 + n.h / 2) * p.k}; })()`);
  const g = id => d.querySelector(`#view .mmstage [data-mmn="t${id}"]`);
  let a = at(T2), b = at(T1), p0 = pan();
  pe(w, g(T2), 'pointerdown', a.x, a.y); pe(w, d, 'pointermove', a.x + 10, a.y + 10); await frame(w);
  pe(w, d, 'pointermove', b.x, b.y); await frame(w);
  check(!!d.querySelector('#view .mmstage.mmdragging') && g(T1)?.classList.contains('drop'), 'map, mouse: the branch under the pointer is the target (zoom 1.5)');
  check(pan() === p0, 'map, mouse: the map does not move under a dragged branch');
  pe(w, d, 'pointerup', b.x, b.y);
  check(await until(async () => await parent(T2) === T1), 'map, mouse: dropped = hangs under the target');
  // Esc cancels
  await until(() => g(T3)); await sleep(200);
  a = at(T3); b = at(T4);
  pe(w, g(T3), 'pointerdown', a.x, a.y); pe(w, d, 'pointermove', a.x + 10, a.y); await frame(w);
  pe(w, d, 'pointermove', b.x, b.y); await frame(w);
  check(g(T4)?.classList.contains('drop'), 'map, mouse: the target is marked');
  esc(w);
  check(!d.querySelector('#view .mmnode.drop, #view .mmstage.mmdragging'), 'map, mouse: Esc drops the marks');
  pe(w, d, 'pointermove', b.x + 30, b.y + 30); await frame(w);
  pe(w, d, 'pointerup', b.x + 30, b.y + 30); await sleep(400);
  check(await parent(T3) === null && pan() === p0, 'map, mouse: after Esc nothing is rehung and the map stays');
  w.close();

  // phone: one finger moves the map, a held finger rehangs, two fingers zoom
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true, setup: x => { x.ontouchstart = null; x.navigator.maxTouchPoints = 5; }}); d = w.document; e = s => w.eval(s);
  await until(() => d.querySelector('#view .mmstage [data-mmn]'));
  e(`MM.pan = {k: 0.8, x: 20, y: 10}; mm_applyPan()`);
  const finger = (el, type, x, y, id = 1) => { pe(w, el, type === 'touchstart' ? 'pointerdown' : type === 'touchmove' ? 'pointermove' : 'pointerup', x, y, {id, kind: 'touch'}); };
  // one finger on a branch without the hold: the map moves
  a = at(T4); p0 = e('MM.pan.x');
  finger(g(T4), 'touchstart', a.x, a.y); te(w, g(T4), 'touchstart', [[a.x, a.y]]);
  finger(d, 'touchmove', a.x + 40, a.y); te(w, g(T4), 'touchmove', [[a.x + 40, a.y]]); await frame(w);
  finger(d, 'touchend', a.x + 40, a.y); te(w, g(T4), 'touchend', []);
  check(Math.round(e('MM.pan.x') - p0) === 40 && !d.querySelector('#view .mmstage .lift'), 'map, touch: one finger without the hold moves the map');
  await sleep(200);
  // held 0.45 s: lifted, then dragged onto Alpha
  a = at(T4); b = at(T1);
  const px = e('MM.pan.x');
  finger(g(T4), 'touchstart', a.x, a.y); te(w, g(T4), 'touchstart', [[a.x, a.y]]);
  await sleep(600);
  check(g(T4)?.classList.contains('lift'), 'map, touch: a held branch lifts');
  finger(d, 'touchmove', a.x + 20, a.y); const tm = te(w, g(T4), 'touchmove', [[a.x + 20, a.y]]); await frame(w);
  finger(d, 'touchmove', b.x, b.y); te(w, g(T4), 'touchmove', [[b.x, b.y]]); await frame(w);
  check(tm.defaultPrevented && e('MM.pan.x') === px, 'map, touch: the lifted branch follows, the map stays');
  check(g(T1)?.classList.contains('drop'), 'map, touch: the target under the finger is marked');
  finger(d, 'touchend', b.x, b.y); te(w, g(T4), 'touchend', []);
  check(await until(async () => await parent(T4) === T1), 'map, touch: held and dropped = hangs under the target');
  await until(() => g(T3)); await sleep(200);
  // two fingers on a branch: a pinch zooms, no branch lifts or moves
  a = at(T3); const k0 = e('MM.pan.k');
  finger(g(T3), 'touchstart', a.x, a.y, 1); te(w, g(T3), 'touchstart', [[a.x, a.y]]);
  finger(g(T3), 'touchstart', a.x + 50, a.y, 2); te(w, g(T3), 'touchstart', [[a.x, a.y], [a.x + 50, a.y]]);
  await sleep(600);
  finger(d, 'touchmove', a.x + 100, a.y, 2); te(w, g(T3), 'touchmove', [[a.x, a.y], [a.x + 100, a.y]]); await frame(w);
  check(e('MM.pan.k') > k0 * 1.5 && !d.querySelector('#view .mmstage .lift, #view .mmnode.drop'), 'map, touch: two fingers zoom, no drag starts ' + e('MM.pan.k'));
  finger(d, 'touchend', a.x + 100, a.y, 2); finger(d, 'touchend', a.x, a.y, 1); te(w, g(T3) || d, 'touchend', []);
  await sleep(400);
  check(await parent(T3) === null, 'map, touch: after the pinch nothing is rehung');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
