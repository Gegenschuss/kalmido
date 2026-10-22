// 2.97.0 UI tests (part A), own container (start.sh) with the small page server of the feed tests inside (fake_feeds.py). jsdom:
// #1950 bookmarks: a part of the area Home (module "reading"); the view saves a pasted link (one undo step), the card shows the
//       preview once the server fetched it (title, site, picture of the app, link with noopener), search, the tag filter,
//       cards / list, archive (+ undo), the details with the reading text as plain text; the share target /share?url=
//       offers "Save as bookmark", the bookmark button of the browser (/share?bm=1) shows the page, Save keeps it (details).
// Firefox 390 touch: the view has no horizontal scrolling, the buttons are >= 40 px, screenshot.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p297_a_ui', check, shots: 'P297A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const FS = 'http://127.0.0.1:8098';
if (!process.env.P297A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_BOOKMARK_ALLOW_HOSTS=127.0.0.1:8098'}});
fs.copyFileSync(path.join(__dirname, 'fake_feeds.py'), path.join(DATA, 'fake_feeds.py'));
fs.mkdirSync(path.join(DATA, 'feeds'), {recursive: true});
const page = (title, word) => `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><meta property="og:site_name" content="Example Site">
<meta property="og:description" content="About ${word}"><meta property="og:image" content="/pic.png"><script>var x = "never-shown";</script></head>
<body><nav>Menu words</nav><article><p>A paragraph about ${word} that is long enough to count as the reading text of this page.</p>
<p>Another line with <b>bold</b> text <script>document.write("injected")</script> and more words.</p></article></body></html>`;
fs.writeFileSync(path.join(DATA, 'feeds', 'one.html'), page('Gardening on balconies', 'zebrafish'));
fs.writeFileSync(path.join(DATA, 'feeds', 'two.html'), page('Shared from the phone', 'pelican'));
fs.writeFileSync(path.join(DATA, 'feeds', 'three.html'), page('Saved with the button', 'walrus'));
// a 1x1 PNG
fs.writeFileSync(path.join(DATA, 'feeds', 'pic.png'), Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_feeds.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,reading'});

  // ================= the view: empty, then save a link
  let w = await boot({user: 'alice', hash: 'bookmarks'}), d = w.document;
  // 2.172.0 (#2679): Bookmarks moved from the area Home into the area Reading
  check(w.eval(`mg_area('reading')[3].some(p => p[0] === 'bookmarks') && !mg_area('life')[3].some(p => p[0] === 'bookmarks')`), '#1950: Bookmarks is a part of the area Reading (2.172.0)');
  await until(() => d.querySelector('.bmview .empty'));
  check(d.querySelector('.bmview .empty'), '#1950: the empty state with a hint');
  check(d.querySelector('#side [data-sbbpart="bookmarks"][aria-current="page"]'), '#1950: an entry of the area Reading');  // 2.152.2 (#2618): the area's parts are entries of the panel; 2.172.0 (#2679): area Reading
  const inp = d.querySelector('#bm-url');
  check(inp && d.querySelector('label[for="bm-url"]'), '#1950: the link field with a label');
  inp.value = FS + '/one.html';
  d.querySelector('[data-bm-form]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(() => d.querySelector('.bmgrid .bmcard'));
  check(d.querySelectorAll('.bmgrid .bmcard').length === 1, '#1950: the link shows up as a card');
  check(w.eval(`HIST.undo.length`) >= 1 && /Save bookmark/.test(w.eval(`HIST.undo[HIST.undo.length - 1].label`)), '#1950: saving is one undo step');
  await until(() => /Gardening on balconies/.test(d.querySelector('.bmcard .bmtitle')?.textContent || ''), 120);
  const card = d.querySelector('.bmcard');
  check(/Gardening on balconies/.test(card?.querySelector('.bmtitle')?.textContent || ''), '#1950: the card shows the title of the page once fetched');
  check(/Example Site/.test(card?.querySelector('.bmsite')?.textContent || '') && /About zebrafish/.test(card?.querySelector('.bmdesc')?.textContent || ''), '#1950: site and description');
  check(/^\/api\/bookmarks\/\d+\/image/.test(card?.querySelector('.bmpic img')?.getAttribute('src') || ''), '#1950: the picture comes from the app');
  const a = card?.querySelector('a.bmtitle');
  check(a && a.getAttribute('href') === FS + '/one.html' && /noopener/.test(a.rel) && a.target === '_blank', '#1950: the link opens in a new tab with noopener');

  // ================= search, tags, list view, archive + undo
  const id1 = +card.dataset.id;
  await call('POST', '/api/bookmarks', {url: 'https://example.com/other', title: 'Another one', tags: ['recipes']});
  await w.eval(`bm_reload()`);
  await until(() => d.querySelectorAll('.bmcard').length === 2);
  check(d.querySelectorAll('.bmcard').length === 2, '#1950: two bookmarks');
  const q = d.querySelector('[data-bm-q]');
  q.value = 'zebrafish'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => d.querySelectorAll('.bmcard').length === 1);
  check(d.querySelectorAll('.bmcard').length === 1 && +d.querySelector('.bmcard').dataset.id === id1, '#1950: the search finds the reading text');
  const q2 = d.querySelector('[data-bm-q]'); q2.value = 'nothing-like-this'; q2.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => d.querySelector('.bmview .empty'));
  check(/No bookmarks match/.test(d.querySelector('.bmview .empty')?.textContent || ''), '#1950: no match: a clear hint');
  const q3 = d.querySelector('[data-bm-q]'); q3.value = ''; q3.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => d.querySelectorAll('.bmcard').length === 2);
  click(w, d.querySelector('[data-bm-tag="recipes"]'));
  await until(() => d.querySelectorAll('.bmcard').length === 1);
  check(d.querySelectorAll('.bmcard').length === 1 && /Another one/.test(d.querySelector('.bmcard').textContent), '#1950: the tag filter');
  click(w, d.querySelector('[data-bm-tag="recipes"]'));
  await until(() => d.querySelectorAll('.bmcard').length === 2);
  click(w, d.querySelector('[data-bm="list"]'));
  await until(() => d.querySelector('.bmlist .bmrow'));
  check(d.querySelectorAll('.bmlist .bmrow').length === 2 && w.eval(`LS.get('bmView')`) === 'list', '#1950: the list view (remembered)');
  click(w, d.querySelector('[data-bm="cards"]'));
  await until(() => d.querySelector('.bmgrid'));
  click(w, d.querySelector(`.bmcard[data-id="${id1}"] [data-bm="arch"]`));
  await until(() => !d.querySelector(`.bmcard[data-id="${id1}"]`));
  check(!d.querySelector(`.bmcard[data-id="${id1}"]`), '#1950: archived: hidden from the default list');
  await w.eval(`histStep('undo')`);
  await until(() => d.querySelector(`.bmcard[data-id="${id1}"]`));
  check(d.querySelector(`.bmcard[data-id="${id1}"]`), '#1950: one undo step brings it back');

  // ================= the details
  click(w, d.querySelector(`.bmcard[data-id="${id1}"] [data-bm="open"]`));
  await until(() => d.querySelector('.modal.bmdlg'));
  let md = d.querySelector('.modal.bmdlg');
  check(md && md.querySelector('#bmd-title') && md.querySelector('#bmd-note') && md.querySelector('#bmd-tags'), '#1950: details with title, note, tags');
  const tx = md?.querySelector('.bmtextb');
  check(tx && /A paragraph about zebrafish/.test(tx.textContent) && !tx.querySelector('b, script') && !/never-shown|injected|Menu words/.test(tx.textContent), '#1950: the reading text as plain text');
  if (md) { md.querySelector('#bmd-note').value = 'read on Sunday'; click(w, md.querySelector('[data-m="save"]')); }
  await until(() => !d.querySelector('.modal.bmdlg'));
  check((await call('GET', `/api/bookmarks/${id1}`)).note === 'read on Sunday', '#1950: the note is saved');
  w.close();

  // ================= the share target and the bookmark button of the browser
  w = await boot({user: 'alice', path: 'share?title=' + encodeURIComponent('Shared') + '&url=' + encodeURIComponent(FS + '/two.html')}); d = w.document;
  await until(() => d.querySelector('[data-sd="bookmark"]'));
  check(d.querySelector('[data-sd="task"]') && d.querySelector('[data-sd="bookmark"]'), '#1950: a shared link offers "Save as bookmark" next to a new task');
  click(w, d.querySelector('[data-sd="bookmark"]'));
  await until(() => d.querySelector('.modal.bmdlg'));
  check(d.querySelector('.modal.bmdlg') && w.eval(`S.route.mod`) === 'bookmarks', '#1950: saved, the details open in Bookmarks');
  let all = (await call('GET', '/api/bookmarks')).items || [];
  check(all.some(x => x.url === FS + '/two.html'), '#1950: the shared link is a bookmark');
  w.close();
  w = await boot({user: 'alice', path: 'share?bm=1&title=' + encodeURIComponent('Saved with the button') + '&url=' + encodeURIComponent(FS + '/three.html')}); d = w.document;
  await until(() => d.querySelector('.modal.bmconfdlg'));
  check(d.querySelector('.modal.bmconfdlg') && /Saved with the button/.test(d.querySelector('.bmconfdlg').textContent) && !d.querySelector('[data-sd]'),
    '#1950: the bookmark button shows the page first (nothing saved without Save)');
  check(!((await call('GET', '/api/bookmarks')).items || []).some(x => x.url === FS + '/three.html'), '#1950: … not saved yet');
  d.querySelector('.bmconfdlg form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(() => d.querySelector('.modal.bmdlg:not(.bmconfdlg)'));
  check(d.querySelector('.modal.bmdlg:not(.bmconfdlg)'), '#1950: Save keeps it and opens the details');
  all = (await call('GET', '/api/bookmarks')).items || [];
  check(all.some(x => x.url === FS + '/three.html' && x.title === 'Saved with the button'), '#1950: … with the page title');
  check(/javascript:/.test(w.eval(`bm_bookmarklet()`)) && /\/share/.test(w.eval(`bm_bookmarklet()`)) && /bm=1/.test(w.eval(`bm_bookmarklet()`)), '#1950: the bookmarklet opens /share?bm=1');
  w.close();

  // ================= Firefox 390 touch
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#bookmarks');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.bmcard')`).catch(() => false)); i++) await sleep(300);
    await sleep(800);
    const g = await ev(`(() => { const bs = [...document.querySelectorAll('.bmadd .btn, .bmcard .iconbtn, .bmseg button')].map(b => b.getBoundingClientRect()).filter(r => r.width);
      return {wide: document.documentElement.scrollWidth <= 390, min: Math.min(...bs.map(r => r.height)), n: bs.length}; })()`);
    check(g && g.wide, `${tag}: #1950 the view has no horizontal scrolling ` + JSON.stringify(g));
    check(g && g.n > 0 && g.min >= 40, `${tag}: #1950 the buttons are >= 40 px ` + JSON.stringify(g));
    await shot('p297a-390-bookmarks.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
