// 2.633.0 (#4994) UI test: the edges of the home-screen app on an iPhone (Safari "Add to Home Screen", standalone).
// kalmido-suite: fresh
// Own container (start.sh), Firefox. Firefox has no safe area, so the test sets --safe-b / --safe-t on the root element (the
// values env(safe-area-inset-*) gives on an iPhone with a home indicator: 34 px below, 47 px above). Invented data only.
// - the status bar: apple-mobile-web-app-status-bar-style is black again (2.750.0, #5240; the --safe-t rules below are
//   measured with a simulated 47 px and stay valid); the head starts below the clock; the workspace stripe on top of the head and the loading bar sit
//   below the status bar, not behind the clock (the glowing line seen on a phone)
// - the tab bar keeps only part of the home indicator room: padding-bottom max(--safe-b - 1.4375rem, min(--safe-b, .5rem)),
//   34 px -> 11 px (2.809.0, #5437: was 22 px with - .75rem), 12 px -> 8 px, 0 -> 0 (no safe area: as before); it ends at the
//   screen's bottom; the labels sit close to it but stay clear of the home indicator (its top ~13 px above the edge)
// - 2.809.0 (#5437): the phone heads (#top, the agent chat's head) are sticky boxes as wide as the screen: iOS 26 draws its
//   scroll-edge blur over the top of a home-screen app unless the top centre sits in such a fixed / sticky box; the head is
//   fully opaque (no opacity / filter / backdrop-filter on it or above it) and nothing lies over it
// - everything above the bar follows the same edge (--tabs-bot): the "+" button, the office import foot (no second safe-area
//   padding), the list's end (#view: --tabs-bot + 4.5rem) - the last row ends above the "+" button
// - the phone drawer's stripe sits below the status bar too; a light design paints the area behind the white clock black
// - the page canvas (html) has the tab bar colour = theme-color: no grey band below the bar when it bounces
// - a computer with a mouse: no tab bar, --tabs-bot is the safe area alone (the old calc(--tabs-h + --safe-b))
// freelancer-matrix: none (layout only)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2633_b_safearea_ui', check, shots: 'P2633B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  // 2.809.0 (#5437): agents on as well (the agent chat's head below)
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['office', 'agents']});  // the setup wizard is done
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'office,collab,agents'});
  const lid = (await call(CA, 'POST', '/api/lists', {name: 'Long list'})).id;
  check(!!lid, 'a list');
  // 2.809.0 (#5437): an agent that is working, with a few messages (the reported case: the agent chat's head while it works)
  const ME = (await call(CA, 'GET', '/api/state')).me;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'comments'], username: 'dev', display_name: 'Dev Agent'});
  check(!!ag.id && !!ag.token, 'an agent');
  await call(CA, 'PUT', `/api/lists/${lid}/members`, {user_id: ag.id, role: 'edit'});
  const v1 = async (m, u, b) => (await fetch(B + 'api/v1' + u, {method: m, headers: {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'}, body: b ? JSON.stringify(b) : undefined})).json().catch(() => ({}));
  for (let i = 1; i <= 12; i++) await v1('POST', `/agent/chats/${ME.id}`, {body: `Message ${i}: a longer line so that the list of messages fills the screen`});
  check((await v1('PUT', '/agent/status', {status: 'working', text: 'Job: Release (bundle)'})).status === 'working', 'the agent works');
  for (let i = 1; i <= 30; i++) await call(CA, 'POST', '/api/tasks', {title: `Task ${String(i).padStart(2, '0')}`, list_id: lid});

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.ok)`);
  // the safe area of an iPhone with a home indicator (Firefox has none): set on the root element, the stylesheet's own value loses
  const safe = (b, t) => `(() => { const s = document.documentElement.style; s.setProperty('--safe-b', '${b}px'); s.setProperty('--safe-t', '${t}px'); return 1; })()`;
  // 2.809.0 (#5437): the head at the top of a phone screen. iOS 26 blurs and dims the top ~30 px of a home-screen app unless the
  // element at the top centre sits in a fixed / sticky box about as wide as the screen (WebKit fixedContainerEdges: >= 90 %,
  // no backdrop-filter in its line); Firefox has no such blur, so the test measures that condition and the head's own state:
  // full opacity, no filter above it, the topmost element at the name / title is the head's own text
  const HEAD = sel => `(() => { const h = document.querySelector('${sel}'); if (!h) return {none: 1}; const r = h.getBoundingClientRect(), W = innerWidth;
    const d = e => (e.id ? '#' + e.id : e.tagName.toLowerCase()) + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\\s+/).join('.') : '');
    const t = h.querySelector('.chnm b') || h.querySelector('h1') || h; let op = 1; const fx = [];
    for (let e = t; e; e = e.parentElement) { const c = getComputedStyle(e); op *= +c.opacity; if (c.filter !== 'none' || (c.backdropFilter || 'none') !== 'none' || c.mixBlendMode !== 'normal') fx.push(d(e)); }
    const tr = t.getBoundingClientRect(), hit = document.elementFromPoint(tr.left + Math.min(tr.width / 2, 20), tr.top + tr.height / 2);
    let edge = '', bf = false; for (let e = document.elementFromPoint(W / 2, 2); e; e = e.parentElement) { const c = getComputedStyle(e); if ((c.backdropFilter || 'none') !== 'none') bf = true;
      if ((c.position === 'fixed' || c.position === 'sticky') && e.getBoundingClientRect().width >= W * .9) { edge = d(e); break; } }
    return {pos: getComputedStyle(h).position, top: Math.round(r.top), w: Math.round(r.width), W, op, fx, txt: t.textContent.trim().slice(0, 40), own: !!hit && (hit === t || t.contains(hit) || h.contains(hit)), hit: hit ? d(hit) : '', edge, bf}; })()`;
  const headOk = (o, what) => {
    check(!o.none && o.op === 1 && !o.fx.length, what + ': the head in full opacity, no filter / backdrop-filter on it or above it ' + JSON.stringify(o));
    check(o.own && o.txt, what + ': nothing lies over the head (its own text is the topmost element) ' + JSON.stringify(o));
    check(o.pos === 'sticky' && o.w >= o.W * .9 && !!o.edge && !o.bf, what + ': the top centre sits in a sticky box as wide as the screen, no backdrop-filter (no iOS edge blur) ' + JSON.stringify(o));
  };
  const GEO = `(() => { const R = e => e.getBoundingClientRect(), tb = document.querySelector('#tabs'), cs = getComputedStyle(tb), labs = [...tb.querySelectorAll('button>span')].filter(s => s.getClientRects().length && getComputedStyle(s).position !== 'absolute');
    return {h: Math.round(R(tb).height), pb: parseFloat(cs.paddingBottom), bot: Math.round(R(tb).bottom), vh: innerHeight, lab: labs.length ? Math.round(Math.max(...labs.map(s => R(s).bottom))) : 0,
      fab: Math.round(R(document.querySelector('#fab')).bottom), view: parseFloat(getComputedStyle(document.querySelector('#view')).paddingBottom),
      tbot: getComputedStyle(document.documentElement).getPropertyValue('--tabs-bot').trim()}; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#l/' + lid);
    check(await ready(ev, `document.querySelectorAll('#view .trow').length >= 30 && !!document.querySelector('#tabs') && !!document.querySelector('#fab')`, 100), 'the list with 30 tasks, the tab bar and the "+" button');
    // ---- the status bar
    check(await ev(`document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]')?.content`) === 'black', 'status bar style "black" (2.750.0 #5240: the page starts below the clock; --safe-t is 0 there, the rules stay for a translucent bar)');
    await ev(safe(34, 47));
    check(await ready(ev, `parseFloat(getComputedStyle(document.querySelector('#tabs')).paddingBottom) === 11`, 20), 'safe area 34 px: the bar takes it');  // 2.809.0 (#5437): 22 -> 11
    // 2.725.0 (#5159): since #5115 reduced motion keeps a .01 ms transition only for visual properties - the padding above is
    // there at once, the box shadows of the stripes still run that transition in the same frame (CI read 0px / 4px). Wait until
    // no transition runs any more (a real state: getAnimations), after a style read that starts them.
    check(await ready(ev, `(() => { for (const e of [document.querySelector('#top'), document.querySelector('#side .sbfix-m .sbhead')]) if (e) getComputedStyle(e).boxShadow;
      return [document.querySelector('#top'), document.querySelector('#side .sbfix-m .sbhead')].every(e => !e || !e.getAnimations().some(a => a.pending || a.playState === 'running')); })()`, 40), 'the stripes\' transitions have ended');
    const top = await ev(`(() => { const t = document.querySelector('#top'), h = t.querySelector('h1'); const l = document.createElement('div'); l.className = 'ldbar on'; l.id = 'p2633-ld'; document.body.appendChild(l);
      const o = {sh: getComputedStyle(t).boxShadow, pt: parseFloat(getComputedStyle(t).paddingTop), h1: Math.round(h.getBoundingClientRect().top), ld: Math.round(l.getBoundingClientRect().top)}; l.remove(); return o; })()`);
    check(top.pt >= 47 && top.h1 >= 47, 'the head starts below the clock ' + JSON.stringify(top));
    check(top.ld === 47, 'the loading bar sits below the status bar, not behind the clock ' + JSON.stringify(top));
    // the workspace stripe on top of the head (4 px): below the status bar (47..51 px), the 47 px behind the clock in the page colour
    check(/0px 47px 0px 0px inset/.test(top.sh) && /0px 51px 0px 0px inset/.test(top.sh) && top.sh.indexOf('47px') < top.sh.indexOf('51px'), 'the workspace stripe sits below the status bar ' + top.sh);
    // the phone drawer's stripe (6 px) likewise below the status bar: its sticky head paints it, the box has no top border then
    // 2.1108.0 (#5964): the head is pinned on top and paints the stripe now (was the search)
    const sd = await ev(`(() => { const sd = document.querySelector('#side'), m = sd?.querySelector('.sbfix-m .sbhead'); return {has: !!m, bt: sd ? getComputedStyle(sd).borderTopWidth : '', sh: m ? getComputedStyle(m).boxShadow : ''}; })()`);
    check(sd.has && sd.bt === '0px' && /0px 47px 0px 0px inset/.test(sd.sh) && /0px 53px 0px 0px inset/.test(sd.sh), 'the drawer\'s stripe sits below the status bar, not behind the clock ' + JSON.stringify(sd));
    // ---- the tab bar: only part of the home indicator room
    const g34 = await ev(GEO);
    // 2.809.0 (#5437): the strip below the labels about halved (a trial): 11 px instead of 22 px, the bar 67 px high
    check(g34.pb === 11 && g34.h === 56 + 11 && g34.bot === g34.vh, 'safe area 34 px: the bar keeps 11 px below (not 34, was 22) and ends at the screen bottom ' + JSON.stringify(g34));
    check(g34.lab > 0 && g34.vh - g34.lab <= 11 + 16, 'the labels sit close to the bottom edge ' + JSON.stringify(g34));
    check(g34.vh - g34.lab >= 16, 'the labels stay clear of the home indicator (its top ~13 px above the edge) ' + JSON.stringify(g34));
    check(g34.tbot !== '' && g34.vh - g34.fab === 67 + 16, 'the "+" button 1rem above the bar (moves down with it) ' + JSON.stringify(g34));
    check(g34.view === 67 + 72, '#view ends --tabs-bot + 4.5rem above the bottom (was + 6rem plus the full safe area) ' + JSON.stringify(g34));
    await ev(`(() => { const v = document.querySelector('#view'); v.scrollTop = v.scrollHeight; return 1; })()`);
    check(await ready(ev, `(() => { const v = document.querySelector('#view'); return v.scrollTop + v.clientHeight >= v.scrollHeight - 1; })()`, 20), 'scrolled to the end of the list');
    const end = await ev(`(() => { const r = [...document.querySelectorAll('#view .trow')].pop().getBoundingClientRect(), f = document.querySelector('#fab').getBoundingClientRect(), t = document.querySelector('#tabs').getBoundingClientRect(); return {row: Math.round(r.bottom), fab: Math.round(f.top), tabs: Math.round(t.top)}; })()`);
    check(end.row <= end.fab && end.row <= end.tabs, 'the last row ends above the "+" button and the tab bar ' + JSON.stringify(end));
    await shot('p2633b-list-end-34.png');
    headOk(await ev(HEAD('#top')), 'list, safe area 34/47');  // 2.809.0 (#5437)
    await ev(safe(12, 0));
    check(await ready(ev, `parseFloat(getComputedStyle(document.querySelector('#tabs')).paddingBottom) === 8`, 20), 'safe area 12 px: the bar takes it');
    const g12 = await ev(GEO);
    check(g12.pb === 8 && g12.h === 64, 'safe area 12 px: the bar keeps 8 px (.5rem) ' + JSON.stringify(g12));
    await ev(safe(0, 0));
    check(await ready(ev, `parseFloat(getComputedStyle(document.querySelector('#tabs')).paddingBottom) === 0`, 20), 'no safe area: the bar takes it');
    const g0 = await ev(GEO);
    check(g0.pb === 0 && g0.h === 56 && g0.view === 56 + 72, 'no safe area: no room below the bar, as before ' + JSON.stringify(g0));
    headOk(await ev(HEAD('#top')), 'list, no safe area (status bar "black")');  // 2.809.0 (#5437)
    // ---- the canvas below the bar: the tab bar colour = theme-color
    const col = await ev(`(() => { const c = document.createElement('canvas').getContext('2d'); c.fillStyle = document.querySelector('meta[name="theme-color"]').content; const m = c.fillStyle;
      const h = getComputedStyle(document.documentElement).backgroundColor; const p = h.match(/\\d+/g).slice(0, 3).map(Number); const hex = '#' + p.map(x => x.toString(16).padStart(2, '0')).join(''); return {meta: m, html: hex}; })()`);
    check(col.meta === col.html, 'the page canvas below the bar has the tab bar colour (theme-color) ' + JSON.stringify(col));
    // ---- the office import foot: above the bar, no second safe-area padding
    await ev(safe(34, 47));
    await nav(B + '#office');
    check(await ready(ev, `[...document.styleSheets].some(s => /office\\.css/.test(s.href || ''))`, 100), 'the office styles are loaded');
    const foot = await ev(`(() => { const d = document.createElement('div'); d.className = 'foot stfoot oimfoot'; d.id = 'p2633-oim'; (document.querySelector('#view')).appendChild(d); const cs = getComputedStyle(d); const o = {pb: parseFloat(cs.paddingBottom), bottom: cs.bottom}; d.remove(); return o; })()`);
    check(foot.pb === 12 && foot.bottom === '67px' /* 2.809.0 (#5437): 78 -> 67 */, 'the import foot: .75rem padding below (no --safe-b again), sticky right above the bar ' + JSON.stringify(foot));
    await shot('p2633b-office-34.png');
    // ---- a light design: the white clock of black-translucent stays readable - black behind it, as the opaque bar was
    const lt = await ev(`(() => { localStorage.setItem('tasks.theme', '"light"'); applyTheme(); const r = getComputedStyle(document.documentElement);
      return {theme: document.documentElement.dataset.theme, sbar: r.getPropertyValue('--sbar-bg').trim(), bg: r.getPropertyValue('--bg').trim(), top: getComputedStyle(document.querySelector('#top')).boxShadow}; })()`);
    // the head's colours ease over (a transition): wait for the settled shadow
    lt.settled = await ready(ev, `(() => { const v = getComputedStyle(document.querySelector('#top')).boxShadow; return /^rgb\\(0, 0, 0\\) 0px 47px/.test(v); })()`, 40);
    check(lt.settled, 'light design: black behind the clock (a white clock stays readable) ' + JSON.stringify(lt));
    await ev(`(() => { localStorage.setItem('tasks.theme', '"dark"'); applyTheme(); return 1; })()`);
  }, true);

  // ---- 2.809.0 (#5437): the agent chat's head on a phone (status bar "black": no safe area above), the agent working
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#agents/' + ag.id);
    check(await ready(ev, `document.body.classList.contains('in-chat') && !!document.querySelector('.chview .chath .chnm b') && document.querySelectorAll('#chat-msgs .cmsg').length >= 12 && /Release/.test(document.querySelector('.chath .chst')?.textContent || '')`, 100), 'the agent chat full screen, its messages and "working: Job …" in the head');
    await ev(safe(34, 0));
    const h = await ev(HEAD('.chview > .chath'));
    headOk(h, 'agent chat');
    check(h.txt === 'Dev Agent' && h.top === 0, 'the head shows the agent at the top of the screen ' + JSON.stringify(h));
    // the agent's own colour on the head (as reported: a coloured stripe and tinted background): still opaque and sticky
    await ev(`(() => { S.colors = S.colors || {}; S.colors[${ag.id}] = '#8b5cf6'; render(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.chview > .chath.agcol')`, 40), 'the head in the agent\'s colour');
    headOk(await ev(HEAD('.chview > .chath')), 'agent chat in its colour');
    await shot('p2633b-chat-head.png');
    // still usable: back leaves the chat
    await ev(`(() => { document.querySelector('.chath .chback').click(); return 1; })()`);
    check(await ready(ev, `!document.body.classList.contains('in-chat')`, 40), 'back in the head leaves the chat');
  }, true);

  // ---- a computer: the old values
  await firefox(async ({cmd, ev, ctx, nav}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    await signIn(ev);
    await nav(B + '#l/' + lid);
    check(await ready(ev, `document.querySelectorAll('#view .trow').length >= 30`, 100), 'desktop: the list');
    // --tabs-bot measured with a probe (an unregistered custom property has no computed length): the safe area alone, as before
    const d = await ev(`(() => { document.documentElement.style.setProperty('--safe-b', '10px'); const p = document.createElement('div'); p.style.cssText = 'position:fixed;left:0;width:1px;height:1px;bottom:var(--tabs-bot)'; document.body.appendChild(p);
      const o = {tbot: Math.round(innerHeight - p.getBoundingClientRect().bottom), tabs: getComputedStyle(document.querySelector('#tabs')).display, view: parseFloat(getComputedStyle(document.querySelector('#view')).paddingBottom)}; p.remove(); return o; })()`);
    check(d.tabs === 'none' && d.tbot === 10, 'desktop (mouse): no tab bar, --tabs-bot = the safe area alone (as before) ' + JSON.stringify(d));
  }, false);

  console.log(`p2633_b_safearea_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
