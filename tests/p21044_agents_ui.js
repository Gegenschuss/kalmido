// kalmido-suite: fresh
// 2.1044.0 UI test (#5824, #5825; own container, start.sh, jsdom). Real routes against tests/fake_anthropic.py (the provider
// stand-in inside the test container), as p2565_d_srvmodel_ui.js. Invented people only.
// freelancer-matrix: agents (frida has no organisation: her own server agent - its model from the chat menu, its card's settings)
// #5824 the chat menu of a server agent: "Model" opens a dialog with the provider's models by name, the current one chosen, the
//       server's default marked; a choice is saved at once and the next chat answer runs with it (the latest runs); "Model per
//       routine, instructions and key" leads into the server settings; an agent without a key says so with a way to add one
// #5825 the agent cards: a gear and a tap on picture / name open the settings (the owner without admin rights: her row in
//       Settings > Agents > Set up; the instance admin: the dialog "Edit agent", a colour changed there shows on the card at once);
//       a right click opens the card's menu (Settings, Chat, Plans, Log and usage limit, Pause); a person who may not change
//       the agent sees no gear and the picture keeps the person card
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const SKEY = 'AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA=';  // a test server key (the provider key is sealed with it)
if (!process.env.P21044_NOSTART) {
  const extra = `${process.env.EXTRA || ''} -e KALMIDO_SECRET_KEY=${SKEY} -e KALMIDO_SRVAGENT_ANTHROPIC_URL=http://127.0.0.1:8091 -e KALMIDO_SRVAGENT_RUN_S=60`;
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: extra.trim()}});
  require('fs').copyFileSync(path.join(__dirname, 'fake_anthropic.py'), path.join(DATA, 'fake_anthropic.py'));
  execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_anthropic.py']);
}
const providerUp = () => { try { execFileSync('docker', ['exec', CT, 'python', '-c', "import socket; socket.create_connection(('127.0.0.1', 8091), 1)"], {stdio: 'ignore'}); return true; } catch { return false; } };
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const items = d => [...d.querySelectorAll('[role="menuitem"]')];
const itemTx = d => items(d).map(b => b.textContent.replace(/\s+/g, ' ').trim());

(async () => {
  await until(async () => (await fetch(B + 'sw.js').catch(() => null))?.ok);
  check(await until(providerUp), 'the stand-in of the provider runs');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']}, CK);
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'}, CK);
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 10}, CK);
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, CK);
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'}, CK)).id;
  const FK = await login('frida'), BK = await login('bob');
  for (const k of [FK, BK]) await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'}, k);
  check(((await call('GET', '/api/state', null, FK)).me?.workspaces || []).length === 0, 'frida has no organisation');
  const AID = (await call('POST', '/api/my/agents', {username: 'frida-ki', display_name: 'Frida KI', provider: 'kalmido-server'}, FK)).id;
  check((await call('PUT', `/api/agents/${AID}/server`, {api_key: 'sk-test-ui-0000abcd'}, FK)).has_key === true, 'her server agent with a key');
  const NOKEY = (await call('POST', '/api/my/agents', {username: 'frida-two', display_name: 'Frida Zwei', provider: 'kalmido-server'}, FK)).id;
  await call('PUT', `/api/agents/${NOKEY}/server`, {instructions: 'Short answers.'}, FK);  // a server agent, no key yet
  const FL = (await call('POST', '/api/lists', {name: 'Garden'}, FK)).id;
  for (const id of [AID, NOKEY]) await call('PUT', `/api/lists/${FL}/members`, {user_id: id, role: 'edit'}, FK);
  const st = await call('GET', '/api/state', null, FK);
  check((st.agents || []).find(a => a.id === AID)?.server === true, '#5824: the agent object says it runs on the Kalmido server');

  // ================= #5824 the model of a server agent from its chat menu
  let w = await boot({user: 'frida', hash: 'agents'}), d = w.document;
  const openModel = async aid => {
    w.eval(`chatOpen(${aid})`); await idle(w);
    click(w, await until(() => d.querySelector('.chath [data-act="chat-head-menu"]')));
    const it = await until(() => items(d).find(b => /^Model/.test(b.textContent.trim())));
    check(it && !it.disabled, '#5824: "Model" in the chat menu can be chosen ' + JSON.stringify(itemTx(d)));
    click(w, it);
    return until(() => lastModal(d)?.querySelector('#srvm-body') && lastModal(d));
  };
  let md = await openModel(AID);
  check(md && /Model of Frida KI/.test(md.querySelector('h3')?.textContent || ''), '#5824: the dialog "Model of Frida KI"');
  const sel = md && await until(() => md.querySelector('#srvm-sel'));
  const opts = sel ? [...sel.options].map(o => o.textContent) : [];
  check(sel && sel.options.length === 3 && sel.value === 'claude-sonnet-5-5' && opts.includes('Claude Haiku 5.5') && opts.some(t => /^Claude Sonnet 5\.5 · server default$/.test(t)),
    '#5824: the provider\'s models, the current one chosen, the server default marked ' + JSON.stringify(opts));
  check(/applies from its next message/.test(md?.textContent || ''), '#5824: says when a change applies');
  if (sel) { sel.value = 'claude-haiku-5-5'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const saved = await until(async () => (await call('GET', `/api/agents/${AID}/server`, null, FK)).model === 'claude-haiku-5-5');
  check(saved, '#5824: the choice is saved at once (the server settings show the same model)');
  check(await until(() => /Model changed to/.test(d.querySelector('#toast')?.textContent || '')), '#5824: a toast names the new model');
  // the next answer runs with it
  await call('POST', `/api/agents/${AID}/chat`, {body: 'Hello'}, FK);
  const runs = await until(async () => { const r = (await call('GET', `/api/agents/${AID}/server/runs`, null, FK)).runs || []; return r.some(x => x.state === 'done') && r; }, 400);
  check(runs && runs[0].model === 'claude-haiku-5-5', '#5824: the next chat answer ran with the chosen model ' + JSON.stringify((runs || [])[0] || {}).slice(0, 200));
  // the way to the model per routine: the server settings
  click(w, md?.querySelector('[data-m="srvm-more"]'));
  const ed = await until(() => lastModal(d)?.querySelector('#srv-keyhint') && lastModal(d));
  check(ed && ed.querySelector('.srvflows'), '#5824: "Model per routine, instructions and key" opens the server settings with the routines');
  ed?.remove();
  // without a key: a sentence and a way to the key, no empty choice
  md = await openModel(NOKEY);
  check(md && await until(() => /No API key is stored/.test(md.textContent)) && !md.querySelector('#srvm-sel') && md.querySelector('[data-m="srvm-key"]'),
    '#5824: no key - says so, with "Add an API key" ' + (md?.textContent || '').replace(/\s+/g, ' ').slice(0, 200));
  click(w, md?.querySelector('[data-m="srvm-key"]'));
  check(await until(() => lastModal(d)?.querySelector('#srv-key')), '#5824: "Add an API key" opens the key field');
  lastModal(d)?.remove();
  w.eval('chatClose()');

  // ================= #5825 the cards (frida: owner, no admin)
  w.close(); w = await boot({user: 'frida', hash: 'agents'}); d = w.document;
  const card = (dd, id) => dd.querySelector(`.agcard[data-agc="${id}"]`);
  check(await until(() => card(d, AID)), 'her agent\'s card');
  const head = card(d, AID)?.querySelector('.agset');
  check(head && head.tagName === 'BUTTON' && head.getAttribute('aria-label') === 'Settings of Frida KI' && /Frida KI/.test(head.textContent) && head.querySelector('.avatar')
    && !card(d, AID).querySelector('[data-mcard]'), '#5825: picture and name are one button "Settings of Frida KI"');
  check(card(d, AID)?.querySelector('.agb .agsetb[aria-label="Settings of Frida KI"]'), '#5825: the gear next to Chat and Plans');
  click(w, head);
  const row = await until(() => d.querySelector(`.smodal [data-myag="${AID}"]`));
  check(row && /Frida KI/.test(row.textContent) && row.querySelector('[data-myag-act="srv"]'), '#5825: a tap on picture / name opens her agent\'s settings (with the server settings)');
  d.querySelectorAll('.smodal, .modal').forEach(m => m.remove());
  click(w, card(d, AID)?.querySelector('.agsetb'));
  check(await until(() => d.querySelector(`.smodal [data-myag="${AID}"]`)), '#5825: the gear opens them too');
  d.querySelectorAll('.smodal, .modal').forEach(m => m.remove());
  card(d, AID)?.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  check(await until(() => itemTx(d).includes('Settings')) && ['Chat', 'Plans', 'Log and usage limit', 'Pause'].every(x => itemTx(d).includes(x)),
    '#5825: the card\'s menu by right click ' + JSON.stringify(itemTx(d)));
  click(w, items(d).find(b => b.textContent.trim() === 'Settings'));
  check(await until(() => d.querySelector(`.smodal [data-myag="${AID}"]`)), '#5825: "Settings" in the card\'s menu opens them');
  w.close();

  // ================= #5825 the instance admin and a team agent; a member without rights
  const TA = (await call('POST', '/api/admin/agents', {scopes: ['read', 'comments'], username: 'helper', display_name: 'Helper'}, CK)).id;
  const L = (await call('POST', '/api/lists', {name: 'Office'}, CK)).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: TA, role: 'edit'}, CK);
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'}, CK);
  await call('PATCH', `/api/lists/${L}`, {agent_members: true}, CK);  // members may see and use the project's agent (default off)
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  check(await until(() => card(d, TA)?.querySelector('.agsetb')), '#5825: the admin sees the gear on the team agent');
  click(w, card(d, TA).querySelector('.agsetb'));
  const em = await until(() => [...d.querySelectorAll('.modal')].find(m => /Edit agent/.test(m.querySelector('h3')?.textContent || '')));
  check(em && em.querySelector('#ag-name')?.value === 'Helper', '#5825: the gear opens "Edit agent" with its name');
  const col = em?.querySelector('[data-accol="#30a46c"]');
  click(w, col);
  check(await until(() => /#30a46c/.test(card(d, TA)?.querySelector('.avatar')?.getAttribute('style') || '')), '#5825: a colour chosen there shows on the card at once');
  em?.remove();
  w.close();
  w = await boot({user: 'bob', hash: 'agents'}); d = w.document;
  check(await until(() => card(d, TA)), 'bob sees the team agent\'s card');
  check(card(d, TA) && !card(d, TA).querySelector('.agsetb') && !card(d, TA).querySelector('.agset') && card(d, TA).querySelector('[data-mcard]'),
    '#5825: a member without rights: no gear, the picture keeps the person card');
  card(d, TA)?.dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  check(await until(() => itemTx(d).includes('Chat')) && !itemTx(d).includes('Settings') && !itemTx(d).includes('Pause'), '#5825: his menu without Settings / Pause ' + JSON.stringify(itemTx(d)));
  w.close();

  console.log(`p21044_agents_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
