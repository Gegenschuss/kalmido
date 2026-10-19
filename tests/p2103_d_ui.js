// 2.103.0 UI tests, part D (#2175 delete messages / the history of the agent chat), own container (start.sh;
// P2103D_NOSTART=1: a running server). jsdom:
// - the menu of a message (mine and the agent's answer) offers "Delete message"; it asks first, then the message leaves
//   the chat and the server (for good)
// - the chat header has a menu with "Delete history"; it asks first, then the conversation is empty on screen and server
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2103D_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  if (!ag.id) console.log('agent', JSON.stringify(ag));
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const ORG = ME.workspaces[0].id, L = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const mine = await call('POST', `/api/agents/${AG}/chat`, {body: 'Plan the week'});
  if (mine.status !== 201) console.log('mine', JSON.stringify(mine));
  const mine2 = await call('POST', `/api/agents/${AG}/chat`, {body: 'And the month'});
  const theirs = await (await fetch(V + `/agent/chats/${ME.id}`, {method: 'POST', headers: AGH, body: JSON.stringify({body: 'Sure, which list?'})})).json();
  check(mine.status === 201 && mine2.status === 201 && theirs.id, 'setup: three messages');
  const cm = (d, id) => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  const menuOf = async (w, d, id) => {
    w.eval('closePop && closePop()');
    click(w, cm(d, id).querySelector('[data-act="chat-msg-menu"]'));
    await until(() => d.querySelector('.menu-list button'));
    return [...d.querySelectorAll('.menu-list button')];
  };
  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.__dialogs = 'manual';
  w.eval(`chatOpen(${AG})`); await until(() => cm(d, theirs.id));
  const msgs = async () => (await call('GET', `/api/agents/${AG}/chat`)).messages || [];

  // ================= one message
  let items = await menuOf(w, d, mine.id);
  check(items.some(b => b.textContent.trim() === 'Delete message'), 'my message: the menu offers Delete message ' + items.map(b => b.textContent.trim()));
  w.eval('closePop()');
  items = await menuOf(w, d, theirs.id);
  check(items.some(b => b.textContent.trim() === 'Delete message'), "the agent's answer: Delete message too");
  w.eval('closePop()');
  items = await menuOf(w, d, mine.id);
  click(w, items.find(b => b.textContent.trim() === 'Delete message'));
  let dlg = await until(() => d.querySelector('.modal.cdlg [data-cd="yes"]') && d.querySelector('.modal.cdlg'));
  check(/for good/.test(dlg?.textContent || ''), 'it asks first, and says "for good"');
  check((await msgs()).some(m => m.id === mine.id), 'asking deletes nothing yet');
  click(w, dlg.querySelector('[data-cd="no"]'));
  await sleep(200);
  check((await msgs()).some(m => m.id === mine.id) && !!cm(d, mine.id), 'Cancel: the message stays');
  items = await menuOf(w, d, mine.id);
  click(w, items.find(b => b.textContent.trim() === 'Delete message'));
  dlg = await until(() => d.querySelector('.modal.cdlg [data-cd="yes"]') && d.querySelector('.modal.cdlg'));
  click(w, dlg.querySelector('[data-cd="yes"]'));
  check(await until(() => !cm(d, mine.id)), 'the message leaves the chat');
  check(!(await msgs()).some(m => m.id === mine.id), 'and the server');

  // ================= the whole history
  const head = await until(() => d.querySelector('.chath [data-act="chat-head-menu"]'));
  check(!!head, 'the chat header has a menu button');
  if (head) {
    click(w, head);
    await until(() => d.querySelector('.menu-list button'));
    const b = [...d.querySelectorAll('.menu-list button')].find(x => x.textContent.trim() === 'Delete history');
    check(!!b, 'the header menu offers Delete history');
    if (b) {
      click(w, b);
      dlg = await until(() => d.querySelector('.modal.cdlg [data-cd="yes"]') && d.querySelector('.modal.cdlg'));
      check(/Claude/.test(dlg?.textContent || '') && /for good/.test(dlg?.textContent || ''), 'it names the agent and asks first');
      click(w, dlg.querySelector('[data-cd="yes"]'));
      check(await until(() => !cm(d, mine2.id) && !cm(d, theirs.id)), 'the chat is empty on screen');
      check((await msgs()).length === 0, 'and on the server');
    }
  }
  console.log(`p2103_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
