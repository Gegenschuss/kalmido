// 2.144.6 A (#2053) UI (jsdom): time entries to an invoice. A person without an organisation (their personal office):
// the switch "Billable" in the entry dialog (one undo step), the row shows "not billable" / "billed <number>" (opens the
// invoice, no delete button), a billed entry's dialog locks duration / date / task / billable and keeps the note,
// the dialog "Invoice from time entries" shows the open billable hours.
// usage: node p21446_a_ui.js <datadir>
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = async (fn, ms = 4000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(100); } return false; };
const ent = async (tid, id) => (await call('GET', `/api/time/entries?task_id=${tid}`)).entries.find(e => e.id === id);

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,clients,office', workspace: 'private'});
  const CL = (await call('POST', '/api/clients', {name: 'Nordwind GmbH', org_id: null, rate: 80})).id;
  const L = (await call('POST', '/api/lists', {name: 'Hafenfilm', kind: 'project', time_tracking: true})).id;
  await call('PATCH', `/api/lists/${L}`, {client_id: CL});
  const T = (await call('POST', '/api/tasks', {title: 'Schnitt', list_id: L})).id;
  const day = n => { const d = new Date(); d.setDate(d.getDate() - n); d.setHours(9, 0, 0, 0); return d.toISOString(); };
  const E1 = await call('POST', '/api/time/entries', {task_id: T, start: day(3), minutes: 90, note: 'first cut'});
  const E2 = await call('POST', '/api/time/entries', {task_id: T, start: day(2), minutes: 30, note: 'own review'});
  check(E1.billable === true && E2.billable === true, 'setup: entries are billable by default');

  let w = await boot({user: 'alice', hash: 'l/' + L}); let d = w.document;
  // ================= the switch in the dialog, one undo step
  w.eval(`openDetail(${T})`); await sleep(700);
  w.eval(`entryModal(findEntry(${E2.id}))`); await sleep(100);
  let md = [...d.querySelectorAll('.modal')].pop();
  const sw = md.querySelector('#te-bill');
  check(sw && sw.checked && !sw.disabled, 'dialog: the switch "Billable" is on');
  sw.checked = false; md.querySelector('[data-m="save"]').click();
  check(await until(async () => (await ent(T, E2.id))?.billable === false), 'switch off: the server has billable false');
  check(await until(() => [...d.querySelectorAll('#d-time .terow')].some(r => /not billable/.test(r.querySelector('.tebill')?.textContent || ''))), 'row: "not billable"');
  check(w.eval('HIST.undo.length') >= 1 && /not billable/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), 'one undo step for the switch');
  await w.eval("histStep('undo')"); await sleep(300);
  check(await until(async () => (await ent(T, E2.id))?.billable === true), 'undo: billable again');
  await call('PATCH', `/api/time/entries/${E2.id}`, {billable: false});

  // ================= invoice from time: the dialog shows the open hours
  await w.eval(`go('office/offers')`); await sleep(800);
  w.eval('ofdFromTimeDialog()'); await sleep(200);
  md = [...d.querySelectorAll('.modal')].pop();
  const f = md.querySelector('#ofd-ft-from');
  if (f) { f.value = day(10).slice(0, 10); f.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(() => /Open billable: 1[.,]5/.test(md.querySelector('.tbill-open')?.textContent || '')), 'from-time dialog: open billable hours ' + (md.querySelector('.tbill-open')?.textContent || ''));
  check(/0[.,]5 h not billable/.test(md.querySelector('.tbill-open')?.textContent || ''), 'from-time dialog: not billable hours');
  md.querySelector('[data-m="close"]').click();
  const inv = await call('POST', '/api/office/docs/from-time', {client_id: CL, from: day(10).slice(0, 10), to: day(0).slice(0, 10)});
  check(inv.time && inv.time.taken_entries === 1, 'setup: the draft takes the billable entry');

  // ================= the billed row and its locked dialog
  await w.eval(`go('l/${L}')`); await w.eval('load().then(render)'); await sleep(300);
  w.eval(`openDetail(${T})`); await sleep(800);
  const row = [...d.querySelectorAll('#d-time .terow')].find(r => r.querySelector('.tebill[data-go]'));
  check(row && row.querySelector('.tebill').dataset.go === `office/invoices/${inv.id}` && /billed/.test(row.querySelector('.tebill').textContent), 'row: "billed" opens the invoice');
  check(row && !row.querySelector('[data-act="te-del"]') && row.querySelector('[data-act="te-edit"]'), 'billed row: edit, no delete');
  w.eval(`entryModal(findEntry(${E1.id}))`); await sleep(100);
  md = [...d.querySelectorAll('.modal')].pop();
  check(md.querySelector('#te-dur').disabled && md.querySelector('#te-date').disabled && md.querySelector('#te-target').disabled && md.querySelector('#te-bill').disabled,
    'billed dialog: duration, date, task and the switch are locked');
  check(!md.querySelector('[data-m="del"]') && md.querySelector('.tebill-hint'), 'billed dialog: no delete, the hint');
  md.querySelector('#te-note').value = 'first cut, colour'; md.querySelector('[data-m="save"]').click();
  check(await until(async () => (await ent(T, E1.id))?.note === 'first cut, colour'), 'billed entry: the note still changes');

  console.log(`${ok} ok, ${F.length} failed, js errors: ${errs.length}`); errs.forEach(e => console.log('JSERR', e));
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
