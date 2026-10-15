// 2.49.0 UI test (lead), own container (start.sh). jsdom:
// #1770 the fixed sign Private / organisation in a list's header (from the list's own org_id, under "All" too); switching the
//       workspace leaves a list of another workspace for the inbox; opening a list of another workspace directly switches the
//       filter along (no list shown outside the chosen workspace any more).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const st0 = await call('GET', '/api/state');
  const ORG = st0.me.workspaces[0].id;
  const W = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const P = (await call('POST', '/api/lists', {name: 'Garden', org_id: null})).id;
  await call('POST', '/api/tasks', {title: 'Deploy', list_id: W});

  // under "All": the sign names the list's own workspace
  let w = await boot({user: 'alice', hash: 'l/' + W}), d = w.document;
  await until(() => d.querySelector('#top .wsbadge'));
  const sign = () => d.querySelector('#top h1 .wsbadge');
  check(sign() && /Example Org/.test(sign().textContent), '#1770: the organisation list carries the organisation sign under All ' + (sign()?.textContent || ''));
  check(!d.querySelector('#top .wschip'), '#1770: no second chip next to the sign');
  w.location.hash = '#l/' + P; await until(() => /Private/.test(sign()?.textContent || ''));
  check(sign() && /Private/.test(sign().textContent), '#1770: the private list carries "Private" ' + (sign()?.textContent || ''));
  w.location.hash = '#inbox'; await sleep(400);
  check(!sign(), '#1770: the inbox has no sign');

  // switching to Private while the organisation list is open -> the inbox
  w.location.hash = '#l/' + W; await until(() => /Example Org/.test(sign()?.textContent || ''));
  w.eval(`wsSet('private')`); await until(() => w.eval('S.route.key') === 'inbox');
  check(w.eval('S.route.key') === 'inbox', '#1770: switching the workspace leaves the list of another workspace for the inbox ' + w.eval('S.route.key'));
  // switching to the list's own workspace keeps it
  w.location.hash = '#l/' + P; await until(() => w.eval('S.route.key') === 'l:' + P);
  w.eval(`wsSet('private')`); await sleep(400);
  check(w.eval('S.route.key') === 'l:' + P, '#1770: a list of the chosen workspace stays open');

  // opening the organisation list directly while Private is shown: the filter follows
  w.location.hash = '#l/' + W; await until(() => w.eval('wsCur()') === 'org:' + ORG);
  check(w.eval('wsCur()') === 'org:' + ORG, '#1770: opening a list of another workspace switches the filter along ' + w.eval('wsCur()'));
  check(d.querySelectorAll('#view .trow').length === 1, '#1770: its tasks are shown');
  await until(async () => (await call('GET', '/api/state')).settings.workspace === 'org:' + ORG);
  check((await call('GET', '/api/state')).settings.workspace === 'org:' + ORG, '#1770: the followed filter is saved');
  check(w.eval(`wsHidden({list_id: ${P}})`) === true, '#1770: a task of another workspace is hidden, no exception for an open list');

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
