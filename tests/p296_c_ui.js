// 2.96.0 UI tests of part C (#2015; own container, start.sh). jsdom, the agent chat on the phone page:
// - three messages of a job = ONE card (name, version, state, the newest first line); folded by default, a tap unfolds the
//   three messages (indented), the state is kept per device
// - a new message of the job updates the card in place (last line), the card stays unfolded; the state follows the job
// - the end result ("✅ …" without job_msg = recognised from the text) and an error stay visible under the card as one
//   short line each (2.107.0, #1962: the whole text folded in the card); a message with buttons is never inside a card
// - the filter All / Only me and <agent> / Jobs (buttons + a menu for the phone), kept per device; no job = no filter
// - a search hit in a folded card unfolds it (jcd_reveal); hit areas >= 2.75rem (44 px) on the phone (CSS)
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P296C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
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
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  const J = (await v1('POST', '/agent/jobs', {title: 'Knox: Release 2.96 job cards', user_id: me.id, state: 'running'})).id;
  check(J, 'setup: a job');
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Please build the release'});
  const m1 = (await say('Knox: started the build', {job_id: J, job_msg: 'say'})).id;
  await say('Hello, a plain answer');
  const m2 = (await say('Knox: tests are running', {job_id: J})).id;
  const m3 = (await say('Knox: halfway there\nsecond line', {job_id: J, job_msg: 'say'})).id;
  check(m1 && m2 && m3, 'setup: three job messages');

  const w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}), d = w.document;
  const box = () => d.querySelector('#chat-msgs');
  const card = () => d.querySelector(`#chat-msgs .jcd[data-jcd="${J}"]`);
  await until(() => card() && /plain answer/.test(box()?.textContent || ''));

  // ================= one card per job
  check(d.querySelectorAll('#chat-msgs .jcd').length === 1, 'three messages of a job = one card ' + d.querySelectorAll('#chat-msgs .jcd').length);
  const c0 = card();
  check(c0?.querySelector('.jcdt b')?.textContent === 'Knox' && c0.querySelector('.jcdv')?.textContent === '2.96', 'the card: name + version ' + c0?.querySelector('.jcdt')?.textContent);
  check(c0?.querySelector('.jcdst.st-running')?.textContent === 'running', 'the card: state running (from the job) ' + c0?.querySelector('.jcdst')?.outerHTML);
  check(c0?.querySelector('.jcdl')?.textContent === 'Knox: halfway there', 'the card: the first line of the newest message ' + c0?.querySelector('.jcdl')?.textContent);
  const hist = () => card()?.querySelector('.jcdhist');
  check(hist()?.hidden && hist().querySelectorAll(':scope > .cmsg').length === 3, 'folded: the three messages are hidden under the card');
  check([...box().children].indexOf(card()) > [...box().children].findIndex(x => /plain answer/.test(x.textContent)), 'the card stands at the place of the newest job message');
  check(box().querySelector(':scope > .cmsg.me') && [...box().querySelectorAll(':scope > .cmsg.ag')].some(x => /plain answer/.test(x.textContent)), 'my message and the plain answer stay rows of the chat');
  check(d.querySelector('#chat-msgs [data-mid="a:' + m2 + '"]')?.querySelector('.jobtag'), 'the folded rows keep their job tag (job history, search)');

  // ================= unfold / fold
  click(w, card().querySelector('button.jcdh'));
  await until(() => hist() && !hist().hidden);
  check(!hist().hidden && card().classList.contains('open') && card().querySelector('.jcdh').getAttribute('aria-expanded') === 'true', 'a tap unfolds the card');
  check([...hist().querySelectorAll(':scope > .cmsg')].map(x => x.dataset.mid).join() === [m1, m2, m3].map(x => 'a:' + x).join(), 'unfolded: the three messages in order (indented in .jcdhist)');
  check(w.eval(`!!LS.get('jcdOpen', {})[${J}]`), 'the open card is kept per device');

  // ================= a new message updates the card in place
  const m4 = (await say('Knox: packaging now', {job_id: J, job_msg: 'say'})).id;
  await w.eval('chatLoad()');
  await until(() => card()?.querySelector('.jcdl')?.textContent === 'Knox: packaging now');
  check(d.querySelectorAll('#chat-msgs .jcd').length === 1 && card().querySelector('.jcdl').textContent === 'Knox: packaging now', 'a new job message: still one card, the last line follows');
  check(!hist().hidden && hist().querySelectorAll(':scope > .cmsg').length === 4, 'the card stays unfolded and takes the new message');
  click(w, card().querySelector('button.jcdh'));
  await until(() => hist()?.hidden);
  check(hist().hidden && !w.eval(`!!LS.get('jcdOpen', {})[${J}]`), 'a second tap folds it again');

  // ================= the end result, an error, a question with buttons
  const long = '✅ Knox: release ready\n' + Array.from({length: 9}, (_, i) => `- point ${i + 1}`).join('\n');
  const mr = (await say(long, {job_id: J})).id;
  const mq = (await say('Knox: may I push?', {job_id: J, choices: [{id: 'yes', label: 'Yes'}, {id: 'no', label: 'No'}]})).id;
  await v1('PATCH', `/agent/jobs/${J}`, {state: 'done'});
  await w.eval('chatLoad()');
  await until(() => card()?.querySelector('.jcdst.st-done') && d.querySelector(`#chat-msgs [data-mid="a:${mq}"]`));
  // 2.107.0 (#1962): the end result is a short line under the card (a tap opens the job's chat), the whole text stays
  // folded in the card -- no 5-line block with "Show more" any more
  const res = card()?.querySelector(':scope > .jcsl.k-result');
  check(res && res.querySelector('span')?.textContent === '✅ Knox: release ready', '"✅ …" without job_msg = the end result, one short line under the card');
  check(card().querySelector(`.jcdhist [data-mid="a:${mr}"]`) && !card().querySelector('.jcdres'), 'the whole result is folded in the card');
  check(card().querySelector('.jcdst.st-done')?.textContent === 'finished', 'the state follows the job: finished');
  const q = d.querySelector(`#chat-msgs [data-mid="a:${mq}"]`);
  check(q && q.parentElement === box() && !q.closest('.jcd'), 'a question with buttons of the job stays its own row (never in the card)');
  const me2 = (await say('⚠️ Knox: upload failed', {job_id: J})).id;
  await w.eval('chatLoad()');
  await until(() => card()?.querySelector(':scope > .jcsl.k-error'));
  check(/upload failed/.test(card()?.querySelector(':scope > .jcsl.k-error')?.textContent || ''), '"⚠️ …" = an error, a short line under the card');
  check(hist().querySelectorAll(':scope > .cmsg').length === 6, '2.107.0 (#1962): result and error are folded in the history too');

  // ================= the filter
  // 2.144.0 (#2419): no filter row any more, the header icon (menu) on every width
  check(!d.querySelector('#jcd-filt') && d.querySelector('#jcd-fbtn.jcdfbtn:not([hidden])'), 'with a job: the filter icon in the header, no filter row');
  click(w, d.querySelector('#jcd-fbtn')); await until(() => d.querySelector('[role=menuitem]'));
  check(/Only me and Dev Bot/.test(d.querySelector('[role=menu]')?.textContent || [...d.querySelectorAll('[role=menuitem]')].map(x => x.textContent).join()), 'the filter names the agent');
  click(w, [...d.querySelectorAll('[role=menuitem]')].find(x => /Jobs/.test(x.textContent)));
  await until(() => !/plain answer/.test(box().textContent));
  check(card() && !/plain answer/.test(box().textContent) && !box().querySelector(':scope > .cmsg.me') && d.querySelector(`#chat-msgs [data-mid="a:${mq}"]`), 'Jobs: the card and the question, not the plain answer or my message');
  check(w.eval(`LS.get('jcdFilt')`) === 'jobs', 'the filter is kept per device');
  click(w, d.querySelector('#jcd-fbtn')); await until(() => d.querySelector('[role=menuitem]'));  // 2.117.0 (#2260): the phone icon opens the menu
  check(d.querySelector('#jcd-fbtn .jcdfdot'), 'the icon carries a dot while the filter is not All');
  click(w, [...d.querySelectorAll('[role=menuitem]')].find(x => /Only me/.test(x.textContent)));
  await until(() => !card() && /plain answer/.test(box().textContent));
  // 2.144.0 (#2416): the job's question with plain buttons is a job message (only open approval cards stay, p2144_a_ui)
  check(!card() && /plain answer/.test(box().textContent) && box().querySelector(':scope > .cmsg.me') && !d.querySelector(`#chat-msgs [data-mid="a:${mq}"]`), 'Only me and the agent (the menu): no card, the plain answer, my message, not the job question');
  // a search hit in a job's message: the filter steps aside and the card unfolds
  w.eval(`jcd_reveal(${m2})`);
  await until(() => card() && !hist()?.hidden);
  check(w.eval(`LS.get('jcdFilt')`) === 'all' && card() && !hist().hidden, 'a search hit inside a folded card / behind the filter: All + unfolded');
  click(w, card().querySelector('button.jcdh'));

  // ================= the reading of a message's kind, no job = no filter
  check(w.eval(`jcd_kind({body: '✅ done'})`) === 'result' && w.eval(`jcd_kind({body: '⏰ time limit'})`) === 'error' && w.eval(`jcd_kind({body: '⏹ stopped'})`) === 'error'
        && w.eval(`jcd_kind({body: 'plain'})`) === 'say' && w.eval(`jcd_kind({body: '✅ x', job_msg: 'say'})`) === 'say', 'kind: job_msg first, else the leading sign');
  const html = w.eval(`(() => { const k = S.chat.msgs; S.chat.msgs = [{id: 1, from: 'agent', kind: 'message', body: 'plain', created_at: '2026-10-18T10:00:00Z', reactions: []}, {id: 2, from: 'user', kind: 'message', body: 'mine', created_at: '2026-10-18T10:01:00Z', reactions: []}]; const h = chatMsgs() + jcd_fbtnHtml(); S.chat.msgs = k; chatMsgs(); return h; })()`);
  const tmp = d.createElement('div'); tmp.innerHTML = html;
  check(!tmp.querySelector('.jcd') && tmp.querySelector('#jcd-fbtn')?.hidden && tmp.querySelectorAll('.cmsg').length === 2, 'no job in the chat: no card, no filter, rows as before');

  // ================= phone: hit areas of the card and the filter >= 2.75rem (44 px at 16 px)
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'agentchat.css'), 'utf8');
  const blk = css.slice(css.indexOf('/* 2.96.0 C (#2015)'));
  const rule = sel2 => (new RegExp(sel2.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{([^}]*)\\}').exec(blk) || [])[1] || '';
  check(/min-height:2\.75rem/.test(rule('.jcdh')) && /min-height:2\.75rem/.test(rule('.jcdfbtn')) && /min-height:2\.75rem/.test(rule('.jcdmore')), 'card, menu and "Show more": min-height 2.75rem (44 px)');
  check(/\.jcdfbtn\{[^}]*display:inline-flex/.test(blk) && !/\.jcdseg/.test(blk), 'the header icon on every width, no filter buttons');  // 2.144.0 (#2419)
  const plain = blk.replace(/\/\*[\s\S]*?\*\//g, '').replace('max(1rem,16px)', '').replace(/linear-gradient\(#000 70%,transparent\)/g, '');  // the mask's black is no colour
  check(!/(?<![\d.])([3-9]|\d{2,})px/.test(plain) && !/#[0-9a-f]{3,6}\b/i.test(plain), 'CSS: rem sizes, no new colours');

  console.log(`p296_c_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
