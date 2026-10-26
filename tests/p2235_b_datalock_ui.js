// kalmido-suite: fresh
// 2.235.0 B UI tests (#2902, own container, start.sh). jsdom, the section "Data the agent never sees" in the agent's gear:
// - the areas as switches: private e-mails on (marked default), the fixed ones (journal, health ...) on and greyed, contracts off
// - a switch -> PATCH /api/agents/<id>/data-lock with only {areas: {key: bool}}; the quiet tick; the value is on the server
// - a project added from the list and removed again, a tag added (Enter / button) and removed; after a reload the state is there
// - the same for a person in an organisation and for a person without an organisation (freelancer-matrix: agents)
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

async function openLock(user, id) {
  const w = await boot({user, hash: 'agents'}), d = w.document;
  await until(() => d.querySelector('.agcard'));
  w.eval(`settingsModal('ai')`); await sleep(500);
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  const r = await until(() => d.querySelector(`#s-myown [data-myag="${id}"]`));
  click(w, r.querySelector('[data-myag-act="work"]'));
  const md = await until(() => lastModal(d)?.classList.contains('awdlg') && lastModal(d));
  const box = md && await until(() => md.querySelector('#aw-lock #awl-a-mail') && md.querySelector('#aw-lock'));
  return {w, d, md, box};
}

async function scenario(tag, user, AID, LID, ck) {
  const T = ` (${tag})`, srv = async () => (await call('GET', `/api/agents/${AID}/data-lock`, null, ck)).data_lock;
  const {w, box} = await openLock(user, AID);
  check(box, 'the section is in the gear' + T);
  if (!box) { w.close(); return; }
  w.eval(`window.__ao = api; api = function(m, u, b) { if (/data-lock/.test(u) && m === 'PATCH') window.__sent.push(JSON.stringify(b)); return window.__ao.apply(this, arguments); }; window.__sent = [];`);
  check(/Data the agent never sees/.test(box.textContent), 'the heading' + T);
  const mail = box.querySelector('#awl-a-mail'), jr = box.querySelector('#awl-a-journal'), con = box.querySelector('#awl-a-contracts');
  check(mail.checked && !mail.disabled && /default/.test(mail.closest('label').textContent), 'private e-mails: locked, switchable, marked default' + T);
  check(jr.checked && jr.disabled && box.querySelector('#awl-a-health').checked && box.querySelector('#awl-a-health').disabled, 'journal / health: always locked, greyed' + T);
  check(!con.checked, 'contracts open by default' + T);
  con.checked = true; con.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => w.__sent[0] === '{"areas":{"contracts":true}}'), 'one switch = only that area: ' + w.__sent[0] + T);
  check(await until(() => box.querySelector('.svtick')), 'the quiet tick' + T);
  check(await until(async () => (await srv()).areas.contracts === true), 'contracts locked on the server' + T);
  setVal(w, box.querySelector('#awl-addlist'), String(LID));
  check(await until(async () => JSON.stringify((await srv()).lists.map(x => x.id)) === `[${LID}]`), 'a project added' + T);
  check(await until(() => box.querySelector(`[data-awl-rmlist="${LID}"]`) && /Diary project/.test(box.textContent)), 'the project is listed by name' + T);
  check(!box.querySelector(`#awl-addlist option[value="${LID}"]`), 'a locked project is no longer offered' + T);
  const tin = box.querySelector('#awl-tagin'); tin.value = '#Privat';
  click(w, box.querySelector('[data-awl-addtag]'));
  check(await until(async () => JSON.stringify((await srv()).tags) === '["Privat"]'), 'a tag added (without #)' + T);
  const tin2 = await until(() => box.querySelector('#awl-tagin')); tin2.value = 'health-notes';
  tin2.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
  check(await until(async () => (await srv()).tags.length === 2), 'Enter adds a tag' + T);
  click(w, await until(() => box.querySelector('[data-awl-rmtag="health-notes"]')));
  check(await until(async () => JSON.stringify((await srv()).tags) === '["Privat"]'), 'a tag removed' + T);
  w.close();
  // a reload shows the state; then the project goes again
  const o2 = await openLock(user, AID);
  check(o2.box && o2.box.querySelector('#awl-a-contracts').checked && o2.box.querySelector(`[data-awl-rmlist="${LID}"]`) && /#Privat/.test(o2.box.textContent), 'the state after a reload' + T);
  if (o2.box) {
    click(o2.w, o2.box.querySelector(`[data-awl-rmlist="${LID}"]`));
    check(await until(async () => (await srv()).lists.length === 0), 'a project removed' + T);
    check(await until(() => /No project locked/.test(o2.box.textContent)), 'the empty hint' + T);
  }
  o2.w.close();
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 3});
  const PA = (await call('POST', '/api/my/agents', {username: 'deskbot', display_name: 'Deskbot'})).id;
  const LA = (await call('POST', '/api/lists', {name: 'Diary project'})).id;
  // a person without an organisation (freelancer-matrix: agents)
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.status < 300, 'a person without an organisation ' + fr.status);
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'agents,comments,collab'}, FK);
  const FA = (await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Fridabot'}, FK)).id;
  const LF = (await call('POST', '/api/lists', {name: 'Diary project'}, FK)).id;
  check(FA && LF, 'the freelancer has an own agent and a project');

  await scenario('organisation', 'alice', PA, LA, CK);
  await scenario('without organisation', 'frida', FA, LF, FK);
  console.log(`p2235_b_datalock_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
