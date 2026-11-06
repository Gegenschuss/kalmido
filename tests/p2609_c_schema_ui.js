// kalmido-suite: fresh
// 2.609.0 (#3373) UI tests, own container (start.sh): the ticket model of an organisation in the app (jsdom).
// - a project with a required field: a new task asks for its value first (cancel = no task, filled in = created with it); the
//   task panel marks the field with *
// - the project's settings list the fields of the organisation with a switch; switching one on makes the linked field
// - the tag editor names an organisation label apart from project tags and personal tags
// - "From template" names the organisation of a template; a member sees it
// - a person without an organisation: her own field templates in her project's settings (freelancer-matrix: orgschema.)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: 'collab,comments,fields', lang: 'en', tour: 'done'});
  let ORG = (await call('GET', '/api/state')).me.workspaces?.[0]?.id;
  if (!ORG) { const me = (await call('GET', '/api/state')).me; const o = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id}); ORG = o.id || o.org?.id; }
  check(ORG && (await call('GET', '/api/state')).me.workspaces.some(x => x.id === ORG && x.role === 'admin'), 'setup: alice administers an organisation');
  const L = (await call('POST', '/api/lists', {name: 'Support', kind: 'project', org_id: ORG})).id;
  const fld = await call('POST', `/api/lists/${L}/fields`, {name: 'Customer', type: 'text', required: true});
  check(fld.required === true, 'setup: a required field ' + JSON.stringify(fld).slice(0, 200));
  const of = await call('POST', '/api/org-fields', {space: `org:${ORG}`, name: 'Severity', type: 'select', options: {options: [{name: 'Low'}, {name: 'High'}]}});
  check(of.key === 'severity', 'setup: a field of the organisation');
  await call('POST', '/api/org-labels', {org_id: ORG, name: 'Escalated', color: '#f87171'});
  const t0 = await call('POST', '/api/tasks', {title: 'Seed', list_id: L, fields: {[fld.id]: 'Acme'}});
  const tp = await call('POST', '/api/templates', {task_id: t0.id, name: 'Ticket', space: `org:${ORG}`});
  check(tp.org_id === ORG, 'setup: a template of the organisation');

  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await idle(w);

  // ================= required field: asked before the task is made
  let p = w.eval(`createTask({title: 'Printer jams', list_id: ${L}}).then(t => t.id, e => 'no:' + e.message)`);
  let md = await until(() => d.querySelector('.rqfmodal'));
  check(md && /Customer/.test(md.textContent) && md.querySelector(`[data-cf="${fld.id}"]`), 'a new task asks for the required field');
  click(w, md?.querySelector('[data-m="close"]'));
  const r1 = await p;
  check(String(r1).startsWith('no:') && !(await call('GET', '/api/state')).tasks.some(t => t.title === 'Printer jams'), 'cancelled: no task');
  p = w.eval(`createTask({title: 'Printer jams', list_id: ${L}}).then(t => t.id, e => 'no:' + e.message)`);
  md = await until(() => d.querySelector('.rqfmodal'));
  click(w, md?.querySelector('[data-m="ok"]'));
  await sleep(200);
  check(d.querySelector('.rqfmodal'), 'an empty value keeps the question open');
  const inp = md?.querySelector(`[data-cf="${fld.id}"]`);
  if (inp) inp.value = 'Initech';
  click(w, md?.querySelector('[data-m="ok"]'));
  const id = await p;
  const st = await call('GET', '/api/state');
  const tk = st.tasks.find(t => t.id === id);
  check(tk && tk.fields?.[fld.id] === 'Initech', 'filled in: created with the value ' + JSON.stringify(tk?.fields));
  const fe = w.eval(`fieldEditor(fieldById(${fld.id}), {id: 0, list_id: ${L}, fields: {}}, false)`);
  check(/cfreq/.test(fe) && /\*/.test(fe), 'the task panel marks the required field');
  check(await w.eval(`createTask({title: 'Sub', list_id: ${L}, parent_id: ${id}}).then(t => !!t.id, () => false)`) && !d.querySelector('.rqfmodal'), 'a subtask is not asked');

  // ================= the fields of the organisation in the project's settings
  w.eval(`listModal(${L})`);
  const box = await until(() => d.querySelector('#l-fields .ofsbox'));
  check(box && /Fields of the organisation/.test(box.textContent) && /Severity/.test(box.textContent) && box.querySelector('[data-ofs="manage"]'), 'the project settings list the organisation\'s fields (admin: Manage…)');
  const sw = box?.querySelector(`[data-ofson="${of.id}"]`);
  if (sw) { sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const linked = await until(async () => (await call('GET', '/api/state')).fields.find(f => f.list_id === L && f.org_field_id === of.id));
  check(linked && linked.name === 'Severity', 'switched on: the linked field is in the project');
  await until(() => [...d.querySelectorAll('#l-fields .mrow .muted')].some(x => /linked/.test(x.textContent)));
  check([...d.querySelectorAll('#l-fields .mrow .muted')].some(x => /linked/.test(x.textContent)), 'the field list marks it as linked');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());

  // ================= labels apart
  const html = w.eval(`tagEditHtml(taskById(${id}), false)`);
  check(/value="Escalated" label="Organisation label"/.test(html), 'the tag editor names the organisation label');
  // ================= From template
  await w.eval('load()');
  const tpl = w.eval('tplOf("task")').find(x => x.id === tp.id);
  check(tpl && tpl.org_id === ORG, 'the app state carries the template of the organisation');

  // ================= a person without an organisation
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {features: 'collab,comments,fields', lang: 'en', tour: 'done'}, CF);
  const FL = (await call('POST', '/api/lists', {name: 'Clients', kind: 'project'}, CF)).id;
  await call('POST', '/api/org-fields', {name: 'Rate', type: 'number'}, CF);
  const w2 = await boot({user: 'frida', hash: 'l/' + FL}), d2 = w2.document;
  await idle(w2);
  w2.eval(`listModal(${FL})`);
  const box2 = await until(() => d2.querySelector('#l-fields .ofsbox'));
  check(box2 && /My field templates/.test(box2.textContent) && /Rate/.test(box2.textContent), 'frida: her own field templates in her project\'s settings');
  click(w2, box2?.querySelector('[data-ofs="manage"]'));
  const mm = await until(() => [...d2.querySelectorAll('.modal')].find(m => m.querySelector('#ofs-list .mrow')));
  check(mm && /rate/.test(mm.textContent), 'frida: Manage… lists them with their key');

  console.log(`p2609_c_schema_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
