// 2.40.0 UI tests, part D: office documents (#1368 #1381 #1364 #1366), own container (start.sh). jsdom; invented data only.
// - #1366: the PDF button opens /pdf?inline=1 in a new tab, the own "Download" button links the download
// - #1364: the "More" menu has "Preview (PDF)" (no JSON print model)
// - #1368 10: send dialog without mail: "To", a plain hint for people who are no admin (no KALMIDO_SMTP_HOST), the button
//   downloads the PDF, the fields are locked
// - #1368 7: reminder dialog: hints for a high fee and for an invoice not yet due (no block)
// - #1368 8 + 9: reminder list: settled reminder below the open ones with "Settled" and the open fee; editor of the
//   finalised reminder: fee open with "Waive fee" / "Fee paid"; waiving updates it
// - #1381: switching the document language swaps the texts and shows the note box (texts changed by hand / no English)
// - #1381: settings > default texts: the English choice shows the English text
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
  await call('PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Studio Nordlicht GmbH', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: TEST_IBAN, email: 'hallo@nordlicht.example', phone: '040 1234567'}});
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'})).id;
  const mk = async () => { const i = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL, service_from: '2026-05-01', items: [{title: 'Beratung', qty: 1, rate: 100}]}); const f = await call('POST', `/api/office/docs/${i.id}/finalize`); return f; };
  const inv = await mk();
  check(inv.http === 200 && inv.locked, 'an invoice finalised ' + inv.http + ' ' + JSON.stringify(inv.error || ''));
  const open2 = await mk();
  const rem = await call('POST', '/api/office/docs/reminder', {doc_ids: [inv.id], level: 2, fee: 5});
  check(rem.http === 201, 'a reminder ' + rem.http);
  await call('POST', `/api/office/docs/${rem.id}/finalize`);
  await call('POST', '/api/office/docs/reminder', {doc_ids: [open2.id], level: 1});
  const pay = await call('POST', `/api/office/docs/${inv.id}/payments`, {amount: 119});
  check(pay.http === 201 && pay.state === 'paid', 'the invoice is paid ' + pay.http);

  // ================= #1366 / #1364 / #1368 10: the finalised invoice: PDF buttons, menu, send dialog
  let w = await boot({hash: 'office/offers/' + open2.id}); let d = w.document;
  await until(() => d.querySelector('.ofdhead .ofdpdf'), 60);
  const pdf = d.querySelector('.ofdhead .ofdpdf'), dl = d.querySelector('.ofdhead .ofddl');
  check(pdf && /\/pdf\?inline=1$/.test(pdf.getAttribute('href')) && pdf.getAttribute('target') === '_blank', '#1366: the PDF button opens the PDF in the browser: ' + pdf?.getAttribute('href'));
  check(dl && /\/pdf$/.test(dl.getAttribute('href')) && dl.hasAttribute('download') && /Download/.test(dl.textContent), '#1366: own "Download" button: ' + dl?.getAttribute('href'));
  d.querySelector('[data-ofd="more"]').click();
  await until(() => d.querySelector('.menu-list'), 20);
  const mt = d.querySelector('.menu-list')?.textContent || '';
  check(/Preview \(PDF\)/.test(mt) && !/print model/.test(mt), '#1364: menu entry "Preview (PDF)": ' + mt.slice(0, 120));
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  const ms = await call('GET', '/api/office/mail-status');
  w.eval('S.me.is_admin = false');
  d.querySelector('[data-ofd="send"]').click();
  await until(() => d.querySelector('#ofd-s-to'), 40);
  const md = d.querySelector('#ofd-s-to')?.closest('.modal') || d.body;
  const lab = d.querySelector('label[for="ofd-s-to"]')?.textContent || '';
  check(lab === 'To', '#1368 10: the field is labelled "To": ' + lab);
  if (!ms.smtp) {
    const warn = md.querySelector('.ofdwarn')?.textContent || '';
    check(/not set up yet/.test(warn) && !/KALMIDO_SMTP_HOST/.test(warn), '#1368 10: plain hint for people who are no admin: ' + warn.slice(0, 100));
    check(md.querySelector('[data-m="ok"]')?.textContent === 'Download PDF' && d.querySelector('#ofd-s-to').disabled, '#1368 10: without mail the button downloads the PDF, fields locked');
  } else check(true, 'mail is set up in this container: the send button stays');
  md.querySelector('[data-m="close"]')?.click();
  w.close();

  // ================= #1368 7: the reminder dialog warns (high fee, not yet due)
  w = await boot({hash: 'office/offers'}); d = w.document;
  await until(() => d.querySelector('.ofdkinds [data-kind="invoice"]'), 60);
  d.querySelector('.ofdkinds [data-kind="invoice"]').click();
  await until(() => d.querySelector('[data-ofd="remind"]'), 60);
  await until(() => d.querySelectorAll('.ofdlist .ofdrow').length >= 2, 60);
  const rowPaid = [...d.querySelectorAll('.ofdlist .ofdrow')].find(x => x.dataset.id === String(inv.id));
  check(rowPaid && /reminder fee open: .*5,00/.test(rowPaid.textContent), '#1368 8: the paid invoice shows the open reminder fee: ' + (rowPaid?.textContent || '').replace(/\s+/g, ' ').slice(0, 160));
  d.querySelector('[data-ofd="remind"]').click();
  await until(() => d.querySelector('#ofd-r-fee'), 40);
  const cb = d.querySelector(`[data-rid="${open2.id}"]`);
  check(!!cb, 'the open invoice is offered');
  if (cb) { cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const fee = d.querySelector('#ofd-r-fee'); fee.value = '15'; fee.dispatchEvent(new w.Event('input', {bubbles: true}));
  const wt = d.querySelector('#ofd-r-warn');
  check(wt && !wt.hidden && /actual costs/.test(wt.textContent) && /Not yet due/.test(wt.textContent), '#1368 7: hints for a high fee and an invoice not yet due: ' + (wt?.textContent || ''));
  fee.value = '0'; fee.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(!/actual costs/.test(wt?.textContent || ''), '#1368 7: no fee hint at 0');
  d.querySelector('.modal [data-m="close"]')?.click();
  w.close();

  // ================= #1368 8 + 9: reminder list and editor
  w = await boot({hash: 'office/offers'}); d = w.document;
  await until(() => d.querySelector('.ofdkinds [data-kind="reminder"]'), 60);
  d.querySelector('.ofdkinds [data-kind="reminder"]').click();
  await until(() => d.querySelectorAll('.ofdlist .ofdrow').length === 2, 60);
  const items = [...d.querySelectorAll('.ofdlist > li')];
  const last = items[items.length - 1]?.textContent || '';
  check(/Settled/.test(last) && /fee open: .*5,00/.test(last) && !!d.querySelector('.ofdlist .ofdgrp'), '#1368 9: settled reminder last, under "Settled", with the open fee: ' + last.replace(/\s+/g, ' ').slice(0, 140));
  w.close();
  w = await boot({hash: 'office/offers/' + rem.id}); d = w.document;
  await until(() => d.querySelector('.ofdfeeinfo'), 60);
  check(/Reminder fee .*5,00.*open/.test(d.querySelector('.ofdfeeinfo')?.textContent || '') && !!d.querySelector('[data-ofd="fee"][data-st="waived"]') && !!d.querySelector('[data-ofd="fee"][data-st="paid"]'),
    '#1368 8: the finalised reminder shows the open fee with Waive / Paid: ' + (d.querySelector('.ofdfeeinfo')?.textContent || ''));
  d.querySelector('[data-ofd="fee"][data-st="waived"]').click();
  await until(() => /waived/.test(d.querySelector('.ofdfeeinfo')?.textContent || ''), 40);
  check(/waived/.test(d.querySelector('.ofdfeeinfo')?.textContent || '') && !!d.querySelector('[data-ofd="fee"][data-st=""]'), '#1368 8: waived, "Open again" offered');
  w.close();

  // ================= #1381: language switch in the editor
  const SV = (await call('POST', '/api/office/services', {name_de: 'Farbkorrektur', daily_rate: 500})).id;
  const off = await call('POST', '/api/office/docs', {project_title: 'Imagefilm', items: [{service_id: SV, qty: 1}]});
  w = await boot({hash: 'office/offers/' + off.id}); d = w.document;
  await until(() => d.querySelector('#ofd-lang'), 60);
  const ls = d.querySelector('#ofd-lang'); ls.value = 'en'; ls.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => d.querySelector('.ofdlnote'), 60);
  check(/Dear Sir or Madam/.test(d.querySelector('#ofd-intro')?.value || ''), '#1381: the intro is English after the switch');
  check(/Farbkorrektur/.test(d.querySelector('.ofdlnote')?.textContent || '') && /no English name/.test(d.querySelector('.ofdlnote')?.textContent || ''), '#1381: note box names the position without an English name: ' + (d.querySelector('.ofdlnote')?.textContent || '').slice(0, 160));
  d.querySelector('[data-ofd="ln-x"]')?.click();
  await until(() => !d.querySelector('.ofdlnote'), 20);
  check(!d.querySelector('.ofdlnote'), '#1381: the note box closes');
  w.close();

  // ================= #1381: settings - the English choice shows the English text
  w = await boot({hash: 'office/settings'}); d = w.document;
  await until(() => d.querySelector('#os-intro-en'), 60);
  const oe = [...d.querySelectorAll('#os-intro-en option')].map(o => o.textContent).join(' | ');
  const od = [...d.querySelectorAll('#os-intro-de option')].map(o => o.textContent).join(' | ');
  check(/thank you|enquiry/i.test(oe) && !/vielen Dank/.test(oe) && /vielen Dank/.test(od), '#1381: English choice in English, German in German: ' + oe.slice(0, 120));
  w.close();

  console.log(`p2400_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
