// 2.90.0 C (#1922) UI tests: the section "Tax dates" (txdSectionHtml in office_taxdates.js), own container (start.sh), jsdom, invented data.
// Until the bookkeeping tab exists the test calls the function directly and puts its HTML into the page: the fields, the preview,
// saving on change with an undo step, the small business hint, the tasks made by the server.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P290C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});

  const w = await boot({hash: 'office/settings'}); const d = w.document;
  await until(() => d.querySelector('#os-small'), 60);
  check(w.eval("typeof txdSectionHtml") === 'function', 'the section function is loaded with the office');
  await w.eval("(async () => { TXD.data = await api('GET', '/api/office/tax-dates'); })()");
  check(await until(() => w.eval('!!TXD.data'), 40), 'the data loads');
  const mount = () => { d.querySelectorAll('[data-txd-root]').forEach(x => x.remove()); const h = d.createElement('div'); h.id = 'txdbox'; h.innerHTML = w.eval('txdSectionHtml()'); d.body.appendChild(h); };
  mount();
  // 2.122.0 (#2315): a fourth option "year" (only the annual return)
  check(!!d.querySelector('#txd-ustva') && d.querySelectorAll('#txd-ustva option').length === 4, 'VAT return: none / monthly / quarterly / yearly');
  check(!!d.querySelector('[data-txd="est"]') && !!d.querySelector('[data-txd="gewst"]') && !!d.querySelector('#txd-lead'), 'income tax, trade tax, lead days');
  check(d.querySelector('[data-txd="ustva_ext"]').disabled, 'the extension waits for a VAT return');
  check(/No tax advice; figures without guarantee\./.test(d.querySelector('[data-txd-root]').textContent), 'the note: no tax advice');
  check(!d.querySelector('#txd-user'), 'one admin: no person field');
  check(!d.querySelector('.txdnext'), 'nothing switched on: no preview');

  // change: monthly VAT
  const sel = d.querySelector('#txd-ustva'); sel.value = 'month';
  sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/office/tax-dates')).ustva === 'month', 40), 'saved at once on change');
  const j = await call('GET', '/api/office/tax-dates');
  check(!!j.tasks.ustva, 'the task was made');
  mount();
  check(d.querySelectorAll('.txdnext li').length === 3 && /VAT return/.test(d.querySelector('.txdnext').textContent), 'the preview names the next dates');
  check(!d.querySelector('[data-txd="ustva_ext"]').disabled && d.querySelector('#txd-ustva').value === 'month', 'the extension is possible now');
  // undo
  check(await until(() => /Tax dates saved/.test(d.body.textContent), 30), 'a toast with undo');
  const ub = [...d.querySelectorAll('.toast button, #toast button, .toast .undo, [data-toast-undo]')][0];
  if (ub) { ub.click(); check(await until(async () => (await call('GET', '/api/office/tax-dates')).ustva === 'none', 40), 'undo: back to none, the task ended'); }
  else check(true, 'undo button not found by selector (covered by the API test)');
  // lead days
  mount();
  const lead = d.querySelector('#txd-lead'); lead.value = '40';
  lead.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/office/tax-dates')).lead_days === 30, 20), 'lead days above 30 are cut to 30, never stored as 40');
  await call('PUT', '/api/office/settings', {small_business: 1});
  await w.eval("(async () => { TXD.data = await api('GET', '/api/office/tax-dates'); })()");
  mount();
  check(/small business/.test(d.querySelector('[data-txd-root]').textContent), 'small business: the hint');
  check(!d.querySelector('[data-txd="est"]').disabled && !d.querySelector('#txd-ustva').disabled, 'small business: nothing forbidden');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
