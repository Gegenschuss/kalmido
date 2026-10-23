// 2.165.0 UI tests (#2612 the very first start greets once on the first tour card, #2613 an error or the connection's loss
// startles the figures on screen, #2614 pull to refresh shows the bot figure, it hops while the refresh runs), own
// container (start.sh, KALMIDO_ONBOARDING=1: the tour of a new account), Firefox: one run with motion on, one with reduced motion (the ff.js default: no motion at all).
// P4: no new route (client-side motion only); frida and gina have no organisation and run every check.
// P2165_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2165_ui', check, shots: 'P2165_SHOTS'});
const firefoxMoving = require('./ff')({tag: 'p2165_ui_move', check, shots: 'P2165_SHOTS', prefs: [['ui.prefersReducedMotion', 0]]});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2165_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_ONBOARDING: '1'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // P4: frida and gina have no organisation
  const users = {};
  for (const [u, n] of [['frida', 'Frida Berg'], ['gina', 'Gina']]) {
    const x = await call(CA, 'POST', '/api/users', {username: u, display_name: n, password: 'password123', email: u + '@example.com'});
    check(x.http < 300, `P4: ${u} (no organisation) ${x.http}`);
    users[u] = await login(u);
    await call(users[u], 'PATCH', '/api/settings', {lang: 'en', tour: 'pending'});
  }
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const EMPTY = (await call(users.frida, 'POST', '/api/lists', {name: 'Leer'})).id;

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (o, u) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  const HI = `(() => { const c = document.querySelector('.tour .tcard'); if (!c) return null; const h = c.querySelector('h3 .thi'), f = c.querySelector('h3 svg.bot');
    return {hi: !!h, b: h ? h.querySelector('b').textContent : '', sub: h ? h.querySelector('.muted').textContent : '', wave: !!c.querySelector('svg.bot.bhi'), st: f ? [...f.classList].join(' ') : '',
      an: c.querySelector('svg.bot.bhi .b-hop') ? getComputedStyle(c.querySelector('svg.bot.bhi .b-hop')).animationName : 'none', step: document.querySelector('.tour').dataset.step, ls: LS.get('botHi', false)}; })()`;
  const STARTLE = `(() => { const f = document.querySelector('#view .hempty svg.bot'), l = document.querySelector('#kbar .kbbrand svg.logo, #side .sbbrand svg.logo');  // 2.152.3 (#2619): on a computer the brand bot sits in the head bar
    return {fig: !!f, on: !!f && f.classList.contains('bstartle'), an: f ? getComputedStyle(f.querySelector('.b-eyes')).animationName : '', logo: !!l && l.classList.contains('bstartle'),
      lan: l ? getComputedStyle(l.querySelector('.lg-eyes')).animationName : ''}; })()`;
  // #2614: a finger pulls the list down (synthetic touch events); the refresh is held for 900 ms to see the hop
  const PULL = `(async () => {
    window.sharedRoute = () => true; window.refreshNow = () => new Promise(r => setTimeout(r, 900));
    const v = document.querySelector('#view'); v.scrollTop = 0; const hit = v.querySelector('.hempty, .trow, *') || v, x = 200, y = 120, out = {};
    const fire = (type, y) => { const t = new Touch({identifier: 7, target: hit, clientX: x, clientY: y}); hit.dispatchEvent(new TouchEvent(type, {bubbles: true, cancelable: true, touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t]})); };
    const look = () => { const p = document.querySelector('#main .ptr'); const b = p && p.querySelector('svg.bot'); return p ? {cls: p.className, bot: b ? [...b.classList].join(' ') : '', icon: !!p.querySelector('svg.i'), tf: p.style.transform,
      hop: b ? getComputedStyle(b.querySelector('.b-hop')).animationName : ''} : null; };
    fire('touchstart', y); fire('touchmove', y + 40); out.half = look();
    fire('touchmove', y + 130); out.far = look();
    fire('touchend', y + 130); await new Promise(r => setTimeout(r, 120)); out.go = look();
    await new Promise(r => setTimeout(r, 1300)); out.after = look();
    return out; })()`;

  // ===== motion on: the greeting waves (alice in no organisation either way; frida = P4), the startle, the hop
  await firefoxMoving(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    check(await signIn(o, 'frida') === 200, 'frida: login');
    await nav(B + '#inbox');
    check(await ready(ev, `!!document.querySelector('.tour .tcard h3')`, 80), '#2612: the tour opens on the very first start');
    let h = await ev(HI);
    check(h && h.hi && h.b === 'Hello, Frida!' && /Nice to have you here/.test(h.sub) && h.step === 'side', '#2612: the first card says hello by first name: ' + JSON.stringify(h));
    check(h && h.wave && /b-hi-in/.test(h.an) && /b-erledigt/.test(h.st) && h.ls === true, '#2612: the figure pops up and waves (happy eyes), remembered on the device: ' + JSON.stringify(h));
    await shot('p2165-hello-1280.png');
    // next + back: the hello stays, the wave does not start again
    await ev(`(() => { document.querySelector('.tour [data-tour="next"]').click(); return 1; })()`); await sleep(300);
    await ev(`(() => { document.querySelector('.tour [data-tour="back"]').click(); return 1; })()`); await sleep(300);
    h = await ev(HI);
    check(h && h.hi && !h.wave, '#2612: back on the first card: the hello without a second wave ' + JSON.stringify(h));
    // skipped and restarted: the calm figure of the tour, no hello
    await ev(`(() => { document.querySelector('.tour [data-tour="skip"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.tour') && S.settings.tour === 'done'`), '#2612: the tour ends');
    await ev(`(() => { tourStart(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.tour .tcard h3')`), '#2612: the restarted tour');
    h = await ev(HI);
    check(h && !h.hi && !h.wave && /htour/.test(h.st) && /b-ruhig/.test(h.st), '#2612: a restarted tour: the calm figure, no hello ' + JSON.stringify(h));
    await ev(`(() => { tourEnd(true); return 1; })()`);

    // #2613: the connection is lost / a write is refused
    await nav(B + '#today'); await ready(ev, `S.booted`, 80); await ev(`(() => { S.searchQ = 'zzzqqq'; S.searchRes = []; go('search'); return 1; })()`);  // 2.223.0 (#2822): the empty list shows the symbol now; a search without hits keeps the bot
    check(await ready(ev, `!!document.querySelector('#view .hempty .bot') && S.booted`, 80), '#2613: the empty list shows the figure');
    await sleep(500);
    await ev(`(() => { setOnline(false); return 1; })()`);
    let s = await ev(STARTLE);
    check(s.fig && s.on && s.an === 'b-startle' && s.logo && s.lan === 'b-startle', '#2613: offline: the figure and the brand bot look startled ' + JSON.stringify(s));
    await ev(`(() => { setOnline(true); return 1; })()`); await sleep(1000);
    s = await ev(STARTLE);
    check(!s.on && !s.logo, '#2613: only for a moment ' + JSON.stringify(s));
    await ev(`(() => { setOnline(false); setOnline(true); return 1; })()`);
    s = await ev(STARTLE);
    check(!s.on, '#2613: at most every 5 s ' + JSON.stringify(s));
    await ev(`(() => { BOT_STARTLE.t = 0; return 1; })()`);
    await ev(`api('PATCH', '/api/lists/99999999', {name: 'x'}).then(() => 1, () => 1)`);
    s = await ev(STARTLE);
    check(s.on && s.an === 'b-startle', '#2613: a refused write startles the figure ' + JSON.stringify(s));
    await sleep(1000);
    await ev(`(() => { BOT_STARTLE.t = 0; return 1; })()`);
    await ev(`api('GET', '/api/lists/99999999/nothing').then(() => 1, () => 1)`);
    s = await ev(STARTLE);
    check(!s.on, '#2613: a plain 404 of a read does not ' + JSON.stringify(s));

  }, false);

  // #2614: phone (touch), pull to refresh
  await firefoxMoving(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await signIn(o, 'frida') === 200, 'frida: login on the phone');
    await nav(B + '#today'); await ready(ev, `S.booted`, 80); await ev(`(() => { S.searchQ = 'zzzqqq'; S.searchRes = []; go('search'); return 1; })()`);  // 2.223.0 (#2822): the empty list shows the symbol now; a search without hits keeps the bot
    check(await ready(ev, `!!document.querySelector('#view .hempty .bot') && S.booted`, 80), '#2614: phone: the list');
    const p = await ev(PULL);
    check(p.half && /\bpbot\b/.test(p.half.cls) && /\bon\b/.test(p.half.cls) && /b-ruhig/.test(p.half.bot) && !p.half.icon && !/rotate/.test(p.half.tf), '#2614: pulling shows the figure (no turning arrow) ' + JSON.stringify(p.half));
    check(p.far && /\bfar\b/.test(p.far.cls) && /b-wartet/.test(p.far.bot), '#2614: far enough: the figure looks up ' + JSON.stringify(p.far));
    check(p.go && /\bgo\b/.test(p.go.cls) && p.go.hop === 'b-hop', '#2614: let go: it hops while the refresh runs ' + JSON.stringify(p.go));
    check(p.after && !/\b(on|go|far)\b/.test(p.after.cls) && /b-ruhig/.test(p.after.bot), '#2614: done: gone again, calm ' + JSON.stringify(p.after));
  }, true);

  // ===== reduced motion (the ff.js default): the greeting stays, nothing moves
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    check(await signIn(o, 'gina') === 200, 'gina: login');
    await nav(B + '#inbox');
    check(await ready(ev, `!!document.querySelector('.tour .tcard h3')`, 80), 'reduced motion: the tour opens');
    const h = await ev(HI);
    check(h && h.hi && h.b === 'Hello, Gina!' && !h.wave && h.an === 'none', '#2612: reduced motion: the same hello, the figure stays still ' + JSON.stringify(h));
    await ev(`(() => { tourEnd(true); return 1; })()`);
    const lid = await ev(`api('POST', '/api/lists', {name: 'Still'}).then(j => j.id)`);
    await ev(`(() => { S.searchQ = 'zzzqqq'; S.searchRes = []; go('search'); return 1; })()`);  // 2.223.0 (#2822): a search without hits keeps the bot, the empty list shows the symbol
    check(await ready(ev, `!!document.querySelector('#view .hempty .bot') && S.booted`, 80), 'reduced motion: the empty list');
    await ev(`(() => { setOnline(false); return 1; })()`);
    const s = await ev(STARTLE);
    check(s.fig && !s.on && !s.logo, '#2613: reduced motion: not startled ' + JSON.stringify(s));
    await ev(`(() => { setOnline(true); return 1; })()`);
  }, false);
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await signIn(o, 'frida') === 200, 'reduced motion: frida on the phone');
    await nav(B + '#today'); await ready(ev, `S.booted`, 80); await ev(`(() => { S.searchQ = 'zzzqqq'; S.searchRes = []; go('search'); return 1; })()`);  // 2.223.0 (#2822): the empty list shows the symbol now; a search without hits keeps the bot
    await ready(ev, `!!document.querySelector('#view .hempty .bot') && S.booted`, 80);
    const p = await ev(PULL);
    check(p.go && /\bgo\b/.test(p.go.cls) && /b-wartet/.test(p.go.bot) && p.go.hop === 'none', '#2614: reduced motion: the figure, but no hop ' + JSON.stringify(p.go));
  }, true);

  console.log(`p2165_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
