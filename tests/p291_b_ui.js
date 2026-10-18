// 2.91.0 UI tests, part B (#1924): subscriptions and tools in the office, own container (start.sh, mode workspaces), Firefox
// (desktop + phone width). Invented companies, people and figures only.
// - the admin has the tab "Subscriptions & tools": two sums (per month / per year) with the net / gross switch, the hint
//   "hardly used" with its filter, one row per subscription (renewal, cancel by in red when near, users)
// - the switch "hardly used" in the row saves at once (and undo takes it back); "+ Subscription" through the sheet lands in
//   the list; a suggestion "Mark as subscription" moves a fixed cost in; the fixed costs list in the cash flow marks it
// - on a phone the rows are cards and nothing sticks out to the side; a member sees no tab
// (P291B_NOSTART=1: a running server, no start.sh)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p291_b_ui', check, shots: 'P291B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P291B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const today = TC.today();
const addDays = (iso, n) => { const d = new Date(iso + 'T12:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const yearBack = iso => `${+iso.slice(0, 4) - 1}${iso.slice(4, 8)}${iso.slice(5) === '02-29' ? '28' : iso.slice(8)}`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const fx = b => call(CA, 'POST', '/api/office/fixed-costs', {start: today, repeat: 'monthly', vat_rate: 0, ...b});
  const s1 = await fx({label: 'Design Suite', amount: 50, sub: 1, seats: [me.id, 'Freie Kraft'], url: 'https://example.com/design'});
  check(s1.http === 201 && s1.sub === 1, 'a subscription ' + s1.http);
  const s2 = await fx({label: 'Domain', amount: 120, repeat: 'yearly', start: yearBack(addDays(today, 20)), sub: 1, notice_days: 10, remind_days: 7, remind_user: me.id});
  check(s2.cancel_by === addDays(today, 10), 'a subscription to cancel in 10 days ' + s2.cancel_by);
  const c1 = await fx({label: 'Notizen App', amount: 4, category: 'Tools'});
  await fx({label: 'Miete', amount: 900});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const subs = `fetch('/api/office/subs', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.cfBasis', '"net"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/subs');
    check(await ready(ev, `document.querySelectorAll('.abo-list .abo-row').length === 2`, 80), 'the tab lists both subscriptions');
    check(await ev(`!!document.querySelector('#view .ofmenu [data-ofm="subs"]')`), 'the tab "Subscriptions & tools" for the admin');
    check(await ev(`!!document.querySelector('#view .ofmenu [data-ofmg="money"] [data-ofm="subs"]')`), 'the point sits in the menu group Money beside the cash flow (2.92.1, #1917)');
    const sums = await ev(`[...document.querySelectorAll('.abo-sum b')].map(b => b.textContent)`);
    check(sums.length === 2 && /60\.00/.test(sums[0]) && /720\.00/.test(sums[1]), 'the sums per month / per year (net) ' + JSON.stringify(sums));
    check(await ev(`/Domain/.test(document.querySelector('.abo-list .abo-cancel.soon')?.closest('.abo-row').textContent || '')`), 'the near last day to cancel in red');
    check(await ev(`/Freie Kraft/.test(document.querySelector('.abo-list').textContent) && !!document.querySelector('.abo-bell')`), 'users and the bell of the reminder');
    check(await ev(`!document.querySelector('.abo-low')`), 'no hint while nothing is hardly used');
    // the switch "hardly used"
    await ev(`(() => { const i = [...document.querySelectorAll('.abo-row')].find(r => /Design Suite/.test(r.textContent)).querySelector('[data-abo-low]'); i.click(); return 1; })()`);
    check(await ready(ev, `${subs}.then(j => j.totals.low_use_count === 1 && j.totals.low_use_per_year === '600.00')`), 'the switch saves "hardly used" (the saving a year)');
    check(await ready(ev, `!!document.querySelector('.abo-low') && /600\\.00/.test(document.querySelector('.abo-low').textContent)`), 'the hint shows the saving (net) ' + await ev(`document.querySelector('.abo-low')?.textContent`));
    await ev(`(() => { document.querySelector('.abo-low').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.abo-list .abo-row').length === 1`), 'the filter shows only the hardly used');
    await ev(`(() => { document.querySelector('.abo-low').click(); return 1; })()`);
    await shot('p291-b-subs.png');
    // a new subscription through the sheet
    await ev(`(() => { document.querySelector('[data-abo="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #abo-amount')`), 'the subscription sheet');
    check(await ev(`document.querySelector('.modal #abo-category').value === 'Software'`), 'the category proposal "Software"');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('#abo-label').value = 'Projekt Tool'; m.querySelector('#abo-amount').value = '12'; m.querySelector('[data-abo-nd="30"]').click(); m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && document.querySelectorAll('.abo-list .abo-row').length === 3`), 'the new subscription is in the list');
    check(await ev(`${subs}.then(j => j.items.some(f => f.label === 'Projekt Tool' && f.sub === 1 && f.notice_days === 30 && f.vat_rate === 19))`), 'saved as a fixed cost with sub = 1 and 30 days');
    // a suggestion
    check(await ev(`!!document.querySelector('[data-abo="mark"][data-id="${c1.id}"]') && !/Miete/.test(document.querySelector('.abo-cands').textContent)`), 'the suggestion: the tool, not the rent');
    await ev(`(() => { document.querySelector('[data-abo="mark"][data-id="${c1.id}"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.abo-list .abo-row').length === 4`), 'marked as subscription');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone nothing sticks out to the side');
    check(await ev(`[...document.querySelectorAll('.abo-sw')].every(x => x.getBoundingClientRect().height >= 43)`), 'large tap targets for the switch');
    await shot('p291-b-subs-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // the fixed costs list marks it and links to the view
    await nav(B + '#office/cashflow');
    check(await ready(ev, `document.querySelectorAll('.abo-tag').length === 4 && !!document.querySelector('a[href="#office/subs"]')`, 80), 'the fixed costs list marks the subscriptions and links to the view');
    // member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/offers');
    check(await ready(ev, `!!document.querySelector('#view .ofmenu [data-ofm="offers"]')`, 80), 'the office (member)');
    check(await ev(`!document.querySelector('#view .ofmenu [data-ofm="subs"]')`), 'a member sees no tab');
  }, false);

  console.log(`p291_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
