// kalmido-suite: fresh
// 2.455.0 (#3848) "Move to project" shows the task's own workspace; another workspace has its own entry and a question.
// Own container (start.sh), jsdom (computer + phone sheet) and Firefox (the headings' weight). Invented data only.
// - task menu + picker: only the task's workspace (and the Basket), "Move to another workspace…" beside it: workspace, then
//   project there; both ways, also organisation -> Private and between organisations; a workspace without projects is greyed
// - the question names task (or number), target workspace and project; Cancel leaves the task, Move moves it, Undo brings it back
// - inside a workspace no question; to the Basket none
// - Basket: the workspace shown now; under "All workspaces" every project under its workspace, the heading above a folder's
// - selection (bar, key m, multi panel): the same; mixed = like All; sort the basket, palette ("Move to project" of a drag)
// frida (no organisation) sees no entry and no question
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2455_b_ui', check, shots: 'P2455B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2455B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const TOUCH = {'(hover: none)': true, '(hover:none)': true, '(pointer:coarse)': true, '(pointer: coarse)': true};
const ENTRY = /Move to another workspace…/;

// what the open menu offers: '#heading' or the entry's text
const rows = d => [...d.querySelectorAll('#pop .menu-list .mgh, #pop .menu-list [role="menuitem"]')].map(x => x.classList.contains('mgh') ? '#' + x.textContent : (x.querySelector('.ml')?.textContent || x.textContent).trim());
const shut = async w => { w.eval('closePop()'); await sleep(40); };
const item = (d, re) => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => re.test(b.textContent));
const choose = async (w, re) => { const b = await until(() => item(w.document, re)); check(b, 'in the menu: ' + re + ' / ' + rows(w.document).join('|')); if (b) click(w, b); await sleep(60); };
const listOf = async id => (await call('GET', `/api/tasks/${id}`)).list_id;
const moved = (id, l) => until(async () => await listOf(id) === l);
const quest = w => until(() => w.document.querySelector('.cdlg'));
const answer = async (w, yes) => { const q = await quest(w); click(w, q.querySelector(`[data-cd="${yes ? 'yes' : 'no'}"]`)); await until(() => !w.document.querySelector('.cdlg')); };
const noQuest = w => !w.document.querySelector('.cdlg');
const open = async (user, ws, hash, o = {}) => {
  await call('PATCH', '/api/settings', {workspace: ws}, o.ck);
  const w = await boot({user, hash, ...o}); w.__dialogs = 'manual'; await until(() => w.document.querySelector('#view'));  // the dialogs stay for the test
  return w;
};
const task = async (title, list_id, ck) => (await call('POST', '/api/tasks', {title, ...(list_id ? {list_id} : {})}, ck)).id;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const me = (await call('GET', '/api/state')).me;
  const A = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id})).id, Be = (await call('POST', '/api/admin/orgs', {name: 'Beta', admin_id: me.id})).id;
  const Ga = (await call('POST', '/api/admin/orgs', {name: 'Gamma', admin_id: me.id})).id;  // no projects
  const L = {};
  for (const [name, x] of [['Kitchen', {}], ['Garden', {folder: 'Outdoors'}], ['Film', {org_id: A, folder: 'Shoots'}], ['Cut', {org_id: A}], ['Budget', {org_id: Be}]]) L[name] = (await call('POST', '/api/lists', {name, ...x})).id;
  check(Object.values(L).every(Boolean), 'lists ' + JSON.stringify(L));
  const IB = (await call('GET', '/api/state')).lists.find(l => l.is_inbox).id;

  // ================= computer, Private: the task menu and the picker
  const T1 = await task('Plan the shoot', L.Kitchen), T2 = await task('Second one', L.Kitchen);
  let w = await open('alice', 'private', 'l/' + L.Kitchen), d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T1}"]`));
  check(w.eval('wsCur()') === 'private' && w.eval('wsOn()') === true, 'the private workspace is shown');
  const R = id => `document.querySelector('#view .trow[data-id="${id}"]')`;
  w.eval(`taskMenu(${R(T1)}, ${T1})`); await sleep(100);
  const tm = rows(d), im = tm.findIndex(x => /^Move to project/.test(x));
  check(im >= 0 && ENTRY.test(tm[im + 1]), 'the task menu: the entry stands beside "Move to project…": ' + tm.join('|'));
  await choose(w, /Move to project/);
  check(rows(d).join('|') === 'Move to another workspace…|Basket|#Outdoors|Garden', 'the picker: only Private, the entry on top: ' + rows(d).join('|'));
  // inside the workspace: no question
  await choose(w, /Garden/);
  check(await moved(T1, L.Garden) && noQuest(w), 'inside a workspace: moved without a question');
  await until(() => d.querySelector('#toast:not(.hidden)'));

  // ================= the other workspace: workspace, project, question, Cancel, Move, Undo
  w.eval(`moveWsItem(document.querySelector('#top h1'), ${T2}).fn()`); await sleep(100);
  check(rows(d).join('|') === 'Alpha|Beta|Gamma', 'first the workspace: ' + rows(d).join('|'));
  check(item(d, /Gamma/).disabled, 'a workspace without projects cannot be chosen');
  await choose(w, /Alpha/);
  check(rows(d).join('|') === 'Cut|#Shoots|Film', 'then the projects there, no Basket: ' + rows(d).join('|'));
  await choose(w, /Film/);
  let q = await quest(w), qt = q.textContent;
  check(/Move to another workspace/.test(qt) && /“Second one”/.test(qt) && /Alpha/.test(qt) && /Film/.test(qt), 'the question names task, workspace and project: ' + qt);
  check(q.querySelector('[data-cd="yes"]').textContent === 'Move' && q.querySelector('[data-cd="no"]').textContent === 'Cancel', 'Move / Cancel');
  await answer(w, false); await sleep(100);
  check(await listOf(T2) === L.Kitchen, 'Cancel: the task stays');
  w.eval(`moveWsItem(document.querySelector('#top h1'), ${T2}).fn()`); await sleep(100);
  await choose(w, /Alpha/); await choose(w, /Film/); await answer(w, true);
  check(await moved(T2, L.Film), 'Move: the task is in the other workspace');
  const un = await until(() => d.querySelector('#toast:not(.hidden) button'));
  check(un, 'the toast offers Undo'); if (un) click(w, un);
  check(await moved(T2, L.Kitchen), 'Undo brings it back');

  // ================= from an organisation to Private and to another organisation
  const T3 = await task('Org task', L.Film);
  w = await open('alice', 'org:' + A, 'l/' + L.Film); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T3}"]`));
  w.eval(`moveListItem(document.querySelector('#top h1'), ${T3}).fn()`); await sleep(100);
  check(rows(d).join('|') === 'Move to another workspace…|Basket|Cut', 'the organisation: only its projects: ' + rows(d).join('|'));
  await choose(w, ENTRY);
  check(rows(d).join('|') === 'Private|Beta|Gamma', 'from an organisation: Private and the other ones: ' + rows(d).join('|'));
  await choose(w, /Beta/); await choose(w, /Budget/); await answer(w, true);
  check(await moved(T3, L.Budget), 'between organisations');
  w.eval(`moveWsItem(document.querySelector('#top h1'), ${T3}).fn()`); await sleep(100);
  await choose(w, /^\s*Private/); await choose(w, /Kitchen/); await answer(w, true);
  check(await moved(T3, L.Kitchen), 'organisation -> Private');
  // to the Basket: it is in every workspace
  const T4 = await task('To the basket', L.Film);
  await until(() => w.eval(`!!taskById(${T4})`) || (w.eval('load()'), false));
  w.eval(`moveListItem(document.querySelector('#top h1'), ${T4}).fn()`); await sleep(100);
  await choose(w, /Basket/);
  check(await moved(T4, IB) && noQuest(w), 'to the Basket without a question');

  // ================= the Basket: the workspace shown now
  const T5 = await task('In the basket', IB);
  await until(() => w.eval(`!!taskById(${T5})`) || (w.eval('load()'), false));
  w.eval(`moveListItem(document.querySelector('#top h1'), ${T5}).fn()`); await sleep(100);
  check(rows(d).join('|') === 'Move to another workspace…|Cut|#Shoots|Film', 'Basket under Alpha: the projects of Alpha: ' + rows(d).join('|'));
  await choose(w, /Cut/);
  check(await moved(T5, L.Cut) && noQuest(w), 'Basket -> the shown workspace: no question');
  await call('PATCH', `/api/tasks/${T5}`, {list_id: IB});

  // ================= "All workspaces": grouped, the question stays
  w = await open('alice', 'all', 'l/' + IB); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${T5}"]`));
  w.eval(`moveListItem(document.querySelector('#top h1'), ${T5}).fn()`); await sleep(100);
  check(rows(d).join('|') === '#Private|Kitchen|#Outdoors|Garden|#Alpha|Cut|#Shoots|Film|#Beta|Budget', 'All, Basket: every project under its workspace, no entry: ' + rows(d).join('|'));
  check([...d.querySelectorAll('#pop .mgrp.tch-ws > .mgh')].map(x => x.textContent).join('|') === 'Private|Alpha|Beta', 'the workspace headings have their own class');
  await choose(w, /Budget/); await answer(w, false);
  check(await listOf(T5) === IB, 'All: Basket -> an organisation asks');
  w.eval(`moveListItem(document.querySelector('#top h1'), ${T5}).fn()`); await sleep(100);
  await choose(w, /Kitchen/);
  check(await moved(T5, L.Kitchen) && noQuest(w), 'All: Basket -> Private needs no question');
  // a task of a project under All: its own workspace
  w.eval(`moveListItem(document.querySelector('#top h1'), ${T5}).fn()`); await sleep(100);
  check(rows(d).join('|') === 'Move to another workspace…|Basket|#Outdoors|Garden', 'All, a project\'s task: its workspace: ' + rows(d).join('|'));
  await shut(w);
  // under All the sidebar has every workspace's projects: a drop there asks too
  const drop = await until(() => d.querySelector(`#side [data-drop="l:${L.Budget}"]`));
  check(drop, 'All: the project of Beta in the sidebar');
  if (drop) {
    w.eval(`dropTask(${T5}, document.querySelector('#side [data-drop="l:${L.Budget}"]'), 0)`);
    await answer(w, false); await sleep(100);
    check(await listOf(T5) === L.Kitchen, 'a drop on another workspace\'s project asks; Cancel leaves the task');
  }

  // ================= the selection: bar, key m, multi panel; mixed = like All
  const S1 = await task('Pick one', L.Kitchen), S2 = await task('Pick two', L.Kitchen), S3 = await task('Pick three', L.Cut);
  await until(() => w.eval(`!!taskById(${S3})`) || (w.eval('load()'), false));
  const sel = (...ids) => w.eval(`S.multi.clear(); ${JSON.stringify(ids)}.forEach(i => S.multi.add(i)); S.multiMode = true`);
  sel(S1, S2);
  w.eval(`multiMoveMenu(document.querySelector('#top h1'))`); await sleep(100);
  check(ENTRY.test(rows(d)[0]) && !rows(d).includes('Film'), 'the bar\'s Move: one workspace, the entry: ' + rows(d).join('|'));
  await choose(w, ENTRY); await choose(w, /Alpha/); await choose(w, /Film/);
  q = await quest(w);
  check(/2 tasks/.test(q.textContent) && /Alpha/.test(q.textContent) && /Film/.test(q.textContent), 'a selection: the question gives the number: ' + q.textContent);
  await answer(w, true);
  check(await moved(S1, L.Film) && await moved(S2, L.Film), 'the selection moved');
  await call('PATCH', `/api/tasks/${S1}`, {list_id: L.Kitchen}); await call('PATCH', `/api/tasks/${S2}`, {list_id: L.Kitchen});
  await until(async () => (await w.eval('load()'), w.eval(`taskById(${S1}).list_id === ${L.Kitchen}`)));
  sel(S1, S3);
  w.eval(`mv_batch(document.querySelector('#top h1'))`); await sleep(100);
  check(rows(d).join('|').startsWith('Basket|#Private|Kitchen') && !rows(d).some(x => ENTRY.test(x)), 'a selection from two workspaces: like All: ' + rows(d).join('|'));
  await choose(w, /Budget/); await answer(w, false);
  check(await listOf(S1) === L.Kitchen && await listOf(S3) === L.Cut, 'mixed: Cancel leaves both');
  sel(S1, S2); w.eval('render()'); await sleep(100);
  w.eval(`meFields(meTasks()).find(x => x.k === 'list').open(document.querySelector('#top h1'))`); await sleep(100);
  check(ENTRY.test(rows(d)[0]) && !rows(d).includes('Cut'), 'the multi panel\'s Project: the same picker: ' + rows(d).join('|'));
  await shut(w); w.eval('S.multi.clear(); S.multiMode = false; render()');

  // ================= sort the basket, the Basket's row button, the palette
  const K1 = await task('Sort me', IB);
  w = await open('alice', 'private', 'l/' + L.Kitchen); d = w.document;
  await until(() => w.eval(`!!taskById(${K1})`));
  w.eval('kbSortStart()');
  await until(() => d.querySelector('[data-kbs="list"]'));
  const kid = w.eval('kbCur().id');
  w.eval(`kbSortDo('list')`); await sleep(100);
  check(ENTRY.test(rows(d)[0]) && rows(d).includes('Kitchen') && !rows(d).includes('Budget'), 'sort the basket: the shown workspace: ' + rows(d).join('|'));
  await choose(w, ENTRY); await choose(w, /Beta/); await choose(w, /Budget/);
  await answer(w, false);
  check(await listOf(kid) === IB && d.querySelector('[data-kbs="list"]') && w.eval('kbCur().id') === kid, 'sort the basket: Cancel stays on the same task');
  w.eval(`kbSortDo('list')`); await sleep(100);
  await choose(w, ENTRY); await choose(w, /Beta/); await choose(w, /Budget/); await answer(w, true);
  check(await moved(kid, L.Budget), 'sort the basket: moved after the question');
  w.eval(`KB.md?.remove()`); await sleep(50);
  const P1 = await task('By palette', L.Kitchen);
  await until(() => w.eval(`!!taskById(${P1})`) || (w.eval('load()'), false));
  await until(() => (w.eval('render()'), d.querySelector(`#view .trow[data-id="${P1}"]`)));
  w.eval(`S.sel = null; S.kf = ${P1}; openPalette('move')`); await sleep(100);
  const pal = w.eval(`palItems().map(x => x.label).join('|')`);
  check(pal.includes('Garden') && !pal.includes('Film') && !pal.includes('Budget') && pal.endsWith('Move to another workspace…'), 'the palette: the same split: ' + pal);
  w.eval(`palItems().find(x => x.id === 'mv:' + ${L.Garden}).fn()`);
  check(await moved(P1, L.Garden) && noQuest(w), 'the palette: inside the workspace no question');
  w.eval(`closePalette()`);

  // ================= phone: the sheet
  const M1 = await task('On the phone', L.Kitchen);
  w = await open('alice', 'private', 'l/' + L.Kitchen, {mobile: true, media: TOUCH}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${M1}"]`));
  w.eval(`moveListItem(document.querySelector('#view .trow[data-id="${M1}"]'), ${M1}).fn()`); await sleep(100);
  check(d.querySelector('#pop').classList.contains('sheet') && d.querySelector('#pop .tch-sht')?.textContent === 'Move to project', 'phone: the sheet');
  check(ENTRY.test(rows(d)[0]) && !rows(d).includes('Budget'), 'phone: own workspace + entry: ' + rows(d).join('|'));
  await choose(w, ENTRY);
  check(d.querySelector('#pop .tch-sht')?.textContent === 'Move to another workspace', 'phone: the second sheet\'s title');
  await choose(w, /Beta/);
  check(d.querySelector('#pop .tch-sht')?.textContent === 'Beta', 'phone: the third sheet names the workspace');
  await choose(w, /Budget/); await answer(w, true);
  check(await moved(M1, L.Budget), 'phone: moved');

  // ================= no organisation: nothing new
  const frida = (await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', lang: 'en'})).id;
  check(frida, 'frida');
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal'}, CF);
  const FL = (await call('POST', '/api/lists', {name: 'Own'}, CF)).id, FL2 = (await call('POST', '/api/lists', {name: 'Other'}, CF)).id, FT = await task('Frida task', FL, CF);
  w = await boot({user: 'frida', hash: 'l/' + FL}); w.__dialogs = 'manual'; d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${FT}"]`));
  w.eval(`taskMenu(document.querySelector('#view .trow[data-id="${FT}"]'), ${FT})`); await sleep(100);
  check(!rows(d).some(x => ENTRY.test(x)), 'frida: no entry in the task menu: ' + rows(d).join('|'));
  await choose(w, /Move to project/);
  check(!rows(d).some(x => ENTRY.test(x)) && !rows(d).some(x => x.startsWith('#')) && rows(d).includes('Other'), 'frida: her projects, nothing else: ' + rows(d).join('|'));
  await choose(w, /Other/);
  check(await until(async () => (await call('GET', `/api/tasks/${FT}`, null, CF)).list_id === FL2), 'frida: moved');
  check(noQuest(w), 'frida: no question');

  // ================= Firefox: the workspace's heading is clearly above a folder's
  await call('PATCH', `/api/tasks/${T5}`, {list_id: IB});
  await call('PATCH', '/api/settings', {workspace: 'all'});
  for (const [width, height, touch] of [[1280, 900, false], [390, 844, true]]) await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    await nav(B + '#l/' + IB);
    let g = null;
    for (let i = 0; i < 60 && !g; i++) {
      g = await ev(`(() => { if (typeof taskById !== 'function' || !taskById(${T5})) return null; moveListItem(document.querySelector('#top h1') || document.body, ${T5}).fn(); const a = document.querySelector('#pop .tch-ws .mgh'), b = document.querySelector('#pop .tch-fd .mgh'); if (!a || !b) return null; const x = getComputedStyle(a), y = getComputedStyle(b); return {ws: parseFloat(x.fontSize), wsW: +x.fontWeight, fd: parseFloat(y.fontSize), fdW: +y.fontWeight, wsC: x.color, fdC: y.color, side: document.documentElement.scrollWidth - innerWidth}; })()`).catch(() => null);
      if (!g) await sleep(250);
    }
    check(g && g.ws > g.fd && g.wsW >= 600 && g.wsW > g.fdW && g.wsC !== g.fdC && g.side <= 0, `${width}: the workspace above the folder ` + JSON.stringify(g));
    await shot(`p2455b-${width}-all.png`);
  }, touch);

  console.log(`p2455_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
