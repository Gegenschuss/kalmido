// 2.40.0 UI tests (agent K: office & finance -- clients and the legacy import), own container (start.sh). jsdom, invented data only:
// - #1380 the client dialog lists the contact persons (cards with name, function, e-mail, phone, default, remove), adds
//   one, makes it the default and saves the whole list; the client page lists them; the document editor offers the
//   choice "Contact person" and the attn. line follows it
// - #1380 the import preview: a duplicate with another contact person offers (and preselects) "Add as contact person"
// - #1372 the country: a search field with the list (DE / AT / CH on top), "Öst" and "AT" find Austria, the pick stores
//   the code; empty shows "Germany (default)"; an invalid stored value is marked, not changed; the company data too
// - #1421 an archived PDF shows the address read from it with the proposals as ticks
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
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const typeIn = (w, el, v) => { el.focus(); el.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true})); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  // 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const c1 = await call('POST', '/api/clients', {name: 'Muster Medien GmbH', contact: 'Erika Beispiel', zip: '50667', city: 'Köln', street: 'Lindenweg 4'});
  check(c1.http === 201 && c1.contacts?.length === 1, 'a client with its default contact person');
  const CL = c1.id;
  await call('PATCH', `/api/clients/${CL}`, {contacts: [{id: c1.contacts[0].id, name: 'Erika Beispiel', is_default: true}, {name: 'Max Probe', role: 'Producer', email: 'max@example.com'}]});

  // ================= #1380 the client dialog
  let w = await boot({hash: `client/${CL}`}); let d = w.document;
  await until(() => d.querySelector('#view .cldetail'), 60);
  // 2.47.3 (#1734): the contact persons sit on the client's card (list + card like the contacts)
  check(d.querySelectorAll('#view .msclks li').length === 2 && /Max Probe/.test(d.querySelector('#view .msclks')?.textContent || ''), 'client page: the contact persons are listed');
  click(w, d.querySelector('[data-act="client-edit"]'));
  await until(() => d.querySelector('.modal.cldlg .clkc'), 30);
  let md = d.querySelector('.modal.cldlg');
  check(md.querySelectorAll('.clkc').length === 2 && md.querySelector('.clkc input[data-clk="is_default"]').checked, 'dialog: two contact cards, the first is the default');
  check(!md.querySelector('#cl-contact'), 'dialog: no single contact field any more');
  click(w, md.querySelector('[data-clk-add]'));
  await sleep(50);
  check(md.querySelectorAll('.clkc').length === 3, 'dialog: "Add contact person" adds a card');
  const last = md.querySelectorAll('.clkc')[2];
  last.querySelector('[data-clk="name"]').value = 'Ida Muster';
  last.querySelector('[data-clk="role"]').value = 'Accounting';
  last.querySelector('[data-clk="is_default"]').checked = true;
  last.querySelector('[data-clk="is_default"]').dispatchEvent(new w.Event('change', {bubbles: true}));
  click(w, md.querySelector('[data-m="save"]'));
  await until(async () => (await call('GET', `/api/clients/${CL}`)).contact === 'Ida Muster', 40);
  let cj = await call('GET', `/api/clients/${CL}`);
  check(cj.contact === 'Ida Muster' && cj.contacts.length === 3 && cj.contacts[0].name === 'Ida Muster' && cj.contacts[0].role === 'Accounting', 'saved: three contact persons, the new one is the default');
  w.close();

  // ================= #1372 the country in the client dialog
  await call('PATCH', '/api/settings', {features: 'cal,comments,collab,office,clients'});
  w = await boot({hash: `client/${CL}`}); d = w.document;
  await until(() => d.querySelector('#view .cldetail'), 60);
  click(w, d.querySelector('[data-act="client-edit"]'));
  await until(() => d.querySelector('.modal.cldlg'), 30);
  md = d.querySelector('.modal.cldlg');
  const q = md.querySelector('.cty .ctyq');
  check(q && md.querySelector('#clb-country[type="hidden"]') && q.placeholder === 'Germany (default)', 'country: a search field, empty = "Germany (default)"');
  if (q) {
    q.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true}));
    const first = [...md.querySelectorAll('.ctyl li[data-code]')].slice(0, 3).map(li => li.dataset.code).join(',');
    check(first === 'DE,AT,CH', 'country: Germany, Austria, Switzerland on top: ' + first);
    typeIn(w, q, 'Austri');  // the names are the browser's in the app language (English here; German: "Öst")
    check(md.querySelector('.ctyl li[data-code]')?.dataset.code === 'AT', 'country: "Austri" finds Austria first: ' + md.querySelector('.ctyl li[data-code]')?.dataset.code);
    typeIn(w, q, 'at');
    check(md.querySelector('.ctyl li[data-code]')?.dataset.code === 'AT', 'country: "AT" finds Austria');
    click(w, md.querySelector('.ctyl li[data-code="AT"]'));
    check(md.querySelector('#clb-country').value === 'AT' && /Austria/.test(q.value), 'country: the pick stores the code and shows the name: ' + q.value);
    click(w, md.querySelector('[data-m="save"]'));
    await until(async () => (await call('GET', `/api/clients/${CL}`)).billing?.country === 'AT', 40);
    check((await call('GET', `/api/clients/${CL}`)).billing?.country === 'AT', 'country: saved as AT');
  }
  w.close();
  // an invalid stored value is marked (the server takes no new ones; an old row may have one)
  const c2 = await call('POST', '/api/clients', {name: 'Altkunde KG'});
  w = await boot({hash: `client/${c2.id}`}); d = w.document;
  await until(() => d.querySelector('#view .cldetail'), 60);
  w.eval(`clientModal({...CLV.data, billing: {...(CLV.data.billing || {}), country: 'XY'}})`);
  await until(() => d.querySelector('.modal.cldlg .cty'), 30);
  md = d.querySelector('.modal.cldlg');
  check(md.querySelector('.cty.bad .ctybad') && md.querySelector('#clb-country').value === 'XY', 'country: an invalid stored value is marked, not changed');
  w.close();

  // ================= #1380 the document: the choice of the contact person
  const inv = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL});
  check(inv.http === 201 && inv.recipient?.lines?.[1] === 'Ida Muster', 'invoice draft: the default in the attn. line');
  w = await boot({hash: `office/offers/${inv.id}`}); d = w.document;
  await until(() => d.querySelector('#ofd-contact_id'), 60);
  const sel = d.querySelector('#ofd-contact_id');
  check(sel && sel.options.length === 4 && sel.value === String(cj.contacts[0].id), 'editor: the choice "Contact person" with the default selected (+ none)');
  if (sel) {
    const erika = cj.contacts.find(k => k.name === 'Erika Beispiel').id;
    sel.value = String(erika); sel.dispatchEvent(new w.Event('change', {bubbles: true}));
    await until(async () => (await call('GET', `/api/office/docs/${inv.id}`)).contact_id === erika, 40);
    const dj = await call('GET', `/api/office/docs/${inv.id}`);
    check(dj.contact_id === erika && dj.recipient.lines[1] === 'Erika Beispiel', 'editor: the attn. line follows the choice');
  }
  w.close();

  // ================= #1380 / #1421 the import page
  w = await boot({hash: 'office/import'}); d = w.document;
  await until(() => d.querySelector('[data-oim="pick-xlsx"]'), 60);
  w.eval(`OIM.pv = {clients: [
    {row: 2, name: 'Kanalwerk Agentur', contact: 'Anna Eins', street: 'Speicherstadt 4', zip: '20457', city: 'Hamburg', country: 'DE', address: 'x', flags: [], reasons: [], dup: null, action: 'new'},
    {row: 3, name: 'Kanalwerk Agentur', contact: 'Bert Zwei', street: 'Speicherstadt 4', zip: '20457', city: 'Hamburg', country: '', address: 'x', flags: [], reasons: [], dup: {kind: 'file', row: 2, name: 'Kanalwerk Agentur'}, action: 'contact'}],
    services: [], equipment: [], other: {}}; ofcDraw();`);
  await until(() => d.querySelectorAll('.oimpv .oimcard').length === 2, 30);
  const cards = [...d.querySelectorAll('.oimpv .oimcard')];
  const act = cards[1].querySelector('select[data-oim-act]');
  check(act && act.value === 'contact' && /Add as contact person/.test(act.selectedOptions[0]?.textContent || '') && ![...act.options].some(o => o.value === 'merge'),
    'preview: a duplicate in the file with another contact person = "Add as contact person" (no merge)');
  check(cards[1].querySelector('.cty .ctyq')?.placeholder === 'Germany (default)' && cards[0].querySelector('.cty .ctyq')?.value === 'Germany (DE)', 'preview: the country as a choice');
  check(/Import 2 entries/.test(d.querySelector('[data-oim="import"]')?.textContent || ''), 'preview: the contact row counts as an entry');
  w.eval(`OIM.arch = [{file_name: 'alt.pdf', kind: 'invoice', number: 'ALT-1', date: '', client_id: null, amount: '', paid: 1, sure: true, done: false, err: '',
    addr: {status: 'ok', unsure: false, new_client: true, add_contact: '', address_differs: false, client_id: null, client_name: '',
      address: {name: 'Leuchtturm Verlag GmbH', contact: 'Frau Ida Leser', street: 'Ringstraße 5', zip: '04109', city: 'Leipzig', country: 'DE', reasons: []}}, pNew: true},
    {file_name: 'scan.pdf', kind: 'invoice', number: 'ALT-2', date: '', client_id: null, amount: '', paid: 1, sure: true, done: false, err: '', addr: {status: 'no_text'}}]; ofcDraw();`);
  await until(() => d.querySelectorAll('.oimaddr').length === 2, 30);
  const ad = [...d.querySelectorAll('.oimaddr')];
  check(/Leuchtturm Verlag GmbH/.test(ad[0].textContent) && ad[0].querySelector('input[data-oim-p="new"]')?.checked, 'archive: the address of the PDF with the ticked proposal "new client"');
  check(/No text in the PDF/.test(ad[1].textContent), 'archive: a scan gets a hint (no OCR)');
  const pn = ad[0].querySelector('input[data-oim-p="new"]');
  pn.checked = false; pn.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(w.eval('OIM.arch[0].pNew') === false, 'archive: untick the proposal');
  w.close();

  // ================= #1372 the company data
  w = await boot({hash: 'office/settings'}); d = w.document;
  await until(() => d.querySelector('#ofc-set'), 60);
  check(!!d.querySelector('#ofc-set .cty #osc-country[type="hidden"]') || !!d.querySelector('#ofc-set #osc-country[type="hidden"]'), 'company data: the country as a choice');
  w.close();

  console.log(`p2400_k_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
