// D3 UI tests (jsdom), fresh DB: touch drag and drop in the sidebar (phone drawer). Long-press a list, then drag:
// reorder, into a folder (onto its header), out of a folder (onto the "Lists" header), with the same highlights as the
// mouse, one request per drop and an undo for folder moves; long-press a folder and drag: reorder folders; a closed
// folder opens while hovered; the drawer auto-scrolls; held without moving = the list menu with "Move to folder…";
// a tap still opens the list; Android's contextmenu during the hold is swallowed. (jsdom has no layout: the element
// under the finger is stubbed with document.elementFromPoint.)
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const st = async () => call('GET', '/api/state');
const toastText = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';
const touch = (w, el, type, y = 20) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' || type === 'touchcancel' ? [] : [{clientX: 40, clientY: y}]; el.dispatchEvent(e); return e; };
const spy = w => { const calls = []; const of = w.fetch; w.fetch = (u, o = {}) => { calls.push([(o.method || 'GET').toUpperCase(), String(u)]); return of(u, o); }; return calls; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const L = async (name, folder = '') => (await call('POST', '/api/lists', {name, ...(folder ? {folder} : {})})).id;
  const L1 = await L('Home'), L2 = await L('Garden'), L3 = await L('Car'), L4 = await L('Taxes', 'Admin'), L5 = await L('Reading', 'Hobby');
  await call('PATCH', '/api/settings', {folders: '["Admin", "Hobby"]'});
  const order = async () => { const s = await st(); const ls = s.lists.filter(l => !l.is_inbox && !l.archived).sort((a, b) => a.sort - b.sort || a.id - b.id); return ls.map(l => l.id); };
  const folderOf = async id => (await st()).lists.find(l => l.id === id).folder;

  const w = await boot({user: 'alice', hash: 'today', mobile: true, media: {'(hover: none)': true}}); const d = w.document;
  const calls = spy(w);
  let under = null;
  d.elementFromPoint = () => under;
  const row = id => d.querySelector(`#side .srow[data-list="${id}"]`);
  const fold = f => d.querySelector(`#side .fhead[data-folder="${f}"]`);
  d.querySelector('[data-act="side"]').click();
  check(d.querySelector('#side.open'), 'drawer open');
  const drag = async (el, target, {hold = 420, end = 'touchend'} = {}) => {
    touch(w, el, 'touchstart'); await sleep(hold);
    under = target; const mv = touch(w, el, 'touchmove', 60);
    const e = touch(w, el, end, 60); under = null;
    return {mv, e};
  };
  // ---- reorder: Car before Home
  touch(w, row(L3), 'touchstart'); await sleep(420);
  check(d.querySelector('.side-ghost') && row(L3).classList.contains('dragging'), 'long-press: the row lifts (ghost)');
  under = row(L1); const mv = touch(w, row(L3), 'touchmove', 60);
  check(mv.defaultPrevented && row(L1).classList.contains('dropbefore'), 'dragging over a list: insert mark (the drawer does not scroll)');
  calls.length = 0;
  const te = touch(w, row(L3), 'touchend', 60); under = null;
  check(te.defaultPrevented && !d.querySelector('.side-ghost'), 'drop: no click after the hold, ghost gone');
  check(await until(async () => { const o = await order(); return o.indexOf(L3) < o.indexOf(L1); }), 'Car now before Home (server)');
  check(calls.filter(c => c[0] !== 'GET').length === 1, 'one request per drop');
  check(d.querySelector('#side.open'), 'the drawer stays open');
  // ---- into a folder: Home onto "Admin"
  await drag(row(L1), fold('Admin'));
  check(await until(async () => (await folderOf(L1)) === 'Admin'), 'dropped on a folder header: moved into the folder');
  check(await until(() => /Moved to folder Admin/.test(toastText(d)) && d.querySelector('#toast button')), `toast with Undo: ${toastText(d)}`);
  d.querySelector('#toast button').click();
  check(await until(async () => (await folderOf(L1)) === ''), 'undo: out of the folder again');
  // ---- out of a folder: Taxes onto the "Lists" header
  await sleep(300);
  await drag(row(L4), d.querySelector('#side .shead.lroot'));
  check(await until(async () => (await folderOf(L4)) === ''), 'dropped on the Lists header: out of the folder');
  check(await until(() => /Removed from folder/.test(toastText(d))), 'toast');
  // ---- between top-level rows takes over their folder: Reading before Garden
  await drag(row(L5), row(L2));
  check(await until(async () => (await folderOf(L5)) === '' && (await order()).indexOf(L5) < (await order()).indexOf(L2)), 'dropped before a top-level list: top level, in place');
  // ---- folders: Hobby before Admin
  await call('PATCH', `/api/lists/${L5}`, {folder: 'Hobby'}); await w.eval('load().then(() => render())'); await sleep(200);
  touch(w, fold('Hobby'), 'touchstart'); await sleep(420);
  under = fold('Admin'); touch(w, fold('Hobby'), 'touchmove', 60);
  check(fold('Admin').classList.contains('dropbefore'), 'folder drag: insert mark on the other folder');
  touch(w, fold('Hobby'), 'touchend', 60); under = null;
  check(await until(async () => JSON.parse((await st()).settings.folders)[0] === 'Hobby'), 'folders reordered');
  // ---- a closed folder opens while hovered
  w.eval("S.collapsed.add('fold:Admin'); renderSide()");
  check(fold('Admin').classList.contains('closed'), 'Admin closed');
  touch(w, row(L2), 'touchstart'); await sleep(420);
  under = fold('Admin'); touch(w, row(L2), 'touchmove', 60); await sleep(700);
  check(!fold('Admin').classList.contains('closed'), 'hovering a closed folder opens it');
  // auto-scroll near the bottom edge
  let scrolled = 0; const sideEl = d.querySelector('#side'); sideEl.scrollBy = (x, y) => { scrolled += y; }; sideEl.getBoundingClientRect = () => ({top: 0, bottom: 800, left: 0, right: 300, width: 300, height: 800});
  under = null; touch(w, row(L2), 'touchmove', 5000);
  check(scrolled > 0, 'near the bottom edge the drawer scrolls');
  touch(w, row(L2), 'touchcancel'); await sleep(100);
  check(!d.querySelector('.side-ghost'), 'cancel: nothing moved, ghost gone');
  // ---- held without moving: the list menu with "Move to folder…"
  touch(w, row(L2), 'touchstart'); await sleep(420);
  const cm = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}); row(L2).dispatchEvent(cm);
  check(cm.defaultPrevented && !d.querySelector('#pop:not(.hidden)'), "Android's contextmenu during the hold is swallowed");
  touch(w, row(L2), 'touchend'); await sleep(150);
  let pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Move to folder…/.test(pop.textContent) && /Edit list…/.test(pop.textContent), 'held without moving: list menu with "Move to folder…"');
  [...pop.querySelectorAll('button')].find(b => /Move to folder…/.test(b.textContent)).click(); await sleep(150);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Hobby/.test(pop.textContent) && /No folder/.test(pop.textContent), 'folder picker');
  [...pop.querySelectorAll('button')].find(b => b.textContent.trim() === 'Hobby').click();
  check(await until(async () => (await folderOf(L2)) === 'Hobby'), 'picked: moved into Hobby');
  // ---- a tap still opens the list
  await w.eval('load().then(() => render())'); d.querySelector('[data-act="side"]').click(); await sleep(100);
  touch(w, row(L3), 'touchstart'); await sleep(80);
  const tap = touch(w, row(L3), 'touchend');
  check(!tap.defaultPrevented, 'a quick tap is not swallowed');
  row(L3).click(); await sleep(200);
  check(w.location.hash === '#l/' + L3, 'tap: the list opens');
  // ---- reorder mode buttons stay as the accessible alternative
  d.querySelector('[data-act="side"]').click(); await sleep(50);
  d.querySelector('[data-act="lists-reorder"]').click(); await sleep(50);
  // 2.25.0 (UX-02): a bar "Sort lists – Done", full names, a grip, ONE "…" per list with up / down / folder
  check(d.querySelector('#side .sreobar [data-act="lists-reorder"]') && d.querySelector('#side .srow.reorder .sgrip') && !d.querySelector('#side .srow.reorder [data-lmove]'), 'reorder mode: bar with Done, grip, no arrow buttons');
  d.querySelector(`#side .srow.reorder[data-list="${L3}"] [data-lsort]`).click(); await sleep(50);
  const ml = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(ml.some(x => /Move up/.test(x)) && ml.some(x => /Move down/.test(x)) && ml.some(x => /Move to folder/.test(x)), 'reorder mode: "…" = up / down / folder: ' + ml.join(' | '));
  w.eval('closePop()');
  d.querySelector('#side .sreobar [data-act="lists-reorder"]').click(); await sleep(50);
  check(!d.querySelector('#side .srow.reorder') && !w.eval('S.listReorder'), 'Done ends the sort mode');
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
