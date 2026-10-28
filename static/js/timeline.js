/* Kalmido web client: The timeline (Gantt).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ timeline (gantt)
// Bars from start to due per open task. With the module "deps" (1.2) it is a small Gantt chart: arrows finish -> start
// from a task to the tasks waiting on it (SVG overlay, drawn after every render from the bars' own positions), a
// conflict colour when a task starts before a task it waits on is due, a hatch on waiting bars, linking by dragging
// the dot at a bar's end onto another bar (mouse / pen), long-press menu + "Connect to…" mode (touch), keyboard (focus
// a bar: Enter opens, C connects, Shift+F10 / context menu key = menu, arrow keys move between bars).
const tlDW = () => isRoadmap() ? rmDW() : Math.max(1, Math.round(tlPx() * (isMobile() ? 30 / 36 : 1) * uiZ()));  // the roadmap (D3) has its own zoom
const TL_DAYS = 70;
// 2.331.0 E (#3311): two fingers / Ctrl + wheel set the day width without steps (px at 100 %, kept on the device); zoomed
// out, the range grows so the timeline stays as wide as before
const TL_PX = 36, TL_PXMIN = 16, TL_PXMAX = 96;
const tlPx = () => { const v = S.tlLive || +LS.get('tlPx', TL_PX); return v > 0 ? Math.max(TL_PXMIN, Math.min(TL_PXMAX, v)) : TL_PX; };
const tlDays = () => Math.max(TL_DAYS, Math.ceil(TL_DAYS * TL_PX / tlPx() / 7) * 7);
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
  const tip = [mdPlain(t.title), when, wait ? blockedTitle(t) : '', conf ? tr('Starts before “{0}” is due', conf.title) : '', t.status === 2 ? tr('done') : ''].filter(Boolean).join(' · ');
  const mark = pick ? (tlCanLink(pick.from, t.id) ? ' tl-ok' : ' tl-no') + (pick.from === t.id ? ' tl-from' : '') : '';
  // 2.7.0 (K14): the label of a short bar goes right of it, or left of it near the end of the range; it never runs past the
  // range, and on the left it stops before the name column (max-width in px, the room there)
  // 2.13.0 (#453 P12): a title that would be cut inside its bar goes next to it too (not only bars under 110 px)
  const sh = w < 110 || String(t.title || '').length * 6.5 + 24 > w;
  const span = (diffDays(start, end) + 1) * DW, room = span - (x + w) - 24, lroom = x - 16, left = sh && room < 120 && lroom > room;
  const lmax = sh ? Math.max(40, Math.min(220, left ? lroom : room)) : 0;
  return `<div class="tl-bar p${t.priority} ${sh ? 'short' : ''}${left ? ' lbl-l' : ''}${wait ? ' wait' : ''}${conf ? ' conf' : ''}${ed ? '' : ' ro'}${t.status ? ' done' : ''}${mark}" data-id="${t.id}" style="left:${x + pad}px;width:${Math.max(TL_MINW, w - 2 * pad)}px" title="${esc(tip)}" tabindex="0" role="button" aria-label="${esc(tip)}">${wait ? ic('lock', 's tl-lk') : ''}<span${lmax ? ` style="max-width:${Math.round(lmax)}px"` : ''}>${mdTitleNL(t.title)}</span><i class="h l"></i><i class="h r"></i></div>` +
    (deps && ed && !pick && dFor(t) ? `<button type="button" class="tl-knob" data-knob="${t.id}" style="left:${x + Math.max(w, TL_MINW + 2 * pad) + 9}px" tabindex="-1" aria-hidden="true" title="${tr('Drag onto the task this one blocks')}"></button>` : '');
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
    (closed ? '' : ord.map(t => `<div class="tl-row tl-nd"><div class="tl-name" data-act="open" data-id="${t.id}">${t.parent_id && ids.has(t.parent_id) ? '<span class="muted">↳ </span>' : ''}<span class="tln">${mdTitleNL(t.title)}</span>${tlWaiting(t) ? `<span class="tl-wf" title="${esc(blockedTitle(t))}">${ic('lock', 's')}${esc(tr('blocked by {0}', blockedNames(t)))}</span>` : ''}</div><div class="tl-track ndt${ed && canEdit(t) ? ' ed' : ''}" data-nd="${t.id}" title="${ed && canEdit(t) ? esc(isTouch() ? tr('Tap a day to set the date; hold and drag for a range') : tr('Click a day to set the date, drag across days for a range')) : ''}"></div></div>`).join(''));
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
  const lbl = tr('Milestone: {0}, {1}', mdPlain(t.title), fmtDateLoc(t.due));
  return `<div class="tl-bar tl-dia short${ed ? '' : ' ro'}${t.status ? ' done' : t.due < today() ? ' over' : ''}" data-id="${t.id}" data-ms="1" style="left:${x - w / 2}px;width:${w}px" title="${esc(lbl)}" tabindex="0" role="button" aria-label="${esc(lbl)}"><span>${mdTitleNL(t.title)}</span></div>`;
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
  const DW = tlDW(), ND = tlDays();  // 2.331.0 E (#3311): ND days in the range
  if (!S.tlStart) S.tlStart = addDays(weekStartOf(today()), -7);
  const start = S.tlStart, end = addDays(start, ND - 1), t0 = today();
  const all = openTasks().filter(t => (!listId || t.list_id === listId) && (!inCal || cvxTaskOn(t)));  // 2.36.1 (#1127): the calendar's task switches
  const dated = all.filter(t => t.due && t.due >= start && (t.start || t.due) <= end);
  const undated = all.filter(t => !t.due).length;
  const ndOn = tlNdOn(listId), und = ndOn ? all.filter(t => !t.due) : [];
  // 2.7.1 (#410): milestones of project lists as markers in the list's row (a list with only milestones in range shows too)
  const msIn = l => l.kind === 'project' && (!listId || l.id === listId) ? (l.milestones || []).filter(m => m.day >= start && m.day <= end) : [];
  // 2.18.0 (#431): the list of a list timeline always has its group (an empty project can be planned right here)
  const groups = S.lists.filter(l => dated.some(t => t.list_id === l.id) || und.some(t => t.list_id === l.id) || listId === l.id).map(l => ({l, ts: dated.filter(t => t.list_id === l.id).sort((a, b) => (a.start || a.due).localeCompare(b.start || b.due) || bySort(a, b)), nd: und.filter(t => t.list_id === l.id)}));
  let head = '', months = '', lastM = '';
  for (let i = 0; i < ND; i++) {
    const d = addDays(start, i), dd = pd(d), wk = dd.getDay() === 0 || dd.getDay() === 6;
    head += `<div class="tl-d ${d === t0 ? 'today' : ''} ${wk ? 'we' : ''}"><span>${WD[dd.getDay()].slice(0, 1)}</span>${dd.getDate()}</div>`;
    if (d.slice(0, 7) !== lastM) { months += `<div class="tl-m" style="left:${i * DW}px">${MON[dd.getMonth()]} ${dd.getFullYear()}</div>`; lastM = d.slice(0, 7); }
  }
  months = tlStickyMonths(months, ND * DW);
  const todayX = diffDays(start, t0) * DW;
  const deps = depsOn(), pick = S.tlPick && deps ? S.tlPick : null;
  const bars = new Map();
  const bar = t => { bars.set(t.id, 1); return t.ms ? tlMsHtml(t, start, DW) : tlBarHtml(t, start, end, DW, pick, deps); };
  // 2.7.0 (K14): names cut with "…" (full name in the tooltip)
  // 2.18.0 (#462 / #431): a milestone task is a diamond in its own row, so the list row only marks the ones not drawn there
  const msMark = (l, ts) => msIn(l).filter(m => !tlMsDrawn(m, ts)).map(m => `<i class="tl-ms ${m.done ? 'done' : m.day < t0 ? 'over' : ''}" style="left:${diffDays(start, m.day) * DW + DW / 2}px" title="${esc(m.name + ' · ' + fmtDateLoc(m.day))}" role="img" aria-label="${esc(tr('Milestone') + ': ' + m.name + ', ' + fmtDateLoc(m.day))}"></i>`).join('');
  const geo = {s0: start, dw: DW, days: ND};
  // 2.18.0 (#462): inside a list the tasks are grouped by section (the list's order, "Unassigned" first as in the list
  // view); every list / section row is a place to draw a new task into (#431), "+ Add task" ends every list group
  const rows = groups.map(g => {
    const cr = canAddTo(g.l.id) && !pick;
    let h = `<div class="tl-row tl-grp" data-l="${g.l.id}"><div class="tl-name" title="${esc(lname(g.l))}"><span class="tln">${esc(lname(g.l))}</span></div>${tlCrTrack(g.l.id, null, 'g:' + g.l.id, geo, cr, msMark(g.l, g.ts))}</div>`;
    for (const sg of tlSecs(g.l.id, g.ts, !!listId)) {
      const shut = !!sg.key && S.collapsed.has(sg.key);
      if (sg.key) h += tlSecRow(g.l, sg, !shut, cr, geo, null);  // 2.18.0 review (R10): no roadmap top here (was an invalid style="top:px")
      if (!shut) h += sg.ts.map(t => `<div class="tl-row${t.ms ? ' tl-msrow' : ''}${sg.key ? ' tl-insec' : ''}"><div class="tl-name" data-act="open" data-id="${t.id}" title="${esc(mdPlain(t.title))}">${t.parent_id ? '<span class="muted">↳ </span>' : ''}<span class="tln">${mdTitleNL(t.title)}</span></div><div class="tl-track">${bar(t)}</div></div>`).join('');
    }
    return h + (g.nd.length ? tlNdRows(g.l, g.nd) : '') + (cr ? tlAddRow(g.l, geo, null) : '');
  }).join('');
  S.tlL = {bars};
  const from = pick && S.tasks.get(pick.from);
  const hint = isMobile() ? tr('Long-press and drag a bar: the middle moves it, the ends change start / due date.') : tr('Drag a bar to move it, drag its ends to change start / due date.');
  const dhint = !deps || ![...bars.keys()].some(i => dFor(S.tasks.get(i))) ? '' : isTouch() ? tr('Long-press a bar and let go for more: connect it to the task it blocks, remove a dependency.') : tr('Drag the dot at the end of a bar onto another bar: that task is then blocked by it. Click an arrow to remove it.');
  // 2.18.0 review: the footer also tells how to draw a new task (only where the user may add one)
  const chint = !pick && groups.some(g => canAddTo(g.l.id)) ? (isTouch() ? tr('Hold an empty spot in a project or section row, then drag to add a task, or tap “+”.') : tr('Drag across empty days in a project or section row to add a task, double-click a day or use “+”.')) : '';
  // 2.298.0 B (#3185): the operating sentences show once on a phone (hintOnce), after that they sit behind (i)
  const tlHow = [chint, hint, dhint].filter(Boolean).join(' ');
  const ndBtn = tlNdBtn(ndOn, undated);
  return `${inCal ? '' : `<div class="calbar"><h2>${tr('Timeline')}</h2>${ndBtn}<div class="calnav"><button class="iconbtn" data-act="tl-prev" title="${esc(tr('Previous period'))}" aria-label="${esc(tr('Previous period'))}">${ic('left')}</button><button class="btn sm" data-act="tl-today">${tr('Today')}</button><button class="iconbtn" data-act="tl-next" title="${esc(tr('Next period'))}" aria-label="${esc(tr('Next period'))}">${ic('right')}</button></div></div>`}
    ${from ? `<div class="tl-pick" role="status">${ic('deps', 's')}<span>${tr('Tap the task that “{0}” blocks', esc(from.title))}</span><span class="spacer"></span><button class="btn sm" data-act="tl-pick-list">${ic('search', 's')} ${tr('Pick from a list…')}</button><button class="btn sm" data-act="tl-pick-cancel">${tr('Cancel')}</button></div>` : ''}
    <div class="tl${pick ? ' picking' : ''}${DW < 22 ? ' tl-sm' : ''}" style="--dw:${DW}px;--days:${ND}">
    <div class="tl-scroll" id="tlscroll"><div class="tl-inner">
      <div class="tl-row tl-headrow" title="${esc(tr('Set a date range via “Start” in the date dialog.'))}"><div class="tl-name"></div><div class="tl-track tl-headtrack"><div class="tl-months">${months}</div><div class="tl-days">${head}</div></div></div>
      ${inCal ? tlCalRows(start, end, DW) : ''}
      ${rows || `<div class="tl-row"><div class="tl-name muted">${tr('No dated tasks')}</div><div class="tl-track"></div></div>`}
      <i class="tl-now" style="left:calc(var(--tl-name) + ${todayX + DW / 2}px)"></i>
      ${listId ? msIn(listById(listId) || {}).map(m => `<i class="tl-msl" style="left:calc(var(--tl-name) + ${diffDays(start, m.day) * DW + DW / 2}px)"></i>`).join('') : ''}
      ${deps ? '<svg class="tl-deps" id="tl-deps" aria-hidden="true" data-fl-fill></svg>' : ''}
    </div></div>
    ${hintOnce('tlrange', tr('Set a date range via “Start” in the date dialog.'))}${hintOnce('tlfoot', tlHow)}<div class="muted tl-foot">${undated && !ndOn ? trn('{0} task without a date is not shown.', '{0} tasks without a date are not shown.', undated) + ' ' : ''}<div class="shint" data-iilabel="${esc(tr('How to use the timeline'))}">${tlHow}</div></div></div>`;
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
  if (!depsOn()) { svg.innerHTML = ''; svg._flh = ''; return; }
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
    if (closed) tip = tr('“{0}” is blocked by “{1}” (done)', title(w), title(b));
    else if (conf) tip = tr('“{0}” starts before “{1}” is due', title(w), title(b));
    else tip = tr('“{0}” is blocked by “{1}”', title(w), title(b));
    if (!(W && B)) tip += ' · ' + tr('outside this view');
    out += `<g class="dep ${kind}${W && B ? '' : ' stub'}" data-dep="${w}:${b}"><title>${esc(tip)}</title><path class="hit" d="${d}"/><path class="ln" d="${d}" marker-end="url(#tl-ah-${kind})"/>${W && B ? '' : `<circle class="st" cx="${W ? Math.max(0, W.x - 20) : B.x + B.w + 20}" cy="${W ? W.y : B.y}" r="2.5"/>`}</g>`;
  }
  const mk = k => `<marker id="tl-ah-${k}" class="ah ${k}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0.5L7.5,4L0,7.5z"/></marker>`;
  const h = `<defs>${mk('ok')}${mk('conf')}${mk('done')}</defs>${out}<path class="rubber" d=""/>`;
  if (svg._flh !== h || !svg.firstChild) { svg.innerHTML = h; svg._flh = h; }  // 2.46.2 (#1718): the arrows stay when nothing moved
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
  const ro = el.firstElementChild || el; if (tlRO && el.__ro !== ro) { if (el.__ro?.nodeType) tlRO.unobserve(el.__ro); el.__ro = ro; tlRO.observe(ro); }  // 2.46.2 (#1718): a morph may bring another first child
  tlArrows();
}

// ---- linking: a task may wait on another one when I can change it; the server checks again (cycles, rights)
// 2.65.0 (#1823): tlReaches is in lazyload.js (the list's drag asks it; this file loads on demand)
function tlCanLink(b, w) {
  const wt = S.tasks.get(w);
  return b !== w && !!wt && canEdit(wt) && dFor(wt) && dFor(S.tasks.get(b)) && !(wt.blockers || []).includes(b) && !tlReaches(b, w);
}
async function tlConnect(b, w) {
  const wt = S.tasks.get(w), bt = S.tasks.get(b);
  if (!wt || !bt) return;
  if ((wt.blockers || []).includes(b)) { toast(tr('“{0}” is already blocked by “{1}”', wt.title, bt.title)); return; }
  try { await api('POST', '/api/deps', {task_id: w, blocker_id: b}); } catch { return; }  // api() showed the server's reason
  await load(); render();
  if (S.sel === w || S.sel === b) loadDeps(S.sel);
  toast(tr('“{0}” is now blocked by “{1}”', wt.title, bt.title));
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
    const rm = [...(canEdit(t) ? (t.blockers || []).map(b => S.tasks.get(b)).filter(Boolean).map(b => ({label: tr('No longer blocked by “{0}”', nm(b.title)), icon: 'x', fn: () => tlUnlink(id, b.id)})) : []),
      ...openTasks().filter(x => (x.blockers || []).includes(id) && canEdit(x)).map(x => ({label: tr('“{0}” is no longer blocked', nm(x.title)), icon: 'x', fn: () => tlUnlink(x.id, id)}))];
    if (rm.length) items.push('-', ...rm);
    if (dch_canPull(t)) items.push('-', {label: tr('Pull the chain in'), icon: 'deps', fn: () => dch_pull(id)});  // 2.67.0 B (#1865)
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
// 2.193.0 B (#2219): every timeline drag scrolls #tlscroll sideways at its edges (left: right of the sticky names), also
// while the finger stays still; the day under the finger follows (ndDay measures the track anew)
const tlSc = () => $('#tlscroll');
const tlNameW = () => { const sc = tlSc(); return (sc && $('.tl-row:not(.tl-headrow) .tl-name', sc)?.offsetWidth) || 0; };
const tlDrgScroll = {scrollX: tlSc, scrollXInset: tlNameW, edge: 40, step: 12};
function ndShow(d) {
  if (!d.el) { d.el = document.createElement('div'); d.el.className = 'tl-bar ndraw'; d.tr.appendChild(d.el); }
  const a = d.d0 < d.d1 ? d.d0 : d.d1, b = d.d0 < d.d1 ? d.d1 : d.d0, g = ndGeo(d.tr), DW = g.dw;
  d.el.style.left = diffDays(g.s0, a) * DW + 2 + 'px'; d.el.style.width = Math.max(TL_MINW, (diffDays(a, b) + 1) * DW - 4) + 'px';
  d.el.textContent = a < b ? `${fmtDayAbs(a)} – ${fmtDayAbs(b)}` : fmtDayAbs(b);
}
// 2.193.0 B (#2219): finger, mouse and pen on drag.js. Mouse / pen: press and drag (a click = that day); touch: a tap
// sets the day, hold ~0.3 s, then drag for a range (a swipe during the hold scrolls)
drg_attach(document, {hold: 300, onTarget: true, accept: () => true, ...tlDrgScroll,
  start(el, x, y, kind, ev) {
    const tr_ = el.closest?.('.tl-track.ndt.ed'); if (!tr_) return null;
    const d0 = ndDay(tr_, x), d = {tr: tr_, id: +tr_.dataset.nd, d0, d1: d0, el: null, touch: kind === 'touch'};
    if (!d.touch) { ndShow(d); ev.preventDefault(); }
    return d;
  },
  onHold: d => { ndShow(d); if (navigator.vibrate) navigator.vibrate(12); },
  // 2.87.9 (#1965): drawn again only when the day under the pointer changes (no measuring right after a write)
  onMove: (d, x) => { const d1 = ndDay(d.tr, x); if (d1 !== d.d1 || !d.el) { d.d1 = d1; ndShow(d); } },
  onDrop: d => tlDraw(d.id, d.d0, d.d1),
  onTap: d => tlDraw(d.id, d.d0, d.d0),  // a click, or a hold without moving: that day
  onCancel: (d, up) => { if (up) tlDraw(d.id, d.d0, d.d0); else d.el?.remove(); },  // up: a quick tap (before the hold)
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
let tlCr = null;  // drawing a new task: {tr, d0, d1, el, touch, held}
function crShow(d) {
  if (!d.el) { d.el = document.createElement('div'); d.el.className = 'tl-ghost'; d.el.setAttribute('aria-hidden', 'true'); d.tr.appendChild(d.el); }
  const a = d.d0 < d.d1 ? d.d0 : d.d1, b = d.d0 < d.d1 ? d.d1 : d.d0, g = ndGeo(d.tr);
  d.el.style.left = diffDays(g.s0, a) * g.dw + 2 + 'px'; d.el.style.width = Math.max(TL_MINW, (diffDays(a, b) + 1) * g.dw - 4) + 'px';
  d.el.textContent = a < b ? `${fmtDayAbs(a)} – ${fmtDayAbs(b)}` : fmtDayAbs(b);
}
// 2.193.0 B (#2219): on drag.js. Touch: the events are followed on the touched element (onTarget): a re-render during
// the hold (sync, a server answer) replaces the track, the events then go to the old, detached node (2.21.0)
drg_attach(document, {hold: 450, onTarget: true, ...tlDrgScroll,
  start(el, x, y, kind, ev) {
    const tr_ = el.closest?.('.tl-track.tl-cr'); if (!tr_ || S.tlPick || !tlCrFree(ev)) return null;
    const d0 = ndDay(tr_, x);
    tlCr = {tr: tr_, d0, d1: d0, el: null, touch: kind === 'touch', held: false};
    if (!tlCr.touch) ev.preventDefault();  // no text selection while drawing
    return tlCr;
  },
  accept: (d, dx) => d.touch || Math.abs(dx) >= 4 || null,
  onHold: d => { d.held = true; tlCrLive(); crShow(d); if (navigator.vibrate) navigator.vibrate(12); },
  onStart: d => { d.held = true; },
  onMove: (d, x) => { tlCrLive(); const d1 = ndDay(d.tr, x); if (d.el && d1 === d.d1) return; d.d1 = d1; crShow(d); },  // 2.87.9 (#1965): only on a new day
  onDrop: d => { tlCrDone(d); if (d.touch || d.d0 !== d.d1) tlNewOpen(d.tr, d.d0, d.d1); },
  onTap: d => { tlCrDone(d); if (d.touch) tlNewOpen(d.tr, d.d0, d.d0); },  // touch: held and let go = that day; a mouse click does nothing (double-click = one day)
  onCancel: d => tlCrDone(d),  // a quick tap, a swipe (the timeline scrolls), Esc
});
function tlCrDone(d) { if (tlCr === d) tlCrLive(); d.el?.remove(); if (tlCr === d) tlCr = null; }
document.addEventListener('dblclick', e => {
  const tr_ = e.target.closest?.('.tl-track.tl-cr'); if (!tr_ || S.tlPick || !tlCrFree(e)) return;
  e.preventDefault(); const d = ndDay(tr_, e.clientX); tlNewOpen(tr_, d, d);
});
// the track of the gesture after a re-render (same row key); the ghost is drawn anew there
function tlCrLive() {
  if (!tlCr || tlCr.tr.isConnected) return;
  const n = $(`.tl-track.tl-cr[data-k="${rmEsc(tlCr.tr.dataset.k || '')}"]`);
  if (n) { tlCr.tr = n; tlCr.el = null; }
}
document.addEventListener('contextmenu', e => { if (tlCr?.touch && tlCr.held) e.preventDefault(); });
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
  const tb = L.over || (e?.target || tlLinkAt)?.closest?.('.tl-bar[data-id]');
  if (tb) tlConnect(L.from, +tb.dataset.id);
}

let tlDragged = false;
function tlApply(d, px) {
  const DW = tlDW(), n = Math.round(px / DW), {b, mode, left, width} = d;
  if (d.n1 === n) return;  // 2.87.9 (#1965): the bar snaps to days: nothing to do until the pointer reaches another day
  d.n1 = n; d.days = n;
  if (mode === 'm') b.style.left = left + n * DW + 'px';
  if (mode === 'r') b.style.width = Math.max(DW - 4, width + n * DW) + 'px';
  if (mode === 'l') { const w = Math.max(DW - 4, width - n * DW); b.style.left = left + (width - w) + 'px'; b.style.width = w + 'px'; }
  const k = b.nextElementSibling;
  if (k && k.classList.contains('tl-knob')) k.style.left = (parseFloat(b.style.left) + parseFloat(b.style.width) + 11) + 'px';
  tlArrowsSoon();  // the arrows follow the bar while it is dragged
  dch_preview(d);  // 2.67.0 B (#1865): the tasks that will move along slide with it
}
async function tlCommit(d) {
  const {t, mode, days, b} = d;
  b.classList.remove('drag', 'mode-l', 'mode-r', 'mode-m');
  dch_clear(d);
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
  const msg = tr('Date: {0}', start && start < due ? `${fmtDayAbs(start)} – ${fmtDayAbs(due)}` : dayLabel(due));
  // 2.67.0 B (#1865): earlier: the chain stays (said in the one toast; a second toast would replace its Undo - review),
  // "Pull the chain in" stays in the bar menu and the task panel
  shiftUndo(before, r, dch_afterEarlier(t, t.due, due) ? [msg, tr('The waiting tasks stay where they are')].join(' · ') : msg);
}
// 2.193.0 B (#2219): bars on drag.js, one way for finger and mouse. Touch: hold a bar ~0.3 s, then drag; grabbed near
// an end = change start / due, middle = move; held and let go without moving = the bar menu (connect, remove
// dependencies, open). Mouse: the ends (handles) or the middle; dropped on "No date" = the date goes. The bar follows the
// pointer by days, also while the timeline scrolls under it at the edges.
function tlBarReset(d) { d.b.classList.remove('drag', 'mode-l', 'mode-r', 'mode-m'); dch_clear(d); }
drg_attach(document, {hold: 300, onTarget: true, ...tlDrgScroll,
  start(el, x, y, kind, ev) {
    const b = el.closest?.('.tl-bar'); if (!b || S.tlPick) return null;  // "Connect to…": a tap picks the task (click)
    const t = S.tasks.get(+b.dataset.id); if (!t) return null;
    const ed = canEdit(t), touch = kind === 'touch';
    if (touch ? !ed && !depsOn() : kind !== 'mouse' || !ed) return null;
    let mode = 'm';
    if (touch) { const r = b.getBoundingClientRect(), rel = x - r.left, edge = Math.min(28, r.width / 3); mode = r.width >= 56 && rel < edge ? 'l' : r.width >= 56 && rel > r.width - edge ? 'r' : 'm'; }
    else { mode = el.classList.contains('l') ? 'l' : el.classList.contains('r') ? 'r' : 'm'; ev.preventDefault(); }
    return {b, t, mode, ed, touch, x0: x, sl0: tlSc()?.scrollLeft || 0, left: b.offsetLeft || parseFloat(b.style.left) || 0, width: b.offsetWidth || parseFloat(b.style.width) || 0, days: 0};
  },
  accept: (d, dx, dy) => (d.touch ? Math.abs(dx) > 6 : Math.hypot(dx, dy) >= 4) || null,
  onHold: d => { if (d.ed) d.b.classList.add('drag', 'mode-' + d.mode); if (navigator.vibrate) navigator.vibrate(12); },
  onStart: d => { if (d.ed) d.b.classList.add('drag', ...(d.touch ? ['mode-' + d.mode] : [])); },
  onMove: (d, x) => { if (d.ed) tlApply(d, x - d.x0 + (tlSc()?.scrollLeft || 0) - d.sl0); },
  onDrop: (d, x, y) => {
    tlDragged = true; setTimeout(() => { tlDragged = false; }, 400);
    const nd = !d.touch && document.elementFromPoint?.(x, y)?.closest?.('.tl-ndhead, .tl-nd');
    if (nd && d.t.due) { tlBarReset(d); tlUndate(d.t.id); return; }
    if (!d.days) { tlBarReset(d); if (d.touch) render(); return; }
    tlCommit(d);
  },
  onTap: d => { tlBarReset(d); if (d.touch) { tlDragged = true; setTimeout(() => { tlDragged = false; }, 400); tlBarMenu(d.b); } },
  onCancel: d => { tlBarReset(d); if (d.days) render(); },  // Esc, a second finger: the bar back where it was
});
// mouse / pen: drag from the dot at a bar's end onto another bar; a plain click on the dot starts the "Connect to…" mode
// 2.87.9 (#1965): the connecting line follows once per frame
const tlLinkF = rafThrottle(e => tlLinkMove(e));
let tlLinkAt = null;  // the element under the pointer (the target where elementFromPoint is missing)
for (const k of ['pointermove', 'pointerup']) document.addEventListener(k, e => { if (tlLink) tlLinkAt = /** @type {any} */ (e.target); }, true);
drg_attach(document, {touch: false, threshold: 4, ...tlDrgScroll,
  start(el, x, y, kind, ev) {
    const k = el.closest?.('.tl-knob'); if (!k) return null;
    ev.preventDefault(); ev.stopPropagation();
    tlLinkAt = null; tlLinkStart(+k.dataset.knob, {clientX: x, clientY: y});
    return tlLink;
  },
  onMove: (d, x, y) => tlLinkF({clientX: x, clientY: y, target: tlLinkAt}),
  onDrop: () => { tlLinkF.flush(); tlLinkEnd(); },
  onTap: () => tlLinkEnd(),  // not moved: "Connect to…"
  onCancel: () => { tlLinkF.cancel(); tlLinkEnd(null, true); },
});
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

// ---- 2.331.0 E (#3311): two fingers / Ctrl + wheel / Safari's pinch on a timeline (list, calendar, roadmap) zoom only it:
// the day width follows without steps (the roadmap changes week / month / quarter beyond a bound), the day under the
// fingers stays under them; the page keeps its size. Kept on release: the roadmap in its prefs, the timeline on the device
const tlz_s0 = d => d.rm ? S.rmStart : S.tlStart;
pz_attach($('#view') || document, {
  area: t => t?.closest('#view .tl') || null,
  start(a, x) {
    const sc = tlSc(); if (!sc) return null;
    if (drg_cur) drg_cancel();  // a bar's drag / hold ends: two fingers zoom
    const rm = isRoadmap() && !!S.rmV, dw = rm ? S.rmV.G.dw : tlDW(), s0 = rm ? S.rmV.G.start : S.tlStart;
    const left = sc.getBoundingClientRect().left + tlNameW(), pos = Math.max(0, (x - left + sc.scrollLeft) / dw);
    return {rm, left, px0: rm ? rmPx() : tlPx(), px: 0, at: addDays(s0, Math.floor(pos)), fr: pos - Math.floor(pos)};
  },
  move(d, k, x) {
    const px = d.rm ? Math.max(RM_PXMIN, Math.min(RM_PXMAX, d.px0 * k)) : Math.max(TL_PXMIN, Math.min(TL_PXMAX, d.px0 * k));
    if (Math.abs(px - (d.px || d.px0)) < .05) return;
    d.px = px;
    if (d.rm) {
      const z = rmZFor(px);
      if (S.rmStartZ !== z) { S.rmStart = addDays(weekStartOf(d.at), -RM_Z[z].lead); S.rmStartZ = z; }  // the day stays in the new zoom's range
      S.rmLive = {z, px};
    } else S.tlLive = px;
    // the range starts early enough for the day under the fingers to stay where it is
    const dw = tlDW(), off = x - d.left, lack = off / dw - (diffDays(tlz_s0(d), d.at) + d.fr);
    if (lack > 0) { const s = addDays(tlz_s0(d), -7 * Math.ceil(lack / 7)); if (d.rm) S.rmStart = s; else S.tlStart = s; }
    renderView();
    const sc = tlSc(); if (sc) sc.scrollLeft = Math.max(0, (diffDays(tlz_s0(d), d.at) + d.fr) * dw - off);
  },
  end(d) {
    if (d.rm) {
      const L = S.rmLive; S.rmLive = null;
      if (L) { const f = Math.round(L.px / RM_Z[L.z].px * 1000) / 1000; rmSet({z: L.z, zf: f === 1 ? undefined : f}, ''); }
    } else if (S.tlLive) { LS.set('tlPx', Math.round(S.tlLive * 10) / 10); S.tlLive = null; }
  },
});
