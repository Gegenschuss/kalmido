// kalmido-suite: fresh
// 2.823.0 (#4773) the own rules of "My tasks" (minerules.js, mineorder.js mrApply, /api/mine-rules). jsdom, own container (start.sh):
// - the overdue task lands in Now by the first rule (server), the view menu offers "Rules…", the dialog shows that rule as a sentence
// - "Add rule": When "Priority becomes high", Move into "Someday", Save -> the rule is in the list; a task that becomes
//   high moves into Someday by itself; dragged by hand into Soon it stays there (once per occasion)
// - the switch turns a rule off, the trash deletes it and "Undo" in the message brings it back
// - the tasks and the project stay as they are
// Firefox 320 x 640 (touch): the dialog and the rule dialog inside the screen, no sideways scrolling.
// freelancer-matrix: tasks - frida has no organisation.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2823_a_mine_rules_ui', check, shots: 'P2823A_SHOTS'});
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
  const mk = async (title, b = {}) => (await call(CF, 'POST', '/api/tasks', {title, list_id: L, ...b})).id;
  const TA = await mk('Pay the rent', {due: '2020-01-02'}), TB = await mk('Water the plants'), TC = await mk('Call the bank');
  const tasks0 = async () => JSON.stringify((await call(CF, 'GET', '/api/state')).tasks.filter(t => t.list_id === L).map(t => [t.id, t.sort, t.section_id, t.due]));

  const w = await boot({user: 'frida', hash: 'assigned'}), d = w.document;
  const heads = () => [...d.querySelectorAll('#view .ghead[data-key^="ms:"]')];
  const head = re => heads().find(x => re.test(x.textContent));
  const inSec = (re, id) => !!head(re)?.closest('.group')?.querySelector(`.trow[data-id="${id}"]`);
  check(await until(() => head(/\bNow\b/) && head(/Someday/)), 'the sections are there');
  check(await until(() => inSec(/\bNow\b/, TA)), '(1) the overdue task is in Now by the first rule');
  check(inSec(/Recently assigned/, TB) && inSec(/Recently assigned/, TC), 'the others stay in "Recently assigned"');
  const list0 = await tasks0();

  // the dialog: the first rule as a sentence
  const item = () => w.eval(`topMoreItems().find(x => x.label === 'Rules…')`);
  check(item(), 'the view menu offers "Rules…"');
  w.eval(`topMoreItems().find(x => x.label === 'Rules…').fn()`);
  const dlg = () => d.querySelector('.modal.mr-dlg');
  const rows = () => [...(dlg()?.querySelectorAll('.mr-row') || [])];
  check(await until(() => rows().length === 1), 'the dialog lists one rule');
  const txt0 = rows()[0]?.textContent || '';
  check(/Due today or overdue to Now/.test(txt0) && /When a task is due today or overdue, move it to the top of “Now”/.test(txt0), '(1) the first rule as a sentence: ' + txt0.trim());
  check(rows()[0].querySelector('[data-mr-on]').checked, 'it is on');

  // a new rule: priority becomes high -> Someday
  click(w, dlg().querySelector('[data-mr-add]'));
  const ed = () => d.querySelector('.modal.mr-edit');
  check(await until(() => ed()), 'the rule dialog opens');
  const sel = (id, v) => { const s = ed().querySelector('#' + id); s.value = String(v); s.dispatchEvent(new w.Event('change', {bubbles: true})); return s.value === String(v); };
  check(sel('mr-trig', 'before') && ed().querySelector('#mr-days'), 'When "Some days before the due date" asks for the days');
  check(sel('mr-trig', 'prio') && !ed().querySelector('#mr-days'), 'When "Priority becomes high" needs no value');
  const some = [...ed().querySelectorAll('#mr-sec option')].find(o => o.textContent === 'Someday');
  check(some && sel('mr-sec', some.value), 'Move into: Someday');
  click(w, ed().querySelector('[data-m="save"]'));
  check(await until(() => !ed() && rows().length === 2), 'saved: two rules in the list');
  const txt1 = rows()[1]?.textContent || '';
  check(/When the priority of a task becomes high, move it to the top of “Someday”/.test(txt1), 'the new rule as a sentence: ' + txt1.trim());
  click(w, dlg().querySelector('[data-m="close"]'));
  check(await until(() => !dlg()), 'the dialog closes');

  // the rule works: Call the bank becomes high -> Someday by itself
  await call(CF, 'PATCH', `/api/tasks/${TC}`, {priority: 5});
  await w.eval('load().then(render)');
  check(await until(() => inSec(/Someday/, TC)), '(2) the task that became high is in Someday');
  // hand wins
  const key = re => head(re).dataset.key;
  await w.eval(`dropTask(${TC}, document.querySelector('#view .ghead[data-key="${key(/Soon/)}"]'), 0)`);
  check(await until(() => inSec(/Soon/, TC)), 'dragged into Soon by hand');
  await until(async () => (await call(CF, 'GET', '/api/state')).mine_sections.tasks[TC] === +key(/Soon/).slice(3));
  await w.eval('(mrSig = "", mrApply())');
  await w.eval('load().then(render)');
  check(inSec(/Soon/, TC) && (await call(CF, 'GET', '/api/state')).mine_sections.tasks[TC] === +key(/Soon/).slice(3), '(3) the rule runs again, the task stays where the hand put it');
  check(await tasks0() === list0, 'the tasks and the project unchanged (order, sections, due dates)');

  // switch off, delete, Undo
  w.eval(`topMoreItems().find(x => x.label === 'Rules…').fn()`);
  check(await until(() => rows().length === 2), 'the dialog again');
  const box = rows()[1].querySelector('[data-mr-on]');
  box.checked = false; box.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => rows()[1]?.classList.contains('off')), 'switched off: the row is dimmed');
  const srv = async () => (await call(CF, 'GET', '/api/mine-rules')).rules;
  check(await until(async () => (await srv())[1]?.active === false), 'off on the server');
  click(w, rows()[1].querySelector('[data-mr-del]'));
  check(await until(() => rows().length === 1), 'deleted: one rule left');
  check(await until(async () => (await srv()).length === 1), 'deleted on the server');
  const undo = d.querySelector('#toast:not(.hidden) button');
  check(undo && /Rule deleted/.test(d.querySelector('#toast').textContent), 'the message offers Undo');
  click(w, undo);
  check(await until(() => rows().length === 2), 'Undo: the rule is back in the list');
  check(await until(async () => (await srv()).length === 2), 'and on the server');
  w.close();

  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    const ready = async (expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`) === 200, 'login frida');
    await nav(B + '#assigned');
    check(await ready(`!!document.querySelector('#view [data-mse-add]')`), '320 px: the sections are there');
    await ev(`(topMoreItems().find(x => x.label === 'Rules…').fn(), 1)`);
    check(await ready(`document.querySelectorAll('.modal.mr-dlg .mr-row').length === 2`), '320 px: the rules dialog with both rules');
    const inside = sel => ev(`(() => { const c = document.querySelector('${sel} > .card'); if (!c) return null; const b = c.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), vw: innerWidth, sw: document.documentElement.scrollWidth,
      btns: [...c.querySelectorAll('button, input')].filter(x => x.offsetParent).every(x => { const y = x.getBoundingClientRect(); return y.left >= 0 && y.right <= innerWidth + 1; })}; })()`);
    let b = await inside('.modal.mr-dlg');
    check(b && b.l >= 0 && b.r <= b.vw + 1 && b.sw <= b.vw + 1 && b.btns, '320 px: the rules dialog inside the screen, its switches and buttons too ' + JSON.stringify(b));
    await o.shot('p2823a-320-rules.png');
    await ev(`(document.querySelector('.modal.mr-dlg [data-mr-add]').click(), 1)`);
    check(await ready(`!!document.querySelector('.modal.mr-edit #mr-trig')`), '320 px: the rule dialog opens');
    b = await inside('.modal.mr-edit');
    check(b && b.l >= 0 && b.r <= b.vw + 1 && b.sw <= b.vw + 1 && b.btns, '320 px: the rule dialog inside the screen ' + JSON.stringify(b));
    await o.shot('p2823a-320-edit.png');
  }, true);

  console.log(`p2823_a_mine_rules_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
