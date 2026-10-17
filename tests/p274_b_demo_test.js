// 2.74.0 (#1653): Office & finance in the browser demo. Builds the demo (tools/build_demo.py) into tests/.demo-office, serves
// it from a local static server and opens it in jsdom (no container, no API): a new account switches the office on ("What
// do you use Kalmido for?" = Office & finance), creates a client, a service, a quotation with two positions (standard and
// reduced VAT), turns it into an invoice, finalises it and books two payments until it is paid; the sums and the VAT are the
// server's (kalmido/office/calc.py: money(qty x rate), tax per rate on the rounded sum, half up). The PDF opens as the
// print view (overlay, no network), the office's server-only parts answer calmly, a reload keeps the documents, "Reset
// demo" empties the office; nothing leaves the page (no fetch / XHR / WebSocket / sendBeacon of the browser, no CSP report,
// every API call answered by the shim).
// usage: node p274_b_demo_test.js          (needs python3 + jsdom)
const {JSDOM, VirtualConsole} = require('jsdom');
const http = require('http'), fs = require('fs'), path = require('path'), {execFileSync} = require('child_process');
const ROOT = path.join(__dirname, '..'), OUT = path.join(__dirname, '.demo-office');
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ok = 0; const fails = [];
const check = (c, what) => { if (c) ok++; else { fails.push(what); console.log('FAIL:', what); } };

const build = execFileSync(process.env.PYTHON || 'python3', [path.join(ROOT, 'tools', 'build_demo.py'), OUT], {encoding: 'utf-8'});
check(/build_demo: /.test(build), 'demo build: ' + build.trim());
const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2'};
const hits = [];
const srv = http.createServer((req, res) => {
  const u = decodeURIComponent(req.url.split('?')[0]); hits.push(req.method + ' ' + u);
  const p = path.join(OUT, u.replace(/^\/demo\//, '/').replace(/\/$/, '/index.html'));
  if (!u.startsWith('/demo/') || !p.startsWith(OUT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, {'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream'}); fs.createReadStream(p).pipe(res);
});

(async () => {
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const B = `http://127.0.0.1:${srv.address().port}/demo/`;
  const store = {}, errs = [];
  const open = async (lang = 'de-DE', wait = 2500) => {
    const vc = new VirtualConsole();
    vc.on('jsdomError', e => { if (!/navigation|Not implemented|Could not load (img|link)/.test(e.message)) errs.push(e.message); });
    vc.on('error', e => errs.push(String(e && e.stack || e)));
    const dom = await JSDOM.fromURL(B, {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
      beforeParse(w) {
        w.matchMedia = q => ({matches: false, addEventListener() {}, addListener() {}});
        Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; },
          key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
        Object.defineProperty(w.navigator, 'languages', {configurable: true, value: [lang]});
        Object.defineProperty(w.navigator, 'language', {configurable: true, value: lang});
        w.__net = 0;
        w.fetch = () => { w.__net++; return Promise.reject(new TypeError('network')); };
        w.XMLHttpRequest = function () { w.__net++; throw new Error('XHR in the demo'); };
        w.WebSocket = function () { w.__net++; throw new Error('WebSocket in the demo'); };
        w.EventSource = function () { w.__net++; throw new Error('EventSource in the demo'); };
        w.navigator.sendBeacon = () => { w.__net++; return false; };
        w.__prints = 0; w.print = () => { w.__prints++; };
        w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
        w.confirm = () => true; w.prompt = () => null;
      }});
    await sleep(wait);
    return dom.window;
  };
  const J = async (w, expr) => JSON.parse(await w.eval(`(async () => JSON.stringify(await (${expr})))()`));
  const year = String(new Date().getFullYear());

  let w = await open('de-DE'), d = w.document;
  w.eval('tourEnd(true)'); await sleep(200);
  // 1. a new account has no office; "Office & finance" as the purpose switches it on (with the clients)
  check(!w.eval(`feat('office')`), 'new account: office off');
  const pu = await J(w, `api('POST', '/api/me/purpose', {purpose: 'office'})`);
  await w.eval('load().then(render)'); await sleep(300);
  check(w.eval(`feat('office') && feat('clients')`) && !/files|contacts|events/.test(pu.features), 'purpose office: office + clients on, server-only modules stay off: ' + pu.features);
  w.eval(`go('office')`); await sleep(1500);
  const v0 = d.querySelector('#view')?.textContent || '';
  check(/Angebote/.test(v0) && /Neues Angebot/.test(v0), 'office view: quotations tab with "Neues Angebot": ' + v0.slice(0, 160));
  // 2. client (module clients), service with a day rate
  const cl = await J(w, `rawFetch('POST', '/api/clients', {name: 'Beispiel GmbH', street: 'Hauptstraße 5', zip: '20095', city: 'Hamburg', payment_terms_days: 10, contacts: [{name: 'Erika Beispiel', is_default: true}]})`);
  await w.eval('load()');
  check(cl.id && w.eval(`S.clients.some(c => c.name === 'Beispiel GmbH' && c.org_id === null)`), 'client created, in S.clients (private office)');
  const sv = await J(w, `api('POST', '/api/office/services', {name_de: 'Konzept', name_en: 'Concept', unit: 'day', daily_rate: 800, hourly_rate: 100, tax: 'standard', intext: 'extern'})`);
  const svl = await J(w, `api('GET', '/api/office/services?archived=1')`);
  check(sv.id && svl.items.length === 1 && svl.items[0].daily_rate === 800, 'service with a day rate');
  // 3. a new quotation through the button, then client + positions
  w.eval(`ofdDraw()`); await sleep(300);
  d.querySelector('[data-ofd="new"]')?.click(); await sleep(1200);
  const oid = w.eval('S.route.id');
  const of0 = await J(w, `api('GET', '/api/office/docs/${oid}')`);
  check(of0.kind === 'offer' && of0.number === `KVA-${year}-001` && of0.status === 'draft' && of0.can_edit, 'button "Neues Angebot": draft with number ' + of0.number);
  await J(w, `api('PATCH', '/api/office/docs/${oid}', {client_id: ${cl.id}, recipient_from_client: true, project_title: 'Website'})`);
  const of1 = await J(w, `api('PUT', '/api/office/docs/${oid}/items', {items: [{kind: 'service', service_id: ${sv.id}, qty: 2.5, unit: 'day'}, {kind: 'service', title: 'Fachbuch', qty: 3, unit: 'piece', rate: 19.99, tax: 'reduced'}]})`);
  const t = of1.totals;
  check(of1.recipient.name === 'Beispiel GmbH' && of1.recipient.lines.includes('Hauptstraße 5') && of1.recipient.lines.includes('20095 Hamburg'), 'recipient from the client: ' + JSON.stringify(of1.recipient));
  check(of1.items[0].title === 'Konzept' && of1.items[0].rate === 800, 'position filled from the service (title, day rate)');
  // server: 2.5 x 800 = 2000.00 (19 %: 380.00), 3 x 19.99 = 59.97 (7 %: 4.1979 -> 4.20); net 2059.97, gross 2444.17
  check(t.net === 2059.97 && t.gross === 2444.17 && t.tax_lines.length === 2 && t.tax_lines[0].amount === 380 && t.tax_lines[1].amount === 4.2 && t.tax_lines[0].label === 'MwSt. 19 %',
    'quotation sums like the server: ' + JSON.stringify({net: t.net, gross: t.gross, tax: t.tax_lines.map(x => [x.label, x.amount])}));
  check(t.lines[0].total === 2000 && t.lines[1].total === 59.97 && /Alle Preise zuzüglich/.test(t.vat_note), 'quotation lines + VAT note');
  w.eval(`ofdLoadDoc(${oid}, true)`); await sleep(500);
  const ed = d.querySelector('#view')?.textContent || '';
  check(/2\.444,17 €/.test(ed) && /KVA-/.test(ed), 'editor shows the gross total 2.444,17 €');
  // discount 10 % on the quotation: one negative line, the tax on the reduced bases (server rule)
  const od = await J(w, `api('PATCH', '/api/office/docs/${oid}', {discount_pct: 10})`);
  check(od.totals.discount === 206 && od.totals.net === 1853.97 && od.totals.gross === 2199.75, 'discount 10 %: ' + JSON.stringify([od.totals.discount, od.totals.net, od.totals.gross]));
  await J(w, `api('PATCH', '/api/office/docs/${oid}', {discount_pct: 0})`);
  const st = await J(w, `api('POST', '/api/office/docs/${oid}/status', {status: 'accepted'})`);
  check(st.status === 'accepted' && st.can_edit, 'quotation accepted');
  // 4. invoice from the quotation
  const inv = await J(w, `rawFetch('POST', '/api/office/docs/${oid}/invoice')`);
  check(inv.kind === 'invoice' && inv.number === '' && inv.status === 'draft' && inv.source_doc_id === oid && inv.client_id === cl.id && inv.payment_days === 10, 'invoice draft from the quotation (client payment terms 10 days)');
  check(inv.totals.net === '2059.97' && inv.totals.gross === '2444.17' && inv.totals.tax_lines[1].amount === '4.20' && inv.totals.gross_text === '2.444,17 €', 'invoice sums as exact strings: ' + JSON.stringify([inv.totals.net, inv.totals.gross]));
  const early = await w.eval(`rawFetch('POST', '/api/office/docs/${inv.id}/payments', {date: '${year}-01-01', amount: 10, method: 'transfer'}).then(() => 'ok', e => String(e.status || e.message))`);
  check(early !== 'ok', 'no payment before finalising: ' + early);
  const fin = await J(w, `api('POST', '/api/office/docs/${inv.id}/finalize', {})`);
  check(fin.locked && fin.status === 'issued' && fin.number === `RE-${year}-001` && fin.due_date && !fin.can_edit, 'finalised: ' + fin.number + ' due ' + fin.due_date);
  const lockErr = await w.eval(`rawFetch('PATCH', '/api/office/docs/${inv.id}', {project_title: 'x'}).then(() => 'ok', e => String(e.status))`);
  check(lockErr === '409', 'finalised invoice cannot be changed (409)');
  // 5. payments: part, then the rest -> paid
  const today = w.eval(`(() => { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); })()`);
  const p1 = await J(w, `api('POST', '/api/office/docs/${inv.id}/payments', {date: '${today}', amount: 1000, method: 'transfer', note: ''})`);
  check(p1.state === 'partial' && p1.paid === '1000.00' && p1.open === '1444.17', 'part payment: partly paid, open 1444.17: ' + JSON.stringify([p1.state, p1.paid, p1.open]));
  const over = await w.eval(`rawFetch('POST', '/api/office/docs/${inv.id}/payments', {date: '${today}', amount: 5000}).then(() => 'ok', e => String(e.status))`);
  check(over === '400', 'payment above the open amount refused');
  const p2 = await J(w, `api('POST', '/api/office/docs/${inv.id}/payments', {date: '${today}', amount: 1444.17, method: 'cash'})`);
  check(p2.status === 'paid' && p2.state === 'paid' && p2.open === '0.00' && p2.payments.length === 2 && p2.paid_at, 'second payment: paid, open 0.00');
  const lst = await J(w, `api('GET', '/api/office/docs?kind=invoice')`);
  check(lst.docs.length === 1 && lst.docs[0].state === 'paid' && lst.docs[0].gross_text === '2.444,17 €', 'invoice list: paid');
  // 6. the print view instead of the PDF: the PDF link of the editor, the download link, KDEMO.printView
  w.eval(`go('office/offers/${inv.id}')`); await sleep(300); w.eval(`ofdLoadDoc(${inv.id}, true)`); await sleep(600);
  const pdfA = d.querySelector('a.ofdpdf');
  check(!!pdfA && /\/api\/office\/docs\/\d+\/pdf/.test(pdfA.getAttribute('href')), 'editor has the PDF link');
  pdfA?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0})); await sleep(300);
  let pv = d.querySelector('#kd-print');
  const pt = pv?.textContent || '';
  check(!!pv && /Rechnung RE-/.test(pt) && /2\.444,17 €/.test(pt) && /MwSt\. 19 %/.test(pt) && /MwSt\. 7 %/.test(pt) && /Beispiel GmbH/.test(pt) && /Bezahlt/.test(pt) && /Druckansicht/.test(pt), 'PDF link opens the print view: ' + pt.slice(0, 200));
  check(!d.querySelector('.lightbox'), 'no PDF viewer (pdf.js) opened');
  pv?.querySelector('[data-kp="print"]')?.click();
  check(w.__prints === 1, 'print button calls window.print()');
  pv?.querySelector('[data-kp="close"]')?.click(); await sleep(100);
  check(!d.querySelector('#kd-print'), 'print view closes');
  d.querySelector('a.ofddl')?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0})); await sleep(200);
  check(!!d.querySelector('#kd-print') && !d.querySelector('#kd-note'), 'download link: print view too, no notice');
  d.querySelector('#kd-print [data-kp="close"]')?.click();
  w.eval(`window.open('/api/office/docs/${oid}/pdf?inline=1', '_blank')`); await sleep(100);
  check(/Angebot KVA-/.test(d.querySelector('#kd-print')?.textContent || ''), 'window.open of a PDF: the quotation in the print view');
  d.querySelector('#kd-print [data-kp="close"]')?.click();
  // 7. the server-only parts of the office: a calm answer, no notice while browsing; a write (DATEV) gets the notice
  const kpi = await w.eval(`rawFetch('GET', '/api/office/kpi').then(() => 'ok', e => e.status + ' ' + e.message)`);
  check(/^409 /.test(kpi) && /nicht verfügbar/.test(kpi) && !d.querySelector('#kd-note'), 'office KPI: "not available" without the notice: ' + kpi);
  await w.eval(`rawFetch('POST', '/api/office/docs/${inv.id}/datev', {}).catch(() => 0)`); await sleep(100);
  check(!!d.querySelector('#kd-note'), 'DATEV: the notice with the install link');
  d.querySelector('#kd-note button')?.click();
  // the office tabs render without errors
  for (const tab of ['services', 'settings', 'kpi']) { w.eval(`go('office/${tab}')`); await sleep(700); check((d.querySelector('#view')?.innerHTML || '').length > 100, `office tab ${tab} renders`); }
  w.eval(`go('clients')`); await sleep(800);
  check(/Beispiel GmbH/.test(d.querySelector('#view')?.textContent || ''), 'clients view lists the client');
  w.eval(`go('client/${cl.id}')`); await sleep(1000);
  check(/Beispiel GmbH/.test(d.querySelector('#view')?.textContent || ''), 'client page opens');
  check(w.__net === 0, `no fetch / XHR / WebSocket / EventSource / sendBeacon of the browser (${w.__net})`);
  check(!w.KDEMO.miss.length, 'every API call answered by the shim: ' + JSON.stringify(w.KDEMO.miss.slice(0, 6)));
  check(!w.KDEMO.csp.length, 'nothing blocked by the CSP');
  w.close();

  // 8. reload: the documents are still there; reset: the office is empty again (a new account)
  w = await open('de-DE'); d = w.document;
  const again = await J(w, `api('GET', '/api/office/docs?kind=invoice')`);
  check(again.docs.length === 1 && again.docs[0].state === 'paid', 'after reload: the paid invoice is still there');
  w.KDEMO.reset(); await sleep(300); w.close();
  w = await open('de-DE');
  check(!w.eval(`feat('office')`) && !w.KDEMO.db().office && !(w.KDEMO.db().clients || []).length, 'reset: office off and empty');
  w.close();
  // 9. an English office document: English words and number format in the print view
  for (const k of Object.keys(store)) delete store[k];
  w = await open('en-GB'); d = w.document;
  w.eval('tourEnd(true)');
  await w.eval(`api('POST', '/api/me/purpose', {purpose: 'office'}).then(load)`);
  const en = await J(w, `api('POST', '/api/office/docs', {}).then(x => api('PATCH', '/api/office/docs/' + x.id, {lang: 'en', recipient: {name: 'Example Ltd', lines: ['Example Ltd', '1 High Street', 'London']}}))
    .then(x => api('PUT', '/api/office/docs/' + x.id + '/items', {items: [{kind: 'service', title: 'Workshop', qty: 1, unit: 'flat', rate: 1234.5}]}))`);
  check(en.totals.gross === 1469.06 && en.totals.tax_lines[0].label === 'VAT 19 %', 'English quotation: 1234.50 + 19 % = 1469.06');
  w.KDEMO.printView(en.id); await sleep(100);
  const ept = d.querySelector('#kd-print')?.textContent || '';
  check(/Quotation KVA-/.test(ept) && /€1,469\.06/.test(ept) && /Print view/.test(ept), 'English print view: ' + ept.slice(0, 120));
  w.close();

  // 10. real layout in Firefox (skipped without firefox): phone 390 px (touch) and desktop 1280 px; the invoice editor and the
  // print view fit without horizontal scrolling of the page, the print page has no overflow, the CSP blocks nothing.
  // P274B_SHOTS=<dir> saves screenshots.
  const firefox = require('./ff')({tag: 'p274b', check, shots: 'P274B_SHOTS'});
  for (const [vw, vh, touch] of [[390, 844, true], [1280, 800, false]]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B); await ev(`(() => { localStorage.clear(); return 1; })()`); await nav(B); await sleep(2500);
      const id = await ev(`(async () => { tourEnd(true); await api('POST', '/api/me/purpose', {purpose: 'office'}); await load();
        const c = await api('POST', '/api/clients', {name: 'Beispiel GmbH', street: 'Hauptstraße 5', zip: '20095', city: 'Hamburg'}); await load();
        const o = await api('POST', '/api/office/docs', {}); await api('PATCH', '/api/office/docs/' + o.id, {client_id: c.id, recipient_from_client: true, project_title: 'Website-Relaunch mit Buchungssystem'});
        await api('PUT', '/api/office/docs/' + o.id + '/items', {items: [{kind: 'service', title: 'Konzept und Workshop mit dem Team vor Ort', detail: 'zwei Tage inklusive Protokoll', qty: 2.5, unit: 'day', rate: 800},
          {kind: 'service', title: 'Fachbuch', qty: 3, unit: 'piece', rate: 19.99, tax: 'reduced'}]});
        const i = await api('POST', '/api/office/docs/' + o.id + '/invoice'); await api('POST', '/api/office/docs/' + i.id + '/finalize', {});
        location.hash = 'office/offers/' + i.id; return String(i.id); })()`);
      await sleep(1500);
      const tag = `Firefox ${vw}px`;
      const e = JSON.parse(await ev(`JSON.stringify({over: document.documentElement.scrollWidth - innerWidth, txt: (document.querySelector('#view') || {}).textContent || '', csp: KDEMO.csp})`));
      check(e.over <= 0 && /2\.444,17 €/.test(e.txt), `${tag}: invoice editor fits (${e.over}), total shown`);
      await shot(`p274b-editor-${vw}.png`);
      await ev(`(() => { KDEMO.printView(${id}); return 1; })()`); await sleep(500);
      const p = JSON.parse(await ev(`(() => { const pg = document.querySelector('.kp-page'), sc = document.querySelector('#kd-print .kd-pscroll'), bar = document.querySelector('#kd-print .kd-pbar');
        const btn = [...document.querySelectorAll('#kd-print .kd-btn')].map(b => b.getBoundingClientRect().height);
        return JSON.stringify({page: pg ? pg.scrollWidth - pg.clientWidth : -1, sc: sc ? sc.scrollWidth - sc.clientWidth : -1, over: document.documentElement.scrollWidth - innerWidth,
          bar: bar ? bar.getBoundingClientRect().height : 0, btn: Math.min(...btn), csp: KDEMO.csp}); })()`));
      check(p.page <= 0 && p.sc <= 0 && p.over <= 0, `${tag}: print view without horizontal overflow (page ${p.page}, scroll ${p.sc}, doc ${p.over})`);
      if (touch) check(p.btn >= 43.9, `${tag}: print view buttons 44 px on touch (${p.btn})`);
      check(!p.csp.length && !e.csp.length, `${tag}: nothing blocked by the CSP ${JSON.stringify(p.csp)}`);
      await shot(`p274b-print-${vw}.png`);
    }, touch);
  }

  const bad = hits.filter(h => h !== 'GET /favicon.ico' && !/^GET \/demo\/(index\.html|static\/[\w./-]+)?$/.test(h) || /\/api\//.test(h));
  check(!bad.length, 'only static demo files requested: ' + JSON.stringify(bad.slice(0, 5)));
  check(!errs.length, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  srv.close();
  console.log(`p274_b_demo: ${ok} ok, ${fails.length} failed`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
