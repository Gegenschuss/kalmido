// 2.36.2 UI tests (agent D), own container (start.sh). jsdom:
//   #1136 "Keep completed in their section": the defaults (project / list with sections on, plain list off, "Show completed
//   at the bottom" and shopping lists always off), a completed task stays in its section (crossed out, not draggable, the
//   head says "1/2 done"), a completed subtask stays below its parent, "Hide completed" hides them there too, off = the
//   group "Completed" as before; the list dialog's checkbox and the list menu entry store the list's setting
//   #1138 quick add in "Tasks of Bob": the chips show Bob and a list both use, the task is assigned to Bob in that list and
//   stays in the view with "Bob assigned in …"; with nobody shared (Dave) a hint and nothing is added; the view "Assigned
//   by me" groups my open assignments by person (not my own, not completed), sidebar entry
// Firefox 390 touch: rows of a section with a completed task, 44 px rows, nothing sideways; the quick add sheet in "Tasks of
//   Bob" with its chip; "Assigned by me"; screenshots with P2362D_SHOTS=<dir>
process.env.TZ = 'Europe/Berlin';
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2362_d_ui', check, shots: 'P2362D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const CK = {};
const call = async (method, url, body, who = 'alice') => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK[who]}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const rowOf = (d, id) => d.querySelector(`#view .trow[data-id="${id}"]`);
const groupOf = row => row?.closest('.group');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK.alice = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  const ids = {};
  for (const u of ['bob', 'carol', 'dave']) ids[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`})).id;
  for (const u of ['bob', 'carol', 'dave']) CK[u] = await login(u);
  for (const u of ['alice', 'bob', 'carol', 'dave']) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, u);
  const share = async (lid, uid, who = 'alice') => { let r = await call('PUT', `/api/lists/${lid}/members`, {user_id: uid, role: 'edit'}, who); if (r.status === 409) r = await call('PUT', `/api/lists/${lid}/members`, {user_id: uid, role: 'edit', bridge_ok: true}, who); check(r.status === 200, 'setup: share ' + JSON.stringify(r).slice(0, 80)); };
  // lists: a project with two sections, a plain list, a plain list with a section, a shopping list, a list with done at the bottom
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const S1 = (await call('POST', '/api/sections', {list_id: P, name: 'Design'})).id;
  const S2 = (await call('POST', '/api/sections', {list_id: P, name: 'Build'})).id;
  const PLAIN = (await call('POST', '/api/lists', {name: 'Errands'})).id;
  const WS = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  await call('POST', '/api/sections', {list_id: WS, name: 'Spring'});
  const SHOP = (await call('POST', '/api/lists', {name: 'Groceries', family: 'shopping'})).id;
  const DAB = (await call('POST', '/api/lists', {name: 'Packing', done_at_bottom: true})).id;
  await call('PATCH', `/api/lists/${SHOP}`, {done_in_section: 1});
  await call('PATCH', `/api/lists/${DAB}`, {done_in_section: 1});
  const mk = async (title, extra) => (await call('POST', '/api/tasks', {title, ...extra})).id;
  const T1 = await mk('Logo draft', {list_id: P, section_id: S1});
  const T2 = await mk('Colour palette', {list_id: P, section_id: S1});
  const T3 = await mk('Set up the server', {list_id: P, section_id: S2});
  const SUB1 = await mk('Ask for fonts', {list_id: P, parent_id: T2});
  const T4 = await mk('Buy stamps', {list_id: PLAIN});
  for (const id of [T1, SUB1, T4]) await call('POST', `/api/tasks/${id}/complete`);
  // people: carol's board with alice + bob; dave shares nothing with alice
  const W = (await call('POST', '/api/lists', {name: 'Team board'}, 'carol')).id;
  await share(W, (await call('GET', '/api/state')).me.id, 'carol');
  await share(W, ids.bob, 'carol');
  await share(P, ids.carol);
  // dave: alice only reads his list (no list both may write to)
  const DV = (await call('POST', '/api/lists', {name: 'Dave notes'}, 'dave')).id;
  { let r = await call('PUT', `/api/lists/${DV}/members`, {user_id: (await call('GET', '/api/state')).me.id, role: 'view'}, 'dave'); if (r.status === 409) r = await call('PUT', `/api/lists/${DV}/members`, {user_id: (await call('GET', '/api/state')).me.id, role: 'view', bridge_ok: true}, 'dave'); check(r.status === 200, 'setup: alice reads dave\'s list'); }
  const ALICE = (await call('GET', '/api/state')).me.id;

  // ================= #1136 defaults + rendering (jsdom)
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  await until(() => rowOf(d, T2));
  check(w.eval(`[dsxOn(listById(${P})), dsxOn(listById(${PLAIN})), dsxOn(listById(${WS})), dsxOn(listById(${SHOP})), dsxOn(listById(${DAB}))].join()`) === 'true,false,true,false,false',
    'defaults: project on, plain list off, list with sections on, shopping + done-at-bottom always off ' + w.eval(`[dsxOn(listById(${P})), dsxOn(listById(${PLAIN})), dsxOn(listById(${WS})), dsxOn(listById(${SHOP})), dsxOn(listById(${DAB}))].join()`));
  let r1 = rowOf(d, T1);
  check(r1 && r1.classList.contains('done') && groupOf(r1)?.querySelector('.ghead')?.dataset.section === String(S1), 'on: the completed task stays in its section, marked done');
  check(r1 && !r1.hasAttribute('draggable') && rowOf(d, T2).getAttribute('draggable') === 'true', 'on: the completed row is not draggable, the open one is');
  check(![...d.querySelectorAll('#view .ghead')].some(h => /^Completed/.test(h.textContent.trim())), 'on: no group "Completed"');
  const hd = groupOf(r1).querySelector('.ghead .c');
  check(hd && /1\/2 done/.test(hd.textContent) && hd.classList.contains('dsxc'), 'on: the section head says 1/2 done ' + hd?.textContent);
  check(/^\d+$/.test(groupOf(rowOf(d, T3)).querySelector('.ghead .c').textContent.trim()), 'on: a section without completed tasks keeps its plain number');
  const sub = rowOf(d, SUB1);
  check(sub && sub.classList.contains('done') && sub.classList.contains('sub') && groupOf(sub) === groupOf(rowOf(d, T2)), 'on: the completed subtask stays below its parent');
  // Hide completed (the view's own switch) hides them in the sections too
  await w.eval('setShowDone(false)'); await sleep(600);
  check(!rowOf(d, T1) && !rowOf(d, SUB1) && rowOf(d, T2), 'hide completed: gone from the sections, the open ones stay');
  await w.eval('setShowDone(true)'); await sleep(600);
  check(!!rowOf(d, T1), 'show completed: back in the section');
  // the list menu entry turns it off for the list (stored on the server)
  const item = w.eval(`dsxItem(listById(${P}))`);
  check(item && item.on === true, 'list menu: the entry shows it is on');
  await w.eval(`dsxSet(${P}, false)`); await sleep(700);
  w.eval(`S.collapsed.add('done-open'); renderView()`); await sleep(200);  // the group "Completed" starts folded
  check((await call('GET', '/api/state')).lists.find(l => l.id === P).done_in_section === 0, 'list menu: off is stored for the list');
  r1 = rowOf(d, T1);
  check(r1 && /^Completed/.test(groupOf(r1)?.querySelector('.ghead')?.textContent.trim() || ''), 'off: the completed task is in the group "Completed" again');
  check(!rowOf(d, SUB1), 'off: the completed subtask is not shown under its parent');
  // the dialog's checkbox
  w.eval(`listModal(${P})`); await until(() => d.querySelector('#l-dsx'));
  const cb = d.querySelector('#l-dsx');
  check(cb && !cb.checked && !cb.disabled, 'dialog: the checkbox shows off');
  cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900);
  check((await call('GET', '/api/state')).lists.find(l => l.id === P).done_in_section === 1, 'dialog: the checkbox stores on');
  w.eval(`document.querySelector('.modal')?.remove()`);
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + DAB}); d = w.document;
  w.eval(`listModal(${DAB})`); await until(() => d.querySelector('#l-dsx'));
  check(d.querySelector('#l-dsx')?.disabled === true && d.querySelector('#l-dsx')?.checked === false, 'dialog: with "Show completed at the bottom" the checkbox is off and fixed');
  w.close();

  // ================= #1138 quick add in "Tasks of Bob" (desktop composer)
  w = await boot({user: 'alice', hash: 'who/' + ids.bob}); d = w.document;
  await until(() => d.querySelector('#qinput'));
  w.eval(`qdockChips()`);
  const chips = d.querySelector('#qdchips')?.textContent || '';
  check(/Bob/.test(chips) && /Team board/.test(chips), 'who: the chips show Bob and the list both use ' + chips);
  let inp = d.querySelector('#qinput'); inp.value = 'Prepare the meeting';
  await w.eval(`submitQuick(document.querySelector('#qinput'))`); await sleep(900);
  let st = await call('GET', '/api/state');
  const nt = st.tasks.find(t => t.title === 'Prepare the meeting');
  check(nt && nt.assignee_id === ids.bob && nt.list_id === W && nt.assigned_by === ALICE, 'who: the new task is Bob\'s, in the shared list ' + JSON.stringify(nt && [nt.assignee_id, nt.list_id]));
  check(nt && !!rowOf(d, nt.id), 'who: the new task stays in the view');
  check(/Bob assigned in Team board/.test(d.querySelector('#toast')?.textContent || ''), 'who: the toast says for whom and where ' + d.querySelector('#toast')?.textContent);
  check(w.eval(`LS.get('dsxWho.${ids.bob}', 0)`) === W, 'who: the list is remembered for Bob');
  w.close();
  // nobody shared: a hint, nothing added
  w = await boot({user: 'alice', hash: 'who/' + ids.dave}); d = w.document;
  await until(() => d.querySelector('#qinput'));
  w.eval(`qdockChips()`);
  check(/No list with Dave/.test(d.querySelector('#qdchips .qnote.dsxwho')?.textContent || ''), 'who (nothing shared): the hint in the chips');
  const n0 = (await call('GET', '/api/state')).tasks.length;
  inp = d.querySelector('#qinput'); inp.value = 'Lost task';
  await w.eval(`submitQuick(document.querySelector('#qinput'))`); await sleep(700);
  check((await call('GET', '/api/state')).tasks.length === n0, 'who (nothing shared): nothing is added');
  check(/No list with Dave/.test(d.querySelector('#toast')?.textContent || '') && d.querySelector('#qinput').value === 'Lost task', 'who (nothing shared): the toast, the text stays');
  w.close();

  // ================= #1138 "Assigned by me"
  const A2 = await mk('Check the texts', {list_id: P, assignee_id: ids.carol});
  const A3 = await mk('Mine anyway', {list_id: P, assignee_id: ALICE});
  const A4 = await mk('Done for carol', {list_id: P, assignee_id: ids.carol});
  await call('POST', `/api/tasks/${A4}/complete`);
  const B1 = (await call('POST', '/api/tasks', {title: 'Bob for carol', list_id: W, assignee_id: ids.carol}, 'bob')).id;
  w = await boot({user: 'alice', hash: 'byme'}); d = w.document;
  await until(() => rowOf(d, A2));
  const heads = [...d.querySelectorAll('#view .ghead')].map(h => h.textContent.trim().replace(/\s*\d+$/, ''));
  check(heads.join() === 'Bob,Carol', 'by me: one group per person, by name ' + JSON.stringify(heads));
  check(!!rowOf(d, nt.id) && !!rowOf(d, A2) && !rowOf(d, A3) && !rowOf(d, A4) && !rowOf(d, B1), 'by me: my open assignments only');
  check(groupOf(rowOf(d, nt.id))?.querySelector('.ghead')?.textContent.includes('Bob'), 'by me: the task for Bob under Bob');
  check(!!d.querySelector('#side [data-go="byme"], .srow[data-go="byme"]'), 'sidebar: the entry "Assigned by me"');
  check(d.querySelector('#top h1')?.textContent.includes('Assigned by me'), 'by me: the title ' + d.querySelector('#top h1')?.textContent);
  w.close();

  // ================= Firefox 390 (touch)
  const ffLogin = async (o, hash) => {
    await o.nav(B + 'static/icon.svg'); await sleep(300);
    await o.ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.tour', '"done"'); return 1; })()`);
    const s = await o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await o.nav(B + '#' + hash);
    for (let i = 0; i < 30 && !(await o.ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
    await sleep(900);
    return s;
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o, 'l/' + P) === 200, tag + ': login');
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('#view .trow[data-id="${T1}"]')`)); i++) await sleep(300);
    const m = await ev(`(() => { const rows = [...document.querySelectorAll('#view .trow:not(.sub)')].map(r => Math.round(r.getBoundingClientRect().height));
      const done = document.querySelector('#view .trow[data-id="${T1}"]'), ttl = done && getComputedStyle(done.querySelector('.ttl'));
      return {rows, line: ttl ? ttl.textDecorationLine : '', side: document.documentElement.scrollWidth <= innerWidth + 1, head: done?.closest('.group')?.querySelector('.ghead .c')?.textContent}; })()`);
    check(m.rows.length >= 3 && m.rows.every(h => h >= 44), `${tag}: rows >= 44 px ` + JSON.stringify(m.rows));
    check(/line-through/.test(m.line) && /1\/2 done/.test(m.head || ''), `${tag}: the completed task crossed out in its section, "1/2 done" ` + JSON.stringify([m.line, m.head]));
    check(m.side, `${tag}: nothing sideways`);
    await shot('p2362d-390-done-in-section.png');
    // "Tasks of Bob": the quick add sheet with its chip
    await o.nav(B + '#who/' + ids.bob); await sleep(1200);
    await ev(`(() => { openQuickSheet(); return 1; })()`); await sleep(500);
    const q = await ev(`(() => { const c = document.querySelector('.qadd.sheet .qchip.dsxwho'); if (!c) return null; const r = c.getBoundingClientRect(); return {t: c.textContent, w: Math.round(r.width), h: Math.round(r.height), right: Math.round(r.right)}; })()`);
    check(q && /For Bob in Team board/.test(q.t) && q.right <= 390, `${tag}: the sheet shows "For Bob in Team board" ` + JSON.stringify(q));
    await shot('p2362d-390-who-quickadd.png');
    await ev(`(() => { closePop(); return 1; })()`);
    await o.nav(B + '#byme'); await sleep(1200);
    const g = await ev(`[...document.querySelectorAll('#view .ghead')].map(h => h.textContent.trim()).join('|')`);
    check(/Bob/.test(g) && /Carol/.test(g), `${tag}: "Assigned by me" grouped by person ` + g);
    await shot('p2362d-390-assigned-by-me.png');
  }, true);

  console.log(`p2362_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
