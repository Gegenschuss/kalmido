// 2.233.0 A (#2848) UI tests (agent chat), own container (start.sh). jsdom:
// - a suggestion a newer message ended leaves its message and waits folded above the message box: "Earlier suggestions (1)";
//   open: the source (agent / job) and the time, the buttons; a tap sends (answered, the shelf empties), the pen puts the
//   text into the message box, X dismisses on the server
// - the header menu has "Chat settings": a dialog with radio rows, autosave per field (no save button); "Keep all at their
//   message" leaves the buttons at the message (no shelf); "Pin approvals at the top" off hides the pinned approval;
//   "One line" for notices
// Firefox 360 / 412 touch: the shelf is one line folded, open it stays above the box and scrolls inside, tap targets >= 44 px,
// nothing sticks out sideways (screenshots)
// freelancer-matrix: agents (the shelf in the chat of a person without an organisation with a personal agent)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2233_a_chatsugg_ui', check, shots: 'P2233A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me, ORG = ME.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'App dev', org_id: ORG})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const sayTo = async (uid, hd, body, extra = {}) => (await fetch(V + `/agent/chats/${uid}`, {method: 'POST', headers: hd, body: JSON.stringify({body, ...extra})})).json();
  const say = (body, extra) => sayTo(ME.id, AGH, body, extra);
  const cm = (d, id) => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  const shelf = d => d.querySelector('#chat-sug');

  // ================= the shelf
  const q1 = await say('Shall I plan 2.30 now?', {choices: [{id: 'yes', label: 'Plan 2.30', style: 'primary'}, {id: 'no', label: 'Later'}]});
  await say('Status: the build runs.');
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => cm(d, q1.id) && shelf(d) && !shelf(d).hidden);
  check(!cm(d, q1.id).querySelector('.cchoices'), 'the ended suggestion left its message');
  check(shelf(d) && !shelf(d).hidden && /Earlier suggestions \(1\)/.test(shelf(d).textContent), 'the shelf "Earlier suggestions (1)" ' + (shelf(d)?.textContent || '').slice(0, 80));
  check(shelf(d).querySelector('.acsug-t')?.getAttribute('aria-expanded') === 'false' && !shelf(d).querySelector('.acsug-l'), '... folded');
  check(shelf(d).compareDocumentPosition(d.querySelector('#chat-in')) & w.Node.DOCUMENT_POSITION_FOLLOWING, '... above the message box');
  click(w, shelf(d).querySelector('[data-act="acsug-tog"]'));
  await until(() => shelf(d).querySelector('.acsug-i'));
  const it = shelf(d).querySelector('.acsug-i');
  check(it && /Claude/.test(it.querySelector('.acsug-h b')?.textContent || '') && it.querySelector('.acsug-h time'), 'open: the source and the time ' + (it?.textContent || '').slice(0, 120));
  check(/Plan 2\.30/.test(it.textContent) && it.querySelectorAll('.cchb[data-act="chat-choice"]').length === 2 && it.querySelector('.cchpen') && it.querySelector('[data-act="acsug-x"]'),
    'the buttons, the pen and X');
  click(w, it.querySelector('.cchpen'));
  check(d.querySelector('#chat-in').value === 'Plan 2.30', 'the pen puts the text into the message box: ' + d.querySelector('#chat-in').value);
  d.querySelector('#chat-in').value = '';
  click(w, it.querySelector('.cchb[data-cid="yes"]'));
  await until(() => shelf(d).hidden);
  const st1 = (await call('GET', `/api/agents/${AG}/chat`)).messages.find(m => m.id === q1.id);
  check(st1?.choice?.ids?.[0] === 'yes', 'a tap sends: the server has the answer ' + JSON.stringify(st1?.choice));
  check(shelf(d).hidden, '... and the shelf empties');
  // X dismisses on the server
  const q2 = await say('Ship it?', {choices: ['Ship', 'Wait']});
  await say('Another thing.');
  await w.eval('chatLoad()'); await until(() => !shelf(d).hidden && shelf(d).querySelector('[data-act="acsug-x"]'));
  click(w, shelf(d).querySelector('[data-act="acsug-x"]'));
  await until(() => shelf(d).hidden);
  const st2 = (await call('GET', `/api/agents/${AG}/chat`)).messages.find(m => m.id === q2.id);
  check(st2?.choices?.dismissed_at && st2.choice_state === 'expired', 'X: dismissed on the server (every device) ' + JSON.stringify(st2?.choices));

  // ================= the settings
  const q3 = await say('Which colour?', {choices: ['Red', 'Blue']});
  await say('One more line.');
  await w.eval('chatLoad()'); await until(() => !shelf(d).hidden);
  click(w, d.querySelector('[data-act="chat-head-menu"]'));
  const mi = await until(() => [...d.querySelectorAll('#pop [role=menuitem]')].find(x => /^Chat settings/.test(x.textContent.trim())));
  check(!!mi, 'the header menu has "Chat settings"');
  mi?.click();
  const md = await until(() => d.querySelector('.modal.acsetmd'));
  check(md && md.querySelectorAll('fieldset.acset-f').length === 4 && md.querySelector('[data-acset="sugg"][value="collect"]')?.checked && !md.querySelector('.foot .pri'),
    'a dialog with four groups, "collect" chosen, no save button');
  const keep = md.querySelector('[data-acset="sugg"][value="keep"]'); keep.checked = true; keep.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', `/api/agents/${AG}/chat-prefs`)).prefs?.sugg === 'keep');
  check((await call('GET', `/api/agents/${AG}/chat-prefs`)).prefs.sugg === 'keep', 'autosave: stored at once');
  await until(() => cm(d, q3.id)?.querySelector('.cchoices .cchb') && shelf(d).hidden);
  check(cm(d, q3.id)?.querySelectorAll('.cchoices .cchb').length === 2 && shelf(d).hidden, '"Keep all at their message": the buttons stay at the message, no shelf');
  const off = md.querySelector('[data-acset="pin"][value="off"]'); off.checked = true; off.dispatchEvent(new w.Event('change', {bubbles: true}));
  const nl = md.querySelector('[data-acset="notices"][value="line"]'); nl.checked = true; nl.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', `/api/agents/${AG}/chat-prefs`)).prefs?.notices === 'line');
  md.querySelector('[data-m="close"]').click();
  await say('', {approval: {title: 'Delete the old branch'}});
  await fetch(V + `/agent/chats/${ME.id}`, {method: 'POST', headers: AGH, body: JSON.stringify({body: 'New session, summary taken over', kind: 'notice'})});
  await w.eval('chatLoad()'); await until(() => d.querySelector('#chat-msgs .cnotice'));
  check(d.querySelector('#chat-apv')?.hidden, '"Pin approvals at the top" off: nothing pinned');
  check(d.querySelector('#chat-msgs .cnotice.acset-n1'), 'notices "One line"');
  await call('PUT', `/api/agents/${AG}/chat-prefs`, {sugg: 'collect', pin: 'on', notices: 'full'});
  await w.eval('chatLoad()'); await until(() => !d.querySelector('#chat-apv')?.hidden);
  check(!d.querySelector('#chat-apv').hidden && !d.querySelector('#chat-msgs .cnotice.acset-n1'), 'back to the defaults: pinned, the notice in full');
  w.close();

  // ================= freelancer-matrix: agents
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FK);
  const FU = (await call('GET', '/api/state', null, FK)).me;
  check(!(FU.workspaces || []).length, 'freelancer: no organisation');
  const fa = await call('POST', '/api/my/agents', {username: 'fridabot', display_name: 'Frida bot', scopes: ['read', 'tasks:write', 'comments']}, FK);
  const ft = await call('POST', `/api/my/agents/${fa.id}/token`, {}, FK);
  const FH = {Authorization: 'Bearer ' + ft.token, 'Content-Type': 'application/json'};
  const f1 = await sayTo(FU.id, FH, 'Tidy the inbox?', {choices: ['Tidy', 'Later']});
  await sayTo(FU.id, FH, 'Done with the calendar.');
  w = await boot({user: 'frida'}); d = w.document;
  w.eval(`chatOpen(${fa.id})`); await until(() => shelf(d) && !shelf(d).hidden);
  check(/Earlier suggestions \(1\)/.test(shelf(d)?.textContent || ''), 'freelancer: the shelf in the own agent\'s chat');
  click(w, shelf(d).querySelector('[data-act="acsug-tog"]'));
  await until(() => shelf(d).querySelector('.cchb[data-act="chat-choice"]'));
  click(w, shelf(d).querySelector('.cchb[data-act="chat-choice"]'));
  await until(() => shelf(d).hidden);
  const fs = (await call('GET', `/api/agents/${fa.id}/chat`, null, FK)).messages.find(m => m.id === f1.id);
  check(fs?.choice_state === 'answered', 'freelancer: a tap in the shelf answers ' + fs?.choice_state);
  w.close();

  // ================= Firefox 360 / 412 touch
  for (let i = 0; i < 12; i++) await say(`Option set ${i}: which one?`, {choices: [{id: 'a', label: `First ${i}`}, {id: 'b', label: `Second ${i}`}]});
  await say('That is all for now.');
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#chat-sug:not([hidden])')`).catch(() => false)); i++) await sleep(300); await sleep(500); };
  const geo = `(() => { const s = document.querySelector('#chat-sug'), t = s && s.querySelector('.acsug-t'), ci = document.querySelector('#chat-in'); if (!t || !ci) return null;
    const l = s.querySelector('.acsug-l'), sr = s.getBoundingClientRect(), cr = ci.getBoundingClientRect();
    const tg = [...s.querySelectorAll('.acsug-t, .acsug-x, .cchb')].filter(x => x.getBoundingClientRect().height > 0);
    return {above: sr.bottom <= cr.top + 1, h: Math.round(sr.height), tog: Math.round(t.getBoundingClientRect().height), min: Math.round(Math.min(...tg.map(x => x.getBoundingClientRect().height))),
      scroll: l ? l.scrollHeight > l.clientHeight && getComputedStyle(l).overflowY === 'auto' : null, list: l ? Math.round(l.getBoundingClientRect().height) : 0,
      wide: document.documentElement.scrollWidth <= innerWidth, n: (t.textContent.match(/\\((\\d+)\\)/) || [])[1]}; })()`;
  for (const W of [360, 412]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = String(W);
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 780}});
    await o.nav(B + '#agents/' + AG); await ready(ev);
    const g0 = await ev(geo);
    check(g0 && g0.above && g0.tog >= 44 && g0.h <= 60 && g0.n === '10' && g0.wide, `${tag}: folded: one line above the box, 44 px, at most 10 ` + JSON.stringify(g0));
    await shot(`p2233a-${W}-shelf-folded.png`);
    await ev(`(() => { document.querySelector('[data-act="acsug-tog"]').click(); return 1; })()`); await sleep(500);
    const g1 = await ev(geo);
    check(g1 && g1.above && g1.scroll && g1.list <= 0.4 * 780 + 2 && g1.min >= 44 && g1.wide, `${tag}: open: above the box, scrolls inside, capped height, tap targets 44 px ` + JSON.stringify(g1));
    await shot(`p2233a-${W}-shelf-open.png`);
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
