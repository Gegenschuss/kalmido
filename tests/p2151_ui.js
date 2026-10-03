// 2.15.1 UI tests (#636 Today / Tomorrow back in the task header on phones, #633 phone details), own container (start.sh).
// jsdom: the task header has Today / Tomorrow with their words (hidden by CSS where they do not fit) and the row break; one
// tap sets the date; the matrix folds a quadrant by its heading on a phone (remembered, not on
// a desktop); opening Search focuses its field on a phone, a re-render does not; the palette focuses at once on touch; the
// new token dialog has its expiry, error and buttons in the sticky footer, the permissions and agent dialogs a sticky footer;
// German. Firefox with real touch taps (pointerType touch, overlay scroll bars like a phone): the task header at 360 / 390 /
// 412 / 428 (two rows, the whole date, 44 px targets, nothing sideways, a tap on Tomorrow), the Fold folded / unfolded / 880
// portrait (one row with Pin where it fits), a desktop at 1440 (one row, unchanged); the matrix folded by a tap; Search and
// the palette with the keyboard (visualViewport); the new token dialog at 390 x 844 and 360 x 640 (Expires + Create without
// scrolling); the week view (the "all day" row, two-line all-day tasks, 07:00 not cut). Screenshots with P2151_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2151_ui', check, shots: 'P2151_SHOTS', prefs: [['widget.gtk.overlay-scrollbars.enabled', true], ['ui.useOverlayScrollbars', 1]]});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const task = async id => (await call('GET', '/api/state')).tasks.find(t => t.id === id);

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:9[0-9])'/.test(SW), 'service worker cache v90');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'dora', display_name: 'Dora', password: 'password123', lang: 'de'});
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done'}, await login('dora'));
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const mk = async b => (await call('POST', '/api/tasks', {list_id: L, ...b})).id;
  const T = await mk({title: 'Book the flights', due: day(9), due_time: '14:30', priority: 3});
  await mk({title: 'Call the plumber about the kitchen sink', due: day(0), priority: 5});
  await mk({title: 'Write the quarterly report for the board', due: day(0), priority: 1});
  await mk({title: 'Dentist', due: day(0), due_time: '10:00', duration: 60, priority: 0});
  for (let i = 0; i < 6; i++) await mk({title: 'Matrix item ' + i, priority: [5, 3, 1, 0][i % 4]});

  // ================= jsdom: the task header on a phone
  let w = await boot({user: 'alice', mobile: true, hash: 'l/' + L}), d = w.document;
  w.eval(`openDetail(${T})`); await sleep(400);
  let dq = [...d.querySelectorAll('#detail .dtop [data-act="due-q"]')];
  check(dq.length === 2 && dq.map(b => b.querySelector('.dql')?.textContent).join() === 'Today,Tomorrow', '#636: Today / Tomorrow in the header with their words ' + dq.map(b => b.textContent.trim()));
  check(dq[1].getAttribute('aria-label') === 'Due: Tomorrow' && d.querySelector('#detail .dtop .dbr[aria-hidden="true"]'), '#636: aria-label kept, the row break is hidden from screen readers');
  check(d.querySelector('#detail .dtop [data-act="pin"]') && d.querySelector('#detail .dtop .dchip .dct'), 'the header still has Pin (CSS decides) and the date');
  click(w, dq[1]);
  check(await until(async () => (await task(T)).due === day(1)), '#636: a tap on Tomorrow sets tomorrow');
  check((await task(T)).due_time === '14:30', 'the time stays');
  check(await until(() => d.querySelector('#detail [data-act="due-q"][data-d="1"]')?.classList.contains('on')), 'Tomorrow marked as the current date');
  await call('PATCH', `/api/tasks/${T}`, {due: day(9)});
  w.eval('closeDetail()'); w.close();

  // ================= jsdom: the matrix folds on a phone
  w = await boot({user: 'alice', mobile: true, hash: 'matrix'}); d = w.document;
  let qf = [...d.querySelectorAll('.quad .qfold')];
  check(qf.length === 4 && qf.every(b => b.getAttribute('aria-expanded') === 'true' && b.closest('h3')), '#633: four quadrant headings are fold buttons, all open');
  check(/Urgent & important/.test(qf[0].textContent) && qf[0].querySelector('.c')?.textContent === '3', 'the heading keeps the name and the count');
  qf[0].focus(); click(w, qf[0]); await sleep(200);
  const q5 = d.querySelector('.quad[data-quad="5"]');
  check(q5.classList.contains('fold') && q5.querySelector('.qfold').getAttribute('aria-expanded') === 'false', '#633: a tap folds the quadrant');
  check(w.__store['tasks.mxFold'] === '[5]', 'remembered on the device ' + w.__store['tasks.mxFold']);
  check(d.activeElement?.matches?.('.quad[data-quad="5"] .qfold'), 'the focus stays on the heading after the re-render');
  const store = {...w.__store}; w.close();
  w = await boot({user: 'alice', mobile: true, hash: 'matrix', ls: store}); d = w.document;
  check(d.querySelector('.quad[data-quad="5"]').classList.contains('fold') && !d.querySelector('.quad[data-quad="3"]').classList.contains('fold'), 'still folded after a reload, the others open');
  click(w, d.querySelector('.quad[data-quad="5"] .qfold')); await sleep(200);
  check(!d.querySelector('.quad[data-quad="5"]').classList.contains('fold') && w.__store['tasks.mxFold'] === '[]', 'a second tap opens it again');
  w.close();
  w = await boot({user: 'alice', mobile: false, hash: 'matrix', ls: {'tasks.mxFold': '[5]'}}); d = w.document;
  check(!d.querySelector('.quad .qfold') && !d.querySelector('.quad.fold') && d.querySelector('.quad[data-quad="5"] h3'), 'desktop: plain headings, nothing folded (two columns)');
  w.close();

  // ================= jsdom: Search focus on a phone, the palette on touch
  w = await boot({user: 'alice', mobile: true, hash: 'search'}); d = w.document;
  check(d.activeElement?.id === 'searchq', '#633: opening Search on a phone focuses its field');
  d.activeElement.blur(); w.eval('render()'); await sleep(100);
  check(d.activeElement?.id !== 'searchq', 'a re-render does not focus it again (no keyboard popping up)');
  w.eval(`go('today')`); await sleep(400); w.eval(`go('search')`); await sleep(400);
  check(d.activeElement?.id === 'searchq', 'coming to Search again focuses it again');
  w.eval(`go('today')`); await sleep(300);
  w.eval('openPalette()');
  check(d.activeElement?.classList.contains('pqin'), '#633: the palette focuses at once on touch (inside the tap)');
  w.eval('closePalette()'); w.close();

  // ================= jsdom: the token dialogs
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`tokModal(null, [])`); await sleep(300);
  let md = [...d.querySelectorAll('.modal')].pop();
  const foot = md.querySelector('.foot.stfoot');
  check(foot && foot.querySelector('#tk-exp') && foot.querySelector('[data-m="ok"]') && foot.querySelector('#tk-err') && foot.querySelector('label[for="tk-exp"]')?.textContent === 'Expires', '#633: new token: Expires, the error and Create in the sticky footer');
  check(foot.querySelector('#tk-exp').value === '90' && md.querySelectorAll('#tk-exp').length === 1, 'the expiry keeps its default (90 days), only once');
  md.querySelector('#tk-name').value = 'Phone script';
  md.querySelector('#tk-exp').value = '30';
  click(w, md.querySelector('[data-m="ok"]'));
  const tok = await until(async () => (await call('GET', '/api/me/tokens')).tokens.find(t => t.name === 'Phone script'));
  check(tok && tok.expires_at && new Date(tok.expires_at) - Date.now() < 31 * 864e5, 'created with the expiry from the footer');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.eval(`permModal('P', [], ['read'], [], async () => {})`); await sleep(200);
  md = [...d.querySelectorAll('.modal')].pop();
  check(md.querySelector('.foot.stfoot [data-m="ok"]') && md.querySelector('.foot.stfoot #pm-err[hidden]'), 'the permissions dialog: sticky footer with its error line');
  md.remove();
  w.eval(`agModal(null, () => {})`); await sleep(300);
  md = [...d.querySelectorAll('.modal')].pop();
  check(md.querySelector('.foot.stfoot [data-m="ok"]') && md.querySelector('.foot.stfoot #ag-err'), 'the agent dialog: sticky footer with its error line (a taken user name is seen)');
  md.remove(); w.close();

  // ================= jsdom: German
  w = await boot({user: 'dora', mobile: true, hash: 'today'}); d = w.document;
  const DT = (await call('POST', '/api/tasks', {title: 'Steuer', due: day(3)}, await login('dora'))).id;
  await w.eval('load().then(render)'); await sleep(300);
  w.eval(`openDetail(${DT})`); await sleep(400);
  dq = [...d.querySelectorAll('#detail .dtop [data-act="due-q"]')];
  check(dq.map(b => b.querySelector('.dql')?.textContent).join() === 'Heute,Morgen' && dq[0].getAttribute('aria-label') === 'Fällig: Heute', 'German: Heute / Morgen');
  w.eval('closeDetail()');
  w.eval(`tokModal(null, [])`); await sleep(300);
  check([...d.querySelectorAll('.modal')].pop().querySelector('.stfoot label[for="tk-exp"]')?.textContent === 'Läuft ab', 'German: Läuft ab in the footer');
  w.close();

  // ================= Firefox: real touch on phones and the Fold, mouse on a desktop
  const VVSIM = `(() => { const vv = window.visualViewport; window.__kb = {h: null, t: 0};
    Object.defineProperty(vv, 'height', {configurable: true, get: () => window.__kb.h ?? innerHeight});
    Object.defineProperty(vv, 'offsetTop', {configurable: true, get: () => window.__kb.t});
    window.__setKb = (hh, t) => { window.__kb.h = hh; window.__kb.t = t; vv.dispatchEvent(new Event('resize')); vv.dispatchEvent(new Event('scroll')); return 1; };
    return 1; })()`;
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice', ls = {}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); ${Object.entries(ls).map(([k, v]) => `localStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(v)});`).join(' ')} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const tapper = ({cmd, ctx}) => async (x, y) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  const center = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); if (r.top < 0 || r.bottom > innerHeight) { e.scrollIntoView({block: 'center'}); } const q = e.getBoundingClientRect(); return {x: q.left + q.width / 2, y: q.top + q.height / 2}; })()`;
  // the task header: rows, sizes, the date in full, nothing outside
  const HEAD = `(() => { const d = document.querySelector('#detail .dtop'); if (!d) return null; const R = d.getBoundingClientRect(), vis = e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
    const r = s => { const e = d.querySelector(s); if (!vis(e)) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top), b: Math.round(b.bottom), w: Math.round(b.width), h: Math.round(b.height)}; };
    const dct = d.querySelector('.dchip .dct'), dql = d.querySelector('[data-act="due-q"] .dql');
    return {h: Math.round(R.height), over: document.documentElement.scrollWidth - innerWidth, sw: d.scrollWidth - d.clientWidth,
      out: [...d.children].filter(vis).filter(e => { const b = e.getBoundingClientRect(); return b.right > R.right + .5 || b.left < R.left - .5; }).length,
      chk: r('.chk'), chip: r('.dchip'), today: r('[data-act="due-q"][data-d="0"]'), tom: r('[data-act="due-q"][data-d="1"]'), pin: r('[data-act="pin"]'), more: r('[data-act="task-menu"]'),
      clipped: dct.scrollWidth > dct.clientWidth + 1, words: vis(dql), date: dct.textContent}; })()`;
  const headChecks = (tag, x, {rows, words, pin}) => {
    check(x && x.over <= 0 && x.sw <= 0 && x.out === 0, `${tag}: the header fits, nothing sideways ` + JSON.stringify(x));
    check(x.today && x.tom && x.today.h >= 44 && x.tom.h >= 44 && x.today.w >= 44 && x.tom.w >= 44, `${tag}: Today / Tomorrow shown, 44 px targets`);
    check(!x.clipped, `${tag}: the whole date (${x.date}), not cut short`);
    if (rows === 2) check(x.chip.t >= x.chk.b && x.today.t >= x.chk.b && Math.abs(x.today.t - x.chip.t) <= 2 && x.h < 125, `${tag}: date + Today / Tomorrow in a second row`);
    else check(x.h < 70 && Math.abs(x.chip.t - x.today.t) <= 2 && x.chip.l > x.chk.r, `${tag}: one row`);
    check(x.words === words, `${tag}: the words next to the icons ${words ? 'shown' : 'hidden'}`);
    check(!!x.pin === pin, `${tag}: Pin ${pin ? 'in the header' : 'in "…"'}`);
  };
  const openTask = async (o, id) => {
    const tap = tapper(o);
    await o.nav(B + '#l/' + L); await ready(o.ev);
    const p = await o.ev(center(`#view .trow[data-id="${id}"] .ttl`));
    if (p) await tap(p.x, p.y); else await o.ev(`(() => { openDetail(${id}); return 1; })()`);
    for (let i = 0; i < 20 && !(await o.ev(`!!document.querySelector('#detail .dtop')`)); i++) await sleep(200);
    await sleep(500);
  };

  // phones
  for (const [vw, vh, th] of [[360, 780, 'light'], [390, 844, 'dark'], [412, 915, 'light'], [428, 926, 'dark']]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = String(vw), tap = tapper(o);
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await openTask(o, T);
    const x = await ev(HEAD);
    headChecks(tag, x, {rows: 2, words: vw >= 390, pin: true});
    await shot(`p2151-${tag}-header.png`);
    if (vw !== 390) return;
    // a real tap on Tomorrow
    await tap((x.tom.l + x.tom.r) / 2, (x.tom.t + x.tom.b) / 2);
    check(await until(async () => (await task(T)).due === day(1)), '390: a tap on Tomorrow sets tomorrow');
    check(await until(() => ev(`!!document.querySelector('#detail [data-act="due-q"][data-d="1"].on')`)), '390: Tomorrow marked');
    await call('PATCH', `/api/tasks/${T}`, {due: day(9)});
    // the matrix: a tap folds a quadrant
    await o.nav(B + '#matrix'); await ready(ev);
    const qh = await ev(`(() => { const b = document.querySelector('.quad[data-quad="3"] .qfold').getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, h: b.height}; })()`);
    check(qh.h >= 44, '390 matrix: the heading is a 44 px target ' + qh.h);
    const before = await ev(`Math.round(document.querySelector('.quad[data-quad="3"]').getBoundingClientRect().height)`);
    await tap(qh.x, qh.y); await sleep(400);
    const after = await ev(`(() => { const q = document.querySelector('.quad[data-quad="3"]'); return {h: Math.round(q.getBoundingClientRect().height), fold: q.classList.contains('fold'), list: getComputedStyle(q.querySelector('.qlist')).display, over: document.documentElement.scrollWidth - innerWidth}; })()`);
    check(after.fold && after.list === 'none' && after.h < 70 && before > 150 && after.over <= 0, `390 matrix: a tap folds "Not urgent, but important" (${before} -> ${after.h} px)`);
    const lastQ = await ev(center('.quad[data-quad="0"] .qfold')); await tap(lastQ.x, lastQ.y); await sleep(400);
    const lq = await ev(`(() => { const r = document.querySelector('.quad[data-quad="0"] .qfold').getBoundingClientRect(); return {top: Math.round(r.top), bottom: Math.round(r.bottom), ih: innerHeight}; })()`);
    check(lq.top >= 0 && lq.bottom <= lq.ih, '390 matrix: the folded last heading stays in view ' + JSON.stringify(lq));
    await shot('p2151-390-matrix-folded.png');
    await ev(`(() => { localStorage.removeItem('tasks.mxFold'); return 1; })()`);
    // Search: opened, focused; the palette above the keyboard
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { location.hash = 'search'; return 1; })()`); await sleep(800);
    check(await ev(`document.activeElement?.id`) === 'searchq', '390: opening Search focuses the field');
    await ev(`(() => { location.hash = 'today'; return 1; })()`); await sleep(800);
    await ev(VVSIM);
    const sb = await ev(center('#top [data-act="side"]')); await tap(sb.x, sb.y); await sleep(600);
    const sc = await ev(center('#side .scmd')); await tap(sc.x, sc.y); await sleep(700);
    const pa = await ev(`(() => { const c = document.querySelector('.palette .card').getBoundingClientRect(); return {act: document.activeElement?.className, top: Math.round(c.top), foot: getComputedStyle(document.querySelector('.palette .pfoot')).display, kbs: [...document.querySelectorAll('.palette .kbs')].filter(k => getComputedStyle(k).display !== 'none').length, minH: Math.round(Math.min(...[...document.querySelectorAll('.palette .pitem')].map(e => e.getBoundingClientRect().height)))}; })()`);
    check(/pqin/.test(pa.act) && pa.top <= 24 && pa.foot === 'none' && pa.kbs === 0, '390: the drawer search: focused, at the top, no keyboard hints ' + JSON.stringify(pa));
    check(pa.minH >= 44, '390: palette rows are 44 px touch targets ' + pa.minH);
    await ev(`__setKb(${Math.round(vh * .55)}, 0)`); await sleep(500);
    const pk = await ev(`(() => { const c = document.querySelector('.palette .card').getBoundingClientRect(); return {bottom: Math.round(c.bottom), vis: Math.round(visualViewport.height)}; })()`);
    check(pk.bottom <= pk.vis, '390: with the keyboard up the palette ends above it ' + JSON.stringify(pk));
    await shot('p2151-390-palette-keyboard.png');
    await ev(`(() => { closePalette(); __setKb(null, 0); return 1; })()`); await sleep(300);
    // the week view
    await ev(`(() => { S.calMode = 'week'; LS.set('calMode', 'week'); location.hash = 'cal'; return 1; })()`); await sleep(1200);
    const wk = await ev(`(() => { const lb = document.querySelector('.wlbl').getBoundingClientRect(), row = document.querySelector('.wallday').getBoundingClientRect(), wb = document.querySelector('#wbody').getBoundingClientRect();
      const t7 = [...document.querySelectorAll('.wtime')].find(e => e.textContent === '07:00').getBoundingClientRect();
      const ev = [...document.querySelectorAll('.wad .ev')].find(e => /plumber/.test(e.textContent)), lh = parseFloat(getComputedStyle(ev).lineHeight);
      return {row: Math.round(row.height), lbl: Math.round(lb.height), t7top: Math.round(t7.top), wbTop: Math.round(wb.top), evLines: Math.round(ev.getBoundingClientRect().height / lh), over: document.documentElement.scrollWidth - innerWidth, page: document.documentElement.scrollHeight - innerHeight}; })()`);
    check(wk.evLines === 2, '390 week: an all-day task shows two lines of its title');
    check(wk.t7top >= wk.wbTop, '390 week: 07:00 shown in full at the top of the hour grid');
    check(wk.over <= 0 && wk.page <= 1, '390 week: no sideways scroll, only the grid scrolls');
    await shot('p2151-390-week.png');
    // a week without all-day tasks: the row keeps its minimum height with "all day" in two short lines
    await ev(`(() => { document.querySelector('[data-act="cal-next"]').click(); return 1; })()`); await sleep(700);
    const wk2 = await ev(`(() => ({row: Math.round(document.querySelector('.wallday').getBoundingClientRect().height), n: document.querySelectorAll('.wad .ev').length}))()`);
    check(wk2.n === 0 && wk2.row <= 33, '390 week: "all day" does not make its row taller ' + JSON.stringify(wk2));
    // the new token dialog: Expires + Create without scrolling, at 390 x 844 and 360 x 640
    for (const [ww, hh] of [[390, 844], [360, 640]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: ww, height: hh}});
      await o.nav(B + '#today'); await ready(ev);
      await ev(`(() => { settingsModal('account'); return 1; })()`); await sleep(700);
      await ev(`(() => { const x = document.querySelector('.smodal details.sdev'); if (x) x.open = true; return 1; })()`); await sleep(300);
      const nb = await ev(center('[data-tok="new"]')); await tap(nb.x, nb.y); await sleep(700);
      const tk = await ev(`(() => { const m = [...document.querySelectorAll('.modal')].pop(), c = m.querySelector('.card'), r = s => m.querySelector(s).getBoundingClientRect();
        return {ih: innerHeight, exp: Math.round(r('#tk-exp').bottom), ok: Math.round(r('[data-m="ok"]').bottom), okTop: Math.round(r('[data-m="ok"]').top), okH: Math.round(r('[data-m="ok"]').height), st: c.scrollTop, long: c.scrollHeight > c.clientHeight, over: document.documentElement.scrollWidth - innerWidth}; })()`);
      check(tk.st === 0 && tk.exp <= tk.ih && tk.ok <= tk.ih && tk.okTop >= 0 && tk.okH >= 40 && tk.over <= 0, `${ww}x${hh}: new token: Expires and Create visible without scrolling ` + JSON.stringify(tk));
      await shot(`p2151-${ww}x${hh}-newtoken.png`);
      if (hh === 640) {  // the dialog is longer than the screen: the footer stays while the permissions scroll
        check(tk.long, '360x640: the dialog scrolls (the footer must stick)');
        await ev(`(() => { const c = [...document.querySelectorAll('.modal')].pop().querySelector('.card'); c.scrollTop = 120; return 1; })()`); await sleep(200);
        const s2 = await ev(`(() => { const m = [...document.querySelectorAll('.modal')].pop(); return {ok: Math.round(m.querySelector('[data-m="ok"]').getBoundingClientRect().bottom), ih: innerHeight}; })()`);
        check(s2.ok <= s2.ih, '360x640: scrolled, Create still in view');
      }
      await ev(`(() => { [...document.querySelectorAll('.modal')].forEach(m => m.remove()); return 1; })()`);
    }
  }, true);

  // German at 390 (longer words)
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o, 'light', 'dora') === 200, 'de 390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { openDetail(${DT}); return 1; })()`); await sleep(900);
    const x = await ev(HEAD);
    headChecks('de 390', x, {rows: 2, words: true, pin: true});
    await shot('p2151-de-390-header.png');
  }, true);

  // the Fold: unfolded (side panel), folded, unfolded again; 880 portrait (one row, Pin)
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o, 'light') === 200, 'fold: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 904}});
    await openTask(o, T);
    headChecks('fold 904', await ev(HEAD), {rows: 2, words: true, pin: true});
    await shot('p2151-904-header.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 904}}); await sleep(900);
    if (!(await ev(`!!document.querySelector('#detail .dtop')`))) await ev(`(() => { openDetail(${T}); return 1; })()`), await sleep(700);
    headChecks('fold folded 412', await ev(HEAD), {rows: 2, words: true, pin: true});
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 904}}); await sleep(900);
    if (!(await ev(`!!document.querySelector('#detail .dtop')`))) await ev(`(() => { openDetail(${T}); return 1; })()`), await sleep(700);
    headChecks('fold unfolded again', await ev(HEAD), {rows: 2, words: true, pin: true});
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 880, height: 904}}); await sleep(900);
    if (!(await ev(`!!document.querySelector('#detail .dtop')`))) await ev(`(() => { openDetail(${T}); return 1; })()`), await sleep(700);
    headChecks('880 portrait', await ev(HEAD), {rows: 1, words: false, pin: true});
    await shot('p2151-880-header.png');
    // the matrix keeps two columns on the unfolded Fold: no fold buttons
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 904}});
    await o.nav(B + '#matrix'); await ready(ev);
    check(await ev(`!document.querySelector('.quad .qfold')`), 'fold 904 matrix: two columns, no fold buttons');
  }, true);

  // desktop: unchanged, one row with the icons
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o, 'dark') === 200, '1440: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(800);
    const x = await ev(HEAD);
    check(x && x.over <= 0 && x.out === 0 && x.h < 60 && x.today && x.tom && !x.words && x.pin && Math.abs(x.chip.t - x.today.t) <= 3, '1440: one row, Today / Tomorrow as icons, Pin ' + JSON.stringify(x));
    check(!(await ev(`getComputedStyle(document.querySelector('#detail .dtop .dbr')).display !== 'none'`)), '1440: no row break');
    await shot('p2151-1440-header.png');
  }, false);

  console.log(`p2151_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
