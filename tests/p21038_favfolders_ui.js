// 2.1038.0 UI tests (Firefox, a computer, 1440 px), fresh DB, a person WITHOUT an organisation (P4, freelancer-matrix: tasks):
// - #5809: folders are really DRAGGED into the favourites row (not the star): a project folder of the sidebar (its tree stopped the
//   dragstart before the row saw it), a folder of the file store from the sidebar's tree and as a row of the open folder
// - #5811: the menu of a folder tile (right click) shows the folder's content on top and a click opens the entry: a project folder
//   (its projects in the sidebar's order, no archived one, then its subfolders), a folder of the file store (subfolders, then
//   files; "Loading…" first), an empty folder says so, more than ten entries end with "Show all" (opens the folder)
// kalmido-suite: fresh
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21038_favfolders_ui', check, shots: 'P21038_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const favs = async () => JSON.parse((await call('GET', '/api/state')).settings.fav_items || '[]');

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', workspace: 'all', features: 'files,docs'});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'alice has no organisation (P4)');
  // projects: "Clients" with two projects, an archived one and a subfolder; "Many" with twelve
  const NORD = (await call('POST', '/api/lists', {name: 'North client', folder: 'Clients'})).id;
  const SUED = (await call('POST', '/api/lists', {name: 'South client', folder: 'Clients'})).id;
  const OLD = (await call('POST', '/api/lists', {name: 'Old client', folder: 'Clients'})).id;
  await call('PATCH', `/api/lists/${OLD}`, {archived: true});
  await call('POST', '/api/lists', {name: 'Sub project', folder: 'Clients/Abroad'});
  for (let i = 1; i <= 12; i++) await call('POST', '/api/lists', {name: 'Many ' + i, folder: 'Many'});
  // the file store: Top > Box (> Receipts, Letters), Top > Hollow (empty)
  const TOP = (await call('POST', '/api/files/folders', {name: 'Top', space: 'private'})).id;
  const BOX = (await call('POST', '/api/files/folders', {name: 'Box', parent_id: TOP})).id;
  const HOLLOW = (await call('POST', '/api/files/folders', {name: 'Hollow', parent_id: TOP})).id;
  const REC = (await call('POST', '/api/files/folders', {name: 'Receipts', parent_id: BOX})).id;
  await call('POST', '/api/files/folders', {name: 'Letters', parent_id: BOX});
  check(NORD && SUED && TOP && BOX && HOLLOW && REC, 'the data ' + [NORD, SUED, TOP, BOX, HOLLOW, REC]);
  await call('PATCH', '/api/settings', {fav_items: ['v:today']});

  const signIn = async (o, hash) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(async () => { localStorage.clear(); sessionStorage.clear(); return (await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})})).status; })()`);
    await sleep(400);
    await o.nav(B + hash);
  };
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { if (await fn()) return true; await sleep(250); } return false; };
  // a real drag of the element `sel` onto the end of the row: dragstart on the element, dragover / drop on the bar, dragend
  const DRAG = sel => `(() => { const a = document.querySelector(${JSON.stringify(sel)}), bar = document.querySelector('#kbar .fv2bar'); if (!a || !bar) return JSON.stringify({miss: !a ? 'source' : 'bar'});
    const r = bar.getBoundingClientRect(), dt = new DataTransfer(), x = r.right - 12, y = r.top + r.height / 2;
    const fire = (type, el, cx, cy) => el.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, clientX: cx, clientY: cy, dataTransfer: dt}));
    fire('dragstart', a, 0, 0); const add = FV2.add, mark = bar.classList.contains('fv2-drop'); fire('dragover', bar, x, y); fire('drop', bar, x, y); fire('dragend', a, 0, 0);
    return JSON.stringify({add, mark}); })()`;
  // the content rows of the open menu (#5811) and all its labels
  const MENU = `JSON.stringify({kids: [...document.querySelectorAll('#pop .menu-list [data-act="fv2-kid"] .ml')].map(x => x.textContent), all: [...document.querySelectorAll('#pop .menu-list [role="menuitem"] .ml')].map(x => x.textContent)})`;
  const openMenu = key => `(() => { const t = document.querySelector('#kbar .fv2-tile[data-fv2=${JSON.stringify(key)}]'); if (!t) return false; const r = t.getBoundingClientRect(); t.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true, clientX: r.left + 4, clientY: r.top + 4})); return true; })()`;
  const clickKid = label => `(() => { const b = [...document.querySelectorAll('#pop .menu-list [role="menuitem"]')].find(x => x.querySelector('.ml')?.textContent === ${JSON.stringify(label)}); if (!b) return false; b.click(); return true; })()`;

  await firefox(async o => {
    const {ev, cmd, ctx, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await signIn(o, '#today');
    check(await ready(ev, `!!document.querySelector('#kbar .fv2bar') && !!document.querySelector('#side .fhead[data-folder="Clients"]')`), 'the row and the project folder are drawn');

    // ======== #5809: a project folder dragged into the row
    const d1 = JSON.parse(await ev(DRAG('#side .fhead[data-folder="Clients"]')));
    check(d1.add === 'folder:Clients' && d1.mark, '#5809: dragging a project folder offers it to the row ' + JSON.stringify(d1));
    check(await until(async () => (await favs()).includes('folder:Clients')), '#5809: the project folder is a favourite after the drop');
    check(await ready(ev, `!!document.querySelector('#kbar .fv2-tile[data-fv2="folder:Clients"]')`), '#5809: it is a tile of the row');
    await ev(DRAG('#side .fhead[data-folder="Many"]'));
    check(await until(async () => (await favs()).includes('folder:Many')), '#5809: a second project folder');

    // ======== #5809: folders of the file store - the sidebar's tree and a row of the open folder
    await o.nav(B + '#ablage/' + TOP);
    check(await ready(ev, `!!document.querySelector('.abview .abrow[data-abid="${BOX}"]') && !!document.querySelector('#side .sbbt[data-sbbns="ab"][data-sbbid="${TOP}"]')`), 'the open folder shows its rows, the sidebar its tree');
    const d2 = JSON.parse(await ev(DRAG(`.abview .abrow[data-abid="${BOX}"]`)));
    check(d2.add === 'file:' + BOX, '#5809: a folder row of the file store offers itself ' + JSON.stringify(d2));
    check(await until(async () => (await favs()).includes('file:' + BOX)), '#5809: the folder of the file store is a favourite after the drop');
    const d3 = JSON.parse(await ev(DRAG(`#side .sbbt[data-sbbns="ab"][data-sbbid="${TOP}"]`)));
    check(d3.add === 'file:' + TOP, '#5809: a folder of the sidebar\'s file tree offers itself ' + JSON.stringify(d3));
    check(await until(async () => (await favs()).includes('file:' + TOP)), '#5809: the tree\'s folder is a favourite after the drop');
    await ev(DRAG(`.abview .abrow[data-abid="${HOLLOW}"]`));
    check(await until(async () => (await favs()).includes('file:' + HOLLOW)), '#5809: the empty folder too');
    // the move of the file store still works beside it: nothing moved by these drags
    check((await call('GET', `/api/files?parent=${TOP}`)).items?.filter(n => n.kind === 'folder').length === 2, 'the drags moved nothing in the file store');

    // ======== #5811: the menu of a project folder tile
    await signIn(o, '#today');
    check(await ready(ev, `['folder:Clients', 'folder:Many', 'file:${BOX}', 'file:${HOLLOW}'].every(k => document.querySelector('#kbar .fv2-tile[data-fv2="' + k + '"]'))`), 'the folder tiles are drawn');
    check(await ev(openMenu('folder:Clients')), 'right click on the folder tile');
    check(await ready(ev, `!!document.querySelector('#pop [data-act="fv2-kid"]')`), '#5811: the menu shows the content');
    const m1 = JSON.parse(await ev(MENU));
    check(m1.kids.join() === 'North client,South client,Abroad', '#5811: the projects in the sidebar\'s order, then the subfolder, no archived one ' + JSON.stringify(m1));
    check(m1.all.indexOf('South client') < m1.all.indexOf('Open') && m1.all.includes('Remove from favourites'), '#5811: the content stands above the old entries ' + JSON.stringify(m1.all));
    await shot('p21038-folder-menu.png');
    check(await ev(clickKid('South client')), 'click a project in the menu');
    check(await ready(ev, `S.route.key === 'l:${SUED}' && !document.querySelector('#pop .menu-list') && /South client/.test(document.querySelector('#view')?.textContent || '')`), '#5811: the project opens directly');
    // more than ten: "Show all" opens the folder
    check(await ev(openMenu('folder:Many')), 'right click on "Many"');
    check(await ready(ev, `document.querySelectorAll('#pop [data-act="fv2-kid"]').length === 10`), '#5811: at most ten entries');
    check(/Show all/.test(await ev(MENU)), '#5811: "Show all" under them');
    check(await ev(clickKid('Show all')), 'click "Show all"');
    check(await ready(ev, `S.route.key === 'folder:Many'`), '#5811: "Show all" opens the folder');

    // ======== #5811: a folder of the file store: subfolders loaded on opening, a click opens one
    check(await ev(openMenu('file:' + BOX)), 'right click on the file store folder');
    check(await ready(ev, `!!document.querySelector('#pop [data-act="fv2-kid"]')`), '#5811: the file folder\'s content arrives');
    const m2 = JSON.parse(await ev(MENU));
    check(m2.kids.length === 2 && m2.kids.includes('Receipts') && m2.kids.includes('Letters') && !m2.all.includes('Loading…'), '#5811: its subfolders, no "Loading…" left ' + JSON.stringify(m2));
    check(await ev(clickKid('Receipts')), 'click a subfolder');
    check(await ready(ev, `location.hash === '#ablage/${REC}' && /Receipts/.test(document.querySelector('#view')?.textContent || '')`), '#5811: the subfolder opens directly');
    // an empty folder
    check(await ev(openMenu('file:' + HOLLOW)), 'right click on the empty folder');
    check(await ready(ev, `[...document.querySelectorAll('#pop .menu-list [role="menuitem"] .ml')].some(x => x.textContent === 'Empty')`), '#5811: an empty folder says "Empty"');
    check(!await ev(`!!document.querySelector('#pop [data-act="fv2-kid"]')`), '#5811: no content rows for an empty folder');
  });
  console.log(`p21038_favfolders_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(1); });
