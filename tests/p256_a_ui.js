// 2.56.0 UI tests of part A (#1791, #1793; own container, start.sh). jsdom:
// - #1791 the Agents view: "Message" only on a running job's card; the dialog keeps Send off while empty; Send = the
//   agent gets the 'job' event {action: message, text}; the job stays running
// - #1793 the agent chat (phone page): a job's tag shows its name, a tap opens the job's own history (bar with name +
//   title, only the job's messages), the box sends "Job N: …", Back leads to the whole chat; the name at the start of a
//   job's message is the same link; an ended job: the bar says so, the box is off
// - the agent menu of the top bar lists the running job with its name and title
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P256A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  const JA = (await v1('POST', '/agent/jobs', {title: 'Clara: Release 1.0', user_id: me.id})).id;
  const JD = (await v1('POST', '/agent/jobs', {title: 'Ben: Old release', user_id: me.id})).id;
  check(JA && JD, 'setup: two jobs');
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  await say(`Job #${JA} started`, {job_id: JA});
  await say('Hello, how can I help?');
  await say('Clara: halfway there', {job_id: JA});
  await say(`Job #${JD} started`, {job_id: JD});
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Clara: please hurry'});
  await v1('PATCH', `/agent/jobs/${JD}`, {state: 'done'});
  let cur = (await v1('GET', '/agent/events?since=0&limit=500')).cursor;

  // ================= #1791 the card
  let w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  const card = await until(() => d.querySelector(`#job-${JA}`));
  check(card?.querySelector('[data-act="jc-msg"]'), '#1791: a running job has "Message"');
  check(!d.querySelector(`#job-${JD} [data-act="jc-msg"]`), '#1791: an ended job has none');
  click(w, card.querySelector('[data-act="jc-msg"]'));
  const md = await until(() => d.querySelector('.modal #jc-text') && d.querySelector('.modal'));
  const yes = md?.querySelector('[data-cd="yes"]'), ta = md?.querySelector('#jc-text');
  check(/Message to Clara/.test(md?.textContent || ''), '#1791: the dialog names the job');
  await sleep(100);
  check(yes?.disabled && d.querySelector('.modal #jc-text'), '#1791: Send stays off while the text is empty');
  ta.value = 'Please also update the guide.'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(!yes.disabled, '#1791: text typed: Send is on');
  click(w, yes);
  const ev = await until(async () => { const r = await v1('GET', `/agent/events?since=${cur}&limit=500`); return (r.data || []).find(e => (e.event || e.type) === 'job'); }, 40);
  const pl = ev ? (ev.data || ev.payload || ev) : {};
  check(pl.action === 'message' && pl.text === 'Please also update the guide.' && (pl.job || {}).id === JA, '#1791: the agent got the message ' + JSON.stringify(pl).slice(0, 200));
  check((await call('GET', `/api/agents/jobs?id=${JA}`)).jobs?.[0]?.state === 'running', '#1791: the job keeps running');
  w.close();

  // ================= #1793 the job's own history (phone page)
  w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}); d = w.document;
  const tag = await until(() => { const t = d.querySelector(`#chat-msgs button.jobtag[data-jid="${JA}"]`); return t && /Clara/.test(t.textContent) && t; });
  check(tag, '#1793: the tag of a job message shows its name ' + (d.querySelector('#chat-msgs .jobtag')?.textContent || 'none'));
  const nm = d.querySelector(`#chat-msgs .jc-name[data-jid="${JA}"]`);
  check(nm && nm.textContent === 'Clara', '#1793: the name at the start of the job\'s message is a link');
  check(!/Hello/.test(d.querySelector('#chat-msgs .jc-name')?.closest('.cmsg')?.textContent || ''), '#1793: no link in a message of no job');
  click(w, tag);
  const bar = await until(() => d.querySelector('#jc-bar'));
  check(bar && /Clara/.test(bar.textContent) && /Release 1\.0/.test(bar.textContent), '#1793: the bar shows name + title');
  await until(() => /please hurry/.test(d.querySelector('#chat-msgs')?.textContent || ''));
  const txt = d.querySelector('#chat-msgs')?.textContent || '';
  check(/halfway there/.test(txt) && /please hurry/.test(txt) && !/Hello, how can I help/.test(txt) && !new RegExp(`Job #${JD} started`).test(txt), '#1793: only the job\'s messages ' + txt.slice(0, 200));
  const ci = d.querySelector('#chat-in');
  check(ci && !ci.disabled && /Clara/.test(ci.placeholder), '#1793: the box writes to the job');
  ci.value = 'one more thing'; ci.dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, d.querySelector('[data-act="chat-send"]'));
  const sent = await until(async () => ((await call('GET', `/api/agents/${CL}/chat`)).messages || []).find(m => m.from === 'user' && /one more thing/.test(m.body)));
  // 2.56.0 review: the box addresses the job by its number (a title like "Release: 2.56" is no name the service knows)
  check(sent?.body === `Job ${JA}: one more thing`, '#1793: sent as "Job N: …" ' + (sent?.body || ''));
  await until(() => /one more thing/.test(d.querySelector('#chat-msgs')?.textContent || ''));
  check(/one more thing/.test(d.querySelector('#chat-msgs')?.textContent || ''), '#1793: the message shows in the job\'s history');
  click(w, d.querySelector('#jc-bar [data-act="jc-back"]'));
  await until(() => !d.querySelector('#jc-bar') && /Hello, how can I help/.test(d.querySelector('#chat-msgs')?.textContent || ''));
  check(!d.querySelector('#jc-bar') && /Hello, how can I help/.test(d.querySelector('#chat-msgs')?.textContent || ''), '#1793: Back = the whole chat again');
  // an ended job: history yes, box off; the phone's Back in the header leaves the job first
  const tagD = await until(() => d.querySelector(`#chat-msgs button.jobtag[data-jid="${JD}"]`));
  click(w, tagD);
  await until(() => /Job has ended/.test(d.querySelector('#jc-bar')?.textContent || ''));
  check(/Ben/.test(d.querySelector('#jc-bar')?.textContent || '') && /Job has ended/.test(d.querySelector('#jc-bar')?.textContent || ''), '#1793: an ended job: the bar says so');
  check(d.querySelector('#chat-in')?.disabled, '#1793: ... and the box is off');
  click(w, d.querySelector('.chath [data-act="chat-close"]'));
  await until(() => !d.querySelector('#jc-bar'));
  check(!d.querySelector('#jc-bar') && d.querySelector('#chat-msgs'), '#1793: the header\'s Back leaves the job\'s history, the chat stays');
  // ================= the agent menu
  await w.jc_sync(true);
  const items = w.jc_menuItems().map(x => x.label);
  check(items.some(l => l === 'Clara · Release 1.0') && !items.some(l => /Ben/.test(l)), '#1793: the agent menu lists the running job only ' + JSON.stringify(items));
  w.close();

  // ================= desktop: the side panel switches to the job's history and back
  w = await boot({user: 'alice'}); d = w.document;
  w.chatOpen(CL, {float: false});
  const tagP = await until(() => d.querySelector(`#achat button.jobtag[data-jid="${JA}"]`));
  check(tagP, 'desktop: the panel shows the job tag');
  if (tagP) click(w, tagP);
  await until(() => d.querySelector('#achat #jc-bar'));
  check(/Clara/.test(d.querySelector('#achat #jc-bar')?.textContent || '') && !/Hello, how can I help/.test(d.querySelector('#achat #chat-msgs')?.textContent || ''), 'desktop: the panel shows the job\'s history');
  const bk = d.querySelector('#achat [data-act="jc-back"]'); if (bk) click(w, bk);
  await until(() => !d.querySelector('#achat #jc-bar') && /Hello, how can I help/.test(d.querySelector('#achat #chat-msgs')?.textContent || ''));
  check(!d.querySelector('#achat #jc-bar') && d.querySelector('#achat:not(.hidden)'), 'desktop: Back = the whole chat in the panel');
  w.close();

  console.log(`p256_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
