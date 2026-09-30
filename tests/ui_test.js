// UI tests (jsdom) for comments / activity / mentions / link / collab + links toggles. node ui_test.js
const {boot, errs, sleep, B} = require('./boot');
const ids = require('./ids.json');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const api = async (w, method, url, body) => (await w.fetch(url, {method, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: body ? JSON.stringify(body) : undefined})).json();

(async () => {
  // ---------------- alice, English, desktop: list view with chips
  let w = await boot({user: 'alice', hash: 'l/' + ids.L});
  let d = w.document;
  await api(w, 'PATCH', '/api/tasks/' + ids.ST, {url: 'https://github.com/kalmido/demo'});
  await w.eval('load().then(render)'); await sleep(400);
  const row = d.querySelector(`#view .trow[data-id="${ids.ST}"]`);
  check(row, 'shared task row rendered');
  const lnk = row?.querySelector('a.lnk');
  check(lnk && lnk.textContent.trim() === 'github.com' && lnk.target === '_blank' && lnk.rel === 'noopener noreferrer', 'row link chip: domain, new tab, noopener noreferrer');
  check(row?.querySelector('.cmc'), 'row shows the comment count chip');
  check(row?.querySelector('.who'), 'row shows the assignee avatar (collab on)');
  check(d.querySelector('#side .srow[data-go="assigned"]'), 'sidebar has "Assigned to me" (collab on)');
  // clicking the link chip does not open the detail
  lnk?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  await sleep(100);
  check(!w.eval('S.sel'), 'clicking the link chip does not open the task');
  // ---------------- detail with timeline
  w.eval(`openDetail(${ids.ST})`); await sleep(900);
  const tl = d.querySelector('#d-tl');
  check(tl, 'detail has the comments section');
  check(d.querySelectorAll('#d-tl .cm').length >= 3, 'comments rendered: ' + d.querySelectorAll('#d-tl .cm').length);
  check(d.querySelectorAll('#d-tl .actl').length >= 1, 'activity lines rendered');
  check([...d.querySelectorAll('#d-tl .mention')].some(m => m.textContent === '@Bob'), 'mentions highlighted with names');
  check(/Alice created the task/.test(tl?.textContent), 'activity text in English');
  check(/Alice set the link to github\.com/.test(tl?.textContent), 'link activity line');
  check(d.querySelector('.linkchip')?.textContent.trim() === 'github.com' && d.querySelector('.linkchip').rel === 'noopener noreferrer', 'detail link chip');
  check(d.querySelector('#d-assignee'), 'assignee picker present (collab on)');
  // activity toggle, remembered per device
  d.querySelector('[data-act="tl-act"]').click(); await sleep(100);
  check(d.querySelectorAll('#d-tl .actl').length === 0 && w.__store['tasks.showActivity'] === 'false', 'toggle hides activity and remembers it');
  d.querySelector('[data-act="tl-act"]').click(); await sleep(100);
  check(d.querySelectorAll('#d-tl .actl').length >= 1, 'toggle shows activity again');
  // moderation: alice owns the list -> delete buttons on others' comments, edit only on hers
  const others = [...d.querySelectorAll('#d-tl .cm')].filter(c => !/^Alice/.test(c.querySelector('.chead b').textContent));
  check(others.length && others.every(c => c.querySelector('[data-act="c-del"]') && !c.querySelector('[data-act="c-edit"]')), 'owner: delete but no edit on others\' comments');
  // mention picker
  const ta = d.querySelector('#c-input');
  ta.value = 'Ping @Ca'; ta.setSelectionRange(ta.value.length, ta.value.length);
  ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  const pick = d.querySelector('.ccomp .mpick');
  const names = [...pick.querySelectorAll('button')].map(b => b.lastChild.textContent);
  check(!pick.classList.contains('hidden') && names.length === 1 && /Carol/.test(names[0]), 'picker shows Carol for "@Ca": ' + names);
  ta.value = 'Ping @'; ta.setSelectionRange(6, 6); ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  const all = [...pick.querySelectorAll('button')].map(b => b.textContent);
  check(all.length === 3 && !all.some(n => /Alice|Dave/.test(n)), 'picker lists people who see the task, without me and without Dave: ' + all);
  ta.value = 'Ping @Bo'; ta.setSelectionRange(8, 8); ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  ta.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true}));
  check(ta.value === 'Ping @Bob ', 'Enter picks the mention: ' + JSON.stringify(ta.value));
  ta.value += 'please check'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  // offline: nothing lost, clear notice
  w.__offline = true;
  await w.eval('sendComment()'); await sleep(200);
  check(/offline/i.test(d.querySelector('#toast').textContent) && d.querySelector('#c-input').value === 'Ping @Bob please check', 'offline: notice + text stays: ' + d.querySelector('#toast').textContent);
  check(w.eval('OUT.q.length') === 0, 'offline comment is not queued in the outbox');
  w.__offline = false;
  const n0 = d.querySelectorAll('#d-tl .cm').length;
  await w.eval('sendComment()'); await sleep(600);
  check(d.querySelectorAll('#d-tl .cm').length === n0 + 1 && d.querySelector('#c-input').value === '', 'online: comment sent, box cleared');
  const tlj = await api(w, 'GET', `/api/tasks/${ids.ST}/timeline`);
  const last = tlj.comments[tlj.comments.length - 1];
  check(last.body === `Ping <@${ids.ids.bob}> please check` && last.mentions[0] === ids.ids.bob, 'mention stored as user id: ' + last.body);
  // edit own comment
  w.eval(`S.cedit = ${last.id}; drawTimeline()`); await sleep(50);
  const et = d.querySelector(`.c-edit-input[data-cid="${last.id}"]`);
  check(et && et.value === 'Ping @Bob please check', 'edit box shows names instead of tokens');
  et.value = 'Ping @Bob and @Carol'; d.querySelector(`[data-act="c-edit-save"][data-cid="${last.id}"]`).click(); await sleep(700);
  const tlj2 = await api(w, 'GET', `/api/tasks/${ids.ST}/timeline`);
  const e2 = tlj2.comments.find(c => c.id === last.id);
  check(e2.body === `Ping <@${ids.ids.bob}> and <@${ids.ids.carol}>` && e2.edited_at, 'edit saved with mentions');
  check([...d.querySelectorAll('#d-tl .cm')].some(c => /edited/.test(c.textContent)), '"edited" shown');
  // delete own comment -> disappears
  const before = d.querySelectorAll('#d-tl .cm').length;
  d.querySelector(`[data-act="c-del"][data-cid="${last.id}"]`).click(); await sleep(700);
  check(d.querySelectorAll('#d-tl .cm').length === before - 1, 'deleted comment disappears');
  // link field: edit + invalid
  w.eval('closeDetail()'); await sleep(50);
  w.eval(`openDetail(${ids.PT})`); await sleep(700);
  d.querySelector('[data-act="link-edit"]')?.click(); await sleep(50);
  const ui = d.querySelector('#d-url');
  check(ui, 'link edit input');
  ui.value = 'ftp://nope'; ui.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(300);
  check(/http/.test(d.querySelector('#toast').textContent), 'invalid link: notice');
  ui.value = 'example.org/abc'; ui.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(600);
  check(w.eval(`S.tasks.get(${ids.PT}).url`) === 'https://example.org/abc', 'bare domain gets https://');
  // quick add parser
  const r = w.eval(`parseQuick('Read https://github.com/x/y tomorrow !high')`);
  check(r.title === 'Read' && r.url === 'https://github.com/x/y' && r.priority === 5 && r.due && r.chips.some(c => c.type === 'link' && c.label === 'github.com'), 'quick add: URL -> link chip + field');
  const r2 = w.eval(`parseQuick('https://github.com/x/y')`);
  check(r2.title === '' && r2.url === 'https://github.com/x/y', 'quick add: only URL');
  const r3 = w.eval(`parseQuick('Look at https://a.org/b, then decide')`);
  check(r3.url === 'https://a.org/b' && r3.title === 'Look at then decide', 'quick add: trailing comma not part of the URL: ' + JSON.stringify(r3.title));
  w.eval(`S.quick.ignore = new Set(['link'])`);
  const r4 = w.eval(`parseQuick('Read https://github.com/x/y', S.quick.ignore)`);
  check(r4.title === 'Read https://github.com/x/y' && !r4.url, 'link chip can be switched off');
  w.eval(`S.quick.ignore = new Set()`);
  // quick add creates the task with the link, title = domain+path when only a URL
  w.eval(`go('inbox')`); await sleep(400);
  const qi = d.querySelector('#qinput'); qi.value = 'https://www.example.com/docs/page/';
  await w.eval(`submitQuick(document.querySelector('#qinput'))`); await sleep(500);
  const nt = [...w.eval('S.tasks').values()].find(t => t.url === 'https://www.example.com/docs/page/');
  check(nt && nt.title === 'example.com/docs/page', 'quick add only URL: title domain + path');
  // share target (GET /share?text=...) with links on
  const sl = w.eval(`shareLink('Great read https://blog.example.org/post-1.', '')`);
  check(sl[0] === 'https://blog.example.org/post-1' && sl[1] === 'Great read', 'share: link split off: ' + JSON.stringify(sl));
  // search matches the link
  w.eval(`go('search')`); await sleep(200);
  await w.eval(`doSearch('blog.example')`); await sleep(500);
  // unread chip for bob
  w.close();

  // ---------------- bob (German): unread dot + German activity + seen on open
  await api(await boot({user: 'carol', wait: 800}), 'POST', `/api/tasks/${ids.ST}/comments`, {body: 'Neu von Carol'});
  w = await boot({user: 'bob', hash: 'l/' + ids.L}); d = w.document;
  let brow = d.querySelector(`#view .trow[data-id="${ids.ST}"] .cmc`);
  check(brow && brow.classList.contains('unread'), 'bob: unread dot on the row');
  w.eval(`openDetail(${ids.ST})`); await sleep(900);
  check(/Alice hat die Aufgabe erstellt/.test(d.querySelector('#d-tl').textContent), 'German activity text');
  check(d.querySelector('#d-tl .cm.new'), 'new comments highlighted');
  check(/Kommentare/.test(d.querySelector('#d-tl h5').textContent) && d.querySelector('#c-input').placeholder.startsWith('Kommentar schreiben'), 'German section + placeholder');
  const leftovers = ['created the task', 'Show activity', 'Write a comment', 'Comments', 'Send', 'edited', 'removed', 'moved the task', 'set the '].filter(x => new RegExp('\\b' + x + '\\b').test(d.querySelector('#d-tl').textContent));
  check(!leftovers.length, 'no English leftovers in the German timeline: ' + leftovers);
  brow = d.querySelector(`#view .trow[data-id="${ids.ST}"] .cmc`);
  check(brow && !brow.classList.contains('unread'), 'opening marks it seen (dot gone)');
  await sleep(300);
  const bst = await api(w, 'GET', '/api/state');
  check(bst.tasks.find(t => t.id === ids.ST).unread === 0, 'server: seen stored');
  // view-only hint + comments allowed for carol
  w.close();
  w = await boot({user: 'carol', hash: 'l/' + ids.L}); d = w.document;
  w.eval(`openDetail(${ids.ST})`); await sleep(900);
  check(d.querySelector('#c-input') && d.querySelector('.rotag'), 'view-only member: read-only task but comment box');
  check(!d.querySelector('#d-url') && !d.querySelector('[data-act="link-edit"]'), 'view-only: no link editing');
  w.close();

  // ---------------- eve: collab OFF (pre-multi-user look)
  w = await boot({user: 'eve', hash: 'l/' + ids.L}); d = w.document;
  const eveFeatures = (await api(w, 'GET', '/api/state')).settings.features;
  check(!d.querySelector('#view .who'), 'collab off: no assignee chips');  // 2.0.6 (#315): comment chips stay (Comments module)
  check(!d.querySelector('#side .shr'), 'collab off: no shared icon');
  check(!d.querySelector('#side .srow[data-go="assigned"]'), 'collab off: no "Assigned to me"');
  w.eval(`openDetail(${ids.ST})`); await sleep(600);
  check(!d.querySelector('#d-assignee'), 'collab off: no assignee picker');
  check(!d.querySelector('#d-tl [data-act="tl-act"]') && !d.querySelector('#d-tl .actl') && !d.querySelector('#d-tl .rx'), '2.0.6 (#315) collab off: comments as notes only (no activity, no reactions)');
  check(d.querySelector('.linkchip'), 'collab off, links on: link chip still shown');
  check(!/only visible to you/.test(d.querySelector('#detail').textContent), 'collab off: no sharing hint at tags');
  w.eval('closeDetail()');
  w.eval(`listModal(${ids.L})`); await sleep(200);
  check(!d.querySelector('#l-members') && !/Sharing/.test(d.querySelector('.modal').textContent), 'collab off: no sharing section in the list dialog');
  d.querySelector('.modal').remove();
  w.eval('settingsModal()'); await sleep(200);
  const tabopts = [...d.querySelectorAll('#s-tabadd option')].map(o => o.value);
  check(!tabopts.includes('s:assigned'), 'collab off: tab bar cannot pin "Assigned to me"');
  const cb = d.querySelector('[data-feat="collab"]');
  check(cb && !cb.checked && !d.querySelector('[data-feat="links"]'), 'settings: collab unchecked, no links switch any more');
  check(/Share lists, assign tasks, @mentions/.test(cb.closest('label').textContent), 'settings: module description');
  check(w.eval(`tabItem('s:assigned')`) === null, 'tabItem(assigned) null when off');
  check(w.eval(`tabItem('news')`) === null && !tabopts.includes('news'), 'collab off: no News tab option');
  check(!d.querySelector('#top .bell'), 'collab off: no bell');
  // link field always on, even with a legacy features string without "links"
  await api(w, 'PATCH', '/api/settings', {features: 'cal,timeline,matrix,habits,pomo,kanban,paperless'});
  d.querySelector('.modal')?.remove();
  await w.eval('load().then(render)'); await sleep(500);
  check(d.querySelector('#view a.lnk'), 'links always: chip shown without the flag');
  const r5 = w.eval(`parseQuick('Read https://github.com/x/y ')`);
  check(r5.title === 'Read' && r5.url === 'https://github.com/x/y', 'links always: parser extracts the URL without the flag ' + JSON.stringify(r5));
  w.eval(`openDetail(${ids.ST})`); await sleep(500);
  check(d.querySelector('.linkchip') || d.querySelector('#d-url') || d.querySelector('[data-act="link-edit"]'), 'links always: link field in the detail');
  w.eval(`go('news')`); await sleep(300);
  check(w.eval('S.route.mod') === 'tasks', 'collab off: #news falls back to tasks');
  await api(w, 'PATCH', '/api/settings', {features: eveFeatures});  // restore eve's features for later
  w.close();

  console.log(`\n${ok} ok, ${F.length} failed`);
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  process.exit(F.length || errs.length ? 1 : 0);
})();
