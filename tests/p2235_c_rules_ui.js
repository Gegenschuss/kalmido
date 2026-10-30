// kalmido-suite: fresh
// 2.235.0 C UI test (#2903, own container, start.sh). jsdom:
// - the agent dialog (cog in Settings > Agents) shows the section "Standing rules": the rule the agent saved, its date and
//   source ("from the chat", a link to the message), an empty agent the hint how rules come about
// - the switch pauses / resumes (PATCH state), the pen rewords inline (PATCH text), the bin asks first and deletes, a rule
//   added by hand (POST); every step waits for the server state / the toast, never a fixed time
// - the source link jumps to the message (msgJump art a)
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
const call = async (method, url, body, ck = CK, auth) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(auth ? {Authorization: 'Bearer ' + auth} : {Cookie: ck})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const toasted = (d, t) => [...d.querySelectorAll('.toast, #toast, [role="status"]')].some(x => (x.textContent || '').includes(t));

async function openDlg(w, d, id) {
  w.eval(`settingsModal('ai')`);
  await until(() => d.querySelector('.smodal'));
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  const r = await until(() => d.querySelector(`#s-myown [data-myag="${id}"]`));
  click(w, r.querySelector('[data-myag-act="work"]'));
  return until(() => lastModal(d)?.classList.contains('awdlg') && lastModal(d));
}

async function scenario(tag, user, ck) {
  const T = ` (${tag})`;
  const ag = await call('POST', '/api/my/agents', {username: 'rb' + user, display_name: 'Rulebot ' + user, scopes: ['read']}, ck);
  const empty = await call('POST', '/api/my/agents', {username: 'eb' + user, display_name: 'Empty ' + user, scopes: ['read']}, ck);
  check(ag.id && ag.token && empty.id, 'two personal agents' + T);
  const m = await call('POST', `/api/agents/${ag.id}/chat`, {body: 'From now on always write invoices in English'}, ck);
  const r = await call('POST', '/api/v1/agent/rules', {text: 'Invoices always in English', source: {kind: 'chat', id: m.id}}, null, ag.token);
  check(r.status === 201, 'the agent saved a rule ' + r.status + T);
  const rid = r.rule?.id;
  const rules = async () => (await call('GET', `/api/agents/${ag.id}/rules`, null, ck)).rules || [];

  const w = await boot({user, hash: 'agents'}), d = w.document;
  await until(() => d.querySelector('.agcard'));
  const md = await openDlg(w, d, ag.id);
  check(md, 'the dialog opens' + T);
  if (!md) { w.close(); return; }
  const row = await until(() => md.querySelector(`#aw-rules [data-awr-id="${rid}"]`));
  check(row && /Invoices always in English/.test(row.textContent) && /from the chat/.test(row.textContent), 'the rule with its source' + T);
  check(md.querySelector('#awr-h')?.textContent === 'Standing rules', 'the section heading' + T);
  // pause
  const sw = row.querySelector(`[data-awr-on="${rid}"]`);
  sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await rules()).find(x => x.id === rid)?.state === 'paused'), 'the switch pauses it on the server' + T);
  check(await until(() => md.querySelector(`[data-awr-id="${rid}"].paused`)), 'the row shows paused' + T);
  check(await until(() => toasted(d, 'Rule paused')), 'the toast "Rule paused"' + T);
  // reword inline
  click(w, md.querySelector(`[data-awr-edit="${rid}"]`));
  const ta = await until(() => md.querySelector('.awredit'));
  check(ta && ta.value === 'Invoices always in English', 'the inline editor holds the text' + T);
  if (ta) { ta.value = 'Invoices in English, prices in EUR'; click(w, md.querySelector(`[data-awr-save="${rid}"]`)); }
  check(await until(async () => (await rules()).find(x => x.id === rid)?.text === 'Invoices in English, prices in EUR'), 'the new text on the server' + T);
  check(await until(() => /prices in EUR/.test(md.querySelector(`[data-awr-id="${rid}"]`)?.textContent || '')), 'the row shows the new text' + T);
  // by hand
  md.querySelector('#awr-new').value = 'Never book on Sundays';
  click(w, md.querySelector('[data-awr-add]'));
  check(await until(async () => (await rules()).some(x => x.text === 'Never book on Sundays' && x.source.kind === 'manual')), 'a rule added by hand' + T);
  check(await until(() => /added by hand/.test(md.querySelector('#aw-rules')?.textContent || '')), 'shown as added by hand' + T);
  // delete with the question
  const man = (await rules()).find(x => x.source.kind === 'manual');
  click(w, await until(() => md.querySelector(`[data-awr-del="${man?.id}"]`)));
  const ask = await until(() => lastModal(d)?.classList.contains('cdlg') && lastModal(d));
  check(ask && /Delete this rule\?/.test(ask.textContent), 'deleting asks first' + T);
  if (ask) click(w, ask.querySelector('[data-cd="yes"]'));
  check(await until(async () => !(await rules()).some(x => x.id === man?.id)), 'deleted on the server' + T);
  check(await until(() => !md.querySelector(`[data-awr-id="${man?.id}"]`)), 'the row is gone' + T);
  // the source link
  w.eval('window.__jump = null; msgJump = function(o) { window.__jump = o; return Promise.resolve(true); };');
  const src = await until(() => md.querySelector(`[data-awr-src="${rid}"]`));
  if (src) click(w, src);
  check(await until(() => w.__jump && w.__jump.art === 'a' && w.__jump.id === m.id && w.__jump.agent === ag.id), 'the source opens the chat message ' + JSON.stringify(w.__jump) + T);
  [...d.querySelectorAll('.modal')].forEach(x => x.remove());
  // an agent without rules: the hint
  const m2 = await openDlg(w, d, empty.id);
  check(m2 && await until(() => /from now on always/.test(m2.querySelector('#awr-empty')?.textContent || '')), 'no rules: the hint how they come about' + T);
  w.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 5});
  // a person without an organisation (freelancer-matrix: agents)
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.status < 300, 'a person without an organisation ' + fr.status);
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'}, FK);

  await scenario('organisation', 'alice', CK);
  await scenario('without organisation', 'frida', FK);
  console.log(`p2235_c_rules_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
