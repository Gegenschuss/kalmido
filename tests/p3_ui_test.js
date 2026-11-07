// Package 3 UI tests (jsdom), fresh DB on the test container: custom fields (list dialog, field dialog, detail,
// chips, columns, filter, sort, offline, duplicate, template), dependencies (picker, rows, confirm, Today setting,
// activity, unblock News), project status + progress (header, modal, sidebar, News), overview (contents, per-user
// visibility, module switch), view-only restrictions, German texts.
const {boot, errs, sleep, B, login} = require('./boot');
const {idle} = require('./boot');  // 2.192.0 B (#2513): idle(w) = the page's requests done, instead of fixed sleeps
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 100});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const change = (w, el, v) => { if (el.type === 'checkbox') el.checked = v; else el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const ds = n => { const d = new Date(); d.setDate(d.getDate() + n); return  /* 2.80.1: calendar days (clock change) */ `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

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
  await call('PATCH', '/api/settings', {show_progress: String(WORK)}); await call('PATCH', '/api/settings', {show_progress: String(WORK)}, BK);  // 2.40.0 (#1190): the bar is off by default in projects
  const t1 = (await call('POST', '/api/tasks', {title: 'Design', list_id: WORK, due: ds(-1)})).id;
  const t2 = (await call('POST', '/api/tasks', {title: 'Build', list_id: WORK, due: ds(0), assignee_id: BOB})).id;
  const t3 = (await call('POST', '/api/tasks', {title: 'Ship', list_id: WORK})).id;
  const t4 = (await call('POST', '/api/tasks', {title: 'Done already', list_id: WORK})).id;
  await call('POST', `/api/tasks/${t4}/complete`);
  const th = (await call('POST', '/api/tasks', {title: 'Water plants', list_id: HOME, due: ds(0)})).id;

  // ================= custom fields: list dialog + field dialog (owner)
  let w = await boot({user: 'alice', hash: 'l/' + WORK}); let d = w.document;
  w.eval(`listModal(${WORK})`); await until(() => lastModal(d)?.querySelector('#l-fields')); await idle(w);  // 2.624.0 (#3943): the dialog, not a fixed wait
  let md = lastModal(d);
  const fieldDlg = () => until(() => { const m = lastModal(d); return m && m !== md && m.querySelector('#fd-name') && m; });  // 2.624.0 (#3943): the field dialog on top of the list dialog
  check(md.querySelector('#l-fields') && /Field/.test(md.querySelector('#l-fields').textContent), 'list dialog: custom fields section for the owner');
  md.querySelector('[data-m="field-add"]').click(); await fieldDlg();
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
  md.querySelector('[data-m="field-add"]').click(); await fieldDlg();
  fm = lastModal(d);
  input(w, fm.querySelector('#fd-name'), 'Budget'); change(w, fm.querySelector('#fd-type'), 'number');
  input(w, fm.querySelector('#fd-unit'), '€'); fm.querySelector('#fd-pin').checked = true;
  fm.querySelector('[data-m="save"]').click(); await until(() => w.eval(`fieldsAll(${WORK}).some(f => f.name === 'Budget' && f.id > 0)`));  // 2.624.0 (#3943): the server's answer (real id), not 600 ms
  for (const [n, ty] of [['Due to client', 'date'], ['Approved', 'checkbox'], ['Reviewer', 'person'], ['Client', 'text']]) {
    md.querySelector('[data-m="field-add"]').click(); await fieldDlg();
    fm = lastModal(d); input(w, fm.querySelector('#fd-name'), n); change(w, fm.querySelector('#fd-type'), ty); fm.querySelector('[data-m="save"]').click(); await idle(w);
  }
  await until(() => w.eval(`fieldsAll(${WORK}).length === 6 && fieldsAll(${WORK}).every(f => f.id > 0)`));  // 2.624.0 (#3943): every new field has its real id (stand-ins below 0 until the server answers)
  st = await call('GET', '/api/state');
  const FB = st.fields.find(f => f.name === 'Budget'), FD = st.fields.find(f => f.name === 'Due to client'), FC = st.fields.find(f => f.name === 'Approved'), FP = st.fields.find(f => f.name === 'Reviewer'), FT = st.fields.find(f => f.name === 'Client');
  check(FB?.options.unit === '€' && FB.pinned === 1 && FD && FC && FP && FT, 'number (unit, pinned), date, checkbox, person, text fields created');
  // third pin refused with a message (2.88.1, CI: the slow runner draws the new field rows later than the fixed waits above)
  await until(() => md.querySelector(`[data-fpin="${FT.id}"]`) && md.querySelector(`[data-fup="${FB.id}"]`), 8000);
  md.querySelector(`[data-fpin="${FT.id}"]`).click(); await until(() => /At most 2 fields/.test(d.querySelector('#toast').textContent), 3000);
  check(/At most 2 fields/.test(d.querySelector('#toast').textContent), 'pinning a third field: message');
  // reorder: move Budget up
  // 2.624.0 (#3943, CI: the up button was null here): the refused pin draws the rows again after its request; wait for it and the row
  await idle(w); await until(() => md.querySelector(`[data-fup="${FB.id}"]`));
  md.querySelector(`[data-fup="${FB.id}"]`).click();
  await until(async () => (await call('GET', '/api/state')).fields.filter(f => f.list_id === WORK).sort((a, b) => a.sort - b.sort || a.id - b.id)[0]?.name === 'Budget');  // 2.624.0 (#3943): the server has the order
  st = await call('GET', '/api/state');
  check(st.fields.filter(f => f.list_id === WORK).sort((a, b) => a.sort - b.sort || a.id - b.id)[0].name === 'Budget', 'move a field up');
  md.remove();

  // ================= detail: fields section, values, chips
  w.eval(`openDetail(${t2})`); await idle(w);
  // job/2919: under load the panel's fields come after idle (Mac check of 2.542: no section, then a crash) - wait for them
  await until(() => d.querySelector('.cfsec')?.querySelectorAll('[data-cf]').length === 6, 8000);
  const sec = d.querySelector('.cfsec');
  check(sec && sec.querySelectorAll('[data-cf]').length === 6, 'detail: Fields section with 6 editors');
  const outDone = () => until(() => !w.eval('OUT.q.length') && !w.eval('OUT.flushing'));  // 2.624.0 (#3943): each change sent (outbox empty), not 500 ms
  change(w, sec.querySelector(`[data-cf="${FS.id}"]`), OPT.Doing);
  await outDone();
  change(w, d.querySelector(`#detail [data-cf="${FB.id}"]`), '1,234.5');
  await outDone();
  change(w, d.querySelector(`#detail [data-cf="${FC.id}"]`), true);
  await outDone();
  change(w, d.querySelector(`#detail [data-cf="${FP.id}"]`), String(BOB));
  await outDone();
  change(w, d.querySelector(`#detail [data-cf="${FD.id}"]`), ds(5));
  await outDone();
  // 2.551.0 (#4649): the changes go through the outbox online too (#4568): read once it is empty, not after a fixed time
  await until(() => !w.eval('OUT.q.length') && !w.eval('OUT.flushing'));
  let tv = (await call('GET', '/api/state')).tasks.find(t => t.id === t2).fields;
  check(tv[FS.id] === OPT.Doing && tv[FB.id] === '1234.5' && tv[FC.id] === '1' && tv[FP.id] === String(BOB) && tv[FD.id] === ds(5), 'values saved: ' + JSON.stringify(tv));
  change(w, d.querySelector(`#detail [data-cf="${FB.id}"]`), 'abc'); await idle(w);
  // 2.624.0 (#3943, CI: red here): the refusal comes from the outbox after its own flush, later than idle: wait for the message and the queue
  await until(() => /number expected/.test(d.querySelector('#toast').textContent) && !w.eval('OUT.q.length') && !w.eval('OUT.flushing')); await idle(w);
  check(/number expected/.test(d.querySelector('#toast').textContent) && (await call('GET', '/api/state')).tasks.find(t => t.id === t2).fields[FB.id] === '1234.5', 'invalid number: message, value kept');
  const row = () => d.querySelector(`#view .trow[data-id="${t2}"]`);
  check(row().querySelector('.fchip.sel')?.textContent === 'Doing' && /Budget\s*1,234\.5 €/.test(row().querySelector('.meta').textContent), 'row chips: Stage + Budget: ' + row().querySelector('.meta').textContent);
  // activity lines
  await w.eval(`loadTimeline(${t2})`); await until(() => /Alice set Reviewer to Bob/.test(d.querySelector('#d-tl-items')?.textContent || ''));  // 2.624.0 (#3943)
  const tl = d.querySelector('#d-tl-items').textContent;
  check(/Alice set Stage to Doing/.test(tl) && /Alice set Budget to 1,234\.5 €/.test(tl) && /Alice set Reviewer to Bob/.test(tl), 'activity: field lines');
  w.eval('closeDetail()');

  // ================= dependencies: picker, rows, confirm
  w.eval(`openDetail(${t2})`); await idle(w);
  check(/Dependencies/.test(d.querySelector('#d-deps').textContent), 'detail: Dependencies section');
  // 2.25.0 (UX-43): one button "Waiting on…" with the choice "Another task…" / "Someone outside…"
  const waitOn = async () => { d.querySelector('#d-deps [data-act="wait-on"]').click(); await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].some(b => /Another task/.test(b.textContent))); const it = [...d.querySelectorAll('#pop [role="menuitem"]')]; check(it.some(b => /Someone outside/.test(b.textContent)), 'Waiting on…: someone outside offered'); it.find(b => /Another task/.test(b.textContent)).click(); await until(() => d.querySelector('.dpmodal #dp-q')); };  // 2.624.0 (#3943): the menu, then the picker, not fixed waits
  await waitOn();
  let pk = lastModal(d);
  check(pk.querySelectorAll('.tpkrow').length >= 3, 'picker lists open tasks');
  input(w, pk.querySelector('#dp-q'), 'desi');
  check(pk.querySelectorAll('.tpkrow').length === 1 && /Design/.test(pk.querySelector('.tpkrow').textContent), 'picker search');
  pk.querySelector('.tpkrow').click();
  check(await until(() => /Design/.test(d.querySelector('#d-deps')?.textContent || '')), 'detail lists the blocker');
  check(row().querySelector('.blk') && /Blocked by: “Design”/.test(row().querySelector('.blk').title), 'row: waiting indicator with the blocker name');
  // blocking direction from Ship's panel: Ship waits on Build
  w.eval(`openDetail(${t2})`); await idle(w);
  d.querySelector('#d-deps [data-act="dep-add"][data-dir="blocking"]').click(); await until(() => d.querySelector('.dpmodal #dp-q'));  // 2.624.0 (#3943)
  pk = lastModal(d); input(w, pk.querySelector('#dp-q'), 'ship'); pk.querySelector('.tpkrow').click();
  check(await until(async () => (await call('GET', `/api/tasks/${t3}/deps`)).blocked_by.some(x => x.id === t2)), 'blocking: Ship now waits on Build');
  // cycle refused with a message: Design waits on Ship
  w.eval(`openDetail(${t1})`); await idle(w);
  await waitOn();
  pk = lastModal(d); input(w, pk.querySelector('#dp-q'), 'ship'); pk.querySelector('.tpkrow').click(); await until(() => /circular/.test(d.querySelector('#toast').textContent));  // 2.624.0 (#3943): the server's refusal
  check(/circular/.test(d.querySelector('#toast').textContent), 'cycle: message');
  pk.remove();
  // complete a waiting task: confirm
  w.confirm = () => false;
  await w.eval(`toggleTask(${t2})`); await idle(w);  // 2.624.0 (#3943): declined = no request; idle covers one that should not be there
  check((await call('GET', '/api/state')).tasks.find(t => t.id === t2).status === 0, 'confirm declined: not completed');
  let asked = '';
  w.confirm = m => { asked = m; return true; };
  await w.eval(`toggleTask(${t2})`); await idle(w);
  check(/still blocked by “Design”/.test(asked) && (await call('GET', '/api/state')).tasks.find(t => t.id === t2).status === 2, 'confirm accepted: completed (' + asked + ')');
  await call('POST', `/api/tasks/${t2}/reopen`);
  await w.eval('load().then(render)'); await idle(w);
  // batch confirm
  asked = '';
  w.eval(`S.multi = new Set([${t2}, ${th}]); render()`);
  w.confirm = m => { asked = m; return false; };
  d.querySelector('#mbar [data-act="mb-done"]').click(); await until(() => asked); await idle(w);  // 2.624.0 (#3943): the question was asked
  check(/1 of the selected tasks is still blocked/.test(asked) && (await call('GET', '/api/state')).tasks.find(t => t.id === th).status === 0, 'batch: confirm, declined -> nothing done');
  w.eval('S.multi.clear(); S.multiMode = false; render()');
  w.confirm = () => true;
  // remove the dependency via x
  w.eval(`openDetail(${t3})`);  // 2.53.1: wait for the dependency row (700 ms were too short on a slow CI runner)
  await until(() => d.querySelector(`#d-deps [data-act="dep-rm"][data-b="${t2}"]`));
  d.querySelector(`#d-deps [data-act="dep-rm"][data-b="${t2}"]`).click();
  check(await until(async () => !(await call('GET', `/api/tasks/${t3}/deps`)).blocked_by.length), 'remove dependency');
  w.eval('closeDetail()');

  // ================= Today: hide waiting tasks (setting)
  w.location.hash = 'today'; await until(() => d.querySelector(`#view .trow[data-id="${t2}"]`)); await idle(w);  // 2.624.0 (#3943)
  check(d.querySelector(`#view .trow[data-id="${t2}"]`), 'Today shows the waiting task by default');
  w.eval(`settingsModal('general')`); await until(() => lastModal(d)?.querySelector('#s-hideblk')); await idle(w);  // 2.624.0 (#3943)
  md = lastModal(d);
  check(md.querySelector('#s-hideblk') && md.querySelector('#s-progsub'), 'settings > General: Projects switches');
  md.querySelector('#s-hideblk').checked = true; md.querySelector('#s-hideblk').dispatchEvent(new w.Event('change', {bubbles: true}));
  // 2.624.0 (#3943): the setting saved and the view drawn again, not 900 ms
  await until(async () => !d.querySelector(`#view .trow[data-id="${t2}"]`) && (await call('GET', '/api/state')).settings.hide_blocked_today === '1'); md.remove();
  check(!d.querySelector(`#view .trow[data-id="${t2}"]`) && d.querySelector(`#view .trow[data-id="${th}"]`), 'setting on: waiting task left out of Today');
  check((await call('GET', '/api/state')).settings.hide_blocked_today === '1', 'setting saved');
  await call('PATCH', '/api/settings', {hide_blocked_today: '0'});

  // ================= list header: progress + status
  await w.eval('load().then(render)'); w.location.hash = 'l/' + WORK; await idle(w);
  const lh = d.querySelector('.lhead');
  check(lh && /25% 1\/4/.test(lh.querySelector('.lprog').textContent.replace(/\s+/g, ' ')) && /1 overdue/.test(lh.textContent), 'header: progress 1/4, 1 overdue: ' + lh?.textContent);
  // 2.31.0 (#1053): no "Set status" in the list header any more; it is in the list's "…" menu (and on the project page)
  check(!lh.querySelector('[data-act="status"]'), 'header: no "Set status" button (2.31.0)');
  w.eval(`listMenuItems(${WORK}).find(x => x && x.cls === 'mstatus').fn()`); await idle(w);
  md = lastModal(d);
  md.querySelector('[data-st="at_risk"]').click();
  md.querySelector('#st-note').value = 'Vendor is late';
  md.querySelector('[data-m="save"]').click();
  await until(() => /At risk/.test(d.querySelector('.lhead .stpill')?.textContent || '') && /Vendor is late/.test(d.querySelector('.lnote')?.textContent || '') && d.querySelector(`#side .srow[data-list="${WORK}"] .stdot.st-at_risk`)); await idle(w);  // 2.624.0 (#3943)
  check(/At risk/.test(d.querySelector('.lhead .stpill').textContent) && /Vendor is late/.test(d.querySelector('.lnote').textContent), 'status pill + note in the header');
  check(d.querySelector(`#side .srow[data-list="${WORK}"] .stdot.st-at_risk`), 'sidebar: status dot');
  w.eval(`statusModal(${WORK})`); await idle(w);
  check(/At risk/.test(lastModal(d).querySelector('#st-hist').textContent) && /Vendor is late/.test(lastModal(d).querySelector('#st-hist').textContent), 'status history');
  lastModal(d).remove();

  // ================= columns (desktop) + sort by field
  // 2.14.0 (#425): custom fields are columns of the list ("Columns…", for every member)
  await w.eval(`colSave(${WORK}, ['due', ...fieldsOf(${WORK}).map(f => 'f:' + f.id)], true)`); await until(() => d.querySelector('.lchead') && row()?.querySelector('.lcols .lc-f'));  // 2.624.0 (#3943)
  check(d.querySelector('.lchead') && /STAGE|Stage/i.test(d.querySelector('.lchead').textContent) && row().querySelector('.lcols .lc-f'), 'columns view on desktop');
  check(!row().querySelector('.meta > .fchip'), 'columns: no field chips in the meta line (only the hidden copies for narrow widths)');
  await w.eval(`colSave(${WORK}, null, true)`); await until(() => !d.querySelector('.lchead')); await idle(w);  // 2.624.0 (#3943)
  await call('PATCH', `/api/tasks/${t1}`, {fields: {[FB.id]: '99'}});
  await call('PATCH', `/api/tasks/${t3}`, {fields: {[FB.id]: '5000'}});
  await w.eval('load().then(render)'); await idle(w);
  d.querySelector('#top [data-act="top-more"]').click(); await until(() => [...d.querySelectorAll('#pop .menu-list button')].some(b => b.textContent === 'Sort…'));  // 1.5: Sort sits in the header's "…"
  [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent === 'Sort…').click(); await until(() => [...d.querySelectorAll('#pop .menu-list button')].some(b => b.textContent === 'Field: Budget'));  // 2.624.0 (#3943): the menus, not fixed waits
  const sb = [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent === 'Field: Budget');
  check(sb, 'sort menu: Field: Budget'); sb.click(); await until(() => [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).filter(x => [t1, t2, t3].includes(x)).join() === [t1, t2, t3].join());  // 2.624.0 (#3943): the sorted rows
  const order = [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).filter(x => [t1, t2, t3].includes(x));
  check(order.join() === [t1, t2, t3].join(), 'sorted by budget: 99, 1234.5, 5000: ' + order);

  // ================= filter with a custom field; 2.521.0 (#4479): condition rows (was: chips per field)
  w.eval('filterModal()');
  md = await until(() => { const m = lastModal(d); return m && m.querySelector('#f-conds') && m; });
  md.querySelector('[data-m="cond-add"]').click();
  const fopt = n => [...md.querySelectorAll('.fcond .fc-f option')].find(o => o.textContent === n);
  check(fopt('Stage') && fopt('Budget'), 'filter dialog: custom field conditions');
  md.querySelector('#f-name').value = 'Doing';
  change(w, md.querySelector('.fcond .fc-f'), fopt('Stage').value);
  md.querySelector('.fcond .fc-v').click();
  let vp = await until(() => d.querySelector('#pop:not(.hidden) [role="menuitemcheckbox"]') && d.querySelector('#pop'));
  [...vp.querySelectorAll('[role="menuitemcheckbox"]')].find(b => b.textContent.trim() === 'Doing').click(); w.eval('closePop()');
  check(/\b1 task matches/.test(md.querySelector('#f-count').textContent), 'filter count: 1');
  md.querySelector('[data-m="save"]').click(); await until(() => !lastModal(d) || !lastModal(d).querySelector('#f-conds'));
  check(await until(() => [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).join() === String(t2)), 'filter view: only the task with Stage = Doing');
  const fl = (await call('GET', '/api/state')).filters[0];
  check(fl.rules.conds && fl.rules.conds[0].name === 'Stage' && fl.rules.conds[0].v[0] === 'Doing', 'filter rule stored');
  w.eval(`filterModal(${fl.id})`); md = await until(() => { const m = lastModal(d); return m && m.querySelector('#f-conds .fcond') && m; });
  md.querySelector('.fcond .fc-x').click();
  md.querySelector('[data-m="cond-add"]').click();
  change(w, md.querySelector('.fcond .fc-f'), [...md.querySelectorAll('.fcond .fc-f option')].find(o => o.textContent === 'Budget').value);
  change(w, md.querySelector('.fcond .fc-op'), 'gt'); input(w, md.querySelector('.fcond .fc-n'), '1000');
  check(/\b2 tasks match/.test(md.querySelector('#f-count').textContent), 'number filter > 1000: 2 tasks');
  md.querySelector('[data-m="save"]').click(); await until(() => !lastModal(d) || !lastModal(d).querySelector('#f-conds'));
  check(await until(() => [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id).sort().join() === [t2, t3].sort().join()), 'filter view: budget > 1000');

  // ================= offline field edit + duplicate + template dialog
  w.location.hash = 'l/' + WORK; await until(() => d.querySelector(`#view .trow[data-id="${t3}"]`)); await idle(w);  // 2.624.0 (#3943)
  w.eval(`openDetail(${t3})`); await idle(w);
  w.__offline = true;
  change(w, d.querySelector(`#detail [data-cf="${FS.id}"]`), OPT.Idea); await until(() => w.eval('OUT.q.length') === 1 && d.querySelector(`#view .trow[data-id="${t3}"] .fchip.sel`)?.textContent === 'Idea');  // 2.624.0 (#3943)
  check(w.eval('OUT.q.length') === 1 && row() && d.querySelector(`#view .trow[data-id="${t3}"] .fchip.sel`)?.textContent === 'Idea', 'offline: queued, chip updated locally');
  w.__offline = false; await w.eval('flush()');
  await until(async () => !w.eval('OUT.q.length') && !w.eval('OUT.flushing') && (await call('GET', '/api/state')).tasks.find(t => t.id === t3).fields[FS.id] === OPT.Idea);  // 2.624.0 (#3943): replayed on the server
  check((await call('GET', '/api/state')).tasks.find(t => t.id === t3).fields[FS.id] === OPT.Idea, 'offline edit replayed');
  w.eval('closeDetail()');
  await w.eval(`taskMenu($('#top h1'), ${t2})`); await until(() => d.querySelector('#pop .mtmore'));
  d.querySelector('#pop .mtmore').click(); await until(() => [...d.querySelectorAll('#pop .menu-list button')].some(b => b.textContent === 'Duplicate'));  // 2.445.0 (#3008): Duplicate is under "More…"
  [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent === 'Duplicate').click(); await idle(w);
  await until(async () => (await call('GET', '/api/state')).tasks.filter(t => t.title === 'Build').length > 1);  // 2.624.0 (#3943): the copy is on the server
  st = await call('GET', '/api/state');
  const dup = st.tasks.filter(t => t.title === 'Build').find(t => t.id !== t2);
  check(dup && dup.fields[FS.id] === OPT.Doing && dup.fields[FB.id] === '1234.5', 'duplicate keeps the field values');
  const NOT_ON_TRAIN = !require('fs').existsSync(require('path').join(__dirname, '..', 'kalmido/lists/tplextra.py'));  // #3134 sits in main, the live train does not have it yet: drop this then
  check(NOT_ON_TRAIN || (await call('GET', `/api/tasks/${dup.id}/deps`)).blocked_by.some(x => x.id === t1), 'duplicate keeps what it waits on (#3134)');
  const tp = await call('POST', '/api/templates', {list_id: WORK});
  w.eval(`templateModal(${JSON.stringify(tp)})`); await until(() => /Custom fields.*Budget.*Stage/.test(lastModal(d)?.textContent || ''));  // 2.624.0 (#3943)
  check(/Custom fields.*Budget.*Stage/.test(lastModal(d).textContent), 'list template dialog shows the fields');
  lastModal(d).remove();

  // ================= overview
  await call('POST', `/api/lists/${HOME}/status`, {status: 'on_track', note: ''});  // 2.352.0 B (#2752): tracked = has a status
  await call('POST', '/api/deps', {task_id: t2, blocker_id: t1});
  await w.eval('load().then(render)');
  check(d.querySelector('#side [data-go="overview"]'), 'overview in the sidebar');
  w.location.hash = 'overview'; await until(() => d.querySelector('#top h1')?.textContent === 'Project status' && d.querySelector('.ovcard')); await idle(w);  // 2.624.0 (#3943)
  check(d.querySelector('#top h1').textContent === 'Project status', 'overview title: Project status (2.25.0)');
  const cards = [...d.querySelectorAll('.ovcard')];
  check(cards.length === 2 && /Work/.test(cards[0].querySelector('.ovname').textContent) && cards[0].classList.contains('risk'), 'overview: 2 lists, Work (at risk) first');
  const wc = cards[0].textContent;
  check(/Overdue\s*1/.test(wc) && /Design/.test(wc) && new RegExp(`Blocked\\s*${NOT_ON_TRAIN ? 1 : 2}`).test(wc) && /Blocked by: “Design”/.test(wc) && /Without assignee/.test(wc), 'Work card: overdue, waiting (Build and its duplicate, #3134), without assignee');
  check(/Nobody/.test(wc), 'overdue grouped by assignee (Nobody)');
  const tiles = [...d.querySelectorAll('.ovw .sttiles b')].map(b => b.textContent);
  check(tiles[0] === '1' && tiles[1] === (NOT_ON_TRAIN ? '1' : '2') && tiles[2] === '1', 'tiles: 1 overdue, 2 waiting, 1 at risk: ' + tiles);
  d.querySelector('[data-act="ov-only"][data-k="1"]').click(); await until(() => d.querySelectorAll('.ovcard').length === 1);  // 2.624.0 (#3943)
  check(d.querySelectorAll('.ovcard').length === 1, 'needs attention: only Work');
  d.querySelector('[data-act="ov-only"][data-k=""]').click();
  await until(() => d.querySelectorAll('.ovcard').length > 1); d.querySelector('.ovcard [data-act="open-id"]').click(); await until(() => w.eval('S.sel') > 0); await idle(w);  // 2.624.0 (#3943)
  check(w.eval('S.sel') > 0, 'click opens the task');
  w.eval('closeDetail()');
  // settings: layout switch
  w.eval(`settingsModal('layout')`); await until(() => lastModal(d)?.querySelector('[data-feat="progress"]')); await idle(w);  // 2.624.0 (#3943)
  md = lastModal(d); const pc = md.querySelector('[data-feat="progress"]');
  check(pc && pc.checked && /Project progress/.test(pc.closest('label').textContent), 'modules: Project progress switch');
  pc.checked = false; pc.dispatchEvent(new w.Event('change', {bubbles: true})); await until(() => !d.querySelector('#side [data-go="overview"]') && w.eval('S.route.mod') !== 'overview'); await idle(w); md.remove();  // 2.624.0 (#3943): the module off, drawn
  check(!d.querySelector('#side [data-go="overview"]') && w.eval('S.route.mod') !== 'overview', 'progress off: no overview');
  w.location.hash = 'l/' + WORK; await until(() => row()); await idle(w);  // 2.624.0 (#3943): the list drawn
  check(!d.querySelector('.lhead') && !d.querySelector('#side .stdot'), 'progress off: no list header, no status dots (status is part of the module)');
  w.location.hash = 'overview'; await until(() => /project status needs/.test(d.querySelector('#toast').textContent)); await idle(w);  // 2.624.0 (#3943): route() turned the address away (its message)
  check(d.querySelector('#top h1').textContent !== 'Where is it stuck?', 'overview route off -> back to tasks');
  await call('PATCH', '/api/settings', {features: 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress'});
  w.close();

  // ================= carol (view only) + her overview
  const cl2 = (await call('POST', '/api/lists', {name: 'Carol stuff', kind: 'project'}, CKc)).id;
  await call('POST', `/api/lists/${cl2}/status`, {status: 'on_track', note: ''}, CKc);  // 2.352.0 B (#2752): tracked = has a status
  let wc2 = await boot({user: 'carol', hash: 'l/' + WORK}); let dc = wc2.document;
  wc2.eval(`openDetail(${t2})`); await idle(wc2);
  check([...dc.querySelectorAll('#detail [data-cf]')].every(e => e.disabled || e.readOnly), 'view only: field editors read-only');
  check(!dc.querySelector('#d-deps [data-act="dep-add"], #d-deps [data-act="wait-on"]') && !dc.querySelector('#d-deps [data-act="dep-rm"]'), 'view only: no dependency add / remove');
  check(/Design/.test(dc.querySelector('#d-deps').textContent), 'view only: sees the blocker');
  check(!dc.querySelector('.lhead [data-act="status"]:not([disabled])') || /At risk/.test(dc.querySelector('.lhead .stpill').textContent), 'view only: pill shown');
  dc.querySelector('.lhead .stpill').click(); await until(() => /Read-only/.test(lastModal(dc)?.textContent || '')); await idle(wc2);  // 2.624.0 (#3943)
  check(!lastModal(dc).querySelector('[data-m="save"]') && /Read-only/.test(lastModal(dc).textContent), 'view only: status dialog without save');
  lastModal(dc).remove();
  wc2.eval(`listModal(${WORK})`); await until(() => /only the owner and project admins can change them/.test(lastModal(dc)?.textContent || ''));  // 2.624.0 (#3943)
  // 2.152.2 (#2624): project instead of list
  check(!lastModal(dc).querySelector('#l-fields') && /only the owner and project admins can change them/.test(lastModal(dc).textContent), 'view only: list dialog shows fields read-only');
  lastModal(dc).remove(); wc2.eval('closeDetail()');
  wc2.location.hash = 'overview'; await until(() => dc.querySelector('.ovcard')); await idle(wc2);  // 2.624.0 (#3943)
  const cn = [...dc.querySelectorAll('.ovcard .ovname')].map(x => x.textContent.trim());
  check(cn.some(x => /Work/.test(x)) && cn.some(x => /Carol stuff/.test(x)) && !cn.some(x => x.includes('Home')), "carol's overview: only her lists: " + cn);
  wc2.close();

  // ================= bob (German): News for status + unblock, texts
  await call('POST', `/api/tasks/${t1}/complete`);
  let wb = await boot({user: 'bob', hash: 'news'}); let db = wb.document; await until(() => /Alice hat Design erledigt/.test(db.querySelector('#view')?.textContent || '')); await idle(wb);  // 2.624.0 (#3943): News drawn
  const nt = db.querySelector('#view').textContent;
  check(/Alice hat Design erledigt: Deine Aufgabe ist nicht mehr blockiert/.test(nt), 'bob News: unblock (German)');
  check(/Alice hat Work auf\s*Gefährdet gesetzt/.test(nt) && /Vendor is late/.test(nt), 'bob News: status update with note (German)');
  wb.location.hash = 'l/' + WORK; await until(() => db.querySelector('.lhead .stpill')); await idle(wb);  // 2.624.0 (#3943)
  check(/erledigt/.test(db.querySelector('.lhead').textContent) || /\d+ %?|\//.test(db.querySelector('.lhead .lprog').textContent), 'bob: header');
  check(/Gefährdet/.test(db.querySelector('.lhead .stpill').textContent), 'bob: German status label');
  wb.eval(`openDetail(${t3})`); await idle(wb);
  check(/Felder/.test(db.querySelector('.cfsec h5').textContent) && /Abhängigkeiten/.test(db.querySelector('#d-deps h5').textContent) && /Wartet auf…/.test(db.querySelector('#d-deps').textContent), 'bob: German detail sections');
  const EN = /\b(Waiting|Blocking|Dependencies|Fields|Custom fields|On track|At risk|Set status|Overview|stuck)\b/;
  check(!EN.test(db.querySelector('#detail').textContent + db.querySelector('#view').textContent + db.querySelector('#side').textContent), 'bob: no English leftovers');
  wb.location.hash = 'overview'; await until(() => db.querySelector('#top h1')?.textContent === 'Projektstatus'); await idle(wb);  // 2.624.0 (#3943)
  check(db.querySelector('#top h1').textContent === 'Projektstatus' && !EN.test(db.querySelector('#view').textContent), 'bob: German overview');
  // bob's private list: no status/fields editor for alice's fields; bob owns BOBL -> fields section in his dialog
  wb.eval(`listModal(${BOBL})`); await until(() => lastModal(db)?.querySelector('#l-fields'));  // 2.624.0 (#3943)
  check(lastModal(db).querySelector('#l-fields') && /Eigene Felder/.test(lastModal(db).textContent), 'bob: fields section in his own list dialog (German)');
  wb.close();

  // ================= mobile: no columns
  const wm = await boot({user: 'alice', mobile: true, hash: 'l/' + WORK, ls: {['tasks.fcols.' + WORK]: 'true'}});
  check(!wm.document.querySelector('.fcolhead') && !wm.document.querySelector('[data-act="cols"]'), 'mobile: no column view, no header button (Columns… is in the list menu)');
  check(wm.document.querySelector('.lhead .lprog'), 'mobile: progress header');
  wm.close();

  console.log(`${ok} ok, ${F.length} failed`); if (errs.length) console.log('JS errors:', errs);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
