// 1.9.0 UI tests (jsdom), fresh DB: Settings > Integrations "Share from your phone" (HTTP Shortcuts download, address +
// token copy, iPhone guide), profile pictures (Settings > Account presets, the picture everywhere the initials were,
// initials as fallback, admin preset for another user), Administration starts with the users, the refresh button of
// shared lists (+ "…" > Refresh on touch, pull-to-refresh), new comments show while typing in the open task, deleting a
// tag from the sidebar (right-click menu, count dialog, undo), dialogs follow the visual viewport (Galaxy Fold keyboard),
// the News inbox (x to remove, swipe on touch, filter "Mentions & assigned to me", which events create News).
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments';
const cks = {};
const call = async (u, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cks[u]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const clip = w => { w.__clip = []; Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: t => { w.__clip.push(t); return Promise.resolve(); }}}); };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Admin', password: 'password123'})});
  cks.alice = await login('alice');
  const bob = (await call('alice', 'POST', '/api/users', {username: 'bob', display_name: 'Bob Builder', password: 'password123'})).id;
  cks.bob = await login('bob');
  for (const u of ['alice', 'bob']) await call(u, 'PATCH', '/api/settings', {features: ALL});
  const SH = (await call('alice', 'POST', '/api/lists', {name: 'Team'})).id;
  const PRIV = (await call('alice', 'POST', '/api/lists', {name: 'Private'})).id;
  await call('alice', 'PUT', `/api/lists/${SH}/members`, {user_id: bob, role: 'edit'});
  const T1 = (await call('alice', 'POST', '/api/tasks', {title: 'Shared job', list_id: SH, assignee_id: bob, tags: ['old', 'keep']})).id;
  await call('alice', 'POST', '/api/tasks', {title: 'Private job', list_id: PRIV, tags: ['old']});
  await call('bob', 'PUT', '/api/me/avatar', {preset: 'headphones'});

  // ---- share from your phone
  let w = await boot({user: 'alice'}), d = w.document; clip(w);
  w.eval(`settingsModal('share')`); await sleep(600);
  const pane = d.querySelector('#sp-integr');
  check(pane && !pane.classList.contains('hidden') && d.querySelector('#s-share-h')?.textContent === 'Share from your phone', 'Settings > Integrations > Share from your phone');
  const zip = d.querySelector('#s-hszip');
  check(zip && zip.getAttribute('href') === '/api/me/share/httpshortcuts.zip' && zip.hasAttribute('download'), 'HTTP Shortcuts download link');
  const zr = await fetch(B + 'api/me/share/httpshortcuts.zip', {headers: {Cookie: cks.alice}});
  check(zr.ok && zr.headers.get('content-type') === 'application/zip', 'the link delivers the ZIP');
  check(d.querySelector('#s-dropurl').value === 'https://kalmido.example', 'server address shown (2.0.2: without /drop, the shortcut adds it)');
  check(d.querySelector('#s-droptok').type === 'password' && !/[A-Za-z0-9_-]{20}/.test(d.querySelector('#s-droptok').value), 'token hidden until copied');
  d.querySelector('[data-m="drop-copy-url"]').click(); await sleep(200);
  d.querySelector('[data-m="drop-copy-tok"]').click(); await sleep(500);
  const tok = (await call('alice', 'GET', '/api/me')).drop_token;
  check(w.__clip[0] === 'https://kalmido.example' && w.__clip[1] === tok, 'copy buttons: address + token ' + JSON.stringify(w.__clip).slice(0, 80));
  check(/Get Contents of URL/.test(pane.textContent) && /Show in Share Sheet/.test(pane.textContent), 'Shortcuts app guide');
  check(!/Add the Kalmido shortcut/.test(pane.textContent), 'no iOS shortcut link while the server has none');
  w.eval(`S.share = {...S.share, ios_shortcut: 'https://kalmido.com/kalmido.shortcut'}`);
  d.querySelector('[data-m="close"]').click(); w.eval(`settingsModal('share')`); await sleep(500);
  const il = [...d.querySelectorAll('#sp-integr a')].find(a => /Add the Kalmido shortcut/.test(a.textContent));
  check(il && il.href === 'https://kalmido.com/kalmido.shortcut' && il.rel.includes('noopener'), 'iOS shortcut link when configured');
  check(!/HTTP Shortcuts app sends them/.test(pane.textContent), 'old developer-box line gone');

  // ---- Administration: users first
  d.querySelector(`[data-sec="users"]`).click(); await sleep(300);
  const h4 = d.querySelector('#sp-users h4');
  check(h4 && h4.textContent === 'Users' && d.querySelector('#sp-users [data-acc="user-new"]'), 'Administration starts with Users (+ New user): ' + h4?.textContent);
  await sleep(400);
  const brow = [...d.querySelectorAll('#a-users .mrow')].find(r => /Bob Builder/.test(r.textContent));
  check(brow?.querySelector('.avatar.pic img')?.getAttribute('src') === '/static/avatars/headphones.svg', 'admin user list shows Bob\'s picture');

  // ---- profile pictures
  d.querySelector(`[data-sec="account"]`).click(); await sleep(300);
  const opts = [...d.querySelectorAll('#a-avpick [data-av]')].map(b => b.dataset.av);
  check(opts.length === 12 && opts.includes('coffee') && opts.includes('robot') && opts.includes('upload') && opts.at(-1) === 'none', 'presets + upload + none: ' + opts);
  check(d.querySelector('#a-avpick [data-av="none"]').classList.contains('on') && d.querySelector('#side .suser .avatar')?.textContent === 'AA', 'no picture yet: initials');
  d.querySelector('#a-avpick [data-av="coffee"]').click(); await sleep(700);
  check(w.eval('S.me.avatar') === '/static/avatars/coffee.svg' && (await call('alice', 'GET', '/api/me')).avatar === '/static/avatars/coffee.svg', 'preset saved');
  check(d.querySelector('#side .suser .avatar.pic img')?.getAttribute('src') === '/static/avatars/coffee.svg', 'sidebar user row shows it');
  check(d.querySelector('#a-avpick [data-av="coffee"]').classList.contains('on') && d.querySelector('.acct .avatar.pic'), 'picker + account row updated');
  // admin sets a preset for bob in the user dialog
  d.querySelector(`[data-sec="users"]`).click(); await sleep(500);
  d.querySelector(`#a-users [data-acc="user-edit"][data-uid="${bob}"]`).click(); await sleep(300);
  const um = [...d.querySelectorAll('.modal')].at(-1);
  check(um.querySelector('#u-avpick [data-av="headphones"]').classList.contains('on') && !um.querySelector('#u-avpick [data-av="upload"]'), 'user dialog: current preset marked, no upload for others');
  um.querySelector('#u-avpick [data-av="robot"]').click(); um.querySelector('[data-m="save"]').click(); await sleep(800);
  check((await call('bob', 'GET', '/api/me')).avatar === '/static/avatars/robot.svg', 'admin changed Bob\'s preset');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  // pictures everywhere: assignee chip, comments, members, mention picker
  await w.eval('load()'); w.eval('render()'); w.eval(`go('l/${SH}')`); await sleep(500);
  const chip = d.querySelector(`.trow[data-id="${T1}"] .who`);
  check(chip?.classList.contains('pic') && chip.querySelector('img')?.getAttribute('src') === '/static/avatars/robot.svg', 'assignee chip shows Bob\'s picture');
  await call('bob', 'POST', `/api/tasks/${T1}/comments`, {body: 'Hello from Bob'});
  w.eval(`openDetail(${T1})`); await sleep(1200);
  const cm = [...d.querySelectorAll('#d-tl .cm')].find(c => /Hello from Bob/.test(c.textContent));
  check(cm?.querySelector('.avatar.pic img')?.getAttribute('src') === '/static/avatars/robot.svg', 'comment shows the author\'s picture');
  // ---- live comments while typing
  const ta = d.querySelector('#c-input'); ta.focus(); ta.value = 'typing…';
  check(w.eval('editing()'), 'typing in the comment box counts as editing');
  await call('bob', 'POST', `/api/tasks/${T1}/comments`, {body: 'Second while you type'});
  await sleep(5500);
  check([...d.querySelectorAll('#d-tl .cm')].some(c => /Second while you type/.test(c.textContent)) && d.querySelector('#c-input').value === 'typing…', 'new comment appears while typing, draft kept');
  ta.blur(); w.eval('closeDetail?.()'); await sleep(300);

  // ---- refresh button (shared list only, desktop)
  w.eval(`go('l/${SH}')`); await sleep(400);
  check(!!d.querySelector('#top [data-act="refresh"]'), 'refresh button on the shared list');
  await call('bob', 'POST', '/api/tasks', {title: 'Added by Bob', list_id: SH});
  d.querySelector('#top [data-act="refresh"]').click(); await sleep(900);
  check(/Added by Bob/.test(d.querySelector('#view').textContent) && /Up to date/.test(d.querySelector('#toast').textContent), 'refresh loads Bob\'s task + "Up to date"');
  w.eval(`go('l/${PRIV}')`); await sleep(400);
  check(!d.querySelector('#top [data-act="refresh"]'), 'no refresh button on a private list');

  // ---- delete a tag from the sidebar
  w.eval(`S.collapsed.add('side:tags-open'); renderSide()`); await sleep(200);
  const trow = d.querySelector('#side .srow[data-drop="tag:old"]');
  check(!!trow, 'tag row in the sidebar');
  trow.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true})); await sleep(200);
  const mi = [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim());
  check(mi.includes('Delete tag…') && d.querySelector('#pop .menu-list button.danger'), 'tag menu: Delete tag… (red): ' + mi);
  let asked = '';
  w.confirm = t => { asked = t; return true; };
  [...d.querySelectorAll('#pop .menu-list button')].find(b => /Delete tag/.test(b.textContent)).click(); await sleep(1200);
  check(/Delete the tag #old\?/.test(asked) && /removed from 2 tasks \(2 open\)/.test(asked) && /tasks themselves stay/.test(asked), 'dialog names the count: ' + asked);
  check(![...w.eval('[...S.tasks.values()]')].some(t => t.tags.includes('old')) && w.eval(`S.tasks.get(${T1}).tags.join()`) === 'keep', 'tag gone from both tasks, other tags stay');
  check(!d.querySelector('#side .srow[data-drop="tag:old"]'), 'sidebar row gone');
  check(/removed from 2 tasks/.test(d.querySelector('#toast').textContent), 'toast with undo: ' + d.querySelector('#toast').textContent);
  await w.eval(`histStep('undo')`); await sleep(1200);
  check(w.eval(`S.tasks.get(${T1}).tags.slice().sort().join()`) === 'keep,old' && !!d.querySelector('#side .srow[data-drop="tag:old"]'), 'undo brings the tag back');
  w.eval(`go('tag/old')`); await sleep(300);
  check(w.eval('topMoreItems()').some(x => x.label === 'Delete tag…'), 'tag view "…" menu has Delete tag…');

  // ---- dialogs follow the visual viewport (Galaxy Fold)
  const vv = {height: 780, offsetTop: 0, ev: {}, addEventListener(k, f) { (this.ev[k] ||= []).push(f); }, fire(k) { (this.ev[k] || []).forEach(f => f()); }};
  w.close();
  w = await boot({user: 'alice', mobile: true, setup: x => { x.visualViewport = vv; x.innerHeight = 780; let sy = 0; Object.defineProperty(x, 'scrollY', {configurable: true, get: () => sy}); x.scrollTo = (a, b) => { sy = typeof a === 'object' ? a.top : b; x.__scrolled = (x.__scrolled || 0) + 1; }; x.__setSY = v => { sy = v; }; }}); d = w.document;
  check(d.documentElement.style.getPropertyValue('--vvh') === '780px' && d.documentElement.style.getPropertyValue('--vvt') === '0px', 'viewport variables set at start');
  w.eval(`askPrompt('Token name', '')`); await sleep(200);
  vv.height = 420; vv.offsetTop = 0; vv.fire('resize');  // keyboard up
  check(d.documentElement.style.getPropertyValue('--vvh') === '420px' && d.documentElement.style.getPropertyValue('--vvb') === '360px', 'keyboard up: dialog area shrinks to the visible part');
  vv.offsetTop = 180; vv.fire('scroll');
  check(d.documentElement.style.getPropertyValue('--vvt') === '180px', 'visual viewport scrolled: dialog follows');
  w.__setSY(180); vv.height = 780; vv.offsetTop = 0; vv.fire('resize');  // keyboard gone, page left scrolled
  check(d.documentElement.style.getPropertyValue('--vvh') === '780px' && d.documentElement.style.getPropertyValue('--vvt') === '0px' && w.__scrolled >= 1 && w.scrollY === 0, 'keyboard hidden: re-centred, leftover page scroll undone');
  const css = await (await fetch(B + 'static/app.css')).text();
  check(/\.modal\{position:fixed;inset:0;[^}]*padding:calc\(var\(--vvt,0px\) \+ 1rem\) 1rem calc\(var\(--vvb,0px\) \+ 1rem\)/.test(css), 'CSS: .modal padded by --vvt / --vvb');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  // touch: "…" > Refresh on a shared list
  w.eval(`go('l/${SH}')`); await sleep(300);
  check(w.eval('topMoreItems()').some(x => x.label === 'Refresh') && !d.querySelector('#top [data-act="refresh"]'), 'phone: Refresh in the "…" menu, no header button');
  w.close();

  // ---- News inbox
  await call('alice', 'POST', `/api/tasks/${T1}/comments`, {body: `<@${bob}> please check`});
  await call('alice', 'POST', '/api/tasks', {title: 'Assigned to Bob', list_id: SH, assignee_id: bob});
  const tb = (await call('bob', 'POST', '/api/tasks', {title: 'Bob made it', list_id: SH})).id;
  await call('alice', 'POST', `/api/tasks/${tb}/complete`, {});
  w = await boot({user: 'bob', hash: 'news'}); d = w.document;
  await sleep(600);
  let items = [...d.querySelectorAll('#view .nitem')];
  check(items.length >= 3 && items.every(i => i.querySelector('[data-act="news-dismiss"]')), 'every item has a remove button (desktop)');
  check(!items.some(i => i.classList.contains('k-complete')), 'default: completions by others do not show');
  check(d.querySelector('#view .nitem.unread') && /Unread/.test(d.querySelector('#view .nitem.unread').getAttribute('aria-label')), 'unread items marked (bold style + label)');
  const n0 = items.length, u0 = w.eval('S.news.unread');
  items[0].querySelector('[data-act="news-dismiss"]').click(); await sleep(800);
  check(d.querySelectorAll('#view .nitem').length === n0 - 1 && w.eval('S.route.mod') === 'news' && w.eval('S.news.unread') === u0 - 1, 'x removes the item without opening it');
  check((await call('bob', 'GET', '/api/news')).items.length === n0 - 1, 'removed on the server too');
  d.querySelector('[data-act="news-filter"][data-f="me"]').click(); await sleep(800);
  const ks = [...d.querySelectorAll('#view .nitem')].map(i => [...i.classList].find(c => c.startsWith('k-')));
  check(ks.length && ks.every(k => ['k-mention', 'k-assign', 'k-unassign'].includes(k)), 'filter Mentions & assigned to me: ' + ks);
  check(d.querySelector('[data-act="news-filter"][data-f="me"]').textContent.includes('Mentions & assigned to me'), 'filter label');
  d.querySelector('[data-act="news-filter"][data-f=""]').click(); await sleep(700);
  d.querySelector('[data-act="news-settings"]').click(); await sleep(600);
  // 2.1.0 (#317): the News column of the notification matrix replaced the News checkboxes
  const nk = [...d.querySelectorAll('#sp-notify [data-nm][data-ch="news"]')];
  check(nk.length >= 9 && !d.querySelector('#sp-notify [data-nm="complete"][data-ch="news"]').checked && d.querySelector('#sp-notify [data-nm="mention"][data-ch="news"]').checked && !d.querySelector('#sp-notify').classList.contains('hidden'), 'News column in Settings > Notifications (complete off by default)');
  const c = d.querySelector('#sp-notify [data-nm="complete"][data-ch="news"]'); c.checked = true; c.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(700);
  check((await call('bob', 'GET', '/api/state')).settings.news_kinds.split(',').includes('complete'), 'turning "completed" on is saved');
  w.close();
  // touch: swipe to remove
  w = await boot({user: 'bob', hash: 'news', mobile: true, setup: x => { x.ontouchstart = null; x.navigator.maxTouchPoints = 5; }}); d = w.document; await sleep(600);
  items = [...d.querySelectorAll('#view .nitem')];
  const n1 = items.length, first = items[0];
  const T = (type, x) => { const e = new w.Event(type, {bubbles: true}); e.touches = type === 'touchend' ? [] : [{clientX: x, clientY: 100}]; first.dispatchEvent(e); };
  T('touchstart', 300); T('touchmove', 250); T('touchmove', 120); T('touchend', 120); await sleep(900);
  check(d.querySelectorAll('#view .nitem').length === n1 - 1, 'swipe removes an item (' + n1 + ' -> ' + d.querySelectorAll('#view .nitem').length + ')');
  w.close();

  // ---- #246: no news = "No news", never an endless "Loading…" (also with collaboration off)
  await call('alice', 'POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123'});
  cks.erin = await login('erin');
  w = await boot({user: 'erin', hash: 'news'}); d = w.document; await sleep(800);
  check(/No news/.test(d.querySelector('#view').textContent) && !/Loading/.test(d.querySelector('#view').textContent), 'empty feed: "No news": ' + d.querySelector('#view .empty')?.textContent);
  d.querySelector('[data-act="news-filter"][data-f="me"]').click(); await sleep(800);
  check(/No news/.test(d.querySelector('#view').textContent) && !/Loading/.test(d.querySelector('#view').textContent), 'empty filter: "No news" too');
  d.querySelector('[data-act="news-filter"][data-f=""]').click(); await sleep(300);
  w.eval('S.nf.items = null; S.nf.loading = true; renderView()');
  check(/Loading/.test(d.querySelector('#view').textContent), '"Loading…" while a request runs');
  w.eval('S.nf.loading = false'); await w.eval('loadNews()'); await sleep(300);
  check(/No news/.test(d.querySelector('#view').textContent), 'after the request: "No news"');
  w.close();
  const st0 = await call('erin', 'GET', '/api/state');
  await call('erin', 'PATCH', '/api/settings', {features: st0.settings.features.split(',').filter(x => x !== 'collab').join(',')});
  w = await boot({user: 'erin'}); d = w.document; await sleep(300);
  w.eval(`S.route = {mod: 'news', key: ''}; renderView()`); await sleep(500);
  check(!/Loading/.test(d.querySelector('#view').textContent), 'collaboration off: no endless loading');
  w.close();

  // ---- German
  await call('alice', 'PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('share')`); await sleep(500);
  check(d.querySelector('#s-share-h')?.textContent === 'Teilen vom Handy' && /HTTP-Shortcuts-Import herunterladen/.test(d.querySelector('#s-hszip').textContent), 'German: Teilen vom Handy');
  d.querySelector(`[data-sec="account"]`).click(); await sleep(200);
  check(/Profilbild/.test(d.querySelector('#sp-account').textContent), 'German: Profilbild');
  w.close();

  const bad = errs.filter(e => !/Could not parse CSS/.test(e));
  check(!bad.length, 'no script errors: ' + bad.slice(0, 3).join(' | '));
  console.log(`\np190_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
