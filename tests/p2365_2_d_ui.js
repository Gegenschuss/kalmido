// kalmido-suite: fresh
// 2.365.2 D (#2789) UI tests: the office settings of the office tabs moved into Settings > Company & office. Own container
// (start.sh), jsdom, invented data only. freelancer-matrix: office
// - Company & office has the part "Bank & taxes" right after Company: tax reserve and VAT basis, tax dates, mileage
//   allowance per year, cash flow start balance and monthly check, cash boxes; each saves on change through its own route
//   (no bar of the settings form); settingsModal('biz-tax') lands there
// - the tabs Bookkeeping, Cash flow, Cash book and the logbook report keep a link there instead of the fields
// - Settings > Integrations has "E-invoice (Peppol)" leading to the Peppol access in Company & office (fields in one place)
// - Settings > Data has the office's part (export, import and transfer, legacy data); the master data file sits in the
//   office's part Data
// - the agent's office switch and the office's read access point to each other
// - the trips import is on the legacy data page; its number counters and the receipt's SKR account link to the settings
// - the same for a person without an organisation (their private office, they are its admin) and in an organisation
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); let j = null; try { j = await r.json(); } catch { j = null; } return {http: r.status, ...(j || {})}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEAT = 'cal,comments,collab,files,docs,office,clients';
const YEAR = String(new Date().getFullYear());

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, CK);
  const me = (await call('GET', '/api/state', null, CK)).me;
  const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id}, CK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`}, CK);
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  check(fr.http < 300, 'a person without an organisation');
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'}, FCK);

  for (const [who, ck] of [['frida', FCK], ['alice', CK]]) {
    // ---- Settings > Company & office > Bank & taxes
    let w = await boot({user: who, hash: 'today'}), d = w.document;
    await until(() => d.querySelector('#side, main'));
    w.eval(`settingsModal('biz-tax')`);
    const form = await until(() => d.querySelector('.smodal #s-biz #ofc-set #s-biz-tax'), 100) && d.querySelector('.smodal #s-biz #ofc-set');
    check(d.querySelector('.smodal .snav [data-sec="biz"]')?.getAttribute('aria-selected') === 'true', `${who}: settingsModal('biz-tax') opens Company & office`);
    check(!!form, `${who}: Company & office has the part Bank & taxes`);
    if (form) {
      const hs = [...form.querySelectorAll(':scope > h3')].map(h => h.id);  // 2.555.0 (#4664): the groups are h3
      check(hs[0] === 's-biz-company' && hs[1] === 's-biz-tax' && /Bank & taxes/.test(d.getElementById('s-biz-tax').textContent), `${who}: Bank & taxes right after Company ` + hs.join());
      check(await until(() => w.eval('S.bizJump') == null, 40), `${who}: the jump to the part is done once`);
      const q = s => d.querySelector('.smodal #s-biz .ostax ' + s);
      check(!!(await until(() => q('#bk-reserve') && q('[data-bk="basis"][data-v="soll"]') && q('#txd-ustva') && q('.lgb-rset #lgb-rate') && q('.cfsset #cfs-amount-set')
        && q('[data-fcc="on"]') && q('.cbset .cb-bk input[data-cbf="name"]'), 100)), `${who}: tax reserve, VAT basis, tax dates, mileage allowance, start balance, monthly check and cash boxes`);
      check(!!d.querySelector('.smodal .ostax[data-fg-skip]'), `${who}: the part is not a field of the settings form (own saves)`);
      // each saves on change through its own route
      if (q('#bk-reserve')) change(w, q('#bk-reserve'), '25');
      check(await until(async () => (await call('GET', '/api/office/settings', null, ck)).settings?.tax_reserve_pct === 25, 60), `${who}: the tax reserve saved from Settings`);
      if (q('[data-bk="basis"][data-v="soll"]')) click(w, q('[data-bk="basis"][data-v="soll"]'));
      check(await until(async () => (await call('GET', '/api/office/settings', null, ck)).settings?.vat_basis === 'soll', 60), `${who}: the VAT basis saved from Settings`);
      check(await until(() => q('[data-bk="basis"][data-v="soll"]')?.getAttribute('aria-pressed') === 'true', 40), `${who}: the switch shows it`);
      if (q('#txd-ustva')) change(w, q('#txd-ustva'), 'quarter');
      check(await until(async () => (await call('GET', '/api/office/tax-dates', null, ck)).ustva === 'quarter', 60), `${who}: the tax dates saved from Settings`);
      if (q('#lgb-rate')) change(w, q('#lgb-rate'), '0.42');
      check(await until(async () => (await call('GET', '/api/office/settings', null, ck)).settings?.km_rates?.[YEAR] === '0.42', 60), `${who}: the mileage allowance of this year saved from Settings`);
      check(await until(() => /0[.,]42/.test(q('#lgb-rate')?.value || ''), 40), `${who}: the field shows the saved rate`);
      if (q('#cfs-amount-set')) change(w, q('#cfs-amount-set'), '500');
      check(await until(async () => (await call('GET', '/api/office/cashflow/start', null, ck)).start?.amount === '500.00', 60), `${who}: the cash flow start balance saved from Settings`);
      const fcc = await until(() => q('[data-fcc="on"]'), 40);
      if (fcc) { fcc.checked = true; change(w, fcc); }
      check(await until(async () => (await call('GET', '/api/office/cashflow/check', null, ck)).on, 60), `${who}: the monthly check switched on from Settings`);
      const cbn = await until(() => q('.cb-bk input[data-cbf="name"]'), 40);
      if (cbn) change(w, cbn, 'Ladenkasse');
      check(await until(async () => (await call('GET', '/api/office/cashbooks', null, ck)).books?.[0]?.name === 'Ladenkasse', 60), `${who}: a cash box renamed from Settings`);
      check(!d.querySelector('#ofc-set .fgbar'), `${who}: no bar "Unsaved changes"`);
      // the agents: the office's read access points to the switch of each agent
      check(!!d.querySelector('.smodal #s-biz-access') && !!d.querySelector('.smodal #os-agents-read') && !!d.querySelector('.smodal #s-biz [data-setgo="agents"]'), `${who}: the read access links to Settings > Agents`);
      // the master data file sits in the part Data
      check(!!form.querySelector('[data-ostp="data"] a[href="/api/office/export"]') && !form.querySelector('[data-ostp="company"] a[href="/api/office/export"]'), `${who}: the master data file in Data`);
    }

    // ---- Settings > Data: the office's part; a button there leads to Company & office > Data
    w.eval(`(() => { const m = document.querySelector('.smodal'); m._noflush = true; m.remove(); settingsModal('data'); })()`);
    const dat = await until(() => d.querySelector('.smodal [data-pane="data"] #s-ofdata-h'), 60);
    check(!!dat, `${who}: Settings > Data has the office`);
    check(!!d.querySelector('.smodal [data-pane="data"] a[href="/api/office/export"]') && !!d.querySelector('.smodal [data-pane="data"] [data-setgo="#office/import"]'), `${who}: export at once, a way to the legacy data`);
    const go = d.querySelector('.smodal [data-pane="data"] [data-setgo="biz-data"]');
    check(!!go, `${who}: import and transfer lead to Company & office`);
    if (go) {
      click(w, go);
      check(!!(await until(() => d.querySelector('.smodal #s-biz #s-biz-data'), 100)) && d.querySelectorAll('.smodal').length === 1, `${who}: the button opens Company & office (one Settings dialog)`);
    }

    // ---- Settings > Integrations: E-invoice (Peppol) leads to the Peppol access
    w.eval(`(() => { const m = document.querySelector('.smodal'); m._noflush = true; m.remove(); settingsModal('integr'); })()`);
    const pep = await until(() => d.querySelector('.smodal [data-pane="integr"] [data-setgo="biz-peppol"]'), 60);
    check(!!pep && /E-invoice \(Peppol\)/.test(d.querySelector('.smodal #s-pep-h')?.textContent || ''), `${who}: Integrations has E-invoice (Peppol)`);
    if (pep) {
      click(w, pep);
      check(!!(await until(() => d.querySelector('.smodal #s-biz #ofc-set #pep-set') || d.querySelector('.smodal #s-biz #s-biz-docs'), 100)), `${who}: it opens Company & office with the Peppol access`);
      check(d.querySelectorAll('.smodal #pep-set').length <= 1, `${who}: the Peppol fields stay in one place`);
    }
    w.close();

    // ---- the tabs link to the settings instead of holding the fields
    w = await boot({user: who, hash: 'office/books'}); d = w.document;
    const bl = await until(() => d.querySelector('#view [data-setgo="biz-tax"]'), 100);
    check(!!bl && !d.querySelector('#view #bk-reserve') && !d.querySelector('#view #txd-ustva'), `${who}: the bookkeeping links to Bank & taxes, no fields`);
    if (bl) {
      click(w, bl);
      check(!!(await until(() => d.querySelector('.smodal #s-biz #s-biz-tax'), 100)), `${who}: the link opens Settings > Company & office > Bank & taxes`);
    }
    // the receipt's SKR account: the upkeep of all accounts
    const acc = w.eval(`(() => { BK.info = {accounts: {chart: 'SKR03', categories: {Travel: {account: '4670', default: '4670', own: false}}, own: {}}}; const md = document.createElement('div');
      md.className = 'modal bk-sheet'; md.innerHTML = '<input id="bk-cat" value="Travel"><div class="bk-acct"></div>'; document.body.appendChild(md); bkAcctLine(md);
      const t = md.querySelector('.bk-acct [data-setgo="biz-datev"]')?.textContent || ''; md.remove(); return t; })()`);
    check(/All accounts/.test(acc), `${who}: the receipt's account links to all accounts (DATEV) ` + acc);
    // the agent's switch knows the office's read access
    const sw = w.eval(`(() => { const b = document.createElement('div'); oa_switchDraw(b, {office_drafts: 1, can_set: true, agents_read: 0}); return b.querySelector('[data-setgo="biz-agents"]') ? b.textContent : ''; })()`);
    check(/does not let agents read/.test(sw), `${who}: the agent's office switch links to the office's read access ` + sw);
    w.close();

    w = await boot({user: who, hash: 'office/cashflow'}); d = w.document;
    check(!!(await until(() => d.querySelector('#view .rkcfms') && d.querySelector('#view [data-setgo="biz-tax"]'), 100)) && !d.querySelector('#view [data-fcc]'), `${who}: the cash flow links to the monthly check`);
    w.close();
    w = await boot({user: who, hash: 'office/cashbook'}); d = w.document;
    check(!!(await until(() => d.querySelector('#view .cb-bar [data-setgo="biz-tax"]'), 100)) && !d.querySelector('#view [data-cb="view"][data-v="books"]'), `${who}: the cash book links to the cash boxes`);
    w.close();
    w = await boot({user: who, hash: 'office/travel'}); d = w.document;
    check(!!(await until(() => d.querySelector('#view a[href="#office/import/trips"]'), 100)) && !d.querySelector('#view [data-rki="pick"]'), `${who}: the empty trip list links to the import`);
    w.close();
    w = await boot({user: who, hash: 'office/import'}); d = w.document;
    check(!!(await until(() => d.querySelector('#view #oim-trips [data-rki="pick"]'), 100)), `${who}: the legacy data page has the trips import`);
    check(!!d.querySelector('#view .oimsec [data-setgo="biz-docs"]'), `${who}: the number counters link to Documents & numbers`);
    w.close();
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
