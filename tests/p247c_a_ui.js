// 2.47.1 UI tests, part A (#1720 several chats in the chat panel, one above the other), own container (start.sh), jsdom:
// - one agent chat = the panel as before (no window frame, no extra header buttons)
// - Ctrl + click / "Open in split window" adds a window; one window is live (the usual ids), the others are parked
//   (ids renamed); a pointer in a parked window makes it live, every window keeps its own draft
// - a team conversation as a window; a new answer of a parked agent only touches that window
// - fold, double-click on the divider shares the height evenly, close one window (its X, Esc), back to one = as before
// - more windows than fit (220 px each) fold to their header; the windows come back after a reload
// - phone: no split, a row of the open chats above the chat switches between them
// - Firefox (real layout, 1366 x 768): three windows share the height, every message box inside its window, the divider
//   follows the pointer, a double-click evens the heights, a fourth window folds one to its header
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p247c_a_ui', check, shots: 'P247C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'comments,collab,agents,team';
const DESK = {'(hover:hover) and (pointer:fine)': true};
const pe = (w, el, type, o = {}) => {
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, button: 0, ...o});
  if (!w.PointerEvent) { Object.defineProperty(ev, 'pointerId', {value: 1}); Object.defineProperty(ev, 'pointerType', {value: 'mouse'}); }
  el.dispatchEvent(ev); return ev;
};
const sec = (d, k) => d.querySelector(`#achat .cwin[data-cw="${k}"]`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  const ME = (await call('GET', '/api/me')).id || (await call('GET', '/api/state')).me?.id;
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const a1 = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const a2 = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'scout', display_name: 'Scout'});
  const a3 = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'tidy', display_name: 'Tidy'});
  const A1 = a1.id, A2 = a2.id, A3 = a3.id;
  const L = (await call('POST', '/api/lists', {name: 'Studio'})).id;
  for (const u of [BOB, A1]) await call('PUT', `/api/lists/${L}/members`, {user_id: u, role: 'edit'});
  for (const [u, n] of [[A2, 'Scouting'], [A3, 'Tidying']]) { const l = (await call('POST', '/api/lists', {name: n})).id; await call('PUT', `/api/lists/${l}/members`, {user_id: u, role: 'edit'}); }  // one agent per list
  const RID = ((await call('GET', '/api/team')).rooms || []).find(x => x.kind === 'list' && x.list_id === L)?.id;
  check(RID > 0, 'setup: the list room');
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Hello studio'});
  const ALICE = ME || 1;
  const say = (a, body) => fetch(B + `api/v1/agent/chats/${ALICE}`, {method: 'POST', headers: {...H, Authorization: 'Bearer ' + a.token}, body: JSON.stringify({body})}).then(x => x.json());
  await say(a1, 'Claude says hi');
  await say(a2, 'Scout says hi');

  // ================= desktop: one chat = as before
  let w = await boot({user: 'alice', hash: 'l/' + L, media: DESK}), d = w.document;
  await until(() => w.eval('S.booted && (S.agents || []).length >= 3'));
  w.eval(`chatOpen(${A1})`);
  await until(() => d.querySelector('#achat .cmsg'));
  check(!d.querySelector('#achat.cwsplit, #achat .cwin, #achat [data-cwact]'), '#1720: one agent chat: no window frame, no extra buttons');
  check(d.querySelector('#achat > .chath') && d.querySelector('#achat #chat-in'), '#1720: one agent chat: the panel as before (header + input box)');

  // ================= Ctrl + click adds a window
  d.body.insertAdjacentHTML('beforeend', `<button id="t-open2" data-act="chat-open" data-aid="${A2}">Scout</button>`);
  d.getElementById('t-open2').dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ctrlKey: true}));
  await until(() => sec(d, 'a:' + A2)?.querySelector('.cmsg'));
  check(d.querySelectorAll('#achat.cwsplit > .cwin').length === 2, '#1720: Ctrl + click opens a second window');
  check(d.querySelectorAll('#chat-in').length === 1 && w.eval('S.chat.aid') === A2 && sec(d, 'a:' + A2).querySelector('#chat-in'), '#1720: the new window is the live one (one #chat-in)');
  check(!!sec(d, 'a:' + A1).querySelector('[data-cwid="chat-in"]') && sec(d, 'a:' + A1).textContent.includes('Claude says hi'), '#1720: the first window stays (parked, ids renamed, messages kept)');
  check(d.querySelectorAll('#achat .cwsep').length === 1 && d.querySelector('.cwsep').getAttribute('role') === 'separator', '#1720: a divider (role separator) between the windows');
  check(!!sec(d, 'a:' + A1).querySelector('[data-cwact="fold"]') && !!sec(d, 'a:' + A1).querySelector('[data-cwact="menu"]'), '#1720: the window header has Fold and the window menu');
  // separate drafts
  let ci = d.getElementById('chat-in'); ci.value = 'draft two'; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
  pe(w, sec(d, 'a:' + A1).querySelector('.chmsgs'), 'pointerdown');
  check(w.eval('S.chat.aid') === A1 && sec(d, 'a:' + A1).querySelector('#chat-in') && sec(d, 'a:' + A2).querySelector('[data-cwid="chat-in"]'), '#1720: a pointer in a parked window makes it live');
  ci = d.getElementById('chat-in'); ci.value = 'draft one'; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(sec(d, 'a:' + A2).querySelector('textarea').value === 'draft two' && w.eval(`S.drafts['chat:${A2}']`) === 'draft two' && w.eval(`S.drafts['chat:${A1}']`) === 'draft one', '#1720: each window keeps its own draft');

  // ================= a team conversation as a window
  w.eval(`cw_split('t:${RID}')`);
  await until(() => sec(d, 't:' + RID)?.textContent.includes('Hello studio'));
  check(sec(d, 't:' + RID)?.textContent.includes('Hello studio'), '#1720: the team conversation opens as a window');
  check(!!sec(d, 't:' + RID)?.querySelector('#tc-in') && !!sec(d, 't:' + RID).querySelector('[data-cwact="close"]'), '#1720: the team window is live and has a close button');
  check(d.querySelectorAll('#achat .cwin').length === 3, '#1720: three windows');

  // ================= a new answer of a parked agent only touches that window
  pe(w, sec(d, 'a:' + A1).querySelector('.chmsgs'), 'pointerdown');
  const n1 = sec(d, 'a:' + A1).querySelector('.cmsg'), nt = sec(d, 't:' + RID).querySelector('.cmsg');
  // 2.98.1 (CI red): the 4 s change poll could redraw the other windows while CI is slow - held while counting (as p2412_ui)
  await until(() => w.eval('td_polling ? false : (td_polling = true)'), 80);
  w.eval(`window.__ins = {}; window.__mo = new MutationObserver(ms => { for (const m of ms) for (const x of m.addedNodes) if (x.nodeType === 1) { const k = m.target.closest?.('.cwin')?.dataset.cw || '-'; __ins[k] = (__ins[k] || 0) + 1; } }); __mo.observe($('#achat'), {childList: true, subtree: true}); 1`);
  await say(a2, 'Scout found something');
  w.eval('agentPoll()');
  await until(() => sec(d, 'a:' + A2)?.textContent.includes('Scout found something'), 60);
  check(sec(d, 'a:' + A2)?.textContent.includes('Scout found something'), '#1720: the parked window shows the new answer');
  const ins = w.eval('__mo.disconnect(); td_polling = false; __ins');
  check(!ins['a:' + A1] && !ins['t:' + RID] && !ins['-'], '#1720: only that window was drawn again ' + JSON.stringify(ins));
  check(sec(d, 'a:' + A1).querySelector('.cmsg') === n1 && sec(d, 't:' + RID).querySelector('.cmsg') === nt, '#1720: the other windows keep their nodes');

  // ================= fold, divider, close
  sec(d, 'a:' + A1).querySelector('[data-cwact="fold"]').click();
  check(sec(d, 'a:' + A1).classList.contains('cwc') && sec(d, 'a:' + A1).querySelector('[data-cwact="fold"]').getAttribute('aria-expanded') === 'false', '#1720: Fold folds the window to its header');
  sec(d, 'a:' + A1).querySelector('[data-cwact="fold"]').click();
  check(!sec(d, 'a:' + A1).classList.contains('cwc'), '#1720: ... and unfolds it again');
  w.eval('S.cw.wins[0].h = 2.5; S.cw.wins[1].h = 0.5; cw_layout(); 1');
  check(sec(d, 'a:' + A1).style.flexGrow === '2.5', '#1720: the heights are shares (flex-grow)');
  d.querySelector('#achat .cwsep').dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true}));
  check(w.eval('S.cw.wins.every(x => x.h === 1)') && sec(d, 'a:' + A1).style.flexGrow === '1', '#1720: a double-click on the divider shares the height evenly');
  const sep = d.querySelector('#achat .cwsep'); sep.focus();
  sep.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
  check(w.eval('S.cw.wins.every(x => x.h === 1)'), '#1720: the divider works with the keyboard');
  // the window menu: move down
  const i0 = w.eval(`S.cw.wins.findIndex(x => x.k === 'a:${A1}')`);
  w.eval(`cw_move('a:${A1}', ${i0 < 2 ? 1 : -1})`);
  check(w.eval(`S.cw.wins.findIndex(x => x.k === 'a:${A1}')`) === i0 + (i0 < 2 ? 1 : -1) && [...d.querySelectorAll('#achat .cwin')].map(x => x.dataset.cw).join() === w.eval('S.cw.wins.map(x => x.k).join()'), '#1720: Move up / down changes the order ' + w.eval('S.cw.wins.map(x => x.k).join()'));
  check(d.querySelectorAll('#chat-in').length === 1 && d.querySelectorAll('#tc-in').length === 1, '#1720: after drawing again one live agent and one live team window');
  // close the agent window by its X
  sec(d, 'a:' + A2).querySelector('[data-act="chat-close"]').click();
  check(!sec(d, 'a:' + A2) && d.querySelectorAll('#achat .cwin').length === 2 && w.eval('S.chat.aid') === A1, '#1720: the X closes only its window');
  // Esc in the team window closes only it: back to one agent window = as before
  const tin = d.getElementById('tc-in'); tin.focus();
  tin.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
  await sleep(100);
  check(!d.querySelector('#achat.cwsplit') && d.querySelector('#achat > .chath') && !d.getElementById('achat').classList.contains('hidden') && w.eval('S.chat.aid') === A1, '#1720: Esc closes only that window; one left = the panel as before');
  check(d.getElementById('chat-in')?.value === 'draft one', '#1720: ... with its draft');

  // ================= the team view and a team window in the panel at once: one of them holds the live ids
  const DM = (await call('POST', '/api/team/dm', {user_id: BOB})).id;
  await call('POST', `/api/team/rooms/${DM}/messages`, {body: 'Hi Bob'});
  w.eval(`cw_split('t:${RID}')`);
  await until(() => sec(d, 't:' + RID)?.querySelector('#tc-in'));
  w.location.hash = 'team/' + DM;
  await until(() => d.querySelector('#view .tcroom')?.textContent.includes('Hi Bob'));
  check(d.querySelectorAll('#tc-in').length === 1 && !!d.querySelector('#view #tc-in') && w.eval('S.tc.rid') === DM, '#1720: the team view opens a conversation: it is live, the panel window parks');
  pe(w, sec(d, 't:' + RID).querySelector('.chmsgs'), 'pointerdown');
  check(d.querySelectorAll('#tc-in').length === 1 && !!sec(d, 't:' + RID).querySelector('#tc-in') && w.eval('S.tc.rid') === RID, '#1720: a pointer in the panel window makes it live (the team view parks)');
  w.eval('renderView()'); await sleep(300);
  check(d.querySelector('#view .tcroom')?.textContent.includes('Hi Bob') && !d.querySelector('#view #tc-in') && d.querySelectorAll('#tc-in').length === 1, '#1720: the team view drawn again keeps its own conversation (no second #tc-in)');
  pe(w, d.querySelector('#view .tcroom .chmsgs'), 'pointerdown');
  check(w.eval('S.tc.rid') === DM && !!d.querySelector('#view #tc-in') && !!sec(d, 't:' + RID).querySelector('[data-cwid="tc-in"]'), '#1720: a pointer in the team view takes its conversation back');
  pe(w, sec(d, 't:' + RID).querySelector('.chmsgs'), 'pointerdown');
  w.location.hash = 'l/' + L;
  // 2.47.3: wait for the state instead of a fixed 800 ms (the team reload after leaving is slower on a busy CI runner)
  await until(() => w.eval('S.tc.rid') === RID && !!sec(d, 't:' + RID)?.querySelector('#tc-in') && sec(d, 't:' + RID).textContent.includes('Hello studio'), 30);
  check(w.eval('S.tc.rid') === RID && !!sec(d, 't:' + RID).querySelector('#tc-in') && sec(d, 't:' + RID).textContent.includes('Hello studio'), '#1720: leaving the team view keeps the live panel window ' + JSON.stringify({rid: w.eval('S.tc.rid'), RID, DM, lt: w.eval('S.cw.lt'), inp: !!sec(d, 't:' + RID)?.querySelector('#tc-in'), n: d.querySelectorAll('#tc-in').length, txt: (sec(d, 't:' + RID)?.textContent || '').slice(0, 80), hash: w.location.hash}));
  // 2.83.0 (#1774): the split button in the head of a team room (a phone has no long press)
  check(w.eval("o3b_splitBtn({kind: 'list'}, 5)").includes('data-act="tc-split"') && w.eval("o3b_splitBtn({kind: 'dm'}, 5)") === '', '#1774: the head button for a list room, none for a direct message');
  w.eval("cw_ren = 't:5'; 1"); check(w.eval("o3b_splitBtn({kind: 'list'}, 5)") === '', '#1774: none inside the panel window itself'); w.eval("cw_ren = ''; 1");
  d.body.insertAdjacentHTML('beforeend', `<button id="t-split" data-act="tc-split" data-rid="${RID}">split</button>`);
  d.getElementById('t-split').click();
  await until(() => sec(d, 't:' + RID));
  check(!!sec(d, 't:' + RID), '#1774: a click on the head button opens the room as a window');
  w.eval(`cw_close('t:${RID}')`);
  await sleep(100);
  // 2.83.0 (#1775): the colour row on an agent's person card for those who may change it (rights: p247c_b_api)
  const mcCol = () => { w.eval(`personCard(document.querySelector('#top h1') || document.body, ${A1})`); return !!d.querySelector('.mcard .pfcol [data-accol]'); };
  check(w.eval(`!!S.agents.find(a => a.id === ${A1}).can_color`) && mcCol(), '#1775: the admin sees the colour row on the agent\'s card');
  w.eval(`(closePop(), S.agents.find(a => a.id === ${A1}).can_color = false, 1)`);
  check(!mcCol(), '#1775: without can_color no colour row on the card');
  w.eval(`(closePop(), S.agents.find(a => a.id === ${A1}).can_color = true, 1)`);
  await sleep(100);

  // ================= more windows than fit fold (768 px: three open)
  for (const k of [`a:${A2}`, `a:${A3}`, `t:${RID}`]) w.eval(`cw_split('${k}')`);
  await sleep(600);
  const W = w.eval('JSON.stringify(S.cw.wins)');
  check(w.eval('S.cw.wins.length') === 4 && w.eval('S.cw.wins.filter(x => !x.c).length') === 3 && d.querySelectorAll('#achat .cwin.cwc').length === 1, '#1720: four windows at 768 px: one folds to its header ' + W);
  check(w.eval(`!S.cw.wins.find(x => x.k === S.cw.act).c`), '#1720: the active window stays open');
  const store = w.__store;
  check(/"a:\d+"/.test(store['tasks.cwins'] || '') && JSON.parse(store['tasks.cwins']).open === true, '#1720: the open chats are remembered on the device');
  w.close();

  // ================= after a reload
  w = await boot({user: 'alice', hash: 'l/' + L, media: DESK, ls: store, wait: 3500}); d = w.document;
  await until(() => d.querySelectorAll('#achat.cwsplit .cwin').length === 4);
  check(d.querySelectorAll('#achat.cwsplit .cwin').length === 4, '#1720: the windows come back after a reload');
  check([...d.querySelectorAll('#achat .cwin')].map(x => x.dataset.cw).join() === JSON.parse(store['tasks.cwins']).wins.map(x => x.k).join(), '#1720: ... in the same order');
  w.eval(`cw_fold('t:${RID}', false)`);  // the window furthest from the active one is the folded one
  await until(() => sec(d, 't:' + RID)?.textContent.includes('Hello studio'));
  check(sec(d, 't:' + RID)?.textContent.includes('Hello studio') && w.eval('S.cw.wins.filter(x => !x.c).length') === 3, '#1720: ... a folded team window loads its messages when it is unfolded');
  // a chat this person may no longer open is dropped quietly
  await call('PATCH', `/api/admin/agents/${A3}`, {enabled: false});
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L, media: DESK, ls: store, wait: 3500}); d = w.document;
  await until(() => d.querySelectorAll('#achat.cwsplit .cwin').length >= 3);
  check(!sec(d, 'a:' + A3) && d.querySelectorAll('#achat .cwin').length === 3, '#1720: a paused agent is not restored');
  w.eval('chatClose()');
  check(d.getElementById('achat').classList.contains('hidden') && !w.eval('S.cw.wins.length'), '#1720: closing the panel closes all its windows');
  w.close();

  // ================= phone: no split, a row of the open chats
  const ms = {...store, 'tasks.cwins': JSON.stringify({u: JSON.parse(store['tasks.cwins']).u, open: false, wins: [{k: 'a:' + A1, h: 1, c: false}, {k: 'a:' + A2, h: 1, c: false}, {k: 't:' + RID, h: 1, c: false}]})};
  w = await boot({user: 'alice', mobile: true, hash: 'agents/' + A1, ls: ms, wait: 3500}); d = w.document;
  await until(() => d.querySelector('#view .chview .cwsw'));
  check(!d.querySelector('#achat.cwsplit'), '#1720 phone: no split');
  check(d.querySelectorAll('#view .cwsw .cwswb').length === 3 && d.querySelector('#view .cwsw .cwswb.on')?.dataset.cwsw === 'a:' + A1, '#1720 phone: a row with the three open chats, this one marked ' + [...d.querySelectorAll('#view .cwsw button')].map(b => b.dataset.cwsw + (b.classList.contains('on') ? '*' : '')).join());
  d.querySelector(`#view .cwsw [data-cwsw="t:${RID}"]`).click();
  await until(() => /#team\//.test(w.location.hash) && d.querySelector('#view .tcroom .cwsw'));
  check(w.location.hash === '#team/' + RID && !!d.querySelector('#view .tcroom .cwsw .cwswb.on[data-cwsw="t:' + RID + '"]'), '#1720 phone: a tap switches to the conversation (the row stays)');
  w.close();

  // ================= Firefox: the real layout
  await call('PATCH', `/api/admin/agents/${A3}`, {enabled: true});
  await firefox(async ({cmd, ev, nav, ctx, shot, drag}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1366, height: 768}});
    await nav(B + '#l/' + L);
    for (let i = 0; i < 30 && !(await ev('!!(window.S && S.booted)').catch(() => false)); i++) await sleep(300);
    await ev(`(chatOpen(${A1}), 1)`); await sleep(1200);
    await ev(`(cw_split('a:${A2}'), cw_split('t:${RID}'), 1)`); await sleep(1800);
    const LAY = `(() => { const p = document.getElementById('achat'); return {ph: p.clientHeight, sh: p.scrollHeight, ss: [...p.querySelectorAll('.cwin')].map(s => { const r = s.getBoundingClientRect(), c = s.querySelector('.chcomp')?.getBoundingClientRect(); return {h: Math.round(r.height), c: s.classList.contains('cwc'), comp: c ? Math.round(r.bottom - c.bottom) : -1}; })}; })()`;
    let m = await ev(LAY);
    check(m.ss.length === 3 && Math.max(...m.ss.map(x => x.h)) - Math.min(...m.ss.map(x => x.h)) <= 2 && m.sh <= m.ph + 1, '#1720 Firefox: three windows share the height evenly, nothing overflows ' + JSON.stringify(m));
    check(m.ss.every(x => x.comp >= 0), '#1720 Firefox: every message box sits inside its window ' + JSON.stringify(m.ss));
    await shot('p247c-a-three.png');
    const sp = await ev(`(() => { const r = document.querySelector('#achat .cwsep').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
    await drag(sp.x, sp.y, 0, 30); await sleep(300);
    const m2 = await ev(LAY);
    check(Math.abs(m2.ss[0].h - m.ss[0].h - 30) <= 3 && Math.abs(m2.ss[1].h - m.ss[1].h + 30) <= 3, '#1720 Firefox: the divider follows the pointer ' + JSON.stringify(m2.ss.map(x => x.h)));
    await ev(`(document.querySelector('#achat .cwsep').dispatchEvent(new MouseEvent('dblclick', {bubbles: true})), 1)`); await sleep(200);
    m = await ev(LAY);
    check(Math.max(...m.ss.map(x => x.h)) - Math.min(...m.ss.map(x => x.h)) <= 2, '#1720 Firefox: a double-click evens the heights ' + JSON.stringify(m.ss.map(x => x.h)));
    await ev(`(cw_split('a:${A3}'), 1)`); await sleep(1500);
    m = await ev(LAY);
    check(m.ss.length === 4 && m.ss.filter(x => x.c).length === 1 && m.ss.filter(x => !x.c).every(x => x.h >= 219 && x.comp >= 0) && m.sh <= m.ph + 1, '#1720 Firefox: four windows at 768 px: one folds to its header, three keep 220 px ' + JSON.stringify(m));
    await shot('p247c-a-four.png');
  }, false);

  console.log(`p247c_a_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
