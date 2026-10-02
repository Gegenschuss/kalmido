// 2.0.6 UI tests (jsdom), fresh DB:
// #188 tablets in portrait (phone layout, >= 600 x 600): the docked composer instead of the "+", "n" focuses it; phones keep "+"
// #189 "No date" in the roadmap (rows to draw into, switch, folding group) and in the calendar timeline (switch in the bar)
// #190 a running focus session / stopwatch as a card on the time page (pause, resume, stop)
// #191 keyboard: calendar views (1-4, ← →, .), multi-select (Ctrl/Cmd+A, Shift+↓ / Shift+J, Shift+X, x, m, Esc), the help
// #314 the desktop rail follows the tab bar setting (order, search / settings where placed, modules appended, nothing hidden)
// #315 comments as personal notes: private lists, "+ Comment", no mentions / activity outside shared lists, the Comments module,
//      no comments in checklists
// #316 / #322 detail order: description, subtasks, comments, dependencies, tags, attachments, Paperless, fields
// #318 a menu opened inside a dialog (Settings > AI colleague; 2.4.2: the share button is gone, a menu anchored there) shows above it
const fs = require('fs'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, k, o = {}) => w.document.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const ds = n => { const t = new Date(), d = new Date(t.getFullYear(), t.getMonth(), t.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments';
const TABLET = {'(min-width:600px) and (min-height:600px)': true};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const WEB = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const launch = await mk('Plan launch', WEB, {due: ds(3)}), idea = await mk('Undated idea', WEB), idea2 = await mk('Another idea', WEB);
  const copy = await mk('Write copy', WEB, {due: ds(4)}); await mk('Outline', WEB, {parent_id: copy, due: ds(4)});
  await call('POST', '/api/deps', {task_id: copy, blocker_id: launch});
  const PRIV = (await call('POST', '/api/lists', {name: 'Private'})).id;
  const bank = await mk('Call the bank', PRIV), taxes = await mk('Taxes', PRIV);
  const sub1 = await mk('Find the form', PRIV, {parent_id: taxes});
  await call('POST', '/api/deps', {task_id: taxes, blocker_id: bank});
  const CKL = (await call('POST', '/api/lists', {name: 'Groceries', kind: 'checklist'})).id;
  const milk = await mk('Milk', CKL);
  const TEAM = (await call('POST', '/api/lists', {name: 'Team'})).id;
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: BOB, role: 'edit'});
  const plan = await mk('Team plan', TEAM);
  const css0 = await (await fetch(B + 'static/app.css')).text();
  const SW = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
  check(/const CACHE = 'tasks-shell-v((5[89]|6[0-9])|7[0-9])'/.test(SW), 'service worker cache v58 (2.0.8: v59, 2.1.0: v60, 2.1.1: v61, 2.1.2: v62, 2.2.0: v63, 2.2.1: v64, 2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73, 2.7.0: v74, 2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79)');

  // ================= #315 comments in a private list: the box (one line) at the bottom edge -> a note; no @ hint, no activity
  let w = await boot({user: 'alice', hash: 'l/' + PRIV}), d = w.document;
  w.eval(`openDetail(${bank})`); await sleep(700);
  let ci = d.querySelector('#detail .dbot .dcomp #c-input');
  check(ci && !d.querySelector('#detail #d-tl') && ci.placeholder === 'Write a comment…' && !ci.closest('.ccomp').classList.contains('used'), 'private task without comments: no list, only the box (compact), without the @ hint');
  check(!d.querySelector('#detail [data-act="tl-act"]') && !d.querySelector('#detail .cmfold') && !d.querySelector('#detail .cmempty'), 'private: no activity switch, no fold toggle, no "No comments yet"');
  ci.focus(); ci.value = 'Asked for the IBAN form'; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(ci.closest('.ccomp').classList.contains('used'), 'typing opens the bar (files, Send)');
  click(w, d.querySelector('[data-act="c-send"]')); await sleep(1200);
  const tl1 = (await call('GET', `/api/tasks/${bank}/timeline`)).comments;
  check(tl1.length === 1 && tl1[0].body === 'Asked for the IBAN form', 'the note is saved');
  check(d.querySelector('#detail #d-tl .cm [data-act="c-edit"]') && !d.querySelector('#detail #d-tl .cm .rx'), 'the list appears with it: edit, no reactions (private)');
  check(d.activeElement?.id === 'c-input' && d.querySelector('#c-input').value === '', 'the box keeps the focus, empty');
  ci = d.querySelector('#c-input'); ci.value = '@'; ci.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(100);
  check(d.querySelector('#detail .mpick')?.classList.contains('hidden') !== false, 'no mention picker in a private list');
  ci.value = ''; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
  w.close();
  // #316 / #322: order in the panel (a project task with a subtask, a dependency and a comment)
  await call('POST', `/api/tasks/${copy}/comments`, {body: 'Draft is in the drive'});
  w = await boot({user: 'alice', hash: 'l/' + WEB}); d = w.document;
  w.eval(`openDetail(${copy})`); await sleep(1000);
  const body = [...d.querySelector('#detail .dbody').children].map(x => x.id || ['subsec', 'attsec', 'plsec', 'fields', 'cfsec', 'tesec'].find(c => x.classList.contains(c)) || (/^Tags/.test(x.querySelector('h5')?.textContent || '') ? 'tags' : x.className));
  const order = ['d-content', 'subsec', 'd-deps', 'tags', 'attsec', 'fields', 'd-tl'].map(k => body.indexOf(k));
  check(order.every((v, i) => v >= 0 && (!i || v > order[i - 1])) && body[body.length - 1] === 'd-tl', 'detail order: description, subtasks, dependencies, tags, attachments, fields, comments last: ' + body.join('|'));
  check(body.indexOf('d-hist') === body.length - 2, '2.0.7: the folded history of a private list sits right above the comments: ' + body.join('|'));
  check(d.querySelector('#detail > .dbot > .dcomp #c-input') && d.querySelector('#detail > .dbot > .dfoot') && !d.querySelector('#detail .dbody #c-input'), 'the comment box sits with the footer at the bottom edge (outside the scrolling content)');
  check(/Outline/.test(d.querySelector('#detail .subsec')?.textContent || ''), 'subtasks right below the description');
  check(w.eval('JSON.stringify(DETAIL_ORDER)') === JSON.stringify(['subtasks', 'deps', 'tags', 'attachments', 'paperless', 'fields', 'custom', 'time', 'code', 'history', 'comments']), 'the order lives in one list (DETAIL_ORDER; 2.2.0: code)');
  check(/\.dbot\{position:sticky;bottom:0/.test(css0), 'CSS: the box + footer are sticky at the bottom edge');
  w.close();

  // ================= #315 shared list: full section with activity switch + mention hint; checklist: none
  w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  w.eval(`openDetail(${plan})`); await sleep(800);
  check(d.querySelector('#detail #d-tl') && d.querySelector('#detail .dcomp #c-input')?.placeholder === 'Write a comment… (@ mentions someone)' && d.querySelector('#detail [data-act="tl-act"]'), 'shared list: the list with the history (activity switch), @ hint');
  w.eval(`go('l/${CKL}'); openDetail(${milk})`); await sleep(600);
  check(d.querySelector('#detail #d-title'), 'an item of a list with completed at the bottom opens as a full task (2.7.2; was: no comments)');
  w.close();

  // ================= #315 the Comments module switch; off: nothing anywhere
  w = await boot({user: 'alice', hash: 'settings'}); d = w.document;
  w.eval(`settingsModal('modules')`); await sleep(400);
  let md = d.querySelector('.modal.smodal');
  const csw = md.querySelector('[data-pane="modules"] [data-feat="comments"]');
  check(csw && csw.checked && /Timestamped notes/.test(csw.closest('[data-modrow]').textContent), 'Settings > Modules: "Comments" switch with its sentence, on');
  csw.checked = false; csw.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900);
  check(!(await call('GET', '/api/state')).settings.features.split(',').includes('comments'), 'switched off: saved');
  md.remove();
  w.eval(`go('l/${PRIV}')`); await sleep(400);
  check(!d.querySelector(`#view .trow[data-id="${bank}"] .cmc`), 'off: no comment count on the row');
  w.eval(`openDetail(${bank})`); await sleep(600);
  check(!d.querySelector('#detail #d-tl') && !d.querySelector('#detail #c-input'), 'off: no comment section');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});

  // ================= #315 collaboration off (own switch): comments stay, notes only
  await call('PATCH', '/api/settings', {features: ALL.split(',').filter(f => f !== 'collab').join(',')});
  w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  w.eval(`openDetail(${plan})`); await sleep(700);
  check(!d.querySelector('#detail #d-tl') && d.querySelector('#detail #c-input') && !d.querySelector('#detail [data-act="tl-act"]'), 'collaboration off: the box, no history');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});

  // ================= #314 -> 2.8.0 (#434): no rail; the desktop sidebar shows every switched-on module whatever the tab bar
  // setting says (that one is for phones)
  w = await boot({user: 'alice', hash: 'today', ls: {'tasks.tabbar': JSON.stringify(['m:cal', 'search', 'm:tasks', 'stats'])}}); d = w.document;
  check(!d.querySelector('#rail'), 'no rail');
  const css = await (await fetch(B + 'static/app.css')).text();
  check(['cal', 'matrix', 'habits', 'pomo', 'time', 'stats'].every(k => d.querySelector(`#side [data-go="${k}"]`)) && d.querySelectorAll('#side [data-go="search"]').length === 1 && d.querySelector('#side .sset'), 'sidebar: every module, search once, settings');
  // settings: the add select offers agents / stats / time / overview / search / settings
  w.eval(`settingsModal('tabbar')`); await sleep(300);
  md = d.querySelector('.modal.smodal');
  check(/every module in the sidebar/.test(md.querySelector('[data-pane="look"]').textContent), 'tab bar hint: bottom on phones, the desktop sidebar has every module');
  md.remove();
  w.close();

  // ================= #191 keyboard: calendar views
  w = await boot({user: 'alice', hash: 'cal'}); d = w.document;
  key(w, '2'); await sleep(200);
  check(w.eval('S.calMode') === 'week', '2: week');
  key(w, '3'); await sleep(200);
  check(w.eval('S.calMode') === 'day', '3: day');
  const day0 = w.eval('S.calSel || today()');
  key(w, 'ArrowRight'); await sleep(200);
  check(w.eval('S.calSel') !== day0 && w.eval('S.calSel') > day0, '→: next day: ' + w.eval('S.calSel'));
  key(w, 'ArrowLeft'); key(w, 'ArrowLeft'); await sleep(200);
  check(w.eval('S.calSel') < day0, '←: previous');
  key(w, '.'); await sleep(200);
  check(w.eval('S.calSel') === w.eval('today()'), '.: today');
  key(w, '4'); await sleep(250);
  check(w.eval('S.calMode') === 'timeline', '4: timeline');
  key(w, '1'); await sleep(200);
  check(w.eval('S.calMode') === 'month', '1: month');
  // #189: "No date" in the calendar timeline
  key(w, '4'); await sleep(250);
  const cnd = d.querySelector('#view .calbar [data-act="tl-nd"]');
  check(cnd && cnd.getAttribute('aria-pressed') === 'false' && /No date/.test(cnd.textContent) && /\b[3-9]\b/.test(cnd.querySelector('.c')?.textContent || ''), 'calendar timeline: "No date" switch with the count');
  click(w, cnd); await sleep(250);
  check(d.querySelector('#view .tl-ndhead') && [...d.querySelectorAll('#view .tl-nd .tln')].some(x => /Undated idea/.test(x.textContent)), 'switched on: undated tasks as rows per list');
  click(w, d.querySelector('#view .calbar [data-act="tl-nd"]')); await sleep(200);
  check(!d.querySelector('#view .tl-ndhead'), 'switched off again');
  key(w, '1');
  // help overlay
  key(w, '?'); await sleep(120);
  const kh = [...d.querySelectorAll('.kbmodal section h4')].map(h => h.textContent);
  check(kh.includes('Calendar') && kh.includes('Multi-select'), 'help overlay: Calendar + Multi-select groups: ' + kh);
  const khTxt = d.querySelector('.kbmodal').textContent;
  check(['Select all tasks of the view', 'Extend the selection down', 'Previous period', 'Jump to today'].every(x => khTxt.includes(x)), 'help overlay: the new keys named');
  const all = w.eval('JSON.stringify(SHORTCUTS().flatMap(([g, r]) => r.map(([k]) => g + ":" + k)))');
  const dup = JSON.parse(all).filter((x, i, a) => a.indexOf(x) !== i);
  check(!dup.length, 'no key twice in one group: ' + dup);
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.close();

  // ================= #191 keyboard: multi-select
  w = await boot({user: 'alice', hash: 'l/' + WEB}); d = w.document;
  const ids = () => [...d.querySelectorAll('#view .trow')].map(r => +r.dataset.id);
  key(w, 'j'); await sleep(50);
  key(w, 'J', {shiftKey: true}); await sleep(80);
  check(w.eval('S.multi.size') === 2 && d.querySelectorAll('#view .trow.msel').length === 2 && !d.querySelector('#mbar').classList.contains('hidden'), 'Shift+J: the focused and the next task selected, bar shown');
  key(w, 'ArrowDown', {shiftKey: true}); await sleep(80);
  check(w.eval('S.multi.size') === 3, 'Shift+↓: extended to three');
  key(w, 'X', {shiftKey: true}); await sleep(80);
  check(w.eval('S.multi.size') === 2, 'Shift+X: the focused task unselected');
  key(w, 'Escape'); await sleep(100);
  check(w.eval('S.multi.size') === 0, 'Esc: selection cleared');
  key(w, 'a', {ctrlKey: true}); await sleep(200);
  check(w.eval('S.multi.size') === ids().length && ids().length >= 3, 'Ctrl+A: every task of the view');
  key(w, 'm'); await sleep(200);
  check(!d.querySelector('#pop').classList.contains('hidden') && [...d.querySelectorAll('#pop .menu-list button')].some(b => /Private/.test(b.textContent)), 'm: the list menu for the selection');
  w.eval('closePop()');
  w.eval('S.multi.clear(); renderMultiBar(); render()');
  const [s1, s2] = [idea, idea2];
  w.eval(`S.multi.add(${s1}); S.multi.add(${s2}); renderMultiBar()`);
  key(w, 'x'); await sleep(900);
  const st1 = await call('GET', '/api/state'), gone = id => { const t = st1.tasks.find(x => x.id === id); return !t || t.status === 2; };
  check(gone(s1) && gone(s2), 'x: the selected tasks completed');
  await call('POST', `/api/tasks/${s1}/reopen`); await call('POST', `/api/tasks/${s2}/reopen`);
  check(w.eval('S.multi.size') === 0, 'selection cleared after completing');
  w.close();

  // ================= #189 roadmap: "No date" rows, draw a date, the switch, folding
  await call('PATCH', '/api/settings', {roadmap: '{"v":"timeline","po":false,"def":"e"}'});
  w = await boot({user: 'alice', hash: 'all'}); d = w.document; await sleep(300);
  const nh = d.querySelector(`.rm-nh[data-l="${WEB}"]`);
  check(nh && /No date/.test(nh.textContent) && /2/.test(nh.querySelector('.c')?.textContent || ''), 'roadmap: "No date (2)" at the end of the open project');
  const urow = [...d.querySelectorAll(`.rm-u[data-l="${WEB}"]`)];
  check(urow.length === 2 && urow.some(r => /Undated idea/.test(r.textContent)) && urow[0].querySelector('.tl-track.ndt.ed[data-s0][data-dw]'), 'one row per undated task with an empty track to draw into');
  check(d.querySelectorAll(`.rm-t[data-l="${WEB}"]`).length === 3, 'the dated tasks keep their bar rows');
  const tr_ = [...d.querySelectorAll('.rm-u')].find(r => /Undated idea/.test(r.textContent)).querySelector('.tl-track');
  const dw = +tr_.dataset.dw, s0 = tr_.dataset.s0, tgt = ds(5), off = Math.round((new Date(tgt) - new Date(s0)) / 864e5);
  tr_.dispatchEvent(new w.MouseEvent('pointerdown', {bubbles: true, button: 0, clientX: off * dw + dw / 2}));
  d.dispatchEvent(new w.MouseEvent('pointerup', {bubbles: true, button: 0, clientX: off * dw + dw / 2}));
  await sleep(900);
  check((await call('GET', '/api/state')).tasks.find(t => t.id === idea)?.due === tgt, 'click on a day: the task gets that due date: ' + tgt);
  await call('PATCH', `/api/tasks/${idea}`, {due: null}); await w.eval('load()'); w.eval('render()'); await sleep(300);
  click(w, d.querySelector(`.rm-nh[data-l="${WEB}"] [data-act="rm-ndfold"]`)); await sleep(200);
  check(d.querySelector(`.rm-nh[data-l="${WEB}"]`) && !d.querySelector(`.rm-u[data-l="${WEB}"]`), 'the group folds');
  click(w, d.querySelector(`.rm-nh[data-l="${WEB}"] [data-act="rm-ndfold"]`)); await sleep(200);
  const ndc = d.querySelector('.rm-chips [data-act="rm-nd"]');
  check(ndc && ndc.getAttribute('aria-pressed') === 'true', 'chip "No date": on by default');
  click(w, ndc); await sleep(800);
  check(!d.querySelector('.rm-nh') && !d.querySelector('.rm-u'), 'switched off: no undated rows');
  check(JSON.parse((await call('GET', '/api/state')).settings.roadmap).nd === false, 'stored for the user');
  w.close();
  await call('PATCH', '/api/settings', {roadmap: ''});

  // ================= #190 focus session / stopwatch as a card on the time page
  await call('POST', '/api/pomo/start', {kind: 'focus', minutes: 25, task_id: launch});
  w = await boot({user: 'alice', hash: 'time'}); d = w.document; await sleep(300);
  let card = d.querySelector('#view .tvrun.tvpomo');
  check(card && card.classList.contains('k-focus') && /Focus session/.test(card.textContent) && /Plan launch/.test(card.querySelector('.tvr-task').textContent) && /25 min planned/.test(card.textContent), 'focus session: card with kind, task, planned minutes');
  check(/\d\d:\d\d/.test(card.querySelector('[data-pomo-mini]').textContent) && card.querySelector('[data-act="pomo-pause"]') && card.querySelector('[data-act="pomo-stop"]'), 'live time, Pause, Stop');
  check(!d.querySelector('#view .tvrun.idle'), 'no "No timer running" hint while it runs');
  click(w, card.querySelector('[data-act="pomo-pause"]')); await sleep(700);
  card = d.querySelector('#view .tvrun.tvpomo');
  check(card?.classList.contains('paused') && card.querySelector('[data-act="pomo-resume"]'), 'paused: marked, Resume');
  click(w, card.querySelector('[data-act="pomo-stop"]')); await sleep(700);
  check(!d.querySelector('#view .tvrun.tvpomo') && d.querySelector('#view .tvrun.idle'), 'stopped: the card goes');
  await call('POST', '/api/pomo/start', {kind: 'stopwatch', minutes: 0});
  await call('POST', '/api/time/start', {task_id: launch});
  await w.eval('load()'); w.eval('render()'); await sleep(300);
  const cards = [...d.querySelectorAll('#view .tvrun')];
  check(cards.length === 2 && !cards[0].classList.contains('tvpomo') && cards[1].classList.contains('k-stopwatch') && /Stop stopwatch/.test(cards[1].textContent), 'timer + stopwatch: both cards, the time-tracking one first');
  await call('POST', '/api/time/stop', {});
  w.close();
  const pm = (await call('GET', '/api/state')).pomo; if (pm) await call('POST', `/api/pomo/${pm.id}/stop`);

  // ================= #188 tablet portrait: docked composer, no "+"; phone keeps "+"
  w = await boot({user: 'alice', hash: 'l/' + PRIV, mobile: true, media: TABLET}); d = w.document;
  check(w.eval('isMobile() && tabletDock()'), 'tablet portrait: phone layout, tabletDock()');
  check(d.querySelector('#view .qdock #qinput') && d.querySelector('#fab').classList.contains('gone'), 'list view: the docked composer, the "+" hidden');
  key(w, 'n'); await sleep(80);
  check(d.activeElement?.id === 'qinput' && !d.querySelector('.qadd.sheet'), '"n" focuses the composer (no sheet)');
  d.activeElement.blur();
  w.eval(`go('habits')`); await sleep(300);
  check(d.querySelector('#fab').classList.contains('gone'), 'habits: no "+" either');
  w.eval(`go('cal')`); await sleep(300);
  check(!d.querySelector('#view .qdock') && !d.querySelector('#fab').classList.contains('gone'), 'calendar (no composer): the "+" stays');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + PRIV, mobile: true}); d = w.document;
  check(!w.eval('tabletDock()') && !d.querySelector('#fab').classList.contains('gone'), 'phone: the "+" as before');
  w.close();
  check(/@media \(min-width:600px\) and \(max-width:899px\) and \(min-height:600px\)\{\s*\.qdock\{display:block;bottom:calc\(var\(--tabs-h\) \+ var\(--safe-b\)\)/.test(css), 'CSS: the dock shows on portrait tablets, above the tab bar');

  // ================= #318 a menu from inside a dialog goes above it (phone sheet and desktop)
  for (const mobile of [false, true]) {
    w = await boot({user: 'alice', mobile}); d = w.document;
    w.eval(`settingsModal('account')`); await sleep(500);
    // 2.4.2 (#391): the share button is gone; a menu anchored inside the settings dialog (same list picker as before;
    // 2.7.0: anchored in Account, the Agents page only shows with the module or agents)
    const sb = d.querySelector('.modal.smodal [data-m="go-share"]');
    w.__sb = sb;
    w.eval(`menu(window.__sb, S.lists.filter(l => !l.archived && !l.is_inbox && canManage(l)).map(l => ({label: lname(l), icon: 'list', fn: () => { document.querySelector('.modal.smodal')?.remove(); shareModal(l.id); }})))`); await sleep(200);
    const pop = d.querySelector('#pop');
    check(!pop.classList.contains('hidden') && pop.classList.contains('overmodal') && d.querySelector('#scrim').classList.contains('overmodal'), `${mobile ? 'phone' : 'desktop'}: the share menu is marked to show above the dialog`);
    const it = [...pop.querySelectorAll('button')].find(b => /Website/.test(b.textContent));
    click(w, it); await sleep(700);
    check(!pop.classList.contains('overmodal') && d.querySelector('.modal #l-members') && !d.querySelector('.modal.smodal'), `${mobile ? 'phone' : 'desktop'}: picked: the Share dialog (2.6.0)`);
    [...d.querySelectorAll('.modal')].forEach(m => m.remove());
    w.eval(`menu(document.querySelector('#top h1'), [{label: 'x', fn() {}}])`);
    check(!d.querySelector('#pop').classList.contains('overmodal'), 'a menu outside a dialog stays at its usual level');
    w.eval('closePop()');
    w.close();
  }
  check(/#scrim\.overmodal\{z-index:74\}#pop\.overmodal\{z-index:76\}/.test(css), 'CSS: above the dialog (70), below toasts');

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + PRIV}); d = w.document;
  w.eval(`openDetail(${taxes})`); await sleep(700);
  check(d.querySelector('#detail #c-input')?.placeholder === 'Kommentar schreiben…', 'German: "Kommentar schreiben…"');
  key(w, '?'); await sleep(100);
  check(/Mehrfachauswahl/.test(d.querySelector('.kbmodal')?.textContent || '') && /Zu heute springen/.test(d.querySelector('.kbmodal').textContent), 'German: Mehrfachauswahl, Zu heute springen');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p206_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); console.log('FAIL: crashed', e); process.exit(1); });
