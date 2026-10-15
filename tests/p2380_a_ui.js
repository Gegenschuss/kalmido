// 2.38.0 UI tests, part A: invoices in the documents tab of Office & finance (#1021 stage 2, F1), own container (start.sh). jsdom:
// - the documents tab has the kind chips (Quotations | Invoices | Credit notes | Reminders); "Invoices" lists the invoices
//   with the state tag (Draft / Finalised / Partly paid / Paid / Overdue / Cancelled) and the open amount
// - the invoice editor: PO number, payment terms, due date, no raw data / producing automation; a draft's status
//   select is disabled (issued comes with finalising); a finalised invoice shows "Record payment", "Send", the
//   payments section with the sum, and "Credit note / cancel"
// - the quotation editor has "Create invoice"; the settings page has the invoice fields (schemes, DATEV inbox)
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
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
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
  const inv2 = await call('POST', `/api/office/docs/${offer.id}/invoice`);
  const fin = await call('POST', `/api/office/docs/${inv2.id}/finalize`);
  check(fin.http === 200 && fin.number === 'RE-2026-001' && fin.status === 'issued', 'second invoice finalised ' + fin.http + ' ' + JSON.stringify(fin.error || fin.number));
  const pay = await call('POST', `/api/office/docs/${inv2.id}/payments`, {date: '2026-10-01', amount: 1000, method: 'transfer'});
  check(pay.http === 201 && pay.state === 'partial', 'a part payment -> partial ' + pay.http);

  // ================= jsdom: the list with kind chips and state tags
  let w = await boot({hash: 'office/offers'}); let d = w.document;
  await until(() => d.querySelector('.ofdkinds [data-kind="invoice"]'), 60);
  check(d.querySelectorAll('.ofdkinds [data-ofd="kind"]').length === 5 && d.querySelector('.ofdkinds [data-kind="offer"]')?.getAttribute('aria-selected') === 'true', 'documents tab: five kind chips (2.39.1 #1182: + Archive), quotations first');
  check(d.querySelectorAll('.ofdlist .ofdrow').length === 1 && /Draft/.test(d.querySelector('.ofdlist .rotag')?.textContent || ''), 'quotation list as before');
  d.querySelector('.ofdkinds [data-kind="invoice"]').click();
  await until(() => d.querySelectorAll('.ofdlist .ofdrow').length === 2, 60);
  const rows = [...d.querySelectorAll('.ofdlist .ofdrow')];
  check(rows.length === 2 && d.querySelector('.ofdkinds [data-kind="invoice"]').getAttribute('aria-selected') === 'true', 'invoice chip lists the two invoices');
  const partial = rows.find(x => /RE-2026-001/.test(x.textContent));
  check(partial && /Partly paid/.test(partial.querySelector('.rotag')?.textContent || '') && partial.classList.contains('st-partial') && /open: .*1,380\.00/.test(partial.textContent), 'the finalised invoice shows "Partly paid" and the open amount: ' + (partial?.textContent || '').slice(0, 120));
  const draft = rows.find(x => /no number/.test(x.textContent));
  check(draft && /Draft/.test(draft.querySelector('.rotag')?.textContent || ''), 'the draft shows "Draft" without a number');
  check(!!d.querySelector('[data-ofd="remind"]') && !!d.querySelector('[data-ofd="new-inv"]'), 'invoice list: "Create reminder" and "New invoice"');
  const sel = d.querySelector('#ofd-status');
  check(sel && [...sel.options].some(o => o.value === 'overdue') && [...sel.options].some(o => o.value === 'partial'), 'status filter offers the derived states');
  w.close();

  // ================= jsdom: the invoice editor (draft)
  w = await boot({hash: 'office/offers/' + inv.id}); d = w.document;
  await until(() => d.querySelector('.ofdeditor #ofd-order_ref'), 60);
  check(d.querySelector('#ofd-order_ref')?.value === 'PO-77' && !!d.querySelector('#ofd-payment_days') && !!d.querySelector('#ofd-due_date') && !!d.querySelector('#ofd-einvoice_format'), 'invoice editor: PO number, payment terms, due date, e-invoice format');
  check(!d.querySelector('#ofd-raw_mode') && !d.querySelector('#ofd-valid_until') && !d.querySelector('.ofdautos'), 'invoice editor: no raw data / producing automation, no valid-until');
  check(d.querySelector('#ofd-status')?.disabled === true, 'invoice draft: the status select is disabled (issued comes with finalising)');
  check(!!d.querySelector('[data-ofd="finalize"]') && !!d.querySelector('[data-ofd="it-disc"]') && !d.querySelector('[data-ofd="pay"]'), 'invoice draft: Finalise and Discount buttons, no payment yet');
  check(/Invoice/.test(d.querySelector('.ofdhead .ofdnum')?.textContent || '') && /Draft/.test(d.querySelector('.ofdhead .ofdnum')?.textContent || ''), 'invoice draft head: "Invoice Draft"');
  const tot = d.querySelector('#ofd-totals')?.textContent || '';
  check(/Subtotal/.test(tot) && /Total/.test(tot) && /2,000\.00/.test(tot) && /2,380\.00/.test(tot), 'invoice totals: subtotal, tax, total: ' + tot.slice(0, 120));
  w.close();

  // ================= jsdom: the finalised invoice with a payment
  w = await boot({hash: 'office/offers/' + inv2.id}); d = w.document;
  await until(() => d.querySelector('.ofdeditor .ofdpays'), 60);
  check(!!d.querySelector('[data-ofd="pay"]') && !!d.querySelector('[data-ofd="send"]') && !!d.querySelector('[data-ofd="credit"]') && !!d.querySelector('[data-ofd="dup"]'), 'finalised invoice: Record payment, Send, Credit note / cancel, Duplicate');
  check(d.querySelectorAll('.ofdpays .ofdpay').length === 1 && /Paid: .*1,000\.00/.test(d.querySelector('.ofdpaysum')?.textContent || '') && /Open: .*1,380\.00/.test(d.querySelector('.ofdpaysum')?.textContent || ''), 'payments section: one payment, paid / open sum: ' + (d.querySelector('.ofdpaysum')?.textContent || ''));
  check(!!d.querySelector('.ofdpays [data-ofd="pay-del"]'), 'admin sees the remove button of a payment');
  check(d.querySelector('.ofdfs')?.disabled === true && d.querySelector('#ofd-status')?.disabled === false, 'finalised invoice: fields locked, status select open');
  const opts = [...d.querySelectorAll('#ofd-status option')];
  check(opts.find(o => o.value === 'sent')?.disabled === false && opts.find(o => o.value === 'paid')?.disabled === false && opts.find(o => o.value === 'draft')?.disabled === true && opts.find(o => o.value === 'cancelled')?.disabled === true,
    'status options: sent / paid open, draft / cancelled never by hand');
  check(/Partly paid/.test(opts.find(o => o.value === 'issued')?.textContent || ''), 'the current option names the derived state');
  w.close();

  // ================= jsdom: the quotation has "Create invoice"; the settings carry the invoice fields
  w = await boot({hash: 'office/offers/' + offer.id}); d = w.document;
  await until(() => d.querySelector('.ofdeditor [data-ofd="to-invoice"]'), 60);
  check(!!d.querySelector('[data-ofd="to-invoice"]') && !!d.querySelector('#ofd-valid_until') && !!d.querySelector('#ofd-raw_mode'), 'quotation editor: "Create invoice", valid-until and the automation stay');
  w.close();
  w = await boot({hash: 'office/settings'}); d = w.document;
  await until(() => d.querySelector('#ofc-set #os-inv-scheme'), 60);
  check(d.querySelector('#os-inv-scheme')?.value === 'RE-{yyyy}-{seq:03}' && d.querySelector('#os-cr-scheme')?.value === 'GS-{yyyy}-{seq:03}' && !!d.querySelector('#os-datev') && !!d.querySelector('#os-einv') && !!d.querySelector('#os-datev-auto'), 'settings: invoice / credit note schemes, DATEV inbox, e-invoice format');
  w.close();

  console.log(`p2380_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
