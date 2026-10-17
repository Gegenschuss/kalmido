// 2.72.0 UI tests (part B), own container (start.sh). jsdom:
// #1333 the household budget: the module switch (Settings > Modules, Home), the card on Home & life creates a budget,
//       an entry is added, changed, deleted and brought back by one undo step, the month switch, a category with a
//       monthly limit shows its bar (over the limit marked), a recurring entry is booked from "Open this month", the CSV
//       import with column mapping (German columns, one duplicate), a person with read access sees no write buttons
// Firefox 390 touch: the budget view has no horizontal scrolling, "+ Entry" >= 44 px, screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p272_b_budget_ui', check, shots: 'P272B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'collab,contracts,budget';
const pad = n => String(n).padStart(2, '0');
const NOW = new Date(), MONTH = `${NOW.getFullYear()}-${pad(NOW.getMonth() + 1)}`, DAY = `${MONTH}-${pad(Math.min(NOW.getDate(), 28))}`;
const DE = d => `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,contracts'});
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);

  // ================= the module switch: off by default, part of the area Home
  let w = await boot({user: 'alice'}), d = w.document;
  check(!w.eval(`feat('budget')`), '#1333: the module is off by default');
  check(w.eval(`mg_area('life')[3].some(p => p[0] === 'budget')`), '#1333: Budget is a part of the area Home');
  w.eval(`settingsModal('modules')`); await until(() => d.querySelector('[data-feat="budget"]'));
  const sw = d.querySelector('[data-feat="budget"]');
  check(sw && !sw.checked, '#1333: Settings > Modules has the switch, off');
  if (sw) { sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true})); }
  // 2.72.0 (#1333): the settings come with /api/state (there is no GET /api/settings)
  const fts = async () => ((await call('GET', '/api/state')).settings?.features || '').split(',');
  await until(async () => (await fts()).includes('budget'));
  check((await fts()).includes('budget'), '#1333: the switch turns the module on ' + (await fts()).join(','));
  w.close();
  await call('PATCH', '/api/settings', {features: FEAT});

  // ================= the card on Home & life creates a budget
  w = await boot({user: 'alice', hash: 'life'}); d = w.document;
  await until(() => d.querySelector('.lc-budget [data-bg="create"]'));
  check(d.querySelector('.lc-budget [data-bg="create"]'), '#1333: Home & life: the card offers "Create a budget"');
  click(w, d.querySelector('.lc-budget [data-bg="create"]'));
  await until(() => /^#budget\/\d+/.test(w.location.hash) && d.querySelector('.bgview .bgadd'));
  const LID = +(/^#budget\/(\d+)/.exec(w.location.hash) || [])[1];
  check(LID > 0, '#1333: created, the budget view opens ' + w.location.hash);
  const lst = (await call('GET', '/api/state')).lists.find(l => l.id === LID);
  check(lst && lst.life === 'budget', '#1333: a list of the kind budget');
  check(d.querySelector('.bgview .bgtiles') && d.querySelector('.bgmn'), '#1333: totals and the month on top');
  const B0 = await call('GET', `/api/budget/${LID}?month=${MONTH}`);
  check(B0.cats && B0.cats.length >= 6, '#1333: default categories ' + (B0.cats || []).length);
  const outCat = (B0.cats || []).find(c => c.kind === 'out');

  // ================= an entry: add, change, delete, undo
  const dlg = () => d.querySelector('.modal.bgdlg');
  click(w, d.querySelector('[data-bg="add"]')); await until(() => dlg());
  check(dlg()?.querySelector('#bg-amt')?.getAttribute('inputmode') === 'decimal', '#1333: the amount field takes a decimal keyboard');
  check(dlg()?.querySelector('#bg-kind [data-kind="out"][aria-checked="true"]'), '#1333: a new entry is an expense');
  dlg().querySelector('#bg-amt').value = '12,50';
  dlg().querySelector('#bg-title').value = 'Bakery';
  dlg().querySelector('#bg-day').value = DAY;
  if (outCat) dlg().querySelector('#bg-cat').value = String(outCat.id);
  click(w, dlg().querySelector('[data-m="save"]')); await until(() => !dlg());
  let E = await until(async () => (await call('GET', `/api/budget/${LID}?month=${MONTH}`)).entries?.find(x => x.title === 'Bakery'));
  check(E && +E.amount === 12.5 && E.kind === 'out' && E.cat_id === (outCat?.id ?? null), '#1333: the entry is saved (12,50 = 12.5) ' + JSON.stringify(E));
  await until(() => d.querySelector(`[data-bg="entry"][data-id="${E?.id}"]`));
  check(/Bakery/.test(d.querySelector('.bgview')?.textContent || ''), '#1333: the list shows the entry');
  check(w.eval('HIST.undo.length') >= 1, '#1333: adding is one undo step');
  click(w, d.querySelector(`[data-bg="entry"][data-id="${E.id}"]`)); await until(() => dlg());
  check(dlg()?.querySelector('#bg-title')?.value === 'Bakery', '#1333: the entry opens with its values');
  dlg().querySelector('#bg-amt').value = '15';
  click(w, dlg().querySelector('[data-m="save"]')); await until(() => !dlg());
  E = await until(async () => { const x = (await call('GET', `/api/budget/${LID}?month=${MONTH}`)).entries?.find(y => y.title === 'Bakery'); return x && +x.amount === 15 && x; });
  check(E && +E.amount === 15, '#1333: changed to 15');
  await until(() => d.querySelector(`[data-bg="entry"][data-id="${E.id}"]`));
  click(w, d.querySelector(`[data-bg="entry"][data-id="${E.id}"]`)); await until(() => dlg());
  click(w, dlg().querySelector('[data-bg-del]'));
  await until(async () => !(await call('GET', `/api/budget/${LID}?month=${MONTH}`)).entries?.some(y => y.title === 'Bakery'));
  check(!(await call('GET', `/api/budget/${LID}?month=${MONTH}`)).entries?.some(y => y.title === 'Bakery'), '#1333: deleted');
  await w.eval(`histStep('undo')`); await sleep(500);
  E = await until(async () => (await call('GET', `/api/budget/${LID}?month=${MONTH}`)).entries?.find(y => y.title === 'Bakery'));
  check(E && +E.amount === 15 && E.day === DAY, '#1333: undo brings the entry back ' + JSON.stringify(E));
  await until(() => /Bakery/.test(d.querySelector('.bgview')?.textContent || ''));
  check(/Bakery/.test(d.querySelector('.bgview')?.textContent || ''), '#1333: ... and the view shows it again');

  // ================= the month switch
  const m0 = d.querySelector('.bgmn')?.textContent;
  click(w, d.querySelector('[data-bg="prev"]')); await until(() => d.querySelector('.bgmn')?.textContent !== m0);
  check(d.querySelector('.bgmn')?.textContent !== m0 && w.eval('BG.month') !== MONTH, '#1333: ‹ shows the month before ' + d.querySelector('.bgmn')?.textContent);
  check(!/Bakery/.test(d.querySelector('.bgview')?.textContent || ''), '#1333: ... without this month\'s entries');
  check(d.querySelector('[data-bg="now"]'), '#1333: "This month" leads back');
  click(w, d.querySelector('[data-bg="now"]')); await until(() => d.querySelector('.bgmn')?.textContent === m0);
  check(w.eval('BG.month') === MONTH, '#1333: back in this month');

  // ================= a category with a monthly limit: the bar, over the limit marked
  await until(() => d.querySelector('[data-bg="cats"]'));
  click(w, d.querySelector('[data-bg="cats"]')); await until(() => dlg()?.querySelector('#bg-cnew'));
  dlg().querySelector('#bg-cnew').value = 'Fun';
  dlg().querySelector('#bg-cnl').value = '100';
  click(w, dlg().querySelector('[data-cadd]'));
  const FUN = await until(async () => (await call('GET', `/api/budget/${LID}?month=${MONTH}`)).cats?.find(c => c.name === 'Fun'));
  check(FUN && +FUN.limit === 100 && FUN.kind === 'out', '#1333: the category with its limit ' + JSON.stringify(FUN));
  await until(() => dlg()?.querySelector(`.bgcr[data-cid="${FUN?.id}"]`));
  check(dlg()?.querySelector(`.bgcr[data-cid="${FUN?.id}"] [data-cmv]`), '#1333: categories can be moved with arrows');
  click(w, dlg().querySelector('[data-m="close"]')); await until(() => !dlg());
  await call('POST', `/api/budget/${LID}/entries`, {day: DAY, amount: 60, kind: 'out', title: 'Cinema', cat_id: FUN.id});
  w.eval(`bg_after()`);
  // 2.72.0 (#1333): wait for the reloaded bar (the bar at 0 % is there before the reload)
  await until(() => [...d.querySelectorAll('.bgcat')].some(x => /Fun/.test(x.textContent) && /width:\s*60%/.test(x.querySelector('.bgbar i')?.getAttribute('style') || '')));
  let fc = [...d.querySelectorAll('.bgcat')].find(x => /Fun/.test(x.textContent));
  check(fc && /width:\s*60%/.test(fc.querySelector('.bgbar i')?.getAttribute('style') || '') && !fc.classList.contains('over'), '#1333: the bar shows 60 of 100 ' + fc?.innerHTML.slice(0, 200));
  await call('POST', `/api/budget/${LID}/entries`, {day: DAY, amount: 50, kind: 'out', title: 'Concert', cat_id: FUN.id});
  w.eval(`bg_after()`);
  await until(() => [...d.querySelectorAll('.bgcat.over')].some(x => /Fun/.test(x.textContent)));
  fc = [...d.querySelectorAll('.bgcat')].find(x => /Fun/.test(x.textContent));
  check(fc && fc.classList.contains('over') && fc.querySelector('.bgbar.over'), '#1333: over the limit: marked');

  // ================= a recurring entry: "Open this month" -> Booked
  const REC = await call('POST', `/api/budget/${LID}/recurring`, {title: 'Rent', amount: 800, kind: 'out', per: 'month', start: MONTH});
  check(REC.id, '#1333: a recurring entry (API) ' + JSON.stringify(REC).slice(0, 120));
  w.eval(`bg_after()`);
  await until(() => d.querySelector(`[data-bg="book"][data-id="${REC.id}"]`));
  check(/Open this month/.test(d.querySelector('.bgopen')?.textContent || '') && /Rent/.test(d.querySelector('.bgopen')?.textContent || ''), '#1333: "Open this month" lists it');
  click(w, d.querySelector(`[data-bg="book"][data-id="${REC.id}"]`));
  const RB = await until(async () => (await call('GET', `/api/budget/${LID}?month=${MONTH}`)).entries?.find(x => x.recurring_id === REC.id));
  check(RB && +RB.amount === 800 && RB.title === 'Rent', '#1333: "Booked" creates the entry ' + JSON.stringify(RB));
  await until(() => !d.querySelector(`[data-bg="book"][data-id="${REC.id}"]`));
  check(!d.querySelector(`[data-bg="book"][data-id="${REC.id}"]`), '#1333: ... and it is no longer open');
  // the recurring dialog lists it
  click(w, d.querySelector('[data-bg="rec"]')); await until(() => dlg()?.querySelector('.bgrecs'));
  check(/Rent/.test(dlg()?.querySelector('.bgrecs')?.textContent || '') && dlg().querySelector('#bg-rper') && dlg().querySelector('#bg-rs'), '#1333: the recurring entries with their form');
  click(w, dlg().querySelector('[data-m="close"]')); await until(() => !dlg());

  // ================= CSV import: German columns, one duplicate (the bakery entry), the mapping
  const csv = ['Buchungstag;Verwendungszweck;Beguenstigter/Zahlungspflichtiger;Betrag',
    `${DE(DAY)};Bakery;;-15,00`, `${DE(DAY)};Gehalt Oktober;Example GmbH;2.500,00`, `${DE(DAY)};Supermarkt;Example Markt;-42,30`].join('\r\n');
  click(w, d.querySelector('[data-bg="csv"]')); await until(() => dlg()?.querySelector('[data-cs-file]'));
  check(/No bank access/.test(dlg()?.textContent || ''), '#1333: the import says: no bank access');
  w.__csv = [new w.File([csv], 'konto.csv', {type: 'text/csv'})];
  w.eval(`(() => { const f = document.querySelector('[data-cs-file]'); Object.defineProperty(f, 'files', {configurable: true, value: window.__csv}); f.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
  await until(() => dlg()?.querySelector('#cs-date'));
  check(dlg()?.querySelector('#cs-date') && dlg().querySelector('#cs-title') && dlg().querySelector('.bgtbl'), '#1333: the columns to map, with a preview ' + (dlg()?.querySelector('.aerr')?.textContent || '') + ' ' + (dlg()?.querySelector('.bgcsv')?.innerHTML || 'no dialog').slice(0, 300));
  const opt = (sel, rx) => [...dlg().querySelectorAll(`${sel} option`)].find(o => rx.test(o.textContent))?.value;
  dlg().querySelector('#cs-date').value = opt('#cs-date', /Buchungstag/);
  dlg().querySelector('#cs-amt').value = opt('#cs-amt', /Betrag/);
  dlg().querySelector('#cs-title').value = opt('#cs-title', /Verwendungszweck/);
  dlg().querySelector('#cs-cp').value = opt('#cs-cp', /Beguenstigter/);
  dlg().querySelector('#cs-dec').value = ',';
  dlg().querySelector('#cs-df').value = 'DD.MM.YYYY';
  click(w, dlg().querySelector('[data-cs="next"]'));
  await until(() => dlg()?.querySelectorAll('.bgpr').length === 3);
  const rows = [...(dlg()?.querySelectorAll('.bgpr') || [])];
  check(rows.length === 3, '#1333: three rows in the preview ' + rows.length);
  const dupRow = rows.find(x => /Bakery/.test(x.textContent));
  check(dupRow && dupRow.classList.contains('dup') && !dupRow.querySelector('[data-csr]').checked, '#1333: the duplicate is marked and not chosen');
  const sal = rows.find(x => /Gehalt/.test(x.textContent));
  check(sal && sal.querySelector('.bgamt.in') && /2[.,]?500/.test(sal.textContent), '#1333: a plus amount is income (2.500,00)');
  check(/Take over 2 entries/.test(dlg().querySelector('[data-cs="next"]')?.textContent || ''), '#1333: "Take over 2 entries" ' + dlg().querySelector('[data-cs="next"]')?.textContent);
  click(w, dlg().querySelector('[data-cs="next"]')); await until(() => !dlg());
  const B1 = await call('GET', `/api/budget/${LID}?month=${MONTH}`);
  check(B1.entries?.filter(x => x.title === 'Bakery').length === 1, '#1333: the duplicate is not imported twice');
  const sup = B1.entries?.find(x => x.title === 'Supermarkt');
  check(sup && +sup.amount === 42.3 && sup.kind === 'out' && sup.source === 'csv', '#1333: imported as an expense from csv ' + JSON.stringify(sup));
  check(B1.entries?.some(x => /Gehalt/.test(x.title) && x.kind === 'in' && +x.amount === 2500), '#1333: the salary as income');
  w.close();

  // ================= read access only: no write buttons
  await call('PUT', `/api/lists/${LID}/members`, {user_id: bob.id, role: 'view'});
  const wb = await boot({user: 'bob', hash: `budget/${LID}`}); const db = wb.document;
  await until(() => db.querySelector('.bgview .bgtiles'));
  check(db.querySelector('.bgview .bgtiles') && /Bakery/.test(db.querySelector('.bgview')?.textContent || ''), '#1333: bob sees the shared budget');
  check(!db.querySelector('[data-bg="add"]') && !db.querySelector('[data-bg="book"]') && !db.querySelector('[data-bg="cats"]') && !db.querySelector('[data-bg="csv"]'), '#1333: read only: no write buttons');
  check(db.querySelector('.bgro'), '#1333: read only: the hint says so');
  const be = db.querySelector('[data-bg="entry"]'); click(wb, be); await until(() => db.querySelector('.modal.bgdlg'));
  check(db.querySelector('.modal.bgdlg') && !db.querySelector('.modal.bgdlg [data-bg-del]') && !db.querySelector('.modal.bgdlg [data-bgf-up]'), '#1333: read only: an entry opens without delete / upload');
  wb.close();

  // ================= Firefox: the phone (390, touch)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + `#budget/${LID}`);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('.bgview .bgadd')`).catch(() => false)); i++) await sleep(300);
    await sleep(800);
    const g = await ev(`(() => { const a = document.querySelector('.bgview .bgadd'); if (!a) return null; const r = a.getBoundingClientRect();
      return {add: Math.min(r.width, r.height), wide: document.documentElement.scrollWidth <= 390, view: document.querySelector('#view').scrollWidth <= document.querySelector('#view').clientWidth + 1}; })()`);
    check(g && g.wide && g.view, `${tag}: #1333 the budget view without horizontal scrolling ` + JSON.stringify(g));
    check(g && g.add >= 44, `${tag}: #1333 "+ Entry" >= 44 px ` + JSON.stringify(g));
    await shot('p272b-390-budget.png');
    await ev(`(() => { document.querySelector('[data-bg="add"]').click(); return 1; })()`); await sleep(700);
    const m = await ev(`(() => { const c = document.querySelector('.bgdlg .card'); if (!c) return null; const r = c.getBoundingClientRect(); return {left: r.left, right: r.right, wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(m && m.left >= 0 && m.right <= 390 && m.wide, `${tag}: #1333 the entry dialog fits the phone ` + JSON.stringify(m));
    await shot('p272b-390-entry.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
