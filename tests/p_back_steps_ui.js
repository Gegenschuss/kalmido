// 2.956.0 UI test (#5230: Back = exactly one visible step, for every level), own container
// kalmido-suite:
// The shared suite of the Back mechanism (backclose.js F8D_LV, f8d_step): Firefox as a touch screen (Android Back =
// history.back()) in phone widths 320 / 460 px. Each place: open it, press Back once, exactly one level / view goes, the
// page below stays. Area tasks add their places here (one block each). Invented data only. PBACK_NOSTART=1 = the container runs.
// - the sidebar as a drawer: Back closes it, the page stays (it went one page back before #5230)
// - a list left from the drawer, Back = the page before with the drawer open again (#953), the next Back closes only the
//   drawer, no entry is pushed again for the reopened drawer (it made the Back after it a dead one)
// - the date picker (#dpop): Back closes the picker only, the dialog below stays
// - the tour: every card shown by Next is a step; Back and the tour's own Back button go one card back, the last Back ends it
// - the views of a page (#view._stk, f8d_step): Back shows the view before; another page empties them (no stale entries)
// - a lightbox over a dialog, the search palette: one Back each
// The settings' areas (#5214) stay in p2736_l_settings_back_ui.
// P4: alice works without an organisation: the person without an organisation
// freelancer-matrix: n/a - no route of its own, the Back key in the browser
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p_back_steps_ui', check, shots: 'PBACK_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.PBACK_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const lst = await call('POST', '/api/lists', {name: 'Garden plans'});
  check(lst.id > 0, 'a list ' + JSON.stringify(lst));
  await call('POST', '/api/tasks', {title: 'Water the tomatoes', list_id: lst.id});

  await firefox(async ({cmd, ev, nav: go, ctx, shot, until: wait}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const STATE = `JSON.stringify({open: f8d_open(), depth: f8d_depth(), f8d: history.state?.f8d, p: f8d_bk.pushed, skip: f8d_bk.skip, hash: location.hash, side: !!document.querySelector('#side.open')})`;
    // settled: n levels / views open, our entries match them, the history stands on the top one
    const at = (n, more = 'true', timeout = 6000) => wait(`!f8d_bk.skip && f8d_depth() === ${n} && f8d_bk.pushed === ${n} && (history.state?.f8d || 0) === ${n} && (${more})`, {timeout});
    const back = () => ev(`(history.back(), 1)`);
    // the page below everything: #today, with the entry of #inbox under it (a Back too many would land there)
    const start = async () => {
      await go(B + '#inbox');
      check(await wait(`!!document.querySelector('#view') && typeof f8d_step === 'function' && S.route?.key === 'inbox'`, {timeout: 20000}), 'the app is there');
      await ev(`(location.hash = '#today', 1)`);
      await wait(`S.route?.key === 'today' && !!document.querySelector('#view .vhead, #view h1, #view h2')`, {timeout: 10000});
      await ev(`(history.replaceState({pback: 1}, '', location.href), 1)`);
      await ev(`(window.__push = 0, window.__p0 || (window.__p0 = history.pushState), history.pushState = function () { window.__push++; return window.__p0.apply(this, arguments); }, 1)`);
    };
    const onToday = `location.hash === '#today' && history.state?.pback === 1`;

    for (const W of [320, 460]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 760}});
      await start();
      check(await ev(`isTouch() && isMobile()`), `${W}: a touch screen in phone width`);

      // 1. the drawer: Back closes it, the page stays
      await ev(`(document.querySelector('#top [data-act="side"]').click(), 1)`);
      check(await at(1, `!!document.querySelector('#side.open')`), `${W}: the drawer opens, one entry ` + await ev(STATE));
      check(await ev(`!!document.querySelector('#side [data-go="l/${lst.id}"]')`), `${W}: the drawer shows the list "Garden plans"`);
      await shot(`pback-drawer-${W}.png`);
      await back();
      check(await wait(`!document.querySelector('#side.open') && f8d_bk.pushed === 0 && !f8d_bk.skip && ${onToday}`, {timeout: 6000}), `${W}: Back closes the drawer, Today stays ` + await ev(STATE));

      // 2. #953: a list left from the drawer -> Back = Today with the drawer open again -> Back closes only the drawer
      await ev(`(document.querySelector('#top [data-act="side"]').click(), 1)`);
      await at(1, `!!document.querySelector('#side.open')`);
      await ev(`(document.querySelector('#side [data-go="l/${lst.id}"]').click(), 1)`);
      check(await wait(`location.hash === '#l/${lst.id}' && !document.querySelector('#side.open') && [...document.querySelectorAll('#view .trow')].some(r => r.textContent.includes('Water the tomatoes'))`, {timeout: 10000}), `${W}: the list from the drawer, its task is shown ` + await ev(STATE));
      const pushes = await ev(`window.__push`);
      await back();
      check(await wait(`location.hash === '#today' && !!document.querySelector('#side.open') && !f8d_bk.skip && f8d_bk.pushed === 1`, {timeout: 8000}), `${W}: Back = Today with the drawer open again ` + await ev(STATE));
      await sleep(300);
      check(await ev(`window.__push`) === pushes, `${W}: the reopened drawer takes its old entry, none is pushed ` + await ev(STATE));
      await back();
      check(await wait(`!document.querySelector('#side.open') && f8d_bk.pushed === 0 && !f8d_bk.skip && location.hash === '#today'`, {timeout: 6000}), `${W}: the next Back closes only the drawer, Today stays ` + await ev(STATE));
      await start();

      // 3. the date picker over a dialog: Back closes the picker only
      await ev(`(settingsModal(), 1)`);
      await at(1, `!!document.querySelector('.modal.smodal')`);
      await ev(`(dpOpen(document.querySelector('.modal.smodal h3'), {kind: 'date', value: '2026-03-14', label: 'Pick a day', onPick: () => {}}), 1)`);
      check(await at(2, `!!document.querySelector('#dpop') && f8d_open() === 'dpop'`), `${W}: the date picker counts as a level ` + await ev(STATE));
      check(await ev(`!!document.querySelector('#dpop') && /2026|March|14/.test(document.querySelector('#dpop').textContent)`), `${W}: the picker shows its month`);
      await back();
      check(await at(1, `!document.querySelector('#dpop') && !!document.querySelector('.modal.smodal:not(.an-out)')`), `${W}: Back closes the picker, the dialog stays ` + await ev(STATE));
      await back();
      check(await wait(`!document.querySelector('.modal.smodal:not(.an-out)') && f8d_bk.pushed === 0 && ${onToday}`, {timeout: 6000}), `${W}: the next Back closes the dialog, Today stays ` + await ev(STATE));

      // 4. a lightbox over a dialog, then the search palette: one Back each
      await ev(`(settingsModal(), 1)`);
      await at(1);
      await ev(`(() => { const d = document.createElement('div'); d.className = 'lightbox'; d.textContent = 'A photo'; document.body.appendChild(d); return 1; })()`);
      check(await at(2, `f8d_open() === 'lightbox'`), `${W}: a lightbox over the dialog ` + await ev(STATE));
      await back();
      check(await at(1, `!document.querySelector('.lightbox') && !!document.querySelector('.modal.smodal:not(.an-out)')`), `${W}: Back closes the lightbox only ` + await ev(STATE));
      await back();
      await wait(`f8d_bk.pushed === 0 && !f8d_bk.skip`, {timeout: 6000});
      await ev(`(openPalette(), 1)`);
      check(await at(1, `f8d_open() === 'palette'`), `${W}: the search palette, one entry ` + await ev(STATE));
      await back();
      check(await wait(`!document.querySelector('.palette:not(.an-out)') && f8d_bk.pushed === 0 && ${onToday}`, {timeout: 6000}), `${W}: Back closes the palette, Today stays ` + await ev(STATE));

      // 5. the tour: Next = a step, Back one card back, its Back button the same, the last Back ends it
      await ev(`(tourStart(), 1)`);
      check(await at(1, `!!document.querySelector('.tour .tcard [data-tour="next"]') && TOUR.i === 0`, 10000), `${W}: the tour opens on its first card ` + await ev(STATE));
      const card = () => ev(`document.querySelector('.tour .tcard h3')?.textContent || ''`);
      const c0 = await card();
      await ev(`(document.querySelector('.tour [data-tour="next"]')?.click(), 1)`);
      check(await at(2, `TOUR.i === 1 && !!document.querySelector('.tour [data-tour="back"]')`), `${W}: Next: card 2, a step of Back ` + await ev(STATE));
      const c1 = await card();
      await ev(`(document.querySelector('.tour [data-tour="next"]')?.click(), 1)`);
      check(await at(3, `TOUR.i === 2 && !!document.querySelector('.tour [data-tour="back"]')`), `${W}: Next: card 3 ` + await ev(STATE));
      check(c0 && c1 && c0 !== c1, `${W}: the cards differ ` + JSON.stringify([c0, c1]));
      await back();
      check(await at(2, `TOUR.i === 1`) && await card() === c1, `${W}: Back shows card 2 again ` + await ev(STATE));
      await ev(`(document.querySelector('.tour [data-tour="back"]')?.click(), 1)`);
      check(await at(1, `TOUR.i === 0`) && await card() === c0, `${W}: the tour's own Back = card 1, its entry goes ` + await ev(STATE));
      await back();
      check(await wait(`!TOUR.on && !document.querySelector('.tour') && f8d_bk.pushed === 0 && location.hash === '#today'`, {timeout: 6000}), `${W}: the last Back ends the tour, Today stays ` + await ev(STATE));
      await start();

      // 6. the views of a page (#view._stk): Back shows the view before; another page empties them
      await ev(`(window.__v = 0, f8d_step(document.querySelector('#view'), () => { window.__v--; }), window.__v++, 1)`);
      await ev(`(f8d_step(document.querySelector('#view'), () => { window.__v--; }), window.__v++, 1)`);
      check(await at(2, `window.__v === 2 && f8d_open() === 'view'`), `${W}: two views of the page, two entries ` + await ev(STATE));
      await back();
      check(await at(1, `window.__v === 1`), `${W}: Back shows the view before ` + await ev(STATE));
      await back();
      check(await wait(`window.__v === 0 && f8d_bk.pushed === 0 && !f8d_bk.skip && ${onToday}`, {timeout: 6000}), `${W}: the next Back shows the first view, Today stays ` + await ev(STATE));
      await ev(`(f8d_step(document.querySelector('#view'), () => { window.__v--; }), window.__v++, 1)`);
      await at(1);
      await ev(`(location.hash = '#inbox', 1)`);
      check(await wait(`S.route?.key === 'inbox' && !document.querySelector('#view')._stk?.length && f8d_bk.pushed === 0 && !f8d_bk.skip && location.hash === '#inbox'`, {timeout: 6000}), `${W}: another page empties the views of the page before ` + await ev(STATE));
    }
  }, true);

  console.log(`p_back_steps_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
