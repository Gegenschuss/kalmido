// 2.47.3 UI tests (part C, #1731, #1733, #1734), own container (start.sh, mode workspaces). jsdom, invented data only:
// - #1731 contacts: Edit in the selection bar opens one sheet; typing ticks a field, only ticked / filled fields change; one
//   request; the toast's Undo puts the old values back; Shift-click ticks the rows in between
// - #1734 Office > Clients: list + card like the contacts (heading Office > Clients, "Client" tag and briefcase on the card,
//   "Contact" tag on a contact's card), the card has rate, budget, contact persons; the empty list explains clients vs. contacts
// - #1733 clients: the selection mode (select button, All, Edit = rate for all, Archive with Undo, Delete with one question:
//   a client in a framework contract is archived instead), Esc ends it, a long press on the phone starts it
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});  // KMT_NOSTART=1: a running app
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const ptr = (w, el, type, extra = {}) => {  // jsdom has no PointerEvent: a MouseEvent with pointerType
  const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, button: 0, clientX: 10, clientY: 10});
  Object.defineProperty(e, 'pointerType', {value: extra.pointerType || 'mouse'}); el.dispatchEvent(e);
};
const typeIn = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,contacts,office,clients,time'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  const BK = (await call('POST', '/api/books', {name: 'Mine', org_id: null})).id;
  const cs = [];
  for (const n of ['Anna Test', 'Bert Test', 'Carl Test']) cs.push((await call('POST', '/api/contacts', {book_id: BK, fn: n, groups: ['Old'], note: 'first'})).id);

  // ================= #1731: edit several contacts at once
  let w = await boot({hash: 'contacts'}); let d = w.document;
  await until(() => d.querySelectorAll('#view .ctrow').length === 3, 60);
  const row = name => [...d.querySelectorAll('#view .ctrow')].find(x => x.textContent.includes(name));
  d.querySelector('[data-ct="pick"]').click(); await sleep(50);
  check(!!d.querySelector('#ct-sbar [data-ctb="edit"]') && d.querySelector('#ct-sbar [data-ctb="edit"]').disabled, '#1731: Edit in the bar, waiting for a tick');
  row('Anna Test').click(); await sleep(30);
  const sh = new w.MouseEvent('click', {bubbles: true, cancelable: true, shiftKey: true}); row('Carl Test').dispatchEvent(sh); await sleep(50);
  check(w.eval('CT.pick.size') === 3, '#1733: Shift-click ticks the rows in between (contacts)');
  row('Bert Test').click(); await sleep(30);
  check(w.eval('CT.pick.size') === 2, 'a tap unticks Bert again');
  d.querySelector('#ct-sbar [data-ctb="edit"]').click(); await until(() => d.querySelector('.modal.msdlg'), 20);
  const md = d.querySelector('.modal.msdlg');
  check(md && /Edit 2 contacts/.test(md.textContent) && md.querySelector('[data-msf="groups_add"]') && md.querySelector('[data-msf="org"]') && md.querySelector('[data-msf="kind"]') && md.querySelector('[data-msf="note_append"]'),
    '#1731: one sheet with groups, company, department, kind, note');
  typeIn(w, md.querySelector('[data-msf="groups_add"]'), 'Fair, Old');
  typeIn(w, md.querySelector('[data-msf="org"]'), 'Example Corp');
  check(md.querySelector('[data-msuse="org"]').checked && !md.querySelector('[data-msuse="dept"]').checked, '#1731: typing ticks the field, the others stay off');
  typeIn(w, md.querySelector('[data-msf="note_append"]'), 'Met at the fair');
  md.querySelector('[data-m="save"]').click();
  await until(async () => (await call('GET', `/api/contacts/${cs[0]}`)).org === 'Example Corp', 40);
  let a = await call('GET', `/api/contacts/${cs[0]}`), b = await call('GET', `/api/contacts/${cs[1]}`);
  check(a.org === 'Example Corp' && JSON.stringify(a.groups) === JSON.stringify(['Old', 'Fair']) && a.note === 'first\n\nMet at the fair' && a.dept === '', '#1731: the ticked fields changed: ' + JSON.stringify([a.org, a.groups, a.note]));
  check(b.org === '' && b.note === 'first', '#1731: the unticked contact stays');
  await until(() => /2 contacts changed/.test(d.querySelector('#toast')?.textContent || ''), 20);
  check(/2 contacts changed/.test(d.querySelector('#toast').textContent) && d.querySelector('#toast button'), '#1731: the toast with Undo');
  d.querySelector('#toast button').click();
  await until(async () => (await call('GET', `/api/contacts/${cs[0]}`)).org === '', 40);
  a = await call('GET', `/api/contacts/${cs[0]}`);
  check(a.org === '' && JSON.stringify(a.groups) === JSON.stringify(['Old']) && a.note === 'first', '#1731: Undo = one step back for both contacts');
  // the contact's card says "Contact" (clients are on)
  row('Anna Test').click(); await until(() => d.querySelector('.ctcard .mstag'), 20);
  check(/Contact/.test(d.querySelector('.ctcard .mstag')?.textContent || '') && !d.querySelector('.ctcard .mstag-cl'), '#1734: a contact card carries the tag Contact');
  w.close();

  // ================= #1734: the clients page, empty first
  w = await boot({hash: 'clients'}); d = w.document;
  await until(() => d.querySelector('#view .msclempty'), 60);
  check(/Clients are everyone you write quotations and invoices for/.test(d.querySelector('#view .msclempty')?.textContent || ''), '#1734: the empty list explains clients vs. contacts');  // 2.165.3 (#2647): the new client text
  // 2.87.9 (#1917): no heading "Office > Clients" any more (it looked like a way back); the office menu shows the place
  await until(() => d.querySelector('#side [data-ofm="clients"][aria-current="page"]'), 30);  // 2.152.2 (#2617): the office panel #side
  check(!d.querySelector('#view .msclh') && !d.querySelector('#view .ofrail') && !!d.querySelector('#side [data-ofm="clients"][aria-current="page"]'), '#1917: no heading, the menu marks Clients');  // 2.98.0 (#2180): the office rail  // 2.152.2 (#2617): the points sit in the panel #side
  w.close();
  const cl = [];
  for (const [n, o] of [['Alpha GmbH', {rate: 90, budget_h: 20, contacts: [{name: 'Max Example', role: 'Producer', is_default: true}]}], ['Beta AG', {}], ['Gamma KG', {}]]) cl.push((await call('POST', '/api/clients', {name: n, org_id: ORG, ...o})).id);
  check((await call('POST', '/api/office/contracts', {name: 'Frame', client_id: cl[2]})).http < 300, 'a framework contract points to Gamma');
  w = await boot({hash: 'clients'}); d = w.document;
  await until(() => d.querySelectorAll('#view .msclients .ctrow').length === 3, 60);
  const crow = name => [...d.querySelectorAll('#view .msclients .ctrow')].find(x => x.textContent.includes(name));
  check(d.querySelectorAll('#view .msclients .ctrow').length === 3 && d.querySelector('#view .ctcard.ctnone'), '#1734: the list on the left, an empty card place on the right');
  crow('Alpha GmbH').click();
  await until(() => d.querySelector('#view #mscl-h'), 40);
  check(w.eval('S.route.client') === cl[0] && d.querySelector('#view #mscl-h').textContent === 'Alpha GmbH' && d.querySelectorAll('#view .msclients .ctrow').length === 3, '#1734: a tap opens the card next to the list');
  const card = d.querySelector('#view .msclcard');
  check(/Client/.test(card.querySelector('.mstag-cl')?.textContent || '') && card.querySelector('.mscav'), '#1734: the card carries the tag Client and the briefcase');
  check(/Hourly rate/.test(card.textContent) && /90/.test(card.textContent) && /20 h/.test(card.textContent) && /Max Example/.test(card.querySelector('.msclks')?.textContent || ''), '#1734: rate, budget, contact persons on the card');
  check(!!card.querySelector('[data-act="client-edit"]') && !!card.querySelector('.cldetail .sttiles'), '#1734: Edit (the full dialog) and the hours on the card');
  // search
  typeIn(w, d.querySelector('#mscl-q'), 'beta'); await sleep(250);
  check(d.querySelectorAll('#view .msclients .ctrow').length === 1, '#1734: the search narrows the list');
  typeIn(w, d.querySelector('#mscl-q'), ''); await sleep(250);

  // ================= #1733: the selection of clients
  d.querySelector('[data-mscl="pick"]').click(); await sleep(50);
  check(!!d.querySelector('#ct-sbar [data-clb="all"]') && d.querySelectorAll('#view .msclients .ctrow .ctchk').length === 3, '#1733: the same selection bar and a tick per row');
  d.querySelector('#ct-sbar [data-clb="all"]').click(); await sleep(50);
  check(w.eval('MSC.pick.size') === 3, '#1733: All ticks every shown client');
  crow('Gamma KG').click(); await sleep(50);
  d.querySelector('#ct-sbar [data-clb="edit"]').click(); await until(() => d.querySelector('.modal.msdlg'), 20);
  const m2 = d.querySelector('.modal.msdlg');
  typeIn(w, m2.querySelector('[data-msf="rate"]'), '75,5');
  m2.querySelector('[data-m="save"]').click();
  await until(async () => (await call('GET', `/api/clients/${cl[1]}`)).rate === 75.5, 40);
  check((await call('GET', `/api/clients/${cl[0]}`)).rate === 75.5 && (await call('GET', `/api/clients/${cl[2]}`)).rate === null, '#1733: Edit sets the rate of the two ticked clients');
  await until(() => /2 clients changed/.test(d.querySelector('#toast')?.textContent || ''), 20);
  d.querySelector('#toast button').click();
  await until(async () => (await call('GET', `/api/clients/${cl[0]}`)).rate === 90, 40);
  check((await call('GET', `/api/clients/${cl[0]}`)).rate === 90 && (await call('GET', `/api/clients/${cl[1]}`)).rate === null, '#1733: Undo puts the old rates back');
  // archive + undo
  await until(() => d.querySelector('[data-mscl="pick"]'), 20);
  d.querySelector('[data-mscl="pick"]').click(); await sleep(50);
  await until(() => crow('Beta AG'), 40);  // 2.47.3: the list is drawn again after the undo (slow CI runner)
  crow('Beta AG').click(); await sleep(30);
  d.querySelector('#ct-sbar [data-clb="arch"]').click();
  await until(async () => (await call('GET', `/api/clients/${cl[1]}`)).archived, 40);
  check((await call('GET', `/api/clients/${cl[1]}`)).archived, '#1733: Archive');
  await until(() => d.querySelectorAll('#view .msclients .ctrow').length === 2, 40);
  check(d.querySelectorAll('#view .msclients .ctrow').length === 2, '#1733: an archived client leaves the list (Archived shows it)');
  await until(() => /1 client archived/.test(d.querySelector('#toast')?.textContent || '') && d.querySelector('#toast button'), 40);  // CI of 2.307.7: the own toast before its button (an older toast and its Undo can still be there on a slow runner)
  d.querySelector('#toast button')?.click();
  await until(async () => !(await call('GET', `/api/clients/${cl[1]}`)).archived, 40);
  check(!(await call('GET', `/api/clients/${cl[1]}`)).archived, '#1733: Undo of Archive');
  // delete: one question; Gamma (in a contract) is archived instead
  let asked = '';
  w.confirm = t => { asked = t; return true; };
  await until(() => d.querySelectorAll('#view .msclients .ctrow').length === 3, 40);
  d.querySelector('[data-mscl="pick"]').click(); await sleep(50);
  await until(() => crow('Beta AG') && crow('Gamma KG'), 40);  // 2.48.1: the list may be drawn again after the undo (slow CI runner)
  crow('Beta AG').click(); crow('Gamma KG').click(); await sleep(50);
  d.querySelector('#ct-sbar [data-clb="del"]').click();
  await until(async () => (await call('GET', `/api/clients/${cl[1]}`)).http === 404, 40);
  check(/Delete 2 clients\?/.test(asked), '#1733: one question with the count: ' + asked);
  check((await call('GET', `/api/clients/${cl[1]}`)).http === 404 && (await call('GET', `/api/clients/${cl[2]}`)).archived, '#1733: Beta deleted, Gamma (in use) archived');
  await until(() => /1 deleted/.test(d.querySelector('#toast')?.textContent || ''), 20);
  check(/1 deleted/.test(d.querySelector('#toast').textContent) && /1 archived/.test(d.querySelector('#toast').textContent), '#1733: the toast says x deleted, y archived: ' + d.querySelector('#toast').textContent);
  await until(() => d.querySelector('[data-mscl="pick"]'), 40);  // 2.272.0 (#3029): the list loads again after the delete (trash + undo step)
  d.querySelector('[data-mscl="pick"]').click(); await sleep(50);
  check(!!d.querySelector('#ct-sbar'), 'selection again');
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(50);
  check(!d.querySelector('#ct-sbar') && w.eval('MSC.pick') === null, '#1733: Esc ends the selection');
  // 2.272.0 D (#3029): Beta lies in the clients' trash (box "Trash"), with the period; Restore brings it back
  const tb = d.querySelector('#mscl-trash'); tb.checked = true; tb.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => d.querySelector('#view .mscltrash [data-mscl="trest"]'), 40);
  check(/Beta AG/.test(d.querySelector('#view .mscltrash')?.textContent || '') && /stay in the trash until the deletion runs of the server are switched on/.test(d.querySelector('#view .mscltrdays')?.textContent || ''),  // 2.223.3 (#2877): runs off on the test server
    '#3029: the trash lists Beta with the note that the trash keeps: ' + (d.querySelector('#view .ctlistw')?.textContent || '').slice(0, 200));
  d.querySelector('#view .mscltrash [data-mscl="trest"]').click();
  await until(async () => (await call('GET', `/api/clients/${cl[1]}`)).http !== 404, 40);
  check((await call('GET', `/api/clients/${cl[1]}`)).id === cl[1], '#3029: Restore brings Beta back');
  w.close();
  // the phone: list, then card; a long press starts the selection
  w = await boot({hash: 'clients', mobile: true}); d = w.document;
  await until(() => d.querySelectorAll('#view .msclients .ctrow').length === 1, 60);
  const r1 = d.querySelector('#view .msclients .ctrow');
  ptr(w, r1, 'pointerdown', {pointerType: 'touch'}); await sleep(650); ptr(w, r1, 'pointerup', {pointerType: 'touch'}); r1.click(); await sleep(50);
  check(!!d.querySelector('#ct-sbar') && w.eval('MSC.pick.size') === 1 && !/client\/\d/.test(w.location.hash), '#1733: a long press starts the selection (the click after it does not open the card)');
  d.querySelector('#ct-sbar [data-clb="close"]').click(); await sleep(700);  // past the guard against the click that ends a long press
  d.querySelector('#view .msclients .ctrow').click();
  await until(() => d.querySelector('#view #mscl-h'), 40);
  check(!d.querySelector('#view .ctlistw') && !!d.querySelector('#view [data-mscl="back"]'), '#1734: the phone shows the card alone with a back button');
  d.querySelector('#view [data-mscl="back"]').click();
  await until(() => d.querySelector('#view .ctlistw'), 40);
  check(!!d.querySelector('#view .ctlistw'), '#1734: back to the list');
  w.close();

  // ================= #1360: the card of a person without an organisation (personal office) shows the open invoices
  const mk = await call('POST', '/api/users', {username: 'dora', display_name: 'Dora Frei', password: 'password123', email: 'dora@example.com'});
  check(mk.http < 300, 'dora created');
  const CKD = await login('dora');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,contacts,office,clients,time'}, CKD);
  const dcl = (await call('POST', '/api/clients', {name: 'Privatkunde Eins'}, CKD)).id;
  check(!!dcl, 'a client of the person without an organisation');
  w = await boot({user: 'dora', hash: 'clients'}); d = w.document;
  await until(() => d.querySelectorAll('#view .msclients .ctrow').length === 1, 60);
  d.querySelector('#view .msclients .ctrow').click();
  await until(() => d.querySelector('#view #mscl-h'), 40);
  await until(() => [...d.querySelectorAll('#view .msclcard .ctsec h4')].some(h => h.textContent === 'Open invoices'), 40);
  check([...d.querySelectorAll('#view .msclcard .ctsec h4')].some(h => h.textContent === 'Open invoices') && /No open invoices/.test(d.querySelector('#view .msclcard').textContent),
        '#1360/#1734: the card of a person without an organisation shows the open invoices section');
  w.close();

  // ================= #1360: the clients page follows the workspace of the sidebar (a private and an organisation client)
  const pc = (await call('POST', '/api/clients', {name: 'Privat Eins', org_id: null})).id;
  check(!!pc, 'a private client of the person with an organisation');
  const names = () => [...d.querySelectorAll('#view .msclients .ctrow')].map(x => x.textContent);
  const seen = async (ws, want) => {
    await call('PATCH', '/api/settings', {workspace: ws});
    w = await boot({hash: 'clients'}); d = w.document;
    await until(() => d.querySelectorAll('#view .msclients .ctrow').length === want, 60);
    const t = names().join('|'); w.close(); return t;
  };
  let t = await seen('private', 1);
  check(/Privat Eins/.test(t) && !/Alpha GmbH/.test(t), '#1360: workspace Private shows only the private client: ' + t);
  t = await seen('org:' + ORG, 1);
  check(/Alpha GmbH/.test(t) && !/Privat Eins/.test(t), '#1360: workspace of the organisation shows only its client: ' + t);
  t = await seen('all', 2);
  check(/Alpha GmbH/.test(t) && /Privat Eins/.test(t), '#1360: All shows both: ' + t);

  console.log(`p2473_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
