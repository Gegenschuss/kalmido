// kalmido-suite: fresh
// 2.392.0 D (#3369) UI tests, own container (start.sh): the view "Waiting for me" (jsdom). The sidebar row appears only while
// something waits, the view groups by kind, a row leads to its task, a job keeps its buttons, the Today card links to the view,
// the empty state is plain. A person without an organisation (freelancer-matrix: tasks).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, ...(ck ? {Cookie: ck} : {})}, body: body === undefined ? undefined : JSON.stringify(body)}); if (!r.ok) console.log('call failed', method, url, r.status, await r.text()); try { return await r.clone().json(); } catch { return {}; } };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return null; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', email: 'alice@example.com'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');  // freelancer-matrix: tasks
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Release', kind: 'project', ptype: 'software'})).id;
  const me = (await call('GET', '/api/state')).me?.id;
  const ag = await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Frida bot', scopes: ['read', 'tasks:write', 'comments']});
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const AH = {Authorization: 'Bearer ' + (await call('POST', `/api/my/agents/${ag.id}/token`)).token};
  const T = (await call('POST', '/api/tasks', {title: 'Check the invoice', list_id: L})).id;

  const w = await boot({user: 'frida', hash: 'mine_wait'}), d = w.document;
  await until(() => w.eval(`S.mw.items !== null`)); await idle(w);
  check(/Nothing waits for you/.test(d.querySelector('#view').textContent), 'the empty state');
  check(/Waiting for me/.test(d.querySelector('#side, .side, body').textContent), 'on the view its row stays in the sidebar');
  w.eval(`go('today')`); await idle(w);
  check(!d.querySelector('[data-go="mine_wait"]'), 'nothing waits: no row in the sidebar');
  check(!d.querySelector('.waitcard'), 'nothing waits: no card in Today');

  await call('POST', `/api/tasks/${T}/review`, {action: 'request', reviewer_id: me});
  await call('POST', `/api/v1/tasks/${T}/comments`, {body: 'May I?', approval: {title: 'Publish the page'}}, null, AH);
  await w.eval(`mwLoad(true)`); await idle(w);
  check(w.eval(`mwCount()`) === 2, 'two things wait');
  check(!!(await until(() => d.querySelector('[data-go="mine_wait"]'))), 'the sidebar row appears');
  const link = await until(() => d.querySelector('.waitcard a[href="#mine_wait"]'));
  check(link && /2 things wait for you/.test(link.textContent), 'the Today card links to the view, no list of its own');

  await call('POST', '/api/v1/agent/jobs', {title: 'Confirm the cut', task_id: T, state: 'waiting'}, null, AH);
  await w.eval(`mwLoad(true)`); w.eval(`go('mine_wait')`); await idle(w);
  const secs = await until(() => { const s = [...d.querySelectorAll('.mwg h3')].map(x => x.textContent); return s.length >= 3 ? s : null; });
  check(secs && /Approvals/.test(secs.join()) && /Reviews/.test(secs.join()) && /Jobs/.test(secs.join()), 'grouped by kind ' + JSON.stringify(secs));
  const a = [...d.querySelectorAll('.mwg a.mwa')].find(x => /Publish the page/.test(x.textContent));
  check(a && a.getAttribute('href') === `#t/${T}`, 'a row leads to its task');
  check(/Release/.test(a?.textContent || ''), 'the row names its project');
  check(!!d.querySelector('.mwg [data-act="job-do"][data-a="approve"]'), 'a waiting job keeps its buttons');
  check(!/e2e1:/.test(d.querySelector('#view').textContent), 'no cipher shown');

  console.log(`p2392_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
