// kalmido-suite: fresh
// 2.752.0 (#4887) UI tests: files and documents are ONE area "Files" with ONE folder tree. Own container (start.sh), jsdom
// (computer and phone) + Firefox for the pictures and the widths (1440, 390, 320). Invented names and files only.
// - the panel: one tree (the documents folder stands once), below it "All documents", "To review", then Shared / Trash; no
//   fold node "Documents" with a second tree of the same folders
// - a folder with recognition shows the documents' view (bar: search, filter, sort, Add, Scan; its subfolder as a card
//   first; only its own documents; a search takes the subfolders along: ?under=), a folder without recognition its list
// - the old links #docs, #docs/review, #docs/v/<id>, #docs/<id> lead to #ablage/... (replaced, no extra history entry)
// - #ablage/<id> of a file opens its document view after a new start (reload); Close leads into its folder; Back from a
//   document opened in the folder leads back to the folder
// - a reader (view rights on a shared folder): the documents' view without Add / Scan / New folder
// - a phone: the spaces with "All documents" / "To review" on top of a folder; the documents' list keeps its switch
// freelancer-matrix: files (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2752_a_files_ui', check, shots: 'P2752A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2752A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const up = async (ck, url, field, name, text, extra = {}) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  fd.append(field, new Blob([text], {type: 'text/plain'}), name);
  return (await fetch(B + url, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd})).json().catch(() => ({}));
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const on = async ck => { const st = await call(ck, 'GET', '/api/state'); const feats = [...new Set([...(st.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(','); await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'}); };
  await on(CA);
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Reader', password: 'password123', email: 'bob@example.com'})).id;
  check(BOB, 'setup: bob');
  const CB = await login('bob'); await on(CB);
  const DOC = ((await up(CA, 'api/docs', 'files', 'letter-otter.txt', 'Letter of an invented otter club', {ws: 'private'})).ids || [])[0];
  check(DOC, 'setup: a document (makes the documents folder)');
  const ROOT = (await call(CA, 'GET', `/api/files/nodes/${DOC}`)).parent_id;
  const SUB = (await call(CA, 'POST', '/api/files/folders', {parent_id: ROOT, name: 'Otter archive'})).id;
  const DOC2 = ((await up(CA, 'api/files/upload', 'file', 'old-otter.txt', 'An older invented otter letter', {parent_id: String(SUB)})).items || [])[0]?.id;
  const PLAIN = (await call(CA, 'POST', '/api/files/folders', {space: 'private', name: 'Garden'})).id;
  const FILE = ((await up(CA, 'api/files/upload', 'file', 'seeds.txt', 'Tomatoes, beans', {parent_id: String(PLAIN)})).items || [])[0]?.id;
  check(ROOT && SUB && DOC2 && PLAIN && FILE, 'setup: the documents folder with a subfolder, a plain folder with a file');
  check(await until(async () => (await call(CA, 'GET', `/api/docs/${DOC2}`)).http === 200), 'setup: the file of the subfolder is a document (recognition inherited)');
  const VID = (await call(CA, 'POST', '/api/obj/docview', {title: 'Otter letters', query: 'q=otter', ws: 'private'})).id;
  check(VID, 'setup: a saved view');
  check((await call(CA, 'POST', `/api/files/nodes/${ROOT}/shares`, {user_id: BOB, role: 'view'})).http < 300, 'setup: the documents folder shared with bob (view)');

  // ================= a computer: one tree, the rows below it
  let w = await boot({user: 'alice', hash: 'ablage'}), d = w.document;
  check(await until(() => d.querySelector(`#side .sbbtree [data-go="ablage/${ROOT}"]`) && d.querySelector('#side .abfilt [data-go="ablage/docs"]')), 'the panel: the documents folder in the tree, All documents below it');
  check(d.querySelectorAll(`#side [data-go="ablage/${ROOT}"]`).length === 1, 'the documents folder stands once in the panel (' + d.querySelectorAll(`#side [data-go="ablage/${ROOT}"]`).length + ')');
  check(!d.querySelector('#side [data-k="ab:docs"]') && !d.querySelector('#side .dc-ptree') && !d.querySelector('#side [data-dcunder]'), 'no fold node "Documents", no second tree');
  const order = [...d.querySelectorAll('#side .sbbp [data-go]')].map(b => b.dataset.go);
  const iDocs = order.indexOf('ablage/docs'), iRev = order.indexOf('ablage/review'), iTree = order.indexOf('ablage/' + ROOT), iTrash = order.findIndex(g => /trash/.test(g) || g === 'ablage');
  check(iTree >= 0 && iDocs > iTree && iRev === iDocs + 1, 'below the tree: All documents, then To review ' + JSON.stringify(order));
  check(/All documents/.test(d.querySelector('#side [data-go="ablage/docs"]').textContent) && /To review/.test(d.querySelector('#side [data-go="ablage/review"]').textContent), 'the rows are named');
  check(d.querySelector('#side .abrest [data-absp="trash"]') && d.querySelector('#side .abfilt').compareDocumentPosition(d.querySelector('#side .abrest')) & 4, 'Shared with me / the trash after the documents\' rows ' + iTrash);
  check(await until(() => d.querySelector(`#side [data-go="ablage/v/${VID}"]`)), 'the saved view below To review');
  check(w.eval(`tr(mg_area('ablage')[2])`) === 'Files' && !d.querySelector('#view .mgtabs'), 'the area is called "Files", no tabs');

  // a folder with recognition: the documents' view
  w.location.hash = '#ablage/' + ROOT;
  check(await until(() => d.querySelector(`.abview .dc-infold [data-dco="${DOC}"]`)), 'a folder with recognition: the documents\' view with its document');
  check(d.querySelector('.abview .dc-infold .dc-bar #dc-q') && d.querySelector('.dc-infold [data-dc="more"]') && d.querySelector('.dc-infold .dc-sortb') && d.querySelector('.dc-infold [data-ab="upload"]') && d.querySelector('.dc-infold [data-ab="scan"]'), '... its bar: search, filter, sort, Add, Scan');
  check(!d.querySelector('.dc-infold .dc-seg') && !d.querySelector('.abview .ablist'), '... no switch All | To review, no list');
  const sub = d.querySelector(`.dc-infold .abcards [data-ab="open"][data-id="${SUB}"]`), first = d.querySelector('.dc-infold .dc-card');
  check(sub && first && first.contains(sub), '... its subfolder as the first card');
  check(await until(() => w.eval(`!DC.loading && DC.docs && DC.docs.some(x => x.id === ${DOC}) && !DC.docs.some(x => x.id === ${DOC2})`)), '... only its own documents (the subfolder\'s one not)');
  check(w.eval(`dc_params().getAll('folder').join()`) === String(ROOT) && !w.eval(`dc_params().get('under')`), '... asked for as ?folder=');
  w.eval(`DC.q = 'otter'`);
  check(w.eval(`dc_params().get('under')`) === String(ROOT) && !w.eval(`dc_params().getAll('folder').length`), 'a search in the folder takes the subfolders along (?under=)');
  w.eval(`DC.q = ''`);
  check(d.querySelector(`.dc-infold [data-dco="${DOC}"]`)?.closest('li')?.querySelector('[data-ab="menu"]'), 'a document card keeps the file store\'s menu');
  // Back from a document opened in the folder: the folder again
  d.querySelector(`.dc-infold [data-dco="${DOC}"]`).click();
  check(await until(() => w.location.hash === `#ablage/${DOC}` && w.eval('S.route.mod') === 'docs' && d.querySelector('.dv-view')), 'a card opens the document view at #ablage/<id>');
  w.history.back();
  check(await until(() => w.location.hash === `#ablage/${ROOT}` && d.querySelector(`.dc-infold [data-dco="${DOC}"]`) && !d.querySelector('.dv-view')), 'Back: the folder with its documents again');
  // a folder without recognition: its list
  w.location.hash = '#ablage/' + PLAIN;
  check(await until(() => d.querySelector(`.abview .ablist [data-abid="${FILE}"]`) && !d.querySelector('.dc-infold')), 'a folder without recognition: its list');

  // the four old links
  const hist = w.history.length;
  w.location.hash = '#docs';
  check(await until(() => w.location.hash === '#ablage/docs' && w.eval('S.route.mod') === 'docs' && d.querySelector(`.dc-view [data-dco="${DOC}"]`) && d.querySelector('#side [data-go="ablage/docs"][aria-current="page"]')), '#docs -> #ablage/docs (All documents, marked)');
  w.location.hash = '#docs/review';
  check(await until(() => w.location.hash === '#ablage/review' && w.eval('DC.f.review') && d.querySelector('#side [data-go="ablage/review"][aria-current="page"]')), '#docs/review -> #ablage/review');
  w.location.hash = '#docs/v/' + VID;
  check(await until(() => w.location.hash === '#ablage/v/' + VID && w.eval(`DC.dv === ${VID}`) && d.querySelector(`#side [data-go="ablage/v/${VID}"][aria-current="page"]`)), '#docs/v/<id> -> #ablage/v/<id> (the view)');
  w.location.hash = '#docs/' + DOC;
  check(await until(() => w.location.hash === '#ablage/' + DOC && d.querySelector(`.dv-view .dc-body[data-id="${DOC}"]`)), '#docs/<id> -> #ablage/<id> (the document view)');
  check(w.history.length <= hist + 4, 'the old address is replaced, not kept as an extra entry (' + (w.history.length - hist) + ')');
  w.close();

  // a new start on the address of a file: its document view; Close leads into its folder
  w = await boot({user: 'alice', hash: 'ablage/' + DOC}); d = w.document;
  check(await until(() => d.querySelector(`.dv-view .dc-body[data-id="${DOC}"]`) && w.location.hash === '#ablage/' + DOC, 80), 'reload of #ablage/<id of a file>: the document view');
  d.querySelector('.dv-view [data-dc="close"]')?.click();
  check(await until(() => w.location.hash === '#ablage/' + ROOT && d.querySelector('.dc-infold')), 'Close without a way back: its folder');
  w.close();
  w = await boot({user: 'alice', hash: 'ablage/' + FILE}); d = w.document;
  check(await until(() => d.querySelector(`.dv-view .dc-body[data-id="${FILE}"]`), 80), 'reload of a plain file: the same view');
  w.close();

  // ================= a reader: no writing buttons
  w = await boot({user: 'bob', hash: 'ablage/' + ROOT}); d = w.document;
  check(await until(() => d.querySelector(`.dc-infold [data-dco="${DOC}"]`), 80), 'bob (view): the documents\' view of the shared folder');
  check(!d.querySelector('.dc-infold [data-ab="upload"]') && !d.querySelector('.dc-infold [data-ab="scan"]') && !d.querySelector('.abview [data-ab="new-folder"]'), 'bob: no Add, Scan, New folder');
  w.close();
  check((await call(CB, 'GET', `/api/docs/${DOC}`)).http === 200 && (await call(CB, 'PATCH', `/api/files/nodes/${DOC}`, {name: 'renamed.txt'})).http >= 400, 'bob: reads the document, cannot rename it (rights unchanged)');

  // ================= a phone
  w = await boot({user: 'alice', hash: 'ablage/' + ROOT, mobile: true}); d = w.document;
  check(await until(() => d.querySelector('.abspaces .abfilt[data-go="ablage/docs"]') && d.querySelector('.abspaces .abfilt[data-go="ablage/review"]') && d.querySelector(`.dc-infold [data-dco="${DOC}"]`)), 'phone: All documents / To review on top of the folder\'s documents');
  w.location.hash = '#ablage/docs';
  check(await until(() => d.querySelector('.dc-view .abdnav [data-go="ablage"]') && d.querySelector('.dc-view .dc-seg')), 'phone: the list keeps its switch, the spaces lead back');
  check(d.querySelectorAll('.dc-view [data-dc="review"], .dc-view [data-go="ablage/review"]').length === 1, 'phone: "To review" once (#4472)');
  check(!d.querySelector('.dc-view .abdnav [data-go="docs"]'), 'phone: no switch Files | Documents');
  w.close();

  // ================= pictures and widths
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, 'Firefox: login');
    const wait = async (js, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    for (const [wd, h, tag] of [[1440, 900, '1440'], [390, 844, '390'], [320, 640, '320']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: h}});
      await o.nav(B + '#ablage/' + ROOT);
      check(await wait(`!!document.querySelector('.abview .dc-infold [data-dco="${DOC}"]')`), `${tag}: the documents' view of the folder`);
      await sleep(500);
      check(await ev(`document.documentElement.scrollWidth <= innerWidth + 1`), `${tag}: nothing sticks out`);
      await shot(`p2752-a-${tag}-folder.png`);
      await o.nav(B + '#docs');
      check(await wait(`location.hash === '#ablage/docs' && !!document.querySelector('.dc-view [data-dco]')`), `${tag}: #docs leads to All documents`);
      await sleep(400);
      check(await ev(`document.documentElement.scrollWidth <= innerWidth + 1`), `${tag}: All documents: nothing sticks out`);
      await shot(`p2752-a-${tag}-all.png`);
    }
  });

  console.log(`p2752_a_files_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
