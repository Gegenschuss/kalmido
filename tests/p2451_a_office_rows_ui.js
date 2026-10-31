// 2.451.0 UI tests (#3834 office lists), own container (start.sh). jsdom, invented data only, as a person without an organisation:
// freelancer-matrix: office
// - phone CSS: no symbols in the rows of quotations and archive; the buttons stay in the page for screen readers
// - a long press / right click on an archive row opens the row menu (preview, download, correct), no preview under it;
//   without a long press the phone's PDF view has "Correct"
// - sort choice on quotations, archive and pipeline: date, client, amount, name, per list, remembered
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const PDF = Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF\n');
const menuItems = d => [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
const pick = async (d, label) => { const it = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => b.textContent.trim() === label)); it?.click(); };
const ptr = (w, el, type) => { const e = new w.MouseEvent(type, {bubbles: true, clientX: 5, clientY: 5}); Object.defineProperty(e, 'pointerType', {value: 'touch'}); el.dispatchEvent(e); };
const press = (w, el) => ptr(w, el, 'pointerdown');
const release = (w, el) => ptr(w, el, 'pointerup');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients'});
  const st = await call('GET', '/api/state');
  check(!(st.orgs || []).length, 'a person without an organisation');
  const S1 = (await call('POST', '/api/office/services', {name_de: 'Schnitt', daily_rate: 100})).id;
  const mk = async (name, title, date, qty) => {
    const cl = (await call('POST', '/api/clients', {name, zip: '20457', city: 'Hamburg'})).id;
    const o = await call('POST', '/api/office/docs', {project_title: title, client_id: cl, date, items: [{service_id: S1, qty}]});
    check(o.http === 201, 'quotation ' + title + ' ' + o.http);
    return {cl, id: o.id};
  };
  const A = await mk('Zeta GmbH', 'Alpha film', '2026-03-01', 5), Bb = await mk('Alfa AG', 'Mid film', '2026-02-01', 9), Cc = await mk('Muster KG', 'Zulu film', '2026-01-01', 1);
  const run = await call('POST', '/api/office/legacy/archive/run');
  for (const [no, amount, date] of [['A-1', '100', '2025-05-08'], ['A-2', '900', '2025-01-08']]) {
    const fd = new FormData();
    fd.append('file', new Blob([PDF, no], {type: 'application/pdf'}), no + '.pdf');
    for (const [k, v] of Object.entries({run_id: run.run_id, kind: 'offer', number: no, client_id: A.cl, date, amount, paid: '0'})) fd.append(k, String(v));
    const up = await fetch(B + 'api/office/legacy/archive', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
    check(up.status === 201, 'archived quotation ' + up.status);
  }
  for (const [title, value, date] of [['Small deal', 10, '2026-06-01'], ['Big deal', 500, '2026-05-01']]) check((await call('POST', '/api/office/deals', {title, value, stage: 'inquiry', expected_date: date})).http === 201, 'deal ' + title);

  // ================= the phone rule (jsdom does not lay out: the rule itself, the buttons stay in the page)
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'office.css'), 'utf8');
  const ph = css.slice(css.indexOf('(#3834)'));
  check(/@media \(max-width:767px\)\{\s*li>\.ofdrmore,\.oimarch \.oimdl\{position:absolute/.test(ph), 'phones: dots, download and edit leave the row, for screen readers they stay');

  // ================= quotations: the sort
  let w = await boot({hash: 'office/offers', mobile: true}); let d = w.document;
  const ids = () => [...d.querySelectorAll('.ofdlist .ofdrow')].map(x => +x.dataset.id).join();
  await until(() => d.querySelectorAll('.ofdlist .ofdrow').length === 3, 60);
  check(ids() === [A.id, Bb.id, Cc.id].join(), 'default: newest date first ' + ids());
  check(d.querySelector('.ofdlist .ofdrmore') && !d.querySelector('.ofdlist .ofdrow button'), 'the dots button stays beside the row, for screen readers');
  const sortTo = async label => { d.querySelector('[data-lsort]').click(); await pick(d, label); };
  d.querySelector('[data-lsort]').click();
  const opts = await until(() => menuItems(d).length && menuItems(d));
  check(['Date', 'Client', 'Amount', 'Name'].every(t => (opts || []).some(x => x.startsWith(t))), 'the choice: date, client, amount, name: ' + opts);
  await pick(d, 'Client');
  check(await until(() => ids() === [Bb.id, Cc.id, A.id].join()), 'by client A-Z ' + ids());
  await sortTo('Amount');
  check(await until(() => ids() === [Bb.id, A.id, Cc.id].join()), 'by amount, largest first ' + ids());
  await sortTo('Amount');
  check(await until(() => ids() === [Cc.id, A.id, Bb.id].join()), 'the same choice again: the other direction ' + ids());
  await sortTo('Name');
  check(await until(() => ids() === [A.id, Bb.id, Cc.id].join()), 'by name ' + ids());
  check(w.eval(`LS.get('lst.sort.docs.offer', null)?.k`) === 'name', 'remembered for this list');
  w.close();
  // ================= remembered, per list
  w = await boot({hash: 'office/offers', ls: {'tasks.lst.sort.docs.offer': JSON.stringify({k: 'amount', d: 'asc'})}}); d = w.document;
  check(await until(() => ids() === [Cc.id, A.id, Bb.id].join()), 'a new start keeps the sort ' + ids());
  d.querySelector('.ofdkinds [data-kind="archive"]').click();
  await until(() => d.querySelector('.oimarch a.ofdrow'), 60);
  const arch = () => [...d.querySelectorAll('.oimarch a.ofdrow .ofcn b')].map(b => b.textContent.split(' ')[0]).join();
  check(arch() === 'A-1,A-2', 'the archive has its own sort: newest first ' + arch());
  w.close();

  // ================= archive: the row menu on the phone
  w = await boot({hash: 'office/offers', mobile: true}); d = w.document;
  await until(() => d.querySelector('.ofdkinds [data-kind="archive"]'), 60);
  d.querySelector('.ofdkinds [data-kind="archive"]').click();
  await until(() => d.querySelector('.oimarch a.ofdrow'), 60);
  d.querySelector('[data-lsort]').click(); await pick(d, 'Amount');
  check(await until(() => arch() === 'A-2,A-1'), 'archive by amount ' + arch());
  const row = d.querySelector('.oimarch a.ofdrow');
  check(/"arch":\d+/.test(row.dataset.pview), "the phone's PDF view carries Correct");
  press(w, row);
  const items = await until(() => menuItems(d).includes('Download PDF') && menuItems(d));
  release(w, row);
  check(items && ['Preview (PDF)', 'Download PDF', 'Correct archived document'].every(t => items.includes(t)), 'a long press opens the row menu: ' + items);
  row.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  await sleep(50);
  check(!d.querySelector('.lightbox'), 'the click that ends the press opens no preview');
  await pick(d, 'Correct archived document');
  check(await until(() => d.querySelector('.r81b-dlg'), 40), 'the menu entry opens the correction dialog');
  d.querySelector('.r81b-dlg [data-m="close"], .r81b-dlg [data-m="cancel"]')?.click();
  w.close();
  w = await boot({hash: 'office/offers'}); d = w.document;
  await until(() => d.querySelector('.ofdkinds [data-kind="archive"]'), 60);
  d.querySelector('.ofdkinds [data-kind="archive"]').click();
  const r2 = await until(() => d.querySelector('.oimarch a.ofdrow'), 60);
  check(!/"arch"/.test(r2.dataset.pview), 'the computer keeps its row buttons, the PDF view stays as it was');
  r2.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  check(await until(() => menuItems(d).includes('Correct archived document')), 'a right click opens the same menu');
  w.close();

  // ================= pipeline
  w = await boot({hash: 'office/pipeline'}); d = w.document;
  const cards = () => [...d.querySelectorAll('[data-pipcol="inquiry"] .pptitle')].map(x => x.textContent).join();
  await until(() => d.querySelectorAll('[data-pipcol="inquiry"] .pptitle').length === 2, 60);
  const manual = cards();
  d.querySelector('[data-lsort="pipeline"]').click();
  await pick(d, 'Amount');
  check(await until(() => cards() === 'Big deal,Small deal'), 'pipeline by amount ' + cards());
  d.querySelector('[data-lsort="pipeline"]').click();
  await pick(d, 'Standard');
  check(await until(() => cards() === manual), 'pipeline: Standard is the order from before ' + cards());
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
