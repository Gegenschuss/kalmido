// 2.172.0 UI tests (part B), own container (start.sh) with the fake feed server inside (fake_feeds.py). jsdom:
// #2679 the area Reading (Read later, Feeds, Bookmarks) instead of parts of Home: in the bar of sidebar B, in Settings >
//       Modules, old links #feeds / #bookmarks open in it; the view "Read later" saves a pasted link, ticks it off (undo),
//       the ticked ones on request; a shared link offers "Read later"
// 2.490.0 (#4025): the share question picks the target ("Read later · Private" / "· Alpha (Team)", the same for bookmarks
//       and the bookmark button), no longer the shown workspace; Reading off in an organisation = no button; three
//       organisations: one "… in team…"; the server refuses an organisation without membership / with Reading off;
//       a person without an organisation sees only the plain buttons (freelancer parity)
// #2677 Feeds in an organisation's view: no longer hidden there (O3A_PRIV), only the organisation's feeds; a member who
//       is no admin sees no address field / unfollow; the private view shows none of them
// Firefox 390 touch: the view "Read later" has no horizontal scrolling, the buttons are >= 40 px, screenshot.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2172_b_ui', check, shots: 'P2172B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098'}});
fs.copyFileSync(path.join(__dirname, 'fake_feeds.py'), path.join(DATA, 'fake_feeds.py'));
fs.mkdirSync(path.join(DATA, 'feeds'), {recursive: true});
const day = n => new Date(Date.now() - n * 86400000).toUTCString();
const feed = (title, slug) => `<?xml version="1.0"?><rss version="2.0"><channel><title>${title}</title><link>https://example.com/${slug}</link>
<item><title>${title} news</title><link>https://example.com/${slug}/1</link><guid>${slug}1</guid><pubDate>${day(0)}</pubDate><description>Some text</description></item></channel></rss>`;
fs.writeFileSync(path.join(DATA, 'feeds', 'team.xml'), feed('Team Blog', 'team'));
fs.writeFileSync(path.join(DATA, 'feeds', 'mine.xml'), feed('My Blog', 'mine'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_feeds.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,contracts,feeds,reading';

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal']});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id, SP = 'org:' + ORG;
  await call('POST', '/api/users', {orgs: [{id: ORG, role: 'member'}], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: SP}, CB);
  check((await call('POST', '/api/feeds', {url: 'http://127.0.0.1:8098/team.xml', space: SP})).status === 201, 'an organisation feed');
  check((await call('POST', '/api/feeds', {url: 'http://127.0.0.1:8098/mine.xml'})).status === 201, 'a private feed');

  // ================= #2679 the area Reading
  let w = await boot({user: 'alice', hash: 'reading'}), d = w.document;
  check(w.eval(`JSON.stringify(mg_area('reading')[3].map(p => p[0]))`) === '["reading","feeds","bookmarks"]', '#2679: the area Reading with Read later, Feeds, Bookmarks');
  check(w.eval(`!mg_area('life')[3].some(p => ['feeds', 'bookmarks'].includes(p[0])) && !LIFE_MODS.includes('reading')`), '#2679: no longer parts of Home');
  check(w.eval(`!O3A_PRIV.includes('feeds') && !o3a_privOnly('reading')`), '#2677: Reading is not private-only');
  await until(() => d.querySelector('.rlview .empty'));
  check(d.querySelector('.rlview .empty'), '#2679: the view Read later, empty state with a hint');
  check(d.querySelector('#srail [data-sbb="reading"][aria-current="page"]'), '#2679: its own entry in the bar of sidebar B');
  check(d.querySelector('#side [data-sbbpart="reading"][aria-current="page"]') && d.querySelector('#side [data-sbbpart="feeds"]') && d.querySelector('#side [data-sbbpart="bookmarks"]'), '#2679: the three parts in the panel');
  const inp = d.querySelector('#rl-url');
  check(inp && d.querySelector('label[for="rl-url"]'), '#2679: the link field with a label');
  inp.value = 'https://example.com/long-read';
  d.querySelector('[data-rl-form]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(() => d.querySelector('.rlrow'));
  const row = d.querySelector('.rlrow');
  check(row && /example\.com/.test(row.textContent) && row.querySelector('a.bmtitle[target="_blank"][rel~="noopener"]'), '#2679: saved, listed with link and site');
  click(w, d.querySelector('.rlrow [data-rl="tick"]'));
  await until(() => !d.querySelector('.rlrow'));
  check(!d.querySelector('.rlrow'), '#2679: ticked off');
  click(w, d.querySelector('[data-rl="done-list"]'));
  await until(() => d.querySelector('.rlrow'));
  check(d.querySelector('.rlrow.st-read'), '#2679: the ticked ones on request');
  w.eval(`settingsModal('modules')`); await until(() => d.querySelector('[data-mgarea="reading"]'));
  check(d.querySelector('[data-mgarea="reading"]'), '#2679: Settings > Modules: one switch for the area Reading');
  w.close();
  for (const h of ['feeds', 'bookmarks']) {
    w = await boot({user: 'alice', hash: h}); d = w.document;
    await until(() => d.querySelector(`#srail [data-sbb="reading"][aria-current="page"]`));
    check(w.eval('S.route.mod') === h && d.querySelector('#srail [data-sbb="reading"][aria-current="page"]'), `#2679: the old link #${h} opens in the area Reading`);
    w.close();
  }

  // ================= #2677 feeds of the shown workspace
  w = await boot({user: 'alice', hash: 'feeds'}); d = w.document;
  await until(() => d.querySelector('.rssitem'));
  check(/My Blog/.test(d.querySelector('.rssview').textContent) && !/Team Blog/.test(d.querySelector('.rssview').textContent), '#2677: Private shows only the private feeds');
  w.close();
  await call('PATCH', '/api/settings', {workspace: SP});
  w = await boot({user: 'alice', hash: 'feeds'}); d = w.document;
  await until(() => d.querySelector('.rssitem'));
  check(w.eval('S.route.mod') === 'feeds' && w.eval('wsCur()') === SP, '#2677: Feeds stays open in the organisation view (no jump to Private)');
  check(/Team Blog/.test(d.querySelector('.rssview').textContent) && !/My Blog/.test(d.querySelector('.rssview').textContent), '#2677: the organisation view shows only its feeds');
  check(d.querySelector('#rss-url') && d.querySelector('[data-rss="del"]'), '#2677: the admin manages the sources');
  click(w, d.querySelector('.rssitem [data-rss="later"]'));
  await until(() => d.querySelector('.rssitem [data-rss="later"][aria-pressed="true"]'));
  w.close();
  w = await boot({user: 'bob', hash: 'feeds'}); d = w.document;
  await until(() => d.querySelector('.rssitem'));
  check(/Team Blog/.test(d.querySelector('.rssview').textContent), '#2677: a member reads the organisation feeds');
  check(!d.querySelector('#rss-url') && !d.querySelector('[data-rss="del"]') && d.querySelector('.rssro'), '#2677: a member who is no admin: no address field, no unfollow, a hint');
  w.close();
  w = await boot({user: 'bob', hash: 'reading'}); d = w.document;
  await until(() => d.querySelector('.rlrow'));
  check(/Team Blog news/.test(d.querySelector('.rlview').textContent) && !/long-read/.test(d.querySelector('.rlview').textContent), '#2679: the organisation read later: the saved article, none of the private entries');
  w.close();

  // ================= #2679 the share sheet: read later
  // 2.490.0 (#4025): the target is picked in the share question ("Read later · Private" = the plain button, preselected as
  // before; "Read later · Alpha (Team)" per organisation), no longer the shown workspace (Bob shows Alpha)
  const shareAt = async (u, user = 'bob', extra = '') => {
    w = await boot({user, path: 'share?' + extra + 'title=' + encodeURIComponent('Shared article') + '&url=' + encodeURIComponent(u)}); d = w.document;
    await until(() => d.querySelector(extra ? '.modal.bmconfdlg' : '[data-sd="later"]'));
  };
  const has = async (sp, u, ck = CB) => ((await call('GET', '/api/reading?space=' + sp, null, ck)).items || []).some(x => x.url === u);
  await shareAt('https://example.org/shared-private');
  const sdTxt = sel => (d.querySelector(sel)?.textContent || '').trim();
  check(d.querySelector('[data-sd="task"]') && /Read later · Private/.test(sdTxt('[data-sd="later"]')), '#4025: "Read later · Private" ' + sdTxt('[data-sd="later"]'));
  check(/Read later · Alpha \(Team\)/.test(sdTxt(`[data-sd="later:${SP}"]`)), '#4025: "Read later · Alpha (Team)" ' + sdTxt(`[data-sd="later:${SP}"]`));
  check(/Bookmark · Private/.test(sdTxt('[data-sd="bookmark"]')) && /Bookmark · Alpha \(Team\)/.test(sdTxt(`[data-sd="bookmark:${SP}"]`)), '#4025: the same choice for bookmarks');
  check(!d.querySelector('[data-sd="later:team"]'), '#4025: one organisation: its own button, no "in team…"');
  click(w, d.querySelector('[data-sd="later"]'));
  await until(() => w.eval('S.route.mod') === 'reading');
  await until(() => /Private/.test(d.querySelector('#toast')?.textContent || ''));
  check(/Saved to “Read later” in “Private”/.test(d.querySelector('#toast')?.textContent || ''), '#4025: the toast names Private ' + (d.querySelector('#toast')?.textContent || '').slice(0, 120));
  check(await has('private', 'https://example.org/shared-private') && !await has(SP, 'https://example.org/shared-private'), '#4025: saved into Private although Alpha is shown');
  w.close();
  await shareAt('https://example.org/shared');
  click(w, d.querySelector(`[data-sd="later:${SP}"]`));
  await until(() => w.eval('S.route.mod') === 'reading' && d.querySelector('.rlrow'));
  // 2.172.1 A (#2690): the toast names the workspace the link went to
  check(/Saved to “Read later” in “Alpha”/.test(d.querySelector('#toast')?.textContent || ''), '#2690: the toast names the workspace ' + (d.querySelector('#toast')?.textContent || '').slice(0, 120));
  const v = await call('GET', '/api/reading?space=' + SP, null, CB);
  check((v.items || []).some(x => x.url === 'https://example.org/shared' && x.title === 'Shared article'), '#2679: saved into the organisation (picked) ' + JSON.stringify(v).slice(0, 200));
  check(!await has('private', 'https://example.org/shared'), '#2679: … not into Private');
  w.close();
  // 2.490.0 (#4025): a bookmark into the organisation from the share question, and with the bookmark button of the browser
  // (its window offers the same choice, Private preselected)
  await shareAt('http://127.0.0.1:8098/team.xml');
  click(w, d.querySelector(`[data-sd="bookmark:${SP}"]`));
  await until(() => d.querySelector('.modal.bmdlg'));
  const bms = async (sp, u) => ((await call('GET', '/api/bookmarks?space=' + sp, null, CB)).items || []).some(x => x.url === u);
  check(await bms(SP, 'http://127.0.0.1:8098/team.xml') && !await bms('private', 'http://127.0.0.1:8098/team.xml'), '#4025: the bookmark went to Alpha');
  check(/Saved in “Alpha”/.test(d.querySelector('#toast')?.textContent || ''), '#4025: the bookmark toast names Alpha ' + (d.querySelector('#toast')?.textContent || '').slice(0, 120));
  w.close();
  await shareAt('http://127.0.0.1:8098/mine.xml', 'bob', 'bm=1&');
  const sel = d.querySelector('#bmc-sp');
  check(sel && sel.value === 'private' && [...sel.options].map(o => o.textContent).join('|') === 'Bookmark · Private|Bookmark · Alpha (Team)', '#4025: the bookmark button: Private preselected, Alpha (Team) ' + (sel ? [...sel.options].map(o => o.value + '=' + o.textContent).join('|') : 'none'));
  if (sel) sel.value = SP;
  d.querySelector('.bmconfdlg form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(() => d.querySelector('.modal.bmdlg:not(.bmconfdlg)'));
  check(await bms(SP, 'http://127.0.0.1:8098/mine.xml'), '#4025: the bookmark button saved into the picked organisation');
  w.close();
  // 2.490.0 (#4025): an organisation with Reading switched off by its admin has no button; the server refuses it too
  await call('PATCH', `/api/settings`, {workspace: 'private'}, CB);
  check((await call('PATCH', `/api/orgs/${ORG}`, {areas_off: ['reading']})).status === 200, 'Alpha: Reading off');
  await shareAt('https://example.org/off');
  check(!d.querySelector(`[data-sd="later:${SP}"]`) && !d.querySelector(`[data-sd="bookmark:${SP}"]`) && /^Read later$/.test(sdTxt('[data-sd="later"]')), '#4025: Reading off in Alpha: no Alpha button, the plain "Read later" ' + sdTxt('[data-sd="later"]'));
  w.close();
  check((await call('POST', '/api/reading', {url: 'https://example.org/off', space: SP}, CB)).status === 403, '#4025: Reading off in Alpha: saving there 403');
  check((await call('POST', '/api/bookmarks', {url: 'https://example.org/off', space: SP}, CB)).status === 403, '#4025: Reading off in Alpha: a bookmark there 403');
  await call('PATCH', `/api/orgs/${ORG}`, {areas_off: []});
  await call('PATCH', `/api/settings`, {workspace: SP}, CB);
  // 2.490.0 (#4025): three organisations: "Read later in team…" offers them; an organisation Bob is not in is refused (404)
  const O2 = (await call('POST', '/api/orgs', {name: 'Beta'})).id, O3 = (await call('POST', '/api/orgs', {name: 'Gamma'})).id;
  check(O2 && O3, 'two more organisations ' + O2 + ' ' + O3);
  check((await call('POST', '/api/users', {orgs: [{id: ORG, role: 'member'}, {id: O2, role: 'member'}, {id: O3, role: 'member'}], username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'})).status < 300, 'carol in three organisations');
  const CC = await login('carol');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, CC);
  await shareAt('https://example.org/gamma', 'carol');
  check(d.querySelector('[data-sd="later:team"]') && d.querySelector('[data-sd="bookmark:team"]') && !d.querySelector('[data-sd^="later:org:"]'), '#4025: three organisations: one "Read later in team…"');
  click(w, d.querySelector('[data-sd="later:team"]'));
  await until(() => d.querySelector(`[data-sd="later:org:${O3}"]`));
  check([ORG, O2, O3].every(o => d.querySelector(`[data-sd="later:org:${o}"]`)) && /Gamma \(Team\)/.test(sdTxt(`[data-sd="later:org:${O3}"]`)), '#4025: … offers the three organisations');
  click(w, d.querySelector(`[data-sd="later:org:${O3}"]`));
  await until(() => w.eval('S.route.mod') === 'reading');
  await until(() => /Gamma/.test(d.querySelector('#toast')?.textContent || ''));
  check(await has('org:' + O3, 'https://example.org/gamma', CC) && !await has('private', 'https://example.org/gamma', CC), '#4025: saved into Gamma');
  w.close();
  check((await call('POST', '/api/reading', {url: 'https://example.org/x', space: 'org:' + O2}, CB)).status === 404, '#4025: Bob is not in Beta: read later there 404');
  check((await call('POST', '/api/bookmarks', {url: 'https://example.org/x', space: 'org:' + O2}, CB)).status === 404, '#4025: Bob is not in Beta: a bookmark there 404');
  check(!await has('org:' + O2, 'https://example.org/x', CC), '#4025: … nothing landed in Beta');
  // 2.490.0 (#4025): a person without an organisation: only Private, the plain buttons, no team button
  check((await call('POST', '/api/users', {orgs: [], username: 'fred', display_name: 'Fred', password: 'password123', email: 'fred@example.com'})).status < 300, 'fred without an organisation');
  const CF = await login('fred');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CF);
  check(!((await call('GET', '/api/state', null, CF)).me.workspaces || []).length, 'fred is in no organisation');
  await shareAt('https://example.org/fred', 'fred');
  check(/^Read later$/.test(sdTxt('[data-sd="later"]')) && !d.querySelector('[data-sd^="later:"], [data-sd^="bookmark:"]'), '#4025: without an organisation: the plain "Read later", no team button');
  click(w, d.querySelector('[data-sd="later"]'));
  await until(() => w.eval('S.route.mod') === 'reading');
  check(await has('private', 'https://example.org/fred', CF), '#4025: without an organisation: saved privately');
  w.close();
  check((await call('POST', '/api/reading', {url: 'https://example.org/y', space: SP}, CF)).status === 404, '#4025: without an organisation: Alpha refused (404)');

  // ================= Firefox 390 touch
  await call('PATCH', '/api/settings', {workspace: 'private'});
  await call('POST', '/api/reading', {url: 'https://example.com/another-long-read-with-a-very-long-address/that-should-not-overflow', title: 'A long title of an article that wraps on a small phone screen'});
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#reading');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.rlrow')`).catch(() => false)); i++) await sleep(300);
    await sleep(600);
    const g = await ev(`(() => { const bs = [...document.querySelectorAll('.rlrow .iconbtn, .rlview .bmadd .btn')].map(b => b.getBoundingClientRect()).filter(r => r.width);
      return {wide: document.documentElement.scrollWidth <= 390, min: Math.min(...bs.map(r => r.height)), n: bs.length}; })()`);
    check(g && g.wide, `${tag}: #2679 the view has no horizontal scrolling ` + JSON.stringify(g));
    check(g && g.n > 0 && g.min >= 40, `${tag}: #2679 the buttons are >= 40 px ` + JSON.stringify(g));
    await shot('p2172b-390-reading.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
