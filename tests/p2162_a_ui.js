// 2.162.0 part A UI test (#2603), turned round by 2.417.0 C (#2604): the test phase deletion is gone - the "More" menu of a
// finalised invoice no longer offers "Delete" to the admin (no "type the number" dialog), "Credit note / cancel" is the way;
// the row menu of the list neither. Desktop and the phone width (mobile). Invented names only. P2162AUI_NOSTART=1 = the
// server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2162AUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const items = d => [...d.querySelectorAll('#pop [role="menuitem"], .menu-list [role="menuitem"], .sheet [role="menuitem"]')];
const names = d => items(d).map(b => b.textContent.trim());
const FEAT = 'clients,office';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments']});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Studio Example GmbH', street: 'Hafenweg 1', zip: '20457', city: 'Hamburg', country: 'de', tax_number: '12/345/67890', vat_id: 'DE999999999', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Example Bank'}, lang: 'en'});
  const C = await call('POST', '/api/clients', {name: 'Example Client AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE', org_id: ORG});
  const mk = async title => {
    const q = await call('POST', '/api/office/docs', {kind: 'invoice', project_title: title, client_id: C.id, service_from: '2030-02-01', service_to: '2030-02-28'});
    await call('PUT', '/api/office/docs/' + q.id + '/items', {items: [{title: 'Shoot', qty: 1, rate: 900}]});
    const f = await call('POST', '/api/office/docs/' + q.id + '/finalize');
    check(f.locked === true && f.number, 'finalised ' + title + ' ' + JSON.stringify(f).slice(0, 200));
    return f;
  };
  const I1 = await mk('Desktop invoice'), I2 = await mk('Phone invoice');
  const open = async d => { const more = await until(() => d.querySelector('#view [data-ofd="more"]')); more?.click(); await until(() => items(d).length); return more; };

  for (const [inv, mobile, who] of [[I1, false, 'desktop'], [I2, true, 'phone']]) {
    const w = await boot({user: 'alice', hash: 'office/offers/' + inv.id, mobile}), d = w.document;
    w.__dialogs = 'manual';
    check(await open(d), `${who}: the invoice menu button`);
    check(names(d).length && !names(d).includes('Delete'), `${who}: a finalised invoice offers no Delete (#2604) ` + names(d).join(' | '));
    check(!!d.querySelector('#view [data-ofd="credit"]'), `${who}: the correction is the button "Credit note / cancel"`);
    check(!d.querySelector('.modal.cdlg #cdlg-in'), `${who}: no "type the number" dialog`);
    w.close();
  }
  // the row menu of the invoice list (right click) follows can_delete
  const w = await boot({user: 'alice', hash: 'office/invoices'}), d = w.document;
  const row = await until(() => d.querySelector(`.ofdrow[data-id="${I1.id}"]`), 60);
  check(!!row, 'the invoice row in the list');
  row?.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  check(await until(() => names(d).includes('Open')) && !names(d).includes('Delete'), 'row menu: no Delete ' + names(d).join(' | '));
  w.close();
  check((await call('DELETE', '/api/office/docs/' + I1.id + '?confirm_number=' + encodeURIComponent(I1.number))).status === 409, 'the server keeps it too (409)');

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
