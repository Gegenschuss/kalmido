// 2.89.0 part B UI test (#1916): the tables view (static/js/sheets.js), own container (start.sh): jsdom for the behaviour,
// Firefox for the real look. Invented names only.
// - the area "Tables" in the sidebar (switch "sheets"), the overview with its empty state, "New table" (one undo step)
// - the grid: keys like a spreadsheet (typing overwrites, Enter saves and goes down, arrows), a formula, the suggestions after
//   "=", the colour classes of the origin (own / formula / Kalmido / frozen), the panel "Comes from" / "Goes into", a cell name
// - a selection column made in the column dialog (options with palette colours, colour for the whole row), the cell's menu
// - sorting (saved, one undo step), filtering (view only), paste of a block, undo / redo of a cell
// - presence of another member, the agents' changes in the panel, a table attached to a list (list menu "Tables")
// - phone width: tap = choose, a second tap edits; a person without an organisation (dave) works in a private table
// - Firefox: desktop with dependency arrows, the option label's contrast in light and dark, the phone; screenshots with
//   P289B_SHOTS=<dir>
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p289_b_ui', check, shots: 'P289B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P289B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const FEAT = 'collab,comments,sheets';
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { try { if (await fn()) return true; } catch { /* not yet */ } await sleep(150); } return false; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el && el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const lum = c => { const m = String(c).match(/\d+(\.\d+)?/g); if (!m) return 0; const [r, g, b] = m.slice(0, 3).map(x => { const v = +x / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  await call('POST', '/api/users', {orgs: [], username: 'dave', display_name: 'Dave', password: 'password123', email: 'dave@example.com'});
  const CB = await login('bob'), CD = await login('dave');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CD);
  const L = (await call('POST', '/api/lists', {name: 'Shoot Berlin', org_id: ORG})).id;
  for (const t of ['Book the van', 'Call the crew']) await call('POST', '/api/tasks', {title: t, list_id: L});

  // ---- static: sizes in rem, motion only transform / opacity
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'sheets.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const px = (css.replace(/@media[^{]*\{/g, '').match(/(\d+(\.\d+)?)px/g) || []).filter(x => parseFloat(x) > 2);
  check(!px.length, 'sheets.css: only rem sizes ' + px.slice(0, 3));
  const tr0 = [...css.matchAll(/transition:([^;}]+)/g)].map(m => m[1]);
  check(tr0.length && tr0.every(t => t === 'none' || t.split(',').every(p => /^\s*(transform|opacity)\s/.test(p))), 'transitions: only transform / opacity ' + tr0);
  check(/prefers-reduced-motion: reduce/.test(css), 'reduced motion respected');

  // ---- the area and the overview
  let w = await boot({user: 'alice', hash: 'sheets'}), d = w.document;
  check(d.querySelector('#srail [data-sbb="sheets"].on[aria-current="page"]'), 'sidebar: "Tables" among the areas');  // 2.152.2 (#2622): the area icon in the bar
  check(await until(() => /No tables yet/.test(d.querySelector('#view').textContent)), 'overview: the empty state ' + d.querySelector('#view').textContent.slice(0, 120));  // 2.308.0 (#3260): wait for the overview instead of a fixed time
  w.prompt = () => 'Quote shoot';
  click(w, d.querySelector('[data-shv="new"]'));
  check(await until(() => /^#sheets\/\d+$/.test(w.location.hash) && w.eval('!!SHV.sh') && d.querySelector('#shv-scroll td.shvc')), 'new table: opened ' + w.location.hash);
  const SID = +w.location.hash.split('/')[1];
  const sh0 = await call('GET', `/api/sheets/${SID}`);
  check(sh0.title === 'Quote shoot' && sh0.space === `org:${ORG}`, 'new table: title, the organisation as space ' + sh0.space);
  check(d.querySelectorAll('#shv-scroll tbody tr').length === 10 && [...d.querySelectorAll('#shv-scroll .shvlet')].map(x => x.textContent).join() === 'A,B,C', 'grid: 10 rows, columns A B C');
  const C = sh0.columns.map(c => c.id), R = sh0.rows.map(r => r.id);
  const td = (r, c) => d.getElementById(`shv-c-${r}-${c}`);
  const sc = () => d.getElementById('shv-scroll');
  const get = async () => call('GET', `/api/sheets/${SID}`);
  const cellOf = (sh, addr) => (sh.cells || []).find(c => c.addr === addr);

  // ---- keys: typing overwrites, Enter saves and goes down
  w.eval(`shvSelect(${R[0]}, ${C[0]})`); sc().focus();
  check(td(R[0], C[0]).classList.contains('cur') && d.getElementById('shv-addr').textContent === 'A1', 'A1 chosen, the bar shows its address');
  key(w, sc(), '5');
  let ed = d.getElementById('shv-ed');
  check(ed && ed.value === '5', 'typing starts the editor with the key');
  key(w, ed, 'Enter');
  check(await until(async () => cellOf(await get(), 'A1')?.value === 5), 'Enter saves A1 = 5');
  check(w.eval('SHV.cur.r') === R[1], 'and goes one row down');
  key(w, sc(), '7'); key(w, d.getElementById('shv-ed'), 'Enter');
  await until(async () => cellOf(await get(), 'A2')?.value === 7);
  key(w, sc(), 'ArrowUp'); key(w, sc(), 'ArrowUp'); key(w, sc(), 'ArrowRight');
  check(w.eval('SHV.cur.r') === R[0] && w.eval('SHV.cur.c') === C[1], 'arrows: to B1');
  // a formula with the suggestions after "="
  key(w, sc(), '=');
  ed = d.getElementById('shv-ed');
  check(await until(() => d.querySelector('#shv-ac button[data-shvac]')), 'after "=" the suggestions open');
  ed.value = '=SUM'; ed.setSelectionRange(4, 4); ed.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => [...d.querySelectorAll('#shv-ac code')].some(c => /^(SUMME|SUM)$/.test(c.textContent))), 'typing SUM suggests the function');
  key(w, ed, 'Escape');
  check(!d.getElementById('shv-ac'), 'Escape closes the suggestions first');
  ed.value = '=A1+A2'; ed.dispatchEvent(new w.Event('input', {bubbles: true}));
  key(w, ed, 'Enter');
  check(await until(async () => cellOf(await get(), 'B1')?.value === 12), 'B1 = A1+A2 = 12');
  await until(() => td(R[0], C[1]).classList.contains('o-formula'));
  check(td(R[0], C[1]).classList.contains('o-formula') && td(R[0], C[0]).classList.contains('o-own'), 'origin colours: formula quiet, the own number normal');
  check(/=A1\+A2/.test(td(R[0], C[1]).getAttribute('title') || ''), 'hover: the formula with addresses ' + td(R[0], C[1]).getAttribute('title'));
  // the panel
  w.eval(`shvSelect(${R[0]}, ${C[1]})`);
  let side = d.getElementById('shv-side');
  check(/Comes from/.test(side.textContent) && [...side.querySelectorAll('[data-shv="goto"]')].map(b => b.textContent).join() === 'A1,A2', 'panel: B1 comes from A1, A2 ' + [...side.querySelectorAll('[data-shv="goto"]')].map(b => b.textContent));
  w.eval(`shvSelect(${R[0]}, ${C[0]})`);
  check(/Goes into/.test(side.textContent) && [...d.querySelectorAll('#shv-side [data-shv="goto"]')].some(b => b.textContent === 'B1'), 'panel: A1 goes into B1');
  // undo / redo of a cell
  await w.eval(`histStep('undo')`);
  check(await until(async () => !cellOf(await get(), 'B1')?.raw), 'undo: B1 empty again');
  await w.eval(`histStep('redo')`);
  check(await until(async () => cellOf(await get(), 'B1')?.value === 12), 'redo: B1 = 12 again');
  // a name for A1: the bar shows it
  w.eval(`shvSelect(${R[0]}, ${C[0]})`);
  const nm = d.getElementById('shv-name'); nm.focus(); nm.value = 'rate'; key(w, nm, 'Enter');
  check(await until(async () => (await get()).names?.rate), 'a name for A1 from the panel');
  await until(() => d.getElementById('shv-addr').textContent === 'rate');
  check(d.getElementById('shv-addr').textContent === 'rate', 'the bar shows the name');

  // ---- a selection column from the column dialog, its colour for the whole row
  w.eval(`shvColModal(SHV.sh._col.get(${C[2]}))`);
  await until(() => d.querySelector('.modal.shvcmd'));  // 2.308.0 (#3260): wait for the dialog instead of a fixed time
  let md = d.querySelector('.modal.shvcmd');
  check(md, 'the column dialog');
  md.querySelector('#shv-ct').value = 'Status';
  const k = md.querySelector('#shv-ck'); k.value = 'select'; k.dispatchEvent(new w.Event('change', {bubbles: true}));
  const nameOpt = (i, v) => { const x = md.querySelector(`[data-oname="${i}"]`); x.value = v; x.dispatchEvent(new w.Event('input', {bubbles: true})); };
  nameOpt(0, 'Open');
  click(w, md.querySelector('[data-m="opt-add"]')); nameOpt(1, 'Booked');
  click(w, md.querySelector('[data-ocol="1"]'));
  check(md.querySelectorAll('.lrpal [data-opal]').length === w.eval('LCOLORS.length'), 'the palette of the app for an option');
  click(w, md.querySelector('.lrpal [data-opal="#4ade80"]'));
  const rr = md.querySelector('input[name="shv-cm"][value="row"]'); rr.checked = true; rr.dispatchEvent(new w.Event('change', {bubbles: true}));
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await get()).columns.find(c => c.id === C[2])?.kind === 'select'), 'saved: the column is a selection');
  const col = (await get()).columns.find(c => c.id === C[2]);
  check(col.title === 'Status' && col.color_mode === 'row' && col.options.map(o => o.label).join() === 'Open,Booked' && col.options[1].color === '#4ade80', 'title, options with colour, row mode ' + JSON.stringify(col));
  await until(() => d.querySelector(`#shv-scroll th[data-c="${C[2]}"]`)?.textContent.includes('Status'));
  // the cell's menu
  w.eval(`shvSelect(${R[0]}, ${C[2]})`); sc().focus();
  key(w, sc(), 'Enter');
  check(await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].some(b => b.textContent.includes('Booked'))), 'Enter on a selection cell: its options as a menu');
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => b.textContent.includes('Booked')));
  check(await until(async () => cellOf(await get(), 'C1')?.value === 'Booked'), 'the option saved (value = label)');
  await until(() => d.querySelector(`#shv-scroll tr[data-id="${R[0]}"]`)?.classList.contains('shvrc'));
  const row1 = d.querySelector(`#shv-scroll tr[data-id="${R[0]}"]`);
  check(row1.classList.contains('shvrc') && /--shr:\s*#4ade80/.test(row1.getAttribute('style') || '') && td(R[0], C[2]).querySelector('.shvopt.fill'), 'the whole row takes the colour, the cell a filled label');

  // ---- sorting (saved, one undo step) and filtering (view only)
  await w.eval(`shvSort(${C[0]}, -1)`);
  check(await until(async () => (await get()).rows[0].id === R[1]), 'sorted descending by A: the 7 first (saved)');
  check(d.querySelector('#shv-scroll tbody tr').dataset.id === String(R[1]), 'the grid shows the new order');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await get()).rows[0].id === R[0]), 'undo: the old order');
  w.eval(`shvFilterPop(${C[0]}, document.querySelector('[data-shv="col"][data-c="${C[0]}"]'))`);
  await until(() => d.querySelector('#pop [data-shvf="q"]'));  // 2.308.0 (#3260): wait for the filter field instead of a fixed time
  const fq = d.querySelector('#pop [data-shvf="q"]'); fq.value = '7'; fq.dispatchEvent(new w.Event('input', {bubbles: true}));  // column A is a text column: "contains"
  check(await until(() => d.querySelectorAll('#shv-scroll tbody tr').length === 1 && d.querySelector('[data-shv="unfilter"]')), 'filter A contains 7: one row shown, a reset button');  // 2.308.0 (#3260): wait for the filtered grid instead of a fixed time
  check((await get()).rows.length === 10, 'the filter changes nothing on the server');
  w.eval('closePop()'); click(w, d.querySelector('[data-shv="unfilter"]'));
  check(await until(() => d.querySelectorAll('#shv-scroll tbody tr').length === 10), 'filters reset: all rows');  // 2.308.0 (#3260): wait for all rows instead of a fixed time

  // ---- paste of a block (Excel / Sheets text) at A4, one undo step
  w.eval(`shvSelect(${R[3]}, ${C[0]})`);
  await w.eval(`shvPaste({clipboardData: {getData: t => t === 'text/plain' ? '1\\t2\\n3\\t4' : ''}, preventDefault() {}})`);
  let s1 = await get();
  check(cellOf(s1, 'A4')?.value === 1 && cellOf(s1, 'B5')?.value === 4, 'paste: a 2 x 2 block from A4');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !cellOf(await get(), 'A4')?.raw && !cellOf(await get(), 'B5')?.raw), 'undo: the block is gone');

  // ---- a Kalmido value, frozen
  w.eval(`shvSelect(${R[1]}, ${C[1]})`); sc().focus();
  key(w, sc(), '='); ed = d.getElementById('shv-ed'); ed.value = '=liste.shoot_berlin.aufgaben'; ed.dispatchEvent(new w.Event('input', {bubbles: true})); key(w, ed, 'Enter');
  check(await until(async () => cellOf(await get(), 'B2')?.origin === 'kalmido'), 'a Kalmido variable: origin kalmido ' + JSON.stringify(cellOf(await get(), 'B2')));
  await until(() => td(R[1], C[1]).classList.contains('o-kalmido'));
  check(td(R[1], C[1]).classList.contains('o-kalmido') && /2/.test(td(R[1], C[1]).textContent), 'the cell in the accent colour, 2 tasks');
  w.eval(`shvSelect(${R[1]}, ${C[1]})`);
  check(/Kalmido sources/.test(d.getElementById('shv-side').textContent) && d.querySelector('#shv-side a.shvsrc[href="#l/' + L + '"]'), 'panel: the source list linked');
  click(w, d.querySelector('#shv-side [data-shv="freeze"]'));
  check(await until(() => td(R[1], C[1]).classList.contains('o-frozen')), 'freeze: grey');
  await w.eval(`histStep('undo')`);
  check(await until(() => td(R[1], C[1]).classList.contains('o-kalmido')), 'undo: live again');

  // ---- presence of another member, the agents' changes
  const a1 = cellOf(await get(), 'A1');
  await call('POST', `/api/sheets/${SID}/presence`, {cell_id: a1.id}, CB);
  await w.eval(`shvLoad(${SID}, true)`);
  check(await until(() => /Bob is editing A1/.test(d.querySelector('.shvpres')?.textContent || '') && td(R[0], C[0]).classList.contains('shvpc')), 'presence: "Bob is editing A1", the cell marked');  // 2.308.0 (#3260): wait for the presence instead of a fixed time
  w.eval(`SHV.sh.batches = [{batch: 'b1', agent_id: 1, agent_name: 'Helper', created_at: new Date().toISOString(), count: 2, undone: 0}]; shvSideSync()`);
  check(/Changes by agents/.test(d.getElementById('shv-side').textContent) && d.querySelector('#shv-side [data-shv="bundo"][data-b="b1"]'), 'panel: an agent call with "Take back"');
  w.close();

  // ---- attached to a list: the list menu, the list's tables, new = attached
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(w.eval(`listMenuItems(${L}).some(x => x.label === 'Tables')`), 'list menu: "Tables"');
  w.eval(`go('sheets/l/${L}')`);
  check(await until(() => /No tables attached yet/.test(d.querySelector('#view').textContent)), "the list's tables: empty");  // 2.308.0 (#3260): wait for the list's tables instead of a fixed time
  w.prompt = () => 'Budget';
  click(w, d.querySelector('[data-shv="new"]'));
  check(await until(() => /^#sheets\/\d+$/.test(w.location.hash) && w.eval('SHV.sh?.title') === 'Budget'), 'a new table from there');
  const BID = +w.location.hash.split('/')[1];
  // 2.165.12: the back button gets the list name once the lists are drawn - wait for it (red once on CI 2.165.11)
  check((await call('GET', `/api/sheets/${BID}`)).list_id === L && await until(() => /Shoot Berlin/.test(d.querySelector('.shvtop .btn')?.textContent || '')), 'attached to the list, the back button names it');
  // delete with undo
  await w.eval(`shvDelete(${BID}, 'Budget', ${L})`);
  check((await call('GET', `/api/sheets/${BID}`))._status === 404, 'deleted (trash)');
  // 2.284.0 A (#3120): Mac red 2x - histStep does nothing while HIST.busy and first flushes pending saves (slow on a busy
  // place): wait for no undo running and the delete's step on top, then up to 15 s for the restore
  await until(() => !w.eval('HIST.busy') && /^Deleted /.test(w.eval('HIST.undo[HIST.undo.length - 1]?.label') || ''));
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${BID}`))._status === 200, 100), 'undo: back ' + w.eval(`(HIST.busy ? 'busy ' : '') + (HIST.undo[HIST.undo.length - 1]?.label || '-') + ' / ' + (HIST.redo[HIST.redo.length - 1]?.label || '-')`));
  w.close();

  // ---- a reader of the list: read only
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'view'});
  w = await boot({user: 'bob', hash: 'sheets/' + BID}); d = w.document;
  await until(() => d.querySelector('#shv-scroll'));
  check(/Read only/.test(d.querySelector('.shvtop')?.textContent || '') && !d.querySelector('[data-shv="coladd"]') && d.getElementById('shv-in').readOnly, 'a reader: "Read only", no add buttons, the bar read only');
  w.close();

  // ---- phone width: tap = choose, a second tap edits; dave without an organisation
  w = await boot({user: 'dave', hash: 'sheets', mobile: true}); d = w.document;
  w.prompt = () => 'Kit';
  click(w, d.querySelector('[data-shv="new"]'));
  check(await until(() => w.eval('!!SHV.sh') && d.querySelector('#shv-scroll td.shvc')), 'dave: a new table');
  const ds = await call('GET', '/api/sheets/' + w.eval('SHV.sh.id'), null, CD);
  check(ds.space === 'private', 'dave: the table is private ' + ds.space);
  const t0 = d.querySelector('#shv-scroll td.shvc');
  click(w, t0);
  check(t0.isConnected && d.querySelector('#shv-scroll td.shvc.cur') && !d.getElementById('shv-ed'), 'phone: the first tap chooses');
  click(w, d.querySelector('#shv-scroll td.shvc.cur'));
  check(d.getElementById('shv-ed'), 'phone: the second tap edits');
  check(d.querySelector('.shvbody .shvside'), 'phone: the panel is there (below the grid)');
  w.close();

  // ---- Firefox: the real look
  const ffLogin = async ({ev, nav}, theme, user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const look = async (o, vw, vh, theme) => {
    const {cmd, ev, nav, shot} = o, tag = `${vw} ${theme}`;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o, theme) === 200, tag + ': login');
    await nav(B + '#sheets/' + SID);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#shv-scroll td.shvc')`).catch(() => false)); i++) await sleep(250);
    await sleep(500);
    await ev(`(() => { SHV.deps = 2; shvSelect(${R[0]}, ${C[1]}); shvRender(); return 1; })()`);
    // 2.308.0 (#3260): wait for the arrows and the filled label instead of a fixed time
    for (let i = 0; i < 40 && !(await ev(`document.querySelectorAll('#shv-deps path[marker-end]').length >= 2 && !!document.querySelector('#shv-scroll .shvopt.fill')`).catch(() => false)); i++) await sleep(250);
    const x = await ev(`(() => { const o = document.querySelector('#shv-scroll .shvopt.fill'), g = document.querySelector('#shv-scroll'), k = document.querySelector('#shv-scroll td.o-kalmido');
      const cs = o && getComputedStyle(o); return {fg: cs && cs.color, bg: cs && cs.backgroundColor, paths: document.querySelectorAll('#shv-deps path[marker-end]').length,
        gw: Math.round(g.getBoundingClientRect().width), vw: innerWidth, kc: k && getComputedStyle(k).color, acc: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()}; })()`);
    check(x && x.fg && contrast(x.fg, x.bg) >= 4.5, `${tag}: the option label reads well (${x && contrast(x.fg, x.bg).toFixed(2)})`);
    check(x && x.paths >= 2, `${tag}: arrows for the whole table ` + (x && x.paths));
    check(x && x.gw <= x.vw, `${tag}: the grid stays inside the screen (scrolls inside) ` + JSON.stringify(x));
    await shot(`p289b-${vw}-${theme}.png`);
  };
  await firefox(async o => { await look(o, 1280, 800, 'light'); await look(o, 1280, 800, 'dark'); }, false);
  await firefox(async o => { await look(o, 390, 844, 'dark'); }, true);

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
