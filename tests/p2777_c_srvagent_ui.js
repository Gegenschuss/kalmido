// kalmido-suite: fresh
// 2.777.0 C UI test (#5378, own container, start.sh). jsdom: a new agent on the Kalmido server set up like a person does it.
// - an organisation's admin: "Belongs to: Team agent of <organisation>", ticks a project under "Projects for the agent", Create:
//   the project is shared with the agent before the starter pack, the agent's window opens WITHOUT a red error and lists the
//   routines as active
// - the same without a project: the window shows the calm hint (no red) with "Share project"; that button opens the project
//   choice, Share shares it, the routines turn active and the hint goes
// - a member of the organisation: the tab Agents shows the team agent with "No project shared" / "1 project", without "Plans";
//   its chat opens and shows Kalmido's fixed answer on how to share a project
// - a person without an organisation: her own agent with her own project, no red error, routines active (freelancer-matrix: agents)
// Real routes (no model call is needed: the starter pack and the fixed answer make none).
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const SKEY = 'AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=';  // a test server key (the provider key is sealed with it)
if (!process.env.P2777CU_NOSTART) {
  const extra = `${process.env.EXTRA || ''} -e KALMIDO_SECRET_KEY=${SKEY} -e KALMIDO_SRVAGENT_ANTHROPIC_URL=http://127.0.0.1:8091`;
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: extra.trim()}});
}
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const redShown = md => [...md.querySelectorAll('.calerr')].some(x => !x.hidden && x.textContent.trim());

async function newDialog(w, d) {
  w.eval(`settingsModal('ai')`);
  await until(() => d.querySelector('.smodal'));
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  const btn = await until(() => d.querySelector('.smodal [data-myag-act="srvnew"]'));
  if (!btn) return null;
  click(w, btn);
  return until(() => lastModal(d)?.querySelector('#srv-name') && lastModal(d));
}

// fills the dialog like a person; own = the "Belongs to" value; pj = the project names to tick -> the agent's window (or null)
async function create(w, d, T, un, own, pj) {
  const md = await newDialog(w, d);
  check(md, 'the dialog opens' + T);
  if (!md) return null;
  const sel = md.querySelector('#srv-own');
  if (own && sel) { sel.value = own; change(w, sel); }
  const boxes = await until(() => md.querySelectorAll('[data-srv-pj]').length && [...md.querySelectorAll('[data-srv-pj]')]);
  check(boxes && /Projects for the agent/.test(md.textContent), 'the dialog lists "Projects for the agent"' + T);
  for (const n of pj) {
    const b = (boxes || []).find(x => x.closest('label').textContent.includes(n));
    check(b, `the project "${n}" is offered` + T);
    if (b) b.checked = true;
  }
  md.querySelector('#srv-name').value = 'KI ' + un; md.querySelector('#srv-user').value = un;
  md.querySelector('#srv-key').value = 'sk-test-ui-0000abcd';
  click(w, md.querySelector('[data-m="srv-ok"]'));
  check(await until(() => !md.isConnected), 'Create closes the dialog' + T);
  const ed = await until(() => lastModal(d)?.querySelector('#srv-st .srvsti') && lastModal(d));
  check(ed && /on the Kalmido server/.test(ed.querySelector('h3').textContent), 'the agent\'s window opens after Create' + T);
  return ed;
}

(async () => {
  await until(async () => (await fetch(B + 'sw.js').catch(() => null))?.ok);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['comments', 'collab']}, CK);
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 10}, CK);
  const ORG = (await call('GET', '/api/state', null, CK)).me.workspaces[0].id;
  for (const [u, rk] of [['bob', 'admin'], ['carl', 'member']]) await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`, orgs: [{id: ORG, role: rk}]}, CK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  const BK = await login('bob'), CA = await login('carl'), FK = await login('frida');
  for (const k of [BK, CA, FK]) await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'}, k);
  const P1 = (await call('POST', '/api/lists', {name: 'Harbour project', org_id: ORG}, BK)).id;
  const P2 = (await call('POST', '/api/lists', {name: 'Lighthouse project', org_id: ORG}, BK)).id;
  const FL = (await call('POST', '/api/lists', {name: 'Frida garden'}, FK)).id;
  check(P1 && P2 && FL, 'setup: the projects');
  const agentOf = async (ck, un) => ((await call('GET', '/api/agents', null, ck)).agents || []).find(a => a.username === un);

  // ---------------------------------------------------------------- a team agent with a chosen project
  let w = await boot({user: 'bob', hash: 'inbox'}), d = w.document;
  let T = ' (team agent with a project)';
  let ed = await create(w, d, T, 'team-ki', `org:${ORG}`, ['Harbour project']);
  const a1 = await until(() => agentOf(BK, 'team-ki'));
  check(a1 && a1.owner_id === null && a1.org_id === ORG, 'a team agent of the organisation' + T);
  if (ed && a1) {
    check(!redShown(ed), 'no red error in the window' + T);
    check(!ed.querySelector('.srvwait'), 'no "no project" hint: the project is shared' + T);
    const act = await until(() => ['briefing', 'tidy', 'followup'].every(k => ed.querySelector(`[data-srv-sti="${k}"]`)?.dataset.state === 'active'));
    check(act && /Morning briefing at 07:30/.test(ed.textContent) && /On/.test(ed.querySelector('[data-srv-sti="briefing"]').textContent),
      'the routines are listed as active (On)' + T);
    check(ed.querySelector('[data-srv-sti="office"] [data-srv-add="office"]'), 'the item left out (office) offers "Add" in the window' + T);
    const pl = (await call('GET', `/api/agents/${a1.id}/schedules`, null, BK)).data || [];
    check(pl.length === 3 && pl.every(p => p.enabled), 'on the server: three active plans' + T);
    const lm = await call('GET', '/api/state', null, BK);
    check((lm.lists || []).find(l => l.id === P1)?.members?.some(m => m.user_id === a1.id), 'the chosen project is shared with the agent' + T);
    click(w, ed.querySelector('[data-m="close"]'));
  }
  w.close();

  // ---------------------------------------------------------------- without a project: a calm hint, "Share project"
  w = await boot({user: 'bob', hash: 'inbox'}); d = w.document;
  T = ' (team agent without a project)';
  ed = await create(w, d, T, 'team-two', `org:${ORG}`, []);
  const a2 = await until(() => agentOf(BK, 'team-two'));
  if (ed && a2) {
    check(!redShown(ed), 'no red error in the window' + T);
    const hint = await until(() => ed.querySelector('.srvwait'));
    check(hint && /No project is shared with KI team-two yet/.test(hint.textContent) && /start on their own/.test(hint.textContent) && hint.getAttribute('role') === 'note',
      'the calm hint: the routines wait and start on their own' + T);
    check(ed.querySelector('[data-srv-sti="briefing"]')?.dataset.state === 'waiting' && /Waits for a project/.test(ed.querySelector('[data-srv-sti="briefing"]').textContent),
      'the routines say "Waits for a project"' + T);
    const sb = ed.querySelector('[data-srv="share"]');
    check(sb && /Share project/.test(sb.textContent), 'the button "Share project"' + T);
    if (sb) {
      click(w, sb);
      const sm = await until(() => lastModal(d)?.querySelector('[data-m="srv-pjok"]') && lastModal(d));
      check(sm && /Share a project with KI team-two/.test(sm.textContent), 'the project choice opens' + T);
      if (sm) {
        const names = [...sm.querySelectorAll('[data-srv-pj]')].map(x => x.closest('label').textContent);
        check(names.some(n => n.includes('Lighthouse project')) && !names.some(n => n.includes('Harbour project')),
          'it offers the free project of the organisation, not the one that has an agent already' + T);
        click(w, sm.querySelector('[data-m="srv-pjok"]'));
        check(await until(() => !sm.querySelector('#srv-pjerr').hidden), 'Share without a choice: it asks for one' + T);
        sm.querySelector(`[data-srv-pj="${P2}"]`).checked = true;
        click(w, sm.querySelector('[data-m="srv-pjok"]'));
        check(await until(() => !sm.isConnected), 'Share closes the choice' + T);
        const back = await until(() => !ed.querySelector('.srvwait') && ed.querySelector('[data-srv-sti="briefing"]')?.dataset.state === 'active');
        check(back && ed.isConnected, 'back in the window: the hint is gone, the routines are active' + T);
        const pl = (await call('GET', `/api/agents/${a2.id}/schedules`, null, BK)).data || [];
        check(pl.length === 3 && pl.every(p => p.enabled && !p.share_wait), 'on the server: the waiting plans started' + T);
      }
    }
    click(w, ed.querySelector('[data-m="close"]'));
  }
  w.close();

  // ---------------------------------------------------------------- a member: the tab Agents and the chat without a project
  T = ' (member of the organisation)';
  const a3 = await call('POST', `/api/orgs/${ORG}/server-agents`, {username: 'team-three', display_name: 'Team Three'}, BK);
  check(a3.id, 'setup: a third team agent without a project' + T);
  const say = await call('POST', `/api/agents/${a3.id}/chat`, {body: 'What is due today?'}, CA);
  check(say.status === 201, 'carl writes to it without a project' + T);
  w = await boot({user: 'carl', hash: 'agents'}); d = w.document;
  // review F4: every request of the app that ends in 4xx / 5xx and every toast while carl uses the chat
  w.eval(`window.__p2777bad = []; window.__p2777toast = []; { const f0 = window.fetch; window.fetch = async (...x) => { const r = await f0(...x); if (r.status >= 400) window.__p2777bad.push(r.status + ' ' + String(x[0]?.url || x[0])); return r; }; }
    { const t0 = toast; toast = (...x) => { window.__p2777toast.push(String(x[0] ?? '')); return t0(...x); }; }`);
  const c3 = await until(() => d.querySelector(`.agcard[data-k="ag${a3.id}"]`));
  check(c3 && /No project shared/.test(c3.textContent) && /Team Three/.test(c3.textContent), 'its card: "No project shared"' + T);
  const c1 = a1 && d.querySelector(`.agcard[data-k="ag${a1.id}"]`);
  check(c1 && /1 project/.test(c1.textContent), 'the first team agent: "1 project"' + T);
  check(c3 && !c3.querySelector('[data-act="sched-open"]') && c3.querySelector('[data-act="chat-open"]'), 'no "Plans" (no data), but the chat' + T);
  if (c3) {
    click(w, c3.querySelector('[data-act="chat-open"]'));
    const ans = await until(() => [...d.querySelectorAll('#achat, .achat, .chatview, main')].some(x => /do not see any project of yours/.test(x.textContent)));
    check(ans, 'the chat opens and shows the answer: it sees nothing, how to share a project' + T);
    // 2.777.0 (#5378): review F4 - text only, no side calls: writing works, the answer shows, no red error
    const box = await until(() => d.querySelector(`.chmsgs[data-agid="${a3.id}"]`)?.closest('#achat, .chview'));
    check(box && box.querySelector('#chat-in') && !box.querySelector('[data-act="chat-attach"]') && !box.querySelector('.mreply') && !box.querySelector('[data-act="chat-react"]'),
      'review F4: only the text box - no attach, no reply, no reactions' + T);
    const mb = box?.querySelector('.cmsg [data-act="chat-msg-menu"]');
    if (mb) {
      click(w, mb);
      const items = await until(() => { const l = [...d.querySelectorAll('[role="menuitem"]')].map(x => x.textContent.trim()); return l.length && l; });
      check(items && items.some(x => /^Copy/.test(x)) && !items.some(x => /Reply|Pin|Edit|Delete|React|Save as task/.test(x)),
        'review F4: the message menu only copies ' + JSON.stringify(items) + T);
      d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
    }
    const n0 = box ? box.querySelectorAll('.cmsg').length : 0;
    const ci = box?.querySelector('#chat-in');
    if (ci) {
      ci.focus(); ci.value = 'Can you help me?'; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
      click(w, box.querySelector('[data-act="chat-send"]'));
      const two = await until(() => { const ms = [...d.querySelectorAll(`.chmsgs[data-agid="${a3.id}"] .cmsg`)]; return ms.length >= n0 + 2 && ms; });
      check(two && /Can you help me\?/.test(two[two.length - 2].textContent) && /do not see any project of yours/.test(two[two.length - 1].textContent),
        'review F4: carl writes and sees his text and the fixed answer right after it' + T);
      check(await until(() => { const c2 = d.querySelector('#chat-in'); return !!c2 && c2.value === ''; }), 'the box is empty again (the input after sending, also when it was drawn anew)' + T);
    }
    const bad = w.eval('window.__p2777bad || []').filter(x => x.includes(`/api/agents/${a3.id}`) || x.includes('/api/chat')), toasts = w.eval('window.__p2777toast || []');
    check(!bad.length, 'review F4: no request of the chat ends in an error ' + JSON.stringify(bad) + T);
    check(!toasts.some(t => /error|share a project with the agent first|not found/i.test(t)), 'review F4: no error toast ' + JSON.stringify(toasts) + T);
  }
  w.close();

  // ---------------------------------------------------------------- a person without an organisation
  w = await boot({user: 'frida', hash: 'inbox'}); d = w.document;
  T = ' (without organisation)';
  ed = await create(w, d, T, 'frida-ki', '', ['Frida garden']);
  const a4 = await until(() => agentOf(FK, 'frida-ki'));
  check(a4 && a4.owner_id, 'her personal agent' + T);
  if (ed && a4) {
    check(!redShown(ed) && !ed.querySelector('.srvwait'), 'no red error, no hint' + T);
    check(await until(() => ed.querySelector('[data-srv-sti="briefing"]')?.dataset.state === 'active'), 'the routines are active' + T);
    const st = await call('GET', '/api/state', null, FK);
    check((st.lists || []).find(l => l.id === FL)?.members?.some(m => m.user_id === a4.id), 'her project is shared with her agent' + T);
  }
  w.close();

  console.log(`p2777_c_srvagent_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
