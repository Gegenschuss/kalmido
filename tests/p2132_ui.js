// 2.13.2 (#478) UI tests, own container (start.sh, isolated test database): the fixes of the independent re-review of
// 2.13.0. One regression check per finding: list | task | chat side by side on a desktop, the task takes the chat's place
// where all three do not fit (N1), re-renders keep the keyboard focus (N2), a half-typed quick add survives folding /
// unfolding a Fold (N3), Markdown in comments and chat (N4), font size 75-150 % with round done circles (N5), 0-byte files
// refused (N6), an approval once in Today (N7), the phone chat inside an iOS-pushed visual viewport (N8), the pill and Send
// keep the keyboard (N9), the chat panel stays at the bottom when the window gets lower (N10), and the "Feinschliff" items
// F1-F14 plus fewer inline helper texts in Settings > Integrations / Administration. jsdom (logic) and Firefox headless
// via ff.js: 390 / 428 touch with a simulated iOS keyboard, Fold 904 touch with fold / unfold, desktop 1440 / 1920 / 1100
// with mouse + keyboard. Screenshots with P2132_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2132_ui', check, shots: 'P2132_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const upload = async (url, files, fields = {}) => { const fd = new FormData(); for (const [k, v] of Object.entries(fields)) fd.append(k, v); for (const [n, b] of files) fd.append('file', new Blob([b], {type: 'text/plain'}), n); const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:8[5-9]|9[0-9]|[1-9][0-9]{2})'/.test(SW), 'service worker cache v85');

  // ================= F12: setup step 2 after a reload starts from the modules that are on now
  const su = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true})});
  check(su.status === 200, 'setup');
  CK = await login('alice');
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await until(() => d.querySelector('.authscreen .supresets'), 80);
  check(d.querySelector('.supreset.on[data-su-preset="me"]'), 'F12: a new account (all modules on = the default) starts with "For me" (2.19.0, was "Simple list")');
  w.close();
  await call('PATCH', '/api/settings', {features: 'cal,kanban,matrix,collab,comments'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('.authscreen .supresets'), 80);
  const cnt = d.querySelector('.authscreen .sucust summary .muted')?.textContent || '';
  check(!d.querySelector('.supreset.on[data-su-preset="me"]') && /^5 /.test(cnt) && d.querySelector('[data-use="kanban"]')?.checked && !d.querySelector('[data-use="habits"]')?.checked, 'F12: after a reload step 2 shows what is on (5 modules), not "Simple list": ' + cnt);
  w.close();
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;

  // data: a project shared with an agent, sections, tasks
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  for (const n of ['Backlog', 'Doing']) await call('POST', '/api/sections', {list_id: P, name: n});
  const SECS = (await call('GET', '/api/state')).sections.filter(s => s.list_id === P).map(s => s.id);
  const T = [];
  for (let i = 1; i <= 4; i++) T.push((await call('POST', '/api/tasks', {title: 'Page ' + i, list_id: P, section_id: SECS[0], due: day(i)})).id);
  // F1: a long column with two-line titles (cards used to shrink into each other)
  for (let i = 1; i <= 24; i++) await call('POST', '/api/tasks', {title: `Anna live while quick add, a title long enough for two lines ${i}`, list_id: P});
  await tcall('GET', '/agent/events?since=0', TOK);

  // ================= N6: 0-byte files are refused (task, chat, project files), a real one still works
  const e1 = await upload(`/api/tasks/${T[0]}/attachments`, [['empty.txt', '']]);
  check(e1.status === 400 && /empty\.txt: the file is empty and was not uploaded/.test(e1.error || ''), 'N6: a 0-byte task file is refused with a clear message ' + JSON.stringify(e1).slice(0, 160));
  const e2 = await upload(`/api/agents/${AG}/chat`, [['empty.png', '']]);
  check(e2.status === 400 && /empty/.test(e2.error || ''), 'N6: a 0-byte chat file is refused ' + JSON.stringify(e2).slice(0, 160));
  const e3 = await upload(`/api/lists/${P}/files`, [['empty.pdf', '']]);
  check(e3.status === 400 && /empty/.test(e3.error || ''), 'N6: a 0-byte project file is refused ' + JSON.stringify(e3).slice(0, 160));
  const e4 = await upload(`/api/tasks/${T[0]}/attachments`, [['note.txt', 'hello']]);
  check(e4.status === 200 && e4.attachments?.length === 1, 'N6: a file with content is attached');
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  const sent = []; const of = w.fetch; w.fetch = (u, o) => { sent.push(String(u)); return of(u, o); };
  await w.eval(`uploadFiles(${T[0]}, [new File([], 'leer.txt')])`); await sleep(300);
  check(/leer\.txt: the file is empty and was not uploaded/.test(d.querySelector('#toast')?.textContent || '') && !sent.some(u => /attachments/.test(u)), 'N6: the app says so before uploading and sends nothing');
  w.fetch = of; w.close();

  // ================= N4 + F5 + F6: Markdown in comments and chat, grouped agent comments, "working" is not "writing"
  const md = '## Plan\n- one\n- two\n- [ ] open point\n- [x] done point\n\n**bold** and `code`';
  await tcall('POST', `/tasks/${T[1]}/comments`, TOK, {body: md});
  await tcall('POST', `/tasks/${T[1]}/comments`, TOK, {body: 'Second note right after'});
  await tcall('POST', `/agent/chats/${ME}`, TOK, {body: md});
  await tcall('PUT', '/agent/status', TOK, {status: 'working', text: 'Checking', task_id: T[1]});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`openDetail(${T[1]})`); await until(() => d.querySelectorAll('#d-tl .cm').length >= 2, 60);
  const cms = [...d.querySelectorAll('#d-tl .cm')], c1 = cms.find(c => /Plan/.test(c.textContent));
  check(c1 && c1.querySelector('.cbody .mdc h5')?.textContent === 'Plan' && c1.querySelectorAll('.cbody .mdc ul li').length === 4 && !/##/.test(c1.querySelector('.cbody').textContent), 'N4: a comment renders headings and lists (no raw "##")');
  const cbs = c1 ? [...c1.querySelectorAll('.cbody input[type=checkbox]')] : [];
  check(cbs.length === 2 && cbs.every(x => x.disabled && !x.dataset.mdline) && cbs[1].checked && c1.querySelector('.cbody b') && c1.querySelector('.cbody code'), 'N4: checkboxes read-only in a comment, bold + code');
  const c2 = cms.find(c => /Second note/.test(c.textContent));
  check(c2 && c2.classList.contains('grp') && !c1.classList.contains('grp'), 'F5: the second comment of the same agent in a row is grouped under the first');
  check(c1.querySelector('.cmrxq [data-act="c-react"][data-e="up"]') && !c1.querySelector('.rxbar:not(.cmrxq) .rx.add'), 'F5: the quick reactions sit in the hover bar, not as a row under every comment');
  const ty = d.querySelector('#d-typing');
  check(ty && !ty.classList.contains('hidden') && /Claude is working on it/.test(ty.textContent) && !/writing/.test(ty.textContent) && !ty.querySelector('.atdots'), 'F6: an agent "working" on the task: "is working on it", no typing dots ' + (ty?.textContent || ''));
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelector('#chat-msgs .cbub .mdc'), 60);
  const cb = [...d.querySelectorAll('#chat-msgs .cmsg.ag .cbub')].pop();
  check(cb && cb.querySelector('h5') && cb.querySelectorAll('li').length === 4 && cb.querySelector('input[disabled]'), 'N4: an agent chat message renders the same Markdown');
  await tcall('PUT', '/agent/status', TOK, {status: 'idle'});
  w.eval('chatClose()'); w.close();

  // ================= N1 (logic): no room for list + task + chat: the task takes the chat's place, a button brings it back
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`chatOpen(${AG})`); await sleep(600);
  w.eval(`openDetail(${T[0]})`); await sleep(500);
  check(d.body.classList.contains('chat-yield') && d.querySelector('#detail .dchatb'), `N1: ${w.innerWidth} px: the task takes the chat's place (body.chat-yield), with a chat button in its header`);
  click(w, d.querySelector('#detail .dchatb')); await sleep(400);
  check(!w.eval('S.sel') && !d.body.classList.contains('chat-yield') && d.body.classList.contains('chat-open'), 'N1: the chat button closes the task, the chat is back');
  w.eval(`openDetail(${T[0]})`); await sleep(300);
  w.eval(`chatOpen(${AG})`); await sleep(300);
  check(!w.eval('S.sel') && !d.body.classList.contains('chat-yield'), 'N1: opening the chat (agent pill, person card) closes the task in its place');
  // N9 (logic): the pill and Send do not take the focus from the chat box
  const ci = d.querySelector('#chat-in'); ci.focus();
  const md1 = new w.MouseEvent('mousedown', {bubbles: true, cancelable: true}); d.querySelector('#chat-new').dispatchEvent(md1);
  const md2 = new w.MouseEvent('mousedown', {bubbles: true, cancelable: true}); d.querySelector('[data-act="chat-send"]').dispatchEvent(md2);
  check(md1.defaultPrevented && md2.defaultPrevented && d.activeElement === ci, 'N9: a press on "New message" / Send keeps the focus in the chat box');
  w.eval('chatClose()'); w.close();

  // ================= N7 + F14: a waiting job once in Today; the card stays when the Agents module (tab) is off
  const J = (await tcall('POST', '/agent/jobs', TOK, {title: 'Publish page 1', task_id: T[0], state: 'waiting', log: 'ready'})).id;
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#view .waitcard'), 60); await sleep(300);
  check(d.querySelector('#view .waitcard') && d.querySelector('#view .agband') && !d.querySelector('#view .agband .agb-w'), 'N7: Today on a desktop: the card "1 job waits for you", the agent band without the same approval');
  // N2: a re-render of the view keeps the keyboard focus on the band cell (no ping-pong to the start)
  const cell = d.querySelector('#view .agband [data-act="team-agent"]'); cell.focus();
  w.eval('renderView()');
  const f1 = d.activeElement;
  check(f1 && f1.isConnected && f1.matches(`#view .agband [data-act="team-agent"][data-aid="${AG}"]`) && d.querySelector('#view .waitcard'), 'N2: after a live re-render the focus is still on the band cell (the area is morphed, not rebuilt)');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  await w.eval(`setListView(listById(${P}), 'list')`); await sleep(500);
  check(await until(() => d.querySelector('#view .agband .agb-w')), 'N7: in a list the band still shows the waiting job');
  w.eval(`openDetail(${T[0]})`); await sleep(600);
  const pin = d.querySelector('#detail [data-act="pin"]'); pin.focus(); w.eval('renderDetail()');
  check(d.activeElement?.isConnected && d.activeElement?.matches('#detail [data-act="pin"]'), 'N2: a re-render of the task panel keeps the focus on the same button');
  // F7: the calm conflict bar is shown: no toast saying the same
  const dc = d.querySelector('#d-content'); dc.classList.remove('hidden'); dc.focus();
  w.eval(`(() => { const c = {field: 'content', server: 'theirs', mine: 'mine'}; addConflicts(${T[0]}, [c], 'Page 1'); cfInline(${T[0]}, 'content', c, 'mine'); })()`); await sleep(600);
  check(d.querySelector('#detail .cfbar') && !/changed elsewhere in the meantime, please review/.test(d.querySelector('#toast')?.textContent || ''), 'F7: the conflict bar under the field, no toast on top of it');
  dc.blur(); w.eval('S.conflicts = []; LS.set("conflicts", [])'); w.close();
  await call('PATCH', '/api/settings', {features: ALL.replace(',agents', '')});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(await until(() => d.querySelector('#view .waitcard'), 60) && !d.querySelector('#view .agband'), 'F14: Agents module (tab) off: the approval card stays (like the agent pill), no band');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});
  await tcall('PATCH', `/agent/jobs/${J}`, TOK, {state: 'done'});

  // ================= F4: "#id" + Enter in the search opens the task
  w = await boot({user: 'alice', hash: 'search'}); d = w.document;
  const sq = await until(() => d.querySelector('#searchq'));
  sq.value = '#' + T[2]; sq.dispatchEvent(new w.Event('input', {bubbles: true}));
  sq.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
  check(await until(() => w.eval('S.sel') === T[2]), 'F4: "#id" + Enter opens that task');
  w.close();

  // ================= F9: the column menus of the Kanban board have a name
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  await w.eval(`setListView(listById(${P}), 'kanban')`); await sleep(600);
  const sm = [...d.querySelectorAll('#view [data-act="section-menu"]')];
  check(sm.length === 2 && sm.every(b => /^More: /.test(b.getAttribute('aria-label') || '')), 'F9: Kanban column "…" buttons are labelled: ' + sm.map(b => b.getAttribute('aria-label')).join(' | '));
  await w.eval(`setListView(listById(${P}), 'list')`); await sleep(300);
  w.close();

  // ================= N5: 75-150 %; a stored 50 counts as 75
  w = await boot({user: 'alice', hash: 'today', ls: {'tasks.fsize': '50'}}); d = w.document;
  check(w.eval('fsPct()') === 75 && Math.abs(w.eval('uiZ()') - .75) < 1e-9, 'N5: a stored 50 % (2.13.0 / 2.13.1) counts as 75 %');
  w.eval(`settingsModal('look')`); await sleep(500);
  check(d.querySelector('#s-fsize')?.min === '75' && d.querySelector('#s-fsize')?.max === '150', 'N5: the slider goes from 75 to 150 %');
  w.eval('fsStep(-5)');
  check(w.eval('fsPct()') === 75, 'N5: Ctrl - stops at 75 %');
  w.close();
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));

  // ================= Firefox
  for (let i = 0; i < 40; i++) await tcall('POST', `/agent/chats/${ME}`, TOK, {body: `Answer ${i + 1}: some text that is long enough to make the chat scroll on every screen size`});
  const ffLogin = async ({ev, nav}, theme = 'light', ls = {}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); ${Object.entries(ls).map(([k, v]) => `localStorage.setItem(${JSON.stringify(k)}, ${JSON.stringify(v)});`).join(' ')} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const VVSIM = `(() => { const vv = window.visualViewport; window.__kb = {h: null, t: 0};
    Object.defineProperty(vv, 'height', {configurable: true, get: () => window.__kb.h ?? innerHeight});
    Object.defineProperty(vv, 'offsetTop', {configurable: true, get: () => window.__kb.t});
    window.__setKb = (hh, t) => { window.__kb.h = hh; window.__kb.t = t; vv.dispatchEvent(new Event('resize')); vv.dispatchEvent(new Event('scroll')); return 1; };
    return 1; })()`;

  // ---- desktop 1440 / 1920, mouse: N1 side by side, N10 pinned on resize, N2 Tab through the band with live updates
  for (const vw of [1440, 1920]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}) === 200, vw + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 900}});
    await nav(B + '#l/' + P); await ready(ev);
    await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1500);
    await ev(`(() => { openDetail(${T[0]}); return 1; })()`); await sleep(1200);
    const g = await ev(`(() => { const r = s => { const e = document.querySelector(s); if (!e || getComputedStyle(e).display === 'none') return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), w: Math.round(b.width)}; }; return {main: r('#main'), det: r('#detail'), chat: r('#achat'), yld: document.body.classList.contains('chat-yield')}; })()`);
    check(g.main && g.det && g.chat && !g.yld && g.det.r <= g.chat.l + 1 && g.det.l - g.main.r <= 2 && g.main.w >= 420, `${vw} N1: list | task | chat side by side, nothing under the chat, no gap ` + JSON.stringify(g));
    await shot(`p2132-${vw}-list-task-chat.png`);
    // N10: the panel stays at the bottom when the window gets lower
    await ev(`(() => { closeDetail(); const b = document.querySelector('#chat-msgs'); b.scrollTop = b.scrollHeight; return 1; })()`); await sleep(400);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 560}}); await sleep(900);
    const pb = await ev(`(() => { const b = document.querySelector('#chat-msgs'); return {gap: Math.round(b.scrollHeight - b.scrollTop - b.clientHeight), h: b.clientHeight}; })()`);
    check(pb.gap <= 4, `${vw} N10: the chat panel stays at the bottom when the window gets lower ` + JSON.stringify(pb));
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 900}}); await sleep(600);
    await ev(`(() => { chatClose(); return 1; })()`); await sleep(300);
    if (vw !== 1440) return;
    // N1 at 1100: no room for all three: the task replaces the chat, its chat button brings the chat back
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1100, height: 800}}); await sleep(500);
    await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1000);
    await ev(`(() => { openDetail(${T[0]}); return 1; })()`); await sleep(1000);
    const y = await ev(`(() => { const c = document.querySelector('#achat'), b = document.querySelector('#detail .dchatb'), d = document.querySelector('#detail').getBoundingClientRect(); return {yld: document.body.classList.contains('chat-yield'), chatHidden: getComputedStyle(c).display === 'none', btn: !!b && getComputedStyle(b).display !== 'none', detR: Math.round(d.right), vw: innerWidth}; })()`);
    check(y.yld && y.chatHidden && y.btn && y.detR <= y.vw + 1, '1100 N1: the task takes the chat\'s place, the chat button is in its header ' + JSON.stringify(y));
    await shot('p2132-1100-task-instead-of-chat.png');
    await ev(`(() => { document.querySelector('#detail .dchatb').click(); return 1; })()`); await sleep(700);
    const y2 = await ev(`(() => ({sel: S.sel, chat: getComputedStyle(document.querySelector('#achat')).display !== 'none', focus: document.activeElement?.id}))()`);
    check(!y2.sel && y2.chat && y2.focus === 'chat-in', '1100 N1: back to the chat, its box has the focus ' + JSON.stringify(y2));
    await ev(`(() => { chatClose(); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}}); await sleep(500);
    // N2: Tab through the agent band while the agent's status changes (live re-renders): the focus walks on. 2.31.0
    // (#1052): Today shows the band only when something needs me, so this runs in the project list (band always there)
    const J2 = (await tcall('POST', '/agent/jobs', TOK, {title: 'Approve me', state: 'waiting'})).id;
    await nav(B + '#l/' + P); await ready(ev); await sleep(800);
    await ev(`(() => { document.querySelector('#view .agband .agb-tog').focus(); return 1; })()`);
    const seen = [];
    const id = () => ev(`(() => { const a = document.activeElement; return a ? (a.dataset.act || a.id || a.tagName) + ':' + (a.dataset.jid || a.dataset.aid || '') + ':' + [...document.querySelectorAll('button, a, input')].indexOf(a) : '-'; })()`);
    for (let i = 0; i < 4; i++) {
      await tcall('PUT', '/agent/status', TOK, {status: i % 2 ? 'idle' : 'working', text: 'step ' + i});
      await ev(`load().then(() => { render(); return 1; })`); await sleep(250);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: ''}, {type: 'keyUp', value: ''}]}]});
      await sleep(150); seen.push(await id());
    }
    check(new Set(seen).size === seen.length && seen.every(s => s !== '-' && !/^BODY/.test(s)), 'N2: Tab moves on through live re-renders (no ping-pong): ' + seen.join(' > '));
    await tcall('PATCH', `/agent/jobs/${J2}`, TOK, {state: 'done'});
    await tcall('PUT', '/agent/status', TOK, {status: 'idle'});
    // F1: Kanban cards of a long column never run into each other
    await nav(B + '#l/' + P); await ready(ev);
    await ev(`setListView(listById(${P}), 'kanban').then(() => 1)`); await sleep(1200);
    const ov = await ev(`(() => { const col = document.querySelector('#view .kcol .kcards'); const r = [...col.children].map(x => x.getBoundingClientRect()); let bad = 0; for (let i = 1; i < r.length; i++) if (r[i].top < r[i - 1].bottom - 1) bad++; return {n: r.length, bad, two: r.some(x => x.height > 50)}; })()`);
    check(ov.n >= 20 && ov.bad === 0, 'F1: Kanban: cards of a long column do not overlap ' + JSON.stringify(ov));
    await shot('p2132-1440-kanban.png');
    await ev(`setListView(listById(${P}), 'list').then(() => 1)`); await sleep(400);
  }, false);

  // ---- Fold 904 touch, dark, French: N3 fold / unfold with a half-typed quick add, F3 matrix at 904 x 680, F2 numbers
  await call('PATCH', '/api/settings', {lang: 'fr'});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}, 'dark', {[`tasks.ids.${P}`]: 'true'}) === 200, 'Fold: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 904}});
    await nav(B + '#today'); await ready(ev);
    const q0 = await ev(`(() => { const q = document.querySelector('#qinput'); if (!q || !q.offsetParent) return false; q.focus(); q.value = 'Half typed task'; q.dispatchEvent(new Event('input', {bubbles: true})); q.setSelectionRange(4, 4); return true; })()`);
    check(q0, 'Fold 904: the "Add task" box is there');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 412, height: 904}}); await sleep(1200);
    const q1 = await ev(`(() => { const s = document.querySelector('#qsheet'); return {sheet: !!s, val: s && s.value, focus: document.activeElement?.id, caret: s && s.selectionStart}; })()`);
    check(q1.sheet && q1.val === 'Half typed task' && q1.focus === 'qsheet', 'N3: folding: the half-typed text moves into the phone\'s quick sheet with the focus ' + JSON.stringify(q1));
    await shot('p2132-fold-folded-quick.png');
    await ev(`(() => { const s = document.querySelector('#qsheet'); s.value += ' and more'; s.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 904}}); await sleep(1200);
    const q2 = await ev(`(() => { const q = document.querySelector('#qinput'); return {val: q && q.value, sheet: !!document.querySelector('#qsheet'), focus: document.activeElement?.id}; })()`);
    check(q2.val === 'Half typed task and more' && !q2.sheet && q2.focus === 'qinput', 'N3: unfolding: the text is back in the box, the sheet closed, focus kept ' + JSON.stringify(q2));
    await ev(`(() => { const q = document.querySelector('#qinput'); q.value = ''; q.blur(); return 1; })()`);
    // N3 inside the phone layout: a tablet / Fold portrait (880 px, docked box) folded to 390 never crosses 899 px
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 880, height: 904}}); await sleep(900);
    const q3 = await ev(`(() => { const q = document.querySelector('#qinput'); if (!q || !q.offsetParent) return false; q.focus(); q.value = 'Docked draft'; q.dispatchEvent(new Event('input', {bubbles: true})); return true; })()`);
    if (q3) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}}); await sleep(1200);
      const q4 = await ev(`(() => { const s = document.querySelector('#qsheet'); return {sheet: !!s, val: s && s.value, focus: document.activeElement?.id}; })()`);
      check(q4.sheet && q4.val === 'Docked draft' && q4.focus === 'qsheet', 'N3: 880 (docked box) -> 390: the text moves into the quick sheet ' + JSON.stringify(q4));
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 880, height: 904}}); await sleep(1200);
      const q5 = await ev(`(() => { const q = document.querySelector('#qinput'); return {val: q && q.value, sheet: !!document.querySelector('#qsheet')}; })()`);
      check(q5.val === 'Docked draft' && !q5.sheet, 'N3: 390 -> 880: back in the docked box ' + JSON.stringify(q5));
      // a keyboard (only the height changes) never moves it
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 880, height: 500}}); await sleep(900);
      check(!(await ev(`!!document.querySelector('#qsheet')`)), 'N3: a keyboard (height only) never moves the text into the sheet');
      await ev(`(() => { const q = document.querySelector('#qinput'); if (q) { q.value = ''; q.blur(); } return 1; })()`);
    } else console.log('p2132_ui: no docked box at 880 x 904 (viewport rule), 880 -> 390 part skipped');
    // F3: the matrix at 904 x 680 in French: all quadrants on screen, no horizontal scroll
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 680}});
    await nav(B + '#matrix'); await ready(ev); await sleep(500);
    const mx = await ev(`(() => { const v = document.querySelector('#view'), q = [...document.querySelectorAll('#view .quad')].map(x => x.getBoundingClientRect()); const vr = v.getBoundingClientRect(); return {n: q.length, over: v.scrollWidth - v.clientWidth, right: Math.round(Math.max(...q.map(x => x.right))), vr: Math.round(vr.right)}; })()`);
    check(mx.n === 4 && mx.over <= 1 && mx.right <= mx.vr, 'F3: matrix 904 x 680 (fr): the quadrants fit, no horizontal scroll ' + JSON.stringify(mx));
    await shot('p2132-fold-matrix-fr.png');
    // F2: the task number in a Kanban card is a compact label, not a 3rem column
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 904}});
    await nav(B + '#l/' + P); await ready(ev);
    await ev(`setListView(listById(${P}), 'kanban').then(() => 1)`); await sleep(1000);
    const gw = await ev(`(() => { const g = document.querySelector('#view .kcards .tgut'); if (!g) return null; const r = g.getBoundingClientRect(), t = g.parentElement.querySelector('.tmain, .ttl').getBoundingClientRect(); return {w: Math.round(r.width), gap: Math.round(t.left - r.right)}; })()`);
    check(gw && gw.w < 40 && gw.gap <= 12, 'F2: the number in a card is compact ' + JSON.stringify(gw));
    await ev(`setListView(listById(${P}), 'list').then(() => 1)`); await sleep(300);
  }, true);
  await call('PATCH', '/api/settings', {lang: 'de'});

  // ---- phones 390 / 428 touch, German: N8 iOS keyboard pushes the page, N9 pill + Send keep the keyboard, F8, F11, F13,
  // helper texts, N5 round circles at 75 %
  for (const vw of [390, 428]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    const vh = vw === 390 ? 844 : 926;
    check(await ffLogin({ev, nav}) === 200, vw + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    const tap = (x, y) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    const rect = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
    await nav(B + '#agents/' + AG); await ready(ev); await sleep(800);
    await ev(VVSIM);
    const ci = await rect('#chat-in'); await tap(ci.x, ci.y); await sleep(300);
    await ev(`__setKb(${Math.round(vh * .6)}, 260)`); await sleep(700);
    const kb = await ev(`(() => { const h = document.querySelector('.chview .chath').getBoundingClientRect(), i = document.querySelector('#chat-in').getBoundingClientRect(), vv = visualViewport, m = document.querySelector('#chat-msgs'); return {hTop: Math.round(h.top), hBot: Math.round(h.bottom), inBot: Math.round(i.bottom), visTop: vv.offsetTop, visBot: vv.offsetTop + vv.height, fix: document.querySelector('.chview').classList.contains('vvfix'), atBottom: m.scrollHeight - m.scrollTop - m.clientHeight < 8, focus: document.activeElement.id}; })()`);
    check(kb.fix && kb.hTop >= kb.visTop - 1 && kb.hBot > kb.visTop + 5 && kb.inBot <= kb.visBot + 1 && kb.atBottom && kb.focus === 'chat-in', `${vw} N8: iOS keyboard pushed the page (offsetTop 260): header with Back, newest message and the box are in view ` + JSON.stringify(kb));
    await shot(`p2132-${vw}-ios-kb-pushed.png`);
    // N9: the pill and Send keep the focus (the keyboard stays)
    // the pill for real: scrolled up, an answer arrives (a pill shown by hand could be hidden again by the next refresh)
    await ev(`(() => { const b = document.querySelector('#chat-msgs'); b.scrollTop = 0; b.dispatchEvent(new Event('scroll')); return 1; })()`); await sleep(200);
    await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'An answer while you read above (' + vw + ')'});
    await ev(`chatLoad().then(() => 1)`); await sleep(300);
    const pv = await ev(`(() => ({pill: !document.querySelector('#chat-new').classList.contains('hidden'), focus: document.activeElement.id}))()`);
    check(pv.pill && pv.focus === 'chat-in', `${vw} N9: scrolled up + an answer: "New message ↓" shows, the box keeps the focus ` + JSON.stringify(pv));
    const pl = await rect('#chat-new'); await tap(pl.x, pl.y); await sleep(400);
    check(await ev(`document.activeElement.id`) === 'chat-in', `${vw} N9: a tap on "New message ↓" keeps the keyboard (focus in the box)`);
    await ev(`(() => { const t = document.querySelector('#chat-in'); t.focus(); t.value = 'Hello'; t.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const sb = await rect('[data-act="chat-send"]'); await tap(sb.x, sb.y); await sleep(1500);
    const af = await ev(`(() => ({focus: document.activeElement.id, val: document.querySelector('#chat-in').value, last: [...document.querySelectorAll('#chat-msgs .cmsg.me')].pop()?.textContent || ''}))()`);
    check(af.focus === 'chat-in' && af.val === '' && /Hello/.test(af.last), `${vw} N9: Send sends and keeps the keyboard ` + JSON.stringify(af));
    await ev(`(() => { document.activeElement.blur(); __setKb(null, 0); return 1; })()`); await sleep(500);
    check(!(await ev(`document.querySelector('.chview').classList.contains('vvfix')`)), `${vw} N8: keyboard down: the chat is back in the page`);
    if (vw !== 390) return;
    // F8: offline while a task is open: said in the task's header
    await nav(B + '#l/' + P); await ready(ev);
    await ev(`(() => { openDetail(${T[0]}); return 1; })()`); await sleep(900);
    // offline for the app (the 4 s change check must not switch it back to online in between)
    await ev(`(() => { Object.defineProperty(OUT, 'online', {configurable: true, get: () => false, set() {}}); staleDraw(); return 1; })()`); await sleep(200);
    const of = await ev(`(() => { const s = document.querySelector('#stale'); const r = s && s.getBoundingClientRect(); return {inHead: !!s && !!s.closest('#detail .dtop'), vis: !!r && r.width > 0 && r.top >= 0 && r.bottom <= innerHeight, txt: s ? s.textContent : ''}; })()`);
    check(of.inHead && of.vis && /Offline/.test(of.txt), '390 F8: offline with a task open: "Offline" in the task header ' + JSON.stringify(of));
    await shot('p2132-390-detail-offline.png');
    await ev(`(() => { delete OUT.online; OUT.online = true; closeDetail(); return 1; })()`);
    for (let i = 0; i < 30 && await ev(`!!(history.state && history.state.detail)`).catch(() => true); i++) await sleep(100);
    await sleep(300);
    // F11: 44 px for "Set status" and the assignee pictures' hit area
    const t11 = await ev(`(() => { const b = document.createElement('button'); b.className = 'stpill none'; b.textContent = 'Status'; document.body.appendChild(b); const h = b.getBoundingClientRect().height; b.remove();
      const w = document.createElement('button'); w.className = 'whob'; document.body.appendChild(w); const a = getComputedStyle(w, '::after'); const ins = parseFloat(a.top); w.remove(); return {stpill: h, whob: ins}; })()`);
    check(t11.stpill >= 43.5 && t11.whob <= -9.5, '390 F11: "Set status" 44 px high, assignee pictures with a 44 px hit area ' + JSON.stringify(t11));
    // F13 + helper texts: Settings on the phone
    await ev(`(() => { settingsModal('integr'); return 1; })()`); await sleep(1200);
    const sn = await ev(`(() => { const b = document.querySelector('.snmore'); return {more: !!b && !b.classList.contains('hidden') && getComputedStyle(b).display !== 'none'}; })()`);
    check(sn.more, '390 F13: the cut settings tab strip shows "More ›"');
    const CNT = `(() => { const vis = e => e.offsetWidth && e.offsetHeight && getComputedStyle(e).visibility !== 'hidden'; const root = document.querySelector('.smodal');
      const hs = [...root.querySelectorAll('.shint:not(.iisrc), .mhint, p.muted, div.muted')].filter(vis).filter(e => !e.closest('button') && e.textContent.trim().length > 25);
      return hs.filter(e => !hs.some(o => o !== e && o.contains(e))).length; })()`;
    const ni = await ev(CNT);
    check(ni <= 4, '390 helper texts: Integrations has at most 4 inline texts (was 9): ' + ni);
    await shot('p2132-390-settings-integr.png');
    await ev(`(() => { const n = document.querySelector('.snav'); n.scrollLeft = n.scrollWidth; return 1; })()`); await sleep(400);
    check(await ev(`document.querySelector('.snmore').classList.contains('hidden')`), '390 F13: at the end of the strip "More ›" goes');
    await ev(`(() => { document.querySelector('.snav [data-sec="users"]').click(); return 1; })()`); await sleep(1500);
    const nu = await ev(CNT);
    check(nu <= 4, '390 helper texts: Administration has at most 4 inline texts (was 8): ' + nu);
    await ev(`(() => { document.querySelectorAll('.modal:not(.authscreen)').forEach(x => x.remove()); return 1; })()`);
    // N5: 75 %: the done circles stay round (no 7 x 44 ovals)
    await ev(`(() => { LS.set('fsize', 75); applyLook(); render(); return 1; })()`); await sleep(600);
    const ck = await ev(`(() => { const c = document.querySelector('#view .trow .chk'); const r = c.getBoundingClientRect(); const fs = Math.min(...[...document.querySelectorAll('#view .trow .ttl, #view .trow .meta span')].filter(x => x.offsetWidth).map(x => parseFloat(getComputedStyle(x).fontSize))); return {w: r.width, h: r.height, fs}; })()`);
    check(Math.abs(ck.w - ck.h) < .5 && ck.w > 8 && ck.fs >= 9, '390 N5: at 75 % the done circles stay round, text at least 9 px ' + JSON.stringify(ck));
    await shot('p2132-390-font-75.png');
    await ev(`(() => { LS.del('fsize'); applyLook(); return 1; })()`);
  }, true);

  console.log(`p2132_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
