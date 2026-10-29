// kalmido-suite:
// 2.390.0 B (#3355) UI tests (own container, start.sh), jsdom: a saved filter knows assignee, column, sprint, milestone and text.
// - the filter dialog offers Assignee (Me, Nobody), Column (the project's columns, No column), Sprint (Current sprint, Backlog),
//   Milestone (the milestones, No milestone) and a text field; the count follows a choice and the typed text
// - filterMatch: who me / none, a column / none, the active sprint / backlog, a milestone / none, text in title or notes
//   (any case); saving keeps the new rules
// freelancer-matrix: tasks (a person without an organisation, the own project)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P23900B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'setup: frida has no organisation');
  const ME = st0.me.id;
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'kanban', 'progress', 'collab'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const L = (await call('POST', '/api/lists', {name: 'Product', kind: 'project'})).id;
  const S1 = (await call('PUT', `/api/lists/${L}/sprint-settings`, {on: true})).started_id;
  const SEC = (await call('POST', '/api/sections', {list_id: L, name: 'Doing'})).id;
  const mk = b => call('POST', '/api/tasks', {list_id: L, ...b}).then(j => j.id);
  const M = await mk({title: 'Release one', ms: 1, due: '2026-12-01'});
  const A = await mk({title: 'Alpha login crash', assignee_id: ME, section_id: SEC, sprint_id: S1});
  const Bt = await mk({title: 'Beta export', content: 'about the CSV Crash'});
  const C = await mk({title: 'Gamma', milestone_id: M});
  check(S1 && SEC && M && A && Bt && C, `setup: sprint ${S1}, column ${SEC}, tasks ${[M, A, Bt, C]}`);

  const w = await boot({user: 'frida', hash: 'today'}), d = w.document;
  check(await until(() => typeof w.filterModal === 'function' && w.taskById(A)), 'the app is there');
  const m = (id, r) => w.eval(`filterMatch(taskById(${id}), ${JSON.stringify(r)})`);
  // the matcher
  check(m(A, {who: ['me']}) && !m(Bt, {who: ['me']}) && m(Bt, {who: ['none']}) && !m(A, {who: ['none']}), 'assignee: me / nobody');
  check(m(A, {who: [String(ME)]}), 'assignee: a person id');
  check(m(A, {secs: [String(SEC)]}) && !m(Bt, {secs: [String(SEC)]}) && m(Bt, {secs: ['none']}), 'column: Doing / no column');
  check(m(A, {sprints: ['cur']}) && !m(Bt, {sprints: ['cur']}) && m(Bt, {sprints: ['none']}) && !m(A, {sprints: ['none']}), 'sprint: current / backlog');
  check(m(C, {ms: [String(M)]}) && !m(A, {ms: [String(M)]}) && m(A, {ms: ['none']}) && !m(C, {ms: ['none']}), 'milestone: one / none');
  check(m(A, {text: 'CRASH'}) && m(Bt, {text: 'crash'}) && !m(C, {text: 'crash'}), 'text: title or notes, any case');
  check(m(A, {who: ['me'], text: 'crash'}) && !m(Bt, {who: ['me'], text: 'crash'}) && m(Bt, {op: 'or', who: ['me'], text: 'crash'}), 'AND / OR with the new rules');
  check(m(C, {}) && m(C, {who: [], text: '  '}), 'empty rules match everything');

  // the dialog
  w.eval('filterModal()');
  const md = await until(() => d.querySelector('.modal #f-text') && d.querySelector('.modal'));
  const vals = k => [...md.querySelectorAll(`.fchips[data-key="${k}"] button`)].map(b => b.dataset.v);
  check(vals('who').join(',') === 'me,none', `Assignee chips ${vals('who')}`);
  check(vals('secs').includes(String(SEC)) && vals('secs').at(-1) === 'none', `Column chips ${vals('secs')}`);
  check(vals('sprints').join(',') === 'cur,none', `Sprint chips ${vals('sprints')}`);
  check(vals('ms').join(',') === `${M},none`, `Milestone chips ${vals('ms')}`);
  const h4 = [...md.querySelectorAll('h4')].map(x => x.textContent.trim());
  check(['Assignee', 'Column', 'Sprint', 'Milestone', 'Text'].every(x => h4.includes(x)), `the headings ${h4}`);
  const cnt = () => md.querySelector('#f-count').textContent;
  click(w, md.querySelector('.fchips[data-key="who"] button[data-v="me"]'));
  check(md.querySelector('.fchips[data-key="who"] button[data-v="me"]').classList.contains('on') && /\b1 open task\b/.test(cnt()), `a chip: on + count ${cnt()}`);
  input(w, md.querySelector('#f-text'), 'nothing like this');
  check(/\b0 open tasks\b/.test(cnt()), `the text narrows the count ${cnt()}`);
  input(w, md.querySelector('#f-text'), 'crash');
  md.querySelector('#f-name').value = 'Mine';
  click(w, md.querySelector('[data-m="save"]'));
  const f = await until(async () => ((await call('GET', '/api/state')).filters || []).find(x => x.name === 'Mine'));
  check(f && JSON.stringify(f.rules.who) === '["me"]' && f.rules.text === 'crash', `saved with the new rules ${JSON.stringify(f && f.rules)}`);
  check(await until(() => w.location.hash === '#f/' + (f && f.id)), `the saved filter opens ${w.location.hash}`);
  // reopening shows the choices
  w.eval(`filterModal(${f && f.id})`);
  const md2 = await until(() => [...d.querySelectorAll('.modal')].find(x => x.querySelector('#f-text')));
  check(md2 && md2.querySelector('#f-text').value === 'crash' && md2.querySelector('.fchips[data-key="who"] button[data-v="me"]').classList.contains('on'), 'reopened: text and chip kept');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
