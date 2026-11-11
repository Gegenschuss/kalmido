// kalmido-suite: fresh
// 2.958.0 C (#3911) UI test (jsdom), own container: a task that is already done, dropped on the done column, shows the message only
// (no Undo, still done); an open task dropped there still offers Undo, which opens it again. Invented names only.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login, errs, until, undoToast} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ck = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['kanban', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const l = await call('POST', '/api/lists', {name: 'Board', view: 'kanban'});
  await call('PATCH', '/api/lists/' + l.id, {view: 'kanban'});
  const a = await call('POST', '/api/sections', {list_id: l.id, name: 'Doing'});
  const b = await call('POST', '/api/sections', {list_id: l.id, name: 'Finished'});
  const old = await call('POST', '/api/tasks', {title: 'Old card', list_id: l.id, section_id: a.id});
  const open = await call('POST', '/api/tasks', {title: 'Open card', list_id: l.id, section_id: a.id});
  await call('POST', '/api/tasks/batch', {ids: [old.id], action: 'complete'});  // completed while the column has no meaning yet: the card stays in Doing
  await call('PATCH', '/api/sections/' + b.id, {kind: 'done'});
  const w = await boot({user: 'alice', hash: 'l/' + l.id}), d = w.document;
  const toast = () => d.querySelector('#toast:not(.hidden)')?.textContent || '';
  const seen = []; new w.MutationObserver(() => { const t = d.querySelector('#toast'); if (!t.classList.contains('hidden')) seen.push({text: t.textContent, undo: !!t.querySelector('button:not(.tx)')}); }).observe(d.querySelector('#toast'), {childList: true, subtree: true, characterData: true, attributes: true});
  await until(() => w.eval(`S.tasks.has(${old.id})`));
  await w.eval(`taskToSection(${old.id}, ${b.id})`);
  check(await until(() => seen.some(x => /Moved to section Finished/.test(x.text))), 'the message is shown ' + JSON.stringify(seen));
  check(!seen.some(x => x.undo), 'no Undo button for the done task ' + JSON.stringify(seen));
  check((await call('GET', '/api/tasks/' + old.id)).status === 2, 'the task stays done');
  seen.length = 0;
  await w.eval(`taskToSection(${open.id}, ${b.id})`);
  check(await undoToast(w, /Moved to section Finished/), 'the open task offers Undo');
  check(await until(async () => (await call('GET', '/api/tasks/' + open.id)).status === 0), 'Undo opens it again');
  check(!errs.length, 'no script errors ' + errs.slice(0, 2));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack); process.exit(1); });
