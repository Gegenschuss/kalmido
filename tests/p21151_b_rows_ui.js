// 2.1151.0 B UI tests (#3835 stage 2: tasks and projects), own container (start.sh). jsdom, invented data only, as a person
// kalmido-suite: fresh
// without an organisation. Phones: the rows have no symbols (kept in the page for screen readers), a long press opens the menu.
// - phone CSS: task rows (checklist put-back, trash buttons), section heads, comments: hidden like .sr on phones only
// - a task row held and let go unmoved opens the task's menu, "Select" on top; "Select" starts the selection; the
//   browser's menu event of a touch does the same (no selection at once any more)
// - a trash row: the long press opens Restore / Delete permanently; Restore brings the task back
// - a section head held: its whole menu, its "+" first, no up / down (the head drags); "+" opens the add sheet there
// - the project page: milestone and key link rows open their menu by a long press, "Edit" opens the dialog
// - a comment on the phone: the long press menu holds Reply, Save as task, Edit, Delete as well
// - the computer is unchanged: section menu with Move left / right, comment menu without the row buttons, pin in the row
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const items = d => [...d.querySelectorAll('#pop:not(.hidden) [role^="menuitem"]:not([disabled])')].map(b => b.textContent.trim());
const pick = async (d, re) => { const it = await until(() => [...d.querySelectorAll('#pop:not(.hidden) [role^="menuitem"]')].find(b => re.test(b.textContent.trim()))); it?.click(); return !!it; };
const ptr = (w, el, type) => { const e = new w.MouseEvent(type, {bubbles: true, clientX: 5, clientY: 5}); Object.defineProperty(e, 'pointerType', {value: 'touch'}); el.dispatchEvent(e); };
const touch = (w, el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' ? [] : [{clientX: 20, clientY: 20}]; el.dispatchEvent(e); return e; };
// a finger held on el (drag.js: touch events; the hold of the tasks is 380 ms, of a section head 450 ms) and let go unmoved
const hold = async (w, el) => { touch(w, el, 'touchstart'); await sleep(560); return touch(w, el, 'touchend'); };
// a long press of multisel.js ms_longPress (pointer events, 500 ms)
const press = async (w, el) => { ptr(w, el, 'pointerdown'); await sleep(650); ptr(w, el, 'pointerup'); };
const closePop = w => w.eval('closePop()');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'kanban,comments,collab,progress'});
  const st = await call('GET', '/api/state');
  check(!(st.orgs || []).length, 'a person without an organisation');
  const L = (await call('POST', '/api/lists', {name: 'Garden', kind: 'project'})).id;
  const SA = (await call('POST', '/api/sections', {name: 'Spring', list_id: L})).id;
  const mk = async (title, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: L, ...extra})).id;
  const T1 = await mk('Cut the hedge along the whole north fence', {section_id: SA}), T2 = await mk('Plant tulips', {section_id: SA});
  const TX = await mk('Old idea');
  check((await call('DELETE', `/api/tasks/${TX}`)).http < 300, 'a task in the trash');
  const MS = await call('POST', `/api/lists/${L}/milestones`, {name: 'Harvest', day: '2027-09-01'});
  check(MS.http < 300, 'a milestone ' + MS.http);
  const LK = await call('POST', `/api/lists/${L}/links`, {title: 'Seed catalogue', url: 'https://example.org/seeds'});
  check(LK.http < 300, 'a key link ' + LK.http);
  const CM = await call('POST', `/api/tasks/${T1}/comments`, {body: 'Bring the long ladder'});
  check(CM.http < 300 && CM.id, 'a comment ' + CM.http);

  // ================= the phone rules (jsdom does not lay out: the rules themselves; the buttons stay in the page)
  const lists = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'start-00-lists.css'), 'utf8');
  check(/\(#3835\)[^\n]*\n@media \(max-width:767px\)\{\s*#view \.trow \.ckback,#view \.trow\.trtrash>\.iconbtn,#view \.ghead\[data-section\]:not\(\[data-section=""\]\) \.gact\{position:absolute!important;[^}]*clip-path:inset\(50%\)/.test(lists), 'phones: put-back, trash buttons and the section head\'s + and … leave the row (screen readers keep them)');
  const cmc = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'start-comments.css'), 'utf8');
  check(/\(#3835\)[^\n]*\n@media \(max-width:767px\)\{\s*\.cm \.cacts,[^{]*\.cm\.cacton \.cacts\{position:absolute!important;[^}]*clip-path:inset\(50%\)/.test(cmc), 'phones: a comment shows no symbols, not even after a tap');
  check(/\.ms-phsr\{position:absolute!important/.test(fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'start-phrows-3835.css'), 'utf8')), 'the shared .ms-phsr rule (project page, snippets, forms)');

  // ================= phone: a task row
  let w = await boot({hash: 'l/' + L, mobile: true, media: {'(hover: none)': true}}), d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  await until(() => row(T1));
  check(row(T1).querySelector('.ttl')?.textContent.includes('Cut the hedge along the whole north fence') && !row(T1).querySelector('.rpin'), 'phone: the row carries its full title and no pin symbol');
  check(row(T1).querySelector('.chk[data-act="toggle"]'), 'phone: the tick stays in the row');
  const te = await hold(w, row(T1).querySelector('.ttl'));
  const ti = await until(() => items(d).length && items(d));
  check(te.defaultPrevented && (ti || [])[0] === 'Select' && !w.eval('S.multiMode'), 'held and let go: the task menu, "Select" on top, nothing selected yet ' + ti);
  check(ti && ti.some(x => /^Delete/.test(x)) && !ti.some(x => /^Move (up|down)$/.test(x)), 'the menu holds the task\'s actions (Delete), no Move up / down on a touch screen ' + ti);
  check(await pick(d, /^Select$/) && await until(() => w.eval(`S.multiMode && S.multi.has(${T1}) && S.multi.size === 1`)), '"Select" starts the selection with this task');
  w.eval('S.multi.clear(); S.multiMode = false; render()'); await sleep(200);
  // the browser's menu event (Android: it can come instead of the app's own press)
  const ce = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}); Object.defineProperty(ce, 'pointerType', {value: 'touch'});
  row(T2).querySelector('.ttl').dispatchEvent(ce);
  check(ce.defaultPrevented && await until(() => items(d)[0] === 'Select') && !w.eval('S.multiMode'), 'the menu event of a touch opens the same menu');
  closePop(w); await sleep(150);

  // ================= phone: a section head
  const head = () => d.querySelector(`#view .ghead[data-section="${SA}"]`);
  check(head()?.querySelector('.gadd') && head()?.querySelector('[data-act="section-menu"]'), 'the head keeps its + and … in the page (screen readers)');
  const he = await hold(w, head());
  const hi = await until(() => items(d).length && items(d));
  check(he.defaultPrevented && /^Add a task to Spring$/.test((hi || [])[0] || '') && hi.includes('Rename') && hi.some(x => /^Delete section/.test(x)), 'held section head: its whole menu, its + first ' + hi);
  check(hi && !hi.some(x => /^Move (left|right|section)/.test(x)) && !hi.includes('Section menu…'), 'no up / down and no second level (the head drags) ' + hi);
  check(await pick(d, /^Add a task to Spring$/) && await until(() => d.querySelector('.qadd.sheet') && w.eval(`S.quickPreset?.section_id === ${SA}`)), 'its + opens the add sheet for that section');
  w.close();

  // ================= phone: the trash
  w = await boot({hash: 'trash', mobile: true, media: {'(hover: none)': true}}); d = w.document;
  const tr0 = await until(() => d.querySelector(`#view .trow.trtrash[data-id="${TX}"]`));
  check(tr0 && tr0.querySelector('[data-act="restore"]'), 'the trash row keeps its buttons in the page');
  await press(w, tr0.querySelector('.ttl') || tr0);
  const xi = await until(() => items(d).length && items(d));
  check(xi && xi.join('|') === 'Restore|Delete permanently', 'the trash row\'s long press: Restore, Delete permanently ' + xi);
  check(await pick(d, /^Restore$/) && await until(async () => !(await call('GET', `/api/tasks/${TX}`)).deleted_at), 'Restore brings the task back');
  w.close();

  // ================= phone: the project page
  w = await boot({hash: 'l/' + L, mobile: true, media: {'(hover: none)': true}}); d = w.document;
  await until(() => w.eval('typeof routeList === "function" && !!routeList()'));
  await w.eval(`setListView(routeList(), 'overview')`);
  const msr = await until(() => d.querySelector('#view .povm'));
  check(msr && msr.querySelector('[data-pov="ms-edit"].ms-phsr') && msr.querySelector('.chk'), 'milestone: the edit symbol leaves the phone row (screen readers keep it), the tick stays');
  await press(w, msr.querySelector('.pmn'));
  check(await until(() => items(d).join('|') === 'Edit'), 'milestone: the long press opens its menu ' + items(d));
  check(await pick(d, /^Edit$/) && await until(() => d.querySelector('.modal.povmodal')), 'its "Edit" opens the milestone dialog');
  d.querySelector('.modal.povmodal [data-m="close"], .modal.povmodal [data-m="cancel"]')?.click(); await sleep(200);
  const lkr = await until(() => d.querySelector('#view .povl .povla'));
  check(lkr && lkr.closest('.povl').querySelector('[data-pov="link-edit"].ms-phsr') && lkr.closest('.povl').querySelector('.rowgrip'), 'key link: the edit symbol leaves the phone row, the grip (drag) stays');
  await press(w, lkr);
  check(await until(() => items(d).join('|') === 'Edit'), 'key link: the long press opens its menu ' + items(d));
  closePop(w);
  w.close();

  // ================= phone: a comment
  w = await boot({hash: 't/' + T1, mobile: true, media: {'(hover: none)': true}}); d = w.document;
  const cmEl = await until(() => d.querySelector(`#d-tl-items .cm[data-cid="${CM.id}"]`));
  check(cmEl && cmEl.querySelector('.cacts [data-act="c-edit"]'), 'the comment keeps its buttons in the page');
  w.eval(`cmCopyMenu(document.querySelector('#d-tl-items .cm[data-cid="${CM.id}"] [data-act="cm-copy"]'), document.querySelector('#d-tl-items .cm[data-cid="${CM.id}"]'))`);
  const ci = await until(() => items(d).length && items(d));
  check(ci && ['Copy', 'Reply', 'Save as task', 'Edit', 'Delete'].every(x => ci.includes(x)), 'the comment\'s long press menu holds every row symbol ' + ci);
  check(await pick(d, /^Edit$/) && await until(() => d.querySelector(`.c-edit-input[data-cid="${CM.id}"]`)), 'its "Edit" opens the comment for editing');
  w.close();

  // ================= the computer: unchanged
  w = await boot({hash: 'l/' + L}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T1}"] .rpin`));
  check(d.querySelector(`#view .trow[data-id="${T1}"] .rpin`), 'computer: the row keeps its pin');
  w.eval(`sectionMenu(document.querySelector('#view .ghead[data-section="${SA}"]'), ${SA})`);
  const di = await until(() => items(d).length && items(d));
  check(di && di.includes('Move left / up') && di.includes('Move right / down'), 'computer: the section menu keeps Move left / right ' + di);
  closePop(w);
  w.close();
  w = await boot({hash: 't/' + T1}); d = w.document;
  await until(() => d.querySelector(`#d-tl-items .cm[data-cid="${CM.id}"] [data-act="cm-copy"]`));
  w.eval(`document.querySelector('#d-tl-items .cm[data-cid="${CM.id}"] [data-act="cm-copy"]').click()`);
  const dc = await until(() => items(d).length && items(d));
  check(dc && dc.includes('Copy') && !dc.includes('Reply') && !dc.includes('Delete'), 'computer: the comment\'s copy menu is as before ' + dc);
  w.close();

  console.log(`p21151_b_rows_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
