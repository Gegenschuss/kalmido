// Package D3 UI tests (jsdom), fresh DB on the test container: the roadmap ("All" as a timeline). The view switch
// List | Timeline (stored per user on the server, only with the timeline module), grouping by folder and list, the
// summary spans and the progress fill, collapse / expand (per group, all, the default by the number of projects, stored
// per user), the filter chips (projects only + its hint, hide done, assignee, list picker), dragging a summary bar with
// synthetic pointer events (the whole project moves on the server, dependents in other lists with "Move dependent tasks
// along", one undo in one request), the refusal for a view-only share, arrows into collapsed groups (merged, with a
// count), zoom week / month / quarter with prev / next / today, the phone path (long-press > "Move project by…"),
// the keyboard, German texts, the progress module off, and 50 projects with 1000 tasks (virtualised rows).
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const ds = n => { const t = new Date(), d = new Date(t.getFullYear(), t.getMonth(), t.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const ptr = (w, el, type, x = 0, extra = {}) => {  // jsdom has no PointerEvent: a MouseEvent with pointerType / pointerId
  const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, button: 0, clientX: x, clientY: 10, ...extra});
  Object.defineProperty(e, 'pointerType', {value: extra.pointerType || 'mouse'}); Object.defineProperty(e, 'pointerId', {value: 1});
  el.dispatchEvent(e);
};
const touch = (w, el, type, x = 10) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' ? [] : [{clientX: x, clientY: 10}]; el.dispatchEvent(e); return e; };
const key = (w, el, k, extra = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...extra}));
const st = async (ck = CK) => call('GET', '/api/state', null, ck);
const taskOf = async (id, ck = CK) => (await st(ck)).tasks.find(t => t.id === id);
const prefs = async (ck = CK) => { const s = (await st(ck)).settings.roadmap; return s ? JSON.parse(s) : {}; };
const toastText = d => d.querySelector('#toast:not(.hidden)')?.textContent || '';
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const spy = w => { const calls = []; const of = w.fetch; w.fetch = (u, o = {}) => { calls.push([(o.method || 'GET').toUpperCase(), String(u)]); return of(u, o); }; return calls; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const BK = await login('bob'), CKc = await login('carol');
  await call('PATCH', '/api/settings', {lang: 'de'}, BK);
  const L = async (name, kind = 'project', folder = '') => (await call('POST', '/api/lists', {name, kind, ...(folder ? {folder} : {})})).id;
  const WEB = await L('🌐 Website', 'project', 'Clients'), BRAND = await L('Brand', 'project', 'Clients'), FILM = await L('Film'), SHOP = await L('Groceries', 'list');
  await call('PATCH', '/api/settings', {folders: '["Clients"]'});
  await call('PATCH', `/api/lists/${WEB}`, {color: '#6d8cff'});
  await call('PUT', `/api/lists/${WEB}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${WEB}/members`, {user_id: CAROL, role: 'view'});
  await call('PUT', `/api/lists/${FILM}/members`, {user_id: BOB, role: 'edit'});
  const mk = async (title, list, start, due, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: list, ...(start != null ? {start: ds(start)} : {}), ...(due != null ? {due: ds(due)} : {}), ...extra})).id;
  const w1 = await mk('Kickoff', WEB, null, 1), w2 = await mk('Design', WEB, 2, 10, {assignee_id: BOB}), w3 = await mk('Build', WEB, 11, 30), wN = await mk('Ideas', WEB, null, null);
  const wD = await mk('Brief', WEB, null, 0);
  await call('POST', `/api/tasks/${wD}/complete`);
  const b1 = await mk('Moodboard', BRAND, 32, 40), f1 = await mk('Shoot', FILM, 12, 20), f2 = await mk('Cut', FILM, 21, 28);
  await mk('Milk', SHOP, null, 2);
  const dep = (w, b) => call('POST', '/api/deps', {task_id: w, blocker_id: b});
  await dep(b1, w3); await dep(f1, w1); await dep(f1, w2); await dep(f2, f1);

  // ================= view switch (alice, desktop)
  let w = await boot({user: 'alice', hash: 'all'}); let d = w.document;
  const seg = () => [...d.querySelectorAll('#top [data-act="rm-view"]')];
  check(seg().length === 2 && seg()[0].classList.contains('on') && d.querySelector('#view .trow'), '"All": List | Timeline switch, list view by default');
  seg()[1].click();
  check(await until(() => d.querySelector('.tl.rm')), 'Timeline: the roadmap');
  check(await until(async () => (await prefs()).v === 'timeline'), 'the choice is stored for the user on the server');
  check(!d.querySelector('#top [data-act="sort"]') && !d.querySelector('#top [data-act="multi"]'), 'no sort / multi-select in the roadmap');
  // grouping: projects only (default, a project exists) -> Film, folder Clients, Website, Brand
  const rows = () => [...d.querySelectorAll('#rm-rows .rm-row')];
  const gname = lid => d.querySelector(`.rm-g[data-l="${lid}"] .rm-gname`);
  const sum = lid => d.querySelector(`.rm-sum[data-lid="${lid}"]`);
  // 2.0.6 (#189): the "No date" rows (rm-nh / rm-u) are not groups
  const order = rows().filter(r => !r.classList.contains('rm-t') && !r.classList.contains('rm-u') && !r.classList.contains('rm-nh') && !r.classList.contains('rm-s') && !r.classList.contains('rm-a')).map(r => r.classList.contains('rm-f') ? 'F:' + r.textContent.trim().replace(/\d+$/, '') : +r.dataset.l);
  check(JSON.stringify(order) === JSON.stringify([FILM, 'F:Clients', WEB, BRAND]), `groups: lists without folder, then the folder with its lists: ${JSON.stringify(order)}`);
  check(d.querySelector('[data-act="rm-po"]').classList.contains('on') && !d.querySelector(`.rm-g[data-l="${SHOP}"]`), 'Projects only: on by default (a project exists), plain lists hidden');
  check(!d.querySelector('.rm-hint'), 'no hint while projects exist');
  check(d.querySelectorAll(`.rm-t[data-l="${WEB}"]`).length === 3, 'fewer than 5 projects: expanded, open dated tasks as rows (undated / done not)');
  // summary spans
  let V = w.eval('({s: S.rmV.G.start, dw: S.rmV.G.dw, z: S.rmV.G.z})');
  const X = n => Math.round(((new Date(ds(n)) - new Date(V.s)) / 864e5)) * V.dw;
  check(V.z === 'month' && Math.abs(parseFloat(sum(WEB).style.left) - X(1)) < .01 && Math.abs(parseFloat(sum(WEB).style.width) - (X(30) + V.dw - X(1))) < .01, `summary bar: earliest date .. latest due (month zoom) ${sum(WEB).style.left} ${sum(WEB).style.width}`);
  check(Math.abs(parseFloat(sum(FILM).style.left) - X(12)) < .01, 'summary bar starts at the earliest start');
  check(sum(WEB).querySelector('.rm-fill').style.width === '20%' && /20%/.test(sum(WEB).nextElementSibling.textContent), 'progress fill: 1 of 5 main tasks done = 20 %');
  check(sum(WEB).style.getPropertyValue('--lc') === '#6d8cff' && sum(WEB).nextElementSibling.querySelector('.rm-em')?.textContent === '🌐', 'list colour + emoji on the summary bar');
  check(sum(WEB).querySelectorAll('.cap').length === 2 && sum(WEB).getAttribute('role') === 'button' && sum(WEB).tabIndex === 0, 'bracket bar with end caps, focusable');
  check(/Website/.test(sum(WEB).getAttribute('aria-label')) && /20 % done/.test(sum(WEB).getAttribute('aria-label')), 'accessible label with the dates and progress');
  // arrows: across groups while expanded
  const dep_ = k => d.querySelector(`#tl-deps g.dep[data-dep="${k}"]`);
  check(await until(() => dep_(`${f1}:${w2}`) && dep_(`${b1}:${w3}`)), 'arrows between tasks of different lists');
  // ---- collapse one group
  gname(WEB).click();
  check(await until(() => !d.querySelector(`.rm-t[data-l="${WEB}"]`)), 'click on the name: the list collapses to its summary row');
  check(await until(async () => (await prefs()).t?.['l' + WEB] === 0), 'collapse state stored per user');
  const agg = () => d.querySelector('#tl-deps g.dep[data-rmdep]');
  check(await until(() => agg()), 'collapsed: the two arrows Website -> Shoot merged into one');
  check(agg() && agg().querySelector('.rm-badge text').textContent === '2' && agg().dataset.rmdep.split(',').length === 2, 'merged arrow with a count badge');
  check(dep_(`${b1}:${w3}`)?.classList.contains('agg'), 'a single arrow from a collapsed list starts at its summary bar');
  agg().querySelector('.hit').dispatchEvent(new w.MouseEvent('click', {bubbles: true})); await sleep(100);
  let pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /“Shoot” waits on “Kickoff”/.test(pop.textContent) && /“Shoot” waits on “Design”/.test(pop.textContent), 'merged arrow: popover lists both');
  w.eval('closePop()');
  // ---- collapse all / expand all
  d.querySelector('[data-act="rm-collapse"]').click();
  check(await until(() => !d.querySelector('.rm-t')), 'Collapse all: one row per project');
  check(await until(async () => (await prefs()).def === 'c'), 'stored');
  d.querySelector('[data-act="rm-expand"]').click();
  check(await until(() => d.querySelectorAll('.rm-t').length === 6), 'Expand all');
  // ---- filters
  d.querySelector('[data-act="rm-hd"]').click();
  check(await until(() => d.querySelector(`.tl-bar.done[data-id="${wD}"]`)), 'Hide done off: completed task shown, struck through');
  d.querySelector('[data-act="rm-hd"]').click();
  check(await until(() => !d.querySelector(`.tl-bar[data-id="${wD}"]`)), 'Hide done on again');
  d.querySelector('[data-act="rm-po"]').click();
  check(await until(() => d.querySelector(`.rm-g[data-l="${SHOP}"]`)), 'Projects only off: plain lists with dated tasks appear');
  check(!d.querySelector(`.rm-g[data-l="${SHOP}"] .rm-fill[style*="%"]`) || sum(SHOP).querySelector('.rm-fill').style.width === '0%', 'a plain list has no progress fill');
  d.querySelector('[data-act="rm-po"]').click();
  await until(() => !d.querySelector(`.rm-g[data-l="${SHOP}"]`));
  d.querySelector('[data-act="rm-who"]').click(); await sleep(100);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Everyone/.test(pop.textContent) && /Unassigned/.test(pop.textContent) && /Bob/.test(pop.textContent), 'assignee filter: everyone, me, unassigned, the people');
  [...pop.querySelectorAll('button')].find(b => b.textContent.trim() === 'Bob').click();
  check(await until(() => d.querySelectorAll('.rm-t').length === 1 && d.querySelector(`.tl-bar[data-id="${w2}"]`) && !d.querySelector(`.rm-g[data-l="${BRAND}"]`)), 'assignee Bob: only his task, lists without a match hidden');
  check(d.querySelector('[data-act="rm-who"]').classList.contains('on') && /Bob/.test(d.querySelector('[data-act="rm-who"]').textContent), 'chip shows the filter');
  w.eval("rmSet({who: ''})");
  d.querySelector('[data-act="rm-lists"]').click(); await sleep(100);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && pop.querySelector(`input[data-l="${FILM}"]`) && pop.querySelector('input[data-f="Clients"]'), 'list picker: lists and folders');
  const cb = pop.querySelector('input[data-f="Clients"]'); cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => !d.querySelector(`.rm-g[data-l="${FILM}"]`) && d.querySelector(`.rm-g[data-l="${WEB}"]`) && d.querySelector(`.rm-g[data-l="${BRAND}"]`)), 'folder ticked: only its lists');
  check(await until(async () => JSON.stringify((await prefs()).ls) === JSON.stringify([WEB, BRAND])), 'list selection stored');
  w.eval('closePop()'); w.eval('rmSet({ls: []})');
  await until(() => d.querySelector(`.rm-g[data-l="${FILM}"]`));
  // ---- zoom + navigation
  d.querySelector('[data-act="rm-zoom"][data-k="quarter"]').click();
  check(await until(() => d.querySelector('.tl.rm.z-quarter')), 'Quarter zoom');
  V = w.eval('({s: S.rmV.G.start, dw: S.rmV.G.dw, days: S.rmV.G.days})');
  check(Math.abs(V.dw - 4) < .001 && V.days === 546 && d.querySelectorAll('.tl-days .rm-w').length === 78 && d.querySelectorAll('.tl-days .rm-ml').length >= 17, `quarter: week columns (78), month labels, 4 px per day: ${V.dw}`);
  check(/^Q\d \d{4}$/.test(d.querySelector('.tl-months .tl-m').textContent), 'quarter labels on top');
  check(await until(async () => (await prefs()).z === 'quarter'), 'zoom stored per user');
  d.querySelector('[data-act="rm-zoom"][data-k="week"]').click();
  check(await until(() => d.querySelectorAll('.tl-days .tl-d').length === 84), 'Week zoom: day columns');
  const s0 = w.eval('S.rmStart');
  d.querySelector('[data-act="rm-next"]').click();
  check(w.eval('S.rmStart') === w.eval(`addDays('${s0}', 14)`), 'next: two weeks on');
  d.querySelector('[data-act="rm-prev"]').click(); d.querySelector('[data-act="rm-prev"]').click();
  check(w.eval('S.rmStart') === w.eval(`addDays('${s0}', -14)`), 'prev');
  d.querySelector('[data-act="rm-today"]').click();
  check(w.eval('S.rmStart') === s0, 'Today: back');
  d.querySelector('[data-act="rm-zoom"][data-k="month"]').click();
  await until(() => d.querySelector('.tl.rm.z-month'));
  check(errs.length === 0, 'no script errors (grouping, filters, zoom): ' + errs.join(' | '));

  // ---- drag a summary bar: the whole project moves, one undo in one request
  const calls = spy(w);
  const DW = w.eval('S.rmV.G.dw');
  const before = {};
  for (const id of [w1, w2, w3]) before[id] = await taskOf(id);
  ptr(w, sum(WEB), 'pointerdown', 100); ptr(w, d, 'pointermove', 100 + 3 * DW + 2);
  check(sum(WEB).style.transform === `translateX(${3 * DW}px)` && d.querySelector(`.tl-bar[data-id="${w3}"]`).style.transform === `translateX(${3 * DW}px)`, 'while dragging: the summary bar and the task bars of the list move along');
  check(/3 days later/.test(sum(WEB).nextElementSibling.textContent), 'the delta next to the bar');
  check(!d.querySelector(`.tl-bar[data-id="${f1}"]`).style.transform, 'other lists stay');
  ptr(w, d, 'pointerup', 100 + 3 * DW + 2);
  check(await until(async () => (await taskOf(w3)).due === ds(33)), 'drop: moved on the server');
  const a1 = await taskOf(w1), a2 = await taskOf(w2), aN = await taskOf(wN);
  check(a1.due === ds(4) && a2.start === ds(5) && a2.due === ds(13) && !aN.due, 'every open dated task +3 days, durations kept, undated untouched');
  check((await taskOf(f1)).due === ds(20), 'Film has "Move dependent tasks along" off: not moved');
  check(await until(() => /3 tasks moved/.test(toastText(d)) && d.querySelector('#toast button')), `toast "3 tasks moved" with Undo: ${toastText(d)}`);
  check(calls.filter(c => c[0] === 'POST' && /\/api\/lists\/\d+\/shift/.test(c[1])).length === 1, 'one request for the whole project');
  calls.length = 0;
  d.querySelector('#toast button').click();
  check(await until(async () => (await taskOf(w3)).due === before[w3].due && (await taskOf(w2)).start === before[w2].start && (await taskOf(w1)).due === before[w1].due), 'one undo: everything back');
  const wr = calls.filter(c => c[0] !== 'GET' && /\/api\/tasks/.test(c[1]));
  check(wr.length === 1 && /\/api\/tasks\/batch/.test(wr[0][1]), `the undo is one request too: ${JSON.stringify(wr)}`);
  // with dependents in another list (Film: setting on)
  // the undo reloads and redraws after the server answered; on a busy CI runner that can take longer than 4 s, and a drag
  // that starts before it ends races its reload (2.12.1: the drag below then never reached the server)
  check(await until(() => !w.eval('HIST.busy'), 20000), 'the undo has finished (reload + redraw)');
  await call('PATCH', `/api/lists/${FILM}`, {dep_shift: true});
  await w.eval('load().then(() => render())');
  await until(() => sum(WEB) && w.eval('!!S.rmV') && !w.eval('HIST.busy'), 8000); await sleep(300);
  calls.length = 0;
  ptr(w, sum(WEB), 'pointerdown', 100); ptr(w, d, 'pointermove', 100 + 10 * DW); ptr(w, d, 'pointerup', 100 + 10 * DW);
  check(await until(() => calls.some(c => c[0] === 'POST' && /\/api\/lists\/\d+\/shift/.test(c[1])), 8000),
    `the drag sends the shift request: ${JSON.stringify(calls.slice(-4))} ${toastText(d)}`);
  // the shift with dependents can take longer than 4 s on a busy CI runner (2.11.0: the toast came, the poll had given up)
  check(await until(async () => (await taskOf(f1)).start === ds(22), 20000), 'dependent task in another list moved along (Shoot waits on Design)');
  await until(async () => (await taskOf(f2)).start === ds(31), 8000);
  const f2x = await taskOf(f2); check(f2x.start === ds(31), `and its own dependent (Cut waits on Shoot): ${f2x.start} ${f2x.due}`);
  check(await until(() => /3 tasks moved · 2 dependent tasks moved/.test(toastText(d))), `toast names both: ${toastText(d)}`);
  d.querySelector('#toast button').click();
  check(await until(async () => (await taskOf(f1)).start === ds(12) && (await taskOf(f2)).due === ds(28) && (await taskOf(w3)).due === ds(30)), 'one undo takes the dependents back too');
  // a click (no movement) = menu; keyboard
  await sleep(450);  // a click right after a drag is swallowed (400 ms)
  ptr(w, sum(WEB), 'pointerdown', 100); ptr(w, d, 'pointerup', 100); sum(WEB).click(); await sleep(100);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && /Move project by…/.test(pop.textContent) && /Open list/.test(pop.textContent) && /Collapse/.test(pop.textContent), `click on a summary bar: menu (move by, open list, collapse): ${d.querySelector('#pop').className} ${d.querySelector('#pop').textContent.slice(0, 80)} ${w.eval('rmDragged')}`);
  w.eval('closePop()');
  sum(FILM).focus(); key(w, sum(FILM), 'm'); await sleep(100);
  let md = lastModal(d);
  check(md && md.classList.contains('rmmodal') && /Film/.test(md.textContent) && /2 open tasks with a date/.test(md.textContent), 'keyboard M: "Move project by…" dialog');
  md.querySelector('[data-q="-7"]').click();
  check(md.querySelector('#rm-n').value === '-1' && md.querySelector('#rm-unit .on').dataset.u === '7' && /→/.test(md.querySelector('#rm-prev').textContent), 'quick choice: 1 week earlier, preview of the new span');
  md.querySelector('#rm-ok').click();
  check(await until(async () => (await taskOf(f1)).start === ds(5)), 'dialog: moved 7 days earlier');
  check(await until(() => /2 tasks moved/.test(toastText(d))), 'toast');
  d.querySelector('#toast button').click();
  await until(async () => (await taskOf(f1)).start === ds(12));
  gname(WEB).focus(); key(w, gname(WEB), 'Enter');
  check(await until(() => !d.querySelector(`.rm-t[data-l="${WEB}"]`)), 'keyboard Enter on a name: collapse');
  key(w, d.querySelector(`.rm-gname[data-key="l${WEB}"]`), 'Enter');
  check(await until(() => d.querySelector(`.rm-t[data-l="${WEB}"]`)), 'and expand');
  // the cap: shown before anything is sent
  check(errs.length === 0, 'no script errors (drag, undo, keyboard): ' + errs.join(' | '));
  w.close();

  // ================= view-only share: no moving
  await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline'})}, CKc);
  w = await boot({user: 'carol', hash: 'all'}); d = w.document;
  check(await until(() => sum(WEB)), 'view-only member sees the shared project');
  check(sum(WEB).classList.contains('ro') && d.querySelector(`.rm-g[data-l="${WEB}"] .rm-ro`), 'marked read-only');
  const cc = spy(w);
  ptr(w, sum(WEB), 'pointerdown', 100); ptr(w, d, 'pointermove', 160);
  check(!sum(WEB).style.transform, 'view-only: the bar does not move');
  ptr(w, d, 'pointerup', 160);
  check(await until(() => /View only/.test(toastText(d))), `view-only: toast instead: ${toastText(d)}`);
  check(!cc.some(c => /shift/.test(c[1])), 'nothing sent');
  const r = await call('POST', `/api/lists/${WEB}/shift`, {days: 3}, CKc);
  check(/view only/i.test(r.error || ''), `the server refuses too: ${r.error}`);
  await sleep(450); sum(WEB).click(); await sleep(100);
  pop = d.querySelector('#pop:not(.hidden)');
  check(pop && !/Move project by/.test(pop.textContent) && /Open list/.test(pop.textContent), 'view-only: menu without "Move project by…"');
  w.close();

  // ================= phone: long-press > "Move project by…" (bob, German)
  await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline'})}, BK);
  w = await boot({user: 'bob', hash: 'all', mobile: true, media: {'(hover: none)': true}}); d = w.document;
  check(await until(() => sum(WEB)), 'phone: roadmap');
  check(d.querySelector('[data-act="rm-po"]').textContent === 'Nur Projekte' && /lange drücken/.test(d.querySelector('.tl-foot').textContent), 'German labels + touch hint');
  check(w.eval('S.rmV.G.rh') >= 40 && w.eval('isMobile()'), 'phone: taller rows (tap targets)');
  touch(w, sum(WEB), 'touchstart'); await sleep(250);
  touch(w, sum(WEB), 'touchmove', 30);
  await sleep(350);
  check(!d.querySelector('.rmmodal'), 'moving the finger (scrolling) cancels the long-press');
  touch(w, sum(WEB), 'touchend');
  touch(w, sum(WEB), 'touchstart'); await sleep(550);
  const te = touch(w, sum(WEB), 'touchend');
  md = lastModal(d);
  check(md && md.classList.contains('rmmodal') && /Projekt verschieben um…/.test(md.textContent), 'long-press: "Move project by…" (German)');
  check(te.defaultPrevented, 'no click after the hold');
  md.querySelector('#rm-n').value = '2'; md.querySelector('#rm-n').dispatchEvent(new w.Event('input', {bubbles: true}));
  check(/→/.test(md.querySelector('#rm-prev').textContent), 'preview updates');
  md.querySelector('#rm-ok').click();
  check(await until(async () => (await taskOf(w3, BK)).due === ds(44)), 'moved by 2 weeks');
  check(await until(() => /3 Aufgaben verschoben/.test(toastText(d))), `German toast: ${toastText(d)}`);
  d.querySelector('#toast button').click();
  check(await until(async () => (await taskOf(w3, BK)).due === ds(30)), 'undo');
  check(errs.length === 0, 'no script errors (phone): ' + errs.join(' | '));
  w.close();

  // ================= module switches: progress off -> no fill; timeline off -> no switch, the list
  const full = (await st()).settings.features;
  await call('PATCH', '/api/settings', {features: full.split(',').filter(f => f !== 'progress').join(',')});
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  check(sum(WEB) && sum(WEB).querySelector('.rm-fill').style.width === '0%' && !/%/.test(sum(WEB).nextElementSibling.textContent), 'progress module off: no fill, no percentage');
  w.close();
  await call('PATCH', '/api/settings', {features: full.split(',').filter(f => !['timeline', 'deps', 'time', 'fields', 'collab', 'progress'].includes(f)).join(',')});
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  check(!d.querySelector('#top [data-act="rm-view"]') && !d.querySelector('.tl.rm') && d.querySelector('#view .trow'), 'timeline module off: "All" is the list, no switch');
  check(errs.length === 0, 'no script errors (modules off): ' + errs.join(' | '));
  w.close();
  await call('PATCH', '/api/settings', {features: full, roadmap: ''});

  // ================= no project yet: hint; 5+ projects: collapsed by default; 50 projects x 20 tasks
  const AL = (await st()).lists;
  await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline'})});
  for (const id of [WEB, BRAND, FILM]) await call('PATCH', `/api/lists/${id}`, {kind: 'list'});
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  check(!d.querySelector('[data-act="rm-po"]').classList.contains('on') && /Make a list a project to plan it here/.test(d.querySelector('.rm-hint')?.textContent || ''), 'no project: "Projects only" off, with the hint');
  check(d.querySelector(`.rm-g[data-l="${SHOP}"]`) && d.querySelector(`.rm-g[data-l="${WEB}"]`), 'no project: every list with dates');
  w.close();
  for (const id of [WEB, BRAND, FILM]) await call('PATCH', `/api/lists/${id}`, {kind: 'project'});
  for (let i = 0; i < 3; i++) { const l = await L('Extra ' + i); await mk('T' + i, l, 1, 5 + i); }
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  check(d.querySelectorAll('.rm-g').length === 6 && !d.querySelector('.rm-t'), '6 projects: collapsed by default');
  w.close();
  // 50 projects, 1000 tasks: straight into the test database would bypass the app; the API is fast enough
  const big = [];
  for (let i = 0; i < 44; i++) big.push(L('P' + String(i).padStart(2, '0')));
  const bl = await Promise.all(big);
  const jobs = [];
  for (const l of bl) for (let k = 0; k < 22; k++) jobs.push(() => mk('Task ' + k, l, k * 3, k * 3 + 4));
  for (let i = 0; i < jobs.length; i += 25) await Promise.all(jobs.slice(i, i + 25).map(f => f()));
  await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline', def: 'e'})});
  w = await boot({user: 'alice', hash: 'all', wait: 4000}); d = w.document;
  const nModel = w.eval('S.rmV.M.rows.length'), nDom = d.querySelectorAll('#rm-rows .rm-row').length;
  check(nModel > 1000 && nDom <= 64, `virtualised: ${nModel} rows in the model, ${nDom} in the DOM`);
  const t0 = Date.now(); w.eval('renderView()'); const ms = Date.now() - t0;
  check(ms < 1500, `a full redraw with 1000+ rows stays quick (jsdom): ${ms} ms`);
  const sc = d.querySelector('#tlscroll'), rh = w.eval('S.rmV.G.rh'), hh = w.eval('S.rmV.G.hh');
  sc.scrollTop = 600 * rh; sc.dispatchEvent(new w.Event('scroll')); await sleep(120);
  const firstTop = parseFloat(d.querySelector('#rm-rows .rm-row').style.top);
  check(firstTop > 500 * rh + hh && firstTop <= 600 * rh + hh && d.querySelectorAll('#rm-rows .rm-row').length <= 64, `scrolling: the rows in view are drawn (${firstTop})`);
  check(d.querySelectorAll('#tl-deps g.dep').length >= 1, 'arrows still drawn');
  check(errs.length === 0, 'no script errors (large): ' + errs.join(' | '));
  w.close();
  void AL;

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
