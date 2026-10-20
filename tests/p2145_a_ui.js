// 2.145.0 UI tests, part A (#2433 lilac logo, #2437 logo + word mark at the bottom, #2438 head centred on the page header,
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
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  const WS = 'org:' + org.id;
  await call(CB, 'PATCH', '/api/settings', {workspace: WS});
  const L = await call(CA, 'POST', '/api/lists', {name: 'Projekt Alpha', org_id: org.id});
  const t = await call(CB, 'POST', '/api/tasks', {title: 'Angebot pruefen', list_id: L.id, assignee_id: me.id});
  check(t.http < 300, '#2444: bob assigns a task to alice ' + t.http);
  await call(CA, 'PATCH', '/api/settings', {workspace: 'private'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // vertical middle of the workspace head and of the page header's content row (the title)
  const mids = `(() => { const m = e => { const b = e.getBoundingClientRect(); return b.top + b.height / 2; };
    const h = document.querySelector('#side .sbhead .wsbar') || document.querySelector('#side .sbhead'), t = document.querySelector('#top h1') || document.querySelector('#top');
    return h && t ? [m(h), m(t)] : null; })()`;
  const sbmark = `(() => { const b = document.querySelector('#side .sfoot .sbmark'); if (!b) return null; const lg = b.querySelector('svg.logo'), w = b.querySelector('svg.kword');
    return {label: b.getAttribute('aria-label'), go: b.dataset.go, plate: lg && lg.querySelector('rect').getAttribute('fill'), word: !!w, inside: b.scrollWidth <= b.clientWidth + 1, tag: b.tagName}; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#news');
    check(await ready(ev, `!!document.querySelector('#side .sbhead .wsbar')`, 80), 'the app is up');
    // ===== #2433 / #2437
    const mk = await ev(sbmark);
    check(mk && mk.tag === 'BUTTON' && mk.go === 'home' && mk.label === 'Kalmido - Start', '#2437: the mark at the bottom is a button to Start: ' + JSON.stringify(mk));
    check(mk && mk.plate === '#6d4bd8' && mk.word && mk.inside, '#2433: the logo plate is lilac, the word mark shows, nothing overflows: ' + JSON.stringify(mk));
    check(await ev(`(() => { const b = document.querySelector('#side .sfoot .sbmark'), s = document.querySelector('#side .sfoot .sset'); return !!(b && s && (s.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)); })()`), '#2437: the mark sits under Settings');
    await ev(`(() => { document.querySelector('#side .sfoot .sbmark').click(); return 1; })()`);
    check(await ready(ev, `S.route.mod === 'home'`), '#2437: a tap opens Start');
    await ev(`(() => { document.documentElement.style.setProperty('--accent', '#d4541b'); return 1; })()`);
    check(await ev(`document.querySelector('#side .sbmark svg.logo rect').getAttribute('fill') === '#6d4bd8'`), '#2433: the logo ignores the accent colour');
    // ===== #2438 desktop
    await nav(B + '#news');
    await ready(ev, `!!document.querySelector('#side .sbhead .wsbar')`, 40);
    let m = await ev(mids);
    check(m && Math.abs(m[0] - m[1]) <= 2.5, '#2438: desktop, the head and the page header share a middle: ' + JSON.stringify(m));
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
    check(m && Math.abs(m[0] - m[1]) <= 2.5, '#2438: phone, drawer open, the head and the page header share a middle: ' + JSON.stringify(m));
    await shot('p2145-a-drawer-phone.png');
    await ev(`(() => { document.querySelector('#side .sbmark').scrollIntoView(); document.querySelector('#side .sbmark').click(); return 1; })()`);
    check(await ready(ev, `S.route.mod === 'home' && !document.querySelector('#side.open')`), '#2437: on the phone a tap opens Start and closes the drawer');
  }, false);

  console.log(`p2145_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
