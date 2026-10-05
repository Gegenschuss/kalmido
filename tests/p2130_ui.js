// 2.13.0 (#453) UI tests, own container (start.sh, isolated test database): the polish round after the UX review. One
// regression check per finding: chat reactions on hover / long press and 👍 = approval only on a question (A2), waiting
// jobs in the agent pill's menu and in Today (A6), Kanban touch drag scrolls slowly at the edge (A4), keyboard: focus
// ring, skip link, the sidebar as one tab stop (A9), the bell: an agent's comments grouped, back to the bell, undo of
// "Mark all as read" (A5), the view switch under the list title on phones and a menu without duplicates (A7), "Plan my
// day" (A8), #agents/<id> on Fold / desktop (A10), habit cells (A11), the toast above a sheet (A12), offline in words
// (A13), long press = select + a labelled selection bar (A14), the foldable sidebar (A15), setup step 2 after a reload
// (A16) and the "Feinschliff" items P1-P20, plus the helper texts behind (i). jsdom (logic) and Firefox headless via
// ff.js: 390 x 844 touch (with a keyboard-sized viewport), Fold 904 x 904 touch, desktop 1440 x 900; light + dark;
// German and French. Screenshots with P2130_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2130_ui', check, shots: 'P2130_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };  // local date (the container runs in Europe/Berlin)
const I18N = l => JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'static', 'i18n', l + '.json'), 'utf8'));

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:8[3-9]|9[0-9]|[1-9][0-9]{2})'/.test(SW), 'service worker cache v83');

  // ================= A16: the setup page's step 2 comes back after a reload until "Start"
  const su = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true})});
  check(su.status === 200, 'setup (the setup page sends wizard: true)');
  CK = await login('alice');
  check((await call('GET', '/api/state')).setup_pending === true, 'A16: step 2 pending after the account was created');
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await until(() => d.querySelector('.authscreen .supresets'), 80);
  check(!!d.querySelector('.authscreen .supresets') && d.querySelector('#app').hasAttribute('inert'), 'A16: a reload shows "What do you want to use?" again, the app behind is inert');
  w.close();
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  check((await call('GET', '/api/state')).setup_pending === false, 'A16: done after Start');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;

  // the data: a project shared with an agent, tasks, a checklist list
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, TOK = ag.token;
  const P = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  for (const n of ['Backlog', 'Doing', 'Review', 'Done']) await call('POST', '/api/sections', {list_id: P, name: n});
  const SECS = (await call('GET', '/api/state')).sections.filter(s => s.list_id === P).map(s => s.id);
  const T = [];
  for (let i = 1; i <= 6; i++) T.push((await call('POST', '/api/tasks', {title: 'Page ' + i, list_id: P, section_id: SECS[0], due: day(i)})).id);
  await tcall('GET', '/agent/events?since=0', TOK);  // online

  // ================= A2: reactions only on hover / long press; 👍 counts as approval only on a question
  const q1 = await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'Status: the build is green.'});
  const q2 = await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'Shall I deploy it now?\n\n```\nnpm run x?y\n```'});
  const msgs = (await call('GET', `/api/agents/${AG}/chat`)).messages;
  check(msgs.find(m => m.id === q1.id)?.asks === false && msgs.find(m => m.id === q2.id)?.asks === true, 'A2: the API says which agent message asks (asks)');
  check((await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'See https://example.org/?a=1 and `x?`'})).id && (await call('GET', `/api/agents/${AG}/chat`)).messages.pop().asks === false, 'A2: a ? in a link or code is no question');
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelectorAll('#chat-msgs .cmsg.ag').length >= 3);
  const r1 = d.querySelector(`#chat-msgs .cmsg[data-mid="${q1.id}"]`), r2 = d.querySelector(`#chat-msgs .cmsg[data-mid="${q2.id}"]`);
  // 2.18.0 (#651, intended change): the quick reactions are visible in the meta line of every message (no hidden bar)
  check(r1 && r1.querySelectorAll('.cmeta .rxrow .rx.add').length === 3 && !r1.querySelector('.rxhint') && !/counts as/.test(r1.querySelector('[data-e="up"]').getAttribute('aria-label')), 'A2 / #651: a status message: 👍 👎 ❤️ visible, plain reactions');
  check(r2 && !r2.querySelector('.rxhint'), 'A2: an older question has no "👍 = approval" hint (only the newest message)');
  check(d.querySelector('#achat .chath .ib[data-ii="chat-info"]') && !d.querySelector('#achat .chnote'), 'helper texts: the chat note is behind (i) in the header, not under the input');
  check(!d.querySelector('#chat-st .atdots'), 'P11: no typing dots in the header (only the line under the messages)');
  const rp1 = await call('POST', `/api/agents/${AG}/chat/${q1.id}/reactions`, {emoji: 'up'});
  check(rp1.status === 200 && rp1.approval === null, 'A2: 👍 on a status message is a plain reaction, no approval');
  const q3 = await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'May I merge the branch?'});
  await w.eval('chatLoad()'); await sleep(300);
  const r3 = () => d.querySelector(`#chat-msgs .cmsg[data-mid="${q3.id}"]`);
  check(r3()?.querySelector('.rxrow .rxhint')?.textContent === '👍 = approval', 'A2: the newest question shows its bar with "👍 = approval"');
  check(/counts as approval/.test(r3()?.querySelector('.rxrow [data-e="up"]')?.getAttribute('aria-label') || ''), 'A2: its 👍 says it counts as approval');
  click(w, r3().querySelector('.rxrow [data-e="up"]')); await until(() => r3()?.querySelector('.rxok'), 100);
  check(/Counted as approval/.test(r3()?.querySelector('.rxok')?.textContent || '') && !r3()?.querySelector('.rxhint') && r3()?.querySelector('.rxrow .rx.on[data-e="up"][aria-pressed="true"]'), 'A2: after 👍: "Counted as approval", 👍 pressed ' + (r3()?.innerHTML || '-').replace(/<svg.*?<\/svg>/g, '').slice(0, 400));
  check(/Approved/.test(d.querySelector('#toast')?.textContent || ''), 'A2: toast "Approved"');
  w.close();

  // ================= A6: a waiting job in the agent pill's menu and in Today
  const J = (await tcall('POST', '/agent/jobs', TOK, {title: 'Publish page 1', task_id: T[0], state: 'waiting', log: 'ready'})).id;
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#view .waitcard'), 60);
  const wc = d.querySelector('#view .waitcard');
  check(wc && /1 job waits for you/.test(wc.textContent) && /Publish page 1/.test(wc.textContent) && wc.querySelector(`[data-act="job-do"][data-a="approve"][data-jid="${J}"]`) && wc.querySelector('[data-a="reject"]'), 'A6: Today: "1 job waits for you" with Approve / Reject');
  await w.eval(`agentChipMenu(document.querySelector('#top .achip') || document.querySelector('#top h1'))`); await sleep(400);
  const mi = [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim());
  check(mi[0] && /Claude waits for you: Publish page 1/.test(mi[0]) && mi.some(t => /Approve/.test(t)) && mi.some(t => /Reject/.test(t)), 'A6: the agent pill menu starts with what waits for me: ' + mi.slice(0, 4).join(' | '));
  click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => /Approve/.test(b.textContent)));
  check(await until(async () => (await tcall('GET', `/agent/jobs/${J}`, TOK)).action === 'approve'), 'A6: Approve from the menu reaches the job');
  await w.eval('load().then(render)'); await sleep(600);
  check(!d.querySelector('#view .waitcard'), 'A6: the Today card goes once nothing waits');
  // A10: #agents/<id> opens the chat on a desktop
  w.close(); w = await boot({user: 'alice', hash: 'agents/' + AG}); d = w.document;
  check(await until(() => d.querySelector('#achat:not(.hidden) #chat-in')), 'A10: #agents/<id> opens the chat on Fold / desktop');
  w.close();

  // ================= A5: the bell: an agent's comments are one item; back to the bell; undo for "Mark all as read"
  for (const t of T.slice(0, 5)) await tcall('POST', `/tasks/${t}/comments`, TOK, {body: 'Checked page ' + t});
  const nw = await call('GET', '/api/news');
  const grp = nw.items.find(x => x.kind === 'comment' && x.agent);
  check(grp && grp.count === 5 && grp.tasks.length === 5 && nw.unread === 1, `A5: 5 agent comments on 5 tasks = one item, 1 unread (${nw.unread}, ${grp?.count}/${grp?.tasks?.length})`);
  const AN = (await call('POST', '/api/users', {username: 'anna', display_name: 'Anna', password: 'password123'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: AN, role: 'edit'});
  const CKA = await login('anna');
  await call('POST', `/api/tasks/${T[5]}/comments`, {body: 'Looks good'}, CKA);
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + P}); d = w.document;
  await w.eval(`bellPop(document.querySelector('#top .bell'))`); await until(() => d.querySelectorAll('#pop .bplist .nitem').length >= 2);
  const items = [...d.querySelectorAll('#pop .bplist .nitem')];
  check(items.some(n => /Claude left 5 comments on 5 tasks/.test(n.textContent)), 'A5: the bell: "Claude left 5 comments on 5 tasks"');
  const anna = items.find(n => /Anna commented/.test(n.textContent));
  click(w, anna); await until(() => w.eval('S.sel') === T[5]);
  check(w.eval('S.sel') === T[5] && d.querySelector('#pop').classList.contains('hidden'), 'A5: an item opens its task');
  w.eval('closeDetail()'); await sleep(500);
  check(!d.querySelector('#pop').classList.contains('hidden') && d.querySelector('#pop .bpop'), 'A5: Back returns to the bell');
  const u0 = w.eval('S.news.unread');
  click(w, d.querySelector('#pop [data-bp="readall"]')); await until(() => /marked as read/.test(d.querySelector('#toast')?.textContent || ''));
  check(/marked as read/.test(d.querySelector('#toast').textContent) && /Undo/.test(d.querySelector('#toast button')?.textContent || ''), 'A5: "Mark all as read" has an Undo');
  check((await call('GET', '/api/news')).unread === 0, 'A5: all read');
  d.querySelector('#toast button').click(); await sleep(800);
  check((await call('GET', '/api/news')).unread === u0 && u0 > 0, `A5: Undo makes them unread again (${u0})`);
  closeAll(w); w.close();
  // P9: the News view has one filter row
  w = await boot({user: 'alice', hash: 'news'}); d = w.document;
  await until(() => d.querySelector('#view .nitem'));
  check(d.querySelectorAll('#view .nchips').length === 1 && !d.querySelector('#view .nbar .seg') && d.querySelectorAll('#view .nchips button').length >= 2 && [...d.querySelectorAll('#view .nchips button')].filter(b => /^All$/.test(b.textContent.trim())).length === 1, 'P9: News: one filter row, "All" once: ' + [...d.querySelectorAll('#view .nchips button')].map(b => b.textContent.trim()).join('|'));
  click(w, d.querySelector('#view [data-act="news-filter"][data-f="me"]')); await sleep(600);
  check(w.eval('S.nf.filter') === 'me' && d.querySelector('#view [data-fme]').getAttribute('aria-pressed') === 'true', 'P9: "Mentions & assigned to me" is a chip in that row');
  click(w, d.querySelector('#view [data-fme]')); await sleep(600);
  check(w.eval('S.nf.filter') === '', 'P9: a second tap turns it off');
  w.close();

  // ================= A7: the view switch under the title on phones; the "…" menu without duplicates
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + P}); d = w.document;
  const seg = d.querySelector('#view .vsegm');
  check(seg && [...seg.querySelectorAll('button')].map(b => b.textContent.trim()).join('|') === 'Overview|List|Kanban|Timeline' && seg.querySelector('button.on[aria-pressed="true"]')?.textContent.trim() === 'List', 'A7: phone: Overview (first in projects) / List / Kanban / Timeline under the title, the active one marked');
  const more = w.eval('topMoreItems().filter(x => x !== "-").map(x => x.label || "")');
  check(!more.includes('List') && !more.includes('Kanban') && more.includes('As a list') && more.includes('As a project') && new Set(more).size === more.length, 'A7: "…" without the views, "As a list / As a project", no duplicates: ' + more.join(' | '));
  click(w, seg.querySelector('[data-act="view-kanban"]')); await until(() => d.querySelector('#view .kanban'));
  check(d.querySelector('#view .kanban') && d.querySelector('#view .vsegm button.on')?.textContent.trim() === 'Kanban', 'A7: a tap switches to Kanban');
  check(d.querySelector('#view .kadd input')?.getAttribute('aria-label') === 'New task in Backlog', 'P6: Kanban "+ Task" has a name');
  // task numbers: in the panel (copyable), "#id" in the command palette, "Show task numbers" for any list; no keyboard
  // popping up when a dialog opens on a phone
  w.eval(`openDetail(${T[0]})`); await sleep(400);
  check(d.querySelector('#detail .dcid')?.textContent === '#' + T[0], 'task number in the panel: #' + T[0]);
  w.eval('closeDetail()'); w.eval(`listModal(${P})`); await sleep(300);
  check(d.activeElement?.id !== 'l-name', 'phone: the list dialog does not focus its name field (no keyboard)');
  w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove())`);
  w.close();
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`openPalette(); PAL.q = '#${T[0]}'; palDraw()`);
  check(w.eval('PAL.items[0]?.id') === 'tid:' + T[0], 'palette: "#id" jumps to the task');
  w.eval(`PAL.q = '${T[0]}'; palDraw()`);
  check(w.eval('PAL.items[0]?.id') === 'tid:' + T[0], 'palette: a bare number too');
  w.eval('closePalette()');
  const shown = () => d.querySelectorAll('#view .trow .tgut').length;
  check(!shown(), 'numbers off by default (no tickets)');
  await w.eval(`colSave(${P}, ['id', 'due'], true)`); await sleep(300);
  check(shown() > 0, '2.14.0: the column "Task number" shows them in any list');
  await w.eval(`colSave(${P}, null, true)`); await sleep(200);
  w.close();
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});

  // ================= A13: offline in words; A14 multi bar; P8 quick add toast; P1 / P17; A8
  w = await boot({user: 'alice', mobile: true, hash: 'today'}); d = w.document;
  w.__offline = true; w.eval(`toggleTask(${T[4]})`); await sleep(400); w.eval('setOnline(false); staleDraw()');
  check(/Offline · 1 change waiting/.test(d.querySelector('#stale')?.textContent || ''), 'A13: "Offline · 1 change waiting": ' + (d.querySelector('#stale')?.textContent || '-'));
  w.__offline = false; w.eval('setOnline(true)'); await until(() => !w.eval('OUT.q.length'), 40); w.eval('S.syncOk = Date.now(); staleDraw()');
  check(!d.querySelector('#stale'), 'A13: back online: the chip goes');
  w.eval(`S.multiMode = true; S.multi.add(${T[0]}); renderMultiBar()`);
  const mb = [...d.querySelectorAll('#mbar .mbb:not([hidden])')].map(b => b.querySelector('.mbl')?.textContent);
  check(mb.join('|') === 'All|Today|Date|List|Completed|More' && d.querySelectorAll('#mbar .mbb[hidden]').length >= 5, 'A14: phone selection bar: labels, four actions + More: ' + mb.join('|'));
  click(w, d.querySelector('#mbar [data-act="mb-more"]')); await sleep(200);
  check(/Priority/.test(d.querySelector('#pop').textContent) && /Delete/.test(d.querySelector('#pop').textContent), 'A14: More holds the rest');
  closeAll(w); w.eval('S.multi.clear(); S.multiMode = false; render()');
  w.eval(`openQuickSheet('Call Bob tomorrow 10:00')`); await sleep(100);
  check(d.body.classList.contains('qsheet-open'), 'P8: the + button hides behind the add sheet');
  await w.eval(`submitQuick(document.querySelector('#qsheet'))`); await sleep(900);
  check(/Inbox · Tomorrow 10:00/.test(d.querySelector('#toast')?.textContent || '') && /Open/.test(d.querySelector('#toast button')?.textContent || ''), 'P8: where the task went: ' + d.querySelector('#toast')?.textContent);
  closeAll(w); w.close();

  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  check(d.querySelector('#view .lhead .lpg .lpx') && /Next due:/.test(d.querySelector('#view .lhead .lmeta')?.textContent || ''), 'P1: the × stays with the progress bar, "Next due: …"');
  w.eval(`setListView(routeList(), 'overview')`); await until(() => d.querySelector('#view .pov'));
  const sst = [...d.querySelectorAll('#view button')].filter(b => /Set status/.test(b.textContent));
  check(sst.length <= 1 && !d.querySelector('#view .lhead .stpill'), 'P1: "Set status" once in the overview ' + sst.map(b => b.className + '@' + (b.closest('[id], section')?.id || b.parentElement.className)).join(', '));
  w.eval(`setListView(routeList(), 'list')`); await sleep(300);
  // A8: Plan my day: planned + still free, the ones that do not fit get actions
  for (let i = 0; i < 5; i++) await call('POST', '/api/tasks', {title: 'Long ' + i, list_id: P, due: day(0), duration: 240});
  await w.eval('load().then(render)');
  w.eval(`dayplanModal('day')`); await until(() => d.querySelector('.dpm .dpsum'));
  const sum = d.querySelector('.dpm .dpsum').textContent;
  check(/planned/.test(sum) && /still free/.test(sum) && !/· \d+m free/.test(sum), 'A8: the header says planned + still free: ' + sum);
  const nf = d.querySelector('.dpm [data-dp="nofit-tm"]');
  check(nf && d.querySelector('.dpm [data-dp="nofit-date"]'), 'A8: "Does not fit today" offers Tomorrow / Plan on …');
  const nid = +nf.dataset.id; click(w, nf);
  check(await until(async () => ((await call('GET', '/api/state')).tasks.find(t => t.id === nid)?.plan_start || '').startsWith(day(1))), 'A8: Tomorrow plans it for tomorrow (its due date stays)');
  check((await call('GET', '/api/state')).tasks.find(t => t.id === nid)?.due === day(0), 'A8: … the due date is unchanged');
  closeAll(w); w.close();

  // ================= P19: a "done at the bottom" list adds new items at the end
  const EK = (await call('POST', '/api/lists', {name: 'Shopping'})).id;
  await call('PATCH', `/api/lists/${EK}`, {checklist: true});
  for (const n of ['Eggs', 'Milk', 'Bread']) await call('POST', '/api/tasks', {title: n, list_id: EK});
  const ek = (await call('GET', '/api/state')).tasks.filter(t => t.list_id === EK).sort((a, b) => a.sort - b.sort).map(t => t.title);
  check(ek.join() === 'Eggs,Milk,Bread', 'P19: new items land at the end: ' + ek.join());

  // ================= P2 / P3 / P5 / P7: language
  check(I18N('de')['Next|section'] === 'Als Nächstes' && I18N('fr')['Done|section'] === 'Terminé', 'P2: the software project sections are translated');
  check(I18N('fr').Inbox === 'Boîte de réception', 'P3: "Boîte" with the circumflex');
  check(I18N('de')['Next week'] === 'Nächste Woche', 'P5: "Nächste Woche" in full');
  const bad = await fetch(B + 'api/auth/login', {method: 'POST', headers: {...H, 'Accept-Language': 'fr-FR,fr;q=0.9'}, body: JSON.stringify({username: 'alice', password: 'wrong-one'})});
  check(/(incorrect|Nom d’utilisateur|mot de passe)/i.test((await bad.json()).error || ''), 'P7: a failed login answers in the page\'s language (fr)');
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`datePop(document.querySelector('#view .trow'), ${T[0]})`); await sleep(300);
  if (!d.querySelector('#p-dur')) { d.querySelector('#p-time').value = '10:00'; d.querySelector('#p-time').dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(300); }
  const durs = [...(d.querySelector('#p-dur')?.options || [])].map(o => o.textContent);
  check(durs.includes('Dauer 1,5 h') && d.querySelector('#p-dur').getAttribute('aria-label') === 'Dauer', 'P4 / P5: "Dauer 1,5 h", the select has a name');
  check(d.querySelector('#p-rep')?.getAttribute('aria-label') && /Erinnerung/.test(d.querySelector('#pop .prow .plab')?.textContent || ''), 'P5: repeat select named, the reminders have a label');
  closeAll(w); w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});
  // P6: names
  w = await boot({user: 'alice', hash: 'cal'}); d = w.document;
  check(d.querySelector('[data-act="cal-prev"]')?.getAttribute('aria-label') === 'Previous period' && d.querySelector('[data-act="cal-next"]')?.getAttribute('aria-label') === 'Next period', 'P6: calendar ‹ › have names');
  w.close();
  w = await boot({user: 'alice', hash: 'search'}); d = w.document;
  check(d.querySelector('#searchq')?.getAttribute('aria-label') === 'Search', 'P6: the search field has a name');
  w.close();

  // ================= helper texts: settings, the list dialog
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('general')`); await sleep(400);
  const inl = () => [...d.querySelectorAll('.smodal .shint')].filter(h => !h.classList.contains('iisrc'));
  check(d.querySelectorAll('.smodal .ib[data-ii]').length >= 15 && inl().every(h => h.matches('.keep, .cnote, .warn, .wpstate, .updline, .aanone, .aimodoff, [role], [aria-live]') || h.querySelector('a, button, code, input, select') || !h.textContent.trim()), `helper texts: settings: ${d.querySelectorAll('.smodal .ib[data-ii]').length} behind (i), inline only the kept ones (${inl().length})`);
  const ib = d.querySelector('[data-pane="general"] .ib[data-ii]');
  check(ib && d.getElementById(ib.dataset.ii)?.textContent.length > 10 && ib.getAttribute('aria-describedby') === ib.dataset.ii, 'helper texts: (i) is described by its text');
  click(w, ib); await sleep(100);
  check(!d.querySelector('#iitip').classList.contains('hidden') && d.querySelector('#iitip').textContent === d.getElementById(ib.dataset.ii).textContent.trim() && ib.getAttribute('aria-expanded') === 'true', 'helper texts: a tap shows it');
  click(w, d.querySelector('.smodal h3')); await sleep(50);
  check(d.querySelector('#iitip').classList.contains('hidden'), 'helper texts: a tap elsewhere hides it');
  // P20: search the settings
  const ss = d.querySelector('#s-search'); ss.value = 'working hours'; ss.dispatchEvent(new w.Event('input', {bubbles: true}));
  const hit = d.querySelector('#s-sres [data-hit]');
  check(hit && /Working hours/i.test(hit.textContent), 'P20: settings search finds "Working hours"');
  w.eval(`document.querySelector('.snav [data-sec="look"]').click()`); click(w, d.querySelector('#s-sres [data-hit]')); await sleep(100);
  check(!d.querySelector('.spane[data-pane="general"]').classList.contains('hidden'), 'P20: a hit opens its tab');
  closeAll(w);
  w.eval(`listModal(${P})`); await sleep(500);
  check(d.querySelectorAll('.lmodal .ib[data-ii]').length >= 3, `helper texts: list dialog: ${d.querySelectorAll('.lmodal .ib[data-ii]').length} behind (i)`);
  closeAll(w); w.close();
  // A15: the sidebar can be folded away below 1100 px
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`sideFold(true)`); await sleep(100);
  check(d.querySelector('#app').classList.contains('side-rail') && w.eval(`LS.get('sideFold')`) === true, 'A15: folded sidebar (drawer) on a ~1000 px window, remembered');
  w.eval(`sideFold(false)`); await sleep(100);
  check(!d.querySelector('#app').classList.contains('side-rail'), 'A15: back');
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));
  w.close();

  // ================= an attachment whose file got lost (empty on disk after a copy): 410, and the panel says so
  const ATT = await (async () => { const fd = new FormData(); fd.append('file', new Blob([Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==', 'base64')], {type: 'image/jpeg'}), 'photo.jpg');
    const r = await fetch(B + `api/tasks/${T[3]}/attachments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd}); const j = await r.json(); return (j.attachments || []).pop(); })();
  { const r1 = await fetch(B + `api/attachments/${ATT.id}?v=${ATT.size}`, {headers: {Cookie: CK}}), r2 = await fetch(B + 'api/attachments/' + ATT.id, {headers: {Cookie: CK}});
    check(r1.status === 200 && /max-age=86400/.test(r1.headers.get('cache-control')) && r2.status === 200 && /no-cache/.test(r2.headers.get('cache-control')), 'attachment: the versioned address (?v=size) is cached, the bare one revalidates'); }
  const attDir = path.join(DATA, 'attachments'), attFile = fs.readdirSync(path.join(attDir, String(T[3]))).map(f => path.join(attDir, String(T[3]), f))[0];
  fs.truncateSync(attFile, 0);
  { const r = await fetch(B + `api/attachments/${ATT.id}?v=${ATT.size}`, {headers: {Cookie: CK}});
    check(r.status === 410 && r.headers.get('cache-control') === 'no-store', 'attachment: an empty file on disk answers 410, never cached'); }
  const sc = await call('GET', '/api/admin/storage-check');
  check(sc.checked >= 1 && sc.problems.some(p => p.kind === 'attachment' && p.id === ATT.id && p.problem === 'empty' && p.owner === T[3]), 'Settings > Administration > Check storage lists the damaged file');

  // ================= notes on a flaky network (a phone): saved when the field is left / every 5 s, queued offline text is
  // coalesced, a "conflict" with our own earlier save is none, a real one keeps the draft and shows a calm bar
  {
    w = await boot({user: 'alice', mobile: true, hash: 'l/' + P}); d = w.document;
    const TT = T[2];
    w.eval(`openDetail(${TT})`); await until(() => d.querySelector('#d-content'));
    const ta = () => d.querySelector('#d-content');
    const typeIt = v => { const t = ta(); t.focus(); t.value = v; t.dispatchEvent(new w.Event('input', {bubbles: true})); };
    const srv = async () => (await call('GET', '/api/state')).tasks.find(t => t.id === TT).content || '';
    typeIt('Hello'); await sleep(1200);
    check(await srv() === '', 'notes: no save every keystroke pause (the 600 ms autosave is gone)');
    w.__offline = true; await w.eval('flushSaves()');
    typeIt('Hello world'); await w.eval('flushSaves()'); typeIt('Hello world, offline'); await w.eval('flushSaves()');
    const q = w.eval(`OUT.q.filter(e => e.url === '/api/tasks/${TT}').length`);
    check(q === 1 && d.activeElement === ta() && ta().value === 'Hello world, offline', `offline: the queued text is coalesced into one entry (${q}), focus + text kept`);
    w.__offline = false; await w.eval('flush()'); await sleep(400);
    check(await srv() === 'Hello world, offline' && !w.eval('S.conflicts.length') && d.activeElement === ta(), 'back online: the latest text arrives, no conflict, the field keeps the focus');
    // a save whose answer got lost: the server has it, the device still builds on the older text
    await call('PATCH', `/api/tasks/${TT}`, {content: 'Lost answer', _prev: {content: 'Hello world, offline'}});
    w.eval(`S.sentVals['${TT}:content'].push('Lost answer')`);
    typeIt('Lost answer and more'); await w.eval('flushSaves()'); await sleep(300);
    check(await srv() === 'Lost answer and more' && !w.eval('S.conflicts.length') && !d.querySelector('.cfbar'), 'a "conflict" with our own earlier save is none: the newest text goes on top');
    // a real conflict: Anna changed the notes meanwhile
    await call('PATCH', `/api/tasks/${TT}`, {content: 'Anna wrote this'}, CKA);
    typeIt('Lost answer and more, my draft'); await w.eval('flushSaves()'); await sleep(300);
    check(d.querySelector('#detail .cfbar') && d.activeElement === ta() && ta().value === 'Lost answer and more, my draft' && await srv() === 'Anna wrote this', 'a real conflict: the draft and the focus stay, a calm bar under the field');
    click(w, d.querySelector('#detail .cfbar [data-cfi="mine"]')); await sleep(500);
    check(await srv() === 'Lost answer and more, my draft' && !d.querySelector('.cfbar') && !w.eval(`S.conflicts.some(c => c.tid === ${TT})`), '"Keep mine" saves the draft on top of the other version');
    check(!errs.length, 'flaky network: no JS errors ' + errs.join(' | '));
    ta().blur(); w.close();
  }

  // ================= Firefox
  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  const CTR = `(fg, bg) => { const p = s => s.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => /^color\\(/.test(s) ? v * 255 : v).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); const L = c => { const [r, g, b] = p(c); return .2126 * r + .7152 * g + .0722 * b; }; const a = L(fg), b = L(bg); return (Math.max(a, b) + .05) / (Math.min(a, b) + .05); }`;
  const bgOf = `el => { for (let n = el; n; n = n.parentElement) { const c = getComputedStyle(n).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; } return 'rgb(255,255,255)'; }`;

  // ---- phone 390 x 844, touch, light, German
  await call('PATCH', '/api/settings', {lang: 'de'});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}, 'light') === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    const tap = (x, y, hold = 60) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: hold}, {type: 'pointerUp', button: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    // P11: the chat: its header replaces the page header, back on the left; A2: the hidden bar opens with a long press
    await nav(B + '?p=1#agents/' + AG); await sleep(2200);
    const ch = await ev(`(() => { const h = document.querySelector('.chview .chath'); const m = [...document.querySelectorAll('#chat-msgs .cmsg.ag')].find(x => /build is green/.test(x.textContent)); const q = m && m.querySelector('.rxrow .rx.add'); return {inChat: document.body.classList.contains('in-chat'), top: getComputedStyle(document.querySelector('#top')).display, first: h && h.firstElementChild.classList.contains('chback'), shown: q ? +getComputedStyle(q).opacity : null, mh: m ? Math.round(m.getBoundingClientRect().height) : 0, note: !!document.querySelector('.chnote')}; })()`);
    check(ch.inChat && ch.top === 'none' && ch.first && ch.shown >= .6 && !ch.note, '390 P11 / #651: chat header replaces the page header, back on the left, quick reactions visible (2.18.0), no note under the input ' + JSON.stringify(ch));
    await shot('p2130-chat-390.png');
    const op = await ev(`(() => { const m = [...document.querySelectorAll('#chat-msgs .cmsg.ag')].find(x => /build is green/.test(x.textContent)); m.querySelector('.rxtog')?.click(); const b = m.querySelector('.rxrow .rx.add'); const r = b ? b.getBoundingClientRect() : {width: 0, height: 0}; return {w: r.width, h: r.height}; })()`);
    check(op.w >= 43.5 && op.h >= 43.5, '390 #651: the visible reactions are 44 px targets ' + JSON.stringify(op));
    // the (i) next to the agent's name
    const ir = await ev(`(() => { const b = document.querySelector('.chath .ib'); const r = b.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
    await tap(ir.x, ir.y); await sleep(200);
    const tip = await ev(`(() => { const t = document.querySelector('#iitip'); const r = t.getBoundingClientRect(); return {on: !t.classList.contains('hidden'), txt: t.textContent.slice(0, 40), in: r.left >= 0 && r.right <= innerWidth && r.top >= 0}; })()`);
    check(tip.on && tip.in && tip.txt.length > 10, '390 helper texts: a tap on (i) in the chat header shows the note on screen ' + JSON.stringify(tip));
    await tap(200, 400); await sleep(100);
    // an image attachment whose file is gone: a tile that says so instead of a broken image
    await nav(B + '?att=1#l/' + P); await ready(ev);
    await ev(`(() => { openDetail(${T[3]}); return 1; })()`); await sleep(1500);
    const at = await ev(`(() => { const b = document.querySelector('#detail .att.broken'); return {broken: !!b, txt: b ? b.textContent : '', img: document.querySelectorAll('#detail .att.img img').length}; })()`);
    check(at.broken && /fehlt|missing/i.test(at.txt) && !at.img, '390: an attachment whose file is gone shows "missing", not a broken image ' + JSON.stringify(at));
    // 2.13.2: on a phone closeDetail() goes history.back() (the task's history entry); that navigation lands after the next
    // nav() and took the page back to the previous document (the flaky A7 / "listModal is not defined"): wait for it first
    await ev(`(() => { closeDetail(); return 1; })()`);
    for (let i = 0; i < 30 && await ev(`!!(history.state && history.state.detail)`).catch(() => true); i++) await sleep(100);
    await sleep(300);
    // A7: the view switch; A11 habits; P13 contrast
    await nav(B + '?p=2#l/' + P); await ready(ev);
    const vs = await ev(`(() => { const s = document.querySelector('#view .vsegm'); if (!s) return null; const r = s.getBoundingClientRect(); return {n: s.querySelectorAll('button').length, h: Math.min(...[...s.querySelectorAll('button')].map(b => b.getBoundingClientRect().height)), right: r.right, vw: innerWidth, txt: s.textContent}; })()`);
    check(vs && vs.n === 4 && vs.h >= 43.5 && vs.right <= vs.vw + .5 && /Liste/.test(vs.txt) && /Übersicht/.test(vs.txt), '390 A7: the view switch under the title (German), 44 px, inside the screen ' + JSON.stringify(vs));
    const ctr = await ev(`(() => { const C = ${CTR}, bg = ${bgOf}; const sp = [...document.querySelectorAll('#tabs button:not(.on) > span')].filter(s => s.offsetWidth)[0]; return sp ? C(getComputedStyle(sp).color, bg(sp)) : 0; })()`);
    check(ctr >= 4.5, '390 P13: inactive tab label contrast ' + ctr.toFixed(2));
    await shot('p2130-list-390.png');
    // the list dialog with its (i)
    await ev(`(() => { listModal(${P}); return 1; })()`); await sleep(700);
    const ld = await ev(`(() => ({ib: document.querySelectorAll('.lmodal .ib[data-ii]').length, inl: [...document.querySelectorAll('.lmodal .shint')].filter(h => h.offsetHeight).length}))()`);
    check(ld.ib >= 3, '390 helper texts: list dialog ' + JSON.stringify(ld));
    await shot('p2130-listdialog-390.png');
    await ev(`(() => { document.querySelectorAll('.modal:not(.authscreen)').forEach(x => x.remove()); return 1; })()`);
    await nav(B + '?p=3#habits'); await ready(ev);
    await ev(`fetch('/api/habits', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({name: 'Walk'})}).then(() => load()).then(() => { render(); return 1; })`); await sleep(600);
    const hc = await ev(`(() => { const c = [...document.querySelectorAll('.hweek:not(.head) .hc')]; const r = c.map(x => x.getBoundingClientRect()); return {n: c.length, w: Math.min(...r.map(x => x.width)), h: Math.min(...r.map(x => x.height)), over: document.documentElement.scrollWidth > innerWidth}; })()`);
    check(hc.n >= 7 && hc.w >= 43.5 && hc.h >= 43.5 && !hc.over, '390 A11: habit day cells 44 px, no overflow ' + JSON.stringify(hc));
    // A12: a toast above an open sheet
    await nav(B + '?p=4#l/' + P); await ready(ev);
    await ev(`(() => { toast('Erledigt', () => {}); snoozeSheet(${T[1]}); return 1; })()`); await sleep(500);
    const ts = await ev(`(() => { const t = document.querySelector('#toast').getBoundingClientRect(), s = document.querySelector('#pop.sheet').getBoundingClientRect(); return {tb: Math.round(t.bottom), st: Math.round(s.top), tt: Math.round(t.top), overlap: !(t.bottom <= s.top + 1 || t.top >= s.bottom)}; })()`);
    check(!ts.overlap, '390 A12: the toast does not cover the sheet ' + JSON.stringify(ts));
    await ev(`(() => { closePop(); return 1; })()`);
    // A14: long press on a row = select
    const rw = await ev(`(() => { const r = document.querySelector('#view .trow .tmain').getBoundingClientRect(); return {x: r.left + 30, y: r.top + r.height / 2}; })()`);
    await tap(rw.x, rw.y, 700); await sleep(400);
    const sel = await ev(`(() => { const b = document.querySelector('#mbar'), r = b.getBoundingClientRect(); return {mode: S.multiMode, n: S.multi.size, vis: !b.classList.contains('hidden'), in: r.left >= 0 && r.right <= innerWidth + .5, lab: [...b.querySelectorAll('.mbb:not([hidden]) .mbl')].map(x => x.textContent).join('|')}; })()`);
    check(sel.mode && sel.n === 1 && sel.vis && sel.in && /Heute/.test(sel.lab), '390 A14: long press selects the row, the bar fits with labels ' + JSON.stringify(sel));
    await shot('p2130-select-390.png');
    await ev(`(() => { S.multi.clear(); S.multiMode = false; render(); return 1; })()`);
    // the keyboard: the chat with a keyboard-sized viewport keeps the newest message in view (#453 N4 still holds)
    await nav(B + '?p=5#agents/' + AG); await sleep(2000);
    await ev(`(() => { document.querySelector('#chat-in').focus(); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 464}}); await sleep(700);
    const kb = await ev(`(() => { const b = document.querySelector('#chat-msgs'); return {kb: document.body.classList.contains('kb-open'), h: Math.round(b.clientHeight), gap: Math.round(b.scrollHeight - b.scrollTop - b.clientHeight)}; })()`);
    check(kb.kb && kb.h >= 260 && kb.gap <= 2, '390 keyboard: the chat without the page header has more room ' + JSON.stringify(kb));
    await shot('p2130-chat-keyboard-390.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}}); await sleep(300);
    // settings with the search and the (i)
    await nav(B + '?p=6#today'); await ready(ev);
    await ev(`(() => { settingsModal('general'); return 1; })()`); await sleep(700);
    const st = await ev(`(() => { const s = document.querySelector('#s-search').getBoundingClientRect(); return {s: s.width > 100 && s.right <= innerWidth, ib: document.querySelectorAll('.smodal .ib').length}; })()`);
    check(st.s && st.ib > 10, '390 P20: the settings search is on screen, (i) buttons ' + JSON.stringify(st));
    await shot('p2130-settings-390.png');
  }, true);

  // ---- #429: the font size slider at its ends on a phone: 150 % without sideways overflow, 50 % with 44 px touch targets
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}, 'light') === 200, '#429: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    for (const pct of [150, 50]) {
      await ev(`(() => { localStorage.setItem('tasks.fsize', '${pct}'); return 1; })()`);
      await nav(B + `?fs=${pct}#l/` + P); await ready(ev);
      const r = await ev(`(() => { const small = [...document.querySelectorAll('#top button, #view .iconbtn, #tabs button, #view .vsegm button')].filter(e => e.offsetWidth).filter(e => e.getBoundingClientRect().height < 43.5).map(e => (e.className || e.tagName) + ':' + Math.round(e.getBoundingClientRect().height)); return {ui: getComputedStyle(document.documentElement).getPropertyValue('--ui').trim(), over: document.documentElement.scrollWidth > innerWidth, small, h1: !!document.querySelector('#top h1')?.offsetWidth}; })()`);
      check(!r.over && r.h1 && (pct === 150 || !r.small.length), `390 #429 ${pct} %: no sideways overflow, the title shows` + (pct === 50 ? ', touch targets still 44 px ' : ' ') + JSON.stringify(r));
      await shot(`p2130-fontsize-${pct}-390.png`);
    }
    await ev(`(() => { localStorage.removeItem('tasks.fsize'); return 1; })()`);
  }, true);

  // ---- iPhone behaviour (simulated: iOS keeps innerHeight and only shrinks window.visualViewport): the add sheet and
  // the date sheet sit above the "keyboard", the chat never overflows sideways (390 and 428 wide)
  for (const vw of [390, 428]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}, 'dark') === 200, `${vw} iOS: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 926}});
    await nav(B + `?ios=${vw}#l/` + P); await ready(ev);
    const FAKE = `(h, top) => { const t = new EventTarget(); Object.assign(t, {height: h, width: innerWidth, offsetTop: top, offsetLeft: 0, pageTop: top, scale: 1}); Object.defineProperty(window, 'visualViewport', {configurable: true, value: t}); vvSync(); }`;
    await ev(`(() => { openQuickSheet(''); return 1; })()`); await sleep(300);
    await ev(`(${FAKE})(560, 0)`); await sleep(200);
    const q = await ev(`(() => { const r = document.querySelector('#qsheet').getBoundingClientRect(); return {bottom: Math.round(r.bottom), lim: visualViewport.height + visualViewport.offsetTop, vvb: getComputedStyle(document.documentElement).getPropertyValue('--vvb')}; })()`);
    check(q.bottom <= q.lim, `${vw} iOS: the add sheet's field sits above the keyboard ` + JSON.stringify(q));
    await shot(`p2130-ios-quickadd-${vw}.png`);
    await ev(`(() => { closePop(); return 1; })()`);
    await ev(`(() => { snoozeSheet(${T[1]}); return 1; })()`); await sleep(300);
    const sh = await ev(`(() => { const r = document.querySelector('#pop.sheet').getBoundingClientRect(); return {bottom: Math.round(r.bottom), lim: visualViewport.height + visualViewport.offsetTop}; })()`);
    check(sh.bottom <= sh.lim + 1, `${vw} iOS: a bottom sheet sits above the keyboard ` + JSON.stringify(sh));
    await ev(`(() => { closePop(); return 1; })()`);
    await nav(B + `?ios2=${vw}#agents/` + AG); await sleep(2200);
    await ev(`(() => { document.querySelector('#chat-in').focus(); return 1; })()`);
    await ev(`(${FAKE})(560, 0)`); await sleep(300);
    const ch = await ev(`(() => { const c = document.querySelector('#chat-in').getBoundingClientRect(), s = document.querySelector('[data-act="chat-send"]').getBoundingClientRect(); return {sw: document.scrollingElement.scrollWidth, iw: innerWidth, send: Math.round(s.right), inBottom: Math.round(c.bottom), lim: visualViewport.height, gap: Math.round(visualViewport.height - c.bottom), meta: document.querySelector('meta[name=viewport]').content}; })()`);
    check(ch.sw <= ch.iw && ch.send <= ch.iw && ch.inBottom <= ch.lim + 1 && ch.gap < 90, `${vw} iOS: chat: no sideways overflow, Send on screen, the box right above the keyboard ` + JSON.stringify(ch));
    await shot(`p2130-ios-chat-${vw}.png`);
  }, true);

  // ---- Fold 904 x 904, touch, dark, French
  await call('PATCH', '/api/settings', {lang: 'fr'});
  await call('PATCH', `/api/lists/${P}`, {view: 'kanban'});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}, 'dark') === 200, '904: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 904, height: 904}});
    await nav(B + '?f=1#l/' + P); await ready(ev);
    // A4: a card held at the right edge: the board scrolls slowly (no jump of 3 columns in 300 ms)
    const k0 = await ev(`(() => { const k = document.querySelector('#view .kanban'); k.style.scrollBehavior = 'auto'; const c = k.querySelector('.kcol .trow .tmain').getBoundingClientRect(), kr = k.getBoundingClientRect(), col = k.querySelector('.kcol').getBoundingClientRect().width; return {id: +k.querySelector('.kcol .trow').dataset.id, sec: S.tasks.get(+k.querySelector('.kcol .trow').dataset.id).section_id, x: c.left + Math.min(60, c.width / 2), y: c.top + c.height / 2, edge: Math.min(innerWidth, kr.right) - 6, col, sw: k.scrollWidth, cw: k.clientWidth}; })()`);
    if (k0.sw > k0.cw + 50) {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [
        {type: 'pointerMove', x: Math.round(k0.x), y: Math.round(k0.y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 500},
        {type: 'pointerMove', x: Math.round((k0.x + k0.edge) / 2), y: Math.round(k0.y), duration: 150}, {type: 'pointerMove', x: Math.round(k0.edge), y: Math.round(k0.y), duration: 150},
        {type: 'pause', duration: 300}]}]});
      const s300 = await ev(`document.querySelector('#view .kanban').scrollLeft`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pause', duration: 900}]}]});
      const s1200 = await ev(`document.querySelector('#view .kanban').scrollLeft`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerUp', button: 0}]}]}); await cmd('input.releaseActions', {context: ctx}); await sleep(900);
      check(s300 < k0.col * .9 && s1200 > s300, `904 A4: edge scroll: after 300 ms ${s300} px (< 1 column of ${Math.round(k0.col)}), then on to ${s1200}`);
      const moved = await ev(`fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.tasks.find(t => t.id === ${k0.id}).section_id)`);
      check(moved !== k0.sec && moved !== undefined, '904 A4: the card was dropped into a column (not discarded): section ' + moved);
    } else check(true, '904 A4: board fits, no edge scroll needed');
    await shot('p2130-kanban-904-dark-fr.png');
    // A15: the sidebar can be folded away; the (i) and the logo in the accent
    const sf = await ev(`(() => { const b = document.querySelector('#side .sfold'); if (!b) return null; b.click(); return new Promise(r => setTimeout(() => r({rail: document.querySelector('#app').classList.contains('side-rail'), logo: getComputedStyle(document.querySelector('.sbrand svg.logo') || document.body).color}), 300)); })()`);
    check(sf && sf.rail, '904 A15: "Fold the sidebar away" turns it into a drawer ' + JSON.stringify(sf));
    await ev(`(() => { sideFold(false); return 1; })()`);
    // P15: the week view: only the hour grid scrolls
    await nav(B + '?f=2#cal'); await ready(ev);
    await ev(`(() => { const b = document.querySelector('[data-cv="week"], [data-act="cal-view"][data-v="week"]'); if (b) b.click(); else { S.calView = 'week'; LS.set('calView', 'week'); renderView(); } return 1; })()`); await sleep(700);
    const cw = await ev(`(() => { const v = document.querySelector('#view'), wb = document.querySelector('#wbody'); return wb ? {view: v.scrollHeight - v.clientHeight, wb: wb.scrollHeight > wb.clientHeight} : null; })()`);
    check(!cw || (cw.view <= 1 && cw.wb), '904 P15: week view: the page does not scroll, the hour grid does ' + JSON.stringify(cw));
    await shot('p2130-week-904-dark-fr.png');
    // P3 (fr): the overdue card keeps its × in the corner
    await call('POST', '/api/tasks', {title: 'En retard', list_id: P, due: day(-2)});
    await nav(B + '?f=3#today'); await ready(ev);
    const od = await ev(`(() => { const o = document.querySelector('#view .odban'); if (!o) return null; const x = o.querySelector('[data-act="od-hide"]').getBoundingClientRect(), r = o.getBoundingClientRect(); return {corner: x.right >= r.right - 8 && x.top <= r.top + 8, h: Math.min(...[...o.querySelectorAll('.btn')].map(b => b.getBoundingClientRect().height))}; })()`);
    check(od && od.corner && od.h >= 43.5, '904 P3 / P14: the overdue card: × in its corner, 44 px buttons ' + JSON.stringify(od));
    await shot('p2130-today-904-dark-fr.png');
  }, true);

  // ---- the unfolded Fold with the chat (screenshots from a real device): 904 x 680 and 904 x 904, sidebar open and folded; a
  // rotation while the chat is open (1200 x 904 <-> 904 x 1200): below 1000 px the chat is a full page with Back, at 1200
  // the main area sits beside the panel (never under it); the draft, the focus and the newest message stay
  await call('PATCH', '/api/settings', {lang: 'de'});
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}, 'dark') === 200, 'Fold chat: login');
    const vp = (w, h) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
    const LAY = `(() => { const v = document.querySelector('#view'), m = document.querySelector('#main').getBoundingClientRect(), a = document.querySelector('#achat:not(.hidden)'), ar = a && a.getBoundingClientRect(), sd = document.querySelector('#side'), sr = sd.getBoundingClientRect(), side = getComputedStyle(sd).display !== 'none' && sr.width > 0 && sr.right > 0 && !document.querySelector('#app').classList.contains('side-rail');
      const t = [...document.querySelectorAll('#view .trow .tmain')].filter(e => e.offsetWidth).map(e => e.getBoundingClientRect().width), fab = document.querySelector('#fab');
      return {iw: innerWidth, main: Math.round(m.width), mainR: Math.round(m.right), panel: ar ? Math.round(ar.left) : -1, full: !!document.querySelector('#view .chview'), back: !!document.querySelector('#view .chview .chback'), side, sideW: side ? Math.round(sr.width) : 0,
        ttl: t.length ? Math.round(Math.min(...t)) : null, fab: !!fab && getComputedStyle(fab).display !== 'none' && !fab.classList.contains('gone'), dots: !!document.querySelector('#chat-st .atdots'), note: !!document.querySelector('.chnote'),
        draft: document.querySelector('#chat-in')?.value, focus: document.activeElement?.id, gap: (() => { const b = document.querySelector('#chat-msgs'); return b ? Math.round(b.scrollHeight - b.scrollTop - b.clientHeight) : null; })()}; })()`;
    for (const [w, h] of [[904, 680], [904, 904]]) for (const fold of [false, true]) {
      await vp(w, h);
      await nav(B + `?fold=${w}${h}${fold}#l/` + P); await ready(ev);
      await ev(`(() => { LS.set('sideFold', ${fold}); fitLayout(); render(); return 1; })()`); await sleep(300);
      let L = await ev(LAY);
      check(!L.fab && L.ttl > 200, `${w}x${h} ${fold ? 'folded' : 'sidebar'}: the list: no + button next to the add bar, titles get room ` + JSON.stringify(L));
      await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1500);
      L = await ev(LAY);
      check(L.full && L.back && L.panel === -1 && L.main >= w - L.sideW - 2 && !L.dots && !L.note, `${w}x${h} ${fold ? 'folded' : 'sidebar'}: the chat is a full page beside the sidebar, Back, no dots / note ` + JSON.stringify(L));
      await shot(`p2130-fold-chat-${w}x${h}-${fold ? 'folded' : 'sidebar'}.png`);
      await ev(`(() => { document.querySelector('#view .chback').click(); return 1; })()`); await sleep(800);
      check(await ev(`location.hash`) === '#l/' + P, `${w}x${h}: Back returns to the list`);
    }
    await ev(`(() => { LS.set('sideFold', false); return 1; })()`);
    // the rotation while the chat is open
    await vp(1200, 904); await nav(B + '?rot=1#l/' + P); await ready(ev);
    await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1500);
    await ev(`(() => { const t = document.querySelector('#chat-in'); t.focus(); t.value = 'Entwurf beim Drehen'; t.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    let L = await ev(LAY);
    check(L.panel > 0 && L.mainR <= L.panel + 1 && L.ttl > 200, '1200x904: the panel, the main area beside it (not under it) ' + JSON.stringify(L));
    await shot('p2130-rotate-1200-panel.png');
    await vp(904, 1200); await sleep(900);
    L = await ev(LAY);
    check(L.full && L.panel === -1 && L.draft === 'Entwurf beim Drehen' && L.focus === 'chat-in' && L.gap <= 2, 'rotated to 904x1200: a full page, draft + focus + newest message kept ' + JSON.stringify(L));
    await shot('p2130-rotate-904-full.png');
    await vp(1200, 904); await sleep(900);
    L = await ev(LAY);
    check(L.panel > 0 && !L.full && L.mainR <= L.panel + 1 && L.draft === 'Entwurf beim Drehen', 'rotated back to 1200x904: the panel again, the draft kept ' + JSON.stringify(L));
  }, true);
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ---- desktop 1440 x 900, mouse, light then dark, English
  await call('PATCH', '/api/settings', {lang: 'en'});
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});
  for (const theme of ['light', 'dark']) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}, theme) === 200, `1440 ${theme}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '?d=1#today'); await ready(ev);
    const key = k => cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: k}, {type: 'keyUp', value: k}]}]});
    const TAB = '', DOWN = '';
    // headless Firefox never focuses its window, so :focus / :focus-visible never match there: the ring is checked in the
    // style sheet (a 2px outline for every :focus-visible, no rule takes it away from buttons) and on the element's rule
    const RING = `(() => { const rs = [...document.styleSheets].flatMap(sh => { try { return [...sh.cssRules]; } catch { return []; } }).flatMap(r => r.cssRules && !r.selectorText ? [...r.cssRules] : [r]).filter(r => r.selectorText);
      const all = rs.find(r => r.selectorText.split(',').some(x => x.trim() === ':focus-visible') && /outline:\\s*2px solid/.test(r.cssText));
      const off = rs.filter(r => /focus/.test(r.selectorText) && /outline:\\s*(none|0)[;\\s]/.test(r.cssText) && r.selectorText.split(',').some(x => /^(button|#side|\\.srow|\\.skip)(:|\\s)/.test(x.trim())));
      return !!all && !off.length; })()`;
    const ring0 = await ev(RING);
    check(ring0, `1440 ${theme} A9: a 2 px focus ring for every :focus-visible, none taken away from buttons / the sidebar`);
    const foc = () => ev(`(() => { const a = document.activeElement; return {id: a.id, side: !!a.closest('#side'), view: !!a.closest('#main'), txt: (a.textContent || '').trim().slice(0, 20), ring: ${ring0}}; })()`);
    await ev(`(() => { document.activeElement?.blur(); window.focus(); return 1; })()`);
    await key(TAB); await sleep(150);
    const f1 = await foc();
    const sk = await ev(`[...document.styleSheets].flatMap(sh => { try { return [...sh.cssRules]; } catch { return []; } }).some(r => r.selectorText === '.skip:focus' && r.style.transform === 'none')`);
    check(f1.id === 'skip' && sk && f1.ring, `1440 ${theme} A9: the first Tab: the skip link "Skip to content", visible, with a ring ` + JSON.stringify(f1));
    await key(TAB); await sleep(150);
    const f2 = await foc();
    check(f2.side && f2.ring, `1440 ${theme} A9: the second Tab: the sidebar (one stop) with a focus ring ` + JSON.stringify(f2));
    await key(DOWN); await sleep(150);
    const f3 = await foc();
    check(f3.side && f3.txt !== f2.txt, `1440 ${theme} A9: ↓ walks the sidebar ` + JSON.stringify(f3));
    await key(TAB); await sleep(150);
    const f4 = await foc();
    check(!f4.side, `1440 ${theme} A9: the next Tab leaves the sidebar ` + JSON.stringify(f4));
    await shot(`p2130-focus-1440-${theme}.png`);
    // the skip link jumps to the content
    await ev(`(() => { document.querySelector('#skip').click(); return 1; })()`); await key(TAB); await sleep(150);
    const f5 = await foc();
    check(f5.view && !f5.side, `1440 ${theme} A9: after the skip link Tab lands in the content ` + JSON.stringify(f5));
    // A2: hover shows the quick reactions; helper text tooltip on hover
    await nav(B + '?d=2#l/' + P); await ready(ev);
    await ev(`(() => { chatOpen(${AG}); return 1; })()`); await sleep(1500);
    const m = await ev(`(() => { const m = [...document.querySelectorAll('#chat-msgs .cmsg.ag')].find(x => /build is green/.test(x.textContent)); m.scrollIntoView({block: 'center'}); const r = m.querySelector('.cbub').getBoundingClientRect(); return {x: r.left + 20, y: r.top + r.height / 2, op: getComputedStyle(m.querySelector('.rxrow .rx.add')).opacity}; })()`);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(m.x), y: Math.round(m.y)}, {type: 'pause', duration: 250}]}]});
    const op2 = await ev(`getComputedStyle([...document.querySelectorAll('#chat-msgs .cmsg.ag')].find(x => /build is green/.test(x.textContent)).querySelector('.rxrow .rx.add')).opacity`);
    check(+m.op >= .6 && +op2 >= .6, `1440 ${theme} #651: the quick reactions are visible without hover (${m.op} / ${op2})`);
    const ib = await ev(`(() => { const r = document.querySelector('#achat .chath .ib').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2}; })()`);
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(ib.x), y: Math.round(ib.y)}, {type: 'pause', duration: 250}]}]});
    const tp = await ev(`(() => { const t = document.querySelector('#iitip'); return t && !t.classList.contains('hidden') ? t.textContent.slice(0, 30) : null; })()`);
    check(tp && /Claude answers/.test(tp), `1440 ${theme} helper texts: hovering (i) shows the tooltip ` + tp);
    await shot(`p2130-chat-1440-${theme}.png`);
    await cmd('input.releaseActions', {context: ctx});
    await ev(`(() => { chatClose(); return 1; })()`);
    // the settings and the list dialog
    await ev(`(() => { settingsModal('general'); return 1; })()`); await sleep(700);
    await shot(`p2130-settings-1440-${theme}.png`);
    await ev(`(() => { document.querySelectorAll('.modal:not(.authscreen)').forEach(x => x.remove()); listModal(${P}); return 1; })()`); await sleep(700);
    await shot(`p2130-listdialog-1440-${theme}.png`);
    await ev(`(() => { document.querySelectorAll('.modal:not(.authscreen)').forEach(x => x.remove()); return 1; })()`);
    // P16: the logo in the accent colour
    const lg = await ev(`(() => { const s = document.querySelector('.sbrand svg.logo'); return s ? getComputedStyle(s).color : null; })()`);
    check(lg && !/rgb\(45, 212, 191\)/.test(lg), `1440 ${theme} P16: the logo follows the accent (${lg})`);
  }, false);

  // ---- the sign-in page (P7): 44 px fields, show password, nothing behind it gets the focus
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B); await sleep(1800);
    const lg = await ev(`(() => { const p = document.querySelector('#au-pw'), b = document.querySelector('[data-au="pwshow"]'); if (!p || !b) return null; b.click(); return {h: Math.round(p.getBoundingClientRect().height), type: p.type, inert: document.querySelector('#app').hasAttribute('inert')}; })()`);
    check(lg && lg.h >= 43.5 && lg.type === 'text' && lg.inert, '390 P7: sign-in: 44 px fields, "Show password", the app behind is inert ' + JSON.stringify(lg));
    await shot('p2130-login-390.png');
  }, true);

  console.log(`p2130_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });

function closeAll(w) { try { w.eval(`closePop(); document.querySelectorAll('.modal:not(.authscreen)').forEach(x => x.remove()); if (S.sel) closeDetail(); 1`); } catch { /* closed */ } }
