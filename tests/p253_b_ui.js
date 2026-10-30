// 2.53.0 part B UI test, own container (start.sh). jsdom:
// #1426 list colours: a fixed palette of 12 tones (an older free colour stays stored, the nearest tone is shown, the list
//       dialog never writes it back), the open list's colour as the accent of the list view (left again on leaving), a
//       folder's colour for new lists in it (server + dialog), the card edge on boards and in the collected views (not
//       in the list's own list view), the switch "List colours only as a dot".
// #1474 workspace colours: an organisation's list carries its colour (header stripe, sign, sidebar stripe, frame of
//       the input fields); a private list stays neutral; moving a task / list from Private into the organisation says
//       who sees it now (with Undo); only an admin of the organisation sets its colour (403 for a member).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const FREE = '#123456';  // an older free colour (before the palette)
  const OLD = (await call('POST', '/api/lists', {name: 'Old colour', color: FREE, org_id: null})).id;
  const TEAL = (await call('POST', '/api/lists', {name: 'Teal list', color: '#2dd4bf', org_id: null})).id;
  const W = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const P = (await call('POST', '/api/lists', {name: 'Garden', org_id: null})).id;
  const today = TC.today();
  const T1 = (await call('POST', '/api/tasks', {title: 'Teal task', list_id: TEAL, due: today})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Private task', list_id: P})).id;

  // ---- #1426 the palette
  let w = await boot({user: 'alice', hash: 'l/' + TEAL}), d = w.document;
  check(w.eval('LP_TONES.length') === 12 && w.eval('LP_TONES.every(t => t.length === 6 && t.slice(2).every(c => /^#[0-9a-f]{6}$/.test(c)))'), '#1426: 12 tones, each with dark value + ink and light value + ink');
  check(w.eval(`lp_near('#2dd4bf')[2]`) === '#2dd4bf', '#1426: a palette value maps to itself');
  const shown = w.eval(`lp_col(listById(${OLD}))`);
  check(w.eval('LP_TONES.map(t => t[2])').includes(shown) && shown !== FREE, '#1426: an old free colour shows the nearest tone ' + shown);
  check(w.eval(`lp_near('#6ee7b7')`) && w.eval(`lp_near('#f5b041')[2]`) === '#f5b041', '#1426: the colours of the old picker map to a tone');

  // ---- accent of the open list, back on leaving
  const main = () => d.querySelector('#main');
  await until(() => main().classList.contains('lp-acc'));
  check(main().classList.contains('lp-acc') && main().style.getPropertyValue('--lpd') === '#2dd4bf' && main().style.getPropertyValue('--lpil') === '#ffffff', '#1426: the open list sets its accent on the list view (--lpd / --lpil)');
  check(d.querySelector('#fab').classList.contains('lp-acc'), '#1426: the + button takes the accent too');
  check(!d.documentElement.style.getPropertyValue('--lpd') && !d.body.classList.contains('lp-acc'), '#1426: never global (only #main / #fab)');
  check(main().classList.contains('lp-one'), '#1426: one list open: lp-one (its rows need no edge, the accent says it)');
  w.location.hash = '#l/' + P; await until(() => !main().classList.contains('lp-acc'));
  check(!main().classList.contains('lp-acc') && !main().style.getPropertyValue('--lpd'), '#1426: a list without colour: the normal accent again');

  // ---- card edges: Today (collected view) and a board
  w.location.hash = '#today'; await until(() => d.querySelector(`#view .trow[data-id="${T1}"]`));
  let row = d.querySelector(`#view .trow[data-id="${T1}"]`);
  check(row && row.classList.contains('lpc') && /--lpd:#2dd4bf/.test(row.getAttribute('style') || ''), '#1426: Today: the task carries its list colour as the card edge');
  check(!main().classList.contains('lp-one'), '#1426: a collected view shows the edges');
  // the old free colour is never written back by the list dialog (another field saved)
  w.eval(`listModal(${OLD})`); await until(() => d.querySelector('.modal.lmodal #l-col'));
  let md = d.querySelector('.modal.lmodal');
  check(md.querySelectorAll('#l-col button').length === 13 && md.querySelector('#l-col button.on')?.dataset.c === shown, '#1426: the dialog: none + 12 tones, the shown tone pressed');
  const nm = md.querySelector('#l-name'); nm.value = 'Old colour 2'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === OLD).name === 'Old colour 2');
  check((await call('GET', '/api/state')).lists.find(l => l.id === OLD).color === FREE, '#1426: saving the name keeps the stored free colour (no one-way step)');
  // a new tone from the palette is stored
  click(w, md.querySelector('#l-col button[data-c="#f87171"]'));
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === OLD).color === '#f87171'), '#1426: a tone picked in the dialog is stored');
  md.querySelector('[data-m="close"]')?.click(); await sleep(200);
  d.querySelectorAll('.modal').forEach(x => x.remove());

  // ---- folder colour -> new lists in it
  w.eval(`lp_folderSet('Work', '#a78bfa')`);
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).settings.folder_colors || '{}').Work === '#a78bfa'), '#1426: the folder colour is stored (folder_colors)');
  check(w.eval('HIST.undo[HIST.undo.length - 1]?.label') && /Colour of/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), '#1426: the folder colour is one undo step');
  const NL = await call('POST', '/api/lists', {name: 'In work', folder: 'Work'});
  check(NL.color === '#a78bfa', '#1426: a new list in the folder takes its colour (server) ' + NL.color);
  const NL2 = await call('POST', '/api/lists', {name: 'Explicitly none', folder: 'Work', color: ''});
  check(NL2.color === '', '#1426: an explicit "no colour" stays');
  check((await call('GET', '/api/state')).lists.find(l => l.id === TEAL).color === '#2dd4bf', '#1426: existing lists keep their colour');
  await w.eval('load()');  // the app's own poll may have read the settings before the change
  w.eval(`listModal(null, 'Work')`); await until(() => d.querySelector('.modal.lnew #l-col'));
  check(d.querySelector('.modal.lnew #l-col button.on')?.dataset.c === '#a78bfa', '#1426: the new-list dialog preselects the folder colour');
  d.querySelectorAll('.modal').forEach(x => x.remove());
  check(!(await call('PATCH', '/api/settings', {folder_colors: {Work: 'url(x)'}})).ok, '#1426: an invalid folder colour is refused');

  // ---- a board: the cards carry the edge (also in the list's own board): the card is the row in .kcards
  const card = d.createElement('div'); card.innerHTML = w.eval(`taskRow(taskById(${T1}), {compact: true})`);
  check(card.firstElementChild?.classList.contains('lpc'), '#1426: board cards carry the list colour edge (class)');
  const css = await require('./boot').allCss(); // 2.65.0 (#1824): + the module stylesheets
  check(/#view \.kcards \.trow\.lpc\{box-shadow:inset/.test(css), '#1426: the edge on board cards also inside the list itself');
  w.close();

  // ---- the switch "List colours only as a dot"
  await call('PATCH', '/api/settings', {list_color_dot: '1'});
  w = await boot({user: 'alice', hash: 'l/' + TEAL}); d = w.document;
  await until(() => d.querySelector('#top h1'));
  check(d.body.classList.contains('lp-dot') && !d.querySelector('#main').classList.contains('lp-acc'), '#1426: only as a dot: no accent');
  w.location.hash = '#today'; await until(() => d.querySelector(`#view .trow[data-id="${T1}"]`));
  check(!d.querySelector(`#view .trow[data-id="${T1}"]`).classList.contains('lpc'), '#1426: only as a dot: no card edge');
  check(!!d.querySelector(`#side .srow[data-list="${TEAL}"] .lic.lcol, #side .srow[data-list="${TEAL}"] .licd`), '#1426: only as a dot: the sidebar keeps the colour');
  w.eval(`settingsModal('look')`); await until(() => d.querySelector('#s-lpdot'));
  check(d.querySelector('#s-lpdot')?.checked === true, '#1426: the switch in Appearance shows the setting');
  d.querySelectorAll('.modal').forEach(x => x.remove());
  w.close();
  await call('PATCH', '/api/settings', {list_color_dot: '0'});

  // ---- #1474 workspace colours
  w = await boot({user: 'alice', hash: 'l/' + W}); d = w.document;
  const sign = () => d.querySelector('#top h1 .wsbadge');
  await until(() => sign());
  check(d.querySelector('#main').classList.contains('wsc-on') && /^#[0-9a-f]{6}$/.test(d.querySelector('#main').style.getPropertyValue('--wsd')), '#1474: an organisation list: wsc-on + --wsd on #main (the input frame; 2.138.2 #2389: no header stripe any more)');
  check(sign()?.dataset.wsc === '1' && /--wsd:/.test(sign().getAttribute('style') || ''), '#1474: the sign in the organisation colour');
  check(d.querySelector(`#side .srow[data-list="${W}"]`)?.dataset.wsc === '1', '#1474: the sidebar stripe at the organisation list');
  check(!d.querySelector(`#side .srow[data-list="${P}"]`)?.dataset.wsc, '#1474: no stripe at a private list');
  check(w.eval(`WSC_TONES.map(t => t[0]).includes(wsc_tone(${ORG})[0])`), '#1474: an organisation without own colour has a default tone');
  check(!w.eval(`WSC_TONES.some(t => LP_TONES.some(x => x[2] === t[0] || x[4] === t[1]))`), '#1474: a palette of its own (no list tone)');
  w.location.hash = '#l/' + P; await until(() => /Private/.test(sign()?.textContent || ''));
  check(!d.querySelector('#main').classList.contains('wsc-on') && !sign()?.dataset.wsc, '#1474: a private list stays neutral');
  // the comment field of a task of the organisation
  const T3 = (await call('POST', '/api/tasks', {title: 'Org task', list_id: W})).id;
  await w.eval('load()'); w.location.hash = '#l/' + W; await until(() => d.querySelector(`.trow[data-id="${T3}"]`));
  w.eval(`openDetail(${T3})`); await until(() => d.querySelector('#detail').classList.contains('wsc-on'));
  check(d.querySelector('#detail').classList.contains('wsc-on'), '#1474: the detail of an organisation task frames its comment field');

  // moving a task from Private into the organisation: the hint + Undo
  await w.eval(`patchUndoable(${T2}, {list_id: ${W}}, 'Moved')`);
  const toast = () => d.querySelector('#toast');
  check(/Will be visible to everyone in Example Org/.test(toast()?.textContent || ''), '#1474: moving a task into the organisation says who sees it ' + (toast()?.textContent || ''));
  check(!!toast()?.querySelector('button'), '#1474: with Undo');
  click(w, [...toast().querySelectorAll('button')].find(b => /Undo/.test(b.textContent)) || toast().querySelector('button'));
  check(await until(async () => (await call('GET', '/api/tasks/' + T2)).list_id === P), '#1474: Undo moves it back');
  // a task moved inside Private: no hint
  await w.eval(`patchUndoable(${T2}, {list_id: ${TEAL}}, 'Moved to Teal')`);
  check(!/Will be visible/.test(toast()?.textContent || ''), '#1474: moving inside Private: no hint');
  // a list moved into the organisation (list dialog)
  w.eval(`listModal(${P})`); await until(() => d.querySelector('.modal.lmodal #l-ws'));
  const ws = d.querySelector('.modal.lmodal #l-ws'); ws.value = String(ORG); ws.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(() => /Will be visible to everyone in Example Org/.test(toast()?.textContent || '')), '#1474: moving a list into the organisation says who sees it');
  check(await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === P).org_id === ORG), '#1474: the list moved');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await call('GET', '/api/state')).lists.find(l => l.id === P).org_id), '#1474: Undo makes it private again');
  d.querySelectorAll('.modal').forEach(x => x.remove());
  w.close();

  // ---- only an admin of the organisation sets its colour
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const og = await call('GET', '/api/orgs');
  const mem = og.orgs[0].members.map(m => m.id);
  check((await call('PATCH', '/api/admin/orgs/' + ORG, {members: [...mem, bob.id], admins: og.orgs[0].members.filter(m => m.role === 'admin').map(m => m.id)})).status === 200, 'bob joins the organisation');
  const CB = await login('bob');
  check((await call('PATCH', '/api/orgs/' + ORG, {color: '#ef8a6b'}, CB)).status === 403, '#1474: a member cannot set the colour (403)');
  check((await call('PATCH', '/api/orgs/' + ORG, {color: 'red;x'})).status === 400, '#1474: an invalid colour is refused');
  check((await call('PATCH', '/api/orgs/' + ORG, {color: '#ef8a6b'})).color === '#ef8a6b', '#1474: the organisation admin sets it');
  check((await call('GET', '/api/state', null, CB)).me.workspaces.find(x => x.id === ORG)?.color === '#ef8a6b', '#1474: every member reads it in /api/state');
  check((await call('PATCH', '/api/orgs/99999', {color: '#ef8a6b'}, CB)).status === 404, '#1474: another organisation: 404');
  // Settings > Workspaces: the admin's swatches, a member's disabled
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal(lmOrgPaneOn() ? 'org' : 'account')`); await until(() => d.querySelector('.wscpick'));
  check(d.querySelectorAll('.wscpick [data-wscp]').length === 8 && d.querySelector('.wscpick [data-wscp].on')?.dataset.wscp === '#ef8a6b', '#1474: the admin sees 8 swatches, the chosen one pressed');
  click(w, d.querySelector('.wscpick [data-wscp="#4cc3d9"]'));
  check(await until(async () => (await call('GET', '/api/orgs')).orgs[0].color === '#4cc3d9'), '#1474: a tap sets the colour');
  w.close();
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal(lmOrgPaneOn() ? 'org' : 'account')`); await until(() => d.querySelector('.wscpick'));
  check(!d.querySelector('.wscpick'), '#1474 (#3013): a member has no organisation colour picker');  // 2.354.0 C (#3013): was a locked picker
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
