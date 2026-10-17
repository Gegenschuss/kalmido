// 2.88.0 part B UI test (#1980), own container (start.sh): the admin user management for hundreds of accounts.
// - Settings > Administration > Users: a search field and a filter above the list, pages of 50 (previous / next, "1–50 of N"),
//   the own account cannot be selected, a selection shows the bar (disable / enable / add to an organisation / clear)
// - the delete dialog of an account with lists: the lists by name, "Hand them over to" (the default) with the people every
//   list may go to, "Delete them along" only after the user name is typed; handing over deletes the account
// - Firefox (phone width, touch): search bar, list and delete dialog inside the screen; screenshots with P288B_SHOTS=<dir>
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p288_b_ui', check, shots: 'P288B_SHOTS'});
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const rows = md => [...md.querySelectorAll('#a-users .mrow[data-urow]')];
const pick = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const type = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob Example', password: 'password123', email: 'bob@example.com'})).id;
  const CAROL = (await call('POST', '/api/users', {orgs: [ORG], username: 'carol', display_name: 'Carol Example', password: 'password123', email: 'carol@example.com'})).id;
  for (let i = 0; i < 60; i++) await call('POST', '/api/users', {username: `pers${String(i).padStart(2, '0')}`, display_name: `Person ${String(i).padStart(2, '0')}`});
  const CB = await login('bob');
  const BL = (await call('POST', '/api/lists', {name: 'Bob plan', org_id: ORG}, CB)).id;
  await call('PUT', `/api/lists/${BL}/members`, {user_id: CAROL, role: 'edit'}, CB);

  // ---- the list: search, filter, pages, selection
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await until(() => d.querySelector('#side .srow'));
  w.eval(`settingsModal('users')`);
  const md = (await until(() => d.querySelector('.modal #a-users .mrow[data-urow]'))).closest('.modal');
  check(md.querySelector('#a-uq[type="search"]') && md.querySelector('#a-uflt option[value="disabled"]'), 'a search field and a filter above the list');
  check(rows(md).length === 50, 'a page of 50 rows ' + rows(md).length);
  const pg = md.querySelector('#a-upg');
  check(/1–50 of 63/.test(pg.textContent) && pg.querySelector('[data-upg="-1"]').disabled && !pg.querySelector('[data-upg="1"]').disabled, 'pager: 1–50 of 63 ' + pg.textContent);
  pg.querySelector('[data-upg="1"]').click();
  await until(() => rows(md).length === 13);
  check(rows(md).length === 13 && /51–63 of 63/.test(md.querySelector('#a-upg').textContent), 'the second page: 13 rows');
  type(w, md.querySelector('#a-uq'), 'carol@exa');
  await until(() => rows(md).length === 1);
  check(rows(md).length === 1 && /Carol Example/.test(rows(md)[0].textContent) && !md.querySelector('#a-upg').textContent.trim().length, 'search by e-mail: one row, no pager');
  type(w, md.querySelector('#a-uq'), '');
  pick(w, md.querySelector('#a-uflt'), 'disabled');
  await until(() => /Nothing found/.test(md.querySelector('#a-users').textContent));
  check(/Nothing found/.test(md.querySelector('#a-users').textContent), 'filter disabled: nothing found');
  pick(w, md.querySelector('#a-uflt'), 'people');
  await until(() => rows(md).length === 50);
  check(md.querySelector(`[data-usel="${w.eval('S.me.id')}"]`)?.disabled, 'the own account cannot be selected');
  const cb = md.querySelector(`[data-usel="${BOB}"]`);
  cb.checked = true; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  const bar = md.querySelector('#a-usel');
  check(!bar.hidden && /1 selected/.test(bar.textContent) && bar.querySelector('[data-ubulk="disable"]') && bar.querySelector('[data-ubulk="enable"]'), 'a selection shows the bar ' + bar.textContent);
  bar.querySelector('[data-ubulk="clear"]').click();
  check(bar.hidden && !cb.checked, 'clear selection');

  // ---- the delete dialog
  w.eval(`window.__del = ua8_delete({id: ${BOB}, display_name: 'Bob Example'})`);
  const dd = (await until(() => d.querySelector('.modal .ua8how'))).closest('.modal');
  check(/Bob plan/.test(dd.querySelector('.ua8lists').textContent) && /shared with Carol Example/.test(dd.querySelector('.ua8lists').textContent), 'the lists by name and with whom shared ' + dd.querySelector('.ua8lists').textContent);
  const tr = dd.querySelector('[name="ua8how"][value="transfer"]'), dl = dd.querySelector('[name="ua8how"][value="delete"]'), go = dd.querySelector('[data-m="go"]');
  check(tr.checked && !go.disabled && [...dd.querySelectorAll('#ua8-to option')].some(o => +o.value === CAROL), 'default: hand over, Carol offered');
  check(dd.querySelector('#ua8-del').hidden, 'the typed confirmation is hidden while handing over');
  dl.checked = true; dl.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(!dd.querySelector('#ua8-del').hidden && go.disabled && /shared/.test(dd.querySelector('#ua8-del').textContent), 'delete along: the warning, the button waits for the name');
  type(w, dd.querySelector('#ua8-conf'), 'bobx');
  check(go.disabled, 'a wrong name keeps it disabled');
  type(w, dd.querySelector('#ua8-conf'), 'bob');
  check(!go.disabled, 'the typed user name enables it');
  tr.checked = true; tr.dispatchEvent(new w.Event('change', {bubbles: true}));
  pick(w, dd.querySelector('#ua8-to'), String(CAROL));
  go.click();
  const res = await Promise.race([w.eval('window.__del'), sleep(5000).then(() => 'timeout')]);
  check(res === true && !dd.isConnected, 'handed over: the dialog closes ' + res);
  const own = await call('GET', `/api/lists/${BL}/owner`, null, await login('carol'));
  check(own.owner?.id === CAROL, 'Carol owns Bob\'s list ' + JSON.stringify(own.owner));
  check((await call('GET', '/api/users?all=1&limit=50&q=bob')).total === 0, 'Bob\'s account is gone');
  w.close();

  // ---- Firefox, phone width: inside the screen
  const D2 = (await call('POST', '/api/users', {orgs: [ORG], username: 'dora', display_name: 'Dora Example', password: 'password123', email: 'dora@example.com'})).id;
  await call('POST', '/api/lists', {name: 'Dora notes', org_id: ORG}, await login('dora'));
  await firefox(async o => {
    const {cmd, ev, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'phone: login');
    await nav(B + '#today');
    for (let i = 0; i < 40 && !(await ev(`typeof settingsModal === 'function' && !!document.querySelector('#side')`).catch(() => false)); i++) await sleep(250);
    await ev(`(settingsModal('users'), 1)`);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#a-users .mrow[data-urow]')`).catch(() => false)); i++) await sleep(250);
    const x = await ev(`(() => { const q = document.querySelector('#a-uq').getBoundingClientRect(), f = document.querySelector('#a-uflt').getBoundingClientRect(), c = document.querySelector('#a-users .ua8chk').getBoundingClientRect();
      return {qr: Math.round(q.right), fr: Math.round(f.right), qw: Math.round(q.width), cw: Math.round(c.width), vw: innerWidth}; })()`);
    check(x && x.fr <= x.vw && x.qw >= 120 && x.cw >= 20, 'phone: search and filter inside the screen, a large tick box ' + JSON.stringify(x));
    await shot('p288b-users-390.png');
    await ev(`(ua8_delete({id: ${D2}, display_name: 'Dora Example'}), 1)`);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('.modal .ua8how')`).catch(() => false)); i++) await sleep(250);
    const y = await ev(`(() => { const c = document.querySelector('.modal .ua8how').closest('.card').getBoundingClientRect(), s = document.querySelector('#ua8-to').getBoundingClientRect();
      return {l: Math.round(c.left), r: Math.round(c.right), sr: Math.round(s.right), vw: innerWidth}; })()`);
    check(y && y.l >= 0 && y.r <= y.vw && y.sr <= y.vw, 'phone: the delete dialog inside the screen ' + JSON.stringify(y));
    await shot('p288b-delete-390.png');
  }, true);

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
