// kalmido-suite: fresh
// 2.458.0 UI tests, own container (start.sh), jsdom + Firefox (layout at 320 / 412 / 840 px). Invented data, as a person without an organisation:
// freelancer-matrix: tasks
// - #3880: the names of the areas never break inside a word (bar at 840 px, drawer at 412 and 320 px), a word too wide gets smaller or ends in "…"
// - #3838: the monthly repeat text is one whole text per language
// - #3855 at 320 px: read-later buttons below the title, the meal plan breaks between words, a number stays with its sign,
//   one "…" on the head of Events today, long hints in fields cut, all-day week entries one cut line
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const firefox = require('./ff')({tag: 'p2458_b_ui', check, shots: 'P2458B_SHOTS'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const FEATS = 'cal,habits,review,family,reading,events,bookmarks';
// a word of a name split over two lines: the first text fragment of a word and its end stand on different lines
const SPLIT = `(sel => [...document.querySelectorAll(sel)].filter(n => n.getClientRects().length && !n.classList.contains('srcut')).flatMap(n => {
  const t = n.firstChild; if (!t) return []; const out = []; const re = /\\S+/g; let m;
  while ((m = re.exec(t.data))) { const r = document.createRange(); r.setStart(t, m.index); r.setEnd(t, m.index + m[0].length); if (new Set([...r.getClientRects()].map(x => Math.round(x.top))).size > 1 || r.getBoundingClientRect().width > n.clientWidth + 1) out.push(m[0]); }
  return out; }))`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEATS + ',time,wiki,stats,contacts,office,clients,budget,health,home'});

  // ================= #3838 (the language files stay whole texts, jsdom)
  const w = await boot({user: 'alice'});
  const lbl = r => w.eval(`repeatLabelBase(${JSON.stringify(r)})`);
  check(lbl('FREQ=MONTHLY;BYMONTHDAY=5') === 'Monatlich am 5.', '#3838 on a day: ' + lbl('FREQ=MONTHLY;BYMONTHDAY=5'));
  check(lbl('FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=5') === 'Alle 3 Monate am 5.', '#3838 every 3 months: ' + lbl('FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=5'));
  check(lbl('FREQ=MONTHLY;BYDAY=2TU') === 'Monatlich am zweiten Dienstag', '#3838 nth: ' + lbl('FREQ=MONTHLY;BYDAY=2TU'));
  check(lbl('FREQ=MONTHLY;INTERVAL=2;BYDAY=-1FR') === 'Alle 2 Monate am letzten Freitag', '#3838 last: ' + lbl('FREQ=MONTHLY;INTERVAL=2;BYDAY=-1FR'));
  check(lbl('FREQ=MONTHLY') === 'Monatlich', '#3838 plain');
  const src = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'quickadd.js'), 'utf8');
  check(!/' ' \+ tr\('on /.test(src), '#3838: nothing glued together any more');

  // ================= layout
  const L = (await call('POST', '/api/lists', {name: 'Plan'})).id;
  await call('POST', '/api/tasks', {list_id: L, title: 'Linsensuppe mit Brot', due: new Date().toISOString().slice(0, 10), all_day: true});
  await firefox(async ({cmd, ev, nav, ctx, shot, until}) => {
    const size = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    await nav(B + '#today');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await size(840, 700); await nav(B + '#today');
    check(await until(() => ev(`document.querySelectorAll('#srail .srbn').length > 3`)), '#3880 840 px: the bar is there');
    await sleep(200);
    let s = await ev(`${SPLIT}('#srail .srbn')`);
    check(s.length === 0, '#3880 840 px: no word split in the bar: ' + JSON.stringify(s));
    await shot('p2458-840-rail.png');
    for (const px of [412, 320]) {
      await size(px, 700); await nav(B + `?w=${px}#today`);
      await until(() => ev(`!!document.querySelector('#top .menu') && !!S.booted`));
      await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu').click(); return 1; })()`);
      check(await until(() => ev(`document.querySelectorAll('#side .sbmr .srbn').length > 3`)), `#3880 ${px} px: the drawer's row is there`);
      await until(() => ev(`${SPLIT}('#side .sbmr .srbn').length === 0`));  // 2.499.0 (#4047): the fit runs in a frame after the draw: wait for its result, not a fixed time
      s = await ev(`${SPLIT}('#side .sbmr .srbn')`);
      check(s.length === 0, `#3880 ${px} px: no word split in the drawer: ` + JSON.stringify(s));
      // 2.499.0 (#4047): nothing in the drawer is cut: no "…" class, no text beyond its box in either direction
      const cut = await ev(`[...document.querySelectorAll('#side .sbmr .srbn')].filter(n => n.classList.contains('srcut') || getComputedStyle(n).getPropertyValue('-webkit-line-clamp') !== 'none' || n.scrollWidth > n.clientWidth + 1 || n.scrollHeight > n.clientHeight + 1).map(n => n.textContent)`);
      check(cut.length === 0, `#4047 ${px} px: no area name cut in the drawer: ` + JSON.stringify(cut));
      // 2.660.0 (#5103): this Firefox runs with "reduce motion" (ff.js): every size the fit set was a .01 ms transition, the fit
      // measured the old size and its watcher fitted again every other frame ("Rückblick" 9 / 10 px, split in every other frame,
      // red now and then). A fit (as after any redraw) ends the fitting: in the next 30 frames no further fit, no size changes
      const calm = await ev(`new Promise(res => { const f0 = window.sbb_fit, sz = () => [...document.querySelectorAll('#side .sbmr .srbn')].map(n => n.style.fontSize).join(); let runs = 0, flips = 0, k = 0; window.sbb_fit = () => { runs++; f0(); }; f0(); let last = sz(); const tick = () => { const s = sz(); if (s !== last) { flips++; last = s; } if (++k < 30) requestAnimationFrame(tick); else { window.sbb_fit = f0; res({runs, flips, sizes: s}); } }; requestAnimationFrame(tick); })`);
      check(calm.runs === 0 && calm.flips === 0, `#5103 ${px} px: a fit is final, it does not wake itself: ` + JSON.stringify(calm));
      // 2.651.0 (#5063): the names' type grows after the fit without a redraw, resize or font event (in the CI a font load did
      // it: "Rückblick" drawn in 10 px after it was measured in 9 px): the app fits them again by itself
      if (px === 320) {
        await ev(`(() => { const st = document.createElement('style'); st.id = 'p2458grow'; st.textContent = 'html body #side .sbmr .srb{font-size:.75rem}'; document.head.append(st); return 1; })()`);
        const GROWN = `(() => { const ns = [...document.querySelectorAll('#side .sbmr .srbn')]; return {fs: getComputedStyle(document.querySelector('#side .sbmr .srb')).fontSize, split: ${SPLIT}('#side .sbmr .srbn'), over: ns.filter(n => n.scrollWidth > n.clientWidth + 1).map(n => n.textContent), sizes: ns.map(n => n.style.fontSize)}; })()`;
        await until(async () => { const g = await ev(GROWN); return g.fs === '12px' && !g.split.length && !g.over.length; });
        const g = await ev(GROWN);
        check(g.fs === '12px' && !g.split.length && !g.over.length, '#5063 320 px: names that grow after the fit are fitted again: ' + JSON.stringify(g));
        await ev(`(() => { document.getElementById('p2458grow').remove(); return 1; })()`);
        check(await until(() => ev(`${SPLIT}('#side .sbmr .srbn').length === 0`)), '#5063 320 px: and again when they shrink back');
      }
      await shot(`p2458-${px}-drawer.png`);
    }
    await ev(`(() => { const n = document.querySelector('#side .sbmr .srbn'); n.textContent = 'Donaudampfschifffahrtsgesellschaft'; sbb_fit(); return 1; })()`);
    // 2.499.0 (#4047, replaces the "…" of #3880 on the phone): a word far too long stays whole, its column grows, the row scrolls sideways
    const lng = await ev(`(() => { const n = document.querySelector('#side .sbmr .srbn'), r = n.closest('.sbmr'), w = document.createRange(); w.selectNodeContents(n); const h = w.getClientRects().length; return {cut: n.classList.contains('srcut'), sw: n.scrollWidth, cw: n.clientWidth, lines: h, rsw: r.scrollWidth, rcw: r.clientWidth, ox: getComputedStyle(r).overflowX, st: r.getAttribute('style')}; })()`);
    check(!lng.cut && lng.sw <= lng.cw + 1 && lng.lines === 1 && lng.rsw > lng.rcw && lng.ox === 'auto', '#4047: far too long: whole, never "…" or split; the row scrolls ' + JSON.stringify(lng));

    await nav(B + '#today'); await sleep(300);
    // #3855 at 320 px: the real rules on small pieces of the pages
    const box = `(q => { const r = document.querySelector(q).getBoundingClientRect(); return {w: Math.round(r.width), top: Math.round(r.top), bottom: Math.round(r.bottom)}; })`;
    await ev(`(() => { const v = document.querySelector('#view'); v.innerHTML = '<link rel="stylesheet" href="css/bookmarks.css"><ul class="bmlist"><li class="bmrow"><span class="bmthumb"></span><div class="bmbody"><a class="bmtitle">Typografie und Lesbarkeit im Alltag</a></div><span class="bmacts"><a class="iconbtn"></a><a class="iconbtn"></a><a class="iconbtn"></a></span></li></ul>'
      + '<div class="fday"><span class="fdl">Montag, 3.</span><span class="fdm"><span class="fmeal"><a>Linsensuppe mit Spaghetti</a><button class="iconbtn"></button></span></span><button class="iconbtn"></button></div>'
      + '<div class="lyb lym"><div class="group cevtoday"><div class="ghead"><button class="iconbtn gact cvxtm"></button></div></div><button class="iconbtn lymore"></button></div>'; return 1; })()`);
    await until(() => ev(`getComputedStyle(document.querySelector('.bmacts')).justifyContent === 'flex-end'`).catch(() => false));
    const t = await ev(`${box}('.bmtitle')`), a = await ev(`${box}('.bmacts')`);
    check(t.w >= 180 && a.top >= t.bottom, '#3855: read later: the buttons below the title, it keeps the width: ' + JSON.stringify({t, a}));
    const m = await ev(`${box}('.fmeal a')`);
    check(m.w >= 110, '#3855: a meal gets the width: ' + JSON.stringify(m));
    check(await ev(`getComputedStyle(document.querySelector('.fmeal a')).overflowWrap`) === 'normal', '#3855: a meal breaks between words only');
    check((await ev(`${SPLIT}('.fmeal a')`)).length === 0, '#3855: no word of a meal split');
    check(await ev(`getComputedStyle(document.querySelector('.cvxtm')).display === 'none' && getComputedStyle(document.querySelector('.lymore')).display !== 'none'`), '#3855: one "…" on Events today');
    await shot('p2458-320-pieces.png');
    // #3855 the number and its sign
    check(await ev(`curMoney(12120.98, 'EUR') === '12.120,98\\u00a0€'`), '#3855: the number keeps its sign');
    // #3855 the hint of a narrow field
    check(await ev(`(() => { const i = document.createElement('input'); i.placeholder = 'x'; document.body.append(i); const t = getComputedStyle(i).textOverflow; i.remove(); return t; })()`) === 'ellipsis', '#3855: hints are cut');
  });
  console.log(`p2458_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL', e); process.exit(1); });
