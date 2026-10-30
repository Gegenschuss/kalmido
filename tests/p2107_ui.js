// 2.153.0 UI tests (#1962; own container, start.sh), 2.153.0: rescued onto 2.147. jsdom, the agent chat on the phone page:
// - the whole chat: a job is its card; under it the newest results / questions / errors (2.144.0 fold, never repeated in the
//   folded history) and the link "Open the job chat"; the start line and the other messages stay folded in the card
// - the job's own chat: the start line, its messages, its progress lines (grey, in time order); what I type there goes out
//   with job_id AND still "Job N:" in front (hosts that read only the text reach the job), it lands in the job's chat and in
//   the whole chat inside the card, never as an own row
// - messages without job_id stay rows of the whole chat; hit area of the link >= 2.75rem
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2107_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Please build the release'});
  const J = (await v1('POST', '/agent/jobs', {title: 'Knox: Release 2.107 job chat', user_id: me.id, state: 'running', log: 'Started'})).id;
  check(J, 'setup: a job');
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  const m1 = (await say('Knox: building', {job_id: J, job_msg: 'say'})).id;
  await say('Hello, a plain answer');
  await v1('PATCH', `/agent/jobs/${J}`, {append_log: 'Tests green'});
  const mq = (await say('Knox: which colour should the badge have?', {job_id: J, job_msg: 'question'})).id;
  const mr = (await say('✅ Knox: release ready\n- point 1\n- point 2', {job_id: J, job_msg: 'result'})).id;
  check(m1 && mq && mr, 'setup: job messages');

  const w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}), d = w.document;
  const box = () => d.querySelector('#chat-msgs');
  const card = () => d.querySelector(`#chat-msgs .jcd[data-jcd="${J}"]`);
  await until(() => card() && /plain answer/.test(box()?.textContent || ''));

  // ================= the whole chat: one card, the question and the result under it, the link
  check(d.querySelectorAll('#chat-msgs .jcd').length === 1, 'the job = one card');
  const under = () => [...(card()?.querySelectorAll(':scope > .jcdres') || [])];
  check(under().length === 2 && under()[0].querySelector(`[data-mid="a:${mq}"]`) && under()[1].querySelector(`[data-mid="a:${mr}"]`), 'under the card: the question and the result ' + under().length);
  check(/point 2/.test(under()[1]?.textContent || ''), 'the result is shown whole (short: not cut)');
  const go = card()?.querySelector(':scope > .jcsgo');
  check(go && go.dataset.act === 'jc-open' && +go.dataset.jid === J && /To the job chat/.test(go.textContent) && go.querySelector('svg'), 'the link "To the job chat" (2.290.0 B #3145: grey, arrow at the right)');
  const hist = () => card()?.querySelector('.jcdhist');
  check(hist()?.hidden && hist().querySelector('.cnotice') && /Release 2\.107 job chat/.test(hist().querySelector('.cnotice').textContent), 'folded: the start line is in the card');
  check(hist().querySelectorAll(':scope > .cmsg').length === 1, 'folded: the other job message (question and result are not repeated) ' + hist().querySelectorAll(':scope > .cmsg').length);
  check([...box().children].some(x => x.classList.contains('cmsg') && /plain answer/.test(x.textContent)) && box().querySelector(':scope > .cmsg.me'), 'messages without job_id stay rows of the whole chat');
  check(!box().querySelector(':scope > .jcsp'), 'no progress lines in the whole chat');

  // ================= the job's own chat
  click(w, go);
  await until(() => d.querySelector('#jc-bar') && d.querySelector('#chat-msgs .jcsp'));
  check(w.eval('S.chat.job && +S.chat.job.id') === J && d.querySelector('#jc-bar'), 'the link opens the job\'s chat');
  const rows = () => [...box().children];
  const prog = () => rows().filter(x => x.classList.contains('jcsp')).map(x => x.textContent);
  check(prog().join('|') === 'Started|Tests green', 'the progress lines in the job\'s chat ' + prog().join('|'));
  const idx = t => rows().findIndex(x => x.textContent.includes(t));
  check(idx('Started') < idx('Knox: building') && idx('Knox: building') < idx('Tests green') && idx('Tests green') < idx('which colour'), 'progress lines stand in time order between the messages');
  check(rows().some(x => x.classList.contains('cnotice') && /Release 2\.107 job chat/.test(x.textContent)), 'the start line is a row of the job\'s chat');
  check(!rows().some(x => /plain answer/.test(x.textContent)) && !d.querySelector('#chat-msgs .jcd'), 'the job\'s chat: no plain message, no cards');
  check(/release ready/.test(box().textContent) && /point 2/.test(box().textContent), 'the job\'s chat shows the whole result');

  // ================= typing in the job's chat
  const sent = [];
  const of = w.rawFetch; w.rawFetch = (m, u, b) => { if (m === 'POST' && /\/chat$/.test(u)) sent.push(b); return of(m, u, b); };
  const ci = d.querySelector('#chat-in');
  check(/Message to Knox/.test(ci?.placeholder || ''), 'the box addresses the job ' + ci?.placeholder);
  ci.value = 'Job ' + J + ': blue please'; await w.eval('chatSend()');
  await until(() => sent.length && rows().some(x => /blue please/.test(x.textContent)));
  check(sent[0]?.job_id === J && sent[0]?.body === `Job ${J}: blue please`, 'sent with job_id, a typed "Job N:" kept once ' + JSON.stringify(sent[0]));
  ci.value = 'and a bigger font'; await w.eval('chatSend()');
  await until(() => sent.length > 1 && rows().some(x => /bigger font/.test(x.textContent)));
  check(sent[1]?.job_id === J && sent[1]?.body === `Job ${J}: and a bigger font`, 'a plain text: "Job N:" in front, with job_id ' + JSON.stringify(sent[1]));
  const srv = await call('GET', `/api/agents/${CL}/chat?job=${J}`);
  check(srv.messages.filter(m => m.from === 'user' && m.job_id === J).map(m => m.body).join('|') === `Job ${J}: blue please|Job ${J}: and a bigger font`, 'the server stored both with the job');
  w.rawFetch = of;

  // ================= back to the whole chat: my job messages are inside the card
  click(w, d.querySelector('[data-act="jc-back"]'));
  await until(() => card() && !d.querySelector('#jc-bar'));
  check(card() && !rows().some(x => x.classList.contains('cmsg') && /blue please|bigger font/.test(x.textContent)), 'the whole chat: my messages to the job are no own rows');
  check([...(hist()?.querySelectorAll(':scope > .cmsg.me') || [])].map(x => x.textContent).join('|').includes('blue please'), 'they are folded in the job\'s card');

  // ================= the prefix stays the second way in the whole chat
  check(w.eval(`jc_send('Knox: hi')`) === 'Knox: hi', 'outside a job\'s chat nothing is changed (the prefix stays the second way)');

  // ================= phone: hit areas
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'agentchat.css'), 'utf8');
  const blk = css.slice(css.indexOf('/* 2.153.0 (#1962)'));
  const rule = s2 => (new RegExp(s2.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{([^}]*)\\}').exec(blk) || [])[1] || '';
  check(/min-height:2\.75rem/.test(rule('.jcsgo')), 'the link: min-height 2.75rem (44 px)');
  check(/color:var\(--muted\)/.test(rule('.jcsgo')) && /align-self:flex-end/.test(rule('.jcsgo')) && /color:var\(--accent\)/.test((/\.jcsgo:hover,\.jcsgo:focus-visible\{([^}]*)\}/.exec(blk) || [])[1] || ''), 'the link: grey at the right, accent only on hover / focus (2.290.0 B #3145)');
  const plain = blk.replace(/\/\*[\s\S]*?\*\//g, '');
  check(!/(?<![\d.])([3-9]|\d{2,})px/.test(plain) && !/#[0-9a-f]{3,6}\b/i.test(plain), 'CSS: rem sizes, no new colours');

  console.log(`p2107_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
