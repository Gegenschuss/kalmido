// kalmido-suite: fresh
// 2.439.0 (#3617) UI tests: the e-mail signature, own container (start.sh). jsdom. Invented companies and addresses only.
// - the send dialog of an invoice shows the signature, a tick to leave it off, the answer address (the company's), one sentence
//   on the sender; "Edit" opens the editor and a saved signature is in the open dialog at once
// - the editor: preview follows the text, "Fill from name and company data" puts the prefilled text back, sender name and
//   answer address are saved; without a logo no logo switch
// - Send with the tick off and another answer address carries both in the request
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2439AU_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  await call('PUT', '/api/office/settings', {lang: 'en', company_fields: {name: 'Studio Nordlicht GmbH', street: 'Weg 12', zip: '20457', city: 'Hamburg', country: 'DE', email: 'hallo@nordlicht.example', phone: '040 123456', vat_id: 'DE123456789', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktweg 5', zip: '50667', city: 'Koeln', country: 'DE', email: 'kunde@example.com'})).id;
  const inv = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL, service_from: '2026-10-01', items: [{title: 'Schnitt', qty: 1, rate: 100}]});
  const fin = await call('POST', `/api/office/docs/${inv.id}/finalize`);
  check(fin.http === 200, 'an invoice finalised ' + JSON.stringify(fin).slice(0, 160));

  const w = await boot({hash: 'office/offers/' + inv.id}); const d = w.document;
  await until(() => d.querySelector('[data-ofd="send"]'));
  d.querySelector('[data-ofd="send"]').click();
  await until(() => d.querySelector('#ofd-s-to'));
  check(d.querySelector('.ofm-sig')?.textContent.includes('Studio Nordlicht GmbH'), 'the send dialog shows the prefilled signature');
  check(d.querySelector('#ofm-on')?.checked, 'attached by default');
  check(d.querySelector('#ofm-reply')?.value === 'hallo@nordlicht.example', 'answer address = the company');
  check(!!d.querySelector('.ofm-send')?.nextElementSibling?.textContent, 'one sentence on the sender');

  d.querySelector('[data-ofmsig="edit"]').click();  // 2.500.0 (#4058): its own attribute
  await until(() => d.querySelector('#ofm-text'));
  check(!d.querySelector('#ofm-logo'), 'no logo, no logo switch');
  const ta = d.querySelector('#ofm-text');
  ta.value = 'Beste Gruesse\nTeam Nordlicht'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(d.querySelector('#ofm-prevtext').textContent === ta.value, 'the preview follows the text');
  check(d.querySelector('#ofm-prevlogo').hidden, 'no logo in the preview');
  d.querySelector('.ofm-dlg [data-m="prefill"]').click();
  check(ta.value.includes('Studio Nordlicht GmbH'), 'prefilled again');
  ta.value = 'Beste Gruesse\nTeam Nordlicht'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  d.querySelector('#ofm-name').value = 'Team Nordlicht';
  d.querySelector('.ofm-dlg [data-m="save"]').click();
  await until(() => !d.querySelector('#ofm-text'));
  await until(() => d.querySelector('.ofm-sig')?.textContent.startsWith('Beste Gruesse'));
  check(d.querySelector('.ofm-sig').textContent === 'Beste Gruesse\nTeam Nordlicht', 'the saved signature is in the open send dialog');
  const p = await call('GET', '/api/office/mail-profile');
  check(p.saved && p.signature === 'Beste Gruesse\nTeam Nordlicht' && p.from_name === 'Team Nordlicht', 'saved through the editor');

  // what Send carries
  d.querySelector('#ofm-on').checked = false;
  d.querySelector('#ofm-reply').value = 'einmal@nordlicht.example';
  const b = w.eval('(md => ofmSendBody(md))')(d.querySelector('.ofm-send').closest('.modal, [role="dialog"]') || d.body);
  check(b.signature === false && b.reply_to === 'einmal@nordlicht.example', 'Send carries the tick and the address ' + JSON.stringify(b));

  // 2.500.0 (#4058): the office's navigation carries data-ofm="<area>"; a click on it moves on and opens no signature editor.
  // Counted synchronously at the click (the editor is opened by the document's click listener), computer panel and phone list
  for (const mobile of [false, true]) {
    const w2 = await boot({hash: 'office', mobile}); const d2 = w2.document;
    const who = mobile ? 'phone' : 'computer';
    check(w2.eval('typeof ofmSigModal') === 'function', `${who}: the editor's function exists (the count below means something)`);
    w2.eval('window.__sig = 0; ofmSigModal = () => { window.__sig++; }');
    await until(() => d2.querySelector('[data-ofm]'));
    for (const key of ['cashbook', 'offers']) {
      const b2 = await until(() => d2.querySelector(`[data-ofm="${key}"]`));
      b2.click();
      check(w2.__sig === 0, `${who}: a click on the office's point ${key} opens no signature editor`);
      await until(() => w2.location.hash.startsWith(`#office/${key}`));
      if (mobile) { w2.location.hash = '#office'; await until(() => d2.querySelector('.ofmstart [data-ofm]')); }
    }
    check(!d2.querySelector('#ofm-text'), `${who}: no editor open after the clicks`);
  }

  console.log(`p2439_a_mailsig_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
