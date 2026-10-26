// 2.235.0 A UI tests (#2891 #2900 #2901, own container, start.sh). jsdom:
// - the dialog "Work style and notifications" shows the section Control on top: a new agent has "Approve everything" chosen
// - picking a level / adding an own one-way step / a deadline -> PATCH /api/agents/<id>/control with ONLY that key; after a
//   reload the values are there; the four fixed one-way steps are ticked and locked; "After the deadline" only with a deadline
// - the goal field only on "Free run with a goal"
// - the history lists the agent's decision; Undo takes it back (the task goes to the trash)
// - an agent from before 2.235.0 shows "No level chosen yet - works as before."
// - 2.235.0 A2 (#2891): the approval card shows its step (bound method, path, body), one-way and the recommendation
// - the same for a person without an organisation (freelancer-matrix: agents)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
// the real default for new agents (tests/start.sh starts other suites with legacy = no level)
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_AGENT_CONTROL_NEW: 'approve_all'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body, tok) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const dbx = (sql, args) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args || [])]).toString() || '[]');

async function dialog(user, id) {
  const w = await boot({user, hash: 'agents'}), d = w.document;
  await until(() => d.querySelector('.agcard'));
  w.eval(`window.__ao = api; api = function(m, u, b) { if (/\\/control$/.test(u) && m === 'PATCH') window.__sent.push(JSON.stringify(b)); return window.__ao.apply(this, arguments); }; window.__sent = [];`);
  w.eval(`awOpen({id: ${id}, name: 'Bot'})`);
  const md = await until(() => lastModal(d)?.classList.contains('awdlg') && lastModal(d)?.querySelector('#aw-control h4') && lastModal(d));
  return {w, d, md};
}

async function scenario(tag, user, ag, ck, lid) {
  const T = ` (${tag})`;
  let {w, md} = await dialog(user, ag.id);
  check(md, 'the section Control is drawn' + T);
  if (!md) { w.close(); return; }
  check(md.querySelector('[data-awc="level"][value="approve_all"]').checked, 'a new agent: "Approve everything" chosen' + T);
  check(md.querySelectorAll('.awco input[disabled][checked]').length === 4, 'the four fixed one-way steps, ticked and locked' + T);
  check(md.querySelector('#awc-goal').closest('.awsub').hidden, 'no goal field on approve_all' + T);
  check(md.querySelector('#awc-then').closest('.row').hidden, 'no "after the deadline" without a deadline' + T);
  const routine = md.querySelector('[data-awc="level"][value="routine"]'); routine.checked = true; change(w, routine);
  check(await until(() => w.__sent.length === 1), 'one PATCH' + T);
  check(w.__sent[0] === '{"level":"routine"}', 'only the level: ' + w.__sent[0] + T);
  check(await until(() => md.querySelector('.svtick')), 'the quiet tick' + T);
  const free = md.querySelector('[data-awc="level"][value="free"]'); free.checked = true; change(w, free);
  check(await until(() => md.querySelector('#awc-goal') && !md.querySelector('#awc-goal').closest('.awsub').hidden), 'the goal field appears on free' + T);
  const goal = md.querySelector('#awc-goal'); goal.value = 'keep it tidy'; change(w, goal);
  await until(() => w.__sent.length === 3);
  md.querySelector('#awc-now').value = 'send invoices'; click(w, md.querySelector('[data-awc-addow]'));
  check(await until(() => [...md.querySelectorAll('.awco .mrow')].some(r => /send invoices/.test(r.textContent))), 'the own one-way step is listed' + T);
  const dl = md.querySelector('#awc-deadline'); dl.value = '4h'; change(w, dl);
  check(await until(() => md.querySelector('#awc-then') && !md.querySelector('#awc-then').closest('.row').hidden), '"after the deadline" appears' + T);
  const srv = await until(async () => { const c = (await call('GET', `/api/agents/${ag.id}/control`, null, ck)).control; return c && c.level === 'free' && c.goal === 'keep it tidy' && c.one_way[0] === 'send invoices' && c.deadline === '4h' && c; }, 60);
  check(srv, 'all values are on the server ' + JSON.stringify(srv) + T);
  check(w.__sent.every(x => Object.keys(JSON.parse(x)).length === 1), 'every PATCH carried one key' + T);
  // 2.235.0 A2 (#2891): the approval card names the bound step, one-way and the agent's recommendation
  const hd = typeof w.ccApvHead === 'function' ? w.ccApvHead({title: 'x', step: {method: 'POST', path: '/api/v1/tasks/batch', body: {action: 'delete', ids: [1, 2, 3]}}, one_way: true, recommend: 'no'}, true) : '';
  check(/Step: 3 tasks, action delete/.test(hd) && /data-apv-oneway/.test(hd) && /recommends: No/.test(hd), 'the card shows step, one-way and the recommendation: ' + hd + T);
  const hd2 = typeof w.ccApvHead === 'function' ? w.ccApvHead({title: 'x', step: {method: 'DELETE', path: '/api/v1/tasks/345'}}, true) : '';
  check(/Step: Delete task 345/.test(hd2) && !/data-apv-oneway/.test(hd2), 'a delete step reads as words: ' + hd2 + T);
  w.close();
  // the agent decides itself (free), the history shows it with Undo
  const r = await v1('POST', '/tasks', {title: 'Made by the agent', list_id: lid}, ag.token);
  check(r.status === 201, 'the agent creates a task on free ' + r.status + T);
  ({w, md} = await dialog(user, ag.id));
  check(md && md.querySelector('[data-awc="level"][value="free"]').checked && md.querySelector('#awc-goal').value === 'keep it tidy' && md.querySelector('#awc-deadline').value === '4h', 'the values are there after a reload' + T);
  const undo = await until(() => [...md.querySelectorAll('.awch .mrow')].find(x => /Made by the agent/.test(x.textContent))?.querySelector('[data-awc-undo]'));
  check(undo, 'the history line has Undo' + T);
  if (undo) {
    click(w, undo);
    check(await until(() => [...md.querySelectorAll('.awch .mrow')].some(x => /Made by the agent/.test(x.textContent) && /taken back/.test(x.textContent))), 'the line says taken back' + T);
    check(await until(() => (dbx('SELECT deleted_at FROM tasks WHERE id=?', [r.id])[0] || {}).deleted_at), 'the task is in the trash' + T);
  }
  w.close();
  // an agent from before 2.235.0
  dbx("UPDATE agents SET control='' WHERE user_id=?", [ag.id]);
  ({w, md} = await dialog(user, ag.id));
  check(md && md.querySelector('[data-awc-legacy]') && /works as before/.test(md.querySelector('[data-awc-legacy]').textContent), 'legacy: "No level chosen yet"' + T);
  check(md && ![...md.querySelectorAll('[data-awc="level"]')].some(x => x.checked), 'legacy: no level ticked' + T);
  w.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 3});
  const PA = await call('POST', '/api/my/agents', {username: 'deskbot', display_name: 'Deskbot'});
  const AL = (await call('POST', '/api/lists', {name: 'Alice desk'})).id;
  await call('PUT', `/api/lists/${AL}/members`, {user_id: PA.id, role: 'edit'});
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.status < 300, 'a person without an organisation ' + fr.status);
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'}, FK);
  const FA = await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Fridabot'}, FK);
  const FL = (await call('POST', '/api/lists', {name: 'Frida desk'}, FK)).id;
  await call('PUT', `/api/lists/${FL}/members`, {user_id: FA.id, role: 'edit'}, FK);
  check(FA.id && FA.token, 'the freelancer has an own agent');

  await scenario('organisation', 'alice', PA, CK, AL);
  await scenario('without organisation', 'frida', FA, FK, FL);
  console.log(`p2235_a_control_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
