// 2.144.2 part B UI tests (flows and state), own container (start.sh). jsdom:
// - #2467 five subtasks typed fast while the server answers slowly: all five rows show at once (before any answer), in order;
//   after the answers no duplicates, real ids, the same order after a reload
// - #2370 the table print view: an early afterprint + media end (Android) keep it until the user is back in the app; a late
//   afterprint (desktop) still removes it at once
// - #1811 calendar draft: Confirm drops Draft / Confirm from the popover at once; a popover opened again while the confirm is
//   on its way shows no Draft
// - #1644 office search: typing keeps the same field (and its focus), only the result list is drawn again
// - #2375 vacation approved: the hint has Undo; "Use this device" comes back at once after another zone; the vacation
//   accounts stay open after a save
// - #2352 the receipt sheet's account line keeps the last known accounts while the books reload
// - #2372 cash flow: "Use as real balance" sits in its own bar below the month's table, not in a table cell
// freelancer-matrix: none (no new routes)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21442B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'cal', 'collab', 'comments', 'time', 'events', 'workload', 'office'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: 1})).id;
  sql('INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?) ON CONFLICT DO NOTHING', [ORG, BOB, 'member']);
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats}, CB);
  const L = (await call('POST', '/api/lists', {name: 'Flat'})).id;
  const P = (await call('POST', '/api/tasks', {title: 'Kitchen', list_id: L})).id;

  // ================= #2467 subtasks show at once
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const f0 = w.fetch; let answered = 0;
  w.fetch = (u, o = {}) => /\/api\/tasks$/.test(String(u)) && o.method === 'POST' ? sleep(4000).then(() => f0(u, o)).then(r => { answered++; return r; }) : f0(u, o);
  w.eval(`openDetail(${P})`); await until(() => d.querySelector('#d-sub'));
  const NAMES = ['One bulb', 'Two switch', 'Three wall', 'Four tap', 'Five door'];
  for (const n of NAMES) { const f = d.querySelector('#d-sub'); f.focus(); f.value = n; f.dispatchEvent(new w.Event('input', {bubbles: true})); key(w, f, 'Enter'); await sleep(20); }
  const shown = () => [...d.querySelectorAll('#detail .subs .trow')].map(r => NAMES.find(n => r.textContent.includes(n))).filter(Boolean);
  const early = shown();
  check(answered === 0 && JSON.stringify(early) === JSON.stringify(NAMES), '#2467: all five rows at once, before any answer, in order: ' + JSON.stringify(early) + ' answered ' + answered);
  check(d.querySelector('#d-sub')?.value === '' && d.activeElement === d.querySelector('#d-sub'), '#2467: the field is empty and keeps the focus');
  await until(() => answered >= 5, 200); await sleep(400);
  const ids = [...d.querySelectorAll('#detail .subs .trow')].map(r => +r.dataset.id);
  check(JSON.stringify(shown()) === JSON.stringify(NAMES) && ids.length === 5 && ids.every(i => i > 0), '#2467: after the answers five real rows, no duplicates: ' + JSON.stringify(ids));
  const srv = (await call('GET', '/api/state')).tasks.filter(t => t.parent_id === P).sort((a, b) => a.sort - b.sort || a.id - b.id).map(t => t.title);
  check(JSON.stringify(srv) === JSON.stringify(NAMES), '#2467: the server has them in order ' + JSON.stringify(srv));
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`openDetail(${P})`); await until(() => d.querySelectorAll('#detail .subs .trow').length >= 5);
  check(JSON.stringify(shown()) === JSON.stringify(NAMES), '#2467: the same order after a reload ' + JSON.stringify(shown()));

  // ================= #2370 the print view stays on Android
  await w.eval(`loadModule('sheets')`); await until(() => w.eval(`typeof shk_print === 'function'`));
  const pr = await w.eval(`(async () => {
    const out = {}; let mqL = null; const mq = {matches: false, addEventListener: (t, f) => { mqL = f; }, removeEventListener: () => { mqL = null; }};
    const mm = window.matchMedia; window.matchMedia = q => q === 'print' ? mq : mm.call(window, q);
    SHV.sh = {id: 987654, title: 'Print me', columns: [], rows: [], _rowNo: new Map()};
    const on = () => document.body.classList.contains('shkprint') && !!document.getElementById('shk-print');
    let mqEnd = false; window.print = () => { mq.matches = true; mqL?.(); dispatchEvent(new Event('afterprint')); setTimeout(() => { mq.matches = false; mqL?.(); mqEnd = true; }, 30); };
    shk_print(); await new Promise(r => setTimeout(r, 900));
    out.kept = on();
    dispatchEvent(new FocusEvent('focus')); out.focusNoBlur = on();  // a focus without leaving first is no return
    dispatchEvent(new FocusEvent('blur')); dispatchEvent(new FocusEvent('focus'));
    out.goneBack = !on();
    // 2.144.2 (#2370): on a slow runner the media end of the first run (30 ms timer) can come late and hit the second run before
    // its print() (early end -> view kept) -> wait for it first
    for (let i = 0; i < 200 && !mqEnd; i++) await new Promise(r => setTimeout(r, 20));
    let printedAt = 0; window.print = () => { printedAt = performance.now(); };  // desktop: print() blocks, afterprint comes when the dialog closes
    // 2.145.0: wait for the real print() call, then past the 500 ms early window (a fixed 700 ms was flaky on a busy first run)
    shk_print(); for (let i = 0; i < 100 && !printedAt; i++) await new Promise(r => setTimeout(r, 20));
    await new Promise(r => setTimeout(r, Math.max(0, printedAt + 650 - performance.now())));
    out.desk1 = on(); dispatchEvent(new Event('afterprint')); out.desk2 = !on();
    window.matchMedia = mm; SHV.sh = null; return JSON.stringify(out);
  })()`);
  const prj = JSON.parse(pr || '{}');
  check(prj.kept && prj.focusNoBlur, '#2370: early afterprint + media end keep the print view ' + pr);
  check(prj.goneBack, '#2370: back in the app (blur, focus): the view goes ' + pr);
  check(prj.desk1 && prj.desk2, '#2370: desktop: a late afterprint removes it at once ' + pr);
  w.close();

  // ================= #1811 calendar draft confirm
  const now = new Date(TC.today() + 'T12:00:00'), t1 = dstr(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
  const ev = await call('POST', '/api/events', {title: 'Shoot day draft', start: `${t1}T09:00`, end: `${t1}T17:00`, status: 'tentative'});
  check(ev.http === 201 && ev.status === 'tentative', 'setup: a tentative event ' + ev.http);
  w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"week"'}}); d = w.document;
  w.eval(`S.calSel = '${t1}'; renderView()`);
  const g0 = w.fetch;
  w.fetch = (u, o = {}) => /\/api\/events\/\d+$/.test(String(u)) && o.method === 'PATCH' ? sleep(1500).then(() => g0(u, o)) : g0(u, o);
  const chip = await until(() => [...d.querySelectorAll('#view [data-cev]')].find(x => /Shoot day draft/.test(x.textContent)));
  click(w, chip);
  const pop = await until(() => d.querySelector('#pop .evpop [data-evp="apok"]') && d.querySelector('#pop'));
  check(pop && pop.querySelector('.evdraftb'), 'setup: the popover says Draft + Confirm');
  click(w, pop?.querySelector('[data-evp="apok"]'));
  check(!d.querySelector('#pop .apdraftact, #pop .evdraftb'), '#1811: Draft + Confirm leave the popover at once (also its exit picture)');
  click(w, chip);  // opened again while the confirm is still on its way
  const pop2 = await until(() => d.querySelector('#pop:not(.hidden) .evpop [data-evp="edit"]') && d.querySelector('#pop'));
  check(pop2 && !pop2.querySelector('.evdraftb, [data-evp="apok"]'), '#1811: the popover opened again meanwhile shows no Draft ' + (pop2?.textContent || '').slice(0, 120));
  check(await until(async () => (await call('GET', `/api/events/${ev.id}`)).status === 'confirmed'), '#1811: confirmed on the server');
  w.close();

  // ================= #1644 office search keeps the field
  await call('POST', '/api/office/services', {name_de: 'Kamera', name_en: 'Camera', category: 'Video', unit: 'day', daily_rate: 900});
  await call('POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Editing', category: 'Video', unit: 'hour', hourly_rate: 120});
  w = await boot({user: 'alice', hash: 'office/services'}); d = w.document;
  const rows0 = await until(() => d.querySelectorAll('.office .ofcrow').length >= 2, 80);
  check(rows0, 'setup: the office services list ' + d.querySelectorAll('.office .ofcrow').length);
  const q = d.querySelector('#ofc-q');
  if (q) {
    q.focus();
    for (const s of ['e', 'ed', 'edi', 'edit']) { q.value = s; q.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(60); }
    await sleep(200);
    check(d.querySelector('#ofc-q') === q && d.activeElement === q && q.value === 'edit', '#1644: the same search field keeps the focus and every letter');
    check(d.querySelectorAll('.office .ofcrow').length === 1 && /Schnitt/.test(d.querySelector('.office .ofcrow')?.textContent || ''), '#1644: the result list follows the search');
    q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(200);
    check(d.querySelectorAll('.office .ofcrow').length === 2, '#1644: empty search: all rows again');
  } else check(false, '#1644: no search field');

  // ================= #2352 account line while the books reload
  await w.eval(`loadModule('office')`); await until(() => w.eval(`typeof bkAcctLine === 'function'`));
  const acc = w.eval(`(() => {
    BK.info = {accounts: {chart: 'SKR03', own: {}, categories: {Travel: {account: '4670', default: '4670', own: false}}}};
    const md = document.createElement('div'); md.className = 'modal bk-sheet'; md.innerHTML = '<input id="bk-cat" value="Travel"><div class="bk-acct"></div>';
    document.body.appendChild(md); bkAcctLine(md); const a = md.querySelector('.bk-acct').textContent;
    BK.info = null; bkAcctLine(md); const b = md.querySelector('.bk-acct').textContent;  // the books reload (Take over / undo)
    md.remove(); return JSON.stringify({a, b});
  })()`);
  const accj = JSON.parse(acc || '{}');
  check(/4670/.test(accj.a || '') && /4670/.test(accj.b || ''), '#2352: the account line stays while the books reload ' + acc);
  w.close();

  // ================= #2372 the real-balance bar (source of the row builder: own bar after the table)
  w = await boot({user: 'alice', hash: 'office'}); d = w.document;
  await w.eval(`loadModule('office')`); await until(() => w.eval(`typeof cfb_realBar === 'function'`));
  const rb = w.eval(`(() => { const r = {month: '2026-05', account: 100, real: null, bank: {amount: 1234, day: '2026-05-31', diff: 0}};
    const box = document.createElement('div'); box.innerHTML = '<table><tbody>' + cfb_rows(r) + '</tbody></table>' + cfb_realBar(r);
    return JSON.stringify({inCell: !!box.querySelector('td [data-cfb="real"]'), bar: !!box.querySelector(':scope > .cfb-real [data-cfb="real"]'),
      none: cfb_realBar({...r, real: 5}) === '' && cfb_realBar({...r, bank: null}) === ''}); })()`);
  const rbj = JSON.parse(rb || '{}');
  check(rbj.bar && !rbj.inCell && rbj.none, '#2372: "Use as real balance" in its own bar below the table ' + rb);
  w.close();

  // ================= #2375 vacation: Undo in the hint, accounts stay open; time zone button
  const t = new Date(), mon = new Date(t.getFullYear(), t.getMonth(), t.getDate() - (t.getDay() + 6) % 7 + 14);
  const D1 = dstr(mon), D2 = dstr(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + 1)), M1 = D1.slice(0, 7) + '-01';
  await call('PUT', '/api/team/leave/quota', {user_id: BOB, year: mon.getFullYear(), days: 28, org: ORG});
  check((await call('PUT', '/api/team/leave/approval', {on: true, org: ORG})).approval === true, 'setup: vacation needs an approval');
  const rq = await call('POST', '/api/team/absences', {kind: 'vacation', start_date: D1, end_date: D2, org: ORG}, CB);
  check(rq.status === 'pending', 'setup: bob\'s request is pending ' + JSON.stringify(rq).slice(0, 160));
  w = await boot({user: 'alice', hash: 'workload'}); d = w.document;
  await until(() => d.querySelector('#view .ab2tabs'));
  w.eval(`WLV.tab = 'abs'; AB2.start = '${M1}'; AB2.data = null; render()`);
  const okb = await until(() => d.querySelector('#view .lvreq [data-act="lv-ok"]'), 60);
  click(w, okb);
  check(await until(async () => (await call('GET', `/api/team/absences?start=${D1}&end=${D2}`)).items?.[0]?.status === 'approved'), '#2375: approved on the server');
  const tb = await until(() => { const el = d.querySelector('#toast:not(.hidden)'); return el && /Vacation approved/.test(el.textContent) && el.querySelector('button:not(.tx)') && el; });
  check(tb, '#2375: the hint "Vacation approved" has Undo ' + (d.querySelector('#toast')?.textContent || ''));
  click(w, tb?.querySelector('button:not(.tx)'));
  check(await until(async () => (await call('GET', `/api/team/absences?start=${D1}&end=${D2}`)).items?.[0]?.status === 'pending'), '#2375: Undo in the hint: the request is open again');
  const box = await until(() => w.eval('!!(LV.data && LV.data.people)') && d.querySelector('#view details.lvbox'), 60);
  if (box) { box.open = true; box.dispatchEvent(new w.Event('toggle')); }
  await sleep(100);
  const sw = d.querySelector('#view #lv-approval');
  if (sw) { sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => (await call('GET', `/api/team/leave?org=${ORG}&year=${mon.getFullYear()}`)).approval === false), '#2375: the approval switch saved');
  await until(() => w.eval('!!(LV.data && LV.data.people)') && d.querySelector('#view details.lvbox') && !d.querySelector('#view #lv-approval')?.checked, 60);
  check(d.querySelector('#view details.lvbox')?.open === true, '#2375: the vacation accounts stay open after the save');
  w.close();

  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('time')`);
  const tz = await until(() => d.querySelector('.smodal #s-ttz'));
  const dev = w.eval('tsl_deviceTz()');
  if (tz && dev) {
    const other = [...tz.options].map(o => o.value).find(v => v && v !== dev);
    tz.value = dev; tz.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(100);
    check(!d.querySelector('.smodal [data-tsl="tzdev"]'), '#2375: the device zone chosen: no "Use this device"');
    tz.value = other; tz.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(100);
    check(!!d.querySelector('.smodal [data-tsl="tzdev"]'), '#2375: another zone: "Use this device" at once');
  } else check(false, '#2375: the time zone row ' + !!tz + ' ' + dev);
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
