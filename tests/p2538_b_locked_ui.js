// 2.538.0 part B (#4372) UI: a project with the lock offers none of the three texts it cannot encrypt, an open one still does.
// kalmido-suite: fresh
// Own container (start.sh), invented names only. The lock is simulated in the page (le2eOn), the server side is
// p2538_b_locked_test.py.
// - the project status dialog: no note field (the status buttons stay); an open project: the field is there
// - the project overview: no description block; an open project: there
// - the time entry dialog: no note row for a task / project with the lock, back when another project is chosen
// - the notice before switching on names the three texts and that existing ones are deleted for good
// freelancer-matrix: lists, time (everything as a person without an organisation)
// P2538BU_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2538BU_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n, ms = 150) => require('./boot').until(fn, {timeout: n ? n * ms : 15000, step: ms});
const FEAT = 'collab,time,comments,progress';
const NOTE = 'The project description, the note of the project status and the notes of time entries cannot be encrypted: they are not available in it, and existing ones are deleted for good when you switch it on.';

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'time']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'frida (no organisation) ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Strongbox', time_tracking: true})).id;
  const L2 = (await call(CF, 'POST', '/api/lists', {name: 'Open one', time_tracking: true})).id;
  check(L && L2, 'two projects');

  const w = await boot({user: 'frida', hash: 'l/' + L}), d = w.document;
  await until(() => w.eval(`!!listById(${L}) && !!listById(${L2})`));
  w.eval(`window.__lk = le2eOn; le2eOn = id => +id === ${L} || window.__lk(id); 1`);  // the lock of L, as the state would carry it

  // status dialog
  w.eval(`statusModal(${L}); 1`);
  await until(() => d.querySelector('.stmodal'));
  check(d.querySelector('.stmodal .stchoice') && !d.querySelector('.stmodal #st-note'), 'locked: the status dialog has the status buttons but no note field');
  d.querySelector('.stmodal')?.remove();
  w.eval(`statusModal(${L2}); 1`);
  await until(() => d.querySelector('.stmodal'));
  check(!!d.querySelector('.stmodal #st-note'), 'open: the status dialog has the note field');
  d.querySelector('.stmodal')?.remove();

  // overview: the description block
  w.eval(`setListView(routeList(), 'overview'); 1`);
  await until(() => d.querySelector('#view .pov .povs'));
  check(!d.querySelector('#view #pov-desc'), 'locked: the overview has no description block');
  w.location.hash = 'l/' + L2;
  await until(() => w.eval(`routeList()?.id`) === L2);
  w.eval(`setListView(routeList(), 'overview'); 1`);
  await until(() => d.querySelector('#view #pov-desc'));
  check(!!d.querySelector('#view #pov-desc'), 'open: the overview has the description block');

  // time entry dialog
  w.eval(`entryModal(null, {list_id: ${L}}); 1`);
  await until(() => d.querySelector('#te-noterow'));
  check(d.querySelector('#te-noterow')?.hidden === true, 'locked: no note row in the time entry dialog');
  const sel = d.querySelector('#te-target');
  sel.value = 'l:' + L2; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(d.querySelector('#te-noterow')?.hidden === false, 'another, open project chosen: the note row is back');
  sel.value = 'l:' + L; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(d.querySelector('#te-noterow')?.hidden === true, 'back to the locked project: hidden again');
  d.querySelector('#te-noterow')?.closest('.modal, .mdl, dialog, [role="dialog"]')?.remove();

  // the notice before switching on
  w.eval(`e2eEnsure = async () => true; le2eInfo = async () => ({blockers: [], members: [{user_id: S.me.id, name: 'Frida', has_keys: true}]}); le2u_startDlg(${L}); 1`);
  const dlg = await until(() => d.querySelector('.cdlg .le2unote') && d.querySelector('.cdlg'));
  const vis = [...(dlg?.querySelectorAll('ol.le2unote > li') || [])].map(x => x.textContent);
  check(vis.includes(NOTE), 'the notice names the three texts and that they are deleted for good, visible ' + JSON.stringify(vis));
  w.close();

  console.log(`p2538_b_locked_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
