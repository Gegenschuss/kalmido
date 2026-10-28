// kalmido-suite: fresh
// 2.364.0 D (#3035) the dialog "New agent" in short form: display name, team / personal, workspace and profile picture;
// everything else (username, note, where it runs, proposals, permissions, IPs, webhook, limits, runtime) is folded under
// "Advanced" (closed) and sent exactly as before when it stays closed. "Permissions" is a heading once; the runtime's
// permission mode is called "Approvals". After "Create" the one-command setup opens at once; the token for an own setup
// and the way by hand only under "For advanced users"; in Settings > Agents > Set up the steps by hand (useradd …) are
// folded the same way. Own container (start.sh), jsdom.
// freelancer-matrix: agents - frida has no organisation: her personal agent goes the same way (one-command setup first).
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 6000) => { for (let t = 0; t < ms; t += 100) { const v = await f(); if (v) return v; await sleep(100); } return f(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,agents'});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,agents'});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'P4: frida is in no organisation');

  // (1) the admin's "New team agent": four things visible, the rest folded
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await w.eval(`api('GET', '/api/admin/agents').then(j => { S.agOffer = j.scopes; agModal(null, () => {}, {kind: 'team'}); })`);
  let md = await until(() => lastModal(d)?.querySelector('#ag-name') && lastModal(d));
  const adv = md?.querySelector('details#ag-adv');
  check(adv && !adv.open && /Advanced/.test(adv.querySelector('summary')?.textContent || ''), '"Advanced" is there and closed');
  const outside = id => md.querySelector('#' + id) && !md.querySelector('#' + id).closest('details#ag-adv');
  check(['ag-owner', 'ag-ws', 'ag-name', 'ag-avpick'].every(outside), 'short form: kind, workspace, name, picture outside "Advanced" ' + ['ag-owner', 'ag-ws', 'ag-name', 'ag-avpick'].map(i => i + ':' + outside(i)).join(','));
  const inside = ['ag-user', 'ag-note', 'ag-prov', 'ag-prop', 'ag-ips', 'ag-url', 'ag-lsoft', 'ag-lhard', 'ag-model', 'ag-ac', 'ag-pm'];
  check(inside.every(i => md.querySelector('#' + i)?.closest('details#ag-adv')), 'the rest under "Advanced" ' + inside.filter(i => !md.querySelector('#' + i)?.closest('details#ag-adv')).join(','));
  check(md.querySelector('.scopes')?.closest('details#ag-adv'), 'the permissions under "Advanced"');
  const heads = [...md.querySelectorAll('h4, legend, label')].map(x => x.textContent.trim()).filter(t => t === 'Permissions');
  check(heads.length === 1, '"Permissions" is a heading once ' + heads.length);
  check(md.querySelector('label[for="ag-pm"]')?.textContent === 'Approvals', 'the runtime choice is called "Approvals"');
  // the values sent without opening "Advanced": exactly the old defaults
  w.eval(`window.__sent = null; { const o = calReq; calReq = (m, u, b) => { if (m === 'POST' && u === '/api/admin/agents') window.__sent = JSON.parse(JSON.stringify(b)); return o(m, u, b); }; }`);
  const nm = md.querySelector('#ag-name'); nm.value = 'Robo'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(md.querySelector('#ag-user').value === 'robo', 'the username follows the name (folded)');
  click(w, md.querySelector('[data-m="ok"]'));
  const sent = await until(() => w.eval('window.__sent'));
  const want = {display_name: 'Robo', note: '', provider: '', proposals: 'shared', webhook_url: '', limits: null,
    runtime: {model: '', autocompact: true, autocompact_pct: null, nightly_reset: '', permission_mode: ''},
    scopes: ['read', 'tasks:write', 'comments', 'files:read', 'files:write'], allowed_ips: '', owner_id: null, org_id: org.id, username: 'robo'};
  const norm = o => JSON.stringify(Object.keys(o || {}).sort().reduce((a, k) => ({...a, [k]: o[k]}), {}));
  check(norm(sent) === norm(want), 'sent exactly as before ' + norm(sent));
  // (2) the one-command setup at once; the token and the way by hand under "For advanced users"
  md = await until(() => lastModal(d)?.querySelector('#ains-dir') && lastModal(d));
  check(md && /Set up Robo on a computer/.test(md.querySelector('h3')?.textContent || ''), 'after Create: the one-command setup');
  const fa = md?.querySelector('details#av-adv');
  check(fa && !fa.open && /For advanced users/.test(fa.querySelector('summary').textContent) && !md.querySelector('#av-tokv'), 'token and the way by hand folded under "For advanced users"');
  check(!/useradd/.test(md?.textContent || ''), 'no useradd in the setup dialog');
  click(w, md.querySelector('[data-m="av-tok"]'));
  check(/^abk_/.test(md.querySelector('#av-tokv')?.value || ''), 'the token on request');
  const ag = (await call(CA, 'GET', '/api/admin/agents')).agents.find(a => a.username === 'robo');
  check(ag && JSON.stringify(ag.effective_scopes) === '["read","tasks:write","comments","files:read","files:write"]' && !ag.owner && ag.org_id === org.id, 'the agent on the server ' + JSON.stringify(ag && {s: ag.effective_scopes, o: ag.org_id}));
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  // (3) Settings > Agents > Set up: the steps by hand folded
  w.eval(`settingsModal('ai')`);
  await until(() => d.querySelector('.smodal'));
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  const by = await until(() => d.querySelector('#s-agguide details.agbyhand'));
  check(by && !by.open && /For advanced users/.test(by.querySelector('summary').textContent), 'Set up: the steps by hand under "For advanced users" ' + w.eval(`JSON.stringify({sm: document.querySelectorAll('.smodal').length, g: !!document.querySelector('#s-agguide'), panes: [...document.querySelectorAll('[data-aisp]')].map(p => p.dataset.aisp + (p.hidden ? '-' : '+')), m: S.route.mod})`));
  check(/one command/.test(d.querySelector('#s-agguide')?.textContent || ''), 'Set up: the one-command way named first');
  w.close();

  // (4) P4: frida's personal agent: the one-command setup right after creating
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  w.eval(`settingsModal('ai')`);
  await until(() => d.querySelector('.smodal'));
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  const fin = await until(() => d.querySelector('#myag-user'));
  check(fin, 'frida: the create form');
  if (fin) {
    d.querySelector('#myag-user').value = 'fridabot'; d.querySelector('#myag-name').value = 'Fridabot';
    click(w, d.querySelector('[data-myag-act="new"]'));
    md = await until(() => d.querySelector('.modal:not(.smodal) #ains-dir') && lastModal(d));
    check(md && md.querySelector('details#av-adv:not([open])') && !md.querySelector('#av-tokv'), 'frida: one-command setup at once, the token folded');
    check((await call(CF, 'GET', '/api/my/agents')).agents?.length === 1, 'frida: created');
  }
  w.close();

  console.log(`p2364_d_agentform_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
