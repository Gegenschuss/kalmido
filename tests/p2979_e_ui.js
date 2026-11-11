// 2.979.0 UI test, part E (#5667): an undo / redo the server takes back by its group (undo.js histDo, #5255) no longer runs
// the entry's own undo function, which used to fetch the area again; the areas of projects / settings with their own store
// register how they fetch (core.js histReloader, undo.js histRedraw):
// kalmido-suite: fresh
// freelancer-matrix: undo (a person without an organisation: her deleted rule comes back in the open project dialog)
//  - rules.js: a rule deleted in the open project dialog; one undo shows it again in the open box, it can be switched off
//    afterwards (no stale row), redo removes it again
//  - sectpl.js: a section template deleted in its open dialog; undo shows it again there, redo removes it
//  - listadmin.js: an active project deleted: the trash keeps no server step, so the step must not take the archiving's group
//    (one undo brings it back active, the trash page drops it; redo puts it into the trash again)
//  - settings.js: Settings > Data > templates: a template deleted from its dialog; undo shows it again in the open list
// jsdom, fresh container. Invented names only. The waits are on states (rows, the server's answer), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const undo = w => w.eval(`histStep('undo').then(() => 1)`);
const redo = w => w.eval(`histStep('redo').then(() => 1)`);

// the rules box of the open project dialog: delete a rule, undo, switch it off, redo
async function rulesCase(ck, user, L, w) {
  const d = w.document;
  const R = await call(ck, 'POST', `/api/lists/${L}/rules`, {name: `Kranich ${user}`, trigger: {kind: 'created'}, action: {kind: 'comment', text: 'Checked by the rule'}});
  check(R.id > 0, `${user}: a rule (${R.http} ${R.error || ''})`);
  w.eval(`listModal(${L})`);
  const row = () => d.querySelector(`#l-rules .rul-row[data-rid="${R.id}"]`);
  check(await until(() => row()), `${user}: the project dialog shows the rule`);
  click(w, row()?.querySelector('[data-rul-del]'));
  check(await until(() => !row() && w.eval('HIST.undo.length') > 0), `${user}: deleted, the row leaves the box`);
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), `${user}: the step is a group of the server`);
  await undo(w);
  check(await until(() => row()), `${user}: undo (server group): the open dialog shows the rule again`);
  check(/Kranich/.test(row()?.textContent || ''), `${user}: ... with its name (${(row()?.textContent || '').slice(0, 60)})`);
  await redo(w);
  check(await until(() => !row()), `${user}: redo: deleted again, the row goes`);
  check(!((await call(ck, 'GET', `/api/lists/${L}/rules`)).rules || []).some(x => x.id === R.id), `${user}: the server has it deleted`);
  await undo(w);
  check(await until(() => row()), `${user}: undo once more: back in the box`);
  // a change after the undo (a new step; it ends the way forward, so it comes after the redo)
  const sw = row()?.querySelector('[data-rul-on]');
  if (sw) { sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => ((await call(ck, 'GET', `/api/lists/${L}/rules`)).rules || []).some(x => x.id === R.id && !x.active)), `${user}: the rule brought back can be changed again (switched off)`);
  check(await until(() => row()?.classList.contains('off')), `${user}: ... and the row shows it off`);
  d.querySelector('.modal [data-m="close"], .modal [data-act="close"]')?.click();
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: []});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Heron'})).id;
  await call(CA, 'POST', '/api/sections', {list_id: L, name: 'Morning'});
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Feed the heron', list_id: L})).id;
  const w = await boot({user: 'alice', hash: 'inbox'}); const d = w.document;
  check(await until(() => w.eval(`!!listById(${L})`)), 'the client knows the project');

  // ---- rules.js
  await rulesCase(CA, 'alice', L, w);

  // ---- sectpl.js: the dialog of section templates
  const ST = await call(CA, 'POST', '/api/section-templates', {name: 'Flamingo plan', list_id: L, space: 'private'});
  check(ST.id > 0, `a section template (${ST.http} ${ST.error || ''})`);
  await w.eval(`sct_open(${L}).then(() => 1)`);
  const srow = () => d.querySelector(`.sctmodal .sctt[data-sct="${ST.id}"]`);
  check(await until(() => srow()), 'the dialog shows the section template');
  click(w, srow()?.querySelector('[data-m="del"]'));
  check(await until(() => !srow() && d.querySelector('.sctmodal')), 'deleted: gone from the open dialog');
  await undo(w);
  check(await until(() => srow()), 'undo (server group): the open dialog shows the template again');
  check(/Flamingo plan/.test(srow()?.textContent || ''), `... with its name (${(srow()?.textContent || '').slice(0, 60)})`);
  await redo(w);
  check(await until(() => !srow()), 'redo: gone again');
  await undo(w);
  check(await until(() => srow()), 'undo once more: back');
  d.querySelector('.sctmodal [data-m="close"]')?.click();
  check(await until(() => !d.querySelector('.sctmodal')), 'the dialog closes (back in the app)');

  // ---- settings.js: Settings > Data, the list of templates
  const TP = await call(CA, 'POST', '/api/templates', {task_id: T, name: 'Pelican routine'});
  check(TP.id > 0, `a template (${TP.http} ${TP.error || ''})`);
  w.eval(`settingsModal('data')`);
  const trow = () => d.querySelector(`.smodal #s-tpls [data-tpl="${TP.id}"]`);
  check(await until(() => trow()), 'Settings > Data lists the template');
  click(w, trow()?.querySelector('[data-tpl-edit]'));
  check(await until(() => d.querySelector('.tpmodal [data-m="del"]')), 'its dialog opens');
  click(w, d.querySelector('.tpmodal [data-m="del"]'));
  check(await until(() => !d.querySelector('.tpmodal') && !trow()), 'deleted: gone from the settings list');
  await undo(w);
  check(await until(() => trow()), 'undo (server group): the open settings list shows the template again');
  await redo(w);
  check(await until(() => !trow()), 'redo: gone again');
  [...d.querySelectorAll('.smodal')].forEach(m => m.remove());

  // ---- listadmin.js: an ACTIVE project deleted (archived first, then into the trash, #2304): the trash keeps no server step,
  // the step goes back by its own functions; it must not take the archiving's group (the server would take back only that)
  const G = (await call(CA, 'POST', '/api/lists', {name: 'Stork'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Count the storks', list_id: G});
  await w.eval('load().then(() => 1)');
  check(await until(() => w.eval(`!!listById(${G}) && !listById(${G}).archived`)), 'the client knows the active project');
  check(await w.eval(`listDeleteForGood(${G})`) === true, 'deleted');
  const lst = async () => ((await call(CA, 'GET', '/api/state')).lists || []).find(x => x.id === G);
  const inTrash = async () => ((await call(CA, 'GET', '/api/trash/lists')).lists || []).some(x => x.id === G);
  check(await until(() => w.eval('(HIST.undo[HIST.undo.length - 1]?.label || "")').includes('Stork')), 'the delete is the newest step');
  check(await inTrash(), 'the server has it in the trash');
  check(w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') === 0, 'the step carries no server group (its own functions take it back)');
  w.location.hash = 'trash';
  const orow = () => d.querySelector(`.otrlists .otrrow[data-otr="${G}"]`);
  check(await until(() => orow()), 'the trash page shows the deleted project');
  await undo(w);
  check(await until(async () => { const x = await lst(); return x && !x.archived; }), 'one undo brings it back ACTIVE');
  check(!(await inTrash()), '... nothing left in the trash');
  check(await until(() => !orow()), '... and the shown trash page no longer lists it');
  check(await until(() => w.eval(`!!listById(${G}) && !listById(${G}).archived`)), '... the app shows the active project again');
  await redo(w);
  check(await until(() => inTrash()), 'redo: into the trash again');
  check(await until(() => orow()), 'redo: the trash page lists it again');
  await undo(w);
  check(await until(async () => { const x = await lst(); return x && !x.archived; }), 'undo after redo: active again');
  w.close();

  // ---- a person without an organisation (freelancer parity): her rule
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CF = await login('fiona');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'private'});
  const LF = (await call(CF, 'POST', '/api/lists', {name: 'Ibis'})).id;
  const wf = await boot({user: 'fiona', hash: 'inbox'});
  check(await until(() => wf.eval(`!!listById(${LF})`)), 'fiona: the client knows her project');
  await rulesCase(CF, 'fiona', LF, wf);
  wf.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2979_e_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
