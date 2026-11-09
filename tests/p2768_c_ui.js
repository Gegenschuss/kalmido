// 2.768.0 (#4888) part C UI tests, own container (start.sh; P2768C_NOSTART=1 / KMT_NOSTART: the container runs already), jsdom
// kalmido-suite: fresh
// freelancer-matrix: files, docs (frida has no organisation, as tests/freelancer_fixture.py). Invented names and files only.
// - the "+" at the head of the panel's tree makes a new folder at the top of the space (askPrompt, answered by w.prompt)
// - All documents: a document card is draggable (a mouse) and dropped on a folder of the panel it moves there (no upload)
// - a choice of two document cards dragged by one of them onto a folder of the panel moves both, ONE undo brings both back
// - a folder shown as cards: a file card dragged onto a folder card moves it; a dragged choice does not take one of its own
//   folders as target
// - a reader's cards are not draggable; on a touch screen the cards carry the finger's mark (data-abmv), no browser drag
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until, histAdded} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2768C_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const up = async (ck, url, field, name, text, extra = {}) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  fd.append(field, new Blob([text], {type: 'text/plain'}), name);
  return (await fetch(B + url, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd})).json().catch(() => ({}));
};
// one dataTransfer for the whole drag (as the browser's): setData adds its type, the drop reads it back
const mkDT = (types = [], files = []) => { const data = {}; return {types: [...types], files, effectAllowed: '', dropEffect: '', setData(k, v) { data[k] = v; if (!this.types.includes(k)) this.types.push(k); }, getData: k => data[k] || '', setDragImage() {}}; };
const dnd = (w, el, type, dt) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = dt; el.dispatchEvent(e); return e; };
const card = (d, id) => d.querySelector(`.dc-card [data-dcchk="${id}"]`)?.closest('.dc-card');
const ctrlClick = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ctrlKey: true}));
const count = d => d.querySelector('#ab-sbar .mcount')?.textContent || '';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call(AK, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const on = async ck => { const st = await call(ck, 'GET', '/api/state'); await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'private', features: [...new Set([...(st.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(',')}); };
  const FR = (await call(AK, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []})).id;
  const GR = (await call(AK, 'POST', '/api/users', {username: 'greta', display_name: 'Greta Reader', password: 'password123', email: 'greta@example.com', orgs: []})).id;
  const CK = await login('frida'); await on(CK);
  const CG = await login('greta'); await on(CG);
  check(FR && GR && ((await call(CK, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida (and greta) have no organisation');
  const D0 = ((await up(CK, 'api/docs', 'files', 'otter-letter.txt', 'An invented letter of the otter club', {ws: 'private'})).ids || [])[0];
  const ROOT = (await call(CK, 'GET', `/api/files/nodes/${D0}`)).parent_id;
  const D1 = ((await up(CK, 'api/files/upload', 'file', 'otter-two.txt', 'Another invented otter letter', {parent_id: String(ROOT)})).items || [])[0]?.id;
  const ARC = (await call(CK, 'POST', '/api/files/folders', {space: 'private', name: 'Otter archive'})).id;
  const GARDEN = (await call(CK, 'POST', '/api/files/folders', {space: 'private', name: 'Pond'})).id;
  const SUB = (await call(CK, 'POST', '/api/files/folders', {parent_id: GARDEN, name: 'Reeds'})).id;
  const P = ((await up(CK, 'api/files/upload', 'file', 'lilies.txt', 'Water lilies', {parent_id: String(GARDEN)})).items || [])[0]?.id;
  await call(CK, 'PATCH', '/api/settings', {set_delta: {ab_cards: {add: ['n:' + GARDEN]}}});
  check(D0 && ROOT && D1 && ARC && GARDEN && SUB && P, 'setup: documents, folders, a file');
  check(await until(async () => (await call(CK, 'GET', `/api/docs/${D1}`)).http === 200), 'setup: the second file is a document');
  const parent = async id => (await call(CK, 'GET', `/api/files/nodes/${id}`)).parent_id;

  // ================= the "+" at the head of the tree
  let w = await boot({user: 'frida', hash: 'ablage/docs'}), d = w.document;
  const plus = await until(() => d.querySelector('#side .abthead [data-abtadd]'));
  check(plus && plus.dataset.abtadd === 'private', 'the head of the tree has "+" for the private space');
  w.prompt = () => 'Fresh otters';
  plus?.click();
  check(await until(async () => ((await call(CK, 'GET', '/api/files?space=private')).items || []).some(n => n.kind === 'folder' && n.name === 'Fresh otters')), 'the "+" made a folder at the top of the space');

  // ================= All documents: a card onto a folder of the panel
  check(await until(() => card(d, D0) && card(d, D1)), 'All documents shows both documents');
  check(card(d, D0)?.getAttribute('draggable') === 'true', 'a document card is draggable (a mouse)');
  w.eval('window.__up = []; ab_upload = (fs, t) => { window.__up.push(t ?? null); };');
  const side = await until(() => d.querySelector(`#side [data-abdrop="${ARC}"]`));
  if (check(side, 'the panel shows the archive folder')) {
    const dt = mkDT(['Files'], [new w.File(['x'], 'otter-letter.txt', {type: 'text/plain'})]);
    dnd(w, card(d, D0), 'dragstart', dt);
    check(dt.getData('application/x-kalmido-node') === String(D0), 'the drag carries the document\'s node');
    check(dnd(w, side, 'dragover', dt).defaultPrevented, 'the panel folder takes the document card');
    dnd(w, side, 'drop', dt); dnd(w, d.body, 'dragend', dt);
    check(await until(async () => await parent(D0) === ARC, 60), 'the document moved into the archive');
    check(!w.__up.length, 'nothing was uploaded');
    await call(CK, 'PATCH', `/api/files/nodes/${D0}`, {parent_id: ROOT});
  }
  w.close();

  // ================= a choice of two dragged by one: both move, ONE undo
  w = await boot({user: 'frida', hash: 'ablage/docs'}); d = w.document;
  check(await until(() => card(d, D0) && card(d, D1)), 'All documents again');
  ctrlClick(w, card(d, D0).querySelector('[data-dco]'));
  await until(() => /1 selected/.test(count(d)));
  card(d, D1).querySelector('[data-dcchk]').click();
  check(await until(() => /2 selected/.test(count(d))), 'two documents chosen');
  const side2 = await until(() => d.querySelector(`#side [data-abdrop="${ARC}"]`));
  if (side2 && card(d, D1)) {
    const n0 = w.eval('HIST.undo.length');
    const dt = mkDT();
    dnd(w, card(d, D1), 'dragstart', dt);
    const ids = dt.getData('application/x-kalmido-node').split(',').map(Number).sort();
    check(ids.length === 2 && ids.includes(D0) && ids.includes(D1), 'the drag carries the whole choice ' + ids);
    check(dnd(w, side2, 'dragover', dt).defaultPrevented, 'the panel folder takes the choice');
    dnd(w, side2, 'drop', dt); dnd(w, d.body, 'dragend', dt);
    check(await until(async () => await parent(D0) === ARC && await parent(D1) === ARC, 60), 'both documents moved into the archive');
    check(await histAdded(w, n0), 'ONE undo step for both');
    await w.eval(`histStep('undo')`);
    check(await until(async () => await parent(D0) === ROOT && await parent(D1) === ROOT, 60), 'Undo brings both back');
  }
  w.close();

  // ================= a folder as cards: a file card onto a folder card; a chosen folder is no target of its own choice
  w = await boot({user: 'frida', hash: 'ablage/' + GARDEN}); d = w.document;
  check(await until(() => card(d, P) && card(d, SUB)), 'Pond shows its file and subfolder as cards');
  const subT = () => d.querySelector(`#view .abview [data-abdrop="${SUB}"]`);
  if (card(d, P) && subT()) {
    card(d, P).querySelector('[data-dcchk]').click(); card(d, SUB).querySelector('[data-dcchk]').click();
    check(await until(() => /2 selected/.test(count(d))), 'file and subfolder chosen');
    const dt = mkDT();
    dnd(w, card(d, P), 'dragstart', dt);
    check(!dnd(w, subT(), 'dragover', dt).defaultPrevented, 'a folder of the dragged choice does not take it');
    dnd(w, d.body, 'dragend', dt);
    d.querySelector('#ab-sbar [data-absel="close"]')?.click();
    await until(() => !d.querySelector('#ab-sbar'));
    const dt2 = mkDT();
    dnd(w, card(d, P), 'dragstart', dt2);
    check(dnd(w, subT(), 'dragover', dt2).defaultPrevented, 'the folder card takes the file card');
    dnd(w, subT(), 'drop', dt2); dnd(w, d.body, 'dragend', dt2);
    check(await until(async () => await parent(P) === SUB, 60), 'the file moved into the subfolder');
  }
  w.close();

  // ================= a reader: no drag; a touch screen: the finger's mark
  check((await call(CK, 'POST', `/api/files/nodes/${GARDEN}/shares`, {user_id: GR, role: 'view'})).http < 300, 'Pond shared with greta for reading');
  await call(CG, 'PATCH', '/api/settings', {set_delta: {ab_cards: {add: ['n:' + GARDEN]}}});
  w = await boot({user: 'greta', hash: 'ablage/' + GARDEN}); d = w.document;
  check(await until(() => card(d, SUB)), 'greta sees Pond as cards');
  check(card(d, SUB) && !card(d, SUB).hasAttribute('draggable') && !card(d, SUB).hasAttribute('data-abmv'), 'a reader\'s card is not draggable');
  w.close();
  w = await boot({user: 'frida', hash: 'ablage/' + GARDEN, mobile: true, media: {'(hover: none)': true, '(hover: hover)': false}}); d = w.document;
  if (await until(() => card(d, SUB))) {
    const c = card(d, SUB);
    check(c.dataset.abmv === '1' && !c.hasAttribute('draggable'), 'a touch screen: the card carries the finger\'s mark, no browser drag');
  } else check(false, 'Pond on a touch screen');
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
