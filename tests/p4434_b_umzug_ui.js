// kalmido-suite: fresh
// 2.547.0 (#4434) UI test, jsdom: Office > Receipts names the old receipts of the own documents once and moves them only on a click.
// - a person without an organisation with her personal office and one e-invoice from before #4433 (never sorted): the hint
//   "1 receipt is still in your documents"; "Show" opens the preview with the row preset to "Move"; "Stays" switches the
//   button off and nothing moved; "Move 1 receipt" moves it (toast), the hint turns into the undo line
// freelancer-matrix: office
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const FEATURES = 'files,docs,clients,office';
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 75) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const UBL = `<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017</cbc:CustomizationID><cbc:ID>ER-2026-99</cbc:ID><cbc:IssueDate>2026-03-05</cbc:IssueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyName><cbc:Name>Beispiel Papier GmbH</cbc:Name></cac:PartyName>
    <cac:PartyTaxScheme><cbc:CompanyID>DE123456789</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>
    <cac:PartyLegalEntity><cbc:RegistrationName>Beispiel Papier GmbH</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Kunde Beispiel</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="EUR">19.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">100.00</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">19.00</cbc:TaxAmount>
    <cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount><cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="EUR">119.00</cbc:TaxInclusiveAmount><cbc:PayableAmount currencyID="EUR">119.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
  <cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="C62">1</cbc:InvoicedQuantity><cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount>
    <cac:Item><cbc:Name>Papier</cbc:Name><cac:ClassifiedTaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>
    <cac:Price><cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</ubl:Invoice>
`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: FEATURES}, FK);
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Frida Grafik', vat_id: 'DE111222333'}}, FK);
  const fd = new FormData();
  fd.append('ws', 'private');
  fd.append('files', new Blob([UBL], {type: 'application/xml'}), 'rechnung-papier.xml');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: FK}, body: fd})).json();
  const id = up.ids?.[0];
  check(id && await until(async () => (await call('GET', `/api/docs/${id}`, null, FK)).state === 'done'), 'setup: an e-invoice read, never sorted');
  const area = async () => (await call('GET', `/api/docs/${id}`, null, FK)).area?.area;
  check(await area() === 'private', 'setup: it lies in her own documents');

  const w = await boot({user: 'frida', hash: 'office/receipts'}), d = w.document;
  const hint = await until(() => d.querySelector('.shint.amv'));
  check(hint && /1 receipt is still in your documents/.test(hint.textContent), '#4434: the hint with the number ' + (hint && hint.textContent));
  hint?.querySelector('[data-amv="open"]')?.click();
  const md = await until(() => d.querySelector('.amvmd'));
  const sel = md && md.querySelector(`select[data-amv-id="${id}"]`);
  const go = md && md.querySelector('[data-m="go"]');
  check(sel && sel.value === 'move', 'the preview: the row preset to Move');
  check(go && /Move 1 receipt/.test(go.textContent) && !go.disabled, 'the button names the number ' + (go && go.textContent));
  if (sel) { sel.value = 'stay'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(go && go.disabled, '"Stays": nothing to move, the button is off');
  check(await area() === 'private', '#4434: the preview moved nothing');
  if (sel) { sel.value = 'move'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  go?.click();
  check(await until(() => /1 receipt moved into the office/.test(d.querySelector('#toast')?.textContent || '')), 'the toast after the click ' + (d.querySelector('#toast')?.textContent || ''));
  check(await until(async () => await area() === 'office'), 'the click moved it into the office');
  check(await until(() => /moved from your documents into the office/.test(d.querySelector('.shint.amv')?.textContent || '') && d.querySelector('.shint.amv [data-amv="undo"]')),
    'the hint turned into the undo line ' + (d.querySelector('.shint.amv')?.textContent || ''));
  w.close();

  console.log(`p4434_b_umzug_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
