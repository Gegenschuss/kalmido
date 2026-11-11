// 2.947.0 (#5454): a draft in the invoices list names its kind ("Invoice · client"), not "(no number)"; the deletion toast says where it went (jsdom)
// kalmido-suite: fresh
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const FEAT = 'cal,comments,collab,office,clients';
const TEST_IBAN = 'DE02120300000000202051';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  // 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const st = await call('GET', '/api/office/settings');
  check(st.http === 200 && st.role === 'admin', 'office settings, alice is the organisation admin ' + st.http);
  await call('PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH'}, lang: 'en', company_fields: {name: 'Studio Nordlicht GmbH', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: TEST_IBAN}, producing_on: 1, raw_on: 1});  // 2.40.0 (#1379)
  const S1 = (await call('POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Editing', category: 'Video', daily_rate: 1000})).id;
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'})).id;
  const offer = await call('POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: CL, project_ref: 'PO-77', service_from: '2026-05-01', items: [{service_id: S1, qty: 2}]});
  check(offer.http === 201 && offer.number, 'a quotation ' + offer.http);
  const inv = await call('POST', `/api/office/docs/${offer.id}/invoice`);
  check(inv.http === 201 && inv.kind === 'invoice' && inv.number === '' && inv.order_ref === 'PO-77', 'an invoice draft from the quotation ' + inv.http);
  let w = await boot({hash: 'office/invoices'}); let d = w.document;
  await until(() => d.querySelector('.ofdlist .ofdrow'), 60);
  const row = d.querySelector('.ofdlist .ofdrow');
  const name = (row?.querySelector('.ofcn b')?.textContent || '').trim();
  check(/^Invoice/.test(name) && !/no number/.test(row?.textContent || ''), 'a draft row: "Invoice · client", not "(no number)": ' + name);
  check(/Draft/.test(row?.querySelector('.rotag')?.textContent || ''), 'the draft tag stays');
  w.close();
  console.log(`p2925_a_office_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash ' + e.stack); process.exit(1); });
