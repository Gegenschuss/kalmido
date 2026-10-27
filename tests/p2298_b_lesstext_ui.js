// 2.298.0 B (#3185): less text in tasks, projects, views, calendar, sidebar. Own container (start.sh). Firefox 390 x 844 touch:
// project status and timeline (screenshots with P2298B_SHOTS) and the reduced texts / icon labels / hidden hints.
// freelancer-matrix: tasks
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2298_b_lesstext_ui', check, shots: 'P2298B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2298B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const ds = n => { const d = new Date(Date.now() + n * 864e5); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const wait = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P1 = (await call('POST', '/api/lists', {name: 'Relaunch', view: 'timeline', kind: 'project'})).id;
  const P2 = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  for (const [t, l, due, start] of [['Design', P1, ds(3), ds(-2)], ['Build', P1, ds(9), ds(4)], ['Launch', P1, null, null], ['Copy', P2, ds(-1), null], ['Photos', P2, ds(5), null]])
    await call('POST', '/api/tasks', {title: t, list_id: l, due, ...(start ? {start} : {})});
  // a task with every row icon: pin, repeat, reminder, description, two subtasks (one done)
  const RICH = (await call('POST', '/api/tasks', {title: 'Rich row', list_id: P2, due: ds(2), repeat: 'FREQ=WEEKLY', reminders: '0', content: 'Some notes'})).id;
  await call('PATCH', `/api/tasks/${RICH}`, {pinned: 1});
  const K1 = (await call('POST', '/api/tasks', {title: 'Kid one', list_id: P2, parent_id: RICH})).id;
  await call('POST', '/api/tasks', {title: 'Kid two', list_id: P2, parent_id: RICH});
  await call('POST', `/api/tasks/${K1}/complete`, {});
  await call('POST', '/api/tasks', {title: 'Plain', list_id: P2});
  // alice has no organisation here: every check below is also the freelancer case (private space, own admin)

  // ================= jsdom (a mouse, English)
  let w = await boot({user: 'alice', hash: 'overview'}), d = w.document;
  check(await until(() => d.querySelector('.ovw .sttiles')), 'status page shows');
  const tl0 = [...d.querySelectorAll('.ovw .sttiles > div')];
  check(tl0.length >= 2 && tl0.every(x => x.title && !x.querySelector('small')), 'tiles: the sub line is the title, not a line of text ' + tl0.map(x => x.title).join('|'));
  check(!d.querySelector('.ovw .stnote') && await until(() => [...d.querySelectorAll('.ovw .shint.iisrc')].some(x => /Progress: completed vs\. all main tasks/.test(x.textContent))), 'progress rule sits behind (i), not as a paragraph');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + P1}); d = w.document;
  check(await until(() => d.querySelector('.tl-foot .shint')), 'timeline footer shows');
  const ft = d.querySelector('.tl-foot');
  check(/Drag a bar to move it/.test(ft.querySelector('.shint').textContent) && await until(() => ft.querySelector('.shint.iisrc') && ft.querySelector('.ib')), 'timeline: the operating sentences sit behind (i)');
  check(!d.querySelector('.mhint[data-hint="tlfoot"]'), 'timeline: the one-time hint is for touch only');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + P2}); d = w.document;
  const row = await until(() => [...d.querySelectorAll('#view .trow')].find(r => /Rich row/.test(r.textContent)));
  const tt = x => [...(row?.querySelectorAll(x) || [])];
  const has = (cls, tip, re) => { const e = tt('.meta ' + cls).find(x => x.title === tip || (re && re.test(x.title))); return !!e && new RegExp(tip.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).test(e.querySelector('.sr')?.textContent || ''); };
  check(row && has('.pinm', 'Pinned'), 'row: the pin has a title and a screen reader text');
  check(row && tt('.meta span').some(x => x.title === 'Repeats' && /Repeats/.test(x.querySelector('.sr')?.textContent || '')), 'row: repeat icon with title + text');
  check(row && tt('.meta span').some(x => x.title === 'Reminder' && /Reminder/.test(x.querySelector('.sr')?.textContent || '')), 'row: reminder icon with title + text');
  check(row && tt('.meta span').some(x => x.title === 'Has a description' && /Has a description/.test(x.querySelector('.sr')?.textContent || '')), 'row: description icon with title + text');
  check(row && has('.subc', '1 of 2 subtasks done'), 'row: subtask count says what it counts ' + tt('.meta .subc').map(x => x.title + '|' + x.textContent).join(';'));
  w.close();
  w = await boot({user: 'alice', hash: 'matrix'}); d = w.document;
  const qs = await until(() => [...d.querySelectorAll('.matrix .quad')].length === 4 && [...d.querySelectorAll('.matrix .quad')]);
  const emptyTxt = qs ? qs.map(q => q.querySelector('.qlist > .muted')?.textContent || '').filter(Boolean) : [];
  check(qs && emptyTxt.length >= 1 && emptyTxt.every(t => /^(High|Medium|Low) priority$|^No priority$/.test(t)) && !qs.some(q => /^empty$/.test(q.querySelector('.qlist > .muted')?.textContent || '')), 'matrix: an empty quadrant names its priority, not "empty" ' + emptyTxt.join('|'));
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + P2}); d = w.document;
  const rr = await until(() => [...d.querySelectorAll('#view .trow')].find(r => /Rich row/.test(r.textContent)));
  w.eval(`datePop(document.querySelector('#view .trow[data-id="${RICH}"]'), ${RICH})`);
  const pop = await until(() => d.querySelector('.mcal .mh [data-mm]') && d.querySelector('.mcal'));
  check(pop && [...d.querySelectorAll('.mcal .mh [data-mm]')].map(b => b.getAttribute('aria-label') + '/' + b.title).join('|') === 'Previous month/Previous month|Next month/Next month', 'date popover: the month arrows are named');
  check(pop && /Reminder \(before\)/.test(d.querySelector('.plab')?.textContent || '') && !d.querySelector('#dp-thint, #p-dl ~ .nothing'), 'date popover: the reminder row says "before"');
  const dl = d.querySelector('#p-dl');
  check(!dl || /days left/.test(dl.closest('label').title), 'date popover: the deadline box names its effect');
  w.close();
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#overview');
    check(await wait(ev, `!!document.querySelector('.ovw .sttiles')`), '390: the project status page shows');
    await sleep(500);
    await shot('p2298b-390-status.png');
    check(await ev(`document.documentElement.scrollWidth <= innerWidth + 1`), '390: the status page has no horizontal scrolling');
    check(await ev(`!!document.querySelector('.ovw .shint.iisrc') && getComputedStyle(document.querySelector('.ovw .shint.iisrc')).display === 'none'`), '390: the progress rule is not visible, only its (i)');
    await nav(B + '#l/' + P1);
    check(await wait(ev, `!!document.querySelector('.tl-foot')`), '390: the timeline shows');
    await sleep(500);
    await shot('p2298b-390-timeline.png');
    check(await ev(`!!document.querySelector('.mhint[data-hint="tlfoot"]')`), '390: the timeline operating hint shows the first time');
    check(await wait(ev, `!!document.querySelector('.tl-foot .ib') && getComputedStyle(document.querySelector('.tl-foot .shint')).display === 'none'`), '390: the footer sentences are behind (i), not visible');
    // 2.298.0 (#3185): the (i) of the footer names itself (data-iilabel) instead of a bare "More information"
    check(await ev(`(document.querySelector('.tl-foot .ib')?.getAttribute('aria-label') || '') === 'How to use the timeline' && /How to use the timeline/.test(document.querySelector('.tl-foot .ib').textContent)`), '390: the footer (i) reads "How to use the timeline"');
    await ev(`(() => { document.querySelector('[data-act="hint-x"][data-k="tlfoot"]').click(); return 1; })()`);
    await nav(B + '#l/' + P1);
    check(await wait(ev, `!!document.querySelector('.tl-foot')`) && await ev(`!document.querySelector('.mhint[data-hint="tlfoot"]') && !!document.querySelector('.tl-foot .ib')`), '390: after dismissing, the hint stays gone and the (i) stays');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
