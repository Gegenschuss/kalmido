// 2.98.0 part C UI tests, own container (start.sh), Firefox. Invented people and companies only.
// #2180 the office rail (variant A): on a computer a second column left of the page with the groups Sell, Money,
// Administration as small caps headings and their points below each other (15 rem at 1280 px, 12 rem at 1024 px, the
// page still wide enough), the active point with aria-current, up / down / Home / End inside the rail, the page's own
// heading .ofpt, the path on a detail page (2.152.2 #2617: the rail is gone, its points sit in the panel #side, the keys
// are the sidebar's); Settings has the tabs General | Templates (services, text blocks, their old
// routes lead there); the small caps readable in the light theme (4.5:1). Phone 402 px: the start page lists the groups in
// one column, a sub page has the way back "< Office · group" first and the group's points as ONE row of tabs (no wrap,
// the active one in sight, left / right). A person without an organisation (her own admin, P4) is the main person here.
// #2181 tables: the frame's grip (drag, keys, double click = automatic), the size per table after reloading, empty
// columns / rows fill the frame and typing into one adds it (one undo step), "Open in its own window" (no sidebar, a change
// there shows in the main window), full screen; a phone shows none of it.
// P298C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p298_c_ui', check, shots: 'P298C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P298C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,sheets';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  for (const ck of [CA, CC]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');
  const os = await call(CC, 'GET', '/api/office/settings');
  check(os.http === 200 && os.role === 'admin' && os.personal, 'P4: carol is the admin of her own office');
  const cl = await call(CC, 'POST', '/api/clients', {name: 'Example Ltd'});
  check(cl.id > 0, 'a client of carol');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  const key = (ev, k) => ev(`(() => { const a = document.activeElement; a.dispatchEvent(new KeyboardEvent('keydown', {key: '${k}', bubbles: true, cancelable: true})); return document.activeElement?.dataset?.ofm || ''; })()`);
  const noSide = `document.documentElement.scrollWidth <= window.innerWidth + 1`;
  const theme = (ev, t) => ev(`(() => { localStorage.setItem('tasks.theme', '"${t}"'); return 1; })()`);
  // the contrast of the small caps against the page (WCAG relative luminance)  // 2.152.2 (#2617): the group headings in #side
  const contrast = `(() => { const rgb = s => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(Number); const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * r + .7152 * g + .0722 * b; };
    const h = document.querySelector('#side [data-ofmg] .sgt > span:not(.c)'); let el = h, bg = 'rgba(0, 0, 0, 0)'; while (el && /rgba\\(0, 0, 0, 0\\)|transparent/.test(bg)) { bg = getComputedStyle(el).backgroundColor; el = el.parentElement; }
    if (/rgba\\(0, 0, 0, 0\\)|transparent/.test(bg)) bg = getComputedStyle(document.body).backgroundColor;
    const a = lum(rgb(getComputedStyle(h).color)), b = lum(rgb(bg)); return Math.round((Math.max(a, b) + .05) / (Math.min(a, b) + .05) * 100) / 100; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`); await theme(ev, 'light');
    check(await signIn(ev, 'carol') === 200, 'carol signs in');
    // ================= #2180 computer 1280
    await nav(B + '#office/offers');
    check(await ready(ev, `!document.querySelector('#view .ofrail') && !!document.querySelector('#view .ofwrap > .ofbody') && !!document.querySelector('#side .sbbp[data-ofmg]') && typeof OFC === 'object' && !!OFC.info`, 80), '#2180: the points in the panel left of the page');  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    const pts = await ev(`[...document.querySelectorAll('#side .sbbp[data-ofmg]')].map(g => g.dataset.ofmg + ':' + [...g.querySelectorAll('[data-ofm]')].map(b => b.dataset.ofm).join('+')).join(' ')`);  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    // 2.161.2 (#2616): Documents follow Quotes & invoices
    // 2.153.0 (#2028): + letters (tab Correspondence) at the end of 'sell'
    check(pts === 'sell:pipeline+offers+gendocs+clients+contacts+contracts+letters money:cashflow+kpi+bank+books+subs+travel+meals+cashbook admin:equipment+agreements+settings', '#2180: groups and points in order (P4: all of them) ' + pts);  // 2.121.0 (#2095): + cashbook under Money  // 2.119.0 (#2288): + meals (entertainment receipts) under Money
    check(await ev(`[...document.querySelectorAll('#side [data-ofmg] .sgt > span:not(.c)')].map(h => h.textContent.trim()).join('|') === 'Sell|Money|Administration' && document.querySelectorAll('#side [data-ofmg] .sgt[data-act="sbb-group"]').length === 3`), '#2180: three small caps headings (each folds)');  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    check(await ev(`(() => { const n = document.querySelector('#side'), b = document.querySelector('#srail'); return document.querySelector('#side h2.sbbpt')?.textContent === 'Office' && b?.tagName === 'NAV' && b.getAttribute('aria-label') === 'Areas' && [...n.querySelectorAll('[data-ofm]')].every(b => b.tagName === 'BUTTON' && !b.getAttribute('role')); })()`), '#2180: the panel "Office" of buttons (the bar a nav "Areas"), no tabs');  // 2.152.2 (#2617 #2622): the panel + the bar
    check(await ev(`(() => { const on = [...document.querySelectorAll('#side [aria-current="page"]')]; return on.length === 1 && on[0].dataset.ofm === 'offers' && on[0].classList.contains('on'); })()`), '#2180: the active point (aria-current)');  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    check(await ev(`document.querySelector('#view .ofbody > .ofpt')?.textContent === 'Quotes & invoices' && !document.querySelector('#view .ofmcrumb')`), '#2180: the page heading, no path on a list page');
    // 2.152.2 (#2617 #2622): no rail width / sticky rail any more: the page starts right of the panel, the bar marks the area
    check(await ev(`(() => { const b = document.querySelector('#view .ofwrap > .ofbody').getBoundingClientRect(), p = document.querySelector('#side').getBoundingClientRect(); return b.left >= p.right - 1 && document.querySelector('#srail [data-sbb="office"]')?.getAttribute('aria-current') === 'page'; })()`), '#2180: the page right of the panel, the bar marks Office');  // 2.152.2 (#2617 #2622)
    check(await ev(noSide), '#2180 1280: nothing sticks out to the side');
    const cr = await ev(contrast);
    check(cr >= 4.5, '#2180: the small caps have 4.5:1 in the light theme ' + cr);
    console.log('p298_c_ui: contrast of the small caps (light) ' + cr);
    await shot('p298c-desktop-1280-light.png');
    // the keys inside the panel (2.152.2 #2617: the sidebar's roving: Home = the panel's first button, End = its last point)
    await ev(`(() => { document.querySelector('#side [data-ofm]').focus(); return 1; })()`);  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    check(await key(ev, 'ArrowDown') === 'offers', '#2180: ArrowDown = the next point');
    check(await key(ev, 'ArrowUp') === 'pipeline', '#2180: ArrowUp = the point before');
    check(await key(ev, 'End') === 'settings', '#2180: End = the last point');
    check(await key(ev, 'ArrowUp') === 'agreements', '#2180: ArrowUp from the last point = the one before');  // 2.152.2 (#2617): Home leaves the office points (the panel's first button)
    check(await ev(`location.hash === '#office/offers'`), '#2180: the keys only move the focus');
    // Settings: General | Templates (services and text blocks; their old routes lead there)
    await click(ev, '#side [data-ofm="settings"]');  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    check(await ready(ev, `location.hash === '#office/settings' && !!document.querySelector('.office .ofrseg [data-go="office/settings"][aria-selected="true"]') && !!document.querySelector('#ofc-set')`, 60), '#2180: Settings opens on General');
    check(await ev(`!document.querySelector('#side [data-ofm="services"],#side [data-ofm="texts"]')`), '#2180: services and text blocks are no points of the rail');  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    await click(ev, '.office .ofrseg [aria-selected="false"]');
    check(await ready(ev, `location.hash === '#office/services' && !!document.querySelector('.office[data-ofctab="services"] .ofrseg2 [data-go="office/services"][aria-selected="true"]') && document.querySelector('#side [data-ofm][aria-current="page"]')?.dataset.ofm === 'settings'`, 60), '#2180: the tab Templates = services, the rail stays on Settings');  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    await click(ev, '.office .ofrseg2 [data-go="office/texts"]');
    check(await ready(ev, `location.hash === '#office/texts' && !!document.querySelector('.office[data-ofctab="texts"] .ofrseg [aria-selected="true"]') && document.querySelector('.office .ofrseg [aria-selected="true"]').dataset.go === 'office/texts'`, 60), '#2180: Templates > Text blocks');
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('.office .ofrseg [data-go="office/texts"]')`, 60), '#2180: Templates opens the one used last');
    await nav(B + '#office/services');
    check(await ready(ev, `!!document.querySelector('.office[data-ofctab="services"] .ofrseg2') && document.querySelector('#view .ofbody > .ofpt')?.textContent === 'Settings'`, 60), '#2180: the old route #office/services leads into the tab');
    // the path of a detail page instead of the heading
    await nav(B + '#client/' + cl.id);
    check(await ready(ev, `!!document.querySelector('#view .ofbody > .ofmcrumb')`, 60), '#2180: the path on a client, inside the page column');
    check(await ev(`!document.querySelector('#view .ofpt') && document.querySelector('#side [data-ofm][aria-current="page"]')?.dataset.ofm === 'clients'`), '#2180: no heading on a detail page, the rail marks Clients');  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    // dark theme
    await theme(ev, 'dark'); await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('#side [data-ofmg]') && !!OFC.info`, 60); await sleep(500);  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    check(await ev(contrast) >= 4.5, '#2180: the small caps have 4.5:1 in the dark theme too');
    await shot('p298c-desktop-1280-dark.png');
    // ================= #2180 computer 1024: the page still wide enough (2.152.2 #2617: no rail)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1024, height: 800}});
    await theme(ev, 'light'); await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('#side [data-ofmg]') && !!OFC.info`, 60); await sleep(600);  // // 2.152.2 (#2617): the office points sit in the panel #side, no rail in the page
    const m = JSON.parse(await ev(`JSON.stringify({rail: !!document.querySelector('#view .ofrail'), body: Math.round(document.querySelector('#view .ofbody').getBoundingClientRect().width), side: !!document.querySelector('#side') && document.querySelector('#side').getBoundingClientRect().width})`));  // 2.152.2 (#2617): rail = a rail left in the page (there is none)
    console.log('p298_c_ui: 1024 px - rail / page / sidebar ' + JSON.stringify(m));  // 2.152.2 (#2617): rail = still a rail in the page (none)
    check(!m.rail, '#2180 1024: no rail in the page, the points sit in the panel ' + JSON.stringify(m));  // 2.152.2 (#2617): no rail width any more
    // with the main sidebar open (15 rem) 722 px are left for rail + page: a 12 rem rail leaves ~506 px (560 would need a
    // narrower rail); the quotations' search, filter and kinds still fit
    check(m.body >= 500, '#2180 1024: the page column is at least 500 px wide ' + JSON.stringify(m));
    check(await ev(noSide), '#2180 1024: no scrolling sideways');
    await shot('p298c-desktop-1024.png');
    // ================= #2180 phone 402
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await nav(B + 'static/icon.svg'); await nav(B + '#office');
    check(await ready(ev, `document.querySelectorAll('#view .ofmstart .ofl .oflg').length === 3`, 80), '#2180 phone: the start page lists three groups');
    check(await ev(`!document.querySelector('#view .ofrail') && !document.querySelector('#view .ofpb') && !document.querySelector('#view .ofmtiles')`), '#2180 phone: the list is the menu, no tiles');
    check(await ev(`(() => { const rs = [...document.querySelectorAll('#view .oflc .oflr')], l = new Set(rs.map(b => Math.round(b.getBoundingClientRect().left))), w = new Set(rs.map(b => Math.round(b.getBoundingClientRect().width))); return rs.length === 18 && l.size === 1 && w.size === 1 && rs.every(b => b.getBoundingClientRect().height >= 45); })()`), '#2180 phone: one column, 18 rows of at least 2.875 rem');  // 2.121.0 (#2095): + cashbook  // 2.119.0 (#2288): + meals (entertainment receipts) under Money  // 2.153.0 (#2028): + correspondence
    check(await ev(`[...document.querySelectorAll('#view .oflg h3')].map(h => h.textContent.trim()).join('|') === 'Sell|Money|Administration'`), '#2180 phone: the group headings');
    check(await ev(noSide), '#2180 phone: nothing sticks out to the side (start)');
    await shot('p298c-phone-start.png');
    await click(ev, '#view .oflc [data-ofm="subs"]');
    check(await ready(ev, `location.hash === '#office/subs' && !!document.querySelector('#view .ofpb .ofpts')`, 60), '#2180 phone: a row opens its page with the bar');
    await sleep(500);
    const pb = JSON.parse(await ev(`(() => { const bar = document.querySelector('#view .ofpb'), row = bar.querySelector('.ofpts'), ts = [...row.querySelectorAll('.ofpt2')], rb = row.getBoundingClientRect(), on = row.querySelector('.ofpt2.on').getBoundingClientRect();
      const first = [...bar.querySelectorAll('button,a,[tabindex]')].find(x => x.tabIndex >= 0);
      return JSON.stringify({n: ts.length, rows: new Set(ts.map(t => Math.round(t.getBoundingClientRect().top))).size, wrap: getComputedStyle(row).flexWrap, ox: getComputedStyle(row).overflowX, onSeen: on.left >= rb.left - 1 && on.right <= rb.right + 1,
        back: first?.classList.contains('ofpback') && first.dataset.go === 'office/start', label: bar.querySelector('.ofpback').textContent.trim(), sticky: getComputedStyle(bar).position, th: Math.min(...ts.map(t => t.getBoundingClientRect().height))}); })()`));
    check(pb.n === 8 && pb.rows === 1 && pb.wrap === 'nowrap' && pb.ox === 'auto', '#2180 phone: the eight points of Money in ONE row that scrolls ' + JSON.stringify(pb));  // 2.121.0 (#2095): + cashbook  // 2.119.0 (#2288): + meals (entertainment receipts) under Money
    check(pb.onSeen, '#2180 phone: the active tab is in sight ' + JSON.stringify(pb));
    check(pb.back && /^Office\s*·\s*Money$/.test(pb.label) && pb.sticky === 'sticky' && pb.th >= 43, '#2180 phone: the way back "Office · Money" first, sticky, large tabs ' + JSON.stringify(pb));
    check(await ev(noSide), '#2180 phone: nothing sticks out to the side (sub page)');
    await shot('p298c-phone-page.png');
    await ev(`(() => { document.querySelector('#view .ofpb .ofpt2.on').focus(); return 1; })()`);
    check(await key(ev, 'ArrowRight') === 'travel' && await key(ev, 'ArrowLeft') === 'subs' && await key(ev, 'Home') === 'cashflow', '#2180 phone: left / right / Home in the tab row');
    await click(ev, '#view .ofpb .ofpback');
    check(await ready(ev, `location.hash === '#office/start' && document.querySelectorAll('#view .oflg').length === 3`, 60), '#2180 phone: the way back leads to the start list');
  }, false);

  // ================= #2181 tables: the frame can be dragged (also empty), the size stays, empty cells fill it, typing into
  // one adds the column (one undo step), its own window (no sidebar, live into the main window), full screen; phone: none
  const E = await call(CC, 'POST', '/api/sheets', {title: 'Empty sheet', space: 'private'});
  const FS = await call(CC, 'POST', '/api/sheets', {title: 'Full sheet', space: 'private'});
  check(E.id > 0 && FS.id > 0 && (E.columns || []).length === 3 && (E.rows || []).length === 10, '#2181: two tables (3 columns, 10 rows)');
  const fcells = []; (FS.rows || []).forEach((r, i) => (FS.columns || []).forEach((c, j) => fcells.push({row_id: r.id, col_id: c.id, raw: String(i * 10 + j + 1)})));
  check((await call(CC, 'PUT', `/api/sheets/${FS.id}/cells`, {cells: fcells})).http === 200, '#2181: the full table filled');
  await firefox(async ({cmd, ev, ctx, nav, shot, drag}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`); await theme(ev, 'light');
    check(await signIn(ev, 'carol') === 200, '#2181: carol signs in');
    const open = async id => { await nav(B + '#sheets/' + id); const r = await ready(ev, `!!document.querySelector('#shv-scroll td.shvc') && SHV.sh?.id === ${id}`, 80); await sleep(900); return r; };
    const box = id => ev(`(() => { const b = document.querySelector('.shvsheet .shzbox'), r = b.getBoundingClientRect(), g = document.querySelector('#shz-grip')?.getBoundingClientRect();
      return JSON.stringify({w: Math.round(r.width), h: Math.round(r.height), set: !!b.dataset.shzset, gx: g ? g.left + g.width / 2 : 0, gy: g ? g.top + g.height / 2 : 0, gin: !!g && g.right <= r.right + 1 && g.bottom <= r.bottom + 1 && g.right >= r.right - 24 && g.bottom >= r.bottom - 24,
        pc: document.querySelectorAll('#shv-scroll thead th.shzph').length, pr: document.querySelectorAll('#shv-scroll tbody.shzrows tr').length, real: document.querySelectorAll('#shv-scroll td.shvc').length, ls: (LS.get('shzSize', {}) || {})[${id}] || null,
        side: document.querySelector('.shvside')?.getBoundingClientRect().width || 0}); })()`).then(JSON.parse);
    check(await open(E.id), '#2181: the empty table opens');
    const a = await box(E.id);
    check(a.gin && a.real === 30 && a.pc > 0 && !a.set, '#2181: the grip at the frame\'s corner, empty columns fill the frame (nothing created) ' + JSON.stringify(a));
    check(await ev(`!!document.querySelector('.shvtop [data-shz="win"]') && !!document.querySelector('.shvtop [data-shz="full"]') && document.querySelector('.shvtop [data-shv="deps"]').nextElementSibling?.dataset.shz === 'win'`), '#2181: both buttons next to "Dependencies"');
    await drag(a.gx, a.gy, -160, 160); await sleep(900);
    const b = await box(E.id);
    check(b.set && Math.abs(b.w - (a.w - 160)) <= 4 && Math.abs(b.h - (a.h + 160)) <= 4, '#2181: the empty table\'s frame dragged smaller and higher ' + JSON.stringify([a, b]));
    check(b.pr > 0 && b.real === 30, '#2181: empty rows fill the higher frame, no data created ' + JSON.stringify(b));
    check(b.ls && Math.abs(b.ls.w * 16 - b.w) <= 6 && Math.abs(b.ls.h * 16 - b.h) <= 6, '#2181: the size is kept for this table on this device ' + JSON.stringify(b.ls));
    check((await call(CC, 'GET', `/api/sheets/${E.id}`)).columns.length === 3, '#2181: still 3 columns on the server');
    await shot('p298c-sheet-empty-dragged.png');
    check(await open(E.id), '#2181: reopened');
    const c = await box(E.id);
    check(c.set && Math.abs(c.w - b.w) <= 2 && Math.abs(c.h - b.h) <= 2, '#2181: the size after reloading ' + JSON.stringify([b, c]));
    // keys on the grip: right = 1 rem wider, Home = automatic again
    await ev(`(() => { const g = document.querySelector('#shz-grip'); g.focus(); g.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true, cancelable: true})); return 1; })()`); await sleep(700);
    const d = await box(E.id);
    check(Math.abs(d.w - (c.w + 16)) <= 2 && Math.abs(d.h - c.h) <= 2, '#2181: ArrowRight on the grip = 1 rem wider ' + JSON.stringify([c.w, d.w]));
    await ev(`(() => { document.querySelector('#shz-grip').dispatchEvent(new MouseEvent('dblclick', {bubbles: true, cancelable: true})); return 1; })()`); await sleep(700);
    const e0 = await box(E.id);
    check(!e0.set && !e0.ls, '#2181: a double click on the grip = the automatic size ' + JSON.stringify(e0));
    // typing into an empty column adds it (and only it), one undo step
    await ev(`(() => { const td = document.querySelector('#shv-scroll tbody:not(.shzrows) td.shzph[data-shzc="0"]'); td.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true, button: 0, pointerType: 'mouse'})); return 1; })()`); await sleep(200);
    await ev(`(() => { document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {key: 'x', bubbles: true, cancelable: true})); return 1; })()`); await sleep(200);
    check(await ev(`document.activeElement?.id === 'shz-ed' && document.activeElement.value === 'x'`), '#2181: typing into an empty cell opens its field');
    await ev(`(() => { const i = document.getElementById('shz-ed'); i.value = 'Extra'; i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return 1; })()`);
    let s1 = null; for (let i = 0; i < 40; i++) { s1 = await call(CC, 'GET', `/api/sheets/${E.id}`); if ((s1.columns || []).length === 4) break; await sleep(250); }
    const d4 = s1.columns[3];
    check(s1.columns.length === 4 && (s1.cells || []).some(x => x.col_id === d4.id && x.raw === 'Extra' && x.row_id === s1.rows[0].id) && s1.rows.length === 10, '#2181: the column D was added with the value in row 1 ' + JSON.stringify({cols: s1.columns.length, rows: s1.rows.length}));
    check(await ready(ev, `[...document.querySelectorAll('#shv-scroll td.shvc')].some(td => /Extra/.test(td.textContent))`, 40), '#2181: the value shows in the grid');
    await ev(`histStep('undo')`);
    let s2 = null; for (let i = 0; i < 40; i++) { s2 = await call(CC, 'GET', `/api/sheets/${E.id}`); if ((s2.columns || []).length === 3) break; await sleep(250); }
    check(s2.columns.length === 3, '#2181: ONE undo step takes the column back');
    // the full table: the frame drags the same way
    check(await open(FS.id), '#2181: the full table opens ' + await ev(`JSON.stringify({h: location.hash, sh: SHV.sh?.id, err: SHV.err, v: (document.querySelector('#view')?.textContent || '').slice(0, 160)})`));
    const f = await box(FS.id);
    await drag(f.gx, f.gy, -120, 120); await sleep(900);
    const g = await box(FS.id);
    check(g.set && Math.abs(g.w - (f.w - 120)) <= 4 && Math.abs(g.h - (f.h + 120)) <= 4 && g.real === 30, '#2181: the full table\'s frame dragged ' + JSON.stringify([f, g]));
    check(await ev(`/^1$/.test(document.querySelector('#shv-scroll td.shvc')?.textContent.trim() || '')`), '#2181: the values stay');
    await shot('p298c-sheet-full.png');
    // its own window: /?mini=1#sheets/<id> without the sidebar, a change there shows in the main window
    const ctx2 = (await cmd('browsingContext.create', {type: 'window'})).context;
    const ev2 = async expr => { const r = await cmd('script.evaluate', {expression: expr, target: {context: ctx2}, awaitPromise: true, resultOwnership: 'none'}); return r.result?.value; };
    await cmd('browsingContext.navigate', {context: ctx2, url: B + '?mini=1#sheets/' + FS.id, wait: 'complete'});
    let solo = false; for (let i = 0; i < 80 && !solo; i++) { solo = await ev2(`!!document.querySelector('#shv-scroll td.shvc') && typeof SHV === 'object' && SHV.sh?.id === ${FS.id}`).catch(() => false); if (!solo) await sleep(250); }
    check(solo, '#2181: the table in its own window');
    check(await ev2(`document.documentElement.classList.contains('mini-sheet') && !document.querySelector('#side')?.getClientRects().length && !document.querySelector('[data-shz="win"]') && !document.querySelector('#shz-grip')`), '#2181: own window without sidebar, no window button, no grip');
    await ev2(`(() => { const r = SHV.sh.rows[0].id, c = SHV.sh.columns[1].id; return shvPut([{row_id: r, col_id: c, raw: 'From the window'}], 'x').then(() => 1); })()`);
    check(await ready(ev, `[...document.querySelectorAll('#shv-scroll td.shvc')].some(td => /From the window/.test(td.textContent))`, 160), '#2181: the change in the own window shows in the main window');
    await cmd('browsingContext.close', {context: ctx2}).catch(() => {});
    // full screen on and off
    await click(ev, '.shvtop [data-shz="full"]'); await sleep(500);
    check(await ev(`document.documentElement.classList.contains('shzfull') && !document.querySelector('#side').getClientRects().length && document.querySelector('.shvtop [data-shz="full"]').getAttribute('aria-pressed') === 'true'`), '#2181: full screen hides the sidebar');
    await click(ev, '.shvtop [data-shz="full"]'); await sleep(500);
    check(await ev(`!document.documentElement.classList.contains('shzfull') && !!document.querySelector('#side').getClientRects().length`), '#2181: and back');
    // phone: no buttons, no grip, no empty cells
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    check(await open(FS.id), '#2181 phone: the table opens');
    check(await ev(`!document.querySelector('[data-shz]') && !document.querySelector('#shz-grip') && !document.querySelector('#shv-scroll .shzph') && document.querySelectorAll('#shv-scroll td.shvc').length === 30`), '#2181 phone: no window / full screen buttons, no grip, the grid as before');
  }, false);

  console.log(`p298_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
