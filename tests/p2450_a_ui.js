// 2.45.0 UI tests, part A (the sidebar), own container (start.sh), jsdom.
// - #1503: the default order Plan, Lists, Views, Areas, Filters, Tags, Conversations (an own order stays)
// - #1502: All / Completed / Trash / Archived are the group "More" (folded on a new device, open on a used one unless every
//   group was folded), it follows "Fold all", its header shows a folded open view; Tags has a header like the other groups;
//   Settings stays alone at the bottom
// - #1509: "Messages" with the unread count on top of "Conversations", the last conversations (at most 5, unread first and
//   bold), a bubble at every person opens the direct message, g n opens the messenger (in the shortcut help)
// - #1532: a new folder belongs to the shown workspace (Private / an organisation), so it shows there at once
// - #1516: "Notes" in Views with the number of notes; #notes = the notes of all lists: pinned first, the list's name, a filter
//   by list, a search in title and text, "New note" in a picked list; rights as before (participants / view-only)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, k) => w.document.body.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments';
const groups = d => [...d.querySelectorAll('#side .sgroup')].map(x => (x.className.match(/sg-(\w+)/) || [])[1]).filter(Boolean);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  // 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  const ALICE = (await call('GET', '/api/state')).me.id;
  const BOB = (await call('POST', '/api/users', {orgs: [1], username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAR = (await call('POST', '/api/users', {orgs: [1], username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const CB = await login('bob'), CC = await login('carol');
  for (const ck of [CB, CC]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL}, ck);
  const WEB = (await call('POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  const GAR = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  await call('PUT', `/api/lists/${WEB}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${WEB}/members`, {user_id: CAR, role: 'view'});
  await call('POST', '/api/tasks', {title: 'Write the text', list_id: WEB, tags: ['copy']});
  // notes: two in the project (one pinned), one in the private list
  const N1 = (await call('POST', `/api/lists/${WEB}/notes`, {title: 'Kickoff', body: 'We meet at the harbour on Monday.'})).id;
  const N2 = (await call('POST', `/api/lists/${WEB}/notes`, {title: 'Decisions', body: 'Blue logo.', pinned: true})).id;
  const N3 = (await call('POST', `/api/lists/${GAR}/notes`, {title: 'Seeds', body: 'Tomatoes and beans.'})).id;
  // conversations: Bob writes to Alice directly and in the project channel
  const DM = (await call('POST', '/api/team/dm', {user_id: ALICE}, CB)).id;
  await call('POST', `/api/team/rooms/${DM}/messages`, {body: 'Hello Alice'}, CB);
  const CH = (await call('GET', '/api/team', null, CB)).rooms.find(r => r.list_id === WEB)?.id;
  await call('POST', `/api/team/rooms/${CH}/messages`, {body: 'The draft is up'}, CB);

  // ================= #1503 the order, #1502 the group "More" on a new device
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  await sleep(400);
  check(w.eval('SIDE_GROUPS.join()') === 'focus,lists,views,areas,filters,tags,team,more', '#1503 #1502: the default order ' + w.eval('SIDE_GROUPS.join()'));
  const gs = groups(d);
  check(gs.indexOf('focus') < gs.indexOf('lists') && gs.indexOf('lists') < gs.indexOf('views') && gs.indexOf('views') < gs.indexOf('areas') && gs.indexOf('team') < gs.indexOf('more') && gs[gs.length - 1] === 'more', '#1503: Plan, Lists, Views, Areas … Conversations, More ' + gs.join());
  const more = () => d.querySelector('#side .sg-more');
  check(more()?.querySelector('.sgh.closed') && more().querySelector('.sgfold[hidden] .srow[data-go="trash"]') && /3/.test(more().querySelector('.sgh .c')?.textContent || ''), '#1502: More folded on a new device, its number = 3 entries');
  check([...d.querySelectorAll('#side .sfoot > *')].map(x => x.dataset.act).join() === 'settings', '#1502: Settings alone at the bottom');
  click(w, more().querySelector('[data-act="side-group"]')); await sleep(150);
  check(more().querySelector(':scope > .srow[data-go="all"]') && more().querySelector(':scope > .srow[data-go="done"]') && JSON.parse(w.__store['tasks.sideOpenG'] || '[]').includes('more'), '#1502: opened, remembered per device');
  click(w, more().querySelector('[data-act="side-group"]')); await sleep(150);
  w.eval(`go('trash')`); await sleep(400);
  check(more().querySelector('.sgh.closed.sgon') && /open view/.test(more().querySelector('.sgh').textContent), '#1502: the folded header shows the open Trash');
  w.eval(`go('inbox')`); await sleep(300);
  check(!more().querySelector('.sgh.sgon'), '#1502: … and not any more on another view');
  // Tags: a header like the others (grp), folded by default
  const tg = d.querySelector('#side .sg-tags');
  check(tg && tg.querySelector('.shead.sgh [data-act="side-group"][data-g="tags"]') && !d.querySelector('#side .stoggle') && tg.querySelector('.sgh.closed'), '#1502: Tags with a group header (folded)');
  // fold all / unfold all takes More along
  const fa = () => d.querySelector('#side [data-kb="side-all"]');
  click(w, fa()); await sleep(400);
  click(w, fa()); await sleep(400);
  check(more().querySelector('.sgh:not(.closed)') && d.querySelector('#side .sg-tags .sgh:not(.closed)'), '#1502: "Unfold all" opens More and Tags');
  click(w, fa()); await sleep(400);
  check(more().querySelector('.sgh.closed') && d.querySelector('#side .sg-tags .sgh.closed') && !w.eval('kbSideAnyOpen()'), '#1502: "Fold all" folds them');
  // the sidebar settings know the group (sort / hide)
  check(w.eval('sideGroupOrder().includes("more")') && w.eval('tr(SIDE_NAMES.more)') === 'More', '#1502: More in the sidebar settings');
  await call('PATCH', '/api/settings', {sidebar: JSON.stringify({order: ['views', 'areas', 'lists', 'focus'], hidden: ['g:more']})}); await w.eval('load().then(render)'); await sleep(400);
  check(w.eval('sideGroupOrder().slice(0, 4).join()') === 'views,areas,lists,focus' && !more() && d.querySelector('#side .sfoot .sset'), '#1503 #1502: an own order stays, More can be hidden');
  await call('PATCH', '/api/settings', {sidebar: ''});
  w.close();
  // a used device: More open, unless every group was folded; an open Tags group stays open
  w = await boot({user: 'alice', hash: 'inbox', ls: {'tasks.kbAreasMig': '1', 'tasks.collapsed': JSON.stringify(['side:tags-open'])}}); d = w.document; await sleep(300);
  check(more()?.querySelector('.sgh:not(.closed)') && d.querySelector('#side .sg-tags .sgh:not(.closed)'), '#1502: used device: More open, Tags stays open');
  w.close();
  w = await boot({user: 'alice', hash: 'inbox', ls: {'tasks.kbAreasMig': '1', 'tasks.sideGroups': JSON.stringify(['focus', 'lists', 'filters', 'tags', 'team'])}}); d = w.document; await sleep(300);
  check(more()?.querySelector('.sgh.closed'), '#1502: used device with everything folded: More folded too');
  w.close();

  // ================= #1509 the messenger in the sidebar
  await call('PATCH', '/api/settings', {side_people: String(BOB)});  // 2.99.0 (#2187): people only while pinned
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  const msg = await until(() => d.querySelector('#side .sg-team .sbmsg[data-go="team"]'));
  check(msg && /Messages/.test(msg.textContent) && msg.querySelector('.c.nunread')?.textContent.startsWith('2'), '#1509: "Messages" with 2 unread ' + msg?.textContent);
  check(d.querySelector('#side .sg-team').firstElementChild.nextElementSibling === msg, '#1509: on top of Conversations');
  const conv = await until(() => d.querySelectorAll('#side .sbconv').length === 2 && [...d.querySelectorAll('#side .sbconv')]);
  check(conv && conv.every(b => b.classList.contains('sbun')) && conv.some(b => b.dataset.go === `team/${DM}`) && conv.some(b => b.dataset.go === `team/${CH}`), '#1509: the 2 conversations, unread (bold)');
  // 2.99.0 (#2187): Bob stands there as a conversation, so not a second time as a person (pinned or not); the person row with
  // its bubble is checked in p299_e_ui.js
  check(![...d.querySelectorAll('#side .sbpw')].some(x => /Bob/.test(x.textContent)), '#2187: Bob only once (as the conversation)');
  click(w, d.querySelector(`#side .sbconv[data-go="team/${DM}"]`));
  check(await until(() => w.eval(`S.route.mod === 'team' && S.tc.rid === ${DM}`)), '#1509: the conversation row opens the direct message');
  await until(() => !d.querySelector(`#side .sbconv[data-go="team/${DM}"]`)?.classList.contains('sbun'));
  check(d.querySelector(`#side .sbconv[data-go="team/${DM}"]`)?.classList.contains('on') && !d.querySelector(`#side .sbconv[data-go="team/${DM}"]`).classList.contains('sbun'), '#1509: the open conversation lit, read');
  // live: a new message raises the count (the version poll calls teamChanged)
  await call('POST', `/api/team/rooms/${CH}/messages`, {body: 'And the photos'}, CB);
  w.eval(`go('inbox')`); await sleep(200); await w.eval('teamChanged()');
  check(await until(() => /^2/.test(d.querySelector('#side .sbmsg .c')?.textContent || '')), '#1509: the unread count follows live ' + d.querySelector('#side .sbmsg .c')?.textContent);
  // g n
  key(w, 'g'); key(w, 'n');
  check(await until(() => w.eval(`S.route.mod === 'team'`)), '#1509: g n opens the messenger');
  check(w.eval(`SHORTCUTS().some(([, rows]) => rows.some(r => r[0] === 'g n'))`), '#1509: g n in the shortcut help');
  w.close();
  // at most 5: six more channels with a message
  for (let i = 1; i <= 6; i++) {
    const L = (await call('POST', '/api/lists', {name: 'Room ' + i})).id;
    await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
    const r = (await call('GET', '/api/team', null, CB)).rooms.find(x => x.list_id === L)?.id;
    await call('POST', `/api/team/rooms/${r}/messages`, {body: 'Hi ' + i}, CB);
  }
  w = await boot({user: 'alice', hash: 'inbox', mobile: true}); d = w.document;
  const cs = await until(() => d.querySelectorAll('#side .sbconv').length && [...d.querySelectorAll('#side .sbconv')]);
  check(cs && cs.length === 5 && cs.every(b => b.classList.contains('sbun')), '#1509: at most 5 conversations (phone drawer) ' + cs?.length);
  w.close();

  // ================= #1516 the notes of all lists
  w = await boot({user: 'alice', hash: 'inbox', ls: {'tasks.sideOpenG': JSON.stringify(['views'])}}); d = w.document; await sleep(300);
  const nrow = d.querySelector('#side .sg-views .srow[data-go="notes"]');
  check(nrow && nrow.querySelector('.c')?.textContent === '3', '#1516: "Notes" in Views with 3 ' + nrow?.textContent);
  click(w, nrow); await until(() => d.querySelector('#view .sbnall'));
  const cards = () => [...d.querySelectorAll('#view .sbncard')];
  check(cards().length === 3 && cards()[0].getAttribute('href') === `#note/${N2}` && /Website/.test(cards()[0].querySelector('.sbnl').textContent) && /Garden/.test(cards().find(a => a.getAttribute('href') === `#note/${N3}`)?.textContent || ''), '#1516: all notes, pinned first, the list on each card');
  check(d.querySelector('#top h1')?.textContent.trim() === 'Notes', '#1516: the title "Notes" ' + d.querySelector('#top h1')?.textContent);
  check(await until(() => /harbour/.test(cards().find(a => a.getAttribute('href') === `#note/${N1}`)?.textContent || '')), '#1516: the first words of a note');
  // filter by list
  const sel = d.querySelector('#sbn-l');
  check(sel && sel.querySelector('optgroup'), '#1516: a filter by project / list');
  sel.value = String(GAR); sel.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(150);
  check(cards().length === 1 && cards()[0].getAttribute('href') === `#note/${N3}`, '#1516: filtered to Garden');
  sel.value = '0'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(150);
  // search in the text
  const q = d.querySelector('#sbn-q'); q.value = 'harbour'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => cards().length === 1 && cards()[0].getAttribute('href') === `#note/${N1}`), '#1516: the search finds the text');
  q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(150);
  // a new note: a list is asked for (two lists with notes I may write in)
  click(w, d.querySelector('[data-sb="note-new"]')); await sleep(200);
  const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(items.some(b => /Garden/.test(b.textContent)) && items.some(b => /Website/.test(b.textContent)) && !items.some(b => /Basket|Inbox/.test(b.textContent)), '#1516: "New note" asks for the list (no Inbox)');
  click(w, items.find(b => /Garden/.test(b.textContent)));
  check(await until(() => w.eval(`S.route.mod === 'notes' && S.nt.lid === ${GAR} && !!S.nt.id`)), '#1516: the new note opens in Garden');
  check((await call('GET', `/api/lists/${GAR}/notes`)).notes.length === 2, '#1516: stored in Garden');
  w.eval(`go('notes/${WEB}')`);
  check(await until(() => d.querySelector('#view .ntview .ntcard') && !d.querySelector('#view .sbnall') && /Website/.test(d.querySelector('#top h1')?.textContent || '')), '#1516: #notes/<id> stays the notes of one list ' + d.querySelector('#top h1')?.textContent + ' ' + d.querySelector('#view')?.textContent.slice(0, 80));
  w.close();
  // Bob (member of Website) sees its notes, not the private list's; Carol (view only) cannot write
  w = await boot({user: 'bob', hash: 'notes'}); d = w.document;
  await until(() => d.querySelector('#view .sbnall'));
  check(cards().length === 2 && !cards().some(a => /Seeds/.test(a.textContent)) && d.querySelector('[data-sb="note-new"]'), '#1516: Bob: only the shared notes, may write');
  w.close();
  w = await boot({user: 'carol', hash: 'notes'}); d = w.document;
  await until(() => d.querySelector('#view .sbnall'));
  check(cards().length === 2 && !d.querySelector('[data-sb="note-new"]'), '#1516: Carol (view): reads, no "New note"');
  w.close();

  // ================= #1532 a new folder belongs to the shown workspace (shows at once while empty)
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const fShown = n => [...d.querySelectorAll('#side .fhead')].some(f => f.dataset.folder === n);
  await call('PATCH', '/api/settings', {workspace: 'private'});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document; await sleep(300);
  w.prompt = () => 'Ideas'; await w.eval('newFolder()');
  check(await until(() => fShown('Ideas')), '#1532: Private: the new folder shows at once');
  check(await until(async () => (await call('GET', '/api/folders/props?folder=Ideas')).props?.org_id === 0), '#1532: stored as private');
  await call('PATCH', '/api/settings', {workspace: 'org:' + ORG}); await w.eval('load().then(render)'); await sleep(300);
  w.prompt = () => 'Team ideas'; await w.eval('newFolder()');
  check(await until(() => fShown('Team ideas')) && !fShown('Ideas'), '#1532: in the organisation: its new folder shows, the private one not');
  w.prompt = () => 'Drafts'; await w.eval(`newFolder(null, 'Team ideas')`);
  check(await until(() => fShown('Team ideas') && !w.eval(`foldClosed('Team ideas')`) ? [...d.querySelectorAll('#side .fhead')].some(f => f.dataset.folder === 'Team ideas/Drafts') : w.eval(`folderNames().includes('Team ideas/Drafts') && sb_folderInWs('Team ideas/Drafts')`)), '#1532: a subfolder inherits the workspace');
  check(!('Team ideas/Drafts' in w.eval('S.folderProps')), '#1532: … without an own setting');
  await call('PATCH', '/api/settings', {workspace: 'all'}); await w.eval('load().then(render)'); await sleep(300);
  check(fShown('Ideas') && fShown('Team ideas'), '#1532: All shows both');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
