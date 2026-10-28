/* Kalmido web client: The module "Family".
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.19.0 (#653): the module "Family"
// A module like Habits (Settings > Modules > Family, off by default; the setup question "What do you use Kalmido for?"
// turns it on for "Family"). Off = no trace: no view, no list kinds, no task-panel section. Made of ordinary tasks and
// lists (see the server's section): birthdays / anniversaries (yearly tasks, the age, gift ideas = subtasks, import from
// CardDAV contacts), household rotation (tasks.rotation), kid accounts (simple view, stars, rewards), who comes along
// (task people), shopping lists (areas = sections, shopping mode), household deadlines, meal plan, packing templates.
const famOn = () => feat('family');
const kidMe = () => !!S.me?.kid;
S.kids = []; S.famWeek = null; S.shop = null;
const FAM_KINDS = [['', N_('An ordinary project')], ['shopping', N_('Shopping list')], ['meals', N_('Meal plan')], ['birthdays', N_('Birthdays')],
  ['household', N_('Household')], ['packing', N_('Packing list')], ['family', N_('Family')], ['recipes', N_('Recipes')]];  // 2.46.1 (#1615): "family"; 2.140.0 A (#2132): "recipes"
const FAM_KIND_ICON = {shopping: 'cart', meals: 'meal', birthdays: 'cake', household: 'home', packing: 'bag', recipes: 'book'};
const famKindOf = lid => listById(lid)?.family || '';
const isOcc = t => !!t?.fam && (t.fam.kind === 'birthday' || t.fam.kind === 'anniversary');
const isDl = t => t?.fam?.kind === 'deadline';
// 2.46.1 (#1615): a meal = a task marked as one (fam.kind meal, any list) or a task of an old Meal plan list
const pm_isMeal = t => t?.fam?.kind === 'meal' || famKindOf(t?.list_id) === 'meals';
const occAge = t => isOcc(t) && t.fam.year && t.due ? +t.due.slice(0, 4) - t.fam.year : null;
// "turns 80" / "25 years" (the anniversary), '' without a year
function occWhat(t) {
  const a = occAge(t); if (a == null || a < 0) return '';
  return t.fam.kind === 'birthday' ? tr('turns {0}', a) : trn('{0} year', '{0} years', a);
}
const DL_TYPES = [['passport', N_('Passport'), 'key'], ['id_card', N_('ID card'), 'user'], ['car', N_('Car inspection'), 'pulse'],
  ['insurance', N_('Insurance'), 'lock'], ['contract', N_('Contract'), 'file'], ['other', N_('Other deadline'), 'hourglass']];
const dlName = k => tr((DL_TYPES.find(x => x[0] === k) || DL_TYPES[5])[1]);
const daysTo = d => Math.round((pd(d) - pd(today())) / 864e5);
function daysWord(n) { return n === 0 ? tr('today') : n === 1 ? tr('tomorrow') : n < 0 ? trn('{0} day ago', '{0} days ago', -n) : trn('in {0} day', 'in {0} days', n); }

// ---- what the Family view shows (the same rules as GET /api/family on the server)
// the whole turn order from whoever is on now: "Alice → Bob → Lina"
function rotOrder(t) { const r = t.rotation, n = r.who.length, i = (r.i || 0) % n; return r.who.map((_, j) => personName(t.list_id, r.who[(i + j) % n]) || '?').join(' → '); }
function famData() {
  const open = [...S.tasks.values()].filter(t => t.status === 0 && !t.deleted_at && !t.context);
  const occ = open.filter(t => isOcc(t) && t.due).sort((a, b) => a.due.localeCompare(b.due) || a.title.localeCompare(b.title));
  const dls = open.filter(t => isDl(t) && t.due).sort((a, b) => a.due.localeCompare(b.due));
  const rots = open.filter(t => t.rotation?.who?.length > 1);
  const mon = S.famWeek || today(), sun = addDays(mon, 6);  // 2.19.0: the next seven days from today (a Sunday showed only the past week)
  const mealLists = S.lists.filter(l => l.family === 'meals' && !l.archived);
  const meals = [...S.tasks.values()].filter(t => !t.deleted_at && !t.parent_id && t.due && t.due >= mon && t.due <= sun && pm_isMeal(t) && !listById(t.list_id)?.archived);
  const shops = S.lists.filter(l => l.family === 'shopping' && !l.archived);
  return {occ, dls, rots, mon, meals, mealLists, shops, kids: S.kids || []};
}
const shopOpen = lid => [...S.tasks.values()].filter(t => t.list_id === lid && t.status === 0 && !t.deleted_at && !t.parent_id).length;

// ---- 2.140.0 A (#2131): amount + price of a shopping item (tasks.fam {kind: shop, qty?, unit?, price?}; the title stays the name)
const isShopItem = t => !!t && !t.parent_id && (t.fam?.kind === 'shop' || (famKindOf(t.list_id) === 'shopping' && !t.fam));
const shopQty = t => t?.fam?.kind === 'shop' && t.fam.qty != null ? fmtNum(t.fam.qty, 3) + (t.fam.unit ? ' ' + t.fam.unit : '') : (t?.fam?.kind === 'shop' && t.fam.unit ? t.fam.unit : '');
const famRowQty = t => famOn() && isShopItem(t) && shopQty(t) ? `<span class="qtym" title="${esc(tr('Quantity'))}">${esc(shopQty(t))}</span>` : '';
// the same rules as the server's shop_split: a clear leading amount ("2 Milch", "500 g Mehl", "2x Eier"); else none
const SHOP_UNITS = 'x|×|kg|g|gr|mg|l|ml|cl|dl|liter|litre|liters|litres|stk|st|stück|pck|pack|packs|packung|packungen|dose|dosen|can|cans|bund|bunch|el|tl|tbsp|tsp|cup|cups|pcs|piece|pieces|becher|glas|gläser|flasche|flaschen|bottle|bottles|scheiben|slice|slices|zehen|clove|cloves|prise|pinch|oz|lb|lbs';
const SHOP_SPLIT = new RegExp(`^\\s*(\\d{1,5}(?:[.,]\\d{1,3})?|\\d{1,3}\\s*/\\s*\\d{1,3}|\\d{0,3}\\s*[½¼¾⅓⅔])\\s*(?:(${SHOP_UNITS})\\.?(?=\\s)|)\\s+(\\S.*)$`, 'iu');
const SHOP_FRAC = {'½': .5, '¼': .25, '¾': .75, '⅓': 1 / 3, '⅔': 2 / 3};
function qtyParse(v) {
  const x = String(v ?? '').trim(); let m;
  if ((m = x.match(/^(\d{1,6})?\s*([½¼¾⅓⅔])$/))) return (+(m[1] || 0)) + SHOP_FRAC[m[2]];
  if ((m = x.match(/^(\d{1,6})\s*\/\s*(\d{1,4})$/))) return +m[2] ? +m[1] / +m[2] : null;
  return /^\d{1,6}([.,]\d{1,3})?$/.test(x) ? +x.replace(',', '.') : null;
}
function shopSplit(title) {
  const s0 = String(title || '').trim(), m = s0.match(SHOP_SPLIT);
  if (!m) return {qty: null, unit: '', name: s0};
  const q = qtyParse(m[1].replace(/\s+/g, '')), name = m[3].trim();
  let unit = m[2] || ''; if (/^(x|×)$/i.test(unit)) unit = '';
  if (q == null || q <= 0 || q > 1e5 || !/\p{L}/u.test(name) || (!unit && q > 99)) return {qty: null, unit: '', name: s0};
  return {qty: Math.round(q * 1000) / 1000, unit, name};
}
const shopKeyC = s => shopSplit(String(s || '').replace(/\s*\([^)]*\)\s*$/, '')).name.replace(/[\s.,;:!?]+/g, ' ').trim().toLowerCase();
// the fam of a shopping item after a change (ch: {qty, unit, price}; null / '' = remove); null = nothing left
function shopFamWith(t, ch) {
  const f = {...(t.fam?.kind === 'shop' ? t.fam : {}), ...ch, kind: 'shop'};
  for (const k of ['qty', 'unit', 'price']) if (f[k] == null || f[k] === '') delete f[k];
  return Object.keys(f).length > 1 ? f : null;
}
const moneyParse = v => { const x = String(v ?? '').trim().replace(/\s|€/g, '').replace(',', '.'); return x === '' ? null : /^\d{1,7}(\.\d{1,2})?$/.test(x) ? +x : NaN; };

// ---- 2.140.0 A (#2132): recipes = tasks of a list of family "recipes" (or fam kind recipe); a meal may point to one
const isRecipe = t => !!t && !t.parent_id && t.fam?.kind !== 'meal' && (t.fam?.kind === 'recipe' || famKindOf(t.list_id) === 'recipes');
const famRecipes = () => [...S.tasks.values()].filter(t => isRecipe(t) && t.status === 0 && !t.deleted_at && !t.context && !listById(t.list_id)?.archived)
  .sort((a, b) => a.title.localeCompare(b.title));

function viewFamily() {
  if (kidMe()) return viewKid();
  const d = famData(), t0 = today();
  const card = (k, icon, title, body, more = '', n = '') => `<section class="dcard fcard fc-${k}" aria-labelledby="fh-${k}"><h2 id="fh-${k}">${ic(icon, 's')}<span>${esc(title)}</span>${n !== '' ? `<span class="dcn">${n}</span>` : ''}<span class="spacer"></span>${more}</h2>${body}</section>`;
  const open = id => `href="#t/${id}"`;
  // birthdays + anniversaries: the next 60 days, at least the next three
  const occ = d.occ.filter((t, i) => daysTo(t.due) <= 60 || i < 3).slice(0, 8);
  const occH = occ.length ? `<ul class="flist">${occ.map(t => { const n = daysTo(t.due), w = occWhat(t); return `<li><a ${open(t.id)} class="frow"><span class="fem" aria-hidden="true">${ic(t.fam.kind === 'birthday' ? 'cake' : 'ring')}</span><span class="ft"><b>${esc(t.fam.name || t.title)}</b>${w ? `<span class="muted">${esc(w)}</span>` : ''}</span><span class="fwhen ${n <= 7 ? 'soon' : ''}">${esc(n <= 14 ? daysWord(n) : fmtDateLoc(t.due))}</span></a></li>`; }).join('')}</ul>`
    : `<p class="muted">${tr('No birthdays yet.')}</p>`;
  // whose turn
  const rotH = d.rots.length ? `<ul class="flist">${d.rots.map(t => { const r = t.rotation;
    return `<li><a ${open(t.id)} class="frow">${av(t.assignee_id, personName(t.list_id, t.assignee_id) || '?')}<span class="ft"><b>${esc(t.title)}</b><span class="muted">${esc(rotOrder(t))} · ${esc(r.mode === 'week' ? tr('weekly') : tr('after each time'))}</span></span>${t.due ? `<span class="fwhen ${t.due < t0 ? 'over' : ''}">${esc(dayLabel(t.due))}</span>` : ''}</a></li>`; }).join('')}</ul>`
    : `<p class="muted">${tr('Nobody takes turns yet: open a repeating task in a shared project and choose “Take turns”.')}</p>`;
  // meal plan of the week
  const days = [...Array(7)].map((_, i) => addDays(d.mon, i));
  const mealH = `<div class="fweek" role="group" aria-label="${esc(tr('Meal plan'))}">${days.map(day => { const ms = d.meals.filter(t => t.due === day);
    return `<div class="fday ${day === t0 ? 'today' : ''}"><span class="fdl">${esc(dayLabel(day))}</span><span class="fdm">${ms.map(t => `<span class="fmeal ${t.status ? 'done' : ''}"><a ${open(t.id)}>${esc(t.title)}</a><button type="button" class="iconbtn" data-act="fam-ingr" data-id="${t.id}" title="${esc(tr('Ingredients to the shopping list'))}" aria-label="${esc(tr('Ingredients of {0} to the shopping list', t.title))}">${ic('cart', 's')}</button></span>`).join('')}</span><button type="button" class="iconbtn" data-act="fam-meal" data-day="${day}" title="${esc(tr('Add a meal'))}" aria-label="${esc(tr('Add a meal on {0}', fmtDateLoc(day)))}">${ic('plus', 's')}</button></div>`; }).join('')}</div>`;
  // 2.140.0 A (#2132): any week: back / ahead, a day to start from, back to today; the range is said
  const away = !!S.famWeek && S.famWeek !== t0;
  const weekNav = `<span class="fwnav"><button type="button" class="iconbtn" data-act="fam-week" data-d="-7" aria-label="${esc(tr('Previous week'))}" title="${esc(tr('Previous week'))}">${ic('left', 's')}</button><button type="button" class="btn sm fwpick" data-act="fam-weekpick" aria-label="${esc(tr('Show the meal plan from') + ': ' + fmtDateLoc(d.mon) + ' – ' + fmtDateLoc(addDays(d.mon, 6)))}" title="${esc(tr('Choose a day'))}">${ic('cal', 's')}<span>${esc(fmtDateLoc(d.mon))} – ${esc(fmtDateLoc(addDays(d.mon, 6)))}</span></button><button type="button" class="iconbtn" data-act="fam-week" data-d="7" aria-label="${esc(tr('Next week'))}" title="${esc(tr('Next week'))}">${ic('right', 's')}</button>${away ? `<button type="button" class="btn sm" data-act="fam-weeknow">${tr('Today')}</button>` : ''}</span>`;  // "Today" last: the buttons before it keep their place (the focus)
  const mealFoot = `<div class="fcfoot"><button type="button" class="btn sm" data-act="fam-recipes">${ic('book', 's')}<span>${tr('Recipes')}</span>${famRecipes().length ? `<span class="c">${famRecipes().length}</span>` : ''}</button></div>`;
  // shopping
  const shopH = d.shops.length ? `<ul class="flist">${d.shops.map(l => `<li class="frow fshop"><a href="#l/${l.id}" class="ft"><b>${esc(lname(l))}</b><span class="muted">${esc(trn('{0} item left', '{0} items left', shopOpen(l.id)))}</span></a><button type="button" class="btn pri" data-act="fam-shop" data-id="${l.id}">${ic('cart', 's')}<span>${tr('Shopping mode')}</span></button></li>`).join('')}</ul>`
    : `<p class="muted">${tr('No shopping list yet.')}</p><button type="button" class="btn" data-act="fam-newlist" data-k="shopping">${ic('plus', 's')} ${tr('Shopping list')}</button>`;
  // deadlines: what is due in the next half year, and what is overdue
  const dls = d.dls.filter(t => daysTo(t.due) <= 183).slice(0, 8);
  const dlH = dls.length ? `<ul class="flist">${dls.map(t => { const n = daysTo(t.due); return `<li><a ${open(t.id)} class="frow">${ic((DL_TYPES.find(x => x[0] === t.fam.type) || DL_TYPES[5])[2], 's')}<span class="ft"><b>${esc(t.title)}</b><span class="muted">${esc(dlName(t.fam.type))}${t.fam.expires ? ' · ' + esc(tr('expires {0}', fmtDateLoc(t.fam.expires))) : ''}</span></span><span class="fwhen ${n < 0 ? 'over' : n <= 30 ? 'soon' : ''}">${esc(daysWord(n))}</span></a></li>`; }).join('')}</ul>`
    : `<p class="muted">${d.dls.length ? tr('Nothing due in the next six months.') : tr('Passport, car inspection, insurance: add a deadline and get reminded in time.')}</p>`;
  // kids
  const kidsH = d.kids.length ? d.kids.map(k => kidCardHtml(k)).join('') : '';
  const packH = `<div class="fpack">${PACK_UI.map(([k, n, e]) => `<button type="button" class="btn" data-act="fam-pack" data-k="${k}">${ic(e, 's')} ${tr(n)}</button>`).join('')}</div>`;
  return `<div class="dash fam"><div class="dashhead fhead"><span class="spacer"></span>
    <button type="button" class="btn sm" data-act="fam-occ">${ic('cake', 's')}<span>${tr('Birthday')}</span></button>
    <button type="button" class="btn sm" data-act="fam-dl">${ic('hourglass', 's')}<span>${tr('Household deadline')}</span></button>${lyCustomBtn('family')}</div>
    ${lyHtml('family', {  // 2.55.0 (#1067): the cards are blocks of the view builder (same order and width as before)
      occ: card('occ', 'cake', tr('Birthdays & anniversaries'), occH + `<div class="fcfoot"><button type="button" class="btn sm" data-act="fam-contacts">${ic('users', 's')}<span>${tr('From contacts…')}</span></button></div>`, '', d.occ.filter(t => daysTo(t.due) <= 30).length || ''),
      rot: card('rot', 'turns', tr('Whose turn'), rotH, '', d.rots.length || ''),
      meals: card('meals', 'meal', tr('Meal plan'), mealH + mealFoot, weekNav),
      shop: card('shop', 'cart', tr('Shopping'), shopH),
      dl: card('dl', 'hourglass', tr('Deadlines'), dlH, '', d.dls.filter(t => daysTo(t.due) <= 30).length || ''),
      kids: kidsH ? card('kids', 'star', tr('Kids'), kidsH) : '',
      pack: card('pack', 'bag', tr('Packing lists'), packH),
    })}</div>`;
}
const PACK_UI = [['holiday', N_('Holiday'), 'beach'], ['pool', N_('Swimming pool'), 'wave'], ['daycare', N_('Daycare'), 'bag'], ['camping', N_('Camping'), 'tent'], ['business', N_('Business trip'), 'brief']];  // 2.223.0 C (#2820): app icons, not emoji

// ---- kids: a parent's card (stars, requests, give stars, rewards) and the kid's own view
function kidCardHtml(k) {
  const req = (k.rewards || []).filter(r => r.state === 'requested');
  return `<div class="kidc" data-kid="${k.id}"><div class="kidh">${av(k.id, k.display_name)}<b>${esc(k.display_name)}</b><span class="kstars" aria-label="${esc(trn('{0} star', '{0} stars', k.stars))}"><span aria-hidden="true">★</span> ${k.stars}</span><span class="spacer"></span>
    <button type="button" class="btn sm" data-act="fam-give" data-kid="${k.id}">${ic('plus', 's')}<span>${tr('Stars')}</span></button><button type="button" class="btn sm" data-act="fam-rewards" data-kid="${k.id}">${ic('gift', 's')}<span>${tr('Rewards')}</span></button><button type="button" class="btn sm" data-act="fam-pin" data-kid="${k.id}" aria-label="${esc(tr('Parent PIN for {0}', k.display_name))}">${ic('lock', 's')}<span>${k.pin ? tr('PIN on') : tr('PIN')}</span></button></div>
    ${req.map(r => `<div class="kreq"><span class="kreqt">${esc(tr('{0} would like: {1}', k.display_name, (r.emoji ? r.emoji + ' ' : '') + r.title))} · ${r.cost} ★</span><span class="kreqb"><button type="button" class="btn sm" data-act="fam-decide" data-rid="${r.id}" data-ok="0">${tr('Not now')}</button><button type="button" class="btn sm pri" data-act="fam-decide" data-rid="${r.id}" data-ok="1">${ic('check', 's')}<span>${tr('Approve')}</span></button></span></div>`).join('')}</div>`;
}
// the kid's view: big buttons, only its own tasks (the server sends no others), its stars and the rewards
function viewKid() {
  const k = (S.kids || [])[0] || {stars: 0, rewards: []};
  const mine = [...S.tasks.values()].filter(t => !t.deleted_at && !t.parent_id && !t.context && (t.status === 0 || (t.completed_at && Date.now() - Date.parse(t.completed_at) < 864e5)))
    .sort((a, b) => a.status - b.status || (a.due || '9999').localeCompare(b.due || '9999') || a.id - b.id);
  const todo = mine.filter(t => t.status === 0);
  const hi = new Date().getHours();
  // 2.49.0 (#1537, owner decision 15.10.): the kid's own tasks first, then one section per list shared with it (its name
  // as the heading; an empty one says so)
  const shared = kd_sharedLists(), sid = new Set(shared.map(l => l.id)), own = mine.filter(t => !sid.has(t.list_id));
  const ul = ts => `<ul class="kidtasks">${ts.map(t => `<li class="${t.status ? 'done' : ''}"><button type="button" class="kidchk" data-act="kid-tick" data-id="${t.id}" role="checkbox" aria-checked="${t.status === 2}" aria-label="${esc(tr('Done: {0}', t.title))}">${t.status ? ic('check') : ''}</button>
      <span class="kidt"><b>${esc(t.title)}</b>${t.due ? `<span class="muted">${esc(dayLabel(t.due))}${t.due_time ? ' ' + esc(fmtTimeLoc(t.due_time)) : ''}</span>` : ''}</span><span class="kidst" aria-label="${esc(trn('{0} star', '{0} stars', t.stars ?? 1))}">${'★'.repeat(Math.min(5, t.stars ?? 1))}</span></li>`).join('')}</ul>`;
  return `<div class="kidv"><div class="kidtop"><h2>${esc(hi < 11 ? tr('Good morning, {0}', S.me.display_name) : hi < 18 ? tr('Hello, {0}', S.me.display_name) : tr('Good evening, {0}', S.me.display_name))}</h2>
    <div class="kidbal" role="status" aria-label="${esc(trn('You have {0} star', 'You have {0} stars', k.stars))}"><span aria-hidden="true">★</span><b>${k.stars}</b></div></div>
    <h3 class="kidsec">${tr('My tasks')}</h3>
    ${own.length ? ul(own) : mine.length || shared.length ? `<p class="muted kd_empty">${tr('Nothing to do right now.')}</p>` : botEmpty('erledigt', tr('Nothing to do right now.'), '')}
    ${shared.map(l => { const ts = mine.filter(t => t.list_id === l.id);
      return `<section class="kd_list" data-kd-list="${l.id}"><h3 class="kidsec">${esc(lname(l))}</h3>${ts.length ? ul(ts) : `<p class="muted kd_empty">${tr('Nothing here for you right now.')}</p>`}</section>`; }).join('')}
    ${todo.length || !mine.length ? '' : `<p class="kidyay">${tr('All done. Great job!')}</p>`}
    <h3 class="kidsec">${tr('Rewards')}</h3>
    ${(k.rewards || []).length ? `<ul class="kidrw">${k.rewards.map(r => `<li><span class="kre" aria-hidden="true">${r.emoji ? esc(r.emoji) : ic('gift')}</span><span class="kidt"><b>${esc(r.title)}</b><span class="muted">${r.cost} ★</span></span>${r.state === 'requested' ? `<span class="kwait">${tr('Asked – waiting')}</span>` : r.state === 'redeemed' ? `<span class="muted">${tr('Redeemed')}</span>` : k.stars < r.cost ? `<span class="kneed">${esc(trn('{0} more star', '{0} more stars', r.cost - k.stars))}</span>` : `<button type="button" class="btn pri kidbtn" data-act="kid-want" data-rid="${r.id}">${tr('I want this')}</button>`}</li>`).join('')}</ul>`
      : `<p class="muted">${tr('No rewards yet: ask your parents.')}</p>`}</div>`;
}
// 2.49.0 (#1537): the lists others shared with the kid (not its own Basket / lists), by name
const kd_sharedLists = () => S.lists.filter(l => !l.archived && !l.is_inbox && !l.context && l.owner_id !== S.me?.id).sort((a, b) => lname(a).localeCompare(lname(b)));

// ---- dialogs
function occModal(o = {}) {
  const lists = S.lists.filter(l => !l.archived && canEditList(l.id) && !l.is_inbox);
  const bl = lists.find(l => l.family === 'birthdays') || lists.find(l => l.family === 'family');  // 2.46.1 (#1615): or the list "Family"
  const months = [...Array(12)].map((_, i) => MON[i]);
  const md = modal(`<h3>${ic('cake', 's')} ${tr('Birthday or anniversary')}</h3>
    <div class="seg" id="oc-kind" role="radiogroup" aria-label="${esc(tr('Kind'))}"><button type="button" role="radio" aria-checked="true" class="on" data-k="birthday">${tr('Birthday')}</button><button type="button" role="radio" aria-checked="false" data-k="anniversary">${tr('Anniversary')}</button></div>
    <div class="row"><label for="oc-name">${tr('Who')}</label><input id="oc-name" maxlength="100" autocomplete="off" placeholder="${esc(tr('e.g. Grandma Erika'))}"></div>
    <div class="row"><label for="oc-day">${tr('Date')}</label><span class="ocdate"><input id="oc-day" type="number" inputmode="numeric" min="1" max="31" placeholder="${esc(tr('Day'))}" aria-label="${esc(tr('Day'))}"><select id="oc-month" aria-label="${esc(tr('Month'))}">${months.map((m, i) => `<option value="${i + 1}" ${i === new Date().getMonth() ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select><input id="oc-year" type="number" inputmode="numeric" min="1900" max="${new Date().getFullYear()}" placeholder="${esc(tr('Year'))}" aria-label="${esc(tr('Year (optional)'))}"></span></div>
    <div class="row"><label for="oc-lead">${tr('Remind me')}</label><select id="oc-lead">${[0, 1, 3, 7, 14, 30].map(n => `<option value="${n}" ${n === 7 ? 'selected' : ''}>${n ? trn('{0} day before', '{0} days before', n) : tr('on the day')}</option>`).join('')}</select></div>
    <div class="row"><label for="oc-gifts">${tr('Gift ideas')}</label><input id="oc-gifts" placeholder="${esc(tr('optional, separated by commas'))}"></div>
    ${lists.length > 1 || !bl ? `<div class="row"><label for="oc-list">${tr('Project')}</label><select id="oc-list">${bl ? '' : `<option value="">${tr('New project: Family')}</option>`}${lists.map(l => `<option value="${l.id}" ${l === bl ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>` : ''}
    <div class="aerr" role="alert" id="oc-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Add')}</button></div>`);
  md.classList.add('famdlg');
  let kind = 'birthday';
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.k) { kind = b.dataset.k; $$('#oc-kind button', md).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); }); return; }
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'save') return;
    const name = $('#oc-name', md).value.trim(), dy = +$('#oc-day', md).value, mo = +$('#oc-month', md).value, y = $('#oc-year', md).value.trim();
    const errEl = $('#oc-err', md);
    if (!name) { errEl.textContent = tr('Please enter a name'); $('#oc-name', md).focus(); return; }
    if (!(dy >= 1 && dy <= new Date(2000, mo, 0).getDate())) { errEl.textContent = tr('Please enter the day'); $('#oc-day', md).focus(); return; }  // 29 Feb is fine
    const body = {name, kind, date: `--${String(mo).padStart(2, '0')}-${String(dy).padStart(2, '0')}`, lead_days: +$('#oc-lead', md).value,
      gifts: $('#oc-gifts', md).value.split(',').map(x => x.trim()).filter(Boolean), ...(y ? {year: +y} : {}), ...($('#oc-list', md)?.value ? {list_id: +$('#oc-list', md).value} : {})};
    // rawFetch: the error shows in the dialog, not also as a toast
    try { const t = await rawFetch('POST', '/api/family/occasions', body); md.remove(); await load(); render(); toast(tr('Added: {0}', t.title), () => openDetail(t.id), 6000, tr('Open')); }
    catch (er) { errEl.textContent = er.message || ''; }
  });
  setTimeout(() => { $('#oc-name', md)?.focus(); if (o.name) $('#oc-name', md).value = o.name; }, 30);
}
function dlModal() {
  const lists = S.lists.filter(l => !l.archived && canEditList(l.id) && !l.is_inbox);
  const hl = lists.find(l => l.family === 'household') || lists.find(l => l.family === 'family');  // 2.46.1 (#1615)
  const md = modal(`<h3>${ic('hourglass', 's')} ${tr('Household deadline')}</h3>
    <div class="ptcards dltypes" role="radiogroup" aria-label="${esc(tr('Kind'))}">${DL_TYPES.map(([k, n, i], j) => `<button type="button" class="ptcard ${j ? '' : 'on'}" role="radio" aria-checked="${!j}" data-dl="${k}">${ic(i, 's')}<b>${tr(n)}</b></button>`).join('')}</div>
    <div class="row"><label for="dl-who" id="dl-wholab">${tr('For whom / what')}</label><input id="dl-who" maxlength="100" autocomplete="off" placeholder="${esc(tr('e.g. Lina, the family car, household insurance'))}"></div>
    <div class="row"><label id="dl-explab">${tr('Expires on')}</label>${dateIn('dl-exp', '', {label: tr('Expires on'), empty: tr('choose')})}</div>
    <div class="row dlnotice" hidden><label for="dl-notice">${tr('Notice period')}</label><select id="dl-notice">${[0, 1, 2, 3, 6, 12].map(n => `<option value="${n}">${n ? trn('{0} month', '{0} months', n) : tr('none')}</option>`).join('')}</select></div>
    <div class="shint lhint" id="dl-hint"></div>
    ${lists.length > 1 || !hl ? `<div class="row"><label for="dl-list">${tr('Project')}</label><select id="dl-list">${hl ? '' : `<option value="">${tr('New project: Family')}</option>`}${lists.map(l => `<option value="${l.id}" ${l === hl ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>` : ''}
    <div class="aerr" role="alert" id="dl-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Add')}</button></div>`);
  md.classList.add('famdlg');
  let type = 'passport';
  const NOTICE = {insurance: 3, contract: 1};
  const hint = () => {
    $('.dlnotice', md).hidden = !(type in NOTICE);
    const lead = {passport: 90, id_card: 60, car: 30, insurance: 21, contract: 14, other: 14}[type];
    $('#dl-hint', md).textContent = [type in NOTICE ? tr('Due on the last day to cancel (the end minus the notice period).') : '', type === 'car' ? tr('Repeats every two years.') : type in NOTICE ? tr('Repeats every year.') : '',
      trn('Reminder {0} day before and on the day.', 'Reminder {0} days before and on the day.', lead)].filter(Boolean).join(' ');
    $('#dl-explab', md).textContent = type in NOTICE ? tr('Ends on') : tr('Expires on');
  };
  hint();
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.dl) { type = b.dataset.dl; $$('[data-dl]', md).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); }); if (type in NOTICE) $('#dl-notice', md).value = String(NOTICE[type]); hint(); return; }
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'save') return;
    const exp = $('#dl-exp', md).value, who = $('#dl-who', md).value.trim(), errEl = $('#dl-err', md);
    if (!exp) { errEl.textContent = tr('Please enter the date'); return; }
    if (type === 'other' && !who) { errEl.textContent = tr('Please enter a name'); $('#dl-who', md).focus(); return; }
    const body = {type, expires: exp, who, ...(type in NOTICE ? {notice_months: +$('#dl-notice', md).value} : {}), ...($('#dl-list', md)?.value ? {list_id: +$('#dl-list', md).value} : {})};
    try { const t = await rawFetch('POST', '/api/family/deadlines', body); md.remove(); await load(); render(); toast(tr('Added: {0}', t.title), () => openDetail(t.id), 6000, tr('Open')); }
    catch (er) { errEl.textContent = er.message || ''; }
  });
  setTimeout(() => $('[data-dl="passport"]', md)?.focus(), 30);
}
async function famPack(k) {
  const pk = PACK_UI.find(x => x[0] === k);
  try { const j = await api('POST', '/api/family/packing', {template: k}); await load(); go('l/' + j.list_id); toast(tr('Packing list created: {0}', tr(pk[1]))); } catch { /* api() said it */ }
}
async function famNewList(kind) {
  try { const l = await api('POST', '/api/lists', {name: tr(FAM_KINDS.find(x => x[0] === kind)[1]), family: kind}); await load(); return l.id; } catch { return null; }
}
// 2.46.1 (#1615): the list "Family" (created when missing) and its section `key` (server: FAM_SECTIONS) -> {list_id, section_id}
const PM_FAM_SECS = {household: N_('Household'), birthdays: N_('Birthdays'), meals: N_('Meal plan'), deadlines: N_('Deadlines')};
async function pm_famTarget(key) {
  let l = S.lists.find(x => x.family === 'family' && !x.archived && canAddTo(x.id));
  const lid = l ? l.id : await famNewList('family'); if (!lid) return null;
  const nm = [tr(PM_FAM_SECS[key]), PM_FAM_SECS[key]].map(x => x.toLowerCase());
  let s = S.sections.find(x => x.list_id === lid && nm.includes(x.name.trim().toLowerCase()));
  if (!s) { try { s = await api('POST', '/api/sections', {list_id: lid, name: tr(PM_FAM_SECS[key])}); await load(); } catch { s = null; } }
  return {list_id: lid, section_id: s?.id || null};
}
// 2.140.0 A (#2132): a meal = a name or a recipe of the collection (the meal points to it); any day, also weeks ahead
async function famMealAdd(day, name, recipe) {
  // 2.46.1 (#1615): an old Meal plan list first, else the list "Family" (section Meal plan), marked as a meal
  let lid = famData().mealLists.find(l => canAddTo(l.id))?.id, sec = {};
  const fam = recipe ? {kind: 'meal', recipe: recipe.id, ...(recipe.fam?.serves ? {serves: recipe.fam.serves} : {})} : null;
  if (!lid) { const x = await pm_famTarget('meals'); if (!x) return null; lid = x.list_id; sec = {section_id: x.section_id, fam: fam || {kind: 'meal'}}; }
  else if (fam) sec = {fam};
  return createTask({title: (recipe ? recipe.title : name).trim().slice(0, 300), list_id: lid, due: day, ...sec}).catch(() => null);
}
async function famMeal(day) {
  const rs = famRecipes();
  if (!rs.length) {
    const name = await askPrompt(tr('What is on {0}?', fmtDateLoc(day)), '', {ok: tr('Add'), input: {placeholder: tr('e.g. Lasagne'), max: 300}});
    if (!name || !name.trim()) return;
    const t = await famMealAdd(day, name);
    if (t) toast(tr('Added: {0}', t.title), () => openDetail(t.id), 6000, tr('Ingredients…'));
    return;
  }
  const md = modal(`<h3>${ic('meal', 's')} ${esc(tr('What is on {0}?', fmtDateLoc(day)))}</h3>
    <div class="row"><input id="fm-name" maxlength="300" autocomplete="off" placeholder="${esc(tr('e.g. Lasagne'))}" aria-label="${esc(tr('Meal'))}"></div>
    <h4 class="fmrh">${tr('From your recipes')}</h4><div class="fmrecipes" role="group" aria-label="${esc(tr('Recipes'))}"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Add')}</button></div>`);
  md.classList.add('famdlg');
  const draw = () => { const q = $('#fm-name', md).value.trim().toLowerCase(), hit = rs.filter(r => !q || r.title.toLowerCase().includes(q)).slice(0, 30);
    $('.fmrecipes', md).innerHTML = hit.map(r => `<button type="button" class="btn sm" data-rid="${r.id}">${ic('book', 's')}<span>${esc(r.title)}</span></button>`).join('') || `<p class="muted">${tr('No recipe of that name.')}</p>`; };
  draw();
  $('#fm-name', md).addEventListener('input', draw);
  const done = t => { md.remove(); if (t) toast(tr('Added: {0}', t.title), () => openDetail(t.id), 6000, tr('Open')); };
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.rid) { done(await famMealAdd(day, '', taskById(+b.dataset.rid))); return; }
    if (b.dataset.m !== 'save') return;
    const name = $('#fm-name', md).value.trim(); if (!name) { $('#fm-name', md).focus(); return; }
    const r = rs.find(x => x.title.trim().toLowerCase() === name.toLowerCase());  // the exact name of a recipe = that recipe
    done(await famMealAdd(day, name, r));
  });
  setTimeout(() => $('#fm-name', md)?.focus(), 30);
}
// a recipe onto a day of the meal plan
function famPlan(id) {
  const r = taskById(id); if (!r) return;
  const md = modal(`<h3>${ic('meal', 's')} ${esc(tr('Plan “{0}”', r.title))}</h3>
    <div class="row"><label for="fp-day">${tr('Day')}</label>${dateIn('fp-day', today(), {label: tr('Day'), clear: false})}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Add')}</button></div>`);
  md.classList.add('famdlg');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const day = $('#fp-day', md)?.value; if (!day) return;
    md.remove();
    const t = await famMealAdd(day, '', r);
    if (t) { S.famWeek = day; toast(tr('Planned on {0}', fmtDateLoc(day)), () => go('family'), 6000, tr('Meal plan')); }
  });
}
// the meal plan from any day on (the seven days from there)
function famWeekPick() {
  const md = modal(`<h3>${ic('cal', 's')} ${tr('Show the meal plan from')}</h3>
    <div class="row">${dateIn('fw-day', S.famWeek || today(), {label: tr('Day'), clear: false})}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Show')}</button></div>`);
  md.classList.add('famdlg');
  md.addEventListener('click', e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    const d = $('#fw-day', md)?.value; md.remove();
    if (b.dataset.m === 'save' && d) { S.famWeek = d === today() ? null : d; renderView(); $('#view [data-act="fam-weekpick"]')?.focus(); }
  });
}
// the list of recipes (created when missing)
async function famRecipesOpen() {
  const l = S.lists.find(x => x.family === 'recipes' && !x.archived);
  const lid = l ? l.id : await famNewList('recipes');
  if (lid) go('l/' + lid);
}
// 2.140.0 A (#2132): the ingredients of a meal / recipe to a shopping list: a short choice first (tick per ingredient,
// untick what is at home), the amounts scaled to the servings, the same item on the list gets the amount added
async function famIngredients(id) {
  const t = taskById(id); if (!t) return;
  const shops = S.lists.filter(l => l.family === 'shopping' && !l.archived && canEditList(l.id));
  let lid = shops.some(l => l.id === S.famShopLid) ? S.famShopLid : shops[0]?.id || null, sv = t.fam?.serves || null, p;
  const prev = () => api('POST', `/api/tasks/${id}/to-shopping`, {preview: true, ...(lid ? {list_id: lid} : {}), ...(sv ? {servings: sv} : {})});
  try { p = await prev(); } catch { return; }
  if (!p.items.length) { toast(tr('No ingredients found: write them as a list in the notes')); return; }
  if (!sv) sv = p.serves;
  const off = new Set();  // names unticked (kept when the servings change)
  const amt = x => x.qty != null ? fmtNum(x.qty, 2) + (x.unit ? ' ' + x.unit : '') : x.unit || '';
  const md = modal(`<h3>${ic('cart', 's')} ${esc(tr('Ingredients of {0}', t.title))}</h3>
    ${p.serves ? `<div class="row"><label for="fi-sv">${tr('Servings')}</label><input id="fi-sv" class="numin" type="number" inputmode="numeric" min="1" max="100" value="${esc(sv || '')}"></div>` : ''}
    ${shops.length > 1 ? `<div class="row"><label for="fi-list">${tr('Shopping list')}</label><select id="fi-list">${shops.map(l => `<option value="${l.id}" ${l.id === lid ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>` : ''}
    <p class="muted">${tr('Untick what is at home already.')}</p>
    <ul class="fingr" role="group" aria-label="${esc(tr('Ingredients'))}"></ul>
    <div class="aerr" role="alert" id="fi-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('To the shopping list')}</button></div>`);
  md.classList.add('famdlg');
  const draw = () => { $('.fingr', md).innerHTML = p.items.map((x, i) => `<li><label class="chkl"><input type="checkbox" data-i="${i}" ${off.has(x.name) ? '' : 'checked'}><span class="fiq">${esc(amt(x))}</span><span class="fin">${esc(x.name)}</span>${x.have ? `<small class="muted">${esc(x.qty != null ? tr('on the list, the quantity is added') : tr('on the list'))}</small>` : ''}</label></li>`).join(''); };
  draw();
  const again = async () => { try { p = await prev(); draw(); } catch { /* api() said it */ } };
  md.addEventListener('change', e => {
    if (e.target.dataset.i != null) { const n = p.items[+e.target.dataset.i].name; e.target.checked ? off.delete(n) : off.add(n); }
    if (e.target.id === 'fi-sv') { sv = Math.max(1, Math.min(100, Math.round(+e.target.value) || 1)); again(); }
    if (e.target.id === 'fi-list') { lid = +e.target.value; S.famShopLid = lid; again(); }
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const items = p.items.filter(x => !off.has(x.name)).map(x => ({name: x.name, qty: x.qty, unit: x.unit}));
    if (!items.length) { $('#fi-err', md).textContent = tr('Nothing to add'); return; }
    let j; try { j = await rawFetch('POST', `/api/tasks/${id}/to-shopping`, {items, ...(lid ? {list_id: lid} : {})}); } catch (er) { $('#fi-err', md).textContent = er.message || ''; return; }
    md.remove(); await load(); render();
    const msg = [j.added.length ? trn('{0} item on the shopping list', '{0} items on the shopping list', j.added.length) : '', (j.merged || []).length ? trn('{0} quantity added', '{0} quantities added', j.merged.length) : '', j.skipped.length ? trn('{0} was already there', '{0} were already there', j.skipped.length) : ''].filter(Boolean).join(' · ');
    toast(msg || tr('Nothing to add'), () => go('l/' + j.list_id), 6000, tr('Open'));
  });
}
// 2.140.0 A (#2131): amount and price of an item, from shopping mode (a tap on the amount)
function shopQtyEdit(id) {
  const t = taskById(id); if (!t) return;
  const f = t.fam?.kind === 'shop' ? t.fam : {};
  const md = modal(`<h3>${esc(t.title)}</h3>
    <div class="row"><label for="sq-qty">${tr('Quantity')}</label><span class="lcost"><input id="sq-qty" class="numin" inputmode="decimal" autocomplete="off" value="${f.qty != null ? esc(fmtNum(f.qty, 3)) : ''}" placeholder="1"><input id="sq-unit" class="numin" autocomplete="off" maxlength="16" value="${esc(f.unit || '')}" placeholder="${esc(tr('Unit'))}" aria-label="${esc(tr('Unit'))}"></span></div>
    <div class="row"><label for="sq-price">${tr('Price')}</label><input id="sq-price" class="numin" inputmode="decimal" autocomplete="off" value="${f.price != null ? esc(fmtNum(f.price, 2)) : ''}" placeholder="0,00"></div>
    <div class="aerr" role="alert" id="sq-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('famdlg', 'shopqdlg');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const qv = $('#sq-qty', md).value.trim(), q = qv === '' ? null : qtyParse(qv), pr = moneyParse($('#sq-price', md).value);
    if (qv !== '' && (q == null || q > 1e5)) { $('#sq-err', md).textContent = tr('Invalid value: {0}', tr('Quantity')); $('#sq-qty', md).focus(); return; }
    if (Number.isNaN(pr)) { $('#sq-err', md).textContent = tr('Invalid value: {0}', tr('Price')); $('#sq-price', md).focus(); return; }
    const unit = $('#sq-unit', md).value.trim().slice(0, 16);
    md.remove();
    try { await patchTask(id, {fam: shopFamWith(t, {qty: q, unit, price: pr})}, true); } catch { /* queued offline */ }
    shopDraw(); $(`.shopmode [data-act="shop-qty"][data-id="${id}"]`)?.focus({preventScroll: true});
  });
  setTimeout(() => $('#sq-qty', md)?.focus(), 30);
}
async function famGive(kid) {
  const k = (S.kids || []).find(x => x.id === kid); if (!k) return;
  const md = modal(`<h3>${tr('Stars for {0}', esc(k.display_name))}</h3>
    <div class="kgive" role="group" aria-label="${esc(tr('How many'))}">${[1, 2, 3, 5, 10].map(n => `<button type="button" class="btn" data-n="${n}">+${n} ★</button>`).join('')}<button type="button" class="btn" data-n="-1">−1 ★</button></div>
    <div class="row"><label for="kg-note">${tr('What for')}</label><input id="kg-note" maxlength="200" placeholder="${esc(tr('optional, e.g. helped with the dishes'))}"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (!b.dataset.n) return;
    try { const j = await api('POST', `/api/family/kids/${kid}/stars`, {delta: +b.dataset.n, note: $('#kg-note', md).value.trim()}); famKidSet(j); md.remove(); toast(tr('{0} now has {1} ★', k.display_name, j.stars)); } catch { /* api() said it */ }
  });
}
function famKidSet(k) { S.kids = (S.kids || []).map(x => x.id === k.id ? k : x); render(); }
function rewardsModal(kid) {
  let k = (S.kids || []).find(x => x.id === kid); if (!k) return;
  const md = modal(`<h3>${ic('gift', 's')} ${tr('Rewards for {0}', esc(k.display_name))}</h3><div id="rw-list"></div>
    <h4>${tr('New reward')}</h4>
    <div class="row"><label for="rw-title">${tr('Reward')}</label><input id="rw-title" maxlength="200" placeholder="${esc(tr('e.g. 30 minutes of games, a trip to the zoo'))}"></div>
    <div class="row"><label for="rw-cost">${tr('Stars')}</label><input id="rw-cost" type="number" inputmode="numeric" min="1" max="1000" value="10" class="numin"><label class="chkl"><input type="checkbox" id="rw-once"> ${tr('only once')}</label></div>
    <div class="row"><label for="rw-emo">${tr('Picture')}</label><input id="rw-emo" maxlength="8" class="numin" placeholder="🎁"></div>
    <div class="aerr" role="alert" id="rw-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button><button class="btn pri" data-m="add">${ic('plus', 's')} ${tr('Add')}</button></div>`);
  const draw = () => { $('#rw-list', md).innerHTML = (k.rewards || []).length ? `<ul class="flist">${k.rewards.map(r => `<li class="frow"><span class="fem" aria-hidden="true">${r.emoji ? esc(r.emoji) : ic('gift')}</span><span class="ft"><b>${esc(r.title)}</b><span class="muted">${r.cost} ★${r.once ? ' · ' + tr('only once') : ''}${r.state === 'requested' ? ' · ' + tr('asked for') : r.state === 'redeemed' ? ' · ' + tr('redeemed') : ''}</span></span>${r.state === 'redeemed' ? '' : k.stars < r.cost ? `<span class="muted kneed">${esc(trn('{0} more star', '{0} more stars', r.cost - k.stars))}</span>` : `<button type="button" class="btn sm" data-redeem="${r.id}" title="${esc(tr('Redeem now: the stars are taken'))}">${tr('Redeem')}</button>`}<button type="button" class="iconbtn" data-rdel="${r.id}" aria-label="${esc(tr('Delete {0}', r.title))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('No rewards yet.')}</p>`; };
  const reload = j => { if (j) { famKidSet(j); k = j; } draw(); };
  draw();
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    try {
      if (b.dataset.m === 'close') { md.remove(); return; }
      if (b.dataset.m === 'add') {
        const title = $('#rw-title', md).value.trim(); if (!title) { $('#rw-err', md).textContent = tr('Please enter a name'); return; }
        await api('POST', `/api/family/kids/${kid}/rewards`, {title, cost: +$('#rw-cost', md).value || 1, emoji: $('#rw-emo', md).value.trim(), once: $('#rw-once', md).checked});
        $('#rw-title', md).value = ''; $('#rw-err', md).textContent = '';
        reload((await api('GET', '/api/family/kids')).kids.find(x => x.id === kid)); return;
      }
      if (b.dataset.redeem) { reload(await api('POST', `/api/family/rewards/${b.dataset.redeem}/decide`, {approve: true})); toast(tr('Redeemed')); return; }
      if (b.dataset.rdel) { if (!await askConfirm(tr('Delete this reward?'), '', {ok: tr('Delete'), danger: true})) return; await api('DELETE', `/api/family/rewards/${b.dataset.rdel}`); reload((await api('GET', '/api/family/kids')).kids.find(x => x.id === kid)); }
    } catch (er) { $('#rw-err', md).textContent = er.message || ''; }
  });
}
// address books (CardDAV): birthdays + anniversaries of the contacts become yearly tasks
async function contactsModal() {
  const lists = S.lists.filter(l => !l.archived && canEditList(l.id) && !l.is_inbox);
  const bl = lists.find(l => l.family === 'birthdays') || lists.find(l => l.family === 'family');  // 2.46.1 (#1615): or the list "Family"
  const md = modal(`<h3>${ic('users', 's')} ${tr('Birthdays from your contacts')}</h3>
    <p class="muted">${tr('Kalmido reads the birthdays and anniversaries of an address book (CardDAV: Nextcloud, iCloud, Radicale, mailbox.org …) once a day and adds them as yearly tasks. Changed dates go back into an address book only when you switch that on for it. The password is stored encrypted.')}</p>
    <div id="ct-list"><div class="muted">${tr('Loading…')}</div></div>
    <h4>${tr('Add an address book')}</h4>
    <div class="row"><label for="ct-url">${tr('Server address')}</label><input id="ct-url" type="url" inputmode="url" autocapitalize="off" placeholder="https://…"></div>
    <div class="row"><label for="ct-user">${tr('Username')}</label><input id="ct-user" autocapitalize="off" autocomplete="off"></div>
    <div class="row"><label for="ct-pw">${tr('Password')}</label><input id="ct-pw" type="password" autocomplete="new-password" placeholder="${esc(tr('an app password, if the server offers one'))}"></div>
    <div class="row"><label for="ct-list-sel">${tr('Project')}</label><select id="ct-list-sel">${bl ? '' : `<option value="">${tr('New project: Family')}</option>`}${lists.map(l => `<option value="${l.id}" ${l === bl ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>
    <div class="aerr" role="alert" id="ct-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button><button class="btn pri" data-m="add">${ic('plus', 's')} ${tr('Connect')}</button></div>`);
  md.classList.add('famdlg');
  const draw = j => { $('#ct-list', md).innerHTML = j.sources.length ? `<ul class="flist">${j.sources.map(s => `<li class="frow"><span class="ft"><b>${esc(s.name)}</b><span class="muted">${esc(s.url_hint)} · ${s.status === 'error' ? esc(s.error_text) : esc(trn('{0} date', '{0} dates', s.count))}${s.synced_at ? ' · ' + esc(tr('read {0}', fmtAgo(s.synced_at))) : ''}</span>${ctWbHtml(s)}</span><button type="button" class="btn sm" data-ctsync="${s.id}">${ic('sync', 's')}<span>${tr('Read now')}</span></button><button type="button" class="iconbtn" data-ctdel="${s.id}" aria-label="${esc(tr('Remove {0}', s.name))}" title="${esc(tr('Remove'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('No address book connected.')}</p>`; };
  const reload = async () => { try { draw(await api('GET', '/api/family/contacts')); } catch { /* offline */ } };
  reload();
  md.addEventListener('change', async e => {  // 2.140.0 D (#2137): write-back per address book (off by default)
    const el = e.target; if (!el.dataset?.ctwb) return;
    const on = el.checked, errEl = $('#ct-err', md);
    if (on && !await askConfirm(tr('Write dates back?'), tr('When you change the date or the year of a birthday or anniversary from this address book in the family section of its task, Kalmido changes it in the address book too. Only that date is changed, nothing is deleted.'), {ok: tr('Switch on')})) { el.checked = false; return; }
    el.disabled = true;
    try { await api('PATCH', `/api/family/contacts/${el.dataset.ctwb}`, {writeback: on}); errEl.textContent = ''; await reload(); }
    catch (er) { el.checked = !on; el.disabled = false; errEl.textContent = er.message || ''; }
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    const errEl = $('#ct-err', md);
    if (b.dataset.m === 'close') { md.remove(); return; }
    b.disabled = true;
    try {
      if (b.dataset.m === 'add') {
        errEl.textContent = '';
        const body = {url: $('#ct-url', md).value.trim(), username: $('#ct-user', md).value.trim(), password: $('#ct-pw', md).value, ...($('#ct-list-sel', md).value ? {list_id: +$('#ct-list-sel', md).value} : {})};
        const s = await api('POST', '/api/family/contacts', body);
        $('#ct-pw', md).value = ''; toast(trn('{0} date found', '{0} dates found', s.count)); await load(); render();
      }
      if (b.dataset.ctsync) { const s = await api('POST', `/api/family/contacts/${b.dataset.ctsync}/sync`, {}); toast(s.status === 'ok' ? trn('{0} date found', '{0} dates found', s.count) : s.error_text); await load(); render(); }
      if (b.dataset.ctdel) { if (!await askConfirm(tr('Remove this address book?'), tr('The birthdays it added stay as your tasks.'), {ok: tr('Remove'), danger: true})) { b.disabled = false; return; } await api('DELETE', `/api/family/contacts/${b.dataset.ctdel}`); }
      await reload();
    } catch (er) { errEl.textContent = er.message || ''; }
    if (b.isConnected) b.disabled = false;
  });
}
// 2.140.0 D (#2137): the write-back switch of an address book; a read-only one (a mirror) gets a hint instead
function ctWbHtml(s) {
  if (s.writeback_avail === 'no') return `<span class="muted ctwb-note" data-ctwbro="${s.id}">${tr('Read only (for example a mirror): changes stay in Kalmido')}</span>`;
  return `<span class="ctwb"><label class="swc"><input type="checkbox" data-ctwb="${s.id}" ${s.writeback ? 'checked' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Write changes back to the address book'))}</span></label><span aria-hidden="true">${tr('Write changes back to the address book')}</span></span>${s.writeback && s.writeback_avail === 'some' ? `<span class="muted ctwb-note">${tr('Some of its address books are read only: nothing is written there')}</span>` : ''}${s.writeback_error ? `<span class="aerr ctwb-note">${esc(s.writeback_error)}</span>` : ''}`;
}
const fmtAgo = iso => { const m = Math.round((Date.now() - Date.parse(iso)) / 60000); return m < 1 ? tr('just now') : m < 60 ? trn('{0} min ago', '{0} min ago', m) : m < 1440 ? trn('{0} h ago', '{0} h ago', Math.round(m / 60)) : fmtDateLoc(iso.slice(0, 10)); };

// ---- the task panel: the family section (birthday / deadline data, taking turns, who comes along, stars, ingredients)
function famDetailHtml(t, l, ro) {
  if (!famOn() || !t || t.id <= 0 || t.context) return '';
  const out = [], ppl = listPeople(l).filter(p => !p.agent && !(l.members || []).find(m => m.user_id === p.user_id && m.agent));
  const shared = !!l?.shared && collab();
  // 2.27.0 (#975): "Who comes along", "Take turns" and the stars are for family / household lists (Used for: …, Home & life),
  // never for a project or an ordinary work list; a task that already uses one of them keeps showing it
  const proj = (l?.kind || 'list') === 'project', famL = !proj && !l?.org_id && !!(l?.family || l?.life);  // 2.28.0 (#935): never in an organisation's list
  if (isOcc(t)) {
    const w = occWhat(t);
    out.push(`<div class="row"><label for="d-fname">${t.fam.kind === 'birthday' ? tr('Birthday of') : tr('Anniversary of')}</label><input id="d-fname" value="${esc(t.fam.name || '')}" maxlength="100" ${ro ? 'readonly' : ''}></div>
      <div class="row"><label for="d-fyear">${t.fam.kind === 'birthday' ? tr('Year of birth') : tr('Since')}</label><input id="d-fyear" class="numin" type="number" inputmode="numeric" min="1900" max="${new Date().getFullYear()}" value="${esc(t.fam.year || '')}" ${ro ? 'readonly' : ''}>${w ? `<span class="fage">${esc(w)}${t.due ? ' · ' + esc(fmtDateLoc(t.due)) : ''}</span>` : ''}</div>`);
    // 2.140.0 D (#2137): from an address book: the date here also goes back into it (when that is on for the address book)
    if (String(t.fam.src || '').startsWith('carddav:') && t.due) out.push(`<div class="row"><label>${tr('Date')}</label>${ro ? `<span>${esc(fmtDateLoc(t.due))}</span>` : dateIn('d-fdate', t.due, {label: tr('Date'), clear: false})}<span class="muted">${tr('also in the address book, if write-back is on')}</span></div>`);
  }
  if (isDl(t)) {
    out.push(`<div class="row"><label>${tr('Household deadline')}</label><span class="muted">${esc(dlName(t.fam.type))}${t.fam.who ? ' · ' + esc(t.fam.who) : ''}</span></div>
      <div class="row"><label>${t.fam.notice ? tr('Ends on') : tr('Expires on')}</label>${ro ? `<span>${esc(fmtDateLoc(t.fam.expires || ''))}</span>` : dateIn('d-fexp', t.fam.expires || '', {label: t.fam.notice ? tr('Ends on') : tr('Expires on'), clear: false})}${t.fam.notice ? `<span class="muted">${esc(trn('notice period {0} month', 'notice period {0} months', t.fam.notice))}</span>` : ''}</div>`);
  }
  if (shared && (t.rotation || (famL && t.repeat && !t.fam))) {  // taking turns: only repeating tasks of shared lists (not a birthday / deadline)
    const r = t.rotation, on = !!r, who = new Set(r?.who || []);
    out.push(`<div class="row frot"><label>${tr('Take turns')}</label><label class="swc"><input type="checkbox" id="d-rot" ${on ? 'checked' : ''} ${ro || !canEditList(t.list_id) ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Take turns'))}</span></label>${on ? `<span class="muted">${esc(rotOrder(t))}</span>` : ''}</div>
      ${on ? `<div class="row"><label>${tr('Who')}</label><div class="fpeople" role="group" aria-label="${esc(tr('Who takes turns'))}">${ppl.map(p => `<button type="button" class="fperson ${who.has(p.user_id) ? 'on' : ''}" data-rotp="${p.user_id}" aria-pressed="${who.has(p.user_id)}" ${ro ? 'disabled' : ''}>${av(p.user_id, p.name)}<span>${esc(p.name)}</span></button>`).join('')}</div></div>
      <div class="row"><label>${tr('Next person')}</label><div class="seg" role="radiogroup" aria-label="${esc(tr('Next person'))}"><button type="button" role="radio" data-rotm="done" class="${r.mode !== 'week' ? 'on' : ''}" aria-checked="${r.mode !== 'week'}" ${ro ? 'disabled' : ''}>${tr('after each time')}</button><button type="button" role="radio" data-rotm="week" class="${r.mode === 'week' ? 'on' : ''}" aria-checked="${r.mode === 'week'}" ${ro ? 'disabled' : ''}>${tr('every week')}</button></div></div>` : ''}`);
  }
  if (shared && ppl.length > 1 && (famL || (t.people || []).length)) {  // who comes along (family events)
    const pp = new Set(t.people || []);
    out.push(`<div class="row"><label>${tr('Who comes along')}</label><div class="fpeople" role="group" aria-label="${esc(tr('Who comes along'))}">${ppl.map(p => `<button type="button" class="fperson ${pp.has(p.user_id) ? 'on' : ''}" data-famp="${p.user_id}" aria-pressed="${pp.has(p.user_id)}" ${ro || !canEditList(t.list_id) ? 'disabled' : ''}>${av(p.user_id, p.name)}<span>${esc(p.name)}</span></button>`).join('')}</div></div>`);
  }
  const kidIn = (l?.members || []).some(m => S.kidIds?.has(m.user_id));
  if ((kidIn && !t.fam && !proj) || t.stars != null) {
    out.push(`<div class="row"><label for="d-stars">${tr('Stars for a child')}</label><input id="d-stars" class="numin" type="number" inputmode="numeric" min="0" max="50" value="${esc(t.stars ?? '')}" placeholder="1" ${ro || !canEditList(t.list_id) ? 'readonly' : ''}><span class="muted">★</span></div>`);
  }
  const rw = !ro;
  if (isShopItem(t)) {  // 2.140.0 A (#2131): amount (number + unit) and price of the line
    const f = t.fam?.kind === 'shop' ? t.fam : {}, sp = f.qty == null ? shopSplit(t.title) : null;
    out.push(`<div class="row"><label for="d-fqty">${tr('Quantity')}</label><input id="d-fqty" class="numin" inputmode="decimal" autocomplete="off" value="${f.qty != null ? esc(fmtNum(f.qty, 3)) : ''}" placeholder="1" ${rw ? '' : 'readonly'}><input id="d-funit" class="numin" autocomplete="off" maxlength="16" value="${esc(f.unit || '')}" placeholder="${esc(tr('Unit'))}" aria-label="${esc(tr('Unit'))}" ${rw ? '' : 'readonly'}>${sp?.qty != null && rw ? `<button type="button" class="btn sm" data-act="fam-qtytitle" data-id="${t.id}">${esc(tr('Take “{0}” from the title', fmtNum(sp.qty, 3) + (sp.unit ? ' ' + sp.unit : '')))}</button>` : ''}</div>
      <div class="row"><label for="d-fprice">${tr('Price')}</label><input id="d-fprice" class="numin" inputmode="decimal" autocomplete="off" value="${f.price != null ? esc(fmtNum(f.price, 2)) : ''}" placeholder="0,00" ${rw ? '' : 'readonly'}></div>`);
  }
  if (isRecipe(t)) {  // 2.140.0 A (#2132): a recipe: for how many, its ingredients to a shopping list, onto a day of the meal plan
    out.push(`<div class="row"><label for="d-fserves">${tr('Servings')}</label><input id="d-fserves" class="numin" type="number" inputmode="numeric" min="1" max="100" value="${esc(t.fam?.serves ?? '')}" placeholder="4" ${rw ? '' : 'readonly'}></div>
      <div class="row"><label>${tr('Ingredients')}</label><button type="button" class="btn sm" data-act="fam-ingr" data-id="${t.id}">${ic('cart', 's')}<span>${tr('To the shopping list')}</span></button><button type="button" class="btn sm" data-act="fam-plan" data-id="${t.id}">${ic('meal', 's')}<span>${tr('Plan on a day')}</span></button></div>
      <p class="muted fhint">${tr('Ingredients as a list below a heading “Ingredients”, the method as numbered steps.')}</p>`);
  }
  if (pm_isMeal(t) && !t.parent_id) {  // 2.46.1 (#1615): also a meal in the list "Family"
    const rs = famRecipes(), rid = t.fam?.recipe, rec = rid && taskById(rid);
    // 2.140.0 A (#2132): the recipe it is made from and for how many
    if (rs.length || rid) out.push(`<div class="row"><label for="d-frecipe">${tr('Recipe')}</label><select id="d-frecipe" ${rw ? '' : 'disabled'}><option value="">${tr('none')}</option>${rid && !rec ? `<option value="${rid}" selected>${esc(tr('(not visible)'))}</option>` : ''}${rs.map(r => `<option value="${r.id}" ${r.id === rid ? 'selected' : ''}>${esc(r.title)}</option>`).join('')}</select>${rec ? `<a class="btn sm" href="#t/${rec.id}">${ic('book', 's')}<span>${tr('Open')}</span></a>` : ''}</div>`);
    if (rid || t.fam?.serves) out.push(`<div class="row"><label for="d-fserves">${tr('Servings')}</label><input id="d-fserves" class="numin" type="number" inputmode="numeric" min="1" max="100" value="${esc(t.fam?.serves ?? '')}" placeholder="${esc(rec?.fam?.serves ?? 4)}" ${rw ? '' : 'readonly'}></div>`);
    out.push(`<div class="row"><label>${tr('Ingredients')}</label><button type="button" class="btn sm" data-act="fam-ingr" data-id="${t.id}">${ic('cart', 's')}<span>${tr('To the shopping list')}</span></button><span class="muted">${rid ? tr('from the recipe, or one per line in the description') : tr('one per line in the description')}</span></div>`);
  }
  return out.length ? `<div class="dsec famsec"><h5>${tr('Family')}</h5><div class="famf">${out.join('')}</div></div>` : '';
}
async function famDetailPatch(t, body) { try { await patchUndoable(t.id, body); } catch { renderDetail(); } }
document.addEventListener('change', e => {
  const el = e.target; if (!el.closest?.('#detail .famsec')) return;
  const t = taskById(S.sel); if (!t) return;
  if (el.id === 'd-fname' || el.id === 'd-fyear') { const v = el.value.trim(); famDetailPatch(t, {fam: {...t.fam, ...(el.id === 'd-fname' ? {name: v} : {year: v ? +v : null})}}); }
  if (el.id === 'd-fexp' && el.value) famDetailPatch(t, {fam: {...t.fam, expires: el.value}});
  if (el.id === 'd-fdate' && el.value && el.value !== t.due) patchTask(t.id, {due: el.value, _act: 'occ_date'}).catch(() => renderDetail());  // 2.140.0 D (#2137)
  if (el.id === 'd-stars') famDetailPatch(t, {stars: el.value === '' ? null : +el.value});
  // 2.140.0 A (#2131, #2132): amount, unit, price of a shopping item; servings and recipe of a recipe / meal
  if (el.id === 'd-fqty' || el.id === 'd-funit' || el.id === 'd-fprice') {
    const q = el.id === 'd-fqty' ? (el.value.trim() === '' ? null : qtyParse(el.value)) : undefined, pr = el.id === 'd-fprice' ? moneyParse(el.value) : undefined;
    if (q === undefined && pr === undefined) { famDetailPatch(t, {fam: shopFamWith(t, {unit: el.value.trim().slice(0, 16)})}); return; }
    if ((el.id === 'd-fqty' && el.value.trim() !== '' && (q == null || q < 0 || q > 1e5)) || Number.isNaN(pr)) { toast(tr('Invalid value: {0}', el.id === 'd-fqty' ? tr('Quantity') : tr('Price'))); renderDetail(); return; }
    famDetailPatch(t, {fam: shopFamWith(t, el.id === 'd-fqty' ? {qty: q} : {price: pr})});
  }
  if (el.id === 'd-fserves') {
    const v = el.value === '' ? null : Math.max(1, Math.min(100, Math.round(+el.value) || 1));
    const f = {...(t.fam || {kind: isRecipe(t) ? 'recipe' : 'meal'})}; if (v == null) delete f.serves; else f.serves = v;
    famDetailPatch(t, {fam: Object.keys(f).length > 1 || t.fam ? f : null});  // a fam kind of its own stays
  }
  if (el.id === 'd-frecipe') {
    const f = {...(t.fam || {}), kind: 'meal'}; if (el.value) f.recipe = +el.value; else delete f.recipe;
    if (!f.recipe) delete f.serves;
    famDetailPatch(t, {fam: Object.keys(f).length > 1 || t.fam?.kind === 'meal' ? f : null});
  }
  if (el.id === 'd-rot') {
    if (!el.checked) { famDetailPatch(t, {rotation: null}); return; }
    const l = listById(t.list_id), ppl = listPeople(l).filter(p => !(l.members || []).find(m => m.user_id === p.user_id && m.agent)).map(p => p.user_id);
    const who = [t.assignee_id, ...ppl].filter((x, i, a) => x && a.indexOf(x) === i);
    if (who.length < 2) { el.checked = false; toast(tr('Taking turns needs at least two people')); return; }
    famDetailPatch(t, {rotation: {who, mode: 'done'}});
  }
});
document.addEventListener('click', e => {
  const b = e.target.closest?.('#detail .famsec [data-rotp], #detail .famsec [data-rotm], #detail .famsec [data-famp]'); if (!b || b.disabled) return;
  const t = taskById(S.sel); if (!t) return;
  if (b.dataset.famp) { const s = new Set(t.people || []), u = +b.dataset.famp; s.has(u) ? s.delete(u) : s.add(u); famDetailPatch(t, {people: [...s]}); return; }
  const r = t.rotation; if (!r) return;
  if (b.dataset.rotm) { if (r.mode !== b.dataset.rotm) famDetailPatch(t, {rotation: {who: r.who, mode: b.dataset.rotm}}); return; }
  const u = +b.dataset.rotp, who = r.who.includes(u) ? r.who.filter(x => x !== u) : [...r.who, u];
  if (who.length < 2) { toast(tr('Taking turns needs at least two people')); return; }
  famDetailPatch(t, {rotation: {who, mode: r.mode}});
});

// ---- shopping mode: big ticks, grouped by shop area, live for everyone (polls every 2 s while open)
function shopModeOpen(lid) {
  const l = listById(lid); if (!l) return;
  S.shop = {lid};
  const ov = document.createElement('div');
  ov.className = 'modal shopmode'; ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-modal', 'true'); ov.setAttribute('aria-labelledby', 'shop-h');
  ov.innerHTML = '<div class="card shopcard"></div>';
  document.body.appendChild(ov);
  modalA11y(ov);
  shopDraw();
  onRemove(ov, () => {
    S.shop = null; clearInterval(shopTimer); render();
    if (history.state?.shop) history.back();  // closed with X / Esc: drop the entry the back button would close it with
    // render() drew the view anew: the focus goes back to the button that opened shopping mode (WCAG 2.4.3)
    const a = document.activeElement;
    if (!a || a === document.body || !a.isConnected) $(`#view [data-act="fam-shop"][data-lid="${lid}"], #view [data-act="fam-shop"][data-id="${lid}"], #view [data-act="shop-start"][data-lid="${lid}"]`)?.focus({preventScroll: true});
  });
  clearInterval(shopTimer);
  shopTimer = setInterval(shopPoll, 2000);
  shopPoll();  // 2.140.0 A (#2131): fresh at once, so the local copy (the offline cache) is the latest one for the shop
  if (isMobile() || isTouch()) history.pushState({shop: lid}, '', location.hash);  // Android Back closes shopping mode, not the app
  // a phone keyboard would cover half the list: the field gets the focus only with a mouse / keyboard
  if (!isTouch()) setTimeout(() => $('.shopmode .shopadd input')?.focus({preventScroll: true}), 60);
}
window.addEventListener('popstate', () => { if (S.shop) $('.shopmode')?.remove(); });
// a tap on an item's name ticks it too (the whole row is the target; the circle stays the control for screen readers)
document.addEventListener('click', e => { const n = e.target.closest?.('.shopmode .shopt'); if (n) n.closest('.shopi')?.querySelector('.shopchk:not([disabled])')?.click(); });
// 2.19.0: the Family dialogs are no forms: Enter in a one-line field (the phone's "Done" key) saves like the main button
document.addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.isComposing || e.shiftKey || !e.target.matches?.('.famdlg input:not([type="checkbox"])')) return;
  const b = e.target.closest('.famdlg').querySelector('.foot .btn.pri'); if (!b) return;
  e.preventDefault(); b.click();
});
document.addEventListener('focusin', e => { if (e.target.matches?.('.famdlg input:not([type="checkbox"])') && !e.target.hasAttribute('enterkeyhint')) e.target.setAttribute('enterkeyhint', 'done'); });
let shopTimer = 0;
// 2.140.0 A (#2131): offline in the shop: ticks, unticks, new items and amounts wait in the outbox (core.js) and go out on
// reconnect (last state wins); the poll then only tries quietly every 10 s, the hint and the number of waiting changes follow
const shopSig = () => `${OUT.online ? 1 : 0}|${OUT.down ? 1 : 0}|${OUT.q.length}`;
async function shopPoll() {
  if (!S.shop) return;
  if (S.shop.sig !== shopSig() && !imeOn) shopDraw();
  if (document.hidden || OUT.q.length || imeOn) return;  // the add field keeps its text and focus through a redraw
  if (!OUT.online && (S.shop.n = (S.shop.n || 0) + 1) % 5) return;
  try { const {v} = await api('GET', '/api/version'); if (v !== S.v) { await load(); shopDraw(); } } catch { /* offline: the ticks wait in the queue */ }
}
function shopDraw() {
  const ov = $('.shopmode'); if (!ov || !S.shop) return;
  const l = listById(S.shop.lid); if (!l) { ov.remove(); return; }
  const items = [...S.tasks.values()].filter(t => t.list_id === l.id && !t.deleted_at && !t.parent_id);
  const open = items.filter(t => t.status === 0), done = items.filter(t => t.status !== 0).sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''));
  const secs = S.sections.filter(s => s.list_id === l.id).sort((a, b) => a.sort - b.sort || a.id - b.id);
  const ro = !canAddTo(l.id);
  const qn = t => shopQty(t), pr = t => t.fam?.kind === 'shop' && t.fam.price != null ? t.fam.price : null;  // 2.140.0 A (#2131)
  const row = t => `<li class="shopi ${t.status ? 'done' : ''}"><button type="button" class="shopchk" data-act="shop-tick" data-id="${t.id}" role="checkbox" aria-checked="${t.status !== 0}" aria-label="${esc((qn(t) ? qn(t) + ' ' : '') + t.title)}" ${canEdit(t) ? '' : 'disabled'}>${t.status ? ic('check') : ''}</button><span class="shopt">${esc(t.title)}${pr(t) != null ? `<small class="shoppr">${esc(fmtMoney(pr(t)))}</small>` : ''}</span><button type="button" class="shopq ${qn(t) ? '' : 'none'}" data-act="shop-qty" data-id="${t.id}" title="${esc(tr('Quantity and price'))}" aria-label="${esc(tr('Quantity and price of {0}', t.title) + (qn(t) ? ': ' + qn(t) : ''))}" ${canEdit(t) ? '' : 'disabled'}>${qn(t) ? esc(qn(t)) : ic('plus', 's')}</button>${!t.status && secs.length && canEditList(l.id) ? `<button type="button" class="iconbtn shoparea" data-act="shop-area" data-id="${t.id}" aria-haspopup="menu" title="${esc(tr('Shop area'))}" aria-label="${esc(tr('Shop area of {0}', t.title))}">${ic('columns', 's')}</button>` : ''}</li>`;
  const groups = [...secs.map(s => [s.name, open.filter(t => t.section_id === s.id)]), [tr('Other'), open.filter(t => !t.section_id || !secs.some(s => s.id === t.section_id))]].filter(g => g[1].length);
  const focusId = document.activeElement?.closest?.('.shopmode') ? (document.activeElement.dataset.id ? `[data-act="${document.activeElement.dataset.act}"][data-id="${document.activeElement.dataset.id}"]` : document.activeElement.id ? '#' + document.activeElement.id : '') : '';
  const val = $('#shop-in', ov)?.value || '';
  S.shop.sig = shopSig();
  const sum = ts => ts.reduce((a, t) => a + (pr(t) || 0), 0), priced = items.some(t => pr(t) != null);
  const off = !OUT.online ? `<p class="shopoff" role="status">${ic('cloud', 's')}<span>${esc([OUT.down ? tr('Server not reachable – changes are sent later') : tr('Offline – changes are sent later'), OUT.q.length ? trn('{0} change waiting', '{0} changes waiting', OUT.q.length) : ''].filter(Boolean).join(' · '))}</span></p>` : '';
  $('.shopcard', ov).innerHTML = `<div class="shophead"><h2 id="shop-h">${ic('cart', 's')}<span>${esc(lname(l))}</span></h2><span class="shopn" role="status">${esc(open.length ? trn('{0} left', '{0} left', open.length) : tr('Everything in the cart'))}</span><span class="spacer"></span><button type="button" class="iconbtn shopx" data-act="shop-close" aria-label="${esc(tr('End shopping mode'))}" title="${esc(tr('End shopping mode'))}">${ic('x')}</button></div>
    ${off}${ro ? '' : `<form class="shopadd" data-shopadd><input id="shop-in" autocomplete="off" enterkeyhint="done" placeholder="${esc(tr('Add an item'))}" aria-label="${esc(tr('Add an item'))}"><button type="submit" class="btn pri" aria-label="${esc(tr('Add'))}">${ic('plus', 's')}</button></form>`}
    <div class="shopbody">${groups.map(([n, ts]) => `<section class="shopg"><h3>${esc(n)} <span class="c">${ts.length}</span></h3><ul>${ts.map(row).join('')}</ul></section>`).join('') || (items.length ? '' : `<p class="muted">${tr('The list is empty.')}</p>`)}
    ${done.length ? `<section class="shopg shopdone"><h3>${tr('In the cart')} <span class="c">${done.length}</span></h3><ul>${done.map(row).join('')}</ul></section>` : ''}</div>
    ${priced ? `<div class="shopsum" role="status"><span>${tr('Still to buy')} <b>${esc(fmtMoney(sum(open)))}</b></span><span>${tr('In the cart')} <b>${esc(fmtMoney(sum(done)))}</b></span></div>` : ''}`;
  if ($('#shop-in', ov)) $('#shop-in', ov).value = val;
  if (focusId) { const f = $(focusId, ov); if (f) f.focus({preventScroll: true}); }
}
document.addEventListener('submit', async e => {
  if (!e.target.matches?.('[data-shopadd]')) return;
  e.preventDefault();
  const inp = $('#shop-in'), raw = inp?.value || '', v = raw.trim(); if (!v || !S.shop || inp.dataset.qbusy) return;
  inp.dataset.qbusy = '1';  // 2.359.2 B (#3049): the text stays until the item is saved; a second Enter sends nothing twice
  // 2.140.0 A (#2131): a clear leading amount goes to the amount field; an open item of the same name is not added twice
  // (the amount is added to it when the units match), also offline
  const sp = shopSplit(v), lid = S.shop.lid, k = shopKeyC(sp.name);
  const same = [...S.tasks.values()].find(t => t.list_id === lid && t.status === 0 && !t.deleted_at && !t.parent_id && shopKeyC(t.title) === k);
  try {
    if (same) {
      const f = same.fam?.kind === 'shop' ? same.fam : null, uk = u => String(u || '').toLowerCase().replace(/\.$/, '');
      if (sp.qty != null && !same.fam && shopSplit(same.title).qty == null) await patchTask(same.id, {fam: shopFamWith(same, {qty: sp.qty, unit: sp.unit})}, true);
      else if (sp.qty != null && f?.qty != null && uk(f.unit) === uk(sp.unit)) await patchTask(same.id, {fam: shopFamWith(same, {qty: Math.round((f.qty + sp.qty) * 1000) / 1000})}, true);
      toast(tr('Already on the list: {0}', same.title));
    } else await createTask({title: sp.qty != null ? sp.name : v, list_id: lid, ...(sp.qty != null ? {fam: shopFamWith({}, {qty: sp.qty, unit: sp.unit})} : {})});
    const f = $('#shop-in'); if (f && f.value === raw) f.value = '';  // saved: empty (text typed meanwhile stays)
    if (inp.value === raw) inp.value = '';
    await load();
  } catch { /* api() said it; the text stays in the field */ } finally { delete inp.dataset.qbusy; }
  shopDraw(); $('#shop-in')?.focus({preventScroll: true});
});

// ---- clicks of the Family view, the kid view, shopping mode and the list bars
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-act^="fam-"], [data-act^="kid-"], [data-act^="shop-"]'); if (!a || a.disabled) return;
  e.preventDefault(); e.stopPropagation();
  const k = a.dataset.act, id = +a.dataset.id || 0;
  if (k === 'fam-occ') occModal();
  else if (k === 'fam-dl') dlModal();
  else if (k === 'fam-contacts') contactsModal();
  else if (k === 'fam-pack') famPack(a.dataset.k);
  else if (k === 'fam-newlist') { const lid = await famNewList(a.dataset.k); if (lid) go('l/' + lid); }
  else if (k === 'fam-meal') famMeal(a.dataset.day);
  else if (k === 'fam-ingr') famIngredients(id);
  else if (k === 'fam-week') { S.famWeek = addDays(S.famWeek || today(), +a.dataset.d); renderView(); $(`#view [data-act="fam-week"][data-d="${a.dataset.d}"]`)?.focus(); }
  else if (k === 'fam-weeknow') { S.famWeek = null; renderView(); $('#view [data-act="fam-weekpick"]')?.focus(); }  // 2.140.0 A (#2132)
  else if (k === 'fam-weekpick') famWeekPick();
  else if (k === 'fam-plan') famPlan(id);
  else if (k === 'fam-recipes') famRecipesOpen();
  else if (k === 'fam-qtytitle') { const t = taskById(id), sp = shopSplit(t?.title); if (t && sp.qty != null) famDetailPatch(t, {title: sp.name, fam: shopFamWith(t, {qty: sp.qty, unit: sp.unit})}); }
  else if (k === 'shop-qty') shopQtyEdit(id);
  else if (k === 'fam-shop' || k === 'shop-start') shopModeOpen(id || +a.dataset.lid);
  else if (k === 'fam-areas') { try { const j = await api('POST', `/api/lists/${a.dataset.lid}/shop-areas`, {}); await load(); render(); toast(trn('{0} shop area added', '{0} shop areas added', j.added)); } catch { /* api() said it */ } }
  else if (k === 'fam-give') famGive(+a.dataset.kid);
  else if (k === 'fam-rewards') rewardsModal(+a.dataset.kid);
  else if (k === 'fam-pin') kd_pinSet(+a.dataset.kid);  // 2.49.0 (#1551)
  else if (k === 'fam-decide') { try { famKidSet(await api('POST', `/api/family/rewards/${a.dataset.rid}/decide`, {approve: a.dataset.ok === '1'})); toast(a.dataset.ok === '1' ? tr('Redeemed') : tr('Declined')); } catch { /* api() said it */ } }
  else if (k === 'kid-tick') {
    const t = taskById(id); if (!t) return;
    const was = t.status, before = S.kids?.[0]?.stars ?? 0;
    await toggleTask(id);
    const got = (S.kids?.[0]?.stars ?? before) - before;  // ticked again after an untick: no new stars, so no "+N"
    if (was === 0 && got > 0) toast(trn('+{0} star!', '+{0} stars!', got));
  }
  else if (k === 'kid-want') { try { const j = await api('POST', `/api/family/rewards/${a.dataset.rid}/request`, {}); S.kids = [j]; renderView(); toast(tr('Asked. Your parents get a message.')); } catch { /* api() said it */ } }
  else if (k === 'shop-close') $('.shopmode')?.remove();
  else if (k === 'shop-tick') { const t = taskById(id); if (!t) return; try { await toggleTask(id); } catch { /* queued offline */ } shopDraw(); $(`.shopmode [data-act="shop-tick"][data-id="${id}"]`)?.focus({preventScroll: true}); }
  else if (k === 'shop-area') {
    const t = taskById(id), secs = S.sections.filter(s => s.list_id === t.list_id).sort((x, y) => x.sort - y.sort || x.id - y.id);
    menu(a, [...secs.map(s => ({label: s.name, on: t.section_id === s.id, fn: async () => { await patchTask(id, {section_id: s.id}, true).catch(() => {}); shopDraw(); }})),
      '-', {label: tr('Other'), on: !t.section_id, fn: async () => { await patchTask(id, {section_id: null}, true).catch(() => {}); shopDraw(); }}]);
  }
});
// the bar above a family list: shopping mode / shop areas, the meal plan, birthdays
function famBar(l) {
  if (!famOn() || !l?.family || l.archived) return '';
  if (l.family === 'shopping') {
    const n = shopOpen(l.id), hasSec = S.sections.some(s => s.list_id === l.id);
    return `<div class="fambar"><button type="button" class="btn pri shopgo" data-act="shop-start" data-lid="${l.id}">${ic('cart', 's')}<span>${tr('Shopping mode')}</span></button><span class="muted">${esc(trn('{0} item left', '{0} items left', n))}</span>${!hasSec && canEditList(l.id) ? `<button type="button" class="btn sm" data-act="fam-areas" data-lid="${l.id}">${ic('columns', 's')}<span>${tr('Add shop areas')}</span></button>` : ''}</div>`;
  }
  // 2.140.0 A (#2132): a recipe = a task (servings in the task panel, ingredients + method in its description)
  if (l.family === 'recipes') return `<div class="fambar"><a class="btn" href="#family">${ic('meal', 's')}<span>${tr('Week plan')}</span></a><span class="muted">${tr('A recipe per task: ingredients and method in its description.')}</span></div>`;
  if (l.family === 'meals') return `<div class="fambar"><a class="btn" href="#family">${ic('meal', 's')}<span>${tr('Week plan')}</span></a><span class="muted">${tr('A meal per day, the ingredients in its description.')}</span></div>`;
  if (l.family === 'birthdays') return `<div class="fambar"><button type="button" class="btn" data-act="fam-occ">${ic('cake', 's')}<span>${tr('Birthday')}</span></button><button type="button" class="btn" data-act="fam-contacts">${ic('users', 's')}<span>${tr('From contacts…')}</span></button></div>`;
  if (l.family === 'household') return `<div class="fambar"><button type="button" class="btn" data-act="fam-dl">${ic('hourglass', 's')}<span>${tr('Household deadline')}</span></button><a class="btn" href="#family">${ic('family', 's')}<span>${tr('Family')}</span></a></div>`;
  // 2.46.1 (#1615): the list "Family" holds birthdays, deadlines and the meal plan in its sections
  if (l.family === 'family') return `<div class="fambar"><button type="button" class="btn" data-act="fam-occ">${ic('cake', 's')}<span>${tr('Birthday')}</span></button><button type="button" class="btn" data-act="fam-dl">${ic('hourglass', 's')}<span>${tr('Household deadline')}</span></button><a class="btn" href="#family">${ic('meal', 's')}<span>${tr('Week plan')}</span></a></div>`;
  return '';
}

// ---- "What do you use Kalmido for?" (setup, welcome tour, Settings > Modules)
const purposeCards = (cur, attr = 'data-purpose') => `<div class="ptcards purposes" role="radiogroup" aria-label="${esc(tr('What do you use Kalmido for?'))}">${PURPOSES.map(([k, i, n, d]) => `<button type="button" class="ptcard ${k === cur ? 'on' : ''}" role="radio" aria-checked="${k === cur}" ${attr}="${k}">${ic(i, 's')}<b>${tr(n)}</b><small class="muted">${tr(d)}</small></button>`).join('')}</div>`;
// 2.364.0 A (#3032): the first start of an account an admin made (user admin, organisation invitation, import) asks only
// "What do you use Kalmido for?" (the language is set already), preselected with the purpose of the inviting admin, else
// "For me". The answer switches the modules to exactly that package; the "Getting started" list and the tour follow.
// Closed without an answer: nothing changes, the question comes again on the next start.
function paskOpen() {
  const pre = S.settings.purpose_ask;
  if (!pre || pre === 'done' || S.me?.kid || $('.paskdlg')) return Promise.resolve(false);
  let cur = PURPOSES.some(x => x[0] === pre) ? pre : 'me';
  return new Promise(res => {
    const md = modal(`<h3>${tr('What do you use Kalmido for?')}</h3><p class="muted">${tr('Pick what fits: it switches the modules. Everything can be changed later under Settings > Modules.')}</p>
      <div id="pask-c">${purposeCards(cur, 'data-pask')}</div><div class="aerr" role="alert" id="pask-err"></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-pask-go>${tr('Continue')}</button></div>`);
    md.classList.add('paskdlg');
    let done = false;
    onRemove(md, () => { if (!done) res(false); });
    md.addEventListener('click', async e => {
      const c = e.target.closest('[data-pask]');
      if (c) { cur = c.dataset.pask; $('#pask-c', md).innerHTML = purposeCards(cur, 'data-pask'); $(`[data-pask="${cur}"]`, md)?.focus(); return; }
      if (!e.target.closest('[data-pask-go]')) return;
      try { await api('POST', '/api/me/purpose', {purpose: cur, only: true}); } catch (err) { $('#pask-err', md).textContent = err.message || tr('Server not reachable.'); return; }
      done = true; S.settings.purpose_ask = 'done'; md.remove();
      try { await load(); render(); } catch { /* offline: the next load */ }
      res(true);
    });
  });
}
async function purposeSet(p) {
  const n = PURPOSES.find(x => x[0] === p);
  // 2.25.0 (UX-25): the dialog lists what changes (modules on / off, tabs that leave the tab bar)
  // 2.46.1 (#1591): with the switch "Switch on all modules" (on = every module, off = lists and tasks only)
  const all = pm_allOn(), want = pm_purposeOn(p, all), mname = k => tr(FEATS.find(x => x[0] === k)?.[1] || k);
  const ton = [...new Set([...PURPOSE_ALL, ...(PURPOSE_EXTRA[p] || []), ...(all ? pma_full() : [])])].filter(k => want.has(k) && !feat(k)), toff = pm_touched(all).filter(k => !want.has(k) && feat(k));
  const tabs = tabIds().filter(id => id.startsWith('m:') && toff.includes(id.slice(2))).map(id => mname(id.slice(2)));
  const chg = `<ul class="cdlg-l">${ton.length ? `<li>${esc(tr('On: {0}', ton.map(mname).join(', ')))}</li>` : ''}${toff.length ? `<li>${esc(tr('Off: {0}', toff.map(mname).join(', ')))}</li>` : ''}${tabs.length ? `<li>${esc(tr('Leaves the tab bar: {0}', tabs.join(', ')))}</li>` : ''}${!ton.length && !toff.length ? `<li>${esc(tr('No module changes.'))}</li>` : ''}</ul>`;
  // 2.46.1 (#1615): Family brings the shopping list + the list "Family" (always, once); the switch adds example entries
  const famNew = p === 'family' && !S.lists.some(l => ['shopping', 'family', 'household', 'birthdays', 'meals'].includes(l.family));
  const once = p === 'family' ? (famNew ? tr('Example entries in the shopping list and the project Family.') : '') : p === 'software' ? tr('A software project is created once.') : p === 'team' || p === 'office' ? tr('The sample project is created once.') : '';
  // 2.46.1 (#1602): the sample project is a switch, off by default (instead of the fixed sentence)
  let ex = false; const exCh = e => { if (e.target.id === 'pm-ex') ex = e.target.checked; };
  document.addEventListener('change', exCh);
  let ok; try { ok = await askConfirm(tr('Switch to “{0}”?', tr(n[2])), '', {ok: tr('Set up'), html: `<p>${esc(tr('Your modules are switched to fit; nothing is deleted and everything can be changed again below.'))}</p>${chg}${famNew ? `<p>${esc(tr('A shopping list and a project Family (sections Household, Birthdays, Meal plan, Deadlines) are created once, in the folder Family.'))}</p>` : ''}${once ? pm_switchHtml('pm-ex', false, tr('Create a sample project'), once) : ''}`}); } finally { document.removeEventListener('change', exCh); }
  if (!ok) return false;
  let j; try { j = await api('POST', '/api/me/purpose', {purpose: p, all_modules: all, examples: !!once && ex}); } catch { return false; }
  S.settings.features = j.features; S.settings.purpose = p; S.settings.mods_all = all ? '1' : '0';
  await load();
  // 2.46.1 (#1601): a state fetched across the switch may carry the modules from before; the answer of the switch counts
  if (S.settings.purpose === p) S.settings.features = j.features;
  render();
  toast(j.created?.length ? trn('Done: {0} project created', 'Done: {0} projects created', j.created.length) : tr('Done'));
  return true;
}

// ---- 2.19.0: more reactions in the chats: "+" next to 👍 👎 ❤️ opens the emoji grid of the comments (any emoji too)
function rxMore(anchor) {
  const act = anchor.dataset.rxact, mid = +anchor.dataset.mid;
  reactPicker(anchor, null, v => act === 'chat-react' ? chatReact(mid, v) : act === 'tc-react' ? tcReact(mid, v) : null);
  setTimeout(() => $('#pop .rxgrid button')?.focus({preventScroll: true}), 0);
}
document.addEventListener('click', e => { const b = e.target.closest?.('[data-act="rx-more"]'); if (!b) return; e.preventDefault(); e.stopPropagation(); rxMore(b); });
// Settings > Modules: "What do you use Kalmido for?"
let pm_purposeBusy = false;
document.addEventListener('click', async e => {
  const b = e.target.closest?.('.smodal [data-purpose]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  // 2.46.1 (#1601): one purpose switch at a time; quick clicks between the purposes overlapped (switch, reload, rebuild)
  // and left a dialog whose counts and switches showed different states
  if (pm_purposeBusy) return;
  pm_purposeBusy = true;
  let ok; try { ok = await purposeSet(b.dataset.purpose); } finally { pm_purposeBusy = false; }
  if (!ok) return;
  const mds = $$('.smodal'); if (mds.length) { mds.forEach(md => { md._noflush = true; md.remove(); }); settingsModal('modules'); settingsSync(); setTimeout(() => $(`.smodal [data-purpose="${b.dataset.purpose}"]`)?.focus(), 80); }
});
// 2.19.0 (owner, #655): the magnifier stays visible on a phone while the sidebar drawer is open: a round search button on
// the dimmed area next to the drawer, where the header's search sits (the header itself is under the scrim then)
function sideSearchSync() {
  const sc = $('#scrim'); if (!sc) return;
  let b = $('.sidesearch', sc);
  if (!b) {
    b = document.createElement('button'); b.type = 'button'; b.className = 'iconbtn sidesearch';
    b.addEventListener('click', e => { e.stopPropagation(); closeSide(); openPalette(); });
    sc.appendChild(b);
  }
  const lab = tr('Search and commands');
  if (b.getAttribute('aria-label') !== lab) { b.setAttribute('aria-label', lab); b.title = lab; b.innerHTML = ic('search'); }
}
// 2.49.0 (#1537): what a child account sees in Settings: its account (name, picture, colour, password, sign-in), General
// (language), Appearance and Notifications (push). The areas whose writes the server refuses to a child (organisation,
// modules, integrations, agents, data, administration), the help for grown-ups and in the account pane app passwords,
// end-to-end keys and the developer part are hidden by app.css (block 2.49.0 B; the panes stay in the page, their set-up
// code expects them)
// ---- 2.49.0 (#1551): the parents' PIN of a child account. With a PIN the child needs it for Settings, its account and
// Log out (the server checks too, family/pin.py); a correct PIN opens them for 5 minutes in this session. Ticking off and
// asking for rewards never need it.
const kd_me = () => (S.me?.kid && (S.kids || [])[0]) || null;
function kd_pinNeed() { const k = kd_me(); return !!(k && k.pin && !(k.pin_open && Date.parse(k.pin_open) > Date.now())); }
function kd_pinClosed() { const k = kd_me(); if (k) { k.pin_open = null; if (!$('.kdpin')) kd_pinAsk(); } }
function kd_pinAsk(then) {
  const k = kd_me(); if (!k) return;
  $('.kdpin')?.remove();
  const md = modal(`<h3>${ic('lock', 's')} ${tr('Parent PIN')}</h3>
    <p class="muted">${tr('Settings, your account and logging out need the PIN of your parents.')}</p>
    <input id="kd-pin" class="kd_pinin" type="password" inputmode="numeric" pattern="[0-9]*" autocomplete="off" maxlength="6" aria-label="${esc(tr('PIN'))}">
    <div class="kd_pinmsg" id="kd-pinmsg" role="status" aria-live="polite"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Open')}</button></div>`);
  md.classList.add('kdpin');
  const inp = $('#kd-pin', md), msg = $('#kd-pinmsg', md);
  const wait = s => { msg.textContent = trn('Too many wrong PINs. Try again in {0} minute.', 'Too many wrong PINs. Try again in {0} minutes.', Math.max(1, Math.ceil(s / 60))); inp.disabled = true; };
  if (k.pin_wait > 0) wait(k.pin_wait);
  const go = async () => {
    const pin = inp.value.trim(); if (!/^[0-9]{4,6}$/.test(pin)) { msg.textContent = tr('The PIN has 4 to 6 digits'); inp.focus(); return; }
    try {
      const j = await rawFetch('POST', '/api/me/pin/unlock', {pin});
      k.pin_open = j.until; k.pin_wait = 0; md.remove(); if (then) then();
    } catch (e) {
      if (e.status === 429) wait(e.data?.wait || 900);
      else if (e.status === 403) { msg.textContent = e.data?.left ? trn('Wrong PIN. {0} try left.', 'Wrong PIN. {0} tries left.', e.data.left) : tr('Wrong PIN'); inp.value = ''; inp.focus(); }
      else msg.textContent = e.message || '';
    }
  };
  md.addEventListener('click', e => { const b = e.target.closest('button'); if (!b) return; if (b.dataset.m === 'close') md.remove(); else if (b.dataset.m === 'ok') go(); });
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go(); } });
  setTimeout(() => inp.focus(), 30);
}
// a parent: set, change or remove the PIN of a child
function kd_pinSet(kid) {
  const k = (S.kids || []).find(x => x.id === kid); if (!k) return;
  const md = modal(`<h3>${ic('lock', 's')} ${tr('Parent PIN for {0}', esc(k.display_name))}</h3>
    <p class="muted">${tr('With a PIN {0} needs it for Settings, the account and logging out. Ticking off tasks and asking for rewards stay free.', esc(k.display_name))}</p>
    <div class="row"><label for="kd-new">${k.pin ? tr('New PIN') : tr('PIN')}</label><input id="kd-new" class="kd_pinin" type="password" inputmode="numeric" pattern="[0-9]*" autocomplete="new-password" maxlength="6" placeholder="${esc(tr('4 to 6 digits'))}"></div>
    <div class="aerr" role="alert" id="kd-err"></div>
    <div class="foot">${k.pin ? `<button class="btn danger" data-m="del">${tr('Remove PIN')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('famdlg');
  const errEl = $('#kd-err', md), inp = $('#kd-new', md);
  const save = async () => {
    const pin = inp.value.trim(); if (!/^[0-9]{4,6}$/.test(pin)) { errEl.textContent = tr('The PIN has 4 to 6 digits'); inp.focus(); return; }
    try { famKidSet(await rawFetch('PUT', `/api/family/kids/${kid}/pin`, {pin})); md.remove(); toast(tr('PIN saved for {0}', k.display_name)); } catch (e) { errEl.textContent = e.message || ''; }
  };
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') md.remove();
    else if (b.dataset.m === 'save') save();
    else if (b.dataset.m === 'del') { try { famKidSet(await rawFetch('DELETE', `/api/family/kids/${kid}/pin`)); md.remove(); toast(tr('PIN removed for {0}', k.display_name)); } catch (er) { errEl.textContent = er.message || ''; } }
  });
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
  setTimeout(() => inp.focus(), 30);
}
// ---- 2.49.0 (#1533): the welcome tour of a child account: at most four big cards in plain words, no sample project,
// no modules, no shortcuts, no settings. A child cannot add tasks itself (family.py KID_WRITE), so there is no card for it.
function kd_tourSteps() {
  const at = sel => () => { const e = $(sel); return e ? e.getBoundingClientRect() : null; };
  const s = [{id: 'kd-tasks', sel: '.kidv .kidsec', t: N_('Your tasks'), d: N_('Here are your things for today.'), r: at('.kidv .kidsec')},
    {id: 'kd-tick', sel: '.kidv .kidchk', t: N_('Tick off'), d: N_('Tap the circle when you have done something. Then it is done and you get stars.'), r: at('.kidv .kidchk')},
    {id: 'kd-parents', sel: '.kidv .kd_list', t: N_('From your parents'), d: collab() ? N_('Tasks your parents give you are here, under the name of their project. Messages come in behind the bell at the top.') : N_('Tasks your parents give you are here, under the name of their project.'), r: at('.kidv .kd_list .kidsec')}];
  return s;
}
