// Package C UI tests (jsdom): Settings > Data > Import -- the source picker with its help text and file types, the preview
// (counts per list, warnings, escaped sample rows, options that re-run the preview: target list, Trello mode / archived
// cards, completed tasks, Todoist priority scale, list name), Import (report + Undo), the "Recent imports" list with Undo,
// the history line "imported from ...", TickTick still direct, German.
// Starts its own container (start.sh) and sets up the users over the API.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DATA = process.argv[2];
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const FX = path.join(__dirname, 'fixtures', 'import');
const call = async (cookie, method, url, body) => {
  const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cookie}, body: body === undefined ? undefined : JSON.stringify(body)});
  const t = await r.text(); try { return JSON.parse(t); } catch { return t; }
};
const set = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const pick = (w, input, name, bytes) => {  // a file chosen in the file input
  const f = new File([bytes || fs.readFileSync(path.join(FX, name))], name);
  Object.defineProperty(input, 'files', {configurable: true, value: [f]});
  input.dispatchEvent(new w.Event('change', {bubbles: true}));
};
async function dataPane(w) {
  w.eval(`settingsModal()`); await sleep(400);
  const md = w.document.querySelector('.smodal');
  click(w, md.querySelector('.snav [data-sec="data"]')); await sleep(300);
  return md;
}
(async () => {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA]);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const ca = await login('alice');
  const own = await call(ca, 'POST', '/api/lists', {name: 'Existing'});

  let w = await boot({user: 'alice'}), d = w.document;
  let md = await dataPane(w);
  const src = md.querySelector('#s-imp-src'), inp = md.querySelector('#s-import'), out = () => md.querySelector('#s-imp-out');
  check([...src.options].map(o => o.value).join() === 'todoist,trello,asana,mstodo,ics,ticktick', 'source picker: six sources');
  check(/Export as a CSV file/.test(md.querySelector('#s-imp-help').textContent) && inp.accept.includes('.zip'), 'Todoist help + file types');
  set(w, src, 'mstodo'); await sleep(50);
  check(/classic Outlook for Windows/.test(md.querySelector('#s-imp-help').textContent) && inp.accept.includes('.ics'), 'Microsoft To Do: recommended export path');
  set(w, src, 'ics'); await sleep(50);
  check(/Nextcloud Tasks/.test(md.querySelector('#s-imp-help').textContent), 'ICS help');

  // ---- Todoist preview
  set(w, src, 'todoist'); await sleep(50);
  pick(w, inp, 'Haushalt.csv'); await sleep(1500);
  const box = () => out().querySelector('.impbox');
  check(box() && /Preview: 12 tasks will be created/.test(box().textContent), 'preview headline ' + (box()?.textContent || '').slice(0, 80));
  check(/Haushalt/.test(box().textContent) && /new list/.test(box().textContent), 'preview: list row (new list)');
  check(box().querySelectorAll('.impwarn li').length >= 3 && /Date not understood/.test(box().textContent), 'preview: warnings');
  check(box().querySelectorAll('.impr').length === 8 && box().querySelector('.impr.sub') && box().querySelector('.impr .tag'), 'preview: sample rows (subtasks indented, tags)');
  check(!w.eval(`[...S.tasks.values()].some(t => t.title === 'Müll rausbringen')`), 'preview: nothing imported yet');
  check(md.querySelector('#s-imp-priority_scale') && md.querySelector('#s-imp-completed') && !md.querySelector('#s-imp-mode'), 'Todoist options (no Trello options)');
  check(md.querySelector('#s-imp-name').value === 'Haushalt', 'list name prefilled');
  // escaping: the task with HTML in its title is not in the first 8 samples; import a tiny file with one to check
  set(w, md.querySelector('#s-imp-priority_scale'), '4'); await sleep(1500);
  check(md.querySelector('#s-imp-priority_scale').value === '4' && /p1 \(highest\)/.test(md.querySelector('#s-imp-priority_scale').textContent), 'option change re-runs the preview (kept)');
  // target = existing list: list name field disappears, list row says existing
  set(w, md.querySelector('#s-imp-target'), String(own.id)); await sleep(1500);
  check(/existing list/.test(box().textContent) && !md.querySelector('#s-imp-name'), 'target: existing list');
  set(w, md.querySelector('#s-imp-target'), 'new'); await sleep(1500);
  set(w, md.querySelector('#s-imp-name'), 'Zuhause'); await sleep(200);
  click(w, box().querySelector('[data-imp="go"]')); await sleep(2000);
  check(/Imported: 12 tasks/.test(box().textContent) && box().querySelector('[data-imp="undo"]'), 'import report with Undo');
  check(w.eval(`S.lists.some(l => l.name === 'Zuhause') && [...S.tasks.values()].some(t => t.title === 'Müll rausbringen')`), 'imported into a list with the chosen name');
  check(w.eval(`[...S.tasks.values()].find(t => t.title === 'Müll rausbringen').priority`) === 5, 'priority scale 4 = p1 applied');
  check(/Imported: 12 tasks/.test(d.querySelector('#toast').textContent), 'toast');
  check(md.querySelectorAll('#s-imp-hist [data-imp="undo"]').length === 1, 'recent imports: one with Undo');
  // history line of an imported task
  const tid = w.eval(`[...S.tasks.values()].find(t => t.title === 'Müll rausbringen').id`);
  md.remove();
  w.eval(`openDetail(${tid})`); await sleep(1200);
  check(/Alice imported the task from Todoist/.test(d.querySelector('#detail').textContent), 'history: imported from Todoist');
  w.close();

  // ---- escaping + undo from the recent list
  w = await boot({user: 'alice'}); d = w.document;
  md = await dataPane(w);
  pick(w, md.querySelector('#s-import'), 'x.csv', 'TYPE,CONTENT\ntask,<img src=x onerror="window.__x=1"> <b>bold</b>\ntask,"<script>window.__y=1</script>"\n'); await sleep(1500);
  check(out().querySelectorAll('img, script, .imptab b').length === 0 && /<img src=x/.test(out().textContent) && !w.__x && !w.__y, 'sample rows escaped');
  click(w, out().querySelector('[data-imp="cancel"]')); await sleep(100);
  check(!out().querySelector('.impbox') && md.querySelector('#s-import').value === '', 'cancel clears the preview');
  const hb = md.querySelector('#s-imp-hist [data-imp="undo"]');
  click(w, hb); await sleep(1800);
  check(w.eval(`![...S.tasks.values()].some(t => t.title === 'Müll rausbringen')`) && /Import undone: 12 tasks removed/.test(d.querySelector('#toast').textContent), 'undo from the recent imports');
  check(!md.querySelector('#s-imp-hist [data-imp="undo"]'), 'undone import leaves the list');

  // ---- Trello options
  set(w, md.querySelector('#s-imp-src'), 'trello'); await sleep(50);
  pick(w, md.querySelector('#s-import'), 'trello-board.json'); await sleep(1500);
  check(md.querySelector('#s-imp-mode') && md.querySelector('#s-imp-archived') && /Preview: 7 tasks/.test(out().textContent), 'Trello: mode + archived options');
  check(/Archived cards and cards in archived lists were skipped/.test(out().textContent), 'Trello: archived warning');
  set(w, md.querySelector('#s-imp-mode'), 'lists'); await sleep(1500);
  check(/To Do/.test(out().textContent) && /Doing/.test(out().textContent) && md.querySelector('#s-imp-mode').value === 'lists', 'Trello: lists mode preview');
  set(w, md.querySelector('#s-imp-archived'), 'done'); await sleep(1500);
  check(/Preview: 9 tasks/.test(out().textContent), 'Trello: archived as done');
  click(w, out().querySelector('[data-imp="go"]')); await sleep(2000);
  check(w.eval(`S.lists.filter(l => l.folder === 'Website Relaunch').length`) === 3, 'Trello lists mode: three lists in a folder');
  click(w, out().querySelector('[data-imp="undo"]')); await sleep(1800);
  check(w.eval(`S.lists.filter(l => l.folder === 'Website Relaunch').length`) === 0, 'undo from the report removes the new lists');

  // ---- errors show as a toast and leave no box
  set(w, md.querySelector('#s-imp-src'), 'asana'); await sleep(50);
  pick(w, md.querySelector('#s-import'), 'Work.csv'); await sleep(1200);
  check(!out().querySelector('.impbox') && /not an Asana CSV/.test(d.querySelector('#toast').textContent), 'wrong file: error toast');

  // ---- TickTick: direct import (no preview)
  set(w, md.querySelector('#s-imp-src'), 'ticktick'); await sleep(50);
  const tt = '"Folder Name","List Name","Title","Kind","Tags","Content","Is Check list","Start Date","Due Date","Reminder","Repeat","Priority","Status","Created Time","Completed Time","Order","Timezone","Is All Day","Is Floating","Column Name","Column Order","View Mode","taskId","parentId"\n'
    + '"","TT list","From TickTick","TEXT","","","N","","","","","0","0","2026-09-01T10:00:00+0000","","1","Europe/Berlin","","false","","","list","tt1",""\n';
  pick(w, md.querySelector('#s-import'), 'tt.csv', tt); await sleep(1500);
  check(!out().querySelector('.impbox') && w.eval(`[...S.tasks.values()].some(t => t.title === 'From TickTick')`), 'TickTick: imported directly');
  w.close();

  // ---- German
  await call(ca, 'PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice'}); d = w.document;
  md = await dataPane(w);
  check(/Übernimm deine Aufgaben/.test(md.querySelector('[data-pane="data"]').textContent) && /Als CSV-Datei exportieren/.test(md.querySelector('#s-imp-help').textContent), 'German: help');
  pick(w, md.querySelector('#s-import'), 'Haushalt.csv'); await sleep(1500);
  check(/Vorschau: 12 Aufgaben werden angelegt/.test(out().textContent) && /Datum nicht verstanden/.test(out().textContent)
    && /Neue Listen/.test(out().textContent) && /12 Aufgaben importieren/.test(out().textContent), 'German: preview');
  w.close();
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
