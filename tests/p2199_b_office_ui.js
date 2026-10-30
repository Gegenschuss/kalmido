// 2.199.0 B (#2742) UI tests: folders for the office. Own container (start.sh), jsdom, invented names only.
// - documents (a computer): the panel shows the whole folder tree below the documents folder (ns 'dc', draggable, a menu);
//   a subfolder picked = the list shows its documents (?under=), a removable line names the path; the document's folder
//   field is a pick with the path ("Documents / Client Alpha / 2026") and offers a new subfolder of the current one
// - the office (a computer): 2.351.0 (#3312) the area Quotes & invoices is a tree node (no group "Folders", no automatic
//   groups); the year is a filter at the top of the list; the document's More menu files it into a folder (a reference node)
// - a phone: the documents' folders in the drawer, held to drag (data-sbbdrag), a menu
// freelancer-matrix: n/a (no new route here; alice's personal office without an organisation is the freelancer case, the
// routes run in p2199_b_office_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2199B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent);
const openRow = async (w, d, txt) => { const r = rowOf(d, txt); const a = r?.querySelector('[data-act="sbb-tree"]'); if (a && !a.dataset.open) a.click(); return r; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'docs', 'office', 'clients'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  // a document in the private documents folder, then into Client Alpha / 2026 (the path makes both folders)
  const fd = new FormData();
  fd.append('ws', 'private');
  fd.append('files', new Blob(['Contract text of an invented client'], {type: 'text/plain'}), 'contract-alpha.txt');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}));
  const DOC = (up.ids || [])[0];
  check(DOC && (await call('PATCH', `/api/docs/${DOC}`, {folder: 'Client Alpha / 2026'})).http === 200, 'setup: a document in Client Alpha / 2026');
  const fd2 = new FormData();
  fd2.append('ws', 'private');
  fd2.append('files', new Blob(['Another letter'], {type: 'text/plain'}), 'letter-beta.txt');
  const DOC2 = ((await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd2})).json().catch(() => ({}))).ids || [])[0];
  check(DOC2, 'setup: a second document (no folder)');

  // ================= documents, a computer
  let w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  const CA = await until(() => rowOf(d, 'Client Alpha'));
  check(CA && CA.dataset.sbbns === 'dc' && CA.getAttribute('draggable') === 'true' && CA.dataset.sbbmenu === '1', 'documents: the panel shows the folder, draggable, with a menu');
  await openRow(w, d, 'Client Alpha');
  const Y = await until(() => rowOf(d, '2026'));
  check(Y && Y.dataset.sbbpar === 'n:' + CA?.dataset.sbbid, 'documents: its subfolder below it (any depth)');
  Y?.querySelector('.sbbtn')?.click();
  check(await until(() => /Documents \/ Client Alpha \/ 2026/.test(d.querySelector('.dc-under')?.textContent || '')), 'documents: the picked folder named with its path');
  check(await until(() => d.querySelectorAll('.dc-grid [data-dco]').length === 1 && d.querySelector(`.dc-grid [data-dco="${DOC}"]`)), 'documents: only the folder\'s document is listed');
  d.querySelector('[data-dc="under-off"]')?.click();
  check(await until(() => d.querySelectorAll('.dc-grid [data-dco]').length === 2 && !d.querySelector('.dc-under')), 'documents: the line removed = all documents again');
  w.location.hash = '#docs/' + DOC;
  const sel = await until(() => d.querySelector('#dc-folder'));
  const opts = sel ? [...sel.options].map(o => o.textContent) : [];
  check(opts.includes('Documents / Client Alpha / 2026') && opts.includes('Documents / Client Alpha') && sel.value === String(Y?.dataset.sbbid || ''),
    'documents: the folder field is a pick with the path ' + JSON.stringify(opts));
  check(opts.includes('New subfolder in 2026…'), 'documents: a new subfolder of the current one');
  w.close();

  // ================= the office, a computer
  const Q = await call('POST', '/api/office/docs', {kind: 'offer', project_title: 'Harbour film', items: [{title: 'Edit day', qty: 1, rate: 800}]});
  check(Q.http === 201, 'setup: a quotation in the personal office ' + JSON.stringify(Q).slice(0, 160));
  const OFF = (await call('POST', '/api/files/folders', {space: 'private', name: 'Office'})).id;
  w = await boot({user: 'alice', hash: 'office/offers'}); d = w.document;
  // 2.351.0 (#3312): the group "Folders" and the automatic groups By client / By project / By year are gone -- each document
  // area of the panel opens as a tree of its own (office_tree.js, p2351_a_officetree_ui.js); client / project / year are
  // filters at the top of the list
  const AR = await until(() => d.querySelector('#side .sbbt[data-sbbid="a:offers"]'));
  check(AR && AR.dataset.sbbns === 'oft' && AR.dataset.sbbmenu === '1' && !rowOf(d, 'By year') && !d.querySelector('#side [data-offolders]'),
    'office: Quotes & invoices is a tree node; no automatic groups, no group "Folders"');
  const yr = new Date().getFullYear().toString();
  const ysel = await until(() => d.querySelector('#ofd-flt-year'));
  check(ysel && [...ysel.options].some(o => o.value === yr), 'office: the year is a filter at the top of the list');
  if (ysel) { ysel.value = yr; ysel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(() => w.eval(`ofd_grpQs()`) === '&year=' + yr), 'office: the list asks for the year');
  w.location.hash = '#office/offers/' + Q.id;
  await until(() => w.eval(`OFD.doc && OFD.doc.id === ${Q.id}`));
  const labels = w.eval(`ofdMoreItems(OFD.doc, false).filter(Boolean).map(x => x.label || x)`);
  check(labels.includes('File in a folder…'), 'office: the More menu files the document ' + JSON.stringify(labels));
  w.eval(`ofd_fileDlg(OFD.doc)`);
  const mi = await until(() => menuItems(d).includes('Office') && menuItems(d));
  check(mi && mi.includes('Office'), 'office: the folders of the office\'s space ' + JSON.stringify(mi));
  [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.textContent.includes('Office'))?.click();
  check(await until(async () => (await call('GET', `/api/files/refs/office_doc/${Q.id}`)).node?.parent_id === OFF), 'office: filed into Office (a reference node)');
  w.close();

  // ================= a phone
  w = await boot({user: 'alice', hash: 'docs', mobile: true}); d = w.document;
  w.eval('renderSide()');
  const P = await until(() => rowOf(d, 'Client Alpha'));
  check(!P || (!P.hasAttribute('draggable') && P.dataset.sbbdrag === '1' && P.dataset.sbbmenu === '1'), 'phone: the documents\' folders are held to drag, with a menu');
  w.close();

  console.log(`p2199_b_office_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
