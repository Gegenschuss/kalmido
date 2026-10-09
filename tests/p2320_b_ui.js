// 2.32.0 UI tests (agent B: the agent chat), own container (start.sh). jsdom:
// #1079 the chat header: "Host default (Auto)" once the host reported its own default, the model the host really runs
//       ("Opus 5.5"), a wished model the host has not taken yet: "set: sonnet · runs: Opus 5.5"; the menu names it too
// #1081 steps: up to 3 small grey lines under the typing dots (newest on top, shown as text, never as HTML); a tap hides
//       them (setting agent_steps_live, saved), "Show steps" / a tap on the dots brings them back; the answer takes them
//       away; the header switch "Always show steps" (aria-pressed, saved) keeps them above every answer; a job result in
//       the chat has its folded "History" (open with the switch), grouped by the job's progress lines (time + bold line),
//       the full history as a text file; the job list has the same block; another person's job has none
// #1062 under the messages only the typing dots (the state "working · …" stands only in the header); the reaction smiley of
//       an agent message is hidden until hover / focus (desktop) or a long press (touch)
// #1082 approvals with 👍 / 👎 (decorative, aria-hidden; the button text names it): a permission question's Allow / Deny and
//       its result line, the job buttons
// Firefox 390 touch: the live steps under the dots (screenshot), nothing sticks out sideways, the smiley of an agent message
// is not tappable before a long press; 1440: the header with the model, the kept steps and the job history (screenshot).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2320_b_ui', check, shots: 'P2320B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Release', list_id: L})).id;
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();
  const say = (body, extra = {}) => v1('POST', `/agent/chats/${ME.id}`, {body, ...extra});
  const step = text => v1('POST', '/agent/progress', {text, chat_user_id: ME.id});
  const cm = (d, id) => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);

  // ================= #1079 the header
  await v1('PUT', '/agent/status', {status: 'idle', model: 'Opus 5.5', host_permission_mode: 'auto', permission_mode: 'auto'});
  const hello = await say('Hello Alice');
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => cm(d, hello.id));
  check(/^Host default \(Auto\)$/.test(d.querySelector('.chmode')?.textContent.trim() || ''), '#1079: the badge names the host\'s default: ' + d.querySelector('.chmode')?.textContent);
  check(d.querySelector('.chmodel')?.textContent === 'Opus 5.5', '#1079: the model the host runs: ' + d.querySelector('.chmodel')?.textContent);
  click(w, d.querySelector('.chmode')); await sleep(200);
  check([...d.querySelectorAll('[role="menuitem"]')].some(b => /Host default \(Auto\)/.test(b.textContent)), '#1079: the menu names it too');
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  await call('PATCH', `/api/admin/agents/${AG}`, {runtime: {model: 'sonnet'}});
  await w.eval('load().then(render)'); await w.eval('chatLoad()'); await sleep(300);
  check(d.querySelector('.chmodel')?.textContent === 'set: sonnet · runs: Opus 5.5', '#1079: a wished model the host has not taken yet: both ' + d.querySelector('.chmodel')?.textContent);
  await call('PATCH', `/api/admin/agents/${AG}`, {runtime: {model: 'claude-opus-5-5'}});
  await w.eval('load().then(render)'); await w.eval('chatLoad()'); await sleep(300);
  check(d.querySelector('.chmodel')?.textContent === 'Opus 5.5', '#1079: the same model in another spelling: only the running one ' + d.querySelector('.chmodel')?.textContent);
  await call('PUT', `/api/agents/${AG}/permission-mode`, {mode: 'ask'});
  await w.eval('load().then(render)'); await w.eval('chatLoad()'); await sleep(300);
  check(d.querySelector('.chmode')?.textContent.trim() === 'Ask first · runs: Auto', '#1079: wish and real mode differ: both ' + d.querySelector('.chmode')?.textContent);
  await call('PUT', `/api/agents/${AG}/permission-mode`, {mode: ''});

  // ================= #1081 live steps + #1062 the line under the messages
  await call('POST', `/api/agents/${AG}/chat`, {body: 'Please fix the build'});
  await v1('PUT', '/agent/status', {status: 'working', text: 'Answering Alice'});
  for (const t of ['I read the failing test first', 'The build log shows a missing import', 'Fixing the import <img src=x onerror="window.__x=1">', 'Running the tests now'])
    await step(t);
  await w.eval('load().then(render)'); await w.eval('chatLoad()'); await sleep(300);
  let lines = [...d.querySelectorAll('#chat-steps .chstep')].map(x => x.textContent);
  check(lines.length === 3 && lines[0] === 'Running the tests now' && /<img src=x/.test(lines[1]) && !d.querySelector('#chat-steps img') && !w.__x,
    '#1081: the newest 3 live steps, newest on top, shown as text ' + JSON.stringify(lines));
  check(d.querySelector('#chat-steps').compareDocumentPosition(d.querySelector('#chat-typing')) & 2, '#1081: under the typing line');
  check(!/working on it|Answering Alice/.test(d.querySelector('#chat-typing')?.textContent || '') && /Answering Alice/.test(d.querySelector('#chat-st')?.textContent || ''),
    '#1062: the state only in the header, not again under the messages');
  click(w, d.querySelector('#chat-steps .chstepl')); await sleep(300);
  check(!d.querySelector('#chat-steps .chstep') && d.querySelector('#chat-steps .chstepon'), '#1081: a tap hides them ("Show steps" stays)');
  check(await until(async () => (await call('GET', '/api/state')).settings.agent_steps_live === '0'), '#1081: ... saved on the server');
  click(w, d.querySelector('#chat-steps .chstepon')); await sleep(300);
  check(d.querySelectorAll('#chat-steps .chstep').length === 3, '#1081: "Show steps" brings them back');
  const ans = await say('Fixed: the import was missing.');
  await w.eval('chatLoad()'); await until(() => cm(d, ans.id));
  check(d.querySelector('#chat-steps').classList.contains('hidden') && !cm(d, ans.id).querySelector('.csteps'), '#1081: the answer takes the live lines away (kept steps only with the switch)');
  // the switch in the header
  const tog = () => d.querySelector('.chstog');
  check(tog() && tog().getAttribute('aria-pressed') === 'false' && tog().getAttribute('aria-label') === 'Always show steps', '#1081: the header switch "Always show steps"');
  click(w, tog()); await sleep(300);
  const kept = [...(cm(d, ans.id)?.querySelectorAll('.csteps span') || [])].map(x => x.textContent);
  check(tog().getAttribute('aria-pressed') === 'true' && kept.length === 4 && kept[0] === 'I read the failing test first' && cm(d, ans.id).querySelector('.csteps').nextElementSibling?.classList.contains('cbub'),
    '#1081: switched on: the run\'s steps small above the answer, oldest first ' + JSON.stringify(kept));
  check(!cm(d, hello.id).querySelector('.csteps'), '#1081: ... only where there were steps');
  check(await until(async () => (await call('GET', '/api/state')).settings.agent_steps_always === '1'), '#1081: the switch is saved per person');

  // ================= #1081 a job's history
  const job = await v1('POST', '/agent/jobs', {title: 'Release 2.32', task_id: T, user_id: ME.id, log: 'started'});
  await v1('PATCH', `/agent/jobs/${job.id}`, {append_log: 'Build'});
  await v1('POST', '/agent/progress', {text: 'Compiling the server', job_id: job.id});
  await v1('PATCH', `/agent/jobs/${job.id}`, {append_log: 'Tests'});
  await v1('POST', '/agent/progress', {text: 'All suites green', job_id: job.id});
  const res = await say('Release 2.32 is ready.', {job_id: job.id});
  await w.eval('chatLoad()'); await until(() => cm(d, res.id)?.querySelector('.jvb .jvh'));
  const jv = () => cm(d, res.id)?.querySelector('details.jobv');
  check(jv()?.open && [...jv().querySelectorAll('.jvh b')].map(x => x.textContent).join('|') === 'started|Build|Tests' && /All suites green/.test(jv().textContent),
    '#1081: the job result has its history, open with the switch, grouped by the progress lines ' + (jv()?.textContent || '').slice(0, 120));
  check(/History/.test(jv()?.querySelector('summary')?.textContent || '') && jv()?.querySelector(`a.jvdl[href="/api/agents/jobs/${job.id}/steps?format=txt"][download]`), '#1081: "History" + the whole history as a text file');
  click(w, jv().querySelector('summary')); await sleep(300);
  check(jv() && !jv().open && !jv().querySelector('.jvb'), '#1081: a tap on "History" folds it');
  click(w, d.querySelector('.chstog')); await sleep(300);
  check(!cm(d, ans.id).querySelector('.csteps'), '#1081: switched off: the kept steps go');
  await call('PATCH', '/api/settings', {agent_steps_always: '0', agent_steps_live: '1'});

  // ================= #1082 thumbs on a permission question
  const pq = await say('May I run `npm test`?', {permission: true, expires_in: 600});
  await w.eval('chatLoad()'); await until(() => cm(d, pq.id)?.querySelector('.cperm'));
  const pb = [...cm(d, pq.id).querySelectorAll('.cperm .cchb')];
  check(pb.length === 2 && pb[0].querySelector('.thumb[aria-hidden="true"]')?.textContent === '\u{1F44D}' && /Allow/.test(pb[0].textContent)
    && pb[1].querySelector('.thumb[aria-hidden="true"]')?.textContent === '\u{1F44E}' && /Deny/.test(pb[1].textContent) && !pb[0].querySelector('svg'),
    '#1082: Allow 👍 / Deny 👎, the emoji hidden from screen readers');
  click(w, pb[0]); await until(() => cm(d, pq.id)?.querySelector('.cpermst.ok'));
  check(cm(d, pq.id).querySelector('.cpermst.ok .thumb')?.textContent === '\u{1F44D}' && /Allowed/.test(cm(d, pq.id).querySelector('.cpermst').textContent), '#1082: "👍 Allowed HH:MM"');
  // #1062 the smiley: desktop only on hover (jsdom: the class and the rule exist)
  const ag1 = cm(d, hello.id);
  check(ag1.querySelector('.rxrow .rxtog'), '#1062: the agent message keeps its smiley (shown on hover / long press)');
  w.close();

  // ================= the Agents tab: the job list (alice: her job with history, bob: none)
  const wj = await v1('POST', '/agent/jobs', {title: 'Needs an OK', task_id: T, state: 'waiting', user_id: ME.id});
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  await until(() => d.querySelector('.jobs .job'));
  w.eval("S.jobs.f = 'all'; loadJobs()"); await until(() => [...d.querySelectorAll('.jobs .job')].some(j => /Release 2.32/.test(j.textContent)));
  const jr = [...d.querySelectorAll('.jobs .job')].find(j => /Release 2.32/.test(j.textContent));
  check(jr?.querySelector('details.jobv') && !jr.querySelector('details.jobv').open, '#1081: the job list: a folded "History" on my job');
  click(w, jr?.querySelector('details.jobv summary')); await until(() => d.querySelector('.jobs details.jobv[open] .jvh'));
  check(d.querySelectorAll('.jobs details.jobv[open] .jvh').length === 3, '#1081: ... opens with the grouped lines');
  const wr = [...d.querySelectorAll('.jobs .job')].find(j => /Needs an OK/.test(j.textContent));
  const jb = wr ? [...wr.querySelectorAll('[data-act="job-do"]')] : [];
  check(jb.length >= 2 && jb[0].querySelector('.thumb')?.textContent === '\u{1F44D}' && jb[1].querySelector('.thumb')?.textContent === '\u{1F44E}', '#1082: the job buttons Approve 👍 / Reject 👎');
  w.close();
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  w = await boot({user: 'bob', hash: 'agents'}); d = w.document;
  w.eval("S.jobs.f = 'all'; loadJobs()"); await until(() => [...d.querySelectorAll('.jobs .job')].some(j => /Release 2.32/.test(j.textContent)));
  const br = [...d.querySelectorAll('.jobs .job')].find(j => /Release 2.32/.test(j.textContent));
  check(br && !br.querySelector('details.jobv') && !/Compiling the server/.test(d.body.textContent), '#1081: bob sees the job (shared task), never its history');
  w.close();
  await v1('PATCH', `/agent/jobs/${wj.id}`, {state: 'stopped'});

  // ================= Firefox: the phone (390, touch) and the desktop (1440)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await call('POST', `/api/agents/${AG}/chat`, {body: 'And the release notes?'});
  await v1('PUT', '/agent/status', {status: 'working', text: 'Writing the notes'});
  for (const t of ['I collect the merged tasks of 2.32', 'Twelve tasks, three of them bug fixes', 'Writing the English notes now']) await step(t);
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(1200);
    await ev(`(() => { const b = document.querySelector('#chat-msgs'); b.scrollTop = b.scrollHeight; return 1; })()`); await sleep(300);
    const g = await ev(`(() => { const s = document.querySelector('#chat-steps'); const ls = s ? [...s.querySelectorAll('.chstep')] : []; const r = s?.getBoundingClientRect();
      const tg = [...document.querySelectorAll('#chat-msgs .cmsg.ag:not(.rxshow) .rxrow .rxtog')].map(x => x.getBoundingClientRect().width);
      return {n: ls.length, fs: ls[0] ? parseFloat(getComputedStyle(ls[0]).fontSize) : 0, h: r ? Math.round(r.height) : 0, vis: !!r && r.bottom <= innerHeight && r.top >= 0,
        wide: document.documentElement.scrollWidth <= 390, tg}; })()`);
    check(g && g.n === 3 && g.fs > 0 && g.fs <= 12 && g.h >= 44 && g.vis, `${tag}: #1081 three small live lines under the dots, a 44 px tap target, in view ` + JSON.stringify(g));
    check(g && g.wide, `${tag}: nothing sticks out sideways`);
    check(g && g.tg.length && g.tg.every(x => x <= 1), `${tag}: #1062 the smiley of an agent message is not there before a long press ` + JSON.stringify(g?.tg));
    await shot('p2320b-390-live-steps.png');
  }, true);
  await say('Here are the notes: …');
  await call('PATCH', '/api/settings', {agent_steps_always: '1'});
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { chatOpen(${AG}, {float: false}); return 1; })()`); await sleep(1800);
    await ev(`(() => { const b = document.querySelector('#chat-msgs'); b.scrollTop = b.scrollHeight; return 1; })()`); await sleep(300);
    const g = await ev(`(() => { const m = document.querySelector('.chmodel'), n = document.querySelector('.chnm'); const k = [...document.querySelectorAll('#chat-msgs .csteps')];
      const t = [...document.querySelectorAll('#chat-msgs .cmsg.ag')].pop()?.querySelector('.rxtog');
      return {model: m?.textContent, inHead: !!m && m.getBoundingClientRect().right <= n.getBoundingClientRect().right + 1, kept: k.length, hist: !!document.querySelector('#chat-msgs details.jobv[open] .jvh'),
        tog: t ? getComputedStyle(t).opacity : null}; })()`);
    check(g && g.model === 'Opus 5.5' && g.inHead, `${tag}: #1079 the model in the header ` + JSON.stringify(g));
    check(g && g.kept >= 2 && g.hist, `${tag}: #1081 kept steps and the open job history ` + JSON.stringify(g));
    check(g && g.tog === '0', `${tag}: #1062 the smiley waits for the mouse ` + JSON.stringify(g));
    await shot('p2320b-1440-steps-history.png');
  }, false);
  await call('PATCH', '/api/settings', {agent_steps_always: '0'});

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
