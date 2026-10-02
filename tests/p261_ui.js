// 2.6.1 UI tests, own container (start.sh). jsdom: #401 the date popover saves at once (one undo step per visit, "Saved",
// Undo in its foot puts everything back, Done + the toast's Undo), the setting "Confirm changes with OK" brings Cancel / OK
// back; #402 a status dot per agent in the header, always (also idle / never connected), green / blue / yellow / grey / red,
// names + states in the tooltip and the menu, Settings > Agents > Overview > "In the header" hides single agents; #403 the
// bell opens a dropdown with the newest News (the view stays, Esc / outside closes, "Show all" goes to #news); #404 filter
// chips in the News view and under the bell (view only, per device), the list bell's "Custom selection…" (menu, dialog with
// the events x News / Push, list dialog) and the German texts; SW v73.
// Then Firefox headless (WebDriver BiDi, skipped without firefox), touch emulation at 360 x 780 and 390 x 844, a mouse at
// 1280 x 800 and 1920 x 1080: with two agents (one idle and never connected, one working) and a running timer the title,
// "…" and the bell stay inside the viewport, the agents' dots are on screen (pill or status chip), the bell opens a sheet
// (phone) / a dropdown inside the viewport (desktop), touch targets of the pill and the chips >= 44 px
// (screenshots with P261_SHOTS=<dir>).
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const {boot, sleep, B, login} = require('./boot');
const WS = globalThis.WebSocket || require('ws');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

const firefox = require('./ff')({tag: 'p261_ui', check, shots: 'P261_SHOTS'});  // 2.7.2: the shared Firefox helper (with the start retry)
const HEAD = `(() => {
  const t = document.querySelector('#top'); if (!t || !t.querySelector('h1')) return {none: location.href};
  const vw = document.documentElement.clientWidth;
  const R = e => { if (!e || !e.offsetWidth) return null; const b = e.getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom, b.width, b.height]; };
  const out = [...t.children].filter(e => e.offsetWidth && e.getBoundingClientRect().right > vw + 0.5).map(e => e.className || e.tagName);
  const dots = [...t.querySelectorAll('.hdot')].filter(e => e.offsetWidth && e.getBoundingClientRect().right <= vw + .5).map(e => e.className);
  const clip = [...t.querySelectorAll(':scope > .tmini, :scope > .achip, :scope > .stchip')].filter(e => e.offsetWidth && e.scrollWidth > e.clientWidth + 1).map(e => e.className);
  return {clip, lvl: (t.className.match(/tl\\d/) || [''])[0], vw, more: R(t.querySelector('[data-act="top-more"]')), bell: R(t.querySelector('.bell')), out, dots,
    ach: R(t.querySelector('.achip')), st: R(t.querySelector('.stchip')), ht: R(t.querySelector('h1 .ht'))};
})()`;

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v7[3-9]'/.test(SW), 'service worker cache v73 (2.7.0: v74, 2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const ag2 = await call('POST', '/api/admin/agents', {username: 'helper', display_name: 'Helper'});
  const L = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project'})).id;
  for (const id of [BOB, ag.id, ag2.id]) await call('PUT', `/api/lists/${L}/members`, {user_id: id, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Go live', list_id: L, due: day(5)})).id;
  for (let i = 0; i < 3; i++) await call('POST', '/api/tasks', {title: `Task ${i + 1}`, list_id: L, due: day(i)});
  const getT = id => call('GET', `/api/tasks/${id}`);

  // ================= #401 the date popover saves at once
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  check(w.eval('dateInstant()') === true, 'default: instant');
  w.eval(`datePop(document.querySelector('#top h1'), ${T})`); await sleep(100);
  let pop = d.querySelector('#pop');
  check(pop.querySelector('[data-q="done"]') && !pop.querySelector('[data-q="ok"]') && pop.querySelector('[data-q="revert"]').hidden && /apply at once/.test(pop.querySelector('.psaved').textContent),
    'foot: "Changes apply at once" + Done, Undo hidden, no OK');
  click(w, pop.querySelector('[data-q="1"]')); await sleep(900);
  check((await getT(T)).due === day(1), 'Tomorrow is saved at once (popover still open): ' + (await getT(T)).due);
  check(!pop.classList.contains('hidden') && /Saved/.test(pop.querySelector('.psaved').textContent) && !pop.querySelector('[data-q="revert"]').hidden, '"Saved" + Undo in the foot');
  click(w, pop.querySelector('[data-rem="0"]')); await sleep(900);
  check(((await getT(T)).reminders || '').length > 0, 'a reminder too: ' + (await getT(T)).reminders);
  const nUndo = w.eval('HIST.undo.length');
  click(w, pop.querySelector('[data-q="done"]')); await sleep(400);
  check(pop.classList.contains('hidden') && w.eval('HIST.undo.length') === nUndo + 1, 'Done closes; ONE undo step for the visit');
  const toastEl = d.querySelector('#toast');
  check(!toastEl.classList.contains('hidden') && /Date:/.test(toastEl.textContent) && toastEl.querySelector('button'), 'toast "Date: …" with Undo: ' + toastEl.textContent);
  click(w, toastEl.querySelector('button')); await sleep(900);
  let t0 = await getT(T);
  check(t0.due === day(5) && !t0.reminders, 'the toast\'s Undo restores day AND reminder: ' + t0.due + ' ' + t0.reminders);
  // Undo in the foot: back + closed, no history step
  w.eval(`datePop(document.querySelector('#top h1'), ${T})`); await sleep(100);
  pop = d.querySelector('#pop');
  click(w, pop.querySelector('[data-q="0"]')); await sleep(900);
  check((await getT(T)).due === day(0), 'Today saved');
  const n2 = w.eval('HIST.undo.length');
  click(w, pop.querySelector('[data-q="revert"]')); await sleep(900);
  check((await getT(T)).due === day(5) && pop.classList.contains('hidden') && w.eval('HIST.undo.length') === n2, 'Undo in the foot: back, closed, no extra step');
  // closing with Esc / outside also keeps it (the change is already saved)
  w.eval(`datePop(document.querySelector('#top h1'), ${T})`); await sleep(100);
  click(w, d.querySelector('#pop [data-q="w"]')); await sleep(200);
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(900);
  check((await getT(T)).due === w.eval('nextWeekday(1)'), 'Esc right after a tap: still saved (sent on close)');
  await w.eval(`histStep('undo')`); await sleep(600);
  check((await getT(T)).due === day(5), 'Ctrl+Z / ← undoes it');
  // the setting
  w.eval(`settingsModal('general')`); await sleep(500);
  let md = d.querySelector('.smodal');
  const cb = md.querySelector('#s-dateok');
  check(cb && !cb.checked && /Confirm changes with OK/.test(cb.closest('label').textContent), 'Settings > General: "Confirm changes with OK" (off)');
  cb.checked = true; change(w, cb); await sleep(700);
  check((await call('GET', '/api/state')).settings.date_confirm === '1' && w.eval('dateInstant()') === false, 'switched on (server)');
  md.remove();
  w.eval(`datePop(document.querySelector('#top h1'), ${T})`); await sleep(100);
  pop = d.querySelector('#pop');
  check(pop.querySelector('[data-q="ok"]') && pop.querySelector('[data-q="cancel"]') && !pop.querySelector('[data-q="done"]'), 'with the setting: Cancel / OK');
  click(w, pop.querySelector('[data-q="1"]')); await sleep(700);
  check((await getT(T)).due === day(5), 'nothing saved before OK');
  click(w, pop.querySelector('[data-q="cancel"]')); await sleep(500);
  check((await getT(T)).due === day(5), 'Cancel: nothing saved');
  w.eval(`datePop(document.querySelector('#top h1'), ${T})`); await sleep(100);
  click(w, d.querySelector('#pop [data-q="1"]')); click(w, d.querySelector('#pop [data-q="ok"]')); await sleep(800);
  check((await getT(T)).due === day(1), 'OK saves');
  await call('PATCH', `/api/tasks/${T}`, {due: day(5)});
  await call('PATCH', '/api/settings', {date_confirm: '0'});
  w.close();

  // ================= #402 status dots for every agent, always (2.8.0: in views without the agent band, e.g. the calendar;
  // where the band shows, the dots live there and the pill keeps only the robot)
  w = await boot({user: 'alice', hash: 'cal'}); d = w.document;
  check(!d.querySelector('#view .agband'), 'calendar: no agent band');
  let chip = d.querySelector('#top .achip');
  check(chip && chip.classList.contains('calm') && chip.querySelectorAll('.hdot').length === 2 && chip.querySelectorAll('.hdot.hs-offline').length === 2 && !chip.querySelector('.act'),
    'two agents never connected: the pill with two grey dots, no busy text');
  check(/Claude: not connected/.test(chip.title) && /Helper: not connected/.test(chip.title) && /Agents: Claude not connected, Helper not connected/.test(chip.getAttribute('aria-label')), 'tooltip + label: names and states: ' + chip.title);
  check(chip.getAttribute('aria-haspopup') === 'menu', 'a menu button');
  w.close();
  await v1(ag.token, 'GET', '/agent/events'); await v1(ag2.token, 'GET', '/agent/events');
  await v1(ag.token, 'PUT', '/agent/status', {status: 'working', task_id: T, text: 'Checking links'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(d.querySelector('#view .agband .agb-a.hs-working') && d.querySelector('#view .agband .agb-a.hs-ready') && d.querySelector('#top .achip .abot') && !d.querySelector('#top .achip .hdot'), '2.8.0: list with agents: the dots in the band, the robot in the header');
  w.close();
  w = await boot({user: 'alice', hash: 'cal'}); d = w.document;
  chip = d.querySelector('#top .achip');
  check(chip.querySelector('.hdot.hs-working') && chip.querySelector('.hdot.hs-ready') && chip.classList.contains('busy') && /Claude/.test(chip.querySelector('.act')?.textContent || ''),
    'working = blue dot, idle = green dot, busy text next to them: ' + chip.textContent);
  check(w.eval(`agentHst({enabled: true, contact_age: 1, status: 'error'})`) === 'error' && w.eval(`agentHst({enabled: true, contact_age: 1, status: 'idle', limit_reached: true})`) === 'error'
    && w.eval(`agentHst({enabled: true, contact_age: 1, status: 'idle', waiting: 1})`) === 'waiting' && w.eval(`agentHst({enabled: false, contact_age: 1, status: 'idle'})`) === 'offline'
    && w.eval(`agentHst({enabled: true, contact_age: 1, status: 'idle'})`) === 'ready', 'states: error / limit = red, waiting = yellow, paused = grey, idle = green');
  check(w.eval(`hdotsHtml([1,2,3,4,5,6,7].map(i => ({id: i, enabled: true, contact_age: 1, status: 'idle', name: 'A' + i})))`).match(/class="hdot /g).length === 4 && /\+3/.test(w.eval(`hdotsHtml([1,2,3,4,5,6,7].map(i => ({id: i, enabled: true, contact_age: 1, status: 'idle', name: 'A' + i})))`)), 'many agents: 4 dots + "+3"');
  click(w, chip); await sleep(200);
  const mi = [...d.querySelectorAll('#pop .menu-list button')];
  check(mi.length >= 4 && mi[0].querySelector('.hdot') && /Claude: working · Checking links/.test(mi[0].textContent) && /Helper: ready/.test(mi[1].textContent), 'menu: every agent with its dot and state: ' + mi.map(x => x.textContent.trim()).join(' | '));
  const choose = mi.find(x => /Choose the agents shown/.test(x.textContent));
  check(choose, 'menu: "Choose the agents shown…"');
  click(w, choose); await sleep(800);
  md = d.querySelector('.smodal');
  const vis = [...md.querySelectorAll('[data-agvis]')];
  check(md.querySelector('#s-agdots-h') && vis.length === 2 && vis.every(x => x.checked) && md.querySelector('#sp-ai:not(.hidden)'), 'Settings > Agents > Overview > "In the header": both ticked');
  const hv = vis.find(x => +x.dataset.agvis === ag2.id); hv.checked = false; change(w, hv); await sleep(800);
  check((await call('GET', '/api/state')).settings.agents_hidden === String(ag2.id), 'agents_hidden saved: ' + (await call('GET', '/api/state')).settings.agents_hidden);
  check(d.querySelectorAll('#top .achip .hdot').length === 1 && !d.querySelector('#top .achip .hdot.hs-ready'), 'header: only Claude\'s dot now');
  const cv = vis.find(x => +x.dataset.agvis === ag.id); cv.checked = false; change(w, cv); await sleep(800);
  check(d.querySelector('#top .achip') && !d.querySelector('#top .achip .hdot') && d.querySelector('#top .achip .act'), 'none shown: the busy pill stays (old look) while Claude works');
  md.remove();
  await v1(ag.token, 'PUT', '/agent/status', {status: 'idle'});
  w.eval('agentPoll()'); await sleep(800);
  check(!d.querySelector('#top .achip'), 'none shown and nobody busy: no pill');
  await call('PATCH', '/api/settings', {agents_hidden: ''});
  w.close();
  // German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(/Agenten: Claude bereit, Helper bereit/.test(d.querySelector('#top .achip')?.getAttribute('aria-label') || ''), 'German label: ' + d.querySelector('#top .achip')?.getAttribute('aria-label'));
  w.eval(`settingsModal('general')`); await sleep(500);
  check(/Änderungen mit OK bestätigen/.test(d.querySelector('.smodal #s-dateok')?.closest('label')?.textContent || ''), 'German: "Änderungen mit OK bestätigen"');
  d.querySelector('.smodal').remove();
  w.eval(`bellMenu(document.querySelector('#top h1'), ${L})`); await sleep(200);
  check(/Eigene Auswahl…/.test(d.querySelector('#pop').textContent), 'German: "Eigene Auswahl…"');
  w.eval('closePop()');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #403 + #404 the bell's dropdown and the filter chips (bob gets News)
  await call('PATCH', `/api/tasks/${T}`, {assignee_id: BOB});
  for (let i = 0; i < 3; i++) await call('POST', `/api/tasks/${T}/comments`, {body: `Note ${i + 1}`});
  const BT = (await call('POST', '/api/tasks', {title: 'Bobs own', list_id: L}, CKB)).id;
  await call('POST', `/api/tasks/${BT}/comments`, {body: `<@${BOB}> please check`});
  const nb = (await call('GET', '/api/news', null, CKB)).items;
  check(nb.length >= 2 && nb.some(x => x.kind === 'assign') && nb.some(x => x.kind === 'mention'), 'bob has News: ' + nb.map(x => x.kind).join(','));
  w = await boot({user: 'bob', hash: 'l/' + L}); d = w.document;
  const bellB = d.querySelector('#top .bell');
  check(bellB && bellB.dataset.act === 'bell-pop' && bellB.getAttribute('aria-haspopup') === 'dialog' && bellB.querySelector('.nbadge'), 'the bell is a popup button with its badge');
  click(w, bellB); await sleep(900);
  pop = d.querySelector('#pop');
  check(!pop.classList.contains('hidden') && pop.classList.contains('bellpop') && pop.querySelectorAll('.bpop .nitem').length === nb.length && w.eval('S.route.mod') === 'tasks',
    'bell: a dropdown with the newest News, the list stays: ' + pop.querySelectorAll('.nitem').length);
  check(pop.querySelector('.bpop [data-bp="all"]') && /Show all/.test(pop.querySelector('[data-bp="all"]').textContent) && pop.querySelector('[data-bp="readall"]'), '"Show all" + "Mark all as read"');
  const chips = [...pop.querySelectorAll('.nchips [data-bpk]')].map(x => x.textContent.trim());
  check(chips[0] === 'All' && chips.includes('Mentions') && chips.includes('Assignments') && !chips.includes('Status'), 'chips only for kinds that are there: ' + chips.join(','));
  click(w, pop.querySelector('[data-bpk="mention"]')); await sleep(100);
  pop = d.querySelector('#pop');
  check([...pop.querySelectorAll('.bpop .nitem')].every(x => x.classList.contains('k-mention')) && pop.querySelectorAll('.bpop .nitem').length === 1 && w.eval(`LS.get('newsKind')`) === 'mention',
    'chip "Mentions": only mentions (remembered on this device)');
  click(w, pop.querySelector('[data-bpk="mention"]')); await sleep(100);
  check(d.querySelectorAll('#pop .bpop .nitem').length === nb.length && w.eval(`S.nf.kind`) === '', 'the same chip again: all');
  key(w, d.body, 'Escape'); await sleep(100);
  check(d.querySelector('#pop').classList.contains('hidden') && w.eval('S.route.mod') === 'tasks', 'Esc closes, the list stays');
  click(w, d.querySelector('#top .bell')); await sleep(400);
  click(w, d.querySelector('#scrim')); await sleep(100);
  check(d.querySelector('#pop').classList.contains('hidden'), 'a click outside closes');
  click(w, d.querySelector('#top .bell')); await sleep(400);
  const first = d.querySelector('#pop .bpop .nitem');
  const tid = w.eval(`S.nf.items[${first.dataset.i}].task_id`);
  click(w, first); await sleep(900);
  check(d.querySelector('#pop').classList.contains('hidden') && w.eval('S.sel') === tid, 'an item opens its task, the dropdown closes');
  click(w, d.querySelector('#top .bell')); await sleep(400);
  click(w, d.querySelector('#pop [data-bp="all"]')); await sleep(700);
  check(w.eval('S.route.mod') === 'news' && d.querySelector('#pop').classList.contains('hidden'), '"Show all" opens the News view');
  // the chips in the News view
  const vchips = [...d.querySelectorAll('#view .nchips [data-nk]')];
  check(vchips.length >= 3 && vchips[0].classList.contains('on'), 'News view: chips, "All" on');
  click(w, d.querySelector('#view .nchips [data-nk="assign"]')); await sleep(300);
  check(d.querySelectorAll('#view .nitem').length >= 1 && [...d.querySelectorAll('#view .nitem')].every(x => /k-(assign|unassign)/.test(x.className)), 'News view: chip "Assignments"');
  click(w, d.querySelector('#view .nchips [data-nk=""]')); await sleep(300);
  check(d.querySelectorAll('#view .nitem').length === nb.length, 'News view: "All" again');
  w.close();
  // phone: a sheet from the bottom
  w = await boot({user: 'bob', mobile: true, hash: 'l/' + L}); d = w.document;
  click(w, d.querySelector('#top .bell')); await sleep(900);
  check(d.querySelector('#pop.bellpop.sheet .bpop'), 'phone: the bell opens a sheet');
  w.close();

  // ================= #404 the custom bell in the UI
  w = await boot({user: 'bob', hash: 'l/' + L}); d = w.document;
  w.eval(`bellMenu(document.querySelector('#top h1'), ${L})`); await sleep(200);
  const bells = [...d.querySelectorAll('#pop .menu-list button')];
  check(bells.map(b => b.textContent.trim()).join('|') === 'All activity|Default|Mute|Custom selection…', 'bell menu: four options: ' + bells.map(b => b.textContent.trim()).join('|'));
  click(w, bells[3]); await sleep(300);
  md = d.querySelector('.modal.bcmodal');
  const rows = [...md.querySelectorAll('.nmr')].map(r => r.querySelector('.nml').textContent);
  check(md && /Notifications for Launch/.test(md.querySelector('h3').textContent) && rows.some(r => /New tasks/.test(r)) && rows.some(r => /Comments/.test(r)) && rows.some(r => /Mentions of me/.test(r))
    && rows.some(r => /Completed tasks/.test(r)) && rows.some(r => /Project status/.test(r)) && rows.some(r => /approval/.test(r)), 'dialog: the events: ' + rows.join(' | '));
  check(md.querySelector('[data-bc="comment"][data-ch="news"]').checked && !md.querySelector('[data-bc="newtask"][data-ch="news"]').checked, 'starts from the matrix (comments on, new tasks off)');
  md.querySelector('[data-bc="newtask"][data-ch="news"]').checked = true;
  md.querySelector('[data-bc="comment"][data-ch="push"]').checked = false;
  click(w, md.querySelector('[data-bcq="save"]')); await sleep(800);
  let lb = (await call('GET', '/api/state', null, CKB)).lists.find(l => l.id === L);
  check(lb.bell === 'custom' && lb.bell_custom.newtask.news === 1 && lb.bell_custom.comment.push === 0 && lb.bell_custom.comment.news === 1, 'saved: ' + JSON.stringify(lb.bell_custom));
  check(/Notifications for Launch: Custom selection/.test(d.querySelector('#toast').textContent), 'toast: ' + d.querySelector('#toast').textContent);
  check(w.eval(`listMenuItems(${L}).some(x => x.label === 'Notifications: Custom selection')`), 'list menu names it');
  w.eval(`listModal(${L})`); await sleep(500);
  const lsel = d.querySelector('.lmodal #l-bell');
  check(lsel.value === 'custom' && !d.querySelector('.lmodal #l-bellc').hidden && /own choice per event/.test(d.querySelector('#l-bellhint').textContent), 'list dialog: custom + "Choose events…"');
  lsel.value = 'mute'; change(w, lsel); await sleep(700);
  check((await call('GET', '/api/state', null, CKB)).lists.find(l => l.id === L).bell === 'mute' && d.querySelector('.lmodal #l-bellc').hidden, 'list dialog: back to Mute');
  lsel.value = 'custom'; change(w, lsel); await sleep(300);
  md = d.querySelector('.modal.bcmodal');
  check(md && md.querySelector('[data-bc="newtask"][data-ch="news"]').checked, 'custom again: the stored choice');
  click(w, md.querySelector('[data-bcq="cancel"]')); await sleep(200);
  check(lsel.value === 'mute' && (await call('GET', '/api/state', null, CKB)).lists.find(l => l.id === L).bell === 'mute', 'Cancel: the select shows the bell as it is');
  await call('PUT', `/api/lists/${L}/bell`, {mode: 'default'}, CKB);
  w.close();

  // ================= Firefox: the header with the dots, the bell's dropdown / sheet
  await call('PATCH', '/api/settings', {lang: 'en'});
  await v1(ag2.token, 'GET', '/agent/events');
  await v1(ag.token, 'PUT', '/agent/status', {status: 'working', task_id: T, text: 'Checking links'});
  await call('POST', '/api/time/start', {task_id: T});
  for (const touch of [true, false]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      check(lgi === 200, 'Firefox: login');
      let nr = 0;
      const open = async hash => { await nav(B + 'static/icon.svg'); await nav(B + '?v=' + (++nr) + '#' + hash); for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); };
      for (const [vw, vh] of touch ? [[360, 780], [390, 844]] : [[1280, 800], [1920, 1080]]) {
        await v1(ag.token, 'GET', '/agent/events'); await v1(ag2.token, 'GET', '/agent/events');  // stay connected
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        await open('l/' + L); await sleep(2200);
        const hd = await ev(HEAD);
        check(hd.more && hd.bell && hd.more[1] <= vw + .5 && hd.bell[1] <= vw + .5 && !hd.out.length, `${vw}px: "…" and the bell in view, nothing sticking out ${JSON.stringify(hd)}`);
        // 2.8.0 (#434): on the desktop the list's agent band carries the dots (the header keeps the robot)
        const bandDots = touch ? 0 : await ev(`document.querySelectorAll('#view .agband .hdot').length`);
        check((hd.dots.length >= 1 || bandDots >= 1) && (hd.ach || hd.st), `${vw}px: the agents' dots are on screen (${hd.dots.length} header, ${bandDots} band) ${hd.lvl}`);
        check(!hd.clip.length, `${vw}px: no pill cut inside (timer time, dots): ${hd.clip.join(',')} ${hd.lvl}`);
        if (touch) {
          const tgt = hd.st || hd.ach;
          check(tgt && tgt[4] >= 43.5 && tgt[5] >= 43.5, `${vw}px touch: the dots' button >= 44 px ${JSON.stringify(tgt)}`);
        }
        await shot(`p261-head-${vw}.png`);
        await ev(`document.querySelector('#top .bell').click(); 1`); await sleep(1200);
        const bp = await ev(`(() => { const p = document.querySelector('#pop'); const r = p.getBoundingClientRect(); const ch = [...p.querySelectorAll('.nchip, [data-bp="all"]')].map(e => { const b = e.getBoundingClientRect(); return [b.width, b.height]; }); return {open: !p.classList.contains('hidden'), sheet: p.classList.contains('sheet'), l: r.left, r: r.right, t: r.top, b: r.bottom, ih: innerHeight, iw: innerWidth, ch, mod: S.route.mod}; })()`);
        check(bp.open && bp.l >= 0 && bp.r <= bp.iw + .5 && bp.b <= bp.ih + .5 && bp.mod === 'tasks', `${vw}px: the bell's ${touch ? 'sheet' : 'dropdown'} inside the viewport, the view stays ${JSON.stringify(bp)}`);
        check(touch ? bp.sheet : !bp.sheet, `${vw}px: ${touch ? 'a sheet' : 'a dropdown'}`);
        if (touch) check(bp.ch.every(([cw, chh]) => cw >= 43.5 && chh >= 43.5), `${vw}px: chips + "Show all" >= 44 px ${JSON.stringify(bp.ch)}`);
        await shot(`p261-bell-${vw}.png`);
        await ev(`closePop(); 1`);
      }
      // the date popover's foot on a phone / desktop
      await ev(`datePop(document.querySelector('#top h1'), ${T}); 1`); await sleep(400);
      const dp = await ev(`(() => { const f = document.querySelector('#pop .popfoot'); const r = f.getBoundingClientRect(); return {w: r.width, r: r.right, iw: innerWidth, done: !!f.querySelector('[data-q="done"]')}; })()`);
      check(dp.done && dp.r <= dp.iw + .5, `date popover foot in view ${JSON.stringify(dp)}`);
      await shot(`p261-date-${touch ? 'phone' : 'desktop'}.png`);
      await ev(`(() => { popOnClose = null; closePop(); return 1; })()`);
    }, touch);
  }

  console.log(`p261_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
