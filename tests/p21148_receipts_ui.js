// kalmido-suite: fresh
// 2.1148.0 (#4895) the point "Receipts" below the file store's tree: on a computer the panel shows "Receipts" after the
// folders, with its parts Office / Entertainment / Household below it once one is open; a part lists its receipts (name,
// day, amount) and a tap opens the receipt's area (the office's receipts list, the budget list in the entry's month) - the
// receipts stay there. On a phone (390 px, no panel) the top of "My files" has the row "Receipts", opened it shows the three
// parts as sections. Own container (start.sh), jsdom.
// freelancer-matrix: files - frida has no organisation: everything in her private workspace with her personal office.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const form = async (ck, url, fd) => { const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 6000) => { for (let t = 0; t < ms; t += 100) { if (f()) return true; await sleep(100); } return !!f(); };
const FEAT = 'cal,comments,collab,files,docs,office,budget';
const PDF = Buffer.from('%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [] /Count 0 >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'P4: frida is in no organisation');

  await call(CF, 'POST', '/api/files/folders', {space: 'private', name: 'Taxes'});
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([PDF], {type: 'application/pdf'}), 'papier.pdf');
  const up = await form(CF, '/api/docs', fd), nid = (up.ids || [])[0];
  check(up.http === 201 && nid, 'setup: a document ' + up.http);
  check((await call(CF, 'PATCH', `/api/docs/${nid}`, {date: '2026-02-01', amount: '59.50'})).http < 300, 'setup: its date and amount');
  check((await call(CF, 'PUT', `/api/docs/${nid}/receipt`, {category: 'Office', vat_pct: '19', keep: true})).http < 300, 'setup: recorded as a receipt');
  const bl = (await call(CF, 'POST', '/api/budget/lists', {})).list_id;
  const ent = await call(CF, 'POST', `/api/budget/${bl}/entries`, {day: '2026-09-03', amount: 10, kind: 'out', title: 'Paint'});
  const bf = new FormData(); bf.append('file', new Blob([Buffer.from('paid')], {type: 'text/plain'}), 'bill.txt');
  check((await form(CF, `/api/budget/entries/${ent.id}/files`, bf)).http < 300, 'setup: a receipt on a budget entry');

  // (1) a computer: "Receipts" in the panel after the folders, its parts below it once a part is open
  let w = await boot({user: 'frida', hash: 'ablage'}), d = w.document;
  const side = () => [...d.querySelectorAll('#side .sbbt .sbbtn')].map(b => [b.textContent.trim(), b.dataset.go]);
  check(await until(() => side().some(x => x[1] === 'ablage/aus-receipts')), 'the panel: "Receipts" ' + JSON.stringify(side()));
  const gos = side().map(x => x[1]);
  check(gos.indexOf('ablage/aus-receipts') > gos.findIndex(g => /^ablage\/\d+$/.test(g)), 'the panel: "Receipts" after the folder Taxes');
  w.location.hash = '#ablage/aus-rcoffice';
  check(await until(() => side().some(x => x[1] === 'ablage/aus-rcbudget') && !!d.querySelector('#view .abrcx')), 'a part open: Office / Entertainment / Household below "Receipts" ' + JSON.stringify(side()));
  check(side().find(x => x[1] === 'ablage/aus-rcoffice')?.[0] === 'Office' && side().find(x => x[1] === 'ablage/aus-rcbudget')?.[0] === 'Household', 'the parts\' names');
  check(!side().some(x => x[1] === 'ablage/aus-rcmeals'), 'no Entertainment without a meal');
  const row = d.querySelector('#view .abrcx');
  check(row?.querySelector('.abname')?.textContent === 'papier.pdf' && /59\.50/.test(row?.querySelector('.abmeta2')?.textContent || ''), 'Office: the receipt with its amount ' + (row?.textContent || ''));
  check((d.querySelector('#view .abcollnote')?.textContent || '').includes('Receipts stay in their area'), 'the note: the receipts stay in their area');
  check([...d.querySelectorAll('#view .abcrumbs [data-go]')].some(b => b.dataset.go === 'ablage/aus-receipts'), 'the path: My files / Receipts / Office');
  check(!d.querySelector('#view .abrcx a[download], #view .abrcx [data-ab="menu"]'), 'no download, no menu: only a way into the area');
  row.querySelector('.abopen').click();
  check(await until(() => w.location.hash === '#office/books/receipts' && w.eval('S.route.mod') === 'office'), 'a tap opens the office\'s receipts list ' + w.location.hash);
  w.close();

  // (2) a phone: the row "Receipts" at the top of My files, opened the parts as sections; the budget's receipt opens its month
  w = await boot({user: 'frida', hash: 'ablage', mobile: true}); d = w.document;
  const names = () => [...d.querySelectorAll('#view .ablist .abrow .abname')].map(e => e.textContent);
  check(await until(() => names().includes('Taxes') && names().includes('Receipts')), 'the phone: Taxes and Receipts in the list ' + JSON.stringify(names()));
  d.querySelector('#view .abrow.abcoll[data-abcoll="receipts"] .abopen').click();
  check(await until(() => w.eval('S.route.aus') === 'receipts' && d.querySelectorAll('#view .abcollg').length === 2), 'opened: two sections (Office, the budget list) ' + w.location.hash);
  const heads = [...d.querySelectorAll('#view .abcollh')].map(h => h.textContent);
  check(heads[0] === 'Office', 'the first section: Office ' + JSON.stringify(heads));
  const brow = [...d.querySelectorAll('#view .abrcx')].find(x => x.querySelector('.abname')?.textContent === 'bill.txt');
  check(!!brow && (brow.querySelector('.abmeta2')?.textContent || '').includes('Paint'), 'the budget\'s receipt with the entry\'s title');
  brow?.querySelector('.abopen').click();
  check(await until(() => w.location.hash === `#budget/${bl}/2026-09`), 'a tap opens the budget list in the entry\'s month ' + w.location.hash);
  check(await until(() => w.eval('BG.month') === '2026-09'), 'the budget shows September 2026');
  w.close();

  console.log(`p21148_receipts_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
