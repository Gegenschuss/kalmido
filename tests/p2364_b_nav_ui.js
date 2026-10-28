// kalmido-suite: fresh
// 2.364.0 B UI tests "navigation" (own container, start.sh, jsdom, invented names only):
// - #3018: Office & finance off -> the area is called "Contacts" with the contacts icon (bar, palette); the contacts page offers
//   "Quotations and invoices? Turn on Office & finance" with a switch that turns it on; the clients' module text says "only
//   within your organisation" only to people in an organisation
// - #3031: Start is the first icon of the bar (own icon, not the house) and of the phone's drawer row; the app opened without a
//   page lands on Start, Settings > General "Open the app on" Basket lands in the basket; Today without the briefing card while
//   Start is in the bar (with Start hidden it comes back); the evening review only from the account's second week
// - #3040 (Firefox, touch): 820 and 768 px wide = the computer layout (bar of the areas, no tab bar, nothing sideways, a task
//   opens next to the list); 760 / 690 = the phone; "More" = the drawer's list of areas (names and order), Settings last;
//   the drawer's area icons as a grid of rows (no swiping row); the team chat has one name
// freelancer-matrix: contacts -- fiona has no organisation (her own admin), alice is the org admin.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p2364_b_nav_ui', check: (c, w) => check(c, w), shots: 'P2364B_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2364B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { let x = null; try { x = await fn(); } catch { /* not there yet */ } if (x) return x; await sleep(150); } try { return await fn(); } catch { return null; } };
const NOOFFICE = 'cal,collab,comments,contacts,clients';
const fs = require('fs');
const sql = q => { const [DBC, DBN] = fs.readFileSync(path.join(DATA, '.kalmido-db'), 'utf8').trim().split(/\s+/); return execFileSync('docker', ['exec', DBC, 'psql', '-U', 'kalmido', '-d', DBN, '-Atqc', q]).toString(); };
const day = n => require('./testclock').day(n);
const feats = async ck => ((await call('GET', '/api/state', null, ck)).settings || {}).features || '';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const ACK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']}, ACK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: NOOFFICE}, ACK);
  const FID = (await call('POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123'}, ACK)).id;  // no orgs = a freelancer
  check(!!FID, 'setup: fiona without an organisation');
  const FCK = await login('fiona', undefined, {startPage: null});  // her own start page (default Start)
  check(((await call('GET', '/api/state', null, FCK)).settings || {}).start_page === 'home', '#3031: a new account opens on Start (start_page home)');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: NOOFFICE}, FCK);

  // ================= #3018 Office & finance off: the area is "Contacts"
  {
    const w = await boot({user: 'fiona', hash: 'contacts', startPage: null}), d = w.document;
    const bar = await until(() => d.querySelector('#srail .srb[data-sbb="office"]'));
    check(bar?.querySelector('.srbn')?.textContent === 'Contacts', '#3018 fiona: the bar entry is called Contacts: ' + bar?.querySelector('.srbn')?.textContent);
    const icIs = (el, name) => { const t = d.createElement('div'); t.innerHTML = w.eval(`ic(${JSON.stringify(name)})`); return !!el?.querySelector('svg') && el.querySelector('svg').innerHTML === t.querySelector('svg')?.innerHTML; };
    check(icIs(bar, 'users') && !icIs(bar, 'receipt'), '#3018 fiona: the bar entry has the contacts icon');
    const pal = w.eval(`mg_nameKey(mg_area('office'))`);
    check(pal === 'Contacts', '#3018 fiona: one name for the area everywhere (mg_nameKey) ' + pal);
    const hint = await until(() => d.querySelector('#view .ct18'));
    check(hint && /Quotations and invoices\?/.test(hint.textContent) && /Turn on Office & finance/.test(hint.textContent), '#3018 fiona: the contacts page offers Office & finance');
    // the clients' text in Settings > Modules: no "only within your organisation" without an organisation
    w.eval(`settingsModal('modules')`);
    const row = await until(() => d.querySelector('.smodal [data-modrow="clients"]'));
    check(row && /Clients above the projects/.test(row.textContent) && !/only within your organisation/.test(row.textContent), '#3018 fiona: the clients text without "only within your organisation"');
    d.querySelector('.smodal [data-m="close"], .smodal .mclose')?.click();
    for (const m of d.querySelectorAll('.smodal')) m.remove();
    // the switch turns Office & finance on and opens the office
    const sw = hint?.querySelector('[data-ct18on]');
    if (sw) { sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true})); }
    check(await until(async () => (await feats(FCK)).split(',').includes('office')), '#3018 fiona: the switch turns Office & finance on');
    check(await until(() => /^#office/.test(w.location.hash)), '#3018 fiona: then the office opens: ' + w.location.hash);
    check(await until(() => d.querySelector('#srail .srb[data-sbb="office"] .srbn')?.textContent === 'Office'), '#3018 fiona: on again the entry is called Office');
    check(await until(() => !d.querySelector('.ct18')), '#3018 fiona: no hint while the office is on');
    w.close();
  }
  {
    // alice is in an organisation: her clients text keeps the note; hiding the hint keeps it hidden
    const w = await boot({user: 'alice', hash: 'contacts'}), d = w.document;
    const hint = await until(() => d.querySelector('#view .ct18'));
    check(!!hint, '#3018 alice: the hint is there for the org admin too');
    hint?.querySelector('[data-ct18x]')?.click();
    check(await until(() => !d.querySelector('.ct18')) && w.localStorage.getItem('tasks.ct18Hide') === 'true', '#3018 alice: "Hide" hides the hint on this device');
    w.eval(`settingsModal('modules')`);
    const row = await until(() => d.querySelector('.smodal [data-modrow="clients"]'));
    check(/only within your organisation/.test(row?.textContent || ''), '#3018 alice: in an organisation the clients text keeps "only within your organisation"');
    w.close();
  }

  // ================= #3031 Start visible, the start page, Today's cards
  {
    await call('POST', '/api/tasks', {title: 'Send the offer', list_id: (await call('GET', '/api/state', null, FCK)).lists.find(l => l.is_inbox).id, due: day(-1)}, FCK);
    // a fresh start without a page in the address: Start (startPage: null = the account's own setting, default Start)
    let w = await boot({user: 'fiona', startPage: null, ls: {'tasks.lastKey': '"today"'}}), d = w.document;
    check(await until(() => w.location.hash === '#home' && w.eval('S.route.mod') === 'home'), '#3031 fiona: the app opens on Start: ' + w.location.hash);
    const first = await until(() => d.querySelector('#srail .srbs [data-sbb]'));
    check(first?.dataset.sbb === 'home' && first.querySelector('.srbn')?.textContent === 'Start', '#3031 fiona: Start is the first icon of the bar: ' + first?.dataset.sbb);
    check(first?.classList.contains('on') && first.getAttribute('aria-current') === 'page', '#3031 fiona: Start is marked as the open area');
    const icOf = name => { const t = d.createElement('div'); t.innerHTML = w.eval(`ic(${JSON.stringify(name)})`); return t.querySelector('svg')?.innerHTML; };
    check(first?.querySelector('svg')?.innerHTML === icOf('start') && icOf('start') !== icOf('home'), '#3031 fiona: Start has its own icon, not the house');
    check(await until(() => d.querySelector('#view .dgrid')), '#3031 fiona: the Start page is drawn');
    // Today: no briefing card while Start is in the bar
    w.location.hash = '#today';
    check(await until(() => w.eval('S.route.key') === 'today' && /Send the offer/.test(d.querySelector('#view')?.textContent || '')), '#3031 fiona: Today is open with its overdue task');
    await sleep(500);  // the briefing would come with the next drawing (its request); its absence is the point here
    check(!d.querySelector('#view .bfcard'), '#3031 fiona: Today without the briefing card while Start is in the bar');
    // Settings > General: open the app on the basket
    w.eval(`settingsModal('general')`);
    const sel = await until(() => d.querySelector('.smodal #s-startpg'));
    check(sel && [...sel.options].map(o => o.value).join() === 'home,inbox,today,last' && sel.value === 'home', '#3031 fiona: Settings > General "Open the app on", Start by default');
    if (sel) { sel.value = 'inbox'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); }
    check(await until(async () => ((await call('GET', '/api/state', null, FCK)).settings || {}).start_page === 'inbox'), '#3031 fiona: the choice is saved to the account');
    w.close();
    w = await boot({user: 'fiona', startPage: null}); d = w.document;
    check(await until(() => w.location.hash === '#inbox' && w.eval('S.route.key') === 'inbox'), '#3031 fiona: "Basket" opens the basket: ' + w.location.hash);
    w.close();
    check((await call('PATCH', '/api/settings', {start_page: 'nowhere'}, FCK)).status === 400, '#3031: an unknown start page is refused');
    // Start hidden in the bar: Today shows the briefing again; a young account: no evening review, an older one: the review
    await call('PATCH', '/api/settings', {sidebar: JSON.stringify({hidden: ['e:home']}), work_start: '00:00', work_end: '00:01'}, FCK);
    w = await boot({user: 'fiona', hash: 'today', startPage: null}); d = w.document;
    check(await until(() => d.querySelector('#view .bfcard')), '#3031 fiona: Start hidden -> Today shows the briefing');
    check(!d.querySelector('#srail [data-sbb="home"]'), '#3031 fiona: Start hidden -> not in the bar');
    check(await until(() => w.eval('!!S.dayplan')) && !d.querySelector('#view .rvcard:not(.bfcard)'), '#3031 fiona: an account of today: no evening review on Today');
    w.close();
    sql(`UPDATE users SET created_at='2025-01-01T00:00:00Z' WHERE id=${FID}`);
    w = await boot({user: 'fiona', hash: 'today', startPage: null}); d = w.document;
    check(await until(() => d.querySelector('#view .rvcard:not(.bfcard)')), '#3031 fiona: from the second week on: the evening review on Today ' + JSON.stringify(w.eval('({since: S.me.since, dp: !!S.dayplan, rv: S.review.day, d: !!S.review.data, t: S.review.data && Object.keys(S.review.data)})')));
    w.close();
    // the phone: Start first in the drawer's row of area icons
    w = await boot({user: 'alice', mobile: true, hash: 'inbox'}); d = w.document;
    await until(() => d.querySelector('#top .menu'));
    w.eval(`sideDrawerOpen()`);
    const row = await until(() => d.querySelector('#side .sbmr .srb[data-sbb]'));
    check(row?.dataset.sbb === 'home', '#3031 alice phone: Start first in the drawer row: ' + row?.dataset.sbb);
    w.close();
  }

  // ================= #3040 the computer layout from 768 px, "More" = the drawer's areas
  {
    const MANY = 'cal,collab,comments,contacts,clients,office,time,pomo,review,stats,family,contracts,home,reading,feeds,files,docs,wiki,sheets,habits,agents';
    await call('PATCH', '/api/settings', {features: MANY, start_page: 'today'}, ACK);
    const P = (await call('POST', '/api/lists', {name: 'Website relaunch'}, ACK)).id;
    const T = (await call('POST', '/api/tasks', {title: 'Collect the texts', list_id: P}, ACK)).id;
    await firefox(async o => {
      const {cmd, ev, ctx, nav, shot} = o;
      const wait = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(200); } return false; };
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, '#3040 ff: login');
      const LAYOUT = `(() => { const v = el => !!el && el.getClientRects().length > 0 && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden';
        return {w: innerWidth, mob: isMobile(), rail: v(document.querySelector('#srail .srb[data-sbb]')), tabs: v(document.querySelector('#tabs')) && document.querySelector('#tabs').offsetHeight > 0, side: v(document.querySelector('#side')) && !document.querySelector('#app').classList.contains('side-rail'), sideways: document.documentElement.scrollWidth - innerWidth}; })()`;
      for (const [vw, vh] of [[820, 1180], [768, 1024]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        await nav(B + '#l/' + P);
        check(await wait(`!!S.booted && !!document.querySelector('#view .trow') && !!document.querySelector('#srail .srb[data-sbb]')`), `#3040 ${vw}: the project is open`);
        const L = await ev(LAYOUT);
        check(L.w === vw && !L.mob && L.rail && !L.tabs && L.sideways <= 0, `#3040 ${vw}: the computer layout (bar of the areas, no tab bar, nothing sideways) ` + JSON.stringify(L));
        await ev(`(() => { openDetail(${T}); return 1; })()`);
        check(await wait(`!!document.querySelector('#detail .dtop') && document.querySelector('#app').classList.contains('detail-open')`), `#3040 ${vw}: a task opens`);
        await sleep(400);
        const D = await ev(`(() => { const d = document.querySelector('#detail').getBoundingClientRect(), l = document.querySelector('#view').getBoundingClientRect(); return {dl: Math.round(d.left), dr: Math.round(d.right), dw: Math.round(d.width), lw: Math.round(l.width), lr: Math.round(l.right), sideways: document.documentElement.scrollWidth - innerWidth}; })()`);
        check(D.dr <= vw + 1 && D.dw >= 280 && D.lw >= 280 && D.sideways <= 0, `#3040 ${vw}: the task panel fits next to the list ` + JSON.stringify(D));
        await shot(`p2364b-${vw}-task.png`);
        await ev(`(() => { if (typeof closeDetail === "function") closeDetail(); return 1; })()`); await sleep(300);
        await nav(B + '#home'); await wait(`!!document.querySelector('#view .dgrid')`);
        await shot(`p2364b-${vw}-start.png`);
      }
      // below 768: the phone
      for (const vw of [760, 690]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 1000}});
        await nav(B + '#today'); await wait(`!!S.booted && !!document.querySelector('#tabs button')`);
        const L = await ev(LAYOUT);
        check(L.mob && L.tabs && !L.rail, `#3040 ${vw}: the phone layout (tab bar, no bar of the areas) ` + JSON.stringify(L));
      }
      // "More" = the drawer's list of areas, Settings last
      await ev(`(() => { tabsMore(document.querySelector('#tabs [data-act="tabs-more"]') || document.querySelector('#top h1')); return 1; })()`);
      check(await wait(`!!document.querySelector('#pop [role="menuitem"]')`), '#3040 690: "More" opens');
      const M = await ev(`(() => { const g = document.querySelector('#pop .mgrp[aria-label="Areas"]'), all = [...document.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
        return {areas: g ? [...g.querySelectorAll('[role="menuitem"]')].map(b => b.textContent.trim()) : [], last: all[all.length - 1], all}; })()`);
      await ev(`(() => { closePop(); return 1; })()`); await sleep(200);
      await ev(`(() => { sideDrawerOpen(); renderSide(); return 1; })()`);
      check(await wait(`!!document.querySelector('#side.open .sbmr .srb[data-sbb]')`), '#3040 690: the drawer opens');
      await sleep(400);
      const G = await ev(`(() => { const r = document.querySelector('#side .sbmr'), bs = [...r.querySelectorAll('.srb[data-sbb]')], R = el => el.getBoundingClientRect();
        return {names: bs.map(b => b.querySelector('.srbn').textContent.trim()), rows: new Set(bs.map(b => Math.round(R(b).top))).size, swipe: r.scrollWidth > r.clientWidth + 1, inside: bs.every(b => R(b).right <= R(r).right + 1), minH: Math.min(...bs.map(b => R(b).height)),
          team: (document.querySelector('#side .sbmsg .n') || {}).textContent || ''}; })()`);
      check(M.areas.length >= 8 && M.areas.join('|') === G.names.join('|'), '#3040 690: "More" lists exactly the drawer\'s areas, same order ' + JSON.stringify({more: M.areas, drawer: G.names}));
      check(M.areas[0] === 'Start' && M.areas.includes('Knowledge') && M.areas.includes('Tables'), '#3040 690: Start, Knowledge and Tables are in "More" ' + M.areas.join('|'));
      check(M.last === 'Settings', '#3040 690: Settings is the last entry of "More" ' + M.all.join('|'));
      check(G.rows >= 2 && !G.swipe && G.inside && G.minH >= 43, '#3040 690: the drawer\'s area icons as a grid of rows, nothing to swipe ' + JSON.stringify(G));
      check(!G.team || G.team === 'Team chat', '#3040 690: the team chat is called Team chat in the drawer: ' + G.team);
      await shot('p2364b-690-drawer.png');
    }, true);
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
