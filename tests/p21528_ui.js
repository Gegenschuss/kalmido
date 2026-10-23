// 2.152.8 (#2711) UI tests: Back in a job's history of the agent chat on a touch device. Own container (start.sh), Firefox.
// freelancer-matrix: agents (alice runs the instance without an organisation, her agent and its job are private)
// - phone (390 px, touch), chat page: a job's history has its own Back step - Back leads to the whole agent chat (not out of
//   the chat), the next Back leaves the chat as before; the bar's back button takes the step away again (one Back leaves);
//   a job opened from another page (agent menu) - Back = whole chat, then the page before
// - tablet (1280 px, touch), chat panel: Back in a job's history = whole chat, the panel stays open
// - computer (1280 px, mouse): unchanged, no history entry for a job's history
// P21528_NOSTART=1 = the server already runs. Screenshots: P21528_SHOTS (kalmido-mactest.sh shot p21528_ui).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21528_ui', check, shots: 'P21528_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21528_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me;
  check(!(me.workspaces || []).length, 'P4: alice has no organisation');
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const CL = ag.id; TOK = ag.token;
  check(CL > 0 && !!TOK, 'a private agent');
  const L = (await call('POST', '/api/lists', {name: 'Errands'})).id;
  check((await call('PUT', `/api/lists/${L}/members`, {user_id: CL, role: 'edit'})).http < 300, 'her private project is shared with the agent');
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Please build the release'});
  const J = (await v1('POST', '/agent/jobs', {title: 'Clara: Release 1.0', user_id: me.id, state: 'running'})).id;
  check(J > 0, 'a running job');
  await v1('POST', `/agent/chats/${me.id}`, {body: `Job #${J} started`, job_id: J});
  await v1('POST', `/agent/chats/${me.id}`, {body: 'Hello, how can I help?'});
  await v1('POST', `/agent/chats/${me.id}`, {body: 'Clara: halfway there', job_id: J});

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  const start = async (ev, nav, w) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev) === 200, `${w}: alice signs in`);
    await nav(B + '#l/' + L);
    return ready(ev, `S.booted && location.hash === '#l/${L}'`);
  };
  const inJob = `!!S.chat.job && +S.chat.job.id === ${J} && !!document.getElementById('jc-bar')`;
  const whole = `+S.chat.aid === ${CL} && !S.chat.job && !document.getElementById('jc-bar')`;
  const back = ev => ev('(history.back(), 1)');

  // ================= phone: 390 px, touch, the chat page
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await start(ev, nav, '390 px'), '390 px: the project page');
    await ev(`(chatOpen(${CL}), 1)`);
    check(await ready(ev, `location.hash === '#agents/${CL}' && !!document.querySelector('#view .chview [data-act="jc-open"][data-jid="${J}"]')`), '390 px: the chat page with the job link');
    await ev(`(document.querySelector('#view .chview [data-act="jc-open"][data-jid="${J}"]').click(), 1)`);
    check(await ready(ev, inJob, 30), '390 px: the job\'s history opens');
    check(await ev('history.state?.jc === 1'), '390 px: the job\'s history has its own history entry');
    await shot('phone-job');
    await back(ev);
    check(await ready(ev, `${whole} && location.hash === '#agents/${CL}' && !!document.querySelector('#view .chview')`, 20), '390 px: Back leads to the whole agent chat, not out of the chat');
    await sleep(300);
    check(await ev(whole), '390 px: and stays there');
    await back(ev);
    check(await ready(ev, `location.hash === '#l/${L}'`, 20), '390 px: the next Back leaves the chat as before');

    // the bar's back button: the step is taken away again, one Back leaves the chat
    await ev(`(chatOpen(${CL}), 1)`);
    check(await ready(ev, `!!document.querySelector('#view .chview [data-act="jc-open"][data-jid="${J}"]')`), '390 px: the chat page again');
    await ev(`(document.querySelector('#view .chview [data-act="jc-open"][data-jid="${J}"]').click(), 1)`);
    check(await ready(ev, inJob, 30), '390 px: the job\'s history again');
    await ev(`(document.querySelector('#jc-bar [data-act="jc-back"]').click(), 1)`);
    check(await ready(ev, whole, 20), '390 px: the bar\'s back button leads to the whole chat');
    await sleep(600);
    check(await ev(`!history.state?.jc && location.hash === '#agents/${CL}'`), '390 px: the job\'s entry is gone');
    await back(ev);
    check(await ready(ev, `location.hash === '#l/${L}'`, 20), '390 px: then one Back leaves the chat');

    // a job opened from another page (the agent menu of the top bar): Back = the whole chat, then the page before
    await ev(`jc_sync(true).then(() => 1)`);
    await ev(`(jc_enter(${CL}, S.jc.jobs[${J}] || {id: ${J}}), 1)`);
    check(await ready(ev, `${inJob} && location.hash === '#agents/${CL}'`, 30), '390 px: the job\'s history from another page');
    await back(ev);
    check(await ready(ev, `${whole} && location.hash === '#agents/${CL}'`, 20), '390 px: Back leads to the whole chat');
    await back(ev);
    check(await ready(ev, `location.hash === '#l/${L}'`, 20), '390 px: the next Back to the page before');
  }, true);

  // ================= tablet: 1280 px, touch, the chat panel
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    check(await start(ev, nav, '1280 px touch'), '1280 px touch: the project page');
    if (!await ev('isTouch() && !chatFull()')) { console.log('p21528_ui: no touch panel in this Firefox, tablet part skipped'); return; }
    await ev(`(chatOpen(${CL}), 1)`);
    check(await ready(ev, `!document.getElementById('achat').classList.contains('hidden') && !!document.querySelector('#achat [data-act="jc-open"][data-jid="${J}"]')`), '1280 px touch: the chat panel with the job link');
    await ev(`(document.querySelector('#achat [data-act="jc-open"][data-jid="${J}"]').click(), 1)`);
    check(await ready(ev, inJob, 30), '1280 px touch: the job\'s history in the panel');
    await shot('tablet-job');
    await back(ev);
    check(await ready(ev, `${whole} && !document.getElementById('achat').classList.contains('hidden') && location.hash === '#l/${L}'`, 20), '1280 px touch: Back leads to the whole chat, the panel stays open');
  }, true);

  // ================= computer: 1280 px, mouse - unchanged
  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    check(await start(ev, nav, '1280 px'), '1280 px: the project page');
    await ev(`(chatOpen(${CL}), 1)`);
    check(await ready(ev, `!!document.querySelector('[data-act="jc-open"][data-jid="${J}"]')`), '1280 px: the chat with the job link');
    const n = await ev('history.length');
    await ev(`(document.querySelector('[data-act="jc-open"][data-jid="${J}"]').click(), 1)`);
    check(await ready(ev, inJob, 30), '1280 px: the job\'s history');
    check(await ev(`history.length === ${n} && !history.state?.jc`), '1280 px: no history entry with a mouse (unchanged)');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
