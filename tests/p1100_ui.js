// 1.10.0 UI tests (jsdom), fresh DB: list roles in the list dialog (role picker with one-line explanations, admins manage,
// the owner never gets a picker, members see names only), the assignee column (picture / dashed "nobody" circle per row,
// click -> assign menu -> saved, desktop column + phone cell, subtasks in the detail panel, hidden per list via "…"),
// the participant's view (only their tasks, sections with their tasks only, the read-only context parent without notes /
// comments / files, no delete, no list change, no section tools, quick add works and the task stays theirs), German.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments';
const cks = {};
const call = async (u, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cks[u]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const menuItems = d => [...d.querySelectorAll('.menu-list [role="menuitem"]')];

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  cks.alice = await login('alice');
  const id = {alice: 1};
  for (const [u, n] of [['bob', 'Bob'], ['carol', 'Carol'], ['pete', 'Pete']]) {
    id[u] = (await call('alice', 'POST', '/api/users', {username: u, display_name: n, password: 'password123'})).id;
    cks[u] = await login(u);
  }
  for (const u of Object.keys(cks)) await call(u, 'PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const L = (await call('alice', 'POST', '/api/lists', {name: 'Film'})).id;
  const sA = (await call('alice', 'POST', '/api/sections', {list_id: L, name: 'Alpha'})).id;
  const sB = (await call('alice', 'POST', '/api/sections', {list_id: L, name: 'Beta'})).id;
  const sG = (await call('alice', 'POST', '/api/sections', {list_id: L, name: 'Gamma'})).id;
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: id.bob, role: 'admin'});
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: id.carol, role: 'edit'});
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: id.pete, role: 'participant'});
  const mk = async (u, b) => (await call(u, 'POST', '/api/tasks', b)).id;
  const T1 = await mk('alice', {title: 'Pete top', list_id: L, section_id: sA, assignee_id: id.pete});
  const T2 = await mk('alice', {title: 'Parent secret', list_id: L, section_id: sB, content: 'PARENT-NOTES', assignee_id: id.carol});
  const T2a = await mk('alice', {title: 'Pete sub', parent_id: T2, assignee_id: id.pete});
  const T2b = await mk('alice', {title: 'Sibling hidden', parent_id: T2});
  const T3 = await mk('alice', {title: 'Nobody yet', list_id: L, section_id: sG});
  await call('alice', 'POST', `/api/tasks/${T2}/comments`, {body: 'PARENT-COMMENT'});

  // ---- owner: members dialog with the role picker
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`listModal(${L})`); await sleep(900);
  let md = [...d.querySelectorAll('.modal')].at(-1);
  const sel = md.querySelector(`[data-mrole="${id.pete}"]`);
  check(sel && [...sel.options].map(o => o.value).join() === 'admin,edit,participant,view' && sel.value === 'participant', 'role picker: 4 roles, current selected');
  check([...sel.options].map(o => o.textContent).join() === 'Admin,Member,Participant,Viewer' && sel.options[2].title === 'Sees only the tasks assigned to them', 'role names + one-line explanation');
  const help = md.querySelector('.rolehelp');
  check(help && /Participant\s*Sees only the tasks assigned to them/.test(help.textContent) && /Viewer\s*Sees everything, changes nothing/.test(help.textContent), 'role legend under the members');
  check(!md.querySelector(`[data-mrole="${id.alice}"]`) && /Owner/.test(md.querySelector(`.mrow[data-uid="${id.alice}"]`).textContent), 'owner row: no picker');
  const addrole = md.querySelector('#l-addrole');
  check(!addrole || addrole.value === 'edit', 'add row defaults to Member');
  sel.value = 'view'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900);
  check((await call('alice', 'GET', '/api/state')).lists.find(x => x.id === L).members.find(m => m.user_id === id.pete).role === 'view', 'role changed via the picker');
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: id.pete, role: 'participant'});
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());

  // ---- assignee column (desktop): picture or dashed circle, click -> menu -> assigned
  await w.eval('load()'); w.eval('render()'); await sleep(300);
  const row3 = d.querySelector(`.trow[data-id="${T3}"]`);
  const cw = row3.querySelector('.tcols .c-who .whob');
  check(cw && cw.tagName === 'BUTTON' && cw.querySelector('.who.none') && cw.dataset.act === 'assign', 'unassigned row: dashed circle button');
  check(d.querySelector(`.trow[data-id="${T1}"] .c-who .whob .who:not(.none)`)?.textContent === 'P', 'assigned row: avatar (initials)');
  check(!row3.querySelector('.meta .who'), 'no duplicate avatar in the meta line');
  cw.click(); await sleep(300);
  let items = menuItems(d);
  check(items.map(b => b.textContent.trim()).join('|') === 'Nobody|Alice (me)|Bob|Carol|Pete · Participant', 'assign menu: nobody + people (roles noted): ' + items.map(b => b.textContent.trim()).join('|'));
  items.find(b => /Carol/.test(b.textContent)).click(); await sleep(900);
  check((await call('alice', 'GET', `/api/tasks/${T3}`)).assignee_id === id.carol, 'assigned from the column');
  check(d.querySelector(`.trow[data-id="${T3}"] .c-who .who`)?.textContent === 'C', 'column shows the new assignee');
  // subtask in the detail panel: own assign cell
  w.eval(`openDetail(${T2})`); await sleep(800);
  const subBtn = d.querySelector(`#detail .subs .trow[data-id="${T2b}"] .wcell .whob`);
  check(subBtn && subBtn.querySelector('.who.none'), 'subtask row in the detail panel: assign cell');
  subBtn.click(); await sleep(300);
  menuItems(d).find(b => /Bob/.test(b.textContent)).click(); await sleep(900);
  check((await call('alice', 'GET', `/api/tasks/${T2b}`)).assignee_id === id.bob, 'subtask assigned independently of its parent');
  check((await call('alice', 'GET', `/api/tasks/${T2}`)).assignee_id === id.carol, 'parent keeps its assignee');
  w.eval('closeDetail()'); await sleep(200);
  // hide the column per list
  const hideIt = w.eval(`listMenuItems(${L}, document.body)`).find(x => x.label === 'Hide assignee column');
  check(!!hideIt, 'list "…" offers Hide assignee column');
  hideIt.fn(); await sleep(300);
  check(!d.querySelector(`.trow[data-id="${T3}"] .whob`) && d.querySelector(`.trow[data-id="${T3}"] .c-who .who`)?.textContent === 'C', 'hidden: plain avatar as before, no buttons');
  check(w.eval(`listMenuItems(${L}, document.body)`).some(x => x.label === 'Show assignee column'), 'and back: Show assignee column');
  w.eval(`listMenuItems(${L}, document.body)`).find(x => x.label === 'Show assignee column').fn(); await sleep(200);
  w.close();

  // ---- phone: compact cell at the row end
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true}); d = w.document; await sleep(300);
  const pc = d.querySelector(`.trow[data-id="${T1}"] .wcell .whob`);
  check(pc && pc.querySelector('.who')?.textContent === 'P', 'phone: assignee cell at the row end');
  pc.click(); await sleep(300);
  check(menuItems(d).length === 5, 'phone: the same assign menu');
  d.body.click(); w.close();

  // ---- admin: manages members (picker), no picker for the owner
  w = await boot({user: 'bob', hash: 'l/' + L}); d = w.document;
  w.eval(`listModal(${L})`); await sleep(900);
  md = [...d.querySelectorAll('.modal')].at(-1);
  check(md.querySelector(`[data-mrole="${id.pete}"]`) && md.querySelector(`[data-mrole="${id.carol}"]`), 'admin: role pickers for members');
  check(!md.querySelector(`[data-mrole="${id.alice}"]`) && !md.querySelector(`[data-mrole="${id.bob}"]`), 'admin: none for the owner or himself');
  w.close();
  // member: names and roles only
  w = await boot({user: 'carol', hash: 'l/' + L}); d = w.document;
  w.eval(`listModal(${L})`); await sleep(900);
  md = [...d.querySelectorAll('.modal')].at(-1);
  check(!md.querySelector('[data-mrole]') && /Participant/.test(md.querySelector(`.mrow[data-uid="${id.pete}"]`).textContent), 'member: roles as text, no pickers');
  w.close();

  // ---- participant view
  w = await boot({user: 'pete', hash: 'l/' + L}); d = w.document; await sleep(300);
  const rows = [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id);
  check(rows.includes(T1) && rows.includes(T2) && rows.includes(T2a) && !rows.includes(T2b) && !rows.includes(T3), 'participant list: own tasks + context parent ' + rows);
  const heads = [...d.querySelectorAll('#view .ghead')].map(h => h.textContent);
  check(heads.some(h => /Alpha/.test(h)) && heads.some(h => /Beta/.test(h)) && !heads.some(h => /Gamma/.test(h)), 'sections only where my tasks are: ' + heads.join('|'));
  check(/Participant: you see only the tasks assigned to you/.test(d.querySelector('.rohint')?.textContent || ''), 'participant hint');
  check(!d.querySelector('[data-act="section-new"]') && !d.querySelector('[data-act="section-menu"]'), 'no section tools');
  check(d.querySelector(`.trow[data-id="${T2}"]`).classList.contains('ro') && !d.querySelector(`.trow[data-id="${T1}"]`).classList.contains('ro'), 'context parent read-only, own task not');
  check(!d.querySelector('#view button.whob'), 'participant cannot assign (no buttons)');
  check(d.querySelector(`.trow[data-id="${T1}"] .whob .who`)?.textContent === 'P', 'but sees the assignee');
  check(!w.eval('S.tasks.has(' + T2b + ')') && w.eval(`S.tasks.get(${T2}).content`) === '', 'no hidden data in the client state');
  // today / all: the context parent is not a task of mine there
  w.eval(`go('all')`); await sleep(300);
  check(![...d.querySelectorAll('#view .trow')].some(r => +r.dataset.id === T2) || d.querySelector(`#view .trow[data-id="${T2a}"]`), 'smart view: context parent not listed on its own');
  w.eval(`go('l/${L}')`); await sleep(300);
  // context detail: read-only, no comments / time / deps
  w.eval(`openDetail(${T2})`); await sleep(900);
  check(/Context/.test(d.querySelector('#detail .rotag')?.textContent || '') && !d.querySelector('#detail #d-tl') && !/PARENT/.test(d.querySelector('#detail').textContent), 'context detail: tag, no comments, no notes');
  check(d.querySelector('#d-title').readOnly && d.querySelector('#d-assignee')?.disabled !== false, 'context detail read-only');
  w.eval('closeDetail()');
  // own task detail: editable, but no delete / list change / assignee change
  w.eval(`openDetail(${T1})`); await sleep(900);
  check(!d.querySelector('#d-title').readOnly && d.querySelector('#d-list').disabled && d.querySelector('#d-assignee').disabled, 'own task: editable, list + assignee locked');
  check(d.querySelector('#d-tl'), 'own task: comments');
  d.querySelector('#detail [data-act="task-menu"]').click(); await sleep(300);
  check(!menuItems(d).some(b => /^Delete$/.test(b.textContent.trim())), 'no Delete in the task menu');
  d.body.click(); w.eval('closeDetail()'); await sleep(200);
  // quick add: allowed, the task is mine
  const qi = d.querySelector('#qinput');
  check(!!qi, 'quick add available in the participant list');
  qi.value = 'Pete adds this'; await w.eval(`submitQuick(document.querySelector('#qinput'))`); await sleep(1500);
  const mine = (await call('alice', 'GET', '/api/state')).tasks.find(t => t.title === 'Pete adds this');
  check(mine && mine.list_id === L && mine.assignee_id === id.pete, 'quick add: in the list, assigned to me ' + JSON.stringify(mine && {l: mine.list_id, a: mine.assignee_id}));
  w.close();

  // ---- German
  await call('alice', 'PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`listModal(${L})`); await sleep(900);
  md = [...d.querySelectorAll('.modal')].at(-1);
  check([...md.querySelector(`[data-mrole="${id.pete}"]`).options].map(o => o.textContent).join() === 'Admin,Mitglied,Teilnehmer,Betrachter', 'German role names');
  check(/Sieht nur die eigenen, zugewiesenen Aufgaben/.test(md.querySelector('.rolehelp').textContent), 'German explanations');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  check(w.eval(`listMenuItems(${L}, document.body)`).some(x => x.label === 'Spalte „Zuständig“ ausblenden'), 'German column toggle');
  w.close();

  const bad = errs.filter(e => !/Could not parse CSS/.test(e));
  check(!bad.length, 'no script errors: ' + bad.slice(0, 3).join(' | '));
  console.log(`\np1100_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
