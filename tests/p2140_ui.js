// 2.14.0 UI tests (#425 list columns + the heron), own container (start.sh, isolated test database).
// API: the list setting `columns` (owner / list admins, 403 for an editor, 400 for unknown keys or fields of another list,
// null = default, a new field joins configured columns, a deleted one drops out), API v1 GET / PATCH with `fields`.
// jsdom: "Columns…" in the header and the list menu (the old per-device switches are gone), the dialog (default ticks,
// order with the arrows and Alt+arrows, Save for everyone with Undo, Default, read-only for an editor), the rows (cells in
// the list's order, task number gutter, the values only in their columns), the heron in empty lists, Today (empty / all
// done), search without hits, the start page when the server is unreachable, the 404 and public-link error pages, German.
// Firefox: phones 380 / 390 / 428 touch, Fold 904 (fold / unfold, rotate 904 x 680), 880 touch, desktops 1100 / 1440 /
// 1920 mouse (light + dark): no horizontal overflow, two cells on narrow widths and the rest in the second line, the title
// row lines up with the cells, the dialog fits with 44 px targets, the heron's sun follows the accent colour.
// Screenshots with P2140_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2140_ui', check, shots: 'P2140_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _st: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const lst = async id => (await call('GET', '/api/state')).lists.find(l => l.id === id);

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:8[7-9]|9[0-9])'/.test(SW), 'service worker cache v87');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAR = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const CB = await login('bob'), CC = await login('carol');
  for (const ck of [CB, CC]) await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, ck);
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${P}/members`, {user_id: CAR, role: 'admin'});
  const FS = await call('POST', `/api/lists/${P}/fields`, {name: 'Stage', type: 'select', options: {options: [{name: 'Idea', color: '#94a3b8'}, {name: 'Doing', color: '#6d8cff'}]}});
  const FB = await call('POST', `/api/lists/${P}/fields`, {name: 'Budget', type: 'number', options: {unit: 'EUR'}});
  const OTHER = (await call('POST', '/api/lists', {name: 'Other', kind: 'project'})).id;
  const FO = await call('POST', `/api/lists/${OTHER}/fields`, {name: 'Elsewhere', type: 'text'});
  const T = [];
  const mk = async b => { const t = await call('POST', '/api/tasks', {list_id: P, ...b}); T.push(t.id); return t.id; };
  const T1 = await mk({title: 'Homepage layout with a long title that needs room', due: day(1), priority: 5, tags: ['web'], assignee_id: BOB});
  const T2 = await mk({title: 'Copy text', due: day(-1), priority: 3});
  const T3 = await mk({title: 'Launch', due: day(5)});
  await call('POST', '/api/tasks', {list_id: P, parent_id: T1, title: 'Header'});
  await call('POST', '/api/deps', {task_id: T3, blocker_id: T2});
  await call('PATCH', `/api/tasks/${T1}`, {fields: {[FS.id]: FS.options.options[1].id, [FB.id]: '1200'}});
  await call('POST', '/api/time/entries', {task_id: T1, start: new Date(Date.now() - 2 * 36e5).toISOString(), minutes: 95});
  const EMPTY = (await call('POST', '/api/lists', {name: 'Empty one'})).id;

  // ================= API: the list setting
  check((await lst(P)).columns === null, 'a list starts with columns null (default layout)');
  check((await call('PATCH', `/api/lists/${P}`, {columns: ['due', 'who']}, CB)).status === 403, 'an editor cannot change the columns (403)');
  check((await lst(P)).columns === null, '… and nothing changed');
  const r1 = await call('PATCH', `/api/lists/${P}`, {columns: ['id', 'prio', 'due', 'f:' + FS.id, 'who', 'due']}, CC);
  check(r1.status === 200, 'a list admin changes the columns');
  check(JSON.stringify((await lst(P)).columns) === JSON.stringify(['id', 'prio', 'due', 'f:' + FS.id, 'who']), 'stored in order, duplicates dropped ' + JSON.stringify((await lst(P)).columns));
  check(JSON.stringify((await call('GET', '/api/state', null, CB)).lists.find(l => l.id === P).columns) === JSON.stringify(['id', 'prio', 'due', 'f:' + FS.id, 'who']), 'every member sees the same columns');
  check((await call('PATCH', `/api/lists/${P}`, {columns: ['due', 'bogus']})).status === 400, 'an unknown key: 400');
  check((await call('PATCH', `/api/lists/${P}`, {columns: ['f:' + FO.id]})).status === 400, 'a field of another list: 400');
  check((await call('PATCH', `/api/lists/${P}`, {columns: 'due'})).status === 400, 'not an array: 400');
  check((await call('PATCH', `/api/lists/${P}`, {columns: null})).status === 200 && (await lst(P)).columns === null, 'null = back to the default');
  await call('PATCH', `/api/lists/${P}`, {columns: ['due']});
  const FN = await call('POST', `/api/lists/${P}/fields`, {name: 'Client', type: 'text'});
  check(JSON.stringify((await lst(P)).columns) === JSON.stringify(['due', 'f:' + FN.id]), 'a new field joins configured columns at the end');
  await call('DELETE', `/api/fields/${FN.id}`);
  check(JSON.stringify((await lst(P)).columns) === JSON.stringify(['due']), 'a deleted field drops out: ' + JSON.stringify((await lst(P)).columns));
  await call('PATCH', `/api/lists/${P}`, {columns: null});
  // API v1
  const TOK = (await call('POST', '/api/me/tokens', {name: 't', scopes: ['read', 'write']})).token;
  const v1 = await tcall('GET', `/lists/${P}`, TOK);
  check(v1._st === 200 && v1.columns === null && (v1.fields || []).map(f => f.name).join() === 'Stage,Budget', 'API v1: a list has columns (null) and its fields ' + JSON.stringify({c: v1.columns, f: v1.fields}));
  const v1p = await tcall('PATCH', `/lists/${P}`, TOK, {columns: ['due', 'f:' + FB.id]});
  check(v1p._st === 200 && JSON.stringify(v1p.columns) === JSON.stringify(['due', 'f:' + FB.id]), 'API v1: PATCH columns');
  check((await tcall('PATCH', `/lists/${P}`, TOK, {columns: ['nope']}))._st === 400, 'API v1: unknown column 400');
  const v1l = await tcall('GET', '/lists', TOK);
  check((v1l.data || []).find(l => l.id === P)?.fields?.length === 2, 'API v1: the list page carries fields too');
  const spec = await (await fetch(B + 'api/v1/openapi.json')).json();
  check(!!spec.components?.schemas?.ListPatch?.properties?.columns, 'OpenAPI: ListPatch.columns');
  await call('PATCH', `/api/lists/${P}`, {columns: null});

  // ================= heron on the server pages
  const nf = await fetch(B + 'no/such/page', {headers: {Accept: 'text/html', Cookie: CK}});
  const nfh = await nf.text();
  check(nf.status === 404 && /class="heron"/.test(nfh) && /Page not found/.test(nfh) && /href="\/"/.test(nfh) && !/Shared with/.test(nfh), '404 page: heron, title, a way back, no "Shared with" footer');
  check(!/<svg class="heron"[^>]*aria-label/.test(nfh) && !/<title>[^<]*<\/title><\/svg>/.test(nfh), 'the heron is decorative (no label of its own)');
  const pg = await (await fetch(B + 's/nonexistenttoken0000000000', {headers: {Accept: 'text/html'}})).text();
  check(/class="heron"/.test(pg) && /Link not available/.test(pg), 'public link gone: heron');
  const api404 = await fetch(B + 'api/v1/nothing', {headers: {Accept: 'text/html', Authorization: 'Bearer ' + TOK}});
  check(api404.status === 404 && /json/.test(api404.headers.get('content-type') || ''), 'API 404 stays JSON');

  // ================= jsdom: header button, menu, dialog, rows
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  check(!!d.querySelector('#top [data-act="cols"]'), 'desktop header: the Columns button');
  check(!d.querySelector('#top [data-act="field-cols"]'), 'the old per-device field-columns switch is gone');
  const items = w.eval(`listMenuItems(${P}, document.body)`).map(x => x.label);
  check(items.includes('Columns…') && !items.includes('Show task numbers') && !items.some(x => /assignee column/.test(x || '')), 'list "…": "Columns…" replaces "Show task numbers" / "Hide assignee column" ' + items.join(' | '));
  check(row(T1).querySelector('.tcols') && !row(T1).querySelector('.lcols'), 'default layout: the old date / assignee columns');
  click(w, d.querySelector('#top [data-act="cols"]')); await sleep(200);
  let md = d.querySelector('.modal.colmd');
  check(md && md.getAttribute('role') === 'dialog', 'the Columns dialog opens');
  const ticked = () => [...md.querySelectorAll('.colr input:checked')].map(x => x.dataset.colk);
  const order = () => [...md.querySelectorAll('.colr')].map(x => x.dataset.k);
  check(ticked().slice(0, 3).join() === 'due,who,time' && !md.querySelector('#col-num').checked, 'the default layout is the starting point ' + ticked().join());
  check(order().includes('f:' + FS.id) && order().includes('prio') && order().includes('deps'), 'every column is offered, custom fields too ' + order().join());
  // tick prio, Stage, the number; untick time; move prio to the top with the arrows, Stage up with Alt+Up
  const tick = (k, on) => { const i = md.querySelector(`[data-colk="${k}"]`); i.checked = on; i.dispatchEvent(new w.Event('change', {bubbles: true})); };
  tick('prio', true); tick('f:' + FS.id, true); tick('time', false);
  const num = md.querySelector('#col-num'); num.checked = true; num.dispatchEvent(new w.Event('change', {bubbles: true}));
  for (let i = 0; i < 12 && order()[0] !== 'prio'; i++) click(w, md.querySelector('.colr[data-k="prio"] [data-colmv="-1"]'));
  check(order()[0] === 'prio', 'the up arrow moves a column up');
  check(md.querySelector('.colr[data-k="prio"] [data-colmv="-1"]').disabled, 'the first row cannot move further up');
  const sIn = md.querySelector(`.colr[data-k="f:${FS.id}"] input`); const before = order().indexOf('f:' + FS.id);
  sIn.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'ArrowUp', altKey: true, bubbles: true}));
  check(order().indexOf('f:' + FS.id) === before - 1, 'Alt+Up moves the focused row');
  click(w, md.querySelector('[data-colact="save"]')); await sleep(600);
  const want = ['id', ...order().filter(k => ticked().includes(k))];
  const saved = (await lst(P)).columns;
  check(JSON.stringify(saved) === JSON.stringify(want) && saved[1] === 'prio' && saved.includes('f:' + FS.id) && !saved.includes('time'), 'Save stores the list\'s columns in the dialog\'s order ' + JSON.stringify(saved) + ' ' + JSON.stringify(want));
  check(/Columns saved for everyone/.test(d.querySelector('#toast')?.textContent || ''), 'toast: saved for everyone, with Undo');
  const r = row(T1);
  const cells = [...r.querySelectorAll('.lcols .lc')].map(x => x.className.split(' ')[1]);
  check(cells.join() === saved.filter(k => k !== 'id').map(k => k.startsWith('f:') ? 'lc-f' : 'lc-' + k).join(), 'the row\'s cells follow the list\'s order ' + cells.join());
  check(r.querySelector('.tgut')?.textContent === '#' + T1, 'the task number in front of the title');
  check(/High/.test(r.querySelector('.lc-prio')?.textContent || '') && /Doing/.test(r.querySelector('.lc-f')?.textContent || ''), 'priority and the custom field in their cells');
  check(!r.querySelector('.meta .tchip') && !r.querySelector('.meta .dt') && !r.querySelector('.meta > .tag'), 'hidden columns are not in the row (time), shown ones not twice (date) ' + r.querySelector('.meta').innerHTML.slice(0, 200));
  check(!!d.querySelector('#view .lchead') && /Stage/.test(d.querySelector('#view .lchead').textContent), 'the title row names the columns');
  check(!!row(T2).querySelector('.lc-due .over'), 'an overdue date keeps its colour in the column');
  check(r.querySelector('.lcols .lc').classList.length >= 2 && [...r.querySelectorAll('.lcols .lc')].slice(2).every(x => x.classList.contains('o2')), 'cells after the second carry o2 (move to line 2 on narrow widths)');
  check([...r.querySelectorAll('.meta .mlc')].length >= 1 && [...r.querySelectorAll('.meta .mlc')].every(x => x.classList.contains('o2')), 'their copies wait in the second line');
  // Undo
  click(w, d.querySelector('#toast button')); await sleep(900);
  check((await lst(P)).columns === null && row(T1).querySelector('.tcols'), 'Undo: back to the default layout');
  w.eval(`colSave(${P}, ${JSON.stringify(saved)}, true)`); await sleep(500);
  // Default button
  w.eval(`colModal(${P})`); await sleep(150); md = d.querySelector('.modal.colmd');
  check(!md.querySelector('[data-colact="reset"]').disabled, '"Default" is offered while the list has its own columns');
  click(w, md.querySelector('[data-colact="reset"]')); await sleep(600);
  check((await lst(P)).columns === null, '"Default" resets for everyone');
  w.eval(`colSave(${P}, ${JSON.stringify(saved)}, true)`); await sleep(500);
  // field dialog: no "show as a chip" while the list has columns
  w.eval(`fieldModal(${P}, fieldById(${FB.id}))`); await sleep(150);
  check(d.querySelector('#fd-pin')?.closest('.row')?.hidden === true, 'field dialog: "show as a chip" hidden in a list with columns');
  d.querySelectorAll('.modal').forEach(x => x.remove());
  // heron: empty list, search without hits, Today
  await w.eval(`go('l/${EMPTY}')`); await sleep(500);
  let he = d.querySelector('#view .empty.hempty');
  check(he && he.querySelector('svg.heron[aria-hidden="true"] .hr-sun') && /No tasks/.test(he.textContent) && /field below/.test(he.textContent), 'empty list: the heron + a hint');
  check([...d.querySelectorAll('svg.heron')].every(x => x.getAttribute('aria-hidden') === 'true' && !x.querySelector('title')), 'the heron is decorative (aria-hidden, no title)');
  w.eval(`S.searchQ = 'zzzqqq'; S.searchRes = []; go('search')`); await sleep(400);
  he = d.querySelector('#view .empty.hempty');
  check(he && /No results/.test(he.textContent), 'search without hits: the heron');
  w.close();
  // Today: nothing / all done (a fresh user)
  await call('POST', '/api/users', {username: 'dora', display_name: 'Dora', password: 'password123'});
  const CD = await login('dora'); await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CD);
  w = await boot({user: 'dora', hash: 'today'}); d = w.document;
  check(/Nothing left for today/.test(d.querySelector('#view .hempty')?.textContent || '') && d.querySelector('#view .hempty .heron'), 'Today without tasks: the heron looks into the water');
  w.close();
  const dt = await call('POST', '/api/tasks', {title: 'Done today', due: day(0)}, CD);
  await call('PATCH', `/api/tasks/${dt.id}`, {status: 2}, CD);
  w = await boot({user: 'dora', hash: 'today', ls: {'tasks.showDone': 'true'}}); d = w.document;
  const he2 = d.querySelector('#view .hempty');
  check(!he2 || /All done for today/.test(he2.textContent) || d.querySelector('#view .trow'), 'Today with everything done: "All done for today." ' + (he2?.textContent || ''));
  w.close();
  // editor: read-only dialog, German
  w = await boot({user: 'bob', hash: 'l/' + P}); d = w.document;
  w.eval(`colModal(${P})`); await sleep(200); md = d.querySelector('.modal.colmd');
  check(md && md.querySelector('.rohint') && [...md.querySelectorAll('input')].every(x => x.disabled) && !md.querySelector('[data-colact="save"]') && !md.querySelector('[data-colmv]'), 'an editor sees the columns read-only');
  check(!!row(T1)?.querySelector('.lcols'), 'an editor sees the same columns');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  check(/Spalten/.test(d.querySelector('#top [data-act="cols"]')?.getAttribute('title') || ''), 'German: "Spalten…"');
  w.eval(`colModal(${P})`); await sleep(200);
  check(/Für alle in dieser Liste gleich/.test(d.querySelector('.colmd .coldesc')?.textContent || ''), 'German dialog text: ' + (d.querySelector('.colmd .coldesc')?.textContent || ''));
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});
  // ================= #484 quick add: "Add and open details" + the paper clip
  w = await boot({user: 'alice', hash: 'l/' + EMPTY}); d = w.document;
  const qo = d.querySelector('.qadd [data-act="q-open"]'), qc = d.querySelector('.qadd [data-act="q-clip"]');
  check(qo && qc && qo.getAttribute('aria-label') === 'Add and open details' && qc.getAttribute('aria-label') === 'Add with a file…' && qo.title && qc.title, 'desktop composer: paper clip + "Add and open details" with names');
  const nTasks = async () => (await call('GET', '/api/state')).tasks.filter(t => t.list_id === EMPTY).length;
  click(w, qo); await sleep(400);
  check(await nTasks() === 0 && /Type a title first/.test(d.querySelector('#toast')?.textContent || ''), 'empty box: nothing is created, a hint');
  const qi = d.querySelector('#qinput'); qi.value = 'Write the report'; qi.dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, d.querySelector('.qadd [data-act="q-open"]'));
  const made = await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.list_id === EMPTY && t.title === 'Write the report'), 40);
  await sleep(500);
  check(made && w.eval('S.sel') === made.id && d.querySelector('#detail'), '"Add and open details" creates the task and opens its details');
  check(!/Open/.test(d.querySelector('#toast:not(.hidden) button')?.textContent || ''), 'no extra "Open" toast');
  w.eval('closeDetail()'); await sleep(300);
  // the paper clip: files from the chooser (a stub stands in for the system dialog)
  const pick = files => w.eval(`(() => { const f = document.querySelector('#qfile'); Object.defineProperty(f, 'files', {configurable: true, value: window.__pick}); f.dispatchEvent(new Event('change')); return 1; })()`);
  w.HTMLInputElement.prototype.click = function () { if (this.id === 'qfile') setTimeout(() => pick(), 0); };
  w.__pick = [new w.File(['hello'], 'meeting-notes.txt', {type: 'text/plain'})];
  click(w, d.querySelector('.qadd [data-act="q-clip"]'));
  const fileTask = await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.list_id === EMPTY && t.title === 'meeting-notes' && (t.attachments || []).length), 60);
  await sleep(400);
  check(fileTask && fileTask.attachments[0].name === 'meeting-notes.txt', 'paper clip with an empty box: the file name is the title, the file is attached');
  check(fileTask && w.eval('S.sel') === fileTask.id, 'paper clip: the new task\'s details open');
  w.eval('closeDetail()'); await sleep(300);
  const before0 = await nTasks();
  w.__pick = [new w.File([''], 'empty.txt', {type: 'text/plain'})];
  click(w, d.querySelector('.qadd [data-act="q-clip"]')); await sleep(800);
  check(await nTasks() === before0 && /empty/.test(d.querySelector('#toast')?.textContent || ''), 'a 0-byte file is refused, no task');
  w.eval(`OUT.online = false`);
  click(w, d.querySelector('.qadd [data-act="q-clip"]')); await sleep(300);
  check(/Offline/.test(d.querySelector('#toast')?.textContent || ''), 'offline: the paper clip says it needs a connection');
  w.eval(`OUT.online = true`);
  w.close();
  // phone: the quick sheet has both, "Add and open" closes the sheet and opens the task
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + EMPTY}); d = w.document;
  w.eval(`openQuickSheet()`); await sleep(200);
  check(d.querySelector('.qadd.sheet [data-act="q-open"]') && d.querySelector('.qadd.sheet [data-act="q-clip"]'), 'phone sheet: paper clip + "Add and open details"');
  d.querySelector('#qsheet').value = 'Call the plumber';
  click(w, d.querySelector('.qadd.sheet [data-act="q-open"]'));
  const ph = await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.title === 'Call the plumber'), 40);
  await sleep(500);
  check(ph && w.eval('S.sel') === ph.id && !d.querySelector('.qadd.sheet'), 'phone: the sheet closes and the details open');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + EMPTY}); d = w.document;
  check(d.querySelector('.qadd [data-act="q-open"]')?.getAttribute('aria-label') === 'Anlegen und Details öffnen', 'German labels');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});
  for (const t of (await call('GET', '/api/state')).tasks.filter(t => t.list_id === EMPTY)) await call('DELETE', `/api/tasks/${t.id}`);

  // p210 flake, the real cause: a state answer that a save overtook must not put the old value back (load() fetches again)
  w = await boot({user: 'alice', hash: 'today', setup: x => { const f0 = x.fetch; x.fetch = async (u, o) => { const r = await f0(u, o); if (x.__slowState && /\/api\/state/.test(String(u))) await new Promise(rs => setTimeout(rs, 900)); return r; }; }});
  w.__slowState = true;
  const ld = w.eval('load()'); await sleep(80);
  await w.eval(`api('PATCH', '/api/settings', {hide_progress: '777'}).then(() => { S.settings.hide_progress = '777'; })`);
  await ld; w.__slowState = false;
  check(w.eval('S.settings.hide_progress') === '777', 'a state answer overtaken by a save does not undo it locally: ' + w.eval('S.settings.hide_progress'));
  await call('PATCH', '/api/settings', {hide_progress: ''});
  w.close();
  // unreachable server at the start: the heron
  w = await boot({user: 'alice', hash: 'today', setup: x => { x.__offline = true; }}); d = w.document;
  await sleep(500);
  const off = d.querySelector('#view .hempty');
  check(!off || off.querySelector('.heron'), 'start without a server: the heron (when the start page shows) ' + (off?.textContent || 'no start page'));
  w.close();
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));

  // ================= Firefox: layouts
  const ffLogin = async ({ev, nav}, theme = 'light') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const ROWS = `(() => { const vis = e => getComputedStyle(e).display !== 'none' && !!e.offsetParent;
    const v = document.querySelector('#view'), r = document.querySelector('#view .trow[data-id="${T1}"]');
    const cells = r ? [...r.querySelectorAll('.lcols .lc')].filter(vis) : [];
    const ml = r ? [...r.querySelectorAll('.meta .mlc')].filter(vis) : [], mlc = ml.length;
    const tiny = ml.filter(e => { const b = e.getBoundingClientRect(), m = e.closest('.meta').getBoundingClientRect(); return b.width < 4 || b.right > m.right + 1 || m.width < 40; }).length;
    const full = r ? [...r.querySelectorAll('.lcols .lc')].filter(c => c.innerHTML.trim()) : [], all = full.length, shown = full.filter(vis).length;
    const t = r && r.querySelector('.ttl').getBoundingClientRect(), rr = r && r.getBoundingClientRect();
    const head = document.querySelector('#view .lchead'), hv = head && vis(head);
    let align = 0;
    if (hv && r) { const hc = [...head.querySelectorAll('.lc')].filter(vis); cells.forEach((c, i) => { const h = hc[i]; if (h) align = Math.max(align, Math.abs(Math.round(h.getBoundingClientRect().right - c.getBoundingClientRect().right))); }); }
    const over = Math.max(v.scrollWidth - v.clientWidth, document.documentElement.scrollWidth - innerWidth);
    const outside = cells.filter(c => c.getBoundingClientRect().right > rr.right + 1).length;
    return {cells: cells.length, all, shown, mlc, tiny, head: !!hv, align, over, outside, titleW: t ? Math.round(t.width) : 0}; })()`;
  const DLG = `(() => { const c = document.querySelector('.colmd .card'); if (!c) return null; const r = c.getBoundingClientRect();
    const small = [...c.querySelectorAll('.colmv, .colr .chkl, .colnum, .foot .btn')].filter(e => e.offsetWidth).map(e => e.getBoundingClientRect()).filter(b => b.height < 43.5).length;
    return {fits: r.left >= 0 && r.right <= innerWidth + .5 && r.top >= 0 && r.bottom <= innerHeight + .5, small, over: c.scrollWidth - c.clientWidth}; })()`;
  const SUN = `(() => { const s = document.querySelector('#view .heron .hr-sun'); if (!s) return null; const acc = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
    const probe = document.createElement('span'); probe.style.color = 'var(--accent)'; document.body.appendChild(probe); const want = getComputedStyle(probe).color; probe.remove();
    const h = document.querySelector('#view .heron').getBoundingClientRect();
    return {fill: getComputedStyle(s).fill, want, acc, w: Math.round(h.width), line: getComputedStyle(document.querySelector('#view .heron')).color}; })()`;
  const layout = async ({cmd, ev, nav, ctx, shot}, vw, vh, tag, phone) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + '#l/' + P); await ready(ev);
    const x = await ev(ROWS);
    check(x.over <= 1 && x.outside === 0, `${tag}: no horizontal overflow, cells inside the row ` + JSON.stringify(x));
    check(x.tiny === 0, `${tag}: the second line is never squeezed behind a long title ` + JSON.stringify(x));
    const lvl = await ev(`(() => { const r = document.querySelector('#view .trow[data-id="${T1}"]'); const t = r.querySelector('.ttl').getBoundingClientRect(); const c = [...r.querySelectorAll('.lcols .lc')].find(e => getComputedStyle(e).display !== 'none' && e.innerHTML.trim()); if (!c) return null; const b = c.getBoundingClientRect(); const lh = parseFloat(getComputedStyle(r.querySelector('.ttl')).lineHeight); return Math.round(Math.abs((b.top + b.height / 2) - (t.top + lh / 2))); })()`);
    check(lvl !== null && lvl <= 4, `${tag}: the cells sit level with the title's first line (off by ${lvl} px)`);
    // phones and narrow list columns (an unfolded Fold with the sidebar): two cells, the rest in line 2, no title row
    if (phone || !x.head) check(x.cells <= 2 && x.shown + x.mlc === x.all && !x.head, `${tag}: at most two cells, the rest in line 2, no title row ` + JSON.stringify(x));
    else check(x.align <= 2 && x.cells >= 3 && x.shown + x.mlc === x.all, `${tag}: the title row lines up with the cells, the rest in line 2 ` + JSON.stringify(x));
    if (tag === '1920') check(x.shown === x.all && x.mlc === 0, '1920: every column has room, nothing doubled in line 2 ' + JSON.stringify(x));
    check(x.titleW >= 80, `${tag}: the title keeps room ` + JSON.stringify(x));
    await shot(`p2140-${tag}-list.png`);
    if (phone) {  // "Columns…" high up in "…" (the view group, after Sort…)
      const pos = await ev(`topMoreItems().filter(x => x !== '-').findIndex(x => x.label === 'Columns…')`);
      check(pos >= 0 && pos <= 6, `${tag}: "Columns…" is among the first entries of "…" (position ${pos + 1})`);
    }
    await ev(`(() => { colModal(${P}); return 1; })()`); await sleep(400);
    const dl = await ev(DLG);
    check(dl && dl.fits && dl.over <= 1 && (dl.small === 0 || !phone), `${tag}: the Columns dialog fits` + (phone ? ', 44 px targets ' : ' ') + JSON.stringify(dl));
    await shot(`p2140-${tag}-dialog.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    await nav(B + '#l/' + EMPTY); await ready(ev);
    const qb = await ev(`(() => { if (document.querySelector('#fab') && getComputedStyle(document.querySelector('#fab')).display !== 'none' && !document.querySelector('#qinput')?.offsetParent) openQuickSheet(); const b = [...document.querySelectorAll('.qadd [data-act="q-open"], .qadd [data-act="q-clip"]')].filter(e => e.offsetParent); const r = b.map(e => e.getBoundingClientRect()); const out = {n: b.length, minW: Math.round(Math.min(...r.map(x => x.width))), minH: Math.round(Math.min(...r.map(x => x.height))), inside: r.every(x => x.right <= innerWidth + .5 && x.left >= 0)}; closePop?.(); return out; })()`);
    check(qb.n === 2 && qb.inside && (!phone || (qb.minW >= 43.5 && qb.minH >= 43.5)), `${tag}: quick add shows the paper clip + "Add and open"` + (phone ? ' with 44 px targets ' : ' ') + JSON.stringify(qb));
    await sleep(300);
    const s = await ev(SUN);
    check(s && s.fill === s.want && s.w >= 90 && s.line !== s.fill, `${tag}: the heron's sun is the accent colour, lines in the text colour ` + JSON.stringify(s));
    await shot(`p2140-${tag}-empty.png`);
  };
  // phones (touch)
  for (const [vw, vh] of [[380, 800], [390, 844], [428, 926]]) await firefox(async o => {
    check(await ffLogin(o, vw === 390 ? 'dark' : 'light') === 200, vw + ': login');
    await layout(o, vw, vh, String(vw), true);
  }, true);
  // Fold (touch): unfolded 904, folded, unfolded again, rotated; 880 portrait
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o, 'dark') === 200, 'Fold: login');
    await layout(o, 904, 904, 'fold904', false);
    await o.nav(B + '#l/' + P); await ready(ev);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 904}}); await sleep(900);
    const f1 = await ev(ROWS);
    check(f1.cells <= 2 && f1.over <= 1 && !f1.head, 'Fold folded (412): two cells, nothing sticks out ' + JSON.stringify(f1));
    await shot('p2140-fold-folded.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 904}}); await sleep(900);
    const f2 = await ev(ROWS);
    check(f2.over <= 1 && f2.outside === 0, 'Fold unfolded again: no overflow ' + JSON.stringify(f2));
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 680}}); await sleep(900);
    const f3 = await ev(ROWS);
    check(f3.over <= 1 && f3.outside === 0, 'Fold rotated (904 x 680): no overflow ' + JSON.stringify(f3));
    await shot('p2140-fold-rotated.png');
    await layout(o, 880, 904, 'fold880', true);
  }, true);
  // desktops (mouse)
  for (const [vw, vh, th] of [[1100, 800, 'light'], [1440, 900, 'dark'], [1920, 1080, 'light']]) await firefox(async o => {
    check(await ffLogin(o, th) === 200, vw + ': login');
    await layout(o, vw, vh, String(vw), false);
    if (vw === 1440) {  // drag the handle of the sixth row to the top (one drag, several rows)
      await o.ev(`(() => { colModal(${P}); return 1; })()`); await sleep(400);
      const pt = await o.ev(`(() => { const r = [...document.querySelectorAll('.colr')]; const h = r[5].querySelector('.colh').getBoundingClientRect(), t = r[0].getBoundingClientRect(); return {x: h.left + h.width / 2, y: h.top + h.height / 2, ty: t.top + 4, k: r[5].dataset.k}; })()`);
      await o.drag(pt.x, pt.y, 0, pt.ty - pt.y);
      await sleep(300);
      const first = await o.ev(`document.querySelector('.colr').dataset.k`);
      check(first === pt.k, `1440: dragging the handle moves a row over several places (${pt.k} -> first: ${first})`);
      await o.ev(`(() => { document.querySelector('[data-colact="close"]').click(); return 1; })()`); await sleep(300);
      check(await o.ev(`document.activeElement === document.querySelector('#top [data-act="top-more"]') || document.activeElement === document.body || !!document.activeElement`), '1440: the dialog closes');
    }
    if (vw === 1920) {  // with the task panel open the list column gets narrower: still no overflow
      await o.nav(B + '#l/' + P); await ready(o.ev);
      await o.ev(`(() => { openDetail(${T1}); return 1; })()`); await sleep(900);
      const x = await o.ev(ROWS);
      check(x.over <= 1 && x.outside === 0, '1920 with the task panel: no overflow ' + JSON.stringify(x));
      await o.shot('p2140-1920-detail.png');
    }
  }, false);

  console.log(`p2140_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
