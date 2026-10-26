// 2.46.2 UI tests, part B, own container (start.sh). jsdom:
// - #1665 desktop: a dialog of modal() moves by its header (askConfirm, Settings); it stays inside the window; a double click on
//   the header puts it back in the middle; a button in the header keeps its click; a drag that ends beside the card does not
//   close the dialog (a mousedown on the backdrop still does); a new dialog opens in the middle; touch / phone: no drag
// - #1719 desktop: "Open in its own window" in the agent chat's and a team room's header (gone on touch), a middle click on a
//   conversation opens it too; one window name per chat; /?mini=1#agents/<id> and #team/<id> show only the chat (no Back, no
//   list of conversations), go back to their chat from another address, and keep the UI state to themselves
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'comments,collab,agents,team';
const DESK = {'(hover:hover) and (pointer:fine)': true};
const TOUCH = {'(hover: none)': true, '(hover:hover) and (pointer:fine)': false};
// a pointer event (jsdom may lack PointerEvent: a MouseEvent with the pointer fields)
const pe = (w, el, type, x, y, o = {}) => {
  const C = w.PointerEvent || w.MouseEvent, ev = new C(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, ...o});
  if (!w.PointerEvent) { Object.defineProperty(ev, 'pointerId', {value: 1}); Object.defineProperty(ev, 'pointerType', {value: o.pointerType || 'mouse'}); }
  el.dispatchEvent(ev); return ev;
};
// jsdom has no layout: the card is 400 x 300, centred in 1024 x 768, plus its shift
const fakeRect = (w, card) => { card.getBoundingClientRect = () => { const d = card._dw || {x: 0, y: 0}; return {left: 312 + d.x, top: 234 + d.y, right: 712 + d.x, bottom: 534 + d.y, width: 400, height: 300}; }; };
const shift = card => card.style.transform;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id;
  const L = (await call('POST', '/api/lists', {name: 'Studio'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const team = await call('GET', '/api/team');
  const RID = ((team.rooms || []).find(x => x.kind === 'list' && x.list_id === L) || {}).id;
  check(RID > 0, 'setup: the list room ' + JSON.stringify(team).slice(0, 160));
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Hello studio'});

  // ================= #1665 desktop
  let w = await boot({user: 'alice', hash: 'l/' + L, media: DESK}), d = w.document;
  w.__dialogs = 'manual';  // boot.js answers askConfirm by itself otherwise
  await until(() => w.eval('S.booted'));
  w.eval(`window._cf = askConfirm('Delete the draft?', 'It is gone then.')`);
  let md = await until(() => d.querySelector('.modal.cdlg')), card = md.querySelector('.card'), hd = card.querySelector('h3');
  fakeRect(w, card);
  check(!shift(card), '#1665: a new dialog opens in the middle');
  pe(w, hd, 'pointerdown', 500, 250); pe(w, d, 'pointermove', 600, 300); pe(w, d, 'pointerup', 600, 300);
  check(shift(card) === 'translate(100px, 50px)', '#1665: dragging the header moves the dialog: ' + shift(card));
  pe(w, hd, 'pointerdown', 600, 300); pe(w, d, 'pointermove', 3000, -900); pe(w, d, 'pointermove', 3000, -900);
  await sleep(60);  // 2.87.9 (#1965): a move shows in the next frame
  check(shift(card) === 'translate(312px, -234px)', '#1665: the dialog stays inside the window (top right corner): ' + shift(card));
  // the drag ends over the backdrop: up + click there do not close it
  pe(w, md, 'pointerup', 3000, -900); md.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));
  await sleep(100);
  check(md.isConnected, '#1665: a drag that ends beside the dialog does not close it');
  hd.dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true, cancelable: true}));
  check(!shift(card), '#1665: a double click on the header puts it back in the middle: ' + shift(card));
  // a smaller window keeps a moved dialog inside
  pe(w, hd, 'pointerdown', 500, 250); pe(w, d, 'pointermove', 800, 250); pe(w, d, 'pointerup', 800, 250);
  check(shift(card) === 'translate(300px, 0px)', '#1665: moved right ' + shift(card));
  Object.defineProperty(w, 'innerWidth', {configurable: true, value: 900}); w.dispatchEvent(new w.Event('resize'));
  await sleep(150);
  check(shift(card) === 'translate(188px, 0px)', '#1665: a smaller window pulls the dialog back inside: ' + shift(card));
  Object.defineProperty(w, 'innerWidth', {configurable: true, value: 1024});
  // the keyboard still works (Esc = no), the backdrop still closes
  md.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}));
  check(await until(() => !md.isConnected) && (await w.eval('window._cf')) === false, '#1665: Esc still closes the dialog (no)');
  w.eval(`askConfirm('Again?')`);
  md = await until(() => d.querySelector('.modal.cdlg')); card = md.querySelector('.card');
  check(!shift(card), '#1665: the next dialog opens in the middle again (nothing remembered)');
  md.dispatchEvent(new w.MouseEvent('mousedown', {bubbles: true}));
  check(await until(() => !md.isConnected), '#1665: a mousedown on the backdrop still closes');
  // Settings: the header row with its Back button; the button keeps its click and does not start a drag
  w.eval(`settingsModal('look')`);
  md = await until(() => d.querySelector('.modal.smodal')); card = md.querySelector('.card'); fakeRect(w, card);
  const sb = card.querySelector('.shdr .sback');
  pe(w, sb, 'pointerdown', 330, 250); pe(w, d, 'pointermove', 430, 300); pe(w, d, 'pointerup', 430, 300);
  check(!shift(card), '#1665: a button in the header does not drag');
  pe(w, card.querySelector('.shdr h3'), 'pointerdown', 400, 250); pe(w, d, 'pointermove', 380, 270); pe(w, d, 'pointerup', 380, 270);
  check(shift(card) === 'translate(-20px, 20px)', '#1665: Settings move by their header too: ' + shift(card));
  // a dialog over a dialog moves on its own
  w.eval(`askConfirm('Over it?')`);
  const md2 = await until(() => d.querySelector('.modal.cdlg')), c2 = md2.querySelector('.card'); fakeRect(w, c2);
  pe(w, c2.querySelector('h3'), 'pointerdown', 500, 250); pe(w, d, 'pointermove', 450, 250); pe(w, d, 'pointerup', 450, 250);
  check(shift(c2) === 'translate(-50px, 0px)' && shift(card) === 'translate(-20px, 20px)', '#1665: stacked dialogs move each on their own: ' + shift(c2) + ' / ' + shift(card));
  w.eval(`$$('.modal').forEach(m => m.remove())`);

  // ================= #1719 desktop: the button and the middle click
  await w.eval(`(() => { window._wo = []; window.open = (u, n, f) => { window._wo.push([u, n, f]); return {focus() {}}; }; return 1; })()`);
  w.eval(`chatOpen(${AG})`);
  // 2.350.0 (#3317): "Open in its own window" is an entry of the agent chat header's ⋯ menu
  await until(() => d.querySelector('#achat [data-act="chat-head-menu"]'));
  const owin = async () => { d.querySelector('#achat [data-act="chat-head-menu"]').click(); return until(() => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(x => x.textContent.trim() === 'Open in its own window')); };
  let ab = await owin();
  check(!!ab && !d.querySelector('#achat [data-dwchat]'), '#1719: the agent chat header menu has "Open in its own window"');
  ab?.click();
  let wo = w.eval('window._wo');
  check(wo.length === 1 && wo[0][0] === `/?mini=1#agents/${AG}` && wo[0][1] === `kalmido-chat-a-${AG}` && /popup/.test(wo[0][2]), '#1719: the agent chat opens in its window ' + JSON.stringify(wo));
  ab = await owin(); ab?.click();
  wo = w.eval('window._wo');
  check(wo.length === 2 && wo[1][1] === wo[0][1], '#1719: the same chat comes back to the same window name');
  w.eval('chatClose()');
  w.location.hash = 'team/' + RID;
  const tb = await until(() => d.querySelector(`.tcrhead [data-dwchat="team/${RID}"]`));
  check(!!tb, '#1719: the team room header has "Open in its own window"');
  tb?.click();
  wo = w.eval('window._wo');
  check(wo.length === 3 && wo[2][0] === `/?mini=1#team/${RID}` && wo[2][1] === `kalmido-chat-t-${RID}`, '#1719: the team room opens in its window ' + JSON.stringify(wo[2]));
  const row = d.querySelector(`.tcrow[data-rid="${RID}"]`);
  row?.dispatchEvent(new w.MouseEvent('auxclick', {bubbles: true, cancelable: true, button: 1}));
  wo = w.eval('window._wo');
  check(wo.length === 4 && wo[3][1] === `kalmido-chat-t-${RID}`, '#1719: a middle click on the conversation opens its window');
  w.close();

  // ================= #1719 touch: nothing changes
  w = await boot({user: 'alice', hash: 'team/' + RID, media: TOUCH}); d = w.document; w.__dialogs = 'manual';
  await until(() => d.querySelector('.tcrhead'));
  await sleep(300);
  check(!d.querySelector('[data-dwchat]'), '#1719: touch: no "Open in its own window"');
  // #1665 touch: no drag
  w.eval(`askConfirm('Touch?')`);
  md = await until(() => d.querySelector('.modal.cdlg')); card = md.querySelector('.card'); fakeRect(w, card);
  pe(w, card.querySelector('h3'), 'pointerdown', 500, 250); pe(w, d, 'pointermove', 600, 300); pe(w, d, 'pointerup', 600, 300);
  check(!shift(card), '#1665: touch / phone: the dialog does not move');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true, media: DESK}); d = w.document; w.__dialogs = 'manual';
  await until(() => w.eval('S.booted'));
  w.eval(`askConfirm('Narrow?')`);
  md = await until(() => d.querySelector('.modal.cdlg')); card = md.querySelector('.card'); fakeRect(w, card);
  pe(w, card.querySelector('h3'), 'pointerdown', 500, 250); pe(w, d, 'pointermove', 600, 300); pe(w, d, 'pointerup', 600, 300);
  check(!shift(card), '#1665: a phone width: the dialog does not move');
  w.close();

  // ================= #1719 the windows
  w = await boot({user: 'alice', path: '?mini=1', hash: 'agents/' + AG, media: DESK}); d = w.document;
  await until(() => d.querySelector('#view .chview #chat-in'));
  check(d.documentElement.classList.contains('mini') && d.documentElement.classList.contains('mini-chat'), '#1719: the agent window is a chat window');
  check(!!d.querySelector('#view .chview #chat-in') && !d.querySelector('#achat:not(.hidden) #chat-in'), '#1719: the agent chat fills the window (not the side panel)');
  check(!d.querySelector('[data-dwchat]'), '#1719: the window has no "Open in its own window" itself');
  await until(() => /^Claude · /.test(d.title));
  check(/^Claude · /.test(d.title), '#1719: the window title is the agent: ' + d.title);
  w.location.hash = 'today';
  await until(() => w.location.hash === '#agents/' + AG);
  check(w.location.hash === '#agents/' + AG, '#1719: another address goes back to the chat: ' + w.location.hash);
  const before = JSON.stringify(Object.keys(w.__store).sort());
  w.eval(`LS.set('chatLast', 999); LS.set('lastKey', 'today')`);
  check(w.__store['tasks.chatLast'] !== '999' && JSON.stringify(Object.keys(w.__store).sort()) === before, '#1719: the window keeps the UI state to itself');
  w.close();
  w = await boot({user: 'alice', path: '?mini=1', hash: 'team/' + RID, media: DESK}); d = w.document;
  const msg = await until(() => [...d.querySelectorAll('#tc-msgs .cbub')].some(x => /Hello studio/.test(x.textContent)));
  check(msg && !!d.querySelector('#tc-in'), '#1719: the team window shows the conversation and its box');
  // jsdom applies no style sheet: the rule that hides the list of conversations, Back and the top bar in a chat window
  const css = await require('./boot').allCss(); // 2.65.0 (#1824): + the module stylesheets
  check(d.documentElement.classList.contains('mini-chat') && /html\.mini-chat #top,html\.mini-chat \.chback,html\.mini-chat \.tcback,html\.mini-chat \.tclist\{display:none!important\}/.test(css), '#1719: no list of conversations, Back or top bar in the window');
  // a new message comes live (the box without focus: the poll holds team updates back while someone types, as in any tab)
  d.activeElement?.blur?.();
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Live from Bob'}, BCK);
  w.eval('teamChanged()');  // what the change poll calls (like p2170_ui)
  const live = await until(() => [...d.querySelectorAll('#tc-msgs .cbub')].some(x => /Live from Bob/.test(x.textContent)), 60);
  check(live, '#1719: a new message arrives live in the window');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
