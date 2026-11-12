// 2.1081.0 (#5907) UI test, own container (start.sh), Firefox with a mouse; invented pages only. Screenshots: P21081A_SHOTS.
// kalmido-suite: fresh
// A folder that has a page of the same name (page "Script" + subpages "Script/…", as an import from SilverBullet leaves them)
// shows ONCE in the folder list and in the panel: as the folder row with the page mark (.wkpgdir), no second row as a page.
// A click opens the folder view: the page's text on top (read, "Edit" opens the page itself), the subpages below. Links
// [[Script]] still open the page; the tree of the narrow view keeps its one row whose name opens the page.
// freelancer-matrix: Wissen (alice has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21081_a_wikidir_ui', check, shots: 'P21081A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21081A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  check(!(st0.me.workspaces || []).length, 'setup: alice has no organisation (a person on her own)');
  const P = {};
  for (const [k, p, b] of [['script', 'Script', 'The script page text about the whole film.'], ['one', 'Script/Scene one', 'Scene one at the harbour.'],
    ['two', 'Script/Scene two', 'Scene two in the train.'], ['loose', 'Loose page', 'See [[Script]] for the scenes.']]) P[k] = (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: b})).id;
  check(Object.values(P).every(Boolean), 'setup: a page with two subpages and a page at the top');

  await firefox(async ({cmd, ev, ctx, nav, shot, until, idle}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    // the rows of the open folder: [name, folder?, page mark?, href]
    const ROWS = `JSON.stringify([...document.querySelectorAll('#view .wkfolder .wkdlist .wkitem')].map(a => [a.textContent.trim(), a.classList.contains('wkdrow'), !!a.querySelector('.wkpgdir'), a.getAttribute('href')]))`;

    // 1) the space's top: "Script" once, as a folder with the page mark; the loose page as a page
    await nav(B + '?w=1280#wiki');
    check(await until(`/Loose page/.test(document.querySelector('#view .wkfolder .wkdlist')?.textContent || '')`, {timeout: 20000}), 'the space\'s top lists its rows');
    await idle();
    let rows = JSON.parse(await ev(ROWS));
    const sc = rows.filter(r => r[0] === 'Script');
    check(sc.length === 1, `#5907 the folder list shows "Script" once (${JSON.stringify(rows)})`);
    check(sc[0] && sc[0][1] && sc[0][2] && /#wiki\/d\/Script$/.test(sc[0][3]), `#5907 "Script" is the folder row with the page mark ${JSON.stringify(sc)}`);
    check(!rows.some(r => r[3] === '#wiki/' + P.script), `#5907 no second row for the page "Script" ${JSON.stringify(rows)}`);
    check(rows.some(r => r[0] === 'Loose page' && !r[1] && !r[2]), `the loose page stays a page row ${JSON.stringify(rows)}`);
    check(await ev(`(document.querySelector('#view .wkfolder .wkpgdir')?.getAttribute('aria-label') || '') === 'Folder with its page'`), 'the page mark is named for screen readers');
    // the panel: one entry "Script" with the mark
    const side = await until(`(() => { const r = [...document.querySelectorAll('#side .sbbtree .sbbtn')].filter(b => b.textContent.trim() === 'Script'); return r.length ? JSON.stringify(r.map(b => !!b.querySelector('.wkpgdir'))) : null; })()`, {timeout: 10000});
    check(side === '[true]', `#5907 the panel shows "Script" once, with the page mark (${side})`);
    await shot('p21081a-top-1280.png');

    // 2) a click on the folder: the page's text on top, the subpages below
    await ev(`(() => { [...document.querySelectorAll('#view .wkfolder .wkdlist a.wkdrow')].find(a => a.textContent.trim() === 'Script').click(); return 1; })()`);
    check(await until(`S.route.wdir === 'Script' && document.querySelector('#view .wkfolder h2')?.textContent.trim() === 'Script'`, {timeout: 10000}), 'the click opens the folder "Script"');
    check(await until(`/The script page text about the whole film/.test(document.querySelector('#view .wkfolder .wkdpage .wkdpmd')?.textContent || '')`, {timeout: 10000}), '#5907 the folder view shows the page\'s text on top');
    rows = JSON.parse(await ev(ROWS));
    check(rows.map(r => r[0]).join('|') === 'Scene one|Scene two', `#5907 the subpages are listed below ${JSON.stringify(rows)}`);
    const order = await ev(`(() => { const a = document.querySelector('#view .wkdpage'), l = document.querySelector('#view .wkfolder .wkdlist'); return !!a && !!l && a.getBoundingClientRect().bottom <= l.getBoundingClientRect().top + 1; })()`);
    check(order, 'the page text stands above the list');
    check(!await ev(`!!document.querySelector('#view .wkfolder .empty')`), 'no "This folder is empty" under a folder with its page');
    await shot('p21081a-folder-1280.png');
    // "Edit" opens the page itself
    await ev(`(() => { document.querySelector('#view .wkdpage .wkdpbar a.btn').click(); return 1; })()`);
    check(await until(`S.route.wid === ${P.script} && document.querySelector('#view .wkpage h2')?.textContent.trim().startsWith('Script')`, {timeout: 10000}), '#5907 "Edit" opens the page "Script"');
    check(await until(`[...document.querySelectorAll('#side .sbbtree .sbbt.on .sbbtn')].some(b => b.textContent.trim() === 'Script')`, {timeout: 10000}), '#5907 the panel marks the folder row "Script" while its page is open');

    // 3) a link [[Script]] still opens the page
    await nav(B + '?w=1280#wiki/' + P.loose);
    // a computer opens the page in its editor: the link is checked in the page's rendered text (the read view, wk_render)
    const href = await until(`WK.pg?.id === ${P.loose} && typeof wem_cut === 'function' && ((wk_render(WK.pg).match(/href="(#wiki\\/\\d+)" class="wklink"/) || [])[1] || null)`, {timeout: 15000});
    check(href === '#wiki/' + P.script, `#5907 the link [[Script]] goes to the page (${href})`);

    // 4) the narrow view's tree: one row whose name opens the page
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 460, height: 860}});
    await nav(B + '?w=460#wiki');
    const tree = await until(`(() => { const a = [...document.querySelectorAll('#wk-res .wktree a.wkitem, #wk-res .wktree .wkdir')].filter(x => x.textContent.trim() === 'Script'); return a.length ? JSON.stringify(a.map(x => x.getAttribute('href'))) : null; })()`, {timeout: 20000});
    check(tree === JSON.stringify(['#wiki/' + P.script]), `the tree keeps one row "Script" that opens the page (${tree})`);
    await shot('p21081a-tree-460.png');
  });

  console.log(`p21081_a_wikidir_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
