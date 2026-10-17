// 2.71.0 UI tests (part B), own container (start.sh). jsdom:
// #1459 a task in several lists without a copy: the task menu offers "Show also in list…" (only lists of the same
//       workspace the person may change), linking puts the task into the further list's view (with the mark "From <its
//       list>") and leaves it in its own list (mark "Also in <list>"), the sidebar counts it in both lists, the board of the
//       further list puts it into the column of the link, dropping it on another column there changes only the link,
//       "Remove from <list>" is one undo step (undo brings the link back with its column), the history names the list;
//       a reader of only the further list does not see the task there
// Firefox 390 touch: the further list on the phone with the mark, screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p271_b_ui', check, shots: 'P271B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,kanban';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const dave = await call('POST', '/api/users', {orgs: [1], username: 'dave', display_name: 'Dave', password: 'password123', email: 'dave@example.com'});
  const CD = await login('dave');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CD);
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const SALES = (await call('POST', '/api/lists', {name: 'Sales', org_id: ORG})).id;
  const MKT = (await call('POST', '/api/lists', {name: 'Marketing', org_id: ORG})).id;
  const PRIV = (await call('POST', '/api/lists', {name: 'Private notes', org_id: null})).id;
  await call('PUT', `/api/lists/${MKT}/members`, {user_id: dave.id, role: 'edit'});
  const S1 = (await call('POST', '/api/sections', {list_id: MKT, name: 'Ideas'})).id;
  const S2 = (await call('POST', '/api/sections', {list_id: MKT, name: 'Doing'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Launch flyer', list_id: SALES})).id;

  // ================= the task menu: "Show also in list…"
  let w = await boot({user: 'alice', hash: 'l/' + SALES}), d = w.document;
  await until(() => d.querySelector(`.trow[data-id="${T}"]`));
  const items = w.eval(`ml_menuItems(document.body, taskById(${T})).map(x => x.label)`);
  check(items.includes('Show also in list…'), '#1459: the task menu offers "Show also in list…" ' + JSON.stringify(items));
  const ok1 = w.eval(`[${MKT}, ${PRIV}, ${SALES}].map(id => ml_okTarget(taskById(${T}), listById(id)))`);
  check(JSON.stringify(ok1) === '[true,false,false]', '#1459: offered: the organisation list, not the private one, not its own ' + JSON.stringify(ok1));
  await w.eval(`ml_add(${T}, ${MKT})`); await sleep(300);
  let srv = (await call('GET', `/api/tasks/${T}`));
  check(srv.list_id === SALES && (srv.also || []).map(a => a.list_id).join() === String(MKT), '#1459: linked on the server, its own list unchanged');
  w.eval('render()'); await sleep(100);
  check(/Also in Marketing/.test(d.querySelector(`.trow[data-id="${T}"] .mlm`)?.textContent || ''), '#1459: the row in Sales: "Also in Marketing"');
  const cnt = w.eval(`counts().lists`);
  check(cnt[SALES] === 1 && cnt[MKT] === 1, '#1459: the sidebar counts it in both lists ' + JSON.stringify(cnt));
  check(w.eval(`HIST.undo.length`) >= 1, '#1459: linking is an undo step');
  w.close();

  // ================= the further list: the view, the board, dropping changes only the link
  w = await boot({user: 'alice', hash: 'l/' + MKT}); d = w.document;
  await until(() => d.querySelector(`.trow[data-id="${T}"]`));
  check(d.querySelector(`.trow[data-id="${T}"]`), '#1459: the task shows in Marketing');
  check(/From Sales/.test(d.querySelector(`.trow[data-id="${T}"] .mlm`)?.textContent || ''), '#1459: with the mark "From Sales"');
  await call('PATCH', `/api/tasks/${T}/links/${MKT}`, {section_id: S1});
  await call('PATCH', `/api/lists/${MKT}`, {view: 'kanban'});
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + MKT}); d = w.document;
  await until(() => d.querySelector(`.kcol[data-kcol="${S1}"] .trow[data-id="${T}"]`));
  check(d.querySelector(`.kcol[data-kcol="${S1}"] .trow[data-id="${T}"]`), '#1459: the board puts it into the column of the link');
  await w.eval(`ml_drop(taskById(${T}), {kcol: document.querySelector('.kcol[data-kcol="${S2}"]')})`); await sleep(300);
  srv = await call('GET', `/api/tasks/${T}`);
  check(srv.list_id === SALES && !srv.section_id && srv.also?.[0]?.section_id === S2, '#1459: the drop changed only the link ' + JSON.stringify([srv.list_id, srv.section_id, srv.also]));
  w.eval('render()'); await sleep(100);
  check(d.querySelector(`.kcol[data-kcol="${S2}"] .trow[data-id="${T}"]`), '#1459: now in the column Doing');
  // remove + undo
  const rm = w.eval(`ml_menuItems(document.body, taskById(${T})).map(x => x.label)`);
  check(rm.includes('Remove from Marketing'), '#1459: the menu offers "Remove from Marketing" ' + JSON.stringify(rm));
  await w.eval(`ml_remove(${T}, ${MKT})`); await sleep(300);
  srv = await call('GET', `/api/tasks/${T}`);
  check(!srv.also && srv.list_id === SALES && !srv.deleted_at, '#1459: removed from Marketing, the task stays');
  w.eval('render()'); await sleep(100);
  check(!d.querySelector(`.trow[data-id="${T}"]`), '#1459: gone from the board');
  await w.eval(`histStep('undo')`); await sleep(600);
  srv = await call('GET', `/api/tasks/${T}`);
  check(srv.also?.[0]?.list_id === MKT && srv.also[0].section_id === S2, '#1459: undo brings the link back with its column ' + JSON.stringify(srv.also));
  w.close();

  // ================= the history names the list; a reader of only Marketing does not see the task
  const tl = await call('GET', `/api/tasks/${T}/timeline`);
  check((tl.activity || []).some(a => a.kind === 'ml_add' && a.data.name === 'Marketing'), '#1459: the history names Marketing');
  const wd = await boot({user: 'dave', hash: 'l/' + MKT}); await sleep(800);
  check(!wd.document.querySelector(`.trow[data-id="${T}"]`) && !/Launch flyer/.test(wd.document.body.textContent), '#1459: dave (only Marketing) does not see the task');
  wd.close();

  // ================= Firefox: the further list on the phone (390, touch)
  await call('PATCH', `/api/lists/${MKT}`, {view: 'list'});
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + MKT); await ready(ev);
    const g = await ev(`(() => { const m = document.querySelector('.trow[data-id="${T}"] .mlm'); if (!m) return null; const r = m.getBoundingClientRect();
      return {right: r.right, wide: document.documentElement.scrollWidth <= 390, text: m.textContent}; })()`);
    check(g && g.right <= 390 && g.wide && /From Sales/.test(g.text), `${tag}: #1459 the mark fits the phone ` + JSON.stringify(g));
    await shot('p271b-390-further-list.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
