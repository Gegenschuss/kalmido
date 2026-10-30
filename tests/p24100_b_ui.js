// kalmido-suite: fresh
// 2.410.0 B (#3515): the board shows on every card how long it has been in its column. Own container, jsdom.
// - a card moved a moment ago: "0 min" in grey; the times of the column "Doing" (limits: yellow after 1 h, red after 1 d)
//   back-dated through the test data (never waited for): 2 h = yellow, 3 days = red; a column without limits stays grey
//   ("10 d"); a card without a known move counts from its creation
// - the column menu offers "Time limits…"; the dialog saves both limits (hours / days) in one step, the menu then shows
//   them, red not above yellow is refused with a message (nothing saved); the cards follow the new limits
// - a linked task in the board of its further list counts from its place there
// - the list view (not the board) shows no time
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const sql = (q, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(args)]).toString() || '[]');
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ago = h => new Date(Date.now() - h * 3600e3).toISOString().slice(0, 19) + '+00:00';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,kanban'});
  const P = (await call('POST', '/api/lists', {name: 'Board'})).id;
  await call('PATCH', `/api/lists/${P}`, {view: 'kanban'});
  const DO = (await call('POST', '/api/sections', {list_id: P, name: 'Doing'})).id;
  const RV = (await call('POST', '/api/sections', {list_id: P, name: 'Review'})).id;
  await call('PATCH', `/api/sections/${DO}`, {dwell_warn_h: 1, dwell_alert_h: 24});
  const mk = async (title, sid) => (await call('POST', '/api/tasks', {title, list_id: P, section_id: sid})).id;
  const FRESH = await mk('Fresh card', RV), YEL = await mk('Two hours', RV), RED = await mk('Three days', RV), GREY = await mk('Ten days', DO), NEW = await mk('Never moved', DO);
  for (const t of [FRESH, YEL, RED]) await call('PATCH', `/api/tasks/${t}`, {section_id: DO});
  await call('PATCH', `/api/tasks/${GREY}`, {section_id: RV});
  sql('UPDATE tasks SET section_at=? WHERE id=?', [ago(2), YEL]);
  sql('UPDATE tasks SET section_at=? WHERE id=?', [ago(72), RED]);
  sql('UPDATE tasks SET section_at=? WHERE id=?', [ago(240), GREY]);
  sql('UPDATE tasks SET created_at=? WHERE id=?', [ago(5), NEW]);
  // a linked task: its own list elsewhere, on this board in Review since 30 h
  const O = (await call('POST', '/api/lists', {name: 'Origin'})).id;
  const LNK = (await call('POST', '/api/tasks', {title: 'Linked card', list_id: O})).id;
  await call('POST', `/api/tasks/${LNK}/links`, {list_id: P, section_id: RV});
  sql('UPDATE task_links SET section_at=? WHERE task_id=? AND list_id=?', [ago(30), LNK, P]);
  check(P && DO && RV && FRESH && LNK, 'setup');

  const w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  const chip = id => d.querySelector(`#view .kanban .trow[data-id="${id}"] .dwm`);
  await until(() => chip(FRESH));
  const st = id => { const c = chip(id); return c ? c.dataset.dw + ' ' + [...c.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim() : 'none'; };
  check(/^ok [01] min$/.test(st(FRESH)), '#3515: a card moved a moment ago: grey, "0 min" (' + st(FRESH) + ')');
  check(st(YEL) === 'warn 2 h', '#3515: 2 h in Doing (yellow after 1 h): yellow (' + st(YEL) + ')');
  check(st(RED) === 'alert 3 d', '#3515: 3 days in Doing (red after 1 day): red (' + st(RED) + ')');
  check(st(GREY) === 'ok 10 d', '#3515: a column without limits stays grey, "10 d" (' + st(GREY) + ')');
  check(st(NEW) === 'warn 5 h', '#3515: never moved: counts from its creation (' + st(NEW) + ')');
  check(st(LNK) === 'ok 1 d', '#3515: a linked task counts from its place on this board (' + st(LNK) + ')');
  check(/In this column for 3 d · Over the red limit/.test(chip(RED)?.getAttribute('title') || ''), '#3515: the tooltip says it (' + chip(RED)?.getAttribute('title') + ')');
  check(chip(RED)?.classList.contains('dw-alert') && chip(YEL)?.classList.contains('dw-warn') && !/dw-/.test(chip(GREY)?.className || 'x'), '#3515: the colour classes (red / yellow / none)');

  // the column menu: Time limits… -> the dialog
  const menuOf = async sid => { click(w, d.querySelector(`.kcol[data-kcol="${sid}"] [data-act="section-menu"]`)); return until(() => [...d.querySelectorAll('#pop [role="menuitem"], #pop .menu-list button')].find(b => /Time limits/.test(b.textContent))); };
  let mi = await menuOf(RV);
  check(mi && /Time limits…/.test(mi.textContent), '#3515: the column menu offers "Time limits…" (' + mi?.textContent + ')');
  click(w, mi);
  let dlg = await until(() => d.querySelector('.cdlg #dw-warn') && d.querySelector('.cdlg'));
  check(!!dlg, '#3515: the dialog opens with the two limits');
  // red not above yellow: refused, nothing saved
  dlg.querySelector('#dw-warn').value = '2'; dlg.querySelector('#dw-warn-u').value = '24';
  dlg.querySelector('#dw-alert').value = '30'; dlg.querySelector('#dw-alert-u').value = '1';
  dlg.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  check(await until(() => /red limit must be above/.test(d.body.textContent)), '#3515: red below yellow: the message');
  check(sql('SELECT dwell_warn_h, dwell_alert_h FROM sections WHERE id=?', [RV])[0].dwell_warn_h === null, '#3515: nothing saved');
  // 1 day yellow, 9 days red
  mi = await menuOf(RV); click(w, mi);
  dlg = await until(() => d.querySelector('.cdlg #dw-warn') && d.querySelector('.cdlg'));
  dlg.querySelector('#dw-warn').value = '1'; dlg.querySelector('#dw-warn-u').value = '24';
  dlg.querySelector('#dw-alert').value = '9'; dlg.querySelector('#dw-alert-u').value = '24';
  dlg.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  const saved = await until(() => { const r = sql('SELECT dwell_warn_h, dwell_alert_h FROM sections WHERE id=?', [RV])[0]; return r.dwell_warn_h === 24 && r.dwell_alert_h === 216 ? r : null; });
  check(!!saved, '#3515: the dialog saves 1 day / 9 days as 24 / 216 hours');
  check(await until(() => st(GREY) === 'alert 10 d' && st(LNK) === 'warn 1 d'), '#3515: the cards follow the new limits (' + st(GREY) + ', ' + st(LNK) + ')');
  mi = await menuOf(RV);
  check(mi && /Time limits: 1 d \/ 9 d/.test(mi.textContent), '#3515: the menu shows the limits (' + mi?.textContent + ')');
  d.querySelector('#pop')?.classList.add('hidden');

  // the list view shows no time
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});
  w.eval(`listById(${P}).view = 'list'; render()`);
  check(await until(() => !d.querySelector('#view .kanban') && d.querySelector(`#view .trow[data-id="${RED}"]`)), 'list view drawn');
  check(!d.querySelector('#view .dwm'), '#3515: the list view shows no time in the column');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  w.close();
  console.log(`p24100_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
