// kalmido-suite: fresh
// 2.364.0 D (#3020) the file store's organisation tab for a member: organisation folders need org_access or a share
// (kalmido/files/store.py, unchanged). An empty organisation tab tells a member why ("... once an admin opens them to
// everyone or shares them with you"); an admin does not get that line. An admin's "New folder" at the top of an
// organisation asks "Visible to all members?" (default off = the folder stays closed as before; ticked = org_access view,
// the member sees it). Own container (start.sh), jsdom.
// freelancer-matrix: files - frida has no organisation: her private tab gets neither the line nor the question.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 6000) => { for (let t = 0; t < ms; t += 100) { if (f()) return true; await sleep(100); } return !!f(); };
const FEAT = 'cal,comments,collab,files';
const HINT = 'once an admin opens them to everyone';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CB = await login('bob'), CF = await login('frida');
  for (const ck of [CA, CB, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'P4: frida is in no organisation');
  const sp = `org:${org.id}`;
  const empty = d => d.querySelector('#view .abempty');

  // (1) the member's empty organisation tab explains why
  let w = await boot({user: 'bob', hash: 'ablage'}), d = w.document;
  check(await until(() => !!empty(d)), 'bob: the empty organisation tab ' + w.eval('S.route.mod + " " + ab_curSpace()'));
  check(w.eval('ab_curSpace()') === sp, 'bob: the organisation tab is open');
  check((d.querySelector('#view .abemptyhint')?.textContent || '').includes(HINT), 'bob (member): the line about admins opening / sharing folders');
  w.close();

  // (2) the admin: no such line; "New folder" asks "Visible to all members?" (default off)
  w = await boot({user: 'alice', hash: 'ablage'}); d = w.document;
  check(await until(() => !!empty(d)), 'alice: the empty organisation tab');
  check(!d.querySelector('#view .abemptyhint'), 'alice (admin): no line about admins');
  const newFolder = async (name, tick) => {
    w.eval('ab_newFolder()');
    check(await until(() => !!d.querySelector('.cdlg #cdlg-in')), 'the New folder dialog ' + name);
    const box = d.querySelector('.cdlg #ab-nfall');
    check(!!box && !box.checked, 'admin: the question "Visible to all members?", unticked ' + name);
    check((box?.closest('label')?.textContent || '').includes('Visible to all members?'), 'the question text');
    if (box && tick) { box.checked = true; box.dispatchEvent(new w.Event('change', {bubbles: true})); }
    d.querySelector('.cdlg #cdlg-in').value = name;
    d.querySelector('.cdlg form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
    const got = async () => ((await call(CA, 'GET', `/api/files?space=${encodeURIComponent(sp)}`)).items || []).find(n => n.name === name);
    let n = null; for (let i = 0; i < 40 && !(n = await got()); i++) await sleep(150);
    if (tick) for (let i = 0; i < 40 && n && !n.org_access; i++) { await sleep(150); n = await got(); }
    return n;
  };
  const open = await newFolder('Contracts', true);
  check(open && open.org_access === 'view', 'ticked: the folder is open to every member (org_access view) ' + JSON.stringify(open && open.org_access));
  const closed = await newFolder('Board', false);
  check(closed && closed.org_access === '', 'unticked: as before, closed ' + JSON.stringify(closed && closed.org_access));
  w.close();
  const bobSees = ((await call(CB, 'GET', `/api/files?space=${encodeURIComponent(sp)}`)).items || []).map(n => n.name);
  check(bobSees.includes('Contracts') && !bobSees.includes('Board'), 'bob sees the opened folder only ' + JSON.stringify(bobSees));

  // (3) P4: frida (no organisation): private tab, no line, no question
  w = await boot({user: 'frida', hash: 'ablage'}); d = w.document;
  check(await until(() => !!empty(d)), 'frida: the empty private tab');
  check(w.eval('ab_curSpace()') === 'private' && !d.querySelector('#view .abemptyhint'), 'frida: no line about admins');
  w.eval('ab_newFolder()');
  check(await until(() => !!d.querySelector('.cdlg #cdlg-in')), 'frida: the New folder dialog');
  check(!d.querySelector('.cdlg #ab-nfall'), 'frida: no question about members');
  d.querySelector('.cdlg #cdlg-in').value = 'Taxes';
  d.querySelector('.cdlg form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  let fr = []; for (let i = 0; i < 40 && !fr.includes('Taxes'); i++) { await sleep(150); fr = ((await call(CF, 'GET', '/api/files?space=private')).items || []).map(n => n.name); }
  check(fr.includes('Taxes'), 'frida: the folder is created ' + JSON.stringify(fr));
  w.close();

  console.log(`p2364_d_ablage_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
