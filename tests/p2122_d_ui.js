// 2.122.0 D (#2315) UI tests: VAT only once a year. Own container (start.sh), jsdom, invented data.
// The tax dates offer "Yearly (annual return only)" (no extension, the hint on the tax adviser, "Annual VAT return" in the preview);
// the VAT figures of the bookkeeping have "Whole year" (no month / quarter field, last year preselected) and follow the setting.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2122D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs'});
  check((await call('PUT', '/api/office/settings', {small_business: 0})).http === 200, 'no small business');
  const yPrev = new Date().getFullYear() - 1;

  const w = await boot({hash: 'office/books/ustva'}); const d = w.document;
  check(await until(() => d.querySelector('#bk-ustva .seg') && d.querySelector('#txd-ustva'), 80), 'the bookkeeping tab with the VAT figures and the tax dates');
  const seg = () => [...d.querySelectorAll('#bk-ustva [data-bk="mode"]')];
  check(seg().map(b => b.dataset.v).join() === 'month,quarter,year' && /Whole year/.test(seg()[2]?.textContent || ''), 'the period: month / quarter / whole year');
  check(w.eval('BK.mode') === 'quarter' && !!d.querySelector('#bk-period'), 'no tax dates: quarters by default, the quarter field');

  // whole year by hand
  seg()[2].click();
  check(await until(() => w.eval(`!!BK.ustva && BK.ustva.period === 'y' && BK.pyear === ${yPrev}`), 40), 'whole year: last year loaded');
  check(await until(() => !d.querySelector('#bk-period') && d.querySelector('#bk-pyear')?.value === String(yPrev) && seg()[2].getAttribute('aria-pressed') === 'true', 40),
    'whole year: no month / quarter field, the year field shows last year');
  seg()[1].click();
  check(await until(() => w.eval(`BK.mode === 'quarter' && /^q[1-4]$/.test(BK.period)`) && !!d.querySelector('#bk-period'), 40), 'back to quarters');

  // the tax dates: yearly
  check(d.querySelectorAll('#txd-ustva option').length === 4 && !!d.querySelector('#txd-ustva option[value="year"]')
    && /Yearly \(annual return only\)/.test(d.querySelector('#txd-ustva option[value="year"]').textContent), 'the tax dates offer "Yearly (annual return only)"');
  const sel = d.querySelector('#txd-ustva'); sel.value = 'year';
  sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/office/tax-dates')).ustva === 'year', 40), 'yearly: saved at once');
  check(await until(() => d.querySelector('#txd-ustva')?.value === 'year' && !d.querySelector('[data-txd="ustva_ext"]'), 40), 'yearly: no deadline extension');
  check(/tax adviser/.test(d.querySelector('[data-txd-root]')?.textContent || ''), 'yearly: the hint on the tax adviser');
  check(await until(() => /Annual VAT return/.test(d.querySelector('.txdnext')?.textContent || ''), 40), 'yearly: the preview names the annual return');
  check(await until(() => w.eval(`BK.mode === 'year' && BK.period === 'y' && BK.pyear === ${yPrev}`) && !d.querySelector('#bk-period'), 60),
    'the bookkeeping follows: whole year, last year preselected');

  // monthly again: the bookkeeping follows too
  const sel2 = d.querySelector('#txd-ustva'); sel2.value = 'month';
  sel2.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => w.eval(`BK.mode === 'month' && /^m(0[1-9]|1[0-2])$/.test(BK.period)`), 60), 'monthly: the bookkeeping shows months');
  check(await until(() => !!d.querySelector('[data-txd="ustva_ext"]'), 40), 'monthly: the extension is back');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
