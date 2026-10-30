// 2.299.0 E UI tests (#3194: an agent reads a receipt, proposal kind receipt_read; own container, start.sh). jsdom:
// - the document sheet: "Read with an agent" only while an agent of the office area may read it (switches on, the file
//   shared); the request dialog says that Kalmido sends nothing out; while the agent reads: one status line
// - the agent's values: "Read by the agent (name)" with Discard / Take over; Take over sets the amount (toast), Undo brings
//   the amount before back (one step)
// - the proposal card: the values as a table, the positions (shown only), Take over
// freelancer-matrix: office (alice works in her personal office, no organisation)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2299E_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n, ms = 150) => require('./boot').until(fn, {timeout: n ? n * ms : 15000, step: ms});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const upload = async (name, text) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const j = await r.json(); const id = (j.ids || [])[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 100, 200);
  return id;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents,office,clients,docs,files'});
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['read', 'office', 'files:read']});
  sql('UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?', [ag.id]);  // alice's personal agent (her personal office)
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call('GET', '/api/office/settings');
  const id = await upload('rechnung.txt', 'Beispiel Buerobedarf GmbH\nRechnung Nr. RE-2026-17\nGesamt 119,00 EUR\n');
  check(id > 0, 'setup: a receipt');
  await call('PATCH', `/api/docs/${id}`, {amount: '1.00'});

  // ================= the button in the document sheet
  let w = await boot({user: 'alice', hash: 'docs/' + id}), d = w.document;
  await until(() => d.querySelector('.dc-md'));
  check(!(await until(() => d.querySelector('[data-ast-ask="receipt_read"]'), 10)), '#3194: switches off, not shared: no button');
  w.close();
  check((await call('PATCH', `/api/office/agents/${ag.id}`, {office_drafts: true})).http === 200 && (await call('PUT', '/api/office/settings', {agents_read: 1})).http === 200
    && (await call('POST', `/api/files/nodes/${id}/shares`, {agent_id: ag.id, role: 'view'})).http === 201, 'setup: both office switches on, the file shared');
  w = await boot({user: 'alice', hash: 'docs/' + id}); d = w.document;
  const btn = await until(() => d.querySelector('[data-ast-ask="receipt_read"]'));
  check(btn && /Read with an agent/.test(btn.textContent) && btn.closest('.rx-slot'), '#3194: the button with the recognised values');
  click(w, btn);
  const ask = await until(() => d.querySelector('.ast-askm'));
  check(ask && /Kalmido sends nothing out/.test(ask.textContent) && !ask.querySelector('#ast-field'), '#3194: the dialog says nothing goes out');
  if (ask) click(w, ask.querySelector('[data-m="ok"]'));
  const job = await until(() => sql("SELECT id FROM agent_jobs WHERE kind='receipt_read' AND user_id=1")[0]);
  check(job && job.id, '#3194: the request');
  w.close();
  w = await boot({user: 'alice', hash: 'docs/' + id}); d = w.document;
  check(await until(() => /Claude is reading the receipt/.test(d.querySelector('.rcr-wait')?.textContent || '')), '#3194: while the agent reads: one status line');
  w.close();

  // ================= the values in the document sheet: Take over, Undo
  const sub = await call('POST', `/api/v1/agent/jobs/${job.id}/proposal`, {supplier: 'Beispiel Buerobedarf GmbH', invoice_no: 'RE-2026-17', gross: '119.00', vat_pct: '19',
    positions: [{text: 'Papier A4', qty: 10, net: '100.00'}]}, null, AGH);
  check(sub.http === 201, 'setup: the agent answers ' + sub.http);
  w = await boot({user: 'alice', hash: 'docs/' + id}); d = w.document;
  const line = await until(() => d.querySelector('.rcr-sug'));
  check(line && /Read by the agent \(Claude\)/.test(line.textContent) && /RE-2026-17/.test(line.textContent) && line.querySelector('[data-rcr^="apply:"]') && line.querySelector('[data-rcr^="discard:"]'),
    '#3194: "Read by the agent (Claude)" with the values, Discard / Take over');
  click(w, line?.querySelector('[data-rcr^="apply:"]'));
  check(await until(async () => (await call('GET', `/api/docs/${id}`)).amount === '119.00'), '#3194: Take over sets the amount');
  check(await until(() => /Values taken over/.test(d.querySelector('#toast, .toast')?.textContent || ''), 30), '#3194: the toast');
  check(await until(() => !d.querySelector('.rcr-sug')), '#3194: the line goes after taking over');
  await sleep(300);
  await w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', `/api/docs/${id}`)).amount === '1.00'), '#3194: Undo brings the amount back');
  w.close();

  // ================= the proposal card
  const j2 = await call('POST', '/api/proposals', {kind: 'receipt_read', agent_id: ag.id, doc_id: id});
  await call('POST', `/api/v1/agent/jobs/${j2.id}/proposal`, {supplier: 'Beispiel Buerobedarf GmbH', gross: '119.00', positions: [{text: 'Papier A4', qty: 10}]}, null, AGH);
  w = await boot({user: 'alice', hash: 'prop/' + j2.id}); d = w.document;
  const md = await until(() => d.querySelector('.ppm .rcr-tab') && d.querySelector('.ppm'));
  check(md && /Proposal by Claude/.test(md.textContent) && /Beispiel Buerobedarf GmbH/.test(md.querySelector('.rcr-tab')?.textContent || '')
    && /1 position/.test(md.querySelector('.rcr-pos summary')?.textContent || '') && md.querySelector('[data-pp="apply"]') && !md.querySelector('.ppi'),
  '#3194: the card: the values, the positions, Take over, no entry list');
  click(w, md?.querySelector('[data-pp="apply"]'));
  check(await until(async () => (await call('GET', `/api/docs/${id}`)).amount === '119.00'), '#3194: Take over from the card');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
