// 2.1156.0 part A UI test (#4280, start budget): the dialogs moved out of the start files load on their first use.
// kalmido-suite: fresh
// jsdom with the app's own on-demand loading (boot lazy: true = a fresh device): the start has no script tag of the moved
// files; each dialog opened through its stand-in (lazyload.js LD_CALL) or a real click loads its module and shows its CONTENT
// (the project's name in the project dialog, the people part of the Share dialog, the client's name field, ...); closed and
// opened again it comes at once. The tags overview (LD_VIEW) draws its cards after "Loading…".
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21156A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, ms = 15000) => require('./boot').until(fn, {timeout: ms, step: 100});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const tagged = (d, f) => [...d.querySelectorAll('script[src*="/static/js/"]')].some(s => new RegExp(`/static/js/${f}\\.js`).test(s.getAttribute('src')));
const MOVED = ['listmodal', 'sharemodal', 'foldershare', 'folderprops', 'clientdlg', 'evcals', 'fieldmodal', 'orgadmin', 'sched',
  'timeentry', 'habitdlg', 'propcards', 'importprop', 'contractprop', 'meetprop', 'signoff', 'tagsview', 'move', 'acctadm',
  'orgexport', 'photometa', 'cryptscope'];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,events,cal,clients,time,habits,fields'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const P = (await call('POST', '/api/lists', {name: 'Lazy Harbour', org_id: ORG, folder: 'Docks'})).id;
  const T = (await call('POST', '/api/tasks', {list_id: P, title: 'Paint the crane', tags: ['rusty']})).id;
  check(P > 0 && T > 0, 'setup: a project in a folder with a tagged task');

  const e0 = errs.length;
  const w = await boot({user: 'alice', hash: `l/${P}`, lazy: true}), d = w.document;
  const html = await (await fetch(B)).text();
  check(MOVED.every(f => !html.includes(`/static/js/${f}.js`)), 'index.html has no script tag of the moved files');
  check(MOVED.every(f => !tagged(d, f)), 'a cold start loads none of the moved files');
  check(typeof w.listModal === 'function' && typeof w.shareModal === 'function', 'the stand-ins of the moved dialogs are there at start');

  const modalWith = (sel, txt) => [...d.querySelectorAll('.modal')].find(m => m.querySelector(sel) && (!txt || m.textContent.includes(txt)));
  const closeAll = () => d.querySelectorAll('.modal').forEach(m => m.remove());

  // the project dialog: through the real button of the project's menu would need a menu; the stand-in is what every caller uses
  w.eval(`listModal(${P})`);
  await until(() => modalWith('#l-name'));
  const lm = modalWith('#l-name');
  check(lm && lm.querySelector('#l-name').value.includes('Lazy Harbour'), 'Edit project: the dialog shows the project\'s name');
  check(tagged(d, 'listmodal'), 'Edit project loaded listmodal.js');
  closeAll();
  w.eval(`listModal(${P})`);
  check(!!modalWith('#l-name'), 'the second opening comes at once (the real function replaced the stand-in)');
  closeAll();

  // the Share dialog through the real button of the project's header
  const shb = await until(() => d.querySelector(`[data-act="share-list"]`));
  click(w, shb);
  await until(() => modalWith('#l-members'));
  check(!!modalWith('#l-members', 'People'), 'Share: the button of the project loads sharemodal.js and shows the people part');
  closeAll();

  // a folder's Share dialog and settings
  w.eval(`folderShareModal('Docks')`);
  await until(() => [...d.querySelectorAll('.modal')].some(m => m.textContent.includes('Docks')));
  check([...d.querySelectorAll('.modal')].some(m => m.textContent.includes('Docks')), 'the Share dialog of a folder opens with the folder\'s name');
  closeAll();
  w.eval(`folderPropsModal('Docks')`);
  await until(() => tagged(d, 'folderprops') && d.querySelector('.modal'));
  check(!!d.querySelector('.modal') && tagged(d, 'folderprops'), 'Folder settings… loads folderprops.js and opens');
  closeAll();

  // New client, Add time, New habit, New field, Calendars…
  w.eval('clientModal(null)');
  await until(() => modalWith('#cl-name'));
  check(!!modalWith('#cl-name', 'New client'), 'New client: the dialog with its name field');
  closeAll();
  w.eval(`entryModal(null, {task_id: ${T}})`);
  await until(() => modalWith('#te-target'));
  check(!!modalWith('#te-target', 'Add time'), 'Add time: the dialog with the task choice');
  closeAll();
  w.eval('habitModal()');
  await until(() => [...d.querySelectorAll('.modal h3')].some(h => h.textContent.includes('New habit')));
  check([...d.querySelectorAll('.modal h3')].some(h => h.textContent.includes('New habit')), 'New habit: the dialog opens');
  closeAll();
  w.eval(`fieldModal(${P}, null, () => {})`);
  await until(() => [...d.querySelectorAll('.modal h3')].some(h => h.textContent.includes('New field')));
  check([...d.querySelectorAll('.modal h3')].some(h => h.textContent.includes('New field')), 'New field: the dialog opens');
  closeAll();
  w.eval('evCalsModal()');
  await until(() => [...d.querySelectorAll('.modal h3')].some(h => h.textContent.includes('Calendars')));
  check([...d.querySelectorAll('.modal h3')].some(h => h.textContent.includes('Calendars')), 'Calendars…: the dialog opens');
  closeAll();

  // the tags overview: "Loading…", then the tag's card
  w.location.hash = '#tags';
  await until(() => d.querySelector('.tgcard'));
  const card = d.querySelector('.tgcard');
  check(card && card.textContent.includes('#rusty') && tagged(d, 'tagsview'), 'the tags overview loads tagsview.js and shows the tag #rusty');
  click(w, card);
  await until(() => /#tag\/rusty/.test(w.location.hash));
  check(/#tag\/rusty/.test(w.location.hash), 'a tag card leads on to the tag\'s view');

  check(errs.length === e0, 'no script error: ' + errs.slice(e0).join(' | ').slice(0, 300));
  w.close();
  console.log(`p21156_a_lazydlg_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
