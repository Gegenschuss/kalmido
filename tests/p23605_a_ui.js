#!/usr/bin/env node
// kalmido-suite: fresh
// 2.360.5 UI test (#3245, test gap of 2.240.0 A #2884), own container (start.sh, an assistant configured, no model call). jsdom:
//   Settings > Organisation: the switch "The assistant may read comments of other members" under the organisation; its admin
//   turns it on (stored on the server, PATCH /api/orgs/<id>) and off again; a plain member sees it read-only (disabled) with
//   "Only an admin of this organisation can change it."; a person without an organisation sees no such switch.
// P23605A_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const AI_ENV = ' -e KALMIDO_AI_BASE_URL=http://127.0.0.1:8089/v1 -e KALMIDO_AI_MODEL=fake-1 -e KALMIDO_AI_KEY=test-key -e KALMIDO_AI_NAME=Fake-AI';
if (!process.env.P23605A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + AI_ENV}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().then(j => ({status: r.status, ...j})).catch(() => ({status: r.status})); };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [{id: ORG, role: 'member'}]});
  await call('POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com'});
  for (const u of ['alice', 'bob', 'fiona']) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, await login(u));
  const st = await call('GET', '/api/state');
  check(st.assistant && st.assistant.enabled, 'setup: the server has an assistant ' + JSON.stringify(st.assistant || {}).slice(0, 120));
  const orgOn = async () => ((await call('GET', '/api/orgs')).orgs || []).find(o => o.id === ORG)?.asst_comments;
  check(!(await orgOn()), 'the switch is off by default');

  // ================= the admin turns it on and off
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('org')`);
  let cb = await until(() => d.querySelector(`#s-ws .asst-orgrow #asst-o${ORG}`));
  check(cb && !cb.disabled && !cb.checked, 'the admin: the switch under the organisation, off, changeable');
  if (cb) {
    cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
    check(await until(async () => (await orgOn()) === true), 'ticking it stores the switch on the server');
    cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
    check(await until(async () => (await orgOn()) === false), 'unticking it turns it off again');
  }
  w.close();

  // ================= a plain member: read-only
  await call('PATCH', `/api/orgs/${ORG}`, {asst_comments: true});
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('org')`);
  cb = await until(() => d.querySelector(`#s-ws .asst-orgrow #asst-o${ORG}`));
  check(cb && cb.disabled && cb.checked, 'a member: the switch shows its state, disabled');
  const hint = cb ? cb.closest('.asst-orgrow').nextElementSibling : null;
  check(hint && /Only an admin of this organisation can change it/.test(hint.textContent), 'a member: the hint names who decides: ' + (hint?.textContent || ''));
  w.close();

  // ================= a person without an organisation: no switch (freelancer: no organisation, nothing to share)
  w = await boot({user: 'fiona'}); d = w.document;
  w.eval(`settingsModal('org')`);
  await until(() => d.querySelector('#s-ws')?.children.length);  // the workspaces pane drew its content
  check(!d.querySelector('.asst-orgrow'), 'a person without an organisation: no switch');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
