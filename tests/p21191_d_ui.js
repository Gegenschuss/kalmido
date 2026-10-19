// 2.119.1 D UI tests (own container, start.sh; P21191D_NOSTART=1: the container runs already). jsdom:
// - #2310 (the wobbly p247c_a_ui, #1720): a patch of an unchanged agent chat swaps no node (the job card filter came back
//   as hidden="" and was replaced on every patch; a parked window that takes its ids back has them last in its attributes)
// - #2310: a team window in the chat panel that is parked (or made live again) while its first load is still out loads
//   its messages anyway (it stayed at "Loading…" for good)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
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

  console.log(`p21191_d_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
