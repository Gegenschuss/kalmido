// 2.144.6 UI test, part B (#2400: office fixes from the review of 2.138), own container (start.sh). jsdom, invented data only:
// - F2: "Continue after the archive" for invoices asks for a reason (a dialog with a text field); Cancel changes
//   nothing, a reason sets the counter; the quotation counter asks nothing
// - F4: an entry restored by hand after an undo: the undone run offers no "Archive leftover entries"
// P21446B_NOSTART=1 = the container is running.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21446B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const PDF = Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF\n');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Beispiel', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const CL = (await call('POST', '/api/clients', {name: 'Muster Medien GmbH', zip: '20457', city: 'Musterstadt'})).id;
  const run = await call('POST', '/api/office/legacy/archive/run');
  check(run.http === 201, 'archive run ' + run.http);
  for (const [n, kind] of [['412', 'invoice'], ['388', 'offer']]) {
    const fd = new FormData();
    fd.append('file', new Blob([Buffer.concat([PDF, Buffer.from('% ' + n + '\n')])], {type: 'application/pdf'}), `${n}_MusterMedien_Imagefilm__08.05.26_${kind === 'invoice' ? 'R' : 'KV'}.pdf`);
    for (const [k, v] of Object.entries({run_id: run.run_id, kind, number: `${n}_MusterMedien_Imagefilm__08.05.26`, project_no: n, client_id: CL, date: '2026-05-08', amount: '1190'})) fd.append(k, String(v));
    const up = await fetch(B + 'api/office/legacy/archive', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
    check(up.status === 201, `archived ${kind} ${up.status}`);
  }

  // ================= F2: the invoice counter asks for a reason
  let w = await boot({hash: 'office/import'}); let d = w.document;
  let btn = await until(() => d.querySelector('[data-oim="counter"][data-kind="invoice"]'), 60);
  check(!!btn, 'F2: "Continue after the archive" for invoices');
  btn?.click();
  let inp = await until(() => d.querySelector('.modal #cdlg-in'), 30);
  check(!!inp && /give a reason/.test(d.querySelector('.modal')?.textContent || ''), 'F2: a dialog asks for the reason: ' + (d.querySelector('.modal')?.textContent || '').slice(0, 160));
  d.querySelector('.modal [data-cd="no"]')?.click();
  await sleep(600);
  check((await call('GET', '/api/office/legacy/counter')).invoice.last === 0, 'F2: Cancel changes nothing');
  btn = await until(() => d.querySelector('[data-oim="counter"][data-kind="invoice"]'), 30);
  btn?.click();
  inp = await until(() => d.querySelector('.modal #cdlg-in'), 30);
  if (inp) { inp.value = 'Continue after the old invoices'; }
  d.querySelector('.modal form')?.dispatchEvent(new w.Event('submit', {cancelable: true}));
  check(await until(async () => (await call('GET', '/api/office/legacy/counter')).invoice.last === 412, 40), 'F2: with a reason the counter continues after 412');
  const log = await call('GET', '/api/office/log?limit=20');
  check((log.log || []).some(x => x.target === 'legacy' && JSON.stringify(x).includes('Continue after the old invoices')), 'F2: the reason is in the office log');
  const ob = await until(() => d.querySelector('[data-oim="counter"][data-kind="offer"]'), 30);
  ob?.click();
  check(await until(async () => (await call('GET', '/api/office/legacy/counter')).offer.last === 388, 40) && !d.querySelector('.modal #cdlg-in'), 'F2: the quotation counter asks no reason');
  w.close();

  // ================= F4: restored by hand -> no "Archive leftover entries"
  const imp = await call('POST', '/api/office/legacy/import', {services: [{name_de: 'Rest A', daily_rate: 100, action: 'new'}]});
  check(imp.http === 201, 'F4: an import ' + imp.http);
  const NA = (await call('GET', '/api/office/services?archived=1')).items.find(x => x.name_de === 'Rest A').id;
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', project_title: 'Imagefilm Probe'});
  await call('PUT', `/api/office/docs/${doc.id}/items`, {items: [{kind: 'service', service_id: NA, qty: 1}]});
  const u = await call('POST', `/api/office/legacy/runs/${imp.run_id}/undo`);
  check(u.http === 200 && (u.archived || []).length === 1, 'F4: the undo archives the used service ' + u.http);
  await call('PATCH', `/api/office/services/${NA}`, {archived: 0});
  w = await boot({hash: 'office/import'}); d = w.document;
  await until(() => d.querySelector('.oim .oimrun'), 60);
  await sleep(600);
  check(!d.querySelector(`.oim [data-imr="tidy"][data-id="${imp.run_id}"]`), 'F4: no "Archive leftover entries" for an entry restored by hand');
  w.close();

  console.log(`p21446_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
