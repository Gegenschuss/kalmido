// 2.46.2 UI tests of part D (own container, start.sh). jsdom:
// - #1472 the month label of a client page is empty (not "Invalid Date") without a month
// - #1662 an empty section has no "Drop tasks here" field any more, its name takes the drop; "+ New section" stays
// - #1663 encryption locked and no note of mine: the encrypted-note field is gone; with a note of mine: "Unlock"
// - #1664 a subfolder on the upper half of a top folder becomes a top-level folder right before it; lower half = into it
//   (2.352.0 #2748: through the sidebar tree, sbb_treeReg 'lf')
// - #1647 the import action bar is a flex row over the full width (the spacer works)
const {execFileSync} = require('child_process');
const {webcrypto} = require('crypto');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const dnd = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: ''}; e.clientY = 10; el.dispatchEvent(e); return e; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const L = (await call('POST', '/api/lists', {name: 'Office'})).id;
  const A = (await call('POST', '/api/sections', {name: 'Doing', list_id: L})).id, C = (await call('POST', '/api/sections', {name: 'Later', list_id: L})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Invoice', list_id: L, section_id: A})).id;
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await until(() => d.querySelector('#view .trow'));

  // ================= #1472
  check(w.eval(`monthLabel(undefined)`) === '' && w.eval(`monthLabel('')`) === '' && w.eval(`monthLabel('nonsense')`) === '', '#1472: no month = empty label, never "Invalid Date"');
  check(/2026/.test(w.eval(`monthLabel('2026-03')`)), '#1472: a month still reads as month and year');

  // ================= #1662
  check(!d.querySelector('#view .sdrop[data-section]') && d.querySelector(`#view .ghead[data-section="${C}"]`) && d.querySelector('#view .sdrop.snew[data-newsec]'),
    '#1662: the empty section stays visible without a drop field; "+ New section" is still there');
  dnd(w, d.querySelector(`#view .trow[data-id="${T1}"]`), 'dragstart'); await sleep(20);
  const hd = d.querySelector(`#view .ghead[data-section="${C}"]`);
  check(dnd(w, hd, 'dragover').defaultPrevented && hd.classList.contains('drop'), '#1662: the empty section\'s name takes the task and is highlighted');
  dnd(w, hd, 'drop');
  check(await until(async () => (await call('GET', `/api/tasks/${T1}`)).section_id === C), '#1662: dropped on the name: the task is in the empty section');

  // ================= #1663
  Object.defineProperty(w, 'crypto', {configurable: true, value: webcrypto});
  check(!!w.crypto?.subtle, '#1663: WebCrypto in the test page');
  w.eval(`E2E.st = {set: true}`);
  check(w.eval(`e2eNoteHtml({id: 7, encrypted_note_mine: false})`) === '', '#1663: locked, no note of mine: no field at all');
  check(/note-unlock/.test(w.eval(`e2eNoteHtml({id: 7, encrypted_note_mine: true})`)), '#1663: locked, a note of mine: "Unlock" as before');

  // ================= #1664
  w.eval(`S.settings.folders = JSON.stringify(['Work', 'Work' + FSEP + 'Sub', 'Home'])`);
  // 2.352.0 (#2748): a folder is dragged by the sidebar tree (areas.js sbb_tzone: upper edge = before, middle = into, lower
  // edge = after); sorted before a top folder from inside another one = a top-level folder right before it (the tree's order)
  await w.eval(`SBB_TREE.lf.order('Work' + FSEP + 'Sub', {before: 'Home', into: ''})`);
  await until(async () => JSON.parse(((await call('GET', '/api/state')).settings || {}).folders || '[]').join() === 'Work,Sub,Home');
  const fl = JSON.parse(w.eval(`S.settings.folders`));
  check(JSON.stringify(fl) === JSON.stringify(['Work', 'Sub', 'Home']), '#1664: the folder is now top-level, right before Home ' + JSON.stringify(fl));
  const sv = JSON.parse(((await call('GET', '/api/state')).settings || {}).folders || '[]');
  check(JSON.stringify(sv) === JSON.stringify(fl), '#1664: the order is saved ' + JSON.stringify(sv));

  // ================= #1647
  const css = require('./boot').allCssSync(); // 2.65.0 (#1824): + the module stylesheets
  check(/\.oimfoot\{display:flex;[^}]*justify-content:flex-end/.test(css) && /\.oimfoot\{[^}]*margin:1rem -1\.75rem 0/.test(css) && /\.oimfoot\{[^}]*background:var\(--bg2\)/.test(css) && /\.oimfoot\{[^}]*border-top:1px solid var\(--line2\)/.test(css),
    '#1647: the import bar: flex row, full width, own background, line above');

  console.log(`p2462_d_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
