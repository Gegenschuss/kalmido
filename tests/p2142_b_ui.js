// 2.142.0 UI tests, part B (#2147) (jsdom): Settings > Data > Import with the new sources Notion, Google Tasks, ClickUp,
// Jira, any CSV and Markdown: in the source picker with help text and file types, the preview of each (counts, list
// row), the CSV preview names which column went where (data-field), Import asks for the target (private) and creates the
// tasks, Undo removes them. Sample files made here (invented names). English interface; starts its own container.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DATA = process.argv[2];
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const set = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const pick = (w, input, name, text) => {
  const f = new w.File([text], name);
  Object.defineProperty(input, 'files', {configurable: true, value: [f]});
  input.dispatchEvent(new w.Event('change', {bubbles: true}));
};
async function dataPane(w) {
  w.eval(`settingsModal()`); await sleep(400);
  const md = w.document.querySelector('.smodal');
  click(w, md.querySelector('.snav [data-sec="data"]')); await sleep(300);
  return md;
}
const SAMPLES = {
  notion: ['Aufgaben 0123456789abcdef0123456789abcdef.csv', 'Name,Status,Date,Tags\nNotion eins,Done,"January 15, 2025",a\nNotion zwei,,,\n', 2, /Notion:/, '.zip'],
  gtasks: ['Tasks.json', JSON.stringify({kind: 'tasks#taskLists', items: [{kind: 'tasks#taskList', id: 'l', title: 'Google Liste', items: [{kind: 'tasks#task', id: 'a', title: 'Google eins', status: 'needsAction'}]}]}), 1, /takeout\.google\.com/, '.json'],
  clickup: ['clickup.csv', 'Task ID,Task Name,Status,List Name\nc1,ClickUp eins,to do,CU Liste\nc2,ClickUp zwei,complete,CU Liste\n', 2, /ClickUp:/, '.csv'],
  jira: ['jira.csv', 'Summary,Issue key,Issue id,Status,Project name\nJira eins,J-1,1,To Do,Jira Projekt\n', 1, /Export CSV/, '.csv'],
  csv: ['Liste.csv', 'Aufgabe;Fällig;Kosten\nCSV eins;15.04.2025;10\nCSV zwei;;\n', 2, /The preview shows which column went where/, '.csv'],
  markdown: ['plan.md', '# MD Liste\n- [ ] MD eins\n  - [x] MD zwei\n', 2, /headings become lists/, '.md'],
};
(async () => {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA]);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  await login('alice');
  const w = await boot({user: 'alice'}), d = w.document;
  const md = await dataPane(w);
  const src = md.querySelector('#s-imp-src'), inp = md.querySelector('#s-import'), out = () => md.querySelector('#s-imp-out'), box = () => out().querySelector('.impbox');
  const vals = [...src.options].map(o => o.value);
  check(['notion', 'gtasks', 'clickup', 'jira', 'csv', 'markdown'].every(x => vals.includes(x)) && vals[0] === 'todoist' && vals.at(-1) === 'ticktick',
    'source picker: the six new sources, Todoist first, TickTick last: ' + vals.join());
  w.eval(`window.__itc = []; const _itc0 = importTargetConfirm; importTargetConfirm = o => { __itc.push(o); return _itc0(o); }`);
  for (const [k, [name, text, n, help, ext]] of Object.entries(SAMPLES)) {
    set(w, src, k); await sleep(80);
    check(help.test(md.querySelector('#s-imp-help').textContent) && inp.accept.includes(ext), `${k}: help text + file types`);
    pick(w, inp, name, text); await sleep(1500);
    const re = new RegExp(`Preview: ${n} tasks? will be created`);
    check(box() && re.test(box().textContent) && box().querySelector('[data-imp="go"]'), `${k}: preview ` + (box()?.textContent || d.querySelector('#toast')?.textContent || '').slice(0, 160));
    if (k === 'csv') {
      const f = [...box().querySelectorAll('.impcols [data-field]')].map(x => x.dataset.field + ':' + x.querySelector('.n').textContent);
      check(f.join() === 'title:Aufgabe,due:Fällig,notes:Kosten', 'csv: the preview names which column went where: ' + f.join());
      check(/Due date/.test(box().querySelector('.impcols').textContent), 'csv: field names in words');
    } else check(!box().querySelector('.impcols'), `${k}: no column table`);
    click(w, box().querySelector('[data-imp="go"]')); await sleep(2200);
    check(/Imported: \d+ tasks?/.test(box()?.textContent || '') && box().querySelector('[data-imp="undo"]'), `${k}: imported, Undo offered`);
    const first = name === 'Tasks.json' ? 'Google eins' : text.match(/(Notion eins|ClickUp eins|Jira eins|CSV eins|MD eins)/)[1];
    check(w.eval(`[...S.tasks.values()].some(t => t.title === ${JSON.stringify(first)})`), `${k}: the task is in the app`);
    click(w, box().querySelector('[data-imp="undo"]')); await sleep(1800);
    check(w.eval(`![...S.tasks.values()].some(t => t.title === ${JSON.stringify(first)})`), `${k}: undo removes it`);
  }
  check(w.eval(`__itc.length === 6 && __itc.every(o => o.ws === 'private')`), 'every import named its target first (private): ' + w.eval('JSON.stringify(__itc)'));
  // a wrong file: the server's message as a toast, no box
  set(w, src, 'jira'); await sleep(80);
  pick(w, inp, 'x.csv', 'Title\nx\n'); await sleep(1200);
  check(!box() && /not a Jira CSV/.test(d.querySelector('#toast').textContent), 'wrong file: error toast');
  w.close();
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
