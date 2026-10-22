// 2.145.0 UI tests, part A (#2433 lilac logo, #2437 logo + word mark at the bottom (2.161.2 #2607: on top, the workspace switch), #2438 head centred on the page header,
// #2444 hint for unread news in other workspaces), own container (start.sh, mode workspaces), Firefox (desktop + phone).
// P2145A_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2145_a_ui', check, shots: 'P2145A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2145A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'})).id;
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  const WS = 'org:' + org.id;
  await call(CB, 'PATCH', '/api/settings', {workspace: WS});
  const L = await call(CA, 'POST', '/api/lists', {name: 'Projekt Alpha', org_id: org.id});
  await call(CA, 'PUT', `/api/lists/${L.id}/members`, {user_id: BOB, role: 'edit'});
  const t = await call(CB, 'POST', '/api/tasks', {title: 'Angebot pruefen', list_id: L.id, assignee_id: me.id});
  check(t.http < 300, '#2444: bob assigns a task to alice ' + t.http);
  await call(CA, 'PATCH', '/api/settings', {workspace: 'private'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // vertical middle of the workspace head and of the page header's content row (the title)
  const mids = `(() => { const m = e => { const b = e.getBoundingClientRect(); return b.top + b.height / 2; };
    const h = document.querySelector('#side .sbhead .wsbar') || document.querySelector('#side .sbhead'), t = document.querySelector('#top h1') || document.querySelector('#top');
    return h && t ? [m(h), m(t)] : null; })()`;
  // geometry for failure messages
  const dbg = `(() => { const r = e => { if (!e) return null; const b = e.getBoundingClientRect(); return [Math.round(b.top), Math.round(b.height)]; }, q = s => document.querySelector(s), cs = getComputedStyle(q('#side'));
    return JSON.stringify({side: r(q('#side')), pt: cs.paddingTop, bt: cs.borderTopWidth, fix: r(q('#side .sbfix')), head: r(q('#side .sbhead')), ws: r(q('#side .wsbar')), top: r(q('#top')), h1: r(q('#top h1')), menu: r(q('#top .menu')), tools: r(q('#side .sbtools')), st: q('#side').scrollTop, fcs: [getComputedStyle(q('#side .sbfix')).marginTop, getComputedStyle(q('#side .sbfix')).top, getComputedStyle(q('#side .sbfix')).position], first: q('#side').firstElementChild.className, ot: q('#side .sbfix').offsetTop, tr: cs.transform, ptsb: cs.getPropertyValue('--sbpt')}); })()`;
  // 2.161.2 (#2607): the small mark at the bottom is gone; the brand on top (logo + word mark) is the workspace switch, its
  // menu has Start
  // 2.152.3 (#2619): on a computer the brand sits in the head bar (#kbar .kbsw: .kbbrand + the workspace), its menu only
  // switches workspaces; Start is in the account menu. The phone keeps the brand in the drawer with Start (brandStart)
  const sbmark = `(() => { const b = document.querySelector('#kbar .kbsw'), k = b && b.querySelector('.kbbrand'); if (!k) return null; const lg = k.querySelector('svg.logo'), w = k.querySelector('svg.kword');
    return {act: b.dataset.act, plate: lg && lg.querySelector('rect').getAttribute('fill'), word: !!w, inside: k.scrollWidth <= k.clientWidth + 1, tag: b.tagName, old: !!document.querySelector('#side .sbmark, #side .sbbrand')}; })()`;
  const brandStart = `(() => { document.querySelector('#side .sbbrand').click(); return new Promise(r => setTimeout(() => { const s = document.querySelector('#pop .wsm-home'); if (s) s.click(); r(!!s); }, 300)); })()`;
  const acctStart = `(() => { document.querySelector('#kbar .kbacct').click(); return new Promise(r => setTimeout(() => { const s = [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => (b.querySelector('.ml') || b).textContent.trim() === 'Start'); if (s) s.click(); r(!!s); }, 300)); })()`;  // 2.152.3 (#2619): Start on a computer = the account menu
  const wsNoStart = `(() => { document.querySelector('#kbar .kbsw').click(); return new Promise(r => setTimeout(() => { const ok = !!document.querySelector('#pop .kbwsi') && !document.querySelector('#pop .wsm-home, #pop .wsm-side'); closePop(); r(ok); }, 300)); })()`;  // 2.152.3 (#2619)

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#news');
    check(await ready(ev, `!!document.querySelector('#kbar .kbsw')`, 80), 'the app is up');  // 2.152.3 (#2619): the workspace switch moved into the head bar
    // ===== #2433 / #2437; 2.161.2 (#2607): the mark moved to the top (the brand = the workspace switch), Start in its menu
    const mk = await ev(sbmark);
    check(mk && mk.tag === 'BUTTON' && mk.act === 'sbb-ws' && !mk.old, '#2607: the brand on top is a button opening the workspace menu, no mark at the bottom: ' + JSON.stringify(mk));  // 2.152.3 (#2619): the brand moved from the panel into the head bar (sbb-ws), none left in the panel
    check(mk && mk.plate === '#6d4bd8' && mk.word && mk.inside, '#2433: the logo plate is lilac, the word mark shows, nothing overflows: ' + JSON.stringify(mk));
    check(await ev(wsNoStart), '#2619: the brand menu switches workspaces, no Start / Hide the sidebar');  // 2.152.3 (#2619): Start left the brand menu on a computer
    check(await ev(acctStart), '#2607: the account menu has Start');  // 2.152.3 (#2619): Start on a computer = the account menu
    check(await ready(ev, `S.route.mod === 'home'`), '#2437: Start opens the start page');
    await ev(`(() => { document.documentElement.style.setProperty('--accent', '#d4541b'); return 1; })()`);
    check(await ev(`document.querySelector('#kbar .kbbrand svg.logo rect').getAttribute('fill') === '#6d4bd8'`), '#2433: the logo ignores the accent colour');  // 2.152.3 (#2619): the brand moved into the head bar
    // ===== #2438 desktop
    await nav(B + '#news');
    await ready(ev, `!!document.querySelector('#kbar .kbsw')`, 40);  // 2.152.3 (#2619): the workspace switch moved into the head bar
    let m = await ev(mids);
    console.log('EXP', await ev(`(() => { const f = document.querySelector('#side .sbfix'), o = []; for (const [k, v] of [['top', '0px'], ['top', '3px'], ['position', 'relative'], ['position', 'static']]) { f.style[k] = v; o.push(k + v + ':' + f.getBoundingClientRect().top); } f.style.cssText = ''; return o.join(' '); })()`)); check(m && Math.abs(m[0] - m[1]) <= 2.5, '#2438: desktop, the head and the page header share a middle: ' + JSON.stringify(m) + ' ' + await ev(dbg));
    // ===== #2444 desktop: the hint, then Switch
    check(await ready(ev, `S.news && S.news.unread_me >= 1`, 60), '#2444: the bell counts the assignment ' + JSON.stringify(await ev(`S.news`)));
    check(await ready(ev, `wsCur() === 'private' && !!document.querySelector('#view .nelse')`, 60), '#2444: the empty view hints at the other workspace');
    const hint = await ev(`(document.querySelector('#view .nelse') || {}).textContent || ''`);
    check(/1 unread in Alpha/.test(hint) && /Switch/.test(hint), '#2444: the hint names the workspace: ' + hint);
    await shot('p2145-a-news-hint.png');
    await ev(`(() => { document.querySelector('#view .nelse [data-act="news-ws"]').click(); return 1; })()`);
    check(await ready(ev, `wsCur() === '${WS}' && !document.querySelector('#view .nelse') && /Angebot pruefen/.test(document.querySelector('#view').textContent)`, 60), '#2444: Switch shows the news in the organisation, the hint is gone');
    await ev(`(() => { fetch('/api/settings', {method: 'PATCH', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({workspace: 'private'})}); return 1; })()`);
    // ===== phone: open drawer
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#news');
    await ready(ev, `!!document.querySelector('#top .menu')`, 60);
    await ev(`(() => { document.querySelector('#top .menu').click(); return 1; })()`);
    await sleep(600);
    m = await ev(mids);
    check(m && Math.abs(m[0] - m[1]) <= 2.5, '#2438: phone, drawer open, the head and the page header share a middle: ' + JSON.stringify(m) + ' ' + await ev(dbg));
    await shot('p2145-a-drawer-phone.png');
    check(await ev(brandStart), '#2607: on the phone the brand menu has Start');  // 2.161.2 (#2607): was the mark at the bottom
    check(await ready(ev, `S.route.mod === 'home' && !document.querySelector('#side.open')`), '#2437: on the phone Start opens the start page and closes the drawer');
  }, false);

  console.log(`p2145_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
