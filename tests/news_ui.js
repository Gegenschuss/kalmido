// News UI tests (jsdom). Needs the api_test.py DB (alice en, bob de, carol, eve collab off).
const {boot, errs, sleep} = require('./boot');
const ids = require('./ids.json');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const api = async (w, method, url, body) => (await w.fetch(url, {method, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: body ? JSON.stringify(body) : undefined})).json();
(async () => {
  // fresh events for alice: bob mentions her, carol comments, bob completes nothing
  let wb = await boot({user: 'bob', wait: 800});
  await api(wb, 'POST', `/api/tasks/${ids.ST}/comments`, {body: `<@1> the **numbers** are in`});
  const wc = await boot({user: 'carol', wait: 800});
  await api(wc, 'POST', `/api/tasks/${ids.ST}/comments`, {body: 'Looks good'});
  wc.close(); wb.close();
  let w = await boot({user: 'alice'}), d = w.document;
  const st = await api(w, 'GET', '/api/news');
  const bell = d.querySelector('#top .bell');
  check(bell && bell.querySelector('.nbadge')?.textContent === String(st.unread) && st.unread > 0, `bell with badge ${st.unread}`);
  check(d.querySelector('#side .srow[data-go="news"] .c')?.textContent === String(st.unread), 'sidebar News row with count');
  // 2.6.1 (#403): the bell opens a dropdown with the newest News; "Show all" goes to #news
  const mod0 = w.eval('S.route.mod');
  bell.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await sleep(700);
  check(w.eval('S.route.mod') === mod0 && d.querySelector('#pop:not(.hidden) .bpop .nitem'), 'bell opens the dropdown, the view stays');
  d.querySelector('#pop [data-bp="all"]').dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await sleep(700);
  check(w.eval('S.route.mod') === 'news' && d.querySelector('#top h1').textContent === 'News' && d.querySelector('#pop').classList.contains('hidden'), '"Show all" opens #news');
  let rows = [...d.querySelectorAll('#view .nitem')];
  check(rows.length === st.items.length && rows.length > 0, `rows rendered ${rows.length}/${st.items.length}`);
  check(/Robin|Bob/.test(rows[1]?.textContent) && /mentioned you/.test(d.querySelector('#view').textContent), 'English texts');
  check(d.querySelector('#view .nitem .mention.me'), 'my mention highlighted in the excerpt');
  check(rows[0].classList.contains('unread') && rows[0].querySelector('time').textContent === 'just now', 'unread accent + relative time');
  check(d.querySelector('#view .nitem .ntask .nt')?.textContent, 'task title shown');
  check(!d.querySelector('#fab') || d.querySelector('#fab').classList.contains('gone'), 'no FAB on News');
  // click opens the task and marks it read
  const first = st.items[0];
  rows[0].dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await sleep(800);
  check(w.eval('S.sel') === first.task_id, 'click opens the task');
  const st2 = await api(w, 'GET', '/api/news');
  check(st2.items[0].read && st2.unread === st.unread - 1 - (st.items.filter(x => x.task_id === first.task_id && !x.read).length - 1), `click marks read (${st.unread} -> ${st2.unread})`);
  w.eval('closeDetail()'); await sleep(200);
  // filter
  // 1.9.0: "Mentions & assigned to me" (mentions + assignments) replaced "Only mentions"
  d.querySelector('[data-act="news-filter"][data-f="me"]').click(); await sleep(700);
  rows = [...d.querySelectorAll('#view .nitem')];
  check(rows.length > 0 && rows.every(r => ['k-mention', 'k-assign', 'k-unassign'].some(k => r.classList.contains(k))), 'mentions & assigned to me filter');
  check(w.__store['tasks.newsFilter'] === '"me"', 'filter remembered per device');
  d.querySelector('[data-act="news-filter"][data-f=""]').click(); await sleep(700);
  // old task not in state: fetched on demand
  const tgt = st.items.find(x => x.task_id)?.task_id;
  w.eval(`S.tasks.delete(${tgt})`);
  const idx = [...d.querySelectorAll('#view .nitem')].findIndex((r, i) => w.eval(`S.nf.items[${i}].task_id`) === tgt);
  d.querySelectorAll('#view .nitem')[idx].dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await sleep(900);
  check(w.eval('S.sel') === tgt && d.querySelector('#detail #d-title, #detail .dtop'), 'task outside the state opened via GET /api/tasks/<id>');
  w.eval('closeDetail()'); await sleep(200);
  // mark all read
  d.querySelector('[data-act="news-readall"]')?.click(); await sleep(700);
  check(!d.querySelector('#top .bell .nbadge') && !d.querySelector('#view .nitem.unread') && (await api(w, 'GET', '/api/news')).unread === 0, 'mark all as read clears the badge');
  // two users: bob mentions alice while alice's window polls
  wb = await boot({user: 'bob', wait: 800});
  await api(wb, 'POST', `/api/tasks/${ids.ST}/comments`, {body: '<@1> once more'});
  await sleep(5500);
  check(d.querySelector('#top .bell .nbadge')?.textContent === '1', 'badge updates within the poll');
  check(d.querySelectorAll('#view .nitem.unread').length === 1, 'open News view refreshes');
  // read on another device -> badge goes away via the version signature
  await api(w, 'POST', '/api/news/read', {all: true}); w.eval('S.news.sig = "stale"');
  await sleep(5000);
  check(!d.querySelector('#top .bell .nbadge'), 'signature change reloads the badge');
  w.close();
  // bob: German, mobile, tab bar
  w = await boot({user: 'bob', mobile: true, hash: 'news', ls: {'tasks.tabbar': JSON.stringify(['m:tasks', 'news', 'm:cal'])}}); d = w.document;
  await sleep(600);
  const txt = d.querySelector('#view').textContent + d.querySelector('#top').textContent;
  check(d.querySelector('#top h1').textContent === 'Neuigkeiten', 'German title');
  check(/hat dich erwähnt|hat kommentiert|Kommentare von|hat dir eine Aufgabe zugewiesen/.test(txt), 'German item texts');
  const left = ['mentioned you', 'commented', 'assigned', 'Mark all', 'Only mentions', 'News', 'just now', 'min ago', 'shared the list', 'Loading'].filter(x => txt.includes(x));
  check(!left.length, 'no English leftovers (de): ' + left);
  const tab = d.querySelector('#tabs button[data-go="news"]');
  check(tab && tab.classList.contains('on') && /Neuigkeiten/.test(tab.textContent), 'News pinned in the mobile tab bar, active');
  w.eval('settingsModal()'); await sleep(300);
  check(!![...d.querySelectorAll('#s-tabbar [data-tab="news"]')].length, 'settings list shows the pinned News tab');
  d.querySelector('.modal')?.remove();
  w.eval(`LS.set('tabbar', ['m:tasks', 'm:cal', 'm:matrix', 'm:habits', 'm:pomo', 's:today']); render()`);
  w.eval(`tabsMore(document.querySelector('[data-act="tabs-more"]'))`); await sleep(200);
  check(/Neuigkeiten/.test(d.querySelector('#pop, .menu-list')?.textContent || ''), '"More" offers News');
  w.eval(`settingsModal()`); await sleep(300);
  check([...d.querySelectorAll('#s-tabadd option')].some(o => o.value === 'news'), 'tab option "News" available');
  w.close();
  console.log(`\n${ok} ok, ${F.length} failed`);
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  process.exit(F.length || errs.length ? 1 : 0);
})();
