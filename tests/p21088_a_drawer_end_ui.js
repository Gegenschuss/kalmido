// kalmido-suite: fresh
// 2.1088.0 (#5894) UI test (guard): the phone's drawer ends above its foot (Settings + the account). Scrolled to the end, the last
// entry of the office panel (Cash book, the last of Money) stands wholly above the foot and nothing stands behind it, at 320, 360
// and 460 px. While the list is longer than the screen, the rows in the middle slide under the foot like under the search on
// top (the foot is sticky in the drawer's one scrolling box) - that is scrolling, not a hidden entry. Firefox with touch, own
// container (start.sh).
// 2.1091.0 (#5896): while more entries follow below, a light shadow lies over the foot (#side.sb-more, the foot's ::before); scrolled
// to the end it is gone, scrolled back up it is there again; a list that fits the screen has none; the computer sidebar has none.
// freelancer-matrix: n/a - nur Oberfläche (no route changed; the drawer of a person without an organisation: p2196_a_mside_ui.js)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21088_a_drawer_end_ui', check, shots: 'P21088A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P21088A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const MODS = 'cal,comments,office,contacts,wiki,time,pomo,review,stats,agents';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const r = await fetch(B + 'api/auth/login', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', password: 'password123'})});
  const CA = (r.headers.get('set-cookie') || '').split(';')[0];
  const call = (method, url, body) => fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined});
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: MODS.split(',')});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: MODS + ',collab'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // where the drawer's entries stand against its foot; "under" = entries that overlap the foot (partly or wholly)
  const M = `(() => { const s = document.querySelector('#side'), dock = document.querySelector('#side .sbdock'), sc = s;
    if (!s || !dock) return null; const R = el => el.getBoundingClientRect(), d = R(dock), sr = R(s);
    const rows = [...document.querySelectorAll('#side .srow, #side [data-ofm]')].filter(x => !dock.contains(x) && x.offsetParent);
    const cash = document.querySelector('#side [data-ofm="cashbook"]');
    return {under: rows.filter(x => { const b = R(x); return b.bottom > d.top + 1 && b.top < d.bottom - 1; }).map(x => x.textContent.trim()),
      cash: cash ? {top: Math.round(R(cash).top), bottom: Math.round(R(cash).bottom)} : null, dockTop: Math.round(d.top), dockBottom: Math.round(sr.bottom - d.bottom),
      scrolls: sc.scrollHeight > sc.clientHeight + 1, st: sc.scrollTop, inside: s.scrollWidth <= s.clientWidth + 1}; })()`;
  // the shadow over the foot: the drawer's mark and what the foot's ::before draws ('none' = no shadow)
  const SH = `(() => { const s = document.querySelector('#side'), dock = document.querySelector('#side .sbdock');
    return s && dock ? {more: s.classList.contains('sb-more'), sh: getComputedStyle(dock, '::before').boxShadow, sh_: s.scrollHeight, ch: s.clientHeight, st: Math.round(s.scrollTop)} : null; })()`;
  const shadow = on => `(() => { const x = ${SH}; return !!x && x.more === ${on} && (x.sh !== 'none') === ${on}; })()`;
  const toEnd = `(() => { const sc = document.querySelector('#side'); sc.scrollTop = sc.scrollHeight; return 1; })()`;

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.ofmAll', 'true'); localStorage.setItem('tasks.sbbUnfold', '["office:money"]'); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login in the browser');
    await nav(B + '#office'); await ready(ev, `!!S.booted && S.route.mod === 'office'`, 80);  // the first boot takes the settings (all office points)
    for (const [w, h] of [[320, 568], [360, 640], [460, 800]]) {
      const tag = `${w}x${h}`;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      await nav(B + 'static/icon.svg'); await nav(B + '#office');
      check(await ready(ev, `!!document.querySelector('#top .menu') && !!S.booted && S.route.mod === 'office'`, 80), `${tag}: the office is up`);
      await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('#side.open') && !!document.querySelector('#side [data-ofm="cashbook"]')`, 40), `${tag}: the drawer opens with the office panel and Cash book`);
      await ready(ev, `(() => { const s = document.querySelector('#side'); return s && Math.abs(s.getBoundingClientRect().left) < 1; })()`, 20);  // the slide-in has ended
      let m = (await ev(M)) || {};
      await shot(`p21088a-open-${w}.png`);
      check(m.dockBottom != null && Math.abs(m.dockBottom) <= 2 && m.inside, `${tag}: the foot stands at the bottom, nothing sideways ` + JSON.stringify(m));
      // on opening the shadow follows where the drawer stands (it may open scrolled to the open entry, at 460 px at the very end)
      check(await ready(ev, `(() => { const x = ${SH}; return !!x && x.more === (x.sh_ - x.st - x.ch > 2) && (x.sh !== 'none') === x.more; })()`, 20), `${tag}: on opening the shadow over the foot matches the drawer's place (#5896) ` + JSON.stringify(await ev(SH)));
      await ev(`(() => { document.querySelector('#side').scrollTop = 0; return 1; })()`);
      check(await ready(ev, shadow(true), 20), `${tag}: at the top of the list a shadow over the foot says more entries follow (#5896) ` + JSON.stringify(await ev(SH)));
      await ev(toEnd); await sleep(150);
      m = (await ev(M)) || {};
      check(await ready(ev, shadow(false), 20), `${tag}: at the end of the list the shadow over the foot is gone (#5896) ` + JSON.stringify(await ev(SH)));
      await shot(`p21088a-end-${w}.png`);
      check(m.cash && m.cash.bottom <= m.dockTop + 1 && m.under.length === 0, `${tag}: at the end of the list Cash book stands above the foot ` + JSON.stringify(m));
      check(m.scrolls, `${tag}: the office panel is longer than the screen here (else the test proves nothing) ` + JSON.stringify(m));
      await ev(`(() => { const sc = document.querySelector('#side'); sc.scrollTop = Math.max(0, sc.scrollTop - 80); return 1; })()`);
      check(await ready(ev, shadow(true), 20), `${tag}: scrolled back up the shadow is there again (#5896) ` + JSON.stringify(await ev(SH)));
      await ev(`(() => { history.back(); return 1; })()`); await ready(ev, `!document.querySelector('#side.open')`, 20);
    }
    // 2.1091.0 (#5896): a list that fits the screen has no shadow over the foot
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 460, height: 3000}});
    await nav(B + 'static/icon.svg'); await nav(B + '#office');
    check(await ready(ev, `!!document.querySelector('#top .menu') && !!S.booted && S.route.mod === 'office'`, 80), 'tall: the office is up');
    await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#side.open') && !!document.querySelector('#side [data-ofm="cashbook"]')`, 40), 'tall: the drawer opens with Cash book');
    await ready(ev, `(() => { const s = document.querySelector('#side'); return s && Math.abs(s.getBoundingClientRect().left) < 1; })()`, 20);
    const t = (await ev(M)) || {};
    check(t.scrolls === false, 'tall: the whole list fits the screen (else the case proves nothing) ' + JSON.stringify(t));
    check(await ready(ev, shadow(false), 20), 'tall: a list that fits has no shadow over the foot (#5896) ' + JSON.stringify(await ev(SH)));
    await ev(`(() => { history.back(); return 1; })()`); await ready(ev, `!document.querySelector('#side.open')`, 20);
    // the computer sidebar stays as it is: no shadow over its foot, even while its list goes on below
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 500}});
    await nav(B + 'static/icon.svg'); await nav(B + '#office');
    check(await ready(ev, `!!S.booted && S.route.mod === 'office' && !!document.querySelector('#side .srow, #side [data-ofm]')`, 80), 'desktop: the office and its sidebar are up');
    const dsk = await ev(SH);  // null = this sidebar has no foot (sidebar B): nothing to shade either
    check(!dsk || dsk.sh === 'none', 'desktop: no shadow over the sidebar foot (#5896) ' + JSON.stringify(dsk));
  }, true);

  console.log(`p21088_a_drawer_end_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
