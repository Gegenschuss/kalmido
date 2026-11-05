// kalmido-suite: fresh
// 2.565.0 D UI test (#4674, own container, start.sh). jsdom: the server settings of a Kalmido AI (static/js/srvagent.js) offer
// "Model per routine": one choice per starter routine (briefing, basket, meeting notes, follow-up), filled from the same live
// model list of the provider as the agent's model, "Like the agent" by default; Save sends only the changed routines
// (flow_models), the dialog shows the stored choice again; the latest runs name the routine and the model.
// Real routes against tests/fake_anthropic.py (the provider stand-in inside the test container), as p2557_c_srvagent_ui.js.
// freelancer-matrix: agents (a person without an organisation and her own server agent)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const SKEY = 'AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=';  // a test server key (the provider key is sealed with it)
if (!process.env.P2565DU_NOSTART) {
  const extra = `${process.env.EXTRA || ''} -e KALMIDO_SECRET_KEY=${SKEY} -e KALMIDO_SRVAGENT_ANTHROPIC_URL=http://127.0.0.1:8091 -e KALMIDO_SRVAGENT_RUN_S=60`;
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: extra.trim()}});
  require('fs').copyFileSync(path.join(__dirname, 'fake_anthropic.py'), path.join(DATA, 'fake_anthropic.py'));
  execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_anthropic.py']);
}
const providerUp = () => { try { execFileSync('docker', ['exec', CT, 'python', '-c', "import socket; socket.create_connection(('127.0.0.1', 8091), 1)"], {stdio: 'ignore'}); return true; } catch { return false; } };
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

async function openSettings(w, d, aid) {
  w.eval(`settingsModal('ai')`);
  await until(() => d.querySelector('.smodal'));
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  const sb = await until(() => d.querySelector(`.smodal [data-myag="${aid}"] [data-myag-act="srv"]`));
  if (!sb) return null;
  click(w, sb);
  return until(() => lastModal(d)?.querySelector('#srv-keyhint') && lastModal(d));
}

(async () => {
  await until(async () => (await fetch(B + 'sw.js').catch(() => null))?.ok);
  check(await until(providerUp), 'the stand-in of the provider runs');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']}, CK);
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 10}, CK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab,docs,files'}, FK);
  check(((await call('GET', '/api/state', null, FK)).me?.workspaces || []).length === 0, 'frida has no organisation');
  const ag = await call('POST', '/api/my/agents', {username: 'frida-ki', display_name: 'Frida KI', provider: 'kalmido-server'}, FK);
  const AID = ag.id;
  check((await call('PUT', `/api/agents/${AID}/server`, {api_key: 'sk-test-ui-0000abcd'}, FK)).has_key === true, 'her server agent with a key');

  let w = await boot({user: 'frida', hash: 'inbox'}), d = w.document;
  const log = [];
  const f0 = w.fetch;
  w.fetch = (u, o = {}) => { if (/\/api\/agents\/\d+\/server$/.test(String(u)) && o.method === 'PUT') log.push(JSON.parse(o.body)); return f0(u, o); };
  let ed = await openSettings(w, d, AID);
  check(ed, 'the server settings open');
  if (ed) {
    check(ed.querySelector('.srvflows legend')?.textContent === 'Model per routine', 'the section "Model per routine"');
    const sels = () => [...ed.querySelectorAll('[data-srv-fm]')];
    check(sels().map(s => s.dataset.srvFm).join() === 'briefing,tidy,meetings,followup', 'one choice per routine ' + sels().map(s => s.dataset.srvFm).join());
    check(/Morning briefing/.test(ed.querySelector('label[for="srv-fm-briefing"]')?.textContent || ''), 'the routine named as in the starter pack');
    const filled = await until(() => sels().length === 4 && sels().every(s => s.options.length === 4) && 1);
    check(filled && sels().every(s => s.value === '' && s.options[0].textContent === 'Like the agent')
      && [...sels()[0].options].map(o => o.value).slice(1).join() === 'claude-opus-5-5,claude-sonnet-5-5,claude-haiku-5-5',
    'filled from the live model list, "Like the agent" chosen ' + sels().map(s => s.options.length).join());
    ed.querySelector('#srv-fm-briefing').value = 'claude-haiku-5-5';
    click(w, ed.querySelector('[data-m="srv-save"]'));
    const p = await until(() => log.find(x => x.flow_models));
    check(p && JSON.stringify(p.flow_models) === '{"briefing":"claude-haiku-5-5"}', 'Save sends only the changed routine ' + JSON.stringify(p?.flow_models));
    const sv = await until(async () => { const j = await call('GET', `/api/agents/${AID}/server`, null, FK); return j.flow_models?.briefing === 'claude-haiku-5-5' && j; });
    check(sv && sv.flow_models.tidy === '' && sv.model === 'claude-sonnet-5-5', 'stored: the briefing\'s model, the agent\'s model unchanged');
    const n0 = log.length;
    await until(() => ed.querySelector('#srv-fm-briefing')?.dataset.was === 'claude-haiku-5-5');
    click(w, ed.querySelector('[data-m="srv-save"]'));
    const p2 = await until(() => log.length > n0 && log[n0]);
    check(p2 && !('flow_models' in p2), 'Save without a change sends no flow_models ' + JSON.stringify(p2));
    click(w, ed.querySelector('[data-m="close"]'));
  }
  w.close();

  // a planned briefing runs with its model: the latest runs name the routine and the model
  const plans = await call('POST', `/api/agents/${AID}/server/starter`, {items: ['briefing']}, FK);
  const pid = plans.items?.[0]?.id;
  check(pid, 'the briefing plan of the starter pack');
  await call('POST', `/api/agent-schedules/${pid}/run`, {}, FK);
  const runs = await until(async () => { const r = (await call('GET', `/api/agents/${AID}/server/runs`, null, FK)).runs || []; return r.some(x => x.state === 'done' && x.flow === 'briefing') && r; }, 400);
  check(runs && runs[0].model === 'claude-haiku-5-5', 'the briefing ran with its model ' + JSON.stringify((runs || [])[0]));
  w = await boot({user: 'frida', hash: 'inbox'}); d = w.document;
  ed = await openSettings(w, d, AID);
  const row = ed && await until(() => ed.querySelector('.srvrun'));
  check(row && /Morning briefing/.test(row.textContent) && /claude-haiku-5-5/.test(row.textContent), 'the latest runs: routine and model ' + (row?.textContent || '').replace(/\s+/g, ' ').slice(0, 160));
  check(ed && (await until(() => ed.querySelector('#srv-fm-briefing')?.value === 'claude-haiku-5-5')), 'the dialog shows the stored choice again');
  w.close();

  console.log(`p2565_d_srvmodel_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
