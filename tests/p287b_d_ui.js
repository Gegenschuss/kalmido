// 2.87.9 part D UI tests (#1965, drags follow the pointer once per frame; own container, start.sh). jsdom:
// - rafThrottle: many calls in one frame run once, with the last arguments; flush() runs a pending call at once
// - the grip of the task panel with 300 tasks in the list: 60 pointer moves within one frame = no measuring and no
//   storing while the events come in, one width update in the next frame, stored once on release (the width it showed)
// - the drop highlight of a mouse drag: 60 dragover events over the same half of the same row change the classes once;
//   the other half / another row moves it
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P287BD_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    return r.json().catch(() => ({}));
  }
};
const pe = (w, el, type, x, y = 300) => {
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0});
  if (!w.PointerEvent) { Object.defineProperty(ev, 'pointerId', {value: 1}); Object.defineProperty(ev, 'pointerType', {value: 'mouse'}); }
  el.dispatchEvent(ev); return ev;
};
const frame = w => new Promise(r => w.requestAnimationFrame(() => w.requestAnimationFrame(r)));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Many'})).id;
  check(L > 0, 'setup: a list');
  const T = [];
  for (let i = 0; i < 300; i += 10) T.push(...(await Promise.all(Array.from({length: 10}, (_, j) => call('POST', '/api/tasks', {title: 'Row ' + (i + j + 1), list_id: L})))).map(t => t.id));
  check(T.filter(Boolean).length === 300, 'setup: 300 tasks ' + T.filter(Boolean).length);

  const w = await boot({user: 'alice', hash: 'l/' + L, setup: x => { Object.defineProperty(x, 'innerWidth', {configurable: true, value: 1600}); }}), d = w.document;  // 2.209.0 (#2772): wide, so the task panel is not shrunk (25.5 rem at the start of the drag)
  await sleep(800);
  check(d.querySelectorAll('#view .trow[data-id]').length > 0, 'the list shows its rows');

  // ---- rafThrottle
  w.eval(`window._rt = []; window._rf = rafThrottle((a, b) => window._rt.push(a + b));`);
  w.eval(`for (let i = 0; i < 60; i++) _rf(i, 1)`);
  check(w.eval('_rt.length') === 0, 'rafThrottle: nothing runs while the events come in');
  await frame(w);
  check(JSON.stringify(w.eval('_rt')) === '[60]', 'rafThrottle: one run per frame, with the last arguments ' + JSON.stringify(w.eval('_rt')));
  w.eval(`_rf(5, 5); _rf.flush()`);
  check(JSON.stringify(w.eval('_rt')) === '[60,10]', 'rafThrottle: flush() runs the pending call at once');
  w.eval(`_rf(1, 1); _rf.cancel()`); await frame(w);
  check(w.eval('_rt.length') === 2, 'rafThrottle: cancel() drops it');

  // ---- the task panel's grip: 60 moves in one frame
  w.eval(`openDetail(${T[0]})`); await sleep(500);
  w.eval('placeGrips()');
  const g = d.getElementById('pgrip-det');
  check(!!g, 'the grip of the task panel');
  if (g) {
    // jsdom has no layout: the panel's right edge is 0, so x = -rem * width
    const rem = w.eval('parseFloat(getComputedStyle(document.documentElement).fontSize) || 16'), mx = w.eval(`panelMax('det')`);
    const want = Math.max(20, Math.round(Math.min(mx, 22) * 4) / 4);
    w.eval(`window._gbr = 0; { const o = Element.prototype.getBoundingClientRect; Element.prototype.getBoundingClientRect = function () { window._gbr++; return o.call(this); }; }`);
    const st0 = JSON.stringify(w.__store), f0 = w.eval('DRAGSTAT.frames');
    pe(w, g, 'pointerdown', -rem * 25.5);
    const b0 = w.eval('_gbr');
    for (let i = 1; i <= 60; i++) pe(w, g, 'pointermove', -rem * (25.5 + (want - 25.5) * i / 60));
    check(w.eval('_gbr') === b0, `#1965: no measuring while the moves come in (${w.eval('_gbr') - b0} reads)`);
    check(JSON.stringify(w.__store) === st0, '#1965: nothing stored while dragging');
    check(d.documentElement.style.getPropertyValue('--detW') === '25.5rem', '#1965: the width waits for the frame ' + d.documentElement.style.getPropertyValue('--detW'));
    await frame(w);
    check(w.eval('DRAGSTAT.frames') - f0 === 1, `#1965: 60 moves = one update (${w.eval('DRAGSTAT.frames') - f0} frames)`);
    check(d.documentElement.style.getPropertyValue('--detW') === want + 'rem', '#1965: the panel shows the dragged width ' + d.documentElement.style.getPropertyValue('--detW'));
    check(JSON.stringify(w.__store) === st0, '#1965: still nothing stored');
    pe(w, g, 'pointerup', -rem * want);
    check(+w.__store['tasks.pw.det'] === want, '#1965: stored once on release ' + w.__store['tasks.pw.det']);
    check(!d.body.classList.contains('pgdrag') && !g.style.transform, '#1965: after the drag: no drag cursor sheet, the grip back in place');
    w.eval(`localStorage.removeItem('tasks.pw.det'); panelVars();`);
    w.eval('closeDetail()'); await sleep(300);
  }

  // ---- the drop highlight of a mouse drag
  const rows = [...d.querySelectorAll('#view .trow[data-id]')];
  const src = rows[0], over = rows[3], other = rows[5];
  if (src && over && other) {
    const dt = {setData() {}, getData() { return ''; }, effectAllowed: '', dropEffect: '', types: [], files: []};
    const de = (el, type, y = 0) => { const ev = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientY: y}); Object.defineProperty(ev, 'dataTransfer', {value: dt}); el.dispatchEvent(ev); return ev; };
    src.setAttribute('draggable', 'true'); de(src, 'dragstart'); await sleep(60);
    let n = 0; const mo = new w.MutationObserver(m => { n += m.length; }); mo.observe(d.querySelector('#view'), {attributes: true, attributeFilter: ['class'], subtree: true});
    let allowed = 0;
    for (let i = 0; i < 60; i++) if (de(over, 'dragover').defaultPrevented) allowed++;
    await sleep(20);
    check(allowed === 60, '#1965: every dragover over a row still allows the drop');
    check(over.classList.contains('dropbefore') && d.querySelectorAll('.dropbefore, .dropafter').length === 1, '#1965: the row shows where it lands');
    check(n <= 2, `#1965: 60 dragovers on the same place change the classes once (${n} changes)`);
    over.getBoundingClientRect = () => ({top: 0, bottom: 40, height: 40, left: 0, right: 400, width: 400});
    de(over, 'dragover', 30);
    check(over.classList.contains('dropafter') && !over.classList.contains('dropbefore'), '#1965: the lower half moves the mark below the row');
    de(other, 'dragover');
    check(other.classList.contains('dropbefore') && !over.classList.contains('dropafter'), '#1965: another row takes the mark');
    over.classList.remove('dropbefore', 'dropafter'); other.classList.remove('dropbefore');
    de(other, 'dragover');
    check(other.classList.contains('dropbefore'), '#1965: a mark taken away by someone else comes back');
    mo.disconnect();
    de(src, 'dragend');
    check(!d.querySelector('.dropbefore, .dropafter, .drop'), '#1965: dragend clears the marks');
  } else check(false, 'setup: rows for the drag');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p287b_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
