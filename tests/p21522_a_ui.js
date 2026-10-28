// 2.152.2 part A UI tests (#2622 #2617 #2618 #2632): sidebar B on a computer. Own container (start.sh), Firefox, 1280 px,
// light theme. Invented people only. freelancer-matrix: office / time / tasks -- the main person (carol) has no organisation
// (her own office admin, P4).
// - #2622: a narrow bar of the areas (#srail, aria-label, aria-current) left of ONE panel (#side); a click on an icon changes
//   panel AND page; back on Tasks the list that was open comes back (kept per device); the calendar is an icon of its own
//   and no row of the Tasks panel any more, the Tasks panel has no group "Areas"; Settings + account at the bottom of the bar
// - #2617: the office panel: Sell / Money / Administration, a folded group stays folded after reloading; no second column
//   (.ofrail) on the page any more, the page keeps its heading
// - #2618: the Time panel lists its parts (time tracking, focus timer), no tab row on the page, the header names the part
// - #2632: the office panel has as many points on #clients (office not loaded yet) as on #office
// - up / down move the focus inside the panel; a phone (402 px) has no bar
// P21522A_NOSTART=1 = the server already runs. Screenshots: P21522A_SHOTS (a screenshot run of the UI test runner).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21522_a_ui', check, shots: 'P21522A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21522A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,time,pomo,review,stats,timeline,matrix,progress';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  await call(CC, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');
  const L = (await call(CC, 'POST', '/api/lists', {name: 'Shoot Miller'})).id;
  check(L > 0, 'a list of carol');
  for (const t of ['Call the location', 'Book the crew', 'Send the quote']) await call(CC, 'POST', '/api/tasks', {title: t, list_id: L});
  await call(CC, 'POST', '/api/clients', {name: 'Example Ltd'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  const ofmN = `document.querySelectorAll('#side [data-ofm]').length`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.ofmAll', 'true'); localStorage.setItem('tasks.sbbUnfold', '["office:money"]'); /* 2.276.0 (#3039): every office point shown, Money open by hand (the first-day menu: p2276_a_ui.js) */ sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'carol') === 200, 'carol signs in');

    // ================= #2632 first, on a fresh page: #clients before the office script is loaded
    await nav(B + '#clients');
    check(await ready(ev, `!!document.querySelector('#srail [data-sbb="office"].on') && document.querySelectorAll('#side [data-ofm]').length > 10`, 80), '#2632: #clients shows the office panel');
    await sleep(1500);
    const nClients = await ev(ofmN), keysClients = await ev(`[...document.querySelectorAll('#side [data-ofm]')].map(b => b.dataset.ofm).join()`);
    await nav(B + '#office/offers');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('#top h1') && !/^Office/.test(document.querySelector('#top h1').textContent.trim())`, 80), '2.224.0 B (#2816): the office page: the big heading = the page name');
    await sleep(800);
    const keysOffice = await ev(`[...document.querySelectorAll('#side [data-ofm]')].map(b => b.dataset.ofm).join()`);
    check(nClients === await ev(ofmN) && keysClients === keysOffice, `#2632: the same points on #clients and #office (${nClients}: ${keysClients} / ${keysOffice})`);

    // ================= #2617 the office panel, no second column
    const pts = await ev(`[...document.querySelectorAll('#side .sbbp[data-ofmg]')].map(g => g.dataset.ofmg + ':' + [...g.querySelectorAll('[data-ofm]')].map(b => b.dataset.ofm).join('+')).join(' ')`);
    check(pts === 'sell:pipeline+offers+invoices+gendocs+clients+contacts+contracts+letters money:receipts+cashflow+kpi+bank+books+subs+travel+meals+cashbook admin:equipment+agreements+settings', '#2617: groups and points in the order of #2616 (P4: all of them) ' + pts);  // 2.380.0 (#3409): + invoices
    check(await ev(`[...document.querySelectorAll('#side .sbbg .sgt > span:first-of-type')].map(s => s.textContent.trim()).join('|')`) === 'Sell|Money|Administration', '#2617: the group headings (2.351.0 (#3312): the group "Folders" went into the area trees)');
    check(await ev(`(() => { const on = [...document.querySelectorAll('#side [data-ofm][aria-current="page"]')]; return on.length === 1 && on[0].dataset.ofm === 'offers' && (on[0].classList.contains('on') || !!on[0].closest('.sbbt.on')); })()`), '#2617: the open point is marked (aria-current)');  // 2.351.0 (#3312): a tree node marks its row
    check(await ev(`!document.querySelector('#view .ofrail, #view [data-mgtabs]') && !document.querySelector('#view .ofpt') && !!document.querySelector('#top h1')`), '#2617: no second column; 2.224.0 B (#2816): the heading is in the head');
    const ttl = await ev(`document.querySelector('#side .sbbpt')?.textContent || ''`);
    check(ttl.trim() === 'Office', '#2617: the panel is called Office ' + JSON.stringify(ttl));
    await shot('p21522a-office-panel-light.png');
    await click(ev, '#side [data-act="sbb-group"][data-g="office:money"]');
    check(await ready(ev, `!document.querySelector('#side [data-ofm="cashflow"]') && document.querySelector('#side [data-g="office:money"]')?.getAttribute('aria-expanded') === 'false' && !!document.querySelector('#side [data-ofm="offers"]')`, 20), '#2617: Money folds alone');
    await nav(B + 'static/icon.svg'); await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('#side [data-g="office:money"]') && typeof OFC === 'object' && !!OFC.info`, 80), 'the office again after reloading');
    check(await ev(`!document.querySelector('#side [data-ofm="cashflow"]') && document.querySelector('#side [data-g="office:money"]').getAttribute('aria-expanded') === 'false' && !!document.querySelector('#side [data-ofm="equipment"]')`), '#2617: Money stays folded after reloading (this device)');
    await click(ev, '#side [data-act="sbb-group"][data-g="office:money"]');
    check(await ready(ev, `!!document.querySelector('#side [data-ofm="cashflow"]')`, 20), '#2617: and opens again');

    // ================= #2622 the bar, panel + page together, the last page per area
    await nav(B + '#l/' + L);
    check(await ready(ev, `!!document.querySelector('#view .trow') && !!document.querySelector('#srail [data-sbb="tasks"].on')`, 80), 'the list Shoot Miller');
    check(await ev(`(() => { const r = document.querySelector('#srail'); const w = r.getBoundingClientRect().width; return r.tagName === 'NAV' && r.getAttribute('aria-label') === 'Areas' && w > 64 && w < 80 && document.querySelector('#srail [data-sbb="tasks"]').getAttribute('aria-current') === 'page'; })()`), '#2622: a narrow bar with aria-label and aria-current');
    const icons = await ev(`[...document.querySelectorAll('#srail .srbs [data-sbb]')].map(b => b.dataset.sbb).join()`);
    // 2.152.2 (#2622, decision 21.10. 18:37 + sketch B): Plan stays fixed on top with the search; Views sit between Plan and the projects
    check(await ev(`(() => { const p = document.querySelector('#side .sbfix .sg-focus [data-go="inbox"]'), g = [...document.querySelectorAll('#side > .sgroup')].map(x => [...x.classList].find(c => c.startsWith('sg-'))); return !!p && getComputedStyle(document.querySelector('#side .sbfix')).position === 'sticky' && !g.includes('sg-focus') && (!g.includes('sg-views') || g.indexOf('sg-views') < g.indexOf('sg-lists')); })()`), '#2622: Plan fixed on top, Views above the projects');
    check(/^tasks,cal,office,time,review(,|$)/.test(icons) && !/wiki|sheets|agents/.test(icons), '#2622: the icons in their order (only the switched-on areas) ' + icons);
    check(await ev(`!document.querySelector('#srail .srfoot, #srail .sset') && !document.querySelector('#srail .sbacct') && !!document.querySelector('#kbar .kbacct') && !document.querySelector('#side .sset, #side .sbacct') && !!document.querySelector('#kbar .kbsrch') && !document.querySelector('#side .scmd')`), '#2622: the account and the search in the head bar, no Settings at the bottom of the bar'); // 2.380.2 (#3400): Settings moved from the bottom of the bar into the Kalmido menu (#kbar .kbsw)  // 2.152.3 (#2619): the account (bottom of the bar) and the search (top of the panel) moved into the head bar
    check(await ev(`!document.querySelector('#side .sg-areas') && !document.querySelector('#side [data-go="cal"]') && !!document.querySelector('#side .sg-lists') && (document.querySelector('#side .sg-lists .shead')?.textContent || '').length > 0`), '#2622: Tasks panel: no Areas group, no Calendar row, the lists stay');
    check(await ev(`!/Calendar/.test(document.querySelector('#side .sg-views')?.textContent || '')`), '#2622: Views without the calendar');
    check(await ev(`document.querySelector('#side [data-go="l/${L}"]')?.classList.contains('on')`), 'the list is marked in the panel');
    await shot('p21522a-tasks-panel-light.png');
    await click(ev, '#srail [data-sbb="office"]');
    check(await ready(ev, `location.hash.startsWith('#office/') && !!document.querySelector('#srail [data-sbb="office"].on') && !!document.querySelector('#side [data-ofm]')`, 60), '#2622: the office icon opens panel AND page ' + await ev('location.hash'));
    check(await ev(`location.hash === '#office/offers'`), '#2622: the office opens on its page used last');
    await click(ev, '#srail [data-sbb="tasks"]');
    check(await ready(ev, `location.hash === '#l/${L}' && !!document.querySelector('#side .sg-lists') && !!document.querySelector('#srail [data-sbb="tasks"].on')`, 60), '#2622: back on Tasks: the list that was open ' + await ev('location.hash'));
    await click(ev, '#srail [data-sbb="cal"]');
    check(await ready(ev, `location.hash === '#cal' && !!document.querySelector('.calbar .seg [data-k="month"]') && !document.querySelector('#side').getClientRects().length`, 60), '#2622: the calendar: own icon; 2.224.0 (#2817): its views only as tabs on top, no panel');
    await click(ev, '.calbar .seg [data-k="week"]');
    check(await ready(ev, `!!document.querySelector('.calbar .seg button.on[data-k="week"]')`, 20), '#2622: a view tab switches the calendar');  // 2.224.0 (#2817): the tab on top
    await click(ev, '.calbar .seg [data-k="month"]');
    await sleep(400); await shot('p2224a-cal-light.png');  // 2.224.0 (#2817)

    // keys: up / down inside the panel, the bar is one stop of its own
    await click(ev, '#srail [data-sbb="tasks"]');
    await ready(ev, `!!document.querySelector('#side .sg-lists')`, 40);
    const down = await ev(`(() => { const a = [...document.querySelectorAll('#side .srow')].find(b => b.offsetParent); a.focus(); a.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true, cancelable: true})); const b = document.activeElement; return b !== a && b.closest('#side') && !b.closest('#srail') ? 1 : 0; })()`);
    check(down === 1, '#2622: ArrowDown moves to the next row of the panel');
    const rail = await ev(`(() => { const b = document.querySelector('#srail [data-sbb="tasks"]'); b.focus(); b.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true, cancelable: true})); return document.activeElement?.dataset?.sbb || ''; })()`);
    check(rail === 'cal', '#2622: ArrowDown in the bar = the next icon ' + rail);

    // ================= #2618 Time; 2.224.0 (#2817): no panel, its parts as tabs on top
    await click(ev, '#srail [data-sbb="time"]');
    check(await ready(ev, `location.hash === '#time' && !!document.querySelector('#view .mgtabs [data-go="time"][aria-selected="true"]') && !!document.querySelector('#view .mgtabs [data-go="pomo"]') && !document.querySelector('#side').getClientRects().length`, 60), '#2817: Time: time tracking + focus timer as tabs, no panel');
    check(await ev(`document.querySelector('#top h1')?.textContent === 'Time tracking'`), '#2618: the header names the part ' + await ev(`document.querySelector('#top h1')?.textContent`));
    await shot('p2224a-time-light.png');  // 2.224.0 (#2817)
    await click(ev, '#view .mgtabs [data-go="pomo"]');
    check(await ready(ev, `location.hash === '#pomo' && !!document.querySelector('#view .mgtabs [data-go="pomo"].on') && !!document.querySelector('#srail [data-sbb="time"].on')`, 40), '#2817: the focus timer from its tab, the icon stays lit');
    await click(ev, '#srail [data-sbb="review"]');
    await ready(ev, `location.hash === '#review'`, 40);
    await click(ev, '#srail [data-sbb="time"]');
    check(await ready(ev, `location.hash === '#pomo'`, 40), '#2618: Time comes back on the focus timer (its page used last)');

    // ================= a phone: no bar
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await nav(B + '#time');
    check(await ready(ev, `!!document.querySelector('#view .mgtabs')`, 60), 'phone: the tabs of Time stay');
    check(await ev(`!document.querySelector('#srail')?.getClientRects().length && !document.querySelector('#app.sb-b')`), 'phone: no bar');
  }, false);

  console.log(`p21522_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
