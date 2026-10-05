/* Kalmido web client: Which tasks a view shows (smart lists, filters, sorting, grouping).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ view selection
function viewTasks() {
  const k = S.route.key, t0 = today();
  const open = openTasks(true);
  // completed tasks from the last 14 days stay visible (collapsed) in list views
  const doneRecent = [...S.tasks.values()].filter(t => t.status !== 0 && !t.parent_id && !archHidden(t) && !t.context);
  const doneSince = t => t.completed_at && t.completed_at.slice(0, 10) >= addDays(t0, -1);  // date views: done since yesterday
  // roots = matching tasks whose parent does not match too (a subtask due today shows up in "Heute"
  // even if its parent does not); children are rendered below their root
  const pick = (pred, group, extra = {}) => {
    const m = open.filter(t => (!t.context || extra.list) && pred(t)), ids = new Set(m.map(t => t.id));
    return {open: m.filter(t => !t.parent_id || !ids.has(t.parent_id)), group, ...extra};
  };
  // 1.5.1: every view has its own "Show completed" (list "…" menu), so every view offers its completed tasks
  if (k === 'today') return {...pick(t => ((t.due && t.due <= t0) || dlToday(t) || planToday(t, t0)) && !(t.blocked && hideBlockedToday()), 'date'), done: doneRecent.filter(t => t.due && t.due <= t0 && doneSince(t))};  // 2.7.0 (#412): deadlines from their first reminder
  if (k === 'tomorrow') return {...pick(t => t.due === addDays(t0, 1), 'none'), done: doneRecent.filter(t => t.due === addDays(t0, 1))};
  if (k === 'week') return {...pick(t => t.due && t.due <= addDays(t0, 6), 'date'), done: doneRecent.filter(t => t.due && t.due <= addDays(t0, 6) && doneSince(t))};
  if (k === 'doable') return {...pick(t => doable(t, t0), 'none'), done: doneRecent.filter(t => doneSince(t) && mineTask(t) && !(t.due && t.due > t0))};
  if (k === 'waiting') return {...pick(t => !!t.waiting_at, 'list'), done: []};  // 2.1.0 (#335)
  if (k === 'pinned') return {...pick(t => !!t.pinned, 'list'), done: []};  // 2.16.0 (#648): grouped by list
  if (k === 'all') return {...pick(() => true, 'list'), done: doneRecent};
  if (k === 'assigned') return {...pick(mineAssigned, 'list'), done: doneRecent.filter(t => !!S.me && t.assignee_id === S.me.id)};  // 2.10.0: + my groups' tasks
  if (k.startsWith('grp:')) {  // 2.10.0 (#441): open tasks assigned to a group, in the lists I see
    const gid = +k.slice(4);
    return {...pick(t => t.assignee_group_id === gid, 'list'), done: []};
  }
  if (k === 'inbox' || k.startsWith('l:')) {
    const lid = k === 'inbox' ? inbox().id : +k.slice(2);
    return {...pick(t => t.list_id === lid, 'section', {list: lid}), done: doneRecent.filter(t => t.list_id === lid)};
  }
  if (k.startsWith('who:')) {  // 2.7.2 (#418): open tasks assigned to one person, in the lists I see
    const id = +k.slice(4);
    return {...pick(t => t.assignee_id === id, 'list'), done: doneRecent.filter(t => t.assignee_id === id)};
  }
  if (k.startsWith('tag:')) {
    const tg = k.slice(4);
    return {...pick(t => hasTag(t, tg), 'list'), done: doneRecent.filter(t => hasTag(t, tg))};
  }
  if (k.startsWith('folder:')) {
    const ids = new Set(folderLists(k.slice(7)).map(l => l.id));
    return {...pick(t => ids.has(t.list_id), 'list', {folder: k.slice(7)}), done: doneRecent.filter(t => ids.has(t.list_id))};
  }
  if (k.startsWith('f:')) {
    const f = S.filters.find(x => x.id === +k.slice(2));
    return f ? {...pick(t => filterMatch(t, f.rules), 'date'), done: doneRecent.filter(t => filterMatch(t, f.rules))} : {open: [], done: [], group: 'none'};
  }
  return {open: [], done: [], group: 'none'};
}
// 1.7.0 "Now doable": open, not waiting on an open task, due today / overdue or undated, not starting later, and mine:
// assigned to me, or unassigned in a list I own (private lists included); with collaboration off every task is mine
function mineTask(t) {
  if (!collab()) return true;
  if (t.assignee_id) return !!S.me && t.assignee_id === S.me.id;
  if (t.assignee_group_id) return myGroup(t.assignee_group_id);  // 2.10.0 (#441): my group's tasks are mine until someone takes one
  return isOwner(listById(t.list_id));
}
// 2.10.0 (#441): "Assigned to me" = assigned to me or to one of my groups
const mineAssigned = t => !!S.me && (t.assignee_id === S.me.id || myGroup(t.assignee_group_id));
// a subtask without its own due date follows its open parent (an undated step of a later task is not doable yet)
// 2.11.0: the day plan's slot of an open task (plan_start "YYYY-MM-DDTHH:MM") from today on, else null
const planToday = (t, t0 = today()) => (t.plan_start || '').slice(0, 10) === t0;  // 2.11.0: Today also shows the day plan's tasks
const planOf = t => t.status === 0 && /^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(t.plan_start || '') && t.plan_start.slice(0, 10) >= today() ? t.plan_start : null;
const planLabel = (t, short) => { const p = planOf(t); if (!p) return ''; const d = p.slice(0, 10), hm = fmtTimeLoc(p.slice(11)), e = t.duration ? fmtTimeLoc(dpHm(Math.min(1439, dpMin(p.slice(11)) + t.duration))) : '';
  return (d === today() ? '' : dayLabel(d) + ' ') + hm + (e && !short ? '–' + e : ''); };
function doable(t, t0 = today()) {
  if (t.status === 0 && planToday(t, t0) && mineTask(t) && !(t.blocked && dFor(t))) return true;  // 2.11.0: planned for today
  if (!(t.status === 0 && !(t.blocked && dFor(t)) && (!t.due || t.due <= t0) && !(t.start && t.start > t0) && mineTask(t))) return false;
  const p = t.parent_id && !t.due ? S.tasks.get(t.parent_id) : null;
  return !(p && p.status === 0 && !doable(p, t0));
}
// 2.11.0 (#439): a language in the pickers; machine-translated ones carry a "Beta" mark (_meta.beta in their file)
const langName = L => esc(L.name) + (L.beta ? ` <span class="lbeta" title="${esc(tr('Machine-translated, corrections welcome'))}">${tr('Beta')}</span>` : '');
const DATE_OPTS = [['overdue', N_('Overdue')], ['today', N_('Today')], ['tomorrow', N_('Tomorrow')], ['3d', N_('Next 3 days')], ['7d', N_('Next 7 days')], ['month', N_('This month')], ['later', N_('Later')], ['nodate', N_('No date')]];
function dateMatch(t, d) {
  const t0 = today();
  if (d === 'nodate') return !t.due;
  if (!t.due) return false;
  switch (d) {
    case 'overdue': return t.due < t0;
    case 'today': return t.due === t0;
    case 'tomorrow': return t.due === addDays(t0, 1);
    case '3d': return t.due >= t0 && t.due <= addDays(t0, 2);
    case '7d': return t.due >= t0 && t.due <= addDays(t0, 6);
    case 'month': return t.due.slice(0, 7) === t0.slice(0, 7);
    case 'later': return t.due > addDays(t0, 6);
  }
  return false;
}
// categories are OR-ed inside ("Heute oder Morgen"), combined with the filter's op (UND / ODER)
function filterMatch(t, r = {}) {
  const c = [];
  if (r.lists?.length) c.push(r.lists.includes(t.list_id));
  if (r.dates?.length) c.push(r.dates.some(d => dateMatch(t, d)));
  if (r.prios?.length) c.push(r.prios.includes(t.priority));
  if (r.types?.length) c.push(r.types.includes(t.ttype || ''));  // 2.4.0 (#340): '' = no type
  if (r.tags?.length) c.push(r.tags.some(g => hasTag(t, g)));
  for (const [fid, cr] of Object.entries(r.cf || {})) if (cfRuleOn(cr) && fieldById(+fid)) c.push(cfMatch(t, fid, cr));
  if (!c.length) return true;
  return r.op === 'or' ? c.some(Boolean) : c.every(Boolean);
}
// 1.5.1: "Show completed" per view (list, filter, smart list, tag), per user and synced (setting show_done_views, a json
// map route key -> 0/1; not shared with the other members of a shared list). 1.8.1: no global switch any more, a view
// without its own choice shows its completed tasks; the calendar has its own entry "cal" (toggle in its bar)
function doneViews() { try { const o = JSON.parse(S.settings.show_done_views || '{}'); return o && typeof o === 'object' && !Array.isArray(o) ? o : {}; } catch { return {}; } }
const showDone = (key = S.route.key) => { const v = doneViews()[key]; return v === undefined ? true : !!+v; };
const showDoneCal = () => showDone('cal');
// the views that have a "Completed" group (and so the toggle)
const doneToggleView = () => { const k = S.route.key, l = routeList(); return S.route.mod === 'tasks' && !NOLIST_KEYS.includes(k) && !isKanban() && !isTimeline() && !isRoadmap() && !isOverview() && !(l && l.checklist); };  // 2.7.2 (#414): "Show completed at the bottom" has its own group
async function setShowDone(on, key = S.route.key) {
  const was = doneViews()[key], to = on ? 1 : 0;
  const put = async v => {  // only this view's entry changes: a choice made for another view meanwhile stays
    const o = doneViews(); if (v === undefined) delete o[key]; else o[key] = v;
    for (const x of Object.keys(o)) if ((x.startsWith('l:') && !listById(+x.slice(2))) || (x.startsWith('f:') && !S.filters.some(f => f.id === +x.slice(2)))) delete o[x];  // gone lists / filters
    S.settings.show_done_views = JSON.stringify(o); render();
    try { await api('PATCH', '/api/settings', {show_done_views: S.settings.show_done_views}); } catch { try { await load(); } catch { /* offline */ } render(); }
    return {skipped: []};
  };
  await put(to);
  offerUndo(on ? tr('Completed tasks are shown here') : tr('Completed tasks are hidden here'), histAdd({label: `${on ? tr('Show completed') : tr('Hide completed')}: ${titleFor(key)}`, sett: true, undo: () => put(was), redo: () => put(to)}));
}
const doneItem = () => ({label: showDone() ? tr('Hide completed') : tr('Show completed'), icon: 'eye', fn: () => setShowDone(!showDone())});
// default: priority first, manual order (drag) inside each priority. 'sort2.' = new key, old per-view choices reset once.
// 1.7.0: "Flow" (dependencies module only) is the default of project lists (list view) and of "Now doable"
function sortDefault(k = S.route.key) {
  if (!depsOn()) return k === 'doable' ? 'date' : 'prio';
  if (k === 'doable') return 'flow';
  const l = k.startsWith('l:') ? listById(+k.slice(2)) : null;
  return l && l.kind === 'project' && !isKanban() && !isTimeline() ? 'flow' : 'prio';
}
const sortMode = (k = S.route.key) => { const m = LS.get('sort2.' + k, null); return !m || (m === 'flow' && !depsOn()) ? sortDefault(k) : m; };
const dueKey = t => (t.due || '9999') + (t.due_time || '99');
// Flow ties: start date (a task without one starts on its due date), due date + time, priority, manual order
const flowTie = (a, b) => (a.start || a.due || '9999').localeCompare(b.start || b.due || '9999') || dueKey(a).localeCompare(dueKey(b)) || b.priority - a.priority || bySort(a, b);
// 1.7.0 Flow: topological order by "Waiting on" (a task comes after the open tasks it waits on); only dependencies
// inside the given set count (the lock of a task waiting on something outside stays). Kahn's algorithm, the ready task
// with the smallest tie key first; a cycle falls back to the tie order for what is left (FLOW.cyc -> hint in the view)
const FLOW = {cyc: false};
const FLOW_WHY = N_('Waits on nothing open: the first task in the flow order (dependencies, then date, then priority).');
function flowSort(arr) {
  const ids = new Set(arr.map(t => t.id)), need = new Map(), after = new Map();
  for (const t of arr) {
    const bs = depsOn() ? [...new Set(t.blockers || [])].filter(b => b !== t.id && ids.has(b)) : [];
    need.set(t.id, bs.length);
    for (const b of bs) { if (!after.has(b)) after.set(b, []); after.get(b).push(t); }
  }
  const out = [], left = new Set(arr);
  let cyc = false;
  while (left.size) {
    let pick = null;
    for (const t of left) if (!need.get(t.id) && (!pick || flowTie(t, pick) < 0)) pick = t;
    if (!pick) { cyc = true; for (const t of left) if (!pick || flowTie(t, pick) < 0) pick = t; }
    left.delete(pick); out.push(pick);
    for (const x of after.get(pick.id) || []) need.set(x.id, Math.max(0, need.get(x.id) - 1));
  }
  if (cyc) FLOW.cyc = true;
  arr.splice(0, arr.length, ...out);
  return arr;
}
function sortTasks(arr, m = sortMode()) {
  if (m === 'flow') return flowSort(arr);
  const f = {
    custom: bySort,
    date: (a, b) => dueKey(a).localeCompare(dueKey(b)) || b.priority - a.priority || bySort(a, b),
    prio: (a, b) => b.priority - a.priority || bySort(a, b),
    title: (a, b) => a.title.localeCompare(b.title, 'de'),
    // 2.0.8 (#319): by creation, newest first / oldest first (ties: id, i.e. creation order)
    created: (a, b) => (b.created_at || '').localeCompare(a.created_at || '') || b.id - a.id,
    created_asc: (a, b) => (a.created_at || '').localeCompare(b.created_at || '') || a.id - b.id,
  }[m] || (m.startsWith('cf:') ? cfSortCmp(+m.slice(3)) : bySort);
  return arr.sort(f);
}
function groupTasks(v) {
  const all = sortTasks(v.open.slice()), pinned = all.filter(t => t.pinned);
  // 1.7.0: Flow shows one sequence instead of date groups (sections and the folder's lists stay)
  const g = groupRest(v.group === 'date' && sortMode() === 'flow' ? {...v, group: 'none'} : v, all.filter(t => !t.pinned));
  return pinned.length ? [{id: 'pinned', name: tr('Pinned'), tasks: pinned, cls: 'pin'}, ...g] : g;
}
function groupRest(v, arr) {
  const t0 = today();
  if (v.group === 'date') {
    const g = new Map();
    for (const t of arr) {
      const key = S.route.key === 'today' && planToday(t, t0) && !(t.due && t.due < t0) ? t0 : !t.due ? 'zz' : t.due < t0 ? 'over' : t.due;  // 2.11.0: planned = today
      if (!g.has(key)) g.set(key, []);
      g.get(key).push(t);
    }
    return [...g.entries()].sort((a, b) => (a[0] === 'over' ? '' : a[0]).localeCompare(b[0] === 'over' ? '' : b[0]))
      .map(([k, ts]) => ({id: 'd:' + k, name: k === 'over' ? tr('Overdue') : k === 'zz' ? tr('No date') : dayLabel(k, true), cls: k === 'over' ? 'over' : '', tasks: ts}));
  }
  if (v.group === 'list') {
    const g = new Map();
    for (const t of arr) { if (!g.has(t.list_id)) g.set(t.list_id, []); g.get(t.list_id).push(t); }
    return (v.folder ? sideOrder() : S.lists).filter(l => g.has(l.id)).map(l => ({id: 'l:' + l.id, name: lname(l), tasks: g.get(l.id), color: cssColor(l.color) || '', img: l.icon || '',
      ...(v.folder && l.folder !== v.folder ? {sub: l.folder} : {})}));  // 2.4.0 (#361): the lists of a subfolder get its header
  }
  if (v.group === 'section') {
    const secs = S.sections.filter(s => s.list_id === v.list);
    if (!secs.length) return [{id: 'all', name: '', tasks: arr}];
    const out = [{id: 's:0', name: tr('Unassigned'), tasks: arr.filter(t => !t.section_id || !secs.some(s => s.id === t.section_id)), section: null}];
    for (const s of secs) out.push({id: 's:' + s.id, name: s.name, tasks: arr.filter(t => t.section_id === s.id), section: s.id});
    return out.filter((g, i) => i > 0 || g.tasks.length);
  }
  return [{id: 'all', name: '', tasks: arr}];
}
function titleFor(k) {
  if (SMART[k]) return tr(SMART[k].name);
  if (k.startsWith('l:')) return lname(listById(+k.slice(2))) || tr('List');
  if (k.startsWith('tag:')) return '#' + k.slice(4);
  if (k.startsWith('who:')) { const id = +k.slice(4); return S.me && id === S.me.id ? tr('My tasks') : tr('Tasks of {0}', personNameAny(id) || '?'); }
  if (k.startsWith('grp:')) return tr('Group {0}', grpName(+k.slice(4)));
  if (k.startsWith('f:')) return (S.filters.find(f => f.id === +k.slice(2)) || {}).name || tr('Filters');
  if (k.startsWith('folder:')) return fDisp(k.slice(7));
  if (k === 'cal') return tr('Calendar');
  return '';
}
function quickDefaults() {
  const k = S.route.key, d = {};
  if (k === 'today') d.due = today();
  if (k === 'tomorrow') d.due = addDays(today(), 1);
  if (k.startsWith('l:')) d.list_id = +k.slice(2);
  if (k === 'inbox') d.list_id = inbox().id;
  if (k === 'assigned' && S.me) d.assignee_id = S.me.id;
  if (k.startsWith('who:') && S.me && +k.slice(4) === S.me.id) d.assignee_id = S.me.id;
  if (k.startsWith('tag:')) d.tags = [k.slice(4)];
  if (k.startsWith('folder:')) { const fl = folderLists(k.slice(7)).filter(l => canEditList(l.id)); if (fl.length) d.list_id = fl[0].id; }  // the folder's first list (~list picks another)
  if (S.route.mod === 'cal') d.due = S.calSel;
  if (k.startsWith('f:')) {  // new task in a filter view should show up in it
    const r = (S.filters.find(f => f.id === +k.slice(2)) || {}).rules || {};
    if (r.lists?.length === 1) d.list_id = r.lists[0];
    if (r.prios?.length === 1) d.priority = r.prios[0];
    if (r.tags?.length) d.tags = [r.tags[0]];
    if (r.dates?.includes('today') || r.dates?.includes('3d') || r.dates?.includes('7d')) d.due = today();
  }
  return d;
}
