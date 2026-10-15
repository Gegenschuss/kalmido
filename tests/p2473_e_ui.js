// 2.47.3 UI tests, part E, own container (start.sh), jsdom:
// - #1727: Cmd/Ctrl-click marks a second list (route lists:<a>,<b>), Shift-click marks the range in sidebar order,
//   Cmd-click again removes one; marked rows are highlighted (data-mark); a plain click opens one list (marks gone)
// - the marked view: title "3 lists", the tasks of all marked lists grouped by list, a bar with Archive / Clear selection;
//   Esc clears the marks (back to the first list)
// - Archive: one question with the number and the skipped list (only viewer rights), then the lists are archived and ONE
//   undo step brings them all back
// - dragging a list to reorder still works (and a drag never marks)
// - phone: the long-press menu's "Select several lists" opens the marked view, a tap adds the next list
// - #1460: the DATEV block in the office settings and the button + dialog in the invoice list (admin)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2473E_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const DESK = {'(hover:hover) and (pointer:fine)': true};
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0, ...o}));
const dnd = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: ''}; e.clientY = 10; el.dispatchEvent(e); return e; };
const settle = () => sleep(600);  // the route and the sidebar follow the address a moment later
const row = (d, id) => d.querySelector(`#side .srow[data-list="${id}"]`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,office,clients'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const L = {};
  for (const n of ['Alpha', 'Bravo', 'Charlie', 'Delta']) L[n] = (await call('POST', '/api/lists', {name: n})).id;
  for (const n of ['Alpha', 'Bravo', 'Charlie', 'Delta']) await call('POST', '/api/tasks', {title: 'Task in ' + n, list_id: L[n]});
  // a list of Bob's, shared with Alice to view only: it can be marked, never archived by her
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab'}, CKB);
  const BL = (await call('POST', '/api/lists', {name: 'Echo of Bob'}, CKB)).id;
  await call('POST', '/api/tasks', {title: 'Task in Echo', list_id: BL}, CKB);
  const ME = (await call('GET', '/api/state')).me.id;
  await call('PUT', `/api/lists/${BL}/members`, {user_id: ME, role: 'view'}, CKB);

  // ================= desktop: marking
  let w = await boot({user: 'alice', hash: 'l/' + L.Alpha, media: DESK}), d = w.document;
  await until(() => w.eval('!!(window.S && S.booted)') && row(d, L.Delta) && row(d, BL));
  click(w, row(d, L.Charlie), {metaKey: true});
  await until(() => w.location.hash.startsWith('#lists/')); await settle();
  check(w.location.hash === `#lists/${L.Alpha},${L.Charlie}`, '#1727: Cmd-click adds a second list to the open one ' + w.location.hash);
  await until(() => row(d, L.Charlie)?.dataset.mark);
  check(row(d, L.Alpha)?.dataset.mark === '1' && row(d, L.Charlie)?.dataset.mark === '1' && !row(d, L.Bravo)?.dataset.mark, '#1727: the marked rows are highlighted');
  click(w, row(d, L.Bravo), {ctrlKey: true});
  await until(() => w.location.hash.split(',').length === 3); await settle();
  check(w.location.hash === `#lists/${L.Alpha},${L.Charlie},${L.Bravo}`, '#1727: Ctrl-click adds one more ' + w.location.hash);
  click(w, row(d, L.Charlie), {metaKey: true});
  await until(() => w.location.hash.split(',').length === 2); await settle();
  check(w.location.hash === `#lists/${L.Alpha},${L.Bravo}`, '#1727: Cmd-click on a marked list removes it ' + w.location.hash);
  // Shift: the range in sidebar order from the last clicked list
  const order = [...d.querySelectorAll('#side .srow[data-list]')].map(x => +x.dataset.list).filter(id => [L.Alpha, L.Bravo, L.Charlie, L.Delta].includes(id));
  click(w, row(d, order[0]));  // a plain click: opens that list, the marks are gone
  await until(() => w.location.hash === '#l/' + order[0]); await settle();
  check(w.location.hash === '#l/' + order[0] && !d.querySelector('#side .srow[data-mark]'), '#1727: a plain click opens one list, no marks left');
  click(w, row(d, order[2]), {shiftKey: true});
  await until(() => w.location.hash.startsWith('#lists/')); await settle();
  check(w.location.hash === '#lists/' + order.slice(0, 3).join(','), '#1727: Shift-click marks the range in sidebar order ' + w.location.hash + ' / ' + order.join());
  await until(() => d.querySelector('#top .dxbar'));
  // the view: title, groups, bar
  const title = d.querySelector('#top h1')?.textContent || w.eval('viewTitle ? viewTitle() : ""');
  check(/3 lists/.test(d.querySelector('#view')?.textContent || '') || /3 lists/.test(title || '') || /3 lists/.test(d.title), '#1727: the view is titled "3 lists" ' + title);
  const vt = d.querySelector('#view')?.textContent || '';
  check(order.slice(0, 3).every(id => vt.includes('Task in ' + w.eval(`listById(${id}).name`))) && !vt.includes('Task in ' + w.eval(`listById(${order[3]}).name`)), '#1727: the tasks of the marked lists, no others');
  check(d.querySelectorAll('#top .dxbar [data-act="dx-archive"], #top .dxbar [data-act="dx-clear"]').length === 2, '#1727: the bar with Archive and Clear selection');
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  await until(() => w.location.hash === '#l/' + order[0]); await settle();
  check(w.location.hash === '#l/' + order[0] && !d.querySelector('#side .srow[data-mark]'), '#1727: Esc clears the marks ' + w.location.hash);

  // dragging still reorders (and does not mark)
  const before = (await call('GET', '/api/state')).lists.filter(l => !l.is_inbox && !l.archived).sort((a, b) => a.sort - b.sort || a.id - b.id).map(l => l.id);
  const src = row(d, order[3]), tgt = row(d, order[0]);
  dnd(w, src, 'dragstart'); await sleep(30); dnd(w, tgt, 'dragover'); dnd(w, tgt, 'drop'); dnd(w, src, 'dragend');
  await sleep(1200);
  const after = (await call('GET', '/api/state')).lists.filter(l => !l.is_inbox && !l.archived).sort((a, b) => a.sort - b.sort || a.id - b.id).map(l => l.id);
  check(after.indexOf(order[3]) < after.indexOf(order[0]) && before.indexOf(order[3]) > before.indexOf(order[0]), `#1727: dragging a list still reorders: ${before} -> ${after}`);
  check(!w.location.hash.startsWith('#lists/'), '#1727: a drag marks nothing');

  // ================= archive several lists: one question, skipped list named, one undo
  w.eval(`go('lists/${L.Alpha},${L.Bravo},${BL}')`);
  await until(() => d.querySelector('#top .dxbar [data-act="dx-archive"]'));
  click(w, d.querySelector('#top .dxbar [data-act="dx-archive"]'));
  await until(() => d.querySelector('.modal.cdlg'));
  const q = d.querySelector('.modal.cdlg')?.textContent || '';
  check(/Archive 2 lists\?/.test(q) && q.includes('Echo of Bob') && /no right/i.test(q), '#1727: one question with the number, the list without the right is named ' + q.slice(0, 200));
  d.querySelector('.modal.cdlg [data-cd="yes"]').click();
  await until(async () => (await call('GET', '/api/state')).lists.filter(l => [L.Alpha, L.Bravo].includes(l.id) && l.archived).length === 2);
  let st = await call('GET', '/api/state');
  const arch = id => !!st.lists.find(l => l.id === id)?.archived;
  check(arch(L.Alpha) && arch(L.Bravo) && !arch(BL) && !arch(L.Charlie), '#1727: the two own lists are archived, Bob\'s is not');
  await until(() => !d.querySelector('.modal.cdlg') && /archived/i.test(d.getElementById('toast')?.textContent || ''));
  check(/2 lists archived/.test(d.getElementById('toast')?.textContent || ''), '#1727: the toast says 2 lists archived ' + d.getElementById('toast')?.textContent);
  check(w.eval('HIST.undo.length') >= 1 && /Archived 2 lists/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), '#1727: one undo step for all of them');
  await w.eval('histStep("undo")');
  await until(async () => (await call('GET', '/api/state')).lists.filter(l => [L.Alpha, L.Bravo].includes(l.id) && !l.archived).length === 2);
  st = await call('GET', '/api/state');
  check(!arch(L.Alpha) && !arch(L.Bravo), '#1727: one undo brings both lists back');
  w.close();

  // ================= phone: the long-press menu starts the marking, a tap adds
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + L.Charlie}); d = w.document;
  await until(() => w.eval('!!(window.S && S.booted)') && row(d, L.Delta));
  const items = w.eval(`listMenuItems(${L.Charlie}, document.querySelector('#side .srow[data-list="${L.Charlie}"]')).filter(x => x && x.label).map(x => x.label)`);
  check(items.includes('Select several lists'), '#1727 phone: the list menu has "Select several lists" ' + items.join('|'));
  w.eval(`listMenuItems(${L.Charlie}, document.querySelector('#side .srow[data-list="${L.Charlie}"]')).find(x => x && x.label === 'Select several lists').fn()`);
  await until(() => w.location.hash === '#lists/' + L.Charlie); await settle();
  check(w.location.hash === '#lists/' + L.Charlie, '#1727 phone: "Select" opens the marked view with this list');
  click(w, row(d, L.Delta));
  await until(() => w.location.hash.includes(',')); await settle();
  check(w.location.hash === `#lists/${L.Charlie},${L.Delta}`, '#1727 phone: in the marked view a tap adds a list ' + w.location.hash);
  w.close();

  // ================= #1460: DATEV settings block + export dialog (admin of an organisation)
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Studio Test', admin_id: ME})).id;
  await call('PATCH', '/api/settings', {workspace: 'org:' + ORG});
  w = await boot({user: 'alice', hash: 'office/settings', media: DESK}); d = w.document;
  await until(() => d.querySelector('#dx-adv'));
  check(!!d.querySelector('.dxset #dx-adv') && !!d.querySelector('#dx-chart') && d.querySelector('#dx-a-standard')?.placeholder === '8400', '#1460: the DATEV block in the settings with the chart default as placeholder');
  d.querySelector('#dx-adv').value = '1234567'; d.querySelector('#dx-cli').value = '42';
  await w.eval(`ofcSaveSettings(document.getElementById('ofc-set'))`);
  const s2 = (await call('GET', '/api/office/settings')).settings.datev_extf || {};
  check(s2.advisor_no === '1234567' && s2.client_no === '42' && s2.chart === 'SKR03', '#1460: the block is saved with the settings ' + JSON.stringify(s2));
  w.eval(`go('office/offers')`);
  await until(() => d.querySelector('[data-ofd="kind"][data-kind="invoice"]'));
  d.querySelector('[data-ofd="kind"][data-kind="invoice"]')?.click();
  await until(() => d.querySelector('[data-dx="extf"]'));
  check(!!d.querySelector('[data-dx="extf"]'), '#1460: "DATEV export" in the invoice list');
  d.querySelector('[data-dx="extf"]')?.click();
  await until(() => d.querySelector('.modal #dx-from'));
  const f0 = d.querySelector('.modal #dx-from')?.value || '', t0 = d.querySelector('.modal #dx-to')?.value || '';
  check(/^\d{4}-\d\d-01$/.test(f0) && t0 > f0 && t0.slice(0, 7) === f0.slice(0, 7), `#1460: the dialog proposes the previous month ${f0} - ${t0}`);
  w.close();

  console.log(`p2473_e_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
