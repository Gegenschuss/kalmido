// 2.139.0 UI tests, part A: threads in the team chat (#2127) and "Read by" (#2129), own container (start.sh). jsdom:
// desktop: the line under a first message ("2 replies", faces, a dot while unread), the thread pane right of the conversation
// (.tcview.inthread) with the first message, its answers and its own box (sending, the line counts on), "Reply in thread"
// in a message's menu, closing; "Read by 1" under my latest read message, the list behind it (read / not read yet), a DM
// says "Read"; Settings > Notifications > "Send read receipts" saves. Phone width (390 px): the thread replaces the
// conversation (no pane), Back returns. Classes / data attributes, English accounts.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2139A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  const st0 = await call('GET', '/api/state'), feats = new Set(((st0.settings || {}).features || '').split(',').filter(Boolean)); feats.add('collab');
  const FEAT = [...feats].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const ids = {}, cks = {};
  for (const u of ['bob', 'carol']) {
    ids[u] = (await call('POST', '/api/users', {orgs: [ORG], username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123'})).id;
    cks[u] = await login(u);
    await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, cks[u]);
  }
  const L = (await call('POST', '/api/lists', {name: 'Team', org_id: ORG})).id;
  for (const u of [ids.bob, ids.carol]) await call('PUT', `/api/lists/${L}/members`, {user_id: u, role: 'edit'});
  const PRJ = (await call('POST', '/api/team/channels', {name: 'Project', org_id: ORG, open: false, members: [ids.bob, ids.carol]})).id;
  check(PRJ > 0, 'a channel to start with');
  const R = (await call('POST', `/api/team/rooms/${PRJ}/messages`, {body: 'Kickoff on Monday?'})).id;
  const T1 = (await call('POST', `/api/team/rooms/${PRJ}/messages`, {body: 'Monday works', thread_of: R}, cks.bob)).id;
  const T2 = (await call('POST', `/api/team/rooms/${PRJ}/messages`, {body: 'Me too', thread_of: R}, cks.carol)).id;
  const M = (await call('POST', `/api/team/rooms/${PRJ}/messages`, {body: 'Agenda is up'})).id;
  await call('POST', `/api/team/rooms/${PRJ}/read`, {}, cks.bob);  // bob read the main conversation, carol did not
  check(R && T1 && T2 && M, 'messages and thread answers through the API');

  // ================= desktop: the thread line, the pane, sending, "Reply in thread", "Read by"
  {
    const w = await boot({user: 'alice', hash: 'team/' + PRJ}), d = w.document;
    await until(() => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${R}"]`));
    const line = await until(() => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${R}"] .tthline`));
    check(line && /2 replies/.test(line.textContent) && line.querySelectorAll('.tthav .avatar').length === 2 && line.querySelector('.tthdot'),
      'line: "2 replies", two faces, a dot while unread ' + (line?.textContent || '').trim().slice(0, 80));
    check(!d.querySelector(`#tc-msgs [data-mid="t:${T1}"]`) && !d.querySelector(`#tc-msgs [data-mid="t:${T2}"]`), 'main list: no thread answers');
    click(w, line);
    await until(() => d.querySelector(`.tthpane #tth-msgs [data-mid="t:${T2}"]`));
    check(d.querySelector('.tcview.inthread') && d.querySelector('aside.tthpane .tthview'), 'pane: right of the conversation (.inthread)');
    check(d.querySelector(`.tthpane #tth-msgs [data-mid="t:${R}"]`) && d.querySelector(`.tthpane #tth-msgs [data-mid="t:${T1}"]`) && d.querySelector('.tthpane .tthsep'),
      'pane: the first message, a separator, the answers');
    check(d.querySelector('#tc-msgs') && d.querySelector('#tth-in') && d.querySelector('#tc-in'), 'pane: the conversation and both boxes stay');
    const room = await until(async () => { const x = (await call('GET', '/api/team')).rooms.find(q => q.id === PRJ); return x && x.unread === 0 && x; });
    check(room && room.unread === 0, 'pane: opening it read the answers ' + JSON.stringify(room || {}).slice(0, 120));
    // send in the thread
    const ta = d.querySelector('#tth-in'); ta.value = 'Room 2 then';
    click(w, d.querySelector('[data-act="tth-send"]'));
    const th = await until(async () => { const j = await call('GET', `/api/team/rooms/${PRJ}/messages?thread=${R}`); return j.messages?.length === 3 && j; });
    check(th && th.messages[2].body === 'Room 2 then' && th.messages[2].thread_of === R, 'send: the answer lands in the thread');
    await until(() => [...d.querySelectorAll('#tth-msgs .cmsg')].some(x => /Room 2 then/.test(x.textContent)));
    check([...d.querySelectorAll('#tth-msgs .cmsg')].some(x => /Room 2 then/.test(x.textContent)), 'send: shown in the pane');
    check(/3 replies/.test(d.querySelector(`#tc-msgs .cmsg[data-mid="t:${R}"] .tthline`)?.textContent || ''), 'send: the line counts on');
    check(!d.querySelector(`#tc-msgs .cmsg[data-mid="t:${th?.messages?.[2]?.id}"]`), 'send: not in the main list');
    // "Reply in thread" in the menu of a main message
    click(w, d.querySelector(`#tc-msgs .cmsg[data-mid="t:${M}"] [data-act="tc-msg-menu"]`));
    await until(() => d.querySelector('#pop [role="menuitem"]'));
    const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
    const rit = items.find(x => /Reply in thread/.test(x.textContent));
    check(!!rit && rit.querySelector('svg'), 'menu: "Reply in thread" with an icon ' + items.map(x => x.textContent.trim()).join('|'));
    click(w, rit);
    await until(() => d.querySelector(`.tthpane .tthview[data-root="${M}"]`));
    check(d.querySelector(`.tthpane .tthview[data-root="${M}"]`) && /No replies yet/.test(d.querySelector('.tthpane .tthsep')?.textContent || ''), 'menu: opens the (empty) thread of that message');
    // the thread view's own menu: no "Reply in thread" there
    click(w, d.querySelector(`.tthpane .cmsg[data-mid="t:${M}"] [data-act="tc-msg-menu"]`));
    await until(() => d.querySelector('#pop [role="menuitem"]'));
    check(![...d.querySelectorAll('#pop [role="menuitem"]')].some(x => /Reply in thread/.test(x.textContent)), 'menu: not inside a thread');
    w.eval('closePop()');
    click(w, d.querySelector('.tthpane [data-act="tth-close"]'));
    await until(() => !d.querySelector('.tcview.inthread'));
    check(!d.querySelector('.tcview.inthread') && !d.querySelector('.tthpane'), 'close: the pane goes');
    // "Read by" under my latest read message (bob read "Agenda is up", carol did not)
    const rl = await until(() => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${M}"] .trdline`));
    check(rl && /Read by 1/.test(rl.textContent) && rl.querySelectorAll('.avatar').length === 1, '"Read by 1" with one face ' + (rl?.textContent || '').trim());
    check(d.querySelectorAll('#tc-msgs .trdline').length === 1, 'only one "Read by" line (no ticks at every message)');
    click(w, rl);
    await until(() => d.querySelector('.modal .trdl'));
    const lists = [...d.querySelectorAll('.modal .trdl')].map(x => x.textContent);
    check(lists.length === 2 && /Bob/.test(lists[0]) && /Carol/.test(lists[1]) && !/Carol/.test(lists[0]), 'the list: read (Bob) / not read yet (Carol) ' + lists.join(' | '));
    d.querySelector('.modal')?.remove();
    // Settings > Notifications: "Send read receipts"
    w.eval(`settingsModal('notify')`); await until(() => d.querySelector('#s-trd'));
    const cb = d.querySelector('#s-trd');
    check(cb && cb.checked, 'settings: "Send read receipts" on by default');
    cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
    const off = await until(async () => (await call('GET', '/api/state')).settings?.chat_read_receipts === '0');
    check(off, 'settings: switched off and saved');
    d.querySelector('.modal')?.remove();
    await call('PATCH', '/api/settings', {chat_read_receipts: '1'});
    check(!errs.length, `desktop: no JS errors ${errs.join(' | ')}`);
    await sleep(500); w.close();
  }

  // ================= phone width (390 px): the thread replaces the conversation, Back returns
  {
    errs.length = 0;
    const w = await boot({user: 'bob', mobile: true, hash: 'team/' + PRJ}), d = w.document;
    const line = await until(() => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${R}"] .tthline`));
    check(!!line, 'phone: the thread line');
    click(w, line);
    await until(() => d.querySelector(`.tcroom .tthview #tth-msgs [data-mid="t:${T1}"]`));
    check(d.querySelector('.tcroom .tthview') && !d.querySelector('#tc-msgs') && !d.querySelector('.tthpane'), 'phone: the thread full size instead of the conversation');
    check(d.querySelector('.tthview [data-act="tth-close"]'), 'phone: a Back button');
    const ta = d.querySelector('#tth-in'); ta.value = 'From my phone';
    click(w, d.querySelector('[data-act="tth-send"]'));
    const th = await until(async () => { const j = await call('GET', `/api/team/rooms/${PRJ}/messages?thread=${R}`); return j.messages?.some(m => m.body === 'From my phone') && j; });
    check(!!th, 'phone: sends in the thread');
    click(w, d.querySelector('.tthview [data-act="tth-close"]'));
    await until(() => d.querySelector('#tc-msgs'));
    check(d.querySelector('#tc-msgs') && !d.querySelector('.tthview'), 'phone: Back returns to the conversation');
    check(!errs.length, `phone: no JS errors ${errs.join(' | ')}`);
    await sleep(500); w.close();
  }

  // ================= a direct message says "Read"
  {
    errs.length = 0;
    const DM = (await call('POST', '/api/team/dm', {user_id: ids.bob})).id;
    const D1 = (await call('POST', `/api/team/rooms/${DM}/messages`, {body: 'Quick question'})).id;
    await call('POST', `/api/team/rooms/${DM}/read`, {}, cks.bob);
    const w = await boot({user: 'alice', hash: 'team/' + DM}), d = w.document;
    const rl = await until(() => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${D1}"] .trdline`));
    check(rl && rl.tagName === 'DIV' && /^\s*Read\s*$/.test(rl.textContent), 'DM: "Read" (no list behind it) ' + (rl?.outerHTML || '').slice(0, 120));
    check(!errs.length, `DM: no JS errors ${errs.join(' | ')}`);
    await sleep(500); w.close();
  }

  console.log(`p2139_a_ui: ${ok} ok, ${F.length} failed`);
  execFileSync('docker', ['rm', '-f', process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test'], {stdio: 'ignore'});
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
