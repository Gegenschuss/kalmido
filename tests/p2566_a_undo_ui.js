// 2.566.0 A (#4704) UI tests, own container (start.sh, mode workspaces), jsdom, invented data only:
// kalmido-suite: fresh
// An Undo is a second write that never overwrites what someone else saved meanwhile (core.js undoWrite / undoStep: only the
// keys the step changed, with expect_updated_at of the own save). Two sessions of the same person: the page (A) and a second
// one (B, the API), run for a member of an organisation and for a person without an organisation (freelancer parity).
// - a letter (the toast's Undo): A saves the subject, B changes the reference line, A presses Undo -> B's reference line
//   stays, A's subject stays (not undone), the toast says "Changed elsewhere, not undone"; without a change elsewhere the
//   Undo takes the subject back as before
// - a budget entry (the history step, Ctrl+Z): A saves the amount, B renames the entry, A undoes -> B's title stays, the
//   amount is not undone, the message says so; without a change elsewhere the amount goes back
// - the server checks that came with it: PATCH /api/polls/<id> and /api/appt/types/<id>, PUT /api/appt/page answer 409 with
//   the current state for an old expect_updated_at and save with the current one
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,events,collab,office,clients,budget,contracts';
const DAY = TC.today(), MONTH = DAY.slice(0, 7), OLD = '2001-01-01T00:00:00Z';
// B saves (without a version, like an old client) until its save has a later updated_at than `was` (whole seconds)
async function otherSave(ck, url, body, was, pick = j => j) {
  let j = null;
  await until(async () => { j = await call(ck, 'PATCH', url, body); return j.http === 200 && pick(j)?.updated_at && pick(j).updated_at !== was; });
  return j;
}

async function round(who, ck) {
  // ================= a letter: the toast's Undo
  const L = await call(ck, 'POST', '/api/office/letters', {rcpt_name: 'Example Authority', subject: 'First subject'});
  check(L.http === 201 && L.id, `${who}: a letter draft ${L.http}`);
  const getL = async () => call(ck, 'GET', `/api/office/letters/${L.id}`);
  let w = await boot({user: who, hash: `office/letters/${L.id}`}); let d = w.document;
  const toastText = () => d.querySelector('#toast')?.textContent || '';
  const undoBtn = () => d.querySelector('#toast:not(.hidden) button:not(.tx)');
  const saveSubject = async v => {
    await until(() => d.querySelector('#lt-subject') && d.querySelector('[data-lt="save"]'));
    const inp = d.querySelector('#lt-subject'); inp.value = v; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
    click(w, d.querySelector('[data-lt="save"]'));
  };
  await saveSubject('Second subject');
  check(await until(async () => (await getL()).subject === 'Second subject'), `${who}: A saved the subject`);
  check(await until(() => /Saved/.test(toastText()) && undoBtn()), `${who}: "Saved" with Undo: ${toastText()}`);
  const saved = await getL();
  const o = await otherSave(ck, `/api/office/letters/${L.id}`, {ref_line: 'Reference of B'}, saved.updated_at);
  check(o?.ref_line === 'Reference of B', `${who}: B changed the reference line of the same letter`);
  click(w, undoBtn());
  check(await until(() => /Changed elsewhere, not undone/.test(toastText())), `${who}: the Undo says it was changed elsewhere: ${toastText()}`);
  let now = await getL();
  check(now.ref_line === 'Reference of B', `${who}: B's reference line stays (not overwritten by the undo) ` + now.ref_line);
  check(now.subject === 'Second subject', `${who}: the subject is not undone either ` + now.subject);
  // without a change elsewhere: the Undo works as before (the page shows B's version first)
  check(await until(() => d.querySelector('#lt-ref_line')?.value === 'Reference of B'), `${who}: the editor shows the saved letter again`);
  await saveSubject('Third subject');
  check(await until(async () => (await getL()).subject === 'Third subject'), `${who}: A saved again`);
  check(await until(() => /Saved/.test(toastText()) && undoBtn()), `${who}: "Saved" with Undo again`);
  click(w, undoBtn());
  check(await until(async () => (await getL()).subject === 'Second subject'), `${who}: Undo without a change elsewhere takes the subject back`);
  now = await getL();
  check(now.ref_line === 'Reference of B', `${who}: ... and leaves the other fields as they are ` + now.ref_line);
  w.close();

  // ================= a budget entry: the history step
  const LID = (await call(ck, 'POST', '/api/budget/lists', {})).list_id;
  check(LID > 0, `${who}: a budget`);
  const rent = await call(ck, 'POST', `/api/budget/${LID}/entries`, {day: DAY, amount: 800, kind: 'out', title: 'Rent'});
  const entry = async () => ((await call(ck, 'GET', `/api/budget/${LID}?month=${MONTH}`)).entries || []).find(x => x.id === rent.id) || {};
  w = await boot({user: who, hash: `budget/${LID}`}); d = w.document;
  const dlg = () => d.querySelector('.modal.bgdlg');
  const rowOf = re => [...d.querySelectorAll('.bgview [data-bg="entry"]')].find(b => re.test(b.textContent));
  const msg = () => d.querySelector('#toast')?.textContent || '';
  const edit = async (re, amt) => {
    check(await until(() => rowOf(re)), `${who}: the row ${re}`);
    click(w, rowOf(re)); await until(() => dlg()?.querySelector('#bg-amt'));
    dlg().querySelector('#bg-amt').value = amt; click(w, dlg().querySelector('[data-m="save"]'));
  };
  await edit(/Rent/, '99');
  check(await until(async () => +(await entry()).amount === 99), `${who}: A saved the amount 99`);
  const e1 = await entry();
  const o2 = await otherSave(ck, `/api/budget/entries/${rent.id}`, {title: 'Rent of B'}, e1.updated_at);
  check(o2?.title === 'Rent of B', `${who}: B renamed the same entry`);
  await w.eval(`histStep('undo')`);
  check(await until(() => /Changed elsewhere, not undone/.test(msg())), `${who}: the undo says it was changed elsewhere: ${msg()}`);
  let en = await entry();
  check(en.title === 'Rent of B', `${who}: B's title stays (not overwritten by the undo) ` + en.title);
  check(+en.amount === 99, `${who}: the amount is not undone either ` + en.amount);
  // without a change elsewhere: the undo works as before
  check(await until(() => rowOf(/Rent of B/)), `${who}: the page shows B's title (reloaded after the undo)`);
  await edit(/Rent of B/, '77');
  check(await until(async () => +(await entry()).amount === 77), `${who}: A saved the amount 77`);
  await w.eval(`histStep('undo')`);
  check(await until(async () => +(await entry()).amount === 99), `${who}: undo without a change elsewhere takes the amount back to 99`);
  en = await entry();
  check(en.title === 'Rent of B', `${who}: ... and leaves the title as it is ` + en.title);
  w.close();

  // ================= the server checks that came with it (an old version -> 409 with the current state, the current one saves)
  const P = await call(ck, 'POST', '/api/polls', {title: 'Kick-off', duration: 30, options: [{start: `${TC.day(7)}T10:00`}, {start: `${TC.day(7)}T11:00`}]});
  check(P.http === 201 && P.poll?.updated_at, `${who}: a poll ${P.http}`);
  if (P.poll) {
    const x = await call(ck, 'PATCH', `/api/polls/${P.poll.id}`, {title: 'Old', expect_updated_at: OLD});
    check(x.http === 409 && x.poll?.title === 'Kick-off', `${who}: poll with an old version: 409 with the poll ${x.http}`);
    const y = await call(ck, 'PATCH', `/api/polls/${P.poll.id}`, {title: 'Kick-off 2', expect_updated_at: P.poll.updated_at});
    check(y.http === 200 && y.poll?.title === 'Kick-off 2', `${who}: poll with the current version saves ${y.http}`);
  }
  const T = await call(ck, 'POST', '/api/appt/types', {name: 'Call', duration_min: 30});
  check(T.http === 201 && T.updated_at, `${who}: an appointment type with updated_at ${T.http}`);
  if (T.id) {
    const x = await call(ck, 'PATCH', `/api/appt/types/${T.id}`, {name: 'Old', expect_updated_at: OLD});
    check(x.http === 409 && x.type?.name === 'Call', `${who}: appointment type with an old version: 409 with the type ${x.http}`);
    const y = await call(ck, 'PATCH', `/api/appt/types/${T.id}`, {name: 'Call 2', expect_updated_at: T.updated_at});
    check(y.http === 200 && y.name === 'Call 2', `${who}: appointment type with the current version saves ${y.http}`);
  }
  const pg = await call(ck, 'PUT', '/api/appt/page', {title: 'Book me'});
  check(pg.http === 200 && pg.page?.updated_at, `${who}: the booking page with updated_at ${pg.http}`);
  if (pg.page?.updated_at) {
    const x = await call(ck, 'PUT', '/api/appt/page', {title: 'Old', expect_updated_at: OLD});
    // 2.566.0 (#4704): the page's 409 carries it under "current" (#4701 on main, the same check)
    check(x.http === 409 && x.current?.page?.title === 'Book me', `${who}: booking page with an old version: 409 with the page ${x.http}`);
    const y = await call(ck, 'PUT', '/api/appt/page', {title: 'Book me 2', expect_updated_at: pg.page.updated_at});
    check(y.http === 200 && y.page?.title === 'Book me 2', `${who}: booking page with the current version saves ${y.http}`);
  }
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await round('alice', CA);

  // ================= a person without an organisation: the same
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  await round('frida', CF);

  console.log(`p2566_a_undo_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
