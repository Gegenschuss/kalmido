// @ts-check
/* Kalmido web client: "My tasks" as a board (2.156.0 C, #2072), module "mineboard" (lazyload.js, loaded on its first draw).
   The same tasks as the list (mineorder.js moAll: assigned to me / my groups, hidden lists only when due today or overdue) in
   columns by due date (Overdue / Today / This week / Later / No date, the default), priority or list; the cards are the
   Kanban cards (taskRow compact), phones swipe the columns like the Kanban board (.kanban). Dropping a card on a column sets
   what the column means: the date (Today = today, This week = tomorrow, Later = the next week's first day, No date = none;
   Overdue takes nothing), the priority or the list (only a list I may write; a subtask there becomes standalone).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const MB_PRIOS = [{p: 5, n: N_('High')}, {p: 3, n: N_('Medium')}, {p: 1, n: N_('Low')}, {p: 0, n: N_('None')}];
const mb_weekEnd = t0 => addDays(weekStartOf(t0), 6);
const mb_byDue = (a, b) => (a.due || '9999').localeCompare(b.due || '9999') || (a.due_time || '99').localeCompare(b.due_time || '99') || moCmp(a, b);

function mb_cols(by, tasks) {
  if (by === 'prio') return MB_PRIOS.map(({p, n}) => ({key: 'p' + p, name: tr(n), tasks: tasks.filter(t => (t.priority || 0) === p).sort(mb_byDue), lock: false, lic: null}));
  if (by === 'list') {
    const g = new Map();
    for (const t of tasks) { if (!g.has(t.list_id)) g.set(t.list_id, []); g.get(t.list_id).push(t); }
    return kbListOrder().filter(l => g.has(l.id)).map(l => ({key: 'l' + l.id, name: lname(l), lic: l, tasks: g.get(l.id).sort(mb_byDue), lock: !canEditList(l.id)}));
  }
  const t0 = today(), we = mb_weekEnd(t0), tm = addDays(t0, 1);
  const cols = [
    {key: 'over', name: tr('Overdue'), tasks: tasks.filter(t => t.due && t.due < t0), lock: true, lic: null},
    {key: 'today', name: tr('Today'), tasks: tasks.filter(t => t.due === t0), lock: false, lic: null},
    {key: 'week', name: tr('This week'), tasks: tasks.filter(t => t.due && t.due > t0 && t.due <= we), lock: tm > we, lic: null},
    {key: 'later', name: tr('Later'), tasks: tasks.filter(t => t.due && t.due > we), lock: false, lic: null},
    {key: 'none', name: tr('No date'), tasks: tasks.filter(t => !t.due), lock: false, lic: null}];
  for (const c of cols) c.tasks.sort(mb_byDue);
  return cols.filter(c => c.tasks.length || (c.key !== 'over' && !(c.key === 'week' && c.lock)));
}

function mb_view() {
  const by = moBoardBy(), t0 = today(), tasks = moAll().filter(t => mtCounts(t, t0)), cols = mb_cols(by, tasks);
  const card = t => taskRow(t, {compact: true, showList: by !== 'list'});
  const head = c => `<div class="khead">${c.lic ? licMark(c.lic, 'lsm') : ''}<span class="mbname">${esc(c.name)}</span> <span class="muted mbn">${c.tasks.length}</span>${c.lock && by === 'list' ? `<span class="mblk" title="${esc(tr('View only'))}" aria-label="${esc(tr('View only'))}">${ic('lock', 's')}</span>` : ''}</div>`;
  const empty = tasks.length ? '' : `<p class="muted lempty">${esc(tr('Nothing here'))}</p>`;
  return `${moSegHtml()}${empty}<div class="kanban mboard" data-mbby="${by}">${cols.map(c => `
    <div class="kcol mbcol${c.lock ? ' mblock' : ''}" data-mbcol="${esc(c.key)}" role="group" aria-label="${esc(c.name)}">
      ${head(c)}
      <div class="kcards">${c.tasks.map(card).join('')}</div>
    </div>`).join('')}</div>`;
}

// dnd.js dropTask0 (through mineorder.js mbDropHook): true = handled here (also when nothing changes)
async function mb_drop(t, el) {
  const col = el.closest?.('#view .mboard .mbcol'); if (!col) return false;  // elsewhere (the sidebar's lists, Today ...): as before
  const key = col.dataset.mbcol || '', by = moBoardBy();
  if (by === 'prio') {
    const p = +key.slice(1);
    if ((t.priority || 0) === p) return true;
    if (tlkHits(t, {priority: p})) { tlkToast(t); render(); return true; }
    await patchUndoable(t.id, {priority: p}, tr('Priority: {0}', tr((MB_PRIOS.find(x => x.p === p) || MB_PRIOS[3]).n))).catch(() => {});
    return true;
  }
  if (by === 'list') {
    const lid = +key.slice(1);
    if (!lid || lid === t.list_id) return true;
    if (!canEditList(lid)) { roToast(); return true; }
    if (tlkHits(t, {list_id: lid})) { tlkToast(t); render(); return true; }
    await patchUndoable(t.id, {list_id: lid, section_id: null, ...(t.parent_id ? {parent_id: null} : {})}, t.parent_id ? tr('Standalone in {0}', lname(listById(lid))) : tr('Moved to {0}', lname(listById(lid)))).catch(() => {});
    return true;
  }
  const t0 = today(), we = mb_weekEnd(t0), tm = addDays(t0, 1);
  const due = {today: t0, week: tm <= we ? tm : undefined, later: addDays(we, 1), none: null}[key];
  if (due === undefined) { toast(tr('Pick a day in the task')); return true; }  // Overdue (and This week on its last day) take nothing
  const cur = mb_cols('due', [t]).find(c => c.tasks.length)?.key;
  if (cur === key) return true;
  const body = due ? {due} : {due: null, due_time: null};
  if (tlkHits(t, body)) { tlkToast(t); render(); return true; }
  await patchUndoable(t.id, body, due ? tr('Date: {0}', dayLabel(due)) : tr('No date')).catch(() => {});
  return true;
}
