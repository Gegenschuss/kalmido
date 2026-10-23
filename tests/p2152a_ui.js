// 2.161.2 UI tests, part A (#2607 the brand on top of the sidebar is the workspace switch, #2608 the bot figure stays
// alive), own container (start.sh, mode workspaces), Firefox (desktop + phone; reduced motion on = the ff.js default,
// one run with motion on). P2152A_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2152a_ui', check, shots: 'P2152A_SHOTS'});
const firefoxMoving = require('./ff')({tag: 'p2152a_ui_move', check, shots: 'P2152A_SHOTS', prefs: [['ui.prefersReducedMotion', 0]]});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2152A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // P4: frida has no organisation
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.http < 300, 'P4: frida (no organisation) ' + fr.http);
  const CF = await login('frida');
  for (const ck of [CA, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'private'});
  const me = (await call(CA, 'GET', '/api/state')).me;
  await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  const EMPTY = (await call(CA, 'POST', '/api/lists', {name: 'Leer'})).id;

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (o, u) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  const BRAND = `(() => { const b = document.querySelector('#side .sbhead .sbbrand'); if (!b) return null; const r = b.getBoundingClientRect(), s = document.querySelector('#side').getBoundingClientRect();
    return {first: b === document.querySelector('#side .sbhead button'), act: b.dataset.act, pop: b.getAttribute('aria-haspopup'), logo: !!b.querySelector('svg.logo'), word: !!b.querySelector('svg.kword'),
      ws: (b.querySelector('.sbbsub .wsn') || {}).textContent, dot: !!b.querySelector('.sbbsub .wsp-dot, .sbbsub svg.i'), top: Math.round(r.top - s.top), h: Math.round(r.height), inside: b.scrollWidth <= b.clientWidth + 1,
      mark: !!document.querySelector('#side .sbmark'), logos: document.querySelectorAll('#side svg.logo').length}; })()`;
  const openMenu = `(() => { document.querySelector('#side .sbbrand').click(); return new Promise(r => setTimeout(() => r({head: [...document.querySelectorAll('#pop .mgh')].map(x => x.textContent.trim()),
    items: [...document.querySelectorAll('#pop [role="menuitem"]')].map(x => (x.querySelector('.ml') || x).textContent.trim()), home: !!document.querySelector('#pop .wsm-home'), side: (document.querySelector('#pop .wsm-side .ml') || {}).textContent}), 300)); })()`;
  const pick = cls => `(() => { const b = document.querySelector('#pop .${cls}'); if (b) b.click(); return !!b; })()`;
  // 2.152.3 (#2619): on a computer the brand + the workspace sit in the head bar (#kbar .kbsw), its menu only switches
  // (organisations first, then Private, All), adds a company and opens its settings; Start moved to the account menu, hiding
  // the panel to the panel head (.sbbhide). BRAND / openMenu above stay for the phone's drawer
  const BRANDK = `(() => { const b = document.querySelector('#kbar .kbsw'); if (!b) return null; const r = b.getBoundingClientRect(), s = document.querySelector('#side').getBoundingClientRect();
    return {first: b === document.querySelector('#kbar button'), act: b.dataset.act, pop: b.getAttribute('aria-haspopup'), logo: !!b.querySelector('.kbbrand svg.logo'), word: !!b.querySelector('.kbbrand svg.kword'),
      ws: (b.querySelector('.kbfirm .wsn') || {}).textContent, dot: !!b.querySelector('.kbfirm .wsp-dot, .kbfirm svg.i'), above: Math.round(s.top - r.bottom), inside: b.scrollWidth <= b.clientWidth + 1,
      mark: !!document.querySelector('#side .sbmark'), side: !!document.querySelector('#side .sbbrand, #side svg.logo'), logos: document.querySelectorAll('#kbar svg.logo').length}; })()`;
  const openMenuK = `(() => { document.querySelector('#kbar .kbsw').click(); return new Promise(r => setTimeout(() => r({head: [...document.querySelectorAll('#pop .mgh')].map(x => x.textContent.trim()),
    ws: [...document.querySelectorAll('#pop .kbwsi')].map(x => (x.querySelector('.ml') || x).textContent.trim()), on: ((document.querySelector('#pop .kbwsi.on .ml') || {}).textContent || '').trim(),
    add: !!document.querySelector('#pop .kbws-add'), set: !!document.querySelector('#pop .kbws-set'), home: !!document.querySelector('#pop .wsm-home'), side: !!document.querySelector('#pop .wsm-side')}), 300)); })()`;
  const tap = sel => `(() => { const b = document.querySelector('${sel}'); if (b) b.click(); return !!b; })()`;
  const acctStart = `(() => { document.querySelector('#kbar .kbacct').click(); return new Promise(r => setTimeout(() => { const s = [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => (b.querySelector('.ml') || b).textContent.trim() === 'Start'); if (s) s.click(); r(!!s); }, 300)); })()`;
  const MOTION = `(() => { const e = document.querySelector('#view .hempty .bot .b-eyes'); return e ? {an: getComputedStyle(e).animationName, blink: typeof wsBlinkT === 'undefined' ? 'gone' : wsBlinkT} : null; })()`;

  // ===== reduced motion (the ff.js default), desktop + phone
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    check(await signIn(o, 'alice') === 200, 'alice: login');
    await nav(B + '#today');  // 2.223.0 (#2822): the empty list shows the symbol now; the bot stays on the calm Today page
    check(await ready(ev, `!!document.querySelector('#kbar .kbsw')`, 80), 'the app is up');  // 2.152.3 (#2619): the brand moved into the head bar
    // #2607: the brand on top
    let b = await ev(BRANDK);  // 2.152.3 (#2619): the head bar
    check(b && b.first && b.act === 'sbb-ws' && b.pop === 'menu' && b.logo && b.word && b.ws === 'Private' && b.dot && b.inside, '#2607: the brand (logo + word mark) is the first button of the head bar, the workspace beside it: ' + JSON.stringify(b));  // 2.152.3 (#2619): was the first button of the panel head (ws-menu)
    check(b && b.above >= 0 && !b.mark && !b.side && b.logos === 1, '#2607: the brand over the panel, none left in the panel, the small mark at the bottom is gone: ' + JSON.stringify(b));  // 2.152.3 (#2619): the head bar over the panel
    let m = await ev(openMenuK);
    check(m.head.includes('Switch to') && m.ws.join('|') === 'Alpha|Private|All workspaces' && m.on === 'Private' && m.add && !m.set && !m.home && !m.side, '#2619: the menu: Switch to (organisations first, Private, All), Add a company; no Start / Hide the sidebar: ' + JSON.stringify(m));  // 2.152.3 (#2619): the new workspace menu (sbb_wsMenu)
    await shot('p2152a-menu-1280.png');
    await ev(`(() => { closePop(); return 1; })()`);
    check(await ev(tap('#side .sbbhide')), '#2619: Hide the panel (panel head)');  // 2.152.3 (#2619): hiding moved from the brand menu (wsm-side) to the panel head
    check(await ready(ev, `document.querySelector('#app').classList.contains('side-rail') && LS.get('sideFold', false) === true`), '#2607: the sidebar folds away on a wide screen');
    check(await ev(tap('#srail .srpanel')), '#2619: hidden: the bar offers to show the panel again');  // 2.152.3 (#2619): was "Show the sidebar" in the brand menu
    check(await ready(ev, `!document.querySelector('#app').classList.contains('side-rail') && LS.get('sideFold', false) === false`), '#2607: the sidebar is back');
    await ev(tap('#side .sbbhide')); await ready(ev, `document.querySelector('#app').classList.contains('side-rail')`);
    check(await ev(tap('#srail .srb.on[data-sbb]')) && await ready(ev, `!document.querySelector('#app').classList.contains('side-rail') && LS.get('sideFold', false) === false`), '#2619: a click on the open area\'s icon brings the panel back');  // 2.152.3 (#2619): new
    // #2608 with reduced motion: no animation on the empty page, no blink timer
    await nav(B + '#today');  // 2.223.0 (#2822): the empty list shows the symbol now; the bot stays on the calm Today page
    check(await ready(ev, `!!document.querySelector('#view .hempty .bot')`, 60), '#2608: the empty list shows the figure');
    const mo = await ev(MOTION);
    check(mo && mo.an === 'none' && mo.blink === 0, '#2608: reduced motion: no animation, no blink timer ' + JSON.stringify(mo));
    // an organisation: its name under the brand
    await ev(`(() => { wsSet('org:' + S.me.workspaces[0].id); return 1; })()`);
    check(await ready(ev, `(document.querySelector('#kbar .kbsw .wsn') || {}).textContent === 'Alpha'`), '#2607: the organisation\'s name beside the brand');  // 2.152.3 (#2619): the switch in the head bar
    await shot('p2152a-org-1280.png');
    await ev(`(() => { wsSet('private'); return 1; })()`);
    // Start from the account menu  // 2.152.3 (#2619): on a computer no longer in the brand menu
    check(await ev(acctStart), '#2619: the account menu has Start');
    check(await ready(ev, `S.route.mod === 'home'`), '#2607: Start opens the start page');
    // phone: the drawer has the same head; Start closes it
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#inbox');
    await ready(ev, `!!document.querySelector('#top .menu')`, 60);
    await ev(`(() => { document.querySelector('#top .menu').click(); return 1; })()`); await sleep(600);
    b = await ev(BRAND);
    check(b && b.first && b.logo && b.ws === 'Private' && b.inside, '#2607: phone: the drawer has the brand on top ' + JSON.stringify(b));
    await shot('p2152a-drawer-390.png');
    m = await ev(openMenu);
    check(m.home && m.side === 'Hide the sidebar', '#2607: phone: Start + Hide the sidebar ' + JSON.stringify(m));
    await ev(pick('wsm-side'));
    check(await ready(ev, `!document.querySelector('#side.open')`), '#2607: phone: Hide the sidebar closes the drawer');
  }, false);

  // ===== P4: frida without an organisation
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    check(await signIn(o, 'frida') === 200, 'frida: login');
    await nav(B + '#inbox');
    check(await ready(ev, `!!document.querySelector('#kbar .kbsw')`, 80), 'P4: the brand is there without an organisation');  // 2.152.3 (#2619): the brand in the head bar
    const b = await ev(BRANDK);
    check(b && b.logo && b.ws === 'Private', 'P4: the brand says Private ' + JSON.stringify(b));
    const m = await ev(openMenuK);
    check(m.ws.join('|') === 'Private' && m.on === 'Private' && m.add && !m.set && !m.home && !m.side, 'P4: the menu: Private, Add a company ' + JSON.stringify(m));  // 2.152.3 (#2619): the new workspace menu, Start in the account menu
    await ev(`(() => { closePop(); return 1; })()`);
    check(await ev(acctStart), 'P4: the account menu has Start');  // 2.152.3 (#2619): Start moved to the account menu
    check(await ready(ev, `S.route.mod === 'home'`), 'P4: Start opens the start page');
  }, false);

  // ===== #2608 with motion: the empty page loops, the brand has a blink timer
  await firefoxMoving(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    check(await signIn(o, 'alice') === 200, 'motion: login');
    await nav(B + '#today');  // 2.223.0 (#2822): the empty list shows the symbol now; the bot stays on the calm Today page
    check(await ready(ev, `!!document.querySelector('#view .hempty .bot')`, 80), 'motion: the empty list shows the figure');
    const mo = await ev(MOTION);
    check(mo && /b-idle/.test(mo.an) && mo.blink, '#2608: the figure loops on the empty page, the brand bot has a blink timer ' + JSON.stringify(mo));
    // the blink itself (class + animation on the eyes), not while typing
    const bl = await ev(`(() => { const b = document.querySelector('#kbar .kbsw'); b.classList.add('blink'); const n = getComputedStyle(b.querySelector('svg.logo .lg-eyes')).animationName; b.classList.remove('blink'); return n; })()`);
    check(bl === 'b-blink', '#2608: the brand bot blinks ' + bl);  // 2.152.3 (#2619): the brand in the head bar (#kbar .kbsw.blink)
  }, false);

  console.log(`p2152a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
