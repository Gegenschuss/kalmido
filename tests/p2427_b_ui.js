// kalmido-suite: fresh
// 2.427.0 B (#3551) UI test, own container (start.sh), Firefox on a phone (390 x 844, touch) and on a desktop (1440 x 900,
// mouse): above the rows of a list with shown fields a field strip (.lcbar) names the fields; a tap on a name opens the
// column menu (sorting puts the arrow on the name), "Fields" opens "Shown fields". No strip in a board, none without shown
// fields; on the desktop the column titles stay and the strip is hidden. axe (WCAG 2.2 A + AA) over the strip.
// A person without an organisation in her private lists.
// freelancer-matrix: lists (no route touched; the person has no organisation)
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2427_b_ui', check, shots: 'P2427B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', modules: ['fields', 'kanban']});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.id > 0, 'the person without an organisation (setup)');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields,kanban'});
  const st = await call(CF, 'GET', '/api/state');
  check(!(st.orgs || []).length, 'frida has no organisation');
  // L: shown fields (date + a text field); P: no shown fields; K: shown fields, but a board
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Private things'})).id;
  const FT = (await call(CF, 'POST', `/api/lists/${L}/fields`, {name: 'Note', type: 'text'})).id;
  await call(CF, 'PATCH', `/api/lists/${L}`, {columns: ['due', `f:${FT}`]});
  const T = [];
  for (let i = 0; i < 5; i++) T.push((await call(CF, 'POST', '/api/tasks', {title: `Thing ${i + 1}`, list_id: L, due: '2026-11-0' + (1 + i), fields: {[FT]: `note ${5 - i}`}})).id);
  check(T.every(Boolean), 'five tasks with a note (setup)');
  const P = (await call(CF, 'POST', '/api/lists', {name: 'Plain things'})).id;
  const TP = (await call(CF, 'POST', '/api/tasks', {title: 'Plain one', list_id: P})).id;
  const K = (await call(CF, 'POST', '/api/lists', {name: 'Board things'})).id;
  await call(CF, 'PATCH', `/api/lists/${K}`, {columns: ['due'], view: 'kanban'});
  const TK = (await call(CF, 'POST', '/api/tasks', {title: 'Card one', list_id: K, due: '2026-11-02'})).id;
  const KF = `f:${FT}`;
  const shown = sel => `(() => { const e = document.querySelector('${sel}'); return !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0; })()`;

  // ---- the phone
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const tap = async sel => { const b = await ev(`(() => { const e = document.querySelector('${sel}'); if (!e) return null; e.scrollIntoView({block: 'nearest', inline: 'nearest'}); const b = e.getBoundingClientRect(); return {x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2)}; })()`);
      if (!b) return false;
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: b.x, y: b.y}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx}); return true; };
    const item = re => `Array.from(document.querySelectorAll('[role="menuitem"]')).find(b => ${re}.test(b.textContent) && b.getClientRects().length)`;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#tc-${T[4]}') && !!document.querySelector('#view .lcbar')`), '#3551: phone: the list with shown fields has the field strip');
    const bar = await ev(`(() => { const b = document.querySelector('#view .lcbar'); if (!b) return null; const r = b.getBoundingClientRect();
      return {lid: +b.dataset.lid, ks: [...b.querySelectorAll('.lcbn')].map(x => x.dataset.k), names: [...b.querySelectorAll('.lcbn')].map(x => x.textContent.trim()),
        h: Math.min(...[...b.querySelectorAll('button')].map(x => x.getBoundingClientRect().height)), w: r.width, sw: document.documentElement.scrollWidth,
        fields: b.querySelector('.lcbf')?.textContent.trim(), ico: !!b.querySelector('.lcbf svg'), rowTop: document.querySelector('#tc-${T[0]}').getBoundingClientRect().top, top: r.top}; })()`);
    check(await ev(shown('#view .lcbar')) && !(await ev(shown('#view .lchead'))), '#3551: phone: the strip is shown, the column titles stay hidden');
    check(bar && bar.lid === L && JSON.stringify(bar.ks) === JSON.stringify(['due', KF]) && bar.names.includes('Note'), `#3551: the strip names the shown fields in their order (${bar && bar.names})`);
    check(bar && bar.fields === 'Fields' && bar.ico, `#3551: "Fields" with the columns icon at the end (${bar && bar.fields})`);
    check(bar && bar.h >= 44, `#3551: 44 px tap targets (${bar && bar.h})`);
    check(bar && bar.top < bar.rowTop && bar.sw <= 391, `#3551: the strip sits above the rows, nothing sideways (page ${bar && bar.sw} px)`);
    await shot('p2427b-strip.png');
    // axe over the strip
    if ((await ev(`typeof axe`)) === 'undefined') await ev(AXE + '\n;1');
    const ax = await ev(`axe.run('#view .lcbar', {runOnly: {type: 'tag', values: ${JSON.stringify(TAGS)}}, resultTypes: ['violations']}).then(r => r.violations.map(v => v.id + '(' + v.nodes.length + ') ' + v.nodes[0].target.join(' ')))`);
    check(Array.isArray(ax) && !ax.length, '#3551: no axe violations in the strip: ' + JSON.stringify(ax).slice(0, 500));
    // a tap on "Note" opens the column menu; "Sort ascending" sorts and puts the arrow on the name
    await tap(`#view .lcbar .lcbn[data-k="${KF}"]`);
    check(await ready(`!!(${item('/Sort ascending/')})`), '#3551: a tap on a field name opens the column menu');
    const mi = await ev(`[...document.querySelectorAll('[role="menuitem"]')].filter(b => b.getClientRects().length).map(b => b.textContent.trim())`);
    check(mi.some(t => /Note/.test(t)) && mi.some(t => /Sort descending/.test(t)) && mi.some(t => /Hide column/.test(t)) && mi.some(t => /Shown fields/.test(t)),
      `#3551: the same menu as on the desktop (${mi.join(' | ').slice(0, 300)})`);
    await shot('p2427b-menu.png');
    await ev(`(${item('/Sort ascending/')}).click(), 1`);
    check(await ready(`!!document.querySelector('#view .lcbar .lcbn.sorted[data-k="${KF}"] .lcsa')`), '#3551: sorted by the field: its name carries the arrow');
    check(await ready(`(() => { const ids = [...document.querySelectorAll('#view .trow[data-id]')].map(x => +x.dataset.id); return ids.indexOf(${T[4]}) > -1 && ids.indexOf(${T[4]}) < ids.indexOf(${T[0]}); })()`),
      '#3551: the rows follow the sort (note 1 before note 5)');
    // "Fields" opens "Shown fields"
    await tap('#view .lcbar .lcbf');
    check(await ready(`!!document.querySelector('#col-t') && /Shown fields/.test(document.querySelector('#col-t').textContent)`), '#3551: "Fields" opens "Shown fields"');
    await shot('p2427b-fields.png');
    // no strip without shown fields, none in a board
    await nav(B + '#l/' + P);
    check(await ready(`!!document.querySelector('#view .trow[data-id="${TP}"]')`), 'the list without shown fields');
    check(!(await ev(`!!document.querySelector('#view .lcbar')`)), '#3551: no strip without shown fields');
    await nav(B + '#l/' + K);
    check(await ready(`!!document.querySelector('.kanban') && !!document.querySelector('.kanban .trow[data-id="${TK}"]')`), 'the board');
    check(!(await ev(`!!document.querySelector('#view .lcbar')`)), '#3551: no strip in a board');
  }, true);

  // ---- the desktop: the column titles as before, the strip hidden
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`!!document.querySelector('#tc-${T[4]}') && !!document.querySelector('#view .lchead .lc[data-k="${KF}"]')`), 'desktop: the list with column titles');
    check(await ev(shown('#view .lchead')) && !(await ev(shown('#view .lcbar'))), '#3551: desktop: the column titles are shown, the strip is hidden');
  }, false);

  console.log(`p2427_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
