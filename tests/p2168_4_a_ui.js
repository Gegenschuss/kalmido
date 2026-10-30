// 2.210 A (#2755) UI tests (own container, start.sh), jsdom: every page of a deep wiki can be reached in the knowledge view.
// The wiki: 7 levels, a folder that is a page too ("Audio" + "Audio/Mix" + deeper), the same folder in other case ("audio/…"),
// umlauts, spaces, a path of about 220 characters, and more than 30 pages (the phone tree starts closed).
// - phone: every folder row has its arrow (.wktog); the arrow of a folder that is a page too opens it without opening the
//   page; with every folder opened by its arrow every page is a link in the tree
// - computer (sidebar B): with every arrow of the panel opened every folder is a row; the folder lists (#wiki/d/<path>)
//   together show every page, each folder its subfolders and its own pages
// - more pages than the index carries: said above the list (.wkcapped), not silently cut
// - the import report names shortened names apart from skipped ones
// freelancer-matrix: wiki (the pages are in the private space of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21684A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const LONG = 'Ein sehr langer Ordnername für Aufnahmen und Notizen';
const PATHS = ['Audio', 'Audio/Mix', 'Audio/Mix/Mastering/Loudness/Targets/Streaming/Spotify', 'audio/Recording/Mics',
  'Claude/Apps/Kalmido/Releases/2.168/Notes/Part A', 'Claude/Apps', 'Privat/Ärzte/Zahnärztin Übersicht', 'Wiki/Leer zeichen/Seite mit Abständen',
  'Wiki/' + [LONG, LONG, LONG, LONG].join('/') + '/Ende', ...Array.from({length: 30}, (_, i) => 'Ablage/Seite ' + i)];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state')).me.id});  // a server with organisations
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'setup: frida has no organisation');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const ids = {};
  for (const p of PATHS) { const r = await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text'}); ids[p] = r.id; if (!r.id) console.log('create', p, r.http, r.error); }
  check(Object.values(ids).every(Boolean), 'setup: every page created (' + Object.values(ids).filter(Boolean).length + ' of ' + PATHS.length + ')');
  const ls = {'tasks.wkSpace': JSON.stringify('private')};

  // ================= phone: the tree
  let w = await boot({user: 'frida', mobile: true, hash: 'wiki', ls}), d = w.document;
  await until(() => typeof w.wk_loadPage === 'function' && w.eval(`(WK.idx.private?.pages || []).length`) === PATHS.length, 60);
  const det = name => [...d.querySelectorAll('#wk-res details')].find(x => x.querySelector(':scope > summary')?.textContent.trim() === name);
  check(await until(() => det('Audio') && !det('Audio').open), 'more than 30 pages: the folders start closed');
  const audio = det('Audio');
  check(audio?.querySelector(':scope > summary > .wktog') && audio.querySelector(':scope > summary > a[href^="#wiki/"]'), 'the folder "Audio" is a page too: its row has the arrow and the page link');
  check([...d.querySelectorAll('#wk-res details > summary')].every(s => s.querySelector(':scope > .wktog')), 'every folder row has its arrow');
  audio.querySelector(':scope > summary > .wktog').click();
  check(await until(() => det('Audio')?.open && w.location.hash === '#wiki'), 'the arrow opens the folder that is a page too, the page stays closed ' + w.location.hash);
  check(await until(() => det('Mix')), 'its subfolder "Mix" (a page too) shows');
  // open every folder by its arrow until none is closed
  for (let round = 0; round < 15; round++) {
    const shut = [...d.querySelectorAll('#wk-res details:not([open]) > summary > .wktog')];
    if (!shut.length) break;
    shut.forEach(t => t.click());
    await sleep(50);
  }
  check(!d.querySelector('#wk-res details:not([open])'), 'every folder opened by its arrow');
  const linked = new Set([...d.querySelectorAll('#wk-res a[href^="#wiki/"]')].map(a => +a.getAttribute('href').split('/')[1]));
  const lost = PATHS.filter(p => !linked.has(ids[p]));
  check(!lost.length, 'phone: every page is a link in the tree; missing: ' + lost.join(' | '));
  check(!det('audio') && det('Recording'), '"audio/…" (other case) is in the folder "Audio", no second folder');
  check(w.location.hash === '#wiki', 'opening folders never opened a page');
  // the index says when it carries fewer pages than the space has
  w.eval(`WK.idx.private.more = true; viewSafeRender()`);
  check(await until(() => /5[.,]?000/.test(d.querySelector('#view .wkcapped')?.textContent || '')), 'more pages than the index carries: a hint names the limit');
  w.eval(`WK.idx.private.more = false; viewSafeRender()`);
  check(await until(() => !d.querySelector('#view .wkcapped')), 'no hint for a complete index');
  // the import report: shortened names apart from skipped ones
  w.eval(`wka_report({created: [1, 2], files_n: 0, skipped: ['x.exe'], skipped_detail: [{name: 'x.exe', reason: 'no'}], skipped_n: 1, shortened: [{name: 'Very/long.md', path: 'Very/lo~abc123~ng'}], shortened_n: 1})`);
  const rep = await until(() => [...d.querySelectorAll('.modal, [role="dialog"]')].find(m => /shortened/.test(m.textContent)));
  check(rep && /1 names shortened/.test(rep.textContent) && /Very\/lo~abc123~ng/.test(rep.textContent) && /1 skipped/.test(rep.textContent), 'the report lists shortened and skipped names apart');
  w.close();

  // ================= computer: the panel and the folder lists
  w = await boot({user: 'frida', hash: 'wiki', ls}); d = w.document;
  await until(() => typeof w.wk_panelHtml === 'function' && w.eval(`(WK.idx.private?.pages || []).length`) === PATHS.length, 60);
  check(await until(() => d.querySelector('#side .sbbtree')), 'the panel shows the folders');
  for (let round = 0; round < 60; round++) {
    const shut = [...d.querySelectorAll('#side [data-act="sbb-tree"]:not([data-open="1"])')];
    if (!shut.length) break;
    shut[0].click();
    await sleep(60);
  }
  const rows = [...d.querySelectorAll('#side .sbbtree .sbbtn')].map(b => b.dataset.go);
  const folders = [...new Set(PATHS.flatMap(p => p.split('/').slice(0, -1).map((_, i, a) => a.slice(0, i + 1).join('/').toLowerCase())))];
  const noRow = folders.filter(f => !rows.some(g => decodeURIComponent(g.replace(/^wiki\/d\//, '')).toLowerCase() === f));
  check(!noRow.length, 'panel: every folder is a row once all arrows are open; missing: ' + noRow.join(' | '));
  // every folder list: its subfolders and its own pages -- together every page
  const seen = new Set();
  for (const f of ['', ...folders]) {
    w.location.hash = f ? '#wiki/d/' + encodeURIComponent(f) : '#wiki';
    await until(() => d.querySelector('#view .wkfolder #wk-res') && (f ? w.eval(`S.route.wdir`) === f : !w.eval(`S.route.wdir`)), 40);
    await sleep(80);
    for (const a of d.querySelectorAll('#view .wkfolder a[href^="#wiki/"]')) { const id = +a.getAttribute('href').split('/')[1]; if (id) seen.add(id); }
    const subs = folders.filter(x => x.startsWith(f ? f + '/' : '') && !x.slice(f ? f.length + 1 : 0).includes('/') && x !== f);
    const shown = [...d.querySelectorAll('#view .wkfolder .wkdrow')].map(a => decodeURIComponent(a.getAttribute('href').replace(/^#wiki\/d\//, '')).toLowerCase());
    check(subs.every(x => shown.includes(x)), `folder list "${f.slice(0, 60)}": every subfolder ${subs.filter(x => !shown.includes(x)).join(' | ')}`);
  }
  const unseen = PATHS.filter(p => !seen.has(ids[p]));
  check(!unseen.length, 'computer: the folder lists together show every page; missing: ' + unseen.join(' | '));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
