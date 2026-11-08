// 2.619.0 A UI test (#4947, #4943), own container (start.sh), jsdom, a person WITHOUT an organisation (frida, as
// kalmido-suite: fresh
// tests/freelancer_fixture.py) and alice for a task frida may not see. Invented names only.
// - #4947 knowledge pages: a bare #123 is plain text (no link, no "Mentioned in", no task link on the server); only [[#123]]
//   (and [[#123|label]]) links a task: the link with its title for who may see the task, a foreign task stays "#id" without
//   its title; the same rule in a locked space (wkeTasks), for the checkbox lines (wem_cbAll) and in code nothing is linked;
//   the "/" task search puts [[#id]]
// - #4943 phone: Back closes the quick add sheet, also after a menu opened in it took the close hook (closePop alone left
//   the sheet open); a tap on the area icon of the page already open closes the drawer; go() to the same address in
//   another spelling (decoded) runs route() and closes the drawer
// freelancer-matrix: wiki, tasks
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2619A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true}, AK);
  const st0 = await call('GET', '/api/state', null, AK);
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats}, AK);
  const FT = (await call('POST', '/api/tasks', {title: 'Secret merger plan'}, AK)).id;  // alice's own: frida may not see it
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  CK = await login('frida');
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'setup: frida has no organisation');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const T1 = (await call('POST', '/api/tasks', {title: 'Mix the stems'})).id;
  check(T1 > 0 && FT > 0 && T1 !== FT, 'setup: the tasks');

  // ================= #4947 the server: only [[#id]] is a task link
  const mk = async (p, body) => (await call('POST', '/api/wiki/pages', {space: 'private', path: p, body})).id;
  const BARE = await mk('Tracker settings', `First Frame is #${T1}: OFF\nLens #${T1} wide`);
  const LINK = await mk('Mix notes', `Next: [[#${T1}]], foreign [[#${FT}]], alias [[#${T1}|the mix]]\n\nIn code: \`[[#${T1}]]\``);
  check(BARE > 0 && LINK > 0, 'setup: the pages');
  const men = await call('GET', '/api/wiki/mentions?task=' + T1);
  check(JSON.stringify((men.pages || []).map(p => p.id)) === JSON.stringify([LINK]), '#4947: "Mentioned in" lists only the page with [[#id]], not the bare #id ' + JSON.stringify(men.pages));
  check((await call('GET', '/api/wiki/mentions?task=' + FT)).http === 404, '#4947: mentions of a task frida may not see: 404');
  check(!JSON.stringify(await call('GET', '/api/wiki/pages/' + LINK)).includes('Secret merger'), '#4947: the page never carries the foreign title');
  const men2 = await call('GET', '/api/wiki/mentions?task=' + FT, null, AK);
  check(Array.isArray(men2.pages) && !men2.pages.length, '#4947: alice: frida\'s private page is not hers to see ' + JSON.stringify(men2));

  // ================= #4947 the read view
  let w = await boot({user: 'frida', hash: 'wiki/' + BARE, ls: {'tasks.wkSpace': JSON.stringify('private'), 'tasks.wkRo': '"1"'}}), d = w.document;
  const md = () => d.querySelector('#wk-md');
  check(await until(() => md()?.textContent.includes('First Frame is #' + T1)), '#4947: the bare page is drawn with its text');
  check(!md().querySelector('a.tref, a[data-tref]'), '#4947: a bare #id is no task link ' + (md()?.innerHTML || '').slice(0, 300));
  w.location.hash = 'wiki/' + LINK;
  const tl = await until(() => md()?.querySelector(`a.tref[data-tref="${T1}"]`));
  check(tl && tl.title === 'Mix the stems' && tl.textContent.includes('Mix the stems') && tl.getAttribute('href') === '#t/' + T1, '#4947: [[#id]] = the task link with its title ' + (tl?.outerHTML || 'none'));
  const al = [...md().querySelectorAll(`a.tref[data-tref="${T1}"]`)].find(a => a.textContent === 'the mix');
  check(!!al, '#4947: [[#id|label]] shows the label as the link');
  check(!md().querySelector(`a[data-tref="${FT}"]`) && !md().textContent.includes('Secret merger') && md().textContent.includes('#' + FT), '#4947: a foreign task: plain "#id", no title ' + md().textContent.slice(0, 200));
  const noCode = (() => { const c = md().cloneNode(true); c.querySelectorAll('code').forEach(x => x.remove()); return c.textContent; })();
  check(!noCode.includes('[[#'), '#4947: no brackets left outside code ' + noCode.slice(0, 200));
  check(md().querySelector('code')?.textContent === `[[#${T1}]]` && !md().querySelector('code a'), '#4947: in code it stays text');
  // the other places of the same rule
  check(JSON.stringify(w.eval(`[...wkeTasks('a #5 b [[#6]] c [[#7|x]] d [[ #8]]')]`)) === '[6,7]', '#4947: a locked space (wkeTasks) reads only [[#id]]');
  check(JSON.stringify(w.eval(`wem_cbAll('- [ ] Call #12\\n- [ ] Mail [[#13]]').map(L => [L.has, L.tid])`)) === '[[false,0],[true,13]]', '#4947: checkbox lines link a task only with [[#id]]');
  check(w.eval(`wem_cbAll('- [ ] Call #12')[0].has`) === false, '#4947: a bare #id line can still become a task');
  w.eval(`(() => { const ta = document.createElement('textarea'); ta.id = 'p2619ta'; document.body.appendChild(ta); ta.value = 'Start\\n#'; ta.setSelectionRange(7, 7); WK.ac = {from: 6, hits: [], i: 0, tk: true}; WKLV.tk = {at: 6}; wklv_tkPick(ta, {tid: ${T1}}); })()`);
  check(d.querySelector('#p2619ta')?.value === `Start\n[[#${T1}]] `, '#4947: the "/" task search puts [[#id]] ' + JSON.stringify(d.querySelector('#p2619ta')?.value));
  w.close();

  // ================= #4943 phone: Back closes the quick add sheet
  w = await boot({user: 'frida', mobile: true, hash: 'today'}); d = w.document;
  const sheet = () => d.querySelector('.qadd.sheet:not(.an-out)');
  check(w.eval('isTouch()') === true, '#4943: the phone window counts as touch (the Back handling is on)');
  w.eval('openQuickSheet()');
  check(await until(() => sheet() && w.history.state?.f8d), '#4943: the open sheet has its own history entry');
  w.history.back();
  check(await until(() => !sheet() && d.querySelector('#scrim').classList.contains('hidden')), '#4943: Back closes the sheet and its scrim');
  check(await until(() => !w.history.state?.f8d && w.location.hash === '#today'), '#4943: the page stays (no route change) ' + w.location.hash);
  // a menu opened in the sheet (list, template) takes popOnClose; after it closed, Back closed nothing (the old 'pop' way)
  await sleep(400);
  w.eval('openQuickSheet()');
  await until(() => sheet() && w.history.state?.f8d);
  w.eval(`openPop(document.querySelector('#qsheet'), '<div class="p2619m">menu</div>')`);
  check(!d.querySelector('#pop').classList.contains('hidden'), '#4943: a menu over the sheet');
  // 2.652.0 (#5070): the menu has its own history entry over the sheet's (one per level); Back once it is there
  check(await until(() => w.history.state?.f8d === 2), '#4943: the menu over the sheet has its own history entry');
  w.history.back();
  check(await until(() => d.querySelector('#pop').classList.contains('hidden')), '#4943: Back closes the menu first');
  check(!!sheet(), '#4943: … the sheet stays under it');
  check(await until(() => w.history.state?.f8d), '#4943: the sheet has its history entry again');
  w.history.back();
  check(await until(() => !sheet() && d.querySelector('#scrim').classList.contains('hidden')), '#4943: the next Back closes the sheet (the menu had taken its close hook)');
  await sleep(400);

  // ================= #4943 the drawer: the entry of the open page closes it
  const home = w.eval(`sbb_home('tasks')`);
  w.location.hash = home;
  await until(() => w.location.hash === '#' + home && w.eval('S.route.mod + "/" + S.route.key') !== 'tasks/today');
  w.eval('sideDrawerOpen(); renderSide()');
  const on = await until(() => d.querySelector('#side.open .sbmr .srb.on[data-sbb]'));
  check(on && on.dataset.go === home, '#4943: the drawer shows the open area marked ' + (on?.outerHTML || '').slice(0, 160));
  on?.click();
  check(await until(() => !d.querySelector('#side.open')), '#4943: a tap on the icon of the page already open closes the drawer');
  check(w.location.hash === '#' + home, '#4943: … and stays on the page');
  // go() to the same address in another spelling: no hashchange, route() itself closes the drawer
  w.location.hash = 'tag/' + encodeURIComponent('café');
  check(await until(() => w.eval('S.route.key') === 'tag:café'), '#4943: on the tag page ' + w.eval('S.route.key'));
  w.eval('sideDrawerOpen()');
  check(!!d.querySelector('#side.open'), '#4943: the drawer is open again');
  w.eval(`go('tag/café')`);
  check(await until(() => !d.querySelector('#side.open')), '#4943: go() to the same page (decoded spelling) closes the drawer');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
