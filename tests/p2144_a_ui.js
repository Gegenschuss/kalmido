// 2.144.0 UI tests of part A (#2416 #2419 #2412; own container, start.sh). jsdom, the agent chat at the computer with a job in it:
// - #2419: no filter row above the messages, the filter icon in the chat header (also wide), its menu, the dot while not "All"
// - #2416: "Only me and <agent>": my messages + the main agent's; a job's result WITH buttons is left out, an open approval of
//   the job stays; "Jobs": the card, the job's result with buttons and its approval, not the plain answer
// - #2412: while the agent works a Stop button next to Send (tooltip names the keys); a press / Esc sends the event abort
//   (the agent sees it), the button waits; the agent's confirmation hides it; Ctrl+C with a selection stays Copy; an open
//   menu keeps its Esc; in a job's history Stop carries the job_id
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2144A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const J = (await v1('POST', '/agent/jobs', {title: 'Knox: Release 2.144 filter', user_id: me.id, state: 'running'})).id;
  check(J, 'setup: a job');
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Please build the release'});
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  const plain = (await say('Hello, a plain answer')).id;
  const js = (await say('Knox: started the build', {job_id: J, job_msg: 'say'})).id;
  // #2416: a job's result with the suggestion buttons (what the service posts) and an open approval card of the job
  const jr = (await say('✅ Knox: release ready', {job_id: J, job_msg: 'result', choices: [{id: 's1', label: 'Make it live'}]})).id;
  const ja = (await v1('POST', `/agent/chats/${me.id}`, {body: 'Knox: may I push?', job_id: J, approval: {title: 'Push 2.144', what: 'The release goes to the public repo'}})).id;
  check(plain && js && jr && ja, 'setup: the messages');

  const w = await boot({user: 'alice', hash: `agents/${CL}`}), d = w.document;
  const fbtn = () => d.querySelector('#jcd-fbtn'), box = () => d.querySelector('#chat-msgs'), row = id => d.querySelector(`#chat-msgs [data-mid="a:${id}"]`);
  await until(() => fbtn() && !fbtn().hidden);
  // ================= #2419 the filter icon on every width
  check(fbtn() && !fbtn().hidden && d.querySelector('.chath').contains(fbtn()), 'wide: the filter icon sits in the chat header');
  check(!d.querySelector('#jcd-filt') && !d.querySelector('.jcdseg'), 'wide: no filter row above the messages');
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'agentchat.css'), 'utf8');
  check(/\.jcdfbtn\{[^}]*display:inline-flex/.test(css) && !/\.jcdfilt|\.jcdseg/.test(css), 'CSS: the icon shows on every width, the row rules are gone');
  const pick = async label => {
    click(w, fbtn()); await until(() => d.querySelector('[role=menuitem]'));
    const it = [...d.querySelectorAll('[role=menuitem]')];
    check(it.length === 3, 'the menu has three choices');
    click(w, it.find(x => label.test(x.textContent))); await sleep(300);
  };
  // ================= #2416 Only me and <agent>
  await pick(/Only me/);
  await until(() => !d.querySelector('.jcd'));
  check(w.eval(`LS.get('jcdFilt')`) === 'me' && fbtn().querySelector('.jcdfdot'), 'Only me: kept, the icon carries the dot');
  check(row(plain) && box().querySelector(':scope > .cmsg.me'), 'Only me: the plain answer and my message');
  check(!d.querySelector('.jcd') && !row(js), 'Only me: no job card, no job message');
  check(!row(jr), 'Only me: the job result WITH buttons is left out (#2416)');
  check(row(ja), 'Only me: the open approval of the job stays');
  // ================= Jobs
  await pick(/Jobs/);
  await until(() => d.querySelector('.jcd'));
  check(d.querySelector('.jcd') && row(jr) && row(ja), 'Jobs: the card, the result with buttons, the approval');
  check(!row(plain) && !box().querySelector(':scope > .cmsg.me'), 'Jobs: not the plain answer, not my message');
  // the rule as a function: a job row with buttons, an answered approval, a main-agent message with buttons
  check(w.eval(`jcd_pass({from: 'agent', choices: {choices: [{id: 1}]}}, 'me', 7)`) === false
        && w.eval(`jcd_pass({from: 'agent', choices: {choices: [{id: 1}]}}, 'me', 0)`) === true
        && w.eval(`jcd_pass({from: 'agent', choices: {choices: [{id: 1}]}}, 'jobs', 0)`) === false
        && w.eval(`jcd_pass({id: 1, from: 'agent', choices: {approval: {title: 'x'}}, choice: {ids: ['yes']}}, 'me', 7)`) === false, 'jcd_pass: the filter rules');
  await pick(/^\s*All/);
  await until(() => row(plain) && d.querySelector('.jcd'));
  check(row(plain) && d.querySelector('.jcd') && !fbtn().querySelector('.jcdfdot'), 'All: everything again, no dot');

  // ================= #2412 Stop
  const stopB = () => d.querySelector('#chat-stop'), ci = () => d.querySelector('#chat-in');
  check(stopB() && stopB().hidden, 'idle: the Stop button is hidden');
  const working = async () => { await v1('PUT', '/agent/status', {status: 'working', text: 'Answering in the chat'}); w.eval('agentPoll()'); await until(() => stopB() && !stopB().hidden, 40); };
  const aborts = async () => ((await v1('GET', '/agent/events?since=0')).data || []).filter(e => e.event === 'abort');
  await working();
  check(stopB() && !stopB().hidden && !stopB().disabled, 'working: the Stop button shows next to Send');
  check(stopB().closest('.chcomp') && /Esc/.test(stopB().title) && /Ctrl\+C/.test(stopB().title) && stopB().querySelector('svg, .i, i'), 'Stop: an icon, the tooltip names the keys');
  click(w, stopB());
  await until(async () => (await aborts()).length === 1);
  let ab = await aborts();
  check(ab.length === 1 && ab[0].data.user.id === me.id && !ab[0].data.job_id, 'the press sends abort to the agent');
  await until(() => stopB()?.disabled);
  check(stopB().disabled && /Stopping/.test(stopB().title), 'the button waits: Stopping…');
  await v1('POST', '/agent/aborted', {seq: ab[0].seq});
  w.eval('agentPoll()');
  await until(() => stopB()?.hidden);
  check(stopB().hidden, 'confirmed by the agent: the button goes');
  // Esc in the box sends it too
  await working();
  ci().focus(); key(w, ci(), 'Escape');
  await until(async () => (await aborts()).length === 2);
  check((await aborts()).length === 2 && d.querySelector('#chat-msgs'), 'Esc while working: abort, the chat stays open');
  await v1('POST', '/agent/aborted', {}); w.eval('agentPoll()'); await until(() => stopB()?.hidden);
  // Ctrl+C with a selection stays Copy (Windows / Linux); an open menu keeps its Esc
  await working();
  ci().value = 'copy me'; ci().focus(); ci().setSelectionRange(0, 4);
  key(w, ci(), 'c', {ctrlKey: true}); await sleep(600);
  check((await aborts()).length === 2 && !stopB().disabled, 'Ctrl+C with a selection: no abort');
  ci().setSelectionRange(7, 7);
  key(w, ci(), 'c', {ctrlKey: true});
  await until(async () => (await aborts()).length === 3);
  check((await aborts()).length === 3, 'Ctrl+C without a selection: abort');
  await v1('POST', '/agent/aborted', {}); w.eval('agentPoll()'); await until(() => stopB()?.hidden);
  await working();
  click(w, fbtn()); await until(() => d.querySelector('[role=menuitem]'));
  key(w, d.querySelector('[role=menuitem]'), 'Escape'); await sleep(600);
  check((await aborts()).length === 3, 'an open menu: Esc closes the menu, no abort');
  ci().value = '';
  // in a job's history the abort carries the job
  w.eval(`jc_enter(${CL}, {id: ${J}})`);
  await until(() => d.querySelector('#jc-bar'));
  await w.eval('jc_sync(true)'); w.eval('chatPatch({})'); await until(() => stopB() && !stopB().hidden, 40);
  check(stopB() && !stopB().hidden, 'a running job\'s history: Stop shows');
  click(w, stopB());
  await until(async () => (await aborts()).length === 4);
  ab = await aborts();
  check(ab.length === 4 && ab[3].data.job_id === J, 'Stop in a job\'s history carries the job_id');

  console.log(`p2144_a_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
