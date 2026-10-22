// 2.39.1 UI tests, part K, own container (start.sh). jsdom:
// - #1219 the inbox is called "Basket" in every language (no "Inbox" / "Eingang" left in the texts about it); the sidebar's
//   number says "to sort"; "Sort" in the basket walks item by item: to a list, assign to me, today, waiting on someone,
//   delete, skip (buttons + number keys), the end page ("Basket empty" / still to sort), Esc ends
// - #1219 My tasks: the assigned tasks + the group "From your lists, without a date" (only unassigned, undated tasks of lists
//   only I use; a shared list's unassigned task is not in it), foldable (stored like the other groups)
// - #1221 the group header of a list in a folder shows "Folder › List", a click on the folder opens it; the per-task list line
//   is gone in a list group; the groups reorder (menu / drag), stored per view on the server, "Reset the order" in "…"
// - #1185 the sidebar: "Views" (calendar, matrix ...) and "Areas" (habits, statistics ...); an own arrangement stays (Areas
//   right after Views); "Fold all" folds every group and folder and switches to "Unfold all"
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const FEAT = 'cal,matrix,habits,stats,comments,collab';

(async () => {
  // ================= #1219 the name in every language (the files)
  const I18N = path.join(__dirname, '..', 'static', 'i18n');
  const OLD = {de: /Eingang(?!s?-?[a-z])|Eingangs/, fr: /boîte de réception/i, es: /bandeja de entrada/i, it: /In arrivo|posta in arrivo/, nl: /\binbox\b/i};
  const NEW = {de: 'Korb', fr: 'Panier', es: 'Cesta', it: 'Raccolta', nl: 'Mand'};
  // 2.48.0 (#1111): "Dokumente/Eingang" is the fixed name of a folder in the file store (data, the same in every language), not the basket
  // 2.142.1 (#2150): "Share inbox (ntfy)" is the heading of the ntfy share inbox per person (the topic, not the basket)
  const allowed = k => /DATEV|document inbox|ntfy share inbox|Share inbox \(ntfy\)|topic inbox|Incoming invoices|^Coming up$|Dokumente\/Eingang/.test(k);  // it: "In arrivo" = coming up
  for (const lg of Object.keys(NEW)) {
    const dict = JSON.parse(fs.readFileSync(path.join(I18N, lg + '.json'), 'utf8'));
    check(dict.Basket === NEW[lg], `#1219 ${lg}: Basket = ${NEW[lg]} (${dict.Basket})`);
    check(!('Inbox' in dict), `#1219 ${lg}: no key "Inbox" any more`);
    const bad = Object.entries(dict).filter(([k, v]) => !allowed(k) && (/inbox/i.test(k) || OLD[lg].test(JSON.stringify(v))));
    check(!bad.length, `#1219 ${lg}: no old name left ` + JSON.stringify(bad.slice(0, 3)));
  }

  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  // 2.46.0 (#1592): no organisation from the start any more: the setup creates the one these tests use (id 1), new people join it
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const st0 = await call('GET', '/api/state'), ME = st0.me, ORG = ME.workspaces[0].id, INBOX = st0.lists.find(l => l.is_inbox).id;
  const bob = await call('POST', '/api/users', {orgs: [1], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const HOME = (await call('POST', '/api/lists', {name: 'Household', org_id: ORG})).id;
  const SOLO = (await call('POST', '/api/lists', {name: 'Garden', org_id: ORG, folder: 'Private'})).id;
  await call('PATCH', `/api/lists/${SOLO}`, {folder: 'Private'});
  const TEAM = (await call('POST', '/api/lists', {name: 'Team', org_id: ORG})).id;
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: bob.id, role: 'edit'});
  for (const t of ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot']) await call('POST', '/api/tasks', {title: t, list_id: INBOX});
  await call('POST', '/api/tasks', {title: 'Dated already', list_id: INBOX, due: '2030-01-01'});
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  await mk('Prune the roses', SOLO); await mk('Rake leaves', SOLO, {due: '2030-02-02'});
  await mk('Team chore', TEAM); await mk('Mine in team', TEAM, {assignee_id: ME.id});
  await mk('Mine at home', HOME, {assignee_id: ME.id}); await mk('Fix the gate', SOLO, {assignee_id: ME.id});

  // ================= #1219 sidebar + Sort
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  const ibRow = d.querySelector('#side .srow[data-go="inbox"]');
  check(ibRow && ibRow.querySelector('.n')?.textContent === 'Basket', '#1219: the sidebar row says Basket');
  check(/6 to sort/.test(ibRow?.querySelector('.c')?.getAttribute('title') || '') && /to sort/.test(ibRow?.querySelector('.c .sr')?.textContent || ''), '#1219: the number says "to sort" (6, the dated item does not count) ' + ibRow?.querySelector('.c')?.outerHTML);
  check(d.querySelector('#top h1, #top .ttl')?.textContent.includes('Basket') || /Basket/.test(d.querySelector('#top')?.textContent || ''), '#1219: the view title says Basket');
  const sb = d.querySelector('#top [data-kb="sort"]');
  check(!!sb && /Sort/.test(sb.textContent), '#1219: a Sort button in the basket');
  click(w, sb);
  let md = await until(() => d.querySelector('.kbsortm'));
  check(!!md && md.querySelectorAll('.kbact').length === 8 && /1 of 6/.test(md.querySelector('.kbpos')?.textContent || ''), '#1219: the sort page: 8 actions, 1 of 6');
  check(/Keys/.test(md.querySelector('.kbleg')?.textContent || '') && md.querySelector('.kba-list kbd')?.textContent === '1', '#1219: the key legend is visible');
  const cur = () => md.querySelector('.kbttl')?.textContent;
  const done = {};
  // 1: to a list (button + list menu)
  let t = cur(); done.list = t;
  click(w, md.querySelector('[data-kbs="list"]'));
  const hb = await until(() => [...d.querySelectorAll('.menu-list button')].find(b => /Household/.test(b.textContent)));
  check(!!hb && ![...d.querySelectorAll('.menu-list button')].some(b => /Basket/.test(b.textContent)), '#1219: the list menu (without the basket)');
  click(w, hb);
  await until(() => cur() && cur() !== t);
  // 2: assign to me (key 2)
  t = cur(); done.me = t; key(w, md.querySelector('.kbsort'), '2'); await until(() => cur() !== t);
  // 3: today (key 3)
  t = cur(); done.today = t; key(w, md.querySelector('.kbsort'), '3'); await until(() => cur() !== t);
  // 6: waiting on someone (field + Enter)
  t = cur(); done.wait = t; key(w, md.querySelector('.kbsort'), '6');
  const wn = await until(() => md.querySelector('#kb-wn'));
  check(!!wn, '#1219: waiting: a field for whom');
  wn.value = 'the carpenter'; key(w, wn, 'Enter'); await until(() => cur() !== t);
  // 7: delete
  t = cur(); done.del = t; key(w, md.querySelector('.kbsort'), '7'); await until(() => cur() !== t, 60);
  check(/deleted/.test(d.querySelector('#toast')?.textContent || '') && !!d.querySelector('#toast button'), '#1219: delete offers Undo');
  // 0: skip
  t = cur(); done.skip = t; key(w, md.querySelector('.kbsort'), '0');
  await until(() => md.querySelector('.kbend'));
  check(/Done for now/.test(md.querySelector('.kbend')?.textContent || '') && /1 item is still to sort/.test(md.querySelector('.kbend')?.textContent || ''), '#1219: the end page: one still to sort ' + md.querySelector('.kbsort')?.textContent);
  const st = await call('GET', '/api/state'), by = n => st.tasks.find(x => x.title === n);
  check(by(done.list)?.list_id === HOME, '#1219: moved to Household');
  check(by(done.me)?.assignee_id === ME.id && by(done.me)?.list_id === INBOX, '#1219: assigned to me');
  check(!!by(done.today)?.due, '#1219: a date (today)');
  check(by(done.wait)?.wait_note === 'the carpenter' && !!by(done.wait)?.waiting_at, '#1219: waiting on the carpenter');
  check(!by(done.del), '#1219: deleted (in the trash)');
  check(by(done.skip)?.list_id === INBOX && !by(done.skip)?.due, '#1219: skipped stays as it was');
  click(w, md.querySelector('[data-kbs="end"]')); await until(() => !d.querySelector('.kbsortm'));
  // again: Esc ends; then the last one away -> "Basket empty"
  click(w, d.querySelector('#top [data-kb="sort"]'));
  md = await until(() => d.querySelector('.kbsortm'));
  check(md && /1 of 1/.test(md.querySelector('.kbpos')?.textContent || '') && cur() === done.skip, '#1219: a new round: only what is still to sort');
  key(w, md.querySelector('.kbsort'), 'Escape'); await until(() => !d.querySelector('.kbsortm'));
  check(!d.querySelector('.kbsortm'), '#1219: Esc ends');
  click(w, d.querySelector('#top [data-kb="sort"]')); md = await until(() => d.querySelector('.kbsortm'));
  key(w, md.querySelector('.kbsort'), '4'); await until(() => md.querySelector('.kbend'));
  check(/Basket empty/.test(md.querySelector('.kbend')?.textContent || '') && /Everything is sorted/.test(md.textContent), '#1219: "Basket empty" at the end');
  click(w, md.querySelector('[data-kbs="end"]')); await sleep(200);
  check(!d.querySelector('#top [data-kb="sort"]'), '#1219: nothing to sort: no Sort button');
  w.close();
  // phone: big buttons, no key legend
  w = await boot({user: 'alice', hash: 'inbox', mobile: true}); d = w.document;
  await call('POST', '/api/tasks', {title: 'Golf', list_id: INBOX}); await w.eval('load().then(render)'); await sleep(300);
  w.eval('kbSortStart()'); md = await until(() => d.querySelector('.kbsortm'));
  check(md && md.querySelectorAll('.kbact').length === 8, '#1219 phone: the same actions');
  w.close();

  // ================= #1219 / #1221 My tasks (2.40.0, #1344: grouped by list is no longer the default)
  await call('PATCH', '/api/settings', {mine_view: 'lists'});
  w = await boot({user: 'alice', hash: 'assigned'}); d = w.document;
  const groups = () => [...d.querySelectorAll('#view .group')];
  // 2.152.2 (#2624): project instead of list
  const mine = groups().find(g => /From your projects, without a date/.test(g.querySelector('.ghead')?.textContent || ''));
  check(!!mine && groups().at(-1) === mine || (mine && groups().indexOf(mine) >= groups().length - 2), '#1219: the group "From your lists, without a date" at the bottom');
  const mtx = mine?.textContent || '';
  check(/Prune the roses/.test(mtx) && !/Rake leaves/.test(mtx) && !/Team chore/.test(mtx) && !/Fix the gate/.test(mtx), '#1219: only unassigned, undated tasks of lists only I use ' + mtx.slice(0, 200));
  check(!/Team chore/.test(d.querySelector('#view').textContent), '#1219: the shared list: only what is assigned');
  check(/Mine in team/.test(d.querySelector('#view').textContent) && /Mine at home/.test(d.querySelector('#view').textContent), '#1219: the assigned tasks stay');
  click(w, mine.querySelector('.ghead')); await sleep(150);
  check(w.eval('S.collapsed.has("kb:mine")') && !/Prune the roses/.test(d.querySelector('#view').textContent), '#1219: the group folds (stored like the others)');
  click(w, d.querySelector('#view .ghead[data-key="kb:mine"]')); await sleep(150);
  // #1221 the breadcrumb
  const gg = groups().find(g => g.dataset.kbg === 'l:' + SOLO);
  const cr = gg?.querySelector('.kbcrumb');
  check(cr && cr.querySelector('.kbcp')?.textContent === 'Private' && cr.querySelector('.kbcl')?.textContent === 'Garden' && /›/.test(cr.textContent), '#1221: "Private › Garden" ' + gg?.querySelector('.ghead')?.innerHTML.slice(0, 300));
  check(!gg?.querySelector('.trow .tlist, .trow .lname') || !/Garden/.test([...gg.querySelectorAll('.trow')].map(x => x.querySelector('.meta, .tmeta')?.textContent || '').join('')), '#1221: no list line under the tasks of the list group');
  // #1221 order: the default = the sidebar's (lists without a folder, then folders); move Garden to the top
  const order0 = groups().filter(g => g.dataset.kbg).map(g => g.dataset.kbg);
  check(order0.at(-1) === 'l:' + SOLO && order0[0] === 'l:' + INBOX && order0.includes('l:' + HOME) && order0.includes('l:' + TEAM), '#1221: default in the sidebar order (basket, lists, then folders) ' + order0.join());
  click(w, gg.querySelector('[data-kb="grp-menu"]'));
  // 2.62.0 (#1853): the four moves sit behind one "Change position…" entry (second level)
  click(w, await until(() => [...d.querySelectorAll('.menu-list button')].find(b => /Change position/.test(b.textContent))));
  const top = await until(() => [...d.querySelectorAll('.menu-list button')].find(b => /To the top/.test(b.textContent)));
  click(w, top); await sleep(500);
  const order1 = groups().filter(g => g.dataset.kbg).map(g => g.dataset.kbg);
  check(order1[0] === 'l:' + SOLO, '#1221: Garden on top ' + order1.join());
  const go = JSON.parse((await call('GET', '/api/state')).settings.group_order || '{}');
  check(JSON.stringify(go.assigned) === JSON.stringify(order1), '#1221: stored per view on the server ' + JSON.stringify(go));
  // a click on the folder in the crumb opens the folder
  click(w, groups().find(g => g.dataset.kbg === 'l:' + SOLO).querySelector('.kbcrumb .kbcp')); await sleep(300);
  check(w.eval('S.route.key') === 'folder:Private', '#1221: a click on the folder opens it (' + w.eval('S.route.key') + ')');
  w.eval('go("assigned")'); await sleep(300);
  check(w.eval('topMoreItems()').some(x => x.label === 'Reset the order'), '#1221: "…" offers "Reset the order"');
  w.eval('topMoreItems().find(x => x.label === "Reset the order").fn()'); await sleep(500);
  check(groups().filter(g => g.dataset.kbg).map(g => g.dataset.kbg).join() === order0.join() && (await call('GET', '/api/state')).settings.group_order === '{}', '#1221: reset: the sidebar order again, removed on the server');
  // drag (desktop): Team onto the first group
  const gT = groups().find(g => g.dataset.kbg === 'l:' + TEAM), gH = groups().filter(g => g.dataset.kbg)[0];
  const dt = {setData() {}, effectAllowed: ''};
  const dev = (el, type) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.dataTransfer = dt; el.dispatchEvent(e); };
  dev(gT.querySelector('.kbgrip'), 'dragstart'); dev(gH.querySelector('.ghead'), 'dragover'); dev(gH.querySelector('.ghead'), 'drop'); await sleep(500);
  check(groups().filter(g => g.dataset.kbg)[0]?.dataset.kbg === 'l:' + TEAM, '#1221: dragged onto the first group = the top ' + groups().filter(g => g.dataset.kbg).map(g => g.dataset.kbg).join());

  // ================= #1185 the sidebar
  const side = () => [...d.querySelectorAll('#side .sgroup')].map(g => (g.className.match(/sg-(\w+)/) || [])[1]).filter(Boolean);
  check(side().indexOf('views') >= 0 && side().indexOf('areas') < 0, '#1185: Views; the areas are the bar ' + side().join());  // 2.152.2 (#2622): no group Areas on a computer, the areas are icons of #srail
  const vtx = d.querySelector('#side .sg-views')?.innerHTML || '';  // 2.152.2 (#2622): the areas sit in #srail
  check(!/data-go="cal"/.test(vtx) && /data-go="matrix"/.test(vtx) && !/data-go="habits"/.test(vtx) && d.querySelector('#srail [data-sbb="cal"]'), '#1185: Views: matrix (no habits; the calendar is an icon of the bar)');  // 2.152.2 (#2622): the calendar in #srail
  check(d.querySelector('#srail [data-sbb="habits"]') && d.querySelector('#srail [data-sbb="review"]') && !d.querySelector('#side [data-mgside], #side [data-go="habits"]'), '#1185: Areas: habits, statistics (Review) in the bar');  // 2.152.2 (#2622): the area icons of #srail
  check(d.querySelector('#srail')?.getAttribute('aria-label') === 'Areas', '#1185: the bar is called Areas');  // 2.152.2 (#2622): the bar's name instead of the group's
  // an own arrangement from before (no "areas"): kept, Areas right after Views; a hidden Views hides Areas too
  await call('PATCH', '/api/settings', {sidebar: JSON.stringify({order: ['lists', 'views', 'focus'], hidden: []})}); await w.eval('load().then(render)'); await sleep(300);
  check(w.eval('sideGroupOrder().slice(0, 4).join()') === 'lists,views,areas,focus', '#1185: own order kept ' + w.eval('sideGroupOrder().join()'));
  await call('PATCH', '/api/settings', {sidebar: JSON.stringify({order: ['lists', 'views'], hidden: ['g:views']})}); await w.eval('load().then(render)'); await sleep(300);
  check(!d.querySelector('#side .sg-areas') && !d.querySelector('#side .sg-views'), '#1185: Views hidden before -> no Views (and no group Areas)');  // 2.152.2 (#2622): no group Areas on a computer
  await call('PATCH', '/api/settings', {sidebar: ''}); await w.eval('load().then(render)'); await sleep(300);
  // fold all / unfold all
  const fa = () => d.querySelector('#side [data-kb="side-all"]');
  check(fa() && /Fold all/.test(fa().title), '#1185: "Fold all" in the head of the sidebar');
  click(w, fa()); await sleep(600);
  check(!w.eval('kbSideAnyOpen()') && w.eval('foldClosed("Private")') && d.querySelector('#side .sg-lists .sgh.closed') && /Unfold all/.test(fa().title), '#1185: everything folded, the button says "Unfold all"');
  const fc = (await call('GET', '/api/state')).settings.folders_closed;
  check(/Private/.test(fc || ''), '#1185: the folded folders are stored like a single fold ' + fc);
  click(w, fa()); await sleep(600);
  check(!w.eval('foldClosed("Private")') && d.querySelector('#side .sg-views > .smod') && d.querySelector('#side .sg-lists .sgh:not(.closed)') && /Fold all/.test(fa().title), '#1185: everything unfolded again');  // 2.152.2 (#2622): Views instead of the gone group Areas
  w.close();
  // German: "Korb" and "Bereiche"
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  await until(() => d.querySelector('#side .srow[data-go="inbox"] .n')?.textContent === 'Korb', 40);
  check(d.querySelector('#side .srow[data-go="inbox"] .n')?.textContent === 'Korb', '#1219 German: Korb');
  check(d.querySelector('#srail')?.getAttribute('aria-label') === 'Bereiche', '#1185 German: Bereiche');  // 2.152.2 (#2622): the bar's name
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
