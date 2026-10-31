// kalmido-suite: fresh
// 2.431.0 B UI tests (#3594, #3605): the office editor, own container (start.sh). jsdom; invented data only. Played by a
// person WITHOUT an organisation (the personal office; freelancer-matrix: office).
// - #3594: the subject (project title) is a multi-line field (textarea, 2 rows at the start, up to 1000 characters);
//   a line break typed there is saved
// - #3605: "Finalise" asks with the number the invoice gets ("Will be finalised as RE-..."); Cancel finalises nothing and
//   moves no number; OK finalises it with exactly that number
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2431B_UI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const st = await call('PUT', '/api/office/settings', {lang: 'de', currency: 'EUR', company_fields: {name: 'Beispiel Studio', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt',
    country: 'DE', email: 'kontakt@example.com', tax_number: '12/345/67890', vat_id: 'DE999999999', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  check(st.http === 200, 'office settings ' + st.http);
  const inv = await call('POST', '/api/office/docs', {kind: 'invoice', project_title: 'Imagefilm', recipient: {name: 'Beispielkunde AG', lines: ['Marktplatz 2', '54321 Beispielort']},
    service_from: '2026-05-01', items: [{title: 'Kamera', qty: 1, rate: 500}]});
  check(inv.http === 201, 'invoice draft ' + inv.http);
  const I = inv.id;
  const pv = await call('GET', `/api/office/docs/${I}/number-preview`);
  check(pv.http === 200 && /^RE-/.test(pv.number || '') && pv.given === false, '#3605: the preview route ' + JSON.stringify(pv));

  const w = await boot({user: 'frida', hash: 'office/invoices/' + I}); const d = w.document;
  // ================= #3594: the subject is a textarea
  const ta = await until(() => d.querySelector('#ofd-project_title'));
  check(ta && ta.tagName === 'TEXTAREA' && +ta.getAttribute('rows') >= 2 && ta.getAttribute('maxlength') === '1000' && ta.dataset.grow,
    '#3594: the subject is a growing textarea (2 rows, 1000 characters): ' + (ta && ta.outerHTML.slice(0, 160)));
  ta.focus(); ta.value = 'Imagefilm\nDreh und Schnitt'; ta.dispatchEvent(new w.Event('input', {bubbles: true})); ta.dispatchEvent(new w.Event('change', {bubbles: true})); ta.blur();
  check(await until(async () => (await call('GET', `/api/office/docs/${I}`)).project_title === 'Imagefilm\nDreh und Schnitt'), '#3594: the line break is saved');
  check(+ta.rows >= 2, '#3594: the field keeps at least 2 rows');

  // ================= #3605: the finalise dialog names the number
  const asked = [];
  w.confirm = t => { asked.push(t); return false; };
  d.querySelector('[data-ofd="finalize"]').click();
  check(await until(() => asked.length), '#3605: Finalise asks first');
  check(asked[0] && asked[0].includes('Will be finalised as ' + pv.number), '#3605: the question names the number: ' + asked[0]);
  check(await until(() => !d.querySelector('.modal.cdlg')), 'the dialog closes on Cancel');
  const still = await call('GET', `/api/office/docs/${I}`);
  check(!still.locked && !still.number, '#3605: Cancel finalises nothing (no number given)');
  check((await call('GET', `/api/office/docs/${I}/number-preview`)).number === pv.number, '#3605: Cancel moved no number');
  w.confirm = t => { asked.push(t); return true; };
  await until(() => d.querySelector('[data-ofd="finalize"]'));
  d.querySelector('[data-ofd="finalize"]').click();
  const fin = await until(async () => { const x = await call('GET', `/api/office/docs/${I}`); return x.locked && x; });
  check(fin && fin.number === pv.number, '#3605: finalised with the number the dialog named ' + (fin && fin.number));

  w.close();
  console.log(`p2431_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); console.log(`p2431_b_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
