// kalmido-suite: fresh
// 2.351.0 B (#2749) UI tests: the address book in folders (ctfold.js). Own container (start.sh), jsdom. Invented names only.
// - a computer, the address book open: the panel shows the folders of the address book (ns 'ct') per workspace with the
//   shared tree: a folder (draggable, takes drops, a menu: New folder…, Share…, Rename…, Move to the trash), the books and
//   contacts filed in it; a book dragged onto another folder lands there (server)
// - a folder opens as the filter of the contacts list (#contacts/f/<id>, the bar with its name; x ends it)
// - the folder's Share dialog (the file store's) offers the workspace's agents; the address book's own Share dialog offers
//   them too ("Person or agent")
// freelancer-matrix: n/a (the routes run in p2351_b_contacts_tree_test.py, also for a person without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2351B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent);
function dnd(w, from, to, y) {  // a mouse drag of node from onto node to at height y (0..1) of it
  to.getBoundingClientRect = () => ({top: 100, height: 20, left: 0, width: 200, right: 200, bottom: 120});
  const ev = (type, el) => { const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientY: 100 + y * 20}); Object.defineProperty(e, 'dataTransfer', {value: {setData() {}, types: [], effectAllowed: '', dropEffect: ''}}); el.dispatchEvent(e); return e; };
  ev('dragstart', from); const over = ev('dragover', to); ev('drop', to); ev('dragend', from);
  return over.defaultPrevented;
}
const openRow = async (d, name) => { const a = rowOf(d, name)?.querySelector('[data-act="sbb-tree"]'); if (a && !a.dataset.open) a.click(); await sleep(150); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Example Studio', admin_id: (await call('GET', '/api/state')).me.id})).id;
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'contacts', 'office', 'clients'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  const AG = (await call('POST', '/api/admin/agents', {scopes: ['read', 'contacts'], username: 'crewbot', display_name: 'Crewbot', org_id: ORG})).id;
  const fold = async (name, b) => (await call('POST', '/api/contacts/folders', {name, space: 'private', ...b})).folder?.id;
  const FR = await fold('Friends'), FA = await fold('Archive'), FC = await fold('Crew', {space: 'org:' + ORG});
  const BK = (await call('POST', '/api/books', {name: 'Private people', org_id: null})).id;
  const OB = (await call('POST', '/api/books', {name: 'Studio people', org_id: ORG})).id;
  const P1 = (await call('POST', '/api/contacts', {book_id: BK, fn: 'Paula Example'})).id;
  const placed = (await call('POST', '/api/files/refs', {ref_kind: 'address_book', ref_id: BK, parent_id: FR})).node?.id;
  check(ORG && AG && FR && FA && FC && BK && OB && P1 && placed, 'setup ' + JSON.stringify({ORG, AG, FR, FA, FC, BK, OB, P1, placed}));

  // ================= a computer: the panel of the address book
  let w = await boot({user: 'alice', hash: 'contacts'}), d = w.document;
  const roots = await until(() => { const r = [...d.querySelectorAll('#side .sbbt[data-sbbns="ct"][data-sbbid^="r:"]')]; return r.length === 2 && r; });
  check(roots && roots.map(r => r.dataset.sbbid).join() === `r:private,r:org:${ORG}`, 'one entry per workspace ' + (roots || []).map(r => r.dataset.sbbid).join());
  const R1 = await until(() => rowOf(d, 'Friends'));
  check(R1 && R1.dataset.sbbid === 'f' + FR && R1.dataset.sbbpar === 'r:private' && R1.getAttribute('draggable') === 'true' && R1.dataset.sbbdrop === '1' && R1.dataset.sbbmenu === '1',
    'a folder: ns / id / par, draggable, takes drops, has a menu');
  await openRow(d, 'Friends');
  const BR = await until(() => rowOf(d, 'Private people'));
  check(BR && BR.dataset.sbbid === 'b' + BK && BR.dataset.sbbpar === 'f' + FR, 'the filed book inside its folder');
  // the folder opens as the list's filter
  R1.querySelector('.sbbtn').click();
  check(await until(() => d.querySelector('#view .ctfbar') && [...d.querySelectorAll('#view .ctrow .ctn b')].map(x => x.textContent).join() === 'Paula Example'),
    'the folder filters the list: the bar and the book\'s contact ' + (d.querySelector('#view')?.textContent || '').slice(0, 200));
  d.querySelector('#view [data-ctf="clear"]').click();
  check(await until(() => !d.querySelector('#view .ctfbar')), 'x ends the folder filter');
  // the folder's menu
  rowOf(d, 'Friends').querySelector('.sbbtn').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  const mi = await until(() => menuItems(d).length && menuItems(d));
  check(mi && ['New folder…', 'Share…', 'Rename…', 'Move to the trash'].every(x => mi.includes(x)), 'the folder\'s menu ' + JSON.stringify(mi));
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  await sleep(150);
  // drag the book onto Archive
  check(dnd(w, rowOf(d, 'Private people'), rowOf(d, 'Archive'), 0.5), 'a folder takes the dragged book');
  check(await until(async () => ((await call('GET', '/api/contacts/folders')).items || []).find(x => x.kind === 'book' && x.id === BK)?.parent_id === FA),
    'the book is now in Archive (server) ' + (d.querySelector('#toast')?.textContent || ''));
  // the folder's Share dialog: the file store's, with the organisation's agent
  await openRow(d, 'Example Studio');
  w.eval(`ctf_share(${FC})`);
  const sel = await until(() => d.querySelector('.abshdlg #ab-sht'));
  check(sel && [...sel.querySelectorAll('optgroup')].some(g => g.label === 'Agents' && [...g.querySelectorAll('option')].some(o => o.textContent === 'Crewbot')),
    'the folder\'s Share dialog offers the agent ' + (sel ? sel.innerHTML.slice(0, 300) : ''));
  d.querySelector('.abshdlg [data-m="close"]')?.click();
  await sleep(150);
  // the address book's own Share dialog offers the agent too
  w.eval(`ctShareModal(ctBook(${OB}), [], new Map(), () => {})`);
  const sel2 = await until(() => d.querySelector('#cbs-user'));
  check(sel2 && [...sel2.querySelectorAll('optgroup')].some(g => g.label === 'Agents' && [...g.querySelectorAll('option')].some(o => +o.value === AG)),
    'the book\'s Share dialog offers the agent ' + (sel2 ? sel2.innerHTML.slice(0, 300) : ''));
  w.close();

  console.log(`p2351_b_contacts_tree_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
