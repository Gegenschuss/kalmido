// 2.114.0 C (#2256) UI tests: number ranges (office_numranges.js), own container (start.sh), jsdom, invented data.
// The settings page shows the next running number of every series below the number schemes: the preview follows the
// input, an invoice jump asks for a reason, "Apply" saves (confirm) and the scheme's "next: …" follows. The document editor:
// a click on the pencil next to the number opens the field; after saving the head AND the document list show the new
// number at once; a change made elsewhere (the console) reaches an open list with the next state load.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2114C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const Y = String(new Date().getFullYear());
const range = async k => (await call('GET', '/api/office/number-ranges')).ranges.find(x => x.kind === k);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const st = await call('PUT', '/api/office/settings', {offer_scheme: 'A-{seq:03}', invoice_scheme: 'RE-{yyyy}-{seq:03}'});
  check(st.http === 200, 'schemes set ' + st.http);

  // ---- the settings page: the block below the number schemes (the person without an organisation = its own admin)
  const w = await boot({hash: 'office/settings'}); const d = w.document;
  w.confirm = () => true;
  check(!!await until(() => d.querySelector('#onum-invoice'), 80), 'the block "Next running number" is there');
  check(d.querySelectorAll('#onum-box .onumrow').length === 4, 'four series: quotation, invoice, credit note, reminder');
  check(!d.querySelector('#onum-box input[id^="os-"]') && d.querySelector('#onum-box').hasAttribute('data-fg-skip'), 'not part of the settings save (no os- ids, form guard skipped)');
  const rowI = () => d.querySelector('.onumrow[data-kind="invoice"]');
  check(new RegExp('applies to ' + Y).test(rowI().textContent) && /at least 1/.test(rowI().textContent), 'invoice: "applies to <year>", smallest value');
  check(!/applies to/.test(d.querySelector('.onumrow[data-kind="offer"]').textContent), 'quotation without a year in the scheme: no year hint');
  check(rowI().querySelector('[data-onum="set"]').disabled && !d.querySelector('#onum-invoice-why'), 'unchanged: Apply off, no reason field');
  const inp = d.querySelector('#onum-invoice'); inp.value = '1001';
  inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => d.querySelector('#onum-invoice-why')), 'a jump in the invoice series asks for a reason');
  check(d.querySelector('#onum-invoice-pv').textContent.includes(`RE-${Y}-1001`), 'the preview shows the finished number: ' + d.querySelector('#onum-invoice-pv').textContent);
  check(d.activeElement && d.activeElement.id === 'onum-invoice', 'the focus stays in the field');
  check(!rowI().querySelector('[data-onum="set"]').disabled, 'Apply on');
  // without a reason: the server's error at the row
  rowI().querySelector('[data-onum="set"]').click();
  check(await until(() => /reason/.test(rowI().querySelector('[role="alert"]')?.textContent || '')), 'without a reason: the error at the row');
  check((await range('invoice')).next === 1, 'nothing saved without a reason');
  const why = d.querySelector('#onum-invoice-why'); why.value = 'Nummern bis 1000 im Altprogramm';
  why.dispatchEvent(new w.Event('input', {bubbles: true}));
  rowI().querySelector('[data-onum="set"]').click();
  check(await until(async () => (await range('invoice')).next === 1001, 40), 'Apply: the series continues at 1001');
  check(await until(() => /at least 1001/.test(rowI().textContent) && d.querySelector('#onum-invoice').value === '1001'), 'the row shows the new state');
  check(await until(() => (d.querySelector('#os-inv-scheme-pv')?.textContent || '').includes(`RE-${Y}-1001`)), 'the scheme\'s preview follows: ' + d.querySelector('#os-inv-scheme-pv')?.textContent);
  const log = await call('GET', '/api/office/log?limit=20');
  check(log.log.some(x => x.target === 'number_range' && x.detail.after.reason === 'Nummern bis 1000 im Altprogramm'), 'the reason is in the office log');
  // a quotation needs no reason
  const io = d.querySelector('#onum-offer'); io.value = '40'; io.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(!d.querySelector('#onum-offer-why'), 'quotations: no reason field');
  d.querySelector('.onumrow[data-kind="offer"] [data-onum="set"]').click();
  check(await until(async () => (await range('offer')).next === 40, 40), 'quotation series at 40');
  w.close();

  // ---- the document editor: the draft's number, head and list at once
  const o1 = await call('POST', '/api/office/docs', {kind: 'offer', items: [{title: 'Schnitt', qty: 1, rate: 100}]});
  check(o1.http === 201 && o1.number === 'A-040', 'a new quotation gets A-040: ' + o1.number);
  const w2 = await boot({hash: 'office/offers'}); const d2 = w2.document;
  check(await until(() => (d2.querySelector('.ofdlist')?.textContent || '').includes('A-040'), 80), 'the list shows A-040');
  w2.location.hash = `office/offers/${o1.id}`;
  check(!!await until(() => d2.querySelector('[data-onum="doc-open"]'), 60), 'the draft has the pencil next to its number');
  d2.querySelector('[data-onum="doc-open"]').click();
  const din = await until(() => d2.querySelector('#onum-doc'));
  check(din && din.value === 'A-040', 'the field holds the number');
  check(/counter of the series stays/.test(d2.querySelector('.onumdoc')?.textContent || ''), 'quotation: the hint that the counter stays');
  din.value = 'A-777'; din.dispatchEvent(new w2.Event('input', {bubbles: true}));
  d2.querySelector('[data-onum="doc-save"]').click();
  check(await until(() => (d2.querySelector('.ofdhead .ofdnum b')?.textContent || '').includes('A-777') && !d2.querySelector('#onum-doc')), 'the head shows A-777 at once');
  check((await call('GET', `/api/office/docs/${o1.id}`)).number === 'A-777', 'saved on the server');
  w2.location.hash = 'office/offers';
  check(await until(() => { const t = d2.querySelector('.ofdlist')?.textContent || ''; return t.includes('A-777') && !t.includes('A-040'); }, 60), 'the list shows the new number at once');
  // a used number: the error at the field
  const o2 = await call('POST', '/api/office/docs', {kind: 'offer'});
  w2.location.hash = `office/offers/${o2.id}`;
  await until(() => w2.eval('OFD.doc && OFD.doc.id') === o2.id, 60);
  (await until(() => d2.querySelector('[data-onum="doc-open"]'))).click();
  const din2 = await until(() => d2.querySelector('#onum-doc')); din2.value = 'A-777';
  din2.dispatchEvent(new w2.Event('input', {bubbles: true}));
  d2.querySelector('[data-onum="doc-save"]').click();
  check(await until(() => /already used/.test(d2.querySelector('.onumdoc [role="alert"]')?.textContent || '')), 'a used number: the error at the field');
  d2.querySelector('[data-onum="doc-x"]').click();
  check(await until(() => !d2.querySelector('#onum-doc')), 'Cancel closes the field');
  // a sent quotation: no pencil
  await call('POST', `/api/office/docs/${o1.id}/status`, {status: 'sent'});
  w2.location.hash = `office/offers/${o1.id}`;
  await until(() => w2.eval('OFD.doc && OFD.doc.id') === o1.id, 60);
  await w2.eval(`ofdLoadDoc(${o1.id}, true)`);
  check(await until(() => d2.querySelector('.ofdhead') && w2.eval('OFD.doc.status') === 'sent') && !d2.querySelector('[data-onum="doc-open"]'), 'a sent quotation: no number field');
  // a change made elsewhere (the console) reaches the open list with the next state load
  w2.location.hash = 'office/offers';
  await until(() => (d2.querySelector('.ofdlist')?.textContent || '').includes(o2.number || 'A-041'), 60);
  const ch = await call('POST', `/api/office/docs/${o2.id}/number`, {number: 'A-555'});
  check(ch.http === 200, 'number changed through the API');
  await w2.eval('load()');
  check(await until(() => (d2.querySelector('.ofdlist')?.textContent || '').includes('A-555'), 60), 'the open list follows a change made elsewhere');
  w2.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
