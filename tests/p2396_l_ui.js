// 2.396.0 (#3385) UI tests: the row "Used for" is gone from the project dialog (List | Project went with 2.352.0 #2752). Own container
// (start.sh), jsdom, a person WITHOUT an organisation (as tests/freelancer_fixture.py; freelancer-matrix: tasks).
// kalmido-suite: fresh
// - new and existing dialog: no #l-fam (and no kind switch since 2.352.0)
// - a private list named like a shopping list offers "Use as a shopping list?" once; the button sets family shopping +
//   ticked at the bottom (one undo step); a tracked project (with a status), a list of an organisation and a list that already is one get no offer
// - a shopping list moved into an organisation from the dialog ends its list kind (as the row "Used for" did), no 409
// - the organisation hint names shopping lists instead of "Used for"
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2396L_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const listOf = async id => ((await call('GET', '/api/state')).lists || []).find(l => l.id === id) || {};
const FAM = 'cal,comments,collab,family';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, AK);
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK)).id;
  await call('PATCH', '/api/settings', {features: FAM, lang: 'en', tour: 'done'}, AK);
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {features: FAM, lang: 'en', tour: 'done'});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  const P = (await call('POST', '/api/lists', {name: 'Shopping centre launch'})).id;
  check((await call('POST', `/api/lists/${P}/status`, {status: 'on_track'})).http < 300, 'a tracked project (status, 2.352.0 #2752)');
  const E = (await call('POST', '/api/lists', {name: 'Einkauf'})).id;

  // ================= the dialog: no "Used for" (2.352.0 #2752 took the kind switch away: no List | Project either)
  let w = await boot({user: 'frida', hash: 'today'}); let d = w.document;
  check(await until(() => w.eval(`feat('family') && !!listById(${E})`)), 'the family module is on');
  w.eval('listModal()'); let md = await until(() => d.querySelector('.modal.lnew'));
  check(!md.querySelector('#l-fam') && !md.querySelector('.lfamrow') && !/Used for|Progress and status/.test(md.textContent), 'new: no "Used for", no old switch text');
  check(!md.querySelector('#l-kindp') && !md.querySelector('.lkrow'), 'new: no kind switch (main 2.352.0, #2752)');
  md.remove();
  w.eval(`listModal(${E})`); md = await until(() => d.querySelector('.modal.lmodal'));
  check(!md.querySelector('#l-fam') && !md.querySelector('.lfamrow') && !/Used for/.test(md.textContent), 'existing list: no "Used for"');
  md.remove(); w.close();

  // ================= the shopping hint in the list
  w = await boot({user: 'frida', hash: 'l/' + E}); d = w.document;
  const btn = await until(() => d.querySelector('#view .onehint[data-hint="shop"] [data-act="shop-on"]'));
  check(btn && !d.querySelector('#view .onehint[data-hint="dab"]'), 'a list named Einkauf: the offer "Use as a shopping list?" (alone)');
  btn.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  const e1 = await until(async () => { const l = await listOf(E); return l.family === 'shopping' && l.checklist ? l : null; });
  check(e1, 'the button: family shopping + ticked at the bottom');
  check(await until(() => !d.querySelector('#view .onehint[data-hint="shop"]') && d.querySelector('#view [data-act="shop-start"]')), 'the offer is gone, shopping mode is there');
  w.eval("histStep('undo')");
  check(await until(async () => { const l = await listOf(E); return !l.family && !l.checklist; }), 'one undo step takes both back');
  check(await until(() => !w.eval(`listById(${E}).family`)) && !d.querySelector('#view .onehint[data-hint="shop"]'), 'used once = not offered again');
  w.close();
  w = await boot({user: 'frida', hash: 'l/' + P}); d = w.document;
  await until(() => w.eval('S.route.key') === 'l:' + P);
  check(!d.querySelector('#view .onehint[data-hint="shop"]'), 'a tracked project named like shopping: no offer');
  w.close();

  // ================= organisation: no offer; moving a shopping list into it ends the list kind
  CK = AK;
  const O = (await call('POST', '/api/lists', {name: 'Einkauf Büro', org_id: ORG})).id;
  const S = (await call('POST', '/api/lists', {name: 'Groceries', family: 'shopping'})).id;
  check(O && (await listOf(O)).org_id === ORG && (await listOf(S)).family === 'shopping', 'alice: an organisation list and a private shopping list');
  w = await boot({user: 'alice', hash: 'l/' + O}); d = w.document;
  await until(() => w.eval('S.route.key') === 'l:' + O && !!d.querySelector('#view'));
  check(!d.querySelector('#view .onehint[data-hint="shop"]'), 'a list of an organisation: no offer (shopping lists are private)');
  w.eval(`listModal(${S})`); md = await until(() => d.querySelector('.modal.lmodal'));
  check(!md.querySelector('#l-fam') && md.querySelector('#l-ws'), 'alice: the dialog has the workspace, no "Used for"');
  const ws = md.querySelector('#l-ws'); ws.value = String(ORG); ws.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(/Shopping lists and Home & life are private only/.test(md.querySelector('#l-wshint').textContent), 'the hint names shopping lists');
  // 2.401.0 (#2924): the dry run shows the move dialog first; it notes the end of the shopping list (no block), Move moves
  const dlg = await until(() => { const x = d.querySelector('.smv-dlg'); const b = x?.querySelector('[data-smv="yes"]'); return b && !b.disabled ? x : null; });
  check(dlg && /stops being a shopping list/.test(dlg.textContent), 'the move dialog notes the end of the shopping list, Move enabled');
  if (dlg) dlg.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  const s1 = await until(async () => { const l = await listOf(S); return l.org_id === ORG ? l : null; });
  check(s1 && !s1.family, 'moved into the organisation: no longer a shopping list (no 409)');
  md.remove(); w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
