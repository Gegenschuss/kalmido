// 2.583.0 (#4840) UI test, own container (start.sh, isolated test database), Firefox. Invented data only.
// kalmido-suite:
// Full width in all areas: at 1920 px the content of task list, office, contacts and documents is wider than 96rem, the
// project list's time column shows "3:00 Std" untruncated; 1440 x 900 and 390 px have no sideways overflow.
// freelancer-matrix: Breiten (alice has no organisation; the widths do not depend on the workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2583_b_fullwidth', check, shots: 'P2583B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['office', 'contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'office,contacts,docs'});
  const L = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  for (const t of ['Write the brief', 'Book the studio', 'Cast two actors']) await call('POST', '/api/tasks', {title: t, list_id: L, due: '2026-11-12'});
  // 2.583.0 (#4840 Teil F): a project with many columns (two text fields, a number field) for the table rows
  const G = (await call('POST', '/api/lists', {name: 'Shoot plan', kind: 'project'})).id;
  const FT1 = (await call('POST', `/api/lists/${G}/fields`, {name: 'Location', type: 'text'})).id;
  const FT2 = (await call('POST', `/api/lists/${G}/fields`, {name: 'Notes for crew', type: 'text'})).id;
  const FN = (await call('POST', `/api/lists/${G}/fields`, {name: 'Budget', type: 'number'})).id;
  await call('PATCH', `/api/lists/${G}`, {columns: ['due', 'prio', 'f:' + FT1, 'f:' + FT2, 'f:' + FN, 'tags', 'progress', 'created']});
  const GT = (await call('POST', '/api/tasks', {title: 'Prepare the detailed production schedule for the whole shoot with travel, crew, catering and the rented equipment', list_id: G, due: '2026-11-12', priority: 5,
    fields: {[FT1]: 'Old harbour warehouse at the north pier, gate three', [FT2]: 'Bring warm clothes, the hall is not heated before ten', [FN]: 1250}})).id;
  await call('POST', '/api/tasks', {title: 'Book the studio', list_id: G, fields: {[FN]: 80}});

  await firefox(async ({cmd, ev, ctx, nav, until, shot}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    const M = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}), v = document.querySelector('#view'); if (!e) return null;
      return {w: e.getBoundingClientRect().width, rem: parseFloat(getComputedStyle(document.documentElement).fontSize), over: v.scrollWidth - v.clientWidth}; })()`;
    const PAGES = [['task list', '#l/' + L, '#view .lwrap'], ['office', '#office', '#view .ofwrap'], ['contacts', '#contacts', '#view .ofwrap, #view .ctview'], ['documents', '#docs', '#view .dc-wrap, #view .abview']];
    for (const [vw, vh] of [[390, 844], [1440, 900], [1920, 1080]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      for (const [name, hash, sel] of PAGES) {
        if (vw < 768 && name === 'office') continue;
        await nav(B + '?w=' + vw + hash);
        const m = await until(`!!S.booted && (${M(sel)})`).catch(() => null);
        if (!m) { check(false, `${vw}px ${name}: ${sel} shows`); continue; }
        if (vw === 1920) check(m.w > 96 * m.rem, `${vw}px ${name}: wider than 96rem ` + JSON.stringify(m));
        check(m.over <= 1, `${vw}px ${name}: no sideways overflow ` + JSON.stringify(m));
      }
    }
    // the project list's time column: "3:00 Std" is not cut off at 1920 px (widths scrolled in with the column)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1920, height: 1080}});
    await nav(B + '?w=1920#l/' + L);
    await until(`!!S.booted && !!document.querySelector('#view .lwrap')`);
    const w = await ev(`(() => { const c = getComputedStyle(document.documentElement), r = parseFloat(c.fontSize); const probe = document.createElement('span'); probe.className = 'lc lc-time'; probe.style.cssText = 'position:absolute;visibility:hidden'; probe.textContent = '3:00 Std'; document.querySelector('#view .lwrap').appendChild(probe);
      const o = {sw: probe.scrollWidth, cw: probe.clientWidth}; probe.remove(); return o; })()`);
    check(w.sw <= w.cw, 'the time column holds "3:00 Std" untruncated ' + JSON.stringify(w));

    // 2.583.0 (#4840 Teil F): rows like a table. Many columns at 2560 px: the title gets at most about 40rem (unless the text
    // columns are at their widest), a text column is wider than at 1440 px, titles and cells line up, the number sits right
    const TB = `(() => { const r = document.querySelector('#view .trow[data-id="${GT}"]'), h = document.querySelector('#view .lchead'), v = document.querySelector('#view');
      if (!r) return null; const rem = parseFloat(getComputedStyle(document.documentElement).fontSize), vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).display !== 'none';
      const cell = k => r.querySelector('.lcols .lc[data-k="' + k + '"]'), t1 = cell('f:${FT1}'), n = cell('f:${FN}'), nb = n && n.querySelector('.cfx,span,b,button') || n;
      let align = 0; if (vis(h)) for (const c of r.querySelectorAll('.lcols .lc')) { const hc = h.querySelector('.lc[data-k="' + c.dataset.k + '"]'); if (vis(c) && vis(hc)) align = Math.max(align, Math.abs(c.getBoundingClientRect().right - hc.getBoundingClientRect().right)); }
      return {rem, list: document.querySelector('#view .lwrap').getBoundingClientRect().width / rem, title: r.querySelector('.tmain').getBoundingClientRect().width / rem,
        t1: vis(t1) ? t1.getBoundingClientRect().width / rem : 0, t1cut: vis(t1) ? t1.scrollWidth - t1.clientWidth : -1, grow: [...r.querySelectorAll('.lcols .lc.lcgw')].filter(vis).length,
        nJust: n ? getComputedStyle(n).justifyContent : '', nGap: vis(n) && nb ? n.getBoundingClientRect().right - nb.getBoundingClientRect().right : -1,
        shown: [...r.querySelectorAll('.lcols .lc')].filter(vis).length, fit: r.querySelector('.lcols')?.getAttribute('style') || '', cw: t1 ? getComputedStyle(t1).width : '', lw: v.style.getPropertyValue('--lw'), align: Math.round(align), over: Math.max(v.scrollWidth - v.clientWidth, document.documentElement.scrollWidth - innerWidth)}; })()`;
    const tb = {};
    for (const [vw, vh] of [[390, 844], [1440, 900], [1920, 1080], [2560, 1440]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + '?w=' + vw + '#l/' + G);
      // wait for the real state: the row carries its column widths (lcFit) and the field cell its text (under a loaded Mac the first
      // render came before them once)
      let m = tb[vw] = await until(`!!S.booted && (() => { const x = ${TB}; return x && (${vw} < 768 || x.fit && x.t1cut >= 0) ? x : null; })()`).catch(() => null);
      // 2560 px: the text columns grow a moment after the first drawing (Firefox styles the row again once the list's width is
      // known, lw_sync); wait for that state, the plain measurement stays when it never comes
      if (m && vw === 2560) m = tb[vw] = await until(`(() => { const x = ${TB}; return x && x.t1 > 7.5 ? x : null; })()`).catch(() => null) || await ev(TB) || m;
      if (!m) { check(false, `${vw}px: the many-column row shows`); continue; }
      check(m.over <= 1, `${vw}px many columns: no sideways overflow ` + JSON.stringify(m));
      if (vw >= 1440) check(m.align <= 2, `${vw}px many columns: column titles and cells line up ` + JSON.stringify(m));
      if (vw >= 1920) await shot(`p2583b-${vw}-columns.png`);
    }
    const a = tb[2560], b = tb[1440];
    if (a && b) {
      check(a.list >= 96 && a.shown === 8, '2560 px: the list is wider than 96rem and all eight columns stand in the first line ' + JSON.stringify(a));
      check(a.grow === 3 && (a.title <= 42 || a.t1 >= 21.9), '2560 px: the title gets at most about 40rem while the text columns are not at their widest ' + JSON.stringify(a));
      check(a.t1 > b.t1 + 2, 'the text column is wider at 2560 px than at 1440 px ' + JSON.stringify({a: a.t1, b: b.t1}));
      check(a.nJust === 'flex-end' && a.nGap >= -0.5 && a.nGap <= 2, 'the number column is right-aligned in its column ' + JSON.stringify(a));
    }
  }, false);

  console.log(`p2583_b_fullwidth: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
