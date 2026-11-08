// 2.750.0 part A UI tests (#4879), own container (start.sh; P2750A_NOSTART=1: the container runs already), jsdom
// kalmido-suite: fresh
// freelancer-matrix: files, docs (frida has no organisation, as tests/freelancer_fixture.py).
// - #4879 a drag that begins in Kalmido never uploads: a card of the file store dragged by its picture (not the row) onto a
//   folder card moves the file (before: the browser's own drag carried a file, the drop uploaded it as a new version); dropped
//   on the empty view nothing happens; any other drag begun on the page (only the shared type of dropany.js) uploads nothing,
//   not in the panel either; a file from the computer (no dragstart) still uploads into the folder; the own folder takes nothing
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2750A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
// one dataTransfer for the whole drag (as the browser's): setData adds its type, the drop reads it back
const mkDT = (types = [], files = []) => { const data = {}; return {types: [...types], files, effectAllowed: '', dropEffect: '', setData(k, v) { data[k] = v; if (!this.types.includes(k)) this.types.push(k); }, getData: k => data[k] || '', setDragImage() {}}; };
const dnd = (w, el, type, dt) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = dt; el.dispatchEvent(e); return e; };
const upload = async (name, parent) => {
  const fd = new FormData(); fd.append('parent_id', String(parent)); fd.append('file', new Blob(['hello ' + name]), name);
  return ((await (await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).items || [])[0]?.id;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  CK = await login('frida');
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs'])].filter(Boolean).join(',')});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const PLAIN = (await call('POST', '/api/files/folders', {name: 'Plain', space: 'private'})).id;
  const SUB = (await call('POST', '/api/files/folders', {name: 'Sub', parent_id: PLAIN})).id;
  const ARC = (await call('POST', '/api/files/folders', {name: 'Archive', space: 'private'})).id;
  const NOTE = await upload('note.txt', PLAIN), NOTE2 = await upload('memo.txt', PLAIN);
  check(PLAIN && SUB && ARC && NOTE && NOTE2, 'folders Plain/Sub, Archive and two files in Plain');
  const v0 = (await call('GET', `/api/files/nodes/${NOTE}`)).version;
  // Plain as cards (the person's setting ab_cards, as abdocs.js abd_setCards)
  await call('PATCH', '/api/settings', {set_delta: {ab_cards: {add: ['n:' + PLAIN]}}});

  // ================= #4879
  let w = await boot({user: 'frida', hash: 'ablage/' + PLAIN}), d = w.document;
  const card = id => d.querySelector(`#view .abview .dc-card [data-ab="open"][data-id="${id}"]`);
  check(await until(() => card(NOTE) && card(SUB)), 'Plain shows its files and Sub as cards');
  w.eval('window.__up = []; ab_upload = (fs, t) => { window.__up.push(t ?? null); };');
  const subT = () => d.querySelector(`#view .abview [data-abdrop="${SUB}"]`);
  if (card(NOTE)) {
    // the picture of the card starts the drag (not a row): the browser has put the file in already
    const dt = mkDT(['Files'], [new w.File(['x'], 'note.txt', {type: 'text/plain'})]);
    dnd(w, card(NOTE).querySelector('.dc-th') || card(NOTE), 'dragstart', dt);
    check(dt.types.includes('application/x-kalmido-node') && dt.getData('application/x-kalmido-node') === String(NOTE), 'the drag carries the node type with the id');
    check(dt.types.includes('application/x-kalmido-inside'), 'and the shared "begun in Kalmido" type');
    const ov = dnd(w, subT(), 'dragover', dt);
    check(ov.defaultPrevented && subT().classList.contains('abdrop'), 'the folder card takes the dragged card');
    dnd(w, subT(), 'drop', dt); dnd(w, d.body, 'dragend', dt);
    check(await until(async () => (await call('GET', `/api/files/nodes/${NOTE}`)).parent_id === SUB), 'the drop MOVED the file into Sub');
    check(!w.__up.length, 'nothing was uploaded (no new version): ' + JSON.stringify(w.__up));
    check((await call('GET', `/api/files/nodes/${NOTE}`)).version === v0, 'the file keeps its version');
  }
  if (card(NOTE2)) {
    // dropped on the empty view: neither move nor upload
    const dt = mkDT(['Files'], [new w.File(['x'], 'memo.txt', {type: 'text/plain'})]);
    dnd(w, card(NOTE2), 'dragstart', dt);
    const v = d.querySelector('#view .abview');
    const ov = dnd(w, v, 'dragover', dt);
    check(!ov.defaultPrevented, 'the view itself does not offer the upload for a drag from Kalmido');
    dnd(w, v, 'drop', dt); dnd(w, d.body, 'dragend', dt);
    await sleep(300);
    check(!w.__up.length && (await call('GET', `/api/files/nodes/${NOTE2}`)).parent_id === PLAIN, 'dropped on the view: nothing happens');
    // the panel's folder (desktop): a drag begun elsewhere in Kalmido (only the shared type) uploads nothing there
    const side = await until(() => d.querySelector(`#side [data-abdrop="${ARC}"]`));
    if (side) {
      const dt2 = mkDT(['Files', 'application/x-kalmido-inside'], [new w.File(['x'], 'pic.png', {type: 'image/png'})]);
      check(!dnd(w, side, 'dragover', dt2).defaultPrevented, 'the panel does not offer the upload for a drag from Kalmido');
      dnd(w, side, 'drop', dt2);
      // the card onto the panel's Archive moves it
      const dt3 = mkDT(['Files'], [new w.File(['x'], 'memo.txt', {type: 'text/plain'})]);
      dnd(w, card(NOTE2), 'dragstart', dt3);
      check(dnd(w, side, 'dragover', dt3).defaultPrevented, 'the panel folder takes the card');
      dnd(w, side, 'drop', dt3); dnd(w, d.body, 'dragend', dt3);
      check(await until(async () => (await call('GET', `/api/files/nodes/${NOTE2}`)).parent_id === ARC), 'the card moved into Archive (panel)');
      check(!w.__up.length, 'the panel uploaded nothing');
      // its own folder takes nothing
      const own = d.querySelector(`#side [data-abdrop="${PLAIN}"]`);
      if (own && card(SUB)) {
        const dt4 = mkDT();
        dnd(w, card(SUB), 'dragstart', dt4);
        check(!dnd(w, own, 'dragover', dt4).defaultPrevented, 'the own folder in the panel does not take its subfolder');
        dnd(w, d.body, 'dragend', dt4);
      }
    } else check(false, 'the panel shows Archive');
  }
  // a file from the computer (no dragstart) still uploads into the folder card
  if (subT()) {
    const dt = mkDT(['Files'], [new w.File(['y'], 'new.txt', {type: 'text/plain'})]);
    check(dnd(w, subT(), 'dragover', dt).defaultPrevented, 'a file from the computer is taken');
    dnd(w, subT(), 'drop', dt);
    check(await until(() => w.__up.length === 1 && w.__up[0] === SUB), 'it is uploaded into Sub: ' + JSON.stringify(w.__up));
  }
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
