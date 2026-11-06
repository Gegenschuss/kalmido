// kalmido-suite: fresh
// 2.528.0 part B (#4305, A9 + A16): an online change of a task carries what this device saw (_prev), like the offline queue:
// a field another device changed meanwhile is kept and waits in the conflicts dialog instead of being overwritten silently.
// Single changes (priority, date, personal tags, list tags, custom fields) and the multi-edit panel (batch patch /
// patch_each), and the time entry dialog (A13). A field this device already shows with its new value (shown before it was sent) is no base: no false conflict.
// No new route; the server side of _prev for a person without an organisation: p2528_b_time_test.py (time) and p287b (tasks).
const {boot, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };

(async () => {
  await until(async () => (await fetch(B + 'sw.js').catch(() => null))?.ok);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');  // the "other device": its own session of the same person
  await call('POST', '/api/admin/setup', {lang: 'en', time_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'fields,time'});
  const L = (await call('POST', '/api/lists', {name: 'Garden', kind: 'project', time_tracking: 1})).id;
  const FLD = (await call('POST', `/api/lists/${L}/fields`, {name: 'Size', type: 'text'})).id;
  const LT = await call('POST', `/api/lists/${L}/tags`, {name: 'green'});
  await call('POST', `/api/lists/${L}/tags`, {name: 'blue'});
  const mk = async title => (await call('POST', '/api/tasks', {title, list_id: L, tags: ['a'], priority: 0})).id;
  const T1 = await mk('Cut the hedge'), T2 = await mk('Water the roses'), T3 = await mk('Rake the leaves');
  check(L && FLD && LT.id && T1 && T2 && T3, 'setup ' + JSON.stringify({L, FLD, LT}));

  const w = await boot({user: 'alice'});
  check(await until(() => w.eval(`!!S.tasks.get(${T3})`)), 'the window knows the tasks');
  const srv = async id => call('GET', `/api/tasks/${id}`);
  // 2.549.0 (#4568): a task's change goes through the outbox online too (2.537.0): its answer (conflicts, the server's values) comes once it is sent
  const drained = () => until(() => w.eval('!OUT.q.length && !OUT.flushing'));
  // the window still shows the old value (as when the other device's change has not arrived yet), then changes it online
  const stale = (id, js) => w.eval(`(() => { const t = S.tasks.get(${id}); ${js}; return 1; })()`);
  const sent = [];
  w.eval('window.__f0 = window.fetch');
  w.fetch = (u, o) => { if (o?.method && o.method !== 'GET' && /\/api\/(tasks|time)/.test(String(u))) sent.push({u: String(u), b: JSON.parse(o.body || '{}')}); return w.__f0(u, o); };

  // priority: the other device set High, this one (still showing None) sets Low -> High stays, a conflict waits
  await call('PATCH', `/api/tasks/${T1}`, {priority: 5});
  await stale(T1, 't.priority = 0');
  await w.eval(`patchTask(${T1}, {priority: 1})`); await drained();
  let s = await srv(T1);
  check(s.priority === 5, 'A9: the other device\'s priority stays (no silent last write) ' + s.priority);
  check(sent.at(-1)?.b?._prev?.priority === 0, 'A9: the online PATCH carries what this device saw ' + JSON.stringify(sent.at(-1)));
  check(w.eval(`S.conflicts.some(c => c.tid === ${T1} && c.field === 'priority' && c.mine === 1)`), 'A9: the conflict waits in the dialog ' + w.eval('JSON.stringify(S.conflicts)'));
  check(w.eval(`S.tasks.get(${T1}).priority`) === 5, 'A9: the window follows the server');
  // "Use mine" in the dialog wins on purpose (its base is now the server's value)
  w.eval('conflictModal()');
  const bt = await until(() => [...w.document.querySelectorAll('#cf-list [data-cf="mine"]')][0]);
  bt.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  check(await until(async () => (await srv(T1)).priority === 1), 'A9: "Use mine" sets its value');

  // date: no other change meanwhile -> applied, no conflict
  const n0 = w.eval('S.conflicts.length');
  await w.eval(`patchTask(${T1}, {due: '2027-03-01'})`); await drained();
  check((await srv(T1)).due === '2027-03-01' && w.eval('S.conflicts.length') === n0, 'A9: a change without one elsewhere goes through');
  // a caller that showed the value before sending it (the window has the new value already): no false conflict
  await stale(T1, "t.due = '2027-03-05'");
  await w.eval(`patchTask(${T1}, {due: '2027-03-05'})`); await drained();
  check((await srv(T1)).due === '2027-03-05' && w.eval('S.conflicts.length') === n0, 'A9: an already shown value is no base (no false conflict) ' + w.eval('JSON.stringify(S.conflicts)'));

  // personal tags: the other device added "b", this one (still showing ["a"]) sends ["a", "c"] -> "b" is not lost
  await call('PATCH', `/api/tasks/${T2}`, {tags: ['a', 'b']});
  await stale(T2, "t.tags = ['a']");
  await w.eval(`patchTask(${T2}, {tags: ['a', 'c']})`); await drained();
  s = await srv(T2);
  check(JSON.stringify([...s.tags].sort()) === '["a","b"]', 'A9: the tag added elsewhere stays ' + JSON.stringify(s.tags));
  check(w.eval(`S.conflicts.some(c => c.tid === ${T2} && c.field === 'tags')`), 'A9: tags conflict in the dialog');

  // list tags (server: compared too since 2.528.0)
  await call('PATCH', `/api/tasks/${T2}`, {ltags: ['blue']});
  await stale(T2, 't.ltags = []');
  await w.eval(`patchTask(${T2}, {ltags: ['green']})`); await drained();
  s = await srv(T2);
  check(JSON.stringify(s.ltags) === '["blue"]', 'A9: the list tag set elsewhere stays ' + JSON.stringify(s.ltags));
  check(w.eval(`S.conflicts.some(c => c.tid === ${T2} && c.field === 'ltags')`), 'A9: list tags conflict in the dialog');

  // custom field
  await call('PATCH', `/api/tasks/${T3}`, {fields: {[FLD]: 'large'}});
  await stale(T3, `t.fields = {}`);
  await w.eval(`patchTask(${T3}, {fields: {${FLD}: 'small'}})`); await drained();
  s = await srv(T3);
  check(s.fields?.[FLD] === 'large', 'A9: the field value set elsewhere stays ' + JSON.stringify(s.fields));
  check(w.eval(`S.conflicts.some(c => c.tid === ${T3} && c.field === 'field:${FLD}')`), 'A9: field conflict in the dialog');

  // A16: the multi-edit panel, the same value for all (batch patch): T2's date changed elsewhere stays, T3 changes
  await call('PATCH', `/api/tasks/${T2}`, {due: '2027-05-05'});
  await stale(T2, 't.due = null'); await stale(T3, 't.due = null');
  w.eval(`S.multi = new Set([${T2}, ${T3}])`);
  await w.eval("meApply('date', t => t.due !== '2027-06-01' ? {due: '2027-06-01'} : null, 'Date')");
  check((await srv(T2)).due === '2027-05-05', 'A16: multi-edit keeps the date changed elsewhere');
  check((await srv(T3)).due === '2027-06-01', 'A16: multi-edit changes the other task');
  check(w.eval(`S.conflicts.some(c => c.tid === ${T2} && c.field === 'due')`), 'A16: its conflict waits in the dialog');
  const bp = sent.filter(x => /\/api\/tasks\/batch$/.test(x.u)).at(-1);
  check(bp?.b?.action === 'patch' && bp.b.data?.prev?.[T2]?.due === null, 'A16: the batch carries prev ' + JSON.stringify(bp?.b));

  // A16: different values per task (patch_each, a shift by days)
  await call('PATCH', `/api/tasks/${T3}`, {due: '2027-07-01'});
  await stale(T2, "t.due = '2027-05-05'"); await stale(T3, "t.due = '2027-06-01'");
  await w.eval("meApply('date', t => t.due ? {due: addDays(t.due, 1)} : null, 'Shift')");  // what meShift(1) does (it does not return the promise)
  check((await srv(T2)).due === '2027-05-06', 'A16: patch_each changes the task without a change elsewhere');
  check((await srv(T3)).due === '2027-07-01', 'A16: patch_each keeps the date changed elsewhere');
  check(w.eval(`S.conflicts.some(c => c.tid === ${T3} && c.field === 'due' && c.mine === '2027-06-02')`), 'A16: patch_each conflict in the dialog ' + w.eval('JSON.stringify(S.conflicts)'));

  // A13: the time entry dialog sends what it showed; changed elsewhere meanwhile = 409, said in the dialog, Reload = the saved one
  // 2.576.0 (#4764): objsave.js saveDialog - the dialog comes again with the saved entry, the own note over it and marked; "Take
  // theirs" (instead of Reload) puts the saved note in
  const te = await call('POST', '/api/time/entries', {task_id: T1, start: '2026-10-05T09:00', minutes: 30, note: 'Hedge, front'});
  check(te.id, 'time entry ' + JSON.stringify(te));
  w.eval(`entryModal(${JSON.stringify(te)})`);
  check(await until(() => w.document.querySelector('#te-note')), 'A13: the dialog is open');
  await call('PATCH', `/api/time/entries/${te.id}`, {note: 'Hedge, front and back'});
  w.document.querySelector('#te-note').value = 'Hedge, front (mine)';
  w.document.querySelector('[data-m="save"]').dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  const hint = await until(() => w.document.querySelector('.modal .obj-merge'));
  check(hint && /Changed by someone else in the meantime/.test(hint.textContent), 'A13: the dialog says the entry changed meanwhile');
  check(w.document.querySelector('#te-note')?.value === 'Hedge, front (mine)' && w.document.querySelector('#te-noterow')?.classList.contains('obj-theirs'), 'A13: the own note stays, marked as changed elsewhere');
  let tv = (await call('GET', `/api/time/entries?task_id=${T1}`)).entries?.find(x => x.id === te.id);
  check(tv?.note === 'Hedge, front and back', 'A13: the other note stays ' + tv?.note);
  check(sent.some(x => x.u.endsWith(`/api/time/entries/${te.id}`) && x.b._prev?.note === 'Hedge, front'), 'A13: the PATCH carries _prev');
  hint.querySelector('[data-om="theirs"]').dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  check(await until(() => w.document.querySelector('#te-note')?.value === 'Hedge, front and back'), 'A13: "Take theirs" shows the saved version');
  w.document.querySelector('#te-note').value = 'Hedge, all sides';
  w.document.querySelector('[data-m="save"]').dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  check(await until(async () => (await call('GET', `/api/time/entries?task_id=${T1}`)).entries?.find(x => x.id === te.id)?.note === 'Hedge, all sides'), 'A13: saved on the new base');

  w.close();
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})();
