// kalmido-suite: fresh
// 2.758.0 UI test (#5223): the agents page moves only when the person makes it move. Own container (start.sh), Firefox (real
// layout) on a phone with a finger (320 and 460 px, touch). Alice (no organisation, her private agent) has several running jobs
// with a long history, a log and a conversation; the page is scrolled to the middle, History / Conversation / Log of one job
// are opened by a tap, the history box is scrolled into its middle. Then three agent steps arrive (the oldest job changes
// last), the conversation loads again and a new job starts: the tapped summary and the job card under it keep their screen
// position (+-1 px), the history box keeps its scroll and stays the same node, the conversation's <details> is not exchanged,
// the cards keep their order (by start, newest on top). Invented names only.
// freelancer-matrix: agents (alice without an organisation: her own jobs list, history and conversation)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p5223_agenten_ruhe_ui', check, shots: 'P5223_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,agents'});
  const ME = (await call('GET', '/api/state')).me;
  check(!(ME.workspaces || []).length, 'setup: Alice has no organisation');
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper'});
  const AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();
  // a step; the server's step limit per agent (429) is waited out, the step is sent again
  const prog = async (text, job_id) => { for (let i = 0; i < 40; i++) { const x = await fetch(V + '/agent/progress', {method: 'POST', headers: AGH, body: JSON.stringify({text, job_id})}); if (x.status !== 429) return check(x.status === 201, `step "${text}" stored (${x.status})`); await sleep(1500); } check(false, `step "${text}": still 429`); };
  const L = (await call('POST', '/api/lists', {name: 'Garden plan'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  // six running jobs, each with a log, a few steps and a message; the third (T) gets a long history
  const J = [];
  for (let i = 0; i < 6; i++) {
    const j = await v1('POST', '/agent/jobs', {title: `Garden job ${i + 1}`, user_id: ME.id, log: 'started'});
    J.push(j.id);
    await v1('PATCH', `/agent/jobs/${j.id}`, {append_log: Array.from({length: 6}, (_, k) => `Bed ${i}.${k} prepared`).join('\n')});
    for (let k = 0; k < 3; k++) await prog(`Watering row ${k} of job ${i + 1}`, j.id);
    await v1('POST', `/agent/chats/${ME.id}`, {body: `Job ${i + 1}: halfway through the beds`, job_id: j.id});
  }
  const T = J[2];
  for (let k = 0; k < 40; k++) await prog(`Planting seedling ${k} along the fence`, T);

  const run = (wd, ht) => firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = String(wd);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, `${tag}: Firefox login`);
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };
    const tap = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return false; e.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerType: 'touch'})); e.click(); return true; })()`);
    // the gathered live redraws of the page have run (no timer left, no request open)
    const settled = async () => { await o.idle?.().catch(() => {}); await wait(`!FL.vt && !jobStepsBusy.size && !Object.values(S.jth).some(t => t.busy)`, 40); await sleep(500); };
    await o.nav(B + '#agents');
    check(await wait(`document.querySelectorAll('#view .jobs .job').length === 6`), `${tag}: the six jobs are drawn`);
    const order = () => ev(`JSON.stringify([...document.querySelectorAll('#view .jobs .job')].map(e => +e.id.slice(4)))`).then(JSON.parse);
    const o0 = await order();
    check(JSON.stringify(o0) === JSON.stringify([...J].reverse()), `${tag}: the open jobs by start, newest on top (${o0})`);
    // scroll so that job T's card begins in the upper third, then tap History, Conversation and Log of T
    await ev(`(() => { const v = document.getElementById('view'), c = document.getElementById('job-${T}'); v.scrollTop += c.getBoundingClientRect().top - v.getBoundingClientRect().top - 60; return 1; })()`);
    check(await ev(`document.getElementById('view').scrollTop > 0`), `${tag}: the page is scrolled`);
    check(await tap(`#job-${T} details.jobth > summary`), `${tag}: Conversation tapped`);
    check(await wait(`/halfway through/.test(document.querySelector('#job-${T} .jobth .jthbody')?.textContent || '')`), `${tag}: the conversation is loaded`);
    check(await tap(`#job-${T} details.joblog > summary`), `${tag}: Log tapped`);
    check(await tap(`#job-${T} details.jobv > summary`), `${tag}: History tapped`);
    check(await wait(`document.querySelectorAll('#job-${T} details.jobv[open] .jvb .jvh, #job-${T} details.jobv[open] .jvb .jvs').length > 20`), `${tag}: the history is loaded`);
    await settled();
    // the history box in its middle; mark the nodes that must stay
    await ev(`(() => { const b = document.querySelector('#job-${T} .jvb'); b.scrollTop = Math.round((b.scrollHeight - b.clientHeight) / 2); b.__p5223 = 1; document.querySelector('#job-${T} details.jobth').__p5223 = 1; return 1; })()`);
    check(await ev(`(() => { const b = document.querySelector('#job-${T} .jvb'); return b.scrollHeight > b.clientHeight + 40; })()`), `${tag}: the history box scrolls`);
    const pos = () => ev(`JSON.stringify((() => { const s = document.querySelector('#job-${T} details.jobv > summary'), n = document.getElementById('job-${T}').nextElementSibling, b = document.querySelector('#job-${T} .jvb');
      return {sum: s.getBoundingClientRect().top, next: n && n.getBoundingClientRect().top, box: b && b.scrollTop, boxSame: !!(b && b.__p5223), thSame: !!document.querySelector('#job-${T} details.jobth')?.__p5223, thOpen: !!document.querySelector('#job-${T} details.jobth')?.open}; })())`).then(JSON.parse);
    const p0 = await pos();
    await shot(`p5223-${tag}-before.png`);
    // three agent steps: the oldest job (J[0]) and T change, the page hears it the way /api/version tells it
    for (let k = 0; k < 3; k++) {
      await prog(`Step ${k} of the first job`, J[0]);
      await prog(`Compost turned ${k}`, T);
      await ev(`(stepsChanged(), loadJobs(), 1)`);
      check(await wait(`/Compost turned ${k}/.test(document.querySelector('#job-${T} .jvb')?.textContent || '')`), `${tag}: step ${k}: the open history shows the new step`);
      await settled();
      const p = await pos();
      check(Math.abs(p.sum - p0.sum) <= 1, `${tag}: step ${k}: the tapped History stays where it was (${p0.sum} -> ${p.sum})`);
      check(Math.abs(p.next - p0.next) <= 1, `${tag}: step ${k}: the job card under it stays where it was (${p0.next} -> ${p.next})`);
      check(p.boxSame && Math.abs(p.box - p0.box) <= 1, `${tag}: step ${k}: the history box is the same and keeps its scroll (${p0.box} -> ${p.box}, same ${p.boxSame})`);
    }
    check(JSON.stringify(await order()) === JSON.stringify(o0), `${tag}: the working jobs kept their places`);
    // the conversation loads again (a new message of the job): its <details> stays, only the inside changes
    await v1('POST', `/agent/chats/${ME.id}`, {body: `Job 3: the fence is planted`, job_id: T});
    await ev(`(jth_load(S.jobs.items.find(x => x.id === ${T})), 1)`);
    check(await wait(`/fence is planted/.test(document.querySelector('#job-${T} .jobth')?.textContent || '')`), `${tag}: the conversation shows the new message`);
    await settled();
    let p = await pos();
    check(p.thSame && p.thOpen, `${tag}: the conversation is the same open element (not exchanged)`);
    check(Math.abs(p.sum - p0.sum) <= 1, `${tag}: the conversation loading again keeps History where it was (${p0.sum} -> ${p.sum})`);
    // a new job starts while the page is scrolled: the reading position stays
    const NJ = (await v1('POST', '/agent/jobs', {title: 'Garden job 7', user_id: ME.id, log: 'started'})).id;
    await ev(`(loadJobs(), 1)`);
    check(await wait(`!!document.getElementById('job-${NJ}')`), `${tag}: the new job is drawn`);
    await settled();
    p = await pos();
    check(Math.abs(p.sum - p0.sum) <= 1 && Math.abs(p.next - p0.next) <= 1, `${tag}: a new job on top keeps the reading position (${p0.sum} -> ${p.sum})`);
    check((await order())[0] === NJ, `${tag}: the new job is on top`);
    await shot(`p5223-${tag}-after.png`);
    await v1('PATCH', `/agent/jobs/${NJ}`, {state: 'done'});
  }, true);
  await run(320, 640);
  await run(460, 800);
  console.log(`p5223_agenten_ruhe_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
