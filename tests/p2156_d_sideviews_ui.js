// 2.156.0 UI tests of part D (#2186: saved views of the sidebar), own container (start.sh), invented data only.
// jsdom:
// - "Save as view…" in the sidebar's tool menu: the dialog (name, icon grid, start page, groups / entries to show, open)
// - the view's tile apart from the favourites, framed while active; the fixed tile "Everything"
// - what the view hides waits under "Others (N)" (folded; a hidden group as a whole), nothing is lost
// - a second tap on the active tile = "Everything"; a start page opens when switched
// - folding inside a view is only for now: the stored view stays, "Update view" keeps it
// - a second session of the same person (another device) follows the active view without reload
// - Settings > Appearance > Sidebar lists the views; a fresh start loads sideviews.js on demand (lazy) and draws the tiles
// Firefox (1440 mouse, 390 touch drawer): screenshots only
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2156_d_ui', check, shots: 'P2156D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const menuItem = (d, re) => [...d.querySelectorAll('.menu-list [role="menuitem"]')].find(b => re.test(b.textContent));
const stored = async () => { const s = (await call('GET', '/api/state')).settings; return {views: JSON.parse(s.side_views || '[]'), act: s.side_view || ''}; };
const ALL = 'cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments,kanban';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ALL.split(',').filter(x => x !== 'collab')});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  const HOME = (await call('POST', '/api/lists', {name: 'Home'})).id;
  await call('POST', '/api/lists', {name: 'Work stuff', folder: 'Work'});
  await call('POST', '/api/filters', {name: 'Mine', rules: {lists: [HOME]}});
  await call('POST', '/api/tasks', {title: 'Buy bread', list_id: HOME, tags: ['errand']});
  await call('PATCH', '/api/settings', {fav_items: ['v:today']});

  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const side = sel => d.querySelector('#side ' + sel);
  const inMore = el => !!el?.closest('.sg-svmore');
  check(!side('.sv-row') && side('[data-svt]'), 'no view tiles without a view; the tool button in the sidebar head');
  // ================= "Save as view…"
  click(w, side('[data-svt]'));
  const save = await until(() => menuItem(d, /^Save as view/));
  check(save, 'the tool menu offers "Save as view…": ' + [...d.querySelectorAll('.menu-list [role="menuitem"]')].map(b => b.textContent).join('|'));
  click(w, save);
  const dlg = await until(() => d.querySelector('.svdlg'));
  check(dlg && dlg.querySelector('#svd-name') && dlg.querySelectorAll('.svd-ico[role="radio"]').length >= 20 && dlg.querySelector('#svd-start'), 'the dialog: name, icon grid (app icons), start page');
  check(dlg && !/[\u{1F300}-\u{1FAFF}]/u.test(dlg.querySelector('.svd-ic').textContent), 'the icon grid has no emoji');
  check(dlg?.querySelector('[data-svk="v:week"]') && dlg.querySelector('[data-svk="g:filters"]') && dlg.querySelector('[data-svk="folder:Work"]') && dlg.querySelector(`[data-svk="l:${HOME}"]`), 'the dialog lists groups and entries (Plan, filters, folders, lists)');
  if (dlg) {
    dlg.querySelector('#svd-name').value = 'Road';
    click(w, dlg.querySelector('[data-svi="car"]'));
    dlg.querySelector('[data-svk="v:week"]').checked = false;
    dlg.querySelector('[data-svk="g:filters"]').checked = false;
    const st = dlg.querySelector('#svd-start'); st.value = 'today';
    click(w, dlg.querySelector('[data-svd="save"]'));
  }
  const s1 = await until(async () => { const s = await stored(); return s.views.length === 1 && s; });
  const V = s1 && s1.views[0];
  check(V && V.name === 'Road' && V.icon === 'car' && V.hide.includes('v:week') && V.hide.includes('g:filters') && V.start === 'today', 'stored: name, icon, hidden entries, start page ' + JSON.stringify(V));
  check(s1 && s1.act === V.id, 'a new view is the active one at once');
  // ================= the tiles
  await until(() => side('.sv-tile.on'));
  const tiles = () => [...d.querySelectorAll('#side .sv-tile')];
  check(tiles().length === 2 && tiles()[0].dataset.svid === '' && tiles()[1].dataset.svid === V?.id, 'the tiles: "Everything" first, then the view');
  check(side('.sv-tile.on')?.dataset.svid === V?.id && side('.sv-tile.on').getAttribute('aria-pressed') === 'true', 'the active tile is marked');
  check(side('.sg-favs .sv-row') && side('.sg-favs .fv2-grid') && !side('.sv-row .fv2-tile'), 'the view tiles sit apart from the favourite tiles');
  // ================= "Others (N)"
  const more = side('.sg-svmore');
  check(more && /Others \(2\)/.test(more.textContent), 'hidden: "Others (2)" at the end ' + (more ? more.querySelector('.sgt').textContent : 'none'));
  check(more && more.querySelector('.svm-body').hidden, '"Others" starts folded');
  check(inMore(side('.sg-filters')) && !side('.sg-focus [data-go="week"]'), 'the hidden group and entry are out of their place');
  check(d.querySelector('#side > .sg-svmore')?.nextElementSibling?.classList.contains('sfoot'), '"Others" right above Settings');
  click(w, side('.sg-svmore [data-sv="more"]'));
  await until(() => !side('.sg-svmore .svm-body')?.hidden);
  check(inMore(side('.svm[data-go="week"]')) && inMore(side('.sg-filters .srow')), 'unfolded: the hidden entry and the group are there (nothing lost)');
  click(w, side('.sg-svmore .srow[data-go="week"]'));
  check(await until(() => w.eval('S.route.key') === 'week'), 'a hidden entry still opens');
  // ================= only for now: folding inside the view
  const listsOpen = () => w.eval("sideOpen('lists')");
  const was = listsOpen();
  click(w, side('.sg-lists .sgt[data-act="side-group"]'));
  check(await until(() => listsOpen() !== was), 'a group folds inside the view');
  check(JSON.stringify((await stored()).views[0].open) === JSON.stringify(V.open), 'folding does not change the stored view');
  click(w, side('[data-svt]'));
  const upd = await until(() => menuItem(d, /^Update view/));
  check(upd && !upd.disabled, 'the tool menu offers "Update view" after a change');
  click(w, upd);
  check(await until(async () => (await stored()).views[0].open.includes('lists') === !was), '"Update view" stores the folding');
  // ================= the second device
  const w2 = await boot({user: 'alice', hash: 'inbox'}), d2 = w2.document;
  check(await until(() => d2.querySelector(`#side .sv-tile.on[data-svid="${V?.id}"]`)), 'a second session shows the same active view');
  // ================= second tap = Everything
  click(w, side('.sv-tile.on'));
  check(await until(async () => (await stored()).act === ''), 'a second tap on the active tile switches back to "Everything"');
  check(await until(() => side('.sv-tile.on')?.dataset.svid === '' && !side('.sg-svmore') && !inMore(side('.sg-filters'))), 'Everything: the whole sidebar, no "Others"');
  check(await until(() => !d2.querySelector('#side .sv-tile.on[data-svid]:not([data-svid=""])') && !d2.querySelector('#side .sg-svmore')), 'the second session follows without reload');
  w.location.hash = '#inbox'; await sleep(300);
  click(w, side(`.sv-tile[data-svid="${V?.id}"]`));
  check(await until(() => w.eval('S.route.key') === 'today'), 'switching to the view opens its start page');
  // ================= settings
  w.eval("settingsModal('sidebar')");
  check(await until(() => d.querySelectorAll('#s-sv .svrow').length === 1 && /Road/.test(d.querySelector('#s-sv').textContent)), 'Settings > Sidebar lists the view');
  check(d.querySelector('#s-sv-h') && d.querySelector('[data-sv="new"]'), 'Settings: heading and "New view…"');
  d.querySelector('.modal')?.remove();
  // ================= on demand: a fresh start without the modules loaded draws the tiles once sideviews.js is there
  const w3 = await boot({user: 'alice', hash: 'today', lazy: true}), d3 = w3.document;
  check(await until(() => d3.querySelector(`#side .sv-tile.on[data-svid="${V?.id}"]`) && d3.querySelector('#side .sg-svmore')), 'lazy start: sideviews.js loads on demand, the view is applied');

  // ================= Firefox: screenshots (desktop, phone drawer)
  const layout = async (o, tag, vw, vh, touch) => {
    const {cmd, ev, ctx, shot, nav} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(async () => { localStorage.clear(); return (await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})})).status; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + '#today');
    for (let i = 0; i < 60 && !(await ev(`!!document.querySelector('#side .sv-tile.on')`).catch(() => false)); i++) await sleep(300);
    if (touch) { await ev(`(() => { sideOpenDrawer(); return 1; })()`); await sleep(600); }
    await ev(`(() => { const b = document.querySelector('#side .sg-svmore [data-sv="more"]'); if (b) b.click(); return 1; })()`); await sleep(400);
    const m = await ev(`(() => { const t = document.querySelector('#side .sv-tile.on'); if (!t) return null; const r = t.getBoundingClientRect(); return {h: r.height, w: r.width, rem: parseFloat(getComputedStyle(document.documentElement).fontSize)}; })()`);
    check(m && m.h >= (touch ? 2.75 : 2.25) * m.rem - 1, tag + ': the view tile is tall enough to tap ' + JSON.stringify(m));
    await shot(`p2156d-${tag}.png`);
  };
  await firefox(async o => { await layout(o, '1440', 1440, 900); }, false);
  await firefox(async o => { await layout(o, '390', 390, 760, true); }, true);

  console.log(`${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
