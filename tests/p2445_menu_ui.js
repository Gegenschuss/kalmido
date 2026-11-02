// 2.445.0 UI tests (#3008: the task "…" and the project "…" tidied, jsdom), fresh DB
// - task menu: the everyday entries on the first level, the rare ones under "More…" (one level deeper), "Indent" without the
//   title of the task above, won't do + delete last; from the task panel nothing its header shows (pin, time, assignee)
// - project menu: one switch hide / show / bottom instead of three entries, for the owner; a choice equal to the default ends
//   the view's own entry; someone who may not set the list option keeps the plain entry; Share not doubled to the header
// kalmido-suite: fresh
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await call(CK, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['comments']});
  await call(CK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const bob = await call(CK, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const P = (await call(CK, 'POST', '/api/lists', {name: 'Shoot', ptype: 'agency', time_tracking: true})).id;
  const A = (await call(CK, 'POST', '/api/tasks', {title: 'A very long title of the task above that used to be cut off', list_id: P})).id;
  const T = (await call(CK, 'POST', '/api/tasks', {title: 'Second', list_id: P})).id;
  await call(CK, 'PATCH', '/api/tasks/' + A, {sort: 1});
  await call(CK, 'PATCH', '/api/tasks/' + T, {sort: 2});  // Second is under the long title: it can be indented
  const r = await call(CK, 'PUT', `/api/lists/${P}/members`, {user_id: bob.id, role: 'edit'});
  check(r.status < 300, 'setup: bob is in the project ' + r.status);

  const w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  check(await until(() => w.eval(`!!taskById(${T}) && routeList()?.id === ${P}`)), 'setup: the project is loaded');
  const labels = () => [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  const open = async js => { w.eval(js); await until(() => d.querySelector('#pop [role="menuitem"]')); return labels(); };
  const anchor = `document.querySelector('#view .trow[data-id="${T}"] .ttl') || document.querySelector('#top h1')`;

  // ================= the task menu, first level
  const one = await open(`taskMenu(${anchor}, ${T})`);
  check(one.length <= 19, 'task menu: at most 19 entries on the first level, was 22 in groups: ' + one.length + ' ' + one.join('|'));
  check(one.includes('Start time tracking') && one.some(x => x.startsWith('Move to project…')) && one.includes('Assign…') && one.includes('Delete'), 'task menu: time, move, assign, delete on the first level ' + one.join('|'));
  check(one.slice(-2).join('|') === 'Won’t do (discard)|Delete', "task menu: won't do + delete last " + one.slice(-3).join('|'));
  for (const x of ['Make it a milestone', 'Save as template', 'Duplicate']) check(!one.includes(x), `task menu: "${x}" is not on the first level`);
  check(one.includes('More…'), 'task menu: More… ' + one.join('|'));
  // ================= the second level
  d.querySelector('#pop .mtmore').click();
  const two = await until(() => labels().includes('Make it a milestone') ? labels() : null);
  check(two && ['Make it a milestone', 'Save as template', 'Duplicate', 'Indent'].every(x => two.includes(x)), 'More…: the rare entries ' + two);
  check(two && !two.some(x => /Indent \(|used to be/.test(x)), 'More…: "Indent" alone, no title in it ' + two);
  check(two && !two.includes('Delete'), 'More…: delete stays on the first level');
  w.eval('closePop()');

  // ================= the task panel: nothing its header shows
  w.eval(`openDetail(${T})`);
  await until(() => d.querySelector('#detail .dtop [data-act="task-menu"]'));
  const pan = await open(`taskMenu(document.querySelector('#detail .dtop [data-act="task-menu"]'), ${T})`);
  check(!pan.includes('Pin') && !pan.includes('Start time tracking'), 'panel: pin + time only in its header ' + pan.join('|'));
  check(!!d.querySelector('#detail .dtop [data-act="pin"]') && !!d.querySelector('#detail .dtop [data-act="timer-toggle"]'), 'panel: the header has both');
  check(!pan.includes('Assign…') === !!d.querySelector('#detail .dmeta [data-act="assign"]'), 'panel: Assign… only without the chip ' + pan.join('|'));
  w.eval('closePop(); closeDetail?.()');

  // ================= the project menu: one switch
  const row = () => w.eval(`JSON.stringify(topMoreItems().filter(x => x && x.rcls === 'mdone3').map(x => x.row.map(b => [b.label, !!b.on])))`);
  const flat = () => w.eval(`JSON.stringify(topMoreItems().filter(x => x && x.label).map(x => x.label))`);
  const def = w.eval(`lmDoneDefault('l:${P}')`), dn = def ? 'Show' : 'Hide', ot = def ? 'Hide' : 'Show';  // the default of this view
  check(row() === JSON.stringify([[['Hide', !def], ['Show', def], ['Bottom', false]]]).replace(/true/g, 'true'), 'switch: the owner sees one row, the default is on ' + row());
  check(!/Hide completed|Show completed|like the default/.test(flat()), 'switch: no separate entries ' + flat());
  const pick = async n => { await open(`menu(document.querySelector('#top h1'), topMoreItems())`); [...d.querySelectorAll('#pop .mdone3 button')].find(b => b.textContent.trim() === n).click(); };
  await pick('Bottom');
  check(await until(() => w.eval(`!!listById(${P}).checklist`)), 'switch: Bottom sets the list option');
  check(await until(() => /"Bottom",true/.test(row())), 'switch: Bottom is on ' + row());
  await pick(ot);
  check(await until(() => w.eval(`!listById(${P}).checklist && showDone() === ${!def}`)), 'switch: the other choice ends Bottom');
  check(w.eval(`lmDoneOwn('l:${P}')`), 'switch: a choice other than the default is the view\'s own');
  await pick(dn);
  check(await until(() => w.eval(`showDone() === ${def} && !lmDoneOwn('l:${P}')`)), 'switch: a choice equal to the default ends the own entry');

  // ================= the sort menu has the same switch
  await open(`sortMenu(document.querySelector('#top h1'))`);
  check(d.querySelectorAll('#pop .mdone3').length === 1 && !labels().includes('Show completed at the bottom'), 'sort menu: the same switch ' + labels().join('|'));
  w.eval('closePop()');

  // 2.474.0 (#3917): two quick writes of one list: the second waits for the first, so the newer value stays on the server
  // (the "plain entry" check below went red when the older "Bottom" overtook and stayed on)
  w.eval(`window.__lp = {n: 0, go: null}; { const f = window.fetch; window.fetch = (u, o) => { if (o?.method === 'PATCH' && /\\/api\\/lists\\/${P}$/.test(String(u))) { const k = ++window.__lp.n; if (k === 1) return new Promise(r => { window.__lp.go = () => r(f(u, o)); }); } return f(u, o); }; }`);
  w.eval(`window.__lpa = listPatch(${P}, {checklist: true}); window.__lpb = listPatch(${P}, {checklist: false}); Promise.all([window.__lpa, window.__lpb]).then(() => { window.__lp.done = true; });`);
  check(await until(() => w.eval('!!window.__lp.go')), 'order: the first write is under way');
  check(w.eval('!listById(' + P + ').checklist && window.__lp.n === 1'), 'order: the second write waits for the first ' + w.eval('window.__lp.n'));
  w.eval('window.__lp.go()');
  check(await until(() => w.eval('!!window.__lp.done && window.__lp.n === 2')), 'order: both writes went out');
  const ol = (await call(CK, 'GET', '/api/state')).lists?.find(x => x.id === P);
  check(ol && !ol.checklist, 'order: the newer value stays on the server ' + ol?.checklist);

  // ================= not doubled to the header
  if (w.eval(`!!document.querySelector('#top [data-act="share-list"]') && topLevel() < 3`)) check(!/Share…/.test(flat()), 'project menu: Share… only in the header ' + flat());
  w.close();

  // ================= who may not set the list option keeps the plain entry
  const wb = await boot({user: 'bob', hash: 'l/' + P});
  check(await until(() => wb.eval(`!!listById(${P}) && routeList()?.id === ${P}`)), 'setup: bob is in the project');
  const bi = wb.eval(`JSON.stringify(topMoreItems().filter(x => x && (x.rcls === 'mdone3' || /completed/.test(x.label || ''))).map(x => x.label || x.rcls))`);
  check(bi === '["Show completed"]', 'a member: the plain entry, no switch: ' + bi);
  wb.close();

  check(!errs.length, 'no page errors ' + errs.slice(0, 3).join(' | '));
  console.log(`p2445_menu_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
