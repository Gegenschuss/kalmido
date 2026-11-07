#!/usr/bin/env node
// kalmido-suite: fresh
// 2.653.0 A UI tests (#5079, own container, start.sh). jsdom, the dialog "Work style and notifications" > History:
// - lines in words: never a method or an API path ("Changed PATCH /api/v1/tasks/4501" before), a task change names its title
//   and its field ("Title changed: ..."), a decision the agent wrote itself reads "Decided: ..."
// - like steps in a row (same kind, same project, at most 5 minutes apart) are one line "N tasks created in <project>"
//   that opens to the single steps, each with its own Undo
// - the dialog shows at most 5 lines (a group counts as one) and "Show whole history"; that view lists all lines in groups
// - the same for a person without an organisation (freelancer-matrix: agents)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_AGENT_CONTROL_NEW: 'free'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body, tok, hd = {}) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok, ...hd}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const dbx = (sql, args) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args || [])]).toString() || '[]');

async function dialog(user, id) {
  const w = await boot({user, hash: 'agents'}), d = w.document;
  await until(() => d.querySelector('.agcard'));
  w.eval(`awOpen({id: ${id}, name: 'Bot'})`);
  const md = await until(() => lastModal(d)?.classList.contains('awdlg') && lastModal(d)?.querySelector('.awch .mrow') && lastModal(d));
  return {w, d, md};
}

async function scenario(tag, user, ag, lid) {
  const T = ` (${tag})`;
  // newest first: a rename, three decisions days apart, seven creations in a row (one group), a line from before 2.653.0
  dbx("INSERT INTO agent_decisions(agent_id,list_id,step,level,kind,method,path,title,via,created_at) VALUES(?,?,'change','free','other','PATCH','/api/v1/tasks/999999','','self','2026-09-01T08:00:00+00:00')", [ag.id, lid]);
  const ids = [];
  for (let i = 1; i <= 7; i++) { const r = await v1('POST', '/tasks', {title: `Batch task ${i}`, list_id: lid}, ag.token); ids.push(r.id); }
  check(ids.every(Boolean), 'the agent created seven tasks' + T);
  const DEC = ['Answered the job card myself', 'Did not start the nightly build', 'Changed the tick-off message'];
  for (const [i, x] of DEC.entries()) {
    const d = await v1('POST', '/agent/decisions', {title: x}, ag.token);
    check(d.status === 201, 'a decision line ' + d.status + T);
    dbx('UPDATE agent_decisions SET created_at=? WHERE id=?', [`2026-10-0${2 + i}T08:00:00+00:00`, d.id]);  // days apart: single lines
  }
  dbx('UPDATE tasks SET locked=0 WHERE id=?', [ids[0]]);  // the agent's own tasks start locked (#1118); the lock is not the point here
  const t = await v1('GET', `/tasks/${ids[0]}`, null, ag.token);
  const r = await v1('PATCH', `/tasks/${ids[0]}`, {title: 'Renamed by the agent'}, ag.token, {'If-Match': t.updated_at});
  check(r.status === 200, 'the agent renames a task ' + r.status + T);

  let {w, md} = await dialog(user, ag.id);
  check(md, 'the history is drawn' + T);
  if (!md) { w.close(); return; }
  const box = md.querySelector('.awch');
  const text = md.querySelector('#aw-control').textContent;
  check(!/\/api\/v1|PATCH|POST /.test(text), 'no method or API path in the dialog: ' + text.slice(-400) + T);
  const top = [...box.children];
  check(top.length === 5, 'the dialog shows 5 lines (groups count as one): ' + top.length + T);
  check(/Title changed: Renamed by the agent/.test(top[0]?.textContent || ''), 'the newest line names the field and the title: ' + top[0]?.textContent + T);
  const grp = box.querySelector('details.awcg');
  check(grp && /7 tasks created in /.test(grp.querySelector('summary').textContent), 'seven creations are one line: ' + grp?.querySelector('summary').textContent + T);
  if (grp) {
    grp.open = true;
    const rows = grp.querySelectorAll('.awcgl .mrow');
    check(rows.length === 7 && [...rows].every(x => x.querySelector('[data-awc-undo]')), 'the group opens to its 7 steps, each with Undo' + T);
    const undo = rows[0]?.querySelector('[data-awc-undo]');
    if (undo) {
      click(w, undo);
      check(await until(() => [...md.querySelectorAll('.awch details.awcg .awcgl .mrow')].some(x => /undone/.test(x.textContent))), 'one step of the group is undone, the others stay' + T);
    }
  }
  check(/Decided: Changed the tick-off message/.test(box.textContent), 'a decision reads "Decided: ..."' + T);
  const all = md.querySelector('[data-awc-all]');
  check(all && /Show whole history/.test(all.textContent), 'the link "Show whole history" below' + T);
  if (all) {
    click(w, all);
    const sub = await until(() => lastModal(w.document)?.classList.contains('awcalldlg') && lastModal(w.document).querySelector('.awcall .mrow') && lastModal(w.document));
    check(sub, 'the view "Whole history" opens' + T);
    if (sub) {
      const st = sub.querySelector('.awcall').textContent;
      check(/Decided: Answered the job card myself/.test(st) && /Task changed/.test(st) && /7 tasks created in /.test(st), 'the whole history has every line, in groups: ' + st.slice(0, 300) + T);
      check(!/\/api\/v1|PATCH /.test(st), 'no method or path in the whole history either' + T);
      check(md.style.display === 'none', 'the settings step aside while it is open' + T);
      click(w, sub.querySelector('[data-m="close"]'));
      check(await until(() => !sub.isConnected && md.style.display === ''), '"Done" goes back to the settings' + T);
    }
  }
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

  await scenario('organisation', 'alice', PA, AL);
  await scenario('without organisation', 'frida', FA, FL);
  console.log(`p2653_a_agentlog_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
