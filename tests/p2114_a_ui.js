// 2.114.0 UI tests (part A), own container (start.sh). jsdom:
// #2060 list settings > Rules: the dialog offers the new triggers (created, assigned, custom field) and actions (priority,
//       list tag, custom field) with their choices; "When a task is created, then priority high" is saved from the dialog,
//       the row shows the sentence, a new task gets the high priority (visible in the list); the field trigger shows the
//       values of a checkbox field, the field action the value input of a number field.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2114A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEAT = 'cal,comments,collab,fields,kanban';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const L = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG, kind: 'project'})).id;
  const OKF = (await call('POST', `/api/lists/${L}/fields`, {name: 'Signed', type: 'checkbox'})).id;
  const HRS = (await call('POST', `/api/lists/${L}/fields`, {name: 'Hours', type: 'number'})).id;
  await call('POST', `/api/lists/${L}/tags`, {name: 'hot'});

  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`listModal(${L})`);
  await until(() => d.querySelector('#l-rules [data-rul-add]'));
  const box = () => d.querySelector('#l-rules');
  click(w, box().querySelector('[data-rul-add]'));
  await until(() => d.querySelector('.rul-dlg'));
  const dl = () => d.querySelector('.rul-dlg');
  const kinds = sel => [...(dl().querySelector(sel)?.options || [])].map(o => o.value);
  check(['created', 'assigned', 'field'].every(k => kinds('#rul-trig').includes(k)), '#2060: the new triggers in the dialog ' + kinds('#rul-trig'));
  check(['priority', 'tag', 'field'].every(k => kinds('#rul-act').includes(k)), '#2060: the new actions in the dialog ' + kinds('#rul-act'));
  // the choices of the new kinds
  change(w, dl().querySelector('#rul-trig'), 'assigned');
  check(kinds('#rul-tuser')[0] === '' && kinds('#rul-tuser').length >= 2, '#2060: assigned: anybody or a person ' + kinds('#rul-tuser'));
  change(w, dl().querySelector('#rul-trig'), 'field');
  check(kinds('#rul-tfld').includes(String(OKF)), '#2060: field trigger lists the custom fields');
  change(w, dl().querySelector('#rul-tfld'), String(OKF));
  check(kinds('#rul-tfv').join() === ',1,0', '#2060: checkbox field: any change / checked / unchecked ' + kinds('#rul-tfv'));
  change(w, dl().querySelector('#rul-act'), 'field');
  change(w, dl().querySelector('#rul-afld'), String(HRS));
  check(dl().querySelector('#rul-fval')?.tagName === 'INPUT', '#2060: number field: a value input');
  change(w, dl().querySelector('#rul-act'), 'tag');
  check(dl().querySelector('#rul-atag')?.options.length === 1, '#2060: tag action lists the list tags');
  // When a task is created, then priority high
  dl().querySelector('#rul-name').value = 'Hot';
  change(w, dl().querySelector('#rul-trig'), 'created');
  check(dl().querySelector('#rul-tv').hidden && dl().querySelector('#rul-tv2').hidden, '#2060: created needs no further choice');
  change(w, dl().querySelector('#rul-act'), 'priority');
  check(dl().querySelector('#rul-prio')?.value === 'high', '#2060: priority: high is the default');
  click(w, dl().querySelector('[data-m="save"]'));
  await until(() => !dl());
  const rules = (await call('GET', `/api/lists/${L}/rules`)).rules || [];
  check(rules.length === 1 && rules[0].trigger.kind === 'created' && rules[0].action.kind === 'priority' && rules[0].action.priority === 'high',
    '#2060: saved on the server ' + JSON.stringify(rules));
  await until(() => box()?.querySelector('.rul-row'));
  const txt = box()?.querySelector('.rul-row')?.textContent || '';
  check(/When a task is created, then set its priority to High\./.test(txt), '#2060: the row reads the sentence: ' + txt);
  d.querySelector('.modal [data-m="close"], .modal .x')?.click?.();
  w.close();

  // a new task gets the high priority, visible in the list
  const t = await call('POST', '/api/tasks', {list_id: L, title: 'Fresh lead'});
  check(t.priority === 5 || (await call('GET', `/api/tasks/${t.id}`)).priority === 5, '#2060: the rule set priority high');
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  const chk = await until(() => d.querySelector(`.chk[data-id="${t.id}"]`));
  check(chk && chk.classList.contains('p5'), '#2060: the task shows the high priority in the list ' + (chk?.className || 'missing'));
  w.close();

  console.log(`p2114_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
