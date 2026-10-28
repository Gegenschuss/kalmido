// kalmido-suite: fresh
// 2.409.0 (#3490) UI test (jsdom), own container (start.sh): areas on / off per workspace
//  - the organisation's admins switched the office off, Bob himself the knowledge pages in Private: the office is gone in the
//    organisation's view, there in Private; the knowledge pages the other way round; "All workspaces" shows both (on in one)
//  - Settings > Modules: the main switches stay as they are (the office's area switch on in the organisation's view), below
//    them one group per workspace; the admins' choice is disabled there; a switch saves ws_areas_off and the app follows
//  - an old link to the office in the organisation's view: a hint with a button to Private, which opens it there
//  - Settings > Organisation: the areas of the organisation, for a member read-only
// freelancer-matrix: settings (the per-workspace group needs organisations; alone, Private = the main switches, p2409_a_api)
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
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEATS = 'cal,collab,comments,contacts,files,clients,office,wiki,sheets,time,reading';

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const me = await call('GET', '/api/state');
  const org = await call('POST', '/api/admin/orgs', {name: 'Nordwind', admin_id: me.me.id});
  check(org.id, 'an organisation');
  check((await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [org.id]})).id, 'bob, a member');
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATS, workspace: `org:${org.id}`, ws_areas_off: JSON.stringify({private: ['wiki']})}, CB);
  check((await call('PATCH', `/api/orgs/${org.id}`, {areas_off: ['office']})).status === 200, 'the admin switches the office off for the members');

  const w = await boot({user: 'bob'}), d = w.document, ev = s => w.eval(s);
  const WS = `org:${org.id}`;
  check(ev('wsCur()') === WS, '(setup) bob sees the organisation');
  check(ev('officeOn()') === false && ev(`mg_on('office')`) === false, 'organisation: the office is off');
  check(ev(`feat('wiki')`) === true, 'organisation: his knowledge pages are on there');
  check(!d.querySelector('[data-sbb="office"], [data-mgside="office"]'), 'organisation: no office in the bar / sidebar');
  check(ev(`feat('contacts')`) === false && ev(`feat('clients')`) === false, 'organisation: the whole area (contacts, clients) is off');
  check(ev(`wsa_raw(() => officeOn())`) === true, 'the main switch stays on');

  // ================= an old link to the office in the organisation's view
  ev(`go('office')`);
  const tst = await until(() => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && t.textContent.includes('You find it in the workspace') && t; });
  check(tst && tst.textContent.includes('Private'), 'the hint names Private ' + (tst?.textContent || ''));
  check(ev('S.route.mod') !== 'office', 'the office does not open in the organisation');
  tst?.querySelector('button')?.click();
  check(await until(() => ev('wsCur()') === 'private' && ev('S.route.mod') === 'office'), 'the button switches to Private and opens the office ' + ev('wsCur()') + ' ' + ev('S.route.mod'));
  check(ev('officeOn()') === true && ev(`feat('wiki')`) === false, 'Private: office on, knowledge pages off (his own choice)');
  check(await until(async () => (await call('GET', '/api/state', null, CB)).settings.workspace === 'private'), 'the server knows the workspace Private');

  await w.eval(`wsSet('all')`);
  check(ev('officeOn()') === true && ev(`feat('wiki')`) === true, 'All workspaces: both shown (each on in one workspace)');
  await w.eval(`wsSet('${WS}')`);

  // ================= Settings > Modules
  ev(`settingsModal('modules')`);
  await until(() => d.querySelector('.smodal [data-wsagrp]'));
  const grp = ws => d.querySelector(`.smodal [data-wsagrp="${ws}"]`);
  check(grp('private') && grp(WS), 'one group per workspace');
  check(d.querySelector('.smodal input[data-mgarea="office"]')?.checked === true, 'the main switch of the office shows on (the organisation is shown)');
  const oo = grp(WS)?.querySelector('input[data-wsa="office"]');
  check(oo && oo.disabled && !oo.checked && grp(WS).textContent.includes('Switched off by the admins of Nordwind'), 'the admins\' choice: disabled, says who');
  check(!grp(WS)?.querySelector('input[data-wsa="review"]'), 'no review in the organisation (private only)');
  const pw = grp('private')?.querySelector('input[data-wsa="wiki"]');
  check(pw && !pw.checked && !pw.disabled, 'Private: the knowledge pages off, his own switch');
  const ot = grp(WS)?.querySelector('input[data-wsa="time"]');
  check(ot && ot.checked, 'organisation: time on');
  ot.checked = false; ot.dispatchEvent(new w.Event('change', {bubbles: true}));
  const st = await until(async () => { const s = JSON.parse((await call('GET', '/api/state', null, CB)).settings.ws_areas_off || '{}'); return (s[WS] || []).includes('time') && s; });
  check(st && JSON.stringify(st.private) === '["wiki"]', 'the switch saves ws_areas_off (the other workspace kept) ' + JSON.stringify(st));
  check(await until(() => ev(`feat('time')`) === false), 'the app follows: time off in the organisation');
  check(d.querySelector('.smodal input[data-feat="time"]')?.checked !== false, 'the main switch of time stays on');
  d.querySelector('.smodal')?.remove();

  // ================= Settings > Organisation: the areas of the organisation, read-only for a member
  ev(`settingsModal('org')`);
  const box = await until(() => d.querySelector('.smodal .wsa-org'));
  check(box, 'the section "Areas in this organisation"');
  const ob = box?.querySelector('input[data-wsaorg="office"]');
  check(ob && !ob.checked && ob.disabled, 'office off, a member cannot change it');
  check(box?.querySelector('input[data-wsaorg="wiki"]')?.checked === true && !box.querySelector('input[data-wsaorg="review"]'), 'the others on, no review');

  console.log(`p2409_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
