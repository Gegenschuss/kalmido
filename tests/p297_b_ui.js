// 2.97.0 part B UI test (#1951), own container (start.sh): the client form has "Display name (optional)" with its hint and
// the extra address line, no free "Address" text; pickers show the display name; the client list search finds the display
// name and the legal name. The document head shows the recipient read-only (from the client) with "Edit client" instead
// of the free recipient fields, "Address missing - add it at the client" without street / postcode / city, and "Add
// client" in a document without one (a small dialog: name + address, then set as the document's client).
// P297B_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P297B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,office,clients';
const setVal = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); el.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'de',
    company_fields: {name: 'Studio Nordlicht GmbH', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE'}});
  const C1 = await call('POST', '/api/clients', {org_id: ORG, name: 'Foo AG', street: 'Steinenring 1', zip: '4051', city: 'Basel', country: 'CH'});
  const C2 = await call('POST', '/api/clients', {org_id: ORG, name: 'Foo AG', street: 'Unter den Linden 2', zip: '10117', city: 'Berlin', country: 'DE'});
  check(C1.status === 201 && C2.status === 201, 'two clients with the same name');

  // ================= the client form
  let w = await boot({user: 'alice', hash: 'clients'}), d = w.document;
  await until(() => d.querySelector('#view'));
  w.eval('clientModal(null, {stay: true})');
  const md = await until(() => d.querySelector('.modal.cldlg'));
  check(md && md.querySelector('#cl-dname') && /Shown in pickers and lists, not on the invoice\./.test(md.querySelector('#cl-dname-h')?.textContent || ''),
    'the form: "Display name (optional)" with its hint');
  check(md && /Display name \(optional\)/.test(md.textContent), 'the label "Display name (optional)"');
  check(md && !md.querySelector('#cl-addr') && md.querySelector('#clb-street') && md.querySelector('#clb-address_extra') && md.querySelector('#clb-zip') && md.querySelector('#clb-city'),
    'no free address any more; street, address extra, postcode, city in the form');
  const order = [...(md?.querySelectorAll('[data-clb]') || [])].map(x => x.dataset.clb);
  check(order.indexOf('address_extra') === order.indexOf('street') + 1, 'the extra line right under the street ' + order.join(','));
  check(md && !md.querySelector('details.clbill [data-clb="street"]'), 'the address stands in the form, not inside the billing details');
  setVal(w, md.querySelector('#cl-name'), 'Foo AG');
  setVal(w, md.querySelector('#cl-dname'), 'Foo Schweiz');
  setVal(w, md.querySelector('#clb-street'), 'Bahnhofstrasse 3');
  setVal(w, md.querySelector('#clb-address_extra'), 'c/o Empfang');
  setVal(w, md.querySelector('#clb-zip'), '8001');
  setVal(w, md.querySelector('#clb-city'), 'Zürich');
  md.querySelector('[data-m="save"]').click();
  const C3 = await until(async () => (await call('GET', '/api/clients')).clients.find(c => c.display_name === 'Foo Schweiz'));
  check(C3 && C3.name === 'Foo AG' && C3.billing.address_extra === 'c/o Empfang' && C3.billing.street === 'Bahnhofstrasse 3', 'saved: display name, extra line, street ' + JSON.stringify(C3?.billing || {}).slice(0, 160));
  await until(() => w.eval(`(S.clients || []).length === 3`));
  check(w.eval(`cdn_label(clientById(${C3?.id}))`) === 'Foo Schweiz' && w.eval(`cdn_label(clientById(${C1.id}))`) === 'Foo AG (Basel)', 'pickers: the display name, the city for twins');
  check(w.eval(`listDlgTeamHtml({id: 9, role: 'owner', client_id: null}, 9)`).includes('Foo Schweiz'), 'the list dialog\'s client picker shows the display name');
  // the search of the client list finds both names
  w.eval('ms_clDirty(); ms_clLoad()');
  await until(() => w.eval(`(MSC.items || []).length === 3`));
  check(w.eval(`(MSC.q = 'schweiz', ms_clShown().map(c => c.id).join())`) === String(C3?.id), 'search: the display name');
  check(w.eval(`(MSC.q = 'foo ag', ms_clShown().length)`) === 3, 'search: the legal name finds all three');
  w.eval(`MSC.q = ''`);
  w.close();

  // ================= the document head: the recipient from the client
  const doc = await call('POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: C1.id});
  w = await boot({user: 'alice', hash: 'office/offers/' + doc.id}); d = w.document;
  const rec = await until(() => d.querySelector('.ofdeditor .cdnrec .cdnadr'), 60);
  check(rec && /Steinenring 1/.test(rec.textContent) && /4051 Basel/.test(rec.textContent) && /CH/.test(rec.textContent), 'the read-only address block: ' + (rec?.textContent || ''));
  check(!d.querySelector('#ofd-recipient_name') && !d.querySelector('#ofd-recipient_lines'), 'no free recipient / address lines');
  check(!d.querySelector('.ofdeditor .cdnmiss'), 'no hint with a full address');
  const sel = d.querySelector('#ofd-client_id');
  check(sel && [...sel.options].some(o => o.textContent === 'Foo AG (Basel)') && [...sel.options].some(o => o.textContent === 'Foo Schweiz'), 'the client picker shows the labels');
  d.querySelector('.ofdeditor [data-ofd="client-edit"]')?.click();
  const em = await until(() => d.querySelector('.modal.cldlg'), 60);
  check(em && em.querySelector('#cl-name')?.value === 'Foo AG', '"Edit client" opens the client dialog');
  if (em) {
    setVal(w, em.querySelector('#clb-street'), 'Steinenring 9');
    em.querySelector('[data-m="save"]').click();
  }
  check(await until(() => /Steinenring 9/.test(d.querySelector('.ofdeditor .cdnrec .cdnadr')?.textContent || ''), 60), 'after saving the block shows the new street');
  w.close();

  // ================= without an address: the hint
  const NA = await call('POST', '/api/clients', {org_id: ORG, name: 'Ohne Anschrift KG'});
  const doc2 = await call('POST', '/api/office/docs', {project_title: 'Lücke', client_id: NA.id});
  w = await boot({user: 'alice', hash: 'office/offers/' + doc2.id}); d = w.document;
  const miss = await until(() => d.querySelector('.ofdeditor .cdnmiss'), 60);
  check(miss && /Address missing - add it at the client/.test(miss.textContent), 'the hint "Address missing - add it at the client"');
  w.close();

  // ================= without a client: "Add client" (name + address), then the document's client
  const doc3 = await call('POST', '/api/office/docs', {project_title: 'Neu'});
  w = await boot({user: 'alice', hash: 'office/offers/' + doc3.id}); d = w.document;
  const add = await until(() => d.querySelector('.ofdeditor .cdnrec [data-ofd="client-new"]'), 60);
  check(add, 'a document without a client offers "Add client"');
  add?.click();
  const qm = await until(() => d.querySelector('.modal.cldlg'), 60);
  check(qm && qm.querySelector('#cl-name') && qm.querySelector('#clb-street') && !qm.querySelector('#cl-icon') && !qm.querySelector('#cl-note'), 'the small dialog: name + address only');
  if (qm) {
    setVal(w, qm.querySelector('#cl-name'), 'Neukunde GmbH');
    setVal(w, qm.querySelector('#clb-street'), 'Ring 5');
    setVal(w, qm.querySelector('#clb-zip'), '50667');
    setVal(w, qm.querySelector('#clb-city'), 'Köln');
    qm.querySelector('[data-m="save"]').click();
  }
  const got = await until(async () => { const x = await call('GET', '/api/office/docs/' + doc3.id); return x.client_id && x; }, 60);
  check(got && got.recipient.name === 'Neukunde GmbH' && got.recipient.lines.includes('Ring 5') && got.recipient.lines.includes('50667 Köln'), 'the new client is the document\'s client ' + JSON.stringify(got?.recipient || {}).slice(0, 160));
  check(await until(() => /Ring 5/.test(d.querySelector('.ofdeditor .cdnrec .cdnadr')?.textContent || ''), 60), 'the head shows its address');
  w.close();

  console.log(`p297_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
