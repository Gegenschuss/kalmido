// kalmido-suite: fresh
// 2.469.0 (#3749) UI test: a connected agent reads a credit card statement, own container (start.sh), jsdom. An invented statement.
// freelancer-matrix: office
// - a statement no reader could read: "Read with an agent" while an agent may read it, the dialog says nothing goes out
// - while the agent reads: one status line; its proposal: the positions on the sheet, a merchant with HTML stays text
// - Take over: the positions in the statement, still "Confirm positions"; Undo takes them back
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(CK ? {Cookie: CK} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const pdf = lines => {  // a PDF with a text layer, hand-written
  const stream = `BT /F1 10 Tf 12 TL 40 760 Td\n${lines.map(x => `(${x}) Tj T*`).join('\n')}\nET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  return out + `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
};
const openSheet = async (w, d) => {
  const card = await until(() => d.querySelector('[data-cc="card"]'));
  click(w, card);
  const st = await until(() => d.querySelector('[data-cc="stmt"]'));
  click(w, st);
  return !!(await until(() => d.querySelector('[data-cc="confirm"]')));
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents,office,clients,docs,files'});
  const me = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['read', 'office', 'files:read']});
  sql('UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?', [ag.id]);  // alice's personal agent (her personal office)
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call('GET', '/api/office/settings');
  await call('PATCH', `/api/office/agents/${ag.id}`, {office_drafts: true});
  await call('PUT', '/api/office/settings', {agents_read: 1});
  const card = await call('POST', '/api/office/cards', {holder_id: me.id, last4: '4711'});
  const fd = new FormData(); fd.append('file', new Blob([pdf(['Dieses Blatt hat keine Positionen'])], {type: 'application/pdf'}), 'stmt.pdf'); fd.append('month', '2025-03');
  const up = await (await fetch(B + `api/office/cards/${card.id}/statements`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json();
  const s = up.statement;
  check(s && up.read === false, 'setup: a statement no reader could read');
  check((await call('POST', `/api/files/nodes/${s.node_id}/shares`, {agent_id: ag.id, role: 'view'})).http === 201, 'setup: the PDF shared with the agent');

  let w = await boot({user: 'alice', hash: 'office/cards'}), d = w.document;
  check(await openSheet(w, d), 'the statement sheet');
  const btn = await until(() => d.querySelector('[data-ast-ask="card_statement_read"]'));
  check(btn && /Read with an agent/.test(btn.textContent), '#3749: the button on a statement without positions');
  click(w, btn);
  const ask = await until(() => d.querySelector('.ast-askm'));
  check(ask && /Kalmido sends nothing out/.test(ask.textContent), '#3749: the dialog says nothing goes out');
  if (ask) click(w, ask.querySelector('[data-m="ok"]'));
  const job = await until(() => sql("SELECT id FROM agent_jobs WHERE kind='card_statement_read' AND user_id=1")[0]);
  check(job && job.id, '#3749: the request');
  w.close();

  w = await boot({user: 'alice', hash: 'office/cards'}); d = w.document;
  await openSheet(w, d);
  check(await until(() => /Claude is reading the statement/.test(d.body.textContent)), '#3749: while the agent reads: one status line');
  w.close();

  const sub = await call('POST', `/api/v1/agent/jobs/${job.id}/proposal`, {total: '42.50', lines: [{day: '2025-03-02', merchant: 'Hotel Beispiel', amount: '40.00'},
    {day: '2025-03-03', merchant: '<img src=x id=boese onerror=alert(1)>', amount: '2.50'}]}, AGH);
  check(sub.http === 201, 'setup: the agent answers ' + sub.http);
  w = await boot({user: 'alice', hash: 'prop/' + job.id}); d = w.document;
  const md = await until(() => d.querySelector('.ppm .rcr-tab') && d.querySelector('.ppm'));
  check(md && /Proposal by Claude/.test(md.textContent) && /Hotel Beispiel/.test(md.textContent) && /2 positions/.test(md.textContent) && md.querySelector('[data-pp="apply"]'), '#3749: the card: the positions, Take over');
  check(md && /<img src=x/.test(md.textContent) && !d.querySelector('#boese'), '#3749: a merchant with HTML stays text');
  click(w, md?.querySelector('[data-pp="apply"]'));
  check(await until(async () => (await call('GET', `/api/office/cards/statements/${s.id}`)).lines?.length === 2), '#3749: Take over adds the positions');
  const t = await call('GET', `/api/office/cards/statements/${s.id}`);
  check(t.statement.state === 'draft' && t.statement.total === '42.50', '#3749: still a draft the person confirms');
  check(await until(() => /Positions applied/.test(d.querySelector('#toast, .toast')?.textContent || '')), '#3749: the toast');
  await sleep(300);
  await w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', `/api/office/cards/statements/${s.id}`)).lines?.length === 0), '#3749: Undo takes them back');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
