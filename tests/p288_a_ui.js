// 2.88.0 UI tests, part A (#1915 quotations with versions in the cash flow), own container (start.sh). jsdom, invented data:
// - a sent quotation's editor shows "In the cash flow" (Automatic / Yes / No, outside the locked form) with the hint which
//   version counts; a tap saves it, one undo step takes it back
// - an older version names the version that counts instead
// - the cash flow: a sent quotation is marked as an open quotation (dashed entry, the month's share apart)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, allCss} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P288A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ym = (d, n) => { const x = new Date(d.getFullYear(), d.getMonth() + n, 1); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});  // no organisation: the personal office
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,office,clients'});
  const CL = (await call('POST', '/api/clients', {name: 'Kunde Eins GmbH'})).id;
  const M1 = ym(new Date(), 1);
  const q = await call('POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: CL, service_from: M1 + '-02', service_to: M1 + '-20'});
  await call('PUT', `/api/office/docs/${q.id}/items`, {items: [{kind: 'service', title: 'Dreh', qty: 1, unit: 'day', rate: 1000}]});
  await call('POST', `/api/office/docs/${q.id}/status`, {status: 'sent'});
  const q2 = await call('POST', `/api/office/docs/${q.id}/duplicate`);
  await call('POST', `/api/office/docs/${q2.id}/status`, {status: 'sent'});
  check(q2.version_of === q.id, 'setup: the copy is the second version');

  // ================= the editor of the newest version
  let w = await boot({hash: `office/offers/${q2.id}`}); let d = w.document;
  const box = await until(() => d.querySelector('.cf8sec'), 60);
  check(box && !box.closest('fieldset'), 'the switch sits outside the locked form of a sent quotation');
  check(box && box.querySelectorAll('[data-cf8]').length === 3 && box.querySelector('[data-cf8="auto"]')?.getAttribute('aria-pressed') === 'true', 'Automatic / Yes / No, Automatic chosen');
  check(/counts in the cash flow as an open quotation/.test(box?.querySelector('.cf8hint')?.textContent || ''), 'the hint: this version counts as an open quotation: ' + (box?.textContent || '').slice(0, 200));
  check(/Version 2 of 2/.test(box?.textContent || ''), 'the hint names the version');
  check([...(box?.querySelectorAll('[data-cf8]') || [])].every(b => b.tagName === 'BUTTON'), 'real buttons (keyboard, screen reader)');
  click(w, box.querySelector('[data-cf8="no"]'));
  check(await until(async () => (await call('GET', `/api/office/docs/${q2.id}`)).cashflow === 'no', 30), 'No is saved');
  check(await until(() => d.querySelector('.cf8sec [data-cf8="no"]')?.classList.contains('on') && /Counts instead/.test(d.querySelector('.cf8sec .cf8hint')?.textContent || ''), 30),
    'the editor shows the new choice and the version that counts instead: ' + (d.querySelector('.cf8sec')?.textContent || '').slice(0, 200));
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/office/docs/${q2.id}`)).cashflow === 'auto', 30), 'one undo step takes it back');
  w.close();

  // ================= the older version
  w = await boot({hash: `office/offers/${q.id}`}); d = w.document;
  const box1 = await until(() => d.querySelector('.cf8sec'), 60);
  check(box1 && new RegExp('Counts instead: ' + (q2.number || 'Draft')).test(box1.textContent), 'the older version names the one that counts: ' + (box1?.textContent || '').slice(0, 200));
  w.close();

  // ================= the cash flow plan
  w = await boot({hash: 'office/cashflow'}); d = w.document;
  await until(() => d.querySelectorAll('.rkcfms .rkcfm').length === 3, 80);
  const card = [...d.querySelectorAll('.rkcfms .rkcfm')][1];
  check(card && /open quotations/.test(card.querySelector('.rkcfopenl')?.textContent || ''), 'the month shows its share of open quotations: ' + (card?.textContent || '').slice(0, 200));
  const v = card?.querySelector('.rkcfv[data-k$="|in|plan"]');
  if (v) click(w, v);
  const li = await until(() => card && d.querySelector('.rkcfms .rkcfm:nth-child(2) .rkcfents li.rkcfopen'), 30);
  check(li && /Open quotation/.test(li.textContent) && /Imagefilm/.test(li.textContent), 'the entry is an open quotation: ' + (li?.textContent || '').slice(0, 160));
  check(d.querySelectorAll('.rkcfms .rkcfm:nth-child(2) .rkcfents li').length === 1, 'only one version of the chain is in the plan');
  const css = await allCss();
  check(/\.rkcfents \.rkcfopen \.ofcrow\{border-left:\.125rem dashed var\(--accent\)/.test(css), 'marked dashed in the accent colour (no new colour)');
  w.close();

  console.log(`p288_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
