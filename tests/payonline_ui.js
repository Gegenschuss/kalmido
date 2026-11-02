// kalmido-suite: fresh
// 2.469.0 UI test (#3459), own container (start.sh), Firefox (desktop, mouse). Invented names only.
// PAYONLINEUI_NOSTART=1 = the server already runs.
// - freelancer-matrix: office -- a person without an organisation: Office > Settings > Invoices has the block "Online payment of
//   invoices" (provider, key, webhook address to copy, secret, switch only once both are set); no secret is shown again
// - the invoice shows the switch "Offer online payment"; switched off it stays off after a reload
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'payonline_ui', check, shots: 'PAYONLINEUI_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.PAYONLINEUI_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {http: r.status, ...j}; };
const FEAT = 'cal,comments,collab,office,clients,docs,contacts,time';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments', 'collab']});
  await call(CA, 'POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida Free', password: 'password123', email: 'frida@example.com'});
  const FR = await login('frida');
  await call(FR, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(FR, 'PUT', '/api/office/settings', {lang: 'en', currency: 'EUR', company_fields: {name: 'Studio Frida', street: 'Hafenstraße 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const cl = await call(FR, 'POST', '/api/clients', {name: 'Testkunde Nord', street: 'Marktstraße 5', zip: '50667', city: 'Köln', country: 'DE'});
  const inv = await call(FR, 'POST', '/api/office/docs', {kind: 'invoice', lang: 'en', client_id: cl.id, service_from: '2026-10-01', items: [{title: 'Schnitt', qty: 1, rate: 100}]});
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.ok)`);
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#pol-set')`, 100), 'the block in the settings');
    await ev(`(() => { const d = document.querySelector('#pol-set'); d.open = true; const s = document.querySelector('#pol-provider'); s.value = 'stripe'; s.dispatchEvent(new Event('change', {bubbles: true})); })()`);
    check(await ready(ev, `!!document.querySelector('#pol-url') && document.querySelector('#pol-url').value.includes('/api/hooks/pay/')`), 'the webhook address shows after choosing the provider');
    check(await ev(`document.querySelector('#pol-on').disabled`), 'the switch waits for the key and the secret');
    for (const [id, v] of [['#pol-key', 'sk_test_ui'], ['#pol-sec', 'whsec_ui_0123456789']]) {
      await ev(`(() => { const i = document.querySelector('${id}'); i.value = '${v}'; i.dispatchEvent(new Event('change', {bubbles: true})); })()`);
      await sleep(200);
      await ready(ev, `document.querySelector('${id}') && document.querySelector('${id}').value === ''`);
    }
    check(await ready(ev, `!document.querySelector('#pol-on').disabled`), 'both set: the switch can be used');
    check(await ev(`document.querySelector('#pol-key').value === '' && !document.querySelector('#pol-set').textContent.includes('sk_test_ui')`), 'the key is not shown again');
    await ev(`document.querySelector('#pol-on').click()`);
    check(await ready(ev, `document.querySelector('#pol-on').checked`), 'switched on');
    await shot('settings');
    await call(FR, 'POST', `/api/office/docs/${inv.id}/finalize`);
    await nav(B + `#office/invoices/${inv.id}`);
    check(await ready(ev, `!!document.querySelector('#pol-doc input[data-poldoc="on"]')`, 100), 'the invoice shows the switch');
    check(await ev(`!!document.querySelector('[data-poldoc="copy"]')`), 'and the copy button');
    await ev(`document.querySelector('#pol-doc input[data-poldoc="on"]').click()`);
    await sleep(300);
    const j = await call(FR, 'GET', `/api/office/docs/${inv.id}`);
    check(j.pay_online && j.pay_online.on === false, 'switched off on the server');
    await shot('invoice');
  });
  console.log(`payonline_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
