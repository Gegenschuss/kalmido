// 2.0.8 UI tests (jsdom + the service worker in a Node vm), fresh DB:
// #319 sort "Created" (newest first, picked again: oldest first) per view incl. "All", the creation date on the rows, German
// #320 the agent chat: a sent message closes the keyboard on a phone (blur), the desktop keeps the focus
// #321 Settings > AI colleague: every list I manage in one table, "Agent sees it" shares / unshares, "Tidy up" off/suggest/auto
// #323 phones: a <select> opens an app-style bottom sheet (label, icons, check, search above 10 options, keys); desktop and
//      selects inside a popover / data-native stay native
// #325 the notification badge is a 96 x 96 grey + alpha PNG (white silhouette)
// #331 push buttons: the service worker shows Reply + Done and opens /#reply/<id>; the app opens the task with the
//      comment box focused
const fs = require('fs'), path = require('path'), vm = require('vm');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const mdown = (w, el) => el && el.dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el && el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,agents';

// ------------------------------------------------------------------ service worker: Reply + Done
const SW = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
function swEnv() {
  const L = {}, shown = [], opened = [];
  const self = {location: {origin: 'https://kalmido.example'}, addEventListener: (t, f) => { L[t] = f; }, skipWaiting() {},
    registration: {showNotification: async (t, o) => { shown.push([t, o]); }, getNotifications: async () => [], pushManager: {}},
    clients: {matchAll: async () => [], openWindow: async u => { opened.push(u); return {}; }, claim() {}}};
  const ctx = {self, caches: {open: async () => ({addAll: async () => {}, put() {}}), keys: async () => [], match: async () => null},
    fetch: async () => new Response('{}'), URL, Response, atob, Uint8Array, JSON, Promise, console, setTimeout};
  vm.createContext(ctx); vm.runInContext(SW, ctx);
  return {L, shown, opened};
}
async function swTests() {
  check(/const CACHE = 'tasks-shell-v((59|6[0-9])|7[0-2])'/.test(SW), 'service worker cache v59 (2.1.0: v60, 2.1.1: v61, 2.1.2: v62, 2.2.0: v63, 2.2.1: v64, 2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72)');
  const S = swEnv();
  const e = {data: {json: () => ({title: 'Task X', body: 'Bob commented: look', tag: 't-7', url: '/#t/7', task: 7,
    actions: [{action: 'reply', title: 'Reply', url: '/#reply/7'}, {action: 'done', title: 'Done', url: '/#done/7'}]})}, waitUntil(p) { this.p = p; }};
  S.L.push(e); await e.p;
  const o = S.shown[0]?.[1] || {};
  check(JSON.stringify((o.actions || []).map(a => a.action)) === '["reply","done"]' && o.data.actions.reply === '/#reply/7' && o.data.task === 7, 'SW: Reply + Done on a comment push');
  check(o.badge === '/static/badge-96.png', 'SW: the badge file name stays');
  const n = {data: o.data, close() {}};
  const c = {action: 'reply', notification: n, waitUntil(p) { this.p = p; }};
  S.L.notificationclick(c); await c.p;
  check(S.opened[0] === '/#reply/7', 'SW: Reply opens /#reply/<id>: ' + S.opened[0]);
}

(async () => {
  await swTests();
  // #325 the badge: 96 x 96, grey + alpha (colour type 4), mostly transparent (a silhouette, no plate)
  const png = fs.readFileSync(path.join(__dirname, '..', 'static', 'badge-96.png'));
  check(png.readUInt32BE(16) === 96 && png.readUInt32BE(20) === 96 && png[25] === 4, 'badge: 96 x 96 grey + alpha PNG');

  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const WEB = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const HOME = (await call('POST', '/api/lists', {name: '🏠 Home'})).id;
  const BOBS = (await call('POST', '/api/lists', {name: 'Bobs list'}, CKB)).id;
  await call('PUT', `/api/lists/${BOBS}/members`, {user_id: 1, role: 'edit'}, CKB);  // alice: member, not manager
  await call('PUT', `/api/lists/${WEB}/members`, {user_id: AG, role: 'edit'});
  await call('PUT', `/api/lists/${WEB}/members`, {user_id: BOB, role: 'edit'});
  const mk = async (title, list_id, extra = {}) => { const id = (await call('POST', '/api/tasks', {title, list_id, ...extra})).id; await sleep(30); return id; };
  const t1 = await mk('First written', HOME), t2 = await mk('Second written', HOME, {priority: 5}), t3 = await mk('Third written', HOME);
  const SEC = (await call('POST', '/api/sections', {list_id: WEB, name: 'Ideas'})).id;
  const plan = await mk('Plan launch', WEB);

  // ================= #319 sort "Created"
  let w = await boot({user: 'alice', hash: 'l/' + HOME}), d = w.document;
  const order = () => [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id);
  check(order()[0] === t2, 'default: priority first');
  w.eval('sortMenu(document.querySelector("#top h1"))'); await sleep(100);
  let it = [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Created');
  check(it && !it.classList.contains('on'), 'sort menu: "Created"');
  click(w, it); await sleep(300);
  check(w.__store[`tasks.sort2.l:${HOME}`] === '"created"' && JSON.stringify(order()) === JSON.stringify([t3, t2, t1]), 'Created: newest first: ' + order());
  check(d.querySelectorAll('#view .trow .meta .crd').length === 3 && /Created/.test(d.querySelector('#view .trow .crd').title), 'rows show the creation date while sorted by it');
  w.eval('sortMenu(document.querySelector("#top h1"))'); await sleep(100);
  it = d.querySelector('#pop .menu-list button.on');
  check(it && it.textContent.trim() === 'Created: newest first' && /reverse/.test(it.title), 'the active item names the direction');
  click(w, it); await sleep(300);
  check(w.__store[`tasks.sort2.l:${HOME}`] === '"created_asc"' && JSON.stringify(order()) === JSON.stringify([t1, t2, t3]), 'picked again: oldest first: ' + order());
  w.eval(`go('all')`); await sleep(400);
  check(!d.querySelector('#view .trow .crd'), '"All" keeps its own sort (per view)');
  w.eval('sortMenu(document.querySelector("#top h1"))'); await sleep(100);
  click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Created')); await sleep(300);
  const ao = order();
  check(w.__store['tasks.sort2.all'] === '"created"' && ao.indexOf(plan) < ao.indexOf(t3) && ao.indexOf(t3) < ao.indexOf(t1), '"All": newest first across lists: ' + ao);
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + HOME, ls: {[`tasks.sort2.l:${HOME}`]: '"created_asc"'}}); d = w.document;
  w.eval('sortMenu(document.querySelector("#top h1"))'); await sleep(100);
  check([...d.querySelectorAll('#pop .menu-list button')].some(b => b.textContent.trim() === 'Erstellt: älteste zuerst'), 'German: "Erstellt: älteste zuerst"');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #320 chat: a phone closes the keyboard after sending, the desktop keeps typing
  w = await boot({user: 'alice', mobile: true, hash: 'agents/' + AG}); d = w.document; await sleep(500);
  let ci = d.querySelector('#chat-in');
  ci.focus(); ci.value = 'Hello from the phone'; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, d.querySelector('[data-act="chat-send"]')); await sleep(900);
  check(d.querySelector('#chat-in')?.value === '' && d.activeElement?.id !== 'chat-in', 'phone: sent, the box is empty and blurred (keyboard closes)');
  check([...d.querySelectorAll('#chat-msgs *')].some(x => /Hello from the phone/.test(x.textContent)), 'phone: the message shows');
  w.close();
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`chatOpen(${AG})`); await sleep(700);
  ci = d.querySelector('#chat-in'); ci.focus(); ci.value = 'Hello from the desk'; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, d.querySelector('[data-act="chat-send"]')); await sleep(900);
  check(d.activeElement?.id === 'chat-in' && d.activeElement.value === '', 'desktop: the box keeps the focus');
  w.close();

  // ================= #321 Settings > AI colleague: the lists table
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    w = await boot({user: 'alice', mobile, hash: 'today'}); d = w.document;
    w.eval(`settingsModal('ai')`); await sleep(500);
    click(w, d.querySelector('.modal.smodal [data-aisub="lists"]')); await sleep(800);  // 2.5.1 (#393): the sub-tab Lists
    const tb = d.querySelector('.modal.smodal #s-ai-tbl');
    // 2.5.1: first only the shared lists + "Show all (2)"
    const first = [...(tb?.querySelectorAll('.airow:not(.aihead)') || [])];
    check(first.length === 1 && +first[0].dataset.lid === WEB && /Show all \(2\)/.test(tb.querySelector('[data-aiall="1"]')?.textContent || ''), `${lab}: first the shared list + Show all (2)`);
    click(w, tb.querySelector('[data-aiall="1"]')); await sleep(300);
    const rows = [...(tb?.querySelectorAll('.airow:not(.aihead)') || [])];
    check(tb && rows.length === 2 && rows.some(r => +r.dataset.lid === WEB) && rows.some(r => +r.dataset.lid === HOME) && !rows.some(r => +r.dataset.lid === BOBS),
      `${lab}: every list I manage (not Bob's, not the inbox): ${rows.map(r => r.textContent.trim().slice(0, 20))}`);
    check(/List.*Agent sees it.*Tidy up/.test(tb?.querySelector('.aihead')?.textContent || ''), `${lab}: the column heads`);
    const wr = tb.querySelector(`.airow[data-lid="${WEB}"]`), hr = tb.querySelector(`.airow[data-lid="${HOME}"]`);
    check(wr.querySelector(`[data-aid="${AG}"]`)?.getAttribute('aria-pressed') === 'true' && hr.querySelector(`[data-aid="${AG}"]`)?.getAttribute('aria-pressed') === 'false', `${lab}: chips show who sees what`);
    check(wr.querySelector('select[data-aitidy]') && !hr.querySelector('select[data-aitidy]') && hr.querySelector('.aitd .muted'), `${lab}: tidy only where an agent is`);
    w.close();
  }
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  click(w, d.querySelector('.modal.smodal [data-aisub="lists"]')); await sleep(800);
  d.querySelector('.modal.smodal').remove();
  w.eval(`settingsModal('ai')`); await sleep(900);
  check(d.querySelector('.modal.smodal [data-aisub="lists"]').getAttribute('aria-selected') === 'true' && !d.querySelector('#aisp-lists').hidden, 'reopened: the sub-tab Lists is remembered on this device');
  click(w, d.querySelector('#s-ai-tbl [data-aiall="1"]')); await sleep(300);
  click(w, d.querySelector(`#s-ai-tbl .airow[data-lid="${HOME}"] [data-aid="${AG}"]`)); await sleep(1200);
  let st = await call('GET', '/api/state');
  check((st.lists.find(l => l.id === HOME).members || []).some(m => m.user_id === AG && m.role === 'edit'), 'click: shared with the agent (Member)');
  const hsel = d.querySelector(`#s-ai-tbl .airow[data-lid="${HOME}"] select[data-aitidy]`);
  check(hsel && d.querySelector(`#s-ai-tbl .airow[data-lid="${HOME}"] [data-aid="${AG}"]`).getAttribute('aria-pressed') === 'true', 'redrawn: pressed, tidy select appears');
  hsel.value = 'suggest'; hsel.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900);
  st = await call('GET', '/api/state');
  check(st.lists.find(l => l.id === HOME).agent_tidy === 'suggest', 'tidy: saved as suggest');
  let asked = ''; w.confirm = m => { asked = m; return true; };
  click(w, d.querySelector(`#s-ai-tbl .airow[data-lid="${HOME}"] [data-aid="${AG}"]`)); await sleep(1400);
  st = await call('GET', '/api/state');
  check(/Stop sharing/.test(asked) && !(st.lists.find(l => l.id === HOME).members || []).some(m => m.user_id === AG), 'unshare after a confirm: ' + asked.slice(0, 60));
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  click(w, d.querySelector('.modal.smodal [data-aisub="lists"]')); await sleep(900);
  check(/Agent sieht sie/.test(d.querySelector('#s-ai-tbl .aihead')?.textContent || '') && /Welche Listen er sieht/.test(d.querySelector('#s-ai-lists-h')?.textContent || '') && /Listen/.test(d.querySelector('[data-aisub="lists"]')?.textContent || ''), 'German heads');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #323 the select sheet on phones
  for (let i = 0; i < 10; i++) await call('POST', '/api/lists', {name: 'Extra ' + i});
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + WEB}); d = w.document;
  w.eval(`openDetail(${plan})`); await sleep(900);
  const sel = d.querySelector('#detail #d-list');
  const ev = mdown(w, sel);
  const pop = d.querySelector('#pop');
  check(!ev && !pop.classList.contains('hidden') && pop.classList.contains('sheet') && pop.classList.contains('selpop'), 'phone: a tap on the list select opens the bottom sheet (system picker prevented)');
  check(pop.querySelector('.sshead')?.textContent === 'List' && pop.querySelector('#ss-q'), 'sheet: label on top, search above 10 options');
  const cur = pop.querySelector('[role="option"].on');
  check(cur && /Website/.test(cur.textContent) && cur.querySelector('.sschk') && cur.getAttribute('aria-selected') === 'true', 'the current value has the check');
  check(pop.querySelector('[role="option"] .ssemo')?.textContent === '🏠' && pop.querySelector('[role="option"]:not(:has(.ssemo)) svg.i'), 'emoji of a list as its icon, else the list icon');
  const q = pop.querySelector('#ss-q'); q.value = 'home'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  const vis = [...pop.querySelectorAll('[role="option"]')].filter(b => !b.hidden);
  check(vis.length === 1 && /Home\b/.test(vis[0].textContent), 'search filters the options');
  key(w, q, 'Enter'); await sleep(900);
  check(d.querySelector('#pop').classList.contains('hidden') && (await call('GET', '/api/state')).tasks.find(t => t.id === plan).list_id === HOME, 'Enter picks the first match: moved to Home');
  w.close();
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + WEB}); d = w.document;
  await call('PATCH', `/api/tasks/${plan}`, {list_id: WEB});
  w.eval(`load().then(render)`); await sleep(500);
  w.eval(`openDetail(${plan})`); await sleep(900);
  const ssel = d.querySelector('#detail #d-sec');
  key(w, ssel, 'Enter'); await sleep(100);
  const p2 = d.querySelector('#pop');
  check(!p2.classList.contains('hidden') && !p2.querySelector('#ss-q') && p2.querySelectorAll('[role="option"]').length === 2, 'keyboard Enter opens it too; 2 options: no search');
  check(d.activeElement?.closest('#pop') && d.activeElement.classList.contains('on'), 'focus on the current option');
  key(w, d.activeElement, 'ArrowDown'); await sleep(50);
  check(/Ideas/.test(d.activeElement?.textContent || ''), 'ArrowDown moves to the next option');
  click(w, d.activeElement); await sleep(900);
  check((await call('GET', '/api/state')).tasks.find(t => t.id === plan).section_id === SEC, 'picking fires change: section saved');
  const asel = d.querySelector('#detail #d-assignee');
  mdown(w, asel); await sleep(50);
  check(d.querySelector('#pop [role="option"] .avatar'), 'assignee options with avatars');
  key(w, d.querySelector('#pop'), 'Escape'); d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(50);
  check(d.querySelector('#pop').classList.contains('hidden'), 'Esc closes the sheet');
  // native where a sheet makes no sense: inside a popover (the date picker's repeat), data-native, desktop
  w.eval(`datePop(document.querySelector('#top h1'), ${plan})`); await sleep(100);
  const rep = d.querySelector('#pop #p-rep');
  check(rep && mdown(w, rep) && d.querySelector('#pop #p-rep'), 'a select inside a popover stays native (the date picker stays open)');
  w.eval('closePop()');
  const nat = d.createElement('select'); nat.setAttribute('data-native', ''); nat.innerHTML = '<option>a</option><option>b</option>'; d.body.appendChild(nat);
  check(mdown(w, nat) && d.querySelector('#pop').classList.contains('hidden'), 'data-native stays native');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + WEB}); d = w.document;
  w.eval(`openDetail(${plan})`); await sleep(800);
  check(mdown(w, d.querySelector('#detail #d-list')) && d.querySelector('#pop').classList.contains('hidden'), 'desktop: native select');
  w.close();
  w = await boot({user: 'alice', mobile: true, hash: 'today'}); d = w.document;
  w.eval(`settingsModal('look')`); await sleep(600);
  const ts = d.querySelector('.modal #s-tabadd');
  if (ts && ts.options.length >= 2) { mdown(w, ts); await sleep(50); check(d.querySelector('#pop.selpop') && d.querySelector('#pop').classList.contains('overmodal'), 'settings select: the sheet above the dialog'); }
  w.close();

  // ================= #331 #reply/<id>: the task opens with the comment box focused
  w = await boot({user: 'alice', hash: 'reply/' + plan}); d = w.document; await sleep(800);
  check(w.eval('S.sel') === plan && d.activeElement?.id === 'c-input', 'desktop: #reply/<id> opens the task, the comment box has the focus');
  check(w.location.hash === '#all' || !/reply/.test(w.location.hash), 'the reply hash is replaced: ' + w.location.hash);
  w.close();
  w = await boot({user: 'alice', mobile: true, hash: 'reply/' + plan}); d = w.document; await sleep(900);
  check(w.eval('S.sel') === plan && d.activeElement?.id === 'c-input', 'phone: the same');
  w.close();

  check(!errs.length, 'no page errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p208_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
