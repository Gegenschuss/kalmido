// 2.1004.0 A (#5572) Polish office: the list pages of a phone have ONE navigation line above their content. Own container
// kalmido-suite: fresh
// (start.sh), Firefox. Invented data only.
// - #5572 (phone 360 x 740, touch): Quotations and Invoices show above the list only the office menu row: the way back is an
//   arrow before the tabs (its words "Office · Sell" stay its name), the document kinds (Credit notes, Payment reminders,
//   Archive ...) follow their point in the same row, no line for company / role with one office, no second row of kind tabs.
//   The list's content (a made quotation / invoice) is in sight; a tap on a tab of the row switches (Invoices, Payment
//   reminders and back to Invoices); the arrow leads back to the office's start list. A person without an organisation (frida).
// - a computer keeps its kind tabs above the list and the company / role line; no office menu row in the page.
// Screenshots into $P21004A_SHOTS.
// freelancer-matrix: office (frida has no organisation)
// usage: node p21004_a_office_nav_mobile.js <datadir>
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21004_a_nav', check, shots: 'P21004A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Beispiel Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  check((await call('POST', '/api/users', {username: 'frida', display_name: 'frida', password: 'password123', email: 'frida@example.com', orgs: []})).http < 300, 'user frida');
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FK);
  await call('PUT', '/api/office/settings', {pack: 'DE', company_fields: {name: 'Studio Beispiel', street: 'Hafenstrasse 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}}, FK);
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE'}, FK)).id;
  const Q = (await call('POST', '/api/office/docs', {client_id: CL, project_title: 'Imagefilm'}, FK)).id;
  await call('PUT', `/api/office/docs/${Q}/items`, {items: [{kind: 'service', title: 'Kamera', qty: 2, unit: 'day', rate: 800}]}, FK);
  const INV = (await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL, project_title: 'Schnittfassung', service_from: '2026-10-01', items: [{title: 'Schnitt', qty: 1, rate: 100}]}, FK)).id;
  check(!!Q && !!INV && (await call('POST', `/api/office/docs/${INV}/finalize`, {}, FK)).http === 200, 'a quotation and a finalised invoice');

  const signIn = (ev, user) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  const shown = sel => `[...document.querySelectorAll(${JSON.stringify(sel)})].some(e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && getComputedStyle(e).visibility !== 'hidden'; })`;
  // the navigation above the list: every visible line of the menu row, the path, the company / role line and the kind tabs that
  // stands between the top bar and the first row of the list (lines = distinct vertical bands)
  const navLines = `(() => {
    const row = document.querySelector('#view .ofdlist .ofdrow'); if (!row) return null; const rt = row.getBoundingClientRect().top;
    const vis = e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && b.bottom <= rt + 1 && getComputedStyle(e).visibility !== 'hidden'; };
    const parts = [...document.querySelectorAll('#view .ofpb .ofpback, #view .ofpb .ofpt2, #view .ofmcrumb, #view .ofchead > *, #view .ofdkinds button')].filter(vis);
    const bands = []; for (const e of parts) { const b = e.getBoundingClientRect(), m = (b.top + b.bottom) / 2; if (!bands.some(x => Math.abs(x - m) < 10)) bands.push(m); }
    return {lines: bands.length, what: parts.map(e => e.className.split(' ')[0] + ':' + e.textContent.trim().slice(0, 20)), rowTop: Math.round(rt)};
  })()`;
  const center = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; e.scrollIntoView({block: 'nearest', inline: 'center'}); const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2, seen: b.left >= 0 && b.right <= innerWidth}; })()`;

  // ================= #5572: a phone, 360 x 740, a finger
  await firefox(async ({cmd, ev, ctx, nav, shot, until, drag}) => {
    const tap = async (sel, what) => { const c = await until(center(sel)); check(c && c.seen, what + ': in sight ' + JSON.stringify(c)); if (c) await drag(c.x, c.y, 0, 0, 'touch'); };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'frida') === 200, 'phone: frida signed in');
    await nav(B + '#office/offers');
    check(await until(`(() => { const r = document.querySelector('#view .ofdlist .ofdrow[data-id="${Q}"]'); if (!r) return false; const b = r.getBoundingClientRect(); return b.top >= 0 && b.bottom <= innerHeight && /Beispielkunde AG/.test(r.textContent); })()`, {timeout: 20000}), '#5572 phone: the quotation is in sight in the list');
    const n1 = await until(navLines);
    check(n1 && n1.lines === 1, '#5572 phone: Quotations: ONE navigation line above the list ' + JSON.stringify(n1));
    check(await ev(`!${shown('#view .ofchead > *')} && !${shown('#view .ofdkinds')}`), '#5572 phone: no company / role line with one office, no second row of kind tabs');
    check(await ev(`(() => { const b = document.querySelector('#view .ofpb .ofpback'); return /Back to Office · Sell/.test(b.getAttribute('aria-label') || '') && b.getBoundingClientRect().height >= 43 && b.getBoundingClientRect().width >= 43; })()`), '#5572 phone: the way back is a large arrow named "Back to Office · Sell"');
    check(await ev(`!!document.querySelector('#view .ofpb .ofpk[data-ofk="archive"]') && document.querySelector('#view .ofpb [data-ofm="offers"]').classList.contains('on')`), '#5572 phone: the quotations\' kind Archive follows its point in the row, Quotations is marked');
    check(await ev('document.documentElement.scrollWidth <= innerWidth'), '#5572 phone: nothing wider than the screen');
    await shot('p21004a-handy-angebote.png');

    // a tab of the row: Invoices
    await tap('#view .ofpb [data-ofm="invoices"]', 'phone: the tab Invoices');
    check(await until(`/^#office\\/invoices/.test(location.hash) && !!document.querySelector('#view .ofdlist .ofdrow[data-id="${INV}"]')`, {timeout: 20000}), '#5572 phone: the tab Invoices shows the invoice ' + await ev('location.hash'));
    const n2 = await until(navLines);
    check(n2 && n2.lines === 1, '#5572 phone: Invoices: ONE navigation line above the list ' + JSON.stringify(n2));
    check(await ev(`['credit', 'reminder', 'archive'].every(k => !!document.querySelector('#view .ofpb .ofpk[data-ofk="' + k + '"]'))`), '#5572 phone: the kinds of the invoices are in the same row');
    await shot('p21004a-handy-rechnungen.png');
    // a kind in the row: Payment reminders, then back to Invoices
    await tap('#view .ofpb .ofpk[data-ofk="reminder"]', 'phone: the kind Payment reminders');
    check(await until(`location.hash === '#office/invoices/reminder' && /No payment reminders yet/.test(document.querySelector('#view .ofcbody')?.textContent || '') && document.querySelector('#view .ofpb .ofpk[data-ofk="reminder"]')?.classList.contains('on')`, {timeout: 20000}), '#5572 phone: Payment reminders open, marked in the row ' + await ev('location.hash'));
    check(await ev(`(() => { const b = document.querySelector('#view .ofpb [data-ofm="invoices"]'); return b.classList.contains('ofpsub') && getComputedStyle(b).borderBottomColor !== getComputedStyle(document.querySelector('#view .ofpb .ofpk.on')).borderBottomColor; })()`), '#5572 phone: only the kind is underlined, not its point as well');
    await shot('p21004a-handy-mahnungen.png');
    await tap('#view .ofpb [data-ofm="invoices"]', 'phone: the tab Invoices again');
    check(await until(`/^#office\\/invoices(\\/invoice)?$/.test(location.hash) && !!document.querySelector('#view .ofdlist .ofdrow[data-id="${INV}"]') && !document.querySelector('#view .ofpb .ofpk.on')`, {timeout: 20000}), '#5572 phone: the tab Invoices leads back from the reminders to the invoices ' + await ev('location.hash'));
    // the arrow: back to the office's start list
    await tap('#view .ofpb .ofpback', 'phone: the arrow back');
    check(await until(`location.hash === '#office/start' && document.querySelectorAll('#view .oflg').length > 0`, {timeout: 20000}), '#5572 phone: the arrow leads back to the office\'s start list ' + await ev('location.hash'));
  }, true);

  // ================= a computer: kind tabs and the company / role line stay
  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'frida') === 200, 'desktop: frida signed in');
    await nav(B + '#office/invoices');
    check(await until(`!!document.querySelector('#view .ofdlist .ofdrow[data-id="${INV}"]')`, {timeout: 20000}), 'desktop: the invoice list');
    check(await ev(`${shown('#view .ofdkinds [data-kind="reminder"]')} && !document.querySelector('#view .ofpb') && !document.querySelector('#view .ofpk')`), '#5572 desktop: the kind tabs stay above the list, no menu row in the page');
    check(await ev(`/Admin/.test(document.querySelector('#view .ofchead .ofcorg')?.textContent || '')`), '#5572 desktop: the company / role line stays');
    await shot('p21004a-desktop-rechnungen.png');
  });

  console.log(`p21004_a_office_nav_mobile: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
