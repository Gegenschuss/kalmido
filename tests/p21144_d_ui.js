// 2.114.4 UI tests, part D (#2269 #2286), own container (start.sh), Firefox (desktop + phone width). Invented companies and figures only.
// freelancer-matrix: office
// - #2269: the invoice-from-quotation dialog: the radio buttons stay narrow and the text starts right next to them
// - #2286: travel list: no receipts -> the per diem is the bold main amount, no receipts column; with receipts two columns
//   "Per diem" / "Receipts", a missing value is a dash; the evaluation hides the receipts block when there are none
// run as the admin of an organisation AND as a person without organisation
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21144_d_ui', check, shots: 'P21144D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P21144D_NOSTART !== '1' && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const svc = (title, qty, rate) => ({kind: 'service', title, qty, unit: 'day', rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});

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
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noScroll = `document.documentElement.scrollWidth <= window.innerWidth + 1`;

  // quotations with a part for both, trips: 2024 without receipts, 2025 with a receipt on one trip only
  const prep = {};
  for (const [u, ck] of [['alice', CA], ['frida', CF]]) {
    const doc = await call(ck, 'POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Campaign ' + u, items: [svc('Concept', 1, 800)]});
    check(doc.http === 201, u + ': a quotation ' + doc.http);
    const pa = await call(ck, 'POST', `/api/office/docs/${doc.id}/parts`, {title: 'Module A'});
    await call(ck, 'PUT', `/api/office/docs/${doc.id}/parts/${pa.part.id}/items`, {items: [svc('Animation', 2, 500)]});
    const t1 = await call(ck, 'POST', '/api/office/trips', {date_from: '2024-03-10', date_to: '2024-03-12', overnight: 1, dest: 'Hamburg', people: [{name: 'Externe Person'}]});
    check(t1.http === 201, u + ': a trip without receipts ' + t1.http);
    prep[u] = {doc: doc.id};
  }
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    for (const [w, h] of [[1280, 900], [390, 844]]) for (const u of ['alice', 'frida']) {
      const tag = `${u} ${w}px: `;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await signIn(ev, u);
      // ---- #2269
      await nav(B + `#office/offers/${prep[u].doc}`);
      check(await ready(ev, `!!document.querySelector('[data-ofd="to-invoice"]')`, 80), tag + 'the quotation editor');
      await ev(`document.querySelector('[data-ofd="to-invoice"]').click()`);
      check(await ready(ev, `!!document.querySelector('.tpmode input[type=radio]')`, 40), tag + 'the invoice dialog');
      check(await ev(`[...document.querySelectorAll('.tpmode input')].every(i => i.getBoundingClientRect().width < 48)`), tag + '#2269: the radio buttons stay narrow');
      check(await ev(`[...document.querySelectorAll('.tpmode')].every(l => { const i = l.querySelector('input').getBoundingClientRect(), s = l.querySelector('span').getBoundingClientRect(); return s.left >= i.right - 1 && s.left - i.right < 24 && s.right <= l.getBoundingClientRect().right + 1; })`), tag + '#2269: the text starts next to the radio button');
      await shot(`p21144-d-dialog-${u}-${w}.png`);
      await ev(`document.querySelector('.modal [data-m="close"]')?.click()`);
      // ---- #2286 year without receipts
      await nav(B + 'static/icon.svg');  // fresh page: no dialog or stale hash state left over
      await nav(B + '#office/travel');
      check(await ready(ev, `!!document.querySelector('#rk-year')`, 80), tag + 'the travel tab');
      await ev(`(() => { const s = document.querySelector('#rk-year'); s.value = '2024'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
      check(await ready(ev, `document.querySelectorAll('.rklist .ofcrow').length === 1`, 80), tag + 'the trip of 2024');
      check(await ev(`!document.querySelector('.rklist .rkrc') && /28\\.00|56\\.00|Per diem without amount|–/.test(document.querySelector('.rklist .rkpd')?.textContent || '')`), tag + '#2286: no receipts -> no receipts column, the per diem is the main amount ' + await ev(`document.querySelector('.rklist .ofcrow')?.textContent`));
      check(await ev(`!!document.querySelector('.rklist .rkpd b') && !/0\\.00/.test(document.querySelector('.rklist .ofcrow').textContent)`), tag + '#2286: no 0.00 in the row');
      check(await ev(noScroll), tag + 'no horizontal scrolling');
      await shot(`p21144-d-list-${u}-${w}.png`);
    }
  });
  // ---- #2286 with receipts (2025): two columns, a dash where a value is missing
  for (const [u, ck] of [['alice', CA], ['frida', CF]]) {
    await call(ck, 'POST', '/api/office/trips', {date_from: '2025-03-10', date_to: '2025-03-12', overnight: 1, dest: 'Berlin', people: [{name: 'Externe Person'}], items: [{date: '2025-03-10', category: 'train', amount: 100}]});
    await call(ck, 'POST', '/api/office/trips', {date_from: '2025-05-02', date_to: '2025-05-02', dest: 'Bonn', vma_off: 1});
  }
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    for (const [w, h] of [[1280, 900], [390, 844]]) for (const u of ['alice', 'frida']) {
      const tag = `${u} ${w}px: `;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await signIn(ev, u);
      await nav(B + '#office/travel');
      check(await ready(ev, `!!document.querySelector('#rk-year')`, 80), tag + 'the travel tab');
      await ev(`(() => { const s = document.querySelector('#rk-year'); s.value = '2025'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
      check(await ready(ev, `document.querySelectorAll('.rklist .ofcrow').length === 2`, 80), tag + 'the trips of 2025');
      check(await ev(`[...document.querySelectorAll('.rklist .ofcrow')].every(r => r.querySelector('.rkpd') && r.querySelector('.rkrc'))`), tag + '#2286: with receipts every row has both columns');
      check(await ev(`(() => { const b = [...document.querySelectorAll('.rklist .ofcrow')].find(r => /Berlin/.test(r.textContent)), n = [...document.querySelectorAll('.rklist .ofcrow')].find(r => /Bonn/.test(r.textContent)); return /100\\.00/.test(b.querySelector('.rkrc').textContent) && /–/.test(n.querySelector('.rkrc').textContent) && !/0\\.00/.test(n.textContent); })()`), tag + '#2286: a dash instead of 0.00 ' + await ev(`document.querySelector('.rklist')?.textContent`));
      check(await ev(noScroll), tag + 'no horizontal scrolling with two columns');
      await shot(`p21144-d-list2-${u}-${w}.png`);
    }
  });
  console.log(F.length ? `FAILED ${F.length}:\n` + F.join('\n') : `p21144_d_ui: ${ok} checks passed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
