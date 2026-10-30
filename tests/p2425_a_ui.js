// kalmido-suite: fresh
// 2.425.0 UI tests, part A (#3575), own container (start.sh), jsdom: a job's history is open on the agents page, the chat
// window is open and its box has the focus with typed text and a selection. A new step of the job (and the chat that loads
// again) redraws the list and the history but never takes the focus: the box keeps it, its text and its selection - also
// when the chat window itself is drawn again. Only the own click on "History" puts the focus on the row.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
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
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Release', list_id: L})).id;
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();
  const job = await v1('POST', '/agent/jobs', {title: 'Release 2.425', task_id: T, user_id: ME.id, log: 'started'});
  await v1('PATCH', `/agent/jobs/${job.id}`, {append_log: 'Build'});
  await v1('POST', '/agent/progress', {text: 'Compiling the server', job_id: job.id});
  await v1('POST', '/agent/chats/' + ME.id, {body: 'Hello Alice'});

  const w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  w.eval("S.jobs.f = 'all'; loadJobs()");
  const row = () => [...d.querySelectorAll('.jobs .job')].find(j => /Release 2.425/.test(j.textContent));
  await until(() => row()?.querySelector('details.jobv summary'));
  // the own click on History: the focus goes to the row (stays as it was)
  click(w, row()?.querySelector('details.jobv summary'));
  await until(() => d.querySelector('.jobs details.jobv[open] .jvh'));
  await until(() => d.activeElement?.matches?.('details.jobv > summary'));
  check(d.activeElement?.matches?.('details.jobv > summary'), '#3575: the own click on History puts the focus on the row');
  // the chat window with typed text and a selection in its box
  w.eval(`chatOpen(${AG})`);
  await until(() => d.querySelector('#achat #chat-in'));
  const typed = () => { const ci = d.querySelector('#chat-in'); ci.value = 'Please check the'; ci.focus(); ci.setSelectionRange(7, 12); return ci; };
  typed();
  check(d.activeElement?.id === 'chat-in', '#3575: the chat box has the focus');
  const kept = () => { const a = d.activeElement; return a?.id === 'chat-in' && a.value === 'Please check the' && a.selectionStart === 7 && a.selectionEnd === 12; };
  // a new step arrives: history and list redraw, the chat loads again
  await v1('POST', '/agent/progress', {text: 'Running the suites', job_id: job.id});
  w.eval('stepsChanged(); 1');
  await until(() => /Running the suites/.test(d.querySelector('.jobs details.jobv[open]')?.textContent || ''));
  check(/Running the suites/.test(d.querySelector('.jobs details.jobv[open]')?.textContent || ''), '#3575: the open history shows the new step');
  await sleep(500);  // the gathered redraw (400 ms) has run
  check(kept(), '#3575: a new step leaves the focus, the text and the selection in the chat box');
  // the chat window drawn again (another job chat key): its box is new, it gets the focus back with the selection
  typed();
  w.eval("document.querySelector('#achat').dataset.jc = 'x'; 1");
  await v1('POST', '/agent/progress', {text: 'All suites green', job_id: job.id});
  w.eval('stepsChanged(); 1');
  await until(() => /All suites green/.test(d.querySelector('.jobs details.jobv[open]')?.textContent || ''));
  await sleep(500);
  check(kept(), '#3575: the chat window drawn again keeps the focus, the text and the selection in its new box');
  // another field (the job filter search, any input outside the history) keeps it too
  const inp = d.createElement('input'); inp.id = 'p3575-probe'; d.body.appendChild(inp); inp.value = 'abc'; inp.focus(); inp.setSelectionRange(1, 2);
  w.eval('jobStepsRedraw(); 1'); await sleep(500);
  check(d.activeElement === inp && inp.selectionStart === 1 && inp.selectionEnd === 2, '#3575: any other field keeps the focus and its selection');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
