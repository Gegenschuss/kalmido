// 2.742.0 A UI test (#4858 split view on a wide screen), own container (start.sh, isolated test database), Firefox with a mouse.
// kalmido-suite: fresh
// Invented data only. alice has no organisation (freelancer-matrix: Geteilte Ansicht).
// - the switch in Settings > Appearance only from about 90 rem window width (not at 1200 px); off = no iframe, splitview.js not loaded
// - on: the right half is an iframe /?split=1 (the normal app, any route), the left app measures only its half (innerWidth);
// 2.891.0 (#5358): from 90 rem (was 160) and the normal app on the right (was /?mini=1&split=1, the mini mode); the use itself: p2891_a_splitview_abnahme_ui.js
//   only that address may be framed, by the app itself (frame-ancestors 'self' / SAMEORIGIN), "/" stays DENY
// - "Open on the right" in the menu of a project and of a task shows its route in the right half; off it is not in the menu
// - the right copy does not overwrite the main window's UI state (lastKey); the right route is remembered (splR)
// - the grip: a drag makes the right half wider, the width holds over a reload and goes to the account (setting look)
// 2.1040.0 (#5813): the settings show the split view from the lowest threshold (66 rem, both halves' minimum; 1000 px: nothing),
//   "Split from window width" in px moves the threshold (1200 px with 1100: offered), a smaller value is raised to the lower bound
//   with a hint, Default empties it; the value is the person's (setting look splMin); the line between the halves is always visible
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2742_a_splitview', check, shots: 'P2742A_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Harbour shoot', kind: 'project'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Scout the north pier', list_id: L})).id;
  await call('POST', '/api/tasks', {title: 'Rent the dolly', list_id: L});

  // the server: only the split view's address may be framed, and only by the app itself
  const hs = async u => { const r = await fetch(B + u, {headers: {Cookie: CA}}); return {csp: r.headers.get('content-security-policy') || '', xfo: r.headers.get('x-frame-options') || ''}; };
  const h0 = await hs(''), h1 = await hs('?split=1'), h2 = await hs('?mini=1');  // 2.891.0 (#5358): ?split=1 without mini=1
  check(/frame-ancestors 'none'/.test(h0.csp) && h0.xfo === 'DENY', '"/" stays DENY ' + JSON.stringify(h0));
  check(/frame-ancestors 'self'/.test(h1.csp) && !/frame-ancestors 'none'/.test(h1.csp) && h1.xfo === 'SAMEORIGIN', '/?split=1 may be framed by the app itself ' + JSON.stringify(h1));
  check(/frame-ancestors 'none'/.test(h2.csp) && h2.xfo === 'DENY', 'an own window without split stays DENY ' + JSON.stringify(h2));

  await firefox(async ({cmd, ev, ctx, nav, until, drag, shot}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    // a new load every time (an address that differs only in its hash would stay the same page): ?n=<counter>
    let nn = 0; const load = h => nav(B + '?n=' + (++nn) + h);
    const booted = () => until(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view')`, {timeout: 30000});
    const openLook = async () => {
      await ev(`(document.querySelectorAll('.smodal').forEach(m => m.remove()), loadModule('settings').then(() => { settingsModal('look'); return 1; }))`);
      return until(`!!document.querySelector('.smodal #s-lookin')`);
    };
    const FR = `document.querySelector('#splitpane iframe.splitfr')`;
    const frHash = `(() => { try { return ${FR}.contentWindow.location.hash; } catch { return null; } })()`;
    const frDoc = `(() => { try { return ${FR}.contentDocument; } catch { return null; } })()`;

    // ---- a window of 1000 px: no switch (2.891.0 (#5358): offered from 90 rem = 1440 px, was 160 rem; 1600 px has it now)
    // 2.1040.0 (#5813): was 1200 px; the settings show it from the lowest threshold now (66 rem = 1056 px), 1000 px is below it
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1000, height: 1000}});
    await load('#today'); await booted();
    check(await openLook(), '1000 px: Settings > Appearance opens');
    check(await ev(`!document.querySelector('#s-split') && !document.querySelector('#s-splmin') && spl_offer() === false`), '1000 px: no switch for the split view');

    // ---- 2.1040.0 (#5813): 1200 px - the section with "Split from window width"; the standard 1440 px does not split here
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1200, height: 1000}});
    await load('#today'); await booted();
    check(await openLook(), '1200 px: Settings > Appearance opens');
    const s0 = await until(`(() => { const f = document.querySelector('#s-splmin'), i = document.querySelector('#s-splinfo'), l = document.querySelector('label[for="s-splmin"]');
      return f && i && l ? {val: f.value, ph: f.placeholder, info: i.textContent, label: l.textContent, offer: spl_offer(), sw: !!document.querySelector('#s-split'), vw: document.documentElement.clientWidth} : null; })()`);
    check(s0 && s0.sw && s0.label === 'Split from window width' && s0.val === '' && s0.ph === '1440' && s0.offer === false, '1200 px: the switch and the empty field (standard 1440) show, not offered yet ' + JSON.stringify(s0));
    check(s0 && s0.info.includes(`Your window: ${s0.vw} px`) && s0.info.includes('Split from 1440 px.'), '1200 px: the line says the window width and the threshold ' + JSON.stringify(s0));
    const typeMin = v => ev(`(() => { const f = document.querySelector('#s-splmin'); f.focus(); f.value = ${JSON.stringify(v)}; f.dispatchEvent(new Event('input', {bubbles: true})); f.dispatchEvent(new Event('change', {bubbles: true})); f.blur(); return 1; })()`);
    await typeMin('1100');
    const s1 = await until(`(() => { const i = document.querySelector('#s-splinfo').textContent; return spl_offer() && LS.get('splMin', 0) === 1100 && !i.includes('Split from') ? {val: document.querySelector('#s-splmin').value, info: i} : null; })()`);
    check(s1 && s1.val === '1100', '1100 px typed: the split view is offered at 1200 px ' + JSON.stringify(s1));
    const lk = await (async () => { for (let i = 0; i < 40; i++) { const s = (await call('GET', '/api/state')).settings || {}; try { const o = JSON.parse(s.look || '{}'); if (o.splMin === 1100) return o; } catch { /* not yet */ } await sleep(250); } return null; })();
    check(!!lk, 'the threshold is the person\'s (setting look splMin)');
    await typeMin('800');
    const s2 = await until(`(() => { const f = document.querySelector('#s-splmin'), i = document.querySelector('#s-splinfo').textContent, lo = spl_lo();
      return f.value === String(lo) && LS.get('splMin', 0) === lo ? {lo, info: i} : null; })()`);
    check(s2 && s2.lo >= 1050 && s2.lo <= 1060 && s2.info.includes(`At least ${s2.lo} px, otherwise neither half has enough room.`), 'a too small value becomes the lower bound with a hint ' + JSON.stringify(s2));
    await ev(`document.querySelector('[data-m="s-splmin-std"]').click(), 1`);
    const s3 = await until(`(() => { const f = document.querySelector('#s-splmin'), i = document.querySelector('#s-splinfo').textContent; return f.value === '' && LS.get('splMin', null) == null && !spl_offer() && i.includes('Split from 1440 px.') ? i : null; })()`);
    check(!!s3, 'Default: the field is empty, the standard applies again (not offered at 1200 px) ' + JSON.stringify(s3));
    const lkStd = await (async () => { for (let i = 0; i < 40; i++) { const s = (await call('GET', '/api/state')).settings || {}; try { if (JSON.parse(s.look || '{}').splMin == null) return true; } catch { /* not yet */ } await sleep(250); } return false; })();
    check(lkStd, 'Default reached the account (no splMin)');

    // ---- 2800 px: the switch, off = nothing loaded
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 2800, height: 1100}});
    await load('#today'); await booted();
    check(await ev(`!document.querySelector('iframe.splitfr') && typeof spl_sync === 'undefined'`), 'off: no iframe, splitview.js not loaded');
    check(await ev(`!listMenuItems(${L}, document.body).some(x => x && x.cls === 'msplit')`), 'off: "Open on the right" is not in the project menu');
    await openLook();
    check(await until(`!!document.querySelector('#s-split') && !document.querySelector('#s-split').checked`), '2800 px: the switch is offered, off');
    await ev(`document.querySelector('#s-split').click()`);
    const up = await until(`(() => { const f = ${FR}, d = ${frDoc}; return f && d && !d.documentElement.classList.contains('mini') && d.querySelector('#view') ? {src: f.getAttribute('src'), hash: ${frHash}} : null; })()`, {timeout: 30000});
    check(up && /^\/\?split=1#/.test(up.src), 'on: the right half is an iframe /?split=1, the normal app (no mini mode) ' + JSON.stringify(up));  // 2.891.0 (#5358): was /?mini=1&split=1 in mini mode
    const lay = await ev(`(() => { const p = document.querySelector('#splitpane').getBoundingClientRect(), vw = document.documentElement.clientWidth;
      return {vw, iw: innerWidth, pane: Math.round(p.width), left: Math.round(p.left), body: Math.round(document.body.getBoundingClientRect().width), split: document.documentElement.classList.contains('split-on')}; })()`);
    // 2.1040.0 (#5813): the line in the middle is always there (4 px, the border colour, not transparent), the grip around it wider
    const ln = await ev(`(() => { const g = document.querySelector('#splitpane .splgrip'), a = getComputedStyle(g, '::after'); return {w: a.width, bg: a.backgroundColor, grip: g.getBoundingClientRect().width}; })()`);
    check(ln.w === '4px' && !/rgba\(0, 0, 0, 0\)|transparent/.test(ln.bg) && ln.grip > 4, 'the line between the halves is visible without hovering ' + JSON.stringify(ln));
    check(lay.split && Math.abs(lay.pane - lay.vw / 2) <= 2 && Math.abs(lay.body + lay.pane - lay.vw) <= 2, 'on: half and half, the left app in the left half ' + JSON.stringify(lay));
    check(Math.abs(lay.iw - lay.body) <= 2, 'on: innerWidth of the main window is its half ' + JSON.stringify(lay));
    await ev(`document.querySelectorAll('.smodal').forEach(m => m.remove()), 1`);

    // ---- "Open on the right": a project, then a task; the main window's state stays its own
    const lk0 = await ev(`localStorage.getItem('tasks.lastKey')`);
    const it = await ev(`(() => { const x = listMenuItems(${L}, document.body).find(x => x && x.cls === 'msplit'); if (!x) return ''; x.fn(); return x.label; })()`);
    check(it === 'Open on the right', 'on: the project menu has "Open on the right" ' + it);
    const lst = await until(`(() => { const d = ${frDoc}; return ${frHash} === '#l/${L}' && d && [...d.querySelectorAll('#view .trow .ttl')].some(e => /Scout the north pier/.test(e.textContent)); })()`, {timeout: 20000});
    check(lst, 'the project shows in the right half');
    check(await ev(`location.hash === '#today' && localStorage.getItem('tasks.lastKey') === ${JSON.stringify(lk0)}`), 'the right copy leaves the main window\'s lastKey alone ' + JSON.stringify(await ev(`[location.hash, localStorage.getItem('tasks.lastKey')]`)));
    check(await until(`LS.get('splR', '') === '#l/${L}'`), 'the right route is remembered (splR)');
    await shot('p2742a-split-list.png');
    // 2.1040.0 (#5813): the account has a look since the threshold part above, and a reload adopts the account's (lookAdopt):
    // wait until "on" and the right route have reached it (the look goes out after a short pause)
    const lkOn = await (async () => { for (let i = 0; i < 40; i++) { const s = (await call('GET', '/api/state')).settings || {}; try { const o = JSON.parse(s.look || '{}'); if (o.split === true && o.splR === '#l/' + L) return true; } catch { /* not yet */ } await sleep(250); } return false; })();
    check(lkOn, 'on and the right route reached the account before the reload');
    await load('#l/' + L); await booted();
    check(await until(`(() => { const d = ${frDoc}; return !!(d && d.querySelector('#view')); })()`, {timeout: 30000}), 'after a reload the right half comes back');
    check(await ev(`${frHash} === '#l/${L}'`), 'after a reload the right half shows the remembered route');
    await until(`!!document.querySelector('#view .trow[data-id="${T}"]')`);
    await ev(`(() => { taskMenu(document.querySelector('#view .trow[data-id="${T}"]'), ${T}); return 1; })()`);
    // like "Open in its own window" it stands in the menu's second level "More…"
    await until(`[...document.querySelectorAll('[role=menu] button.msubm')].some(b => /More/.test(b.textContent))`);
    await ev(`[...document.querySelectorAll('[role=menu] button.msubm')].find(b => /More/.test(b.textContent)).click(), 1`);
    check(await until(`!!document.querySelector('[role=menu] button.msplit')`), 'the task menu has "Open on the right" (under More…)');
    await ev(`document.querySelector('[role=menu] button.msplit').click(), 1`);
    check(await until(`(() => { const d = ${frDoc}; return !!(d && d.querySelector('#detail.open, #app.detail-open')) && /Scout the north pier/.test(d.querySelector('#detail')?.textContent || ''); })()`, {timeout: 20000}),
      'the task opens in the right half ' + JSON.stringify(await ev(frHash)));

    // ---- the grip: 300 px to the left = the right half 300 px wider; holds over a reload, goes to the account
    const g = await ev(`(() => { const r = document.querySelector('#splitpane .splgrip').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, pane: document.querySelector('#splitpane').getBoundingClientRect().width}; })()`);
    await drag(g.x, g.y, -300, 0);
    const w1 = await until(`(() => { const w = document.querySelector('#splitpane').getBoundingClientRect().width; return Math.abs(w - ${g.pane} - 300) <= 8 ? {w, rem: LS.get('splW', 0)} : null; })()`);
    check(w1 && w1.rem > 0, 'the grip makes the right half 300 px wider ' + JSON.stringify({before: g.pane, after: w1}));
    check(await ev(`Math.abs(innerWidth - document.body.getBoundingClientRect().width) <= 2`), 'after the drag innerWidth is still the left half');
    const look = await (async () => { for (let i = 0; i < 40; i++) { const s = (await call('GET', '/api/state')).settings || {}; try { const o = JSON.parse(s.look || '{}'); if (o.split === true && o.splW > 0) return o; } catch { /* not yet */ } await sleep(250); } return null; })();
    check(look && w1 && Math.abs(look.splW - w1.rem) < 0.01, 'on and width are the person\'s (setting look) ' + JSON.stringify(look));
    await load('#today'); await booted();
    const w2 = await until(`(() => { const p = document.querySelector('#splitpane'); return p ? p.getBoundingClientRect().width : 0; })()`, {timeout: 30000});
    check(w1 && Math.abs(w2 - w1.w) <= 2, 'the width holds over a reload ' + JSON.stringify({w1, w2}));

    // ---- off again: no iframe, the whole width for the app, no menu entry; after a reload nothing of it loads
    await openLook();
    await ev(`document.querySelector('#s-split').click(), 1`);
    check(await until(`!document.querySelector('iframe.splitfr') && !document.documentElement.classList.contains('split-on') && Math.abs(innerWidth - document.documentElement.clientWidth) <= 2 && Math.abs(document.body.getBoundingClientRect().width - document.documentElement.clientWidth) <= 1`),
      'off: the iframe goes, the app has the whole width');
    await ev(`document.querySelectorAll('.smodal').forEach(m => m.remove()), 1`);
    check(await ev(`!listMenuItems(${L}, document.body).some(x => x && x.cls === 'msplit')`), 'off: no "Open on the right" in the menu');
    // the account has "off" (the look goes out after a short pause; a reload before it would adopt the account's older "on")
    const off = await (async () => { for (let i = 0; i < 40; i++) { const s = (await call('GET', '/api/state')).settings || {}; try { if (JSON.parse(s.look || '{}').split === false) return true; } catch { /* not yet */ } await sleep(250); } return false; })();
    check(off, 'off goes to the account (setting look)');
    await load('#today'); await booted();
    await ev(`new Promise(r => setTimeout(() => r(1), 0))`);  // spl_check's timer (main.js, queued at the start) has had its turn
    const st = await ev(`({fr: !!document.querySelector('iframe.splitfr'), mod: typeof spl_sync, split: LS.get('split', null), look: S.settings.look, scripts: [...document.querySelectorAll('script[data-ld]')].map(x => x.dataset.ld).join(',')})`);
    check(!st.fr && st.mod === 'undefined', 'off after a reload: no iframe, splitview.js not loaded ' + JSON.stringify(st));
  }, false);

  console.log(`p2742_a_splitview: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
