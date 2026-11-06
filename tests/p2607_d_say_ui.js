// kalmido-suite: fresh
// 2.607.0 D (#4549) tests: guests and read-only people of an organisation only read in its objects.
// Own container (start.sh), jsdom, invented names only, addresses @example.com.
// freelancer-matrix: tasks
// - API (web + v1): a read-only person / a guest of the organisation comments, reacts, answers an agent's buttons, comments a
//   video sign-off and writes in the organisation's team chat (a project's channel, an open channel: post, react, pin) = 403
//   with the role's text; a member does all of it (200 / 201); accounting comments as before; a guest with a personal edit
//   share keeps commenting; a member who is only a participant comments on their own task, a guest participant does not;
//   a DM, the own private list and taking a reaction back stay open; a person without an organisation comments as before
// - the flags: say_no on the list in /api/state, on the timeline and on the room of a conversation (null for a member)
// - the app: instead of the comment box / the chat input a short hint, no reaction buttons; a member keeps both
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2607D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (method, url, body, ck) => {
  const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status};
};
const v1 = async (method, url, body, tok) => {
  const r = await fetch(B + 'api/v1/' + url.replace(/^\//, ''), {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined});
  const t = await r.text(); return {http: r.status, text: t, j: (() => { try { return JSON.parse(t); } catch { return {}; } })()};
};
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const FEAT = 'cal,comments,collab,videos,files,docs';
const RO = /read-only/, GU = /does not include this/;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const A = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments', 'collab', 'videos']}, A);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, A);
  const ORG = (await call('GET', '/api/state', null, A)).me.workspaces[0].id;
  const uid = {}, ck = {};
  for (const [u, role] of [['bob', 'member'], ['gina', 'guest'], ['rita', 'readonly'], ['axel', 'accounting']]) {
    const r = await call('POST', '/api/users', {orgs: [{id: ORG, role}], username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`}, A);
    uid[u] = r.id; ck[u] = await login(u);
    await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ck[u]);
  }
  const fr = await call('POST', '/api/users', {orgs: [], username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'}, A);
  ck.frida = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ck.frida);
  const {bob: Bo, gina: Gi, rita: Ri, axel: Ax, frida: Fr} = ck;
  check(uid.bob && uid.gina && uid.rita && uid.axel && fr.id, 'setup: the people ' + JSON.stringify(uid));

  // L2: an organisation project shared with everybody (rita edit = capped to view, gina / axel view, bob edit)
  const L2 = (await call('POST', '/api/lists', {name: 'Studio board', org_id: ORG}, A)).id;
  for (const [u, role] of [['bob', 'edit'], ['rita', 'edit'], ['gina', 'view'], ['axel', 'view']]) await call('PUT', `/api/lists/${L2}/members`, {user_id: uid[u], role}, A);
  const T2 = (await call('POST', '/api/tasks', {list_id: L2, title: 'Plan the shoot'}, A)).id;
  // L3: shared with the guest to edit; L4: participants (the guest and the member)
  const L3 = (await call('POST', '/api/lists', {name: 'Guest work', org_id: ORG}, A)).id;
  await call('PUT', `/api/lists/${L3}/members`, {user_id: uid.gina, role: 'edit'}, A);
  const T3 = (await call('POST', '/api/tasks', {list_id: L3, title: 'Shared draft'}, A)).id;
  const L4 = (await call('POST', '/api/lists', {name: 'Helpers', org_id: ORG}, A)).id;
  for (const u of ['gina', 'bob']) await call('PUT', `/api/lists/${L4}/members`, {user_id: uid[u], role: 'participant'}, A);
  const T4 = (await call('POST', '/api/tasks', {list_id: L4, title: 'For the guest', assignee_id: uid.gina}, A)).id;
  const T5 = (await call('POST', '/api/tasks', {list_id: L4, title: 'For the member', assignee_id: uid.bob}, A)).id;
  check(L2 && L3 && L4 && T2 && T3 && T4 && T5, 'setup: projects and tasks');
  const C0 = (await call('POST', `/api/tasks/${T2}/comments`, {body: 'Kick-off on Monday'}, A)).id;
  check(C0 > 0, 'setup: the admin comments');

  // ================= task comments (web)
  let r = await call('POST', `/api/tasks/${T2}/comments`, {body: 'Can I?'}, Ri);
  check(r.http === 403 && RO.test(r.error || ''), `read-only: no comment, 403 with the role's text ${r.http} ${r.error}`);
  r = await call('POST', `/api/tasks/${T2}/comments`, {body: 'Can I?'}, Gi);
  check(r.http === 403 && GU.test(r.error || ''), `guest (view share): no comment, 403 ${r.http} ${r.error}`);
  r = await call('POST', `/api/tasks/${T2}/comments`, {body: 'Looks good'}, Bo);
  check(r.http === 200 && r.id > 0, `member: comments ${r.http}`);
  const CB = r.id;
  r = await call('POST', `/api/tasks/${T2}/comments`, {body: 'Receipt is in'}, Ax);
  check(r.http === 200, `accounting: comments as before ${r.http} ${r.error || ''}`);
  r = await call('POST', `/api/tasks/${T3}/comments`, {body: 'Done my part'}, Gi);
  check(r.http === 200, `guest with a personal edit share: comments there ${r.http} ${r.error || ''}`);
  r = await call('POST', `/api/tasks/${T4}/comments`, {body: 'Mine'}, Gi);
  check(r.http === 403, `guest participant: no comment on the own task ${r.http}`);
  r = await call('POST', `/api/tasks/${T5}/comments`, {body: 'Mine'}, Bo);
  check(r.http === 200, `member participant: comments on the own task (participant rights stay) ${r.http} ${r.error || ''}`);
  const PL = (await call('POST', '/api/lists', {name: 'Private notes', org_id: null}, Ri)).id;
  const PT = (await call('POST', '/api/tasks', {list_id: PL, title: 'Mine'}, Ri)).id;
  r = await call('POST', `/api/tasks/${PT}/comments`, {body: 'A note to myself'}, Ri);
  check(r.http === 200, `read-only: the own private list keeps its comments ${r.http} ${r.error || ''}`);
  // freelancer-matrix: tasks
  const FL = (await call('POST', '/api/lists', {name: 'Own work'}, Fr)).id;
  const FT = (await call('POST', '/api/tasks', {list_id: FL, title: 'Cut the trailer'}, Fr)).id;
  r = await call('POST', `/api/tasks/${FT}/comments`, {body: 'First cut ready'}, Fr);
  check(r.http === 200, `freelancer: comments on the own task ${r.http} ${r.error || ''}`);
  check((await call('GET', `/api/tasks/${FT}/timeline`, null, Fr)).say_no === null, 'freelancer: no say_no on the timeline');

  // ================= reactions
  r = await call('POST', `/api/comments/${C0}/reactions`, {emoji: 'up'}, Ri);
  check(r.http === 403 && RO.test(r.error || ''), `read-only: no reaction ${r.http} ${r.error}`);
  r = await call('POST', `/api/comments/${C0}/reactions`, {emoji: 'heart', on: true}, Gi);
  check(r.http === 403, `guest: no reaction ${r.http}`);
  r = await call('POST', `/api/comments/${C0}/reactions`, {emoji: 'up', on: false}, Ri);
  check(r.http === 200, `read-only: taking a reaction back stays open ${r.http} ${r.error || ''}`);
  r = await call('POST', `/api/comments/${C0}/reactions`, {emoji: 'up'}, Bo);
  check(r.http === 200 && (r.reactions || []).length === 1, `member: reacts ${r.http}`);

  // ================= an agent's answer buttons
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'comments'], username: 'claude', display_name: 'Claude'}, A);
  await call('PUT', `/api/lists/${L2}/members`, {user_id: ag.id, role: 'edit'}, A);
  const qc = await v1('POST', `tasks/${T2}/comments`, {body: 'Which cut?', choices: ['Short', 'Long']}, ag.token);
  const QC = qc.j.id;
  check(qc.http === 201 && QC > 0, `setup: the agent asks with buttons ${qc.http} ${qc.text.slice(0, 150)}`);
  r = await call('POST', `/api/comments/${QC}/choice`, {choice_ids: ['Short']}, Ri);
  check(r.http === 403 && RO.test(r.error || ''), `read-only: no answer to the buttons ${r.http} ${r.error}`);
  r = await call('POST', `/api/comments/${QC}/choice`, {choice_ids: ['Short']}, Gi);
  check(r.http === 403, `guest: no answer to the buttons ${r.http}`);
  r = await v1('POST', `comments/${QC}/choice`, {choice_ids: ['Long']}, await (async () => (await call('POST', '/api/me/tokens', {name: 'r', scopes: ['read', 'write', 'comments']}, Ri)).token)());
  check(r.http === 403, `v1 read-only: no answer to the buttons ${r.http}`);
  r = await call('POST', `/api/comments/${QC}/choice`, {choice_ids: ['Short']}, A);  // (bob may not address the admin's agent; while it is the newest question)
  check(r.http === 200, `the project's owner answers the buttons ${r.http} ${r.error || ''}`);

  // ================= API v1 (people's own tokens)
  const tok = async c => (await call('POST', '/api/me/tokens', {name: 't', scopes: ['read', 'write', 'comments']}, c)).token;
  const VR = await tok(Ri), VG = await tok(Gi), VB = await tok(Bo);
  check(VR && VG && VB, 'setup: the tokens');
  r = await v1('POST', `tasks/${T2}/comments`, {body: 'Via the API'}, VR);
  check(r.http === 403 && RO.test(r.text), `v1 read-only: no comment ${r.http} ${r.text.slice(0, 150)}`);
  r = await v1('POST', `tasks/${T2}/comments`, {body: 'Via the API'}, VG);
  check(r.http === 403, `v1 guest: no comment ${r.http}`);
  r = await v1('POST', `comments/${C0}/reactions`, {emoji: 'heart'}, VR);
  check(r.http === 403, `v1 read-only: no reaction ${r.http}`);
  r = await v1('POST', `tasks/${T2}/comments`, {body: 'Via the API'}, VB);
  check(r.http === 201, `v1 member: comments ${r.http} ${r.text.slice(0, 150)}`);
  r = await v1('PATCH', `comments/${CB}`, {body: 'Looks good!'}, VB);
  check(r.http === 200, `v1 member: edits the own comment ${r.http}`);

  // ================= a video sign-off of the organisation
  const VID = (await call('POST', '/api/videos', {title: 'First cut', url: 'https://vimeo.com/123456789', list_id: L2}, A)).id;
  check(VID > 0, 'setup: a video sign-off at the project');
  r = await call('POST', `/api/videos/${VID}/comments`, {body: 'Brighter at twelve'}, Ri);
  check(r.http === 403 && RO.test(r.error || ''), `read-only: no comment on the sign-off ${r.http} ${r.error}`);
  r = await call('POST', `/api/videos/${VID}/comments`, {body: 'Brighter at twelve'}, Bo);
  check(r.http === 200, `member: comments the sign-off ${r.http} ${r.error || ''}`);

  // ================= team chat
  const rooms = async c => (await call('GET', '/api/team', null, c)).rooms || [];
  const R2 = (await rooms(Bo)).find(x => x.list_id === L2)?.id;
  const R3 = (await rooms(Gi)).find(x => x.list_id === L3)?.id;
  const CH = (await call('POST', '/api/team/channels', {name: 'General', org_id: ORG, open: true}, A)).id;
  check(R2 && R3 && CH, `setup: the project channels and an open channel ${R2} ${R3} ${CH}`);
  const say = (rid, c, body = 'Hello') => call('POST', `/api/team/rooms/${rid}/messages`, {body}, c);
  r = await say(R2, Ri);
  check(r.http === 403 && RO.test(r.error || ''), `read-only: nothing in the project's channel ${r.http} ${r.error}`);
  r = await say(R2, Gi);
  check(r.http === 403 && GU.test(r.error || ''), `guest (view): nothing in the project's channel ${r.http} ${r.error}`);
  r = await say(R2, Bo);
  check(r.http === 201, `member: writes in the project's channel ${r.http}`);
  r = await say(R2, Ax);
  check(r.http === 201, `accounting: writes as before ${r.http} ${r.error || ''}`);
  r = await say(R3, Gi);
  check(r.http === 201, `guest with an edit share: writes in that project's channel ${r.http} ${r.error || ''}`);
  r = await say(CH, Bo);
  const MB = r.id;
  check(r.http === 201 && MB > 0, `member: writes in the open channel ${r.http}`);
  r = await say(CH, Ri);
  check(r.http === 403, `read-only: reads the open channel, writes nothing ${r.http}`);
  check((await call('GET', `/api/team/rooms/${CH}/messages`, null, Ri)).http === 200, 'read-only: the open channel stays readable');
  r = await call('POST', `/api/team/messages/${MB}/reactions`, {emoji: 'up'}, Ri);
  check(r.http === 403, `read-only: no reaction in the channel ${r.http}`);
  r = await call('POST', `/api/team/messages/${MB}/reactions`, {emoji: 'up', on: false}, Ri);
  check(r.http === 200, `read-only: taking a reaction back stays ${r.http} ${r.error || ''}`);
  r = await call('POST', `/api/team/messages/${MB}/pin`, {pinned: true}, Ri);
  check(r.http === 403, `read-only: no pin in the channel ${r.http}`);
  r = await v1('POST', `team/rooms/${CH}/messages`, {body: 'Via the API'}, VR);
  check(r.http === 403, `v1 read-only: nothing in the channel ${r.http}`);
  r = await v1('POST', `team/rooms/${R2}/messages`, {body: 'Via the API'}, VG);
  check(r.http === 403, `v1 guest: nothing in the project's channel ${r.http}`);
  r = await v1('POST', `team/rooms/${CH}/messages`, {body: 'Via the API'}, VB);
  check(r.http === 201, `v1 member: writes in the channel ${r.http} ${r.text.slice(0, 150)}`);
  const DM = (await call('POST', '/api/team/dm', {user_id: uid.bob}, Ri)).id;
  r = await say(DM, Ri, 'A quick question');
  check(DM && r.http === 201, `read-only: a direct message stays open ${r.http} ${r.error || ''}`);

  // ================= the flags for the app
  const sl = async c => Object.fromEntries(((await call('GET', '/api/state', null, c)).lists || []).map(l => [l.id, l]));
  const sR = await sl(Ri), sG = await sl(Gi), sB = await sl(Bo), sA = await sl(Ax);
  check(RO.test(sR[L2]?.say_no || '') && GU.test(sG[L2]?.say_no || '') && GU.test(sG[L4]?.say_no || ''), 'state: say_no on the project for the read-only person / the guest');
  check(!sB[L2]?.say_no && !sG[L3]?.say_no && !sA[L2]?.say_no && !sR[PL]?.say_no, 'state: no say_no for a member, an edit share, accounting, a private list');
  check(RO.test((await call('GET', `/api/tasks/${T2}/timeline`, null, Ri)).say_no || ''), 'timeline: say_no for the read-only person');
  check((await call('GET', `/api/tasks/${T2}/timeline`, null, Bo)).say_no === null, 'timeline: say_no null for a member');
  check(RO.test((await call('GET', `/api/team/rooms/${CH}/messages`, null, Ri)).room?.say_no || ''), 'room: say_no for the read-only person');
  check((await call('GET', `/api/team/rooms/${CH}/messages`, null, Bo)).room?.say_no === null, 'room: say_no null for a member');

  // ================= the app: the hint instead of the boxes
  let w = await boot({user: 'rita', hash: 't/' + T2}), d = w.document;
  check(await until(() => d.querySelector('#detail .dcomp .sayno') && d.querySelector(`#detail [data-cid="${C0}"]`)), 'read-only: the hint instead of the comment box');
  check(!d.querySelector('#detail #c-input'), 'read-only: no comment box');
  check(RO.test(d.querySelector('#detail .sayno')?.textContent || ''), 'read-only: the hint says the role ' + d.querySelector('#detail .sayno')?.textContent);
  check(!d.querySelector('#detail [data-act="c-react-more"]') && !d.querySelector('#detail .rx.add'), 'read-only: no reaction buttons');
  w.close();
  w = await boot({user: 'bob', hash: 't/' + T2}); d = w.document;
  check(await until(() => d.querySelector('#detail #c-input') && d.querySelector(`#detail [data-act="c-react-more"]`)), 'member: the comment box and the reaction button');
  check(!d.querySelector('#detail .sayno'), 'member: no hint');
  w.close();
  w = await boot({user: 'rita', hash: 'team/' + CH}); d = w.document;
  check(await until(() => d.querySelector('.tcarch.sayno') && d.querySelector(`[data-mid="t:${MB}"]`)), 'read-only: the hint instead of the chat input');
  check(!d.querySelector('#tc-in'), 'read-only: no chat input');
  w.close();
  w = await boot({user: 'bob', hash: 'team/' + CH}); d = w.document;
  check(await until(() => d.querySelector('#tc-in')), 'member: the chat input');
  check(!d.querySelector('.tcarch.sayno'), 'member: no hint in the chat');
  w.close();

  console.log(`p2607_d_say: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
