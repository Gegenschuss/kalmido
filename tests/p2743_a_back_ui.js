// 2.743.0 A UI test, own container (start.sh), Firefox. Invented data only.
// kalmido-suite:
// - #5235: the visible Back arrow of a detail page goes *up* in the history (navUp, backnav.js): came the user from the list,
//   it is history.back() - the phone's Back afterwards leaves the list and does NOT open the closed contact again; opened
//   directly (link, reload), the list replaces the detail entry (no new entry, still inside Kalmido). Same for a link
//   marked data-navup (Bookkeeping, Tables, ...).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2743_a_back_ui', check, shots: 'P2743A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2743A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  const feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('contacts');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...feats].join(',')});
  const bk = await call('POST', '/api/books', {name: 'Customers'});
  const cid = (await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Anna Alpha'})).id;
  const lid = (await call('POST', '/api/lists', {name: 'Project one'})).id;
  check(!!cid && !!lid, 'setup: a contact and a project');

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    const hashIs = h => ready(ev, `location.hash === '${h}' && !!S.booted`);
    const backBtn = `document.querySelector('#view [data-ct="back"]')`;

    // 1) list -> contact -> the arrow -> the phone's Back: leaves the list, the contact stays closed
    await nav(B + '#today');
    check(await hashIs('#today'), 'start view');
    await ev(`location.hash = '#contacts'`);
    check(await ready(ev, `!!document.querySelector('#view [data-ctopen="${cid}"]')`), 'the contact list shows the contact');
    await ev(`document.querySelector('#view [data-ctopen="${cid}"]').click()`);
    check(await hashIs(`#contacts/${cid}`) && await ready(ev, `!!${backBtn}`), 'the contact opens with the Back arrow');
    const len = await ev(`history.length`);
    await ev(`${backBtn}.click()`);
    check(await hashIs('#contacts'), 'the arrow shows the list');
    check(await ev(`BN.i`) === 1, 'the arrow went back in the history (view index 1 = the list), no new entry: ' + await ev(`BN.i`));
    await ev(`history.back()`);  // the phone's Back
    check(await hashIs('#today'), 'Back after the arrow leaves the list (to the view before it)');
    await sleep(300);
    check(await ev(`location.hash`) === '#today', 'the closed contact does not open again: ' + await ev(`location.hash`));
    check(await ev(`history.length`) === len, 'no extra history entry from the arrow');

    // 2) direct entry: the contact opened by a link, no list before -> the arrow shows the list, still inside Kalmido
    await nav(B + 'static/icon.svg');
    await nav(B + `#contacts/${cid}`);
    check(await ready(ev, `!!${backBtn}`), 'direct entry: the contact with the Back arrow');
    const len2 = await ev(`history.length`);
    await ev(`${backBtn}.click()`);
    check(await hashIs('#contacts'), 'direct entry: the arrow shows the list (not the page before Kalmido)');
    check(await ready(ev, `!!document.querySelector('#view [data-ctopen="${cid}"]')`), 'direct entry: the list is drawn');
    check(await ev(`history.length`) === len2 && await ev(`BN.i`) === 0, 'direct entry: the list replaced the contact entry (no new entry, first view)');

    // 3) an "up" link (data-navup): back in the history when the target was the view before, else a replace
    await nav(B + 'static/icon.svg');  // a new page load (a hash-only nav from #contacts would be a step of its own)
    await nav(B + '#today');
    await hashIs('#today');
    const i0 = await ev(`BN.i`);
    await ev(`location.hash = '#l/${lid}'`);
    await ready(ev, `S.route.key === 'l:${lid}'`);
    const link = h => ev(`(() => { const a = document.createElement('a'); a.href = '${h}'; a.setAttribute('data-navup', ''); a.textContent = 'up'; document.querySelector('#view').appendChild(a); a.click(); return true; })()`);
    await link('#today');
    check(await hashIs('#today') && await ev(`BN.i`) === i0, 'an up link to the view before goes back in the history');
    await ev(`location.hash = '#l/${lid}'`);
    await ready(ev, `S.route.key === 'l:${lid}'`);
    const len3 = await ev(`history.length`);
    await link('#contacts');  // not the view before: replace
    check(await hashIs('#contacts') && await ev(`BN.i`) === i0 + 1 && await ev(`history.length`) === len3, 'an up link elsewhere replaces the entry');
    await ev(`history.back()`);
    check(await hashIs('#today'), 'Back after the replace skips the replaced view');
  }, false);

  console.log(`p2743_a_back_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
