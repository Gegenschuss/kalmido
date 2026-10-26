// 2.364.0 C (#3041) UI tests, own container (start.sh). jsdom, invented data only:
// - Settings > Organisation is the one place to manage: People (members with the role picker in their row, the server's
//   users, groups), Agents (server admins), Data (encryption, recovery key, export, backups); "Administration" is called
//   "Server" (Sign-in, Server, Log) and only a server admin sees it; a sub-tab of the other area opens that area.
// - ONE invitation dialog: by e-mail, or (server admins only, as before) by link: a new account in the organisation with
//   the chosen role, the link to copy. An organisation admin who is no server admin gets no link choice.
// - The recovery key / export of an organisation once (Organisation > Data), not again under People or the server switch.
// - One role word: the project role "view" reads "Read-only" (German "Nur lesen"), the server admin box "Manage the server".
// - A member sees no sub-tabs and no invitation; a person without an organisation keeps their own settings (P4).
// - #3044: Settings > Access is listed only with an own API token / webhook, else it waits under Integrations > "For advanced
//   users"; "New user" folds SSO login, ntfy topic, child account and the OIDC note under "Advanced"; everyday German words.
// freelancer-matrix: settings
// kalmido-suite: fresh
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2364C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const secOn = md => md.querySelector('.snav .on')?.dataset.sec;
const subs = (md, sec) => [...md.querySelectorAll(`[data-pane="${sec}"] [data-admsub]`)].map(b => b.dataset.admsub).join();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const uid = {};
  for (const [u, role] of [['olga', 'admin'], ['bob', 'member']]) uid[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs: [{id: ORG, role}]})).id;
  uid.frida = (await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'})).id;  // no organisation
  for (const u of ['alice', 'olga', 'bob', 'frida']) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, await login(u));

  // ================= the server admin (also the organisation's admin)
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('org')`);
  let md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'org', 'settingsModal(org) opens Organisation: ' + secOn(md));
  check(subs(md, 'org') === 'users,agents,odata', 'Organisation: People, Agents, Data: ' + subs(md, 'org'));
  check(subs(md, 'users') === 'signin,server,log', 'Server: Sign-in, Server, Log: ' + subs(md, 'users'));
  check(md.querySelector('.snav [data-sec="users"] span')?.textContent === 'Server' && ![...md.querySelectorAll('.snav [data-sec] span')].some(s => s.textContent === 'Administration'), 'the area is called Server, no "Administration"');
  const people = md.querySelector('#admp-users');
  check(people && !people.hidden && people.querySelector('#s-ws') && people.querySelector('#a-users') && people.querySelector('[data-acc="user-new"]'), 'People: the organisation\'s members and the server\'s users in one place');
  // the role in the person's row
  const rs = await until(() => d.querySelector(`#s-ws select[data-wsrole="${uid.bob}"]`));
  check(rs && rs.closest('.mrow') && /Bob/.test(rs.closest('.mrow').textContent), 'the role picker sits in Bob\'s row');
  if (rs) { rs.value = 'readonly'; rs.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => ((await call('GET', '/api/orgs')).orgs.find(o => o.id === ORG)?.members.find(m => m.id === uid.bob) || {}).role === 'readonly'), 'the role saves from the row');
  check([...(rs?.options || [])].find(o => o.value === 'readonly')?.textContent === 'Read-only', 'organisation role word "Read-only"');
  // one invitation dialog: by e-mail or by link
  const ib = await until(() => d.querySelector(`.wsorg[data-oid="${ORG}"] .wsadd [data-oinv="new"]`));
  check(ib && /Invite people/.test(ib.textContent) && !d.querySelector('[data-wsadd]'), 'one "Invite people" button instead of the field + Add');
  click(w, ib);
  let dlg = await until(() => d.querySelector('#oinv-mail')?.closest('.modal'));
  check(dlg && dlg.querySelector('[data-oinvhow="mail"].on') && dlg.querySelector('[data-oinvhow="link"]') && dlg.querySelector('#oinv-role'), 'the dialog: by e-mail (on) or by link, with the role');
  click(w, dlg?.querySelector('[data-oinvhow="link"]'));
  check(dlg && !dlg.querySelector('#oinv-name').closest('.row').hidden && !dlg.querySelector('#oinv-mail').required, 'by link: the name field, the e-mail optional');
  if (dlg) {
    const nm = dlg.querySelector('#oinv-name'); nm.value = 'Lena Link'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
    const un = dlg.querySelector('#oinv-user'); if (!un.value) un.value = 'lena.link';
    dlg.querySelector('#oinv-role').value = 'readonly';
    dlg.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  }
  const lk = await until(() => d.querySelector('#inv-link'));
  check(lk && /#invite\//.test(lk.value), 'by link: the invitation link to copy');
  const lena = await until(async () => ((await call('GET', '/api/orgs')).orgs.find(o => o.id === ORG)?.members || []).find(m => m.name === 'Lena Link'));
  check(lena && lena.role === 'readonly', 'by link: a new account in the organisation with the chosen role: ' + JSON.stringify(lena || {}));
  d.querySelectorAll('.modal:not(.smodal)').forEach(m => m.remove());
  // Data: the organisation's boxes once, backups beside them
  click(w, md.querySelector('[data-admsub="odata"]'));
  const od = md.querySelector('#admp-odata');
  check(od && !od.hidden, 'Data opens');
  check(await until(() => od.querySelector(`#s-wsdata .ocbox[data-ocorg="${ORG}"]`) && od.querySelector(`#s-wsdata .oxbox[data-oxorg="${ORG}"]`)), 'Data: encryption + recovery key and the export of the organisation');
  check(!md.querySelector(`#s-ws .ocbox[data-ocorg="${ORG}"], #s-ws .oxbox, .ocadm`) && md.querySelectorAll(`.ocbox[data-ocorg="${ORG}"]`).length === 1, 'the recovery key once (not under People, not under the server switch)');
  check(od.querySelector('#s-bk-h') && od.querySelector('#s-orgenc') && !md.querySelector('[data-pane="users"] #s-bk'), 'Data: backups and the encryption switch (no longer under Server)');
  // Agents: the members' switch and the server-wide rules together
  check(md.querySelector('#admp-agents #s-orgagents') && md.querySelector('#admp-agents #s-uag'), 'Agents: "Members may connect agents" and the rules for every agent');
  // a jump into the other area
  w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove()); settingsModal('server')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'users' && !md.querySelector('#admp-server').hidden, "settingsModal('server'): Server > Server");
  click(w, md.querySelector('[data-admsub="agents"]'));
  check(await until(() => secOn(md) === 'org' && !md.querySelector('#admp-agents').hidden), 'a sub-tab of Organisation opens Organisation: ' + secOn(md));
  // the server admin box in "Edit user"
  click(w, md.querySelector('[data-admsub="users"]'));
  const eb = await until(() => md.querySelector(`#a-users [data-acc="user-edit"][data-uid="${uid.bob}"]`));
  click(w, eb);
  const um = await until(() => d.querySelector('#u-admin')?.closest('.modal'));
  check(um && /Manage the server/.test(um.querySelector('#u-admin').closest('label').textContent), 'Edit user: "Manage the server" instead of "Admin"');
  w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove())`);
  // #3044: "New user": the special fields under a closed "Advanced"
  w.eval(`userModal(null)`);
  const nu = await until(() => d.querySelector('#u-proxy')?.closest('.modal'));
  const adv = nu?.querySelector('details.uadv');
  check(adv && !adv.open && ['#u-proxy', '#u-topic', '#u-kid'].every(q => adv.querySelector(q)) && /OIDC/.test(adv.textContent), 'New user: SSO, ntfy, child account and OIDC folded under "Advanced"');
  check(nu && !nu.querySelector('#u-name').closest('details') && !nu.querySelector('#u-email').closest('details') && !/OIDC/.test(nu.querySelector('#u-email').placeholder), 'New user: name and e-mail stay in view, no OIDC word at the e-mail');
  w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove())`);
  // one role word in projects
  check(w.eval(`tr(ROLES.find(r => r[0] === 'view')[1])`) === 'Read-only' && w.eval(`tr(FP_ROLES.find(r => r[0] === 'view')[1])`) === 'Read-only', 'project role "view" reads "Read-only"');
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('org')`);
  md = await until(() => d.querySelector('.smodal'));
  await until(() => md.querySelector('#s-ws .wsorg'));
  const navs = [...md.querySelectorAll('.snav [data-sec] span')].map(s => s.textContent);
  check(navs.includes('Organisation') && navs.includes('Server') && !navs.includes('Verwaltung'), 'German: Organisation + Server, no Verwaltung: ' + navs.join('|'));
  const ros = [...md.querySelectorAll('#s-ws select[data-wsrole] option')].map(o => o.textContent);
  check(w.eval(`tr(ROLES.find(r => r[0] === 'view')[1])`) === 'Nur lesen' && ros.includes('Nur lesen') && !ros.some(t => /Betrachter|Read-only/.test(t)), 'German: "Nur lesen" for projects and organisations: ' + [...new Set(ros)].join('|'));
  check(/Personen einladen/.test(md.querySelector('#s-ws').textContent), 'German: "Personen einladen"');
  // #3044: everyday words (old -> new in the report)
  const W = {'Tab bar': 'Leiste unten', 'Swimlanes': 'Zeilen', 'Block': 'Kachel', 'Lying idle': 'Unberührt', 'Host default': 'Vorgabe des Servers', 'Show the celebration': 'Kleine Feier zeigen',
    'Copy as [[link]]': 'Als Verweis kopieren', 'Web Push': 'Browser-Push', 'ntfy topic': 'ntfy-Thema', 'Pipeline, weighted': 'Anfragen nach Chance', 'Advanced': 'Erweitert', 'For advanced users': 'Für Fortgeschrittene'};
  const bad = Object.entries(W).filter(([k, v]) => w.eval(`tr(${JSON.stringify(k)})`) !== v).map(([k]) => k + '=' + w.eval(`tr(${JSON.stringify(k)})`));
  check(!bad.length, 'German everyday words: ' + bad.join(' | '));
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= the organisation's admin (no server admin)
  w = await boot({user: 'olga'}); d = w.document;
  w.eval(`settingsModal('org')`);
  md = await until(() => d.querySelector('.smodal'));
  check(secOn(md) === 'org' && subs(md, 'org') === 'users,odata', 'organisation admin: People and Data, no Agents: ' + subs(md, 'org'));
  check(!md.querySelector('.snav [data-sec="users"]') && !md.querySelector('#a-users'), 'organisation admin: no Server, no server users');
  click(w, await until(() => d.querySelector(`.wsorg[data-oid="${ORG}"] [data-oinv="new"]`)));
  dlg = await until(() => d.querySelector('#oinv-mail')?.closest('.modal'));
  check(dlg && !dlg.querySelector('[data-oinvhow]'), 'organisation admin: invitation by e-mail only (the link stays with the server admins)');
  d.querySelectorAll('.modal:not(.smodal)').forEach(m => m.remove());
  check(await until(() => md.querySelector(`#admp-odata #s-wsdata .oxbox[data-oxorg="${ORG}"]`)), 'organisation admin: the export under Data');
  w.close();

  // ================= a member
  await call('PUT', `/api/orgs/${ORG}/members`, {user_id: uid.bob, role: 'member'});
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('org')`);
  md = await until(() => d.querySelector('.smodal'));
  await until(() => md.querySelector('#s-ws .wsorg'));
  check(secOn(md) === 'org' && !md.querySelector('[data-admsub]') && !md.querySelector('.snav [data-sec="users"]'), 'member: Organisation without sub-tabs, no Server');
  check(!md.querySelector('[data-oinv="new"]') && !md.querySelector('#s-wsdata'), 'member: no invitation, no data boxes');
  // #3044: no own token / webhook: Access is not listed, it waits under Integrations > "For advanced users"
  const acb = md.querySelector('.snav [data-sec="access"]');
  check(acb && acb.hidden, 'member without a token: Access not listed');
  const ga = md.querySelector('[data-pane="integr"] details.aczadv [data-m="go-access"]');
  check(ga && !ga.closest('details').open, 'Integrations: Access under a closed "For advanced users"');
  click(w, ga);
  check(await until(() => secOn(md) === 'access' && !acb.hidden), 'the link opens Access and lists it');
  w.close();
  const CB = await login('bob');
  check((await call('POST', '/api/me/tokens', {name: 'Script', scopes: ['read']}, CB)).status < 300, 'bob: an own API token');
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('integr')`);
  md = await until(() => d.querySelector('.smodal'));
  check(!md.querySelector('.snav [data-sec="access"]').hidden && !md.querySelector('details.aczadv') && md.querySelector('[data-pane="integr"] [data-m="go-access"]'), 'with an own token: Access listed, the link not folded');
  w.close();

  // ================= without an organisation (P4): the own settings stay
  w = await boot({user: 'frida'}); d = w.document;
  w.eval(`settingsModal('account')`);
  md = await until(() => d.querySelector('.smodal'));
  const fs = [...md.querySelectorAll('.snav [data-sec]')].map(b => b.dataset.sec);
  check(!fs.includes('org') && !fs.includes('users') && ['account', 'general', 'look', 'notify', 'data'].every(k => fs.includes(k)), 'without an organisation: the own areas, no Organisation / Server: ' + fs.join());
  check(md.querySelector('#sp-data a[href="/api/export.json"]') && md.querySelector('#sp-account'), 'without an organisation: the own export and account');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2364_c_admin_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
