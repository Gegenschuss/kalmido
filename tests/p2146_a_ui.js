// 2.146.0 UI tests, part A (#2451, receiving e-invoices), own container (start.sh), Firefox. Invented companies and figures
// only; the XRechnung is written here. freelancer-matrix: files
// - a person without organisation: the file pickers of the documents and of the bookkeeping's receipt button take .xml;
//   an uploaded XRechnung (UBL) opens as a document with the mark "E-invoice", amount and sender from the XML and the
//   button "Readable view"; the readable view is a plain page (seller, sum, escaped item name, no script); the
//   bookkeeping's receipt sheet links the readable view too
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2146_a_ui', check, shots: 'P2146A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2146A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const UBL = `<?xml version="1.0" encoding="UTF-8"?>
<ubl:Invoice xmlns:ubl="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
<cbc:ID>UI-2026-7</cbc:ID><cbc:IssueDate>2026-10-05</cbc:IssueDate><cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
<cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Beispiel Papier GmbH</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
<cac:TaxTotal><cbc:TaxAmount currencyID="EUR">19.00</cbc:TaxAmount><cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">100.00</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">19.00</cbc:TaxAmount><cac:TaxCategory><cbc:ID>S</cbc:ID><cbc:Percent>19</cbc:Percent></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
<cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">119.00</cbc:TaxInclusiveAmount><cbc:PayableAmount currencyID="EUR">119.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
<cac:InvoiceLine><cbc:ID>1</cbc:ID><cbc:InvoicedQuantity unitCode="C62">1</cbc:InvoicedQuantity><cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Papier &lt;img src=x onerror=alert(1)&gt;</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine>
</ubl:Invoice>`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // the person without organisation (tests/freelancer_fixture.py does the same in Python)
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([UBL], {type: 'application/xml'}), 'xrechnung.xml');
  const id = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CF}, body: fd})).json()).ids?.[0];
  check(!!id, 'the XRechnung uploaded');
  let d = {};
  for (let i = 0; i < 120 && !['done', 'failed'].includes(d.state); i++) { await sleep(500); d = await call(CF, 'GET', `/api/docs/${id}`); }
  check(d.method === 'e-invoice' && d.amount === '119.00', 'recognised as e-invoice ' + [d.state, d.method, d.amount].join('|'));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone first
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + '#docs');
    check(await ready(ev, `!!document.querySelector('#dc-file')`, 80), 'the documents area');
    check(await ev(`/\\.xml/.test(document.querySelector('#dc-file').accept)`), 'the documents picker takes .xml ' + await ev(`document.querySelector('#dc-file')?.accept`));
    await nav(B + `#docs/${id}`);
    check(await ready(ev, `!!document.querySelector('.dc-md .dc-einv')`, 80), 'the document sheet offers the readable view');
    check(await ev(`/E-invoice/.test(document.querySelector('.dc-md .dc-state')?.textContent || '')`), 'the state names the e-invoice ' + await ev(`document.querySelector('.dc-md .dc-state')?.textContent.replace(/\\s+/g, ' ')`));
    check(await ev(`document.querySelector('#dc-sender')?.value === 'Beispiel Papier GmbH'`), 'the sender from the XML');
    check(await ev(`document.querySelector('.dc-md .dc-einv').getAttribute('href') === '/api/docs/${id}/einvoice' && document.querySelector('.dc-md .dc-einv').target === '_blank'`), 'the link opens the view in a new tab');
    await shot('p2146-a-doc.png');
    // the bookkeeping: the receipt button takes .xml, the receipt sheet links the view
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.querySelector('#bk-file')`, 80), 'the bookkeeping');
    check(await ev(`/\\.xml/.test(document.querySelector('#bk-file').accept)`), 'the receipt button takes .xml');
    await ev(`(() => { bkSheet(${id}, false); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .bk-einv')`, 60), 'the receipt sheet links the readable view');
    // the readable view itself (parsed from its HTML: the page runs no script, CSP sandbox)
    const view = `fetch('/api/docs/${id}/einvoice', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.text()).then(t => new DOMParser().parseFromString(t, 'text/html'))`;
    check(await ev(`${view}.then(v => /Beispiel Papier GmbH/.test(v.body.textContent) && v.body.textContent.includes('119.00') && v.body.textContent.includes('UI-2026-7'))`), 'the readable view: seller, number, sum');
    check(await ev(`${view}.then(v => !v.querySelector('script, img, iframe') && v.body.textContent.includes('<img src=x'))`), 'no script, the item name shown as text');
  }, false);

  console.log(`p2146_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
