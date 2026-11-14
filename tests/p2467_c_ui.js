// 2.467.0 (#3456) UI tests: Anlage EUeR and annual VAT return. Own container (start.sh), jsdom, invented data.
// The bookkeeping links the tax forms, the page shows the lines of the year, switches to the annual return, a year without a form shows
// the note, the VAT paid is saved, CSV and PDF are offered.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2467C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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

  const w = await boot({hash: 'office/books'}); const d = w.document;
  check(await until(() => d.querySelector('[data-bk-taxforms]')), 'the bookkeeping links the tax forms');
  w.location.hash = 'office/books/taxforms/euer';
  // 2.826.0 (#5506): CI v2.787.0 red here once (green on the same code at night) without a hint why - say what was on screen
  if (!check(await until(() => d.querySelector('#tf-year') && d.querySelector('.bk-tab')), 'the page with the lines')) {
    console.log('p2467_c_ui: no lines - hash', w.location.hash, 'route', JSON.stringify(w.eval('S.route')), 'TF',
      JSON.stringify(w.eval('({kind: TF.kind, year: TF.year, oid: TF.oid, d: !!TF.d, rows: TF.d && TF.d.rows.length, err: TF.err, t: TF.t, seq: TF.seq, info: !!OFC.info, infoErr: OFC.infoErr})')),
      'view:', (d.querySelector('#view')?.textContent || '').replace(/\s+/g, ' ').slice(0, 400));
  }
  w.eval("TF.year = 2026; TF.d = null; ofcDraw()");
  check(await until(() => /Summe Betriebsausgaben/.test(d.querySelector('.bk-tab')?.textContent || '')), 'the wording of the form');
  check(await until(() => [...d.querySelectorAll('.bk-tab tr')].some(t => /^76/.test(t.textContent.trim()))), '2026: line 76');
  // #6135 (CI 14.11.2026 red: "Loading…" for good, seq 811): two loads at once - each stale answer drew and started the next load,
  // so a newer one was always under way; now a stale answer draws nothing and the newest one ends it
  const s0 = w.eval('TF.d = null; tfLoad(); tfLoad(); TF.seq');
  check(await until(() => w.eval('!!TF.d') && [...d.querySelectorAll('.bk-tab tr')].some(t => /^76/.test(t.textContent.trim()))), '#6135: two loads at once: the lines come');
  check(w.eval('TF.seq') - s0 <= 1 && !w.eval('TF.busy'), `#6135: no chain of loads behind it (seq ${s0} -> ${w.eval('TF.seq')})`);
  check(!!d.querySelector('a[href*="taxform/euer.csv?year=2026"]') && !!d.querySelector('a[href*="taxform/euer.pdf?year=2026"]'), 'CSV and PDF');
  check(/No tax advice/.test(d.querySelector('#view').textContent), 'the note');
  const inp = d.querySelector('#tf-paid'); inp.value = '12.50';
  inp.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/office/books/taxform/euer?year=2026')).vat_paid === '12.50'), 'VAT paid saved');
  w.location.hash = 'office/books/taxforms/ust';
  check(await until(() => /Vorauszahlungssoll/.test(d.querySelector('.bk-tab')?.textContent || '')), 'the annual return');
  w.eval("TF.year = new Date().getFullYear() - 6; TF.d = null; ofcDraw()");
  check(await until(() => /no line assignment/.test(d.querySelector('#view').textContent) && !d.querySelector('.bk-tab')), 'a year without a form: the note, no lines');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
