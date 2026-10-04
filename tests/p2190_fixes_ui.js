// 2.19.0 UI tests of the fixes reported during the release, own container (start.sh, isolated test database).
// - #667 drop zones of sections: an empty section's "Drop tasks here" takes a task (jsdom + a real finger in Firefox:
//   the zone used to be hidden before the drop was read), the new "+ New section" zone at the end of a list (name it,
//   the task lands in it, Undo puts it back and removes the section), "Move to section…" offers "New section…" too
// - #668 notifications: the app icon's number (Badging API) = unread News + chat; opening the app closes notifications
//   that need nothing any more, keeps unread / due ones; "Mark all as read" closes all; the service worker closes "*"
//   and sets the badge from a push
// - #669 the docked "Add task" bar on an unfolded Fold / tablet (600-899 px wide): the on-screen keyboard (it shrinks
//   the height below 600 px) no longer flips the layout and takes the focus away, and the list stays put while typing,
//   in portrait and landscape (Firefox, touch, keyboard-sized viewport, real keys)
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2190_fixes_ui', check, shots: 'P2190X_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const ROOT = path.join(__dirname, '..');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const dnd = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = {setData() {}, getData: () => '', effectAllowed: '', dropEffect: ''}; e.clientY = 10; el.dispatchEvent(e); return e; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const L = (await call('POST', '/api/lists', {name: 'Office'})).id;
  const A = (await call('POST', '/api/sections', {name: 'Doing', list_id: L})).id, C = (await call('POST', '/api/sections', {name: 'Later', list_id: L})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Invoice', list_id: L, section_id: A})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Call the bank', list_id: L, section_id: A})).id;
  const secsOf = async () => (await call('GET', '/api/state')).sections.filter(s => s.list_id === L);

  // ================= #667 jsdom: "+ New section" at the end of the list, Undo, the menu
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await until(() => d.querySelector('#view .trow'));
  const nz = () => d.querySelector('#view .sdrop.snew[data-newsec]');
  check(nz() && /New section/.test(nz().textContent) && d.querySelector(`#view .sdrop[data-section="${C}"]`), 'drop zones: the empty section and "+ New section" at the end');
  w.prompt = () => 'Phase 2';
  dnd(w, d.querySelector(`#view .trow[data-id="${T2}"]`), 'dragstart'); await sleep(20);
  check(d.body.classList.contains('tdrag'), 'while dragging the zones show (set right after dragstart)');
  check(dnd(w, nz(), 'dragover').defaultPrevented && nz().classList.contains('drop'), '"+ New section" takes a task, highlighted while over it');
  dnd(w, nz(), 'drop');
  check(await until(async () => { const s = (await secsOf()).find(x => x.name === 'Phase 2'); return s && (await call('GET', `/api/tasks/${T2}`)).section_id === s.id; }), 'dropped: section "Phase 2" made, the task in it');
  check(await until(() => /New section “Phase 2”/.test(d.querySelector('#toast')?.textContent || '') && d.querySelector('#toast button')), 'a toast with Undo');
  d.querySelector('#toast button').click();
  check(await until(async () => !(await secsOf()).some(x => x.name === 'Phase 2') && (await call('GET', `/api/tasks/${T2}`)).section_id === A), 'Undo: back in "Doing", the section removed');
  // the empty section's zone (jsdom)
  await until(() => d.querySelector(`#view .trow[data-id="${T2}"]`));
  dnd(w, d.querySelector(`#view .trow[data-id="${T2}"]`), 'dragstart');
  const ez = d.querySelector(`#view .sdrop[data-section="${C}"]`);
  check(dnd(w, ez, 'dragover').defaultPrevented, 'the empty section\'s zone takes a task');
  dnd(w, ez, 'drop');
  check(await until(async () => (await call('GET', `/api/tasks/${T2}`)).section_id === C), 'dropped into the empty section');
  // a plain drop on another task still reorders (the new zone's check once threw over a row)
  { const s0 = (await call('GET', `/api/tasks/${T1}`)).sort, rows = [...d.querySelectorAll('#view .trow')];
    await w.eval('load().then(() => render())'); await sleep(200);
    const tgt = d.querySelector(`#view .trow[data-id="${T2}"]`);
    dnd(w, d.querySelector(`#view .trow[data-id="${T1}"]`), 'dragstart'); await sleep(20); dnd(w, tgt, 'dragover'); dnd(w, tgt, 'drop'); dnd(w, tgt, 'dragend');
    check(await until(async () => { const t = await call('GET', `/api/tasks/${T1}`); return t.section_id === C; }) && rows.length, 'a task dropped on a task of another section: moved there (no error)'); void s0; }
  // keyboard: "Move to section…" -> "New section…"
  w.eval(`sectionPicker(document.querySelector('#view .trow[data-id="${T1}"]'), ${T1})`); await sleep(100);
  const items = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim());
  check(items.some(x => /New section…/.test(x)) && items.some(x => /Later/.test(x)), '"Move to section…" offers "New section…" ' + items.join('|'));
  w.prompt = () => 'Next week';
  [...d.querySelectorAll('#pop [role="menuitem"]')].find(x => /New section…/.test(x.textContent)).click();
  check(await until(async () => { const s = (await secsOf()).find(x => x.name === 'Next week'); return s && (await call('GET', `/api/tasks/${T1}`)).section_id === s.id; }), 'menu: the new section with the task in it');
  // a list without sections: the menu still offers it
  const L2 = (await call('POST', '/api/lists', {name: 'Plain'})).id, T3 = (await call('POST', '/api/tasks', {title: 'Loose', list_id: L2})).id;
  await w.eval('load()');
  w.eval(`closePop(); sectionPicker(document.body, ${T3})`); await sleep(100);
  check([...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim()).join('|') === 'New section…', 'a list without sections: only "New section…"');
  w.eval('closePop()');

  // ================= #668 jsdom: the app badge and the notification sweep
  const shown = [];
  const reg = {getNotifications: async () => shown.filter(n => !n.closed)};
  Object.defineProperty(w.navigator, 'serviceWorker', {configurable: true, value: {getRegistration: async () => reg, register: () => Promise.resolve(), addEventListener() {}, controller: null}});
  const badge = [];
  w.navigator.setAppBadge = async n => { badge.push(n); }; w.navigator.clearAppBadge = async () => { badge.push(0); };
  const DUE = (await call('POST', '/api/tasks', {title: 'Pay rent', list_id: L, due: new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10)})).id;
  const LATER = (await call('POST', '/api/tasks', {title: 'Some day', list_id: L, due: '2099-01-01'})).id;
  await call('POST', `/api/tasks/${T3}/complete`, {});
  await w.eval('load()');
  for (const tag of [`t-${T3}`, `t-${DUE}`, `t-${LATER}`, 't-999999', 'team-5', 'agents-3', 'digest', '']) shown.push({tag, closed: false, close() { this.closed = true; }});
  w.eval('S.tc.rooms = [{id: 5, unread: 0}]; S.nf.items = []');
  const n1 = await w.eval('wpSweep()');
  const left = shown.filter(x => !x.closed).map(x => x.tag);
  check(JSON.stringify(left) === JSON.stringify([`t-${DUE}`]) && n1 === 7, 'opening the app: only the due reminder stays (done, gone, read chat, agents, digest closed) ' + left.join(','));
  shown.forEach(x => { x.closed = false; });
  w.eval(`S.tc.rooms = [{id: 5, unread: 2}]; S.nf.items = [{task_id: ${LATER}, read: false, ids: [1]}]`);
  await w.eval('wpSweep()');
  check(['team-5', `t-${LATER}`, `t-${DUE}`].every(t => !shown.find(x => x.tag === t).closed), 'unread chat and unread News stay');
  await w.eval('wpSweep(null, true)');
  check(shown.every(x => x.closed), '"Mark all as read": every notification closes');
  w.eval('S.news = {unread: 3, sig: "x"}; S.team = {enabled: true, unread: 2}; badgeN = -1; badgeSync()');
  const exp = w.eval('(collab() ? 3 : 0) + (teamOn() ? 2 : 0)');
  check(badge.at(-1) === exp, `the app badge: unread News + chat (${badge.at(-1)} = ${exp})`);
  w.eval('S.news = {unread: 0, sig: "y"}; S.team = {enabled: true, unread: 0}; badgeSync()');
  check(badge.at(-1) === 0, 'nothing unread: the badge is cleared');
  w.close();
  // the service worker: "*" closes all, a push sets the badge
  {
    const src = fs.readFileSync(path.join(ROOT, 'static', 'sw.js'), 'utf8');
    const notes = [{tag: 't-1', closed: false, close() { this.closed = true; }}, {tag: 'team-2', closed: false, close() { this.closed = true; }}];
    const ls = {}, set = [];
    const self = {addEventListener: (k, f) => { ls[k] = f; }, registration: {getNotifications: async () => notes.filter(n => !n.closed), showNotification: async () => {}},
      navigator: {setAppBadge: async n => set.push(n), clearAppBadge: async () => set.push(0)}, location: {origin: 'https://kalmido.example'}, clients: {matchAll: async () => []}, skipWaiting() {}};
    const ctx = vm.createContext({self, caches: {open: async () => ({addAll: async () => {}}), keys: async () => [], match: async () => null}, fetch: async () => ({}), URL, console, setTimeout, Response: function () {}});
    vm.runInContext(src, ctx);
    let wait; ls.push({data: {json: () => ({type: 'dismiss', tags: ['*'], badge: 0})}, waitUntil: p => { wait = p; }}); await wait;
    check(notes.every(n => n.closed) && set.at(-1) === 0, 'service worker: a dismiss push with "*" closes every notification, badge 0');
    ls.push({data: {json: () => ({title: 'x', tag: 't-9', badge: 4})}, waitUntil: p => { wait = p; }}); await wait;
    check(set.at(-1) === 4, 'service worker: a push sets the badge to its number');
  }

  // ================= #667 Firefox: a real finger drops into the empty section and onto "+ New section"
  await call('PATCH', `/api/tasks/${T2}`, {section_id: A});
  const tapDrag = async ({cmd, ctx, ev}, from, to) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'}, actions: [
      {type: 'pointerMove', x: Math.round(from.x), y: Math.round(from.y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 700},
      {type: 'pointerMove', x: Math.round(to.x), y: Math.round((from.y + to.y) / 2), duration: 200}, {type: 'pointerMove', x: Math.round(to.x), y: Math.round(to.y), duration: 200},
      {type: 'pause', duration: 200}]}]});
    if (process.env.DBG) console.log('during', await ev(`JSON.stringify({drop: [...document.querySelectorAll('.drop,.dropbefore,.dropafter')].map(e => e.className.slice(0, 40)), tdrag: document.body.classList.contains('tdrag'), st: document.getElementById('view').scrollTop, at: document.elementFromPoint(${Math.round(to.x)}, ${Math.round(to.y)})?.className})`));
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  const ffLogin = async ({ev, nav}) => { await nav(B + 'static/icon.svg'); return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`); };
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 1200}});  // the whole list fits: no edge scrolling
    await ffLogin(o);
    await nav(B + '#l/' + L); await sleep(2500);
    const pos = sel => ev(`(() => { document.body.classList.add('tdrag'); const e = document.querySelector('${sel}'); const b = e.getBoundingClientRect(); document.body.classList.remove('tdrag'); return {x: b.left + Math.min(60, b.width / 2), y: b.top + b.height / 2}; })()`);
    const to1 = await pos(`#view .sdrop[data-section="${C}"]`);
    const from = await ev(`(() => { const b = document.querySelector('#view .trow[data-id="${T2}"] .ttl').getBoundingClientRect(); return {x: b.left + 30, y: b.top + b.height / 2}; })()`);
    await tapDrag(o, from, to1);
    check(await until(async () => (await call('GET', `/api/tasks/${T2}`)).section_id === C), 'touch: dropped on "Drop tasks here" of an empty section: moved (#667)');
    await sleep(2500);
    await ev(`(() => { document.querySelector('#toast')?.classList.add('hidden'); return 1; })()`);  // the Undo toast sits right over the zone
    await ev(`(() => { document.body.classList.add('tdrag'); const v = document.getElementById('view'); v.scrollTop = v.scrollHeight; document.body.classList.remove('tdrag'); return 1; })()`); await sleep(300);
    const from2 = await ev(`(() => { const e = document.querySelector('#view .trow[data-id="${T2}"] .ttl'); const b = e.getBoundingClientRect(); return {x: b.left + 30, y: b.top + b.height / 2}; })()`);
    const to2 = await pos('#view .sdrop.snew');
    await tapDrag(o, from2, to2);
    await sleep(600);
    // the app's own prompt dialog: the name is prefilled ("New section"), typed over, saved
    const pre = await ev(`document.querySelector('#cdlg-in')?.value || ''`);
    check(pre === 'New section', 'touch: "+ New section" asks for the name, prefilled ' + JSON.stringify(pre));
    await ev(`(() => { const i = document.querySelector('#cdlg-in'); if (i) { i.value = 'By touch'; i.closest('form').requestSubmit(); } return 1; })()`);
    check(await until(async () => { const s = (await secsOf()).find(x => x.name === 'By touch'); return s && (await call('GET', `/api/tasks/${T2}`)).section_id === s.id; }), 'touch: the new section holds the task');
  }, true);

  // ================= #669 Firefox: the docked "Add task" bar with the keyboard up (unfolded Fold / tablet)
  const L3 = (await call('POST', '/api/lists', {name: 'Long'})).id;
  for (let i = 0; i < 40; i++) await call('POST', '/api/tasks', {title: `Task number ${i + 1} with some words`, list_id: L3});
  for (const [vw, vh, what] of [[690, 829, 'Fold unfolded portrait'], [829, 690, 'Fold unfolded landscape'], [904, 1000, 'Fold 904'], [768, 1024, 'tablet portrait']]) await firefox(async o => {
    const {cmd, ev, ctx, nav} = o, tag = `${what} ${vw}x${vh}`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await ffLogin(o);
    await nav(B + '#l/' + L3); await sleep(2500);
    await ev(`(() => { document.getElementById('view').scrollTop = 300; return 1; })()`); await sleep(200);
    const q = await ev(`(() => { const q = document.querySelector('#qinput'); if (!q || !q.offsetParent) return null; const r = q.getBoundingClientRect(); return {x: r.left + 40, y: r.top + r.height / 2}; })()`);
    check(q, `${tag}: the docked "Add task" bar is there`);
    if (!q) return;
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(q.x), y: Math.round(q.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
    await sleep(300);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: Math.round(vh * 0.55)}}); await sleep(700);  // the keyboard: resizes-content
    const st0 = await ev(`({a: document.activeElement?.id, s: document.getElementById('view').scrollTop, dock: !!document.querySelector('#qinput')?.offsetParent})`);
    check(st0.a === 'qinput' && st0.dock, `${tag}: keyboard up: the bar stays, the focus (and so the keyboard) too ${JSON.stringify(st0)}`);
    for (const ch of 'Dentist 3p') {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: ch}, {type: 'keyUp', value: ch}]}]});
      await ev(`(() => { document.getElementById('view').scrollTop += 30; return 1; })()`);  // what Chrome's caret reveal does to a sticky field
      await sleep(120);
    }
    await sleep(300);
    const st1 = await ev(`({a: document.activeElement?.id, s: document.getElementById('view').scrollTop, v: document.querySelector('#qinput').value})`);
    check(st1.a === 'qinput' && Math.abs(st1.s - st0.s) <= 1 && st1.v === 'Dentist 3p', `${tag}: ten keys: the list did not move, still typing ${JSON.stringify({st0, st1})}`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}}); await sleep(400);
    check(await ev(`!!document.querySelector('#qinput')?.offsetParent && document.querySelector('#qinput').value === 'Dentist 3p'`), `${tag}: keyboard down: the bar and the text are still there`);
  }, true);

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
