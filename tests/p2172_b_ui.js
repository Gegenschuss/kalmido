// 2.172.0 UI tests (part B), own container (start.sh) with the fake feed server inside (fake_feeds.py). jsdom:
// #2679 the area Reading (Read later, Feeds, Bookmarks) instead of parts of Home: in the bar of sidebar B, in Settings >
//       Modules, old links #feeds / #bookmarks open in it; the view "Read later" saves a pasted link, ticks it off (undo),
//       the ticked ones on request; a shared link offers "Read later" and lands in the shown workspace
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
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
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

  // ================= #2679 the share sheet: read later in the shown workspace
  w = await boot({user: 'bob', path: 'share?title=' + encodeURIComponent('Shared article') + '&url=' + encodeURIComponent('https://example.org/shared')}); d = w.document;
  await until(() => d.querySelector('[data-sd="later"]'));
  check(d.querySelector('[data-sd="task"]') && d.querySelector('[data-sd="later"]'), '#2679: a shared link offers "Read later"');
  click(w, d.querySelector('[data-sd="later"]'));
  await until(() => w.eval('S.route.mod') === 'reading' && d.querySelector('.rlrow'));
  const v = await call('GET', '/api/reading?space=' + SP, null, CB);
  check((v.items || []).some(x => x.url === 'https://example.org/shared' && x.title === 'Shared article'), '#2679: saved into the organisation (the shown workspace) ' + JSON.stringify(v).slice(0, 200));
  check(!((await call('GET', '/api/reading?space=private', null, CB)).items || []).some(x => x.url === 'https://example.org/shared'), '#2679: … not into Private');
  w.close();

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
