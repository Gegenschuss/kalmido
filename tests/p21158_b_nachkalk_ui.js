// 2.1158.0 B UI test (#4566 B): the post-calculation of an accepted quotation. Own container (start.sh). Invented names only.
// kalmido-suite: fresh
// An accepted quotation with tasks shows "Post-calculation" next to "Create invoice"; a draft quotation does not. A click
// opens the preview: per position planned and actual (Edit: 6 h quoted, 8.25 h tracked; Concept a day position stays,
// marked "not by time"; Music licence has no task) and the sums; "Create invoice draft" opens the new invoice draft with
// the tracked hours. Played by a person WITHOUT an organisation (the personal office; freelancer-matrix: office).
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21158BUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'clients,office,collab,fields,time';
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['comments', 'collab']});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'a person without an organisation');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Studio Example', street: 'Hafenweg 1', zip: '20457', city: 'Hamburg', country: 'de', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Example Bank'}, lang: 'en'});
  const C = await call('POST', '/api/clients', {name: 'Example Client AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE'});
  const q = await call('POST', '/api/office/docs', {kind: 'offer', project_title: 'Film', client_id: C.id, items: [
    {kind: 'service', title: 'Concept', qty: 2, unit: 'day', rate: 800},
    {kind: 'service', title: 'Edit', qty: 6, unit: 'hour', rate: 95},
    {kind: 'service', title: 'Music licence', qty: 1, unit: 'flat', rate: 400}]});
  check(q.id, 'the quotation');
  const L = await call('POST', '/api/lists', {name: 'Film project', ptype: 'agency', time_tracking: true});
  await call('POST', `/api/office/docs/${q.id}/project`, {list_id: L.id});
  const pv = await call('GET', `/api/office/docs/${q.id}/tasks`);
  await call('POST', `/api/office/docs/${q.id}/tasks`, {pick: pv.rows.filter(x => x.title !== 'Music licence').map(x => x.key)});
  const ts = ((await call('GET', '/api/state')).tasks || []).filter(t => t.list_id === L.id);
  const tid = t => ts.find(x => x.title === t)?.id;
  check(tid('Edit') && tid('Concept'), 'the tasks from the quotation ' + ts.map(t => t.title).join());
  await call('POST', '/api/time/entries', {task_id: tid('Edit'), start: '2026-11-10T09:00', minutes: 495});  // 8.25 h
  await call('POST', '/api/time/entries', {task_id: tid('Concept'), start: '2026-11-11T09:00', minutes: 600});

  // a draft quotation: no button
  let w = await boot({user: 'alice', hash: 'office/offers/' + q.id}), d = w.document;
  check(await until(() => d.querySelector('.ofdhead [data-ofd="to-invoice"]')), 'the quotation opens');
  check(!d.querySelector('[data-ofd="postcalc"]'), 'a draft quotation: no "Post-calculation"');
  w.close();
  await call('POST', `/api/office/docs/${q.id}/status`, {status: 'accepted'});

  w = await boot({user: 'alice', hash: 'office/offers/' + q.id}); d = w.document;
  const btn = await until(() => d.querySelector('.ofdhead [data-ofd="postcalc"]'));
  check(btn && /Post-calculation/.test(btn.textContent) && d.querySelector('.ofdhead [data-ofd="to-invoice"]'), 'accepted: "Post-calculation" next to "Create invoice" ' + txt(btn));
  btn?.click();
  const md = await until(() => d.querySelector('.modal.opc-dlg'));
  check(!!md, 'the preview opens');
  const rowsOk = await until(() => md?.querySelectorAll('.opc-tab tbody tr').length >= 3);
  check(rowsOk, 'the preview shows the positions');
  const row = t => [...(md?.querySelectorAll('.opc-tab tbody tr') || [])].find(r => txt(r.querySelector('th')).startsWith(t));
  const cells = t => [...(row(t)?.querySelectorAll('td') || [])].map(txt);
  check(row('Edit')?.classList.contains('opc-time') && /^6\b/.test(cells('Edit')[0]) && /^8\.25\b/.test(cells('Edit')[1]) && /\+2\.25/.test(cells('Edit')[2]),
    'Edit: planned 6, actual 8.25, +2.25 ' + cells('Edit').join(' | '));
  check(row('Concept')?.classList.contains('opc-not_time') && /not by time/.test(txt(row('Concept'))) && /10 h tracked/.test(cells('Concept')[1]) && /^2\b/.test(cells('Concept')[1]),
    'Concept: a day position stays, marked not by time ' + txt(row('Concept')));
  check(/no task/.test(txt(row('Music licence'))), 'Music licence: no task ' + txt(row('Music licence')));
  const foot = txt(md?.querySelector('.opc-tab tfoot'));
  check(/2,?570\.00/.test(foot) && /2,?783\.75/.test(foot), 'the sums planned 2,570.00 / actual 2,783.75 ' + foot);
  md.querySelector('[data-m="ok"]')?.click();
  const opened = await until(() => /Invoice/.test(txt(d.querySelector('.ofdhead .ofdnum'))) && !d.querySelector('.modal.opc-dlg'));
  check(opened, 'the invoice draft opens ' + txt(d.querySelector('.ofdhead .ofdnum')));
  const id = +(w.location.hash.match(/(\d+)/) || [])[1];
  const inv = id ? await call('GET', `/api/office/docs/${id}`) : {};
  const it = (inv.items || []).find(x => x.title === 'Edit');
  check(inv.kind === 'invoice' && inv.status === 'draft' && it && +it.qty === 8.25 && +it.rate === 95, `the draft carries the tracked hours ${inv.kind} ${inv.status} ${it?.qty}`);
  const inputs = [...d.querySelectorAll('#view input')].map(x => x.value);
  check(inputs.some(v => /^8[.,]25$/.test(v)), 'the editor shows 8.25 h ' + inputs.slice(0, 12).join(' '));
  w.close();

  console.log(`p21158_b_nachkalk_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
