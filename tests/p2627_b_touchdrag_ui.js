// 2.627.0 part B UI tests (jsdom), fresh DB (#4961 #4962 #4966)
// kalmido-suite: fresh
// The last drags of a mouse without a finger way, and the three own touch paths, now by drag.js. Real touch events (touchstart / touchmove / touchend, the touches as plain objects;
// jsdom has no layout: the boxes and the element under the finger are given here):
// - the file store (#4961): a file row held and dragged onto a folder = the same move as the mouse's drop; a swipe moves
//   nothing; held without moving = the row's menu; Esc cancels; no browser drag on a touch screen, the mouse keeps it
// - the area rail (#4962): an icon held and dragged onto the lower half of the first = second, as the mouse; a quick tap
//   stays the browser's (it opens the area); held without moving = the icon's menu; the mouse keeps its drag
// - the sidebar's list rows (#4966): held and dragged before another list = moved; Esc and a second finger cancel
// - the sidebar's tree (#4966): a folder held and dragged before another = sorted; Esc cancels; held without moving = the menu
// - the favourite tiles (#4966): a tile held and dragged behind another = moved; Esc cancels (the tile stays)
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { let x = null; try { x = await fn(); } catch { /* not yet */ } if (x) return x; await sleep(150); } try { return await fn(); } catch { return null; } };
const upload = async (name, text, form) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name);
  for (const [k, v] of Object.entries(form || {space: 'private'})) fd.append(k, v);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return (await r.json()).items[0].id;
};
// a touch event on el: n fingers at (x, y)
const tc = (w, el, type, x, y, n = 1) => {
  const e = new w.Event(type, {bubbles: true, cancelable: true}), t = Array.from({length: n}, (_, i) => ({identifier: i + 1, target: el, clientX: x + 30 * i, clientY: y}));
  Object.defineProperty(e, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : t});
  Object.defineProperty(e, 'changedTouches', {value: t});
  el.dispatchEvent(e); return e;
};
const esc = w => w.document.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
// the browser's click after a drag: swallowed by drag.js
const after = w => w.document.body.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const box = (el, left, top, width, height) => { el.getBoundingClientRect = () => ({left, top, width, height, right: left + width, bottom: top + height, x: left, y: top}); };
const store = () => { const m = {}; return {setData(k, v) { m[k] = v; }, getData(k) { return m[k] || ''; }, get types() { return Object.keys(m); }, effectAllowed: '', dropEffect: ''}; };
const dev = (w, el, type, dt, x = 0, y = 0) => { const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: y}); Object.defineProperty(e, 'dataTransfer', {value: dt}); el.dispatchEvent(e); return e; };
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], #pop button')].map(b => b.textContent.trim());
const closeMenus = w => { try { w.eval('closePop()'); } catch { /* none open */ } };
const TOUCH = {'(hover: none)': true, '(pointer: coarse)': true};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'files,collab,comments,cal,wiki'});

  // ================================================================ the file store (#4961)
  const KISTE = (await call('POST', '/api/files/folders', {name: 'Kiste', space: 'private'})).id;
  const FILE = await upload('brief.txt', 'Hallo');
  const parent = async () => { const j = await call('GET', `/api/files/nodes/${FILE}`); return j.parent_id ?? j.node?.parent_id ?? null; };
  check((await parent()) === null, 'setup: the file at the top, a folder beside it');
  let w = await boot({user: 'alice', hash: 'ablage', media: TOUCH, ls: {abSpace: '"private"'}}), d = w.document;
  const abrow = id => d.querySelector(`#view .abview .abrow[data-abid="${id}"]`);
  check(await until(() => abrow(FILE) && abrow(KISTE)), 'touch: the file store shows the file and the folder');
  check(!abrow(FILE).hasAttribute('draggable') && abrow(FILE).dataset.abmv === '1', 'touch: no browser drag on the row, the finger holds it');
  const layAb = () => {
    box(abrow(KISTE), 0, 100, 400, 50); box(abrow(FILE), 0, 150, 400, 50);
    d.elementFromPoint = (x, y) => (y >= 100 && y < 150 ? abrow(KISTE)?.querySelector('.abopen') : y >= 150 && y < 200 ? abrow(FILE)?.querySelector('.abopen') : null) || d.body;
  };
  layAb();
  // a swipe without the hold: nothing moves
  { const r = abrow(FILE).querySelector('.abopen'); tc(w, r, 'touchstart', 50, 170); await sleep(40); tc(w, r, 'touchmove', 50, 150); tc(w, r, 'touchmove', 50, 120); tc(w, r, 'touchend', 50, 120); await sleep(300);
    check((await parent()) === null && !d.querySelector('.ghost-drag, #view .abdrop'), 'touch: a quick swipe over a file row scrolls, it moves nothing'); }
  // held, dragged onto the folder, Esc: nothing moves
  { const r = abrow(FILE).querySelector('.abopen'); tc(w, r, 'touchstart', 50, 170);
    check(await until(() => abrow(FILE).classList.contains('dragging'), 20), 'touch: the hold lifts the row');
    tc(w, r, 'touchmove', 50, 140); tc(w, r, 'touchmove', 50, 125); await sleep(60);
    check(abrow(KISTE).querySelector('.abopen').classList.contains('abdrop') && !!d.querySelector('.ghost-drag'), 'touch: the folder is marked, a copy of the row follows the finger');
    esc(w); tc(w, r, 'touchend', 50, 125); await sleep(300);
    check((await parent()) === null && !d.querySelector('.ghost-drag, #view .abdrop, #view .abrow.dragging'), 'touch: Esc cancels, nothing moved'); }
  // held, dragged onto the folder, let go
  layAb();
  { const r = abrow(FILE).querySelector('.abopen'); tc(w, r, 'touchstart', 50, 170);
    await until(() => abrow(FILE).classList.contains('dragging'), 20);
    tc(w, r, 'touchmove', 50, 140); tc(w, r, 'touchmove', 50, 125); await sleep(60);
    tc(w, r, 'touchend', 50, 125); after(w); }
  check(await until(async () => (await parent()) === KISTE), 'touch: the held file dragged onto the folder = in the folder (the same move as the mouse)');
  check(await until(() => !abrow(FILE) && !d.querySelector('.ghost-drag, #view .abdrop')), 'touch: the row left the list, nothing of the drag stays behind');
  // held without moving = the row's menu
  await call('PATCH', `/api/files/nodes/${FILE}`, {parent_id: null});
  await w.eval('ab_reload()');
  check(await until(() => abrow(FILE)), 'touch: the file is back at the top');
  layAb();
  { const r = abrow(FILE).querySelector('.abopen'); tc(w, r, 'touchstart', 50, 170); await until(() => abrow(FILE).classList.contains('dragging'), 20);
    const te = tc(w, r, 'touchend', 50, 170);
    check(te.defaultPrevented, 'touch: held and let go: no click opens the file');
    check(await until(() => items(d).some(t => /Move to…/.test(t)), 20), 'touch: held without moving = the row\'s menu ' + items(d).join('|'));
    check((await parent()) === null, 'touch: held without moving moves nothing'); closeMenus(w); }
  w.close();
  // the mouse: the browser's drag as before
  w = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: '"private"'}}); d = w.document;
  check(await until(() => abrow(FILE) && abrow(KISTE)), 'mouse: the file store');
  check(abrow(FILE).getAttribute('draggable') === 'true', 'mouse: the row keeps the browser\'s drag');
  { const dt = store(), t = abrow(KISTE).querySelector('.abopen'); dev(w, abrow(FILE), 'dragstart', dt); dev(w, t, 'dragover', dt); dev(w, t, 'drop', dt); dev(w, abrow(FILE) || d.body, 'dragend', dt); }
  check(await until(async () => (await parent()) === KISTE), 'mouse: the same move into the folder');
  w.close();

  // ================================================================ the area rail (#4962)
  const railOrder = async () => JSON.parse((await call('GET', '/api/state')).settings?.nav_menus || '{}').rail?.order || [];
  w = await boot({user: 'alice', hash: 'today', media: TOUCH}); d = w.document;
  const srbs = () => [...d.querySelectorAll('#srail .srb[data-sbb]')], rail = () => srbs().map(b => b.dataset.sbb);
  check(await until(() => srbs().length >= 3), 'touch (tablet): the rail of the areas ' + rail());
  check(srbs().every(b => !b.hasAttribute('draggable')), 'touch: no browser drag on the icons (the hold is the app\'s)');
  const layRail = () => { srbs().forEach((b, i) => box(b, 0, 100 + 50 * i, 52, 50)); d.elementFromPoint = (x, y) => srbs()[Math.floor((y - 100) / 50)] || d.body; };
  layRail();
  const R0 = rail(), mv = R0[2], first = R0[0];
  // a quick tap: the browser's (the area opens by its click)
  { const b = srbs()[2]; tc(w, b, 'touchstart', 20, 220); await sleep(60); const te = tc(w, b, 'touchend', 20, 220);
    check(!te.defaultPrevented && !b.classList.contains('dragging'), 'touch: a quick tap on an icon is not taken (it opens the area)'); }
  // held, dragged onto the lower half of the first icon, let go
  { const b = srbs()[2]; tc(w, b, 'touchstart', 20, 220);
    check(await until(() => b.classList.contains('dragging'), 20), 'touch: the hold lifts the icon');
    tc(w, b, 'touchmove', 20, 200); await sleep(40); tc(w, b, 'touchmove', 20, 140); await sleep(60);
    check(srbs()[0].classList.contains('srbdaft'), 'touch: the line marks the place after the first icon');
    tc(w, b, 'touchend', 20, 140); after(w); }
  check(await until(() => rail()[1] === mv && rail()[0] === first), 'touch: the held icon dragged onto the first one\'s lower half = second ' + rail());
  check(await until(async () => (await railOrder())[1] === mv), 'touch: the order is stored like the mouse\'s');
  check(!d.querySelector('#srail .srbdbef, #srail .srbdaft, #srail .dragging, .ghost-drag'), 'touch: nothing of the drag stays behind');
  // held without moving = the icon's menu
  layRail();
  { const b = srbs()[1]; tc(w, b, 'touchstart', 20, 170); await until(() => b.classList.contains('dragging'), 20); tc(w, b, 'touchend', 20, 170);
    check(await until(() => items(d).some(t => /Move up/.test(t)) && items(d).some(t => /Set as start area/.test(t)), 20), 'touch: held without moving = the icon\'s menu ' + items(d).join('|'));
    check(rail()[1] === mv, 'touch: held without moving moves nothing'); closeMenus(w); }
  w.close();
  // the mouse: the browser's drag as before (back to the start first)
  await call('PATCH', '/api/settings', {nav_menus: '{}'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(await until(() => srbs().length >= 3 && rail().join() === R0.join()), 'mouse: the rail as at the start');
  check(srbs().every(b => b.getAttribute('draggable') === 'true'), 'mouse: the icons keep the browser\'s drag');
  { const dt = store(), src = d.querySelector(`#srail .srb[data-sbb="${mv}"]`), dst = srbs()[0]; box(dst, 0, 100, 52, 50);
    dev(w, src, 'dragstart', dt); dev(w, dst, 'dragover', dt, 20, 140); dev(w, dst, 'drop', dt, 20, 140); dev(w, src, 'dragend', dt); }
  check(await until(() => rail()[1] === mv), 'mouse: the same place as the finger ' + rail());
  w.close();

  // ================================================================ the sidebar's list rows and tree (#4966)
  const L = async (name, folder = '') => (await call('POST', '/api/lists', {name, ...(folder ? {folder} : {})})).id;
  const L1 = await L('Home'), L3 = await L('Car'); await L('Garden'); await L('Taxes', 'Admin'); await L('Reading', 'Hobby');
  await call('PATCH', '/api/settings', {folders: '["Admin", "Hobby"]'});
  const order = async () => { const s = await call('GET', '/api/state'); return s.lists.filter(l => !l.is_inbox && !l.archived && !l.folder).sort((a, b) => a.sort - b.sort || a.id - b.id).map(l => l.id); };
  const folders = async () => JSON.parse((await call('GET', '/api/state')).settings.folders || '[]');
  const O0 = await order();
  w = await boot({user: 'alice', hash: 'today', mobile: true, media: TOUCH}); d = w.document;
  let under = null;
  d.elementFromPoint = () => typeof under === 'function' ? under() : under;
  const row = id => d.querySelector(`#side .srow[data-list="${id}"]`), fold = f => d.querySelector(`#side .fhead[data-folder="${f}"]`);
  d.querySelector('[data-act="side"]').click();
  check(await until(() => d.querySelector('#side.open') && row(L3) && fold('Admin')), 'touch: the drawer with the lists and folders');
  // a list row: held, over another list, Esc = nothing moves
  { const r = row(L3); tc(w, r, 'touchstart', 40, 20); await until(() => d.querySelector('.side-ghost'), 20);
    under = row(L1); tc(w, r, 'touchmove', 40, 60); await sleep(60);
    check(row(L1).classList.contains('dropbefore'), 'list row: the mark before the other list');
    esc(w); await sleep(60);
    check(!d.querySelector('.side-ghost') && !d.querySelector('#side .dropbefore, #side .dropafter') && !row(L3).classList.contains('dragging'), 'list row: Esc cancels (ghost and marks gone)');
    tc(w, r, 'touchend', 40, 60); under = null; await sleep(300);
    check((await order()).join() === O0.join(), 'list row: after Esc nothing moved'); }
  // a second finger cancels
  { const r = row(L3); tc(w, r, 'touchstart', 40, 20); await until(() => d.querySelector('.side-ghost'), 20);
    under = row(L1); tc(w, r, 'touchmove', 40, 60); await sleep(60);
    tc(w, r, 'touchstart', 40, 60, 2); await sleep(60);
    check(!d.querySelector('.side-ghost'), 'list row: a second finger cancels the drag');
    tc(w, r, 'touchend', 40, 60); under = null; await sleep(300);
    check((await order()).join() === O0.join(), 'list row: after the second finger nothing moved'); }
  // held, before the first list, let go
  { const r = row(L3); tc(w, r, 'touchstart', 40, 20); await until(() => d.querySelector('.side-ghost'), 20);
    under = row(L1); const mv2 = tc(w, r, 'touchmove', 40, 60); await sleep(60);
    check(mv2.defaultPrevented, 'list row: the drawer does not scroll under the drag');
    const te = tc(w, r, 'touchend', 40, 60); under = null;
    check(te.defaultPrevented && !d.querySelector('.side-ghost'), 'list row: let go, no click after the hold, ghost gone'); }
  check(await until(async () => { const o = await order(); return o.indexOf(L3) < o.indexOf(L1); }), 'list row: Car before Home (server)');
  // the tree: a folder held, Esc cancels; then Hobby before Admin
  await sleep(300);
  const layF = () => { box(fold('Admin'), 0, 50, 300, 40); };
  layF();
  { const h = fold('Hobby'); tc(w, h, 'touchstart', 40, 20); await until(() => h.classList.contains('dragging'), 20);
    under = fold('Admin'); tc(w, h, 'touchmove', 40, 52);
    check(fold('Admin').classList.contains('sbbdbef'), 'tree: the mark on the other folder');
    esc(w);
    check(!fold('Admin').classList.contains('sbbdbef') && !h.classList.contains('dragging'), 'tree: Esc cancels (marks gone)');
    tc(w, h, 'touchend', 40, 52); under = null; await sleep(300);
    check((await folders())[0] === 'Admin', 'tree: after Esc the folders as before'); }
  layF();
  { const h = fold('Hobby'); tc(w, h, 'touchstart', 40, 20); await until(() => h.classList.contains('dragging'), 20);
    under = fold('Admin'); tc(w, h, 'touchmove', 40, 52); const te = tc(w, h, 'touchend', 40, 52); under = null;
    check(te.defaultPrevented, 'tree: let go after the hold, no click'); }
  check(await until(async () => (await folders())[0] === 'Hobby'), 'tree: the held folder dragged before the other = sorted');
  // held without moving = the folder's menu
  await until(() => fold('Admin'));
  { const h = fold('Admin'); tc(w, h, 'touchstart', 40, 20); await until(() => h.classList.contains('dragging'), 20); tc(w, h, 'touchend', 40, 20);
    check(await until(() => items(d).length, 20), 'tree: held without moving = the folder\'s menu ' + items(d).join('|')); closeMenus(w); }
  w.close();

  // ================================================================ the favourite tiles (#4966)
  await call('PATCH', '/api/settings', {fav_items: ['v:today', 'v:tomorrow', 'v:inbox']});
  const favs = async () => JSON.parse((await call('GET', '/api/state')).settings?.fav_items || '[]');
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  const tile = k => d.querySelector(`#kbar .fv2bar [data-fv2="${k}"]`);
  check(await until(() => tile('v:today') && tile('v:tomorrow') && tile('v:inbox')), 'tiles: the bar shows three tiles');
  w.eval(`(() => {
    const gb = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function () {
      const r = (l, t, w, h) => ({left: l, top: t, width: w, height: h, right: l + w, bottom: t + h, x: l, y: t});
      if (this.matches?.('#kbar .fv2bar')) return r(100, 0, 500, 40);
      if (this.matches?.('#kbar .fv2bar [data-fv2]')) { const i = [...this.parentNode.children].indexOf(this); return r(104 + i * 34, 5, 30, 30); }
      return gb.call(this);
    };
    document.elementFromPoint = (x, y) => y < 0 || y > 40 ? document.body : [...document.querySelectorAll('#kbar .fv2bar [data-fv2]')].find(t => { const b = t.getBoundingClientRect(); return x >= b.left && x <= b.right; }) || document.querySelector('#kbar .fv2bar');
    return 1; })()`);
  // held, dragged onto the right half of the last tile, Esc: nothing moves
  { const t = tile('v:today'); tc(w, t, 'touchstart', 120, 20);
    check(await until(() => w.eval('FV2.drag') === 'v:today', 20), 'tiles: the hold lifts the tile');
    tc(w, t, 'touchmove', 104 + 2 * 34 + 25, 20);
    check(tile('v:inbox').classList.contains('fv2-after'), 'tiles: the mark behind the last tile');
    esc(w);
    check(!w.eval('FV2.drag') && !d.querySelector('#kbar .fv2-after, #kbar .fv2-before, #kbar .dragging'), 'tiles: Esc cancels (the tile goes back)');
    tc(w, t, 'touchend', 104 + 2 * 34 + 25, 20); await sleep(300);
    check((await favs()).join() === 'v:today,v:tomorrow,v:inbox', 'tiles: after Esc the order as before ' + (await favs())); }
  // held, dragged behind the last tile, let go
  { const t = tile('v:today'); tc(w, t, 'touchstart', 120, 20); await until(() => w.eval('FV2.drag') === 'v:today', 20);
    tc(w, t, 'touchmove', 104 + 2 * 34 + 25, 20); tc(w, t, 'touchend', 104 + 2 * 34 + 25, 20); }
  check(await until(async () => (await favs()).join() === 'v:tomorrow,v:inbox,v:today'), 'tiles: the held tile dragged behind the last = the last ' + (await favs()));
  w.close();

  check(!errs.length, 'no script errors: ' + errs.join(' | ').slice(0, 300));
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
