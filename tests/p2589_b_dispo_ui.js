// 2.589.0 B UI test (#4571): shoot days of a quotation in the disposition. Own container (start.sh). The preview of
// kalmido-suite: fresh
// "Create tasks" shows the shoot part as a shoot day (its date from the period of service, "2 × Camera" open places, ticked);
// applying pencils it in; the disposition shows the group "Open places" with a row per crew function, the booking sheet fills
// a place with a person (Undo opens it again). The module off: the preview shows only the hint. Invented names only.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2589BUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'clients,office,collab,fields,time,workload,dispo';
const dstr = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments', 'collab']});
  const st0 = await call('GET', '/api/state'), ORG = st0.me.workspaces[0].id, ME = st0.me.id;
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'org:' + ORG});
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Studio Example GmbH', street: 'Hafenweg 1', zip: '20457', city: 'Hamburg', country: 'de', tax_number: '12/345/67890', vat_id: 'DE999999999', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Example Bank'}, lang: 'en', industry_packs: ['film']});
  const CAM = (await call('POST', '/api/office/crew', {name_de: 'Kamera', name_en: 'Camera', rate_day: 650, intext: 'intern'})).id;
  const C = await call('POST', '/api/clients', {name: 'Example Client AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE', org_id: ORG});
  const t = new Date(), D1 = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 8)), D2 = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 9));
  const q = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Spot', client_id: C.id, service_from: D1, items: [{kind: 'service', title: 'Concept', qty: 1, unit: 'day', rate: 800}]});
  const p = await call('POST', `/api/office/docs/${q.id}/parts`, {kind: 'shoot', title: 'Shoot Harbour'});
  const sh = await call('PATCH', `/api/office/docs/${q.id}/parts/${p.part?.id}`, {sheet: {head: {shoot_days: 2}, staff: [{role_id: CAM, qty: 2}]}});
  check(q.id && p.part?.id && sh.id === q.id && CAM, 'setup: a quotation with a shoot part ' + JSON.stringify(sh).slice(0, 160));

  // ================= the preview: the shoot day with its date and places
  let w = await boot({user: 'alice', hash: 'office/offers/' + q.id}), d = w.document;
  (await until(() => d.querySelector('#view [data-dpj="tasks"]')))?.click();
  let md = await until(() => d.querySelector('.modal.otkdlg .otkdtbl'));
  md = md?.closest('.modal');
  const rows = [...(md?.querySelectorAll('.otkdtbl tbody tr') || [])];
  check(rows.length === 1 && /Shoot Harbour/.test(rows[0].textContent) && /Open places: 2 × Camera/.test(rows[0].textContent) && /2 days/.test(rows[0].textContent),
    'one shoot day, two open camera places, two days: ' + rows.map(r => r.textContent.replace(/\s+/g, ' ').trim()).join(' | '));
  check(md?.querySelector('#otkd-0-d')?.value === D1 && md?.querySelector('[data-otkdp]')?.checked, 'the date from the period of service, ticked ' + md?.querySelector('#otkd-0-d')?.value);
  md?.querySelector('[data-m="ok"]')?.click();
  const booked = await until(async () => { const j = await call('GET', `/api/team/dispo?start=${D1}&days=7`); return (j.bookings || []).filter(b => b.offer).length === 2 && j; });
  check(booked && booked.bookings.every(b => b.kind === 'slot' && b.status === 'option' && b.start === D1 && b.end === D2 && b.slot === 'Camera'), 'pencilled in: two open places ' + JSON.stringify(booked?.bookings));
  w.close();

  // ================= the disposition: open places, fill one
  w = await boot({user: 'alice', hash: 'workload'}); d = w.document;
  (await until(() => d.querySelector('#view .ab2tabs [data-v="dispo"]')))?.click();
  await until(() => d.querySelector('#view [data-act="dp-new"]'));
  w.eval(`DPV.start = '${D1}'; dp_reload()`);
  await until(() => d.querySelector('#view .dptable') && w.eval('DPV.data && DPV.data.start') === D1);
  const grp = [...d.querySelectorAll('#view .dptable .dpgrp th')].map(x => x.textContent);
  check(grp[0] === 'Open places' && [...d.querySelectorAll('#view .dptable th[scope="row"]')].some(x => x.textContent.includes('Camera')), 'the group Open places with the row Camera ' + grp.join());
  (await until(() => d.querySelector('#view .dptable .dpbk.slot')))?.click();
  const em = await until(() => d.querySelector('.dpmd'));
  const sels = [...(em?.querySelectorAll('.dpfill') || [])];
  check(sels.length === 2 && [...em.querySelectorAll('.dpjobres li')].every(li => /Open: Camera/.test(li.textContent)), 'the sheet: two open places to fill');
  const bid = +(sels[0]?.dataset.id || 0);
  if (sels[0]) { sels[0].value = `user:${ME}`; sels[0].dispatchEvent(new w.Event('change', {bubbles: true})); }
  const filled = await until(async () => { const j = await call('GET', `/api/team/dispo?start=${D1}&days=7`); const b = (j.bookings || []).find(x => x.id === bid); return b && b.kind === 'user' ? b : null; });
  check(filled && filled.rid === ME && filled.slot === 'Camera', 'the place filled with Alice, its function kept ' + JSON.stringify(filled));
  await until(() => [...d.querySelectorAll('#view .dpres span, #view .dpbk')].length);
  await w.eval("histStep('undo')");
  check(await until(async () => { const j = await call('GET', `/api/team/dispo?start=${D1}&days=7`); return (j.bookings || []).find(x => x.id === bid)?.kind === 'slot'; }), 'Undo opens the place again');
  w.close();

  // ================= the module off: only the hint
  await call('PATCH', '/api/settings', {features: 'clients,office,collab,fields,time,workload'});
  w = await boot({user: 'alice', hash: 'office/offers/' + q.id}); d = w.document;
  (await until(() => d.querySelector('#view [data-dpj="tasks"]')))?.click();
  const md3 = await until(() => d.querySelector('.modal.otkdlg'));
  check(md3 && await until(() => md3.querySelector('.otkdhint')) && !md3.querySelector('.otkdtbl') && /Disposition/.test(md3.querySelector('.otkdhint')?.textContent || ''),
    'module off: a hint, no shoot days ' + md3?.querySelector('.otkdhint')?.textContent);
  w.close();

  console.log(`p2589_b_dispo_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
