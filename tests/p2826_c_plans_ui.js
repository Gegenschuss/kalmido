// 2.826.0 C UI test (#5510): the plans of an agent from its chat, pause all with undo, the starter pack's switches. Own container
// (start.sh), jsdom.
// kalmido-suite: fresh
// freelancer-matrix: agents (alice runs the instance without an organisation; her personal server agent)
// Invented people only.
// - the chat's "…" menu has "Plans"; it opens the same dialog as the card's "Plans" button: its plans with their titles are visible
// - "Pause all": every plan shows paused, the button turns into "Resume all"; the toast's Undo brings them back on
// - the agent's window "Private AI on the Kalmido server": a routine with its own plan (Morning briefing) has a switch On / Paused;
//   off -> "Paused" and the plan is still in the Plans dialog (paused, not deleted); on again -> "On"; a routine without a plan
//   (meeting notes, a rule) keeps its text
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, o) => require('./boot').until(fn, o);
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  check((await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 10})).status === 200, 'personal agents allowed');
  const ag = await call('POST', '/api/my/agents', {username: 'pki', display_name: 'Private AI', provider: 'kalmido-server', org_id: null});
  check(ag.id, 'a personal server agent ' + JSON.stringify(ag).slice(0, 200));
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  check((await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'})).status === 200, 'her project shared with it');
  check((await call('POST', `/api/agents/${ag.id}/server/starter`, {items: ['briefing', 'followup', 'meetings']})).status === 200, 'the starter pack');
  check((await call('POST', `/api/agents/${ag.id}/schedules`, {title: 'Water the plants', prompt: 'Remind me to water the plants.', freq: 'daily', time: '18:00'})).status === 201, 'an own plan');

  // the chat's menu: Plans
  let w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  w.eval(`chatOpen(${ag.id})`); await idle(w);
  const menuItem = async re => {
    click(w, await until(() => d.querySelector('.chath [data-act="chat-head-menu"]')));
    return until(() => [...d.querySelectorAll('[role=menuitem]')].find(x => re.test(x.textContent)));
  };
  const it = await menuItem(/^\s*Plans\s*$/);
  check(it, '#5510: the chat menu has "Plans"');
  click(w, it);
  const md = await until(() => d.querySelector('.schedmd'));
  const rows = () => [...(md?.querySelectorAll('.schedrow') || [])];
  check(md && await until(() => rows().length === 3) && /Water the plants/.test(md.textContent) && /Planned jobs: Private AI/.test(md.textContent),
    'the Plans dialog of this agent opens with its plans visible: ' + rows().map(r => r.querySelector('b')?.textContent).join(', '));
  check(rows().every(r => !r.classList.contains('off')), 'all on at first');

  // pause all + undo
  const allBtn = () => md.querySelector('[data-sm="all"]');
  check(allBtn() && /Pause all/.test(allBtn().textContent), 'the button "Pause all" on top');
  click(w, allBtn());
  check(await until(() => rows().length === 3 && rows().every(r => r.classList.contains('off'))), '#5510: Pause all: every plan paused');
  check(await until(() => /Resume all/.test(allBtn()?.textContent || '')), 'the button now says "Resume all"');
  const undo = await until(() => [...d.querySelectorAll('#toast button, .toast button')].find(b => /Undo/.test(b.textContent)));
  check(undo && /3 plans paused/.test(d.querySelector('#toast')?.textContent || undo.closest('div')?.textContent || ''), 'the toast "3 plans paused" with Undo');
  if (undo) click(w, undo);
  check(await until(() => rows().length === 3 && rows().every(r => !r.classList.contains('off'))), 'Undo: all on again');
  check(await until(() => /Pause all/.test(allBtn()?.textContent || '')), 'and the button says "Pause all" again');
  md.remove();

  // the starter pack's switches in the agent's window
  w.eval(`srv_editModal(agentById(${ag.id}))`);
  const sw = () => d.querySelector('[data-srv-sti="briefing"] input[data-srv-sw]');
  check(await until(() => sw() && sw().checked), '#5510: the Morning briefing has a switch, on');
  check(/On/.test(d.querySelector('[data-srv-sti="briefing"]').textContent), 'it reads "On"');
  check(d.querySelector('[data-srv-sti="meetings"]') && !d.querySelector('[data-srv-sti="meetings"] input[data-srv-sw]'), 'a routine without a plan (meeting notes) has no switch');
  sw().checked = false; sw().dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => d.querySelector('[data-srv-sti="briefing"]')?.dataset.state === 'paused' && sw() && !sw().checked && /Paused/.test(d.querySelector('[data-srv-sti="briefing"]').textContent)), 'switched off: "Paused"');
  const plans = await call('GET', `/api/agents/${ag.id}/schedules`);
  check((plans.data || []).length === 3 && (plans.data || []).some(s => !s.enabled), 'the plan is still there, paused (not deleted)');
  sw().checked = true; sw().dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => d.querySelector('[data-srv-sti="briefing"]')?.dataset.state === 'active' && sw()?.checked), 'switched on again: "On"');
  w.close();

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
