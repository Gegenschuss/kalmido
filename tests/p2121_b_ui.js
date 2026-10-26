// 2.121.0 UI tests, part B (#2095): the cash book in the office, own container (start.sh), Firefox (desktop + phone width).
// Invented companies, people and figures only.
// - the tab "Cash book" (menu group Money): the balance of the default box, the quick entry (in / out, amount, text, today)
// - an income and an expense in the list with the running balance; one below zero shows the clear error
// - the undo of a booking = a cancellation (nothing deleted); cancelling from the dialog (confirmation) books a counter entry
// - the day closing: the preview (opening, income, expense, closing), the confirmation; afterwards the entries are locked
//   and their dialog is read-only
// - the cash boxes (settings): a rename saves on its own; CSV / PDF links; on a phone nothing sticks out to the side and the
//   quick entry has large targets; a member does not see the cash book
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const {undoToast} = require('./ff');
const firefox = require('./ff')({tag: 'p2121_b_ui', check, shots: 'P2121B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2121B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CBo = await login('bob');
  for (const ck of [CA, CBo]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CBo]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const bk = (await call(CA, 'GET', '/api/office/cashbooks')).books[0];
  const p = await call(CA, 'PATCH', `/api/office/cashbooks/${bk.id}`, {opening: '100'});
  check(p.http === 200 && p.balance === '100.00', 'the default box with an opening balance of 100');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const api = (u) => `fetch('${u}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const bal = `(document.querySelector('.cb-bal')?.textContent || '').replace(/\\s/g, ' ')`;
  const book = (dir, amount, text) => `(() => { document.querySelector('[data-cb="dir"][data-v="${dir}"]').click(); const f = document.querySelector('#cb-quick');
    f.querySelector('#cb-amount').value = '${amount}'; f.querySelector('#cb-text').value = '${text}'; f.querySelector('.cb-go').click(); return 1; })()`;
  const yes = `(() => { const b = document.querySelector('.modal [data-cd="yes"]'); if (!b) return false; b.click(); return true; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.ofmAll', 'true'); localStorage.setItem('tasks.sbbUnfold', '["office:money"]'); /* 2.276.0 (#3039): every office point shown, Money open by hand (the first-day menu: p2276_a_ui.js) */ sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/cashbook');
    check(await ready(ev, `!!document.querySelector('#cb-quick') && !!document.querySelector('.cb-bal')`, 80), 'the cash book with the quick entry');
    check(await ev(`/100[.,]00/.test(${bal})`), 'the balance 100 ' + await ev(bal));
    check(await ev(`!!document.querySelector('#side [data-ofm="cashbook"]')`), 'the office menu has "Cash book"');  // 2.152.2 (#2617): the office points sit in the panel #side
    check(await ev(`!!document.querySelector('.cb-euer') && !!document.querySelector('.cb-note')`), 'the note: not in the income/expense statement');
    // an income, an expense
    await ev(book('in', '25,50', 'Verkauf Theke'));
    check(await ready(ev, `document.querySelectorAll('.cb-list .cb-row').length === 1 && /125[.,]50/.test(${bal})`), 'an income: in the list, balance 125.50 ' + await ev(bal));
    check(await ev(`/1/.test(document.querySelector('.cb-list .cb-no').textContent) && /Undo/.test(document.querySelector('#toast')?.textContent || '')`), 'number 1 and the undo in the toast');
    await ev(book('out', '10', 'Porto'));
    check(await ready(ev, `document.querySelectorAll('.cb-list .cb-row').length === 2 && /115[.,]50/.test(${bal})`), 'an expense: balance 115.50');
    // undo of the expense = a cancellation
    await undoToast(ev, /Booked as no\. 2/);  // 2.312.0 A (#3283): the expense's own toast, not the income's
    check(await ready(ev, `document.querySelectorAll('.cb-list .cb-row').length === 3 && /125[.,]50/.test(${bal}) && /Cancels no\\. 2/.test(document.querySelector('.cb-list').textContent)`),
      'the undo of a booking cancels it (a counter entry no. 3, nothing deleted)');
    // below zero
    await ev(book('out', '500', 'Zu viel'));
    check(await ready(ev, `/below zero/.test(document.querySelector('#cb-qerr')?.textContent || '')`), 'below zero: the clear error under the quick entry');
    check(await ev(`document.querySelectorAll('.cb-list .cb-row').length === 3`), 'nothing booked');
    await shot('p2121-b-cashbook.png');
    // cancel from the dialog
    await ev(`(() => { [...document.querySelectorAll('.cb-list .cb-row')].find(b => b.querySelector('.cb-no').textContent.trim() === '1').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [data-m="cancel"]') && !!document.querySelector('.modal [data-m="save"]')`), 'the entry dialog (open day: editable)');
    await ev(`(() => { document.querySelector('.modal [data-m="cancel"]').click(); return 1; })()`);
    check(await ready(ev, yes), 'the cancellation asks first');
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelectorAll('.cb-list .cb-row').length === 4 && /100[.,]00/.test(${bal})`), 'cancelled: a counter entry, balance 100 ' + await ev(bal));
    check(await ev(`${api('/api/office/cashbooks/' + bk.id + '/entries')}.then(j => j.entries.length === 4 && j.entries[0].storno_of_no === 1 && j.entries.find(e => e.no === 1).cancelled_by_no === 4)`),
      'no. 4 cancels no. 1');
    // the day closing
    await ev(`(() => { document.querySelector('[data-cb="close"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .cb-plan dl') && !document.querySelector('.modal [data-m="save"]').disabled`), 'the closing preview');
    check(await ev(`/100[.,]00/.test(document.querySelector('.modal .cb-plan').textContent) && /cannot be undone/.test(document.querySelector('.modal').textContent)`), 'the preview shows the balances and says: no undo');
    await shot('p2121-b-closing.png');
    await ev(`(() => { document.querySelector('.modal [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, yes), 'closing asks once more');
    check(await ready(ev, `!document.querySelector('.modal') && /Closed up to/.test(document.querySelector('.cb-head').textContent) && document.querySelectorAll('.cb-list .cb-lock').length === 4`), 'closed: every entry locked');
    await ev(`(() => { document.querySelector('.cb-list .cb-row').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .cb-fs[disabled]') && !document.querySelector('.modal [data-m="save"]')`), 'a closed entry opens read-only');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.modal')`);
    check(await ev(`!!document.querySelector('a[href^="/api/office/cashbook.csv"]') && !!document.querySelector('a[href^="/api/office/cashbook.pdf"]')`), 'CSV and PDF links');
    // the cash boxes
    await ev(`(() => { document.querySelector('[data-cb="view"][data-v="books"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.cb-bk input[data-cbf="name"]')`), 'the cash boxes');
    check(await ev(`document.querySelector('.cb-bk input[data-cbf="opening"]').disabled`), 'the opening balance is fixed after the closing');
    await ev(`(() => { const i = document.querySelector('.cb-bk input[data-cbf="name"]'); i.value = 'Ladenkasse'; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `${api('/api/office/cashbooks')}.then(j => j.books[0].name === 'Ladenkasse')`), 'a rename saves on its own');
    await ev(`(() => { document.querySelector('[data-cb="view"][data-v="entries"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#cb-quick')`);
    // phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone the cash book stays inside the screen');
    check(await ev(`['#cb-amount', '#cb-text', '.cb-go', '[data-cb="dir"]'].every(s => document.querySelector(s).getBoundingClientRect().height >= 43)`), 'large targets in the quick entry');
    await shot('p2121-b-cashbook-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('#side [data-ofm="offers"]')`, 80), 'the office (member)');  // 2.152.2 (#2617): the office points sit in the panel #side
    check(await ev(`!document.querySelector('#side [data-ofm="cashbook"]')`), 'a member does not see the cash book');  // 2.152.2 (#2617): the office points sit in the panel #side
  }, false);

  console.log(`p2121_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
