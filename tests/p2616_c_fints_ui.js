// 2.616.0 part C (#2473) UI test: the bank fetch over FinTS in the office's tab Bank.
// kalmido-suite: fresh
// Own container (start.sh, mode workspaces, the stand-in bank of the test containers: KALMIDO_TEST_FINTS_FAKE=1, no network). Invented companies and accounts only.
// - without the server's product registration the button "Fetch from bank" is there, switched off, with the reason next to it
// - with it (restart, same data): the dialog (account, sign-in name, PIN as a password field, server, period) -> "Connect" ->
//   "Please approve in your banking app" -> it goes on by itself once approved -> the preview (2 new) -> "Import" asks for
//   the target (importTargetConfirm) -> the two bookings are in the list; the PIN field is empty again after "Connect";
//   the sign-in name is offered again the next time (never the PIN)
// - 2.616.0 (#2473, Fable finding 4): another admin set the server address since -> the dialog says who and when
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2616_c_fints_ui', check, shots: 'P2616C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const ENV = ' -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_TEST_FINTS_FAKE=1';
const start = (extra, keep) => {
  if (process.env.P2616CUI_NOSTART || process.env.KMT_NOSTART) return;
  const env = {...process.env, EXTRA: (process.env.EXTRA || '') + ENV + extra};
  if (keep) env.KEEP = '1'; else delete env.KEEP;
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env});
};
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const PIN = 'UiPin-' + Math.random().toString(36).slice(2, 10);

(async () => {
  start('', false);
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  let CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const co = await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE',
    iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}});
  check(co.http === 200, 'company with a German IBAN ' + co.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = sel => `(() => { const e = ${sel}; if (!e) return 0; e.click(); return 1; })()`;
  const set = (sel, v) => `(() => { const e = document.querySelector('${sel}'); if (!e) return 0; e.value = ${JSON.stringify(v)}; e.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`;
  const BTN = `document.querySelector('[data-bnk="fints"]')`;

  // ---- off: no product registration
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/bank');
    check(await ready(ev, `!!${BTN}`, 80), 'off: the button "Fetch from bank" is there');
    check(await ev(`${BTN}.disabled && /not set up on this server/.test(document.querySelector('#bnk-fnt-off')?.textContent || '') && ${BTN}.getAttribute('aria-describedby') === 'bnk-fnt-off'`),
      'off: switched off, the reason next to it (and named for screen readers)');
    await shot('p2616-c-off.png');
  }, false);

  // ---- on: restart with the registration, same data
  start(' -e KALMIDO_FINTS_PRODUCT_ID=TESTPRODUCT0000000000', true);
  await sleep(600);
  CA = await login('alice');
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/bank');
    check(await ready(ev, `!!${BTN} && !${BTN}.disabled && !document.querySelector('#bnk-fnt-off')`, 80), 'on: the button is on');
    await ev(click(BTN));
    check(await ready(ev, `!!document.querySelector('.fntdlg #fn-pin')`, 60), 'the dialog opens (office_fints.js loaded on demand)');
    check(await ev(`document.querySelector('#fn-pin').type === 'password' && document.querySelector('#fn-pin').autocomplete === 'off' && /2051/.test(document.querySelector('#fn-acct').textContent)`),
      'the PIN is a password field; the account with its IBAN end is offered');
    await ev(`window.__itc = []; const _itc0 = importTargetConfirm; importTargetConfirm = o => { __itc.push(o); return _itc0(o); }; 1`);
    await ev(set('#fn-login', 'decoupled')); await ev(set('#fn-pin', PIN)); await ev(set('#fn-server', 'https://fints.example.com/fints'));
    await ev(click(`document.querySelector('.fntdlg [data-fn="next"]')`));
    check(await ready(ev, `/Please approve in your banking app/.test(document.querySelector('.fntdlg')?.textContent || '')`, 40), 'decoupled: "Please approve in your banking app"');
    await shot('p2616-c-wait.png');
    check(await ready(ev, `document.querySelectorAll('.fntdlg .bnkprev .ofcrow').length === 2 && /2 new/.test(document.querySelector('.fntdlg').textContent)`, 60), 'approved: it goes on by itself to the preview (2 new)');
    await shot('p2616-c-preview.png');
    await ev(click(`document.querySelector('.fntdlg [data-fn="next"]')`));
    check(await ready(ev, `!!document.querySelector('[data-cd="yes"]')`, 40) && await ev(`__itc.length === 1 && /Beispielbank|Main account|Alpha|Bank/.test(String(__itc[0].place))`), 'Import asks for the target first');
    await ev(click(`document.querySelector('[data-cd="yes"]')`));
    check(await ready(ev, `!document.querySelector('.fntdlg') && document.querySelectorAll('.bnklist .bnkrow').length === 2`, 60), 'the two bookings are in the list, the dialog is closed');
    await ev(click(BTN));
    check(await ready(ev, `document.querySelector('.fntdlg #fn-login')?.value === 'decoupled' && document.querySelector('.fntdlg #fn-pin')?.value === '' && document.activeElement?.id === 'fn-pin'`, 60),
      'next time: the sign-in name is offered again, the PIN field is empty and has the focus');
    check(await ev(`document.querySelector('.fntdlg .fn-srvchg')?.textContent === ''`), 'own server address: no note in the dialog');
    await ev(click(`document.querySelector('.fntdlg [data-fn="close"]')`));
    // 2.616.0 (#2473, Fable finding 4): Dave (another admin) fetches with another server address -> Alice's dialog names it
    check((await call(CA, 'POST', '/api/users', {username: 'dave', display_name: 'Dave Admin', password: 'password123', email: 'dave@example.com'})).http === 200, 'dave');
    check((await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'dave@example.com', role: 'admin'})).http === 200, 'dave is an admin of the organisation');
    const CD = await login('dave');
    await call(CD, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`});
    const acc = (await call(CD, 'GET', '/api/office/bank/fints')).accounts[0];
    const dv = await call(CD, 'POST', '/api/office/bank/fints/start', {account_id: acc.id, login: 'decoupled', pin: PIN, server: 'https://fints2.example.com/fints', mechanism: '921'});
    let dd = dv.dialog || {};
    for (let i = 0; i < 20 && dd.state === 'decoupled'; i++) dd = (await call(CD, 'POST', `/api/office/bank/fints/${dd.id}/poll`, {})).dialog || {};
    check(dd.state === 'preview', 'dave: his fetch reaches the preview ' + dd.state);
    await call(CD, 'DELETE', `/api/office/bank/fints/${dd.id}`);
    await ev(click(BTN));
    check(await ready(ev, `/changed by Dave Admin/.test(document.querySelector('.fntdlg .fn-srvchg')?.textContent || '') && document.querySelector('.fntdlg #fn-server')?.value === 'https://fints2.example.com/fints'`, 60),
      'server changed by another admin: the dialog says who changed it');
    await shot('p2616-c-srvchg.png');
    await ev(click(`document.querySelector('.fntdlg [data-fn="close"]')`));
  }, false);
  const st = await call(CA, 'GET', '/api/office/bank/fints');
  check(st.on === true && !JSON.stringify(st).includes(PIN), 'the PIN is in no answer');

  console.log(`p2616_c_fints_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
