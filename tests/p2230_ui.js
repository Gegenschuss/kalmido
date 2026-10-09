// 2.23.0 UI tests: package "Team, family, clients" (#463) and the ride-alongs #794 #711 #444 #799, own container (start.sh).
// jsdom: the modules are off by default; on: the sidebar group "Clients" above the lists, a client created in its dialog, the
// client's page (tiles, budget bar, the timesheet with the client's lists), the client of a list in the list dialog, the
// workload table, an approval (asked in its dialog, the approver's bar with Approve / changes / Reject, the row chip, the
// history), the forms of a list (created in the dialog, the link), the sign-in link + QR code in the user dialog, the
// registration settings and "Create account" on the login page, the organisation in the administration (#799), the
// sidebar's icon column (#794).
// Firefox: a phone (390 touch), the Fold (690 touch), a desktop (1440 mouse): #794 the gap folder head -> first list equals
// list -> list, one icon column (folder icon, emoji, dot), nothing sideways and 44 px targets on the clients / workload
// views, axe (WCAG 2.2 A + AA) over the views, the approval bar and the login page with "Create account". Screenshots with
// P2230_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2230_ui', check, shots: 'P2230_SHOTS'});
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const BASE = 'cal,comments,collab,time,progress,agents';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: BASE});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: BASE + ',workload'}, BCK);
  const P = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  await call('POST', '/api/lists', {name: '🎯 Goals', folder: 'Work'}); await call('POST', '/api/lists', {name: 'Plain', folder: 'Work'});
  await call('POST', '/api/lists', {name: '🌀 Top emoji'}); await call('POST', '/api/lists', {name: 'Top plain'});

  // ================= off = no trace
  let w = await boot({user: 'alice', hash: 'clients'}), d = w.document;
  await sleep(300);
  check(w.eval('S.route.mod') === 'tasks' && !d.querySelector('#side .sg-clients') && !d.querySelector('#side [data-go="workload"]'), 'off: no clients group, no workload row');
  w.eval(`settingsModal('modules')`); await sleep(400);
  check(['clients', 'workload', 'forms'].every(k => d.querySelector(`.smodal [data-feat="${k}"]`) && !d.querySelector(`.smodal [data-feat="${k}"]`).checked), 'Settings > Modules: three switches, off');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  // #794: the icon column in the sidebar
  const sb = w.eval(`(() => { const f = [...document.querySelectorAll('#side .fhead')].find(x => /Work/.test(x.textContent)); const g = [...document.querySelectorAll('#side .srow[data-list]')].find(x => /Goals/.test(x.textContent));
    return {fic: !!f?.querySelector('.sic svg'), chevLast: f && [...f.children].findIndex(x => x.classList?.contains('fcar')) > [...f.children].findIndex(x => x.classList?.contains('n')), emo: g?.querySelector('.sic.semo')?.textContent, name: g?.querySelector('.n')?.textContent,
      dots: [...document.querySelectorAll('#side .srow[data-list]')].every(r => r.querySelector('.sic'))}; })()`);
  check(sb.fic && sb.chevLast && sb.emo === '🎯' && sb.name === 'Goals' && sb.dots, '#794: folder icon in the icon column, the arrow at the end, the emoji in the column, the name without it ' + JSON.stringify(sb));
  w.close();
  await call('PATCH', '/api/settings', {features: BASE + ',clients,workload,forms'});

  // ================= clients
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  const grp = d.querySelector('#side .sg-clients');
  const order = [...d.querySelectorAll('#side .sgroup')].map(x => x.className);
  check(grp && order.findIndex(c => c.includes('sg-clients')) === order.findIndex(c => c.includes('sg-lists')) - 1, 'the group "Clients" right above the lists');
  click(w, d.querySelector('#side [data-act="client-new"]')); await sleep(200);
  let md = d.querySelector('.modal.cldlg');
  check(md && md.querySelector('#cl-name') && md.querySelector('#cl-rate') && md.querySelector('#cl-bh'), 'the client dialog (with rate and budget)');
  input(w, md.querySelector('#cl-name'), 'Café Aurora'); md.querySelector('#cl-icon').value = '☕'; md.querySelector('#cl-contact').value = 'Maria';
  md.querySelector('#cl-rate').value = '80'; md.querySelector('#cl-bh').value = '10';
  click(w, md.querySelector('[data-m="save"]'));
  await until(() => w.eval('S.route.mod') === 'clients' && d.querySelector('#view .cldetail'));
  const CL = w.eval('S.route.client');
  check(CL && d.querySelector('#view .cldetail h2')?.textContent === 'Café Aurora' && d.querySelectorAll('#view .sttiles > div').length === 4, 'saved: the client page with four tiles');
  check(d.querySelector(`#side .scl[data-go="client/${CL}"].on`) && d.querySelector('#side .scl .semo')?.textContent === '☕', 'the sidebar row, highlighted, with its symbol');
  // the list's client in the list dialog
  w.eval(`listModal(${P})`); await sleep(400);
  const sel = d.querySelector('.modal #l-client');
  check(sel && [...sel.options].some(o => +o.value === CL), 'the list dialog: the client choice');
  change(w, sel, String(CL));
  await until(() => w.eval(`listById(${P}).client_id`) === CL);
  check(w.eval(`listById(${P}).client_id`) === CL, 'the list belongs to the client now');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  const T1 = (await call('POST', '/api/tasks', {title: 'Design', list_id: P, duration: 120})).id;
  await call('POST', '/api/time/entries', {task_id: T1, start: new Date(Date.now() - 3 * 3600e3).toISOString(), minutes: 90});
  w.eval(`go('client/${CL}')`); await sleep(200); w.eval('clReload()');
  await until(() => /2h 0m/.test(d.querySelector('#view .cltable')?.textContent || ''), 80);
  check(/Website relaunch/.test(d.querySelector('#view .cltable').textContent) && /2h 0m/.test(d.querySelector('#view .cltable').textContent) && d.querySelector('#view .clbud .clbar'),
    'estimate vs. actual per list, the budget bar ' + d.querySelector('#view .cltable')?.textContent);
  check(await until(() => /1:30/.test(d.querySelector('#view .sttiles')?.textContent || ''), 60), 'the tiles: 1:30 this month');  // 2.25.0: waits for the tiles too (CI flake)
  click(w, d.querySelector('#view [data-act="client-sheet"]'));
  await until(() => d.querySelector('.tsheet .tspage'), 60);
  check(w.eval('S.route.mod') === 'time' && /Café Aurora/.test(d.querySelector('.tsheet .tsclient')?.textContent || '') && /Website relaunch/.test(d.querySelector('.tsheet').textContent),
    'the timesheet of the client (its lists, its name on top)');
  check(d.querySelector('#view .tvclient a')?.textContent === 'Café Aurora', 'the time view shows the client filter');
  d.querySelector('.tsheet')?.remove(); d.body.classList.remove('tsprint');
  click(w, d.querySelector('#view [data-act="client-tvx"]')); await sleep(200);
  check(!d.querySelector('#view .tvclient') && w.eval('S.tv.client') === null, 'the client filter off again');
  w.eval(`go('clients')`); await until(() => d.querySelector('#view .clcard'));
  check(d.querySelector('#view .clcard h2 a')?.getAttribute('href') === `#client/${CL}`, 'all clients: a card per client');
  w.close();

  // ================= workload (Bob)
  await call('POST', '/api/tasks', {title: 'Build', list_id: P, assignee_id: BOB, due: new Date().toISOString().slice(0, 10), duration: 600});
  w = await boot({user: 'bob', hash: 'workload'}); d = w.document;
  await until(() => d.querySelector('#view .wltable tbody tr'));
  const rows = [...d.querySelectorAll('#view .wltable tbody tr')].map(r => r.querySelector('th').textContent);
  check(rows.some(x => /Bob/.test(x)) && rows.some(x => /Alice/.test(x)) && d.querySelectorAll('#view .wltable thead th').length === 6, 'the workload: people x 4 weeks + no date ' + rows.join('|'));
  check(d.querySelector('#view .wltable .wlc.lv-warn, #view .wltable .wlc.lv-ok, #view .wltable .wlc.lv-over'), 'a cell with its level');
  check(d.querySelector('#side [data-go="workload"]'), 'the row "Workload" under Views');
  w.close();

  // ================= approval
  const AP = (await call('POST', '/api/tasks', {title: 'Approve the logo', list_id: P})).id;
  w = await boot({user: 'alice', hash: `l/${P}`}); d = w.document;
  w.eval(`openDetail(${AP})`); await sleep(300);
  w.eval(`approvalRequest(${AP})`); await sleep(300);
  md = [...d.querySelectorAll('.modal')].pop();
  check(md && md.querySelector('#ap-who') && [...md.querySelector('#ap-who').options].map(o => o.textContent).includes('Bob'), 'ask for approval: Bob to choose');
  md.querySelector('#ap-note').value = 'By Friday';
  click(w, md.querySelector('[data-m="save"]'));
  await until(() => w.eval(`S.tasks.get(${AP})?.approval`) === 'pending');
  await until(() => d.querySelector('#detail .apbar'));
  check(/Waiting for the approval of Bob/.test(d.querySelector('#detail .apbar')?.textContent || '') && d.querySelector('#detail [data-act="ap-cancel"]'), 'the bar: waiting for Bob, withdraw');
  w.eval(`render()`); await sleep(200);
  check(d.querySelector(`#view .trow[data-id="${AP}"] .apchip`), 'the row shows "Approval"');
  w.close();
  w = await boot({user: 'bob', hash: `l/${P}`}); d = w.document;
  w.eval(`openDetail(${AP})`); await sleep(400);
  check(d.querySelectorAll('#detail .apbar [data-act="ap-decide"]').length === 3, 'Bob: Approve, Ask for changes, Reject');
  click(w, d.querySelector('#detail [data-act="ap-decide"][data-k="approve"]'));
  const apt = await until(async () => { const x = await call('GET', `/api/tasks/${AP}`); return x.approval === 'approved' && x.completed_at ? x : null; }, 80);
  check(apt && apt.approval === 'approved' && apt.completed_at, 'approved: done (completed)');
  w.close();
  w = await boot({user: 'alice', hash: `l/${P}`}); d = w.document;
  w.eval(`S.extra = S.extra || []; openTaskById(${AP})`); await sleep(900);
  check(/Approved by Bob/.test(d.querySelector('#detail .apbar')?.textContent || ''), 'Alice sees "Approved by Bob"');
  w.close();

  // ================= forms
  w = await boot({user: 'alice', hash: `l/${P}`}); d = w.document;
  w.eval(`listModal(${P})`); await sleep(300);
  click(w, d.querySelector('.modal [data-act="forms-open"]')); await sleep(600);
  md = [...d.querySelectorAll('.modal')].pop();
  check(/Forms/.test(md.textContent) && md.querySelector('[data-fm="new"]'), 'the forms dialog');
  click(w, md.querySelector('[data-fm="new"]')); await sleep(200);
  const ed = [...d.querySelectorAll('.modal')].pop();
  input(w, ed.querySelector('#fm-title'), 'Change request');
  click(w, ed.querySelector('[data-m="save"]'));
  await until(() => [...d.querySelectorAll('.modal')].some(m => /Change request/.test(m.textContent)));
  const fl = await call('GET', `/api/lists/${P}/forms`);
  check(fl.forms?.length === 1 && fl.forms[0].title === 'Change request' && fl.forms[0].access === 'org', 'a form was created');
  const pg = await (await fetch(B + fl.forms[0].url.split('kalmido.example/')[1], {headers: {Cookie: BCK}})).text();
  check(/Change request/.test(pg) && /name="subject"/.test(pg), 'its page (Bob, same organisation)');
  w.close();

  // ================= users: sign-in link + QR, approve a registration, the organisation, registration settings
  const KID = (await call('POST', '/api/users', {username: 'tim', display_name: 'Tim', password: 'password123', kid: true, parents: [1]})).id;
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval(`settingsModal('users')`); await until(() => d.querySelector(`.smodal [data-acc="user-edit"][data-uid="${KID}"]`));
  click(w, d.querySelector(`.smodal [data-acc="user-edit"][data-uid="${KID}"]`)); await sleep(300);
  md = [...d.querySelectorAll('.modal')].pop();
  click(w, md.querySelector('[data-m="signin"]'));
  await until(() => d.querySelector('.qrbox img'));
  check(d.querySelector('.qrbox img')?.getAttribute('src').startsWith('data:image/svg+xml') && /#signin\//.test(d.querySelector('#qr-link')?.value || ''), 'the sign-in link with its QR code');
  [...d.querySelectorAll('.modal:not(.smodal)')].forEach(m => m.remove());
  check(/Organisation/.test(d.querySelector('.smodal #a-orgs-h')?.textContent || '') && !d.querySelector('.smodal #a-vis') && !d.querySelector('.smodal [data-acc="org-new"]'), '#799: the organisation is shown, no switch, no "New organisation"');
  const ss = d.querySelector('.smodal #s-signup');
  check(ss && ss.value === 'off' && ss.querySelector('option[value="open"]').disabled, '#711: registration off; "open" not offered for an organisation');
  change(w, ss, 'approval'); await sleep(500);
  check((await call('GET', '/api/state')).about.signup_mode === 'approval', '#711: saved');
  w.close();
  // the login page: Create account
  const {JSDOM} = require('jsdom');
  const {PooledLoader} = require('./boot');
  const dom = await JSDOM.fromURL(B, {runScripts: 'dangerously', resources: new PooledLoader(), pretendToBeVisual: true, beforeParse(x) {
    const st = {}; Object.defineProperty(x, 'localStorage', {value: {getItem: k => st[k] ?? null, setItem: (k, v) => { st[k] = String(v); }, removeItem: k => { delete st[k]; }, key: i => Object.keys(st)[i], get length() { return Object.keys(st).length; }}});
    x.matchMedia = () => ({matches: false, addEventListener() {}, addListener() {}}); x.fetch = (u, o = {}) => fetch(new URL(String(u), B), o);
    Object.defineProperty(x.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}}); x.scrollTo = () => {}; }});
  w = dom.window; d = w.document;
  await until(() => d.querySelector('.authscreen [data-au="signup"]'), 60);
  check(d.querySelector('.authscreen [data-au="signup"]'), '#711: the login page offers "Create account"');
  click(w, d.querySelector('.authscreen [data-au="signup"]')); await sleep(200);
  check(d.querySelector('#su-form #su-name') && d.querySelector('#su-form #su-mail') && d.querySelector('#su-form #su-pw'), '#711: the form (this container has no SMTP: a password, then an admin approves)');
  w.close();

  // ================= #823: team chat: a message of Bob and one of mine
  const room = (await call('GET', '/api/team')).rooms.find(r => r.list_id === P);
  const RID = room?.id;
  const MB = (await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Can you check the logo?'}, BCK)).id;
  const MA = (await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'On it.'})).id;
  check(RID && MB && MA, '#823: two messages in the list channel');
  check((await call('POST', `/api/team/messages/${MA}/reactions`, {emoji: 'up'})).status === 400, '#823: no reaction on my own message (400)');
  check((await call('POST', `/api/team/messages/${MA}/reactions`, {emoji: 'heart'}, BCK)).status === 200, '#823: Bob reacts to mine');
  w = await boot({user: 'alice', hash: `team/${RID}`}); d = w.document;
  await until(() => d.querySelector(`#view .cmsg[data-mid="t:${MA}"]`), 60);
  const mine = d.querySelector(`#view .cmsg[data-mid="t:${MA}"]`), his = d.querySelector(`#view .cmsg[data-mid="t:${MB}"]`);
  check(mine && !mine.querySelector('.rx:not([disabled]):not([data-act="tc-msg-menu"])') && mine.querySelector('.rx[disabled]')?.textContent.includes('❤'), '#823: my message: only Bob\'s heart, read-only ' + mine?.querySelector('.cmeta')?.innerHTML.slice(0, 200));
  check(his && his.querySelector('.rxtog') && his.querySelectorAll('.rx.rxq').length >= 3, '#823: Bob\'s message: the smiley and the hidden quick reactions');
  click(w, his.querySelector('.rxtog')); await sleep(150);
  check(d.querySelector(`#view .cmsg[data-mid="t:${MB}"]`).classList.contains('rxshow'), '#823: the smiley opens them');
  w.close();

  // ================= #824: an agent at work (for the Firefox pictures: the dot at the tab, the "More" menu)
  const AGJ = await call('POST', '/api/admin/agents', {scopes: ['read'], username: 'claude', display_name: 'Claude'});
  await call('PUT', `/api/lists/${P}/members`, {user_id: AGJ.id, role: 'edit'});
  const agv = (m, u, b) => fetch(B + 'api/v1' + u, {method: m, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + AGJ.token}, body: b ? JSON.stringify(b) : undefined});
  await agv('GET', '/agent/events'); await agv('PUT', '/agent/status', {status: 'working', text: 'Sorting the requests'});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval('agentLive()'); await sleep(200);
  const sa = d.querySelector('#side [data-go="agents"]');
  check(sa && sa.classList.contains('aspin') && /Claude is working/.test(sa.getAttribute('aria-label') || ''), '#824: the Agents row: working mark + "Claude is working" in its label');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, user, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel = '#top h1', n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  const SMALL = sel => `(() => { const coarse = matchMedia('(pointer: coarse)').matches, min = coarse ? 43.5 : 23.5; return [...document.querySelectorAll('${sel}')].filter(b => { const r = b.getBoundingClientRect(), cs = getComputedStyle(b); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !b.closest('[hidden]'); })
    .filter(b => { const r = b.getBoundingClientRect(); return r.width < min || r.height < min; }).map(b => (b.dataset.act || b.className) + ' ' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height)).slice(0, 8); })()`;
  const axe = async (ev, where) => {
    if ((await ev(`typeof axe`)) === 'undefined') await ev(AXE + '\n;1');
    const r = await ev(`axe.run(document, {runOnly: {type: 'tag', values: ${JSON.stringify(TAGS)}}, resultTypes: ['violations']}).then(r => r.violations.map(v => ({id: v.id, n: v.nodes.length, nodes: v.nodes.slice(0, 2).map(x => x.target.join(' ') + ' ' + (x.failureSummary || '').slice(0, 120))})))`);
    check(!r.length, `${where}: no axe violations: ` + r.map(v => `${v.id}(${v.n}) ${v.nodes[0]}`).join(' | ').slice(0, 700));
  };
  const sideways = ev => ev(`document.documentElement.scrollWidth - innerWidth`);
  for (const [vw, vh, th, touch] of [[390, 844, 'dark', true], [690, 829, 'light', true], [1440, 900, 'light', false]]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${vw}x${vh} ${th}`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o, 'alice', th) === 200, tag + ': login');
    await o.nav(B + '#inbox'); await ready(ev, '#side .fhead');
    // #794: the sidebar folder: no gap after the head, one icon column
    await ev(`(() => { document.querySelector('#side').classList.add('open'); return 1; })()`); await sleep(500);
    const g = await ev(`(() => { const f = [...document.querySelectorAll('#side .fhead')].find(x => /Work/.test(x.textContent)); const kids = [...f.nextElementSibling.querySelectorAll('.srow[data-list]')];
      const r = el => el.getBoundingClientRect(); const top = [...document.querySelectorAll('#side .sg-lists > .srow[data-list]')];
      const ic = el => Math.round(r(el.querySelector('.sic')).left + r(el.querySelector('.sic')).width / 2);
      return {gHead: Math.round(r(kids[0]).top - r(f).bottom), gList: Math.round(r(kids[1]).top - r(kids[0]).bottom), hHead: Math.round(r(f).height), hList: Math.round(r(kids[0]).height),
        topIc: [...new Set(top.map(ic))], fIc: ic(f), kidIc: [...new Set(kids.map(ic))], before: Math.round(r(f).top - r(f.previousElementSibling).bottom)}; })()`);
    check(Math.abs(g.gHead - g.gList) <= 1 && Math.abs(g.hHead - g.hList) <= 1, `${tag}: #794: folder head -> first list = list -> list, same height ` + JSON.stringify(g));
    check(g.topIc.length === 1 && Math.abs(g.fIc - g.topIc[0]) <= 1 && g.kidIc.length === 1 && g.before >= 8, `${tag}: #794: one icon column (top lists + folder), one inside the folder, room before the folder ` + JSON.stringify(g));
    await shot(`p2230-${vw}-${th}-side.png`);
    await ev(`(() => { document.querySelector('#side').classList.remove('open'); location.hash = '#clients'; return 1; })()`); await ready(ev, '#view .clcard');
    check(await sideways(ev) <= 0, `${tag}: clients: nothing sideways`);
    if (vw !== 690) await axe(ev, `${tag} clients`);
    await ev(`(() => { location.hash = '#client/' + S.clients[0].id; return 1; })()`); await ready(ev, '#view .cldetail .cltable');
    check(await sideways(ev) <= 0, `${tag}: a client: nothing sideways`);
    const sm = await ev(SMALL('#view .cldetail button, #view .cldetail a.btn'));
    check(!sm.length, `${tag}: a client: targets ` + JSON.stringify(sm));
    if (vw !== 690) await axe(ev, `${tag} client`);
    await shot(`p2230-${vw}-${th}-client.png`);
    await ev(`(() => { location.hash = '#workload'; return 1; })()`); await ready(ev, '#view .wltable');
    check(await sideways(ev) <= 0, `${tag}: workload: the page does not scroll sideways (the table scrolls in its box)`);
    const sw = await ev(SMALL('#view .wload .wlb:not([disabled]), #view .wload .wlcap, #view .wload .clhead button'));
    check(!sw.length, `${tag}: workload: targets ` + JSON.stringify(sw));
    if (vw !== 690) await axe(ev, `${tag} workload`);
    await shot(`p2230-${vw}-${th}-workload.png`);
    if (vw === 390) {  // #824: the dot at the agents tab / More
      await ev(`(() => { location.hash = '#inbox'; agentLive(); return 1; })()`); await ready(ev, '#tabs');
      await ev(`(() => { agentLive(); return 1; })()`); await sleep(300);
      await shot(`p2230-${vw}-${th}-agentdot.png`);
    }
    if (vw !== 690) {  // #823 + #824: the team chat (reactions behind the smiley) and an agent at work
      await ev(`(() => { location.hash = '#team/${RID}'; return 1; })()`); await ready(ev, '#view .cmsg');
      await shot(`p2230-${vw}-${th}-teamchat.png`);
      await ev(`(() => { const b = document.querySelector('#view .cmsg[data-mid="t:${MB}"] .rxtog'); b && b.click(); return 1; })()`); await sleep(400);
      if (vw === 390) await axe(ev, `${tag} team chat with the reactions open`);
      await shot(`p2230-${vw}-${th}-teamchat-react.png`);
    }
    if (vw === 390) {
      await ev(`(() => { location.hash = '#l/${P}'; return 1; })()`); await ready(ev, '#view .trow');
      await ev(`(() => { openDetail(${AP}); return 1; })()`); await ready(ev, '#detail .apbar');
      await axe(ev, `${tag} approval bar`);
      await shot(`p2230-${vw}-${th}-approval.png`);
      await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(() => 1)`);
      await o.nav(B); await ready(ev, '.authscreen [data-au="signup"]');
      await axe(ev, `${tag} login with Create account`);
      await ev(`(() => { document.querySelector('.authscreen [data-au="signup"]').click(); return 1; })()`); await sleep(400);
      const s2 = await ev(SMALL('.authscreen button, .authscreen input'));
      check(!s2.length, `${tag}: the registration form: 44 px ` + JSON.stringify(s2));
      await axe(ev, `${tag} registration form`);
      await shot(`p2230-${vw}-${th}-signup.png`);
    }
  }, touch);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
