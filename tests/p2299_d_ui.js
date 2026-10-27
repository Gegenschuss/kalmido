// 2.299.0 UI tests of part D (#3193; own container, start.sh). jsdom. Invented companies and figures only:
// - document sheet of an invoice whose figures do not add up: below the recognised values one folded block "N hints on this
//   receipt" with the sentences ("Please check: net 400.00 + VAT 76.00 ...", "Missing: tax number ..."); Hide hints folds it
//   to "N hints hidden" (one undo step: Undo brings the block back)
// - the receipts list of the bookkeeping: "Only with hints" with the number, the row tagged "With hints", the filter keeps
//   only that receipt
// - phone width: the block is there
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const {execFileSync} = require('child_process');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2299D_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const head = ['Muster Werkstatt GmbH', 'Industrieweg 12', '12345 Beispielstadt', '', 'Rechnung an:', 'Beispiel Agentur', 'Hauptstraße 7', '54321 Musterdorf', ''];
const BAD = [...head, 'Rechnungsnummer: RE-2026-502', 'Rechnungsdatum: 12.10.2026', '1  4 h  Wartung Druckmaschine  320,00 EUR', '2  1 Stk  Ersatzteil Walze  80,00 EUR',
  'Nettobetrag  400,00 EUR', 'zzgl. 19 % MwSt  76,00 EUR', 'Gesamtbetrag  496,00 EUR'].join('\n');
const OK = [...head, 'USt-IdNr.: DE273645199', 'Rechnungsnummer: RE-2026-501', 'Rechnungsdatum: 12.10.2026', '1  4 h  Wartung Druckmaschine  320,00 EUR',
  '2  1 Stk  Ersatzteil Walze  80,00 EUR', 'Nettobetrag  400,00 EUR', 'zzgl. 19 % MwSt  76,00 EUR', 'Gesamtbetrag  476,00 EUR'].join('\n');

async function upload(name, text, amount) {
  const fd = new FormData();
  fd.append('ws', 'private');
  fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json();
  const id = (up.ids || [])[0];
  const doc = await until(async () => { const x = await call('GET', `/api/docs/${id}`); return x.state === 'done' ? x : null; }, 150);
  await call('PATCH', `/api/docs/${id}`, {amount, date: '2026-10-12'});
  await call('PUT', `/api/docs/${id}/receipt`, {category: 'Material', vat_pct: '19', keep: true});
  return [id, doc];
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: (st.settings?.features || '') + ',docs,files,office'});
  const [D, doc] = await upload('rechnung-falsch.txt', BAD, '496.00');
  const [D2] = await upload('rechnung-ok.txt', OK, '476.00');
  check((doc?.checks?.items || []).some(x => x.code === 'calc_sum'), 'setup: the check found the sum ' + JSON.stringify(doc?.checks || {}).slice(0, 200));

  // ================= the document sheet
  const v = await boot({user: 'alice', hash: `docs/${D}`}), e = v.document;
  const blk = await until(() => e.querySelector('.rx-slot details.rck'), 80);
  const t = (blk?.textContent || '').replace(/\s+/g, ' ');
  check(blk && /hints on this receipt/.test(blk.querySelector('summary')?.textContent || ''), 'one folded block "N hints on this receipt" ' + t.slice(0, 120));
  check(blk && !blk.open && blk.classList.contains('rck-warn'), 'folded, marked as a warning');
  check(/Please check: net 400\.00 \+ VAT 76\.00 gives 476\.00, the receipt says 496\.00/.test(t) && /Missing: tax number or VAT ID/.test(t), 'the sentences ' + t.slice(0, 300));
  check(e.querySelectorAll('.rck-list li.rck-w').length >= 2, 'warnings marked');
  blk.querySelector('[data-rck^="hide"]').click();
  await until(() => e.querySelector('.rck-off'), 80);
  check(e.querySelector('.rck-off') && !e.querySelector('details.rck') && /hints hidden/.test(e.querySelector('.rck-off')?.textContent || ''), 'Hide hints: folded to "N hints hidden"');
  check(v.eval(`HIST.undo.length && /Hints hidden/.test(HIST.undo[HIST.undo.length - 1].label)`), 'Hide = one undo step');
  await v.eval(`histStep('undo')`);
  await until(() => e.querySelector('details.rck'), 80);
  check(e.querySelector('details.rck') && !e.querySelector('.rck-off'), 'Undo: the block is back');
  v.close();
  const v2 = await boot({user: 'alice', hash: `docs/${D2}`}), e2 = v2.document;
  await until(() => e2.querySelector('.rx-slot'), 60);
  check(!e2.querySelector('.rck'), 'a complete invoice: no block');
  v2.close();

  // ================= the receipts list of the bookkeeping
  const w = await boot({user: 'alice', hash: 'office/books/receipts'}), g = w.document;
  await until(() => g.querySelector('#rcl-hints'), 80);
  w.eval(`rclSet({per: 'custom', from: '2026-01-01', to: '2026-12-31'})`);
  await until(() => g.querySelector(`.rcl-list [data-id="${D2}"]`), 80);
  const lbl = g.querySelector('.rcl-hints')?.textContent || '';
  check(/Only with hints/.test(lbl) && /\b1\b/.test(lbl), 'the filter "Only with hints" with the number ' + lbl.trim());
  check(/With hints/.test(g.querySelector(`.rcl-list [data-id="${D}"]`)?.textContent || '') && !/With hints/.test(g.querySelector(`.rcl-list [data-id="${D2}"]`)?.textContent || ''),
    'the row with hints is tagged, the other not');
  const cb = g.querySelector('#rcl-hints');
  cb.checked = true; cb.dispatchEvent(new w.window.Event('change', {bubbles: true}));
  await until(() => !g.querySelector(`.rcl-list [data-id="${D2}"]`) && g.querySelector(`.rcl-list [data-id="${D}"]`), 80);
  check(!g.querySelector(`.rcl-list [data-id="${D2}"]`) && g.querySelector(`.rcl-list [data-id="${D}"]`), 'the filter keeps only the receipt with hints');
  w.close();

  // ================= phone width
  const m = await boot({user: 'alice', hash: `docs/${D}`, mobile: true}), f = m.document;
  const mb = await until(() => f.querySelector('details.rck > summary'), 80);
  check(mb && f.querySelector('details.rck'), 'phone: the block is there');
  console.log(`p2299_d_ui: ${ok} ok, ${F.length} failed`);
  m.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
