// kalmido-suite: fresh
// 2.572.0 B (#4747) UI tests, Firefox at 390 px with touch: a phone's favourites are no row under the header any more but a
// row over the tab bar. A swipe up on the tab bar opens it, a swipe down / a tile / a tap next to it / Escape closes it; a plain
// tap on a tab never opens it; the grip is a button with aria-expanded (tap opens and closes); no grip while the tab
// "Favourites" is pinned or a field has the focus (the keyboard). Invented data only. P2572B_SHOTS=dir: pictures.
// freelancer-matrix: tasks  (frida has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const {realClick} = require('./ff');
const firefox = require('./ff')({tag: 'p2572_b_favswipe_ui', check, shots: 'P2572B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };

// a finger on the element `sel` (its middle) moving by dy in steps; touch events as the phone sends them
const SWIPE = (sel, dy, dx = 0) => `(() => {
  const el = document.querySelector('${sel}'), r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
  const fire = (type, X, Y) => { const t = new Touch({identifier: 7, target: el, clientX: X, clientY: Y}); el.dispatchEvent(new TouchEvent(type, {bubbles: true, cancelable: true, touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t]})); };
  fire('touchstart', x, y);
  for (let i = 1; i <= 4; i++) fire('touchmove', x + ${dx} * i / 4, y + ${dy} * i / 4);
  fire('touchend', x + ${dx}, y + ${dy});
  return 1; })()`;
const OPEN = `!document.querySelector('#favup').classList.contains('hidden')`;
const SHUT = `document.querySelector('#favup').classList.contains('hidden')`;
const GRIP = `!document.querySelector('#favgrip').classList.contains('hidden') && document.querySelector('#favgrip').getBoundingClientRect().height > 0`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all'});
  const FL = (await call(CF, 'POST', '/api/lists', {name: 'Shoot prep'})).id;
  await call(CF, 'POST', '/api/tasks', {list_id: FL, title: 'Book the van'});
  await call(CF, 'PUT', `/api/lists/${FL}/favorite`, {on: true});
  await call(CF, 'PATCH', '/api/settings', {fav_items: ['v:today', 'v:week', 'v:all', `l:${FL}`]});
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(100); } return false; };

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot, drag} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 760}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#today');
    check(await ready(ev, `S.booted && document.querySelectorAll('#tabs button').length > 0 && document.querySelectorAll('#favup .fv2-tile').length === 4`), 'the row holds the four favourites');
    check(await ev(`!document.querySelector('#favrow') && !document.querySelector('#main .fv2bar')`), 'no row under the header any more');
    check(await ready(ev, GRIP), 'the grip is there');
    check(await ev(SHUT), 'the row starts closed');
    const g = JSON.parse(await ev(`(() => { const b = document.querySelector('#favgrip'), r = b.getBoundingClientRect(), t = document.querySelector('#tabs').getBoundingClientRect();
      return JSON.stringify({tag: b.tagName, exp: b.getAttribute('aria-expanded'), ctl: b.getAttribute('aria-controls'), lab: b.getAttribute('aria-label'), edge: r.top < t.top && r.bottom > t.top}); })()`));
    check(g.tag === 'BUTTON' && g.exp === 'false' && g.ctl === 'favup' && g.lab === 'Favourites' && g.edge, 'the grip: a button on the top edge of the tab bar, aria-expanded false ' + JSON.stringify(g));

    // a plain tap on a tab (a finger moves a few pixels) never opens the row; the tab still works
    await ev(SWIPE('#tabs button:not(.on)', -6, 2));
    await ev(`(() => { document.querySelector('#tabs button:not(.on)').click(); return 1; })()`);
    check(await ready(ev, `location.hash !== '#today'`), 'the tab still opens its page');
    check(await ev(SHUT), 'a tap on a tab does not open the row');
    await nav(B + '#today'); await ready(ev, `S.booted && S.route.key === 'today' && document.querySelectorAll('#favup .fv2-tile').length === 4`);
    // a sideways move on the bar is no swipe up either
    await ev(SWIPE('#tabs button', -20, 80));
    check(await ev(SHUT), 'a sideways move does not open the row');

    // a swipe up on the bar opens it above the bar, the grip says so
    await ev(SWIPE('#tabs button', -70));
    check(await ready(ev, OPEN), 'a swipe up on the tab bar opens the row');
    check(await ev(`document.querySelector('#favgrip').getAttribute('aria-expanded') === 'true'`), 'aria-expanded true');
    await ready(ev, `!document.querySelector('#favup').getAnimations().some(a => a.playState === 'running')`, 20);
    const p = JSON.parse(await ev(`(() => { const r = document.querySelector('#favup').getBoundingClientRect(), t = document.querySelector('#tabs').getBoundingClientRect(), a = document.querySelector('#favup .fv2-tile').getBoundingClientRect();
      return JSON.stringify({over: Math.abs(r.bottom - t.top) < 2, h: a.height, tile: a.top >= r.top && a.bottom <= r.bottom}); })()`));
    check(p.over && p.tile && p.h >= 44, 'the row sits right above the tab bar, big targets ' + JSON.stringify(p));
    await shot('p2572b-open.png');
    // a swipe down closes
    await ev(SWIPE('#favup', 60));
    check(await ready(ev, SHUT), 'a swipe down closes the row');
    check(await ev(`document.querySelector('#favgrip').getAttribute('aria-expanded') === 'false'`), 'aria-expanded false again');
    // the grip: tap opens, tap closes (keyboard and screen reader: it is a button)
    await ev(`(() => { document.querySelector('#favgrip').click(); return 1; })()`);
    check(await ready(ev, OPEN), 'a tap on the grip opens the row');
    await ev(`(() => { document.querySelector('#favgrip').click(); return 1; })()`);
    check(await ready(ev, SHUT), 'a second tap on the grip closes it');
    // a tap next to it closes
    await ev(`(() => { document.querySelector('#favgrip').click(); return 1; })()`);
    await ready(ev, OPEN);
    await ev(`(() => { const v = document.querySelector('#view'); v.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerType: 'touch'})); return 1; })()`);
    check(await ready(ev, SHUT), 'a tap next to the row closes it');
    // Escape closes and gives the focus back to the grip
    await ev(`(() => { document.querySelector('#favgrip').focus(); document.querySelector('#favgrip').click(); return 1; })()`);
    await ready(ev, OPEN);
    await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    check(await ready(ev, SHUT) && await ev(`document.activeElement?.id === 'favgrip'`), 'Escape closes, the focus is on the grip');
    // a tile opens its target and closes the row
    await ev(SWIPE('#tabs button', -70));
    await ready(ev, OPEN);
    await ev(`(() => { document.querySelector('#favup .fv2-tile[data-fv2="l:${FL}"]').click(); return 1; })()`);
    check(await ready(ev, `S.route.key === 'l:${FL}'`), 'a tile opens its list');
    check(await ready(ev, SHUT), 'and closes the row');
    // a real finger (the browser's own touch input) on the bar
    const tb = JSON.parse(await ev(`(() => { const r = document.querySelector('#tabs button').getBoundingClientRect(); return JSON.stringify({x: r.left + r.width / 2, y: r.top + r.height / 2}); })()`));
    await drag(tb.x, tb.y, 0, -80, 'touch').catch(e => console.log('touch drag:', e.message));
    check(await ready(ev, OPEN), 'a real swipe up with a finger opens the row');
    await ev(`(() => { fvd_set(false); return 1; })()`);

    // a field with the focus (the keyboard is up): no grip, an open row closes
    await ev(`(() => { document.querySelector('#favgrip').click(); return 1; })()`);
    await ready(ev, OPEN);
    await ev(`(() => { const i = document.createElement('input'); i.id = 'p2572b-in'; i.style.cssText = 'position:fixed;top:7rem;left:1rem;z-index:99'; document.addEventListener('focusin', () => { window.__fi = (window.__fi || 0) + 1; }, true); document.body.append(i); return 1; })()`);
    const rc = await realClick(o, '#p2572b-in', {kind: 'touch'});  // a real tap: the browser focuses the field as a phone does
    check(rc.ok && await ready(ev, `document.activeElement?.id === 'p2572b-in'`), 'the field has the focus ' + rc.on);
    // a headless Firefox without the window's focus moves the focus but sends no focus events (seen on the Mac runner): the one a phone sends
    await ev(`(() => { if (!window.__fi) { window.__fake = 1; document.activeElement.dispatchEvent(new FocusEvent('focusin', {bubbles: true})); } return 1; })()`);
    check(await ready(ev, `${SHUT} && document.querySelector('#favgrip').classList.contains('hidden')`), 'a field has the focus: no grip, the row closed ' + await ev(`JSON.stringify({fi: window.__fi || 0, a: document.activeElement?.id, ef: editFocused(), can: fvd_can(), n: FVD.n, mob: isMobile(), g: document.querySelector('#favgrip').className, open: fvd_isOpen()})`));
    await ev(SWIPE('#tabs button', -70));
    check(await ev(SHUT), 'a field has the focus: a swipe opens nothing');
    await ev(`(() => { const i = document.querySelector('#p2572b-in'); i.blur(); if (window.__fake) i.dispatchEvent(new FocusEvent('focusout', {bubbles: true})); i.remove(); return 1; })()`);
    check(await ready(ev, GRIP), 'the focus left the field: the grip is back');

    // the tab "Favourites" pinned: neither grip nor row
    await ev(`(() => { LS.set('tabbar', [...tabIds(), 'favs']); render(); return 1; })()`);
    check(await ready(ev, `document.querySelector('#favgrip').classList.contains('hidden') && !document.querySelector('#favup .fv2-tile')`), 'the tab pinned: no grip, no row');
    await ev(SWIPE('#tabs button', -70));
    check(await ev(SHUT), 'the tab pinned: a swipe opens nothing');
    await ev(`(() => { LS.set('tabbar', tabIds().filter(x => x !== 'favs')); render(); return 1; })()`);
    check(await ready(ev, GRIP), 'the tab unpinned: the grip is back');

    // a computer / tablet: the favourites stay in the head bar, no grip
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1024, height: 760}});
    check(await ready(ev, `document.querySelectorAll('#kbar .fv2bar .fv2-tile').length === 4 && document.querySelector('#favgrip').classList.contains('hidden') && !document.querySelector('#favup .fv2-tile')`), 'wide: head bar, no grip, no row');
  }, true);

  console.log(`p2572_b_favswipe_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
