// 2.66.0 UI tests, part B (#1835 merging duplicate clients), own container (start.sh). jsdom, invented data only:
// - the selection bar of the clients has "Merge", active from two ticked clients
// - the dialog: the target first, a choice per differing field (phone), the contact persons joined; step 2 = the server's
//   overview and the note that the others are gone (30 days undo); Merge moves everything and opens the target
// - the toast with Undo brings the other client back; the client's card shows "Merged with ..." with Undo in its history
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,time'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  const C1 = (await call('POST', '/api/clients', {name: 'Nordwind GmbH', org_id: ORG, phone: '+49 30 1111', contacts: [{name: 'Anna Example', is_default: true}]})).id;
  const C2 = (await call('POST', '/api/clients', {name: 'Nordwind (duplicate)', org_id: ORG, phone: '+49 30 2222', email: 'dup@example.com', contacts: [{name: 'Ben Example'}]})).id;
  await call('POST', '/api/clients', {name: 'Other KG', org_id: ORG});
  check(C1 && C2, 'setup: three clients');

  // ================= selection bar + dialog
  let w = await boot({hash: 'clients'}); let d = w.document;
  await until(() => d.querySelectorAll('#view .msclients .ctrow').length === 3, 60);
  const crow = name => [...d.querySelectorAll('#view .msclients .ctrow')].find(x => x.textContent.includes(name));
  click(w, d.querySelector('[data-mscl="pick"]')); await sleep(50);
  crow('Nordwind GmbH').click(); await sleep(50);
  const mb = () => d.querySelector('#ct-sbar [data-clb="merge"]');
  check(mb() && mb().disabled && /Merge/.test(mb().textContent), 'bar: "Merge" waits for a second client');
  crow('Nordwind (duplicate)').click(); await sleep(50);
  check(mb() && !mb().disabled, 'bar: "Merge" active with two ticked clients');
  click(w, mb());
  const md = await until(() => d.querySelector('.modal.mgdlg'), 30);
  check(md && /Merge 2 clients/.test(md.querySelector('h3')?.textContent || ''), 'dialog: title with the count');
  const tgt = md && md.querySelector('input[name="mg-t"]:checked');
  check(tgt && +tgt.value === C1, 'dialog: the first ticked client is the target');
  const ph = md ? [...md.querySelectorAll('input[name="mg-f-phone"]')] : [];
  check(ph.length === 2, 'dialog: a choice for the differing phone numbers');
  check(/Ben Example/.test(md?.querySelector('.mgjoin')?.textContent || '') && /Anna Example/.test(md.querySelector('.mgjoin').textContent), 'dialog: the contact persons are joined');
  check(!md?.querySelector('input[name="mg-f-email"]'), 'dialog: no choice where only one client has a value (e-mail)');
  const p2 = ph.find(x => +x.value === C2);
  if (p2) { p2.checked = true; p2.dispatchEvent(new w.Event('change', {bubbles: true})); }
  click(w, md.querySelector('[data-m="next"]'));
  await until(() => md.querySelector('.mglines li'), 40);
  const lines = [...md.querySelectorAll('.mglines li')].map(x => x.textContent);
  check(lines.some(x => /1 contact person/.test(x)), 'step 2: the server overview ' + JSON.stringify(lines));
  check(/gone afterwards/.test(md.querySelector('.mgwarn')?.textContent || '') && /Nordwind \(duplicate\)/.test(md.querySelector('.mgwarn').textContent), 'step 2: the note names the client that goes');
  click(w, md.querySelector('[data-m="run"]'));
  await until(async () => (await call('GET', `/api/clients/${C2}`)).http === 404, 40);
  const t = await call('GET', `/api/clients/${C1}`);
  check(t.phone === '+49 30 2222' && t.email === 'dup@example.com' && t.contacts.length === 2, 'merged: the picked phone, the filled e-mail, both contact persons');
  await until(() => /2 clients merged/.test(d.querySelector('#toast')?.textContent || ''), 30);
  check(/2 clients merged/.test(d.querySelector('#toast')?.textContent || '') && d.querySelector('#toast button'), 'toast with Undo');
  await until(() => w.eval('S.route.client') === C1 && d.querySelector('#view .clmhist'), 40);
  const hs = d.querySelector('#view .clmhist');
  check(hs && /Merged with Nordwind \(duplicate\)/.test(hs.textContent) && hs.querySelector('[data-clm-undo]'), 'card: the target opens with the history line and Undo');
  // undo from the toast
  d.querySelector('#toast button')?.click();
  await until(async () => (await call('GET', `/api/clients/${C2}`)).http === 200, 40);
  const b = await call('GET', `/api/clients/${C2}`);
  check(b.http === 200 && b.phone === '+49 30 2222' && (await call('GET', `/api/clients/${C1}`)).phone === '+49 30 1111', 'toast Undo: the other client is back, the target as before');
  w.close();

  // ================= undo from the client's history
  const m = await call('POST', '/api/clients/merge', {target: C1, ids: [C2]});
  check(m.run_id, 'again: merged through the API');
  w = await boot({hash: `client/${C1}`}); d = w.document;
  const ub = await until(() => d.querySelector(`#view .clmhist [data-clm-undo="${m.run_id}"]`), 60);
  check(ub && /Undo/.test(ub.textContent), 'history: Undo next to the newest merge');
  if (ub) click(w, ub);
  await until(async () => (await call('GET', `/api/clients/${C2}`)).http === 200, 40);
  check((await call('GET', `/api/clients/${C2}`)).http === 200, 'history: Undo brings the client back');
  await until(() => /Merge undone/.test(d.querySelector('#toast')?.textContent || ''), 30);
  check(/Merge undone/.test(d.querySelector('#toast')?.textContent || ''), 'history: the toast says so');
  await until(() => d.querySelector('#view .clmhist') && !d.querySelector('#view .clmhist [data-clm-undo]'), 40);
  check(/undone/.test(d.querySelector('#view .clmhist')?.textContent || '') && !d.querySelector('#view .clmhist [data-clm-undo]'), 'history: the lines say undone, no Undo left');
  w.close();

  console.log(`p266_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
