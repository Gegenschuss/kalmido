// 2.750.0 B (#4502) UI test, own container (start.sh).
// kalmido-suite: fresh
// The column titles (.lchead) with sorting by a click in the collected views (Today, My tasks) and in a list without its own columns; the column "Project" (key list) in the collected views,
// not in a single list; the shown columns of the collected views are the person's own (user setting view_cols, 400 for
// unknown keys). jsdom for the logic, Firefox on a phone (390 x 844, touch: strip instead of titles, nothing sideways) and
// on a desktop (1440 x 900: the titles, the project column visible). Everything as a person without an organisation.
// freelancer-matrix: lists (no new route; PATCH /api/settings view_cols as the person without an organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2548_b_ui', check, shots: 'P2548B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = (fn, ms = 15000) => require('./boot').until(fn, {timeout: ms, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['fields', 'collab']});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.id > 0, 'the person without an organisation (setup)');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields,collab'});
  const ST0 = await call(CF, 'GET', '/api/state'), ME = fr.id;
  check(!(ST0.orgs || []).length && ME > 0, 'frida has no organisation');
  // two private lists; Zulu's task is created first (manual order), so a sort by project has to move it
  const Z = (await call(CF, 'POST', '/api/lists', {name: 'Zulu works'})).id, A = (await call(CF, 'POST', '/api/lists', {name: 'Alpha works'})).id;
  const TZ = (await call(CF, 'POST', '/api/tasks', {title: 'Zebra job', list_id: Z, due: day(0), assignee_id: ME})).id;
  const TA = (await call(CF, 'POST', '/api/tasks', {title: 'Apple job', list_id: A, due: day(0), assignee_id: ME})).id;
  const TA2 = (await call(CF, 'POST', '/api/tasks', {title: 'Apricot job', list_id: A, due: day(3), assignee_id: ME})).id;
  check(TZ && TA && TA2, 'three tasks (setup)');

  // ---- the setting: the person's own, checked by the server
  check((await call(CF, 'PATCH', '/api/settings', {view_cols: '["due","bogus"]'})).http === 400, 'view_cols: an unknown key is 400');
  check((await call(CF, 'PATCH', '/api/settings', {view_cols: '[]'})).http === 400, 'view_cols: an empty list is 400');
  check((await call(CF, 'PATCH', '/api/settings', {view_cols: ''})).http < 300, 'view_cols: "" = the default');

  // ---- jsdom: Today
  let w = await boot({user: 'frida', hash: 'today'}), d = w.document;
  const ids = () => [...d.querySelectorAll('#view .trow[data-id]')].map(x => +x.dataset.id);
  check(await until(() => d.querySelector(`#view .trow[data-id="${TA}"]`) && d.querySelector('#view .lchead')), 'Today: the column titles above the rows');
  const head = () => d.querySelector('#view .lchead');
  check(head()?.dataset.lid === 'v' && !!head().querySelector('.lc[data-k="list"] [data-colsort="list"]') && !!head().querySelector('.lc[data-k="due"]'), 'Today: the titles carry the columns Due and Project ' + [...(head()?.querySelectorAll('.lc') || [])].map(x => x.dataset.k).join());
  check(/Alpha works/.test(d.querySelector(`#view .trow[data-id="${TA}"] .lcols .lc-list`)?.textContent || ''), 'Today: the row shows its project in the column');
  check(!/Today/.test(d.querySelector(`#view .trow[data-id="${TA}"] .lcols .lc-due`)?.textContent || 'Today'), 'Today: due today without a time = an empty date cell (#1051)');
  // a click on "Project" sorts A-Z, a second one Z-A, a third one back
  click(w, head().querySelector('[data-colsort="list"]'));
  check(await until(() => ids().indexOf(TA) > -1 && ids().indexOf(TA) < ids().indexOf(TZ) && head()?.querySelector('.lc[data-k="list"]')?.getAttribute('aria-sort') === 'ascending'), 'Today: click on Project = A-Z (aria-sort ascending) ' + ids().join());
  click(w, head().querySelector('[data-colsort="list"]'));
  check(await until(() => ids().indexOf(TZ) > -1 && ids().indexOf(TZ) < ids().indexOf(TA) && head()?.querySelector('.lc[data-k="list"]')?.getAttribute('aria-sort') === 'descending'), 'Today: second click = Z-A ' + ids().join());
  click(w, head().querySelector('[data-colsort="list"]'));
  check(await until(() => !head()?.querySelector('.lc[aria-sort]')), 'Today: third click = the view\'s sort again');
  // the column menu: hide "Tags" = the person's setting, at once on screen
  const tg = head().querySelector('.lc[data-k="tags"]');
  check(!!tg, 'Today: the Tags column by default');
  if (tg) {
    w.eval(`lcMenu(document.querySelector('#view .lchead .lc[data-k="tags"]'))`);
    const hide = await until(() => [...d.querySelectorAll('[role="menuitem"]')].find(b => /Hide column/.test(b.textContent)));
    check(!!hide && [...d.querySelectorAll('[role="menuitem"]')].some(b => /Shown columns/.test(b.textContent)), 'Today: the column menu offers Hide column and Shown columns');
    if (hide) click(w, hide);
    check(await until(() => !d.querySelector('#view .lchead .lc[data-k="tags"]')), 'Today: the hidden column is gone from the titles');
    const st = await until(async () => { const s = (await call(CF, 'GET', '/api/state')).settings || {}; return s.view_cols ? s : null; });
    const vc = st ? JSON.parse(st.view_cols) : [];
    check(vc.includes('list') && vc.includes('due') && !vc.includes('tags'), 'the choice is stored for the person (view_cols ' + (st && st.view_cols) + ')');
  }
  w.close();

  // ---- jsdom: My tasks (needs collaboration: tasks assigned to me; the same titles and the same person's columns; a click sorts, though My tasks has its own order)
  w = await boot({user: 'frida', hash: 'assigned'}); d = w.document;
  check(await until(() => d.querySelector(`#view .trow[data-id="${TA2}"]`) && d.querySelector('#view .lchead[data-lid="v"]')), 'My tasks: the column titles');
  check(!d.querySelector('#view .lchead .lc[data-k="tags"]') && !!d.querySelector('#view .lchead .lc[data-k="list"]'), 'My tasks: the person\'s columns (Tags hidden in Today stays hidden here)');
  click(w, d.querySelector('#view .lchead [data-colsort="list"]'));
  check(await until(() => { const x = ids(); return x.indexOf(TA) > -1 && x.indexOf(TA2) > -1 && x.indexOf(TZ) > -1 && Math.max(x.indexOf(TA), x.indexOf(TA2)) < x.indexOf(TZ); }), 'My tasks: click on Project sorts A-Z ' + ids().join());
  w.close();

  // ---- jsdom: a single list without its own columns: the same titles, no project column
  w = await boot({user: 'frida', hash: 'l/' + A}); d = w.document;
  check(await until(() => d.querySelector(`#view .trow[data-id="${TA}"]`) && d.querySelector('#view .lchead')), 'a list without its own columns: the column titles');
  check(d.querySelector('#view .lchead')?.dataset.lid === String(A) && !!d.querySelector('#view .lchead [data-colsort="due"]'), 'the list: its default columns (Due) as titles');
  check(!d.querySelector('#view .lchead .lc[data-k="list"]') && !d.querySelector('#view .lcols .lc-list'), 'the list: no column Project');
  check(!w.eval(`colChoices(listById(${A}))`).some(x => x[0] === 'list'), 'the list\'s Columns dialog does not offer Project');
  click(w, d.querySelector('#view .lchead [data-colsort="due"]'));
  check(await until(() => ids().indexOf(TA) > -1 && ids().indexOf(TA) < ids().indexOf(TA2) && !!d.querySelector('#view .lchead .lc[data-k="due"][aria-sort]')), 'the list: a click on Due sorts by the date');
  check((await call(CF, 'GET', '/api/state')).lists.find(l => l.id === A).columns == null, 'the list keeps no own columns from sorting');
  // job/2754: what the default columns leave out stays in the second line: sorted by Created, the creation date
  w.eval(`sortSet('created')`);
  check(await until(() => !!d.querySelector(`#view .trow[data-id="${TA}"] .meta .crd`)), 'the list: sorted by Created, the row shows its creation date');
  w.close();

  const shown = sel => `(() => { const e = document.querySelector('${sel}'); return !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0; })()`;
  const enter = async ({ev, cmd, ctx, nav}, vw, vh) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
  };
  // ---- the phone: no titles, the strip of names, nothing sideways
  await firefox(async o => {
    const {ev, nav, shot} = o;
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await enter(o, 390, 844);
    await nav(B + '#today');
    check(await ready(`!!document.querySelector('#view .trow[data-id="${TA}"]') && !!document.querySelector('#view .lcbar[data-lid="v"]')`), 'phone: Today has the strip of column names');
    check(await ev(shown('#view .lcbar')) && !(await ev(shown('#view .lchead'))), 'phone: the strip is shown, the column titles are hidden');
    const g = await ev(`(() => { const r = document.querySelector('#view .trow[data-id="${TA}"]'), t = r.querySelector('.ttl').getBoundingClientRect(); return {sw: document.documentElement.scrollWidth, tw: Math.round(t.width), cols: !!r.querySelector('.lcols')}; })()`);
    check(g && g.sw <= 391 && g.tw > 120 && g.cols, 'phone: nothing sideways, the title keeps its room ' + JSON.stringify(g));
    await shot('p2548b-today-phone.png');
    await ev(`document.querySelector('#view .lcbar [data-act="vcols"]').click(), 1`);
    check(await ready(`[...document.querySelectorAll('[role="menuitem"]')].some(b => /Project/.test(b.textContent) && b.getClientRects().length)`), 'phone: "Columns" opens the person\'s column choice');
  }, true);
  // ---- the desktop: the titles, the project column visible
  await firefox(async o => {
    const {ev, nav, shot} = o;
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await enter(o, 1440, 900);
    await nav(B + '#today');
    check(await ready(`!!document.querySelector('#view .trow[data-id="${TA}"]') && !!document.querySelector('#view .lchead[data-lid="v"]')`), 'desktop: Today with column titles');
    check(await ev(shown('#view .lchead')) && await ev(shown(`#view .trow[data-id="${TA}"] .lcols .lc-list`)) && !(await ev(shown('#view .lcbar'))), 'desktop: titles and the project column shown, no strip');
    const al = await ev(`(() => { const h = document.querySelector('#view .lchead .lc[data-k="list"]').getBoundingClientRect(), c = document.querySelector('#view .trow[data-id="${TA}"] .lcols .lc-list').getBoundingClientRect(); return Math.abs(h.right - c.right); })()`);
    check(al < 3, 'desktop: the title lines up with its cells (' + al + ' px)');
    await shot('p2548b-today-desktop.png');
  }, false);

  console.log(`p2548_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
