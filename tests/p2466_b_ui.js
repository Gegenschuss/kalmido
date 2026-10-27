// 2.46.6 UI tests of part B (#1680 #1708 #1709 #1716, own container, start.sh). jsdom:
// - #1680: the switch "Members may see and use the agent" of a list (and a folder) with a personal agent says that only its
//   owner can address it; a list with a team agent says nothing of the kind
// - #1708: the agent's card in the Agents view has "Lists" (name, folder, who may address it, listens in); a tap opens the
//   list's settings; a personal agent: "Only you use it."; the row of a personal agent shows its workspace and changes it
// - #1709: creating a personal agent offers "Set it up on a computer now?" (Set up opens the setup, the token only on
//   request); the row says "Set up" until a computer connected
// - #1716: "Which agent when?" in the dialogs that create an agent
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 3});
  const st = await call('GET', '/api/state'), ORG = st.me.workspaces[0].id;
  const CAROL = (await call('POST', '/api/users', {orgs: [ORG], username: 'carol', display_name: 'Carol', password: 'password123', email: 'carol@example.com'})).id;
  const PA = (await call('POST', '/api/my/agents', {username: 'deskbot', display_name: 'Deskbot'})).id;
  const TA = (await call('POST', '/api/admin/agents', {username: 'teamy', display_name: 'Teamy', scopes: ['read', 'tasks:write', 'comments']})).id;
  const L1 = (await call('POST', '/api/lists', {name: 'Shoot plan', org_id: ORG, folder: 'Projects'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Office', org_id: ORG})).id;
  for (const [l, u] of [[L1, CAROL], [L1, PA], [L2, CAROL]]) {
    let r = await call('PUT', `/api/lists/${l}/members`, {user_id: u, role: 'edit'});
    if (r.status === 409) r = await call('PUT', `/api/lists/${l}/members`, {user_id: u, role: 'edit', bridge_ok: true});
    check(r.status < 300, `share list ${l} with ${u} (${r.status})`);
  }
  let r = await call('PUT', `/api/lists/${L2}/agent`, {agent_id: TA});
  if (r.status === 409) r = await call('PUT', `/api/lists/${L2}/agent`, {agent_id: TA, bridge_ok: true});
  await call('PATCH', `/api/lists/${L2}`, {agent_members: true});

  let w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  await until(() => d.querySelector('.agcard'));

  // ================= #1680
  const h1 = w.eval(`tidyRowHtml(listById(${L1}))`), h2 = w.eval(`tidyRowHtml(listById(${L2}))`);
  check(/Deskbot is your personal agent: only you can address it/.test(h1), '#1680: the switch of a list with my personal agent says only I can address it');
  check(!/personal agent/.test(h2), '#1680: no such hint for a team agent');
  check(w.eval(`av_folderPersonal('Projects').length`) === 1 && w.eval(`av_folderPersonal('Nothing').length`) === 0, '#1680: the folder defaults see the personal agent in the folder');
  check(/only Carol can address it/.test(w.eval(`av_personalHint([{name: 'X', mine: false, owner: 'Carol'}])`)), '#1680: someone else\'s personal agent names its owner');

  // ================= #1708: the card's lists
  const card = id => d.querySelector(`.agcard[data-k="ag${id}"]`);
  check(await until(() => card(PA)?.querySelector('details.aglists')), '#1708: the personal agent\'s card has "Lists"');
  const pl = card(PA)?.querySelector('details.aglists');
  check(/Only you use it/.test(pl?.textContent || '') && /Shoot plan/.test(pl?.textContent || '') && /Projects/.test(pl?.textContent || ''), '#1708: "Only you use it." + the list with its folder');
  check(/only you/.test(pl?.querySelector(`[data-avlist="${L1}"]`)?.textContent || ''), '#1708: who may address it in the list');
  const tl = card(TA)?.querySelector('details.aglists');
  check(tl && /Others can use it in: Office/.test(tl.textContent) && /all members \(2 people\)/.test(tl.textContent), '#1708: the team agent: open to the members of Office (2 people)');
  check(/listens in|only via @/.test(tl?.textContent || ''), '#1708: listens in / only via @');
  click(w, pl.querySelector(`[data-avlist="${L1}"]`));
  check(await until(() => /Shoot plan/.test(lastModal(d)?.querySelector('#l-name')?.value || lastModal(d)?.textContent || '')), '#1708: a tap opens the list\'s settings');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());

  // ================= #1708: the workspace in the row + #1709: the setup offer
  w.eval(`settingsModal('ai')`); await sleep(500);
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  const prow = () => d.querySelector(`#s-myown [data-myag="${PA}"]`);
  await until(() => prow());
  const wb = prow()?.querySelector('[data-myag-act="ws"]');
  check(wb && /Example Org/.test(wb.textContent), '#1708: the row shows the workspace');
  click(w, wb); await until(() => d.querySelector('#pop [role="menuitem"]'));
  const priv = [...d.querySelectorAll('#pop [role="menuitem"]')].find(x => /Private/.test(x.textContent));
  check(priv, '#1708: the menu offers Private'); if (priv) click(w, priv);
  check(await until(async () => (await call('GET', '/api/my/agents')).agents.find(a => a.id === PA)?.org_id === null), '#1708: the agent is private now');
  check(await until(() => /Private/.test(prow()?.querySelector('[data-myag-act="ws"]')?.textContent || '')), '#1708: the row follows');
  check(prow()?.querySelector('[data-myag-act="setup"].avsetup') && /Set up/.test(prow().querySelector('[data-myag-act="setup"]').textContent), '#1709: "Set up" with its text while no computer connected');
  // #1716: "Which agent when?" where a personal agent is created
  check(d.querySelector('.smodal details.avwhich'), '#1716: "Which agent when?" in Set up');
  d.querySelector('#myag-user').value = 'deskbot2'; d.querySelector('#myag-name').value = 'Deskbot 2';
  click(w, d.querySelector('[data-myag-act="new"]'));
  check(await until(() => d.querySelector('.modal:not(.smodal) [data-m="av-setup"]')), '#1709: "Set it up on a computer now?" after creating');
  let md = lastModal(d);
  check(/Set it up on a computer now/.test(md.textContent) && !md.querySelector('#av-tokv'), '#1709: the token is not shown unasked');
  click(w, md.querySelector('[data-m="av-tok"]'));
  check(/^abk_/.test(md.querySelector('#av-tokv')?.value || ''), '#1709: the token on request');
  click(w, md.querySelector('[data-m="av-setup"]'));
  check(await until(() => lastModal(d)?.querySelector('#ains-dir')), '#1709: Set up opens the setup dialog');
  check(!md.isConnected, '#1709: the offer is closed (the token is gone with it)');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());

  // #1716: the admin's dialog for a new agent
  w.eval(`agModal(null, null, {kind: 'team'})`); await sleep(300);
  check(lastModal(d)?.querySelector('details.avwhich'), '#1716: "Which agent when?" in the new agent dialog');
  w.close();
  console.log(`p2466_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
