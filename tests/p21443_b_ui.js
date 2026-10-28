// 2.147.1 UI tests, part B (#2054): suggested payment reminders + the GiroCode setting, own container (start.sh, mode
// workspaces), Firefox (desktop + phone width). Invented companies, people and figures only.
// - an overdue invoice (watchdog): the invoice list shows "1 payment reminder suggested" with a jump; the jump opens the
//   reminder list with its drafts, the suggested draft is marked and the list says nothing goes out automatically
// - the office settings: "Suggest payment reminders", the days (7) and the GiroCode switch, saved
// - on a phone the hint stays inside the screen and is a large target
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21443_b_ui', check, shots: 'P21443B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21443B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const sql = (q, args = []) => execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(args)]);
const FEAT = 'cal,comments,collab,office,clients';
const ago = n => { const d = new Date(Date.now() - n * 864e5); return d.toISOString().slice(0, 10); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const st = await call(CA, 'PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', email: 'hallo@beispiel.example', vat_id: 'DE123456789',
    iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  check(st.http === 200, 'office settings ' + st.http);
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'});
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', lang: 'de', client_id: cl.id, project_title: 'Schnitt', service_from: '2026-05-01', items: [{title: 'Schnitt', qty: 1, rate: 500}]});
  check(inv.http === 201, 'an invoice ' + inv.http);
  const fin = await call(CA, 'POST', `/api/office/docs/${inv.id}/finalize`);
  check(fin.http === 200, 'finalised ' + fin.http + ' ' + JSON.stringify(fin).slice(0, 200));
  sql('UPDATE office_docs SET due_date=? WHERE id=?', [ago(12), inv.id]);
  let sug = 0;
  for (let i = 0; i < 120 && !sug; i++) { sug = (await call(CA, 'GET', '/api/office/docs?kind=invoice')).dunning?.suggested || 0; if (!sug) await sleep(500); }
  check(sug === 1, 'the watchdog suggests one reminder ' + sug);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= the invoice list: the hint with the jump
    await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('[data-ofd="kind"][data-kind="invoice"]')`, 80);
    // 2.109.0 (#2054): the first click can land before the office view is wired up (race seen on the Mac runner) -> click again
    let hint = false;
    for (let k = 0; k < 4 && !hint; k++) {
      await ev(`(() => { document.querySelector('[data-ofd="kind"][data-kind="invoice"]')?.click(); return 1; })()`);
      hint = await ready(ev, `/1 payment reminder suggested/.test(document.querySelector('.dun-hint.dun-go')?.textContent || '')`, 40);
    }
    check(hint, 'the invoice list: "1 payment reminder suggested"');
    await shot('p21443-b-hint.png');
    await ev(`(() => { document.querySelector('.dun-hint.dun-go').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('[data-ofd="kind"][data-kind="reminder"]')?.getAttribute('aria-selected') === 'true' && document.querySelector('#ofd-status')?.value === 'draft'`, 60),
      'the jump: the reminder list with its drafts');
    check(await ready(ev, `document.querySelectorAll('.ofdlist .dun-tag').length === 1 && /nothing goes out automatically/.test(document.querySelector('p.dun-hint')?.textContent || '')`, 60),
      'the reminder list marks the suggested draft and says nothing is sent');
    // phone width
    await ev(`(() => { document.querySelector('[data-ofd="kind"][data-kind="invoice"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.dun-hint.dun-go')`, 60);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone the list stays inside the screen');
    check(await ev(`document.querySelector('.dun-hint.dun-go').getBoundingClientRect().height >= 43`), 'on a phone the hint is a large target');
    await shot('p21443-b-hint-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= the settings
    // 2.147.1 (#2054): the office settings come in areas and save each field on its own (#2247): the area "docs" holds both
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');
    await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub="docs"]')`, 80);
    await ev(`(() => { document.querySelector('#ofc-set [data-ostsub="docs"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#os-dun-on')?.getClientRects().length && !!document.querySelector('#os-girocode')`, 80), 'the settings: suggestions and GiroCode in the area of documents');
    check(await ev(`document.querySelector('#os-dun-on').checked && document.querySelector('#os-dun-days').value === '7' && document.querySelector('#os-girocode').checked`), 'the settings: defaults on, 7 days');
    await ev(`(() => { const d = document.querySelector('#os-dun-days'); d.focus(); d.value = '5'; d.dispatchEvent(new Event('input', {bubbles: true})); d.dispatchEvent(new FocusEvent('focusout', {bubbles: true})); return 1; })()`);
    await ready(ev, `fetch('/api/office/settings', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.settings.dunning_grace_days === 5)`, 60);
    await ev(`(() => { const g = document.querySelector('#os-girocode'); g.checked = false; g.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/settings', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.settings.dunning_grace_days === 5 && j.settings.girocode === 0 && j.settings.dunning_suggest === 1)`, 60),
      'the settings are saved');
    await shot('p21443-b-settings.png');
  }, false);

  console.log(`p21443_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
