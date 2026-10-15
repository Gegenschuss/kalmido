// 2.46.0 UI tests, part A (#1561 #1592), own container (start.sh), jsdom only. Invented names only.
// "New user" in Settings > Users: the organisation (none / each one; exactly one = preselected as a member) and the role
// in it; saved as orgs [{id, role}]; with two organisations nothing is preselected; the user list shows every account
// (also people outside the admin's organisations); Administration > Organisations offers "New organisation".
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

async function newUserDialog(w, d) {
  w.eval(`settingsModal('users')`);
  await until(() => d.querySelector('.smodal [data-acc="user-new"]') && d.querySelector('.smodal #a-orgs .mrow, .smodal #a-orgs .muted:not(.mhint)'));
  await sleep(300);
  click(w, d.querySelector('.smodal [data-acc="user-new"]'));
  await until(() => d.querySelector('.modal:not(.smodal) #u-user'));
  return [...d.querySelectorAll('.modal:not(.smodal)')].pop();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments'], org_name: 'Northwind'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ORG = (await call('GET', '/api/orgs')).orgs[0].id;
  const GINA = (await call('POST', '/api/users', {username: 'gina', display_name: 'Gina Outside', password: 'password123'})).id;

  // ================= one organisation: preselected as a member, the role can be admin
  let w = await boot({user: 'alice'}), d = w.document;
  await sleep(300);
  let md = await newUserDialog(w, d);
  const so = md.querySelector('#u-org'), sr = md.querySelector('#u-orgrole');
  check(so && so.value === String(ORG) && so.options.length === 2 && so.options[0].value === '0', '#1561: one organisation: preselected, "None" offered');
  check(sr && !md.querySelector('#u-orgrow').hidden && sr.value === 'member' && [...sr.options].map(o => o.value).join() === 'member,admin', '#1561: the role: member (default) / admin');
  change(w, so, '0');
  check(md.querySelector('#u-orgrow').hidden, '#1561: no organisation: no role');
  change(w, so, String(ORG)); change(w, sr, 'admin');
  input(w, md.querySelector('#u-name'), 'Dora Admin'); input(w, md.querySelector('#u-user'), 'dora'); input(w, md.querySelector('#u-pw'), 'password123');
  click(w, md.querySelector('[data-m="save"]'));
  await until(async () => (await call('GET', '/api/orgs')).orgs[0].members.some(m => m.name === 'Dora Admin'));
  let mem = (await call('GET', '/api/orgs')).orgs[0].members.find(m => m.name === 'Dora Admin');
  check(mem && mem.role === 'admin', '#1561: saved as an admin of the organisation ' + JSON.stringify(mem));
  // the user list: every account, also outside the admin's organisations
  await until(() => d.querySelector(`.smodal [data-urow="${GINA}"]`));
  check(d.querySelector(`.smodal [data-urow="${GINA}"]`), '#1592: the user management lists a person outside every organisation');
  check(d.querySelector('.smodal [data-acc="org-new"]'), '#1592: "New organisation" in the administration');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());

  // ================= a kid: never an admin (sent as a member)
  md = await newUserDialog(w, d);
  change(w, md.querySelector('#u-orgrole'), 'admin');
  const kid = md.querySelector('#u-kid'); kid.checked = true; change(w, kid);
  input(w, md.querySelector('#u-name'), 'Kim Kid'); input(w, md.querySelector('#u-user'), 'kim'); input(w, md.querySelector('#u-pw'), 'password123');
  click(w, md.querySelector('[data-m="save"]'));
  await until(async () => (await call('GET', '/api/orgs')).orgs[0].members.some(m => m.name === 'Kim Kid'));
  mem = (await call('GET', '/api/orgs')).orgs[0].members.find(m => m.name === 'Kim Kid');
  check(mem && mem.role === 'member', '#1561: a kid joins as a member ' + JSON.stringify(mem));
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.close();

  // ================= two organisations: nothing preselected
  await call('POST', '/api/admin/orgs', {name: 'Southwind'});
  w = await boot({user: 'alice'}); d = w.document;
  await sleep(300);
  md = await newUserDialog(w, d);
  check(md.querySelector('#u-org')?.value === '0' && md.querySelector('#u-org').options.length === 3 && md.querySelector('#u-orgrow').hidden, '#1561: two organisations: "None" preselected');
  input(w, md.querySelector('#u-name'), 'Nils None'); input(w, md.querySelector('#u-user'), 'nils'); input(w, md.querySelector('#u-pw'), 'password123');
  click(w, md.querySelector('[data-m="save"]'));
  await until(async () => (await call('GET', '/api/users?all=1')).users.some(u => u.username === 'nils'));
  const nils = (await call('GET', '/api/users?all=1')).users.find(u => u.username === 'nils');
  check(nils && nils.orgs.length === 0, '#1562: saved without an organisation ' + JSON.stringify(nils && nils.orgs));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
