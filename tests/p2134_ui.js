// 2.13.4 UI tests (phone round, reported on a folded Galaxy Z Fold, Android Chrome PWA), own container (start.sh, isolated
// test database). Real touch gestures in Firefox (WebDriver BiDi input.performActions with pointerType touch: long press,
// drag, hold at the edge, swipe) at 390 x 844 and 880 x 904, plus jsdom:
// - the "+" of a section head opens the quick sheet with that section (the inline field ended up behind the keyboard),
//   the sheet's box stays above a simulated keyboard (visualViewport);
// - a touch drag never leaves its ghost behind: a lost touchend (a new touch), Escape, the app going to the background;
// - holding a dragged task at the bottom / top edge scrolls the list on its own, also with the finger still;
// - "Move to list" appears while dragging: dropping on it opens the list picker, the task moves;
// - mouse drags scroll the list at its edges;
// - the phone chat: a swipe beside the message box does not scroll the page (no gap above the tab bar);
// - Markdown: nested lists, numbered lists keep counting across nested bullets, <ol start>.
// Screenshots with P2134_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2134_ui', check, shots: 'P2134_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _st: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:8[7-9]|9[0-9]|[1-9][0-9]{2})'/.test(SW), 'service worker cache v87');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const L = (await call('POST', '/api/lists', {name: 'Heide'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Elsewhere'})).id;
  await call('POST', '/api/sections', {list_id: L, name: 'Mitnehmen'});
  const SEC = (await call('GET', '/api/state')).sections.find(s => s.list_id === L).id;
  const T = [];
  for (let i = 1; i <= 36; i++) T.push((await call('POST', '/api/tasks', {title: `Task ${String(i).padStart(2, '0')}`, list_id: L})).id);
  for (let i = 0; i < 6; i++) await tcall('POST', `/agent/chats/${ME}`, TOK, {body: `Message ${i}\n\n1. First:\n   - a\n   - b\n2. Second`});

  // ================= jsdom: Markdown lists
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const md = w.eval(`renderMd('1. First:\\n   - a\\n   - b\\n2. Then\\n\\n3. Three')`);
  check(/<ol><li>First:<ul><li>a<\/li><li>b<\/li><\/ul><\/li><li>Then<\/li><\/ol>/.test(md), 'Markdown: bullets nest in the numbered item, the numbering goes on: ' + md);
  check(/<ol start="3"><li>Three/.test(md), 'Markdown: a list that starts at 3 shows 3');
  const md2 = w.eval(`renderMd('1. A\\n- x\\n2. B')`);
  check(/<ol start="2"><li>B/.test(md2), 'Markdown: an unindented bullet in between does not restart at 1: ' + md2);
  check(/class="cb on"/.test(w.eval(`renderMd('- [x] done\\n- [ ] open')`)), 'Markdown: checkboxes still work');
  const md3 = w.eval(`renderMd('Run:\\n\\x60\\x60\\x60\\nconst a = <b>1</b>;\\n  - not a list\\n\\x60\\x60\\x60\\nafter')`);
  // 2.18.0 (#408 G): the block sits in a .mdcode wrapper with a Copy button after the <pre>
  check(/<pre class="mdpre"><code>const a = &lt;b&gt;1&lt;\/b&gt;;\n  - not a list<\/code><\/pre>(?:<button[^]*?<\/button><\/div>)?<p>after<\/p>/.test(md3), 'Markdown: fenced code blocks stay as they are (escaped, no list): ' + md3);
  w.close();
  // ================= jsdom phone: the section "+" opens the quick sheet with the section
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + L}); d = w.document;
  const plus = d.querySelector(`#view .ghead [data-act="sec-add"][data-sec="${SEC}"]`);
  check(!!plus, 'phone: the section head has its "+"');
  click(w, plus); await sleep(300);
  const sh = d.querySelector('.qadd.sheet #qsheet');
  check(sh && /Mitnehmen/.test(sh.placeholder) && !d.querySelector('#view .secadd-in'), 'phone: section "+" opens the quick sheet for that section ' + (sh && sh.placeholder));
  sh.value = 'Sunscreen'; click(w, d.querySelector('.qadd.sheet [data-act="qsheet-send"]'));
  const sc = await until(async () => (await call('GET', '/api/state')).tasks.find(t => t.title === 'Sunscreen'), 40);
  check(sc && sc.section_id === SEC && sc.list_id === L, 'the task lands in that section');
  w.close();
  // desktop keeps the inline field
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  click(w, d.querySelector(`#view .ghead [data-act="sec-add"][data-sec="${SEC}"]`)); await sleep(300);
  check(!!d.querySelector('#view .secadd-in') && !d.querySelector('.qadd.sheet'), 'desktop: the inline field under the section head as before');
  // mouse drag at the edge of the list scrolls it (dragover near the bottom)
  d.querySelector('#view').getBoundingClientRect = () => ({top: 100, bottom: 700, left: 0, right: 800, width: 800, height: 600});  // jsdom has no layout
  w.eval(`dragId = ${T[0]}; dsEdge(695)`);
  check(w.eval('DSE.v') > 0, 'mouse drag near the bottom edge: the list scrolls down');
  w.eval(`dsEdge(105)`);
  check(w.eval('DSE.v') < 0, 'mouse drag near the top edge: the list scrolls up');
  w.eval(`dragId = null; DSE.v = 0`);
  // a mouse drop on another list in the sidebar moves the task there
  const srow = d.querySelector(`#side [data-drop="l:${L2}"]`);
  check(!!srow, 'desktop sidebar: other lists are drop targets');
  if (srow) { await w.eval(`dropTask(${T[30]}, document.querySelector('#side [data-drop="l:${L2}"]'), 0)`); await sleep(600); }
  check((await call('GET', '/api/state')).tasks.find(t => t.id === T[30]).list_id === L2, 'desktop: dropped on another list in the sidebar, the task moved');
  w.close();
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));

  // ================= Firefox: real touch gestures
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const VVSIM = `(() => { const vv = window.visualViewport; window.__kb = {h: null, t: 0};
    Object.defineProperty(vv, 'height', {configurable: true, get: () => window.__kb.h ?? innerHeight});
    Object.defineProperty(vv, 'offsetTop', {configurable: true, get: () => window.__kb.t});
    window.__setKb = (hh, t) => { window.__kb.h = hh; window.__kb.t = t; vv.dispatchEvent(new Event('resize')); vv.dispatchEvent(new Event('scroll')); return 1; };
    return 1; })()`;
  for (const [vw, vh] of [[390, 844], [880, 904]]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const tag = String(vw);
    check(await ffLogin({ev, nav}) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    // one finger: down, hold, move in steps, optionally hold at the end, up (or not)
    const touch = (pts, {hold = 600, endHold = 0, up = true} = {}) => {
      const a = [{type: 'pointerMove', x: Math.round(pts[0][0]), y: Math.round(pts[0][1])}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: hold}];
      for (const [x, y] of pts.slice(1)) a.push({type: 'pointerMove', x: Math.round(x), y: Math.round(y), duration: 120});
      if (endHold) a.push({type: 'pause', duration: endHold});
      if (up) a.push({type: 'pointerUp', button: 0});
      return cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'}, actions: a}]});
    };
    const release = () => cmd('input.releaseActions', {context: ctx});
    const rowAt = id => ev(`(() => { const r = document.querySelector('#view .trow[data-id="${id}"]'); if (!r) return null; const b = r.querySelector('.ttl').getBoundingClientRect(); return {x: b.left + 20, y: b.top + b.height / 2}; })()`);
    // task rows fully on screen (above the tab bar / composer), top first
    const vis = () => ev(`(() => { const lim = Math.min(innerHeight, ...[document.querySelector('#tabs'), document.querySelector('.qdock')].filter(e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height).map(e => e.getBoundingClientRect().top)); return [...document.querySelectorAll('#view .trow')].filter(r => { const b = r.getBoundingClientRect(); return b.top > 80 && b.bottom < lim - 10; }).map(r => +r.dataset.id).filter(id => id > 0); })()`);
    const ghosts = () => ev(`document.querySelectorAll('.ghost-drag').length + (document.body.classList.contains('tdrag') ? 10 : 0)`);
    await nav(B + '#l/' + L); await ready(ev);
    // 1) a drag whose end never arrives (the finger stays down), then a new touch elsewhere: the ghost goes
    let V = await vis();
    check(V.length >= 4, `${tag}: rows on screen ` + V.length);
    let p = await rowAt(V[0]);
    await touch([[p.x, p.y], [p.x, p.y + 30]], {up: false}); await sleep(200);
    check(await ghosts() > 0, `${tag}: a long press + move starts a drag (ghost)`);
    await shot(`p2134-${tag}-dragging.png`);
    await ev(`(() => { const t = new Touch({identifier: 99, target: document.querySelector('#top h1'), clientX: 10, clientY: 10}); document.querySelector('#top h1').dispatchEvent(new TouchEvent('touchstart', {bubbles: true, touches: [t], targetTouches: [t], changedTouches: [t]})); return 1; })()`).catch(() => 0);
    await sleep(200);
    check(await ghosts() === 0, `${tag}: a new touch after a lost touchend clears the ghost`);
    await release(); await sleep(300);
    check(await ghosts() === 0, `${tag}: no ghost after letting go`);
    // 2) Escape and the app going to the background end a drag
    p = await rowAt(V[1]);
    await touch([[p.x, p.y], [p.x, p.y + 20]], {up: false}); await sleep(200);
    await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`); await sleep(200);
    check(await ghosts() === 0, `${tag}: Escape ends a touch drag without a ghost`);
    await release(); await sleep(300);
    p = await rowAt(V[2]);
    await touch([[p.x, p.y], [p.x, p.y + 20]], {up: false}); await sleep(200);
    await ev(`(() => { Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); document.dispatchEvent(new Event('visibilitychange')); delete document.hidden; return 1; })()`); await sleep(200);
    check(await ghosts() === 0, `${tag}: the app going to the background ends a touch drag without a ghost`);
    await release(); await sleep(300);
    // a re-render (live update) in the middle of a drag: the drag goes on and still ends cleanly
    p = await rowAt(V[3]);
    await touch([[p.x, p.y], [p.x, p.y + 20]], {up: false}); await sleep(150);
    await ev(`(() => { render(); return 1; })()`); await sleep(150);
    await release(); await sleep(400);
    check(await ghosts() === 0, `${tag}: a re-render during the drag leaves no ghost`);
    // 2b) a swipe that the system cancels (touchcancel) snaps back and does nothing
    p = await rowAt(V[0]);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(p.x), y: Math.round(p.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerMove', x: Math.round(p.x + 40), y: Math.round(p.y), duration: 60}, {type: 'pointerMove', x: Math.round(p.x + 75), y: Math.round(p.y), duration: 60}]}]});
    await sleep(150);
    const sw0 = await ev(`document.querySelector('#view .trow[data-id="${V[0]}"]').style.transform`);
    await ev(`(() => { document.dispatchEvent(new TouchEvent('touchcancel', {bubbles: true})); return 1; })()`); await sleep(350);
    const sw1 = await ev(`document.querySelector('#view .trow[data-id="${V[0]}"]').style.transform`);
    check(/translateX/.test(sw0) && !sw1, `${tag}: a cancelled swipe snaps back (${sw0} -> '${sw1}')`);
    await release(); await sleep(300);
    check((await call('GET', '/api/state')).tasks.find(t => t.id === V[0]).status === 0, `${tag}: and does not complete the task`);
    // 3) auto-scroll: hold a task at the bottom edge with the finger still: the list scrolls on its own
    await ev(`(() => { document.querySelector('#view').scrollTop = 0; return 1; })()`); await sleep(200);
    V = await vis(); const DR = V[0];
    const before = (await call('GET', '/api/state')).tasks.filter(t => t.list_id === L && !t.section_id && t.status === 0);
    p = await rowAt(DR);
    const bottomY = await ev(`(() => { const b = Math.min(innerHeight, ...['#tabs', '#view .qdock'].map(q => document.querySelector(q)).filter(e => e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height).map(e => e.getBoundingClientRect().top)); return Math.min(b, document.querySelector('#view').getBoundingClientRect().bottom) - 20; })()`);
    const s0 = await ev(`document.querySelector('#view').scrollTop`);
    await touch([[p.x, p.y], [p.x, (p.y + bottomY) / 2], [p.x, bottomY]], {endHold: 700, up: false});
    const s1 = await ev(`document.querySelector('#view').scrollTop`);
    check(s1 > s0 + 150, `${tag}: holding a dragged task at the bottom edge scrolls the list (${s0} -> ${s1})`);
    await shot(`p2134-${tag}-autoscroll.png`);
    await touch([[p.x, bottomY], [p.x, bottomY - 120]], {hold: 0, up: false}).catch(() => 0);  // out of the edge zone, over a row
    const dbg = await ev(`(() => ({lp: !!lp && {active: lp.active, lx: lp.lx, ly: lp.ly, sv: lp.sv}, under: (() => { const e = lp && document.elementFromPoint(lp.lx, lp.ly); return e ? (e.closest('.trow')?.dataset.id || e.tagName + '.' + e.className) : null; })()}))()`);
    await release(); await sleep(900);
    if (process.env.P2134_DEBUG) console.log('DEBUG', JSON.stringify(dbg), await ev(`document.querySelector('#toast')?.textContent`));
    const shownAfter = await ev(`[...document.querySelectorAll('#view .trow')].map(r => +r.dataset.id)`);
    check(shownAfter.indexOf(DR) > V.length, `${tag}: dropped further down than the first screen (row ${shownAfter.indexOf(DR) + 1}, ${V.length} rows fit on the screen)`);
    void before;
    check(await ghosts() === 0, `${tag}: no ghost after the scrolled drop`);
    // 4) "Move to list": drag a task onto it, the list picker opens, the task moves
    await ev(`(() => { document.querySelector('#view').scrollTop = 0; return 1; })()`); await sleep(300);
    V = await vis(); const MT = V[1];
    p = await rowAt(MT);
    await touch([[p.x, p.y], [p.x, p.y + 40]], {up: false}); await sleep(200);
    const mv = await ev(`(() => { const m = document.querySelector('#tdmove'); if (!m) return null; const b = m.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, h: b.height}; })()`);
    check(mv && mv.h >= 43.5, `${tag}: while dragging, "Move to list" shows (44 px) ` + JSON.stringify(mv));
    await release(); await sleep(400);
    if (mv) {
      p = await rowAt(MT);
      await touch([[p.x, p.y], [p.x, (p.y + mv.y) / 2], [mv.x, mv.y]], {endHold: 300}); await sleep(600);
      check(await ev(`!!document.querySelector('.palette') && PAL.mode === 'move'`), `${tag}: dropped on "Move to list": the list picker opens`);
      await shot(`p2134-${tag}-move.png`);
      await ev(`(() => { const it = PAL.items.find(x => x.label === 'Elsewhere'); it && it.fn(); closePalette(); return 1; })()`); await sleep(800);
      check((await call('GET', '/api/state')).tasks.find(t => t.id === MT).list_id === L2, `${tag}: the task moved to the other list`);
      await release();
    }
    // 5) the section "+" with a keyboard: the sheet's box is above the keyboard
    if (vw === 390) {
      await nav(B + '#l/' + L); await ready(ev); await ev(VVSIM);
      await ev(`(() => { document.querySelector('#view .ghead [data-act="sec-add"][data-sec="${SEC}"]').scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
      const sp = await ev(`(() => { const b = document.querySelector('#view .ghead [data-act="sec-add"][data-sec="${SEC}"]').getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2}; })()`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(sp.x), y: Math.round(sp.y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]}); await release();
      await sleep(500);
      await ev(`__setKb(${Math.round(vh * .55)}, 0)`); await sleep(600);
      const kb = await ev(`(() => { const i = document.querySelector('#qsheet'); if (!i) return null; const b = i.getBoundingClientRect(); return {bottom: Math.round(b.bottom), top: Math.round(b.top), vv: visualViewport.height, focus: document.activeElement === i}; })()`);
      check(kb && kb.bottom <= kb.vv + 1 && kb.top >= 0 && kb.focus, '390: section "+" with the keyboard up: the box is visible above it, with the focus ' + JSON.stringify(kb));
      await shot('p2134-390-section-plus-kb.png');
      await ev(`(() => { __setKb(null, 0); closePop(); return 1; })()`); await sleep(300);
      // the comment box of a task with the (iOS) keyboard up: the panel ends above the keyboard
      await ev(`(() => { openDetail(${T[10]}); return 1; })()`); await sleep(900);
      await ev(`(() => { document.querySelector('#c-input').focus(); return 1; })()`); await sleep(200);
      await ev(`__setKb(${Math.round(vh * .55)}, 0)`); await sleep(700);
      const ck = await ev(`(() => { const b = document.querySelector('#c-input').getBoundingClientRect(); return {top: Math.round(b.top), bottom: Math.round(b.bottom), vv: visualViewport.height}; })()`);
      check(ck.bottom <= ck.vv + 1 && ck.top > 0, '390: the comment box stays above the (iOS) keyboard ' + JSON.stringify(ck));
      await shot('p2134-390-comment-kb.png');
      await ev(`(() => { __setKb(null, 0); document.activeElement.blur(); closeDetail(); return 1; })()`); await sleep(600);
      // 6) the phone chat: swiping beside the box scrolls nothing outside the messages
      await nav(B + '#agents/' + AG); await ready(ev); await sleep(800);
      const c0 = await ev(`(() => { const c = document.querySelector('.chview .chcomp') || document.querySelector('#chat-in').parentElement; const b = c.getBoundingClientRect(), t = document.querySelector('#tabs'); return {x: Math.round(b.left + 12), y: Math.round(b.top + b.height / 2), gap: Math.round((t && getComputedStyle(t).display !== 'none' ? t.getBoundingClientRect().top : innerHeight) - b.bottom), vs: document.querySelector('#view').scrollTop}; })()`);
      await touch([[c0.x, c0.y], [c0.x, c0.y - 120], [c0.x, c0.y - 250]], {hold: 30}); await release(); await sleep(500);
      const c1 = await ev(`(() => { const c = document.querySelector('.chview .chcomp') || document.querySelector('#chat-in').parentElement; const b = c.getBoundingClientRect(), t = document.querySelector('#tabs'); return {gap: Math.round((t && getComputedStyle(t).display !== 'none' ? t.getBoundingClientRect().top : innerHeight) - b.bottom), vs: document.querySelector('#view').scrollTop, ws: document.scrollingElement.scrollTop}; })()`);
      check(c1.vs === 0 && c1.ws === 0 && Math.abs(c1.gap - c0.gap) <= 2, '390 chat: a swipe beside the box moves nothing, no gap above the tab bar ' + JSON.stringify({c0, c1}));
      await shot('p2134-390-chat-swipe.png');
      const ol = await ev(`(() => { const o = [...document.querySelectorAll('#chat-msgs ol')]; return o.length ? o[0].querySelectorAll(':scope > li').length : 0; })()`);
      check(ol === 2, '390 chat: the numbered list goes on after the nested bullets (2 items in one list)');
    }
  }, true);

  console.log(`p2134_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
