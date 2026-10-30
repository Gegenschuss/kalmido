// 2.113.2 A (#2253) UI tests: terms and conditions (AGB) as a PDF in Office & finance, own container (start.sh). jsdom:
// - the settings tab has the block "Terms and conditions (PDF)" with one row per language: the uploaded German terms show
//   their name and date with Show / Replace / Remove, the English row offers Upload; Remove is one undo step
// - the send dialog of a finalised quotation has the tick "Attach terms and conditions", ticked; an invoice's is unticked;
//   a quotation in a language without terms has no tick
// Invented companies and files only.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2113BA_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Studio Nordlicht GmbH', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const fd = new FormData();
  fd.append('file', new Blob([Buffer.from('%PDF-1.4\n% invented terms\n%%EOF\n')], {type: 'application/pdf'}), 'AGB Nordlicht.pdf');
  fd.append('date', '2026-10-01');
  const up = await fetch(B + 'api/office/terms/de', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(up.ok, 'the German terms uploaded ' + up.status);
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE', email: 'kunde@example.com'})).id;
  const offer = await call('POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: CL, items: [{title: 'Schnitt', qty: 2, rate: 900}]});
  check(offer.http === 201, 'a quotation ' + offer.http);
  check((await call('POST', `/api/office/docs/${offer.id}/finalize`)).http === 200, 'the quotation finalised');
  const offEn = await call('POST', '/api/office/docs', {client_id: CL, lang: 'en', items: [{title: 'Edit', qty: 1, rate: 100}]});
  await call('POST', `/api/office/docs/${offEn.id}/finalize`);
  const inv = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL, service_from: '2026-10-01', items: [{title: 'Schnitt', qty: 1, rate: 100}]});
  check((await call('POST', `/api/office/docs/${inv.id}/finalize`)).http === 200, 'an invoice finalised');

  // ================= the settings block
  let w = await boot({hash: 'office/settings'}); let d = w.document;
  await until(() => d.querySelector('#agb-box .agbrow'), 60);
  const rows = [...d.querySelectorAll('#agb-box .agbrow')];
  check(rows.length === 2 && /Terms and conditions \(PDF\)/.test(d.querySelector('#agb-box label')?.textContent || ''), 'settings: the block with two language rows');
  const de = rows.find(x => x.dataset.lg === 'de'), en = rows.find(x => x.dataset.lg === 'en');
  check(de && /AGB Nordlicht\.pdf/.test(de.textContent) && /as of/.test(de.textContent), 'the German row: name and date: ' + (de?.textContent || '').slice(0, 100));
  check(de && /\/api\/office\/terms\/de\/file/.test(de.querySelector('a.btn')?.getAttribute('href') || '') && !!de.querySelector('[data-agb="up"]') && !!de.querySelector('[data-agb="del"]'),
    'the German row: Show / Replace / Remove for the admin');
  check(en && /No terms and conditions yet/.test(en.textContent) && !!en.querySelector('[data-agb="up"]') && !en.querySelector('[data-agb="del"]'), 'the English row: Upload only');
  check(!d.querySelector('#agb-box input[type="date"]'), 'no native date inputs in the block');
  en.querySelector('[data-agb="up"]').click();
  await until(() => d.querySelector('#ofd-agb-file'), 20);
  check(!!d.querySelector('#ofd-agb-file') && d.querySelector('#ofd-agb-date')?.type === 'hidden' && !!d.querySelector('[data-dpfor="ofd-agb-date"]'), 'the upload dialog: file + the app\'s own date picker');
  d.querySelector('.modal [data-m="close"]')?.click();
  de.querySelector('[data-agb="del"]').click();
  await until(() => /No terms and conditions yet/.test(d.querySelector('#agb-box .agbrow[data-lg="de"]')?.textContent || ''), 40);
  check((await call('GET', '/api/office/terms')).terms.de === null, 'Remove: the German terms are gone');
  await w.eval("histStep('undo')");
  await until(async () => (await call('GET', '/api/office/terms')).terms.de, 40);
  check((await call('GET', '/api/office/terms')).terms.de?.date === '2026-10-01', 'one undo step puts them back');
  w.close();

  // ================= the send dialog
  w = await boot({hash: 'office/offers/' + offer.id}); d = w.document;
  await until(() => d.querySelector('[data-ofd="send"]'), 60);
  check(!!d.querySelector('[data-ofd="send"]'), 'a finalised quotation has "Send"');
  d.querySelector('[data-ofd="send"]').click();
  // 2.434.0 (#3619): a quotation carries its terms as the last pages of its PDF - a note instead of the tick
  await until(() => d.querySelector('#ofd-s-terms-in'), 40);
  const tk = d.querySelector('#ofd-s-terms-in');
  check(tk && !d.querySelector('#ofd-s-terms') && /last pages of the PDF/.test(tk.textContent || ''), 'quotation: the note "terms are the last pages of the PDF", no tick');
  w.close();
  w = await boot({hash: 'office/offers/' + inv.id}); d = w.document;
  await until(() => d.querySelector('[data-ofd="send"]'), 60);
  d.querySelector('[data-ofd="send"]').click();
  await until(() => d.querySelector('#ofd-s-to'), 40);
  await until(() => d.querySelector('#ofd-s-terms'), 20);
  check(d.querySelector('#ofd-s-terms') && !d.querySelector('#ofd-s-terms').checked, 'invoice: the tick is there, unticked');
  w.close();
  w = await boot({hash: 'office/offers/' + offEn.id}); d = w.document;
  await until(() => d.querySelector('[data-ofd="send"]'), 60);
  d.querySelector('[data-ofd="send"]').click();
  await until(() => d.querySelector('#ofd-s-to'), 40);
  await sleep(300);
  check(!d.querySelector('#ofd-s-terms'), 'an English quotation with German terms only: no tick');
  w.close();

  console.log(`p2113c_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
