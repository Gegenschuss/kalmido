// kalmido-suite: fresh
// 2.609.0 (#3372) UI tests, own container (start.sh): own ticket types in the app (jsdom). Quick add !epic / !<own name>
// takes the own type (and leaves !milestone alone), the row's chip shows the own type's name and an epic's subtask progress,
// the task panel's type select offers the project's types, the project's pick limits it, Settings > Data > Ticket types
// lists the types, switches a suggestion on and asks before deleting a type with tasks (their number).
// A person without an organisation (freelancer-matrix: tasks).
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
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');  // freelancer-matrix: tasks
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'App', tickets: true})).id;
  const ep = await call('POST', '/api/ticket-types', {key: 'epic'});
  const inc = await call('POST', '/api/ticket-types', {name: 'Incident', icon: 'zap', color: '#aa3300'});
  const E = (await call('POST', '/api/tasks', {title: 'Big release', list_id: L, ttype: 'epic'})).id;
  const k1 = (await call('POST', '/api/tasks', {title: 'Part one', list_id: L, parent_id: E})).id;
  await call('POST', '/api/tasks', {title: 'Part two', list_id: L, parent_id: E});
  await call('POST', `/api/tasks/${k1}/complete`, {});
  const I = (await call('POST', '/api/tasks', {title: 'Server down', list_id: L, ttype: 'incident'})).id;
  check(ep.key === 'epic' && inc.key === 'incident', 'setup: two own types ' + JSON.stringify([ep, inc]).slice(0, 160));
  const w = await boot({user: 'frida', hash: 'l/' + L}), d = w.document;
  await until(() => w.eval('(S.ttypes || []).length === 2'));
  w.eval('render()'); await idle(w);
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);

  // ================= the chips: an own type, an epic with its progress
  const ic = await until(() => row(I)?.querySelector('.ttchip'));
  check(ic && ic.textContent.trim() === 'Incident' && /aa3300/i.test(ic.getAttribute('style') || ''), 'own type chip: name and colour ' + (ic?.outerHTML || '').slice(0, 200));
  const ec = row(E)?.querySelector('.ttchip');
  check(ec && /Epic/.test(ec.textContent) && /1\/2/.test(ec.textContent), 'epic chip with its progress ' + (ec?.textContent || ''));
  // ================= quick add
  const pq = s => JSON.parse(w.eval(`JSON.stringify(parseQuick(${JSON.stringify(s)}))`));
  const q1 = pq('Plan the launch !epic tomorrow');
  check(q1.ttype === 'epic' && q1.title === 'Plan the launch', 'quick add: !epic ' + JSON.stringify(q1));
  const q2 = pq('Mail is down !Incident');
  check(q2.ttype === 'incident', 'quick add: !<own name> ' + JSON.stringify(q2));
  const q3 = pq('Ship it !milestone !bug');
  check(q3.ms === 1 && q3.ttype === 'bug', 'quick add: !milestone stays a milestone next to a type ' + JSON.stringify(q3));
  check(pq('Note !story').ttype === undefined, 'quick add: a type that is not switched on stays text');
  // ================= the task panel: the project's types, the epic's progress
  w.eval(`openDetail(${E})`); await until(() => w.eval(`S.tl.id === ${E}`)); await idle(w);
  const sel = await until(() => d.querySelector('#d-ttype'));
  check(sel && [...sel.options].map(o => o.value).join(',') === ',bug,feature,task,epic,incident', 'type select: built-in + own ' + (sel ? [...sel.options].map(o => o.value) : ''));
  check(/1 of 2 subtasks done/.test(d.querySelector('.ttepic')?.textContent || ''), 'the epic shows its progress in the panel');
  await call('PATCH', `/api/lists/${L}`, {ttypes: ['bug', 'epic']});
  w.eval(`listById(${L}).ttypes = '["bug","epic"]'; renderDetail()`); await idle(w);
  const sel2 = await until(() => d.querySelector('#d-ttype')?.options.length === 3 && d.querySelector('#d-ttype'));
  check(sel2 && [...sel2.options].map(o => o.value).join(',') === ',bug,epic', 'type select: only what the project picked ' + (sel2 ? [...sel2.options].map(o => o.value) : ''));
  // ================= the project dialog: the pick
  w.eval(`ticketTplModal(${L})`);
  const picks = await until(() => d.querySelectorAll('[data-ttk]').length && d.querySelectorAll('[data-ttk]'));
  check(picks && [...picks].filter(x => x.checked).map(x => x.dataset.ttk).join(',') === 'bug,epic', 'project dialog: the pick ticked');
  check(!!d.querySelector('[data-tpl="epic"]'), 'project dialog: a template of the epic too');
  click(w, d.querySelector('.ttmodal [data-m="close"]'));
  // ================= Settings > Data > Ticket types
  w.eval(`settingsModal('data')`);
  const rows = await until(() => d.querySelectorAll('#s-tty .ttyrow').length === 2 && d.querySelectorAll('#s-tty .ttyrow'));
  check(!!rows, 'settings: the two own types');
  const sug = await until(() => d.querySelector('[data-tty-sug="story"]'));
  check(!!sug && !d.querySelector('[data-tty-sug="epic"]'), 'settings: story still a suggestion, epic not');
  click(w, sug);
  await until(() => d.querySelectorAll('#s-tty .ttyrow').length === 3);
  check(d.querySelectorAll('#s-tty .ttyrow').length === 3, 'settings: story switched on');
  click(w, d.querySelector(`[data-tty-del="${inc.id}"]`));
  const q = await until(() => d.querySelector('#cdlg-b'));
  check(q && /1 task will have no type/.test(q.textContent), 'settings: delete asks with the number of tasks ' + (q?.textContent || ''));
  click(w, d.querySelector('[data-cd="yes"]'));
  await until(() => d.querySelectorAll('#s-tty .ttyrow').length === 2);
  const t = await call('GET', `/api/tasks/${I}`);
  check(t.ttype === '', 'after the question the task has no type ' + t.ttype);

  console.log(`p2609_c_ttypes_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
