// 2.33.0 UI tests, part B (#1080 search in conversations), own container (start.sh). Firefox, 390 x 844 touch:
// - the magnifier in a team chat's header opens a search bar under it (not there before); typing finds the hits of this
//   conversation, the newest is opened (older pages loaded until it is there), the words are marked in the message, "1 of 2",
//   the arrows go to the older / newer hit; Escape / X closes it and the marks go
// - the same in the chat with an agent
// - the search page: below the tasks a part "Messages" with sender, chat, date and the snippet (hit marked), filter chips
//   (All / Comments / Team chats / Agent chats); a hit opens the place (a comment: the task with the comment marked)
// - the command field: the group "Messages" with the hits
// Screenshots into $P2330B_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2330_b_ui', check, shots: 'P2330B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,family,team';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const CL = ag.id, CLH = {'Content-Type': 'application/json', Authorization: 'Bearer ' + ag.token};
  const L = (await call('POST', '/api/lists', {name: 'Work'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: CL, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Kitchen plan', list_id: L})).id;
  for (let i = 1; i <= 6; i++) await call('POST', `/api/tasks/${T}/comments`, {body: `Comment ${i} about cupboards`});
  const CM = (await call('POST', `/api/tasks/${T}/comments`, {body: 'The Ärger with the Spülmaschine is solved'})).id;
  const rooms = (await call('GET', '/api/team')).rooms, RW = rooms.find(x => x.kind === 'list').id;
  const M1 = (await call('POST', `/api/team/rooms/${RW}/messages`, {body: 'First note: the Spülmaschine arrives on Monday'})).id;
  for (let i = 1; i <= 60; i++) await call('POST', `/api/team/rooms/${RW}/messages`, {body: `Filler message ${i}`});
  const M2 = (await call('POST', `/api/team/rooms/${RW}/messages`, {body: 'Spuelmaschine works now'})).id;
  for (let i = 1; i <= 3; i++) await call('POST', `/api/team/rooms/${RW}/messages`, {body: `Later message ${i}`});
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Please check the Spülmaschine invoice'});
  const ans = await (await fetch(B + `api/v1/agent/chats/${(await call('GET', '/api/state')).me.id}`, {method: 'POST', headers: CLH, body: JSON.stringify({body: 'The invoice of the dishwasher is in the inbox'})})).json();
  check(ans.id, 'setup: the agent answers');

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const until = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const type = (ev, sel, v) => ev(`(() => { const i = document.querySelector('${sel}'); i.focus(); i.value = ${JSON.stringify(v)}; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    check(await ffLogin(o) === 200, 'login');
    await nav(B + '#team/' + RW); await ready(ev);
    await until(ev, `!!document.querySelector('#tc-msgs .cmsg')`);

    // ================= team chat: the magnifier, the bar, hits, arrows
    const b0 = await ev(`(() => { const b = document.querySelector('.tcrhead [data-act="ms-toggle"]'); if (!b) return null; const r = b.getBoundingClientRect(); return {w: r.width, h: r.height, bar: !!document.querySelector('.mqbar'), in: r.right <= innerWidth}; })()`);
    check(b0 && b0.w >= 24 && b0.h >= 24 && !b0.bar && b0.in, '#1080: a magnifier in the team chat header, no search bar before ' + JSON.stringify(b0));
    await ev(`(() => { document.querySelector('.tcrhead [data-act="ms-toggle"]').click(); return 1; })()`); await sleep(300);
    const b1 = await ev(`(() => { const bar = document.querySelector('.mqbar'); return {bar: !!bar, h: Math.round(bar?.getBoundingClientRect().height || 0), under: bar?.previousElementSibling?.classList.contains('tcrhead'), foc: document.activeElement?.id, over: document.documentElement.scrollWidth <= 390}; })()`);
    check(b1.bar && b1.h >= 44 && b1.h <= 64 && b1.under && b1.foc === 'ms-q' && b1.over, '#1080: the bar opens under the header, the field has the focus ' + JSON.stringify(b1));
    await type(ev, '#ms-q', 'spülmaschine');
    const got = await until(ev, `document.querySelector('.mqbar .mscount')?.textContent === '1 of 2'`);
    await until(ev, `!!document.querySelector('[data-mid="t:${M2}"] mark.mshl')`, 20);
    const h1 = await ev(`(() => { const m = document.querySelector('[data-mid="t:${M2}"] mark.mshl'); return {cnt: document.querySelector('.mqbar .mscount').textContent, mark: m?.textContent, n: document.querySelectorAll('mark.mshl').length}; })()`);
    check(got && h1.mark === 'Spuelmaschine' && h1.n === 1, '#1080: the newest hit first (ä = ue), the word marked in the message ' + JSON.stringify(h1));
    await shot('p2330b-390-teamsearch.png');
    await ev(`(() => { document.querySelector('.mqbar [data-act="ms-older"]').click(); return 1; })()`);
    const old = await until(ev, `!!document.querySelector('[data-mid="t:${M1}"] mark.mshl')`);
    const h2 = await ev(`(() => { const el = document.querySelector('[data-mid="t:${M1}"]'), r = el?.getBoundingClientRect(), box = document.querySelector('#tc-msgs').getBoundingClientRect();
      return {cnt: document.querySelector('.mqbar .mscount').textContent, vis: !!r && r.top < box.bottom && r.bottom > box.top, mark: el?.querySelector('mark.mshl')?.textContent, older: document.querySelector('.mqbar [data-act="ms-older"]').disabled, newer: document.querySelector('.mqbar [data-act="ms-newer"]').disabled}; })()`);
    check(old && h2.cnt === '2 of 2' && h2.vis && h2.mark === 'Spülmaschine' && h2.older && !h2.newer, '#1080: the arrow goes to the older hit, older pages loaded, in view ' + JSON.stringify(h2));
    await ev(`(() => { document.querySelector('#ms-q').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`); await sleep(300);
    check(await ev(`!document.querySelector('.mqbar') && !document.querySelector('mark.mshl')`), '#1080: Escape closes the bar, the marks go');

    // ================= agent chat
    await nav(B + '#agents/' + CL); await ready(ev);
    await until(ev, `!!document.querySelector('#chat-msgs .cmsg')`);
    const a0 = await ev(`(() => { const b = document.querySelector('.chath [data-act="ms-toggle"]'); return b ? {w: b.getBoundingClientRect().width, in: b.getBoundingClientRect().right <= innerWidth} : null; })()`);
    check(a0 && a0.w >= 24 && a0.in, '#1080: a magnifier in the agent chat header ' + JSON.stringify(a0));
    await ev(`(() => { document.querySelector('.chath [data-act="ms-toggle"]').click(); return 1; })()`); await sleep(200);
    await type(ev, '#ms-q', 'invoice');
    const ac = await until(ev, `document.querySelector('.mqbar .mscount')?.textContent === '1 of 2' && !!document.querySelector('#chat-msgs mark.mshl')`);
    check(ac && await ev(`document.querySelector('#chat-msgs mark.mshl').textContent === 'invoice'`), '#1080: search in the agent chat, the newest hit marked');
    await ev(`(() => { document.querySelector('.mqbar [data-act="ms-close"]').click(); return 1; })()`); await sleep(200);
    check(await ev(`!document.querySelector('.mqbar')`), '#1080: X closes the bar');

    // ================= the search page: "Messages" with chips
    await nav(B + '#search'); await ready(ev);
    await type(ev, '#searchq', 'Spülmaschine');
    const sp = await until(ev, `document.querySelectorAll('#smsgs .mhit').length >= 4`);
    const s1 = await ev(`(() => { const hs = [...document.querySelectorAll('#smsgs .mhit')]; return {n: hs.length, chips: [...document.querySelectorAll('#smsgs .mschips .chip')].map(c => c.textContent).join('|'),
      team: hs.some(h => /Team chat · Work/.test(h.querySelector('.mhc').textContent)), ue: hs.some(h => h.querySelector('.mhs mark')?.textContent === 'Spuelmaschine'),
      first: hs[0] && {who: hs[0].querySelector('.mhh b').textContent, chat: hs[0].querySelector('.mhc').textContent, time: !!hs[0].querySelector('time').textContent, mark: hs[0].querySelector('.mhs mark')?.textContent},
      h: Math.round(hs[0]?.getBoundingClientRect().height || 0), heron: !!document.querySelector('#sresults .hempty') && getComputedStyle(document.querySelector('#sresults .hempty')).display !== 'none', over: document.documentElement.scrollWidth <= 390}; })()`);
    check(sp && s1.n === 4 && s1.chips === 'All|Comments|Team chats|Agent chats' && s1.first?.who === 'Alice' && /Agent chat · Claude/.test(s1.first.chat) && s1.first.time && s1.first.mark === 'Spülmaschine' && s1.team && s1.ue && s1.h >= 44 && !s1.heron && s1.over,
      '#1080: "Messages" on the search page: sender, chat, date, snippet with the hit marked, filter chips ' + JSON.stringify(s1));
    await shot('p2330b-390-searchpage.png');
    await ev(`(() => { [...document.querySelectorAll('#smsgs .mschips .chip')].find(c => c.textContent === 'Comments').click(); return 1; })()`);
    const cOnly = await until(ev, `document.querySelectorAll('#smsgs .mhit').length === 1 && document.querySelector('#smsgs .chip.on')?.textContent === 'Comments'`);
    check(cOnly, '#1080: the chip "Comments" keeps only the comment');
    await ev(`(() => { document.querySelector('#smsgs .mhit').click(); return 1; })()`);
    const jumped = await until(ev, `!!document.querySelector('#detail [data-mid="c:${CM}"]')`);
    check(jumped && await ev(`S.sel === ${T}`), '#1080: a comment hit opens the task with the comment');
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(400);

    // ================= the command field
    await ev(`(() => { openPalette(); return 1; })()`); await sleep(300);
    await type(ev, '.palette .pqin', 'dishwasher');
    const pm = await until(ev, `[...document.querySelectorAll('.palette .pgroup')].some(g => g.textContent === 'Messages') && !!document.querySelector('.palette .pitem .pmsg mark')`);
    check(pm && await ev(`document.querySelector('.palette .pitem .pmsg mark').textContent === 'dishwasher'`), '#1080: the command field shows the group "Messages" with the hit marked');
    await ev(`(() => { closePalette(); return 1; })()`);
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
