// 2.685.0 (#5128) UI test, part B: the balance sheet page (static/js/office_ledger.js). Own container (start.sh), jsdom, invented
// kalmido-suite: fresh
// figures. The personal office of alice with the balance sheet: (c) an opening that does not balance (a balance on account 9000)
// shows its difference before the closing; (3) the PDF links next to the CSV of the balance sheet and the profit and loss account,
// the server answers them with a PDF; (4) an entry by hand changed in the edit dialog (PUT with its version) shows the new amount,
// the opening balances again and the hint goes; a stale version (changed meanwhile) is refused, the dialog stays open.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2685B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});
const Y = new Date().getFullYear();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs'});
  check((await call('PUT', '/api/office/settings', {small_business: 0, currency: 'EUR', datev_extf: {chart: 'SKR03'}, company_fields: {name: 'Beispiel Studio GmbH', country: 'DE'}})).http === 200, 'office settings');
  check((await call('PUT', '/api/office/books/ledger/settings', {method: 'balance'})).method === 'balance', 'balance sheet chosen');
  // the opening: bank 25,000 against 9000, capital only 24,000 -> 1,000 left on account 9000
  check((await call('POST', '/api/office/books/ledger/entries', {kind: 'open', day: `${Y}-01-01`, debit: '1200', credit: '9000', amount: '25000.00', text: 'Bank'})).http === 201, 'opening entry bank');
  const cap = await call('POST', '/api/office/books/ledger/entries', {kind: 'open', day: `${Y}-01-01`, debit: '9000', credit: '0800', amount: '24000.00', text: 'Stammkapital'});
  check(cap.http === 201, 'opening entry capital (too small)');

  const w = await boot({hash: 'office/books'}); const d = w.document;
  check(await until(() => d.querySelector('#bk-year')), 'the bookkeeping is there');
  w.eval(`LDB.year = ${Y}; LDB.d = null; location.hash = '#office/books/ledger'`);
  check(await until(() => d.querySelector('[data-ldb-total="a"]')), 'the balance sheet page is drawn');
  // (c) the opening that does not balance is named with its difference
  const op = d.querySelector('[data-ldb-opening]');
  check(op && /1,000\.00/.test(op.textContent), 'the opening difference is shown: ' + (op?.textContent || '-'));
  // (3) the PDF links next to the CSV, the server gives a PDF
  for (const what of ['bs', 'pl']) {
    const a = d.querySelector(`a[data-ldb-pdf="${what}"]`);
    check(a && a.getAttribute('href') === `/api/office/books/ledger/${what}.pdf?year=${Y}` && a.closest('.ofcbar')?.querySelector(`a[href*="/${what}.csv"]`), `the PDF link of ${what} next to its CSV`);
    const res = await fetch(B + `api/office/books/ledger/${what}.pdf?year=${Y}`, {headers: {...H, Cookie: CK}});
    const head = Buffer.from(await res.arrayBuffer()).subarray(0, 5).toString('latin1');
    check(res.ok && head === '%PDF-', `the server answers ${what}.pdf with a PDF (${res.status} ${head})`);
  }
  // (4) the edit dialog: the capital entry 24,000 -> 25,000
  const btn = d.querySelector(`[data-ldb="edit"][data-id="${cap.id}"]`);
  check(btn, 'an edit button on the entry by hand');
  btn?.click();
  check(await until(() => d.querySelector('#ldb-eamt')), 'the edit dialog opens');
  check(d.querySelector('#ldb-edebit').value === '9000' && d.querySelector('#ldb-ecredit').value === '0800' && /24,?000\.00/.test(d.querySelector('#ldb-eamt').value)
    && d.querySelector('#ldb-ekind').value === 'open', 'the dialog holds the entry: ' + d.querySelector('#ldb-eamt').value);
  // a stale version: the entry changes meanwhile (another device) -> 409, the dialog stays
  const mid = await call('PUT', `/api/office/books/ledger/entries/${cap.id}`, {text: 'Stammkapital (Notar)', expect_updated_at: cap.updated_at});
  check(mid.http === 200, 'the entry changed elsewhere');
  const set = (id, v) => { const x = d.querySelector('#' + id); x.value = v; x.dispatchEvent(new w.Event('input', {bubbles: true})); };
  set('ldb-eamt', '25000');
  d.querySelector('.modal [data-m="ok"], [data-m="ok"]').click();
  check(await until(() => (d.querySelector('.modal .aerr, .aerr')?.textContent || '').trim()), 'a stale version is refused: the dialog names the error');
  check(d.querySelector('#ldb-eamt'), 'the dialog stays open');
  const cur = (await call('GET', `/api/office/books/ledger?year=${Y}`)).entries.find(e => e.id === cap.id);
  check(cur && cur.amount === '24000.00', 'nothing saved on a stale version: ' + cur?.amount);
  d.querySelector('[data-m="close"]')?.click();
  check(await until(() => !d.querySelector('#ldb-eamt')), 'the dialog closed');
  w.eval('LDB.d = null; ofcDraw()');
  check(await until(() => d.querySelector(`[data-ldb="edit"][data-id="${cap.id}"]`)), 'the page drawn again');
  d.querySelector(`[data-ldb="edit"][data-id="${cap.id}"]`).click();
  check(await until(() => d.querySelector('#ldb-etext')?.value === 'Stammkapital (Notar)'), 'the dialog holds the current version');
  set('ldb-eamt', '25000');
  d.querySelector('.modal [data-m="ok"], [data-m="ok"]').click();
  check(await until(() => /25,000\.00/.test(d.querySelector(`[data-ldb-entry="${cap.id}"]`)?.textContent || '')), 'the list shows the new amount');
  check(await until(() => !d.querySelector('[data-ldb-opening]') && d.querySelector('[data-ldb-check="ok"]')), 'the opening balances: the hint is gone');
  const sv = (await call('GET', `/api/office/books/ledger?year=${Y}`)).entries.find(e => e.id === cap.id);
  check(sv && sv.amount === '25000.00' && sv.kind === 'open' && sv.text === 'Stammkapital (Notar)', 'the server has the change: ' + JSON.stringify(sv));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
