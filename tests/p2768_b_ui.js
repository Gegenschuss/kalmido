// 2.768.0 UI test, part B (#4888 point 3: ONE detail sheet = the document view, also for plain files): own container (start.sh), jsdom.
// kalmido-suite: fresh
// Invented data only. P2768B_NOSTART=1 = the container runs.
// - "Details and history" of a file opens the document view on its tab History (not the old dialog): the versions (each one to
//   view, to download with ?v=, to restore with the right to write), on top "Upload a new version…", the history, "Mentioned in"
//   with the knowledge page that links the file
// - restoring v1 = a new version with v1's content, ONE undo step (undo: the version before is the newest again); the view
//   (its tab, its download) follows
// - a new version through the fixed input of the tab (chosen or dropped onto the window): ONE undo step too
// - a version opens in the viewer of its kind (text: the text view, its name with "· v1")
// - the view's Actions: Upload a new version… / Move to… / Rename… (a plain file); Rename renames and the title follows
// - a folder's "Details and history" stays the dialog (no versions there)
// - a reader (a view share) sees the tab History with the versions to view / download, no Restore, no upload, no actions that write
// P4: alice works without an organisation (private files): the person without an organisation (freelancer-matrix: files)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2768B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const FEAT = 'cal,collab,comments,contacts,files,docs,wiki';
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const content = async (id, v) => (await fetch(B + `api/files/nodes/${id}/content?dl=1${v ? '&v=' + v : ''}`, {headers: {'X-Requested-With': 'kalmido', Cookie: CK}})).text();
const until = async (fn, n = 75) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
async function upload(name, text, parent) {
  const fd = new FormData();
  fd.append('file', new Blob([text], {type: 'text/plain'}), name);
  fd.append('parent_id', String(parent));
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return ((await r.json()).items || [])[0];
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Example', password: 'password123'})).id;
  const FID = (await call('POST', '/api/files/folders', {name: 'Kunde Nord', space: 'private'})).id;
  const OTHER = (await call('POST', '/api/files/folders', {name: 'Archiv', space: 'private'})).id;
  await upload('note.txt', 'first', FID);
  const NID = (await upload('note.txt', 'second!', FID))?.id;
  let node = await call('GET', `/api/files/nodes/${NID}`);
  check(NID && node.version === 2 && node.versions?.length === 2, 'a plain text file with two versions ' + JSON.stringify([NID, node.version]));
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Kundenmappe', body: `Siehe [[datei:${NID}]].`})).id;
  check((await call('GET', `/api/wiki/refs?file=${NID}`)).pages?.some(p => p.id === PG), 'the knowledge page links the file (server)');
  check((await call('POST', `/api/files/nodes/${NID}/shares`, {user_id: BOB, role: 'view'})).status < 300, 'bob may read the file');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEAT}, await login('bob'));

  // ================= alice: "Details and history" of the file -> the view, tab History
  const w = await boot({user: 'alice', hash: `ablage/${FID}`}), d = w.document;
  check(await until(() => d.querySelector(`.abrow[data-abid="${NID}"]`) && w.eval('typeof ab_detailsOf === "function"')), 'the folder lists the file');
  const item = (n, label) => w.eval(`ab_menuItems(${JSON.stringify(n)}).filter(Boolean).find(x => x.label === ${JSON.stringify(label)})`);
  item(w.eval(`ab_item(${NID})`), 'Details and history').fn();
  const hist = () => d.querySelector('.dv-view #dv-p-hist');
  check(await until(() => w.location.hash === `#ablage/${NID}` && hist() && !hist().hidden && hist().querySelectorAll('.abvrow').length === 2), '"Details and history" of a file: the document view on its tab History ' + w.location.hash);
  check(!d.querySelector('.abdlg') && d.querySelector('.dv-view [data-dvtab="hist"]')?.getAttribute('aria-selected') === 'true', '... no dialog, the tab History selected');
  const row = no => hist().querySelector(`.abvrow[data-abvno="${no}"]`);
  check(row(1)?.querySelector('[data-abv="1"]') && !row(2)?.querySelector('[data-abv]') && /current/.test(row(2)?.textContent || ''), '... v1 restorable, v2 marked as the current one without Restore');
  check(/[?&]v=1(&|$)/.test(row(1)?.querySelector('a[download]')?.getAttribute('href') || '') && /dl=1/.test(row(1).querySelector('a[download]').getAttribute('href')), '... the download of v1 asks for ?v=1 ' + row(1)?.querySelector('a[download]')?.getAttribute('href'));
  check(row(1)?.querySelector('[data-abvv="1"]'), '... each version can be viewed');
  check(hist().querySelector('#abd-verfile[type="file"]') && hist().querySelector('[data-abd="ver"]'), '... on top "Upload a new version…" with its fixed input');
  check(/uploaded/.test(hist().querySelector('.ablog')?.textContent || ''), '... the history with its entries ' + (hist().querySelector('.ablog')?.textContent || '').slice(0, 120));
  check(await until(() => hist().querySelector(`.abrefs .wkmen a[href="#wiki/${PG}"]`)), '... "Mentioned in" with the knowledge page');

  // view a version: the text view with its name
  click(w, row(1).querySelector('[data-abvv="1"]'));
  check(await until(() => /note\.txt · v1/.test(d.querySelector('.lightbox')?.textContent || '')), 'view v1: the viewer of its kind, named "· v1" ' + (d.querySelector('.lightbox')?.textContent || '').slice(0, 80));
  d.querySelector('.lightbox')?.remove();

  // restore v1: ONE undo step
  const u0 = w.eval('HIST.undo.length');
  click(w, row(1).querySelector('[data-abv="1"]'));
  check(await until(async () => (await call('GET', `/api/files/nodes/${NID}`)).version === 3), 'Restore v1: the server has v3');
  check(await content(NID) === 'first', '... with the content of v1');
  check(await until(() => hist().querySelectorAll('.abvrow').length === 3 && row(3) && /current/.test(row(3).textContent)), '... the tab follows: three versions, v3 the current one');
  check(w.eval('HIST.undo.length') === u0 + 1 && w.eval('HIST.undo[HIST.undo.length - 1].label') === 'Restore version 1', '... ONE undo step "Restore version 1"');
  check(/v=3/.test(d.querySelector('.dv-view .dv-dl')?.getAttribute('href') || ''), '... the download of the view gets the new version ' + d.querySelector('.dv-view .dv-dl')?.getAttribute('href'));
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/files/nodes/${NID}`)).version === 4) && await content(NID) === 'second!', 'Undo: the version before (v2) is the newest again (as v4)');
  check(await until(() => hist().querySelectorAll('.abvrow').length === 4), '... the tab follows');

  // a new version through the fixed input of the tab
  const inp = hist().querySelector('#abd-verfile');
  Object.defineProperty(inp, 'files', {value: [new w.File(['third one'], 'note.txt', {type: 'text/plain'})], configurable: true});
  inp.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', `/api/files/nodes/${NID}`)).version === 5) && await content(NID) === 'third one', 'a new version through the tab: v5');
  check(await until(() => hist().querySelectorAll('.abvrow').length === 5), '... the tab follows');
  check(/New version of “note\.txt”/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), '... ONE undo step ' + w.eval('HIST.undo[HIST.undo.length - 1].label'));
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/files/nodes/${NID}`)).version === 6) && await content(NID) === 'second!', 'Undo of the new version: v4 is the newest again (as v6)');

  // the view's actions
  const acts = () => [...d.querySelectorAll('.dv-view .dv-amenu [data-dc]')].map(b => b.dataset.dc);
  check(['dvnewver', 'dvmove', 'dvren'].every(a => acts().includes(a)), 'Actions: Upload a new version… / Move to… / Rename… ' + acts().join());
  w.prompt = () => 'note-renamed.txt';
  click(w, d.querySelector('.dv-view [data-dc="dvren"]'));
  check(await until(async () => (await call('GET', `/api/files/nodes/${NID}`)).name === 'note-renamed.txt'), 'Rename… from the view renames the file');
  check(await until(() => d.querySelector('.dv-view #dc-h')?.textContent === 'note-renamed.txt'), '... the title of the view follows');
  click(w, d.querySelector('.dv-view [data-dc="dvmove"]'));
  check(await until(() => [...d.querySelectorAll('#pop button, #pop [role="menuitem"]')].some(b => /Archiv/.test(b.textContent))), 'Move to… from the view: the folders to choose (Archiv)');
  const tgt = [...d.querySelectorAll('#pop button, #pop [role="menuitem"]')].find(b => /Archiv/.test(b.textContent));
  if (tgt) click(w, tgt);
  check(await until(async () => (await call('GET', `/api/files/nodes/${NID}`)).parent_id === OTHER), '... the file moves into Archiv');

  // a folder: the dialog stays
  w.eval('dcv_close()');
  await until(() => !d.querySelector('.dv-view'));
  w.eval(`go('ablage/${OTHER}')`);
  await until(() => d.querySelector(`.abrow[data-abid="${NID}"]`));
  w.eval(`ab_details(${FID})`);
  check(await until(() => d.querySelector('.abdlg')) && !d.querySelector('.abdlg .abvrow') && !d.querySelector('.dv-view'), 'a folder: "Details and history" stays the dialog (no versions)');
  check(d.querySelector('.abdlg')?.textContent.includes('Kunde Nord'), '... of that folder');
  d.querySelector('.abdlg [data-m="close"]')?.click();
  w.close();

  // ================= bob, a reader: the tab History without the buttons that write
  const wb = await boot({user: 'bob', hash: `ablage/${NID}`}), db = wb.document;
  check(await until(() => db.querySelector('.dv-view [data-dvtab="hist"]')), 'a reader: the view has the tab History');
  click(wb, db.querySelector('.dv-view [data-dvtab="hist"]'));
  const bh = () => db.querySelector('.dv-view #dv-p-hist');
  check(await until(() => bh()?.querySelectorAll('.abvrow').length === 6), '... the versions ' + (bh()?.querySelectorAll('.abvrow').length));
  check(bh().querySelector('.abvrow a[download]') && bh().querySelector('[data-abvv]'), '... to download and to view');
  check(!bh().querySelector('[data-abv]') && !bh().querySelector('#abd-verfile') && !bh().querySelector('[data-abd="ver"]'), '... no Restore, no upload');
  check(!db.querySelector('.dv-view [data-dc="dvnewver"], .dv-view [data-dc="dvmove"], .dv-view [data-dc="dvren"], .dv-view [data-dc="del"]'), '... no actions that write');
  wb.close();

  console.log(`p2768_b_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
