// 2.312.0 D (#3266) UI, own container (start.sh): the admin's agent dialog, section "Runtime", has "Permission questions go
// to". A team agent: the select is filled from GET /api/agents/<id>/perm-users ("As set up on its computer" first, then the
// people it reaches in a shared project); choosing a person and saving stores runtime.perm_user. A personal agent: the select
// shows its owner only and stays disabled (nothing is sent). A new agent's dialog has no such row.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, B, login, until, idle} = require('./boot');
const {shareAny} = require('./legacy');  // one agent per list
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: 'collab,comments,agents', lang: 'en', tour: 'done'});
  const me = (await call('GET', '/api/state')).me.id;
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'})).id;
  await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'});
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const own = await call('POST', '/api/admin/agents', {username: 'mine', display_name: 'Mine', owner_id: me});
  const L = (await call('POST', '/api/lists', {name: 'Household'})).id;
  await shareAny(call, DATA, L, ag.id, 'edit');
  await call('PUT', `/api/lists/${L}/members`, {user_id: bob, role: 'admin'});
  const adm = async id => (await call('GET', '/api/admin/agents')).agents.find(a => a.id === id);

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  // ---- a team agent
  w.eval(`agModal(${JSON.stringify(await adm(ag.id))}, null)`);
  const sel = await until(() => { const s = d.querySelector('#ag-pu'); return s && !s.disabled && s.options.length > 1 && s; });
  const md = sel && sel.closest('.modal');
  const names = sel ? [...sel.options].map(o => o.textContent) : [];
  check(sel && names[0] === 'As set up on its computer' && sel.value === '', `team agent: first "As set up on its computer", selected: ${names}`);
  check(names.slice(1).sort().join() === 'Alice,Bob', `team agent: only the people it reaches (no Carol): ${names}`);
  check(/Only people it reaches in a shared project/.test(md?.querySelector('#ag-puhint')?.textContent || ''), 'team agent: the hint says who can be chosen');
  if (sel) {
    sel.value = String(bob);
    click(w, md.querySelector('[data-m="ok"]'));
    await until(() => !d.querySelector('#ag-pu'));
    await idle(w);
  }
  check((await adm(ag.id))?.runtime?.perm_user === bob, 'saving stores bob as runtime.perm_user');
  w.eval(`agModal(${JSON.stringify(await adm(ag.id))}, null)`);
  const sel2 = await until(() => { const s = d.querySelector('#ag-pu'); return s && !s.disabled && s.options.length > 1 && s; });
  check(sel2 && sel2.value === String(bob), 'opened again: bob is selected');
  click(w, sel2?.closest('.modal')?.querySelector('[data-m="close"]'));
  await until(() => !d.querySelector('#ag-pu'));

  // ---- a personal agent: its owner only, no choice
  w.eval(`agModal(${JSON.stringify(await adm(own.id))}, null)`);
  const sel3 = await until(() => { const s = d.querySelector('#ag-pu'); return s && s.options.length === 1 && s.options[0].value === String(me) && s; });
  check(sel3 && sel3.disabled && sel3.options[0].textContent === 'Alice', 'personal agent: the owner only, disabled');
  check(/A personal agent asks its owner/.test(d.querySelector('#ag-puhint')?.textContent || ''), 'personal agent: the hint');
  click(w, sel3?.closest('.modal')?.querySelector('[data-m="close"]'));
  await until(() => !d.querySelector('#ag-pu'));

  // ---- a new agent: no row yet
  w.eval('agModal(null, null, {kind: "team"})');
  await until(() => d.querySelector('#ag-model'));
  check(d.querySelector('#ag-model') && !d.querySelector('#ag-pu'), 'new agent: no choice yet');

  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  console.log(`p2312_d_perm_user_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
