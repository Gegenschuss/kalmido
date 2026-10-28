// kalmido-suite: fresh
// 2.356.0 C UI tests (#3003 #3004 #3005): quotation <-> invoice in the office editor, own container (start.sh). jsdom;
// invented data only. Played by a person WITHOUT an organisation (the personal office; freelancer-matrix: office).
// - #3003: the invoice shows "From quotation" with a link, the quotation "Invoices for this quotation"; "Create invoice"
//   on a quotation with an invoice asks first (the question names it)
// - #3004: the path line names the document that is open (after a quotation was open before: the invoice); Preview,
//   Download and "…" sit in one group; the kind tab is part of the address (#office/offers/invoice) and Back returns
// - #3005: the client is the first field of the head, language / currency / VAT / contract wait folded under "More details";
//   an invoice without rights shows no "Transfer of rights" (a button instead), the quotation keeps it; "New invoice" >
//   "From a quotation…" lists the open quotations without an invoice; the editor's "…" menu has no second "Preview (PDF)"
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2356C_UI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // freelancer-matrix: office -- a person without an organisation
  const u = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(u.http === 200 || u.http === 201, 'the freelancer ' + u.http);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('GET', '/api/office/settings');
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'})).id;
  const quote = async title => { const q = await call('POST', '/api/office/docs', {client_id: CL, project_title: title}); await call('PUT', `/api/office/docs/${q.id}/items`, {items: [{kind: 'service', title: 'Kamera', qty: 2, unit: 'day', rate: 800}]}); return q.id; };
  const Q = await quote('Imagefilm'), Q2 = await quote('Werbespot');
  const inv = await call('POST', `/api/office/docs/${Q}/invoice`, {});
  check(inv.http === 201, 'an invoice from the quotation ' + inv.http);
  const I = inv.id;
  // the invoice took over the quotation's rights (the office's default rights note): shown; emptied here = an invoice without rights
  check(Object.values((await call('GET', `/api/office/docs/${I}`)).rights || {}).some(v => v && (typeof v !== 'object' || v.text)), '#3005: the invoice takes over the rights of its quotation');
  const cr = await call('PATCH', `/api/office/docs/${I}`, {rights: {time: '', territory: '', media: '', exceptions: '', exclusive: 0, note: ''}});
  check(cr.http === 200, 'setup: the invoice without rights ' + cr.http);

  // ================= #3004: the path line after a quotation was open before
  const w = await boot({user: 'frida', hash: 'office/offers/' + Q}); const d = w.document;
  check(await until(() => d.querySelector('.ofdhead [data-ofd="to-invoice"]')), 'the quotation opens');
  // #3003 on the quotation
  check(await until(() => d.querySelector(`.oil_link a[href="#office/offers/${I}"]`)) && /Invoices for this quotation/.test(d.querySelector('.oil_link').textContent),
    '#3003: the quotation lists its invoice with a link');
  // #3005 head: client first, the rest folded
  const head = d.querySelector('[data-sec="head"]');
  check(head?.querySelector('.ofdgrid .row')?.querySelector('#ofd-client_id'), '#3005: the client is the first field of the head');
  const more = d.querySelector('details.oil_more');
  check(more && !more.open && more.querySelector('#ofd-lang') && more.querySelector('#ofd-currency') && more.querySelector('#ofd-vat_mode') && /EUR/.test(more.querySelector('summary').textContent),
    '#3005: language / currency / VAT folded under More details, the summary names them');
  check(d.querySelector('[data-sec="rights"]'), '#3005: the quotation keeps its Transfer of rights');
  check(d.querySelector('.oil_tail [data-ofd="more"]') && d.querySelector('.oil_tail .ofdpdf'), '#3004: Preview and "…" sit in one group');
  // the editor's menu: no second Preview
  d.querySelector('.ofdhead [data-ofd="more"]').click();
  const items = await until(() => { const x = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim()); return x.length && x; });
  check(items && !items.some(t => /Preview/.test(t)), '#3005: the editor menu has no second Preview: ' + items);
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  // #3003: Create invoice again asks, naming the invoice
  d.querySelector('.ofdhead [data-ofd="to-invoice"]').click();
  const ask = await until(() => d.querySelector('.cdlg #cdlg-t'));
  check(ask && /already has an invoice/.test(ask.textContent), '#3003: a second invoice asks first: ' + ask?.textContent);
  d.querySelector('.cdlg [data-cd="no"]')?.click();
  // open the invoice now: the path line names it
  w.location.hash = '#office/offers/' + I;
  check(await until(() => /Invoice/.test(d.querySelector('.ofdhead .ofdnum')?.textContent || '')), 'the invoice opens');
  const crumb = await until(() => { const c = d.querySelector('#view .ofmcrumb'); return c && /Invoice/.test(c.textContent) && c; });
  check(crumb && !/Quotation/.test(crumb.textContent), '#3004: the path line names the open invoice: ' + d.querySelector('#view .ofmcrumb')?.textContent);
  check(await until(() => d.querySelector(`.oil_link a[href="#office/offers/${Q}"]`)) && /From quotation/.test(d.querySelector('.oil_link').textContent), '#3003: the invoice names its quotation with a link');
  check(!d.querySelector('[data-sec="rights"]') && d.querySelector('[data-ofd="rights-add"]'), '#3005: an invoice without rights shows no Transfer of rights, a button instead');
  d.querySelector('[data-ofd="rights-add"]').click();
  check(await until(() => d.querySelector('[data-sec="rights"]')), '#3005: the button opens the section');
  check(d.querySelector('[data-sec="head"] .ofdgrid .row #ofd-client_id') && d.querySelector('details.oil_more #ofd-lang'), '#3005: the invoice head: client first, the rest folded');

  // ================= #3004: the kind tab in the address, Back returns
  d.querySelector('[data-ofd="back"]').click();
  check(await until(() => /^#office\/offers\/invoice$/.test(w.location.hash) && d.querySelector('.ofdkinds [data-kind="invoice"][aria-selected="true"]')),
    '#3004: back to the list: the address names the tab ' + w.location.hash);
  d.querySelector('.ofdkinds [data-kind="offer"]').click();
  check(await until(() => w.location.hash === '#office/offers/offer' && d.querySelector('.ofdkinds [data-kind="offer"][aria-selected="true"]')), '#3004: the quotation tab changes the address ' + w.location.hash);
  w.history.back();
  check(await until(() => w.location.hash === '#office/offers/invoice' && d.querySelector('.ofdkinds [data-kind="invoice"][aria-selected="true"]')), '#3004: Back returns to the invoice tab ' + w.location.hash);
  // #3003: the list names the kind of amount
  check(await until(() => /gross/.test(d.querySelector('.ofdlist .oil_amt')?.textContent || '')), '#3003: the invoice list says gross');

  // ================= #3005: New invoice > From a quotation…
  d.querySelector('[data-ofd="new-inv"]').click();
  const mi = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /From a quotation/.test(b.textContent)));
  check(mi && ![...d.querySelectorAll('#pop [role="menuitem"]')].some(b => /open it and press/.test(b.textContent)), '#3005: the menu has a real entry "From a quotation…"');
  mi?.click();
  const pick = await until(() => d.querySelector('.modal .oil_pick'));
  const ids = pick ? [...pick.querySelectorAll('[data-oil-pick]')].map(b => +b.dataset.oilPick) : [];
  check(ids.includes(Q2) && !ids.includes(Q), '#3005: the choice lists the open quotation without an invoice only: ' + ids);

  w.close();
  console.log(`p2356_c_docs_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); console.log(`p2356_c_docs_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
