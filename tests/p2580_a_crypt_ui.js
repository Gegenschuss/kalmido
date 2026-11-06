// kalmido-suite: fresh
// 2.580.0 A (#4485) UI test (jsdom), own container, invented data only: Settings > Organisation > Data shows the overview of
// what is encrypted ONCE, folded under "What is encrypted?" - not again in every organisation's box and not again in the admin
// block. Three organisations: one overview, closed; every organisation keeps its own state and key buttons.
// A server admin WITHOUT an organisation (the person on her own): the overview is there once, too (in the admin block).
// freelancer-matrix: settings
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const ORGS = [(await call('GET', '/api/state')).me.workspaces[0].id];
  for (const n of ['Beta Films', 'Gamma Works']) ORGS.push((await call('POST', '/api/admin/orgs', {name: n, admin_id: ME})).id);
  check(ORGS.length === 3 && ORGS.every(Boolean), 'setup: three organisations');

  // ================= three organisations: the overview once, folded
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('org')`);
  const md = await until(() => d.querySelector('.smodal'));
  click(w, md.querySelector('[data-admsub="odata"]'));
  const od = md.querySelector('#admp-odata');
  check(await until(() => ORGS.every(o => od.querySelector(`#s-wsdata .ocbox[data-ocorg="${o}"] .ocst [data-oc="show"], #s-wsdata .ocbox[data-ocorg="${o}"] .ocst .shint`))), 'every organisation shows its state and key buttons');
  check(await until(() => md.querySelectorAll('.pmcsw').length >= 1), 'the overview is drawn');
  await sleep(500);  // the admin block loads beside the boxes: it must not add a second one
  check(md.querySelectorAll('.pmcsw').length === 1, 'the overview exists exactly once (' + md.querySelectorAll('.pmcsw').length + ')');
  const det = md.querySelector('details#s-cryptscope');
  check(det && !det.open && /What is encrypted\?/.test(det.querySelector('summary')?.textContent || '') && det.querySelector('.pmcsw .pmcs.on') && det.querySelector('.pmcsw .pmcs.off'), 'it stands folded under "What is encrypted?" with both lists');
  check(!md.querySelector('.ocbox .pmcsw, #s-orgenc .pmcsw, .ocst .pmcsw'), 'not inside an organisation box and not in the admin block');
  check(det && od.querySelector('#s-wsdata-h').compareDocumentPosition(det) & 4, 'it stands in the Data area under its heading');
  w.close();

  // ================= a server admin without an organisation: once, in the admin block
  const DAVE = (await call('POST', '/api/users', {username: 'dave', display_name: 'Dave', password: 'password123', email: 'dave@example.com', is_admin: true, orgs: []})).id;
  check(!!DAVE, 'setup: an admin without an organisation');
  const CD = await login('dave');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CD);
  check(!((await call('GET', '/api/state', null, CD)).me.workspaces || []).length, 'dave: no organisation');
  w = await boot({user: 'dave'}); d = w.document;
  w.eval(`settingsModal('org')`);
  const md2 = await until(() => d.querySelector('.smodal'));
  click(w, md2.querySelector('[data-admsub="odata"]'));
  check(await until(() => md2.querySelectorAll('.pmcsw').length >= 1), 'without an organisation: the overview is drawn');
  await sleep(500);
  const det2 = md2.querySelector('details#s-cryptscope');
  check(md2.querySelectorAll('.pmcsw').length === 1 && det2 && !det2.open && det2.querySelector('.pmcsw'), 'without an organisation: once, folded, in the admin block');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  console.log(`p2580_a_crypt_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2580_a_crypt_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
