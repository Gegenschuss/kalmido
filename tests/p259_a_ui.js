// 2.59.0 UI tests, part A (#1735 client contact persons from the address book), own container (start.sh). jsdom, invented data only:
// - the client dialog offers "From the address book" per contact person; the search lists the organisation's address book
//   (not the private one), a pick copies name, function, e-mail and phone and marks the card "Linked"; saving stores contact_id
// - the client page links the contact person to its contact; the contact card shows "Contact person at" with the client
// - "Unlink" drops the link on saving; the name stays
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

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,clients,contacts'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const bk = await call('POST', '/api/books', {name: 'Customers', org_id: ORG});
  const ho = await call('POST', `/api/books/${bk.id}/org`, {org_role: 'view'});
  check(bk.http === 201 && ho.org_owned, 'setup: an address book of the organisation ' + JSON.stringify(ho).slice(0, 160));
  const ct = await call('POST', '/api/contacts', {book_id: bk.id, given: 'Petra', family: 'Buyer', title: 'Head of purchasing', emails: [{value: 'petra@example.com'}], phones: [{value: '+49 30 1234'}]});
  const pb = await call('POST', '/api/books', {name: 'Private', org_id: null});
  await call('POST', '/api/contacts', {book_id: pb.id, given: 'Hidden', family: 'Private'});
  const cl = await call('POST', '/api/clients', {name: 'Acme', org_id: ORG, contacts: [{name: 'Typed'}]});
  check(cl.http === 201 && ct.id, 'setup: client and contact');
  const CL = cl.id;

  // ================= the client dialog: pick from the address book
  let w = await boot({hash: `client/${CL}`}); let d = w.document;
  await until(() => d.querySelector('#view .cldetail'), 60);
  click(w, d.querySelector('[data-act="client-edit"]'));
  await until(() => d.querySelector('.modal.cldlg .clkc'), 30);
  let md = d.querySelector('.modal.cldlg');
  const pick = md.querySelector('.clkc [data-clk-pick]');
  check(pick && /From the address book/.test(pick.textContent), 'dialog: "From the address book" on the contact person');
  if (pick) {
    click(w, pick);
    await until(() => d.querySelector('#pop [data-cklp]'), 40);
    const hits = [...d.querySelectorAll('#pop [data-cklp]')].map(x => x.textContent);
    check(hits.length === 1 && /Petra Buyer/.test(hits[0]) && !hits.some(h => /Hidden/.test(h)), 'search: only the organisation\'s book ' + JSON.stringify(hits));
    click(w, d.querySelector('#pop [data-cklp]'));
    await sleep(80);
    const card = md.querySelector('.clkc');
    check(card.querySelector('[data-clk="name"]').value === 'Petra Buyer' && card.querySelector('[data-clk="role"]').value === 'Head of purchasing'
      && card.querySelector('[data-clk="email"]').value === 'petra@example.com' && card.querySelector('[data-clk="phone"]').value === '+49 30 1234', 'pick: the fields are filled');
    check(card.querySelector('.cklk') && card.querySelector('[data-clk-unlink]') && !card.querySelector('[data-clk-pick]'), 'pick: marked "Linked" with "Unlink"');
    click(w, md.querySelector('[data-m="save"]'));
    const cj = await until(async () => { const x = await call('GET', `/api/clients/${CL}`); return x.contacts?.[0]?.contact_id === ct.id ? x : null; }, 40);
    check(cj && cj.contacts[0].name === 'Petra Buyer', 'saved: contact_id and the copied name');
  }
  w.close();

  // ================= the client page and the contact card
  w = await boot({hash: `client/${CL}`}); d = w.document;
  await until(() => d.querySelector('#view .msclks'), 60);
  check(d.querySelector(`#view .msclks a[href="#contacts/${ct.id}"]`), 'client page: the linked contact person opens the contact');
  w.close();
  w = await boot({hash: `contacts/${ct.id}`}); d = w.document;
  const sec = await until(() => d.querySelector('.cklsec'), 60);
  check(sec && /Contact person at/.test(sec.textContent) && sec.querySelector(`a[href="#client/${CL}"]`) && /Acme/.test(sec.textContent), 'contact card: "Contact person at" Acme');
  w.close();

  // ================= unlink
  w = await boot({hash: `client/${CL}`}); d = w.document;
  await until(() => d.querySelector('#view .cldetail'), 60);
  click(w, d.querySelector('[data-act="client-edit"]'));
  await until(() => d.querySelector('.modal.cldlg .clkc [data-clk-unlink]'), 30);
  md = d.querySelector('.modal.cldlg');
  click(w, md.querySelector('[data-clk-unlink]'));
  await sleep(50);
  check(!md.querySelector('.clkc .cklk') && md.querySelector('.clkc [data-clk-pick]'), 'unlink: the mark is gone, the search is back');
  click(w, md.querySelector('[data-m="save"]'));
  const uj = await until(async () => { const x = await call('GET', `/api/clients/${CL}`); return x.contacts?.[0]?.contact_id === null ? x : null; }, 40);
  check(uj && uj.contacts[0].name === 'Petra Buyer', 'unlink: saved without the link, the name stays');
  w.close();

  console.log(`p259_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
