// kalmido-suite: fresh
// 2.351.0 F UI tests (#2823, review M4): a draft edited through a folder share, own container (start.sh), jsdom. Invented
// services and amounts only.
// - two saves right after each other over the folder way (a new line, then its quantity): one line on the server, not two
//   (the new line's id and the version go along like on the office route, #3012)
// - after a save the editor keeps the folder mark: the More menu offers the preview only, no status pick, no parts
// - the owner saves in between: the next change gets the conflict bar; Reload shows the owner's state, still read through
//   the folder
// freelancer-matrix: office  (a draft of a personal office -- the private space without an organisation -- shared from a private folder)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2351F_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent);
const svc = (title, qty, rate, unit = 'day') => ({kind: 'service', title, qty, unit, rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});

async function viaFolder(owner, space, bobId, CB, tag) {
  await call(owner, 'PATCH', '/api/settings', {workspace: space});  // the office of the space (a personal office: private)
  const doc = await call(owner, 'POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Spot', items: [svc('Concept', 1, 800)]});
  check(doc.status === 201, 'setup: a quotation ' + doc.status + tag);
  const fol = await call(owner, 'POST', '/api/files/folders', {name: 'Shared drafts', space});
  const ref = await call(owner, 'POST', '/api/files/refs', {ref_kind: 'office_doc', ref_id: doc.id, parent_id: fol.id});
  const sh = await call(owner, 'POST', `/api/files/nodes/${fol.id}/shares`, {user_id: bobId, role: 'edit'});
  check(ref.status === 200 && sh.status === 201, `setup: filed and shared with bob (edit) (${ref.status} ${sh.status})` + tag);
  const w = await boot({user: 'bob', hash: `office/offers/${doc.id}`}), d = w.document;
  check(await until(() => d.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 1 && w.eval('!!(OFD.doc && OFD.doc.via_folder)')),
    'bob: the editor opens the draft through the folder' + tag);
  // ---- two saves right after each other
  w.eval(`OFD.doc.items.push(${JSON.stringify(svc('Editing', 1, 600))});
    window.__p1 = ofdPutItems(); OFD.doc.items[OFD.doc.items.length - 1].qty = 4; window.__p2 = ofdPutItems(); 1`);
  await w.eval('Promise.all([window.__p1, window.__p2])');
  let s = await call(CB, 'GET', `/api/fsref/office_doc/${doc.id}`);
  check(s.items?.length === 2 && +s.items[1].qty === 4, `the new line once, with quantity 4 (${s.items?.length}, ${s.items?.[1]?.qty})` + tag);
  check(!d.querySelector('.ofdcf') && w.eval('OFD.doc.updated_at') === s.updated_at, 'no conflict, the editor holds the current version' + tag);
  // ---- the folder mark stays after the saves
  check(w.eval('OFD.doc.via_folder === true && OFD.doc.folder_role === "edit" && OFD.doc.can_delete === false'), 'the folder mark stays after a save' + tag);
  await until(() => w.eval('OFD.saving') === 0);
  check(!d.querySelector('#ofd-status') && !d.querySelector('#ofd-contract_id'), 'no status pick, no framework contract pick through the folder' + tag);
  click(w, d.querySelector('[data-ofd="more"]'));
  const items = await until(() => menuItems(d).length && menuItems(d));
  check(JSON.stringify(items) === JSON.stringify(['Preview (PDF)']), 'the More menu offers the preview only ' + JSON.stringify(items) + tag);
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  // ---- the owner saves in between
  s = await call(owner, 'GET', `/api/office/docs/${doc.id}`);
  const other = s.items.map(x => ({id: x.id, kind: x.kind, title: x.title, qty: x.qty, unit: x.unit, rate: x.rate, tax: x.tax}));
  other[1].title = 'Editing (owner)';
  const r = await call(owner, 'PUT', `/api/office/docs/${doc.id}/items`, {items: other, expect_updated_at: s.updated_at});
  check(r.status === 200, 'the owner saves ' + r.status + tag);
  change(w, d.querySelector('.ofdits [data-i="0"][data-k="qty"]'), '7');
  check(await until(() => d.querySelector('.ofdcf [data-ofd="cf-reload"]')), 'bob: the conflict bar with Reload' + tag);
  s = await call(owner, 'GET', `/api/office/docs/${doc.id}`);
  check(s.items[1].title === 'Editing (owner)' && +s.items[0].qty === 1, 'the owner\'s save stays on the server' + tag);
  click(w, d.querySelector('[data-ofd="cf-reload"]'));
  check(await until(() => !d.querySelector('.ofdcf') && d.querySelectorAll('.ofdits [data-k="title"]')[1]?.value === 'Editing (owner)'), 'Reload shows the current state' + tag);
  await until(() => !w.eval('OFD.docLoading'));
  check(w.eval('OFD.doc.via_folder === true'), 'after Reload: still through the folder' + tag);
  change(w, d.querySelector('.ofdits [data-i="0"][data-k="qty"]'), '5');
  s = await until(async () => { const x = await call(owner, 'GET', `/api/office/docs/${doc.id}`); return +x.items?.[0]?.qty === 5 ? x : null; });
  check(s && s.items[1].title === 'Editing (owner)' && !d.querySelector('.ofdcf'), 'after Reload the next edit saves' + tag);
  check(!errs.length, 'no script errors ' + errs.join(' | ') + tag); errs.splice(0);
  w.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,files'});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [{id: org.id, role: 'member'}]});
  check(bob.status === 200 || bob.status === 201, 'setup: bob ' + bob.status);
  check((await call(CA, 'PUT', `/api/office/rights/people/${bob.id}`, {groups: ['tpl:staff']})).status === 200, 'setup: bob in Staff (no quotations)');
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,files', workspace: `org:${org.id}`});
  check((await call(CB, 'GET', '/api/office/docs')).status === 403, 'setup: the office itself gives bob no quotations');
  await viaFolder(CA, `org:${org.id}`, bob.id, CB, ' (organisation)');

  // ================= freelancer-matrix: office - a draft of alice's personal office (the private space without an organisation,
  // the same office code a freelancer has), shared from her private folder with bob (a folder share needs a common organisation)
  await viaFolder(CA, 'private', bob.id, CB, ' (personal office)');

  console.log(`p2351_f_review_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
