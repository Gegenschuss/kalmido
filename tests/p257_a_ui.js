// 2.57.0 UI tests of part A (#1798: the sidebar's fixed head and favourites of every kind), own container (start.sh).
// Server: fav_items is checked strictly (unknown keys 400, doubles dropped); a list's star keeps its place in fav_items.
// jsdom:
// - a star from the row menu (right-click) of Today, a list, a folder, the calendar, a filter, a tag, a person, an agent
// - the tiles: icon only, the name as title + aria-label, no numbers, in ONE order across kinds
// - the tile menu: Move left / Move right / Remove; a second session of the same person gets the new order without reload
// - "Only favourites" only for lists; a target the person cannot see any more is left out but stays stored
// Firefox (1440, 904 mouse; 390 touch drawer): the head stays in place while the sidebar scrolls, tiles square, drag to reorder
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p257_a_ui', check, shots: 'P257A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const rclick = (w, el) => el && el.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
const items = async () => JSON.parse((await call('GET', '/api/state')).settings.fav_items || '[]');
const menuItem = (d, re) => [...d.querySelectorAll('.menu-list [role="menuitem"]')].find(b => re.test(b.textContent));
const ALL = 'cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments,kanban';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ALL.split(',').filter(x => x !== 'collab')});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const TEAM = (await call('POST', '/api/lists', {name: 'Team'})).id, HOME = (await call('POST', '/api/lists', {name: 'Home'})).id;
  const WORK = (await call('POST', '/api/lists', {name: 'Work stuff', folder: 'Work'})).id;
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: BOB, role: 'edit'});
  const FLT = (await call('POST', '/api/filters', {name: 'Mine', rules: {lists: [HOME]}})).id;
  await call('POST', '/api/tasks', {title: 'Buy bread', list_id: HOME, tags: ['errand']});
  await call('POST', '/api/tasks', {title: 'Plan the week', list_id: TEAM});
  const AG = (await call('POST', '/api/admin/agents', {scopes: ['read'], username: 'helper', display_name: 'Helper'})).id;
  if (AG) await call('PUT', `/api/lists/${TEAM}/members`, {user_id: AG, role: 'edit'});

  // ================= the server: fav_items
  for (const bad of ['"x"', '["zz:1"]', '["v:nope"]', '[1]', '["folder:"]', '{"a":1}', JSON.stringify(Array.from({length: 201}, (_, i) => 'l:' + i))]) {
    const r = await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: `{"fav_items":${bad}}`});
    check(r.status === 400, 'fav_items: invalid value refused: ' + bad.slice(0, 40) + ' ' + r.status);
  }
  check((await call('PATCH', '/api/settings', {fav_items: ['v:today', 'm:cal', 'v:today', 'tag: errand ']})).status === 200, 'fav_items: a valid list is stored');
  check(JSON.stringify(await items()) === '["v:today","m:cal","tag:errand"]', 'fav_items: doubles dropped, names trimmed ' + JSON.stringify(await items()));
  await call('PUT', `/api/lists/${HOME}/favorite`, {});
  check((await items()).at(-1) === 'l:' + HOME, 'a new list star takes the last place in fav_items');
  await call('DELETE', `/api/lists/${HOME}/favorite`);
  check(!(await items()).includes('l:' + HOME), 'an unstarred list leaves fav_items');
  check(JSON.parse((await call('GET', '/api/state', null, await login('bob'))).settings.fav_items || '[]').length === 0, 'bob notices nothing of alice\'s favourites');
  await call('PATCH', '/api/settings', {fav_items: ['folder:Work', 'v:today']});
  await call('POST', '/api/folders/rename', {old: 'Work', new: 'Job'});
  check((await items()).join() === 'folder:Job,v:today', 'a renamed folder stays a favourite ' + (await items()).join());
  await call('POST', '/api/folders/rename', {old: 'Job', new: 'Work'});
  await call('PATCH', '/api/settings', {fav_items: []});
  // 2.99.0 (#2187): a person / an idle agent only stands in the sidebar while pinned
  await call('PATCH', '/api/settings', {side_people: String(BOB), side_agents: AG ? String(AG) : ''});

  // ================= stars from the row menus
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  check(!d.querySelector('#side .sg-favs'), 'no favourites section without a star');
  check(d.querySelector('#side .sbfix .sbhead') && d.querySelector('#side .sbdock .scmd'), 'the fixed head holds the workspace heading (2.138.2 #2392); 2.104.0 (#2161): the search sits in the bottom dock');
  const star = async (sel, key, what) => {
    let r, it;
    for (let i = 0; i < 3 && !it; i++) { r = d.querySelector(sel); rclick(w, r); it = await until(() => menuItem(d, /^Add to favourites/), 12); }  // a sync redraw may close the menu
    check(r && it, what + ': the row menu offers "Add to favourites" ' + sel + (r ? ' menu: ' + [...d.querySelectorAll('.menu-list [role="menuitem"]')].map(b => b.textContent).join('|') : ' no row; tags: ' + [...d.querySelectorAll('#side [data-go^="tag"]')].map(b => b.dataset.go).join()));
    click(w, it);
    check(await until(async () => (await items()).includes(key)), what + ': stored as ' + key);
    await sleep(250);
  };
  await star('#side .srow[data-go="today"]', 'v:today', 'Today');
  await star(`#side .srow[data-list="${TEAM}"]`, 'l:' + TEAM, 'a list');
  check((await call('GET', '/api/state')).settings.fav_lists === String(TEAM), 'a list star still sets fav_lists');
  await star('#side .fhead[data-folder="Work"]', 'folder:Work', 'a folder');
  await star('#side [data-go="cal"]', 'm:cal', 'the calendar');
  await star(`#side .srow[data-go="f/${FLT}"]`, 'f:' + FLT, 'a filter');
  await star('#side .srow[data-go="tag/errand"]', 'tag:errand', 'a tag');
  await star(`#side .srow[data-go="who/${BOB}"]`, 'p:' + BOB, 'a person');
  if (AG && d.querySelector(`#side .srow[data-aid="${AG}"]`)) await star(`#side .srow[data-aid="${AG}"]`, 'a:' + AG, 'an agent');
  else console.log('agent row not in the sidebar here, agent star skipped');
  const tiles = () => [...d.querySelectorAll('#side .sg-favs .fv2-tile')];
  const order = () => tiles().map(t => t.dataset.fv2).join();
  await until(() => tiles().length >= 7);
  const want = ['v:today', 'l:' + TEAM, 'folder:Work', 'm:cal', 'f:' + FLT, 'tag:errand', 'p:' + BOB, ...(AG && d.querySelector(`#side .fv2-tile[data-fv2="a:${AG}"]`) ? ['a:' + AG] : [])].join();
  check(order() === want, 'the tiles in the order of the stars, across kinds: ' + order());
  check(tiles().every(t => (t.textContent.trim() === '' || t.querySelector('.avatar')) && !t.querySelector('.n') && t.title && t.getAttribute('aria-label') === t.title), 'tiles: icon only (a person: the avatar), the name as title + aria-label');
  check(!/\d/.test(tiles().map(t => t.textContent).join('')) && !d.querySelector('#side .fv2-tile .c'), 'tiles: no numbers');
  check(d.querySelector('#side .fv2-tile[data-fv2="v:today"]')?.title === 'Today' && d.querySelector('#side .fv2-tile[data-fv2="v:today"]').classList.contains('on'), 'the tile of the open view is marked');
  check(!d.querySelector('#side .sg-favs .srow'), 'no list rows in the favourites any more');
  rclick(w, d.querySelector('#side .srow[data-go="today"]'));
  check(await until(() => menuItem(d, /^Remove from favourites/)), 'a starred row offers "Remove from favourites"');
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(200);
  // a tile opens its target
  click(w, d.querySelector('#side .fv2-tile[data-fv2="folder:Work"]'));
  check(await until(() => w.eval('S.route.key') === 'folder:Work'), 'a tile opens its target');

  // ================= arranging: the tile menu
  rclick(w, d.querySelector('#side .fv2-tile[data-fv2="m:cal"]'));
  const left = await until(() => menuItem(d, /^Move left/));
  check(left && menuItem(d, /^Move right/) && menuItem(d, /^Remove from favourites/) && menuItem(d, /^Open/), 'the tile menu: Open, Move left / right, Remove');
  click(w, left);
  check(await until(async () => (await items()).join().startsWith(`v:today,l:${TEAM},m:cal,folder:Work`)), 'Move left: one place to the left, stored ' + (await items()).join());
  check(await until(() => order().startsWith(`v:today,l:${TEAM},m:cal,folder:Work`)), 'Move left: drawn');
  rclick(w, d.querySelector('#side .fv2-tile[data-fv2="v:today"]'));
  check(await until(() => menuItem(d, /^Move left/)?.disabled), 'the first tile cannot move further left');
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(200);
  // undo = one step
  w.eval("histStep('undo')");
  check(await until(async () => (await items()).join().startsWith(`v:today,l:${TEAM},folder:Work,m:cal`)), 'Undo puts it back (one step)');
  // a second session of the same person follows without reload
  const w2 = await boot({user: 'alice', hash: 'today'}), d2 = w2.document;
  const order2 = () => [...d2.querySelectorAll('#side .sg-favs .fv2-tile')].map(t => t.dataset.fv2).join();
  check(order2() === order(), 'the second session shows the same order: ' + order2());
  rclick(w, d.querySelector('#side .fv2-tile[data-fv2="tag:errand"]'));
  click(w, await until(() => menuItem(d, /^Move right/)));
  check(await until(async () => (await items()).indexOf('tag:errand') === 6), 'Move right: stored');
  check(await until(() => order2() === order(), 120), 'the second session gets the new order without reload: ' + order2());
  w2.close();
  // remove from the tile
  rclick(w, d.querySelector('#side .fv2-tile[data-fv2="tag:errand"]'));
  click(w, await until(() => menuItem(d, /^Remove from favourites/)));
  check(await until(async () => !(await items()).includes('tag:errand')) && await until(() => !d.querySelector('#side .fv2-tile[data-fv2="tag:errand"]')), 'Remove from favourites: gone');

  // ================= "Only favourites" stays for lists
  const onlyBtn = () => d.querySelector('#side .sg-favs [data-fav-only]');
  check(onlyBtn(), '"Only favourites" is offered while a list is starred');
  click(w, onlyBtn());
  await until(() => d.querySelector('#side .sg-lists .sfavmore'));
  check(d.querySelector('#side .sg-lists .sfavmore') && !d.querySelector(`#side .sg-lists .srow[data-list="${HOME}"]`), '"Only favourites" folds the other lists');
  check(d.querySelector(`#side .srow[data-go="f/${FLT}"]`) && d.querySelector('#side .srow[data-go="today"]'), '"Only favourites" leaves filters and Plan alone');
  click(w, onlyBtn()); await sleep(300);
  rclick(w, d.querySelector('#side .fv2-tile[data-fv2="l:' + TEAM + '"]'));
  click(w, await until(() => menuItem(d, /^Remove from favourites/)));
  check(await until(async () => (await call('GET', '/api/state')).settings.fav_lists === ''), 'removing a list tile removes its star');
  check(await until(() => !onlyBtn() && d.querySelector('#side .sg-favs')), 'without a starred list no "Only favourites" button, the other tiles stay');

  // ================= targets the person cannot see now: left out, kept
  await call('PUT', `/api/lists/${HOME}/favorite`, {});
  await call('PATCH', '/api/settings', {fav_items: [...(await items()).filter(x => x !== 'l:' + HOME)]});  // as an older app: star without a place
  w.close(); w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(order().endsWith('l:' + HOME), 'a star without a place (older app, agent) shows at the end: ' + order());
  await call('PATCH', `/api/lists/${HOME}`, {archived: true});
  await call('DELETE', `/api/lists/${TEAM}/members/${BOB}`);
  w.close(); w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(!d.querySelector(`#side .fv2-tile[data-fv2="l:${HOME}"]`), 'an archived list: no tile');
  check(!d.querySelector(`#side .fv2-tile[data-fv2="p:${BOB}"]`), 'a person no longer in the team: no tile');
  check((await items()).includes('p:' + BOB), 'the hidden favourite stays stored');
  await call('PATCH', `/api/lists/${HOME}`, {archived: false});
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: BOB, role: 'edit'});
  w.close();

  // ================= Firefox: the fixed head, tile size, dragging
  await call('PATCH', '/api/settings', {fav_only: '0'});  // 2.80.3: the two quick "Only favourites" clicks above may land in either order
  let extra = 0; for (let i = 0; i < 40; i++) if ((await call('POST', '/api/lists', {name: 'Extra list ' + (i + 1)})).id) extra++;  // 2.57.0 (#1798): 40, with 26 the sidebar of a fresh run was only 2 px taller than a 900 px window
  const layout = async (o, tag, vw, vh, touch) => {
    const {cmd, ev, ctx, shot, nav} = o;
    await nav(B + 'static/icon.svg');
    const st = await ev(`(async () => { localStorage.clear(); return (await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})})).status; })()`);
    check(st === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + '#today');
    for (let i = 0; i < 100 && !(await ev(`!!document.querySelector('#side .fv2-tile') && document.querySelectorAll('#side .srow[data-list]').length > 25 && document.querySelector('#side').scrollHeight - document.querySelector('#side').clientHeight > 300`).catch(() => false)); i++) await sleep(300);  // the extra lists drawn and the sidebar really scrolls
    await sleep(600);
    if (touch) { await ev(`(() => { sideOpenDrawer(); return 1; })()`); await sleep(600); }
    const m = await ev(`(() => { const s = document.querySelector('#side'), f = document.querySelector('#side .sbfix'), t = document.querySelector('#side .fv2-tile'); if (!f || !t) return null;
      const top0 = f.getBoundingClientRect().top, r = t.getBoundingClientRect(); s.scrollTop = 600;
      return new Promise(res => requestAnimationFrame(() => { const top1 = f.getBoundingClientRect().top, ft = document.elementFromPoint(r.left + r.width / 2, f.getBoundingClientRect().top + 8);
        res({scroll: s.scrollTop, sh: s.scrollHeight, ch: s.clientHeight, rows: document.querySelectorAll('#side .srow').length, top0, top1, h: f.getBoundingClientRect().height, vh: innerHeight, w: r.width, th: r.height, rem: parseFloat(getComputedStyle(document.documentElement).fontSize), front: !!ft && !!ft.closest('.sbfix')}); })); })()`);
    check(m, tag + ': head and tiles drawn');
    if (m) {
      check(m.scroll > 100, tag + ': the sidebar scrolls ' + JSON.stringify({...m, extra}));
      check(Math.abs(m.top1 - m.top0) < 2 && m.top1 >= -1 && m.front, tag + ': the head stays in place while the sidebar scrolls ' + JSON.stringify(m));
      check(Math.abs(m.w - m.th) < 2 && m.w >= 2.75 * m.rem - 1, tag + ': tiles square, at least 2.75 rem ' + JSON.stringify(m));
      check(m.h < m.vh * 0.6, tag + ': the head stays below 60 % of the height ' + JSON.stringify(m));
    }
    await ev(`(() => { document.querySelector('#side').scrollTop = 0; return 1; })()`);
    await shot(`p257a-${tag}.png`);
    if (touch) return;
    // drag the first tile behind the third one (synthetic HTML5 events, laid out for real)
    const before = await ev(`[...document.querySelectorAll('#side .fv2-tile')].map(t => t.dataset.fv2).join()`);
    const res = await ev(`(async () => { const ts = [...document.querySelectorAll('#side .fv2-tile')], a = ts[0], c = ts[2], r = c.getBoundingClientRect(), dt = new DataTransfer();
      const fire = (type, el, x, y) => el.dispatchEvent(new DragEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, dataTransfer: dt}));
      fire('dragstart', a, 0, 0); const x = r.right - 4, y = r.top + r.height / 2; fire('dragover', document.elementFromPoint(x, y), x, y);
      const mark = c.className; fire('drop', document.elementFromPoint(x, y), x, y); fire('dragend', a, 0, 0);
      await new Promise(res => setTimeout(res, 900)); return {mark, order: [...document.querySelectorAll('#side .fv2-tile')].map(t => t.dataset.fv2).join()}; })()`);
    const b = before.split(','), exp = [b[1], b[2], b[0], ...b.slice(3)].join();
    check(/fv2-after/.test(res.mark), tag + ': dragging over a tile marks the place ' + res.mark);
    check(res.order === exp, tag + ': a drag moves the tile ' + res.order + ' / ' + exp);
    check(await until(async () => (await items()).filter(x => res.order.split(',').includes(x)).join() === exp), tag + ': the drag is stored');
  };
  await firefox(async o => { await layout(o, '1440', 1440, 900); await layout(o, '904', 904, 800); }, false);
  await firefox(async o => { await layout(o, '390', 390, 760, true); }, true);

  console.log(`${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
