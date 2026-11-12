// kalmido-suite: fresh
// 2.1002.0 UI test (#5491, stage 2b of the core's trash: tasks and projects come back through the core; first built in
// 2.851.0), own container (start.sh; P21002B_NOSTART=1 / KMT_NOSTART=1: a running server), jsdom. Invented names only.
// freelancer-matrix: tasks (alice works without an organisation: her private workspace)
// - a task deleted in its project: it leaves the list, the trash view shows it with its title; "Restore" there -> it leaves
//   the trash view and is in its project again (its row with the title)
// - a project deleted (archived first): the trash view lists it under "Deleted projects" with its name and its task count;
//   "Restore" -> it leaves the trash section, is among the projects again and its tasks are back in it
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21002B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'private'});
  const st = () => call('GET', '/api/state');
  const L = (await call('POST', '/api/lists', {name: 'Example Garden Plan', org_id: null})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Order the seeds', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Water the beds', list_id: L})).id;
  check(L && T && T2, 'setup: a project with two tasks');

  // ================= a task: delete -> in the trash view -> restore -> in its project again
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.__dialogs = 'manual';
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  check(await until(() => row(T) && /Order the seeds/.test(row(T).textContent)), 'the task stands in its project');
  check((await call('DELETE', `/api/tasks/${T}`)).ok === true, 'the task deleted');
  w.eval(`load().then(() => renderView())`);
  check(await until(() => !row(T) && row(T2)), 'the deleted task left its project (the other one stays)');
  w.eval(`go('trash')`);
  const tr1 = await until(() => !row(T2) && row(T));
  check(tr1 && /Order the seeds/.test(tr1.textContent) && !row(T2), 'the trash view shows the deleted task (not the live one) ' + (tr1?.textContent || '').slice(0, 120));
  const back = tr1 && tr1.querySelector('[data-act="restore"]');
  check(!!back, 'the row offers Restore');
  if (back) click(w, back);
  check(await until(async () => (await st()).tasks.some(t => t.id === T), 60), 'Restore: the task is live again');
  check(await until(() => !row(T)), 'Restore: it left the trash view');
  w.eval(`go('l/${L}')`);
  check(await until(() => row(T) && /Order the seeds/.test(row(T).textContent) && row(T2)), 'back in its project with its title, next to the other task');

  // ================= a project: delete -> "Deleted projects" -> restore -> among the projects with its tasks
  await call('PATCH', `/api/lists/${L}`, {archived: 1});
  check((await call('DELETE', `/api/lists/${L}`)).trash === true, 'the project deleted (into the trash)');
  check(await until(async () => !(await st()).lists.some(l => l.id === L), 60), 'the project left the projects');
  w.eval(`S.otr.at = 0; load().then(() => go('trash'))`);  // deleted beside the app (API): its 30-second cache of the projects' trash (listadmin.js otr_load) is not told
  const pr = await until(() => d.querySelector(`#view .otrlists [data-otr="${L}"]`));
  check(pr && /Deleted projects/.test(pr.closest('.otrlists')?.querySelector('.ghead')?.textContent || ''), 'the trash view has the section "Deleted projects"');
  check(pr && /Example Garden Plan/.test(pr.textContent) && /2 tasks/.test(pr.textContent), 'the row: its name and its 2 tasks ' + (pr?.textContent || '').slice(0, 160));
  check(!row(T) && !row(T2), 'its tasks are no rows of the task trash');
  const pb = pr && pr.querySelector('[data-otra="restore"]');
  check(!!pb, 'the project row offers Restore');
  if (pb) click(w, pb);
  check(await until(async () => (await st()).lists.some(l => l.id === L), 60), 'Restore: the project is among the projects again');
  check(await until(() => !d.querySelector(`#view .otrlists [data-otr="${L}"]`)), 'Restore: it left the trash section');
  const s2 = await st();
  check(s2.tasks.some(t => t.id === T && t.list_id === L) && s2.tasks.some(t => t.id === T2 && t.list_id === L), 'its tasks came back with it');
  await call('PATCH', `/api/lists/${L}`, {archived: 0});
  w.eval(`load().then(() => go('l/${L}'))`);
  check(await until(() => row(T) && row(T2) && /Water the beds/.test(row(T2).textContent)), 'opened again: the project shows both tasks');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
