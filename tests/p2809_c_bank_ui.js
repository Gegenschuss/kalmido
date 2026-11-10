// 2.809.0 C (#5452) UI test: the calmer bank row.
// kalmido-suite: fresh
// The suggestion with its button and ONE button "Other receipt / invoice", the marks (private, no receipt needed, ignore, cash box transfer) in a "More" menu with one line of explanation each, the
// hint for a missing receipt once above the list. Own container (start.sh, mode workspaces), Firefox desktop + phone width.
// Invented companies, people, accounts and figures only. tenant-matrix: office
// - wide: the row with money in shows the invoice as suggestion with "Assign"; every open row has exactly two buttons; the hint once
// - "More" opens a menu with the four marks, each explained (ignore and no receipt needed tell apart); "Private" -> the row is done
// - phone: one row of buttons (same line, 44 px), "More" opens as a sheet with a head
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2809_c_bank_ui', check, shots: 'P2809C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2809C_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const day = n => { const d = new Date(TC.today() + 'T12:00:00'); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const de = iso => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

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
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', vat_id: 'DE123456789', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Weg 2', zip: '10115', city: 'Berlin', country: 'DE'});
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: day(20), items: [{title: 'Schnitt', qty: 1, rate: 1000}]});
  const fin = await call(CA, 'POST', `/api/office/docs/${inv.id}/finalize`);
  check(fin.http === 200 && fin.number, 'a finalised invoice ' + fin.http);
  const csv = `Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n${de(day(3))};Kunde Eins GmbH;Rechnung ${fin.number};1.190,00\n${de(day(2))};Bäckerei Beispiel;Brötchen;-4,50\n${de(day(1))};Software Beispiel GmbH;Abo;-119,00\n`;
  const pv = await call(CA, 'POST', '/api/office/bank/import/preview', {text: csv});
  const mapping = {}; for (const k of ['date', 'amount', 'amount_in', 'amount_out', 'title', 'counterpart', 'decimal', 'date_format']) mapping[k] = pv.guess?.[k] ?? null;
  const imp = await call(CA, 'POST', '/api/office/bank/import', {text: csv, filename: 'konto.csv', mapping});
  check(imp.http === 201 && imp.count === 3, 'three bookings imported ' + imp.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const row = p => `[...document.querySelectorAll('.bnklist .bnkrow')].find(e => /${p}/.test(e.textContent))`;
  const click = sel => `(() => { const e = ${sel}; if (!e) return 0; e.click(); return 1; })()`;
  const vis = sel => `[...document.querySelectorAll('${sel}')].filter(e => e.getClientRects().length)`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#office/bank');
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 3`, 80), 'the bank tab lists three open bookings');
    // the row with money in: the invoice as suggestion with its button, beside it only "Other invoice…" and "More"
    check(await ready(ev, `!!${row('Kunde Eins')}?.querySelector('.bnksug [data-bnk="match"][data-kind="invoice"]') && new RegExp(${JSON.stringify(fin.number)}).test(${row('Kunde Eins')}.querySelector('.bnksug').textContent)`),
      'money in: the invoice is the suggestion with its button');
    const acts = await ev(`[...document.querySelectorAll('.bnklist .bnkrow')].map(r => [...r.querySelectorAll('.bnkacts button')].map(b => b.dataset.bnk).join(','))`);
    check(acts.length === 3 && acts.every(a => a === 'other,more'), 'every open row: exactly "Other …" and "More" ' + JSON.stringify(acts));
    check(await ev(`/Other invoice/.test(${row('Kunde Eins')}.querySelector('[data-bnk="other"]').textContent) && /Other receipt/.test(${row('Bäckerei')}.querySelector('[data-bnk="other"]').textContent)`),
      '"Other invoice…" for money in, "Other receipt…" for money out');
    check(await ev(`!document.querySelector('.bnklist [data-kind="private"], .bnklist [data-kind="ignored"], .bnklist [data-kind="noreceipt"], .bnklist [data-kind="cash"]')`),
      'no mark buttons in the rows any more');
    check(await ev(`${vis('.bnkmiss1')}.length === 1 && !document.querySelector('.bnklist .bnkmiss') && /Receipt missing\\?/.test(document.querySelector('.bnkmiss1').textContent)`),
      'the hint "Receipt missing?" once above the list, not in the rows');
    check(await ev(`document.querySelector('.bnkmiss1').getBoundingClientRect().bottom <= document.querySelector('.bnklist').getBoundingClientRect().top + 1`), 'the hint stands above the list');
    await shot('p2809-c-bank-wide.png');
    // "More" -> the four marks with their explanation
    await ev(click(`${row('Bäckerei')}?.querySelector('[data-bnk="more"]')`));
    check(await ready(ev, `!!document.querySelector('#pop:not(.hidden) [data-act="bnk-private"]')`), '"More" opens the menu');
    const items = await ev(`[...document.querySelectorAll('#pop [role="menuitem"]')].map(b => [b.dataset.act, b.querySelector('.ml')?.firstChild?.textContent || '', b.querySelector('.msub')?.textContent || ''])`);
    check(items.map(x => x[0]).join(',') === 'bnk-private,bnk-noreceipt,bnk-ignored,bnk-cash', 'the four marks in the menu ' + JSON.stringify(items));
    check(items.every(x => x[2].length > 20), 'each mark has a line of explanation');
    const sub = k => (items.find(x => x[0] === k) || [])[2] || '';
    check(/counts in the books/.test(sub('bnk-noreceipt')) && /Left out of the books/.test(sub('bnk-ignored')) && sub('bnk-noreceipt') !== sub('bnk-ignored'),
      '"No receipt needed" (counts) and "Ignore" (left out) are told apart');
    check(await ev(`document.querySelector('#pop').getBoundingClientRect().right <= innerWidth + 1`), 'the menu stays on the screen');
    await shot('p2809-c-bank-menu-wide.png');
    await ev(click(`document.querySelector('#pop [data-act="bnk-private"]')`));
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 2 && !${row('Bäckerei')}`), '"Private": the booking leaves the open list');
    await ev(click(`document.querySelector('[data-bnk="state"][data-v="matched"]')`));
    check(await ready(ev, `/Private/.test(${row('Bäckerei')}?.querySelector('.bnkm')?.textContent || '')`), '"Matched" shows it as private');
    await ev(click(`document.querySelector('[data-bnk="state"][data-v="open"]')`));
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 2`), 'back to the open ones');
    // the suggestion's button still assigns (#5383 uses the same rows)
    await ev(click(`${row('Kunde Eins')}?.querySelector('.bnksug [data-bnk="match"]')`));
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 1 && !${row('Kunde Eins')}`), 'the suggestion\'s button assigns the invoice');

    // ---- phone width: one row of buttons, the menu as a sheet
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ready(ev, `${vis('.bnklist .bnkrow .bnkacts button')}.length === 2`), 'phone: the row with its two buttons');
    check(await ev(`(() => { const b = ${vis('.bnklist .bnkrow .bnkacts button')}.map(x => x.getBoundingClientRect()); return b.length === 2 && Math.abs(b[0].top - b[1].top) < 2 && b.every(x => x.height >= 43.5); })()`),
      'phone: the buttons stand in one row, 44 px high');
    check(await ev(`(() => { const W = document.documentElement.clientWidth; return ${vis('.bnklist *')}.every(e => e.getBoundingClientRect().right <= W + 1); })()`), 'phone: nothing sticks out to the side');
    await shot('p2809-c-bank-phone.png');
    await ev(click(`${row('Software')}?.querySelector('[data-bnk="more"]')`));
    check(await ready(ev, `!!document.querySelector('#pop.sheet:not(.hidden) [data-act="bnk-noreceipt"]') && /Mark booking/.test(document.querySelector('#pop .tch-sht')?.textContent || '')`),
      'phone: "More" opens a sheet with its head');
    check(await ready(ev, `(() => { const p = document.querySelector('#pop.sheet'), r = p?.getBoundingClientRect(); return !!r && r.top < innerHeight - 150 && r.bottom <= innerHeight + 1 && document.getAnimations().every(a => a.playState !== 'running' || !p.contains(a.effect?.target)) && +getComputedStyle(p).opacity === 1; })()`),
      'phone: the sheet stands on the screen ' + JSON.stringify(await ev(`(() => { const p = document.querySelector('#pop'); const r = p.getBoundingClientRect(); return [r.top, r.bottom, innerHeight, getComputedStyle(p).opacity, getComputedStyle(p).transform]; })()`)));
    await shot('p2809-c-bank-menu-phone.png');
    await ev(click(`document.querySelector('#pop [data-act="bnk-noreceipt"]')`));
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 0`), 'phone: "No receipt needed" from the sheet marks the last one');
  }, false);

  console.log(`p2809_c_bank_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
