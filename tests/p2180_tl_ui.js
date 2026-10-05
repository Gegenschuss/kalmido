// 2.18.0 UI tests, lane 2b (own container, isolated test database): the timeline with sections (#462), new tasks drawn
// right into it (#431) and milestone tasks as diamonds. jsdom: section header rows in the list order ("Unassigned"
// first), folding per device (aria-expanded, focus stays), drag across days -> inline field -> Enter = a task with exactly
// that start..due in that list + section, double-click = one day, "+ Add task" / the section "+" (keyboard path, focus to
// the new bar), Escape cancels, a plain click creates nothing, undo history, offline (outbox, start kept), a viewer
// cannot create, the calendar's timeline and the roadmap ("All" as a timeline) with sections + creating there, milestone
// diamonds (a11y name, drag moves the date, Enter opens, no second marker in the list row). Firefox: REAL pointer input:
// a mouse drag at 1440 (+ moving a diamond), touch long-press + drag at 390 and 904 (unfolded square, folded / rotated),
// a plain swipe scrolls and creates nothing, a quick tap does nothing, 44 px targets, nothing sideways, light + dark.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2180_tl_ui', check, shots: 'P2180_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const ptr = (w, el, type, x = 0, extra = {}) => {  // jsdom has no PointerEvent: a MouseEvent with pointerType / pointerId
  const e = new w.MouseEvent(type, {bubbles: true, cancelable: true, button: 0, clientX: x, clientY: 10, ...extra});
  Object.defineProperty(e, 'pointerType', {value: extra.pointerType || 'mouse'}); Object.defineProperty(e, 'pointerId', {value: 1});
  el.dispatchEvent(e);
};
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields';
const state = async (ck = CK) => {
  let j = await call('GET', '/api/state', null, ck);
  if (!j.tasks && ck === CK) { console.log('state: HTTP ' + j.status + ', signing in again'); CK = await login('alice'); j = await call('GET', '/api/state', null, CK); }
  return j.tasks || [];
};
const byTitle = async (t, ck = CK) => (await state(ck)).find(x => x.title === t);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ALL.split(',').filter(x => x !== 'collab')});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done', lang: 'en'}, CB);
  const P = (await call('POST', '/api/lists', {name: 'Relaunch', kind: 'project', view: 'timeline'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'view'});
  const SD = (await call('POST', '/api/sections', {list_id: P, name: 'Design'})).id;
  const SB = (await call('POST', '/api/sections', {list_id: P, name: 'Build'})).id;
  const SE = (await call('POST', '/api/sections', {list_id: P, name: 'Empty'})).id;
  const A = (await call('POST', '/api/tasks', {title: 'Sketches', list_id: P, section_id: SD, start: day(0), due: day(2)})).id;
  const Bt = (await call('POST', '/api/tasks', {title: 'Frontend', list_id: P, section_id: SB, start: day(1), due: day(4)})).id;
  const C = (await call('POST', '/api/tasks', {title: 'Kickoff', list_id: P, due: day(1)})).id;
  const M = (await call('POST', '/api/tasks', {title: 'Go live', list_id: P, section_id: SB, due: day(6), ms: 1})).id;
  const mT = (await state()).find(t => t.id === M);
  check(mT && mT.ms === 1, 'setup: a milestone task (lane 2a: ms = 1) ' + JSON.stringify(mT && {ms: mT.ms}));

  // ================= jsdom: the list timeline (alice, desktop)
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  await until(() => d.querySelector('#view .tl'));
  const secNames = () => [...d.querySelectorAll('.tl-sec .tl-secb .tln')].map(x => x.textContent);
  check(secNames().join() === 'Unassigned,Design,Build,Empty', '#462: section rows in the list order, "Unassigned" first, empty sections too in a list timeline: ' + secNames().join());
  const rowsOrder = [...d.querySelectorAll('#view .tl-row:not(.tl-headrow)')].map(r => r.classList.contains('tl-grp') ? 'L' : r.classList.contains('tl-sec') ? 'S:' + r.querySelector('.tln').textContent : r.classList.contains('tl-add') ? '+' : r.querySelector('[data-id]')?.dataset.id);
  check(rowsOrder.join() === ['L', 'S:Unassigned', C, 'S:Design', A, 'S:Build', Bt, M, 'S:Empty', '+'].join(), '#462: tasks under their section, "+ Add task" ends the list: ' + rowsOrder.join());
  // fold a section (per device), keyboard: a real button with aria-expanded
  const fold = sid => d.querySelector(`.tl-secb[data-key="tlsec:${sid}"]`);
  check(fold(SD).tagName === 'BUTTON' && fold(SD).getAttribute('aria-expanded') === 'true', 'section fold = button, aria-expanded');
  fold(SD).focus(); click(w, fold(SD)); await sleep(150);
  check(!d.querySelector(`.tl-bar[data-id="${A}"]`) && fold(SD).getAttribute('aria-expanded') === 'false' && /tlsec:/.test(w.__store['tasks.collapsed'] || ''), '#462: folded: its tasks hidden, saved per device');
  check(d.activeElement === fold(SD), 'the focus stays on the fold button');
  click(w, fold(SD)); await sleep(150);
  check(d.querySelector(`.tl-bar[data-id="${A}"]`), 'unfolded again');
  // milestone diamond
  const dia = () => d.querySelector(`.tl-bar.tl-dia[data-id="${M}"]`);
  check(dia() && /^Milestone: Go live, /.test(dia().getAttribute('aria-label')) && dia().getAttribute('role') === 'button' && dia().tabIndex === 0, 'milestone: a diamond with the a11y name "Milestone: name, date": ' + dia()?.getAttribute('aria-label'));
  check(!d.querySelector('.tl-grp .tl-ms') && d.querySelectorAll('.tl-msl').length === 1, 'one clean presentation: diamond row + thin vertical line, no second marker in the list row');
  check(dia().closest('.tl-row').classList.contains('tl-msrow') && !dia().querySelector('.h'), 'own row, no resize ends');
  // drag the diamond by 2 days (mouse)
  const DW = w.eval('tlDW()'), S0 = w.eval('S.tlStart');
  ptr(w, dia(), 'pointerdown', 100); ptr(w, d, 'pointermove', 100 + 2 * DW); ptr(w, d, 'pointerup', 100 + 2 * DW);
  check(await until(async () => (await state()).find(t => t.id === M)?.due === day(8)), 'milestone: dragging moves its date (+2 days)');
  await until(() => dia());
  dia().focus(); key(w, dia(), 'Enter'); await sleep(200);
  check(w.eval('S.sel') === M, 'milestone: Enter opens it like a bar');
  w.eval('closeDetail()'); await sleep(100);

  // review fixes (lane F1): no invalid inline style on timeline section / add rows (R10), month labels span their month
  // with a sticky text (R10), the footer tells how to create, a keyboard way to move a diamond (Shift+F10 menu, D)
  check(![...d.querySelectorAll('#view .tl-row')].some(r => /top:\s*px/.test(r.getAttribute('style') || '')) && !d.querySelector('#view .tl-sec.rm-row, #view .tl-add.rm-row'), 'review R10: no invalid "top:px" / roadmap classes on timeline section and add rows');
  const tms = [...d.querySelectorAll('.tl-months .tl-m')];
  check(tms.length && tms.every(m => /width:\s*\d/.test(m.getAttribute('style')) && m.querySelector('span')?.textContent), 'review R10: month labels span their month, text in a sticky span: ' + tms.map(m => m.getAttribute('style')).join(' | '));
  check(/double-click a day/.test(d.querySelector('.tl-foot')?.textContent || ''), 'review: the footer tells how to create a task: ' + d.querySelector('.tl-foot')?.textContent);
  dia().focus(); key(w, dia(), 'F10', {shiftKey: true}); await sleep(150);
  const dmi = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent);
  check(dmi.some(x => /Move to date…/.test(x)), 'review: the diamond menu (Shift+F10) offers "Move to date…": ' + dmi.join(' / '));
  w.eval('closePop()'); await sleep(50);
  await until(() => dia()); dia().focus(); key(w, dia(), 'd'); await sleep(150);
  check(!d.querySelector('#pop').classList.contains('hidden') && !d.querySelector('#pop [role="menu"]'), 'review: D on a focused diamond opens the date popover');
  w.eval('closePop()'); await sleep(100);

  // drag across empty days of the "Design" section row -> ghost -> inline field
  const track = k => d.querySelector(`.tl-track.tl-cr[data-k="${k}"]`);
  const dayAt = i => w.eval(`addDays(S.tlStart, ${i})`);
  const hist0 = w.eval('HIST.undo.length');
  ptr(w, track('tlsec:' + SD), 'pointerdown', 10 * DW + 5);
  ptr(w, d, 'pointermove', 11 * DW + 5);
  check(track('tlsec:' + SD).querySelector('.tl-ghost'), '#431: a ghost bar shows the range while dragging');
  ptr(w, d, 'pointermove', 13 * DW + 5); ptr(w, d, 'pointerup', 13 * DW + 5); await sleep(150);
  let inp = d.querySelector('#tl-new-in');
  check(inp && d.activeElement === inp && inp.closest('.tl-track').dataset.k === 'tlsec:' + SD, '#431: on release the title field opens in that row, focused');
  check(inp && /New task, /.test(d.querySelector('label[for="tl-new-in"]')?.textContent || ''), 'the field has a label');
  check(/\d.*–.*\d/.test(d.querySelector('.tl-new .tl-nws')?.textContent || ''), 'review R4: the field carries the range in short form too (shown on narrow screens): ' + d.querySelector('.tl-new .tl-nws')?.textContent);
  inp.value = 'Moodboard'; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  key(w, inp, 'Enter');
  const mb = await until(() => byTitle('Moodboard'));
  check(mb && mb.start === dayAt(10) && mb.due === dayAt(13) && mb.section_id === SD && mb.list_id === P, `#431: Enter creates the task with exactly that range in that list + section: ${mb && [mb.start, mb.due, mb.section_id].join()} (want ${dayAt(10)}..${dayAt(13)}, ${SD})`);
  check(await until(() => d.activeElement?.dataset?.id === String(mb?.id)), '#431: the focus moves to the new bar');
  check(!d.querySelector('#tl-new-in') && w.eval('HIST.undo.length') > hist0, 'the field is gone, one history step (undo)');
  // a plain click on a row creates nothing
  ptr(w, track('tlsec:' + SB), 'pointerdown', 9 * DW + 5); ptr(w, d, 'pointerup', 9 * DW + 5); await sleep(100);
  check(!d.querySelector('#tl-new-in'), 'a plain click opens nothing');
  // double-click a day of "Build" = one day
  track('tlsec:' + SB).dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true, clientX: 12 * DW + 5, clientY: 10}));
  await sleep(150); inp = d.querySelector('#tl-new-in');
  check(inp && d.activeElement === inp, '#431: double-click opens the field');
  inp.value = 'Deploy script'; key(w, inp, 'Enter');
  const ds_ = await until(() => byTitle('Deploy script'));
  check(ds_ && !ds_.start && ds_.due === dayAt(12) && ds_.section_id === SB, '#431: one day: due only, no start, section Build: ' + JSON.stringify(ds_ && [ds_.start, ds_.due, ds_.section_id]));
  // the list row: no section
  track('g:' + P).dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true, clientX: 14 * DW + 5, clientY: 10}));
  await sleep(150); inp = d.querySelector('#tl-new-in');
  inp.value = 'Loose end'; key(w, inp, 'Enter');
  const le = await until(() => byTitle('Loose end'));
  check(le && le.due === dayAt(14) && !le.section_id, '#431: on the list row: in the list, no section');
  // "+ Add task": keyboard path, Escape cancels, focus back to "+"
  const addb = () => d.querySelector(`.tl-addb[data-k="add:${P}"]`);
  check(addb() && addb().tagName === 'BUTTON' && /Add task/.test(addb().textContent) && /Add task to Relaunch/.test(addb().getAttribute('aria-label')), '"+ Add task" is a real button with a name');
  addb().focus(); click(w, addb()); await sleep(150);
  inp = d.querySelector('#tl-new-in');
  check(inp && d.activeElement === inp && w.eval('S.tlNew.d0') === w.eval('S.tlNew.d1'), '"+": the field opens on one day');
  const n0 = (await state()).length;
  key(w, inp, 'Escape'); await sleep(200);
  check(!d.querySelector('#tl-new-in') && d.activeElement === addb(), 'Escape cancels, the focus goes back to "+"');
  check((await state()).length === n0, 'Escape created nothing');
  click(w, addb()); await sleep(150);
  inp = d.querySelector('#tl-new-in'); inp.value = 'From plus'; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, d.querySelector('.tl-new [data-act="tl-new-ok"]'));
  const fp = await until(() => byTitle('From plus'));
  check(fp && fp.due === day(0) && !fp.start, '"+": the ✓ button creates it on today: ' + fp?.due);
  // the "+" of a section (collapsed section opens)
  click(w, fold(SE)); await sleep(150);
  click(w, d.querySelector(`.tl-secadd[data-k="tlsec:${SE}"]`)); await sleep(150);
  inp = d.querySelector('#tl-new-in');
  check(inp && fold(SE).getAttribute('aria-expanded') === 'true' && /Add task to Empty/.test(d.querySelector(`.tl-secadd[data-k="tlsec:${SE}"]`).getAttribute('aria-label')), 'section "+": named, opens a folded section');
  inp.value = 'In empty'; key(w, inp, 'Enter');
  const ie = await until(() => byTitle('In empty'));
  check(ie && ie.section_id === SE, 'section "+": created in that section');
  // a re-render while typing keeps the field and the text
  click(w, addb()); await sleep(150);
  inp = d.querySelector('#tl-new-in'); inp.value = 'Half typed'; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  w.eval('renderView()'); await sleep(100);
  check(d.querySelector('#tl-new-in')?.value === 'Half typed', 'a re-render (sync) keeps the field and its text');
  key(w, d.querySelector('#tl-new-in'), 'Escape'); await sleep(100);
  // offline: the normal create path (outbox), the range kept locally
  w.__offline = true;
  ptr(w, track('tlsec:' + SD), 'pointerdown', 20 * DW + 5); ptr(w, d, 'pointermove', 22 * DW + 5); ptr(w, d, 'pointerup', 22 * DW + 5); await sleep(150);
  inp = d.querySelector('#tl-new-in'); inp.value = 'Offline drawn'; key(w, inp, 'Enter'); await sleep(400);
  const off = w.eval(`(() => { const t = [...S.tasks.values()].find(x => x.title === 'Offline drawn'); return t ? [t.start, t.due, t.section_id] : null; })()`);
  check(off && off[0] === dayAt(20) && off[1] === dayAt(22) && off[2] === SD && d.querySelector('.tl-bar span') && [...d.querySelectorAll('.tl-bar span')].some(s => s.textContent === 'Offline drawn'), 'offline: created locally with its range, the bar is there: ' + JSON.stringify(off));
  w.__offline = false;
  w.eval('flush()');
  check(await until(async () => (await byTitle('Offline drawn'))?.start === dayAt(20), 60), 'offline: sent when back online, with the start');
  w.close();

  // ================= viewer: nothing to draw into
  w = await boot({user: 'bob', hash: 'l/' + P}); d = w.document;
  await until(() => d.querySelector('#view .tl'));
  check(d.querySelectorAll('.tl-sec').length >= 3 && !d.querySelector('.tl-track.tl-cr') && !d.querySelector('.tl-addb') && !d.querySelector('.tl-secadd'), 'viewer: sections shown, no "+" and no drawing tracks');
  const vt = d.querySelector('.tl-sec .tl-track');
  vt.dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true, clientX: 50, clientY: 10})); await sleep(150);
  check(!d.querySelector('#tl-new-in'), 'viewer: double-click does nothing');
  check(d.querySelector(`.tl-bar.tl-dia[data-id="${M}"]`)?.classList.contains('ro'), 'viewer: the diamond is read-only');
  w.close();

  // ================= the calendar's timeline
  await call('POST', '/api/sections', {list_id: P, name: 'Spare'});
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"timeline"'}}); d = w.document;
  await until(() => d.querySelector('#view .tl'));
  const cs = [...d.querySelectorAll('.tl-sec .tln')].map(x => x.textContent);
  check(cs.includes('Design') && cs.includes('Build') && !cs.includes('Spare'), 'calendar timeline: sections (only those with tasks): ' + cs.join());
  const cDW = w.eval('tlDW()');
  d.querySelector(`.tl-track.tl-cr[data-k="tlsec:${SB}"]`).dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true, clientX: 16 * cDW + 5, clientY: 10}));
  await sleep(150); inp = d.querySelector('#tl-new-in'); inp.value = 'From calendar'; key(w, inp, 'Enter');
  const fc = await until(() => byTitle('From calendar'));
  check(fc && fc.section_id === SB && fc.due === w.eval('addDays(S.tlStart, 16)'), 'calendar timeline: creating works there too');
  w.close();

  // ================= the roadmap ("All" as a timeline)
  await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline'})});
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  await until(() => d.querySelector('#rm-rows .rm-row'));
  const rs = [...d.querySelectorAll('#rm-rows .rm-s .tln')].map(x => x.textContent);
  check(rs.join() === 'Unassigned,Design,Build,Empty,Spare', 'roadmap: sections inside an expanded project: ' + rs.join());
  check(d.querySelector(`#rm-rows .rm-a [data-act="tl-add"][data-k="add:${P}"]`), 'roadmap: "+ Add task" at the end of the project');
  check(d.querySelector(`#rm-rows .rm-t .tl-bar.tl-dia[data-id="${M}"]`) && !d.querySelector(`.rm-g[data-l="${P}"] .rm-ms`), 'roadmap: the milestone as a diamond row, no second marker on the open project row');
  const G = w.eval('({s: S.rmV.G.start, dw: S.rmV.G.dw})');
  d.querySelector(`.tl-track.tl-cr[data-k="tlsec:${SD}"]`).dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true, clientX: 30 * G.dw + 1, clientY: 10}));
  await sleep(200); inp = d.querySelector('#tl-new-in');
  check(inp, 'roadmap: double-click on a section row opens the field');
  inp.value = 'From roadmap'; key(w, inp, 'Enter');
  const fr = await until(() => byTitle('From roadmap'));
  check(fr && fr.section_id === SD && fr.due === w.eval(`addDays('${G.s}', 30)`), 'roadmap: created in that section on that day');
  check(await until(() => d.activeElement?.dataset?.id === String(fr?.id)), 'roadmap: the focus on the new bar');
  // folding a section in the roadmap
  click(w, d.querySelector(`#rm-rows .tl-secb[data-key="tlsec:${SD}"]`)); await sleep(200);
  check(!d.querySelector(`#rm-rows .tl-bar[data-id="${A}"]`) && d.querySelector(`#rm-rows .tl-secb[data-key="tlsec:${SD}"]`)?.getAttribute('aria-expanded') === 'false', 'roadmap: a section folds');
  click(w, d.querySelector(`#rm-rows .tl-secb[data-key="tlsec:${SD}"]`)); await sleep(200);
  // collapsed project: the marker is back on its row
  w.eval(`rmToggle('l${P}')`); await sleep(200);
  check(d.querySelector(`.rm-g[data-l="${P}"] .rm-ms`) && !d.querySelector('#rm-rows .rm-s'), 'roadmap: a collapsed project shows its milestone marker, no section rows');
  w.close();
  await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'list'})});

  // ================= Firefox: real pointer input
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#view .tl')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const OVER = `(() => ({o: document.documentElement.scrollWidth - innerWidth, v: document.querySelector('#view').scrollWidth - document.querySelector('#view').clientWidth}))()`;
  // two points on the visible part of a row's track (k0 days in, then k1 days further) + the days they stand for
  const SPOT = (k, k0, k1) => `(() => { const tr = document.querySelector('.tl-track.tl-cr[data-k="${k}"]'); if (!tr) return null; tr.closest('.tl-row').scrollIntoView({block: 'center'});
    const sc = document.querySelector('#tlscroll'), nw = tr.closest('.tl-row').querySelector('.tl-name').getBoundingClientRect().right, r = tr.getBoundingClientRect(), rr = tr.closest('.tl-row').getBoundingClientRect(), dw = +tr.dataset.dw;
    const vis = Math.max(nw, r.left), i0 = Math.ceil((vis - r.left) / dw) + ${k0}, x0 = r.left + (i0 + .5) * dw, x1 = x0 + ${k1} * dw;
    return {x0, x1, y: rr.top + rr.height / 2, d0: addDays(tr.dataset.s0, i0), d1: addDays(tr.dataset.s0, i0 + ${k1}), sl: sc.scrollLeft, iw: innerWidth}; })()`;
  const typeKeys = (cmd, ctx, text) => cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k1', actions: [...text].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]}).then(() => cmd('input.releaseActions', {context: ctx}));
  const ENTER = '';
  const SMALL = `(() => { const out = []; for (const e of document.querySelectorAll('#view .tl-secb, #view .tl-secadd, #view .tl-addb, #view .tl-new .iconbtn, #view .tl-dia')) { const r = e.getBoundingClientRect(); if (!r.width) continue; if (r.width < 43.5 || r.height < 43.5) out.push((e.className || e.tagName) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)); } return out.slice(0, 6); })()`;

  // 1440, mouse, light: drag-create, move a diamond
  await firefox(async o => {
    const {cmd, ev, ctx, shot, drag} = o;
    check(await ffLogin(o, 'light') === 200, '1440: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + P); await ready(ev);
    const sp = await ev(SPOT('tlsec:' + SB, 1, 3));
    check(sp && sp.x1 < sp.iw, '1440: a spot on the Build row ' + JSON.stringify(sp));
    await drag(sp.x0, sp.y, sp.x1 - sp.x0, 0, 'mouse'); await sleep(400);
    check(await ev(`document.activeElement?.id === 'tl-new-in'`), '1440: after a real mouse drag the field is focused');
    await shot('p2180-tl-new-1440.png');
    await typeKeys(cmd, ctx, 'Real drag' + ENTER); await sleep(800);
    const rd = await until(() => byTitle('Real drag'));
    check(rd && rd.start === sp.d0 && rd.due === sp.d1 && rd.section_id === SB, `1440: a real drag created the exact range ${rd && rd.start}..${rd && rd.due} (want ${sp.d0}..${sp.d1})`);
    check(await ev(`document.activeElement?.dataset?.id === '${rd?.id}'`), '1440: the focus on the new bar');
    // move the diamond with the mouse by 1 day
    const before = (await state()).find(t => t.id === M)?.due;
    const dp = await ev(`(() => { const b = document.querySelector('.tl-dia[data-id="${M}"]'); b.scrollIntoView({block: 'center', inline: 'center'}); const r = b.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, dw: tlDW()}; })()`);
    await drag(dp.x, dp.y, dp.dw, 0, 'mouse'); await sleep(800);
    const after = (await state()).find(t => t.id === M)?.due;
    check(after === w_add(before, 1), `1440: a real mouse drag moves the diamond by one day ${before} -> ${after}`);
    const ov = await ev(OVER);
    check(ov.o <= 0, '1440: nothing sideways on the page ' + JSON.stringify(ov));
    await shot('p2180-tl-1440.png');
  }, false);

  // touch: 390 (dark), 904 unfolded, 904 x 412 rotated / folded
  for (const [vw, vh, th] of [[390, 844, 'dark'], [904, 904, 'light'], [904, 412, 'dark']]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${vw}x${vh} ${th}`;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await o.nav(B + '#l/' + P); await ready(ev);
    const ov = await ev(OVER);
    check(ov.o <= 0, `${tag}: nothing sideways on the page ` + JSON.stringify(ov));
    const sm = await ev(SMALL);
    check(!sm.length, `${tag}: 44 px targets ` + JSON.stringify(sm));
    const T = (acts) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: acts}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    const n0 = (await state()).length;
    // a quick tap does nothing
    let sp = await ev(SPOT('tlsec:' + SD, 0, 2));
    await T([{type: 'pointerMove', x: Math.round(sp.x0), y: Math.round(sp.y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]); await sleep(500);
    check(!(await ev(`!!document.querySelector('#tl-new-in')`)), `${tag}: a quick tap opens nothing`);
    // a plain swipe scrolls the timeline and creates nothing
    sp = await ev(SPOT('tlsec:' + SD, 3, 2));
    await T([{type: 'pointerMove', x: Math.round(sp.x0), y: Math.round(sp.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerMove', x: Math.round(sp.x0 - 60), y: Math.round(sp.y), duration: 60}, {type: 'pointerMove', x: Math.round(sp.x0 - 140), y: Math.round(sp.y), duration: 60}, {type: 'pointerUp', button: 0}]); await sleep(700);
    const sl = await ev(`document.querySelector('#tlscroll').scrollLeft`);
    check(!(await ev(`!!document.querySelector('#tl-new-in') || !!document.querySelector('.tl-ghost')`)), `${tag}: a swipe opens nothing`);
    // the same swipe on an empty spot of a plain task row (no drawing there): the drawing rows must scroll the same way
    const cp = await ev(`(() => { const row = document.querySelector('.tl-bar[data-id="${C}"]').closest('.tl-row'), tr = row.querySelector('.tl-track'); row.scrollIntoView({block: 'center'}); const r = row.getBoundingClientRect(), x = Math.min(innerWidth, tr.getBoundingClientRect().right, document.querySelector('#tlscroll').getBoundingClientRect().right) - 30, y = r.top + r.height / 2; return {x, y, ok: document.elementFromPoint(x, y) === tr, hit: document.elementFromPoint(x, y)?.className, sl: document.querySelector('#tlscroll').scrollLeft}; })()`);
    await T([{type: 'pointerMove', x: Math.round(cp.x), y: Math.round(cp.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerMove', x: Math.round(cp.x - 60), y: Math.round(cp.y), duration: 60}, {type: 'pointerMove', x: Math.round(cp.x - 140), y: Math.round(cp.y), duration: 60}, {type: 'pointerUp', button: 0}]); await sleep(700);
    const cl = await ev(`document.querySelector('#tlscroll').scrollLeft`);
    check(cp.ok && (sl !== sp.sl) === (cl !== cp.sl), `${tag}: a swipe on a drawing row scrolls like one on a plain row (drawing row ${sp.sl} -> ${sl}, plain row ${cp.sl} -> ${cl}, ${cp.ok ? '' : 'hit ' + cp.hit}; headless Firefox may not pan synthetic touches at all)`);
    check((await state()).length === n0, `${tag}: tap + swipe created nothing`);
    // long-press, then drag
    sp = await ev(SPOT('tlsec:' + SB, 1, 2));
    await T([{type: 'pointerMove', x: Math.round(sp.x0), y: Math.round(sp.y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 700},
      {type: 'pointerMove', x: Math.round((sp.x0 + sp.x1) / 2), y: Math.round(sp.y), duration: 150}, {type: 'pointerMove', x: Math.round(sp.x1), y: Math.round(sp.y), duration: 150}, {type: 'pointerUp', button: 0}]); await sleep(700);
    const f = await ev(`(() => { const i = document.querySelector('#tl-new-in'); if (!i) return null; const r = i.closest('.tl-new').getBoundingClientRect(), vv = visualViewport; return {d0: S.tlNew.d0, d1: S.tlNew.d1, l: r.left, r: r.right, b: r.bottom, vb: vv.offsetTop + vv.height, iw: innerWidth}; })()`);
    check(f && f.d0 === sp.d0 && f.d1 === sp.d1, `${tag}: long-press + drag: the field with the range ${f && f.d0}..${f && f.d1} (want ${sp.d0}..${sp.d1})`);
    check(f && f.l >= -0.5 && f.r <= f.iw + .5 && f.b <= f.vb + .5, `${tag}: the field is inside the visible viewport ` + JSON.stringify(f));
    const sm2 = await ev(SMALL);
    check(!sm2.length, `${tag}: the field's buttons are 44 px ` + JSON.stringify(sm2));
    await shot(`p2180-tl-${vw}x${vh}-${th}.png`);
    if (vw < 900) {
      // review R4: phones show the range in short form in the field; R5: section names are readable (not cut)
      const nw = await ev(`(() => { const e = document.querySelector('.tl-new .tl-nws'), r = e && e.getBoundingClientRect(); return {t: e?.textContent, w: r ? r.width : 0, cut: [...document.querySelectorAll('#view .tl-secb .tln')].filter(x => x.scrollWidth > x.clientWidth + 1).map(x => x.textContent)}; })()`);
      check(nw.w > 0 && /\d/.test(nw.t || ''), `${tag}: review R4: the short range shows in the field ` + JSON.stringify(nw));
      check(!nw.cut.length, `${tag}: review R5: section names are not cut ` + JSON.stringify(nw.cut));
      // review R2: with the keyboard up (the visible area shrinks to ~470 px) tab bar and "+" step aside, the field is visible
      const hid = await ev(`(() => ({c: document.body.classList.contains('tl-typing'), t: getComputedStyle(document.querySelector('#tabs')).display, f: getComputedStyle(document.querySelector('#fab')).display}))()`);
      check(hid.c && hid.t === 'none' && hid.f === 'none', `${tag}: review R2: tab bar and FAB hidden while the field has the focus ` + JSON.stringify(hid));
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 470}}); await sleep(700);
      const kb = await ev(`(() => { const i = document.querySelector('#tl-new-in'), b = i && i.closest('.tl-new').getBoundingClientRect(), vv = visualViewport, x = b && (b.left + b.right) / 2, y = b && (b.top + b.bottom) / 2, hit = b && document.elementFromPoint(x, y); return {act: document.activeElement === i, top: b && b.top, bot: b && b.bottom, vb: vv.offsetTop + vv.height, own: !!hit?.closest?.('.tl-new'), hit: hit?.id || hit?.className}; })()`);
      check(kb.act && kb.bot <= kb.vb + .5 && kb.top >= 0 && kb.own, `${tag}: review R2: in a ~470 px high view the field stays visible and uncovered ` + JSON.stringify(kb));
      await shot(`p2180-tl-${vw}-kb.png`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}}); await sleep(400);
    }
    await ev(`(() => { const i = document.querySelector('#tl-new-in'); i.value = 'Touch ${vw}x${vh}'; i.dispatchEvent(new Event('input', {bubbles: true})); i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return 1; })()`);
    const tt = await until(() => byTitle(`Touch ${vw}x${vh}`));
    check(tt && tt.start === sp.d0 && tt.due === sp.d1 && tt.section_id === SB, `${tag}: created with exactly that range in Build`);
    const ov2 = await ev(OVER);
    check(ov2.o <= 0, `${tag}: still nothing sideways ` + JSON.stringify(ov2));
    if (vw < 900) check(await until(() => ev(`!document.body.classList.contains('tl-typing') && getComputedStyle(document.querySelector('#tabs')).display !== 'none'`)), `${tag}: review R2: the tab bar is back after creating`);
    // review R4: a long-press on the first visible day right of the sticky names (inside the edge zone), a small wobble,
    // then a drag 2 days to the right: exactly the days under the finger, no edge auto-scroll during the press
    const eg = await ev(`(() => { const tr = document.querySelector('.tl-track.tl-cr[data-k="g:${P}"]'), row = tr.closest('.tl-row'); row.scrollIntoView({block: 'center'}); const sc = document.querySelector('#tlscroll'); if (sc.scrollLeft < 200) sc.scrollLeft = 200;
      const nr = row.querySelector('.tl-name').getBoundingClientRect().right, r = tr.getBoundingClientRect(), rr = row.getBoundingClientRect(), dw = +tr.dataset.dw, x0 = nr + 6, i0 = Math.floor((x0 - r.left) / dw);
      const hit = document.elementFromPoint(x0, rr.top + rr.height / 2); return {x0, x1: x0 + 2 * dw, y: rr.top + rr.height / 2, d0: addDays(tr.dataset.s0, i0), d1: addDays(tr.dataset.s0, i0 + 2), sl: sc.scrollLeft, hit: hit && (hit.className + '|' + (hit.closest('.tl-bar')?.dataset.id || ''))}; })()`);
    await T([{type: 'pointerMove', x: Math.round(eg.x0), y: Math.round(eg.y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 700}, {type: 'pointerMove', x: Math.round(eg.x0 - 4), y: Math.round(eg.y), duration: 60},
      {type: 'pointerMove', x: Math.round((eg.x0 + eg.x1) / 2), y: Math.round(eg.y), duration: 150}, {type: 'pointerMove', x: Math.round(eg.x1), y: Math.round(eg.y), duration: 150}, {type: 'pointerUp', button: 0}]); await sleep(700);
    const eN = await ev(`(() => ({n: S.tlNew && [S.tlNew.d0, S.tlNew.d1], sl: document.querySelector('#tlscroll').scrollLeft}))()`);
    check(eN.n && eN.n[0] === eg.d0 && eN.n[1] === eg.d1, `${tag}: review R4: long-press at the left edge: range ${eN.n} (want ${eg.d0},${eg.d1}; scrollLeft ${eg.sl} -> ${eN.sl}; under the finger: ${eg.hit})`);
    await ev(`(() => { const i = document.querySelector('#tl-new-in'); i?.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); return 1; })()`); await sleep(300);
    // review R10: scrolled into the month, its name still shows at the left of the visible range (sticky)
    const mo = await ev(`(() => { const sc = document.querySelector('#tlscroll'), nr = document.querySelector('.tl-headrow .tl-name').getBoundingClientRect().right, dw = tlDW();
      const ms = [...document.querySelectorAll('.tl-headrow .tl-m')], m = ms.find(x => { const r = x.getBoundingClientRect(); return r.left < nr + 1 && r.right > nr + 6 * dw; }); if (!m) return {none: true};
      const r0 = m.getBoundingClientRect(); sc.scrollLeft += 3 * dw; const s = m.querySelector('span').getBoundingClientRect(), r1 = m.getBoundingClientRect();
      return {t: m.textContent, sl: s.left, nr, ml: r1.left, w: s.width}; })()`);
    check(!mo.none && (mo.sl >= mo.nr - 1 && mo.sl <= mo.nr + 12 && mo.ml < mo.nr - 10 && mo.w > 20), `${tag}: review R10: the month name sticks right of the names when scrolled into the month ` + JSON.stringify(mo));
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
function w_add(s, n) { const d = new Date(s + 'T12:00:00'); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; }
