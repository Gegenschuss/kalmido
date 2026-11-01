// kalmido-suite: fresh
// 2.445.0 (#3011): tablet widths. Kanban: the first column is always "Tasks", columns 18 rem wide from 600 px (84vw only
// below), the matrix 2x2 from 700 px (CSS read as text: jsdom lays nothing out), page title of the matrix = "Matrix",
// the timeline's heading = "Timeline" and it says how many dated tasks "Projects only" hides.
const fs = require('fs'), path = require('path');
const {boot, errs, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 15000, step: 100});
const ds = n => { const t = new Date(), d = new Date(t.getFullYear(), t.getMonth(), t.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/@media \(max-width:599px\)\{ \.kcol\{flex-basis:84vw\} \}/.test(css) && !/^\s+\.kcol\{flex-basis:84vw/m.test(css), 'CSS: the 84vw columns only below 600 px');
  check(/@media \(max-width:699px\)\{ \.matrix\{grid-template-columns:minmax\(0,1fr\)\} \}/.test(css) && !/max-width:767px\)\{ \.matrix/.test(css), 'CSS: the matrix is one column only below 700 px');

  const P = (await call('POST', '/api/lists', {name: 'Board', kind: 'project'})).id;
  await call('PATCH', `/api/lists/${P}`, {view: 'kanban'});
  await call('POST', '/api/sections', {list_id: P, name: 'Doing'});
  await call('POST', '/api/tasks', {title: 'Loose card', list_id: P, due: ds(5)});
  const inb = (await call('GET', '/api/state')).lists.find(l => l.is_inbox).id;
  await call('POST', '/api/tasks', {title: 'Inbox dated', list_id: inb, due: ds(2)});
  await call('POST', '/api/tasks', {title: 'Inbox dated 2', list_id: inb, due: ds(3)});

  let w = await boot({user: 'alice', hash: 'l/' + P}); let d = w.document;
  check(await until(() => d.querySelector('.kanban .khead')), 'kanban rendered');
  check(/^Tasks\b/.test(d.querySelector('.kcol .khead').textContent.trim()), 'first column "Tasks" next to a section: ' + d.querySelector('.kcol .khead').textContent);
  w.close();

  w = await boot({user: 'alice', hash: 'matrix'}); d = w.document;
  check(await until(() => d.querySelector('.matrix')) && d.querySelector('#top h1').textContent.trim() === 'Matrix', 'matrix page title = "Matrix": ' + d.querySelector('#top h1').textContent);
  w.close();

  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline'})});
  w.close();
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  check(await until(() => d.querySelector('.tl.rm')), 'timeline rendered');
  check(/^Timeline/.test(d.querySelector('#top h1').textContent.trim()), 'timeline heading: ' + d.querySelector('#top h1').textContent);
  check(/2 dated tasks hidden/.test(d.querySelector('.rm-hidn')?.textContent || ''), 'hint: 2 dated tasks hidden: ' + d.querySelector('.rm-hidn')?.textContent);
  d.querySelector('[data-act="rm-po"]').click();
  check(await until(() => !d.querySelector('.rm-hidn')), 'Projects only off: no hint');
  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
