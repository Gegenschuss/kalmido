// 2.46.0 part B (#1603, jsdom) "Everyone in the organisation", own container (start.sh, mode workspaces):
// - the list dialog of an organisation list shows "Visibility" (Only invited people / Everyone in the organisation) to the
//   owner; switching saves at once with one undo step, the switch "Members of the organisation may edit" appears with it
// - a private list has no such row; a member without admin rights sees it disabled
// - a reader (organisation member, not invited) sees the list in the sidebar with the "Not joined" mark, a bar with "Join"
//   instead of "View only"; its tasks stay out of Today until joining; "Join" makes them a member (one undo step = leave)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2460B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: `${process.env.EXTRA || ''} -e KALMIDO_INSTANCE_MODE=workspaces`}});
const ck = {};
const call = async (who, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck[who]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const T0 = ymd(new Date());
const ready = async (w, id) => until(() => { try { return !!w.eval(`listById(${id})`); } catch { return false; } }, 60);
const state = async who => (await call(who, 'GET', '/api/state')).j;

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  ck.alice = await login('alice');
  await call('alice', 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const ids = {};
  for (const u of ['bob', 'carol', 'dave']) ids[u] = (await call('alice', 'POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`})).j.id;
  const org = (await call('alice', 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: ids.bob})).j.id;
  for (const u of ['bob', 'carol', 'dave']) { ck[u] = await login(u); await call(u, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments'}); }
  for (const u of ['carol', 'dave']) await call('bob', 'PUT', `/api/orgs/${org}/members`, {email: `${u}@example.com`});
  for (const u of ['carol', 'dave']) await call(u, 'POST', `/api/orgs/${org}/join`);  // 2.148.1 (#2480): they accept the invitation
  for (const u of ['bob', 'carol', 'dave']) ck[u] = await login(u);  // the new memberships in the session
  const L = (await call('bob', 'POST', '/api/lists', {name: 'Orgwide plan', org_id: org})).j.id;
  const P = (await call('bob', 'POST', '/api/lists', {name: 'Own notes', org_id: null})).j.id;
  await call('bob', 'POST', '/api/tasks', {title: 'Due today in the plan', list_id: L, due: T0});
  await call('bob', 'PUT', `/api/lists/${L}/members`, {user_id: ids.dave, role: 'edit'});

  // ---- the owner's list dialog
  let w = await boot({user: 'bob', hash: 'l/' + L}), d = w.document;
  await ready(w, L); w.listModal(L);
  let sel = await until(() => d.querySelector('#l-ovis'));
  check(sel && !sel.disabled && sel.value === '', 'owner: the row "Visibility", default "Only invited people"');
  check(d.querySelector('.ovedit')?.hidden === true, 'owner: the edit switch is hidden while only invited people see it');
  sel.value = 'org'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await state('bob')).lists.find(l => l.id === L)?.org_visibility === 'org'), 'owner: "Everyone in the organisation" saved at once');
  check(await until(() => d.querySelector('.ovedit')?.hidden === false), 'owner: the switch "Members of the organisation may edit" appears');
  check(/organisation/.test(d.querySelector('#l-ovhint')?.textContent || ''), 'owner: the hint follows the choice');
  check(await until(() => /Visible to everyone in the organisation/.test(d.body.textContent)), 'owner: a message with undo');
  await w.histStep?.('undo');
  if (typeof w.histStep === 'function') {
    check(await until(async () => (await state('bob')).lists.find(l => l.id === L)?.org_visibility === ''), 'undo: back to only invited people');
    await call('bob', 'PATCH', `/api/lists/${L}`, {org_visibility: 'org'});
  }
  w.close();
  w = await boot({user: 'bob', hash: 'l/' + P}); d = w.document;
  await ready(w, P); w.listModal(P);
  await until(() => d.querySelector('#l-name'));
  check(!d.querySelector('#l-ovis'), 'a private list: no row "Visibility"');
  w.close();
  w = await boot({user: 'dave', hash: 'l/' + L}); d = w.document;
  await ready(w, L); w.listModal(L);
  sel = await until(() => d.querySelector('#l-ovis'));
  check(sel && sel.disabled && sel.value === 'org', 'an invited member: the row read-only');
  w.close();

  w = await boot({user: 'dave', hash: 'today'}); d = w.document;
  check(await until(() => /Due today in the plan/.test(d.querySelector('#view')?.textContent || '')), 'an invited member: the task in Today');
  w.close();
  // ---- the reader
  w = await boot({user: 'carol', hash: 'today'}); d = w.document;
  await ready(w, L);
  check(!/Due today in the plan/.test(d.querySelector('#view')?.textContent || ''), 'reader: the tasks stay out of Today');
  const row = await until(() => d.querySelector(`#side [data-l="${L}"], #side [data-id="${L}"], [data-go="l:${L}"]`) || [...d.querySelectorAll('#side *')].find(e => e.textContent.trim() === 'Orgwide plan'));
  check(!!row, 'reader: the list in the sidebar');
  check(!!d.querySelector('#side .ovmark'), 'reader: the quiet mark "Not joined"');
  w.close();
  w = await boot({user: 'carol', hash: 'l/' + L}); d = w.document;
  const btn = await until(() => d.querySelector('[data-ovjoin]'));
  check(!!btn && /Join/.test(btn.textContent), 'reader: the bar with "Join"');
  check(/Due today in the plan/.test(d.querySelector('#view')?.textContent || ''), 'reader: the list itself shows its tasks');
  btn.click();
  check(await until(async () => (await state('carol')).lists.find(l => l.id === L)?.org_reader !== true), 'join: a member');
  check(await until(() => !d.querySelector('[data-ovjoin]')), 'join: the bar is gone');
  check(await until(() => /You joined/.test(d.body.textContent)), 'join: a message with undo');
  if (typeof w.histStep === 'function') {
    await w.histStep('undo');
    check(await until(async () => (await state('carol')).lists.find(l => l.id === L)?.org_reader === true), 'undo of join: reader again');
  }
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
