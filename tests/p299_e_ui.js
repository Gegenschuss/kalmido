// 2.99.0 UI tests, part E (#2187): the sidebar group "Conversations" no longer grows with every person a list is shared with.
// - "Messages" + at most 5 last conversations stay; people only while pinned (at most 5, settings side_people), a person
//   standing there as a conversation not a second time; "All people …" at the end (their tasks, a message, pin)
// - groups: only the ones I am a member of; agents: only pinned (side_agents), unread or working ones
// - the pins hold on every device (server setting), pin / unpin = one undo step, the 6th pin is refused with a note,
//   a pinned person I no longer share a list with drops out without their name
// Own container (start.sh), jsdom. P299E_NOSTART=1: an app already running.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P299E_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 200) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };  // 2.206.0 B (#2513): 30 s (CI load)
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  const ALICE = (await call('GET', '/api/state')).me.id;
  const L = (await call('POST', '/api/lists', {name: 'Team'})).id;
  const P = [];  // eight people sharing the list "Team"
  for (let i = 1; i <= 8; i++) {
    const id = (await call('POST', '/api/users', {orgs: [1], username: 'p' + i, display_name: 'Person ' + i, password: 'password123'})).id;
    await call('PUT', `/api/lists/${L}/members`, {user_id: id, role: 'edit'}); P.push(id);
  }
  // Zed: in the organisation, but no shared list - never a name in Alice's sidebar
  const ZED = (await call('POST', '/api/users', {orgs: [1], username: 'zed', display_name: 'Zed Hidden', password: 'password123'})).id;
  // two conversations: Person 1 and Person 2 write to Alice directly
  for (const i of [0, 1]) {
    const ck = await login('p' + (i + 1));
    await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL}, ck);
    const dm = (await call('POST', '/api/team/dm', {user_id: ALICE}, ck)).id;
    await call('POST', `/api/team/rooms/${dm}/messages`, {body: 'Hello Alice ' + i}, ck);
  }
  // groups: one with Alice, one without her (with an open task: an admin used to see it too)
  const GIN = (await call('POST', '/api/admin/groups', {name: 'Office', members: [ALICE, P[2]]})).id;
  const GOUT = (await call('POST', '/api/admin/groups', {name: 'Field', members: [P[3]]})).id;
  await call('POST', '/api/tasks', {title: 'Fix the fence', list_id: L, assignee_group_id: GOUT});
  // agents, each in a list of its own (one agent per list): an idle one, one to pin
  const mkAgent = async (u, n) => { const a = await call('POST', '/api/admin/agents', {scopes: ['write'], username: u, display_name: n}); const l = (await call('POST', '/api/lists', {name: 'Work of ' + n})).id; await call('PUT', `/api/lists/${l}/members`, {user_id: a.id, role: 'edit'}); return {id: a.id, tok: a.token}; };
  const AG1 = await mkAgent('quietbot', 'QuietBot'), AG2 = await mkAgent('pinbot', 'PinBot');

  // ================= the server: side_people / side_agents
  check((await call('PATCH', '/api/settings', {side_people: P.slice(0, 6).join(',')})).status === 400, 'side_people: a 6th person is refused (400)');
  check((await call('PATCH', '/api/settings', {side_people: 'x'})).status === 400, 'side_people: only ids');
  check((await call('PATCH', '/api/settings', {side_agents: 'a,b'})).status === 400, 'side_agents: only ids');
  check((await call('GET', '/api/state')).settings.side_people === '', 'side_people: nothing stored on a refusal');

  // ================= the sidebar without pins
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  const team = () => d.querySelector('#side .sg-team');
  check(await until(() => d.querySelectorAll('#side .sbconv').length === 2), '2 conversations in the sidebar');
  check(!team().querySelector('.sbpw') && !team().querySelector('[data-go^="who/"]'), 'no person rows without pinning (8 people shared)');
  const allRow = team().querySelector('.sbpall[data-act="sb-people"]');
  check(allRow && /All people/.test(allRow.textContent) && team().lastElementChild === allRow, '"All people …" as the last row');
  check(team().querySelector(`.sgrp[data-go="grp/${GIN}"]`) && !team().querySelector(`.sgrp[data-go="grp/${GOUT}"]`), 'groups: mine yes, the other (even with a task) no');
  check(!team().querySelector(`[data-aid="${AG1.id}"]`) && !team().querySelector(`[data-aid="${AG2.id}"]`), 'agents: none pinned, none working: not in the group');
  check(d.querySelector('#srail [data-sbb="agents"]'), '… they stay under "Agents"');  // 2.152.2 (#2622): the area is an icon of the bar

  // ================= "All people …": pin Person 3 (one undo step)
  click(w, allRow);
  const md = await until(() => d.querySelector('.modal.sbpmd'));
  check(md && md.querySelectorAll('.sbpl .mrow[data-uid]').length === 8 && !/Zed/.test(md.textContent), 'the dialog lists the 8 people I share a list with, not Zed');
  const pinBtn = uid => d.querySelector(`.modal.sbpmd .mrow[data-uid="${uid}"] [data-sbp="pin"]`);
  click(w, pinBtn(P[2]));
  check(await until(() => team().querySelector(`.sbpw [data-go="who/${P[2]}"]`)), 'Person 3 pinned: in the sidebar');
  check(await until(() => pinBtn(P[2])?.getAttribute('aria-pressed') === 'true'), 'the pin shows pressed');
  check(team().querySelector(`.sbpw .sbdm[aria-label="Message Person 3"]`), 'the row has the message bubble');
  check((await call('GET', '/api/state')).settings.side_people === String(P[2]), 'stored as side_people');
  // CI of 2.168.6: Person 1 got lost on the way and the 6th pin went through (4,5,6,7,8): before each next click the
  // server AND the page hold the same pins (a page state fetched meanwhile no longer sends an older list)
  const pinsAre = want => until(async () => w.eval(`sbp_ids('side_people').join(',')`) === want && (await call('GET', '/api/state')).settings.side_people === want);
  await w.eval(`histStep('undo')`);
  check(await until(() => !team().querySelector(`[data-go="who/${P[2]}"]`)) && await pinsAre(''), 'undo: unpinned again');
  await w.eval(`histStep('redo')`);
  check(await until(() => team().querySelector(`[data-go="who/${P[2]}"]`)) && await pinsAre(String(P[2])), 'redo: pinned again');
  // Person 1 has a conversation: pinned, but not twice
  await until(() => pinBtn(P[0])); click(w, pinBtn(P[0]));
  check(await pinsAre([P[2], P[0]].join(',')), 'Person 1 pinned');
  check(!team().querySelector(`[data-go="who/${P[0]}"]`) && team().querySelectorAll('.sbconv').length === 2, 'Person 1 stands there only as the conversation');
  // up to 5, the 6th is refused with a note
  // 2.206.0 B (#2513): each pin also arrived in the page (pressed) before the next click: the page sends its own list of pins
  // (CI of 2.168.3: "the 6th pin is refused" red - the 6th click came before the page knew the 5th); the note is waited for
  const pinned = [P[2], P[0]];
  for (const i of [3, 4, 5]) {
    click(w, pinBtn(P[i])); pinned.push(P[i]);
    await until(() => pinBtn(P[i])?.getAttribute('aria-pressed') === 'true');
    await pinsAre(pinned.join(','));
  }
  await until(() => pinBtn(P[0])?.getAttribute('aria-pressed') === 'true');
  check(await pinsAre(pinned.join(',')), '5 people pinned ' + w.eval(`sbp_ids('side_people').join(',')`));
  click(w, pinBtn(P[6]));
  const note = await until(() => /At most 5 people/.test(d.querySelector('#toast')?.textContent || ''));
  const sp = (await call('GET', '/api/state')).settings.side_people.split(',');
  check(sp.length === 5 && !sp.includes(String(P[6])), 'the 6th pin is refused ' + sp.join());
  check(note, '… with a note');
  click(w, md.querySelector('[data-m="close"]'));
  // a click on a name opens their tasks
  w.eval(`sbp_dialog()`); await until(() => d.querySelector('.modal.sbpmd'));
  click(w, d.querySelector(`.modal.sbpmd .mrow[data-uid="${P[7]}"] [data-sbp="go"]`));
  check(await until(() => w.location.hash === '#who/' + P[7] && !d.querySelector('.modal.sbpmd')), 'a name opens their tasks');
  w.close();

  // ================= a second device: the same pins
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  check(await until(() => d.querySelector(`#side .sg-team [data-go="who/${P[2]}"]`)), 'a new session shows the pinned person too');
  // right-click on the person: unpin from there
  const row = d.querySelector(`#side .sg-team [data-go="who/${P[2]}"]`);
  row.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  const un = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Unpin from the sidebar/.test(b.textContent)));
  check(un, 'the person\'s menu offers "Unpin from the sidebar"');
  if (un) click(w, un);
  check(await until(() => !d.querySelector(`#side .sg-team [data-go="who/${P[2]}"]`)), '… and unpins');
  // the conversation's menu offers the pin too
  const conv = d.querySelector('#side .sbconv');
  conv.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  check(await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].some(b => /(Pin to|Unpin from) the sidebar/.test(b.textContent))), 'a direct conversation\'s menu has the pin entry');
  w.eval('typeof closePop === "function" && closePop()');
  w.close();

  // ================= agents: pinned or working
  await call('PATCH', '/api/settings', {side_agents: String(AG2.id), side_people: [P[2], ZED].join(',')});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  check(await until(() => d.querySelector(`#side .sg-team [data-aid="${AG2.id}"]`)), 'a pinned agent stands there ' + w.eval(`S.settings.side_agents + ' | ' + JSON.stringify((S.agents || []).map(a => [a.id, a.name])) + ' | ' + shownAgents().map(a => a.id)`));
  check(!d.querySelector(`#side .sg-team [data-aid="${AG1.id}"]`), 'an idle agent without anything unread not');
  // 2.99.0 (#2187): both in one wait - the sidebar draws again once the shared people are loaded (flaky as two steps)
  check(await until(() => d.querySelector(`#side .sg-team [data-go="who/${P[2]}"]`) && !/Zed/.test(d.querySelector('#side').textContent)), 'a pinned person without a shared list drops out (no name), the others stay');
  await tcall('PUT', '/agent/status', AG1.tok, {status: 'working', text: 'Sorting'});
  await w.eval('load().then(render)');
  check(await until(() => d.querySelector(`#side .sg-team [data-aid="${AG1.id}"]`)), 'a working agent shows up');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
