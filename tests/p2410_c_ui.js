// 2.41.0 UI tests of agent C, own container (start.sh). jsdom:
// - #1428 folders show whether they are shared, with the symbols of a list: a private folder none, a folder shared with people
//   (people symbol), with an agent (robot), with both; a subfolder inherits its top folder's; only lists inside shared = the
//   weaker sign; shown folded too; the folder view says it; "New list" in a shared folder names the people and the agent;
//   moving a list into a shared folder says "Now shared with …" with Undo
// - #1420 one Share dialog for a folder like the list's: ✕ in the head, People with the owner first and "Add", the role
//   help, Agents (adding one; the first is the default of the lists), Public link, Owner with "Transfer ownership of all
//   lists…", greyed parts with the reason, "Folder settings…" at the bottom left; the folder menu has no extra group entry
// - #1423 folder settings like the list's: switches with a third state "Not set", saved at once with "Saved · Undo" (no Save
//   button), "Not set" puts a switch back; tidying only with an agent
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab';
const fhead = (d, f) => d.querySelector(`#side .fhead[data-folder="${f}"]`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const uid = {};
  for (const u of ['bob', 'carol']) uid[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: u + '@example.com'})).id;
  const AG = (await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'})).id;
  const mk = async (name, folder) => (await call('POST', '/api/lists', {name, folder})).id;
  const P1 = await mk('Diary', 'Private');
  await mk('Plans', 'Team');
  await mk('Builds', 'Bots');
  await mk('Mixed', 'Both');
  await mk('Deep', 'Both/Sub');
  const L1 = await mk('Loose one', 'Loose');
  await call('PUT', '/api/folders/people', {folder: 'Team', user_id: uid.bob, role: 'edit'});
  await call('PUT', '/api/folders/agents', {folder: 'Bots', agent_id: AG});
  await call('PUT', '/api/folders/people', {folder: 'Both', user_id: uid.bob, role: 'edit'});
  await call('PUT', '/api/folders/agents', {folder: 'Both', agent_id: AG});
  await call('PUT', `/api/lists/${L1}/members`, {user_id: uid.carol, role: 'edit'});

  // ================= #1428 the folder rows
  let w = await boot({user: 'alice'}), d = w.document;
  await until(() => fhead(d, 'Loose'));
  const sym = f => { const h = fhead(d, f), s = h?.querySelector('.fshr'); return s ? {p: !!s.querySelector('.i-users, [data-i="users"], svg') && !/^\s*$/.test(s.innerHTML), bot: !!s.querySelector('.lbot'), weak: s.classList.contains('fshweak'), tip: s.getAttribute('title') || ''} : null; };
  check(fhead(d, 'Private') && !sym('Private'), '#1428: a private folder has no symbol');
  const team = sym('Team');
  // 2.152.2 (#2624): project instead of list
  check(team && !team.bot && !team.weak && /New projects here are shared with 1 person/.test(team.tip), '#1428: shared with a person: people symbol + tooltip ' + JSON.stringify(team));
  const bots = sym('Bots');
  check(bots && bots.bot && !bots.weak && /agent Claude/.test(bots.tip), '#1428: with an agent: the robot ' + JSON.stringify(bots));
  const both = sym('Both');
  check(both && both.bot && /1 person and agent Claude/.test(both.tip), '#1428: with both ' + JSON.stringify(both));
  const sub = sym('Both/Sub');
  check(sub && sub.bot && /1 person and agent Claude/.test(sub.tip), '#1428: the subfolder inherits its top folder ' + JSON.stringify(sub));
  const loose = sym('Loose');
  // 2.152.2 (#2624): project instead of list
  check(loose && loose.weak && /1 project in here is shared; new projects stay private/.test(loose.tip), '#1428: only a list inside shared: the weaker sign ' + JSON.stringify(loose));
  w.eval(`foldSet('Team', true); renderSide()`);
  check(fhead(d, 'Team')?.classList.contains('closed') && sym('Team'), '#1428: shown folded too');
  // the folder view (phone / app: the same head)
  w.location.hash = '#folder/' + encodeURIComponent('Both'); w.eval(`(typeof route === 'function') && route()`);
  await until(() => d.querySelector('.fhdsh'), 20);
  check(/1 person and agent Claude/.test(d.querySelector('.fhdsh')?.textContent || ''), '#1428: the folder view says it ' + (d.querySelector('.fhdsh')?.textContent || 'none'));
  // "New list" in a shared folder names the agent
  w.eval(`listModal(null, 'Bots')`);
  let md = await until(() => [...d.querySelectorAll('.modal')].pop());
  check(/It will be shared with agent Claude/.test(md?.querySelector('#l-fhint')?.textContent || ''), '#1428: the new-list hint names the agent ' + (md?.querySelector('#l-fhint')?.textContent || ''));
  d.querySelectorAll('.modal').forEach(m => m.remove());
  // moving a list into a shared folder
  await w.eval(`setListFolder(${P1}, 'Team')`);
  const tt = await until(() => { const t = d.querySelector('#toast'); return t && !t.classList.contains('hidden') && /Now shared with 1 person/.test(t.textContent) ? t : null; });
  check(tt && /Undo/.test(tt.textContent), '#1428: "Now shared with 1 person" + Undo ' + (d.querySelector('#toast')?.textContent || ''));
  if (tt) click(w, tt.querySelector('button'));
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === P1)?.folder === 'Private'), '#1428: Undo puts the list back');

  // ================= #1420 the folder's Share dialog
  const fItems = await (async () => { w.eval(`folderMenu(document.querySelector('#side .fhead[data-folder="Team"]'), 'Team')`); await sleep(200); return [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent); })();
  check(fItems.some(x => /Share folder/.test(x)) && !fItems.some(x => /Share with a group/.test(x)), '#1420: one share entry in the folder menu ' + fItems.join('|'));
  d.querySelector('#pop')?.remove();
  w.eval(`LS.set('agSafeSeen', true); folderShareModal('Team')`);
  md = await until(() => d.querySelector('.modal.fshmodal #fsh-members [data-m="add"]') && d.querySelector('.modal.fshmodal #fsh-members .mrow[data-uid]')?.closest('.modal'));
  check(md && md.querySelector('.lhdr [data-m="close"]'), '#1420: a ✕ in the head');
  check(md && /Alice/.test(md.querySelector('#fsh-members .fshowner')?.textContent || '') && /Owner/.test(md.querySelector('#fsh-members .fshowner')?.textContent || ''), '#1420: the owner row first');
  check(md && /Bob/.test(md.querySelector('#fsh-members .mrow[data-uid]')?.textContent || ''), '#1420: the person of the folder');
  check(md && /Add/.test(md.querySelector('#fsh-members [data-m="add"]')?.textContent || '') && md.querySelector('.rolehelp'), '#1420: "Add" and the role help');
  check(md && md.querySelector('#fsh-sec-ag') && md.querySelector('#fp-sec-ntf') && md.querySelector('#fsh-sec-own'), '#1420: Agents, Notifications, Owner parts');
  const parts = md ? [...md.querySelectorAll('h4')].map(h => h.textContent) : [];
  check(parts.indexOf('People') < parts.indexOf('Agents') && parts.indexOf('Agents') < parts.indexOf('Notifications for members') && parts.indexOf('Notifications for members') < parts.indexOf('Owner'), '#1420: the list dialog\'s order ' + parts.join('|'));
  check(md && md.querySelectorAll('.fshgrey').length >= 1 && /folder settings/.test(md.querySelector('.fshgrey')?.textContent || ''), '#1420: what a folder does elsewhere: greyed with the reason');
  // 2.152.2 (#2624): project instead of list
  check(md && /Transfer ownership of all projects/.test(md.querySelector('#fsh-own')?.textContent || ''), '#1420: "Transfer ownership of all lists…"');
  const foot = md?.querySelector('.foot');
  check(foot && foot.firstElementChild?.dataset.m === 'fsh-props' && /Folder settings/.test(foot.firstElementChild.textContent), '#1420: "Folder settings…" at the bottom left');
  // add the agent from the dialog
  const sel = await until(() => md.querySelector('#fsh-agadd'));
  if (sel) { sel.value = String(AG); click(w, md.querySelector('[data-m="fsh-agadd"]')); }
  check(await until(async () => (await call('GET', '/api/folders/agents?folder=Team')).agents?.[0]?.agent_id === AG), '#1420: the agent added from the dialog');
  // 2.152.2 (#2624): project instead of list
  check(await until(() => /default for the projects/.test(md.querySelector('#fsh-agents')?.textContent || '')), '#1420: it is the default of the lists');
  click(w, md.querySelector('.lhdr [data-m="close"]'));
  await sleep(300);

  // ================= #1423 folder settings
  w.eval(`folderPropsModal('Bots')`);
  md = await until(() => d.querySelector('.modal.fsmodal #fs-am')?.closest('.modal'));
  const am = md?.querySelector('#fs-am');
  check(am && am.type === 'checkbox' && am.getAttribute('role') === 'switch' && am.closest('.fsw').classList.contains('unset'), '#1423: a switch, not set at first');
  check(md && !md.querySelector('[data-m="ok"]') && md.querySelector('.lhdr [data-m="close"]'), '#1423: no Save button, a ✕ in the head');
  check(md && /Members may see and use the agent/.test(md.textContent) && /Agent may tidy up entries/.test(md.textContent) && /Agent follows up/.test(md.textContent), '#1423: the list\'s texts');
  check(md && !md.querySelector('#fs-td').disabled && /Claude/.test(md.querySelector('#fs-ags')?.textContent || ''), '#1423: tidying offered with an agent; the agent named');
  if (am) { am.checked = true; am.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => (await call('GET', '/api/folders/props?folder=Bots')).props?.agent_members === true), '#1423: saved at once');
  check(await until(() => md.querySelector('.ssaved.on [data-m="fs-undo"]')) && !am.closest('.fsw').classList.contains('unset'), '#1423: "Saved · Undo", the switch is set now');
  click(w, md.querySelector('[data-m="fs-undo"]'));
  check(await until(async () => !('agent_members' in ((await call('GET', '/api/folders/props?folder=Bots')).props || {}))), '#1423: Undo takes it back (not set again)');
  if (am) { am.checked = false; am.dispatchEvent(new w.Event('change', {bubbles: true})); }
  await until(async () => (await call('GET', '/api/folders/props?folder=Bots')).props?.agent_members === false);
  const clr = await until(() => { const b = md.querySelector('[data-fsclr="agent_members"]'); return b && !b.hidden ? b : null; });
  if (clr) click(w, clr);
  check(await until(async () => !('agent_members' in ((await call('GET', '/api/folders/props?folder=Bots')).props || {}))) && await until(() => am.closest('.fsw').classList.contains('unset')), '#1423: "Not set" puts it back');
  click(w, md.querySelector('.lhdr [data-m="close"]'));
  await sleep(200);
  w.eval(`folderPropsModal('Private')`);
  md = await until(() => d.querySelector('.modal.fsmodal #fs-td')?.closest('.modal'));
  check(md && md.querySelector('#fs-td').disabled && /Add an agent in the Share dialog first/.test(md.querySelector('#fs-tdhint')?.textContent || ''), '#1423: no agent: tidying greyed with the reason');
  check(md && !/Repository …/.test(md.textContent), '#1423: "Repository…" without a space');

  console.log(`p2410_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
