// 2.26.0 UI tests (the web client part), own container (start.sh). jsdom:
// #936 multi-select + multi-edit in the task panel: Shift-click = range from the anchor (the open task), Ctrl/Cmd-click
//      toggles one; from two tasks the panel shows "n tasks" with the common fields: the same value shows, different ones
//      show "Mixed"; a change applies to all at once, keeps the "changed" marker, and is ONE undo step; tags half filled
//      (only some have it), a click adds to all, the next removes from all; the date shifted by +1 day keeps the
//      differences; fields of a view-only / participant list are locked with the number of tasks; the selection bar has
//      only count, Complete, Delete, Clear selection (phone: + Edit = the panel as a sheet); a plain click opens one task
//      and ends the selection; a selected title opens that task alone; the keyboard keys d / m reach the panel
// #932 the sidebar's width: a grip (keyboard ← →, Home / End, Enter / double-click = standard), stored per device
// #937 the iOS keyboard (a visual viewport that shrinks, also scrolled): the docked quick add, the comment box of the task
//      panel and the team chat's composer stay inside the visible area (Firefox, 390 x 844 and a tablet 820 x 1180)
// Firefox: 1440 mouse (a real Shift-click range, the multi panel light + dark, the sidebar dragged wider), 1280 / 1920
// with the task panel open (nothing overlaps, the list keeps its room), 390 touch (the sheet), screenshots in
// $P2260_SHOTS when set.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2260_ui', check, shots: 'P2260_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const BASE = 'cal,comments,collab,time,progress,agents,kanban,timeline,matrix';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); };
const getT = async id => (await call('GET', '/api/tasks/' + id));

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: BASE});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: BASE}, BCK);
  const ME_ID = (await call('GET', '/api/state')).me.id;
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const mk = async (title, o = {}, ck = CK) => (await call('POST', '/api/tasks', {title, list_id: L, ...o}, ck)).id;
  const T = [];
  T.push(await mk('Cut the hedge', {due: day(1), priority: 3, tags: ['a']}));
  T.push(await mk('Buy seeds', {due: day(2), priority: 3, tags: ['a']}));
  T.push(await mk('Water the roses', {due: day(3), priority: 3, tags: ['a']}));
  T.push(await mk('Fix the fence', {due: day(4), priority: 3, tags: ['a']}));
  T.push(await mk('Rake the leaves', {due: day(5), priority: 3, tags: ['a']}));
  // bob's lists: one shared with alice view-only, one where alice is a participant
  const QV = (await call('POST', '/api/lists', {name: 'Bob view'}, BCK)).id;
  await call('PUT', `/api/lists/${QV}/members`, {user_id: ME_ID, role: 'view'}, BCK);
  const V1 = (await call('POST', '/api/tasks', {title: 'Bob plan A', list_id: QV, priority: 3}, BCK)).id;
  const V2 = (await call('POST', '/api/tasks', {title: 'Bob plan B', list_id: QV, priority: 3}, BCK)).id;
  const QP = (await call('POST', '/api/lists', {name: 'Bob team'}, BCK)).id;
  await call('PUT', `/api/lists/${QP}/members`, {user_id: ME_ID, role: 'participant'}, BCK);
  const P1 = (await call('POST', '/api/tasks', {title: 'Alice part', list_id: QP, assignee_id: ME_ID}, BCK)).id;

  // ================= #936 desktop (jsdom)
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T[0]}"]`));
  const ttl = id => d.querySelector(`#view .trow[data-id="${id}"] .ttl`);
  const multi = () => JSON.stringify(w.eval('[...S.multi].sort((a, b) => a - b)'));
  const want = ids => JSON.stringify([...ids].sort((a, b) => a - b));
  // the rows in their visible order: O[0..4]; the selection used below: O[0], O[2], O[4]
  const O = [...d.querySelectorAll('#view .trow')].map(x => +x.dataset.id).filter(id => T.includes(id));
  check(O.length === 5, 'five rows ' + O);
  click(w, ttl(O[0])); await sleep(200);
  check(w.eval('S.sel') === O[0], 'a plain click opens the task');
  click(w, ttl(O[2]), {shiftKey: true}); await sleep(200);
  check(multi() === want([O[0], O[1], O[2]]), '#936: Shift-click selects the range from the open task (visible order) ' + multi());
  check(d.querySelector('#detail.multi') && w.eval('S.sel') === null, '#936: the panel turns into the multi panel');
  check(/^3 tasks$/.test(d.querySelector('#detail .mecount')?.textContent || ''), '#936: "3 tasks" on top: ' + d.querySelector('#detail .mecount')?.textContent);
  click(w, ttl(O[4]), {ctrlKey: true}); await sleep(150);
  check(multi() === want([O[0], O[1], O[2], O[4]]), '#936: Ctrl-click adds one');
  click(w, ttl(O[1]), {metaKey: true}); await sleep(150);
  check(multi() === want([O[0], O[2], O[4]]), '#936: Cmd-click removes one again');
  // one of them gets the tag b (half filled below), the dates stay different
  const SEL = [O[0], O[2], O[4]], OUT = O[1];
  await call('PATCH', '/api/tasks/' + O[2], {tags: ['a', 'b']}); await w.eval('load().then(() => render())'); await sleep(300);
  check(d.querySelectorAll('#view .trow.msel').length === 3, '#936: the rows are marked');
  // the bar: count, Complete, Delete, Clear selection
  const barActs = () => [...d.querySelectorAll('#mbar > *')].map(x => x.dataset.act || x.className.split(' ')[0]);
  check(JSON.stringify(barActs()) === JSON.stringify(['mcount', 'mb-done', 'mb-del', 'mb-close']), '#936: the bar has only count, Complete, Delete, Clear selection: ' + barActs().join('|'));
  // common vs mixed
  const fld = k => d.querySelector(`#detail .mef[data-k="${k}"]`);
  const val = k => fld(k)?.querySelector('.mev');
  check(val('priority') && !val('priority').classList.contains('mixed') && /Medium/.test(val('priority').textContent), '#936: the same priority shows as it is: ' + val('priority')?.textContent);
  check(val('date')?.classList.contains('mixed') && /Mixed/.test(val('date').textContent), '#936: different dates: "Mixed"');
  check(val('list') && /Garden/.test(val('list').textContent) && !val('list').classList.contains('mixed'), '#936: the common list');
  check(!d.querySelector('#detail #d-title, #detail #d-content, #detail #c-input, #detail #d-sub'), '#936: no title / notes / comments / subtasks for many');
  const titles = [...d.querySelectorAll('#detail .melist .metl')].map(b => b.textContent.trim());
  check(titles.length === 3 && SEL.every(id => titles.includes(w.eval(`S.tasks.get(${id}).title`))), '#936: the selected titles are listed ' + titles.join('|'));
  // priority -> all, highlighted, one undo step
  const h0 = w.eval('HIST.undo.length');
  click(w, val('priority')); await sleep(150);
  const hi = [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'High');
  check(!!hi, '#936: the priority menu'); click(w, hi);
  await until(async () => (await getT(SEL[2])).priority === 5);
  const pr = await Promise.all(SEL.map(getT));
  check(pr.every(t => t.priority === 5) && (await getT(OUT)).priority === 3, '#936: the priority applies to all selected (and only them) ' + pr.map(t => t.priority));
  await until(() => fld('priority')?.classList.contains('chg'));
  check(fld('priority')?.classList.contains('chg') && /changed/.test(fld('priority').textContent) && !fld('date').classList.contains('chg'), '#936: the changed field is highlighted ("changed"), the others not');
  check(/High/.test(val('priority').textContent), '#936: the panel shows the new common value');
  check(w.eval('HIST.undo.length') === h0 + 1, '#936: one history step for the whole change');
  await w.eval('histStep("undo")'); await sleep(400);
  const pu = await Promise.all(SEL.map(getT));
  check(pu.every(t => t.priority === 3), '#936: one undo restores all ' + pu.map(t => t.priority));
  // tags: half filled, add to all, remove from all
  const tag = g => [...d.querySelectorAll('#detail .metag')].find(b => b.dataset.tag === g);
  await until(() => tag('b'));
  check(tag('a')?.classList.contains('on') && tag('a').getAttribute('aria-pressed') === 'true', '#936: a tag all have is full');
  check(tag('b')?.classList.contains('half') && tag('b').getAttribute('aria-pressed') === 'mixed', '#936: a tag only some have is half filled');
  click(w, tag('b')); await until(async () => (await getT(SEL[0])).tags.includes('b'));
  let tg = await Promise.all(SEL.map(getT));
  check(tg.every(t => t.tags.includes('b') && t.tags.includes('a')), '#936: a click adds it to all (nothing replaced) ' + tg.map(t => t.tags.join('+')));
  await until(() => tag('b')?.classList.contains('on'));
  click(w, tag('b')); await until(async () => !(await getT(SEL[1])).tags.includes('b'));
  tg = await Promise.all(SEL.map(getT));
  check(tg.every(t => !t.tags.includes('b') && t.tags.includes('a')), '#936: the next click removes it from all ' + tg.map(t => t.tags.join('+')));
  const inp = d.querySelector('#me-tag');
  inp.value = 'urgent'; key(w, inp, 'Enter'); await until(async () => (await getT(SEL[2])).tags.includes('urgent'));
  check((await Promise.all(SEL.map(getT))).every(t => t.tags.includes('urgent')), '#936: a new tag typed in goes to all');
  // the date: +1 day keeps the differences
  const shift = d.querySelector('#detail [data-act="me-shift"][data-n="1"]');
  check(!!shift && d.querySelector('#detail [data-act="me-shift"][data-n="7"]') && d.querySelector('#detail [data-act="me-shift"][data-n="-1"]'), '#936: −1 day / +1 day / +1 week');
  const du0 = (await Promise.all(SEL.map(getT))).map(t => t.due), out0 = (await getT(OUT)).due;
  click(w, shift); await until(async () => (await getT(SEL[0])).due !== du0[0]);
  const du = (await Promise.all(SEL.map(getT))).map(t => t.due);
  check(du.join() === du0.map(x => { const z = new Date(x + 'T12:00:00'); z.setDate(z.getDate() + 1); return z.toISOString().slice(0, 10); }).join() && new Set(du).size === 3 && (await getT(OUT)).due === out0, '#936: +1 day: each task by itself ' + du0 + ' -> ' + du);
  check(fld('date')?.classList.contains('chg') && val('date').classList.contains('mixed'), '#936: the date still "Mixed", now marked as changed');
  // a fixed date for all
  click(w, val('date')); await sleep(150);
  const tom = [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Tomorrow');
  click(w, tom); await until(async () => (await getT(SEL[2])).due === day(1));
  check((await Promise.all(SEL.map(getT))).every(t => t.due === day(1)), '#936: a fixed date for all');
  await until(() => !val('date').classList.contains('mixed'));
  check(/Tomorrow/.test(val('date').textContent), '#936: then shown as common: ' + val('date').textContent);
  // the keyboard: d opens the date of the panel, Esc ends the selection
  w.eval('closePop()'); d.activeElement?.blur?.();
  key(w, d.body, 'd'); await sleep(150);
  check(!d.querySelector('#pop').classList.contains('hidden') && [...d.querySelectorAll('#pop .menu-list button')].some(b => b.textContent.trim() === 'Pick a date…'), '#936: "d" opens the date menu of the panel');
  w.eval('closePop()');
  // removing one from the panel, a title opens one task alone
  click(w, d.querySelector(`#detail [data-act="me-drop"][data-id="${SEL[2]}"]`)); await sleep(150);
  check(multi() === want([SEL[0], SEL[1]]), '#936: × removes one from the selection');
  // the selection changed: the "changed" markers are gone
  check(!d.querySelector('#detail .mef.chg'), '#936: a new selection starts without markers');
  click(w, d.querySelector(`#detail .metl[data-id="${SEL[1]}"]`)); await sleep(250);
  check(w.eval('S.sel') === SEL[1] && w.eval('S.multi.size') === 0 && !d.querySelector('#detail.multi') && d.querySelector('#d-title')?.value === w.eval(`S.tasks.get(${SEL[1]}).title`), '#936: a title opens that task alone, the selection ends');
  // a plain click on a row ends a selection
  click(w, ttl(SEL[0]), {ctrlKey: true}); await sleep(150);
  check(w.eval('S.multi.size') === 2 && d.querySelector('#detail.multi'), '#936: Ctrl-click with a task open: both selected');
  click(w, ttl(OUT)); await sleep(250);
  check(w.eval('S.sel') === OUT && w.eval('S.multi.size') === 0 && !d.querySelector('#view .trow.msel'), '#936: a plain click opens the task and ends the selection');
  // Shift+J (keyboard) still selects
  w.eval('closeDetail()'); await sleep(100);
  w.eval(`kfocus(${O[0]})`); key(w, d.body, 'J', {shiftKey: true}); await sleep(150);
  check(w.eval('S.multi.size') === 2 && d.querySelector('#detail.multi'), '#936: Shift+J selects two, the panel follows ' + JSON.stringify([w.eval('S.multi.size'), w.eval('S.kf'), !d.querySelector('#pop').classList.contains('hidden'), !!d.querySelector('.modal, .qadd.sheet, .tsheet, .lightbox'), d.activeElement?.tagName + '.' + d.activeElement?.className]));
  key(w, d.body, 'Escape'); await sleep(150);
  check(w.eval('S.multi.size') === 0 && !d.querySelector('#detail.multi') && d.querySelector('#detail').classList.contains('hidden'), '#936: Esc clears the selection and closes the panel');

  // permissions: a view-only list and a participant role
  w.eval(`S.multi = new Set([${T[0]}, ${V1}, ${V2}]); renderMultiBar()`); await sleep(200);
  const lk = fld('priority');
  check(lk?.classList.contains('lock') && val('priority').disabled && /No permission for 2 tasks/.test(lk.textContent), '#936: view-only tasks lock the field: ' + lk?.textContent.replace(/\s+/g, ' ').trim());
  check(d.querySelector('#detail .metags.lock #me-tag') === null && d.querySelector('#detail .metags .melock'), '#936: tags locked too');
  w.eval(`S.multi = new Set([${T[0]}, ${P1}]); renderMultiBar()`); await sleep(200);
  check(fld('assignee')?.classList.contains('lock') && /No permission for 1 task/.test(fld('assignee').textContent), '#936: a participant may not change the assignee: locked');
  check(fld('list')?.classList.contains('lock'), '#936: ... nor move to another list');
  check(!fld('date')?.classList.contains('lock') && !val('date').disabled, '#936: ... but the date is open');
  w.eval('S.multi.clear(); S.multiMode = false; render()'); await sleep(100);
  check(!d.querySelector('#detail.multi'), 'cleared');

  // ================= #932 the sidebar's width (jsdom: keyboard + storage)
  w.eval('placeGrips()');
  const g = d.querySelector('#pgrip-side');
  check(g && g.getAttribute('role') === 'separator' && /sidebar/i.test(g.getAttribute('aria-label') || ''), '#932: a grip "Width of the sidebar"');
  key(w, g, 'ArrowRight'); await sleep(50);
  check(+JSON.parse(w.__store['tasks.pw.side'] || '0') === 16, '#932: → = 1 rem wider, stored per device ' + w.__store['tasks.pw.side']);
  check(d.documentElement.style.getPropertyValue('--sideW') === '16rem', '#932: --sideW follows');
  key(w, g, 'ArrowLeft', {shiftKey: true}); await sleep(50);
  check(+JSON.parse(w.__store['tasks.pw.side'] || '0') === 12, '#932: Shift+← = 4 rem narrower');
  key(w, g, 'Home'); key(w, g, 'Enter'); await sleep(50);
  check(!w.__store['tasks.pw.side'] && d.documentElement.style.getPropertyValue('--sideW') === '15rem', '#932: Enter = the standard width (not stored)');
  w.close();

  // ================= #936 phone (jsdom): select mode, taps toggle, "Edit" opens the sheet
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T[0]}"]`));
  w.eval(`S.multiMode = true; S.multi.add(${T[0]}); S.multiLast = ${T[0]}; render()`); await sleep(150);
  click(w, d.querySelector(`#view .trow[data-id="${T[2]}"] .ttl`)); await sleep(150);
  check(w.eval('S.multi.size') === 2 && !w.eval('S.sel'), '#936 phone: a tap in select mode adds the task');
  check(!d.querySelector('#detail.multi'), '#936 phone: no panel over the list until asked');
  const acts = [...d.querySelectorAll('#mbar > *')].map(x => x.dataset.act || x.className.split(' ')[0]);
  check(JSON.stringify(acts) === JSON.stringify(['mcount', 'me-sheet', 'mb-done', 'mb-del', 'mb-close']), '#936 phone: the bar: count, Edit, Complete, Delete, Clear ' + acts.join('|'));
  click(w, d.querySelector('#mbar [data-act="me-sheet"]')); await sleep(200);
  check(d.querySelector('#detail.multi') && !d.querySelector('#detail').classList.contains('hidden') && /2 tasks/.test(d.querySelector('#detail .mecount').textContent), '#936 phone: "Edit" opens the panel as a sheet');
  click(w, d.querySelector('#detail [data-act="me-sheet-close"]')); await sleep(300);
  check(!d.querySelector('#detail.multi') && w.eval('S.multi.size') === 2, '#936 phone: "Done" closes the sheet, the selection stays');
  click(w, d.querySelector(`#view .trow[data-id="${T[2]}"] .ttl`)); await sleep(150);
  check(w.eval('S.multi.size') === 1, '#936 phone: another tap takes it out again');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, theme = 'light', ls = {}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); ${Object.entries(ls).map(([k, v]) => `localStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(v)});`).join(' ')} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const OVER = `(() => document.documentElement.scrollWidth - innerWidth)()`;
  const center = (ev, sel) => ev(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return {x: Math.round(r.left + Math.min(40, r.width / 2)), y: Math.round(r.top + r.height / 2)}; })()`);
  const keyClick = async ({cmd, ctx}, x, y, k) => cmd('input.performActions', {context: ctx, actions: [
    {type: 'key', id: 'k1', actions: [{type: 'keyDown', value: k}, {type: 'pause', duration: 0}, {type: 'pause', duration: 0}, {type: 'keyUp', value: k}]},
    {type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x, y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}, {type: 'pause', duration: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
  // the layout with the task panel open: sidebar | list | panel side by side, nothing overlaps, the list keeps >= 420 px
  const LAYOUT = `(() => { const s = document.querySelector('#side').getBoundingClientRect(), m = document.querySelector('#main').getBoundingClientRect(), p = document.querySelector('#detail').getBoundingClientRect();
    return {s: Math.round(s.right), ml: Math.round(m.left), mr: Math.round(m.right), mw: Math.round(m.width), pl: Math.round(p.left), rail: document.querySelector('#app').classList.contains('side-rail'), o: document.documentElement.scrollWidth - innerWidth}; })()`;
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    // a real Shift-click range from the open task
    const FO = await ev(`[...document.querySelectorAll('#view .trow')].map(x => +x.dataset.id)`);
    await ev(`(() => { document.querySelector('#view .trow[data-id="${FO[0]}"] .ttl').click(); return 1; })()`); await sleep(500);
    const p = await center(ev, `#view .trow[data-id="${FO[3]}"] .ttl`);
    await keyClick(o, p.x, p.y, ''); await sleep(600);
    const sel = await ev(`[...S.multi].length`);
    check(sel === 4, `${tag}: a real Shift-click selects the range (4) ` + sel);
    check(await ev(`!!document.querySelector('#detail.multi') && (window.getSelection() + '').trim() === ''`), `${tag}: the multi panel, no text selected by the Shift-click`);
    const q = await center(ev, `#view .trow[data-id="${FO[1]}"] .ttl`);
    await keyClick(o, q.x, q.y, ''); await sleep(500);
    check(await ev(`[...S.multi].length`) === 3, `${tag}: a real Ctrl-click takes one out`);
    check((await ev(OVER)) <= 0, `${tag}: nothing sideways`);
    const lay = await ev(LAYOUT);
    check(lay.pl >= lay.mr - 1 && lay.mw >= 420, `${tag}: the multi panel sits beside the list ` + JSON.stringify(lay));
    const mb = await ev(`(() => { const b = document.querySelector('#mbar').getBoundingClientRect(), p = document.querySelector('#detail').getBoundingClientRect(); return {b: Math.round(b.right), p: Math.round(p.left), n: document.querySelectorAll('#mbar > *').length}; })()`);
    check(mb.b <= mb.p && mb.n === 4, `${tag}: the bar (4 elements) beside the panel ` + JSON.stringify(mb));
    // one changed field for the screenshot
    await ev(`(() => { document.querySelector('#detail [data-act="me-shift"][data-n="7"]').click(); return 1; })()`); await sleep(1200);
    check(await ev(`!!document.querySelector('#detail .mef.chg[data-k="date"]')`), `${tag}: the shifted date is marked`);
    const small = await ev(`(() => [...document.querySelectorAll('#detail .mev, #detail .metag')].filter(e => e.getBoundingClientRect().height < 31).length)()`);
    check(small === 0, `${tag}: the panel's controls are big enough to hit ` + small);
    await shot(`p2260-${th}-1440-multi.png`);
    if (th === 'light') {
      // #932: drag the sidebar wider (the list keeps its room, the grip stays on the edge)
      await ev(`(() => { S.multi.clear(); render(); return 1; })()`); await sleep(400);
      await ev(`(() => { document.querySelector('#view .trow[data-id="${T[0]}"] .ttl').click(); return 1; })()`); await sleep(600);
      const g = await ev(`(() => { placeGrips(); const g = document.querySelector('#pgrip-side'), r = g.getBoundingClientRect(), s = document.querySelector('#side').getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + 200), s: Math.round(s.width), h: g.hidden}; })()`);
      check(!g.h && g.s === 240, `${tag}: the sidebar grip, 240 px standard ` + JSON.stringify(g));
      await o.drag(g.x, g.y, 96, 0); await sleep(500);
      const a = await ev(`(() => ({s: Math.round(document.querySelector('#side').getBoundingClientRect().width), st: localStorage.getItem('tasks.pw.side'), g: Math.round(document.querySelector('#pgrip-side').getBoundingClientRect().left + 5 - document.querySelector('#side').getBoundingClientRect().right)}))()`);
      check(Math.abs(a.s - 336) <= 8 && Math.abs(+a.st - 21) <= 0.5 && Math.abs(a.g) <= 1, `${tag}: dragged 96 px wider, stored, the grip follows ` + JSON.stringify(a));
      const lay2 = await ev(LAYOUT);
      check(!lay2.rail && lay2.s <= lay2.ml && lay2.pl >= lay2.mr - 1 && lay2.mw >= 420 && lay2.o <= 0, `${tag}: wider sidebar, list and panel beside it ` + JSON.stringify(lay2));
      await shot('p2260-light-1440-sidebar.png');
      await o.drag(a.s + 0, g.y, 900, 0); await sleep(500);
      const lay3 = await ev(LAYOUT);
      check(!lay3.rail && lay3.mw >= 418, `${tag}: dragged far: the list still keeps 420 px ` + JSON.stringify(lay3));
      await ev(`(() => { document.querySelector('#pgrip-side').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); return 1; })()`); await sleep(300);
      const db = await ev(`[Math.round(document.querySelector('#side').getBoundingClientRect().width), localStorage.getItem('tasks.pw.side')]`);
      check(db[0] === 240 && db[1] == null, `${tag}: double-click = the standard width ` + JSON.stringify(db));
      for (const [vw, vh] of [[1280, 800], [1920, 1080]]) {
        await ev(`(() => { localStorage.setItem('tasks.pw.side', '19'); panelVars(); fitLayout(); return 1; })()`);
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}}); await sleep(700);
        const ly = await ev(LAYOUT);
        check(!ly.rail && ly.s <= ly.ml && ly.pl >= ly.mr - 1 && ly.mw >= 420 && ly.o <= 0, `${vw}: a wider sidebar (19 rem) + the task panel: nothing overlaps, the list keeps its room ` + JSON.stringify(ly));
      }
      await ev(`(() => { localStorage.removeItem('tasks.pw.side'); panelVars(); fitLayout(); return 1; })()`);
    }
  }, false);

  // 390 phone (touch): the sheet; the keyboard (a fake visual viewport) over the quick sheet, the comment box, the team chat
  // a fake visual viewport: the keyboard takes h px at the bottom, iOS may have scrolled the visual viewport down by top px
  // (Firefox defines visualViewport on the window itself: it is replaced, never deleted). Measured after the transitions.
  const FAKEVV = (h, top) => `Object.defineProperty(window, 'visualViewport', {configurable: true, value: {height: innerHeight - ${h}, offsetTop: ${top}, width: innerWidth, offsetLeft: 0, scale: 1, addEventListener() {}, removeEventListener() {}}});`;
  const KB = (sel, h, top = 0) => `(async () => { const el = document.querySelector(${JSON.stringify(sel)}); if (!el) return null; ${FAKEVV(0, 0)} vvSync(); el.focus();
    ${FAKEVV(h, top)} vvSync(); await new Promise(r => setTimeout(r, 250));
    const r = el.getBoundingClientRect(), vb = ${top} + innerHeight - ${h};
    return {top: Math.round(r.top), bottom: Math.round(r.bottom), vt: ${top}, vb: Math.round(vb), pin: !!el.closest('.vvpin'), act: document.activeElement === el}; })()`;
  const KBOFF = `(async () => { document.activeElement?.blur?.(); ${FAKEVV(0, 0)} vvSync(); await new Promise(r => setTimeout(r, 450)); return 1; })()`;
  const inside = k => k && k.top >= k.vt - 1 && k.bottom <= k.vb + 1;
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { S.multiMode = true; S.multi = new Set([${T[0]}, ${T[2]}, ${T[4]}]); render(); return 1; })()`); await sleep(300);
    await ev(`(() => { document.querySelector('#mbar [data-act="me-sheet"]').click(); return 1; })()`); await sleep(700);
    const sh = await ev(`(() => { const r = document.querySelector('#detail').getBoundingClientRect(); return {t: Math.round(r.top), b: Math.round(r.bottom), w: Math.round(r.width), o: document.documentElement.scrollWidth - innerWidth}; })()`);
    check(sh.t > 100 && sh.b <= 845 && sh.w === 390 && sh.o <= 0, `${tag}: the multi panel is a bottom sheet (the list stays visible above) ` + JSON.stringify(sh));
    const small = await ev(`(() => [...document.querySelectorAll('#detail .mev, #detail .metag, #detail .metl, #mbar button')].filter(e => { const r = e.getBoundingClientRect(); return r.height && r.height < 43.5; }).map(e => e.className).slice(0, 5))()`);
    check(!small.length, `${tag}: 44 px targets in the sheet ` + small.join('|'));
    await shot('p2260-light-390-sheet.png');
    await ev(`(() => { S.multi.clear(); S.multiMode = false; render(); return 1; })()`); await sleep(400);
    // the quick sheet above the keyboard (also when iOS scrolled the visual viewport)
    await ev(`(() => { openQuickSheet(''); return 1; })()`); await sleep(500);
    let k = await ev(KB('#qsheet', 330));
    check(inside(k), `${tag}: the quick add stays above the keyboard ` + JSON.stringify(k));
    k = await ev(KB('#qsheet', 330, 120));
    check(inside(k), `${tag}: ... also with the visual viewport scrolled ` + JSON.stringify(k));
    await shot('p2260-light-390-quickadd-keyboard.png');
    await ev(KBOFF); await ev('closePop(); 1'); await sleep(300);
    // the comment box of the task panel
    await ev(`(() => { openDetail(${T[0]}); return 1; })()`); await sleep(900);
    k = await ev(KB('#c-input', 330));
    check(inside(k), `${tag}: the comment box stays above the keyboard ` + JSON.stringify(k));
    k = await ev(KB('#c-input', 330, 140));
    check(inside(k), `${tag}: ... also scrolled ` + JSON.stringify(k));
    await ev(KBOFF); await ev('closeDetail(); 1'); await sleep(400);
    // the team chat's composer
    await ev(`(() => { dmOpen(${BOB}, 'Bob Baker'); return 1; })()`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('#tc-in')`)); i++) await sleep(300);
    k = await ev(KB('#tc-in', 330));
    check(inside(k), `${tag}: the team chat's input stays above the keyboard ` + JSON.stringify(k));
    k = await ev(KB('#tc-in', 330, 100));
    check(inside(k), `${tag}: ... also scrolled ` + JSON.stringify(k));
    await shot('p2260-light-390-teamchat-keyboard.png');
    await ev(KBOFF); await sleep(400);
    check(!(await ev(`!!document.querySelector('.vvpin, .vvph')`)), `${tag}: nothing stays pinned once the keyboard is gone`);
    // the search field
    await o.nav(B + '#search'); await ready(ev);
    k = await ev(KB('#searchq', 330));
    check(inside(k), `${tag}: the search field stays visible ` + JSON.stringify(k));
    await ev(KBOFF);
  }, true);
  // a tablet (docked quick add at the bottom of the list): pinned above the keyboard, then let go
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '820 tablet';
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 820, height: 1180}});
    await o.nav(B + '#l/' + L); await ready(ev);
    check(await ev(`!!document.querySelector('#view .qdock #qinput') && !!document.querySelector('#view .qdock').offsetParent`), `${tag}: the docked quick add`);
    let k = await ev(KB('#view .qdock #qinput', 420));
    check(inside(k) && k.pin && k.act, `${tag}: the docked quick add is pinned above the keyboard ` + JSON.stringify(k));
    k = await ev(KB('#view .qdock #qinput', 420, 150));
    check(inside(k), `${tag}: ... and follows a scrolled visual viewport ` + JSON.stringify(k));
    await shot('p2260-light-820-quickadd-keyboard.png');
    await ev(KBOFF); await sleep(500);
    check(await ev(`!document.querySelector('.vvpin, .vvph') && !!document.querySelector('#view .qdock #qinput')`), `${tag}: let go when the keyboard is gone`);
  }, true);

  console.log(`p2260_ui: ${ok} ok, ${F.length} failed`);
  if (F.length) { console.log(F.join('\n')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
