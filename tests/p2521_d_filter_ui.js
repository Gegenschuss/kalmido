// kalmido-suite:
// 2.521.0 D (#4479, #4478) UI tests (own container, start.sh): the filter dialog as condition rows, jsdom + Firefox. Invented
// names only. A person without an organisation (frida), folder "Kunden" with the subfolder "Kunden/Nord", one project outside:
// - filterMatch, new rules {op, conds}: folder with its subfolders, folder empty, "is none of" holds on top also with OR,
//   "does not contain", a custom field by name in every project with such a field (select by option name), numbers
// - the old rules of every kind (lists, dates, prios, types, tags, who, secs, sprints, ms, dlv, text, cf sel / chk / date / num,
//   AND and OR) hit exactly the same tasks as the matcher before 2.521.0 (its copy below), also after the dialog saved them
// - the dialog: starts empty, "+ Condition" adds a row (what / comparison / value / x), one entry per same-named field, the
//   value menu (search, a check per value, stays open), the live count "N tasks match", the column list follows the chosen
//   projects, saving stores {op, conds}, reopening shows the rows, x removes one
// - Firefox, 320 px wide: the rows wrap inside the dialog, nothing sticks out
// freelancer-matrix: tasks (a person without an organisation, the own projects and folders)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2521_d_filter_ui', check, shots: 'P2521D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2521D_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const until = async (fn, n = 80) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
// the matcher before 2.521.0 (static/js/views.js), the measure for "the same tasks"
const OLD = `function oldFilterMatch(t, r = {}) {
  const c = [];
  if (r.lists?.length) c.push(r.lists.includes(t.list_id));
  if (r.dates?.length) c.push(r.dates.some(d => dateMatch(t, d)));
  if (r.prios?.length) c.push(r.prios.includes(t.priority));
  if (r.types?.length) c.push(r.types.includes(t.ttype || ''));  // 2.4.0 (#340): '' = no type
  if (r.tags?.length) c.push(r.tags.some(g => hasTag(t, g)));
  for (const [fid, cr] of Object.entries(r.cf || {})) if (cfRuleOn(cr) && fieldById(+fid)) c.push(cfMatch(t, fid, cr));
  // 2.390.0 B (#3355): assignee (me | none | user id), column, sprint (cur = the list's active one | none = backlog),
  // milestone (id | none), text in title or notes
  if (r.who?.length) c.push(r.who.some(w => (w === 'none' ? !t.assignee_id : t.assignee_id === (w === 'me' ? S.me?.id : +w))));
  if (r.secs?.length) c.push(r.secs.some(s => (s === 'none' ? !t.section_id : t.section_id === +s)));
  if (r.sprints?.length) c.push(r.sprints.some(s => (s === 'none' ? !t.sprint_id : !!t.sprint_id && spr_active(listById(t.list_id))?.id === t.sprint_id)));
  if (r.ms?.length) c.push(r.ms.some(m => (m === 'none' ? !t.milestone_id : t.milestone_id === +m)));
  if (r.dlv?.length) c.push(r.dlv.includes(dv_state(t) || 'none'));  // 2.392.2 (#3365): the delivery state
  const q = (r.text || '').trim().toLowerCase();
  if (q) c.push((t.title || '').toLowerCase().includes(q) || (t.content || '').toLowerCase().includes(q));
  if (!c.length) return true;
  return r.op === 'or' ? c.some(Boolean) : c.every(Boolean);
}
`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'setup: frida has no organisation');
  const ME = st0.me.id;
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'kanban', 'progress', 'collab', 'fields'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const LA = (await call('POST', '/api/lists', {name: 'Alpha', kind: 'project', folder: 'Kunden'})).id;
  const LB = (await call('POST', '/api/lists', {name: 'Beta', kind: 'project', folder: 'Kunden/Nord'})).id;
  const LC = (await call('POST', '/api/lists', {name: 'Gamma', kind: 'project'})).id;
  const S1 = (await call('PUT', `/api/lists/${LA}/sprint-settings`, {on: true})).started_id;
  const SA = (await call('POST', '/api/sections', {list_id: LA, name: 'Doing'})).id;
  const SC = (await call('POST', '/api/sections', {list_id: LC, name: 'Later'})).id;
  const fld = (l, b) => call('POST', `/api/lists/${l}/fields`, b);
  const FA = await fld(LA, {name: 'Stufe', type: 'select', options: {options: [{name: 'Neu'}, {name: 'Alt'}]}});
  const FB = await fld(LB, {name: 'Stufe', type: 'select', options: {options: [{name: 'neu'}, {name: 'Fertig'}]}});
  const FN = await fld(LA, {name: 'Budget', type: 'number'});
  const FK = await fld(LA, {name: 'Ok', type: 'checkbox'});
  const FD = await fld(LA, {name: 'Abgabe', type: 'date'});
  const st1 = await call('GET', '/api/state');
  const fid = n => st1.fields.find(f => f.list_id === n[0] && f.name === n[1]);
  const fa = fid([LA, 'Stufe']), fb = fid([LB, 'Stufe']), fn = fid([LA, 'Budget']), fk = fid([LA, 'Ok']), fdd = fid([LA, 'Abgabe']);
  const oa = Object.fromEntries(fa.options.options.map(o => [o.name, o.id])), ob = Object.fromEntries(fb.options.options.map(o => [o.name, o.id]));
  check(FA.http < 300 && FB.http < 300 && FN.http < 300 && FK.http < 300 && FD.http < 300 && oa.Neu && ob.neu, `setup: fields ${[FA.http, FB.http, FN.http, FK.http, FD.http]}`);
  const mk = b => call('POST', '/api/tasks', b).then(j => j.id);
  const today = new Date().toISOString().slice(0, 10);
  const T = {
    a1: await mk({list_id: LA, title: 'Alpha one', priority: 5, assignee_id: ME, section_id: SA, sprint_id: S1, tags: ['eilig'], due: today}),
    a2: await mk({list_id: LA, title: 'Alpha two', content: 'old notes', priority: 1}),
    b1: await mk({list_id: LB, title: 'Beta alpha', priority: 3, tags: ['eilig']}),
    c1: await mk({list_id: LC, title: 'Gamma alpha', section_id: SC}),
    c2: await mk({list_id: LC, title: 'Gamma two', ttype: 'bug'}),
  };
  T.m = await mk({list_id: LA, title: 'Release', ms: 1, due: '2027-03-01'});
  await call('PATCH', `/api/tasks/${T.a2}`, {milestone_id: T.m});
  await call('PATCH', `/api/tasks/${T.a1}`, {fields: {[fa.id]: oa.Neu, [fn.id]: '1200', [fk.id]: '1', [fdd.id]: today}});
  await call('PATCH', `/api/tasks/${T.a2}`, {fields: {[fa.id]: oa.Alt, [fn.id]: '50'}});
  await call('PATCH', `/api/tasks/${T.b1}`, {fields: {[fb.id]: ob.neu}});
  check(Object.values(T).every(Boolean), `setup: tasks ${JSON.stringify(T)}`);

  const w = await boot({user: 'frida', hash: 'today'}), d = w.document;
  check(await until(() => typeof w.filterModal === 'function' && w.taskById(T.b1) && w.taskById(T.a1)?.fields?.[fa.id]), 'the app is there');
  w.eval(OLD);
  const hits = r => w.eval(`[${Object.values(T).join(',')}].filter(id => filterMatch(taskById(id), ${JSON.stringify(r)}))`);
  const ids = (...k) => k.map(x => T[x]).sort((a, b) => a - b).join(',');
  const got = r => hits(r).sort((a, b) => a - b).join(',');
  const C = (op, ...conds) => ({op, conds});
  // folders (#4478): a folder holds its subfolders
  check(got(C('and', {f: 'folder', op: 'in', v: ['Kunden']})) === ids('a1', 'a2', 'b1', 'm'), `folder Kunden with Kunden/Nord: ${got(C('and', {f: 'folder', op: 'in', v: ['Kunden']}))}`);
  check(got(C('and', {f: 'folder', op: 'in', v: ['Kunden/Nord']})) === ids('b1'), 'the subfolder alone');
  check(got(C('and', {f: 'folder', op: 'empty'})) === ids('c1', 'c2'), 'folder empty: the project outside');
  check(got(C('and', {f: 'folder', op: 'in', v: ['Kund']})) === '', 'a folder is a path, not a text prefix');
  // "is none of" holds on top, also with OR (#4478)
  const orx = C('or', {f: 'text', op: 'has', v: 'alpha'}, {f: 'list', op: 'nin', v: [LA]});
  check(got(orx) === ids('b1', 'c1'), `OR + none of a project: ${got(orx)}`);
  const orf = C('or', {f: 'prio', op: 'in', v: [5, 3]}, {f: 'text', op: 'has', v: 'gamma'}, {f: 'folder', op: 'nin', v: ['Kunden/Nord']});
  check(got(orf) === ids('a1', 'c1', 'c2'), `OR + none of a folder: ${got(orf)}`);
  check(got(C('or', {f: 'list', op: 'nin', v: [LC]})) === ids('a1', 'a2', 'b1', 'm'), 'only a "none of": everything else');
  check(got(C('and', {f: 'text', op: 'nhas', v: 'ALPHA'}, {f: 'list', op: 'in', v: [LA, LC]})) === ids('c2', 'm'), 'does not contain (title, any case)');
  check(got(C('and', {f: 'text', op: 'nhas', v: 'old'})).split(',').length === 5 && !hits(C('and', {f: 'text', op: 'nhas', v: 'old'})).includes(T.a2), 'does not contain: also the notes');
  check(got(C('and', {f: 'tag', op: 'empty'})) === ids('a2', 'c1', 'c2', 'm') && got(C('and', {f: 'sec', op: 'empty'})) === ids('a2', 'b1', 'c2', 'm'), 'tag / column empty');
  check(got(C('and', {f: 'list', op: 'in', v: []})) === ids('a1', 'a2', 'b1', 'c1', 'c2', 'm'), 'a row without values is off');
  // a custom field by name: every project with such a field, the option by its name (any case)
  check(got(C('and', {f: 'cf', name: 'stufe', ft: 'select', op: 'in', v: ['Neu']})) === ids('a1', 'b1'), `Stufe = Neu in Alpha and Beta: ${got(C('and', {f: 'cf', name: 'stufe', ft: 'select', op: 'in', v: ['Neu']}))}`);
  check(got(C('and', {f: 'cf', name: 'Stufe', ft: 'select', op: 'nin', v: ['Neu']})) === ids('a2', 'c1', 'c2', 'm'), 'Stufe none of Neu (projects without the field too)');
  check(got(C('and', {f: 'cf', name: 'Stufe', ft: 'select', op: 'empty'})) === ids('m'), 'Stufe empty: only where the field exists');
  check(got(C('and', {f: 'cf', name: 'Budget', ft: 'number', op: 'gt', v: 100})) === ids('a1') && got(C('and', {f: 'cf', name: 'Budget', ft: 'number', op: 'empty'})) === ids('m'), 'number greater than / empty');

  // the old rules of every kind: the same tasks as before
  const OLDR = [
    {lists: [LA]}, {lists: [LA, LC], op: 'or', prios: [5]}, {dates: ['today', 'nodate']}, {dates: ['later'], op: 'or', tags: ['eilig']}, {prios: [0, 1]},
    {types: ['bug']}, {types: ['']}, {tags: ['eilig'], who: ['me']}, {who: ['none']}, {who: [String(ME)]}, {secs: [String(SA), 'none']}, {secs: ['none'], op: 'or', ms: [String(T.m)]},
    {sprints: ['cur']}, {sprints: ['none'], lists: [LA]}, {ms: ['none']}, {dlv: ['none']}, {dlv: ['parked']}, {text: 'ALPHA'}, {text: '  '},
    {cf: {[fa.id]: {sel: [oa.Neu]}}}, {cf: {[fa.id]: {sel: ['']}}}, {cf: {[fb.id]: {sel: [ob.neu]}}, op: 'or', lists: [LC]}, {cf: {[fk.id]: {chk: ['0']}}},
    {cf: {[fdd.id]: {date: ['today']}}}, {cf: {[fn.id]: {num: {op: 'gt', v: '100'}}}}, {cf: {[fn.id]: {num: {op: 'empty'}}}}, {cf: {[fn.id]: {num: {op: 'set'}}}, op: 'or', text: 'gamma'},
    {cf: {[fn.id]: {num: {op: 'lt', v: ''}}}}, {cf: {99999: {sel: ['x']}}}, {cf: {[fa.id]: {sel: []}}}, {},
    {op: 'or', lists: [LB], dates: ['today'], prios: [1], types: ['bug'], tags: ['eilig'], who: ['me'], secs: [String(SC)], sprints: ['cur'], ms: [String(T.m)], dlv: ['none'], text: 'two', cf: {[fn.id]: {num: {op: 'eq', v: '50'}}}},
  ];
  const all = Object.values(T).join(',');
  const same = r => w.eval(`(() => { const r = ${JSON.stringify(r)}, ts = [${all}].map(taskById); const a = ts.filter(t => oldFilterMatch(t, r)).map(t => t.id).join(), b = ts.filter(t => filterMatch(t, r)).map(t => t.id).join(), c = ts.filter(t => filterMatch(t, {op: r.op, conds: flt_conds(r)})).map(t => t.id).join(); return a === b && b === c ? 'ok' : a + ' | ' + b + ' | ' + c; })()`);
  for (const r of OLDR) { const x = same(r); check(x === 'ok', `old rules ${JSON.stringify(r)}: old | new | converted ${x}`); }

  // the dialog: an old filter (cf + lists) opens converted and, saved without a change, still hits the same tasks
  const OF = {op: 'or', lists: [LC], cf: {[fa.id]: {sel: [oa.Alt]}}, text: 'beta'};
  const of = (await call('POST', '/api/filters', {name: 'Alt', rules: OF})).id;
  await w.eval('load()'); await until(() => w.eval(`S.filters.some(f => f.id === ${of})`));
  const before = got(OF);
  w.eval(`filterModal(${of})`);
  let md = await until(() => [...d.querySelectorAll('.modal')].find(x => x.querySelector('#f-conds .fcond')));
  check(md && md.querySelectorAll('.fcond').length === 3, `an old filter opens as rows: ${md && md.querySelectorAll('.fcond').length}`);
  check(md && [...md.querySelectorAll('.fc-f')].map(s => s.value).join() === `list,cfid|${fa.id},text`, `its rows: ${md && [...md.querySelectorAll('.fc-f')].map(s => s.value)}`);
  click(w, md.querySelector('[data-m="save"]'));
  const sv = await until(async () => { const f = ((await call('GET', '/api/state')).filters || []).find(x => x.id === of); return f && Array.isArray(f.rules.conds) && f; });
  check(sv && sv.rules.op === 'or' && sv.rules.conds.length === 3, `saved as conditions ${JSON.stringify(sv && sv.rules)}`);
  check(sv && got(sv.rules) === before, `the same tasks after saving: ${before} -> ${sv && got(sv.rules)}`);
  await until(() => !d.querySelector('.modal #f-conds'));

  // a new filter: empty, "+ Condition", the rows
  w.eval('filterModal()');
  md = await until(() => d.querySelector('.modal #f-conds') && d.querySelector('.modal #f-conds').closest('.modal'));
  const cnt = () => md.querySelector('#f-count').textContent;
  check(md && !md.querySelector('.fcond') && md.querySelector('[data-m="cond-add"]'), 'a new filter starts empty with "+ Condition"');
  check(/\b6 tasks match\b/.test(cnt()), `the count without a row: ${cnt()}`);
  click(w, md.querySelector('[data-m="cond-add"]'));
  const row = (i = 0) => md.querySelectorAll('.fcond')[i];
  check(row() && row().querySelector('.fc-f') && row().querySelector('.fc-op') && row().querySelector('.fc-v') && row().querySelector('.fc-x'), 'a row: what / comparison / value / x');
  check(d.activeElement === row().querySelector('.fc-f'), 'the new row has the focus');
  const whats = [...row().querySelectorAll('.fc-f option')].map(o => o.textContent);
  check(['Project', 'Folder', 'Date', 'Priority', 'Tag', 'Assignee', 'Column', 'Sprint', 'Milestone', 'Delivery state', 'Text'].every(x => whats.includes(x)), `what: ${whats}`);
  check(whats.filter(x => x === 'Stufe').length === 1 && whats.includes('Budget'), `one entry per same-named field: ${whats}`);
  check([...row().querySelectorAll('.fc-op option')].map(o => o.value).join() === 'in,nin', 'project: is one of / is none of');
  change(w, row().querySelector('.fc-f'), 'folder');
  check([...row().querySelectorAll('.fc-op option')].map(o => o.textContent).join() === 'is one of,is none of,is empty', 'folder: one of / none of / empty');
  // the value menu: search, a check per value, stays open
  click(w, row().querySelector('.fc-v'));
  let pop = await until(() => { const p = d.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menuitemcheckbox"]') && p; });
  const item = t => [...pop.querySelectorAll('[role="menuitemcheckbox"]')].find(b => b.textContent.trim() === t);
  check(pop && item('Kunden') && item('Kunden / Nord'), `the folders in the menu: ${pop && [...pop.querySelectorAll('[role="menuitemcheckbox"]')].map(b => b.textContent.trim())}`);
  click(w, item('Kunden'));
  check(!pop.classList.contains('hidden') && item('Kunden').getAttribute('aria-checked') === 'true' && item('Kunden').querySelector('.mchk'), 'a value: checked, the menu stays open');
  check(/\b4 tasks match\b/.test(cnt()) && /Kunden/.test(row().querySelector('.fc-v').textContent), `the count follows at once: ${cnt()}`);
  w.eval('closePop()');
  // a second row: project none of Alpha, OR: the note on top
  click(w, md.querySelector('[data-m="cond-add"]'));
  change(w, row(1).querySelector('.fc-op'), 'nin');
  click(w, row(1).querySelector('.fc-v'));
  pop = await until(() => { const p = d.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menuitemcheckbox"]') && p; });
  click(w, [...pop.querySelectorAll('[role="menuitemcheckbox"]')].find(b => b.textContent.trim() === 'Alpha'));
  w.eval('closePop()');
  check(/\b1 task matches\b/.test(cnt()), `folder Kunden, none of Alpha: ${cnt()}`);
  click(w, md.querySelector('#f-op [data-op="or"]'));
  check(/\b1 task matches\b/.test(cnt()) && /always applies on top/.test(cnt()), `OR: "none of" still on top, the note says so: ${cnt()}`);
  // columns: only the chosen projects' columns
  click(w, md.querySelector('[data-m="cond-add"]'));
  change(w, row(2).querySelector('.fc-f'), 'list');
  click(w, row(2).querySelector('.fc-v'));
  pop = await until(() => { const p = d.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menuitemcheckbox"]') && p; });
  click(w, [...pop.querySelectorAll('[role="menuitemcheckbox"]')].find(b => b.textContent.trim() === 'Gamma'));
  w.eval('closePop()');
  click(w, md.querySelector('[data-m="cond-add"]'));
  change(w, row(3).querySelector('.fc-f'), 'sec');
  click(w, row(3).querySelector('.fc-v'));
  pop = await until(() => { const p = d.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menuitemcheckbox"]') && p; });
  const secs = [...pop.querySelectorAll('[role="menuitemcheckbox"]')].map(b => b.textContent.trim());
  check(secs.includes('Gamma › Later') && secs.at(-1) === 'No column' && secs.every(x => x === 'No column' || x.startsWith('Gamma › ')), `the columns of the chosen project only: ${secs}`);
  w.eval('closePop()');
  click(w, row(3).querySelector('.fc-x'));
  check(md.querySelectorAll('.fcond').length === 3, 'x removes the row');
  // a long value list has the menu's search; a text row and a field by name
  click(w, md.querySelector('[data-m="cond-add"]'));
  change(w, row(3).querySelector('.fc-f'), 'date');
  click(w, row(3).querySelector('.fc-v'));
  pop = await until(() => { const p = d.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('#mq-q') && p; });
  input(w, pop && pop.querySelector('#mq-q'), 'tomorrow');
  const vis = pop ? [...pop.querySelectorAll('[role="menuitemcheckbox"]')].filter(b => !b.hidden).map(b => b.textContent.trim()) : [];
  check(vis.join() === 'Tomorrow', `the search narrows the values: ${vis}`);
  w.eval('closePop()');
  change(w, row(3).querySelector('.fc-f'), 'text');
  check(row(3).querySelector('.fc-t') && [...row(3).querySelectorAll('.fc-op option')].map(o => o.value).join() === 'has,nhas', 'text: contains / does not contain');
  input(w, row(3).querySelector('.fc-t'), 'gamma');
  const sk = [...row(0).querySelectorAll('.fc-f option')].find(o => o.textContent === 'Stufe').value;
  click(w, md.querySelector('[data-m="cond-add"]'));
  change(w, row(4).querySelector('.fc-f'), sk);
  click(w, row(4).querySelector('.fc-v'));
  pop = await until(() => { const p = d.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menuitemcheckbox"]') && p; });
  const opts = [...pop.querySelectorAll('[role="menuitemcheckbox"]')].map(b => b.textContent.trim());
  check(opts.join('|') === 'Neu|Alt|Fertig|empty', `the options by name, once: ${opts}`);
  click(w, [...pop.querySelectorAll('[role="menuitemcheckbox"]')].find(b => b.textContent.trim() === 'Neu'));
  w.eval('closePop()');
  md.querySelector('#f-name').value = 'Zeilen';
  click(w, md.querySelector('[data-m="save"]'));
  const nf = await until(async () => ((await call('GET', '/api/state')).filters || []).find(x => x.name === 'Zeilen'));
  const cs = nf && nf.rules.conds;
  check(nf && nf.rules.op === 'or' && cs.length === 5 && !('lists' in nf.rules), `saved as {op, conds}: ${JSON.stringify(nf && nf.rules)}`);
  check(cs && JSON.stringify(cs[0]) === '{"f":"folder","op":"in","v":["Kunden"]}' && JSON.stringify(cs[1]) === `{"f":"list","op":"nin","v":[${LA}]}`, `the rows as stored ${JSON.stringify(cs)}`);
  check(cs && cs[4].f === 'cf' && cs[4].name === 'Stufe' && cs[4].ft === 'select' && cs[4].v.join() === 'Neu' && !cs[4].fid, `a field by name ${JSON.stringify(cs && cs[4])}`);
  check(nf && got(nf.rules) === ids('b1', 'c1', 'c2'), `the saved filter's tasks: ${nf && got(nf.rules)}`);
  check(await until(() => w.location.hash === '#f/' + (nf && nf.id)), `the saved filter opens ${w.location.hash}`);
  check(await until(() => d.querySelectorAll('#view .trow').length === 3), `the view shows its 3 tasks: ${d.querySelectorAll('#view .trow').length}`);
  w.eval(`filterModal(${nf && nf.id})`);
  md = await until(() => [...d.querySelectorAll('.modal')].find(x => x.querySelector('#f-conds .fcond')));
  check(md && md.querySelectorAll('.fcond').length === 5 && md.querySelector('.fc-t').value === 'gamma' && md.querySelector('#f-op [data-op="or"]').classList.contains('on'), 'reopened: the rows and OR kept');
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));

  // Firefox, 320 px: the rows wrap inside the dialog
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#today');
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    check(await ready(`typeof filterModal === 'function' && S.filters.length > 1`), 'Firefox: the app is there');
    await ev(`(() => { filterModal(${nf && nf.id}); return 1; })()`);
    check(await ready(`document.querySelectorAll('.modal .fcond').length === 5`), 'Firefox: the dialog with its rows');
    const lay = await ev(`(() => { const m = document.querySelector('.modal .fconds'), r = m.getBoundingClientRect(); const bad = [...m.querySelectorAll('.fcond > *')].filter(x => { const b = x.getBoundingClientRect(); return b.right > r.right + 1 || b.left < r.left - 1; }).length; const rows = [...m.querySelectorAll('.fcond')].map(x => x.getBoundingClientRect().height); return JSON.stringify({bad, w: innerWidth, sw: document.documentElement.scrollWidth, wrap: rows.some(h => h > 50)}); })()`);
    const L = JSON.parse(lay || '{}');
    check(L.bad === 0 && L.sw <= 320 && L.wrap, `Firefox 320 px: nothing sticks out, the rows wrap ${lay}`);
    await shot('p2521d-320');
  });

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
