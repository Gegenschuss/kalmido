// 2.62.0 UI tests of part A (#1530, #1848; own container, start.sh). jsdom:
// - #1848 team chat: the bar above the messages shows a pin that is older than the loaded page, a tap jumps to it (older
//   pages load); "Pin" in a message's menu pins it (the bar says 1/2, the arrow goes to the other one), the pin mark sits
//   in the message's line, the x in the bar unpins; agent chat (phone page): the bar shows the pin, "Pin" in the menu
// - #1530 team chat and agent chat: Enter shows the message at once as "Sending…" and empties the box; a second Enter
//   while it is on its way sends nothing (the text stays in the box); the server has the message once
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P262A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 30000, step: 200});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const enter = (w, el) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, bubbles: true, cancelable: true}));  // 2.94.0 (#2024): Ctrl+Enter sends
const menuItem = (d, label) => [...d.querySelectorAll('[role="menuitem"]')].find(b => b.textContent.trim() === label);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const bob = await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const CL = ag.id; TOK = ag.token;
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: bob.id, role: 'edit'});
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  const RID = ((await call('GET', '/api/team')).rooms || []).find(r => r.list_id === W)?.id;
  check(RID, 'setup: the channel of the list');
  const tm = [];
  // 2.281.0 (#3117): at most 60 messages per person and minute -- the first half comes from the agent (the UI part sends more)
  for (let i = 0; i < 60; i++) tm.push((i < 30 ? await v1('POST', `/team/rooms/${RID}/messages`, {body: `Message ${i}`}) : await call('POST', `/api/team/rooms/${RID}/messages`, {body: `Message ${i}`})).id);
  check((await call('POST', `/api/team/messages/${tm[0]}/pin`, {pinned: true})).ok, 'setup: the oldest message is pinned');

  // ================= #1848 team chat
  let w = await boot({user: 'alice', hash: `team/${RID}`}), d = w.document;
  const bar = await until(() => { const b = d.querySelector(`[data-cpn="t:${RID}"]`); return b && !b.hidden && /Message 0/.test(b.textContent) && b; });
  check(bar && bar.querySelectorAll('.cpnrow').length === 1, '#1848 team: the bar shows the pin that is older than the page ' + (d.querySelector('[data-cpn]')?.outerHTML || 'none').slice(0, 200));
  check(!d.querySelector(`#tc-msgs [data-mid="t:${tm[0]}"]`), '#1848 team: ... which is not loaded yet');
  // 2.206.0 B (#2513): the room's first loads are done before the tap (CI of 2.168.3: a tap during the first load found no messages)
  await idle(w);
  if (bar) click(w, d.querySelector(`[data-cpn="t:${RID}"] [data-act="cpn-go"]`) || bar.querySelector('[data-act="cpn-go"]'));
  check(await until(() => d.querySelector(`#tc-msgs [data-mid="t:${tm[0]}"]`)), '#1848 team: a tap jumps to it (older pages loaded)');
  check(await until(() => d.querySelector(`#tc-msgs [data-mid="t:${tm[0]}"] .cpnmark`)), '#1848 team: the pinned message carries the pin mark');
  const mb = d.querySelector(`#tc-msgs [data-act="tc-msg-menu"][data-mid="${tm[59]}"]`);
  check(mb, '#1848 team: the menu button of the newest message');
  if (mb) click(w, mb);
  const pin = await until(() => menuItem(d, 'Pin'));
  check(pin && menuItem(d, 'Reply'), '#1848 team: "Pin" sits in the menu next to "Reply"');
  if (pin) click(w, pin);
  const two = await until(() => d.querySelectorAll(`[data-cpn="t:${RID}"] .cpnrow`).length === 2);  // 2.87.9 (#1909): one line per pin
  check(two && /Message 59/.test(d.querySelector(`[data-cpn="t:${RID}"]`).textContent), '#1848 team: the new pin shows first');
  check(((await call('GET', `/api/team/rooms/${RID}/messages`)).pins || []).length === 2, '#1848 team: the server has two pins');
  check(/Message 0/.test(d.querySelector(`[data-cpn="t:${RID}"]`)?.textContent || '') && !d.querySelector(`[data-cpn="t:${RID}"] [data-act="cpn-next"]`), '#1848 team: both pins are in the bar, no arrow');
  click(w, d.querySelector(`[data-cpn="t:${RID}"] .cpnrow:last-child [data-act="cpn-x"]`));
  await until(async () => ((await call('GET', `/api/team/rooms/${RID}/messages`)).pins || []).length === 1);
  const left = (await call('GET', `/api/team/rooms/${RID}/messages`)).pins || [];
  check(left.length === 1 && left[0].id === tm[59], '#1848 team: the x unpins its line');
  await until(() => d.querySelectorAll(`[data-cpn="t:${RID}"] .cpnrow`).length === 1);
  check(/Message 59/.test(d.querySelector(`[data-cpn="t:${RID}"]`)?.textContent || ''), '#1848 team: the bar follows');
  // ================= #1530 team chat: Enter twice
  const ta = d.querySelector('#tc-in');
  ta.value = 'Back online'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  enter(w, ta);
  check(ta.value === '' && d.querySelector('#tc-msgs .csdpend') && /Sending/.test(d.querySelector('#tc-msgs .csdpend').textContent), '#1530 team: at once "Sending…", the box empty');
  ta.value = 'Back online'; enter(w, ta);
  check(ta.value === 'Back online', '#1530 team: a second Enter while it is on its way sends nothing');
  await until(() => !d.querySelector('#tc-msgs .csdpend'));
  await idle(w);  // 2.206.0 B (#2513): instead of a fixed 500 ms
  const tms = (await call('GET', `/api/team/rooms/${RID}/messages`)).messages || [];
  check(tms.filter(m => m.body === 'Back online').length === 1, '#1530 team: the server has the message once');
  check(d.querySelectorAll('#tc-msgs .cmsg').length && !d.querySelector('#tc-msgs .csdpend') && [...d.querySelectorAll('#tc-msgs .cbub')].filter(b => /Back online/.test(b.textContent)).length === 1, '#1530 team: shown once');
  w.close();

  // ================= #1848 agent chat (phone page)
  const am = [];
  for (let i = 0; i < 4; i++) am.push((await v1('POST', `/agent/chats/${me.id}`, {body: `Answer ${i}`})).id);
  check((await call('POST', `/api/agents/${CL}/chat/${am[0]}/pin`, {pinned: true})).ok, 'setup: an agent message is pinned');
  w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}); d = w.document;
  const abar = await until(() => { const b = d.querySelector(`[data-cpn="a:${CL}"]`); return b && !b.hidden && /Answer 0/.test(b.textContent) && b; });
  check(abar, '#1848 chat: the bar shows the pin');
  const amb = await until(() => d.querySelector(`#chat-msgs [data-act="chat-msg-menu"][data-mid="${am[3]}"]`));
  if (amb) click(w, amb);
  const apin = await until(() => menuItem(d, 'Pin'));
  check(apin, '#1848 chat: "Pin" in the menu');
  if (apin) click(w, apin);
  check(await until(() => d.querySelectorAll(`[data-cpn="a:${CL}"] .cpnrow`).length === 2), '#1848 chat: two pins in the bar');
  // ================= #1530 agent chat: Enter twice
  const ci = d.querySelector('#chat-in');
  ci.value = 'Mac back online'; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
  enter(w, ci);
  check(ci.value === '' && d.querySelector('#chat-msgs .csdpend'), '#1530 chat: at once "Sending…", the box empty');
  ci.value = 'Mac back online'; enter(w, ci);
  check(ci.value === 'Mac back online', '#1530 chat: a second Enter while it is on its way sends nothing');
  await until(() => !d.querySelector('#chat-msgs .csdpend'));
  await idle(w);
  const cms = (await call('GET', `/api/agents/${CL}/chat`)).messages || [];
  check(cms.filter(m => m.body === 'Mac back online').length === 1, '#1530 chat: the server has the message once');
  w.close();

  console.log(`p262_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
