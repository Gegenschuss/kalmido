// 2.85.0 UI tests (part B), own container (start.sh) with a fake feed server inside (fake_feeds.py). jsdom:
// #1162 feeds: the module is off by default, a part of the area Home with its switch in Settings > Modules; the view
//       "Feeds" follows a feed from the address field (one undo step unfollows), shows the articles (title, feed, summary
//       as text, unread marked, links with noopener), "Read later" makes one task in the reading list (the button then
//       says "Saved"), "Read" marks it, "Mark all read" + undo, the card on Home & life with the unread count, the
//       empty state, an OPML export link.
// Firefox 390 touch: the view has no horizontal scrolling, the buttons are >= 40 px, screenshot.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p285_b_ui', check, shots: 'P285B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098'}});
fs.copyFileSync(path.join(__dirname, 'fake_feeds.py'), path.join(DATA, 'fake_feeds.py'));
fs.mkdirSync(path.join(DATA, 'feeds'), {recursive: true});
const day = n => new Date(Date.now() - n * 86400000).toUTCString();
fs.writeFileSync(path.join(DATA, 'feeds', 'rss.xml'), `<?xml version="1.0"?><rss version="2.0"><channel><title>Example News</title><link>https://example.com/</link>
<item><title>Fresh article</title><link>https://example.com/fresh</link><guid>f1</guid><pubDate>${day(0)}</pubDate><description>&lt;b&gt;Bold&lt;/b&gt; words &lt;script&gt;alert(1)&lt;/script&gt;</description></item>
<item><title>Older article</title><link>https://example.com/older</link><guid>f2</guid><pubDate>${day(2)}</pubDate><description>Some text</description></item>
</channel></rss>`);
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_feeds.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,contracts,feeds';

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,contracts'});

  // ================= the module switch: off by default, part of the area Home
  let w = await boot({user: 'alice'}), d = w.document;
  check(!w.eval(`feat('feeds')`), '#1162: the module is off by default');
  // 2.172.0 (#2677): Feeds moved from the area Home into the area Reading
  check(w.eval(`mg_area('reading')[3].some(p => p[0] === 'feeds') && !mg_area('life')[3].some(p => p[0] === 'feeds')`), '#1162: Feeds is a part of the area Reading (2.172.0)');
  w.eval(`settingsModal('modules')`); await until(() => d.querySelector('[data-feat="feeds"]'));
  const sw = d.querySelector('[data-feat="feeds"]');
  check(sw && !sw.checked, '#1162: Settings > Modules has the switch, off');
  if (sw) { sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const fts = async () => ((await call('GET', '/api/state')).settings?.features || '').split(',');
  await until(async () => (await fts()).includes('feeds'));
  check((await fts()).includes('feeds'), '#1162: the switch turns the module on');
  w.close();
  await call('PATCH', '/api/settings', {features: FEAT});

  // ================= the view: empty, then follow a feed
  w = await boot({user: 'alice', hash: 'feeds'}); d = w.document;
  await until(() => d.querySelector('.rssview .empty'));
  check(d.querySelector('.rssview .empty'), '#1162: the empty state with a hint');
  check(d.querySelector('#side [data-sbbpart="feeds"][aria-current="page"]'), '#1162: a part of the area Reading');  // 2.152.2 (#2618): the part in the panel instead of a tab; 2.172.0 (#2677): area Reading
  const inp = d.querySelector('#rss-url');
  check(inp && d.querySelector('label[for="rss-url"]'), '#1162: the address field with a label');
  inp.value = 'http://127.0.0.1:8098/rss.xml';
  d.querySelector('[data-rss-form]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(() => d.querySelectorAll('.rsslist .rssitem').length === 2);
  const items = [...d.querySelectorAll('.rsslist .rssitem')];
  check(items.length === 2, '#1162: following fetches the articles at once');
  check(items[0]?.textContent.includes('Fresh article') && items[0].textContent.includes('Example News'), '#1162: title + feed name, newest first');
  check(items[0]?.classList.contains('unread'), '#1162: unread marked');
  const sum = items[0]?.querySelector('.rsssum');
  check(sum && sum.textContent.trim() === 'Bold words' && !sum.querySelector('b, script'), '#1162: the summary as plain text ' + sum?.innerHTML);
  const a = items[0]?.querySelector('a[target="_blank"]');
  check(a && a.getAttribute('href') === 'https://example.com/fresh' && /noopener/.test(a.rel) && /noreferrer/.test(a.rel), '#1162: the link opens in a new tab with noopener noreferrer');
  check(!d.querySelector('.rssview img'), '#1162: no pictures');
  check(d.querySelector('a[href^="/api/feeds/opml"]'), '#1162: the menu offers the OPML export');  // 2.172.0 (#2677): + ?space=
  check(d.querySelector('[data-rss-opml]'), '#1162: … and the OPML import');
  check(w.eval(`HIST.undo.length`) >= 1 && /Follow feed/.test(w.eval(`HIST.undo[HIST.undo.length - 1].label`)), '#1162: following is one undo step');

  // ================= read later
  const lat = () => d.querySelector(`.rssitem[data-id="${items[0].dataset.id}"] [data-rss="later"]`);
  click(w, lat());
  await until(() => lat()?.getAttribute('aria-pressed') === 'true');
  check(lat()?.textContent.includes('Saved'), '#1162: "Read later" -> "Saved"');
  const st = await call('GET', '/api/state');
  const rl = st.lists.find(l => l.life === 'reading');
  const tasks = (st.tasks || []).filter(t => rl && t.list_id === rl.id);
  check(rl && tasks.length === 1 && tasks[0].title === 'Fresh article' && tasks[0].url === 'https://example.com/fresh', '#1162: one task with title + link in the reading list ' + JSON.stringify(tasks).slice(0, 200));
  click(w, lat()); await sleep(800);
  const st2 = await call('GET', '/api/state');
  check((st2.tasks || []).filter(t => rl && t.list_id === rl.id).length === 1, '#1162: a second press makes no second task');
  check(d.querySelector(`.rssitem[data-id="${items[0].dataset.id}"]`)?.classList.contains('read'), '#1162: a saved article counts as read');

  // ================= read, all read + undo
  const rd = () => d.querySelector(`.rssitem[data-id="${items[1].dataset.id}"] [data-rss="read"]`);
  click(w, rd());
  await until(() => d.querySelector(`.rssitem[data-id="${items[1].dataset.id}"]`)?.classList.contains('read'));
  check(d.querySelector(`.rssitem[data-id="${items[1].dataset.id}"]`)?.classList.contains('read'), '#1162: "Read" marks the article');
  click(w, rd());
  await until(() => d.querySelector(`.rssitem[data-id="${items[1].dataset.id}"]`)?.classList.contains('unread'));
  check(d.querySelector(`.rssitem[data-id="${items[1].dataset.id}"]`)?.classList.contains('unread'), '#1162: … and "Unread" back');
  click(w, d.querySelector('[data-rss="allread"]'));
  await until(() => !d.querySelector('.rssitem.unread'));
  check(!d.querySelector('.rssitem.unread'), '#1162: "Mark all read"');
  await w.eval(`histStep('undo')`);
  await until(() => d.querySelector('.rssitem.unread'));
  check(d.querySelector('.rssitem.unread'), '#1162: one undo step brings the unread one back');
  w.close();

  // ================= the card on Home & life
  w = await boot({user: 'alice', hash: 'life'}); d = w.document;
  await until(() => d.querySelector('.lc-feeds .dcn'));
  check(d.querySelector('.lc-feeds'), '#1162: Home & life has the card Feeds');
  check(d.querySelector('.lc-feeds .dcn')?.textContent === '1', '#1162: … with the unread count ' + d.querySelector('.lc-feeds .dcn')?.textContent);
  check(d.querySelector('.lc-feeds a[href="#feeds"]'), '#1162: … and a way to the view');
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
    await o.nav(B + '#feeds');
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.rssitem')`).catch(() => false)); i++) await sleep(300);
    await sleep(600);
    const g = await ev(`(() => { const bs = [...document.querySelectorAll('.rssacts .btn, .rssadd .btn')].map(b => b.getBoundingClientRect()).filter(r => r.width);
      return {wide: document.documentElement.scrollWidth <= 390, min: Math.min(...bs.map(r => r.height)), n: bs.length}; })()`);
    check(g && g.wide, `${tag}: #1162 the view has no horizontal scrolling ` + JSON.stringify(g));
    check(g && g.n > 0 && g.min >= 40, `${tag}: #1162 the buttons are >= 40 px ` + JSON.stringify(g));
    await shot('p285b-390-feeds.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
