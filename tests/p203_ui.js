// 2.0.3 UI tests (jsdom), fresh DB: #305 the comment box stays visible under the newest comment (2.0.6: no folding any
// more, the box at the bottom edge of the panel); #302 News "Unread only" (hides read items, remembered per device, German text); #286 iOS home-screen app:
// status bar "black" (the page starts below it), no bottom-edge shift, manifest / theme colours match the tab bar.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const cks = {};
const call = async (u, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cks[u]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  cks.alice = await login('alice');
  const bob = (await call('alice', 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  cks.bob = await login('bob');
  for (const u of ['alice', 'bob']) await call(u, 'PATCH', '/api/settings', {features: 'kanban,timeline,collab,comments', lang: 'en'});
  const me = 1;  // alice = the setup account
  const L = (await call('alice', 'POST', '/api/lists', {name: 'Film'})).id;
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: bob, role: 'edit'});
  const T1 = (await call('alice', 'POST', '/api/tasks', {title: 'Cut trailer', list_id: L})).id;
  const T2 = (await call('alice', 'POST', '/api/tasks', {title: 'Colour grade', list_id: L})).id;
  for (const b of ['First note', 'Second note', 'Newest note']) await call('bob', 'POST', `/api/tasks/${T1}/comments`, {body: b});
  await call('bob', 'POST', `/api/tasks/${T2}/comments`, {body: `<@${me}> please check the grade`});

  // ---- #305 the comment box always visible; 2.0.6: no folding any more, the box at the bottom edge
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`openDetail(${T1})`); await sleep(1300);
  let tl = d.querySelector('#d-tl');
  const vis = el => !!el && w.getComputedStyle(el).display !== 'none';
  const cms = [...tl.querySelectorAll('.cm')];
  check(cms.length === 3 && cms.every(vis) && !tl.classList.contains('fold'), 'all comments show (no folding)');
  const comp = d.querySelector('#detail .dbot .ccomp');
  check(vis(comp) && vis(comp.querySelector('#c-input')), 'the comment box is visible');
  check(cms[2].compareDocumentPosition(comp) & w.Node.DOCUMENT_POSITION_FOLLOWING, 'the box sits below the newest comment');
  const inp = d.querySelector('#c-input');
  inp.value = 'Draft text'; inp.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(100);
  check(comp.classList.contains('used'), 'a draft opens the bar (files, Send)');
  const inp2 = d.querySelector('#c-input');  // (a sync may have re-rendered the panel)
  inp2.value = 'A new comment'; inp2.dispatchEvent(new w.Event('input', {bubbles: true}));
  d.querySelector('[data-act="c-send"]').click(); await sleep(1200);
  tl = d.querySelector('#d-tl');
  const last = tl.querySelector('.cm.last');
  check(/A new comment/.test(last?.textContent || '') && vis(last) && d.querySelector('#c-input').value === '', 'sent: the new comment is the last one, the box is empty');
  w.eval('closeDetail()'); await sleep(200);
  w.close();

  // ---- #302 News: Unread only
  const n0 = await call('alice', 'GET', '/api/news');
  const t1item = n0.items.find(x => x.task_id === T1);
  check(n0.items.length >= 2 && t1item, `alice has news (${n0.items.length})`);
  await call('alice', 'POST', '/api/news/read', {ids: t1item.ids});
  w = await boot({user: 'alice', hash: 'news'}); d = w.document; await sleep(600);
  let rows = [...d.querySelectorAll('#view .nitem')];
  check(rows.length === n0.items.length && rows.some(r => !r.classList.contains('unread')), 'All: read and unread items');
  const tog = d.querySelector('#view .nbar [data-act="news-unread"]');
  check(tog && tog.textContent.trim() === 'Unread only' && tog.getAttribute('aria-pressed') === 'false', 'toggle "Unread only" next to the filter, off');
  tog.click(); await sleep(200);
  rows = [...d.querySelectorAll('#view .nitem')];
  check(rows.length === n0.items.length - 1 && rows.every(r => r.classList.contains('unread')), 'on: read items hidden');
  check(d.querySelector('[data-act="news-unread"]').classList.contains('on') && d.querySelector('[data-act="news-unread"]').getAttribute('aria-pressed') === 'true' && w.__store['tasks.newsUnread'] === 'true', 'on state, remembered per device');
  const i0 = +rows[0].dataset.i, want = w.eval(`S.nf.items[${i0}].task_id`);
  rows[0].dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true})); await sleep(800);
  check(w.eval('S.sel') === want, 'click on a filtered row opens the right task (index kept)');
  w.eval('closeDetail()'); await sleep(300);
  check([...d.querySelectorAll('#view .nitem')].length === rows.length, 'the item opened just now stays until the next load');
  d.querySelector('[data-act="news-filter"][data-f="me"]').click(); await sleep(700);
  check(d.querySelector('[data-act="news-unread"]').classList.contains('on'), 'combines with "Mentions & assigned to me"');
  d.querySelector('[data-act="news-filter"][data-f=""]').click(); await sleep(700);
  w.close();
  await call('alice', 'POST', '/api/news/read', {all: true});
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsUnread': 'true'}}); d = w.document; await sleep(600);
  check(!d.querySelectorAll('#view .nitem').length && /No unread news/.test(d.querySelector('#view').textContent), 'all read: "No unread news"');
  w.close();
  await call('alice', 'PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsUnread': 'true'}}); d = w.document; await sleep(600);
  check(d.querySelector('[data-act="news-unread"]')?.textContent.trim() === 'Nur ungelesene' && /Keine ungelesenen Neuigkeiten/.test(d.querySelector('#view').textContent), 'German: Nur ungelesene');
  w.close();
  await call('alice', 'PATCH', '/api/settings', {lang: 'en'});

  // ---- #286 iOS home-screen app
  w = await boot({user: 'alice', mobile: true, hash: 'inbox'}); d = w.document;
  check(d.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]')?.content === 'black', 'status bar style "black" (page starts below it)');
  check(!d.documentElement.classList.contains('iosgap') && w.eval('typeof iosGapSync') === 'undefined', 'no bottom-edge shift any more');
  check(d.querySelector('meta[name="theme-color"]')?.content === '#16171a', 'theme-color = tab bar colour (dark)');
  w.close();
  const man = await (await fetch(B + 'manifest.json')).json();
  check(man.theme_color === '#16171a' && man.background_color === '#16171a', 'manifest colours = tab bar colour');

  const errList = errs.filter(e => !/Could not load|ECONNREFUSED|NetworkError|ResizeObserver/.test(e));
  check(!errList.length, 'no script errors: ' + errList.slice(0, 3).join(' | '));
  console.log(`p203_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); process.exit(1); });
