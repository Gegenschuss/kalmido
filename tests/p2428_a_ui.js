// kalmido-suite: fresh
// 2.428.0 A (#3581) UI tests: one selection bar everywhere -- the shared floating bar of multisel.js (ms_barHtml, class
// .mselbar, like the tasks' and the contacts' bar) in the documents, the file store, the knowledge lists, the user
// management and the receipts of a trip. Own container (start.sh), jsdom, invented names only.
// - documents: Select -> #dc-sbar (hint, count, Edit, Download, More); More holds the CSV export; Esc ends; a Ctrl-click
//   on a card and a click on its hover mark start choosing (nothing opens); a long press (touch) starts it too
// - file store: the row's box (shown on hover) starts choosing -> #ab-sbar (Move, Download, Delete); Ctrl-click, Shift-click
//   range, long press; Delete moves the chosen files into the trash; Esc ends
// - knowledge: a box ticked on hover starts choosing -> #wk-sbar; Ctrl-click on a second row adds it (no page opens); Esc ends
// - users (settings): a tick shows #ua-sbar; Esc clears the selection first, the dialog stays
// - trip receipts: a tick shows #rk-sbar with "Bill on"; All ticks every open receipt; Esc ends
// - the old bars' CSS (.dc-selbar, .abselbar, .wkselbar, .ua8sel) is gone, .mselbar floats
// freelancer-matrix: files, docs, wiki (alice has no organisation: her private spaces; the file store's bar has no "More")
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2428A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const upload = async (name, text) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name); fd.append('space', 'private');
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return (await r.json()).items[0].id;
};
const esc = (w, el) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
const tick = (w, el) => { el.checked = true; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const ctrlClick = (w, el, shift) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ctrlKey: !shift, shiftKey: !!shift}));
const touch = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); for (const [k, v] of Object.entries({pointerType: 'touch', clientX: 5, clientY: 5})) Object.defineProperty(e, k, {value: v}); el.dispatchEvent(e); };
const count = (d, id) => d.querySelector(`#${id} .mcount`)?.textContent || '';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs', 'wiki', 'office'])].filter(Boolean).join(',')});

  // ================= the CSS: one floating bar, the old ones gone
  const css = ['app.css', 'css/docs.css', 'css/wiki.css', 'css/settings.css'].map(f => { try { return fs.readFileSync(path.join(__dirname, '..', 'static', f), 'utf8'); } catch { return ''; } }).join('\n');
  check(/\.mselbar\{position:fixed/.test(css), 'the shared bar (.mselbar) floats');
  check(!/\.(dc-selbar|abselbar|wkselbar|ua8sel)\{/.test(css) && !/#ct-sbar\{/.test(css), 'the old bars have no CSS any more');

  // ================= documents
  for (const t of ['Letter one', 'Letter two']) {
    const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob(['Invoice example ' + t]), t + '.txt');
    const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
    check(r.status === 201, 'a document uploaded: ' + r.status);
  }
  let w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  await until(() => d.querySelectorAll('[data-dco]').length === 2, 60);
  const ids = w.eval('DC.docs.map(x => x.id)');
  check(!d.querySelector('#dc-sbar') && d.querySelectorAll('.dc-selmark').length === 2, 'documents: no bar yet, every card has its (hover) mark');
  d.querySelector('[data-dcsel="mode"]').click();
  let bar = await until(() => d.querySelector('#dc-sbar.mselbar'));
  check(bar && /Tap documents/.test(count(d, 'dc-sbar')) && bar.querySelector('[data-dcsel="edit"]')?.disabled, 'documents: Select -> the shared bar with the hint, Edit waits ' + count(d, 'dc-sbar'));
  for (const id of ids) w.eval(`dc_smvToggle(${id})`);
  bar = await until(() => /2 selected/.test(count(d, 'dc-sbar')) && d.querySelector('#dc-sbar'));
  check(bar && ['edit', 'zip', 'more', 'all', 'close'].every(k => bar.querySelector(`[data-dcsel="${k}"]`)), 'documents: 2 selected, Edit / Download / More / All / X');
  bar?.querySelector('[data-dcsel="more"]').click();
  check(await until(() => d.querySelector('#pop .menu-list .msm-csv')), 'documents: More holds "Export as CSV"');
  w.eval('closePop()');
  esc(w, d.body);
  check(await until(() => !d.querySelector('#dc-sbar') && !w.eval('DC.selOn')), 'documents: Esc ends the selection');
  const h0 = w.location.hash;
  ctrlClick(w, d.querySelector(`[data-dco="${ids[0]}"]`));
  check(await until(() => /1 selected/.test(count(d, 'dc-sbar'))) && w.location.hash === h0 && !d.querySelector('.dc-md'), 'documents: a Ctrl-click chooses the card, nothing opens');
  esc(w, d.body); await until(() => !w.eval('DC.selOn'));
  d.querySelector(`[data-dco="${ids[1]}"] .dc-selmark`).dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  check(await until(() => /1 selected/.test(count(d, 'dc-sbar')) && w.eval(`DC.sel.has(${ids[1]})`)), 'documents: the hover mark starts choosing');
  esc(w, d.body); await until(() => !w.eval('DC.selOn'));
  touch(w, d.querySelector(`[data-dco="${ids[0]}"]`), 'pointerdown');
  check(await until(() => w.eval(`DC.selOn && DC.sel.has(${ids[0]})`)), 'documents: a long press starts choosing with the card');
  touch(w, d.querySelector(`[data-dco="${ids[0]}"]`), 'pointerup');
  w.close();

  // ================= file store
  const A = [await upload('a-one.txt', 'first'), await upload('b-two.txt', 'second'), await upload('c-three.txt', 'third')];  // by name or by date: A[0] .. A[2] span all three
  w = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: '"private"'}}); d = w.document;
  const box = id => d.querySelector(`[data-absel="one"][data-id="${id}"]`);
  await until(() => A.every(box), 60);
  check(!d.querySelector('#ab-sbar') && A.every(box), 'file store: no bar yet, every row has its (hover) box');
  tick(w, box(A[0]));
  bar = await until(() => /1 selected/.test(count(d, 'ab-sbar')) && d.querySelector('#ab-sbar.mselbar'));
  check(bar && ['move', 'dl', 'trash', 'all', 'close'].every(k => bar.querySelector(`[data-absel="${k}"]`)) && !bar.querySelector('[data-absel="more"]'),
    'file store: the box starts choosing -> Move, Download, Delete, no "More" without an organisation');
  esc(w, d.body);
  check(await until(() => !d.querySelector('#ab-sbar') && !w.eval('AB.selOn')), 'file store: Esc ends the selection');
  const h1 = w.location.hash;
  ctrlClick(w, d.querySelector(`.abrow[data-abid="${A[0]}"] .abopen`));
  await until(() => /1 selected/.test(count(d, 'ab-sbar')));
  ctrlClick(w, d.querySelector(`.abrow[data-abid="${A[2]}"] .abopen`), true);
  check(await until(() => /3 selected/.test(count(d, 'ab-sbar'))) && w.location.hash === h1 && !d.querySelector('.modal'), 'file store: Ctrl-click, then Shift-click chooses the range, nothing opens');
  esc(w, d.body); await until(() => !w.eval('AB.selOn'));
  touch(w, d.querySelector(`.abrow[data-abid="${A[1]}"] .abopen`), 'pointerdown');
  check(await until(() => w.eval(`AB.selOn && AB.sel.has(${A[1]})`)), 'file store: a long press starts choosing (the menu stays on the right click)');
  touch(w, d.querySelector(`.abrow[data-abid="${A[1]}"] .abopen`), 'pointerup');
  await sleep(700);  // the click that would end the press is past (ms_lpRecent)
  tick(w, box(A[2]));
  await until(() => /2 selected/.test(count(d, 'ab-sbar')));
  d.querySelector('#ab-sbar [data-absel="trash"]').click();
  check(await until(async () => { const it = (await call('GET', '/api/files?space=private')).items || []; return !it.some(n => n.id === A[1] || n.id === A[2]) && it.some(n => n.id === A[0]); }, 60),
    'file store: Delete moves the chosen files into the trash');
  check(await until(() => !d.querySelector('#ab-sbar')), 'file store: the selection ends after the action');
  w.close();

  // ================= knowledge
  for (const p of ['Loose', 'Other']) await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p});
  w = await boot({user: 'alice', hash: 'wiki'}); d = w.document;
  const row = txt => [...d.querySelectorAll('#view .wkrow')].find(r => r.querySelector(':scope > .wkitem, :scope > details > summary > .wkitem')?.textContent.trim() === txt);
  const wbox = txt => row(txt)?.querySelector(':scope > .absel input[data-wksel="one"]');
  await until(() => wbox('Loose') && wbox('Other'), 60);
  check(wbox('Loose') && !d.querySelector('#view .wkselrow') && !d.querySelector('#wk-sbar'), 'knowledge: the (hover) boxes wait, no bar yet');
  tick(w, wbox('Loose'));
  check(await until(() => /1 selected/.test(count(d, 'wk-sbar')) && d.querySelector('#wk-sbar.mselbar [data-wksel="move"]') && d.querySelector('#wk-sbar [data-wksel="trash"]')),
    'knowledge: the box starts choosing -> the shared bar with Move and Delete');
  const h2 = w.location.hash;
  ctrlClick(w, row('Other').querySelector(':scope > .wkitem'));
  check(await until(() => /2 selected/.test(count(d, 'wk-sbar'))) && w.location.hash === h2, 'knowledge: a Ctrl-click adds a row, no page opens');
  esc(w, d.body);
  check(await until(() => !d.querySelector('#wk-sbar') && !w.eval('WK.selOn')), 'knowledge: Esc ends the selection');
  w.close();

  // ================= users (settings)
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Example', password: 'password123', email: 'bob@example.com', orgs: []});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('users')`);
  const ub = await until(() => d.querySelector('#a-users .ua8chk:not(:disabled)'), 60);
  tick(w, ub);
  check(await until(() => /1 selected/.test(count(d, 'ua-sbar')) && d.querySelector('#a-usel #ua-sbar.mselbar [data-ubulk="disable"]') && d.querySelector('#ua-sbar [data-ubulk="enable"]')),
    'users: a tick shows the shared bar with Disable / Enable');
  esc(w, ub);
  check(await until(() => d.querySelector('#a-usel').hidden && !ub.checked) && d.querySelector('.modal #a-users'), 'users: Esc clears the selection, the dialog stays');
  w.close();

  // ================= trip receipts
  const y = new Date().getFullYear();
  const trip = await call('POST', '/api/office/trips', {date_from: `${y}-03-10`, dest: 'Example Town', people: [{id: st.me.id}], items: [{date: `${y}-03-10`, category: 'train', amount: 40}, {date: `${y}-03-10`, category: 'taxi', amount: 12}]});
  check(trip.id, 'a trip with two receipts ' + trip.http);
  w = await boot({user: 'alice', hash: 'office/travel'}); d = w.document;
  await until(() => w.eval(`typeof RK === 'object' && !!RK.data`), 60);
  w.eval(`RK.year = ''; RK.open = ${trip.id}; rk_reload()`);
  const rb = await until(() => d.querySelectorAll('[data-rk="sel"]').length === 2 && d.querySelector('[data-rk="sel"]'), 60);
  check(rb && !d.querySelector('#rk-sbar'), 'trip: the receipts have their boxes, no bar yet');
  if (rb) tick(w, rb);
  check(await until(() => /1 selected/.test(count(d, 'rk-sbar')) && d.querySelector('#rk-sbar.mselbar [data-rk="bill"]')), 'trip: a tick shows the shared bar with "Bill on"');
  d.querySelector('#rk-sbar [data-rk="all"]')?.click();
  check(await until(() => /2 selected/.test(count(d, 'rk-sbar'))), 'trip: All ticks every open receipt');
  esc(w, d.body);
  check(await until(() => !d.querySelector('#rk-sbar') && !w.eval('RK.sel.size')), 'trip: Esc ends the selection');
  w.close();

  console.log(`p2428_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
