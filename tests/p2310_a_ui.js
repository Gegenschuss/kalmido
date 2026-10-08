// 2.31.0 UI tests, part A ("Phone everyday use"), own container (start.sh). Firefox (390 touch, 1440 mouse):
// #1051 task row: a tap between the circle and the title (where the number was) opens the task; on the phone the number
//      sits in the meta line, so titles with and without a number start at the same x; the last row is not covered by the
//      tab bar or the "+" button; a pin only on pinned rows (a mouse also sees it on hover and pins with it); Today shows
//      no "Today" chip per task (only a time)
// #1052 Today: the daily review folds to one line after its first read (and unfolds again), its numbers not in mono;
//      "All to today" / "Another day…" in the head of "Overdue" (no card of their own); no agent band for an offline agent
// #1053 list header: progress, overdue and next due in ONE slim line, no "Set status" there (it is in the list's "…"
//      menu), the view switch 36 px high on the phone
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2310_a_ui', check, shots: 'P2310A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields';
const ds = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return ds(d); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  // work_end 00:00: the daily review card is due all day
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, work_start: '00:00', work_end: '00:00'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});  // never connected = offline
  const SW = (await call('POST', '/api/lists', {name: 'Software', kind: 'project', tickets: true})).id;
  await call('PUT', `/api/lists/${SW}/members`, {user_id: BOB, role: 'edit'});
  const HOME = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const OVER = await mk('Weekly report', SW, {due: day(-2), priority: 5});
  const T1 = await mk('Offer for the client', SW, {due: day(0)});
  const TT = await mk('Standup call', SW, {due: day(0), due_time: '10:00'});
  const H1 = await mk('Call the plumber', HOME, {due: day(0)});
  const PIN = await mk('Pinned for the week', SW, {due: day(3)});
  await call('PATCH', `/api/tasks/${PIN}`, {pinned: 1});
  for (let i = 0; i < 14; i++) await mk('Backlog item ' + (i + 1), SW, {due: day(5 + i)});
  await mk('The very last task', SW, {due: day(30)});
  const DN = await mk('Done thing', SW, {due: day(0)});
  await call('POST', `/api/tasks/${DN}/complete`, {});

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const tap = (cmd, ctx, x, y, kind = 'touch') => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'p', parameters: {pointerType: kind}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
  const rowJs = id => `document.querySelector('#view .trow[data-id="${id}"]')`;

  // ================= the phone (390, touch)
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    // #1053 the list header
    await nav(B + '#l/' + SW); await ready(ev);
    const lh = await ev(`(() => { const h = document.querySelector('#view .lhead'), p = h && h.querySelector('.lprow'); if (!h || !p) return null; const r = h.getBoundingClientRect(), pr = p.getBoundingClientRect(), bar = p.querySelector('.pbar').getBoundingClientRect(), o = p.querySelector('.lmeta.over'), n = p.querySelector('.lnext');
      return {h: Math.round(r.height), pTop: Math.round(pr.top), barW: Math.round(bar.width), over: !!o && o.getBoundingClientRect().top >= pr.top - 1 && o.getBoundingClientRect().bottom <= pr.bottom + 1 && o.getBoundingClientRect().left > bar.right,
        next: !!n && n.getBoundingClientRect().bottom <= pr.bottom + 1 && n.getBoundingClientRect().right <= innerWidth, set: !!document.querySelector('#view .stpill.none'), sx: document.documentElement.scrollWidth}; })()`);
    check(lh && lh.h <= 50 && lh.barW >= 40 && lh.over && lh.next && lh.sx <= 390, `${tag}: #1053 progress, overdue and next due in one line (bar left, texts right) ` + JSON.stringify(lh));
    check(lh && !lh.set, `${tag}: #1053 no "Set status" in the list view`);
    const vs = await ev(`(() => { const b = [...document.querySelectorAll('#view .vsegm button')].map(x => x.getBoundingClientRect().height); return b.length ? {min: Math.min(...b), max: Math.max(...b)} : null; })()`);
    check(vs && vs.min >= 24 && vs.max <= 40, `${tag}: #1053 the view switch about 36 px high (>= 24) ` + JSON.stringify(vs));
    // #1053 "Set status" in the list's "…" menu
    await ev(`(() => { listMenu(document.querySelector('#top h1'), ${SW}); return 1; })()`); await sleep(500);
    check(await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].some(x => /Set status/.test(x.textContent))`), `${tag}: #1053 "Set status" in the list's menu`);
    await ev(`(() => { closePop(); return 1; })()`); await sleep(200);
    // #1051 the number in the meta line, no gutter; no pin on rows that are not pinned
    const nm = await ev(`(() => { const r = ${rowJs(T1)}, g = r.querySelector('.tgut'), m = r.querySelector('.meta .mid'); return {gut: !!g && g.getBoundingClientRect().width === 0, mid: !!m && m.getBoundingClientRect().width > 0 && m.textContent === '#${T1}'}; })()`);
    check(nm.gut && nm.mid, `${tag}: #1051 the number sits in the meta line on the phone ` + JSON.stringify(nm));
    const pins = await ev(`(() => { const vis = e => !!e && e.getBoundingClientRect().width > 0 && getComputedStyle(e).opacity !== '0'; const rows = [...document.querySelectorAll('#view .trow')]; return {pinned: vis(${rowJs(PIN)}.querySelector('.meta .pinm')), others: rows.filter(r => r.dataset.id !== '${PIN}').filter(r => vis(r.querySelector('.pinm, .rpin'))).length}; })()`);
    check(pins.pinned && pins.others === 0, `${tag}: #1051 a pin only on the pinned row ` + JSON.stringify(pins));
    await shot('p2310a-390-list.png');
    // #1051 a tap on the number (now in the meta line, where the dead zone was) opens the task; the circle's own 44 px
    // target ends where the title begins
    const pt = await ev(`(() => { const r = ${rowJs(T1)}; r.scrollIntoView({block: 'center'}); const c = r.querySelector('.chk'), t = r.querySelector('.ttl').getBoundingClientRect(), m = r.querySelector('.meta .mid').getBoundingClientRect(), hit = c.getBoundingClientRect().right + parseFloat(getComputedStyle(c, '::after').right) * -1; return {x: m.left + m.width / 2, y: m.top + m.height / 2, hitEnd: Math.round(hit), title: Math.round(t.left), num: Math.round(m.left)}; })()`);
    // 2.31.1 (device test): on a real phone the circle's touch area reached over the number and ticked the task off
    check(pt.hitEnd <= pt.num - 4 && pt.hitEnd <= pt.title - 4, `${tag}: #1051 the circle's touch area ends before the number and the title ` + JSON.stringify(pt));
    await sleep(300);
    await tap(cmd, ctx, pt.x, pt.y); await sleep(900);
    check(await ev(`S.sel === ${T1} && !!document.querySelector('#detail.open')`) && !(await call('GET', '/api/state')).tasks.find(t => t.id === T1)?.status, `${tag}: #1051 a tap on the number opens the task ` + JSON.stringify(pt));
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(600);
    // #1051 the last row is not covered by the tab bar or the "+" button
    await ev(`(() => { const v = document.querySelector('#view'); v.scrollTop = v.scrollHeight; return 1; })()`); await sleep(500);
    const lr = await ev(`(() => { const r = [...document.querySelectorAll('#view .trow')].pop().getBoundingClientRect(), f = document.querySelector('#fab').getBoundingClientRect(), t = document.querySelector('#tabs').getBoundingClientRect(); return {row: Math.round(r.bottom), fab: Math.round(f.top), tabs: Math.round(t.top)}; })()`);
    check(lr.row <= lr.fab && lr.row <= lr.tabs, `${tag}: #1051 the last row ends above the "+" button and the tab bar ` + JSON.stringify(lr));
    await shot('p2310a-390-list-end.png');
    // Today: one x for every title (with and without number), no "Today" chip, the time stays
    await nav(B + '#today/review'); await ready(ev); await sleep(800);
    const ti = await ev(`(() => { const rows = [...document.querySelectorAll('#view .trow:not(.sub)')].filter(r => r.getBoundingClientRect().width); const xs = rows.map(r => Math.round(r.querySelector('.ttl').getBoundingClientRect().left)); return {n: rows.length, xs: [...new Set(xs)]}; })()`);
    check(ti.n >= 4 && ti.xs.length === 1, `${tag}: #1051 in Today every title starts at the same x (lists with and without numbers) ` + JSON.stringify(ti));
    const chip = await ev(`(() => ({t1: ${rowJs(T1)}.querySelector('.meta .dt')?.textContent || '', h1: ${rowJs(H1)}.querySelector('.meta .dt')?.textContent || '', tt: ${rowJs(TT)}.querySelector('.meta .dt')?.textContent || '', over: ${rowJs(OVER)}.querySelector('.meta .dt')?.textContent || ''}))()`);
    check(!chip.t1 && !chip.h1 && /10:00/.test(chip.tt) && !/Today/.test(chip.tt) && chip.over.length > 0, `${tag}: #1051 no "Today" chip in Today, the time and overdue stay ` + JSON.stringify(chip));
    // #1052 overdue actions in the head of "Overdue", no card
    const od = await ev(`(() => ({head: !!document.querySelector('#view .ghead.over .odact [data-act="od-move"]') && !!document.querySelector('#view .ghead.over .odact [data-act="od-other"]'), card: !!document.querySelector('#view .odban')}))()`);
    check(od.head && !od.card, `${tag}: #1052 "All to today" / "Another day…" in the head of Overdue ` + JSON.stringify(od));
    // #1052 the review: full on its first read, numbers not in mono
    const rv = await ev(`(() => { const c = document.querySelector('#view .rvcard'), n = c && c.querySelector('.rvnums'); return c ? {fold: c.classList.contains('fold'), mono: !n || getComputedStyle(n).fontFamily === getComputedStyle(document.querySelector('#view .meta .mid')).fontFamily} : null; })()`);
    check(rv && !rv.fold && !rv.mono, `${tag}: #1052 the review card in full on the first read, numbers in the normal font ` + JSON.stringify(rv));
    await shot('p2310a-390-today-review.png');
    await nav(B + '#today'); await ready(ev); await sleep(800);
    const fd = await ev(`(() => { const c = document.querySelector('#view .rvcard'); if (!c) return null; const r = c.getBoundingClientRect(); return {fold: c.classList.contains('fold'), h: Math.round(r.height), txt: c.textContent.replace(/\\s+/g, ' ').trim(), plan: !!c.querySelector('[data-act="dayplan"]'), sx: document.documentElement.scrollWidth}; })()`);
    check(fd && fd.fold && fd.h <= 56 && /1 done · \d+ still open/.test(fd.txt) && fd.plan && fd.sx <= 390, `${tag}: #1052 back in Today the review is one line ("1 done · … · Plan tomorrow") ` + JSON.stringify(fd));
    await shot('p2310a-390-today.png');
    await ev(`(() => { document.querySelector('#view .rvcard .rvfold').click(); return 1; })()`); await sleep(500);
    check(await ev(`!!document.querySelector('#view .rvcard:not(.fold) .rvnums')`), `${tag}: #1052 a tap unfolds it`);
    await ev(`(() => { route(); return 1; })()`); await sleep(500);
    check(await ev(`!!document.querySelector('#view .rvcard:not(.fold)')`), `${tag}: #1052 unfolded stays unfolded today`);
    await ev(`(() => { document.querySelector('#view .rvcard .rvfold').click(); return 1; })()`); await sleep(500);
    check(await ev(`!!document.querySelector('#view .rvcard.fold')`), `${tag}: #1052 and folds again`);
  }, true);

  // ================= the desktop (1440, mouse)
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o, tag = '1440';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#today'); await ready(ev); await sleep(600);
    check(await ev(`!document.querySelector('#view .agband')`), `${tag}: #1052 no agent band in Today for an agent that is only offline`);
    check(await ev(`!!document.querySelector('#view .ghead.over .odact') && !document.querySelector('#view .odban')`), `${tag}: #1052 the overdue actions in the head of Overdue`);
    await nav(B + '#l/' + SW); await ready(ev); await sleep(600);
    // the number stays in its gutter on the desktop, and a click on it opens the task
    const g = await ev(`(() => { const r = ${rowJs(T1)}; r.scrollIntoView({block: 'center'}); const g = r.querySelector('.tgut'), m = r.querySelector('.meta .mid'); const b = g.getBoundingClientRect(); return {gut: b.width > 0, mid: !!m && m.getBoundingClientRect().width === 0, x: b.left + b.width / 2, y: b.top + b.height / 2}; })()`);
    check(g.gut && g.mid, `${tag}: #1051 the desktop keeps the number gutter ` + JSON.stringify(g));
    await tap(cmd, ctx, g.x, g.y, 'mouse'); await sleep(700);
    check(await ev(`S.sel === ${T1}`), `${tag}: #1051 a click on the number opens the task`);
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(400);
    // a click into the gap between the number and the title opens it too
    const gp = await ev(`(() => { const r = ${rowJs(TT)}; r.scrollIntoView({block: 'center'}); const g = r.querySelector('.tgut').getBoundingClientRect(), t = r.querySelector('.tmain').getBoundingClientRect(); return {x: (g.right + t.left) / 2, y: g.top + g.height / 2, gap: t.left - g.right}; })()`);
    await tap(cmd, ctx, gp.x, gp.y, 'mouse'); await sleep(700);
    check(await ev(`S.sel === ${TT}`), `${tag}: #1051 a click between the number and the title opens the task ` + JSON.stringify(gp));
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(400);
    // the pin: visible on the pinned row, on others only on hover; a click pins
    const op = id => ev(`(() => { const p = ${rowJs(id)}.querySelector('.rpin'); return p ? getComputedStyle(p).opacity : 'none'; })()`);
    check(await op(PIN) === '1' && await op(OVER) === '0', `${tag}: #1051 the pin shows on the pinned row only ` + await op(PIN) + '/' + await op(OVER));
    const hp = await ev(`(() => { ${rowJs(OVER)}.scrollIntoView({block: 'center'}); const r = ${rowJs(OVER)}.querySelector('.tmain').getBoundingClientRect(); return {x: r.left + 20, y: r.top + r.height / 2}; })()`);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(hp.x), y: Math.round(hp.y)}]}]}); await sleep(400);
    check(await op(OVER) === '1', `${tag}: #1051 hovering a row shows its pin`);
    await shot('p2310a-1440-list-hover.png');
    const pb = await ev(`(() => { const r = ${rowJs(OVER)}.querySelector('.rpin').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
    await tap(cmd, ctx, pb.x, pb.y, 'mouse'); await sleep(800);
    check((await call('GET', '/api/state')).tasks.find(t => t.id === OVER)?.pinned, `${tag}: #1051 a click on the hover pin pins the task`);
    await call('PATCH', `/api/tasks/${OVER}`, {pinned: 0});
    const lh = await ev(`(() => { const h = document.querySelector('#view .lhead'); return {h: Math.round(h.getBoundingClientRect().height), set: !!document.querySelector('#view .stpill.none'), full: /Next due:/.test(h.querySelector('.lnext')?.innerText || '')}; })()`);
    check(lh.h <= 40 && !lh.set && lh.full, `${tag}: #1053 one slim header line, "Next due: …" in words, no "Set status" ` + JSON.stringify(lh));
    await shot('p2310a-1440-list.png');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
