// 2.102.0 UI tests, part A (#1988 the list trash, #2006 invitations without an own calendar), own container (start.sh;
// P2102A_NOSTART=1: a running server). jsdom:
// - deleting an archived list: the dialog says it goes to the trash and can be restored; the list leaves the screen, the
//   toast offers Undo, the undo brings it back (archived, with its task)
// - Trash: "Deleted lists" with name, who / when, the task count; Restore brings it back, "Delete permanently…" asks and
//   deletes it for good; nothing of it in the task rows of the trash
// - a person without an own calendar who is invited to an event: the calendar module shows it (calEvOn, the event in the view)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2102A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,events';
const day = n => { const d = new Date(Date.now() + n * 864e5); return d.toISOString().slice(0, 10); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const BOB = (await call('POST', '/api/users', {orgs: [1], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const st = () => call('GET', '/api/state');

  // ================= #1988 delete -> trash, undo
  const L = (await call('POST', '/api/lists', {name: 'Scrapbook', org_id: null})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Collect ideas', list_id: L})).id;
  await call('PATCH', `/api/lists/${L}`, {archived: 1});
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  w.__dialogs = 'manual';
  await until(() => w.eval(`!!listById(${L})`));
  let p = w.eval(`listDeleteForGood(${L})`);
  const dlg = await until(() => d.querySelector('.modal.cdlg [data-cd="yes"]') && d.querySelector('.modal.cdlg'));
  const txt = (dlg?.textContent || '').replace(/\s+/g, ' ');
  check(/Delete “Scrapbook”\?/.test(txt) && /goes to the trash with its tasks/.test(txt) && /restored there for 30 days/.test(txt) && !/This cannot be undone/.test(txt),
    'the dialog: into the trash, restorable for 30 days ' + txt.slice(0, 300));
  click(w, dlg.querySelector('[data-cd="yes"]'));
  check(await p === true && await until(async () => !(await st()).lists.some(l => l.id === L), 60), 'the list is gone from the state');
  const toast = await until(() => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && /moved to the trash/.test(t.textContent) ? t : null; });
  check(toast && /Undo/.test(toast.textContent), 'the toast says "moved to the trash" and offers Undo ' + (toast?.textContent || ''));
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await st()).lists.some(l => l.id === L && l.archived), 60), 'undo: the list is back (archived)');
  check((await call('GET', '/api/trash/lists')).lists?.length === 0 && (await call('GET', `/api/tasks/${T}`)).status !== 404, 'undo: nothing left in the list trash, its task is reachable');

  // ================= the trash page: "Deleted lists"
  check((await call('DELETE', `/api/lists/${L}`)).trash === true, 'setup: into the trash again');
  w.eval(`load().then(() => go('trash'))`);
  let row = await until(() => d.querySelector(`#view .otrlists [data-otr="${L}"]`));
  check(row && /Deleted lists/.test(d.querySelector('#view .otrlists .ghead')?.textContent || ''), 'Trash: the section "Deleted lists"');
  check(row && /Scrapbook/.test(row.textContent) && /Alice/.test(row.textContent) && /1 task/.test(row.textContent), 'the row: name, by whom, 1 task ' + (row?.textContent || ''));
  check(!d.querySelector(`#view .trow[data-id="${T}"]`), 'its task is not a row of the task trash');
  check(/30 days/.test(d.querySelector('#view .otrnote')?.textContent || ''), 'the period is named');
  click(w, row.querySelector('[data-otra="restore"]'));
  check(await until(async () => (await st()).lists.some(l => l.id === L), 60), 'Restore: the list is back');
  check(await until(() => !d.querySelector(`#view .otrlists [data-otr="${L}"]`)), 'Restore: gone from the trash section');
  await call('DELETE', `/api/lists/${L}`);
  w.eval(`S.otr.at = 0; renderView()`);
  row = await until(() => d.querySelector(`#view .otrlists [data-otr="${L}"]`));
  click(w, row.querySelector('[data-otra="purge"]'));
  const cd = await until(() => d.querySelector('.modal.cdlg [data-cd="yes"]') && d.querySelector('.modal.cdlg'));
  check(cd && /permanently/.test(cd.textContent) && /cannot be undone/.test(cd.textContent), 'Delete permanently asks first');
  click(w, cd.querySelector('[data-cd="yes"]'));
  check(await until(async () => (await call('GET', '/api/trash/lists')).lists?.length === 0, 60), 'deleted for good: the list trash is empty');
  check(await until(() => !d.querySelector('#view .otrlists')), 'the section disappears');
  w.close();

  // ================= #2006 invited without an own calendar
  const CAL = await call('POST', '/api/evcals', {name: 'Studio'});
  const cid = CAL.id || CAL.cal?.id;
  const ev = await call('POST', '/api/events', {title: 'Kick-off meeting', cal_id: cid, start: day(0) + 'T23:00', end: day(0) + 'T23:30', attendees: [{user_id: BOB}]});
  check(ev.status === 200 || ev.status === 201, 'setup: an event with bob invited ' + JSON.stringify(ev).slice(0, 200));
  w = await boot({user: 'bob', hash: 'cal', ls: {'tasks.calMode': '"month"'}}); d = w.document;
  await sleep(600);
  check(w.eval('(S.evcals || []).length') === 0, 'bob has no own calendar');
  check(String(w.eval('S.evsig')).split('|')[0] === '1', 'his state counts the invitation');
  check(w.eval('calEvOn()') === true, '#2006: the calendar shows events without an own calendar');
  check(await until(() => /Kick-off meeting/.test(d.querySelector('#view')?.textContent || ''), 60), '#2006: the invited event is in the calendar view');
  w.close();
  void ME;

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
