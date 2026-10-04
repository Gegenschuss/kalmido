// 2.18.0 UI tests, lane 3 (the owner's decisions from #651 + small fixes from #652), own container (start.sh, isolated
// test database).
// jsdom: the search icon never folds into "…" (no .tf4, not in topFolded() at tl4); the quick reactions 👍 👎 ❤️ sit
// visibly on every chat message (agent chat + team chat, mine too), one tap toggles, counts, names, aria-pressed, one Tab
// stop per message (roving tabindex, ← → Home End), the agent's question keeps "counts as approval" + the toast; News
// sections are h2 (no jump h1 -> h3); a team message edited to empty + Save offers to delete it (Cancel / Delete, focus).
// Firefox: touch taps at 360 / 390 / 412 and the Fold 904 (portrait + landscape), a mouse at 1440, light + dark: the
// magnifier is in the header at every width with a long list name, a timer, the agents' chip and the bell, the title is
// cut instead, nothing overlaps or scrolls sideways, header targets 44 px; the reactions are visible + one tap toggles;
// the view switch is 44 x 44 on the touch Fold; the heading order. Screenshots with P2180R_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2180_ride_ui', check, shots: 'P2180R_SHOTS', prefs: [['widget.gtk.overlay-scrollbars.enabled', true], ['ui.useOverlayScrollbars', 1]]});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const LONG = 'Website relaunch 2026 for the client';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, tour: 'done'}, CB);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const L = (await call('POST', '/api/lists', {name: LONG, kind: 'project'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const L2 = (await call('POST', '/api/lists', {name: 'Home'})).id;  // a short name: the view switch stays in the header
  await call('POST', '/api/tasks', {title: 'Water the plants', list_id: L2});
  const T = [];
  for (const t of ['Write the homepage text', 'Pick the photos', 'Call the printer']) T.push((await call('POST', '/api/tasks', {title: t, list_id: L})).id);
  await call('POST', `/api/tasks/${T[0]}/comments`, {body: 'First draft is in'}, CB);
  await call('POST', `/api/tasks/${T[2]}/comments`, {body: `<@${ME}> can you call them?`}, CB);
  await call('POST', '/api/tasks', {title: 'Review the logo', list_id: L, assignee_id: ME}, CB);
  await tcall('GET', '/agent/events?since=0', TOK);  // the agent is online
  const q1 = await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'Status: the build is green.'});
  await call('POST', `/api/agents/${AG}/chat`, {body: 'Thanks!'});
  const q2 = await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'May I merge the branch?'});

  // ================= jsdom: the search icon never folds into "…"
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const top = d.querySelector('#top'), pal = top.querySelector('[data-act="palette"]');
  check(pal && !pal.classList.contains('tf4') && !pal.classList.contains('tf'), '#651: the search button in the header is no foldable item');
  for (const l of ['tl3', 'tl4']) {
    top.classList.add(l);
    check(!w.eval('topFolded()').some(x => x.icon === 'search' || /^Search/.test(x.label)), `#651: ${l}: search is not among the items folded into "…"`);
    top.classList.remove(l);
  }
  check(top.querySelector('h1')?.getAttribute('title') === LONG && top.querySelector('h1 .ht')?.textContent === LONG, 'the h1 keeps the whole title (tooltip + text for screen readers)');
  w.close();

  // ================= jsdom: the agent chat: reactions visible on every message, approval on the question
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelectorAll('#chat-msgs .cmsg').length >= 3, 60);
  const cm = () => [...d.querySelectorAll('#chat-msgs .cmsg')];
  check(cm().length >= 3 && cm().every(m => m.querySelectorAll('.cmeta .rxrow .rx[data-e]').length === 3 && !m.querySelector('.rxtog, .chrxq')), '#651: 👍 👎 ❤️ visible on every agent-chat message (the agent\'s and mine), no smiley, no hidden bar');
  check(cm().every(m => m.querySelectorAll('.rxrow .rx[tabindex="0"]').length === 1 && m.querySelectorAll('.rxrow .rx[tabindex="-1"]').length === 2), '#651: one Tab stop per message (roving tabindex)');
  const R = id => d.querySelector(`#chat-msgs .cmsg[data-mid="${id}"]`);
  const up1 = R(q1.id).querySelector('.rxrow [data-e="up"]');
  check(up1.getAttribute('aria-label') === 'React with thumbs up' && up1.getAttribute('aria-pressed') === 'false' && !up1.querySelector('.rxn'), '#651: names: "React with thumbs up", not pressed, no count ' + up1.getAttribute('aria-label'));
  check(R(q1.id).querySelector('.rxrow').getAttribute('role') === 'group' && R(q1.id).querySelector('.rxrow').getAttribute('aria-label') === 'Reactions', 'the row is a named group');
  // keyboard: → moves inside the row
  up1.focus(); key(w, up1, 'ArrowRight');
  const dn1 = R(q1.id).querySelector('.rxrow [data-e="down"]');
  check(d.activeElement === dn1 && dn1.tabIndex === 0 && up1.tabIndex === -1, '#651: → moves to 👎 (and takes the Tab stop)');
  key(w, dn1, 'End'); check(d.activeElement === R(q1.id).querySelector('.rxrow [data-e="heart"]'), 'End: ❤️');
  key(w, d.activeElement, 'Home'); check(d.activeElement === R(q1.id).querySelector('.rxrow [data-e="up"]'), 'Home: 👍');
  // one tap on a status message: a plain reaction, the count shows
  { const hb = R(q1.id).querySelector('.rxrow [data-e="heart"]'); hb.focus(); click(w, hb); }
  check(await until(() => R(q1.id)?.querySelector('.rxrow .rx.on[data-e="heart"][aria-pressed="true"] .rxn')?.textContent === '1'), '#651: one tap: ❤️ is mine, count 1');
  check(/React with heart: Alice/.test(R(q1.id).querySelector('.rxrow [data-e="heart"]').getAttribute('aria-label')), 'its name says who: ' + R(q1.id).querySelector('.rxrow [data-e="heart"]').getAttribute('aria-label'));
  check(d.activeElement === R(q1.id).querySelector('.rxrow [data-e="heart"]'), '#651: the focus stays on the chip after the row is redrawn');
  click(w, R(q1.id).querySelector('.rxrow [data-e="heart"]'));
  check(await until(() => R(q1.id)?.querySelector('.rxrow .rx.add[data-e="heart"][aria-pressed="false"]') && !R(q1.id).querySelector('.rxrow [data-e="heart"] .rxn')), '#651: a second tap takes it back');
  // my own message
  const mineM = () => d.querySelector('#chat-msgs .cmsg.me');
  click(w, mineM().querySelector('.rxrow [data-e="up"]'));
  check(await until(() => mineM()?.querySelector('.rxrow .rx.on[data-e="up"]')), '#651: 👍 on my own message, one tap');
  // the question: 👍 counts as approval
  check(R(q2.id).querySelector('.rxrow .rxhint')?.textContent === '👍 = approval' && /counts as approval/.test(R(q2.id).querySelector('.rxrow [data-e="up"]').getAttribute('aria-label')) && /counts as rejection/.test(R(q2.id).querySelector('.rxrow [data-e="down"]').getAttribute('aria-label')), '2.7.2 kept: the newest question says 👍 = approval, 👍 / 👎 are named as approval / rejection');
  click(w, R(q2.id).querySelector('.rxrow [data-e="up"]'));
  check(await until(() => /Counted as approval/.test(R(q2.id)?.querySelector('.rxok')?.textContent || '')), 'one tap on 👍: "Counted as approval"');
  check(/Approved/.test(d.querySelector('#toast')?.textContent || ''), 'and the toast "Approved"');
  const ch = (await call('GET', `/api/agents/${AG}/chat`)).messages.find(m => m.id === q2.id);
  check(ch && ch.reactions.some(r => r.emoji === 'up' && r.users.some(u => u.id === ME)), 'the server has the approval');
  w.eval('chatClose()'); w.close();

  // ================= jsdom: the team chat: reactions + an emptied message
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.__dialogs = 'manual';
  w.eval(`go('team')`); await until(() => d.querySelector('.tclist .tcrow'));
  click(w, d.querySelector('.tclist .tcrow')); await until(() => d.querySelector('#tc-in'));
  const RID = w.eval('S.tc.rid');
  const mA = await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Draft for the client'});
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Looks good'}, CB);
  w.eval('teamChanged()');
  await until(() => [...d.querySelectorAll('#tc-msgs .cmsg.ag')].some(m => /Looks good/.test(m.textContent)));
  const bm = () => [...d.querySelectorAll('#tc-msgs .cmsg.ag')].pop();
  check([...d.querySelectorAll('#tc-msgs .cmsg')].every(m => m.querySelectorAll('.cmeta .rxrow .rx').length === 3) && !d.querySelector('#tc-msgs .rxtog[data-act="rx-tog"]'), '#651 team chat: 👍 👎 ❤️ visible on every message, no smiley');
  click(w, bm().querySelector('.rxrow [data-e="up"]'));
  check(await until(() => bm()?.querySelector('.rxrow .rx.on[data-e="up"][aria-pressed="true"] .rxn')?.textContent === '1'), '#651 team chat: one tap, count 1');
  await call('POST', `/api/team/messages/${bm().dataset.mid}/reactions`, {emoji: 'up'}, CB);
  await w.eval('loadRoom(S.tc.rid)'); w.eval('tcPatch()');
  check(await until(() => bm()?.querySelector('.rxrow [data-e="up"] .rxn')?.textContent === '2'), 'Bob too: count 2 ' + bm()?.querySelector('.rxrow [data-e="up"]')?.outerHTML);
  click(w, bm().querySelector('.rxrow [data-e="up"]'));
  check(await until(() => bm()?.querySelector('.rxrow .rx:not(.on)[data-e="up"] .rxn')?.textContent === '1'), 'a second tap takes mine back, Bob\'s stays');
  // edit to empty + Save -> "Delete this message?"
  const myM = () => d.querySelector(`#tc-msgs .cmsg[data-mid="${mA.id}"]`);
  await until(() => myM());
  click(w, myM().querySelector('[data-act="tc-msg-menu"]')); await sleep(80);
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Edit/.test(b.textContent))); await sleep(100);
  const ed = d.querySelector('#tc-msgs .tc-edit'); ed.value = '   ';
  click(w, d.querySelector('[data-act="tc-edit-save"]'));
  let dl = await until(() => [...d.querySelectorAll('.modal.cdlg')].pop());
  check(dl && /Delete this message\?/.test(dl.textContent) && dl.querySelector('[data-cd="yes"]')?.textContent.includes('Delete'), '#652: an emptied message: Save asks "Delete this message?"');
  click(w, dl.querySelector('[data-cd="no"]')); await sleep(200);
  check(d.activeElement?.classList.contains('tc-edit') && (await call('GET', `/api/team/rooms/${RID}/messages`)).messages.some(m => m.id === mA.id && !m.deleted), 'Cancel: the message stays, the focus back in the text box');
  click(w, d.querySelector('[data-act="tc-edit-save"]'));
  dl = await until(() => [...d.querySelectorAll('.modal.cdlg')].pop());
  click(w, dl.querySelector('[data-cd="yes"]'));
  check(await until(async () => (await call('GET', `/api/team/rooms/${RID}/messages`)).messages.find(m => m.id === mA.id)?.deleted), '#652: Delete deletes it');
  check(await until(() => myM()?.querySelector('.cbub.del') && !d.querySelector('#tc-msgs .tc-edit')) && d.activeElement?.id === 'tc-in', 'it shows as deleted, the edit box is gone, the focus in the message box');
  // 2.18.0 review (nit): the conversation list's preview shows no Markdown markers ("```js", **, `)
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Here is the fix:\n```js\nconst a = 1;\n```'}, CB);
  const pv = (await call('GET', '/api/team')).rooms.find(r => r.id === RID)?.last?.text;
  check(pv === 'Here is the fix: const a = 1;', 'review: the room preview has no Markdown fences (API): ' + JSON.stringify(pv));
  await w.eval('loadTeam()'); w.eval('render()');
  const pvEl = () => d.querySelector(`.tclist .tcrow[data-rid="${RID}"] .tclast`);
  check(await until(() => /Here is the fix: const a = 1;/.test(pvEl()?.textContent || '') && !/```/.test(pvEl().textContent)), 'review: ... and in the conversation list: ' + pvEl()?.textContent);
  d.querySelector('#tc-in').value = '**Bold** and `code` in [a link](https://example.com)'; await w.eval('tcSend()'); w.eval('render()');
  check(await until(() => /You: Bold and code in a link/.test(pvEl()?.textContent || '')), 'review: a message sent here: its local preview without markers too: ' + pvEl()?.textContent);
  w.close();

  // ================= jsdom: 2.18.0 review R8: density "Custom" starts exactly at the current spacing, step 1
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  { const c = JSON.parse(w.eval('JSON.stringify(densVars(20, 33))')), f = JSON.parse(w.eval('JSON.stringify(densVars(60, 67))'));
    check(c['--srow-h'] === '1.75rem' && c['--row-py'] === '0.375rem' && c['--row-h'] === '2.5rem' && c['--row-fs'] === '.875rem', 'R8: mouse: Custom at the Compact start values gives the Compact CSS values ' + JSON.stringify(c));
    check(f['--srow-h'] === '2.25rem' && f['--row-py'] === '0.625rem' && f['--row-h'] === '2.75rem' && f['--row-fs'] === '.9375rem', 'R8: mouse: ... and at the Comfortable start values the Comfortable ones ' + JSON.stringify(f)); }
  w.eval(`LS.set('densSideV', 80); LS.set('densRowsV', 90); lookSet('density', 'comfortable'); lookSet('density', 'custom')`);
  check(w.eval(`densV('side')`) === 60 && w.eval(`densV('rows')`) === 67, 'R8: Custom from Comfortable starts at 60 / 67 (an old custom value does not make it jump): ' + w.eval(`densV('side') + '/' + densV('rows')`));
  check(d.documentElement.dataset.sbase === undefined, 'R8: the comfortable half: no compact sidebar gaps');
  w.eval(`lookSet('density', 'compact'); lookSet('density', 'custom')`);
  check(w.eval(`densV('side')`) === 20 && d.documentElement.dataset.sbase === 'compact', 'R8: Custom from Compact starts at 20 and keeps the compact sidebar gaps');
  w.eval(`settingsModal('appearance')`); await sleep(400);
  { const sl = d.querySelector('#s-dens-rows');
    check(sl && sl.step === '1' && sl.value === '33' && sl.getAttribute('aria-valuetext') === '33 %' && d.getElementById('s-dens-rows-v').textContent === '33 %', 'R8: the slider has step 1, value, output and aria-valuetext agree (33 %)');
    sl.value = '41'; sl.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(80);
    check(sl.value === '41' && sl.getAttribute('aria-valuetext') === '41 %' && d.getElementById('s-dens-rows-v').textContent === '41 %' && w.eval(`densV('rows')`) === 41, 'R8: moved to 41: value, label and stored value agree'); }
  w.eval(`LS.del('density'); LS.del('densSideV'); LS.del('densRowsV'); LS.del('densitySide'); LS.del('densityRows'); applyDensity()`);
  [...d.querySelectorAll('.modal')].forEach(m => m.remove()); w.close();

  // ================= jsdom: News headings
  w = await boot({user: 'alice', hash: 'news', ls: {'tasks.newsBundle': null}}); d = w.document;
  await until(() => d.querySelector('#view .nsect'), 60);
  const hs = [...d.querySelectorAll('#top h1, #view h1, #view h2, #view h3, #view h4')].map(h => +h.tagName[1]);
  check(hs.length >= 2 && hs[0] === 1 && hs.every((l, i) => !i || l <= hs[i - 1] + 1) && d.querySelector('#view .nsect h2.nsh'), '#652: News: h1 -> h2 (no jump to h3): ' + hs.join(','));
  w.close();

  // ================= Firefox
  const tm = await call('POST', '/api/time/start', {task_id: T[1]});
  check(tm.status === 200, 'a running timer (crowds the header)');
  await tcall('PUT', '/agent/status', TOK, {status: 'working', task_id: T[0], text: 'Breaking it down'});
  const ffLogin = async ({ev, nav}, theme = 'light') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(900); };
  const tapper = ({cmd, ctx}) => async (x, y) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  // the header: the magnifier visible + 44 px, not in "…", the visible items do not overlap, nothing sideways
  const HDR = `(() => { const t = document.querySelector('#top'), vis = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
    const s = t.querySelector('[data-act="palette"]'), sr = s && vis(s) ? s.getBoundingClientRect() : null, ht = t.querySelector('h1 .ht');
    const kids = [...t.children].filter(vis).map(e => ({n: (e.dataset.act || e.className.split(' ')[0] || e.tagName), r: e.getBoundingClientRect()})).sort((a, b) => a.r.left - b.r.left);
    const over = []; for (let i = 1; i < kids.length; i++) if (kids[i].r.left < kids[i - 1].r.right - 1) over.push(kids[i - 1].n + '/' + kids[i].n);
    const small = [...t.querySelectorAll('button')].filter(vis).filter(b => { const r = b.getBoundingClientRect(); return matchMedia('(pointer: coarse)').matches ? r.width < 43.5 || r.height < 43.5 : r.width < 23.5 || r.height < 23.5; }).map(b => (b.dataset.act || b.className) + ' ' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height));
    return {lvl: (/\\btl(\\d)\\b/.exec(t.className) || [0, 0])[1], s: sr ? {w: Math.round(sr.width), h: Math.round(sr.height), l: Math.round(sr.left), r: Math.round(sr.right)} : null, iw: innerWidth,
      cut: ht ? ht.scrollWidth > ht.clientWidth + 1 : null, htw: ht ? Math.round(ht.getBoundingClientRect().width) : 0, folded: topFolded().map(x => x.label), over, small, o: document.documentElement.scrollWidth - innerWidth,
      bell: !!t.querySelector('.bell') && vis(t.querySelector('.bell')), more: !!t.querySelector('[data-act="top-more"]') && vis(t.querySelector('[data-act="top-more"]'))}; })()`;
  const HEAD = `(() => { const hs = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')].filter(h => h.getBoundingClientRect().width > 0 && !h.closest('.hidden, [hidden], #side, .modal')).map(h => +h.tagName[1]); return {hs, ok: hs[0] === 1 && hs.every((l, i) => !i || l <= hs[i - 1] + 1)}; })()`;
    // 2.18.0 review R8: switching to "Custom" moves nothing (sidebar rows / gaps, task rows), from Compact and Comfortable
  const DM = `(() => { const t = e => Math.round(e.getBoundingClientRect().top * 2) / 2, h = e => Math.round(e.getBoundingClientRect().height * 2) / 2;
    const sd = [...document.querySelectorAll('#side .srow, #side .fhead, #side .scmd, #side .sgroup')].slice(0, 16), rw = [...document.querySelectorAll('#view .trow')].slice(0, 6);
    return {side: sd.map(t).concat(sd.map(h)), rows: rw.map(t).concat(rw.map(h))}; })()`;
  const densNoJump = async (ev, tag) => {
    for (const from of ['compact', 'comfortable']) {
      await ev(`(() => { LS.del('densSideV'); LS.del('densRowsV'); lookSet('density', '${from}'); return 1; })()`); await sleep(250);
      const a = await ev(DM);
      await ev(`(() => { lookSet('density', 'custom'); return 1; })()`); await sleep(250);
      const b = await ev(DM), diff = k => a[k].map((x, i) => Math.abs(x - b[k][i])).reduce((m, x) => Math.max(m, x), 0);
      check(a.rows.length && diff('side') <= .6 && diff('rows') <= .6, `${tag}: R8: ${from} -> Custom moves nothing (sidebar ${diff('side')} px, rows ${diff('rows')} px)`);
    }
    await ev(`(() => { for (const k of ['density', 'densSideV', 'densRowsV', 'densitySide', 'densityRows']) LS.del(k); applyDensity(); return 1; })()`);
  };
  // 2.18.0 review R12 / R13: an unused reaction (grey silhouette) >= 3:1, the chat's "Sent" >= 4.5:1, on their background
  const CONTRAST = `(() => { const lum = c => { const m = c.match(/[\\d.]+/g).map(Number), f = v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }; return .2126 * f(m[0]) + .7152 * f(m[1]) + .0722 * f(m[2]); };
    const bgOf = e => { for (let x = e; x; x = x.parentElement) { const m = getComputedStyle(x).backgroundColor.match(/[\\d.]+/g); if (m && (m.length < 4 || +m[3] > .5)) return getComputedStyle(x).backgroundColor; } return 'rgb(255,255,255)'; };
    const cr = (a, b) => { const x = lum(a), y = lum(b); return +((Math.max(x, y) + .05) / (Math.min(x, y) + .05)).toFixed(2); };
    const rx = [...document.querySelectorAll('#chat-msgs .rxrow .rx.add')].filter(e => !e.matches(':hover, :focus-visible')), fl = rx.map(e => getComputedStyle(e).filter), g = fl.map(f => { const m = /brightness\\(0\\).*invert\\(([\\d.]+)\\)/.exec(f); return m ? Math.round(255 * +m[1]) : -1; });
    const rxc = rx.map((e, i) => g[i] < 0 ? 0 : cr('rgb(' + g[i] + ',' + g[i] + ',' + g[i] + ')', bgOf(e)));
    const dl = document.querySelector('#chat-msgs .cdlv'); let dlc = null; if (dl) { const on = dl.classList.contains('on'); dl.classList.remove('on'); dlc = cr(getComputedStyle(dl).color, bgOf(dl)); if (on) dl.classList.add('on'); }
    return {n: rx.length, f: fl[0], same: new Set(fl).size === 1, min: Math.min(...rxc), op: Math.min(...rx.map(e => +getComputedStyle(e).opacity)), dlc}; })()`;
  for (const [vw, vh, th] of [[360, 780, 'light'], [390, 844, 'dark'], [412, 915, 'light'], [904, 1080, 'dark'], [904, 680, 'light'], [1080, 904, 'light']]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tap = tapper(o), tag = `${vw}x${vh} ${th}`;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    for (const [name, hash] of [['list', 'l/' + L], ['today', 'today'], ['news', 'news']]) {
      await o.nav(B + '#' + hash); await ready(ev);
      const h = await ev(HDR);
      const drawerSide = vw >= 900 && !h.s;  // the unfolded Fold may show the sidebar with its own search field (2.13.3)
      check((h.s && h.s.w >= 43.5 && h.s.h >= 43.5 && h.s.l >= 0 && h.s.r <= h.iw) || (drawerSide && await ev(`!!document.querySelector('#side .scmd') && document.querySelector('#side .scmd').getBoundingClientRect().width > 0`)), `${tag} ${name}: the magnifier is in the header, 44 px, on screen ` + JSON.stringify(h.s));
      check(!h.folded.some(x => /^Search/.test(x)), `${tag} ${name}: search is never folded into "…" ` + JSON.stringify(h.folded));
      check(!h.over.length && h.o <= 0 && h.bell, `${tag} ${name}: header items do not overlap, the bell is there, nothing sideways ` + JSON.stringify({over: h.over, o: h.o, lvl: h.lvl}));
      check(!h.small.length, `${tag} ${name}: header targets 44 px ` + JSON.stringify(h.small));
      if (name === 'list' && vw < 900) check(h.cut === true || h.htw > 0, `${tag}: the long list name is cut (ellipsis) instead ` + JSON.stringify({cut: h.cut, htw: h.htw, lvl: h.lvl}));
      // 2.18.0 review R3 (owner rule): one-tap actions (view switch, undo / redo, Share) only fold into "…" (tl3) when they do
      // not fit with the title cut to its minimum; with the room of the unfolded Fold they stay
      if (name === 'list' && vw >= 900) {
        const fz = await ev(`(() => { const t = document.querySelector('#top'), l = topLevel(), vs = [...t.querySelectorAll('.vseg button')].filter(b => b.getBoundingClientRect().width > 0).length;
          let lower = null; if (l === 3) { t.classList.replace('tl3', 'tl2'); lower = topFits(t, t.querySelector('h1 .ht'), topNeed(t.querySelector('h1 .ht'))); fitTop(); }
          return {l, vs, lower, folded: topFolded().map(x => x.label), items: [...t.children].filter(e => e.getBoundingClientRect().width > 0).map(e => e.dataset.act || e.className)}; })()`);
        check(fz.l < 3 || fz.lower === 0, `${tag}: R3: header items fold only when they do not fit with the title at its minimum ` + JSON.stringify(fz));
        if (vw === 1080) check(fz.l < 3 && fz.vs >= 1 && fz.items.includes('hist tf') && fz.items.includes('share-list') && !fz.folded.length, `${tag}: R3: with a long list name the view switch, undo / redo and Share stay in the header ` + JSON.stringify(fz));
      }
      if (name === 'news') { const hd = await ev(HEAD); check(hd.ok, `${tag} news: heading order ` + JSON.stringify(hd.hs)); }
      await shot(`p2180r-${vw}x${vh}-${th}-${name}.png`);
    }
    if (vw >= 900) {  // #652: the view switch on the touch Fold
      await o.nav(B + '#l/' + L2); await ready(ev);
      const vs = await ev(`(() => { const b = [...document.querySelectorAll('#top .vseg button, #view .vsegm button')].filter(e => e.getBoundingClientRect().width > 0); return b.map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }); })()`);
      check(vs.length && vs.every(([x, y]) => x >= 44 && y >= 44), `${tag}: the view switch is at least 44 x 44 on touch ` + JSON.stringify(vs));
    }
    // the agent chat: visible reactions, one tap toggles (real taps)
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(800);
    const rr = await ev(`(() => { const out = []; for (const m of document.querySelectorAll('#chat-msgs .cmsg')) { const bs = [...m.querySelectorAll('.rxrow .rx')]; const r = bs.map(b => b.getBoundingClientRect()); out.push({n: bs.length, w: Math.round(Math.min(...r.map(x => x.width))), h: Math.round(Math.min(...r.map(x => x.height))), l: Math.round(Math.min(...r.map(x => x.left))), r: Math.round(Math.max(...r.map(x => x.right))), op: Math.min(...bs.map(b => +getComputedStyle(b).opacity))}); } return out; })()`);
    check(rr.length >= 3 && rr.every(x => x.n >= 3 && x.w >= 43.5 && x.h >= 43.5 && x.l >= 0 && x.r <= vw && x.op >= .6), `${tag}: every chat message shows its reactions (44 px, on screen, visible) ` + JSON.stringify(rr));
    const P = `(() => { const e = document.querySelector('#chat-msgs .cmsg[data-mid="${q1.id}"] .rxrow [data-e="down"]'); e.scrollIntoView({block: 'center'}); const q = e.getBoundingClientRect(); return {x: q.left + q.width / 2, y: q.top + q.height / 2}; })()`;
    let p = await ev(P); await tap(p.x, p.y);
    check(await until(() => ev(`document.querySelector('#chat-msgs .cmsg[data-mid="${q1.id}"] .rxrow [data-e="down"]')?.getAttribute('aria-pressed') === 'true'`), 30), `${tag}: one tap on 👎 reacts`);
    await shot(`p2180r-${vw}x${vh}-${th}-chat.png`);
    p = await ev(P); await tap(p.x, p.y);
    check(await until(() => ev(`document.querySelector('#chat-msgs .cmsg[data-mid="${q1.id}"] .rxrow [data-e="down"]')?.getAttribute('aria-pressed') === 'false'`), 30), `${tag}: a second tap takes it back`);
    const x = await ev(`document.documentElement.scrollWidth - innerWidth`);
    check(x <= 0, `${tag} chat: nothing sideways (${x})`);
    // 2.18.0 (owner feedback, screenshot): the reaction is a compact pill (drawn smaller inside the 44 px hit area), never a big circle
    const pill = await ev(`(() => { const b = document.querySelector('#chat-msgs .rxrow .rx.on, #chat-msgs .rxrow .rx:not(.add)') || document.querySelector('#chat-msgs .rxrow .rx'); const cs = getComputedStyle(b, '::before'), r = b.getBoundingClientRect();
      const h = cs.content !== 'none' ? r.height - parseFloat(cs.top) - parseFloat(cs.bottom) : r.height, w = cs.content !== 'none' ? r.width - parseFloat(cs.left) - parseFloat(cs.right) : r.width; return {h: Math.round(h), w: Math.round(w)}; })()`);
    check(pill.h <= 32 && pill.w >= pill.h, `${tag}: the reaction pill is compact (${JSON.stringify(pill)})`);
    { const c = await ev(CONTRAST);
      check(c.n >= 3 && c.same && c.min >= 3 && c.op === 1, `${tag}: R12: unused reactions are one grey silhouette, >= 3:1 ` + JSON.stringify(c));
      check(c.dlc === null || c.dlc >= 4.5, `${tag}: R13: the chat's "Sent" >= 4.5:1 ` + JSON.stringify(c)); }
    // 2.18.0 (owner feedback, screenshot): the working ring of the tab bar is concentric with the tab's icon
    if (vw < 900) {
      const ring = await ev(`(() => { const t = document.querySelector('#tabs .tico'); if (!t) return null; t.closest('button').classList.add('aspin'); const i = t.querySelector('svg').getBoundingClientRect(), cs = getComputedStyle(t, '::before'), tr = t.getBoundingClientRect();
        const cx = tr.left + parseFloat(cs.left) + parseFloat(cs.marginLeft) + parseFloat(cs.width) / 2, cy = tr.top + parseFloat(cs.top) + parseFloat(cs.marginTop) + parseFloat(cs.height) / 2;
        return {dx: Math.round(Math.abs(cx - (i.left + i.width / 2))), dy: Math.round(Math.abs(cy - (i.top + i.height / 2))), c: cs.content}; })()`);
      check(ring && ring.c !== 'none' && ring.dx <= 1 && ring.dy <= 1, `${tag}: the tab's working ring is centred on its icon ` + JSON.stringify(ring));
    }
    if (vw === 390 || vw === 904 && vh === 1080) {
      await o.nav(B + '#l/' + L); await ready(ev); await densNoJump(ev, tag);
      // R14: the team chat's message box: a long placeholder stays on one line (ellipsis), not wrapped / clipped
      await o.nav(B + '#team'); await ready(ev);
      await ev(`(() => { const r = [...document.querySelectorAll('.tclist .tcrow')].find(x => x.textContent.includes(${JSON.stringify(LONG)})); r && r.click(); return !!r; })()`); await sleep(1200);
      const ph = await ev(`(() => { const ta = document.querySelector('#tc-in'); if (!ta) return null; ta.value = ''; autosize(ta); const cs = getComputedStyle(ta); const cx = document.createElement('canvas').getContext('2d'); cx.font = cs.font; return {ws: cs.whiteSpace, sh: ta.scrollHeight, ch: ta.clientHeight, h: Math.round(ta.getBoundingClientRect().height), ph: ta.placeholder, pw: Math.round(cx.measureText(ta.placeholder).width), room: Math.round(ta.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)), lab: ta.getAttribute('aria-label')}; })()`);
      check(ph && /Website relaunch/.test(ph.ph) && ph.ws === 'nowrap' && ph.sh <= ph.ch + 1 && ph.h <= 48 && ph.pw <= ph.room && /…$/.test(ph.ph) && ph.lab.includes(LONG), `${tag}: R14: the long placeholder stays on one line ` + JSON.stringify(ph));
      await shot(`p2180r-${vw}x${vh}-${th}-teamph.png`);
    }
    // 2.18.0 (#642): density "Custom" at the tightest: touch rows stay 44 px
    if (vw === 390) {
      await ev(`(() => { localStorage.setItem('tasks.density', '"custom"'); localStorage.setItem('tasks.densRowsV', '0'); localStorage.setItem('tasks.densSideV', '0'); applyDensity(); return 1; })()`);
      await o.nav(B + '#l/' + L); await ready(ev);
      const rh = await ev(`Math.min(...[...document.querySelectorAll('#view .trow')].filter(r => r.getBoundingClientRect().height > 0).map(r => r.getBoundingClientRect().height))`);
      check(rh >= 43.5, `${tag}: Custom at 0 %: task rows stay 44 px on touch (${rh})`);
      await ev(`(() => { localStorage.removeItem('tasks.density'); localStorage.removeItem('tasks.densRowsV'); localStorage.removeItem('tasks.densSideV'); applyDensity(); return 1; })()`);
    }
  }, true);
  // a mouse at 1440: the reactions visible without hover, the header fits
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    const h = await ev(HDR);
    check(!h.over.length && h.o <= 0 && !h.small.length && !h.folded.some(x => /^Search/.test(x)), `${tag}: the header fits ` + JSON.stringify({over: h.over, small: h.small, folded: h.folded}));
    await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1500);
    const rr = await ev(`[...document.querySelectorAll('#chat-msgs .cmsg')].map(m => { const bs = [...m.querySelectorAll('.rxrow .rx')]; return {n: bs.length, h: Math.round(Math.min(...bs.map(b => b.getBoundingClientRect().height))), op: Math.min(...bs.map(b => +getComputedStyle(b).opacity))}; })`);
    check(rr.length >= 3 && rr.every(x => x.n >= 3 && x.h >= 23.5 && x.op >= .6), `${tag}: the reactions are visible without hover (24 px) ` + JSON.stringify(rr));
    // 2.18.0 (owner feedback, screenshot): composite input bars show the focus once, on the bar (no box inside the box)
    await o.nav(B + '#l/' + L); await ready(ev);
    const fr = await ev(`(() => { const i = document.querySelector('.qadd input, .qadd.dock input'); if (!i) return null; i.focus(); const bar = i.closest('.box').closest('.qadd.dock') || i.closest('.box');
      const ci = getComputedStyle(i), cb = getComputedStyle(bar); return {inner: ci.boxShadow, outline: ci.outlineStyle, barShadow: cb.boxShadow, barBorder: cb.borderTopColor, acc: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()}; })()`);
    check(fr && fr.inner === 'none' && (fr.outline === 'none' || !fr.outline) && fr.barShadow !== 'none', `${tag}: quick add: the bar shows the focus, the inner field no second ring ` + JSON.stringify(fr));
    // 2.18.0 (#642): Custom at 0 % with a mouse: rows get tight, never below 24 px
    await ev(`(() => { localStorage.setItem('tasks.density', '"custom"'); localStorage.setItem('tasks.densRowsV', '0'); applyDensity(); return 1; })()`);
    await o.nav(B + '#l/' + L); await ready(ev);
    const rh = await ev(`Math.min(...[...document.querySelectorAll('#view .trow')].filter(r => r.getBoundingClientRect().height > 0).map(r => r.getBoundingClientRect().height))`);
    check(rh >= 23.5 && rh < 40, `${tag}: Custom at 0 %: tighter rows, at least 24 px (${rh})`);
    await ev(`(() => { localStorage.removeItem('tasks.density'); localStorage.removeItem('tasks.densRowsV'); applyDensity(); return 1; })()`);
    await shot(`p2180r-1440-${th}-chat.png`);
    await o.nav(B + '#l/' + L); await ready(ev); await densNoJump(ev, tag);
    await o.nav(B + '#news'); await ready(ev);
    const hd = await ev(HEAD); check(hd.ok, `${tag} news: heading order ` + JSON.stringify(hd.hs));
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
