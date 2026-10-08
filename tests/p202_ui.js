// 2.0.2 UI tests (jsdom), fresh DB: comments right below the description (folded to the newest, remembered per device;
// long descriptions fold after ~8 lines; phones: "Details | Comments"), editing a title in the list (double-click, E),
// keyboard (arrows, Space, Enter, focus ring), recently viewed in the command palette, own list icons (presets, sidebar,
// header, palette, list dialog), "+" on section headers, collapse / expand all ("…" + Shift+C), drag autoscroll speed,
// share from the phone (server address without /drop, new token in place), "Claude is writing …"
// (task panel, chat, spinning ring on the chip / agents button, dot while waiting), German texts.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const cks = {};
const call = async (u, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cks[u]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
let AT = '';
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + AT}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const key = (w, k, o = {}) => w.document.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  cks.alice = await login('alice');
  const bob = (await call('alice', 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  cks.bob = await login('bob');
  for (const u of ['alice', 'bob']) await call(u, 'PATCH', '/api/settings', {features: 'kanban,timeline,collab,agents,comments', lang: 'en'});
  const ag = await call('alice', 'POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  AT = ag.token; const CL = ag.id;
  const L = (await call('alice', 'POST', '/api/lists', {name: 'Film'})).id;
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: bob, role: 'edit'});
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: CL, role: 'edit'});
  const S1 = (await call('alice', 'POST', '/api/sections', {list_id: L, name: 'Shoot'})).id;
  const S2 = (await call('alice', 'POST', '/api/sections', {list_id: L, name: 'Edit'})).id;
  const long = Array.from({length: 14}, (_, i) => `Line ${i + 1} of the brief`).join('\n');
  const T1 = (await call('alice', 'POST', '/api/tasks', {title: 'Cut trailer', list_id: L, section_id: S1, content: long})).id;
  const T2 = (await call('alice', 'POST', '/api/tasks', {title: 'Colour grade', list_id: L, section_id: S2})).id;
  const T3 = (await call('alice', 'POST', '/api/tasks', {title: 'Music', list_id: L, section_id: S2})).id;
  await call('alice', 'POST', '/api/tasks', {title: 'Sub one', list_id: L, parent_id: T3});
  for (const b of ['First note', 'Second note', 'Newest note']) await call('bob', 'POST', `/api/tasks/${T1}/comments`, {body: b});

  // ---- #242 comments in the task panel; 2.0.6 (#316 / #322): at the end of the panel, all of them (no
  // folding any more), the box at the bottom edge (sticky, see p206_ui.js); long descriptions still fold
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`openDetail(${T1})`); await sleep(1300);
  const tl = d.querySelector('#d-tl');
  const body = [...d.querySelectorAll('#detail .dbody > *, #detail .dcpane > *')].map(x => x.id || x.className);
  // 2.24.0 (UX-41): the comments follow the subtasks; only "More details" (folded) may come after them
  check(body.filter(x => x !== 'd-more' && x !== 'dmore').indexOf('d-tl') === body.filter(x => x !== 'd-more' && x !== 'dmore').length - 1 && body.indexOf('d-content') < body.indexOf('d-tl'), 'comments at the end of the panel (before "More details"): ' + body.join('|').slice(0, 160));
  const cms = [...tl.querySelectorAll('.cm')];
  check(cms.length === 3 && cms[2].classList.contains('last') && /Newest note/.test(cms[2].textContent) && !tl.classList.contains('fold') && !tl.querySelector('.cmfold'), 'all three comments, no folding');
  check(/Comments/.test(tl.querySelector('.cmhead').textContent) && tl.querySelector('#d-tl-count').textContent === '3', 'bar "Comments (3)"');
  check(d.querySelector('#detail .dbot .dcomp .ccomp #c-input') && !tl.querySelector('#c-input'), 'the comment box sits at the bottom edge, not in the list');
  const md = d.querySelector('#d-md');
  check(md.classList.contains('clamp') && d.querySelector('[data-act="md-more"]')?.textContent === 'Show more', 'long description folded after ~8 lines, "Show more"');
  d.querySelector('[data-act="md-more"]').click(); await sleep(100);
  check(!md.classList.contains('clamp') && d.querySelector('[data-act="md-more"]').textContent === 'Show less', 'Show more unfolds it');
  w.eval(`closeDetail(); openDetail(${T2})`); await sleep(900);
  check(!d.querySelector('[data-act="md-more"]'), 'short description: no "Show more"');
  w.eval('closeDetail()'); await sleep(300);

  // ---- #183 keyboard: arrows, Space, Enter, focus ring; #182 E / double-click edits the title in the list
  w.eval(`go('l/${L}')`); await sleep(500);
  w.eval('document.activeElement?.blur?.(); S.kf = null');  // 2.16.0 (#473): closing a task puts the focus back on its row; start from nothing here
  key(w, 'ArrowDown'); await sleep(100);
  const first = d.querySelector('#view .trow.kfocus');
  check(first && +first.dataset.id === T1, 'ArrowDown focuses the first task (focus ring class)');
  key(w, 'ArrowDown'); await sleep(100);
  check(+d.querySelector('#view .trow.kfocus')?.dataset.id === w.eval('rowIds()[1]'), 'ArrowDown again: next task');
  key(w, 'ArrowUp'); await sleep(100);
  check(+d.querySelector('#view .trow.kfocus')?.dataset.id === T1, 'ArrowUp: back');
  w.eval(`kfocus(${T2})`);
  key(w, 'e'); await sleep(150);
  let inp = d.querySelector(`#view .trow[data-id="${T2}"] .ttlin`);
  check(inp && inp.value === 'Colour grade' && d.activeElement === inp, 'E edits the title in the list');
  inp.value = 'Colour grading'; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  w.eval('renderView()'); await sleep(50);  // a sync re-render keeps the field and the text
  inp = d.querySelector(`#view .trow[data-id="${T2}"] .ttlin`);
  check(inp && inp.value === 'Colour grading', 'a re-render keeps the inline edit');
  inp.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); await sleep(900);
  check((await call('alice', 'GET', `/api/tasks/${T2}`)).title === 'Colour grading' && !d.querySelector('.ttlin'), 'Enter saves the new title');
  check(w.eval('HIST.undo.length') > 0 && /Colour grading/.test(w.eval('HIST.undo[HIST.undo.length-1].label')), 'one undo step for the rename');
  const tm = d.querySelector(`#view .trow[data-id="${T3}"] .tmain`);
  tm.dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true})); await sleep(150);
  inp = d.querySelector(`#view .trow[data-id="${T3}"] .ttlin`);
  check(inp && inp.value === 'Music', 'double-click edits the title in the list');
  inp.value = 'Changed'; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  inp.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); await sleep(400);
  check(!d.querySelector('.ttlin') && (await call('alice', 'GET', `/api/tasks/${T3}`)).title === 'Music', 'Esc cancels');
  w.eval(`kfocus(${T2})`);
  key(w, ' '); await sleep(900);
  check((await call('alice', 'GET', `/api/tasks/${T2}`)).status === 2, 'Space completes the focused task');
  w.eval(`toggleTask(${T2})`); await sleep(700);
  w.eval(`kfocus(${T1})`); key(w, 'Enter'); await sleep(500);
  check(w.eval('S.sel') === T1, 'Enter opens it');
  w.eval('closeDetail()');
  w.eval('shortcutsModal()'); await sleep(100);
  const kbt = d.querySelector('.kbmodal').textContent;
  check(/Complete task \(or X\)/.test(kbt) && /Edit title in the list/.test(kbt) && /Collapse or expand all/.test(kbt) && /Next task \(or J\)/.test(kbt), 'shortcut help lists the new keys');
  d.querySelector('.kbmodal [data-m="close"]').click();

  // ---- #184 recently viewed on top of the palette
  w.eval('openPalette()'); await sleep(200);
  const pg = d.querySelector('.palette .pgroup');
  const pis = [...d.querySelectorAll('.palette .pitem')].slice(0, 3).map(x => x.querySelector('.plt').textContent);
  check(pg && pg.textContent === 'Recently viewed' && pis[0] === 'Cut trailer' && pis.includes('Film'), 'Recently viewed: last task + list first ' + pis.join('|'));
  d.querySelector('.palette .pitem').click(); await sleep(600);
  check(w.eval('S.sel') === T1 && !JSON.parse(w.__store['tasks.palRecent'] || '[]').some(x => x.startsWith('rv:')), 'opening from there works, no double entry in Recent');
  w.eval('closeDetail()');

  // ---- #283 "+" on section headers
  const gh = d.querySelector(`#view .ghead[data-section="${S2}"]`);
  check([...d.querySelectorAll('#view .ghead[data-section]')].every(g => g.querySelector('.gadd')), '"+" on every section header');
  gh.querySelector('.gadd').click(); await sleep(200);
  let si = d.querySelector('#view .secadd-in');
  check(si && si.dataset.sec === String(S2) && d.activeElement === si && /Edit/.test(si.placeholder), 'input right in the section, focused');
  si.value = 'Titles !high'; si.dispatchEvent(new w.Event('input', {bubbles: true}));
  si.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); await sleep(1200);
  const nt = [...w.eval('S.tasks').values()].find(t => t.title === 'Titles');
  check(nt && nt.section_id === S2 && nt.priority === 5 && nt.list_id === L, 'Enter adds it to that section (quick-add syntax works)');
  si = d.querySelector('#view .secadd-in');
  check(si && si.value === '' && d.activeElement === si, 'the input stays open for the next one');
  si.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); await sleep(200);
  check(!d.querySelector('#view .secadd-in'), 'Esc closes it');

  // ---- #284 collapse / expand all
  const items = w.eval('topMoreItems()').filter(x => x.label);
  check(items.some(x => x.label === 'Collapse all') && items.some(x => x.label === 'Expand all'), '"…": Collapse all / Expand all');
  key(w, 'C', {shiftKey: true}); await sleep(200);
  check([...d.querySelectorAll('#view .ghead[data-section]')].every(g => g.classList.contains('closed')) && !d.querySelector('#view .trow'), 'Shift+C collapses every section');
  const lsC = JSON.parse(w.__store['tasks.collapsed'] || '[]');
  check(lsC.includes('s:' + S1) && lsC.includes('s:' + S2) && lsC.includes('t' + T3), 'remembered per device (sections + tasks with subtasks)');
  key(w, 'C', {shiftKey: true}); await sleep(200);
  check(![...d.querySelectorAll('#view .ghead')].some(g => g.classList.contains('closed')) && d.querySelectorAll('#view .trow.sub').length === 1, 'Shift+C again expands all (subtasks too)');

  // ---- #285 autoscroll while dragging (speed by distance to the edge)
  check(w.eval('dsSpeed(250, 0, 500)') === 0 && w.eval('dsSpeed(2, 0, 500)') < -15 && w.eval('dsSpeed(40, 0, 500)') < 0 && w.eval('dsSpeed(40, 0, 500)') > w.eval('dsSpeed(2, 0, 500)') && w.eval('dsSpeed(498, 0, 500)') > 15, 'speed grows towards the edge');
  w.eval(`window.__fb = {isConnected: true, scrollTop: 300, scrollHeight: 3000, clientHeight: 500, scrollWidth: 0, clientWidth: 0, getBoundingClientRect: () => ({top: 100, bottom: 600, left: 0, right: 800})}; DS.on = true; DS.box = __fb; DS.x = 300; DS.y = 590; DS.last = Date.now(); dsStep();`);
  check(w.eval('__fb.scrollTop') > 300, 'near the bottom edge: scrolls down');
  w.eval('DS.y = 105; dsStep();');
  check(w.eval('__fb.scrollTop') < w.eval('300 + 22'), 'near the top edge: scrolls up');
  w.eval('dsStop()');
  check(!w.eval('DS.on'), 'drop / dragend stops it');

  // ---- #245 own list icons
  await call('alice', 'PUT', `/api/lists/${L}/icon`, {preset: 'kalmido'});
  w.eval('load().then(render)'); await sleep(700);
  check(d.querySelector(`#side .srow[data-list="${L}"] img.licon`)?.getAttribute('src') === '/static/icon.svg', 'sidebar: the picture instead of the dot');
  check(d.querySelector('#top h1 img.licon')?.getAttribute('src') === '/static/icon.svg', 'header: the picture before the list name');
  w.eval('openPalette()'); await sleep(150);
  const pin = d.querySelector('.palette .picon');
  check(pin && pin.getAttribute('src') === '/static/icon.svg', 'palette: the picture');
  w.eval('closePalette()');
  w.eval(`listModal(${L})`); await sleep(400);
  const lm = d.querySelector('.modal');
  check(lm.querySelector('#l-emo img.licon'), 'list dialog: the icon button shows the picture');
  check(lm.querySelectorAll('.lipick [data-licon]').length >= 12 && lm.querySelector('.lipick [data-licon="kalmido"].on'), 'picture presets (app icon + profile pictures) + upload, the current one marked');
  lm.querySelector('.lipick [data-licon="robot"]').click(); await sleep(900);
  check(w.eval(`listById(${L}).icon`) === '/static/avatars/robot.svg' && lm.querySelector('#l-emo img')?.getAttribute('src') === '/static/avatars/robot.svg', 'pick a preset: saved, shown at once');
  lm.querySelector('#l-emo').click(); lm.querySelector('#l-emogrid [data-emo="🎬"]').click(); await sleep(1200);
  check(w.eval(`listById(${L}).icon`) === '' && w.eval(`listById(${L}).name`) === '🎬Film', 'an emoji replaces the picture ' + w.eval(`listById(${L}).name`));
  lm.querySelector('#l-emo').click(); lm.querySelector('.lipick [data-licon="coffee"]').click(); await sleep(1500);
  check(w.eval(`listById(${L}).icon`) === '/static/avatars/coffee.svg' && w.eval(`listById(${L}).name`) === 'Film', 'a picture takes the emoji out of the name ' + w.eval(`listById(${L}).name`));
  lm.querySelector('[data-m="close"]').click(); await sleep(300);

  // ---- #293 share from the phone: server address without /drop, new token right there
  w.eval(`settingsModal('share')`); await sleep(700);
  check(d.querySelector('#s-dropurl').value === 'https://kalmido.example' && /Without \/drop/.test(d.querySelector('#sp-integr').textContent), 'server address without /drop + hint');
  check(/server address above followed by \/drop/.test(d.querySelector('#sp-integr').textContent), 'guide: by hand, /drop goes after the server address');
  const tok0 = (await call('alice', 'GET', '/api/me')).drop_token;
  d.querySelector('[data-m="drop-new-tok"]').click(); await sleep(1000);
  const tok1 = (await call('alice', 'GET', '/api/me')).drop_token;
  check(tok1 && tok1 !== tok0 && d.querySelector('#s-droptok').value === tok1 && d.querySelector('#s-droptok').type === 'text', 'New token in "Share from your phone": field shows the new one');
  d.querySelector('[data-m="close"]').click(); await sleep(200);
  w.eval(`settingsModal('share')`); await sleep(700);
  d.querySelector('[data-m="drop-copy-tok"]').click(); await sleep(500);  // loads the real token into the field
  // 2.7.0 (#405 S3): the upload token lives only under Share from your phone; Account links there
  w.eval(`settingsModal('account')`); await sleep(500);
  const sm = d.querySelector('.modal');
  check(!sm.querySelector('[data-acc="token-new"]') && sm.querySelector('[data-pane="account"] [data-m="go-share"]'), 'Account: no second "New token", a link to Share from your phone');
  sm.querySelector('[data-m="go-share"]').click(); await sleep(200);
  check(sm.querySelector('.snav [data-sec="integr"]').classList.contains('on') && sm.querySelector('#s-droptok'), 'the link opens Share from your phone');
  sm.querySelector('[data-m="close"]').click(); await sleep(200);

  // ---- #299 "Claude is writing …" (2.13.2 #478 F6: "working" on a task without a typing signal = "is working on it")
  await v1('PUT', '/agent/status', {status: 'working', text: 'Reading the brief', task_id: T1});
  w.eval('load().then(render)'); await sleep(700);
  check(d.querySelector('#top .achip.aspin'), 'header chip: spinning ring while working');
  check(/Claude: working · Reading the brief/.test(d.querySelector('#top .achip').title), 'chip tooltip: which agent and what');
  w.eval(`openDetail(${T1})`); await sleep(1000);
  let ty = d.querySelector('#d-typing');
  check(ty && !ty.classList.contains('hidden') && /Claude is working on it/.test(ty.textContent) && /Reading the brief/.test(ty.textContent), 'task panel: "Claude is working on it" + status text (2.13.2: "writing" only with a typing signal)');
  check(ty.closest('#d-tl'), 'in the comment list');
  w.eval(`openDetail(${T2})`); await sleep(900);
  check(d.querySelector('#d-typing').classList.contains('hidden'), 'not on another task (the agent named its task)');
  await v1('PUT', '/agent/status', {status: 'working', text: 'Tidying up'});
  w.eval('load().then(render)'); await sleep(800);
  // 2.30.0 (#1039, intended change): "working" without a task shows in the chat only, never in a task
  check(d.querySelector('#d-typing').classList.contains('hidden'), 'without a task: not in the tasks of its lists (2.30)');
  // typing in the comment box: no full reload, the indicator still follows
  const ci = d.querySelector('#c-input'); ci.focus();
  await v1('PUT', '/agent/status', {status: 'idle'});
  w.eval('agentPoll()'); await sleep(700);
  check(d.querySelector('#d-typing').classList.contains('hidden') && d.activeElement === ci, 'idle: gone, while the comment box keeps the focus');
  ci.blur();
  await v1('PUT', '/agent/status', {status: 'waiting', text: 'Need an OK'});
  w.eval('load().then(render)'); await sleep(700);
  check(d.querySelector('#top .achip.await') && !d.querySelector('#top .achip.aspin'), 'waiting: accent dot instead of the ring');
  await v1('PUT', '/agent/status', {status: 'working', text: 'Answering'});
  w.eval('load().then(render)'); await sleep(700);
  w.eval(`chatOpen(${CL})`); await sleep(800);
  ty = d.querySelector('#chat-typing');
  // 2.30.0 (#1039): "working" without a task shows under the chat's last message, as "is working on it" without typing dots
  check(ty && !ty.querySelector('.atdots') && /Claude is working on it/.test(ty.textContent), 'chat: "working" alone is no typing (no dots), but "is working on it" under the messages');
  check(d.querySelector('#side [data-go="agents"].aspin'), 'sidebar agents row: spinning ring');
  w.eval('chatClose()');
  w.close();

  // ---- phone: the jump to the comments (2.31.0, was "Details | Comments"), tab bar ring
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true, ls: {'tasks.tabbar': JSON.stringify(['m:tasks', 'agents', 'settings'])}}); d = w.document;
  w.eval(`openDetail(${T1})`); await sleep(1200);
  // 2.31.0 (#1054): no tabs any more: a small jump "To the comments (3)" next to the assignee, the comments stay below
  check(!d.querySelector('#detail .dtabs') && d.querySelector('#detail .dmeta [data-act="d-jump-cm"]') && d.querySelector('#d-jump-count').textContent === '3', 'phone: no Details | Comments tabs, a jump to the comments (3)');
  check(d.querySelectorAll('#d-tl .cm').length === 3 && d.querySelector('#detail .dcomp #c-input'), 'the comments + the box in the stream');
  check(d.querySelector('#tabs [data-go="agents"].aspin'), 'tab bar agents tab: spinning ring');
  w.close();

  // ---- #286 iOS home-screen app: 2.0.3 dropped the measured shift (it pushed the tab bar out of the web view); the
  // status bar is "black" now, so the page starts below it (checked in p203_ui.js)

  // ---- German
  await call('alice', 'PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`openDetail(${T1})`); await sleep(1200);
  check(/Kommentare/.test(d.querySelector('#d-tl .cmhead').textContent) && d.querySelector('[data-act="md-more"]').textContent === 'Mehr anzeigen', 'German: comments bar, Mehr anzeigen');
  await v1('PUT', '/agent/status', {status: 'working', task_id: T1});
  w.eval('load().then(render)'); await sleep(800);
  check(/Claude arbeitet daran/.test(d.querySelector('#d-typing').textContent), 'German: Claude arbeitet daran');
  w.eval('closeDetail(); openPalette()'); await sleep(200);
  check(d.querySelector('.palette .pgroup').textContent === 'Zuletzt angesehen', 'German: Zuletzt angesehen');
  w.close();

  const errList = errs.filter(e => !/Could not load|ECONNREFUSED|NetworkError|ResizeObserver/.test(e));
  check(!errList.length, 'no script errors: ' + errList.slice(0, 3).join(' | '));
  console.log(`p202_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); process.exit(1); });
