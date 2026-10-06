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
const FAM_KINDS = [['', N_('An ordinary list')], ['shopping', N_('Shopping list')], ['meals', N_('Meal plan')], ['birthdays', N_('Birthdays')],
  ['household', N_('Household')], ['packing', N_('Packing list')]];
const FAM_KIND_ICON = {shopping: 'cart', meals: 'meal', birthdays: 'cake', household: 'home', packing: 'bag'};
const famKindOf = lid => listById(lid)?.family || '';
const isOcc = t => !!t?.fam && (t.fam.kind === 'birthday' || t.fam.kind === 'anniversary');
const isDl = t => t?.fam?.kind === 'deadline';
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
  const meals = [...S.tasks.values()].filter(t => !t.deleted_at && !t.parent_id && t.due && t.due >= mon && t.due <= sun && mealLists.some(l => l.id === t.list_id));
  const shops = S.lists.filter(l => l.family === 'shopping' && !l.archived);
  return {occ, dls, rots, mon, meals, mealLists, shops, kids: S.kids || []};
}
const shopOpen = lid => [...S.tasks.values()].filter(t => t.list_id === lid && t.status === 0 && !t.deleted_at && !t.parent_id).length;

function viewFamily() {
  if (kidMe()) return viewKid();
  const d = famData(), t0 = today();
  const card = (k, icon, title, body, more = '', n = '') => `<section class="dcard fcard fc-${k}" aria-labelledby="fh-${k}"><h2 id="fh-${k}">${ic(icon, 's')}<span>${esc(title)}</span>${n !== '' ? `<span class="dcn">${n}</span>` : ''}<span class="spacer"></span>${more}</h2>${body}</section>`;
  const open = id => `href="#t/${id}"`;
  // birthdays + anniversaries: the next 60 days, at least the next three
  const occ = d.occ.filter((t, i) => daysTo(t.due) <= 60 || i < 3).slice(0, 8);
  const occH = occ.length ? `<ul class="flist">${occ.map(t => { const n = daysTo(t.due), w = occWhat(t); return `<li><a ${open(t.id)} class="frow"><span class="fem" aria-hidden="true">${t.fam.kind === 'birthday' ? '🎂' : '💍'}</span><span class="ft"><b>${esc(t.fam.name || t.title)}</b>${w ? `<span class="muted">${esc(w)}</span>` : ''}</span><span class="fwhen ${n <= 7 ? 'soon' : ''}">${esc(n <= 14 ? daysWord(n) : fmtDateLoc(t.due))}</span></a></li>`; }).join('')}</ul>`
    : `<p class="muted">${tr('No birthdays yet.')}</p>`;
  // whose turn
  const rotH = d.rots.length ? `<ul class="flist">${d.rots.map(t => { const r = t.rotation, i = (r.i || 0) % r.who.length, nx = r.who[(i + 1) % r.who.length], ln = listById(t.list_id);
    return `<li><a ${open(t.id)} class="frow">${av(t.assignee_id, personName(t.list_id, t.assignee_id) || '?')}<span class="ft"><b>${esc(t.title)}</b><span class="muted">${esc(rotOrder(t))} · ${esc(r.mode === 'week' ? tr('weekly') : tr('after each time'))}</span></span>${t.due ? `<span class="fwhen ${t.due < t0 ? 'over' : ''}">${esc(dayLabel(t.due))}</span>` : ''}</a></li>`; }).join('')}</ul>`
    : `<p class="muted">${tr('Nobody takes turns yet: open a repeating task in a shared list and choose “Take turns”.')}</p>`;
  // meal plan of the week
  const days = [...Array(7)].map((_, i) => addDays(d.mon, i));
  const mealH = `<div class="fweek" role="group" aria-label="${esc(tr('Meal plan'))}">${days.map(day => { const ms = d.meals.filter(t => t.due === day);
    return `<div class="fday ${day === t0 ? 'today' : ''}"><span class="fdl">${esc(dayLabel(day))}</span><span class="fdm">${ms.map(t => `<span class="fmeal ${t.status ? 'done' : ''}"><a ${open(t.id)}>${esc(t.title)}</a><button type="button" class="iconbtn" data-act="fam-ingr" data-id="${t.id}" title="${esc(tr('Ingredients to the shopping list'))}" aria-label="${esc(tr('Ingredients of {0} to the shopping list', t.title))}">${ic('cart', 's')}</button></span>`).join('')}</span><button type="button" class="iconbtn" data-act="fam-meal" data-day="${day}" title="${esc(tr('Add a meal'))}" aria-label="${esc(tr('Add a meal on {0}', fmtDateLoc(day)))}">${ic('plus', 's')}</button></div>`; }).join('')}</div>`;
  const weekNav = `<span class="fwnav"><button type="button" class="iconbtn" data-act="fam-week" data-d="-7" aria-label="${esc(tr('Previous week'))}" title="${esc(tr('Previous week'))}">${ic('left', 's')}</button><button type="button" class="iconbtn" data-act="fam-week" data-d="7" aria-label="${esc(tr('Next week'))}" title="${esc(tr('Next week'))}">${ic('right', 's')}</button></span>`;
  // shopping
  const shopH = d.shops.length ? `<ul class="flist">${d.shops.map(l => `<li class="frow fshop"><a href="#l/${l.id}" class="ft"><b>${esc(lname(l))}</b><span class="muted">${esc(trn('{0} item left', '{0} items left', shopOpen(l.id)))}</span></a><button type="button" class="btn pri" data-act="fam-shop" data-id="${l.id}">${ic('cart', 's')}<span>${tr('Shopping mode')}</span></button></li>`).join('')}</ul>`
    : `<p class="muted">${tr('No shopping list yet.')}</p><button type="button" class="btn" data-act="fam-newlist" data-k="shopping">${ic('plus', 's')} ${tr('Shopping list')}</button>`;
  // deadlines: what is due in the next half year, and what is overdue
  const dls = d.dls.filter(t => daysTo(t.due) <= 183).slice(0, 8);
  const dlH = dls.length ? `<ul class="flist">${dls.map(t => { const n = daysTo(t.due); return `<li><a ${open(t.id)} class="frow">${ic((DL_TYPES.find(x => x[0] === t.fam.type) || DL_TYPES[5])[2], 's')}<span class="ft"><b>${esc(t.title)}</b><span class="muted">${esc(dlName(t.fam.type))}${t.fam.expires ? ' · ' + esc(tr('expires {0}', fmtDateLoc(t.fam.expires))) : ''}</span></span><span class="fwhen ${n < 0 ? 'over' : n <= 30 ? 'soon' : ''}">${esc(daysWord(n))}</span></a></li>`; }).join('')}</ul>`
    : `<p class="muted">${d.dls.length ? tr('Nothing due in the next six months.') : tr('Passport, car inspection, insurance: add a deadline and get reminded in time.')}</p>`;
  // kids
  const kidsH = d.kids.length ? d.kids.map(k => kidCardHtml(k)).join('') : '';
  const packH = `<div class="fpack">${PACK_UI.map(([k, n, e]) => `<button type="button" class="btn" data-act="fam-pack" data-k="${k}"><span aria-hidden="true">${e}</span> ${tr(n)}</button>`).join('')}</div>`;
  return `<div class="dash fam"><div class="dashhead fhead"><span class="spacer"></span>
    <button type="button" class="btn sm" data-act="fam-occ">${ic('cake', 's')}<span>${tr('Birthday')}</span></button>
    <button type="button" class="btn sm" data-act="fam-dl">${ic('hourglass', 's')}<span>${tr('Household deadline')}</span></button></div>
    <div class="dgrid">
    ${card('occ', 'cake', tr('Birthdays & anniversaries'), occH + `<div class="fcfoot"><button type="button" class="btn sm" data-act="fam-contacts">${ic('users', 's')}<span>${tr('From contacts…')}</span></button></div>`, '', d.occ.filter(t => daysTo(t.due) <= 30).length || '')}
    ${card('rot', 'turns', tr('Whose turn'), rotH, '', d.rots.length || '')}
    ${card('meals', 'meal', tr('Meal plan'), mealH, weekNav)}
    ${card('shop', 'cart', tr('Shopping'), shopH)}
    ${card('dl', 'hourglass', tr('Deadlines'), dlH, '', d.dls.filter(t => daysTo(t.due) <= 30).length || '')}
    ${kidsH ? card('kids', 'star', tr('Kids'), kidsH) : ''}
    ${card('pack', 'bag', tr('Packing lists'), packH)}
    </div></div>`;
}
const PACK_UI = [['holiday', N_('Holiday'), '🏖️'], ['pool', N_('Swimming pool'), '🏊'], ['daycare', N_('Daycare'), '🎒'], ['camping', N_('Camping'), '⛺'], ['business', N_('Business trip'), '💼']];

// ---- kids: a parent's card (stars, requests, give stars, rewards) and the kid's own view
function kidCardHtml(k) {
  const req = (k.rewards || []).filter(r => r.state === 'requested');
  return `<div class="kidc" data-kid="${k.id}"><div class="kidh">${av(k.id, k.display_name)}<b>${esc(k.display_name)}</b><span class="kstars" aria-label="${esc(trn('{0} star', '{0} stars', k.stars))}"><span aria-hidden="true">★</span> ${k.stars}</span><span class="spacer"></span>
    <button type="button" class="btn sm" data-act="fam-give" data-kid="${k.id}">${ic('plus', 's')}<span>${tr('Stars')}</span></button><button type="button" class="btn sm" data-act="fam-rewards" data-kid="${k.id}">${ic('gift', 's')}<span>${tr('Rewards')}</span></button></div>
    ${req.map(r => `<div class="kreq"><span class="kreqt">${esc(tr('{0} would like: {1}', k.display_name, (r.emoji ? r.emoji + ' ' : '') + r.title))} · ${r.cost} ★</span><span class="kreqb"><button type="button" class="btn sm" data-act="fam-decide" data-rid="${r.id}" data-ok="0">${tr('Not now')}</button><button type="button" class="btn sm pri" data-act="fam-decide" data-rid="${r.id}" data-ok="1">${ic('check', 's')}<span>${tr('Approve')}</span></button></span></div>`).join('')}</div>`;
}
// the kid's view: big buttons, only its own tasks (the server sends no others), its stars and the rewards
function viewKid() {
  const k = (S.kids || [])[0] || {stars: 0, rewards: []};
  const mine = [...S.tasks.values()].filter(t => !t.deleted_at && !t.parent_id && !t.context && (t.status === 0 || (t.completed_at && Date.now() - Date.parse(t.completed_at) < 864e5)))
    .sort((a, b) => a.status - b.status || (a.due || '9999').localeCompare(b.due || '9999') || a.id - b.id);
  const todo = mine.filter(t => t.status === 0);
  const hi = new Date().getHours();
  return `<div class="kidv"><div class="kidtop"><h2>${esc(hi < 11 ? tr('Good morning, {0}', S.me.display_name) : hi < 18 ? tr('Hello, {0}', S.me.display_name) : tr('Good evening, {0}', S.me.display_name))}</h2>
    <div class="kidbal" role="status" aria-label="${esc(trn('You have {0} star', 'You have {0} stars', k.stars))}"><span aria-hidden="true">★</span><b>${k.stars}</b></div></div>
    <h3 class="kidsec">${tr('My tasks')}</h3>
    ${mine.length ? `<ul class="kidtasks">${mine.map(t => `<li class="${t.status ? 'done' : ''}"><button type="button" class="kidchk" data-act="kid-tick" data-id="${t.id}" role="checkbox" aria-checked="${t.status === 2}" aria-label="${esc(tr('Done: {0}', t.title))}">${t.status ? ic('check') : ''}</button>
      <span class="kidt"><b>${esc(t.title)}</b>${t.due ? `<span class="muted">${esc(dayLabel(t.due))}${t.due_time ? ' ' + t.due_time : ''}</span>` : ''}</span><span class="kidst" aria-label="${esc(trn('{0} star', '{0} stars', t.stars ?? 1))}">${'★'.repeat(Math.min(5, t.stars ?? 1))}</span></li>`).join('')}</ul>`
      : heronEmpty('done', tr('Nothing to do right now.'), '')}
    ${todo.length || !mine.length ? '' : `<p class="kidyay">${tr('All done. Great job!')}</p>`}
    <h3 class="kidsec">${tr('Rewards')}</h3>
    ${(k.rewards || []).length ? `<ul class="kidrw">${k.rewards.map(r => `<li><span class="kre" aria-hidden="true">${esc(r.emoji || '🎁')}</span><span class="kidt"><b>${esc(r.title)}</b><span class="muted">${r.cost} ★</span></span>${r.state === 'requested' ? `<span class="kwait">${tr('Asked – waiting')}</span>` : r.state === 'redeemed' ? `<span class="muted">${tr('Redeemed')}</span>` : k.stars < r.cost ? `<span class="kneed">${esc(trn('{0} more star', '{0} more stars', r.cost - k.stars))}</span>` : `<button type="button" class="btn pri kidbtn" data-act="kid-want" data-rid="${r.id}">${tr('I want this')}</button>`}</li>`).join('')}</ul>`
      : `<p class="muted">${tr('No rewards yet: ask your parents.')}</p>`}</div>`;
}

// ---- dialogs
function occModal(o = {}) {
  const lists = S.lists.filter(l => !l.archived && canEditList(l.id) && !l.is_inbox);
  const bl = lists.find(l => l.family === 'birthdays');
  const months = [...Array(12)].map((_, i) => MON[i]);
  const md = modal(`<h3>${ic('cake', 's')} ${tr('Birthday or anniversary')}</h3>
    <div class="seg" id="oc-kind" role="radiogroup" aria-label="${esc(tr('Kind'))}"><button type="button" role="radio" aria-checked="true" class="on" data-k="birthday">${tr('Birthday')}</button><button type="button" role="radio" aria-checked="false" data-k="anniversary">${tr('Anniversary')}</button></div>
    <div class="row"><label for="oc-name">${tr('Who')}</label><input id="oc-name" maxlength="100" autocomplete="off" placeholder="${esc(tr('e.g. Grandma Erika'))}"></div>
    <div class="row"><label for="oc-day">${tr('Date')}</label><span class="ocdate"><input id="oc-day" type="number" inputmode="numeric" min="1" max="31" placeholder="${esc(tr('Day'))}" aria-label="${esc(tr('Day'))}"><select id="oc-month" aria-label="${esc(tr('Month'))}">${months.map((m, i) => `<option value="${i + 1}" ${i === new Date().getMonth() ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select><input id="oc-year" type="number" inputmode="numeric" min="1900" max="${new Date().getFullYear()}" placeholder="${esc(tr('Year'))}" aria-label="${esc(tr('Year (optional)'))}"></span></div>
    <div class="row"><label for="oc-lead">${tr('Remind me')}</label><select id="oc-lead">${[0, 1, 3, 7, 14, 30].map(n => `<option value="${n}" ${n === 7 ? 'selected' : ''}>${n ? trn('{0} day before', '{0} days before', n) : tr('on the day')}</option>`).join('')}</select></div>
    <div class="row"><label for="oc-gifts">${tr('Gift ideas')}</label><input id="oc-gifts" placeholder="${esc(tr('optional, separated by commas'))}"></div>
    ${lists.length > 1 || !bl ? `<div class="row"><label for="oc-list">${tr('List')}</label><select id="oc-list">${bl ? '' : `<option value="">${tr('New list: Birthdays')}</option>`}${lists.map(l => `<option value="${l.id}" ${l === bl ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>` : ''}
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
  const hl = lists.find(l => l.family === 'household');
  const md = modal(`<h3>${ic('hourglass', 's')} ${tr('Household deadline')}</h3>
    <div class="ptcards dltypes" role="radiogroup" aria-label="${esc(tr('Kind'))}">${DL_TYPES.map(([k, n, i], j) => `<button type="button" class="ptcard ${j ? '' : 'on'}" role="radio" aria-checked="${!j}" data-dl="${k}">${ic(i, 's')}<b>${tr(n)}</b></button>`).join('')}</div>
    <div class="row"><label for="dl-who" id="dl-wholab">${tr('For whom / what')}</label><input id="dl-who" maxlength="100" autocomplete="off" placeholder="${esc(tr('e.g. Lina, the family car, household insurance'))}"></div>
    <div class="row"><label id="dl-explab">${tr('Expires on')}</label>${dateIn('dl-exp', '', {label: tr('Expires on'), empty: tr('choose')})}</div>
    <div class="row dlnotice" hidden><label for="dl-notice">${tr('Notice period')}</label><select id="dl-notice">${[0, 1, 2, 3, 6, 12].map(n => `<option value="${n}">${n ? trn('{0} month', '{0} months', n) : tr('none')}</option>`).join('')}</select></div>
    <div class="shint lhint" id="dl-hint"></div>
    ${lists.length > 1 || !hl ? `<div class="row"><label for="dl-list">${tr('List')}</label><select id="dl-list">${hl ? '' : `<option value="">${tr('New list: Household')}</option>`}${lists.map(l => `<option value="${l.id}" ${l === hl ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>` : ''}
    <div class="aerr" role="alert" id="dl-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Add')}</button></div>`);
  md.classList.add('famdlg');
  let type = 'passport';
  const NOTICE = {insurance: 3, contract: 1};
  const hint = () => {
    $('.dlnotice', md).hidden = !(type in NOTICE);
    const lead = {passport: 90, id_card: 60, car: 30, insurance: 21, contract: 14, other: 14}[type];
    $('#dl-hint', md).textContent = [type in NOTICE ? tr('Due on the last day to cancel (the end minus the notice period).') : '', type === 'car' ? tr('Repeats every two years.') : type in NOTICE ? tr('Repeats every year.') : '',
      trn('Reminder {0} day before and on the day.', 'Reminder {0} days before and on the day.', lead), tr('Link the Paperless document in the task afterwards.')].filter(Boolean).join(' ');
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
async function famMeal(day) {
  const name = await askPrompt(tr('What is on {0}?', fmtDateLoc(day)), '', {ok: tr('Add'), input: {placeholder: tr('e.g. Lasagne'), max: 300}});
  if (!name || !name.trim()) return;
  let lid = famData().mealLists.find(l => canAddTo(l.id))?.id;
  if (!lid) lid = await famNewList('meals');
  if (!lid) return;
  const t = await createTask({title: name.trim(), list_id: lid, due: day}).catch(() => null);
  if (t) toast(tr('Added: {0}', t.title), () => openDetail(t.id), 6000, tr('Ingredients…'));
}
async function famIngredients(id) {
  const t = taskById(id); if (!t) return;
  let j; try { j = await api('POST', `/api/tasks/${id}/to-shopping`, {}); } catch { return; }
  await load(); render();
  const msg = [j.added.length ? trn('{0} item on the shopping list', '{0} items on the shopping list', j.added.length) : '', j.skipped.length ? trn('{0} was already there', '{0} were already there', j.skipped.length) : ''].filter(Boolean).join(' · ');
  toast(msg || tr('Nothing to add'), () => go('l/' + j.list_id), 6000, tr('Open'));
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
  const draw = () => { $('#rw-list', md).innerHTML = (k.rewards || []).length ? `<ul class="flist">${k.rewards.map(r => `<li class="frow"><span class="fem" aria-hidden="true">${esc(r.emoji || '🎁')}</span><span class="ft"><b>${esc(r.title)}</b><span class="muted">${r.cost} ★${r.once ? ' · ' + tr('only once') : ''}${r.state === 'requested' ? ' · ' + tr('asked for') : r.state === 'redeemed' ? ' · ' + tr('redeemed') : ''}</span></span>${r.state === 'redeemed' ? '' : k.stars < r.cost ? `<span class="muted kneed">${esc(trn('{0} more star', '{0} more stars', r.cost - k.stars))}</span>` : `<button type="button" class="btn sm" data-redeem="${r.id}" title="${esc(tr('Redeem now: the stars are taken'))}">${tr('Redeem')}</button>`}<button type="button" class="iconbtn" data-rdel="${r.id}" aria-label="${esc(tr('Delete {0}', r.title))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('No rewards yet.')}</p>`; };
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
  const bl = lists.find(l => l.family === 'birthdays');
  const md = modal(`<h3>${ic('users', 's')} ${tr('Birthdays from your contacts')}</h3>
    <p class="muted">${tr('Kalmido reads the birthdays and anniversaries of an address book (CardDAV: Nextcloud, iCloud, Radicale, mailbox.org …) once a day and adds them as yearly tasks. Nothing is written back. The password is stored encrypted.')}</p>
    <div id="ct-list"><div class="muted">${tr('Loading…')}</div></div>
    <h4>${tr('Add an address book')}</h4>
    <div class="row"><label for="ct-url">${tr('Server address')}</label><input id="ct-url" type="url" inputmode="url" autocapitalize="off" placeholder="https://…"></div>
    <div class="row"><label for="ct-user">${tr('Username')}</label><input id="ct-user" autocapitalize="off" autocomplete="off"></div>
    <div class="row"><label for="ct-pw">${tr('Password')}</label><input id="ct-pw" type="password" autocomplete="new-password" placeholder="${esc(tr('an app password, if the server offers one'))}"></div>
    <div class="row"><label for="ct-list-sel">${tr('List')}</label><select id="ct-list-sel">${bl ? '' : `<option value="">${tr('New list: Birthdays')}</option>`}${lists.map(l => `<option value="${l.id}" ${l === bl ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>
    <div class="aerr" role="alert" id="ct-err"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button><button class="btn pri" data-m="add">${ic('plus', 's')} ${tr('Connect')}</button></div>`);
  md.classList.add('famdlg');
  const draw = j => { $('#ct-list', md).innerHTML = j.sources.length ? `<ul class="flist">${j.sources.map(s => `<li class="frow"><span class="ft"><b>${esc(s.name)}</b><span class="muted">${esc(s.url_hint)} · ${s.status === 'error' ? esc(s.error_text) : esc(trn('{0} date', '{0} dates', s.count))}${s.synced_at ? ' · ' + esc(tr('read {0}', fmtAgo(s.synced_at))) : ''}</span></span><button type="button" class="btn sm" data-ctsync="${s.id}">${ic('sync', 's')}<span>${tr('Read now')}</span></button><button type="button" class="iconbtn" data-ctdel="${s.id}" aria-label="${esc(tr('Remove {0}', s.name))}" title="${esc(tr('Remove'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('No address book connected.')}</p>`; };
  const reload = async () => { try { draw(await api('GET', '/api/family/contacts')); } catch { /* offline */ } };
  reload();
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
const fmtAgo = iso => { const m = Math.round((Date.now() - Date.parse(iso)) / 60000); return m < 1 ? tr('just now') : m < 60 ? trn('{0} min ago', '{0} min ago', m) : m < 1440 ? trn('{0} h ago', '{0} h ago', Math.round(m / 60)) : fmtDateLoc(iso.slice(0, 10)); };

// ---- the task panel: the family section (birthday / deadline data, taking turns, who comes along, stars, ingredients)
function famDetailHtml(t, l, ro) {
  if (!famOn() || !t || t.id <= 0 || t.context) return '';
  const out = [], ppl = listPeople(l).filter(p => !p.agent && !(l.members || []).find(m => m.user_id === p.user_id && m.agent));
  const shared = !!l?.shared && collab();
  if (isOcc(t)) {
    const w = occWhat(t);
    out.push(`<div class="row"><label for="d-fname">${t.fam.kind === 'birthday' ? tr('Birthday of') : tr('Anniversary of')}</label><input id="d-fname" value="${esc(t.fam.name || '')}" maxlength="100" ${ro ? 'readonly' : ''}></div>
      <div class="row"><label for="d-fyear">${t.fam.kind === 'birthday' ? tr('Year of birth') : tr('Since')}</label><input id="d-fyear" class="numin" type="number" inputmode="numeric" min="1900" max="${new Date().getFullYear()}" value="${esc(t.fam.year || '')}" ${ro ? 'readonly' : ''}>${w ? `<span class="fage">${esc(w)}${t.due ? ' · ' + esc(fmtDateLoc(t.due)) : ''}</span>` : ''}</div>`);
  }
  if (isDl(t)) {
    out.push(`<div class="row"><label>${tr('Household deadline')}</label><span class="muted">${esc(dlName(t.fam.type))}${t.fam.who ? ' · ' + esc(t.fam.who) : ''}</span></div>
      <div class="row"><label>${t.fam.notice ? tr('Ends on') : tr('Expires on')}</label>${ro ? `<span>${esc(fmtDateLoc(t.fam.expires || ''))}</span>` : dateIn('d-fexp', t.fam.expires || '', {label: t.fam.notice ? tr('Ends on') : tr('Expires on'), clear: false})}${t.fam.notice ? `<span class="muted">${esc(trn('notice period {0} month', 'notice period {0} months', t.fam.notice))}</span>` : ''}</div>`);
  }
  if (shared && (t.rotation || (t.repeat && !t.fam))) {  // taking turns: only repeating tasks of shared lists (not a birthday / deadline)
    const r = t.rotation, on = !!r, who = new Set(r?.who || []);
    out.push(`<div class="row frot"><label>${tr('Take turns')}</label><label class="swc"><input type="checkbox" id="d-rot" ${on ? 'checked' : ''} ${ro || !canEditList(t.list_id) ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Take turns'))}</span></label>${on ? `<span class="muted">${esc(rotOrder(t))}</span>` : ''}</div>
      ${on ? `<div class="row"><label>${tr('Who')}</label><div class="fpeople" role="group" aria-label="${esc(tr('Who takes turns'))}">${ppl.map(p => `<button type="button" class="fperson ${who.has(p.user_id) ? 'on' : ''}" data-rotp="${p.user_id}" aria-pressed="${who.has(p.user_id)}" ${ro ? 'disabled' : ''}>${av(p.user_id, p.name)}<span>${esc(p.name)}</span></button>`).join('')}</div></div>
      <div class="row"><label>${tr('Next person')}</label><div class="seg" role="radiogroup" aria-label="${esc(tr('Next person'))}"><button type="button" role="radio" data-rotm="done" class="${r.mode !== 'week' ? 'on' : ''}" aria-checked="${r.mode !== 'week'}" ${ro ? 'disabled' : ''}>${tr('after each time')}</button><button type="button" role="radio" data-rotm="week" class="${r.mode === 'week' ? 'on' : ''}" aria-checked="${r.mode === 'week'}" ${ro ? 'disabled' : ''}>${tr('every week')}</button></div></div>` : ''}`);
  }
  if (shared && ppl.length > 1) {  // who comes along (family events)
    const pp = new Set(t.people || []);
    out.push(`<div class="row"><label>${tr('Who comes along')}</label><div class="fpeople" role="group" aria-label="${esc(tr('Who comes along'))}">${ppl.map(p => `<button type="button" class="fperson ${pp.has(p.user_id) ? 'on' : ''}" data-famp="${p.user_id}" aria-pressed="${pp.has(p.user_id)}" ${ro || !canEditList(t.list_id) ? 'disabled' : ''}>${av(p.user_id, p.name)}<span>${esc(p.name)}</span></button>`).join('')}</div></div>`);
  }
  const kidIn = (l?.members || []).some(m => S.kidIds?.has(m.user_id));
  if ((kidIn && !t.fam) || t.stars != null) {
    out.push(`<div class="row"><label for="d-stars">${tr('Stars for a child')}</label><input id="d-stars" class="numin" type="number" inputmode="numeric" min="0" max="50" value="${esc(t.stars ?? '')}" placeholder="1" ${ro || !canEditList(t.list_id) ? 'readonly' : ''}><span class="muted">★</span></div>`);
  }
  if (famKindOf(t.list_id) === 'meals' && !t.parent_id) {
    out.push(`<div class="row"><label>${tr('Ingredients')}</label><button type="button" class="btn sm" data-act="fam-ingr" data-id="${t.id}">${ic('cart', 's')}<span>${tr('To the shopping list')}</span></button><span class="muted">${tr('one per line in the description')}</span></div>`);
  }
  return out.length ? `<div class="dsec famsec"><h5>${tr('Family')}</h5><div class="famf">${out.join('')}</div></div>` : '';
}
async function famDetailPatch(t, body) { try { await patchUndoable(t.id, body); } catch { renderDetail(); } }
document.addEventListener('change', e => {
  const el = e.target; if (!el.closest?.('#detail .famsec')) return;
  const t = taskById(S.sel); if (!t) return;
  if (el.id === 'd-fname' || el.id === 'd-fyear') { const v = el.value.trim(); famDetailPatch(t, {fam: {...t.fam, ...(el.id === 'd-fname' ? {name: v} : {year: v ? +v : null})}}); }
  if (el.id === 'd-fexp' && el.value) famDetailPatch(t, {fam: {...t.fam, expires: el.value}});
  if (el.id === 'd-stars') famDetailPatch(t, {stars: el.value === '' ? null : +el.value});
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
async function shopPoll() {
  if (!S.shop || document.hidden || OUT.q.length || imeOn) return;  // the add field keeps its text and focus through a redraw
  try { const {v} = await api('GET', '/api/version'); if (v !== S.v) { await load(); shopDraw(); } } catch { /* offline: the ticks wait in the queue */ }
}
function shopDraw() {
  const ov = $('.shopmode'); if (!ov || !S.shop) return;
  const l = listById(S.shop.lid); if (!l) { ov.remove(); return; }
  const items = [...S.tasks.values()].filter(t => t.list_id === l.id && !t.deleted_at && !t.parent_id);
  const open = items.filter(t => t.status === 0), done = items.filter(t => t.status !== 0).sort((a, b) => (b.completed_at || '').localeCompare(a.completed_at || ''));
  const secs = S.sections.filter(s => s.list_id === l.id).sort((a, b) => a.sort - b.sort || a.id - b.id);
  const ro = !canAddTo(l.id);
  const row = t => `<li class="shopi ${t.status ? 'done' : ''}"><button type="button" class="shopchk" data-act="shop-tick" data-id="${t.id}" role="checkbox" aria-checked="${t.status !== 0}" aria-label="${esc(t.title)}" ${canEdit(t) ? '' : 'disabled'}>${t.status ? ic('check') : ''}</button><span class="shopt">${esc(t.title)}</span>${!t.status && secs.length && canEditList(l.id) ? `<button type="button" class="iconbtn shoparea" data-act="shop-area" data-id="${t.id}" aria-haspopup="menu" title="${esc(tr('Shop area'))}" aria-label="${esc(tr('Shop area of {0}', t.title))}">${ic('columns', 's')}</button>` : ''}</li>`;
  const groups = [...secs.map(s => [s.name, open.filter(t => t.section_id === s.id)]), [tr('Other'), open.filter(t => !t.section_id || !secs.some(s => s.id === t.section_id))]].filter(g => g[1].length);
  const focusId = document.activeElement?.closest?.('.shopmode') ? (document.activeElement.dataset.id ? `[data-act="${document.activeElement.dataset.act}"][data-id="${document.activeElement.dataset.id}"]` : document.activeElement.id ? '#' + document.activeElement.id : '') : '';
  const val = $('#shop-in', ov)?.value || '';
  $('.shopcard', ov).innerHTML = `<div class="shophead"><h2 id="shop-h">${ic('cart', 's')}<span>${esc(lname(l))}</span></h2><span class="shopn" role="status">${esc(open.length ? trn('{0} left', '{0} left', open.length) : tr('Everything in the cart'))}</span><span class="spacer"></span><button type="button" class="iconbtn shopx" data-act="shop-close" aria-label="${esc(tr('End shopping mode'))}" title="${esc(tr('End shopping mode'))}">${ic('x')}</button></div>
    ${ro ? '' : `<form class="shopadd" data-shopadd><input id="shop-in" autocomplete="off" enterkeyhint="done" placeholder="${esc(tr('Add an item'))}" aria-label="${esc(tr('Add an item'))}"><button type="submit" class="btn pri" aria-label="${esc(tr('Add'))}">${ic('plus', 's')}</button></form>`}
    <div class="shopbody">${groups.map(([n, ts]) => `<section class="shopg"><h3>${esc(n)} <span class="c">${ts.length}</span></h3><ul>${ts.map(row).join('')}</ul></section>`).join('') || (items.length ? '' : `<p class="muted">${tr('The list is empty.')}</p>`)}
    ${done.length ? `<section class="shopg shopdone"><h3>${tr('In the cart')} <span class="c">${done.length}</span></h3><ul>${done.map(row).join('')}</ul></section>` : ''}</div>`;
  if ($('#shop-in', ov)) $('#shop-in', ov).value = val;
  if (focusId) { const f = $(focusId, ov); if (f) f.focus({preventScroll: true}); }
}
document.addEventListener('submit', async e => {
  if (!e.target.matches?.('[data-shopadd]')) return;
  e.preventDefault();
  const inp = $('#shop-in'), v = inp?.value.trim(); if (!v || !S.shop) return;
  inp.value = '';
  try { await createTask({title: v, list_id: S.shop.lid}); await load(); } catch { /* api() said it */ }
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
  else if (k === 'fam-shop' || k === 'shop-start') shopModeOpen(id || +a.dataset.lid);
  else if (k === 'fam-areas') { try { const j = await api('POST', `/api/lists/${a.dataset.lid}/shop-areas`, {}); await load(); render(); toast(trn('{0} shop area added', '{0} shop areas added', j.added)); } catch { /* api() said it */ } }
  else if (k === 'fam-give') famGive(+a.dataset.kid);
  else if (k === 'fam-rewards') rewardsModal(+a.dataset.kid);
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
  if (l.family === 'meals') return `<div class="fambar"><a class="btn" href="#family">${ic('meal', 's')}<span>${tr('Week plan')}</span></a><span class="muted">${tr('A meal per day, the ingredients in its description.')}</span></div>`;
  if (l.family === 'birthdays') return `<div class="fambar"><button type="button" class="btn" data-act="fam-occ">${ic('cake', 's')}<span>${tr('Birthday')}</span></button><button type="button" class="btn" data-act="fam-contacts">${ic('users', 's')}<span>${tr('From contacts…')}</span></button></div>`;
  if (l.family === 'household') return `<div class="fambar"><button type="button" class="btn" data-act="fam-dl">${ic('hourglass', 's')}<span>${tr('Household deadline')}</span></button><a class="btn" href="#family">${ic('family', 's')}<span>${tr('Family')}</span></a></div>`;
  return '';
}

// ---- "What do you use Kalmido for?" (setup, welcome tour, Settings > Modules)
const purposeCards = (cur, attr = 'data-purpose') => `<div class="ptcards purposes" role="radiogroup" aria-label="${esc(tr('What do you use Kalmido for?'))}">${PURPOSES.map(([k, i, n, d]) => `<button type="button" class="ptcard ${k === cur ? 'on' : ''}" role="radio" aria-checked="${k === cur}" ${attr}="${k}">${ic(i, 's')}<b>${tr(n)}</b><small class="muted">${tr(d)}</small></button>`).join('')}</div>`;
async function purposeSet(p) {
  const n = PURPOSES.find(x => x[0] === p);
  // 2.25.0 (UX-25): the dialog lists what changes (modules on / off, tabs that leave the tab bar)
  const want = new Set(PURPOSE_MODS[p] || []), mname = k => tr(FEATS.find(x => x[0] === k)?.[1] || k);
  const ton = PURPOSE_ALL.filter(k => want.has(k) && !feat(k)), toff = PURPOSE_ALL.filter(k => !want.has(k) && feat(k));
  const tabs = tabIds().filter(id => id.startsWith('m:') && toff.includes(id.slice(2))).map(id => mname(id.slice(2)));
  const chg = `<ul class="cdlg-l">${ton.length ? `<li>${esc(tr('On: {0}', ton.map(mname).join(', ')))}</li>` : ''}${toff.length ? `<li>${esc(tr('Off: {0}', toff.map(mname).join(', ')))}</li>` : ''}${tabs.length ? `<li>${esc(tr('Leaves the tab bar: {0}', tabs.join(', ')))}</li>` : ''}${!ton.length && !toff.length ? `<li>${esc(tr('No module changes.'))}</li>` : ''}</ul>`;
  const once = p === 'family' && !S.lists.some(l => l.family) ? tr('A shopping list, household chores, birthdays and a meal plan are created once (in the folder Family).') : p === 'software' ? tr('A software project is created once.') : p === 'team' ? tr('The sample project is created once.') : '';
  if (!await askConfirm(tr('Switch to “{0}”?', tr(n[2])), '', {ok: tr('Set up'), html: `<p>${esc(tr('Your modules are switched to fit; nothing is deleted and everything can be changed again below.'))}</p>${chg}${once ? `<p>${esc(once)}</p>` : ''}`})) return false;
  let j; try { j = await api('POST', '/api/me/purpose', {purpose: p}); } catch { return false; }
  S.settings.features = j.features; S.settings.purpose = p;
  await load(); render();
  toast(j.created?.length ? trn('Done: {0} list created', 'Done: {0} lists created', j.created.length) : tr('Done'));
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
document.addEventListener('click', async e => {
  const b = e.target.closest?.('.smodal [data-purpose]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  if (!await purposeSet(b.dataset.purpose)) return;
  const md = $('.smodal'); if (md) { md._noflush = true; md.remove(); settingsModal('modules'); setTimeout(() => $(`.smodal [data-purpose="${b.dataset.purpose}"]`)?.focus(), 80); }
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
