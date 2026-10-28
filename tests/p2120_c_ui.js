// 2.120.0 UI tests, part C (#2090): the DATEV settings' section "Receipts and travel expenses" and the export dialog. Own
// container (start.sh), Firefox (desktop + phone width), an organisation's admin and a person without an organisation.
// Invented companies, people and figures only.
// - the section inside the DATEV block of the office settings: switch, counter account, collective creditor, tax keys, the
//   travel accounts with the chart's defaults as placeholders (employees' accounts for an organisation)
// - a field saves itself on change (no save bar), one undo step in the toast brings the old value back
// - the export dialog has "Include receipts and travel expenses" (on by default)
// - a person without an organisation: the owner's travel accounts (4673) -- freelancer-matrix: office
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const {undoToast} = require('./ff');
const firefox = require('./ff')({tag: 'p2120_c_ui', check, shots: 'P2120C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2120C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const s1 = await call(CA, 'PUT', '/api/office/settings', {company: {name: 'Studio Beispiel GmbH'}, datev_extf: {advisor_no: '1234567', client_no: '12345'}});
  check(s1.http === 200, 'DATEV numbers');
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.http < 300, 'a person without an organisation');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const getJ = url => `fetch('${url}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const setv = (sel, v) => `(() => { const x = document.querySelector('${sel}'); x.value = ${JSON.stringify(v)}; x.dispatchEvent(new Event('input', {bubbles: true})); x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  const clk = sel => `(() => { const x = document.querySelector('${sel}'); if (!x) return 0; x.click(); return 1; })()`;
  const openDx = `(() => { const d = document.querySelector('details.dxset'); if (!d) return 0; d.open = true; return 1; })()`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.dvset *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const ph = key => `document.querySelector('.dvset input[data-dv="travel"][data-name="${key}"]')?.placeholder`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/settings');
    check(await ready(ev, openDx, 80), 'the DATEV block in the office settings');
    check(await ready(ev, `!!document.querySelector('.dvset #dv-on') && document.querySelector('.dvset #dv-on').checked`), 'the section with the switch (on)');
    check(await ready(ev, `${ph('fares')} === '4663' && ${ph('hotel')} === '4666' && ${ph('vma')} === '4664'`, 60), 'travel accounts with the employees\' defaults as placeholders');
    check(await ev(`document.querySelector('#dv-cred').placeholder === '70000' && document.querySelector('#dv-other').placeholder === '4900'`), 'creditor and other expenses placeholders');
    check(await ev(`!!document.querySelector('.dvset[data-fg-skip]')`), 'the section saves itself (outside the form guard)');
    await ev(setv('#dv-cred', '71000'));
    check(await ready(ev, `${getJ('/api/office/settings')}.then(j => j.settings.datev_extf.creditor === '71000')`), 'the creditor saved on change');
    check(await ev(`!document.querySelector('#ofc-set > .fgbar')`), 'no save bar for the field');
    await ev(`(() => { document.querySelector('.dvset')?.scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot('p2120-c-settings.png');
    await undoToast(ev, 'Saved');  // 2.312.0 A (#3283)
    check(await ready(ev, `${getJ('/api/office/settings')}.then(j => j.settings.datev_extf.creditor === '')`), 'one undo step brings the old value back');
    await ready(ev, `!!document.querySelector('.dvset input[data-dv="travel"][data-name="hotel"]')`, 60);  // the undo redraws the section
    await ev(setv('.dvset input[data-dv="travel"][data-name="hotel"]', '4676'));
    check(await ready(ev, `${getJ('/api/office/settings')}.then(j => j.settings.datev_extf.travel.hotel === '4676')`), 'a travel account saved');
    await ev(setv('#dv-cred', '7x'));
    check(await ready(ev, `/Invalid value/.test(document.querySelector('#dv-err')?.textContent || '')`), 'an invalid number shows the error at the section');

    // ---- the export dialog (invoice list)
    await nav(B + '#office/invoices');  // 2.380.0 (#3409): the invoices' own area
    await ready(ev, `!!document.querySelector('[data-ofd="kind"][data-kind="invoice"]')`, 80);
    await ev(clk('[data-ofd="kind"][data-kind="invoice"]'));
    check(await ready(ev, `!!document.querySelector('[data-dx="extf"]')`, 80), 'the DATEV export button');
    await ev(clk('[data-dx="extf"]'));
    check(await ready(ev, `!!document.querySelector('.modal #dx-in') && document.querySelector('.modal #dx-in').checked`), 'the dialog: include receipts and travel expenses (on)');
    await ev(clk('.modal [data-m="close"]'));

    // ---- phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#office/settings');
    check(await ready(ev, openDx, 80) && await ready(ev, `!!document.querySelector('.dvset #dv-on')`), 'phone: the section');
    check(await ev(noSide), 'phone: nothing sticks out at the side');
    await ev(`(() => { document.querySelector('.dvset')?.scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot('p2120-c-phone.png');

    // ---- a person without an organisation
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`);
    await nav(B + 'static/icon.svg');
    await signIn(ev, 'frida');
    await nav(B + '#office/settings');
    check(await ready(ev, openDx, 80), 'freelancer: the DATEV block');
    check(await ready(ev, `${ph('fares')} === '4673' && ${ph('vma')} === '4674'`, 60), 'freelancer: the owner\'s travel accounts');
  }, false);

  console.log(`p2120_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
