// 2.41.0 UI tests (agent D), own container (start.sh). jsdom:
// - #1365 list settings: "Show in My tasks" (only for me, saves at once with Undo); My tasks: the tasks of a switched-off list
//   in the folded group "Hidden (N)" at the end with "Show the list again" per list, my tasks of it due today / overdue in the
//   small group "From hidden lists"; the sidebar count leaves the hidden ones out (the due ones count); "Grouped by list" too
// - #1471 list settings: the switch "Time tracking" for every list type (off; hours / rate only with it on), the timer in the
//   task panel follows it, the project hint no longer promises time tracking
// - #1205 "Waiting on": the recent entries below the field (filter while typing, a tap takes one, the x removes it from the
//   suggestions only), in the multi-edit dialog too; on a phone they show when the dialog opens, big rows
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
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const ghead = (d, cls) => d.querySelector(`#view .ghead.${cls}`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['comments', 'time']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,time,comments,deps,timeline,progress'});
  const st0 = await call('GET', '/api/state'), ME = st0.me;
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const day = n => { const x = new Date(Date.now() + n * 864e5); return x.toLocaleDateString('sv'); };
  const TEAM = (await call('POST', '/api/lists', {name: 'Team'})).id;
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: bob.id, role: 'edit'});
  const INS = (await call('POST', '/api/lists', {name: 'Insurance'})).id;
  const PRJ = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const TT = await mk('Team work', TEAM, {assignee_id: ME.id});
  const PAY = await mk('Pay the premium', INS, {assignee_id: ME.id, due: day(0)});
  const REN = await mk('Renew the contract', INS, {assignee_id: ME.id, due: day(5)});
  const UND = await mk('Sort the letters', INS);  // undated, unassigned, a list only I use: "From your lists, without a date"
  const PT = await mk('Write the plan', PRJ, {assignee_id: ME.id});

  // ================= #1365 the switch in the list settings
  let w = await boot({user: 'alice', hash: 'assigned'}), d = w.document;
  const c0 = w.eval('counts().assigned');
  check(c0 === 4, '#1365: My tasks counts every task of mine at first: ' + c0);
  check(!ghead(d, 'mthid') && !ghead(d, 'mturg'), '#1365: nothing hidden at first');
  w.eval(`listModal(${INS})`); await sleep(200);
  let md = lastModal(d), sw = md.querySelector('#l-inmine');
  check(sw && sw.checked && /only for you/.test(sw.closest('.row').textContent), '#1365: list settings: "Show in My tasks", on, only for you');
  sw.checked = false; change(w, sw);
  check(await until(async () => ((await call('GET', '/api/state')).mine_hidden || []).includes(INS)), '#1365: saved at once on the server');
  check(await until(() => /is hidden in My tasks/.test(d.querySelector('#toast')?.textContent || '')), '#1365: a message with Undo');
  click(w, d.querySelector('#toast button'));
  check(await until(async () => !((await call('GET', '/api/state')).mine_hidden || []).includes(INS)) && md.querySelector('#l-inmine').checked, '#1365: Undo shows the list again (the switch follows)');
  sw = md.querySelector('#l-inmine'); sw.checked = false; change(w, sw);
  await until(async () => ((await call('GET', '/api/state')).mine_hidden || []).includes(INS));
  md.remove();
  w.eval('render()'); await sleep(200);
  // ================= #1365 My tasks with a hidden list
  const urg = ghead(d, 'mturg'), hid = ghead(d, 'mthid');
  check(urg && /From hidden lists/.test(urg.textContent) && urg.closest('.group').querySelector(`.trow[data-id="${PAY}"]`), '#1365: due today from a hidden list: the small group "From hidden lists"');
  check(hid && /Hidden/.test(hid.textContent) && hid.querySelector('.c')?.textContent === '2' && hid.classList.contains('closed'), '#1365: "Hidden (2)" folded: ' + (hid?.textContent || ''));
  check(!hid.closest('.group').querySelector('.trow'), '#1365: folded = no rows');
  const groups = [...d.querySelectorAll('#view .ghead')].map(x => x.className);
  check(/mthid/.test(groups[groups.length - 1]) && groups.findIndex(x => /mturg/.test(x)) === groups.length - 2, '#1365: both at the end, Hidden last: ' + groups.join(' | '));
  check(d.querySelector(`#view .trow[data-id="${TT}"]`) && !d.querySelector(`#view .trow[data-id="${REN}"]`), '#1365: the other lists unchanged, the hidden task not in the open list');
  check(w.eval('counts().assigned') === 3, '#1365: the sidebar counts the open ones + the due one, not the later one: ' + w.eval('counts().assigned'));
  click(w, hid); await sleep(200);
  const hg = ghead(d, 'mthid').closest('.group');
  check(!ghead(d, 'mthid').classList.contains('closed') && hg.querySelector(`.trow[data-id="${REN}"]`) && hg.querySelector(`.trow[data-id="${UND}"]`), '#1365: opened: the later task and the undated one');
  const head = hg.querySelector('.mthl');
  check(head && /Insurance/.test(head.textContent) && head.querySelector('[data-mt="show"]') && /Show the list again/.test(head.textContent), '#1365: one head per list with "Show the list again"');
  // grouped by list: the hidden list has no group of its own
  w.eval("S.settings.mine_view = 'lists'; render()"); await sleep(200);
  check(!d.querySelector(`#view .group[data-kbg="l:${INS}"]`) && ![...d.querySelectorAll('#view .ghead')].some(x => !/mthid|mturg/.test(x.className) && /Insurance/.test(x.textContent)) && ghead(d, 'mthid'), '#1365: grouped by list: no Insurance group, the Hidden group stays');
  w.eval("S.settings.mine_view = 'own'; render()"); await sleep(200);
  // other views are unchanged
  w.eval("go('today')"); await sleep(400);
  check(d.querySelector(`#view .trow[data-id="${PAY}"]`), '#1365: Today still shows the task of the hidden list');
  w.eval("go('assigned')"); await sleep(400);
  click(w, ghead(d, 'mthid').closest('.group').querySelector('[data-mt="show"]'));
  check(await until(async () => ((await call('GET', '/api/state')).mine_hidden || []).length === 0) && await until(() => !ghead(d, 'mthid') && !ghead(d, 'mturg')), '#1365: "Show the list again": back in My tasks');
  check(w.eval('counts().assigned') === 4, '#1365: the count is whole again');
  // the own order still works: a drag changes only the own order
  w.eval(`moSave([${REN}, ${TT}, ${PAY}, ${PT}])`);
  check(await until(async () => (await call('GET', '/api/state')).mine_order?.[REN] === 0), '#1365 / #1344: the own order is saved as before');
  w.close();

  // ================= #1471 the switch "Time tracking"
  w = await boot({user: 'alice', hash: 'l/' + PRJ}); d = w.document;
  w.eval(`openDetail(${PT})`); await sleep(300);
  check(!d.querySelector('#detail [data-act="timer-toggle"]') && !d.querySelector('#d-time'), '#1471: a project without the switch: no timer in the task panel');
  w.eval('closeDetail()');
  w.eval(`listModal(${PRJ})`); await sleep(200);
  md = lastModal(d);
  const tt = md.querySelector('#l-time');
  check(tt && !tt.checked && md.querySelector('.ltimex')?.hidden && !tt.closest('.kproj'), '#1471: the switch "Time tracking", off, not in the project-only part; hours / rate hidden');
  check(!/time tracking/.test(md.querySelector('#l-khint').textContent), '#1471: the project hint no longer names time tracking');
  tt.checked = true; change(w, tt);
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === PRJ).time_tracking === 1) && !md.querySelector('.ltimex').hidden, '#1471: on: saved at once, hours / rate shown');
  md.remove();
  w.eval(`openDetail(${PT})`); await sleep(300);
  check(await until(() => d.querySelector('#detail [data-act="timer-toggle"]')), '#1471: the timer is there');
  w.eval('closeDetail()');
  w.eval(`listModal(${TEAM})`); await sleep(200);
  check(lastModal(d).querySelector('#l-time') && !lastModal(d).querySelector('#l-time').checked, '#1471: a plain list has the switch too');
  lastModal(d).remove();
  w.close();

  // ================= #1205 Waiting on: recent entries
  const W = [];
  for (const n of ['Offer from the carpenter', 'Tax office', 'Delivery of the chairs']) { const id = await mk('W ' + n, TEAM); W.push(id); await call('PUT', `/api/tasks/${id}/waiting`, {note: n}); }
  await call('PUT', `/api/tasks/${TT}/waiting`, {note: 'Bobs supplier'}, await login('bob'));  // another person's text
  const NEW = await mk('Needs an answer', TEAM);
  w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  w.eval(`waitDialog(${NEW})`); await sleep(300);
  md = lastModal(d);
  const inp = md.querySelector('#w-note'), box = () => md.querySelector('.wsug');
  check(box() && box().hidden, '#1205: computer: the list waits for the first keystroke');
  inp.value = ''; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => box() && !box().hidden && box().querySelectorAll('.wsrow').length === 3), '#1205: typing shows the recent entries: ' + (box()?.textContent || ''));
  const rows = () => [...box().querySelectorAll('.wspick')].map(x => x.textContent);
  check(rows()[0] === 'Delivery of the chairs' && !rows().includes('Bobs supplier'), '#1205: newest first, only my own: ' + rows().join(' | '));
  inp.value = 'off'; inp.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(100);
  check(rows().join() === 'Offer from the carpenter,Tax office', '#1205: typing filters: ' + rows().join(' | '));
  click(w, box().querySelector('[data-wsx="1"]'));
  check(await until(() => rows().join() === 'Offer from the carpenter'), '#1205: x removes it from the list');
  check(await until(async () => !(await call('GET', '/api/me/wait-suggestions')).items.some(x => x.note === 'Tax office')), '#1205: ... on the server too');
  check((await call('GET', `/api/tasks/${W[1]}`)).wait_note === 'Tax office', '#1205: the task keeps its text');
  const xb = box().querySelector('.wsx');
  check(xb && xb.getAttribute('aria-label') && /Remove/.test(xb.getAttribute('aria-label')), '#1205: the x has a label');
  inp.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true}));
  inp.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
  check(inp.value === 'Offer from the carpenter' && box().hidden && lastModal(d) === md, '#1205: arrow + Enter takes the entry (the dialog stays open)');
  click(w, md.querySelector('[data-m="ok"]'));
  check(await until(async () => (await call('GET', `/api/tasks/${NEW}`)).wait_note === 'Offer from the carpenter'), '#1205: saved with the chosen text');
  // multi-edit: the same list
  w.eval(`S.multi = new Set([${W[0]}, ${W[2]}]); meWaitDialog()`); await sleep(300);
  md = lastModal(d);
  const mi = md.querySelector('#mw-note');
  mi.value = ''; mi.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => md.querySelector('.wsug') && !md.querySelector('.wsug').hidden && md.querySelectorAll('.wsug .wsrow').length >= 2), '#1205: multi-edit dialog: the same suggestions');
  click(w, md.querySelector('.wsug [data-ws="0"]'));
  check(mi.value === (await call('GET', '/api/me/wait-suggestions')).items[0].note, '#1205: a tap takes it');
  md.remove();
  w.close();
  // phone: the list opens with the dialog
  const PH = await mk('Phone task', TEAM);
  w = await boot({user: 'alice', hash: 'l/' + TEAM, mobile: true}); d = w.document;
  w.eval(`waitDialog(${PH})`);
  check(await until(() => lastModal(d)?.querySelector('.wsug:not([hidden]) .wsrow')), '#1205: phone: the recent entries show when the dialog opens');
  w.close();

  console.log(`p2410_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
