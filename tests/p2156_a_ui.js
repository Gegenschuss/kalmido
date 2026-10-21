// 2.156.0 UI tests of part A (own container, start.sh). jsdom:
// - #1949: the client knows five levels (state max_depth -> maxDepth()); the mind map makes a sub-branch down to level 5
//   and refuses level 6 with a hint (no editor, no "New sub-branch" in the sheet), dragging onto a branch that would go too
//   deep changes nothing, onto level 4 works; the import puts deeper levels below level 5 (mm_flatCap); the task view offers
//   "Add subtask" down to level 4; CSS indents levels 4 and 5 and less on a phone
// - #1948: properties on demand: key E / the tool bar button / the More menu, remembered per list; a branch with properties
//   gets the taller node (52) with the second line (priority dot, date, person, tags, subtasks), the line meets its middle;
//   off: the selected branch shows its properties below it (peek); the outline shows them too; the SVG export carries the line
// - #1201: "Add ideas" (key I) asks the agent of the list (dialog with what it gets), the map shows the waiting request, the
//   agent's ideas as pale branches; ✓ takes one over (a task, Undo removes it), "Discard all" ends it; without an agent of the
//   list the entry is greyed with the hint; the bell's "Proposal ready" opens the list as a mind map; phone: the sheet of an idea
// Firefox (real layout, skipped without firefox): screenshots (P2156A_SHOTS) desktop with properties + ideas, phone map,
// phone outline -- and nothing leaves the screen at 390 px
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p2156_a_ui', check: (c, w) => check(c, w), shots: 'P2156A_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2156A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const agent = async (method, url, body, tok) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const rectH = (d, id) => +(d.querySelector(`#view [data-mmn="${id}"] > rect`)?.getAttribute('height') || 0);
const toastText = d => d.querySelector('#toast')?.textContent || '';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice Admin', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const L = (await call('POST', '/api/lists', {name: 'Brainstorm'})).id;
  await call('PATCH', '/api/lists/' + L, {view: 'mindmap'});
  const mk = async (title, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: L, ...extra})).id;
  const A1 = await mk('Plan', {priority: 5, due: '2030-05-02', tags: ['web']});
  const A2 = await mk('Design', {parent_id: A1});
  const A3 = await mk('Pages', {parent_id: A2});
  const A4 = await mk('Home page', {parent_id: A3});
  const LOOSE = await mk('Loose');
  const tasks = async () => (await call('GET', '/api/state')).tasks.filter(t => t.list_id === L);

  // ================= #1949 five levels
  let w = await boot({user: 'alice', hash: 'l/' + L, rowIcons: 'all'}), d = w.document;
  const stage = () => d.querySelector('#view .mmstage');
  check(await until(() => stage() && d.querySelector(`#view [data-mmn="t${A4}"]`)), 'the list opens as a mind map with four levels');
  check(w.eval('S.maxDepth') === 5 && w.eval('maxDepth()') === 5, '#1949: the client has the levels from the server: ' + w.eval('S.maxDepth'));
  w.eval(`mm_select('t${A4}')`);
  key(w, stage(), 'Tab');
  let ed = await until(() => d.querySelector('#mm-edit'));
  check(ed, '#1949: level 4 takes a sub-branch (editor)');
  if (ed) { ed.value = 'Hero image'; key(w, ed, 'Enter'); }
  const A5 = (await until(async () => (await tasks()).find(t => t.title === 'Hero image')))?.id;
  check(A5 && (await tasks()).find(t => t.id === A5).parent_id === A4, '#1949: level 5 created');
  await until(() => d.querySelector(`#view [data-mmn="t${A5}"]`));
  w.eval(`mm_select('t${A5}')`); await sleep(50);
  key(w, stage(), 'Tab'); await sleep(150);
  check(!d.querySelector('#mm-edit') && /At most 5 levels/.test(toastText(d)), '#1949: level 6 refused with a hint: ' + toastText(d));
  const items = w.eval(`(() => { let got = null; const m0 = menu; menu = (a, its) => { got = its; }; mm_nodeMenu(null, mm_node('t${A5}')); menu = m0; return got.filter(x => x && x.label).map(x => x.label + (x.dis ? '!' : '')).join('|'); })()`);
  check(!/New sub-branch/.test(items) && /New branch/.test(items), '#1949: the sheet of level 5 has no "New sub-branch": ' + items);
  await w.eval(`mm_rehang('t${LOOSE}', 't${A5}')`); await sleep(200);
  check(!(await tasks()).find(t => t.id === LOOSE).parent_id, '#1949: dragging onto level 5 changes nothing');
  await w.eval(`mm_rehang('t${LOOSE}', 't${A4}')`);
  check(await until(async () => (await tasks()).find(t => t.id === LOOSE).parent_id === A4), '#1949: dragging onto level 4 makes it level 5');
  check(w.eval(`dgFits(${A3}, ${LOOSE})`) && !w.eval(`dgFits(${A5}, ${LOOSE})`), '#1949: the drag check of the list reads the levels');
  const cap = w.eval(`JSON.stringify(mm_flatCap([{title: 'a', children: [{title: 'b', children: [{title: 'c', children: []}]}]}], 3))`);
  check(cap === JSON.stringify({items: [{title: 'a', children: [{title: 'b', children: []}, {title: 'c', children: []}]}], moved: 1}), '#1949: import: below level 5 flattened ' + cap);
  w.eval(`mm_select('t${A3}')`);
  await w.eval(`mm_importTree(listById(${L}), {children: [{title: 'Imp 1', children: [{title: 'Imp 2', children: [{title: 'Imp 3', children: []}]}]}]})`);
  const imp = await until(async () => { const ts = await tasks(); const g = n => ts.find(t => t.title === n); return g('Imp 3') && [g('Imp 1'), g('Imp 2'), g('Imp 3')]; });
  check(imp && imp[0].parent_id === A3 && imp[1].parent_id === imp[0].id && imp[2].parent_id === imp[0].id, '#1949: the import under level 3 ends at level 5 (Imp 3 next to Imp 2)');
  check(/moved up/.test(toastText(d)), '#1949: the import says so: ' + toastText(d));
  w.eval(`openDetail(${A4})`); await sleep(300);
  check(d.querySelector('#d-sub'), '#1949: the task view of level 4 offers "Add subtask"');
  w.eval(`closeDetail(); openDetail(${A5})`); await sleep(300);
  check(!d.querySelector('#d-sub'), '#1949: level 5 does not');
  w.eval('closeDetail()');
  const css = require('./boot').allCssSync();
  check(/\.trow\.d3\{margin-left:5\.25rem\}/.test(css) && /\.trow\.d4\{margin-left:7rem\}/.test(css) && /max-width:599px\)\{\.trow\.sub\.d1\{margin-left:1\.125rem\}/.test(css),
    '#1949: CSS indents levels 4 and 5, less on a phone');

  // ================= #1948 properties on demand
  w.eval(`MM.sel = 'r'; mm_draw()`); await sleep(200);
  check(!d.querySelector('#view .mmprops') && rectH(d, 't' + A1) === 34, '#1948: off by default: one-line branches');
  key(w, stage(), 'e'); await sleep(250);
  check(w.eval('MM.props') === true && JSON.parse(w.localStorage.getItem('tasks.mmProps') || '{}')[L] === 1, '#1948: E switches it on, remembered per list');
  check(rectH(d, 't' + A1) === 52 && d.querySelector(`#view [data-mmn="t${A1}"] .mmprops .mmpd.p5`), '#1948: a branch with properties: taller node, priority dot');
  const pk = w.eval(`mm_node('t${A1}').pi.map(x => x.k).join(',')`);
  check(pk === 'prio,due,sub,tag', '#1948: the line: priority, date, subtasks, tags (the row symbols "All"): ' + pk);
  check(rectH(d, 't' + A5) === 34, '#1948: a branch without properties keeps one line');
  const ln = w.eval(`(() => { const n = mm_node('t${A1}'); return [...document.querySelectorAll('#view .mmline')].map(p => p.getAttribute('d')).find(s => s.endsWith(' ' + n.x + ' ' + (n.y + n.h / 2))) || ''; })()`);
  check(ln, '#1948: the line meets the middle of the taller node');
  const ovl = w.eval(`(() => { const ns = MM.last.L.nodes; return ns.some(a => ns.some(b => a !== b && a.x === b.x && a.y < b.y + b.h && b.y < a.y + a.h)); })()`);
  check(!ovl, '#1948: no two nodes of a column overlap');
  check(/class="mmprops"/.test(w.eval('mm_exportSvg()')), '#1948: the SVG export carries the properties');
  d.querySelector('#view [data-mm="as-outline"]').click(); await sleep(200);
  check(d.querySelector('#view .mmoutline .mmop .mmpd'), '#1948: the outline shows them too');
  d.querySelector('#view [data-mm="as-map"]').click(); await sleep(200);
  d.querySelector('#view [data-mm="props"]').click(); await sleep(250);
  check(w.eval('MM.props') === false && rectH(d, 't' + A1) === 34, '#1948: the button switches it off');
  w.eval(`mm_select('t${A1}')`); await sleep(100);
  check(d.querySelector('#mm-peek .mmpd') && /#web/.test(d.querySelector('#mm-peek').textContent), '#1948: off: the selected branch shows its properties below it');
  check(!/class="mmprops"/.test(w.eval('mm_exportSvg()')), '#1948: the export follows the switch');
  const more = w.eval(`(() => { let got = null; const m0 = menu; menu = (a, its) => { got = its; }; mm_moreMenu(document.querySelector('#view [data-mm="more"]')); menu = m0; return got.filter(x => x && x.label).map(x => x.label + (x.dis ? '!' : '')).join('|'); })()`);
  check(/Show properties/.test(more) && /Add ideas/.test(more), '#1948 / #1201: the More menu: ' + more);
  w.close();

  // ================= #1201 add ideas
  const ag = await call('POST', '/api/admin/agents', {username: 'ideabot', display_name: 'Idea Bot', scopes: ['read', 'write']});
  check(ag.id > 0 && ag.token, 'setup: an agent');
  const L2 = (await call('POST', '/api/lists', {name: 'Not shared'})).id;
  await call('PATCH', '/api/lists/' + L2, {view: 'mindmap'});
  w = await boot({user: 'alice', hash: 'l/' + L2}); d = w.document;
  await until(() => d.querySelector('#view .mmstage'));
  await w.eval('mm_ideaAgents()');
  const it0 = w.eval(`JSON.stringify(mm_ideasItem(mm_node('r')))`);
  check(/"dis":true/.test(it0) && /Share this list with a connected agent/.test(it0), '#1201: no agent of the list: greyed with the hint ' + it0);
  w.close();
  const shr = await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const agl = await call('GET', `/api/proposals/agents?kind=ideas&list_id=${L}`);
  check((agl.agents || []).some(x => x.id === ag.id), 'setup: the list is shared with the agent, it can be asked ' + JSON.stringify({shr, agl}).slice(0, 300));
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  await until(() => d.querySelector(`#view [data-mmn="t${A2}"]`));
  w.eval(`mm_select('t${A2}')`);
  w.__dialogs = 'manual';  // the dialog is checked and answered here (boot.js dialogBridge)
  key(w, stage(), 'i');
  const dlg = await until(() => d.querySelector('.cdlg #cdlg-in'));
  check(dlg && /gets the path of this branch and the name of the list, nothing else/.test(d.querySelector('.cdlg').textContent), '#1201: I opens the request with what the agent gets ' + toastText(d) + ' ' + (d.querySelector('.cdlg')?.textContent || '').slice(0, 200));
  if (dlg) { dlg.value = 'Pages for a small shop'; d.querySelector('.cdlg form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); }
  w.__dialogs = undefined;
  const job = await until(async () => (await call('GET', `/api/lists/${L}/ideas`)).jobs?.[0]);
  check(job && job.state === 'requested' && job.target === 't' + A2, '#1201: the request is there: ' + JSON.stringify(job));
  check(await until(() => d.querySelector('#view .mmnode.ideawait') && d.querySelector('#view .mmideas [data-mm="ideas-stop"]')), '#1201: the map shows the waiting request');
  const ans = await agent('POST', `/agent/jobs/${job.id}/proposal`, {items: [{title: 'Shop', children: [{title: 'Cart'}]}, {title: 'Contact'}]}, ag.token);
  check(ans.status === 201, '#1201: the agent answers ' + ans.status);
  await w.eval('mm_ideasLoad()');
  check(await until(() => d.querySelectorAll('#view .mmnode.idea').length === 3), '#1201: three pale branches (two ideas, one sub-idea)');
  check(/Take all/.test(d.querySelector('#view .mmideas')?.textContent || ''), '#1201: the line above the map offers "Take all"');
  const shop = w.eval(`MM.last.L.nodes.find(n => n.kind === 'idea' && n.title === 'Shop').id`);
  d.querySelector(`#view [data-mm="idea-take"][data-n="${shop}"]`)?.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  const made = await until(async () => (await tasks()).find(t => t.title === 'Shop'));
  check(made && made.parent_id === A2, '#1201: ✓ takes the idea over as a task under the branch');
  check(await until(() => d.querySelector(`#view [data-mmn="t${made?.id}"]`) && w.eval(`MM.last.L.nodes.some(n => n.kind === 'idea' && n.title === 'Cart' && n.parent.id === 't${made?.id}')`)),
    '#1201: its sub-idea now hangs at the new task');
  // the phone's sheet of an idea
  const sheet = w.eval(`(() => { let got = null; const m0 = menu; menu = (a, its) => { got = its; }; mm_nodeMenu(null, MM.last.L.nodes.find(n => n.kind === 'idea' && n.title === 'Cart')); menu = m0; return got.filter(x => x && x.label).map(x => x.label).join('|'); })()`);
  check(/Take over/.test(sheet) && /Discard/.test(sheet) && /Take all/.test(sheet), '#1201: the sheet of an idea: ' + sheet);
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await tasks()).some(t => t.title === 'Shop')), '#1201: Undo removes the idea taken over');
  d.querySelector('#view .mmideas [data-mm="ideas-drop"]')?.click();
  check(await until(async () => !(await call('GET', `/api/lists/${L}/ideas`)).jobs.length), '#1201: "Discard all" ends the request');
  check(await until(() => !d.querySelector('#view .mmnode.idea') && !d.querySelector('#view .mmideas')), '#1201: no pale branches left');
  // the bell: "Proposal ready" of kind ideas opens the list as a mind map
  const r2 = await call('POST', '/api/proposals', {kind: 'ideas', agent_id: ag.id, list_id: L, branch: 'r'});
  await agent('POST', `/agent/jobs/${r2.id}/proposal`, {items: [{title: 'Newsletter'}]}, ag.token);
  w.location.hash = 'today'; await sleep(300);
  await w.eval(`propOpen(${r2.id})`);
  check(await until(() => /#l\/\d+/.test(w.location.hash) && +w.location.hash.split('/')[1] === L && d.querySelector('#view .mmstage')), '#1201: the bell opens the list as a mind map');
  check(await until(() => [...d.querySelectorAll('#view .mmnode.idea')].some(g => /Newsletter/.test(g.textContent))), '#1201: with the idea');
  w.close();

  // ================= phone: compact properties, the outline
  await call('POST', '/api/tasks', {title: 'Long tags', list_id: L, tags: ['alpha-long-tag', 'beta-long-tag', 'gamma-long-tag', 'delta-long-tag'], due: '2030-06-01'});
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true, rowIcons: 'all', ls: {'tasks.mmProps': JSON.stringify({[L]: 1})}}); d = w.document;
  check(await until(() => d.querySelector('#view .mmstage .mmprops')), 'phone: properties remembered');
  const lt = w.eval(`(() => { const n = MM.last.L.nodes.find(x => x.title === 'Long tags'); return {w: n.w, txt: document.querySelector('#view [data-mmn="' + n.id + '"] .mmprops').textContent}; })()`);
  check(lt.w <= 240 && /…/.test(lt.txt), 'phone: a long line ends in … ' + JSON.stringify(lt));
  w.close();

  // ================= Firefox: the real layout + screenshots
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.mmProps', JSON.stringify({${L}: 1})); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    const r3 = await call('POST', '/api/proposals', {kind: 'ideas', agent_id: ag.id, list_id: L, branch: 't' + A3});
    await agent('POST', `/agent/jobs/${r3.id}/proposal`, {items: [{title: 'About us'}, {title: 'Imprint'}]}, ag.token);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + '#l/' + L);
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .mmstage .mmnode.idea")').catch(() => false)); i++) await sleep(300);
    check(await ev('!!document.querySelector("#view .mmstage .mmprops")'), 'Firefox 1280: properties and ideas on the map');
    await shot('p2156a-mindmap-1280.png');
    const OVER = `(() => { const vw = document.documentElement.clientWidth, bad = [...document.querySelectorAll('#view *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1 && !e.closest('.mmcanvas, .vsegm'); }).map(e => e.className.baseVal ?? e.className).slice(0, 5); return {vw, sw: document.documentElement.scrollWidth, bad}; })()`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#l/' + L);
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .mmstage [data-mmn]")').catch(() => false)); i++) await sleep(300);
    const o = await ev(OVER);
    check(o.sw <= o.vw + 1 && !o.bad.length, '390 px: the map, its bar and the ideas line inside the screen ' + JSON.stringify(o));
    await shot('p2156a-mindmap-390.png');
    await ev(`(() => { document.querySelector('#view [data-mm="as-outline"]').click(); return 1; })()`);
    await sleep(500);
    const o2 = await ev(OVER);
    check(o2.sw <= o2.vw + 1 && !o2.bad.length, '390 px: the outline with properties inside the screen ' + JSON.stringify(o2));
    await shot('p2156a-outline-390.png');
  }, true);

  console.log(`p2156_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
