// 2.18.0 UI tests (#430 milestones as tasks, "Software 2" B / D), own container (start.sh, isolated test database).
// jsdom: creating a milestone (quick add "!milestone", the task panel switch, the task menu), the diamond in list rows,
// Kanban cards, calendar month / week / day chips and the agenda, checking it off; the "Milestone" field of a task and the
// bulk action "Set milestone"; the milestone's panel (progress bar, its tasks, burndown with a text + table alternative,
// release notes + Copy); the overview block (opens the milestone task); undated milestones; screen reader names.
// Firefox at 390 touch (real taps) and 1440 mouse, light + dark: layout (nothing sideways), 44 px targets, the diamond
// really is a rotated square, axe on the milestone panel. Screenshots with P2180_MS_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2180_ms_ui', check, shots: 'P2180_MS_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const state = async () => (await call('GET', '/api/state'));
const task = async id => (await state()).tasks.find(t => t.id === id);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'App', kind: 'project', tickets: 1})).id;
  const LK = (await call('POST', '/api/lists', {name: 'Board', kind: 'project', view: 'kanban'})).id;
  const MS = (await call('POST', '/api/tasks', {title: 'Release 1.0', list_id: L, ms: 1, due: day(3)})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Sign-in page', list_id: L, ttype: 'feature', milestone_id: MS})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Crash on start', list_id: L, ttype: 'bug', milestone_id: MS})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Write the docs', list_id: L})).id;
  const T4 = (await call('POST', '/api/tasks', {title: 'Polish icons', list_id: L})).id;
  await call('POST', `/api/tasks/${T1}/complete`);
  const KM = (await call('POST', '/api/tasks', {title: 'Board launch', list_id: LK, ms: 1, due: day(1)})).id;
  await call('POST', '/api/tasks', {title: 'Board card', list_id: LK, due: day(1)});
  const MSN = (await call('POST', '/api/tasks', {title: 'Someday', list_id: L, ms: 1})).id;
  const TB = (await call('POST', '/api/tasks', {title: 'Login fails', list_id: L, ttype: 'bug'})).id;  // review: Bug chip contrast
  const CD = (await call('POST', '/api/tasks', {title: 'Done in the calendar', list_id: LK, due: day(0)})).id;
  await call('POST', `/api/tasks/${CD}/complete`);

  // ================= jsdom: the list
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  check(row(MS)?.querySelector('.chk.ms') && !row(T3)?.querySelector('.chk.ms'), 'list: the milestone has the diamond glyph, other tasks the circle');
  check(/Complete milestone: Release 1\.0/.test(row(MS).querySelector('.chk').getAttribute('aria-label')), 'list: screen readers hear "Complete milestone"');
  check(/Milestone/.test(row(MS).querySelector('.meta .msm')?.textContent || '') && row(MS).querySelector('.meta .msm.sr'), 'list: "Milestone" in the row description (visually hidden when dated)');
  check(/Milestone without a date/.test(row(MSN)?.querySelector('.meta .msm')?.textContent || '') && !row(MSN).querySelector('.meta .msm.sr'), 'list: an undated milestone says so visibly');
  check(row(T2)?.querySelector('.meta .mschip')?.textContent.includes('Release 1.0'), 'list: a task of a milestone shows it as a small chip');
  check(!row(T3).querySelector('.mschip'), '… a task without one shows none');
  // check it off
  click(w, row(MSN).querySelector('.chk'));
  check(await until(async () => (await task(MSN))?.status === 2), 'checking a milestone off completes it');
  await call('POST', `/api/tasks/${MSN}/reopen`);
  // quick add: !milestone
  w.eval(`(() => { const i = document.querySelector('#qinput'); i.focus(); i.value = 'Beta !milestone'; i.dispatchEvent(new Event('input', {bubbles: true})); updateChips(i); return 1; })()`);
  check(await until(() => [...d.querySelectorAll('.qchip')].some(c => c.dataset.qtype === 'ms' && /Milestone/.test(c.textContent))) || w.eval(`parseQuick('Beta !milestone').ms === 1`), 'quick add: "!milestone" is recognized (chip)');
  await w.eval(`submitQuick(document.querySelector('#qinput'))`); await sleep(600);
  const beta = (await state()).tasks.find(t => t.title === 'Beta');
  check(beta && beta.ms === 1 && beta.list_id === L, 'quick add creates the milestone');
  // the task panel: a normal task -> the Milestone field
  w.eval(`openDetail(${T3})`); await sleep(400);
  const sel = d.querySelector('#d-msel');
  check(sel && [...sel.options].map(o => o.textContent).some(x => x.startsWith('Release 1.0')) && sel.labels?.[0], 'panel: a field to choose the milestone, labelled');
  check(d.querySelector('#d-ms') && !d.querySelector('#d-ms').checked && d.querySelector('#d-ms').labels.length, 'panel: the "This task is a milestone" switch (project list), labelled');
  sel.value = String(MS); change(w, sel);
  check(await until(async () => (await task(T3))?.milestone_id === MS), 'panel: choosing the milestone saves it');
  // the switch makes a task a milestone and back
  w.eval(`openDetail(${T4})`); await sleep(400);
  const sw = d.querySelector('#d-ms'); sw.checked = true; change(w, sw);
  check(await until(async () => (await task(T4))?.ms === 1), 'panel: the switch makes it a milestone');
  await sleep(300);
  check(d.querySelector('#detail .dtop .chk.ms') && !d.querySelector('#detail .subsec'), 'panel: diamond in the header, no subtasks section');
  const sw2 = d.querySelector('#d-ms'); sw2.checked = false; change(w, sw2);
  check(await until(async () => !(await task(T4))?.ms), '… and back to a normal task');
  w.eval('closeDetail()');
  // bulk action: Set milestone
  // 2.26.0 (#936): the milestone of a selection is set in the multi panel
  w.eval(`S.multi = new Set([${T4}, ${T3}]); renderMultiBar()`); await sleep(200);
  const mb = d.querySelector('#detail.multi [data-act="me-f"][data-f="milestone"]');
  check(mb && /Milestone/.test(mb.getAttribute('aria-label')), 'multi-select: the milestone field in the multi panel');
  click(w, mb); await sleep(300);
  const item = [...d.querySelectorAll('#pop button, #pop [role=menuitem]')].find(b => b.textContent.includes('Release 1.0'));
  check(item, 'its menu lists the open milestones');
  check(item && item.textContent.includes(w.eval(`fmtDateLoc('${day(3)}')`)) && !item.textContent.includes(w.eval(`fmtDate('${day(3)}')`)), 'review: the menu shows the date in the app\'s format ' + item?.textContent);
  if (item) click(w, item);
  check(await until(async () => (await task(T4))?.milestone_id === MS), 'bulk: the task joins the milestone');
  w.eval(`S.multi = new Set([${MS}, ${T3}]); renderMultiBar()`); await sleep(100);
  check(d.querySelector('#detail.multi') && !d.querySelector('#detail.multi [data-f="milestone"]'), 'no milestone field when a milestone itself is selected');
  w.eval(`S.multi.clear(); S.multiMode = false; renderMultiBar()`);
  // the milestone's panel
  w.eval(`openDetail(${MS})`);
  await until(() => d.querySelector('#d-ms .msburn'));
  const sec = d.querySelector('#d-ms');
  check(sec && sec.querySelector('h5')?.textContent === 'Milestone', 'milestone panel: its own section');
  const pb = sec.querySelector('[role=progressbar]');
  check(pb && pb.getAttribute('aria-valuenow') === '25' && /1 of 4 done/.test(sec.querySelector('.msnum').textContent), 'progress: a bar (25 %) and "1 of 4 done" ' + sec.querySelector('.msnum')?.textContent);
  const items = [...sec.querySelectorAll('.mstasks li')];
  check(items.length === 4 && items[items.length - 1].classList.contains('done') && /done/.test(items[items.length - 1].querySelector('.sr')?.textContent || ''), 'its tasks, open first, done ones marked for screen readers');
  const svg = sec.querySelector('svg.msburn');
  check(svg.getAttribute('role') === 'img' && /Burndown: 3 of 4 tasks open/.test(svg.getAttribute('aria-label')), 'burndown: an image with a summary ' + svg.getAttribute('aria-label'));
  check(sec.querySelector('.msbtab summary')?.textContent === 'Show as table' && sec.querySelectorAll('.msbtab tbody tr').length >= 1 && sec.querySelector('.msbtab th[scope=col]'), 'burndown: a table alternative');
  check(svg.querySelector('.msb-ideal') && svg.querySelector('.msb-act'), 'burndown: ideal + actual line');
  const rn = sec.querySelector('.msrn');
  check(rn && /Features/.test(rn.textContent) && /Sign-in page/.test(rn.textContent) && !/Crash on start/.test(rn.textContent), 'release notes: preview of the completed tasks');
  let copied = null;
  Object.defineProperty(w.navigator, 'clipboard', {value: {writeText: async t => { copied = t; }}, configurable: true});
  click(w, sec.querySelector('[data-act="ms-copy"]')); await sleep(200);
  check(copied && copied.startsWith('## Release 1.0') && copied.includes(`- #${T1} Sign-in page`), 'Copy puts the Markdown on the clipboard');
  check(sec.querySelector('[data-act="ms-copy"]').getAttribute('aria-label') === 'Copy release notes', 'review: Copy is named "Copy release notes"');
  check(w.eval('S.msr.j.burndown.days.length') >= 2 || /Not enough history yet/.test(sec.querySelector('.msbnone')?.textContent || ''), 'R9: a fresh milestone (one day) says "Not enough history yet"');
  // completing a task of it refreshes the section
  await call('POST', `/api/tasks/${T2}/complete`); await w.eval('load().then(() => { render(); renderDetail(); })'); await sleep(300); w.eval('renderDetail()');
  check(await until(() => /2 of 4 done/.test(d.querySelector('#d-ms .msnum')?.textContent || '')), 'the section follows changes of its tasks');
  // a task of the milestone opens from the section
  click(w, [...d.querySelectorAll('#d-ms [data-act="ms-open"]')].find(b => b.textContent.includes('Write the docs')));
  check(await until(() => w.eval('S.sel') === T3), 'a task of the milestone opens from the list');
  // the "…" menu
  w.eval(`taskMenu(document.body, ${T4})`); await sleep(200);
  check([...d.querySelectorAll('#pop button, #pop [role=menuitem]')].some(b => /Make it a milestone/.test(b.textContent)), 'task menu: "Make it a milestone"');
  w.eval('closePop(); closeDetail()');
  // activity line
  const tl = await call('GET', `/api/tasks/${T3}/timeline`);
  const ma = (tl.items || tl.activity || []).find(a => a.kind === 'milestone');
  check(ma && /added the task to the milestone/.test(w.eval(`actText(${JSON.stringify(ma)}, {})`) || ''), 'history: "… added the task to the milestone …"');
  w.close();

  // 2.18.0 review (R13): "All" timeline: the fold toggle and "Open list" are siblings (no button inside role=button)
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  const rmSeg = [...d.querySelectorAll('#top [data-act="rm-view"]')]; if (rmSeg[1]) rmSeg[1].click();
  await until(() => d.querySelector('.rm-g .rm-gname'));
  const gn = d.querySelector(`.rm-g[data-l="${L}"] .rm-gname`);
  check(gn && gn.getAttribute('role') === 'button' && !gn.querySelector('button, a, [role=button]') && gn.parentElement.querySelector(':scope > .rm-go')?.getAttribute('aria-label') === 'Open list',
    'R13: roadmap list row: toggle and "Open list" side by side, nothing nested');
  w.close();

  // ================= Kanban, calendar, overview
  w = await boot({user: 'alice', hash: 'l/' + LK}); d = w.document;
  check(d.querySelector(`.kcards .trow[data-id="${KM}"] .chk.ms`), 'Kanban: the card of a milestone has the diamond');
  w.close();
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}); d = w.document;
  const ev = d.querySelector(`.cal .ev[data-id="${KM}"]`);
  check(ev && ev.classList.contains('ms') && ev.querySelector('.msd') && /Milestone:/.test(ev.querySelector('.sr')?.textContent || ''), 'calendar month: a diamond chip, "Milestone:" for screen readers');
  w.eval(`S.calSel = '${day(1)}'; renderView()`); await sleep(200);
  check(d.querySelector(`.agenda .trow[data-id="${KM}"] .chk.ms`), 'calendar agenda: the diamond row');
  w.eval(`S.calMode = 'week'; S.calSel = '${day(1)}'; renderView()`); await sleep(200);
  check(d.querySelector(`.week .ev.ms[data-id="${KM}"] .msd`), 'calendar week: the diamond (all-day)');
  w.eval(`S.calMode = 'day'; renderView()`); await sleep(200);
  check(d.querySelector(`.week .ev.ms[data-id="${KM}"]`), 'calendar day: the diamond');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`setListView(listById(${L}), 'overview')`); await sleep(1200);
  const pm = [...d.querySelectorAll('.povm')];
  check(pm.length >= 3 && pm.some(x => /Release 1\.0/.test(x.textContent)) && pm.some(x => /Someday/.test(x.textContent) && /No date/.test(x.textContent)), 'overview: the milestone tasks, an undated one says "No date"');
  click(w, d.querySelector(`.povm [data-pov="ms-open"][data-id="${MS}"]`));
  check(await until(() => w.eval('S.sel') === MS), 'overview: the name opens the milestone task');
  check(w.eval(`(() => { const x = listById(${L}).milestones; return x.every(m => m.day) && x.some(m => m.id === ${MS}); })()`), 'l.milestones (timeline markers / next milestone) from the tasks, dated only');
  w.close();

  // ================= Firefox: layout, targets, the diamond, axe
  // contrast of el's text on the first opaque background from bgEl up, translucent layers composited (opacity included)
  const CR = `((el, bgEl) => { const P = c => { const n = (c.match(/[\\d.]+/g) || []).map(Number); return /^color\\(/.test(c) ? n.map((v, i) => i < 3 ? v * 255 : v) : n; }; const lum = c => { const m = c.slice(0, 3).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * m[0] + .7152 * m[1] + .0722 * m[2]; };
    const layers = []; for (let e = el; e; e = e.parentElement) { const b = P(getComputedStyle(e).backgroundColor); if (b.length >= 3) { const a = b.length > 3 ? b[3] : 1; if (a > 0) layers.push([b[0], b[1], b[2], a]); if (a >= 1) break; } }
    let bg = [255, 255, 255]; for (const l of layers.reverse()) bg = bg.map((v, i) => l[i] * l[3] + v * (1 - l[3]));
    let op = 1; for (let e = el; e; e = e.parentElement) op *= +getComputedStyle(e).opacity;
    const f = P(getComputedStyle(el).color), fa = (f.length > 3 ? f[3] : 1) * op, fg = bg.map((v, i) => f[i] * fa + v * (1 - fa));
    const a = lum(fg), b = lum(bg); return Math.round((Math.max(a, b) + .05) / (Math.min(a, b) + .05) * 100) / 100; })`;
  const AXE = (() => { try { return fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8'); } catch { return null; } })();
  const ffLogin = async ({ev, nav}, theme = 'light') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const OVER = `(() => ({o: document.documentElement.scrollWidth - innerWidth, v: document.querySelector('#view').scrollWidth - document.querySelector('#view').clientWidth}))()`;
  const SMALL = sel => `(() => { const out = []; for (const e of document.querySelectorAll(${JSON.stringify(sel)})) {
      const r = e.getBoundingClientRect(); if (!r.width || r.bottom < 0 || r.top > innerHeight) continue;
      let w = r.width, h = r.height; for (const p of ['::before', '::after']) { const ps = getComputedStyle(e, p); if (ps.content !== 'none' && ps.position === 'absolute') { w = Math.max(w, parseFloat(ps.width) || 0); h = Math.max(h, parseFloat(ps.height) || 0); } }
      if (w < 43.5 || h < 43.5) out.push((e.dataset.act || e.id || e.className || e.tagName) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)); } return out.slice(0, 8); })()`;
  const DIAMOND = id => `(() => { const c = document.querySelector('#view .trow[data-id="${id}"] .chk'); if (!c) return null; const t = getComputedStyle(c).transform; return {t, r: getComputedStyle(c).borderTopLeftRadius}; })()`;
  const tapper = ({cmd, ctx}) => async (x, y) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  const center = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; e.scrollIntoView({block: 'center'}); const q = e.getBoundingClientRect(); return {x: q.left + q.width / 2, y: q.top + q.height / 2}; })()`;
  const axe = async (ev, where) => {
    if (!AXE) return;
    if ((await ev('typeof axe')) === 'undefined') await ev(AXE + '\n;1');
    const r = await ev(`axe.run(document.querySelector('#detail'), {runOnly: {type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}, resultTypes: ['violations']})
      .then(r => r.violations.map(v => v.id + '(' + v.nodes.length + ') ' + v.nodes[0].target.join(' ')))`);
    check(!r.length, `${where}: no axe violations in the milestone panel: ` + r.join(' | ').slice(0, 500));
  };
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tap = tapper(o), tag = '390 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + L); await ready(ev);
    const x = await ev(OVER);
    check(x.o <= 0 && x.v <= 0, `${tag} list: nothing sideways ` + JSON.stringify(x));
    const dm = await ev(DIAMOND(MS));
    check(dm && /matrix/.test(dm.t) && dm.t !== 'none', `${tag}: the milestone glyph is rotated (a diamond) ` + JSON.stringify(dm));
    check(!(await ev(SMALL(`#view .trow[data-id="${MS}"] .chk`))).length, `${tag}: the diamond is a 44 px target`);
    check(await ev(`getComputedStyle(document.querySelector('#view .trow[data-id="${T3}"] .mschip') || document.body).display === 'none'`), `${tag}: no milestone chip on phones (calm rows)`);
    await shot(`p2180ms-${th}-390-list.png`);
    let p = await ev(center(`#view .trow[data-id="${MS}"] .ttl`)); await tap(p.x, p.y); await sleep(1500);
    check(await ev(`!!document.querySelector('#detail #d-ms .msprog')`), `${tag}: a tap opens the milestone panel`);
    await ev(`(() => { const s = document.querySelector('#d-ms'); s && s.scrollIntoView(); return 1; })()`); await sleep(300);
    const sm = await ev(SMALL('#d-ms button, #d-ms summary'));
    check(!sm.length, `${tag} panel: 44 px targets ` + JSON.stringify(sm));
    const pw = await ev(`(() => { const d = document.querySelector('#detail'); const s = document.querySelector('#d-ms .msburn').getBoundingClientRect(); return {o: d.scrollWidth - d.clientWidth, w: Math.round(s.width)}; })()`);
    check(pw.o <= 0 && pw.w > 200, `${tag} panel: nothing sideways, the burndown uses the width ` + JSON.stringify(pw));
    await shot(`p2180ms-${th}-390-panel.png`);
    await axe(ev, tag);
    await o.nav(B + '#cal'); await ready(ev);
    const cx = await ev(OVER);
    check(cx.o <= 0, `${tag} calendar: nothing sideways ` + JSON.stringify(cx));
  }, true);
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    check((await ev(OVER)).o <= 0, `${tag} list: nothing sideways`);
    const ch = await ev(`(() => { const c = document.querySelector('#view .trow[data-id="${T3}"] .mschip'); return c ? getComputedStyle(c).display : null; })()`);
    check(ch && ch !== 'none', `${tag}: the milestone chip shows on a wide screen`);
    check(!(await ev(SMALL(`#view .trow[data-id="${MS}"] .chk`).replace('43.5', '23.5').replace('43.5', '23.5'))).length, `${tag}: the diamond is a 24 px target`);
    await ev(`(() => { document.querySelector('#view .trow[data-id="${MS}"] .ttl').click(); return 1; })()`); await sleep(1500);
    check(await ev(`!!document.querySelector('#d-ms .msburn')`), `${tag}: the milestone panel with the burndown`);
    const st = await ev(`(() => { const a = document.querySelector('#d-ms .msb-act'); return a ? getComputedStyle(a).stroke : ''; })()`);
    check(st && st !== 'none', `${tag}: the burndown line is drawn in the accent ` + st);
    // 2.18.0 review: the bulk bar stays left of the open task panel (it covered the comment field)
    await ev(`(() => { S.multi = new Set([${T3}]); S.multiMode = true; renderMultiBar(); return 1; })()`); await sleep(300);
    const mb = await ev(`(() => { const b = document.querySelector('#mbar').getBoundingClientRect(), p = document.querySelector('#detail').getBoundingClientRect(); return {b: Math.round(b.right), p: Math.round(p.left), w: Math.round(b.width)}; })()`);
    check(mb.w > 0 && mb.b <= mb.p, `${tag}: the bulk bar does not cover the task panel ` + JSON.stringify(mb));
    await ev(`(() => { S.multi.clear(); S.multiMode = false; renderMultiBar(); return 1; })()`);
    await shot(`p2180ms-${th}-1440-panel.png`);
    await axe(ev, tag);
    // 2.18.0 review (R13): the Bug chip on a selected row >= 4.5:1
    const bc = await ev(`(() => { const r = document.querySelector('#view .trow[data-id="${TB}"]'); if (!r) return null; r.classList.add('sel'); const c = r.querySelector('.ttchip.tt-bug'); const v = ${CR}(c, r); r.classList.remove('sel'); return v; })()`);
    check(bc && bc >= 4.5, `${tag}: the Bug chip on a selected row: ` + bc);
    // the list name in rows (Trash, search) is cut with "…"
    const ls = await ev(`(() => { const m = document.createElement('div'); m.className = 'meta'; m.innerHTML = '<span class="lst">x</span>'; document.querySelector('#view').appendChild(m); const cs = getComputedStyle(m.firstChild); const r = [cs.display, cs.textOverflow]; m.remove(); return r.join(); })()`);
    check(/^(inline-)?block,ellipsis$/.test(ls || ''), `${tag}: list names in rows end with "…" when cut ` + ls);
    await o.nav(B + '#cal'); await ready(ev);
    check(await ev(`!!document.querySelector('.cal .ev.ms .msd')`), `${tag}: calendar month shows the diamond chip`);
    const dc = await ev(`(() => { const e = document.querySelector('.cal .ev.done'); return e ? ${CR}(e, e) : null; })()`);
    check(dc && dc >= 4.5, `${tag}: a completed calendar chip is readable (>= 4.5:1): ` + dc);
    await shot(`p2180ms-${th}-1440-cal.png`);
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
