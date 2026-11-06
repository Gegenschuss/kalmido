// 2.542.0 UI test, part B (#4614): a swipe to the right on a message of the agent chat starts the reply again. Own container
// kalmido-suite: fresh
// (start.sh), Firefox 390 px touch, as a person without an organisation (frida chats with her own agent).
// - a long answer of the agent (heading, list, bold, a suggestion button): a swipe on its list opens the reply bar with the
//   agent's name; the message springs back, the arrow goes
// - a swipe on my own message: "Reply to your own message"
// - a live redraw of the chat while the finger is on the message (the touched row changed: chatDraw / chatPatch, or the poll
//   redraws the view: viewSafeRender) no longer swaps the touched node: on phones (WebKit / Chrome) the swipe died with it, no
//   touchend reaches the document (Firefox keeps sending them, so the test checks the node itself); the held-back redraw comes
//   after the swipe. The same for a comment in the task panel (drawTimeline)
// - a code block in a long answer (it wraps in a chat bubble) is swipeable too; a table that really scrolls sideways is not
// - an up / down move does not reply; the menu entry "Reply" stays
// - team chat: the same swipe with a redraw of the room while the finger is on it (2.151.1 guard, still green)
// freelancer-matrix: agents (frida has no organisation and chats with her agent)
// P2542B_NOSTART=1 = the server already runs. Screenshots: P2542B_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2542_b_swipe_ui', check, shots: 'P2542B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2542B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'comments,collab,agents,team';
const LONGMD = '## Plan for the release\n\nHere is what I would do next:\n\n- **First** the colours of the chat head and the send button\n- then the swipe to reply on phones\n- and last the side bar: it opens again in every area\n\n```\nkalmido-mactest.sh run p2542_b_swipe_ui\nkalmido-mactest.sh run p2542_b_color_ui\n```\n\n### Open points\n\n1. the tests on the Mac\n2. a screenshot of each\n\n| Area | Column two | Column three | Column four | Column five | Column six |\n| --- | --- | --- | --- | --- | --- |\n| a-very-long-cell-without-any-break-at-all | another-very-long-cell-without-a-break | x | y | z | w |\n\nShall I start?';

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
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  const ag = await call(CF, 'POST', '/api/my/agents', {username: 'helper', display_name: 'Helper', scopes: ['read', 'write']});
  check(ag.http < 300 && ag.id && ag.token, 'frida\'s agent ' + ag.http);
  const AG = ag.id, TOK = ag.token, ME = (await call(CF, 'GET', '/api/state')).me.id;
  const say = (body, extra = {}) => tcall('POST', `/agent/chats/${ME}`, TOK, {body, ...extra});
  const P = (await call(CF, 'POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call(CF, 'PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  const Q = (await call(CF, 'POST', `/api/agents/${AG}/chat`, {body: 'What comes next?'})).id;
  const LA = await say(LONGMD, {choices: [{id: 'go', label: 'Start the release', style: 'primary'}]});
  check(LA.status < 300 && LA.id, 'the long answer with a suggestion ' + LA.status);
  const MINE = (await call(CF, 'POST', `/api/agents/${AG}/chat`, {body: 'One more question about the colours, please.'})).id;
  const T = (await call(CF, 'POST', '/api/tasks', {title: 'Store screenshots', list_id: P})).id;
  const CM = (await call(CF, 'POST', `/api/tasks/${T}/comments`, {body: 'The screenshots for the store are ready, please have a look at them.'})).id;
  check(T > 0 && CM > 0, 'a task with a comment ' + T + ' ' + CM);
  check(Q > 0 && MINE > 0, 'my messages');
  // alice and bob: the room of a shared project
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Studio', kind: 'project'})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const RID = (((await call(CA, 'GET', '/api/team')).rooms || []).find(x => x.kind === 'list' && x.list_id === L) || {}).id;
  check(RID > 0, 'the room of the shared project');
  const TM = (await call(CB, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Can you also check the screenshots for the store?'})).id;

  const signIn = async (ev, nav, u) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`) === 200, `${u} signs in`);
  };
  // the place to put the finger: a list item of the message (agent) or its bubble, in the middle of the screen
  // job/2919: x stays 140 px from the right edge (the 130 px move must end inside the 390 px screen); a retry waits until the
  // message of the last try is back in place - measured while it still sat moved, the finger started past the edge (load on the runner)
  const spot = (box, mid, sel) => `(() => { const m = document.querySelector('${box} [data-mid="${mid}"]'); if (!m) return null; m.scrollIntoView({block: 'center'});
    const e = m.querySelector('${sel}') || m.querySelector('.cbub') || m, r = e.getBoundingClientRect(); return {x: Math.round(Math.min(Math.max(r.left + 24, 60), innerWidth - 140)), y: Math.round(r.top + Math.min(r.height / 2, 14)), tag: e.tagName}; })()`;
  // what the swipe left behind: the reply bar, the message back in place, no arrow
  const bar = (box, mid) => `(() => { const b = [...document.querySelectorAll('.rbar:not(.hidden)')].find(x => x.offsetParent); const m = document.querySelector('${box} [data-mid="${mid}"]');
    return {bar: b ? b.textContent.trim() : '', back: !!m && !m.style.transform && !m.classList.contains('rsw'), arrow: !!document.querySelector('${box} .rswarr')}; })()`;
  // a live redraw on the first move of the finger (as an answer arriving or a whole-view redraw while the finger is down)
  // __kept: the touched message's node is still in the page right after the redraw (the finger still down)
  const onMove = (js, sel) => `(() => { window.__redraws = 0; window.__kept = null; const f = e => { document.removeEventListener('touchmove', f, true); const n = e.target.closest?.('${sel}');
    setTimeout(() => { try { ${js}; window.__redraws++; window.__kept = !!n && n.isConnected; } catch (e) { window.__redrawErr = String(e); } }, 0); };
    document.addEventListener('touchmove', f, true); return 1; })()`;
  const cancel = () => `(() => { document.querySelector('.rbar:not(.hidden) [data-act="reply-x"]')?.click(); return 1; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot, drag, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await signIn(ev, nav, 'frida');
    await nav(B + '#today'); await until(`!!document.querySelector('#top h1')`, {timeout: 20000});
    await ev(`(() => { chatOpen(${AG}); return 1; })()`);
    check(await until(`!!document.querySelector('#chat-msgs [data-mid="a:${LA.id}"] .cbub li') && !!document.querySelector('#chat-msgs [data-mid="a:${LA.id}"] .cchoices')`, {timeout: 20000}), 'the long answer with its list and suggestion is there');
    const A = '#chat-msgs';
    const swipe = async (mid, sel, what) => {
      let p = await ev(spot(A, mid, sel)), s = {};
      // a slow runner may still scroll the first move: one more try (as p2330_a)
      for (let i = 0; i < 2 && p; i++) { await drag(p.x, p.y, 130, 6, 'touch'); s = await until(`${bar(A, mid)}.bar && ${bar(A, mid)}.back ? ${bar(A, mid)} : null`, {timeout: 3000}) || await ev(bar(A, mid)); if (s.bar) break; await until(`${bar(A, mid)}.back`, {timeout: 3000}); p = await ev(spot(A, mid, sel)); }
      check(!!p, what + ': the message is on the screen');
      return s;
    };
    // the long answer: a swipe on its list
    let s = await swipe(`a:${LA.id}`, '.cbub li', 'agent');
    check(/Reply to Helper/.test(s.bar) && s.back && !s.arrow, '#4614: a swipe on the list of a long agent answer opens the reply bar ' + JSON.stringify(s));
    await shot('p2542b-agent-swipe.png');
    await ev(cancel());
    // my own message
    s = await swipe(`a:${MINE}`, '.cbub', 'mine');
    check(/Reply to your own message/.test(s.bar) && s.back, '#4614: a swipe on my own message replies to it ' + JSON.stringify(s));
    await ev(cancel());
    // the code block of the long answer (it wraps, nothing scrolls sideways): swipeable
    s = await swipe(`a:${LA.id}`, '.cbub pre', 'agent code');
    check(/Reply to Helper/.test(s.bar), '#4614: a swipe on the code block of the answer replies ' + JSON.stringify(s));
    await ev(cancel());
    // the wide table scrolls sideways: no reply there (its own scrolling)
    const tw = await ev(`(() => { const t = document.querySelector('${A} [data-mid="a:${LA.id}"] .mdtbl'); return t ? t.scrollWidth > t.clientWidth + 1 : null; })()`);
    if (tw) {
      const tp0 = await ev(spot(A, `a:${LA.id}`, '.mdtbl td'));
      if (tp0) { await drag(tp0.x, tp0.y, 130, 6, 'touch'); await sleep(400); }
      check(!(await ev(bar(A, `a:${LA.id}`))).bar, '#4614: a table that scrolls sideways keeps its own swipe');
      await ev(cancel());
    } else check(tw === false, 'the wide table is there ' + tw);
    // the touched message changes while the finger is on it (an edit, a job's steps, a tick) and the chat is drawn
    const M = `#chat-msgs .cmsg[data-mid="a:${LA.id}"]`;
    await ev(onMove(`const m = S.chat.msgs.find(x => x.id === ${LA.id}); m.body = m.body + ' (updated)'; m.edited_at = new Date().toISOString(); window.__rows = 0; const pr = window.patchRows; window.patchRows = function () { window.__rows++; return pr.apply(this, arguments); }; chatDraw(); window.__rows0 = window.__rows`, M));
    s = await swipe(`a:${LA.id}`, '.cbub li', 'agent + patch');
    const k1 = await ev('({kept: window.__kept, n: window.__redraws, err: window.__redrawErr || ""})');
    check(/Reply to Helper/.test(s.bar) && s.back, '#4614: a chat refresh while swiping: the reply bar opens ' + JSON.stringify(s));
    check(k1.kept === true, '#4614: a chat refresh while swiping keeps the touched message (held back) ' + JSON.stringify(k1));
    // (a later chatLoad brings the server's text back, so the patch itself is counted: none during the swipe, one after it)
    check(await until(`window.__rows0 === 0 && window.__rows >= 1`, {timeout: 5000}), '#4614: the held-back chat refresh comes after the swipe ' + JSON.stringify(await ev('({rows0: window.__rows0, rows: window.__rows})')));
    await ev(cancel());
    // the poll redraws the view while the finger is down (td_renderSoon / viewSafeRender wait for the finger: lpHold)
    await ev(onMove(`viewSafeRender()`, M));
    s = await swipe(`a:${LA.id}`, '.cbub li', 'agent + view');
    const k2 = await ev('({kept: window.__kept, n: window.__redraws, stale: S.viewStale, err: window.__redrawErr || ""})');
    check(/Reply to Helper/.test(s.bar) && s.back && k2.kept === true, '#4614: a view redraw while swiping waits for the end of the swipe ' + JSON.stringify(s) + JSON.stringify(k2));
    // the reply box has the focus now (typing holds a view redraw as before): once it is left, the poll draws the held view
    await ev(`(() => { document.activeElement?.blur?.(); return 1; })()`);
    check(await until(`!S.viewStale`, {timeout: 15000}), '#4614: the held-back view redraw comes after the swipe');
    await ev(cancel());
    // an up / down move does not reply
    const p = await ev(spot(A, `a:${LA.id}`, '.cbub li'));
    if (p) { await drag(p.x, p.y, 4, p.y > 400 ? -160 : 160, 'touch'); await sleep(300); }
    check(!(await ev(bar(A, `a:${LA.id}`))).bar, '#4614: an up / down move does not reply');
    // the menu's "Reply" stays
    await ev(`(() => { document.querySelector('${A} [data-mid="a:${LA.id}"] [data-act="chat-msg-menu"]').click(); return 1; })()`);
    check(await until(`!!document.querySelector('#pop:not(.hidden) [data-act="msg-reply"], #pop:not(.hidden) [data-act="chat-reply"], .tsheet [data-act="msg-reply"]') || [...document.querySelectorAll('#pop:not(.hidden) button, .tsheet button')].some(b => /^Reply$/.test(b.textContent.trim()))`, {timeout: 5000}), '#4614: the message menu still has "Reply"');

    // ================= team chat (alice): a redraw of the room while swiping (2.151.1)
    await signIn(ev, nav, 'alice');
    await nav(B + '#team/' + RID);
    check(await until(`!!document.querySelector('#tc-msgs [data-mid="t:${TM}"]')`, {timeout: 20000}), 'team: the room');
    await ev(onMove(`teamChanged()`, '#tc-msgs .cmsg[data-mid="t:${TM}"]'));
    let tp = await ev(spot('#tc-msgs', `t:${TM}`, '.cbub')), ts = {};
    for (let i = 0; i < 2 && tp; i++) { await drag(tp.x, tp.y, 130, 6, 'touch'); ts = await until(`${bar('#tc-msgs', `t:${TM}`)}.bar ? ${bar('#tc-msgs', `t:${TM}`)} : null`, {timeout: 3000}) || {}; if (ts.bar) break; await until(`${bar('#tc-msgs', `t:${TM}`)}.back`, {timeout: 3000}); tp = await ev(spot('#tc-msgs', `t:${TM}`, '.cbub')); }
    check(/Reply to Bob Baker/.test(ts.bar || ''), 'team: a swipe while the room is refreshed opens the reply bar ' + JSON.stringify(ts));
    await ev(cancel());

    // ================= comments in the task panel (frida): drawTimeline while swiping
    await signIn(ev, nav, 'frida');
    await nav(B + '#t/' + T); await until(`!!document.querySelector('#detail .cm[data-mid="c:${CM}"]')`, {timeout: 20000});
    const CS = `#detail .cm[data-mid="c:${CM}"]`;
    await ev(onMove(`const c = S.tl.comments.find(x => x.id === ${CM}); c.body = c.body + ' (edited)'; c.edited_at = new Date().toISOString(); drawTimeline()`, CS));
    let cp = await ev(`(() => { const m = document.querySelector('${CS}'); if (!m) return null; m.scrollIntoView({block: 'center'}); const r = (m.querySelector('.cbody') || m).getBoundingClientRect(); return {x: Math.round(Math.min(Math.max(r.left + 40, 60), innerWidth - 140)), y: Math.round(r.top + Math.min(r.height / 2, 12))}; })()`), cs = '';
    for (let i = 0; i < 2 && cp && !cs; i++) { await drag(cp.x, cp.y, 130, 4, 'touch'); cs = await until(`[...document.querySelectorAll('.rbar:not(.hidden)')].find(x => x.offsetParent)?.textContent.trim() || ''`, {timeout: 3000}); }
    const k3 = await ev('({kept: window.__kept, n: window.__redraws, err: window.__redrawErr || ""})');
    check(/Reply to/.test(cs || '') && k3.kept === true, '#4614 comments: a timeline refresh while swiping keeps the comment, the reply bar opens ' + JSON.stringify({cs, k3}));
    check(await until(`/\(edited\)/.test(document.querySelector('${CS}')?.textContent || '')`, {timeout: 5000}), '#4614 comments: the held-back refresh comes after the swipe');
  }, true);

  console.log(`p2542_b_swipe_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
