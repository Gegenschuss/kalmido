// 2.46.0 UI tests of part C, own container (start.sh). jsdom:
// - #1606 Share folder: changing a person's role asks first when lists of the folder have a role of their own ("In 1 list Bob
//   has a role of its own (Beta: Admin)."): "Only new lists" keeps them, "Cancel" puts the choice back and changes nothing,
//   "Set everywhere" replaces them; without such lists no question (as before); the same for a group's role
// - #1605 a group's picture in the folder's Share dialog, the list's Share dialog, the group dialog (preset picker, saved
//   with the group) and the task assigned to the group; without a picture the group symbol as before
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2460C_RUNNING) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const pick = (w, sel, v) => { sel.value = v; sel.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEAT = 'cal,comments,collab';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const uid = {};
  for (const u of ['bob', 'carol']) uid[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123'})).id;
  const mk = async (name, folder) => (await call('POST', '/api/lists', {name, folder})).id;
  const LA = await mk('Alpha', 'Work'), LB = await mk('Beta', 'Work');
  await call('PUT', '/api/folders/people', {folder: 'Work', user_id: uid.bob, role: 'edit'});
  await call('PUT', `/api/lists/${LB}/members`, {user_id: uid.bob, role: 'admin'});  // Beta: a role set by hand
  const G = (await call('POST', '/api/admin/groups', {name: 'Crew', members: [uid.carol]})).id;
  const G2 = (await call('POST', '/api/admin/groups', {name: 'Plain', members: [uid.carol]})).id;
  await call('PUT', `/api/lists/${LA}/groups/${G}`, {role: 'admin'});  // the group's own role in Alpha
  await call('PUT', `/api/folders/groups/${G}`, {folder: 'Work', role: 'edit'});
  await call('PUT', `/api/folders/groups/${G2}`, {folder: 'Work', role: 'view'});
  await call('PUT', `/api/admin/groups/${G}/avatar`, {preset: 'coffee'});
  const T = (await call('POST', '/api/tasks', {title: 'Sort the cables', list_id: LA})).id;
  await call('PATCH', `/api/tasks/${T}`, {assignee_group_id: G});
  const dbx = (sql, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]).toString());
  const roleOf = async lid => dbx('SELECT role FROM list_members WHERE list_id=? AND user_id=?', [lid, uid.bob])[0]?.role;
  const folderRole = async () => ((await call('GET', '/api/folders/people?folder=Work')).people || [])[0]?.role;

  let w = await boot({user: 'alice'}), d = w.document;
  await until(() => d.querySelector('#side') && w.eval('(S.groups || []).length') === 2);
  w.eval(`LS.set('agSafeSeen', true); folderShareModal('Work')`);
  let md = await until(() => d.querySelector('.modal.fshmodal [data-fprole]')?.closest('.modal'));
  check(md, 'the Share dialog of the folder');
  // ================= #1606 people
  const ask = () => d.querySelector('.modal [data-fgrq="all"]')?.closest('.modal');
  pick(w, md.querySelector(`[data-fprole="${uid.bob}"]`), 'view');
  let q = await until(ask);
  check(q && /In 1 list Bob has a role of its own \(Beta: Admin\)\./.test(q.textContent), '#1606: the question names the list and its role: ' + (q?.textContent || '').replace(/\s+/g, ' ').slice(0, 200));
  check(q && [...q.querySelectorAll('[data-fgrq]')].map(b => b.textContent).join('|') === 'Cancel|Only new lists|Set everywhere', '#1606: Cancel | Only new lists | Set everywhere');
  click(w, q.querySelector('[data-fgrq="new"]'));
  await until(async () => await folderRole() === 'view');
  check(await folderRole() === 'view' && await roleOf(LB) === 'admin' && await roleOf(LA) === 'edit', '#1606: "Only new lists": the folder role changes, the lists keep theirs');
  pick(w, md.querySelector(`[data-fprole="${uid.bob}"]`), 'participant');
  q = await until(ask);
  check(q && /In 2 lists Bob has a role of its own \(Alpha: Can edit|In 2 lists Bob has a role of its own \(Alpha: /.test(q.textContent), '#1606: now two lists: ' + (q?.textContent || '').replace(/\s+/g, ' ').slice(0, 200));
  click(w, q.querySelector('[data-fgrq="x"]'));
  await sleep(500);
  check(!ask() && md.querySelector(`[data-fprole="${uid.bob}"]`).value === 'view', '#1606: Cancel puts the choice back: ' + md.querySelector(`[data-fprole="${uid.bob}"]`).value);
  check(await folderRole() === 'view' && await roleOf(LB) === 'admin', '#1606: Cancel changes nothing');
  pick(w, md.querySelector(`[data-fprole="${uid.bob}"]`), 'participant');
  q = await until(ask);
  click(w, q.querySelector('[data-fgrq="all"]'));
  await until(async () => await roleOf(LB) === 'participant');
  check(await folderRole() === 'participant' && await roleOf(LB) === 'participant' && await roleOf(LA) === 'participant', '#1606: "Set everywhere" replaces the roles');
  pick(w, md.querySelector(`[data-fprole="${uid.bob}"]`), 'view');
  await sleep(700);
  check(!ask() && await folderRole() === 'view' && await roleOf(LA) === 'view', '#1606: no list with its own role: no question, changed at once');
  // ================= #1606 groups
  const gsum = await until(() => md.querySelector('#fsh-sec-grp summary'));
  click(w, gsum);
  const gsel = await until(() => md.querySelector(`[data-fgrole="${G}"]`));
  pick(w, gsel, 'view');
  q = await until(ask);
  check(q && /In 1 list Crew has a role of its own \(Alpha: Admin\)\./.test(q.textContent), '#1606: the question for a group: ' + (q?.textContent || '').replace(/\s+/g, ' ').slice(0, 200));
  click(w, q.querySelector('[data-fgrq="new"]'));
  await sleep(700);
  let lg = (await call('GET', `/api/lists/${LA}/groups`)).groups || [];
  check(lg.some(x => x.group_id === G && x.via === 'list' && x.role === 'admin') && lg.some(x => x.group_id === G && x.via === 'Work' && x.role === 'view'), '#1606: group, "Only new lists": Alpha keeps its own group role ' + JSON.stringify(lg));
  // ================= #1605 the group's picture
  const grow = await until(() => md.querySelector(`[data-fgrole="${G}"]`)?.closest('.mrow'));
  check(grow && grow.querySelector('.avatar.gav.pic img')?.getAttribute('src') === '/static/avatars/coffee.svg', '#1605: the picture in the folder\'s Share dialog');
  const prow = md.querySelector(`[data-fgrole="${G2}"]`)?.closest('.mrow');
  check(prow && !prow.querySelector('.gav img') && prow.querySelector('.gav svg, .gav .i'), '#1605: without a picture the group symbol as before');
  click(w, md.querySelector('.lhdr [data-m="close"]'));
  await sleep(300);
  w.eval(`shareModal(${LA})`);
  const sm = await until(() => d.querySelector(`.modal [data-gsh="${G}"]`)?.closest('.modal'));
  check(sm && sm.querySelector(`[data-gsh="${G}"] .gav.pic img`), '#1605: the picture in the list\'s Share dialog');
  sm?.remove();
  await sleep(200);
  w.location.hash = '#l/' + LA; w.eval(`(typeof route === 'function') && route()`);
  const chip = await until(() => d.querySelector('#view .gchip'));
  check(chip && chip.querySelector('img.fggimg')?.getAttribute('src') === '/static/avatars/coffee.svg', '#1605: the picture in the task assigned to the group');
  // the group dialog: picker, saved with Save
  w.eval(`grpEdit(document.body, ${G2})`);
  const gm = await until(() => d.querySelector('.modal.grpmodal #gr-avpick')?.closest('.modal'));
  check(gm && gm.querySelector('#gr-avpick [data-fgav="none"].on') && gm.querySelectorAll('#gr-avpick [data-fgav]').length >= 12, '#1605: the picker in the group dialog (presets, upload, none)');
  click(w, gm.querySelector('#gr-avpick [data-fgav="plant"]'));
  check(gm.querySelector('#gr-avpick [data-fgav="plant"].on'), '#1605: the chosen preset is marked');
  check(((await call('GET', '/api/groups')).groups.find(x => x.id === G2) || {}).avatar === '', '#1605: nothing saved before Save');
  click(w, gm.querySelector('[data-m="ok"]'));
  await until(async () => ((await call('GET', '/api/groups')).groups.find(x => x.id === G2) || {}).avatar);
  check(((await call('GET', '/api/groups')).groups.find(x => x.id === G2) || {}).avatar === '/static/avatars/plant.svg', '#1605: saved with the group');
  await until(() => w.eval(`grpById(${G2})?.avatar`) === '/static/avatars/plant.svg');  // the app reloaded its state
  w.eval(`grpEdit(document.body, ${G2})`);
  const gm2 = await until(() => d.querySelector('.modal.grpmodal #gr-avpick [data-fgav="plant"].on')?.closest('.modal'));
  check(gm2, '#1605: the dialog shows the saved picture');
  if (gm2) { click(w, gm2.querySelector('#gr-avpick [data-fgav="none"]')); click(w, gm2.querySelector('[data-m="ok"]')); }
  await until(async () => ((await call('GET', '/api/groups')).groups.find(x => x.id === G2) || {}).avatar === '');
  check(((await call('GET', '/api/groups')).groups.find(x => x.id === G2) || {}).avatar === '', '#1605: "No picture" removes it');
  w.close();

  console.log(`p2460_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
