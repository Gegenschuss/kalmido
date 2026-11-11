// 2.111.0 UI tests, part A (#2233, office: saved at once, undo when leaving), own container (start.sh), Firefox. Invented
// names only.
// - a quotation opened and left without a change: no hint
// - a field changed: Ctrl+Z (focus outside the field) takes that step back
// 2.905.0 (#5255, undo across devices stage 7): no editor session any more - every save is a step of the server's history:
// - two more changes, then "Back": no hint (nothing is folded); Ctrl+Z twice brings back both values, one step each
// - a change here, then one of another session of the person: Ctrl+Z takes the newest (the other one) back first
// - a finalised invoice (on the server) is a barrier: Ctrl+Z names it, the change before it stays
// - a table: a changed cell, Ctrl+Z empties it again
// - the client dialog: after "Save" the hint "… saved · Undo", its button brings back the old name
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2111_a_ui', check, shots: 'P2111A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2111A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,sheets';
const COMPANY = {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', email: 'hallo@beispiel.example', vat_id: 'DE123456789',
  iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank', tax_number: '12/345/67890'};  // 2.905.0 (#5255): an invoice to finalise
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const doc = await call(CA, 'POST', '/api/office/docs', {project_title: 'Alpha film'});
  check(doc.http === 201, 'a quotation ' + doc.http);
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Example Studio', org_id: org.id});
  const docGet = async () => call(CA, 'GET', `/api/office/docs/${doc.id}`);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 250 : 15000, step: 250});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const setField = (ev, id, v) => ev(`(() => { const i = document.getElementById('${id}'); i.focus(); i.value = ${JSON.stringify(v)}; i.dispatchEvent(new Event('change', {bubbles: true})); i.blur(); return 1; })()`);
  const toastOn = `(() => { const t = document.getElementById('toast'); return !!t && !t.classList.contains('hidden') && /saved/i.test(t.textContent) && !!t.querySelector('button:not(.tx)'); })()`;
  const open = async (ev, nav) => { await nav(B + `#office/offers/${doc.id}`); return ready(ev, `!!document.getElementById('ofd-project_title')`, 80); };
  const back = ev => ev(`(() => { document.querySelector('[data-ofd="back"]').click(); return 1; })()`);
  const ctrlZ = ev => ev(`(() => { document.activeElement?.blur?.(); document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', ctrlKey: true, bubbles: true})); return 1; })()`);
  const idle = ev => ready(ev, `!HIST.busy`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // opened and left without a change: no hint
    check(await open(ev, nav), 'the quotation opens');
    await back(ev);
    await sleep(1200);
    check(!await ev(toastOn), 'left without a change: no hint');
    // a change, Ctrl+Z takes it back (the focus is not in a field)
    check(await open(ev, nav), 'the quotation opens again');
    await setField(ev, 'ofd-project_title', 'Beta film');
    check(await until(async () => (await docGet()).project_title === 'Beta film'), 'the field is saved at once');
    await ev(`(() => { document.activeElement?.blur?.(); document.body.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', ctrlKey: true, bubbles: true})); return 1; })()`);
    check(await until(async () => (await docGet()).project_title === 'Alpha film'), 'Ctrl+Z: the step back');
    check(await ready(ev, `document.getElementById('ofd-project_title')?.value === 'Alpha film'`), 'Ctrl+Z: the editor shows the old title');
    // 2.905.0 (#5255): two changes, then Back: no hint (the steps stay single); Ctrl+Z twice -> both values from before
    await idle(ev);
    await setField(ev, 'ofd-project_title', 'Gamma film');
    await until(async () => (await docGet()).project_title === 'Gamma film');
    await setField(ev, 'ofd-project_ref', 'REF-7');
    check(await until(async () => (await docGet()).project_ref === 'REF-7'), 'the second field is saved');
    await back(ev);
    await sleep(1200);
    check(!await ev(toastOn), 'Back after a change: no folded hint any more');
    await shot('p2111-a-hint.png');
    await ctrlZ(ev);
    check(await until(async () => { const d = await docGet(); return d.project_title === 'Gamma film' && d.project_ref === ''; }), 'Ctrl+Z: the newest step back (the reference)');
    await idle(ev);
    await ctrlZ(ev);
    check(await until(async () => (await docGet()).project_title === 'Alpha film'), 'Ctrl+Z again: the title from before');
    // across devices: a change in this window, then one of another session of alice (the API) - Ctrl+Z takes back the
    // person's newest step first (the other session's), then the one of this window
    check(await open(ev, nav), 'opened a third time');
    await idle(ev);
    await setField(ev, 'ofd-project_title', 'Delta film');
    await until(async () => (await docGet()).project_title === 'Delta film');
    await back(ev);
    await call(CA, 'PATCH', `/api/office/docs/${doc.id}`, {project_title: 'Changed elsewhere'});
    await idle(ev);
    await ctrlZ(ev);
    check(await until(async () => (await docGet()).project_title === 'Delta film'), 'Ctrl+Z: the other session\'s newer step goes back first');
    await idle(ev);
    await ctrlZ(ev);
    check(await until(async () => (await docGet()).project_title === 'Alpha film'), 'Ctrl+Z again: the step of this window');
    // finalising (on the server): a barrier
    const s0 = await call(CA, 'PUT', '/api/office/settings', {company_fields: COMPANY});
    const cl2 = await call(CA, 'POST', '/api/clients', {name: 'Kunde Beta GmbH', street: 'Weg 2', zip: '10115', city: 'Berlin', country: 'DE', email: 'kunde-beta@example.com', org_id: org.id});
    const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl2.id, service_from: today(), items: [{title: 'Schnitt', qty: 1, rate: 100}]});
    const fin = await call(CA, 'POST', `/api/office/docs/${inv.id}/finalize`, {});
    check(s0.http === 200 && fin.http === 200, `an invoice finalised (${s0.http} ${fin.http} ${fin.error || ''})`);
    await idle(ev);
    await ctrlZ(ev);
    check(await ready(ev, `/Stopped before a step that cannot be undone/.test(document.getElementById('toast')?.textContent || '')`), 'Ctrl+Z on the barrier: named, nothing undone ' + await ev(`document.getElementById('toast')?.textContent || ''`));
    check((await call(CA, 'GET', `/api/office/docs/${inv.id}`)).number, 'the invoice stays finalised');
    // a table: a cell, Ctrl+Z empties it again
    const sh = await call(CA, 'POST', '/api/sheets', {title: 'Budget sheet'});
    check(sh.http === 201, 'a table ' + sh.http);
    const cellOf = async () => ((await call(CA, 'GET', `/api/sheets/${sh.id}`)).cells || []).find(c => c.raw === 'Forty-two');
    await nav(B + `#sheets/${sh.id}`);
    check(await ready(ev, `typeof SHV !== 'undefined' && SHV.sh?.id === ${sh.id}`, 80), 'the table opens');
    await ev(`shvPut([{row_id: SHV.sh.rows[0].id, col_id: SHV.sh.columns[0].id, raw: 'Forty-two'}]).then(() => 1)`);
    check(await until(async () => !!await cellOf()), 'the cell is saved');
    check(await ready(ev, `HIST.undo.length > 0 && histGids(HIST.undo.at(-1)).length > 0`), 'the step names its server group');
    await ctrlZ(ev);
    check(await until(async () => !await cellOf()), 'Ctrl+Z: the cell is empty again');
    // the client dialog: "Save" -> the hint, Undo -> the old name
    await nav(B + '#office/offers');
    await ready(ev, `typeof clientModal === 'function' && (S.clients || []).some(c => c.id === ${cl.id})`, 80);
    await ev(`(() => { clientModal(S.clients.find(c => c.id === ${cl.id})); return 1; })()`);
    // 2.747.0 (#5246): the dialog's "… saved · Undo" comes from objsave.js (objSaved, loaded with the save) instead of office_undo.js
    check(await ready(ev, `!!document.querySelector('.cldlg #cl-name')`), 'the client dialog');
    await ev(`(() => { document.querySelector('.cldlg #cl-name').value = 'Example Studio Ltd'; document.querySelector('.cldlg [data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, toastOn), 'client saved: "… saved · Undo"');
    check((await call(CA, 'GET', `/api/clients/${cl.id}`)).name === 'Example Studio Ltd', 'the new name is saved');
    await ev(`(() => { document.querySelector('#toast button:not(.tx)').click(); return 1; })()`);
    check(await until(async () => (await call(CA, 'GET', `/api/clients/${cl.id}`)).name === 'Example Studio'), 'Undo: the old name');
  }, false);

  console.log(`p2111_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
