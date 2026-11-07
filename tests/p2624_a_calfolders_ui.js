// 2.624.0 UI test, part A (#3946): folders in "Per project" of the Calendars window. jsdom, own container (start.sh):
// kalmido-suite: fresh
// - "Per project" groups the lists by folder like the sidebar (own lists first, a folder's lists below it, subfolders
//   indented), every folder has its own switch
// - a folder off: stored in cal_folders_hidden; the switches of its lists and subfolders greyed with "Off through the folder";
//   the "N projects hidden" hint counts them; the month leaves their tasks out, also those of a list added to the folder later
// - the list's own calendar view still shows its tasks (the rule is for the calendar views only)
// - from 8 lists a search on top: filters by list and folder names, the hits show their folder path, no hit: a hint
// Every wait is on a real state (rows drawn, setting stored, chips there).
process.env.TZ = 'Europe/Berlin';
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = fn => until0(fn, {timeout: 20000, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const settings = async () => (await call('GET', '/api/state')).settings;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,timeline,events'});
  const t1 = day(1);
  const mk = async (name, folder) => (await call('POST', '/api/lists', {name, ...(folder ? {folder} : {})})).id;
  const HOME = await mk('Home');
  const WEB = await mk('Website', 'Clients/Acme'), SHOP = await mk('Shop', 'Clients/Acme/Webshop'), BETA = await mk('Beta campaign', 'Clients');
  await mk('Taxes'); await mk('Garden', 'Private'); await mk('Books', 'Private'); await mk('Kitchen');
  await call('POST', '/api/tasks', {title: 'Water the plants', list_id: HOME, due: t1});
  await call('POST', '/api/tasks', {title: 'Launch the website', list_id: WEB, due: t1});
  await call('POST', '/api/tasks', {title: 'Fill the shop', list_id: SHOP, due: t1});
  check(HOME && WEB && SHOP && BETA, 'lists in folders and subfolders');

  let w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}), d = w.document;
  w.eval(`S.calMode = 'month'; S.calSel = '${t1}'; S.calMonth = '${t1.slice(0, 7)}'; renderView()`);
  const chips = () => [...d.querySelectorAll('#view .cal .ev, #view .agenda')].map(x => x.textContent).join(' | ');
  check(await until(() => /Launch the website/.test(chips()) && /Fill the shop/.test(chips())), 'month: the folder lists\' tasks show ' + chips());

  // ================= the Calendars window, "Per project"
  const open = async () => {
    click(w, d.querySelector('#view .calbar [data-act="ev-cals"]'));
    await until(() => d.querySelector('.modal.evcmodal [data-evc="lists"]'));
    const md = d.querySelector('.modal.evcmodal');
    click(w, md.querySelector('[data-evc="lists"]'));
    await until(() => md.querySelector('.cvflists .cvxrow.sub'));
    return md;
  };
  let md = await open();
  const frows = () => [...md.querySelectorAll('.cvfrow')];
  const fsw = f => md.querySelector(`.cvfrow[data-folder="${f}"] input[data-cvx="folder"]`);
  const lrow = name => [...md.querySelectorAll('.cvflists .cvxrow.sub')].find(r => r.querySelector('.evcn')?.firstChild?.textContent === name);
  const order = [...md.querySelectorAll('.cvflists .cvxrow.sub[data-cvfq], .cvfrow')].map(r => r.classList.contains('cvfrow') ? 'F:' + r.dataset.folder : r.querySelector('.evcn').firstChild.textContent);
  check(order.indexOf('Home') < order.indexOf('F:Clients') && order.indexOf('F:Clients') < order.indexOf('Beta campaign') && order.indexOf('Beta campaign') < order.indexOf('F:Clients/Acme')
    && order.indexOf('F:Clients/Acme') < order.indexOf('Website') && order.indexOf('Website') < order.indexOf('F:Clients/Acme/Webshop') && order.indexOf('F:Clients/Acme/Webshop') < order.indexOf('Shop')
    && order.at(-1) === w.eval(`lname(S.lists.find(l => l.is_inbox))`), 'grouped like the sidebar: own lists, folder, its lists, its subfolders, the inbox last ' + JSON.stringify(order));
  check(frows().length === 4 && frows().every(r => r.querySelector('input[data-cvx="folder"]')?.checked && r.querySelector('.sr')?.textContent), 'a switch per folder (on, with an accessible name)');
  const pad = r => parseFloat(r.style.paddingLeft || '0');
  check(pad(frows().find(r => r.dataset.folder === 'Clients/Acme')) > pad(frows().find(r => r.dataset.folder === 'Clients')) && pad(lrow('Shop')) > pad(lrow('Website')), 'subfolders and their lists indented');

  // ================= a folder off
  const s = fsw('Clients/Acme'); s.checked = false; change(w, s);
  check(await until(async () => JSON.stringify(JSON.parse((await settings()).cal_folders_hidden)) === '["Clients/Acme"]'), 'folder switch: stored (cal_folders_hidden)');
  await until(() => lrow('Website')?.querySelector('input').disabled);
  for (const n of ['Website', 'Shop']) check(lrow(n).querySelector('input').disabled && !lrow(n).querySelector('input').checked && /Off through the folder/.test(lrow(n).textContent), `${n}: greyed, "Off through the folder"`);
  check(fsw('Clients/Acme/Webshop').disabled && /Off through the folder/.test(md.querySelector('.cvfrow[data-folder="Clients/Acme/Webshop"]').textContent), 'the subfolder: greyed too');
  check(!lrow('Beta campaign').querySelector('input').disabled && !fsw('Clients').disabled, 'the parent folder and its own list stay as they are');
  check(/2 projects hidden/.test(md.querySelector('.cvxrow:not(.sub) .evcn').textContent), 'the hint counts the lists hidden through the folder: ' + md.querySelector('.cvxrow:not(.sub) .evcn').textContent);
  click(w, md.querySelector('[data-evc="close"]'));
  w.eval(`S.calMode = 'month'; S.calSel = '${t1}'; S.calMonth = '${t1.slice(0, 7)}'; renderView()`);
  check(await until(() => /Water the plants/.test(chips()) && !/Launch the website|Fill the shop/.test(chips())), 'month: the folder\'s tasks (and its subfolder\'s) gone, the others stay ' + chips());

  // a list added to the folder later: off as well
  const LATER = await mk('Newsletter', 'Clients/Acme');
  await call('POST', '/api/tasks', {title: 'Send the newsletter', list_id: LATER, due: t1});
  check(await until(() => w.eval(`!!listById(${LATER}) && [...S.tasks.values()].some(t => t.list_id === ${LATER})`)), 'the new list and its task arrive');
  w.eval(`renderView()`);
  check(await until(() => /Water the plants/.test(chips()) && !/Send the newsletter/.test(chips())) && !w.eval(`cvxTaskOn([...S.tasks.values()].find(t => t.list_id === ${LATER}))`), 'a list added to the hidden folder later: off too');
  // the list's own calendar view shows its tasks
  const lc = w.eval(`(() => { const l = listById(${WEB}); S.calMode = 'month'; S.calSel = '${t1}'; S.calMonth = '${t1.slice(0, 7)}'; return lcal_view(l); })()`);
  check(/Launch the website/.test(lc), 'the list\'s own calendar view still shows its task');

  // ================= the search (9 lists + inbox here)
  md = await open();
  const q = md.querySelector('[data-cvfq-in]');
  check(q && q.getAttribute('aria-label'), 'from 8 lists: the search on top');
  const shown = () => [...md.querySelectorAll('.cvflists [data-cvfq]')].filter(r => !r.hidden).map(r => r.classList.contains('cvfrow') ? 'F:' + r.dataset.folder : r.querySelector('.evcn').firstChild.textContent);
  q.value = 'shop'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => JSON.stringify(shown()) === JSON.stringify(['F:Clients/Acme/Webshop', 'Shop'])), 'search "shop": the subfolder and its list ' + JSON.stringify(shown()));
  const sp = lrow('Shop').querySelector('.cvfpath');
  check(sp && !sp.hidden && /Clients \/ Acme \/ Webshop/.test(sp.textContent), 'the hit shows its folder path: ' + sp?.textContent);
  q.value = 'acme'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => shown().includes('Website') && shown().includes('Newsletter') && shown().includes('F:Clients/Acme') && !shown().includes('Home') && !shown().includes('Beta campaign')), 'search by a folder name: the folder\'s lists ' + JSON.stringify(shown()));
  q.value = 'zzz nothing'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => !shown().length && !md.querySelector('.cvfnone').hidden), 'no hit: the hint');
  // switching while searching keeps the filter
  q.value = 'acme'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => shown().includes('Website'));
  const s2 = fsw('Clients/Acme'); s2.checked = true; change(w, s2);
  check(await until(async () => (await settings()).cal_folders_hidden === '[]'), 'the folder on again: stored');
  check(await until(() => md.querySelector('[data-cvfq-in]')?.value === 'acme' && !shown().includes('Home') && !lrow('Website').querySelector('input').disabled), 'after the redraw: search kept, the list switches free');
  click(w, md.querySelector('[data-evc="close"]'));

  await call('PATCH', '/api/settings', {cal_folders_hidden: []});
  w.close();
  console.log(`p2624_a_calfolders_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
