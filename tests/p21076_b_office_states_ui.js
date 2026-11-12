// 2.1076.0 UI tests, part B (#5450): the office says empty / loading / failed / no access with the one block of the lists
// kalmido-suite: fresh
// (render.js emptyState / loadingHtml / errorState / noAccessState), own container (start.sh, mode workspaces), jsdom, a phone
// (about 360 px: mobile) and a computer (1280 px). Invented companies, people and figures only.
// - an office without receipts (Fiona, no organisation: her private office): Receipts shows a real empty state with its text
//   and "Upload receipt", no filter block and no "nothing matches"
// - a failed load (the request held in the page and answered with a refusal) shows the reason and "Try again" -- never the
//   empty text; "Try again" really loads: the receipt list of the organisation, the bank page of the private office
// - the start page keeps the place of "bookings without a receipt" while its counter loads (no jump when it comes)
// - the figures without any payment: one empty state, no empty axis
// - the role Bookkeeping: no "Correspondence" in the office menu; the page itself says "No access" in the one form
// Every wait is on a real state of the page.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = TC.today();
// requests matching re ("METHOD /url") wait in w.__held until the test calls go() (the real request) or fail(text, status)
const hold = (w, re) => {
  w.__held = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => re.test(`${o.method || 'GET'} ${u}`)
    ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: (msg, st = 400) => res(new Response(JSON.stringify({error: msg}), {status: st, headers: {'content-type': 'application/json'}}))}))
    : f1(u, o);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };

function tinyPdf(text) {  // a one-page PDF with a text layer
  const s = `BT /F1 12 Tf 40 700 Td (${text}) Tj ET`;
  const o = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${s.length} >>\nstream\n${s}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  o.forEach((x, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${x}\nendobj\n`; });
  const xr = out.length; out += `xref\n0 ${o.length + 1}\n0000000000 65535 f \n` + offs.map(n => String(n).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${o.length + 1} /Root 1 0 R >>\nstartxref\n${xr}\n%%EOF\n`;
}
async function receipt(ck, ws, name, amount, day) {
  const fd = new FormData(); fd.append('ws', ws); fd.append('files', new Blob([tinyPdf('Beleg ' + name)], {type: 'application/pdf'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  const j = await r.json(); check(r.status === 201, 'upload ' + name + ' ' + r.status);
  const id = j.ids[0];
  check((await call(ck, 'PATCH', `/api/docs/${id}`, {amount, date: day})).http === 200, 'amount + date ' + name);
  check((await call(ck, 'PUT', `/api/docs/${id}/receipt`, {category: 'Material', vat_pct: '19', keep: true})).http === 200, 'receipt ' + name);
  return id;
}
const txt = (d, sel) => d.querySelector(sel)?.textContent || '';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Gegenlicht Werkstatt', admin_id: me.id});
  const ws = `org:${org.id}`;
  await call(CA, 'PATCH', '/api/settings', {workspace: ws});
  for (const [u, n] of [['carl', 'Carl Books'], ['fiona', 'Fiona Solo']]) {
    await call(CA, 'POST', '/api/users', {username: u, display_name: n, password: 'password123', email: `${u}@example.com`});
    if (u === 'carl') check((await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'carl@example.com', role: 'accounting'})).http < 300, 'carl joins as the bookkeeping');
    const ck = await login(u);
    await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: u === 'carl' ? ws : 'private'});
  }
  const CF = await login('fiona');
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'fiona has no organisation');
  await receipt(CA, ws, 'papier.pdf', '119.00', today);
  // Carl in the office group "Bookkeeping" (levels: every area at least read, the money areas edit): the role the office rights
  // show as Bookkeeping; Correspondence was in his menu and its page said "Only for admins"
  const carlId = ((await call(CA, 'GET', '/api/users')).users || []).find(x => x.username === 'carl')?.id;
  check((await call(CA, 'PUT', `/api/office/rights/people/${carlId}`, {groups: ['tpl:bookkeeping']})).http < 300, 'carl gets the office group Bookkeeping');

  for (const mobile of [true, false]) {
    const tag = mobile ? 'p360' : 'd1280';
    // ================= Fiona, private office without a single receipt: a real empty state, no filters
    let w = await boot({user: 'fiona', mobile, hash: 'office/receipts'}), d = w.document;
    check(await until(() => d.querySelector('#view .rcl-none')), `${tag}: Fiona: Receipts shows the empty state`);
    check(/No receipts yet\./.test(txt(d, '#view .rcl-none')), `${tag}: Fiona: it says so in a sentence`);
    check(!!d.querySelector('#view .rcl-none [data-rcl="upfirst"]') && /Upload receipt/.test(txt(d, '#view .rcl-none [data-rcl="upfirst"]')), `${tag}: Fiona: with "Upload receipt"`);
    check(!d.querySelector('#view .rcl-filters') && !/Nothing matches/.test(txt(d, '#view')), `${tag}: Fiona: no filter block, no "nothing matches" for 0 receipts`);
    check(await until(() => !d.querySelector('#view .eload')), `${tag}: Fiona: nothing left loading`);

    // ================= Fiona, the bank page fails to load: the reason + "Try again", which then loads the page
    hold(w, /^GET \/api\/office\/bank\/tx\?/);
    w.location.hash = '#office/bank';
    check(await until(() => w.__held.length >= 1), `${tag}: Fiona: the bank list is requested (held)`);
    check(!!d.querySelector('#view .eload') && !/No bookings yet/.test(txt(d, '#view')), `${tag}: Fiona: while it loads: the loading block, not the empty text`);
    w.__held.forEach(h => h.fail('The bank list is resting for the test'));
    check(await until(() => d.querySelector('#view .eerr [data-esretry]')), `${tag}: Fiona: the failure shows "Try again"`);
    check(/The bank list is resting for the test/.test(txt(d, '#view .eerr')) && /Try again/.test(txt(d, '#view .eerr [data-esretry]')), `${tag}: Fiona: with the reason`);
    check(!/No bookings yet/.test(txt(d, '#view')) && !d.querySelector('#view .bnkbar'), `${tag}: Fiona: a failure never looks empty`);
    unhold(w);
    d.querySelector('#view .eerr [data-esretry]').click();
    check(await until(() => d.querySelector('#view .bnkbar') && /No bookings yet/.test(txt(d, '#view .empty'))), `${tag}: Fiona: "Try again" loads the bank page (its bar and its real empty state)`);
    check(!d.querySelector('#view .eerr'), `${tag}: Fiona: the failure is gone`);
    check(!!d.querySelector('#view .empty [data-bnk="imp"]'), `${tag}: Fiona: the empty bank offers the import`);
    w.close();

    // ================= Alice, organisation: the receipt list fails, "Try again" brings the receipt
    w = await boot({user: 'alice', mobile, hash: 'office/start'}); d = w.document;
    check(await until(() => d.querySelector('#view .ofmstart')), `${tag}: Alice: the office start page`);
    hold(w, /^GET \/api\/office\/books\/receipts\?/);
    w.location.hash = '#office/receipts';
    check(await until(() => w.__held.length >= 1), `${tag}: Alice: the receipts are requested (held)`);
    w.__held.forEach(h => h.fail('The receipts are resting for the test'));
    check(await until(() => d.querySelector('#view .eerr [data-esretry]')), `${tag}: Alice: the failed list shows "Try again"`);
    check(/The receipts are resting for the test/.test(txt(d, '#view .eerr')), `${tag}: Alice: with the reason`);
    check(!d.querySelector('#view .rcl-empty') && !d.querySelector('#view .rcl-none') && !d.querySelector('#view .rcl-filters'), `${tag}: Alice: no empty state, no filters while it failed`);
    unhold(w);
    d.querySelector('#view .eerr [data-esretry]').click();
    check(await until(() => d.querySelectorAll('#view .rcl-list > li').length === 1), `${tag}: Alice: "Try again" loads the list`);
    check(/papier/.test(txt(d, '#view .rcl-list')), `${tag}: Alice: the receipt is there`);
    check(!d.querySelector('#view .eerr'), `${tag}: Alice: the failure is gone`);

    // ================= the figures without a payment: one empty state, no empty axis
    w.location.hash = '#office/kpi';
    check(await until(() => d.querySelector('#view .kptiles')), `${tag}: Alice: the figures`);
    check(!!d.querySelector('#view .kpchart .kpnone') && !d.querySelector('#view .kpbars'), `${tag}: Alice: no payment yet: the empty state instead of the axis`);
    check(/No payments received in/.test(txt(d, '#view .kpnone')), `${tag}: Alice: it says why`);

    // ================= the start page keeps the place of "bookings without a receipt" while the counter loads
    if (mobile) {
      w.eval("BNR.cnt = undefined; BNR.cntAt = 0; LS.set('bnrCnt.' + OFC.info.org_id, 1)");  // as on a first visit
      hold(w, /\/api\/office\/bank\/noreceipt\/count/);
      w.location.hash = '#office/start';
      check(await until(() => w.__held.length >= 1), `${tag}: Alice: the start page asks for the counter (held)`);
      check(await until(() => d.querySelector('#view .ofmstart .bnrwait .eload')), `${tag}: Alice: its row keeps the place while it loads`);
      check(!!d.querySelector('#view .ofmstart .ofl'), `${tag}: Alice: the menu rows are below it at once`);
      w.__held.forEach(h => h.go());
      unhold(w);
      check(await until(() => !d.querySelector('#view .bnrwait')), `${tag}: Alice: once there, the place goes (no booking without a receipt)`);
    }
    w.close();

    // ================= Carl, the bookkeeping: no "Correspondence" in the menu, the page says "No access" in the one form
    w = await boot({user: 'carl', mobile, hash: 'office/start'}); d = w.document;
    check(await until(() => w.eval('typeof OFC === "object" && !!OFC.info') && d.querySelector('#view .ofmstart')), `${tag}: Carl: the office start`);
    check(w.eval("OFC.info.role") === 'accounting' && w.eval("!!(ofm_lv() || {}).books"), `${tag}: Carl: the bookkeeping, ruled by the office group`);
    check(w.eval("ofm_items().some(i => i.key === 'books')"), `${tag}: Carl: the bookkeeping is in his menu`);
    check(w.eval("!ofm_items().some(i => i.key === 'letters')"), `${tag}: Carl: no Correspondence in his menu`);
    check(!d.querySelector('#view [data-ofm="letters"]'), `${tag}: Carl: no Correspondence row on the start page`);
    w.location.hash = '#office/letters';
    check(await until(() => d.querySelector('#view .enoacc')), `${tag}: Carl: a direct link shows the no-access block`);
    check(/No access/.test(txt(d, '#view .enoacc')) && /Only for admins of the office/.test(txt(d, '#view .enoacc')), `${tag}: Carl: it says why`);
    w.close();
  }
  // Alice (admin) keeps the point
  const w = await boot({user: 'alice', hash: 'office/start'});
  check(await until(() => w.eval('typeof OFC === "object" && !!OFC.info')), 'Alice: the office is loaded');
  check(w.eval("ofm_items().some(i => i.key === 'letters')"), 'Alice, admin: Correspondence stays in the menu');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
