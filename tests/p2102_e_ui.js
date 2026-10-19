// 2.102.0 part E UI tests (#1999, #1998; own container, start.sh). jsdom:
// - clienterr.js: off until the server operator chose a list (nothing sent); then an unhandled error is sent once with the
//   place below /static/ only (origin, query dropped), a short stack of such places, the version and the area (no id);
//   the same error once, "Script error." and an extension's script never, at most 20 per page load; a rejected promise
//   is sent, an expected one (offline, an answer of the server, the session's end) not; the server takes it (204)
// - drag.js: below the threshold no drag (a tap), past it onStart / onMove / onDrop with the pointer's place, the click
//   after a drag is swallowed (not after a tap), Esc cancels, a ghost follows by transform and goes, a second finger
//   cancels, a long press: a move during the hold ends the press (a scroll), after the hold it drags; drg_begin starts at
//   once (ghost now, a release without moving = onTap); accept decides instead of the threshold
// - secdrag.js / sheetdrag.js keep their tests (p2461_a_ui.js, p2391_m_ui.js) unchanged
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2102E_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    return r.json().catch(() => ({}));
  }
};
const pe = (w, el, type, x, y = 100) => {
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0});
  if (!w.PointerEvent) { Object.defineProperty(ev, 'pointerId', {value: 1}); Object.defineProperty(ev, 'pointerType', {value: 'mouse'}); }
  el.dispatchEvent(ev); return ev;
};
// a touch event (jsdom has no Touch constructor): touches as plain objects
const te = (w, el, type, pts) => {
  const ev = new w.Event(type, {bubbles: true, cancelable: true});
  const list = pts.map(([x, y]) => ({identifier: 1, target: el, clientX: x, clientY: y}));
  Object.defineProperty(ev, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : list});
  Object.defineProperty(ev, 'changedTouches', {value: list});
  el.dispatchEvent(ev); return ev;
};
const frame = w => new Promise(r => w.requestAnimationFrame(() => w.requestAnimationFrame(r)));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call('POST', '/api/lists', {name: 'Errors', kind: 'project'})).id;
  check(P > 0, 'setup: a project list');

  // ================================================================ clienterr.js, off
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  await sleep(600);
  const sent = [];
  const realFetch = w.fetch;
  w.fetch = (u, o = {}) => { if (String(u).includes('/api/client-errors')) sent.push(JSON.parse(o.body)); return realFetch(u, o); };
  const fire = (msg, file, line, col, stack) => w.dispatchEvent(new w.ErrorEvent('error', {message: msg, filename: file, lineno: line, colno: col,
    error: Object.assign(new w.Error(msg), {stack: stack || ''})}));
  check(w.eval('S.about.client_errors') === false, 'off by default: S.about.client_errors is false');
  fire('TypeError: off test', B + 'static/js/render.js', 1, 1);
  await sleep(300);
  check(sent.length === 0, 'off: nothing is sent');
  w.close();

  // ================================================================ clienterr.js, on
  await call('PATCH', `/api/lists/${P}/error-hook`, {state: 'on'});
  const st = await call('PATCH', '/api/admin/settings', {client_errors_list: P});
  check(st.client_errors_list === P, 'setup: the admin chose the list ' + JSON.stringify(st.client_errors_list));
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  await sleep(600);
  sent.length = 0;
  const answers = [];
  const realFetch2 = w.fetch;
  w.fetch = (u, o = {}) => {
    if (!String(u).includes('/api/client-errors')) return realFetch2(u, o);
    sent.push(JSON.parse(o.body));
    return realFetch2(u, o).then(r => { answers.push(r.status); return r; });
  };
  check(w.eval('S.about.client_errors') === true, 'on: S.about.client_errors');
  const fire2 = (msg, file, line, col, stack) => w.dispatchEvent(new w.ErrorEvent('error', {message: msg, filename: file, lineno: line, colno: col,
    error: Object.assign(new w.Error(msg), {stack: stack || ''})}));
  fire2('TypeError: a.b is not a function', B + 'static/js/render.js?v=9', 120, 7,
        `drawRow@${B}static/js/render.js?v=9:120:7\nrender@${B}static/js/render.js:40:3\nx@https://other.example/lib.js:1:1`);
  await sleep(500);
  const e0 = sent[0] || {};
  check(sent.length === 1, 'on: the error is sent ' + sent.length);
  check(e0.src === '/static/js/render.js' && e0.line === 120 && e0.col === 7, 'the place: /static/ path, line, column ' + JSON.stringify(e0));
  check(e0.stack === 'drawRow /static/js/render.js:120:7\nrender /static/js/render.js:40:3', 'the stack: only /static/ places, no origin, no query ' + JSON.stringify(e0.stack));
  check(e0.kind === 'error' && typeof e0.ver === 'string' && e0.view && !/\d/.test(e0.view), 'kind, version, the area without an id ' + JSON.stringify([e0.kind, e0.ver, e0.view]));
  check(!JSON.stringify(e0).includes(String(B).replace(/\/$/, '')), 'no origin anywhere in the report');
  check(answers[0] === 204, 'the server takes it (204) ' + answers[0]);
  fire2('TypeError: a.b is not a function', B + 'static/js/render.js', 120, 9);
  fire2('Script error.', '', 0, 0);
  fire2('Boom from an extension', 'moz-extension://abc/content.js', 3, 4);
  await sleep(300);
  check(sent.length === 1, 'the same error, "Script error." and an extension never ' + sent.length);
  // rejected promises
  const rej = reason => { const ev = new w.Event('unhandledrejection'); Object.defineProperty(ev, 'reason', {value: reason}); w.dispatchEvent(ev); };
  rej(w.eval(`new Offline('offline')`));
  rej(Object.assign(new w.Error('Not allowed'), {status: 403, data: {error: 'Not allowed'}}));
  rej(new w.Error('auth'));
  await sleep(200);
  check(sent.length === 1, 'expected rejections (offline, a server answer, the session) are not sent ' + sent.length);
  rej(Object.assign(new w.Error('Cannot read properties of null'), {stack: `f@${B}static/js/detail.js:5:6`}));
  await sleep(300);
  const e1 = sent[1] || {};
  check(sent.length === 2 && e1.kind === 'rejection' && e1.stack === 'f /static/js/detail.js:5:6', 'a rejected promise is sent ' + JSON.stringify(e1));
  for (let i = 0; i < 30; i++) fire2('Limit ' + i, B + 'static/js/core.js', 10 + i, 1);
  await sleep(500);
  check(sent.length === 20, 'at most 20 per page load ' + sent.length);
  w.close();
  await call('PATCH', '/api/admin/settings', {client_errors_list: null});

  // ================================================================ drag.js
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  await sleep(400);
  w.eval(`window._box = document.createElement('div'); _box.id = 'drgbox'; _box.innerHTML = '<span class="it">Item</span>'; document.body.appendChild(_box);
    window._log = []; window._drg = {start: (t, x, y, kind) => t.closest('#drgbox') ? {kind} : null,
      onStart: (d, x, y) => _log.push('start ' + x + ',' + y), onMove: (d, x, y, dx, dy) => _log.push('move ' + dx + ',' + dy),
      onDrop: (d, x, y) => _log.push('drop ' + x + ',' + y + ' ' + d.kind), onCancel: () => _log.push('cancel'), onTap: () => _log.push('tap'),
      ghost: {el: _box.querySelector('.it'), cls: 'drgtest-ghost'}};
    drg_attach(_box, _drg);`);
  const box = d.getElementById('drgbox'), it = box.querySelector('.it');
  const log = () => w.eval('_log.splice(0).join("|")');
  // a tap: below the threshold
  pe(w, it, 'pointerdown', 100, 100); pe(w, it, 'pointermove', 103, 102); pe(w, it, 'pointerup', 103, 102);
  check(log() === 'tap', 'below the threshold: a tap, no drag');
  let clicked = 0; box.addEventListener('click', () => clicked++);
  it.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  check(clicked === 1, 'the click after a tap goes through');
  // a drag
  pe(w, it, 'pointerdown', 100, 100);
  pe(w, it, 'pointermove', 110, 100);
  check(!!d.querySelector('.drgtest-ghost'), 'a ghost follows the drag');
  pe(w, it, 'pointermove', 140, 130);
  check(d.querySelector('.drgtest-ghost')?.style.transform === 'translate(40px, 30px)', 'the ghost slides by transform ' + d.querySelector('.drgtest-ghost')?.style.transform);
  pe(w, it, 'pointerup', 140, 130);
  check(log() === 'start 110,100|move 10,0|move 40,30|drop 140,130 mouse', 'past the threshold: start, moves, drop with the place');
  check(!d.querySelector('.drgtest-ghost'), 'the ghost goes after the drop');
  it.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  check(clicked === 1, 'the click after a drag is swallowed');
  await sleep(400);
  // Esc cancels
  pe(w, it, 'pointerdown', 100, 100); pe(w, it, 'pointermove', 120, 100);
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
  pe(w, it, 'pointermove', 150, 100); pe(w, it, 'pointerup', 150, 100);
  check(log() === 'start 120,100|move 20,0|cancel', 'Esc cancels; later moves do nothing');
  check(!d.querySelector('.drgtest-ghost') && w.eval('drg_cur') === null, 'nothing left after Esc');
  await sleep(400);
  // touch: a drag, a second finger cancels
  te(w, it, 'touchstart', [[50, 50]]); const mv = te(w, it, 'touchmove', [[50, 70]]); te(w, it, 'touchend', [[50, 70]]);
  check(log() === 'start 50,70|move 0,20|drop 50,70 touch' && mv.defaultPrevented, 'touch: a drag, the page does not scroll under it');
  await sleep(400);
  te(w, it, 'touchstart', [[50, 50]]); te(w, it, 'touchmove', [[50, 70]]); te(w, it, 'touchstart', [[50, 70], [90, 90]]);
  check(log() === 'start 50,70|move 0,20|cancel', 'touch: a second finger cancels');
  await sleep(400);
  // a long press
  w.eval(`window._box2 = document.createElement('div'); _box2.id = 'drgbox2'; document.body.appendChild(_box2);
    drg_attach(_box2, {..._drg, ghost: null, hold: 300, start: t => t.closest('#drgbox2') ? {kind: 'hold'} : null});`);
  const b2 = d.getElementById('drgbox2');
  te(w, b2, 'touchstart', [[10, 10]]); const sc = te(w, b2, 'touchmove', [[10, 40]]);
  check(log() === 'cancel' && !sc.defaultPrevented, 'a long press: moving during the hold ends it (the page scrolls)');
  te(w, b2, 'touchstart', [[10, 10]]); await sleep(350); te(w, b2, 'touchmove', [[10, 40]]); te(w, b2, 'touchend', [[10, 40]]);
  check(log() === 'start 10,40|move 0,30|drop 10,40 hold', 'after the hold the move drags');
  await sleep(400);
  // drg_begin: at once, a release without moving = tap
  w.eval(`window._h = document.createElement('div'); _h.className = 'hd'; _h.textContent = 'Head'; document.body.appendChild(_h);
    drg_begin(_h, 20, 20, {..._drg, ghost: {el: _h, cls: 'drgtest-g2'}}, {kind: 'begun'});`);
  const hh = d.querySelector('.hd');
  check(!!d.querySelector('.drgtest-g2'), 'drg_begin: the ghost shows at once');
  const endEv = te(w, hh, 'touchend', [[20, 20]]);
  check(log() === 'tap' && !d.querySelector('.drgtest-g2') && endEv.defaultPrevented, 'drg_begin: let go without moving = onTap, no click follows');
  w.eval(`drg_begin(_h, 20, 20, _drg, {kind: 'begun'})`);
  te(w, hh, 'touchmove', [[20, 23]]); te(w, hh, 'touchmove', [[20, 60]]); te(w, hh, 'touchend', [[20, 60]]);
  check(log() === 'start 20,60|move 0,40|drop 20,60 begun', 'drg_begin: the drag follows the touch on the element');
  await sleep(400);
  // accept instead of the threshold (sheetdrag: vertical only)
  w.eval(`drg_attach(document.body, {..._drg, ghost: null, start: t => t.closest('.hd') ? {kind: 'acc'} : null,
    accept: (d, dx, dy) => Math.abs(dx) < 8 && Math.abs(dy) < 8 ? null : Math.abs(dx) > Math.abs(dy) ? false : true});`);
  te(w, hh, 'touchstart', [[20, 20]]); te(w, hh, 'touchmove', [[40, 22]]);
  check(log() === 'cancel', 'accept: a sideways move gives up');
  te(w, hh, 'touchstart', [[20, 20]]); te(w, hh, 'touchmove', [[25, 25]]); te(w, hh, 'touchmove', [[22, 40]]); te(w, hh, 'touchend', [[22, 40]]);
  check(log() === 'start 22,40|move 2,20|drop 22,40 acc', 'accept: a vertical move drags, below 8 px waits');
  check(typeof w.eval('drg_reduced()') === 'boolean', 'drg_reduced answers');

  check(errs.length === 0, 'no script errors ' + errs.slice(0, 3).join(' | '));
  console.log(`p2102_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
