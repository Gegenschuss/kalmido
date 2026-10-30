// 2.435.0 UI tests, part A (#3600), own container (start.sh, mode workspaces). jsdom, invented data only:
// - the blocks of the client card fold at their title: open by default details, contact persons, open invoices; folded with
//   their number in the title projects ("Projects (2)"), time tracking, documents, letters (now a block of their own)
// - a person folds a block open / closed and hides one: kept per person (view_clients) after a reload, alike for every client
// - the office admin switches a block off under Office > Settings > Functions > Client card: it is gone at every client of
//   the office, for the members too; an unknown block is refused
// - a freelancer without an organisation is the admin of their own office: the switch works for their private clients
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});  // KMT_NOSTART=1: a running app
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const keys = d => [...d.querySelectorAll('#view .msclcard .lyb[data-lyk]')].map(x => x.dataset.lyk);
const foldBtn = (d, k) => d.querySelector(`#view [data-mscl="fold"][data-k="${k}"]`);
const saved = async (ck = CK) => { const v = (await call('GET', '/api/state', null, ck)).settings?.view_clients || ''; return v ? JSON.parse(v) : {}; };
const FEAT = 'cal,comments,collab,contacts,office,clients,time';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'contacts']});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  await call('POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CB = await login('bob'), CC = await login('carol');
  for (const ck of [CK, CB, CC]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ck);
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CK, CB]) await call('PATCH', '/api/settings', {workspace: `org:${ORG}`}, ck);
  await call('PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Beispiel Studio GmbH', city: 'Musterstadt', country: 'DE'}});
  const CL = await call('POST', '/api/clients', {name: 'Kunde Eins GmbH', org_id: ORG, email: 'kunde@example.com', note: 'Eine Notiz', contacts: [{name: 'Maria Test', email: 'maria@example.com'}]});
  const CL2 = await call('POST', '/api/clients', {name: 'Kunde Zwei AG', org_id: ORG});
  check(CL.http < 300 && CL2.http < 300, 'two clients ' + [CL.http, CL2.http]);
  for (const n of ['Website', 'Broschüre']) {
    const l = await call('POST', '/api/lists', {name: n, org_id: ORG});
    await call('PATCH', `/api/lists/${l.id}`, {client_id: CL.id});
  }

  // ================= the defaults: open / folded with the number
  let w = await boot({user: 'alice', hash: 'client/' + CL.id}), d = w.document;
  await until(() => foldBtn(d, 'lists') && foldBtn(d, 'letters'));
  check(foldBtn(d, 'details')?.getAttribute('aria-expanded') === 'true' && d.querySelector('#view .ctfields'), '#3600: details open by default');
  check(foldBtn(d, 'persons')?.getAttribute('aria-expanded') === 'true' && /Maria Test/.test(d.querySelector('#view .lyb[data-lyk="persons"]')?.textContent || ''), '#3600: contact persons open by default');
  const lt = foldBtn(d, 'lists')?.textContent || '';
  check(foldBtn(d, 'lists').getAttribute('aria-expanded') === 'false' && /Projects\s*\(2\)/.test(lt) && !d.querySelector('#view .cltable'), '#3600: projects folded with the number in the title: ' + lt);
  check(foldBtn(d, 'month')?.getAttribute('aria-expanded') === 'false' && !d.querySelector('#view .sttiles'), '#3600: time tracking folded');
  check(/Letters\s*\(0\)/.test(foldBtn(d, 'letters').textContent) && foldBtn(d, 'letters').getAttribute('aria-expanded') === 'false', '#3600: letters a block of their own, folded: ' + foldBtn(d, 'letters').textContent);
  check(keys(d).includes('gendocs') ? foldBtn(d, 'gendocs').getAttribute('aria-expanded') === 'false' : true, '#3600: documents folded');

  // ================= fold open / closed, hide: kept per person
  click(w, foldBtn(d, 'lists'));
  await until(() => d.querySelector('#view .cltable'));
  check(foldBtn(d, 'lists')?.getAttribute('aria-expanded') === 'true' && /Website/.test(d.querySelector('#view .cltable')?.textContent || ''), '#3600: projects fold open');
  click(w, foldBtn(d, 'details'));
  await until(() => !d.querySelector('#view .ctfields'));
  check(foldBtn(d, 'details')?.getAttribute('aria-expanded') === 'false' && !d.querySelector('#view .ctfields'), '#3600: details fold closed');
  let v = await until(async () => { const x = await saved(); return x.opts?.lists?.open === true && x.opts?.details?.open === false ? x : null; });
  check(v, '#3600: the folds are stored per person ' + JSON.stringify(v));
  click(w, d.querySelector('#view [data-act="wg-more"][data-k="month"]'));
  const hide = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /^Hide/.test(b.textContent.trim())));
  if (hide) click(w, hide);
  v = await until(async () => { const x = await saved(); return (x.hidden || []).includes('month') ? x : null; });
  check(v && !keys(d).includes('month'), '#3600: hiding time tracking is stored');
  w.close();
  w = await boot({user: 'alice', hash: 'client/' + CL2.id}); d = w.document;
  await until(() => foldBtn(d, 'lists'));
  check(foldBtn(d, 'lists').getAttribute('aria-expanded') === 'true' && foldBtn(d, 'details').getAttribute('aria-expanded') === 'false' && !keys(d).includes('month'),
    '#3600: after a reload, at another client: the same folds and hidden blocks ' + keys(d));
  w.close();

  // ================= the office admin switches a block off for the office
  w = await boot({user: 'alice', hash: 'office/settings', ls: {'tasks.ofcSetSub': '"functions"'}}); d = w.document;
  const sw = await until(() => d.querySelector('#ofc-set [data-ccb="lists"]'), 80);
  check(sw && sw.checked && !d.querySelector('#ofc-set [data-ccb="details"]'), '#3600: Settings > Functions has the client card switches (details always shows)');
  if (sw) { sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const st = await until(async () => { const s = (await call('GET', '/api/office/settings')).settings || {}; return (s.client_blocks_off || []).includes('lists') ? s : null; });
  check(st && st.client_blocks_off.join() === 'lists', '#3600: the switch saves client_blocks_off ' + JSON.stringify(st?.client_blocks_off));
  w.close();
  check((await call('GET', `/api/clients/${CL.id}`)).blocks_off?.join() === 'lists', '#3600: the client says which blocks are off');
  check((await call('PUT', '/api/office/settings', {client_blocks_off: ['nope']})).http === 400, '#3600: an unknown block is refused');
  for (const [u, ck] of [['alice', CK], ['bob', CB]]) {
    w = await boot({user: u, hash: 'client/' + CL.id}); d = w.document;
    await until(() => foldBtn(d, 'persons'));
    check(foldBtn(d, 'persons') && !keys(d).includes('lists') && !foldBtn(d, 'lists'), `#3600: ${u}: the switched off block is gone ` + keys(d));
    check(!w.eval(`lyBlocks('clients').some(b => b[0] === 'lists')`), `#3600: ${u}: and no block to bring back`);
    w.close();
    void ck;
  }
  await call('PUT', '/api/office/settings', {client_blocks_off: []});
  check(!(await call('GET', `/api/clients/${CL.id}`)).blocks_off?.length, '#3600: switched on again');

  // ================= a freelancer without an organisation: their own office admin
  const PC = await call('POST', '/api/clients', {name: 'Privatkunde Solo', org_id: null}, CC);
  check(PC.http < 300 && PC.org_id == null, 'carol: a private client ' + PC.http);
  const ps = await call('PUT', '/api/office/settings', {client_blocks_off: ['lists', 'month']}, CC);
  check(ps.http < 300, 'carol: the own office takes the switch ' + ps.http);
  check((await call('GET', `/api/clients/${PC.id}`, null, CC)).blocks_off?.join() === 'month,lists', '#3600: P4: the private client says which blocks are off');
  w = await boot({user: 'carol', hash: 'client/' + PC.id}); d = w.document;
  await until(() => foldBtn(d, 'details'));
  check(foldBtn(d, 'details')?.getAttribute('aria-expanded') === 'true' && !keys(d).includes('lists') && !keys(d).includes('month'), '#3600: P4: carol\'s card without the blocks she switched off ' + keys(d));
  w.close();

  console.log(`p2435_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
