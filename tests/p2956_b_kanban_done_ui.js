// 2.956.0 UI tests part B (jsdom), fresh DB, invented data only:
// kalmido-suite: fresh
// - #3912 a board column with the meaning done / rejected (sections.kind) shows the tasks completed / marked "won't do" in
//   it: a tick moves the card into the done column and it stays visible there (title shown, crossed out, not dragged by the
//   mouse); the number in the column head counts only the open tasks; more than 5 -> the newest 5 and "Show N more tasks",
//   which shows the rest and folds back; the rejected column the same; a board with only completed cards is not "empty";
//   the board in swimlanes shows them in the lane too. Also for a person without an organisation (freelancer-matrix: lists).
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'kanban,collab,comments';

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  // a person without an organisation (as tests/freelancer_fixture.py: created by the admin without orgs)
  await call(CK, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});

  const P = (await call(CK, 'POST', '/api/lists', {name: 'Garden plan'})).id;
  const OPEN = (await call(CK, 'POST', '/api/sections', {list_id: P, name: 'To do', kind: 'open'})).id;
  const DONE = (await call(CK, 'POST', '/api/sections', {list_id: P, name: 'Finished', kind: 'done'})).id;
  const REJ = (await call(CK, 'POST', '/api/sections', {list_id: P, name: 'Dropped', kind: 'rejected'})).id;
  const T = [];
  for (let i = 1; i <= 9; i++) T.push((await call(CK, 'POST', '/api/tasks', {title: 'Bed ' + i, list_id: P, section_id: OPEN})).id);
  await call(CK, 'PATCH', `/api/lists/${P}`, {view: 'kanban'});

  const w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  const col = sid => d.querySelector(`#view .kanban:not(.swl) .kcol[data-kcol="${sid}"]`);
  const cards = sid => [...(col(sid)?.querySelectorAll('.kcards .trow[data-id]') || [])];
  const ids = sid => cards(sid).map(r => +r.dataset.id);
  const headN = sid => col(sid)?.querySelector('.khead .c')?.textContent.trim();
  check(await until(() => cards(OPEN).length === 9), 'setup: the board with 9 cards in "To do"');
  check(cards(DONE).length === 0 && headN(DONE) === '0', 'setup: "Finished" is empty');

  // ---- a tick: the card moves into the done column and stays visible there
  await w.eval(`toggleTask(${T[0]})`);
  check(await until(() => ids(DONE).includes(T[0])), '#3912: the ticked card is shown in the done column');
  const c0 = cards(DONE)[0];
  check(/Bed 1/.test(c0?.querySelector('.ttl')?.textContent || ''), '#3912: its title is visible ' + (c0?.textContent || '').trim().slice(0, 60));
  check(c0?.classList.contains('done'), '#3912: it looks completed (crossed out)');
  check(c0 && !c0.hasAttribute('draggable'), '#3912: the mouse does not drag a completed card');
  check(headN(DONE) === '0' && headN(OPEN) === '8', `#3912: the heads count only open tasks (done ${headN(DONE)}, open ${headN(OPEN)})`);
  check(!ids(OPEN).includes(T[0]), '#3912: the card left "To do"');

  // ---- more than 5: the newest 5, the rest behind "Show N more tasks"
  for (const id of T.slice(1, 7)) await call(CK, 'PATCH', `/api/tasks/${id}`, {section_id: DONE});
  const st = await call(CK, 'GET', `/api/tasks/${T[6]}`);
  check(st.status === 2, '#3912: a move into the done column completes the task (server) ' + st.status);
  await w.eval('load().then(() => render())');
  check(await until(() => cards(DONE).length === 5), '#3912: 7 completed -> 5 shown ' + cards(DONE).length);
  check(!ids(DONE).includes(T[0]), '#3912: the oldest (the first ticked) is behind "more"');
  check(ids(DONE)[0] === T[6], '#3912: the newest first ' + JSON.stringify(ids(DONE)));
  let more = col(DONE)?.querySelector('.kdnmore');
  check(/Show 2 more tasks/.test(more?.textContent || '') && more?.getAttribute('aria-expanded') === 'false', '#3912: "Show 2 more tasks" ' + (more?.textContent || ''));
  check(headN(DONE) === '0' && headN(OPEN) === '2', '#3912: the heads still count only the open ones');
  click(w, more);
  check(await until(() => cards(DONE).length === 7), '#3912: "more" shows all 7');
  check(ids(DONE).includes(T[0]), '#3912: the oldest is there now');
  more = col(DONE)?.querySelector('.kdnmore');
  check(/Show less/.test(more?.textContent || '') && more?.getAttribute('aria-expanded') === 'true', '#3912: and offers "Show less"');
  click(w, more);
  check(await until(() => cards(DONE).length === 5), '#3912: "Show less" folds back to 5');

  // ---- the rejected column
  await call(CK, 'PATCH', `/api/tasks/${T[7]}`, {section_id: REJ});
  check((await call(CK, 'GET', `/api/tasks/${T[7]}`)).status === -1, '#3912: a move into the rejected column = won\'t do (server)');
  await w.eval('load().then(() => render())');
  check(await until(() => ids(REJ).includes(T[7])), '#3912: the rejected card is shown in its column');
  check(cards(REJ)[0]?.classList.contains('done') && headN(REJ) === '0', '#3912: crossed out, not counted');

  // ---- the board in swimlanes (by priority): the completed cards are in their lane's done column
  w.eval(`swlSet(${P}, 'prio')`);
  const lane = k => d.querySelector(`#view .kanban.swl .swlane[data-swl="${k}"]`);
  const lcards = (k, sid) => [...(lane(k)?.querySelectorAll(`.kcol[data-kcol="${sid}"] .kcards .trow[data-id]`) || [])];
  check(await until(() => lcards('p0', DONE).length === 5), '#3912 lanes: the lane shows 5 completed cards ' + lcards('p0', DONE).length);
  const top = d.querySelector(`#view .kanban.swl .swlhrow .kcol[data-kcol="${DONE}"] .khead .c`)?.textContent.trim();
  check(top === '0', '#3912 lanes: the column head counts only open ones ' + top);
  click(w, lane('p0')?.querySelector(`.kcol[data-kcol="${DONE}"] .kdnmore`));
  check(await until(() => lcards('p0', DONE).length === 7), '#3912 lanes: "more" in the lane shows all 7');
  check(lcards('p0', REJ).length === 1, '#3912 lanes: the rejected card too');
  w.eval(`swlSet(${P}, '')`);
  check(errs.length === 0, 'no script errors ' + JSON.stringify(errs));
  w.close();

  // ---- a person without an organisation, a board with only completed cards: not "No tasks."
  const Q = (await call(CF, 'POST', '/api/lists', {name: 'Moving house'})).id;
  await call(CF, 'POST', '/api/sections', {list_id: Q, name: 'Open', kind: 'open'});
  const QD = (await call(CF, 'POST', '/api/sections', {list_id: Q, name: 'Done', kind: 'done'})).id;
  const QT = (await call(CF, 'POST', '/api/tasks', {title: 'Order boxes', list_id: Q})).id;
  await call(CF, 'PATCH', `/api/tasks/${QT}`, {section_id: QD});
  await call(CF, 'PATCH', `/api/lists/${Q}`, {view: 'kanban'});
  const wf = await boot({user: 'frida', hash: 'l/' + Q}), df = wf.document;
  const fc = () => df.querySelector(`#view .kcol[data-kcol="${QD}"] .kcards .trow[data-id="${QT}"]`);
  check(await until(() => fc()), '#3912 freelancer: the completed card is on the board');
  check(/Order boxes/.test(fc()?.textContent || ''), '#3912 freelancer: with its title');
  check(!df.querySelector('#view .kempty'), '#3912: a board with only completed cards does not say "No tasks."');
  check(errs.length === 0, 'freelancer: no script errors ' + JSON.stringify(errs));
  wf.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
