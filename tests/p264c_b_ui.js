// 2.64.3 part B (#1817): the lock per knowledge space -- client (static/js/wikie2e.js + hooks in wiki.js), own container
// (start.sh), Firefox (real WebCrypto). An organisation space with two people:
// - Alice switches it on (wkeStart, Bob gets his key), the server keeps ciphers only (path and text), its search finds nothing
// - local: the index opens paths and texts, search, backlinks and "mentioned in" run in the browser; a name taken is refused
//   here; a template's text is copied here; rename changes the [[links]] in the other pages; a folder moves page by page
// - export = a ZIP made in the browser with the plain names; import = a ZIP read in the browser (paths cleaned, non-.md skipped)
// - Bob reads with his own key; Carol joins -> waiting list -> Alice releases -> Carol reads; Carol leaves -> key change ->
//   every page in the new generation; Alice switches it off -> plain texts on the server again
// - H1: no localStorage entry holds a plain text; lock = the decrypted pages leave the page
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p264c_b_ui', check, shots: 'P264CB_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.BASE) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, j: await r.json().catch(() => ({}))}; };
const PASS = {alice: 'correct horse battery staple', bob: 'another horse battery staple', carol: 'third horse battery staple'};
const M = 'ZQWmark';  // every plain text of the encrypted space carries it
const gens = idx => (idx.pages || []).flatMap(p => [p.path, p.body]).filter(v => typeof v === 'string' && v.startsWith('e2e1:')).map(v => JSON.parse(v.slice(5)).g);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const feats = async ck => { const st = (await call('GET', '/api/state', null, ck)).j; await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...(st.settings?.features || '').split(',').filter(Boolean), 'wiki', 'collab'].join(',')}, ck); };
  await feats(CK);
  const ME = (await call('GET', '/api/state')).j.me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: ME})).j.id;
  const SP = 'org:' + ORG;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).j.id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'})).j.id;
  check((await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'})).status < 300, 'setup: Bob in the organisation');
  const CKB = await login('bob'), CKC = await login('carol');
  await feats(CKB); await feats(CKC);
  const T = (await call('POST', '/api/tasks', {title: 'Task for the mention'})).j.id;
  const mk = async (p, body) => (await call('POST', '/api/wiki/pages', {space: SP, path: p, body})).j.id;
  const START = await mk('Docs/Start', `${M} start page, see [[Docs/Other]] and #${T}`);
  const OTHER = await mk('Docs/Other', `${M} other page`);
  const TPL = await mk('Templates/Meeting', `${M} template text`);
  check(START > 0 && OTHER > 0 && TPL > 0, 'setup: three pages in the organisation space');
  const hasA = (await call('GET', '/api/wiki/e2e?space=' + SP)).status === 200;
  check(hasA, 'the server has the lock routes of the knowledge pages (part A)');
  if (!hasA) { console.log(`p264c_b_ui: ${ok} passed, ${F.length} failed`); process.exit(1); }

  const session = (user, fn) => firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const waitFor = async (expr, n = 80) => { for (let i = 0; i < n; i++) { const v = await ev(expr).catch(() => null); if (v) return v; await sleep(250); } return null; };
    const boot = async hash => { await nav(B + 'static/icon.svg'); await nav(B + hash); await waitFor('!!(window.S && S.booted)'); await sleep(500); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.wkSpace', ${JSON.stringify(JSON.stringify(SP))}); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox: login ${user}`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await boot('#inbox');
    const sweep = () => ev(`Object.keys(localStorage).filter(k => (localStorage.getItem(k) || '').includes('${M}')).join(',')`);
    const unlock = () => ev(`(async () => { await e2eLoad(true); if (!E2E.st.set) return !!(await e2eCreate(${JSON.stringify(PASS[user])})); await e2eAdopt(await e2eUnwrapPass(E2E.st.bundle_pass, ${JSON.stringify(PASS[user])})); return e2eUnlocked(); })()`);
    await fn({ev, waitFor, boot, shot, sweep, unlock});
  }, false);

  // ---------------------------------------------------------------- Bob sets up his encryption, Alice switches the space on
  await session('bob', async ({unlock}) => { check(await unlock(), 'Bob sets up encryption'); });
  await session('alice', async ({ev, waitFor, boot, shot, sweep, unlock}) => {
    check(await unlock(), 'Alice sets up encryption');
    const pr = await ev(`(async () => { const p = []; const r = await wkeStart(${JSON.stringify(SP)}, x => p.push(x)); return {r, p, mode: wkeMode(${JSON.stringify(SP)}), ready: wkeReady(${JSON.stringify(SP)})}; })().catch(e => ({err: e.message}))`);
    check(pr.r === true && pr.mode === 'on' && pr.ready, 'wkeStart: the space is encrypted ' + JSON.stringify(pr).slice(0, 300));
    const p = pr.p || [];
    check(p.length && p[p.length - 1].done === p[p.length - 1].total && p[p.length - 1].total >= 3, 'wkeStart: progress up to the last page ' + JSON.stringify(p));
    let idx = (await call('GET', '/api/wiki?space=' + SP + '&bodies=1')).j;
    check(idx.e2e?.mode === 'on' && (idx.pages || []).length === 3 && idx.pages.every(x => x.path.startsWith('e2e1:') && x.body.startsWith('e2e1:')) && !JSON.stringify(idx).includes(M),
      'the server keeps ciphers only: path and text of every page');
    const sr = (await call('GET', '/api/wiki/search?q=' + M)).j;
    check(!(sr.pages || []).length, 'the server search finds nothing in the encrypted space');
    const info = (await call('GET', '/api/wiki/e2e?space=' + SP)).j;
    check((info.members || []).find(m => m.user_id === BOB)?.key_gens?.includes(1), 'Bob got his key at the start');

    // local: index, search, backlinks, mentions
    const loc = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; await wk_load(sp, true); const ps = wk_pages(sp);
      const other = await wkePage(await rawFetch('GET', '/api/wiki/pages/${OTHER}'));
      return {paths: ps.map(x => x.path), search: wkeSearch('${M} start').map(x => x.id), wks: (await wk_search('${M} other')).map(x => x.id),
        back: (other.backlinks || []).map(x => x.id), men: (await wkeMentions(${T})).map(x => x.id), tpl: ps.find(x => x.id === ${TPL})?.template, body: other.body}; })()`);
    check(JSON.stringify(loc.paths) === JSON.stringify(['Docs/Other', 'Docs/Start', 'Templates/Meeting']), 'the index opens and sorts the paths ' + JSON.stringify(loc.paths));
    check(loc.body === `${M} other page`, 'a page opens with the space key');
    check(loc.search?.includes(START) && loc.wks?.includes(OTHER), 'local search: the pages of the unlocked space are found ' + JSON.stringify([loc.search, loc.wks]));
    check(loc.back?.includes(START), 'backlinks computed in the browser ' + JSON.stringify(loc.back));
    check(loc.men?.includes(START), '"mentioned in" computed in the browser ' + JSON.stringify(loc.men));
    check(loc.tpl === true, 'the template flag from the plain path');

    // writing: a new page, a name taken, a template, rename with links, a folder
    const NEW = await ev(`wkeCreate(${JSON.stringify(SP)}, 'Docs/New', 0, '${M} new [[Docs/Other|the other]]').then(r => r.id, e => 'ERR ' + e.message)`);
    check(NEW > 0, 'a new page in the encrypted space ' + NEW);
    await ev(`wk_load(${JSON.stringify(SP)}, true).then(() => 1)`);
    check(await ev(`wkeCreate(${JSON.stringify(SP)}, ' docs/NEW ', 0, 'x').then(() => 'made', e => e.code)`) === 'wiki_taken', 'a name taken is refused in the browser');
    const FT = await ev(`wkeCreate(${JSON.stringify(SP)}, 'From template', ${TPL}).then(r => r.id + '|' + r.body, e => 'ERR ' + e.message)`);
    check(String(FT).endsWith(`|${M} template text`), 'a template\'s text is copied in the browser ' + FT);
    check((await call('POST', '/api/wiki/pages', {space: SP, path: 'Plain', body: 'plain'})).status === 409, 'the server refuses a plain page in the encrypted space');
    await ev(`wk_load(${JSON.stringify(SP)}, true).then(() => 1)`);
    const rn = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; const p = wk_pages(sp).find(x => x.id === ${OTHER});
      const r = await wkeRename(p, 'Docs/Renamed'); await wk_load(sp, true);
      const st = await wkePage(await rawFetch('GET', '/api/wiki/pages/${START}')), nw = await wkePage(await rawFetch('GET', '/api/wiki/pages/' + ${NEW}));
      return {n: r.relinked, path: r.path, st: st.body, nw: nw.body}; })().catch(e => ({err: e.message}))`);
    check(rn.path === 'Docs/Renamed' && rn.n === 2 && rn.st.includes('[[Docs/Renamed]]') && rn.nw.includes('[[Docs/Renamed|the other]]'), 'rename changes the [[links]] in the other pages ' + JSON.stringify(rn).slice(0, 300));
    const mv = await ev(`wkeMove(${JSON.stringify(SP)}, 'Docs', 'Notes').then(async r => { await wk_load(${JSON.stringify(SP)}, true); return {n: r.moved.length, paths: wk_pages(${JSON.stringify(SP)}).map(x => x.path)}; }, e => ({err: e.message}))`);
    check(mv.n === 3 && mv.paths.includes('Notes/Start') && mv.paths.includes('Notes/Renamed') && !mv.paths.some(x => x.startsWith('Docs/')), 'a folder is renamed page by page ' + JSON.stringify(mv));
    idx = (await call('GET', '/api/wiki?space=' + SP + '&bodies=1')).j;
    check(idx.pages.every(x => x.path.startsWith('e2e1:')) && !JSON.stringify(idx).includes(M) && !JSON.stringify(idx).includes('Notes'), 'after the changes: still ciphers only');

    // export / import in the browser
    const ex = await ev(`(async () => { let blob = null; const s0 = wkeSave; wkeSave = b => { blob = b; };
      try { await wkeExport(${JSON.stringify(SP)}); } finally { wkeSave = s0; }
      const es = wkeUnzip(new Uint8Array(await blob.arrayBuffer())), td = new TextDecoder();
      return es.map(x => x.name + '=' + td.decode(x.data()).slice(0, 40)); })().catch(e => ['ERR ' + e.message])`);
    check(ex.some(x => x.startsWith(`Notes/Start.md=${M} start page`)) && ex.some(x => x.startsWith('Templates/Meeting.md=')), 'export: a ZIP of the decrypted .md files with the plain names ' + JSON.stringify(ex).slice(0, 300));
    const im = await ev(`(async () => { const te = new TextEncoder();
      const z = wkeZip([{name: 'Imp/One.md', data: te.encode('${M} imported one')}, {name: ' Sub / Two [x].md', data: te.encode('${M} two')}, {name: '../evil/Three.md', data: te.encode('x')}, {name: 'notes.txt', data: te.encode('x')}, {name: 'notes/start.md', data: te.encode('dup')}]);
      const r = await wkeImport(${JSON.stringify(SP)}, new File([z], 'w.zip', {type: 'application/zip'}));
      await wk_load(${JSON.stringify(SP)}, true);
      const cs = new Blob([te.encode('${M} deflated')]).stream().pipeThrough(new CompressionStream('deflate-raw'));
      const inf = new TextDecoder().decode(await wkeInflate(new Uint8Array(await new Response(cs).arrayBuffer())));
      return {c: r.created.length, s: r.skipped, paths: wk_pages(${JSON.stringify(SP)}).map(x => x.path), inf}; })().catch(e => ({err: e.message}))`);
    check(im.c === 2 && im.paths?.includes('Imp/One') && im.paths?.includes('Sub/Two x') && im.s?.includes('../evil/Three.md') && im.s?.includes('notes.txt') && im.s?.includes('notes/start.md'), 'import: .md files created encrypted, paths cleaned, others / taken names skipped ' + JSON.stringify(im).slice(0, 300));
    check(im.inf === `${M} deflated`, 'import: deflate entries open with DecompressionStream');
    idx = (await call('GET', '/api/wiki?space=' + SP + '&bodies=1')).j;
    check(!JSON.stringify(idx).includes(M) && !JSON.stringify(idx).includes('Sub/'), 'the imported pages are ciphers on the server');

    // the view: lock mark, tree, dialog
    await boot('#wiki');
    await unlock();  // the keys of this device: the passphrase again after the reload
    check(await waitFor(`!!document.querySelector('#view .wkemark')`), 'the view: lock mark at the space ' + await ev(`(document.querySelector('#view')?.innerHTML || '').slice(0, 300)`));
    await ev(`(document.querySelector('#view [data-wke="unlock"]')?.click(), 1)`);  // the lock box: "Unlock"
    check(await waitFor(`[...document.querySelectorAll('#view .wkitem')].some(a => a.textContent.includes('Start'))`), 'the view: the decrypted tree after "Unlock" ' + await ev(`(document.querySelector('#wk-res')?.textContent || '').slice(0, 200)`));
    await ev(`(wkeDlg(${JSON.stringify(SP)}), 1)`);
    check(await waitFor(`(document.querySelector('.wkedlg')?.textContent || '').includes('Bob')`), 'the dialog "Encryption…" lists the members with their key state');
    await shot('dialog');
    await ev(`(document.querySelector('.cdlg [data-cd="yes"]')?.click(), 1)`);
    check(!(await sweep()), 'H1: no localStorage entry holds a plain text of the space ' + await sweep());
    check(await ev(`(e2eLock(), !WKE.memo.size && !Object.keys(WKE.keys).length && !(WK.idx[${JSON.stringify(SP)}]?.pages || []).some(p => p.path) && !JSON.stringify(HIST.undo).includes('Notes'))`), 'lock: the decrypted pages and keys leave the page');
  });

  // ---------------------------------------------------------------- Bob reads with his own key
  await session('bob', async ({ev, unlock}) => {
    await unlock();
    const b = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; await wk_load(sp, true); const p = await wkePage(await rawFetch('GET', '/api/wiki/pages/${START}')); return {paths: wk_pages(sp).map(x => x.path), body: p.body}; })().catch(e => ({err: e.message}))`);
    check(b.paths?.includes('Notes/Start') && b.body?.startsWith(`${M} start page`), 'Bob reads the pages with his own key ' + JSON.stringify(b).slice(0, 200));
  });

  // ---------------------------------------------------------------- Carol joins: waiting list, release, she reads
  await session('carol', async ({ev, unlock}) => { check(await unlock(), 'Carol sets up encryption'); });
  check((await call('PUT', `/api/orgs/${ORG}/members`, {email: 'carol@example.com', role: 'member'})).status < 300, 'Carol joins the organisation');
  await session('carol', async ({ev, unlock}) => {
    await unlock();
    const c = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; await wk_load(sp, true); return {mine: WKE.st[sp]?.mine, n: wk_pages(sp).length, lock: wkeLockHtml(sp)}; })().catch(e => ({err: e.message}))`);
    check(c.mine === false && c.n === 0 && /Key pending/.test(c.lock || ''), 'Carol waits for the key: placeholder "Key pending" ' + JSON.stringify(c).slice(0, 200));
  });
  await session('alice', async ({ev, unlock}) => {
    await unlock();
    const w = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; await wk_load(sp, true); const i = await wkeInfo(sp, true); return {pending: i.pending.map(p => p.user_id), bar: wkeBarHtml(sp), n: await wkeReleaseAll(sp)}; })().catch(e => ({err: e.message}))`);
    check(w.pending?.includes(CAROL) && /waiting for the key/.test(w.bar || '') && w.n === 1, 'Alice sees the waiting person and releases the key ' + JSON.stringify(w).slice(0, 300));
  });
  const news = (await call('GET', '/api/news', null, CKC)).j;
  check(JSON.stringify(news).includes('wiki_e2e_key'), 'Carol gets the news entry about the released key');
  await session('carol', async ({ev, unlock}) => {
    await unlock();
    const c = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; await wk_load(sp, true); const p = await wkePage(await rawFetch('GET', '/api/wiki/pages/${START}')); return p.body; })().catch(e => 'ERR ' + e.message)`);
    check(String(c).startsWith(`${M} start page`), 'Carol reads after the release ' + String(c).slice(0, 80));
  });

  // ---------------------------------------------------------------- Carol leaves: key change, every page in generation 2
  check((await call('DELETE', `/api/orgs/${ORG}/members/${CAROL}`)).status < 300, 'Carol leaves the organisation');
  check(((await call('GET', '/api/wiki/e2e?space=' + SP)).j.rotate || 0) > 0, 'the space shows "key change pending"');
  await session('alice', async ({ev, unlock}) => {
    await unlock();
    const k = await ev(`(async () => { const sp = ${JSON.stringify(SP)}; await wk_load(sp, true); const r = await wkeRotate(sp, true); const e = await wkeReenc(sp); return {r, e, gen: WKE.st[sp].gen}; })().catch(e => ({err: e.message}))`);
    check(k.r === true && k.e === true && k.gen === 2, 'the key changes and the pages are encrypted again ' + JSON.stringify(k));
    const idx = (await call('GET', '/api/wiki?space=' + SP + '&bodies=1')).j, g = gens(idx);
    check(g.length >= 12 && g.every(x => x === 2), 'every path and text in the new generation ' + JSON.stringify([...new Set(g)]));
    const i = (await call('GET', '/api/wiki/e2e?space=' + SP)).j;
    check(!(i.members || []).some(m => m.user_id === CAROL) && !i.rotate && !i.reenc, 'Carol is no member any more, nothing pending');

    // switching off: plain texts on the server again
    const off = await ev(`wkeStop(${JSON.stringify(SP)}, 'password123', () => {}).then(r => ({r, on: wkeOn(${JSON.stringify(SP)})}), e => ({err: e.message}))`);
    check(off.r === true && off.on === false, 'wkeStop: switched off ' + JSON.stringify(off));
  });
  const idx = (await call('GET', '/api/wiki?space=' + SP)).j;
  check(!idx.e2e && idx.pages.some(x => x.path === 'Notes/Start') && idx.pages.every(x => !x.path.startsWith('e2e1:')), 'the paths are plain on the server again');
  const pg = (await call('GET', '/api/wiki/pages/' + START)).j;
  check(pg.body?.startsWith(`${M} start page`) && (pg.backlinks || []).length >= 0, 'the text is plain on the server again');
  check(((await call('GET', '/api/wiki/search?q=' + M)).j.pages || []).length >= 3, 'the server search finds the pages again');

  console.log(`p264c_b_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
