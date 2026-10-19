// 2.119.1 UI tests, part C, own container (start.sh; P21191C_NOSTART=1: a running server). jsdom:
// - #2304: deleting an ACTIVE list (archived first by the delete): the undo right after brings it back active (not into the
//   archive), with its folder, position and task; redo moves it into the trash again; an archived list still comes back archived
// - #2298: the framework contract dialog offers "Move to another workspace…" (office admin, another workspace there); the
//   move dialog names the contract with its files; moved -> in the organisation's office, one undo step brings it back.
//   A plain member of the organisation does not get the button; a person without an organisation neither (no other workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P21191C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const st = () => call('GET', '/api/state');
  const lst = async id => (await st()).lists.find(l => l.id === id);

  // ================= #2304 an active list: undo brings it back active, folder + position kept
  await call('POST', '/api/lists', {name: 'Alpha', folder: 'Work'});
  const L = (await call('POST', '/api/lists', {name: 'Garden', folder: 'Work'})).id;
  await call('PATCH', `/api/lists/${L}`, {sort: 7});
  const T = (await call('POST', '/api/tasks', {title: 'Water the roses', list_id: L})).id;
  const before = await lst(L);
  check(before && !before.archived && before.folder === 'Work', 'setup: an active list in the folder Work ' + JSON.stringify(before || {}).slice(0, 200));
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  w.__dialogs = 'manual';
  await until(() => w.eval(`!!listById(${L})`));
  const p = w.eval(`listDeleteForGood(${L})`);
  const dlg = await until(() => d.querySelector('.modal.cdlg [data-cd="yes"]') && d.querySelector('.modal.cdlg'));
  click(w, dlg.querySelector('[data-cd="yes"]'));
  check(await p === true && await until(async () => !(await st()).lists.some(l => l.id === L), 60), 'the list is gone from the state');
  check(await until(async () => (await call('GET', '/api/trash/lists')).lists?.some(x => x.id === L), 60), 'it is in the list trash');
  const toast = await until(() => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && /moved to the trash/.test(t.textContent) ? t : null; });
  check(toast && /Undo/.test(toast.textContent), 'the toast offers Undo ' + (toast?.textContent || ''));
  await w.eval(`histStep('undo')`);
  const back = await until(async () => { const x = await lst(L); return x && !x.archived ? x : null; }, 60);
  check(!!back, '#2304: undo brings the list back ACTIVE, not into the archive ' + JSON.stringify(await lst(L) || {}).slice(0, 200));
  check(back && back.folder === 'Work' && back.sort === before.sort && back.name === 'Garden', '#2304: folder and position as before ' + JSON.stringify(back || {}).slice(0, 200));
  check((await call('GET', `/api/tasks/${T}`)).status !== 404 && !(await call('GET', '/api/trash/lists')).lists?.some(x => x.id === L), 'its task is back, nothing left in the trash');
  check(await until(() => w.eval(`!!listById(${L}) && !listById(${L}).archived`), 60), 'the client shows it as an active list again');
  await w.eval(`histStep('redo')`);
  check(await until(async () => (await call('GET', '/api/trash/lists')).lists?.some(x => x.id === L), 60), 'redo: into the trash again');
  await w.eval(`histStep('undo')`);
  check(await until(async () => { const x = await lst(L); return x && !x.archived; }, 60), 'undo after redo: active again');

  // an archived list keeps the old rule: the undo brings it back into the archive
  const A = (await call('POST', '/api/lists', {name: 'Old notes'})).id;
  await call('PATCH', `/api/lists/${A}`, {archived: 1});
  w.eval('load().then(render)');
  await until(() => w.eval(`!!listById(${A})`));
  const p2 = w.eval(`listDeleteForGood(${A})`);
  const dlg2 = await until(() => d.querySelector('.modal.cdlg [data-cd="yes"]') && d.querySelector('.modal.cdlg'));
  click(w, dlg2.querySelector('[data-cd="yes"]'));
  check(await p2 === true && await until(async () => (await call('GET', '/api/trash/lists')).lists?.some(x => x.id === A), 60), 'archived list: into the trash');
  await w.eval(`histStep('undo')`);
  check(await until(async () => { const x = await lst(A); return x && x.archived; }, 60), 'archived list: undo brings it back archived');
  w.close();

  // ================= #2298 framework contracts: the move button in the contract dialog
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'clients,office'});
  const ORG = (await st()).me.workspaces[0].id;
  await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  const CB = await login('bob'), CF = await login('frida');
  for (const ck of [CB, CF]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'clients,office'}, ck);
  await call('PATCH', '/api/settings', {workspace: 'private'});
  const C = (await call('POST', '/api/office/contracts', {name: 'Rahmenvertrag Nord'})).id;
  check(!!C, 'setup: a private framework contract');
  const openC = async (w, cid) => {
    const d = w.document;
    const row = await until(() => d.querySelector(`[data-ofc="open"][data-kind="contracts"][data-id="${cid}"]`), 60);
    if (!row) return null;
    click(w, row);
    return until(() => d.querySelector('.modal.ofcdlg'));
  };
  w = await boot({user: 'alice', hash: 'office/contracts'}); d = w.document;
  let md = await openC(w, C);
  const mvb = md && md.querySelector('[data-m="move"]');
  check(!!mvb && /Move to another workspace/.test(mvb.textContent), '#2298: the contract dialog offers the move');
  if (mvb) click(w, mvb);
  const smv = await until(() => d.querySelector('.smv-dlg'));
  check(!!smv && /Rahmenvertrag Nord/.test(smv.querySelector('.smv-what')?.textContent || ''), '#2298: the move dialog names the contract');
  check(await until(() => /framework contract moves with its PDF files/.test(smv?.querySelector('.smv-notes')?.textContent || '')), '#2298: the dry run note ' + (smv?.querySelector('.smv-notes')?.textContent || ''));
  const yes = smv && await until(() => { const b = smv.querySelector('[data-smv="yes"]'); return b && !b.disabled ? b : null; });
  if (yes) click(w, yes);
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  const inOrg = async () => ((await call('GET', '/api/office/contracts?archived=1')).items || []).some(x => x.id === C);
  check(await until(inOrg, 60), '#2298: the contract is in the organisation\'s office');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await inOrg()), 60), '#2298: one undo step takes it back');
  await call('PATCH', '/api/settings', {workspace: 'private'});
  check(((await call('GET', '/api/office/contracts')).items || []).some(x => x.id === C), '#2298: back in the personal office');
  w.close();
  // a plain member: no button (the routes of contracts are for admins)
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`}, CB);
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  const CO2 = (await call('POST', '/api/office/contracts', {name: 'Vertrag der Organisation'})).id;
  w = await boot({user: 'bob', hash: 'office/contracts'});
  md = await openC(w, CO2);
  check(md && !md.querySelector('[data-m="move"]'), '#2298: a plain member gets no move button');
  w.close();
  // freelancer-matrix: office - a person without an organisation: no other workspace, no button
  const CFr = (await call('POST', '/api/office/contracts', {name: 'Rahmenvertrag privat'}, CF)).id;
  w = await boot({user: 'frida', hash: 'office/contracts'});
  md = await openC(w, CFr);
  check(md && !md.querySelector('[data-m="move"]'), '#2298: without an organisation there is no move button');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
