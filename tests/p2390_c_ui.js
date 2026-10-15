// 2.39.0 UI tests, part C (#1179 edit my own messages in the agent chat), own container (start.sh). jsdom:
// - the menu of my own message offers "Edit", the agent's message not
// - Edit turns the bubble into a text box (my text in it); Escape leaves it unchanged; Save stores the new text
// - the message then says "edited"; a tap shows the earlier versions (current text + the old one with its time)
// - Enter in the edit box saves too; an empty text is not sent (the box stays)
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
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  // 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me, ORG = ME.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const mine = await call('POST', `/api/agents/${AG}/chat`, {body: 'Plan the week with three tasks'});
  check(mine.status === 201, 'setup: my message');
  const theirs = await (await fetch(V + `/agent/chats/${ME.id}`, {method: 'POST', headers: AGH, body: JSON.stringify({body: 'Sure, which list?'})})).json();
  const cm = (d, id) => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  const menuOf = async (w, d, id) => {
    w.eval('closePop && closePop()');
    click(w, cm(d, id).querySelector('[data-act="chat-msg-menu"]'));
    await until(() => d.querySelector('.menu-list button'));
    return [...d.querySelectorAll('.menu-list button')].map(b => b.textContent.trim());
  };

  const w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => cm(d, theirs.id));
  // ================= the menu
  let items = await menuOf(w, d, mine.id);
  check(items.includes('Edit'), 'my message: the menu offers Edit ' + JSON.stringify(items));
  items = await menuOf(w, d, theirs.id);
  check(!items.includes('Edit'), "the agent's message: no Edit " + JSON.stringify(items));
  w.eval('closePop()');
  // ================= Escape leaves it as it was
  w.eval(`chatEditStart(${mine.id})`);
  let ta = await until(() => cm(d, mine.id)?.querySelector('textarea.ach-edit'));
  check(ta && ta.value === 'Plan the week with three tasks', 'Edit: a text box with my text in the bubble');
  check(!!cm(d, mine.id).querySelector('[data-act="chat-ed-save"]') && !!cm(d, mine.id).querySelector('[data-act="chat-ed-cancel"]'), 'Save and Cancel buttons');
  ta.value = 'something else';
  key(w, ta, 'Escape');
  await until(() => !cm(d, mine.id)?.querySelector('textarea.ach-edit'));
  check(!cm(d, mine.id).querySelector('textarea') && /three tasks/.test(cm(d, mine.id).querySelector('.cbub')?.textContent || ''), 'Escape: back, the text unchanged');
  check(!cm(d, mine.id).querySelector('.cedited'), 'not edited: no "edited"');
  // ================= Save
  w.eval(`chatEditStart(${mine.id})`);
  ta = await until(() => cm(d, mine.id)?.querySelector('textarea.ach-edit'));
  ta.value = '   ';
  click(w, cm(d, mine.id).querySelector('[data-act="chat-ed-save"]'));
  await sleep(400);
  check(!!cm(d, mine.id).querySelector('textarea.ach-edit'), 'an empty text is not sent: the box stays');
  ta = cm(d, mine.id).querySelector('textarea.ach-edit');
  ta.value = 'Plan the week with four tasks';
  click(w, cm(d, mine.id).querySelector('[data-act="chat-ed-save"]'));
  await until(() => cm(d, mine.id)?.querySelector('.cedited'));
  check(/four tasks/.test(cm(d, mine.id).querySelector('.cbub')?.textContent || '') && !cm(d, mine.id).querySelector('textarea'), 'Save: the new text in the bubble');
  const ed = cm(d, mine.id).querySelector('.cedited');
  check(ed && /edited/.test(ed.textContent) && !ed.disabled, 'the message says "edited" (a button)');
  check(!cm(d, theirs.id).querySelector('.cedited'), "the agent's message: no edited mark");
  // ================= the earlier versions
  click(w, ed);
  const md = await until(() => d.querySelector('.chedmd'));
  check(md && /Earlier versions/.test(md.textContent) && /four tasks/.test(md.querySelector('.chednow')?.textContent || '')
        && /three tasks/.test(md.querySelector('.chedits')?.textContent || '') && md.querySelectorAll('.chedits li time').length === 1,
        'a tap: the current text and the earlier version with its time');
  click(w, md.querySelector('[data-m="close"]'));
  await until(() => !d.querySelector('.chedmd'));
  // ================= Enter saves; the server has it
  w.eval(`chatEditStart(${mine.id})`);
  ta = await until(() => cm(d, mine.id)?.querySelector('textarea.ach-edit'));
  ta.value = 'Plan the week with five tasks';
  key(w, ta, 'Enter');
  await until(() => /five tasks/.test(cm(d, mine.id)?.querySelector('.cbub')?.textContent || ''));
  const j = await call('GET', `/api/agents/${AG}/chat`);
  const m = (j.messages || []).find(x => x.id === mine.id);
  check(m && m.body === 'Plan the week with five tasks' && m.edits.length === 2, 'Enter saved: the server has the text and two earlier versions');
  await w.eval('chatLoad()'); await sleep(300);
  check(/five tasks/.test(cm(d, mine.id)?.querySelector('.cbub')?.textContent || '') && !!cm(d, mine.id).querySelector('.cedited'), 'after a refresh: still edited, the new text');

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
