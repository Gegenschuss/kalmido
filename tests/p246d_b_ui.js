// 2.46.4 UI tests of part B (#1751, own container, start.sh). jsdom: the list switch "Tap does not open details".
// - a shopping list (on by default): a tap on a task row ticks it off (undo message), a second tap puts it back; no panel
// - a mouse click waits for a double click: a double click renames the task (inline field), nothing is ticked off
// - "Open details" on top of the row's menu (taskMenu, right-click) and of the phone's selection menu opens the task
// - Ctrl-click still selects; the circle still ticks; a read-only member's tap opens the task as before
// - the switch in the list settings (owner): off = a tap opens the details again (old behaviour), one undo step
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
// a click with a pointer type (jsdom's MouseEvent has none: set it like a browser's PointerEvent would)
const tap = (w, el, o = {}) => { const e = new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0, detail: o.detail || 1, ctrlKey: !!o.ctrl}); Object.defineProperty(e, 'pointerType', {value: o.type || 'touch'}); el.dispatchEvent(e); return e; };
const status = async id => (await call('GET', `/api/tasks/${id}`)).status;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const SHOP = (await call('POST', '/api/lists', {name: 'Groceries', family: 'shopping'})).id;
  const PLAIN = (await call('POST', '/api/lists', {name: 'Office'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Apples', list_id: SHOP})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Bread', list_id: SHOP})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Cheese', list_id: SHOP})).id;
  const P1 = (await call('POST', '/api/tasks', {title: 'Report', list_id: PLAIN})).id;
  let w = await boot({user: 'alice', hash: 'l/' + SHOP}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`), ttl = id => row(id)?.querySelector('.ttl');
  await until(() => ttl(T1));
  check(w.eval(`tp_on(listById(${SHOP}))`) === true && w.eval(`tp_on(listById(${PLAIN}))`) === false, '#1751: on for the new shopping list, off for a plain list');

  // ================= a tap ticks off, a second tap puts it back
  tap(w, ttl(T1));
  check(await until(async () => (await status(T1)) === 2), '#1751: a tap on the title ticks the task off');
  check(!w.eval('S.sel') && !d.querySelector('#detail.open, #detail:not(.hidden) #d-title'), '#1751: no task panel opened');
  check(await until(() => /Completed|Apples/.test(d.querySelector('#toast')?.textContent || '')) && !!d.querySelector('#toast [data-act], #toast button'), '#1751: the undo message of the circle: ' + (d.querySelector('#toast')?.textContent || ''));
  await until(() => ttl(T1));
  tap(w, ttl(T1));
  check(await until(async () => (await status(T1)) === 0), '#1751: a second tap on the completed task puts it back');
  // the gap of the row (the row itself) ticks off too
  await until(() => row(T2));
  tap(w, row(T2));
  check(await until(async () => (await status(T2)) === 2), '#1751: a tap on the row\'s gap ticks off too');
  await call('POST', `/api/tasks/${T2}/reopen`); await w.eval('load().then(render)'); await until(() => ttl(T2));

  // ================= a mouse click waits; a double click renames and ticks nothing
  tap(w, ttl(T3), {type: 'mouse'});
  check((await status(T3)) === 0, '#1751: a mouse click waits a moment (a double click may follow)');
  check(await until(async () => (await status(T3)) === 2), '#1751: ... then ticks the task off');
  await call('POST', `/api/tasks/${T3}/reopen`); await w.eval('load().then(render)'); await until(() => ttl(T3));
  tap(w, ttl(T3), {type: 'mouse'}); tap(w, ttl(T3), {type: 'mouse', detail: 2});
  ttl(T3).dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true}));
  await sleep(600);
  check((await status(T3)) === 0, '#1751: a double click ticks nothing off');
  check(!!d.querySelector(`#view .trow[data-id="${T3}"] .ttlin`), '#1751: a double click still renames the task in the list');
  w.eval('inlineEditCancel()'); await sleep(100);

  // ================= Ctrl-click selects, the circle ticks
  tap(w, ttl(T2), {type: 'mouse', ctrl: true});
  check(w.eval(`S.multi.has(${T2})`) && (await status(T2)) === 0, '#1751: Ctrl-click still selects (nothing ticked off)');
  w.eval('S.multi.clear(); S.multiMode = false; render()'); await sleep(100);
  tap(w, row(T2).querySelector('[data-act="toggle"]'));
  check(await until(async () => (await status(T2)) === 2), '#1751: the circle ticks off as before');
  await call('POST', `/api/tasks/${T2}/reopen`); await w.eval('load().then(render)'); await until(() => ttl(T2));

  // ================= "Open details" in the menus
  w.eval(`taskMenu(document.querySelector('#view .trow[data-id="${T1}"] .ttl'), ${T1})`); await sleep(100);
  const od = [...d.querySelectorAll('[role="menuitem"]')].find(b => /Open details/.test(b.textContent));
  check(!!od, '#1751: "Open details" in the row menu (right-click)');
  od?.click(); await sleep(400);
  check(w.eval('S.sel') === T1, '#1751: "Open details" opens the task');
  w.eval('closeDetail()'); await sleep(200);
  w.eval(`S.multiMode = true; S.multi.add(${T2}); renderMultiBar()`);
  w.eval(`multiMoreMenu(document.querySelector('#mbar') || document.body)`); await sleep(100);
  const od2 = [...d.querySelectorAll('[role="menuitem"]')].find(b => /Open details/.test(b.textContent));
  check(!!od2, '#1751: "Open details" in the selection menu (long press > More)');
  od2?.click(); await sleep(400);
  check(w.eval('S.sel') === T2 && !w.eval('S.multiMode') && !w.eval('S.multi.size'), '#1751: it opens the task and ends the selection');
  w.eval('closeDetail()'); await sleep(200);
  check(!w.eval(`tp_menuItems(taskById(${P1}), document.body)`).length, '#1751: not in a list without the switch');

  // ================= the switch in the list settings
  w.eval(`listModal(${SHOP})`); await sleep(300);
  const cb = d.querySelector('.modal #l-tap');
  check(!!cb && cb.checked && /Tap does not open details/.test(cb.closest('.row').textContent), '#1751: the switch in the list settings, on');
  check(/ticks it off/.test(d.querySelector('.modal .ltaprow + .shint')?.textContent || ''), '#1751: with its explanation');
  cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === SHOP)?.tap_done === 0), '#1751: off is saved');
  check(await until(() => /opens the details/.test(d.querySelector('#toast')?.textContent || '')), '#1751: a message with undo');
  d.querySelector('.modal [data-m="close"]')?.click(); await sleep(300);
  await until(() => ttl(T1));
  tap(w, ttl(T1)); await sleep(500);
  check(w.eval('S.sel') === T1 && (await status(T1)) === 0, '#1751: switched off: a tap opens the details again (old behaviour)');
  w.eval('closeDetail()'); await sleep(200);
  await w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === SHOP)?.tap_done === 1), '#1751: undo switches it on again');

  // ================= a plain list: a tap opens the task as before
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + PLAIN}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${P1}"] .ttl`));
  tap(w, d.querySelector(`#view .trow[data-id="${P1}"] .ttl`)); await sleep(500);
  check(w.eval('S.sel') === P1 && (await status(P1)) === 0, '#1751: a list without the switch: a tap opens the task');
  w.close();

  console.log(`p246d_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
