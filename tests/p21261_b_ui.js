// 2.126.1 UI tests (part B), own container (start.sh). jsdom:
// #2125 the proposal card of kind sheet_tasks: the table (link) and the list, one row per table row as the person sees it
//       (the agent's title over the cell's, the row number), a row without a title greyed out with its reason, the count
//       "Apply 2 entries"; an edited title and an unticked row reach the server (one task, the edited title); the row then
//       carries the mark "Carried over"
// #2126 the plan dialog: the field Kind (Job in the chat | Sort the basket (proposal)); choosing "Sort the basket" fills
//       title, every working day, 07:30, hides the list, marks the text optional and shows its own hint; saving without a
//       text works and the row reads "Sort the basket · …"
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21261B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const input = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const FEAT = 'cal,comments,collab,agents,sheets';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments', 'sheets:read'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const L = (await call('POST', '/api/lists', {name: 'Shoot'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const sh = await call('POST', '/api/sheets', {title: 'Shot list', space: 'private'});
  const C = sh.columns.map(c => c.id), R = sh.rows.map(x => x.id);
  await call('PUT', `/api/sheets/${sh.id}/cells`, {cells: [{row_id: R[0], col_id: C[0], raw: 'Camera check'}, {row_id: R[1], col_id: C[0], raw: 'Book studio'},
    {row_id: R[2], col_id: C[1], raw: 'no title here'}]});
  check((await call('POST', `/api/sheets/${sh.id}/shares`, {user_id: AG, role: 'read'})).status === 201, 'setup: the table shared with the agent');
  const J = await v1(ag.token, 'POST', '/agent/proposals/sheet-tasks', {sheet_id: sh.id, rows: [R[0], {row_id: R[1], title: 'Book the studio'}, R[2]], list_id: L, title_col: C[0]});
  check(J.status === 201, 'the agent proposes three rows ' + JSON.stringify(J).slice(0, 200));

  // ================= #2125 the card
  let w = await boot({user: 'alice', hash: 'prop/' + J.id}), d = w.document;
  const md = await until(() => d.querySelector('.modal.ppm'));
  check(md && /Tasks from the table Shot list/.test(md.querySelector('h3').textContent), '#2125: #prop/<id> opens the card');
  const where = md.querySelector('.pptask');
  check(where && where.querySelector(`a[href="#sheets/${sh.id}"]`) && /Shoot/.test(where.textContent), '#2125: the table (link) and the list');
  let rows = [...md.querySelectorAll('.ppi')];
  check(rows.length === 3 && rows[0].querySelector('.ppt').value === 'Camera check' && rows[1].querySelector('.ppt').value === 'Book the studio'
    && /Book studio/.test(rows[1].querySelector('.ppo')?.textContent || '') && /Row 1/.test(rows[0].textContent), '#2125: the rows, the agent title over the cell, the row number');
  check(rows[2].classList.contains('shtx') && rows[2].querySelector('.ppc').disabled && /No title in this row/.test(rows[2].textContent), '#2125: the row without a title is greyed out with its reason');
  check(/Apply 2 entries/.test(md.querySelector('[data-pp="apply"]').textContent) && /2 of 2 selected/.test(md.querySelector('.ppcount').textContent), '#2125: Apply 2 entries');
  check(/carried over/i.test(md.querySelector('.shint').textContent), '#2125: the hint names the mark');
  input(w, rows[0].querySelector('.ppt'), 'Check the camera');
  const c1 = rows[1].querySelector('.ppc'); c1.checked = false; change(w, c1);
  check(/Apply 1 entry/.test(md.querySelector('[data-pp="apply"]').textContent), '#2125: unticked -> Apply 1 entry');
  click(w, md.querySelector('[data-pp="apply"]'));
  await until(() => !d.querySelector('.modal.ppm'), 60);
  const st = await call('GET', '/api/state');
  const made = (st.tasks || []).filter(t => t.list_id === L).map(t => t.title);
  check(made.length === 1 && made[0] === 'Check the camera', '#2125: one task with the edited title ' + JSON.stringify(made));
  const lk = await call('GET', `/api/sheets/${sh.id}/links`);
  check((lk.links || []).filter(x => x.kind === 'task').map(x => x.row_id).join() === String(R[0]), '#2125: only the first row carries the mark');
  w.close();

  // ================= #2126 the plan dialog: Kind
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  await until(() => d.querySelector(`[data-act="sched-open"][data-aid="${AG}"]`));
  click(w, d.querySelector(`[data-act="sched-open"][data-aid="${AG}"]`));
  const sm = await until(() => d.querySelector('.modal.schedmd'));
  click(w, sm.querySelector('[data-sm="new"]')); await until(() => d.getElementById('sc-act'));
  const act = d.getElementById('sc-act');
  check(act && act.value === 'chat' && [...act.options].map(o => o.textContent).join('|') === 'Job in the chat|Sort the basket (proposal)', '#2126: Kind, default the chat');
  check(!d.getElementById('sc-listrow').hidden && d.querySelector('.schedopt').hidden, '#2126: chat: list shown, the text is needed');
  act.value = 'triage'; change(w, act); await sleep(50);
  check(d.getElementById('sc-title').value === 'Sort the basket' && d.getElementById('sc-freq').value === 'weekdays' && d.getElementById('sc-time').value === '07:30',
    '#2126: Sort the basket: title, every working day, 07:30');
  check(d.getElementById('sc-listrow').hidden && !d.querySelector('.schedopt').hidden && !d.getElementById('sc-trhint').hidden && d.getElementById('sc-chhint').hidden,
    '#2126: no list, text optional, its own hint');
  click(w, sm.querySelector('[data-sf="save"]'));
  await until(() => d.querySelector('.schedmd .schedrow'));
  const row = d.querySelector('.schedmd .schedrow');
  check(row && /Sort the basket · Every working day/.test(row.textContent.replace(/\s+/g, ' ')), '#2126: saved without a text, the row names the kind ' + row?.textContent.replace(/\s+/g, ' '));
  const P = (await call('GET', `/api/agents/${AG}/schedules`)).data[0];
  check(P && P.action === 'triage' && P.list_id === null && P.prompt && P.time === '07:30', '#2126: stored as triage ' + JSON.stringify(P).slice(0, 200));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
