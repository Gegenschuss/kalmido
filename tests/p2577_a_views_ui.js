// kalmido-suite: fresh
// 2.577.0 (#3356) UI tests (own container, start.sh), jsdom: shared views in the head of a project.
// - no view yet: no header button, "New shared view…" in the "…" menu of a person who may edit, nothing for a reader
// - the dialog has no choice of projects, offers sort, grouping, display; saving opens the view
// - the open view filters the list, brings its sort and grouping, Kanban as its display; a view tab by hand wins; "All tasks"
//   gives everything back, the own sort too
// - a view is not with the filters of the sidebar; a reader sees and opens it, cannot edit it
// freelancer-matrix: lists (a person without an organisation, the own project)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  CK = CA;
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  for (const u of ['frida', 'rita']) await call('POST', '/api/users', {username: u, display_name: u, password: 'password123', email: u + '@example.com', orgs: []});
  CK = await login('frida');
  const st = await call('GET', '/api/state');
  const feats = [...new Set([...(st.settings.features || '').split(',').filter(Boolean), 'kanban', 'collab'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const L = (await call('POST', '/api/lists', {name: 'Product'})).id;
  const SEC = (await call('POST', '/api/sections', {list_id: L, name: 'Doing'})).id;
  const mk = b => call('POST', '/api/tasks', {list_id: L, ...b}).then(j => j.id);
  const A = await mk({title: 'Zebra urgent', priority: 5, section_id: SEC}), Bt = await mk({title: 'Apple urgent', priority: 5}), C = await mk({title: 'Calm one', priority: 1});
  const RCK = await login('rita');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats}, RCK);
  const RID = (await call('GET', '/api/state', null, RCK)).me.id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: RID, role: 'view'});

  const w = await boot({user: 'frida', hash: 'l/' + L}), d = w.document;
  check(await until(() => typeof w.lv_pick === 'function' && w.taskById(A) && d.querySelector('#top h1')), 'the app is there');
  const items = () => w.eval(`JSON.stringify(lv_items(listById(${L}), !!document.querySelector('#top [data-act="lviews"]')).map(i => i.label))`);
  check(!d.querySelector('#top [data-act="lviews"]'), 'no view: no button in the head');
  check(/New shared view…/.test(items()), `no view: the first one from the "…" menu ${items()}`);
  w.eval(`filterModal(0, ${L})`);
  const md = await until(() => d.querySelector('.modal #f-sort') && d.querySelector('.modal'));
  // 2.577.0: the dialog of condition rows (fltdlg.js, 2.521.0): a shared view has no project / folder condition
  click(w, md && md.querySelector('[data-m="cond-add"]'));
  const fsel = md && md.querySelector('.fcond .fc-f');
  check(fsel && ![...fsel.options].some(o => ['list', 'folder'].includes(o.value)), 'the dialog has no choice of projects');
  check(md.querySelector('#f-group') && md.querySelector('#f-display'), 'it offers grouping and display');
  md.querySelector('#f-name').value = 'Urgent';
  if (fsel) { fsel.value = 'prio'; fsel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  click(w, md.querySelector('.fcond .fc-v'));
  const pp = await until(() => d.querySelector('#pop:not(.hidden) [role="menuitemcheckbox"]') && d.querySelector('#pop'));
  click(w, pp && [...pp.querySelectorAll('[role="menuitemcheckbox"]')].find(x => x.textContent.trim() === 'High'));
  check(await until(() => /2 tasks match/.test(md.querySelector('#f-count').textContent)), 'the count: the two urgent ones ' + md.querySelector('#f-count').textContent);
  md.querySelector('#f-sort').value = 'title';
  md.querySelector('#f-group').value = 'none';
  click(w, md.querySelector('[data-m="save"]'));
  const open = await until(() => w.eval(`lv_cur(${L})`));
  check(open && open.name === 'Urgent', 'saved: the view is open');
  const rows = () => w.eval(`JSON.stringify(viewTasks().open.map(t => t.id))`);
  check(!JSON.parse(rows()).includes(C) && JSON.parse(rows()).includes(A), `the view filters the list ${rows()}`);
  check(w.eval('sortMode()') === 'title', `its sort ${w.eval('sortMode()')}`);
  check(w.eval('viewTasks().group') === 'none', 'its grouping');
  check(await until(() => /Urgent/.test(d.querySelector('#top [data-act="lviews"]')?.textContent || '')), 'the head names the open view');
  check(w.eval('S.filters.length') === 0 && !d.querySelector('#side [data-k^="f:"]'), 'a view is not with the sidebar filters');

  await call('PATCH', '/api/filters/' + open.id, {rules: {...open.rules, display: 'kanban'}});
  await w.eval('load()');
  await until(() => w.eval(`lv_cur(${L}).rules.display`) === 'kanban');
  w.eval('render()');
  check(w.eval(`listView(listById(${L}))`) === 'kanban' && w.eval('isKanban()'), 'its display: Kanban');
  await w.eval(`setListView(listById(${L}), 'list')`);
  check(w.eval(`listView(listById(${L}))`) === 'list', 'a view tab by hand wins');
  check(JSON.parse(rows()).length === 2, 'the filter stays');
  w.eval(`lv_pick(listById(${L}), null)`);
  check(JSON.parse(rows()).includes(C) && w.eval('viewTasks().group') === 'section', '"All tasks": everything again');
  check(w.eval('sortMode()') !== 'title', 'and the own sort');
  check(/Shared views/.test(items()) || !!d.querySelector('#top [data-act="lviews"]'), 'with a view: the way to it');

  const w2 = await boot({user: 'rita', hash: 'l/' + L}), d2 = w2.document;
  check(await until(() => typeof w2.lv_pick === 'function' && w2.taskById(A) && w2.eval('S.views.length') === 1), 'a reader has the view');
  w2.eval(`lv_menu(document.querySelector('#top h1'), listById(${L}))`);
  const lab = await until(() => [...d2.querySelectorAll('.menu-list button')].map(b => b.textContent).join('|'));
  check(/Urgent/.test(lab) && /All tasks/.test(lab), `a reader's menu ${lab}`);
  check(!/New shared view|Edit view/.test(lab), 'no editing for a reader');
  w2.eval(`lv_pick(listById(${L}), ${open.id})`);
  check(!w2.eval(`JSON.stringify(viewTasks().open.map(t => t.id))`).includes(`${C}`), 'a reader opens it');
  await call('DELETE', '/api/filters/' + open.id);
  await w2.eval('load()');
  check(w2.eval(`lv_cur(${L})`) === null && w2.eval('viewTasks().open.length') === 3, 'a deleted view: the project as usual');
  check(!errs.length, `no script errors ${errs}`);
  console.log(`p2577_a_views_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
