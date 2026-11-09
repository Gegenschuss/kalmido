// 2.754.0 UI test (#5222: the job card of the Agents page opens the job's chat). Own container (start.sh), Firefox. Invented data only.
// kalmido-suite: fresh
// freelancer-matrix: agents (alice runs the instance without an organisation, her agent and its jobs are private)
// - phone 320 px and 460 px (touch): every job card - running AND ended - has "Open chat" first in its button row; "Message"
//   only on the running one; nothing sticks out of the page; the button stays where it is when the job ends (calm view)
// - a tap on the title opens the job's history (#agents/<agent>, the job bar); Back (the bar's button or the phone's Back)
//   leads to the Agents page again, not into the whole chat
// - an ended job: the box stays on ("Message wakes the job up…"), the message goes out as "Job N: …" with its job_id
// - computer 1280 px (mouse): "Open chat" opens the job in the side panel, the bar's Back closes the panel over the Agents page
// P2754B_NOSTART=1 = the server already runs. Screenshots: P2754B_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2754_b_jobcard_ui', check, shots: 'P2754B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2754B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
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
  const job = async (title, text, state = 'running') => {
    const id = (await v1('POST', '/agent/jobs', {title, user_id: me.id, state: 'running'})).id;
    await v1('POST', `/agent/chats/${me.id}`, {body: text, job_id: id});
    if (state !== 'running') await v1('PATCH', `/agent/jobs/${id}`, {state});
    return id;
  };
  const JA = await job('Clara: Release 1.0', 'Clara: halfway there');
  const JD = await job('Ben: Old release', 'Ben: all done', 'done');
  const JR = await job('Dora: Guide', 'Dora: writing the guide');
  await v1('POST', `/agent/chats/${me.id}`, {body: 'Hello, how can I help?'});
  check(JA > 0 && JD > 0 && JR > 0, 'setup: two running jobs and an ended one');

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  const start = async (ev, nav, w) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev) === 200, `${w}: alice signs in`);
    await nav(B + '#agents');
    // the "All" filter: the ended job is listed too
    await ready(ev, `S.booted && location.hash === '#agents' && !!document.querySelector('[data-act="jobs-f"][data-f="all"]')`);
    await ev(`(document.querySelector('[data-act="jobs-f"][data-f="all"]').click(), 1)`);
    return ready(ev, `!!document.querySelector('#job-${JA}') && !!document.querySelector('#job-${JD}')`);
  };
  const openBtn = id => `document.querySelector('#job-${id} .jobb [data-act="jc-open"]')`;
  const inJob = id => `!!S.chat.job && +S.chat.job.id === ${id} && !!document.getElementById('jc-bar') && location.hash === '#agents/${CL}'`;
  const onAgents = `location.hash === '#agents' && !S.chat.job && !document.querySelector('#view .chview') && !!document.querySelector('#job-${JA}')`;

  const phone = async (wd, endOne) => firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: 800}});
    check(await start(ev, nav, `${wd} px`), `${wd} px: the Agents page with the jobs`);
    // the cards: "Open chat" on every job, first in the row; "Message" only on the running one
    const cards = await ev(`JSON.stringify([${JA}, ${JD}].map(id => { const b = document.querySelector('#job-' + id + ' .jobb [data-act="jc-open"]'); return {id, b: !!b, first: !!b && b === b.parentNode.firstElementChild, from: b?.dataset.from, aid: +b?.dataset.aid, msg: !!document.querySelector('#job-' + id + ' [data-act="jc-msg"]'), ttl: !!document.querySelector('#job-' + id + ' .jobh .jc-ttl[data-act="jc-open"]')}; }))`).then(JSON.parse).catch(() => []);
    const ca = cards.find(c => c.id === JA) || {}, cd = cards.find(c => c.id === JD) || {};
    check(ca.b && ca.first && ca.from === 'agents' && ca.aid === CL && ca.ttl, `${wd} px: the running job's card has "Open chat" first, its title opens it too ${JSON.stringify(ca)}`);
    check(cd.b && cd.first && cd.from === 'agents' && cd.ttl, `${wd} px: the ended job's card has "Open chat" as well ${JSON.stringify(cd)}`);
    check(ca.msg && !cd.msg, `${wd} px: "Message" stays for the running job only`);
    check(await ev(`document.documentElement.scrollWidth <= innerWidth + 1 && [...document.querySelectorAll('.job .jobb [data-act="jc-open"]')].every(b => b.getBoundingClientRect().right <= innerWidth + 1)`), `${wd} px: nothing sticks out of the page`);
    await shot(`phone${wd}-cards`);

    if (endOne) {  // calm view: the job ends, "Open chat" stays where it was in its card
      const pos = `(() => { const c = document.querySelector('#job-${JR}'), b = c?.querySelector('.jobb [data-act="jc-open"]'); return b ? Math.round(b.getBoundingClientRect().left - c.getBoundingClientRect().left) : null; })()`;
      const x0 = await ev(pos);
      check(x0 !== null, `${wd} px: the third job's card has "Open chat"`);
      await v1('PATCH', `/agent/jobs/${JR}`, {state: 'done'});
      check(await ready(ev, `!!document.querySelector('#job-${JR}.st-done') && !document.querySelector('#job-${JR} [data-act="jc-msg"]')`, 80), `${wd} px: the job has ended on the page`);
      check(await ev(pos) === x0, `${wd} px: "Open chat" did not move when the job ended (${x0})`);
    }

    // the ended job: a tap on its title opens its history, the box stays on
    await ev(`(document.querySelector('#job-${JD} .jobh .jc-ttl').click(), 1)`);
    check(await ready(ev, inJob(JD), 40), `${wd} px: the title opens the ended job's history`);
    check(await ready(ev, `/ended/.test(document.getElementById('jc-bar')?.textContent || '') && !!document.getElementById('chat-in') && !document.getElementById('chat-in').disabled && /wakes the job up/.test(document.getElementById('chat-in').placeholder)`, 30),
      `${wd} px: an ended job: the bar says so, the box stays on with "Message wakes the job up…"`);
    check(await ev(`document.querySelector('#jc-bar [data-act="jc-back"]')?.title === 'Back to the agents'`), `${wd} px: the bar's back button says where it leads`);
    check(await ready(ev, `/all done/.test(document.getElementById('chat-msgs')?.textContent || '') && !/halfway there/.test(document.getElementById('chat-msgs')?.textContent || '')`, 40), `${wd} px: the ended job's history shows its own messages`);
    await shot(`phone${wd}-ended-job`);
    const msg = `wake up ${wd}`;
    await ev(`(() => { const ci = document.getElementById('chat-in'); ci.value = ${JSON.stringify(msg)}; ci.dispatchEvent(new Event('input', {bubbles: true})); document.querySelector('.chview [data-act="chat-send"]').click(); return 1; })()`);
    let sent = null;
    for (let i = 0; i < 60 && !sent; i++) { sent = ((await call('GET', `/api/agents/${CL}/chat`)).messages || []).find(m => m.from === 'user' && m.body.includes(msg)); if (!sent) await sleep(250); }
    check(sent?.body === `Job ${JD}: ${msg}` && sent?.job_id === JD, `${wd} px: sent to the ended job as "Job N: …" with its job_id ${sent?.body} ${sent?.job_id}`);
    await ev(`(document.querySelector('#jc-bar [data-act="jc-back"]').click(), 1)`);
    check(await ready(ev, onAgents, 40), `${wd} px: the bar's Back leads to the Agents page, not into the whole chat`);
    check(await ev(`!history.state?.jc`), `${wd} px: no job entry left in the history`);

    // the running job: "Open chat", then the phone's Back
    await ready(ev, `!!${openBtn(JA)}`);
    const n1 = await ev('history.length');
    await ev(`(${openBtn(JA)}.click(), 1)`);
    check(await ready(ev, inJob(JA), 40), `${wd} px: "Open chat" opens the running job's history`);
    check(await ev(`!document.getElementById('chat-in').disabled && /Clara/.test(document.getElementById('chat-in').placeholder)`), `${wd} px: the box writes to the running job`);
    check(await ev(`history.length === ${n1} + 1`), `${wd} px: one step in the history (the chat page), no extra job entry`);
    await ev('(history.back(), 1)');
    check(await ready(ev, onAgents, 40), `${wd} px: the phone's Back leads to the Agents page`);
  }, true);

  await phone(320, true);
  await phone(460, false);

  // ================= computer: 1280 px, mouse - the side panel
  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    check(await start(ev, nav, '1280 px'), '1280 px: the Agents page');
    await ev(`(${openBtn(JA)}.click(), 1)`);
    check(await ready(ev, `!!S.chat.job && +S.chat.job.id === ${JA} && !!document.querySelector('#achat:not(.hidden) #jc-bar') && location.hash === '#agents'`, 40), '1280 px: "Open chat" shows the job in the side panel');
    await ev(`(document.querySelector('#achat [data-act="jc-back"]').click(), 1)`);
    check(await ready(ev, `!S.chat.job && !!document.getElementById('achat')?.classList.contains('hidden') && location.hash === '#agents' && !!document.querySelector('#job-${JA}')`, 40), '1280 px: Back closes the panel over the Agents page');
  }, false);

  console.log(`p2754_b_jobcard_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error('FAIL: crashed', e); process.exit(1); });
