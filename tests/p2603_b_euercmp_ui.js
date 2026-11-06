// 2.603.0 (#4921) UI test, part B: the comparison with the year before under the EUeR. Own container (start.sh), jsdom, invented data.
// kalmido-suite: now=2027-02-15T10:00:00+01:00
// A year before only in the DATEV booking archive: the section shows the year, the year before marked "Source: DATEV archive",
// the deviation, the VAT liability and the archive's accounts behind the sums; a year without anything before says so.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2603B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});
const head = (cat, name, ver, y) => ['"EXTF"', '700', String(cat), `"${name}"`, String(ver), '20260101120000000', '', '"RE"', '""', '""', '1234567', '12345', `${y}0101`, '4', `${y}0101`, `${y}1231`].concat(Array(15).fill('')).join(';');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs'});
  check((await call('PUT', '/api/office/settings', {small_business: 0, datev_extf: {advisor_no: '1234567', client_no: '12345', fy_start: 1, acct_len: 4, chart: 'SKR03'}})).http === 200, 'office settings');
  const b21 = [head(21, 'Buchungsstapel', 13, 2025), '"Umsatz (ohne Soll/Haben-Kz)";"Soll/Haben-Kennzeichen";"WKZ Umsatz";"Konto";"Gegenkonto (ohne BU-Schlüssel)";"BU-Schlüssel";"Belegdatum";"Belegfeld 1";"Buchungstext"',
    '11900,00;"S";"EUR";1200;8400;;1503;"B-1";"Honorar Archiv"', '1190,00;"S";"EUR";4930;1200;"9";0204;"B-2";"Buerobedarf"'].join('\r\n') + '\r\n';
  const b20 = [head(20, 'Kontenbeschriftungen', 3, 2025), '"Konto";"Kontenbeschriftung";"Sprach-ID"', '8400;"Erlöse 19 % USt";"de-DE"', '4930;"Buerobedarf";"de-DE"'].join('\r\n') + '\r\n';
  const fd = new FormData();
  fd.append('file', new Blob([b21]), 'EXTF_Buchungsstapel_2025.csv'); fd.append('file', new Blob([b20]), 'EXTF_Kontenbeschriftungen_2025.csv');
  const imp = await fetch(B + 'api/office/books/archive/import', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(imp.status === 201, 'the archive of 2025 imported ' + imp.status);
  const api = await call('GET', '/api/office/books/euer/compare?year=2026');
  check(api.http === 200 && api.source === 'archive', 'the server: 2025 from the archive ' + api.source);

  const w = await boot({hash: 'office/books'}); const d = w.document;
  check(await until(() => d.querySelector('#bk-year') && d.querySelector('.bk-cmp')), 'the bookkeeping shows the comparison section');
  w.eval('BK.year = 2026; BK.info = null; BK.euer = null; ofcDraw()');
  const sec = () => d.querySelector('.bk-cmp[data-bk-cmpsrc]');
  check(await until(() => sec()?.dataset.bkCmpsrc === 'archive' && sec().querySelector('[data-bk-cmp="profit"]')), 'the year 2026 against the archive');
  const s = sec();
  check(s && /2026/.test(s.querySelector('thead').textContent) && /2025/.test(s.querySelector('thead').textContent), 'the two years in the head');
  check(s && /Source: DATEV archive/.test(s.querySelector('.bk-cmpmark')?.textContent || ''), 'the archive year is marked as such');
  const inc = s && s.querySelector('[data-bk-cmp="income_total"]');
  check(inc && /10,000\.00/.test(inc.textContent) && /-100 %/.test(inc.textContent), 'income: 10,000 net the year before, -100 % ' + (inc && inc.textContent));
  check(s && s.querySelector('[data-bk-cmp="vat_due"]') && /VAT liability/.test(s.querySelector('[data-bk-cmp="vat_due"]').textContent), 'the VAT liability row');
  check(s && s.querySelector('details.bk-cmpacc') && /8400/.test(s.querySelector('details.bk-cmpacc').textContent), 'the archive accounts behind the sums');
  check(s && /display only/.test(s.textContent) && /DATEV booking archive/.test(s.textContent), 'the notes: display only, from the archive');
  w.eval('BK.year = 2025; BK.info = null; BK.euer = null; ofcDraw()');
  check(await until(() => sec()?.dataset.bkCmpsrc === 'none' && d.querySelector('[data-bk-cmpnone]')), 'nothing for 2024: said so');
  check(!d.querySelector('.bk-cmpmark'), 'no archive mark without archive');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
