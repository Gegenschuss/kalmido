// 2.143.0 UI tests (part A, #2151), own container (start.sh). jsdom:
//   Settings > Organisation as its admin: every member row has the role picker with all five roles (the stored role
//   selected), "What the roles mean" explains them; changing a role in the picker stores it on the server.
//   Invite by e-mail: the role picker has the new roles, its hint follows the chosen role.
//   A read-only member: an organisation-wide list is not editable in the app (canEditList / canEdit false), a member's is;
//   their organisation shows "your role: Read-only" and no role pickers.
// P2143A_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2143A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const uid = {};
  for (const [u, role] of [['bob', 'member'], ['rita', 'readonly']]) uid[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs: [{id: ORG, role}]})).id;
  for (const u of ['alice', 'bob', 'rita']) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, await login(u));
  const L1 = (await call('POST', '/api/lists', {name: 'Team board', org_id: ORG})).id;
  await call('PATCH', `/api/lists/${L1}`, {org_visibility: 'org', org_edit: 1});
  const T1 = (await call('POST', '/api/tasks', {list_id: L1, title: 'Plan the spring'})).id;

  // ================= the admin: role pickers + explanations
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('org')`);
  const sel = await until(() => d.querySelector(`#s-ws select[data-wsrole="${uid.rita}"]`));
  check(sel && sel.value === 'readonly', 'the member row: the stored role is selected');
  check(sel && [...sel.options].map(o => o.value).join() === 'member,admin,readonly,accounting,guest', 'all five roles in the picker: ' + (sel ? [...sel.options].map(o => o.value) : ''));
  check(sel && [...sel.options].every(o => o.title), 'each role carries its explanation as the tooltip');
  const help = d.querySelector('#s-ws .orgrolehelp');
  check(help && help.querySelectorAll('li').length === 5 && /What the roles mean/.test(help.textContent), '"What the roles mean" lists the five roles');
  const bs = d.querySelector(`#s-ws select[data-wsrole="${uid.bob}"]`);
  bs.value = 'guest'; bs.dispatchEvent(new w.Event('change', {bubbles: true}));
  const got = await until(async () => { const o = (await call('GET', '/api/orgs')).orgs.find(x => x.id === ORG); return (o.members.find(m => m.id === uid.bob) || {}).role === 'guest'; });
  check(got, 'changing the picker stores the role on the server');
  await call('PUT', `/api/orgs/${ORG}/members`, {user_id: uid.bob, role: 'member'});
  // invite by e-mail: the dialog's role picker
  const ib = await until(() => d.querySelector('.wsorg [data-oinv="new"]'));
  ib?.click();
  const rs = await until(() => d.querySelector('#oinv-role'));
  check(rs && rs.querySelector('option[value="guest"]') && rs.querySelector('option[value="accounting"]'), 'the invitation offers the new roles');
  const hint0 = d.querySelector('.oinvrolehint')?.textContent || '';
  rs.value = 'guest'; rs.dispatchEvent(new w.Event('change', {bubbles: true}));
  const hint1 = d.querySelector('.oinvrolehint')?.textContent || '';
  check(hint0 && hint1 && hint0 !== hint1 && /personally/.test(hint1), `the hint follows the role: "${hint0}" -> "${hint1}"`);
  w.close();

  // ================= a read-only member: nothing editable in the organisation
  w = await boot({user: 'rita'}); d = w.document;
  await until(() => w.eval(`!!listById(${L1})`));
  check(w.eval(`listById(${L1})?.role`) === 'view', 'read-only: the organisation-wide list arrives as view');
  check(w.eval(`canEditList(${L1})`) === false && w.eval(`canEdit(taskById(${T1}))`) === false, 'read-only: the app offers no editing');
  w.eval(`settingsModal('org')`);
  const sum = await until(() => d.querySelector('#s-ws .wsorg summary'));
  check(sum && /your role: Read-only/.test(sum.textContent), 'read-only: "your role" in the organisation: ' + (sum?.textContent || ''));
  check(!d.querySelector('#s-ws select[data-wsrole]') && !d.querySelector('.orgrolehelp'), 'read-only: no role pickers');
  w.close();
  w = await boot({user: 'bob'}); d = w.document;
  await until(() => w.eval(`!!listById(${L1})`));
  check(w.eval(`canEditList(${L1})`) === true, 'a member edits the same list');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
