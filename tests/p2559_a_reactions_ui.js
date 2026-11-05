// 2.559.0 UI tests, part A (#4659): an emoji reaction shows at once (optimistic like #1501), jsdom, invented data:
// kalmido-suite: fresh
// - on a comment (agents.js commentReact): the reaction is marked as mine while the answer is still held; the request says
//   on: true; the server follows; a refusal (409) takes it back with the message; tapping again takes it off at once
// - in the agent chat (agentchat.js chatReact): the same; a refusal (500) takes it back
// - no GET /api/state follows a reaction
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, idle, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
// requests matching re ("METHOD /url") wait in w.__held until go() / fail(text, status); every request lands in w.__log
// the live update's poll (GET /api/version every 4 s) waits while a test holds requests, so a GET /api/state it would start
// (its retry after a crossing write has no auto=1) is never mistaken for a consequence of the action; what is still on its
// way (a timeline the poll asked for) arrives before the action
const hold = async (w, re) => {
  if (w.__f1) w.fetch = w.__f1;  // the parked polls of a hold before go on first
  for (const v of w.__vers || []) v();
  await until(() => !w.eval('td_polling'));
  w.__held = []; w.__log = []; w.__resp = []; w.__vers = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => { const k = `${o.method || 'GET'} ${u}`; w.__log.push(k);
    if (/^GET \/api\/version\b/.test(k)) return new Promise(res => w.__vers.push(() => res(f1(u, o))));
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), body: o.body, go: () => res(f1(u, o)), fail: (msg, st = 409) => res(new Response(JSON.stringify({error: msg}), {status: st, headers: {'content-type': 'application/json'}}))})) : f1(u, o); };
  await idle(w);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; for (const v of w.__vers || []) v(); w.__vers = []; };
const noState = w => !w.__log.some(k => /^GET \/api\/state\b/.test(k) && !/[?&]auto=1/.test(k));  // auto=1 = the live update's poll, no consequence of the action
const FEAT = 'collab,agents,comments';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['agents', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call(CA, 'GET', '/api/state')).me.id;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['write'], username: 'helper', display_name: 'Helper'});
  const AG = ag.id, TOK = ag.token;
  const P = (await call(CA, 'POST', '/api/lists', {name: 'Website', kind: 'project'})).id;
  await call(CA, 'PUT', `/api/lists/${P}/members`, {user_id: AG, role: 'edit'});
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Landing page', list_id: P})).id;
  await tcall('GET', '/agent/events?since=0', TOK);
  const cm = await tcall('POST', `/tasks/${T}/comments`, TOK, {body: 'First draft is ready'});
  const CID = cm.id;
  check(CID > 0, 'the agent commented: ' + CID);
  const rxOf = async () => ((await call(CA, 'GET', `/api/tasks/${T}/timeline`)).comments || []).find(c => c.id === CID)?.reactions || [];
  const mineOn = rs => rs.some(x => x.emoji === 'up' && (x.users || []).some(u => u.id === ME));

  const w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  w.eval(`openDetail(${T})`);
  check(await until(() => d.querySelector(`#d-tl [data-act="c-react"][data-cid="${CID}"][data-e="up"]`)), 'the comment shows its reaction buttons');
  const onBtn = () => d.querySelector(`#d-tl .rx.on[data-act="c-react"][data-cid="${CID}"][data-e="up"]`);

  // ================= a comment reaction at once
  await hold(w, /^POST \/api\/comments\/\d+\/reactions$/);
  w.eval(`window.__p = commentReact(${CID}, 'up')`);
  check(await until(() => w.__held.length === 1), 'comment: the request is held');
  check(await until(() => onBtn()), 'comment: 👍 is marked as mine before the answer');
  check(JSON.parse(w.__held[0].body || '{}').on === true, 'comment: the request says on: true');
  check(!mineOn(await rxOf()), 'comment: the server has none yet');
  w.__held[0].go(); await w.eval('window.__p');
  check(await until(async () => mineOn(await rxOf())), 'comment: the server follows');
  check(await until(() => onBtn()), 'comment: still marked after the answer: ' + w.eval(`JSON.stringify(tlComment(${CID})?.reactions)`));
  check(noState(w), 'comment: no GET /api/state: ' + w.__log.join(' | '));

  // ================= taking it off at once; a refusal puts it back
  await hold(w, /^POST \/api\/comments\/\d+\/reactions$/);
  w.eval(`window.__p = commentReact(${CID}, 'up')`);
  check(await until(() => w.__held.length === 1 && !onBtn()), 'comment off: unmarked before the answer: ' + w.eval(`JSON.stringify(tlComment(${CID})?.reactions)`) + ' ' + w.__held.length);
  check(JSON.parse(w.__held[0].body || '{}').on === false, 'comment off: the request says on: false');
  w.__held[0].fail('Refused for the test', 409);
  check(await until(() => onBtn()), 'comment off refused: marked again');
  check(await until(() => /Refused for the test/.test(d.querySelector('#toast')?.textContent || '')), 'comment off refused: with the server\'s message');
  check(mineOn(await rxOf()) && noState(w), 'comment off refused: the server keeps it, no reload: ' + w.__log.join(' | '));
  unhold(w);

  // ================= the agent chat
  const sent = await tcall('POST', `/agent/chats/${ME}`, TOK, {body: 'The page is online'});
  check(sent.http < 300, 'the agent wrote in the chat');
  w.eval(`chatOpen(${AG})`);
  check(await until(() => w.eval(`S.chat.msgs.some(m => m.from === 'agent')`) && d.querySelector('#chat-msgs .cmsg.ag')), 'the chat shows the agent\'s message');
  const MID = w.eval(`[...S.chat.msgs].reverse().find(m => m.from === 'agent').id`);
  const chatOn = () => d.querySelector(`#chat-msgs .rx.on[data-act="chat-react"][data-mid="${MID}"][data-e="heart"]`);
  await hold(w, /^POST \/api\/agents\/\d+\/chat\/\d+\/reactions$/);
  w.eval(`window.__p = chatReact(${MID}, 'heart')`);
  check(await until(() => w.__held.length === 1 && chatOn()), 'chat: ❤️ is marked as mine before the answer');
  w.__held[0].fail('Server trouble', 500);
  check(await until(() => !chatOn()), 'chat refused (500): unmarked again');
  await w.eval('window.__p');
  await hold(w, /^POST \/api\/agents\/\d+\/chat\/\d+\/reactions$/);
  w.eval(`window.__p = chatReact(${MID}, 'heart')`);
  check(await until(() => w.__held.length === 1 && chatOn()), 'chat again: marked at once');
  w.__held[0].go(); await w.eval('window.__p');
  check(chatOn() && w.eval(`S.chat.msgs.find(m => m.id === ${MID}).reactions.some(r => r.emoji === 'heart')`), 'chat: the answer keeps it');
  check(noState(w), 'chat: no GET /api/state');
  unhold(w);
  w.close();

  console.log(`p2559_a_reactions_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
