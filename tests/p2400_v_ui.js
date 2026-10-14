// 2.40.0 UI tests (agent V), own container (start.sh). jsdom:
// - #1190 a project's progress bar is off by default and has no x; the list menu switches it on (per person)
// - #1361 favourites: the list menu and the star in the list header set / clear the personal star; the sidebar section
//   "Favourites" on top; "Only favourites" folds every other list under "More lists (N)" (a tap opens them); "Only favourites"
//   per view (Today) with a note and a way back
// - #1344 My tasks: right under the basket; own order by default: new / newly assigned on top, a drag changes only the own
//   order (tasks.sort unchanged), the subtitle "List › Section" opens the list; "Grouped by list" in "…" brings the groups back
// - #1345 the organisation as a second line under "Kalmido"
// Firefox 1000 x 800 (an unfolded Fold): the organisation name is not cut and stands below the app name; the agent chat header
//   keeps the agent's name whole and puts the permission badge into the second line
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2400_v_ui', check, shots: 'P2400V_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const settings = async () => (await call('GET', '/api/state')).settings;
const ORGNAME = 'Northwind Trading Company';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,progress,comments'});
  const st0 = await call('GET', '/api/state'), ME = st0.me, ORG = ME.workspaces?.[0]?.id, INBOX = st0.lists.find(l => l.is_inbox).id;
  if (ORG && (await call('PATCH', `/api/admin/orgs/${ORG}`, {name: ORGNAME})).status !== 200) await call('PATCH', `/api/orgs/${ORG}`, {name: ORGNAME});
  const ON = ((await call('GET', '/api/state')).me.orgs || [])[0] || '', HASORG = !!ON && ON.toLowerCase() !== 'kalmido';  // renamed where the mode allows it
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const PRJ = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project', ...(ORG ? {org_id: ORG} : {})})).id;
  const TEAM = (await call('POST', '/api/lists', {name: 'Team', ...(ORG ? {org_id: ORG} : {})})).id;
  const HOME = (await call('POST', '/api/lists', {name: 'Household', ...(ORG ? {org_id: ORG} : {})})).id;
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: bob.id, role: 'edit'});
  const SEC = (await call('POST', '/api/sections', {list_id: TEAM, name: 'Backlog'})).id;
  const today = (await call('GET', '/api/state')).today || new Date().toISOString().slice(0, 10);
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const P1 = await mk('Write the plan', PRJ, {due: today}); await mk('Book the room', PRJ);
  const TD = await mk('Team today', TEAM, {due: today});
  const T1 = await mk('First mine', TEAM, {assignee_id: ME.id, section_id: SEC});
  const T2 = await mk('Second mine', HOME, {assignee_id: ME.id});
  const T3 = await mk('Third mine', PRJ, {assignee_id: ME.id});

  // ================= #1190 the progress bar
  let w = await boot({user: 'alice', hash: 'l/' + PRJ}), d = w.document;
  check(!d.querySelector('#view .lhead .lprog') && !d.querySelector('#view .lhead .lpx'), '#1190: a project shows no progress bar by default, no x');
  check(!d.querySelector(`#side .srow[data-list="${PRJ}"] .sprog`), '#1190: no bar in the sidebar either');
  w.eval(`listMenuItems(${PRJ}).find(x => x.label === 'Show progress').fn()`);
  check(await until(() => d.querySelector('#view .lhead .lprog')) && !d.querySelector('#view .lhead .lpx'), '#1190: "Show progress" switches it on, without an x');
  check(await until(async () => (await settings()).show_progress === String(PRJ)), '#1190: stored for the person');
  w.eval(`listMenuItems(${PRJ}).find(x => x.label === 'Hide progress').fn()`);
  check(await until(() => !d.querySelector('#view .lhead .lprog')), '#1190: "Hide progress" switches it off again');

  // ================= #1345 the organisation under the app name
  const org = d.querySelector('#side .sbrand .sbhome .sbtxt .sborg');
  if (HASORG) check(org && org.textContent === ON && org.previousElementSibling?.textContent === 'Kalmido', '#1345: the organisation as the second line under "Kalmido" ' + d.querySelector('#side .sbrand')?.innerHTML.slice(0, 300));
  else console.log('#1345: no organisation in this instance mode, the org line check is skipped');

  // ================= #1361 favourites
  const star = () => d.querySelector('#top .hfav');
  w.close(); w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  check(star() && star().getAttribute('aria-pressed') === 'false', '#1361: a star in the list header, not set');
  check(!d.querySelector('#side .sg-favs'), '#1361: no favourites section without a star');
  click(w, star());
  check(await until(() => star()?.getAttribute('aria-pressed') === 'true'), '#1361: the star in the header sets it');
  check(await until(async () => (await settings()).fav_lists === String(TEAM)), '#1361: stored on the server');
  check((await call('GET', '/api/state', null, await login('bob'))).settings.fav_lists === '', '#1361: bob (member of Team) notices nothing');
  w.eval(`listMenuItems(${PRJ}).find(x => x.label === 'Add to favourites').fn()`);
  check(await until(async () => (await settings()).fav_lists === `${TEAM},${PRJ}`), '#1361: the list menu (also the sidebar context menu) sets it');
  const favs = await until(() => d.querySelector('#side .sg-favs'));
  const groups = [...d.querySelectorAll('#side .sgroup')];
  check(favs && groups[0] === favs, '#1361: the section "Favourites" is the first group of the sidebar');
  check(favs && [...favs.querySelectorAll('.srow[data-list]')].map(x => +x.dataset.list).join() === `${TEAM},${PRJ}`, '#1361: both favourites in it');
  check(w.eval(`listMenuItems(${TEAM}).some(x => x.label === 'Remove from favourites')`), '#1361: the menu offers to remove it');
  // Only favourites
  const lists = () => d.querySelector('#side .sg-lists');
  click(w, favs.querySelector('[data-fav-only]'));
  check(await until(async () => (await settings()).fav_only === '1'), '#1361: "Only favourites" is stored');
  const more = await until(() => lists()?.querySelector('.sfavmore'));
  check(more && /More lists \(1\)/.test(more.textContent) && !lists().querySelector(`.srow[data-list="${HOME}"]`), '#1361: the other lists fold under "More lists (1)" ' + more?.textContent);
  click(w, more);
  check(await until(() => lists()?.querySelector(`.srow[data-list="${HOME}"]`)), '#1361: a tap opens them');
  click(w, d.querySelector('#side .sg-favs [data-fav-only]'));
  check(await until(async () => (await settings()).fav_only === '0') && await until(() => !lists()?.querySelector('.sfavmore')), '#1361: off again: every list as before');
  // Only favourites per view: Today
  w.eval('go("today")'); await sleep(300);
  check(d.querySelector(`#view .trow[data-id="${TD}"]`) && d.querySelector(`#view .trow[data-id="${P1}"]`), '#1361: Today shows both lists first');
  w.eval(`listMenuItems(${TEAM}).find(x => x.label === 'Remove from favourites').fn()`); await sleep(300);
  const it = w.eval(`topMoreItems().find(x => x.label === 'Only favourites')`);
  check(it && !it.on, '#1361: "…" of Today offers "Only favourites"');
  w.eval(`topMoreItems().find(x => x.label === 'Only favourites').fn()`);
  check(await until(() => !d.querySelector(`#view .trow[data-id="${TD}"]`) && d.querySelector(`#view .trow[data-id="${P1}"]`)), '#1361: Today only from favourites');
  check(d.querySelector('#view .favnote') && await until(async () => (await settings()).fav_views === 'today'), '#1361: a note says so, stored per view');
  w.eval('go("tomorrow")'); await sleep(200); w.eval('go("today")'); await sleep(200);
  check(!d.querySelector(`#view .trow[data-id="${TD}"]`), '#1361: the filter stays with the view');
  click(w, d.querySelector('#view .favnote [data-fav-view-off]'));
  check(await until(() => d.querySelector(`#view .trow[data-id="${TD}"]`)) && await until(async () => (await settings()).fav_views === ''), '#1361: "Show all" switches it off');
  w.close();

  // ================= #1344 My tasks
  w = await boot({user: 'alice', hash: 'assigned'}); d = w.document;
  const plan = [...d.querySelectorAll('#side .sg-focus .srow[data-go]')].map(x => x.dataset.go);
  check(plan[0] === 'inbox' && plan[1] === 'assigned', '#1344: My tasks right under the basket ' + plan.join());
  const order = () => [...d.querySelectorAll('#view .trow[data-id]')].map(x => +x.dataset.id).filter(id => [T1, T2, T3].includes(id) || id > T3);
  check(order().join() === [T3, T2, T1].join(), '#1344: own order by default, not placed yet = newest first ' + order().join());
  check(!d.querySelector('#view .group[data-kbg]'), '#1344: no list groups in the own order');
  const sub = d.querySelector(`#view .trow[data-id="${T1}"] .mosub`);
  check(sub && /Team › Backlog/.test(sub.textContent), '#1344: the subtitle "List › Section" ' + sub?.textContent);
  const sort0 = (await call('GET', '/api/state')).tasks.filter(t => [T1, T2, T3].includes(t.id)).map(t => t.sort).join();
  w.eval(`dropTask(${T1}, document.querySelector('#view .trow[data-id="${T3}"]'), 0)`);
  check(await until(() => order().join() === [T1, T3, T2].join()), '#1344: a drag puts it there ' + order().join());
  const mo = await until(async () => { const s = await call('GET', '/api/state'); return s.mine_order?.[T1] === 0 && s; });
  check(mo && mo.mine_order[T3] === 1 && mo.mine_order[T2] === 2, '#1344: the own order on the server ' + JSON.stringify(mo?.mine_order));
  check(mo && mo.tasks.filter(t => [T1, T2, T3].includes(t.id)).map(t => t.sort).join() === sort0, '#1344: tasks.sort unchanged');
  const T4 = await mk('Brand new mine', HOME, {assignee_id: ME.id});
  await w.eval('load().then(render)'); await sleep(300);
  check(order()[0] === T4 && order().slice(1).join() === [T1, T3, T2].join(), '#1344: a new task lands on top ' + order().join());
  click(w, d.querySelector(`#view .trow[data-id="${T1}"] .mosub`)); await sleep(300);
  check(w.eval('S.route.key') === 'l:' + TEAM, '#1344: a tap on the subtitle opens the list (' + w.eval('S.route.key') + ')');
  w.eval('go("assigned")'); await sleep(300);
  const items = w.eval('topMoreItems().map(x => x.label + (x.on ? "*" : ""))');
  check(items.includes('Own order*') && items.includes('Grouped by list'), '#1344: "…" switches the view ' + items.join('|'));
  w.eval(`topMoreItems().find(x => x.label === 'Grouped by list').fn()`);
  check(await until(() => d.querySelector(`#view .group[data-kbg="l:${TEAM}"]`) && !d.querySelector('#view .mosub')), '#1344: grouped by list as before');
  check(await until(async () => (await settings()).mine_view === 'lists'), '#1344: stored');
  w.close();

  // ================= Firefox: 1000 x 800 (an unfolded Fold), mouse
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper of the planning office'});
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o, tag = '1000';
    await nav(B + 'static/icon.svg');
    const st = await ev(`(async () => { localStorage.clear(); return (await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})})).status; })()`);
    check(st === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1000, height: 800}});
    await nav(B + '#l/' + TEAM);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
    await sleep(800);
    const m = await ev(`(() => { const o = document.querySelector('#side .sbrand .sborg'), n = document.querySelector('#side .sbrand .sbtxt > span');
      if (!o) return null; const a = o.getBoundingClientRect(), b = n.getBoundingClientRect();
      return {cut: o.scrollWidth > o.clientWidth + 1, below: a.top >= b.bottom - 2, w: Math.round(a.width), txt: o.textContent}; })()`);
    if (HASORG) check(m && !m.cut && m.below, `${tag}: the organisation name stands whole below "Kalmido" ` + JSON.stringify(m));
    if (ag.id) {
      await ev(`chatOpen(${ag.id})`); await sleep(1200);
      const c = await ev(`(() => { const b = document.querySelector('.chath .chnm b'), md = document.querySelector('.chath .chnm .chmode'), l2 = document.querySelector('.chath .chl2');
        if (!b) return null; const r = b.getBoundingClientRect();
        return {cut: b.scrollWidth > b.clientWidth + 1, name: b.textContent, mode: md ? md.getBoundingClientRect().top >= r.bottom - 2 : null, l2: l2 ? Math.round(l2.getBoundingClientRect().top - r.top) : null}; })()`);
      check(c && !c.cut, `${tag}: the agent's name in the chat header is not cut ` + JSON.stringify(c));
      if (c && c.mode !== null) check(c.mode, `${tag}: the permission badge in the second line ` + JSON.stringify(c));
      await shot('p2400v-1000-chat.png');
    }
  }, false);

  console.log(`${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
