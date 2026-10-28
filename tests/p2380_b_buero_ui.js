// 2.380.0 part B UI tests (#3418, #3409), own container (start.sh). jsdom, invented data only, run for a member of an
// organisation (alice, admin) and a person without one (frida, her own admin):
// - #3418: "New quotation" creates the draft at once (no dialog); its menu has "Trial document (SAMPLE)"; "New invoice" has
//   the same entry; the trial document's editor head carries the one-time hint, a real one none
// - #3409: Quotations and Invoices are two points of the group Sell (computer: the panel; phone: the group's row); Quotations
//   has the tabs Quotations + Archive, Invoices the tabs Invoices, Credit notes, Reminders, Delivery notes, Archive; each
//   archive shows only its own kind (mixed legacy archive), Invoices filters All / open / paid and the sum line follows the
//   filters (client filter too, kept while the tabs change); an old link #office/offers/<invoice> and #office/offers/credit
//   move on to office/invoices; the path line names the area; the panel's trees: docs/tree only quotations,
//   docs/tree?sec=invoices only the invoice kinds (each its own root); the figure "Open items" opens the invoices
// freelancer-matrix: office
// kalmido-suite: fresh
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')];
const kinds = d => [...d.querySelectorAll('.ofdkinds [data-ofd="kind"]')].map(b => b.dataset.kind).join(',');
const FEAT = 'clients,office';
const PDF = Buffer.from('%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF\n');
async function archive(ck, run, f) {
  const fd = new FormData();
  fd.append('file', new Blob([PDF], {type: 'application/pdf'}), f.number + '.pdf');
  for (const [k, v] of Object.entries({run_id: run, ...f})) fd.append(k, String(v));
  const r = await fetch(B + 'api/office/legacy/archive', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return r.status;
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call(CA, 'GET', '/api/state')).me.workspaces[0].id;
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  for (const [user, who, ck] of [['alice', 'org', CA], ['frida', 'freelancer', CF]]) {
    // ---- data: a quotation, an invoice, a credit note; the legacy archive with a quotation, a paid and an open invoice
    const cl = await call(ck, 'POST', '/api/clients', {name: 'Example Media Ltd', zip: '10115', city: 'Berlin'});
    const cl2 = await call(ck, 'POST', '/api/clients', {name: 'Sample Films', zip: '20457', city: 'Hamburg'});
    check(cl.id && cl2.id, `${who}: two clients`);
    const Q = await call(ck, 'POST', '/api/office/docs', {project_title: 'Spot', client_id: cl.id});
    const I = await call(ck, 'POST', '/api/office/docs', {kind: 'invoice', project_title: 'Spot', client_id: cl.id});
    check(Q.kind === 'offer' && I.kind === 'invoice', `${who}: a quotation and an invoice ${Q.http} ${I.http}`);
    const run = await call(ck, 'POST', '/api/office/legacy/archive/run');
    check(run.http === 201, `${who}: archive run ${run.http}`);
    const up = [await archive(ck, run.run_id, {kind: 'offer', number: 'A-OLD-1', client_id: cl.id, date: '2025-03-01', amount: '500', paid: '0'}),
      await archive(ck, run.run_id, {kind: 'invoice', number: 'R-OLD-1', client_id: cl.id, date: '2025-04-01', amount: '1190', paid: '1'}),
      await archive(ck, run.run_id, {kind: 'invoice', number: 'R-OLD-2', client_id: cl2.id, date: '2025-05-01', amount: '238', paid: '0'})];
    check(up.every(x => x === 201), `${who}: three archived documents ${up}`);

    // ---- the trees of the panel: each area its own documents
    const tq = await call(ck, 'GET', '/api/office/docs/tree'), ti = await call(ck, 'GET', '/api/office/docs/tree?sec=invoices');
    check(tq.http === 200 && tq.docs.some(x => x.id === Q.id) && tq.docs.every(x => x.kind === 'offer'), `${who}: #3409 the quotations' tree holds quotations only ${JSON.stringify(tq.docs?.map(x => x.kind))}`);
    check(ti.http === 200 && ti.area === 'invoices' && ti.docs.some(x => x.id === I.id && x.open === `office/invoices/${I.id}`) && ti.docs.every(x => x.kind !== 'offer'), `${who}: #3409 the invoices' tree holds the invoice kinds, opened in office/invoices ${JSON.stringify(ti.docs?.map(x => x.kind + ':' + x.open))}`);
    const fq = await call(ck, 'POST', '/api/office/docs/tree/folders', {name: 'Q folder'}), fi = await call(ck, 'POST', '/api/office/docs/tree/folders?sec=invoices', {name: 'I folder'});
    check(fq.http === 201 && fi.http === 201 && fq.folder.parent_id !== fi.folder.parent_id, `${who}: #3409 each area makes its folders below its own root ${fq.http} ${fi.http}`);
    const tq2 = await call(ck, 'GET', '/api/office/docs/tree'), ti2 = await call(ck, 'GET', '/api/office/docs/tree?sec=invoices');
    check(tq2.folders.some(f => f.name === 'Q folder') && !tq2.folders.some(f => f.name === 'I folder') && ti2.folders.some(f => f.name === 'I folder') && !ti2.folders.some(f => f.name === 'Q folder'),
      `${who}: #3409 the folders stay in their area`);

    // ================= a computer: the panel, the tabs, New
    let w = await boot({user, hash: 'office/offers'}), d = w.document;
    check(await until(() => d.querySelector('#side [data-ofm="offers"]') && d.querySelector('#side [data-ofm="invoices"]')), `${who}: #3409 the panel has Quotations and Invoices`);
    const pts = [...d.querySelectorAll('#side [data-ofmg="sell"] [data-ofm]')].map(b => b.dataset.ofm).join();
    check(/offers,invoices/.test(pts), `${who}: #3409 Invoices right after Quotations in Sell ${pts}`);
    check(/^\s*Quotations\s*$/.test(d.querySelector('#side [data-ofm="offers"]')?.textContent || '') && /^\s*Invoices\s*$/.test(d.querySelector('#side [data-ofm="invoices"]')?.textContent || ''), `${who}: #3409 the names of the points`);
    check(await until(() => w.eval('Array.isArray(OFD.list) && !OFD.loading') && kinds(d) === 'offer,archive'), `${who}: #3409 Quotations: the tabs Quotations + Archive ${kinds(d)}`);
    check(!!d.querySelector('.ofdlist .ofdrow[data-id="' + Q.id + '"]') && !d.querySelector('.ofdlist .ofdrow[data-id="' + I.id + '"]'), `${who}: the quotation list`);
    // #3418: New creates at once; the menu beside it has the trial document
    d.querySelector('.office .ofdbar [data-ofd="new-more"]').click();
    await until(() => items(d).length);
    check(items(d).some(b => b.textContent.trim() === 'Trial document (SAMPLE)'), `${who}: #3418 the menu New has "Trial document (SAMPLE)"`);
    d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    d.querySelector('.office .ofdbar [data-ofd="new"]').click();
    check(await until(() => d.querySelector('.ofdeditor') && +w.eval('S.route.id') > I.id), `${who}: #3418 "New quotation" opens a new draft at once`);
    check(!d.querySelector('.modal') && !d.querySelector('.tri-hint'), `${who}: #3418 no dialog, no trial hint on a real quotation`);
    check(/^#office\/offers\/\d+$/.test(w.location.hash), `${who}: #3409 the quotation in its area ${w.location.hash}`);
    // the archive of Quotations: the archived quotation only
    w.location.hash = '#office/offers/archive';
    check(await until(() => d.querySelector('.oimarch')), `${who}: the quotations' archive`);
    let arch = () => [...d.querySelectorAll('.oimarch .ofcn b')].map(b => b.textContent).join('|');
    check(/A-OLD-1/.test(arch()) && !/R-OLD/.test(arch()), `${who}: #3409 the quotations' archive shows quotations only: ${arch()}`);
    check(!d.querySelector('[data-oim-paid]') && /Archived quotations: 500/.test(d.querySelector('.oimsum')?.textContent || ''), `${who}: #3409 no paid filter, the quotations' sum ${d.querySelector('.oimsum')?.textContent}`);
    w.close();

    // ================= Invoices: its tabs, the archive with the paid filter + sum, the client filter kept
    w = await boot({user, hash: 'office/invoices'}); d = w.document;
    check(await until(() => w.eval('Array.isArray(OFD.list) && !OFD.loading') && kinds(d) === 'invoice,credit,reminder,delivery,archive'), `${who}: #3409 Invoices: its five tabs ${kinds(d)}`);
    check(d.querySelector('#side [data-ofm="invoices"]')?.getAttribute('aria-current') === 'page', `${who}: #3409 the panel marks Invoices`);
    check(await until(() => d.querySelector('.ofdlist .ofdrow[data-id="' + I.id + '"]')) && !d.querySelector('.ofdlist .ofdrow[data-id="' + Q.id + '"]'), `${who}: the invoice list`);
    const st = [...(d.querySelector('#ofd-status')?.options || [])].map(o => o.value).join();
    check(/open/.test(st) && /paid/.test(st), `${who}: #3409 the invoices filter open / paid ${st}`);
    d.querySelector('.office .ofdbar [data-ofd="new-inv"]').click();
    await until(() => items(d).length);
    check(items(d).some(b => b.textContent.trim() === 'Empty invoice') && items(d).some(b => b.textContent.trim() === 'Trial document (SAMPLE)'), `${who}: #3418 "New invoice": Empty invoice and the trial document`);
    d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    d.querySelector('.ofdkinds [data-kind="archive"]').click();
    check(await until(() => w.location.hash === '#office/invoices/archive' && d.querySelector('.oimarch')), `${who}: #3409 the invoices' archive ${w.location.hash}`);
    check(/R-OLD-1/.test(arch()) && /R-OLD-2/.test(arch()) && !/A-OLD/.test(arch()), `${who}: #3409 the invoices' archive shows invoices only: ${arch()}`);
    const sum = () => (d.querySelector('.oimsum')?.textContent || '').replace(/\s+/g, ' ');
    check(/Archived invoices: 1,428\.00.*paid: 1,190\.00/.test(sum()), `${who}: #3409 the sum of all invoices: ${sum()}`);
    d.querySelector('[data-oim-paid="open"]').click();
    check(await until(() => /R-OLD-2/.test(arch()) && !/R-OLD-1/.test(arch())), `${who}: #3409 filter open: ${arch()}`);
    check(/Archived invoices: 238\.00.*paid: 0\.00/.test(sum()) && d.querySelector('[data-oim-paid="open"]')?.getAttribute('aria-pressed') === 'true', `${who}: #3409 the sum follows "open": ${sum()}`);
    d.querySelector('[data-oim-paid="paid"]').click();
    check(await until(() => /R-OLD-1/.test(arch()) && !/R-OLD-2/.test(arch())) && /Archived invoices: 1,190\.00.*paid: 1,190\.00/.test(sum()), `${who}: #3409 filter paid + its sum: ${arch()} ${sum()}`);
    d.querySelector('[data-oim-paid=""]').click();
    const sel = await until(() => d.querySelector('#oim-cl'));
    check(!!sel && [...sel.options].some(o => o.value === String(cl2.id)), `${who}: the client filter stays`);
    sel.value = String(cl2.id); sel.dispatchEvent(new w.Event('change', {bubbles: true}));
    check(await until(() => /R-OLD-2/.test(arch()) && !/R-OLD-1/.test(arch())) && /Archived invoices: 238\.00/.test(sum()), `${who}: #3409 the client filter and its sum: ${sum()}`);
    d.querySelector('.ofdkinds [data-kind="invoice"]').click();
    await until(() => d.querySelector('.ofdkinds [data-kind="invoice"][aria-selected="true"]'));
    d.querySelector('.ofdkinds [data-kind="archive"]').click();
    check(await until(() => d.querySelector('#oim-cl')?.value === String(cl2.id) && /R-OLD-2/.test(arch()) && !/R-OLD-1/.test(arch())), `${who}: #3409 the choice is kept while the tabs change`);
    w.eval(`OIM.cl = ''`);
    // the figure "Open items" opens the invoices
    w.eval(`kp_openItems('open')`);
    check(await until(() => /^#office\/invoices/.test(w.location.hash) && d.querySelector('.ofdkinds [data-kind="invoice"][aria-selected="true"]') && d.querySelector('#ofd-status')?.value === 'open'), `${who}: #3409 "Open items" opens Invoices ${w.location.hash}`);
    w.close();

    // ================= old links move on: an invoice under office/offers, the old kind address
    w = await boot({user, hash: 'office/offers/' + I.id}); d = w.document;
    check(await until(() => w.location.hash === '#office/invoices/' + I.id && d.querySelector('.ofdeditor')), `${who}: #3409 #office/offers/<invoice> moves on to ${w.location.hash}`);
    check(await until(() => d.querySelector('#side [data-ofm="invoices"]')?.getAttribute('aria-current') === 'page'), `${who}: #3409 the panel marks Invoices for the invoice`);
    check(await until(() => /Invoices/.test(d.querySelector('#view .ofmcrumb')?.textContent || '') && !/Quot/.test(d.querySelector('#view .ofmcrumb')?.textContent || '')), `${who}: #3409 the path names Invoices: ${d.querySelector('#view .ofmcrumb')?.textContent}`);
    d.querySelector('[data-ofd="back"]').click();
    check(await until(() => /^#office\/invoices(\/invoice)?$/.test(w.location.hash) && d.querySelector('.ofdlist')), `${who}: #3409 back to the invoices' list ${w.location.hash}`);
    w.location.hash = '#office/offers/credit';
    check(await until(() => w.location.hash === '#office/invoices/credit' && d.querySelector('.ofdkinds [data-kind="credit"][aria-selected="true"]')), `${who}: #3409 #office/offers/credit moves on to ${w.location.hash}`);
    w.location.hash = '#office/offers/' + Q.id;
    check(await until(() => d.querySelector('.ofdeditor') && w.eval('OFD.doc?.id') === Q.id) && w.location.hash === '#office/offers/' + Q.id, `${who}: a quotation stays in Quotations ${w.location.hash}`);
    check(await until(() => /Quotations/.test(d.querySelector('#view .ofmcrumb')?.textContent || '')), `${who}: #3409 the path names Quotations`);
    w.close();

    // ================= a phone: the group's row has both points
    w = await boot({user, hash: 'office/invoices', mobile: true}); d = w.document;
    check(await until(() => d.querySelector('#view .ofpb [data-ofm="offers"]') && d.querySelector('#view .ofpb [data-ofm="invoices"]')), `${who}: #3409 phone: the row of Sell has Quotations and Invoices`);
    check(d.querySelector('#view .ofpb [data-ofm="invoices"]')?.getAttribute('aria-current') === 'page', `${who}: #3409 phone: Invoices is marked`);
    check(await until(() => kinds(d) === 'invoice,credit,reminder,delivery,archive'), `${who}: #3409 phone: the invoices' tabs`);
    w.close();
  }

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
