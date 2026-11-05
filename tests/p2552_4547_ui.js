// 2.552.0 (#4547) UI tests (jsdom), fresh DB, a person without an organisation: what is typed into a document's positions,
// a table's cells and the client dialog's contact persons / symbol survives the end of the session (401 -> sign-in -> reload)
// kalmido-suite: fresh
// - a position: the PUT of the positions is kept (core.js fdWrite) until the server has it, sent after the sign-in; a position
//   typed in but not left yet goes at pagehide (keepalive) and is kept the same way
// - a table cell: the PUT of the cells the same; an open cell editor at pagehide too
// - the client dialog: an added contact person and the chosen symbol come back when the dialog opens again (fdDialog x)
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CF;
const call = async (method, url, body, ck = CF) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
// every request that leaves the window [method, path, body, keepalive]; fake(m, p) answers instead of the server
const stub = (w, fake) => { const calls = [], of = w.fetch; w.fetch = (u, o = {}) => { const m = (o.method || 'GET').toUpperCase(), p = new URL(String(u), B).pathname; calls.push([m, p, o.body, !!o.keepalive]); const r = fake && fake(m, p, o); return r ? Promise.resolve(r) : of(u, o); }; return calls; };
const jres = (st, j) => new Response(JSON.stringify(j), {status: st, headers: {'content-type': 'application/json'}});
// the session ended for the requests that match re (method + path)
const gone = (w, re) => stub(w, (m, p) => re.test(m + ' ' + p) ? jres(401, {error: 'Not signed in'}) : null);
const change = (w, el, v) => { if (!el) return; if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const input = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const click = (w, el) => el?.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const svc = (title, qty, rate) => ({kind: 'service', title, qty, unit: 'day', rate, tax: 'standard', raw_fee: 0, producing: 0, in_handling: 0, in_markup: 0, intext: 'intern', cost: 0, discountable: 1});
const FEATURES = 'cal,collab,comments,contacts,files,clients,office,sheets';

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, AK);
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK);  // a server with organisations
  // the person without an organisation (as tests/freelancer_fixture.py)
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'setup: a person without an organisation ' + fu.http);
  CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATURES});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'setup: frida is in no organisation');
  await call('GET', '/api/office/settings');
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Campaign', items: [svc('Concept', 1, 800), svc('Edit', 2, 500)]});
  check(doc.http === 201, 'setup: a quotation ' + doc.http);
  const D = doc.id;
  const sht = await call('POST', '/api/sheets', {title: 'Budget', space: 'private'});
  check(sht.http === 201, 'setup: a table ' + sht.http);
  const SID = sht.id;
  const CL = (await call('POST', '/api/clients', {name: 'Acme Testkunde'})).id;
  check(!!CL, 'setup: a client');
  const sh = {store: {}, wins: []}, opt = h => ({user: 'frida', hash: h, shared: sh});
  const kept = (w, re) => Object.keys(w.__store).filter(k => /^tasks\.fdw\./.test(k) && re.test(w.__store[k] || ''));
  const items = async () => (await call('GET', `/api/office/docs/${D}`)).items || [];

  // ================= a position: the save meets the ended session
  let w = await boot(opt(`office/offers/${D}`)), d = w.document;
  const fid = w.eval('S.me.id');
  const pos = (i, k) => d.querySelector(`.ofdeditor [data-i="${i}"][data-k="${k}"]`);
  check(!!await until(() => pos(0, 'title')), 'position: the editor shows the positions');
  let calls = gone(w, /^PUT \/api\/office\/docs\/\d+\/items$/);
  change(w, pos(0, 'title'), 'Concept and script');
  check(await until(() => calls.some(([m, p]) => m === 'PUT' && p === `/api/office/docs/${D}/items`)), 'position: the save went out (and met the ended session)');
  check(await until(() => kept(w, /Concept and script/).length === 1), 'position: the positions are kept for after the sign-in ' + Object.keys(w.__store).filter(k => /fdw/.test(k)));
  check((await items())[0]?.title === 'Concept', 'position: the server did not get it');
  w.dispatchEvent(new w.Event('pagehide'));  // the reload to the sign-in page
  w.close();
  w = await boot(opt(`office/offers/${D}`)); d = w.document;  // signed in again, the page loads anew
  check(await until(async () => (await items())[0]?.title === 'Concept and script'), 'position: sent after the sign-in');
  check(await until(() => !kept(w, /Concept and script/).length), 'position: sent = no longer kept');
  check(await until(() => pos(0, 'title')?.value === 'Concept and script'), 'position: the open document shows it ' + JSON.stringify(pos(0, 'title')?.value));
  check((await items()).length === 2, 'position: no line twice');

  // a position typed in, not left yet, when the page goes (the reload of an ended session)
  calls = gone(w, /^PUT \/api\/office\/docs\/\d+\/items$/);
  const t2 = pos(1, 'title'); t2.focus(); input(w, t2, 'Edit and colour');
  check(w.document.activeElement === t2, 'position typed: the field has the focus');
  w.dispatchEvent(new w.Event('pagehide'));
  // the save runs in the document's row of saves (a microtask after the event, still before the page goes)
  check(await until(() => calls.some(([m, p, , ka]) => m === 'PUT' && p === `/api/office/docs/${D}/items` && ka)), 'position typed: out with keepalive at pagehide ' + JSON.stringify(calls.map(c => c[0] + ' ' + c[1])));
  check(await until(() => kept(w, /Edit and colour/).length === 1), 'position typed: kept for after the sign-in');
  w.close();
  w = await boot(opt(`office/offers/${D}`)); d = w.document;
  check(await until(async () => (await items())[1]?.title === 'Edit and colour'), 'position typed: sent after the sign-in');
  check(await until(() => !kept(w, /Edit and colour/).length), 'position typed: no longer kept');
  w.close();

  // ================= a table cell
  const cellRaw = async (r, c) => ((await call('GET', `/api/sheets/${SID}`)).cells || []).find(x => x.row_id === r && x.col_id === c)?.raw;
  w = await boot(opt('sheets/' + SID)); d = w.document;
  check(await until(() => w.eval(`typeof SHV !== 'undefined' && SHV.sh?.id === ${SID} && SHV.sh.rows.length > 1 && SHV.sh.columns.length > 0`)), 'cell: the table is open');
  const R0 = w.eval('SHV.sh.rows[0].id'), R1 = w.eval('SHV.sh.rows[1].id'), C0 = w.eval('SHV.sh.columns[0].id');
  calls = gone(w, /^PUT \/api\/sheets\/\d+\/cells$/);
  w.eval(`shvSelect(${R0}, ${C0}); shvEditStart(null)`);
  const ed = await until(() => d.getElementById('shv-ed'));
  check(!!ed, 'cell: the editor is open');
  ed.value = 'Apples';
  w.eval('shvEditEnd(true)');
  check(await until(() => calls.some(([m, p]) => m === 'PUT' && p === `/api/sheets/${SID}/cells`)), 'cell: the write went out (and met the ended session)');
  check(await until(() => kept(w, /Apples/).length === 1), 'cell: the input is kept for after the sign-in');
  check(await cellRaw(R0, C0) !== 'Apples', 'cell: the server did not get it');
  w.dispatchEvent(new w.Event('pagehide'));
  w.close();
  w = await boot(opt('sheets/' + SID)); d = w.document;
  check(await until(async () => await cellRaw(R0, C0) === 'Apples'), 'cell: sent after the sign-in');
  check(await until(() => !kept(w, /Apples/).length), 'cell: no longer kept');
  check(await until(() => /Apples/.test(d.getElementById(`shv-c-${R0}-${C0}`)?.textContent || '')), 'cell: the open table shows it');

  // an open cell editor when the page goes
  check(await until(() => w.eval(`SHV.sh?.id === ${SID}`)), 'cell typed: the table is open again');
  calls = gone(w, /^PUT \/api\/sheets\/\d+\/cells$/);
  w.eval(`shvSelect(${R1}, ${C0}); shvEditStart(null)`);
  const ed2 = await until(() => d.getElementById('shv-ed'));
  ed2.value = 'Pears';
  w.dispatchEvent(new w.Event('pagehide'));
  check(calls.some(([m, p, , ka]) => m === 'PUT' && p === `/api/sheets/${SID}/cells` && ka), 'cell typed: out with keepalive at pagehide');
  check(kept(w, /Pears/).length === 1, 'cell typed: kept for after the sign-in');
  w.close();
  w = await boot(opt('sheets/' + SID)); d = w.document;
  check(await until(async () => await cellRaw(R1, C0) === 'Pears'), 'cell typed: sent after the sign-in');
  check(await until(() => !kept(w, /Pears/).length), 'cell typed: no longer kept');
  w.close();

  // ================= the client dialog: a contact person added, a symbol chosen
  const ICO = 'ic:shop', ckey = `tasks.fdf.${fid}.cl.${CL}`;
  w = await boot(opt('clients')); d = w.document;
  check(await until(() => w.eval('S.booted && typeof clientModal === "function"')), 'client: the app is up');
  w.eval(`clientModal(${JSON.stringify(await call('GET', '/api/clients/' + CL))})`);
  let md = await until(() => d.querySelector('.modal.cldlg'));
  click(w, md.querySelector('[data-clk-add]'));
  const kn = await until(() => md.querySelector('[data-clk="name"][data-i="0"]'));
  input(w, kn, 'Jana Berg');
  input(w, md.querySelector('[data-clk="email"][data-i="0"]'), 'jana@example.com');
  click(w, md.querySelector(`[data-clico="${ICO}"]`));
  check(await until(() => /Jana Berg/.test(w.__store[ckey] || '') && (w.__store[ckey] || '').includes(ICO)), 'client: the contact person and the symbol are kept while typing ' + (w.__store[ckey] || '').slice(0, 300));
  calls = gone(w, /^PATCH \/api\/clients\/\d+$/);
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(() => calls.some(([m, p]) => m === 'PATCH' && p === '/api/clients/' + CL)), 'client: the save went out (and met the ended session)');
  let cs = await call('GET', '/api/clients/' + CL);
  check(!(cs.contacts || []).length && !cs.icon, 'client: the server did not get it');
  check(/Jana Berg/.test(w.__store[ckey] || ''), 'client: the ended session kept it');
  w.dispatchEvent(new w.Event('pagehide'));
  w.close();
  w = await boot(opt('clients')); d = w.document;
  check(await until(() => w.eval('S.booted && typeof clientModal === "function"')), 'client: the app is up again');
  w.eval(`clientModal(${JSON.stringify(await call('GET', '/api/clients/' + CL))})`);
  md = await until(() => d.querySelector('.modal.cldlg'));
  check(md?.querySelector('[data-clk="name"][data-i="0"]')?.value === 'Jana Berg' && md.querySelector('[data-clk="email"][data-i="0"]')?.value === 'jana@example.com', 'client: the contact person is back');
  check(md?.querySelector('#cl-icon')?.value === ICO && md.querySelector(`[data-clico="${ICO}"]`)?.classList.contains('on'), 'client: the symbol is back ' + md?.querySelector('#cl-icon')?.value);
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => { const c = await call('GET', '/api/clients/' + CL); return c.icon === ICO && (c.contacts || []).some(k => k.name === 'Jana Berg'); }), 'client: saved now with both');
  check(await until(() => !w.__store[ckey]), 'client: saved = no longer kept');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`p2552_4547_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
