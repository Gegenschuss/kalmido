// 2.1130.0 (#6057) UI tests (jsdom + Firefox), fresh DB: the pop-up for new chat messages (static/js/msgpop.js, liveparts.js mp_check)
// - a message of Bob in the project's conversation while Alice is on Today: ONE card with Bob's name, the project and the first
//   line; a screen reader hears it; a tap opens the conversation and the message is there to read; the card is gone
// - the conversation open: Bob's next message pops up nothing
// - three messages in quick succession: ONE card "3 new messages from Bob", the newest line
// - the x and Esc close it; it goes by itself after its time
// - an agent's answer: a card with the agent's name, a tap opens its chat
// - the switch Settings > Notifications > "Pop-up for new messages" off: nothing pops up, the service worker hears "not visible"
// - Firefox: the card lies over the page (the page under it does not move), top right on a desktop, across the width on a phone
// kalmido-suite: fresh
const {boot, errs, B, login, until, sleep} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21130_b_msgpop_ui', check, shots: 'P21130B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const call = async (method, url, body, ck, hdr = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hdr}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']}, CK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CK);
  const ME = (await call('GET', '/api/state', null, CK)).me, ORG = ME.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob Builder', password: 'password123', email: 'bob@example.com'}, CK)).id;
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, BK);
  const L = await call('POST', '/api/lists', {name: 'Shoot Berlin', org_id: ORG}, CK);
  await call('PUT', `/api/lists/${L.id}/members`, {user_id: BOB, role: 'edit'}, CK);
  const ROOM = (await call('GET', '/api/team', null, CK)).rooms.find(r => r.list_id === L.id).id;
  await call('GET', '/api/team', null, BK);
  const bobSays = body => call('POST', `/api/team/rooms/${ROOM}/messages`, {body}, BK);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'comments'], username: 'claude', display_name: 'Claude'}, CK);
  const AH = {Authorization: 'Bearer ' + ag.token};
  await call('PUT', `/api/lists/${L.id}/members`, {user_id: ag.id, role: 'edit'}, CK);  // an agent talks to the people it works with

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  const card = () => d.querySelector('#msgpop:not(.mpgone)');
  // what the poll does when the team chat / the agent chat moved: ask, then wait until the answer is in
  const ask = async () => { const t0 = w.eval('JSON.stringify([S.mp.t, S.mp.a])'); w.eval('mp_check()'); await until(() => !w.eval('S.mp.busy')); return t0; };
  await until(() => w.eval('!!S.booted'));
  await ask();
  check(w.eval('S.mp.t !== null && S.mp.a !== null'), 'the first ask knows where the window starts');
  check(!card(), 'nothing pops up for what was there before');

  // ================= one message: one card, the tap opens the conversation
  await bobSays('The van is booked for Monday\nand the second line');
  await ask();
  check(await until(card), 'Bob\'s message pops up on Today');
  check(d.querySelectorAll('#msgpop').length === 1, 'one card');
  check(card()?.querySelector('.mpwho')?.textContent === 'Bob Builder', 'the sender: ' + card()?.querySelector('.mpwho')?.textContent);
  check(card()?.querySelector('.mpwhere')?.textContent === 'Shoot Berlin', 'the project: ' + card()?.querySelector('.mpwhere')?.textContent);
  check(card()?.querySelector('.mpline')?.textContent === 'The van is booked for Monday', 'the first line: ' + card()?.querySelector('.mpline')?.textContent);
  check(!!card()?.querySelector('.avatar'), 'the sender\'s picture (or initials)');
  check(await until(() => (d.querySelector('#srlive')?.textContent || '').includes('Bob Builder')), 'a screen reader hears it: ' + d.querySelector('#srlive')?.textContent);
  card().querySelector('.mpopen').click();
  check(await until(() => w.location.hash === '#team/' + ROOM), 'the tap opens the conversation: ' + w.location.hash);
  check(await until(() => [...d.querySelectorAll('#tc-msgs .tcm, #tc-msgs [data-mid]')].some(m => m.textContent.includes('The van is booked'))), 'the message is there to read in the conversation');
  check(await until(() => !card()), 'the card is gone after the tap');

  // ================= the conversation open: nothing pops up
  await bobSays('Also the lights');
  await ask();
  await sleep(300);
  check(!card(), 'the open conversation: no card for its own new message');

  // ================= three in quick succession: one bundled card
  w.location.hash = '#today';
  await until(() => w.eval("S.route.mod !== 'team'"));
  await bobSays('One'); await bobSays('Two'); await bobSays('Three is the newest');
  await ask();
  check(await until(card), 'the three pop up');
  check(d.querySelectorAll('#msgpop').length === 1, 'still one card');
  check(card()?.querySelector('.mpwho')?.textContent === '3 new messages from Bob Builder', 'bundled: ' + card()?.querySelector('.mpwho')?.textContent);
  check(card()?.querySelector('.mpline')?.textContent === 'Three is the newest', 'the newest line: ' + card()?.querySelector('.mpline')?.textContent);
  card().querySelector('.mpx').click();
  check(await until(() => !card()), 'the x closes it');
  check(w.location.hash === '#today', 'the x opens nothing: ' + w.location.hash);

  // ================= Esc, and by itself after its time
  await bobSays('Esc test');
  await ask();
  check(await until(card), 'a new one pops up');
  card().dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  check(await until(() => !card()), 'Esc closes it');
  await bobSays('Goes by itself');
  await ask();
  check(await until(card), 'another one pops up');
  check(await until(() => !card(), {timeout: 12000}), 'it goes by itself after its time');

  // ================= an agent's answer: its chat opens
  const r = await call('POST', `/api/v1/agent/chats/${ME.id}`, {body: 'Shall I send the rough cut to the client?'}, null, AH);
  check(r.status === 201, 'the agent answers ' + r.status);
  await ask();
  check(await until(card), 'the agent\'s question pops up');
  check(card()?.querySelector('.mpwho')?.textContent === 'Claude' && card()?.querySelector('.mpline')?.textContent.startsWith('Shall I send'), 'the agent\'s name and the line: ' + card()?.textContent);
  card().querySelector('.mpopen').click();
  check(await until(() => w.location.hash === '#agents/' + ag.id), 'the tap opens the agent\'s chat: ' + w.location.hash);
  check(await until(() => [...d.querySelectorAll('#chat-msgs [data-mid], #chat-msgs .msg')].some(m => m.textContent.includes('Shall I send'))), 'the answer is there to read in its chat');

  // ================= the switch off (Settings > Notifications)
  w.location.hash = '#today';
  await until(() => w.eval("S.route.mod !== 'agents'"));
  check(w.eval('(() => { let got; mp_swAsk({ports: [{postMessage: x => { got = x; }}]}); return got && got.visible; })()') === true, 'the service worker hears: visible, pop-up on');
  await w.eval("loadModule('settings')"); w.eval("settingsModal('newskinds')");
  const sw = await until(() => d.querySelector('#s-msgpop'));
  check(!!sw && sw.checked, 'Settings > Notifications: the switch "Pop-up for new messages", on by default');
  check(sw?.closest('label')?.textContent.includes('Pop-up for new messages'), 'its label');
  sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(w.eval("LS.get('msgPop', '1')") === '0', 'off is stored on this device');
  d.querySelector('.smodal [data-m="close"], .modal [data-m="close"]')?.click();
  await bobSays('Nobody sees me pop up');
  await ask();
  await sleep(400);
  check(!card(), 'off: nothing pops up');
  check(w.eval('(() => { let got; mp_swAsk({ports: [{postMessage: x => { got = x; }}]}); return got && got.visible; })()') === false, 'off: the service worker hears "not visible" (the push shows)');
  w.eval("LS.set('msgPop', '1')");
  w.close();

  // ================= Firefox: over the page, nothing moves; desktop top right, phone across the width
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.ok)`), 'firefox: logged in');
    await nav(B + '#today');
    for (let i = 0; i < 100 && !(await ev('!!(window.S && S.booted)').catch(() => false)); i++) await sleep(100);
    const pop = async () => {
      await ev('(mp_check(), 1)'); for (let i = 0; i < 50 && await ev('S.mp.busy'); i++) await sleep(100);
      await bobSays('Firefox sees this ' + Date.now());
      await ev('(mp_check(), 1)');
      for (let i = 0; i < 100 && !(await ev("!!document.querySelector('#msgpop:not(.mpgone)')")); i++) await sleep(100);
    };
    const MEAS = `(() => { const m = document.querySelector('#msgpop'), v = document.querySelector('#view'); if (!m) return null; const r = m.getBoundingClientRect(), s = getComputedStyle(m);
      return {pos: s.position, top: Math.round(r.top), right: Math.round(innerWidth - r.right), left: Math.round(r.left), w: Math.round(r.width), iw: innerWidth, view: v ? Math.round(v.getBoundingClientRect().top) : null, sy: scrollY}; })()`;
    const viewTop = async () => ev(`(() => { const v = document.querySelector('#view'); return v ? Math.round(v.getBoundingClientRect().top) : null; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}}); await sleep(300);
    const v0 = await viewTop();
    await pop();
    const dk = await ev(MEAS);
    check(dk && dk.pos === 'fixed', 'desktop: the card lies over the page (fixed) ' + JSON.stringify(dk));
    check(dk && dk.view === v0, `desktop: the page under it does not move (${v0} -> ${dk && dk.view})`);
    check(dk && dk.top >= 0 && dk.top < 40 && dk.right >= 4 && dk.right < 40 && dk.w < dk.iw / 2, 'desktop: small, top right ' + JSON.stringify(dk));
    await shot('p21130b-desktop-1280.png');
    await ev("(mp_hide(), 1)");
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 800}}); await sleep(400);
    const v1 = await viewTop();
    await pop();
    const ph = await ev(MEAS);
    check(ph && ph.left <= 12 && ph.right <= 12 && ph.w >= ph.iw - 24, 'phone: across the width ' + JSON.stringify(ph));
    check(ph && ph.view === v1, `phone: the page under it does not move (${v1} -> ${ph && ph.view})`);
    await shot('p21130b-phone-390.png');
  });

  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  console.log(`p21130_b_msgpop_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p21130_b_msgpop_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
