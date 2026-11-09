// kalmido-suite: fresh
// 2.768.0 (#4888) part A UI tests: in the area "Files" ONE selection, ONE bar, ONE menu for rows AND cards (documents, files,
// folders) in every view. Own container (start.sh), jsdom (computer and a 390 px phone). Invented names and files only.
// - a folder with recognition: every card (its subfolder too) has the choosing mark; a right click on a document card and on a
//   folder card opens the menu with "Select" on top and the file row's items (Open, Download, Rename, Move to, a new version,
//   the trash); a mixed choice (subfolder + document) -> Move -> ONE undo brings both back
// - All documents: choose two -> "Move to the trash" asks with the number -> both go -> ONE undo brings both back
// - a folder shown as cards: a plain file card has the mark and the same menu (its "…" too); file + folder + document chosen:
//   the bar offers Edit (documents chosen), a file alone not
// - a reader: a node without write rights is skipped and counted ("1 skipped"), the rest goes; the reader's menu has no
//   writing items
// - a phone (390 px): a long press on a card opens the menu with "Select" on top; while choosing a long press ticks
// - Firefox (a finger, 390 and 320 px; a mouse, 1440 px): the bar with all six buttons stays inside the screen (P2768A_SHOTS: pictures)
// freelancer-matrix: files, docs (alice and bob have no organisation: their private workspaces)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until, histAdded} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } return !!c; };
const ff = require('./ff');
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2768A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const up = async (ck, url, field, name, text, extra = {}) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  fd.append(field, new Blob([text], {type: 'text/plain'}), name);
  return (await fetch(B + url, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd})).json().catch(() => ({}));
};
const pe = (w, el, type) => {  // a touch pointer (jsdom: a MouseEvent with pointerType)
  const ev = new w.MouseEvent(type, {bubbles: true, cancelable: true, clientX: 30, clientY: 30, button: 0});
  for (const [k, v] of [['pointerId', 1], ['pointerType', 'touch']]) Object.defineProperty(ev, k, {value: v});
  el.dispatchEvent(ev);
};
const rclick = (w, el) => el.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, button: 2}));
const ctrlClick = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ctrlKey: true}));
const menuIt = d => d.querySelector('#pop:not(.hidden)') ? [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim()) : [];
const menuPick = (d, t) => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(x => x.textContent.trim() === t || x.textContent.trim().startsWith(t))?.click();
const shut = async w => { w.eval('closePop()'); await until(() => !menuIt(w.document).length, {timeout: 3000}); };
const count = d => d.querySelector('#ab-sbar .mcount')?.textContent || '';
const card = (d, id) => d.querySelector(`.dc-card [data-dcchk="${id}"]`)?.closest('.dc-card');
const face = (d, id) => card(d, id)?.querySelector('[data-dco], [data-ab="open"]');  // the card's own button (a document's or a file's / folder's)

(async () => {
  await sleep(600);
  check((await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})})).ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const on = async ck => { const st = await call(ck, 'GET', '/api/state'); const feats = [...new Set([...(st.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(','); await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'}); };
  await on(CA);
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Reader', password: 'password123', email: 'bob@example.com', orgs: []})).id;
  const CB = await login('bob'); await on(CB);
  check(BOB, 'setup: bob');
  // the documents folder (recognises) with a subfolder and two documents; a target folder; a plain folder as cards
  const D0 = ((await up(CA, 'api/docs', 'files', 'letter-heron.txt', 'Letter of an invented heron club', {ws: 'private'})).ids || [])[0];
  const ROOT = (await call(CA, 'GET', `/api/files/nodes/${D0}`)).parent_id;
  const SUB = (await call(CA, 'POST', '/api/files/folders', {parent_id: ROOT, name: 'Heron archive'})).id;
  const D1 = ((await up(CA, 'api/files/upload', 'file', 'heron-one.txt', 'An invented heron letter one', {parent_id: String(ROOT)})).items || [])[0]?.id;
  const D2 = ((await up(CA, 'api/files/upload', 'file', 'heron-two.txt', 'An invented heron letter two', {parent_id: String(ROOT)})).items || [])[0]?.id;
  const TGT = (await call(CA, 'POST', '/api/files/folders', {space: 'private', name: 'Target box'})).id;
  const GARDEN = (await call(CA, 'POST', '/api/files/folders', {space: 'private', name: 'Garden'})).id;
  const G2 = (await call(CA, 'POST', '/api/files/folders', {parent_id: GARDEN, name: 'Seed packs'})).id;
  const P = ((await up(CA, 'api/files/upload', 'file', 'seeds.txt', 'Tomatoes, beans', {parent_id: String(GARDEN)})).items || [])[0]?.id;
  const D3 = ((await up(CA, 'api/files/upload', 'file', 'heron-three.txt', 'An invented heron letter three', {parent_id: String(ROOT)})).items || [])[0]?.id;
  check(ROOT && SUB && D1 && D2 && TGT && GARDEN && G2 && P && D3, 'setup: folders, files, documents');
  check(await until(async () => (await call(CA, 'GET', `/api/docs/${D3}`)).http === 200), 'setup: the files in the documents folder are documents');
  check((await call(CA, 'PATCH', `/api/files/nodes/${D3}`, {parent_id: GARDEN})).http < 300, 'setup: a document moved into the plain folder (stays a document)');
  await call(CA, 'PATCH', '/api/settings', {set_delta: {ab_cards: {add: ['n:' + GARDEN]}}});
  // a reader: a folder shared with bob for reading, in it a folder he may change and a file he may only read
  const BOX = (await call(CA, 'POST', '/api/files/folders', {space: 'private', name: 'Shared box'})).id;
  const Q = (await call(CA, 'POST', '/api/files/folders', {parent_id: BOX, name: 'Bob may change'})).id;
  const R = ((await up(CA, 'api/files/upload', 'file', 'read-only.txt', 'Only to read', {parent_id: String(BOX)})).items || [])[0]?.id;
  check((await call(CA, 'POST', `/api/files/nodes/${BOX}/shares`, {user_id: BOB, role: 'view'})).http < 300 && (await call(CA, 'POST', `/api/files/nodes/${Q}/shares`, {user_id: BOB, role: 'edit'})).http < 300, 'setup: shared with bob (view, a subfolder edit)');
  // 2.768.0 (#4888): the documents' list carries each row's role and owner (the bar leaves out what may not change)
  const dl = await call(CA, 'GET', '/api/docs?ws=private&facets=0');
  check((dl.docs || []).length >= 3 && dl.docs.every(x => x.role === 'owner' && x.owner_id), 'the documents\' list has role + owner per row ' + JSON.stringify((dl.docs || []).map(x => [x.id, x.role, x.owner_id])));
  const parent = async id => (await call(CA, 'GET', `/api/files/nodes/${id}`)).parent_id;
  const inTrash = async id => !!(await call(CA, 'GET', `/api/files/nodes/${id}`)).in_trash;

  // ================= a folder with recognition: every card has the mark, ONE menu on document and folder cards
  let w = await boot({user: 'alice', hash: 'ablage/' + ROOT}), d = w.document;
  check(await until(() => card(d, SUB) && card(d, D1) && card(d, D2)), 'the folder with recognition: the subfolder and the documents as cards, each with its mark');
  rclick(w, face(d, D1));
  let it = await until(() => menuIt(d).length > 3 && menuIt(d));
  check(it && it[1] === 'Select', 'a right click on a document card: "Select" on top ' + it);
  check(it && ['Open', 'Download', 'Rename…', 'Move to…', 'Upload a new version…', 'Move to the trash'].every(t => it.includes(t)), 'the document card\'s menu = the file row\'s items ' + it);
  await shut(w);
  rclick(w, face(d, SUB));
  it = await until(() => menuIt(d).length > 3 && menuIt(d));
  check(it && it[1] === 'Select' && it.includes('Move to the trash') && it.includes('Download as ZIP'), 'a right click on a folder card: "Select" on top, the folder\'s items ' + it);
  // the card's "…" opens the same menu
  await shut(w);
  card(d, D2).querySelector('[data-ab="menu"]')?.click();
  it = await until(() => menuIt(d).length > 3 && menuIt(d));
  check(it && it[1] === 'Select' && it.includes('Rename…'), 'the card\'s "…" opens the same menu ' + it);
  menuPick(d, 'Select');
  check(await until(() => /1 selected/.test(count(d)) && w.eval(`AB.sel.has(${D2})`)), '"Select" starts choosing with the card');
  const h0 = w.location.hash;
  face(d, SUB).dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  check(await until(() => /2 selected/.test(count(d))) && w.location.hash === h0, 'while choosing a tap on the folder card ticks it, nothing opens');
  const bar = d.querySelector('#ab-sbar');
  check(bar && ['all', 'move', 'dl', 'edit', 'trash', 'more', 'close'].every(k => bar.querySelector(`[data-absel="${k}"]`)), 'ONE bar: All, Move, Download, Edit (a document is chosen), Move to the trash, More');
  check(bar?.querySelector('[data-absel="trash"].danger'), '... "Move to the trash" is red');
  const n0 = w.eval('HIST.undo.length');
  bar.querySelector('[data-absel="move"]').click();
  await until(() => menuIt(d).some(t => /Target box/.test(t)));
  menuPick(d, 'Target box');
  check(await until(async () => await parent(D2) === TGT && await parent(SUB) === TGT, 60), 'Move: the document and the subfolder are in the target folder');
  check(await histAdded(w, n0), 'ONE undo step for both');
  await w.eval(`histStep('undo')`);
  check(await until(async () => await parent(D2) === ROOT && await parent(SUB) === ROOT, 60), 'Undo brings both back');
  w.close();

  // ================= All documents: two into the trash, asked with the number, ONE undo
  w = await boot({user: 'alice', hash: 'ablage/docs'}); d = w.document;
  const asked = []; w.confirm = m => { asked.push(m); return true; };
  check(await until(() => card(d, D0) && card(d, D1)), 'All documents: the cards');
  ctrlClick(w, face(d, D0));
  await until(() => /1 selected/.test(count(d)));
  card(d, D1).querySelector('[data-dcchk]').click();
  check(await until(() => /2 selected/.test(count(d))), 'Ctrl-click and the mark choose two documents');
  const n1 = w.eval('HIST.undo.length');
  d.querySelector('#ab-sbar [data-absel="trash"]').click();
  check(await until(() => asked.length === 1) && /Move 2 items to the trash\?/.test(asked[0]), 'the bar asks with the number ' + asked[0]);
  check(await until(async () => await inTrash(D0) && await inTrash(D1), 60), 'both documents are in the trash');
  check(await histAdded(w, n1), 'ONE undo step');
  check(await until(() => !d.querySelector('#ab-sbar')), 'the selection ends');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await inTrash(D0)) && !(await inTrash(D1)), 60), 'Undo brings both documents back');
  w.close();

  // ================= a folder as cards: a plain file card has the mark and the same menu; file + folder + document chosen
  w = await boot({user: 'alice', hash: 'ablage/' + GARDEN}); d = w.document;
  check(await until(() => card(d, P) && card(d, G2) && card(d, D3)), 'the plain folder as cards: file, folder and document, each with its mark');
  rclick(w, face(d, P));
  it = await until(() => menuIt(d).length > 3 && menuIt(d));
  check(it && it[1] === 'Select' && it.includes('Rename…') && it.includes('Move to the trash'), 'a right click on a file card: the same menu with "Select" on top ' + it);
  menuPick(d, 'Select');
  check(await until(() => /1 selected/.test(count(d)) && !d.querySelector('#ab-sbar [data-absel="edit"]')), 'a plain file alone: no Edit');
  card(d, G2).querySelector('[data-dcchk]').click();
  card(d, D3).querySelector('[data-dcchk]').click();
  check(await until(() => /3 selected/.test(count(d)) && d.querySelector('#ab-sbar [data-absel="edit"]')), 'file + folder + document in ONE choice: Edit is there');
  // a right click on a chosen card of several: the bar's actions as a menu
  rclick(w, face(d, D3));
  it = await until(() => menuIt(d).length > 3 && menuIt(d));
  check(it && /3 selected/.test(it[0]) && ['Move to…', 'Download', 'Edit', 'Move to the trash'].every(t => it.includes(t)), 'a right click on a chosen card: the selection\'s menu = the bar ' + it);
  await shut(w);
  d.querySelector('#ab-sbar [data-absel="close"]').click();
  check(await until(() => !d.querySelector('#ab-sbar') && !w.eval('AB.selOn')), 'X ends the selection');
  w.close();

  // ================= a reader: skipped and counted, no writing items
  w = await boot({user: 'bob', hash: 'ablage/' + BOX}); d = w.document;
  const asked2 = []; w.confirm = m => { asked2.push(m); return true; };
  check(await until(() => d.querySelector(`.abrow[data-abid="${Q}"]`) && d.querySelector(`.abrow[data-abid="${R}"]`)), 'bob sees the shared folder\'s rows');
  rclick(w, d.querySelector(`.abrow[data-abid="${R}"] .abopen`));
  it = await until(() => menuIt(d).length > 2 && menuIt(d));
  check(it && it.includes('Open') && !['Rename…', 'Move to…', 'Move to the trash', 'Upload a new version…', 'Tags…'].some(t => it.includes(t)), 'a reader\'s menu has no writing items ' + it);
  await shut(w);
  for (const id of [Q, R]) { const b = d.querySelector(`[data-absel="one"][data-id="${id}"]`); b.checked = true; b.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(() => /2 selected/.test(count(d))), 'bob chooses both rows');
  d.querySelector('#ab-sbar [data-absel="trash"]').click();
  check(await until(() => asked2.length === 1) && /Move 1 item to the trash\?/.test(asked2[0]) && /1 skipped/.test(asked2[0]), 'the question counts what goes and what is skipped ' + asked2[0]);
  check(await until(async () => await inTrash(Q), 60) && !(await inTrash(R)), 'the folder bob may change went, the read-only file stayed');
  check(await until(() => /1 skipped/.test(d.querySelector('#toast')?.textContent || '')), 'the message says "1 skipped" ' + (d.querySelector('#toast')?.textContent || ''));
  w.close();
  await call(CA, 'POST', '/api/files/restore', {ids: [Q]});

  // ================= a phone (390 px): a long press on a card opens the menu, while choosing it ticks
  w = await boot({user: 'alice', hash: 'ablage/' + ROOT, mobile: true}); d = w.document;
  w.innerWidth = 390;
  check(await until(() => card(d, D1) && card(d, D2)), 'phone: the cards');
  pe(w, face(d, D1), 'pointerdown');
  it = await until(() => menuIt(d).length > 3 && menuIt(d));
  check(it && it[1] === 'Select' && !w.eval('AB.selOn'), 'phone: a long press opens the menu, "Select" on top ' + it);
  pe(w, face(d, D1), 'pointerup');
  menuPick(d, 'Select');
  check(await until(() => w.eval(`AB.selOn && AB.sel.has(${D1})`)), 'phone: "Select" starts choosing');
  await sleep(700);  // the click guard of the press is over (multisel.js ms_lpRecent, its own time)
  pe(w, face(d, D2), 'pointerdown');
  check(await until(() => w.eval(`AB.sel.has(${D2})`)) && !menuIt(d).length, 'phone: while choosing a long press ticks the card, no menu');
  pe(w, face(d, D2), 'pointerup');
  check(/2 selected/.test(count(d)), 'phone: the bar counts both');
  w.close();

  // ================= Firefox: the bar fits (a finger at 390 / 320 px, a mouse at 1440 px)
  for (const [touch, sizes] of [[true, [[390, 844], [320, 640]]], [false, [[1440, 900]]]]) {
    await ff({tag: 'p2768_a_ui', check, shots: 'P2768A_SHOTS'})(async o => {
      const {cmd, ev, ctx, shot} = o;
      await o.nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
      const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
      for (const [wd, h] of sizes) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: h}});
        await o.nav(B + '#ablage/' + ROOT);
        check(await wait(`!!document.querySelector('.dc-card [data-dcchk="${D1}"]') && !!document.querySelector('.dc-card [data-dcchk="${SUB}"]')`), `${wd}: the folder's cards`);
        await ev(`(ab_selPick(${D1}), ab_selPick(${SUB}), 1)`);
        check(await wait(`/2 selected/.test(document.querySelector('#ab-sbar .mcount')?.textContent || '')`), `${wd}: the bar with 2 selected`);
        await sleep(400);
        const m = await ev(`(() => { const b = document.querySelector('#ab-sbar'), r = b.getBoundingClientRect(), bs = [...b.querySelectorAll('.mbb, .mbx')].map(x => x.getBoundingClientRect());
          return {l: Math.round(r.left), r: Math.round(r.right), n: bs.length, inside: bs.every(x => x.width > 0 && x.left >= r.left - 1 && x.right <= r.right + 1 && x.bottom <= innerHeight + 1), over: document.documentElement.scrollWidth > innerWidth + 1}; })()`);
        check(m && m.n === 7 && m.l >= 0 && m.r <= wd + 1 && m.inside && !m.over, `${wd}: all six buttons and X inside the bar, the bar inside the screen ` + JSON.stringify(m));
        await shot(`p2768-a-${wd}-bar.png`);
        await ev(`(ab_selEnd(), ab_draw(), 1)`);
      }
    }, touch);
  }

  console.log(`p2768_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
