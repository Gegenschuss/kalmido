// 2.121.0 UI tests of part A (#2092; own container, start.sh). jsdom. Invented companies and figures only:
// - document sheet of an uploaded invoice: one line "Recognised: supplier · No. · net · VAT 19 % · gross" with Discard /
//   Take over; Take over sets sender and VAT rate (one undo step; Undo brings the old values and the line back); the invoice
//   number stays visible with a copy button; Discard hides the line (one undo step)
// - phone width: the line and its buttons are there
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const {execFileSync} = require('child_process');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2121A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const INV = ['Muster Bau GmbH · Werkstraße 12 · 54321 Beispielort', 'Herrn', 'Max Kunde', 'Am Feld 3', '54320 Kundendorf', 'Rechnung',
  'Rechnungs-Nr.: RE-2026-118', 'Kundennummer: K-5521', 'Datum: 06.10.2026', 'Arbeitszeit 4 Std.   240,00 €', 'Material  60,00 €',
  'Nettobetrag  300,00 €', 'zzgl. 19 % MwSt.  57,00 €', 'Gesamtbetrag  357,00 €', 'USt-IdNr. DE123456789'].join('\n');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: (st.settings?.features || '') + ',docs,files'});
  const fd = new FormData();
  fd.append('ws', 'private');
  fd.append('files', new Blob([INV], {type: 'text/plain'}), 'rechnung-bau.txt');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json();
  const D = (up.ids || [])[0];
  const doc = await until(async () => { const x = await call('GET', `/api/docs/${D}`); return x.state === 'done' ? x : null; }, 150);
  check(doc?.extracted?.supplier === 'Muster Bau GmbH', 'setup: recognised ' + JSON.stringify(doc?.extracted || {}).slice(0, 200));

  // ================= the document sheet
  const v = await boot({user: 'alice', hash: `docs/${D}`}), e = v.document;
  const line = await until(() => e.querySelector('.rx-slot .rx-sug'), 80);
  const t = line?.textContent || '';
  check(line && /Recognised/.test(t) && /Muster Bau GmbH/.test(t) && /No\. RE-2026-118/.test(t) && /VAT 19 %/.test(t) && /300[.,]00/.test(t) && /357[.,]00/.test(t),
    'the line: supplier, number, net, rate, gross ' + t.replace(/\s+/g, ' ').slice(0, 200));
  check(line?.querySelector('[data-rx^="apply"]') && line?.querySelector('[data-rx^="dismiss"]'), 'Take over + Discard');
  check(/RE-2026-118/.test(e.querySelector('.rx-no')?.textContent || '') && e.querySelector('.rx-no [data-rx^="copy"]'), 'the invoice number with a copy button');
  line.querySelector('[data-rx^="apply"]').click();
  await until(() => !e.querySelector('.rx-sug') && e.querySelector('#dc-sender')?.value === 'Muster Bau GmbH' && e.querySelector('#rc-vat')?.value === '19', 80);
  check(e.querySelector('#dc-sender')?.value === 'Muster Bau GmbH', 'Take over: the sender');
  check(e.querySelector('#rc-vat')?.value === '19', 'Take over: the VAT rate of the receipt');
  check(!e.querySelector('.rx-sug') && e.querySelector('.rx-no'), 'taken over: the line goes, the number stays');
  check(v.eval(`HIST.undo.length && /taken over/.test(HIST.undo[HIST.undo.length - 1].label)`), 'Take over = one undo step');
  await v.eval(`histStep('undo')`);
  await until(() => e.querySelector('.rx-sug') && !e.querySelector('#dc-sender')?.value, 80);
  check(e.querySelector('.rx-sug') && !e.querySelector('#dc-sender')?.value, 'Undo: the old values and the line are back');
  check(((await call('GET', `/api/docs/${D}/receipt`)).receipt || {}).vat_pct == null, 'Undo: no VAT rate on the server');
  e.querySelector('.rx-sug [data-rx^="dismiss"]').click();
  await until(() => !e.querySelector('.rx-sug'));
  check(!e.querySelector('.rx-sug') && e.querySelector('.rx-no'), 'Discard: the line goes, the number stays');
  check(v.eval(`HIST.undo.length && /discarded/.test(HIST.undo[HIST.undo.length - 1].label)`), 'Discard = one undo step');
  await v.eval(`histStep('undo')`);
  await until(() => e.querySelector('.rx-sug'));
  check(e.querySelector('.rx-sug'), 'Undo of Discard: the line is back');
  v.close();

  // ================= phone width
  const m = await boot({user: 'alice', hash: `docs/${D}`, mobile: true}), f = m.document;
  const mb = await until(() => f.querySelector('.rx-sug [data-rx^="apply"]'), 80);
  check(mb && f.querySelector('.rx-sug [data-rx^="dismiss"]'), 'phone: the line with its buttons');
  m.close();

  console.log(`p2121_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
