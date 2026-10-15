// 2.47.0 UI tests, part C (#1216): the shoot calculation sheet editor (static/js/office_sheet.js), own container in mode
// workspaces (start.sh), jsdom, invented crew and figures only:
// - the office settings show the switch "Industry pack Film & Video" and save industry_packs
// - the quotation editor shows a part of kind 'shoot' with the sheet (.dksheet, rendered by the parts editor of #1215)
// - the sheet: head values, crew rows with the people count, preparation tick, markup (admin); a change is saved on the
//   server and the figures come back; "Add crew" picks a role from the crew master data; set days other than the shoot
//   days show the note; additional costs can be added; the sums show the net, admins also third-party costs and surplus
// - a member sees no markup field, no intern / extern and no third-party costs / surplus
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (el.type === 'checkbox') el.checked = !!v; else el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const partOf = j => Array.isArray(j?.parts) ? j.parts.filter(p => p.kind === 'shoot').at(-1) : (j?.part || j);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal', 'comments']});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'});
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients', workspace: `org:${ORG}`}, BK);

  // ================= the switch in the office settings
  let w = await boot({hash: 'office/settings'}); let d = w.document;
  const sw = await until(() => d.querySelector('#os-ind-film'), 60);
  check(sw && !sw.checked && /Film & Video/.test(sw.closest('label')?.textContent || ''), 'settings: the switch Film & Video, off');
  w.close();
  const st = await call('PUT', '/api/office/settings', {industry_packs: ['film']});
  check(st.http === 200 && (st.settings || {}).industry_packs?.[0] === 'film', 'settings: pack on');

  // ================= master data + a quotation with a shoot part
  const cam = await call('POST', '/api/office/crew', {name_de: 'Kamera', name_en: 'Camera', rate_day: 650, intext: 'intern'});
  const lig = await call('POST', '/api/office/crew', {name_de: 'Beleuchter', name_en: 'Lighting', rate_day: 350, intext: 'extern', markup_pct: 10});
  const e1 = await call('POST', '/api/office/equipment', {name: 'Kamera-Set', name_en: 'Camera kit', daily_rate: 400});
  const SET = (await call('POST', '/api/office/sets', {name: 'Interview', discount_pct: 20, items: [{equipment_id: e1.id, qty: 1}]})).id;
  const DOC = (await call('POST', '/api/office/docs', {})).id;
  let P = partOf(await call('POST', `/api/office/docs/${DOC}/parts`, {kind: 'shoot', title: 'Shooting'}));
  const PID = P?.id;
  check(PID, 'a shoot part');
  P = partOf(await call('PATCH', `/api/office/docs/${DOC}/parts/${PID}`, {sheet: {head: {shoot_days: 1, travel_days: 1, prep_days: 0.5, nights: 0},
    staff: [{role_id: cam.id, qty: 1, prep: 1}, {role_id: lig.id, qty: 1, prep: 0}], set: {set_id: SET}, discount_pct: 0}}));
  check(P?.calc?.net, 'the sheet computes: ' + P?.calc?.net);

  // ================= the editor (admin)
  w = await boot({hash: `office/offers/${DOC}`}); d = w.document;
  await until(() => w.eval('OFD.doc && OFD.doc.id') === DOC, 60);
  // the parts editor of #1215 renders the sheet; open the part when it is shown as a row first
  let sheet = await until(() => d.querySelector(`.dksheet[data-pid="${PID}"]`), 20);
  if (!sheet) { const opener = d.querySelector(`[data-part="${PID}"], [data-pid="${PID}"]:not(.dksheet)`); if (opener) { click(w, opener); sheet = await until(() => d.querySelector(`.dksheet[data-pid="${PID}"]`), 40); } }
  check(sheet, 'the quotation editor shows the shoot sheet');
  if (!sheet) {  // keep testing the sheet itself with the editor functions on the page
    const box = d.createElement('div'); d.querySelector('#view').appendChild(box);
    const part = partOf(await call('GET', `/api/office/docs/${DOC}`)) || P;
    box.innerHTML = w.dkSheetHtml(part, w.eval('OFD.doc'), true); w.dkSheetBind(box, part);
    sheet = box.querySelector('.dksheet');
  }
  const root = sheet.parentElement;
  // 2.47.0: the live sheet -- loading master data (the crew picker) draws the office view again and replaces the box
  const S = () => d.querySelector(`.tpsheet .dksheet[data-pid="${PID}"]`) || root.querySelector('.dksheet');
  await sleep(300);  // the editor wires the sheet right after drawing it
  check(S().querySelectorAll('[data-dk^="head."]').length === 13, 'head: 13 values');
  check(S().querySelectorAll('[data-dk$=".qty"][data-dk^="staff."]').length === 2, 'two crew rows');
  check(S().querySelector('[data-dk="staff.1.markup_pct"]')?.value === '10', 'admin: the markup of the role');
  check(/Third-party costs/.test(S().textContent) && /Surplus/.test(S().textContent), 'admin: third-party costs and surplus');
  // people count 2 for the camera -> saved, the figures follow
  change(w, S().querySelector('[data-dk="staff.0.qty"]'), '2');
  const saved = await until(async () => (partOf(await call('GET', `/api/office/docs/${DOC}`))?.sheet?.staff || [])[0]?.qty === 2, 40);
  check(saved, 'qty 2 saved');
  await until(() => /3[.,]250/.test(S().textContent), 40);
  check(/3[.,]250[.,]00/.test(S().textContent), 'camera 2 x 1,625 shown');
  // add crew from the master data
  click(w, S().querySelector('[data-dka="role"]'));
  const md = await until(() => d.querySelector('.modal.ofdpick [data-rid]'), 80);
  check(md && /Camera|Kamera/.test(d.querySelector('.modal.ofdpick')?.textContent || ''), 'crew picker lists the roles');
  if (md) click(w, d.querySelector(`.modal.ofdpick [data-rid="${cam.id}"]`));
  await until(() => S()?.querySelectorAll('[data-dk^="staff."][data-dk$=".qty"]').length === 3, 40);
  check(S().querySelectorAll('[data-dk^="staff."][data-dk$=".qty"]').length === 3, 'a third crew row');
  // set days other than the shoot days -> the note
  change(w, S().querySelector('[data-dk="set.days"]'), '2');
  await until(() => S()?.querySelector('.dkhint'), 40);
  check(/differs from 1 shooting days/.test(S().querySelector('.dkhint')?.textContent || ''), 'set: the note about the shoot days');
  // additional costs
  click(w, S().querySelector('[data-dka="extra"]'));
  await until(() => S()?.querySelector('[data-dk="extras.0.name"]'), 40);
  change(w, S().querySelector('[data-dk="extras.0.name"]'), 'Fahrzeug');
  await until(async () => (partOf(await call('GET', `/api/office/docs/${DOC}`))?.sheet?.extras || [])[0]?.name === 'Fahrzeug', 40);
  change(w, S().querySelector('[data-dk="extras.0.rate"]'), '150');
  const ex = await until(async () => (partOf(await call('GET', `/api/office/docs/${DOC}`))?.sheet?.extras || [])[0]?.rate === 150, 40);
  check(ex, 'additional cost saved with name and price');
  check(/Net total/.test(S().textContent), 'sums: net total');
  w.close();

  // ================= member
  w = await boot({user: 'bob', hash: `office/offers/${DOC}`}); d = w.document;
  await until(() => w.eval('OFD.doc && OFD.doc.id') === DOC, 60);
  let ms = await until(() => d.querySelector(`.dksheet[data-pid="${PID}"]`), 20);
  if (!ms) {
    const box = d.createElement('div'); d.querySelector('#view').appendChild(box);
    const part = partOf(await call('GET', `/api/office/docs/${DOC}`, null, BK));
    box.innerHTML = w.dkSheetHtml(part, w.eval('OFD.doc'), false); w.dkSheetBind(box, part);
    ms = box.querySelector('.dksheet');
  }
  check(ms && !ms.querySelector('.dkmk') && !ms.querySelector('[data-dk$=".intext"]'), 'member: no markup, no intern / extern');
  check(ms && !/Third-party costs|Surplus/.test(ms.textContent), 'member: no third-party costs / surplus');
  check(ms && ms.querySelectorAll('[data-dk^="staff."][data-dk$=".qty"]').length === 3, 'member: sees the crew rows');
  w.close();

  console.log(`p2470_c_sheet_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
