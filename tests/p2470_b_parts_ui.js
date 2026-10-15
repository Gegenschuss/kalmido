// 2.47.0 UI tests, part B (#1215 parts of a quotation), own container (start.sh), jsdom. Invented services and amounts.
// - the quotation editor: the title page shows a part line (quantity x the part's net, "Open part"), the section "Parts" lists
//   every part and marks the one that is not on the title page
// - opening a part shows the quotation's position editor for its positions; a change goes to the part (its net changes), the
//   print switch is stored, "Title page" goes back and the part line shows the new amount
// - "Add service" offers the parts after the services; picking one puts it on the title page
// - "Create invoice" asks for the form (like the quotation / title page / summary) and makes the invoice in the chosen form
// - the office settings have the preset for invoices from quotations with parts
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2470_B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const svc = (title, qty, rate) => ({kind: 'service', title, qty, unit: 'day', rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  // 2.47.0: since 2.46.0 (#1592) nobody joins an organisation automatically: Office needs one
  { const me = (await call('GET', '/api/state')).me; const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
    await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}); }
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Campaign', items: [svc('Concept', 1, 800)]});
  check(doc.status === 201, 'a quotation ' + doc.status);
  const pa = await call('POST', `/api/office/docs/${doc.id}/parts`, {title: 'Module A'});
  const PA = pa.part.id;
  await call('PUT', `/api/office/docs/${doc.id}/parts/${PA}/items`, {items: [svc('Animation', 2, 500)]});
  const pb = await call('POST', `/api/office/docs/${doc.id}/parts`, {title: 'Module B', add_to_title: false});
  const PB = pb.part.id;
  await call('PUT', `/api/office/docs/${doc.id}/parts/${PB}/items`, {items: [svc('Sound', 1, 300)]});

  // ================= the title page and the section "Parts"
  let w = await boot({user: 'alice', hash: `office/offers/${doc.id}`}), d = w.document;
  await until(() => d.querySelector('.ofdeditor .tppl'));
  const pl = d.querySelector('.ofdeditor .tppl');
  check(pl && pl.querySelector('[data-k="qty"]')?.value === '1' && /1,000\.00/.test(pl.querySelector('.ofdlt')?.textContent || ''), 'title page: the part line 1 x 1,000.00 ' + (pl?.textContent || '').replace(/\s+/g, ' ').slice(0, 120));
  check(pl && pl.querySelector('[data-ofd="tp-open"]'), 'title page: the part line opens the part');
  const sec = d.querySelector('details[data-sec="parts"]');
  check(sec && sec.open && sec.querySelectorAll('.tprow').length === 2, 'the section "Parts" lists both parts (open)');
  const rows = [...(sec?.querySelectorAll('.tprow') || [])];
  check(rows.length === 2 && !rows[0].querySelector('.tpunused') && rows[1].querySelector('.tpunused'), 'the part that is not on the title page is marked');
  check(/1,800\.00/.test(d.querySelector('#ofd-totals')?.textContent || ''), 'title page: net total 1,800.00 ' + (d.querySelector('#ofd-totals')?.textContent || '').replace(/\s+/g, ' ').slice(0, 80));

  // ================= an open part
  click(w, pl.querySelector('[data-ofd="tp-open"]'));
  await until(() => d.querySelector('.tphead .tptitle'));
  check(d.querySelector('.tphead .tptitle')?.value === 'Module A', 'the open part: its title');
  const its = [...d.querySelectorAll('.tpsec .ofdits .ofdit')];
  check(its.length === 1 && its[0].querySelector('[data-k="title"]')?.value === 'Animation', 'the open part: the position editor with its positions');
  check(!d.querySelector('.tppl') && !d.querySelector('details[data-sec="parts"]'), 'the open part replaces the title page positions');
  change(w, its[0].querySelector('[data-k="qty"]'), '3');
  const net = await until(async () => { const x = await call('GET', `/api/office/docs/${doc.id}`); const p = (x.parts || []).find(q => q.id === PA); return p && p.totals.net === 1500 && x.totals.net === 2300 ? x : null; });  // (both written by one save)
  check(net && net.totals.net === 2300, 'a change in the part goes to the part: part 1,500, quotation 2,300 ' + (net && net.totals.net));
  check((net?.items || []).length === 2, 'the title page keeps its two positions');
  await until(() => /1,500\.00/.test(d.querySelector('.tptotals')?.textContent || ''));
  check(/1,500\.00/.test(d.querySelector('.tptotals')?.textContent || ''), 'the part\'s sum on screen');
  d.querySelector('.tphead [data-tp="print"]').checked = false;
  change(w, d.querySelector('.tphead [data-tp="print"]'));
  check(await until(async () => ((await call('GET', `/api/office/docs/${doc.id}`)).parts || []).find(q => q.id === PA)?.print === 0), 'the print switch is stored');
  const ti = d.querySelector('.tphead .tptitle'); change(w, ti, 'Module A (web)');
  check(await until(async () => ((await call('GET', `/api/office/docs/${doc.id}`)).parts || []).find(q => q.id === PA)?.title === 'Module A (web)'), 'renaming the part');
  click(w, d.querySelector('[data-ofd="tp-back"]'));
  await until(() => d.querySelector('.tppl'));
  check(/1,500\.00/.test(d.querySelector('.tppl .ofdlt')?.textContent || ''), 'back on the title page: the part line shows the new amount');

  // ================= "Add service" offers the parts
  click(w, d.querySelector('[data-ofd="it-svc"]'));
  await until(() => d.querySelector('.ofdpick [data-m="part"]'));
  const picks = [...d.querySelectorAll('.ofdpick [data-m="part"]')];
  check(picks.length === 2, 'the service choice lists the parts ' + picks.length);
  click(w, picks.find(b => +b.dataset.pid === PB));
  const after = await until(async () => { const x = await call('GET', `/api/office/docs/${doc.id}`); return (x.items || []).some(i => i.ref_part_id === PB) ? x : null; });
  check(after && after.totals.net === 2600, 'picking a part puts it on the title page (2,300 + 300) ' + (after && after.totals.net));
  await until(() => d.querySelectorAll('.tppl').length === 2);
  check(!d.querySelector('details[data-sec="parts"] .tpunused'), 'no part is marked unused any more');

  // ================= the invoice: the form is chosen
  click(w, d.querySelector('[data-ofd="to-invoice"]'));
  await until(() => d.querySelector('input[name="tp-mode"]'));
  const modes = [...d.querySelectorAll('input[name="tp-mode"]')];
  check(modes.map(x => x.value).join() === 'full,title,summary' && modes[0].checked, 'the invoice choice: like the quotation (preset), title page, summary');
  modes[2].checked = true;
  click(w, d.querySelector('.ofddlg')?.closest('.modal, [role="dialog"], div')?.parentElement?.querySelector('[data-m="ok"]') || [...d.querySelectorAll('[data-m="ok"]')].pop());
  await until(() => w.eval('OFD.doc && OFD.doc.kind') === 'invoice');
  const inv = w.eval('OFD.doc');
  check(inv && inv.kind === 'invoice' && Math.abs(+inv.totals.net - 2600) < 0.005 && inv.items.every(i => i.title === 'Film production'), 'summary invoice with the quotation\'s net ' + JSON.stringify(inv && inv.items.map(i => i.title)));
  check(!errs.length, 'no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // ================= a sent quotation: its parts can still be opened (read only)
  await call('POST', `/api/office/docs/${doc.id}/status`, {status: 'sent'});
  w = await boot({user: 'alice', hash: `office/offers/${doc.id}`}); d = w.document;
  await until(() => d.querySelector('.ofdeditor .tppl [data-ofd="tp-open"]'));
  click(w, d.querySelector('.ofdeditor .tppl [data-ofd="tp-open"]'));
  await until(() => d.querySelector('.tphead .tptitle'));
  check(d.querySelector('.tphead .tptitle') && d.querySelector('.tpsec .ofdits [data-k="qty"]')?.closest('fieldset')?.disabled, 'sent quotation: a part opens read only');
  click(w, d.querySelector('[data-ofd="tp-back"]'));
  await until(() => d.querySelector('.tppl'));
  check(!!d.querySelector('.tppl'), 'sent quotation: back to the title page');
  w.close();

  // ================= the office settings
  w = await boot({user: 'alice', hash: 'office/settings'}); d = w.document;
  await until(() => d.querySelector('#os-parts-inv'));
  check(d.querySelector('#os-parts-inv')?.value === 'full' && d.querySelector('#os-parts-t-de')?.value === 'Filmherstellung', 'settings: the preset (like the quotation, "Filmherstellung")');
  check(!errs.length, 'no script errors ' + errs.join(' | '));
  w.close();

  console.log(`p2470_b_parts_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
