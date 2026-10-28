// 2.144.0 UI tests of part A (#2416 #2419 #2412; own container, start.sh). jsdom, the agent chat at the computer with a job in it:
// - #2419: no filter row above the messages, the filter icon in the chat header (also wide), its menu, the dot while not "All"
// - #2416: "Only me and <agent>": my messages + the main agent's; a job's result WITH buttons is left out, an open approval of
//   the job stays; "Jobs": the card, the job's result with buttons and its approval, not the plain answer
// - #2412: while the agent works Stop (2.411.0 #3446: the first entry of the ⋯ menu, a red dot on ⋯; tooltip names the keys); a press / Esc sends the event abort
//   (the agent sees it), the entry waits; the agent's confirmation removes it; Ctrl+C with a selection stays Copy; an open
//   menu keeps its Esc; in a job's history Stop carries the job_id
// - 2.144.0 A2 (#2412): Stop only for a run for me ("working" alone, with no typing to me and no message of mine waiting,
//   is someone else's run: no button); Esc in the open message search closes the search, not the answer
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
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
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

  {  // 2.180.0 C (#2695): merged from p2117_c_ui.js (#2260) - the phone: the icon in the header, no row, no select, no dot at All
    const pw = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}), pd = pw.document, pb = () => pd.querySelector('#jcd-fbtn');
    await until(() => pb() && !pb().hidden);
    check(pb() && !pb().hidden && pd.querySelector('.chath').contains(pb()), 'phone: the filter icon sits in the chat header');
    check(!pd.querySelector('#jcd-filt') && !pd.querySelector('.jcdseg') && !pd.querySelector('select.jcdsel'), 'phone: no filter row, no select.jcdsel');
    check(!pb().querySelector('.jcdfdot'), 'phone: filter All, no dot');
    pw.close();
  }
  const w = await boot({user: 'alice', hash: `agents/${CL}`}), d = w.document;
  const fbtn = () => d.querySelector('#jcd-fbtn'), box = () => d.querySelector('#chat-msgs'), row = id => d.querySelector(`#chat-msgs [data-mid="a:${id}"]`);
  await until(() => fbtn() && !fbtn().hidden);
  const openFilter = async () => {  // 2.152.2 (#2627): the header's menu -> the entry "Filter: …" -> the three choices
    click(w, fbtn()); await until(() => d.querySelector('[role=menuitem]'));
    click(w, [...d.querySelectorAll('[role=menuitem]')].find(x => /^Filter/.test(x.textContent.trim())));
    await until(() => [...d.querySelectorAll('[role=menuitem]')].some(x => x.textContent.trim() === 'All'));
  };
  // ================= #2419 the filter icon on every width
  check(fbtn() && !fbtn().hidden && d.querySelector('.chath').contains(fbtn()), 'wide: the filter icon sits in the chat header');
  check(!d.querySelector('#jcd-filt') && !d.querySelector('.jcdseg'), 'wide: no filter row above the messages');
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'agentchat.css'), 'utf8');
  check(/\.jcdfbtn\{[^}]*display:inline-flex/.test(css) && !/\.jcdfilt|\.jcdseg/.test(css), 'CSS: the icon shows on every width, the row rules are gone');
  // 2.180.0 C (#2695): merged from p2117_c_ui.js - hit area, accent dot, rem only; no select; no dot at the start
  const blk = css.slice(css.indexOf('/* 2.96.0 C (#2015)'));
  check(/\.jcdfbtn\{[^}]*min-width:2\.75rem;min-height:2\.75rem/.test(blk) && /\.jcdfdot\{[^}]*background:var\(--accent\)/.test(blk), 'CSS: icon >= 2.75rem, dot in the accent colour');
  check(!/\.jcdfbtn\{[^}]*\d+px/.test(blk) && !/\.jcdfdot\{[^}]*\d+px/.test(blk), 'CSS: rem sizes');
  check(!d.querySelector('select.jcdsel') && !fbtn().querySelector('.jcdfdot'), 'wide: no select.jcdsel, filter All: no dot');
  const pick = async label => {
    await openFilter();  // 2.152.2 (#2627)
    const it = [...d.querySelectorAll('[role=menuitem]:not(.mback)')];  // 2.152.2 (#2627): the choices are the submenu of "Filter: …"
    // 2.290.0 B (#3157): a fourth choice "Me, <agent> and job results" between "Only me" and "Jobs"
    check(it.length === 4 && /All/.test(it[0].textContent) && /Only me and Dev Bot/.test(it[1].textContent) && /Me, Dev Bot and job results/.test(it[2].textContent) && /Jobs/.test(it[3].textContent), 'the menu: All / Only me and <agent> / Me, <agent> and job results / Jobs');
    click(w, it.find(x => label.test(x.textContent))); await sleep(300);
  };
  // ================= #2416 Only me and <agent>
  await pick(/Only me/);
  await until(() => !d.querySelector('.jcd'));
  check(w.eval(`LS.get('jcdFilt')`) === 'me' && fbtn().classList.contains('jcdfon') && /Filter: /.test(fbtn().title), 'Only me: kept, the icon names the filter');  // 2.350.0 (#3317): no dot, the title
  check(row(plain) && box().querySelector(':scope > .cmsg.me'), 'Only me: the plain answer and my message');
  check(!d.querySelector('.jcd') && !row(js), 'Only me: no job card, no job message');
  check(!row(jr), 'Only me: the job result WITH buttons is left out (#2416)');
  check(row(ja), 'Only me: the open approval of the job stays');
  // ================= 2.290.0 B (#3157) Me, <agent> and job results
  // an error of the job and a result of a second (part) job without buttons; progress lines (say) must stay out
  const je = (await say('⚠ Knox: the build failed', {job_id: J, job_msg: 'error'})).id;
  const J3 = (await v1('POST', '/agent/jobs', {title: 'Lena: Release 2.144 part', user_id: me.id, state: 'running'})).id;
  const jq = (await say('Lena: halfway there', {job_id: J3, job_msg: 'say'})).id;
  const jr3 = (await say('✅ Lena: part ready\n1\n2\n3\n4\n5\n6\n7', {job_id: J3, job_msg: 'result'})).id;
  await w.eval('jc_sync(true)'); w.eval('agentPoll()');
  await pick(/Me, Dev Bot and job results/);
  await until(() => row(je));
  check(w.eval(`LS.get('jcdFilt')`) === 'res' && fbtn().classList.contains('jcdfon') && /Filter: /.test(fbtn().title), 'Results: kept, the icon names the filter');  // 2.350.0 (#3317)
  check(row(plain) && box().querySelector(':scope > .cmsg.me'), 'Results: the plain answer and my message');
  check(!d.querySelector('.jcd') && !row(js) && !row(jq), 'Results: no job card, no say / progress line');
  check(row(jr) && row(je) && row(jr3), 'Results: the end results (also with buttons) and the error');
  check(row(ja), 'Results: the open approval of the job stays');
  check(/Knox/.test(row(jr).closest('.jcdrf')?.querySelector('.jcdrn')?.textContent || '') && /Lena/.test(row(jr3).closest('.jcdrf')?.querySelector('.jcdrn')?.textContent || ''), 'Results: the name of the job in front of the result (also a part job)');
  check(row(jr3).closest('.jcdres')?.classList.contains('jcdclamp') && row(jr3).closest('.jcdrf').querySelector('.jcdmore'), 'Results: a long result is cut with "Show more"');
  check(w.eval(`jcd_pass({from: 'agent', body: 'x', job_msg: 'say'}, 'res', 7)`) === false
        && w.eval(`jcd_pass({from: 'agent', body: 'x', job_msg: 'result'}, 'res', 7)`) === true
        && w.eval(`jcd_pass({from: 'agent', body: 'x', job_msg: 'error'}, 'res', 7)`) === true
        && w.eval(`jcd_pass({from: 'agent', body: 'x'}, 'res', 0)`) === true, 'jcd_pass: the results rule');
  // an unknown stored value falls back to All, the new one is remembered like the others
  w.eval(`LS.set('jcdFilt', 'bogus')`);
  check(w.eval(`jcd_filter()`) === 'all', 'an unknown stored filter falls back to All');
  w.eval(`LS.set('jcdFilt', 'res')`);
  check(w.eval(`jcd_filter()`) === 'res', 'the results filter is remembered');
  // ================= Jobs
  await pick(/Jobs/);
  await until(() => d.querySelector('.jcd'));
  check(d.querySelector('.jcd') && row(jr) && row(ja), 'Jobs: the card, the result with buttons, the approval');
  check(w.eval(`LS.get('jcdFilt')`) === 'jobs' && fbtn().classList.contains('jcdfon') && /Filter: Jobs/.test(fbtn().title), 'Jobs: kept, the icon names the filter');  // 2.350.0 (#3317)  // 2.180.0 C (#2695): from p2117_c_ui.js
  check(!row(plain) && !box().querySelector(':scope > .cmsg.me'), 'Jobs: not the plain answer, not my message');
  // the rule as a function: a job row with buttons, an answered approval, a main-agent message with buttons
  check(w.eval(`jcd_pass({from: 'agent', choices: {choices: [{id: 1}]}}, 'me', 7)`) === false
        && w.eval(`jcd_pass({from: 'agent', choices: {choices: [{id: 1}]}}, 'me', 0)`) === true
        && w.eval(`jcd_pass({from: 'agent', choices: {choices: [{id: 1}]}}, 'jobs', 0)`) === false
        && w.eval(`jcd_pass({id: 1, from: 'agent', choices: {approval: {title: 'x'}}, choice: {ids: ['yes']}}, 'me', 7)`) === false, 'jcd_pass: the filter rules');
  await pick(/^\s*All/);
  await until(() => row(plain) && d.querySelector('.jcd'));
  check(row(plain) && d.querySelector('.jcd') && !fbtn().querySelector('.jcdfdot') && !fbtn().classList.contains('jcdfon'), 'All: everything again, no dot');

  // ================= #2412 Stop
  // 2.411.0 (#3446): Stop left the box: it is the first entry of the ⋯ menu (red), the ⋯ button has a red dot (chbusy) meanwhile
  const ci = () => d.querySelector('#chat-in'), busy = () => !!fbtn()?.classList.contains('chbusy');
  const stopIt = async () => { w.eval('closePop()'); click(w, fbtn()); await until(() => d.querySelector('#pop:not(.hidden) [role=menuitem]')); return d.querySelector('#pop:not(.hidden) .chmi-stop'); };
  check(!d.querySelector('#chat-stop, .chcomp .chstop'), 'no Stop button in the box any more (#3446)');
  check(!busy() && !(await stopIt()), 'idle: no dot, no Stop in the menu'); w.eval('closePop()');
  // 2.144.0 A2 (#2412): a run for me = "working" + its typing signal to me (what the launcher sends while it answers)
  const working = async () => { await v1('PUT', '/agent/status', {status: 'working', text: 'Answering in the chat'}); await v1('POST', '/agent/typing', {chat_user_id: me.id}); w.eval('agentPoll()'); await until(() => busy(), 40); };
  const aborts = async () => ((await v1('GET', '/agent/events?since=0')).data || []).filter(e => e.event === 'abort');
  // "working" while a job of the agent runs is the job's: no Stop in the main chat
  await v1('PUT', '/agent/status', {status: 'working', text: 'Job: Knox'}); await w.eval('jc_sync(true)'); w.eval('agentPoll()'); await sleep(1500);
  check(!busy(), 'a job runs: its "working" shows no Stop in the main chat');
  await v1('PATCH', `/agent/jobs/${J}`, {state: 'done'}); await w.eval('jc_sync(true)');
  // 2.144.0 A2: "working" without typing to me and without a message of mine waiting = someone else's run: no Stop
  await v1('PUT', '/agent/status', {status: 'working', text: 'Answering in the chat'}); w.eval('agentPoll()'); await sleep(1500);
  check(!busy() && w.eval(`chatBusy(agentById(${CL}))`) === false, 'working for someone else: no Stop for me (#2412 A2)');
  await working();
  check(busy() && /Stop the answer/.test(fbtn().title), 'working: the ⋯ button has the dot and names Stop (#3446)');
  let it = await stopIt();
  const all = [...d.querySelectorAll('#pop:not(.hidden) [role=menuitem]')];
  check(it && all[0] === it && !it.disabled && /Stop the answer/.test(it.textContent) && /Esc/.test(it.title) && /Ctrl\+C/.test(it.title), 'Stop: the first menu entry, the tooltip names the keys (#3446)');
  click(w, it);
  await until(async () => (await aborts()).length === 1);
  let ab = await aborts();
  check(ab.length === 1 && ab[0].data.user.id === me.id && !ab[0].data.job_id, 'the press sends abort to the agent');
  it = await stopIt();
  check(it && it.disabled && /Stopping/.test(it.textContent), 'the entry waits: Stopping…');
  w.eval('closePop()');
  await v1('POST', '/agent/aborted', {seq: ab[0].seq});
  w.eval('agentPoll()');
  await until(() => !busy());
  check(!busy(), 'confirmed by the agent: the dot goes');
  // Esc in the box sends it too
  await working();
  ci().focus(); key(w, ci(), 'Escape');
  await until(async () => (await aborts()).length === 2);
  check((await aborts()).length === 2 && d.querySelector('#chat-msgs'), 'Esc while working: abort, the chat stays open');
  await v1('POST', '/agent/aborted', {}); w.eval('agentPoll()'); await until(() => !busy());
  // Ctrl+C with a selection stays Copy (Windows / Linux); an open menu keeps its Esc
  await working();
  ci().value = 'copy me'; ci().focus(); ci().setSelectionRange(0, 4);
  key(w, ci(), 'c', {ctrlKey: true}); await sleep(600);
  check((await aborts()).length === 2 && !w.eval('chatAbortWaits()'), 'Ctrl+C with a selection: no abort');
  ci().setSelectionRange(7, 7);
  key(w, ci(), 'c', {ctrlKey: true});
  await until(async () => (await aborts()).length === 3);
  check((await aborts()).length === 3, 'Ctrl+C without a selection: abort');
  await v1('POST', '/agent/aborted', {}); w.eval('agentPoll()'); await until(() => !busy());
  await working();
  click(w, fbtn()); await until(() => d.querySelector('[role=menuitem]'));
  key(w, d.querySelector('[role=menuitem]'), 'Escape'); await sleep(600);
  check((await aborts()).length === 3, 'an open menu: Esc closes the menu, no abort');
  ci().value = '';
  // 2.144.0 A2: Esc in the open message search closes the search, the agent keeps working
  click(w, d.querySelector('.chath [data-act="ms-toggle"]')); await until(() => d.querySelector('#ms-q'));
  key(w, d.querySelector('#ms-q'), 'Escape'); await sleep(600);
  check((await aborts()).length === 3 && !d.querySelector('#ms-q'), 'Esc in the message search: the search closes, no abort');
  // in a job's history the abort carries the job
  const J2 = (await v1('POST', '/agent/jobs', {title: 'Lena: Release 2.144 stop', user_id: me.id, state: 'running'})).id;
  await w.eval('jc_sync(true)');
  w.eval(`jc_enter(${CL}, {id: ${J2}})`);
  await until(() => d.querySelector('#jc-bar'));
  await w.eval('jc_sync(true)'); w.eval('chatPatch({})'); await until(() => busy(), 40);
  it = await stopIt();
  check(busy() && it, 'a running job\'s history: the dot and Stop in the menu');
  if (it) click(w, it);
  await until(async () => (await aborts()).length === 4);
  ab = await aborts();
  check(ab.length === 4 && ab[3].data.job_id === J2, 'Stop in a job\'s history carries the job_id');

  console.log(`p2144_a_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
