// 2.119.1 D UI tests (own container, start.sh; P21191D_NOSTART=1: the container runs already). jsdom:
// - #2310 (the wobbly p247c_a_ui, #1720): a patch of an unchanged agent chat swaps no node (the job card filter came back
//   as hidden="" and was replaced on every patch; a parked window that takes its ids back has them last in its attributes)
// - #2310: a team window in the chat panel that is parked (or made live again) while its first load is still out loads
//   its messages anyway (it stayed at "Loading…" for good)
// Firefox (real layout, phone 390 x 844, touch):
// - #2206 the choosing mark in Documents has a 44 x 44 px touch target (the circle stays 1.75rem, the row no higher)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21191_d_ui', check, shots: 'P21191D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21191D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team,files,docs';
const DESK = {'(hover:hover) and (pointer:fine)': true};
const pe = (w, el, type) => {
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, button: 0});
  if (!w.PointerEvent) { Object.defineProperty(ev, 'pointerId', {value: 1}); Object.defineProperty(ev, 'pointerType', {value: 'mouse'}); }
  el.dispatchEvent(ev);
};
const sec = (d, k) => d.querySelector(`#achat .cwin[data-cw="${k}"]`);
// added element nodes below #achat while fn runs (and shortly after), per window
const watch = async (w, fn, ms = 400) => {
  w.eval(`window.__ad = []; window.__mo = new MutationObserver(ms => { for (const m of ms) for (const x of m.addedNodes) if (x.nodeType === 1) __ad.push((m.target.closest?.('.cwin')?.dataset.cw || '-') + ' ' + x.tagName + '#' + x.id); }); __mo.observe($('#achat'), {childList: true, subtree: true}); 1`);
  w.eval(fn); await sleep(ms);
  return w.eval('__mo.disconnect(); __ad');
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  const ME = (await call('GET', '/api/me')).id || 1;
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const a1 = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const a2 = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'scout', display_name: 'Scout'});
  const A1 = a1.id, A2 = a2.id;
  const L = (await call('POST', '/api/lists', {name: 'Studio'})).id;
  for (const u of [BOB, A1]) await call('PUT', `/api/lists/${L}/members`, {user_id: u, role: 'edit'});
  const l2 = (await call('POST', '/api/lists', {name: 'Scouting'})).id; await call('PUT', `/api/lists/${l2}/members`, {user_id: A2, role: 'edit'});
  const RID = ((await call('GET', '/api/team')).rooms || []).find(x => x.kind === 'list' && x.list_id === L)?.id;
  check(RID > 0, 'setup: the list room');
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Hello studio'});
  const say = (a, body) => fetch(B + `api/v1/agent/chats/${ME}`, {method: 'POST', headers: {...H, Authorization: 'Bearer ' + a.token}, body: JSON.stringify({body})}).then(x => x.json());
  await say(a1, 'Claude says hi');
  await say(a2, 'Scout says hi');

  let w = await boot({user: 'alice', hash: 'l/' + L, media: DESK}), d = w.document;
  await until(() => w.eval('S.booted && (S.agents || []).length >= 2'));

  // ================= #2310: the node comparison
  check(w.eval(`(() => { const t = document.createElement('div'); t.innerHTML = '<span class="x" id="q" hidden></span>'; return typeof wk_sameEl === 'function' && wk_sameEl(t.firstChild, '<span class="x" id="q" hidden></span>'); })()`), '#2310: an element with hidden is the same as its HTML');
  check(w.eval(`(() => { const e = document.createElement('span'); e.className = 'x'; e.setAttribute('role', 'status'); e.id = 'q'; e.textContent = 'a'; return typeof wk_sameEl === 'function' && wk_sameEl(e, '<span class="x" id="q" role="status">a</span>'); })()`), '#2310: ... and with its attributes in another order');
  check(!w.eval(`(() => { const e = document.createElement('span'); e.id = 'q'; e.textContent = 'a'; return typeof wk_sameEl !== 'function' || wk_sameEl(e, '<span id="q">b</span>') || wk_sameEl(e, '<span id="q">a</span><i></i>'); })()`), '#2310: another text / a second node is not the same');

  // ================= #2310: an unchanged agent chat: a patch swaps nothing
  w.eval(`chatOpen(${A1})`);
  await until(() => d.querySelector('#achat .cmsg'));
  await sleep(500);
  let ad = await watch(w, 'chatPatch(); agentLive(); chatPatch(); agentLive(); 1');
  check(!ad.length, '#2310: one chat: an unchanged patch swaps no node ' + JSON.stringify(ad));

  // ================= #2310: two windows; the first one parked and live again (its ids come back last)
  w.eval(`cw_split('a:${A2}')`);
  await until(() => sec(d, 'a:' + A2)?.querySelector('.cmsg'));
  pe(w, sec(d, 'a:' + A1).querySelector('.chmsgs'), 'pointerdown');
  check(w.eval('S.chat.aid') === A1 && !!sec(d, 'a:' + A1).querySelector('#chat-in'), '#2310: setup: the first window is live again');
  await sleep(800);  // its fresh load (chatLoad) is in
  ad = await watch(w, 'chatPatch(); agentLive(); chatDraw(); 1');
  check(!ad.length, '#2310: two windows: a patch of the live one swaps no node ' + JSON.stringify(ad));
  ad = await watch(w, 'agentPoll(); 1', 800);
  check(!ad.length, '#2310: ... nor a poll of the agents without news ' + JSON.stringify(ad));
  w.eval('chatClose()');
  await sleep(100);

  // ================= #2310: a team window parked while its first load is still out
  w.eval(`(cw_split('t:${RID}'), cw_tcPark(), 1)`);  // the same as the team view opening right away (p247c_a_ui on a slow runner)
  check(w.eval('S.cw.lt') === '' && !!sec(d, 't:' + RID), '#2310: setup: the team window is parked');
  await until(() => sec(d, 't:' + RID)?.textContent.includes('Hello studio'));
  check(sec(d, 't:' + RID)?.textContent.includes('Hello studio'), '#2310: the parked window loads its messages (no "Loading…" for good) ' + (sec(d, 't:' + RID)?.textContent || '').replace(/\s+/g, ' ').slice(0, 80));
  w.eval(`cw_close('t:${RID}')`); w.eval('chatClose()');
  await sleep(100);
  // ... and made live again at once (the parked answer lands in the old state)
  w.eval(`(cw_split('t:${RID}'), cw_tcPark(), cw_act('t:${RID}'), 1)`);
  check(w.eval('S.cw.lt') === 't:' + RID && !!sec(d, 't:' + RID)?.querySelector('#tc-in'), '#2310: setup: the team window is live again');
  await until(() => w.eval('!!S.tc.room') && sec(d, 't:' + RID)?.textContent.includes('Hello studio'));
  check(w.eval(`S.tc.rid === ${RID} && !!S.tc.room`) && sec(d, 't:' + RID)?.textContent.includes('Hello studio'), '#2310: live again before its messages came: they come');
  w.close();

  // ================= #2206 Firefox: the choosing mark in Documents, measured
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob(['Rechnung Beispiel 12,50 EUR']), 'beleg.txt');
  await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#docs');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('[data-dcsel="mode"]')`).catch(() => false)); i++) await sleep(300);
    const rowH = () => ev(`Math.round(document.querySelector('.dc-card')?.getBoundingClientRect().height || 0)`);
    const h0 = await rowH();
    await ev(`(document.querySelector('[data-dcsel="mode"]').click(), 1)`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('.dc-selmark')`)); i++) await sleep(200);
    await sleep(300);
    // the target = the mark's padding box grown by its ::after insets; and a tap 21 px off its centre still lands on the mark
    const m = await ev(`(() => { const k = document.querySelector('.dc-selmark'); if (!k) return null; const r = k.getBoundingClientRect(), c = getComputedStyle(k), a = getComputedStyle(k, '::after');
      const bw = parseFloat(c.borderLeftWidth) + parseFloat(c.borderRightWidth), bh = parseFloat(c.borderTopWidth) + parseFloat(c.borderBottomWidth);
      const x = r.left + r.width / 2, y = r.top + r.height / 2, hit = [[-21, 0], [21, 0], [0, -21], [0, 21], [-20, -20], [20, 20]].map(([dx, dy]) => document.elementFromPoint(x + dx, y + dy) === k);
      return {mark: Math.round(r.width), w: r.width - bw - parseFloat(a.left) - parseFloat(a.right), h: r.height - bh - parseFloat(a.top) - parseFloat(a.bottom), hit}; })()`);
    check(m && m.w >= 44 && m.h >= 44, '#2206: the choosing mark in Documents has a 44 x 44 px touch target ' + JSON.stringify(m));
    check(m && m.hit.every(Boolean), '#2206: ... a tap 21 px off its centre still hits the mark ' + JSON.stringify(m?.hit));
    check(m && m.mark === 28, '#2206: ... the circle itself stays 1.75rem ' + m?.mark);
    check(await rowH() === h0, '#2206: ... the card is no higher ' + h0);
    await shot('p21191-d-docs-select.png');
  }, true);

  console.log(`p21191_d_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
