// 2.559.0 UI tests, part D (#4660): the area Reading shows changes at once (optimistic), own container (start.sh) with the
// kalmido-suite: fresh
// small feed / page server inside (fake_feeds.py, nothing goes out), jsdom. Invented titles and people only.
// - Read later: a pasted link is a row at once (still on its way: no actions), a refusal takes it out and gives the link
//   back to the field; let through it gets its real id. Ticking off takes the row out at once, a refusal brings it back.
// - Feeds: "Read", "Mark all read" and "Read later" show before the answer (the unread count too), a refusal puts the
//   marks and the count back.
// - Bookmarks: a pasted link is a card at once (a refusal takes it out), "Mark read" and the details' Save show at once
//   (the dialog closes), Delete takes the card out at once; a refusal puts each back.
// - a person without an organisation: Read later and Bookmarks the same (freelancer parity)
// - none of these actions fetches the whole state again (no GET /api/state)
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const FS = 'http://127.0.0.1:8098';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098 -e KALMIDO_BOOKMARK_ALLOW_HOSTS=127.0.0.1:8098'}});
fs.copyFileSync(path.join(__dirname, 'fake_feeds.py'), path.join(DATA, 'fake_feeds.py'));
fs.mkdirSync(path.join(DATA, 'feeds'), {recursive: true});
const day = n => new Date(Date.now() - n * 86400000).toUTCString();
fs.writeFileSync(path.join(DATA, 'feeds', 'rss.xml'), `<?xml version="1.0"?><rss version="2.0"><channel><title>Garden News</title><link>${FS}/</link>
<item><title>Tomatoes in pots</title><link>${FS}/a1</link><guid>g1</guid><pubDate>${day(0)}</pubDate><description>Some text</description></item>
<item><title>Herbs on the sill</title><link>${FS}/a2</link><guid>g2</guid><pubDate>${day(1)}</pubDate><description>More text</description></item>
<item><title>Compost basics</title><link>${FS}/a3</link><guid>g3</guid><pubDate>${day(2)}</pubDate><description>Other text</description></item>
</channel></rss>`);
const page = (title, word) => `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title><meta property="og:site_name" content="Example Site">
<meta property="og:description" content="About ${word}"></head><body><article><p>A paragraph about ${word} long enough to count as the reading text.</p></article></body></html>`;
fs.writeFileSync(path.join(DATA, 'feeds', 'one.html'), page('Balcony gardening', 'pelicans'));
fs.writeFileSync(path.join(DATA, 'feeds', 'two.html'), page('Window boxes', 'walrus'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_feeds.py']);
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const FEAT = 'cal,feeds,reading';
// requests matching re ("METHOD /url") wait in w.__held until the test calls go() (the real request) or fail(text, status)
const hold = (w, re) => {
  w.__held = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => re.test(`${o.method || 'GET'} ${u}`)
    ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: (msg, st = 400) => res(new Response(JSON.stringify({error: msg}), {status: st, headers: {'content-type': 'application/json'}}))}))
    : f1(u, o);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };
// every request of the page in w.__sent (to see that no action fetches the whole state again)
const watch = w => { w.__sent = []; const f0 = w.fetch; w.fetch = (u, o = {}) => { w.__sent.push(`${o.method || 'GET'} ${u}`); return f0(u, o); }; };
const stateFetches = w => { let rep = 0; return w.__sent.filter(s => { if (!/^GET \/api\/state(\?|$)/.test(s)) return false; if (/auto=1/.test(s)) { rep = 2; return false; } if (rep) { rep--; return false; } return true; }); };  // the live poll (auto=1) and load()'s up to two repeats when a write crossed it are no reload of the action
const submit = (w, sel) => w.document.querySelector(sel).dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
const toastHas = (d, re) => re.test(d.querySelector('#toast')?.textContent || '');

// ---- Read later: add (held, refused, let through) and tick off (held, refused, let through)
async function readLater(who, ck, url) {
  const w = await boot({user: who, hash: 'reading'}), d = w.document;
  check(await until(() => d.querySelector('#rl-url') && d.querySelector('.rlview .empty')), `${who}: Read later, empty`);
  watch(w);
  const srv = async () => (await call(ck, 'GET', '/api/reading?space=private'));
  const tmpRow = () => [...d.querySelectorAll('.rlrow')].find(r => +r.dataset.id < 0);
  hold(w, /^POST \/api\/reading$/);
  d.querySelector('#rl-url').value = url; submit(w, '[data-rl-form]');
  check(await until(() => w.__held.length === 1), `${who}: Add: the request is on its way (held)`);
  check(tmpRow() && /127\.0\.0\.1/.test(tmpRow().textContent) && !tmpRow().querySelector('[data-rl="tick"]'), `${who}: the row shows before the answer, without actions yet`);
  check(d.querySelector('#rl-url').value === '', `${who}: the field emptied at once`);
  check(!(await srv()).count, `${who}: the server has nothing yet`);
  w.__held[0].fail('Refused for the test');
  check(await until(() => !d.querySelector('.rlrow') && d.querySelector('#rl-url').value === url), `${who}: the refusal takes the row out and gives the link back`);
  check(await until(() => toastHas(d, /Refused for the test/)), `${who}: with the server's message`);
  submit(w, '[data-rl-form]');
  check(await until(() => w.__held.length === 2), `${who}: the second Add is held`);
  check(tmpRow(), `${who}: it shows at once again`);
  w.__held[1].go();
  check(await until(async () => (await srv()).count === 1), `${who}: the server stores it`);
  check(await until(() => d.querySelector('.rlrow') && +d.querySelector('.rlrow').dataset.id > 0 && d.querySelector('.rlrow [data-rl="tick"]')), `${who}: the row carries its real id and can be ticked`);
  unhold(w);
  // tick off
  hold(w, /^POST \/api\/tasks\/\d+\/complete$/);
  d.querySelector('.rlrow [data-rl="tick"]').click();
  check(await until(() => w.__held.length === 1), `${who}: Tick: the request is held`);
  check(!d.querySelector('.rlrow'), `${who}: the row went before the answer`);
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => d.querySelector('.rlrow [data-rl="tick"]')), `${who}: the refusal brings the row back`);
  check((await srv()).count === 1, `${who}: the server still has it open`);
  d.querySelector('.rlrow [data-rl="tick"]').click();
  check(await until(() => w.__held.length === 2), `${who}: the second tick is held`);
  check(!d.querySelector('.rlrow'), `${who}: gone at once again`);
  w.__held[1].go();
  check(await until(async () => (await srv()).done_count === 1), `${who}: the server ticks it off`);
  check(await until(() => toastHas(d, /Read:/)), `${who}: the undo toast after the answer`);
  unhold(w);
  check(!stateFetches(w).length, `${who}: Read later fetched no whole state: ` + stateFetches(w).join(' | '));
  w.close();
}

// ---- Bookmarks: add (held, refused, let through), mark read, the details' Save, delete
async function bookmarks(who, ck, url, title, full) {
  const w = await boot({user: who, hash: 'bookmarks'}), d = w.document;
  check(await until(() => d.querySelector('#bm-url') && d.querySelector('.bmview .empty')), `${who}: Bookmarks, empty`);
  watch(w);
  const srv = async () => ((await call(ck, 'GET', '/api/bookmarks')).items || []);
  const tmpCard = () => [...d.querySelectorAll('.bmcard')].find(r => +r.dataset.id < 0);
  hold(w, /^POST \/api\/bookmarks$/);
  d.querySelector('#bm-url').value = url; submit(w, '[data-bm-form]');
  check(await until(() => w.__held.length === 1), `${who}: Add: the request is on its way (held)`);
  check(tmpCard() && /Loading preview/.test(tmpCard().textContent) && !tmpCard().querySelector('[data-bm="read"]'), `${who}: the card shows before the answer, without actions yet`);
  check(!(await srv()).length, `${who}: the server has none yet`);
  w.__held[0].fail('Refused for the test');
  check(await until(() => !d.querySelector('.bmcard') && d.querySelector('#bm-url').value === url), `${who}: the refusal takes the card out and gives the link back`);
  submit(w, '[data-bm-form]');
  check(await until(() => w.__held.length === 2), `${who}: the second Add is held`);
  check(tmpCard(), `${who}: it shows at once again`);
  w.__held[1].go();
  check(await until(async () => (await srv()).length === 1), `${who}: the server stores it`);
  check(await until(() => new RegExp(title).test(d.querySelector('.bmcard .bmtitle')?.textContent || '') && +d.querySelector('.bmcard').dataset.id > 0), `${who}: the card carries its real id and the fetched title`);
  unhold(w);
  const id = +d.querySelector('.bmcard').dataset.id, card = () => d.querySelector(`.bmcard[data-id="${id}"]`);
  // mark read
  hold(w, /^PATCH \/api\/bookmarks\/\d+$/);
  card().querySelector('[data-bm="read"]').click();
  check(await until(() => w.__held.length === 1), `${who}: Mark read: the request is held`);
  check(card()?.classList.contains('st-read'), `${who}: the card is read before the answer`);
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => card()?.classList.contains('st-unread')), `${who}: the refusal makes it unread again`);
  check((await srv())[0]?.state === 'unread', `${who}: the server has it unread`);
  if (full) {
    card().querySelector('[data-bm="read"]').click();
    check(await until(() => w.__held.length === 2), 'Mark read again: held');
    w.__held[1].go();
    check(await until(async () => (await srv())[0]?.state === 'read'), 'the server marks it read');
    check(await until(() => card()?.classList.contains('st-read')), 'the card stays read after the list came again');
    unhold(w);
    // the details: Save closes at once, the card shows the note; a refusal takes it back
    const openDetail = async () => { card().querySelector('[data-bm="open"]').click(); return until(() => d.querySelector('.modal.bmdlg #bmd-note')); };
    hold(w, /^PATCH \/api\/bookmarks\/\d+$/);
    check(await openDetail(), 'the details open');
    d.querySelector('.modal.bmdlg #bmd-note').value = 'for the weekend';
    d.querySelector('.modal.bmdlg [data-m="save"]').click();
    check(await until(() => w.__held.length === 1), 'Save: the request is held');
    check(!d.querySelector('.modal.bmdlg') && /for the weekend/.test(card()?.querySelector('.bmnote')?.textContent || ''), 'the dialog closed and the card shows the note before the answer');
    w.__held[0].fail('Refused for the test');
    check(await until(() => !card()?.querySelector('.bmnote')), 'the refusal takes the note back');
    check(await openDetail(), 'the details open again');
    d.querySelector('.modal.bmdlg #bmd-note').value = 'for the weekend';
    d.querySelector('.modal.bmdlg [data-m="save"]').click();
    check(await until(() => w.__held.length === 2), 'the second Save is held');
    w.__held[1].go();
    check(await until(async () => (await srv())[0]?.note === 'for the weekend'), 'the server stores the note');
    check(await until(() => /Edit bookmark/.test(w.eval(`HIST.undo[HIST.undo.length - 1]?.label || ''`))), 'the undo step comes after the answer');
    unhold(w);
    // delete
    hold(w, /^DELETE \/api\/bookmarks\/\d+$/);
    check(await openDetail(), 'the details open for Delete');
    d.querySelector('.modal.bmdlg [data-m="del"]').click();
    check(await until(() => w.__held.length === 1), 'Delete: the request is held');
    check(!card(), 'the card went before the answer');
    w.__held[0].fail('Refused for the test', 500);
    check(await until(() => card()), 'the refusal brings the card back');
    check((await srv()).length === 1, 'the server still has it');
    unhold(w);
  }
  unhold(w);
  check(!stateFetches(w).length, `${who}: Bookmarks fetched no whole state: ` + stateFetches(w).join(' | '));
  w.close();
}

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});

  await readLater('alice', CA, FS + '/to-read');

  // ================= Feeds: read, Mark all read, Read later
  check((await call(CA, 'POST', '/api/feeds', {url: FS + '/rss.xml', space: 'private'})).http === 201, 'a private feed');
  const unreadSrv = async () => (await call(CA, 'GET', '/api/feeds/items?space=private')).unread;
  check(await until(async () => await unreadSrv() === 3), 'the feed has three unread articles');
  let w = await boot({user: 'alice', hash: 'feeds'}), d = w.document;
  check(await until(() => d.querySelectorAll('.rsslist .rssitem.unread').length === 3), 'Feeds: three unread articles');
  watch(w);
  const ids = [...d.querySelectorAll('.rsslist .rssitem')].map(x => +x.dataset.id);
  const item = id => d.querySelector(`.rssitem[data-id="${id}"]`);
  const optN = () => d.querySelector('[data-rss-feed] option:not([value="0"])')?.textContent || '';
  check(/\(3\)/.test(optN()), 'the feed choice says 3 unread');
  hold(w, /^POST \/api\/feeds\/read$/);
  item(ids[0]).querySelector('[data-rss="read"]').click();
  check(await until(() => w.__held.length === 1), 'Read: the request is held');
  check(item(ids[0])?.classList.contains('read') && /\(2\)/.test(optN()), 'the article is read and the count says 2 before the answer');
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => item(ids[0])?.classList.contains('unread') && /\(3\)/.test(optN())), 'the refusal makes it unread again, the count 3');
  check(await unreadSrv() === 3, 'the server has three unread');
  item(ids[0]).querySelector('[data-rss="read"]').click();
  check(await until(() => w.__held.length === 2), 'the second Read is held');
  w.__held[1].go();
  check(await until(async () => await unreadSrv() === 2), 'the server marks it read');
  check(item(ids[0])?.classList.contains('read'), 'it stays read');
  // Mark all read
  d.querySelector('[data-rss="allread"]').click();
  check(await until(() => w.__held.length === 3), 'Mark all read: held');
  check(!d.querySelector('.rssitem.unread'), 'all articles are read before the answer');
  w.__held[2].fail('Refused for the test');
  check(await until(() => d.querySelectorAll('.rssitem.unread').length === 2), 'the refusal brings the two unread ones back');
  check(await unreadSrv() === 2, 'the server still has two unread');
  unhold(w);
  // Read later from a feed
  hold(w, /^POST \/api\/feeds\/items\/\d+\/later$/);
  const lat = () => item(ids[1])?.querySelector('[data-rss="later"]');
  lat().click();
  check(await until(() => w.__held.length === 1), 'Read later: held');
  check(lat()?.getAttribute('aria-pressed') === 'true' && /Saved/.test(lat()?.textContent || '') && item(ids[1])?.classList.contains('read'), '"Saved" and read before the answer');
  w.__held[0].fail('Refused for the test');
  check(await until(() => lat() && lat().getAttribute('aria-pressed') !== 'true' && item(ids[1])?.classList.contains('unread')), 'the refusal puts button and mark back');
  lat().click();
  check(await until(() => w.__held.length === 2), 'the second Read later is held');
  w.__held[1].go();
  check(await until(async () => (await call(CA, 'GET', '/api/reading?space=private')).count === 1), 'the server saved it to read later');
  check(await until(() => lat()?.getAttribute('aria-pressed') === 'true'), 'the button stays "Saved"');
  unhold(w);
  check(!stateFetches(w).length, 'Feeds fetched no whole state: ' + stateFetches(w).join(' | '));
  w.close();

  await bookmarks('alice', CA, FS + '/one.html', 'Balcony gardening', true);

  // ================= a person without an organisation: the same at once
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  await readLater('frida', CF, FS + '/frida-reads');
  await bookmarks('frida', CF, FS + '/two.html', 'Window boxes', false);

  console.log(`p2559_d_reading_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
