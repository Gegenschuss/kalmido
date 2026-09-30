// Package 3 UI tests (jsdom), fresh DB on the test container: custom fields (list dialog, field dialog, detail,
// chips, columns, filter, sort, offline, duplicate, template), dependencies (picker, rows, confirm, Today setting,
// activity, unblock News), project status + progress (header, modal, sidebar, News), overview (contents, per-user
// visibility, module switch), view-only restrictions, German texts.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const change = (w, el, v) => { if (el.type === 'checkbox') el.checked = v; else el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const ds = n => { const d = new Date(Date.now() + n * 864e5); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const BK = await login('bob'), CKc = await login('carol');
  await call('PATCH', '/api/settings', {lang: 'de'}, BK);
  const WORK = (await call('POST', '/api/lists', {name: 'Work', kind: 'project'})).id;
  const HOME = (await call('POST', '/api/lists', {name: 'Home', kind: 'project'})).id;
  await call('PUT', `/api/lists/${WORK}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${WORK}/members`, {user_id: CAROL, role: 'view'});
  const BOBL = (await call('POST', '/api/lists', {name: 'Bob private', kind: 'project'}, BK)).id;
  const t1 = (await call('POST', '/api/tasks', {title: 'Design', list_id: WORK, due: ds(-1)})).id;
  const t2 = (await call('POST', '/api/tasks', {title: 'Build', list_id: WORK, due: ds(0), assignee_id: BOB})).id;
  const t3 = (await call('POST', '/api/tasks', {title: 'Ship', list_id: WORK})).id;
  const t4 = (await call('POST', '/api/tasks', {title: 'Done already', list_id: WORK})).id;
  await call('POST', `/api/tasks/${t4}/complete`);
  const th = (await call('POST', '/api/tasks', {title: 'Water plants', list_id: HOME, due: ds(0)})).id;

  // ================= custom fields: list dialog + field dialog (owner)
  let w = await boot({user: 'alice', hash: 'l/' + WORK}); let d = w.document;
  w.eval(`listModal(${WORK})`); await sleep(200);
  let md = lastModal(d);
  check(md.querySelector('#l-fields') && /Field/.test(md.querySelector('#l-fields').textContent), 'list dialog: custom fields section for the owner');
  md.querySelector('[data-m="field-add"]').click(); await sleep(100);
  let fm = lastModal(d);
  input(w, fm.querySelector('#fd-name'), 'Stage');
  change(w, fm.querySelector('#fd-type'), 'select');
  check(fm.querySelectorAll('.optrow').length === 1, 'select: one option row to start');
  input(w, fm.querySelector('[data-oname="0"]'), 'Idea');
  fm.querySelector('[data-m="opt-add"]').click();
  input(w, fm.querySelector('[data-oname="1"]'), 'Doing');
  fm.querySelector('[data-ocol="1"]').click();
  fm.querySelector('#fd-pin').checked = true;
  fm.querySelector('[data-m="save"]').click();
  check(await until(() => (md.querySelector('#l-fields')?.textContent || '').includes('Stage')), 'new field listed in the list dialog');
  let st = await call('GET', '/api/state');
  const FS = st.fields.find(f => f.name === 'Stage');
  check(FS && FS.type === 'select' && FS.options.options.map(o => o.name).join() === 'Idea,Doing' && FS.pinned === 1, 'server: select field with 2 options, pinned');
  const OPT = Object.fromEntries(FS.options.options.map(o => [o.name, o.id]));
  md.querySelector('[data-m="field-add"]').click(); await sleep(100);
  fm = lastModal(d);
  input(w, fm.querySelector('#fd-name'), 'Budget'); change(w, fm.querySelector('#fd-type'), 'number');
  input(w, fm.querySelector('#fd-unit'), '€'); fm.querySelector('#fd-pin').checked = true;
  fm.querySelector('[data-m="save"]').click(); await sleep(600);
  for (const [n, ty] of [['Due to client', 'date'], ['Approved', 'checkbox'], ['Reviewer', 'person'], ['Client', 'text']]) {
    md.querySelector('[data-m="field-add"]').click(); await sleep(80);
    fm = lastModal(d); input(w, fm.querySelector('#fd-name'), n); change(w, fm.querySelector('#fd-type'), ty); fm.querySelector('[data-m="save"]').click(); await sleep(500);
  }
  st = await call('GET', '/api/state');
  const FB = st.fields.find(f => f.name === 'Budget'), FD = st.fields.find(f => f.name === 'Due to client'), FC = st.fields.find(f => f.name === 'Approved'), FP = st.fields.find(f => f.name === 'Reviewer'), FT = st.fields.find(f => f.name === 'Client');
  check(FB?.options.unit === '€' && FB.pinned === 1 && FD && FC && FP && FT, 'number (unit, pinned), date, checkbox, person, text fields created');
  // third pin refused with a message
  md.querySelector(`[data-fpin="${FT.id}"]`).click(); await sleep(500);
  check(/At most 2 fields/.test(d.querySelector('#toast').textContent), 'pinning a third field: message');
  // reorder: move Budget up
  md.querySelector(`[data-fup="${FB.id}"]`).click(); await sleep(700);
  st = await call('GET', '/api/state');
  check(st.fields.filter(f => f.list_id === WORK).sort((a, b) => a.sort - b.sort || a.id - b.id)[0].name === 'Budget', 'move a field up');
  md.remove();

  // ================= detail: fields section, values, chips
  w.eval(`openDetail(${t2})`); await sleep(700);
  const sec = d.querySelector('.cfsec');
  check(sec && sec.querySelectorAll('[data-cf]').length === 6, 'detail: Fields section with 6 editors');
  change(w, sec.querySelector(`[data-cf="${FS.id}"]`), OPT.Doing);
  await sleep(500);
  change(w, d.querySelector(`#detail [data-cf="${FB.id}"]`), '1,234.5');
  await sleep(500);
  change(w, d.querySelector(`#detail [data-cf="${FC.id}"]`), true);
  await sleep(500);
  change(w, d.querySelector(`#detail [data-cf="${FP.id}"]`), String(BOB));
  await sleep(500);
  change(w, d.querySelector(`#detail [data-cf="${FD.id}"]`), ds(5));
  await sleep(500);
  let tv = (await call('GET', '/api/state')).tasks.find(t => t.id === t2).fields;
  check(tv[FS.id] === OPT.Doing && tv[FB.id] === '1234.5' && tv[FC.id] === '1' && tv[FP.id] === String(BOB) && tv[FD.id] === ds(5), 'values saved: ' + JSON.stringify(tv));
  change(w, d.querySelector(`#detail [data-cf="${FB.id}"]`), 'abc'); await sleep(500);
  check(/number expected/.test(d.querySelector('#toast').textContent) && (await call('GET', '/api/state')).tasks.find(t => t.id === t2).fields[FB.id] === '1234.5', 'invalid number: message, value kept');
  const row = () => d.querySelector(`#view .trow[data-id="${t2}"]`);
  check(row().querySelector('.fchip.sel')?.textContent === 'Doing' && /Budget\s*1,234\.5 €/.test(row().querySelector('.meta').textContent), 'row chips: Stage + Budget: ' + row().querySelector('.meta').textContent);
  // activity lines
  await w.eval(`loadTimeline(${t2})`); await sleep(200);
  const tl = d.querySelector('#d-tl-items').textContent;
  check(/Alice set Stage to Doing/.test(tl) && /Alice set Budget to 1,234\.5 €/.test(tl) && /Alice set Reviewer to Bob/.test(tl), 'activity: field lines');
  w.eval('closeDetail()');

  // ================= dependencies: picker, rows, confirm
  w.eval(`openDetail(${t2})`); await sleep(800);
  check(/Dependencies/.test(d.querySelector('#d-deps').textContent), 'detail: Dependencies section');
  d.querySelector('#d-deps [data-act="dep-add"][data-dir="by"]').click(); await sleep(150);
  let pk = lastModal(d);
  check(pk.querySelectorAll('.dprow').length >= 3, 'picker lists open tasks');
  input(w, pk.querySelector('#dp-q'), 'desi');
  check(pk.querySelectorAll('.dprow').length === 1 && /Design/.test(pk.querySelector('.dprow').textContent), 'picker search');
  pk.querySelector('.dprow').click();
  check(await until(() => /Design/.test(d.querySelector('#d-deps')?.textContent || '')), 'detail lists the blocker');
  check(row().querySelector('.blk') && /Waiting on: “Design”/.test(row().querySelector('.blk').title), 'row: waiting indicator with the blocker name');
  // blocking direction from Ship's panel: Ship waits on Build
  w.eval(`openDetail(${t2})`); await sleep(600);
  d.querySelector('#d-deps [data-act="dep-add"][data-dir="blocking"]').click(); await sleep(150);
  pk = lastModal(d); input(w, pk.querySelector('#dp-q'), 'ship'); pk.querySelector('.dprow').click();
  check(await until(async () => (await call('GET', `/api/tasks/${t3}/deps`)).blocked_by.some(x => x.id === t2)), 'blocking: Ship now waits on Build');
  // cycle refused with a message: Design waits on Ship
  w.eval(`openDetail(${t1})`); await sleep(600);
  d.querySelector('#d-deps [data-act="dep-add"][data-dir="by"]').click(); await sleep(150);
  pk = lastModal(d); input(w, pk.querySelector('#dp-q'), 'ship'); pk.querySelector('.dprow').click(); await sleep(600);
  check(/circular/.test(d.querySelector('#toast').textContent), 'cycle: message');
  pk.remove();
  // complete a waiting task: confirm
  w.confirm = () => false;
  await w.eval(`toggleTask(${t2})`); await sleep(300);
  check((await call('GET', '/api/state')).tasks.find(t => t.id === t2).status === 0, 'confirm declined: not completed');
  let asked = '';
  w.confirm = m => { asked = m; return true; };
  await w.eval(`toggleTask(${t2})`); await sleep(500);
  check(/still waiting on “Design”/.test(asked) && (await call('GET', '/api/state')).tasks.find(t => t.id === t2).status === 2, 'confirm accepted: completed (' + asked + ')');
  await call('POST', `/api/tasks/${t2}/reopen`);
  await w.eval('load().then(render)'); await sleep(300);
  // batch confirm
  asked = '';
  w.eval(`S.multi = new Set([${t2}, ${th}]); render()`);
  w.confirm = m => { asked = m; return false; };
  d.querySelector('#mbar [data-act="mb-done"]').click(); await sleep(300);
  check(/1 of the selected tasks is still waiting/.test(asked) && (await call('GET', '/api/state')).tasks.find(t => t.id === th).status === 0, 'batch: confirm, declined -> nothing done');
  w.eval('S.multi.clear(); S.multiMode = false; render()');
  w.confirm = () => true;
  // remove the dependency via x
  w.eval(`openDetail(${t3})`); await sleep(700);
  d.querySelector(`#d-deps [data-act="dep-rm"][data-b="${t2}"]`).click();
  check(await until(async () => !(await call('GET', `/api/tasks/${t3}/deps`)).blocked_by.length), 'remove dependency');
  w.eval('closeDetail()');

  // ================= Today: hide waiting tasks (setting)
  w.location.hash = 'today'; await sleep(400);
  check(d.querySelector(`#view .trow[data-id="${t2}"]`), 'Today shows the waiting task by default');
  w.eval(`settingsModal('general')`); await sleep(200);
  md = lastModal(d);
  check(md.querySelector('#s-hideblk') && md.querySelector('#s-progsub'), 'settings > General: Projects switches');
  md.querySelector('#s-hideblk').checked = true; md.querySelector('#s-hideblk').dispatchEvent(new w.Event('change', {bubbles: true}));
  await sleep(900); md.remove();
  check(!d.querySelector(`#view .trow[data-id="${t2}"]`) && d.querySelector(`#view .trow[data-id="${th}"]`), 'setting on: waiting task left out of Today');
  check((await call('GET', '/api/state')).settings.hide_blocked_today === '1', 'setting saved');
  await call('PATCH', '/api/settings', {hide_blocked_today: '0'});

  // ================= list header: progress + status
  await w.eval('load().then(render)'); w.location.hash = 'l/' + WORK; await sleep(500);
  const lh = d.querySelector('.lhead');
  check(lh && /25% 1\/4/.test(lh.querySelector('.lprog').textContent.replace(/\s+/g, ' ')) && /1 overdue/.test(lh.textContent), 'header: progress 1/4, 1 overdue: ' + lh?.textContent);
  lh.querySelector('[data-act="status"]').click(); await sleep(400);
  md = lastModal(d);
  md.querySelector('[data-st="at_risk"]').click();
  md.querySelector('#st-note').value = 'Vendor is late';
  md.querySelector('[data-m="save"]').click(); await sleep(800);
  check(/At risk/.test(d.querySelector('.lhead .stpill').textContent) && /Vendor is late/.test(d.querySelector('.lnote').textContent), 'status pill + note in the header');
  check(d.querySelector(`#side .srow[data-list="${WORK}"] .stdot.st-at_risk`), 'sidebar: status dot');
  w.eval(`statusModal(${WORK})`); await sleep(600);
  check(/At risk/.test(lastModal(d).querySelector('#st-hist').textContent) && /Vendor is late/.test(lastModal(d).querySelector('#st-hist').textContent), 'status history');
  lastModal(d).remove();

  // ================= columns (desktop) + sort by field
  d.querySelector('[data-act="field-cols"]').click(); await sleep(200);
  check(d.querySelector('.fcolhead') && /STAGE|Stage/i.test(d.querySelector('.fcolhead').textContent) && row().querySelector('.fcols'), 'columns view on desktop');
  check(!row().querySelector('.meta .fchip'), 'columns: no duplicate chips in the meta line');
  d.querySelector('[data-act="field-cols"]').click(); await sleep(200);
  await call('PATCH', `/api/tasks/${t1}`, {fields: {[FB.id]: '99'}});
  await call('PATCH', `/api/tasks/${t3}`, {fields: {[FB.id]: '5000'}});
  await w.eval('load().then(render)'); await sleep(200);
  d.querySelector('#top [data-act="top-more"]').click(); await sleep(100);  // 1.5: Sort sits in the header's "…"
  [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent === 'Sort…').click(); await sleep(100);
  const sb = [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent === 'Field: Budget');
  check(sb, 'sort menu: Field: Budget'); sb.click(); await sleep(200);
  const order = [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).filter(x => [t1, t2, t3].includes(x));
  check(order.join() === [t1, t2, t3].join(), 'sorted by budget: 99, 1234.5, 5000: ' + order);

  // ================= filter with a custom field
  w.eval('filterModal()'); await sleep(200);
  md = lastModal(d);
  check(md.querySelector(`.fchips[data-cf="${FS.id}"]`) && md.querySelector(`[data-cfnum="${FB.id}"]`), 'filter dialog: custom field conditions');
  md.querySelector('#f-name').value = 'Doing';
  md.querySelector(`.fchips[data-cf="${FS.id}"] [data-v="${OPT.Doing}"]`).click();
  check(/matches 1 open task/.test(md.querySelector('#f-count').textContent), 'filter count: 1');
  md.querySelector('[data-m="save"]').click(); await sleep(800);
  check([...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).join() === String(t2), 'filter view: only the task with Stage = Doing');
  const fl = (await call('GET', '/api/state')).filters[0];
  check(fl.rules.cf && fl.rules.cf[FS.id].sel[0] === OPT.Doing, 'filter rule stored');
  w.eval(`filterModal(${fl.id})`); await sleep(200); md = lastModal(d);
  md.querySelector(`.fchips[data-cf="${FS.id}"] [data-v="${OPT.Doing}"]`).click();
  change(w, md.querySelector(`[data-cfnum="${FB.id}"]`), 'gt'); input(w, md.querySelector(`[data-cfnumv="${FB.id}"]`), '1000');
  check(/matches 2 open tasks/.test(md.querySelector('#f-count').textContent), 'number filter > 1000: 2 tasks');
  md.querySelector('[data-m="save"]').click(); await sleep(800);
  check([...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).sort().join() === [t2, t3].sort().join(), 'filter view: budget > 1000');

  // ================= offline field edit + duplicate + template dialog
  w.location.hash = 'l/' + WORK; await sleep(300);
  w.eval(`openDetail(${t3})`); await sleep(600);
  w.__offline = true;
  change(w, d.querySelector(`#detail [data-cf="${FS.id}"]`), OPT.Idea); await sleep(300);
  check(w.eval('OUT.q.length') === 1 && row() && d.querySelector(`#view .trow[data-id="${t3}"] .fchip.sel`)?.textContent === 'Idea', 'offline: queued, chip updated locally');
  w.__offline = false; await w.eval('flush()'); await sleep(900);
  check((await call('GET', '/api/state')).tasks.find(t => t.id === t3).fields[FS.id] === OPT.Idea, 'offline edit replayed');
  w.eval('closeDetail()');
  await w.eval(`taskMenu($('#top h1'), ${t2})`); await sleep(100);
  [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent === 'Duplicate').click(); await sleep(700);
  st = await call('GET', '/api/state');
  const dup = st.tasks.filter(t => t.title === 'Build').find(t => t.id !== t2);
  check(dup && dup.fields[FS.id] === OPT.Doing && dup.fields[FB.id] === '1234.5', 'duplicate keeps the field values');
  const tp = await call('POST', '/api/templates', {list_id: WORK});
  w.eval(`templateModal(${JSON.stringify(tp)})`); await sleep(100);
  check(/Custom fields.*Budget.*Stage/.test(lastModal(d).textContent), 'list template dialog shows the fields');
  lastModal(d).remove();

  // ================= overview
  await call('POST', '/api/deps', {task_id: t2, blocker_id: t1});
  await w.eval('load().then(render)');
  check(d.querySelector('#side [data-go="overview"]') && d.querySelector('#rail [data-go="overview"]'), 'overview in sidebar + rail');
  w.location.hash = 'overview'; await sleep(400);
  check(d.querySelector('#top h1').textContent === 'Where is it stuck?', 'overview title');
  const cards = [...d.querySelectorAll('.ovcard')];
  check(cards.length === 2 && /Work/.test(cards[0].querySelector('.ovname').textContent) && cards[0].classList.contains('risk'), 'overview: 2 lists, Work (at risk) first');
  const wc = cards[0].textContent;
  check(/Overdue\s*1/.test(wc) && /Design/.test(wc) && /Waiting\s*1/.test(wc) && /Waiting on: “Design”/.test(wc) && /Without assignee/.test(wc), 'Work card: overdue, waiting, without assignee');
  check(/Nobody/.test(wc), 'overdue grouped by assignee (Nobody)');
  const tiles = [...d.querySelectorAll('.ovw .sttiles b')].map(b => b.textContent);
  check(tiles[0] === '1' && tiles[1] === '1' && tiles[2] === '1', 'tiles: 1 overdue, 1 waiting, 1 at risk: ' + tiles);
  d.querySelector('[data-act="ov-only"][data-k="1"]').click(); await sleep(100);
  check(d.querySelectorAll('.ovcard').length === 1, 'needs attention: only Work');
  d.querySelector('[data-act="ov-only"][data-k=""]').click();
  await sleep(100); d.querySelector('.ovcard [data-act="open-id"]').click(); await sleep(400);
  check(w.eval('S.sel') > 0, 'click opens the task');
  w.eval('closeDetail()');
  // settings: layout switch
  w.eval(`settingsModal('layout')`); await sleep(100);
  md = lastModal(d); const pc = md.querySelector('[data-feat="progress"]');
  check(pc && pc.checked && /Project progress/.test(pc.closest('label').textContent), 'modules: Project progress switch');
  pc.checked = false; pc.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900); md.remove();
  check(!d.querySelector('#side [data-go="overview"]') && w.eval('S.route.mod') !== 'overview', 'progress off: no overview');
  w.location.hash = 'l/' + WORK; await sleep(300);
  check(!d.querySelector('.lhead') && !d.querySelector('#side .stdot'), 'progress off: no list header, no status dots (status is part of the module)');
  w.location.hash = 'overview'; await sleep(300);
  check(d.querySelector('#top h1').textContent !== 'Where is it stuck?', 'overview route off -> back to tasks');
  await call('PATCH', '/api/settings', {features: 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress'});
  w.close();

  // ================= carol (view only) + her overview
  const cl2 = (await call('POST', '/api/lists', {name: 'Carol stuff', kind: 'project'}, CKc)).id;
  let wc2 = await boot({user: 'carol', hash: 'l/' + WORK}); let dc = wc2.document;
  wc2.eval(`openDetail(${t2})`); await sleep(800);
  check([...dc.querySelectorAll('#detail [data-cf]')].every(e => e.disabled || e.readOnly), 'view only: field editors read-only');
  check(!dc.querySelector('#d-deps [data-act="dep-add"]') && !dc.querySelector('#d-deps [data-act="dep-rm"]'), 'view only: no dependency add / remove');
  check(/Design/.test(dc.querySelector('#d-deps').textContent), 'view only: sees the blocker');
  check(!dc.querySelector('.lhead [data-act="status"]:not([disabled])') || /At risk/.test(dc.querySelector('.lhead .stpill').textContent), 'view only: pill shown');
  dc.querySelector('.lhead .stpill').click(); await sleep(500);
  check(!lastModal(dc).querySelector('[data-m="save"]') && /View only/.test(lastModal(dc).textContent), 'view only: status dialog without save');
  lastModal(dc).remove();
  wc2.eval(`listModal(${WORK})`); await sleep(100);
  check(!lastModal(dc).querySelector('#l-fields') && /only the owner can change them/.test(lastModal(dc).textContent), 'view only: list dialog shows fields read-only');
  lastModal(dc).remove(); wc2.eval('closeDetail()');
  wc2.location.hash = 'overview'; await sleep(400);
  const cn = [...dc.querySelectorAll('.ovcard .ovname')].map(x => x.textContent.trim());
  check(cn.some(x => /Work/.test(x)) && cn.some(x => /Carol stuff/.test(x)) && !cn.some(x => x.includes('Home')), "carol's overview: only her lists: " + cn);
  wc2.close();

  // ================= bob (German): News for status + unblock, texts
  await call('POST', `/api/tasks/${t1}/complete`);
  let wb = await boot({user: 'bob', hash: 'news'}); let db = wb.document; await sleep(900);
  const nt = db.querySelector('#view').textContent;
  check(/Alice hat Design erledigt: Deine Aufgabe wartet nicht mehr/.test(nt), 'bob News: unblock (German)');
  check(/Alice hat Work auf\s*Gefährdet gesetzt/.test(nt) && /Vendor is late/.test(nt), 'bob News: status update with note (German)');
  wb.location.hash = 'l/' + WORK; await sleep(400);
  check(/erledigt/.test(db.querySelector('.lhead').textContent) || /\d+ %?|\//.test(db.querySelector('.lhead .lprog').textContent), 'bob: header');
  check(/Gefährdet/.test(db.querySelector('.lhead .stpill').textContent), 'bob: German status label');
  wb.eval(`openDetail(${t3})`); await sleep(700);
  check(/Felder/.test(db.querySelector('.cfsec h5').textContent) && /Abhängigkeiten/.test(db.querySelector('#d-deps h5').textContent) && /Wartet auf…/.test(db.querySelector('#d-deps').textContent), 'bob: German detail sections');
  const EN = /\b(Waiting|Blocking|Dependencies|Fields|Custom fields|On track|At risk|Set status|Overview|stuck)\b/;
  check(!EN.test(db.querySelector('#detail').textContent + db.querySelector('#view').textContent + db.querySelector('#side').textContent), 'bob: no English leftovers');
  wb.location.hash = 'overview'; await sleep(400);
  check(db.querySelector('#top h1').textContent === 'Wo hakt es?' && !EN.test(db.querySelector('#view').textContent), 'bob: German overview');
  // bob's private list: no status/fields editor for alice's fields; bob owns BOBL -> fields section in his dialog
  wb.eval(`listModal(${BOBL})`); await sleep(100);
  check(lastModal(db).querySelector('#l-fields') && /Eigene Felder/.test(lastModal(db).textContent), 'bob: fields section in his own list dialog (German)');
  wb.close();

  // ================= mobile: no columns
  const wm = await boot({user: 'alice', mobile: true, hash: 'l/' + WORK, ls: {['tasks.fcols.' + WORK]: 'true'}});
  check(!wm.document.querySelector('.fcolhead') && !wm.document.querySelector('[data-act="field-cols"]'), 'mobile: no column view');
  check(wm.document.querySelector('.lhead .lprog'), 'mobile: progress header');
  wm.close();

  console.log(`${ok} ok, ${F.length} failed`); if (errs.length) console.log('JS errors:', errs);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
