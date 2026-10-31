// kalmido-suite: fresh
// 2.369.0 A (#3200) the office document list in pages, own container (start.sh), jsdom. Invented data only.
// - the invoice list shows 100 rows and "Load more"; a click appends the next rows without doubles; the last page has no button
// - the search also finds a document that is not loaded yet; emptied, the list is back with its button
// - another sorting than newest first works on the large page
// - the client page and the reminder dialog show an old open invoice behind more than 500 newer ones
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const sql = (q, ...a) => execFileSync('python3', ['-c', `import os, sys, dbx
c = dbx.connect(os.path.join(sys.argv[1], 'tasks.db'), timeout=10); c.execute(sys.argv[2], sys.argv[3:]); c.commit(); c.close()`, DATA, q, ...a.map(String)], {cwd: __dirname});
const rowsOf = d => [...d.querySelectorAll('.ofdlist .ofdrow')];

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Example Studio GmbH', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', vat_id: 'DE999999999', iban: 'DE02120300000000202051'}});
  const client = async name => (await call('POST', '/api/clients', {name, street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'})).id;
  const CL = await client('Beispielkunde AG'), CL2 = await client('Altkunde GmbH');
  const mk = async c => { const i = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: c, service_from: '2026-05-01', items: [{title: 'Beratung', qty: 1, rate: 100}]}); return call('POST', `/api/office/docs/${i.id}/finalize`); };
  const old = await mk(CL2), tpl = await mk(CL);
  check(old.locked && tpl.locked, 'two invoices finalised');
  sql(`UPDATE office_docs SET date='2019-01-01', due_date='2019-02-01' WHERE id=?`, old.id);
  sql(`UPDATE office_docs SET date='2026-06-01', due_date='2099-12-31' WHERE id=?`, tpl.id);
  execFileSync('python3', ['-c', `import dbx, os, sys
c = dbx.connect(os.path.join(sys.argv[1], 'tasks.db'), timeout=10)
cols = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='office_docs' AND column_name NOT IN ('id', 'number', 'date') ORDER BY ordinal_position").fetchall()]
cl = ', '.join(cols)
c.execute(f"INSERT INTO office_docs ({cl}, number, date) SELECT {cl}, 'P' || g, '2026-05-' || lpad(CAST(1 + g % 28 AS TEXT), 2, '0') FROM office_docs, generate_series(1, 505) g WHERE id=?", (int(sys.argv[2]),))
c.commit(); c.close()`, DATA, String(tpl.id)], {cwd: __dirname});

  // ---- the list in pages
  let w = await boot({user: 'alice', hash: 'office/invoices'});
  let d = w.document;
  await until(() => rowsOf(d).length >= 100);
  check(rowsOf(d).length === 100, '100 rows at first: ' + rowsOf(d).length);
  const btn = () => d.querySelector('[data-ofd="listmore"]');
  check(btn() && /Load more/.test(btn().textContent), 'the button "Load more"');
  check(!rowsOf(d).some(x => x.dataset.id === String(old.id)), 'the old invoice is not on the first page');
  btn().click();
  await until(() => rowsOf(d).length >= 200);
  const ids = rowsOf(d).map(x => x.dataset.id);
  check(ids.length === 200 && new Set(ids).size === 200, 'a click: the next 100, no doubles: ' + ids.length);
  // a reload of the list (something changed) keeps what was shown
  await w.eval('ofdLoadList(true)');
  await until(() => !w.eval('OFD.loading'));
  check(rowsOf(d).length === 200, 'a reload keeps the rows of "Load more": ' + rowsOf(d).length);

  // ---- the search goes to the server while rows are missing
  const q = d.querySelector('#ofd-q');
  q.focus(); q.value = old.number; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => rowsOf(d).length === 1);
  check(rowsOf(d)[0]?.dataset.id === String(old.id), 'the search finds the invoice that was not loaded: ' + old.number);
  check(!btn(), 'one hit: no button');
  check(d.activeElement?.id === 'ofd-q', 'the search box keeps the cursor');
  const q2 = d.querySelector('#ofd-q');
  q2.value = ''; q2.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => rowsOf(d).length >= 100 && btn());
  check(rowsOf(d).length >= 100 && !!btn(), 'search emptied: the list with its button again');

  // ---- another sorting than newest first
  w.eval(`LS.set('lst.sort.docs.invoice', {k: 'date', d: 'asc'}); ofdLoadList(true)`);
  await until(() => rowsOf(d).length >= 500);
  check(rowsOf(d).length === 500, 'date ascending works on the largest page: ' + rowsOf(d).length);
  btn()?.click();
  await until(() => !btn());
  check(rowsOf(d).length === 507 && rowsOf(d)[0]?.dataset.id === String(old.id), 'all rows, the last page has no button; the oldest first: ' + rowsOf(d).length);
  w.eval(`LS.set('lst.sort.docs.invoice', null)`);

  // ---- the reminder dialog
  d.querySelector('[data-ofd="remind"]').click();
  await until(() => d.querySelector('#ofd-r-fee'));
  check(!!d.querySelector(`[data-rid="${old.id}"]`), 'reminder dialog: the old overdue invoice is offered (behind 500 newer ones)');
  check(d.querySelectorAll('[data-rid]').length === 507, 'reminder dialog: all open invoices, over several pages: ' + d.querySelectorAll('[data-rid]').length);
  d.querySelector('.modal [data-m="close"]')?.click();
  w.close();

  // ---- the client page
  w = await boot({user: 'alice', hash: `client/${CL2}`});
  d = w.document;
  await until(() => d.querySelector(`a[href$="office/invoices/${old.id}"]`));
  check(!!d.querySelector(`a[href$="office/invoices/${old.id}"]`), 'client page: the old open invoice stands there');
  check(w.eval('MSC.inv.length') === 1, 'client page: only the invoices of this client are loaded: ' + w.eval('MSC.inv.length'));
  w.eval(`go('client/${CL}')`);
  await until(() => w.eval(`MSC.invFor === ${CL} && !MSC.invLoading && (MSC.inv || []).length > 0`));
  await until(() => !d.querySelector(`a[href$="office/invoices/${old.id}"]`) && d.querySelector('a[href*="office/invoices/"]'));
  check(!d.querySelector(`a[href$="office/invoices/${old.id}"]`), 'another client: another list');
  w.close();

  console.log(`${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
