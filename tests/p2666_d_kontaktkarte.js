// 2.666.0 UI tests, part D (#3624), own container (start.sh, mode workspaces). jsdom, invented data only:
// kalmido-suite: fresh
// - the contact card is built from blocks like the client card (2.435.0 #3600): by default every block shows and is open
//   (details, note, tasks, ... as before), each folds at its title
// - a person folds a block closed and hides one: kept per person (view_contacts) after a reload, alike for every contact
// - another person keeps their own (the default); a malformed arrangement is refused
// - a person without an organisation (tests/freelancer_fixture.py) has the same, for the contacts of her private book
// - the client card still folds through the shared fold (dashboard.js lyFold)
// freelancer parity: carol has no organisation (no new route: PATCH /api/settings takes the new key view_contacts)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const keys = d => [...d.querySelectorAll('#view .ctcard .lyb[data-lyk]')].map(x => x.dataset.lyk);
const foldBtn = (d, k) => d.querySelector(`#view .ctcard [data-ct="fold"][data-k="${k}"]`);
const saved = async (ck = CK) => { const v = (await call('GET', '/api/state', null, ck)).settings?.view_contacts || ''; return v ? JSON.parse(v) : {}; };
const FEAT = 'cal,comments,collab,contacts,office,clients';

// fold block k at the card and hide block h through its "…" menu; -> the saved arrangement once both are stored
async function foldAndHide(w, d, k, h, ck) {
  click(w, foldBtn(d, k));
  await until(() => foldBtn(d, k)?.getAttribute('aria-expanded') === 'false');
  click(w, d.querySelector(`#view .ctcard [data-act="wg-more"][data-k="${h}"]`));
  const hide = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /^Hide/.test(b.textContent.trim())));
  if (hide) click(w, hide);
  return until(async () => { const x = await saved(ck); return x.opts?.[k]?.open === false && (x.hidden || []).includes(h) ? x : null; });
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'contacts']});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  await call('POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com', orgs: []});
  const CB = await login('bob'), CC = await login('carol');
  for (const ck of [CK, CB, CC]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ck);
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CK, CB]) await call('PATCH', '/api/settings', {workspace: `org:${ORG}`}, ck);
  const bk = await call('POST', '/api/books', {name: 'Customers', org_id: ORG});
  await call('POST', `/api/books/${bk.id}/org`, {org_role: 'edit'});
  const C1 = await call('POST', '/api/contacts', {book_id: bk.id, given: 'Petra', family: 'Muster', emails: [{value: 'petra@example.com', type: ['work']}], note: 'Erste Notiz'});
  const C2 = await call('POST', '/api/contacts', {book_id: bk.id, given: 'Paul', family: 'Beispiel', phones: [{value: '+49 30 5555'}], note: 'Zweite Notiz'});
  check(C1.http === 201 && C2.http === 201, 'setup: two contacts ' + [C1.http, C2.http]);

  // ================= the default: every block shows and is open (as before)
  let w = await boot({user: 'alice', hash: `contacts/${C1.id}`}), d = w.document;
  await until(() => foldBtn(d, 'details') && foldBtn(d, 'note') && foldBtn(d, 'tasks'));
  check(['details', 'note', 'tasks'].every(k => foldBtn(d, k)?.getAttribute('aria-expanded') === 'true'), '#3624: details, note, tasks open by default');
  check(/petra@example\.com/.test(d.querySelector('#view .ctcard .ctfields')?.textContent || '') && /Erste Notiz/.test(d.querySelector('#view .ctcard .ctnote')?.textContent || '')
    && d.querySelector('#view .ctcard .lyb[data-lyk="tasks"] .ctsec'), '#3624: the contents stay where they were');
  check(!!d.querySelector('#view .ctcard [data-act="ly-custom"][data-lyv="contacts"]'), '#3624: the card has "Arrange blocks…"');
  check(w.eval(`LY.contacts.key`) === 'view_contacts', '#3624: the arrangement is stored as view_contacts');

  // ================= fold closed, hide: kept per person, alike for every contact
  let v = await foldAndHide(w, d, 'note', 'tasks', CK);
  check(v, '#3624: folding the note and hiding the tasks is stored ' + JSON.stringify(v));
  check(!d.querySelector('#view .ctcard .ctnote') && !keys(d).includes('tasks'), '#3624: the note folded, the tasks gone ' + keys(d));
  w.close();
  w = await boot({user: 'alice', hash: `contacts/${C2.id}`}); d = w.document;
  await until(() => foldBtn(d, 'note'));
  check(foldBtn(d, 'note')?.getAttribute('aria-expanded') === 'false' && !d.querySelector('#view .ctcard .ctnote') && !keys(d).includes('tasks')
    && foldBtn(d, 'details')?.getAttribute('aria-expanded') === 'true' && /\+49 30 5555/.test(d.querySelector('#view .ctcard .ctfields')?.textContent || ''),
  '#3624: after a reload, at another contact: the same folds and hidden blocks ' + keys(d));
  click(w, foldBtn(d, 'note'));
  await until(() => d.querySelector('#view .ctcard .ctnote'));
  check(/Zweite Notiz/.test(d.querySelector('#view .ctcard .ctnote')?.textContent || '') && foldBtn(d, 'note')?.getAttribute('aria-expanded') === 'true', '#3624: the note folds open again');
  w.close();

  // ================= another person: their own arrangement (the default); a malformed one is refused
  w = await boot({user: 'bob', hash: `contacts/${C1.id}`}); d = w.document;
  await until(() => foldBtn(d, 'note'));
  check(foldBtn(d, 'note')?.getAttribute('aria-expanded') === 'true' && keys(d).includes('tasks'), '#3624: bob keeps the default ' + keys(d));
  w.close();
  check((await call('PATCH', '/api/settings', {view_contacts: '{"nope":1}'}, CB)).http === 400, '#3624: a malformed arrangement is refused');
  check((await call('PATCH', '/api/settings', {view_contacts: JSON.stringify({hidden: ['Bad Key']})}, CB)).http === 400, '#3624: a malformed block key is refused');

  // ================= a person without an organisation (P4)
  const st = await call('GET', '/api/state', null, CC);
  check(!(st.me.workspaces || []).length, 'carol: no organisation');
  const pb = await call('POST', '/api/books', {name: 'Privat'}, CC);
  const P1 = await call('POST', '/api/contacts', {book_id: pb.id, given: 'Erika', family: 'Solo', note: 'Private Notiz'}, CC);
  const P2 = await call('POST', '/api/contacts', {book_id: pb.id, given: 'Max', family: 'Solo'}, CC);
  check(pb.http === 201 && P1.http === 201 && P2.http === 201, 'carol: a private book with two contacts ' + [pb.http, P1.http, P2.http]);
  w = await boot({user: 'carol', hash: `contacts/${P1.id}`}); d = w.document;
  await until(() => foldBtn(d, 'details') && foldBtn(d, 'note'));
  check(foldBtn(d, 'details')?.getAttribute('aria-expanded') === 'true' && /Private Notiz/.test(d.querySelector('#view .ctcard .ctnote')?.textContent || ''), '#3624: P4: open by default');
  v = await foldAndHide(w, d, 'details', 'note', CC);
  check(v, '#3624: P4: folding details and hiding the note is stored ' + JSON.stringify(v));
  w.close();
  w = await boot({user: 'carol', hash: `contacts/${P2.id}`}); d = w.document;
  await until(() => foldBtn(d, 'details'));
  check(foldBtn(d, 'details')?.getAttribute('aria-expanded') === 'false' && !d.querySelector('#view .ctcard .ctfields') && !keys(d).includes('note'),
    '#3624: P4: after a reload, at another contact: the same ' + keys(d));
  w.close();
  check(!(await saved()).opts?.details, '#3624: carol\'s folds are hers, not alice\'s');

  // ================= the client card folds through the shared fold
  const CL = await call('POST', '/api/clients', {name: 'Kunde Eins GmbH', org_id: ORG, email: 'kunde@example.com'});
  w = await boot({user: 'alice', hash: 'client/' + CL.id}); d = w.document;
  const cf = await until(() => d.querySelector('#view [data-mscl="fold"][data-k="details"]'));
  check(cf?.getAttribute('aria-expanded') === 'true' && d.querySelector('#view .msclcard .ctfields'), '#3624: the client card folds as before (details open)');
  if (cf) click(w, cf);
  await until(() => !d.querySelector('#view .msclcard .ctfields'));
  check(d.querySelector('#view [data-mscl="fold"][data-k="details"]')?.getAttribute('aria-expanded') === 'false', '#3624: ... and folds closed');
  w.close();

  console.log(`p2666_d_kontaktkarte: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
