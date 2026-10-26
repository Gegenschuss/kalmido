// 2.154.0 UI tests, part B (#1960): e-invoices over the Peppol network, own container (start.sh, mode workspaces) with the
// stand-in provider inside (stub_peppol.py, port 8098; no real provider is called), Firefox (desktop + phone width).
// Invented companies, people and figures only.
// - the office settings (area documents): the block "E-invoices over the Peppol network" says the provider bills directly;
//   choosing "Own endpoint (URL)" shows the address, the key field and the own Peppol ID with the suggestion from the VAT ID;
//   each field saves itself, the key is never shown again (placeholder "saved"), "Check connection" says it works
// - the client's billing details have the field "Peppol ID" (with its (i))
// - a finalised invoice: the menu offers "Send e-invoice over the Peppol network" and the UBL download; the dialog names the
//   recipient, sends, lists the send as "Sent over Peppol"; the document then shows the status line
// - a client without an id: the dialog names what is missing and offers the id from the VAT ID; taking it over saves it
// - on a phone the dialog stays inside the screen
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2154_b_ui', check, shots: 'P2154B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
if (!process.env.P2154B_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
    EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098 -e KALMIDO_PEPPOL_ALLOW_HOSTS=127.0.0.1:8098'}});  // 2.306.0 D2 (#2875)
  // #2716: the root filesystem is read-only, docker cp refuses even /tmp (tmpfs) - pipe the file in
  execFileSync('docker', ['exec', '-i', CT, 'sh', '-c', 'cat > /tmp/stub_peppol.py'], {input: require('fs').readFileSync(path.join(__dirname, 'stub_peppol.py'))});
  execFileSync('docker', ['exec', '-d', CT, 'python', '/tmp/stub_peppol.py']);
}
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(1200);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const st = await call(CA, 'PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', email: 'hallo@beispiel.example',
    phone: '+49 30 000000', vat_id: 'DE123456789', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  check(st.http === 200, 'office settings ' + st.http);
  const mk = async (name, extra) => (await call(CA, 'POST', '/api/clients', {name, street: 'Marktstraat 5', zip: '1000', city: 'Brussel', country: 'BE', vat_id: 'BE0123456749', customer_no: 'K-7', ...extra})).id;
  const inv = async cl => {
    const d = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', lang: 'de', client_id: cl, project_title: 'Schnitt', service_from: '2026-05-01', items: [{title: 'Schnitt', qty: 2, rate: 450}]});
    const f = await call(CA, 'POST', `/api/office/docs/${d.id}/finalize`);
    check(f.http === 200, 'finalised ' + f.http);
    return d.id;
  };
  const CL1 = await mk('Kunde Eins NV', {peppol_id: '0208:0123456749'}), CL2 = await mk('Kunde Zwei NV');
  const D1 = await inv(CL1), D2 = await inv(CL2);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  const setVal = (sel, v) => `(() => { const e = document.querySelector('${sel}'); e.value = ${JSON.stringify(v)}; e.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  const conf = () => `fetch('/api/office/peppol', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev);
    // ================= the settings block
    await nav(B + '#office/settings');
    await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub="docs"]')`, 80);
    await ev(`(() => { document.querySelector('#ofc-set [data-ostsub="docs"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#pep-set #pep-provider')?.getClientRects().length || (() => { const d = document.querySelector('#pep-set'); if (d) d.open = true; return !!document.querySelector('#pep-set #pep-provider'); })()`, 80),
      'the settings show the Peppol block');
    check(await ev(`/bills you directly/.test(document.querySelector('#pep-set').textContent)`), 'the block says the provider bills directly');
    await ev(setVal('#pep-provider', 'custom'));
    check(await ready(ev, `!!document.querySelector('#pep-url') && !!document.querySelector('#pep-key') && !!document.querySelector('#pep-sender')`, 60), 'own endpoint: address, key and own id');
    await ev(setVal('#pep-url', 'http://127.0.0.1:8098/own'));
    await ready(ev, `${conf()}.then(j => j.endpoint_url === 'http://127.0.0.1:8098/own')`, 60);
    await ev(setVal('#pep-key', 'good-key'));
    check(await ready(ev, `${conf()}.then(j => j.key_set)`, 60), 'the key is saved');
    check(await ready(ev, `document.querySelector('#pep-key')?.value === '' && /saved/.test(document.querySelector('#pep-key')?.placeholder || '')`, 40), 'the key is never shown again');
    const sug = await ready(ev, `!!document.querySelector('#pep-set [data-pepa="suggest"]')`, 40);
    check(sug && await ev(`/9930:DE123456789/.test(document.querySelector('#pep-set [data-pepa="suggest"]').textContent)`), 'the own id is suggested from the VAT id');
    await ev(`(() => { document.querySelector('#pep-set [data-pepa="suggest"]').click(); return 1; })()`);
    check(await ready(ev, `${conf()}.then(j => j.sender_id === '9930:DE123456789' && j.ready)`, 60), 'the suggestion is taken over: ready');
    await ready(ev, `!document.querySelector('#pep-set [data-pepa="check"]')?.disabled`, 40);
    await ev(`(() => { document.querySelector('#pep-set [data-pepa="check"]').click(); return 1; })()`);
    check(await ready(ev, `/Connection works/.test(document.querySelector('#pep-set').textContent)`, 60), 'check connection: it works');
    await ev(`(() => { document.querySelector('#pep-set').scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
    await shot('p2154-b-settings.png');
    // ================= the client field
    check(await ev(`(() => { const h = ofxClientBillingHtml({peppol_id: '0208:0123456749'}); return h.includes('id="clb-peppol_id"') && h.includes('0208:0123456749'); })()`), 'the client billing details have the Peppol ID field');
    // ================= the invoice: menu, dialog, send, status line
    await nav(B + 'static/icon.svg'); await nav(B + `#office/offers/${D1}`);
    check(await ready(ev, `typeof OFD === 'object' && OFD.doc?.id === ${D1} && OFD.doc.locked`, 80), 'the invoice opens');
    await ready(ev, `typeof pep_moreItems === 'function' && pep_moreItems(OFD.doc).length === 2`, 60);
    check(await ev(`(() => { const t = ofdMoreItems(OFD.doc, false).filter(Boolean).map(x => x.label || ''); return t.includes('Send e-invoice over the Peppol network') && t.includes('E-invoice UBL (Peppol)'); })()`), 'the menu offers sending + UBL');
    await ev(`(() => { pep_dialog(OFD.doc); return 1; })()`);
    check(await ready(ev, `/0208:0123456749/.test(document.querySelector('#pep-dlg')?.textContent || '') && !document.querySelector('.modal [data-pepd="send"]').hidden`, 60), 'the dialog names the recipient, send offered');
    await shot('p2154-b-dialog.png');
    await ev(`(() => { document.querySelector('.modal [data-pepd="send"]').click(); return 1; })()`);
    check(await ready(ev, `/Sent over Peppol/.test(document.querySelector('#pep-dlg')?.textContent || '') && document.querySelector('.modal [data-pepd="send"]').hidden`, 80), 'sent: listed, no second send button');
    await shot('p2154-b-sent.png');
    await ev(`(() => { document.querySelector('.modal [data-pepd="close"]').click(); return 1; })()`);
    check(await ready(ev, `/Sent over Peppol/.test(document.querySelector('.pepline')?.textContent || '')`, 60), 'the document shows the status line');
    // ================= a client without an id: what is missing + the suggestion
    await nav(B + 'static/icon.svg'); await nav(B + `#office/offers/${D2}`);
    await ready(ev, `typeof OFD === 'object' && OFD.doc?.id === ${D2}`, 80);
    await ready(ev, `typeof pep_dialog === 'function'`, 40);
    await ev(`(() => { pep_dialog(OFD.doc); return 1; })()`);
    check(await ready(ev, `/The client has no Peppol ID/.test(document.querySelector('#pep-dlg')?.textContent || '') && document.querySelector('.modal [data-pepd="send"]').hidden`, 60), 'missing: the client has no id');
    check(await ev(`/0208:0123456749/.test(document.querySelector('[data-pepd="take"]')?.textContent || '')`), 'the id is suggested from the VAT id');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(`(() => { const c = document.querySelector('.modal .card').getBoundingClientRect(); return c.left >= -1 && c.right <= document.documentElement.clientWidth + 1; })()`), 'on a phone the dialog stays inside the screen');
    await shot('p2154-b-missing-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { document.querySelector('[data-pepd="take"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal [data-pepd="send"]').hidden && !/The client has no Peppol ID/.test(document.querySelector('#pep-dlg').textContent)`, 60), 'taken over: ready to send');
    const c2 = await call(CA, 'GET', `/api/clients/${CL2}`);
    check(c2.billing?.peppol_id === '0208:0123456749', 'the client keeps the taken id');
  }, false);

  console.log(`p2154_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
