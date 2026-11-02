// kalmido-suite:
// 2.484.0 C UI test, own container (start.sh), Firefox 390 x 844. Invented data only.
// - #3949: on the Projects page (#projects) a long press (touch) or a right click on a project row opens the sidebar's project
//   menu, on a folder row the folder menu; the click that ends the press opens nothing
// - #3949: Back from a project to the Projects page shows the place it was left at; the tab (a new call) starts at the top
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2484_c_ui', check, shots: 'P2484C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2484C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal'});
  const ids = [];
  for (let i = 1; i <= 40; i++) ids.push((await call('POST', '/api/lists', {name: 'Project ' + String(i).padStart(2, '0')})).id);
  const inF = (await call('POST', '/api/lists', {name: 'Folder member', folder: 'Zeta'})).id;
  const last = ids[ids.length - 1];

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#projects');
    check(await ready(ev, `!!S.booted && !!document.querySelector('#view .pstart .psrow[data-pl="${ids[0]}"]')`), 'the Projects page shows the project rows');

    // ---- the menu: long press (touch) on a project row
    const menuOpen = `!!document.querySelector('.menu-list [role=menuitem]')`;
    const press = sel => ev(`(() => { const r = document.querySelector('${sel}'); r.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, pointerType: 'touch', clientX: 50, clientY: 300})); return !!r; })()`);
    await press(`#view .pstart .psrow[data-pl="${ids[0]}"]`);
    check(await ready(ev, menuOpen, 20), 'long press on a project row opens a menu');
    check(await ev(`[...document.querySelectorAll('.menu-list [role=menuitem] .ml')].map(x => x.textContent).join('|') === listMenuItems(${ids[0]}).filter(x => x && x.label).map(x => x.label).join('|') || document.querySelectorAll('.menu-list [role=menuitem]').length >= 3`), 'it is the sidebar\'s project menu');
    await ev(`(() => { const r = document.querySelector('#view .pstart .psrow[data-pl="${ids[0]}"]'); r.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerType: 'touch'})); r.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, detail: 1})); })()`);
    await sleep(300);
    check(await ev(`location.hash`) === '#projects', 'the click that ends the press opens no project ' + await ev(`location.hash`));
    await ev(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))`);
    await ready(ev, `!${menuOpen}`, 12);
    // a folder row
    await press(`#view .pstart .psfold[data-pf="Zeta"]`);
    check(await ready(ev, `[...document.querySelectorAll('.menu-list [role=menuitem] .ml')].some(x => /New project in this folder/.test(x.textContent))`, 20), 'long press on a folder row opens the folder menu');
    await ev(`(() => { const r = document.querySelector('#view .pstart .psfold[data-pf="Zeta"]'); r.dispatchEvent(new PointerEvent('pointerup', {bubbles: true, pointerType: 'touch'})); r.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, detail: 1})); })()`);
    await sleep(300);
    check(await ev(`location.hash`) === '#projects', 'the folder is not opened by the end of the press');
    await ev(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))`);
    await ready(ev, `!${menuOpen}`, 12);
    // a right click (computer)
    await ev(`document.querySelector('#view .pstart .psrow[data-pl="${ids[1]}"]').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true}))`);
    check(await ready(ev, menuOpen, 20), 'a right click on a project row opens the menu');
    await ev(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true}))`);
    await ready(ev, `!${menuOpen}`, 12);

    // ---- Back keeps the place
    await ev(`(() => { const v = document.querySelector('#view'); v.scrollTop = v.scrollHeight; return 1; })()`);
    await ready(ev, `document.querySelector('#view').scrollTop > 300`, 12);
    const y = await ev(`document.querySelector('#view').scrollTop`);
    await sleep(400);  // the place is written 250 ms after the last scroll (debounce) -- nothing to observe for it
    await ev(`document.querySelector('#view .pstart .psrow[data-pl="${last}"]').click()`);
    check(await ready(ev, `location.hash === '#l/${last}'`), 'a tap on the last project opens it');
    await ev(`history.back()`);
    check(await ready(ev, `location.hash === '#projects' && !!document.querySelector('#view .pstart .psrow')`), 'Back shows the Projects page');
    check(await ready(ev, `Math.abs(document.querySelector('#view').scrollTop - ${y}) <= 3`, 24), `Back keeps the place (${y}) ` + await ev(`document.querySelector('#view').scrollTop`));
    // a new call through the tab starts at the top
    await nav(B + '#today');
    await ready(ev, `S.route.key === 'today'`);
    await ev(`(() => { const b = [...document.querySelectorAll('#tabs button')].find(b => /Projects/.test(b.textContent)); b.click(); return 1; })()`);
    await ready(ev, `location.hash === '#projects' && !!document.querySelector('#view .pstart .psrow')`);
    await sleep(500);
    check(await ev(`document.querySelector('#view').scrollTop`) === 0, 'the tab starts the page at the top ' + await ev(`document.querySelector('#view').scrollTop`));
  }, true);

  console.log(`p2484_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
