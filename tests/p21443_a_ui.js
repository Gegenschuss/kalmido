// 2.147.1 UI tests, part A (#2523 a task dragged into a chat = a reference), Firefox (desktop + phone width). Own container
// (start.sh; P21443A_NOSTART=1: the container runs already). Invented data only.
// - agent chat: a task row dragged onto the box puts in "#id" (the draft keeps it like typed text); sent, the message shows
//   the reference (a.tref[data-tref]); several selected tasks dragged at once = several references; a file dropped on the
//   box still becomes an attachment (no text)
// - team chat: "#id" at the cursor (spaces around it), a contact as a link, the message shows the reference; the thread box
//   takes a reference too
// - other fields stay closed (the title of a task); a disabled box takes nothing
// - phone width: the "Insert reference" button in the team chat and the agent chat row, a pick goes into that box;
//   the desktop shows no button
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21443_a_ui', check, shots: 'P21443A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21443A_NOSTART) {
  fs.rmSync(DATA, {recursive: true, force: true}); fs.mkdirSync(DATA, {recursive: true});
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
}
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,agents,team,contacts,events';

// in the page: one synthetic HTML5 drag from a source element onto a target element (one DataTransfer for the whole drag)
const DRAG = `window.__fire = (type, el, x, y, dt) => { const e = new DragEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, dataTransfer: dt}); el.dispatchEvent(e); return e.defaultPrevented; };
window.__drag = (src, tgt, caret) => { const dt = new DataTransfer(); __fire('dragstart', src, 0, 0, dt); const r = tgt.getBoundingClientRect(), x = r.left + 4, y = r.top + 4;
  if (caret) document.caretPositionFromPoint = () => null;
  const over = __fire('dragover', tgt, x, y, dt), drop = __fire('drop', tgt, x, y, dt); __fire('dragend', src, 0, 0, dt);
  if (caret) delete document.caretPositionFromPoint; return {over, drop, types: [...dt.types].join(',')}; };
window.__fileDrop = tgt => { const dt = new DataTransfer(); dt.items.add(new File(['call sheet'], 'call-sheet.txt', {type: 'text/plain'}));
  const r = tgt.getBoundingClientRect(), x = r.left + 4, y = r.top + 4; const over = __fire('dragover', tgt, x, y, dt), drop = __fire('drop', tgt, x, y, dt); return {over, drop}; };
window.__fake = html => { const d = document.createElement('div'); d.innerHTML = html; d.style.cssText = 'position:fixed;left:0;top:0;z-index:1'; document.body.appendChild(d); return d.firstElementChild; };
1`;

(async () => {
  await sleep(900);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.org'})).id;
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Shoot'})).id;
  const T1 = (await call(CA, 'POST', '/api/tasks', {title: 'Write the brief', list_id: L})).id;
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'Book the studio', list_id: L})).id;
  const T3 = (await call(CA, 'POST', '/api/tasks', {title: 'Scout the harbour', list_id: L})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});  // a direct message needs a shared list
  await call(CA, 'PUT', `/api/lists/${L}/agent`, {agent_id: ag.id});  // the agent chat needs a list shared with the agent
  const CT = (await call(CA, 'POST', '/api/contacts', {fn: 'Erika Example', org: 'Example Ltd'})).id;
  // the shared list's channel (a direct message has no threads)
  const RID = ((await call(CA, 'GET', '/api/team')).rooms || []).find(x => x.list_id === L)?.id;
  check(ag.id && L && T1 && T2 && T3 && CT && RID, 'setup: agent, list, tasks, contact, the list channel ' + [ag.id, L, T1, T2, T3, CT, RID].join(','));
  const ORIGIN = B.replace(/\/$/, '');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  // CI of 2.167.1: the chat rows draw again once their messages are in (the box / button is briefly gone): wait for the element
  const setVal = async (ev, sel, v) => { await ready(ev, `!!document.querySelector(${JSON.stringify(sel)})`); return ev(`(() => { const i = document.querySelector(${JSON.stringify(sel)}); i.value = ${JSON.stringify(v)}; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`); };
  const tapSel = async (ev, sel) => { await ready(ev, `!!document.querySelector(${JSON.stringify(sel)})`); return ev(`(() => { document.querySelector(${JSON.stringify(sel)}).click(); return 1; })()`); };
  const val = (ev, sel) => ev(`document.querySelector(${JSON.stringify(sel)})?.value ?? null`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#l/' + L);
    await ready(ev, `typeof rf_card === 'function' && typeof S !== 'undefined' && !!S.booted && !!taskById(${T1}) && !!document.querySelector('#view .trow[data-id="${T3}"]')`, 80);
    await ev(DRAG);

    // ================= agent chat (the side panel next to the list)
    await ev(`(() => { chatOpen(${ag.id}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#chat-in') && !document.querySelector('#chat-in').disabled`, 60), 'agent chat: the box is there');
    // the button only on touch devices (isTouch: phone width or no hover; the test machine's Firefox may report no hover)
    check(await ev(`!!document.querySelector('.chcomp [data-rfins="chat-in"]') === isTouch()`), 'the "Insert reference" button follows isTouch() ' + await ev(`String(isTouch())`));
    let d = await ev(`__drag(document.querySelector('#view .trow[data-id="${T1}"]'), document.querySelector('#chat-in'))`);
    check(d.over && d.drop && /application\/x-kalmido-ref/.test(d.types), 'agent chat: the box takes the reference ' + JSON.stringify(d));
    check((await val(ev, '#chat-in')).trim() === '#' + T1, 'agent chat: "#id" in the box ' + await val(ev, '#chat-in'));
    check(await ev(`S.drafts['chat:${ag.id}'] === document.querySelector('#chat-in').value`), 'agent chat: the draft keeps it like typed text');
    await shot('p21443-a-agentchat-drop.png');
    // a file dropped on the box stays an attachment
    d = await ev(`__fileDrop(document.querySelector('#chat-in'))`);
    check(d.drop && (await ev(`(S.chatFiles[${ag.id}] || []).length`)) === 1, 'agent chat: a dropped file becomes an attachment ' + JSON.stringify(d));
    check((await val(ev, '#chat-in')).trim() === '#' + T1, 'agent chat: the file put no text into the box');
    await ev(`(() => { S.chatFiles[${ag.id}] = []; const b = document.querySelector('#chat-files'); if (b) b.innerHTML = ''; return 1; })()`);
    // sent: the message shows the reference
    await ev(`(() => { document.querySelector('[data-act="chat-send"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#chat-msgs a[data-tref="${T1}"]')`, 60), 'agent chat: the sent message shows the reference');
    check(await ready(ev, `fetch('/api/agents/${ag.id}/chat', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.messages.some(m => m.body === '#${T1}'))`), 'agent chat: stored as "#id"');
    // several selected tasks at once
    await ev(`(() => { S.multiMode = true; S.multi.clear(); S.multi.add(${T1}); S.multi.add(${T2}); render(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#view .trow[data-id="${T2}"]')`);
    d = await ev(`__drag(document.querySelector('#view .trow[data-id="${T2}"]'), document.querySelector('#chat-in'))`);
    const mv = (await val(ev, '#chat-in')).trim();
    check(d.drop && mv.split(/\s+/).sort().join(' ') === [`#${T1}`, `#${T2}`].sort().join(' '), 'several tasks: one reference each, apart by a space ' + JSON.stringify(mv));
    await ev(`(() => { S.multi.clear(); S.multiMode = false; render(); return 1; })()`);
    await setVal(ev, '#chat-in', '');
    // other fields stay closed
    await ev(`(() => { openDetail(${T2}); return 1; })()`);
    await ready(ev, `!!document.querySelector('#d-title')`);
    d = await ev(`__drag(document.querySelector('#view .trow[data-id="${T1}"]'), document.querySelector('#d-title'))`);
    check(!d.over && !(await val(ev, '#d-title')).includes('#' + T1), 'the title field is no drop target');
    await ev(`(() => { closeDetail(); return 1; })()`);
    // a disabled box takes nothing
    await ev(`(() => { document.querySelector('#chat-in').disabled = true; return 1; })()`);
    d = await ev(`__drag(document.querySelector('#view .trow[data-id="${T1}"]'), document.querySelector('#chat-in'))`);
    check(!d.over && (await val(ev, '#chat-in')) === '', 'a disabled box takes nothing');
    await ev(`(() => { document.querySelector('#chat-in').disabled = false; return 1; })()`);

    // ================= team chat (the team view)
    await ev(`(() => { go('team/${RID}'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#tc-in')`, 60), 'team chat: the box is there');
    await setVal(ev, '#tc-in', 'before|after');
    await ev(`(() => { const i = document.querySelector('#tc-in'); i.focus(); i.setSelectionRange(7, 7); return 1; })()`);
    d = await ev(`__drag(__fake('<div class="trow" data-id="${T3}" draggable="true">Scout the harbour</div>'), document.querySelector('#tc-in'), true)`);
    check(d.drop && (await val(ev, '#tc-in')) === `before| #${T3} after`, 'team chat: put in at the cursor with spaces ' + JSON.stringify(await val(ev, '#tc-in')));
    check(await ev(`S.drafts['team:${RID}'] === document.querySelector('#tc-in').value`), 'team chat: the draft keeps it');
    await setVal(ev, '#tc-in', '');
    d = await ev(`__drag(__fake('<button class="ctrow" data-ctopen="${CT}"><span class="ctn"><b>Erika Example</b></span></button>'), document.querySelector('#tc-in'))`);
    check(d.drop && (await val(ev, '#tc-in')).trim() === `[Erika Example](${ORIGIN}/#contacts/${CT})`, 'team chat: a contact as a link ' + await val(ev, '#tc-in'));
    await setVal(ev, '#tc-in', '');
    d = await ev(`__drag(__fake('<div class="trow" data-id="${T3}" draggable="true">Scout the harbour</div>'), document.querySelector('#tc-in'))`);
    // a file dropped on the box: an attachment when the room takes files, never text
    const filesOk = await ev(`tcx_filesOk(S.tc.room)`);
    d = await ev(`__fileDrop(document.querySelector('#tc-in'))`);
    check((await val(ev, '#tc-in')).trim() === '#' + T3 && (!filesOk || (await ev(`(S.tc.files[${RID}] || []).length`)) === 1), 'team chat: a dropped file is no text (attachment when files are on: ' + filesOk + ')');
    await ev(`(() => { delete S.tc.files[${RID}]; if (typeof tcx_chipsSync === 'function') tcx_chipsSync(); return 1; })()`);
    await ev(`(() => { document.querySelector('[data-act="tc-send"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#tc-msgs a[data-tref="${T3}"]')`, 60), 'team chat: the sent message shows the reference');
    await shot('p21443-a-teamchat.png');
    // the thread box
    await ready(ev, `S.tc.msgs.some(m => m.id > 0 && String(m.body || '').includes('#${T3}'))`, 40);  // the server's answer (the shown one may still be the local copy)
    const MID = await ev(`Math.max(0, ...S.tc.msgs.filter(m => m.id > 0).map(m => m.id))`);
    await ev(`(() => { tth_open(${RID}, ${MID}, true); return 1; })()`);
    if (await ready(ev, `!!document.querySelector('#tth-in')`, 40)) {
      d = await ev(`__drag(__fake('<div class="trow" data-id="${T2}" draggable="true">Book the studio</div>'), document.querySelector('#tth-in'))`);
      check(d.drop && (await val(ev, '#tth-in')).trim() === '#' + T2, 'thread: the box takes the reference ' + await val(ev, '#tth-in'));
      await ev(`(() => { tth_close(); return 1; })()`);  // the phone part starts in the main conversation
    } else check(false, 'thread: the box is there (message ' + MID + ')');

    // ================= phone width: the button
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    // 2.308.0 (#3271): wait for the open agent chat panel to become the chat page (chatRelayout, 150 ms after the resize) instead of
    // racing it: a late go('agents/…') closed the reference search on the team chat again (the Back handling of backclose.js)
    check(await ready(ev, `!document.querySelector('#achat:not(.hidden)') && /^#agents\\//.test(location.hash)`, 40), 'phone: the agent chat panel became the chat page ' + await ev('location.hash'));
    await nav(B + '#team/' + RID);
    await ready(ev, `typeof rf_card === 'function' && !!S.booted && !!taskById(${T1}) && !!document.querySelector('#tc-in')`, 80);
    check(await ready(ev, `!!document.querySelector('.tccomp [data-rfins="tc-in"]')`, 20), 'phone: "Insert reference" in the team chat row ' + await ev(`[isTouch(), isMobile(), innerWidth, [...document.querySelectorAll('#tc-in')].map(x => x.parentElement.className + ':' + [...x.parentElement.children].map(c => c.tagName + '.' + c.className).join('/')).join(' | ')].join(',')`));
    await setVal(ev, '#tc-in', '');
    await tapSel(ev, '[data-rfins="tc-in"]');
    check(await ready(ev, `PAL.mode === 'ref' && !!document.querySelector('.palette .pqin')`), 'phone: the search opens in reference mode');
    await setVal(ev, '.palette .pqin', String(T1));
    check(await ready(ev, `PAL.items[0]?.id === 'rf:t:${T1}'`), 'phone: the task is the first hit');
    await shot('p21443-a-phone-search.png');
    await tapSel(ev, '.palette [data-pi="0"]');
    check(await ready(ev, `!document.querySelector('.palette') && document.querySelector('#tc-in').value.trim() === '#${T1}'`), 'phone: the pick is in the team chat box ' + await val(ev, '#tc-in'));
    // 2.308.0 (#3271): the closed search takes its Back entry away with a history.back() that lands a moment later: wait for it,
    // else it took the chat page opened right after back to the team chat
    await ready(ev, `typeof f8d_bk !== 'object' || (!f8d_bk.pushed && !f8d_bk.skip && !f8d_bk.queued)`, 20);
    await ev(`(() => { chatOpen(${ag.id}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#chat-in') && !!document.querySelector('.chcomp [data-rfins="chat-in"]')`, 60), 'phone: "Insert reference" in the agent chat row');
    await setVal(ev, '#chat-in', 'see');
    await tapSel(ev, '[data-rfins="chat-in"]');
    await ready(ev, `PAL.mode === 'ref'`);
    await setVal(ev, '.palette .pqin', String(T2));
    await ready(ev, `PAL.items[0]?.id === 'rf:t:${T2}'`);
    await tapSel(ev, '.palette [data-pi="0"]');
    check(await ready(ev, `!document.querySelector('.palette') && document.querySelector('#chat-in').value.trim() === 'see #${T2}'`), 'phone: the pick is in the agent chat box ' + await val(ev, '#chat-in'));
    check(await ev(`S.drafts['chat:${ag.id}'] === document.querySelector('#chat-in').value`), 'phone: the agent chat draft keeps it');
  });
  console.log(`p21443_a_ui: ${ok} passed, ${F.length} failed`);
  if (F.length) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });
