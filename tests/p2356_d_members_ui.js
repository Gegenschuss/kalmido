// kalmido-suite:
// 2.356.0 D UI test (#3129, #3006, #3007): the office for members. Own container (start.sh), Firefox, 1280 px. Invented
// people only. freelancer-matrix: office -- fiona has no organisation (her own admin): no members' line, no "Submit receipt".
// - bob (member of Alpha Studio): Quotes & invoices shows the line "Bookkeeping, cash book and receipts are only seen by admins
//   and the bookkeeping" with "Submit receipt"; the menu point Receipts is "Submit receipt" (#office/receipts), no Bookkeeping; the page takes a
//   file (POST /api/office/receipts/submit) -> toast "Receipt handed in" -> a row "Handed in" under "My receipts handed in"
// - a direct link to #office/cashbook: the same explanation with the way to hand in, no dead end
// - Settings > Company for bob: the hint "Only admins and the bookkeeping change this", the fields locked (dashed), the company
//   name shows the organisation's name
// - alice (admin): Office > Receipts lists the receipt "Handed in by Bob Member"; the palette finds "Open items" by "OP" and
//   opens the invoice list filtered to the open items
// P2356DU_NOSTART=1 = the server already runs. Screenshots: P2356DU_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2356_d_members_ui', check, shots: 'P2356DU_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2356DU_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const me = await call(CA, 'GET', '/api/state');
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha Studio', admin_id: me.me.id});
  check(org.id > 0, 'the organisation Alpha Studio');
  const CK = {};
  for (const [u, n] of [['bob', 'Bob Member'], ['fiona', 'Fiona Solo']]) {
    await call(CA, 'POST', '/api/users', {username: u, display_name: n, password: 'password123', email: `${u}@example.com`});
    if (u === 'bob') check((await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'})).http < 300, 'bob joins Alpha Studio as member');
    CK[u] = await login(u);
    await call(CK[u], 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, ...(u === 'bob' ? {workspace: `org:${org.id}`} : {})});
  }
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`});
  check(!((await call(CK.fiona, 'GET', '/api/state')).me.workspaces || []).length, 'P4: fiona has no organisation');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const fresh = async (ev, nav, u) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`).catch(() => 0);
    check(await signIn(ev, u) === 200, `${u} signs in`);
  };

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // ================= bob, member: the line on the start, the menu point, hand in a receipt
    await fresh(ev, nav, 'bob');
    await nav(B + '#office/offers');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('.office .ofcmbr [data-ofc-submit]')`, 80), '#3006: the members\' line with "Submit receipt" on Quotes & invoices');
    check(await ev(`/only seen by admins and the bookkeeping/.test(document.querySelector('.office .ofcmbr')?.textContent || '')`), '#3006: the line says why');
    check(await ev(`OFC.info.submit === true && ofm_items().some(i => i.key === 'receipts' && i.name === 'Submit receipt') && !ofm_items().some(i => ['books', 'cashbook'].includes(i.key))`), '#3129: the menu point Receipts is "Submit receipt", no Bookkeeping / Cash book');
    await shot('p2356d-member-offers.png');
    await ev(`(() => { document.querySelector('.office .ofcmbr [data-ofc-submit]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.office[data-ofctab="receipts"] .rsb #rsb-files') && !!document.querySelector('.rsb-empty')`, 60), '#3129: "Submit receipt" opens, nothing handed in yet');
    await ev(`(() => { const s = 'BT /F1 12 Tf 40 700 Td (Beleg Taxi) Tj ET';
      const o = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
        '<< /Length ' + s.length + ' >>\\nstream\\n' + s + '\\nendstream', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
      let out = '%PDF-1.4\\n'; const offs = [];
      o.forEach((x, i) => { offs.push(out.length); out += (i + 1) + ' 0 obj\\n' + x + '\\nendobj\\n'; });
      const xr = out.length; out += 'xref\\n0 ' + (o.length + 1) + '\\n0000000000 65535 f \\n' + offs.map(n => String(n).padStart(10, '0') + ' 00000 n \\n').join('');
      out += 'trailer\\n<< /Size ' + (o.length + 1) + ' /Root 1 0 R >>\\nstartxref\\n' + xr + '\\n%%EOF\\n';
      const dt = new DataTransfer(); dt.items.add(new File([out], 'taxi-2356.pdf', {type: 'application/pdf'}));
      const i = document.querySelector('#rsb-files'); i.files = dt.files; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `(() => { const t = document.querySelector('#toast'); return !!t && !t.classList.contains('hidden') && /Receipt handed in/.test(t.textContent); })()`, 60), '#3129: toast "Receipt handed in"');
    check(await ready(ev, `[...document.querySelectorAll('.rsb-list .rsb-row')].some(li => /taxi-2356/.test(li.textContent) && /Handed in/.test(li.textContent))`, 60), '#3129: the row under "My receipts handed in" with its status');
    await shot('p2356d-member-submit.png');

    // ================= a locked page explains instead of a dead end
    await nav(B + '#office/cashbook');
    check(await ready(ev, `!!document.querySelector('.office .ofclocked .ofcmbr [data-ofc-submit]')`, 60), '#3006: #office/cashbook explains and offers "Submit receipt"');

    // ================= Settings > Company: locked fields with a hint, the organisation's name
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set #os-name') && !!document.querySelector('.ofclockhint')`, 60), '#3006: the hint "Only admins and the bookkeeping change this"');
    check(await ev(`(() => { const n = document.querySelector('#os-name'); return n.matches(':disabled') && n.value === 'Alpha Studio' && getComputedStyle(n).borderTopStyle === 'dashed'; })()`),
      '#3006: company name locked (dashed) and suggested from the organisation ' + await ev(`(() => { const n = document.querySelector('#os-name'); return n.value + ' / ' + getComputedStyle(n).borderTopStyle; })()`));
    await shot('p2356d-member-settings.png');

    // ================= fiona (no organisation): her own admin, nothing of it
    await fresh(ev, nav, 'fiona');
    await nav(B + '#office/offers');
    check(await ready(ev, `typeof OFC === 'object' && !!OFC.info && !!document.querySelector('.office[data-ofctab="offers"]')`, 80), 'P4: fiona\'s office opens');
    check(await ev(`!document.querySelector('.ofcmbr') && OFC.info.submit === false && ofm_items().some(i => i.key === 'receipts' && i.name === 'Receipts')`), 'P4: no members\' line, no "Submit receipt" for her own office');

    // ================= alice (admin): the receipt handed in, the palette "OP"
    await fresh(ev, nav, 'alice');
    await nav(B + '#office/receipts');
    check(await ready(ev, `[...document.querySelectorAll('.rsb-in [data-rsb="open"]')].some(b => /taxi-2356/.test(b.textContent) && /Handed in by Bob Member/.test(b.textContent))`, 80), '#3129: Office > Receipts lists the receipt handed in by Bob');
    await shot('p2356d-admin-receipts.png');
    check(await ev(`!document.querySelector('.ofcmbr')`), '#3006: no members\' line for the admin');
    await ev(`(() => { openPalette(); const i = document.querySelector('.palette input'); i.value = 'OP'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/Open items/.test(document.querySelector('.palette')?.textContent || '')`, 20), '#3007: the palette finds "Open items" by "OP"');
    await ev(`(() => { closePalette(); palAll().find(x => x.id === 'v:o-openitems').fn(); return 1; })()`);
    check(await ready(ev, `typeof OFD === 'object' && OFD.kind === 'invoice' && OFD.status === 'open' && document.querySelector('#ofd-status')?.value === 'open'`, 60), '#3007: it opens the invoices filtered to the open items');
    await shot('p2356d-open-items.png');
  }, false);

  console.log(`p2356_d_members_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
