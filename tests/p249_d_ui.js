// 2.49.0 UI tests, part D: ticking off softly (#1766), the x in a toast (#1769), completed hidden in new lists (#1535); own container
// (start.sh). jsdom (the timers drive the animations, jsdom does not run CSS):
//   #1766: the line (ui-strike) comes first; with "Hide completed" the row then folds away (ui-gone) and is gone after the redraw, without it
//          the row stays (struck through); ticked again meanwhile = the exit is cancelled and the task is open; several quick ticks: no
//          redraw in the middle (an untouched row stays the same node); "reduce motion": no animation, the row is dropped at once
//   #1769: the x (button "Close") with a button or a long stay, none on a short message; closes without the action; Escape closes; Undo's shortcut ends
//   #1535: Appearance has the switch for new lists; a new list hides completed (setting on), shows them with the setting off
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
// 2.308.0 (#3275): resolves in the microtask right after the class is set (or at once when it is there), before the next timer
// of the animation can fire - no fixed sleep that a loaded machine overshoots
const classSeen = (w, el, cls) => new Promise(res => {
  if (el.classList.contains(cls)) return res();
  const mo = new w.MutationObserver(() => { if (el.classList.contains(cls)) { mo.disconnect(); res(); } });
  mo.observe(el, {attributes: true, attributeFilter: ['class']});
});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Home'})).id;  // a new list: completed are hidden (#1535)
  const T = [];
  for (const t of ['One', 'Two', 'Three', 'Four', 'Five']) T.push((await call('POST', '/api/tasks', {title: t, list_id: L})).id);
  const st = async id => (await call('GET', `/api/tasks/${id}`)).status;

  let w = await boot({hash: 'l/' + L}), d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T[0]}"]`));
  check(w.eval(`showDone('l:${L}')`) === false && w.eval('doneToggleView()') === true, '#1535: the new list hides completed');

  // ---- #1766: line first, then the row folds away
  const row0 = d.querySelector(`#view .trow[data-id="${T[0]}"]`), keep = d.querySelector(`#view .trow[data-id="${T[4]}"]`);
  const p0 = w.eval(`toggleTask(${T[0]})`);
  await classSeen(w, row0, 'ui-strike');
  check(row0.classList.contains('ui-strike') && !row0.classList.contains('ui-gone'), '#1766: the line comes first');
  await classSeen(w, row0, 'ui-gone');
  check(row0.classList.contains('ui-gone') && row0.style.height, '#1766: then the row folds away (height set, ui-gone)');
  await p0;
  check(!d.querySelector(`#view .trow[data-id="${T[0]}"]`) && (await st(T[0])) !== 0, '#1766: gone after the redraw, completed on the server');
  check(d.querySelector(`#view .trow[data-id="${T[4]}"]`) === keep, '#1766: an untouched row is the same node (no needless redraw)');

  // ---- several quick ticks: nothing redraws in the middle
  // the second tick comes while the first row is folding away (ui-gone set, its exit still running)
  const row1 = d.querySelector(`#view .trow[data-id="${T[1]}"]`), row2 = d.querySelector(`#view .trow[data-id="${T[2]}"]`);
  const pa = w.eval(`toggleTask(${T[1]})`); await classSeen(w, row1, 'ui-gone'); const pb = w.eval(`toggleTask(${T[2]})`);
  await classSeen(w, row2, 'ui-strike');
  check(row1.classList.contains('ui-gone') && row2.classList.contains('ui-strike') && !row2.classList.contains('ui-gone'), '#1766: each row has its own state');
  check(d.querySelector(`#view .trow[data-id="${T[4]}"]`) === keep, '#1766: the list was not redrawn while a row still animates');
  await Promise.all([pa, pb]);
  check(!d.querySelector(`#view .trow[data-id="${T[1]}"]`) && !d.querySelector(`#view .trow[data-id="${T[2]}"]`), '#1766: both gone after the animations');

  // ---- ticked again within the time: the exit is cancelled, the task is open
  const row3 = d.querySelector(`#view .trow[data-id="${T[3]}"]`);
  const pc = w.eval(`toggleTask(${T[3]})`); await classSeen(w, row3, 'ui-strike');
  const pd = w.eval(`toggleTask(${T[3]})`);
  await Promise.all([pc, pd]);
  check(!row3.classList.contains('ui-strike') && !row3.classList.contains('ui-gone') && d.querySelector(`#view .trow[data-id="${T[3]}"]`), '#1766: ticked again meanwhile: the row stays');
  check((await st(T[3])) === 0, '#1766: ... and the task is open on the server (status ' + (await st(T[3])) + ')');

  // ---- completed shown: the row stays struck through
  await w.eval(`setShowDone(true, 'l:${L}')`); await sleep(300);
  const T5 = (await call('POST', '/api/tasks', {title: 'Six', list_id: L})).id;
  await w.eval('load()'); w.eval('render()'); await sleep(200);
  const row5 = d.querySelector(`#view .trow[data-id="${T5}"]`);
  const pe = w.eval(`toggleTask(${T5})`); await classSeen(w, row5, 'ui-strike');
  check(row5.classList.contains('ui-strike'), '#1766: the line runs also when completed are shown');
  await sleep(500);
  check(!row5.classList.contains('ui-gone'), '#1766: ... and the row does not fold away');
  await pe;
  check((await st(T5)) !== 0 && d.querySelector('#view .ghead[data-key="done-open"]'), '#1766: completed, now counted in the Completed group of the list');

  // ---- reduce motion: no animation
  await w.eval(`setShowDone(false, 'l:${L}')`); await sleep(300);
  const T6 = (await call('POST', '/api/tasks', {title: 'Seven', list_id: L})).id;
  await w.eval('load()'); w.eval('render()'); await sleep(200);
  w.eval(`window.matchMedia = q => ({matches: /reduce/.test(q), addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}})`);
  const row6 = d.querySelector(`#view .trow[data-id="${T6}"]`);
  const pf = w.eval(`toggleTask(${T6})`); await classSeen(w, row6, 'ui-now');
  check(row6.classList.contains('ui-now') && row6.style.display === 'none', '#1766: reduced motion: struck at once and dropped at once');
  await pf;
  w.close();

  // ---- #1769: the x in a toast
  w = await boot({hash: 'l/' + L}); d = w.document;
  await until(() => d.querySelector('#toast'));
  const tx = () => d.querySelector('#toast button.tx');
  w.eval(`toast('Saved')`);
  check(!tx(), '#1769: a short message has no x');
  w.eval(`toast('Reminder text', null, 6000)`);
  check(tx() && tx().getAttribute('aria-label') === 'Close' && tx().tagName === 'BUTTON', '#1769: a longer one has the x, a real button labelled Close');
  tx().click();
  check(d.querySelector('#toast').classList.contains('hidden'), '#1769: the x closes it');
  w.eval(`window.__u = 0; toast('Deleted', () => { window.__u++; }, 6000, 'Open')`);
  check(tx() && d.querySelector('#toast button') !== tx(), '#1769: with an action button: the action first, the x after');
  tx().click();
  check(d.querySelector('#toast').classList.contains('hidden') && w.eval('window.__u') === 0, '#1769: the x does not run the action');
  w.eval(`toast('Escape me', () => {}, 6000, 'Open')`);
  d.querySelector('#toast').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  check(d.querySelector('#toast').classList.contains('hidden'), '#1769: Escape closes the toast');
  w.eval(`HIST.toastE = {}; toast('Undo me', () => {}, 6000)`);
  tx().click();
  check(w.eval('HIST.toastE') === null, '#1769: for an undo toast the x also ends the shortcut');
  w.eval(`toast('Undo me', () => { window.__u++; })`);
  d.querySelector('#toast button').click();
  check(w.eval('window.__u') === 1, '#1769: the action button still works');

  // ---- #1535: the switch for new lists
  w.eval(`settingsModal('look')`); await until(() => d.querySelector('#s-sdn'));
  check(d.querySelector('#s-sdn')?.checked === true, '#1535: Appearance > new lists: hide completed is on');
  d.querySelector('#s-sdn').click(); await sleep(500);
  check(w.eval('S.settings.show_done_new') === '0', '#1535: switched off (saved)');
  await call('PATCH', '/api/settings', {show_done_default: '1'});  // a new account's default hides everything; the switch only decides about the entry
  const L2 = (await call('POST', '/api/lists', {name: 'Plain'})).id;
  await w.eval('load()'); await sleep(200);
  check(w.eval(`showDone('l:${L2}')`) === true && w.eval(`showDone('l:${L}')`) === false, '#1535: switched off: a new list shows completed, the earlier one keeps hiding');
  w.close();

  console.log(`p249_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e.stack); process.exit(1); });
