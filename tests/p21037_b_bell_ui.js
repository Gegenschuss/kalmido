// 2.1037.0 (#5807, #5801): the bell's window is calm and its numbers are unambiguous. jsdom, own container (start.sh):
// kalmido-suite: fresh
// #5807 "For you" always on top (empty: "Nothing waits for you"), "Also new" / "Read" one folded history without the unread
//       look (no stripe class, no tick, no count); open / folded is kept by the device and stays after a reload; no number at
//       "Show all"; every filter chip shows its waiting entries; the bell never follows the filter; its label says "Waiting for
//       you: N"; the same For you in the News view and on the start page card
// #5801 the deadline line "1 task due today" at the top of For you, counted once at the bell (= the server's unread_me);
//       a click opens Today; the tick hides it for today (bell -1); one more task due today brings it back (the delta)
// freelancer-matrix: n/a - nur Oberfläche (the server side as a person without an organisation: p21037_b_due_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle, testNow} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21037B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, ms = 15000) => require('./boot').until(fn, {timeout: ms, step: 150});
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const berlinDay = () => new Intl.DateTimeFormat('en-CA', {timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit'}).format(testNow());

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
  const D0 = berlinDay();
  const T1 = (await call('POST', '/api/tasks', {title: 'Write the homepage text', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Call the printer', list_id: L, due: D0})).id;
  await call('POST', `/api/tasks/${T1}/comments`, {body: 'First draft is in'}, CB);  // not for me: history
  await call('POST', `/api/tasks/${T2}/comments`, {body: '<@1> can you call them?'}, CB);  // for me
  const srv = await call('GET', '/api/news');
  check(srv.due?.today === 1 && srv.due?.n === 1 && srv.unread_me === 2, `setup: the server counts the mention + one deadline line: ${JSON.stringify(srv.due)} ${srv.unread_me}`);

  // ================= the bell's window (bundled, the one way since #5808)
  let w = await boot({user: 'alice', ls: {'tasks.newsHist': null}}), d = w.document;
  const bell = () => d.querySelector('#kbar .bell');
  check(bell()?.querySelector('.nbadge')?.textContent === '2', '#5801: bell = mention + the deadline line: ' + bell()?.querySelector('.nbadge')?.textContent);
  check(/Waiting for you: 2/.test(bell()?.getAttribute('aria-label') || '') && /Waiting for you: 2/.test(bell()?.title || ''), '#5807: the bell says "Waiting for you: 2" (label + tooltip): ' + bell()?.getAttribute('aria-label'));
  click(w, bell()); await until(() => d.querySelector('#pop .bpop .ngroup, #pop .bpop .nmeempty'));
  let pop = d.querySelector('#pop .bpop'), me = pop.querySelector('.nsect.me');
  check(me && pop.querySelector('.nsect') === me && me.querySelector('.nsh .c')?.textContent === '2', '#5807: For you first, its number = the bell (entries, not bundles): ' + me?.querySelector('.nsh')?.textContent);
  const due = me?.querySelector('.ndue');
  check(due && /1 task due today/.test(due.textContent) && due.querySelector('a[href="#today"]') && me.firstElementChild.nextElementSibling === due, '#5801: "1 task due today" on top of For you, opens Today');
  check(me?.querySelector('.ngroup.needs.unread') && /Call the printer/.test(me.textContent), '#5807: the mention stands in For you');
  const hist = pop.querySelector('.nhist');
  check(hist && hist.querySelector('[data-act="news-hist"][aria-expanded="false"]') && !hist.querySelector('.ngroup, .nitem') && !/Also new/.test(pop.textContent), '#5807: the rest is a folded history (no Also new)');
  check(!pop.querySelector('.bpfoot .bpn') && /^Show all$/.test(pop.querySelector('[data-bp="all"]').textContent.trim()), '#5807: no number at "Show all"');
  const chip = k => pop.querySelector(`.nchip[data-bpk="${k}"]`);
  check(chip('')?.querySelector('.nchipn')?.textContent === '2' && chip('mention')?.querySelector('.nchipn')?.textContent === '1' && chip('comment') && !chip('comment').querySelector('.nchipn'), '#5807: every chip shows its waiting entries (All 2, Mentions 1, Comments none)');
  // open the history: calm rows, kept by the device
  click(w, hist.querySelector('[data-act="news-hist"]')); await idle(w);
  pop = d.querySelector('#pop .bpop');
  const hg = [...pop.querySelectorAll('.nhist .ngroup')];
  check(hg.length >= 1 && hg.every(g => !g.classList.contains('unread') && !g.querySelector('.ngn, [data-act="news-gread"]')) && pop.querySelector('.nhist [aria-expanded="true"]'), '#5807: the open history has no unread look, no tick, no count');
  check(w.__store['tasks.newsHist'] === 'true', '#5807: open / folded is kept per device');
  // a filter never moves the bell
  click(w, chip('comment')); await idle(w);
  check(bell()?.querySelector('.nbadge')?.textContent === '2', '#5807: the bell does not follow the filter');
  click(w, d.querySelector('#pop .nchip[data-bpk=""]')); await idle(w);
  // seen for today
  click(w, d.querySelector('#pop .ndue [data-act="due-seen"]')); await idle(w);
  check(bell()?.querySelector('.nbadge')?.textContent === '1' && !d.querySelector('#pop .ndue'), '#5801: seen for today: the line goes, the bell -1');
  check((await call('GET', '/api/news')).due?.n === 0, '#5801: the server holds the mark');
  // one more task due today (another device) -> the line comes back with the delta
  await call('POST', '/api/tasks', {title: 'Order the paper', list_id: L, due: D0});
  await until(() => bell()?.querySelector('.nbadge')?.textContent === '2', 20000);
  if (!d.querySelector('#pop .ndue')) { if (d.querySelector('#pop:not(.hidden) .bpop')) { click(w, bell()); await idle(w); } click(w, bell()); await until(() => d.querySelector('#pop .bpop .ndue')); }  // a full reload of the state leaves an open window as it was
  check(bell()?.querySelector('.nbadge')?.textContent === '2' && /2 tasks due today/.test(d.querySelector('#pop .ndue')?.textContent || ''), '#5801: one more task due today brings the line back: ' + bell()?.querySelector('.nbadge')?.textContent);
  w.close();

  // ================= after a reload: the history still open; the News view has the same For you
  // 2.1052.0 (#5808): the News view shows the bundles too (the plain list with its .nsec heads is gone): history rows = calm bundles
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsHist': 'true'}}); d = w.document;
  await until(() => d.querySelector('#view .nhist .ngroup'));
  check(d.querySelector('#view .nhist [aria-expanded="true"]') && [...d.querySelectorAll('#view .nhist .ngroup')].every(r => !r.classList.contains('unread') && !r.querySelector('[data-act="news-gread"]')) && /Write the homepage text/.test(d.querySelector('#view .nhist').textContent), '#5807: after a reload the history is still open, its bundles calm');
  check(d.querySelector('#view .nsect.me .nsh .c')?.textContent === '2' && d.querySelector('#view .nsect.me .ndue') && /Call the printer/.test(d.querySelector('#view .nsect.me .ngroup.needs')?.textContent || ''), '#5807: News view: For you with the bell\'s number, the deadline line and the mention');
  const tabs = [...d.querySelectorAll('#view .ntabs button')].map(b => b.querySelector('.c')?.textContent || '');
  check(tabs[0] === '2' && tabs[1] === '2' && tabs[2] === '', '#5807: tabs count only what waits (All 2, For you 2, Activity none): ' + tabs.join('/'));
  click(w, d.querySelector('#view [data-act="news-hist"]')); await idle(w);
  check(!d.querySelector('#view .nhist .ngroup, #view .nhist .nitem') && w.__store['tasks.newsHist'] === 'false', '#5807: folded again');  // 2.1052.0 (#5808): bundles
  // everything read + the lines seen: For you stays and says so
  await call('POST', '/api/news/read', {all: true}); await call('POST', '/api/news/due-seen', {line: 'today'});
  w.close();
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsHist': null}}); d = w.document;
  await until(() => d.querySelector('#view .nmeempty'));
  check(/Nothing waits for you/.test(d.querySelector('#view .nsect.me')?.textContent || '') && !d.querySelector('#kbar .bell .nbadge'), '#5807: empty For you: "Nothing waits for you", no number at the bell');
  click(w, d.querySelector('#kbar .bell')); await until(() => d.querySelector('#pop .bpop .nmeempty'));
  check(/Nothing waits for you/.test(d.querySelector('#pop .bpop .nsect.me')?.textContent || ''), '#5807: the bell\'s window too');
  w.close();
  // the start page card
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => /Nothing waits for you/.test(d.querySelector('#view')?.textContent || ''), 10000);
  check(/Nothing waits for you/.test(d.querySelector('#view')?.textContent || '') && !/News: nothing new/.test(d.querySelector('#view')?.textContent || ''), '#5807: start page: "Nothing waits for you"');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
