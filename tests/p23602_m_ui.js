#!/usr/bin/env node
// kalmido-suite: fresh
// 2.360.2 M UI tests (#2561), own container (start.sh). jsdom:
//   the Share dialog of a table: by address the row reads "Invited" with the address, for every address; removing it + Undo;
//   Settings > Organisation: the open invitation of an existing account has Resend and Withdraw like any other; withdrawing
//   needs a confirmation and removes it; with invitations switched off an open one stays visible with Withdraw only.
// P23602M_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P23602M_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().then(j => ({status: r.status, ...j})).catch(() => ({status: r.status})); };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id, uid = {};
  for (const u of ['bob', 'carol']) uid[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1) + ' Name', password: 'password123', email: `${u}@example.com`, orgs: u === 'bob' ? [ORG] : []})).id;
  await call('PUT', `/api/orgs/${ORG}/members`, {user_id: uid.bob, role: 'admin'});
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'sheets,collab,comments'}, BK);
  const S = await call('POST', '/api/sheets', {title: 'Holiday budget', space: 'private'}, BK);

  // ================= the Share dialog
  let w = await boot({user: 'bob', hash: 'sheets/' + S.id}), d = w.document;
  await until(() => d.querySelector('#view [data-shv="menu"]'));
  d.querySelector('#view [data-shv="menu"]')?.click();
  const it = await until(() => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"]')].find(b => b.textContent.trim() === 'Share…'));
  check(it, 'the menu offers Share…');
  it?.click();
  await until(() => d.querySelector('.shsdlg'));
  for (const em of ['carol@example.com', 'ghost@example.com']) {
    d.querySelector('#shs-mail').value = em;
    d.querySelector('[data-shs="mail"]').click();
    await until(() => d.querySelector('#shs-list').textContent.includes(em));
  }
  const rows = () => [...d.querySelectorAll('#shs-list .mrow')];
  check(rows().length === 2 && rows().every(r => /Invited/.test(r.textContent)), 'both addresses read "Invited": ' + d.querySelector('#shs-list').textContent);
  check(!/Carol Name/.test(d.querySelector('#shs-list').textContent), 'never the name of the account behind an address');
  check(/With an account at this address/.test(d.querySelector('#toast')?.textContent || ''), 'the neutral notice');
  rows()[1].querySelector('[data-shsx]').click();
  await until(() => rows().length === 1);
  check(rows().length === 1, 'an address row can be removed');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/sheets/${S.id}/shares`, null, BK)).shares?.length === 2), 'Undo: the address is back');
  w.close();

  // ================= open invitations
  await call('POST', `/api/orgs/${ORG}/invites`, {email: 'carol@example.com', role: 'member'}, BK);
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('org')`);
  const row = await until(() => [...d.querySelectorAll('.oinvrow')].find(r => /carol@example\.com/.test(r.textContent)));
  check(row?.querySelector('[data-oinv="resend"]') && row?.querySelector('[data-oinv="withdraw"]'), 'an existing account: Resend and Withdraw like any invitation');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  await call('PATCH', '/api/admin/settings', {org_invites: false});
  w.eval(`settingsModal('org')`);
  const off = await until(() => [...d.querySelectorAll('.oinvrow')].find(r => /carol@example\.com/.test(r.textContent)));
  check(off && !off.querySelector('[data-oinv="resend"]') && off.querySelector('[data-oinv="withdraw"]'), 'invitations off: the row stays, Withdraw only');
  off?.querySelector('[data-oinv="withdraw"]').click();
  const yes = await until(() => d.querySelector('[data-cd="yes"], [data-cd="ok"]'));
  check(yes, 'withdrawing asks first');
  yes?.click();
  check(await until(async () => (await call('GET', `/api/orgs/${ORG}/invites`, null, BK)).invites?.length === 0), 'the invitation is gone');
  await until(() => !d.querySelector('.oinvrow'));
  check(!d.querySelector('.oinvrow'), 'the row is gone');
  await call('PATCH', '/api/admin/settings', {org_invites: true});
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
