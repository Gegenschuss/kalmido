/* Kalmido web client: The timeline (Gantt).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ timeline (gantt)
// Bars from start to due per open task. With the module "deps" (1.2) it is a small Gantt chart: arrows finish -> start
// from a task to the tasks waiting on it (SVG overlay, drawn after every render from the bars' own positions), a
// conflict colour when a task starts before a task it waits on is due, a hatch on waiting bars, linking by dragging
// the dot at a bar's end onto another bar (mouse / pen), long-press menu + "Connect to…" mode (touch), keyboard (focus
// a bar: Enter opens, C connects, Shift+F10 / context menu key = menu, arrow keys move between bars).
const tlDW = () => isRoadmap() ? rmDW() : Math.round((isMobile() ? 30 : 36) * uiZ());  // the roadmap (D3) has its own zoom
const TL_DAYS = 70;
const TL_MINW = 18;  // 1.5.3: a 1-day bar stays wide enough to tell move from resize at small zoom levels
S.tlL = null;        // the drawn timeline: {bars: Map(id -> 1)}
S.tlPick = null;     // "Connect to…" mode: {from}
S.depAll = {v: null, edges: [], closed: new Map(), busy: false};  // GET /api/deps: every dependency incl. completed blockers
const tlStart0 = t => t.start && t.start < t.due ? t.start : t.due;
const tlWaiting = t => dFor(t) && t.blocked > 0 && t.status === 0;
// the first open task t waits on that is due after t starts ("starts before X is due"), else null
function tlConflict(t) {
  if (!dFor(t) || !t.due) return null;
  const s = tlStart0(t);
  for (const b of t.blockers || []) { const x = S.tasks.get(b); if (x && x.status === 0 && x.due && s < x.due) return x; }
  return null;
}
// one task bar (D2 timeline, D3 roadmap): start..due clipped to start..end, DW px per day
function tlBarHtml(t, start, end, DW, pick, deps) {
  const s = tlStart0(t) < start ? start : tlStart0(t);
  const e = t.due > end ? end : t.due;
  const pad = DW >= 12 ? 2 : .5, x = diffDays(start, s) * DW, w = (diffDays(s, e) + 1) * DW;
  const wait = tlWaiting(t), conf = wait && tlConflict(t), ed = canEdit(t) && t.status === 0;
  const when = t.start && t.start < t.due ? `${fmtDayAbs(t.start)} – ${fmtDayAbs(t.due)}` : fmtDayAbs(t.due);
  const tip = [t.title, when, wait ? blockedTitle(t) : '', conf ? tr('Starts before “{0}” is due', conf.title) : '', t.status === 2 ? tr('done') : ''].filter(Boolean).join(' · ');
  const mark = pick ? (tlCanLink(pick.from, t.id) ? ' tl-ok' : ' tl-no') + (pick.from === t.id ? ' tl-from' : '') : '';
  // 2.7.0 (K14): the label of a short bar goes right of it, or left of it near the end of the range; it never runs past the
  // range, and on the left it stops before the name column (max-width in px, the room there)
  // 2.13.0 (#453 P12): a title that would be cut inside its bar goes next to it too (not only bars under 110 px)
  const sh = w < 110 || String(t.title || '').length * 6.5 + 24 > w;
  const span = TL_DAYS * DW, room = span - (x + w) - 24, lroom = x - 16, left = sh && room < 120 && lroom > room;
  const lmax = sh ? Math.max(40, Math.min(220, left ? lroom : room)) : 0;
  return `<div class="tl-bar p${t.priority} ${sh ? 'short' : ''}${left ? ' lbl-l' : ''}${wait ? ' wait' : ''}${conf ? ' conf' : ''}${ed ? '' : ' ro'}${t.status ? ' done' : ''}${mark}" data-id="${t.id}" style="left:${x + pad}px;width:${Math.max(TL_MINW, w - 2 * pad)}px" title="${esc(tip)}" tabindex="0" role="button" aria-label="${esc(tip)}">${wait ? ic('lock', 's tl-lk') : ''}<span${lmax ? ` style="max-width:${Math.round(lmax)}px"` : ''}>${esc(t.title)}</span><i class="h l"></i><i class="h r"></i></div>` +
    (deps && ed && !pick && dFor(t) ? `<button type="button" class="tl-knob" data-knob="${t.id}" style="left:${x + Math.max(w, TL_MINW + 2 * pad) + 9}px" tabindex="-1" aria-hidden="true" title="${tr('Drag onto the task that waits on this one')}"></button>` : '');
}
// 1.5.3 (q): undated tasks in the timeline: per list a folding group "No date (n)" at the end, one row per task with an
// empty dashed track. Click a day = due that day, drag across days = start + due (touch: hold, then drag); the bar then
// moves to its dated place. Header switch "No date" per device: on by default in project lists, off elsewhere.
const tlNdKey = listId => listId ? 'l' + listId : 'all';
function tlNdOn(listId) { const o = LS.get('tlnd', {}) || {}, k = tlNdKey(listId); return k in o ? !!o[k] : !!listId && listById(listId)?.kind === 'project'; }
function tlNdRows(l, ts) {
  const ids = new Set(ts.map(t => t.id)), ord = [];
  const add = t => { ord.push(t); for (const k of ts.filter(x => x.parent_id === t.id).sort(bySort)) add(k); };  // subtasks under their parent
  for (const t of ts.filter(x => !x.parent_id || !ids.has(x.parent_id)).sort(bySort)) add(t);
  const k = 'tlnd:' + l.id, closed = S.collapsed.has(k), ed = canEditList(l.id);
  return `<div class="tl-row tl-grp tl-ndhead" data-ndl="${l.id}"><div class="tl-name" data-act="collapse-tl" data-key="${k}" role="button" aria-expanded="${!closed}">${ic('chev', 's fcar' + (closed ? ' shut' : ''))}${tr('No date')} <span class="c">${ts.length}</span></div><div class="tl-track"></div></div>` +
    (closed ? '' : ord.map(t => `<div class="tl-row tl-nd"><div class="tl-name" data-act="open" data-id="${t.id}">${t.parent_id && ids.has(t.parent_id) ? '<span class="muted">↳ </span>' : ''}<span class="tln">${esc(t.title)}</span>${tlWaiting(t) ? `<span class="tl-wf" title="${esc(blockedTitle(t))}">${ic('lock', 's')}${esc(tr('waits for {0}', blockedNames(t)))}</span>` : ''}</div><div class="tl-track ndt${ed && canEdit(t) ? ' ed' : ''}" data-nd="${t.id}" title="${ed && canEdit(t) ? esc(isTouch() ? tr('Tap a day to set the date; hold and drag for a range') : tr('Click a day to set the date, drag across days for a range')) : ''}"></div></div>`).join(''));
}
const tlNdBtn = (on, n, act = 'tl-nd') => `<button class="btn sm chip ${on ? 'on' : ''}" data-act="${act}" aria-pressed="${on}" title="${esc(tr('Show tasks without a date as rows to draw into'))}">${ic('cal', 's')} ${tr('No date')}${n ? ` <span class="c">${n}</span>` : ''}</button>`;
// ---- 2.18.0 (#462): sections in the timeline / roadmap, (#431) new tasks drawn right into it, milestone diamonds
// a subtask sits in its root task's section (the list view shows it under its parent)
const tlSecOf = t => { let x = t; for (let i = 0; i < 20 && x?.parent_id; i++) { const p = S.tasks.get(x.parent_id); if (!p) break; x = p; } return x?.section_id || null; };
// [{sid, name, key, ts}] in the list's section order; tasks without a (known) section first as "Unassigned", like the
// list view; a list without sections = one group without a header (key ''). empty: show sections without tasks too
function tlSecs(lid, ts, empty) {
  const secs = S.sections.filter(s => s.list_id === lid);
  if (!secs.length) return [{sid: null, name: '', key: '', ts}];
  const ids = new Set(secs.map(s => s.id)), by = new Map();
  for (const t of ts) { const s = tlSecOf(t), k = ids.has(s) ? s : null; if (!by.has(k)) by.set(k, []); by.get(k).push(t); }
  const out = by.get(null)?.length ? [{sid: null, name: tr('Unassigned'), key: `tlsec:${lid}:0`, ts: by.get(null)}] : [];
  for (const s of secs) if (empty || by.get(s.id)?.length) out.push({sid: s.id, name: s.name, key: 'tlsec:' + s.id, ts: by.get(s.id) || []});
  return out;
}
// the track of a list / section / "+" row: with write access a place to draw a new task into (data-* = its geometry)
function tlCrTrack(lid, sid, key, geo, cr, inner) {
  if (!cr) return `<div class="tl-track">${inner}</div>`;
  const hint = isTouch() ? tr('Hold, then drag to add a task here') : tr('Drag across days to add a task, or double-click a day');
  return `<div class="tl-track tl-cr" data-cl="${lid}" data-cs="${sid || ''}" data-k="${esc(key)}" data-s0="${geo.s0}" data-dw="${geo.dw}" data-days="${geo.days}" title="${esc(hint)}">${inner}${tlNewHtml(key, geo)}</div>`;
}
// section header: fold button (per device, like the other folds) + "+" (new task in this section); top = roadmap row
function tlSecRow(l, sg, open, cr, geo, top, n) {
  return `<div class="tl-row tl-sec${top != null ? ' rm-row rm-s' : ''}" data-l="${l.id}"${top != null ? ` style="top:${top}px"` : ''}><div class="tl-name tl-secn"><button type="button" class="tl-secb" data-act="tl-secfold" data-key="${esc(sg.key)}" aria-expanded="${open}" title="${esc(sg.name)}">${ic('chev', 's fcar' + (open ? '' : ' shut'))}<span class="tln">${esc(sg.name)}</span><span class="c">${n ?? sg.ts.length}</span></button>` +
    `${cr ? `<button type="button" class="iconbtn tl-secadd" data-act="tl-add" data-k="${esc(sg.key)}" data-l="${l.id}" data-s="${sg.sid || ''}" title="${esc(tr('Add task to {0}', sg.name))}" aria-label="${esc(tr('Add task to {0}', sg.name))}">${ic('plus', 's')}</button>` : ''}</div>${tlCrTrack(l.id, sg.sid, sg.key, geo, cr, '')}</div>`;
}
// "+ Add task" at the end of every list group (only with write access)
function tlAddRow(l, geo, top) {
  const k = 'add:' + l.id;
  return `<div class="tl-row tl-add${top != null ? ' rm-row rm-a' : ''}" data-l="${l.id}"${top != null ? ` style="top:${top}px"` : ''}><div class="tl-name"><button type="button" class="tl-addb" data-act="tl-add" data-k="${k}" data-l="${l.id}" data-s="" aria-label="${esc(tr('Add task to {0}', lname(l)))}">${ic('plus', 's')}<span>${tr('Add task')}</span></button></div>${tlCrTrack(l.id, null, k, geo, true, '')}</div>`;
}
// a milestone task (t.ms, lane 2a) = a diamond at its date; it is a .tl-bar, so moving it (mouse, long-press), the
// keyboard (Enter, arrows, menu) and the arrows work as for bars; no ends to resize
function tlMsHtml(t, start, DW) {
  const x = diffDays(start, t.due) * DW + DW / 2, w = isTouch() ? 44 : 24, ed = canEdit(t) && t.status === 0;
  const lbl = tr('Milestone: {0}, {1}', t.title, fmtDateLoc(t.due));
  return `<div class="tl-bar tl-dia short${ed ? '' : ' ro'}${t.status ? ' done' : t.due < today() ? ' over' : ''}" data-id="${t.id}" data-ms="1" style="left:${x - w / 2}px;width:${w}px" title="${esc(lbl)}" tabindex="0" role="button" aria-label="${esc(lbl)}"><span>${esc(t.title)}</span></div>`;
}
// 2.18.0 review (R10): a month / quarter label used to sit only at the month's first day, so scrolled a few days in it was
// cut ("er 2026") or gone. Each label now spans its whole period (width up to the next label) and its text is sticky
// right of the sticky names, so the current month always shows at the left of the visible range.
function tlStickyMonths(html, W) {
  const re = /<div class="tl-m" style="left:([\d.]+)px">([^<]*)<\/div>/g, m = [...html.matchAll(re)];
  if (!m.length) return html;
  return m.map((x, i) => { const l = +x[1], r = i + 1 < m.length ? +m[i + 1][1] : W; return `<div class="tl-m" style="left:${l}px;width:${Math.max(0, r - l)}px"><span>${x[2]}</span></div>`; }).join('');
}
// is the milestone marker m (l.milestones) already drawn as a diamond row of one of the tasks ts?
const tlMsDrawn = (m, ts) => ts.some(t => t.ms && (m.id === t.id || (t.title === m.name && t.due === m.day)));  // lane 2a: m.id = the task's id
// the open inline "new task" field (S.tlNew = {at: row key, lid, sid, d0, d1, v, r: route}) in the row it was started in
const tlRouteSig = () => S.route.mod + '|' + S.route.key + '|' + (S.route.mod === 'cal' ? S.calMode : '');
function tlNewHtml(key, geo) {
  const N = S.tlNew; if (!N || N.at !== key || N.r !== tlRouteSig()) return '';
  const a = N.d0 < N.d1 ? N.d0 : N.d1, b = N.d0 < N.d1 ? N.d1 : N.d0;
  const x = Math.max(0, diffDays(geo.s0, a)) * geo.dw, w = (diffDays(a < geo.s0 ? geo.s0 : a, b) + 1) * geo.dw;
  const when = a < b ? `${fmtDayAbs(a)} – ${fmtDayAbs(b)}` : fmtDayAbs(b);
  // 2.18.0 review (R4): narrow screens show the range in short form (5.10.–8.10.), the long one does not fit there
  const sd = x => { try { return pd(x).toLocaleDateString(dpLocale(), {day: 'numeric', month: 'numeric'}); } catch { return x.slice(5); } };
  const whenS = a < b ? `${sd(a)}–${sd(b)}` : sd(b);
  return `<div class="tl-ghost" style="left:${x + 2}px;width:${Math.max(TL_MINW, w - 4)}px" aria-hidden="true"></div>` +
    `<div class="tl-new" style="--x:${x}px"><label class="sr" for="tl-new-in">${esc(tr('New task, {0}', when))}</label><input id="tl-new-in" type="text" maxlength="500" autocomplete="off" enterkeyhint="done" value="${esc(N.v || '')}" placeholder="${esc(tr('Task name'))}"><span class="tl-nwhen" aria-hidden="true"><span class="tl-nwl">${esc(when)}</span><span class="tl-nws">${esc(whenS)}</span></span>` +
    `<button type="button" class="iconbtn" data-act="tl-new-ok" title="${esc(tr('Add'))}" aria-label="${esc(tr('Add'))}">${ic('check', 's')}</button><button type="button" class="iconbtn" data-act="tl-new-x" title="${esc(tr('Cancel'))}" aria-label="${esc(tr('Cancel'))}">${ic('x', 's')}</button></div>`;
}
function viewTimeline(listId, inCal) {
  const DW = tlDW();
  if (!S.tlStart) S.tlStart = addDays(weekStartOf(today()), -7);
  const start = S.tlStart, end = addDays(start, TL_DAYS - 1), t0 = today();
  const all = openTasks().filter(t => !listId || t.list_id === listId);
  const dated = all.filter(t => t.due && t.due >= start && (t.start || t.due) <= end);
  const undated = all.filter(t => !t.due).length;
  const ndOn = tlNdOn(listId), und = ndOn ? all.filter(t => !t.due) : [];
  // 2.7.1 (#410): milestones of project lists as markers in the list's row (a list with only milestones in range shows too)
  const msIn = l => l.kind === 'project' && (!listId || l.id === listId) ? (l.milestones || []).filter(m => m.day >= start && m.day <= end) : [];
  // 2.18.0 (#431): the list of a list timeline always has its group (an empty project can be planned right here)
  const groups = S.lists.filter(l => dated.some(t => t.list_id === l.id) || und.some(t => t.list_id === l.id) || listId === l.id).map(l => ({l, ts: dated.filter(t => t.list_id === l.id).sort((a, b) => (a.start || a.due).localeCompare(b.start || b.due) || bySort(a, b)), nd: und.filter(t => t.list_id === l.id)}));
  let head = '', months = '', lastM = '';
  for (let i = 0; i < TL_DAYS; i++) {
    const d = addDays(start, i), dd = pd(d), wk = dd.getDay() === 0 || dd.getDay() === 6;
    head += `<div class="tl-d ${d === t0 ? 'today' : ''} ${wk ? 'we' : ''}"><span>${WD[dd.getDay()].slice(0, 1)}</span>${dd.getDate()}</div>`;
    if (d.slice(0, 7) !== lastM) { months += `<div class="tl-m" style="left:${i * DW}px">${MON[dd.getMonth()]} ${dd.getFullYear()}</div>`; lastM = d.slice(0, 7); }
  }
  months = tlStickyMonths(months, TL_DAYS * DW);
  const todayX = diffDays(start, t0) * DW;
  const deps = depsOn(), pick = S.tlPick && deps ? S.tlPick : null;
  const bars = new Map();
  const bar = t => { bars.set(t.id, 1); return t.ms ? tlMsHtml(t, start, DW) : tlBarHtml(t, start, end, DW, pick, deps); };
  // 2.7.0 (K14): names cut with "…" (full name in the tooltip)
  // 2.18.0 (#462 / #431): a milestone task is a diamond in its own row, so the list row only marks the ones not drawn there
  const msMark = (l, ts) => msIn(l).filter(m => !tlMsDrawn(m, ts)).map(m => `<i class="tl-ms ${m.done ? 'done' : m.day < t0 ? 'over' : ''}" style="left:${diffDays(start, m.day) * DW + DW / 2}px" title="${esc(m.name + ' · ' + fmtDateLoc(m.day))}" role="img" aria-label="${esc(tr('Milestone') + ': ' + m.name + ', ' + fmtDateLoc(m.day))}"></i>`).join('');
  const geo = {s0: start, dw: DW, days: TL_DAYS};
  // 2.18.0 (#462): inside a list the tasks are grouped by section (the list's order, "Unassigned" first as in the list
  // view); every list / section row is a place to draw a new task into (#431), "+ Add task" ends every list group
  const rows = groups.map(g => {
    const cr = canAddTo(g.l.id) && !pick;
    let h = `<div class="tl-row tl-grp" data-l="${g.l.id}"><div class="tl-name" title="${esc(lname(g.l))}"><span class="tln">${esc(lname(g.l))}</span></div>${tlCrTrack(g.l.id, null, 'g:' + g.l.id, geo, cr, msMark(g.l, g.ts))}</div>`;
    for (const sg of tlSecs(g.l.id, g.ts, !!listId)) {
      const shut = !!sg.key && S.collapsed.has(sg.key);
      if (sg.key) h += tlSecRow(g.l, sg, !shut, cr, geo, null);  // 2.18.0 review (R10): no roadmap top here (was an invalid style="top:px")
      if (!shut) h += sg.ts.map(t => `<div class="tl-row${t.ms ? ' tl-msrow' : ''}${sg.key ? ' tl-insec' : ''}"><div class="tl-name" data-act="open" data-id="${t.id}" title="${esc(t.title)}">${t.parent_id ? '<span class="muted">↳ </span>' : ''}<span class="tln">${esc(t.title)}</span></div><div class="tl-track">${bar(t)}</div></div>`).join('');
    }
    return h + (g.nd.length ? tlNdRows(g.l, g.nd) : '') + (cr ? tlAddRow(g.l, geo, null) : '');
  }).join('');
  S.tlL = {bars};
  const from = pick && S.tasks.get(pick.from);
  const hint = isMobile() ? tr('Long-press and drag a bar: the middle moves it, the ends change start / due date.') : tr('Drag a bar to move it, drag its ends to change start / due date.');
  const dhint = !deps || ![...bars.keys()].some(i => dFor(S.tasks.get(i))) ? '' : isTouch() ? tr('Long-press a bar and let go for more: connect it to the task that waits on it, remove a dependency.') : tr('Drag the dot at the end of a bar onto another bar: that task then waits on it. Click an arrow to remove it.');
  // 2.18.0 review: the footer also tells how to draw a new task (only where the user may add one)
  const chint = !pick && groups.some(g => canAddTo(g.l.id)) ? (isTouch() ? tr('Hold an empty spot in a list or section row, then drag to add a task, or tap “+”.') : tr('Drag across empty days in a list or section row to add a task, double-click a day or use “+”.')) : '';
  const ndBtn = tlNdBtn(ndOn, undated);
  return `${inCal ? '' : `<div class="calbar"><h2>${tr('Timeline')}</h2>${ndBtn}<div class="calnav"><button class="iconbtn" data-act="tl-prev" title="${esc(tr('Previous period'))}" aria-label="${esc(tr('Previous period'))}">${ic('left')}</button><button class="btn sm" data-act="tl-today">${tr('Today')}</button><button class="iconbtn" data-act="tl-next" title="${esc(tr('Next period'))}" aria-label="${esc(tr('Next period'))}">${ic('right')}</button></div></div>`}
    ${from ? `<div class="tl-pick" role="status">${ic('deps', 's')}<span>${tr('Tap the task that waits on “{0}”', esc(from.title))}</span><span class="spacer"></span><button class="btn sm" data-act="tl-pick-list">${ic('search', 's')} ${tr('Pick from a list…')}</button><button class="btn sm" data-act="tl-pick-cancel">${tr('Cancel')}</button></div>` : ''}
    <div class="tl${pick ? ' picking' : ''}" style="--dw:${DW}px;--days:${TL_DAYS}">
    <div class="tl-scroll" id="tlscroll"><div class="tl-inner">
      <div class="tl-row tl-headrow" title="${esc(tr('Set a date range via “Start” in the date dialog.'))}"><div class="tl-name"></div><div class="tl-track tl-headtrack"><div class="tl-months">${months}</div><div class="tl-days">${head}</div></div></div>
      ${inCal ? tlCalRows(start, end, DW) : ''}
      ${rows || `<div class="tl-row"><div class="tl-name muted">${tr('No dated tasks')}</div><div class="tl-track"></div></div>`}
      <i class="tl-now" style="left:calc(var(--tl-name) + ${todayX + DW / 2}px)"></i>
      ${listId ? msIn(listById(listId) || {}).map(m => `<i class="tl-msl" style="left:calc(var(--tl-name) + ${diffDays(start, m.day) * DW + DW / 2}px)"></i>`).join('') : ''}
      ${deps ? '<svg class="tl-deps" id="tl-deps" aria-hidden="true"></svg>' : ''}
    </div></div>
    ${hintOnce('tlrange', tr('Set a date range via “Start” in the date dialog.'))}<div class="muted tl-foot">${chint ? chint + ' ' : ''}${hint} ${dhint ? dhint + ' ' : ''}${undated && !ndOn ? ' ' + trn('{0} task without a date is not shown.', '{0} tasks without a date are not shown.', undated) : ''}</div></div>`;
}

// ---- dependency arrows (SVG overlay in .tl-inner, same coordinates as the tracks)
async function loadDepAll() {
  if (S.depAll.busy || !depsOn()) return;
  const v = S.v;
  S.depAll.busy = true;
  try {
    const j = await rawFetch('GET', '/api/deps');
    S.depAll = {v, edges: j.edges || [], closed: new Map((j.closed || []).map(x => [x.id, x])), busy: false};
    tlArrows();
  } catch { S.depAll.busy = false; S.depAll.v = v; }  // offline: the open blockers every task carries are enough
}
// [{w, b, closed}]: waiting task w, blocker b (closed = the completed blocker's row from /api/deps)
function tlEdges(bars) {
  const out = [], seen = new Set();
  const add = (w, b, closed) => { const k = w + ':' + b; if (!seen.has(k) && (bars.has(w) || bars.has(b))) { seen.add(k); out.push({w, b, closed}); } };
  for (const t of S.tasks.values()) if (t.status === 0 && !t.deleted_at && t.blockers?.length) for (const b of t.blockers) add(t.id, b, null);
  for (const [w, b] of S.depAll.edges) {
    const c = S.depAll.closed.get(b), live = S.tasks.get(b);
    if (c && !(live && live.status === 0) && S.tasks.get(w)?.status === 0) add(w, b, c);
  }
  return out;
}
function tlRound(p, r) {  // orthogonal polyline with rounded elbows
  const f = n => Math.round(n * 10) / 10;
  let d = `M${f(p[0][0])},${f(p[0][1])}`;
  for (let i = 1; i < p.length - 1; i++) {
    const [ax, ay] = p[i - 1], [bx, by] = p[i], [cx, cy] = p[i + 1];
    const l1 = Math.hypot(bx - ax, by - ay), l2 = Math.hypot(cx - bx, cy - by), k = Math.min(r, l1 / 2, l2 / 2);
    if (!k) { d += `L${f(bx)},${f(by)}`; continue; }
    d += `L${f(bx - (bx - ax) / l1 * k)},${f(by - (by - ay) / l1 * k)}Q${f(bx)},${f(by)} ${f(bx + (cx - bx) / l2 * k)},${f(by + (cy - by) / l2 * k)}`;
  }
  const [lx, ly] = p[p.length - 1];
  return d + `L${f(lx)},${f(ly)}`;
}
function tlRoute(x1, y1, x2, y2, h) {
  const g = 8;
  if (x2 - x1 >= 2 * g) return tlRound([[x1, y1], [x1 + g, y1], [x1 + g, y2], [x2, y2]], 5);
  const ym = y2 + (y2 > y1 ? -h / 2 : h / 2);  // back to the left: along the row border above / below the target
  return tlRound([[x1, y1], [x1 + g, y1], [x1 + g, ym], [x2 - g - 2, ym], [x2 - g - 2, y2], [x2, y2]], 5);
}
let tlArrowRaf = 0;
const tlArrowsSoon = () => { if (!tlArrowRaf) tlArrowRaf = requestAnimationFrame(() => { tlArrowRaf = 0; tlArrows(); }); };
function tlArrows() {
  if (isRoadmap()) { rmRows(); rmArrows(); return; }  // D3: computed from the model, rows virtualised
  const svg = $('#tl-deps');
  if (!svg || !S.tlL) return;
  if (!depsOn()) { svg.innerHTML = ''; return; }
  if (S.depAll.v !== S.v) loadDepAll();
  // one read pass (row positions, bar geometry from the inline style = also mid-drag), then one write
  const geo = new Map();
  for (const b of $$('.tl-bar[data-id]', svg.parentElement)) {
    const row = b.parentElement.parentElement;
    geo.set(+b.dataset.id, {x: parseFloat(b.style.left) || 0, w: parseFloat(b.style.width) || 0, y: row.offsetTop + row.offsetHeight / 2, h: row.offsetHeight || 34});
  }
  const title = id => S.tasks.get(id)?.title || S.depAll.closed.get(id)?.title || tr('a task you cannot see');
  let out = '';
  for (const {w, b, closed} of tlEdges(S.tlL.bars)) {
    const W = geo.get(w), B = geo.get(b), wt = S.tasks.get(w), bt = S.tasks.get(b);
    const conf = !closed && bt && bt.status === 0 && bt.due && wt?.due && tlStart0(wt) < bt.due;
    const kind = closed ? 'done' : conf ? 'conf' : 'ok';
    let d, tip;
    if (W && B) d = tlRoute(B.x + B.w, B.y, W.x - 1, W.y, W.h);
    else if (W) d = `M${Math.max(0, W.x - 20)},${W.y}H${W.x - 1}`;
    else d = `M${B.x + B.w},${B.y}H${B.x + B.w + 20}`;
    if (closed) tip = tr('“{0}” waits on “{1}” (done)', title(w), title(b));
    else if (conf) tip = tr('“{0}” starts before “{1}” is due', title(w), title(b));
    else tip = tr('“{0}” waits on “{1}”', title(w), title(b));
    if (!(W && B)) tip += ' · ' + tr('outside this view');
    out += `<g class="dep ${kind}${W && B ? '' : ' stub'}" data-dep="${w}:${b}"><title>${esc(tip)}</title><path class="hit" d="${d}"/><path class="ln" d="${d}" marker-end="url(#tl-ah-${kind})"/>${W && B ? '' : `<circle class="st" cx="${W ? Math.max(0, W.x - 20) : B.x + B.w + 20}" cy="${W ? W.y : B.y}" r="2.5"/>`}</g>`;
  }
  const mk = k => `<marker id="tl-ah-${k}" class="ah ${k}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0.5L7.5,4L0,7.5z"/></marker>`;
  svg.innerHTML = `<defs>${mk('ok')}${mk('conf')}${mk('done')}</defs>${out}<path class="rubber" d=""/>`;
}
// re-layout when the timeline's box changes (window, font size, sidebar); scrolling moves the overlay with the bars
const tlRO = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => tlArrowsSoon()) : null;
if (!tlRO) addEventListener('resize', () => tlArrowsSoon());
// 2.18.0 (#431): the bar just created keeps the focus through re-renders shortly after (it would fall back to the page)
function tlFocKeep() {
  const f = S.tlFoc; if (!f) return;
  if (Date.now() > f.until) { S.tlFoc = null; return; }
  const a = document.activeElement;
  if (!a || a === document.body || !a.isConnected) $(`.tl-bar[data-id="${f.id}"]`)?.focus({preventScroll: true});
}
function tlAfterRender(el) {  // renderView: a new timeline is in the DOM
  tlFocKeep();
  if (tlRO && !el.__ro) { el.__ro = 1; tlRO.observe(el.firstElementChild || el); }
  tlArrows();
}

// ---- linking: a task may wait on another one when I can change it; the server checks again (cycles, rights)
function tlReaches(from, target) {  // does `from` (transitively) wait on `target`? (open blockers I can see)
  const seen = new Set(), todo = [from];
  while (todo.length) { const x = todo.pop(); if (x === target) return true; if (seen.has(x) || seen.size > 5000) continue; seen.add(x); todo.push(...(S.tasks.get(x)?.blockers || [])); }
  return false;
}
function tlCanLink(b, w) {
  const wt = S.tasks.get(w);
  return b !== w && !!wt && canEdit(wt) && dFor(wt) && dFor(S.tasks.get(b)) && !(wt.blockers || []).includes(b) && !tlReaches(b, w);
}
async function tlConnect(b, w) {
  const wt = S.tasks.get(w), bt = S.tasks.get(b);
  if (!wt || !bt) return;
  if ((wt.blockers || []).includes(b)) { toast(tr('“{0}” already waits on “{1}”', wt.title, bt.title)); return; }
  try { await api('POST', '/api/deps', {task_id: w, blocker_id: b}); } catch { return; }  // api() showed the server's reason
  await load(); render();
  if (S.sel === w || S.sel === b) loadDeps(S.sel);
  toast(tr('“{0}” now waits on “{1}”', wt.title, bt.title));
}
async function tlUnlink(w, b) {
  try { await api('DELETE', `/api/deps/${w}/${b}`); } catch { return; }
  await load(); render();
  if (S.sel === w || S.sel === b) loadDeps(S.sel);
  toast(tr('Dependency removed'));
}
function tlDepPop(g) {
  const [w, b] = g.dataset.dep.split(':').map(Number), wt = S.tasks.get(w);
  const nm = id => { const x = S.tasks.get(id)?.title || S.depAll.closed.get(id)?.title || ''; return x.length > 40 ? x.slice(0, 39) + '…' : x; };
  menu(g, [...(canEdit(wt) ? [{label: tr('Remove dependency'), icon: 'x', cls: 'danger', fn: () => tlUnlink(w, b)}] : []),
    {label: tr('Open “{0}”', nm(b)), icon: 'arrow', fn: () => openTaskById(b)}, {label: tr('Open “{0}”', nm(w)), icon: 'arrow', fn: () => openTaskById(w)}]);
}
// bar menu: long-press (touch), right-click, Shift+F10 / context menu key
function tlBarMenu(el) {
  const id = +el.dataset.id, t = S.tasks.get(id); if (!t) return;
  const items = [{label: tr('Open'), icon: 'edit', fn: () => openDetail(id)}];
  // 2.18.0 review: a keyboard way to move a bar / milestone diamond to another day (D, or this menu: Shift+F10)
  if (canEdit(t) && t.status === 0) items.push({label: t.ms ? tr('Move to date…') : tr('Pick a date…'), icon: 'cal', keys: 'D', fn: () => datePop(el, id)});
  if (canEdit(t) && t.due) items.push({label: tr('Remove date'), icon: 'ban', fn: () => tlUndate(id)});
  if (dFor(t)) {
    if (canEdit(t)) items.push({label: tr('Connect to…'), icon: 'deps', keys: 'C', fn: () => tlPickStart(id)}, {label: tr('Pick from a list…'), icon: 'search', fn: () => depPicker(id, 'blocking')});
    const nm = x => x.length > 32 ? x.slice(0, 31) + '…' : x;
    const rm = [...(canEdit(t) ? (t.blockers || []).map(b => S.tasks.get(b)).filter(Boolean).map(b => ({label: tr('Stop waiting on “{0}”', nm(b.title)), icon: 'x', fn: () => tlUnlink(id, b.id)})) : []),
      ...openTasks().filter(x => (x.blockers || []).includes(id) && canEdit(x)).map(x => ({label: tr('“{0}” no longer waits', nm(x.title)), icon: 'x', fn: () => tlUnlink(x.id, id)}))];
    if (rm.length) items.push('-', ...rm);
  }
  menu(el, items);
}
// 1.5.3 (q): an undated task gets its date by drawing into its empty track; a bar dropped on "No date" loses it
async function tlUndate(id) { await patchUndoable(id, {due: null, due_time: null, reminders: '', repeat: '', start: null}, tr('Date removed')); }
async function tlDraw(id, d0, d1) {
  const a = d0 < d1 ? d0 : d1, b = d0 < d1 ? d1 : d0;
  await patchUndoable(id, {due: b, start: a < b ? a : null}, tr('Date: {0}', a < b ? `${fmtDayAbs(a)} – ${fmtDayAbs(b)}` : dayLabel(b)));
}
// 2.0.6 (#189): the roadmap's empty tracks carry their own geometry (data-s0 / data-dw / data-days)
const ndGeo = tr_ => ({s0: tr_.dataset.s0 || S.tlStart, dw: +tr_.dataset.dw || tlDW(), days: +tr_.dataset.days || TL_DAYS});
const ndDay = (tr_, clientX) => { const r = tr_.getBoundingClientRect(), g = ndGeo(tr_); return addDays(g.s0, Math.max(0, Math.min(g.days - 1, Math.floor((clientX - r.left) / g.dw)))); };
let tlNd = null;  // drawing in an empty track: {tr, id, d0, d1, el, touch, timer, active}
function ndShow(d) {
  if (!d.el) { d.el = document.createElement('div'); d.el.className = 'tl-bar ndraw'; d.tr.appendChild(d.el); }
  const a = d.d0 < d.d1 ? d.d0 : d.d1, b = d.d0 < d.d1 ? d.d1 : d.d0, g = ndGeo(d.tr), DW = g.dw;
  d.el.style.left = diffDays(g.s0, a) * DW + 2 + 'px'; d.el.style.width = Math.max(TL_MINW, (diffDays(a, b) + 1) * DW - 4) + 'px';
  d.el.textContent = a < b ? `${fmtDayAbs(a)} – ${fmtDayAbs(b)}` : fmtDayAbs(b);
}
document.addEventListener('pointerdown', e => {
  const tr_ = e.target.closest?.('.tl-track.ndt.ed'); if (!tr_ || e.button !== 0 || e.pointerType === 'touch') return;
  const d0 = ndDay(tr_, e.clientX);
  tlNd = {tr: tr_, id: +tr_.dataset.nd, d0, d1: d0, el: null}; ndShow(tlNd); e.preventDefault();
});
document.addEventListener('pointermove', e => { if (tlNd && !tlNd.touch) { tlNd.d1 = ndDay(tlNd.tr, e.clientX); ndShow(tlNd); } });
document.addEventListener('pointerup', () => { if (!tlNd || tlNd.touch) return; const d = tlNd; tlNd = null; tlDraw(d.id, d.d0, d.d1); });
// touch: a tap sets the day; hold ~0.3 s, then drag for a range
document.addEventListener('touchstart', e => {
  const tr_ = e.target.closest?.('.tl-track.ndt.ed'); if (!tr_) return;
  const p = e.touches[0], d0 = ndDay(tr_, p.clientX);
  tlNd = {tr: tr_, id: +tr_.dataset.nd, d0, d1: d0, el: null, touch: true, x: p.clientX, y: p.clientY, active: false, moved: false};
  tlNd.timer = setTimeout(() => { if (tlNd) { tlNd.active = true; ndShow(tlNd); if (navigator.vibrate) navigator.vibrate(12); } }, 300);
}, {passive: true});
document.addEventListener('touchmove', e => {
  if (!tlNd?.touch) return;
  const p = e.touches[0];
  if (!tlNd.active) { if (Math.hypot(p.clientX - tlNd.x, p.clientY - tlNd.y) > 8) { clearTimeout(tlNd.timer); tlNd = null; } return; }
  e.preventDefault(); tlNd.moved = true; tlNd.d1 = ndDay(tlNd.tr, p.clientX); ndShow(tlNd);
}, {passive: false});
document.addEventListener('touchend', e => {
  if (!tlNd?.touch) return;
  clearTimeout(tlNd.timer); const d = tlNd; tlNd = null;
  if (e.cancelable) e.preventDefault();
  tlDraw(d.id, d.d0, d.d1);  // a tap (or a hold without moving): that day
});
// ---- 2.18.0 (#431): a new task drawn into a list / section row of the timeline or the roadmap. Mouse / pen: drag
// across empty days (a ghost bar shows the range), or double-click a day; touch: hold ~0.45 s on an empty spot, then
// drag (a plain swipe still scrolls, a quick tap does nothing); "+" buttons for the keyboard and for everyone. Then a
// title field at that range: Enter creates the task with exactly that start..due in that list + section (the normal
// create path: offline outbox, history / undo), Escape cancels.
const tlCrFree = e => !e.target.closest?.('.tl-bar, .tl-ms, .rm-sum, .rm-off, .tl-new, button, a, input');
function tlNewOpen(tr_, d0, d1) {
  const lid = +tr_.dataset.cl, sid = +tr_.dataset.cs || null;
  if (!canAddTo(lid)) { roToast(); return; }
  S.tlNew = {at: tr_.dataset.k, lid, sid, d0, d1, v: '', r: tlRouteSig()};
  const k = tr_.dataset.k; if (k?.startsWith('tlsec:') && S.collapsed.has(k)) { S.collapsed.delete(k); LS.set('collapsed', [...S.collapsed]); }
  renderView(); tlNewFocus();
}
// the "+" buttons: the field at today (or the first day in view when today is not in the window)
function tlAddAt(btn) {
  const row = btn.closest('.tl-row'), tr_ = row && $('.tl-track.tl-cr', row); if (!tr_) return;
  const g = ndGeo(tr_), t0 = today(), last = addDays(g.s0, g.days - 1), sc = $('#tlscroll');
  let d = t0;
  if (sc) {  // the day under the left edge of the visible track, when today is scrolled out of view
    const nameW = $('.tl-name', row)?.offsetWidth || 0, first = addDays(g.s0, Math.max(0, Math.floor(sc.scrollLeft / g.dw) + 1)), lastV = addDays(g.s0, Math.max(0, Math.floor((sc.scrollLeft + Math.max(0, sc.clientWidth - nameW)) / g.dw) - 1));
    if (sc.clientWidth && (t0 < first || t0 > lastV)) d = first;
  }
  if (d < g.s0 || d > last) d = g.s0;
  tlNewOpen(tr_, d, d);
}
function tlNewFocus() {
  const i = $('#tl-new-in'); if (!i) return;
  const sc = $('#tlscroll'), box = i.closest('.tl-new');
  if (sc && box) {  // the field next to the sticky names, not under them
    const nameW = $('.tl-row:not(.tl-headrow) .tl-name', sc)?.offsetWidth || 0, x = box.offsetLeft, w = box.offsetWidth;
    if (x < sc.scrollLeft) sc.scrollLeft = Math.max(0, x - 8);
    else if (sc.clientWidth && x + w > sc.scrollLeft + sc.clientWidth - nameW) sc.scrollLeft = x + w - (sc.clientWidth - nameW) + 8;
  }
  i.focus({preventScroll: true}); tlKbSync();  // focus events may lag (window not focused yet): sync right away
  try { i.setSelectionRange(i.value.length, i.value.length); } catch { /* no caret */ }
  // phones: the field stays above the on-screen keyboard (vvSync does the same for every focused field later)
  setTimeout(() => { const vv = window.visualViewport, j = $('#tl-new-in'); if (j && vv && j.getBoundingClientRect().bottom > vv.offsetTop + vv.height - 4) j.scrollIntoView?.({block: 'nearest'}); }, 350);
}
function tlNewEnd(back) {
  const N = S.tlNew; if (!N) return;
  S.tlNew = null; renderView(); tlKbSync();  // a re-render may drop the focused field without a focusout
  if (back) { const b = $(`[data-act="tl-add"][data-k="${rmEsc(N.at)}"]`) || $(`.tl-track.tl-cr[data-k="${rmEsc(N.at)}"]`)?.closest('.tl-row')?.querySelector('button'); b?.focus({preventScroll: true}); }
}
async function tlNewSave() {
  const N = S.tlNew, i = $('#tl-new-in'); if (!N) return;
  const v = (i ? i.value : N.v || '').trim();
  if (!v) { i?.focus(); return; }
  if (!canAddTo(N.lid)) { roToast(); tlNewEnd(); return; }
  const a = N.d0 < N.d1 ? N.d0 : N.d1, b = N.d0 < N.d1 ? N.d1 : N.d0;
  S.tlNew = null;
  let t;
  try { t = await createTask({title: v.slice(0, 500), list_id: N.lid, section_id: N.sid, due: b, ...(a < b ? {start: a} : {})}); }
  catch { S.tlNew = {...N, v}; renderView(); tlNewFocus(); return; }  // api() told why; the text stays for another try
  if (t?.id != null) tlFocusBar(t.id, t.list_id);
  tlKbSync();
}
// after creating: the new bar in view and focused (roadmap: its list opened, its row drawn)
function tlFocusBar(id, lid, n = 0) {
  if (isRoadmap()) {
    const V = S.rmV, r = V?.M.taskRow.get(id);
    if (!r && n === 0 && lid != null && V?.M.listNode.get(lid)?.type === 'g' && !V.M.listNode.get(lid).open) { rmSet({t: {...(rmP().t || {}), ['l' + lid]: 1}}); }
    const r2 = S.rmV?.M.taskRow.get(id), sc = $('#tlscroll');
    if (r2 && sc) { const G = S.rmV.G, y = G.hh + r2.i * G.rh; if (y < sc.scrollTop + G.hh || y + G.rh > sc.scrollTop + sc.clientHeight) sc.scrollTop = Math.max(0, y - sc.clientHeight / 2); rmRows(true); }
  }
  const b = $(`.tl-bar[data-id="${id}"]`);
  if (!b) { if (n < 3) requestAnimationFrame(() => tlFocusBar(id, lid, n + 1)); return; }
  b.focus({preventScroll: true});
  S.tlFoc = {id, until: Date.now() + 2500};  // a re-render right after (sync, the server's answer) keeps it there
  const sc = $('#tlscroll');
  if (sc) { const x = parseFloat(b.style.left) || 0, nameW = $('.tl-row:not(.tl-headrow) .tl-name', sc)?.offsetWidth || 0; if (sc.clientWidth && (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - nameW - 40)) sc.scrollLeft = Math.max(0, x - 40); }
  b.classList.add('flash'); setTimeout(() => b.classList.remove('flash'), 1200);
}
let tlCr = null;  // drawing a new task: {tr, d0, d1, el, touch, timer, active, x, y}
function crShow(d) {
  if (!d.el) { d.el = document.createElement('div'); d.el.className = 'tl-ghost'; d.el.setAttribute('aria-hidden', 'true'); d.tr.appendChild(d.el); }
  const a = d.d0 < d.d1 ? d.d0 : d.d1, b = d.d0 < d.d1 ? d.d1 : d.d0, g = ndGeo(d.tr);
  d.el.style.left = diffDays(g.s0, a) * g.dw + 2 + 'px'; d.el.style.width = Math.max(TL_MINW, (diffDays(a, b) + 1) * g.dw - 4) + 'px';
  d.el.textContent = a < b ? `${fmtDayAbs(a)} – ${fmtDayAbs(b)}` : fmtDayAbs(b);
}
document.addEventListener('pointerdown', e => {
  const tr_ = e.target.closest?.('.tl-track.tl-cr'); if (!tr_ || e.button !== 0 || e.pointerType === 'touch' || S.tlPick || !tlCrFree(e)) return;
  const d0 = ndDay(tr_, e.clientX);
  tlCr = {tr: tr_, d0, d1: d0, el: null, x: e.clientX};
  e.preventDefault();  // no text selection while drawing
});
document.addEventListener('pointermove', e => {
  if (!tlCr || tlCr.touch) return;
  if (!tlCr.el && Math.abs(e.clientX - tlCr.x) < 4) return;
  tlCr.d1 = ndDay(tlCr.tr, e.clientX); crShow(tlCr);
});
document.addEventListener('pointerup', () => {
  if (!tlCr || tlCr.touch) return;
  const d = tlCr; tlCr = null; d.el?.remove();
  if (d.el && d.d0 !== d.d1) tlNewOpen(d.tr, d.d0, d.d1);  // a plain click does nothing (double-click = one day)
});
document.addEventListener('dblclick', e => {
  const tr_ = e.target.closest?.('.tl-track.tl-cr'); if (!tr_ || S.tlPick || !tlCrFree(e)) return;
  e.preventDefault(); const d = ndDay(tr_, e.clientX); tlNewOpen(tr_, d, d);
});
document.addEventListener('touchstart', e => {
  const tr_ = e.target.closest?.('.tl-track.tl-cr'); if (!tr_ || S.tlPick || e.touches.length !== 1 || !tlCrFree(e)) { if (tlCr?.touch) { clearTimeout(tlCr.timer); tlCr = null; } return; }
  const p = e.touches[0], d0 = ndDay(tr_, p.clientX);
  tlCr = {tr: tr_, d0, d1: d0, el: null, touch: true, x: p.clientX, y: p.clientY, active: false};
  tlCr.timer = setTimeout(() => { if (tlCr?.touch) { tlCr.active = true; crShow(tlCr); if (navigator.vibrate) navigator.vibrate(12); } }, 450);
}, {passive: true});
document.addEventListener('touchmove', e => {
  if (!tlCr?.touch) return;
  const p = e.touches[0];
  if (!tlCr.active) { if (Math.hypot(p.clientX - tlCr.x, p.clientY - tlCr.y) > 8) { clearTimeout(tlCr.timer); tlCr = null; } return; }  // a swipe: the timeline scrolls
  e.preventDefault();
  const sc = $('#tlscroll');
  if (sc) {  // scroll along at the edges (left: right of the sticky names, phones have only ~30 px per day)
    // 2.18.0 review (R4): only once the finger has really moved towards that edge; a press on the first visible day
    // sits inside the left edge zone, and scrolling there during the hold shifted the days under the finger (one short)
    const r = sc.getBoundingClientRect(), nw = tlCr.tr.previousElementSibling?.offsetWidth || 0, mv = p.clientX - tlCr.x;
    if (mv > 16 && p.clientX > r.right - 28) sc.scrollLeft += 10; else if (mv < -16 && p.clientX < r.left + nw + 28) sc.scrollLeft -= 10;
  }
  tlCr.d1 = ndDay(tlCr.tr, p.clientX); crShow(tlCr);
}, {passive: false});
function tlCrTouchEnd(e) {
  if (!tlCr?.touch) return;
  clearTimeout(tlCr.timer); const d = tlCr; tlCr = null; d.el?.remove();
  if (!d.active) return;  // a quick tap or a swipe
  if (e.cancelable) e.preventDefault();  // no click / context menu after the hold
  if (e.type === 'touchend') tlNewOpen(d.tr, d.d0, d.d1);
}
document.addEventListener('touchend', tlCrTouchEnd);
document.addEventListener('touchcancel', tlCrTouchEnd);
document.addEventListener('contextmenu', e => { if (tlCr?.touch && tlCr.active) e.preventDefault(); });
document.addEventListener('input', e => { if (e.target.id === 'tl-new-in' && S.tlNew) S.tlNew.v = e.target.value; });
document.addEventListener('keydown', e => {
  if (e.target.id !== 'tl-new-in' || e.isComposing) return;
  if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); tlNewSave(); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); tlNewEnd(true); }
}, true);
// 2.18.0 review (R2): on touch screens the keyboard comes up with the field; the fixed tab bar and the "+" button would
// then cover it (the visible area shrinks to ~470 px on a phone), so they step aside while it has the focus (like the
// chat's kb-open; a separate class, chatFit() owns kb-open)
function tlKbSync() {
  const on = document.activeElement?.id === 'tl-new-in' && isTouch();
  if (document.body.classList.contains('tl-typing') === on) return;
  document.body.classList.toggle('tl-typing', on);
  if (on) setTimeout(() => { const vv = window.visualViewport, j = $('#tl-new-in'); if (j && vv && j.getBoundingClientRect().bottom > vv.offsetTop + vv.height - 4) j.scrollIntoView?.({block: 'nearest'}); }, 60);
}
document.addEventListener('focusin', e => { if (e.target.id === 'tl-new-in' || document.body.classList.contains('tl-typing')) tlKbSync(); });
document.addEventListener('focusout', e => { if (e.target.id === 'tl-new-in') setTimeout(tlKbSync, 0); });
// leaving an empty field (tap / click elsewhere) closes it; with text it stays until Enter / Escape / ✕
document.addEventListener('focusout', e => {
  if (e.target.id !== 'tl-new-in') return;
  setTimeout(() => { const a = document.activeElement, i = $('#tl-new-in'); if (S.tlNew && i && !i.value.trim() && !(a && a.closest?.('.tl-new'))) tlNewEnd(); }, 200);
});
function tlPickStart(id) {
  S.tlPick = {from: id};
  renderView();
  $(`.tl-bar[data-id="${id}"]`)?.focus();
}
function tlPickEnd() { if (!S.tlPick) return; const f = S.tlPick.from; S.tlPick = null; renderView(); $(`.tl-bar[data-id="${f}"]`)?.focus(); }
function tlPickDo(w) {
  const b = S.tlPick?.from; if (!b) return;
  if (w === b) { tlPickEnd(); return; }  // tapped the task itself again: leave the mode
  S.tlPick = null; renderView();
  tlConnect(b, w);
}
// mouse / pen: drag from the dot at a bar's end; a plain click on the dot starts the "Connect to…" mode
let tlLink = null;
function tlLinkStart(id, e) {
  const svg = $('#tl-deps'), from = $(`.tl-bar[data-id="${id}"]`);
  if (!svg || !from) return;
  const row = from.parentElement.parentElement;
  tlLink = {from: id, x0: e.clientX, y0: e.clientY, moved: false, over: null, sx: (parseFloat(from.style.left) || 0) + (parseFloat(from.style.width) || 0), sy: row.offsetTop + row.offsetHeight / 2};
  for (const b of $$('.tl-bar[data-id]')) b.classList.add(tlCanLink(id, +b.dataset.id) ? 'tl-ok' : 'tl-no');
  from.classList.add('tl-from');
  svg.closest('.tl')?.classList.add('linking');
}
function tlLinkMove(e) {
  const L = tlLink; if (!L) return;
  if (!L.moved && Math.hypot(e.clientX - L.x0, e.clientY - L.y0) < 4) return;
  L.moved = true;
  const svg = $('#tl-deps'); if (!svg) return;
  const sc = $('#tlscroll');
  if (sc) { const r = sc.getBoundingClientRect(); if (r.width && e.clientX > r.right - 28) sc.scrollLeft += 12; else if (r.width && e.clientX < r.left + 180) sc.scrollLeft -= 12; }
  const r = svg.getBoundingClientRect();
  const tb = e.target?.closest?.('.tl-bar[data-id]') || (document.elementFromPoint ? document.elementFromPoint(e.clientX, e.clientY)?.closest?.('.tl-bar[data-id]') : null);
  if (L.over && L.over !== tb) L.over.classList.remove('hot');
  L.over = tb && +tb.dataset.id !== L.from ? tb : null;
  let x = e.clientX - r.left, y = e.clientY - r.top;
  if (L.over) {
    L.over.classList.add('hot');
    const row = L.over.parentElement.parentElement; x = parseFloat(L.over.style.left) || 0; y = row.offsetTop + row.offsetHeight / 2;
  }
  const rb = $('.rubber', svg);
  if (rb) { rb.setAttribute('d', `M${L.sx},${L.sy}L${Math.round(x)},${Math.round(y)}`); rb.classList.toggle('no', !!L.over && L.over.classList.contains('tl-no')); }
}
function tlLinkEnd(e, cancel) {
  const L = tlLink; if (!L) return;
  tlLink = null;
  for (const b of $$('.tl-bar.tl-ok, .tl-bar.tl-no, .tl-bar.tl-from, .tl-bar.hot')) b.classList.remove('tl-ok', 'tl-no', 'tl-from', 'hot');
  $('.tl.linking')?.classList.remove('linking');
  $('#tl-deps .rubber')?.setAttribute('d', '');
  if (cancel) return;
  if (!L.moved) { tlPickStart(L.from); return; }
  const tb = L.over || e?.target?.closest?.('.tl-bar[data-id]');
  if (tb) tlConnect(L.from, +tb.dataset.id);
}

let tlDrag = null, tlDragged = false;
function tlApply(d, clientX) {
  const DW = tlDW(), n = Math.round((clientX - d.x) / DW), {b, mode, left, width} = d;
  d.days = n;
  if (mode === 'm') b.style.left = left + n * DW + 'px';
  if (mode === 'r') b.style.width = Math.max(DW - 4, width + n * DW) + 'px';
  if (mode === 'l') { const w = Math.max(DW - 4, width - n * DW); b.style.left = left + (width - w) + 'px'; b.style.width = w + 'px'; }
  const k = b.nextElementSibling;
  if (k && k.classList.contains('tl-knob')) k.style.left = (parseFloat(b.style.left) + parseFloat(b.style.width) + 11) + 'px';
  tlArrowsSoon();  // the arrows follow the bar while it is dragged
}
async function tlCommit(d) {
  const {t, mode, days, b} = d;
  b.classList.remove('drag', 'mode-l', 'mode-r', 'mode-m');
  if (!days) return;
  tlDragged = true; setTimeout(() => { tlDragged = false; }, 400);
  const s0 = tlStart0(t);
  let start = t.start || null, due = t.due;
  if (mode === 'm') { due = addDays(t.due, days); start = t.start ? addDays(t.start, days) : null; }
  if (mode === 'r') { due = addDays(t.due, days); if (due < s0) due = s0; if (!t.start && due !== t.due && due > t.due) start = t.due; }
  if (mode === 'l') { start = addDays(s0, days); if (start >= due) start = null; }
  const before = snapTask(t);
  let r;
  try { r = await patchTask(t.id, {start, due}, true); } catch { render(); return; }
  shiftUndo(before, r, tr('Date: {0}', start && start < due ? `${fmtDayAbs(start)} – ${fmtDayAbs(due)}` : dayLabel(due)));
}
// touch: hold a bar ~0.3 s, then drag. Grabbed near an end = change start / due, middle = move.
// Held and let go without moving: the bar menu (connect, remove dependencies, open).
let tlTouch = null;
document.addEventListener('touchstart', e => {
  const b = e.target.closest('.tl-bar'); if (!b) return;
  const t = S.tasks.get(+b.dataset.id); if (!t) return;
  if (S.tlPick) return;  // "Connect to…": a tap picks the task (click)
  const ed = canEdit(t);
  if (!ed && !depsOn()) return;
  const p = e.touches[0], r = b.getBoundingClientRect(), rel = p.clientX - r.left, edge = Math.min(28, r.width / 3);
  const mode = r.width >= 56 && rel < edge ? 'l' : r.width >= 56 && rel > r.width - edge ? 'r' : 'm';
  tlTouch = {b, t, mode, ed, x: p.clientX, y: p.clientY, x1: p.clientX, left: b.offsetLeft || parseFloat(b.style.left) || 0, width: b.offsetWidth || parseFloat(b.style.width) || 0, days: 0, active: false, moved: false};
  tlTouch.timer = setTimeout(() => {
    if (!tlTouch) return;
    tlTouch.active = true;
    if (ed) b.classList.add('drag', 'mode-' + mode);
    if (navigator.vibrate) navigator.vibrate(12);
  }, 300);
}, {passive: true});
document.addEventListener('touchmove', e => {
  if (!tlTouch) return;
  const p = e.touches[0];
  if (!tlTouch.active) { if (Math.hypot(p.clientX - tlTouch.x, p.clientY - tlTouch.y) > 8) { clearTimeout(tlTouch.timer); tlTouch = null; } return; }
  e.preventDefault();
  if (Math.abs(p.clientX - tlTouch.x1) > 6) tlTouch.moved = true;
  if (!tlTouch.ed) return;
  const sc = $('#tlscroll');
  if (sc) {  // scroll along at the edges, keep the finger's day under the finger
    const r = sc.getBoundingClientRect(), before = sc.scrollLeft;
    if (p.clientX > r.right - 28) sc.scrollLeft += 10;
    else if (p.clientX < r.left + 140) sc.scrollLeft -= 10;
    tlTouch.x -= sc.scrollLeft - before;
  }
  tlApply(tlTouch, p.clientX);
}, {passive: false});
function tlTouchEnd(e) {
  if (!tlTouch) return;
  clearTimeout(tlTouch.timer);
  const d = tlTouch; tlTouch = null;
  if (!d.active) return;
  tlDragged = true; setTimeout(() => { tlDragged = false; }, 400);
  if (e && e.cancelable) e.preventDefault();  // no click after the hold (it would land on the menu's backdrop)
  if (!d.moved || !d.days) { d.b.classList.remove('drag', 'mode-l', 'mode-r', 'mode-m'); if (!d.moved && e?.type === 'touchend') tlBarMenu(d.b); else render(); return; }
  tlCommit(d);
}
document.addEventListener('touchend', tlTouchEnd);
document.addEventListener('touchcancel', tlTouchEnd);
document.addEventListener('pointerdown', e => {
  const k = e.target.closest?.('.tl-knob');
  if (k) { if (e.pointerType !== 'touch' && e.button === 0) { e.preventDefault(); e.stopPropagation(); tlLinkStart(+k.dataset.knob, e); } return; }
  const b = e.target.closest('.tl-bar');
  if (!b || e.pointerType !== 'mouse' || e.button !== 0 || S.tlPick) return;
  const t = S.tasks.get(+b.dataset.id); if (!t || !canEdit(t)) return;
  tlDrag = {b, t, mode: e.target.classList.contains('l') ? 'l' : e.target.classList.contains('r') ? 'r' : 'm', x: e.clientX, left: b.offsetLeft || parseFloat(b.style.left) || 0, width: b.offsetWidth || parseFloat(b.style.width) || 0, days: 0};
  b.setPointerCapture?.(e.pointerId); b.classList.add('drag'); e.preventDefault();
});
document.addEventListener('pointermove', e => { if (tlLink) tlLinkMove(e); else if (tlDrag) tlApply(tlDrag, e.clientX); });
document.addEventListener('pointerup', e => {
  if (tlLink) { tlLinkEnd(e); return; }
  if (!tlDrag) return; const d = tlDrag; tlDrag = null;
  const nd = document.elementFromPoint?.(e.clientX, e.clientY)?.closest?.('.tl-ndhead, .tl-nd');
  if (nd && d.t.due) { d.b.classList.remove('drag', 'mode-l', 'mode-r', 'mode-m'); tlDragged = true; setTimeout(() => { tlDragged = false; }, 400); tlUndate(d.t.id); return; }
  tlCommit(d);
});
document.addEventListener('pointercancel', () => { if (tlLink) tlLinkEnd(null, true); });
document.addEventListener('contextmenu', e => {
  const sl = e.target.closest?.('#side .srow[data-list]');
  if ((sd || sdHeld) && e.target.closest?.('#side')) { e.preventDefault(); return; }  // the touch drag handles it
  if (sl && !S.listReorder) { e.preventDefault(); listMenu(sl, +sl.dataset.list); return; }
  const tg = e.target.closest?.('#side .srow[data-drop^="tag:"]');
  if (tg) { e.preventDefault(); tagMenu(tg, tg.dataset.drop.slice(4)); return; }
  const b = e.target.closest?.('.tl-bar[data-id]'); if (!b || isTouch()) return;
  e.preventDefault(); tlBarMenu(b);
});
// keyboard on a focused bar (capture: before the global shortcuts)
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && (tlLink || S.tlPick)) { e.preventDefault(); e.stopPropagation(); if (tlLink) tlLinkEnd(null, true); else tlPickEnd(); return; }
  const b = e.target.closest?.('.tl-bar[data-id]'); if (!b || e.ctrlKey || e.metaKey || e.altKey) return;
  const id = +b.dataset.id, k = e.key;
  if (k === 'Enter' || k === ' ') { if (S.tlPick) tlPickDo(id); else openDetail(id); }
  else if (k === 'ContextMenu' || (k === 'F10' && e.shiftKey)) tlBarMenu(b);
  else if ((k === 'c' || k === 'C') && dFor(S.tasks.get(id)) && canEdit(S.tasks.get(id)) && !S.tlPick) tlPickStart(id);
  else if ((k === 'd' || k === 'D') && !e.shiftKey && !S.tlPick && S.tasks.get(id)?.status === 0 && canEdit(S.tasks.get(id))) datePop(b, id);  // 2.18.0 review: move by keyboard
  else if (k === 'ArrowDown' || k === 'ArrowUp') { const all = $$('.tl-bar[data-id]'), i = all.indexOf(b); all[i + (k === 'ArrowDown' ? 1 : -1)]?.focus(); }
  else return;
  e.preventDefault(); e.stopPropagation();
}, true);
