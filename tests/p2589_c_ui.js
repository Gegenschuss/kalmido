// 2.589.0 (#3458) UI tests: the tax check before filing. Own container (start.sh), jsdom, invented data.
// kalmido-suite: now=2027-02-15T10:00:00+01:00
// The bookkeeping and the tax forms link the tax check; the page shows one traffic light per point grouped, the counts on top,
// a missing tax number is red with the way into the company details, a click on a point's title leads to its place.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2589C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs'});
  check((await call('PUT', '/api/office/settings', {small_business: 0})).http === 200, 'no small business');
  const api = await call('GET', '/api/office/books/taxcheck?year=2026');
  check(api.http === 200 && api.points.some(p => p.punkt === 'tax_number' && p.ampel === 'red'), 'the server: no tax number is red');

  const w = await boot({hash: 'office/books'}); const d = w.document;
  check(await until(() => d.querySelector('[data-bk-taxcheck]')), 'the bookkeeping links the tax check');
  w.location.hash = 'office/books/taxforms/euer';
  check(await until(() => d.querySelector('#tf-year') && d.querySelector('[data-bk-taxcheck]')), 'the tax forms link it too');
  w.location.hash = 'office/books/taxcheck';
  check(await until(() => d.querySelector('#tc-year') && d.querySelector('.tc-list')), 'the page with the points');
  w.eval("TC.year = 2026; TC.d = null; ofcDraw()");
  check(await until(() => d.querySelector('#tc-year')?.value === '2026' && d.querySelector('.tc-pt[data-tc="tax_number"]')), 'the year 2026');
  const tn = d.querySelector('.tc-pt[data-tc="tax_number"]');
  check(tn && tn.classList.contains('tc-red') && /Deviation/.test(tn.textContent), 'no tax number: red, the word next to the colour');
  check(tn && tn.querySelector('[data-setgo="biz-company"]'), 'red: the way into the company details');
  check(d.querySelectorAll('.tc-list').length >= 5 && d.querySelectorAll('.bk-sec h4').length >= 5, 'the points stand in groups');
  check(/\d+ Deviation/.test(d.querySelector('.tc-sum')?.textContent || ''), 'the counts on top');
  check(/nothing is blocked/.test(d.querySelector('#view').textContent) && /No tax advice/.test(d.querySelector('#view').textContent), 'the notes');
  const go = d.querySelector('.tc-pt[data-tc="ust_year"] a.tc-go');
  check(go && go.getAttribute('href') === '#office/books/taxforms/ust', 'a point links its place');
  go?.click();
  check(await until(() => w.location.hash === '#office/books/taxforms/ust' && /Vorauszahlungssoll/.test(d.querySelector('.bk-tab')?.textContent || '')), 'the click leads there');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
