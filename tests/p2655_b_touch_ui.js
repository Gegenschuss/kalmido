// 2.655.0 part B UI tests (jsdom), fresh DB: a touch tablet (840 x 1180, hover:none, not the phone layout) behaves like
// kalmido-suite: fresh
// a phone for the keyboard and the browser's drag, a computer with a mouse stays as it was.
// #5081 no autofocus into a text field on touch (focusIfKeyboard): the task's date dialog (#p-din, inputmode numeric), the
//   shared date picker (#dp-din: the grid gets the focus instead), "Waiting on" (#w-note), the milestone dialog (#pm-name);
//   Search focuses its field when opened but does not take it back after every render; "+" on a section = the quick sheet
// #5085 no draggable="true" on touch: task rows, the sidebar's project rows, calendar chips, favourite tiles; the finger's
//   swipe that completes a task carries the row out on a tablet too (was phones only)
// Each part again on a computer with a mouse (1440 px, no hover:none): focus and draggable as before.
// The person has no organisation (freelancer parity).
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, n = 100) => require('./boot').until(fn, {timeout: n * 150, step: 150});
// the window's timer queue has passed `ms`: every focus timer the app set before (20-50 ms) has had its turn
const passed = (w, ms = 120) => new Promise(r => w.setTimeout(r, ms));
const TOUCH = {'(hover: none)': true, '(pointer: coarse)': true};
const tc = (w, el, type, x, y) => {
  const e = new w.Event(type, {bubbles: true, cancelable: true}), t = [{identifier: 1, target: el, clientX: x, clientY: y}];
  Object.defineProperty(e, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : t});
  Object.defineProperty(e, 'changedTouches', {value: t});
  el.dispatchEvent(e); return e;
};
const ymd = dt => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CA = await login('alice');
  const callA = async (method, url, body, ck = CA) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
  await callA('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const fr = await callA('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, 'a person without an organisation');
  const CF = await login('frida');
  const call = (method, url, body) => callA(method, url, body, CF);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  const SEC = (await call('POST', '/api/sections', {list_id: L, name: 'Beds'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Water the plants', list_id: L, due: ymd(new Date())})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Cut the hedge', list_id: L, due: ymd(new Date())})).id;
  check(L && SEC && T1 && T2, 'a project with two tasks due today');

  for (const touch of [true, false]) {
    const tag = touch ? 'touch 840' : 'mouse 1440';
    let w = await boot({user: 'frida', hash: 'l/' + L, media: touch ? TOUCH : {}}), d = w.document;
    w.innerWidth = touch ? 840 : 1440; w.innerHeight = touch ? 1180 : 900;
    await until(() => d.querySelector(`#view .trow[data-id="${T1}"]`));
    check(w.eval('isTouch()') === touch && !w.eval('isMobile()'), `${tag}: isTouch ${touch}, not the phone layout`);
    check(w.eval('typeof focusIfKeyboard') === 'function', `${tag}: the shared helper focusIfKeyboard`);

    // ---- #5085 draggable
    const rowsDrag = d.querySelectorAll('#view .trow[draggable="true"]').length, rows = d.querySelectorAll('#view .trow[data-id]').length;
    check(rows >= 2 && rowsDrag === (touch ? 0 : rows), `${tag}: task rows draggable ${touch ? 'none' : 'all'} (${rowsDrag}/${rows})`);
    const side = d.querySelectorAll(`#side [data-list="${L}"]`).length, sideDrag = d.querySelectorAll(`#side [data-list="${L}"][draggable="true"]`).length;
    check(side >= 1 && sideDrag === (touch ? 0 : side), `${tag}: the sidebar's project row draggable ${touch ? 'no' : 'yes'} (${sideDrag}/${side})`);
    const fav = w.eval(`fv2_tileHtml({sep: true, key: 'sep:1'}, false)`);
    check(/fv2-sep/.test(fav) && /draggable="true"/.test(fav) === !touch, `${tag}: a favourite tile draggable ${touch ? 'no' : 'yes'}`);
    w.eval(`S.listReorder = true; render()`);
    const ro = await until(() => d.querySelectorAll(`#side .srow.reorder[data-list="${L}"]`).length);
    check(ro && d.querySelectorAll(`#side .srow.reorder[data-list="${L}"][draggable="true"]`).length === (touch ? 0 : ro), `${tag}: arranging the projects: rows draggable ${touch ? 'no' : 'yes'}`);
    w.eval(`S.listReorder = false; render()`);

    // ---- #5081 the task's date dialog
    w.eval(`datePop(document.querySelector('#view .trow[data-id="${T1}"]'), ${T1})`);
    const pdin = await until(() => d.querySelector('#pop #p-din'));
    if (touch) await passed(w); else await until(() => d.activeElement?.id === 'p-din');
    check(pdin && (d.activeElement?.id === 'p-din') === !touch, `${tag}: the date dialog's field ${touch ? 'not focused' : 'focused'}`);
    check(pdin && pdin.getAttribute('inputmode') === (touch ? 'numeric' : 'text'), `${tag}: the date field's keypad ${touch ? 'numeric' : 'text'}`);
    check(!d.querySelector('#pop.sheet'), `${tag}: the date dialog is a popover, not a sheet`);
    w.eval('closePop()');

    // ---- the shared date picker
    w.eval(`dpOpen(document.querySelector('#top h1') || document.body, {kind: 'date', value: ''})`);
    const din = await until(() => d.querySelector('#dpop #dp-din'));
    if (touch) await until(() => d.activeElement?.closest?.('#dpop .dpg')); else await until(() => d.activeElement?.id === 'dp-din');
    check(din && (d.activeElement === din) === !touch && din.getAttribute('inputmode') === (touch ? 'numeric' : 'text'), `${tag}: the date picker ${touch ? 'focuses the month grid, numeric keypad' : 'focuses the text field'}`);
    w.eval('dpClose(false)');

    // ---- "Waiting on"
    w.eval(`waitDialog(${T2})`);
    const wn = await until(() => d.querySelector('.modal #w-note'));
    if (touch) await passed(w); else await until(() => d.activeElement?.id === 'w-note');
    check(wn && (d.activeElement === wn) === !touch, `${tag}: "Waiting on" ${touch ? 'not focused' : 'focused'}`);
    d.querySelector('.modal [data-m="close"]')?.click(); await until(() => !d.querySelector('.modal #w-note'));

    // ---- the milestone dialog
    w.eval(`povMsModal(listById(${L}), null)`);
    const pm = await until(() => d.querySelector('.modal #pm-name'));
    if (touch) await passed(w); else await until(() => d.activeElement?.id === 'pm-name');
    check(pm && (d.activeElement === pm) === !touch, `${tag}: the milestone's name ${touch ? 'not focused' : 'focused'}`);
    d.querySelector('.modal [data-m="close"]')?.click(); await until(() => !d.querySelector('.modal #pm-name'));

    // ---- "+" on a section: touch = the quick sheet (the inline field went behind the keyboard)
    w.eval(`secAddOpen(${SEC})`);
    if (touch) check(await until(() => d.querySelector('.qadd.sheet #qsheet')) && !d.querySelector('#view .secadd-in'), `${tag}: "+" on a section opens the quick sheet`);
    else check(await until(() => d.activeElement?.classList?.contains('secadd-in')), `${tag}: "+" on a section focuses the inline field`);
    w.eval(`S.secAdd = null; closePop(); render()`);

    // ---- #5085 the swipe that completes a task carries the row out
    if (touch) {
      const r = d.querySelector(`#view .trow[data-id="${T2}"]`), t = r.querySelector('.ttl, .tt, .title') || r;
      tc(w, t, 'touchstart', 100, 300); tc(w, t, 'touchmove', 160, 302); tc(w, t, 'touchmove', 240, 303);
      tc(w, t, 'touchend', 240, 303);
      check(r.style.transform === 'translateX(110%)', `${tag}: a swipe right carries the row out (was phones only): ${r.style.transform}`);
      const sw = await until(async () => (await call('GET', `/api/tasks/${T2}`)).status > 0, 40);  // done (status 2 here)
      check(sw, `${tag}: the swipe completed the task`);
      check((await call('POST', `/api/tasks/${T2}/reopen`)).http < 300, `${tag}: reopened for the next part`);
    }

    // ---- Search: opening focuses, a render does not take the focus back on touch
    w.location.hash = 'search';
    const sq = await until(() => d.activeElement?.id === 'searchq' && d.activeElement);
    check(sq, `${tag}: opening Search focuses its field`);
    sq?.blur(); w.eval('render()');
    if (touch) await passed(w);
    check((d.activeElement?.id === 'searchq') === !touch, `${tag}: after a render the search field ${touch ? 'stays without focus' : 'has the focus again'}`);

    // ---- calendar chips
    w.close();
    w = await boot({user: 'frida', hash: 'cal', ls: {'tasks.calMode': '"month"'}, media: touch ? TOUCH : {}}); d = w.document;
    w.innerWidth = touch ? 840 : 1440; w.innerHeight = touch ? 1180 : 900;
    const evs = await until(() => d.querySelectorAll(`#view .ev[data-id="${T1}"], #view .wev[data-id="${T1}"]`).length);
    const evd = d.querySelectorAll('#view .ev[draggable="true"], #view .wev[draggable="true"]').length;
    check(evs && evd === (touch ? 0 : d.querySelectorAll('#view .ev[data-id], #view .wev[data-id]').length), `${tag}: calendar chips draggable ${touch ? 'none' : 'all'} (${evd})`);
    w.close();
  }
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
