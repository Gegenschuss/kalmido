// 2.578.0 part C UI test (tables: format bar, colour rules, fill handle)
// kalmido-suite: fresh
// 2.578.0 part C UI test (#3462 points 1, 3, 6), own container (start.sh), jsdom. Invented names only. As a person without an
// organisation (frida) in her private table:
// - the format bar under the formula bar: "Bold" makes the chosen cell bold (saved as its format, drawn with the class), one
//   Undo step (Undo / Redo); Ctrl+B on the grid toggles it too
// - a range gets a fill from the palette menu (all its cells), "Merge cells" spans the block (colspan, the covered cell is not
//   drawn), a second press splits it again; "Clear format" keeps the input
// - the dialog "Rules": a rule "greater than 10" with a fill colours exactly the cells above 10, a changed value follows
// - the fill handle: at the choice's corner; filling 1, 2 down gives 3, 4 (one Undo step); the series: dates, weekdays,
//   "Item 1", a formula moves its references; a single number is copied
// - no script errors. P2578C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2578C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const until = (fn, n) => require('./boot').until(async () => { try { return await fn(); } catch { return false; } }, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el && el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  const fr = await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'}, AK);
  check(fr.id, 'a person without an organisation ' + JSON.stringify(fr).slice(0, 120));
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,sheets'});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  const S = await call('POST', '/api/sheets', {title: 'Harvest', space: 'private'});
  check(S._status === 201, 'a private table ' + JSON.stringify(S).slice(0, 120));
  const SID = S.id, R = S.rows.map(r => r.id), C = S.columns.map(c => c.id);
  await call('PATCH', `/api/sheets/${SID}/columns/${C[1]}`, {kind: 'number'});
  await call('PATCH', `/api/sheets/${SID}/columns/${C[2]}`, {kind: 'number'});
  await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{cell: 'A1', raw: 'Apples'}, {cell: 'A2', raw: 'Pears'}, {cell: 'A3', raw: 'Plums'},
    {cell: 'B1', raw: '12'}, {cell: 'B2', raw: '4'}, {cell: 'B3', raw: '30'}, {cell: 'C1', raw: '1'}, {cell: 'C2', raw: '2'}]});
  const sheet = () => call('GET', `/api/sheets/${SID}`);
  const cellOf = (sh, addr) => (sh.cells || []).find(c => c.addr === addr) || {};

  const w = await boot({user: 'frida', hash: 'sheets/' + SID}), d = w.document;
  check(await until(() => d.querySelector('#shv-scroll td.shvc')), 'the table is open');
  const td = (r, c) => d.getElementById(`shv-c-${r}-${c}`), sc = () => d.getElementById('shv-scroll');
  const bar = k => d.querySelector(`#shfm-bar [data-shfm="${k}"]`);
  check(await until(() => d.getElementById('shfm-bar')), 'the format bar is there (right to write)');
  const sel = (r0, c0, r1, c1) => { w.eval(`shvSelect(${r0}, ${c0}); ${r1 != null ? `shvSelect(${r1}, ${c1}, true)` : ''}`); sc().focus(); };

  // ---- bold through the bar, one undo step
  sel(R[0], C[0]);
  click(w, bar('bold'));
  check(await until(async () => cellOf(await sheet(), 'A1').fmt?.bold === true), 'Bold: saved as the cell format');
  check(await until(() => td(R[0], C[0])?.classList.contains('shfm-b')), 'the cell is drawn bold');
  check(await until(() => bar('bold')?.getAttribute('aria-pressed') === 'true'), 'the button shows the state');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !cellOf(await sheet(), 'A1').fmt && !td(R[0], C[0])?.classList.contains('shfm-b')), 'Undo: not bold again');
  await w.eval(`histStep('redo')`);
  check(await until(async () => cellOf(await sheet(), 'A1').fmt?.bold === true), 'Redo: bold again');
  check(cellOf(await sheet(), 'A1').raw === 'Apples', 'the input stays');
  sel(R[1], C[0]);
  key(w, sc(), 'i', {ctrlKey: true});
  check(await until(async () => cellOf(await sheet(), 'A2').fmt?.italic === true), 'Ctrl+I on the grid: italic');

  // ---- a range gets a fill from the palette
  sel(R[0], C[0], R[1], C[1]);
  click(w, bar('fill'));
  const pal = await until(() => d.querySelector('#pop [data-act="shfm-fill-a2"]'));
  check(pal, 'the fill menu offers the palette');
  click(w, pal);
  check(await until(async () => { const s = await sheet(); return ['A1', 'A2', 'B1', 'B2'].every(a => cellOf(s, a).fmt?.fill === 'a2'); }), 'the fill on all four cells');
  check(await until(() => td(R[1], C[1])?.classList.contains('shfm-f-a2')), 'drawn with the fill');
  check(cellOf(await sheet(), 'A1').fmt?.bold === true, 'the fill keeps the bold of A1');

  // ---- merge and split
  sel(R[3], C[0], R[3], C[1]);
  click(w, bar('merge'));
  check(await until(async () => JSON.stringify(cellOf(await sheet(), 'A4').fmt?.merge) === '[1,2]'), 'merge: saved on the top left cell');
  check(await until(() => td(R[3], C[0])?.getAttribute('colspan') === '2' && !td(R[3], C[1])), 'the block spans two columns, the covered cell is not drawn');
  sel(R[3], C[0]);
  click(w, bar('merge'));
  check(await until(async () => !cellOf(await sheet(), 'A4').fmt?.merge && td(R[3], C[1])), 'a second press splits it again');
  sel(R[1], C[0]);
  click(w, bar('clear'));
  check(await until(async () => !cellOf(await sheet(), 'A2').fmt && cellOf(await sheet(), 'A2').raw === 'Pears'), 'Clear format keeps the input');

  // ---- a colour rule from the dialog
  sel(R[0], C[1], R[2], C[1]);
  click(w, bar('rules'));
  const md = await until(() => d.querySelector('.shfmdlg'));
  check(md, 'the dialog "Rules" opens');
  if (md) {
    const op = md.querySelector('#shfm-op'); op.value = 'gt'; op.dispatchEvent(new w.Event('change', {bubbles: true}));
    md.querySelector('#shfm-a').value = '10';
    click(w, md.querySelector('[data-shfmr-fill="a"]'));
    click(w, md.querySelector('[data-m="save"]'));
  }
  check(await until(async () => { const r = (await sheet()).rules || []; return r.length === 1 && r[0].op === 'gt' && r[0].a === '10' && r[0].fill === 'a'; }), 'the rule is saved');
  check(await until(() => td(R[0], C[1])?.classList.contains('shfm-f-a') && td(R[2], C[1])?.classList.contains('shfm-f-a') && !td(R[1], C[1])?.classList.contains('shfm-f-a')),
    'the rule colours 12 and 30, not 4');
  await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{cell: 'B2', raw: '40'}]});
  await w.eval('shvLoad(SHV.sh.id, true)');
  check(await until(() => td(R[1], C[1])?.classList.contains('shfm-f-a')), 'a changed value follows the rule');

  // ---- the fill handle and the series
  sel(R[0], C[2], R[1], C[2]);
  check(await until(() => td(R[1], C[2])?.querySelector('.shfl-h')), 'the handle sits at the corner of the choice');
  await w.eval(`shfl_fill(shvRect(), {down: 2, right: 0}, false)`);
  check(await until(async () => { const s = await sheet(); return cellOf(s, 'C3').value === 3 && cellOf(s, 'C4').value === 4; }), 'filling 1, 2 down gives 3, 4');
  await w.eval(`histStep('undo')`);
  check(await until(async () => { const s = await sheet(); return !cellOf(s, 'C3').raw && !cellOf(s, 'C4').raw; }), 'one Undo step takes the fill back');
  const ser = (src, n, v = true, plain = false) => JSON.stringify(w.shfl_series(src, n, v, plain));
  check(ser(['2026-11-06'], 2) === '["2026-11-07","2026-11-08"]', 'a date goes on by a day ' + ser(['2026-11-06'], 2));
  check(ser(['15.01.2026', '15.02.2026'], 2) === '["15.03.2026","15.04.2026"]', 'dates a month apart go on by months ' + ser(['15.01.2026', '15.02.2026'], 2));
  check(ser(['Mo', 'Di'], 2) === '["Mi","Do"]' && ser(['Friday'], 3) === '["Saturday","Sunday","Monday"]', 'weekdays in their form ' + ser(['Mo', 'Di'], 2));
  check(ser(['Item 1'], 2) === '["Item 2","Item 3"]', '"Item 1" counts up ' + ser(['Item 1'], 2));
  check(ser(['=A1*2+$B$1'], 2) === '["=A2*2+$B$1","=A3*2+$B$1"]' && ser(['=A1'], 1, false) === '["=B1"]', 'a formula moves its references ' + ser(['=A1*2+$B$1'], 2));
  check(ser(['7'], 2) === '["7","7"]' && ser(['1,5', '2'], 2) === '["2,5","3,0"]', 'one number is copied, decimals keep their form ' + ser(['1,5', '2'], 2));
  check(ser(['o1', 'o2'], 2, true, true) === '["o1","o2"]', 'a selection column repeats');

  check(!errs.length, 'no script errors ' + errs.slice(0, 3).join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
