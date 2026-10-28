// 2.138.2 UI tests, part A (office documents), own container (start.sh). Invented data only. jsdom:
// - #2393: the PDF buttons of a draft ask first (dialog "not finalised yet": Finalise now / Show as draft / Cancel);
//   Cancel does nothing (no PDF, still a draft); Show as draft opens the preview (the server marks it); Finalise now
//   finalises (the invoice gets its number) and opens the PDF; a finalised document's buttons are the plain links again
//   (no question); a quotation sent without finalising has the plain links too
// - #2391: the number scheme's building blocks offer "Date with hyphens" ({isodate}) in the settings
// freelancer-matrix: office (a person without an organisation gets the same question)
// usage: node p21381_a_ui.js <datadir>      (P21381A_NOSTART=1: a running server, no start.sh)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21381A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,clients';
const TEST_IBAN = 'DE02120300000000202051';
const COMPANY = {name: 'Studio Beispiel GmbH', street: 'Hafenweg 1', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', vat_id: 'DE999999999', iban: TEST_IBAN, bic: 'BYLADEM1001', bank_name: 'Beispielbank'};

// one person's office: a draft invoice (numbered when finalised), a draft quotation, a quotation sent without finalising
async function prepare(ck) {
  await call('GET', '/api/office/settings', null, ck);
  await call('PUT', '/api/office/settings', {lang: 'en', company_fields: COMPANY}, ck);
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'}, ck)).id;
  const inv = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL, service_from: '2026-05-01', service_to: '2026-05-31', items: [{title: 'Schnitt', qty: 1, rate: 900}]}, ck);
  const q = await call('POST', '/api/office/docs', {client_id: CL, project_title: 'Imagefilm', items: [{title: 'Konzept', qty: 1, rate: 800}]}, ck);
  const qs = await call('POST', '/api/office/docs', {client_id: CL, project_title: 'Altes Angebot', items: [{title: 'Dreh', qty: 1, rate: 1200}]}, ck);
  await call('POST', `/api/office/docs/${qs.id}/status`, {status: 'sent'}, ck);
  return {inv, q, qs};
}

async function editor(user, id) {
  const w = await boot({user, hash: `office/offers/${id}`}), d = w.document;
  await until(() => d.querySelector('.ofdhead [data-ofd="more"]'), 60);
  w.__pv = []; w.pdfView = o => { w.__pv.push(o); };  // the PDF viewer (module pdf) is not opened in jsdom
  return [w, d];
}
const dlg = d => d.querySelector('.modal.ofdpa');

async function run(user, ck, tag) {
  const {inv, q, qs} = await prepare(ck);
  check(inv.http === 201 && !inv.number && q.http === 201 && qs.http === 201, `${tag}: documents ` + [inv.http, q.http, qs.http]);
  // ---- a draft quotation: Cancel, Show as draft
  let [w, d] = await editor(user, q.id);
  const pv = d.querySelector('.ofdhead .ofdpdf'), dl = d.querySelector('.ofdhead .ofddl');
  check(pv && pv.tagName === 'BUTTON' && pv.dataset.ofd === 'pdf-ask' && pv.getAttribute('aria-label') === 'Open PDF' && /Preview/.test(pv.textContent)
    && dl && dl.dataset.ofd === 'pdf-ask' && dl.dataset.dl === '1', `${tag}: a draft's PDF buttons ask first (buttons, labels kept)`);
  // 2.380.0 A (#3410): Preview opens the draft at once (no question); the download keeps asking
  click(w, pv);
  await until(() => w.__pv.length, 30);
  check(w.__pv.length === 1 && w.__pv[0].url === `/api/office/docs/${q.id}/pdf?inline=1` && !dlg(d), `${tag}: Preview opens the draft without a question ` + JSON.stringify(w.__pv));
  check((await call('GET', `/api/office/docs/${q.id}`, null, ck)).locked === false, `${tag}: Preview keeps the draft`);
  click(w, dl);
  const m = await until(() => dlg(d), 30);
  check(m && /not finalised yet/.test(m.textContent) && m.querySelector('[data-pa="final"]') && m.querySelector('[data-pa="draft"]') && m.querySelector('[data-pa=""]')
    && m.getAttribute('role') === 'alertdialog', `${tag}: the download asks: Finalise now / Show as draft / Cancel ` + (m?.textContent || '').slice(0, 160));
  click(w, m?.querySelector('[data-pa=""]'));
  await until(() => !dlg(d), 20); await sleep(300);
  const q1 = await call('GET', `/api/office/docs/${q.id}`, null, ck);
  check(!dlg(d) && w.__pv.length === 1 && q1.locked === false && q1.status === 'draft', `${tag}: Cancel does nothing (still a draft)`);
  click(w, dl);
  click(w, await until(() => dlg(d)?.querySelector('[data-pa="draft"]'), 30));
  await until(() => !dlg(d), 20);
  check(!dlg(d) && w.__pv.length === 1, `${tag}: the download button asks the same and downloads (no viewer)`);
  check(!errs.length, `${tag}: no script errors ` + errs.join(' | ')); errs.splice(0);
  w.close();

  // ---- a draft invoice: Finalise now gives the number, then the PDF; afterwards plain links
  [w, d] = await editor(user, inv.id);
  click(w, d.querySelector('.ofdhead .ofddl'));  // 2.380.0 A (#3410): the download asks (Preview no longer)
  click(w, await until(() => dlg(d)?.querySelector('[data-pa="final"]'), 30));
  const srv = await until(async () => { const j = await call('GET', `/api/office/docs/${inv.id}`, null, ck); return j.locked && j; }, 60);
  check(srv && srv.locked && /\d/.test(srv.number || ''), `${tag}: Finalise now finalises and gives the number ` + (srv && srv.number));
  await sleep(300);
  check(w.__pv.length === 0, `${tag}: then the PDF downloads (no viewer) ` + JSON.stringify(w.__pv));
  await until(() => d.querySelector('a.ofdpdf[data-ofd="pdf"]'), 30);
  const a = d.querySelector('a.ofdpdf[data-ofd="pdf"]');
  check(a && a.getAttribute('href') === `/api/office/docs/${inv.id}/pdf?inline=1` && d.querySelector('a.ofddl[data-ofd="pdf"]')?.hasAttribute('download') && !d.querySelector('[data-ofd="pdf-ask"]'),
    `${tag}: finalised: the plain PDF links, no question`);
  check(!errs.length, `${tag}: no script errors ` + errs.join(' | ')); errs.splice(0);
  w.close();

  // ---- a quotation sent without finalising: plain links (locked since 2.39.0, printed unmarked)
  [w, d] = await editor(user, qs.id);
  check(d.querySelector('a.ofdpdf[data-ofd="pdf"]') && !d.querySelector('[data-ofd="pdf-ask"]'), `${tag}: a sent quotation: the plain PDF links`);
  w.close();
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Beispiel Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await run('alice', CK, 'org');

  // ================= #2391: the building block in the settings
  const w = await boot({hash: 'office/settings'}), d = w.document;
  const bb = await until(() => d.querySelector('.ofcbb [data-bb="{isodate}"]'), 60);
  check(bb && /Date with hyphens/.test(bb.textContent) && bb.title === '{isodate}', '#2391: the building block "Date with hyphens" ({isodate})');
  check(/\{isodate\} = Date with hyphens \(2026-10-14\)/.test(d.body.textContent), '#2391: the explanation lists {isodate}');
  w.close();

  // ================= freelancer-matrix: office (a person without an organisation, its own admin)
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FCK);
  await run('frida', FCK, 'freelancer');

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
