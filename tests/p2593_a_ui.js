// 2.593.0 A (#4891) UI tests: the year pickers of the office come from the data. Own container (start.sh), jsdom, invented data.
// kalmido-suite: fresh
// A person without an organisation (the personal office; freelancer-matrix: office):
// - travel without a trip: "All years" + this year only; a trip of 2019: "All years", this year .. 2019 without gaps, never next year;
//   a chosen year outside the span (the jump after an import) stays a choice
// - entertainment receipts: a meal of 2021 -> this year .. 2021
// - bookkeeping without receipts / invoices: this year + last year (the annual return); the VAT return: from the oldest data
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2593A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const opts = (d, sel) => [...d.querySelectorAll(`${sel} option`)].map(o => o.value).join();
const range = (hi, lo) => { const out = []; for (let y = hi; y >= lo; y--) out.push(String(y)); return out.join(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs,travel'});
  const me = (await call('GET', '/api/state')).me;
  const Y = new Date().getFullYear();

  // ---- travel without a trip
  let w = await boot({hash: 'office/travel'}), d = w.document;
  check(await until(() => d.querySelector('#rk-year'), 80), 'the travel tab');
  check(opts(d, '#rk-year') === `,${Y}`, `no trip: All years + this year only (${opts(d, '#rk-year')})`);
  w.close();

  // ---- a trip of 2019
  check((await call('POST', '/api/office/trips', {date_from: '2019-05-06', date_to: '2019-05-07', dest: 'Hamburg', country: 'DE', people: [{id: me.id}]})).http === 201, 'a trip of 2019');
  w = await boot({hash: 'office/travel'}); d = w.document;
  check(await until(() => d.querySelector('#rk-year') && w.eval('!!RK.data?.years'), 80), 'the travel tab with the years');
  check(opts(d, '#rk-year') === ',' + range(Y, 2019), `2019: All years, this year .. 2019 without gaps (${opts(d, '#rk-year')})`);
  check(!d.querySelector(`#rk-year option[value="${Y + 1}"]`), 'no empty next year');
  const sel = d.querySelector('#rk-year'); sel.value = '2019'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => d.querySelectorAll('.rklist .ofcrow').length === 1 && d.querySelector('#rk-year')?.value === '2019', 80), '2019 chosen: the trip of 2019');
  w.eval(`RK.year = '2012'; ofcDraw();`);  // the jump of the import to a year outside the span
  check(await until(() => d.querySelector('#rk-year')?.value === '2012', 40) && opts(d, '#rk-year') === ',' + range(Y, 2019) + ',2012', `a chosen year outside stays a choice (${opts(d, '#rk-year')})`);
  w.close();

  // ---- entertainment receipts
  check((await call('POST', '/api/office/meals', {date: '2021-05-14', place_name: 'Trattoria Esempio', occasion: 'Follow-up order', host: {id: me.id},
    amounts: [{kind: 'food', rate: 19, gross: '119.00'}]})).http === 201, 'a meal of 2021');
  w = await boot({hash: 'office/meals'}); d = w.document;
  check(await until(() => d.querySelector('#bw-year'), 80), 'the entertainment receipts tab');
  check(opts(d, '#bw-year') === ',' + range(Y, 2021), `meals: All years, this year .. 2021 (${opts(d, '#bw-year')})`);
  w.close();

  // ---- bookkeeping without receipts / invoices
  w = await boot({hash: 'office/books'}); d = w.document;
  check(await until(() => d.querySelector('#bk-year') && w.eval('!!BK.info'), 80), 'the bookkeeping tab');
  check(opts(d, '#bk-year') === range(Y, Y - 1), `books without data: this year + last year (${opts(d, '#bk-year')})`);
  if (d.querySelector('#bk-pyear')) {
    const py = String(w.eval('BK.pyear'));
    check(opts(d, '#bk-pyear') === (py === String(Y) ? String(Y) : range(Y, Y - 1)), `VAT return without data: this year (+ the preselected period's year) (${opts(d, '#bk-pyear')})`);
  }
  w.close();

  // ---- mileage allowance (settings): the next year stays, so its rate can be set in advance (an input, not a filter)
  w = await boot({hash: 'office/logbook'}); d = w.document;
  check(await until(() => w.eval("typeof lb_rateSetHtml === 'function' && !!OFC.info"), 80), 'the logbook module');
  const rs = w.eval('lb_rateSetHtml()');
  check(rs.includes(`<option value="${Y + 1}"`) || rs.includes(`>${Y + 1}<`), `mileage allowance: next year in the year picker (${rs.length})`);
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
