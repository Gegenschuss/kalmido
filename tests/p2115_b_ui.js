// 2.115.0 UI tests (part B, #2062), own container (start.sh). jsdom:
//   Settings > Account > Active sessions: two sessions listed, exactly one "This device", device / browser read, "Log out"
//   on the other one (confirmation) ends it (its cookie is 401), the list redraws with one row and no "everywhere else" button;
//   "Log out everywhere else" with a third session: the toast with the count.
//   Settings > Organisation as its admin (not admin of the server): "Invite by e-mail" opens the dialog (address + role),
//   inviting gives the neutral answer (2.148.1: never the link, no mail notice) and the open invitation; withdraw (confirmation) removes it and the
//   account, ONE undo step invites the address again; a plain member sees no invite button.
// P2115B_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2115B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck, ...hd}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const UA_IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1';
const loginUA = async (user, ua) => {
  const r = await fetch(B + 'api/auth/login', {method: 'POST', headers: {...H, 'User-Agent': ua}, body: JSON.stringify({username: user, password: 'password123'})});
  return r.headers.get('set-cookie').split(';')[0];
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state');
  const ORG = st.me.workspaces[0].id;
  const uid = {};
  for (const u of ['bob', 'carol']) uid[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs: [ORG]})).id;
  await call('PUT', `/api/orgs/${ORG}/members`, {user_id: uid.bob, role: 'admin'});
  for (const u of ['bob', 'carol']) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, await login(u));
  const PHONE = await loginUA('bob', UA_IOS);

  // ================= Active sessions
  let w = await boot({user: 'bob'}), d = w.document;
  w.eval(`settingsModal('account')`);
  const box = await until(() => d.querySelectorAll('#s-ses .sesrow').length >= 3 && d.querySelector('#s-ses'));
  const rows = () => [...d.querySelectorAll('#s-ses .sesrow')];
  check(box && d.querySelector('#s-ses-h')?.textContent === 'Active sessions', 'the section "Active sessions" in Settings > Account');
  check(rows().length === 3 && rows().filter(r => r.querySelector('.sescur')).length === 1 && rows()[0].querySelector('.sescur'),
    `three sessions (boot, setting, phone), exactly one "This device", first: ${rows().length}`);
  const ph = rows().find(r => /Safari on iOS/.test(r.textContent));
  check(ph && /signed in since/.test(ph.textContent) && /Password/.test(ph.textContent), 'the phone: browser + system, since when, how');
  check(rows().every(r => r.querySelector('[data-ses="end"]')) && d.querySelector('#s-ses [data-ses="others"]'), 'every row: Log out; below: everywhere else');
  ph?.querySelector('[data-ses="end"]').click();
  await until(() => rows().length === 2);
  check(rows().length === 2 && !rows().some(r => /Safari on iOS/.test(r.textContent)), 'the phone session is gone from the list');
  check((await call('GET', '/api/state', null, PHONE)).status === 401, 'its cookie is 401');
  d.querySelector('#s-ses [data-ses="others"]').click();
  await until(() => rows().length === 1);
  check(rows().length === 1 && rows()[0].querySelector('.sescur') && !d.querySelector('#s-ses [data-ses="others"]'), 'everywhere else: only this device, no button any more');
  check(/1 session logged out/.test(d.querySelector('#toast')?.textContent || ''), 'the toast with the count');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // ================= Settings > Organisation: invite by e-mail
  w.eval(`settingsModal('org')`);
  const ib = await until(() => d.querySelector('.wsorg [data-oinv="new"]'));
  check(ib && /Invite by e-mail/.test(ib.textContent), 'the organisation admin: "Invite by e-mail"');
  ib?.click();
  const mi = await until(() => d.querySelector('#oinv-mail'));
  check(mi && d.querySelector('#oinv-role option[value="admin"]'), 'the dialog: address + role');
  mi.value = 'nora@example.com'; d.querySelector('#oinv-role').value = 'member';
  mi.closest('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  // 2.148.1 (#2486): an organisation admin never gets the link; 2.148.1 H (#2480): nor a notice about the mail -- the same
  // answer as for an existing account (bundle B: the test follows the review fix)
  check(await until(() => /Invitation sent/.test(d.body.textContent)) && !/could not be sent/.test(d.body.textContent) && !d.querySelector('#inv-link'), 'the organisation admin: the neutral answer, no link');
  const orow = await until(() => [...d.querySelectorAll('.oinvrow')].find(r => /nora@example\.com/.test(r.textContent)));
  check(orow && /Invited/.test(orow.textContent) && orow.querySelector('[data-oinv="resend"]') && orow.querySelector('[data-oinv="withdraw"]'), 'the open invitation with Resend + Withdraw');
  let inv = await call('GET', `/api/orgs/${ORG}/invites`, null, await login('bob'));
  check((inv.invites || []).length === 1, 'the server has the invitation');
  orow?.querySelector('[data-oinv="withdraw"]').click();
  await until(() => ![...d.querySelectorAll('.oinvrow')].some(r => /nora@/.test(r.textContent)));
  check(![...d.querySelectorAll('.oinvrow')].some(r => /nora@/.test(r.textContent)), 'withdrawn: the row is gone');
  inv = await call('GET', `/api/orgs/${ORG}/invites`, null, await login('bob'));
  check((inv.invites || []).length === 0, 'and on the server');
  await w.eval(`histStep('undo')`);
  await until(() => [...d.querySelectorAll('.oinvrow')].some(r => /nora@/.test(r.textContent)));
  inv = await call('GET', `/api/orgs/${ORG}/invites`, null, await login('bob'));
  check((inv.invites || []).length === 1 && inv.invites[0].email === 'nora@example.com', 'ONE undo step: the address is invited again');
  w.close();

  // ================= a plain member: no invite button
  w = await boot({user: 'carol'}); d = w.document;
  w.eval(`settingsModal('org')`);
  await until(() => d.querySelector('#s-ws .wsorg'));
  await sleep(600);
  check(d.querySelector('#s-ws .wsorg') && !d.querySelector('[data-oinv="new"]'), 'a plain member sees no "Invite by e-mail"');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
