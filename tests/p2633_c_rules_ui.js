// 2.633.0 part C UI test (jsdom), own container (start.sh), invented data.
// kalmido-suite: fresh
// #4781 list settings > Rules: the dialog offers the actions "Mark it as done" and "Open it again" (no further choice);
// "When a task comes into the column Done, then mark it as done" is saved from the dialog and the row reads the sentence;
// a task moved into Done is done afterwards.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2633C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  let CK;
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
  const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});
  const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const L = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  const DONE = (await call('POST', '/api/sections', {list_id: L, name: 'Done'})).id;

  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`listModal(${L})`);
  await until(() => d.querySelector('#l-rules [data-rul-add]'));
  click(w, d.querySelector('#l-rules [data-rul-add]'));
  await until(() => d.querySelector('.rul-dlg'));
  const dl = () => d.querySelector('.rul-dlg');
  const kinds = [...(dl().querySelector('#rul-act')?.options || [])].map(o => o.value);
  check(kinds.includes('done') && kinds.includes('reopen'), '#4781: the dialog offers done / reopen ' + kinds);
  dl().querySelector('#rul-name').value = 'Finish';
  change(w, dl().querySelector('#rul-trig'), 'section');
  change(w, dl().querySelector('#rul-tsec'), String(DONE));
  change(w, dl().querySelector('#rul-act'), 'reopen');
  check(!dl().querySelector('#rul-av').innerHTML.trim(), '#4781: reopen needs no further choice');
  change(w, dl().querySelector('#rul-act'), 'done');
  check(!dl().querySelector('#rul-av').innerHTML.trim(), '#4781: done needs no further choice');
  click(w, dl().querySelector('[data-m="save"]'));
  await until(() => !dl());
  const rules = (await call('GET', `/api/lists/${L}/rules`)).rules || [];
  check(rules.length === 1 && rules[0].action.kind === 'done' && rules[0].trigger.section_id === DONE, '#4781: saved on the server ' + JSON.stringify(rules));
  await until(() => d.querySelector('#l-rules .rul-row'));
  const txt = d.querySelector('#l-rules .rul-row')?.textContent || '';
  check(/then mark it as done\./.test(txt), '#4781: the row reads the sentence: ' + txt);
  w.close();

  const t = await call('POST', '/api/tasks', {list_id: L, title: 'Report'});
  await call('PATCH', `/api/tasks/${t.id}`, {section_id: DONE});
  check((await call('GET', `/api/tasks/${t.id}`)).status === 2, '#4781: moved into Done, the task is done');

  console.log(`p2633_c_rules_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
