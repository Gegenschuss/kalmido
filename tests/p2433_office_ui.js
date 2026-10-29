// kalmido-suite: fresh
// 2.433.0 UI test (#3597 #3599 #3604), own container (start.sh), Firefox (desktop, mouse). Invented names only.
// P2433UI_NOSTART=1 = the server already runs.
// - freelancer-matrix: office -- a person without an organisation (the own admin of the personal office):
// - #3604 the client dialog has the field "Short code" (capitals, the automatic code as placeholder), the scheme's building
//   blocks offer {kuerzel}
// - #3597 Settings > Documents & numbers: the switch "Invoice corrections count in the invoice series"; on = the correction
//   scheme becomes the invoice scheme with _RK, the corrections' row of the number ranges is greyed (not settable)
// - #3599 the e-mail for invoices sits next to E-mail (also when adding a client), a contact person has "Gets invoices";
//   the send dialog of an invoice starts with the e-mail for invoices and the contact persons for invoices in copy
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2433_office_ui', check, shots: 'P2433UI_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2433UI_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {http: r.status, ...j}; };
const FEAT = 'cal,comments,collab,office,clients,docs,contacts,time';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments', 'collab']});
  const r0 = await call(CA, 'POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida Free', password: 'password123', email: 'frida@example.com'});
  check(r0.http < 300, 'user frida ' + r0.http);
  const FR = await login('frida');
  await call(FR, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const st = await call(FR, 'PUT', '/api/office/settings', {company: {name: 'Studio Frida'}, lang: 'de', currency: 'EUR',
    company_fields: {name: 'Studio Frida', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051'}});
  check(st.http === 200, 'freelancer: the own office settings ' + st.http);
  const cl = await call(FR, 'POST', '/api/clients', {name: 'Testkunde Nord Partner', short_code: 'TNP', email: 'info@kunde.example', email_invoice: 'rechnung@kunde.example',
    street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE',
    contacts: [{name: 'Anna Projekt', email: 'anna@kunde.example', is_default: true}, {name: 'Bert Buchhaltung', email: 'bert@kunde.example', gets_invoices: true}]});
  check(cl.http === 201, 'a client with short code and contact persons ' + cl.http);
  const inv = await call(FR, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: '2026-10-01', items: [{title: 'Schnitt', qty: 1, rate: 100}]});
  check(inv.http === 201, 'an invoice draft ' + inv.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const fresh = async (ev, nav, u) => { await nav(B + 'static/icon.svg'); await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.ofcSetSub', '"docs"'); return 1; })()`); await signIn(ev, u); };

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await fresh(ev, nav, 'frida');
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set #os-cr-shared')`, 80), '#3597: the switch at the number schemes');
    if (await ev(`(() => { const p = document.querySelector('#ofc-set [data-ostp="docs"]'); return !!p && p.hidden; })()`)) await ev(`(() => { ost_show('docs'); return 1; })()`);
    check(await ev(`!!document.querySelector('#ofc-set .ofcbb [data-bb="{kuerzel}"]')`), '#3604: the building block {kuerzel} as a button');
    check(await ready(ev, `!!document.querySelector('#onum-box .onumrow[data-kind="credit"] input:not([disabled])')`, 40), '#3597: off - the corrections\' own number range');
    await ev(`(() => { const x = document.querySelector('#os-cr-shared'); x.click(); return 1; })()`);
    let on = 0;
    for (let i = 0; i < 40 && !on; i++) { on = (await call(FR, 'GET', '/api/office/settings')).settings?.credit_shared; if (!on) await sleep(200); }
    check(on === 1, '#3597: the switch saves itself');
    check(await ready(ev, `(document.querySelector('#os-cr-scheme')?.value || '') === 'RE-{yyyy}-{seq:03}_RK'`, 40), '#3597: the correction scheme becomes the invoice scheme with _RK ' + await ev(`document.querySelector('#os-cr-scheme')?.value`));
    check(await ready(ev, `!!document.querySelector('#onum-box .onumshared[data-kind="credit"] input[disabled]') && /Counts with the invoice numbers/.test(document.querySelector('#onum-box .onumshared').textContent)`, 40),
      '#3597: the corrections\' number range greyed, "Counts with the invoice numbers"');
    await shot('p2433-settings.png');

    // the client dialog
    await ev(`(() => { api('GET', '/api/clients/${cl.id}').then(c => clientModal(c)); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.cldlg #cl-sc')`), '#3604: the field "Short code" in the client dialog');
    check(await ev(`(() => { const m = document.querySelector('.modal.cldlg'), sc = m.querySelector('#cl-sc'); return sc.value === 'TNP' && sc.maxLength === 6; })()`), '#3604: the saved code');
    check(await ev(`(() => { const sc = document.querySelector('#cl-sc'); sc.value = ''; const n = document.querySelector('#cl-name'); n.value = 'Müller Film'; n.dispatchEvent(new Event('input', {bubbles: true})); sc.value = 'ab-1'; sc.dispatchEvent(new Event('input', {bubbles: true})); return sc.placeholder === 'MUE' && sc.value === 'AB1'; })()`),
      '#3604: the automatic code as placeholder (Müller -> MUE), capitals while typing');
    check(await ev(`(() => { const m = document.querySelector('.modal.cldlg'), e = m.querySelector('#cl-email'), i = m.querySelector('#clb-email_invoice'), p = m.querySelector('#cl-phone');
      return !!i && i.value === 'rechnung@kunde.example' && !i.closest('.clbill') && !!(e.compareDocumentPosition(i) & 4) && !!(i.compareDocumentPosition(p) & 4); })()`), '#3599: the e-mail for invoices between E-mail and Phone');
    check(await ev(`(() => { const bs = [...document.querySelectorAll('.modal.cldlg [data-clk="gets_invoices"]')]; return bs.length === 2 && !bs[0].checked && bs[1].checked; })()`), '#3599: "Gets invoices" per contact person');
    await shot('p2433-client.png');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); if (typeof FG !== 'undefined') FG.d = {}; return 1; })()`);
    await ev(`(() => { clientModal(null); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal.cldlg #cl-name')`), 'the dialog of a new client');
    check(await ev(`(() => { const m = document.querySelector('.modal.cldlg'), i = m.querySelector('#clb-email_invoice'); return !!i && !i.closest('#cl-more') && !!m.querySelector('#cl-more #cl-sc'); })()`),
      '#3599: a new client shows the e-mail for invoices at once (the short code under More details)');
    await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); if (typeof FG !== 'undefined') FG.d = {}; return 1; })()`);

    // the send dialog of the invoice
    const fin = await call(FR, 'POST', `/api/office/docs/${inv.id}/finalize`);
    check(fin.http === 200, 'the invoice is finalised ' + fin.http);
    await nav(B + `#office/doc/${inv.id}`);
    await ready(ev, `typeof ofdSendDialog === 'function'`, 80);
    await ev(`(() => { api('GET', '/api/office/docs/${inv.id}').then(d => ofdSendDialog(d)); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#ofd-s-to')`, 40), 'the send dialog opens');
    check(await ready(ev, `document.querySelector('#ofd-s-to').value === 'rechnung@kunde.example' && document.querySelector('#ofd-s-cc').value === 'bert@kunde.example'`, 20),
      '#3599: to the e-mail for invoices, the contact person for invoices in copy ' + await ev(`[document.querySelector('#ofd-s-to')?.value, document.querySelector('#ofd-s-cc')?.value].join(' | ')`));
    await shot('p2433-send.png');
  }, false);

  console.log(`p2433_office_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
