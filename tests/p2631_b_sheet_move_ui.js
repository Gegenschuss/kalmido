// 2.631.0 part B UI test (#4620): moving rows and columns of a table by their heads, own container (start.sh), Firefox
// kalmido-suite: fresh
// with a touch screen (real touch actions over WebDriver BiDi) and with a mouse. Invented names only.
// - touch: a long press on a row's number lifts it (ghost + drop line while the finger is down), dragged below row 4 it lands
//   there (order checked over the API); the summed rows' total keeps its range (=SUM(A1:A4) stays 10), a single reference
//   follows its cell (=A1*10 is =A4*10); one Undo step brings the order back; a long press in a cell still shows its details
// - the mouse: dragging a column's head moves the column (no menu opens after the drop), the Undo; two chosen rows move together;
//   the row menu's "Move down" (no "Move up" on the first row); in a filtered view a hint instead of a move
// - only reading (bob, a read share): no drag, no move entries in the menu; he sees alice's new order live (no reload)
// - a person without an organisation (freelancer-matrix: sheets): a finger drags a column of her own table
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2631BU_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const firefox = require('./ff')({tag: 'p2631_b_ui', check, shots: 'P2631BU_SHOTS'});
const byPos = xs => (xs || []).slice().sort((a, b) => a.pos - b.pos).map(x => x.id);

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Nordwind', lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,sheets'});
  const ORG = (await call(CA, 'GET', '/api/state')).me.workspaces[0].id;
  const bo = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [ORG]});
  check(bo.http < 300, 'bob ' + bo.http);
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,sheets'});
  const table = async (ck, title, cells) => {
    const t = await call(ck, 'POST', '/api/sheets', {title});
    check(t.http === 201, 'a table ' + title + ' ' + t.http);
    for (const c of (await call(ck, 'GET', `/api/sheets/${t.id}`)).columns) await call(ck, 'PATCH', `/api/sheets/${t.id}/columns/${c.id}`, {kind: 'number'});
    await call(ck, 'PUT', `/api/sheets/${t.id}/cells`, {cells: cells.map(([cell, raw]) => ({cell, raw}))});
    return t.id;
  };
  const S = await table(CA, 'Moving', [['A1', '1'], ['A2', '2'], ['A3', '3'], ['A4', '4'], ['A5', '=SUM(A1:A4)'], ['B1', '=A1*10'], ['C1', '7'], ['C2', '8']]);
  const RO = await table(CA, 'Read only', [['A1', '1'], ['A2', '2'], ['A3', '3']]);
  check((await call(CA, 'POST', `/api/sheets/${RO}/shares`, {user_id: bo.id, role: 'read'})).http === 201, 'shared with bob to read');
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, 'the freelancer ' + fr.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,sheets'});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const SF = await table(CF, 'Frida sheet', [['A1', '1'], ['B1', '2'], ['C1', '=A1+B1']]);
  const st = async (ck, id) => { const j = await call(ck, 'GET', `/api/sheets/${id}`); return {rows: byPos(j.rows), cols: byPos(j.columns), cells: j.cells || []}; };
  const cellOf = (s, addr) => s.cells.find(c => c.addr === addr) || {};
  const A0 = await st(CA, S), R = A0.rows, C = A0.cols;

  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const open = async ({ev, nav, until}, u, id) => {
    await nav(B + 'static/icon.svg'); check(await signIn(ev, u) === 200, u + ': login');
    await nav(B + '#sheets/' + id);
    check(await until(`typeof SHV !== 'undefined' && SHV.sh?.id === ${id} && !!document.querySelector('#shv-scroll td.shvc') && typeof shmv_go === 'function'`), u + ': the table is open, sheetmove.js loaded');
    await ev(`(() => { const s = document.getElementById('shv-scroll'); s.scrollTop = 0; s.scrollLeft = 0; scrollTo(0, 0); return 1; })()`);
  };
  // a head's point (viewport): kind row|col, id, where: mid | low (lower part) | right (right part)
  const head = (ev, kind, id, where = 'mid') => ev(`(() => { const el = document.querySelector(${JSON.stringify(kind === 'row' ? '#shv-scroll tr[data-id="ID"] > th.shvrh' : '#shv-scroll thead th.shvch[data-c="ID"]')}.replace('ID', ${id}));
    if (!el) return null; const r = el.getBoundingClientRect();
    const x = Math.round('${where}' === 'right' ? r.right - 6 : r.left + r.width / 2), y = Math.round('${where}' === 'low' ? r.bottom - 4 : r.top + r.height / 2), h = document.elementFromPoint(x, y);
    return {x, y, hit: !!h && el.contains(h)}; })()`);
  const cellAt = (ev, rid, cid) => ev(`(() => { const r = document.getElementById('shv-c-${rid}-${cid}').getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
  // down on a, hold (ms), drawn to b in steps, still down; lift() ends it
  const press = ({cmd, ctx}, a, b, kind, hold) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: kind}, actions: [
    {type: 'pointerMove', x: a.x, y: a.y}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: hold},
    {type: 'pointerMove', x: Math.round(a.x + (b.x - a.x) / 4), y: Math.round(a.y + (b.y - a.y) / 4), duration: 120},
    {type: 'pointerMove', x: Math.round((a.x + b.x) / 2), y: Math.round((a.y + b.y) / 2), duration: 120}, {type: 'pointerMove', x: b.x, y: b.y, duration: 160}]}]});
  const lift = async ({cmd, ctx}, kind) => { await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: kind}, actions: [{type: 'pointerUp', button: 0}]}]}); await cmd('input.releaseActions', {context: ctx}); };
  const tap = async ({cmd, ctx}, p, kind, hold = 0) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: kind}, actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, ...(hold ? [{type: 'pause', duration: hold}] : []), {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const waitApi = async (until, ck, id, fn) => until(async () => fn(await st(ck, id)), {timeout: 15000});

  // ---- touch (a tablet in landscape)
  await firefox(async o => {
    const {cmd, ev, ctx, until, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1180, height: 820}});
    await open(o, 'alice', S);
    check(await ev(`matchMedia('(hover: none)').matches && isTouch()`), 'touch: the browser is a touch screen');
    const a = await head(ev, 'row', R[0]), b = await head(ev, 'row', R[3], 'low');
    check(a?.hit && b?.hit, 'touch: the heads of rows 1 and 4 are on screen ' + JSON.stringify([a, b]));
    await press(o, a, b, 'touch', 650);
    const mid = await ev(`({ghost: !!document.querySelector('.shmv-ghost'), line: !!document.querySelector('.shmv-line:not([hidden])'), lifted: !!document.querySelector('#shv-scroll th.shvrh.drag'), pale: (document.getElementById('shmv-st')?.textContent || '').includes('${R[0]}')})`);
    check(mid.ghost && mid.line && mid.lifted && mid.pale, 'touch: while the finger is down: ghost, drop line, the row lifted and pale ' + JSON.stringify(mid));
    await shot('p2631b-touch-drag.png');
    await lift(o, 'touch');
    const want = [R[1], R[2], R[3], R[0], ...R.slice(4)];
    check(await waitApi(until, CA, S, s => same(s.rows, want)), 'touch: row 1 is below row 4 now (API) ' + JSON.stringify((await st(CA, S)).rows));
    let s = await st(CA, S);
    check(cellOf(s, 'A5').raw === '=SUM(A1:A4)' && cellOf(s, 'A5').value === 10, 'touch: the total keeps its rows: =SUM(A1:A4) = 10 ' + JSON.stringify(cellOf(s, 'A5')));
    check(cellOf(s, 'B4').raw === '=A4*10' && cellOf(s, 'B4').value === 10, 'touch: =A1*10 followed its cell: =A4*10 ' + JSON.stringify(cellOf(s, 'B4')));
    check(await ev(`!document.querySelector('.shmv-ghost') && !document.querySelector('.shmv-line') && !document.querySelector('#pop:not(.hidden) [role="menuitem"]')`), 'touch: after the drop no ghost, no line, no menu');
    check(await until(`[...document.querySelectorAll('#shv-scroll tbody tr[data-id]')].map(x => +x.dataset.id).slice(0, 4).join() === '${want.slice(0, 4).join()}'`), 'touch: the grid shows the new order');
    await ev(`(async () => { await histIdle(); await histStep('undo'); return 1; })()`);
    check(await waitApi(until, CA, S, s => same(s.rows, R)), 'touch: one Undo step: the old order');
    s = await st(CA, S);
    check(cellOf(s, 'A5').raw === '=SUM(A1:A4)' && cellOf(s, 'B1').raw === '=A1*10', 'touch: after the Undo the formulas as before ' + JSON.stringify([cellOf(s, 'A5').raw, cellOf(s, 'B1').raw]));
    // a swipe on the heads without the hold scrolls / does nothing, and a long press in a cell shows its details as before
    await press(o, await head(ev, 'row', R[0]), await head(ev, 'row', R[2]), 'touch', 0); await lift(o, 'touch');
    await sleep(400);
    check(same((await st(CA, S)).rows, R), 'touch: a swipe without the hold moves nothing');
    await tap(o, await cellAt(ev, R[1], C[0]), 'touch', 800);
    check(await until(`!!document.querySelector('.shvtip')`), 'touch: a long press in a cell still shows its details');
    check(same((await st(CA, S)).rows, R), 'touch: the long press in a cell moved nothing');
    await ev(`(() => { closePop(); return 1; })()`);
  }, true);

  // ---- the mouse
  await firefox(async o => {
    const {cmd, ev, ctx, until, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await open(o, 'alice', S);
    check(await ev(`!isTouch()`), 'mouse: no touch screen');
    // column A to the right of column B
    const a = await head(ev, 'col', C[0]), b = await head(ev, 'col', C[1], 'right');
    await press(o, a, b, 'mouse', 0);
    check(await ev(`!!document.querySelector('.shmv-line:not([hidden])') && !!document.querySelector('.shmv-ghost')`), 'mouse: drop line and ghost while dragging');
    await lift(o, 'mouse');
    const wc = [C[1], C[0], ...C.slice(2)];
    check(await waitApi(until, CA, S, s => same(s.cols, wc)), 'mouse: column A is right of B now (API) ' + JSON.stringify((await st(CA, S)).cols));
    await sleep(300);
    check(await ev(`!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`), 'mouse: no column menu opened after the drag');
    check(await until(`(document.getElementById('toast')?.textContent || '').includes('1 column moved')`), 'mouse: the toast says so (with its Undo)');
    await ev(`(async () => { await histIdle(); await histStep('undo'); return 1; })()`);
    check(await waitApi(until, CA, S, s => same(s.cols, C)), 'mouse: Undo: the old column order');
    // two chosen rows (A1:A2) dragged by row 1's number below row 3: both move
    await until(`SHV.sh?.columns?.[0]?.id === ${C[0]}`);
    await ev(`(() => { shvSelect(${R[0]}, ${C[0]}); shvSelect(${R[1]}, ${C[0]}, true); return 1; })()`);
    await press(o, await head(ev, 'row', R[0]), await head(ev, 'row', R[2], 'low'), 'mouse', 0); await lift(o, 'mouse');
    const w2 = [R[2], R[0], R[1], ...R.slice(3)];
    check(await waitApi(until, CA, S, s => same(s.rows, w2)), 'mouse: the two chosen rows moved together ' + JSON.stringify((await st(CA, S)).rows));
    check(await until(`(document.getElementById('toast')?.textContent || '').includes('2 rows moved')`), 'mouse: "2 rows moved"');
    await ev(`(async () => { await histIdle(); await histStep('undo'); return 1; })()`);
    check(await waitApi(until, CA, S, s => same(s.rows, R)), 'mouse: Undo of the two rows');
    // the row menu: "Move down" (the first row has no "Move up")
    await until(`SHV.sh?.rows?.[0]?.id === ${R[0]}`);
    await ev(`(() => { shvSelect(${R[2]}, ${C[2]}); return 1; })()`);
    await tap(o, await head(ev, 'row', R[0]), 'mouse');
    check(await until(`!!document.querySelector('#pop:not(.hidden) [data-act="shmv-down"]')`), 'mouse: the row menu has "Move down"');
    check(await ev(`!document.querySelector('#pop:not(.hidden) [data-act="shmv-up"]')`), 'mouse: the first row has no "Move up"');
    await shot('p2631b-mouse-menu.png');
    await ev(`(() => { document.querySelector('#pop:not(.hidden) [data-act="shmv-down"]').click(); return 1; })()`);
    check(await waitApi(until, CA, S, s => same(s.rows, [R[1], R[0], ...R.slice(2)])), 'mouse: "Move down" moved row 1 one down');
    await ev(`(async () => { await histIdle(); await histStep('undo'); return 1; })()`);
    check(await waitApi(until, CA, S, s => same(s.rows, R)), 'mouse: Undo of "Move down"');
    // a filtered view: a hint, no move
    await until(`SHV.sh?.rows?.[0]?.id === ${R[0]}`);
    await ev(`(() => { SHV.filt[${S}] = {${C[2]}: {min: 1}}; shvRender(); return 1; })()`);
    await until(`!!document.querySelector('[data-shv="unfilter"]')`);
    const fa = await head(ev, 'row', R[0]), fb = await head(ev, 'row', R[1], 'low');
    await press(o, fa, fb, 'mouse', 0); await lift(o, 'mouse');
    check(await until(`(document.getElementById('toast')?.textContent || '').includes('Reset the filters to move rows')`), 'mouse: filtered: the hint instead of a move');
    await sleep(400);
    check(same((await st(CA, S)).rows, R), 'mouse: filtered: nothing moved');
    await ev(`(() => { delete SHV.filt[${S}]; shvRender(); return 1; })()`);
  }, false);

  // ---- only reading (bob): no drag, no move entries; alice's move shows live
  await firefox(async o => {
    const {cmd, ev, ctx, until} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await open(o, 'bob', RO);
    check(await ev(`SHV.sh.can_write === false`), 'reader: the table is read only');
    const B0 = await st(CB, RO);
    await press(o, await head(ev, 'row', B0.rows[0]), await head(ev, 'row', B0.rows[2], 'low'), 'mouse', 0); await lift(o, 'mouse');
    check(await ev(`!document.querySelector('.shmv-line') && !document.querySelector('.shmv-ghost')`), 'reader: no drag starts');
    await sleep(400);
    check(same((await st(CA, RO)).rows, B0.rows), 'reader: nothing moved');
    await tap(o, await head(ev, 'col', B0.cols[0]), 'mouse');
    check(await until(`!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`), 'reader: the column menu opens (filter)');
    check(await ev(`!document.querySelector('#pop:not(.hidden) [data-act^="shmv-"]')`), 'reader: no move entries in the menu');
    await ev(`(() => { closePop(); return 1; })()`);
    // alice moves row 3 to the top: bob's grid follows by itself
    const nw = [B0.rows[2], B0.rows[0], B0.rows[1], ...B0.rows.slice(3)];
    const r = await call(CA, 'POST', `/api/sheets/${RO}/rows/order`, {ids: nw, prev: B0.rows, moved: [B0.rows[2]]});
    check(r.http === 200, 'alice moves a row ' + r.http);
    check(await until(`[...document.querySelectorAll('#shv-scroll tbody tr[data-id]')].map(x => +x.dataset.id).slice(0, 3).join() === '${nw.slice(0, 3).join()}'`, {timeout: 45000}), 'reader: the new order shows live, without a reload');
  }, false);

  // ---- the freelancer (touch): a column of her own table
  await firefox(async o => {
    const {cmd, ev, ctx, until} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1180, height: 820}});
    await open(o, 'frida', SF);
    const F0 = await st(CF, SF);
    await press(o, await head(ev, 'col', F0.cols[0]), await head(ev, 'col', F0.cols[1], 'right'), 'touch', 650); await lift(o, 'touch');
    check(await waitApi(until, CF, SF, s => same(s.cols, [F0.cols[1], F0.cols[0], ...F0.cols.slice(2)])), 'freelancer: a finger moved column A right of B ' + JSON.stringify((await st(CF, SF)).cols));
    const s = await st(CF, SF);
    check(cellOf(s, 'C1').raw === '=B1+A1' && cellOf(s, 'C1').value === 3, 'freelancer: the formula follows its cells ' + JSON.stringify(cellOf(s, 'C1')));
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
