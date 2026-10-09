// 2.33.0 UI tests (agent A): replies to one message (#1076) and the jump to a message (msgJump, also used by the search #1080),
// own container (start.sh). jsdom:
// - every message carries data-mid="<art>:<id>" (c = comment, t = team chat, a = agent chat)
// - comments, team chat, agent chat: the Reply button opens the reply bar above the box (quote, X; Escape closes it too), the
//   message goes out with reply_to, the answer shows the quote above it; a tap on the quote jumps to the original (msg-hit);
//   a deleted original shows "Message deleted"; the team chat's message menu has "Reply"
// - window.msgJump({art, id, task | chat | agent}) opens the place, pages back until the message is there (team chat > 50,
//   agent chat > 30 messages) and marks it; an unknown id says "Message not found"
// Firefox 390 touch: swiping a message to the right opens the reply bar (team chat and comments); a swipe from the left edge
// or an up / down move does not; screenshot of the reply bar with a quote. 1440: the comment area with a quote (screenshot).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2330_a_ui', check, shots: 'P2330A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Release notes', list_id: L})).id;
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();
  const say = body => v1('POST', `/agent/chats/${ME.id}`, {body});
  const c1 = await call('POST', `/api/tasks/${T}/comments`, {body: 'Do we mention the **search**?'}, BCK);
  const c2 = await call('POST', `/api/tasks/${T}/comments`, {body: 'And the agents?'}, BCK);

  // ================= comments
  let w = await boot({user: 'alice', hash: 't/' + T}), d = w.document;
  const cmEl = id => d.querySelector(`#detail .cm[data-mid="c:${id}"]`);
  await until(() => cmEl(c1.id));
  check(cmEl(c1.id) && cmEl(c2.id), 'comments carry data-mid="c:<id>"');
  click(w, cmEl(c1.id)?.querySelector('[data-act="msg-reply"]'));
  await sleep(150);
  const bar = () => d.querySelector('#detail .rbar:not(.hidden)');
  check(bar() && /Reply to Bob Baker/.test(bar().textContent) && /Do we mention the search\?/.test(bar().textContent), 'comment: Reply opens the bar with the quote ' + (bar()?.textContent || '-'));
  check(d.activeElement?.id === 'c-input', 'comment: the box has the focus');
  click(w, bar()?.querySelector('[data-act="reply-x"]')); await sleep(100);
  check(!bar() && !Object.keys(w.eval('S.reply')).length, 'comment: X closes the bar');
  click(w, cmEl(c2.id)?.querySelector('[data-act="msg-reply"]')); await sleep(100);
  d.querySelector('#c-input').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
  await sleep(100);
  check(!bar(), 'comment: Escape in the box closes the reply first');
  click(w, cmEl(c1.id)?.querySelector('[data-act="msg-reply"]')); await sleep(100);
  d.querySelector('#c-input').value = 'Yes, with a screenshot.';
  click(w, d.querySelector('[data-act="c-send"]'));
  await until(() => [...d.querySelectorAll('#detail .cm')].length === 3);
  const tl = await call('GET', `/api/tasks/${T}/timeline`);
  const R1 = tl.comments.find(c => c.body === 'Yes, with a screenshot.');
  check(R1 && R1.reply_to === c1.id, 'comment: sent with reply_to ' + JSON.stringify(R1 && R1.reply_to));
  await until(() => R1 && cmEl(R1.id)?.querySelector('.mquote'));
  const q = R1 && cmEl(R1.id)?.querySelector('.mquote');
  check(q && /Bob Baker/.test(q.textContent) && /Do we mention the search\?/.test(q.textContent), 'comment: the quote above the answer ' + (q?.textContent || '-'));
  check(!bar(), 'comment: the bar is gone after sending');
  click(w, q); await until(() => cmEl(c1.id)?.classList.contains('msg-hit'));
  check(cmEl(c1.id)?.classList.contains('msg-hit'), 'comment: a tap on the quote marks the original (msg-hit)');
  check(await w.eval(`msgJump({art: 'c', id: 999999, task: ${T}})`) === false && /Message not found/.test(d.querySelector('#toast')?.textContent || ''), 'msgJump: an unknown comment says "Message not found"');
  await call('DELETE', `/api/comments/${c1.id}`, null, BCK);
  w.eval(`loadTimeline(${T})`); await until(() => R1 && cmEl(R1.id)?.querySelector('.mquote.del'));
  check(R1 && /Message deleted/.test(cmEl(R1.id)?.querySelector('.mquote.del')?.textContent || ''), 'comment: a deleted original shows "Message deleted"');
  w.close();

  // ================= team chat
  const rooms = (await call('GET', '/api/team')).rooms;
  const RID = rooms.find(x => x.kind === 'list' && x.list_id === L).id;
  const m1 = await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Who takes the release?'}, BCK);
  for (let i = 0; i < 60; i++) await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Filler ' + i}, i % 2 ? CK : BCK);
  const m2 = await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Anyone?'}, BCK);
  w = await boot({user: 'alice', hash: 'team/' + RID}); d = w.document;
  const tm = id => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${id}"]`);
  await until(() => tm(m2.id));
  check(tm(m2.id) && !tm(m1.id), 'team: data-mid="t:<id>", the first page does not hold the oldest message');
  click(w, tm(m2.id)?.querySelector('[data-act="msg-reply"]')); await sleep(150);
  const tbar = () => d.querySelector('.tcroom .rbar:not(.hidden)');
  check(tbar() && /Reply to Bob Baker/.test(tbar().textContent) && d.activeElement?.id === 'tc-in', 'team: Reply opens the bar above the box');
  d.querySelector('#tc-in').value = 'I do.';
  click(w, d.querySelector('[data-act="tc-send"]'));
  let mine = null;
  await until(async () => { mine = (await call('GET', `/api/team/rooms/${RID}/messages`)).messages.find(x => x.body === 'I do.'); return mine; });
  check(mine && mine.reply_to === m2.id, 'team: sent with reply_to');
  await until(() => mine && tm(mine.id)?.querySelector('.mquote'));
  check(mine && /Anyone\?/.test(tm(mine.id)?.querySelector('.mquote')?.textContent || '') && !tbar(), 'team: the quote above my answer, the bar is gone');
  check(await w.eval(`msgJump({art: 't', id: ${m1.id}, chat: ${RID}})`) === true && tm(m1.id)?.classList.contains('msg-hit'), 'msgJump team: pages back to the oldest message and marks it');
  click(w, mine && tm(mine.id)?.querySelector('.rxtog[data-act="tc-msg-menu"]')); await sleep(200);
  check([...d.querySelectorAll('[role="menuitem"]')].some(b => /^Reply$/.test(b.textContent.trim())), 'team: the message menu has "Reply"');
  w.close();

  // ================= agent chat
  const a1 = await say('Shall I update the README?');
  for (let i = 0; i < 40; i++) await say('Step ' + i);
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  const am = id => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelector('#chat-msgs .cmsg'));
  check(!am(a1.id), 'agent chat: the first page does not hold the oldest message');
  check(await w.eval(`msgJump({art: 'a', id: ${a1.id}, agent: ${AG}})`) === true && am(a1.id)?.classList.contains('msg-hit'), 'msgJump agent chat: pages back and marks it');
  click(w, am(a1.id)?.querySelector('[data-act="msg-reply"]')); await sleep(150);
  check(/Reply to Claude/.test(d.querySelector('#achat .rbar:not(.hidden), .chview .rbar:not(.hidden)')?.textContent || ''), 'agent chat: Reply opens the bar');
  d.querySelector('#chat-in').value = 'Yes, please.';
  click(w, d.querySelector('[data-act="chat-send"]'));
  let my = null;
  await until(async () => { my = (await call('GET', `/api/agents/${AG}/chat`)).messages.find(x => x.body === 'Yes, please.'); return my; });
  check(my && my.reply_to === a1.id && my.reply?.from === 'agent', 'agent chat: sent with reply_to');
  await until(() => my && am(my.id)?.querySelector('.mquote'));
  check(my && /Shall I update the README\?/.test(am(my.id)?.querySelector('.mquote')?.textContent || ''), 'agent chat: the quote above my message');
  const back = await v1('POST', `/agent/chats/${ME.id}`, {body: 'Done.', reply_to: my?.id});
  w.eval('chatLoad()'); await until(() => am(back.id)?.querySelector('.mquote'));
  check(/You/.test(am(back.id)?.querySelector('.mquote b')?.textContent || ''), 'agent chat: the agent\'s answer quotes "You"');
  w.close();

  // ================= Firefox: swipe (390 touch) and the desktop (1440)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview, .tcroom')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const m3 = await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Can you also check the screenshots for the store?'}, BCK);
  await firefox(async o => {
    const {cmd, ev, ctx, shot, drag} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#team/' + RID); await ready(ev); await sleep(1200);
    const box = async id => ev(`(() => { const m = document.querySelector('#tc-msgs .cmsg[data-mid="t:${id}"]'); if (!m) return null; m.scrollIntoView({block: 'center'}); const r = m.getBoundingClientRect(); return {x: Math.round(r.left), y: Math.round(r.top + r.height / 2), w: Math.round(r.width)}; })()`);
    const open = () => ev(`!!document.querySelector('.tcroom .rbar:not(.hidden)')`);
    let b = await box(m3.id);
    check(!!b, tag + ': the message is there');
    if (b) {
      await drag(10, b.y, 140, 0, 'touch'); await sleep(400);
      check(!(await open()), tag + ': a swipe from the left edge does not reply (the phone\'s Back gesture)');
      await drag(b.x + 40, b.y, 4, 160, 'touch'); await sleep(400);
      check(!(await open()), tag + ': an up / down move does not reply');
      b = await box(m3.id);
      await drag(b.x + 40, b.y, 130, 6, 'touch'); await sleep(500);
      check(await open(), tag + ': a swipe to the right opens the reply bar');
      const g = await ev(`(() => { const r = document.querySelector('.tcroom .rbar:not(.hidden)'); const x = r.querySelector('[data-act="reply-x"]').getBoundingClientRect(); const m = document.querySelector('#tc-msgs .cmsg[data-mid="t:${m3.id}"]');
        return {txt: r.textContent, xw: Math.round(x.width), xh: Math.round(x.height), back: !m.style.transform, arrow: !m.querySelector('.rswarr'), wide: document.documentElement.scrollWidth <= 390}; })()`);
      check(g && /Reply to Bob Baker/.test(g.txt) && g.xw >= 44 && g.xh >= 44, tag + ': the bar names Bob, X is a 44 px target ' + JSON.stringify(g));
      check(g && g.back && g.arrow && g.wide, tag + ': the message springs back, the arrow goes, nothing sticks out ' + JSON.stringify(g));
      await shot('p2330a-390-reply-bar.png');
    }
    // comments in the task panel
    await o.nav(B + '#t/' + T); await sleep(2500);
    const cb = await ev(`(() => { const m = document.querySelector('#detail .cm[data-mid="c:${c2.id}"]'); if (!m) return null; m.scrollIntoView({block: 'center'}); const r = m.getBoundingClientRect(); return {x: Math.round(r.left), y: Math.round(r.top + r.height / 2)}; })()`);
    if (cb) {
      await drag(Math.max(60, cb.x + 40), cb.y, 130, 4, 'touch'); await sleep(500);
      check(await ev(`/Reply to Bob Baker/.test(document.querySelector('#detail .rbar:not(.hidden)')?.textContent || '')`), tag + ': a swipe on a comment opens the reply bar');
      check(await ev(`!!document.querySelector('#detail') && !document.querySelector('#detail .dtop')?.style.transform`), tag + ': the task panel itself did not move (its own swipe stays out of the comments)');
    } else check(false, tag + ': the comment is there');
  }, true);
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#t/' + T); await sleep(2500);
    const g = await ev(`(() => { const q = document.querySelector('#detail .mquote'); const b = document.querySelector('#detail .cm [data-act="msg-reply"]');
      return {q: !!q, rb: b ? getComputedStyle(b.closest('.cacts')).opacity : null}; })()`);
    check(g && g.q && g.rb === '0', `${tag}: the quote shows, the Reply button waits for the mouse ` + JSON.stringify(g));
    await shot('p2330a-1440-comment-quote.png');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
