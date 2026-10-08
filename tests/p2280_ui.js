// 2.28.0 UI tests ("Work and private apart, messages"), own container (start.sh). jsdom:
// #935 the workspace switch in the sidebar (Private | <organisation> | All; the setting follows), the lists / tasks / agents of
//      the shown workspace, the header chip; the list dialog's Workspace field ("Used for" only private, a new list in the shown
//      organisation); the share dialog offers the list's workspace only; Settings > Account > Workspaces
// #965 / #970 / #1011 Settings > Users shows people only (one row leads to the agents); the agents grouped (team, my personal,
//      others' personal restricted to name + kill switch); "Add agent…" asks team or personal; "Belongs to" in the dialog
// #985 the robot badge on an agent's picture (share dialog, members)
// #987 News: "For you" | "Activity" | "All", the bell counts only "For you" (+ direct messages), the start page banner
// #1005 the answer buttons under an agent's chat message: a tap answers, the buttons lock
// Firefox (1440 light / dark, 390 touch): screenshots of the changed screens; #976 a REAL right-click on a list in the sidebar
// right next to the sidebar grip opens the list menu while the grip is invisible and the menu is on top.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2280_ui', check, shots: 'P2280_SHOTS'});
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
  const ORG = st0.me.workspaces[0].id, ORGN = st0.me.workspaces[0].name;
  check(st0.workspaces === true && ORG > 0, '#935: the state knows the workspaces ' + JSON.stringify(st0.me.workspaces));
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const my = await call('POST', '/api/admin/agents', {scopes: ['read', 'comments'], username: 'mybot', display_name: 'My bot', owner_id: 1});
  const bb = await call('POST', '/api/admin/agents', {scopes: ['read', 'comments'], username: 'bobbot', display_name: 'Bob bot', owner_id: BOB});
  await call('PATCH', `/api/admin/agents/${my.id}`, {org_id: null});  // my personal agent works in my private space
  await call('PATCH', '/api/settings', {folders: '["Office", "Private"]'});
  const W1 = (await call('POST', '/api/lists', {name: 'Website', folder: 'Office', org_id: ORG})).id;
  const W2 = (await call('POST', '/api/lists', {name: 'Shop', folder: 'Office', org_id: ORG})).id;
  const P1 = (await call('POST', '/api/lists', {name: 'Garden', folder: 'Private', org_id: null})).id;
  const P2 = (await call('POST', '/api/lists', {name: 'Family plans', family: 'household'})).id;
  for (const lid of [W1, W2]) await call('PUT', `/api/lists/${lid}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${W1}/members`, {user_id: AG, role: 'edit'});
  await call('PATCH', `/api/lists/${W1}`, {agent_members: true});
  const TW = (await call('POST', '/api/tasks', {title: 'Deploy the website', list_id: W1, due: new Date().toISOString().slice(0, 10)})).id;
  const TW2 = (await call('POST', '/api/tasks', {title: 'Order stock', list_id: W2})).id;
  const TP = (await call('POST', '/api/tasks', {title: 'Cut the hedge', list_id: P1, due: new Date().toISOString().slice(0, 10)})).id;
  await call('POST', '/api/tasks', {title: 'Dentist', list_id: P2});
  // News: bob mentions and assigns (for me), the agent comments (activity)
  await call('POST', `/api/tasks/${TW}/comments`, {body: '<@1> can you check the DNS?'}, BCK);
  await call('PATCH', `/api/tasks/${TW2}`, {assignee_id: 1}, BCK);
  await fetch(V + `/tasks/${TW}/comments`, {method: 'POST', headers: AGH, body: JSON.stringify({body: 'I looked at the build, all green.'})});
  await fetch(V + `/tasks/${TW2}/comments`, {method: 'POST', headers: AGH, body: JSON.stringify({body: 'Stock levels noted.'})});
  // a question with buttons in the chat
  const q = await (await fetch(V + '/agent/chats/1', {method: 'POST', headers: AGH, body: JSON.stringify({body: 'May I run the deploy?\n```\n./deploy.sh prod\n```', choices: [{id: 'go', label: 'Allow', style: 'primary'}, {id: 'stop', label: 'Deny', style: 'danger'}]})})).json();  // 2.30.0: ids allow / deny = a permission question (p2300_chat_ui)
  check(q.choices && q.choices.choices.length === 2, '#1005: the question with buttons is stored');

  // ================= #935 the switch, the lists of the workspace
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await until(() => d.querySelector('#side .srow[data-list]'));
  const bar = d.querySelector('#side .wsbar');
  check(bar && /All workspaces/.test(bar.textContent) && !bar.classList.contains('on') && !d.querySelector('#top .wschip'), '#935: the switch in the sidebar says "All workspaces" at first, no chip ' + (bar?.textContent || ''));
  click(w, bar); await until(() => d.querySelector('#pop [role="menuitem"]'));
  const wsItems = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim());
  check(wsItems.length === 3 && /Private/.test(wsItems[0]) && wsItems[1].includes(ORGN) && /All workspaces/.test(wsItems[2]), '#935: the menu Private | organisation | All ' + wsItems.join('|'));
  w.eval('closePop()');
  const names = () => [...d.querySelectorAll('#side .srow[data-list] .n')].map(x => x.textContent.trim());
  check(names().includes('Website') && names().includes('Garden'), '#935: all lists in the sidebar ' + names());
  const todayN = () => d.querySelectorAll('#view .trow').length;
  check(todayN() === 2, '#935: Today shows both due tasks ' + todayN());
  w.eval(`wsSet('private')`); await sleep(400);
  check(!names().includes('Website') && names().includes('Garden') && names().includes('Family plans'), '#935: Private: only the private lists ' + names());
  check(![...d.querySelectorAll('#side .fhead')].some(f => f.dataset.folder === 'Office'), '#935: a folder with nothing in this workspace is left out');
  check(todayN() === 1 && d.querySelector('#view .trow .ttl')?.textContent.includes('hedge'), '#935: Today shows the private task only');
  check(d.querySelector('#top .wschip') && /Private/.test(d.querySelector('#top .wschip').textContent) && d.querySelector('#side .wsbar.on') && /Private/.test(d.querySelector('#side .wsbar').textContent), '#935: the header chip and the sidebar button name the workspace');
  await until(async () => (await call('GET', '/api/state')).settings.workspace === 'private');
  check((await call('GET', '/api/state')).settings.workspace === 'private', '#935: the setting follows (every device)');
  w.eval(`wsSet('org:${ORG}')`); await sleep(400);
  check(names().includes('Website') && !names().includes('Garden') && names().includes('Shop'), '#935: the organisation: its lists ' + names());
  check(d.querySelectorAll('#view .trow').length === 1 && d.querySelector('#view .trow .ttl')?.textContent.includes('Deploy'), '#935: Today shows the organisation task only');
  const shown = w.eval('JSON.stringify(shownAgents().map(a => [a.name, a.org_id]))');
  check(w.eval('(S.agents || []).length') >= 2 && JSON.parse(shown).every(a => a[1] === ORG), '#935: the agents of the organisation only ' + shown);
  // a new list in the shown organisation
  w.eval('listModal()'); let md = await until(() => d.querySelector('.modal.lnew'));
  check(md.querySelector('#l-ws') && md.querySelector('#l-ws').value === String(ORG), '#935: a new list starts in the shown workspace');
  check(md.querySelector('.lfamrow') && !md.querySelector('.lfamrow').hidden, '#935: "Used for" is offered for a simple list');
  change(w, md.querySelector('#l-fam'), 'shopping'); await sleep(50);
  check(md.querySelector('#l-ws').value === '', '#935: "Used for" makes the list private (the workspace follows)');
  change(w, md.querySelector('#l-fam'), ''); change(w, md.querySelector('#l-ws'), String(ORG));
  md.querySelector('#l-name').value = 'Marketing'; click(w, md.querySelector('[data-m="save"]'));
  const mk = await until(async () => (await call('GET', '/api/state')).lists.find(l => l.name === 'Marketing'));
  check(mk && mk.org_id === ORG, '#935: created in the organisation ' + (mk && mk.org_id));
  // the list dialog of an existing list: the field, autosave
  w.eval(`listModal(${P1})`); md = await until(() => d.querySelector('.modal.lmodal'));
  check(md.querySelector('#l-ws') && md.querySelector('#l-ws').value === '' && /Private/.test(md.querySelector('#l-wshint').textContent), '#935: the private list says so');
  change(w, md.querySelector('#l-ws'), String(ORG));
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === P1).org_id === ORG);
  check((await call('GET', '/api/state')).lists.find(l => l.id === P1).org_id === ORG, '#935: changing the workspace saves');
  change(w, md.querySelector('#l-ws'), '');
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === P1).org_id === null);
  md.remove();
  // the share dialog offers the workspace's people / agents only
  w.eval(`shareModal(${W2})`); md = await until(() => d.querySelector('.modal.shmodal'));
  await until(() => md.querySelector('#sh-agsel'));
  const agOpts = [...md.querySelectorAll('#sh-agsel option')].map(o => o.textContent);
  check(agOpts.includes('Claude') && agOpts.includes('Bob bot') && !agOpts.some(x => /My bot/.test(x)), '#935: the agent field offers the organisation agents, not the private one ' + agOpts.join('|'));
  check(md.querySelector('#l-members .mrow .avatar') && !md.querySelector('#l-members .avatar.agent'), '#985: people without a robot badge in the share dialog');
  md.remove();
  w.eval(`shareModal(${W1})`); md = await until(() => d.querySelector('.modal.shmodal'));
  await until(() => md.querySelector('#sh-agents .mrow, #sh-agsel'));
  check(d.querySelector('.modal.shmodal .avatar.agent .abot-b'), '#985: the agent carries the robot badge');
  md.remove();
  w.eval(`wsSet('all')`); await sleep(300);
  w.close();

  // ================= #987 News: For you | Activity, the bell, the banner
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => d.querySelector('.dash'));
  await until(() => d.querySelector('.dtome'));
  const st = await call('GET', '/api/state');
  check(st.news.unread_me === 2 && st.news.unread > st.news.unread_me, `#987: 2 for me (mention + assignment), more unread in all ${st.news.unread_me}/${st.news.unread}`);
  check(d.querySelector('.dtome') && /2 messages for you/.test(d.querySelector('.dtome h3').textContent), '#987: the start page banner "2 messages for you" ' + d.querySelector('.dtome h3')?.textContent);
  check(d.querySelector('#top .bell .nbadge')?.textContent === '2', '#987: the bell counts only "For you" ' + d.querySelector('#top .bell .nbadge')?.textContent);
  w.eval(`go('news')`); await until(() => d.querySelector('.ntabs'));
  const tabs = d.querySelector('.ntabs');
  check(tabs && tabs.querySelector('[data-tab="all"]').classList.contains('on') && /For you/.test(tabs.textContent) && /Activity/.test(tabs.textContent), '#987: the tabs All | For you | Activity, All first');
  const secs0 = [...d.querySelectorAll('#view .nsec')].map(x => x.textContent.trim());
  check(secs0.length === 2 && /For you/.test(secs0[0]) && /Activity/.test(secs0[1]) && d.querySelector('#view .nsec.first').nextElementSibling.classList.contains('tome'), '#987: "All" = two sections, the items for me first ' + secs0.join('|'));
  click(w, tabs.querySelector('[data-tab="me"]')); await sleep(200);
  let items = [...d.querySelectorAll('#view .nitem')];
  check(items.length === 2 && items.every(x => x.classList.contains('tome')) && items.some(x => /mentioned you/.test(x.textContent)) && items.some(x => /assigned a task to you/.test(x.textContent)), '#987: "For you" = the mention and the assignment ' + items.map(x => x.querySelector('.ntext')?.textContent).join('|'));
  click(w, d.querySelector('.ntabs [data-tab="act"]')); await sleep(200);
  items = [...d.querySelectorAll('#view .nitem')];
  check(items.length >= 1 && items.every(x => !x.classList.contains('tome')) && items.some(x => /Claude/.test(x.textContent)), '#987: "Activity" = the agent\'s comments ' + items.length);
  click(w, d.querySelector('.ntabs [data-tab="all"]')); await sleep(200);
  check(d.querySelectorAll('#view .nitem').length >= 3 && d.querySelectorAll('#view .nsec').length === 2, '#987: "All" shows everything in two sections');
  // the bell's dropdown: sections
  click(w, d.querySelector('.ntabs [data-tab="me"]')); await sleep(100);
  click(w, d.querySelector('#top [data-act="bell-pop"]')); await until(() => d.querySelector('#pop .bpop .nitem'));
  const secs = [...d.querySelectorAll('#pop .nsec')].map(x => x.textContent.trim());
  check(secs.length === 2 && /For you/.test(secs[0]) && /Activity/.test(secs[1]), '#987: the dropdown: "For you" above "Activity" ' + secs.join('|'));
  check(d.querySelector('#pop .bpop .nitem.tome') && d.querySelector('#pop .nsec.first').nextElementSibling.classList.contains('tome'), '#987: the items for me come first');
  w.eval('closePop()');
  // reading one for me lowers the bell
  w.eval(`go('news')`); await until(() => d.querySelector('#view .nitem.tome'));
  click(w, d.querySelector('#view .nitem.tome')); await sleep(400);
  await until(async () => (await call('GET', '/api/news')).unread_me === 1);
  check((await call('GET', '/api/news')).unread_me === 1, '#987: one read -> one left for me');
  w.close();

  // ================= #1005 the buttons in the chat
  w = await boot({user: 'alice', hash: 'agents/' + AG}); d = w.document;
  await until(() => d.querySelector('#chat-msgs .cmsg.ag .cchoices'));
  const ch = d.querySelector('#chat-msgs .cchoices');
  const btns = [...ch.querySelectorAll('.cchb')];
  check(btns.length === 2 && btns[0].textContent.trim() === 'Allow' && btns[0].classList.contains('st-primary') && btns[1].classList.contains('st-danger') && !btns[0].disabled, '#1005: two buttons, Allow (primary) and Deny (danger)');
  click(w, btns[0]);
  await until(() => d.querySelector('#chat-msgs .cchoices.done'));
  const ch2 = d.querySelector('#chat-msgs .cchoices');
  check(ch2.classList.contains('done') && [...ch2.querySelectorAll('.cchb')].every(b => b.disabled) && ch2.querySelector('.cchb.on')?.textContent.includes('Allow') && /Answered/.test(ch2.querySelector('.cchans')?.textContent || ''), '#1005: answered: the choice shown, the buttons locked');
  const ev = await (await fetch(V + '/agent/events?since=0', {headers: AGH})).json();
  check(ev.data.some(e => e.event === 'chat_choice' && e.data.choice_ids[0] === 'go'), '#1005: the agent got the event chat_choice');
  w.close();

  // ================= #965 / #970 / #1011 Settings > Users and Agents
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#side .srow[data-list]'));
  w.eval(`settingsModal('users')`); md = (await until(() => d.querySelector('.modal #a-users .mrow'))).closest('.modal');
  await until(() => md.querySelectorAll('#a-users .mrow').length >= 3);
  const rows = [...md.querySelectorAll('#a-users .mrow')];
  check(rows.length === 3 && rows[0].classList.contains('agsum') && /3 agents/.test(rows[0].textContent) && rows[0].querySelector('[data-act="agents-go"]'), '#1011: people only + one row "3 agents" ' + rows.map(x => x.textContent.trim().slice(0, 30)).join('|'));
  check(!rows.slice(1).some(x => /Managed under Agents|Claude|My bot/.test(x.textContent)), '#1011: no agent rows among the people');
  click(w, rows[0].querySelector('[data-act="agents-go"]')); await until(() => d.querySelector('#s-ags .agsrow'));
  await until(() => d.querySelectorAll('#s-ags .agsrow').length >= 3);
  const hs = [...d.querySelectorAll('#s-ags .aggh')].map(x => x.textContent.trim());
  check(hs.length === 3 && /Team agents/.test(hs[0]) && /My personal agents/.test(hs[1]) && /Personal agents of others/.test(hs[2]), '#1011: the agents grouped ' + hs.join('|'));
  const restr = d.querySelector('#s-ags .agrestr');
  check(restr && /Bob bot/.test(restr.textContent) && /Bob Baker/.test(restr.textContent) && restr.querySelectorAll('.agacts button').length === 1 && !restr.querySelector('[data-ag="edit"]'), '#965: Bob\'s personal agent: name, owner, the kill switch only');
  check(d.querySelector('#s-ags .agsrow[data-agid="' + AG + '"] .agws'), '#935: the workspace at the agent');
  const addBtn = d.querySelector('[data-ag="new"]');
  check(addBtn && /Add agent…/.test(addBtn.textContent), '#970: "Add agent…"');
  click(w, addBtn); await until(() => d.querySelector('#pop [role="menuitem"]'));
  const mi = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim());
  check(mi.length === 2 && /Team agent/.test(mi[0]) && /Personal agent/.test(mi[1]) && /Only you see and use it/.test(mi[1]), '#970: the chooser explains team and personal ' + mi.join(' | '));
  click(w, d.querySelectorAll('#pop [role="menuitem"]')[1]); await until(() => d.querySelector('#ag-owner'));
  const agmd = d.querySelector('#ag-owner').closest('.modal');
  check(/New personal agent/.test(agmd.querySelector('h3').textContent) && agmd.querySelector('#ag-owner').value === '1' && /Only this person sees/.test(agmd.querySelector('#ag-ownhint').textContent), '#970/#965: a personal agent belongs to me, the hint says what that means');
  check(agmd.querySelector('#ag-ws') && agmd.querySelector('#ag-ws').value === '', '#935: a personal agent starts private');
  const order = [...agmd.querySelectorAll('input')].map(x => x.id);
  check(order.indexOf('ag-name') < order.indexOf('ag-user'), '#926: the display name comes first ' + order.slice(0, 3));
  agmd.querySelector('#ag-name').value = 'Team Dev AI'; agmd.querySelector('#ag-name').dispatchEvent(new w.Event('input', {bubbles: true}));
  check(agmd.querySelector('#ag-user').value === 'team-dev-ai', '#926: the username is suggested from the display name ' + agmd.querySelector('#ag-user').value);
  agmd.querySelector('#ag-user').value = 'Bad Name'; agmd.querySelector('#ag-user').dispatchEvent(new w.Event('input', {bubbles: true}));
  check(!agmd.querySelector('#ag-userhint').hidden && /did you mean bad-name/.test(agmd.querySelector('#ag-userhint').textContent), '#926: a wrong username gets the suggestion ' + agmd.querySelector('#ag-userhint').textContent);
  agmd.remove();
  // Account > Workspaces
  w.eval(`settingsModal('account')`); await until(() => d.querySelector('#s-ws .wsorg'));
  const wsb = d.querySelector('#s-ws');
  check(wsb.textContent.includes(ORGN) && /you are an admin/.test(wsb.textContent) && wsb.querySelectorAll('.wsorg .mrow').length >= 2, '#935: Settings > Account > Workspaces lists the organisation and its members');
  check(wsb.querySelector('.wsorg .mrow .avatar.agent .abot-b'), '#985: agents among the members carry the badge');
  w.close();

  // ================= Firefox: screenshots of the changed screens + #976 the real right-click next to the grip
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); localStorage.setItem('tasks.newsBundle', 'false'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const q2 = await (await fetch(V + '/agent/chats/1', {method: 'POST', headers: AGH, body: JSON.stringify({body: 'Which checks shall I run?', choices: ['lint', 'tests', 'build'], multi: true})})).json();
  check(q2.choices?.multi === true, '#1005: a multi question for the screenshots');
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#today'); await ready(ev);
    check(await ev(`!!document.querySelector('#side .wsbar')`), `${tag}: #935 the switch in the sidebar`);
    await shot(`p2280-${th}-1440-today-all.png`);
    await ev(`(() => { wsSet('org:${ORG}'); return 1; })()`); await sleep(700);
    check(await ev(`!!document.querySelector('#top .wschip') && getComputedStyle(document.querySelector('#top .wschip')).display !== 'none'`), `${tag}: #935 the chip in the header`);
    await shot(`p2280-${th}-1440-today-org.png`);
    // #976: a REAL right-click on the list row right next to the sidebar grip
    const geo = await ev(`(() => { const r = document.querySelector('#side .srow[data-list="${W1}"]').getBoundingClientRect(), g = document.querySelector('#pgrip-side'); const gr = g ? g.getBoundingClientRect() : null; return {x: Math.round(r.right - 14), y: Math.round(r.top + r.height / 2), grip: gr ? [Math.round(gr.left), Math.round(gr.right)] : null}; })()`);
    check(geo.grip && geo.x > geo.grip[0] - 40, `${tag}: #976 the sidebar grip sits at the row's edge ${JSON.stringify(geo)}`);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: geo.x, y: geo.y}, {type: 'pointerDown', button: 2}, {type: 'pointerUp', button: 2}]}]});
    await cmd('input.releaseActions', {context: ctx}); await sleep(400);
    const menuTxt = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim()).join('|')`);
    check(/Archive/.test(menuTxt) && /Edit list/.test(menuTxt), `${tag}: #976 the right-click opened the list menu ` + menuTxt.slice(0, 80));
    check(await ev(`document.body.classList.contains('pop-open') && getComputedStyle(document.querySelector('#pgrip-side')).visibility === 'hidden'`), `${tag}: #976 the sidebar grip is invisible while the menu is open`);
    check(await ev(`(() => { const g = document.querySelector('#pgrip-side'), gr = g.getBoundingClientRect(), p = document.querySelector('#pop'), pr = p.getBoundingClientRect(); const x = Math.min(Math.max(gr.left + gr.width / 2, pr.left + 2), pr.right - 2); let hit = 0; for (const y of [pr.top + 10, pr.top + pr.height / 2, pr.bottom - 10]) { const e = document.elementFromPoint(x, y); if (e && (p.contains(e) || !g.contains(e))) hit++; } return hit === 3 && getComputedStyle(g, '::after').backgroundColor !== getComputedStyle(document.documentElement).getPropertyValue('--accent'); })()`), `${tag}: #976 nothing of the grip (line / tooltip) is hit over the menu`);
    await shot(`p2280-${th}-1440-sidebar-menu.png`);
    await ev(`(() => { closePop(); return 1; })()`); await sleep(200);
    check(await ev(`!document.body.classList.contains('pop-open') && getComputedStyle(document.querySelector('#pgrip-side')).visibility === 'visible'`), `${tag}: #976 the grip is back after the menu`);
    // a dialog: the grip steps aside too (the list dialog with the workspace field)
    await ev(`(() => { listModal(${W1}); return 1; })()`); await sleep(500);
    check(await ev(`document.body.classList.contains('modal-open') && getComputedStyle(document.querySelector('#pgrip-side')).visibility === 'hidden'`), `${tag}: #976 the grip steps aside under a dialog`);
    check(await ev(`!!document.querySelector('.modal #l-ws')`), `${tag}: #935 the Workspace field in the list dialog`);
    await shot(`p2280-${th}-1440-listdialog.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`); await sleep(300);
    check(await ev(`!document.body.classList.contains('modal-open')`), `${tag}: #976 back after the dialog`);
    await ev(`(() => { wsSet('all'); return 1; })()`); await sleep(400);
    await o.nav(B + '#news'); await ready(ev);
    for (let i = 0; i < 20 && (await ev(`document.querySelectorAll('#view .nsec').length`)) < 2; i++) await sleep(300);
    check(await ev(`!!document.querySelector('.ntabs [data-tab="all"].on') && document.querySelectorAll('#view .nsec').length === 2`), `${tag}: #987 News opens with the two sections`)
    await shot(`p2280-${th}-1440-news.png`);
    await ev(`(() => { document.querySelector('#top [data-act="bell-pop"]').click(); return 1; })()`); await sleep(700);
    await shot(`p2280-${th}-1440-bell.png`);
    await ev(`(() => { closePop(); return 1; })()`);
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(900);
    check(await ev(`document.querySelectorAll('#chat-msgs .cchoices').length >= 2`), `${tag}: #1005 the buttons in the chat`);
    await shot(`p2280-${th}-1440-chat-choices.png`);
    await ev(`(() => { settingsModal('agents'); return 1; })()`); await sleep(1200);
    await shot(`p2280-${th}-1440-settings-agents.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); settingsModal('account'); return 1; })()`); await sleep(1200);
    await ev(`(() => { document.querySelector('#s-ws')?.scrollIntoView(); return 1; })()`); await sleep(300);
    await shot(`p2280-${th}-1440-settings-workspaces.png`);
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
  });
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { document.querySelector('#top [data-act="side"]').click(); return 1; })()`); await sleep(600);
    check(await ev(`(() => { const b = document.querySelector('#side .wsbar'); return !!b && b.getBoundingClientRect().width > 200; })()`), `${tag}: #935 the switch in the drawer`);
    await shot('p2280-light-390-drawer.png');
    await ev(`(() => { wsSet('private'); return 1; })()`); await sleep(700);
    check(await ev(`!!document.querySelector('#top .wschip')`), `${tag}: #935 the chip on the phone`);
    await shot('p2280-light-390-today-private.png');
    await ev(`(() => { wsSet('all'); return 1; })()`); await sleep(300);
    await o.nav(B + '#news'); await ready(ev); await sleep(600);
    check(await ev(`(() => { const t = document.querySelector('.ntabs'); return !!t && t.getBoundingClientRect().width <= 390 && document.documentElement.scrollWidth <= 390; })()`), `${tag}: #987 the tabs fit the phone`);
    await shot('p2280-light-390-news.png');
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(900);
    check(await ev(`(() => { const b = document.querySelector('#chat-msgs .cchb'); return !!b && b.getBoundingClientRect().height >= 40; })()`), `${tag}: #1005 the buttons are at least 40 px high on touch`);
    await shot('p2280-light-390-chat-choices.png');
    await o.nav(B + '#home'); await ready(ev); await sleep(800);
    await shot('p2280-light-390-home.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
