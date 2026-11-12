// kalmido-suite: fresh
// 2.1042.0 (#5815) UI tests: the discount of a quotation as percent or fixed amount, and a position's own discount. Own
// container (start.sh), jsdom, invented services and amounts. As a person WITHOUT an organisation (her personal office;
// freelancer-matrix: office).
// - the discount field has a switch % / EUR; switched to EUR and 500 typed, the quotation shows the line "Discount
//   -500.00" with "Fixed amount on the marked positions" and the gross of the acceptance case (2,638.43); back to %, the
//   amount is gone and the percent field is there again
// - a position row has a quiet "Discount %" button; tapped, its percent field appears, 10 typed: the row shows
//   "2,000.00 less 10 % discount (-200.00)" and its amount 1,800.00; the button is gone while the position has a discount
// - an amount over the discountable positions: the server refuses it with the sum, the stored 500 stay
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEATURES = 'cal,collab,comments,contacts,files,clients,office';
const svc = (title, qty, rate, tax = 'standard', unit = 'day') => ({kind: 'service', title, qty, unit, rate, tax, raw_fee: 0, producing: 0, in_handling: 0, in_markup: 0, intext: 'intern', cost: 0, discountable: 1});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, AK);
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK);
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATURES});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  await call('PUT', '/api/office/settings', {lang: 'en', currency: 'EUR'});
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Campaign', raw_mode: 'none', producing_on: 0,
    items: [svc('Direction', 2, 1000), svc('Book licence', 1, 1000, 'reduced', 'flat')]});
  check(doc.http === 201, 'a quotation with 19 % and 7 % ' + doc.http);
  const D = doc.id, get = () => call('GET', `/api/office/docs/${D}`);

  const w = await boot({user: 'frida', hash: `office/offers/${D}`}), d = w.document;
  await until(() => d.querySelector('.ofdeditor .ofdits [data-k="rate"]'));
  // ---- a position's own discount
  const row = t => [...d.querySelectorAll('.ofdeditor .ofdits .ofdit')].find(li => li.querySelector('[data-k="title"]')?.value === t);
  check(row('Direction')?.querySelector('[data-ofd="it-pdisc"]') && !row('Direction')?.querySelector('[data-k="discount_pct"]'), 'a position without a discount: the button "Discount %", no field');
  click(w, row('Direction').querySelector('[data-ofd="it-pdisc"]'));
  const pin = await until(() => row('Direction')?.querySelector('[data-k="discount_pct"]'));
  check(pin && !row('Direction').querySelector('[data-ofd="it-pdisc"]'), 'tapped: the percent field of the position shows');
  change(w, pin, '10');
  let x = await until(async () => { const j = await get(); return +j.items?.[0]?.discount_pct === 10 ? j : null; });
  check(x && x.totals?.lines?.find(l => l.title === 'Direction')?.total === 1800, 'saved: 10 % on the position, its amount 1800 ' + JSON.stringify(x?.totals?.lines?.[0] || {}));
  await until(() => /less 10 % discount/.test(row('Direction')?.textContent || ''));
  const rt = row('Direction')?.textContent || '';
  check(/2,000\.00/.test(rt) && /less 10 % discount/.test(rt) && /200\.00/.test(rt) && /1,800\.00/.test(rt), 'on screen: "2,000.00 less 10 % discount (-200.00)" and 1,800.00 in the row: ' + rt.replace(/\s+/g, ' ').slice(0, 200));
  check(row('Book licence')?.querySelector('[data-ofd="it-pdisc"]') && !row('Book licence')?.querySelector('[data-k="discount_pct"]'), 'the other position keeps only its button');

  // ---- the discount of the whole quotation as a fixed amount
  const mode = await until(() => d.querySelector('#ofd-discount_mode'));
  check(mode && mode.value === 'pct' && d.querySelector('#ofd-discount_pct'), 'the discount field: percent by default, with the switch');
  change(w, mode, 'amount');
  const amt = await until(() => d.querySelector('#ofd-discount_amount'));
  check(amt && !d.querySelector('#ofd-discount_pct'), 'switched to the amount: the amount field instead of the percent');
  change(w, amt, '500');
  x = await until(async () => { const j = await get(); return +j.discount_amount === 500 ? j : null; });
  check(x && x.totals?.gross === 2638.43 && x.totals?.net === 2300, 'saved: 500 off, net 2300.00, gross 2638.43 ' + (x && x.totals?.gross));
  await until(() => /Fixed amount on the marked positions/.test(d.querySelector('.ofdautos')?.textContent || ''));
  const at = d.querySelector('.ofdautos')?.textContent || '';
  check(/Fixed amount on the marked positions/.test(at) && /500\.00/.test(at), 'on screen: the discount line "Fixed amount on the marked positions" with 500.00');
  await until(() => /2,638\.43/.test(d.querySelector('#ofd-totals')?.textContent || ''));
  check(/2,638\.43/.test(d.querySelector('#ofd-totals')?.textContent || ''), 'on screen: the total 2,638.43');
  check(d.querySelector('#ofd-discount_mode')?.value === 'amount' && d.querySelector('#ofd-discount_amount')?.value.replace(/[^0-9]/g, '') === '500', 'after the save the switch stays on the amount, 500 in the field');

  // ---- over the discountable positions: refused, the 500 stay
  const big = await call('PATCH', `/api/office/docs/${D}`, {discount_amount: 5000});
  check(big.http === 400 && /2,800\.00|2\.800,00/.test(big.error || big.message || JSON.stringify(big)), 'an amount over 2800.00 is refused, naming the sum ' + big.http);
  check(+(await get()).discount_amount === 500, 'the 500 stay');

  // ---- back to percent
  change(w, d.querySelector('#ofd-discount_mode'), 'pct');
  x = await until(async () => { const j = await get(); return j.discount_amount == null ? j : null; });
  check(x && x.totals?.discount === 0, 'back to percent: the amount is cleared, no discount');
  await until(() => d.querySelector('#ofd-discount_pct'));
  check(d.querySelector('#ofd-discount_pct') && !/Fixed amount/.test(d.querySelector('.ofdautos')?.textContent || ''), 'on screen: the percent field again, no amount line');

  console.log(`p5815_discount_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
