// kalmido-suite:
// 2.441.0 UI tests (#3592 favourites of everything as a row in the head bar), own container (start.sh), Firefox (1440 and 900 px
// mouse, 390 px touch). Invented data only. P2441_NOSTART=1 = the container runs.
// Server: the new keys and fav_meta are checked strictly; GET /api/favorites/targets names only what the person may read now
// (no right, in the trash, deleted = "gone", nothing of the target leaves).
// Firefox: the row between the workspace switch and the search, the others keep place and size with and without favourites;
// too many = +N; the star in a page header; "Add to favourites" second in a row's menu; a sidebar row dragged in; a divider, an
// own colour; a favourite of another workspace keeps its dot and switches the workspace; Settings count what is gone.
// A phone: the entries in the sidebar (2.489.0 #4014, before: a row under the header), the page with the pinned tab.
// P4: frida has no organisation: her own office, pages, tables, contacts and files as favourites (freelancer-matrix: tasks)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2441_favs_ui', check, shots: 'P2441_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2441_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const items = async ck => JSON.parse((await call(ck, 'GET', '/api/state')).settings.fav_items || '[]');

(async () => {
  await sleep(600);
  check((await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})})).ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'wiki', 'sheets', 'contacts', 'office', 'files', 'docs']});
  const FE = 'cal,comments,wiki,sheets,contacts,office,files,docs,matrix';
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all', features: FE});
  const ORG = (await call(CA, 'GET', '/api/state')).me.workspaces[0].id;
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  await call(CA, 'POST', '/api/users', {username: 'bert', display_name: 'Bert', password: 'password123', email: 'bert@example.com', orgs: []});
  const CF = await login('frida'), CB = await login('bert');
  for (const ck of [CF, CB]) await call(ck, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all', features: FE});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'frida: no organisation');

  // ================= the server: keys and look
  for (const bad of ['["r:nope:1"]', '["r:wiki:x"]', '["file:x"]', '["sep:"]', '["sv:A B"]']) {
    const r = await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CF}, body: `{"fav_items":${bad}}`});
    check(r.status === 400, 'fav_items: refused ' + bad + ' ' + r.status);
  }
  for (const bad of ['"x"', '{"a":1}', '{"l:1":{"c":"red"}}', '{"l:1":{"i":"<b>"}}', '{"l:1":{"z":"a"}}']) {
    const r = await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CF}, body: `{"fav_meta":${bad}}`});
    check(r.status === 400, 'fav_meta: refused ' + bad + ' ' + r.status);
  }
  const PG = (await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'Shoot day checklist'})).id;
  const SH = (await call(CF, 'POST', '/api/sheets', {title: 'Budget sheet'})).id;
  const BK = (await call(CF, 'GET', '/api/contacts')).books?.[0]?.id;
  const CT = (await call(CF, 'POST', '/api/contacts', {...(BK ? {book_id: BK} : {}), given: 'Petra', family: 'Buyer'})).id;
  const OF = (await call(CF, 'POST', '/api/office/docs', {project_title: 'Image film', items: [{title: 'Edit', qty: 1, rate: 100}]})).id;
  const FD = (await call(CF, 'POST', '/api/files/folders', {name: 'Kiste', space: 'private'})).id;
  check(PG && SH && CT && OF && FD, 'frida has a page, a table, a contact, a quotation, a folder ' + [PG, SH, CT, OF, FD]);
  const KEYS = [`r:wiki:${PG}`, `r:sheet:${SH}`, `r:contact:${CT}`, `r:office_doc:${OF}`, `file:${FD}`, 'sep:7', 'v:today'];
  check((await call(CF, 'PATCH', '/api/settings', {fav_items: KEYS})).http === 200, 'the new keys are stored');
  check((await call(CF, 'PATCH', '/api/settings', {fav_meta: {'v:today': {c: '#1a7f8e', i: 'star'}}})).http === 200, 'a look is stored');
  const T1 = await call(CF, 'GET', '/api/favorites/targets');
  check(Object.keys(T1.items || {}).length === 5 && !T1.gone.length, 'frida reads all five ' + JSON.stringify(T1).slice(0, 300));
  check(T1.items?.[`r:wiki:${PG}`]?.name === 'Shoot day checklist' && T1.items[`r:wiki:${PG}`].to === `wiki/${PG}` && T1.items[`r:wiki:${PG}`].ws === 'private', 'a page: name, route, workspace');
  check(T1.items?.[`r:office_doc:${OF}`]?.ws === 'private', 'her own office counts as Private (P4)');
  check(T1.items?.[`file:${FD}`]?.folder === true && T1.items[`file:${FD}`].to === `ablage/${FD}`, 'a folder of the file store');
  // somebody else's keys: nothing of the target leaves
  await call(CB, 'PATCH', '/api/settings', {fav_items: KEYS});
  const T2 = await call(CB, 'GET', '/api/favorites/targets');
  check(!Object.keys(T2.items || {}).length && T2.gone.length === 5 && !/Shoot|Budget|Petra|Image|Kiste/.test(JSON.stringify(T2)), 'bert gets nothing of frida\'s targets ' + JSON.stringify(T2).slice(0, 200));
  await call(CB, 'PATCH', '/api/settings', {fav_items: []});
  // the trash: gone, back again with the object
  await call(CF, 'POST', '/api/wiki/trash', {ids: [PG]});
  await call(CF, 'DELETE', `/api/sheets/${SH}`);
  await call(CF, 'DELETE', `/api/contacts/${CT}`);
  const T3 = await call(CF, 'GET', '/api/favorites/targets');
  check([`r:wiki:${PG}`, `r:sheet:${SH}`, `r:contact:${CT}`].every(k => T3.gone.includes(k)), 'in the trash = gone ' + JSON.stringify(T3.gone));
  check(!(await items(CF)).includes('x') && (await items(CF)).includes(`r:sheet:${SH}`), 'a gone favourite stays stored');

  // a name that is ciphertext is never shown; a page with a lock stays a favourite of the person who has it (review)
  const LK = (await call(CF, 'POST', '/api/files/folders', {name: 'Soon sealed', space: 'private'})).id;
  const LP = (await call(CF, 'POST', '/api/wiki/pages', {space: 'private', path: 'Soon sealed'})).id;
  execFileSync('python3', ['-c', `import sys, os; sys.path.insert(0, ${JSON.stringify(__dirname)}); import dbx; c = dbx.connect(os.path.join(${JSON.stringify(DATA)}, 'tasks.db'), timeout=10); c.execute("UPDATE wiki_pages SET path='e2e1:sealedpage' WHERE id=${+LP}"); c.execute("UPDATE fs_nodes SET name='e2e1:sealed' WHERE id=${+LK}"); c.commit(); c.close()`], {stdio: 'inherit'});
  check(LK && LP, 'a folder and a page with a ciphertext name ' + [LK, LP]);
  await call(CF, 'PATCH', '/api/settings', {fav_items: [`file:${LK}`, `r:wiki:${LP}`]});
  const T4 = await call(CF, 'GET', '/api/favorites/targets');
  check(T4.items?.[`file:${LK}`]?.name === 'File store' && T4.items?.[`r:wiki:${LP}`]?.name === 'Page' && !/sealed/i.test(JSON.stringify(T4.items)), 'ciphertext names stay out ' + JSON.stringify(T4));
  await call(CB, 'PATCH', '/api/settings', {fav_items: [`r:wiki:${LP}`]});
  check((await call(CB, 'GET', '/api/favorites/targets')).gone?.length === 1, 'somebody else: a locked page stays gone');
  await call(CB, 'PATCH', '/api/settings', {fav_items: []});
  await call(CF, 'PATCH', '/api/settings', {fav_items: KEYS});

  // ================= Firefox
  const PG2 = (await call(CA, 'POST', '/api/wiki/pages', {space: `org:${ORG}`, path: 'Team handbook'})).id;
  const OFA = (await call(CA, 'POST', '/api/office/docs', {project_title: 'Company film'})).id;
  const LS = []; for (let i = 0; i < 40; i++) LS.push((await call(CA, 'POST', '/api/lists', {name: 'List ' + i, org_id: ORG})).id);
  const signIn = async (o, u, hash) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(async () => { localStorage.clear(); sessionStorage.clear(); return (await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})})).status; })()`);
    await o.nav(B + hash);
  };
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const GEO = `(() => { const r = s => { const e = document.querySelector(s), b = e && e.getBoundingClientRect(); return b && [Math.round(b.left), Math.round(b.width)]; }; return JSON.stringify({sw: r('#kbar .kbsw'), sr: r('#kbar .kbsrch'), en: r('#kbar .kbend')}); })()`;
  // an area the organisation's admins switched off: gone while it is off (review)
  await call(CA, 'PATCH', '/api/settings', {fav_items: [`r:wiki:${PG2}`]});
  check(!!(await call(CA, 'GET', '/api/favorites/targets')).items?.[`r:wiki:${PG2}`], 'a page of the organisation');
  await call(CA, 'PATCH', `/api/orgs/${ORG}`, {areas_off: ['wiki']});
  check((await call(CA, 'GET', '/api/favorites/targets')).gone?.includes(`r:wiki:${PG2}`), 'its area switched off: gone');
  await call(CA, 'PATCH', `/api/orgs/${ORG}`, {areas_off: []});
  await call(CA, 'PATCH', '/api/settings', {fav_items: [], fav_lists: ''});
  await firefox(async o => {
    const {ev, cmd, ctx, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await signIn(o, 'alice', '#today');
    check(await ready(ev, `!!document.querySelector('#kbar .fv2bar')`), 'the row is in the head bar');
    await sleep(500);
    const g0 = await ev(GEO);
    await call(CA, 'PATCH', '/api/settings', {fav_items: ['v:today', `r:wiki:${PG2}`, `r:office_doc:${OFA}`, 'sep:1', 'm:matrix', `l:${LS[0]}`], fav_lists: String(LS[0])});
    await signIn(o, 'alice', '#today');
    check(await ready(ev, `document.querySelectorAll('#kbar .fv2-tile').length === 5`), 'five favourites drawn, of every kind');
    await sleep(300);
    const g1 = await ev(GEO);
    check(g0 === g1, 'the head bar keeps place and size of everything else ' + g0 + ' / ' + g1);
    const m = JSON.parse(await ev(`(() => { const t = document.querySelector('#kbar .fv2-tile[data-fv2="v:today"]').getBoundingClientRect(), b = document.querySelector('#kbar .fv2bar').getBoundingClientRect(), a = document.querySelector('#kbar .kbsw').getBoundingClientRect(), s = document.querySelector('#kbar .kbsrch').getBoundingClientRect(); return JSON.stringify({left: b.left >= a.right - 1, right: b.right <= s.left + 9, sq: Math.abs(t.width - t.height) < 1, sep: !!document.querySelector('#kbar .fv2-sep'), side: !!document.querySelector('#side .fv2-tile')}); })()`));
    check(m.left && m.right, 'the row lies between the switch and the search ' + JSON.stringify(m));
    check(m.sq && m.sep && !m.side, 'symbols, a divider, none in the sidebar any more ' + JSON.stringify(m));
    const hint = await ev(`document.querySelector('#kbar .fv2-tile[data-fv2="r:wiki:${PG2}"]').title`);
    check(/Team handbook/.test(hint) && /Page/.test(hint), 'the hint has the name and the place ' + hint);
    check(await ev(`!!document.querySelector('#kbar .fv2-tile[data-fv2="r:wiki:${PG2}"] .wsp-dot')`), 'a dot shows the workspace');
    await shot('p2441-bar.png');
    // an object opens (the office follows the workspace)
    await ev(`(() => { document.querySelector('#kbar .fv2-tile[data-fv2="r:office_doc:${OFA}"]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/offers/${OFA}'`), 'a favourite opens its object ' + await ev('location.hash'));
    // the star in a header
    await ev(`(() => { go('wiki'); return 1; })()`);
    check(await ready(ev, `S.route.mod === 'wiki' && !!document.querySelector('#top [data-fv2-star]')`), 'a star in the header of an area');
    await ev(`(() => { document.querySelector('#top [data-fv2-star]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#kbar .fv2-tile[data-fv2="m:wiki"]')`), 'the star adds the area to the row');
    // second in the menu
    const second = await ev(`(() => { const it = listMenuItems(${LS[1]}).filter(x => x !== '-' && x.label); return JSON.stringify(it.slice(0, 3).map(x => x.label)); })()`);
    check(/favourites/.test(JSON.parse(second)[0]) || /favourites/.test(JSON.parse(second)[1]), 'Add to favourites stands at the top of a list menu ' + second);
    // a sidebar row dragged into the row
    await ev(`(() => { go('today'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#side .srow[data-list="${LS[2]}"]')`), 'the row of a list');
    const dr = await ev(`(async () => { const a = document.querySelector('#side .srow[data-list="${LS[2]}"]'), bar = document.querySelector('#kbar .fv2bar'), r = bar.getBoundingClientRect(), dt = new DataTransfer(), x = r.right - 12, y = r.top + r.height / 2;
      const fire = (type, el, cx, cy) => el.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, clientX: cx, clientY: cy, dataTransfer: dt}));
      fire('dragstart', a, 0, 0); const mark = bar.classList.contains('fv2-drop'), add = FV2.add; fire('dragover', bar, x, y); const conn = bar.isConnected, seen = FV2.add; fire('drop', bar, x, y); const after = FV2.add; fire('dragend', a, 0, 0); return JSON.stringify({mark, add, conn, seen, after}); })()`);
    check(JSON.parse(dr).mark, 'the row marks itself while something is dragged ' + dr);
    check(await ready(ev, `!!document.querySelector('#kbar .fv2-tile[data-fv2="l:${LS[2]}"]') && favIs(${LS[2]})`), 'dropped: it is a favourite ' + dr + ' ' + await ev('fv2_stored().join() + " | " + S.settings.fav_lists'));
    // the look
    await call(CA, 'PATCH', '/api/settings', {fav_meta: {'v:waiting': {c: '#1a7f8e'}}});
    await ev(`(() => { S.settings.fav_meta = JSON.stringify({'v:waiting': {c: '#1a7f8e'}}); fv2_metaSet('v:today', {c: '#c2410c'}); return 1; })()`);
    check(await ready(ev, `/--fvc/.test(document.querySelector('#kbar .fv2-tile[data-fv2="v:today"]').getAttribute('style') || '')`), 'an own colour is drawn');
    await sleep(400);
    check(!/v:waiting/.test((await call(CA, 'GET', '/api/state')).settings.fav_meta || ''), 'the look of what left the row goes with it (review)');
    // +N: too many for the room; nothing else moves
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 900, height: 800}});
    await sleep(300);
    const g2 = await ev(GEO);
    await call(CA, 'PATCH', '/api/settings', {fav_items: ['v:today', ...LS.map(l => 'l:' + l)], fav_lists: LS.join(',')});
    await signIn(o, 'alice', '#today');
    check(await ready(ev, `!document.querySelector('#kbar .fv2-more').hidden`), '+N appears when the row is full');
    await sleep(300);
    const fit = JSON.parse(await ev(`(() => { const b = document.querySelector('#kbar .fv2bar'), m = b.querySelector('.fv2-more'), vis = [...b.querySelectorAll('.fv2-tile')].filter(x => !x.hidden), hid = [...b.querySelectorAll('.fv2-tile')].filter(x => x.hidden); return JSON.stringify({text: m.textContent, vis: vis.length, hid: hid.length, in: m.getBoundingClientRect().right <= b.getBoundingClientRect().right + 1}); })()`));
    check(fit.vis > 0 && fit.text === '+' + fit.hid && fit.in, '+N counts what is hidden and stays inside the row ' + JSON.stringify(fit));
    check(await ev(GEO) === g2, 'the others do not shrink: ' + g2 + ' / ' + await ev(GEO));
    await ev(`(() => { document.querySelector('#kbar .fv2-more').click(); return 1; })()`);
    // 2.521.0 (#4396): the +N menu ends with "Only favourites" (it moved out of the sidebar), so the rest is one item less
    check(await ready(ev, `document.querySelectorAll('.menu-list [role="menuitem"]').length === ${fit.hid} + 1`), '+N lists the rest (and Only favourites)');
    await shot('p2441-more.png');
  }, false);
  // frida: no organisation; a gone favourite is counted
  await firefox(async o => {
    const {ev, cmd, ctx} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await signIn(o, 'frida', '#today');
    check(await ready(ev, `document.querySelectorAll('#kbar .fv2-tile[data-fv2^="r:"], #kbar .fv2-tile[data-fv2^="file:"]').length >= 2`), 'frida: her objects in the row');
    check(await ready(ev, `FV2.gone.length >= 2 && fv2_goneKeys().length === FV2.gone.length`), 'frida: the gone ones are known ' + await ev('FV2.gone.join()'));
    check(!(await ev(`!!document.querySelector('#kbar .fv2-tile .wsp-dot')`)), 'frida: no workspace dot without workspaces');
    const html = await ev(`lc_favGoneHtml()`);
    check(/no longer available/.test(html), 'Settings count them ' + html);
  }, false);
  // a phone
  // 2.489.0 (#4014): a phone has no head bar: no row of its own over the header any more, the favourites are entries of the
  // sidebar's section "Favourites" (symbol, name, number); a computer keeps the row; turning between the two draws again
  const FL = (await call(CF, 'POST', '/api/lists', {name: 'Shoot prep'})).id;
  for (const t of ['Book the van', 'Call the gaffer']) await call(CF, 'POST', '/api/tasks', {list_id: FL, title: t});
  await call(CF, 'PUT', `/api/lists/${FL}/favorite`, {on: true});
  await call(CF, 'PATCH', '/api/settings', {fav_items: ['v:today', `r:office_doc:${OF}`, `file:${FD}`, `l:${FL}`]});
  await firefox(async o => {
    const {ev, cmd, ctx, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 760}});
    await signIn(o, 'frida', '#today');
    const SIDE = `[...document.querySelectorAll('#side .sg-favs .fv2side .fv2-row')]`;
    check(await ready(ev, `${SIDE}.length === 4`), 'phone: four entries under "Favourites" in the sidebar ' + await ev(`${SIDE}.map(x => x.dataset.fv2).join()`));
    check(!(await ev(`!!document.querySelector('#favrow, .fv2bar:not(.fv2-page) .fv2-tile')`)), 'phone: no row of tiles over the page');
    const e = JSON.parse(await ev(`(() => { const r = k => document.querySelector('#side .fv2side .fv2-row[data-fv2="' + k + '"]'); return JSON.stringify({names: ${SIDE}.map(x => x.querySelector('.n')?.textContent).join('|'), icon: !!r('v:today')?.querySelector('.fv2-ri svg'), n: r('l:${FL}')?.querySelector('.c')?.textContent, on: r('v:today')?.classList.contains('on')}); })()`));
    check(/Today/.test(e.names) && /Image film|Quotation/.test(e.names) && /Shoot prep/.test(e.names) && e.icon, 'phone: symbol and name ' + JSON.stringify(e));
    check(e.n === '2', 'phone: the list counts its open tasks ' + JSON.stringify(e));
    check(e.on, 'phone: the open view is marked');
    check(/nunread[^>]*>2</.test(await ev(`(() => { const a = S.agents; S.agents = [{id: 991, waiting: 1, chat_unread: 1}]; const h = fv2_sideN('a:991'); S.agents = a; return h; })()`)), 'phone: what is unread keeps its marked number');
    await ev(`(() => { sideOpenDrawer(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#side.open')`);
    await shot('p2441-phone.png');
    await ev(`(() => { document.querySelector('#side .fv2side .fv2-row[data-fv2="l:${FL}"]').click(); return 1; })()`);
    check(await ready(ev, `S.route.key === 'l:${FL}' && !document.querySelector('#side.open')`), 'phone: an entry opens its target and closes the drawer');
    // turning: wide = the row in the head bar, no entries; narrow again = the entries
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1024, height: 760}});
    check(await ready(ev, `document.querySelectorAll('#kbar .fv2bar .fv2-tile').length === 4 && !document.querySelector('#side .fv2side')`), 'wide: the row in the head bar, no entries in the sidebar');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 760}});
    check(await ready(ev, `${SIDE}.length === 4 && !document.querySelector('#kbar .fv2bar .fv2-tile')`), 'narrow again: the entries are back');
    check(await ev(`topMoreItems().some(x => /favourites/.test(x.label || ''))`), 'phone: the star of a page is in "…"');
    await shot('p2441-phone.png');
    await ev(`(() => { nav_pref('tabbar').order.push('favs'); S.settings.nav_menus = S.settings.nav_menus || '{}'; LS.set('tabbar', [...tabIds(), 'favs']); render(); go('favorites'); return 1; })()`);
    check(await ready(ev, `S.route.key === 'favorites' && document.querySelectorAll('#view .fv2-page .fv2-tile').length === 4`), 'phone: the page lists them');
    check(/Image film|Quotation/.test(await ev(`document.querySelector('#view .fv2-page').textContent`)), 'phone: names on the page');
    await shot('p2441-page.png');
  }, true);

  console.log(`${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(1); });
