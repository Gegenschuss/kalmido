// kalmido-suite: fresh
// 2.623.0 part E UI tests (jsdom), fresh DB (#4621): what the mouse drags, the finger drags too, by drag.js. With real touch
// events (touchstart / touchmove / touchend, the touches as plain objects; jsdom has no Touch and no layout: the boxes and
// the element under the finger are given here):
// - the sheet tabs of a table (sheetbook.js): held, dragged onto another tab, let go = the same order as the mouse's drop;
//   a swipe without the hold moves nothing; held and let go without moving = the tap (the open tab's menu); no browser
//   drag on a touch screen, the mouse keeps it
// - the groups of My tasks by project (basket.js): held header dragged onto the first group = the top, as the mouse's grip;
//   a swipe moves nothing; held without moving = the order menu
// - sections (secdrag.js, already on drag.js): held header dragged above the first = the first, as the mouse; a swipe moves
//   nothing. The rows' order (rowd_attach) has its own test with the finger: tests/p2456_a_rowdrag_ui.js
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const HOLD = 450;  // above ROWD_HOLD (380) and the sections' 450 ms is waited for by state below
// a touch event: touches as plain objects (x, y)
const tc = (w, el, type, x, y) => {
  const e = new w.Event(type, {bubbles: true, cancelable: true}), t = [{identifier: 1, target: el, clientX: x, clientY: y}];
  Object.defineProperty(e, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : t});
  Object.defineProperty(e, 'changedTouches', {value: t});
  el.dispatchEvent(e); return e;
};
// a browser's click after a drag: swallowed by drg_noClick (otherwise it would be the next click of the test)
const after = w => w.document.body.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
// a box for jsdom (no layout)
const box = (el, left, top, width, height) => { el.getBoundingClientRect = () => ({left, top, width, height, right: left + width, bottom: top + height, x: left, y: top}); };
// an HTML5 drag event of the mouse with a small data store
const store = () => { const m = {}; return {setData(k, v) { m[k] = v; }, getData(k) { return m[k] || ''; }, get types() { return Object.keys(m); }, effectAllowed: '', dropEffect: ''}; };
const dev = (w, el, type, dt, x = 0, y = 0) => { const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: y}); Object.defineProperty(e, 'dataTransfer', {value: dt}); el.dispatchEvent(e); return e; };
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"], .menu-list button')];
const closeMenus = d => { d.dispatchEvent(new d.defaultView.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,sheets'});
  const st0 = await call('GET', '/api/state'), ME = st0.me, ORG = ME.workspaces[0].id;
  const TOUCH = {'(hover: none)': true, '(pointer: coarse)': true};

  // ================================================================ sheet tabs
  const SH = await call('POST', '/api/sheets', {title: 'Shoot plan', space: 'private'});
  for (let i = 0; i < 2; i++) await call('POST', `/api/sheets/${SH.id}/tabs`, {after_id: SH.id});
  const tabs = async () => (await call('GET', `/api/sheets/${SH.id}/tabs`)).tabs.map(t => t.id);
  const T0 = await until(async () => { const t = await tabs(); return t.length === 3 && t; });
  check(T0 && T0.length === 3, 'setup: a table with three sheets ' + T0);

  let w = await boot({user: 'alice', hash: 'sheets/' + SH.id, media: TOUCH}), d = w.document;
  const tabEls = () => [...d.querySelectorAll('#view .shbtab')];
  check(await until(() => tabEls().length === 3), 'touch: the bar shows three tabs');
  check(tabEls().every(t => !t.hasAttribute('draggable')), 'touch: no browser drag on the tabs (the hold is the app\'s)');
  const layTabs = () => { tabEls().forEach((t, i) => box(t, 100 * i, 500, 100, 40)); const at = (x, y) => (y >= 500 && y < 540 && tabEls()[Math.floor(x / 100)]) || d.body; d.elementFromPoint = at; };
  // a swipe without the hold: nothing moves, no mark
  layTabs();
  { const t = tabEls()[2]; tc(w, t, 'touchstart', 250, 520); await sleep(40); tc(w, t, 'touchmove', 230, 520); tc(w, t, 'touchmove', 40, 520); tc(w, t, 'touchend', 40, 520);
    await sleep(300);
    check((await tabs()).join() === T0.join() && !d.querySelector('.shbtab.drag, .ghost-drag'), 'touch: a quick swipe over the tabs scrolls, it moves no sheet'); }
  // held, dragged onto the first tab, let go
  { const t = tabEls()[2]; tc(w, t, 'touchstart', 250, 520);
    check(await until(() => t.classList.contains('drag'), 20), 'touch: the hold lifts the tab');
    tc(w, t, 'touchmove', 200, 520); await sleep(40); tc(w, t, 'touchmove', 40, 520); await sleep(60);
    check(!!d.querySelector('.ghost-drag'), 'touch: a copy of the tab follows the finger');
    tc(w, t, 'touchend', 40, 520); after(w); }
  const T1 = [T0[2], T0[0], T0[1]];
  check(await until(async () => (await tabs()).join() === T1.join()), 'touch: the held tab dragged onto the first = the first ' + (await tabs()));
  check(await until(() => !d.querySelector('.shbtab.drag, .ghost-drag')), 'touch: nothing of the drag stays behind');
  // Undo as after the mouse's move (one step)
  await until(() => tabEls().length === 3 && +tabEls()[0].dataset.id === T0[2]);
  check(await until(() => w.eval('HIST.undo.length') > 0), 'touch: the move is an Undo step');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await tabs()).join() === T0.join()), 'touch: Undo puts the sheet back ' + (await tabs()));
  // held and let go without moving = the tap: on the open tab its menu
  await until(() => tabEls().length === 3 && +tabEls()[0].dataset.id === T0[0]);
  layTabs();
  { const t = d.querySelector('#view .shbtab.on'); const x = 100 * tabEls().indexOf(t) + 50;
    tc(w, t, 'touchstart', x, 520); await until(() => t.classList.contains('drag'), 20); tc(w, t, 'touchend', x, 520);
    check(await until(() => items(d).some(b => /Rename/.test(b.textContent)), 20), 'touch: held without moving = the tap (the open sheet\'s menu)');
    check((await tabs()).join() === T0.join(), 'touch: held without moving moves nothing'); closeMenus(d); }
  w.close();

  // the mouse: the same move by the browser's drag
  w = await boot({user: 'alice', hash: 'sheets/' + SH.id}); d = w.document;
  check(await until(() => tabEls().length === 3), 'mouse: three tabs');
  check(tabEls().every(t => t.getAttribute('draggable') === 'true'), 'mouse: the tabs keep the browser\'s drag');
  { const dt = store(); dev(w, tabEls()[2], 'dragstart', dt); dev(w, tabEls()[0], 'dragover', dt); dev(w, tabEls()[0], 'drop', dt); dev(w, tabEls()[2], 'dragend', dt); }
  check(await until(async () => (await tabs()).join() === T1.join()), 'mouse: the same order as the finger ' + (await tabs()));
  w.close();

  // ================================================================ groups of My tasks by project
  const L = {};
  for (const n of ['Household', 'Team', 'Garden']) L[n] = (await call('POST', '/api/lists', {name: n, org_id: ORG})).id;
  for (const n of Object.keys(L)) await call('POST', '/api/tasks', {title: 'Mine in ' + n, list_id: L[n], assignee_id: ME.id});
  await call('PATCH', '/api/settings', {mine_view: 'lists'});
  const order = async () => JSON.parse((await call('GET', '/api/state')).settings.group_order || '{}');
  w = await boot({user: 'alice', hash: 'assigned', media: TOUCH}); d = w.document;
  const groups = () => [...d.querySelectorAll('#view .group[data-kbg]')];
  check(await until(() => groups().length >= 3), 'touch: My tasks shows the project groups ' + groups().length);
  const layGroups = () => {
    groups().forEach((g, i) => { box(g, 0, 200 * i, 400, 200); const h = g.querySelector(':scope > .ghead'); if (h) box(h, 0, 200 * i, 400, 40); });
    d.elementFromPoint = (x, y) => { const g = groups()[Math.floor(y / 200)]; return g ? g.querySelector(':scope > .ghead') || g : d.body; };
  };
  const ids0 = groups().map(g => g.dataset.kbg), last = ids0[ids0.length - 1];
  layGroups();
  // a swipe without the hold
  { const h = groups().at(-1).querySelector(':scope > .ghead'), y = 200 * (groups().length - 1) + 20;
    tc(w, h, 'touchstart', 100, y); await sleep(40); tc(w, h, 'touchmove', 100, y - 30); tc(w, h, 'touchmove', 100, 20); tc(w, h, 'touchend', 100, 20); await sleep(300);
    check(groups().map(g => g.dataset.kbg).join() === ids0.join() && !d.querySelector('#view .kbdragging, .ghost-drag'), 'touch: a quick swipe over a group\'s header scrolls, it moves no group'); }
  // held, dragged onto the first group, let go
  { const h = groups().at(-1).querySelector(':scope > .ghead'), y = 200 * (groups().length - 1) + 20;
    tc(w, h, 'touchstart', 100, y);
    check(await until(() => groups().at(-1).classList.contains('kbdragging'), 20), 'touch: the hold lifts the group');
    tc(w, h, 'touchmove', 100, y - 40); await sleep(40); tc(w, h, 'touchmove', 100, 20); await sleep(60);
    check(groups()[0].classList.contains('kbdrop'), 'touch: the first group is marked as the place');
    tc(w, h, 'touchend', 100, 20); after(w); }
  check(await until(() => groups()[0]?.dataset.kbg === last), 'touch: the held group dragged onto the first = the top ' + groups().map(g => g.dataset.kbg));
  const go1 = await until(async () => { const o = await order(); return Object.keys(o).length && o; });
  check(!!go1, 'touch: the order is stored like the mouse\'s ' + JSON.stringify(go1));
  check(!d.querySelector('#view .kbdrop, #view .kbdragging, .ghost-drag'), 'touch: nothing of the drag stays behind');
  // held without moving = the order menu, nothing moves
  layGroups();
  { const now = groups().map(g => g.dataset.kbg).join(), h = groups()[1].querySelector(':scope > .ghead');
    tc(w, h, 'touchstart', 100, 220); await until(() => groups()[1].classList.contains('kbdragging'), 20); tc(w, h, 'touchend', 100, 220);
    check(await until(() => items(d).some(b => /Change position|To the top/.test(b.textContent)), 20), 'touch: held without moving = the order menu ' + items(d).map(b => b.textContent.trim()).join('|'));
    check(groups().map(g => g.dataset.kbg).join() === now, 'touch: held without moving moves nothing'); closeMenus(d); }
  w.close();

  // the mouse: the same move by the grip (the reset first, then the last group onto the first)
  await call('PATCH', '/api/settings', {group_order: '{}'});
  w = await boot({user: 'alice', hash: 'assigned'}); d = w.document;
  check(await until(() => groups().length >= 3 && groups().map(g => g.dataset.kbg).join() === ids0.join()), 'mouse: the order as at the start');
  { const dt = store(); dev(w, groups().at(-1).querySelector('.kbgrip'), 'dragstart', dt); dev(w, groups()[0].querySelector('.ghead'), 'dragover', dt); dev(w, groups()[0].querySelector('.ghead'), 'drop', dt); }
  check(await until(() => groups()[0]?.dataset.kbg === last), 'mouse: the same top group as the finger ' + groups().map(g => g.dataset.kbg));
  check(await until(async () => JSON.stringify(await order()) === JSON.stringify(go1)), 'mouse: the same stored order as the finger');
  w.close();

  // ================================================================ sections
  const P = (await call('POST', '/api/lists', {name: 'Shoot', org_id: ORG, kind: 'project'})).id;
  const SEC = [];
  for (const n of ['Alpha', 'Beta', 'Gamma']) SEC.push((await call('POST', '/api/sections', {list_id: P, name: n})).id);
  for (const [i, s] of SEC.entries()) await call('POST', '/api/tasks', {title: 'Task ' + i, list_id: P, section_id: s});
  const secs = async () => (await call('GET', '/api/state')).sections.filter(s => s.list_id === P).sort((a, b) => (a.sort ?? 0) - (b.sort ?? 0) || a.id - b.id).map(s => s.id);
  check((await secs()).join() === SEC.join(), 'setup: three sections ' + (await secs()));
  w = await boot({user: 'alice', hash: 'l/' + P, media: TOUCH}); d = w.document;
  const heads = () => [...d.querySelectorAll('#view .ghead[data-section]')].filter(h => SEC.includes(+h.dataset.section));
  check(await until(() => heads().length === 3), 'touch: the list shows three sections');
  const laySecs = () => {
    heads().forEach((h, i) => { const g = h.closest('.group') || h; box(g, 0, 100 + 150 * i, 400, 150); box(h, 0, 100 + 150 * i, 400, 40); });
    d.elementFromPoint = (x, y) => heads()[Math.floor((y - 100) / 150)] || d.body;
  };
  laySecs();
  { const h = heads()[2]; tc(w, h, 'touchstart', 100, 420); await sleep(40); tc(w, h, 'touchmove', 100, 380); tc(w, h, 'touchmove', 100, 110); tc(w, h, 'touchend', 100, 110); await sleep(300);
    check((await secs()).join() === SEC.join() && !d.querySelector('.sb-secghost'), 'touch: a quick swipe over a section header scrolls, it moves no section'); }
  { const h = heads()[2]; tc(w, h, 'touchstart', 100, 420);
    check(await until(() => !!d.querySelector('.sb-secghost'), 20), 'touch: the hold lifts the section');
    for (let i = 1; i <= 5; i++) { tc(w, h, 'touchmove', 100, 420 - (420 - 105) * i / 5); await sleep(40); }
    tc(w, h, 'touchend', 100, 105); after(w); }
  const S1 = [SEC[2], SEC[0], SEC[1]];
  check(await until(async () => (await secs()).join() === S1.join()), 'touch: the held section dragged above the first = the first ' + (await secs()));
  check(await until(() => !d.querySelector('.sb-secghost, #view .sb-secfold')), 'touch: nothing of the drag stays behind');
  w.close();
  // the mouse: the same move (back to the start first, then the browser's drag of the last section's handle above the first)
  await call('POST', `/api/lists/${P}/sections/order`, {ids: SEC});
  check(await until(async () => (await secs()).join() === SEC.join()), 'mouse: the sections as at the start');
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  check(await until(() => heads().length === 3 && heads()[2].querySelector('[data-sdrag]')), 'mouse: the sections have their handle');
  laySecs();
  { const dt = store(); dev(w, heads()[2].querySelector('[data-sdrag]'), 'dragstart', dt); await sleep(40);
    dev(w, heads()[0], 'dragover', dt, 100, 105); dev(w, heads()[0], 'drop', dt, 100, 105); }
  check(await until(async () => (await secs()).join() === S1.join()), 'mouse: the same section order as the finger ' + (await secs()));
  w.close();

  check(!errs.length, 'no script errors: ' + errs.join(' | ').slice(0, 300));
  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
