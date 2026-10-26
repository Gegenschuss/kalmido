// 2.299.0 B (#3191) UI tests: bank rules, own container (start.sh, mode workspaces), Firefox (desktop + phone width). Invented
// companies, people, accounts and figures only. tenant-matrix: office
// - the bank list: the second "Private" for the same counterpart shows the one line "Always like this?"; "Always" makes the
//   rule and marks the third booking at once; "Matched" shows it with "by rule <name>"; "No" is not asked again
// - the office settings, area Data: the section "Bank rules" lists the rule with its hits, the switch turns it off, "New rule"
//   makes one in the dialog (applied to the open bookings), delete takes it out of the list
// - on a phone the section stays inside the screen and its buttons are 44 px high
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2299_b_bankrules_ui', check, shots: 'P2299B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2299B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const day = n => { const d = new Date(TC.today() + 'T12:00:00'); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
let ref = 0;
const camt = rows => `<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt><Stmt>${rows.map(([amt, d, name, purpose]) =>
  `<Ntry><Amt Ccy="EUR">${Math.abs(amt).toFixed(2)}</Amt><CdtDbtInd>${amt > 0 ? 'CRDT' : 'DBIT'}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts><BookgDt><Dt>${d}</Dt></BookgDt><AcctSvcrRef>P2299BUI-${++ref}</AcctSvcrRef><NtryDtls><TxDtls><RltdPties><Cdtr><Pty><Nm>${name}</Nm></Pty></Cdtr></RltdPties><RmtInf><Ustrd>${purpose}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>`).join('')}</Stmt></BkToCstmrStmt></Document>`;

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
  const imp = await call(CA, 'POST', '/api/office/bank/import', {text: camt([[-5, day(3), 'Kiosk Beispiel', 'Zeitung 1'], [-6, day(2), 'Kiosk Beispiel', 'Zeitung 2'],
    [-7, day(1), 'Kiosk Beispiel', 'Zeitung 3'], [-9.9, day(1), 'Bank Beispiel AG', 'Kontofuehrung'], [-3, day(4), 'Spende Verein', 'Spende 1'], [-4, day(4), 'Spende Verein', 'Spende 2']]), filename: 'auszug.xml'});
  check(imp.http === 201 && imp.count === 6, 'six bookings imported ' + imp.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const api = (m, u) => `fetch('${u}', {method: '${m}', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const row = p => `[...document.querySelectorAll('.bnkrow')].find(e => /${p}/.test(e.textContent))`;
  const click = sel => `(() => { const e = ${sel}; if (!e) return 0; e.click(); return 1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/bank');
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 6`, 80), 'the bank tab lists six open bookings');
    await ev(click(`${row('Zeitung 1')}?.querySelector('[data-bnk="match"][data-kind="private"]')`));
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 5`), 'the first "Private"');
    check(!await ev(`!!document.querySelector('.bnkrsug')`), 'the first time asks nothing');
    await ev(click(`${row('Zeitung 2')}?.querySelector('[data-bnk="match"][data-kind="private"]')`));
    check(await ready(ev, `!!document.querySelector('.bnkrsug') && /Always like this/.test(document.querySelector('.bnkrsug').textContent) && /Kiosk Beispiel/.test(document.querySelector('.bnkrsug').textContent)`),
      'the second time: the line "Always like this?" with the counterpart');
    check(await ev(`document.querySelector('.bnkrsug [data-brl="sugok"]').getBoundingClientRect().height >= 43`), 'its button is 44 px high');
    await shot('p2299-b-always.png');
    await ev(click(`document.querySelector('.bnkrsug [data-brl="sugok"]')`));
    check(await ready(ev, `!document.querySelector('.bnkrsug') && document.querySelectorAll('.bnklist .bnkrow').length === 3 && !${row('Zeitung 3')}`), '"Always": the rule marks the third booking at once');
    const rules = await ev(api('GET', '/api/office/bank/rules'));
    check(rules.items?.length === 1 && rules.items[0].counterpart === 'Kiosk Beispiel' && rules.items[0].action === 'private' && rules.items[0].hits === 1, 'the rule is made ' + JSON.stringify(rules.items?.[0] || {}));
    await ev(click(`document.querySelector('[data-bnk="state"][data-v="matched"]')`));
    check(await ready(ev, `/by rule Kiosk Beispiel/.test(${row('Zeitung 3')}?.querySelector('.bnkbyr')?.textContent || '') && !${row('Zeitung 1')}?.querySelector('.bnkbyr')`),
      '"Matched": by rule on the booking the rule marked, not on the ones by hand');
    await ev(click(`document.querySelector('[data-bnk="state"][data-v="open"]')`));
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 3 && !!${row('Spende 1')} && !!${row('Spende 2')}`), 'back to the open ones');
    for (const p of ['Spende 1', 'Spende 2']) { await ev(click(`${row(p)}?.querySelector('[data-bnk="match"][data-kind="ignored"]')`)); await ready(ev, `!${row(p)}`); }
    check(await ready(ev, `!!document.querySelector('.bnkrsug')`), 'a second counterpart: asked again');
    await ev(click(`document.querySelector('.bnkrsug [data-brl="sugno"]')`));
    check(await ready(ev, `!document.querySelector('.bnkrsug')`) && (await ev(api('GET', '/api/office/bank/rules'))).items.length === 1, '"No": no rule, the line goes');

    // ---- the office settings, area Data: Bank rules
    await nav(B + 'static/icon.svg'); await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#ofc-set [data-ostsub="data"]')`, 80), 'the settings page');
    await ev(click(`document.querySelector('#ofc-set [data-ostsub="data"]')`));
    check(await ready(ev, `document.querySelectorAll('.brlset .brlrow').length === 1 && /Kiosk Beispiel/.test(document.querySelector('.brlrow').textContent) && /1 hit/.test(document.querySelector('.brlrow').textContent)`, 60),
      'the section "Bank rules" lists the rule with its hits');
    check(await ev(`!document.querySelector('.brlset').closest('[data-ostp]').hidden`), 'it sits in the area shown');
    await shot('p2299-b-settings.png');
    await ev(click(`document.querySelector('.brlrow [data-brl-on]')`));
    check(await ready(ev, `${api('GET', '/api/office/bank/rules')}.then(j => j.items[0].active === false)`), 'the switch turns the rule off');
    check(await ready(ev, `document.querySelector('.brlrow')?.classList.contains('arch')`), 'the row shows it is off');
    await ev(click(`document.querySelector('.brlset [data-brl="new"]')`));
    check(await ready(ev, `!!document.querySelector('.brldlg #brl-cp')`), '"New rule" opens the dialog');
    await ev(`(() => { const d = document.querySelector('.brldlg'); d.querySelector('#brl-cp').value = 'Bank Beispiel'; d.querySelector('#brl-act').value = 'ignored';
      d.querySelector('#brl-act').dispatchEvent(new Event('change')); return 1; })()`);
    check(await ev(`document.querySelector('.brldlg .brl-cat').hidden && document.querySelector('.brldlg #brl-open').checked`), 'no category field for "Ignore"; apply to open ticked');
    await ev(`(() => { const d = document.querySelector('.brldlg #brl-act'); d.value = 'category'; d.dispatchEvent(new Event('change')); return 1; })()`);
    check(await ev(`!document.querySelector('.brldlg .brl-cat').hidden`), 'the category field for "Category"');
    await ev(click(`document.querySelector('.brldlg [data-brd="save"]')`));
    check(await ready(ev, `/category/i.test(document.querySelector('.brldlg .aerr')?.textContent || '')`), 'a category rule without category: the message in the dialog');
    await ev(`(() => { const d = document.querySelector('.brldlg #brl-act'); d.value = 'ignored'; d.dispatchEvent(new Event('change')); return 1; })()`);
    await ev(click(`document.querySelector('.brldlg [data-brd="save"]')`));
    check(await ready(ev, `!document.querySelector('.brldlg') && document.querySelectorAll('.brlset .brlrow').length === 2`), 'saved: two rules');
    check(await ready(ev, `${api('GET', '/api/office/bank/tx?state=matched')}.then(j => j.items.some(t => t.purpose === 'Kontofuehrung' && t.match.kind === 'ignored' && t.match.by_rule))`),
      'the new rule marked the open booking');
    // ---- phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(300);
    check(await ev(`(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.brlset *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`),
      'on a phone the section stays inside the screen');
    check(await ev(`[...document.querySelectorAll('.brlrow .btn')].every(b => b.getBoundingClientRect().height >= 43)`), 'on a phone its buttons are 44 px high');
    await shot('p2299-b-settings-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(click(`[...document.querySelectorAll('.brlrow')].find(e => /Bank Beispiel/.test(e.textContent))?.querySelector('[data-brl="del"]')`));
    check(await ready(ev, `document.querySelectorAll('.brlset .brlrow').length === 1`), 'delete takes the rule out of the list');
  }, false);

  console.log(`p2299_b_bankrules_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
