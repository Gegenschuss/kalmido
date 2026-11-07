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
const TC = require('./testclock');
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

  // ================================================================ 2.633.0: the office (#4963 #4964 #4965), as a person WITHOUT an
  // organisation (freelancer-matrix: office; the own personal office): a receipt onto a booking, a document onto a folder of the panel,
  // a pipeline card into another column. Held, dragged, let go = the same action as the mouse's drop; a swipe without the hold does nothing
  await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients', workspace: 'private'}, CF);
  const location_ = w => w.location.hash;
  const hold1 = async (w, el, x0, y0, x1, y1, what) => {  // the finger: down, the hold, a few moves, up
    tc(w, el, 'touchstart', x0, y0);
    check(await until(() => el.classList.contains('dragging'), 30), what + ': the hold lifts it');
    for (let i = 1; i <= 5; i++) { tc(w, el, 'touchmove', x0 + (x1 - x0) * i / 5, y0 + (y1 - y0) * i / 5); await sleep(40); }
    tc(w, el, 'touchend', x1, y1); after(w);
  };
  const swipe = async (w, el, x0, y0, x1, y1) => { tc(w, el, 'touchstart', x0, y0); await sleep(40); tc(w, el, 'touchmove', x0 + (x1 - x0) / 2, y0 + (y1 - y0) / 2); tc(w, el, 'touchmove', x1, y1); tc(w, el, 'touchend', x1, y1); await sleep(300); };

  // ---- #4965 the pipeline
  const DEAL = (await call('POST', '/api/office/deals', {title: 'Imagefilm', value: 1000, stage: 'inquiry'}, CF)).id;
  const stageOf = async () => ((await call('GET', '/api/office/deals', null, CF)).items || []).find(x => x.id === DEAL)?.stage;
  check(DEAL && await stageOf() === 'inquiry', 'setup: a deal in the stage Enquiry (without an organisation)');
  w = await boot({user: 'frida', hash: 'office/pipeline', media: TOUCH}); d = w.document;
  const card = () => d.querySelector('[data-pipcol="inquiry"] .ppcard[data-id="' + DEAL + '"]');
  check(await until(() => card() && d.querySelector('[data-pipcol="won"]')), 'touch: the board shows the card and the column Order');
  check(!card().getAttribute('draggable') || card().getAttribute('draggable') === 'true', 'touch: the card keeps the mouse\'s drag');
  { const c = card(), won = d.querySelector('[data-pipcol="won"]'); box(c, 0, 100, 200, 60); box(won, 600, 80, 200, 300);
    d.elementFromPoint = (x, y) => x >= 600 && y >= 80 && y < 380 ? won : x < 200 && y >= 100 && y < 160 ? c : d.body;
    await swipe(w, c, 100, 130, 700, 140);
    check(await stageOf() === 'inquiry' && !d.querySelector('.ghost-drag'), 'touch: a quick swipe over the card moves nothing');
    await hold1(w, c, 100, 130, 700, 200, 'touch');
    check(await until(async () => (await stageOf()) === 'won'), 'touch: the held card dragged into Order = the stage Order (as the mouse) ' + (await stageOf()));
    check(await until(() => !d.querySelector('.ghost-drag, .pipcol.over, .ppcard.dragging')), 'touch: nothing of the drag stays behind'); }
  w.close();

  // ---- #4964 a document onto a folder of the panel
  const cl = await call('POST', '/api/clients', {name: 'Example Ltd'}, CF);
  const DOC = (await call('POST', '/api/office/docs', {kind: 'offer', client_id: cl.id, items: [{title: 'Day 1', qty: 1, rate: 100}]}, CF)).id;
  const FOL = (await call('POST', '/api/office/docs/tree/folders', {name: 'Client Alpha'}, CF)).folder?.id;
  const refOf = async () => ((await call('GET', `/api/files/refs/office_doc/${DOC}`, null, CF)).node || {}).parent_id || null;
  check(DOC && FOL && !(await refOf()), 'setup: a quotation and a folder, the quotation in no folder');
  w = await boot({user: 'frida', hash: 'office/offers', media: TOUCH}); d = w.document;
  const li = () => d.querySelector('#view .ofdli');
  const fnode = () => d.querySelector(`#side .sbbt[data-sbbid="f:offers:${FOL}"]`);
  await until(() => d.querySelector('#side .sbbt[data-sbbid="a:offers"]'));
  await until(() => { if (fnode()) return true; const a = d.querySelector('#side .sbbt[data-sbbid="a:offers"] [data-act="sbb-tree"]'); if (a && !a.dataset.open) a.click(); return false; }, 30);
  check(await until(() => li() && fnode()), 'touch: the list row and the folder of the panel are there: ' + [!!li(), !!fnode(), d.querySelectorAll('#side .sbbt').length, [...d.querySelectorAll('#side .sbbt[data-sbbns="oft"]')].map(e => e.dataset.sbbid).join(','), location_(w)].join(' / '));
  check(li() && li().hasAttribute('data-ofdmv') && !li().hasAttribute('draggable'), 'touch: the row has no browser drag (the hold is the app\'s)');
  { const l = li();
    d.elementFromPoint = (x, y) => { const f = fnode(); if (f) box(f, 0, 300, 200, 30); return f && x < 200 && y >= 300 && y < 330 ? f : x >= 300 && y >= 100 && y < 150 ? l : d.body; };
    box(l, 300, 100, 500, 50);
    await swipe(w, l, 400, 125, 100, 315);
    check(!(await refOf()) && !d.querySelector('.ghost-drag'), 'touch: a quick swipe over the row files nothing');
    await hold1(w, l, 400, 125, 100, 315, 'touch');
    check(await until(async () => (await refOf()) === FOL), 'touch: the held row dragged onto the folder = filed there (as the mouse) ' + (await refOf()));
    check(await until(() => !d.querySelector('.ghost-drag, #side .sbbdin, #view .ofdli.dragging')), 'touch: nothing of the drag stays behind');
    // 2.633.0 (#4964, review): held without moving = the row's menu ONCE, on letting go; the row's long press (ms_longPress, 500 ms,
    // pointer events as a real browser sends them beside the touch ones) must not open it as well while the finger still holds
    const l2 = li(); box(l2, 300, 100, 500, 50);
    const pe = new w.Event('pointerdown', {bubbles: true}); Object.assign(pe, {pointerType: 'touch', clientX: 400, clientY: 125}); l2.querySelector('.ofdrow').dispatchEvent(pe);
    tc(w, l2, 'touchstart', 400, 125);
    check(await until(() => l2.classList.contains('dragging'), 30), 'touch: held still lifts the row');
    await sleep(700);  // past the long press's 500 ms: a negative check (nothing may open), no state to wait for
    check(!items(d).length, 'touch: while the finger still holds, the long-press menu stays shut (the hold took the press)');
    l2.querySelector('.ofdrow').dispatchEvent(new w.Event('pointerup', {bubbles: true})); tc(w, l2, 'touchend', 400, 125);  // a browser sends pointerup before touchend
    check(await until(() => items(d).length, 20), 'touch: let go without moving = the row\'s menu ' + [l2.isConnected, l2.classList.contains('dragging'), w.eval('(OFD.list||[]).length'), w.eval('typeof ofdRowMenu'), !!d.querySelector('#pop'), (d.querySelector('#pop')||{}).className, d.querySelector('#view .ofdrow')?.dataset.id, d.querySelector('#view .ofdrow')?.dataset.arch].join(' / '));
    closeMenus(d); }
  w.close();

  // ---- #4963 a receipt onto a booking
  const day = n => { const x = new Date(TC.today() + 'T12:00:00'); x.setDate(x.getDate() - n); return x.toISOString().slice(0, 10); };
  const ntry = (amt, ref, dd, name) => `<Ntry><Amt Ccy="EUR">${amt}</Amt><CdtDbtInd>DBIT</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>${dd}</Dt></BookgDt><AcctSvcrRef>${ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>${name}</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>Buchung ${ref}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>`;
  const xml = `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Acct><Id><IBAN>DE02120300000000202051</IBAN></Id><Ccy>EUR</Ccy></Acct>${ntry('119.00', 'U-1', day(3), 'Software Beispiel GmbH')}</Stmt></BkToCstmrStmt></Document>`;
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Frida Film', street: 'Weg 3', zip: '10115', city: 'Berlin', country: 'DE'}}, CF);
  const imp = await call('POST', '/api/office/bank/import', {text: xml, filename: 'konto.xml'}, CF);
  check(imp.http === 201, 'setup: a booking imported ' + imp.http);
  const TX = ((await call('GET', '/api/office/bank/tx?state=all', null, CF)).items || []).find(t => t.purpose === 'Buchung U-1')?.id;
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob(['Beleg Software Beispiel 119,00'], {type: 'text/plain'}), 'beleg.txt');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CF}, body: fd})).json().catch(() => ({}));
  const RC = (up.ids || [])[0];
  check(RC && (await call('PATCH', `/api/docs/${RC}`, {amount: '119.00', date: day(3)}, CF)).http === 200 && (await call('PUT', `/api/docs/${RC}/receipt`, {keep: true}, CF)).http === 200, 'setup: a receipt of 119.00 without a booking');
  const matched = async () => ((await call('GET', '/api/office/bank/tx?state=matched', null, CF)).items || []).some(t => t.id === TX && t.match?.kind === 'receipt');
  w = await boot({user: 'frida', hash: 'office/bank/norc', media: TOUCH}); d = w.document;
  const rcEl = () => d.querySelector('.bnrdrag[data-bnr-rc]'), row = () => d.querySelector(`.bnkrow[data-bnr-drop="${TX}"]`);
  check(await until(() => rcEl() && row()), 'touch: the receipt column and the booking are there');
  { const r = rcEl(), b = row(); box(r, 900, 100, 250, 40); box(b, 100, 200, 700, 60);
    d.elementFromPoint = (x, y) => x >= 900 && y >= 100 && y < 140 ? r : x < 800 && y >= 200 && y < 260 ? b : d.body;
    await swipe(w, r, 1000, 120, 300, 230);
    check(!(await matched()) && !d.querySelector('.ghost-drag'), 'touch: a quick swipe over the receipt matches nothing');
    await hold1(w, r, 1000, 120, 300, 230, 'touch');
    check(await until(matched), 'touch: the held receipt dragged onto the booking = matched (as the mouse)');
    check(await until(() => !d.querySelector('.ghost-drag, .bnkrow.on, .bnrdrag.dragging')), 'touch: nothing of the drag stays behind'); }
  w.close();

  check(!errs.length, 'no script errors: ' + errs.join(' | ').slice(0, 300));
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
