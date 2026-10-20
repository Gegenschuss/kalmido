// 2.120.0 UI tests, part A (#2087 progress / final invoices, cash discount), own container (start.sh, mode workspaces),
// Firefox (desktop + phone width). Invented companies, people and figures only.
// - "Create invoice" on a quotation asks for the type: full / progress (percent or amount) / final (lists the progress
//   invoices); a progress invoice of 50 % opens as "Progress invoice" with its type and the cash discount fields in the head
// - the cash discount of the head is saved (percent + days); the office settings carry the default
// - on a phone the dialog stays inside the screen with big targets
// - a person without organisation: the same dialog in the personal office
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2120_a_ui', check, shots: 'P2120A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2120A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = new Date().toISOString().slice(0, 10);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Frei', password: 'password123', email: 'frida@example.com'});
  const CF = await login('frida');
  for (const ck of [CA, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const quote = async ck => {
    await call(ck, 'PUT', '/api/office/settings', {lang: 'en', company_fields: {name: 'Beispiel Studio GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE',
      tax_number: '12/345/67890', iban: 'DE02120300000000202051'}});
    const cl = await call(ck, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Kundenweg 5', zip: '20000', city: 'Beispielstadt', country: 'DE'});
    const q = await call(ck, 'POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: cl.id, service_from: today, service_to: today});
    await call(ck, 'PUT', `/api/office/docs/${q.id}/items`, {items: [{title: 'Shoot', qty: 2, unit: 'day', rate: 4000, tax: 'standard'}, {title: 'Script', qty: 1, unit: 'flat', rate: 2000, tax: 'reduced'}]});
    await call(ck, 'POST', `/api/office/docs/${q.id}/status`, {status: 'accepted'});  // 2.138.0 (#2235): "Create invoice" in the bar once accepted
    return q.id;
  };
  const OFF = await quote(CA);
  check(OFF > 0, 'a quotation');
  await call(CA, 'PUT', '/api/office/settings', {skonto_pct: 2, skonto_days: 10});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const api = (m, u) => `fetch('${u}', {method: '${m}', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const click = sel => `(() => { document.querySelector('${sel}').click(); return 1; })()`;
  const openDialog = async (ev, nav, id) => {
    await nav(B + `#office/offers/${id}`);
    await ready(ev, `!!document.querySelector('[data-ofd="to-invoice"]')`, 80);
    await ev(click('[data-ofd="to-invoice"]'));
    return ready(ev, `document.querySelectorAll('.modal input[name="abs-type"]').length === 3`);
  };
  const pick = v => `(() => { const x = document.querySelector('.modal input[name="abs-type"][value="${v}"]'); x.checked = true; x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= the dialog: full / progress / final
    check(await openDialog(ev, nav, OFF), 'the dialog offers full / progress / final');
    check(await ev(`document.querySelector('.modal input[name="abs-type"][value="full"]').checked && document.querySelector('.modal .abs-p').hidden && document.querySelector('.modal .abs-f').hidden`),
      'full invoice preselected, nothing else shown');
    await ev(pick('progress'));
    check(await ready(ev, `!document.querySelector('.modal .abs-p').hidden && !!document.querySelector('.modal #ofd-abs-val') && /10,000\\.00|10\\.000,00/.test(document.querySelector('.modal .abs-p').textContent)`),
      'progress: amount field with the quotation net');
    await ev(`(() => { document.querySelector('.modal #ofd-abs-val').value = '50'; return 1; })()`);
    await shot('p2120-a-dialog.png');
    await ev(click('.modal [data-m="ok"]'));
    check(await ready(ev, `!document.querySelector('.modal') && /Progress invoice/.test(document.querySelector('.ofdnum')?.textContent || '')`, 60), 'progress: the draft opens as progress invoice');
    const pid = +(await ev(`location.hash.split('/').pop()`));
    const p = await ev(api('GET', `/api/office/docs/${pid}`));
    check(p.inv_type === 'progress' && Math.abs(+p.totals.net - 5000) < 0.001, 'progress: 50 % of the net ' + JSON.stringify(p.totals?.net));
    check(await ev(`document.querySelector('#ofd-inv_type')?.value === 'progress' && !!document.querySelector('#ofd-skonto_pct') && !!document.querySelector('#ofd-skonto_days')`),
      'head: type and cash discount fields');
    check(await ev(`document.querySelector('#ofd-skonto_pct').value.startsWith('2') && document.querySelector('#ofd-skonto_days').value === '10'`), 'head: the default cash discount of the settings');
    await ev(`(() => { const x = document.querySelector('#ofd-skonto_pct'); x.value = '3'; x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    let saved = null; for (let i = 0; i < 30 && !(saved && +saved.skonto_pct === 3); i++) { saved = await ev(api('GET', `/api/office/docs/${pid}`)); await sleep(250); }
    check(saved && +saved.skonto_pct === 3, 'head: the cash discount is saved ' + JSON.stringify(saved?.skonto_pct));
    await shot('p2120-a-head.png');
    check((await ev(`fetch('/api/office/docs/${pid}/finalize', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`)) === 200, 'progress finalised');
    // the final invoice lists it
    check(await openDialog(ev, nav, OFF), 'the dialog again');
    await ev(pick('final'));
    check(await ready(ev, `!document.querySelector('.modal .abs-f').hidden && document.querySelectorAll('.modal .abs-list li').length === 1`), 'final: lists the progress invoice');
    await shot('p2120-a-final.png');
    // phone width: inside the screen, big targets
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(`(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.modal *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`),
      'phone: the dialog stays inside the screen');
    check(await ev(`[...document.querySelectorAll('.modal .tpmode')].every(b => b.getBoundingClientRect().height >= 40)`), 'phone: big targets (the type choice)');
    await shot('p2120-a-dialog-phone.png');
    await ev(click('.modal [data-m="ok"]'));
    check(await ready(ev, `!document.querySelector('.modal') && /Final invoice/.test(document.querySelector('.ofdnum')?.textContent || '')`, 60), 'final: the draft opens as final invoice');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // the list shows the type
    await nav(B + '#office/offers');
    await ev(`(() => { if (typeof OFD !== 'undefined') { OFD.kind = 'invoice'; OFD.list = null; ofdLoadList(true); } return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('.abs-tag')].some(x => /Progress invoice/.test(x.textContent)) && [...document.querySelectorAll('.abs-tag')].some(x => /Final invoice/.test(x.textContent))`, 60),
      'list: the type at the rows');
    // the office settings carry the default
    await nav(B + '#office/settings');
    check(await ready(ev, `!!document.querySelector('#os-skonto') && document.querySelector('#os-skonto-days').value === '10'`, 80), 'settings: the cash discount default');
    // ================= a person without organisation
    await signIn(ev, 'frida');
    await nav(B + 'static/icon.svg');
    const FOFF = await quote(CF);
    check(await openDialog(ev, nav, FOFF), 'freelancer: the dialog');
    await ev(pick('progress'));
    await ev(`(() => { document.querySelector('.modal #ofd-abs-unit').value = 'amount'; document.querySelector('.modal #ofd-abs-val').value = '1000'; return 1; })()`);
    await ev(click('.modal [data-m="ok"]'));
    check(await ready(ev, `!document.querySelector('.modal') && /Progress invoice/.test(document.querySelector('.ofdnum')?.textContent || '')`, 60), 'freelancer: progress invoice by amount');
    const fp = await ev(api('GET', `/api/office/docs/${await ev(`location.hash.split('/').pop()`)}`));
    check(Math.abs(+fp.totals?.net - 1000) < 0.001, 'freelancer: net 1000 ' + JSON.stringify(fp.totals?.net));
  }, false);

  console.log(`p2120_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
