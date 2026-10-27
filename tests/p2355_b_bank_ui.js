// kalmido-suite: fresh
// 2.355.0 B (#2843) UI test: one bank booking split across two invoices, own container (start.sh, mode workspaces), Firefox.
// Invented companies, people, accounts and figures only. tenant-matrix: office
// - the bank list: "Other invoice…" -> "Split across invoices…" shows an amount field per open invoice and the live line
//   "Assigned … · rest …"; "Assign match" books both invoices (paid) and the booking shows its overpaid rest under "Matched"
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2355_b_bank_ui', check, shots: 'P2355B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2355BUI_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const day = n => { const d = new Date(TC.today() + 'T12:00:00'); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const camt = rows => `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>${rows.map(([amt, d, name, purpose], i) =>
  `<Ntry><Amt Ccy="EUR">${Math.abs(amt).toFixed(2)}</Amt><CdtDbtInd>${amt > 0 ? 'CRDT' : 'DBIT'}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>${d}</Dt></BookgDt><AcctSvcrRef>P2355BUI-${i}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Dbtr><Pty><Nm>${name}</Nm></Pty></Dbtr></RltdPties><RmtInf><Ustrd>${purpose}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>`).join('')}</Stmt></BkToCstmrStmt></Document>`;

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
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Alpha Beispiel GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE',
    vat_id: 'DE123456789', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Sammel GmbH', street: 'Kundenweg 2', zip: '20095', city: 'Hamburg', country: 'DE'});
  const inv = [];
  for (const [t, rate] of [['Schnitt', 100], ['Ton', 200]]) {
    const d = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: day(20), items: [{title: t, qty: 1, rate}]});
    const f = await call(CA, 'POST', `/api/office/docs/${d.id}/finalize`);
    check(f.http === 200, `invoice ${t} finalised ${f.http}`);
    inv.push(d.id);
  }
  const imp = await call(CA, 'POST', '/api/office/bank/import', {text: camt([[357.01, day(2), 'Kunde Sammel GmbH', 'Sammelueberweisung']]), filename: 'auszug.xml'});
  check(imp.http === 201 && imp.count === 1, 'the booking imported ' + imp.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = sel => `(() => { const e = ${sel}; if (!e) return 0; e.click(); return 1; })()`;
  const type = (id, v) => `(() => { const e = document.querySelector('[data-bnk-part="${id}"]'); if (!e) return 0; e.value = '${v}'; e.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/bank');
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 1`, 80), 'the bank tab lists the booking');
    await ev(click(`document.querySelector('.bnkrow [data-bnk="other"]')`));
    check(await ready(ev, `!!document.querySelector('.bnkother [data-bnk="split"]') && document.querySelectorAll('.bnkother .ofcrow[data-kind="invoice"]').length === 2`),
      'the other invoices with the button "Split across invoices…"');
    await ev(click(`document.querySelector('.bnkother [data-bnk="split"]')`));
    check(await ready(ev, `document.querySelectorAll('[data-bnk-part]').length === 2`), 'an amount field per open invoice');
    await ev(type(inv[0], '119'));
    await ev(type(inv[1], '238'));
    check(await ready(ev, `/Assigned .*357\\.00.* rest .*0\\.01/.test(document.querySelector('[data-bnk-rest]')?.textContent || '')`),
      'the live line: assigned 357.00, rest 0.01 ' + await ev(`document.querySelector('[data-bnk-rest]')?.textContent || ''`));
    await shot('p2355-b-split.png');
    await ev(click(`document.querySelector('[data-bnk="splitgo"]')`));
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 0`, 60), 'assigned: the booking leaves the open list');
    for (const id of inv) {
      const d = await call(CA, 'GET', `/api/office/docs/${id}`);
      check(d.status === 'paid', `invoice ${id} paid ${d.status}`);
    }
    await ev(click(`document.querySelector('[data-bnk="state"][data-v="matched"]')`));
    check(await ready(ev, `/overpaid .*0\\.01/.test(document.querySelector('.bnkrow .bnkm')?.textContent || '')`),
      '"Matched": the booking names its overpaid rest ' + await ev(`document.querySelector('.bnkrow .bnkm')?.textContent || ''`));
    await shot('p2355-b-split-done.png');
  });
  console.log(`p2355_b_bank_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
