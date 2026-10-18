// 2.91.0 UI tests, part A (#1923): invoice series, own container (start.sh, mode workspaces), Firefox (desktop + phone width).
// Invented companies, people and figures only.
// - the editor of an invoice has "Repeat as series": the sheet (interval, first period, end, send automatically with its
//   sentence, the placeholders) creates the series
// - the invoice list shows the section "Invoice series" with the series (name, client, interval, next date, amount); the
//   switch pauses it (saved); an invoice made by the series shows "From series ..., period ..." in its editor
// - on a phone nothing sticks out to the side and the controls are large; a member sees neither the button nor the section
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p291_a_ui', check, shots: 'P291A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P291A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

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
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'});
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', lang: 'de', client_id: cl.id, project_title: 'Retainer {month}', service_from: '2026-01-01',
    items: [{title: 'Betreuung', qty: 1, rate: 500}]});
  check(inv.http === 201, 'a template invoice ' + inv.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const series = ev => ev(`fetch('/api/office/series', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.items || [])`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= the editor: "Repeat as series" -> the sheet
    await nav(B + `#office/offers/${inv.id}`);
    check(await ready(ev, `!!document.querySelector('[data-rin="new"]')`, 80), 'the editor of an invoice has "Repeat as series"');
    await ev(`(() => { document.querySelector('[data-rin="new"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #ofd-rin-start') && document.querySelectorAll('.modal [data-rin-every]').length === 3`), 'the sheet: interval and first period');
    check(await ev(`/check and send/i.test(document.querySelector('.modal').textContent) && !!document.querySelector('.modal #ofd-rin-auto') && !document.querySelector('.modal #ofd-rin-auto').checked
      && /\\{period\\}/.test(document.querySelector('.modal .rin-ph').textContent)`), 'the sheet: send automatically off with its sentence, the placeholders');
    await shot('p291-a-sheet.png');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('[data-rin-every="quarterly"]').click(); m.querySelector('#ofd-rin-start').value = '2027-01-01'; m.querySelector('#ofd-rin-title').value = 'Retainer Kunde Eins'; m.querySelector('[data-m="ok"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal')`), 'the sheet closes');
    const ss = await series(ev);
    check(ss.length === 1 && ss[0].every === 'quarterly' && ss[0].start === '2027-01-01' && ss[0].template_id === inv.id && ss[0].title === 'Retainer Kunde Eins' && ss[0].auto_send === 0,
      'the series is saved ' + JSON.stringify(ss[0] || {}).slice(0, 200));
    check(await ready(ev, `/Template of series/.test(document.querySelector('.rin-box')?.textContent || '')`), 'the template shows its series');
    // ================= the invoice list: the section of the series
    await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('[data-ofd="kind"][data-kind="invoice"]')`, 80);
    await ev(`(() => { document.querySelector('[data-ofd="kind"][data-kind="invoice"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.rin-sec .rin-it')`, 60), 'the invoice list shows the section of the series');
    await ev(`(() => { const d = document.querySelector('.rin-sec'); d.open = true; return 1; })()`);
    check(await ev(`(() => { const t = document.querySelector('.rin-sec .rin-it').textContent; return /Retainer Kunde Eins/.test(t) && /Kunde Eins GmbH/.test(t) && /quarterly/.test(t) && /595/.test(t); })()`),
      'the row: name, client, interval, amount ' + await ev(`document.querySelector('.rin-sec .rin-it')?.textContent.replace(/\\s+/g, ' ')`));
    await shot('p291-a-list.png');
    await ev(`(() => { document.querySelector('.rin-sec [data-rin="active"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/series', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.items[0].active === 0)`), 'the switch pauses the series');
    check(await ready(ev, `/paused/.test(document.querySelector('.rin-sec .rin-it')?.textContent || '')`), 'the row says paused');
    // make now -> a draft with the hint
    await ev(`(() => { document.querySelector('.rin-sec [data-rin="run"]').click(); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/series', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.items[0].made_count === 1)`), 'make now: an invoice of the series');
    const made = (await series(ev))[0]?.made?.[0];
    check(await ready(ev, `!!document.querySelector('.ofdlist .rin-tag')`), 'the list marks the invoice of the series');
    await nav(B + `#office/offers/${made?.doc_id}`);
    check(await ready(ev, `/From series Retainer Kunde Eins/.test(document.querySelector('.rin-from')?.textContent || '')`, 80), 'the made invoice: "From series ..., period ..."');
    // phone width
    await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('.rin-sec .rin-it')`, 60);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await ev(`(() => { const d = document.querySelector('.rin-sec'); if (d) d.open = true; return 1; })()`);
    await sleep(400);
    check(await ev(noSide), 'on a phone the series stay inside the screen');
    check(await ev(`[...document.querySelectorAll('.rin-sec .rin-acts button, .rin-sec .rin-acts .swl')].every(x => x.getBoundingClientRect().height >= 43)`), 'on a phone the controls are tappable');
    await shot('p291-a-list-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + `#office/offers/${inv.id}`);
    check(await ready(ev, `!!document.querySelector('.ofdeditor')`, 80), 'the editor (member)');
    check(await ev(`!document.querySelector('[data-rin="new"]') && !document.querySelector('.rin-sec')`), 'a member sees neither the button nor the series');
  }, false);

  console.log(`p291_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
