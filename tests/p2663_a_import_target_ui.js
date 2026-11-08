// kalmido-suite: fresh
// 2.663.0 (#4341) UI test (jsdom, own container, mode workspaces; invented data only): the other importers of KNOWN in
// tests/p2356_b_import_target_test.py ask for the target before they store anything, seen by behaviour like the four of #2934 in
// tests/p2501_b_import_target_ui.js: fixed costs, legacy data, trips, budget, Paperless, account move, feeds (OPML), calendar,
// contacts, knowledge pages and tables. Each is driven to its real store step with the shared question stubbed: "no" = no storing
// request, "yes" = the request goes out after the question, and the question names the right workspace (organisation / private).
// A step before it that needs a file on the server or an outside service (preview, upload, a Paperless connection) is given its
// state directly; where the store step is not a button of its own, a test button calls what the app's button / file input calls.
// freelancer-matrix: office, personal, pim, wiki, sheets  tenant-matrix: office, calendar, book
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, idle, until, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2663AUI_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const FEAT = 'cal,comments,collab,office,clients,events,contacts,budget,home,feeds,sheets';
const DAY = TC.today();
const camt = `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt><Id>P2663-1</Id><Ntry><Amt Ccy="EUR">12.00</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>${DAY}</Dt></BookgDt><NtryDtls><TxDtls><RmtInf><Ustrd>Kaffee Beispiel</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>`;
const COMPANY = {name: 'Beispiel GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', vat_id: 'DE123456789', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'};
// the files the importers read (an empty ZIP = its end record only, 22 bytes: the smallest the wiki upload takes)
const files = who => ({
  camt: new File([camt], 'auszug.xml', {type: 'text/xml'}),
  ics: new File([`BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Beispiel//DE\r\nBEGIN:VEVENT\r\nUID:p2663-${who}@example.com\r\nDTSTAMP:20260101T000000Z\r\nDTSTART;VALUE=DATE:${DAY.replace(/-/g, '')}\r\nSUMMARY:Termin Beispiel\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n`], 'termine.ics', {type: 'text/calendar'}),
  vcf: new File(['BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Kontakt Beispiel\r\nEND:VCARD\r\n'], 'kontakt.vcf', {type: 'text/vcard'}),
  opml: new File([`<?xml version="1.0"?><opml version="2.0"><head><title>Feeds</title></head><body><outline type="rss" text="Beispiel" xmlUrl="https://example.com/p2663-${who}.xml"/></body></opml>`], 'feeds.opml', {type: 'text/xml'}),
  zip: new File([Buffer.from([0x50, 0x4b, 0x05, 0x06, ...Array(18).fill(0)])], 'wissen.zip', {type: 'application/zip'}),
  csv: new File(['Name,Betrag\nBeispiel,1\n'], 'tabelle.csv', {type: 'text/csv'})});

// the storing requests, in a list the page cannot lose (fetch is wrapped before the app starts). Only the real store steps of
// these importers count (by their path); their previews, checks, parses, upload starts of a move and the pieces of an upload do not
const STORE = [/^\/api\/office\/fixed-costs\/import$/, /^\/api\/office\/legacy\/import$/, /^\/api\/office\/trips\/import$/, /^\/api\/budget\/\d+\/import\/commit$/,
  /^\/api\/paperless(\/zip)?\/import$/, /^\/api\/account\/import\/[^/]+\/run$/, /^\/api\/feeds\/opml$/, /^\/api\/evcals\/\d+\/import$/, /^\/api\/books\/\d+\/import$/,
  /^\/api\/wiki\/import\/upload$/, /^\/api\/sheets\/import$/];
const watch = x => { x.__log = [];
  x.__store = (method, u) => { const url = String(u); return String(method || 'GET').toUpperCase() === 'POST' && !/preview/.test(url) && STORE.some(r => r.test(url.replace(/^\w+:\/\/[^/]+/, '').split('?')[0])); };
  const f0 = x.fetch; x.fetch = (u, o = {}) => { if (x.__store(o.method, u)) x.__log.push('post ' + String(u)); return f0(u, o); }; };

async function importer(w, who, name, open, go, url) {
  const d = w.document;
  w.eval(`window.__ask = []; window.__ans = false; importTargetConfirm = async o => { __log.push('ask'); __ask.push(o); return __ans; };`);
  w.__log.length = 0;
  await open(d);
  const btn = await until(() => go(d));
  check(btn, `${who} ${name}: the dialog reaches its store button`);
  if (!btn) return null;
  btn.click();
  check(await until(() => w.__log.includes('ask')), `${who} ${name}: the question comes`);
  await idle(w);
  check(w.__log.join() === 'ask', `${who} ${name}: "no" stores nothing: ${w.__log.join()}`);
  w.__log.length = 0; w.eval(`__ans = true`);
  const again = await until(() => { const b = go(d); return b && !b.disabled ? b : null; });
  check(again, `${who} ${name}: after "no" the button works again`);
  if (!again) return null;
  again.click();
  check(await until(() => w.__log.some(x => x.startsWith('post ') && url.test(x))), `${who} ${name}: "yes" sends the import: ${w.__log.join()}`);
  check(w.__log[0] === 'ask', `${who} ${name}: the question before the request: ${w.__log.join()}`);
  await idle(w);
  return w.eval(`__ask[0]`);
}
// a test button for an importer whose store step is no button of its own: a click runs what the app's button / file input runs
const trigger = (w, key, code) => d => {
  let b = d.querySelector(`button[data-p2663="${key}"]`);
  if (!b) {
    b = d.createElement('button'); b.type = 'button'; b.dataset.p2663 = key; b.textContent = key; d.body.append(b);
    b.addEventListener('click', () => { Promise.resolve().then(() => w.eval(code)).catch(e => check(false, `${key}: ${e && e.message}`)); });
  }
  return b;
};
// the app's own file input (made here when the view that holds it is not open): the chosen file, then its change event
const PICK = `window.__pick = (sel, mk, file) => { let f = document.querySelector(sel); if (!f) { f = document.createElement('input'); f.type = 'file'; f.hidden = true; mk(f); f.dataset.p2663 = 'in'; document.body.append(f); }
  Object.defineProperty(f, 'files', {configurable: true, value: [file]}); f.dispatchEvent(new Event('change', {bubbles: true})); };`;
const shut = d => d.querySelectorAll('.modal, [data-p2663], #ctimp').forEach(x => x.remove());

async function all(user, who, isOrg, ORG, ids) {
  const w = await boot({user, hash: 'office', setup: watch}), d = w.document;
  check(await until(() => w.eval('!!OFC.info')), `${who}: the office is open`);  // ofcWs(): the workspace of the shown office
  w.__f = files(who); w.eval(PICK);
  const here = isOrg ? `org:${ORG}` : 'private';
  const ws = (name, o, want = here) => check(o && (want instanceof RegExp ? want.test(String(o.ws)) : (o.ws || 'private') === want), `${who} ${name}: the question names the workspace ${want}: ${o && o.ws}`);
  const office = isOrg ? /^org:\d+$/ : 'private';  // like p2501_b: the office of the shown workspace

  // ---- the office: fixed costs, legacy data, trips (their previews need an uploaded file: the dialog gets the preview's rows)
  ws('fixed costs', await importer(w, who, 'fixed costs', () => w.eval(`fci_modal([{row: 2, label: 'Miete ${who}', amount: 500, repeat: 'monthly', start: '${DAY}', category: 'Miete', vat_rate: 19, sel: true, status: 'new'}], 'fixkosten.xlsx'); 1`),
    d => d.querySelector('[data-fci="go"]'), /office\/fixed-costs\/import/), office);
  shut(d);
  ws('legacy data', await importer(w, who, 'legacy data', () => w.eval(`OIM.pv = {clients: [{row: 2, name: 'Altkunde ${who}', action: 'new', city: 'Musterstadt', country: 'de'}]}; 1`),  // the preview (oimPreview) only fills OIM.pv
    trigger(w, 'oim', 'oimImport()'), /office\/legacy\/import/), office);  // its button in the import view calls oimImport()
  shut(d);
  ws('trips', await importer(w, who, 'trips', () => w.eval(`rk_impModal({people: [], sheets: [{sheet: 'Reisen ${who}', person: null, sum_excel: 14, sum_calc: 14,
      rows: [{row: 2, date_from: '${DAY}', date_to: '${DAY}', dest: 'Musterstadt', overnight: 0, purpose: 'job', amount: 14, excel: 14, reasons: [], sel: true, status: 'new'}]}]}, 'reisen.xlsx'); 1`),
    d => d.querySelector('[data-rki="go"]'), /office\/trips\/import/), office);
  shut(d);

  // ---- the budget: its dialog with the real file step (bgTake = what the file input does; CAMT goes straight to the rows).
  // A budget list is never an organisation's (budget.py bud_list_create): the question names Private for both
  ws('budget', await importer(w, who, 'budget', () => w.eval(`{ BG.lid = ${ids.budget}; const md = bg_csvModal(); md.bgTake([__f.camt]); }`),
    d => d.querySelector('.modal.bgdlg .bgprev') && d.querySelector('.modal.bgdlg [data-cs="next"]'), /budget\/\d+\/import\/commit/), 'private');
  shut(d);

  // ---- Paperless: its preview needs a connection to a Paperless server; the preview's answer is given, the import is real
  w.eval(`window.__api0 = api; PL.ws = '${here}'; api = async (m, u, b) => m === 'GET' && /^\\/api\\/paperless\\/preview/.test(u) ? {count: 1, already: 0, tags: [], senders: [], types: []} : __api0(m, u, b);`);
  ws('Paperless', await importer(w, who, 'Paperless', () => w.eval(`pl_preview(); 1`),
    d => d.querySelector('.pl-pmd [data-plp="start"]'), /paperless\/import/));
  w.eval(`api = __api0;`);
  shut(d);

  // ---- the account move: its preview needs an uploaded export; the import box gets the preview, the run is real (Settings > Data)
  const targets = isOrg ? `[{id: ${ORG}, name: 'Alpha'}, {id: 'private'}]` : `[{id: 'private'}]`;
  ws('account move', await importer(w, who, 'account move', () => w.eval(`{ const md = document.createElement('div'); md.dataset.p2663 = 'umz';
      md.innerHTML = '<div id="s-umz-exp"></div><div id="s-umz-sig"></div><div id="s-umz-imp"></div>'; document.body.append(md); umzInit(md);
      umzImpDraw(md, {id: 'p2663', state: 'preview', preview: {kind: 'user', source: {url: ''}, user: {name: 'Beispiel'}, created_at: '${DAY}T08:00:00Z', counts: {tasks: 1},
        lists: [], people: [], server_links: [], encrypted: {}, not_taken: [], targets: ${targets}}}); }`),
    d => d.querySelector('[data-p2663="umz"] [data-umz="go"]'), /account\/import\/[^/ ]+\/run/));
  shut(d);

  // ---- the file inputs of feeds (OPML), knowledge pages (ZIP) and tables (CSV): the app's own change handlers
  ws('feeds', await importer(w, who, 'feeds', () => {}, trigger(w, 'opml', `__pick('[data-rss-opml]', f => f.setAttribute('data-rss-opml', ''), __f.opml)`), /feeds\/opml/));
  shut(d);
  // ---- calendar and contacts: the import of a given file into the calendar / address book (as from another app, #2154)
  ws('calendar', await importer(w, who, 'calendar', () => {},
    trigger(w, 'ev', `evImport(S.evcals.find(c => c.id === ${ids.cal}) || {id: ${ids.cal}, name: '?'}, () => {}, __f.ics)`), /evcals\/\d+\/import/));
  shut(d);
  // the contacts upload goes by XMLHttpRequest (progress): a stand-in records it and answers "not stored", nothing reaches the server
  w.eval(`window.__XHR0 = XMLHttpRequest; XMLHttpRequest = class { open(m, u) { this.m = m; this.u = u; } setRequestHeader() {} get upload() { return {}; }
    send() { if (__store(this.m, this.u)) __log.push('post ' + this.u); this.status = 400; this.responseText = '{"error": "test"}'; setTimeout(() => this.onload(), 0); } };`);
  ws('contacts', await importer(w, who, 'contacts', () => {}, trigger(w, 'ct', `ctImport(${ids.book}, 'vcf', __f.vcf)`), /books\/\d+\/import/));
  w.eval(`XMLHttpRequest = __XHR0;`);
  shut(d);
  ws('knowledge pages', await importer(w, who, 'knowledge pages', () => {}, trigger(w, 'wk', `__pick('#wk-zip-file', f => { f.id = 'wk-zip-file'; }, __f.zip)`), /wiki\/import\/upload/));
  shut(d);
  // last: a stored table opens itself (go('sheets/<id>'))
  ws('tables', await importer(w, who, 'tables', () => {}, trigger(w, 'sh', `__pick('#shx-import-file', f => { f.id = 'shx-import-file'; }, __f.csv)`), /sheets\/import/));
  shut(d);
  w.close();
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'PUT', '/api/office/settings', {company_fields: COMPANY});
  const A = {cal: (await call(CA, 'POST', '/api/evcals', {name: 'Team', org_id: org.id})).id, book: (await call(CA, 'POST', '/api/books', {name: 'Kunden', org_id: org.id})).id,
    budget: (await call(CA, 'POST', '/api/budget/lists', {})).list_id};
  check(A.cal && A.book && A.budget, 'setup: the calendar, address book (organisation) and budget of alice ' + JSON.stringify(A));
  // a person without an organisation: the same importers in her private workspace
  const u = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', orgs: []});
  check(u.id, 'setup: frida ' + JSON.stringify(u).slice(0, 160));
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CF, 'PUT', '/api/office/settings', {company_fields: COMPANY});
  const Fr = {cal: (await call(CF, 'POST', '/api/evcals', {name: 'Privat'})).id, book: (await call(CF, 'POST', '/api/books', {name: 'Privat'})).id,
    budget: (await call(CF, 'POST', '/api/budget/lists', {})).list_id};
  check(Fr.cal && Fr.book && Fr.budget, 'setup: the calendar, address book and budget of frida ' + JSON.stringify(Fr));

  await all('alice', 'org', true, org.id, A);
  await all('frida', 'frei', false, null, Fr);

  console.log(`p2663_a_import_target_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
