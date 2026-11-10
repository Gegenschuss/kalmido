// 2.828.0 part C (#5463 calendar views readable with many events, #5464 the "Calendars" window tidied): Firefox, real layout,
// kalmido-suite: fresh
// freelancer-matrix: n/a (no route changed; the views and the window are drawn in the client only, tested as alice without an organisation)
// German, invented data only. Phone 390 x 844 (touch) and desktop 1280 x 800 (mouse).
// - phone week, three events at the same time: strips without letters (no cut word stumps), one "+3" over them; a tap on it
//   opens the day view with the three titles readable
// - day view after the week was scrolled to noon: the day starts at its first entry or 07:00 (the earlier), so 06:30 and 08:00
//   are in view without scrolling; the same grid keeps a position the person scrolled to
// - month: "+N weitere" is a button and opens that day
// - year on a desktop: all twelve months in view (December too); on a phone the chosen month is scrolled into view
// - "Calendars" window: the column heads read in full (scrollWidth <= clientWidth), "Fertig" closes; on a phone a row has
//   one switch (head "Anzeigen") and switching it off makes the calendar's events leave the week; the colour swatches are
//   named (no hex code) and 44 px under a finger
// With P2828C_SHOTS: pictures of the views.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2828_c_cal_ff_ui', check, shots: 'P2828C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const day = i => { const d = new Date(); d.setDate(d.getDate() + i); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'de'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'de', collab_all: true, modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'de', tour: 'done', features: 'cal,events'});
  const W = await call('POST', '/api/evcals', {name: 'Drehplanung', color: '#2dd4bf'});
  const P = await call('POST', '/api/evcals', {name: 'Büro und Buchhaltung mit sehr langem Kalendernamen', color: '#f5b041'});
  check(W.id && P.id, 'two calendars');
  const t0 = day(0), t1 = day(1);
  const evs = [[W, t0, '10:00', '11:00', 'Drehbesprechung'], [W, t0, '10:00', '11:00', 'Imagefilm Schnitt'], [P, t0, '10:00', '11:00', 'Stadtwerke Anruf'],
    [W, t0, '13:00', '14:00', 'Mittag'], [W, t0, '15:00', '16:00', 'Tonmischung'], [P, t1, '06:30', '07:00', 'Frühdreh'], [P, t1, '08:00', '09:00', 'Briefing']];
  for (const [c, d, a, b, title] of evs) { const r = await call('POST', '/api/events', {title, cal_id: c.id, start: `${d}T${a}`, end: `${d}T${b}`}); check(r.http < 300, 'event ' + title + ' ' + r.http); }
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(200); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  const start = async (ev, nav, mode) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.calMode', '"${mode}"'); localStorage.setItem('tasks.calDays', '7'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#cal');
  };
  const winOpen = async ev => { await ev(`(() => { document.querySelector('#view [data-act="ev-cals"]').click(); return 1; })()`); return ready(ev, `!!document.querySelector('.modal.evcmodal .evcrow [data-evcshow]')`); };
  // the column heads of the window: each shown head with its text and whether it is cut
  const HEADS = `JSON.stringify([...document.querySelectorAll('.evcmodal .cvxhead .cvxc')].filter(e => e.offsetParent && e.innerText.trim()).map(e => ({t: e.innerText.trim(), cut: e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1})))`;

  // ---- phone
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await start(ev, nav, 'week');
    check(await ready(ev, `[...document.querySelectorAll('#view .wcol[data-day="${t0}"] .wcev')].length >= 5`), 'phone week: the events of today drawn');
    await ev(`(() => { document.querySelector('#wbody').scrollTop = 9.5 * weekH(); return 1; })()`);
    const strips = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('#view .wcol[data-day="${t0}"] .wcev.wn3')].map(x => ({txt: x.innerText.trim(), w: Math.round(x.getBoundingClientRect().width)})))`));
    check(strips.length === 3 && strips.every(x => x.txt === '' && x.w > 0), 'phone week: three at once = three strips without letters ' + JSON.stringify(strips));
    const more = JSON.parse(await ev(`JSON.stringify((() => { const b = document.querySelector('#view .wcol[data-day="${t0}"] .wmore'); if (!b) return null; const r = b.getBoundingClientRect(); return {t: b.innerText.trim(), w: r.width, h: r.height, n: document.querySelectorAll('#view .wcol[data-day="${t0}"] .wmore').length}; })())`));
    check(more && more.t === '+3' && more.w > 20 && more.h >= 27 && more.n === 1, 'phone week: one "+3" over the group, big enough to tap ' + JSON.stringify(more));
    check(await ev(`[...document.querySelectorAll('#view .wcol[data-day="${t0}"] .wcev:not(.wn3)')].some(x => /Mittag/.test(x.innerText))`), 'phone week: a block alone keeps its title');
    await shot('p2828-c-week-phone.png');
    await ev(`(() => { document.querySelector('#view .wcol[data-day="${t0}"] .wmore').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view .week.oneday') && S.calMode === 'day' && S.calSel === '${t0}'`), 'phone: "+3" opens the day');
    check(await ready(ev, `['Drehbesprechung', 'Imagefilm', 'Stadtwerke'].every(t => [...document.querySelectorAll('#view .wcev')].some(x => x.innerText.includes(t.slice(0, 6))))`), 'phone day: the three titles readable');
    await shot('p2828-c-day-phone.png');

    // the year: the chosen month scrolled into view (January is at the top anyway)
    await ev(`(() => { S.calMode = 'year'; S.calSel = '${t0}'; LS.set('calMode', 'year'); renderView(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#cyear')`), 'phone: the year drawn');
    const mk = t0.slice(0, 7);
    check(await ready(ev, `(() => { const r = document.querySelector('#cyear [data-cym="${mk}"]').getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; })()`, 25), 'phone year: the current month in view');
    await shot('p2828-c-year-phone.png');

    // the window on a phone: one switch per row, its head "Anzeigen", the switch takes the calendar out of the week
    await ev(`(() => { S.calMode = 'week'; S.calSel = '${t1}'; LS.set('calMode', 'week'); renderView(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#view .wcev')].some(x => x.textContent.includes('Briefing'))`), 'phone week: "Briefing" before');
    check(await winOpen(ev), 'phone: the Calendars window opens');
    const heads = JSON.parse(await ev(HEADS));
    check(heads.length === 1 && heads[0].t === 'Anzeigen' && !heads[0].cut, 'phone window: one column head "Anzeigen", not cut ' + JSON.stringify(heads));
    const rowSw = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('.evcmodal .evcrow')].map(r => [...r.querySelectorAll('.swc')].filter(s => s.offsetParent).length))`));
    check(rowSw.length === 2 && rowSw.every(n => n === 1), 'phone window: one switch per calendar ' + JSON.stringify(rowSw));
    const name = await ev(`(() => { const e = [...document.querySelectorAll('.evcmodal .evcrow .evcn')].find(x => x.textContent.includes('Büro')); return e.scrollHeight <= e.clientHeight + 1 && e.innerText.includes('Kalendernamen') ? 'full' : e.innerText; })()`);
    check(name === 'full', 'phone window: the long name is not cut ' + name);
    await shot('p2828-c-window-phone.png');
    await ev(`(() => { document.querySelector('.evcmodal [data-evcshow="${P.id}"]').click(); return 1; })()`);
    check(await ready(ev, `![...document.querySelectorAll('#view .wcev')].some(x => x.textContent.includes('Briefing'))`), 'phone: switched off, "Briefing" leaves the week');
    // the row menu has Today / Plan
    await ev(`(() => { document.querySelector('.evcmodal [data-evcmenu="${W.id}"]').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('.menu-list [role="menuitem"]')].map(b => b.innerText).join('|').includes('In Heute')`), 'phone window: the row menu offers "In Heute" and "Beim Planen"');
    await ev(`(() => { const b = [...document.querySelectorAll('.menu-list [role="menuitem"]')].find(b => b.innerText.includes('Farbe')); b.click(); return 1; })()`);
    const pal = JSON.parse(await ev(`(async () => { for (let i = 0; i < 30 && !document.querySelector('#pop .cpal'); i++) await new Promise(r => setTimeout(r, 100)); return JSON.stringify([...document.querySelectorAll('#pop .cpal [data-c]')].map(b => ({l: b.getAttribute('aria-label'), w: b.getBoundingClientRect().width, h: b.getBoundingClientRect().height}))); })()`));
    check(pal.length === 9 && pal.every(p => p.l && !p.l.startsWith('#') && p.w >= 43 && p.h >= 43), 'phone: colour swatches named and 44 px ' + JSON.stringify(pal.slice(0, 2)));
    await ev(`(() => { closePop(); document.querySelector('.evcmodal [data-evcshow="${P.id}"]')?.click(); return 1; })()`);
    await ready(ev, `[...document.querySelectorAll('#view .wcev')].some(x => x.textContent.includes('Briefing'))`);
  }, true);

  // ---- desktop
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await start(ev, nav, 'week');
    check(await ready(ev, `S.route?.mod === 'cal' && !!document.querySelector('#view #wbody')`), 'desktop: the calendar loaded');
    await ev(`(() => { S.calSel = '${t0}'; renderView(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#view .wcol[data-day="${t0}"] .wcev')].length >= 5`), 'desktop week: the events of today drawn');
    // a block of two lines: the time above a one-line title cut with "…" (never broken in the middle of words)
    const blk = JSON.parse(await ev(`JSON.stringify([...document.querySelectorAll('#view .wcol[data-day="${t0}"] .wcev.wn3')].map(x => { const t = x.querySelector('.wct'), b = x.querySelector('b'); return {two: x.classList.contains('w2'), ws: getComputedStyle(t).whiteSpace, bt: Math.round(b.getBoundingClientRect().bottom), tt: Math.round(t.getBoundingClientRect().top), th: Math.round(t.getBoundingClientRect().height)}; }))`));
    check(blk.length === 3 && blk.every(x => x.two && x.ws === 'nowrap' && x.tt >= x.bt - 1 && x.th < 26), 'desktop week: three at once = the time above a one-line title ' + JSON.stringify(blk));
    check(await ev(`(() => { const n = document.querySelector('#view .nowline'); return !n || getComputedStyle(n).zIndex === '0'; })()`), 'desktop: the now line runs behind the blocks');
    check(await ev(`!document.querySelector('#view .wmore') || getComputedStyle(document.querySelector('#view .wmore')).display === 'none'`), 'desktop: no "+N" in the week');
    await shot('p2828-c-week-desktop.png');

    // the day starts at its first entry (06:30, before 07:00) also after the week was scrolled to noon
    await ev(`(() => { S.calSel = '${t1}'; renderView(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#view .wcev')].some(x => x.textContent.includes('Briefing'))`), 'desktop week of tomorrow');
    // (scrolled as far towards noon as the grid goes: the bottom may stop it before 12:00)
    const sc = await ev(`(() => { const wb = document.querySelector('#wbody'); wb.scrollTop = 12 * weekH(); const v = wb.scrollTop; renderView(); return JSON.stringify([v, wb.scrollTop, 7 * weekH()]); })()`);
    const [v0, v1, at7] = JSON.parse(sc);
    check(v0 > at7 && Math.abs(v1 - v0) < 3, 'desktop week: a scrolled position stays on a new drawing ' + sc);
    await ev(`(() => { S.calSel = '${t1}'; document.querySelector('#view [data-act="cal-mode"][data-k="day"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view .week.oneday')`), 'desktop: the day view');
    const vis = `(t => { const wb = document.querySelector('#wbody').getBoundingClientRect(), x = [...document.querySelectorAll('#view .wcev')].find(e => e.textContent.includes(t)); if (!x) return false; const r = x.getBoundingClientRect(); return r.top >= wb.top - 1 && r.bottom <= wb.bottom + 1; })`;
    check(await ready(ev, `${vis}('Frühdreh') && ${vis}('Briefing')`, 20), 'desktop day: 06:30 and 08:00 in view without scrolling');
    await shot('p2828-c-day-desktop.png');

    // the month: "+2 weitere" is a button and opens the day
    await ev(`(() => { S.calSel = '${t0}'; S.calMonth = '${t0.slice(0, 7)}'; S.calMode = 'month'; renderView(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view .cal .cell[data-day="${t0}"] button.more')`), 'desktop month: "+N" is a button');
    check(await ev(`document.querySelector('#view .cal .cell[data-day="${t0}"] button.more').innerText.trim() === '2 weitere'`), 'desktop month: "2 weitere" in words');
    await ev(`(() => { document.querySelector('#view .cal .cell[data-day="${t0}"] button.more').click(); return 1; })()`);
    check(await ready(ev, `S.calMode === 'day' && S.calSel === '${t0}' && !!document.querySelector('#view .week.oneday')`), 'desktop month: "2 weitere" opens the day');

    // the year: all twelve months in view
    await ev(`(() => { S.calMode = 'year'; renderView(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#cyear .cymon').length === 12`), 'desktop: the year drawn');
    const dec = await ev(`(() => { const r = document.querySelectorAll('#cyear .cymon')[11].getBoundingClientRect(); return r.bottom <= innerHeight && r.right <= innerWidth ? 'ok' : JSON.stringify([r.bottom, innerHeight]); })()`);
    check(dec === 'ok', 'desktop year: December in view ' + dec);
    await shot('p2828-c-year-desktop.png');

    // the window: heads in full, "Fertig" closes
    await ev(`(() => { S.calMode = 'week'; renderView(); return 1; })()`);
    check(await winOpen(ev), 'desktop: the Calendars window opens');
    const heads = JSON.parse(await ev(HEADS));
    check(heads.map(h => h.t).join('|') === 'Kalender|Heute|Planen' && heads.every(h => !h.cut), 'desktop window: the heads read in full ' + JSON.stringify(heads));
    const cols = await ev(`(() => { const h = [...document.querySelectorAll('.evcmodal .cvxhead .cvxc')].slice(0, 3).map(e => e.getBoundingClientRect()), s = [...document.querySelectorAll('.evcmodal .evcrow')][0].querySelectorAll('.swc'); return [...s].every((x, i) => { const r = x.getBoundingClientRect(); return Math.abs((r.left + r.right) / 2 - (h[i].left + h[i].right) / 2) <= 3; }) ? 'ok' : 'off'; })()`);
    check(cols === 'ok', 'desktop window: each switch under its head');
    check(await ev(`(() => { const f = document.querySelector('.evcmodal .evcfoot'); return f.querySelectorAll('.btn').length === 1 && f.querySelector('.btn.pri').innerText.trim() === 'Fertig' && f.querySelectorAll('.linkbtn').length >= 2; })()`), 'desktop window: "Fertig" the one button, the side paths links');
    check(await ev(`!!document.querySelector('.evcmodal .evclist ~ .evcrowbtn[data-evc="new"]') && !!document.querySelector('.evcmodal .evcrowbtn[data-evc="trash"]')`), 'desktop window: "Neuer Kalender" and the trash as rows after my calendars');
    await shot('p2828-c-window-desktop.png');
    await ev(`(() => { document.querySelector('.evcmodal [data-evc="done"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal.evcmodal')`, 20), 'desktop window: "Fertig" closes it');
  });

  console.log(`p2828_c_cal_ff_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
