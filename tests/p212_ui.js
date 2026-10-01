// 2.1.2 UI tests (jsdom), own container (start.sh)
// #349 list dialog > Sharing: "Transfer ownership…" for the owner (members first, confirm, the list changes hands, the
// history line), nothing for a member; "Take over…" with the reason for an admin in a list of a disabled user;
// Settings > Administration > "Lists owned by agents or disabled users" with "Take over" (default: me); the News text.
// #346 Settings > Administration > Users: agents as rows with the Agent badge and "Managed under AI colleague" (opens the
// agent dialog, no user edit button); the agent dialog: username editable, picture presets / upload / none, saved.
// Desktop + phone, German texts; SW v62
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = fn(); if (x) return x; await sleep(150); } return fn(); };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,agents';

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(6[2-9]|7[0-4])'/.test(SW), 'service worker cache v62 (2.2.0: v63, 2.2.1: v64, 2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73, 2.7.0: v74)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const ids = {};
  for (const u of ['bob', 'carol', 'erin']) ids[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123'})).id;
  const CKB = await login('bob'), CKE = await login('erin');
  for (const ck of [CKB, CKE]) await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, ck);
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude'});
  const TEAM = (await call('POST', '/api/lists', {name: 'Team'})).id;
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: ids.bob, role: 'edit'});
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: ag.id, role: 'edit'});
  const DEV = (await v1(ag.token, 'POST', '/lists', {name: 'Dev list'})).id;
  const DEV2 = (await v1(ag.token, 'POST', '/lists', {name: 'Dev list 2'})).id;
  const ERIN = (await call('POST', '/api/lists', {name: 'Erins list'}, CKE)).id;
  await call('PUT', `/api/lists/${ERIN}/members`, {user_id: 1, role: 'edit'}, CKE);
  await call('PATCH', `/api/users/${ids.erin}`, {disabled: true});

  // ================= the owner transfers from the Share dialog (2.6.0: out of the list dialog)
  let w = await boot({user: 'alice', hash: 'l/' + TEAM}), d = w.document;
  w.eval(`shareModal(${TEAM})`);
  let btn = await until(() => d.querySelector('.shmodal #l-owner [data-m="own-xfer"]'));
  check(btn && /Transfer ownership…/.test(btn.textContent), 'owner: "Transfer ownership…" in the Share dialog (2.6.0, K12)');
  click(w, btn); await sleep(300);
  let om = d.querySelector('.modal.owmodal');
  const opts = [...(om?.querySelectorAll('#ow-to option') || [])];
  check(om && opts.length === 2 && /Bob · Member/.test(opts[0].textContent) && /Carol/.test(opts[1].textContent) && !opts.some(o => /Claude|Erin|Alice/.test(o.textContent)),
    'the new owner: people only, members first with their role: ' + opts.map(o => o.textContent).join('|'));
  check(om && om.querySelector('#ow-to').value === String(ids.bob) && /You stay in the list as a list admin/.test(om.textContent), 'default: the first member; the hint');
  let asked = '';
  w.confirm = m => { asked = m; return true; };
  click(w, om.querySelector('[data-m="ok"]')); await sleep(1500);
  check(/Make Bob the owner of “Team”\?/.test(asked), 'confirm asked: ' + asked);
  check(!d.querySelector('.modal.owmodal') && !d.querySelector('.shmodal'), 'both dialogs closed');
  check(w.eval(`listById(${TEAM}).role`) === 'admin' && w.eval(`listById(${TEAM}).owner_name`) === 'Bob', 'alice is now a list admin, Bob the owner');
  w.eval(`shareModal(${TEAM})`);
  await until(() => d.querySelector('.shmodal .owhist'));
  check(/Ownership transferred from Alice to Bob/.test(d.querySelector('.shmodal .owhist')?.textContent || ''), 'the history line');
  check(!d.querySelector('.shmodal [data-m="own-xfer"]'), 'no transfer button for a member');
  w.close();
  // bob: the News item
  w = await boot({user: 'bob', hash: 'news'}); d = w.document; await sleep(600);
  check(/Alice made you the owner of the list Team/.test(d.body.textContent), 'News: "Alice made you the owner of the list Team"');
  w.close();

  // ================= an admin in the list of a disabled user: "Take over…"
  w = await boot({user: 'alice', hash: 'l/' + ERIN}); d = w.document;
  w.eval(`shareModal(${ERIN})`);
  btn = await until(() => d.querySelector('.shmodal #l-owner [data-m="own-xfer"]'));
  check(btn && /Take over…/.test(btn.textContent) && /The owner Erin is disabled/.test(d.querySelector('.shmodal #l-owner').textContent), 'admin: "Take over…" with the reason');
  click(w, btn); await sleep(300);
  om = d.querySelector('.modal.owmodal');
  check(om && om.querySelector('#ow-to').value === '1' && /Take over “Erins list”/.test(om.textContent) && /Erin stays in the list/.test(om.textContent), 'takeover dialog: default me');
  click(w, om.querySelector('[data-m="ok"]')); await sleep(1500);
  check(w.eval(`listById(${ERIN}).role`) === 'owner', 'alice owns Erins list');
  w.close();

  // ================= Settings > Administration: lists owned by agents / disabled users
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    w = await boot({user: 'alice', mobile, hash: 'today'}); d = w.document;
    w.eval(`settingsModal('users')`);
    const rows = await until(() => d.querySelectorAll('#s-orph [data-olid]').length && d.querySelectorAll('#s-orph [data-olid]'));
    const devRow = [...rows].find(r => /Dev list 2/.test(r.textContent));
    if (!mobile) {
      check(/Lists owned by agents or disabled users/.test(d.querySelector('#s-orph-h')?.textContent || '') && rows.length === 2, `${lab}: the section with the two agent lists (${rows.length})`);
      check(devRow && /owned by the agent Claude/.test(devRow.textContent), `${lab}: the reason`);
      click(w, devRow.querySelector('[data-orph]')); await sleep(300);
      om = d.querySelector('.modal.owmodal');
      check(om && om.querySelector('#ow-to').value === '1', `${lab}: takeover defaults to me`);
      om.querySelector('#ow-to').value = String(ids.bob);
      click(w, om.querySelector('[data-m="ok"]')); await sleep(1500);
      check(![...d.querySelectorAll('#s-orph [data-olid]')].some(r => /Dev list 2/.test(r.textContent)), `${lab}: the row is gone`);
      const st = await call('GET', '/api/lists/' + DEV2 + '/owner', null, CKB);
      check(st.owner?.id === ids.bob, `${lab}: bob owns Dev list 2`);
    } else {
      check(rows.length === 1 && /Dev list/.test(rows[0].textContent), `${lab}: one list left`);
      click(w, rows[0].querySelector('[data-orph]')); await sleep(300);
      click(w, d.querySelector('.modal.owmodal [data-m="ok"]')); await sleep(1500);
      check(/None: every list is owned by an active person/.test(d.querySelector('#s-orph').textContent), `${lab}: none left`);
      check(w.eval(`listById(${DEV})?.role`) === 'owner', `${lab}: alice owns Dev list, in her sidebar`);
    }
    // #346 the users list: the agent as a row
    const agrow = d.querySelector(`#a-users [data-urow="${ag.id}"]`);
    check(agrow && agrow.querySelector('.abadge') && agrow.querySelector('[data-acc="agent-edit"]') && !agrow.querySelector('[data-acc="user-edit"]')
      && /Managed under Agents/.test(agrow.textContent), `${lab}: agent row with badge + "Managed under Agents"`);
    check(d.querySelector(`#a-users [data-urow="${ids.bob}"] [data-acc="user-edit"]`), `${lab}: people keep the edit button`);
    w.close();
  }

  // ================= the agent dialog: username + picture
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('users')`);
  const lnk = await until(() => d.querySelector(`#a-users [data-urow="${ag.id}"] [data-acc="agent-edit"]`));
  click(w, lnk);
  let am = await until(() => d.querySelector('#ag-avpick')?.closest('.modal'));
  check(am && !am.querySelector('#ag-user').disabled && am.querySelector('#ag-user').value === 'claude', 'agent dialog opened from the users list; username editable');
  check(am && am.querySelector('#ag-avpick [data-av="robot"].on') && am.querySelector('#ag-avpick [data-av="upload"]') && am.querySelector('#ag-avpick [data-av="none"]'),
    'picture: presets (robot marked), upload, none');
  am.querySelector('#ag-user').value = 'claude-dev';
  click(w, am.querySelector('#ag-avpick [data-av="coffee"]'));
  check(am.querySelector('#ag-avpick [data-av="coffee"]').classList.contains('on') && !am.querySelector('#ag-avpick [data-av="robot"]').classList.contains('on'), 'the pick is marked');
  click(w, am.querySelector('[data-m="ok"]')); await sleep(1200);
  let a1 = (await call('GET', '/api/admin/agents')).agents.find(x => x.id === ag.id);
  check(a1.username === 'claude-dev' && a1.avatar === '/static/avatars/coffee.svg', 'saved: username + picture ' + JSON.stringify([a1.username, a1.avatar]));
  check(!d.querySelector('#ag-avpick'), 'dialog closed');
  w.close();
  // German + a taken username shows the error in the dialog
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`);
  const ed = await until(() => d.querySelector(`#s-ags [data-agid="${ag.id}"] [data-ag="edit"]`));
  click(w, ed); am = await until(() => d.querySelector('#ag-avpick')?.closest('.modal'));
  check(/Profilbild/.test(am.textContent) && /API-Tokens gelten nach dem Umbenennen weiter/.test(am.textContent), 'German: the agent dialog');
  am.querySelector('#ag-user').value = 'bob';
  click(w, am.querySelector('[data-m="ok"]')); await sleep(800);
  check(!am.querySelector('#ag-err').hidden && /existiert/.test(am.querySelector('#ag-err').textContent), 'taken username: error in the dialog: ' + am.querySelector('#ag-err').textContent);
  click(w, am.querySelector('#ag-avpick [data-av="none"]'));
  am.querySelector('#ag-user').value = 'claude-dev';
  click(w, am.querySelector('[data-m="ok"]')); await sleep(1000);
  a1 = (await call('GET', '/api/admin/agents')).agents.find(x => x.id === ag.id);
  check(a1.avatar === '', 'none: no picture');
  w.eval(`settingsModal('users')`);
  await until(() => d.querySelector('#s-orph-h'));
  check(/Listen von Agenten oder deaktivierten Benutzern/.test(d.querySelector('#s-orph-h').textContent), 'German: the Administration section');
  check(/Verwaltet unter Agenten/.test((await until(() => d.querySelector(`#a-users [data-urow="${ag.id}"]`)))?.textContent || ''), 'German: agent row');
  w.close();

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
