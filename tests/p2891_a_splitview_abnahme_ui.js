// 2.891.0 A acceptance test (#5358 the split view used like a person uses it), own container (start.sh, isolated test database), Firefox with a mouse.
// kalmido-suite: fresh
// Invented data only. alice has no organisation (freelancer-matrix: Geteilte Ansicht).
// At 1440 px and at 1920 px window width (P2891A_WIDTHS="2800" or a list: other widths, e.g. to show the old state's faults):
// - the switch is offered (from about 90 rem); switched on with the mouse, the right half is the NORMAL app (?split=1, no mini mode):
//   its navigation (sidebar / rail / tab bar) is visible and usable
// - a project, a task, a document, a knowledge page, the calendar and an agent's chat open on the right and show their REAL content
//   (the rows of the project, the task's title in its panel, the document's name, the page's title and text, the event, the messages)
// - on the right a person moves on to another area with the mouse and comes back with Back
// - a second agent's chat on the right shows its own messages while the left shows the first agent's; a message typed on the right
//   is sent from there and lands in that chat (server), the left chat is untouched
// - left and right do not overwrite each other: the left keeps its address and its lastKey, the right writes no settings
// - the server lets the app frame /?split=1 (and nothing else)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2891_a_splitview_abnahme', check, shots: 'P2891A_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const WIDTHS = String(process.env.P2891A_WIDTHS || '1440,1920').split(',').map(Number).filter(x => x > 0);
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const ymd = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents,wiki,files,docs,events'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});  // personal agents (a person without an organisation)
  const ME = (await call('GET', '/api/state')).me;
  const L = (await call('POST', '/api/lists', {name: 'Harbour shoot', kind: 'project'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Scout the north pier', list_id: L})).id;
  await call('POST', '/api/tasks', {title: 'Rent the dolly', list_id: L});
  const L2 = (await call('POST', '/api/lists', {name: 'Lighthouse interview', kind: 'project'})).id;
  await call('POST', '/api/tasks', {title: 'Book the keeper for Tuesday', list_id: L2});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Shoot day checklist', body: 'Bring the spare batteries'})).id;
  const now = new Date(), day = ymd(now);
  const EV = await call('POST', '/api/events', {title: 'Harbour kick-off', start: day + 'T10:00', end: day + 'T11:00'});
  const fd = new FormData(); fd.append('space', 'private');
  fd.append('files', new Blob(['Permit for the north pier\nValid until 31.12.2026\n'], {type: 'text/plain'}), 'Pier permit.txt');
  const DOC = ((await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd})).json().catch(() => ({}))).ids || [])[0];
  const agent = async name => {
    const a = await call('POST', '/api/my/agents', {username: name.toLowerCase(), display_name: name});  // a personal agent (no organisation)
    if (!a.id) console.log('agent', name, JSON.stringify(a));
    return {id: a.id, H: {Authorization: 'Bearer ' + a.token, 'Content-Type': 'application/json'}};
  };
  const A1 = await agent('Scout'), A2 = await agent('Cutter');
  await call('POST', `/api/agents/${A1.id}/chat`, {body: 'Where do we start the pier?'});
  await fetch(B + `api/v1/agent/chats/${ME.id}`, {method: 'POST', headers: A1.H, body: JSON.stringify({body: 'Start at the lighthouse end'})});
  await call('POST', `/api/agents/${A2.id}/chat`, {body: 'Cut the interview to five minutes'});
  await fetch(B + `api/v1/agent/chats/${ME.id}`, {method: 'POST', headers: A2.H, body: JSON.stringify({body: 'Five minutes, two takes'})});
  check(L && T && L2 && PG && EV.id && DOC && A1.id && A2.id, 'setup: project, task, page, event, document, two agents ' + JSON.stringify({PG, ev: EV.id || EV, DOC, a1: A1.id, a2: A2.id}));

  // the server: the app may frame its own /?split=1 (the right half), every other page stays DENY
  const hs = async u => { const r = await fetch(B + u, {headers: {Cookie: CA}}); return {csp: r.headers.get('content-security-policy') || '', xfo: r.headers.get('x-frame-options') || ''}; };
  const hsp = await hs('?split=1'), h0 = await hs(''), hm = await hs('?mini=1');
  check(/frame-ancestors 'self'/.test(hsp.csp) && hsp.xfo === 'SAMEORIGIN', '/?split=1 may be framed by the app itself ' + JSON.stringify(hsp));
  check(/frame-ancestors 'none'/.test(h0.csp) && h0.xfo === 'DENY' && /frame-ancestors 'none'/.test(hm.csp) && hm.xfo === 'DENY', '"/" and /?mini=1 stay DENY');

  await firefox(async o => {
    const {cmd, ev, ctx, nav, until, shot} = o;
    const {realClick} = require('./ff');
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    let nn = 0; const load = h => nav(B + '?n=' + (++nn) + h);
    const booted = () => until(`typeof S !== 'undefined' && S.booted && !!document.querySelector('#view')`, {timeout: 30000});
    const FR = `document.querySelector('#splitpane iframe.splitfr')`;
    const FW = `(() => { try { return ${FR}.contentWindow; } catch { return null; } })()`;
    // in the right half: run an expression with w = its window, d = its document (null while it is not there)
    const inFr = x => ev(`(() => { const w = ${FW}, d = w && w.document; if (!w || !d) return null; try { return (${x}); } catch { return null; } })()`);
    const untilFr = (x, opt = {timeout: 30000}) => until(`(() => { const w = ${FW}, d = w && w.document; if (!w || !d) return null; try { return (${x}); } catch { return null; } })()`, opt);
    // text a person can see: an element in the scope whose text matches, laid out, inside the window, not hidden
    // (the innermost elements carrying the text: a big container that holds it somewhere does not count by itself)
    const SEEN = `((d, sel, re) => { const vw = d.defaultView.innerWidth, vh = d.defaultView.innerHeight;
      const all = [...d.querySelectorAll(sel)].flatMap(r => [r, ...r.querySelectorAll('*')]).filter(e => re.test(e.textContent || '') && ![...e.children].some(c => re.test(c.textContent || '')));
      return all.some(e => { const r = e.getBoundingClientRect();
        if (r.width < 2 || r.height < 2 || r.right < 0 || r.left > vw || r.bottom < 0 || r.top > vh) return false;
        return !e.checkVisibility || e.checkVisibility({visibilityProperty: true, opacityProperty: true}); }); })`;
    const seenFr = (sel, re) => untilFr(`${SEEN}(d, ${JSON.stringify(sel)}, ${re})`);
    const seenL = (sel, re) => until(`${SEEN}(document, ${JSON.stringify(sel)}, ${re})`);
    // a click with the mouse on an element of the right half (the pointer goes to its place in the window, the browser decides what is hit)
    const clickFr = async sel => {
      const p = await inFr(`(() => { const e = d.querySelector(${JSON.stringify(sel)}); if (!e) return null; e.scrollIntoView({block: 'center', inline: 'nearest'});
        const r = e.getBoundingClientRect(), f = ${FR}.getBoundingClientRect(), fr = ${FR}, x = r.left + r.width / 2, y = r.top + r.height / 2, h = d.elementFromPoint(x, y);
        const X = f.left + fr.clientLeft + x, Y = f.top + fr.clientTop + y, top = document.elementFromPoint(X, Y);
        return {x: Math.round(X), y: Math.round(Y), ok: !!h && (h === e || e.contains(h)) && top === fr, on: h ? h.tagName + '.' + h.className : 'nothing'}; })()`);
      if (!p || !p.ok) return {ok: false, on: p ? p.on : 'no element ' + sel};
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'pf', parameters: {pointerType: 'mouse'},
        actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx});
      return {ok: true, on: p.on};
    };
    const type = async text => {
      const actions = []; for (const ch of text) actions.push({type: 'keyDown', value: ch}, {type: 'keyUp', value: ch});
      await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions}]});
      await cmd('input.releaseActions', {context: ctx});
    };
    const frHash = () => inFr(`w.location.hash`);
    const NAV = `#side, #srail, #tabs`;  // the normal app's navigation (wide: sidebar / rail, narrow: the tab bar)
    const navSeen = () => untilFr(`[...d.querySelectorAll(${JSON.stringify(NAV)})].some(e => { const r = e.getBoundingClientRect(); return r.width > 20 && r.height > 20 && getComputedStyle(e).display !== 'none' && !!e.querySelector('[data-go], [data-list], [data-sbb]'); })`, {timeout: 8000});

    for (const W of WIDTHS) {
      const tag = W + ' px: ';
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 1000}});
      await ev(`localStorage.removeItem('tasks.split'), 1`);
      await load('#l/' + L); await booted();
      await seenL('#view .trow', /Scout the north pier/);
      // ---- switch it on with the mouse: Settings > Appearance > Split view
      await ev(`(document.querySelectorAll('.smodal').forEach(m => m.remove()), loadModule('settings').then(() => { settingsModal('look'); return 1; }))`);
      await until(`!!document.querySelector('.smodal #s-lookin')`);
      const offered = await until(`!!document.querySelector('#s-split')`, {timeout: 5000});
      check(offered, tag + 'the switch for the split view is offered');
      if (!offered) { await shot(`p2891a-${W}-no-switch.png`); continue; }
      if (!await ev(`document.querySelector('#s-split').checked`)) { const c = await realClick(o, '#s-split'); if (!c.ok) await ev(`document.querySelector('#s-split').click(), 1`); }
      await ev(`document.querySelectorAll('.smodal').forEach(m => m.remove()), 1`);
      const lk0 = await ev(`localStorage.getItem('tasks.lastKey')`), set0 = (await call('GET', '/api/state')).settings || {};
      const up = await untilFr(`w.eval('typeof S !== "undefined" && S.booted') && d.querySelector('#view') ? {src: ${FR}.getAttribute('src'), mini: d.documentElement.classList.contains('mini')} : null`, {timeout: 40000});
      check(up && !up.mini && /[?&]split=1/.test(up.src) && !/mini=1/.test(up.src), tag + 'on: the right half is the normal app (?split=1, no mini mode) ' + JSON.stringify(up));

      // ---- a project, from its menu ("Open on the right", with the mouse): its rows on the right, the navigation visible
      await until(`!!document.querySelector('#view')`);
      await ev(`(() => { const x = listMenuItems(${L2}, document.body).find(x => x && x.cls === 'msplit'); if (x) x.fn(); return !!x; })()`);
      check(await seenFr('#view .trow', /Book the keeper for Tuesday/), tag + 'project on the right: its tasks are visible ' + JSON.stringify(await frHash()));
      check(await seenFr('#view, #top', /Lighthouse interview/), tag + 'project on the right: its name is visible');
      check(await navSeen(), tag + 'the right half has the app\'s navigation (sidebar, rail or tab bar)');
      await shot(`p2891a-${W}-project.png`);

      // ---- on the right: move on with the mouse to another area, then Back
      const target = await inFr(`(() => { const vis = e => { const r = e.getBoundingClientRect(); if (r.width < 4 || r.height < 4) return false; const h = d.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!h && (h === e || e.contains(h)); };
        const all = [...d.querySelectorAll(${JSON.stringify(NAV)})].flatMap(n => ['[data-list="${L}"]', '[data-go="today"]', '[data-go="inbox"]', '[data-go]'].flatMap(q => [...n.querySelectorAll(q)])).filter(vis);
        const e = all[0]; if (!e) return null; e.setAttribute('data-p2891', '1'); return {go: e.dataset.go || '', list: e.dataset.list || ''}; })()`);
      let moved = null;
      if (target) {
        const c = await clickFr('[data-p2891="1"]');
        check(c.ok, tag + 'the navigation on the right takes a mouse click ' + c.on);
        moved = await untilFr(`w.location.hash !== '#l/${L2}' && w.eval('S.booted') && (d.querySelector('#view')?.textContent || '').trim().length > 20 ? w.location.hash : null`, {timeout: 10000});
      }
      check(!!moved, tag + 'on the right a person moves on to another area ' + JSON.stringify({target, moved}));
      check(await ev(`location.hash === '#l/${L}'`), tag + 'the left stays where it was while the right moves');
      if (moved) {
        try { await cmd('browsingContext.traverseHistory', {context: ctx, delta: -1}); } catch { await inFr(`(w.history.back(), 1)`); }
        check(await untilFr(`w.location.hash === '#l/${L2}'`, {timeout: 10000}) && await seenFr('#view .trow', /Book the keeper for Tuesday/), tag + 'Back on the right: the project again ' + JSON.stringify(await frHash()));
        check(await ev(`location.hash === '#l/${L}'`), tag + 'Back took the right half back, not the left ' + JSON.stringify(await ev('location.hash')));
      }

      // ---- a task (its menu, "More…" > "Open on the right"): the panel with its title
      await until(`!!document.querySelector('#view .trow[data-id="${T}"]')`);
      await ev(`(() => { taskMenu(document.querySelector('#view .trow[data-id="${T}"]'), ${T}); return 1; })()`);
      await until(`[...document.querySelectorAll('[role=menu] button.msubm')].some(b => /More/.test(b.textContent))`);
      await ev(`[...document.querySelectorAll('[role=menu] button.msubm')].find(b => /More/.test(b.textContent)).click(), 1`);
      const sp = await until(`!!document.querySelector('[role=menu] button.msplit')`);
      const spc = sp ? await realClick(o, '[role=menu] button.msplit') : {ok: false, on: 'no menu entry'};
      check(spc.ok, tag + '"Open on the right" in the task menu takes a mouse click ' + spc.on);
      check(sp && await seenFr('#detail', /Scout the north pier/), tag + 'task on the right: its panel shows the title ' + JSON.stringify(await frHash()));
      await ev(`closePop && closePop(), 1`).catch(() => 0);

      // ---- a document, a knowledge page, the calendar (the routes their menus' "Open on the right" use)
      await ev(`spl_open('#docs/${DOC}'), 1`);
      check(await seenFr('body', /Pier permit/), tag + 'document on the right: its name is visible ' + JSON.stringify(await inFr(`[w.location.hash, w.innerWidth, w.innerHeight, ...[...d.querySelectorAll('body *')].filter(e => /Pier permit/.test(e.textContent || '') && ![...e.children].some(c => /Pier permit/.test(c.textContent || ''))).slice(0, 8).map(e => { const r = e.getBoundingClientRect(); return e.tagName + '.' + e.className + ' ' + [r.left, r.top, r.width, r.height].map(Math.round).join(',') + ' ' + (e.checkVisibility ? e.checkVisibility({visibilityProperty: true, opacityProperty: true}) : '-'); })]`)));
      await ev(`spl_open('#wiki/${PG}'), 1`);
      check(await seenFr('#view h2, #view .wktitle', /Shoot day checklist/) && await seenFr('#view', /Bring the spare batteries/), tag + 'knowledge page on the right: title and text visible ' + JSON.stringify(await frHash()));
      await ev(`spl_open('#cal'), 1`);
      check(await seenFr('#view', /Harbour kick-off/), tag + 'calendar on the right: the event is visible ' + JSON.stringify(await frHash()));
      await shot(`p2891a-${W}-calendar.png`);
      check(await ev(`location.hash === '#l/${L}' && localStorage.getItem('tasks.lastKey') === ${JSON.stringify(lk0)}`), tag + 'after six areas on the right the left keeps its address and lastKey ' + JSON.stringify(await ev(`[location.hash, localStorage.getItem('tasks.lastKey')]`)));

      // ---- two agent chats: the first on the left, the second on the right; both show their own messages, typing on the right works
      await ev(`go('agents/${A1.id}'), 1`);
      check(await seenL('#chat-msgs .cmsg', /Start at the lighthouse end/), tag + 'the first agent\'s chat on the left shows its messages ' + JSON.stringify(await ev(`[location.hash, (document.querySelector('#view')?.textContent || '').replace(/\\s+/g, ' ').slice(0, 300)]`)));
      const lk1 = await ev(`localStorage.getItem('tasks.lastKey')`);
      await ev(`spl_open('#agents/${A2.id}'), 1`);
      check(await seenFr('#chat-msgs .cmsg', /Five minutes, two takes/), tag + 'the second agent\'s chat on the right shows its messages ' + JSON.stringify(await inFr(`[w.location.hash, (d.querySelector('#view')?.textContent || '').replace(/\\s+/g, ' ').slice(0, 300)]`)));
      check(!await inFr(`/Start at the lighthouse end/.test(d.querySelector('#chat-msgs')?.textContent || '')`), tag + 'the right chat is not the left one');
      const msg = `From the right ${W}`;
      const ci = await clickFr('#chat-in');
      check(ci.ok, tag + 'the composer on the right takes a mouse click ' + ci.on);
      if (ci.ok) {
        await untilFr(`d.activeElement === d.querySelector('#chat-in')`, {timeout: 3000});
        await type(msg);
        await untilFr(`d.querySelector('#chat-in').value === ${JSON.stringify(msg)}`, {timeout: 3000});
        const sb = await clickFr('.chcomp [data-act="chat-send"]');
        check(sb.ok, tag + 'the send button on the right takes a mouse click ' + sb.on);
      }
      check(await seenFr('#chat-msgs .cmsg', new RegExp(msg)), tag + 'the message typed on the right shows in the right chat');
      const onServer = await (async () => { for (let i = 0; i < 40; i++) { const j = await call('GET', `/api/agents/${A2.id}/chat`); if (JSON.stringify(j).includes(msg)) return true; await sleep(250); } return false; })();
      check(onServer, tag + 'the message lands in the second agent\'s chat (server)');
      check(await ev(`location.hash === '#agents/${A1.id}' && !(document.querySelector('#chat-msgs')?.textContent || '').includes(${JSON.stringify(msg)})`), tag + 'the left chat stays the first agent\'s, untouched');
      await shot(`p2891a-${W}-chats.png`);

      // ---- left and right do not overwrite each other
      check(await ev(`localStorage.getItem('tasks.lastKey') === ${JSON.stringify(lk1)}`), tag + 'the right chat leaves the left\'s lastKey alone ' + JSON.stringify(await ev(`[localStorage.getItem('tasks.lastKey'), ${JSON.stringify(lk1)}]`)));
      const set1 = (await call('GET', '/api/state')).settings || {};
      const diff = Object.keys({...set0, ...set1}).filter(k => !['look', 'whatsnew_seen'].includes(k) && JSON.stringify(set0[k]) !== JSON.stringify(set1[k]));
      check(!diff.length, tag + 'the right half wrote no settings ' + JSON.stringify(diff));
      check(await inFr(`w.eval('typeof spl_offer === "function" && spl_offer() === false') && !d.querySelector('#splitpane')`), tag + 'the right half offers no split view of its own');
      // off again for the next width
      await ev(`(LS.set('split', false), spl_check(), 1)`);
      await until(`!document.querySelector('iframe.splitfr')`);
    }
  }, false);

  console.log(`p2891_a_splitview_abnahme: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
