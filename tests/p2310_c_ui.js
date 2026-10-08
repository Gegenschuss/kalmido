// 2.31.0 UI tests, part C ("everyday phone": menus, search, sub-tabs), own container (start.sh). jsdom + Firefox:
// #1056 menus in groups: the list "…" (View / List headings, the rare entries in "More list options…", archive + delete last
//      and set apart), the task menu (Plan / Organize / Time / Structure, won't do + delete last; in the task panel without
//      date and priority, which its header has), the swipe menu (Snooze / Task), "More" in the tab bar (Views / Conversations);
//      every entry of before stays reachable; arrow keys skip headings and lines, → / ← open and leave the second level;
//      role="group" with aria-label, hr role="separator"
// #1057 one search on the phone: the tab "Search" opens the search (palette) with the focus in its field; with that tab the
//      header magnifier, the drawer's search field and the button next to the drawer are gone (without it they stay); the open
//      drawer leaves nothing behind it tappable; the tab "Lists" opens the drawer at the group Lists
// #1046 Settings > Agents on a phone: the sub-tabs keep their width (no overlap), the strip scrolls, the chosen one is in view
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2310_c_ui', check, shots: 'P2310C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team,notes,pomo';
// what the menus offered before 2.31 (flat): each of it must still be reachable (main level or the second level)
const LIST_BEFORE = ['Edit list…', 'Share…', 'Agent: Claude…', 'Agent access', 'Add section…', 'Shown fields…', 'Team chat', 'Move to folder…', 'Tasks from notes…', 'Notifications: Default', 'Hide progress', 'Archive', 'Delete…'];
const RARE = ['Agent access', 'Tasks from notes…', 'Notifications: Default', 'Hide progress'];

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const P = (await call('POST', '/api/lists', {name: 'Relaunch', kind: 'project'})).id;
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Weekly report', list_id: P, due: new Date().toISOString().slice(0, 10), repeat: 'FREQ=WEEKLY', priority: 3})).id;
  check(T1 > 0, 'a repeating task');
  await call('POST', '/api/tasks', {title: 'Second task', list_id: P});
  for (let i = 1; i <= 12; i++) await call('POST', '/api/lists', {name: 'List ' + String(i).padStart(2, '0')});  // a drawer taller than a phone

  // ================= jsdom: the list menu (#1056)
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  await until(() => d.querySelector('#top h1'));
  await sleep(400);
  const it = w.eval(`listMenuItems(${P})`);
  const flat = it.flatMap(x => x === '-' ? [] : x.more ? [x, ...x.more] : [x]).map(x => x.label).filter(Boolean);
  for (const lab of LIST_BEFORE) check(flat.includes(lab), `#1056 list menu: "${lab}" still reachable ` + flat.join('|'));
  const more = it.find(x => x.more);
  check(more && more.label === 'More list options…' && RARE.every(l => more.more.some(x => x.label === l)), '#1056 the rare entries sit in "More list options…" ' + (more ? more.more.map(x => x.label).join('|') : 'none'));
  check(RARE.every(l => !it.some(x => x.label === l)), '#1056 ... and not on the first level');
  const lab = it.map(x => x === '-' ? '-' : x.label);
  check(lab.slice(-3).join('|') === '-|Archive|Delete…', '#1056 archive + delete last, after a separator ' + lab.join('|'));
  // the header "…" of the list: View + List headings, in this order, danger last
  const top = w.eval('topMoreItems()');
  const heads = top.filter(x => x && x.head).map(x => x.head);
  check(heads.join('|') === 'View|List', '#1056 header "…": headings View, List ' + heads.join('|'));
  const tl = top.map(x => x === '-' ? '-' : x.head ? '#' + x.head : x.label);
  check(tl.indexOf('#View') < tl.indexOf('Sort…') && tl.indexOf('Sort…') < tl.indexOf('#List') && tl.indexOf('#List') < tl.indexOf('Edit list…'), '#1056 Sort… under View, Edit list… under List ' + tl.join('|'));
  check(tl.slice(-2).join('|') === 'Archive|Delete…' && tl[tl.length - 3] === '-', '#1056 header "…": archive + delete last, set apart');
  // rendered: groups with aria-label, separators, keyboard skips headings, → / ← for the second level
  w.eval(`menu(document.querySelector('#top [data-act="top-more"]'), topMoreItems())`);
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const grps = [...d.querySelectorAll('#pop .menu-list > [role="group"].mgrp')];
  check(grps.length === 2 && grps.map(g => g.getAttribute('aria-label')).join('|') === 'View|List' && grps.every(g => g.querySelector('.mgh[aria-hidden="true"]')), '#1056 rendered: two role=group with aria-label and a heading');
  check(d.querySelector('#pop hr[role="separator"]'), '#1056 rendered: the separator says role=separator');
  await sleep(50);
  const kd = k => d.activeElement.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true}));
  let allItems = true, n = d.querySelectorAll('#pop [role="menuitem"]:not([disabled])').length, seen = new Set();
  for (let i = 0; i < n + 2; i++) { kd('ArrowDown'); const a = d.activeElement; if (!a || a.getAttribute('role') !== 'menuitem') allItems = false; seen.add(a.textContent); }
  check(allItems && seen.size === n, `#1056 ↓ stops only on menu items (${seen.size} of ${n})`);
  const sub = d.querySelector('#pop .msubm');
  check(sub && sub.getAttribute('aria-haspopup') === 'menu' && /More list options/.test(sub.textContent), '#1056 "More list options…" marked as a second level');
  sub.focus(); kd('ArrowRight'); await sleep(50);
  let subTxt = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim());
  check(subTxt[0] === 'Back' && RARE.every(l => subTxt.includes(l)), '#1056 → opens the second level, "Back" on top ' + subTxt.join('|'));
  check(d.querySelector('#pop [role="group"]')?.getAttribute('aria-label') === 'More list options', '#1056 the second level has its heading');
  await sleep(20); kd('ArrowLeft'); await sleep(50);
  check(!!d.querySelector('#pop .msubm'), '#1056 ← goes back to the first level');
  d.querySelector('#pop .msubm').click(); await sleep(50);
  [...d.querySelectorAll('#pop [role="menuitem"]')].find(x => /Back/.test(x.textContent)).click(); await sleep(50);
  check(!!d.querySelector('#pop .msubm') && !d.querySelector('#pop').classList.contains('hidden'), '#1056 "Back" (a tap) goes back too');
  w.eval('closePop()');

  // ================= jsdom: the task menu (#1056): from the row: everything; from the panel: no date / priority
  const tmenu = async anchorJs => { w.eval(`taskMenu(${anchorJs}, ${T1})`); await until(() => d.querySelector('#pop [role="menuitem"]')); const x = {items: [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => (b.querySelector('.ml')?.firstChild?.textContent || b.textContent).trim()), heads: [...d.querySelectorAll('#pop .mgh')].map(h => h.textContent)}; w.eval('closePop()'); return x; };
  const row = await tmenu(`document.querySelector('#view .trow[data-id="${T1}"] .ttl') || document.querySelector('#top h1')`);
  check(row.heads.join('|') === 'Plan|Organize|Time|Structure', '#1056 task menu headings ' + row.heads.join('|'));
  check(row.items.includes('New date…') && row.items.includes('High') && row.items.includes('Today'), '#1056 task menu from the row: date + priority');
  check(row.items.slice(-2).join('|') === "Won't do (discard)|Delete", "#1056 won't do + delete last " + row.items.slice(-3).join('|'));
  w.eval(`openDetail(${T1})`);
  await until(() => d.querySelector('#detail .dtop [data-act="task-menu"]'));
  const pan = await tmenu(`document.querySelector('#detail .dtop [data-act="task-menu"]')`);
  check(!pan.items.includes('New date…') && !pan.items.includes('High') && !pan.items.includes('Today'), '#1056 task menu in the panel: no date / priority ' + pan.items.join('|'));
  check(d.querySelector('#detail .dtop [data-act="date"]') && d.querySelector('#detail .dtop [data-act="prio"]'), '#1056 ... the panel header has both');
  const lost = row.items.filter(x => !pan.items.includes(x) && !['New date…', 'Today', 'Tomorrow', 'High', 'Medium', 'Low', 'None', 'Move up', 'Move down'].includes(x));
  check(!lost.length, '#1056 the panel menu lost nothing else ' + lost.join('|'));
  check(pan.items.includes('Skip this occurrence') && pan.items.includes('Assign…'), '#1056 panel: skip + assign stay under Plan');
  // "More" in the tab bar: Views / Conversations, "Customize tab bar" last
  w.eval(`tabsMore(document.querySelector('#top h1'))`);
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const mh = [...d.querySelectorAll('#pop .mgh')].map(h => h.textContent), mi = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(mh[0] === 'Views' && mh.includes('Conversations') && mi[mi.length - 1] === 'Customize tab bar', '#1056 "More": groups ' + mh.join('|') + ' / ' + mi.join('|'));
  w.eval('closePop()');
  // #1057: the tab "Search" opens the palette (no page "Search")
  check(w.eval(`tabItem('search').act`) === 'palette', '#1057 the tab "Search" opens the search');
  w.close();

  // ================= Firefox: the real layout
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice', ls = '') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); ${ls} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const tap = async (o, sel) => {
    const p = await o.ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return null; const r = b.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
    if (!p) return false;
    await o.cmd('input.performActions', {context: o.ctx, actions: [{type: 'pointer', id: 't', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
    await o.cmd('input.releaseActions', {context: o.ctx}); return true;
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + P); await ready(ev);
    // #1057 one search: the tab, no magnifier in the header, no field in the drawer
    check(await ev(`document.body.classList.contains('tab-search') && !!document.querySelector('#tabs [data-act="palette"]')`), `${tag}: #1057 the tab "Search" is there`);
    check(await ev(`(() => { const b = document.querySelector('#top .cmdbar'); return !b || getComputedStyle(b).display === 'none'; })()`), `${tag}: #1057 no magnifier in the header`);
    // #1056 the list "…" as a sheet
    await tap(o, '#top [data-act="top-more"]'); await sleep(700);
    check(await ev(`document.querySelectorAll('#pop .mgrp').length === 2`), `${tag}: #1056 the list menu shows its groups`);
    await shot('p2310c-390-list-menu.png');
    await ev(`(() => { const s = document.querySelector('#pop'); s.scrollTop = s.scrollHeight; return 1; })()`); await sleep(200);
    await shot('p2310c-390-list-menu-end.png');
    await ev(`(() => { closePop(); return 1; })()`); await sleep(300);
    // the drawer: no search field, nothing behind it tappable (the header lies under the dimming)
    await tap(o, '#top [data-act="side"]'); await sleep(700);
    check(await ev(`(() => { const s = document.querySelector('#side .scmd'); return !s || getComputedStyle(s).display === 'none'; })()`), `${tag}: #1057 no search field in the drawer`);
    check(await ev(`(() => { const s = document.querySelector('#scrim .sidesearch'); return !s || getComputedStyle(s).display === 'none'; })()`), `${tag}: #1057 no search button next to the drawer`);
    const behind = await ev(`(() => { const out = []; for (const sel of ['#top .bell', '#top [data-act="top-more"]', '#top .cmdbar', '#tabs button']) { const b = document.querySelector(sel); if (!b) continue; const r = b.getBoundingClientRect(); if (!r.width) continue; const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); if (e && (e === b || b.contains(e))) out.push(sel); } return out; })()`);
    check(behind.length === 0, `${tag}: #1057 with the drawer open nothing behind it can be tapped ` + behind.join(','));
    await shot('p2310c-390-drawer.png');
    await ev(`(() => { closeSide(); return 1; })()`); await sleep(400);
    // the tab "Lists": the drawer starts at Lists
    await ev(`(() => { document.querySelector('#side').scrollTop = 0; return 1; })()`);
    await tap(o, '#tabs [data-act="side"]'); await sleep(800);
    const gtop = await ev(`(() => { const s = document.querySelector('#side'), g = document.querySelector('#side .sg-lists'); return g ? Math.round(g.getBoundingClientRect().top - s.getBoundingClientRect().top) : -1; })()`);
    check(gtop >= 0 && gtop < 60 && await ev(`document.querySelector('#side').scrollTop > 0`), `${tag}: #1057 the tab "Lists" opens the drawer at Lists (${gtop})`);
    await shot('p2310c-390-drawer-lists.png');
    await ev(`(() => { closeSide(); return 1; })()`); await sleep(400);
    // the tab "Search": the palette with the focus in its field
    await tap(o, '#tabs [data-act="palette"]'); await sleep(700);
    check(await ev(`!!document.querySelector('.palette') && document.activeElement === document.querySelector('.palette .pqin')`), `${tag}: #1057 the tab "Search" opens the search, the field has the focus`);
    await ev(`(() => { closePalette(); return 1; })()`); await sleep(300);
    // #1056 the swipe menu: Snooze / Task groups
    await o.nav(B + '#l/' + P); await ready(ev);
    const rp = await ev(`(() => { const r = document.querySelector('#view .trow[data-id="${T1}"]'); if (!r) return null; const b = r.getBoundingClientRect(); return {x: b.right - 40, y: b.top + b.height / 2}; })()`);
    if (rp) {
      await o.drag(rp.x, rp.y, -200, 0, 'touch'); await sleep(800);
      const sw = await ev(`[...document.querySelectorAll('#pop .mgh')].map(h => h.textContent).join('|') + ' / ' + [...document.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim()).slice(-1)[0]`);
      check(/^Snooze\|Task \/ Delete$/.test(sw), `${tag}: #1056 the swipe menu: Snooze / Task, delete last (${sw})`);
      await shot('p2310c-390-swipe.png');
      await ev(`(() => { closePop(); return 1; })()`);
    } else check(false, `${tag}: #1056 a row to swipe`);
    // #1056 the task panel on the phone: date and priority are in its header (visible), so its "…" leaves them out
    await ev(`(() => { openDetail(${T1}); return 1; })()`); await sleep(900);
    check(await ev(`['date', 'prio'].every(k => { const b = document.querySelector('#detail .dtop [data-act="' + k + '"]'); if (!b) return false; const r = b.getBoundingClientRect(); return r.width >= 24 && r.height >= 24 && r.right <= innerWidth && getComputedStyle(b).visibility !== 'hidden'; })`), `${tag}: #1056 date + priority visible in the panel header on the phone`);
    await tap(o, '#detail .dtop [data-act="task-menu"]'); await sleep(700);
    check(await ev(`!!document.querySelector('#pop .mgh') && ![...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /New date|High/.test(b.textContent))`), `${tag}: #1056 the panel's "…" without date / priority`);
    await shot('p2310c-390-task-menu.png');
    await ev(`(() => { closePop(); closeDetail?.(); return 1; })()`); await sleep(400);
    // #1046 Settings > Agents: the sub-tabs do not overlap, the strip scrolls, the chosen one is in view
    await ev(`(() => { settingsModal('agents'); return 1; })()`); await sleep(1200);
    const tabs = await ev(`(() => { const s = document.querySelector('.modal .aisub:not(.admsub)'); if (!s) return null; const bs = [...s.querySelectorAll('button')].map(b => { const r = b.getBoundingClientRect(); return {l: r.left, r: r.right, sw: b.scrollWidth, cw: b.clientWidth}; }); return {bs, sw: s.scrollWidth, cw: s.clientWidth}; })()`);
    if (tabs) {
      const over = tabs.bs.some((b, i) => i && b.l < tabs.bs[i - 1].r - 0.5), clip = tabs.bs.some(b => b.sw > b.cw + 1);
      check(tabs.bs.length >= 5 && !over && !clip, `${tag}: #1046 the agents' sub-tabs neither overlap nor clip ` + JSON.stringify(tabs.bs.map(b => Math.round(b.r - b.l))));
      await shot('p2310c-390-agents-tabs.png');
      await ev(`(() => { const b = [...document.querySelectorAll('.modal .aisub:not(.admsub) button')].pop(); b.click(); return 1; })()`); await sleep(700);
      const vis = await ev(`(() => { const s = document.querySelector('.modal .aisub:not(.admsub)'), b = s.querySelector('button.on'), sr = s.getBoundingClientRect(), br = b.getBoundingClientRect(); return {ok: br.left >= sr.left - 1 && br.right <= sr.right + 1, on: b.dataset.aisub, s: [sr.left, sr.right, s.scrollLeft], b: [br.left, br.right]}; })()`);
      check(vis.ok, `${tag}: #1046 the chosen sub-tab is scrolled into view ` + JSON.stringify(vis));
      await shot('p2310c-390-agents-tabs-end.png');
    } else check(false, `${tag}: #1046 the agents' sub-tabs`);
  }, true);
  // without the tab "Search": the magnifier stays (search must stay reachable)
  await firefox(async o => {
    const {cmd, ev, ctx} = o, tag = '390 no search tab';
    check(await ffLogin(o, 'light', 'alice', `localStorage.setItem('tasks.tabbar', '["s:inbox","s:today","lists"]');`) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    check(await ev(`!document.body.classList.contains('tab-search') && (() => { const b = document.querySelector('#top .cmdbar'); return !!b && getComputedStyle(b).display !== 'none'; })()`), `${tag}: #1057 the header magnifier stays`);
  }, true);
  // desktop: the list "…" with its groups; the sidebar keeps its search field (the header has none next to it)
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + P); await ready(ev);
    check(await ev(`(() => { const s = document.querySelector('#side .scmd'), c = document.querySelector('#top .cmdbar'); return !!s && getComputedStyle(s).display !== 'none' && (!c || getComputedStyle(c).display === 'none'); })()`), `${tag}: #1057 one search on the desktop (the sidebar field)`);
    await ev(`(() => { document.querySelector('#top [data-act="top-more"]').click(); return 1; })()`); await sleep(600);
    check(await ev(`(() => { const p = document.querySelector('#pop'); const r = p.getBoundingClientRect(); return document.querySelectorAll('#pop .mgrp').length === 2 && r.bottom <= innerHeight + 1; })()`), `${tag}: #1056 the list menu with its groups fits`);
    await shot('p2310c-1440-list-menu.png');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
