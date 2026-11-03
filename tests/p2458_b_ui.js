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
      await sleep(250);
      s = await ev(`${SPLIT}('#side .sbmr .srbn')`);
      check(s.length === 0, `#3880 ${px} px: no word split in the drawer: ` + JSON.stringify(s));
      // 2.499.0 (#4047): nothing in the drawer is cut: no "…" class, no text beyond its box in either direction
      const cut = await ev(`[...document.querySelectorAll('#side .sbmr .srbn')].filter(n => n.classList.contains('srcut') || getComputedStyle(n).getPropertyValue('-webkit-line-clamp') !== 'none' || n.scrollWidth > n.clientWidth + 1 || n.scrollHeight > n.clientHeight + 1).map(n => n.textContent)`);
      check(cut.length === 0, `#4047 ${px} px: no area name cut in the drawer: ` + JSON.stringify(cut));
      await shot(`p2458-${px}-drawer.png`);
    }
    await ev(`(() => { const n = document.querySelector('#side .sbmr .srbn'); n.textContent = 'Donaudampfschifffahrtsgesellschaft'; sbb_fit(); return 1; })()`);
    // 2.499.0 (#4047, replaces the "…" of #3880 on the phone): a word far too long breaks inside the word, all of it to read
    const lng = await ev(`(() => { const n = document.querySelector('#side .sbmr .srbn'); return {cut: n.classList.contains('srcut'), brk: n.classList.contains('srbrk'), sw: n.scrollWidth, cw: n.clientWidth, sh: n.scrollHeight, ch: n.clientHeight, lines: Math.round(n.getBoundingClientRect().height / parseFloat(getComputedStyle(n).fontSize))}; })()`);
    check(!lng.cut && lng.brk && lng.sw <= lng.cw + 1 && lng.sh <= lng.ch + 1 && lng.lines >= 2, '#4047: far too long: broken over lines, never "…" ' + JSON.stringify(lng));

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
