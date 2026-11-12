// kalmido-suite: fresh
// 2.1064.0 UI test (#5818): a sent quotation without an answer past its "valid until", own container (start.sh;
// P5818_NOSTART=1 / KMT_NOSTART=1: a running server), jsdom. Invented companies and figures only.
// - the quotation list marks the row "expired" next to its number and client
// - the quotation itself shows the note "Valid until <date> - expired without an answer." with "Extend validity" and
//   "Mark as rejected"; "Extend validity" opens a dialog with a date two weeks ahead, OK -> the note goes, the server has the
//   new date, the list row loses its mark
// - "Mark as rejected" on a second one -> the status reads Rejected, the note goes
// - the bell's entry reads as text: "Quotation AN-1, client has expired without an answer" / "expires in 3 days"
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P5818_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ds = d => d.toISOString().slice(0, 10);
const day = n => { const d = new Date(); d.setHours(12, 0, 0, 0); d.setDate(d.getDate() + n); return ds(d); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  const cl = await call('POST', '/api/clients', {name: 'Nordlicht Studio GmbH', street: 'Hafenweg 2', zip: '20457', city: 'Hamburg', country: 'DE'});
  const sent = async title => {
    const d = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', client_id: cl.id, project_title: title,
      items: [{kind: 'service', title: 'Shooting', qty: 1, unit: 'day', rate: 900, tax: 'standard'}]});
    const p = await call('PATCH', `/api/office/docs/${d.id}`, {valid_until: day(-1), expect_updated_at: d.updated_at});
    check(p.http === 200 && p.valid_until === day(-1), `setup: "valid until" yesterday on ${title} ${p.http}`);
    const s = await call('POST', `/api/office/docs/${d.id}/status`, {status: 'sent'});
    check(s.status === 'sent', `setup: ${title} marked sent`);
    return d.id;
  };
  const A1 = await sent('Imagefilm Hafen'), A2 = await sent('Werbespot Kai');
  let w, d;

  // ================= the list marks it, the editor shows the note, "Extend validity" works
  w = await boot({user: 'alice', hash: 'office/offers'}); d = w.document;
  const row = await until(() => [...d.querySelectorAll('.ofdlist li')].find(li => li.querySelector(`[data-id="${A1}"]`) || li.dataset.id === String(A1)), 80);
  check(!!row && /Nordlicht Studio GmbH/.test(row.textContent) && row.querySelector('.ofe-exp') && /expired/.test(row.querySelector('.ofe-exp').textContent),
    'the list row of a sent quotation past its date reads "expired" next to the client: ' + (row?.textContent || '').replace(/\s+/g, ' ').slice(0, 160));
  w.close();

  w = await boot({user: 'alice', hash: `office/offers/${A1}`}); d = w.document;
  const note = await until(() => d.querySelector('.ofe-note'), 80);
  check(!!note && /expired without an answer/.test(note.textContent), 'the quotation shows the note "expired without an answer": ' + (note?.textContent || '').replace(/\s+/g, ' ').slice(0, 160));
  const ext = note?.querySelector('[data-ofd="ofe-ext"]'), rej = note?.querySelector('[data-ofd="kva-st"][data-st="declined"]');
  check(!!ext && /Extend validity/.test(ext.textContent) && !!rej && /Mark as rejected/.test(rej.textContent), 'the note offers "Extend validity" and "Mark as rejected"');
  click(w, ext);
  const dlg = await until(() => d.querySelector('.modal #ofd-ofe-date'), 40);
  check(!!dlg && dlg.value === day(14), `the dialog proposes two weeks from today ${dlg?.value} / ${day(14)}`);
  check(/Extend validity/.test(d.querySelector('.modal h3')?.textContent || ''), 'the dialog is titled "Extend validity"');
  click(w, d.querySelector('.modal .foot [data-m="ok"]'));
  check(await until(async () => (await call('GET', `/api/office/docs/${A1}`)).valid_until === day(14), 60), 'OK -> the server has the new date');
  check(await until(() => !d.querySelector('.ofe-note') && !d.querySelector('.modal #ofd-ofe-date'), 60), 'OK -> the dialog closes and the note is gone');
  w.close();
  w = await boot({user: 'alice', hash: 'office/offers'}); d = w.document;
  await until(() => d.querySelector('.ofdlist li'), 80);
  check(!d.querySelector(`.ofdlist [data-id="${A1}"]`)?.closest('li')?.querySelector('.ofe-exp'), 'the list row of the extended quotation has no mark any more');
  w.close();

  // ================= "Mark as rejected"
  w = await boot({user: 'alice', hash: `office/offers/${A2}`}); d = w.document;
  const rj = await until(() => d.querySelector('.ofe-note [data-ofd="kva-st"][data-st="declined"]'), 80);
  click(w, rj);
  check(await until(async () => (await call('GET', `/api/office/docs/${A2}`)).status === 'declined', 60), '"Mark as rejected" -> the quotation is rejected');
  check(await until(() => !d.querySelector('.ofe-note'), 60), '"Mark as rejected" -> the note is gone');

  // ================= the bell's entry as text
  const nt = x => w.eval(`newsText({kind: 'offerexp', data: ${JSON.stringify(x)}, actors: []}, {})`);
  check(/Quotation AN-7, Nordlicht Studio GmbH has expired without an answer/.test(nt({state: 'gone', number: 'AN-7', client: 'Nordlicht Studio GmbH'})), 'the bell: "has expired": ' + nt({state: 'gone', number: 'AN-7', client: 'Nordlicht Studio GmbH'}));
  check(/expires in 3 days/.test(nt({state: 'soon', days: 3, number: 'AN-8'})) && /expires today/.test(nt({state: 'soon', days: 0, number: 'AN-9'})), 'the bell: "expires in 3 days" / "expires today"');
  check(/quotation/.test(w.eval(`newsSummaryLine({items: [[{kind: 'offerexp', count: 1}, 0]]})`)), 'the bundle line names quotations, not the raw kind');
  w.close();

  console.log(`p5818_offer_expiry_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
