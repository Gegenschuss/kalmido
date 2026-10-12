// 2.39.1 UI tests, part T (lists like a table), own container (start.sh), Firefox on a desktop (1440 x 900, mouse):
// - #1217: fine lines between the columns in every row (the colour of the row lines), none in a list without columns;
//   the width grip sits on the line left of its column (12 px), dragging follows the mouse without snapping, the title
//   keeps its minimum; a column title dragged to another place moves the column (saved for the list, Undo brings it back);
//   a click without moving still sorts; custom fields in a plain list
// - #1327: a click on a field cell edits it: number (unit shown, Enter saves), text (Esc cancels), choice (a menu with the
//   option colours), checkbox (toggles); Tab goes to the next cell; empty cells show a dash; sorting an empty column says
//   so; the arrow in the column title opens the column menu; "Shown fields…" adds a field (shown at once) and offers
//   rename / delete; with the module off, adding a field switches it on; a viewer gets no editable cells
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2391_t_ui', check, shots: 'P2391T_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'comments,collab,fields';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  // a PLAIN list (kind list) with custom fields as columns
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Receipts'})).id;
  const PLAIN = (await call(CA, 'POST', '/api/lists', {name: 'Shopping'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Milk', list_id: PLAIN});
  const FA = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Amount', type: 'number', options: {unit: 'EUR'}})).id;
  const FS = await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'State', type: 'select', options: {options: [{name: 'Open', color: '#e5484d'}, {name: 'Paid', color: '#30a46c'}]}});
  const FC = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Refunded', type: 'checkbox'})).id;
  const FN = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Note', type: 'text'})).id;
  const FE = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Empty', type: 'text'})).id;
  check(FA && FS.id && FC && FN && FE, '#1217: fields in a plain list (setup)');
  const PAID = FS.options.options.find(o => o.name === 'Paid').id;
  const COLS = ['due', `f:${FA}`, `f:${FS.id}`, `f:${FC}`, `f:${FN}`, `f:${FE}`];
  await call(CA, 'PATCH', `/api/lists/${L}`, {columns: COLS});
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: bob.id, role: 'view'});
  const T1 = (await call(CA, 'POST', '/api/tasks', {title: 'Pharmacy', list_id: L, due: '2026-10-20'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Dentist', list_id: L});
  const lst = async () => (await call(CA, 'GET', '/api/state')).lists.find(l => l.id === L);
  const task = async id => (await call(CA, 'GET', '/api/state')).tasks.find(t => t.id === id);

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot, drag} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const clickAt = (x, y) => act([{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
    const keys = (...ks) => act([{type: 'key', id: 'k', actions: ks.flatMap(k => [{type: 'keyDown', value: k}, {type: 'keyUp', value: k}])}]);
    const type = s => keys(...[...s]);
    const ENTER = '', ESC = '', TAB = '';
    const mid = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, l: b.left, r: b.right, w: b.width}; })()`);
    const cellSel = (tid, fid) => `#tc-${tid} .lc[data-k="f:${fid}"]`;
    const signIn = async u => { await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn('alice');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L); check(await ready(`typeof tcEdit === 'function' && !!document.querySelector('#view .lchead') && !!document.querySelector('#tc-${T1}')`), 'Firefox: the list with columns');
    await sleep(400);

    // ================= #1217 lines
    const ln = await ev(`(() => { const c = document.querySelector('#tc-${T1} .lc[data-k="due"]'), s = getComputedStyle(c, '::before'), row = c.closest('.trow');
      return {content: s.content, w: s.width, bg: s.backgroundColor, rowLine: getComputedStyle(row).borderBottomColor, pos: s.position}; })()`);
    check(ln.content !== 'none' && ln.w === '1px' && ln.bg === ln.rowLine && ln.pos === 'absolute', '#1217: a 1 px line left of each cell in the row colour ' + JSON.stringify(ln));
    // the line runs from the row's top to its bottom: the pixels above and below the cell text belong to it (elementFromPoint ignores
    // pseudo elements, so compare the cell box with the row box: the line is clipped to the row)
    const span = await ev(`(() => { const c = document.querySelector('#tc-${T1} .lc[data-k="f:${FA}"]'), r = c.closest('.trow').getBoundingClientRect(), b = c.getBoundingClientRect(); return {rowH: r.height, cellH: b.height, clip: getComputedStyle(c.closest('.trow')).overflowY}; })()`);
    check(span.clip === 'clip' && span.rowH > span.cellH, '#1217: the line spans the whole row (cut to the row) ' + JSON.stringify(span));
    const hd = await ev(`getComputedStyle(document.querySelector('.lchead .lc[data-k="due"]'), '::before').content`);
    check(hd !== 'none', '#1217: the line continues through the column titles');
    await shot('p2391t-lines.png');

    // ================= #1217 width: grip on the line left of the column, no snapping, title minimum
    const g = await mid(`.lchead .lcg[data-lcg="f:${FA}"]`), c0 = await mid(`.lchead .lc[data-k="f:${FA}"]`);
    check(g && Math.abs(g.w - 12) <= 1 && Math.abs(g.x - (c0.l - 6)) <= 2, `#1217: the grip is 12 px, centred on the line left of the column (${g && g.w} px at ${g && g.x}, cell from ${c0.l})`);
    await drag(g.x, g.y, -37, 0, 'mouse'); await sleep(300);
    const w1 = await ev(`(JSON.parse(localStorage.getItem('tasks.lcw.${L}') || '{}'))['f:${FA}'] || 0`);
    const rem = await ev(`parseFloat(getComputedStyle(document.documentElement).fontSize)`);
    const want = c0.w / rem + 37 / rem;
    check(Math.abs(w1 - want) < 0.15 && Math.abs(w1 * 4 - Math.round(w1 * 4)) > 0.01, `#1217: the width follows the mouse without snapping to 0.25 rem (${w1} rem, expected ${want.toFixed(2)})`);
    const c1 = await mid(`.lchead .lc[data-k="f:${FA}"]`);
    check(Math.abs(c1.l - (c0.l - 37)) <= 2, `#1217: the line moved with the mouse (${c0.l} -> ${c1.l})`);
    check(!(await ev(`!!document.querySelector('.lcguide')`)), '#1217: the accent guide is gone after the drag');
    const g2 = await mid(`.lchead .lcg[data-lcg="due"]`);
    await drag(g2.x, g2.y, 5 - g2.x, 0, 'mouse'); await sleep(300);  // as far left as the window goes
    const tw = await ev(`document.querySelector('.lchead .spacer').getBoundingClientRect().width / parseFloat(getComputedStyle(document.documentElement).fontSize)`);
    check(tw >= 11.5, `#1217: the title keeps its minimum width (${tw.toFixed(1)} rem)`);
    await ev(`(() => { lcwSet(${L}, 'due', null); lcwSet(${L}, 'f:${FA}', null); return 1; })()`); await sleep(200);

    // ================= #1217 move a column by dragging its title; a plain click still sorts
    const hn = await mid(`.lchead .lc[data-k="f:${FN}"] .lcs`), hdue = await mid(`.lchead .lc[data-k="due"]`);
    await drag(hn.x, hn.y, (hdue.l + 4) - hn.x, 0, 'mouse'); await sleep(900);
    let cols = (await lst()).columns;
    check(cols[0] === `f:${FN}` && cols.length === COLS.length, '#1217: the column moved in front (saved for the list) ' + JSON.stringify(cols));
    check(await ev(`(document.querySelector('.lchead .lc[data-k]')?.dataset.k) === 'f:${FN}'`), '#1217: the titles show the new order');
    check(await ev(`document.querySelector('.lchead .lc[data-k="f:${FN}"]').getAttribute('aria-sort') === null`), '#1217: the drag did not sort');
    await ev(`(() => { histStep('undo'); return 1; })()`); await sleep(900);
    cols = (await lst()).columns;
    check(JSON.stringify(cols) === JSON.stringify(COLS), '#1217: Undo brings the order back ' + JSON.stringify(cols));
    const hd2 = await mid(`.lchead .lc[data-k="due"] .lcs`);
    await clickAt(hd2.x, hd2.y); await sleep(300);
    check(await ev(`document.querySelector('.lchead .lc[data-k="due"]').getAttribute('aria-sort') !== null`), '#1217: a click without moving sorts');
    await ev(`(() => { sortSet(''); return 1; })()`); await sleep(200);

    // ================= #1327 edit cells
    check(await ev(`getComputedStyle(document.querySelector('${cellSel(T1, FN)}'), '::after').content`) === '"–"', '#1327: an empty field cell shows a dash');
    check(await ev(`(() => { const c = document.querySelector('${cellSel(T1, FA)}'); return c.tabIndex === 0 && /^Amount: /.test(c.getAttribute('aria-label')); })()`), '#1327: cells are reachable by keyboard with a label "Field: value"');
    let p = await mid(cellSel(T1, FA));
    await clickAt(p.x, p.y); await sleep(200);
    check(await ev(`!!document.querySelector('${cellSel(T1, FA)} .tcin') && document.activeElement.classList.contains('tcin') && document.querySelector('${cellSel(T1, FA)} .tcu')?.textContent === 'EUR'`), '#1327: a number cell opens a field, the unit stays visible');
    check(!(await ev(`!!document.querySelector('#detail.open, body.detail-open') && S.sel === ${T1}`)), '#1327: the click did not open the task');
    await type('42.5'); await keys(ENTER); await sleep(900);
    check((await task(T1)).fields[String(FA)] === '42.5', '#1327: Enter saves the number');
    check(await ev(`document.querySelector('${cellSel(T1, FA)}').textContent.includes('42.5')`), '#1327: the cell shows the new value');
    await shot('p2391t-number.png');
    // Esc cancels
    p = await mid(cellSel(T1, FN)); await clickAt(p.x, p.y); await sleep(200);
    await type('scratch'); await keys(ESC); await sleep(600);
    check((await task(T1)).fields[String(FN)] === undefined && !(await ev(`!!document.querySelector('.tcin')`)), '#1327: Esc cancels');
    // Tab: the next editable cell of the row
    p = await mid(cellSel(T1, FA)); await clickAt(p.x, p.y); await sleep(200);
    await keys(TAB); await sleep(800);
    check(await ev(`document.activeElement === document.querySelector('${cellSel(T1, FS.id)}')`), '#1327: Tab goes to the next cell (the choice)');
    // choice: a menu with the colours
    p = await mid(cellSel(T1, FS.id)); await clickAt(p.x, p.y); await sleep(300);
    const mi = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim() + (b.querySelector('.mswc') ? '*' : ''))`);
    check(mi.includes('Open*') && mi.includes('Paid*'), '#1327: the choice opens a menu with the option colours ' + JSON.stringify(mi));
    await shot('p2391t-select.png');
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Paid/.test(b.textContent)).click(); return 1; })()`); await sleep(900);
    check((await task(T1)).fields[String(FS.id)] === PAID, '#1327: picking an option saves it');
    // checkbox toggles
    p = await mid(cellSel(T1, FC)); await clickAt(p.x, p.y); await sleep(900);
    check((await task(T1)).fields[String(FC)] === '1', '#1327: a checkbox cell toggles on');
    p = await mid(cellSel(T1, FC)); await clickAt(p.x, p.y); await sleep(900);
    check((await task(T1)).fields[String(FC)] === undefined, '#1327: and off again');
    // sorting an empty column: a hint
    const he = await mid(`.lchead .lc[data-k="f:${FE}"] .lcs`); await clickAt(he.x, he.y); await sleep(300);
    const tt = await ev(`document.querySelector('#toast')?.textContent || ''`);
    check(/No values in this column yet/.test(tt), '#1327: sorting an empty column says so ' + JSON.stringify([he, tt]));
    await ev(`(() => { sortSet(''); return 1; })()`); await sleep(200);
    // the arrow in the column title opens the column menu
    check(await ev(`!!document.querySelector('.lchead .lc[data-k="due"] .lcmb[aria-haspopup="menu"]')`), '#1327: an arrow button in the column title');
    await ev(`(() => { document.querySelector('.lchead .lc[data-k="due"] .lcmb').click(); return 1; })()`); await sleep(300);
    const cm = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim())`);
    check(cm.includes('Hide column') && cm.some(x => /Shown fields/.test(x)), '#1327: the arrow opens the column menu ' + JSON.stringify(cm));
    await ev(`(() => { closePop(); return 1; })()`);

    // ================= #1327 "Shown fields…": add a field (shown at once), rename / delete offered
    await ev(`(() => { colModal(${L}); return 1; })()`); await sleep(300);
    check(await ev(`document.querySelectorAll('.modal.colmd [data-colfe]').length === 5 && document.querySelectorAll('.modal.colmd [data-colfd]').length === 5`), '#1327: rename and delete for every field in the dialog');
    await ev(`(() => { document.querySelector('.modal.colmd [data-colact="addfield"]').click(); return 1; })()`); await sleep(300);
    check(await ev(`!!document.querySelector('#fd-name')`), '#1327: "Add custom field" opens the field form');
    await ev(`(() => { document.querySelector('#fd-name').value = 'Invoice no'; document.querySelector('.modal [data-m="save"]').click(); return 1; })()`); await sleep(1200);
    let lf = (await call(CA, 'GET', '/api/state')).fields.find(f => f.list_id === L && f.name === 'Invoice no');
    check(lf && (await lst()).columns.includes('f:' + lf.id), '#1327: the new field is a column at once');
    check(await ev(`!!document.querySelector('.modal.colmd .colr[data-k="f:${lf && lf.id}"] input:checked')`), '#1327: and ticked in the dialog');
    await ev(`(() => { document.querySelector('.modal.colmd [data-colfd="${lf && lf.id}"]').click(); return 1; })()`); await sleep(300);
    check(await ev(`/Delete the field/.test(document.querySelector('.modal:last-of-type')?.textContent || document.body.textContent)`), '#1327: delete asks first');
    await ev(`(() => { const b = [...document.querySelectorAll('.modal button')].find(x => x.textContent.trim() === 'Delete'); b && b.click(); return 1; })()`); await sleep(1200);
    check(!(await call(CA, 'GET', '/api/state')).fields.some(f => f.name === 'Invoice no'), '#1327: the field is deleted');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(x => x.remove()); return 1; })()`);
    // module off: adding a field in the dialog switches it on
    await call(CA, 'PATCH', '/api/settings', {features: 'comments,collab'});
    await ev(`load().then(() => { render(); return 1; })`); await sleep(300);
    check(!(await ev(`fieldsOn()`)) && !(await ev(`!!document.querySelector('#view .lc[data-fe]')`)), '#1327: module off: no field cells');
    await ev(`(() => { colModal(${L}); return 1; })()`); await sleep(300);
    await ev(`(() => { document.querySelector('.modal.colmd [data-colact="addfield"]').click(); return 1; })()`); await sleep(300);
    await ev(`(() => { document.querySelector('#fd-name').value = 'Ref'; document.querySelector('.modal [data-m="save"]').click(); return 1; })()`); await sleep(1500);
    check(await ev(`fieldsOn()`) && /Custom fields are switched on/.test(await ev(`document.querySelector('#toast')?.textContent || ''`)), '#1327: adding a field switched the module on, with a hint');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(x => x.remove()); return 1; })()`);

    // ================= #1217: a list without columns has no lines; #1327: a viewer gets no editable cells
    await nav(B + '#l/' + PLAIN); await ready(`!!document.querySelector('#view .trow')`); await sleep(300);
    check(await ev(`!document.querySelector('#view .lcols') && !document.querySelector('#view .lchead')`), '#1217: a list without columns: no column lines');
    await signIn('bob');
    // a new page load: a hash change alone keeps alice's loaded state in the page
    await nav(B + 'static/icon.svg'); await nav(B + '#l/' + L); await ready(`!!document.querySelector('#tc-${T1}')`); await sleep(400);
    check(await ev(`!document.querySelector('#view .lc[data-fe]') && !!document.querySelector('${cellSel(T1, FA)}')`), '#1327: a viewer sees the cells but cannot edit them');
    p = await mid(cellSel(T1, FA)); await clickAt(p.x, p.y); await sleep(300);
    check(!(await ev(`!!document.querySelector('.tcin')`)), '#1327: a viewer\'s click opens no field');
    check(!(await ev(`!!document.querySelector('.lchead .lcs')`)) || !(await ev(`canManage(listById(${L}))`)), '#1217: a viewer cannot move columns (no manage right)');
  }, false);

  console.log(`p2391_t_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
