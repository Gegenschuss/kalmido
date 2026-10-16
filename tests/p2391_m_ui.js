// 2.39.1 UI tests, part M, own container (start.sh), Firefox:
// Phone (390 x 844, touch):
// - #1202 the comment composer: a tap on the paperclip right after the field had the focus keeps the bar and reaches the file input
// - #1181 bottom sheets: a grip; drag up = taller, drag down = closed (menu, date picker, dialog); the X is out of sight on touch
// - #1189 html / body do not scroll (overflow hidden), the sidebar keeps its overscroll to itself
// - #1180 statistics: round axis steps (time in whole hours), the app font on the axes, even gaps between the date labels,
//   the long note behind the (i) next to the first heading (closed, a tap shows it)
// - #1224 agent chat: a suggestion has a pen (44 px): it puts the text into the box (appended), nothing is sent; long press too
// Desktop (mouse):
// - #1294 double click / middle click on a list in the sidebar and "Open in its own window" in the list menu call window.open
//   with the mini address; the mini view: no sidebar, the list's name on top, the composer; it keeps the UI state to itself
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2391_m_ui', check, shots: 'P2391M_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'comments,collab,agents,stats,time';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper'});
  const AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Errands'})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Buy paint', list_id: L})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Return the drill', list_id: L});
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});  // the agent may write to whom it shares a list with
  const q = await (await fetch(B + 'api/v1/agent/chats/1', {method: 'POST', headers: AGH, body: JSON.stringify({body: 'What next?', choices: [{id: 'a', label: 'Plan the week'}, {id: 'b', label: 'Tidy the basket'}]})})).json();
  check(q.choices && q.choices.choices.length === 2, 'a chat question with two suggestions ' + JSON.stringify(q).slice(0, 300));

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const until = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const act = (cmd, ctx, kind, steps) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'p' + kind, parameters: {pointerType: kind}, actions: steps}]}).then(() => cmd('input.releaseActions', {context: ctx}));
  const tap = (cmd, ctx, x, y, hold = 0) => act(cmd, ctx, 'touch', [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, ...(hold ? [{type: 'pause', duration: hold}] : []), {type: 'pointerUp', button: 0}]);
  const rect = (ev, sel) => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, top: r.top, h: r.height, w: r.width}; })()`);

  // ================= the phone
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot, drag} = o;
    check(await ffLogin(o) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#l/' + L); await until(ev, `!!document.querySelector('#view .trow')`);
    await sleep(600);

    // ---- #1189
    const doc = await ev(`(() => { const h = getComputedStyle(document.documentElement), b = getComputedStyle(document.body), s = getComputedStyle(document.getElementById('side'));
      return {h: h.overflowY, b: b.overflowY, so: s.overscrollBehaviorY, bh: document.body.getBoundingClientRect().height, ih: innerHeight}; })()`);
    check(doc.h === 'hidden' && doc.b === 'hidden' && doc.so === 'contain' && Math.abs(doc.bh - doc.ih) < 2, '#1189: html / body fixed, the sidebar contains its overscroll ' + JSON.stringify(doc));
    await drag(195, 600, 0, -400, 'touch'); await sleep(300);
    check(await ev(`window.scrollY === 0 && document.documentElement.scrollTop === 0`), '#1189: a swipe does not move the page');

    // ---- #1202
    await ev(`(() => { openDetail(${T}); return 1; })()`);
    await until(ev, `!!document.querySelector('#c-input')`);
    await sleep(500);
    await ev(`(() => { window._fc = 0; document.addEventListener('click', e => { if (e.target.type === 'file') { window._fc++; e.preventDefault(); } }, true); document.getElementById('c-input')?.scrollIntoView({block: 'center'}); return 1; })()`);
    await sleep(300);
    const ci = await rect(ev, '#c-input');
    if (ci) await tap(cmd, ctx, ci.x, ci.y);  // a real tap into the field (the keyboard would come up)
    await sleep(500);
    if (!(await ev(`document.activeElement?.id === 'c-input'`))) await ev(`(() => { document.getElementById('c-input')?.focus(); return 1; })()`);
    await sleep(300);
    const clipSel = '.dcomp .ccomp .cbar label.iconbtn';
    const clip = await rect(ev, clipSel);
    check(clip && clip.w > 0, '#1202: the bar with the paperclip shows while the field has the focus ' + JSON.stringify(await ev(`({ci: !!document.getElementById('c-input'), act: document.activeElement?.id || document.activeElement?.tagName, cls: document.querySelector('.dcomp .ccomp')?.className, bar: document.querySelector('.dcomp .ccomp .cbar') ? getComputedStyle(document.querySelector('.dcomp .ccomp .cbar')).display : 'none-el'})`)));
    if (clip) {
      await tap(cmd, ctx, clip.x, clip.y); await sleep(400);
      const st = await ev(`(() => ({bar: getComputedStyle(document.querySelector('.dcomp .ccomp .cbar')).display, open: document.querySelector('.dcomp .ccomp').classList.contains('open'), fc: window._fc}))()`);
      check(st.bar !== 'none' && st.open && st.fc >= 1, '#1202: the tap on the paperclip reaches the file input, the bar stays ' + JSON.stringify(st));
      await tap(cmd, ctx, 195, 120); await sleep(300);
      check(await ev(`!document.querySelector('.dcomp .ccomp.open')`), '#1202: a tap outside closes the composer again');
    }
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(500);

    // ---- #1181 a menu sheet
    await ev(`(() => { listMenu(document.querySelector('#top h1'), ${L}); return 1; })()`); await sleep(500);
    let p = await rect(ev, '#pop.sheet');
    const sh = await ev(`(() => { const p = document.getElementById('pop'), x = p.querySelector('.tch-shx'); return {grip: getComputedStyle(p).backgroundImage, x: x ? x.getBoundingClientRect().width : -1}; })()`);
    check(p && /gradient/.test(sh.grip) && sh.x >= 44, '#1181: the sheet has its grip; 2.58.0 (#1757): the X stays visible, 44 px wide ' + JSON.stringify(sh));
    await shot('p2391m-390-sheet.png');
    if (p) {
      await drag(195, p.top + 12, 0, -Math.min(220, 2 * (p.top + 4)), 'touch'); await sleep(400);  // 2.58.0 (#1757): the visible X makes the sheet taller, stay inside the viewport
      const p2 = await rect(ev, '#pop.sheet');
      check(p2 && p2.h > p.h + 40, `#1181: dragged up, the sheet is taller (${p.h} -> ${p2 && p2.h})`);
      await shot('p2391m-390-sheet-tall.png');
      const p3 = p2 || p;
      await drag(195, p3.top + 12, 0, Math.min(700, 830 - p3.top - 12), 'touch'); await sleep(700);
      check(await ev(`document.getElementById('pop').classList.contains('hidden')`), '#1181: swiped down, the menu is closed');
      await ev(`(() => { listMenu(document.querySelector('#top h1'), ${L}); return 1; })()`); await sleep(400);
      const p4 = await rect(ev, '#pop.sheet');
      check(p4 && Math.abs(p4.h - p.h) < 4 && await ev(`!document.getElementById('pop').style.transform`), '#1181: opened again, the sheet has its own height back');
      await ev(`(() => { closePop(); return 1; })()`); await sleep(300);
    }
    // the date picker
    await ev(`(() => { dpOpen(document.querySelector('#top h1'), {kind: 'date', value: '', onPick() {}}); return 1; })()`); await sleep(400);
    const dp = await rect(ev, '.dpop.sheet');
    check(!!dp, '#1181: the date picker is a sheet on the phone');
    if (dp) { await drag(195, dp.top + 8, 0, Math.min(500, 830 - dp.top - 8), 'touch'); await sleep(700); check(await ev(`!document.getElementById('dpop')`), '#1181: the date picker closes with a swipe down'); }
    // a dialog in sheet form; a pull down in its scrolled-to-top content closes it too
    await ev(`(() => { listModal(${L}); return 1; })()`); await sleep(700);
    const md = await rect(ev, '.modal:not(.smodal) > .card');
    check(!!md, '#1181: the list dialog opens as a sheet');
    if (md) { await drag(195, md.top + 70, 0, Math.min(500, 830 - md.top - 70), 'touch'); await sleep(800); check(await ev(`!document.querySelector('.modal:not(.smodal)')`), '#1181: the dialog closes with a swipe down from its content (scrolled to the top)'); }

    // ---- #1180 statistics
    const ax = await ev(`(() => {
      const t = mx_ticks(2000, true), c = mx_ticks(7);
      const svg = barChart([0, 400, 2000, 1500, 0, 30, 90, 600, 1200, 800, 300, 100], ['13 Jul','20 Jul','27 Jul','3 Aug','10 Aug','17 Aug','24 Aug','31 Aug','7 Sep','14 Sep','21 Sep','28 Sep'], {tip: () => '', label: 'x', w: 320, time: true, fmt: v => fmtH(Math.round(v))});
      const labs = [...svg.matchAll(/<text class="ch-ax" x="([\\d.]+)" y="[\\d.]+" text-anchor="(\\w+)">([^<]+)<\\/text>/g)].map(m => ({x: +m[1], s: m[3]}));
      const ys = labs.filter(l => /^\\d+ (h|min)$/.test(l.s)).map(l => l.s), xs = labs.filter(l => !/^\\d+ (h|min)$/.test(l.s)).map(l => l.x).sort((a, b) => a - b);
      const gaps = xs.slice(1).map((x, i) => Math.round(x - xs[i]));
      return {t: t.ticks, c: c.ticks, ys, gaps, n: xs.length};
    })()`);
    check(JSON.stringify(ax.t) === JSON.stringify([0, 600, 1200, 1800, 2400]) && JSON.stringify(ax.c) === JSON.stringify([0, 2, 4, 6, 8]), '#1180: round steps (time in 10 h, counts in 2) ' + JSON.stringify([ax.t, ax.c]));
    check(ax.ys.join('|') === '0 h|10 h|20 h|30 h|40 h' || ax.ys.slice().sort().join('|') === ['0 h', '10 h', '20 h', '30 h', '40 h'].sort().join('|'), '#1180: the time axis in whole hours ' + ax.ys.join('|'));
    check(ax.n >= 2 && ax.gaps.length && ax.gaps.slice(0, -1).every(g => Math.abs(g - ax.gaps[0]) <= 1), '#1180: even gaps between the date labels ' + JSON.stringify(ax.gaps));
    await nav(B + '#stats'); await until(ev, `!!document.querySelector('#view .stats svg.chart')`); await sleep(600);
    const stv = await ev(`(() => { const n = document.querySelector('.stats .stnote'), b = document.querySelector('.stats .sthead h3 .ib'), t = document.querySelector('.stats .ch-ax');
      const ff = t ? getComputedStyle(t).fontFamily : '', fv = t ? getComputedStyle(t).fontVariantNumeric : '';
      const cut = [...document.querySelectorAll('.stats svg.chart text.ch-ax')].some(x => x.getBoundingClientRect().left < x.closest('svg').getBoundingClientRect().left - 1);
      return {note: n ? getComputedStyle(n).display : 'missing', ib: !!b, ff, fv, cut}; })()`);
    check(stv.note === 'none' && stv.ib, '#1180: the note is closed behind the (i) at the first heading ' + JSON.stringify(stv));
    check(!/mono/i.test(stv.ff) && /tabular/.test(stv.fv), '#1180: the axes in the app font with tabular figures ' + stv.ff);
    check(!stv.cut, '#1180: no axis label sticks out to the left');
    const ib = await rect(ev, '.stats .sthead h3 .ib');
    if (ib) { await tap(cmd, ctx, ib.x, ib.y); await sleep(400); check(await ev(`(() => { const t = document.getElementById('iitip'); return !!t && !t.classList.contains('hidden') && /Last 12 weeks/.test(t.textContent); })()`), '#1180: a tap on the (i) shows the note'); }
    await shot('p2391m-390-stats.png');

    // ---- #1224
    await nav(B + '#agents/' + ag.id); await until(ev, `!!document.querySelector('#chat-msgs .cchoices .cchpen')`);
    await sleep(500);
    const pen = await rect(ev, '#chat-msgs .cchoices .cchpen');
    const pz = await ev(`(() => { const b = document.querySelector('#chat-msgs .cchpen'); const r = b.getBoundingClientRect(); return {w: r.width, h: r.height, l: b.getAttribute('aria-label'), n: document.querySelectorAll('#chat-msgs .cchpen').length}; })()`);
    check(pz.w >= 44 && pz.h >= 44 && /Plan the week/.test(pz.l) && pz.n === 2, '#1224: a pen per suggestion, 44 px, with a name ' + JSON.stringify(pz));
    await ev(`(() => { const t = document.getElementById('chat-in'); t.value = 'Hi'; t.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    if (pen) { await tap(cmd, ctx, pen.x, pen.y); await sleep(500); }
    const v1 = await ev(`(() => { const t = document.getElementById('chat-in'); return {v: t.value, end: t.selectionStart === t.value.length, open: !document.querySelector('#chat-msgs .cchoices.done')}; })()`);
    check(v1.v === 'Hi Plan the week' && v1.end && v1.open, '#1224: the pen appends the suggestion to the box, caret at the end, nothing sent ' + JSON.stringify(v1));
    const b2 = await rect(ev, '#chat-msgs .cchw:nth-child(2) .cchb');
    if (b2) { await tap(cmd, ctx, b2.x, b2.y, 800); await sleep(600); }
    const v2 = await ev(`({v: document.getElementById('chat-in').value, open: !document.querySelector('#chat-msgs .cchoices.done')})`);
    check(v2.v === 'Hi Plan the week Tidy the basket' && v2.open, '#1224: a long press does the same ' + JSON.stringify(v2));
    const evs = await (await fetch(B + 'api/v1/agent/events?since=0', {headers: AGH})).json();
    check(!(evs.data || []).some(e => e.event === 'chat_choice'), '#1224: the agent got no chat_choice');
    await shot('p2391m-390-chat-pen.png');
  }, true);

  // ================= the desktop: #1294
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    check(await ffLogin(o) === 200, 'desk: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + '#today'); await until(ev, `!!document.querySelector('#side .srow[data-list="${L}"]')`); await sleep(600);
    await ev(`(() => { window._wo = []; window.open = (u, n, f) => { window._wo.push([u, n, f]); return {focus() {}}; }; return 1; })()`);
    const row = await rect(ev, `#side .srow[data-list="${L}"]`);
    const m = [{type: 'pointerMove', x: Math.round(row.x), y: Math.round(row.y)}];
    await act(cmd, ctx, 'mouse', [...m, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}, {type: 'pause', duration: 80}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]);
    await sleep(500);
    let wo = await ev(`window._wo`);
    check(wo.length === 1 && wo[0][0] === `/?mini=1#l/${L}` && wo[0][1] === `kalmido-mini-${L}` && /width=420/.test(wo[0][2]), '#1294: a double click opens the list window ' + JSON.stringify(wo));
    check(await ev(`location.hash`) === `#l/${L}`, '#1294: the single click opened the list in the main view as before');
    await act(cmd, ctx, 'mouse', [...m, {type: 'pointerDown', button: 1}, {type: 'pointerUp', button: 1}]); await sleep(400);
    wo = await ev(`window._wo`);
    check(wo.length === 2, '#1294: a middle click opens it too');
    await ev(`(() => { listMenu(document.querySelector('#side .srow[data-list="${L}"]'), ${L}); return 1; })()`); await sleep(400);
    check(await ev(`(() => { const b = document.querySelector('#pop .mminiwin'); if (!b) return false; b.click(); return window._wo.length === 3; })()`), '#1294: the list menu has "Open in its own window"');
    // the mini window itself
    await ev(`(() => { localStorage.setItem('tasks.lastKey', '"today"'); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 420, height: 700}});
    await nav(B + `?mini=1#l/${L}`); await until(ev, `!!document.querySelector('#view .trow')`); await sleep(800);
    const mv = await ev(`(() => ({mini: document.documentElement.classList.contains('mini'), side: getComputedStyle(document.getElementById('side')).display, tabs: getComputedStyle(document.getElementById('tabs')).display,
      h1: document.querySelector('#top h1')?.textContent.trim(), dock: !!document.querySelector('#view .qdock') && getComputedStyle(document.querySelector('#view .qdock')).display !== 'none', title: document.title,
      menu: !!document.querySelector('#pop .mminiwin')}))()`);
    check(mv.mini && mv.side === 'none' && mv.tabs === 'none' && /Errands/.test(mv.h1) && mv.dock && /Errands/.test(mv.title), '#1294: the mini view: the list only, its name, the composer ' + JSON.stringify(mv));
    check(await ev(`localStorage.getItem('tasks.lastKey')`) === '"today"', '#1294: the mini window does not write the last view of the main window');
    await ev(`(() => { location.hash = '#today'; return 1; })()`); await sleep(700);
    check(await ev(`location.hash`) === `#l/${L}`, '#1294: another view\'s address goes back to the list');
    await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(700);
    check(await ev(`!!document.querySelector('#detail:not(.hidden)')`), '#1294: a task opens in the same window');
    await shot('p2391m-mini.png');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
