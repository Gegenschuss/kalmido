// kalmido-suite:
// 2.352.0 B (#2752) UI tests: no difference any more between a list and a project. Own container (start.sh), jsdom,
// invented names only.
// - tracked = has a status: only projects with a status on the start page card "Projects" and in "Where is it stuck?";
//   a cleared status = gone from both
// - a project of kind "list" without a status: progress bar in its head and in the sidebar, the view "Project page",
//   "Set status" in its menu; no type badge in the header
// freelancer-matrix: lists (alice has no organisation here: every check is also the freelancer case; the routes run in
// p2352_b_project_unify_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2352B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const day = n => { const x = new Date(); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
const FEAT = 'cal,timeline,collab,progress,deps,fields,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, dashboard: ''});
  const P1 = (await call('POST', '/api/lists', {name: 'Garden plan'})).id;                       // kind list, tracked
  const P2 = (await call('POST', '/api/lists', {name: 'Shop opening', kind: 'project'})).id;     // kind project, tracked
  const P3 = (await call('POST', '/api/lists', {name: 'Reading pile', kind: 'project'})).id;     // kind project, not tracked
  const P4 = (await call('POST', '/api/lists', {name: 'Errands'})).id;                           // kind list, not tracked
  for (const [l, t, due] of [[P1, 'Dig beds', day(3)], [P1, 'Buy seeds', null], [P2, 'Sign lease', day(-2)], [P3, 'Novel one', null], [P4, 'Post office', null], [P4, 'Bank', null]]) {
    const id = (await call('POST', '/api/tasks', {title: t, list_id: l, ...(due ? {due} : {})})).id;
    if (t === 'Buy seeds' || t === 'Bank') await call('POST', `/api/tasks/${id}/complete`);
  }
  await call('POST', `/api/lists/${P1}/status`, {status: 'on_track', note: ''});
  await call('POST', `/api/lists/${P2}/status`, {status: 'at_risk', note: 'Lease is late'});
  const names = (d, sel) => [...d.querySelectorAll(sel)].map(x => x.textContent.replace(/\s+/g, ' ').trim());

  // ================= the start page card: tracked projects only
  let w = await boot({user: 'alice', hash: 'home'}), d = w.document;
  check(await until(() => d.querySelector('.dc-projects .dpl li')), 'start page: the card Projects shows');
  let pl = names(d, '.dc-projects .dpl li');
  check(pl.some(x => /Garden plan.*50 %/.test(x)) && pl.some(x => /Shop opening/.test(x)), 'start page: the projects with a status, with their progress ' + JSON.stringify(pl));
  check(!pl.some(x => /Reading pile|Errands/.test(x)), 'start page: projects without a status are not tracked ' + JSON.stringify(pl));
  w.close();

  // ================= "Where is it stuck?": tracked projects only
  w = await boot({user: 'alice', hash: 'overview'}); d = w.document;
  check(await until(() => d.querySelector('.ovcard')), 'Where is it stuck: shows with two tracked projects');
  const ov = names(d, '.ovcard .ovname');
  check(ov.some(x => /Shop opening/.test(x)) && ov.some(x => /Garden plan/.test(x)) && !ov.some(x => /Reading pile|Errands/.test(x)), 'Where is it stuck: only the tracked projects ' + JSON.stringify(ov));
  w.close();

  // ================= a kind=list project without a status: progress, project page, Set status, no badge
  // the bar itself stays a per-person switch (2.40.0 #1190, default off): switched on here for Errands
  await call('PATCH', '/api/settings', {show_progress: String(P4)});
  w = await boot({user: 'alice', hash: 'l/' + P4}); d = w.document;
  check(await until(() => d.querySelector('.lhead .lprog')), 'kind list: progress bar in the project head');
  check(/50%/.test(d.querySelector('.lhead .lprog')?.textContent || ''), 'kind list: 1 of 2 done = 50% ' + (d.querySelector('.lhead .lprog')?.textContent || ''));
  check(d.querySelector(`#side .srow[data-list="${P4}"] .sprog`) || w.eval(`typeof sbiProg !== 'function' || !sbiProg()`), 'kind list: the progress ring in the sidebar');
  check(!d.querySelector('#top .kbadge'), 'no type badge in the header');
  check(w.eval(`viewChoices(listById(${P4})).map(x => x[0])`).includes('overview'), 'kind list: the view "Project page" is offered');
  check(w.eval(`listMenuItems(${P4}, document.body).map(x => x && x.label)`).includes('Set status'), 'kind list: "Set status" in its menu');
  w.eval(`setListView(listById(${P4}), 'overview')`);
  check(await until(() => w.eval('isOverview()')), 'kind list: the project page opens');
  check(!w.eval(`viewChoices(inbox()).map(x => x[0])`).includes('overview'), 'the inbox: no project page');
  w.close();

  // ================= status cleared = not tracked any more
  await call('POST', `/api/lists/${P1}/status`, {status: ''});
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => d.querySelector('.dc-projects .dpl li'));
  pl = names(d, '.dc-projects .dpl li');
  check(!pl.some(x => /Garden plan/.test(x)) && pl.some(x => /Shop opening/.test(x)), 'status cleared: gone from the start page card ' + JSON.stringify(pl));
  check(!w.eval('overviewOn()'), 'one tracked project, not shared: no "Where is it stuck?"');
  w.close();

  console.log(`p2352_b_project_unify_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
