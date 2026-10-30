// kalmido-suite: fresh
// 2.435.0 part B UI tests (jsdom), fresh DB:
// - #3618 the row menu of the document list: a finalised invoice offers Preview, Download PDF, Send by mail… in that order;
//   a draft offers Download PDF (it asks first) but no sending; sending opens the send dialog
// - #3578 the app shell is recognised (window.__KALMIDO_SHELL__ or "KalmidoApp/" in the user agent): Account settings offer
//   "Change server", no install hint, no Web Push offer in the iPhone shell; a plain browser shows none of that
// Invented companies only.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const UA_IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 KalmidoApp/1.0';
const UA_AND = 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36 KalmidoApp/1.0';
const ua = v => w => Object.defineProperty(w.navigator, 'userAgent', {configurable: true, value: v});

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  await call('PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Studio Nordlicht GmbH', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE', email: 'kunde@example.com'})).id;
  const inv = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL, service_from: '2026-10-01', items: [{title: 'Schnitt', qty: 1, rate: 100}]});
  check((await call('POST', `/api/office/docs/${inv.id}/finalize`)).http === 200, 'an invoice finalised');
  const dr = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL, service_from: '2026-10-01', items: [{title: 'Entwurf', qty: 1, rate: 50}]});

  // ================= #3618 the row menu
  let w = await boot({hash: 'office/invoices'});
  await until(() => w.eval('typeof ofdMoreItems') === 'function');
  const labels = id => w.eval(`api('GET', '/api/office/docs/${id}').then(d => ofdMoreItems({id: d.id, kind: d.kind, number: d.number, status: d.status, locked: d.locked, can_edit: d.can_edit}, true).filter(Boolean).map(x => x.label || x))`);
  const lf = await labels(inv.id), ld = await labels(dr.id);
  const iP = lf.indexOf('Preview (PDF)'), iD = lf.indexOf('Download PDF'), iS = lf.indexOf('Send by mail…');
  check(iP >= 0 && iD === iP + 1 && iS === iD + 1, 'finalised invoice: Preview, Download PDF, Send by mail… in this order: ' + lf.join(' | '));
  check(ld.includes('Download PDF') && !ld.includes('Send by mail…'), 'draft: Download PDF, no sending: ' + ld.join(' | '));
  await w.eval(`api('GET', '/api/office/docs/${inv.id}').then(d => ofdMoreItems({id: d.id, kind: d.kind, number: d.number, status: d.status, locked: d.locked}, true).find(x => x && x.label === 'Send by mail…').fn())`);
  check(await until(() => w.document.querySelector('#ofd-s-to')), 'sending opens the send dialog');
  w.close();

  // ================= #3578 the app shell
  const acct = async (opts) => { const x = await boot({hash: 'o', ...opts}); await sleep(300); const h = x.eval('accountHtml()'); const r = {change: /data-acc="shell-server"/.test(h), sa: x.eval('isStandalone()'), url: x.eval('shellServerUrl()')}; x.close(); return r; };
  const plain = await acct({});
  check(!plain.change && !plain.sa && plain.url === '', 'plain browser: no "Change server", not standalone');
  const desk = await acct({setup: w => { w.__KALMIDO_SHELL__ = {kind: 'desktop', os: 'linux', version: '1.0.0', changeServer: 'kalmido-shell://servers'}; }});
  check(desk.change && desk.sa && desk.url === 'kalmido-shell://servers', 'desktop shell: Change server, standalone, its own address: ' + JSON.stringify(desk));
  const deskBad = await acct({setup: w => { w.__KALMIDO_SHELL__ = {kind: 'desktop', changeServer: {x: 1}}; }});
  check(!deskBad.change && deskBad.sa, 'desktop shell with a changeServer that is no string: no entry');
  const ios = await acct({setup: ua(UA_IOS)});
  check(ios.change && ios.sa && ios.url === 'capacitor://localhost/?change=1', 'iOS shell: ' + JSON.stringify(ios));
  const and = await acct({setup: ua(UA_AND)});
  check(and.change && and.url === 'https://localhost/?change=1', 'Android shell: ' + JSON.stringify(and));

  // no install hint in the shell; the iPhone shell has no Web Push offer
  const wi = await boot({hash: 'o', setup: ua(UA_IOS)});
  await sleep(300);
  wi.eval('PWA.shown = false; PWA.ev = null; pwa_hint()');
  check(!wi.document.querySelector('#pwahint') && wi.eval('pwa_ok()') === false, 'iPhone shell: no install hint');
  check(wi.eval('shellIOS()') === true, 'iPhone shell recognised for Web Push');
  wi.close();
  const wa = await boot({hash: 'o', setup: ua(UA_AND)});
  check(wa.eval('shellIOS()') === false && wa.eval('pwa_ok()') === false, 'Android shell: no install hint, Web Push not hidden');
  wa.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2435_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack); process.exit(1); });
