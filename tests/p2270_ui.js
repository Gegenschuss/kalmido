// 2.27.0 UI tests ("Bugs & polish"), own container (start.sh). jsdom:
// #968 the bar "New version available – Reload" when the server runs another version than the code in the window (not while
//      typing; never in a loop), Help shows the app's and the server's version
// #957 the comments come last in the task panel again ("More details" folded above them, with a summary line)
// #966 / #975 / #977 the list dialog: Type = Simple list | Project at the top; "Used for" only for a simple list; the family
//      fields of a task only in family lists (never in a project)
// #972 New project: the box "With the standard sections" (off) names the type's sections; #990 "+ Section" in an empty list
//      and "Add section…" in the list's menu; #974 "Agent: <name>…" opens the share dialog at its agents
// #964 Settings > Agents > Lists grouped by folder, a filter, one agent for a whole folder (one undo); the one agent's
//      "Agent reads every comment" is a switch
// #967 list tags in a list that is not shared; #984 "Views" above the lists; #986 the team chat shows only conversations
//      with messages; #955 the Agents tab explains why it is empty; #1001 "My tasks"; #994 the description shows more lines;
//      #991 a list to the very bottom of its folder; #988 a list in someone else's folder cannot be moved by a member, a
//      member's own sort of a shared list is pointed out
// Firefox: #966 the hidden row really is invisible, #976 the grips step aside while a menu is open, #1006 the column line,
// #958 typing with the list scrolled up never moves the list behind (390 touch, a fake visual viewport that changes its
// height and offset on every key), screenshots in $P2270_SHOTS when set.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2270_ui', check, shots: 'P2270_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,family,team';
const menuItems = d => [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim());

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  await call('PATCH', '/api/settings', {folders: '["Work", "Home"]'});
  const L = (await call('POST', '/api/lists', {name: 'Garden', folder: 'Home'})).id;
  const W1 = (await call('POST', '/api/lists', {name: 'Website', folder: 'Work'})).id;
  const W2 = (await call('POST', '/api/lists', {name: 'Shop', folder: 'Work'})).id;
  const EMPTY = (await call('POST', '/api/lists', {name: 'Empty one', folder: 'Home'})).id;
  const FAM = (await call('POST', '/api/lists', {name: 'Family plans', family: 'household'})).id;
  const PRJ = (await call('POST', '/api/lists', {name: 'Client work', kind: 'project'})).id;
  for (const lid of [FAM, PRJ, W1, W2]) await call('PUT', `/api/lists/${lid}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${W1}/members`, {user_id: AG, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Cut the hedge', list_id: L, tags: ['outside'], content: Array.from({length: 12}, (_, i) => `Line ${i + 1}`).join('\n')})).id;
  await call('POST', `/api/tasks/${T1}/comments`, {body: 'A first comment'});
  const TF = (await call('POST', '/api/tasks', {title: 'Dentist', list_id: FAM})).id;
  const TP = (await call('POST', '/api/tasks', {title: 'Kick-off', list_id: PRJ})).id;

  // ================= #968 a new version on the server
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await until(() => d.querySelector('#view .trow'));
  const appVer = d.querySelector('meta[name="kalmido-version"]')?.content;
  check(/^\d+\.\d+\.\d+$/.test(appVer || ''), '#968: the page names its code version ' + appVer);
  let reloads = 0; w.eval('verReload = () => { window.__rl = (window.__rl || 0) + 1; }');
  w.eval(`S.serverVer = '${appVer}'; verCheck('${appVer}')`);
  check(!d.querySelector('#newver'), '#968: same version: no bar');
  // typing: the bar, no reload
  w.eval(`(() => { const i = document.querySelector('#qinput'); i.focus(); i.value = 'half typed'; })()`);
  w.eval(`verCheck('99.0.0')`);
  check(d.querySelector('#newver') && /New version available/.test(d.querySelector('#newver').textContent) && /Reload/.test(d.querySelector('#newver button').textContent), '#968: another version: the bar with Reload');
  check(!w.__rl, '#968: never reloads while someone types');
  click(w, d.querySelector('#newver [data-nv="go"]')); await sleep(50);
  check(w.__rl === 1, '#968: Reload reloads');
  w.eval(`settingsModal('help')`); await until(() => d.querySelector('.aboutapp'));
  check(/v\d/.test(d.querySelector('.aboutapp')?.textContent || '') && /Server: v99\.0\.0/.test(d.querySelector('.aboutapp')?.textContent || '') && d.querySelector('.aboutapp.off [data-nv="go"]'),
    '#968: Help shows the app and the server version, marked, with Reload ' + (d.querySelector('.aboutapp')?.textContent || '').trim());
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.eval(`S.serverVer = '${appVer}'; verCheck('${appVer}')`);
  check(!d.querySelector('#newver'), '#968: back in step: the bar goes');
  // quiet + an update: one reload by itself, not a second time for the same version
  w.eval(`document.activeElement.blur(); document.querySelector('#qinput').value = ''; verIdle = Date.now() - 60000; sessionStorage.removeItem('kalmido-reloaded'); window.__rl = 0; verCheck('99.0.1')`);
  check(w.__rl === 1, '#968: quiet: reloads once by itself');
  w.eval(`sessionStorage.setItem('kalmido-reloaded', '99.0.1'); window.__rl = 0; verCheck('99.0.1')`);
  check(!w.__rl && d.querySelector('#newver'), '#968: never twice for the same version (the bar stays)');
  w.eval(`S.serverVer = '${appVer}'; verCheck('${appVer}')`);

  // ================= #957 comments last; #994 more lines of the description
  w.eval(`openDetail(${T1})`); await until(() => d.querySelector('#d-tl .cm'));
  const kids = [...d.querySelector('#detail .dbody').children].map(x => x.id || x.className);
  check(kids.indexOf('d-more') >= 0 && kids.indexOf('d-tl') === kids.length - 1 && kids.indexOf('d-more') < kids.indexOf('d-tl'), '#957: "More details" above, the comments last ' + kids.join('|').slice(0, 200));
  check(/1 tag/.test(d.querySelector('#d-more .dmsum')?.textContent || ''), '#957: the folded details say what they hold ' + d.querySelector('#d-more summary')?.textContent);
  check(d.querySelector('#d-md.clamp') && w.getComputedStyle(d.querySelector('#d-md')).maxHeight !== 'none', '#994: a 12-line description still folds');
  w.eval('closeDetail()');
  w.close();

  // ================= list dialog (#977 #966 #972), family fields (#975)
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  await until(() => d.querySelector('#view .trow'));
  w.eval(`listModal(${L})`); let md = await until(() => d.querySelector('.modal.lmodal'));
  const rowsOrder = [...md.querySelectorAll('.card > .row, .card > .lhdr, .card > .row.lkrow')].map(x => x.className);
  check(md.querySelector('.lkseg #l-kindl')?.checked && !md.querySelector('#l-kindp').checked && md.querySelector('.lkseg label.on')?.textContent.includes('Simple list'), '#977: Type: Simple list | Project, Simple list on');
  check(md.querySelector('.lkrow').compareDocumentPosition(md.querySelector('#l-folder')) & 4, '#977: the type sits at the top (before the folder) ' + rowsOrder.slice(0, 4));
  check(md.querySelector('.lfamrow') && !md.querySelector('.lfamrow').hidden, '#977: "Used for" for a simple list');
  click(w, md.querySelector('#l-kindp')); md.querySelector('#l-kindp').checked = true; md.querySelector('#l-kindp').dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === L).kind === 'project');
  check(md.querySelector('.lfamrow').hidden && !md.querySelector('.kproj').hidden && md.querySelector('.lkseg label.on')?.textContent.includes('Project'), '#966: a project: no "Used for", the project fields');
  md.remove();
  await call('PATCH', `/api/lists/${L}`, {kind: 'list'}); await w.eval('load().then(render)'); await sleep(300);
  w.eval(`listModal(null, '', {kind: 'project'})`); md = await until(() => d.querySelector('.modal.lnew'));
  click(w, md.querySelector('[data-pt="software"]'));
  check(!md.querySelector('.ptsecs').hidden && !md.querySelector('#l-ptsecs').checked && /Backlog, Next, In progress, Review, Done/.test(md.querySelector('#l-ptsecsl').textContent), '#972: the box (off) names the sections');
  md.querySelector('#l-name').value = 'Sprint';
  click(w, md.querySelector('[data-m="save"]'));
  let sp = await until(async () => (await call('GET', '/api/state')).lists.find(l => l.name === 'Sprint'));
  check(sp && !(await call('GET', '/api/state')).sections.some(s => s.list_id === sp.id), '#972: created without sections');
  w.eval(`listModal(null, '', {kind: 'project'})`); md = await until(() => d.querySelector('.modal.lnew'));
  click(w, md.querySelector('[data-pt="agency"]')); md.querySelector('#l-ptsecs').checked = true; md.querySelector('#l-name').value = 'Agency X';
  click(w, md.querySelector('[data-m="save"]'));
  sp = await until(async () => (await call('GET', '/api/state')).lists.find(l => l.name === 'Agency X'));
  check(sp && (await call('GET', '/api/state')).sections.filter(s => s.list_id === sp.id).length === 5, '#972: ticked: the five sections');
  // #967 list tags in a private list
  w.eval(`listModal(${EMPTY})`); md = await until(() => d.querySelector('.modal.lmodal'));
  check(md.querySelector('#l-ltags') && /as soon as you share the list/.test(md.textContent), '#967: list tags in a list that is not shared, with the hint');
  md.remove();
  // #975 family fields
  w.eval(`openDetail(${TF})`); await until(() => d.querySelector('#d-title'));
  check(await until(() => /Who comes along|Take turns/.test(d.querySelector('#detail')?.textContent || '')), '#975: a family list: the family fields ' + (d.querySelector('#detail .famsec')?.textContent || 'no famsec') + ' ' + JSON.stringify(w.eval(`(() => { const l = listById(${FAM}); return {f: l.family, sh: l.shared, n: listPeople(l).length, rep: taskById(${TF})?.repeat}; })()`)));
  w.eval(`openDetail(${TP})`); await sleep(500);
  check(!/Who comes along|Take turns/.test(d.querySelector('#detail')?.textContent || ''), '#975: a project: none');
  w.eval('closeDetail()');
  // #990 + Section in an empty list, Add section… in the menu
  w.eval(`go('l/${EMPTY}')`); await until(() => d.querySelector('#view .heron, #view .hempty, #view .empty'));
  check(d.querySelector('#view [data-act="section-new"]'), '#990: "+ Section" in an empty list');
  const lm = w.eval(`listMenuItems(${EMPTY}, document.querySelector('#top h1')).map(x => x.label || x)`);
  check(lm.includes('Add section…'), '#990: "Add section…" in the list\'s menu');
  // #974 Agent… in the list's menu
  const wm = w.eval(`listMenuItems(${W1}, document.querySelector('#top h1')).map(x => x.label || x)`);
  check(wm.includes('Agent: Claude…') && wm.indexOf('Agent: Claude…') === wm.indexOf('Share…') + 1, '#974: "Agent: Claude…" right under Share… ' + wm.slice(0, 4));
  check(w.eval(`listMenuItems(${W2}, document.querySelector('#top h1')).map(x => x.label || x)`).includes('Agent…'), '#974: "Agent…" when the list has none');
  w.eval(`shareModal(${W1}, {focus: 'agents'})`);
  check(await until(() => d.activeElement?.id === 'sh-agsel'), '#974: the share dialog opens at the agent choice');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  // #991 to the bottom of its folder
  w.eval(`moveListEnd(${W1}, 1)`);
  await until(async () => { const ls = (await call('GET', '/api/state')).lists; return ls.find(l => l.id === W1).sort > ls.find(l => l.id === W2).sort; });
  check(w.eval(`(load().then(render), 1)`) && true, 'reload');
  await sleep(500);
  check(w.eval(`sideOrder().filter(l => l.folder === 'Work').map(l => l.id).join()`) === `${W2},${W1}`, '#991: Website now the last of Work');
  const sm = w.eval(`listMenuItems(${W1}, document.querySelector('#side .srow[data-list="${W1}"]')).map(x => x.label || x)`);
  check(sm.includes('Move to the top') && sm.includes('Move to the bottom'), '#991: the sidebar menu has top / bottom ' + sm.join('|'));
  // #984 views above the lists, #1001 My tasks
  const grp = [...d.querySelectorAll('#side .sgroup')].map(x => [...x.classList].find(c => c.startsWith('sg-')));
  check(grp.indexOf('sg-views') >= 0 && grp.indexOf('sg-views') < grp.indexOf('sg-lists'), '#984: Views above the lists ' + grp.join());
  check(/My tasks/.test(d.querySelector('#side [data-go="assigned"]')?.textContent || ''), '#1001: "My tasks"');
  w.close();

  // ================= bob: #988 mirrored, own sort hint; #986 team chat; #955
  w = await boot({user: 'bob', hash: 'l/' + W2}); d = w.document;
  await until(() => d.querySelector('#top h1'));
  check(w.eval(`listById(${W2}).mirrored`) && w.eval(`listById(${W2}).folder`) === 'Work', '#988: bob sees Shop in Alice\'s folder Work');
  w.eval(`moveList(${W2}, -1)`); await sleep(200);
  check(/arranges the lists of this shared folder/.test(d.querySelector('#toast')?.textContent || ''), '#988: bob cannot move it: says who arranges it');
  await call('PATCH', `/api/lists/${W2}`, {sort_mode: 'title'});
  await w.eval('load().then(render)'); await sleep(400);
  check(w.eval('sortMode()') === 'title' && !d.querySelector('.sortown'), '#988: the list\'s sort for bob too, no hint');
  w.eval(`LS.set('sort2.l:${W2}', 'date'); render()`); await sleep(200);
  check(w.eval('sortMode()') === 'date' && d.querySelector('.sortown [data-act="sort-shared"]'), '#988: his own sort is pointed out');
  click(w, d.querySelector('.sortown [data-act="sort-shared"]')); await sleep(200);
  check(w.eval('sortMode()') === 'title' && !d.querySelector('.sortown'), '#988: back to the shared sort');
  w.eval(`go('team')`); await until(() => d.querySelector('.tclist'));
  await sleep(600);
  check(!d.querySelector('.tclist .tcrow') && d.querySelector('.tcempty [data-act="tc-new"]'), '#986: no empty conversations, "Start a conversation"');
  click(w, d.querySelector('.tcempty [data-act="tc-new"]')); await sleep(200);
  check(menuItems(d).some(x => /Family plans|Client work|Shop|Website/.test(x)), '#986: the chats of shared lists to start ' + menuItems(d).join('|'));
  w.eval('closePop()');
  w.eval(`settingsModal('agents')`); await until(() => d.querySelector('#s-myags .agnone, #s-myags .mhint'));
  check(/No agent is available to you yet/.test(d.querySelector('#s-myags')?.textContent || '') && d.querySelector('#s-myags [data-aigo="setup"]'), '#955: why it is empty + connect your own');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.close();

  // ================= #964 Settings > Agents > Lists
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('agents')`); await sleep(400);
  click(w, d.querySelector('[data-aisub="lists"]'));
  await until(() => d.querySelector('#s-ai-tbl .aigrp'), 60);
  const gs = [...d.querySelectorAll('#s-ai-tbl .aigrp')].map(x => x.dataset.aig);
  check(gs[0] === '' && gs.includes('Work') && gs.includes('Home'), '#964: grouped by folder, lists without one first ' + JSON.stringify(gs));
  change(w, d.querySelector('#ai-f'), 'with'); await sleep(200);
  check([...d.querySelectorAll('#s-ai-tbl .airow[data-lid]')].map(x => +x.dataset.lid).join() === String(W1), '#964: filter "With an agent"');
  change(w, d.querySelector('#ai-f'), ''); await sleep(200);
  w.confirm = () => true;
  change(w, d.querySelector('#s-ai-tbl [data-aigsel="Work"]'), String(AG));
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === W2).members.some(m => m.user_id === AG), 60), '#964: one agent for the whole folder');
  check(/now works in 1 lists|now works in/.test(d.querySelector('#toast')?.textContent || ''), '#964: with an undo ' + d.querySelector('#toast')?.textContent);
  click(w, d.querySelector('#s-ai-tbl [data-aifold="Work"]')); await sleep(200);
  check(!d.querySelector(`#s-ai-tbl .airow[data-lid="${W1}"]`) && d.querySelector('#s-ai-tbl [data-aifold="Work"][aria-expanded="false"]'), '#964: a folder group folds');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.eval(`shareModal(${W1})`); await until(() => d.querySelector('#l-tidyrow'), 60);
  check(d.querySelector('#l-tidyrow .lsn1 input[role="switch"][data-lsn]') && !d.querySelector('#l-tidyag'), '#964: one agent: "reads every comment" is a switch, no "Tidy up by"');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.close();

  // ================= Firefox 1440: #966 visibility, #976 grips under menus, #1006 the column line
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await call('PATCH', `/api/lists/${PRJ}`, {columns: ['due', 'who', 'created']});
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + PRJ); await ready(ev);
    check(await ev(`(() => { const g = document.querySelector('.lchead .lcg'); if (!g) return false; const s = getComputedStyle(g, '::after'); return s.backgroundColor !== 'rgba(0, 0, 0, 0)' && s.backgroundColor !== 'transparent'; })()`), `${tag}: #1006 a visible line between the column titles`);
    check(/Drag the column width/.test(await ev(`document.querySelector('.lchead .lcg')?.title || ''`)), `${tag}: #1006 its tooltip`);
    await shot(`p2270-${th}-1440-columns.png`);
    await ev(`(() => { openDetail(${TP}); return 1; })()`); await sleep(900);
    const ord = await ev(`[...document.querySelector('#detail .dbody').children].map(x => x.id || x.className).join('|')`);
    check(/d-more.*d-tl|d-tl$/.test(ord), `${tag}: #957 the comments last ` + ord.slice(-80));
    await shot(`p2270-${th}-1440-panel.png`);
    // a menu open: the grips step aside
    await ev(`(() => { listMenu(document.querySelector('#top h1'), ${PRJ}); return 1; })()`); await sleep(300);
    check(await ev(`[...document.querySelectorAll('.pgrip')].filter(g => !g.hidden).every(g => getComputedStyle(g).visibility === 'hidden')`), `${tag}: #976 the grips step aside while a menu is open`);
    check(await ev(`(() => { const p = document.querySelector('#pop'), r = p.getBoundingClientRect(), e = document.elementFromPoint(r.left + r.width / 2, r.top + 12); return p.contains(e); })()`), `${tag}: #976 the menu is on top`);
    await shot(`p2270-${th}-1440-menu.png`);
    await ev(`(() => { closePop(); return 1; })()`); await sleep(200);
    check(await ev(`[...document.querySelectorAll('.pgrip')].filter(g => !g.hidden).every(g => getComputedStyle(g).visibility === 'visible')`), `${tag}: #976 back after the menu`);
    check(await ev(`(() => { const g = document.querySelector('#pgrip-chat'); return !g || g.hidden && getComputedStyle(g).display === 'none'; })()`), `${tag}: #978 no chat grip while the chat is closed`);
    // #966: a hidden row is invisible
    await ev(`(() => { closeDetail(); listModal(${PRJ}); return 1; })()`); await sleep(500);
    check(await ev(`(() => { const r = document.querySelector('.lfamrow'); return !r || r.offsetParent === null; })()`), `${tag}: #966 "Used for" really invisible in a project`);
    await shot(`p2270-${th}-1440-listdialog.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // the version bar
    // (one step: the app's own poll every 4 s puts the real version back)
    check(await ev(`(() => { verIdle = Date.now(); document.querySelector('#qinput')?.focus(); verCheck('99.9.9'); const b = document.querySelector('#newver'); if (!b) return false; const r = b.getBoundingClientRect(); return r.top >= 0 && r.width > 100 && r.right <= innerWidth; })()`), `${tag}: #968 the bar on screen`);
    await shot(`p2270-${th}-1440-newversion.png`);
  }, false);

  // ================= Firefox 390 touch: #958 typing never moves the list behind
  const many = (await call('POST', '/api/lists', {name: 'Long list'})).id;
  for (let i = 0; i < 40; i++) await call('POST', '/api/tasks', {title: 'Row ' + i, list_id: many});
  const FAKEVV = (h, top) => `Object.defineProperty(window, 'visualViewport', {configurable: true, value: {height: innerHeight - ${h}, offsetTop: ${top}, width: innerWidth, offsetLeft: 0, scale: 1, addEventListener() {}, removeEventListener() {}}});`;
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + many); await ready(ev);
    await ev(`(() => { document.querySelector('#view').scrollTop = 600; return 1; })()`); await sleep(300);
    const s0 = await ev(`document.querySelector('#view').scrollTop`);
    check(s0 > 300, `${tag}: the list scrolled up (${s0})`);
    // the add sheet: keys with a keyboard whose height and offset change (suggestion bar, iOS caret reveal)
    await ev(`(() => { openQuickSheet(); return 1; })()`); await sleep(500);
    const res = await ev(`(async () => { const el = document.querySelector('#qsheet'); el.focus(); const out = [];
      for (let i = 0; i < 8; i++) { ${FAKEVV('(i % 2 ? 336 : 291)', '(i % 3) * 40')} vvSync(); el.value += 'x'; el.dispatchEvent(new InputEvent('input', {bubbles: true})); await new Promise(r => setTimeout(r, 140));
        out.push(document.querySelector('#view').scrollTop + '/' + (window.scrollY || 0)); }
      return out; })()`);
    check(res.every(x => +x.split('/')[0] === s0), `${tag}: #958 the list behind never moves while typing in the add sheet ` + res.join(' '));
    await shot('p2270-light-390-quicksheet-typing.png');
    await ev(`(() => { document.activeElement.blur(); ${FAKEVV(0, 0)} vvSync(); closePop(); return 1; })()`); await sleep(500);
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
