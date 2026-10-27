// 2.141.0 UI tests of part C (#2142 #2143; own container, start.sh). jsdom:
// - the disposition has the download links CSV and ICS (period, filter and area of the view in the address)
// - Newsletter sheet: "Import consents" with a file field; a chosen file shows the preview (counts, problem lines with line
//   numbers), "Import" stores the consents and the preview goes away; nothing is stored before "Import"
// freelancer-matrix: hub  (the person without an organisation uses the same client code; here: the instance admin's own space)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2141C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  const feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean));
  for (const f of ['contacts', 'collab', 'workload', 'dispo']) feats.add(f);
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});

  // ================= disposition: download links
  let w = await boot({user: 'alice', hash: 'workload'}), d = w.document;
  (await until(() => d.querySelector('#view .ab2tabs [data-v="dispo"]')))?.click();
  const csv = await until(() => d.querySelector('#view a.dp-export[data-f="csv"]'));
  const ics = d.querySelector('#view a.dp-export[data-f="ics"]');
  check(csv && ics, 'the disposition has a CSV and an ICS download');
  check(csv && /^\/api\/team\/dispo\/export\?/.test(csv.getAttribute('href')) && /format=csv/.test(csv.getAttribute('href')) && /days=7/.test(csv.getAttribute('href')), 'CSV link: route, format, period');
  check(ics && /format=ics/.test(ics.getAttribute('href')) && ics.hasAttribute('download'), 'ICS link: format, download');
  d.querySelector('#view [data-act="dp-filter"][data-v="people"]')?.click();
  check(await until(() => /filter=people/.test(d.querySelector('#view a.dp-export[data-f="csv"]')?.getAttribute('href') || '')), 'the filter of the view is in the link');
  w.close();

  // ================= consent import
  const bk = await call('POST', '/api/books', {name: 'Customers'});
  const c1 = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Anna Alpha', emails: [{value: 'anna@example.com'}]});
  w = await boot({user: 'alice', hash: 'contacts'}); d = w.document;
  (await until(() => d.querySelector('#view [data-ct="menu"]')))?.click();
  (await until(() => [...d.querySelectorAll('.menu-list [role="menuitem"]')].find(b => /Newsletter/.test(b.textContent))))?.click();
  const inp = await until(() => d.querySelector('.nwl-md #nwl-imp-file'));
  check(inp, 'the newsletter sheet has the import field');
  const text = 'E-Mail;Datum;Quelle\nanna@example.com;05.03.2025;Fair\nbroken;05.03.2025;x\n';
  Object.defineProperty(inp, 'files', {value: [{name: 'consents.csv', size: text.length, text: async () => text}]});
  inp.dispatchEvent(new w.Event('change', {bubbles: true}));
  const sum = await until(() => d.querySelector('.nwl-md .nwl-imp-sum'));
  check(sum && /2 rows: 1 valid, 1 with a problem/.test(sum.textContent), 'the preview counts ' + (sum && sum.textContent));
  check(/Line 3/.test(d.querySelector('.nwl-md .nwl-imp-err')?.textContent || ''), 'the problem line is named with its line number');
  check((await call('GET', `/api/contacts/${c1.id}`)).newsletter.status !== 'yes', 'nothing stored before "Import"');
  d.querySelector('.nwl-md [data-nwl="imp-go"]').click();
  (await until(() => d.querySelector('.itc-dlg [data-cd="yes"]')))?.click();  // 2.356.0 B (#2934): the import names its target first
  check(await until(async () => (await call('GET', `/api/contacts/${c1.id}`)).newsletter.status === 'yes'), 'Import stores the consent');
  check(await until(() => !d.querySelector('.nwl-md .nwl-imp-sum')), 'the preview is gone afterwards');
  w.close();

  console.log(`p2141_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
