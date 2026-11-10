// 2.826.0 A UI test (#5509): "not connected" only for a real problem. Own container (start.sh), jsdom.
// kalmido-suite: fresh
// freelancer-matrix: agents (alice runs the instance without an organisation, her agent is private to her)
// Invented people only. The agent payload (GET /api/agents) has pending_age: seconds the oldest chat message to the agent waits
// unfetched and unanswered (null = nothing waits). The app:
// - an agent that never got in touch: "not connected" (as before, K08)
// - got in touch, then 5 minutes quiet, nothing waits (an agent that starts on demand): "ready" with a calm dot and the hint
//   "starts with the next message" in the chat header (before: "not connected")
// - a message waits unfetched: pending_age is a number; over 5 minutes (counted on the client): "not connected"
// - the agent fetches its chats: nothing waits any more (pending_age null) -> "ready"
// - the agent answers without fetching (a webhook / a starter that read the event): answered = nothing waits
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, idle} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const {shareAny} = require('./legacy');
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, o) => require('./boot').until(fn, o);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en'});
  const me = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'cloudy', display_name: 'Cloudy'});
  check(ag.id && ag.token, 'an agent with a token');
  const L = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  await shareAny(call, DATA, L, ag.id, 'edit');
  const mine = async () => (await call('GET', '/api/agents')).agents.find(a => a.id === ag.id);

  // never in touch: not connected (unchanged)
  let a = await mine();
  check(a && a.contact_age === null && a.pending_age === null, 'never in touch: contact_age and pending_age null ' + JSON.stringify({c: a?.contact_age, p: a?.pending_age}));
  let w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  w.eval(`chatOpen(${ag.id})`); await idle(w);
  const st = () => d.querySelector('#chat-st');
  check(await until(() => st() && /not connected/.test(st().textContent) && st().querySelector('.adot.st-offline')), 'never in touch: the chat header says "not connected": ' + st()?.textContent);
  w.close();

  // in touch once (an API call), then quiet for over 5 minutes with nothing waiting: ready + "starts with the next message"
  check((await v1(ag.token, 'GET', '/agent/chats')).status === 200, 'the agent reads its chats once (its contact)');
  a = await mine();
  check(a.contact_age !== null && a.pending_age === null, 'in touch, nothing waits: pending_age null');
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  w.eval(`chatOpen(${ag.id})`); await idle(w);
  w.eval('S.agentsAt = Date.now() - 400000; agentLive()');  // 400 s later, counted on the client
  check(await until(() => st() && /ready/.test(st().textContent) && !/not connected/.test(st().textContent)), '#5509: quiet for over 5 minutes, nothing waits: "ready" (was "not connected"): ' + st()?.textContent);
  check(st().querySelector('.adot.st-idle.stby') && /starts with the next message/.test(st().querySelector('.chstx')?.title || ''), 'a calm dot and the hint "starts with the next message": ' + (st().querySelector('.chstx')?.title || ''));
  check(/starts with the next message/.test(w.eval(`agentHstLine(agentById(${ag.id}))`)), 'the dots elsewhere (sidebar, list) name the hint too');
  w.close();

  // a message waits unfetched: a number; over 5 minutes: not connected
  check((await call('POST', `/api/agents/${ag.id}/chat`, {body: 'Can you water the tomatoes?'})).status < 300, 'alice writes to the agent');
  a = await mine();
  check(typeof a.pending_age === 'number' && a.pending_age >= 0 && a.pending_age < 120, 'a message waits: pending_age = its age in seconds ' + a.pending_age);
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  w.eval(`chatOpen(${ag.id})`); await idle(w);
  check(await until(() => /Can you water the tomatoes\?/.test(d.querySelector('#achat')?.textContent || '')), 'her message is in the chat');
  check(!/not connected/.test(st().textContent), 'a fresh message: not yet "not connected"');
  w.eval('S.agentsAt = Date.now() - 400000; agentLive()');
  check(await until(() => /not connected/.test(st().textContent) && st().querySelector('.adot.st-offline')), '#5509: the message waits for over 5 minutes: "not connected": ' + st().textContent);
  w.close();

  // the agent fetches it: nothing waits
  const got = await v1(ag.token, 'GET', '/agent/chats');
  check((got.data || []).some(m => /tomatoes/.test(m.body || '')), 'the agent fetched the message');
  a = await mine();
  check(a.pending_age === null, 'fetched: pending_age null again');
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  w.eval(`chatOpen(${ag.id})`); await idle(w);
  w.eval('S.agentsAt = Date.now() - 400000; agentLive()');
  check(await until(() => /ready/.test(st().textContent) && !/not connected/.test(st().textContent)), 'fetched, then quiet: "ready" again: ' + st().textContent);
  w.close();

  // answered through the API only (no event poll, a starter on demand): "ready", not "connected, but no service running" (#933)
  a = await mine();
  check(a.no_service === true && a.pending_age === null, 'API calls, no event poll: the server still reports no_service (#933), nothing waits');
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  w.eval(`chatOpen(${ag.id})`); await idle(w);
  check(await until(() => st() && /ready/.test(st().textContent) && !/no service/.test(st().textContent)), '#5509: right after its answer: "ready", not "connected, but no service running": ' + st()?.textContent);
  check(/starts with the next message/.test(w.eval(`agentHstLine(agentById(${ag.id}))`)), 'and the hint "starts with the next message"');
  check(w.eval(`agentSt({...agentById(${ag.id}), pending_age: 30})`) === 'connected, but no service running', 'while a message waits it names the missing service (#933 stays)');
  w.close();

  // answered without fetching: nothing waits either
  await call('POST', `/api/agents/${ag.id}/chat`, {body: 'And the roses?'});
  check(typeof (await mine()).pending_age === 'number', 'a second message waits');
  check((await v1(ag.token, 'POST', `/agent/chats/${me}`, {body: 'Done, both watered.'})).status < 300, 'the agent answers (without reading the list of chats)');
  check((await mine()).pending_age === null, 'answered: nothing waits (pending_age null)');

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
