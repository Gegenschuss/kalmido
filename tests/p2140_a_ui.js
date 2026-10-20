// 2.140.0 UI tests, part A, own container (start.sh). Invented items only.
// #2131 shopping list: the amount in the task row and big in shopping mode, the price sums (still to buy / in the cart),
// a new item "500 g Flour" = Flour with the amount, the same item again = the amount added (not doubled), amount + price
// by a tap on the amount; offline in the shop: ticks and new items wait in the outbox, a quiet hint with the number of
// waiting changes, no error toasts, everything goes out on reconnect (once); the task panel: amount / unit / price and
// "Take “2” from the title"
// #2132 recipes: servings in the task panel, the ingredients choice (scaled to the servings, untick what is at home),
// "Plan on a day", the meal plan: the range on its button, back to today, the "+" of a day offers the recipes, the
// Recipes button in the card
// P2140A_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2140A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60, ms = 150) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(ms); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const submit = (w, form) => form && form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
const day = n => TC.day(n);
const tasks = async () => (await call('GET', '/api/state')).tasks;
const RECIPE = '## Ingredients\n- 500 g Mince\n- 2 Onions\n- 1 can Tomatoes\n\n## Method\n1. Chop the onions\n2. Layer everything\n';

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,family'});
  const SH = (await call('POST', '/api/lists', {name: 'Groceries', family: 'shopping'})).id;
  const mk = async (title, fam, lid = SH, extra = {}) => (await call('POST', '/api/tasks', {title, list_id: lid, ...(fam ? {fam} : {}), ...extra})).id;
  const MILK = await mk('Milk', {kind: 'shop', qty: 2, unit: 'l', price: 1.2});
  const BREAD = await mk('Bread', {kind: 'shop', price: 2.5});
  const APPLES = await mk('Apples');
  const BUTTER = await mk('2x Butter');
  const RL = (await call('POST', '/api/lists', {name: 'Recipes', family: 'recipes'})).id;
  const RID = await mk('Lasagne', {kind: 'recipe', serves: 4}, RL, {content: RECIPE});

  // ================= #2131 the row and shopping mode
  let w = await boot({user: 'alice', hash: 'l/' + SH}), d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${MILK}"]`));
  check(d.querySelector(`#view .trow[data-id="${MILK}"] .qtym`)?.textContent === '2 l' && !d.querySelector(`#view .trow[data-id="${APPLES}"] .qtym`), 'the amount in the task row (only where there is one)');
  w.eval(`shopModeOpen(${SH})`);
  const sm = () => d.querySelector('.shopmode');
  const item = name => [...sm().querySelectorAll('.shopi')].find(x => x.querySelector('.shopt')?.textContent.startsWith(name));
  await until(() => sm()?.querySelector('.shopi'));
  check(item('Milk')?.querySelector('.shopq')?.textContent === '2 l' && item('Apples')?.querySelector('.shopq.none'), 'shopping mode: the amount big next to the item, a quiet + without one');
  check(/3\.70/.test(sm().querySelector('.shopsum')?.textContent || ''), 'the price sum: ' + (sm().querySelector('.shopsum')?.textContent || ''));
  click(w, item('Milk').querySelector('[data-act="shop-tick"]'));
  check(await until(() => item('Milk')?.classList.contains('done')), 'Milk ticked');
  const sums = () => [...sm().querySelectorAll('.shopsum b')].map(b => b.textContent);
  check(await until(() => /2\.50/.test(sums()[0] || '') && /1\.20/.test(sums()[1] || '')), 'still to buy 2.50, in the cart 1.20: ' + sums());
  sm().querySelector('#shop-in').value = '500 g Flour'; submit(w, sm().querySelector('[data-shopadd]'));
  check(await until(async () => (await tasks()).some(t => t.title === 'Flour' && t.list_id === SH && t.fam?.qty === 500 && t.fam.unit === 'g')), 'a new item: "500 g Flour" = Flour, 500 g');
  await until(() => item('Flour'));
  sm().querySelector('#shop-in').value = '200 g Flour'; submit(w, sm().querySelector('[data-shopadd]'));
  check(await until(async () => { const f = (await tasks()).filter(t => t.title === 'Flour' && t.list_id === SH); return f.length === 1 && f[0].fam?.qty === 700; }), 'the same item again: the amount added, not doubled');
  check(/Already on the list: Flour/.test(d.querySelector('#toast')?.textContent || ''), 'and said so');
  // amount + price by a tap on the amount
  click(w, item('Apples').querySelector('[data-act="shop-qty"]'));
  let md = await until(() => d.querySelector('.modal.shopqdlg'));
  md.querySelector('#sq-qty').value = '3'; md.querySelector('#sq-price').value = '0,99';
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => { const t = (await tasks()).find(x => x.id === APPLES); return t?.fam?.qty === 3 && t.fam.price === 0.99; }), 'amount + price from shopping mode');
  check(await until(() => item('Apples')?.querySelector('.shopq')?.textContent === '3'), 'shown at once');

  // ================= #2131 offline in the shop
  const offCalls = []; { const of = w.fetch; w.fetch = (u, o = {}) => { if (w.__offline) offCalls.push((o.method || 'GET') + ' ' + new URL(String(u), B).pathname); return of(u, o); }; }
  const toasts = []; { const ot = w.toast; w.toast = (m, ...r) => { toasts.push(String(m)); return ot(m, ...r); }; }
  w.__offline = true;
  click(w, item('Bread').querySelector('[data-act="shop-tick"]'));
  check(await until(() => item('Bread')?.classList.contains('done') && w.eval('OUT.q.length') === 1), 'offline: ticked locally, the change waits');
  sm().querySelector('#shop-in').value = 'Eggs'; submit(w, sm().querySelector('[data-shopadd]'));
  check(await until(() => item('Eggs') && w.eval('OUT.q.length') === 2), 'offline: a new item listed, waiting');
  check(await until(() => /Offline – changes are sent later/.test(sm().querySelector('.shopoff')?.textContent || '') && /2 changes waiting/.test(sm().querySelector('.shopoff').textContent), 40), 'a quiet hint with the waiting changes: ' + (sm().querySelector('.shopoff')?.textContent || ''));
  await sleep(4500);  // two polls: no error toasts while offline
  check(!toasts.some(x => /Offline: only works again|Error/.test(x)), 'no error toasts while offline: ' + toasts.join(' | ') + ' calls: ' + [...new Set(offCalls)].join(', '));
  w.__offline = false; w.dispatchEvent(new w.Event('online'));
  check(await until(() => w.eval('OUT.q.length') === 0, 100), 'back online: the queue goes out');
  check(await until(async () => { const ts = await tasks(); return ts.find(t => t.id === BREAD)?.status !== 0 && ts.filter(t => t.title === 'Eggs' && t.list_id === SH).length === 1; }), 'Bread ticked on the server, Eggs there once');
  check(await until(() => !sm().querySelector('.shopoff'), 40), 'the hint goes');
  click(w, sm().querySelector('[data-act="shop-close"]'));
  w.close();

  // ================= #2131 the task panel
  w = await boot({user: 'alice', hash: 't/' + APPLES}); d = w.document;
  await until(() => d.querySelector('#d-fqty'));
  check(d.querySelector('#d-fqty').value === '3' && /0\.99/.test(d.querySelector('#d-fprice').value), 'the panel: amount and price');
  change(w, d.querySelector('#d-funit'), 'kg');
  check(await until(async () => (await tasks()).find(x => x.id === APPLES)?.fam?.unit === 'kg'), 'the unit saved (amount + price stay)');
  check((await tasks()).find(x => x.id === APPLES).fam.price === 0.99, '… the price stayed');
  w.eval(`openDetail(${BUTTER})`);
  const tb = await until(() => d.querySelector('#detail [data-act="fam-qtytitle"]'));
  check(tb && /Take “2” from the title/.test(tb.textContent), 'a title with an amount: the offer to take it over');
  click(w, tb);
  check(await until(async () => { const t = (await tasks()).find(x => x.id === BUTTER); return t?.title === 'Butter' && t.fam?.qty === 2; }), 'taken over: Butter, 2');

  // ================= #2132 recipe: servings, ingredients choice, plan on a day
  w.eval(`openDetail(${RID})`);
  await until(() => d.querySelector('#d-fserves'));
  check(d.querySelector('#d-fserves').value === '4' && d.querySelector('#detail [data-act="fam-ingr"]') && d.querySelector('#detail [data-act="fam-plan"]'), 'a recipe: servings, to the shopping list, plan on a day');
  click(w, d.querySelector('#detail [data-act="fam-ingr"]'));
  md = await until(() => [...d.querySelectorAll('.modal')].pop()?.querySelector('.fingr li') && [...d.querySelectorAll('.modal')].pop());
  check(md.querySelectorAll('.fingr li').length === 3 && /500 g/.test(md.querySelector('.fingr li .fiq').textContent), 'the choice: three ingredients, no method steps');
  change(w, md.querySelector('#fi-sv'), '2');
  check(await until(() => /250 g/.test(md.querySelector('.fingr li .fiq')?.textContent || '')), 'two servings: the amounts halved');
  const tom = [...md.querySelectorAll('.fingr input')].find(x => /Tomatoes/.test(x.closest('label').textContent));
  tom.checked = false; tom.dispatchEvent(new w.Event('change', {bubbles: true}));
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => { const ts = (await tasks()).filter(t => t.list_id === SH && t.status === 0); return ts.some(t => t.title === 'Mince' && t.fam?.qty === 250) && ts.some(t => t.title === 'Onions' && t.fam?.qty === 1) && !ts.some(t => t.title === 'Tomatoes'); }), 'onto the list: scaled, the unticked one left out');
  click(w, d.querySelector('#detail [data-act="fam-plan"]'));
  md = await until(() => [...d.querySelectorAll('.modal')].pop()?.querySelector('#fp-day') && [...d.querySelectorAll('.modal')].pop());
  w.eval('typeof dpClose === "function" && dpClose(true)');
  w.eval(`dpSet(document.getElementById('fp-day'), '${day(30)}')`);
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await tasks()).some(t => t.due === day(30) && t.fam?.kind === 'meal' && t.fam.recipe === RID && t.title === 'Lasagne')), 'planned 30 days ahead, pointing to the recipe');
  w.close();

  // ================= #2132 the meal plan
  w = await boot({user: 'alice', hash: 'family'}); d = w.document;
  const pick = await until(() => d.querySelector('#view [data-act="fam-weekpick"]'));
  check(pick && / – /.test(pick.textContent) && !d.querySelector('#view [data-act="fam-weeknow"]'), 'the range on its button, no "Today" this week');
  check(d.querySelector('#view .fc-meals [data-act="fam-recipes"]'), 'the Recipes button in the card');
  const nx = d.querySelector('#view [data-act="fam-week"][data-d="7"]'); nx.focus(); click(w, nx); await sleep(150);
  check(d.activeElement?.dataset.act === 'fam-week' && d.activeElement.dataset.d === '7', 'next week: the focus stays on its button: ' + (d.activeElement?.outerHTML || '').slice(0, 120) + ' week ' + w.eval('S.famWeek'));
  const now = await until(() => d.querySelector('#view [data-act="fam-weeknow"]'));
  check(now, 'next week: "Today" brings it back');
  click(w, now);
  check(await until(() => !d.querySelector('#view [data-act="fam-weeknow"]') && w.eval('S.famWeek') === null), 'back to today');
  click(w, d.querySelector(`#view [data-act="fam-meal"][data-day="${day(0)}"]`));
  md = await until(() => [...d.querySelectorAll('.modal')].pop()?.querySelector('.fmrecipes [data-rid]') && [...d.querySelectorAll('.modal')].pop());
  check(md && md.querySelector(`.fmrecipes [data-rid="${RID}"]`), 'the "+" of a day offers the recipes');
  click(w, md.querySelector(`.fmrecipes [data-rid="${RID}"]`));
  check(await until(async () => (await tasks()).some(t => t.due === day(0) && t.fam?.recipe === RID && t.fam.serves === 4)), 'the recipe on today, for four');
  w.close();

  console.log(`p2140_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
