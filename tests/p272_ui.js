// 2.7.2 UI tests, own container (start.sh, isolated test database). jsdom: #414 two list types + "Show completed at the
// bottom" (list dialog, sort menu, "…", the Done group with full rows), #417 the robot + dots directly before the bell,
// #418 pictures open the person card (assignee, members, chat; "Tasks of …" = the filtered view, agents: chat + current
// task), #424 breadcrumbs in the task panel (folder › list › section › parent, each jumps there), #421 reactions in the agent
// chat (👍 = approval), #422 Sent / Delivered / typing dots without the agent's help / "offline – answers later", #420
// Settings > Agents > Set up (personal agents, the admin switch, guides per OS), milestones in the "All" timeline, drag &
// drop into the project files, the viewport fix (the keyboard never flips the layout while typing); SW v76.
// Then Firefox headless (WebDriver BiDi, shared helper ff.js), touch at 360 x 780 / 390 x 844, a mouse at 1280 x 800 /
// 1920 x 1080: "…", the robot and the bell in view (robot right before the bell), the breadcrumbs inside the panel, the chat
// reactions, 44 px touch targets, the focus of the add box survives a keyboard-sized viewport; screenshots with P272_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p272_ui', check, shots: 'P272_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const HEAD = `(() => {
  const t = document.querySelector('#top'); if (!t || !t.querySelector('h1')) return {none: location.href};
  const vw = document.documentElement.clientWidth;
  const R = e => { if (!e || !e.offsetWidth) return null; const b = e.getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom, b.width, b.height]; };
  const out = [...t.children].filter(e => e.offsetWidth && e.getBoundingClientRect().right > vw + 0.5).map(e => e.className || e.tagName);
  const vis = [...t.children].filter(e => e.offsetWidth);
  const bell = t.querySelector('.bell'), i = vis.indexOf(bell), prev = vis[i - 1];
  return {vw, more: R(t.querySelector('[data-act="top-more"]')), bell: R(bell), bot: R(t.querySelector('.abot')), prev: prev ? prev.className : '', out};
})()`;
const SMALL = sel => `(() => [...document.querySelectorAll('${sel}')].filter(e => e.offsetWidth && getComputedStyle(e).visibility !== 'hidden').map(e => {
  const b = e.getBoundingClientRect(); let w = b.width, h = b.height;
  for (const ps of ['::before', '::after']) { const s = getComputedStyle(e, ps); if (s.content && s.content !== 'none' && s.position === 'absolute') { const iw = b.width - parseFloat(s.left || 0) - parseFloat(s.right || 0), ih = b.height - parseFloat(s.top || 0) - parseFloat(s.bottom || 0); if (Number.isFinite(iw)) w = Math.max(w, iw); if (Number.isFinite(ih)) h = Math.max(h, ih); } }
  return [e.className || e.tagName, (e.textContent || '').trim().slice(0, 16), Math.round(w), Math.round(h)]; }).filter(x => x[2] < 43.5 || x[3] < 43.5))()`;

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:7[6-9]|8[0-9])'/.test(SW), 'service worker cache v76 (2.8.0: v77, 2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project', folder: 'Clients'})).id;
  const SH = (await call('POST', '/api/lists', {name: 'Groceries'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  const SEC = (await call('POST', '/api/sections', {list_id: P, name: 'Design'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Wireframes', list_id: P, section_id: SEC, assignee_id: BOB, due: day(2)})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Header sketch', list_id: P, section_id: SEC, parent_id: T1})).id;
  await call('POST', `/api/lists/${P}/milestones`, {name: 'Beta', day: day(5)});
  const M1 = (await call('POST', '/api/tasks', {title: 'Milk', list_id: SH, due: day(1)})).id;
  await call('POST', `/api/tasks/${M1}/complete`);
  await call('POST', '/api/tasks', {title: 'Bread', list_id: SH});

  // ================= #414 two types + "Show completed at the bottom"
  let w = await boot({user: 'alice', hash: 'l/' + SH}), d = w.document;
  check(w.eval('LKINDS.map(x => x[0]).join()') === 'list,project', 'two list types');
  w.eval(`listModal(${SH})`); await sleep(200);
  let md = d.querySelector('.modal.lmodal');
  check(md && [...md.querySelectorAll('#l-kind option')].map(o => o.value).join() === 'list,project' && md.querySelector('#l-dab') && !md.querySelector('#l-dab').checked, 'list dialog: List / Project + "Show completed at the bottom" (off)');
  md.querySelector('#l-dab').checked = true; md.querySelector('#l-dab').dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === SH).checklist === 1);
  check((await call('GET', '/api/state')).lists.find(l => l.id === SH).checklist === 1, 'the dialog saves the option');
  click(w, md.querySelector('[data-m="close"]')); await sleep(300);
  check(await until(() => d.querySelector('#view .group.ckdone')), 'the Done group at the bottom');
  const dn = d.querySelector('#view .group.ckdone');
  check(/Milk/.test(dn.textContent) && dn.querySelector('.ckback'), 'done item at the bottom, one tap puts it back');
  check(!d.querySelector('#view .trow.ck') && d.querySelector('#view .group.ckdone .trow .dt'), 'rows are full tasks (the date stays)');
  const more = w.eval('topMoreItems()').map(x => x.label);
  check(more.includes('Show completed at the bottom'), '"…" offers the option: ' + more.slice(0, 8));
  w.eval(`sortMenu(document.querySelector('#top h1'))`); await sleep(100);
  check([...d.querySelectorAll('#pop .dabitem')].length === 1, 'the sort menu offers it too');
  w.eval('closePop()');
  w.eval(`setDab(${SH}, false)`);
  await until(() => !d.querySelector('#view .group.ckdone'));
  check(!d.querySelector('#view .group.ckdone') && (await call('GET', '/api/state')).lists.find(l => l.id === SH).checklist === 0, 'switched off from the menu');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + SH}); d = w.document;
  check(w.eval('topMoreItems()').some(x => x.label === 'Erledigte unten zeigen'), 'de: Erledigte unten zeigen');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #417 robot before the bell (2.8.0: the dots in the agent band where it shows, here the list has one)
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  let chip = d.querySelector('#top .achip');
  check(chip && chip.querySelector('.abot') && !chip.querySelector('.hdot') && d.querySelector('#view .agband .hdot'), 'the robot in the header, the agents\' dots in the band');
  check(chip && chip.nextElementSibling === d.querySelector('#top .bell'), 'directly before the bell');
  // ================= #424 breadcrumbs
  w.eval(`openDetail(${T2})`); await sleep(300);
  let cr = [...d.querySelectorAll('#detail .dcrumbs .dcb')];
  check(cr.map(b => b.dataset.k).join() === 'folder,list,sec,parent' && cr.map(b => b.textContent).join('|') === 'Clients|Website|Design|Wireframes', 'breadcrumbs: ' + cr.map(b => b.textContent).join('|'));
  w.eval(`go('today')`); await sleep(300);
  w.eval(`openDetail(${T1})`); await sleep(300);
  click(w, [...d.querySelectorAll('#detail .dcb')].find(b => b.dataset.k === 'sec')); await sleep(500);
  check(w.eval('S.route.key') === 'l:' + P, 'the section crumb opens the list');
  w.eval(`openDetail(${T2})`); await sleep(300);
  click(w, [...d.querySelectorAll('#detail .dcb')].find(b => b.dataset.k === 'folder')); await sleep(400);
  check(w.eval('S.route.key') === 'folder:Clients', 'the folder crumb opens the folder');
  // ================= #418 person cards
  w.eval(`go('l/${P}')`); await sleep(400);
  // the assignee column: its menu starts with "Show Bob"; without the column the picture itself is the button
  click(w, d.querySelector(`#view .trow[data-id="${T1}"] [data-act="assign"]`)); await sleep(200);
  const show = [...d.querySelectorAll('#pop .mshow, #pop button')].find(b => /Show Bob/.test(b.textContent));
  check(show, 'assignee menu: "Show Bob" first');
  click(w, show); await sleep(200);
  let card = d.querySelector('#pop .mcard');
  check(card && /Bob/.test(card.textContent), 'from the assignee menu: the card');
  w.eval('closePop()');
  w.eval(`LS.set('acol.${P}', false); render()`); await sleep(200);
  const pic = d.querySelector(`#view .trow[data-id="${T1}"] .avb[data-mcard="${BOB}"]`);
  check(pic, 'the assignee picture is a button (mouse, no column)');
  click(w, pic); await sleep(200);
  card = d.querySelector('#pop .mcard');
  check(card && /Bob/.test(card.textContent) && card.querySelector('[data-mc="who"]'), 'person card with "Tasks of Bob"');
  check(!d.querySelector('#detail:not(.hidden) .dtitle') || w.eval('S.sel') !== T1, 'the click did not open the task');
  click(w, card.querySelector('[data-mc="who"]')); await sleep(400);
  check(w.eval('S.route.key') === 'who:' + BOB && d.querySelector('#top h1 .ht').textContent === 'Tasks of Bob', 'the filtered view "Tasks of Bob"');
  check([...d.querySelectorAll('#view .trow')].some(r => +r.dataset.id === T1) && ![...d.querySelectorAll('#view .trow')].some(r => +r.dataset.id === M1), 'only Bob\'s tasks');
  await tcall('PUT', '/agent/status', TOK, {status: 'working', text: 'Wireframes', task_id: T1});
  w.close();
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  const apic = await until(() => d.querySelector(`.avb[data-mcard="${AG}"]`));
  check(apic, 'the agent\'s picture is a button');
  click(w, apic); await sleep(200);
  card = d.querySelector('#pop .mcard');
  check(card && card.querySelector('[data-mc="chat"]') && /Working on/.test(card.textContent) && /Wireframes/.test(card.textContent) && !card.querySelector('[data-mc="who"]'), 'agent card: chat + current task');
  w.eval('closePop()');
  // members in the share dialog
  w.eval(`shareModal(${P})`); await sleep(500);
  check(d.querySelector(`.modal .mrow .avb[data-mcard="${BOB}"]`), 'members: pictures are buttons');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  w.close();

  // ================= #421 #422 chat
  await tcall('PUT', '/agent/status', TOK, {status: 'idle'});
  const cur = (await tcall('GET', '/agent/events?since=0', TOK)).cursor;  // the agent polls: online
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`chatOpen(${AG})`); await sleep(400);
  d.querySelector('#chat-in').value = 'Ready for review?';
  w.eval('chatSend()'); await sleep(400);
  let mine = [...d.querySelectorAll('#chat-msgs .cmsg.me')].pop();
  check(mine && /Sent/.test(mine.querySelector('.cdlv')?.textContent || '') && !mine.querySelector('.cdlv.on'), 'my message: Sent');
  check(d.activeElement?.id === 'chat-in', 'the box keeps its focus after sending (desktop)');
  await tcall('GET', `/agent/events?since=${cur}`, TOK);  // the agent fetches it
  await w.eval('chatLoad()'); await sleep(200);
  mine = [...d.querySelectorAll('#chat-msgs .cmsg.me')].pop();
  check(mine.querySelector('.cdlv.on') && /Delivered/.test(mine.textContent), 'Delivered once the agent fetched it');
  check(!d.querySelector('#chat-typing').classList.contains('hidden'), 'typing dots by themselves while the agent is online');
  d.querySelector('#chat-in').value = 'draft text'; d.querySelector('#chat-in').focus();
  await w.eval('chatLoad()'); await sleep(100);
  check(d.activeElement?.id === 'chat-in' && d.querySelector('#chat-in').value === 'draft text', 'a refresh keeps the box, its text and its focus');
  const ans = await tcall('POST', '/agent/chats/1', TOK, {body: 'Yes. Shall I merge?'});
  await w.eval('chatLoad()'); await sleep(200);
  check(d.querySelector('#chat-typing').classList.contains('hidden'), 'answered: no more dots');
  const am = d.querySelector(`#chat-msgs .cmsg.ag[data-mid="${ans.id}"]`);
  const up = am && am.querySelector('.rx.add[data-e="up"]');
  check(up && am.querySelectorAll('.rx.add').length === 3, 'quick 👍 👎 ❤️ on the agent\'s message');
  click(w, up); await sleep(400);
  check(d.querySelector(`#chat-msgs .cmsg.ag[data-mid="${ans.id}"] .rx.on[data-e="up"]`), 'my 👍 shows');
  const evs = (await tcall('GET', `/agent/events?since=${cur}`, TOK)).data.filter(e => e.event === 'reaction');
  check(evs.length && evs[evs.length - 1].data.approval === 'approved' && evs[evs.length - 1].data.chat_message.id === ans.id, 'the agent got the approval');
  // offline (no event poll for 5 minutes): "answers later"
  w.close();
  await call('POST', `/api/agents/${AG}/chat`, {body: 'Still there?'});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`chatOpen(${AG})`); await sleep(500);
  w.eval(`Object.assign(S.agents.find(a => a.id === ${AG}), {online: false}); chatDraw()`);
  check(/offline – will answer later/.test(d.querySelector('#chat-msgs .chpend.off')?.textContent || ''), '"offline – will answer later"');
  w.close();

  // ================= #420 Settings > Agents > Set up
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(400);
  md = d.querySelector('.smodal');
  click(w, md.querySelector('[data-aisub="setup"]')); await sleep(600);
  check(md.querySelector('#s-uag') && !md.querySelector('#s-uag').checked, 'admin: the switch, off by default');
  check(md.querySelectorAll('[data-agseg="os"] [data-agsv]').length === 3 && md.querySelector('#s-agguide .agsteps li'), 'guides with Linux / macOS / Windows');
  click(w, md.querySelector('[data-agseg="os"] [data-agsv="win"]')); await sleep(100);
  check(/PowerShell|\.ps1|New-NetFirewallRule|Register-ScheduledTask/i.test(md.querySelector('#s-agguide').textContent), 'Windows: PowerShell steps');
  click(w, md.querySelector('[data-agseg="guide"] [data-agsv="own"]')); await sleep(100);
  check(/admin has to switch on/i.test(md.querySelector('#s-agguide').textContent), 'the personal guide says the admin allows it first');
  md.querySelector('#s-uag').checked = true; md.querySelector('#s-uag').dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/admin/agent-policy')).user_agents);
  check((await call('GET', '/api/admin/agent-policy')).user_agents === true, 'admin switches it on');
  w.close();
  w = await boot({user: 'bob', hash: 'l/' + P}); d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(400);
  md = d.querySelector('.smodal');
  click(w, md.querySelector('[data-aisub="setup"]')); await sleep(700);
  check(!md.querySelector('#s-uag') && md.querySelector('#myag-user'), 'Bob: the create form, no admin switch');
  md.querySelector('#myag-user').value = 'bobs-claude'; md.querySelector('#myag-name').value = 'Bob\'s Claude';
  click(w, md.querySelector('[data-myag-act="new"]')); await sleep(900);
  check(/^abk_/.test(d.querySelector('.modal:not(.smodal) #sec-val')?.value || ''), 'the token is shown once');
  check(await until(() => md.querySelector('[data-myag]')), 'his agent in the list');
  check((await call('GET', '/api/my/agents', null, CKB)).agents.length === 1, 'created on the server');
  w.close();

  // ================= milestones in the "All" timeline, drop into the project files
  w = await boot({user: 'alice', hash: 'all'}); d = w.document;
  const seg = [...d.querySelectorAll('#top [data-act="rm-view"]')];
  if (seg[1]) click(w, seg[1]);
  check(await until(() => d.querySelector('.tl.rm .rm-ms')), 'milestone markers in the "All" timeline');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + P, ls: {'tasks.pov': JSON.stringify([P])}}); d = w.document;
  await until(() => d.querySelector('#pov-files'));
  check(d.querySelector('#pov-files .povdz'), 'project files: "Or drop files here"');
  const drop = new w.Event('drop', {bubbles: true, cancelable: true});
  Object.defineProperty(drop, 'dataTransfer', {value: {types: ['Files'], files: [new w.File(['%PDF-1.4'], 'dropped.pdf', {type: 'application/pdf'})]}});
  d.querySelector('#pov-files').dispatchEvent(drop);
  check(await until(() => [...d.querySelectorAll('#pov-files .pfn')].some(x => x.textContent === 'dropped.pdf')), 'a dropped file is uploaded');
  w.close();

  // ================= the viewport fix (K13): the keyboard never changes the layout while typing
  const scr = {width: 880, height: 904, type: 'portrait-primary'};
  w = await boot({user: 'alice', hash: 'today', media: {'(pointer:coarse)': true, '(orientation: landscape)': false}, setup: x => {
    Object.defineProperty(x, 'screen', {configurable: true, value: {get width() { return scr.width; }, get height() { return scr.height; }, orientation: {get type() { return scr.type; }, addEventListener() {}}}});
  }}); d = w.document;
  const meta = () => d.querySelector('meta[name="viewport"]').getAttribute('content');
  check(/^width=900/.test(meta()), 'a near-square touch screen in portrait: width=900 (' + meta() + ')');
  const qi = d.querySelector('#qinput') || d.querySelector('#view .qadd input');
  qi.focus();
  w.matchMedia = q => ({matches: q === '(pointer:coarse)' || q === '(orientation: landscape)', addEventListener() {}, addListener() {}});  // the keyboard shrank the height
  w.eval('stableViewport()');
  check(/^width=900/.test(meta()) && d.activeElement === qi, 'keyboard up (viewport "landscape"): the meta stays, the box keeps its focus');
  scr.width = 904; scr.height = 880; scr.type = 'landscape-primary';  // really turned while typing: waits for the focus to leave
  w.eval('stableViewport()');
  check(/^width=900/.test(meta()) && d.activeElement === qi, 'turned while typing: unchanged until the focus leaves');
  qi.blur(); await sleep(50);
  check(/^width=device-width/.test(meta()), 'after typing: landscape gets the device width (' + meta() + ')');
  w.close();
  // a touch on a timeline bar (2.7.1 report: "the timeline got smaller"): the viewport changes, the meta does not
  scr.width = 880; scr.height = 904; scr.type = 'portrait-primary';
  await call('PATCH', `/api/lists/${P}`, {view: 'timeline'});
  w = await boot({user: 'alice', hash: 'l/' + P, media: {'(pointer:coarse)': true, '(orientation: landscape)': false}, setup: x => {
    Object.defineProperty(x, 'screen', {configurable: true, value: {get width() { return scr.width; }, get height() { return scr.height; }, orientation: {get type() { return scr.type; }, addEventListener() {}}}});
  }}); d = w.document;
  const m1 = meta(), bar = await until(() => d.querySelector('#view .tl-bar'));
  check(bar && /^width=900/.test(m1), 'timeline on a near-square touch screen: width=900');
  bar?.dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true}));
  w.matchMedia = q => ({matches: q === '(pointer:coarse)' || q === '(orientation: landscape)', addEventListener() {}, addListener() {}});
  w.eval('stableViewport()');
  check(meta() === m1, 'touching a bar while the viewport flips: the meta stays');
  w.close();
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});
  if (errs.length) check(false, 'JS errors: ' + [...new Set(errs)].join(' | '));

  // ================= Firefox: 360 / 390 touch, 1280 / 1920 mouse
  for (const touch of [true, false]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      check(lgi === 200, 'Firefox: login');
      let nr = 0;
      const open = async hash => { await nav(B + 'static/icon.svg'); await nav(B + '?v=' + (++nr) + '#' + hash); for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(900); };
      for (const [vw, vh] of touch ? [[360, 780], [390, 844]] : [[1280, 800], [1920, 1080]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        await open('l/' + P);
        const hd = await ev(HEAD);
        check(hd.more && hd.bell && hd.bot && hd.bell[1] <= vw + .5 && hd.more[1] <= vw + .5 && !hd.out.length, `${vw}px: "…", the robot and the bell in view ${JSON.stringify(hd)}`);
        check(/achip|stchip/.test(hd.prev), `${vw}px: the robot right before the bell (${hd.prev})`);
        await shot(`p272-head-${vw}.png`);
        // the task panel with its breadcrumbs
        await ev(`(() => { openDetail(${T2}); return 1; })()`); await sleep(600);
        const crb = await ev(`(() => { const n = document.querySelector('#detail .dcrumbs'); if (!n) return null; const r = n.getBoundingClientRect(), dr = document.querySelector('#detail').getBoundingClientRect(); return {l: r.left, r: r.right, dl: dr.left, dr: dr.right, n: n.querySelectorAll('.dcb').length, sw: n.scrollWidth, cw: n.clientWidth}; })()`);
        check(crb && crb.n === 4 && crb.l >= crb.dl - .5 && crb.r <= crb.dr + .5, `${vw}px: breadcrumbs inside the panel ${JSON.stringify(crb)}`);
        if (touch) {
          const small = await ev(SMALL('#detail .dcb'));
          check(!small.length, `${vw}px: breadcrumbs >= 44 px: ${JSON.stringify(small)}`);
        }
        await shot(`p272-crumbs-${vw}.png`);
        await ev(`(() => { closeDetail(); return 1; })()`); await sleep(300);
        // the add box keeps its focus when the viewport shrinks like for an on-screen keyboard
        // phones: "+" opens the add sheet (the path of the 2.7.1 report: "the keyboard closes at once")
        if (touch) { await ev(`(() => { document.querySelector('#fab').click(); return 1; })()`); await sleep(500); }
        const qf = await ev(`(() => { const i = ${touch} ? document.querySelector('.qadd.sheet input') : document.querySelector('#qinput'); if (!i) return null; i.focus(); return document.activeElement === i ? (i.id || i.className || 'input') : null; })()`);
        await sleep(300);
        const m0 = await ev(`document.querySelector('meta[name="viewport"]').getAttribute('content')`);
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: Math.round(Math.min(vh, vw) * 0.55)}}); await sleep(600);
        const kf = await ev(`(() => ({tag: document.activeElement && document.activeElement.tagName, meta: document.querySelector('meta[name="viewport"]').getAttribute('content')}))()`);
        check(qf && kf.tag === 'INPUT' && kf.meta === m0, `${vw}px: keyboard-sized viewport: the box keeps its focus, the meta stays ${JSON.stringify({qf, kf})}`);
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}}); await sleep(300);
        await ev(`(() => { document.activeElement && document.activeElement.blur(); document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
        // the chat with reactions
        await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1200);
        if (touch) await open('agents/' + AG);
        const rx = await ev(`(() => { const b = [...document.querySelectorAll('#chat-msgs .chrx .rx')].filter(e => e.offsetWidth); return b.length; })()`);
        check(rx >= 3, `${vw}px: chat reactions shown (${rx})`);
        if (touch) {
          const small = await ev(SMALL('#chat-msgs .chrx .rx'));
          check(!small.length, `${vw}px: chat reactions >= 44 px: ${JSON.stringify(small)}`);
        }
        const ov = await ev(`(() => { const m = document.querySelector('#chat-msgs'); return m ? {sw: m.scrollWidth, cw: m.clientWidth} : null; })()`);
        check(ov && ov.sw <= ov.cw + 1, `${vw}px: chat without horizontal overflow ${JSON.stringify(ov)}`);
        await shot(`p272-chat-${vw}.png`);
        await ev(`(() => { chatClose && chatClose(); return 1; })()`);
      }
    }, touch);
  }

  // a near-square touch screen (an unfolded Fold, 880 x 904): touch-drag a timeline bar, nothing rescales
  await call('PATCH', `/api/lists/${P}`, {view: 'timeline'});
  await firefox(async ({cmd, ev, nav, ctx, drag}) => {
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 880, height: 904}});
    await nav(B + '?tl=1#l/' + P); await sleep(1500);
    const before = await ev(`(() => { const t = document.querySelector('#view .tl'), b = document.querySelector('#view .tl-bar'); if (!t || !b) return null; const r = b.getBoundingClientRect(); return {tw: t.getBoundingClientRect().width, x: r.left + r.width / 2, y: r.top + r.height / 2, meta: document.querySelector('meta[name="viewport"]').getAttribute('content'), iw: innerWidth}; })()`);
    check(before, '880 x 904: a timeline with a bar');
    if (!before) return;
    await drag(before.x, before.y, 40, 0, 'touch'); await sleep(800);
    const after = await ev(`(() => { const t = document.querySelector('#view .tl'); return {tw: t ? t.getBoundingClientRect().width : 0, meta: document.querySelector('meta[name="viewport"]').getAttribute('content'), iw: innerWidth}; })()`);
    check(after.meta === before.meta && Math.abs(after.tw - before.tw) < 1 && after.iw === before.iw, `880 x 904: touch-dragging a bar keeps the viewport and the timeline width ${JSON.stringify({before, after})}`);
    await ev(`(() => { histStep && histStep('undo'); return 1; })()`).catch(() => {});
  }, true);
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});

  console.log(`p272_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
