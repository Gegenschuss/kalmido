// kalmido-suite: fresh
// 2.407.0 B (#3493) UI tests, own container (start.sh). jsdom:
// - the usage ring is always shown, also in the green (q-ok, accent); the CSS no longer hides it
// - "Show usage" (⋯ menu and chat settings, per person, agent_quota_show): off = no ring, the ⋯ menu keeps the usage with
//   its windows; on again through the chat settings checkbox
// - an API-key agent with a cost limit: the ring shows its costs against the limit (40 % accent, 80 % yellow), the list
//   "Costs this month: $4.00 of $10.00"; without a limit no ring, the ⋯ menu reads "Costs this month: $x" (today below)
// - the ⋯ menu names the kind of agent instead of "Workspace: X": team agent / your personal agent / personal agent of
//   <name> (each with the organisation), private agent
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2407B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [ORG]})).id;
  const L = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const agent = async name => {
    const a = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write'], username: name, display_name: name});
    await call('PATCH', `/api/admin/agents/${a.id}`, {org_id: ORG});
    await call('PUT', `/api/lists/${L}/members`, {user_id: a.id, role: 'edit'});
    return a;
  };
  const plan = await agent('planbot'), api = await agent('apibot');
  await v1(plan.token, 'PUT', '/agent/quota', {windows: [{label: 'Week', percent: 41}]});
  await call('PATCH', `/api/admin/agents/${api.id}`, {limits: {period: 'month', metric: 'cost', hard: 10}});
  await v1(api.token, 'POST', '/agent/usage', {model: 'm', input_tokens: 10, output_tokens: 5, cost_usd: 4});

  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const open = async aid => { w.eval(`chatOpen(${aid})`); return until(() => w.eval(`S.chat.aid === ${aid} && !!document.querySelector('.chath .chnm b')`)); };
  const reload = async aid => { await w.eval('load().then(render)'); w.eval(`chatOpen(${aid})`); await w.eval('chatLoad()'); await sleep(200); };
  const ring = () => d.querySelector('.chnm .chring');
  const tip = () => d.getElementById('chat-ring')?.textContent || '';
  const menu = () => w.eval(`chatHeadInfo(document.querySelector('#jcd-fbtn') || document.body).filter(x => x && x.label).map(x => ({label: x.label, more: (x.more || []).map(m => m.label), cls: x.cls || ''}))`);

  // ================= the ring always, also in the green
  check(await open(plan.id), 'setup: the chat with the plan agent is open');
  check(ring()?.classList.contains('q-ok') && ring().getAttribute('aria-label') === 'Usage: 41 %', '#3493: the ring is there at 41 % (accent, q-ok) ' + (ring()?.outerHTML || '').slice(0, 120));
  const css = require('./boot').allCssSync();
  check(!/\.chring:is\(\.q-ok/.test(css) && !/\.chring\.q-ok\{display:none/.test(css), '#3493: the CSS no longer hides the ring in the green');
  let m = menu();
  check(m.some(x => x.label === 'Team agent · Alpha' && x.cls === 'chmi-kind') && !m.some(x => /^Workspace: /.test(x.label)), '#3493: ⋯ names the kind of agent instead of the workspace ' + JSON.stringify(m.map(x => x.label)));
  check(m.some(x => x.label === 'Usage: 41 %' && x.more.some(l => /^Week: 41 %/.test(l))), '#3493: ⋯ keeps the usage with its windows ' + JSON.stringify(m));

  // ================= the switch: off in the ⋯ menu entry, on again in the chat settings
  check(w.eval(`quotaShowOn()`) && w.eval(`!!document.querySelector('.chath') && typeof quotaShow`) === 'function', 'setup: "Show usage" is on');
  w.eval(`quotaShow(false)`);
  check(await until(() => !ring() && !d.getElementById('chat-ring')), '#3493: switched off: no ring');
  m = menu();
  check(m.some(x => x.label === 'Usage: 41 %' && x.more.some(l => /^Week: 41 %/.test(l))), '#3493: ... the ⋯ menu still reads the usage ' + JSON.stringify(m.map(x => x.label)));
  check(await until(async () => (await call('GET', '/api/state')).settings.agent_quota_show === '0'), '#3493: ... saved for the person');
  w.eval(`acset_open()`);
  const cb = await until(() => d.getElementById('acset-qshow'));
  check(cb && !cb.checked && /all your chats/.test(cb.closest('fieldset')?.textContent || ''), '#3493: the chat settings show the switch off, with its explanation');
  if (cb) { cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(() => ring()?.classList.contains('q-ok')), '#3493: switched on in the chat settings: the ring is back');
  check(await until(async () => (await call('GET', '/api/state')).settings.agent_quota_show === '1'), '#3493: ... saved');
  d.querySelector('.acsetmd [data-m="close"]')?.click();

  // ================= an API-key agent: costs against its cost limit
  check(await open(api.id), 'setup: the chat with the API agent is open');
  check(ring()?.classList.contains('q-ok') && ring().getAttribute('aria-label') === 'Usage: 40 %', '#3493: the cost ring at 40 % ' + (ring()?.outerHTML || '').slice(0, 120));
  check(/Costs this month: \$4\.00 of \$10\.00/.test(tip()) && /Costs today: \$4\.00/.test(tip()), '#3493: the list names the costs against the limit ' + JSON.stringify(tip()));
  await v1(api.token, 'POST', '/agent/usage', {model: 'm', input_tokens: 10, output_tokens: 5, cost_usd: 4});
  await reload(api.id);
  check(await until(() => ring()?.classList.contains('q-warn')), '#3493: from 75 % yellow (80 %) ' + (ring()?.outerHTML || '').slice(0, 120));
  await call('PATCH', `/api/admin/agents/${api.id}`, {limits: null});
  await reload(api.id);
  check(await until(() => !ring()), '#3493: without a cost limit no ring');
  m = menu();
  check(m.some(x => x.label === 'Costs this month: $8.00' && x.cls === 'chmi-use' && x.more.includes('Costs today: $8.00')), '#3493: ... the ⋯ menu reads the costs ' + JSON.stringify(m));

  // ================= the kind of agent
  check(w.eval(`chatKindLbl({org_id: ${ORG}, owner_id: S.me.id})`) === 'Your personal agent · Alpha', '#3493: my personal agent');
  check(w.eval(`chatKindLbl({org_id: ${ORG}, owner_id: ${BOB}})`) === 'Personal agent of Bob · Alpha', '#3493: the personal agent of someone else, with the name ' + w.eval(`chatKindLbl({org_id: ${ORG}, owner_id: ${BOB}})`));
  check(w.eval(`chatKindLbl({org_id: null, owner_id: S.me.id})`) === 'Private agent' && w.eval(`chatKindLbl({org_id: null, owner_id: null})`) === 'Private agent', '#3493: an agent in the private area');
  check(w.eval(`chatKindLbl({org_id: ${ORG}, owner_id: null})`) === 'Team agent · Alpha', '#3493: a team agent');
  w.eval(`(() => { const o = S.me.workspaces; S.me.workspaces = []; window._k = chatHeadInfo(document.body).some(x => x.cls === 'chmi-kind'); S.me.workspaces = o; })()`);
  check(w.eval('window._k'), '#3493: the kind stands there also without the workspace switcher (not tied to wsOn)');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
