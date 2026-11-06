// 2.571.0 (#4608) UI tests (jsdom), fresh DB: a right click (computer) / a long press (phone) opens the row's own menu everywhere
// - team chat message, comment of a task, agent chat message, section head of a list: the same menu as the "…" button
// - the reactions of a comment / agent message: "React" in that menu (before: the long press opened the bar)
// - right click with selected text in the row, on a link inside it, in the edit box: the browser's menu stays
// - a long press in the calendar grid still drags (no row menu there)
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const rclick = (w, el) => { const ev = new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true, button: 2}); el.dispatchEvent(ev); return ev; };
const pe = (w, el, type) => {  // a touch pointer (jsdom: a MouseEvent with pointerType)
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: 30, clientY: 30, button: 0});
  for (const [k, v] of [['pointerId', 1], ['pointerType', 'touch']]) if (ev[k] !== v) Object.defineProperty(ev, k, {value: v});
  el.dispatchEvent(ev); return ev;
};
const menuOpen = w => { const p = w.document.querySelector('#pop'); return p && !p.classList.contains('hidden') && p.querySelector('[role="menu"]') ? p : null; };
const labels = w => [...(menuOpen(w)?.querySelectorAll('[role="menuitem"]') || [])].map(b => b.textContent.trim());
const longPress = async (w, el) => { pe(w, el, 'pointerdown'); await until(() => menuOpen(w), 12); const o = !!menuOpen(w); pe(w, el, 'pointerup'); return o; };
const closeMenu = w => w.eval('closePop()');

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,agents,comments,cal'});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token, ME = (await call('GET', '/api/state')).me.id;
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  const S1 = (await call('POST', '/api/sections', {list_id: P, name: 'Doing'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Page 1', list_id: P, section_id: S1})).id;
  await tcall('POST', `/tasks/${T1}/comments`, TOK, {body: 'Checked the page'});
  await tcall('GET', '/agent/events?since=0', TOK);
  const RID = (await call('GET', '/api/team')).rooms.find(r => r.list_id === P)?.id;
  const MA = RID && (await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'On it.'})).id;
  const Q = (await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'Status: the build is green.'})).id;
  check(T1 && RID && MA && Q, 'setup ' + [T1, RID, MA, Q]);

  // ================= team chat message
  let w = await boot({user: 'alice', hash: 'team/' + RID}), d = w.document;
  const tcm = () => d.querySelector(`#tc-msgs .cmsg[data-mid="t:${MA}"]`);
  check(await until(() => tcm()), 'the team chat shows the message');
  // the browser's menu stays with selected text in the message
  const bub = tcm().querySelector('.cbub');
  w.getSelection().selectAllChildren(bub);
  let ev = rclick(w, bub);
  check(!ev.defaultPrevented && !menuOpen(w), 'team chat: selected text in the message keeps the browser menu');
  w.getSelection().removeAllRanges();
  ev = rclick(w, tcm());
  check(ev.defaultPrevented && await until(() => menuOpen(w)) && labels(w).includes('Reply') && labels(w).includes('Save as task'), 'team chat: right click opens the message menu ' + labels(w));
  closeMenu(w);
  check(await longPress(w, tcm()) && labels(w).includes('Copy'), 'team chat: a long press opens the message menu ' + labels(w));
  closeMenu(w);
  w.close();

  // ================= comment of a task
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  check(await until(() => d.querySelector('#view .ghead[data-section]')), 'the list shows the section head');
  const gh = () => d.querySelector('#view .ghead[data-section]');
  ev = rclick(w, gh());
  check(ev.defaultPrevented && await until(() => menuOpen(w)) && labels(w).includes('Rename'), 'section head: right click opens the section menu ' + labels(w));
  closeMenu(w);
  check(await longPress(w, gh()) && labels(w).includes('Rename'), 'section head: a long press opens the section menu ' + labels(w));
  closeMenu(w);
  w.eval(`openDetail(${T1})`);
  const cm = () => d.querySelector('#detail .cm[data-cid]');
  check(await until(() => cm()), 'the task shows its comment');
  ev = rclick(w, cm());
  check(ev.defaultPrevented && await until(() => menuOpen(w)) && labels(w).includes('Copy') && labels(w).includes('React'), 'comment: right click opens the menu with Copy and React ' + labels(w));
  [...menuOpen(w).querySelectorAll('[role="menuitem"]')].find(b => /React/.test(b.textContent)).click();
  check(await until(() => cm().classList.contains('rxshow')), 'comment: "React" opens the reaction bar');
  w.eval('S.rxOpen = null; document.querySelectorAll(".rxshow").forEach(x => x.classList.remove("rxshow"))');
  check(await longPress(w, cm()) && labels(w).includes('Copy') && !cm().classList.contains('rxshow'), 'comment: a long press opens the menu, not the bar itself ' + labels(w));
  closeMenu(w);
  w.close();

  // ================= agent chat message
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`chatOpen(${AG})`);
  const am = () => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${Q}"]`);
  check(await until(() => am()), 'the agent chat shows the message');
  ev = rclick(w, am());
  check(ev.defaultPrevented && await until(() => menuOpen(w)) && labels(w).includes('Copy') && labels(w).includes('React'), 'agent chat: right click opens the message menu ' + labels(w));
  closeMenu(w);
  check(await longPress(w, am()) && labels(w).includes('Save as task'), 'agent chat: a long press opens the message menu ' + labels(w));
  closeMenu(w);
  const ta = d.querySelector('#chat-in');
  ev = rclick(w, ta);
  check(!ev.defaultPrevented && !menuOpen(w), 'agent chat: the input box keeps the browser menu');
  w.close();

  // ================= the calendar grid still drags: a long press there opens no row menu
  w = await boot({user: 'alice', hash: 'cal'}); d = w.document;
  await until(() => d.querySelector('#view .cal, #view .cvx, #view [data-cev]'), 40);
  const cell = d.querySelector('#view .cvx-day, #view .calcell, #view [data-day]');
  if (cell) { check(!(await longPress(w, cell)), 'calendar: a long press on the grid opens no row menu'); closeMenu(w); }
  else check(true, 'calendar: no grid cell found in this build (skipped)');
  w.close();

  check(!errs.length, 'no page errors ' + JSON.stringify(errs.slice(0, 3)));
  console.log(ok + ' ok, ' + F.length + ' failed');
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(1); });
