// 2.551.0 (#4615) UI tests (jsdom), fresh DB: a favourite tile dragged out of the bar is removed
// - mouse: dragged well below the bar (about 1.5 tile heights) the tile is crossed out and the bar says "Release to remove";
//   back in the bar it is a normal move again; let go outside = removed, the hint has Undo (back in its place); Esc keeps it
// - touch: hold, drag out, let go = removed with Undo (a list's star too); hold and let go without moving = the menu as before
// The layout is set by the test (jsdom has none): the bar 0-40 px, a tile 30 px high.
// kalmido-suite: fresh
const {boot, errs, B, login, until, undoToast} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const items = async () => JSON.parse((await call('GET', '/api/state')).settings?.fav_items || '[]');
const OUT_Y = 40 + 1.5 * 30 + 15, NEAR_Y = 40 + 20, IN_Y = 20;  // well below / just below / in the bar

// the page's layout: bar 0..40, tiles 30 high side by side; elementFromPoint finds a tile inside the bar, nothing outside
const GEO = `(() => {
  const gb = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function () {
    const r = (l, t, w, h) => ({left: l, top: t, width: w, height: h, right: l + w, bottom: t + h, x: l, y: t});
    if (this.matches?.('#kbar .fv2bar')) return r(100, 0, 500, 40);
    if (this.matches?.('#kbar .fv2bar [data-fv2]')) { const i = [...this.parentNode.children].indexOf(this); return r(104 + i * 34, 5, 30, 30); }
    return gb.call(this);
  };
  document.elementFromPoint = (x, y) => y < 0 || y > 40 ? document.body : [...document.querySelectorAll('#kbar .fv2bar [data-fv2]')].find(t => { const b = t.getBoundingClientRect(); return x >= b.left && x <= b.right; }) || document.querySelector('#kbar .fv2bar');
  return 1; })()`;

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  await call('PUT', `/api/lists/${L}/favorite`, {on: true});
  check((await call('PATCH', '/api/settings', {fav_items: ['v:today', `l:${L}`, 'v:tomorrow']})).status === 200, 'setup: three favourites');
  check((await items()).join() === `v:today,l:${L},v:tomorrow`, 'setup: stored ' + (await items()));

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const tile = k => d.querySelector(`#kbar .fv2bar [data-fv2="${k}"]`), bar = () => d.querySelector('#kbar .fv2bar');
  check(await until(() => tile('v:today') && tile(`l:${L}`) && tile('v:tomorrow')), 'the bar shows the three tiles');
  w.eval(GEO);
  const dt = {effectAllowed: '', dropEffect: '', setData() {}, getData: () => '', types: ['text/plain']};
  const drag = (type, el, x, y) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); for (const [k, v] of [['clientX', x], ['clientY', y], ['dataTransfer', dt]]) Object.defineProperty(e, k, {value: v}); el.dispatchEvent(e); return e; };
  const outShown = k => tile(k)?.classList.contains('fv2-out') && bar().classList.contains('fv2-outing') && bar().dataset.out === 'Release to remove';
  const noOut = () => !d.querySelector('#kbar .fv2-out') && !bar().classList.contains('fv2-outing') && !bar().dataset.out;

  // ================= mouse
  drag('dragstart', tile('v:today'), 120, IN_Y);
  check(w.eval('FV2.drag') === 'v:today', 'mouse: dragging the tile');
  drag('dragover', d.body, 120, NEAR_Y);
  check(noOut(), 'mouse: just below the bar: not out yet');
  const ov = drag('dragover', d.body, 120, OUT_Y);
  check(outShown('v:today') && ov.defaultPrevented, 'mouse: well below: crossed out, the bar says "Release to remove"');
  drag('dragover', tile('v:tomorrow'), 104 + 2 * 34 + 25, IN_Y);
  check(noOut(), 'mouse: back in the bar: a normal move again');
  drag('dragover', d.body, 120, OUT_Y);
  check(outShown('v:today'), 'mouse: out again');
  drag('dragend', tile('v:today'), 0, 0);  // Esc: no drop
  check(noOut() && !w.eval('FV2.drag') && tile('v:today'), 'mouse: Esc / no drop: the tile stays, the marks are gone');
  check((await items()).includes('v:today'), 'mouse: Esc: still a favourite');

  let src = tile('v:today'); drag('dragstart', src, 120, IN_Y);  // the source element: a real dragend fires on it even when the bar drew it away
  drag('dragover', d.body, 120, OUT_Y);
  drag('drop', d.body, 120, OUT_Y); drag('dragend', src, 0, 0);
  check(await until(() => !tile('v:today')), 'mouse: let go outside: the tile is gone');
  check(await until(async () => (await items()).join() === `l:${L},v:tomorrow`), 'mouse: removed on the server ' + (await items()));
  check(noOut(), 'mouse: no marks left');
  check(await undoToast(w, /Removed from favourites/), 'mouse: the hint has Undo');
  check(await until(async () => (await items()).join() === `v:today,l:${L},v:tomorrow`), 'mouse: Undo: back in its place ' + (await items()));
  check(await until(() => tile('v:today')), 'mouse: Undo: the tile is back');

  // a move inside the bar still works (the first behind the third)
  w.eval(GEO);
  src = tile('v:today'); drag('dragstart', src, 120, IN_Y);
  drag('dragover', tile('v:tomorrow'), 104 + 2 * 34 + 25, IN_Y);
  drag('drop', tile('v:tomorrow'), 104 + 2 * 34 + 25, IN_Y); drag('dragend', src, 0, 0);
  check(await until(async () => (await items()).join() === `l:${L},v:tomorrow,v:today`), 'mouse: moving inside the bar still works ' + (await items()));

  // ================= touch
  const touch = (type, el, x, y) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); const p = [{clientX: x, clientY: y}]; Object.defineProperty(e, 'touches', {value: type === 'touchend' ? [] : p}); Object.defineProperty(e, 'changedTouches', {value: p}); el.dispatchEvent(e); return e; };
  await until(() => tile(`l:${L}`)); w.eval(GEO);
  const lt = tile(`l:${L}`), lx = lt.getBoundingClientRect().left + 10;
  touch('touchstart', lt, lx, IN_Y);
  check(await until(() => w.eval('FV2.drag') === `l:${L}`), 'touch: holding the list tile starts the drag');
  touch('touchmove', lt, lx, NEAR_Y);
  check(noOut(), 'touch: just below: not out');
  touch('touchmove', lt, lx, OUT_Y);
  check(outShown(`l:${L}`), 'touch: well below: crossed out, "Release to remove"');
  touch('touchmove', lt, lx, IN_Y);
  check(noOut(), 'touch: back in the bar: normal again');
  touch('touchmove', lt, lx, OUT_Y);
  touch('touchend', lt, lx, OUT_Y);
  check(await until(() => !tile(`l:${L}`)), 'touch: let go outside: the list tile is gone');
  check(await until(async () => { const s = (await call('GET', '/api/state')).settings || {}; return !JSON.parse(s.fav_items || '[]').includes(`l:${L}`) && !String(s.fav_lists || '').split(',').includes(String(L)); }), 'touch: the list is no favourite any more');
  check(await undoToast(w, /Removed from favourites/), 'touch: the hint has Undo (a list too)');
  check(await until(async () => (await items()).join() === `l:${L},v:tomorrow,v:today`), 'touch: Undo: the list back in its place ' + (await items()));

  // hold and let go without moving: the menu as before
  await until(() => tile('v:tomorrow')); w.eval(GEO);
  const ut = tile('v:tomorrow');
  touch('touchstart', ut, 150, IN_Y);
  check(await until(() => w.eval('FV2.drag') === 'v:tomorrow'), 'touch: holding');
  touch('touchend', ut, 150, IN_Y);
  check(await until(() => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].some(b => /Remove from favourites/.test(b.textContent))), 'touch: hold and let go: the menu with "Remove from favourites"');
  check((await items()).includes('v:tomorrow') && noOut(), 'touch: nothing removed');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p2551_c_favout_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
