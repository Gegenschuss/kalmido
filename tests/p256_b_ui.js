// 2.56.0 UI tests (part B), own container (start.sh). jsdom:
// #1795 Settings > Organisation > Lists of the organisation: "Edit" opens name, icon and colour of a list (the pickers of the
//       list dialog) for an organisation admin without a role in the list; Save changes the name and the colour (the row
//       shows them at once), one undo step brings both back; an emoji from the grid goes in front of the name; a preset
//       picture is set at once; the history names the change; the owner reads who renamed the list
// Firefox 390 touch: the edit dialog fits the phone, Save >= 44 px, screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p256_b_ui', check, shots: 'P256B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call('POST', '/api/users', {orgs: [1], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const carol = await call('POST', '/api/users', {orgs: [1], username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  // bob's list of the organisation, shared with carol: alice (the organisation's admin) has no role in it
  const BT = (await call('POST', '/api/lists', {name: 'Bob Team', org_id: ORG, color: '#2dd4bf'}, CB)).id;
  await call('PUT', `/api/lists/${BT}/members`, {user_id: carol.id, role: 'edit'}, CB);
  await call('POST', '/api/tasks', {title: 'Bob secret task', list_id: BT}, CB);
  void bob;

  // ================= #1795 Edit in the overview
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`oadmOpen(${ORG}, 'Kalmido')`); await until(() => d.querySelector(`.oadmmd .oadmrow[data-olid="${BT}"]`));
  const om = () => d.querySelector('.oadmmd');
  const brow = () => om().querySelector(`.oadmrow[data-olid="${BT}"]`);
  check(brow()?.querySelector('[data-oa="edit"]'), '#1795: the row has "Edit"');
  check(brow()?.querySelector('.ole-sw'), '#1795: the row shows the list\'s colour');
  click(w, brow().querySelector('[data-oa="edit"]')); await until(() => d.querySelector('.olemd'));
  const em = () => d.querySelector('.olemd');
  check(em() && em().querySelector('#ole-name')?.value === 'Bob Team', '#1795: the dialog shows the name');
  check(em().querySelectorAll('#ole-col button').length >= 10 && em().querySelector('#ole-col button.on'), '#1795: the colour buttons of the list dialog, the current one on');
  check(em().querySelector('#ole-emogrid [data-emo]') && em().querySelector('#ole-emogrid [data-licon="kalmido"]'), '#1795: the emoji grid and the pictures');
  check(!/secret task/i.test(em().textContent), '#1795: no contents in the dialog');
  // a new name, an emoji, another colour; Save
  em().querySelector('#ole-name').value = 'Team Nord';
  click(w, em().querySelector('#ole-emo'));
  const e1 = em().querySelector('#ole-emogrid [data-emo]:not([data-emo=""])'), emo = e1.dataset.emo;
  click(w, e1); await sleep(50);
  const cb = [...em().querySelectorAll('#ole-col button')].find(b => b.dataset.c && !b.classList.contains('on'));
  click(w, cb);
  click(w, em().querySelector('[data-m="save"]')); await until(() => !em());
  let srv = (await call('GET', `/api/orgs/${ORG}/lists`)).lists.find(x => x.id === BT);
  check(srv && srv.name === emo + 'Team Nord', '#1795: saved: the emoji in front of the name ' + srv?.name);
  check(srv && srv.color === cb.dataset.c, '#1795: saved: the new colour ' + srv?.color + ' ' + cb.dataset.c);
  await until(() => /Team Nord/.test(brow()?.textContent || ''));
  check(/Team Nord/.test(brow()?.textContent || ''), '#1795: the row shows the new name at once');
  check(/Alice changed .*Team Nord/.test(om().querySelector('.oadmlog')?.textContent || '') || /changed/.test(om().querySelector('.oadmlog')?.textContent || ''), '#1795: the history names the change');
  check(/Name: Bob Team → /.test(om().querySelector('.oadmlog')?.textContent || ''), '#1795: the history has old -> new ' + (om().querySelector('.oadmlog')?.textContent || '').slice(0, 160));
  // one undo step brings name and colour back
  check(w.eval('HIST.undo.length') >= 1, '#1795: one undo step');
  await w.eval(`histStep('undo')`); await sleep(400);
  srv = (await call('GET', `/api/orgs/${ORG}/lists`)).lists.find(x => x.id === BT);
  check(srv && srv.name === 'Bob Team' && srv.color === '#2dd4bf', '#1795: undo: name and colour back ' + JSON.stringify(srv && [srv.name, srv.color]));
  await w.eval(`histStep('redo')`); await sleep(400);
  srv = (await call('GET', `/api/orgs/${ORG}/lists`)).lists.find(x => x.id === BT);
  check(srv && srv.name === emo + 'Team Nord', '#1795: redo');
  // a preset picture at once
  click(w, brow().querySelector('[data-oa="edit"]')); await until(() => d.querySelector('.olemd'));
  click(w, em().querySelector('#ole-emo'));
  click(w, em().querySelector('#ole-emogrid [data-licon="kalmido"]'));
  // CI of 2.409.0 (#3506): the name loses its emoji in a second request after the picture (PATCH after PUT icon) - wait for both
  await until(async () => { const x = (await call('GET', `/api/orgs/${ORG}/lists`)).lists.find(y => y.id === BT); return x?.icon && x.name === 'Team Nord'; });
  srv = (await call('GET', `/api/orgs/${ORG}/lists`)).lists.find(x => x.id === BT);
  check(srv.icon === '/static/icon.svg', '#1795: a preset picture is set at once');
  check(srv.name === 'Team Nord', '#1795: the picture takes the emoji out of the name (as in the list dialog) ' + srv.name);
  await until(() => brow()?.querySelector('img.ole-ic'));
  check(brow()?.querySelector('img.ole-ic'), '#1795: the row shows the picture');
  click(w, em().querySelector('[data-m="cancel"]')); await sleep(100);
  check(!em(), '#1795: Cancel closes');
  w.close();
  // the owner reads who did it
  const wb = await boot({user: 'bob', hash: 'news'}); await sleep(600);
  // 2.152.2 (#2624): project instead of list
  check(/Alice renamed the project Bob Team to .*Team Nord \(admin of /.test(wb.document.body.textContent), '#1795: bob reads who renamed his list');
  // 2.58.0 (#1804): the picture change right after the rename joins bob's unread rename item: one item, no second "changed the icon" line
  // 2.152.2 (#2624): project instead of list
  check(!/Alice changed the icon or colour of the project/.test(wb.document.body.textContent) && (wb.document.body.textContent.match(/Alice renamed the project Bob Team to/g) || []).length === 1,
    '#1795: ... and the picture change joined that one item (#1804)');
  wb.close();

  // ================= Firefox: the phone (390, touch)
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
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { oadmOpen(${ORG}, 'Org'); return 1; })()`); await sleep(1200);
    await ev(`(() => { const b = document.querySelector('.oadmmd .oadmrow[data-olid="${BT}"] [data-oa="edit"]'); b && b.click(); return 1; })()`); await sleep(900);
    const g = await ev(`(() => { const c = document.querySelector('.olemd .card'); if (!c) return null; const r = c.getBoundingClientRect();
      const s = document.querySelector('.olemd [data-m="save"]').getBoundingClientRect();
      return {left: r.left, right: r.right, save: Math.min(s.width, s.height), wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide, `${tag}: #1795 the edit dialog fits the phone ` + JSON.stringify(g));
    check(g && g.save >= 44, `${tag}: #1795 Save >= 44 px ` + JSON.stringify(g));
    await shot('p256b-390-orglist-edit.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
