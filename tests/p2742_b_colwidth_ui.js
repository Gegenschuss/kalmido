// 2.742.0 B (#4857) UI test, own container (start.sh), Firefox on a desktop (1440 x 900, mouse) and a phone (390 x 844):
// kalmido-suite: fresh
// the columns of a list get their width from a grip in the column title, per person and list on every device (the user
// setting col_widths, accounts/colwidths.py): dragging widens the column, a reload (and a fresh browser profile = another
// device) keeps it, another list stays as it is, a double-click on the grip = the automatic width again, the grip has no
// upper limit of its own (#4830: only the title keeps its minimum), a click on the column title still sorts (#354) and the
// drag does not, a phone shows no grip and its rows keep their own widths. API: the patch of one list is merged, a wrong
// value is a 400, null = the standard widths. A person without an organisation in her private lists.
// freelancer-matrix: lists (no route touched; PATCH /api/settings only; the person has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2742_b_colwidth_ui', check, shots: 'P2742B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const widths = async ck => JSON.parse((await call(ck, 'GET', '/api/state')).settings?.col_widths || '{}');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['fields']});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.id > 0, 'the person without an organisation (setup)');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields'});
  check(!((await call(CF, 'GET', '/api/state')).orgs || []).length, 'frida has no organisation');
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Private things'})).id, L2 = (await call(CF, 'POST', '/api/lists', {name: 'Other things'})).id;
  const T = [], T2 = [];
  for (const [lid, arr] of [[L, T], [L2, T2]]) {
    const ft = (await call(CF, 'POST', `/api/lists/${lid}/fields`, {name: 'Note', type: 'text'})).id;
    await call(CF, 'PATCH', `/api/lists/${lid}`, {columns: ['due', 'prio', `f:${ft}`]});
    for (let i = 0; i < 4; i++) arr.push((await call(CF, 'POST', '/api/tasks', {title: `Thing ${i + 1}`, list_id: lid, due: `2026-11-0${4 - i}`, priority: i % 2 ? 5 : 0, fields: {[ft]: `note ${i}`}})).id);
  }
  check(T.every(Boolean) && T2.every(Boolean), 'two lists with due, priority and a note (setup)');

  // ---- API: one list's patch is merged, a wrong value is refused, null drops the list
  check((await call(CF, 'PATCH', '/api/settings', {col_widths: {[L2]: {due: 9}}})).http === 200, 'API: a list width is stored');
  check((await call(CF, 'PATCH', '/api/settings', {col_widths: {999999: {prio: 6.123}}})).http === 200, 'API: a second list');
  let w = await widths(CF);
  check(w[L2]?.due === 9 && w[999999]?.prio === 6.12, 'API: the second patch is merged, not replacing the first ' + JSON.stringify(w));
  for (const bad of [{x: {due: 5}}, {[L]: {'Due!': 5}}, {[L]: {due: 'wide'}}, {[L]: [5]}, '[1]'])
    check((await call(CF, 'PATCH', '/api/settings', {col_widths: bad})).http === 400, 'API: a malformed value is refused ' + JSON.stringify(bad));
  await call(CF, 'PATCH', '/api/settings', {col_widths: {[L2]: null, 999999: null}});
  check(!Object.keys(await widths(CF)).length, 'API: null = the standard widths again');
  check(!Object.keys(JSON.parse((await call(CA, 'GET', '/api/state')).settings?.col_widths || '{}')).length, 'another person keeps their own (empty) widths');

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const act = actions => cmd('input.performActions', {context: ctx, actions});
    const release = () => cmd('input.releaseActions', {context: ctx});
    const mid = sel => ev(`(() => { const e = document.querySelector('${sel}'); if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, w: b.width, l: b.left}; })()`);
    const mouse = (x, y, moves) => act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0},
      ...moves.map(dx => ({type: 'pointerMove', x: Math.round(x + dx), y: Math.round(y), duration: 30})), {type: 'pointerUp', button: 0}]}]);
    const cellW = (tid, k) => ev(`(() => { const e = document.querySelector('#tc-${tid} .lc[data-k="${k}"]'); return e ? e.getBoundingClientRect().width : -1; })()`);
    const signIn = async () => {
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    };
    await signIn();
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L2);
    check(await ready(`!!document.querySelector('#view .lchead .lcg[data-lcg="due"]') && !!document.querySelector('#tc-${T2[3]}')`), 'Firefox: the other list with its columns');
    const other0 = await cellW(T2[0], 'due');
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#view .lchead[data-lid="${L}"] .lcg[data-lcg="due"]') && !!document.querySelector('#tc-${T[3]}')`), 'Firefox: the private list with columns');
    const d0 = await cellW(T[0], 'due'), sort0 = await ev(`sortMode()`), SORTED = `[...document.querySelectorAll('.lchead .lc[aria-sort]')].map(e => e.dataset.k + ':' + e.getAttribute('aria-sort')).join()`, as0 = await ev(SORTED);

    // drag the due column's grip 80 px to the left = 80 px wider; the sort does not change
    const g = await mid(`.lchead .lcg[data-lcg="due"]`);
    await mouse(g.x, g.y, [20, 40, 60, 80].map(d => -d)); await release();
    check(await ready(`(lcwGet(${L}).due || 0) > 0 && !document.body.classList.contains('pgdrag')`), 'the dragged width is kept');
    const d1 = await cellW(T[0], 'due');
    check(Math.abs(d1 - (d0 + 80)) <= 3, `#4857: the column got wider by the drag (${d0} -> ${d1} px)`);
    check(await ev(`sortMode()`) === sort0 && await ev(SORTED) === as0, `#354: the drag on the grip does not sort (${sort0}, ${as0})`);
    check(await ready(`fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(s => (JSON.parse(s.settings.col_widths || '{}')['${L}'] || {}).due > 0)`), '#4857: the account keeps the width (user setting)');
    check(!(await ev(`localStorage.getItem('tasks.lcw.${L}')`)), '#4857: nothing per device any more');
    await shot('p2742b-dragged.png');

    // a reload and a fresh profile (= another device) keep it; the other list stays as it was
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#tc-${T[0]} .lc[data-k="due"]') && Math.abs(document.querySelector('#tc-${T[0]} .lc[data-k="due"]').getBoundingClientRect().width - ${d1}) <= 2`), '#4857: after a reload the width stays');
    await signIn();
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#tc-${T[0]} .lc[data-k="due"]') && Math.abs(document.querySelector('#tc-${T[0]} .lc[data-k="due"]').getBoundingClientRect().width - ${d1}) <= 2`), '#4857: another device (empty storage) shows the same width');
    await nav(B + '#l/' + L2);
    check(await ready(`!!document.querySelector('#tc-${T2[0]} .lc[data-k="due"]')`), 'the other list');
    check(Math.abs((await cellW(T2[0], 'due')) - other0) <= 1 && !Object.keys(await ev(`lcwGet(${L2})`)).length, `#4857: the other list keeps its width (${other0} / ${await cellW(T2[0], 'due')})`);

    // no upper limit of its own (the former 24 rem): as far as the title keeps its 12 rem minimum
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#view .lchead[data-lid="${L}"] .lcg[data-lcg="prio"]')`), 'back in the list');
    const gp = await mid(`.lchead .lcg[data-lcg="prio"]`);
    await mouse(gp.x, gp.y, [200, 400, 600, 800, 1000, 1200].map(d => -Math.min(d, gp.x - 10))); await release();
    check(await ready(`(lcwGet(${L}).prio || 0) > 0`), 'the wide drag is kept');
    const wide = await ev(`(() => { const rem = parseFloat(getComputedStyle(document.documentElement).fontSize); return {w: lcwGet(${L}).prio, sp: document.querySelector('.lchead .spacer').getBoundingClientRect().width / rem}; })()`);
    check(wide.w > 24, `#4830: a column gets wider than the former 24 rem (${wide.w} rem)`);
    check(wide.sp >= 11.9, `#4830: the title keeps its minimum (${wide.sp.toFixed(2)} rem)`);
    await shot('p2742b-wide.png');

    // a double-click on the grip = the automatic width again
    const gp2 = await mid(`.lchead .lcg[data-lcg="prio"]`);
    await act([{type: 'pointer', id: 'p1', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(gp2.x), y: Math.round(gp2.y)},
      {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]); await release();
    check(await ready(`!('prio' in lcwGet(${L})) && (lcwGet(${L}).due || 0) > 0`), '#4857: a double-click = the automatic width (only that column)');
    check(await ready(`fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(s => { const w = JSON.parse(s.settings.col_widths || '{}')['${L}'] || {}; return !('prio' in w) && w.due > 0; })`), '#4857: the account forgets the automatic one too');

    // a click on the column title still sorts (#354)
    await ev(`(() => { document.querySelector('.lchead [data-colsort="due"]').click(); return 1; })()`);
    check(await ready(`sortMode() !== '${sort0}' && !!document.querySelector('.lchead .lc[data-k="due"]')?.hasAttribute('aria-sort')`), '#354: a click on the column title sorts');
    await ev(`(() => { document.querySelector('.lchead [data-colsort="due"]').click(); document.querySelector('.lchead [data-colsort="due"]')?.click(); return 1; })()`);

    // the phone: no column titles and no grip; the rows keep their own widths (the stored width does not apply)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#tc-${T[0]}')`), 'phone: the list');
    check(await ev(`(() => { const g = document.querySelector('.lchead .lcg'); return !g || !g.getBoundingClientRect().width; })()`), '#4857: a phone shows no grip');
    const pd = await cellW(T[0], 'due');
    check(pd < 0 || Math.abs(pd - d1) > 3, `#4857: on the phone the row does not take the stored width (${pd} px, desktop ${d1})`);
    await shot('p2742b-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
  }, false);

  console.log(`p2742_b_colwidth_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
