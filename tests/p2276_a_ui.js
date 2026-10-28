// 2.276.0 A UI test (#3039): the office for the first day. Own container (start.sh), Firefox, 1280 px and 390 px. Invented
// people only. freelancer-matrix: office (no new route; GET /api/office/settings has a new field "used") -- carol and dave
// have no organisation (each the admin of the own office, P4).
// - computer: a fresh office without a kept point opens on Quotes & invoices; the group Money is folded; opened by hand it
//   shows Receipts, Bank, Bookkeeping, Cash book and "Show more" (cash flow, figures, travel, entertainment, subscriptions wait
//   until used); the hand's choice stays after reloading
// - Receipts (#office/receipts): the upload of the bookkeeping, the kinds (entertainment, travel) and the list; a file through
//   "Photograph receipt" -> POST /api/docs -> the receipt sheet -> a row in the list; then Money is open on its own
// - the Pipeline is the start only once there is an inquiry; the first invoice opens Money and shows the figures
// - phone 390: the start page folds Money (heading button, aria-expanded), a tap opens it
// P2276A_NOSTART=1 = the server already runs. Screenshots: P2276A_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2276_a_ui', check, shots: 'P2276A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2276A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,docs';
const today = TC.today();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const CK = {};
  for (const [u, n] of [['carol', 'Carol Solo'], ['dave', 'Dave Solo']]) {
    await call(CA, 'POST', '/api/users', {username: u, display_name: n, password: 'password123', email: `${u}@example.com`});
    CK[u] = await login(u);
    await call(CK[u], 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
    check(!((await call(CK[u], 'GET', '/api/state')).me.workspaces || []).length, `P4: ${u} has no organisation`);
  }
  const st = await call(CK.carol, 'GET', '/api/office/settings');
  check(st.role === 'admin' && st.personal === 1 && st.used && Object.values(st.used).every(v => v === false), 'P4: carol is the admin of her own office, nothing used yet ' + JSON.stringify(st.used));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  const fresh = async (ev, nav, u) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`).catch(() => 0);
    check(await signIn(ev, u) === 200, `${u} signs in`);
  };
  const money = `document.querySelector('#side [data-g="office:money"]')?.getAttribute('aria-expanded')`;
  const side = `[...document.querySelectorAll('#side [data-ofmg="money"] [data-ofm]')].map(b => b.dataset.ofm).join()`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    // ================= phone 390 first (dave's office is still empty)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await fresh(ev, nav, 'dave');
    await nav(B + '#office');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('#view .ofmstart [data-ofmg="money"]')`, 80), 'phone: the office start page');
    check(await ev(`(() => { const s = document.querySelector('#view .ofmstart [data-ofmg="money"]'), b = s.querySelector('[data-act="ofm-group"]'); return s.classList.contains('closed') && b?.getAttribute('aria-expanded') === 'false' && !s.querySelector('[data-ofm]'); })()`), 'phone: Money folded on the start page');
    check(await ev(`!!document.querySelector('#view .ofmstart [data-ofmg="sell"] [data-ofm="offers"]')`), 'phone: Sell stays open');
    await shot('p2276a-phone-start.png');
    await click(ev, '#view [data-act="ofm-group"]');
    check(await ready(ev, `(() => { const s = document.querySelector('#view .ofmstart [data-ofmg="money"]'); return !!s && !s.classList.contains('closed') && s.querySelector('[data-act="ofm-group"]').getAttribute('aria-expanded') === 'true' && !!s.querySelector('[data-ofm="receipts"]') && !!s.querySelector('[data-act="ofm-more"]') && !s.querySelector('[data-ofm="kpi"]'); })()`, 20), 'phone: a tap opens Money (Receipts, "Show more", no figures yet)');
    await click(ev, '#view [data-act="ofm-more"]');
    check(await ready(ev, `!!document.querySelector('#view .ofmstart [data-ofmg="money"] [data-ofm="kpi"]') && !document.querySelector('#view [data-act="ofm-more"]')`, 20), 'phone: "Show more" shows the waiting points');

    // ================= computer 1280: carol's fresh office
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await fresh(ev, nav, 'carol');
    await nav(B + '#office');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('.office[data-ofctab="offers"]') && /Quotations/.test(document.querySelector('#top h1')?.textContent || '')`, 80), '#3039: a fresh admin office opens on Quotations (2.380.0 #3409: was Quotes & invoices) ' + await ev(`document.querySelector('.office')?.dataset.ofctab`));
    check(await ready(ev, `${money} === 'false'`, 40), '#3039: Money folded at first');
    check(await ev(`!document.querySelector('#side [data-ofm="receipts"]') && !!document.querySelector('#side [data-ofm="offers"]')`), '#3039: folded = no points of Money, Sell open');
    await shot('p2276a-desktop-start.png');
    await click(ev, '#side [data-act="sbb-group"][data-g="office:money"]');
    check(await ready(ev, `${money} === 'true'`, 20), 'Money opens by hand');
    const pts = await ev(side);
    check(pts === 'receipts,bank,books,cashbook' && await ev(`!!document.querySelector('#side [data-ofmg="money"] [data-act="ofm-more"]')`), '#3039: Receipts first, points used later wait behind "Show more" ' + pts);
    await nav(B + 'static/icon.svg'); await nav(B + '#office/offers');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && ${money} === 'true'`, 80), '#3039: the hand\'s choice stays after reloading');
    await ev(`(() => { localStorage.removeItem('tasks.sbbUnfold'); return 1; })()`);
    // a direct link still opens a waiting point (and keeps it in the menu)
    await nav(B + '#office/kpi');
    check(await ready(ev, `!!document.querySelector('.office[data-ofctab="kpi"]') && !!document.querySelector('#side [data-ofm="kpi"][aria-current="page"]') && ${money} === 'true'`, 60), '#3039: #office/kpi by link: shown, Money open while on it');

    // ================= Receipts: upload + list
    await nav(B + '#office/receipts');
    check(await ready(ev, `!!document.querySelector('.office[data-ofctab="receipts"] .bk-photo #bk-file') && !!document.querySelector('#side [data-ofm="receipts"][aria-current="page"]')`, 80), '#3039: Office > Receipts with the upload');
    check(await ev(`/Office > Receipts/.test(document.querySelector('.bk-photohint')?.textContent || '') && /Dokumente/.test(document.querySelector('.bk-photohint').textContent)`), '#3039: the hint says where the receipt goes');
    check(await ev(`!!document.querySelector('.rcp-kinds a[href="#office/meals"]') && !!document.querySelector('.rcp-kinds a[href="#office/travel"]') && !document.querySelector('.rcl-top')`), '#3039: entertainment / travel as kinds, no way back to the bookkeeping');
    check(await ready(ev, `!!document.querySelector('#rcl-h') && !document.querySelector('[data-rcl="rc"]')`, 60), 'the list, still empty');
    await shot('p2276a-receipts-empty.png');
    await ev(`(() => { const s = 'BT /F1 12 Tf 40 700 Td (Beleg) Tj ET';
      const o = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
        '<< /Length ' + s.length + ' >>\\nstream\\n' + s + '\\nendstream', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
      let out = '%PDF-1.4\\n'; const offs = [];
      o.forEach((x, i) => { offs.push(out.length); out += (i + 1) + ' 0 obj\\n' + x + '\\nendobj\\n'; });
      const xr = out.length; out += 'xref\\n0 ' + (o.length + 1) + '\\n0000000000 65535 f \\n' + offs.map(n => String(n).padStart(10, '0') + ' 00000 n \\n').join('');
      out += 'trailer\\n<< /Size ' + (o.length + 1) + ' /Root 1 0 R >>\\nstartxref\\n' + xr + '\\n%%EOF\\n';
      window.__p2276 = null; const f0 = window.fetch; window.fetch = (u, x) => { const p = f0(u, x); if (String(u).endsWith('/api/docs') && x?.method === 'POST') p.then(r => r.clone().json()).then(j => { window.__p2276 = j; }, () => 0); return p; };
      const dt = new DataTransfer(); dt.items.add(new File([out], 'receipt-2276.pdf', {type: 'application/pdf'}));
      const i = document.querySelector('#bk-file'); i.files = dt.files; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `!!window.__p2276 && (window.__p2276.ids || []).length === 1`, 60), '#3039: the upload answers from /api/docs ' + await ev('JSON.stringify(window.__p2276)'));
    check(await ready(ev, `!!document.querySelector('.bk-sheet #bk-vat')`, 60), 'the receipt sheet opens after the upload');
    await ev(`(() => { const m = document.querySelector('.bk-sheet'); m.querySelector('#bk-cat').value = 'Software'; m.querySelector('#bk-vat').value = '19'; m.querySelector('#bk-amount').value = '119.00';
      m.querySelector('#bk-date').value = '${today}'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.bk-sheet') && [...document.querySelectorAll('[data-rcl="rc"]')].some(b => /119\\.00/.test(b.textContent))`, 80), '#3039: the receipt is a row of the list');
    await shot('p2276a-receipts-row.png');
    const st2 = await call(CK.carol, 'GET', '/api/office/settings');
    check(st2.used?.receipt === true && st2.used?.invoice === false, 'the server knows the first receipt ' + JSON.stringify(st2.used));
    await nav(B + 'static/icon.svg'); await nav(B + '#office/offers');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && ${money} === 'true' && !!document.querySelector('#side [data-ofm="cashflow"]')`, 80), '#3039: with a receipt Money is open on its own and shows the cash flow');

    // ================= Pipeline only with an inquiry
    check(await ev(`(() => { localStorage.removeItem('tasks.ofmLast'); return ofm_entry().key; })()`) === 'offers', '#3039: no inquiry: still Quotes & invoices');
    const deal = await call(CK.carol, 'POST', '/api/office/deals', {title: 'Example inquiry', contact: 'Erika Example', value: 1000});
    check(deal.http < 300, 'an inquiry for carol ' + deal.http);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.removeItem('tasks.ofmLast'); return 1; })()`);
    await nav(B + '#office');
    check(await ready(ev, `!!OFC.info?.used?.inquiry && !!document.querySelector('.office[data-ofctab="pipeline"]')`, 80), '#3039: with an inquiry the office opens on the Pipeline ' + await ev(`document.querySelector('.office')?.dataset.ofctab`));
    await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('.office[data-ofctab="offers"]')`, 60);
    await nav(B + 'static/icon.svg'); await nav(B + '#office');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('.office[data-ofctab="offers"]')`, 80), '#2616: the point used last still wins ' + await ev(`document.querySelector('.office')?.dataset.ofctab`));

    // ================= the first invoice (dave, phone office still without receipt): Money opens, the figures show
    const inv = await call(CK.dave, 'POST', '/api/office/docs', {kind: 'invoice', service_from: today, service_to: today, items: [{title: 'Edit', qty: 1, rate: 500}]});
    check(inv.http < 300, 'dave\'s first invoice ' + inv.http);
    await fresh(ev, nav, 'dave');
    await nav(B + '#office/offers');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && OFC.info.used?.invoice === true && ${money} === 'true'`, 80), '#3039: with an invoice Money is open on its own');
    check(await ev(`!!document.querySelector('#side [data-ofm="kpi"]') && !!document.querySelector('#side [data-ofm="cashflow"]') && !document.querySelector('#side [data-ofm="travel"]')`), '#3039: the figures and the cash flow show, travel still waits ' + await ev(side));
  }, false);

  console.log(`p2276_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
