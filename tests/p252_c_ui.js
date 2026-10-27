// 2.52.0 UI tests of part C (#1438 address books an organisation owns; own container, start.sh). jsdom, invented data only:
// - Address books > More: "Hand over to the organisation…" for the owner (an admin of the book's organisation), after the
//   confirmation the book belongs to it (row: "Belongs to Alpha"; no "Workspace…" any more)
// - "Members of the organisation" > "They can edit" sets the members' role; "Make personal again…" makes it the admin's own
// - each is one undo step: undo of "make personal" hands it over again
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P252_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const items = d => [...d.querySelectorAll('#pop [role="menuitem"]')];
const item = (d, t) => items(d).find(x => (x.querySelector('.ml')?.firstChild?.textContent || x.textContent).trim() === t);
const srv = async id => (await call('GET', '/api/books')).items.find(b => b.id === id);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,contacts,collab', workspace: 'all'});
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha'})).id;
  await call('PATCH', `/api/admin/orgs/${ORG}`, {members: [1], admins: [1]});
  const BK = (await call('POST', '/api/books', {name: 'Suppliers', org_id: ORG})).id;
  await call('POST', '/api/contacts', {fn: 'Petra Supply', book_id: BK});
  check(BK && (await srv(BK)).can_org === true, 'a book of Alpha, alice may hand it over');

  const w = await boot({user: 'alice', hash: 'contacts'}), d = w.document;
  w.confirm = () => true;
  const menuOf = async () => {
    if (!d.querySelector(`.modal [data-cbmenu="${BK}"]`)) {
      await until(() => d.querySelector('#view [data-ct="menu"]'));
      click(w, d.querySelector('#view [data-ct="menu"]')); await until(() => item(d, 'Address books…'));
      click(w, item(d, 'Address books…')); await until(() => d.querySelector(`.modal [data-cbmenu="${BK}"]`));
    }
    click(w, d.querySelector(`.modal [data-cbmenu="${BK}"]`)); return until(() => items(d).length && items(d));
  };
  await menuOf();
  check(item(d, 'Hand over to the organisation…') && item(d, 'Workspace…') && !item(d, 'Make personal again…'), 'a personal book: "Hand over to the organisation…" + "Workspace…"');
  click(w, item(d, 'Hand over to the organisation…'));
  let b = await until(async () => { const x = await srv(BK); return x.org_owned && x; });
  check(b && b.org_owned && b.org_role === 'view', 'handed over: the members can view');
  check(await until(() => /Belongs to Alpha/.test(d.querySelector('.modal #cb-body')?.textContent || '')), 'the row says "Belongs to Alpha"');

  await menuOf();
  check(!item(d, 'Workspace…') && !item(d, 'Hand over to the organisation…') && item(d, 'Make personal again…'), 'an organisation\'s book: no "Workspace…", "Make personal again…"');
  click(w, item(d, 'Members of the organisation'));
  await until(() => item(d, 'They can edit'));
  check(item(d, 'They can view')?.classList.contains('on') && item(d, 'Only admins and people it is shared with'), 'the three choices, "They can view" ticked');
  click(w, item(d, 'They can edit'));
  b = await until(async () => { const x = await srv(BK); return x.org_role === 'edit' && x; });
  check(b && b.org_role === 'edit', 'the members can edit now');

  await menuOf();
  click(w, item(d, 'Make personal again…'));
  b = await until(async () => { const x = await srv(BK); return !x.org_owned && x; });
  check(b && !b.org_owned && b.role === 'owner', 'made personal again (alice\'s own)');
  const labels = () => w.eval('JSON.stringify(HIST.undo.map(e => e.label))');
  await until(() => /made personal/.test(labels()), 80);
  check(labels() === JSON.stringify(['Address book handed over', 'Changed setting: Members of the organisation', 'Address book made personal']),
    'every step is one entry of the undo history ' + labels());
  w.eval("histStep('undo')");
  b = await until(async () => { const x = await srv(BK); return x.org_owned && x; });
  check(b && b.org_owned && b.org_role === 'edit', 'undo: handed over again with the members\' role it had ' + JSON.stringify(b));
  w.close();

  console.log(`\np252_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
