// 2.39.1 UI tests, part L (#1188 list admins delete, Settings > Organisation, moving into a folder with defaults; #1291 menu
// texts; #1214 "Hide completed" as a default), own container (start.sh). jsdom:
// - a list admin's list menu: "Archive list" / "Delete list…"; the delete dialog says the list is shared and that the
//   tasks go to the owner's basket; an editor has neither entry
// - an organisation admin who is only an editor: "Archive list" (the organisation's way), no delete before the archive
// - Settings > Organisation: the members box and "Lists of the organisation" (grouped by owner, folder path); Account links there
// - moving a private list into a folder of the organisation asks first: Cancel leaves it, OK moves it and takes the workspace
// - "Hide completed": the setting in Appearance, the default, the folder default, a list's own choice and "like the default"
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab';
const labels = (w, id) => w.eval(`listMenuItems(${id}, document.body).filter(x => x && x.label).map(x => x.label)`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  // 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, show_done_default: '1', show_done_new: '0'});  // 2.49.0 (#1535): the old defaults (completed stay visible)
  const ME = (await call('GET', '/api/state')).me, ORG = ME.workspaces[0].id;
  const uid = {};
  for (const u of ['bob', 'carol']) uid[u] = (await call('POST', '/api/users', {orgs: [1], username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: u + '@example.com'})).id;
  const CB = await login('bob'), CC = await login('carol');
  for (const c of [CB, CC]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, show_done_default: '1', show_done_new: '0'}, c);  // 2.49.0 (#1535): the old defaults (completed stay visible)
  const SH = (await call('POST', '/api/lists', {name: 'Fair stand', org_id: ORG, folder: 'Events'}, CB)).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: uid.carol, role: 'admin'}, CB);
  await call('PUT', `/api/lists/${SH}/members`, {user_id: ME.id, role: 'edit'}, CB);
  await call('POST', '/api/tasks', {title: 'Book the booth', list_id: SH}, CB);

  // ================= #1188 / #1291 the list admin
  let w = await boot({user: 'carol', hash: 'l/' + SH}), d = w.document;
  w.__dialogs = 'manual';  // the app's own dialogs are driven here (boot.js would answer them)
  await until(() => w.eval(`!!listById(${SH})`));
  let lab = labels(w, SH);
  check(lab.includes('Archive list') && lab.includes('Delete list…'), '#1188 #1291: a list admin: Archive list / Delete list… ' + JSON.stringify(lab));
  w.eval(`listDeleteForGood(${SH})`);
  const dlg = await until(() => d.querySelector('.cdlg'));
  const txt = (dlg?.textContent || '').replace(/\s+/g, ' ');
  check(/The list is shared: all 2 other people lose it/.test(txt), '#1188: the dialog says the list is shared ' + txt.slice(0, 300));
  check(/basket of Bob/.test(txt) && /Bob is told/.test(txt), '#1188: the tasks go to the owner\'s basket, the owner is told ' + txt.slice(0, 300));
  click(w, dlg.querySelector('[data-cd="no"]')); await sleep(200);
  check((await call('GET', '/api/state', null, CB)).lists.some(l => l.id === SH), '#1188: Cancel deletes nothing');
  w.close();

  // ================= #1188 an organisation admin (editor of the list): the organisation's way, archive first
  w = await boot({user: 'alice', hash: 'l/' + SH}); d = w.document; w.__dialogs = 'manual';
  await until(() => w.eval(`!!listById(${SH})`));
  lab = labels(w, SH);
  check(lab.includes('Archive list') && !lab.includes('Delete list…'), '#1188: organisation admin + editor: archive only (delete from the archive) ' + JSON.stringify(lab));
  // ================= #1188 Settings > Organisation
  w.eval(`settingsModal('account')`); await until(() => d.querySelector('[data-lmorg]'));
  check(!!d.querySelector('#sp-account [data-lmorg]') && !d.querySelector('#sp-account #s-ws'), '#1188: Account links to Settings > Organisation');
  click(w, d.querySelector('[data-lmorg]')); await until(() => d.querySelector('#sp-org:not(.hidden) #s-ws .wsorg'));
  check(!!d.querySelector('#st-org.on') && !!d.querySelector('#sp-org #s-ws .wsorg'), '#1188: Settings > Organisation shows the members');
  const ob = d.querySelector(`#sp-org [data-oadm="${ORG}"]`);
  check(!!ob, '#1188: the admin finds "Lists of the organisation" there');
  click(w, ob); await until(() => d.querySelector('.oadmmd .oadmrow'));
  const omd = d.querySelector('.oadmmd');
  check([...omd.querySelectorAll('.lmoh')].some(h => /Bob/.test(h.textContent)) && /Folder: Events/.test(omd.textContent), '#1188: grouped by owner, with the folder path ' + omd.textContent.replace(/\s+/g, ' ').slice(0, 200));
  check(!!omd.querySelector('.lmohint'), '#1188: the hint for privately shared lists');
  w.document.querySelectorAll('.modal').forEach(m => m.remove());
  // ================= #1214 the setting in Appearance
  w.eval(`settingsModal('look')`); await until(() => d.querySelector('#s-sdd'));
  check(d.querySelector('#s-sdd')?.value === '1', '#1214: Appearance > Completed tasks: Show by default');
  w.close();

  // ================= #1188 moving into a folder with defaults asks first (bob)
  const MV = (await call('POST', '/api/lists', {name: 'Mover', org_id: null}, CB)).id;
  await call('PUT', '/api/folders/props', {folder: 'Clients', props: {org_id: ORG}}, CB);
  await call('PATCH', '/api/settings', {folders: JSON.stringify(['Clients', 'Events'])}, CB);
  w = await boot({user: 'bob', hash: 'l/' + MV}); d = w.document; w.__dialogs = 'manual';
  await until(() => w.eval(`!!listById(${MV})`));
  w.eval(`window._lmerr = ''; setListFolder(${MV}, 'Clients').catch(e => { window._lmerr = String(e && e.stack || e); })`);
  let ask = await until(() => d.querySelector('.cdlg'), 60);
  check(ask && /Take the settings of the folder “Clients”/.test(ask.textContent) && /Workspace: Private → /.test(ask.textContent), '#1188: the move asks first ' + (ask?.textContent || '').replace(/\s+/g, ' ').slice(0, 200)
    + ' ' + w.eval('window._lmerr'));
  if (!ask) { console.log(`${ok} ok, ${F.length} failed`); process.exit(1); }
  click(w, ask.querySelector('[data-cd="no"]')); await sleep(800);
  let st = await call('GET', '/api/state', null, CB);
  check(st.lists.find(l => l.id === MV)?.folder === '' || !st.lists.find(l => l.id === MV)?.folder, '#1188: Cancel leaves the list where it is');
  w.eval(`setListFolder(${MV}, 'Clients')`);
  ask = await until(() => d.querySelector('.cdlg'));
  click(w, ask.querySelector('[data-cd="yes"]'));
  await until(async () => (await call('GET', '/api/state', null, CB)).lists.find(l => l.id === MV)?.org_id === ORG);
  st = await call('GET', '/api/state', null, CB);
  check(st.lists.find(l => l.id === MV)?.folder === 'Clients' && st.lists.find(l => l.id === MV)?.org_id === ORG, '#1188: OK moves it and it takes the workspace');

  // ================= #1214 Hide completed: default, folder, list, "like the default"
  const P = (await call('POST', '/api/lists', {name: 'Plain', org_id: null}, CB)).id;
  check(w.eval(`showDone('l:${P}')`) === true, '#1214: without anything: shown (as before)');
  w.eval(`S.settings.show_done_default = '0'`);
  check(w.eval(`showDone('l:${P}')`) === false, '#1214: the default hide');
  w.eval(`S.settings.show_done_default = '1'`);
  await call('PUT', '/api/folders/props', {folder: 'Clients', props: {hide_done: true}}, CB);
  await w.eval('load()'); await sleep(300);
  check(w.eval(`showDone('l:${MV}')`) === false && w.eval(`showDone('folder:Clients')`) === false, '#1214: the folder default hides in its list and the folder view');
  check(w.eval(`showDone('l:${P}')`) === true, '#1214: a list outside the folder: the default');
  await w.eval(`setShowDone(true, 'l:${MV}')`); await sleep(200);
  check(w.eval(`showDone('l:${MV}')`) === true, '#1214: the list\'s own choice beats the folder');
  const it = w.eval(`lmDoneResetItems('l:${MV}').map(x => x.label)`);
  check(it.length === 1 && /like the default \(hidden\)/.test(it[0]), '#1214: "like the default" in the menu of a list with its own choice ' + JSON.stringify(it));
  await w.eval(`lmDoneReset('l:${MV}')`); await sleep(300);
  check(w.eval(`showDone('l:${MV}')`) === false && w.eval(`lmDoneResetItems('l:${MV}').length`) === 0, '#1214: back to the folder default');
  check(!/"l:\d+"/.test((await call('GET', '/api/state', null, CB)).settings.show_done_views || ''), '#1214: the own entry is gone on the server');
  w.eval(`folderPropsModal('Clients')`); await until(() => d.querySelector('#fs-hd'));
  check(d.querySelector('#fs-hd')?.checked === true, '#1214: Folder settings show Hide completed');  // 2.41.0 (#1423): a switch
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
