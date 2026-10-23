// 2.196.0 A (#2737) UI tests: the phone's drawer follows sidebar B of a computer. On top (fixed) search, Today and Inbox,
// below ONE row of the area icons (the computer's bar, same order and rights, scrolls sideways, never wraps), below only the
// chosen area's panel (the computer's panel parts), at the bottom (fixed) Settings and the account. An icon opens the page
// kept for its area and the drawer stays open; one Back closes it. Computer, children and mini windows unchanged.
// Own container (start.sh), Firefox with touch. freelancer-matrix: n/a (no new route; frida without an organisation runs the drawer)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2196_a_mside_ui', check, shots: 'P2196A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2196A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const MODS = 'cal,comments,office,contacts,wiki,time,pomo,review,stats,agents';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: MODS.split(',')});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: MODS + ',collab'});
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.http < 300, 'P4: frida (no organisation) ' + fr.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: MODS});
  const L = {};
  for (const [n, f] of [['Todo', ''], ['Gifts', 'Family'], ['Trips', 'Family'], ['Taxes', 'Private']]) {
    L[n] = (await call(CA, 'POST', '/api/lists', {name: n})).id;
    if (f) await call(CA, 'PATCH', `/api/lists/${L[n]}`, {folder: f});
    await call(CA, 'POST', '/api/tasks', {title: n + ' task', list_id: L[n]});
  }
  await call(CA, 'PATCH', '/api/settings', {folders: JSON.stringify(['Family', 'Private'])});
  check((await call(CA, 'PUT', '/api/folders/people', {folder: 'Family', user_id: BOB, role: 'edit'})).shared === 2, 'setup: the folder Family is shared');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (o, u) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  const tap = sel => `(() => { const b = document.querySelector('${sel}'); if (b) b.click(); return !!b; })()`;
  const open = async ev => { await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`); return ready(ev, `!!document.querySelector('#side.open')`, 20); };
  // what the drawer shows
  const SIDE = `(() => { const s = document.querySelector('#side'), R = el => el && el.getBoundingClientRect(), sr = R(s), row = document.querySelector('#side .sbmr');
    const btns = [...document.querySelectorAll('#side .sbmr .srb[data-sbb]')], dock = document.querySelector('#side .sbdock');
    return {open: s.classList.contains('open'), row: !!row, ids: btns.map(b => b.dataset.sbb), on: (document.querySelector('#side .sbmr .srb.on') || {dataset: {}}).dataset.sbb || '',
      rail: typeof SBB_RAIL === 'undefined' ? [] : SBB_RAIL.map(r => r[0]).filter(id => btns.some(b => b.dataset.sbb === id)),
      oneLine: btns.length > 0 && btns.every(b => Math.abs(R(b).top - R(btns[0]).top) < 1), scrolls: !!row && row.scrollWidth > row.clientWidth + 1, minH: Math.min(...btns.map(b => R(b).height)),
      search: !!document.querySelector('#side .sbfix .scmd'), today: !!document.querySelector('#side .sbfix .srow[data-go="today"]'), inbox: !!document.querySelector('#side .sbfix .srow[data-drop="inbox"]'),
      rowFixed: !!document.querySelector('#side .sbfix .sbmr'), lists: !!document.querySelector('#side .sg-lists'), office: !!document.querySelector('#side [data-ofmg]'), wiki: !!document.querySelector('#side .sbbp, #side [data-act="sbb-tree"], #side .sbbtl'),
      todayTwice: document.querySelectorAll('#side .srow[data-go="today"]').length, set: !!(dock && dock.querySelector('.sset')), acct: !!(dock && dock.querySelector('.sbacct')),
      dockBottom: dock ? Math.round(sr.bottom - R(dock).bottom) : null, fshr: !!document.querySelector('#side .fhead[data-folder="Family"] .fshr'), ws: !!document.querySelector('#side .sbhead .wsbar'),
      inside: s.scrollWidth <= s.clientWidth + 1, mod: S.route.mod, hash: location.hash}; })()`;

  const phone = async (o, w, h, tag) => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
    await nav(B + '#today');
    check(await ready(ev, `!!document.querySelector('#top .menu') && !!S.booted`, 80), `${tag}: the app is up`);
    check(await open(ev), `${tag}: the drawer opens`);
    await sleep(400);
    let s = await ev(SIDE);
    await shot(`p2196a-tasks-${w}.png`);
    check(s.row && s.ids.length >= 5 && s.ids.join() === s.rail.join() && s.ids[0] === 'tasks' && ['cal', 'office', 'wiki'].every(x => s.ids.includes(x)), `${tag}: the row of area icons in the order of the computer's bar ` + JSON.stringify(s));
    check(s.oneLine && s.minH >= 43, `${tag}: one line, big enough to tap ` + JSON.stringify(s));
    if (w <= 360) check(s.scrolls, `${tag}: a narrow phone: the row scrolls sideways ` + JSON.stringify(s));
    check(s.on === 'tasks' && s.search && s.today && s.inbox && s.rowFixed && s.todayTwice === 1, `${tag}: on top search, Today, Inbox and the row; Today only once ` + JSON.stringify(s));
    check(s.lists && !s.office && s.fshr && s.ws && s.inside, `${tag}: the Tasks panel: projects (shared folder with its share symbol), the workspace switch stays ` + JSON.stringify(s));
    check(s.set && s.acct && Math.abs(s.dockBottom) <= 2, `${tag}: at the bottom Settings and the account ` + JSON.stringify(s));
    await ev(`(() => { const s = document.querySelector('#side'); s.scrollTop = s.scrollHeight; return 1; })()`); await sleep(200);
    s = await ev(SIDE);
    check(Math.abs(s.dockBottom) <= 2, `${tag}: the bottom stays put while the middle scrolls ` + JSON.stringify(s));
    await ev(`(() => { document.querySelector('#side').scrollTop = 0; return 1; })()`);
    // an icon: the area's page, the drawer stays open with its panel
    check(await ev(tap('#side .sbmr .srb[data-sbb="office"]')), `${tag}: tap the office icon`);
    check(await ready(ev, `S.route.mod === 'office' && !!document.querySelector('#side [data-ofmg]')`, 40), `${tag}: the office opens with its panel`);
    await sleep(500);
    s = await ev(SIDE);
    check(s.open && s.on === 'office' && s.office && !s.lists && s.search && s.today, `${tag}: the drawer stays open, only the office panel, the top stays ` + JSON.stringify(s));
    await shot(`p2196a-office-${w}.png`);
    // Back once = the drawer closes (no stacked steps)
    await ev(`(() => { history.back(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('#side.open')`, 20), `${tag}: one Back closes the drawer`);
    await sleep(400);
    // a row of the panel goes there and closes the drawer; the area keeps that page
    check(await open(ev), `${tag}: the drawer opens again`);
    await ev(tap('#side .sbmr .srb[data-sbb="office"]'));
    await ready(ev, `S.route.mod === 'office' && !!document.querySelector('#side [data-ofm]')`, 40);
    const row = await ev(`(() => { const r = [...document.querySelectorAll('#side [data-ofm]')].find(b => !b.classList.contains('on')); if (!r) return ''; r.click(); return r.dataset.go; })()`);
    check(!!row && await ready(ev, `location.hash === ${JSON.stringify('#' + row)} && !document.querySelector('#side.open')`, 30), `${tag}: a panel row opens its page and closes the drawer ` + row);
    await sleep(300);
    // Tasks again, then back to the office: its kept page
    await open(ev);
    await ev(tap('#side .sbmr .srb[data-sbb="tasks"]'));
    check(await ready(ev, `S.route.mod === 'tasks' && S.route.key === 'today' && !!document.querySelector('#side.open') && !!document.querySelector('#side .sg-lists')`, 40), `${tag}: Tasks: back on Today, its panel`);
    await ev(tap('#side .sbmr .srb[data-sbb="office"]'));
    check(await ready(ev, `location.hash === ${JSON.stringify('#' + (row || 'x'))} && !!document.querySelector('#side.open')`, 40), `${tag}: the office opens its kept page ` + await ev(`location.hash`));
    // Knowledge: its panel
    await ev(tap('#side .sbmr .srb[data-sbb="wiki"]'));
    check(await ready(ev, `S.route.mod === 'wiki' && !!document.querySelector('#side.open') && !document.querySelector('#side .sg-lists') && !document.querySelector('#side [data-ofmg]')`, 40), `${tag}: Knowledge opens with its panel, the drawer open`);
    await sleep(800);
    s = await ev(SIDE);
    check(s.on === 'wiki' && s.set && s.acct, `${tag}: Knowledge: the icon is marked, the bottom stays ` + JSON.stringify(s));
    await shot(`p2196a-wiki-${w}.png`);
    await ev(`(() => { history.back(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('#side.open')`, 20), `${tag}: after several area changes one Back closes the drawer`);
    await sleep(300);
  };

  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    check(await signIn(o, 'alice') === 200, 'alice: login');
    await phone(o, 360, 780, 'narrow');
    await phone(o, 430, 932, 'wide');
    // the computer: the bar of the areas, no row in the panel
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await nav(B + '#today');
    check(await ready(ev, `!!document.querySelector('#srail .srb[data-sbb]')`, 80), 'computer: the bar of the areas');
    const d = await ev(`({row: !!document.querySelector('#side .sbmr'), b: document.querySelector('#app').classList.contains('sb-b'), kbar: !!document.querySelector('#kbar .kbsw'), dockSearch: !!document.querySelector('#side .sbdock')})`);
    check(!d.row && d.b && d.kbar && !d.dockSearch, 'computer: unchanged (bar + head bar, no icon row in the panel) ' + JSON.stringify(d));
  }, true);

  // P4: frida without an organisation has the same drawer
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    check(await signIn(o, 'frida') === 200, 'frida: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    await ready(ev, `!!document.querySelector('#top .menu') && !!S.booted`, 80);
    check(await open(ev), 'P4: the drawer opens');
    await sleep(300);
    const s = await ev(SIDE);
    check(s.row && s.ids[0] === 'tasks' && s.ids.includes('cal') && s.ids.includes('office') && s.ws && s.set && s.acct, 'P4: the row, the switch, Settings and the account without an organisation ' + JSON.stringify(s));
    await ev(tap('#side .sbmr .srb[data-sbb="cal"]'));
    check(await ready(ev, `S.route.mod === 'cal' && !!document.querySelector('#side.open')`, 40), 'P4: the calendar opens, the drawer stays');
  }, true);

  console.log(`p2196_a_mside_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
