// 2.236.0 A UI tests (#2904-#2911, own container, start.sh). jsdom:
// - Settings > Agents: the row of a personal agent has the button "Work style and notifications" (cog); it opens the dialog
// - a field changed -> PATCH /api/agents/<id>/work-style with ONLY that key; after a reload the value is there; the quiet tick
// - the budget fields / the office hours / the quiet time show only when switched on; the weekday boxes save the list
// - the queue (GET .../queue) is shown when the server has it; an error = no list, the dialog still opens
// - the chat mode menu has the entry; the agent dialog of the admin has the button for a team agent, not for a foreign personal one
// - the same for a person without an organisation (freelancer-matrix: agents)
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
const setVal = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

// opens Settings > Agents > Set up, returns the row of agent id
async function row(w, d, id) {
  w.eval(`settingsModal('ai')`); await sleep(500);
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  return until(() => d.querySelector(`#s-myown [data-myag="${id}"]`));
}

async function scenario(tag, user, PA, ck) {
  const w = await boot({user, hash: 'agents'}), d = w.document, T = ` (${tag})`;
  await until(() => d.querySelector('.agcard'));
  w.eval(`window.__ao = api; api = function(m, u, b) { if (/work-style/.test(u) && m === 'PATCH') window.__sent.push([u, JSON.stringify(b)]); return window.__ao.apply(this, arguments); }; window.__sent = [];`);
  const r = await row(w, d, PA);
  const btn = r?.querySelector('[data-myag-act="work"]');
  check(btn && /Work style and notifications/.test(btn.getAttribute('aria-label') || ''), 'the row has the cog button' + T);
  click(w, btn);
  const md = await until(() => lastModal(d)?.classList.contains('awdlg') && lastModal(d));
  check(md, 'the dialog opens from the agent row' + T);
  if (!md) { w.close(); return; }
  check(md.querySelector('#aw-budget').hidden && md.querySelector('#aw-office').hidden && md.querySelector('#aw-quiet').hidden, 'budget / office hours / quiet time hidden by default' + T);
  check(md.querySelector('#aw-push').value === 'limits', 'a new agent shows "Only at limits"' + T);
  // one field -> one key
  setVal(w, md.querySelector('#aw-report_length'), 'long');
  check(await until(() => w.__sent.length === 1), 'one PATCH' + T);
  check(w.__sent[0]?.[1] === '{"report_length":"long"}' && w.__sent[0][0] === `/api/agents/${PA}/work-style`, 'only the changed key: ' + w.__sent[0]?.[1] + T);
  check(await until(() => d.querySelector('.awdlg .svtick')), 'the quiet tick' + T);
  setVal(w, md.querySelector('#aw-budget_period'), 'day');
  check(await until(() => !md.querySelector('#aw-budget').hidden), 'the budget fields appear' + T);
  setVal(w, md.querySelector('#aw-budget_limit'), '2500,5');
  setVal(w, md.querySelector('#aw-work_mode'), 'office');
  check(await until(() => !md.querySelector('#aw-office').hidden), 'the office hours appear' + T);
  const day3 = md.querySelector('[data-aw-day="3"]'); day3.checked = false; day3.dispatchEvent(new w.Event('change', {bubbles: true}));
  setVal(w, md.querySelector('#aw-quiet_mode'), 'on');
  const pr = md.querySelector('#aw-priority_rule'); pr.value = 'bugs first'; pr.dispatchEvent(new w.Event('change', {bubbles: true}));
  setVal(w, md.querySelector('#aw-max_parallel'), '2');
  setVal(w, md.querySelector('#aw-push'), 'never');
  const nx = md.querySelector('#aw-next_step'); nx.checked = false; nx.dispatchEvent(new w.Event('change', {bubbles: true}));
  const want = await until(async () => { const s = (await call('GET', `/api/agents/${PA}/work-style`, null, ck)).work_style; return s && s.next_step === false && s.push === 'never' && s.max_parallel === 2 && s.priority_rule === 'bugs first' && s.quiet_mode === 'on' && s.budget_limit === 2500.5 && !s.work_days.includes(3) && s.work_days.length === 4 && s.report_length === 'long' && s; }, 60);
  check(want, 'all values are on the server: ' + JSON.stringify(want) + T);
  check(w.__sent.every(x => Object.keys(JSON.parse(x[1])).length === 1), 'every PATCH carried exactly one key' + T);
  w.close();
  // a reload shows the values
  const w2 = await boot({user, hash: 'agents'}), d2 = w2.document;
  await until(() => d2.querySelector('.agcard'));
  const r2 = await row(w2, d2, PA); click(w2, r2.querySelector('[data-myag-act="work"]'));
  const m2 = await until(() => lastModal(d2)?.classList.contains('awdlg') && lastModal(d2));
  check(m2 && m2.querySelector('#aw-report_length').value === 'long' && m2.querySelector('#aw-push').value === 'never' && m2.querySelector('#aw-max_parallel').value === '2'
    && m2.querySelector('#aw-priority_rule').value === 'bugs first' && !m2.querySelector('#aw-next_step').checked && !m2.querySelector('#aw-budget').hidden && !m2.querySelector('#aw-quiet').hidden, 'the values are there after a reload' + T);
  check(m2 && !m2.querySelector('[data-aw-day="3"]').checked && m2.querySelector('[data-aw-day="1"]').checked, 'the weekday boxes follow' + T);
  // the budget line and the queue come from the server parts B / C: shown when present, nothing when not
  if (m2) {
    check(m2.querySelector('#aw-bstate').innerHTML === '' || /of/.test(m2.querySelector('#aw-bstate').textContent), 'no budget line without budget_state' + T);
    check(w2.eval(`aw_budgetLine({period: 'day', metric: 'tokens', used: 1234, limit: 5000, pct: 25, warn: false, paused: false})`).includes('25'), 'the budget line' + T);
    check(/Paused until/.test(w2.eval(`aw_budgetLine({period: 'week', metric: 'cost', used: 6, limit: 5, pct: 120, warn: true, paused: true, resets_at: '2030-01-07T00:00:00Z'})`)), 'the paused line' + T);
    const qh = w2.eval(`aw_queueHtml({items: [{task_id: 1, title: 'Fix <b>x</b>', list_name: 'L', state: 'active', position: 0}, {task_id: 2, title: 'Next', list_name: 'L', state: 'waiting', position: 1}]})`);
    check(/waits, place 1/.test(qh) && /active/.test(qh) && !/<b>x/.test(qh) && qh.includes('data-aw-task="2"'), 'the queue lists active and waiting, titles escaped' + T);
    check(w2.eval(`aw_queueHtml(null)`) === '', 'no queue = no list' + T);
  }
  [...d2.querySelectorAll('.modal')].forEach(m => m.remove());
  w2.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 3});
  const PA = (await call('POST', '/api/my/agents', {username: 'deskbot', display_name: 'Deskbot'})).id;
  const TA = (await call('POST', '/api/admin/agents', {username: 'teamy', display_name: 'Teamy', scopes: ['read']})).id;
  // a person without an organisation (freelancer-matrix: agents)
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.status < 300, 'a person without an organisation ' + fr.status);
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'}, FK);
  const FA = (await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Fridabot'}, FK)).id;
  check(FA, 'the freelancer has an own agent');

  await scenario('organisation', 'alice', PA, CK);
  await scenario('without organisation', 'frida', FA, FK);

  // the admin dialog and the chat menu
  const w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  await until(() => d.querySelector('.agcard'));
  const rt = id => w.eval(`agRtFields(${JSON.stringify({id, enabled: true, owner: null, runtime: {}})})`);
  check(/data-m="aw"/.test(rt(TA)), 'the admin dialog: a team agent has the button');
  check(/data-m="aw"/.test(w.eval(`agRtFields({id: 9, enabled: true, owner: {id: ${(await call('GET', '/api/state')).me.id}}, runtime: {}})`)), 'the admin dialog: my own personal agent has the button');
  check(!/data-m="aw"/.test(w.eval(`agRtFields({id: 9, enabled: true, owner: {id: 99999}, runtime: {}})`)), 'the admin dialog: no button for someone else\'s personal agent');
  check(!/data-m="aw"/.test(w.eval(`agRtFields(null)`)), 'a new agent (no id yet): no button');
  check(w.eval(`typeof awOpen`) === 'function', 'awOpen is there');
  w.close();
  console.log(`p2236_a_workstyle_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
