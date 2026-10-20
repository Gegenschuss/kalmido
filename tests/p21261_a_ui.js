// 2.126.1 UI tests of part A (#2123 #2124: texts worded by a connected agent; own container, start.sh). jsdom:
// - an office quotation draft: "Draft text with an agent" under Introduction and closing only while an agent of the area may
//   draft and the area lets agents read office data; a sent quotation: no button; the request dialog sends the wish
// - the proposal card: who proposes it, the text in an editable field, Copy / Discard (👎) / Take over, no entry list;
//   Take over writes the edited text into the draft (toast), Undo brings the old text back (one step)
// - the status report dialog: "Word the report with an agent" only for a list shared with the agent; a text taken over
//   replaces the fixed text in the preview, one click shows the fixed text again
// - the document sheet shows a summary taken over
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21261A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,agents,office,clients,docs,files'});
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['read', 'write', 'office']});
  sql('UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?', [ag.id]);  // alice's personal agent (her personal office)
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call('GET', '/api/office/settings');
  const cl = await call('POST', '/api/clients', {name: 'Musterfirma GmbH'});
  const q = await call('POST', '/api/office/docs', {client_id: cl.id, project_title: 'Imagefilm'});
  await call('PATCH', `/api/office/docs/${q.id}`, {intro: 'Alte Einleitung'});
  const q2 = await call('POST', '/api/office/docs', {client_id: cl.id, project_title: 'Gesendet'});
  check(q.http === 201 && q2.http === 201, 'setup: two quotation drafts');
  await call('POST', `/api/office/docs/${q2.id}/status`, {status: 'sent'});

  // ================= the button in the office draft
  let w = await boot({user: 'alice', hash: 'office/offers/' + q.id}), d = w.document;
  check(await until(() => d.querySelector('#ofd-intro')) && !(await until(() => d.querySelector('[data-ast-ask]'), 10)), '#2123: switches off: no button');
  w.close();
  check((await call('PATCH', `/api/office/agents/${ag.id}`, {office_drafts: true})).http === 200 && (await call('PUT', '/api/office/settings', {agents_read: 1})).http === 200,
    'setup: both office switches on');
  w = await boot({user: 'alice', hash: 'office/offers/' + q.id}); d = w.document;
  const btn = await until(() => d.querySelector('[data-ast-ask="office_text"]'));
  check(btn && /Draft text with an agent/.test(btn.textContent) && btn.closest('.ofdsec'), '#2123: the button in Introduction and closing');
  click(w, btn);
  const ask = await until(() => d.querySelector('.ast-askm'));
  check(ask && ask.querySelector('#ast-field') && /Claude writes a draft/.test(ask.textContent) && !ask.querySelector('#ast-agent'), '#2123: the dialog: one agent = no choice, the text to word');
  if (ask) {
    ask.querySelector('#ast-wish').value = 'freundlich, kurz';
    ask.querySelector('#ast-field').value = 'intro';
    click(w, ask.querySelector('[data-m="ok"]'));
  }
  const job = await until(() => sql("SELECT id, input FROM agent_jobs WHERE kind='office_text' AND user_id=1")[0]);
  check(job && JSON.parse(job.input).wish === 'freundlich, kurz' && JSON.parse(job.input).field === 'intro', '#2123: the request with the wish ' + JSON.stringify(job || {}).slice(0, 200));
  w.close();
  w = await boot({user: 'alice', hash: 'office/offers/' + q2.id}); d = w.document;
  await until(() => d.querySelector('.ofdhead'));
  await sleep(500);
  check(!d.querySelector('[data-ast-ask]'), '#2123: a sent quotation: no button');
  w.close();

  // ================= the card
  const sub = await call('POST', `/api/v1/agent/jobs/${job.id}/proposal`, {field: 'intro', text: 'Vielen Dank für Ihre Anfrage.'}, null, AGH);
  check(sub.http === 201, 'setup: the agent answers ' + sub.http);
  w = await boot({user: 'alice', hash: 'prop/' + job.id}); d = w.document;
  const md = await until(() => d.querySelector('.ppm .ast-head') && d.querySelector('.ppm'));
  const ta = md?.querySelector('#ast-text');
  check(/Proposal by Claude/.test(md?.textContent || '') && ta && ta.value === 'Vielen Dank für Ihre Anfrage.', "#2123: the card: who proposes it, the agent's text in a field");
  check(md && md.querySelector('[data-ast-copy]') && /Take over/.test(md.querySelector('[data-pp="apply"]')?.textContent || '') && !!md.querySelector('[data-pp="discard"] .thumb svg')  /* 2.139.0 (#2401): app thumb */
    && !md.querySelector('.ppi') && /Alte Einleitung/.test(md.querySelector('.ast-was')?.textContent || ''), '#2123: Copy / Take over / Discard, the current text, no entry list');
  if (ta) ta.value = 'Vielen Dank für Ihre Anfrage, gern bieten wir an.';
  click(w, md?.querySelector('[data-pp="apply"]'));
  check(await until(async () => (await call('GET', `/api/office/docs/${q.id}`)).intro === 'Vielen Dank für Ihre Anfrage, gern bieten wir an.'), '#2123: Take over writes the edited text');
  check(await until(() => /Text taken over into the draft/.test(d.querySelector('#toast, .toast')?.textContent || ''), 30), '#2123: the toast');
  await sleep(300);
  await w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', `/api/office/docs/${q.id}`)).intro === 'Alte Einleitung'), '#2123: Undo brings the old text back');
  w.close();

  // ================= the status report dialog
  const L = await call('POST', '/api/lists', {name: 'Imagefilm Projekt'});
  const L2 = await call('POST', '/api/lists', {name: 'Nicht geteilt'});
  await call('POST', '/api/tasks', {list_id: L.id, title: 'Drehbuch schreiben'});
  await call('PUT', `/api/lists/${L.id}/members`, {user_id: ag.id, role: 'edit'});
  w = await boot({user: 'alice'}); d = w.document;
  w.rptModal(L2.id);
  await until(() => d.querySelector('.rptmodal #rpt-prev .md, .rptmodal #rpt-prev h1') || /Status report/.test(d.querySelector('.rptmodal #rpt-prev')?.textContent || ''));
  await sleep(400);
  check(!d.querySelector('.rptmodal [data-ast-ask]'), '#2124: a list not shared with the agent: no button');
  d.querySelector('.rptmodal')?.remove();
  w.rptModal(L.id);
  const rb = await until(() => d.querySelector('.rptmodal [data-ast-ask="report"]'));
  check(rb && /Word the report with an agent/.test(rb.textContent), '#2124: the button in the status report dialog');
  d.querySelector('.rptmodal')?.remove();
  const jr = await call('POST', '/api/proposals', {kind: 'report', agent_id: ag.id, list_id: L.id, days: 7});
  check(jr.http === 201, 'setup: a report request ' + jr.http);
  await call('POST', `/api/v1/agent/jobs/${jr.id}/proposal`, {text: '# Wochenbericht\n\nDas Drehbuch ist in Arbeit.'}, null, AGH);
  await call('POST', `/api/proposals/${jr.id}/apply`, {select: ['0']});
  w.rptModal(L.id);
  const prev = await until(() => /Wochenbericht/.test(d.querySelector('.rptmodal #rpt-prev')?.textContent || '') && d.querySelector('.rptmodal #rpt-prev'));
  check(prev && d.querySelector('.rptmodal .ast-rptnote'), "#2124: the text taken over replaces the fixed text, with a note");
  click(w, d.querySelector('.rptmodal [data-ast-rpt="toggle"]'));
  check(await until(() => /Status report/.test(d.querySelector('.rptmodal #rpt-prev')?.textContent || '') && !/Wochenbericht/.test(d.querySelector('.rptmodal #rpt-prev')?.textContent || '')),
    '#2124: one click shows the fixed text again');
  d.querySelector('.rptmodal')?.remove();

  // ================= the document sheet: a summary taken over
  const html = w.ast_docSlot({id: 9, summary: 'Hotelrechnung über zwei Nächte', role: 'edit'});
  check(/Hotelrechnung über zwei Nächte/.test(html) && /ast-sum/.test(html), '#2123: the document sheet shows the summary');
  check(w.ast_docSlot({id: 9, summary: '', role: 'view'}) === '', '#2123: read only, no summary: nothing');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
