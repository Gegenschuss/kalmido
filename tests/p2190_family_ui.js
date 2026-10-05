// 2.19.0 UI tests: the module "Family" (#653), own container (start.sh, isolated test database).
// jsdom: the module off leaves no trace; on: the Family view (birthdays with the age, whose turn, the meal plan of a week with
// "+" and the ingredients button, shopping lists, deadlines, kids with requests, packing templates), the dialogs (birthday,
// deadline with its notice period, meal, rewards, stars), the task panel's family section (birthday name / year, gift ideas,
// taking turns, who comes along, stars), "Used for" in the list dialog + the bar above a family list, shopping mode (areas,
// a tick, a new item, the area menu, live: someone else's item shows up by itself), the kid's view (big ticks, stars, asking
// for a reward) and the parent's approval, "What do you use Kalmido for?" in Settings > Modules and in the welcome tour, the
// dashboard card, the palette commands.
// Firefox: touch at 360 / 390 / 412 and the Fold 904 (portrait + landscape), a mouse at 1440 / 1920, light + dark: nothing
// sideways, 44 px targets on touch, real taps in shopping mode and the kid view, axe (WCAG 2.2 A + AA) over the Family view,
// a dialog, the task panel, shopping mode and the kid view. Screenshots with P2190F_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2190_family_ui', check, shots: 'P2190F_SHOTS'});
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };  // local date (TZ of the container)
const FAM = 'cal,habits,comments,collab,family';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'habits', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const LINA = (await call('POST', '/api/users', {username: 'lina', display_name: 'Lina', password: 'password123', kid: true, parents: [1]})).id;
  const CB = await login('bob'), CL = await login('lina');
  await call('PATCH', '/api/settings', {features: FAM, tour: 'done', lang: 'en'}, CB);
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, CL);

  // ================= jsdom: the module off leaves no trace
  let w = await boot({user: 'alice', hash: 'family'}), d = w.document;
  await sleep(300);
  check(w.eval('S.route.mod') === 'tasks' && !d.querySelector('#side [data-go="family"]') && !d.querySelector('#tabs [data-k="m:family"], #tabs [data-mod="family"]'), 'off: #family goes to the tasks, no sidebar row, no tab');
  check(!w.eval(`PURPOSES.length && feat('family')`), 'off: feat(family) false');
  w.eval(`settingsModal('modules')`); await sleep(400);
  check(d.querySelector('.smodal [data-feat="family"]') && !d.querySelector('.smodal [data-feat="family"]').checked && d.querySelectorAll('.smodal .purposes [data-purpose]').length === 5,
    'Settings > Modules: the Family switch (off) and the five purposes (2.22.0: Home)');
  // "What do you use Kalmido for?" -> Family (confirm), the starter lists come
  click(w, d.querySelector('.smodal [data-purpose="family"]'));
  check(await until(() => w.eval(`feat('family')`) && (w.eval('S.lists') || []).filter(l => l.family).length === 4, 60), 'purpose Family: the module on, four starter lists');
  await until(() => d.querySelector('.smodal [data-purpose="family"].on'), 40);
  check(d.querySelector('.smodal [data-purpose="family"]')?.getAttribute('aria-checked') === 'true', 'the chosen purpose is marked');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove()); w.close();
  let st = await call('GET', '/api/state');
  const L = Object.fromEntries(st.lists.filter(l => l.family).map(l => [l.family, l.id]));
  for (const k of ['shopping', 'household', 'meals']) { await call('PUT', `/api/lists/${L[k]}/members`, {user_id: BOB, role: 'edit'}); await call('PUT', `/api/lists/${L[k]}/members`, {user_id: LINA, role: 'edit'}); }
  const chores = st.tasks.filter(t => t.list_id === L.household);
  const BD = await call('POST', '/api/family/occasions', {name: 'Grandma Erika', date: '1946-' + day(5).slice(5), gifts: ['Book', 'Scarf']});
  await call('POST', '/api/family/deadlines', {type: 'passport', who: 'Lina', expires: day(40)});
  await call('PATCH', `/api/tasks/${chores[0].id}`, {rotation: {who: [1, BOB, LINA], mode: 'done'}});
  const KT = await call('POST', '/api/tasks', {title: 'Tidy up your room', list_id: L.household, assignee_id: LINA, stars: 2});
  const ICE = await call('POST', `/api/family/kids/${LINA}/rewards`, {title: 'Ice cream', cost: 2, emoji: '🍦'});
  await call('POST', `/api/family/kids/${LINA}/rewards`, {title: 'Zoo', cost: 50});

  // ================= jsdom: the Family view
  w = await boot({user: 'alice', hash: 'family'}); d = w.document;
  await until(() => d.querySelector('#view .fam'));
  check(d.querySelector('#side [data-go="family"]') && d.querySelector('#top h1')?.textContent.includes('Family'), 'on: sidebar row + the title');
  const cards = [...d.querySelectorAll('#view .fcard')].map(c => c.className.match(/fc-(\w+)/)[1]);
  check(['occ', 'rot', 'meals', 'shop', 'dl', 'kids', 'pack'].every(k => cards.includes(k)), 'the cards: ' + cards);
  check([...d.querySelectorAll('#view .fcard h2')].length === cards.length && !d.querySelector('#view .fam h3'), 'card titles are h2 (heading order after the h1)');
  const occRow = d.querySelector('#view .fc-occ .frow');
  check(/Grandma Erika/.test(occRow?.textContent) && new RegExp('turns ' + (new Date().getFullYear() + (day(5) < new Date().toISOString().slice(0, 10) ? 1 : 0) - 1946)).test(occRow.textContent) && /in 5 days/.test(occRow.textContent),
    'the birthday: name, "turns N", "in 5 days": ' + occRow?.textContent);
  check(/Alice → Bob → Lina/.test(d.querySelector('#view .fc-rot')?.textContent), 'whose turn: the whole order, Alice → Bob → Lina');
  const days = d.querySelectorAll('#view .fc-meals .fday');
  check(days.length === 7 && [...d.querySelectorAll('#view .fc-meals [data-act="fam-meal"]')].every(b => /^Add a meal on /.test(b.getAttribute('aria-label'))), 'the meal plan: 7 days, each with a named +');
  check(d.querySelector('#view .fc-meals .fday.today .fmeal') && d.querySelector('#view .fc-meals [data-act="fam-ingr"]'), 'today\'s meal with the ingredients button');
  check(d.querySelector('#view .fc-shop [data-act="fam-shop"]') && /3 items left/.test(d.querySelector('#view .fc-shop').textContent), 'shopping: the list, 3 items left, Shopping mode');
  check(/Renew the passport: Lina/.test(d.querySelector('#view .fc-dl').textContent), 'deadlines: the passport');
  check(/Lina/.test(d.querySelector('#view .fc-kids').textContent) && d.querySelector('#view .fc-kids [data-act="fam-give"]'), 'kids: Lina with Stars / Rewards');
  check(d.querySelectorAll('#view .fc-pack [data-act="fam-pack"]').length === 5, 'five packing templates');
  // week navigation keeps the focus
  const nx = d.querySelector('#view [data-act="fam-week"][data-d="7"]'); nx.focus(); click(w, nx); await sleep(150);
  check(w.eval('S.famWeek') > w.eval('mondayOf(today())') && d.activeElement?.dataset.act === 'fam-week' && !d.querySelector('#view .fc-meals .fday.today'), 'next week: shown, focus kept');
  click(w, d.querySelector('#view [data-act="fam-week"][data-d="-7"]')); await sleep(150);
  check(w.eval('famData().mon') === w.eval('today()') && d.querySelector('#view .fc-meals .fday.today') === d.querySelector('#view .fc-meals .fday'), 'the meal plan: the next seven days from today');
  // the birthday dialog
  click(w, d.querySelector('#view [data-act="fam-occ"]')); await sleep(150);
  let md = d.querySelector('.modal.famdlg');
  check(md && md.querySelector('#oc-name') && md.querySelector('#oc-month').options.length === 12 && md.querySelector('#oc-kind [aria-checked="true"]')?.dataset.k === 'birthday', 'birthday dialog: name, day / month / year, birthday preselected');
  click(w, md.querySelector('[data-m="save"]')); await sleep(100);
  check(/Please enter a name/.test(md.querySelector('#oc-err').textContent), 'no name: a message, nothing sent');
  check(+md.querySelector('#oc-month').value === new Date().getMonth() + 1 && md.querySelector('#oc-year').placeholder === 'Year', 'the month starts at this month; the year field says "Year"');
  md.querySelector('#oc-name').value = 'Nobody'; md.querySelector('#oc-day').value = '31'; md.querySelector('#oc-month').value = '2';
  md.querySelector('#oc-name').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); await sleep(100);
  check(/Please enter the day/.test(md.querySelector('#oc-err').textContent),
    'Enter in a field saves like Add; 31 February is caught in the dialog');
  md.querySelector('#oc-name').value = 'Uncle Tom'; md.querySelector('#oc-day').value = '3'; md.querySelector('#oc-month').value = '7'; md.querySelector('#oc-year').value = '1970';
  click(w, md.querySelector('#oc-kind [data-k="anniversary"]'));
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await call('GET', '/api/state')).tasks.some(t => t.fam?.name === 'Uncle Tom' && t.fam.kind === 'anniversary' && t.fam.year === 1970 && t.due.slice(5) === '07-03')),
    'saved: an anniversary on 3 July with the year');
  check(await until(() => !d.querySelector('.modal.famdlg') && /Added: Anniversary: Uncle Tom/.test(d.querySelector('#toast').textContent)),
    'dialog closed, toast with Open: ' + (d.querySelector('.modal.famdlg') ? 'dialog open ' + d.querySelector('#oc-err')?.textContent : d.querySelector('#toast').textContent));
  // the deadline dialog: insurance -> notice period 3 months
  click(w, d.querySelector('#view [data-act="fam-dl"]')); await sleep(150);
  md = d.querySelector('.modal.famdlg');
  check(md.querySelector('.dlnotice').hidden && /90 days before/.test(md.querySelector('#dl-hint').textContent), 'passport: no notice period, the lead in the hint');
  click(w, md.querySelector('[data-dl="insurance"]'));
  check(!md.querySelector('.dlnotice').hidden && md.querySelector('#dl-notice').value === '3' && /Ends on/.test(md.querySelector('#dl-explab').textContent), 'insurance: notice period 3 months, "Ends on"');
  md.querySelector('#dl-who').value = 'Home insurance';
  click(w, md.querySelector('.dpbtn')); await sleep(100);
  const yr = new Date().getFullYear();
  check(d.querySelector('#dpop .dpy') && [...d.querySelector('#dpop .dpy').options].some(o => +o.value === yr + 10), 'the date picker: a year select (ten years ahead in one choice)');
  { const y = d.querySelector('#dpop .dpy'); y.value = String(yr + 8); y.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(w.eval('DP.st.cur').startsWith(String(yr + 8)) && d.activeElement?.classList.contains('dpy'), 'a year chosen: the calendar jumps, focus stays on the select');
  w.eval('dpClose(true)');
  w.eval(`dpSet(document.getElementById('dl-exp'), '${day(300)}')`);
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await call('GET', '/api/state')).tasks.some(t => t.fam?.type === 'insurance' && t.fam.expires === day(300) && t.fam.notice === 3 && t.deadline === 2)), 'saved: the insurance deadline');
  // a meal for tomorrow (the prompt) + its ingredients
  w.prompt = () => 'Lasagne';
  click(w, d.querySelector(`#view [data-act="fam-meal"][data-day="${day(1)}"]`) || d.querySelectorAll('#view [data-act="fam-meal"]')[0]);
  check(await until(async () => (await call('GET', '/api/state')).tasks.some(t => t.title === 'Lasagne' && t.list_id === L.meals)), 'a meal added to the meal plan');
  const meal = (await call('GET', '/api/state')).tasks.find(t => t.list_id === L.meals && /Spaghetti/.test(t.title));
  click(w, d.querySelector(`#view [data-act="fam-ingr"][data-id="${meal.id}"]`));
  check(await until(async () => (await call('GET', '/api/state')).tasks.filter(t => t.list_id === L.shopping && t.status === 0).length === 7), 'ingredients on the shopping list (3 + 4)');
  check(await until(() => /4 items on the shopping list/.test(d.querySelector('#toast').textContent)), 'the toast says how many: ' + d.querySelector('#toast').textContent);
  // stars + rewards by a parent
  click(w, d.querySelector(`#view [data-act="fam-give"][data-kid="${LINA}"]`)); await sleep(150);
  md = [...d.querySelectorAll('.modal')].pop();
  click(w, md.querySelector('[data-n="3"]'));
  check(await until(async () => (await call('GET', '/api/family/kids')).kids[0].stars === 3), '+3 stars for Lina');
  click(w, d.querySelector(`#view [data-act="fam-rewards"][data-kid="${LINA}"]`)); await sleep(150);
  md = [...d.querySelectorAll('.modal')].pop();
  check(md.querySelectorAll('#rw-list .frow').length === 2 && md.querySelector(`[data-redeem="${ICE.id}"]`) && !md.querySelector(`[data-redeem="${ICE.id}"]`).disabled, 'rewards dialog: two, Ice cream redeemable');
  md.querySelector('#rw-title').value = 'Movie night'; md.querySelector('#rw-cost').value = '8';
  click(w, md.querySelector('[data-m="add"]'));
  check(await until(() => md.querySelectorAll('#rw-list .frow').length === 3), 'a third reward added');
  md.remove();
  w.close();

  // ================= jsdom: the task panel's family section
  w = await boot({user: 'alice', hash: 't/' + BD.id}); d = w.document;
  await until(() => d.querySelector('#detail .famsec'));
  check(d.querySelector('#detail .subsec h5')?.textContent === 'Gift ideas' && d.querySelector('#d-sub')?.placeholder === 'Add a gift idea', 'a birthday: "Gift ideas" instead of subtasks');
  check(d.querySelector('#d-fname')?.value === 'Grandma Erika' && d.querySelector('#d-fyear')?.value === '1946' && /turns \d+/.test(d.querySelector('#detail .fage')?.textContent), 'name, year, "turns N"');
  change(w, d.querySelector('#d-fyear'), '1947');
  check(await until(async () => (await call('GET', `/api/tasks/${BD.id}`)).fam.year === 1947), 'the year saved');
  w.eval(`openDetail(${chores[0].id})`); await until(() => d.querySelector('#d-rot'));
  check(d.querySelector('#d-rot').checked && d.querySelectorAll('#detail [data-rotp]').length === 3 && d.querySelector('#detail [data-rotm="done"]').getAttribute('aria-checked') === 'true', 'taking turns: on, three people, after each time');
  click(w, d.querySelector('#detail [data-rotm="week"]'));
  check(await until(async () => (await call('GET', `/api/tasks/${chores[0].id}`)).rotation?.mode === 'week'), 'every week: saved');
  click(w, d.querySelector(`#detail [data-rotp="${LINA}"]`));
  check(await until(async () => JSON.stringify((await call('GET', `/api/tasks/${chores[0].id}`)).rotation?.who) === JSON.stringify([1, BOB])), 'Lina out of the turns');
  await until(() => d.querySelector(`#detail [data-famp="${BOB}"]`));
  click(w, d.querySelector(`#detail [data-famp="${BOB}"]`));
  check(await until(async () => JSON.stringify((await call('GET', `/api/tasks/${chores[0].id}`)).people) === JSON.stringify([BOB])), 'Bob comes along');
  check(d.querySelector('#d-stars'), 'stars: shown in a list with a kid');
  change(w, d.querySelector('#d-stars'), '4');
  check(await until(async () => (await call('GET', `/api/tasks/${chores[0].id}`)).stars === 4), 'stars saved');
  const cb = d.querySelector('#d-rot'); cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => !(await call('GET', `/api/tasks/${chores[0].id}`)).rotation), 'taking turns off');
  // the meal panel: "To the shopping list"
  w.eval(`openDetail(${meal.id})`); await until(() => d.querySelector('#detail .famsec [data-act="fam-ingr"]'));
  check(!!d.querySelector('#detail .famsec [data-act="fam-ingr"]'), 'a meal: "To the shopping list" in its panel');
  w.eval('closeDetail()'); w.close();

  // ================= jsdom: "Used for" in the list dialog + the bar above a family list
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval('listModal()'); await sleep(200);
  md = d.querySelector('.modal.lnew');
  check(md.querySelector('#l-fam') && md.querySelector('#l-fam').options.length === 6, 'new list: "Used for" with six choices');
  md.querySelector('#l-name').value = 'Weekend shop';
  change(w, md.querySelector('#l-fam'), 'shopping');
  check(md.querySelector('#l-dab').checked, 'a shopping list: done at the bottom ticked');
  click(w, md.querySelector('[data-m="save"]'));
  const WS = await until(async () => (await call('GET', '/api/state')).lists.find(l => l.name === 'Weekend shop' && l.family === 'shopping'));
  check(WS && WS.checklist === 1 && (await call('GET', '/api/state')).sections.filter(s => s.list_id === WS.id).length === 0, 'created as a shopping list (2.22.0 #747: no shop areas by itself)');
  await until(() => w.eval('S.route.key') === 'l:' + WS.id);
  check(d.querySelector('#view .fambar [data-act="shop-start"]'), 'the bar: Shopping mode');
  check(!d.querySelector('#view .ghead[data-section]'), 'empty shop areas are not listed in the list view');
  w.eval(`listModal(${L.household})`); await sleep(200);
  md = d.querySelector('.modal.lmodal');
  check(md.querySelector('#l-fam').value === 'household', 'edit list: "Used for" Household');
  md.remove(); w.close();

  // ================= jsdom: shopping mode
  check((await call('POST', `/api/lists/${L.shopping}/shop-areas`, {})).added === 8, '2.22.0 (#747): the shop areas switched on by hand, the items sorted in');
  await call('POST', '/api/tasks', {title: 'Birthday candles', list_id: L.shopping});  // nothing to guess from: "Other"
  w = await boot({user: 'alice', hash: 'l/' + L.shopping}); d = w.document;
  await until(() => d.querySelector('#view [data-act="shop-start"]'));
  click(w, d.querySelector('#view [data-act="shop-start"]'));
  await until(() => d.querySelector('.shopmode .shopi'));
  const sm = () => d.querySelector('.shopmode');
  check(sm().getAttribute('role') === 'dialog' && sm().getAttribute('aria-modal') === 'true' && sm().querySelector('#shop-h')?.textContent.includes('Shopping list'), 'a modal dialog with the list name');
  const groups = [...sm().querySelectorAll('.shopg h3')].map(h => h.textContent.replace(/\s*\d+$/, ''));
  check(groups[0] === 'Fruit & vegetables' && groups.includes('Other'), 'grouped by area in the area order, the rest under Other: ' + groups);
  const apples = () => [...sm().querySelectorAll('.shopi')].find(x => /Apples/.test(x.textContent));
  click(w, apples().querySelector('[data-act="shop-tick"]'));
  check(await until(() => apples()?.classList.contains('done') && apples().closest('.shopdone')), 'ticked: Apples moves to "In the cart"');
  check(/7 left/.test(sm().querySelector('.shopn').textContent), 'the counter: 7 left');
  sm().querySelector('#shop-in').focus(); sm().querySelector('#shop-in').value = 'Butter';
  sm().querySelector('[data-shopadd]').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  check(await until(() => [...sm().querySelectorAll('.shopi')].some(x => /Butter/.test(x.textContent))) && d.activeElement?.id === 'shop-in', 'a new item: listed, the field keeps the focus');
  const butter = [...sm().querySelectorAll('.shopi')].find(x => /Butter/.test(x.textContent));
  click(w, butter.querySelector('[data-act="shop-area"]')); await sleep(150);
  const dairy = [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Dairy/.test(b.textContent));
  click(w, dairy);
  check(await until(async () => { const s = await call('GET', '/api/state'); const t = s.tasks.find(x => x.title === 'Butter'); return t && s.sections.find(y => y.id === t.section_id)?.name === 'Dairy & eggs'; }), 'the area menu: Butter -> Dairy & eggs');
  await call('POST', '/api/tasks', {title: 'Coffee', list_id: L.shopping}, CB);
  check(await until(() => [...(sm()?.querySelectorAll('.shopi') || [])].some(x => /Coffee/.test(x.textContent)), 60), 'live: Bob\'s new item shows up by itself');
  const t2 = (await call('POST', '/api/tasks', {title: 'Butter', list_id: L.shopping}, CB));
  check(t2.section_id && (await call('GET', '/api/state')).sections.find(y => y.id === t2.section_id)?.name === 'Dairy & eggs', 'the area memory: the next Butter goes to Dairy & eggs');
  click(w, sm().querySelector('[data-act="shop-close"]')); await sleep(150);
  check(!d.querySelector('.shopmode') && !w.eval('S.shop'), 'closed');
  w.close();

  // ================= jsdom: the kid's view, a reward request, the parent approves
  w = await boot({user: 'lina', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#view .kidv'));
  check(w.eval('S.route.mod') === 'family' && d.body.classList.contains('kidmode') && d.querySelector('#top h1')?.textContent === 'My day', 'a kid lands on its own view ("My day")');
  check(d.querySelector('.kidbal')?.textContent.includes('3') && /You have 3 stars/.test(d.querySelector('.kidbal').getAttribute('aria-label')), 'its stars, named for screen readers');
  const kt = () => d.querySelector(`.kidtasks [data-act="kid-tick"][data-id="${KT.id}"]`);
  check(kt() && kt().getAttribute('role') === 'checkbox' && /Done: Tidy up your room/.test(kt().getAttribute('aria-label')), 'its task: a big named checkbox');
  check(![...d.querySelectorAll('.kidtasks li')].some(li => /Clean the bathroom|Water the plants/.test(li.textContent)), 'only its own tasks');
  w.eval(`openDetail(${KT.id}); openPalette()`); await sleep(100);
  check(!w.eval('S.sel') && !d.querySelector('.palette:not(.hidden)') && w.eval(`topMoreItems().filter(x => x.label).map(x => x.label).join()`) === 'Account,Settings,Log out',
    'a kid gets no task panel, no command palette; "…" has only its account');
  click(w, kt());
  check(await until(() => /\+2 stars!/.test(d.querySelector('#toast')?.textContent || '')), 'ticked: "+2 stars!"');
  check(await until(() => d.querySelector('.kidbal')?.textContent.includes('5')), 'the balance: 5');
  const want = () => d.querySelector(`[data-act="kid-want"][data-rid="${ICE.id}"]`);
  check(want() && /I want this/.test(want().textContent) && !d.querySelector('[data-act="kid-want"][data-rid]:not([data-rid="' + ICE.id + '"])') && /more stars/.test(d.querySelector('.kidrw').textContent),
    'Ice cream: "I want this"; the Zoo shows how many stars are missing');
  click(w, want());
  check(await until(() => /Asked – waiting/.test(d.querySelector('.kidrw').textContent)), 'asked: waiting');
  w.close();
  w = await boot({user: 'alice', hash: 'family'}); d = w.document;
  await until(() => d.querySelector('#view .kreq'));
  check(/Lina would like: 🍦 Ice cream/.test(d.querySelector('#view .kreq').textContent) && d.querySelector('#side [data-go="family"] .nunread'), 'the parent sees the request (+ the count in the sidebar)');
  click(w, d.querySelector('#view .kreq [data-act="fam-decide"][data-ok="1"]'));
  check(await until(async () => (await call('GET', '/api/family/kids')).kids[0].stars === 3), 'approved: -2 stars');
  check(await until(() => !d.querySelector('#view .kreq')), 'the request is gone');
  // the dashboard card + palette commands
  w.eval(`go('home')`); await until(() => d.querySelector('#view .dc-family'));
  check(/Grandma Erika/.test(d.querySelector('#view .dc-family').textContent), 'dashboard: the Family card with the birthday');
  const pal = w.eval(`palAll().map(x => x.id)`);
  check(['a:occ', 'a:dl', 'a:pack:pool', `a:shop:${L.shopping}`, 'v:family'].every(id => pal.includes(id)), 'palette: new birthday / deadline / packing list, shopping mode, the Family view');
  w.close();

  // ================= jsdom: the welcome tour asks "What do you use Kalmido for?"
  const NEWU = (await call('POST', '/api/users', {username: 'nina', display_name: 'Nina', password: 'password123'})).id;
  await call('PATCH', `/api/users/${NEWU}`, {});
  const CN = await login('nina');
  await call('PATCH', '/api/settings', {tour: 'pending'}, CN);
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CN}, body: JSON.stringify({tour: 'pending'})});
  w = await boot({user: 'nina', hash: 'today', ls: {'tasks.lastKey': null}}); d = w.document;
  if (await until(() => d.querySelector('.tour .tpurp'), 40)) {
    check(d.querySelectorAll('.tour [data-tpurpose]').length === 4, 'tour: four purposes on the first card');
    click(w, d.querySelector('.tour [data-tpurpose="family"]')); await sleep(100);
    check(d.querySelector('.tour [data-tpurpose="family"]').classList.contains('on'), 'tour: Family picked');
    click(w, d.querySelector('.tour [data-tour="next"]'));
    check(await until(async () => (await call('GET', '/api/state', null, CN)).settings.features.split(',').includes('family'), 60), 'tour: leaving the first card sets the purpose');
  } else check(true, 'tour not offered to this account (sample_ask off): skipped');
  w.close();

  // ================= Firefox: layout, touch, axe
  const ffLogin = async ({ev, nav}, user, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel = '#top h1', n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  const tapper = ({cmd, ctx}) => async (x, y) => {
    await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
    await cmd('input.releaseActions', {context: ctx});
  };
  const SMALL = sel => `(() => { const coarse = matchMedia('(pointer: coarse)').matches, min = coarse ? 43.5 : 23.5; return [...document.querySelectorAll('${sel}')].filter(b => { const r = b.getBoundingClientRect(), cs = getComputedStyle(b); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !b.closest('[hidden]'); })
    .filter(b => { const r = b.getBoundingClientRect(); return r.width < min || r.height < min; }).map(b => (b.dataset.act || b.className) + ' ' + Math.round(b.getBoundingClientRect().width) + 'x' + Math.round(b.getBoundingClientRect().height)).slice(0, 8); })()`;
  const axe = async (ev, where) => {
    if ((await ev(`typeof axe`)) === 'undefined') await ev(AXE + '\n;1');
    const r = await ev(`axe.run(document, {runOnly: {type: 'tag', values: ${JSON.stringify(TAGS)}}, resultTypes: ['violations']}).then(r => r.violations.map(v => ({id: v.id, n: v.nodes.length, nodes: v.nodes.slice(0, 2).map(x => x.target.join(' ') + ' ' + (x.failureSummary || '').slice(0, 120))})))`);
    check(!r.length, `${where}: no axe violations: ` + r.map(v => `${v.id}(${v.n}) ${v.nodes[0]}`).join(' | ').slice(0, 700));
  };
  for (const [vw, vh, th] of [[360, 780, 'light'], [390, 844, 'dark'], [412, 915, 'light'], [904, 1080, 'dark'], [1080, 904, 'light']]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tap = tapper(o), tag = `${vw}x${vh} ${th}`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o, 'alice', th) === 200, tag + ': login');
    await o.nav(B + '#family'); await ready(ev, '#view .fam');
    check(await ev(`document.documentElement.scrollWidth - innerWidth`) <= 0, `${tag}: Family view: nothing sideways`);
    const sm1 = await ev(SMALL('#view .fam button, #view .fam a.frow, #view .fam a.btn'));
    check(!sm1.length, `${tag}: Family view: touch targets 44 px ` + JSON.stringify(sm1));
    if (vw === 390) await axe(ev, `${tag} Family view`);
    await shot(`p2190f-${vw}x${vh}-${th}-family.png`);
    // shopping mode with real taps
    await o.nav(B + '#l/' + L.shopping); await ready(ev, '#view [data-act="shop-start"]');
    const sb = await ev(`(() => { const r = document.querySelector('#view [data-act="shop-start"]').getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height}; })()`);
    check(sb.h >= 43.5, `${tag}: the Shopping mode button is a 44 px target in view ` + JSON.stringify(sb));
    await tap(sb.x, sb.y);
    check(await until(() => ev(`!!document.querySelector('.shopmode .shopi')`), 40), `${tag}: one tap opens shopping mode`);
    await sleep(200);
    check(await ev(`document.activeElement?.id !== 'shop-in'`), `${tag}: shopping mode on touch: the add field is not focused (no keyboard over the list)`);
    check(await ev(`document.documentElement.scrollWidth - innerWidth`) <= 0, `${tag}: shopping mode: nothing sideways`);
    const sm2 = await ev(SMALL('.shopmode button, .shopmode input'));
    check(!sm2.length, `${tag}: shopping mode: targets 44 px ` + JSON.stringify(sm2));
    if (vw === 390) await axe(ev, `${tag} shopping mode`);
    await shot(`p2190f-${vw}x${vh}-${th}-shopmode.png`);
    const it = await ev(`(() => { const b = [...document.querySelectorAll('.shopmode .shopi:not(.done) [data-act="shop-tick"]')][0]; b.scrollIntoView({block: 'center'}); const r = b.getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2, id: b.dataset.id}; })()`);
    await tap(it.x, it.y);
    check(await until(async () => !!(await call('GET', `/api/tasks/${it.id}`)).completed_at, 40), `${tag}: a tap ticks the item`);
    await call('POST', `/api/tasks/${it.id}/reopen`);
    await ev(`(() => { document.querySelector('.shopmode')?.remove(); return 1; })()`);
    // the task panel's family section
    await o.nav(B + '#t/' + BD.id); await ready(ev, '#detail .famsec');
    check(await ev(`document.documentElement.scrollWidth - innerWidth`) <= 0, `${tag}: task panel: nothing sideways`);
    const sm3 = await ev(SMALL('#detail .famsec button'));
    check(!sm3.length, `${tag}: family section: targets 44 px ` + JSON.stringify(sm3));
    if (vw === 390) await axe(ev, `${tag} task panel (birthday)`);
    // the birthday dialog
    await o.nav(B + '#family'); await ready(ev, '#view .fam');
    await ev(`(() => { document.querySelector('#view [data-act="fam-occ"]').click(); return 1; })()`); await sleep(500);
    check(await ev(`(() => { const c = document.querySelector('.modal.famdlg .card').getBoundingClientRect(); return c.left >= 0 && c.right <= innerWidth + .5; })()`), `${tag}: the birthday dialog fits`);
    if (vw === 390) await axe(ev, `${tag} birthday dialog`);
    await ev(`(() => { document.querySelector('.modal.famdlg')?.remove(); return 1; })()`);
    // the kid view with a real tap on its reward
    check(await ffLogin(o, 'lina', th) === 200, tag + ': kid login');
    await o.nav(B + '#'); await ready(ev, '#view .kidv');
    check(await ev(`document.documentElement.scrollWidth - innerWidth`) <= 0 && await ev(`getComputedStyle(document.querySelector('#side')).display === 'none' && (!document.querySelector('#tabs') || getComputedStyle(document.querySelector('#tabs')).display === 'none')`),
      `${tag}: kid view: no sidebar, no tab bar, nothing sideways`);
    const sm4 = await ev(SMALL('#view .kidv button'));
    check(!sm4.length, `${tag}: kid view: targets 44 px ` + JSON.stringify(sm4));
    const kc = await ev(`(() => { const b = document.querySelector('.kidchk'); if (!b) return null; const r = b.getBoundingClientRect(); return {w: r.width, h: r.height}; })()`);
    check(!kc || (kc.w >= 51 && kc.h >= 51), `${tag}: the kid's tick is big (52 px) ` + JSON.stringify(kc));
    if (vw === 390) await axe(ev, `${tag} kid view`);
    await shot(`p2190f-${vw}x${vh}-${th}-kid.png`);
  }, true);
  for (const [vw, vh, th] of [[1440, 900, 'light'], [1920, 1080, 'dark']]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${vw} ${th}`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o, 'alice', th) === 200, tag + ': login');
    await o.nav(B + '#family'); await ready(ev, '#view .fam');
    check(await ev(`document.documentElement.scrollWidth - innerWidth`) <= 0, `${tag}: Family view: nothing sideways`);
    const cols = await ev(`new Set([...document.querySelectorAll('#view .fcard')].map(c => Math.round(c.getBoundingClientRect().left))).size`);
    check(cols >= 2, `${tag}: the cards in columns (${cols})`);
    await axe(ev, `${tag} Family view`);
    // keyboard only: Tab reaches the week arrows, Enter moves the week, the focus stays
    await ev(`(() => { document.querySelector('#view [data-act="fam-week"][data-d="7"]').focus(); return 1; })()`);
    await ev(`(() => { document.activeElement.click(); return 1; })()`); await sleep(300);  // headless: Enter does not activate a native button
    check(await ev(`S.famWeek > mondayOf(today()) && document.activeElement?.dataset.act === 'fam-week'`), `${tag}: "Next week" from the keyboard: moved, focus kept`);
    await ev(`(() => { document.querySelector('#view [data-act="fam-dl"]').click(); return 1; })()`); await sleep(500);
    await axe(ev, `${tag} deadline dialog`);
    // real Tab keys, after other dialogs were open and closed (they once made Firefox bounce between two buttons)
    const seen = [];
    for (let i = 0; i < 9; i++) { await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'kb', actions: [{type: 'keyDown', value: '\uE004'}, {type: 'keyUp', value: '\uE004'}]}]}); await sleep(80); seen.push(await ev(`document.activeElement.id || document.activeElement.dataset.dl || ''`)); }
    check(seen.includes('dl-who') && new Set(seen).size >= 7 && await ev(`!!document.activeElement.closest('.modal.famdlg')`), `${tag}: Tab walks through the deadline dialog and stays in it: ` + seen.join(','));
    await ev(`(() => { document.querySelector('.modal.famdlg')?.remove(); shopModeOpen(${L.shopping}); return 1; })()`); await sleep(600);
    await axe(ev, `${tag} shopping mode`);
    await shot(`p2190f-${vw}-${th}-shopmode.png`);
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
