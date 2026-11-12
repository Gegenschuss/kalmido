// 2.1052.0 (#5808): News show ONE way, bundled per task; "For you" has one definition, the server's (to_me). jsdom, own container (start.sh):
// kalmido-suite: fresh
// - a bundle stands under "For you" when at least one unread entry in it is to_me (a task with a plain comment AND a mention of me
//   stands there as one bundle); a task with only a plain comment stands in the history
// - the number at "For you" = the bell's number, in the bell's window and in the News view
// - no toggle "Bundled" any more; a device that kept the old setting newsBundle = false still sees the bundles (it is not read)
// - usable: the bundle shows the task's title, a click on a single bundle opens the task, a click on a bundle of two opens its entries;
//   the tab Activity shows only the calm bundles
// freelancer-matrix: n/a - nur Oberfläche (no route changed; the server's to_me as a person without an organisation: p21037_b_due_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21052_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, ms = 15000) => require('./boot').until(fn, {timeout: ms, step: 150});
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const groupOf = (root, title) => [...root.querySelectorAll('.ngroup')].find(g => g.querySelector('.ngt')?.textContent.includes(title));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ALL.split(',').filter(x => x !== 'collab')});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done'}, CB);
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Write the homepage text', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Call the printer', list_id: L})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Order the flyers', list_id: L})).id;
  await call('POST', `/api/tasks/${T1}/comments`, {body: 'First draft is in'}, CB);  // not for me: history
  await call('POST', `/api/tasks/${T2}/comments`, {body: '<@1> can you call them?'}, CB);  // for me
  await call('POST', `/api/tasks/${T3}/comments`, {body: 'Prices are in the sheet'}, CB);  // not for me ...
  await call('POST', `/api/tasks/${T3}/comments`, {body: '<@1> which paper do we take?'}, CB);  // ... but this one is: the bundle is for me
  const srv = await call('GET', '/api/news');
  const meIds = (srv.items || []).filter(it => !it.read && it.to_me).map(it => it.task_id);
  check(meIds.includes(T2) && meIds.includes(T3) && !meIds.includes(T1), 'setup: the server marks the mentions to_me, the plain comment not: ' + JSON.stringify((srv.items || []).map(it => [it.kind, it.task_id, it.to_me])));
  const nMe = String(srv.unread_me);

  // ================= the bell's window, on a device that kept the old setting "plain list"
  let w = await boot({user: 'alice', ls: {'tasks.newsBundle': 'false', 'tasks.newsHist': 'true'}}), d = w.document;
  const bell = () => d.querySelector('#kbar .bell');
  check(bell()?.querySelector('.nbadge')?.textContent === nMe, `the bell counts what waits for me (${nMe}): ` + bell()?.querySelector('.nbadge')?.textContent);
  click(w, bell()); await until(() => d.querySelector('#pop .bpop .ngroup'));
  let pop = d.querySelector('#pop .bpop'), me = pop.querySelector('.nsect.me'), hist = pop.querySelector('.nsect.nhist');
  check(pop.querySelector('.bplist.nbund') && !pop.querySelector('.nsec'), 'the old setting newsBundle = false is not read: the bell shows the bundles');
  check(me && me.querySelector('.nsh .c')?.textContent === nMe, 'For you in the bell carries the bell\'s number: ' + me?.querySelector('.nsh')?.textContent);
  check(groupOf(me, 'Call the printer')?.classList.contains('needs') && groupOf(me, 'Order the flyers')?.classList.contains('needs'), 'both bundles with a mention of me stand under For you');
  check(!groupOf(me, 'Write the homepage text') && groupOf(hist, 'Write the homepage text'), 'the task with only a plain comment stands in the history, not under For you');
  check(me.querySelectorAll('.ngroup').length === 2, 'For you holds exactly the two bundles: ' + [...me.querySelectorAll('.ngt')].map(x => x.textContent).join(' | '));
  click(w, d.querySelector('#pop [data-bp="all"]')); await until(() => w.eval('S.route.mod') === 'news' && d.querySelector('#view .ngroup'));

  // ================= the News view: one way, no toggle
  let v = d.querySelector('#view');
  check(!v.querySelector('[data-act="news-bundle"]') && !/Bundled/.test(v.querySelector('.nbar')?.textContent || ''), 'no toggle "Bundled" in the News bar');
  check(v.querySelector('.nbund') && !v.querySelector('.nsec') && v.querySelector('.nsect.me .nsh .c')?.textContent === nMe, 'News view: the bundles, For you with the bell\'s number');
  check(groupOf(v.querySelector('.nsect.me'), 'Call the printer') && groupOf(v.querySelector('.nsect.nhist'), 'Write the homepage text'), 'News view: the same split as the bell');
  // a bundle of two opens its entries, both readable
  const g3 = groupOf(v, 'Order the flyers');
  if (g3?.querySelector('[data-act="news-group"]')) {
    click(w, g3.querySelector('[data-act="news-group"]')); await until(() => groupOf(d.querySelector('#view'), 'Order the flyers')?.querySelector('.ngitems .nitem'));
    const rows = [...(groupOf(d.querySelector('#view'), 'Order the flyers')?.querySelectorAll('.ngitems .nitem') || [])];
    check(rows.length === 2 && rows.some(r => /which paper/.test(r.textContent)) && rows.some(r => /Prices are in the sheet/.test(r.textContent)), 'the bundle of two opens its two entries with their text');
  } else check(g3 && /which paper|Prices/.test(g3.textContent), 'the flyers bundle shows what was written: ' + g3?.textContent);
  // a single bundle opens the task
  click(w, groupOf(d.querySelector('#view'), 'Call the printer').querySelector('.ngmain')); await until(() => w.eval('S.sel') === T2);
  check(w.eval('S.sel') === T2, 'a click on the bundle opens its task');
  w.eval('closeDetail()'); await until(() => !w.eval('S.sel'));
  // the tab Activity: only the calm bundles
  click(w, d.querySelector('.ntabs [data-tab="act"]')); await until(() => d.querySelector('.ntabs [data-tab="act"].on') && d.querySelector('#view .nbund'));
  v = d.querySelector('#view');
  check(!v.querySelector('.nsect.me') && groupOf(v, 'Write the homepage text') && !groupOf(v, 'Call the printer'), 'Activity: only the calm bundles, nothing for me');
  w.close();

  console.log(`p21052_news_one_ui: ${ok} ok, ${F.length} failed`);
  if (F.length) { console.log('FAILED:\n- ' + F.join('\n- ')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
