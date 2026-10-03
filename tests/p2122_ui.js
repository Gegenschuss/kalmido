// 2.12.2 (#451) UI tests, own container (start.sh, isolated test database). The agent chat while the person types: the agent
// fetches the message (Delivered), sends its typing signal, changes its state and answers -- the input box stays the same
// node with its focus and its text, the list is only patched (old rows keep their nodes), nothing jumps to the top. The
// chat API pages (?limit= / ?before= / has_more), the app shows the newest 30 with "Load older messages" on top.
// jsdom: desktop panel and the phone view agents/<id> (the full re-render path load() + render()). Then Firefox headless
// (ff.js) at 390 x 844 touch and 1280 x 800 mouse: at the bottom it stays pinned to the bottom (also when the typing dots
// appear), scrolled up it keeps its place and shows "New message ↓", "Load older messages" keeps the message in view,
// the focus and the viewport meta never change; with a keyboard-sized viewport (#453 N4) the tab bar goes and the newest
// message stays right above the box. #453 B2/B3 in jsdom: Kanban "+ Task", search and the overview's description editor
// keep focus, text (drafts) through the 4 s live update. Screenshots with P2122_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2122_ui', check, shots: 'P2122_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:8[2-9]|9[0-9])'/.test(SW), 'service worker cache v82');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  // 45 messages: 23 of mine, 22 answers
  for (let i = 1; i <= 45; i++) {
    if (i % 2) await call('POST', `/api/agents/${AG}/chat`, {body: `Question ${i}`});
    else await tcall('POST', `/agent/chats/${ME}`, TOK, {body: `Answer ${i}\n\nwith a second paragraph so the list is tall enough to scroll`});
  }
  const say = async body => tcall('POST', `/agent/chats/${ME}`, TOK, {body});

  // ================= the API pages
  const p1 = await call('GET', `/api/agents/${AG}/chat?limit=30`);
  check(p1.status === 200 && p1.messages.length === 30 && p1.has_more === true && p1.messages[29].body.startsWith('Question 45'), 'GET ?limit=30: the newest 30, has_more');
  const p2 = await call('GET', `/api/agents/${AG}/chat?before=${p1.messages[0].id}&limit=30`);
  check(p2.messages.length === 15 && p2.has_more === false && p2.messages[14].id < p1.messages[0].id && p2.messages[0].body === 'Question 1', 'GET ?before=: the older 15, no more');
  const p3 = await call('GET', `/api/agents/${AG}/chat?after=${p1.messages[27].id}`);
  check(p3.messages.length === 2, '?after= still returns only newer messages');
  check((await call('GET', `/api/agents/${AG}/chat?limit=0`)).status === 400 && (await call('GET', `/api/agents/${AG}/chat?before=x`)).status === 400, 'bad limit / before = 400');
  check((await call('GET', `/api/agents/${AG}/chat`)).messages.length === 45, 'without paging: all (up to 300) as before');

  // ================= jsdom, desktop panel and phone view
  for (const mobile of [false, true]) {
    const tag = mobile ? 'phone' : 'desktop';
    const w = await boot({user: 'alice', mobile, hash: mobile ? 'agents/' + AG : 'l/' + P}), d = w.document;
    if (!mobile) w.eval(`chatOpen(${AG})`);
    await until(() => d.querySelectorAll('#chat-msgs .cmsg').length >= 30);
    check(d.querySelectorAll('#chat-msgs .cmsg').length === 30, `${tag}: the newest 30 messages (${d.querySelectorAll('#chat-msgs .cmsg').length})`);
    const older = d.querySelector('#chat-msgs [data-act="chat-older"]');
    check(older && /Load older messages/.test(older.textContent), `${tag}: "Load older messages" on top`);
    const n46 = d.querySelector('#chat-msgs .cmsg:last-of-type'), total = (await call('GET', `/api/agents/${AG}/chat`)).messages.length;
    click(w, older); await until(() => d.querySelectorAll('#chat-msgs .cmsg').length === total);
    check(d.querySelectorAll("#chat-msgs .cmsg").length === total && !d.querySelector('#chat-msgs [data-act="chat-older"]'), `${tag}: older page loaded, the button is gone (${d.querySelectorAll("#chat-msgs .cmsg").length}, ${!!d.querySelector('#chat-msgs [data-act="chat-older"]')})`);
    check(n46.isConnected, `${tag}: loading older messages keeps the existing rows`);
    // type a draft with the focus in the box
    const ta = d.querySelector('#chat-in'), box = d.querySelector('#chat-msgs'), row = d.querySelector('#chat-msgs .cmsg.ag');
    ta.focus(); ta.value = 'draft while it writes';
    ta.dispatchEvent(new w.Event('input', {bubbles: true}));
    const same = what => {
      const t2 = d.querySelector('#chat-in');
      check(t2 === ta && d.activeElement === ta && ta.value === 'draft while it writes', `${tag} ${what}: the same box, focused, with its text`);
      check(d.querySelector('#chat-msgs') === box && row.isConnected, `${tag} ${what}: the same list, old rows kept`);
    };
    // a message from me (from another device) that the agent fetches -> Delivered
    const mine = await call('POST', `/api/agents/${AG}/chat`, {body: 'From the phone ' + tag});
    await w.eval('load().then(render).then(chatLoad)'); await sleep(300);  // 2.13.0: wait for the chat refresh load() starts (slow runners)
    same('my new message');
    const mrow = d.querySelector(`#chat-msgs .cmsg[data-mid="${mine.id}"]`);
    check(mrow && /Sent/.test(mrow.textContent), `${tag}: my message, Sent`);
    await tcall('GET', `/agent/chats?since=${mine.id - 1}`, TOK);
    await w.eval('chatLoad()'); await w.eval('load().then(render).then(chatLoad)'); await sleep(300);  // 2.13.0: wait for the chat refresh load() starts (slow runners)
    same('delivered');
    check(/Delivered/.test(d.querySelector(`#chat-msgs .cmsg[data-mid="${mine.id}"]`)?.textContent || ''), `${tag}: Delivered in place`);
    // the agent types and works
    await tcall('POST', '/agent/typing', TOK, {chat_user_id: ME});
    await tcall('PUT', '/agent/status', TOK, {status: 'working', text: 'thinking'});
    await w.eval('agentPoll()'); await w.eval('load().then(render).then(chatLoad)'); await sleep(300);  // 2.13.0: wait for the chat refresh load() starts (slow runners)
    same('typing + working');
    check(!d.querySelector('#chat-typing').classList.contains('hidden'), `${tag}: typing dots`);
    // its answer
    const ans = await say('Here you go ' + tag);
    await w.eval('load().then(render).then(chatLoad)'); await sleep(300);  // 2.13.0: wait for the chat refresh load() starts (slow runners)
    same('new answer');
    check(d.querySelector(`#chat-msgs .cmsg[data-mid="${ans.id}"]`) && d.querySelector('#chat-msgs').lastElementChild.dataset.mid === String(ans.id), `${tag}: the answer is appended ` + (d.querySelector('#chat-msgs')?.lastElementChild?.outerHTML || '-').replace(/<svg.*?<\/svg>/g, '').slice(0, 300));
    // a status change (agent band / header dots)
    await tcall('PUT', '/agent/status', TOK, {status: 'idle'});
    await w.eval('agentPoll()'); w.eval('renderTop(); render()'); await sleep(300);
    same('status change');
    w.eval('staleDraw()'); same('offline hint');
    check(!errs.length, `${tag}: no JS errors ${errs.join(' | ')}`);
    w.close();
  }

  // ================= #453 B2 / B3: fields in the main view keep focus + text through live updates (the 4 s poll)
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  const CKB = await login('bob');
  const K = (await call('POST', '/api/lists', {name: 'Board', kind: 'project'})).id;
  await call('PUT', `/api/lists/${K}/members`, {user_id: BOB, role: 'edit'});
  await call('PATCH', `/api/lists/${K}`, {view: 'kanban'});
  await call('POST', '/api/sections', {list_id: K, name: 'Backlog'});
  let bn = 0;
  const bobAdds = lid => call('POST', '/api/tasks', {title: 'From Bob ' + (++bn), list_id: lid}, CKB);
  const typeIn = (w, el, v) => { el.focus(); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
  for (const mobile of [false, true]) {
    const tag = mobile ? 'phone' : 'desktop';
    // Kanban "+ Task"
    let w = await boot({user: 'alice', mobile, hash: 'l/' + K}), d = w.document;
    await until(() => d.querySelector('#view [data-kadd]'));
    const ka = d.querySelector('#view [data-kadd]');
    typeIn(w, ka, 'Hallo Welt');
    const v0 = w.eval('S.v'); await bobAdds(K);
    await until(() => w.eval('S.viewStale') || w.eval('S.v') !== v0, 60); await sleep(4500);
    check(d.contains(ka) && d.activeElement === ka && ka.value === 'Hallo Welt', `${tag}: Kanban "+ Task" keeps node, focus and text through a live update`);
    ka.value = ''; ka.blur(); await until(() => /From Bob/.test(d.querySelector('#view').textContent), 60);
    check(/From Bob/.test(d.querySelector('#view').textContent), `${tag}: after leaving the field the update arrives`);
    // a forced re-render still brings the field back focused with its text
    const ka2 = d.querySelector('#view [data-kadd]'); typeIn(w, ka2, 'abc'); w.eval('renderView()');
    const ka3 = d.querySelector('#view [data-kadd]');
    check(d.activeElement === ka3 && ka3.value === 'abc', `${tag}: renderView() restores the focused Kanban field (${d.activeElement && d.activeElement.tagName})`);
    ka3.value = ''; ka3.blur(); w.close();
    // search
    w = await boot({user: 'alice', mobile, hash: 'search'}); d = w.document;
    await until(() => d.querySelector('#searchq'));
    const sq = d.querySelector('#searchq'); typeIn(w, sq, 'Wire');
    await sleep(400); await bobAdds(P); await sleep(5500);
    const sq2 = d.querySelector('#searchq');
    check(sq2 && d.activeElement === sq2 && sq2.value === 'Wire', `${tag}: search keeps focus and text through a live update`);
    w.close();
    // B3: the project overview's description editor keeps its draft
    w = await boot({user: 'alice', mobile, hash: 'l/' + P}); d = w.document;
    w.eval(`setListView(routeList(), 'overview')`); await until(() => d.querySelector('#view [data-pov="desc-edit"]'));
    click(w, d.querySelector('#view [data-pov="desc-edit"]')); await until(() => d.querySelector('#pov-desc-in'));
    typeIn(w, d.querySelector('#pov-desc-in'), 'Goal: a draft ' + tag);
    await bobAdds(P); await sleep(5500);
    check(d.querySelector('#pov-desc-in')?.value === 'Goal: a draft ' + tag && d.activeElement === d.querySelector('#pov-desc-in'), `${tag}: overview description: draft and focus survive a live update`);
    d.querySelector('#pov-desc-in').blur(); w.eval('renderView()');
    check(d.querySelector('#pov-desc-in')?.value === 'Goal: a draft ' + tag, `${tag}: overview description: the draft survives a re-render without focus`);
    click(w, d.querySelector('#view [data-pov="desc-cancel"]')); await sleep(200);
    check(!d.querySelector('#pov-desc-in') && !w.eval(`S.drafts['pov:${P}']`), `${tag}: Cancel drops the draft`);
    // Save stores what was typed (before 2.12.2 the section and the box shared the id pov-desc, Save sent the section's "value")
    click(w, d.querySelector('#view [data-pov="desc-edit"]')); await until(() => d.querySelector('#pov-desc-in'));
    typeIn(w, d.querySelector('#pov-desc-in'), 'Saved ' + tag); click(w, d.querySelector('#view [data-pov="desc-save"]'));
    check(await until(async () => (await call('GET', `/api/lists/${P}/overview`)).description === 'Saved ' + tag), `${tag}: Save stores the typed description`);
    check(await until(() => !d.querySelector('#pov-desc-in') && /Saved/.test(d.querySelector('#pov-desc').textContent)), `${tag}: the saved description is shown`);
    w.eval(`setListView(routeList(), 'list')`); await sleep(200);
    check(!errs.length, `${tag} B2/B3: no JS errors ${errs.join(' | ')}`);
    w.close();
  }

  // ================= Firefox: 390 touch, 1280 mouse
  for (const [touch, vw, vh] of [[true, 390, 844], [false, 1280, 800]]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      check(lgi === 200, `${vw}px: Firefox login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + '?v=' + vw + '#' + (touch ? 'agents/' + AG : 'l/' + P));
      for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
      await sleep(900);
      if (!touch) await ev(`(() => { chatOpen(${AG}); return 1; })()`);
      for (let i = 0; i < 30 && (await ev(`document.querySelectorAll('#chat-msgs .cmsg').length`)) < 30; i++) await sleep(200);
      await sleep(400);
      const ST = `(() => { const b = document.querySelector('#chat-msgs'), t = document.querySelector('#chat-in'); return {gap: Math.round(b.scrollHeight - b.scrollTop - b.clientHeight), top: Math.round(b.scrollTop), sh: b.scrollHeight, focus: document.activeElement === t, sameTa: t === window.__ta, sameBox: b === window.__box, val: t.value, pill: !document.querySelector('#chat-new').classList.contains('hidden'), meta: document.querySelector('meta[name="viewport"]').getAttribute('content'), n: document.querySelectorAll('#chat-msgs .cmsg').length}; })()`;
      const poll = () => ev(`load().then(() => { render(); return 1; })`).then(() => sleep(500));
      let s = await ev(`(() => { const t = document.querySelector('#chat-in'); window.__ta = t; window.__box = document.querySelector('#chat-msgs'); t.focus(); t.value = 'typing on'; return 1; })()`);
      s = await ev(ST);
      const meta0 = s.meta;
      check(s.n === 30 && s.gap <= 2 && s.sh > s.top + 10, `${vw}px: opens at the newest message ${JSON.stringify(s)}`);
      // at the bottom: typing dots + an answer keep it at the bottom, the focus stays
      await tcall('POST', '/agent/typing', TOK, {chat_user_id: ME}); await tcall('PUT', '/agent/status', TOK, {status: 'working'});
      await ev(`agentPoll().then(() => 1)`); await poll();
      s = await ev(ST);
      check(s.gap <= 2 && s.focus && s.sameTa && s.sameBox && s.val === 'typing on' && s.meta === meta0, `${vw}px: typing dots: pinned to the bottom, box kept ${JSON.stringify(s)}`);
      await say(`Answer at ${vw}`); await poll();
      s = await ev(ST);
      check(s.gap <= 2 && s.top > 0 && s.focus && s.sameTa && s.sameBox && s.val === 'typing on' && !s.pill && s.meta === meta0, `${vw}px: new answer at the bottom: still pinned, focus + text kept ${JSON.stringify(s)}`);
      await shot(`p2122-bottom-${vw}.png`);
      if (touch) {  // #453 N4: the keyboard (a viewport of 55 %): all the room for the messages, the newest right above the box
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: Math.round(vh * 0.55)}}); await sleep(700);
        const kb = await ev(`(() => { const b = document.querySelector('#chat-msgs'), c = document.querySelector('.chcomp').getBoundingClientRect(), last = [...b.querySelectorAll('.cmsg')].pop().getBoundingClientRect(), bb = b.getBoundingClientRect(); return {kb: document.body.classList.contains('kb-open'), tabs: !!document.querySelector('#tabs')?.offsetHeight, h: Math.round(b.clientHeight), gap: Math.round(b.scrollHeight - b.scrollTop - b.clientHeight), lastIn: last.bottom <= bb.bottom + 1 && last.bottom > bb.top, compIn: c.bottom <= innerHeight + 1, focus: document.activeElement === window.__ta}; })()`);
        check(kb.kb && !kb.tabs && kb.h >= 230 && kb.gap <= 2 && kb.lastIn && kb.compIn && kb.focus, `${vw}px keyboard: tab bar gone, ${kb.h} px for messages, newest visible above the box ${JSON.stringify(kb)}`);
        await shot(`p2122-keyboard-${vw}.png`);
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}}); await sleep(700);
        const back = await ev(`(() => { const b = document.querySelector('#chat-msgs'); return {kb: document.body.classList.contains('kb-open'), gap: Math.round(b.scrollHeight - b.scrollTop - b.clientHeight)}; })()`);
        check(!back.kb && back.gap <= 2, `${vw}px keyboard closed: back to normal, still at the bottom ${JSON.stringify(back)}`);
      }
      // scrolled up: the place is kept, the pill shows; a status change does not move anything either
      await ev(`(() => { document.querySelector('#chat-msgs').scrollTop = 120; return 1; })()`); await sleep(300);
      const top0 = (await ev(ST)).top;
      await say(`Second answer at ${vw}`); await poll();
      await tcall('PUT', '/agent/status', TOK, {status: 'idle'}); await ev(`agentPoll().then(() => { renderTop(); return 1; })`); await sleep(400);
      s = await ev(ST);
      check(Math.abs(s.top - top0) <= 1 && s.gap > 40 && s.pill && s.focus && s.sameTa && s.val === 'typing on' && s.meta === meta0, `${vw}px: scrolled up: position kept (${top0}), "New message ↓" shows ${JSON.stringify(s)}`);
      await shot(`p2122-pill-${vw}.png`);
      const pr = await ev(`(() => { const p = document.querySelector('#chat-new'), r = p.getBoundingClientRect(), b = document.querySelector('#chat-msgs').getBoundingClientRect(); return {in: r.top >= b.top && r.bottom <= b.bottom + 1 && r.left >= b.left && r.right <= b.right, h: r.height, t: p.textContent}; })()`);
      check(pr.in && pr.h >= 43.5 && /New message/.test(pr.t), `${vw}px: the pill sits over the list, >= 44 px ${JSON.stringify(pr)}`);
      await ev(`(() => { document.querySelector('#chat-new').click(); return 1; })()`); await sleep(300);
      s = await ev(ST);
      check(s.gap <= 2 && !s.pill, `${vw}px: the pill jumps to the newest message and goes ${JSON.stringify(s)}`);
      // "Load older messages": the message on top stays where it was
      await ev(`(() => { document.querySelector('#chat-msgs').scrollTop = 0; return 1; })()`); await sleep(300);
      const r0 = await ev(`(() => { const m = document.querySelector('#chat-msgs .cmsg'); window.__m = m; return Math.round(m.getBoundingClientRect().top); })()`);
      await ev(`(() => { document.querySelector('#chat-msgs [data-act="chat-older"]').click(); return 1; })()`); await sleep(1000);
      const r1 = await ev(`(() => ({top: window.__m.isConnected ? Math.round(window.__m.getBoundingClientRect().top) : null, n: document.querySelectorAll('#chat-msgs .cmsg').length}))()`);
      check(r1.n > 30 && r1.top !== null && Math.abs(r1.top - r0) <= 2, `${vw}px: older messages load above, the message stays in view (${r0} -> ${JSON.stringify(r1)})`);
      s = await ev(ST);
      check(s.focus && s.sameTa && s.val === 'typing on' && s.meta === meta0, `${vw}px: after everything the box still has the focus ${JSON.stringify(s)}`);
      await ev(`(() => { chatClose && chatClose(); return 1; })()`);
    }, touch);
  }

  console.log(`p2122_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
