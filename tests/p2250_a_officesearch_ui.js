// 2.250.0 A (#2992) UI test, own container (start.sh): the command palette's group "Office" (ftsearch.js).
//  - jsdom, a person without an organisation (the own office; freelancer-matrix: office): typing a client's name shows
//    the group "Office" with the client (sub "Client") and its quotation (number, sub "Quotation · client"); a click on
//    the quotation opens the document (#office/offers/<id>), a click on the client the client page; without the office
//    module the group stays away
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  const CL = (await call('POST', '/api/clients', {name: 'Weingut Sonnenhang', contact: 'Petra Probe'})).id;
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', client_id: CL, project_title: 'Hoffest', items: [{title: 'Konzept', qty: 1, rate: 800}]});
  check(doc.status === 201 && doc.number, 'setup: a quotation with a number ' + JSON.stringify(doc).slice(0, 160));
  const api = await call('GET', '/api/search?q=Sonnenhang');
  check((api.office || []).length === 2, 'setup: the server finds client + quotation ' + JSON.stringify(api).slice(0, 200));

  const w = await boot({user: 'alice'}), d = w.document;
  const items = () => [...d.querySelectorAll('.palette .pitem')];
  const group = () => [...d.querySelectorAll('.palette .pgroup')].find(g => g.textContent === 'Office');
  w.eval('openPalette()'); await sleep(200);
  input(w, d.querySelector('.palette .pqin'), 'Sonnenhang');
  check(await until(group), 'the group "Office" appears after the pause');
  const cl = items().find(b => b.querySelector('.plt')?.textContent === 'Weingut Sonnenhang');
  check(cl && /^Client/.test(cl.querySelector('.pls')?.textContent || ''), 'the client with "Client" below: ' + (cl?.querySelector('.pls')?.textContent || ''));
  const of = items().find(b => b.querySelector('.plt')?.textContent === doc.number);
  const sub = of?.querySelector('.pls')?.textContent || '';
  check(of && /Quotation/.test(sub) && /Weingut Sonnenhang/.test(sub), 'the quotation by its number, kind + client below: ' + sub);
  if (of) click(w, of);
  check(await until(() => w.eval(`S.route.mod === 'office' && +S.route.id === ${doc.id}`)), 'a click opens the quotation ' + w.location.hash);
  w.eval('closePalette()'); w.eval('openPalette()'); await sleep(100);
  input(w, d.querySelector('.palette .pqin'), 'Petra Probe');
  await until(group);
  const cl2 = items().find(b => b.querySelector('.plt')?.textContent === 'Weingut Sonnenhang');
  check(cl2 && /Petra Probe/.test(cl2.querySelector('.pls')?.textContent || ''), 'found by the contact person, named below');
  if (cl2) click(w, cl2);
  check(await until(() => w.eval(`S.route.mod === 'clients' && S.route.client === ${CL}`)), 'a click opens the client page ' + w.location.hash);
  w.eval('closePalette()');
  w.close();

  // the office module off: no group
  await call('PATCH', '/api/settings', {features: 'cal,comments,collab,clients'});
  const w2 = await boot({user: 'alice'}), d2 = w2.document;
  w2.eval('openPalette()'); await sleep(200);
  input(w2, d2.querySelector('.palette .pqin'), 'Hoffest'); await sleep(900);
  check(![...d2.querySelectorAll('.palette .pgroup')].some(g => g.textContent === 'Office'), 'office off: no group "Office"');
  w2.eval('closePalette()');
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  w2.close();
  console.log(`p2250_a_officesearch_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
