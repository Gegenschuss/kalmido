// 2.43.0 UI tests, part A, own container (start.sh), Firefox on a desktop (1920 x 1000, mouse). Invented names and amounts.
// - #1331 a list like a spreadsheet: a click / Esc leaves an active cell with an accent frame, arrow keys / Tab / Shift+Tab move
//   it (the title is the first column), typing overwrites, Enter saves and goes one row down, Enter in the last row opens a new
//   row (a title field) that adds a task; Shift+arrows select a range: typing a value or Delete changes all of it (one undo),
//   Ctrl+D fills down, copy gives TSV + HTML, pasting a 3 x 3 block shows a preview with the wrong cells marked, adds the extra
//   row as a new task and is undone in one step; a due date cell opens the calendar
// - #1328 formula column (read-only, computed), the sum row under number columns (switch to average, saved for the list), a key
//   figure tile on the project page, the formula field in the field dialog
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2430_a_ui', check, shots: 'P2430A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2430_A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const t = await r.text(); try { return JSON.parse(t); } catch { return t; } };
const FEAT = 'comments,collab,fields';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Claims', kind: 'project'})).id;
  const FA = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Amount', type: 'number', options: {unit: 'EUR'}})).id;
  const FS = await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'State', type: 'select', options: {options: [{name: 'open'}, {name: 'rejected'}]}});
  const FN = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Note', type: 'text'})).id;
  const FO = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Double', type: 'formula', formula: '{Amount} * 2', options: {unit: 'EUR'}})).id;
  check(FA && FS.id && FN && FO, 'setup: fields incl. a formula');
  const OPEN = FS.options.options[0].id, REJ = FS.options.options[1].id;
  const COLS = [`f:${FA}`, `f:${FS.id}`, `f:${FN}`, `f:${FO}`, 'due'];
  await call(CA, 'PATCH', `/api/lists/${L}`, {columns: COLS, sort_mode: 'title'});
  const mk = async (title, amount) => (await call(CA, 'POST', '/api/tasks', {title, list_id: L, fields: amount ? {[FA]: amount} : {}})).id;
  const T1 = await mk('A first', '10'), T2 = await mk('B second', '20'), T3 = await mk('C third', null);
  const task = async id => (await call(CA, 'GET', '/api/state')).tasks.find(t => t.id === id);
  const tasksOf = async () => (await call(CA, 'GET', '/api/state')).tasks.filter(t => t.list_id === L && !t.deleted_at);
  const settle = async (fn, n = 30) => { let ts; for (let i = 0; i < n; i++) { ts = await tasksOf(); if (fn(ts)) return ts; await sleep(250); } return ts; };  // the server state once it fits

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const act = actions => cmd('input.performActions', {context: ctx, actions}).then(() => cmd('input.releaseActions', {context: ctx}));
    const clickAt = (x, y, mods = []) => act([...(mods.length ? [{type: 'key', id: 'km', actions: mods.map(m => ({type: 'keyDown', value: m}))}] : []),
      {type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]);
    const keys = (...ks) => act([{type: 'key', id: 'k', actions: ks.flatMap(k => [{type: 'keyDown', value: k}, {type: 'keyUp', value: k}])}]);
    const chord = (mod, k) => act([{type: 'key', id: 'k', actions: [{type: 'keyDown', value: mod}, {type: 'keyDown', value: k}, {type: 'keyUp', value: k}, {type: 'keyUp', value: mod}]}]);
    const type = s => keys(...[...s]);
    const ENTER = '', ESC = '', TAB = '', SHIFT = '', CTRL = '', DOWN = '', UP = '', LEFT = '', RIGHT = '', DEL = '';
    const mid = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2}; })()`);
    const cell = (tid, k) => `#tc-${tid} .lc[data-k="${k}"]`;
    const act0 = () => ev(`(() => { const a = document.activeElement; const c = sgCellOf(a); return c ? c.tid + ':' + c.k : (a && a.className) || ''; })()`);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1920, height: 1000}});
    await nav(B + '#l/' + L);
    check(await ready(`typeof sgCellOf === 'function' && !!document.querySelector('#tc-${T3}')`), 'Firefox: the list with columns');
    await sleep(400);
    const A = `f:${FA}`, S_ = `f:${FS.id}`, N_ = `f:${FN}`, O = `f:${FO}`;

    // ================= #1328 formula column + sum row
    check(await ev(`document.querySelector('${cell(T1, O)}').textContent.includes('20') && !document.querySelector('${cell(T1, O)}').dataset.fe`), '#1328: the formula cell shows the computed value, not editable');
    check(await ev(`/30/.test(document.querySelector('.fxsum [data-fxsum="${A}"]')?.textContent || '')`), '#1328: the sum row adds the amounts ' + await ev(`document.querySelector('.fxsum')?.textContent`));
    check(await ev(`/60/.test(document.querySelector('.fxsum [data-fxsum="${O}"]')?.textContent || '')`), '#1328: … and the formula column');
    await ev(`(() => { document.querySelector('.fxsum [data-fxsum="${A}"]').click(); return 1; })()`); await sleep(300);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Average/.test(b.textContent)).click(); return 1; })()`); await sleep(900);
    check((await call(CA, 'GET', '/api/state')).lists.find(l => l.id === L).col_sums?.[A] === 'avg', '#1328: the choice is saved for the list');
    check(!(await ev(`(() => { povSet(listById(${L}), true); renderView(); const x = !!document.querySelector('#pov-kpis'); povSet(listById(${L}), false); renderView(); return x; })()`)), '#1328: no key figure block before one is set up');
    await ev(`(() => { document.querySelector('.fxsum [data-fxsum="${A}"]').click(); return 1; })()`); await sleep(300);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Key figure on the project page/.test(b.textContent)).click(); return 1; })()`); await sleep(400);
    check(await ev(`document.querySelector('.modal.fxkmd [data-key="title"]')?.value === 'Amount' && document.querySelector('.modal.fxkmd [data-key="agg"]')?.value === 'avg'`), '#1328: the sum row offers a key figure for the project page (prefilled)');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(x => x.remove()); return 1; })()`);
    check(await ev(`/Average/.test(document.querySelector('.fxsum [data-fxsum="${A}"]').textContent) && /15/.test(document.querySelector('.fxsum [data-fxsum="${A}"]').textContent)`), '#1328: the sum row shows the average');
    await shot('p2430a-sumrow.png');

    // ================= #1331 active cell, arrow keys, Tab, typing
    let p = await mid(cell(T1, A)); await clickAt(p.x, p.y); await sleep(250);
    check(await ev(`!!document.querySelector('${cell(T1, A)} .tcin')`), '#1331: a click on a field cell still edits it');
    await keys(ESC); await sleep(500);
    check(await act0() === `${T1}:${A}` && await ev(`document.querySelector('${cell(T1, A)}').classList.contains('sgact')`), '#1331: Esc leaves the active cell with its frame ' + await act0());
    await keys(DOWN); await sleep(150);
    check(await act0() === `${T2}:${A}`, '#1331: ↓ goes to the cell below ' + await act0());
    await keys(RIGHT); await sleep(150);
    check(await act0() === `${T2}:${S_}`, '#1331: → the next column ' + await act0());
    await keys(LEFT, LEFT); await sleep(150);
    check(await act0() === `${T2}:title`, '#1331: ← twice reaches the title ' + await act0());
    await keys(RIGHT); await sleep(100);
    await keys(TAB); await sleep(150);
    check(await act0() === `${T2}:${S_}`, '#1331: Tab = next cell ' + await act0());
    await act([{type: 'key', id: 'k', actions: [{type: 'keyDown', value: SHIFT}, {type: 'keyDown', value: TAB}, {type: 'keyUp', value: TAB}, {type: 'keyUp', value: SHIFT}]}]); await sleep(150);
    check(await act0() === `${T2}:${A}`, '#1331: Shift+Tab = the cell before ' + await act0());
    await type('75'); await sleep(150);
    check(await ev(`document.querySelector('${cell(T2, A)} .tcin')?.value`) === '75', '#1331: typing overwrites the value');
    await keys(ENTER); await sleep(1300);
    check((await task(T2)).fields[String(FA)] === '75', '#1331: Enter saves');
    check(await act0() === `${T3}:${A}`, '#1331: and goes one row down ' + await act0());
    // Enter in the last row: a new row with a title field
    await type('5'); await keys(ENTER); await sleep(1300);
    check((await task(T3)).fields[String(FA)] === '5' && await ev(`document.activeElement?.classList.contains('sgin')`), '#1331: Enter in the last row opens a new row');
    await type('D fresh'); await keys(ENTER); await sleep(1300);
    const fresh = (await tasksOf()).find(t => t.title === 'D fresh');
    check(fresh && await ev(`document.activeElement?.classList.contains('sgin')`), '#1331: Enter adds the task, the next new row is open');
    await keys(ESC); await sleep(400);
    check(!(await ev(`!!document.querySelector('.sgnew')`)), '#1331: Esc closes the new row');
    await shot('p2430a-active.png');

    // ================= #1331 range: type a value for all, Delete, one undo each
    p = await mid(cell(T1, N_)); await clickAt(p.x, p.y); await sleep(250); await keys(ESC); await sleep(400);
    await act([{type: 'key', id: 'k', actions: [{type: 'keyDown', value: SHIFT}, {type: 'keyDown', value: DOWN}, {type: 'keyUp', value: DOWN}, {type: 'keyDown', value: DOWN}, {type: 'keyUp', value: DOWN}, {type: 'keyUp', value: SHIFT}]}]); await sleep(200);
    check(await ev(`document.querySelectorAll('#view .lc.sgsel').length`) === 3, '#1331: Shift+↓ selects a range of 3 cells');
    await type('xyz'); await keys(ENTER); await sleep(1500);
    let ts = await tasksOf();
    check([T1, T2, T3].every(id => ts.find(t => t.id === id).fields[String(FN)] === 'xyz'), '#1331: a typed value changes the whole range');
    await ready(`!HIST.busy`, 20); await ev(`histStep('undo').then(() => 1)`);
    ts = await settle(x => [T1, T2, T3].every(id => x.find(t => t.id === id).fields[String(FN)] === undefined));
    check([T1, T2, T3].every(id => ts.find(t => t.id === id).fields[String(FN)] === undefined), '#1331: one undo brings the range back ' + JSON.stringify([T1, T2, T3].map(id => ts.find(t => t.id === id).fields[String(FN)])) + ' ' + await ev(`JSON.stringify(HIST.undo.slice(-3).map(e => e.label))`));
    // Delete empties the amounts of two rows
    p = await mid(cell(T1, A)); await clickAt(p.x, p.y); await sleep(250); await keys(ESC); await sleep(400);
    await act([{type: 'key', id: 'k', actions: [{type: 'keyDown', value: SHIFT}, {type: 'keyDown', value: DOWN}, {type: 'keyUp', value: DOWN}, {type: 'keyUp', value: SHIFT}]}]); await sleep(200);
    await keys(DEL);
    ts = await settle(x => x.find(t => t.id === T1).fields[String(FA)] === undefined);
    check(ts.find(t => t.id === T1).fields[String(FA)] === undefined && ts.find(t => t.id === T2).fields[String(FA)] === undefined, '#1331: Delete empties the range');
    await ready(`!HIST.busy`, 20); await ev(`histStep('undo').then(() => 1)`);
    ts = await settle(x => x.find(t => t.id === T1).fields[String(FA)] === '10');
    check(ts.find(t => t.id === T1).fields[String(FA)] === '10' && ts.find(t => t.id === T2).fields[String(FA)] === '75', '#1331: undo brings both back');

    // ================= #1331 fill down (Ctrl+D) + copy as a table
    await ev(`(() => { sgFocus({tid: ${T1}, k: '${A}'}); return 1; })()`); await sleep(200);
    await act([{type: 'key', id: 'k', actions: [{type: 'keyDown', value: SHIFT}, {type: 'keyDown', value: DOWN}, {type: 'keyUp', value: DOWN}, {type: 'keyDown', value: DOWN}, {type: 'keyUp', value: DOWN}, {type: 'keyUp', value: SHIFT}]}]); await sleep(200);
    const cp = await ev(`(() => { const d = sgCopyData(); return {t: d?.text, h: d?.html}; })()`);  // what the copy event puts on the clipboard
    check(cp.t === '10\n75\n5' && /<table>/.test(cp.h), '#1331: copy gives the range as TSV + HTML ' + JSON.stringify(cp));
    await chord(CTRL, 'd');
    ts = await settle(x => x.find(t => t.id === T3).fields[String(FA)] === '10');
    check(ts.find(t => t.id === T2).fields[String(FA)] === '10' && ts.find(t => t.id === T3).fields[String(FA)] === '10', '#1331: Ctrl+D fills the first value down');
    await ready(`!HIST.busy`, 20); await ev(`histStep('undo').then(() => 1)`);
    ts = await settle(x => x.find(t => t.id === T2).fields[String(FA)] === '75');
    check(ts.find(t => t.id === T2).fields[String(FA)] === '75', '#1331: undo of the fill');
    await ready(`!HIST.busy`, 20);

    // ================= #1331 paste a 3 x 3 block with a preview (one wrong value, one new row)
    const nBefore = (await tasksOf()).length;
    await ev(`(() => { sgFocus({tid: ${T2}, k: 'title'}); return 1; })()`); await sleep(200);
    // rows from B second down: B second, C third, D fresh -> 4 rows = one new task
    await ev(`(() => { sgPaste('B renamed\\t1.5\\topen\\nC renamed\\t2\\tbogus\\nD renamed\\t3\\trejected\\nE new\\t4\\topen\\n'); return 1; })()`); await sleep(400);  // what the paste event hands over
    check(await ev(`!!document.querySelector('.modal.sgpmd')`), '#1331: pasting opens a preview');
    const pv = await ev(`(() => { const m = document.querySelector('.modal.sgpmd'); return {maps: [...m.querySelectorAll('[data-sgmap]')].map(s => s.value), bad: m.querySelectorAll('td.sgbad').length, n: m.querySelector('.sgpn').textContent, rows: m.querySelectorAll('tbody tr').length}; })()`);
    check(JSON.stringify(pv.maps) === JSON.stringify(['title', A, S_]) && pv.bad === 1 && pv.rows === 4 && /1 new task/.test(pv.n) && /1 invalid cell/.test(pv.n), '#1331: columns mapped from the active cell, the wrong value marked ' + JSON.stringify(pv));
    await shot('p2430a-paste.png');
    await ev(`(() => { document.querySelector('.modal.sgpmd [data-m="ok"]').click(); return 1; })()`); await sleep(3000);
    ts = await tasksOf();
    const tB = ts.find(t => t.id === T2), tC = ts.find(t => t.id === T3), tE = ts.find(t => t.title === 'E new');
    check(tB.title === 'B renamed' && tB.fields[String(FA)] === '1.5' && tB.fields[String(FS.id)] === OPEN, '#1331: pasted into the row (German / English number) ' + JSON.stringify(tB.fields));
    check(tC.title === 'C renamed' && tC.fields[String(FS.id)] === undefined && tC.fields[String(FA)] === '2', '#1331: the wrong value is skipped, the rest of the row taken');
    check(tE && tE.fields[String(FA)] === '4' && ts.length === nBefore + 1, '#1331: the extra row became a new task');
    check(ts.find(t => t.title === 'D renamed')?.fields[String(FS.id)] === REJ, '#1331: a choice by its name');
    await ready(`!HIST.busy`, 20); await ev(`histStep('undo').then(() => 1)`);
    ts = await settle(x => !x.some(t => t.title === 'E new') && x.find(t => t.id === T2).title === 'B second');
    check(ts.find(t => t.id === T2).title === 'B second' && ts.find(t => t.id === T3).title === 'C third' && !ts.some(t => t.title === 'E new'), '#1331: one undo takes the whole paste back ' + ts.map(t => t.title).join(', '));

    // ================= #1331 filter by a column value (the arrow in the column title)
    await call(CA, 'PATCH', `/api/tasks/${T1}`, {fields: {[FS.id]: REJ}});
    await ev(`load().then(() => { render(); return 1; })`); await sleep(300);
    await ready(`taskById(${T1})?.fields?.['${FS.id}'] === '${REJ}'`, 12);
    await ev(`(() => { document.querySelector('.lchead .lc[data-k="${S_}"] .lcmb').click(); return 1; })()`); await sleep(300);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /Filter by this column/.test(b.textContent)).click(); return 1; })()`); await sleep(400);
    await ready(`[...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /rejected/.test(b.textContent))`, 12);
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /rejected/.test(b.textContent)).click(); return 1; })()`);
    check(await ready(`document.querySelectorAll('#view .trow[data-id]').length === 1 && !!document.querySelector('#tc-${T1}') && !!document.querySelector('.sgfnote')`, 12), '#1331: the column filter shows only the matching task, with a note ' + await ev(`JSON.stringify(SG.cf) + ' ' + document.querySelectorAll('#view .trow[data-id]').length + ' ' + JSON.stringify(listById(${L}) && fieldById(${FS.id}) && taskById(${T1}).fields)`));
    check(await ev(`/1 task/.test(document.querySelector('.fxsum')?.textContent || '')`), '#1331: the sum row counts the shown tasks');
    await ev(`(() => { document.querySelector('[data-sgfoff]').click(); return 1; })()`); await sleep(400);
    check(await ev(`document.querySelectorAll('#view .trow[data-id]').length`) >= 4, '#1331: "Show all" brings the rest back');

    // ================= #1331 due date right in the cell
    p = await mid(cell(T1, 'due')); await clickAt(p.x, p.y); await sleep(400);
    check(await ev(`!!document.querySelector('#dpop')`), '#1331: a click on the due cell opens the calendar ' + JSON.stringify(p) + ' ' + await ev(`(() => { const c = document.querySelector('${cell(T1, 'due')}'); const x = document.elementFromPoint(${Math.round(p?.x || 0)}, ${Math.round(p?.y || 0)}); return [c && c.getClientRects().length, x && x.className, document.activeElement?.className, JSON.stringify(SG.f)].join(' | '); })()`));
    await keys(ESC); await sleep(300);

    // ================= #1328 the formula field in the dialog + a key figure tile on the project page
    await ev(`(() => { fieldModal(${L}, null, () => {}); return 1; })()`); await sleep(300);
    await ev(`(() => { const s = document.querySelector('#fd-type'); s.value = 'formula'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`); await sleep(200);
    check(await ev(`!!document.querySelector('#fd-fx') && [...document.querySelectorAll('[data-fxins]')].some(b => b.dataset.fxins === 'Amount')`), '#1328: the dialog offers the formula with the number fields to insert');
    await ev(`(() => { document.querySelector('#fd-name').value = 'Broken'; document.querySelector('#fd-fx').value = '{Amount} * (2'; document.querySelector('.modal [data-m="save"]').click(); return 1; })()`); await sleep(800);
    check(/character 14/.test(await ev(`document.querySelector('#toast')?.textContent || ''`)) && await ev(`!!document.querySelector('#fd-fx')`), '#1328: a wrong formula is refused with the position, the dialog stays');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(x => x.remove()); return 1; })()`);
    await call(CA, 'PATCH', `/api/lists/${L}`, {kpis: [{title: 'Total amount', agg: 'sum', field: FA}, {title: 'Rejected', agg: 'count', cond_field: FS.id, cond_value: REJ}]});
    await ev(`load().then(() => { povSet(listById(${L}), true); renderView(); return 1; })`);
    check(await ready(`document.querySelectorAll('#pov-kpis .fxk').length === 2 && !/…/.test(document.querySelector('#pov-kpis').textContent)`), '#1328: the key figures show on top of the project page');
    check(await ev(`/Total amount\\s*90/.test(document.querySelector('#pov-kpis').textContent.replace(/\\s+/g, ' '))`), '#1328: the sum tile ' + await ev(`document.querySelector('#pov-kpis')?.textContent`));
    check(await ev(`document.querySelector('.lyb[data-lyk]')?.dataset.lyk === 'kpis'`), '#1328: the block comes first');
    await shot('p2430a-kpis.png');
  }, false);

  console.log(`p2430_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
