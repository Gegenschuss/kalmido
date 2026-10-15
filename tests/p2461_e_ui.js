// 2.46.1 UI tests, part E: phone animations (#1558 #1559 #1560), the inline title field (#1622) and the Office tabs (#1637); own
// container (start.sh).
// jsdom (phone = matchMedia max-width true): a closed menu sheet / dialog / date picker keeps its node for the exit (class an-out) and is
//   gone afterwards, a second close is a no-op, opening something new removes the leaving twin at once, "reduce motion" and the desktop
//   remove at once; the scrim and the + button fade out; rows fade before the redraw (and come back when the request fails), opened
//   rows fade in; a route change restarts the view fade, the calendar's next / previous set the side; the Office tab is "Quotes & invoices"
// Firefox 1345 and 390: the inline title field sits on the circle's line inside its row (top-level row and subtask), with and without
//   list columns; Office > Quotes & invoices: one "New quotation" button in the empty state (below the text), no heading above the tabs,
//   the three tab levels share the left edge, search field and filter share one height, no horizontal overflow on the phone
// Screenshots into $P2461E_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2461_e_ui', check, shots: 'P2461E_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,clients,office';
const PH = {mobile: true};  // a phone for jsdom

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const S1 = (await call('POST', '/api/sections', {name: 'Light', list_id: L})).id;
  const T = [];
  for (const t of ['Fix the bath light', 'Move the kitchen light', 'Stair light']) T.push((await call('POST', '/api/tasks', {title: t, list_id: L, section_id: S1})).id);
  await call('POST', '/api/tasks', {title: 'Subtask one', list_id: L, parent_id: T[2]});
  await call('PATCH', `/api/tasks/${T[1]}`, {assignee_id: BOB, due: '2030-05-02'});

  // ================= jsdom, a phone
  let w = await boot({...PH, hash: 'l/' + L}), d = w.document;
  await until(() => d.querySelector('#view .trow'));
  check(w.eval('isMobile()') === true && w.eval('an_on()') === true, 'the phone setup: isMobile and an_on');

  // ---- #1558: the menu sheet (#pop)
  w.eval(`openPop(document.body, '<div class="menu-list"><button>One</button></div>')`);
  let pop = d.querySelector('#pop');
  check(pop.classList.contains('sheet') && !pop.classList.contains('hidden'), '#1558: the menu opens as a sheet');
  w.eval('closePop()'); await sleep(30);
  check(pop.classList.contains('hidden') && pop.classList.contains('an-out') && pop.classList.contains('sheet'), '#1558: closed = hidden for the app, an-out + sheet kept for the exit');
  check(d.querySelector('#scrim').classList.contains('hidden') && d.querySelector('#scrim').classList.contains('an-out'), '#1558: the dimming layer fades out too');
  await sleep(350);
  check(!pop.classList.contains('an-out') && !pop.classList.contains('sheet') && pop.classList.contains('hidden'), '#1558: after the exit the sheet is plain hidden');
  check(!d.querySelector('#scrim').classList.contains('an-out'), '#1558: the scrim exit is over');
  w.eval(`openPop(document.body, '<div>x</div>')`); w.eval('closePop()'); await sleep(30);
  w.eval(`openPop(document.body, '<div>second</div>')`); await sleep(30);
  check(!pop.classList.contains('hidden') && !pop.classList.contains('an-out') && /second/.test(pop.textContent), '#1558: opened again while leaving = shown at once, no stuck exit');
  w.eval('closePop()'); await sleep(350);

  // ---- #1558: a dialog
  const m1 = w.eval(`modal('<h3>First</h3><button data-m="close">Close</button>')`);
  m1.remove(); await sleep(30);
  check(m1.isConnected && m1.classList.contains('an-out') && m1.hasAttribute('inert'), '#1558: a closed dialog stays for its exit (an-out, inert)');
  m1.remove(); m1.remove();  // double tap
  await sleep(350);
  check(!m1.isConnected && !d.querySelector('.modal') && !d.body.classList.contains('modal-open'), '#1558: gone after the exit, a second close changed nothing, scroll lock released');
  const m2 = w.eval(`modal('<h3>Second</h3>')`); m2.remove(); await sleep(20);
  const m3 = w.eval(`modal('<h3 id="third">Third</h3>')`);
  check(!m2.isConnected && m3.isConnected && d.querySelectorAll('.modal').length === 1, '#1558: a new dialog removes the leaving one at once (no twin)');
  m3.remove(); await sleep(350);
  // ---- #1558: the date picker
  w.eval(`dpOpen(document.querySelector('#view .trow .ttl'), {kind: 'date', value: '', onPick() {}})`); await sleep(100);
  const dp = d.querySelector('#dpop'); check(!!dp && dp.classList.contains('sheet'), '#1558: the date picker is a sheet on the phone');
  w.eval('dpClose()'); await sleep(30);
  check(dp.isConnected && dp.classList.contains('an-out') && !w.eval('DP.el'), '#1558: closed = DP.el is null at once, the node folds away');
  await sleep(350); check(!dp.isConnected, '#1558: the picker is removed after the exit');

  // ---- #1558: the phone with "reduce motion" and the desktop remove at once
  w.close();
  w = await boot({...PH, media: {'(prefers-reduced-motion: reduce)': true}, hash: 'l/' + L}); d = w.document;
  const mr = w.eval(`modal('<h3>Calm</h3>')`); mr.remove();
  check(!mr.isConnected && w.eval('an_on()') === false, '#1558: reduce motion: the dialog is removed at once');
  w.eval(`openPop(document.body, '<div>x</div>')`); w.eval('closePop()'); await sleep(30);
  check(!d.querySelector('#pop').classList.contains('an-out'), '#1558: reduce motion: no exit class on the sheet');
  w.close();
  w = await boot({hash: 'l/' + L}); d = w.document; await until(() => d.querySelector('#view .trow'));
  const md = w.eval(`modal('<h3>Desk</h3>')`); md.remove();
  check(!md.isConnected, '#1558: desktop: the dialog is removed at once');
  w.eval(`openPop(document.body, '<div>x</div>')`); w.eval('closePop()'); await sleep(30);
  check(!d.querySelector('#pop').classList.contains('an-out') && !d.querySelector('#scrim').classList.contains('an-out'), '#1558: desktop: no exit classes');
  // desktop rows: completing does not wait
  w.close();

  // ================= #1559 rows (phone)
  w = await boot({...PH, hash: 'l/' + L}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T[0]}"]`));
  const row0 = d.querySelector(`#view .trow[data-id="${T[0]}"]`);
  const done = w.eval(`toggleTask(${T[0]})`);
  await sleep(20);
  check(row0.classList.contains('an-rowout'), '#1559: the row fades while the request runs');
  await done;
  const t0 = await (await fetch(B + `api/tasks/${T[0]}`, {headers: {...H, Cookie: CK}})).json();
  check(t0.status !== 0, '#1559: the task is completed on the server (status ' + t0.status + ')');
  check(!d.querySelector(`#view .trow[data-id="${T[0]}"]:not(.done)`), '#1559: the redraw came after the fade, the row is no longer open');
  // a failing request brings the row back
  const row1 = d.querySelector(`#view .trow[data-id="${T[1]}"]`);
  w.eval(`window.__api = api; api = async () => { throw new Error('boom'); }`);
  let failed = false; try { await w.eval(`toggleTask(${T[1]})`); } catch { failed = true; }
  w.eval(`api = window.__api`);
  check(failed && row1.isConnected && !row1.classList.contains('an-rowout'), '#1559: a failing request: the row comes back (' + failed + ')');
  // opened rows fade in; new rows get a class
  w.eval(`an_rowsIn(() => document.querySelector('#view').insertAdjacentHTML('beforeend', '<div class="trow" data-id="987654"></div>'))`);
  check(d.querySelector('#view .trow[data-id="987654"]')?.classList.contains('an-rowin') && !d.querySelector(`#view .trow[data-id="${T[1]}"]`)?.classList.contains('an-rowin'), '#1559: only rows that were not there fade in');
  // the + button and the selection bar are watched, the scrim opens with a fade (CSS)
  w.eval('S.multi.add(' + T[1] + '); renderMultiBar()'); await sleep(30);
  check(!d.querySelector('#mbar').classList.contains('hidden') && !d.querySelector('#mbar').classList.contains('an-out'), '#1559: the selection bar shows');
  w.eval('S.multi.clear(); S.multiMode = false; renderMultiBar()'); await sleep(30);
  check(d.querySelector('#mbar').classList.contains('hidden') && d.querySelector('#mbar').classList.contains('an-out'), '#1559: the selection bar slides out (hidden + an-out)');
  await sleep(350); check(!d.querySelector('#mbar').classList.contains('an-out'), '#1559: the bar exit is over');

  // ================= #1560 views (phone)
  const sig0 = w.eval('an_sig()');
  w.eval(`go('cal')`); await until(() => d.querySelector('#view .calbar'));
  check(/(^| )an-v[12]( |$)/.test(d.querySelector('#view').className), '#1560: another route restarts the view fade: ' + d.querySelector('#view').className);
  const c1 = d.querySelector('#view').className;
  w.eval('renderView()'); check(d.querySelector('#view').className === c1, '#1560: a redraw of the same route does not restart it');
  d.querySelector('[data-act="cal-next"]').click(); await sleep(50);
  check(/(^| )an-cn[12]( |$)/.test(d.querySelector('#view').className), '#1560: next = the page comes from the right: ' + d.querySelector('#view').className);
  d.querySelector('[data-act="cal-prev"]').click(); await sleep(50);
  check(/(^| )an-cp[12]( |$)/.test(d.querySelector('#view').className), '#1560: previous = from the left');
  d.querySelector('[data-act="cal-today"]').click(); await sleep(50);
  check(/(^| )an-cs[12]( |$)/.test(d.querySelector('#view').className), '#1560: Today = a fade');
  check(sig0 !== w.eval('an_sig()'), '#1560: the route signature differs between the list and the calendar');
  // tab underline: the active tab changes -> the new one gets the class
  w.eval(`AN.tab = 'x'; an_tabs()`);
  check(!d.querySelector('#tabs button.on') || d.querySelector('#tabs button.on').classList.contains('an-tabin'), '#1560: the tab that became active gets the underline class');
  w.close();

  // ================= #1637: the tab name, jsdom
  w = await boot({hash: 'office/offers'}); d = w.document;
  await until(() => d.querySelector('.office .ofctabs'), 60);
  const tab1 = d.querySelector('.office .ofctabs [data-go="office/offers"]');
  check(/^\s*Quotes & invoices\s*$/.test(tab1?.textContent || ''), '#1637: the tab is named "Quotes & invoices": ' + (tab1?.textContent || ''));
  check(!d.querySelector('.office .ofchead h2'), '#1637: no second "Office & finance" heading above the tabs');
  await until(() => d.querySelector('.office .ofdbar'), 60);
  await sleep(300);
  check(d.querySelectorAll('.office [data-ofd="new"]').length === 1 && !!d.querySelector('.office .empty.eact [data-ofd="new"]'), '#1637: the empty list has exactly one "New quotation", the big one in the empty state');
  check(!d.querySelector('.office .empty.eact [data-ofd="new"] ~ *') && !!d.querySelector('.office .empty.eact > span'), '#1637: the button comes after the text');
  d.querySelector('.office .ofdkinds [data-kind="invoice"]').click(); await sleep(400);
  check(!!d.querySelector('.office .ofdbar'), '#1637: the other kinds keep their bar');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const rect = `const R = e => { if (!e) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), t: Math.round(b.top), r: Math.round(b.right), b: Math.round(b.bottom), h: Math.round(b.height)}; };`;
  const inline = async (o, id, what) => {
    const g = await o.ev(`(() => { ${rect} const row = document.querySelector('#view .trow[data-id="${id}"]'); if (!row) return null; inlineEditStart(${id}); const i = row.querySelector('.ttlin'), c = row.querySelector('.chk'); const res = {row: R(row), i: R(i), c: R(c), disp: i && getComputedStyle(i).display}; inlineEditCancel(); return res; })()`);
    check(!!g && !!g.i, `#1622: ${what}: the field is there ` + JSON.stringify(g));
    if (!g || !g.i) return;
    const mid = x => (x.t + x.b) / 2;
    check(g.i.t >= g.row.t && g.i.b <= g.row.b, `#1622: ${what}: the field lies inside its row ` + JSON.stringify(g));
    check(Math.abs(mid(g.i) - mid(g.c)) <= 4, `#1622: ${what}: the field is level with the circle ` + JSON.stringify(g));
    check(g.i.l >= g.c.r && g.i.r <= g.row.r, `#1622: ${what}: the field starts after the circle and ends inside the row`);
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '1345: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1345, height: 800}});
    await o.nav(B + '#l/' + L); await until(() => ev(`!!document.querySelector('#view .trow')`), 60); await sleep(800);
    await inline(o, T[0], '1345 plain list, top-level row');
    await inline(o, T[1], '1345 plain list, row with assignee and date');
    const sub = await ev(`(() => { const r = [...document.querySelectorAll('#view .trow.sub, #view .trow.subrow')][0]; return r ? +r.dataset.id : 0; })()`);
    if (sub) await inline(o, sub, '1345 subtask (comparison)'); else check(false, '1345: the subtask row is there');
    await shot('p2461e-1345-list.png');
    // with list columns
    await call('PATCH', `/api/lists/${L}`, {columns: ['due', 'who']});
    await o.nav(B + '#l/' + L); await sleep(1500);
    await inline(o, T[1], '1345 list with columns, row with assignee');
    await inline(o, T[2], '1345 list with columns, plain row');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 800}}); await sleep(600);
    await inline(o, T[1], '390 list with columns');
    await call('PATCH', `/api/lists/${L}`, {columns: null});
    await o.nav(B + '#l/' + L); await sleep(1500);
    await inline(o, T[0], '390 plain list');
  }, undefined);

  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, 'office: login');
    const ready = async (n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('.office .ofdbar')`).catch(() => false)); i++) await sleep(300); await sleep(600); };
    const office = `(() => { ${rect} const q = s => document.querySelector(s); const empty = q('.office .empty'), btn = empty && empty.querySelector('[data-ofd="new"]'), txt = empty && empty.querySelector(':scope > span'), srch = q('.office .ofdbar .ctsearch'), sel = q('.office .ofdbar select');
      return JSON.stringify({mg: R(q('.mgtabs button')), l2: R(q('.office .ofctabs button')), l3: R(q('.office .ofdkinds button')), srch: R(srch), sel: R(sel), btn: R(btn), txt: R(txt), news: document.querySelectorAll('.office [data-ofd="new"]').length, h2: !!q('.office .ofchead h2'), over: document.documentElement.scrollWidth > innerWidth + 1}); })()`;
    for (const [wd, tag] of [[1345, '1345'], [390, '390']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: 850}});
      await o.nav(B + '#office/offers'); await ready();
      const g = JSON.parse(await ev(office));
      check(g.news === 1 && !g.h2, `#1637 ${tag}: one "New quotation", no heading above the tabs ` + JSON.stringify(g));
      check(g.btn && g.txt && g.btn.t >= g.txt.b - 1, `#1637 ${tag}: the button is below the text ` + JSON.stringify([g.btn, g.txt]));
      check(g.mg && g.l2 && g.l3 && Math.abs(g.mg.l - g.l2.l) <= 4 && Math.abs(g.l2.l - g.l3.l) <= 6, `#1637 ${tag}: the three tab levels start at the same edge ` + JSON.stringify([g.mg, g.l2, g.l3]));
      check(g.srch && g.sel && Math.abs(g.srch.h - g.sel.h) <= 2, `#1637 ${tag}: search field and filter share one height ` + JSON.stringify([g.srch, g.sel]));
      check(!g.over, `#1637 ${tag}: no horizontal overflow`);
      await shot(`p2461e-office-${tag}.png`);
    }
  }, undefined);

  console.log(`p2461_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
