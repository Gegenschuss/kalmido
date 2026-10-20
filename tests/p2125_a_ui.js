// 2.125.0 UI tests of part A (#2118 working days, #2117 vacation account + requests; own container, start.sh). jsdom:
// - Settings > General: "Working week" with seven day buttons; a tap saves the working days at once (Undo restores them)
// - the absences tab: a member sees their vacation account line; with approvals on, a vacation they enter shows the hint,
//   becomes a request (striped in the grid, "requested" in the list, under "Your open vacation requests")
// - the admin: the open request with Approve / Reject; Approve = approved on the server, Undo opens it again; the sheet of
//   a person sets the entitlement and the working days
// Firefox (real layout, skipped without firefox): 390 px touch - the open request with its buttons stays inside the screen
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p2125_a_ui', check: (c, w) => check(c, w), shots: 'P2125A_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2125A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const st0 = await call('GET', '/api/state');
  const feats = [...(st0.settings.features || '').split(',').filter(Boolean), 'collab', 'workload'].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: 1})).id;
  sql('INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?) ON CONFLICT DO NOTHING', [ORG, BOB, 'member']);
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats}, CB);
  const t = new Date();
  // a Monday in two weeks (a request in the future), its month shown in the absences tab
  const mon = new Date(t.getFullYear(), t.getMonth(), t.getDate() - (t.getDay() + 6) % 7 + 14);
  const D1 = dstr(mon), D2 = dstr(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + 1)), M1 = D1.slice(0, 7) + '-01';
  check((await call('PUT', '/api/team/leave/quota', {user_id: BOB, year: mon.getFullYear(), days: 28, org: ORG})).quota?.days === 28, 'setup: bob has 28 days');
  check((await call('PUT', '/api/team/leave/approval', {on: true, org: ORG})).approval === true, 'setup: vacation needs an approval');

  // ================= #2118 Settings > General: the working week
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('general')`);
  const box = await until(() => d.querySelector('.smodal #s-wtdays'));
  check(box && box.querySelectorAll('button').length === 7 && box.querySelectorAll('button.on').length === 5, 'Working week: seven days, Monday..Friday on');
  check(d.querySelector('.smodal #s-wthours'), 'Working week: hours per week');
  check(w.eval(`NOTIF_ROWS.some(r => r[0] === 'leave')`), 'the notification settings have the row Vacation requests');
  box?.querySelector('[data-d="4"]').click();
  check(await until(async () => (await call('GET', '/api/state')).settings.workdays === '0,1,2,3'), 'a tap on Friday saves Monday..Thursday');
  check(box && box.querySelector('[data-d="4"]').getAttribute('aria-pressed') === 'false', 'Friday shows off');
  await w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', '/api/state')).settings.workdays === ''), 'Undo: Monday..Friday again');
  w.close();

  // ================= #2117 the member: account, request
  w = await boot({user: 'bob', hash: 'workload'}); d = w.document;
  await until(() => d.querySelector('#view .ab2tabs'));
  w.eval(`WLV.tab = 'abs'; AB2.start = '${M1}'; AB2.data = null; render()`);
  const acc = await until(() => d.querySelector('#view .lvacc'));
  check(acc && /28/.test(acc.textContent) && /left/.test(acc.textContent), 'bob sees his vacation account ' + (acc && acc.textContent));
  d.querySelector('#view [data-act="ab2-new"]').click();
  const md = await until(() => d.querySelector('.ab2md'));
  check(md && md.querySelector('.lvhint'), 'the sheet says that vacation is a request');
  if (md) {
    md.querySelector('#ab2-from').value = D1; md.querySelector('#ab2-to').value = D2;
    md.querySelector('#ab2-from').dispatchEvent(new w.Event('change', {bubbles: true}));
    md.querySelector('[data-m="save"]').click();
  }
  const ab = await until(async () => { const j = await call('GET', `/api/team/absences?start=${D1}&end=${D2}`, null, CB); return j.items?.length && j; });
  check(ab && ab.items[0].status === 'pending' && ab.items[0].kind === 'vacation', 'saved as a request ' + JSON.stringify(ab && ab.items));
  check(await until(() => d.querySelector('#view .ab2table td.off.req')), 'the grid shows the request striped');
  check(await until(() => /requested/.test(d.querySelector('#view .ab2list:not(.lvlist)')?.textContent || '')), 'the list says "requested"');
  check(await until(() => d.querySelector('#view .lvlist .lvreq')), 'under "Your open vacation requests"');
  check(!d.querySelector('#view [data-act="lv-ok"]'), 'bob has no Approve button');
  w.close();

  // ================= #2117 the admin: approve, Undo, the sheet of a person
  w = await boot({user: 'alice', hash: 'workload'}); d = w.document;
  await until(() => d.querySelector('#view .ab2tabs'));
  w.eval(`WLV.tab = 'abs'; AB2.start = '${M1}'; AB2.data = null; render()`);
  const okb = await until(() => d.querySelector('#view .lvreq [data-act="lv-ok"]'));
  check(okb && d.querySelector('#view .lvreq [data-act="lv-no"]'), 'the admin: Approve and Reject');
  okb?.click();
  check(await until(async () => (await call('GET', `/api/team/absences?start=${D1}&end=${D2}`)).items?.[0]?.status === 'approved'), 'Approve: approved on the server');
  check(await until(() => !d.querySelector('#view .lvreq')), 'no open request any more');
  await w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', `/api/team/absences?start=${D1}&end=${D2}`)).items?.[0]?.status === 'pending'), 'Undo: the request is open again');
  w.eval(`AB2.data = null; ab2_reload()`);
  const box2 = await until(() => w.eval('!!(AB2.data && LV.data && LV.data.people)') && d.querySelector('#view details.lvbox'));
  check(box2, 'the admin: the vacation accounts');
  if (box2) box2.open = true;
  d.querySelector(`#view [data-act="lv-edit"][data-uid="${BOB}"]`)?.click();
  const sh = await until(() => d.querySelector('.lvmd'));
  check(sh && sh.querySelectorAll('#lv-wd button').length === 7, 'the sheet: entitlement and working days');
  if (sh) {
    sh.querySelector('#lv-days').value = '25,5';
    sh.querySelector('#lv-wd [data-d="0"]').click();
    sh.querySelector('[data-m="save"]').click();
  }
  const lv = await until(async () => { const j = await call('GET', `/api/team/leave?year=${mon.getFullYear()}&org=${ORG}`); const p = j.people?.find(x => x.id === BOB); return p?.quota?.days === 25.5 && p; });
  check(lv && lv.workdays.join() === '1,2,3,4', 'saved: 25.5 days, Tuesday..Friday ' + JSON.stringify(lv));
  w.close();

  // ================= Firefox: the real layout on a phone
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#workload');
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .ab2tabs")').catch(() => false)); i++) await sleep(300);
    await ev(`(() => { WLV.tab = 'abs'; AB2.start = '${M1}'; AB2.data = null; render(); return 1; })()`);
    for (let i = 0; i < 30 && !(await ev('!!document.querySelector("#view .lvreq")').catch(() => false)); i++) await sleep(300);
    const o = await ev(`(() => { const vw = document.documentElement.clientWidth, b = document.querySelector('#view .lvreq [data-act="lv-ok"]')?.getBoundingClientRect(); return {sw: document.scrollingElement.scrollWidth, vw, right: b ? b.right : 0, h: b ? b.height : 0}; })()`);
    check(o.sw <= o.vw + 1 && o.right && o.right <= o.vw + 1 && o.h >= 36, '390 px: the request and its buttons inside the screen ' + JSON.stringify(o));
    await shot('p2125a-request-390.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
