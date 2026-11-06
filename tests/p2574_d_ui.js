// kalmido-suite: fresh
// 2.574.0 D (#3376, from 2.393.0 D) UI tests, own container (start.sh), jsdom: quick add "!!!!" = Urgent (mark, chip, priority menu),
// the organisation admin's read-only "Tasks of the organisation" (a project the admin is not in, filter, no private one),
// the project dialog's switch "Approvals need two people" with its hint while nobody else is in the project.
// A person without an organisation for the quick add and the switch (freelancer-matrix: tasks).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, ...(body ? {body: JSON.stringify(body)} : {})}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha Studio', admin_id: me})).id;
  const ids = {};
  for (const u of ['bob', 'carl']) ids[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs: [{id: ORG, role: 'member'}]})).id;
  const CARL = ids.carl;
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const LS = (await call('POST', '/api/lists', {name: 'Studio plan', kind: 'project', org_id: ORG})).id;
  const LP = (await call('POST', '/api/lists', {name: 'Bob private', kind: 'project', org_id: null})).id;
  await call('PUT', `/api/lists/${LS}/members`, {user_id: CARL, role: 'edit'});
  await call('PUT', `/api/lists/${LP}/members`, {user_id: CARL, role: 'edit'});
  await call('POST', '/api/tasks', {title: 'Book the studio', list_id: LS, priority: 7});
  await call('POST', '/api/tasks', {title: 'Secret gift', list_id: LP});

  // ================= the organisation admin's read-only view
  CK = AK;
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`otkOpen(${ORG}, 'Alpha Studio')`);
  const row = await until(() => d.querySelector('.otkmd .otkrow'));
  const txt = d.querySelector('.otkmd')?.textContent || '';
  check(row && /Book the studio/.test(row.textContent) && /Studio plan/.test(row.textContent), 'the task of a project alice is not in ' + (row?.textContent || ''));
  check(row && row.querySelector('.prm.p7')?.textContent === '!!!!', 'its priority mark: !!!!');
  check(!/Secret gift/.test(txt) && /Read only/.test(txt), 'no private project; the read-only hint');
  check([...d.querySelectorAll('#otk-l option')].map(o => o.textContent).join('|') === 'All projects|Studio plan', 'the project filter');
  check(!d.querySelector('.otkmd input:not(#otk-q), .otkmd [contenteditable]') && !d.querySelector('.otkmd [data-act]'), 'nothing to edit in it');
  click(w, d.querySelector('[data-otk-st="done"]'));
  await until(() => /No tasks/.test(d.querySelector('#otk-body')?.textContent || ''));
  check(/No tasks/.test(d.querySelector('#otk-body').textContent), 'Completed: none');
  const log = await call('GET', `/api/orgs/${ORG}/lists`);
  check((log.log || []).filter(x => x.action === 'tasksall').length >= 2, 'every look is in the history ' + JSON.stringify(log.log || []).slice(0, 160));
  w.close();

  // ================= quick add and the switch, a person without an organisation
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'agents,comments,collab'});
  const L = (await call('POST', '/api/lists', {name: 'Solo release', kind: 'project', ptype: 'software'})).id;
  w = await boot({user: 'frida', hash: 'l/' + L}); d = w.document;
  check(w.eval(`parseQuick(' Fix login !!!! ').priority`) === 7 && w.eval(`parseQuick(' Fix login !dringend ').priority`) === 7, 'quick add: !!!! and !dringend = 7');
  check(w.eval(`parseQuick(' Fix login !!! ').priority`) === 5, 'quick add: !!! stays High');
  const p = w.eval(`PRIO_ROW(0).row.map(x => x.label).join('|')`);
  check(p.startsWith('Urgent|High'), 'the priority menu starts with Urgent ' + p);
  d.body.insertAdjacentHTML('beforeend', `<div id="t2e">${w.eval(`ow_listRow(listById(${L}), true)`)}</div>`);
  const sw = d.querySelector('#l-2eyes');
  check(sw && !sw.checked && d.querySelector('#l-2eyes-h').hidden, 'the switch, off; no hint');
  sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => !d.querySelector('#l-2eyes-h').hidden);
  check(!d.querySelector('#l-2eyes-h').hidden && /Share the project first/.test(d.querySelector('#l-2eyes-h').textContent), 'alone in the project: the hint');
  check((await until(async () => (await call('GET', '/api/state')).lists.find(x => x.id === L)?.two_eyes)) == 1, 'saved on the server');
  await idle(w);

  console.log(`p2574_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
