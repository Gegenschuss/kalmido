// 2.162.0 part A UI test (#2603), own container (start.sh): test phase - the "More" menu of a finalised, sent invoice offers
// "Delete" to the admin; the app's own dialog names the number gap and that it was sent, asks for the number and keeps
// Delete off until the typed number matches (a wrong one: still off); the right number deletes it. Desktop and the phone
// width (mobile). Invented names only. P2162AUI_NOSTART=1 = the server already runs.
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
    check(names(d).includes('Delete'), `${who}: a finalised invoice offers Delete (test phase) ` + names(d).join(' | '));
    items(d).find(b => b.textContent.trim() === 'Delete')?.click();
    const md = await until(() => d.querySelector('.modal.cdlg #cdlg-in') && d.querySelector('.modal.cdlg'));
    check(!!md, `${who}: the app's own dialog with an input (no window.prompt)`);
    const txt = md?.textContent || '';
    check(txt.includes(inv.number) && /gap in the office log/.test(txt), `${who}: the dialog names the number and the gap ` + txt.slice(0, 200));
    check(/Type the number to confirm/.test(txt), `${who}: asks for the number`);
    const inp = md?.querySelector('#cdlg-in'), yes = md?.querySelector('[data-cd="yes"]');
    check(yes?.disabled === true, `${who}: Delete is off while nothing is typed`);
    const type = v => { inp.value = v; inp.dispatchEvent(new w.Event('input', {bubbles: true})); };
    type(inv.number + '9');
    check(yes?.disabled === true, `${who}: a wrong number keeps Delete off`);
    type(inv.number);
    check(yes?.disabled === false, `${who}: the right number switches Delete on`);
    md.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
    check(await until(async () => (await fetch(B + 'api/office/docs/' + inv.id, {headers: {...H, Cookie: CK}})).status === 404, 60), `${who}: the invoice is deleted`);
    w.close();
  }
  const log = (await call('GET', '/api/office/log?limit=20')).log || [];
  check(log.some(x => x.action === 'delete' && x.detail?.testphase && x.detail?.number === I1.number), 'the office log has the test phase delete');
  // the office log in the settings reads "Invoice X deleted in the test phase"
  const w = await boot({user: 'alice', hash: 'office/settings'}), d = w.document;
  const btn = await until(() => d.querySelector('[data-ofc="log"]'), 60);
  btn?.click();
  check(await until(() => (d.querySelector('.ofdlog')?.textContent || '').includes('Invoice ' + I1.number + ' deleted in the test phase'), 60),
    'the office log line: "Invoice X deleted in the test phase" ' + (d.querySelector('.ofdlog')?.textContent || '').slice(0, 200));
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
