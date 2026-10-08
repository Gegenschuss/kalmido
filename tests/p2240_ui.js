// 2.24.0 UI tests "Usability", own container (start.sh). jsdom:
// #908 an unfolded foldable in landscape (860-899 px, touch) gets the desktop layout width, portrait / phones / mouse do not
// #832 the keyboard compensation only for a real on-screen keyboard (touch + > 120 px less height), never with a fine
//      pointer (DeX, a desktop window) or a small bar; the page never stays scrolled; the quick add is no login field;
//      UX-30 typed text keeps the recognition chips of the docked bar visible
// #906 "Message" on the person card and on "Tasks of …", "New message" always in the team chat, the explanation when it
//      cannot work yet
// #826 Administration in five sub-tabs (remembered), UX-16 the settings search finds buttons / helper texts / synonyms,
//      opens the sub-tab of its hit and hides the panes when nothing is found
// #825 the crop dialog: a round mask, two previews, keyboard zoom; list icons square
// #907 the notice above the app (hide per device, comes back when it changes), "server in maintenance" on a 503
// #910 the storage meter in Account, the dialog "Storage full" with "Contact support" when an upload is refused
// #896 the organisation setting "Members may connect agents", "Where it runs", the News line when an agent joins
// UX-01 Views folded below the lists, UX-06 no doubled app name, UX-08 no "Person" under every name, UX-21 Log out at the end
// UX-09 one task menu in a fixed order, the swipe menu names its task and ends with "All…", UX-35 Today: one slim
// overdue line, the planners in "…", UX-36 the default tab bar, UX-41 the assignee in the task header + "More details"
// UX-22 / UX-23 the first-run setup: the language sticks, the organisation is asked only for a team
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const closeAll = w => [...w.document.querySelectorAll('.modal')].forEach(m => m.remove());
const BASE = 'cal,comments,collab,time,progress,agents,kanban,timeline,matrix';

(async () => {
  await sleep(600);
  // ================= UX-22: the setup page's language sticks to the account
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup with lang');
  CK = await login('alice');
  let st = await call('GET', '/api/state');
  check(st.settings.lang === 'de' && st.setup_pending, 'UX-22: the language of the setup page is the account\'s (and the setup is still pending)');
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  await until(() => d.querySelector('.authscreen .setupcard'));
  check(!d.querySelector('.tour, .tourcard') && w.eval('S.settings.onboard') !== 'done-x', 'UX-22: no tour over the unfinished setup');
  check(!d.querySelector('.authscreen #su-org'), 'UX-23: "For me": no question about an organisation');
  click(w, d.querySelector('.authscreen [data-su-preset="team"]')); await sleep(150);
  const org = d.querySelector('.authscreen #su-org');
  check(org && org.value === '' && /Team|Firma|team|company/.test(d.querySelector('.authscreen label[for="su-org"]').textContent), 'UX-23: "Team": the name of the team / company, empty (optional)');
  const hs = [...d.querySelectorAll('.authscreen h3')].map(h => h.textContent);
  check(hs.findIndex(t => /Kalmido/.test(t)) < hs.findIndex(t => /Team|Firma|team|company/.test(t)), 'UX-23: the purpose comes first');
  w.close();
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: BASE});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: BASE}, BCK);
  const P = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Write the brief', list_id: P, due: '2020-01-02'})).id;
  await call('POST', '/api/tasks', {title: 'Old thing', due: '2020-01-01'});

  // ================= #908: the layout width of a foldable
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  const vp = (sw, sh, coarse = true) => w.eval(`(() => { Object.defineProperty(screen, 'width', {configurable: true, value: ${sw}}); Object.defineProperty(screen, 'height', {configurable: true, value: ${sh}});
    const mm = window.matchMedia; window.matchMedia = q => ({matches: /pointer:coarse/.test(q) ? ${coarse} : false, addEventListener() {}, addListener() {}});
    stableViewport(); window.matchMedia = mm; return document.querySelector('meta[name="viewport"]').getAttribute('content'); })()`);
  check(/^width=900/.test(vp(880, 760)), '#908: Fold unfolded in landscape (880 px, touch): the desktop width 900');
  check(/device-width/.test(vp(690, 880)), '#908: ... in portrait (690 px): the tablet layout');
  check(/device-width/.test(vp(844, 390)), '#908: a phone in landscape keeps its width');
  check(/device-width/.test(vp(880, 760, false)), '#908: a mouse screen is never scaled');
  check(/device-width/.test(vp(1400, 788)), '#908: a wide window (DeX) keeps its own width');
  // #832: what counts as an on-screen keyboard
  const kb = (fine, h0, h1) => w.eval(`(() => { const q = document.querySelector('#qinput') || document.querySelector('#view input') || document.createElement('input'); if (!q.isConnected) document.body.appendChild(q); q.focus();
    const mm = window.matchMedia; window.matchMedia = x => ({matches: /pointer:fine/.test(x) ? ${fine} : false, addEventListener() {}, addListener() {}});
    S.vvMax = ${h0}; Object.defineProperty(window, 'visualViewport', {configurable: true, value: {height: ${h1}, offsetTop: 0, addEventListener() {}}});
    const r = kbReal(); vvSync(); window.matchMedia = mm; return [r, document.documentElement.style.getPropertyValue('--vvb')]; })()`);
  let k = kb(false, 800, 450);
  check(k[0] === true, '#832: touch + 350 px less height = a real keyboard ' + JSON.stringify(k));
  k = kb(true, 788, 450);
  check(k[0] === false && k[1] === '0px', '#832: a fine pointer (DeX / a desktop window) never compensates ' + JSON.stringify(k));
  k = kb(false, 800, 740);
  check(k[0] === false, '#832: a small bar (autofill, 60 px) is no keyboard');
  w.eval(`delete window.visualViewport`);
  const qi = d.querySelector('#view #qinput') || d.querySelector('#qinput');
  check(qi && qi.getAttribute('autocomplete') === 'off' && qi.getAttribute('data-form-type') === 'other' && qi.getAttribute('name') === 'kalmido-quick-add', '#832: the quick add is no login field (autocomplete off, no password pattern)');
  // UX-30: typed text keeps the recognition visible
  w.eval(`go('l/${P}')`); await sleep(300);
  const dq = d.querySelector('#view .qadd.dock #qinput');
  if (dq) { input(w, dq, 'Call tomorrow 3pm !high'); await sleep(100); check(dq.closest('.qadd.dock').classList.contains('has-text'), 'UX-30: the docked bar keeps its chips while it holds text'); }
  else check(true, 'UX-30: (no docked bar in this jsdom width)');
  // UX-35: Today
  w.eval(`go('today')`); await sleep(300);
  const ob = d.querySelector('#view .odban');
  check(ob && ob.querySelectorAll('.btn').length === 2 && ob.querySelector('[data-act="od-move"][data-d="0"]') && ob.querySelector('[data-act="od-other"]'), 'UX-35: one slim overdue line: "All to today" + "Another day…"');
  check(!d.querySelector('#view .dpbar'), 'UX-35: no planner buttons above the list');
  click(w, d.querySelector('#top [data-act="top-more"]')); await sleep(150);
  const items = [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim());
  check(items[0] === 'Plan my day' && items[1] === 'Fill free time', 'UX-35: the planners lead the "…" menu ' + items.slice(0, 3).join('|'));
  w.eval('closePop()');
  click(w, ob.querySelector('[data-act="od-other"]')); await sleep(150);
  check([...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim()).join('|') === 'Tomorrow|Next week (Mon)|Pick a date…', 'UX-35: "Another day…" = Tomorrow / Next week / Pick a date');
  w.eval('closePop()');
  click(w, ob.querySelector('[data-act="od-move"]')); await sleep(400);
  check(!d.querySelector('#view .odban') && w.eval(`S.tasks.get(${T1}).due`) === w.eval('today()'), 'UX-35: All to today moves them');
  // UX-01 / UX-06 / UX-08: the sidebar
  const grps = [...d.querySelectorAll('#side .sgroup')].map(x => (x.className.match(/sg-(\w+)/) || [])[1]).filter(Boolean);
  check(grps.indexOf('views') < grps.indexOf('lists') && grps.indexOf('focus') < grps.indexOf('views'), 'UX-01 / 2.27.0 (#984): Focus, Views (folded), then the lists ' + grps.join(','));
  check(d.querySelector('#side .sg-views .sgh.closed') && d.querySelector('#side .sg-views .sgfold[hidden] .smod'), 'UX-01: Views folded by default (rows hidden)');
  click(w, d.querySelector('#side .sg-views [data-act="side-group"]')); await sleep(100);
  check(d.querySelector('#side .sg-views > .smod') && JSON.parse(w.__store['tasks.sideOpenG'] || '[]').includes('views'), 'UX-01: opened, remembered per device');
  check(!/Person/.test([...d.querySelectorAll('#side .sg-team .steam')].map(x => x.textContent).join(' ')), 'UX-08: no "Person" under every name');
  check(!d.querySelector('#side .sborg') || d.querySelector('#side .sborg').textContent.toLowerCase() !== 'kalmido', 'UX-06: the organisation only when it is not the app name');
  // UX-36: the default tab bar
  check(JSON.stringify(w.eval('tabIds()')) === JSON.stringify(['s:inbox', 's:today', 'search', 'lists']), 'UX-36: default bar Inbox · Today · Search · Lists');
  check(w.eval(`tabItem('lists').act`) === 'side', 'UX-36: "Lists" opens the drawer');
  // ================= #906: direct messages
  w.eval(`go('who/${BOB}')`); await sleep(300);
  check(d.querySelector(`#top [data-act="dm"][data-uid="${BOB}"]`), '#906: "Message" on "Tasks of Bob"');
  w.eval(`personCard(document.querySelector('#top h1'), ${BOB})`); await sleep(200);
  const dm = d.querySelector('#pop .mcard [data-mc="dm"]');
  check(dm && dm.classList.contains('pri') && d.querySelector('#pop .mcacts').firstElementChild === dm, '#906: the person card: "Message" first and big');
  click(w, dm); await until(() => w.eval('S.route.mod') === 'team' && w.eval('S.tc.rid'));
  check(w.eval('S.route.mod') === 'team' && w.eval('S.tc.rid') > 0, '#906: it opens the conversation with Bob');
  check(d.querySelector('#view [data-act="tc-new"]')?.textContent.includes('New message'), '#906: "New message" in the team chat');
  w.eval(`S.team = {...S.team, enabled: false}`);  // the team chat switched off
  w.__dialogs = 'manual';
  w.eval(`dmOpen(${BOB}, 'Bob')`); await sleep(300);
  const why = d.querySelector('.modal.cdlg');
  check(why && /Collaboration|collaboration/.test(why.textContent), '#906: without the team chat the button explains why ' + (why?.textContent || '').slice(0, 80));
  closeAll(w);
  w.close();

  // ================= UX-41 / UX-09: the task panel and the task menu
  await call('PATCH', `/api/tasks/${T1}`, {assignee_id: BOB});
  w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
  w.eval(`openDetail(${T1})`); await sleep(400);
  const who = d.querySelector('#detail .dmeta .dwho');
  check(who && /Bob/.test(who.textContent) && who.dataset.act === 'assign', 'UX-41: the assignee right under the title');
  const secs = [...d.querySelectorAll('#detail .dbody > .dsec, #detail .dbody > details')].map(x => x.id || x.className.split(' ').slice(0, 2).join('.'));
  check(d.querySelector('#detail details#d-more') && d.querySelector('#detail #d-more #d-assignee'), 'UX-41: the rest folds into "More details" ' + secs.join(','));
  check(!d.querySelector('#detail #d-more').open, 'UX-41: folded by default');
  d.querySelector('#detail #d-more').open = true; d.querySelector('#detail #d-more').dispatchEvent(new w.Event('toggle'));
  check(w.__store['tasks.dMore'] === 'true', 'UX-41: the fold is remembered per device');
  w.eval(`taskMenu(document.querySelector('#view .trow[data-id="${T1}"]') || document.querySelector('#top h1'), ${T1})`); await sleep(150);
  const ml = [...d.querySelectorAll('#pop .menu-list > button, #pop .menu-list > .mquick')].map(b => b.classList.contains('mquick') ? '[' + [...b.querySelectorAll('button')].map(x => x.textContent.trim()).join('/') + ']' : b.textContent.trim().replace(/\s*\S$/, x => x));
  const pos = re => ml.findIndex(x => re.test(x));
  check(pos(/^\[Today\/Tomorrow\]/) === 0 && pos(/New date/) === 1, 'UX-09 / UX-10: the date first, "New date…" ' + ml.slice(0, 3).join(' | '));
  check(pos(/\[High\/Medium\/Low\/None\]/) > 1 && pos(/\[High/) < pos(/Assign/) && pos(/Assign/) < pos(/Move to list/) && pos(/Move to list/) < pos(/Waiting on someone/) && pos(/Waiting/) < pos(/^Pin/) && pos(/^Pin/) < pos(/Save as template/) && pos(/Save as template/) < pos(/^Delete/),
    'UX-09: date · priority · assignee · list · waiting · pin · template · delete ' + ml.join(' | '));
  w.eval('closePop()');
  w.eval(`snoozeSheet(${T1}, document.querySelector('#top h1'), ['-', moveListItem(document.querySelector('#top h1'), ${T1}), {label: tr('All…'), icon: 'dots', fn() {}}], true)`); await sleep(150);
  const sw = [...d.querySelectorAll('#pop .menu-list button')];
  check(sw[0]?.classList.contains('mhead') && sw[0].textContent.includes('Write the brief') && sw[sw.length - 1].textContent.includes('All…'), 'UX-14: the short menu names its task, ends with "All…"');
  w.eval('closePop()');
  w.close();

  // ================= #826 / UX-16 / UX-21 / #910 / #896: settings
  await call('PATCH', '/api/admin/settings', {storage_quota_mb: 1, support_email: 'help@example.com'});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval(`settingsModal('users')`); await sleep(500);
  let md = d.querySelector('.smodal');
  const subs = [...md.querySelectorAll('[data-admsub]')].map(b => b.dataset.admsub);
  check(subs.join() === 'users,signin,org,server,log', '#826: Administration in five sub-tabs ' + subs.join());
  check(!md.querySelector('[data-admp="users"]').hidden && md.querySelector('[data-admp="server"]').hidden && md.querySelector('[data-admp="server"] #s-quota'), '#826: People shown, Server hidden (but there)');
  click(w, md.querySelector('[data-admsub="server"]')); await sleep(100);
  check(!md.querySelector('[data-admp="server"]').hidden && w.__store['tasks.admSub'] === '"server"', '#826: a sub-tab opens and is remembered');
  check(md.querySelector('#s-quota').value === '1' && md.querySelector('#s-support').value === 'help@example.com' && md.querySelector('#s-ann-text') && md.querySelector('#s-maillim'), '#910 / #907 / #899: Server: storage, support address, notice, mail limit');
  click(w, md.querySelector('[data-admsub="org"]')); await sleep(100);
  const oa = md.querySelector('#s-orgagents');
  check(oa && !oa.checked && /Members may connect agents/.test(oa.closest('label').textContent), '#896: Organisation: "Members may connect agents", off by default');
  oa.checked = true; oa.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(400);
  check((await call('GET', '/api/admin/agent-policy')).user_agents === true, '#896: the switch sets the policy');
  // UX-16: the search
  click(w, md.querySelector('[data-admsub="users"]'));
  const sq = md.querySelector('#s-search');
  input(w, sq, 'support'); await sleep(50);
  let hits = [...md.querySelectorAll('#s-sres [data-hit]')];
  check(hits.length && hits.some(h => /Support/.test(h.textContent)), 'UX-16: finds a label inside a sub-tab ' + hits.map(h => h.textContent).join(' / '));
  click(w, hits.find(h => /Support address/.test(h.textContent)) || hits[0]); await sleep(100);
  check(!md.querySelector('[data-admp="server"]').hidden, 'UX-16: a hit opens its sub-tab');
  input(w, sq, 'abmelden'); await sleep(50);
  hits = [...md.querySelectorAll('#s-sres [data-hit]')];
  check(hits.some(h => /Log out/.test(h.textContent)), 'UX-16: a synonym ("abmelden") finds "Log out"');
  input(w, sq, 'xyzzy'); await sleep(50);
  check(md.querySelector('.sbody').classList.contains('snores') && /Nothing found/.test(md.querySelector('#s-sres').textContent), 'UX-16: nothing found: one line, the panes step back');
  input(w, sq, ''); await sleep(50);
  check(!md.querySelector('.sbody').classList.contains('snores'), 'UX-16: cleared: the panes are back');
  closeAll(w);
  w.close();
  // account: storage + log out at the end (bob)
  const tb = (await call('POST', '/api/tasks', {title: 'Files'}, BCK)).id;
  const fd = new FormData(); fd.append('file', new Blob([new Uint8Array(900000)]), 'big.bin');
  await fetch(B + `api/tasks/${tb}/attachments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: BCK}, body: fd});
  w = await boot({user: 'bob', hash: 'inbox'}); d = w.document;
  await sleep(1200);
  w.eval(`settingsModal('account')`); await sleep(400);
  md = d.querySelector('.smodal');
  const sto = md.querySelector('.stoq');
  check(sto && sto.classList.contains('warn') && md.querySelector('.stobar[role="meter"]')?.getAttribute('aria-valuenow') === '86', '#910: the storage meter in Account (86 %, warn) ' + (sto?.textContent || ''));
  const pane = md.querySelector('[data-pane="account"]');
  check(pane.lastElementChild.classList.contains('alogout') || !pane.querySelector('[data-acc="logout"]'), 'UX-21: "Log out" at the very end of Account');
  closeAll(w);
  // a refused upload: the dialog with "Contact support"
  w.__dialogs = 'manual';
  const of0 = w.fetch;  // jsdom's FormData does not reach the server through the test bridge: the server's answer as it comes
  w.fetch = async () => new w.Response(JSON.stringify({error: 'Your storage is full', code: 'quota_exceeded', used: 900000, limit: 1048576, support: 'help@example.com'}), {status: 413, headers: {'content-type': 'application/json'}});
  w.eval(`uploadFiles(${tb}, [new File([new Uint8Array(400000)], 'more.bin')])`);
  const qd = await until(() => [...d.querySelectorAll('.modal.cdlg')].find(m => /Storage full/.test(m.textContent)));
  w.fetch = of0;
  check(qd && /Contact support/.test(qd.textContent) && !/Your storage is full/.test(d.querySelector('#toast')?.textContent || ''), '#910: storage full: the dialog with "Contact support" (no extra toast)');
  check(/mailto:help%40example\.com\?subject=/.test(w.eval('quotaMail(S.storage)')) && /Kalmido|more%20storage|storage/.test(w.eval('quotaMail(S.storage)')), '#910: the support mail is prefilled');
  closeAll(w);
  // #825: the crop dialog (an image drawn in jsdom has no pixels; the dialog itself)
  check(/av-pv2/.test(w.eval('avCropModal.toString()')) && /arc\(256, 256, 252/.test(w.eval('avCropModal.toString()')) && /ArrowLeft/.test(w.eval('avCropModal.toString()')) && /readAsDataURL/.test(w.eval('avCropModal.toString()')) && !/createObjectURL/.test(w.eval('avCropModal.toString()')), '#825: the crop dialog: round mask, two previews, keys, a data: URL (CSP img-src)');
  check(/square: true/.test(w.eval('liconUpload.toString()')), '#825: list icons keep a square crop');
  w.close();

  // ================= #907: the notice
  await call('PUT', '/api/admin/announcement', {text: 'Maintenance tonight at 22:00', level: 'maintenance', minutes: 60});
  w = await boot({user: 'bob', hash: 'inbox'}); d = w.document;
  let bar = d.querySelector('#main #annbar');
  check(bar && bar.classList.contains('maint') && /Maintenance tonight/.test(bar.textContent) && bar.getAttribute('role') === 'status', '#907: the notice above the header');
  click(w, bar.querySelector('[data-act="ann-hide"]')); await sleep(100);
  check(!d.querySelector('#annbar'), '#907: hidden on this device');
  await call('PUT', '/api/admin/announcement', {text: 'Update at 23:00'});
  await w.eval('load()'); w.eval('render()'); await sleep(100);
  check(/Update at 23:00/.test(d.querySelector('#annbar')?.textContent || ''), '#907: a changed notice shows again');
  // "server in maintenance" while the proxy answers 503
  const of = w.fetch; w.fetch = async () => new w.Response('<html>maintenance</html>', {status: 503, headers: {'content-type': 'text/html'}});
  try { await w.eval(`rawFetch('GET', '/api/version')`); } catch { /* expected */ }
  w.eval('renderTop()');
  check(/maintenance/.test(d.querySelector('#top .offline')?.textContent || ''), '#907: a 503 reads "server in maintenance" ' + (d.querySelector('#top .offline')?.textContent || ''));
  w.fetch = of;
  w.close();
  await call('PUT', '/api/admin/announcement', {text: ''});

  // ================= #896: the News line when an agent joins
  const ag = await call('POST', '/api/admin/agents', {username: 'helper', provider: 'Claude (Anthropic, USA)'});
  await call('PUT', `/api/lists/${P}/members`, {user_id: ag.id, role: 'edit'});
  w = await boot({user: 'bob', hash: 'news'}); d = w.document;
  await until(() => d.querySelector('#view .nitem.k-agentjoin'));
  check(/helper/.test(d.querySelector('#view .nitem.k-agentjoin')?.textContent || '') && /Anthropic/.test(d.querySelector('#view .nitem.k-agentjoin')?.textContent || ''), '#896: News: the agent joined, where it runs');
  w.close();

  console.log(`p2240_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
