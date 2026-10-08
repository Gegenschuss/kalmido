// 2.29.0 UI tests ("Folders like lists, calm agents"), own container (start.sh). jsdom:
// #1030 / #929 the folder menu's "Folder settings…" (workspace, agent, members may use it, tidy; apply to all / only new; the
//      lists that cannot follow are named first), the list dialog says what comes from the folder and offers "Back to the
//      folder"; "Share folder" with every role (admin too) and a role switch per person, removing asks "also from the lists?";
//      a new list in a folder shared with me says it will be shared with the folder's people
// #1029 the permission badge in the chat header (Auto / Ask first), a menu to switch it for the admin, the runtime field
// #1024 Settings > Agents: ONE "Set up" (first question: For me / For the team, one sentence each), "Administration" (admins)
//      with the server-wide switches; every agent card says Personal / Team
// #345 Settings > Agents > Lists: lists of others shared with me show up read-only with their owner
// #363 the chat pop-up: the round button bottom right (desktop), the key A, the window stays while switching views, fold,
//      dock as side panel and back
// Firefox (1440 light / dark, 390 touch): screenshots; #1028 a long command in a chat bubble wraps (no sideways scrollbar over
// the next line); #1002 a click on an empty "Assigned" cell of a shared agency project opens the people picker; #963 "+"
// in the reactions opens the emoji field above the chat.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2290_ui', check, shots: 'P2290_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,family,team';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const st0 = await call('GET', '/api/state');
  const ORG = st0.me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  await call('PATCH', '/api/settings', {folders: '["Clients"]'});
  const C1 = (await call('POST', '/api/lists', {name: 'Client A', folder: 'Clients', org_id: null})).id;
  const C2 = (await call('POST', '/api/lists', {name: 'Client B', folder: 'Clients', org_id: null})).id;
  const AGY = (await call('POST', '/api/lists', {name: 'Agency job', ptype: 'agency', org_id: ORG})).id;
  await call('PUT', `/api/lists/${AGY}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${AGY}/members`, {user_id: AG, role: 'edit'});
  const TA = (await call('POST', '/api/tasks', {title: 'Briefing with the client', list_id: AGY})).id;
  await call('POST', '/api/tasks', {title: 'Concept draft', list_id: AGY});
  const BL = (await call('POST', '/api/lists', {name: 'Bob shares', org_id: ORG}, BCK)).id;  // #345: a list of Bob's shared with Alice
  await call('PUT', `/api/lists/${BL}/members`, {user_id: 1, role: 'edit'}, BCK);
  await call('PUT', `/api/lists/${BL}/members`, {user_id: AG, role: 'edit'}, BCK);
  // #1028: a permission question with a long command in a code block, then text under it
  await fetch(V + '/agent/chats/1', {method: 'POST', headers: AGH, body: JSON.stringify({body: 'May I run this?\n```\ncd ~/server-data/bin && ./kalmido-devlist.py show 362 --with-comments --format markdown --output /tmp/a-very-long-path/that/keeps/going/and/going.md\n```\nAnswer: a button, 👍 or 👎, or write "yes".', choices: [{id: 'allow', label: 'Allow', style: 'primary'}, {id: 'deny', label: 'Deny', style: 'danger'}]})});

  // ================= #1030 / #929 folder settings
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await until(() => d.querySelector('#side .fhead[data-folder="Clients"]'));
  w.eval(`folderMenu(document.querySelector('#side .fhead[data-folder="Clients"]'), 'Clients')`);
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const fItems = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim());
  check(fItems.some(x => /Folder settings/.test(x)) && fItems.some(x => /Share folder/.test(x)), '#1030: the folder menu has "Folder settings…" ' + fItems.join('|'));
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(x => /Folder settings/.test(x.textContent)));
  await until(() => d.querySelector('.modal #fs-ws'));
  let md = d.querySelector('.modal');
  check(md && md.querySelector('#fs-ws') && md.querySelector('#fs-ag') && md.querySelector('#fs-am') && md.querySelector('#fs-td') && md.querySelectorAll('[name="fs-ap"]').length === 2, '#1030: workspace, agent, members, tidy and "apply to" in the dialog');
  check(/2 lists in the folder/.test(md.textContent), '#1030: "apply to" counts the lists ' + md.querySelector('.fsapply')?.textContent);
  change(w, md.querySelector('#fs-ws'), String(ORG));
  change(w, md.querySelector('#fs-ag'), String(AG));
  click(w, md.querySelector('[data-m="ok"]'));
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === C1)?.org_id === ORG);
  let st = await call('GET', '/api/state');
  check(st.lists.find(l => l.id === C1).org_id === ORG && st.lists.find(l => l.id === C2).members.some(m => m.user_id === AG), '#1030: saved: both lists in the organisation, the agent in them');
  check(st.folder_props.Clients && st.folder_props.Clients.agent_id === AG, '#1030: the state knows the folder settings ' + JSON.stringify(st.folder_props));
  // a list changed on its own + the dry run names it
  await call('PUT', '/api/folders/props', {folder: 'Clients', props: {agent_members: false}});
  await call('PATCH', `/api/lists/${C2}`, {agent_members: true});
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + C2}); d = w.document;
  await until(() => d.querySelector('#side .srow[data-list]'));
  w.eval(`listModal(${C2})`); await until(() => d.querySelector('.modal #l-fhint'));
  const fh = d.querySelector('.modal #l-fhint');
  check(fh && !fh.hidden && /From the folder/.test(fh.textContent) && /This list differs/.test(fh.textContent) && fh.querySelector('[data-freset]'), '#1030: the list dialog: from the folder, differs, Back to the folder ' + (fh?.textContent || '').slice(0, 160));
  click(w, fh.querySelector('[data-freset]'));
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === C2)?.agent_members === 0);
  check((await call('GET', '/api/state')).lists.find(l => l.id === C2).agent_members === 0, '#1030: Back to the folder takes the folder value again');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  // the dry run in the dialog: a list that keeps its own value is named before saving
  await call('PATCH', `/api/lists/${C2}`, {agent_tidy: 'suggest'});
  w.eval(`folderPropsModal('Clients')`); await until(() => d.querySelector('.modal #fs-td'));
  md = d.querySelector('.modal');
  await call('PUT', '/api/folders/props', {folder: 'Clients', props: {agent_tidy: 'off'}, apply: 'new'});
  await call('PATCH', `/api/lists/${C1}`, {agent_tidy: 'suggest'});
  change(w, md.querySelector('#fs-td'), 'auto');
  click(w, md.querySelector('[data-m="ok"]'));
  await until(() => !md.querySelector('#fs-prev')?.hidden || !md.isConnected);
  check(md.isConnected && !md.querySelector('#fs-prev').hidden && /Client/.test(md.querySelector('#fs-prev').textContent) && /Save anyway/.test(md.querySelector('[data-m="ok"]').textContent),
    '#1030: lists that keep their own value are named first, "Save anyway" ' + (md.querySelector('#fs-prev')?.textContent || '').slice(0, 160));
  md.remove();
  // folder people: every role, switch per person, removing asks
  w.eval(`folderPeopleModal('Clients')`); await until(() => d.querySelector('.modal #fp-role'));
  md = d.querySelector('.modal');
  check([...md.querySelectorAll('#fp-role option')].map(o => o.value).join() === 'admin,edit,participant,view', '#929: every role when sharing a folder');
  change(w, md.querySelector('#fp-user'), String(BOB)); change(w, md.querySelector('#fp-role'), 'admin');
  click(w, md.querySelector('[data-m="add"]'));
  await until(() => md.querySelector('[data-fprole]'));
  check(md.querySelector(`[data-fprole="${BOB}"]`)?.value === 'admin', '#929: Bob is in with the role admin');
  change(w, md.querySelector(`[data-fprole="${BOB}"]`), 'edit');
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === C1)?.members.find(m => m.user_id === BOB)?.role === 'edit');
  check((await call('GET', '/api/state')).lists.find(l => l.id === C1).members.find(m => m.user_id === BOB)?.role === 'edit', '#929: the role switch reaches the lists');
  click(w, md.querySelector(`[data-rm="${BOB}"]`)); await until(() => d.querySelector('#pop [role="menuitem"]'));
  const rmItems = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent);
  check(rmItems.length === 2 && /Also remove from the lists/.test(rmItems[0]) && /Only stop sharing new lists/.test(rmItems[1]), '#929: removing asks: also from the lists / only new ones');
  w.eval('closePop()'); md.remove();
  w.close();
  // Bob: a new list in the folder shared with him says it will be shared
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#side .srow[data-list]'));
  w.eval(`listModal(null, 'Clients')`); await until(() => d.querySelector('.modal #l-fhint'));
  const bh = d.querySelector('.modal #l-fhint');
  check(bh && !bh.hidden && /shared with everyone in the folder/.test(bh.textContent) && bh.querySelector('[data-fnone]'), '#929: the new-list dialog says it will be shared ' + (bh?.textContent || '').slice(0, 140));
  click(w, bh.querySelector('[data-fnone]'));
  check(d.querySelector('.modal #l-folder').value === '' && bh.hidden, '#929: "Create it without a folder instead" empties the folder');
  w.close();

  // ================= #1029 permission badge, #1024 / #345 Settings > Agents, #363 pop-up
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#side .srow[data-list]'));
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelector('#achat .chath'));
  let badge = d.querySelector('#achat .chmode');
  check(badge && badge.tagName === 'BUTTON' && /Host default/.test(badge.textContent), '#1029: the badge in the chat header (admin: a button) ' + (badge?.outerHTML || '').slice(0, 120));
  click(w, badge); await until(() => d.querySelector('#pop [role="menuitem"]'));
  click(w, [...d.querySelectorAll('#pop [role="menuitem"]')].find(x => /^Auto/.test(x.textContent.trim())));
  await until(() => /Auto/.test(d.querySelector('#achat .chmode')?.textContent || ''));
  check(/Auto/.test(d.querySelector('#achat .chmode').textContent) && d.querySelector('#achat .chmode.pm-auto'), '#1029: switched to Auto');
  const agent1 = await (await fetch(V + '/agent', {headers: AGH})).json();
  check(agent1.runtime.permission_mode === 'auto', '#1029: the agent reads it in its runtime');
  w.eval('chatClose()');
  w.eval(`settingsModal('agents')`); await until(() => d.querySelector('.modal [data-aisub="setup"]'));
  md = d.querySelector('.modal');
  const subs = [...md.querySelectorAll('[data-aisub]')].map(b => b.textContent.trim());
  check(subs.filter(x => /Set up/.test(x)).length === 1 && subs.includes('Administration'), '#1024: ONE "Set up" and "Administration" ' + subs.join('|'));
  click(w, md.querySelector('[data-aisub="setup"]')); await sleep(400);
  const setup = md.querySelector('#aisp-setup');
  check(/Who is the agent for/.test(setup.textContent) && [...setup.querySelectorAll('[data-agseg="guide"] [data-agsv]')].map(b => b.textContent.trim()).join('|') === 'For me|For the team' && setup.querySelector('#s-agwhy').textContent.length > 40,
    '#1024: the first question For me / For the team with one sentence ' + [...setup.querySelectorAll('[data-agseg="guide"] [data-agsv]')].map(b => b.textContent.trim()).join('|'));
  check(!setup.querySelector('#s-uag') && md.querySelector('#aisp-admin #s-uag') && md.querySelector('#aisp-admin #s-sclim'), '#1024: the server-wide switches are under Administration, not under Set up');
  click(w, md.querySelector('[data-aisub="agents"]'));
  await until(() => md.querySelector('#s-ags .agown'));
  check(/Team/.test(md.querySelector(`#s-ags [data-agid="${AG}"] .agown`)?.textContent || ''), '#1024: the agent card says Team');
  click(w, md.querySelector('[data-aisub="lists"]'));
  await until(() => md.querySelector(`#s-ai-tbl [data-lid="${BL}"]`));
  const ro = md.querySelector(`#s-ai-tbl [data-lid="${BL}"]`);
  check(ro && ro.classList.contains('airo') && /Bob Baker/.test(ro.textContent) && /Claude/.test(ro.textContent) && !ro.querySelector('select'), '#345: a list of Bob\'s shows up read-only with its owner and agent ' + (ro?.textContent || '').slice(0, 100));
  md.remove();
  // #363 the pop-up button, the key A, the window across views
  await until(() => d.querySelector('#chatfab'));
  check(d.querySelector('#chatfab .avatar'), '#363: the round chat button bottom right');
  click(w, d.querySelector('#chatfab')); await until(() => d.querySelector('#achat.float .chath'));
  check(d.querySelector('#achat.float') && d.body.classList.contains('chat-float') && !d.body.classList.contains('chat-open') && !d.querySelector('#chatfab'), '#363: it opens the chat as a window (no side panel)');
  w.eval(`go('l/${C1}')`); await sleep(500);
  check(d.querySelector('#achat.float:not(.hidden)'), '#363: the window stays while switching views');
  click(w, d.querySelector('#achat [data-act="chat-min"]'));
  check(d.querySelector('#achat.float.min'), '#363: fold to the header');
  click(w, d.querySelector('#achat [data-act="chat-min"]'));
  click(w, d.querySelector('#achat [data-act="chat-dock"]')); await until(() => d.body.classList.contains('chat-open'));
  check(d.body.classList.contains('chat-open') && !d.querySelector('#achat.float'), '#363: dock as side panel');
  click(w, d.querySelector('#achat [data-act="chat-dock"]')); await until(() => d.querySelector('#achat.float'));
  w.eval('chatClose()'); await sleep(200);
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'a', bubbles: true}));
  await until(() => d.querySelector('#achat:not(.hidden)'));
  check(d.querySelector('#achat.float:not(.hidden)'), '#363: the key A opens it');
  d.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'a', bubbles: true})); await sleep(200);
  check(d.querySelector('#achat.hidden'), '#363: ... and closes it');
  w.close();

  // ================= Firefox: screenshots + the real layout checks
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#today'); await ready(ev);
    check(await ev(`(() => { const b = document.querySelector('#chatfab'); if (!b) return false; const r = b.getBoundingClientRect(); return r.right <= innerWidth && r.bottom <= innerHeight && r.width >= 40; })()`), `${tag}: #363 the chat button sits bottom right`);
    await shot(`p2290-${th}-1440-fab.png`);
    await ev(`(() => { document.querySelector('#chatfab').click(); return 1; })()`); await sleep(1200);
    check(await ev(`(() => { const p = document.querySelector('#achat.float'); if (!p) return false; const r = p.getBoundingClientRect(); return r.width < 450 && r.height > 300 && r.right <= innerWidth && r.bottom <= innerHeight; })()`), `${tag}: #363 the chat window`);
    // #1028: the long command wraps inside the bubble, no sideways scrollbar, the line under it is not covered
    check(await ev(`(() => { const pre = [...document.querySelectorAll('#achat .cbub pre.mdpre')].pop(); if (!pre) return false; const cs = getComputedStyle(pre); const next = pre.closest('.mdcode').nextElementSibling; const pr = pre.getBoundingClientRect(), nr = next ? next.getBoundingClientRect() : null; return pre.scrollWidth <= pre.clientWidth + 1 && cs.whiteSpace === 'pre-wrap' && (!nr || nr.top >= pr.bottom - 0.5); })()`), `${tag}: #1028 the code block wraps, the text under it stays free`);
    await shot(`p2290-${th}-1440-chat-window.png`);
    // #963: "+" under a message opens the emoji field ABOVE the chat window (it was behind the chat panel once)
    await ev(`(() => { const b = [...document.querySelectorAll('#achat [data-act="rx-more"]')].pop(); b && b.click(); return !!b; })()`); await sleep(500);
    check(await ev(`(() => { const p = document.querySelector('#pop'), i = document.querySelector('#pop #rx-in'); if (!i || p.classList.contains('hidden')) return false; const r = i.getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!e && p.contains(e); })()`), `${tag}: #963 "+" opens the emoji field on top`);
    await ev(`(() => { closePop(); return 1; })()`);
    await ev(`(() => { chatClose(); return 1; })()`);
    await ev(`(() => { folderPropsModal('Clients'); return 1; })()`); await sleep(900);
    await shot(`p2290-${th}-1440-folder-settings.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); listModal(${C2}); return 1; })()`); await sleep(700);
    await shot(`p2290-${th}-1440-list-dialog-folder.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); settingsModal('agents'); return 1; })()`); await sleep(1000);
    await ev(`(() => { document.querySelector('[data-aisub="setup"]').click(); return 1; })()`); await sleep(800);
    check(await ev(`(() => { const s = document.querySelector('.modal .aisub'); return !!s && s.scrollWidth <= s.clientWidth + 2; })()`), `${tag}: #1024 the six sub-tabs fit`);
    await shot(`p2290-${th}-1440-agents-setup.png`);
    await ev(`(() => { document.querySelector('[data-aisub="lists"]').click(); return 1; })()`); await sleep(1000);
    await shot(`p2290-${th}-1440-agents-lists.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
    // #1002: an empty "Assigned" cell of the shared agency project opens the people picker (a real click)
    await o.nav(B + '#l/' + AGY); await ready(ev); await sleep(600);
    const cell = await ev(`(() => { const rows = [...document.querySelectorAll('#view .trow')]; for (const r of rows) { const c = r.querySelector('[data-act="assign"]'); if (c) { const b = c.getBoundingClientRect(); return {x: Math.round(b.left + b.width / 2), y: Math.round(b.top + b.height / 2), w: b.width}; } } return null; })()`);
    if (cell && cell.w > 0) {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: cell.x, y: cell.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx}); await sleep(500);
      check(await ev(`!document.querySelector('#pop').classList.contains('hidden') && /Bob Baker/.test(document.querySelector('#pop').textContent)`), `${tag}: #1002 a click on the empty Assigned cell opens the people picker`);
      await shot(`p2290-${th}-1440-agency-assign.png`);
      await ev(`(() => { closePop(); return 1; })()`);
    } else check(false, `${tag}: #1002 the empty Assigned cell is visible and clickable ` + JSON.stringify(cell));
  });
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    check(await ev(`!document.querySelector('#chatfab')`), `${tag}: #363 no pop-up button on the phone (the chat is a page there)`);
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(900);
    check(await ev(`(() => { const pre = [...document.querySelectorAll('.cbub pre.mdpre')].pop(); return !!pre && pre.scrollWidth <= pre.clientWidth + 1 && document.documentElement.scrollWidth <= 390; })()`), `${tag}: #1028 the code block wraps on the phone`);
    check(await ev(`!!document.querySelector('.chath .chmode')`), `${tag}: #1029 the badge on the phone`);
    await shot('p2290-light-390-chat.png');
    await ev(`(() => { folderPropsModal('Clients'); return 1; })()`); await sleep(900);
    check(await ev(`document.documentElement.scrollWidth <= 390`), `${tag}: #1030 the folder settings fit the phone`);
    await shot('p2290-light-390-folder-settings.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
