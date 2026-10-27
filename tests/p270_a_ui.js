// 2.70.0 UI tests of part A (#1354; own container, start.sh). jsdom, phone page:
// - the chat with an agent that takes my proposal requests has "Turn a meeting into tasks" next to the clip; an agent with
//   proposals off has none
// - the button opens "Tasks from notes" with THIS agent chosen, a list choice (lists I may write in, never a health list),
//   the photo button (accept image/*); Ask = a request of kind extract to that agent for the chosen list
// - the agent's proposal shows as ONE card in the chat: every task with assignee and date, a tick each; untick one,
//   "Create 1 task" creates only the ticked one (as me) and the card goes; Discard on a second card asks and removes it
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P270A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body, tok = TOK) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const dbx = (sql, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]).toString() || '[]');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const mk = async name => { const a = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: name, display_name: name[0].toUpperCase() + name.slice(1)}); await call('PATCH', `/api/admin/agents/${a.id}`, {org_id: ORG}); return a; };
  const ag = await mk('claude'), ot = await mk('otto');
  const CL = ag.id, OT = ot.id; TOK = ag.token;
  const W = (await call('POST', '/api/lists', {name: 'Shoot', org_id: ORG})).id;
  const W2 = (await call('POST', '/api/lists', {name: 'Office', org_id: ORG})).id;
  const HL = (await call('POST', '/api/lists', {name: 'Doctor'})).id;
  dbx("UPDATE lists SET life='health' WHERE id=?", [HL]);
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  const r2 = await call('PUT', `/api/lists/${W2}/members`, {user_id: OT, role: 'edit'});
  if (r2.status >= 400) dbx("INSERT INTO list_members(list_id,user_id,role,own_role,sort,added_at) VALUES(?,?,?,?,0,'2026-01-01T00:00:00+00:00')", [W2, OT, 'edit', 'edit']);
  await call('PATCH', `/api/admin/agents/${OT}`, {proposals: 'off'});
  check(!((await call('GET', '/api/proposals/agents')).agents || []).some(a => a.id === OT), 'setup: otto takes no proposal requests');
  await call('POST', `/api/agents/${OT}/chat`, {body: 'hello otto'});

  // ================= the entry in the chat
  let w = await boot({user: 'alice', hash: `agents/${OT}`, mobile: true}), d = w.document;
  await until(() => d.querySelector('#chat-in'));
  await sleep(300);
  check(d.querySelector('#chat-in') && !d.querySelector('.mtgbtn'), 'no entry for an agent with proposals off');
  w.close();
  w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}); d = w.document;
  const btn = await until(() => d.querySelector('.chcomp .mtgbtn'));
  check(btn && /Turn a meeting into tasks/.test(btn.getAttribute('aria-label') || ''), 'the chat offers "Turn a meeting into tasks"');
  click(w, btn);
  const md = await until(() => d.querySelector('.modal.mtgreq'));
  check(md && /Tasks from notes/.test(md.textContent), 'the dialog opens');
  check(md?.querySelector('#pp-agent')?.type === 'hidden' && +md.querySelector('#pp-agent').value === CL, 'this agent is chosen');
  const opts = [...(md?.querySelectorAll('#mtg-list option') || [])].map(o => +o.value);
  check(opts.includes(W) && opts.includes(W2) && !opts.includes(HL), 'the list choice: my lists, no health list ' + JSON.stringify(opts));
  const fi = md?.querySelector('#mtg-file');
  check(fi && fi.accept === 'image/*' && fi.multiple, 'the photo button takes images (camera on the phone)');
  check(/Claude/.test(md?.querySelector('#pp-priv')?.textContent || ''), 'the consent line names the agent');
  // nothing typed, no photo: the request is not sent
  click(w, md.querySelector('[data-m="ok"]'));
  await sleep(300);
  check(d.querySelector('.modal.mtgreq') && !((await call('GET', `/api/agents/jobs?agent_id=${CL}&state=open`)).jobs || []).length, 'empty: nothing is sent');
  md.querySelector('#mtg-list').value = String(W); md.querySelector('#mtg-list').dispatchEvent(new w.Event('change', {bubbles: true}));
  md.querySelector('#pp-text').value = 'Alice books the studio by Friday. Someone orders pizza.';
  click(w, md.querySelector('[data-m="ok"]'));
  const job = await until(async () => ((await call('GET', `/api/agents/jobs?agent_id=${CL}&state=open`)).jobs || []).find(j => j.kind === 'extract'));
  check(job, 'Ask = an extract request to this agent');
  const inp = job ? (await v1('GET', `/agent/jobs/${job.id}`)).input : {};
  check(inp?.list?.id === W && /books the studio/.test(inp?.text || ''), 'for the chosen list with the notes');
  await until(() => !d.querySelector('.modal.mtgreq'));
  // a photo only (no text): stored in this chat, the request carries it
  click(w, d.querySelector('.chcomp .mtgbtn'));
  const m2 = await until(() => d.querySelector('.modal.mtgreq'));
  const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
  Object.defineProperty(m2.querySelector('#mtg-file'), 'files', {configurable: true, value: [new w.File([PNG], 'board.png', {type: 'image/png'})]});
  m2.querySelector('#mtg-file').dispatchEvent(new w.Event('change', {bubbles: true}));
  check(/board\.png/.test(m2.querySelector('#mtg-imgs')?.textContent || '') && /1 image/.test(m2.querySelector('#pp-priv').textContent), 'the photo is listed, the consent line names it');
  click(w, m2.querySelector('[data-m="ok"]'));
  const job2 = await until(async () => ((await call('GET', `/api/agents/jobs?agent_id=${CL}&state=open`)).jobs || []).find(j => j.kind === 'extract' && j.id !== job?.id));
  const inp2 = job2 ? (await v1('GET', `/agent/jobs/${job2.id}`)).input : {};
  check((inp2?.images || []).length === 1 && inp2.images[0].name === 'board.png' && inp2.text === '', 'photo only: the request carries the image ' + JSON.stringify(inp2).slice(0, 200));
  check(((await call('GET', `/api/agents/${CL}/chat`)).messages || []).some(m => (m.attachments || []).some(a => a.name === 'board.png')), 'the photo is in my chat with the agent');
  if (job2) await call('POST', `/api/proposals/${job2.id}/discard`);
  w.close();

  // ================= the card
  check((await v1('POST', `/agent/jobs/${job.id}/proposal`, {summary: 'Two things', tasks: [{title: 'Book the studio', assignee_id: me.id, due: '2031-02-07'}, {title: 'Order pizza'}]})).status === 201, 'the agent proposes two tasks');
  w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}); d = w.document;
  const card = await until(() => d.querySelector(`#chat-mtg .mtgcard[data-jid="${job.id}"]`));
  check(card && /2 tasks from the meeting/.test(card.textContent) && card.querySelectorAll('.mtgl li').length === 2, 'one card with both tasks');
  check(/Alice/.test(card?.querySelector('.mtgl li')?.textContent || '') && card.querySelectorAll('[data-mtg="tick"]:checked').length === 2, 'assignee shown, both ticked');
  const t2 = card.querySelectorAll('[data-mtg="tick"]')[1];
  t2.checked = false; t2.dispatchEvent(new w.Event('change', {bubbles: true}));
  const ap = card.querySelector('[data-mtg="apply"]');
  check(/Create 1 task/.test(ap.textContent) && !ap.disabled, 'unticked: "Create 1 task"');
  click(w, ap);
  await until(() => !d.querySelector(`#chat-mtg .mtgcard[data-jid="${job.id}"]`));
  check(!d.querySelector(`#chat-mtg .mtgcard[data-jid="${job.id}"]`), 'the card goes after apply');
  const made = dbx('SELECT title, created_by, assignee_id FROM tasks WHERE list_id=? AND deleted_at IS NULL ORDER BY id', [W]);
  check(made.length === 1 && made[0].title === 'Book the studio' && made[0].created_by === me.id && made[0].assignee_id === me.id, 'only the ticked task, created as me ' + JSON.stringify(made));
  w.close();

  // ================= discard
  const j2 = await call('POST', '/api/proposals', {agent_id: CL, kind: 'extract', list_id: W, text: 'Call the venue'});
  await v1('POST', `/agent/jobs/${j2.id}/proposal`, {tasks: [{title: 'Call the venue'}]});
  w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}); d = w.document;
  const c2 = await until(() => d.querySelector(`#chat-mtg .mtgcard[data-jid="${j2.id}"]`));
  check(c2 && /1 task from the meeting/.test(c2.textContent), 'a second card');
  if (c2) click(w, c2.querySelector('[data-mtg="discard"]'));
  const yes = await until(() => [...d.querySelectorAll('.modal button')].find(b => /^Discard$/.test(b.textContent.trim()) && !b.closest('.mtgcard')));
  if (yes) click(w, yes);
  await until(() => !d.querySelector(`#chat-mtg .mtgcard[data-jid="${j2.id}"]`));
  check(!d.querySelector(`#chat-mtg .mtgcard[data-jid="${j2.id}"]`) && (await call('GET', `/api/proposals/${j2.id}`)).state === 'discarded', 'Discard asks, then the card goes');
  w.close();

  console.log(`p270_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
