// 2.50.0 UI tests of part A (#1195 absences, #1194 disposition; own container, start.sh). jsdom:
// - the workload view has the tabs Workload | Absences | Disposition (the last only with the module "dispo")
// - "Enter an absence" (sheet): kind, period, saved on the server, shown in the grid and the list; Undo removes it
// - the disposition: "Book" (sheet) with a person and a device, the bar in the grid; a second booking of the same device
//   is marked as a warning (the booking stays); "Who is free on ...?" leaves the booked device out
// - phone width: a list per day instead of the grid (CSS), large targets
// Firefox (real layout, skipped without firefox): 390 px touch - absences and disposition stay inside the screen, the grid
// is hidden and the day list shown; 1280 px - the grid
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p250_a_ui', check: (c, w) => check(c, w), shots: 'P250A_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P250A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...feats, 'collab', 'workload'].join(',')});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: 1})).id;
  sql('INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?) ON CONFLICT DO NOTHING', [ORG, BOB, 'member']);
  const now = '2026-01-01T00:00:00Z';
  const CAM = sql('INSERT INTO office_equipment(org_id,name,category,created_at,updated_at) VALUES(?,?,?,?,?) RETURNING id', [ORG, 'Camera A', 'Camera', now, now])[0].id;
  check(ORG > 0 && BOB > 0 && CAM > 0, 'setup: organisation, bob, a camera');
  const t = new Date(), mon = new Date(t); mon.setDate(t.getDate() - (t.getDay() + 6) % 7);
  // next week (in the future: "My bookings" lists from today on)
  const NMON = dstr(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + 7));
  const D1 = dstr(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + 8)), D2 = dstr(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + 9));

  // ================= absences
  let w = await boot({user: 'alice', hash: 'workload'}), d = w.document;
  await until(() => d.querySelector('#view .ab2tabs'));
  const tabs = [...d.querySelectorAll('#view .ab2tabs button')].map(b => b.dataset.v);
  check(tabs.join() === 'wl,abs', 'tabs without the module: Workload | Absences ' + tabs);
  d.querySelector('#view .ab2tabs [data-v="abs"]').click();
  await until(() => d.querySelector('#view [data-act="ab2-new"]'));
  check(d.querySelector('#view .ab2table'), 'absences: the month grid');
  d.querySelector('#view [data-act="ab2-new"]').click();
  const md = await until(() => d.querySelector('.ab2md'));
  check(md && md.querySelectorAll('.ab2kinds button').length === 4, 'the sheet: four kinds');
  if (md) {
    md.querySelector('.ab2kinds [data-k="sick"]').click();
    md.querySelector('#ab2-from').value = D1; md.querySelector('#ab2-to').value = D2;
    md.querySelector('#ab2-from').dispatchEvent(new w.Event('change', {bubbles: true}));
    check(md.querySelector('#ab2-halfrow').hidden, 'two days: no half day');
    md.querySelector('[data-m="save"]').click();
  }
  const ab = await until(async () => { const j = await call('GET', `/api/team/absences?start=${D1}&end=${D2}`); return j.items?.length && j; });
  check(ab && ab.items[0].kind === 'sick' && ab.items[0].start_date === D1 && ab.items[0].end_date === D2, 'saved on the server ' + JSON.stringify(ab && ab.items));
  w.eval('AB2.start = ' + JSON.stringify(D1.slice(0, 7) + '-01') + '; ab2_reload()');
  check(await until(() => d.querySelectorAll('#view .ab2table td.off').length >= 1 && d.querySelector('#view .ab2list .ab2li')), 'the grid marks the days, the list shows the entry');
  await w.eval("histStep('undo')");
  check(await until(async () => !(await call('GET', `/api/team/absences?start=${D1}&end=${D2}`)).items?.length), 'Undo removes the absence');
  await w.eval("histStep('redo')");
  check(await until(async () => (await call('GET', `/api/team/absences?start=${D1}&end=${D2}`)).items?.length === 1), 'Redo brings it back');
  w.close();

  // ================= disposition
  await call('PATCH', '/api/settings', {features: [...feats, 'collab', 'workload', 'dispo'].join(',')});
  w = await boot({user: 'alice', hash: 'workload'}); d = w.document;
  await until(() => d.querySelector('#view .ab2tabs [data-v="dispo"]'));
  check(d.querySelector('#view .ab2tabs [data-v="dispo"]'), 'with the module: the tab Disposition');
  d.querySelector('#view .ab2tabs [data-v="dispo"]').click();
  await until(() => d.querySelector('#view [data-act="dp-new"]'));
  w.eval(`DPV.start = '${NMON}'; dp_reload()`);
  await until(() => d.querySelector('#view .dptable') && w.eval('DPV.data && DPV.data.start') === NMON);
  check(d.querySelector('#view .dptable') && [...d.querySelectorAll('#view .dptable th[scope="row"]')].some(x => x.textContent.includes('Camera A')), 'the grid: a row per resource (Camera A)');
  const book = async (title, day, ids) => {
    d.querySelector('#view [data-act="dp-new"]').click();
    const m = await until(() => d.querySelector('.dpmd'));
    m.querySelector('#dp-title').value = title;
    m.querySelector('#dp-from').value = day; m.querySelector('#dp-to').value = day;
    for (const [k, id] of ids) m.querySelector(`.dppick input[data-k="${k}"][value="${id}"]`).checked = true;
    m.querySelector('[data-m="save"]').click();
    await until(() => !d.querySelector('.dpmd'));
  };
  await book('Shoot day', D1, [['user', 1], ['equipment', CAM]]);
  check(await until(() => [...d.querySelectorAll('#view .dpbk')].some(b => b.textContent.includes('Shoot day'))), 'the booking shows as a bar');
  await book('Interview', D1, [['equipment', CAM]]);
  check(await until(() => d.querySelectorAll('#view .dpbk.warn').length >= 2), 'the same camera twice: both marked as a warning');
  const all = await call('GET', `/api/team/dispo?start=${D1}&days=1`);
  check(all.bookings?.length === 3, 'both bookings stay (warnings never block) ' + (all.bookings || []).length);
  d.querySelector('#dp-freeday').value = D1;
  d.querySelector('#view [data-act="dp-free"]').click();
  const fr = await until(() => d.querySelector('#view .dpfree'));
  check(fr && !fr.textContent.includes('Camera A') && fr.textContent.includes('Bob'), 'who is free: bob yes, the camera not');
  check(d.querySelector('#view .dpminel') && d.querySelector('#view .dpminel').textContent.includes('Shoot day'), 'my bookings: the shoot day (alice is booked)');
  w.close();

  // ================= phone width: a list per day
  w = await boot({user: 'alice', hash: 'workload', mobile: true}); d = w.document;
  await until(() => d.querySelector('#view .ab2tabs'));
  w.eval(`WLV.tab = 'dispo'; DPV.start = '${NMON}'; DPV.data = null; render()`);
  check(await until(() => d.querySelector('#view .dpdays .dpjob')), 'phone: the day list with the jobs');
  const css = require('./boot').allCssSync(); // 2.65.0 (#1824): + the module stylesheets
  check(/@media \(max-width:599px\)\{\.dpgrid\{display:none\}\.dpdays\{display:block\}\}/.test(css) && /\.dpjob\{[^}]*min-height:2\.75rem/.test(css), 'CSS: the grid gives way to the day list, large targets');
  check(/@media \(max-width:599px\)\{\.ab2grid\{display:none\}/.test(css), 'CSS: the absence grid gives way to the list');
  w.close();

  // ================= Firefox: the real layout
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const OVER = `(() => { const vw = document.documentElement.clientWidth, bad = [...document.querySelectorAll('#view *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1 && !e.closest('.wlwrap'); }).map(e => e.tagName + '.' + e.className).slice(0, 5); return {sw: document.scrollingElement.scrollWidth, vw, bad}; })()`;
    const tab = async v => { await ev(`(() => { WLV.tab = '${v}'; DPV.start = '${NMON}'; AB2.start = '${D1.slice(0, 7)}-01'; DPV.data = null; AB2.data = null; render(); return 1; })()`); };
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#workload');
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .ab2tabs")').catch(() => false)); i++) await sleep(300);
    await tab('abs');
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .ab2list")').catch(() => false)); i++) await sleep(300);
    let o = await ev(OVER);
    const g = await ev(`(() => ({grid: getComputedStyle(document.querySelector('#view .ab2grid')).display, li: document.querySelector('#view .ab2li')?.getBoundingClientRect().height || 0}))()`);
    check(o.sw <= o.vw + 1 && !o.bad.length && g.grid === 'none' && g.li >= 44, '390 px: absences inside the screen, the list instead of the grid ' + JSON.stringify({o, g}));
    await shot('p250a-absences-390.png');
    await tab('dispo');
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .dpdays .dpjob")').catch(() => false)); i++) await sleep(300);
    o = await ev(OVER);
    const p = await ev(`(() => ({grid: getComputedStyle(document.querySelector('#view .dpgrid')).display, days: getComputedStyle(document.querySelector('#view .dpdays')).display}))()`);
    check(o.sw <= o.vw + 1 && !o.bad.length && p.grid === 'none' && p.days === 'block', '390 px: the disposition as a day list inside the screen ' + JSON.stringify({o, p}));
    await shot('p250a-dispo-390.png');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + '#workload');
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .ab2tabs")').catch(() => false)); i++) await sleep(300);
    await tab('dispo');
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .dptable .dpbk")').catch(() => false)); i++) await sleep(300);
    const q = await ev(`(() => ({grid: getComputedStyle(document.querySelector('#view .dpgrid')).display, days: getComputedStyle(document.querySelector('#view .dpdays')).display, bars: document.querySelectorAll('#view .dpbk').length}))()`);
    check(q.grid !== 'none' && q.days === 'none' && q.bars >= 2, '1280 px: the grid with the bars ' + JSON.stringify(q));
    await shot('p250a-dispo-1280.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
