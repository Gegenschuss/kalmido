// 2.49.0 UI tests, part A, own container (start.sh with SMTP set, so the link shows), Firefox:
// - #1553 the login page: a soft violet gradient behind the card, a glow that pulses and follows the mouse (fixed on a
//   touch screen, still with reduced motion), a calm card (round corners, centred, the logo only, no heron), a greeting
//   by the time of day above the fields, the line under the card, light and dark, a phone width without side scrolling;
//   the page "Set a new password" (an admin's reset link) looks the same
// - #1531 "Forgot your password?" next to "Stay logged in": opens the address field in the same card (the user name typed
//   so far comes along), Back returns, sending shows the same neutral answer
// Screenshots (P249A_SHOTS): login desktop dark / light, phone dark / light.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const ffMotion = require('./ff')({tag: 'p249_a_ui', check, shots: 'P249A_SHOTS', prefs: [['ui.prefersReducedMotion', 0]]});
const ffStill = require('./ff')({tag: 'p249_a_ui', check, shots: 'P249A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
  EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const GREET = ['Good morning, nice to have you here.', 'Welcome back, nice to have you here.', 'Good evening, nice to have you here.'];

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const page = async (o, theme, w, h) => {
    const {ev, nav, cmd, ctx} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    await nav(B);
    for (let i = 0; i < 40 && !await ev(`!!document.querySelector('.authscreen #auth-form')`).catch(() => false); i++) await sleep(250);
  };
  const look = ev => ev(`(() => { const el = document.querySelector('.authscreen'), c = el.querySelector('.card'), cr = c.getBoundingClientRect(), cs = getComputedStyle(c), bs = getComputedStyle(el), gb = getComputedStyle(el, '::before'), ga = getComputedStyle(el, '::after');
    const rem = document.querySelector('#au-rem')?.closest('label')?.getBoundingClientRect(), fg = document.querySelector('[data-au="forgot"]')?.getBoundingClientRect();
    const rgb = s => (s.match(/[\\d.]+/g) || []).slice(0, 3).map(x => /^color\\(/.test(s) ? Number(x) * 255 : Number(x));  // color-mix() gives color(srgb 0..1)
    return {w: innerWidth, h: innerHeight, sw: document.documentElement.scrollWidth, cl: cr.left, cr: innerWidth - cr.right, cw: cr.width, ct: cr.top, cb: cr.bottom, rad: parseFloat(cs.borderTopLeftRadius),
      shadow: cs.boxShadow, bg: rgb(cs.backgroundColor), grad: bs.backgroundImage, anim: gb.animationName, foot: ga.content, lgx: el.style.getPropertyValue('--lgx'),
      hello: document.querySelector('.lghello')?.textContent || '', heron: !!c.querySelector('.heron'), logo: !!c.querySelector('.alogo svg'),
      row: rem && fg ? Math.abs((rem.top + rem.height / 2) - (fg.top + fg.height / 2)) : 99, fgh: fg ? fg.height : 0,
      btn: getComputedStyle(c.querySelector('.btn.pri')).backgroundImage}; })()`);

  // ---- desktop with a mouse, motion allowed
  await ffMotion(async o => {
    const {ev, cmd, ctx, shot} = o;
    await page(o, 'dark', 1280, 860);
    let L = await look(ev);
    check(GREET.includes(L.hello), '#1553: a greeting by the time of day: ' + L.hello);
    check(L.logo && !L.heron, '#1553: the logo only, no heron');
    check(/linear-gradient/.test(L.grad), '#1553: a soft gradient behind the card');
    check(L.anim === 'lgpulse', '#1553: the glow pulses: ' + L.anim);
    check(/Tasks, team and office in one place\./.test(L.foot), '#1553: the line under the card: ' + L.foot);
    check(Math.abs(L.cl - L.cr) < 4 && L.cw >= 380 && L.cw <= 410, `#1553: the card is centred, 25rem wide (${L.cl}/${L.cr}/${L.cw})`);
    check(L.rad >= 20 && /rgba?\(/.test(L.shadow), '#1553: round corners and a soft shadow: ' + L.rad);
    check(/linear-gradient/.test(L.btn), '#1553: the login button has a light gradient');
    check(L.row < 6, '#1531: "Forgot your password?" sits in the row of "Stay logged in"');
    check(L.bg[0] < 60, '#1553: dark: a dark card ' + L.bg);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: 200, y: 300}, {type: 'pointerMove', x: 240, y: 320, duration: 100}]}]});
    await sleep(300);
    L = await look(ev);
    check(L.lgx === '240px', '#1553: the glow follows the mouse: ' + L.lgx);
    await shot('p249a-login-dark.png');
    // light
    await page(o, 'light', 1280, 860);
    L = await look(ev);
    check(L.bg[0] > 200 && /linear-gradient/.test(L.grad), '#1553: light: a light card on a soft gradient ' + L.bg);
    await shot('p249a-login-light.png');
    // #1531: the link opens the address field in the card, Back returns
    await ev(`(() => { document.querySelector('#au-user').value = 'bob'; document.querySelector('[data-au="forgot"]').click(); return 1; })()`);
    await sleep(200);
    check(await ev(`document.querySelector('.authscreen .card #fg-login')?.value === 'bob'`), '#1531: the field opens in the card, the user name comes along');
    check(await ev(`!!document.querySelector('.authscreen').dataset.lgfoot`), '#1553: the line under the card stays');
    await ev(`(() => { document.querySelector('[data-au="back"]').click(); return 1; })()`);
    await sleep(500);
    check(await ev(`!!document.querySelector('.authscreen #auth-form [data-au="forgot"]')`), '#1531: Back: the login again');
    await ev(`(() => { document.querySelector('[data-au="forgot"]').click(); return 1; })()`);
    await sleep(200);
    await ev(`(() => { document.querySelector('#fg-login').value = 'nobody@example.com'; document.querySelector('#fg-form').requestSubmit(); return 1; })()`);
    let sent = false;
    for (let i = 0; i < 20 && !sent; i++) { await sleep(200); sent = await ev(`!!document.querySelector('.authscreen .lgsent')`); }
    check(sent && await ev(`/If an account/.test(document.querySelector('.lgsent').textContent)`), '#1531: the neutral answer after sending');
    // the page "Set a new password" (an admin's reset link) has the same look
    const j = await call(CA, 'POST', `/api/users/${bob.id}/invite`, {send: false});
    await o.nav(B + 'static/icon.svg');
    await o.nav(j.link.replace(/^https?:\/\/[^/]+\//, B));
    for (let i = 0; i < 40 && !await ev(`!!document.querySelector('.authscreen #inv-form')`).catch(() => false); i++) await sleep(250);
    L = await look(ev);
    check(await ev(`!!document.querySelector('.authscreen #inv-form')`) && /linear-gradient/.test(L.grad) && L.rad >= 20 && L.anim === 'lgpulse' && /Tasks, team/.test(L.foot),
      '#1553: the page "Set a new password" looks the same');
  }, false);

  // ---- phone (touch, reduced motion): the glow stays where it is, nothing pulses, no side scrolling
  await ffStill(async o => {
    const {ev, cmd, ctx, shot} = o;
    await page(o, 'dark', 390, 844);
    let L = await look(ev);
    check(L.sw <= 390 && L.cl >= 8 && L.cr >= 8 && L.cw >= 300, `#1553: phone: the card fits, no side scrolling (${L.sw}/${L.cl}/${L.cr}/${L.cw})`);
    check(L.anim === 'none', '#1553: reduced motion: the glow does not pulse: ' + L.anim);
    check(L.fgh >= 43, '#1531: phone: the link is a big enough target: ' + L.fgh);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: 100, y: 120}, {type: 'pointerDown', button: 0}, {type: 'pointerMove', x: 140, y: 160, duration: 100}, {type: 'pointerUp', button: 0}]}]});
    await sleep(300);
    L = await look(ev);
    check(!L.lgx, '#1553: touch: the glow stays where it is');
    await shot('p249a-phone-dark.png');
    await page(o, 'light', 390, 844);
    await shot('p249a-phone-light.png');
  }, true);

  console.log(`p249_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
