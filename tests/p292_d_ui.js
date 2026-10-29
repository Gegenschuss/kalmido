// 2.92.0 part D UI test (#2008, #2009, #2010), own container (start.sh): three small fixes from the 2.88 device tests.
// - #2008 delete user: "Hand them over to" preselects the deleting admin; without them in the candidates nothing is preselected
//   (Please choose, button locked); invited accounts that never logged in come last
// - #2009 phone: the toast never covers the quotation editor's "In the cash flow" choice
// - #2010 phone: ticking the first user does not move the list (the selection bar is fixed above the tab bar)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p292_d_ui', check, shots: 'P292D_SHOTS'});
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P292D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab,office,clients'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob Example', password: 'password123', email: 'bob@example.com'})).id;
  const CAROL = (await call('POST', '/api/users', {orgs: [ORG], username: 'carol', display_name: 'Carol Example', password: 'password123', email: 'carol@example.com'})).id;
  const BL = (await call('POST', '/api/lists', {name: 'Bob plan', org_id: ORG}, await login('bob'))).id;
  await call('PUT', `/api/lists/${BL}/members`, {user_id: CAROL, role: 'edit'}, await login('bob'));
  const CL = (await call('POST', '/api/clients', {name: 'Kunde Eins GmbH'})).id;
  const q = await call('POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: CL});
  await call('PUT', `/api/office/docs/${q.id}/items`, {items: [{kind: 'service', title: 'Dreh', qty: 1, unit: 'day', rate: 1000}]});

  // ---- #2008: the deleting admin is preselected
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await until(() => d.querySelector('#side .srow'));
  const ME = w.eval('S.me.id');
  w.eval(`window.__del = ua8_delete({id: ${BOB}, display_name: 'Bob Example'})`);
  let dd = (await until(() => d.querySelector('.modal .ua8how'))).closest('.modal');
  let sel = dd.querySelector('#ua8-to');
  check(+sel.value === ME && !dd.querySelector('[data-m="go"]').disabled, 'the deleting admin is preselected: ' + sel.value + ' vs ' + ME);
  dd.querySelector('[data-m="close"]').click();
  // without the admin among the candidates: nothing preselected, the button waits for a choice
  w.eval(`window.__api = api; api = async (m, u, b) => u.endsWith('/delete-info') ? {can_delete: true, username: 'bob', lists: [{id: 1, name: 'X', org_id: null, shared: 0, members: []}], candidates: [{id: ${CAROL}, name: 'Carol Example'}, {id: 99999, name: 'Zed Invited', invited: true}]} : window.__api(m, u, b)`);
  w.eval(`window.__del = ua8_delete({id: ${BOB}, display_name: 'Bob Example'})`);
  dd = (await until(() => d.querySelector('.modal .ua8how'))).closest('.modal');
  sel = dd.querySelector('#ua8-to');
  check(sel.value === '' && dd.querySelector('[data-m="go"]').disabled, 'no admin among the candidates: nothing preselected, button locked');
  check(/Invited/.test(sel.options[sel.options.length - 1].textContent), 'invited accounts stand last');
  sel.value = String(CAROL); sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(!dd.querySelector('[data-m="go"]').disabled, 'a choice unlocks the button');
  dd.querySelector('[data-m="close"]').click();
  w.eval('api = window.__api');

  // ---- phone: #2009 and #2010
  for (let i = 0; i < 12; i++) await call('POST', '/api/users', {username: `pers${i}`, display_name: `Person ${String(i).padStart(2, '0')}`});
  await firefox(async o => {
    const {cmd, ev, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + `#office/offers/${q.id}`);
    for (let i = 0; i < 60 && !(await ev(`!!document.querySelector('.cf8sec .seg')`).catch(() => false)); i++) await sleep(250);
    await ev(`(document.querySelector('.cf8sec .seg').scrollIntoView({block: 'end'}), toast('Saved', () => {}), 1)`);
    await sleep(400);
    const t = await ev(`(() => { const a = document.querySelector('#toast').getBoundingClientRect(), b = document.querySelector('.cf8sec .seg').getBoundingClientRect(); return {at: Math.round(a.top), ab: Math.round(a.bottom), bt: Math.round(b.top), bb: Math.round(b.bottom)}; })()`);
    check(t && (t.ab <= t.bt || t.at >= t.bb), 'phone: the toast does not cover the cash flow choice ' + JSON.stringify(t));
    await shot('p292d-toast-390.png');

    await nav(B + '#today');
    for (let i = 0; i < 40 && !(await ev(`typeof settingsModal === 'function' && !!document.querySelector('#side')`).catch(() => false)); i++) await sleep(250);
    await ev(`(settingsModal('users'), 1)`);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#a-users .ua8chk:not(:disabled)')`).catch(() => false)); i++) await sleep(250);
    const top0 = await ev(`Math.round(document.querySelector('#a-users').getBoundingClientRect().top)`);
    await ev(`(() => { const c = document.querySelector('#a-users .ua8chk:not(:disabled)'); c.click(); return 1; })()`);
    await sleep(400);
    const top1 = await ev(`Math.round(document.querySelector('#a-users').getBoundingClientRect().top)`);
    const bar = await ev(`(() => { const r = document.querySelector('#ua-sbar').getBoundingClientRect(); return {hidden: document.querySelector('#a-usel').hidden, b: Math.round(r.bottom), vh: innerHeight}; })()`);
    check(top0 === top1, 'phone: the list stays put on the first tick ' + top0 + ' -> ' + top1);
    check(bar && !bar.hidden && bar.b <= bar.vh, 'phone: the selection bar is inside the screen ' + JSON.stringify(bar));
    await shot('p292d-users-390.png');
  }, true);

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
