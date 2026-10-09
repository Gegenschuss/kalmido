// 2.35.0 UI tests (agent C), own container (start.sh). jsdom:
// #1094 the language file comes with the version of the code (?v=); a copy in localStorage of an older version while the
//       fetch fails: the old texts show for a moment, then the file is fetched again and the app draws again in the new
//       texts (no page reload); a fresh copy of the same version is used as is; a sign-in page (HTML) is no language file;
//       the automatic reload after an update waits for the second report of the new version (p2270_ui checks it too)
// #1105 no "Refresh" in the list menu (also a shared list); refreshNow stays
// #1107 plans: next run in the date format of the language (de 10.10.2026 07:45)
// #186  file links: a task with smb:// shows the share as a chip with a copy button, file:// is a copy button, the task row
//       carries the folder icon; the detail field accepts a file link
// #1101 Settings > Workspaces: "Lists of the organisation" for its admin; the dialog lists the organisation's lists (no private
//       list), archives one (asks first), deletes an archived one only with its name, the history
// Firefox 390 touch: the dialog fits the phone, actions >= 44 px; the (i) of "Agent follows up" at the right edge of its row
// (a tap in the middle of the row is no (i)), screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2350_c_ui', check, shots: 'P2350C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const SH = (await call('POST', '/api/lists', {name: 'Shared work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: bob.id, role: 'edit'});
  await call('PUT', `/api/lists/${SH}/members`, {user_id: AG, role: 'edit'});
  const BT = (await call('POST', '/api/lists', {name: 'Bob Team', org_id: ORG}, CB)).id;
  const BP = (await call('POST', '/api/lists', {name: 'Bob Private', org_id: null}, CB)).id;
  await call('POST', '/api/tasks', {title: 'Bob task', list_id: BT}, CB);
  const appVer = (await (await fetch(B)).text()).match(/name="kalmido-version" content="([^"]*)"/)?.[1] || '';
  check(/^\d+\.\d+\.\d+/.test(appVer), '#1094: the page names its version ' + appVer);

  // ================= #1094 an old language file in localStorage, the first fetch fails
  await call('PATCH', '/api/settings', {lang: 'de'});
  const seen = [];
  let fails = 1;
  const old = JSON.stringify({code: 'de', ver: '1.0.0', dict: {_meta: {name: 'Deutsch', locale: 'de-DE'}, Inbox: 'ALT-Eingang'}});
  const setupFail = x => { const f0 = x.fetch; x.fetch = (u, o) => { const s = String(u); if (/\/static\/i18n\/de\.json/.test(s)) { seen.push(s); if (fails-- > 0) return Promise.reject(new TypeError('Failed to fetch')); } return f0(u, o); }; };
  let w = await boot({user: 'alice', ls: {'tasks.lang': '"de"', 'tasks.i18n': old}, setup: setupFail}), d = w.document;
  check(seen.length >= 1 && seen.every(u => u.includes('?v=' + encodeURIComponent(appVer))), '#1094: the language file is fetched with the version ' + seen.slice(0, 2).join(' '));
  const st0 = w.eval('({stale: !!I18N.stale, ver: I18N.ver, inbox: tr("Inbox")})');
  check(st0.inbox === 'Eingang' || st0.stale, '#1094: an old copy is only a stopgap (marked stale) ' + JSON.stringify(st0));
  await until(() => w.eval('!I18N.stale && tr("Inbox") === "Eingang"'), 60);
  check(w.eval('!I18N.stale && I18N.ver') === appVer && w.eval('tr("Inbox")') === 'Eingang', '#1094: fetched again: the new texts, the version of the code ' + JSON.stringify(w.eval('({v: I18N.ver, s: !!I18N.stale})')));
  check(/Eingang/.test(d.querySelector('#side')?.textContent || '') && !/ALT-Eingang/.test(d.body.textContent), '#1094: drawn again in the new texts without a page reload');
  check(JSON.parse(w.__store['tasks.i18n']).ver === appVer, '#1094: the copy in localStorage carries the version now');
  w.close();
  // the copy of the current version is used when the fetch fails (offline), not marked
  fails = 99; seen.length = 0;
  const cur = JSON.stringify({code: 'de', ver: appVer, dict: {_meta: {name: 'Deutsch', locale: 'de-DE'}, Inbox: 'Eingang-Kopie'}});
  w = await boot({user: 'alice', ls: {'tasks.lang': '"de"', 'tasks.i18n': cur}, setup: setupFail}); d = w.document;
  check(w.eval('tr("Inbox")') === 'Eingang-Kopie' && !w.eval('I18N.stale'), '#1094: the copy of the same version serves offline, not stale');
  w.close();
  // a sign-in page instead of the file (a proxy login) is no language file
  fails = 0; seen.length = 0;
  w = await boot({user: 'alice', ls: {'tasks.lang': '"de"', 'tasks.i18n': old}, setup: x => { const f0 = x.fetch; let n = 1; x.fetch = (u, o) => /\/static\/i18n\/de\.json/.test(String(u)) && n-- > 0 ? Promise.resolve(new Response('<html>Sign in</html>', {status: 200, headers: {'Content-Type': 'text/html'}})) : f0(u, o); }}); d = w.document;
  await until(() => w.eval('!I18N.stale && tr("Inbox") === "Eingang"'), 60);
  check(w.eval('tr("Inbox")') === 'Eingang' && !w.eval('I18N.stale'), '#1094: an HTML page instead of the file: the old copy only for a moment, then the real file');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #1105 no Refresh in the list menu
  w = await boot({user: 'alice', hash: `l/${SH}`}); d = w.document;
  check(!w.eval('topMoreItems()').some(x => /^Refresh$/.test(x.label)), '#1105: no "Refresh" in the menu of a shared list');
  check(typeof w.eval('refreshNow') === 'function', '#1105: refreshNow stays (offline hint)');

  // ================= #186 file links on a task
  const T = (await call('POST', '/api/tasks', {title: 'Contract', list_id: SH, url: 'smb://nas/Projekte/Kunde A/Vertrag.pdf'})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Local plan', list_id: SH, url: 'file:///Users/me/plan.pdf'})).id;
  w.close(); w = await boot({user: 'alice', hash: `l/${SH}`}); d = w.document;
  const row = d.querySelector(`.trow[data-id="${T}"]`);
  check(row && row.querySelector('a.lnk.flk[href^="smb://"]') && /nas › Projekte › … › Vertrag\.pdf|nas › Projekte › Kunde A › Vertrag\.pdf/.test(row.textContent), '#186: the row shows the share and the file ' + (row?.querySelector('.lnk')?.textContent || ''));
  const row2 = d.querySelector(`.trow[data-id="${T2}"]`);
  check(row2 && row2.querySelector('button.lnk.flk[data-flk^="file://"]') && !row2.querySelector('a[href^="file:"]'), '#186: file:// is a copy button, never a link the browser blocks');
  w.eval(`openDetail(${T})`); await until(() => d.querySelector('#detail .linkf'));
  const lf = d.querySelector('#detail .linkf');
  check(lf.querySelector('a.linkchip.flk[href^="smb://"]') && lf.querySelector('.flkcp[data-flk]') && !lf.querySelector('a[target="_blank"]'), '#186: the detail: chip that opens the share + copy button');
  let copied = '';
  Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: v => { copied = v; return Promise.resolve(); }}});
  click(w, lf.querySelector('.flkcp')); await sleep(100);
  check(copied === 'smb://nas/Projekte/Kunde A/Vertrag.pdf' && /Address copied/.test(d.querySelector('#toast')?.textContent || ''), '#186: copy puts the address on the clipboard ' + copied);
  check(w.eval(`validLink('\\\\\\\\nas\\\\share\\\\x.pdf') && validLink('smb://nas/a') && !validLink('javascript:alert(1)') && !validLink('data:text/html,x')`), '#186: the client check matches the server');
  w.close();

  // ================= #1107 plans: the date format of the language
  await call('POST', `/api/agents/${AG}/schedules`, {title: 'Morning', prompt: 'Brief me', freq: 'daily', time: '07:45', tz: 'Europe/Berlin'});
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  await until(() => d.querySelector(`[data-act="sched-open"][data-aid="${AG}"]`));
  click(w, d.querySelector(`[data-act="sched-open"][data-aid="${AG}"]`)); await until(() => d.querySelector('.schedmd .schedrow'));
  const pt = d.querySelector('.schedmd .schedrow').textContent.replace(/\s+/g, ' ');
  check(/nächste: \d\d\.\d\d\.\d{4},? \d\d:\d\d/.test(pt) && !/nächste: [A-Z][a-z], /.test(pt), '#1107: next run as 10.10.2026 07:45: ' + pt);
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #1101 Lists of the organisation
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('account')`); await until(() => d.querySelector('#s-ws .wsorg'));
  const ob = d.querySelector(`#s-ws [data-oadm="${ORG}"]`);
  check(ob && /Lists of the organisation/.test(ob.textContent), '#1101: the admin has "Lists of the organisation"');
  click(w, ob); await until(() => d.querySelector('.oadmmd .oadmrow'));
  const md = () => d.querySelector('.oadmmd');
  const names = [...md().querySelectorAll('.oadmrow .n b')].map(x => x.textContent);
  check(names.includes('Bob Team') && names.includes('Shared work') && !names.includes('Bob Private') && !/Bob task/.test(md().textContent), '#1101: the organisation\'s lists, no private one, no contents: ' + names);
  const brow = () => md().querySelector(`.oadmrow[data-olid="${BT}"]`);
  check(/Owner: Bob/.test(brow().textContent) && /1 open/.test(brow().textContent), '#1101: owner and numbers in the row ' + brow().textContent.replace(/\s+/g, ' '));
  let asked = ''; w.confirm = t => { asked = t; return true; };
  click(w, brow().querySelector('[data-oa="archive"]')); await until(() => brow()?.querySelector('[data-oa="delete"]'));
  check(/Archive “Bob Team”\?/.test(asked) && brow().querySelector('[data-oa="restore"]'), '#1101: archived after asking: ' + asked);
  check(md().querySelector('.oadmh') && /History/.test(md().querySelector('.oadmlog summary')?.textContent || ''), '#1101: the archive part and the history');
  // delete: a wrong name deletes nothing
  w.prompt = () => 'bob team';
  click(w, brow().querySelector('[data-oa="delete"]')); await sleep(800);
  check(brow() && /does not match/.test(d.querySelector('#toast')?.textContent || ''), '#1101: a wrong name deletes nothing');
  w.prompt = () => 'Bob Team';
  click(w, brow().querySelector('[data-oa="delete"]')); await until(() => !brow());
  check(!brow() && (await call('GET', `/api/orgs/${ORG}/lists`)).lists.every(x => x.id !== BT), '#1101: deleted for good with the name');
  check(/deleted .*Bob Team.* for good/.test(md().querySelector('.oadmlog')?.textContent || ''), '#1101: the history names it');
  check((await call('GET', '/api/news', null, CB)).items.some(x => x.kind === 'orglist'), '#1101: bob got a News entry');
  w.close();
  const wb = await boot({user: 'bob', hash: 'news'}); await sleep(500);
  check(/Alice deleted the list Bob Team for good \(admin of /.test(wb.document.body.textContent), '#1101: bob reads who deleted his list');
  wb.close();
  void BP;

  // ================= Firefox: the phone (390, touch)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { oadmOpen(${ORG}, 'Org'); return 1; })()`); await sleep(1200);
    const g = await ev(`(() => { const c = document.querySelector('.oadmmd .card'); if (!c) return null; const r = c.getBoundingClientRect();
      const bs = [...document.querySelectorAll('.oadmmd .oadmb .btn')].map(b => b.getBoundingClientRect()).map(x => Math.min(x.width, x.height));
      return {left: r.left, right: r.right, min: Math.min(...bs), n: bs.length, wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide, `${tag}: #1101 the dialog fits the phone ` + JSON.stringify(g));
    check(g && g.n >= 2 && g.min >= 44, `${tag}: #1101 its buttons >= 44 px ` + JSON.stringify(g));
    await shot('p2350c-390-orglists.png');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); shareModal(${SH}); return 1; })()`); await sleep(1500);
    const ii = await ev(`(() => { document.querySelectorAll('.modal details').forEach(x => { x.open = true; }); const sw = document.getElementById('l-agf'); const row = sw && sw.closest('.agacc'); if (!row) return null;
      row.scrollIntoView({block: 'center'}); const r = row.getBoundingClientRect(), b = row.querySelector('.ib'); if (!b) return {noib: true}; const br = b.getBoundingClientRect();
      const mid = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return {right: Math.round(r.right - br.right), mid: !!mid?.closest?.('.ib'), inRow: !!mid?.closest?.('.agacc')}; })()`);
    check(ii && !ii.noib && ii.right <= 8 && !ii.mid && ii.inRow, `${tag}: #1107 the (i) of "Agent follows up" at the right edge, the middle of the row is the switch ` + JSON.stringify(ii));
    await shot('p2350c-390-agentfollows.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
