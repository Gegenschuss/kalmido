// 2.521.0 UI test, part B (#4393): a reply to an older message does not jump to the end. Own container (start.sh), Firefox 1280 px.
// kalmido-suite: fresh
// - agent chat: scrolled up, reply to an old message: the view stays (scrollTop), "Sent" and "New message ↓"; an agent answer
//   that comes in meanwhile does not pull it down either (only the pill); the pill goes to the end; at the end a reply still
//   goes to the end; without a reply (scrolled up) it goes to the end as before
// - team chat (the room of a shared project) and a thread: the same (scrolled up + reply = the place stays, pill; without a reply = the end)
// freelancer-matrix: agents (frida has no organisation and chats with her agent)
// P2521B_NOSTART=1 = the server already runs. Screenshots: P2521B_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2521_b_chatreply_ui', check, shots: 'P2521B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2521B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'comments,collab,agents,team';
const LONG = '\n\nwith a second paragraph so the list is tall enough to scroll';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Solo', password: 'password123', email: 'frida@example.com', orgs: []});
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CF = await login('frida'), CB = await login('bob');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'P4: frida has no organisation');
  // frida's agent and a chat tall enough to scroll
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  const ag = await call(CF, 'POST', '/api/my/agents', {username: 'helper', display_name: 'Helper', scopes: ['read', 'write']});
  check(ag.http < 300 && ag.id && ag.token, 'frida\'s agent ' + ag.http);
  const AG = ag.id, TOK = ag.token, ME = (await call(CF, 'GET', '/api/state')).me.id;
  const say = body => tcall('POST', `/agent/chats/${ME}`, TOK, {body});
  const P = (await call(CF, 'POST', '/api/lists', {name: 'Website', kind: 'project'})).id;  // the agent answers people it shares a list with
  await call(CF, 'PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  check((await say('Hello')).status < 300, 'the agent answers in the chat');
  for (let i = 1; i <= 24; i++) {
    if (i % 2) await call(CF, 'POST', `/api/agents/${AG}/chat`, {body: `Question ${i}`});
    else await say(`Answer ${i}${LONG}`);
  }
  // alice and bob share a project: its room with 30 messages, the first one with a thread of 20 answers
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Studio', kind: 'project'})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const RID = (((await call(CA, 'GET', '/api/team')).rooms || []).find(x => x.kind === 'list' && x.list_id === L) || {}).id;
  check(RID > 0, 'the room of the shared project');
  const ROOT = (await call(CB, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Thread root'})).id;
  for (let i = 1; i <= 29; i++) await call(i % 2 ? CB : CA, 'POST', `/api/team/rooms/${RID}/messages`, {body: `Room ${i}${LONG}`});
  for (let i = 1; i <= 20; i++) await call(i % 2 ? CB : CA, 'POST', `/api/team/rooms/${RID}/messages`, {body: `Thread ${i}${LONG}`, thread_of: ROOT});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (ev, nav, u) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`) === 200, `${u} signs in`);
  };
  // the state of a box: distance to the end, scrollTop, the pill shown
  const ST = (box, pill) => `(() => { const b = document.querySelector('${box}'); if (!b) return {}; const p = document.querySelector('${pill}');
    return {gap: Math.round(b.scrollHeight - b.scrollTop - b.clientHeight), top: Math.round(b.scrollTop), pill: !!p && !p.classList.contains('hidden'), toast: document.querySelector('#toast:not(.hidden)')?.textContent || ''}; })()`;
  const scrollTo = (box, top) => `(() => { const b = document.querySelector('${box}'); b.scrollTop = ${top === 'end' ? 'b.scrollHeight' : top}; b.dispatchEvent(new Event('scroll')); return Math.round(b.scrollTop); })()`;
  // reply (or not) to the first message of the box, then (the reply bar drawn and laid out, as a person sees it) send a text
  const send = (box, inp, act, text, reply) => `(async () => { const b = document.querySelector('${box}');
    ${reply ? `b.querySelector('[data-mid] [data-act="msg-reply"]').click(); await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));` : ''}
    const t = document.querySelector('${inp}'); t.value = ${JSON.stringify(text)}; t.dispatchEvent(new Event('input', {bubbles: true}));
    document.querySelector('[data-act="${act}"]').click(); return 1; })()`;
  const sent = (box, text) => `[...document.querySelectorAll('${box} [data-mid]')].some(x => x.textContent.includes(${JSON.stringify(text)})) && !document.querySelector('${box} .csdpend')`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});

    // ================= the agent chat (frida, the side panel)
    await signIn(ev, nav, 'frida');
    await nav(B + '#today'); await ready(ev, `!!document.querySelector('#top h1')`, 60);
    await ev(`(() => { chatOpen(${AG}); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#chat-msgs .cmsg').length >= 20`, 60), 'agent: the chat');
    const A = ST('#chat-msgs', '#chat-new');
    await ready(ev, `${A}.gap <= 3`, 20);
    // scrolled up, a reply to an old message: the view stays, "Sent" and the pill
    const t0 = await ev(scrollTo('#chat-msgs', 120));
   
    await ev(send('#chat-msgs', '#chat-in', 'chat-send', 'Reply while reading up', true));
    check(await ready(ev, sent('#chat-msgs', 'Reply while reading up'), 40), 'agent: the reply is sent');
    let s = await ev(A);
    check(Math.abs(s.top - t0) <= 2 && s.gap > 50 && s.pill && /Sent/.test(s.toast), `#4393 agent: reply scrolled up: the view stays (${t0}), "Sent", "New message ↓" ${JSON.stringify(s)}`);
    await shot('p2521b-agent-reply.png');
    // the agent answers meanwhile: still not pulled down
    const a1 = await say('An answer while you read up');
    await ev(`chatLoad().then(() => 1)`);
    check(await ready(ev, `!!document.querySelector('#chat-msgs [data-mid="a:${a1.id}"]')`, 40), 'agent: the answer arrives');

    s = await ev(A);
    check(Math.abs(s.top - t0) <= 2 && s.pill, `#4393 agent: an agent answer does not pull the view down ${JSON.stringify(s)}`);
    // the pill goes to the end
    await ev(`(() => { document.querySelector('#chat-new').click(); return 1; })()`);
    check(await ready(ev, `${A}.gap <= 3 && !${A}.pill`, 20), `#4393 agent: the pill goes to the end ${JSON.stringify(await ev(A))}`);
    // at the end, a reply: the end as before
    await ev(send('#chat-msgs', '#chat-in', 'chat-send', 'Reply at the end', true));
    check(await ready(ev, sent('#chat-msgs', 'Reply at the end') + ` && ${A}.gap <= 3`, 40), `#4393 agent: a reply at the end stays at the end ${JSON.stringify(await ev(A))}`);
    // scrolled up without a reply: the end as before
    await ev(scrollTo('#chat-msgs', 120));
    await ev(send('#chat-msgs', '#chat-in', 'chat-send', 'Plain message', false));
    check(await ready(ev, sent('#chat-msgs', 'Plain message') + ` && ${A}.gap <= 3`, 40), `#4393 agent: without a reply the chat goes to the end ${JSON.stringify(await ev(A))}`);

    // ================= the team chat (alice, the direct conversation with bob)
    await signIn(ev, nav, 'alice');
    await nav(B + '#team/' + RID);
    check(await ready(ev, `document.querySelectorAll('#tc-msgs .cmsg').length >= 20`, 60), 'team: the room');
    const T = ST('#tc-msgs', '#tc-new');
    await ready(ev, `${T}.gap <= 3`, 20);
    // the first second of a room keeps it at the end (teamFit); a wheel ends that phase like a person reading
    await ev(`(() => { document.querySelector('#tc-msgs').dispatchEvent(new WheelEvent('wheel', {bubbles: true})); return 1; })()`);
    const r0 = await ev(scrollTo('#tc-msgs', 120));
    await ev(send('#tc-msgs', '#tc-in', 'tc-send', 'Room reply while reading up', true));
    check(await ready(ev, sent('#tc-msgs', 'Room reply while reading up'), 40), 'team: the reply is sent');
    s = await ev(T);
    check(Math.abs(s.top - r0) <= 2 && s.gap > 50 && s.pill && /Sent/.test(s.toast), `#4393 team: reply scrolled up: the view stays (${r0}), "Sent", "New message ↓" ${JSON.stringify(s)}`);
    await shot('p2521b-team-reply.png');
    await ev(`(() => { document.querySelector('#tc-new').click(); return 1; })()`);
    check(await ready(ev, `${T}.gap <= 3 && !${T}.pill`, 20), '#4393 team: the pill goes to the end');
    await ev(scrollTo('#tc-msgs', 120));
    await ev(send('#tc-msgs', '#tc-in', 'tc-send', 'Plain room message', false));
    check(await ready(ev, sent('#tc-msgs', 'Plain room message') + ` && ${T}.gap <= 3`, 40), `#4393 team: without a reply the room goes to the end ${JSON.stringify(await ev(T))}`);

    // ================= the thread of the first message
    await ev(`(() => { tth_open(${RID}, ${ROOT}); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#tth-msgs .cmsg').length >= 15`, 60), 'thread: open');
    const TH = ST('#tth-msgs', '#tth-new');
    await ready(ev, `${TH}.gap <= 3`, 20);
    const h0 = await ev(scrollTo('#tth-msgs', 120));
    await ev(send('#tth-msgs', '#tth-in', 'tth-send', 'Thread reply while reading up', true));
    check(await ready(ev, sent('#tth-msgs', 'Thread reply while reading up'), 40), 'thread: the reply is sent');
    s = await ev(TH);
    check(Math.abs(s.top - h0) <= 2 && s.gap > 50 && s.pill && /Sent/.test(s.toast), `#4393 thread: reply scrolled up: the view stays (${h0}), "Sent", "New message ↓" ${JSON.stringify(s)}`);
    await shot('p2521b-thread-reply.png');
    await ev(`(() => { document.querySelector('#tth-new').click(); return 1; })()`);
    check(await ready(ev, `${TH}.gap <= 3 && !${TH}.pill`, 20), '#4393 thread: the pill goes to the end');
    await ev(scrollTo('#tth-msgs', 120));
    await ev(send('#tth-msgs', '#tth-in', 'tth-send', 'Plain thread message', false));
    check(await ready(ev, sent('#tth-msgs', 'Plain thread message') + ` && ${TH}.gap <= 3`, 40), `#4393 thread: without a reply the thread goes to the end ${JSON.stringify(await ev(TH))}`);
  }, false);

  console.log(`p2521_b_chatreply_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
