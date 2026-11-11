// 2.912.0 UI test (#5419), jsdom, fresh DB; invented data only.
// kalmido-suite: fresh
// freelancer-matrix: office
// The reminder fee marked paid asks the day the money came (office_docs.js ofdFeeDayDialog), as the admin of an organisation
// AND as a person without organisation:
// - "Fee paid" opens a dialog with a date field (default today); Cancel = nothing happens (fee stays open, no day)
// - a chosen day is sent: the editor shows "paid" with that day, the stored day is it, the journal books the fee on it
//   (organisation, balance sheet: 1590 to 2700) / the income statement of the year counts it (person without organisation)
// - "Change date" opens the dialog with the stored day; a new day moves the fee to it (shown, stored, booked)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const dbx = (sql, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]).toString() || '[]');
const FEAT = 'cal,comments,collab,office,clients';
const iso = dt => `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`;
const ago = n => { const t = require('./boot').testNow(); t.setHours(12, 0, 0, 0); t.setDate(t.getDate() - n); return iso(t); };
const TODAY = ago(0);
// the paid day lies in the reminder's month or later and not in the future: reminder 6 days ago, then 4 and 2 days ago
const REM_DAY = ago(6), DAY1 = ago(4), DAY2 = ago(2);
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

// a finalised invoice (30 days ago, overdue) and a finalised reminder with a 5,00 fee (6 days ago)
async function reminder(ck, who) {
  const cl = (await call(ck, 'POST', '/api/clients', {name: `${who} Kunde AG`, street: 'Weg 1', zip: '12345', city: 'Musterstadt', country: 'DE'})).id;
  const inv = await call(ck, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl, service_from: ago(30), items: [{title: 'Schnitt', qty: 1, rate: 500}]});
  check(inv.http === 201, `${who}: an invoice ${inv.http} ${JSON.stringify(inv.error || '')}`);
  await call(ck, 'PATCH', `/api/office/docs/${inv.id}`, {date: ago(30)});
  const fin = await call(ck, 'POST', `/api/office/docs/${inv.id}/finalize`);
  check(fin.http === 200 && fin.locked, `${who}: the invoice finalised ${fin.http}`);
  execFileSync('python3', ['-c', 'import sys, dbx; dbx.overdue(sys.argv[1], sys.argv[2:], 10)', DATA, String(inv.id)], {cwd: __dirname});
  const rem = await call(ck, 'POST', '/api/office/docs/reminder', {doc_ids: [inv.id], level: 2, fee: 5});
  check(rem.http === 201, `${who}: a reminder with a fee ${rem.http} ${JSON.stringify(rem.error || '')}`);
  await call(ck, 'PATCH', `/api/office/docs/${rem.id}`, {date: REM_DAY});
  const rf = await call(ck, 'POST', `/api/office/docs/${rem.id}/finalize`);
  check(rf.http === 200 && rf.locked && rf.date === REM_DAY, `${who}: the reminder finalised on ${REM_DAY} ${rf.http} ${rf.date}`);
  return rem.id;
}

const feeDay = id => { const x = dbx('SELECT reminder_fee_state AS st, reminder_fee_paid_at AS day FROM office_docs WHERE id=?', [id])[0] || {}; return [x.st || '', x.day || '']; };

async function run(user, ck, who, booked) {
  const rid = await reminder(ck, who);
  const w = await boot({user, hash: 'office/offers/' + rid}), d = w.document;
  const info = () => (d.querySelector('.ofdfeeinfo')?.textContent || '').replace(/\s+/g, ' ');
  check(await until(() => d.querySelector('[data-ofd="fee"][data-st="paid"]')), `${who}: the finalised reminder offers "Fee paid": ${info()}`);
  check(/Reminder fee .*5[.,]00.*open/.test(info()), `${who}: the fee is shown open: ${info()}`);
  const dlg = () => [...d.querySelectorAll('.modal')].find(m => m.querySelector('#ofd-fee-day'));

  // Cancel: nothing happens
  click(w, d.querySelector('[data-ofd="fee"][data-st="paid"]'));
  check(await until(() => dlg()), `${who}: "Fee paid" opens the dialog with the day`);
  const m0 = dlg();
  check(m0 && /Paid on/.test(m0.textContent) && m0.querySelector('#ofd-fee-day').value === TODAY && /money came/.test(m0.textContent),
    `${who}: the dialog asks "Paid on", default today ${TODAY}: ${m0?.querySelector('#ofd-fee-day')?.value} / ${(m0?.textContent || '').replace(/\s+/g, ' ').slice(0, 160)}`);
  click(w, m0.querySelector('[data-m="close"]'));
  check(await until(() => !dlg()), `${who}: Cancel closes the dialog`);
  const st0 = feeDay(rid);
  check(!st0[0] && !st0[1] && /open/.test(info()), `${who}: Cancel changes nothing (state, day) ${JSON.stringify(st0)} ${info()}`);

  // a chosen day
  click(w, d.querySelector('[data-ofd="fee"][data-st="paid"]'));
  const m1 = await until(() => dlg());
  w.eval(`dpSet(document.querySelector('#ofd-fee-day'), '${DAY1}')`);
  click(w, m1.querySelector('[data-m="ok"]'));
  const shown1 = w.eval(`fmtDateLoc('${DAY1}')`);
  check(await until(() => !dlg() && /paid/.test(info()) && info().includes(shown1)), `${who}: the editor shows paid on ${shown1}: ${info()}`);
  check(JSON.stringify(feeDay(rid)) === JSON.stringify(['paid', DAY1]), `${who}: the chosen day is stored ${JSON.stringify(feeDay(rid))}`);
  check(await booked(rid, DAY1), `${who}: the fee is booked on ${DAY1}`);

  // change the day
  const chg = await until(() => [...d.querySelectorAll('[data-ofd="fee"][data-st="paid"]')].find(b => /Change date/.test(b.textContent)));
  check(!!chg && !!d.querySelector('[data-ofd="fee"][data-st=""]'), `${who}: a paid fee offers "Change date" and "Open again": ${info()}`);
  click(w, chg);
  const m2 = await until(() => dlg());
  check(m2 && m2.querySelector('#ofd-fee-day').value === DAY1, `${who}: "Change date" starts at the stored day ${m2?.querySelector('#ofd-fee-day')?.value}`);
  w.eval(`dpSet(document.querySelector('#ofd-fee-day'), '${DAY2}')`);
  click(w, m2.querySelector('[data-m="ok"]'));
  const shown2 = w.eval(`fmtDateLoc('${DAY2}')`);
  check(await until(() => !dlg() && info().includes(shown2)), `${who}: the editor shows the new day ${shown2}: ${info()}`);
  check(JSON.stringify(feeDay(rid)) === JSON.stringify(['paid', DAY2]), `${who}: the new day is stored ${JSON.stringify(feeDay(rid))}`);
  check(await booked(rid, DAY2) && !await booked(rid, DAY1), `${who}: the booking moved to ${DAY2}`);
  w.close();
}

(async () => {
  await until(async () => (await fetch(B + 'sw.js').catch(() => null))?.ok);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Muster', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const comp = name => ({name, street: 'Weg 2', zip: '12345', city: 'Musterstadt', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051'});
  await call(CA, 'PUT', '/api/office/settings', {lang: 'de', company_fields: comp('Muster GmbH')});
  const ls = await call(CA, 'PUT', '/api/office/books/ledger/settings', {method: 'balance', size: 'small'});
  check(ls.http === 200, 'organisation: balance sheet chosen ' + ls.http);
  // organisation: the journal of the year books the fee on its day (clearing account to reminder fees received)
  const journal = ck => async (rid, day) => {
    const no = dbx('SELECT number FROM office_docs WHERE id=?', [rid])[0]?.number;
    const j = await call(ck, 'GET', `/api/office/books/ledger?year=${day.slice(0, 4)}&journal=1`);
    return (j.journal || []).some(x => x.day === day && x.doc === no && x.credit === '2700' && Number(x.amount) === 5);
  };
  await run('alice', CA, 'organisation', journal(CA));

  // a person without organisation: the income statement of the year counts it, the day is the stored one (checked above)
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  await call(CF, 'PUT', '/api/office/settings', {lang: 'de', currency: 'EUR', company_fields: comp('Frida Beispiel')});
  const euer = async (rid, day) => {
    if (feeDay(rid)[1] !== day) return false;
    const e = await call(CF, 'GET', `/api/office/books/euer?year=${day.slice(0, 4)}`);
    return (e.income || []).some(x => x.key === 'fee' && x.gross === '5.00');
  };
  await run('frida', CF, 'freelancer', euer);

  console.log(`p2912_dunning_day_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
