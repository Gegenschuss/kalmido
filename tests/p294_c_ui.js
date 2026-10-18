// 2.94.0 (#2024) UI tests: chat boxes (team chat, agent chat, editing a message): Enter = new line, Ctrl/Cmd+Enter sends / saves,
// enterkeyhint=enter, Send button title. jsdom, own container (start.sh).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const LST = (await call('POST', '/api/lists', {name: 'Website'})).id;
  await call('PUT', `/api/lists/${LST}/members`, {user_id: BOB, role: 'edit'});  // a DM needs a shared list
  await call('PUT', `/api/lists/${LST}/agent`, {agent_id: AG});
  const dm = await call('POST', '/api/team/dm', {user_id: BOB}), room = {id: dm.id || dm.room?.id};
  if (!room.id) console.log('dm failed', JSON.stringify(dm));
  const key = (w, el, k, o = {}) => { const ev = new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}); el.dispatchEvent(ev); return ev; };
  const type = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
  const msgs = async () => (await call('GET', `/api/team/rooms/${room.id}/messages`)).messages || [];

  // ================= #2024 team chat
  let w = await boot({user: 'alice', hash: 'team/' + room.id}), d = w.document;
  const tin = await until(() => d.querySelector('#tc-in') && w.eval('!!S.tc.room') && d.querySelector('#tc-in'));
  check(tin.getAttribute('enterkeyhint') === 'enter', 'team: enterkeyhint=enter');
  check(!!d.querySelector('[data-act="tc-send"]').title, 'team: the Send button has a title');
  type(w, tin, 'line one');
  let ev = key(w, tin, 'Enter');
  await sleep(500);
  check(!ev.defaultPrevented && tin.value === 'line one' && !(await msgs()).length, 'team: plain Enter is a new line, sends nothing');
  ev = key(w, tin, 'Enter', {shiftKey: true});
  check(!ev.defaultPrevented, 'team: Shift+Enter stays a new line');
  ev = key(w, tin, 'Enter', {ctrlKey: true});
  const sent = await until(async () => (await msgs()).pop());
  check(ev.defaultPrevented && sent && sent.body === 'line one', 'team: Ctrl+Enter sends');
  type(w, tin, 'second');
  key(w, tin, 'Enter', {metaKey: true});
  check(await until(async () => (await msgs()).some(m => m.body === 'second')), 'team: Cmd+Enter sends');
  const mine = await until(() => d.querySelector(`#tc-msgs [data-mid="t:${sent.id}"]`));
  click(w, mine.querySelector('[data-act="tc-msg-menu"]')); await sleep(80);
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Edit/.test(b.textContent))); await sleep(100);
  const ed = d.querySelector('#tc-msgs .tc-edit');
  check(ed && ed.getAttribute('enterkeyhint') === 'enter', 'team edit: enterkeyhint=enter');
  ed.value = 'edited text';
  ev = key(w, ed, 'Enter'); await sleep(400);
  check(!ev.defaultPrevented && d.querySelector('#tc-msgs .tc-edit'), 'team edit: Enter does not save');
  key(w, ed, 'Enter', {ctrlKey: true});
  check(await until(async () => (await msgs()).find(m => m.id === sent.id)?.body === 'edited text'), 'team edit: Ctrl+Enter saves');

  // ================= #2024 agent chat
  w = await boot({user: 'alice', hash: 'l/' + LST}); d = w.document;
  w.eval(`chatOpen(${AG})`); const cin = await until(() => d.querySelector('#chat-in'));
  check(cin.getAttribute('enterkeyhint') === 'enter', 'agent chat: enterkeyhint=enter');
  check(!!d.querySelector('[data-act="chat-send"]').title, 'agent chat: the Send button has a title');
  type(w, cin, 'hello agent');
  ev = key(w, cin, 'Enter'); await sleep(500);
  check(!ev.defaultPrevented && cin.value === 'hello agent' && !d.querySelector('#chat-msgs .cmsg.me'), 'agent chat: plain Enter sends nothing');
  key(w, cin, 'Enter', {ctrlKey: true});
  const mm = await until(() => d.querySelector('#chat-msgs .cmsg.me[data-mid]'));
  check(mm && /hello agent/.test(mm.textContent), 'agent chat: Ctrl+Enter sends');
  w.eval(`chatEditStart(${+mm.dataset.mid.split(':')[1]})`);
  const ae = await until(() => d.querySelector('#chat-msgs textarea.ach-edit'));
  check(ae && ae.getAttribute('enterkeyhint') === 'enter', 'agent edit: enterkeyhint=enter');
  ae.value = 'hello again';
  ev = key(w, ae, 'Enter'); await sleep(400);
  check(!ev.defaultPrevented && d.querySelector('#chat-msgs textarea.ach-edit'), 'agent edit: Enter does not save');
  key(w, ae, 'Enter', {ctrlKey: true});
  check(await until(() => /hello again/.test(d.querySelector('#chat-msgs .cmsg.me')?.textContent || '')), 'agent edit: Ctrl+Enter saves');

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
