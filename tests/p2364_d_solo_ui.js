// kalmido-suite: fresh
// 2.364.0 D (#3036) team entries only with collaborators: one mark "has collaborators" (hasPeers: a project shared with
// another person or an agent, or an organisation of mine with someone else - /api/state org_peers). Without it: no
// "My tasks" in the sidebar (unless something is assigned), no "Assign to me" / "Waiting on someone" when sorting the
// basket, no "Waiting on someone…" in the task's "…". "Lock" is in "…" always (the task panel's bar shows only a set lock,
// to unlock); "Time" sits there instead when time tracking is on; "Lock note" is a "…" entry. A task already waiting
// keeps "No longer waiting". Sharing a project with a second person brings the entries back. Own container, jsdom.
// freelancer-matrix: tasks - frida has no organisation (alone, then sharing one project with bob).
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 6000) => { for (let t = 0; t < ms; t += 100) { const v = await f(); if (v) return v; await sleep(100); } return f(); };
const FEAT = 'cal,comments,collab,time';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CB = await login('bob'), CF = await login('frida');
  for (const ck of [CA, CB, CF]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  const sf = await call(CF, 'GET', '/api/state');
  check(fu.http < 300 && (sf.me?.workspaces || []).length === 0, 'P4: frida is in no organisation');
  // the server's half of the mark
  check(sf.org_peers === false, 'frida: org_peers false ' + sf.org_peers);
  check((await call(CB, 'GET', '/api/state')).org_peers === true, 'bob (Alpha with alice): org_peers true');

  const L = (await call(CF, 'POST', '/api/lists', {name: 'Home', time_tracking: true})).id;
  const T = (await call(CF, 'POST', '/api/tasks', {title: 'Paint the fence', list_id: L, content: 'white, two coats'})).id;
  const TW = (await call(CF, 'POST', '/api/tasks', {title: 'Wait for the plumber', list_id: L})).id;
  await call(CF, 'PUT', `/api/tasks/${TW}/waiting`, {note: 'Plumber'});
  const TL = (await call(CF, 'POST', '/api/tasks', {title: 'Tax papers', list_id: L})).id;
  await call(CF, 'PATCH', `/api/tasks/${TL}`, {locked: 1});
  await call(CF, 'POST', '/api/tasks', {title: 'Loose idea'});  // the basket

  const labels = async (w, d, id) => {
    w.eval(`closePop(); taskMenu(document.querySelector('#top h1') || document.body, ${id})`);
    await until(() => d.querySelector('#pop [role="menuitem"]'));
    return [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  };

  // (1) frida alone
  let w = await boot({user: 'frida', hash: 'l/' + L}), d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T}"]`));
  check(w.eval('hasPeers()') === false, 'alone: hasPeers() false');
  check(!d.querySelector('#side [data-go="assigned"]'), 'alone: no "My tasks" in the sidebar');
  let its = await labels(w, d, T);
  check(its.length > 3, 'the task menu opened ' + its.length);
  check(!its.includes('Waiting on someone…') && !its.includes('Assign…') && !its.includes('Ask for approval…'), 'alone: no Waiting on someone… / Assign… / Ask for approval… ' + JSON.stringify(its));
  check(its.includes('Lock'), '"Lock" is in "…" ' + JSON.stringify(its));
  if (w.eval('!!globalThis.crypto?.subtle')) check(its.includes('Lock note'), '"Lock note" is in "…"');  // jsdom may lack WebCrypto (p248_c_lock_ui checks it in Firefox)
  check((await labels(w, d, TW)).includes('No longer waiting'), 'a waiting task keeps "No longer waiting"');
  w.eval('closePop()');
  w.eval('kbSortStart()'); await until(() => d.querySelector('.kbsort .kbact'));
  let acts = [...d.querySelectorAll('.kbsort .kbact')].map(b => b.dataset.kbs);
  check(acts.length && !acts.includes('me') && !acts.includes('wait'), 'alone: sorting the basket without "Assign to me" / "Waiting on someone" ' + acts);
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  // the task panel: no lock button, "Time" instead (time tracking on); a locked task shows its lock to unlock
  w.eval(`openDetail(${T})`); await until(() => d.querySelector('#detail .dtop'));
  check(!d.querySelector('#detail .dtop [data-act="tlk-toggle"]'), 'the panel: no Lock button in the bar');
  check(!d.querySelector('#detail [data-ln="lock"]'), 'the panel: no "Lock note" link under the note');
  const tb = d.querySelector('#detail .dtop .dtime[data-act="timer-toggle"]');
  check(tb && /Time/.test(tb.textContent), 'the panel: "Time" in the bar');
  w.eval(`openDetail(${TL})`); await until(() => d.querySelector('#detail .dtop .tlkb.on'));
  check(d.querySelector('#detail .dtop .tlkb.on[data-act="tlk-toggle"]'), 'a locked task: the lock in the bar (to unlock)');
  w.close();

  // (2) frida shares Home with her personal agent: the entries come back
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  const pa = await call(CF, 'POST', '/api/my/agents', {username: 'fridabot', display_name: 'Fridabot', provider: ''});
  const sh = await call(CF, 'PUT', `/api/lists/${L}/members`, {user_id: pa.id, role: 'edit'});
  check(pa.id && sh.http < 300, 'frida shares Home with her agent ' + pa.http + ' ' + sh.http);
  w = await boot({user: 'frida', hash: 'l/' + L}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T}"]`));
  check(w.eval('hasPeers()') === true, 'shared: hasPeers() true');
  check(d.querySelector('#side [data-go="assigned"]'), 'shared: "My tasks" in the sidebar');
  its = await labels(w, d, T);
  check(its.includes('Waiting on someone…') && its.includes('Assign…') && its.includes('Lock'), 'shared: Waiting on someone…, Assign… (and Lock) ' + JSON.stringify(its));
  w.eval('closePop()');
  w.eval('kbSortStart()'); await until(() => d.querySelector('.kbsort .kbact'));
  acts = [...d.querySelectorAll('.kbsort .kbact')].map(b => b.dataset.kbs);
  check(acts.includes('me') && acts.includes('wait'), 'shared: sorting the basket with "Assign to me" / "Waiting on someone" ' + acts);
  w.close();

  // (3) bob: no project shared by him, but an organisation with alice
  w = await boot({user: 'bob', hash: 'today'}); d = w.document;
  await until(() => w.eval('!!S.me'));
  check(w.eval('S.orgPeers') === true && w.eval('hasPeers()') === true, 'bob (organisation with someone else): hasPeers() true');
  w.close();

  console.log(`p2364_d_solo_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
