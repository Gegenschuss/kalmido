// kalmido-suite: fresh
// 2.392.0 C (#3370) UI tests, own container (start.sh): the one-way mark and the decisions in the task panel (jsdom).
// The bar with the reason and "Give the yes" for an approver, the mark and a decision through the task menu's functions, a
// replaced decision crossed out and readable, the gate's card names what blocks and offers no "Approve anyway", the
// environment dialog's option. A person without an organisation (freelancer-matrix: tasks).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, ...(ck ? {Cookie: ck} : {})}, ...(body ? {body: JSON.stringify(body)} : {})}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');  // freelancer-matrix: tasks
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Release', kind: 'project', ptype: 'software'})).id;
  const ag = await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Frida bot', scopes: ['read', 'tasks:write', 'comments']});
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const AH = {Authorization: 'Bearer ' + (await call('POST', `/api/my/agents/${ag.id}/token`)).token};
  const T = (await call('POST', '/api/tasks', {title: 'Drop the column', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Plain work', list_id: L})).id;
  await call('PATCH', `/api/lists/${L}`, {irreversible_needs_yes: true});
  const w = await boot({user: 'frida', hash: 'l/' + L}), d = w.document;
  const open = async id => { w.eval(`openDetail(${id})`); await until(() => w.eval(`S.tl.id === ${id} && !!S.tl.comments`)); await idle(w); };
  await open(T);

  // ================= the mark from the menu's function, the bar
  check(!d.querySelector('.owbar'), 'no bar without a mark');
  const it = w.eval(`ow_menuItems(taskById(${T})).map(x => x.label)`);
  check(it.includes('Mark as a one-way step') && it.includes('Add a decision'), 'the menu offers both ' + JSON.stringify(it));
  w.eval(`ow_mark(${T})`);
  const inp = await until(() => d.querySelector('#cdlg-in'));
  inp.value = 'No way back';
  click(w, d.querySelector('[data-cd="yes"]'));
  const bar = await until(() => d.querySelector('.owbar'));
  check(bar && /No way back/.test(bar.textContent) && /Waiting for a yes/.test(bar.textContent), 'the bar: reason and state');
  check(!!d.querySelector('[data-ow="yes"]'), 'the owner gets Give the yes');
  // ================= the yes
  click(w, d.querySelector('[data-ow="yes"]'));
  await until(() => /Yes given/.test(d.querySelector('.owbar')?.textContent || ''));
  check(!d.querySelector('[data-ow="yes"]') && /Yes given/.test(d.querySelector('.owbar').textContent), 'after the yes: the state, no button');
  // ================= decisions
  check(!d.querySelector('.owdec'), 'no section without a decision');
  w.eval(`ow_decAdd(${T})`);
  const di = await until(() => d.querySelector('#cdlg-in')); di.value = 'Keep the old endpoint';
  click(w, d.querySelector('[data-cd="yes"]'));
  const sec = await until(() => d.querySelector('.owdec li'));
  check(sec && /Keep the old endpoint/.test(sec.textContent) && /Decisions/.test(d.querySelector('.owdec h5').textContent), 'the section with the entry');
  check(d.querySelector('#d-dec').compareDocumentPosition(d.querySelector('#d-content')) & w.Node.DOCUMENT_POSITION_FOLLOWING, 'above the description');
  w.eval(`ow_decAdd(${T}, ${+sec.dataset.did})`);
  const d2 = await until(() => d.querySelector('#cdlg-in')); d2.value = 'Drop it next time';
  click(w, d.querySelector('[data-cd="yes"]'));
  await until(() => d.querySelector('.owd.old'));
  check(/Keep the old endpoint/.test(d.querySelector('.owd.old')?.textContent || '') && d.querySelectorAll('.owd').length === 2, 'the old one crossed out and readable');
  // ================= the gate's card: a new reason takes the yes back
  await call('PUT', `/api/tasks/${T}/irreversible`, {reason: 'Now even worse'});
  const r2 = await call('POST', `/api/v1/tasks/${T2}/comments`, {body: 'Ready', suggestion: {kind: 'deploy', evidence: 'green'}}, null, AH);
  await open(T2);
  const card = await until(() => d.querySelector('.sug.gate'));
  check(card && /1 one-way step without a yes/.test(card.textContent) && /Drop the column/.test(card.textContent), 'the card names the task ' + JSON.stringify(r2).slice(0, 160));
  check(card && !card.querySelector('[data-act="gate-skip"]') && !card.querySelector('[data-act="gate-ok"]'), 'no Approve (anyway) while it blocks');
  // ================= the environment dialog
  w.eval(`env_editModal(listById(${L}), null, {manage: true})`);
  check(!!(await until(() => d.querySelector('#env-acc'))), 'the option in the environment dialog');
  check(!d.querySelector('#env-acc').checked, 'off by default');

  console.log(`p2392_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
