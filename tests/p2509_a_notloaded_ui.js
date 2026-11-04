// kalmido-suite: fresh
// 2.509.0 (#4324) UI tests, own container (start.sh): a link #t/<id> to a task that is not in the app's memory (jsdom). A tap on a
// row of "Waiting for me" with a completed task, on a phone and on a Fold (wide): the task is fetched and opened and stays open
// through the next reload, the row stays in the view. No such task / offline: a hint and no panel. A person without an
// organisation (freelancer-matrix: tasks).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle, until: untilT} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2509AU_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, ...(ck ? {Cookie: ck} : {})}, body: body === undefined ? undefined : JSON.stringify(body)}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => untilT(fn, {timeout: 15000, step: 100}).catch(() => null);
const panelShows = (d, title) => { const p = d.querySelector('#detail'); return p && !p.classList.contains('hidden') && p.classList.contains('open') && (p.querySelector('.dtitle, textarea, [data-act="title"]')?.value === title || p.textContent.includes(title)); };
const noPanel = (w, d) => !w.eval('S.sel') && !d.querySelector('#app').classList.contains('detail-open');

async function tapRow(w, d, label, T, title) {
  const a = await until(() => [...d.querySelectorAll('.mwg a.mwa')].find(x => x.getAttribute('href') === `#t/${T}`));
  check(!!a, `${label}: the row of the completed task is in the view`);
  if (!a) return;
  a.click();
  check(!!(await until(() => panelShows(d, title))), `${label}: a tap opens the completed task, the panel is not empty: "${d.querySelector('#detail').textContent.slice(0, 80)}"`);
  await idle(w);
  check(w.eval('S.sel') === T, `${label}: it is the open task`);
  check(!!(await until(() => d.querySelector('#detail').textContent.includes('May I?'))), `${label}: its question can be read and answered in the panel`);
  await w.eval('load().then(render)'); await idle(w);  // the next reload (a change anywhere) keeps it
  check(w.eval('S.sel') === T && panelShows(d, title), `${label}: it stays open after the next reload`);
  w.eval('closeDetail()'); await idle(w);
  check(noPanel(w, d), `${label}: closes as any other task`);
  check(!!(await until(() => [...d.querySelectorAll('.mwg a.mwa')].some(x => x.getAttribute('href') === `#t/${T}`))), `${label}: the row stays in the view`);
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', email: 'alice@example.com'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');  // freelancer-matrix: tasks
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Release', kind: 'project', ptype: 'software'})).id;
  const ag = await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Frida bot', scopes: ['read', 'tasks:write', 'comments']});
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const AH = {Authorization: 'Bearer ' + (await call('POST', `/api/my/agents/${ag.id}/token`)).token};
  const T = (await call('POST', '/api/tasks', {title: 'Roll out the update', list_id: L})).id;
  check((await call('POST', `/api/v1/tasks/${T}/comments`, {body: 'May I?', approval: {title: 'Publish the page'}}, null, AH)).http < 300, 'the agent asks');
  check((await call('POST', `/api/tasks/${T}/complete`, {})).http === 200, 'the task is completed');
  const G = (await call('POST', '/api/tasks', {title: 'Gone later', list_id: L})).id;
  await call('POST', `/api/tasks/${G}/complete`, {});
  // the state carries completed tasks for 14 days (core/state.py): these two were completed long ago
  execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, `UPDATE tasks SET completed_at='2025-01-15T10:00:00+00:00' WHERE id IN (${T},${G})`]);

  for (const [label, mobile] of [['phone', true], ['Fold', false]]) {
    const w = await boot({user: 'frida', mobile, hash: 'mine_wait'}), d = w.document;
    await until(() => w.eval('S.mw.items !== null')); await idle(w);
    check(!w.eval(`!!taskById(${T})`), `${label}: the completed task is not in the app's memory`);
    await tapRow(w, d, label, T, 'Roll out the update');

    // no such task: a hint, no panel
    w.location.hash = '#t/99999999';
    check(!!(await until(() => /Task not found/.test(d.querySelector('#toasts, #toast, body').textContent))), `${label}: an unknown task says so`);
    await idle(w);
    check(noPanel(w, d), `${label}: and leaves no empty panel`);

    // offline: a hint, no panel
    w.eval(`S.extra = null`);
    const real = w.fetch;
    w.fetch = (u, o) => /\/api\/tasks\/\d+/.test(String(u)) ? Promise.reject(new TypeError('network')) : real(u, o);
    w.location.hash = '#t/' + G;
    check(!!(await until(() => /Only available online/.test(d.body.textContent))), `${label}: offline it says so`);
    await idle(w);
    check(noPanel(w, d), `${label}: offline no empty panel`);
    w.fetch = real;
    w.close();
  }

  // the lists come one by one (S.lz, #3136): a completed task of a list still on its way opens as well, its list comes along
  const w = await boot({user: 'frida', hash: 'mine_wait'}), d = w.document;
  await until(() => w.eval('S.mw.items !== null')); await idle(w);
  w.eval(`S.lz = {pending: new Set([${L}]), counts: {}}`);
  w.location.hash = '#t/' + T;
  check(!!(await until(() => panelShows(d, 'Roll out the update'))), 'lists still on their way: the completed task opens');
  check(!!(await until(() => !w.eval(`S.lz?.pending.has(${L})`))), 'and its list has come');
  await idle(w);
  // an edit of the task fetched alone survives the next reload (Fable review): the state brings no copy of it
  await w.eval(`patchTask(${T}, {title: 'Rolled out'})`); await idle(w);
  await w.eval('load().then(render)'); await idle(w);
  check(w.eval(`taskById(${T}).title`) === 'Rolled out' && panelShows(d, 'Rolled out'), 'an edit stays after the next reload');
  // an answer that is no task (no JSON, status 200: rawFetch answers {}): a hint, no loop of requests
  w.eval('closeDetail()'); await idle(w);
  const real = w.fetch; let asked = 0;
  w.fetch = (u, o) => /\/api\/tasks\/\d+/.test(String(u)) ? (asked++, Promise.resolve(new Response('no json', {status: 200, headers: {'Content-Type': 'text/plain'}}))) : real(u, o);
  w.eval(`S.extra = null`); w.location.hash = '#t/' + G;
  check(!!(await until(() => /Task not found/.test(d.body.textContent))), 'no task in the answer: says so');
  await idle(w);
  check(noPanel(w, d), 'no task in the answer: no panel');
  check(asked <= 3, 'no task in the answer: no loop of requests ' + asked);
  w.fetch = real;
  w.eval('closeDetail()'); await idle(w);
  // #4324: the other ways to a task that is not loaded go the same way (time report, saved chat message, full text search)
  w.eval(`S.extra = null; openTaskById(${G})`);
  check(!!(await until(() => panelShows(d, 'Gone later'))), 'openTaskById opens a completed task');
  w.eval('closeDetail()'); await idle(w);
  w.eval(`S.extra = null; chatSaveOpen(${G})`);
  check(!!(await until(() => panelShows(d, 'Gone later'))), 'chatSaveOpen opens a completed task');
  w.eval('closeDetail()'); await idle(w);
  // a task that leaves the state while it is open still closes (2.369.2, #3136): no fetch brings it back
  w.eval(`S.lz = null`);
  const O = (await call('POST', '/api/tasks', {title: 'Open one', list_id: L})).id;
  await w.eval('load().then(render)'); await idle(w);
  w.eval(`openDetail(${O})`); await idle(w);
  check(w.eval('S.sel') === O, 'an open task of the state');
  await call('DELETE', `/api/tasks/${O}`);
  await w.eval('load().then(render)'); await idle(w);
  check(noPanel(w, d), 'deleted elsewhere and gone from the state: the panel closes as before');
  w.close();

  console.log(`p2509_a_notloaded_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
