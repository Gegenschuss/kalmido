// 2.773.0 UI test, part A (#5250): undo across devices, stage 2 - the list "Recent steps" (static/js/undolist.js, loaded on demand).
// kalmido-suite: fresh
// freelancer-matrix: undo (a person without an organisation: the page from the account menu, "Back up to here" takes two of her steps back)
// jsdom, fresh container. Invented names only. alice works in her organisation's office; writes from "another device" go
// straight to the server with X-Kalmido-Device-Name: Laptop (Test):
//  - ← with nothing to undo in this browser is not dead: it is named "Recent steps" and a right-click / a click opens the window
//  - the window lists the person's step groups of the server, newest first: label, time, area (Office), device; a barrier
//    (a finalised invoice) is greyed and so is every older row ("Behind a step that cannot be undone"), their buttons off
//  - live: a write of the other device appears in the open window (the own "self" counter of the poll), no reopening
//  - "Back up to here" on the second row takes TWO groups back (the service's rate as before them); both rows say "Undone"
//    and offer "Redo", which brings one forward again
//  - a conflict answer of the server: the panel names what stayed (the rest went back, the server decides)
//  - this browser's own write is listed with "This device" (the header of core.js rawFetch0); a task step is the server's
//    row of this device (2.905.0, #5255: no "only this device" twin); a change waiting in the outbox without a step of its own is on top
//    ("Not sent yet")
//  - the account menu's "Recent steps" opens the same list as a page (#steps): the same rows and buttons; Back (the phone's
//    system Back = history.back) returns to the view before
// The waits are on states (rows, values on the server, the hash), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DEV = {'X-Kalmido-Device-Name': 'Laptop (Test)'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'cal,comments,collab,office,clients,files,docs';
const COMPANY = {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', email: 'hallo@beispiel.example', vat_id: 'DE123456789',
  iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank', tax_number: '12/345/67890'};
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

async function office(ck, tag) {
  const s = await call(ck, 'PUT', '/api/office/settings', {company_fields: COMPANY});
  check(s.http === 200, `${tag}: office settings (${s.http} ${s.error || ''})`);
  const cl = await call(ck, 'POST', '/api/clients', {name: `Kunde ${tag} GmbH`, street: 'Weg 2', zip: '10115', city: 'Berlin', country: 'DE', email: `kunde-${tag.toLowerCase()}@example.com`});
  const sv = await call(ck, 'POST', '/api/office/services', {name_de: `Schnitt ${tag}`, daily_rate: 800});
  check(cl.id && sv.id, `${tag}: a client and a service (${cl.http} ${sv.http})`);
  return {CL: cl.id, SV: sv.id};
}
const rate = async (ck, sv) => (await call(ck, 'GET', `/api/office/services/${sv}`)).daily_rate;

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', features: FEAT, tour: 'done'});
  const ALICE = (await call(CA, 'GET', '/api/state')).me.id;
  const ORG = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: ALICE})).id;
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${ORG}`});
  const {CL, SV} = await office(CA, 'Alpha');
  const svc = v => call(CA, 'PATCH', `/api/office/services/${SV}`, {daily_rate: v}, DEV);
  await svc(810);
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: CL, service_from: today(), items: [{title: 'Schnitt', qty: 1, rate: 100}]});
  const fin = await call(CA, 'POST', `/api/office/docs/${inv.id}/finalize`, {}, DEV);
  check(fin.http === 200, `the invoice is finalised (${fin.http} ${fin.error || ''})`);
  await svc(820); await svc(830); await svc(840);
  const srv = (await call(CA, 'GET', '/api/undo')).items || [];
  const [G3, G2, G1, GB] = srv, G0 = srv.slice(4).find(g => /Schnitt Alpha/.test(g.label)) || {};
  check(srv.length >= 5 && G3.state === 'done' && G1.state === 'done' && GB.state === 'barrier' && G0.state === 'done' && G3.device === 'Laptop (Test)',
    `the server lists the steps of the other device: 3 changes, the barrier, 1 older ${JSON.stringify(srv.slice(0, 6).map(g => [g.id, g.state, g.device, g.label]))}`);

  let w = await boot({user: 'alice', hash: 'today'}); const d = w.document;
  const btn = () => d.querySelector('#top [data-act="hist-undo"]');
  const row = (id, root = '#pop:not(.hidden)') => d.querySelector(`${root} .ulbody .ulrow[data-ul="s:${id}"]`);
  check(btn() && !btn().disabled && btn().getAttribute('aria-label') === 'Recent steps', `← with nothing to undo here opens the list (${btn()?.getAttribute('aria-label')}, disabled ${btn()?.disabled})`);
  check(!w.eval('typeof UL !== "undefined" && UL.items'), 'nothing fetched before the list is opened');

  // ---- the window: right-click on ←
  btn().dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  check(await until(() => row(G0.id)), 'right-click: the window shows the server steps');
  const rows = [...d.querySelectorAll('#pop .ulbody .ulrow.ul-s')].map(r => r.getAttribute('data-ul'));
  check(rows.slice(0, 4).join() === [G3, G2, G1, GB].map(g => 's:' + g.id).join() && rows.indexOf('s:' + G0.id) > 3, `newest first ${rows}`);
  const r3 = row(G3.id).textContent;
  check(/Changed: Schnitt Alpha/.test(r3) && /Office/.test(r3) && /Laptop \(Test\)/.test(r3) && /\d{1,2}:\d{2}/.test(r3), `a row: label, time, area, device: ${r3}`);
  check(row(GB.id).classList.contains('uloff') && row(GB.id).querySelector('[data-ul-go]').disabled && /Finalised/.test(row(GB.id).textContent), 'the barrier is greyed, its button off');
  check(row(G0.id).classList.contains('uloff') && row(G0.id).querySelector('[data-ul-go]').disabled && /Behind a step that cannot be undone/.test(row(G0.id).textContent), 'an older step behind the barrier is greyed too');
  check(!row(G1.id).classList.contains('uloff') && !row(G1.id).querySelector('[data-ul-go]').disabled, 'the steps above the barrier can be taken back');

  // ---- live: the other device writes, the open window shows it
  await svc(850);
  const G4 = (await call(CA, 'GET', '/api/undo')).items[0];
  check(await until(() => row(G4.id)), 'live: the new step of the other device appears in the open window');
  check(d.querySelector('#pop .ulbody .ulrow').getAttribute('data-ul') === 's:' + G4.id, 'live: on top');

  // ---- "Back up to here" on the second row: two groups back
  row(G3.id).querySelector('[data-ul-go]').click();
  check(await until(async () => await rate(CA, SV) === 830 && !w.eval('UL.busy')), 'Back up to here: two steps back (the rate as after the third change)');
  check(await until(() => row(G4.id)?.classList.contains('ulundone') && row(G3.id)?.classList.contains('ulundone')), 'both rows say they are undone');
  check(/2 steps undone/.test(d.querySelector('#pop .ulnote')?.textContent || ''), `the window says how many went: ${d.querySelector('#pop .ulnote')?.textContent}`);
  check(!row(G2.id).classList.contains('ulundone') && row(G3.id).querySelector('[data-ul-redo]'), 'the step below stays, an undone row offers Redo');
  row(G3.id).querySelector('[data-ul-redo]').click();
  check(await until(async () => await rate(CA, SV) === 840 && !w.eval('UL.busy')), 'Redo brings that step forward again');

  // ---- a conflict answer: what stayed is named (the server took the rest back)
  await w.eval(`(() => { window.__api0 = api; api = (m, u, b) => /\\/api\\/undo\\/to\\//.test(u) ? Promise.resolve({undone: [], partial: [${G2.id}], stayed: [{group: ${G2.id}, kind: 'office_service', id: ${SV}, code: 'conflict', reason: 'Changed elsewhere'}], stopped: null, text: ''}) : window.__api0(m, u, b); return 1; })()`);
  await until(() => row(G2.id) && !row(G2.id).querySelector('[data-ul-go]').disabled);
  row(G2.id).querySelector('[data-ul-go]').click();
  check(await until(() => /Stayed as it is: Changed: Schnitt Alpha: Changed elsewhere/.test(d.querySelector('#pop .ulnote')?.textContent || '')), `a conflict: the window names what stayed (${d.querySelector('#pop .ulnote')?.textContent})`);
  await w.eval('api = window.__api0, 1');

  // ---- this browser: its own write ("This device"), a task step not on the server ("only this device"), a waiting change
  await w.eval(`api('PATCH', '/api/office/services/${SV}', {daily_rate: 860}).then(() => 1)`);
  const own = (await call(CA, 'GET', '/api/undo')).items[0];
  check(own.device && own.device !== 'Laptop (Test)', `a write of the app names its browser (X-Kalmido-Device-Name: ${own.device})`);
  check(await until(() => /This device/.test(row(own.id)?.textContent || '')), 'the window calls this browser "This device"');
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Work'})).id;
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Pay invoice', list_id: L})).id;
  await w.eval('load().then(render)');
  await w.eval(`patchTask(${T}, {priority: 5})`);
  // 2.905.0 (#5255): the task step is on the server now: listed once, as the server's row of this device (no "only this device" twin)
  check(await until(() => [...d.querySelectorAll('#pop .ulbody .ulrow.ul-s')].some(r => /Pay invoice/.test(r.textContent) && /This device/.test(r.textContent))), 'a task step of this browser: the server\'s row of "This device"');
  check(![...d.querySelectorAll('#pop .ulbody .ulrow.ul-l')].some(r => /Pay invoice/.test(r.textContent)), 'no second row "only this device" for it');
  await until(() => w.eval('OUT.q.length') === 0);
  w.__offline = true;
  await w.eval(`enqueue('PATCH', '/api/tasks/${T}', {title: 'Pay invoice today'})`);
  check(await until(() => { const f = d.querySelector('#pop .ulbody .ulrow'); return f && f.classList.contains('ul-q') && /Not sent yet/.test(f.textContent); }), 'a change waiting in the outbox stands on top ("Not sent yet")');
  w.__offline = false; await w.eval('flush()');
  await until(() => w.eval('OUT.q.length') === 0);
  w.eval('closePop()');

  // ---- the page: the account menu's "Recent steps"
  d.querySelector('[data-act="user-menu"]').click();
  const item = await until(() => [...d.querySelectorAll('#pop:not(.hidden) .menu-list button')].find(b => /Recent steps/.test(b.textContent)));
  check(item, 'the account menu has "Recent steps"');
  item.click();
  check(await until(() => w.location.hash === '#steps' && row(G2.id, '#view')), `the page #steps shows the same list (${w.location.hash})`);
  check(row(GB.id, '#view').classList.contains('uloff') && row(GB.id, '#view').querySelector('[data-ul-go]').disabled && row(G2.id, '#view').querySelector('[data-ul-go]'), 'the page: the same rows, the barrier greyed, "Back up to here"');
  check(/Recent steps/.test(d.querySelector('#view .ulhead')?.textContent || ''), 'the page has its title');
  w.history.back();
  check(await until(() => w.location.hash !== '#steps' && !d.querySelector('#view .ulpage')), `Back closes the page to the view before (${w.location.hash})`);
  w.close();

  // ---- a person without an organisation (freelancer parity)
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CF = await login('fiona');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', features: FEAT, tour: 'done', workspace: 'private'});
  const fo = await office(CF, 'Frei');
  await call(CF, 'PATCH', `/api/office/services/${fo.SV}`, {daily_rate: 500}, DEV);
  await call(CF, 'PATCH', `/api/office/services/${fo.SV}`, {daily_rate: 600}, DEV);
  const fg = (await call(CF, 'GET', '/api/undo')).items || [];
  check(fg.length >= 2 && fg.every(g => g.state === 'done'), `fiona: her two steps on the server (${fg.length})`);
  const w2 = await boot({user: 'fiona', hash: 'today'}); const d2 = w2.document;
  d2.querySelector('[data-act="user-menu"]').click();
  const it2 = await until(() => [...d2.querySelectorAll('#pop:not(.hidden) .menu-list button')].find(b => /Recent steps/.test(b.textContent)));
  it2.click();
  const fr = id => d2.querySelector(`#view .ulbody .ulrow[data-ul="s:${id}"]`);
  check(await until(() => fr(fg[1].id)), 'fiona: the page lists her steps');
  fr(fg[1].id).querySelector('[data-ul-go]').click();
  check(await until(async () => await rate(CF, fo.SV) === 800), 'fiona: Back up to here takes both steps back');
  check(await until(() => fr(fg[0].id)?.classList.contains('ulundone') && fr(fg[1].id)?.classList.contains('ulundone')), 'fiona: both rows undone');
  check(!(await call(CA, 'GET', '/api/undo')).items.some(g => fg.some(x => x.id === g.id)), 'alice does not see fiona\'s steps');
  w2.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2773_a_letzte_schritte_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
