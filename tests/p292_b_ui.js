// 2.92.0 UI tests, part B (#1931: the value of equipment), own container (start.sh, mode workspaces), Firefox (desktop +
// phone width). Invented companies, devices and figures only.
// - the admin's equipment list: sums (new value, current value, depreciation of the year) and the CSV / PDF links above it,
//   the current value under a device
// - the device dialog: "Purchase and value" with the depreciation table (years, depreciation, book value), the note "no tax
//   advice"; a purchase price entered in the dialog is saved (decimal comma) and can be taken back by one undo step
// - on a phone nothing sticks out to the side
// - a member sees the device without any price or value
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p292_b_ui', check, shots: 'P292B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P292B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const cam = await call(CA, 'POST', '/api/office/equipment', {name: 'Kamera Alpha', category: 'Kamera', daily_rate: 120, purchase_date: '2024-03-15', purchase_net: '2400', serial_no: 'SN-0815'});
  check(cam.http === 201, 'a device with purchase data ' + cam.http);
  const mic = await call(CA, 'POST', '/api/office/equipment', {name: 'Funkmikrofon', category: 'Ton'});
  const val = await call(CA, 'GET', '/api/office/equipment/value');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *, .modal .card *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const fmt = n => (+n).toLocaleString('en', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/equipment');
    check(await ready(ev, `document.querySelectorAll('.ofcrow[data-kind="equipment"]').length === 2`, 80), 'the equipment list');
    check(await ready(ev, `document.querySelectorAll('.ast-sum .ast-tile').length === 3`), 'the sums above the list');
    check(await ev(`document.querySelector('.ast-sum').textContent.includes(${JSON.stringify(fmt(val.sums.new_value))}) && document.querySelector('.ast-sum').textContent.includes(${JSON.stringify(fmt(val.sums.current_value))})`),
      'the sums show new and current value ' + await ev(`document.querySelector('.ast-sum')?.textContent`));
    check(await ev(`/value\\.csv$/.test(document.querySelector('#ast-csv')?.getAttribute('href') || '') && /value\\.pdf$/.test(document.querySelector('#ast-pdf')?.getAttribute('href') || '')`), 'CSV and PDF links');
    check(await ev(`/No tax advice/.test(document.querySelector('.ast-sum .ast-note')?.textContent || '')`), 'the note: no tax advice');
    check(await ev(`/Current value/.test(document.querySelector('.ofcrow[data-id="${cam.id}"]').textContent)`), 'the current value under the device');
    await shot('p292-b-list.png');
    // the dialog: the depreciation table
    await ev(`(() => { document.querySelector('.ofcrow[data-id="${cam.id}"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .ast-sec[open] .ast-plan')`), 'the device dialog with purchase and value');
    check(await ev(`(() => { const t = document.querySelector('.modal .ast-plan'); const r = t.querySelectorAll('tbody tr'); return r.length === 8 && r[0].textContent.includes('2024') && r[0].textContent.includes('285.71'); })()`),
      'the depreciation table: 8 years, the first one by the month ' + await ev(`document.querySelector('.modal .ast-plan tbody tr')?.textContent`));
    check(await ev(`document.querySelector('#of-serial_no').value === 'SN-0815' && ofcNum(document.querySelector('#of-purchase_net').value) === 2400`), 'the stored values in the fields');
    check(await ev(`/book value/.test(document.querySelector('.modal .ast-sec').textContent) && /No tax advice/.test(document.querySelector('.modal .ast-sec').textContent)`), 'the explanation and the note in the dialog');
    await shot('p292-b-dialog.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone the dialog stays inside the screen');
    await shot('p292-b-dialog-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.modal')`);
    // a price entered in the dialog, then one undo step
    await ev(`(() => { document.querySelector('.ofcrow[data-id="${mic.id}"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #of-purchase_net')`), 'the second device');
    await ev(`(() => { const m = document.querySelector('.modal'); m.querySelector('.ast-sec').open = true; m.querySelector('#of-purchase_net').value = '650.50'; m.querySelector('#of-vendor').value = 'Tonhaus Beispiel'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal') && fetch('/api/office/equipment/${mic.id}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.purchase_net === '650.50' && j.vendor === 'Tonhaus Beispiel')`),
      'the price is saved');
    check(await ev(`HIST.undo[HIST.undo.length - 1]?.label === 'Edit device'`), 'one undo step');
    await ev(`(() => { histStep('undo'); return 1; })()`);
    check(await ready(ev, `fetch('/api/office/equipment/${mic.id}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.purchase_net === '' && j.vendor === '')`), 'undo takes the price back');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#office/equipment');
    check(await ready(ev, `document.querySelectorAll('.ast-sum .ast-tile').length === 3`, 80), 'phone: the sums');
    await sleep(300);
    check(await ev(noSide), 'phone: the list stays inside the screen');
    await shot('p292-b-list-phone.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    // member
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/equipment');
    check(await ready(ev, `document.querySelectorAll('.ofcrow[data-kind="equipment"]').length === 2`, 80), 'member: the equipment list');
    check(await ev(`!document.querySelector('.ast-sum') && !/Current value/.test(document.querySelector('.ofclist').textContent)`), 'member: no sums, no values');
    await ev(`(() => { document.querySelector('.ofcrow[data-id="${cam.id}"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #of-name')`), 'member: the device dialog');
    check(await ev(`!document.querySelector('.modal .ast-sec')`), 'member: no purchase and value part');
  }, false);

  console.log(`p292_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
