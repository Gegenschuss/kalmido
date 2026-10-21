// @ts-check
/* Kalmido web client: the calendar view of one list (2.156.0 C, #2071), part of the module "calendar" (lazyload.js).
   The list's view "Calendar" (lists.view = calendar, stored like Kanban / Timeline) shows the global calendar's month / week /
   day / agenda with only this list's tasks (due date; linked tasks too), no events of calendars and no other servers.
   The calendar's own parts do the work: calByDay filters by S.lcal (calendar.js), dragging a task onto a day sets its date
   (dnd.js), a tap on a day picks it and the add box below creates the task in this list on that day (quickDefaults).
   The mode is shared with the global calendar (S.calMode); its year / timeline modes show the month here.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const LCAL_MODES = ['month', 'week', 'day', 'agenda'];
// the msvview.js parts the calendar draws for other servers: not in a list's calendar (swapped while it draws)
const LCAL_MSV = {msvvCalChips: () => [], msvvCalDay: () => '', msvvCalEnsure: () => ''};

function lcal_view(l) {
  if (!l) return '';
  if (!LCAL_MODES.includes(S.calMode)) S.calMode = 'month';
  if (!S.calSel) S.calSel = today();
  if (!S.calMonth) S.calMonth = S.calSel.slice(0, 7);
  const W = /** @type {any} */ (window), keep = {};
  for (const k of Object.keys(LCAL_MSV)) { keep[k] = W[k]; W[k] = LCAL_MSV[k]; }
  S.lcal = l.id;
  let h = '';
  try { h = S.calMode === 'agenda' ? viewAgenda() : viewCal(); }
  finally { S.lcal = 0; for (const k of Object.keys(keep)) W[k] = keep[k]; }
  return `${vsegHtml(l)}<div class="lcal" data-lcal="${l.id}">${h}</div>`;
}
// calendar.js calBar while a list's calendar draws: the four modes, "Completed" and the period arrows (no events, calendars)
function lcal_bar(title, done = true) {
  const on = showDoneCal();
  const dn = done ? `<button class="btn sm chip ${on ? 'on' : ''}" data-act="cal-done" aria-pressed="${on}" aria-label="${esc(tr('Completed'))}" title="${esc(on ? tr('Hide completed') : tr('Show completed'))}">${ic('eye', 's')}<span class="cdl">${tr('Completed')}</span></button>` : '';
  const modes = [['month', N_('Month')], ['week', N_('Week')], ['day', N_('Day')], ['agenda', N_('Agenda')]];
  return `<div class="calbar"><h2>${title}</h2><div class="seg" role="group" aria-label="${esc(tr('Calendar'))}">${modes.map(([k, n]) => `<button class="${S.calMode === k ? 'on' : ''}" data-act="cal-mode" data-k="${k}" aria-pressed="${S.calMode === k}">${tr(n)}</button>`).join('')}</div>${dn}
    <div class="calnav"><button class="iconbtn" data-act="cal-prev" title="${esc(tr('Previous period'))}" aria-label="${esc(tr('Previous period'))}">${ic('left')}</button><button class="btn sm" data-act="cal-today">${tr('Today')}</button><button class="iconbtn" data-act="cal-next" title="${esc(tr('Next period'))}" aria-label="${esc(tr('Next period'))}">${ic('right')}</button></div></div>`;
}
