// 2.39.1 UI tests (agent F: #1182 Office & finance -- legacy import), own container (start.sh). jsdom, invented data only:
// - Settings has the entry "Import legacy data"; the page office/import shows the spreadsheet upload, the PDF upload, the
//   number counters and the import runs (an archive run with "Undo")
// - a preview (state set directly) is drawn as cards: reasons of an unsure split, duplicate with "what to do", editable
//   fields; unticking a card sets it to skip, the import button counts the ticked rows
// - the documents tab has the kind "Archive": the archived invoice with the "Archive" tag, the paid state and the sums
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const PDF = Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF\n');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  // 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const CL = (await call('POST', '/api/clients', {name: 'Muster Medien GmbH', zip: '20457', city: 'Hamburg'})).id;
  const run = await call('POST', '/api/office/legacy/archive/run');
  check(run.http === 201, 'archive run ' + run.http);
  const fd = new FormData();
  fd.append('file', new Blob([PDF], {type: 'application/pdf'}), '663_MusterMedien_Imagefilm__08.05.26_R.pdf');
  for (const [k, v] of Object.entries({run_id: run.run_id, kind: 'invoice', number: '663_MusterMedien_Imagefilm__08.05.26_R', project_no: '663', client_id: CL, date: '2026-05-08', amount: '1190', paid: '1'})) fd.append(k, String(v));
  const up = await fetch(B + 'api/office/legacy/archive', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(up.status === 201, 'archived invoice ' + up.status);

  // ================= settings: the entry
  let w = await boot({hash: 'office/settings'}); let d = w.document;
  await until(() => d.querySelector('#ofc-set a[href="#office/import"]'), 60);
  check(!!d.querySelector('#ofc-set a[href="#office/import"]'), 'settings: "Import legacy data" link');
  w.close();

  // ================= the import page
  w = await boot({hash: 'office/import'}); d = w.document;
  await until(() => d.querySelector('.oim .oimrun'), 60);
  check(!!d.querySelector('[data-oim="pick-xlsx"]') && !!d.querySelector('#oim-xlsx[accept*=".xlsx"]') && !!d.querySelector('#oim-pdf[multiple]'), 'import page: spreadsheet and PDF upload');
  check(d.querySelector('#side [data-go="office/settings"]')?.getAttribute('aria-current') === 'page', 'import page sits under the Settings point');  // 2.87.9 (#1917): the office menu; 2.98.0 (#2180): the office rail  // 2.152.2 (#2617): the office points sit in the panel #side
  const runRow = d.querySelector('.oim .oimrun');
  check(runRow && /Archive/.test(runRow.textContent) && !!runRow.querySelector('[data-oim="undo"]'), 'import runs: the archive run with Undo: ' + (runRow?.textContent || '').slice(0, 80));
  check(/663/.test(d.querySelector('.oimctr')?.textContent || '') && !!d.querySelector('[data-oim="counter"][data-kind="invoice"]'), 'counter: the highest archived number and the proposal');
  // a preview as the server sends it (state set directly: no file dialog in jsdom)
  w.eval(`OIM.pv = {clients: [
    {row: 2, name: 'Bergtal Studios', contact: '', street: 'Hauptweg 9', zip: '6020', city: 'Innsbruck', country: '', address: 'Bergtal Studios\\nHauptweg 9\\n6020 Innsbruck', flags: ['zip4'], reasons: ['Postcode with 4 digits: Austria or Switzerland?'], dup: null, action: 'new'},
    {row: 3, name: 'Muster Medien GmbH', contact: '', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', address: 'x', flags: [], reasons: [], dup: {kind: 'existing', id: ${CL}, name: 'Muster Medien GmbH'}, action: 'skip'}],
    services: [{row: 2, name_de: 'Schnitt', category: 'Video', daily_rate: 550, action: 'new', dup: false}], equipment: [], other: {staff: 2}}; ofcDraw();`);
  await until(() => d.querySelectorAll('.oimpv .oimcard').length === 3, 30);
  const cards = [...d.querySelectorAll('.oimpv .oimcard')];
  check(cards.length === 3 && cards[0].classList.contains('warn') && /Austria or Switzerland/.test(cards[0].querySelector('.oimwarn')?.textContent || ''), 'preview: the unsure split shows its reason');
  check(cards[1].classList.contains('off') && /Already a client/.test(cards[1].textContent) && !!cards[1].querySelector('select[data-oim-act]'), 'preview: a duplicate is off by default with "what to do"');
  check(!!cards[0].querySelector('.cty input.ctyq') && cards[0].querySelectorAll('input[data-oim-c]').length === 6, 'preview: six editable fields per client (2.40.0 #1372: the country as a choice)');
  check(/Import 2 entries/.test(d.querySelector('[data-oim="import"]')?.textContent || ''), 'import button counts the ticked rows: ' + (d.querySelector('[data-oim="import"]')?.textContent || ''));
  check(/Staff \(2\)/.test(d.querySelector('.oimpv')?.textContent || ''), 'sheets without master data are named');
  const inp = cards[0].querySelector('input[data-k="country"]');
  inp.value = 'AT'; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(w.eval('OIM.pv.clients[0].country') === 'AT', 'an edited field lands in the preview');
  const cb = cards[0].querySelector('input[type="checkbox"]');
  cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  await sleep(100);
  check(w.eval('OIM.pv.clients[0].action') === 'skip' && /Import 1 entry/.test(d.querySelector('[data-oim="import"]')?.textContent || ''), 'unticking skips the row');
  d.querySelector('[data-oim="filter"][data-f="unsure"]').click();
  await sleep(100);
  check(d.querySelectorAll('.oimpv .oimcards')[0].querySelectorAll('.oimcard').length === 1, 'filter "Unsure" shows only the unsure split');
  w.close();

  // ================= the documents tab: kind "Archive"
  w = await boot({hash: 'office/invoices'}); d = w.document;  // 2.380.0 (#3409): the archived invoice is in the invoices' area
  await until(() => d.querySelector('.ofdkinds [data-kind="archive"]'), 60);
  d.querySelector('.ofdkinds [data-kind="archive"]').click();
  await until(() => d.querySelector('.ofdlist a.ofdrow'), 60);
  const row = d.querySelector('.ofdlist a.ofdrow');
  check(row && /663_MusterMedien/.test(row.textContent) && /Archive/.test(row.querySelector('.rotag')?.textContent || '') && /Paid/.test(row.textContent), 'archive: the archived invoice with the tag and the paid state');
  check(/\/api\/office\/legacy\/archive\/\d+\/pdf/.test(row?.getAttribute('href') || '') && row?.getAttribute('target') === '_blank', 'archive: the row opens the original PDF');
  check(/1,190\.00/.test(d.querySelector('.oimsum')?.textContent || ''), 'archive: the sums: ' + (d.querySelector('.oimsum')?.textContent || ''));
  // 2.81.0 (#1834): the client filter above the list, the edit dialog: net + two tax rates (Kalmido adds the gross), paid off,
  // save -> the server has the gross, the tax lines and the history; reopened, the history shows both changes
  check(!!d.querySelector('#oim-cl option[value="' + CL + '"]'), '#1834: the client filter lists the client');
  d.querySelector('[data-oim="arch-edit"]')?.click();
  const dlg = await until(() => d.querySelector('.r81b-dlg'), 40);
  check(!!dlg && /gross, tax unknown/.test(dlg.textContent) && !!dlg.querySelector('#r81b-paid')?.checked, '#1834: the dialog shows the old gross as "tax unknown" and paid');
  const setNet = (i, v, tax) => { const ln = dlg.querySelectorAll('.r81b-ln')[i]; const n = ln.querySelector('[data-r81b="net"]'); n.value = v; n.dispatchEvent(new w.Event('input', {bubbles: true})); if (tax) { const t = ln.querySelector('[data-r81b="tax"]'); t.value = tax; t.dispatchEvent(new w.Event('change', {bubbles: true})); } };
  if (dlg) {
    setNet(0, '100', '19');
    dlg.querySelector('[data-r81b="add"]').click();
    setNet(1, '50', '7');
    check(/172\.50/.test(dlg.querySelector('#r81b-sum')?.textContent || ''), '#1834: the sum 100 @ 19 % + 50 @ 7 % = gross 172.50: ' + (dlg.querySelector('#r81b-sum')?.textContent || ''));
    dlg.querySelector('#r81b-paid').checked = false;
    dlg.querySelector('[data-m="ok"]').click();
  }
  const one = await until(async () => { const x = await call('GET', '/api/office/legacy/archive'); const it = (x.items || [])[0]; return it && it.amount === 172.5 ? it : null; }, 40);
  check(one && one.paid === 0 && (one.tax_lines || []).length === 2 && one.tax === 22.5, '#1834: saved: gross 172.50, tax 22.50, two lines, not paid: ' + JSON.stringify(one || {}).slice(0, 200));
  const h = one ? await call('GET', `/api/office/legacy/archive/${one.id}`) : {};
  check((h.history || []).map(x => x.field).sort().join() === 'amount,paid', '#1834: the history has amount and paid: ' + JSON.stringify(h.history || []).slice(0, 200));
  w.close();

  console.log(`p2391_f_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
