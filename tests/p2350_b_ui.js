// 2.35.0 UI tests (agent B), own container (start.sh). jsdom:
// #1103 approval requests: a card with the accent edge and the heading "Approval needed" (title, "If yes: …", buttons yes /
//      no; the body is not repeated when it is the title), a permission question gets the heading too; the open ones are
//      pinned at the top of the chat (also one older than the loaded page) with their buttons; the sidebar row of the agent
//      and the agent card count them; a press in the pin answers (the agent gets chat_choice approved), a press on the
//      card answers too and it then says "Rejected by Alice at HH:MM"; afterwards nothing is pinned or counted
// Firefox 1280 x 800 (mouse): #1102 a wheel at the end of the chat's messages moves neither the view nor the page (agent
//      chat as side panel, the team chat), the message lists have overscroll-behavior contain; 950 x 800: the agent chat as
//      a page (#view does not scroll); #1099 the live steps start where "… is writing …" starts (within 2 px)
// Firefox 402 x 874 touch (German, the iPhone of the device test): #1107 no two tap areas of the chat header overlap
//      (boxes incl. their ::after extension), each >= 24 px; the ring's box stays >= 44 px; #1099 the steps are indented
//      less than on the desktop but right of the dots; screenshots
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2350_b_ui', check, shots: 'P2350B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';

// the tap area of an element: its box, grown by an absolutely placed ::after (inset)
const TAP_JS = `const tapBox = e => { const r = e.getBoundingClientRect(), a = getComputedStyle(e, '::after'); let b = {l: r.left, t: r.top, r: r.right, b: r.bottom};
  if (a.content !== 'none' && a.position === 'absolute') { const px = v => parseFloat(v) || 0; b = {l: Math.min(b.l, r.left + px(a.left)), t: Math.min(b.t, r.top + px(a.top)), r: Math.max(b.r, r.right - px(a.right)), b: Math.max(b.b, r.bottom - px(a.bottom))}; }
  return b; };`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const ME = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Team list'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const v1 = async (method, url, body) => { const x = await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined}); return {...(await x.json().catch(() => ({}))), status: x.status}; };

  // ================= jsdom: the approval card, the pin, the counts
  const a1 = await v1('POST', `/agent/chats/${ME.id}`, {approval: {title: 'Delete the old export files', what: '42 files leave the server'}});
  check(a1.status === 201, 'approval 1 ' + JSON.stringify(a1).slice(0, 160));
  for (let i = 0; i < 31; i++) await v1('POST', `/agent/chats/${ME.id}`, {body: `Status line ${i + 1}`});
  const a2 = await v1('POST', `/agent/chats/${ME.id}`, {body: 'The release is built and tested on staging.', approval: {title: 'Publish release 2.35.0', what: 'The new version goes live for everyone', yes_label: 'Yes, publish', no_label: 'Not yet'}});
  const pq = await v1('POST', `/agent/chats/${ME.id}`, {body: 'May I run this?\n```\n./deploy.sh staging\n```', permission: true});
  check(a2.status === 201 && pq.status === 201, 'approval 2 + a permission question');
  let w = await boot({hash: 'today'}); let d = w.document;
  await until(() => d.querySelector(`.srow[data-aid="${AG}"]`));
  const sc = d.querySelector(`.srow[data-aid="${AG}"] .apvc`);
  check(sc && /3/.test(sc.textContent) && /3 approvals open/.test(sc.getAttribute('title') || ''), '#1103: the sidebar row counts the open approvals ' + (sc?.outerHTML || '').slice(0, 200));
  w.eval(`chatOpen(${AG})`);
  await until(() => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a2.id}"]`));
  await sleep(300);
  const c2 = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a2.id}"]`);
  check(c2 && c2.classList.contains('apv') && c2.classList.contains('apvopen'), '#1103: the approval request is a card of its own (apv apvopen) ' + (c2?.className || ''));
  check(c2 && c2.querySelector('.apvh')?.textContent.trim() === 'Approval needed' && c2.querySelector('.apvt')?.textContent === 'Publish release 2.35.0'
    && /If yes: The new version goes live for everyone/.test(c2.querySelector('.apvw')?.textContent || ''), '#1103: heading, title and "If yes" ' + (c2?.textContent || '').slice(0, 200));
  check(c2 && /built and tested/.test(c2.querySelector('.cbub')?.textContent || '') && [...c2.querySelectorAll('.apvbtns .cchb')].map(b => b.textContent.trim()).join('|').includes('Yes, publish|') ,
    '#1103: the body above the card, the own labels ' + [...(c2?.querySelectorAll('.apvbtns .cchb') || [])].map(b => b.textContent.trim()).join('|'));
  const cp = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${pq.id}"]`);
  check(cp && cp.classList.contains('apv') && cp.querySelector('.apvh') && cp.querySelector('.cperm'), '#1103: a permission question gets the card + heading too');
  check(!d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a1.id}"]`), '#1103: the first request is older than the loaded page');
  const pin = d.querySelector('#chat-apv');
  const pins = [...(pin?.querySelectorAll('.apvpin') || [])];
  check(pin && !pin.hidden && pins.length === 3 && /Delete the old export files/.test(pins[0].textContent) && pins[0].querySelector('[data-cid="yes"]'), '#1103: all three open ones are pinned at the top, the old one too ' + pins.map(p => p.textContent.trim().slice(0, 40)).join(' / '));
  check(pin && pin.compareDocumentPosition(d.querySelector('#chat-msgs')) & 4, '#1103: the pin sits above the messages');
  const cur = (await v1('GET', '/agent/events?since=latest')).cursor;
  pins[0].querySelector('[data-cid="yes"]').click();
  await until(() => d.querySelectorAll('#chat-apv .apvpin').length === 2);
  const evs = (await v1('GET', `/agent/events?since=${cur}`)).data || [];
  const cc = evs.filter(e => e.event === 'chat_choice').map(e => e.data);
  check(cc.length === 1 && cc[0].approval === 'approved' && cc[0].message_id === a1.id && cc[0].approval_request?.title === 'Delete the old export files', '#1103: the press in the pin reaches the agent as approved ' + JSON.stringify(cc).slice(0, 200));
  d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a2.id}"] [data-cid="no"]`).click();
  await until(() => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a2.id}"] .cpermst`));
  const st2 = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a2.id}"] .cpermst`)?.textContent || '';
  check(/Rejected by Alice at \d\d:\d\d$/.test(st2.trim()) && !d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a2.id}"] .cchb`), '#1103: afterwards the card says who and when, the buttons are gone ' + st2);
  check(!d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a2.id}"]`).classList.contains('apvopen'), '#1103: the answered card loses the accent edge');
  d.querySelector(`#chat-apv [data-mid="${pq.id}"][data-cid="allow"]`)?.click();
  await until(() => d.querySelector('#chat-apv').hidden);
  check(d.querySelector('#chat-apv').hidden && /Allowed/.test(d.querySelector(`#chat-msgs .cmsg[data-mid="a:${pq.id}"] .cpermst`)?.textContent || ''), '#1103: the permission question answered from the pin, nothing pinned any more');
  w.close();
  const ags = (await call('GET', '/api/agents')).agents.find(x => x.id === AG);
  check(ags && ags.approvals_open === 0, '#1103: nothing counted any more');
  // the agent card on the agents page
  const a3 = await v1('POST', `/agent/chats/${ME.id}`, {approval: {title: 'Send the newsletter'}});
  w = await boot({hash: 'agents'}); d = w.document;
  await until(() => d.querySelector('.apvcard'));
  check(/1 approval open/.test(d.querySelector('.apvcard')?.textContent || ''), '#1103: the agent card says "1 approval open" ' + (d.querySelector('.apvcard')?.textContent || ''));
  w.close();
  // review N1: closed by the agent (outcome denied, no answer of the person): "Closed by the agent", never "Approved"
  check((await v1('POST', `/agent/chats/${ME.id}/messages/${a3.id}/withdraw`, {outcome: 'allowed'})).status === 400, 'N1: outcome allowed on an approval request -> 400');
  check((await v1('POST', `/agent/chats/${ME.id}/messages/${a3.id}/withdraw`, {outcome: 'denied'})).status === 200, 'N1: outcome denied');
  w = await boot({hash: 'today'}); d = w.document;
  w.eval(`chatOpen(${AG})`);
  await until(() => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a3.id}"] .cpermst`));
  const st3 = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${a3.id}"] .cpermst`)?.textContent.trim() || '';
  check(st3 === 'Closed by the agent' && d.querySelector('#chat-apv').hidden, 'N1: the card closed by the agent says so, nothing pinned ' + st3);
  w.close();

  // ================= Firefox desktop: #1102 + #1099
  for (let i = 0; i < 40; i++) await v1('POST', `/agent/chats/${ME.id}`, {body: `Line ${i + 1}: ` + 'some words of a longer answer '.repeat(3)});
  const room = await call('POST', '/api/team/dm', {user_id: BOB});
  const rid = room.id || room.room?.id;
  for (let i = 0; i < 40; i++) await call('POST', `/api/team/rooms/${rid}/messages`, {body: `Team line ${i + 1}: ` + 'some words '.repeat(6)}, i % 2 ? BCK : CK);
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.chatFloat', '"0"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview, #chat-msgs, .tcview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const steps = async () => { await v1('POST', '/agent/typing', {chat_user_id: ME.id}); await v1('POST', '/agent/progress', {chat_user_id: ME.id, text: 'I read the tests first'}); };
  // a wheel at the end of a message list: does anything else move?
  const wheelAtEnd = async ({cmd, ev, ctx}, sel) => {
    const p = await ev(`(() => { const b = document.querySelector('${sel}'); if (!b) return null; b.scrollTop = b.scrollHeight; const r = b.getBoundingClientRect();
      const v = document.querySelector('#view'); window.__v0 = [v.scrollTop, document.scrollingElement.scrollTop, b.scrollTop];
      return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), vs: v.scrollHeight - v.clientHeight, ds: document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight,
        ob: getComputedStyle(b).overscrollBehaviorY}; })()`);
    if (!p) return null;
    for (let i = 0; i < 4; i++) {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'wheel', id: 'wh', actions: [{type: 'scroll', x: p.x, y: p.y, deltaX: 0, deltaY: 600}]}]});
      await sleep(250);
    }
    const after = await ev(`(() => { const b = document.querySelector('${sel}'), v = document.querySelector('#view'); return {v: v.scrollTop, d: document.scrollingElement.scrollTop, v0: window.__v0}; })()`);
    return {...p, ...after};
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '1280: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await o.nav(B + '#today'); await ready(ev);
    // a long Today so #view can scroll at all (the chat must not move it)
    await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1500);
    await steps(); await ev(`(() => { stepsChanged?.(); chatLoad(); return 1; })()`); await sleep(1500);
    const al = await ev(`(() => { const s = document.querySelector('#chat-steps .chstep'), t = document.querySelector('#chat-typing .ttx'); if (!s || !t) return {s: !!s, t: !!t};
      return {s: Math.round(s.getBoundingClientRect().left), t: Math.round(t.getBoundingClientRect().left)}; })()`);
    check(al && al.s && Math.abs(al.s - al.t) <= 2, '1280: #1099 the live steps line up with "is writing" ' + JSON.stringify(al));
    await shot('p2350b-1280-steps.png');
    const w1 = await wheelAtEnd(o, '#achat #chat-msgs');
    check(w1 && w1.ob === 'contain', '1280: #1102 the agent chat list has overscroll-behavior contain ' + JSON.stringify(w1));
    check(w1 && w1.v === w1.v0[0] && w1.d === w1.v0[1], '1280: #1102 a wheel at the end of the side panel chat moves neither the view nor the page ' + JSON.stringify(w1));
    await ev(`(() => { chatClose(); return 1; })()`);
    await o.nav(B + '#team/' + rid); await ready(ev); await sleep(1200);
    const w2 = await wheelAtEnd(o, '#tc-msgs');
    check(w2 && w2.ob === 'contain' && w2.vs <= 1, '1280: #1102 the team chat: contain, the view around it does not scroll ' + JSON.stringify(w2));
    check(w2 && w2.v === w2.v0[0] && w2.d === w2.v0[1], '1280: #1102 a wheel at the end of the team chat moves nothing else ' + JSON.stringify(w2));
    // 950: the agent chat is a page
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 950, height: 800}});
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(1500);
    const w3 = await wheelAtEnd(o, '.chview #chat-msgs');
    check(w3 && w3.vs <= 1 && w3.v === 0 && w3.d === w3.v0[1], '950: #1102 the agent chat page: #view does not scroll ' + JSON.stringify(w3));
  }, false);

  // ================= Firefox 402 touch, German: #1107 the header's tap areas, #1099 on the phone
  await call('PATCH', '/api/settings', {lang: 'de'});
  const wk = Math.floor(Date.now() / 1000) + 3 * 86400, fh = Math.floor(Date.now() / 1000) + 3600;
  await v1('PUT', '/agent/quota', {rate_limits: {five_hour: {used_percentage: 23.5, resets_at: fh}, seven_day: {used_percentage: 41, resets_at: wk}}});
  await v1('PUT', '/agent/status', {status: 'idle', model: 'Opus 5.5', host_permission_mode: 'auto'});
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '402: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(1500);
    const g = await ev(`(() => { ${TAP_JS}
      const hd = document.querySelector('.chath'); if (!hd) return null;
      const els = [...hd.querySelectorAll('button, a, [data-act]')].filter((e, i, all) => e.getBoundingClientRect().width > 0 && !all.some(p => p !== e && p.contains(e)));
      const bx = els.map(e => ({n: e.className.split(' ').filter(Boolean).slice(0, 2).join('.') || e.tagName, ...tapBox(e)}));
      const over = [];
      for (let i = 0; i < bx.length; i++) for (let j = i + 1; j < bx.length; j++) {
        const a = bx[i], b = bx[j], ox = Math.min(a.r, b.r) - Math.max(a.l, b.l), oy = Math.min(a.b, b.b) - Math.max(a.t, b.t);
        if (ox > 0.5 && oy > 0.5) over.push(a.n + ' / ' + b.n + ': ' + Math.round(ox) + ' px');
      }
      const small = bx.filter(b => b.r - b.l < 24 || b.b - b.t < 24).map(b => b.n + ' ' + Math.round(b.r - b.l) + 'x' + Math.round(b.b - b.t));
      const ring = document.querySelector('.chnm .chring')?.getBoundingClientRect();
      return {over, small, n: bx.length, ring: ring ? [Math.round(ring.width), Math.round(ring.height)] : null, fits: hd.scrollWidth <= hd.clientWidth + 1,
        boxes: bx.map(b => b.n + ' ' + Math.round(b.l) + '-' + Math.round(b.r))}; })()`);
    check(g && g.n >= 5 && !g.over.length, '402: #1107 no two tap areas of the chat header overlap ' + JSON.stringify(g));
    check(g && !g.small.length && g.ring && g.ring[0] >= 44 && g.ring[1] >= 44 && g.fits, '402: #1107 every tap area >= 24 px, the ring 44 px, the header fits ' + JSON.stringify(g));
    await shot('p2350b-402-chathead.png');
    await steps(); await ev(`(() => { chatLoad(); return 1; })()`); await sleep(1500);
    const al = await ev(`(() => { const s = document.querySelector('#chat-steps .chstep'), t = document.querySelector('#chat-typing .ttx'), dots = document.querySelector('#chat-typing > :first-child'); if (!s || !t) return {s: !!s, t: !!t};
      return {s: Math.round(s.getBoundingClientRect().left), t: Math.round(t.getBoundingClientRect().left), dots: Math.round(dots.getBoundingClientRect().right)}; })()`);
    check(al && al.s && al.s <= al.t && al.s >= al.dots - 4, '402: #1099 on the phone the steps sit right of the dots, a little less indented ' + JSON.stringify(al));
    await v1('POST', `/agent/chats/${ME.id}`, {body: 'Ich brauche dein Okay, bevor ich veröffentliche.', approval: {title: 'Release 2.35.0 veröffentlichen', what: 'Die neue Version geht für alle live'}});
    await ev(`(() => { chatLoad(); return 1; })()`); await sleep(1500);
    await shot('p2350b-402-approval.png');
  }, true);
  await call('PATCH', '/api/settings', {lang: 'en'});
  void a3;
  console.log(`p2350_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
