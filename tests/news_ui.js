// News UI tests (jsdom). Needs the api_test.py DB (alice en, bob de, carol, eve collab off).
const {boot, errs, sleep, until, idle, readState} = require('./boot');  // 2.358.0 C (#2782): idle(w) instead of fixed sleeps
const ids = readState('ids.json');  // 2.609.0 (#4512): from the test data folder
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
  // 2.1037.0 (#5801): alice's tasks due today / overdue are deadline lines at the bell; seen for today, the counts here stay the News ones
  { const wa = await boot({user: 'alice', wait: 800}); for (const line of ['today', 'overdue']) await api(wa, 'POST', '/api/news/due-seen', {line}); wa.close(); }
  let w = await boot({user: 'alice'}), d = w.document;
  const st = await api(w, 'GET', '/api/news');
  const bell = d.querySelector('#kbar .bell');  // 2.152.3 (#2619): the bell moved into the head bar
  // 2.28.0 (#987): the bell and the sidebar count only what people sent me (unread_me), the News view shows everything
  const nMe = st.unread_me;
  check(bell && (nMe ? bell.querySelector('.nbadge')?.textContent === String(nMe) : !bell.querySelector('.nbadge')) && st.unread > 0, `bell with badge ${nMe} (for me) of ${st.unread}`);
  check((d.querySelector('#side .srow[data-go="news"] .c')?.textContent || '') === String(nMe || ''), 'sidebar News row with count');
  // 2.6.1 (#403): the bell opens a dropdown with the newest News; "Show all" goes to #news
  const mod0 = w.eval('S.route.mod');
  bell.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await idle(w);
  // 2.1052.0 (#5808): News show one way, bundled per task: a bundle .ngroup, its head .ngmain (one entry: opens it; several:
  // unfolds them as .ngitems .nitem)
  check(w.eval('S.route.mod') === mod0 && d.querySelector('#pop:not(.hidden) .bpop .ngroup .ngmain .ngt')?.textContent, 'bell opens the dropdown with the bundles, the view stays');
  d.querySelector('#pop [data-bp="all"]').dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await idle(w);
  check(w.eval('S.route.mod') === 'news' && d.querySelector('#top h1').textContent === 'News' && d.querySelector('#pop').classList.contains('hidden'), '"Show all" opens #news');
  // 2.1052.0 (#5808): the bundles instead of the plain rows: every item of the feed stands in exactly one shown bundle; the
  // task ST (bob's mention + carol's comment) is one unread bundle under "For you" with its title, what happened and the time;
  // a click on its head unfolds the entries (the texts, my mention), a click on an entry opens the task
  const gItems = () => JSON.parse(w.eval(`JSON.stringify((() => { const gs = newsGroups((S.nf.items || []).map((it, i) => [it, i]));
    return [...document.querySelectorAll('#view .ngroup')].map(el => (gs.find(g => g.key === el.dataset.gk)?.items || []).map(([it, i]) => ({i, kind: it.kind, task_id: it.task_id}))); })())`));
  const groups = gItems(), covered = groups.flat().map(x => x.i).sort((a, b) => a - b);
  check(groups.length > 0 && groups.every(g => g.length) && covered.length === st.items.length && new Set(covered).size === covered.length, `bundles cover every item once ${covered.length}/${st.items.length} in ${groups.length}`);
  const stG = () => d.querySelector(`#view .nsect.me .ngroup[data-gk="t${ids.ST}u"]`);
  const stTitle = st.items.find(x => x.task_id === ids.ST)?.task_title;
  check(stG() && stTitle && stG().querySelector('.ngt').textContent.includes(stTitle), 'task title shown on its bundle under "For you": ' + stG()?.querySelector('.ngt')?.textContent);
  check(/\d+ mentions?/.test(stG()?.querySelector('.ngs')?.textContent) && /\d+ comments?/.test(stG()?.querySelector('.ngs')?.textContent), 'English summary: ' + stG()?.querySelector('.ngs')?.textContent);
  check(stG()?.classList.contains('unread') && stG().querySelector('.ngs time')?.textContent === 'just now', 'unread accent + relative time');
  check(!d.querySelector('#fab') || d.querySelector('#fab').classList.contains('gone'), 'no FAB on News');
  stG().querySelector('.ngmain').dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await idle(w);
  let rows = [...(stG()?.querySelectorAll('.ngitems .nitem') || [])];
  check(rows.length >= 2 && rows.length === groups.find(g => g.some(x => x.task_id === ids.ST && !st.items[x.i]?.read))?.length && stG().querySelector('.ngmain').getAttribute('aria-expanded') === 'true', `a click unfolds the bundle (${rows.length} entries)`);
  check(rows.some(r => /Robin|Bob/.test(r.textContent)) && /mentioned you/.test(stG()?.textContent), 'English texts');
  check(stG()?.querySelector('.nitem .mention.me'), 'my mention highlighted in the excerpt');
  check(rows[0].classList.contains('unread') && rows[0].querySelector('time').textContent === 'just now', 'unfolded entry: unread accent + relative time');
  // click opens the task and marks it read
  const first = st.items[0];
  const clicked = JSON.parse(w.eval(`JSON.stringify(S.nf.items[${+rows[0].dataset.i}] || null)`) || 'null');  // 2.80.1: the row's own item
  rows[0].dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await idle(w);
  check(w.eval('S.sel') === (clicked?.task_id ?? first.task_id), 'click opens the task');
  // 2.80.1: by meaning instead of by count (CI saw 4 -> 1 and 4 -> 3, the Mac passes; items with the same time can come
  // in another order in the client's list than in the test's request): the clicked row's own items are read, items of
  // other tasks stay unread; the message lists the items that differ
  const st2 = await api(w, 'GET', '/api/news');
  const cids = clicked?.ids || [];
  const stillOpen = cids.filter(i => !st2.items.find(x => x.id === i)?.read);
  const nowRead = st.items.filter(x => x.task_id !== clicked?.task_id && !x.read && st2.items.find(y => y.id === x.id)?.read).map(x => x.id);
  check(cids.length && !stillOpen.length && !nowRead.length && st2.unread <= st.unread - 1,
    `click marks read (${st.unread} -> ${st2.unread}; clicked ${cids.join(',') || '?'}, still unread: ${stillOpen.join(',') || '-'}; other tasks read too: ${nowRead.join(',') || '-'}; `
    + `before: ${st.items.map(x => `${x.id}/${x.task_id}/${x.kind}/${x.read ? 'r' : 'u'}`).join(' ')})`);
  w.eval('closeDetail()'); await sleep(200);
  // filter
  // 1.9.0: "Mentions & assigned to me" (mentions + assignments) replaced "Only mentions"
  d.querySelector('[data-act="news-filter"][data-f="me"]').click(); await idle(w);
  // 2.1052.0 (#5808): the kinds of the entries in the shown bundles
  const ks = gItems().flat().map(x => x.kind);
  check(ks.length > 0 && ks.every(k => ['mention', 'assign', 'unassign'].includes(k)), 'mentions & assigned to me filter: ' + ks);
  check(w.__store['tasks.newsFilter'] === '"me"', 'filter remembered per device');
  d.querySelector('[data-act="news-filter"][data-f=""]').click(); await idle(w);
  // old task not in state: fetched on demand
  const tgt = st.items.find(x => x.task_id)?.task_id;
  w.eval(`S.tasks.delete(${tgt})`);
  // 2.139.1 (#2405): the list is grouped in sections (For you / Also new / Read), so a row's place is not its item index; data-i is
  // 2.1052.0 (#5808): a bundle of one entry opens it from its head; one of several unfolds first
  const rowOf = () => [...d.querySelectorAll('#view .ngmain[data-i], #view .ngitems .nitem[data-i]')].find(r => w.eval(`S.nf.items[${r.dataset.i}].task_id`) === tgt);
  if (!rowOf()) { d.querySelector(`#view .ngroup[data-gk^="t${tgt}"] .ngmain`)?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await idle(w); }
  const row = rowOf();
  row.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await idle(w);
  check(w.eval('S.sel') === tgt && d.querySelector('#detail #d-title, #detail .dtop'), 'task outside the state opened via GET /api/tasks/<id>');
  w.eval('closeDetail()'); await sleep(200);
  // mark all read
  d.querySelector('[data-act="news-readall"]')?.click(); await idle(w);
  check(!d.querySelector('#kbar .bell .nbadge') && !d.querySelector('#view .ngroup.unread') && (await api(w, 'GET', '/api/news')).unread === 0, 'mark all as read clears the badge');  // 2.152.3 (#2619): the bell moved into the head bar
  // two users: bob mentions alice while alice's window polls
  wb = await boot({user: 'bob', wait: 800});
  await api(wb, 'POST', `/api/tasks/${ids.ST}/comments`, {body: '<@1> once more'});
  // CI of 2.307.7: wait for the poll's result instead of a fixed 5.5 s (poll every 4 s + version + news fetch + render)
  await until(() => d.querySelector('#kbar .bell .nbadge')?.textContent === '1' && d.querySelectorAll('#view .ngroup.unread').length === 1);  // 2.1052.0 (#5808): the bundle
  check(d.querySelector('#kbar .bell .nbadge')?.textContent === '1', 'badge updates within the poll');  // 2.152.3 (#2619): the bell moved into the head bar
  check(d.querySelectorAll('#view .nsect.me .ngroup.unread').length === 1 && /once more/.test(d.querySelector('#view .nsect.me .ngroup.unread .ngex')?.textContent), 'open News view refreshes');  // 2.1052.0 (#5808): the bundle under "For you" with the new excerpt
  // read on another device -> badge goes away via the version signature
  await api(w, 'POST', '/api/news/read', {all: true}); w.eval('S.news.sig = "stale"');
  await until(() => !d.querySelector('#kbar .bell .nbadge'));
  check(!d.querySelector('#kbar .bell .nbadge'), 'signature change reloads the badge');  // 2.152.3 (#2619): the bell moved into the head bar
  w.close();
  // bob: German, mobile, tab bar
  w = await boot({user: 'bob', mobile: true, hash: 'news', ls: {'tasks.tabbar': JSON.stringify(['m:tasks', 'news', 'm:cal'])}}); d = w.document;
  await idle(w);
  const txt = d.querySelector('#view').textContent + d.querySelector('#top').textContent;
  check(d.querySelector('#top h1').textContent === 'Neuigkeiten', 'German title');
  // 2.1052.0 (#5808): the bundles say what happened in their summary line ("2 Kommentare", "dir zugewiesen"), entries of one their text
  check(/hat dich erwähnt|hat kommentiert|Kommentare von|hat dir eine Aufgabe zugewiesen|\d+ Erwähnung|\d+ Kommentar|dir zugewiesen/.test(txt), 'German item texts: ' + [...d.querySelectorAll('#view .ngs')].map(x => x.textContent).join(' | ').slice(0, 200));
  // 2.152.2 (#2624): project instead of list
  const left = ['mentioned you', 'commented', 'assigned', 'Mark all', 'Only mentions', 'News', 'just now', 'min ago', 'shared the project', 'Loading'].filter(x => txt.includes(x));
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
  check(w.eval(`tabAddGroups().flatMap(g => g.items).map(x => x.id)`).includes('news'), 'tab option "News" available');  // 2.122.2 (#2329): a sheet instead of the select
  // 2.183.0 A (#2623): the summary line of a News group never shows a raw kind ("orgjoin"); unknown kinds say nothing
  const sl = k => w.eval(`newsSummaryLine({items: [[{kind: '${k}', count: 1}, 0]]})`);
  check(/^(Invitation|Einladung)$/.test(sl('orgjoin')), 'an organisation invitation reads "Invitation", not "orgjoin": ' + sl('orgjoin'));
  for (const k of ['evinvite', 'connreq', 'leavereq', 'tsheet', 'signup', 'wiki_shared', 'ptlimit', 'apblimit', 'docpaid', 'docoverdue', 'offerexp', 'orglogin', 'orgjoinres', 'orgrole', 'zzunknown']) check(!sl(k).includes(k), `kind ${k} is not shown raw: ${sl(k)}`);
  check(sl('zzunknown') === '', 'an unknown kind leaves the summary empty');
  // 2.367.4 (#2972, #2974): the new items read as text
  const nt = (k, d) => w.eval(`newsText({kind: '${k}', data: ${JSON.stringify(d)}, actors: []}, {})`);
  check(nt('docpaid', {number: 'RE-1', client: 'Muster AG'}).includes('RE-1, Muster AG'), 'a payment names the invoice');
  check(nt('docoverdue', {n: 3}).includes('3'), 'several overdue invoices: the count');
  check(nt('orgrole', {name: 'Nordwind', role: 'accounting'}).includes('Accounting') || nt('orgrole', {name: 'Nordwind', role: 'accounting'}).includes('Buchhaltung'), 'a new role by its name');
  w.close();
  console.log(`\n${ok} ok, ${F.length} failed`);
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  process.exit(F.length || errs.length ? 1 : 0);
})();
