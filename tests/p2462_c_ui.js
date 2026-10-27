// 2.46.2 UI tests, part C (#1712 #1651 #1666 #1726 #1660), own container (start.sh). jsdom, invented data only:
// - #1712 the "New API token" button is a solid danger button (never red text on the accent fill)
// - #1651 the settings search field keeps password managers out (readonly until focus, own name); secret fields are new-password
// - #1666 every comment has Copy / Copy as Markdown (mentions as names), also another person's
// - #1726 the "differs from the standard" note has an x; it stays away until the arrangement changes (setting wgstd_hide)
// - #1660 only NEW comments / messages fade in (not the first fill, not older ones), reduced motion = none, "New comment" pill
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,time,progress,kanban,timeline,fields,team';
const items = d => [...d.querySelectorAll('#pop [role="menuitem"]')];
const item = (d, t) => items(d).find(x => (x.querySelector('.ml')?.firstChild?.textContent || x.textContent).trim() === t || x.getAttribute('title') === t);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me.id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const P = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  await call('PATCH', `/api/lists/${P}/overview`, {description: '## Goal\nA new site.'});
  const T = (await call('POST', '/api/tasks', {title: 'Write the copy', list_id: P})).id;
  const cm = (ck, body) => call('POST', `/api/tasks/${T}/comments`, {body}, ck);
  await cm(BCK, `Welcome, <@${ME}>, **please** read this`);
  await cm(CK, 'Second comment');

  // ================= #1726: the setting
  check((await call('PATCH', '/api/settings', {wgstd_hide: '{"home":"abc1"}'})).http === 200, '#1726: wgstd_hide accepts an object of short strings');
  check((await call('PATCH', '/api/settings', {wgstd_hide: '[1]'})).http === 400, '#1726: wgstd_hide refuses a list');
  check((await call('PATCH', '/api/settings', {wgstd_hide: '{"home":' + JSON.stringify('x'.repeat(60)) + '}'})).http === 400, '#1726: wgstd_hide refuses a long value');
  await call('PATCH', '/api/settings', {wgstd_hide: '{}'});

  // ================= #1666 / #1660: comments
  let w = await boot({user: 'alice', hash: 't/' + T}), d = w.document;
  await until(() => d.querySelectorAll('#d-tl-items .cm').length === 2);
  check(d.querySelectorAll('#d-tl-items .cm').length === 2, 'two comments shown');
  check(!d.querySelector('#d-tl-items .cm.cfin'), '#1660: opening a task: no comment fades in');
  check(d.querySelectorAll('#d-tl-items .cm [data-act="cm-copy"]').length === 2, '#1666: a Copy button on every comment (also Bob\'s)');
  let clip = null; w.navigator.clipboard = {writeText: async t => { clip = t; }};
  click(w, d.querySelector('#d-tl-items .cm [data-act="cm-copy"]')); await until(() => item(d, 'Copy as Markdown'));
  check(item(d, 'Copy') && item(d, 'Copy as Markdown'), '#1666: the menu has Copy and Copy as Markdown');
  click(w, item(d, 'Copy as Markdown')); await until(() => clip);
  check(clip === 'Welcome, @Alice, **please** read this', '#1666: the Markdown text with the mention as a name: ' + clip);
  // a new comment (Bob) fades in, the others stay
  await cm(BCK, 'Third comment');
  w.eval(`loadTimeline(${T})`); await until(() => d.querySelectorAll('#d-tl-items .cm').length === 3);
  const cms = [...d.querySelectorAll('#d-tl-items .cm')];
  check(cms[2].classList.contains('cfin') && !cms[0].classList.contains('cfin') && !cms[1].classList.contains('cfin'), '#1660: only the new comment fades in');
  // scrolled up (the last comment out of view) -> the pill; a tap hides it
  check(!!d.querySelector('#cm-new') && d.querySelector('#cm-new').classList.contains('hidden'), '#1660: the pill exists and starts hidden');
  w.eval(`cf_visible = () => false`);
  await cm(BCK, 'Fourth comment'); w.eval(`loadTimeline(${T})`); await until(() => d.querySelectorAll('#d-tl-items .cm').length === 4);
  check(!d.querySelector('#cm-new').classList.contains('hidden') && /New comment/.test(d.querySelector('#cm-new').textContent), '#1660: "New comment" shows when scrolled up and something new arrives');
  w.eval(`Element.prototype.scrollIntoView = function () {}`);
  click(w, d.querySelector('#cm-new')); await sleep(50);
  check(d.querySelector('#cm-new').classList.contains('hidden'), '#1660: a tap hides the pill');
  // reduced motion: nothing animates
  w.eval(`window.matchMedia = () => ({matches: true})`);
  await cm(BCK, 'Fifth comment'); w.eval(`loadTimeline(${T})`); await until(() => d.querySelectorAll('#d-tl-items .cm').length === 5);
  check(!d.querySelector('#d-tl-items .cm.cfin'), '#1660: reduced motion switches the fade off');
  // cf_after unit: seed quiet, older ids quiet, newer ones animate
  const unit = w.eval(`(() => {
    const b = document.createElement('div'); b.id = 'cf-unit'; document.body.appendChild(b);
    const set = ids => { b.innerHTML = ids.map(i => '<div data-mid="a:' + i + '"></div>').join(''); };
    window.matchMedia = () => ({matches: false});
    set([10, 11]); const a1 = cf_after(b, 's1').length;
    set([10, 11, 12]); const a2 = cf_after(b, 's1').length;
    set([5, 10, 11, 12]); const a3 = cf_after(b, 's1').length;
    set([5, 10, 11, 12, 13]); const a4 = cf_after(b, 's1', true).length;
    set([5, 10, 11, 12, 13, 14]); const a5 = cf_after(b, 's2').length;
    return [a1, a2, a3, a4, a5].join(',');
  })()`);
  check(unit === '0,1,0,0,0', '#1660: first fill quiet, a newer id animates, an older page / skipped / another conversation do not: ' + unit);
  w.close();

  // ================= #1660: the team chat (a list room)
  const RID = (await call('GET', '/api/team')).rooms.find(x => x.kind === 'list' && x.list_id === P)?.id;
  check(!!RID, 'the list has a team room');
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'First hello'}, BCK);
  w = await boot({user: 'alice', hash: 'team/' + RID}); d = w.document;
  await until(() => d.querySelector('#tc-msgs .cmsg'));
  check(!d.querySelector('#tc-msgs .cfin') && !!d.querySelector('#tc-new.hidden'), '#1660: the room opens without a fade and with a hidden "New message" pill');
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Second hello'}, BCK);
  w.eval(`loadRoom(S.tc.rid).then(() => tcPatch())`);
  await until(() => d.querySelectorAll('#tc-msgs .cmsg').length === 2);
  check(d.querySelectorAll('#tc-msgs .cmsg')[1]?.classList.contains('cfin') && !d.querySelectorAll('#tc-msgs .cmsg')[0].classList.contains('cfin'), '#1660: a new team message fades in, the old one stays');
  // scrolled up: the pill (jsdom has no layout: fake the box height)
  w.eval(`(() => { const b = document.getElementById('tc-msgs'); Object.defineProperty(b, 'scrollHeight', {value: 1000, configurable: true}); Object.defineProperty(b, 'clientHeight', {value: 300, configurable: true}); b.scrollTop = 0; })()`);
  await call('POST', `/api/team/rooms/${RID}/messages`, {body: 'Third hello'}, BCK);
  w.eval(`loadRoom(S.tc.rid).then(() => tcPatch())`);
  await until(() => d.querySelectorAll('#tc-msgs .cmsg').length === 3);
  check(!d.querySelector('#tc-new').classList.contains('hidden'), '#1660: scrolled up + a new message: "New message" shows');
  click(w, d.querySelector('#tc-new')); await sleep(50);
  check(d.querySelector('#tc-new').classList.contains('hidden'), '#1660: a tap hides the pill');
  w.close();

  // ================= #1712 / #1651
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval(`agTokenModal({name: 'Helper'}, '/api/none')`); await sleep(80);
  const tb = d.querySelector('.modal [data-m="ok"]');
  check(tb && tb.classList.contains('danger') && tb.classList.contains('solid') && !tb.classList.contains('pri'), '#1712: the new-token button is danger solid, not pri');
  check(/Helper/.test(d.querySelector('.modal h3').textContent), '#1712: the title names the agent');
  d.querySelector('.modal').remove();
  w.eval(`settingsModal()`); await until(() => d.querySelector('#s-search'));
  const sq = d.querySelector('#s-search');
  check(sq.getAttribute('name') === 'kalmido-settings-search' && sq.getAttribute('autocomplete') === 'off' && sq.hasAttribute('data-1p-ignore') && sq.getAttribute('data-lpignore') === 'true' && sq.hasAttribute('data-bwignore'), '#1651: the search field has its own name and the password-manager opt-outs');
  check(sq.hasAttribute('readonly'), '#1651: readonly until it is used');
  sq.dispatchEvent(new w.FocusEvent('focus')); check(!sq.hasAttribute('readonly'), '#1651: focus makes it writable');
  const cur = d.querySelector('#a-cur');
  check(!cur || (cur.previousElementSibling?.getAttribute('autocomplete') === 'username' && cur.getAttribute('autocomplete') === 'current-password'), '#1651: the account password has a hidden username field before it');
  w.close();

  // ================= #1726: the note in the UI (the project page)
  const lay = async () => call('GET', `/api/lists/${P}/layout`);
  const pov = {'tasks.pov': JSON.stringify([P])};
  w = await boot({user: 'alice', hash: 'l/' + P, ls: pov}); d = w.document;
  await until(() => d.querySelector('#view .pov .lysix .povs'));
  click(w, d.querySelector('.lyb[data-lyk="desc"] [data-act="wg-more"]')); await until(() => item(d, 'Tall'));
  click(w, item(d, 'Tall'));
  await until(() => d.querySelector('.wgstd [data-act="wg-hide"]'));
  check(!!d.querySelector('.wgstd [data-act="wg-hide"]'), '#1726: the note has an x');
  click(w, d.querySelector('.wgstd [data-act="wg-hide"]'));
  await until(() => !d.querySelector('.wgstd'));
  check(!d.querySelector('.wgstd'), '#1726: the x hides the note');
  const set1 = await until(async () => { const s = (await call('GET', '/api/state')).settings?.wgstd_hide; return s && s !== '{}' ? s : null; });
  check(!!set1 && Object.keys(JSON.parse(set1)).length === 1, '#1726: remembered in the settings (all devices): ' + set1);
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + P, ls: pov}); d = w.document;
  await until(() => d.querySelector('#view .pov .lysix .povs')); await sleep(300);
  check(!d.querySelector('.wgstd'), '#1726: after a reload the note stays away');
  click(w, d.querySelector('.lyb[data-lyk="desc"] [data-act="wg-more"]')); await until(() => item(d, '⅓'));
  click(w, item(d, '⅓'));
  await until(() => d.querySelector('.wgstd'));
  check(!!d.querySelector('.wgstd'), '#1726: another change of the arrangement shows the note again');
  w.close();

  console.log(`p2462_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
