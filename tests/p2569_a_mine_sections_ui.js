// kalmido-suite: fresh
// 2.569.0 A (#4395) "My tasks" with own sections (mineorder.js mse*, /api/mine-sections). jsdom, own container (start.sh):
// - "My tasks" is in the sidebar also alone (no collaboration); in German it is called "Meine Aufgaben", the filter
//   "Assigned to me" stays "Mir zugewiesen"
// - the first opening shows "Recently assigned" (tasks without a place) and the made sections Now / Soon / Someday
// - a task due today or overdue goes into Now by itself; one dragged by hand stays where it was put (hand wins)
// - dragging onto a section head or a row of it, a new section ("New section"), renaming, folding (kept on the server)
// - deleting a section: its tasks fall into the topmost section; after deleting Now nothing moves any more
// - the list's own order and sections stay untouched
// Firefox 320 x 640 (touch): the section heads, their "…" and "New section" inside the screen, no sideways scrolling.
// freelancer-matrix: tasks - frida has no organisation.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2569_a_mine_sections_ui', check, shots: 'P2569A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 150});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments'});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const L = (await call(CF, 'POST', '/api/lists', {name: 'Home'})).id;
  const SEC = (await call(CF, 'POST', '/api/sections', {list_id: L, name: 'Backlog'})).id;
  const mk = async (title, b = {}) => (await call(CF, 'POST', '/api/tasks', {title, list_id: L, section_id: SEC, ...b})).id;
  const TA = await mk('Pay the rent', {due: '2020-01-02'});  // overdue: Now by itself
  const TB = await mk('Water the plants'), TC = await mk('Book a trip'), TE = await mk('Old overdue', {due: '2020-01-03'});
  const list0 = JSON.stringify((await call(CF, 'GET', '/api/state')).tasks.filter(t => t.list_id === L).map(t => [t.id, t.sort, t.section_id]));

  let w = await boot({user: 'frida', hash: 'assigned'}), d = w.document;
  check(await until(() => d.querySelector('#side [data-go="assigned"]')), '(5) alone: "My tasks" in the sidebar');
  const heads = () => [...d.querySelectorAll('#view .ghead[data-key^="ms:"]')];
  const head = re => heads().find(x => re.test(x.textContent));
  const inSec = (re, id) => !!head(re)?.closest('.group')?.querySelector(`.trow[data-id="${id}"]`);
  check(await until(() => head(/\bNow\b/) && head(/Soon/) && head(/Someday/)), '(6) Now, Soon, Someday made at the first opening ' + heads().map(x => x.textContent.trim()).join(' | '));
  check(head(/Recently assigned/) && heads()[0] === head(/Recently assigned/), '(3) "Recently assigned" on top');
  check(inSec(/Recently assigned/, TB) && inSec(/Recently assigned/, TC), '(3) tasks without a place stand in "Recently assigned"');
  check(inSec(/\bNow\b/, TA) && inSec(/\bNow\b/, TE), '(7) overdue tasks in Now by themselves');
  check(!head(/Recently assigned/).querySelector('[data-mse-menu]') && head(/Soon/).querySelector('[data-mse-menu]'), '"Recently assigned" has no "…", own sections have one');
  check(d.querySelector(`#view .trow[data-id="${TB}"] .mosub`), '(4) the origin "List › Section" stays');

  // drag onto a head, onto a row
  const key = re => head(re).dataset.key, sid = re => +key(re).slice(3);
  await w.eval(`dropTask(${TB}, document.querySelector('#view .ghead[data-key="${key(/Soon/)}"]'), 0)`);
  check(await until(() => inSec(/Soon/, TB)), 'dragged onto the head of Soon: there');
  await w.eval(`dropTask(${TA}, document.querySelector('#view .ghead[data-key="${key(/Recently assigned/)}"]'), 0)`);
  check(inSec(/\bNow\b/, TA) && !w.eval('OUT.q.length'), '"Recently assigned" takes no task (the drop has ended, nothing was sent)');
  await w.eval(`dropTask(${TC}, document.querySelector('#view .trow[data-id="${TB}"]'), 0)`);
  check(await until(() => inSec(/Soon/, TC)), 'dragged onto a row of Soon: there too');
  const S1 = await until(async () => { const s = (await call(CF, 'GET', '/api/state')).mine_sections; return s.tasks[TB] === sid(/Soon/) && s.tasks[TC] === sid(/Soon/) && s; });
  check(S1, 'the server keeps both in Soon');
  await w.eval(`dropTask(${TA}, document.querySelector('#view .ghead[data-key="${key(/Someday/)}"]'), 0)`);
  check(await until(() => inSec(/Someday/, TA)) && !inSec(/\bNow\b/, TA), '(7) an overdue task dragged by hand stays where it was put');
  check(JSON.stringify((await call(CF, 'GET', '/api/state')).tasks.filter(t => t.list_id === L).map(t => [t.id, t.sort, t.section_id])) === list0, 'the list\'s order and sections untouched');

  // a new section, rename, fold
  w.prompt = () => 'Errands';
  click(w, d.querySelector('#view [data-mse-add]'));
  check(await until(() => head(/Errands/) && heads().at(-1) === head(/Errands/)), 'a new section at the end');
  w.prompt = () => 'This week';
  click(w, head(/Soon/).querySelector('[data-mse-menu]'));
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const mi = txt => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => b.textContent.trim() === txt);
  check(mi('Rename') && mi('Delete section (tasks stay)'), 'the "…" of a section: Rename, Delete');
  click(w, mi('Rename'));
  check(await until(() => head(/This week/) && inSec(/This week/, TB)), 'renamed, its tasks stay');
  check(await until(async () => (await call(CF, 'GET', '/api/state')).mine_sections.list.find(x => x.kind === 'soon')?.name === 'This week'), 'the new name on the server');
  click(w, head(/This week/));
  check(await until(() => head(/This week/).classList.contains('closed') && !inSec(/This week/, TB)), 'folded: no rows');
  check(await until(async () => (await call(CF, 'GET', '/api/state')).mine_sections.list.find(x => x.kind === 'soon')?.collapsed === true), 'the folding on the server (every device)');
  click(w, head(/This week/));
  await until(() => inSec(/This week/, TB));

  // delete Someday: TA falls into the topmost section (Now)
  click(w, head(/Someday/).querySelector('[data-mse-menu]'));
  await until(() => mi('Delete section (tasks stay)'));
  click(w, mi('Delete section (tasks stay)'));
  check(await until(() => !head(/Someday/) && inSec(/\bNow\b/, TA)), 'deleted: its task in the topmost section');
  // TE: placed by the drag above (shown in Now), not by hand; delete Now -> no more moving, TE into the topmost left
  click(w, head(/\bNow\b/).querySelector('[data-mse-menu]'));
  await until(() => mi('Delete section (tasks stay)'));
  click(w, mi('Delete section (tasks stay)'));
  check(await until(() => !head(/\bNow\b/) && heads().length), 'Now deleted');
  const top = () => heads().find(x => !/Recently assigned/.test(x.textContent));
  check(await until(() => top() && /This week/.test(top().textContent) && top().closest('.group').querySelector(`.trow[data-id="${TE}"]`) && top().closest('.group').querySelector(`.trow[data-id="${TA}"]`)),
    '(7) without Now: the overdue tasks stay in the topmost section, nothing moves them ' + heads().map(x => x.textContent.trim()).join(' | '));
  // (4) desktop: the project as a column instead of the grey line (this device)
  const pc = () => w.eval(`topMoreItems().find(x => x.label === 'Project as a column')`);
  check(pc() && !pc().on, '(4) "…" offers "Project as a column"');
  w.eval(`topMoreItems().find(x => x.label === 'Project as a column').fn()`);
  // 2.750.0 (#4502): My tasks has the column titles of the collected views; its column Project (.lc-list) names the project
  const pcol = () => d.querySelector(`#view .trow[data-id="${TB}"] .c-list, #view .trow[data-id="${TB}"] .lc-list`);
  check(await until(() => (pcol()?.textContent || '').includes('Home') && !d.querySelector(`#view .trow[data-id="${TB}"] .mosub`)), '(4) the column "Project", no grey line ' + (pcol()?.textContent || ''));
  w.eval(`topMoreItems().find(x => x.label === 'Project as a column').fn()`);
  check(await until(() => d.querySelector(`#view .trow[data-id="${TB}"] .mosub`)), '(4) off again: the grey line "List › Section"');
  const TF = await mk('Brand new overdue', {due: '2020-01-04'});
  await w.eval('load().then(render)');
  check(await until(() => inSec(/Recently assigned/, TF)), '(7) without Now a new overdue task stands in "Recently assigned"');
  w.close();

  // (1) German: "Meine Aufgaben", the filter "Mir zugewiesen"
  await call(CF, 'PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'frida', hash: 'assigned'}); d = w.document;
  check(await until(() => /Meine Aufgaben/.test(d.querySelector('#side [data-go="assigned"]')?.textContent || '')), '(1) the sidebar says "Meine Aufgaben"');
  const DE = require('../static/i18n/de.json');
  check(DE['My tasks'] === 'Meine Aufgaben' && DE['Assigned to me'] === 'Mir zugewiesen', '(1) view "Meine Aufgaben", the filter stays "Mir zugewiesen"');
  check(await until(() => heads().some(x => /Zuletzt zugewiesen/.test(x.textContent))), '(1) "Zuletzt zugewiesen" in German');
  w.close();
  await call(CF, 'PATCH', '/api/settings', {lang: 'en'});
  // the defaults again for the phone: a fresh person
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CI = await login('fiona');
  await call(CI, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const LI = (await call(CI, 'POST', '/api/lists', {name: 'A rather long project name for a small screen'})).id;
  const FI = (await call(CI, 'GET', '/api/state')).me.id;  // assigned to her: "My tasks" with collaboration on
  for (const t of ['Call the plumber about the kitchen sink', 'Renew the passport']) await call(CI, 'POST', '/api/tasks', {title: t, list_id: LI, assignee_id: FI});
  await call(CI, 'POST', '/api/tasks', {title: 'Overdue invoice', list_id: LI, due: '2020-01-02', assignee_id: FI});

  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'fiona', password: 'password123'})}).then(r => r.status)`) === 200, 'login fiona');
    await nav(B + '#assigned');
    const there = await ready(`document.querySelectorAll('#view .ghead[data-key^="ms:"]').length >= 4 && !!document.querySelector('#view [data-mse-add]')`);
    if (!there) await o.shot('p2569a-320-missing.png');
    check(there, '320 px: the sections are there ' + await ev(`JSON.stringify({h: location.hash, k: S.route?.key, m: S.route?.mod, own: typeof moOwn === 'function' && moOwn(), secs: S.mineSecs?.list?.length, heads: [...document.querySelectorAll('#view .ghead')].map(x => x.dataset.key), add: !!document.querySelector('#view [data-mse-add]')})`).catch(e => String(e)));
    const box = await ev(`(() => { const b = e => { const x = e.getBoundingClientRect(); return {l: Math.round(x.left), r: Math.round(x.right)}; };
      return {vw: innerWidth, sw: document.documentElement.scrollWidth, heads: [...document.querySelectorAll('#view .ghead[data-key^="ms:"]')].map(b),
        dots: [...document.querySelectorAll('#view [data-mse-menu]')].map(b), add: b(document.querySelector('#view [data-mse-add]'))}; })()`);
    check(box && box.sw <= box.vw + 1, '320 px: no sideways scrolling ' + JSON.stringify(box && [box.sw, box.vw]));
    check(box && box.heads.every(x => x.l >= 0 && x.r <= box.vw + 1) && box.dots.length >= 3 && box.dots.every(x => x.l >= 0 && x.r <= box.vw + 1), '320 px: the heads and their "…" inside the screen ' + JSON.stringify(box && box.dots));
    check(box && box.add.l >= 0 && box.add.r <= box.vw + 1, '320 px: "New section" inside the screen');
    check(await ev(`!!document.querySelector('#view .ghead[data-key^="ms:"]') && [...document.querySelectorAll('#view .ghead[data-key^="ms:"]')].find(x => /Now/.test(x.textContent))?.closest('.group')?.querySelector('.trow') !== null`), '320 px: the overdue task in Now');
    await o.shot('p2569a-320.png');
  }, true);

  console.log(`p2569_a_mine_sections_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
