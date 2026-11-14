// 2.558.0 UI tests (#4693: the file store shows who a node is shared with), own container (start.sh). Invented names only.
// kalmido-suite: fresh
// - a folder's head: "Share" on top and below it "Shared with Bob Example · agent Helper bot" (inherited ones included),
//   a folder without shares: "Only you"; the button opens the Share dialog
// - a row: the names instead of the bare symbol (from three on "Carol Example +4"), a click opens the Share dialog
// - a card (the folder as cards): the same names on the tile
// - the end of a scan: "saved · Shared with …" (from the folder it went into) with "Share…"
// - a receiver: "Shared by Alice Admin" on the row of Shared with me and on the folder's head, no names of other shares
// - Firefox: the names sit inside the row (no overflow), a screenshot of the folder (P2558SN_SHOTS)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2558_4693_share_names_ui', check: (c, w) => check(c, w), shots: 'P2558SN_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2558SN_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const upload = async (name, parent) => { const fd = new FormData(); fd.append('parent_id', String(parent)); fd.append('file', new Blob(['hello']), name); const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd}); return (await r.json()).items[0].id; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Admin', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const U = {};
  for (const [u, nm] of [['bob', 'Bob Example'], ['carol', 'Carol Example'], ['dan', 'Dan Example'], ['erin', 'Erin Example']]) U[u] = (await call('POST', '/api/users', {username: u, display_name: nm, password: 'password123'})).id;
  const AG = (await call('POST', '/api/admin/agents', {username: 'helperbot', display_name: 'Helper bot'})).id;
  const PROJ = (await call('POST', '/api/files/folders', {space: 'private', name: 'Project'})).id;
  const QUIET = (await call('POST', '/api/files/folders', {space: 'private', name: 'Quiet'})).id;
  const SUB = (await call('POST', '/api/files/folders', {parent_id: PROJ, name: 'Invoices'})).id;
  const FILE = await upload('plan.txt', SUB);
  await call('POST', `/api/files/nodes/${PROJ}/shares`, {user_id: U.bob, role: 'view'});
  await call('POST', `/api/files/nodes/${PROJ}/shares`, {agent_id: AG, role: 'view'});
  for (const u of ['carol', 'dan', 'erin']) await call('POST', `/api/files/nodes/${FILE}/shares`, {user_id: U[u], role: 'view'});

  // ================= the owner: the folder's head
  let w = await boot({user: 'alice', hash: 'ablage/' + PROJ}), d = w.document;
  const line = await until(() => d.querySelector('#view .abshline'));
  check(/Shared with Bob Example · agent Helper bot/.test(line?.textContent || ''), 'head: "Shared with Bob Example · agent Helper bot" ' + (line?.textContent || ''));
  check(d.querySelector('#view .abtools [data-ab="share"].abshbtn'), 'head: the Share button on top');
  const sub = await until(() => d.querySelector(`.abrow[data-abid="${SUB}"] .abshw`));
  check(/Bob Example, Helper bot/.test(sub?.textContent || ''), 'a subfolder row: the inherited names ' + (sub?.textContent || ''));
  d.querySelector('#view .abtools .abshbtn').click();
  const md = await until(() => d.querySelector('.abshdlg'));
  check(/Project/.test(md?.querySelector('h3')?.textContent || ''), 'the head\'s Share opens the dialog of the folder');
  md?.querySelector('[data-m="close"]')?.click();
  await until(() => !d.querySelector('.abshdlg'));

  // ================= a row with five names: "Carol Example +4", a click opens its dialog
  w.eval(`go('ablage/${SUB}')`);
  const fr = await until(() => d.querySelector(`.abrow[data-abid="${FILE}"] .abshw`));
  check((fr?.textContent || '').trim() === 'Carol Example +4', 'from three on: the first name +N ' + (fr?.textContent || ''));
  check(/Carol Example, Dan Example, Erin Example, Bob Example · agent Helper bot/.test(fr?.getAttribute('title') || ''), 'the full list as its title ' + fr?.getAttribute('title'));
  fr?.click();
  const md2 = await until(() => d.querySelector('.abshdlg'));
  check(/plan\.txt/.test(md2?.querySelector('h3')?.textContent || ''), 'a click on the names opens the Share dialog of the file');
  md2?.querySelector('[data-m="close"]')?.click();
  await until(() => !d.querySelector('.abshdlg'));

  // ================= the end of a scan (the scan dialog itself is p21121; here its done() as abm_scan calls it)
  await w.eval(`loadModule('abscan')`);
  const NEW = await upload('Scan 1.txt', SUB);
  await w.eval(`(() => { AB.data.items = AB.data.items.filter(x => x.id !== ${NEW}); abm_scanOpen = o => o.done([{id: ${NEW}, name: 'Scan 1.txt', role: 'owner', share_with: []}]); abm_scan(); return 1; })()`);
  const dn = await until(() => d.querySelector('#view .abscdone'));
  check(/Scan 1\.txt/.test(dn?.textContent || '') && /Shared with Bob Example · agent Helper bot/.test(dn?.textContent || ''), 'the scan\'s end: saved + who sees it (from the folder) ' + (dn?.textContent || ''));
  dn?.querySelector('[data-ab="share"]')?.click();
  const md3 = await until(() => d.querySelector('.abshdlg'));
  check(/Scan 1\.txt/.test(md3?.querySelector('h3')?.textContent || ''), 'the scan\'s end: "Share…" opens the dialog of the new file');
  md3?.querySelector('[data-m="close"]')?.click();
  await until(() => !d.querySelector('.abshdlg'));
  d.querySelector('#view .abscdone [data-ab="scandone-x"]')?.click();
  check(await until(() => !d.querySelector('#view .abscdone')), 'the scan\'s end closes');

  // ================= the folder as cards: the names on the tile
  await w.eval(`loadModule('docs')`);
  if (await w.eval(`typeof abd_setCards === 'function' && abd_on()`)) {
    await w.eval(`abd_setCards('n:${SUB}', true)`);
    const cd = await until(() => d.querySelector(`.abcards .abcshw .abshw[data-id="${FILE}"]`));
    check((cd?.textContent || '').trim() === 'Carol Example +4', 'a card: the names ' + (cd?.textContent || ''));
    await w.eval(`abd_setCards('n:${SUB}', false)`);
  } else check(false, 'the cards (docs module) are on');

  // ================= a folder without shares: "Only you"
  w.eval(`go('ablage/${QUIET}')`);
  // 2.1163.0 (#6111): the line says what it means ("Only you see this folder")
  check(await until(() => (d.querySelector('#view .abshline')?.textContent || '').trim() === 'Only you see this folder'), 'a folder without shares: "Only you see this folder"');
  w.close();

  // ================= the receiver
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, CKB);
  w = await boot({user: 'bob', hash: 'ablage'}); d = w.document;
  w.eval(`ab_pick('shared'); AB.key = ''; ab_load()`);
  const br = await until(() => d.querySelector(`.abrow[data-abid="${PROJ}"] .abshby`));
  check(/Shared by Alice Admin/.test(br?.textContent || ''), 'Bob, Shared with me: "Shared by Alice Admin" ' + (br?.textContent || ''));
  check(!d.querySelector(`.abrow[data-abid="${PROJ}"] .abshw`), 'Bob: no names of the shares, no click to Share');
  w.eval(`go('ablage/${SUB}')`);
  check(await until(() => /Shared by Alice Admin/.test(d.querySelector('#view .abshline')?.textContent || '')), 'Bob in the folder: the head says "Shared by Alice Admin"');
  check(!d.querySelector('#view .abshbtn'), 'Bob: no Share button on top');
  await until(() => d.querySelector(`.abrow[data-abid="${FILE}"]`));
  check(!/Carol/.test(d.querySelector('#view').textContent), 'Bob never sees the file\'s other receivers');
  w.close();

  // ================= Firefox: the names sit in the row, a screenshot of the folder
  await firefox(async ({cmd, ev, nav, ctx, shot, until: fu}) => {
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + '#ablage/' + SUB);
    const okRow = await fu(`(() => { const c = document.querySelector('.abrow[data-abid="${FILE}"] .abshw'), r = c && c.closest('.abrow'); if (!c || !r) return false; const a = c.getBoundingClientRect(), b = r.getBoundingClientRect(); return a.width > 20 && a.right <= b.right + 1 && a.left >= b.left - 1; })()`);
    check(okRow, 'Firefox: the names are visible inside the row');
    check(await fu(`!!document.querySelector('#view .abshline') && document.querySelector('#view .abshline').getBoundingClientRect().height > 0`), 'Firefox: the line below the head shows');
    await shot('p2558_4693_folder.png');
  }, false);

  console.log(`p2558_4693_share_names_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); console.log(`p2558_4693_share_names_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
