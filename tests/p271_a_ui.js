// 2.71.0 UI tests (part A), own container (start.sh). jsdom:
// #1457 list settings > Rules (owner): the section lists the rules in one sentence; "Add rule" opens the dialog (Name, When,
//       Then); saving creates the rule on the server and the row shows it; the switch pauses it; delete is one undo step
//       (undo brings it back); an edit member does not see the section; the history line of a rule's change reads
//       "Rule <name>", a rule's comment carries the mark; the proposal card of kind rule shows the sentence and 👍 / 👎
// Firefox 390 touch: the rule dialog fits the phone, Save >= 44 px, screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p271_a_ui', check, shots: 'P271A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEAT = 'cal,comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call('POST', '/api/users', {orgs: [1], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG, kind: 'project'})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: bob.id, role: 'edit'});
  const REV = (await call('POST', '/api/sections', {list_id: W, name: 'Review'})).id;
  await call('POST', '/api/sections', {list_id: W, name: 'Done'});

  // ================= the section in the list settings
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`listModal(${W})`);
  await until(() => d.querySelector('#l-rules [data-rul-add]'));
  const box = () => d.querySelector('#l-rules');
  check(box() && /Rules/.test(box().previousElementSibling?.textContent || ''), '#1457: the list settings have the section Rules');
  click(w, box().querySelector('[data-rul-add]'));
  await until(() => d.querySelector('.rul-dlg'));
  const dl = () => d.querySelector('.rul-dlg');
  check(dl() && dl().querySelector('#rul-name') && dl().querySelector('#rul-trig') && dl().querySelector('#rul-act'), '#1457: the dialog: Name, When, Then');
  dl().querySelector('#rul-name').value = 'Review';
  change(w, dl().querySelector('#rul-trig'), 'section');
  change(w, dl().querySelector('#rul-tsec'), String(REV));
  change(w, dl().querySelector('#rul-act'), 'assign');
  change(w, dl().querySelector('#rul-user'), String(bob.id));
  click(w, dl().querySelector('[data-m="save"]'));
  await until(() => !dl());
  const rules = (await call('GET', `/api/lists/${W}/rules`)).rules || [];
  check(rules.length === 1 && rules[0].name === 'Review' && rules[0].trigger.section_id === REV && rules[0].action.user_id === bob.id,
    '#1457: saved on the server ' + JSON.stringify(rules));
  await until(() => box()?.querySelector('.rul-row'));
  const row = () => box().querySelector('.rul-row');
  check(/When a task comes into the column “Review”, then assign it to Bob\./.test(row()?.textContent || ''), '#1457: the row reads as a sentence: ' + (row()?.textContent || '').trim().slice(0, 160));
  // the switch
  const sw = row().querySelector('[data-rul-on]'); sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', `/api/lists/${W}/rules`)).rules[0].active === false);
  check((await call('GET', `/api/lists/${W}/rules`)).rules[0].active === false, '#1457: the switch pauses the rule');
  await call('PATCH', `/api/rules/${rules[0].id}`, {active: true});
  // delete = one undo step
  await w.eval(`(async () => { await rul_load(${W}); document.querySelector('#l-rules').innerHTML = rul_rowsHtml(${W}); })()`);
  await until(() => box()?.querySelector('[data-rul-del]'));
  click(w, box().querySelector('[data-rul-del]'));
  await until(async () => !((await call('GET', `/api/lists/${W}/rules`)).rules || []).length);
  check(!((await call('GET', `/api/lists/${W}/rules`)).rules || []).length, '#1457: deleted');
  await w.eval(`histStep('undo')`); await sleep(500);
  check(((await call('GET', `/api/lists/${W}/rules`)).rules || []).length === 1, '#1457: undo brings the rule back');
  // the history: a change made by the rule reads "Rule Review"
  const t = (await call('POST', '/api/tasks', {title: 'Draft', list_id: W}, CB)).id;
  await call('PATCH', `/api/tasks/${t}`, {section_id: REV}, CB);
  const tl = await call('GET', `/api/tasks/${t}/timeline`);
  const a = (tl.activity || []).find(x => x.data?.rule);
  check(a, '#1457: the task has a history line of the rule');
  const txt = a ? w.eval(`actText(${JSON.stringify(a)}, ${JSON.stringify(tl.users || {})})`) : '';
  check(/Rule Review/.test(txt), '#1457: the history line reads "Rule Review": ' + txt);
  check(/Rule Review/.test(w.eval(`rul_cmtTag({rule_name: 'Review'})`)), '#1457: a rule comment carries the mark');
  // the proposal card
  const card = w.eval(`rul_draw({agent: {name: 'Robo'}, list_name: 'Work', proposal: {summary: 'Saves time'}, rule_view: {name: 'Agent', trigger: {kind: 'done'}, action: {kind: 'due', days: 0}, names: {}}}).main`);
  check(/When a task is completed, then make it due today\./.test(card.replace(/<[^>]+>/g, '')), '#1457: the proposal card shows the sentence');
  d.querySelector('.modal')?.remove();
  w.close();
  // an edit member does not see the section
  const wb = await boot({user: 'bob'});
  wb.eval(`listModal(${W})`); await sleep(800);
  check(!wb.document.querySelector('#l-rules'), '#1457: an edit member does not see Rules');
  wb.close();

  // ================= Firefox: the phone (390, touch)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { listModal(${W}); return 1; })()`); await sleep(1500);
    await shot('p271a-390-rules-section.png');
    await ev(`(() => { const b = document.querySelector('#l-rules [data-rul-add]'); b && b.click(); return 1; })()`); await sleep(900);
    const g = await ev(`(() => { const c = document.querySelector('.rul-dlg .card'); if (!c) return null; const r = c.getBoundingClientRect();
      const s = document.querySelector('.rul-dlg [data-m="save"]').getBoundingClientRect();
      return {left: r.left, right: r.right, save: Math.min(s.width, s.height), wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide, `${tag}: #1457 the rule dialog fits the phone ` + JSON.stringify(g));
    check(g && g.save >= 44, `${tag}: #1457 Save >= 44 px ` + JSON.stringify(g));
    await shot('p271a-390-rule-dialog.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
