// 2.1162.0 UI test part B (#6097: team chat - the line "New" before the first unread message, the log opens there), own container
// kalmido-suite: fresh
// Firefox as a touch screen in phone width 390 px. A channel of an organisation with 15 unread messages of another person:
// opened -> the line "New" in view, right before the first unread one (its text in view), the log NOT at the end, the pill
// "New message ↓" carries the number; after the read mark moved, a live patch (someone writes) and my own message the line
// stays where it was; left and opened again (nothing unread) -> no line, the log at the end. The same as a person without an
// organisation (her own agent writes in her project's channel - she sees nobody else). Invented data only.
// freelancer-matrix: team - no new route, the client view of /api/team/rooms/<id>/messages (checked for a freelancer below)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21162_b_chat_ui', check, shots: 'P21162B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21162B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'collab,comments';
// a message of several lines, so 15 of them are more than one screen
const long = (tag, i) => `${tag} ${i}\nsecond line of ${tag.toLowerCase()} ${i}\nthird line`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`});
  const bob = (await call(CB, 'GET', '/api/state')).me;
  const room = await call(CA, 'POST', '/api/team/channels', {name: 'Film crew', org_id: org.id, open: false, members: [bob.id]});
  check(room.id > 0, 'a room ' + JSON.stringify(room).slice(0, 200));
  // read before: two of Bob's and one of mine; then 15 unread ones of Bob
  for (let i = 1; i <= 2; i++) await call(CB, 'POST', `/api/team/rooms/${room.id}/messages`, {body: long('Old shot', i)});
  const mine = await call(CA, 'POST', `/api/team/rooms/${room.id}/messages`, {body: 'Seen all of that'});
  check((await call(CA, 'POST', `/api/team/rooms/${room.id}/read`, {last_id: mine.id})).http < 300, 'alice read up to her own message');
  const un = [];
  for (let i = 1; i <= 15; i++) un.push(await call(CB, 'POST', `/api/team/rooms/${room.id}/messages`, {body: long('Unread take', i)}));
  check(un.every(m => m.id > mine.id), '15 unread messages of Bob');

  // a person without an organisation: Frida (sees nobody else here), her own agent in her project = the project's channel;
  // the agent writes 15 messages there (through the API v1 with its token)
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'frida has no organisation');
  const ag = await call(CF, 'POST', '/api/my/agents', {username: 'fridabot', display_name: "Frida's bot", scopes: ['read', 'comments']});
  check(ag.id > 0, 'frida: an own agent ' + JSON.stringify(ag).slice(0, 200));
  const lst = await call(CF, 'POST', '/api/lists', {name: 'Short film'});
  check((await call(CF, 'PUT', `/api/lists/${lst.id}/members`, {user_id: ag.id, role: 'edit'})).http < 300, 'frida: the agent in her project');
  const tok = (await call(CF, 'POST', `/api/my/agents/${ag.id}/token`)).token || '';
  const dm = ((await call(CF, 'GET', '/api/team')).rooms || []).find(x => x.kind === 'list' && x.list_id === lst.id) || {};
  check(dm.id > 0, 'frida: the channel of her project');
  const fun = [];
  for (let i = 1; i <= 15; i++) {
    const rr = await fetch(B + `api/v1/team/rooms/${dm.id}/messages`, {method: 'POST', headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: JSON.stringify({body: long('Cut note', i)})});
    fun.push(await rr.json().catch(() => ({})));
  }
  check(fun.every(m => m.id > 0), 'frida: 15 messages of her agent ' + JSON.stringify(fun[0]).slice(0, 200));

  await firefox(async ({cmd, ev, nav: go, ctx, shot, until: wait}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 780}});
    const signIn = async u => {
      await go(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`) === 200, `Firefox: login ${u}`);
    };
    // the state of the open log: the line, the message after it, what is in view
    const STATE = `(() => { const box = document.querySelector('#tc-msgs'); if (!box) return {none: 1};
      const ln = box.querySelector('.tcunread'), b = box.getBoundingClientRect(), nx = ln?.nextElementSibling, pill = document.querySelector('#tc-new');
      const inView = e => { const r = e.getBoundingClientRect(); return r.top >= b.top - 1 && r.bottom <= b.bottom + 1; };
      return {line: ln ? ln.textContent.trim() : null, lineIn: ln ? inView(ln) : false, next: nx?.dataset?.mid || '', nextTxt: nx ? (nx.querySelector('.cbub')?.textContent || '') : '',
        nextTop: nx ? nx.querySelector('.cbub')?.getBoundingClientRect().top >= b.top && nx.querySelector('.cbub')?.getBoundingClientRect().top < b.bottom : false,
        gap: Math.round(box.scrollHeight - box.scrollTop - box.clientHeight), lines: box.querySelectorAll('.tcunread').length,
        pill: pill && !pill.classList.contains('hidden') ? pill.textContent.trim() : '', mob: isMobile(), touch: isTouch(), hash: location.hash}; })()`;
    const st = () => ev(STATE);
    const loaded = (rid, last) => `S.tc.rid === ${rid} && !!document.querySelector('#tc-msgs [data-mid="t:${last}"]')`;
    // after the first-load phase (teamFit keeps the place for 2 s while the page grows): the place it settled on
    const settled = rid => `S.tc.rid === ${rid} && !(S.tc.fitUntil > Date.now())`;

    const opened = async (tag, rid, first, last, txt, n) => {
      check(await wait(`${loaded(rid, last)} && !!document.querySelector('#tc-msgs .tcunread')`, {timeout: 20000}), `${tag}: the room with the line "New" ` + JSON.stringify(await st()));
      check(await wait(settled(rid), {timeout: 8000}), `${tag}: the first-load phase ended`);
      const s = await st();
      check(s.mob && s.touch, `${tag}: a touch screen in phone width ` + JSON.stringify(s));
      check(s.line === 'New' && s.lines === 1, `${tag}: one line "New" ` + JSON.stringify(s));
      check(s.lineIn, `${tag}: the line is in view ` + JSON.stringify(s));
      check(s.next === 't:' + first && s.nextTxt.includes(txt + ' 1'), `${tag}: right before the first unread message ` + JSON.stringify(s));
      check(s.nextTop, `${tag}: the first unread message's text is in view ` + JSON.stringify(s));
      check(s.gap > 200, `${tag}: the log is NOT at the end ` + JSON.stringify(s));
      check(new RegExp(`^${n} new messages`).test(s.pill), `${tag}: the pill carries the number ${n} ` + JSON.stringify(s));
      return s;
    };

    // 1. a channel of the organisation
    await signIn('alice');
    await go(B + `#team/${room.id}`);
    const s0 = await opened('channel', room.id, un[0].id, un[14].id, 'Unread take', 15);
    await shot('p21162b-new-line.png');
    // the read mark moved at once - the line stays
    check(await wait(`fetch('/api/team/rooms/${room.id}/messages', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.room.last_read === ${un[14].id})`, {timeout: 10000}), 'channel: opened = read up to the last message');
    let s = await st();
    check(s.line === 'New' && s.next === 't:' + un[0].id, 'channel: the line stays after the read mark ' + JSON.stringify(s));
    // a live patch: Bob writes, the conversation is reloaded (as /api/version does) - the line stays, the place too
    const more = await call(CB, 'POST', `/api/team/rooms/${room.id}/messages`, {body: 'One more from Bob'});
    await ev(`teamChanged().then(() => 1)`);
    check(await wait(`!!document.querySelector('#tc-msgs [data-mid="t:${more.id}"]')`, {timeout: 10000}), 'channel: the live message arrived');
    s = await st();
    check(s.line === 'New' && s.lines === 1 && s.next === 't:' + un[0].id, 'channel: the line stays after a live patch ' + JSON.stringify(s));
    check(s.lineIn && s.gap > 200, 'channel: the place does not jump on a live patch ' + JSON.stringify(s) + ' before ' + JSON.stringify(s0));
    // my own message: the line does not move
    await ev(`(() => { const t = document.querySelector('#tc-in'); t.value = 'My own answer'; return tcSend().then(() => 1); })()`);
    check(await wait(`[...document.querySelectorAll('#tc-msgs .cmsg.me .cbub')].some(e => e.textContent.includes('My own answer'))`, {timeout: 10000}), 'channel: my own message is there');
    s = await st();
    check(s.line === 'New' && s.lines === 1 && s.next === 't:' + un[0].id, 'channel: my own message does not move the line ' + JSON.stringify(s));
    // left and opened again: nothing unread -> no line, at the end
    await go(B + '#today');
    check(await wait(`S.route?.key === 'today' && S.tc.rid === null`, {timeout: 15000}), 'channel: left');
    await ev(`(location.hash = '#team/${room.id}', 1)`);
    check(await wait(`${loaded(room.id, more.id)} && [...document.querySelectorAll('#tc-msgs .cbub')].some(e => e.textContent.includes('My own answer'))`, {timeout: 15000}), 'channel: opened again');
    check(await wait(settled(room.id), {timeout: 8000}), 'channel again: the first-load phase ended');
    s = await st();
    check(s.lines === 0, 'channel again: nothing unread = no line ' + JSON.stringify(s));
    check(s.gap < 80, 'channel again: the log at the end as before ' + JSON.stringify(s));
    check(!/new messages/.test(s.pill), 'channel again: no number on the pill ' + JSON.stringify(s));

    // 2. a person without an organisation: a direct message
    await signIn('frida');
    await go(B + `#team/${dm.id}`);
    await opened('freelancer channel', dm.id, fun[0].id, fun[14].id, 'Cut note', 15);
    await shot('p21162b-freelancer.png');
    // the pill: a tap goes to the end and its number goes
    await ev(`(document.querySelector('#tc-new').click(), 1)`);
    check(await wait(`(() => { const b = document.querySelector('#tc-msgs'); return b.scrollHeight - b.scrollTop - b.clientHeight < 80; })()`, {timeout: 8000}), 'freelancer channel: the pill goes to the end');
    check(await wait(`/^New message/.test(document.querySelector('#tc-new').textContent.trim())`, {timeout: 8000}), 'freelancer channel: the pill without the number again ' + JSON.stringify(await st()));
    s = await st();
    check(s.line === 'New', 'freelancer channel: the line stays at the end, too ' + JSON.stringify(s));
  }, true);

  console.log(`p21162_b_chat_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
