// 2.51.0 UI tests, part B (#1351 an inquiry becomes a project, #1358 the setup assistant), own container (start.sh),
// Firefox (desktop + phone width). Invented companies and people only.
// - #1351: the agent's own inquiry proposal opens from its link (#prop/<id>): the project name, the parts as groups (tasks,
//   shoot days, quotation draft), the quotation "not possible" without office rights (its checkboxes disabled, not counted);
//   Apply creates the project + event drafts (tentative) and opens the project; one undo step
// - #1358: on a phone the setup proposal (modules, lists, a first project) fits the width, large tap targets; Apply switches
//   the modules; Settings > Modules has "Set up with your agent", which opens the chat with the prepared text
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p251_b_ui', check, shots: 'P251B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.PK2_SMOKE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const agent = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents,habits'});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['write'], username: 'planner', display_name: 'Planner'});
  check(ag.http === 201 || ag.http === 200, 'agent ' + ag.http);
  const W = await call(CA, 'POST', '/api/lists', {name: 'Work'});
  await call(CA, 'PUT', `/api/lists/${W.id}/members`, {user_id: ag.id, role: 'edit'});
  const inq = await agent(ag.token, 'POST', '/agent/proposals', {kind: 'inquiry', user_id: me.id, title: 'Image film', proposal: {
    summary: 'An image film for Example Ltd', name: 'Image film Example', sections: ['Prep', 'Shoot'], client: {name: 'Example Ltd'},
    tasks: [{title: 'Call back the client', section: 'Prep'}, {title: 'Location scout', section: 'Prep', subtasks: [{title: 'Ask for the permit'}]}],
    shoot_days: [{title: 'Shoot day 1', date: '2027-05-10', location: 'Studio'}, {title: 'Shoot day 2', date: '2027-05-11', start_time: '08:00', end_time: '18:00'}],
    offer: {title: 'Image film', items: [{text: 'Camera day', qty: 2, unit: 'day', price: 900}]}}});
  check(inq.http === 201, 'inquiry proposal ' + inq.http + ' ' + JSON.stringify(inq).slice(0, 200));
  const set = await agent(ag.token, 'POST', '/agent/proposals', {kind: 'setup', user_id: me.id, proposal: {
    modules: [{key: 'time', on: true}, {key: 'habits', on: false}], lists: [{name: 'Leads', sections: ['New', 'Contacted']}],
    project: {type: 'agency', name: 'First client project'}}});
  check(set.http === 201, 'setup proposal ' + set.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const fits = `(() => { const c = document.querySelector('.ppm .card'); const W = document.documentElement.clientWidth; return !!c && [...c.querySelectorAll('*')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= #1351
    await nav(B + '#prop/' + inq.id);
    check(await ready(ev, `!!document.querySelector('.ppm .ppl .ppi')`, 80), '#1351: the proposal opens from its link');
    check(await ev(`document.querySelector('#pp-name')?.value === 'Image film Example' && !!document.querySelector('#pp-share')`), '#1351: project name + share box');
    check(await ev(`document.querySelectorAll('.ppm .pk2h').length === 3`), '#1351: three groups (tasks, shoot days, quotation) ' + await ev(`[...document.querySelectorAll('.ppm .pk2h')].map(x => x.textContent).join('|')`));
    check(await ev(`/New client: Example Ltd/.test(document.querySelector('.ppm .pk2info')?.textContent || '')`), '#1351: the client name as a suggestion');
    check(await ev(`!!document.querySelector('.ppm .pk2no') && [...document.querySelectorAll('.ppm .ppi[data-k^="400"] .ppc')].every(c => c.disabled && !c.checked)`),
      '#1351: the quotation is not possible without office rights');
    check(await ev(`/Apply 5 entries/.test(document.querySelector('[data-pp="apply"]').textContent)`), '#1351: 5 entries selected (2 tasks, 1 subtask, 2 shoot days) ' + await ev(`document.querySelector('[data-pp="apply"]').textContent`));
    check(await ev(`document.querySelector('.ppi[data-k="300"] input[data-f="title"]')?.value === 'Shoot day 1'`), '#1351: a shoot day can be renamed');
    await shot('p251-b-inquiry.png');
    await ev(`(() => { const c = document.querySelector('.ppi[data-k="1"] .ppc'); c.click(); return 1; })()`);
    check(await ev(`document.querySelector('.ppi[data-k="1.0"]').classList.contains('off') && /Apply 3 entries/.test(document.querySelector('[data-pp="apply"]').textContent)`), '#1351: a task takes its subtask along');
    await ev(`(() => { document.querySelector('[data-pp="apply"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.ppm') && /^#l\\//.test(location.hash)`, 60), '#1351: applied, the project opens ' + await ev('location.hash'));
    const evs = await call(CA, 'GET', '/api/events?from=2027-05-01&to=2027-05-31');
    const list = evs.items || [];
    check(list.filter(e => e.status === 'tentative').length === 2, '#1351: two event drafts ' + JSON.stringify(evs).slice(0, 200));
    check(await ready(ev, `!document.querySelector('#toast').classList.contains('hidden') && /1 task created, 2 event drafts/.test(document.querySelector('#toast').textContent) && !!document.querySelector('#toast button')`, 20),
      '#1351: the toast names what was created and offers undo ' + await ev(`document.querySelector('#toast')?.textContent`));

    // ================= #1358 on a phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await nav(B + '#prop/' + set.id);
    check(await ready(ev, `!!document.querySelector('.ppm .ppl .ppi')`, 80), '#1358: the setup proposal opens');
    check(await ev(`/Switch on: Time tracking/.test(document.querySelector('.ppm .ppl').textContent) && /Switch off: Habits/.test(document.querySelector('.ppm .ppl').textContent)`), '#1358: module lines');
    check(await ev(`document.querySelector('.ppi[data-k="100"] input[data-f="title"]')?.value === 'Leads' && !!document.querySelector('.ppi[data-k="200"]')`), '#1358: the list and the first project');
    check(await ev(fits), '#1358: nothing sticks out on a phone');
    check(await ev(`[...document.querySelectorAll('.ppm .pk2p')].every(x => x.getBoundingClientRect().height >= 40)`), '#1358: module lines are large tap targets');
    await shot('p251-b-setup-phone.png');
    await ev(`(() => { document.querySelector('[data-pp="apply"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.ppm')`, 60), '#1358: applied');
    const st = await call(CA, 'GET', '/api/state');
    const fs = (st.settings.features || '').split(',');
    check(fs.includes('time') && !fs.includes('habits'), '#1358: modules switched ' + st.settings.features);
    // Settings > Modules: "Set up with your agent" opens the chat with the prepared text
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await nav(B + '#today');
    await ready(ev, `typeof settingsModal === 'function' && !!document.querySelector('#main, .main, main')`, 60);
    await ev(`(() => { settingsModal('layout'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.smodal [data-pk2="setup"]')`, 40), '#1358: Settings > Modules offers "Set up with your agent"');
    await ev(`(() => { document.querySelector('.smodal [data-pk2="setup"]').click(); return 1; })()`);
    check(await ready(ev, `/^I use Kalmido for/.test(document.querySelector('#chat-in')?.value || '')`, 60), '#1358: the chat opens with the prepared text');
    await shot('p251-b-setup-chat.png');
  }, false);

  console.log(`p251_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
