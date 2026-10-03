// 2.7.0 UI tests, own container (start.sh). jsdom: #412 the date popover (2 weeks / 1 month chips, "Other…" = an own
// reminder like 3 weeks, Deadline + "On Today from the first reminder", Repeat reminder), deadlines in the rows ("10 days
// left", highlighted from the first reminder on) and on Today, the task panel's line; #413 the nag in the popover, the
// list's default (list dialog), Settings > Notifications (quiet hours, the matrix row), the push route #nagoff/<id>;
// #414 "Shopping & packing list" (type select, cart, hint); #407 the time sum in the list / folder header (hours, days,
// budget bar), the list's hours per day, Administration > hours per day; #405 S2 (Agents page only with the module or for
// an admin with agents), S3 (upload token only under Share from your phone), S4 (no "Delete all completed" in Data),
// S5 (Status, Time tracking, German renames), S8 (focus keys land on their module); K13 the viewport of a near-square
// foldable, undo / redo in the header of touch tablets; K14 timeline names with "…", a short bar's label left near the
// end; K21 the tour's first card; the bell's dropdown is resizable (grip + keys, per device) and the phone sheet's
// handle; SW v74.
// Then Firefox headless (WebDriver BiDi, skipped without firefox), touch at 360 x 780 / 390 x 844 / 904 x 1080 (Fold
// inside), a mouse at 1280 x 800 / 1920 x 1080: header ("…" + bell in view), rows of a narrow list column in two lines
// (container query), the date popover inside the viewport with touch targets >= 44 px, the time sum, the timeline labels,
// dragging the bell's grip (desktop) and the sheet's handle (phone); screenshots with P270_SHOTS=<dir>.
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const WS = globalThis.WebSocket || require('ws');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const task = async id => (await call('GET', `/api/tasks/${id}`));
const closeAll = w => { [...w.document.querySelectorAll('.modal')].forEach(m => m.remove()); w.eval('popOnClose = null; closePop()'); };

const firefox = require('./ff')({tag: 'p270_ui', check, shots: 'P270_SHOTS'});  // 2.7.2: the shared Firefox helper (with the start retry)
const HEAD = `(() => {
  const t = document.querySelector('#top'); if (!t || !t.querySelector('h1')) return {none: location.href};
  const vw = document.documentElement.clientWidth;
  const R = e => { if (!e || !e.offsetWidth) return null; const b = e.getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom, b.width, b.height]; };
  const out = [...t.children].filter(e => e.offsetWidth && e.getBoundingClientRect().right > vw + 0.5).map(e => e.className || e.tagName);
  return {vw, more: R(t.querySelector('[data-act="top-more"]')), bell: R(t.querySelector('.bell')), out, ht: R(t.querySelector('h1 .ht'))};
})()`;
// every visible button / control in a container that is smaller than 44 x 44 px (touch), counting ::before / ::after zones
const SMALL = sel => `(() => [...document.querySelectorAll('${sel}')].filter(e => e.offsetWidth && getComputedStyle(e).visibility !== 'hidden').map(e => {
  const b = e.getBoundingClientRect(); let w = b.width, h = b.height;
  for (const ps of ['::before', '::after']) { const s = getComputedStyle(e, ps); if (s.content && s.content !== 'none' && s.position === 'absolute') { const iw = b.width - parseFloat(s.left || 0) - parseFloat(s.right || 0), ih = b.height - parseFloat(s.top || 0) - parseFloat(s.bottom || 0); if (Number.isFinite(iw)) w = Math.max(w, iw); if (Number.isFinite(ih)) h = Math.max(h, ih); } }
  return [e.className || e.tagName, (e.textContent || '').trim().slice(0, 16), Math.round(w), Math.round(h)]; }).filter(x => x[2] < 43.5 || x[3] < 43.5))()`;

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:7[4-9]|8[0-9]|9[0-9])'/.test(SW), 'service worker cache v74 (2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
  check(/action === 'nagoff'/.test(SW) && /maxActions/.test(SW), 'SW: "Stop reminding" in the background, as many buttons as the platform shows');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL.replace(',agents', ''), lang: 'en', tour: 'done'}, CKB);
  const L = (await call('POST', '/api/lists', {name: 'Taxes'})).id;
  const D1 = (await call('POST', '/api/tasks', {title: 'Tax return', list_id: L, due: day(10), reminders: '20160', deadline: 2})).id;
  const D2 = (await call('POST', '/api/tasks', {title: 'Renew passport', list_id: L, due: day(30), reminders: '1440', deadline: 1})).id;
  const D3 = (await call('POST', '/api/tasks', {title: 'Water plants', list_id: L, due: day(3)})).id;
  const P = (await call('POST', '/api/lists', {name: 'Client X', ptype: 'agency', folder: 'Clients'})).id;
  const st0 = await call('GET', '/api/state');
  const fb = st0.fields.find(f => f.list_id === P && f.name === 'Budget h');
  const PT = (await call('POST', '/api/tasks', {title: 'Concept', list_id: P, fields: {[fb.id]: '20'}, due: day(2)})).id;
  await call('POST', '/api/time/entries', {task_id: PT, start: new Date(Date.now() - 6 * 3600e3).toISOString(), minutes: 180});
  const TL1 = (await call('POST', '/api/tasks', {title: 'Final delivery to the client and invoice', list_id: P, start: day(67), due: day(68)})).id;

  // ================= #412 deadlines in the rows, on Today
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  check(row(D1) && !row(D2), 'Today: a deadline (on Today) from its first reminder on (2 weeks before, due in 10 days); not the other one');
  check(row(D1)?.querySelector('.dlc.hot') && /10 days left/.test(row(D1).querySelector('.dlc').textContent), 'row: "10 days left", highlighted: ' + row(D1)?.querySelector('.dlc')?.textContent);
  check(w.eval('counts().today') === 1, 'sidebar count of Today includes it');
  w.eval(`go('l/${L}')`); await sleep(400);
  check(row(D2)?.querySelector('.dlc') && !row(D2).querySelector('.dlc.hot') && /30 days left/.test(row(D2).querySelector('.dlc').textContent), 'list: "30 days left", not highlighted before its first reminder');
  check(!row(D3)?.querySelector('.dlc'), 'a plain due date: no countdown');
  // ================= #412 / #413 the date popover
  w.eval(`datePop(document.querySelector('#top h1'), ${D2})`); await sleep(150);
  let pop = d.querySelector('#pop');
  const chips = [...pop.querySelectorAll('.remchips [data-rem]')].map(b => b.dataset.rem);
  check(['0', '15', '60', '1440', '10080', '20160', '43200'].every(v => chips.includes(v)), 'popover chips incl. 2 weeks + 1 month: ' + chips);
  check(/2 weeks/.test(pop.querySelector('[data-rem="20160"]').textContent) && /1 month/.test(pop.querySelector('[data-rem="43200"]').textContent), 'chip labels');
  click(w, pop.querySelector('[data-q="remc"]')); await sleep(50);
  check(pop.querySelector('#p-remn') && pop.querySelector('#p-remu') && pop.querySelector('[data-q="remadd"]'), '"Other…": number + unit + Add');
  pop.querySelector('#p-remn').value = '3'; change(w, pop.querySelector('#p-remn'));
  pop.querySelector('#p-remu').value = '10080'; change(w, pop.querySelector('#p-remu'));
  click(w, pop.querySelector('[data-q="remadd"]')); await sleep(50);
  check(pop.querySelector('[data-rem="30240"].on') && /3 weeks/.test(pop.querySelector('[data-rem="30240"]').textContent), 'own reminder: 3 weeks before, shown as a chip');
  click(w, pop.querySelector('[data-q="remc"]')); await sleep(50);
  pop.querySelector('#p-remn').value = '400'; pop.querySelector('#p-remu').value = '1440';
  click(w, pop.querySelector('[data-q="remadd"]')); await sleep(50);
  check(/at most a year/.test(d.querySelector('#toast').textContent) && !pop.querySelector('[data-rem="576000"]'), 'more than a year: refused');
  const dl = pop.querySelector('#p-dl');
  check(dl && dl.checked && !pop.querySelector('#p-dlt').checked, 'Deadline ticked, "On Today" not');
  pop.querySelector('#p-dlt').checked = true; change(w, pop.querySelector('#p-dlt')); await sleep(50);
  const ns = pop.querySelector('#p-nag');
  check(ns && [...ns.options].map(o => o.value).join() === ',off,5,10,15,30,60,1d' && /as the list \(Off\)/.test(ns.options[0].textContent), 'Repeat reminder: list default + off + intervals: ' + [...ns.options].map(o => o.textContent).join('|'));
  ns.value = '15'; change(w, ns); await sleep(900);
  let t2 = await task(D2);
  check(t2.reminders.split(',').includes('30240') && t2.deadline === 2 && t2.nag === '15', `saved at once: ${t2.reminders} deadline ${t2.deadline} nag ${t2.nag}`);
  click(w, d.querySelector('#pop [data-q="done"]')); await sleep(300);
  check(row(D2)?.querySelector('.nagm') && /every 15 min/.test(row(D2).querySelector('.nagm').title), 'row: bell + repeat mark with its interval');
  w.eval(`openDetail(${D2})`); await sleep(300);
  const ddl = d.querySelector('#detail .ddl');
  check(ddl && /days left/.test(ddl.textContent) && /Repeat reminder: every 15 min/.test(ddl.textContent), 'task panel: countdown + repeat line: ' + ddl?.textContent);
  w.eval('closeDetail()');
  // the push button "Stop reminding" (no service worker / session): the app at #nagoff/<id>
  w.location.hash = '#nagoff/' + D2; await sleep(900);
  check((await task(D2)).nag === 'off' && /No more repeated reminders/.test(d.querySelector('#toast').textContent), '#nagoff: switched off + toast');
  // ================= #413 settings + the list default
  w.eval(`settingsModal('notify')`); await sleep(500);
  let md = d.querySelector('.smodal');
  check(md.querySelector('#s-qfrom') && md.querySelector('#s-qto') && md.querySelector('#s-qfrom').value === '22:00' && md.querySelector('#s-qto').value === '07:00', 'quiet hours from / until (22:00 - 07:00)');
  const nm = md.querySelector('[data-nm="nag"][data-ch="push"]');
  check(nm && nm.checked && !md.querySelector('[data-nm="nag"][data-ch="news"]'), 'matrix: "Repeated reminders", push only');
  check([...md.querySelectorAll('#s-defrem option')].some(o => o.value === '20160') && [...md.querySelectorAll('#s-defrem option')].some(o => o.value === '43200'), 'default reminder: 2 weeks + 1 month');
  closeAll(w);
  w.eval(`listModal(${L})`); await sleep(400);
  md = d.querySelector('.lmodal');
  const ln = md.querySelector('#l-nag');
  check(ln && ln.value === '', 'list dialog: Repeat reminders (off)');
  ln.value = '1d'; change(w, ln); await sleep(900);
  check((await call('GET', '/api/state')).lists.find(l => l.id === L).nag === '1d', 'list default saved: daily');
  // #414 (2.7.2): the type is gone; "Show completed at the bottom" with the cart hint instead
  const ks = md.querySelector('#l-kind');
  check([...ks.options].map(o => o.textContent).join('|') === 'List|Project', 'types: List|Project (2.7.2): ' + [...ks.options].map(o => o.textContent).join('|'));
  const dab = md.querySelector('#l-dab');
  dab.checked = true; change(w, dab); await sleep(900);
  check(/comes back with one tap/.test(md.textContent) && md.querySelector('.ldabrow'), 'the option with its hint');
  check((await call('GET', '/api/state')).lists.find(l => l.id === L).checklist === 1, 'stored as the option, kind list');
  closeAll(w);
  check(w.eval(`topMoreItems()`).some(x => x.label === 'Show completed at the bottom' && x.icon === 'cart'), '"…": the option with the cart');
  await call('PATCH', `/api/lists/${L}`, {checklist: false});
  await call('PATCH', `/api/lists/${L}`, {kind: 'list'});
  // ================= #407 the time sum
  await w.eval('load().then(render)'); w.eval(`go('l/${P}')`); await sleep(500);
  const ts = d.querySelector('#view .lhead .tsum');
  check(ts && /3 h/.test(ts.textContent) && /0\.4 days/.test(ts.textContent) && ts.querySelector('.tbud i') && /3\/20 h/.test(ts.querySelector('.tbn').textContent), 'list header: 3 h · 0.4 days, budget 3/20 h: ' + ts?.textContent);
  check(/at 8 h per day/.test(ts.title) && /Budget: 20 h/.test(ts.title), 'tooltip: day length + budget: ' + ts?.title);
  w.eval(`listModal(${P})`); await sleep(400);
  md = d.querySelector('.lmodal');
  const dh = md.querySelector('#l-dayh');
  check(dh && dh.placeholder === '8', 'list dialog: hours per day (empty = the server\'s 8)');
  dh.value = '6'; dh.dispatchEvent(new w.Event('input', {bubbles: true})); dh.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true})); await sleep(1300);
  check((await call('GET', '/api/state')).lists.find(l => l.id === P).day_hours === 6, 'list: 6 h per day saved');
  closeAll(w); await w.eval('load().then(render)'); await sleep(300);
  check(/0\.5 days/.test(d.querySelector('#view .lhead .tsum')?.textContent || ''), 'with 6 h per day: 0.5 days');
  w.eval(`go('folder/Clients')`); await sleep(500);
  check(/3 h/.test(d.querySelector('#view .lhead.fhd .tsum')?.textContent || ''), 'folder view: the sum of its project lists');
  // Administration: hours per day for the server
  w.eval(`settingsModal('users')`); await sleep(500);
  const sdh = d.querySelector('.smodal #s-dayh');
  check(sdh && sdh.value === '8', 'Administration: hours per day (8)');
  sdh.value = '7,5'; change(w, sdh); await sleep(700);
  check((await call('GET', '/api/state')).time_day_h === 7.5, 'server value 7.5 saved');
  closeAll(w);
  // ================= #405 S items
  w.eval(`settingsModal('account')`); await sleep(400);
  md = d.querySelector('.smodal');
  check(md.querySelector('[data-pane="account"] [data-m="go-share"]') && !md.querySelector('[data-acc="token"]'), 'S3: Account links to Share from your phone, no token there');
  click(w, md.querySelector('[data-m="go-share"]')); await sleep(200);
  check(md.querySelector('.snav [data-sec="integr"]').classList.contains('on'), 'S3: the link opens Integrations');
  check(!md.querySelector('[data-pane="data"] [data-m="purge"]') && !/Delete all completed/.test(md.querySelector('[data-pane="data"]').textContent), 'S4: no "Delete all completed" in Data');
  check(md.querySelector('.snav [data-sec="ai"]') && md.querySelector('[data-aisub="agents"]').textContent.trim() === 'Status', 'S2/S5: Agents with the module on; first sub-tab "Status"');
  closeAll(w);
  w.eval(`settingsModal('focus')`); await sleep(300);
  md = d.querySelector('.smodal');
  check(md.querySelector('.snav [data-sec="modules"]').classList.contains('on') && md.querySelector('[data-modrow="pomo"] details.mopt').open, 'S8: settingsModal(\'focus\') opens the focus options in Modules');
  closeAll(w);
  check(w.eval(`tabItem('time')`)?.label === 'Time tracking', 'S5: the tab is called "Time tracking" (was "Time")');
  check(!/opens on it/.test(w.eval('tourSteps()')[0].d), 'K21: the tour no longer says the app opens on the Inbox');
  // K14: names with "…", the label of a short bar near the end goes to its left
  check(/lbl-l/.test(w.eval(`tlBarHtml(S.tasks.get(${TL1}), today(), addDays(today(), TL_DAYS - 1), 24, null, false)`)), 'K14: a short bar at the end of the range: label on its left');
  check(!/lbl-l/.test(w.eval(`tlBarHtml(S.tasks.get(${PT}), today(), addDays(today(), TL_DAYS - 1), 24, null, false)`)), 'K14: a short bar with room: label on its right');
  // K13: a near-square touch screen keeps the tablet layout in both orientations
  const vp = (sw, sh, land, coarse = true) => w.eval(`(() => { Object.defineProperty(screen, 'width', {configurable: true, value: ${sw}}); Object.defineProperty(screen, 'height', {configurable: true, value: ${sh}});
    const mm = window.matchMedia; window.matchMedia = q => ({matches: /orientation: landscape/.test(q) ? ${land} : /pointer:coarse/.test(q) ? ${coarse} : false, addEventListener() {}, addListener() {}});
    stableViewport(); window.matchMedia = mm; return document.querySelector('meta[name="viewport"]').getAttribute('content'); })()`);
  check(/^width=900/.test(vp(884, 1060, false)), 'K13: unfolded Fold in portrait (884 px): layout width 900');
  check(/device-width/.test(vp(1060, 884, true)), 'K13: ... in landscape (1060 px): its own width');
  check(/device-width/.test(vp(390, 844, false)), 'K13: a phone keeps device-width');
  check(/device-width/.test(vp(820, 1180, false)), 'K13: a portrait tablet (iPad) keeps device-width');
  check(/device-width/.test(vp(884, 1060, false, false)), 'K13: a mouse screen is never scaled');
  // the bell's dropdown: grip + keys, kept per device
  w.eval(`bellPop(document.querySelector('#top .bell'))`); await sleep(400);
  const grip = d.querySelector('#pop .bpgrip');
  check(grip && /Resize/.test(grip.getAttribute('aria-label')), 'bell dropdown: a resize grip');
  const bh = d.querySelector('#pop .bphl[data-bp="news"]');
  check(bh && /News/.test(bh.textContent) && bh.querySelector('.bpchev')?.textContent === '›', 'bell dropdown: the heading "News" is a link with a chevron');
  key(w, grip, 'ArrowLeft'); key(w, grip, 'ArrowDown', {shiftKey: true});
  const bs = JSON.parse(w.__store['tasks.bellSize'] || 'null');
  check(bs && bs.w > 0 && bs.h > 0, 'keys resize it, stored per device: ' + JSON.stringify(bs));
  click(w, bh); await sleep(300);
  check(w.eval('S.route.mod') === 'news' && d.querySelector('#pop').classList.contains('hidden'), 'the heading opens the News view');
  w.eval(`go('today')`); await sleep(300);
  check(!d.querySelector('#pop').classList.contains('bellpop') && !d.querySelector('#pop').style.width, 'closed: nothing of it stays on the popover');
  w.close();
  w = await boot({user: 'alice', hash: 'today', mobile: true}); d = w.document;
  w.eval(`bellPop(document.querySelector('#top .bell'))`); await sleep(400);
  const grab = d.querySelector('#pop .bpgrab');
  check(grab && !d.querySelector('#pop .bpgrip'), 'phone: the sheet has a handle (no corner grip)');
  key(w, grab, 'Enter');
  check(+(w.__store['tasks.bellSheetH'] || 0) > 0 && d.querySelector('#pop .bpop').style.height, 'phone: Enter on the handle = full height, kept');
  w.close();
  // S2: no Agents page without the module (no agents yet)
  await call('PATCH', '/api/settings', {features: ALL.replace(',agents', '')});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(400);
  check(!d.querySelector('.smodal .snav [data-sec="ai"]') && !d.querySelector('.smodal [data-pane="ai"]'), 'S2: admin without agents, module off: no Agents page');
  check(!w.eval(`palAll().some(x => x.id === 's:ai')`), 'S2: not in the palette either');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});
  // German renames (S5) + 2.7.0 strings
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(w.eval(`tr('Completed tasks')`) === 'Erledigte Aufgaben' && w.eval(`tr('Ownership…')`) === 'Eigentümer…' && w.eval(`tr('Show completed at the bottom')`) === 'Erledigte unten zeigen', 'German: Erledigte Aufgaben, Eigentümer…, Erledigte unten zeigen');
  check(/noch 30 Tage/.test(row(D2)?.querySelector('.dlc')?.textContent || ''), 'German: "noch 30 Tage"');
  w.eval(`datePop(document.querySelector('#top h1'), ${D2})`); await sleep(150);
  check(/Nachhaken/.test(d.querySelector('#pop').textContent) && /2 Wochen/.test(d.querySelector('#pop [data-rem="20160"]').textContent), 'German popover: Nachhaken, 2 Wochen');
  w.eval('popOnClose = null; closePop()');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});
  // K13: undo / redo in the header of a touch tablet with room
  w = await boot({user: 'alice', hash: 'l/' + L, media: {'(hover: none)': true}}); d = w.document;
  check(d.querySelector('#top [data-act="hist-undo"]') && !w.eval('topMoreItems()').some(x => x.icon === 'undo'), 'touch tablet: ← → in the header, not in "…"');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true}); d = w.document;
  check(!d.querySelector('#top [data-act="hist-undo"]') && w.eval('topMoreItems()').some(x => x.icon === 'undo'), 'phone: ← → in "…"');
  w.close();
  if (errs.length) { check(false, 'JS errors: ' + [...new Set(errs)].join(' | ')); }

  // ================= Firefox: layout at 360 / 390 / 904 touch, 1280 / 1920 mouse
  await call('PATCH', `/api/lists/${L}`, {nag: ''});
  await call('PATCH', `/api/tasks/${D2}`, {nag: '30'});
  for (const touch of [true, false]) {
    await firefox(async ({cmd, ev, nav, ctx, shot, drag}) => {
      await nav(B + 'static/icon.svg');
      const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      check(lgi === 200, 'Firefox: login');
      let nr = 0;
      const open = async hash => { await nav(B + 'static/icon.svg'); await nav(B + '?v=' + (++nr) + '#' + hash); for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(900); };
      for (const [vw, vh] of touch ? [[360, 780], [390, 844], [904, 1080]] : [[1280, 800], [1920, 1080]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        // the header + rows of Today (date / list columns on wide screens)
        await open('today');
        const hd = await ev(HEAD);
        check(hd.more && hd.bell && hd.more[1] <= vw + .5 && hd.bell[1] <= vw + .5 && !hd.out.length, `${vw}px: "…" and the bell in view ${JSON.stringify(hd)}`);
        const rows = await ev(`(() => { const r = document.querySelector('#view .trow.hascols') || document.querySelector('#view .trow'); if (!r) return null; const c = r.querySelector('.tcols'), m = r.querySelector('.meta .m-col'), t = r.querySelector('.ttl');
          return {cols: !!c && getComputedStyle(c).display !== 'none', meta: !!m && getComputedStyle(m).display !== 'none', tw: Math.round(t.getBoundingClientRect().width), lw: Math.round(document.querySelector('.lwrap').getBoundingClientRect().width), dl: !!r.querySelector('.dlc')}; })()`);
        if (vw >= 1900) check(rows && rows.cols && !rows.meta, `${vw}px: wide list: columns on the right ${JSON.stringify(rows)}`);
        if (vw === 904) check(rows && !rows.cols && rows.meta && rows.tw > 300, `Fold inside (904): the rows in two lines (container ${rows?.lw}px), the title gets room ${JSON.stringify(rows)}`);
        if (vw < 900) check(rows && !rows.cols, `${vw}px: phone rows ${JSON.stringify(rows)}`);
        await shot(`p270-today-${vw}.png`);
        // the date popover with the new rows
        await ev(`datePop(document.querySelector('#top h1'), ${D2}); 1`); await sleep(400);
        const dp = await ev(`(() => { const p = document.querySelector('#pop'); const r = p.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom, iw: innerWidth, ih: innerHeight, sh: p.scrollHeight, ch: p.clientHeight, nag: !!p.querySelector('#p-nag'), dl: !!p.querySelector('#p-dl')}; })()`);
        check(dp.nag && dp.dl && dp.l >= -0.5 && dp.r <= dp.iw + .5 && dp.b <= dp.ih + .5, `${vw}px: date popover inside the viewport with Deadline + Repeat reminder ${JSON.stringify(dp)}`);
        if (touch && vw < 900) {
          const small = await ev(SMALL('#pop .remchips button, #pop .pdl .chkl, #pop #p-nag'));
          check(!small.length, `${vw}px: popover targets >= 44 px: ${JSON.stringify(small)}`);
        }
        await shot(`p270-date-${vw}.png`);
        await ev(`(() => { popOnClose = null; closePop(); return 1; })()`);
        // the project list: time sum in its header
        await open('l/' + P);
        const tsum = await ev(`(() => { const s = document.querySelector('#view .lhead .tsum'); if (!s) return null; const r = s.getBoundingClientRect(); return {txt: s.textContent, r: r.right, l: r.left, vw: document.documentElement.clientWidth}; })()`);
        check(tsum && /h/.test(tsum.txt) && tsum.r <= tsum.vw + .5 && tsum.l >= 0, `${vw}px: time sum in the header, in view ${JSON.stringify(tsum)}`);
        await shot(`p270-proj-${vw}.png`);
        // the timeline of the project: names cut with "…", labels never over the name column
        await ev(`(async () => { await api('PATCH', '/api/lists/${P}', {view: 'timeline'}); await load(); render(); return 1; })()`); await sleep(700);
        const tl = await ev(`(() => { const n = [...document.querySelectorAll('.tl-row:not(.tl-headrow) .tl-name .tln')]; const lab = [...document.querySelectorAll('.tl-bar.short span')];
          const nameR = document.querySelector('.tl-row:not(.tl-headrow) .tl-name')?.getBoundingClientRect().right || 0;
          const d = document.querySelector('.tl-d span');
          return {names: n.length, ell: n.every(e => getComputedStyle(e).textOverflow === 'ellipsis'), over: lab.filter(s => { const r = s.getBoundingClientRect(); return r.width && r.left < nameR - 1 && getComputedStyle(s).visibility !== 'hidden' && document.elementFromPoint(r.left + 2, r.top + r.height / 2) === s; }).length, wd: d ? getComputedStyle(d).opacity : null}; })()`);
        check(tl.names >= 2 && tl.ell && !tl.over && tl.wd === '1', `${vw}px: timeline names with "…", no label over the names, weekdays readable ${JSON.stringify(tl)}`);
        await shot(`p270-timeline-${vw}.png`);
        // scrolled so that the short bar and its label pass under the name column: the names stay on top, readable
        const tl2 = await ev(`(async () => { const sc = document.querySelector('.tl-scroll'), b = document.querySelector('.tl-bar[data-id="${PT}"]'), nm = document.querySelector('.tl-row:not(.tl-headrow) .tl-name');
          sc.scrollLeft = b.offsetLeft - 4; await new Promise(r => setTimeout(r, 150));
          const sp = b.querySelector('span'), r = sp.getBoundingClientRect(), nr = nm.getBoundingClientRect(), row = b.closest('.tl-row').querySelector('.tl-name');
          const hit = document.elementFromPoint(Math.min(nr.right - 6, Math.max(nr.left + 4, r.left + 4)), r.top + r.height / 2);
          return {under: r.left < nr.right, name: !!hit && !!hit.closest('.tl-name'), rowName: row.textContent}; })()`);
        check(!tl2.under || tl2.name, `${vw}px: a label scrolled under the name column is covered by it ${JSON.stringify(tl2)}`);
        await shot(`p270-timeline-scrolled-${vw}.png`);
        await ev(`(async () => { await api('PATCH', '/api/lists/${P}', {view: 'list'}); await load(); render(); return 1; })()`);
        // the bell: drag the grip (desktop) / the handle (phone)
        if (vw === 904) continue;
        await open('today');
        await ev(`localStorage.removeItem('tasks.bellSize'); localStorage.removeItem('tasks.bellSheetH'); document.querySelector('#top .bell').click(); 1`); await sleep(1000);
        if (!touch) {
          const b0 = await ev(`(() => { const p = document.querySelector('#pop'), g = p.querySelector('.bpgrip').getBoundingClientRect(), r = p.getBoundingClientRect(); return {gx: g.left + g.width / 2, gy: g.top + g.height / 2, w: r.width, h: r.height, r: r.right}; })()`);
          await drag(b0.gx, b0.gy, -120, 140); await sleep(300);
          const b1 = await ev(`(() => { const r = document.querySelector('#pop').getBoundingClientRect(); return {w: r.width, h: r.height, r: r.right, st: localStorage.getItem('tasks.bellSize')}; })()`);
          check(b1.w > b0.w + 100 && b1.h > b0.h + 100 && Math.abs(b1.r - b0.r) < 2 && b1.st, `${vw}px: dragging the grip makes it wider + taller, the right edge stays, stored ${JSON.stringify([b0, b1])}`);
          await ev(`closePop(); document.querySelector('#top .bell').click(); 1`); await sleep(800);
          const b2 = await ev(`(() => { const r = document.querySelector('#pop').getBoundingClientRect(); return {w: r.width, h: r.height}; })()`);
          check(Math.abs(b2.w - b1.w) < 2 && Math.abs(b2.h - b1.h) < 2, `${vw}px: reopened with the same size ${JSON.stringify(b2)}`);
          await ev(`localStorage.removeItem('tasks.bellSize'); closePop(); 1`);
        } else {
          const s0 = await ev(`(() => { const p = document.querySelector('#pop'), g = p.querySelector('.bpgrab').getBoundingClientRect(), r = p.getBoundingClientRect(); return {gx: g.left + g.width / 2, gy: g.top + g.height / 2, h: r.height, gw: g.width, gh: g.height, ih: innerHeight}; })()`);
          check(s0.gh >= 43.5, `${vw}px: the sheet's handle is >= 44 px high ${JSON.stringify(s0)}`);
          await drag(s0.gx, s0.gy, 0, -(s0.gy - 4), 'touch'); await sleep(300);
          const s1 = await ev(`(() => { const r = document.querySelector('#pop').getBoundingClientRect(), f = document.querySelector('#pop .bpfoot').getBoundingClientRect(); return {h: r.height, t: r.top, l: r.left, w: r.width, iw: document.documentElement.clientWidth, ih: innerHeight, fb: f.bottom, st: localStorage.getItem('tasks.bellSheetH')}; })()`);
          check(s1.h > s0.h + 100 && s1.t <= 12 && s1.st, `${vw}px: the handle drags the sheet up to the full height ${JSON.stringify([s0, s1])}`);
          check(Math.abs(s1.l) < 1 && s1.w >= s1.iw - 1 && s1.fb >= s1.ih - 60, `${vw}px: the full sheet spans the width, its foot at the bottom ${JSON.stringify(s1)}`);
          await shot(`p270-bell-full-${vw}.png`);
          await ev(`localStorage.removeItem('tasks.bellSheetH'); closePop(); 1`);
        }
      }
    }, touch);
  }

  console.log(`p270_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
