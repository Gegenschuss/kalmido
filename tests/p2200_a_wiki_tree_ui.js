// 2.200.0 A (#2747) UI tests: the knowledge tree on folders of the file store (wiki.js, wkfolder.py). Own container
// (start.sh), jsdom, a person without an organisation (one workspace).
// - a computer (sidebar B): the panel's tree shows folders AND pages, an empty folder too; its nodes carry ns 'wk', are
//   draggable, folders take drops, everything has a menu
// - dragging a page onto a folder moves it (the server writes the path), dropping on a page's edge sorts it (path stays)
// - the folder's list: rows with the date and the menu "…" (Rename…, Move to…, Move to the trash), "New folder" in the bar
//   makes a folder in the open folder (dialog)
// - a phone: the list shows the empty folder, the row's "…" opens the menu
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2200A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent);
const idx = async () => call('GET', '/api/wiki?space=private');
const pathOf = async id => (await call('GET', '/api/wiki/pages/' + id)).path;
function dnd(w, from, to, y) {  // a mouse drag of node from onto node to at height y (0..1) of it (as p2199_a_tree_ui.js)
  to.getBoundingClientRect = () => ({top: 100, height: 20, left: 0, width: 200, right: 200, bottom: 120});
  const ev = (type, el) => { const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientY: 100 + y * 20}); Object.defineProperty(e, 'dataTransfer', {value: {setData() {}, types: [], effectAllowed: '', dropEffect: ''}}); el.dispatchEvent(e); return e; };
  ev('dragstart', from); const over = ev('dragover', to); ev('drop', to); ev('dragend', from);
  return over.defaultPrevented;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'files'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  const id = {};
  for (const [k, p] of [['check', 'Processes/Checklist'], ['inner', 'Processes/Deep/Inner'], ['loose', 'Loose'], ['other', 'Other']]) id[k] = (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p})).id;
  const fe = await call('POST', '/api/wiki/folders', {space: 'private', name: 'Empty'});
  check(fe.http === 201 && Object.values(id).every(Boolean), 'setup: pages and an empty folder ' + fe.http);
  let j = await idx();
  const fid = n => (j.folders || []).find(f => f.path === n)?.id, nid = pid => (j.pages || []).find(p => p.id === pid)?.node_id;

  // ================= a computer: the panel's tree
  let w = await boot({user: 'alice', hash: 'wiki'}), d = w.document;
  check(await until(() => rowOf(d, 'Processes') && rowOf(d, 'Empty') && rowOf(d, 'Loose')), 'the panel: folders, the empty folder and the pages at the top');
  const P = rowOf(d, 'Processes'), L = rowOf(d, 'Loose'), E = rowOf(d, 'Empty');
  check(P?.dataset.sbbns === 'wk' && P.dataset.sbbdrop === '1' && P.getAttribute('draggable') === 'true' && P.dataset.sbbmenu === '1', 'a folder: draggable, takes drops, has a menu');
  check(L?.dataset.sbbns === 'wk' && !L.dataset.sbbdrop && L.getAttribute('draggable') === 'true' && L.querySelector('.sbbtn')?.dataset.go === 'wiki/' + id.loose, 'a page: draggable, no drops, opens the page');
  check(P && L && P.dataset.sbbpar === L.dataset.sbbpar, 'folders and pages at the top are siblings');
  // dragging a page into a folder: the path follows
  check(dnd(w, L, E, 0.5), 'the empty folder takes the page');
  check(await until(async () => (await pathOf(id.loose)) === 'Empty/Loose'), 'dragged into the folder: its path is Empty/Loose');
  // sorting: "Other" before "Processes" -- the paths stay
  await until(() => rowOf(d, 'Other'));
  const O = rowOf(d, 'Other'), P2 = rowOf(d, 'Processes');
  dnd(w, O, P2, 0.1);
  j = await until(async () => { const x = await idx(); return (x.pages || []).find(p => p.id === id.other)?.sort_no ? x : null; });
  check(!!j && (await pathOf(id.other)) === 'Other', 'sorted by dragging: a place by hand, the path stays');
  j = await idx();
  // the right-click menu of a folder
  rowOf(d, 'Processes').querySelector('.sbbtn').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  let mi = await until(() => menuItems(d).length && menuItems(d));
  check(mi && mi.includes('New folder…') && mi.includes('Rename…') && mi.includes('Move to…') && mi.includes('Move to the trash'), 'right-click: the folder\'s menu ' + JSON.stringify(mi));
  check(mi && mi.includes('Share…'), '2.200.0 F (#2747, review 11): the folder\'s menu has Share… ' + JSON.stringify(mi));
  w.eval('closePop?.()');

  // ================= the folder's list
  w.location.hash = '#wiki/d/Processes';
  check(await until(() => [...d.querySelectorAll('#view #wk-res .wkrow')].length === 2), 'the list of Processes: its folder and its page');
  const row = [...d.querySelectorAll('#view #wk-res .wkrow')].find(r => r.textContent.includes('Checklist'));
  check(!!row?.querySelector('.wkwhen') && !!row.querySelector('[data-wk="rmenu"]'), 'a row: the date and the menu "…"');
  check(d.querySelector('#view .wkcrumbs a')?.textContent === 'Knowledge' && d.querySelector('#side .sbbi[data-go="wiki"] .n')?.textContent === 'Knowledge', 'one name for the top in the panel and the path (audit B 1)');
  row.querySelector('[data-wk="rmenu"]').click();
  mi = await until(() => menuItems(d).length && menuItems(d));
  check(mi && mi.includes('Rename…') && mi.includes('Move to…') && mi.includes('Move to the trash'), 'the row\'s "…": its menu ' + JSON.stringify(mi));
  w.eval('closePop?.()');
  // "New folder" in the bar: into the open folder
  w.__dialogs = 'manual';
  d.querySelector('#view [data-wk="newfolder"]')?.click();
  const md = await until(() => d.querySelector('.cdlg #cdlg-in') && d.querySelector('.cdlg'));
  check(!!md, '"New folder" asks for the name');
  if (md) { md.querySelector('#cdlg-in').value = 'Made here'; md.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); }
  check(await until(async () => ((await idx()).folders || []).some(f => f.path === 'Processes/Made here')), 'the new folder lies in the open folder');
  check(await until(() => [...d.querySelectorAll('#view #wk-res .wkrow')].some(r => r.textContent.includes('Made here'))), 'the list shows the new (empty) folder');
  w.close();

  // ================= a phone
  w = await boot({user: 'alice', hash: 'wiki', mobile: true}); d = w.document;
  check(await until(() => [...d.querySelectorAll('#view .wktree .wkitem')].some(a => a.textContent.includes('Empty'))), 'a phone: the list shows the folders, the empty one too');
  const mrow = await until(() => [...d.querySelectorAll('#view .wkrow')].find(r => r.textContent.includes('Other') && r.querySelector('[data-wk="rmenu"]')));
  check(!!mrow, 'a phone: the row has its "…"');
  mrow?.querySelector('[data-wk="rmenu"]').click();
  mi = await until(() => menuItems(d).length && menuItems(d));
  check(mi && mi.includes('Move to…'), 'a phone: the menu opens ' + JSON.stringify(mi));
  w.close();
  check(fid('Empty') && nid(id.check), 'the index names the nodes');

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
