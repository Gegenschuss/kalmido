// 2.166.0 UI tests (#2633), own container (start.sh), jsdom. Settings save themselves (the pattern of #2247) and the tokens
// sit in one place:
// - Settings > organisation: name and e-mail domains save when the field is left (no Save button); an empty name goes
//   back and is not saved
// - Settings > Access: API tokens, webhooks and the tokens of my personal agents; Account > Advanced, Integrations and
//   Agents link there; the old focus keys "tokens" / "webhooks" open it
// - a person without an organisation (Frida) has the same Access area: her token, her webhook section, her agent
// (public link: checklist_ui.js; mailbox: p2141_a_ui.js; OIDC draft: p290_ui.js + oidc_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const ALL = 'cal,collab,agents,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'agents', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 2});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  check(org.http < 300 && org.id, 'setup: organisation Alpha ' + org.http);
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'setup: a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');

  // ================= organisation: name + domains save themselves
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('org')`); await sleep(500);
  let nm = await until(() => d.querySelector(`.smodal #ws-name-${org.id}`));
  if (!nm) { d.querySelector('.smodal')?.remove(); w.eval(`settingsModal('account')`); nm = await until(() => d.querySelector(`.smodal #ws-name-${org.id}`)); }
  check(nm && !d.querySelector('.smodal [data-wssave]'), 'organisation: name field, no Save button');
  change(w, nm, 'Alpha Studio');
  check(await until(async () => ((await call(CA, 'GET', '/api/orgs')).orgs || []).find(o => o.id === org.id)?.name === 'Alpha Studio'), 'the name saved itself when the field was left');
  const dm = await until(() => d.querySelector(`.smodal #ws-dom-${org.id}`));
  change(w, dm, 'alpha.example');
  check(await until(async () => ((await call(CA, 'GET', '/api/orgs')).orgs || []).find(o => o.id === org.id)?.domains === 'alpha.example'), 'the e-mail domains saved themselves');
  const nm2 = await until(() => d.querySelector(`.smodal #ws-name-${org.id}`));
  change(w, nm2, '   '); await sleep(500);
  check(((await call(CA, 'GET', '/api/orgs')).orgs || []).find(o => o.id === org.id)?.name === 'Alpha Studio' && nm2.value === 'Alpha Studio', 'an empty name goes back, nothing saved');
  d.querySelector('.smodal')?.remove();

  // ================= Settings > Access
  const AG = await call(CA, 'POST', '/api/my/agents', {username: 'alice-bot', display_name: 'Alice Bot'});
  check(AG.http < 300 && AG.id, 'setup: a personal agent ' + AG.http);
  await call(CA, 'POST', '/api/me/tokens', {name: 'Home script', scopes: ['read']});
  w.eval(`settingsModal('tokens')`); await sleep(500);
  let md = d.querySelector('.smodal');
  check(md.querySelector('.snav [data-sec="access"]')?.classList.contains('on'), 'the focus "tokens" opens Settings > Access');
  const pane = md.querySelector('[data-pane="access"]');
  check(pane && pane.querySelector('#s-api-h') && pane.querySelector('#s-wh-h') && pane.querySelector('#s-acz-ag-h'), 'Access: API tokens, webhooks, agents');
  check(await until(() => /Home script/.test(pane.querySelector('#s-toks')?.textContent || '')), 'Access: my API token is listed');
  check(await until(() => /No webhooks yet/.test(pane.querySelector('#s-whs')?.textContent || '')), 'Access: the webhooks load');
  const agRow = await until(() => pane.querySelector(`#s-acz-ags [data-aczag="${AG.id}"]`));
  check(agRow && /Alice Bot/.test(agRow.textContent) && agRow.querySelector('[data-acz="token"]') && agRow.querySelector('[data-acz="setup"]'), 'Access: my agent with "New API token" and "Set up on a computer"');
  click(w, agRow && agRow.querySelector('[data-acz="token"]')); await sleep(300);
  const tm = [...d.querySelectorAll('.modal')].pop();
  check(tm && /New API token for Alice Bot/.test(tm.textContent), 'the agent token dialog opens from Access');
  click(w, tm && tm.querySelector('[data-m="close"]')); await sleep(200);
  for (const sec of ['account', 'integr', 'ai']) check(md.querySelector(`[data-pane="${sec}"] [data-m="go-access"]`), `${sec}: a link to Access`);
  check(!md.querySelector('[data-pane="account"] #s-toks') && !md.querySelector('[data-pane="integr"] #s-whs'), 'the old places have no own token / webhook list any more');
  click(w, md.querySelector('.snav [data-sec="ai"]')); await sleep(300);
  click(w, md.querySelector('[data-pane="ai"] [data-m="go-access"]')); await sleep(300);
  check(md.querySelector('.snav [data-sec="access"]')?.classList.contains('on'), 'the link in Agents opens Access');
  md.remove(); w.eval(`settingsModal('webhooks')`); await sleep(400);
  check(d.querySelector('.smodal .snav [data-sec="access"]')?.classList.contains('on'), 'the focus "webhooks" opens Access');
  w.close();

  // ================= a person without an organisation: the same Access area
  await call(CF, 'POST', '/api/me/tokens', {name: 'Frida script', scopes: ['read']});
  const FAG = await call(CF, 'POST', '/api/my/agents', {username: 'frida-bot', display_name: 'Frida Bot'});
  check(FAG.http < 300, 'frida: her personal agent ' + FAG.http);
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('tokens')`); await sleep(500);
  const fp = d.querySelector('.smodal [data-pane="access"]');
  check(fp && d.querySelector('.smodal .snav [data-sec="access"]')?.classList.contains('on'), 'frida: Settings > Access');
  check(await until(() => /Frida script/.test(fp?.querySelector('#s-toks')?.textContent || '')), 'frida: her API token');
  check(fp && fp.querySelector('#s-wh-h'), 'frida: the webhooks section');
  check(await until(() => /Frida Bot/.test(fp?.querySelector('#s-acz-ags')?.textContent || '')), 'frida: her agent');
  click(w, fp && fp.querySelector('[data-tok="new"]')); await sleep(300);
  check(/Name/.test([...d.querySelectorAll('.modal')].pop()?.textContent || ''), 'frida: "New token" opens the token dialog');
  w.close();

  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
