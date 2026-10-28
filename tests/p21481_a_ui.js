// 2.148.1 part A (#2480, jsdom) joining an organisation needs the person's yes, own container (start.sh, mode workspaces):
// - an organisation admin adds an existing account by e-mail: the person is not a member yet, the News show the invitation
// - opening it asks "Join the organisation …?"; "Later" keeps it open, "Join" makes the person a member in the invited role
// - "Decline the invitation" removes it (a second invitation, declined)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21481A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: `${process.env.EXTRA || ''} -e KALMIDO_INSTANCE_MODE=workspaces`}});
const ck = {};
const call = async (who, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck[who]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const orgsOf = async who => ((await call(who, 'GET', '/api/state')).j.me?.workspaces || []).map(x => x.id);

(async () => {
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  ck.alice = await login('alice');
  await call('alice', 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const ids = {};
  for (const u of ['bob', 'carol']) ids[u] = (await call('alice', 'POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs: []})).j.id;
  const org = (await call('alice', 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: ids.bob})).j.id;
  const beta = (await call('alice', 'POST', '/api/admin/orgs', {name: 'Beta', admin_id: ids.bob})).j.id;
  for (const u of ['bob', 'carol']) { ck[u] = await login(u); await call(u, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments'}); }
  check((await call('bob', 'PUT', `/api/orgs/${org}/members`, {email: 'carol@example.com', role: 'member'})).status === 200, 'the admin invites carol by e-mail');
  check(!(await orgsOf('carol')).includes(org), 'membership needs acceptance: not a member yet');

  // ---- the invitation in the News: "Later" keeps it, "Join" makes carol a member
  let w = await boot({user: 'carol', hash: 'news'}), d = w.document;
  const item = await until(() => d.querySelector('.nitem.k-orgjoin'));
  check(!!item && /invites you to join the organisation/.test(item.textContent) && /Alpha/.test(item.textContent), 'the invitation shows in the News');
  item?.click();
  let dlg = await until(() => d.querySelector('.cdlg'));
  check(!!dlg && /Join the organisation Alpha/.test(dlg.textContent) && !!dlg.querySelector('[data-ojn="decline"]'), 'opening it asks to join, with decline');
  dlg?.querySelector('[data-cd="no"]')?.click();
  await sleep(400);
  check(!(await orgsOf('carol')).includes(org) && (await call('carol', 'GET', '/api/orgs')).j.joins?.length === 1, 'Later: still open, not a member');
  w.eval(`newsOpen((S.nf.items || []).findIndex(x => x.kind === 'orgjoin'))`);
  dlg = await until(() => d.querySelector('.cdlg'));
  dlg?.querySelector('[data-cd="yes"]')?.click();
  check(await until(async () => (await orgsOf('carol')).includes(org)), 'Join: carol is a member');
  check(await until(() => /You joined Alpha/.test(d.body.textContent)), 'Join: a short message');
  w.close();

  // ---- a second invitation, declined
  await call('bob', 'PUT', `/api/orgs/${beta}/members`, {email: 'carol@example.com'});
  w = await boot({user: 'carol', hash: 'news'}); d = w.document;
  const it2 = await until(() => [...d.querySelectorAll('.nitem.k-orgjoin')].find(x => /Beta/.test(x.textContent)));
  it2?.click();
  dlg = await until(() => d.querySelector('.cdlg'));
  dlg?.querySelector('[data-ojn="decline"]')?.click();
  check(await until(async () => !(await call('carol', 'GET', '/api/orgs')).j.joins?.length), 'Decline: the invitation is gone');
  check(!(await orgsOf('carol')).includes(beta), 'Decline: not a member');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
