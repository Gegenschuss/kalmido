// 2.576.0 UI test, part B (#4764): the dialogs of the budget, the time tracking, the journal and the tables after someone else
// kalmido-suite: fresh
// saved meanwhile (a second session of the same person), jsdom, invented names only. objsave.js saveDialog / objMerge:
// - budget entry: only the changed field goes (+ the version); a 409 opens the dialog again with the saved entry, the own input
//   over it and the other's field marked; saving again keeps both; an open dialog shows "Changed by someone else" + Take over
// - budget template (recurring): the same in its form
// - time entry: only the changed field with _prev; the 409 opens the dialog again, the other's note marked, the own switch stays
// - journal: the own text stays in the field after the 409, marked; "Keep mine" saves it, "Take theirs" shows the other one
// - table column dialog: a title changed elsewhere comes back marked with the own title in the field; saving again writes it
// - the phone width once (budget entry): the bar inside the dialog's card
// No bar "Reload" any more anywhere here.
// freelancer-matrix: personal, time, sheets (alice has no organisation: her private workspace)
// Every wait is on a real state (the server's object, the dialog's fields), never on a fixed time.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, CK2;  // two sessions of alice
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, t = 15000) => until0(fn, {timeout: t, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DAY = TC.today(), MONTH = DAY.slice(0, 7);
const spy = w => {
  w.__sent = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => { const m = o.method || 'GET'; if (m === 'PATCH' || m === 'PUT') { try { w.__sent.push({m, u: String(u), b: JSON.parse(o.body)}); } catch { w.__sent.push({m, u: String(u), b: null}); } } return f1(u, o); };
};
const marked = el => !!el?.closest('.obj-theirs');
const keys = b => JSON.stringify(Object.keys(b || {}).sort());

async function budgetChecks(LID) {
  const rent = await call(CK, 'POST', `/api/budget/${LID}/entries`, {day: DAY, amount: 800, kind: 'out', title: 'Rent'});
  check(rent.id && rent.updated_at, 'budget: an entry ' + JSON.stringify(rent).slice(0, 200));
  const w = await boot({user: 'alice', hash: `budget/${LID}`}), d = w.document;
  const dlg = () => d.querySelector('.modal.bgdlg');
  const row = () => [...d.querySelectorAll('.bgview [data-bg="entry"]')].find(b => /Rent/.test(b.textContent));
  const srv = async () => (await call(CK, 'GET', `/api/budget/entries/${rent.id}`));
  check(await until(() => row()), 'budget: the view shows the entry');
  const open = async () => { click(w, row()); return until(() => dlg()?.querySelector('#bg-title')?.value && typeof w.saveDialog === 'function' && dlg()); };
  // ---- conflict on save: another field changed elsewhere
  spy(w);
  let md = await open();
  check((await call(CK2, 'PATCH', `/api/budget/entries/${rent.id}`, {title: 'Rent flat'})).http === 200, 'budget: the other session changes the title');
  md.querySelector('#bg-amt').value = '900';
  click(w, md.querySelector('[data-m="save"]'));
  md = await until(() => dlg()?.querySelector('.obj-merge') && dlg());
  check(!!md, 'budget: the dialog comes back with the merge bar');
  const first = w.__sent.find(x => x.u.endsWith(`/api/budget/entries/${rent.id}`));
  check(keys(first?.b) === keys({amount: 1, expect_updated_at: 1}), 'budget: only the changed field went (+ the version) ' + JSON.stringify(first?.b));
  if (md) {
    check(md.querySelector('#bg-title').value === 'Rent flat' && /^900/.test(md.querySelector('#bg-amt').value), 'budget: the saved title, the own amount over it ' + md.querySelector('#bg-amt').value);
    check(marked(md.querySelector('#bg-title')) && !marked(md.querySelector('#bg-amt')), 'budget: the other\'s field is marked, the own one not');
    check(!md.querySelector('[data-lf-reload]') && !/Reload/.test(md.textContent), 'budget: no Reload bar');
    click(w, md.querySelector('[data-m="save"]'));
  }
  check(await until(async () => { const x = await srv(); return x.title === 'Rent flat' && +x.amount === 900; }), 'budget: the second save keeps both changes');
  // ---- the bar of an open dialog after the change poll, "Take over"
  md = await until(() => !dlg() && open());
  md.querySelector('#bg-cp').value = 'Landlord';
  check((await call(CK2, 'PATCH', `/api/budget/entries/${rent.id}`, {note: 'Paid by transfer'})).http === 200, 'budget: the other session adds a note');
  const bar = await until(() => dlg()?.querySelector('.obj-stale [data-os="take"]'), 25000);
  check(!!bar, 'budget: the open dialog shows "Changed by someone else" with Take over');
  if (bar) {
    click(w, bar);
    md = await until(() => dlg()?.querySelector('#bg-note')?.value === 'Paid by transfer' && dlg());
    check(md && md.querySelector('#bg-cp').value === 'Landlord' && marked(md.querySelector('#bg-note')), 'budget: Take over: the saved note (marked), the own counterpart stays');
    if (md) click(w, md.querySelector('[data-m="save"]'));
    check(await until(async () => { const x = await srv(); return x.note === 'Paid by transfer' && x.counterpart === 'Landlord'; }), 'budget: saved, both on the server');
  }
  // ---- a template (recurring entry)
  await until(() => !dlg());
  const rec = await call(CK, 'POST', `/api/budget/${LID}/recurring`, {title: 'Gym', amount: 40, kind: 'out', per: 'month', start: MONTH});
  check(rec.id, 'budget: a template');
  w.eval('bg_recModal()');
  const ed = await until(() => dlg()?.querySelector(`[data-redit="${rec.id}"]`));
  click(w, ed);
  md = await until(() => dlg()?.querySelector(`.bgrform[data-rid="${rec.id}"]`) && dlg());
  spy(w);
  check((await call(CK2, 'PATCH', `/api/budget/recurring/${rec.id}`, {amount: 45})).http === 200, 'template: the other session changes the amount');
  md.querySelector('#bg-rt').value = 'Gym and pool';
  click(w, md.querySelector('[data-rsave]'));
  check(await until(() => md.querySelector('.obj-merge') && md.querySelector('#bg-rt')?.value === 'Gym and pool'), 'template: the form comes back with the merge bar and the own title');
  const rs = w.__sent.find(x => x.u.endsWith(`/api/budget/recurring/${rec.id}`));
  check(keys(rs?.b) === keys({title: 1, expect_updated_at: 1}), 'template: only the changed field went ' + JSON.stringify(rs?.b));
  check(/^45/.test(md.querySelector('#bg-ra')?.value || '') && marked(md.querySelector('#bg-ra')) && !marked(md.querySelector('#bg-rt')), 'template: the saved amount marked, the own title not');
  click(w, md.querySelector('[data-rsave]'));
  check(await until(async () => { const x = await call(CK, 'GET', `/api/budget/recurring/${rec.id}`); return x.title === 'Gym and pool' && +x.amount === 45; }), 'template: the second save keeps both');
  w.close();
}

async function timeChecks() {
  const L = (await call(CK, 'POST', '/api/lists', {name: 'Garden', kind: 'project', time_tracking: 1})).id;
  const T = (await call(CK, 'POST', '/api/tasks', {title: 'Cut the hedge', list_id: L})).id;
  const te = await call(CK, 'POST', '/api/time/entries', {task_id: T, start: `${DAY}T09:00`, minutes: 30, note: 'Front'});
  check(te.id && te.updated_at, 'time: an entry with its version ' + JSON.stringify(te).slice(0, 200));
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  await until(() => w.eval('typeof entryModal === "function"'));
  spy(w);
  w.eval(`entryModal(${JSON.stringify(te)})`);
  let md = await until(() => d.querySelector('.modal #te-note') && typeof w.saveDialog === 'function' && d.querySelector('#te-note').closest('.modal'));
  check((await call(CK2, 'PATCH', `/api/time/entries/${te.id}`, {note: 'Front and back'})).http === 200, 'time: the other session changes the note');
  md.querySelector('#te-bill').checked = false;
  click(w, md.querySelector('[data-m="save"]'));
  md = await until(() => { const m = d.querySelector('.modal .obj-merge')?.closest('.modal'); return m && m.querySelector('#te-note') && m; });
  check(!!md, 'time: the dialog comes back with the merge bar');
  const first = w.__sent.find(x => x.u.endsWith(`/api/time/entries/${te.id}`));
  check(keys(first?.b) === keys({billable: 1, _prev: 1}) && first.b._prev.billable === true, 'time: only the changed field went, with what the dialog showed ' + JSON.stringify(first?.b));
  if (md) {
    check(md.querySelector('#te-note').value === 'Front and back' && marked(md.querySelector('#te-note')), 'time: the saved note, marked');
    check(md.querySelector('#te-bill').checked === false && !marked(md.querySelector('#te-bill')), 'time: the own switch stays');
    check(!md.querySelector('[data-oxb-reload]'), 'time: no Reload bar');
    click(w, md.querySelector('[data-m="save"]'));
  }
  check(await until(async () => { const x = await call(CK, 'GET', `/api/time/entries/${te.id}`); return x.note === 'Front and back' && x.billable === false; }), 'time: the second save keeps both');
  w.close();
}

async function journalChecks() {
  const w = await boot({user: 'alice', hash: 'review'}), d = w.document;
  const ta = () => d.querySelector('#rv-text');
  check(await until(() => ta()?.dataset.day), 'journal: the review shows the journal');
  const day = ta().dataset.day, url = `/api/life/journal/${day}`;
  const type = text => { const t = ta(); t.focus(); t.value = text; t.dispatchEvent(new w.Event('input', {bubbles: true})); t.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true})); };
  const srv = async () => (await call(CK, 'GET', `/api/life/journal?from=${day}&to=${day}`)).entries?.find(x => x.day === day);
  // ---- "Keep mine"
  check((await call(CK2, 'PUT', url, {text: 'Rain all day', expect_updated_at: ''})).http === 200, 'journal: the other session writes the day');
  type('Sun in the morning');
  const bar = await until(() => d.querySelector('.rvjournal .obj-merge'));
  check(!!bar, 'journal: the 409 shows the merge bar');
  check(ta().value === 'Sun in the morning' && marked(ta()), 'journal: the own text stays in the field, marked');
  check(!d.querySelector('[data-rv-reload]'), 'journal: no Reload bar');
  check((await srv())?.text === 'Rain all day', 'journal: the other text stays on the server meanwhile');
  click(w, bar?.querySelector('[data-om="mine"]'));
  check(await until(async () => (await srv())?.text === 'Sun in the morning'), 'journal: "Keep mine" saves the own text');
  // ---- "Take theirs"
  const now = (await call(CK2, 'PUT', url, {text: '-', expect_updated_at: 'not-this-one'})).entry;  // the version: a 409 names it, writes nothing
  check((await call(CK2, 'PUT', url, {text: 'Rain, then sun', expect_updated_at: now?.updated_at})).http === 200, 'journal: the other session writes again');
  type('Only sun');
  const bar2 = await until(() => d.querySelector('.rvjournal .obj-merge'));
  check(!!bar2, 'journal: the second 409 shows the bar');
  click(w, bar2?.querySelector('[data-om="theirs"]'));
  check(await until(() => ta()?.value === 'Rain, then sun' && !d.querySelector('.rvjournal .obj-merge')), 'journal: "Take theirs" shows the saved text ' + ta()?.value);
  check((await srv())?.text === 'Rain, then sun', 'journal: nothing overwritten');
  w.close();
}

async function sheetChecks() {
  const sh = await call(CK, 'POST', '/api/sheets', {title: 'Plan', space: 'private'});
  check(sh.id, 'table: created ' + JSON.stringify(sh).slice(0, 160));
  const cid = (await call(CK, 'GET', `/api/sheets/${sh.id}`)).columns?.[0]?.id;
  const w = await boot({user: 'alice', hash: 'sheets/' + sh.id}), d = w.document;
  check(await until(() => w.eval(`SHV.sh?.id === ${sh.id} && !!SHV.sh._col.get(${cid})`)), 'table: the table shows');
  w.eval(`shvColModal(SHV.sh._col.get(${cid}))`);
  let md = await until(() => d.querySelector('.modal.shvcmd'));
  check((await call(CK2, 'PATCH', `/api/sheets/${sh.id}/columns/${cid}`, {title: 'Hours'})).http === 200, 'table: the other session renames the column');
  md.querySelector('#shv-ct').value = 'Rate';
  click(w, md.querySelector('[data-m="save"]'));
  md = await until(() => { const m = d.querySelector('.modal.shvcmd'); return m && m.querySelector('.obj-merge') && m; });
  check(!!md, 'table: the dialog comes back with the merge bar');
  if (md) {
    check(md.querySelector('#shv-ct').value === 'Rate' && marked(md.querySelector('#shv-ct')), 'table: the own title stays in the field, marked (title: the saved one)');
    check(/Hours/.test(md.querySelector('#shv-ct').closest('.obj-theirs')?.title || ''), 'table: the mark names the saved title');
    click(w, md.querySelector('[data-m="save"]'));
  }
  check(await until(async () => (await call(CK, 'GET', `/api/sheets/${sh.id}`)).columns?.find(c => c.id === cid)?.title === 'Rate'), 'table: the second save writes the own title');
  w.close();
}

async function phoneCheck(LID) {
  const e = await call(CK, 'POST', `/api/budget/${LID}/entries`, {day: DAY, amount: 12, kind: 'out', title: 'Coffee'});
  const w = await boot({user: 'alice', hash: `budget/${LID}`, mobile: true}), d = w.document;
  const row = () => [...d.querySelectorAll('.bgview [data-bg="entry"]')].find(b => /Coffee/.test(b.textContent));
  check(await until(() => row()), 'phone: the budget shows');
  click(w, row());
  let md = await until(() => d.querySelector('.modal.bgdlg #bg-title')?.value === 'Coffee' && typeof w.saveDialog === 'function' && d.querySelector('.modal.bgdlg'));
  await call(CK2, 'PATCH', `/api/budget/entries/${e.id}`, {title: 'Coffee beans'});
  md.querySelector('#bg-note').value = 'For the office';
  click(w, md.querySelector('[data-m="save"]'));
  md = await until(() => { const m = d.querySelector('.modal.bgdlg'); return m && m.querySelector('.obj-merge') && m; });
  check(md && md.querySelector('.card .obj-merge') && marked(md.querySelector('#bg-title')) && md.querySelector('#bg-note').value === 'For the office',
    'phone: the bar inside the dialog card, the title marked, the own note stays');
  w.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  CK = await login('alice'); CK2 = await login('alice');
  await call(CK, 'POST', '/api/admin/setup', {lang: 'en', time_all: true});
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,contracts,budget,time,review,sheets'});
  const st = await call(CK, 'GET', '/api/state');
  check(!(st.me?.workspaces || []).length, 'alice has no organisation');
  const LID = (await call(CK, 'POST', '/api/budget/lists', {})).list_id;
  check(LID > 0, 'a budget');
  await budgetChecks(LID);
  await timeChecks();
  await journalChecks();
  await sheetChecks();
  await phoneCheck(LID);
  console.log(`p2576_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
