// 2.37.0 UI tests, part U3, own container (start.sh), jsdom:
// - #1161 Agents > Jobs > Open: a job that ends leaves the list without a reload: (1) the plain case, the change check
//   picks it up; (2) an older answer of the jobs list that arrives late (a phone that slept in the middle of a request)
//   does not bring the ended job back; (3) back in front while a field has the focus: the list is fetched again
//   (visibilitychange, pageshow from the back/forward cache)
// - #1165 "Copy" in the menu of every chat message (agent chat and team chat): the Markdown text, an answer the agent
//   split into parts ("… _(Part 1/3)_") as one text, mentions as @Name; without navigator.clipboard the old way
//   (execCommand), both blocked: "Copy failed, select the text by hand"
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };
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
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CKB);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();
  const mkJob = async t => (await v1('POST', '/agent/jobs', {title: t, user_id: ME.id, log: 'started'})).id;

  // ================= #1161 the jobs list follows the end of a job
  const J1 = await mkJob('Release build'), J2 = await mkJob('Audit'), J3 = await mkJob('Full test run'), J4 = await mkJob('Migration');
  check(J1 > 0 && J4 > 0, '#1161: four running jobs');
  let w = await boot({hash: 'agents'}), d = w.document;
  const shown = id => !!d.querySelector(`.jobs #job-${id}`);
  await until(() => [J1, J2, J3, J4].every(shown));
  check([J1, J2, J3, J4].every(shown) && d.querySelector('[data-act="jobs-f"][data-f="open"].on'), '#1161: Agents > Jobs > Open lists the running jobs');
  // (1) plain: the job ends, the change check (every 4 s) brings the list up to date
  await v1('PATCH', `/agent/jobs/${J1}`, {state: 'done', append_log: 'done'});
  await until(() => !shown(J1), 60, 200);
  check(!shown(J1) && shown(J2), '#1161: a finished job leaves "Open" without a reload');
  // (2) a late answer that was asked for while the job still ran must not bring it back
  w.eval(`window.__slow = 0; window.__slowDone = null; { const __api = api; api = async (m, u, b) => {
      if (window.__slow && m === 'GET' && u === '/api/agents/jobs?state=open') { window.__slow = 0; let done; window.__slowDone = new Promise(r => { done = r; });
        const j = await __api(m, u, b); await new Promise(r => setTimeout(r, 2500)); setTimeout(done, 0); return j; }
      return __api(m, u, b); }; }`);
  w.eval('window.__slow = 1; loadJobs()');  // asked while J2 still runs, answered 2.5 s later
  await sleep(300);
  await v1('PATCH', `/agent/jobs/${J2}`, {state: 'done'});
  w.eval('loadJobs()');  // a newer request (the change check / coming back) answers first
  await until(() => !shown(J2), 20, 100);
  check(!shown(J2), '#1161: the newer answer removes the job');
  await w.eval('window.__slowDone');
  await sleep(100);
  check(!shown(J2) && shown(J3), '#1161: the older answer that arrives late does not bring the finished job back');
  // (3) in the background (no change check), ended, back in front while a field has the focus
  w.__hid = true;
  Object.defineProperty(d, 'hidden', {configurable: true, get: () => w.__hid});
  Object.defineProperty(d, 'visibilityState', {configurable: true, get: () => (w.__hid ? 'hidden' : 'visible')});
  d.dispatchEvent(new w.Event('visibilitychange'));
  await v1('PATCH', `/agent/jobs/${J3}`, {state: 'failed'});
  await sleep(4500);
  check(shown(J3), '#1161: in the background nothing is fetched (set-up)');
  const inp = d.createElement('input'); inp.id = 'p2370j-field'; d.body.appendChild(inp); inp.focus();
  check(w.eval('editing()'), '#1161: a field has the focus (set-up) ' + d.activeElement?.id);
  w.__hid = false; d.dispatchEvent(new w.Event('visibilitychange'));
  await until(() => !shown(J3), 20, 100);
  check(!shown(J3) && shown(J4), '#1161: back in front with a focused field: the jobs list is fetched again');
  check(d.activeElement === inp, '#1161: the focused field keeps its focus');
  // pageshow from the back/forward cache
  w.__hid = true; d.dispatchEvent(new w.Event('visibilitychange'));
  await v1('PATCH', `/agent/jobs/${J4}`, {state: 'stopped'});
  w.__hid = false;
  const ps = new w.Event('pageshow'); Object.defineProperty(ps, 'persisted', {value: true}); w.dispatchEvent(ps);
  await until(() => !shown(J4), 20, 100);
  check(!shown(J4) && /No running or waiting jobs/.test(d.querySelector('.jobs')?.textContent || ''), '#1161: pageshow (back/forward cache) fetches the list again');
  w.close();

  // ================= #1165 copy a whole message
  const say = (body, extra = {}) => v1('POST', `/agent/chats/${ME.id}`, {body, ...extra});
  const one = await say('# Plan\n\nThe **whole** plan:\n\n- one\n- `two`');
  const P = ['Part one of the answer.\n\n```bash\necho a\n```\n\n_(Teil 1/3)_', 'Part two.\n\n_(Teil 2/3)_', 'Part three, the end.\n\n_(Teil 3/3)_'];
  const parts = []; for (const b of P) parts.push(await say(b));
  w = await boot({hash: 'today'}); d = w.document;
  w.eval(`window.__toasts = []; { const __t = toast; toast = (m, ...a) => { window.__toasts.push(String(m)); return __t(m, ...a); }; }`);
  w.__clip = [];
  Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: t => { w.__clip.push(t); return Promise.resolve(); }}});
  w.eval(`chatOpen(${AG})`);
  const cm = id => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  await until(() => cm(one.id) && cm(parts[2].id));
  const pick = async (sel, label) => {
    d.querySelector(sel).click();
    await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].length);
    const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
    const it = items.find(b => b.querySelector('.ml')?.textContent === label);
    if (it) it.click();
    return items.map(b => b.querySelector('.ml')?.textContent);
  };
  // 2.41.0 (#1374): "Copy" now copies with formatting (p2410_e_ui); the Markdown text is "Copy as Markdown"
  let labels = await pick(`#chat-msgs .cmsg[data-mid="a:${one.id}"] [data-act="chat-msg-menu"]`, 'Copy as Markdown');
  check(labels.includes('Copy') && labels.includes('Copy as Markdown') && labels.includes('Save as task'), '#1165: "Copy" next to "Save as task" in the message menu ' + JSON.stringify(labels));
  await until(() => w.__clip.length);
  check(w.__clip[0] === '# Plan\n\nThe **whole** plan:\n\n- one\n- `two`', '#1165: the Markdown text is copied ' + JSON.stringify(w.__clip));
  await until(() => w.__toasts.includes('Copied'));
  check(w.__toasts.includes('Copied'), '#1165: "Copied" ' + JSON.stringify(w.__toasts));
  // a split answer, from its middle part
  await pick(`#chat-msgs .cmsg[data-mid="a:${parts[1].id}"] [data-act="chat-msg-menu"]`, 'Copy as Markdown');
  await until(() => w.__clip.length > 1);
  check(w.__clip[1] === 'Part one of the answer.\n\n```bash\necho a\n```\n\nPart two.\n\nPart three, the end.', '#1165: an answer in three parts is copied as one text ' + JSON.stringify(w.__clip[1]));
  await until(() => w.__toasts.includes('Copied (3 parts)'));
  check(w.__toasts.includes('Copied (3 parts)'), '#1165: the toast names the parts ' + JSON.stringify(w.__toasts));
  // without navigator.clipboard (an http address): the old way
  Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: undefined});
  w.__exec = null; d.execCommand = c => { w.__exec = c === 'copy' ? d.activeElement?.value : null; return c === 'copy'; };
  await pick(`#chat-msgs .cmsg[data-mid="a:${one.id}"] [data-act="chat-msg-menu"]`, 'Copy as Markdown');
  await until(() => w.__exec);
  check(w.__exec === '# Plan\n\nThe **whole** plan:\n\n- one\n- `two`' && !d.querySelector('textarea.cliptmp'), '#1165: without navigator.clipboard the old way copies the same text ' + JSON.stringify(w.__exec));
  // both blocked
  w.__toasts.length = 0; d.execCommand = () => false;
  await pick(`#chat-msgs .cmsg[data-mid="a:${one.id}"] [data-act="chat-msg-menu"]`, 'Copy as Markdown');
  await until(() => w.__toasts.length);
  check(w.__toasts.includes('Copy failed, select the text by hand'), '#1165: blocked: "Copy failed, select the text by hand" ' + JSON.stringify(w.__toasts));
  w.close();

  // ---- team chat: Bob's message with a mention of Alice
  const RID = ((await call('GET', '/api/team')).rooms || []).find(x => x.kind === 'list' && x.list_id === L)?.id;
  const tm = await call('POST', `/api/team/rooms/${RID}/messages`, {body: `Hi <@${ME.id}>, the **minutes**:\n\n- decided A`}, CKB);
  check(RID && tm.id, '#1165: Bob writes in the channel ' + JSON.stringify(tm).slice(0, 120));
  w = await boot({hash: 'team/' + RID}); d = w.document;
  w.eval(`window.__toasts = []; { const __t = toast; toast = (m, ...a) => { window.__toasts.push(String(m)); return __t(m, ...a); }; }`);
  w.__clip = [];
  Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: t => { w.__clip.push(t); return Promise.resolve(); }}});
  await until(() => d.querySelector(`#tc-msgs [data-mid="t:${tm.id}"] [data-act="tc-msg-menu"]`));
  labels = await pick(`#tc-msgs [data-mid="t:${tm.id}"] [data-act="tc-msg-menu"]`, 'Copy as Markdown');  // 2.41.0 (#1374)
  check(labels.includes('Copy') && labels.includes('Copy as Markdown') && labels.includes('Save as task'), '#1165: team chat: "Copy" in the same menu ' + JSON.stringify(labels));
  await until(() => w.__clip.length);
  check(w.__clip[0] === 'Hi @Alice, the **minutes**:\n\n- decided A', '#1165: team chat: the text with @Name ' + JSON.stringify(w.__clip));
  await until(() => w.__toasts.includes('Copied'));
  check(w.__toasts.includes('Copied'), '#1165: team chat: "Copied"');
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
