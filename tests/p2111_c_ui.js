// 2.111.0 (#2057) quick add, part C: @person (assign), a duration and a reminder (minutes before the due time, or at a fixed
// time, also without a due date) in English, German and French, the cases that must stay title text (e-mail address, an
// unclear first name, "Version 2", "in 30 min", "Erinnerung Freitag schreiben"), the body a new task gets (qa2_body: the
// person looked up again in the real list) and the row "At a fixed time" of the date dialog. Runs the real app in jsdom on
// the browser demo (tools/build_demo.py, no container), like quick_lang_test.js; invented names only.
// usage: node p2111_c_ui.js
const {JSDOM, VirtualConsole} = require('jsdom');
const http = require('http'), fs = require('fs'), path = require('path'), {execFileSync} = require('child_process');
const ROOT = path.join(__dirname, '..'), OUT = path.join(__dirname, '.demo-p2111c');
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ok = 0; const fails = [];
const check = (c, what) => { if (c) ok++; else { fails.push(what); console.log('FAIL:', what); } };

execFileSync(process.env.PYTHON || 'python3', [path.join(ROOT, 'tools', 'build_demo.py'), OUT], {encoding: 'utf-8'});
const srv = http.createServer((req, res) => {
  const p = path.join(OUT, decodeURIComponent(req.url.split('?')[0]).replace(/^\/demo\//, '/').replace(/\/$/, '/index.html'));
  if (!p.startsWith(OUT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, {'Content-Type': p.endsWith('.js') ? 'text/javascript' : p.endsWith('.css') ? 'text/css' : 'text/html'}); fs.createReadStream(p).pipe(res);
});

const D = n => `addDays(today(), ${n})`, NW = wd => `nextWeekday(${wd})`;
// [input, want: {title, due (expression), due_time, assignee_id, assignee_group_id, duration, reminders, remind_at (expression)}]
const CASES = {
  en: [
    ['Call client @Anna Schmidt ~Team', {title: 'Call client', assignee_id: 501}],
    ['@Zoe review ~Team', {title: 'review', assignee_id: 502}],
    ['@ZOË review ~Team', {title: 'review', assignee_id: 502}],
    ['@Anna plan ~Team', {title: '@Anna plan'}],  // two people called Anna: nobody, the text stays
    ['@Nobody plan ~Team', {title: '@Nobody plan'}],
    ['Write to a@b.example ~Team', {title: 'Write to a@b.example'}],
    ['@Support triage ~Team', {title: 'triage', assignee_group_id: 77}],
    ['@me file the taxes ~Team', {title: 'file the taxes', assignee_id: 'S.me.id'}],
    ['Meeting 30 min', {title: 'Meeting', duration: 30}],
    ['2h Workshop', {title: 'Workshop', duration: 120}],
    ['Report for 1.5 hours', {title: 'Report', duration: 90}],
    ['Interview 1h30', {title: 'Interview', duration: 90}],
    ['Version 2 release', {title: 'Version 2 release'}],
    ['Call in 30 min', {title: 'Call in 30 min'}],
    ['Dentist tomorrow 3pm remind me 15 min before', {title: 'Dentist', due: D(1), due_time: '15:00', reminders: '15'}],
    ['Pay the rent remind me tomorrow 9am', {title: 'Pay the rent', remind_at: `${D(1)} + 'T09:00'`}],
    ['Call the bank remind me friday', {title: 'Call the bank', remind_at: `${NW(5)} + 'T' + rat_allday()`}],
    ['Remind me to call Bob tomorrow', {title: 'Remind me to call Bob', due: D(1)}],
  ],
  de: [
    ['Zahnarzt morgen 15 uhr erinnere mich 1 tag vorher', {title: 'Zahnarzt', due: D(1), due_time: '15:00', reminders: '1440'}],
    ['Steuer erinnere mich Di 9:00', {title: 'Steuer', remind_at: `${NW(2)} + 'T09:00'`}],
    ['Rechnung schreiben erinnere mich morgen um 8', {title: 'Rechnung schreiben', remind_at: `${D(1)} + 'T08:00'`}],
    ['Besprechung 45 Minuten', {title: 'Besprechung', duration: 45}],
    ['Projekt für 1,5 Std', {title: 'Projekt', duration: 90}],
    ['Erinnerung Freitag schreiben', {title: 'Erinnerung schreiben', due: NW(5)}],
    ['So machen wir das', {title: 'So machen wir das'}],
    ['Anruf @ich ~Team', {title: 'Anruf', assignee_id: 'S.me.id'}],
  ],
  fr: [
    ['Dentiste demain 15h rappelle-moi 30 min avant', {title: 'Dentiste', due: D(1), due_time: '15:00', reminders: '30'}],
    ['Facture rappelle-moi demain à 9h', {title: 'Facture', remind_at: `${D(1)} + 'T09:00'`}],
    ['Réunion pendant 2h', {title: 'Réunion', duration: 120}],
    ['Réunion 15h', {title: 'Réunion', due: `('15:00' < nowHM() ? addDays(today(), 1) : today())`, due_time: '15:00'}],  // a French "15h" is a time, never a duration
  ],
};
const KEYS = ['title', 'due', 'due_time', 'assignee_id', 'assignee_group_id', 'duration', 'reminders', 'remind_at'];

(async () => {
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const store = {}, errs = [];
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) errs.push(e.message); });
  const dom = await JSDOM.fromURL(`http://127.0.0.1:${srv.address().port}/demo/`, {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      w.matchMedia = () => ({matches: false, addEventListener() {}, addListener() {}});
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; },
        key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      Object.defineProperty(w.navigator, 'languages', {configurable: true, value: ['en-GB']});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
    }});
  await sleep(2500);
  const w = dom.window;
  check(w.eval('S.lists.some(l => l.is_inbox)'), 'app booted');
  // a shared list with people and a group (collaboration on)
  w.eval(`S.collabAll = true; S.settings.features = (S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').concat('collab').join(',');
    S.lists.push({id: 9901, name: 'Team', owner_id: S.me.id, owner_name: S.me.display_name || 'Demo', shared: true, archived: 0,
      members: [{user_id: 501, name: 'Anna Schmidt', role: 'edit'}, {user_id: 502, name: 'Zoë Martin', role: 'edit'}, {user_id: 503, name: 'Anna Berg', role: 'edit'}],
      groups: [{group_id: 77, name: 'Support'}]});`);
  check(w.eval('canAddTo(9901) && collab()'), 'setup: the shared list is writable, collaboration on');
  for (const [lang, cases] of Object.entries(CASES)) {
    check(await w.eval(`i18nLoad('${lang}')`), `${lang}: language loaded`);
    let n = 0;
    for (const [inp, want] of cases) {
      const r = JSON.parse(w.eval(`JSON.stringify(parseQuick(${JSON.stringify(inp)}, new Set()))`));
      const exp = {};
      for (const k of KEYS) exp[k] = k in want ? (['due', 'remind_at'].includes(k) || want[k] === 'S.me.id' ? w.eval(want[k]) : want[k]) : undefined;
      const got = Object.fromEntries(KEYS.map(k => [k, r[k] ?? undefined]));
      const good = KEYS.every(k => (got[k] ?? null) === (exp[k] ?? null));
      check(good, `${lang}: ${JSON.stringify(inp)} -> ${JSON.stringify(got)}, want ${JSON.stringify(exp)}`);
      n += good;
    }
    console.log(`${lang}: ${n}/${cases.length} cases`);
  }
  await w.eval(`i18nLoad('en')`);
  // a chip that is switched off keeps the text
  const off = JSON.parse(w.eval(`JSON.stringify(parseQuick('Call @Anna Schmidt ~Team', new Set(['who'])))`));
  check(off.title === 'Call @Anna Schmidt' && off.assignee_id === undefined && off.chips.some(c => c.type === 'who' && c.off), `who switched off: ${JSON.stringify(off)}`);
  const chips = JSON.parse(w.eval(`JSON.stringify(parseQuick('Call @Anna Schmidt 30 min ~Team', new Set()).chips.map(c => c.type))`));
  check(chips.includes('who') && chips.includes('dur'), `chips for the person and the duration ${chips}`);
  // the body of the new task: the person looked up again in the list the task really goes to
  const b1 = JSON.parse(w.eval(`JSON.stringify(qa2_body(parseQuick('Call @Anna Schmidt ~Team', new Set()), {title: 'Call', list_id: 9901}))`));
  check(b1.assignee_id === 501 && b1.title === 'Call', `qa2_body: assigned in the list ${JSON.stringify(b1)}`);
  const b2 = JSON.parse(w.eval(`JSON.stringify(qa2_body(parseQuick('Call @Anna Schmidt ~Team', new Set()), {title: 'Call', list_id: inbox().id}))`));
  check(b2.assignee_id === undefined && b2.title === 'Call @Anna Schmidt', `qa2_body: not in the real list -> the text stays ${JSON.stringify(b2)}`);
  const b3 = JSON.parse(w.eval(`JSON.stringify(qa2_body(parseQuick('Pay remind me tomorrow 9am 30 min', new Set()), {title: 'Pay', list_id: inbox().id}))`));
  check(b3.remind_at === w.eval(`${D(1)} + 'T09:00'`) && b3.duration === 30 && !b3.due, `qa2_body: remind_at + duration ${JSON.stringify(b3)}`);
  // collaboration off: @ stays text
  w.eval('S.collabAll = false');
  const r0 = JSON.parse(w.eval(`JSON.stringify(parseQuick('Call @Anna Schmidt ~Team', new Set()))`));
  check(r0.title === 'Call @Anna Schmidt' && r0.assignee_id === undefined, `collaboration off: no assignment ${JSON.stringify(r0)}`);
  w.eval('S.collabAll = true');

  // the date dialog: "At a fixed time" (set date + time, the bell, remove), also without a due date
  const t = JSON.parse(await w.eval(`createTask({title: 'Fixed time 2111', list_id: inbox().id}).then(x => JSON.stringify(x || null))`));
  const id = t && t.id;
  check(!!id, 'setup: a task without a date');
  w.eval(`S.settings.date_confirm = ''; datePop(document.querySelector('#top h1') || document.body, ${id})`);
  await sleep(200);
  check(w.eval(`!!document.querySelector('#pop .ratrow #p-ratd') && !!document.querySelector('#pop .ratrow #p-ratt')`), 'the date dialog has the row “At a fixed time”');
  check(w.eval(`document.querySelector('#pop .ratrow').textContent.includes(tr('At a fixed time'))`), 'with its label');
  w.eval(`dpSet(document.getElementById('p-ratd'), '2031-01-02')`);
  await sleep(100);
  w.eval(`dpSet(document.getElementById('p-ratt'), '08:30')`);
  await sleep(1200);
  check(w.eval(`taskById(${id}).remind_at`) === '2031-01-02T08:30', `saved: ${w.eval(`taskById(${id}).remind_at`)}`);
  check(w.eval(`rat_has(taskById(${id})) && !taskById(${id}).due`), 'the bell shows without a due date');
  check(w.eval(`!!document.querySelector('#pop [data-q="ratx"]')`), 'a remove button');
  w.eval(`document.querySelector('#pop [data-q="ratx"]').click()`);
  await sleep(1200);
  check(!w.eval(`taskById(${id}).remind_at`), `removed: ${w.eval(`taskById(${id}).remind_at`)}`);
  w.eval('closePop()');
  check(!errs.length, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  w.close(); srv.close();
  fs.rmSync(OUT, {recursive: true, force: true});
  console.log(`p2111_c_ui: ${ok} ok, ${fails.length} failed`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
