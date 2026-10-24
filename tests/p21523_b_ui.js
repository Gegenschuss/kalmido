// 2.152.3 part B UI tests (#2619 #2620 #2621): the panels of tables, knowledge and the file store in sidebar B (a computer).
// Own container (start.sh), jsdom, a person WITHOUT an organisation (as tests/freelancer_fixture.py; freelancer-matrix: sheets,
// wiki, files).
// - #2619 tables: "All tables" + "New table", the own tables, a table of a project in its own group (2.199.0 C: an automatic
//   group of the tree, LS sbbOpen 'sh:l<id>'); a click opens #sheets/<id>, the open table in the accent (.on)
// - #2620 knowledge: the top folders in the panel, a subfolder only after its arrow was clicked (LS sbbOpen 'wk:…');
//   a folder opens as a list with its path (#wiki/d/<path>), no tree column (.wkside) on a computer, the bar has search,
//   "New page" and the space menu; sbb_treeAnyOpen / sbb_treeCloseAll for "Collapse all"
// - #2621 file store: Files with its top folders, a subfolder loaded only after a click, no space column; a file dragged onto a
//   folder of the panel is moved there
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21523B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const dnd = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: '', types: [], files: [], setDragImage() {}}; el.dispatchEvent(e); return e; };
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK);  // a server with organisations
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'files', 'sheets'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  const P = (await call('POST', '/api/lists', {name: 'Launch'})).id;
  const S1 = (await call('POST', '/api/sheets', {title: 'Budget', space: 'private'})).id;
  const S2 = (await call('POST', '/api/sheets', {title: 'Crew', space: 'private', list_id: P})).id;
  check(S1 && S2, 'two tables, one of them on the project ' + S1 + ' ' + S2);
  for (const p of ['Docs/Guide', 'Docs/Deep/Inner', 'Top page']) await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p});
  const INV = (await call('POST', '/api/files/folders', {name: 'Invoices', space: 'private'})).id;
  const Q1 = (await call('POST', '/api/files/folders', {name: 'Q1', parent_id: INV})).id;
  const ARC = (await call('POST', '/api/files/folders', {name: 'Archive', space: 'private'})).id;
  const fd = new FormData(); fd.append('space', 'private'); fd.append('file', new Blob(['hello']), 'note.txt');
  const up = await (await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json();
  const NOTE = (up.items || [])[0]?.id;
  check(INV && Q1 && ARC && NOTE, 'folders Invoices/Q1, Archive and a file at the top');

  // ================= #2619 tables in the panel
  let w = await boot({user: 'frida', hash: 'sheets'}); let d = w.document;
  check(await until(() => d.querySelector(`#side [data-sbbsh="${S1}"]`)), 'the panel lists the table Budget');
  check(d.querySelector('#side [data-sbbsh="all"].on') && /All tables/.test(d.querySelector('#side [data-sbbsh="all"]').textContent), '"All tables" (the overview) is open');
  check(!d.querySelector('#side [data-act="sbb-shnew"]'), '2.224.0 B (#2816): "New table" only in the overview head, not in the panel');
  // 2.199.0 C (#2742): the projects are automatic groups of the workspace's tree (sheetfold.js): closed until opened, the
  // arrow keeps it per device in LS sbbOpen 'sh:l<id>' (was a folding group in sbbFold)
  const arr = () => d.querySelector(`#side .sbbt.sbbauto [data-act="sbb-tree"][data-k="sh:l${P}"]`);
  check(arr() && /Launch/.test(arr().closest('.sbbt').textContent) && !d.querySelector(`#side [data-sbbsh="${S2}"]`), 'the project is an automatic group, closed');
  arr()?.click();
  check(await until(() => d.querySelector(`#side [data-sbbsh="${S2}"]`)), 'the project table in the group of its project');
  check(!d.querySelector('#view .wkside'), 'no foreign column');
  d.querySelector(`#side [data-sbbsh="${S1}"] .sbbtn`).click();
  check(await until(() => w.location.hash === '#sheets/' + S1 && d.querySelector(`#side [data-sbbsh="${S1}"].on`)), 'a click opens the table, its row in the accent ' + w.location.hash);
  check(await until(() => d.querySelector('#view .shvside')), 'the cell detail field stays');
  arr()?.click();
  check(await until(() => !d.querySelector(`#side [data-sbbsh="${S2}"]`)) && !w.eval(`(LS.get('sbbOpen', []) || []).includes('sh:l${P}')`), 'the project group folds again, kept in sbbOpen');
  w.close();

  // ================= #2620 knowledge: folders in the panel, lazily; a folder as a list with its path
  w = await boot({user: 'frida', hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify('private')}}); d = w.document;
  check(await until(() => rowOf(d, 'Docs')), 'the panel shows the top folder Docs');
  check(!rowOf(d, 'Deep'), 'its subfolder is not drawn before the click');
  check(!d.querySelector('#view .wkside') && d.querySelector('#view .wkbar #wk-q') && d.querySelector('#view .wkbar [data-wk="new"]') && d.querySelector('#view .wkbar [data-wk="amenu"]'), 'no tree column; search, New page and the space menu in the bar');
  check(d.querySelector('#side .sbbi[data-go="wiki"].on') && [...d.querySelectorAll('#view .wkitem')].some(a => /Top page/.test(a.textContent)), '"All pages": the top of the space with its page');
  rowOf(d, 'Docs').querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Deep')), 'the arrow opens Docs: Deep appears');
  check(w.eval(`(LS.get('sbbOpen', []) || []).includes('wk:private:docs') && sbb_treeAnyOpen()`), 'open per device in sbbOpen, sbb_treeAnyOpen() true');
  rowOf(d, 'Docs').querySelector('.sbbtn').click();
  check(await until(() => w.location.hash === '#wiki/d/Docs' && /^Docs$/.test(d.querySelector('#view .wkfolder h2')?.textContent || '')), 'Docs opens as a list ' + w.location.hash);
  check(/Private/.test(d.querySelector('#view .wkcrumbs')?.textContent || ''), 'the path on top starts at the space');
  check([...d.querySelectorAll('#view .wkdrow')].some(a => /Deep/.test(a.textContent)) && [...d.querySelectorAll('#view .wkitem')].some(a => /Guide/.test(a.textContent)), 'the list: the subfolder Deep and the page Guide');
  check(rowOf(d, 'Docs')?.classList.contains('on'), 'the open folder in the accent');
  w.eval('sbb_treeCloseAll(); renderSide()');
  check(!rowOf(d, 'Deep') && !w.eval('sbb_treeAnyOpen()'), '"Collapse all" (sbb_treeCloseAll) closes the folders');
  w.close();

  // ================= #2621 file store: Files with its folders, lazily; dragging a file onto a folder of the panel moves it
  w = await boot({user: 'frida', hash: 'ablage'}); d = w.document;
  check(await until(() => rowOf(d, 'Invoices') && rowOf(d, 'Archive')), 'the panel shows the top folders under Files');
  check(/Files/.test(d.querySelector('#side [data-sbbpart="ablage"]')?.textContent || ''), 'the part Files stays an entry');
  check(!d.querySelector('#view .abspaces') && d.querySelector('#side [data-absp="trash"]'), 'no space column; the trash is in the panel');
  check(!rowOf(d, 'Q1'), 'the subfolder Q1 is not loaded before the click');
  rowOf(d, 'Invoices').querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Q1')), 'the arrow loads and shows Q1');
  rowOf(d, 'Q1').querySelector('.sbbtn').click();
  check(await until(() => w.location.hash === '#ablage/' + Q1 && /Invoices/.test(d.querySelector('#view .abcrumbs')?.textContent || '') && rowOf(d, 'Q1')?.classList.contains('on')), 'Q1 opens with its path on top, its row in the accent');
  w.location.hash = 'ablage';
  const fr = await until(() => d.querySelector(`.abrow[data-abid="${NOTE}"]`));
  check(fr, 'the file at the top of My files');
  if (fr) {
    dnd(w, fr, 'dragstart');
    const t = rowOf(d, 'Archive'), ov = dnd(w, t, 'dragover');
    check(ov.defaultPrevented && t.classList.contains('abdrop'), 'the folder in the panel takes the file');
    dnd(w, t, 'drop');
    check(await until(async () => (await call('GET', `/api/files/nodes/${NOTE}`)).parent_id === ARC), 'the drop moved the file into Archive');
    check(await until(() => !d.querySelector(`.abrow[data-abid="${NOTE}"]`)), 'it left the open list');
  }
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
