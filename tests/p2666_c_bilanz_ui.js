// 2.666.0 (#3461) UI test, part C: the balance sheet page of the bookkeeping (static/js/office_ledger.js). Own container (start.sh),
// kalmido-suite: fresh
// jsdom, invented figures. The personal office of alice: the choice in the settings (income statement -> balance sheet), the button in the
// bookkeeping's bar, the page with balance sheet, profit and loss and trial balance (assets = equity and liabilities), an entry made
// in the dialog shows in the list and moves the result.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2666C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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

  // the choice in Settings > Company & office > Bank & taxes (the section of office_ledger.js)
  const w = await boot({hash: 'office/books'}); const d = w.document;
  check(await until(() => d.querySelector('#bk-year')), 'the bookkeeping is there');
  check(!d.querySelector('[data-bk-ledger]'), 'no balance sheet button with the income statement');
  w.eval("document.body.insertAdjacentHTML('beforeend', '<div id=\"ldbt\">' + ldb_setHtml() + '</div>')");
  check(await until(() => d.querySelector('#ldb-set #ldb-method')), 'the choice of the profit determination is drawn');
  check(d.querySelector('#ldb-method').value === 'euer' && d.querySelector('[data-ldb-suggest]'), 'income statement chosen, the balance sheet suggested for a GmbH');
  const sel = d.querySelector('#ldb-method'); sel.value = 'balance'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => d.querySelector('#ldb-set #ldb-size')), 'balance sheet chosen: the size appears');
  check((await call('GET', '/api/office/books/ledger/settings')).method === 'balance', 'the server has the balance sheet');
  d.querySelector('#ldbt')?.remove();

  // opening entries (bank and capital) and the page
  check((await call('POST', '/api/office/books/ledger/entries', {kind: 'open', day: `${Y}-01-01`, debit: '1200', credit: '9000', amount: '25000.00', text: 'Bank'})).http === 201, 'opening entry bank');
  check((await call('POST', '/api/office/books/ledger/entries', {kind: 'open', day: `${Y}-01-01`, debit: '9000', credit: '0800', amount: '25000.00', text: 'Stammkapital'})).http === 201, 'opening entry capital');
  w.eval('BK.info = null; BK.euer = null; ofcDraw()');
  check(await until(() => d.querySelector('[data-bk-ledger]')), 'the bookkeeping shows the balance sheet button');
  w.eval(`LDB.year = ${Y}; LDB.d = null; location.hash = '#office/books/ledger'`);
  check(await until(() => d.querySelector('[data-ldb-total="a"]')), 'the balance sheet page is drawn');
  const tot = s => d.querySelector(`[data-ldb-total="${s}"]`)?.textContent || '';
  check(/25,000\.00/.test(tot('a')) && tot('a') === tot('p'), `assets = equity and liabilities: ${tot('a')} / ${tot('p')}`);
  check(d.querySelector('[data-ldb-check="ok"]'), 'the check says debit = credit');
  check(d.querySelectorAll('[data-ldb-entry]').length === 2, 'the two opening entries listed');
  check(d.querySelector('a[href*="/api/office/books/ledger/bs.csv"]') && d.querySelector('a[href*="/api/office/books/ledger/susa.csv"]'), 'the CSV links');
  d.querySelector('[data-ldb="susa"]').click();
  check(await until(() => d.querySelector('.ldb-susa') && /1200/.test(d.querySelector('.ldb-susa').textContent)), 'the trial balance opens with the bank account');

  // an adjusting entry through the dialog: a provision of 500 moves the result
  d.querySelector('[data-ldb="add"]').click();
  check(await until(() => d.querySelector('#ldb-edebit')), 'the entry dialog');
  const set = (id, v) => { const x = d.querySelector('#' + id); x.value = v; x.dispatchEvent(new w.Event('input', {bubbles: true})); };
  set('ldb-edebit', '4950'); set('ldb-ecredit', '0970'); set('ldb-eamt', '500'); set('ldb-etext', 'Rückstellung Abschluss');
  d.querySelector('.modal [data-m="ok"], [data-m="ok"]').click();
  check(await until(() => d.querySelectorAll('[data-ldb-entry]').length === 3), 'the entry shows in the list');
  check(await until(() => /-500\.00|−500\.00|500\.00/.test(d.querySelector('[data-ldb-result]')?.textContent || '') && d.querySelector('[data-ldb-check="ok"]')),
    'the result moved by the provision, still balanced: ' + (d.querySelector('[data-ldb-result]')?.textContent || ''));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
