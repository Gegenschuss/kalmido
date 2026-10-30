// 2.412.0 UI tests (#3552), own container (start.sh), jsdom, invented texts only:
// kalmido-suite:
// - the project's properties (props.js): the type's cut hides what does not fit - a software project shows no video sign-off,
//   client / contacts, documents; an agency no repository / ticket type; a personal project nothing of business
// - one source: a hidden property is no column ("Shown fields…" / colChoices, the default columns), no part of the task panel
//   (ticket type select, tags) and no item of the task's "…" menu (Assign…, Add code snippet)
// - a task that already has something in a hidden property keeps showing it there (tags)
// - the project options: the part "Properties" with one switch per property for the owner (a switch saves at once, the
//   task panel follows, "As the project type" clears the changes); a member who edits does not see the part
// - a type change first says what goes away (cancel = the type stays), then takes the new type's cut
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return c; };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2412_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const ev = (w, s) => JSON.parse(w.eval(`JSON.stringify(${s})`));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'collab', 'time', 'deps', 'fields', 'kanban', 'contacts', 'docs'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Nordwind', admin_id: st0.me.id})).id;
  const bob = await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  check(bob.id, 'setup: bob ' + JSON.stringify(bob).slice(0, 200));
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: `org:${ORG}`}, CKB);
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  const mk = async (name, ptype) => (await call('POST', '/api/lists', {name, kind: 'project', ptype})).id;
  const SW = await mk('Web app', 'software'), AG = await mk('Spring campaign', 'agency'), PV = await mk('Garden', 'private');
  check(SW && AG && PV, 'setup: three projects');
  await call('PATCH', '/api/lists/' + SW, {tickets: 1, time_tracking: true});
  await call('PATCH', '/api/lists/' + AG, {tickets: 1, time_tracking: true});
  check((await call('PUT', `/api/lists/${SW}/members`, {user_id: bob.id, role: 'edit'})).ok !== false, 'setup: bob edits the software project');
  const T1 = (await call('POST', '/api/tasks', {title: 'Login form', list_id: SW})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Water the roses', list_id: PV})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Seed list #green', list_id: PV, tags: ['green']})).id;

  // ================= the type's cut
  const w = await boot({user: 'alice', hash: 'list/' + SW}), d = w.document;
  await until(() => d.querySelector('#view .trow'));
  const on = (lid, k) => ev(w, `pz_on(${lid}, '${k}')`);
  check(!on(SW, 'video') && !on(SW, 'client') && !on(SW, 'docs') && on(SW, 'repo') && on(SW, 'ttype') && on(SW, 'time'), 'software: video, client, documents off; repository, ticket type, time on');
  check(!on(AG, 'repo') && !on(AG, 'ttype') && on(AG, 'video') && on(AG, 'time') && on(AG, 'client'), 'agency: repository and ticket type off, the rest on');
  check(['ticket', 'who', 'time', 'deps', 'points', 'video', 'docs'].every(k => !on(PV, k)) && on(PV, 'tags'), 'personal: business off, tags on');
  check(ev(w, `colChoices(listById(${SW})).map(x => x[0])`).includes('time'), 'software: Tracked time is a column choice');
  check(!ev(w, `colChoices(listById(${PV})).map(x => x[0])`).some(k => ['who', 'time', 'deps'].includes(k)), 'personal: no assignee / time / dependency columns');
  check(!ev(w, `colDefault(listById(${PV}))`).includes('id'), 'personal: no task number in the default columns');

  // ================= task panel: ticket type at the software task, not at the agency one; tags at a task that has some
  w.eval(`openDetail(${T1})`);
  check(await until(() => d.querySelector('#detail #d-ttype')), 'software: the ticket type in the task panel');
  await call('PATCH', '/api/lists/' + SW, {props: {ttype: 0, tags: 0}});
  await w.eval('load()'); w.eval('render(); renderDetail()');
  check(await until(() => !d.querySelector('#detail #d-ttype')), 'ticket type switched off: not in the task panel');
  check(!d.querySelector('#detail .dsec h5') || ![...d.querySelectorAll('#detail .dsec h5')].some(h => h.textContent === 'Tags'), 'tags switched off: no Tags part at a task without tags');
  await call('PATCH', '/api/lists/' + PV, {props: {tags: 0}});
  await w.eval('load()');
  w.eval(`openDetail(${T3})`);
  check(await until(() => [...d.querySelectorAll('#detail .dsec h5')].some(h => h.textContent === 'Tags')), 'a task with tags keeps its Tags part while the property is off');
  w.eval(`openDetail(${T2})`);
  check(await until(() => d.querySelector('#detail .dtitle') && ![...d.querySelectorAll('#detail .dsec h5')].some(h => h.textContent === 'Tags')), 'the task without tags in the same project: no Tags part');
  w.eval(`taskMenu(document.querySelector('#detail .dtop [data-act="task-menu"]'), ${T2})`);
  const mi = await until(() => d.querySelectorAll('[role="menuitem"]').length && [...d.querySelectorAll('[role="menuitem"]')].map(b => b.textContent.trim()));
  check(Array.isArray(mi) && !mi.some(x => /^Start time tracking|^Add time|^Add code snippet/.test(x)), 'personal: the task menu has no time / code items ' + JSON.stringify(mi).slice(0, 300));
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  await call('PATCH', '/api/lists/' + PV, {props: {}});

  // ================= the project options: Properties
  await w.eval('load()');
  w.eval(`listModal(${SW})`);
  const box = await until(() => d.querySelector('.lmodal #l-pz'));
  check(box && box.querySelectorAll('input[data-pz]').length === 11, 'owner: the part Properties with 11 switches');
  check(box && !box.querySelector('input[data-pz="video"]').checked && !box.querySelector('input[data-pz="ttype"]').checked && box.querySelector('input[data-pz="repo"]').checked, 'the switches show the cut and the own changes');
  const vd = box.querySelector('input[data-pz="video"]'); vd.checked = true; vd.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).lists.find(x => x.id === SW).props || '{}').video === 1), 'a switch saves at once (video on)');
  check(await until(() => on(SW, 'video')), 'the app follows at once');
  const rs = await until(() => d.querySelector('.lmodal #l-pz [data-pz-reset]'));
  rs?.click();
  check(await until(async () => !(await call('GET', '/api/state')).lists.find(x => x.id === SW).props), '"As the project type" clears the changes');
  check(await until(() => !d.querySelector('.lmodal #l-pz [data-pz-reset]') && d.querySelector('.lmodal #l-pz input[data-pz="ttype"]')?.checked), 'the part shows the cut again');

  // ================= a type change says first what goes away
  let asked = '';
  w.confirm = m => { asked = m; return false; };
  const sel = d.querySelector('.lmodal #l-ptype'); sel.value = 'agency'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => asked), 'the type change asks first');
  check(/Repository and code/.test(asked) && /Ticket type/.test(asked) && /Nothing is deleted/.test(asked), 'it names what goes away: ' + asked);
  await sleep(300);
  check((await call('GET', '/api/state')).lists.find(x => x.id === SW).ptype === 'software', 'cancelled: the type stays');
  asked = ''; w.confirm = m => { asked = m; return true; };
  sel.value = 'agency'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/state')).lists.find(x => x.id === SW).ptype === 'agency'), 'confirmed: the type changes');
  check(await until(() => !on(SW, 'repo') && on(SW, 'video')), 'the new type\'s cut applies');
  w.close();

  // ================= a member who edits does not see the part
  const wb = await boot({user: 'bob', hash: 'list/' + SW}), db = wb.document;
  await until(() => db.querySelector('#view'));
  wb.eval(`listModal(${SW})`);
  check(await until(() => db.querySelector('.lmodal')) && !db.querySelector('.lmodal #l-pz'), 'a member who edits: no part Properties');
  wb.close();

  if (ok < 26) check(false, 'every part ran (only ' + ok + ' checks)');
  console.log(`p2412_props_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
