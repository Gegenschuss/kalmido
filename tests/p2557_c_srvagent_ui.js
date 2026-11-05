// kalmido-suite: fresh
// 2.557.0 C UI test (#4670, own container, start.sh). jsdom: the setup of an agent on the Kalmido server (static/js/srvagent.js)
// - Settings > Agents > Set up offers "Set up on the Kalmido server"; the dialog is prefilled from GET /api/agents/server/defaults
//   (name, model claude-sonnet-5-5, instructions "Kalmido only"), the key is a password field, five starter ticks
// - Create: the agent (provider kalmido-server) -> PUT /api/agents/<id>/server with key, model and instructions -> the starter
//   pack with only the ticked items (real: plans and standing rules on the server); no token dialog
// - its row shows the cloud button; the settings dialog shows only "…abcd" (Replace / Delete), the models of the provider,
//   the latest runs; Replace + Save sends the new key
// - the instance switch off (server_agents_off): the dialog says so and offers no Create
// Everything real: part B's routes (/api/agents/<id>/server, …/models, …/runs) and a run, against tests/fake_anthropic.py (the
// stand-in for the provider inside the test container, as p2557_b_srvagent_test.py); the window only records what it sent.
// - the same for a person without an organisation (freelancer-matrix: agents)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const SKEY = 'AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=';  // a test server key (the provider key is sealed with it)
if (!process.env.P2557C_NOSTART) {
  const extra = `${process.env.EXTRA || ''} -e KALMIDO_SECRET_KEY=${SKEY} -e KALMIDO_SRVAGENT_ANTHROPIC_URL=http://127.0.0.1:8091 -e KALMIDO_SRVAGENT_RUN_S=60`;
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: extra.trim()}});
  require('fs').copyFileSync(path.join(__dirname, 'fake_anthropic.py'), path.join(DATA, 'fake_anthropic.py'));
  execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_anthropic.py']);
}
const providerUp = () => { try { execFileSync('docker', ['exec', CT, 'python', '-c', "import socket; socket.create_connection(('127.0.0.1', 8091), 1)"], {stdio: 'ignore'}); return true; } catch { return false; } };
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

// what the page sent to part B's routes (recorded, then passed on unchanged)
function record(w, log) {
  const f0 = w.fetch;
  w.fetch = (u, o = {}) => {
    const st = String(u);
    if (/\/api\/agents\/\d+\/server(\/|\?|$)/.test(st)) log.push({method: (o.method || 'GET').toUpperCase(), url: st, body: o.body ? JSON.parse(o.body) : null});
    return f0(u, o);
  };
}

async function setupPane(w, d) {
  w.eval(`settingsModal('ai')`);
  await until(() => d.querySelector('.smodal'));
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  return until(() => d.querySelector('.smodal [data-myag-act="srvnew"]'));
}

async function scenario(tag, user, ck) {
  const T = ` (${tag})`;
  const w = await boot({user, hash: 'inbox'}), d = w.document, log = [];
  record(w, log);
  const btn = await setupPane(w, d);
  check(btn, 'Set up offers the agent on the Kalmido server' + T);
  if (!btn) { w.close(); return; }
  click(w, btn);
  const md = await until(() => lastModal(d)?.querySelector('#srv-name') && lastModal(d));
  check(md, 'the dialog opens' + T);
  if (!md) { w.close(); return; }
  check(md.querySelector('#srv-name').value === 'Kalmido AI' && md.querySelector('#srv-user').value === 'kalmido-ai', 'name and username suggested' + T);
  check(md.querySelector('#srv-key').type === 'password', 'the key is a password field' + T);
  check(md.querySelector('#srv-model').value === 'claude-sonnet-5-5', 'the default model' + T);
  check(/outside Kalmido/.test(md.querySelector('#srv-ins').value), 'the instructions: Kalmido only' + T);
  const ticks = [...md.querySelectorAll('[data-srv-st]')];
  // 2.568.0 (#4673): + the office tick, off by default (it needs the agent's office rights)
  check(ticks.length === 6 && ticks.filter(x => x.dataset.srvSt !== 'office').every(x => x.checked) && !md.querySelector('[data-srv-st="office"]').checked
    && md.querySelector('#srv-fdays').value === '5', 'five starter ticks on, office off, follow-up after 5 days' + T);
  // without a key: refused, nothing created
  click(w, md.querySelector('[data-m="srv-ok"]'));
  check(md.isConnected && !log.length, 'without a key: nothing is sent' + T);
  const un = 'ki-' + user;
  md.querySelector('#srv-name').value = 'KI ' + user; md.querySelector('#srv-user').value = un;
  md.querySelector('#srv-key').value = 'sk-test-ui-0000abcd';
  md.querySelector('[data-srv-st="tidy"]').checked = false;
  md.querySelector('#srv-fdays').value = '3';
  click(w, md.querySelector('[data-m="srv-ok"]'));
  const ag = await until(async () => ((await call('GET', '/api/my/agents', null, ck)).agents || []).find(a => a.username === un));
  check(ag && ag.provider === 'kalmido-server', 'the agent is created with provider kalmido-server' + T);
  if (!ag) { w.close(); return; }
  const put = await until(() => log.find(x => x.method === 'PUT' && x.url.endsWith(`/api/agents/${ag.id}/server`)));
  check(put && put.body.api_key === 'sk-test-ui-0000abcd' && put.body.model === 'claude-sonnet-5-5' && put.body.provider === 'anthropic' && /Kalmido/.test(put.body.instructions),
    'PUT …/server with key, model and instructions' + T);
  const plans = await until(async () => { const p = (await call('GET', `/api/agents/${ag.id}/schedules`, null, ck)).data || []; return p.length >= 2 && p; });
  check(plans && plans.length === 2 && plans.some(p => p.title === 'Morning briefing') && plans.some(p => p.title === 'Follow up' && /3 days/.test(p.prompt)) && !plans.some(p => p.action === 'triage'),
    'the starter pack: only the ticked plans (briefing, follow-up after 3 days, no basket)' + T);
  const rules = (await call('GET', `/api/agents/${ag.id}/rules`, null, ck)).rules || [];
  check(rules.length === 2, 'the starter pack: two standing rules (documents, meetings)' + T);
  check(await until(() => !md.isConnected), 'the dialog closes' + T);
  check(!d.querySelector('#av-tokv') && ![...d.querySelectorAll('.modal')].some(m => /shown only this once/.test(m.textContent)), 'no token dialog for a server agent' + T);
  const sv = await call('GET', `/api/agents/${ag.id}/server`, null, ck);
  check(sv.has_key && sv.key_hint === '…abcd' && sv.model === 'claude-sonnet-5-5' && /outside Kalmido/.test(sv.instructions) && !JSON.stringify(sv).includes('0000abcd'),
    'stored: the key only as its last four characters, model and instructions' + T);
  // a real run: a chat message, the stand-in answers
  await call('POST', `/api/agents/${ag.id}/chat`, {body: 'Hello'}, ck);
  const runs = await until(async () => { const r = (await call('GET', `/api/agents/${ag.id}/server/runs`, null, ck)).runs || []; return r.some(x => x.state === 'done') && r; }, 400);
  check(runs, 'a chat message makes a run that ends done' + T);

  // its row: the cloud button opens its server settings
  const sb = await until(() => d.querySelector(`.smodal [data-myag="${ag.id}"] [data-myag-act="srv"]`));
  check(sb, 'its row shows the button of the server settings' + T);
  if (sb) {
    click(w, sb);
    const ed = await until(() => lastModal(d)?.querySelector('#srv-keyhint') && lastModal(d));
    check(ed && ed.querySelector('#srv-keyhint').textContent === '…abcd' && ed.querySelector('#srv-keyrow').hidden, 'only the last four characters, no key field' + T);
    const opts = await until(() => ed && ed.querySelectorAll('#srv-model option').length === 3 && ed.querySelectorAll('#srv-model option'));
    check(opts && ed.querySelector('#srv-model').value === 'claude-sonnet-5-5', 'the models of the provider, the current one chosen' + T);
    const run = await until(() => ed && ed.querySelector('.srvrun'));
    check(run && /done/.test(run.textContent) && /\d+ steps?/.test(run.textContent) && /chat/.test(run.textContent), 'the latest runs (state, trigger, steps)' + T);
    if (ed) {
      click(w, ed.querySelector('[data-srv="rep"]'));
      check(!ed.querySelector('#srv-keyrow').hidden, 'Replace shows the key field' + T);
      ed.querySelector('#srv-key').value = 'sk-test-new-1111wxyz';
      ed.querySelector('#srv-model').value = 'claude-haiku-5-5';
      const n0 = log.length;
      click(w, ed.querySelector('[data-m="srv-save"]'));
      const p2 = await until(() => log.slice(n0).find(x => x.method === 'PUT'));
      check(p2 && p2.body.api_key === 'sk-test-new-1111wxyz' && p2.body.model === 'claude-haiku-5-5', 'Save sends the new key and model' + T);
      const hint = await until(() => ed.querySelector('#srv-keyhint')?.textContent === '…wxyz');
      check(hint, 'after Save the dialog shows the new last four characters' + T);
      const sv2 = await call('GET', `/api/agents/${ag.id}/server`, null, ck);
      check(sv2.key_hint === '…wxyz' && sv2.model === 'claude-haiku-5-5', 'stored: the new key and model' + T);
      click(w, ed.querySelector('[data-m="close"]'));
    }
  }
  w.close();
}

(async () => {
  await until(async () => (await fetch(B + 'sw.js').catch(() => null))?.ok);
  check(await until(providerUp), 'the stand-in of the provider runs');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'agents,comments,collab,docs,files'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 10});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab,docs,files'}, FK);

  await scenario('organisation', 'alice', CK);
  await scenario('without organisation', 'frida', FK);

  // the instance switch: off -> the dialog says so, no Create
  const off = await call('PATCH', '/api/admin/settings', {server_agents_off: true});
  check(off.server_agents_off === true, 'the instance switch off');
  const w = await boot({user: 'frida', hash: 'inbox'}), d = w.document;
  const btn = await setupPane(w, d);
  if (btn) {
    click(w, btn);
    const md = await until(() => lastModal(d)?.querySelector('.srvoff') && lastModal(d));
    check(md && !md.querySelector('[data-m="srv-ok"]') && !md.querySelector('#srv-key'), 'switched off: a note, no fields, no Create');
  } else check(false, 'switched off: the button is still there (the dialog explains)');
  w.close();
  await call('PATCH', '/api/admin/settings', {server_agents_off: false, password: 'password123'});  // allowing them again: with the password
  console.log(`p2557_c_srvagent_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
