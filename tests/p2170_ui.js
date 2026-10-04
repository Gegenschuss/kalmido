// 2.17.0 UI tests (package B "Communication"), own container (start.sh, isolated test database).
// jsdom: #475 the dashboard behind the logo (cards: waiting for you, today, news, team chat, projects, pinned, notes,
// agents, numbers, search; Customize: ↑ ↓ and a switch per card, saved in the settings); #419 the team chat (the
// conversations with unread counts, a channel and a DM, sending with Enter, @Name -> mention, reactions, edit / delete,
// mute, the sidebar row, the list menu); #442 notes (the list menu / overview entry, new note, typing saves, Markdown with
// #123 links, read-only for viewers, the conflict dialog, delete + Undo, the command field finds notes); #452 News
// bundled (groups per task with a summary line, "Needs you" first, Mark read per group, plain list per device,
// Summarize -> the agent's chat); #443 Settings: the e-mail addresses (not set up here: the hint) and the summary
// switch. Firefox at 390 touch (real taps) and 1440 mouse, light + dark: the layouts, 44 px targets, nothing sideways;
// screenshots with P2170_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2170_ui', check, shots: 'P2170_SHOTS', prefs: [['widget.gtk.overlay-scrollbars.enabled', true], ['ui.useOverlayScrollbars', 1]]});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const type = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAR = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123', lang: 'de'})).id;
  const CB = await login('bob'), CC = await login('carol');
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done'}, CB);
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done', lang: 'de'}, CC);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Garden', kind: 'project'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: CAR, role: 'view'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const T = [];
  for (const [t, d, p] of [['Write the homepage text', 0, 3], ['Pick the photos', 1, 0], ['Call the printer', -1, 5]]) T.push((await call('POST', '/api/tasks', {title: t, list_id: L, due: day(d), priority: p})).id);
  await call('PATCH', `/api/tasks/${T[1]}`, {pinned: 1});
  // News for Alice: comments and a mention by Bob on one task, an assignment
  await call('POST', `/api/tasks/${T[0]}/comments`, {body: 'First draft is in'}, CB);
  await call('POST', `/api/tasks/${T[0]}/comments`, {body: 'And the second part'}, CB);
  await call('POST', `/api/tasks/${T[2]}/comments`, {body: `<@1> can you call them?`}, CB);
  const T4 = (await call('POST', '/api/tasks', {title: 'Review the logo', list_id: L, assignee_id: 1}, CB)).id;

  // ================= jsdom: #475 the dashboard
  let w = await boot({user: 'alice', hash: 'today', ls: {'tasks.newsBundle': null}}), d = w.document;
  const logo = d.querySelector('#side .sbrand .sbhome');
  check(logo && logo.dataset.go === 'home' && logo.getAttribute('aria-label') === 'Dashboard', '#475: the logo opens the dashboard');
  click(w, logo); await sleep(600);
  check(w.location.hash === '#home' && d.querySelector('#top h1')?.textContent.includes('Dashboard'), '#475: #home, titled Dashboard');
  await until(() => d.querySelector('.dcard.dc-news .ngroup'));
  const cards = [...d.querySelectorAll('.dgrid .dcard')].map(c => [...c.classList].find(x => x.startsWith('dc-')));
  check(['dc-wait', 'dc-today', 'dc-news', 'dc-chat', 'dc-projects', 'dc-pinned', 'dc-agents', 'dc-stats', 'dc-search'].every(c => cards.includes(c)), '#475: the cards ' + cards.join());
  check(!cards.includes('dc-notes'), 'no notes yet: the notes card stays away');
  check(d.querySelector('.dc-today').textContent.includes('Write the homepage text') && d.querySelector('.dc-today').textContent.includes('Call the printer'), 'today: due today and overdue');
  check(d.querySelector('.dc-pinned').textContent.includes('Pick the photos'), 'pinned tasks');
  check(/Website/.test(d.querySelector('.dc-projects').textContent) && d.querySelector('.dc-projects .dpb[role="img"]'), 'projects with their progress');
  check(d.querySelector('.dc-wait').textContent.includes('mentioned you') || d.querySelector('.dc-wait').textContent.includes('assigned'), 'waiting for you: the mention / assignment');
  check(d.querySelectorAll('.dcard h3').length === cards.length && [...d.querySelectorAll('.dcard')].every(c => c.getAttribute('aria-labelledby')), 'every card is a named section with a heading');
  // complete from the dashboard
  click(w, d.querySelector(`.dc-today [data-act="toggle"][data-id="${T[2]}"]`));
  check(await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.id === T[2])?.status === 2), 'a task completes right from the card');
  await call('POST', `/api/tasks/${T[2]}/reopen`);
  // customize
  click(w, d.querySelector('[data-act="dash-custom"]')); await sleep(200);
  const rows = [...d.querySelectorAll('.dcust li')];
  check(rows.length === 10 && rows[0].dataset.k === 'wait' && d.activeElement?.closest('.dcust'), 'Customize: every card with ↑ ↓ and a switch, the focus in the list');
  click(w, d.querySelector('.dcust [data-act="dash-mv"][data-k="today"][data-d="-1"]')); await sleep(300);
  const sw = d.querySelector('.dcust [data-dshow="stats"]'); sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(300);
  const ds = JSON.parse((await call('GET', '/api/state')).settings.dashboard || '{}');
  check(ds.order[0] === 'today' && ds.order[1] === 'wait' && ds.hidden.includes('stats'), '#475: order and hidden cards saved in the settings ' + JSON.stringify(ds));
  click(w, d.querySelector('[data-act="dash-done"]')); await sleep(300);
  check(d.querySelector('.dgrid .dcard').classList.contains('dc-today') && !d.querySelector('.dc-stats'), 'Today first now, Statistics hidden');
  w.close();
  w = await boot({user: 'alice', hash: 'home', mobile: true, ls: {'tasks.newsBundle': null}}); d = w.document; await sleep(400);
  check(d.querySelector('.dgrid .dcard.dc-today'), '#475: the same order on another device (phone)');
  // the tab bar's "More" menu with the new views in it (Dashboard / Team chat / Notes are no module of MODS)
  w.eval(`LS.set('tabbar', ['m:tasks', 'm:cal', 'm:habits', 'm:pomo', 'home', 'team', 'news', 'settings']); render()`); await sleep(300);
  let tmErr = null; try { w.eval(`tabsMore(document.querySelector('[data-act="tabs-more"]') || document.body)`); } catch (e) { tmErr = String(e); }
  await sleep(200);
  check(!tmErr && [...d.querySelectorAll('.menu-list button, .menu-list [role=menuitem]')].some(b => /Team chat|Dashboard/.test(b.textContent)), '"More" of the tab bar opens with Dashboard / Team chat in it ' + (tmErr || ''));
  w.close();
  await call('PATCH', '/api/settings', {dashboard: ''});

  // ================= jsdom: #452 News bundled
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsBundle': null}}); d = w.document;
  await until(() => d.querySelector('.nbund .ngroup'));
  const needs = d.querySelector('#ns-need')?.closest('.nsect'), info = d.querySelector('#ns-info')?.closest('.nsect');
  check(needs && needs.textContent.includes('Call the printer') && needs.textContent.includes('Review the logo'), '#452: "Needs you": the mention and the assignment');
  const g0 = [...d.querySelectorAll('.ngroup')].find(g => g.textContent.includes('Write the homepage text'));
  check(g0 && info.contains(g0) && /2 comments/.test(g0.querySelector('.ngs').textContent), '#452: two comments on one task = one group "2 comments" under "For your information" ' + (g0 && g0.querySelector('.ngs').textContent));
  const before = (await call('GET', '/api/news')).unread;
  click(w, g0.querySelector('[data-act="news-gread"]'));
  check(await until(async () => { const j = await call('GET', '/api/news'); return j.unread < before && j.items.filter(it => it.task_id === T[0]).every(it => it.read); }), '#452: Mark read per group');
  check(await until(() => /Marked read/.test(d.getElementById('srlive')?.textContent || '')), 'and that is announced');
  const tog = d.querySelector('[data-act="news-bundle"]');
  check(tog.getAttribute('aria-pressed') === 'true', 'bundled is on by default');
  click(w, tog); await sleep(200);
  check(!d.querySelector('.nbund') && d.querySelector('.nlist .nitem') && w.__store['tasks.newsBundle'] === 'false', '#452: the plain list, per device');
  click(w, d.querySelector('[data-act="news-bundle"]')); await sleep(200);
  // Summarize -> the agent's chat
  click(w, d.querySelector('[data-act="news-sum"]'));
  const msgs = await until(async () => { const j = await call('GET', `/api/agents/${ag.id}/chat`); return (j.messages || []).find(m => /summarize my \d+ unread news/.test(m.body)); });
  check(msgs && /Call the printer/.test(msgs.body), '#452: Summarize sends the unread news to the agent\'s chat');
  check(await until(() => w.eval('S.chat.aid') === ag.id), '… and opens it');
  w.eval('chatClose()'); w.close();

  // ================= jsdom: #419 the team chat
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`go('team')`); await until(() => d.querySelector('.tclist .tcrow'));
  const rws = [...d.querySelectorAll('.tclist .tcrow')];
  check(rws.length === 1 && rws[0].textContent.includes('Website') && !d.querySelector('.tclist').textContent.includes('Garden'), '#419: the shared project has a channel, the private one not');
  check(d.querySelector('[data-act="tc-new"]')?.getAttribute('aria-haspopup') === 'menu', 'a "Message…" button for direct messages');
  click(w, rws[0]); await until(() => d.querySelector('#tc-in'));
  check(d.querySelector('#tc-msgs[role="log"]') && d.querySelector('.tcrhead').textContent.includes('Website'), 'the channel opens with a log and its name');
  const box = d.querySelector('#tc-in');
  type(w, box, 'Hi @Bob, the text is ready');
  key(w, box, 'Enter'); await sleep(500);
  const sent = (await call('GET', `/api/team/rooms/${w.eval('S.tc.rid')}/messages`)).messages.pop();
  check(sent && sent.body === `Hi <@${BOB}>, the text is ready`, '#419: Enter sends, @Bob becomes a mention ' + JSON.stringify(sent?.body));
  check(box.value === '' && d.activeElement === box, 'the box is empty and keeps the focus');
  check(d.querySelector('#tc-msgs .cmsg.me .mention')?.textContent === '@Bob', 'the mention shows as @Bob');
  // Bob answers, Alice gets it live (the change marker)
  const RID = w.eval('S.tc.rid');
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Great, thanks!'}, CB);
  w.eval('teamChanged()');
  check(await until(() => [...d.querySelectorAll('#tc-msgs .cmsg.ag')].some(m => /Great, thanks/.test(m.textContent))), 'Bob\'s answer appears');
  check(d.querySelector('#tc-msgs .cmsg.ag .tcwho')?.textContent.includes('Bob'), 'with his name');
  // react, edit, delete
  const bm = [...d.querySelectorAll('#tc-msgs .cmsg.ag')].pop();
  click(w, bm.querySelector('.rxtog')); await sleep(50);
  click(w, bm.querySelector('.chrxq [data-e="heart"]'));
  check(await until(() => d.querySelector('#tc-msgs .cmsg.ag .chrx .rx.on[data-e="heart"]')), '#419: a reaction');
  const mine = d.querySelector('#tc-msgs .cmsg.me');
  click(w, mine.querySelector('[data-act="tc-msg-menu"]')); await sleep(80);
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Edit/.test(b.textContent))); await sleep(100);
  const ed = d.querySelector('#tc-msgs .tc-edit');
  check(ed && ed.value.includes('@Bob'), 'edit shows the text with @Bob');
  ed.value = 'Hi @Bob, the text is ready now'; key(w, ed, 'Enter');
  check(await until(async () => (await call('GET', `/api/team/rooms/${RID}/messages`)).messages.find(m => m.id === sent.id)?.edited_at), '#419: edited (Enter saves)');
  check(await until(() => /edited/.test(d.querySelector('#tc-msgs .cmsg.me .cmeta')?.textContent || '')), 'marked "edited"');
  // mute
  click(w, d.querySelector('[data-act="tc-mute"]')); await sleep(300);
  check(d.querySelector('[data-act="tc-mute"]').getAttribute('aria-pressed') === 'true', '#419: mute (pressed)');
  // DM via the menu
  click(w, d.querySelector('[data-act="tc-new"]')); await sleep(80);
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Bob/.test(b.textContent)));
  check(await until(() => w.eval('S.tc.room?.kind') === 'dm'), '#419: "Message…" > Bob opens the direct conversation');
  await call('POST', `/api/team/rooms/${w.eval('S.tc.rid')}/messages`, {body: 'Coffee later?'});
  w.close();
  // Bob: unread in the sidebar, the list menu
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#side [data-go="team"]'));
  const tr0 = d.querySelector('#side [data-go="team"]');
  check(tr0 && /\d/.test(tr0.querySelector('.c')?.textContent || ''), '#419: the sidebar row with the unread count');
  w.eval(`go('l/${L}')`); await sleep(300);
  w.eval(`menu(document.querySelector('#top h1'), listMenuItems(${L}, document.querySelector('#top h1')))`); await sleep(80);
  const lm = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(lm.some(x => x.startsWith('Notes')) && lm.includes('Team chat'), '#442 #419: the list menu has Notes and Team chat ' + lm.join('|'));
  w.eval('closePop()'); w.close();

  // ================= jsdom: #442 notes
  w = await boot({user: 'alice', hash: 'notes/' + L}); d = w.document;
  await until(() => d.querySelector('.ntview'));
  check(d.querySelector('.ntview .hempty') && d.querySelector('[data-act="nt-new"]'), '#442: no notes yet: the heron and "New note"');
  click(w, d.querySelector('[data-act="nt-new"]'));
  await until(() => d.querySelector('#nt-title'));
  await sleep(200);
  check(d.activeElement?.id === 'nt-title' && w.location.hash.startsWith('#note/'), 'a new note: the title has the focus, its own address');
  const NID = +w.location.hash.split('/')[1];
  type(w, d.querySelector('#nt-title'), 'Kick-off');
  type(w, d.querySelector('#nt-tags'), 'client, plan');
  type(w, d.querySelector('#nt-body'), `## Decisions\n- go live in May\n- see #${T[0]}`);
  d.querySelector('#nt-body').dispatchEvent(new w.FocusEvent('focusout', {bubbles: true}));
  check(await until(async () => { const n = await call('GET', `/api/notes/${NID}`); return n.title === 'Kick-off' && n.tags.join() === 'client,plan' && n.body.includes('go live'); }), '#442: typing saves by itself (title, tags, text)');
  click(w, d.querySelector('[data-act="nt-mode"][data-m="read"]')); await sleep(200);
  const md = d.querySelector('#nt-md');
  check(md.querySelector('h4, h3, h5')?.textContent === 'Decisions' && md.querySelector(`a.tref[href="#t/${T[0]}"]`)?.textContent.includes('Write the homepage text'), '#442: Markdown with #123 as a task link');
  check(d.querySelector('.ntcard.on')?.textContent.includes('Kick-off'), 'the list of notes shows it');
  // the overview, the palette
  w.eval(`go('l/${L}')`); await sleep(200);
  w.eval(`S.pov.add(${L}); render()`); await sleep(600);
  check(d.querySelector('.povnotes a[href="#note/' + NID + '"]'), '#442: the project overview lists the note');
  w.eval('openPalette()'); type(w, d.querySelector('.palette .pqin'), 'kick'); await sleep(80);
  check([...d.querySelectorAll('.palette .pitem')].some(b => /Kick-off/.test(b.textContent) && /note/.test(b.textContent)), '#442: the command field finds notes');
  w.eval('closePalette()');
  // delete + Undo
  w.eval(`go('note/${NID}')`); await sleep(300);
  click(w, d.querySelector('[data-act="nt-menu"]')); await sleep(80);
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Delete/.test(b.textContent)));
  check(await until(async () => (await call('GET', `/api/notes/${NID}`)).status === 404), '#442: delete');
  click(w, d.querySelector('#toast button'));
  check(await until(async () => (await call('GET', `/api/lists/${L}/notes`)).notes?.some(n => n.title === 'Kick-off' && n.body.includes('go live'))), '#442: Undo brings it back');
  w.close();
  // a viewer reads only; the conflict
  const NN = (await call('GET', `/api/lists/${L}/notes`)).notes[0].id;
  w = await boot({user: 'carol', hash: 'note/' + NN}); d = w.document;
  await until(() => d.querySelector('#nt-title'));
  check(d.querySelector('#nt-title').readOnly && !d.querySelector('[data-act="nt-new"]') && !d.querySelector('[data-act="nt-mode"]'), '#442: a viewer reads, cannot write (German UI too)');
  w.close();
  w = await boot({user: 'alice', hash: 'note/' + NN}); d = w.document;
  await until(() => d.querySelector('#nt-title'));
  click(w, d.querySelector('[data-act="nt-mode"][data-m="edit"]')); await sleep(200);
  await sleep(1100);
  await call('PATCH', `/api/notes/${NN}`, {body: 'Bob rewrote it'}, CB);
  w.__dialogs = 'manual';
  type(w, d.querySelector('#nt-body'), 'Alice adds a line');
  await w.eval('noteFlush()');
  const cd = await until(() => [...d.querySelectorAll('.modal.cdlg')].pop());
  check(cd && /Changed in the meantime by Bob/.test(cd.textContent) && cd.textContent.includes('Bob rewrote it') && cd.textContent.includes('Alice adds a line'), '#442: a change in between: both versions');
  click(w, cd.querySelector('[data-cd="yes"]'));
  check(await until(async () => (await call('GET', `/api/notes/${NN}`)).body === 'Alice adds a line'), '"Keep mine" saves mine');
  w.close();

  // ================= jsdom: #443 Settings
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('integr')`); await sleep(600);
  check(d.querySelector('#s-mail-h') && /Not set up on this server/.test(d.querySelector('#s-mail')?.textContent || ''), '#443: Tasks by e-mail: not set up here, says how');
  w.eval(`[...document.querySelectorAll('.modal')].forEach(m => m.remove()); settingsModal('notify')`); await sleep(600);
  check(/not set up on this server/.test(d.querySelector('#s-digmail-w')?.textContent || ''), '#443: the summary by e-mail: not set up here');
  w.close();

  // ================= German
  w = await boot({user: 'carol', hash: 'home'}); d = w.document; await sleep(400);
  check(d.querySelector('#top h1')?.textContent.includes('Übersicht') || d.querySelector('#top h1')?.textContent.includes('Dashboard'), 'German: the dashboard title');
  check(d.querySelector('[data-act="dash-custom"]')?.textContent.includes('Anpassen'), 'German: Anpassen');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const SMALL = `(() => { const out = []; for (const e of document.querySelectorAll('#view button, #view a[href], #view [role=button], #view input:not([type=hidden]), #view select')) {
      const r = e.getBoundingClientRect(); if (!r.width || r.bottom < 0 || r.top > innerHeight || e.closest('.md, .cbub, p')) continue;
      if (e.tagName === 'INPUT' && /text|search/.test(e.type)) continue; const row = e.closest('.trow'); if (row && e.matches('.ttl')) continue;
      let w = r.width, h = r.height; for (const p of ['::before', '::after']) { const ps = getComputedStyle(e, p); if (ps.content !== 'none' && ps.position === 'absolute') { w = Math.max(w, parseFloat(ps.width) || 0); h = Math.max(h, parseFloat(ps.height) || 0); } }
      if (w < 43.5 || h < 43.5) out.push((e.dataset.act || e.className || e.tagName) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)); } return out.slice(0, 8); })()`;
  const OVER = `(() => ({o: document.documentElement.scrollWidth - innerWidth, v: document.querySelector('#view').scrollWidth - document.querySelector('#view').clientWidth}))()`;
  const tapper = ({cmd, ctx}) => async (x, y) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  const center = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; e.scrollIntoView({block: 'center'}); const q = e.getBoundingClientRect(); return {x: q.left + q.width / 2, y: q.top + q.height / 2, w: q.width, h: q.height}; })()`;
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tap = tapper(o), tag = '390 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    for (const [name, hash] of [['dashboard', 'home'], ['team', 'team'], ['news', 'news'], ['notes', 'notes/' + L]]) {
      await o.nav(B + '#' + hash); await ready(ev); await sleep(500);
      const x = await ev(OVER);
      check(x.o <= 0 && x.v <= 0, `${tag} ${name}: nothing sideways ` + JSON.stringify(x));
      const sm = await ev(SMALL);
      check(!sm.length, `${tag} ${name}: 44 px targets ` + JSON.stringify(sm));
      await shot(`p2170-${th}-390-${name}.png`);
    }
    // the team chat on a phone: tap a conversation, type, send with a tap
    await o.nav(B + '#team'); await ready(ev);
    let p = await ev(center('.tclist .tcrow')); await tap(p.x, p.y); await sleep(1200);
    const lay = await ev(`(() => { const l = document.querySelector('.tclist'), r = document.querySelector('.tcroom'), c = document.querySelector('.tccomp').getBoundingClientRect(); return {list: l && getComputedStyle(l).display, room: !!r, comp: Math.round(c.bottom), ih: innerHeight, tabs: Math.round(document.querySelector('#tabs')?.getBoundingClientRect().top || innerHeight)}; })()`);
    check(lay.list === 'none' && lay.room && lay.comp <= lay.tabs + 1, `${tag}: a tap opens the conversation full screen, the box above the tab bar ` + JSON.stringify(lay));
    p = await ev(center('#tc-in')); await tap(p.x, p.y); await sleep(300);
    await ev(`(() => { const t = document.querySelector('#tc-in'); t.value = 'From the phone (${th})'; t.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    p = await ev(center('[data-act="tc-send"]')); await tap(p.x, p.y); await sleep(800);
    check(await ev(`[...document.querySelectorAll('#tc-msgs .cmsg.me')].some(m => m.textContent.includes('From the phone (${th})'))`), `${tag}: sent with a tap on Send`);
    await shot(`p2170-${th}-390-team-room.png`);
    p = await ev(center('[data-act="tc-back"]')); await tap(p.x, p.y); await sleep(500);
    check(await ev(`getComputedStyle(document.querySelector('.tclist')).display !== 'none'`), `${tag}: Back shows the conversations again`);
    // review of 2.16.1: the reaction bar of an OWN message opens inside the screen; the header keeps the search icon;
    // an unfolded Fold (904) has a close X on the task panel
    p = await ev(center('.tclist .tcrow')); await tap(p.x, p.y); await sleep(800);
    p = await ev(center('#tc-msgs .cmsg.me .rxtog')); if (p) { await tap(p.x, p.y); await sleep(400); }
    const rq = await ev(`(() => { const q = document.querySelector('#tc-msgs .cmsg.me.rxshow .chrxq'); if (!q) return null; const r = q.getBoundingClientRect(); return {t: Math.round(r.top), b: Math.round(r.bottom), l: Math.round(r.left), r: Math.round(r.right), o: getComputedStyle(q).opacity}; })()`);
    check(rq && rq.t >= 0 && rq.l >= 0 && rq.r <= 390 && rq.o === '1', `${tag}: own message: the reaction bar opens on screen ` + JSON.stringify(rq));
    await o.nav(B + '#today'); await ready(ev);
    const sb = await ev(`(() => { const b = document.querySelector('#top [data-act="palette"]'); const r = b?.getBoundingClientRect(); return r && r.width >= 30 && r.right <= innerWidth ? Math.round(r.width) : 0; })()`);
    check(sb > 0, `${tag}: the header has the search icon on the phone (${sb})`);
    if (th === 'light') {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 1080}});
      await o.nav(B + '#t/' + T[0]); await ready(ev); await sleep(600);
      const cx = await ev(`(() => { const b = [...document.querySelectorAll('#detail .dtop [data-act="close-detail"]')].filter(e => e.getBoundingClientRect().width > 0); return b.length; })()`);
      check(cx >= 1, `${tag}: Fold 904: the task panel has a close button (${cx})`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    }
  }, true);
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    for (const [name, hash] of [['dashboard', 'home'], ['team', 'team'], ['news', 'news'], ['notes', 'notes/' + L]]) {
      await o.nav(B + '#' + hash); await ready(ev); await sleep(500);
      if (name === 'team') { await ev(`(() => { document.querySelector('.tclist .tcrow')?.click(); return 1; })()`); await sleep(1000); }
      if (name === 'notes') { await ev(`(() => { document.querySelector('.ntcard')?.click(); return 1; })()`); await sleep(800); }
      const x = await ev(OVER);
      check(x.o <= 0, `${tag} ${name}: nothing sideways ` + JSON.stringify(x));
      await shot(`p2170-${th}-1440-${name}.png`);
    }
    const dg = await ev(`(() => { const cs = [...document.querySelectorAll('.dgrid .dcard')]; return {n: cs.length}; })()`);
    await o.nav(B + '#home'); await ready(ev);
    const cols = await ev(`(() => { const cs = [...document.querySelectorAll('.dgrid .dcard')].map(c => Math.round(c.getBoundingClientRect().left)); return new Set(cs).size; })()`);
    check(cols >= 3, `${tag}: the dashboard uses the width (${cols} columns)`);
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
