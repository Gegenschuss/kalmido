// 2.30.0 UI tests: agents stay inside one circle of people (#919), "Use safely" (#920). Own container (start.sh). jsdom:
// Settings > Agents > Use safely (ten rules + the admins' part, reached with settingsModal('agentsafe')), the setup guides
// carry the short safety step; the first share with an agent on this device shows the hint first; a share that connects
// lists with different people asks "Connect lists with different people?" (Cancel = not shared, Connect anyway = shared);
// the agent's dialog limits it to selected lists and names the bridge; the token dialog has the list limit; the list menu's
// "Agent access" shows what the agent read / changed.
// Firefox (1440 light / dark, 390 touch): screenshots of Use safely, the agent dialog with its bridge, the access log; the
// sub-tabs of Settings > Agents still fit, nothing overflows on the phone.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2300_agentsafe_ui', check, shots: 'P2300_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,family,team';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol Cole', password: 'password123'})).id;
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const AB = (await call('POST', '/api/lists', {name: 'Team Bob', org_id: ORG})).id;
  await call('PUT', `/api/lists/${AB}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${AB}/members`, {user_id: AG, role: 'edit'});
  const AC = (await call('POST', '/api/lists', {name: 'Team Carol', org_id: ORG})).id;
  await call('PUT', `/api/lists/${AC}/members`, {user_id: CAROL, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Read me', list_id: AB})).id;
  await fetch(V + `/tasks/${T1}`, {headers: AGH});
  await fetch(V + `/tasks/${T1}/comments`, {method: 'POST', headers: AGH, body: JSON.stringify({body: 'seen'})});

  // ================= Use safely
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('agentsafe')`);
  await until(() => d.querySelector('.modal #aisp-safe:not([hidden]) .agsafe-rules'));
  let md = d.querySelector('.modal');
  const pane = md.querySelector('#aisp-safe');
  check(pane && !pane.hidden && md.querySelector('[data-aisub="safe"]')?.getAttribute('aria-selected') === 'true', '#920: settingsModal(\'agentsafe\') opens Settings > Agents > Use safely');
  check(pane?.querySelectorAll('.agsafe-rules > li').length === 10 && pane.querySelectorAll('.agsafe-admin li').length === 3, '#920: ten rules and the admins\' part ' + pane?.querySelectorAll('.agsafe-rules > li').length);
  check(/One agent per context/.test(pane?.textContent) && /The same people/.test(pane.textContent) && /Agent access/.test(pane.textContent), '#920: the rules name one agent per context, the same people, the access log');
  check(!/[\u{1F300}-\u{1FAFF}\u{1F44D}]/u.test(pane?.textContent || ''), '#920: no emojis in the rules');
  check(/AGENT-SECURITY\.md/.test(pane?.querySelector('a')?.getAttribute('href') || ''), '#920: the link to the details');
  click(w, md.querySelector('[data-aisub="setup"]')); await sleep(300);
  check(/Use it safely/.test(md.querySelector('#aisp-setup')?.textContent || ''), '#920: the setup guide has the short safety step');
  md.remove();
  check(/Use it safely/.test(w.eval(`agSetupHtml('own', 'mac')`)) && /Use it safely/.test(w.eval(`agSetupHtml('team', 'win')`)), '#920: ... in every guide');

  // ================= first share: the hint, then the bridge question
  w.__dialogs = 'manual';  // this suite answers the dialogs itself
  w.eval(`LS.set('agSafeSeen', false)`);
  let p = w.eval(`window.__r = setListAgent(${AC}, ${AG}, [{id: ${AG}, name: 'Claude'}])`);
  await until(() => d.querySelector('.cdlg'));
  let dl = d.querySelector('.cdlg');
  check(/Before you share a list with an agent/.test(dl?.textContent) && /One agent per context/.test(dl.textContent) && /Use safely/.test(dl.textContent), '#920: the first share shows the hint first ' + dl?.textContent.slice(0, 120));
  click(w, dl.querySelector('[data-cd="yes"]'));
  await until(() => [...d.querySelectorAll('.cdlg')].some(x => /different people/.test(x.textContent)));
  dl = [...d.querySelectorAll('.cdlg')].find(x => /different people/.test(x.textContent));
  check(dl && /Connect lists with different people\?/.test(dl.textContent) && /Team Bob/.test(dl.textContent) && /Connect anyway/.test(dl.textContent), '#919: a bridge asks with the other list named ' + dl?.textContent.slice(0, 200));
  click(w, dl.querySelector('[data-cd="no"]'));
  await until(async () => (await w.__r) === false);
  let mem = (await call('GET', '/api/state')).lists.find(l => l.id === AC).members || [];
  check(!mem.some(m => m.user_id === AG), '#919: Cancel = the agent stays out');
  check(w.eval(`LS.get('agSafeSeen', false)`) === true, '#920: the hint comes once per device');
  w.eval(`window.__r = setListAgent(${AC}, ${AG}, [{id: ${AG}, name: 'Claude'}])`);
  await until(() => [...d.querySelectorAll('.cdlg')].some(x => /different people/.test(x.textContent)));
  check(![...d.querySelectorAll('.cdlg')].some(x => /Before you share/.test(x.textContent)), '#920: ... the second share asks only about the bridge');
  dl = [...d.querySelectorAll('.cdlg')].find(x => /different people/.test(x.textContent));
  click(w, dl.querySelector('[data-cd="yes"]'));
  await until(async () => (await w.__r) === true);
  mem = (await call('GET', '/api/state')).lists.find(l => l.id === AC).members || [];
  check(mem.some(m => m.user_id === AG), '#919: Connect anyway = shared (bridge_ok)');

  // ================= the agent's dialog: list limit + the bridge
  w.eval(`api('GET', '/api/admin/agents').then(j => { S.agOffer = j.scopes; agModal(j.agents.find(x => x.id === ${AG}), () => {}); })`);
  await until(() => d.querySelector('.modal #ag-lcap'));
  md = d.querySelector('.modal');
  const caps = [...md.querySelectorAll('#ag-lcap [data-lcap]')].map(x => x.nextElementSibling.textContent);
  check(caps.includes('Team Bob') && caps.includes('Team Carol') && !md.querySelector('#ag-lcap [data-lcap]:checked'), '#919: the agent dialog lists its lists, none ticked = all ' + caps.join('|'));
  check(/Connects lists with different people/.test(md.querySelector('.agbridges')?.textContent || '') && /approved by Alice/.test(md.querySelector('.agbridges').textContent), '#919: ... and names the approved bridge');
  md.querySelector(`#ag-lcap [data-lcap="${AB}"]`).checked = true;
  click(w, md.querySelector('[data-m="ok"]'));
  await until(async () => (await call('GET', '/api/admin/agents')).agents.find(a => a.id === AG).list_ids?.length === 1);
  check((await call('GET', '/api/admin/agents')).agents.find(a => a.id === AG).list_ids[0] === AB, '#919: Save limits it to the ticked list');
  await call('PATCH', `/api/admin/agents/${AG}`, {list_ids: []});
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // ================= token dialog + list menu "Agent access"
  w.eval(`tokModal(() => {}, [])`);
  await until(() => d.querySelector('.modal #tk-lcap'));
  check([...d.querySelectorAll('.modal #tk-lcap [data-lcap]')].length >= 2, '#919: the token dialog offers the list limit');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  const items = w.eval(`listMenuItems(${AB}).flatMap(x => x.more || [x]).filter(x => x && x.label).map(x => x.label)`);
  check(items.includes('Agent access'), '#919: the list menu has "Agent access" ' + items.join('|'));
  w.eval(`agAccessModal(${AB})`);
  await until(() => d.querySelector('.agaccmd .agacc'));
  const row = d.querySelector('.agaccmd .agacc');
  check(/Claude/.test(row?.textContent) && /read 1 times|read \d+ times/.test(row.textContent) && /changed [1-9]/.test(row.textContent), '#919: the access log shows the agent ' + row?.textContent);
  w.close();
  // Bob (a member) sees it too
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  w.eval(`agAccessModal(${AB})`);
  await until(() => d.querySelector('.agaccmd'));
  check(/Claude/.test(d.querySelector('.agaccmd')?.textContent || ''), '#919: a member sees the access log');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { settingsModal('agentsafe'); return 1; })()`); await sleep(1000);
    check(await ev(`(() => { const s = document.querySelector('.modal .aisub'); return !!s && s.scrollWidth <= s.clientWidth + 2; })()`), `${tag}: the seven sub-tabs of Settings > Agents fit`);
    check(await ev(`(() => { const p = document.querySelector('#aisp-safe'); return !!p && !p.hidden && p.scrollWidth <= p.clientWidth + 1; })()`), `${tag}: Use safely fits`);
    await shot(`p2300-${th}-1440-use-safely.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); api('GET', '/api/admin/agents').then(j => { S.agOffer = j.scopes; agModal(j.agents.find(x => x.id === ${AG}), () => {}); const m = document.querySelector('.modal'); }); return 1; })()`); await sleep(1200);
    await ev(`(() => { const b = document.querySelector('.modal .agbridges'); b && b.scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
    await shot(`p2300-${th}-1440-agent-bridge.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); agAccessModal(${AB}); return 1; })()`); await sleep(900);
    await shot(`p2300-${th}-1440-agent-access.png`);
  });
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { settingsModal('agentsafe'); return 1; })()`); await sleep(1000);
    check(await ev(`document.documentElement.scrollWidth <= 390 && !!document.querySelector('#aisp-safe:not([hidden])')`), `${tag}: Use safely fits the phone`);
    await shot('p2300-light-390-use-safely.png');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); agAccessModal(${AB}); return 1; })()`); await sleep(900);
    check(await ev(`document.documentElement.scrollWidth <= 390`), `${tag}: the access log fits the phone`);
    await shot('p2300-light-390-agent-access.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
