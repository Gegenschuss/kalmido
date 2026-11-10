// 2.891.0 UI test, part D (#5440 empty / loading / error states from one block, #5439 task panel calmer): own container
// kalmido-suite: fresh
// (start.sh), jsdom + Firefox (desktop 1280 px mouse, phone 360 px touch). Invented data only. P2891D_NOSTART=1 = the container runs.
// freelancer-matrix: n/a (no new route; alice has no organisation, every check runs without one)
// - #5440: an empty project, the archive, the trash, Completed and an empty board say "nothing here" with the shared block
//   (symbol + sentence, a fixed minimum height); "+ Section" of an empty project sits right under the text and still asks for
//   the section; a filter without hits says a filter is active and "Change filter" opens it; a trash whose load fails says
//   so with "Try again" (not "Trash is empty."), and "Try again" loads it; errorState / noAccessState for the office and the
//   calendar
// - #5439: desktop 1280 opens the task with the newest comment in sight (history lines of others after it); phone 360: the
//   comments' text is in sight or one tap on "To the comments" away, the bar is one row and with the comment field takes at
//   most a third of the height, no gap under "Watch", Watch and the count are one element, no field "Projects" and no project
//   in the bar for a task in one project (the path on top names it); a reader sees no empty "Attachments"; "Loading…" of the
//   comments keeps its height when it turns into the first history line of a task without comments
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2891_d_ui', check, shots: 'P2891D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2891D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 75) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();
const day = n => new Date(Date.now() + n * 864e5).toISOString().slice(0, 10);

(async () => {
  check(await until(async () => (await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})}).catch(() => null))?.status < 500), 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'kanban,collab,comments'});  // the board needs Kanban
  const mk = async u => { await call(CA, 'POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: u + '@example.com'}); const c = await login(u); await call(c, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'}); return c; };
  const CC = await mk('carla'), CD = await mk('dora');
  const me = async ck => (await call(ck, 'GET', '/api/state')).me;
  const [UA, UC, UD] = [await me(CA), await me(CC), await me(CD)];
  check(!(UA.workspaces || []).length, 'alice: no organisation (freelancer)');
  const EMPTY = (await call(CA, 'POST', '/api/lists', {name: 'Harbour', kind: 'project'})).id;
  const BOARD = (await call(CA, 'POST', '/api/lists', {name: 'Storyboard', kind: 'project'})).id;
  const WORK = (await call(CA, 'POST', '/api/lists', {name: 'Workshop', kind: 'project'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Sand the boards', list_id: WORK});
  const FID = (await call(CA, 'POST', '/api/filters', {name: 'Harbour only', rules: {lists: [EMPTY]}})).id;
  check(EMPTY && BOARD && WORK && FID, 'set-up: three projects, one task, a filter');

  // ================= #5440 the block (jsdom)
  let w = await boot({user: 'alice', hash: `l/${EMPTY}`}), d = w.document;
  check(w.eval(`emptyState({icon: 'list', title: 'X', sub: 'Y'})`).includes('es-big') && w.eval(`emptyState({icon: 'list', title: 'X', size: 'row'})`).includes('es-row') && w.eval(`emptyState({bot: 'ruhig', title: 'X', size: 'sec'})`).includes('hempty'), '#5440: emptyState draws the three sizes');
  check(w.eval(`symEmpty('note', 'X', 'Y')`).includes('es-big') && w.eval(`botEmpty('ruhig', 'X')`).includes('es-big') && w.eval(`o3c_empty('X')`).includes('o3c-empty'), '#5440: symEmpty / botEmpty / o3c_empty are short forms of the block');
  check(/role="status"/.test(w.eval(`loadingHtml()`)) && /Loading…/.test(w.eval(`loadingHtml()`)) && /es-sec/.test(w.eval(`loadingHtml('sec')`)), '#5440: loadingHtml in the same sizes');
  check(/es-sec/.test(w.eval(`errorState({size: 'sec'})`)) && /Could not be loaded/.test(w.eval(`errorState()`)) && !/data-esretry/.test(w.eval(`errorState()`)), '#5440: errorState without a retry function has no button');
  check(/No access/.test(w.eval(`noAccessState()`)) && /enoacc/.test(w.eval(`noAccessState({size: 'row'})`)) && /es-row/.test(w.eval(`noAccessState({size: 'row'})`)), '#5440: noAccessState in the shared block');
  // an empty project: symbol + sentence + hint; "+ Section" right under the text, inside the block (and only once)
  let em = await until(() => d.querySelector('#view .empty.nempty.es-big'));
  check(em && /No tasks\./.test(txt(em)) && /Add the first one/.test(txt(em)) && em.querySelector('svg.i'), '#5440: empty project = the block with its sentence ' + txt(em));
  check(em?.querySelector('.eacts [data-act="section-new"]') && d.querySelectorAll('#view [data-act="section-new"]').length === 1, '#5440: "+ Section" sits in the empty state, once');
  em?.querySelector('[data-act="section-new"]')?.click();
  check(await until(() => /Name of the section/.test(txt(d.querySelector('.modal'))) && d.querySelector('.modal input')), '#5440: "+ Section" of the empty state still asks for the new section');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  // a filter without hits says so and leads to the filter
  w.eval(`go('f/${FID}')`);
  em = await until(() => d.querySelector('#view .empty.efilt'));
  check(em && /No tasks match the filter/.test(txt(em)) && /A filter is active: Harbour only/.test(txt(em)), '#5440: filter without hits: says a filter is active ' + txt(em));
  check(em && !/Add the first one/.test(txt(em)), '#5440: ... and does not ask to add a first task');
  const chg = em?.querySelector('[data-act="filter-edit"]');
  check(chg && /Change filter/.test(txt(chg)), '#5440: the button "Change filter"');
  chg?.click();
  const fm = await until(() => [...d.querySelectorAll('.modal')].find(m => /filter/i.test(txt(m.querySelector('h3'))) && m.querySelector('input')));
  check(fm, '#5440: "Change filter" opens the filter itself');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  // Archive, Trash, Completed: the shared block, no own markup with <br>
  for (const [k, re] of [['archived', /No archived projects\./], ['trash', /Trash is empty\./], ['done', /Nothing completed yet\./]]) {
    w.eval(`go('${k}')`);
    const e = await until(() => [...d.querySelectorAll('#view .empty.nempty.es-big')].find(x => re.test(txt(x))));
    check(e && e.querySelector('svg.i') && !e.querySelector('br'), `#5440: ${k}: the block with symbol and sentence ` + txt(d.querySelector('#view')).slice(0, 80));
  }
  // a trash whose load fails says so, "Try again" loads it (it said "Trash is empty." although nothing was known)
  w.eval(`go('today')`); await until(() => w.eval(`S.route.key === 'today'`));
  w.eval(`window.__api0 = api; api = (m, u, b) => /scope=trash/.test(u) ? Promise.reject(new Error('boom')) : window.__api0(m, u, b); go('trash')`);
  const er = await until(() => d.querySelector('#view .empty.eerr'));
  check(er && /Could not be loaded/.test(txt(er)) && !/Trash is empty/.test(txt(d.querySelector('#view'))), '#5440: trash with a failed load says so, not "empty" ' + txt(er));
  const rb = er?.querySelector('[data-esretry]');
  check(rb && /Try again/.test(txt(rb)), '#5440: ... with "Try again"');
  w.eval(`api = window.__api0`); rb?.click();
  check(await until(() => /Trash is empty\./.test(txt(d.querySelector('#view .empty.nempty'))) && !d.querySelector('#view .eerr')), '#5440: "Try again" loads the trash (now empty)');
  // an empty board: a sentence above its columns (it had only the column "Tasks"); a board with tasks has none
  w.eval(`go('l/${BOARD}')`); await until(() => w.eval(`S.route.key === 'l:${BOARD}'`));
  await w.eval(`setListView(listById(${BOARD}), 'kanban')`);
  em = await until(() => d.querySelector('#view .empty.kempty'));
  check(em && /No tasks\./.test(txt(em)) && /\+ Task/.test(txt(em)) && em.classList.contains('es-sec') && d.querySelector('#view .kanban'), '#5440: empty board: the block above the columns ' + txt(em));
  w.eval(`go('l/${WORK}')`); await until(() => w.eval(`S.route.key === 'l:${WORK}'`));
  await w.eval(`setListView(listById(${WORK}), 'kanban')`);
  check(await until(() => /Sand the boards/.test(txt(d.querySelector('#view .kanban')))) && !d.querySelector('#view .empty.kempty'), '#5440: a board with tasks has no empty state');
  w.close();

  // ================= #5439 data: a shared project, two comments, many history lines of others after them
  const LP = (await call(CA, 'POST', '/api/lists', {name: 'Imagefilm'})).id;
  await call(CA, 'PUT', `/api/lists/${LP}/members`, {user_id: UC.id, role: 'edit'});
  await call(CA, 'PUT', `/api/lists/${LP}/members`, {user_id: UD.id, role: 'view'});
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Cut the trailer', list_id: LP, content: 'Two minutes, music from the archive.'})).id;
  await call(CA, 'POST', `/api/tasks/${T}/comments`, {body: 'First cut is on the drive.'});
  await call(CC, 'POST', `/api/tasks/${T}/comments`, {body: 'Looks good, shorten the intro please.'});
  for (const b of [{due: day(3)}, {priority: 3}, {due: day(4)}, {priority: 5}, {due: day(5)}, {priority: 1}, {due: day(6)}, {priority: 3}, {due: day(7)}, {priority: 5}, {due: day(8)}, {priority: 1}]) await call(CC, 'PATCH', `/api/tasks/${T}`, b);
  const T0 = (await call(CA, 'POST', '/api/tasks', {title: 'Book the studio', list_id: LP})).id;  // no comment
  await call(CA, 'PATCH', '/api/settings', {detail_split: '75'});  // a small comments area (~200 px, as on the shots of the tour)
  const signIn = async (o, u) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // is the comment with this text in sight: inside the viewport, its scroll parents and not under the bottom bar
  const SEEN = s => `(() => { const c = [...document.querySelectorAll('#detail #d-tl-items .cm')].find(x => x.textContent.includes(${JSON.stringify(s)})); if (!c) return false;
    const b = c.querySelector('.cbody') || c, r = b.getBoundingClientRect(); if (!r.height) return false; let top = 0, bot = innerHeight;
    for (let p = b.parentElement; p; p = p.parentElement) { const st = getComputedStyle(p); if (/(auto|scroll|hidden)/.test(st.overflowY)) { const q = p.getBoundingClientRect(); top = Math.max(top, q.top); bot = Math.min(bot, q.bottom); } }
    const db = document.querySelector('#detail .dbot'); if (db && !db.contains(b)) bot = Math.min(bot, db.getBoundingClientRect().top);
    return r.top >= top - 1 && r.top + Math.min(r.height, 16) <= bot + 1; })()`;
  // where "+ Section" of the empty project sits against the empty text
  const PLACE = `(() => { const e = document.querySelector('#view .empty.nempty'), b = e && e.querySelector('[data-act="section-new"]'); if (!e || !b) return null;
    const r = x => x.getBoundingClientRect(), t = r(e.querySelector('b')), s = r(e.querySelector('span') || e.querySelector('b')), br = r(b);
    return {gap: Math.round(br.top - s.bottom), bc: Math.round(br.left + br.width / 2), tc: Math.round(t.left + t.width / 2), h: Math.round(r(e).height), vis: br.bottom <= innerHeight}; })()`;

  // ================= desktop 1280 (mouse)
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    check(await signIn(o, 'alice') === 200, '1280: login');
    // #5440 the empty project, the filter without hits, the empty board
    await nav(B + `#l/${EMPTY}`);
    check(await ready(ev, `!!document.querySelector('#view .empty.nempty [data-act="section-new"]')`, 80), '1280: #5440 the empty project with "+ Section"');
    let p = await ev(PLACE);
    check(p && p.gap >= 0 && p.gap <= 40 && Math.abs(p.bc - p.tc) <= 2 && p.vis, '1280: #5440 "+ Section" right under the text, centred with it ' + JSON.stringify(p));
    check(p && p.h >= 190, '1280: #5440 the empty state keeps its minimum height ' + JSON.stringify(p));
    await shot('p2891d-empty-1280.png');
    await nav(B + `#f/${FID}`);
    check(await ready(ev, `/A filter is active/.test(document.querySelector('#view .empty.efilt')?.textContent || '') && !!document.querySelector('#view .empty.efilt [data-act="filter-edit"]')`, 80), '1280: #5440 filter without hits says so, with "Change filter"');
    await ev(`(() => { document.querySelector('#view .empty.efilt [data-act="filter-edit"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal input')`, 40), '1280: #5440 "Change filter" opens the filter');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // #5439 the task: newest comment in sight
    await nav(B + '#t/' + T);
    check(await ready(ev, `!!document.querySelector('#detail.dsplit #d-cpane #d-tl-items .cm')`, 80), '1280: the task with its comments area');
    check(await ready(ev, `document.querySelectorAll('#d-tl-items .actl').length >= 3`), '1280: history lines of others after the comments');
    check(await ready(ev, SEEN('shorten the intro'), 20), '1280: #5439 the newest comment is in sight when the task opens ' + await ev(`JSON.stringify({st: document.querySelector('#d-cpane').scrollTop, sh: document.querySelector('#d-cpane').scrollHeight, ch: document.querySelector('#d-cpane').clientHeight})`));
    await shot('p2891d-detail-1280.png');
    const g = await ev(`(() => { const w = document.querySelector('#detail .dlgrow'), m = document.querySelector('#detail #d-md:not(.hidden), #detail #d-content:not(.hidden)'); if (!w || !m) return null;
      return {gap: Math.round(m.getBoundingClientRect().top - w.getBoundingClientRect().bottom), one: !!w.querySelector('.dlg-wg .dlg-w') && !!w.querySelector('.dlg-wg .dlg-l'), proj: !!document.querySelector('#detail .dmlp'), crumb: document.querySelector('#detail .dcrumbs')?.textContent || ''}; })()`);
    check(g && g.gap <= 30, '1280: #5439 no empty space between "Watch" and the description ' + JSON.stringify(g));
    check(g && g.one, '1280: #5439 Watch and the watchers count are one element');
    check(g && !g.proj && /Imagefilm/.test(g.crumb), '1280: #5439 the project once (the path on top, no field Projects) ' + JSON.stringify(g));
    check(await ev(`!!document.querySelector('#detail .dcrumbs [data-k="list"][data-id="${LP}"]')`), '1280: #5439 the path on top is the way to the project');
    // "Loading…" keeps its height when it turns into the history line of a task without comments (the timeline held back)
    await ev(`(() => { const f0 = window.fetch; window.fetch = (u, x) => /\\/timeline/.test(String(u)) ? new Promise(r => setTimeout(() => r(f0(u, x)), 1500)) : f0(u, x); location.hash = '#t/${T0}'; return 1; })()`);
    check(await ready(ev, `/Loading/.test(document.querySelector('#detail #d-tl-items')?.textContent || '') && document.querySelector('#detail #d-title')?.value === 'Book the studio'`, 40), '1280: the comments are loading');
    const h1 = await ev(`Math.round(document.querySelector('#detail #d-tl-items').getBoundingClientRect().height)`);
    check(await ready(ev, `!!document.querySelector('#detail #d-tl-items .actl, #detail #d-tl-items .cmempty:not(.cmload)') && !/Loading/.test(document.querySelector('#detail #d-tl-items').textContent)`, 40), '1280: then its history line (a shared task: "created")');
    const h2 = await ev(`Math.round(document.querySelector('#detail #d-tl-items').getBoundingClientRect().height)`);
    check(h1 > 0 && Math.abs(h1 - h2) <= 1, `1280: #5439 the loading place keeps its height (${h1} -> ${h2})`);
  }, false);

  // ================= phone 360 (touch)
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    check(await signIn(o, 'alice') === 200, '360: login');
    await nav(B + `#l/${EMPTY}`);
    check(await ready(ev, `!!document.querySelector('#view .empty.nempty [data-act="section-new"]')`, 80), '360: #5440 the empty project with "+ Section"');
    const p = await ev(PLACE);
    check(p && p.gap >= 0 && p.gap <= 40 && Math.abs(p.bc - p.tc) <= 2 && p.vis, '360: #5440 "+ Section" right under the text, not far below in the middle ' + JSON.stringify(p));
    await shot('p2891d-empty-360.png');
    await nav(B + `#l/${BOARD}`);
    check(await ready(ev, `S.route?.key === 'l:${BOARD}' && !!listById(${BOARD})`, 60), '360: the board project opens');
    await ev(`setListView(listById(${BOARD}), 'kanban').then(() => 1)`);
    check(await ready(ev, `!!document.querySelector('#view .empty.kempty') && !!document.querySelector('#view .kanban')`, 40), '360: #5440 the empty board says so above its columns');
    await nav(B + '#t/' + T);
    check(await ready(ev, `!!document.querySelector('#detail #d-tl-items .cm') && !!document.querySelector('#detail .dthumb')`, 80), '360: the task with its comments and the bar');
    if (!(await ready(ev, SEEN('First cut is on the drive'), 8))) {  // below the description: one tap on "To the comments"
      check(await ev(`!!document.querySelector('#detail [data-act="d-jump-cm"]')`), '360: #5439 the comments are one tap away ("To the comments")');
      await ev(`(() => { document.querySelector('#detail [data-act="d-jump-cm"]').click(); return 1; })()`);
      check(await ready(ev, SEEN('First cut is on the drive'), 20), '360: #5439 after the tap the comment text is in sight');
    }  // seen at once: the SEEN() probe is the check (#5439)
    await shot('p2891d-detail-360.png');
    await ev(`(() => { document.querySelector('#detail .dbody').scrollTop = 0; return 1; })()`);
    const m = await ev(`(() => { const r = s => document.querySelector(s)?.getBoundingClientRect(); const b = r('#detail .dbot'), t = r('#detail .dtop'), w = r('#detail .dlgrow'), md = r('#detail #d-md:not(.hidden)') || r('#detail #d-content:not(.hidden)');
      const kids = [...document.querySelectorAll('#detail .dthumb > *')].filter(x => x.getBoundingClientRect().height > 0).map(x => Math.round(x.getBoundingClientRect().top));
      const wd = s => Math.round(document.querySelector(s)?.getBoundingClientRect().width || 0);
      return {rows: new Set(kids).size, tops: kids, widths: {bar: wd('#detail .dthumb'), chip: wd('#detail .dthumb .dchip'), need: document.querySelector('#detail .dthumb .dchip')?.scrollWidth, done: wd('#detail .dthumb .dtdone'), date: document.querySelector('#detail .dthumb .dchip')?.textContent.trim()}, bot: b && Math.round(b.height), top: t && Math.round(t.height), ih: innerHeight, gap: w && md ? Math.round(md.top - w.bottom) : null, proj: !!document.querySelector('#detail .dthumb .dtproj'), field: !!document.querySelector('#detail .dmlp')}; })()`);
    check(m.rows === 1 || (m.tops.length && Math.max(...m.tops) - Math.min(...m.tops) <= 4), '360: #5439 the bar is one row ' + JSON.stringify(m));
    check(m.bot > 0 && m.bot + m.top <= m.ih / 3 + 2, '360: #5439 the bar + comment field (+ head) take at most a third of the height ' + JSON.stringify(m));
    check(m.gap !== null && m.gap <= 30, '360: #5439 no empty space under "Watch" ' + JSON.stringify(m));
    check(!m.proj && !m.field, '360: #5439 no second project (bar, field) ' + JSON.stringify(m));
    // back to the list
    await ev(`(() => { document.querySelector('#detail [data-act="close-detail"]').click(); return 1; })()`);
    check(await ready(ev, `!location.hash.startsWith('#t/') && !!document.querySelector('#view .trow, #view .empty')`, 40), '360: #5439 Back leaves the task for the list ' + await ev('location.hash'));
  }, true);

  // ================= a reader: no empty "Attachments"
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    check(await signIn(o, 'dora') === 200, 'reader: login');
    await nav(B + '#t/' + T);
    check(await ready(ev, `document.querySelector('#detail #d-title')?.value === 'Cut the trailer' && !!document.querySelector('#detail .rotag')`, 80), 'reader: the task opens read-only');
    await ev(`(() => { const m = document.querySelector('#detail #d-more'); if (m) m.open = true; return 1; })()`);
    check(!(await ev(`!!document.querySelector('#detail .attsec')`)), 'reader: #5439 no empty "Attachments" section');
  }, false);

  console.log(`p2891_d_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
