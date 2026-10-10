/* Kalmido web client: The roadmap.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ roadmap (package D3)
// "All" as a timeline (view switch List | Timeline in the header of "All"; needs only the timeline module): every list
// with its dated tasks, lists grouped by folder, one collapsible header row per list with a summary bar from the
// earliest start (or due) to the latest due of its OPEN dated tasks, filled by the list progress (progress module).
// Dragging a summary bar (mouse / pen), or long-press > "Move project by…" (touch; also in the bar's menu), moves every
// open dated task of the list by the same number of days on the server (POST /api/lists/<id>/shift: one transaction,
// dependents in other lists follow where their list has "Move dependent tasks along" on, one undo for everything).
// Zoom week / month / quarter. Rows are virtualised: a fixed row height, only the rows in view (+ a margin) are in the
// DOM and every position is computed from the dates and the row index (no layout reads), so 50 projects with 1000
// tasks stay smooth. Arrows are the D2 ones; into a collapsed list (or folder) they attach to its summary bar, merged
// into one arrow with a count. Prefs (view, zoom, filters, collapse state) are the user setting "roadmap" (json).
const RM_Z = {week: {px: 36, step: 14, days: 84, lead: 7}, month: {px: 12, step: 28, days: 196, lead: 14}, quarter: {px: 4, step: 91, days: 546, lead: 28}};
const RM_SHIFT_MAX = 500;  // = SHIFT_MAX_TASKS on the server
const rmEsc = v => String(v).replace(/["\\]/g, '\\$&');  // inside a quoted attribute selector
function rmP() {
  const src = S.rmLocal ?? S.settings.roadmap ?? '';
  if (!S.rmPc || S.rmPc.src !== src) {
    let v = {}; try { v = JSON.parse(src || '{}'); } catch { v = {}; }
    S.rmPc = {src, v: v && typeof v === 'object' && !Array.isArray(v) ? v : {}};
  }
  return S.rmPc.v;
}
let rmSaveT = 0;
// merge into the prefs, redraw, save (debounced; kept locally until the server has it, so a poll cannot undo it)
function rmSet(patch, how = 'view') {
  const v = {...rmP(), ...patch};
  for (const k of Object.keys(v)) if (v[k] === undefined) delete v[k];
  S.rmLocal = JSON.stringify(v);
  if (how === 'all') render(); else if (how === 'view') { renderTop(); renderView(); }
  clearTimeout(rmSaveT);
  rmSaveT = setTimeout(async () => {
    const val = S.rmLocal; if (val == null) return;
    try { await api('PATCH', '/api/settings', {roadmap: val}); S.settings.roadmap = val; } catch { return; }  // offline: stays local
    if (S.rmLocal === val) S.rmLocal = null;
  }, 350);
}
const isRoadmap = () => S.route.mod === 'tasks' && S.route.key === 'all' && feat('timeline') && rmP().v === 'timeline';
const rmZoom = () => RM_Z[rmP().z] ? rmP().z : 'month';
const rmDW = () => RM_Z[rmZoom()].px * uiZ() * (isMobile() ? 5 / 6 : 1);
const rmProjects = () => S.lists.filter(l => !l.archived && !l.is_inbox && l.kind === 'project');
const rmPO = () => rmP().po ?? rmProjects().length > 0;   // "Projects only": default on as soon as one project exists
const rmHD = () => rmP().hd !== false;                     // "Hide done": default on
const rmNdOn = () => rmP().nd !== false;                   // 2.0.6 (#189) "No date" rows in open lists: default on
const rmWho = () => collab() ? rmP().who || '' : '';
const rmWhoOk = t => { const w = rmWho(); return !w || (w === 'me' ? !!S.me && t.assignee_id === S.me.id : w === 'none' ? !t.assignee_id : t.assignee_id === +w); };
function rmSpan(ts) { let s = null, e = null; for (const t of ts) { const a = tlStart0(t); if (!s || a < s) s = a; if (!e || t.due > e) e = t.due; } return s ? {s, e} : null; }
function rmGeo() {
  const z = rmZoom();
  if (!S.rmStart || S.rmStartZ !== z) { S.rmStart = addDays(weekStartOf(today()), -RM_Z[z].lead); S.rmStartZ = z; }
  const days = RM_Z[z].days;
  return {z, dw: rmDW(), start: S.rmStart, end: addDays(S.rmStart, days - 1), days, rh: Math.round((isTouch() ? 52 : 44) * uiZ()), hh: Math.round(52 * uiZ())};
}
const rmX = (G, d) => diffDays(G.start, d) * G.dw;
const rmCrGeo = G => ({s0: G.start, dw: G.dw, days: G.days});  // 2.18.0 (#431): the geometry a new task is drawn in
// rows: f = folder, g = list (header row with the summary bar), t = task (only in an expanded list)
function rmModel() {
  const P = rmP(), po = rmPO(), hd = rmHD(), who = rmWho(), sel = (P.ls || []).length ? new Set(P.ls) : null;
  let lists = [inbox(), ...sideOrder()].filter(l => l && !l.archived && (!po || l.kind === 'project') && (!sel || sel.has(l.id)));
  const per = new Map(lists.map(l => [l.id, {open: [], shown: [], undated: 0, und: []}]));
  for (const t of S.tasks.values()) {
    const g = per.get(t.list_id); if (!g || t.deleted_at) continue;
    if (!t.due) { if (t.status === 0) { g.undated++; if (rmWhoOk(t)) g.und.push(t); } continue; }
    if (t.status === 0) g.open.push(t);
    if ((t.status === 0 || (t.status === 2 && !hd)) && rmWhoOk(t)) g.shown.push(t);
  }
  // projects always show up (a new one has no dates yet: plan it here), other lists only with dated tasks;
  // with an assignee filter only the lists with a matching task
  lists = lists.filter(l => { const g = per.get(l.id); return who ? g.shown.length > 0 : g.open.length > 0 || g.shown.length > 0 || l.kind === 'project'; });
  const nGroups = lists.length, def = P.def === 'c' ? 0 : P.def === 'e' ? 1 : nGroups < 5 ? 1 : 0;
  const isOpen = k => { const v = (P.t || {})[k]; return v == null ? (k.startsWith('f:') ? 1 : def) : v; };
  const rows = [], taskRow = new Map(), listNode = new Map(), groupOf = new Map();
  const push = r => { r.i = rows.length; rows.push(r); return r; };
  const addList = (l, fr) => {
    const g = per.get(l.id), open = !!isOpen('l' + l.id), span = rmSpan(g.open);
    const ts = g.shown.sort((a, b) => tlStart0(a).localeCompare(tlStart0(b)) || a.due.localeCompare(b.due) || bySort(a, b));
    ts.forEach(t => groupOf.set(t.id, l.id));
    if (fr) { listNode.set(l.id, fr); return span; }
    const r = push({type: 'g', l, key: 'l' + l.id, open, span, n: g.open.length, undated: g.undated, ts});
    listNode.set(l.id, r);
    // 2.18.0 (#462): inside an open list its sections (header rows, foldable per device), "+ Add task" after them (#431)
    if (open) for (const sg of tlSecs(l.id, ts, l.kind === 'project')) {
      const shut = !!sg.key && S.collapsed.has(sg.key);
      if (sg.key) push({type: 's', l, sg, key: sg.key, open: !shut, n: sg.ts.length});
      if (!shut) for (const t of sg.ts) taskRow.set(t.id, push({type: 't', t, l, insec: !!sg.key}));
    }
    if (open && canAddTo(l.id)) push({type: 'a', l});
    if (open && g.und.length && rmNdOn()) {  // 2.0.6 (#189): "No date (n)" at the end of an open list, like the timeline
      const nk = 'rmnd:' + l.id, shut = S.collapsed.has(nk);
      push({type: 'nh', l, key: nk, open: !shut, n: g.und.length});
      if (!shut) { const ids = new Set(g.und.map(t => t.id)), ord = [];
        const add = t => { ord.push(t); for (const k of g.und.filter(x => x.parent_id === t.id).sort(bySort)) add(k); };
        for (const t of g.und.filter(x => !x.parent_id || !ids.has(x.parent_id)).sort(bySort)) add(t);
        for (const t of ord) push({type: 'u', t, l, sub: !!t.parent_id && ids.has(t.parent_id)}); }
    }
    return span;
  };
  lists.filter(l => l.is_inbox || !l.folder).forEach(l => addList(l, null));
  for (const f of folderNames()) {
    const fl = lists.filter(l => !l.is_inbox && l.folder === f); if (!fl.length) continue;
    const fr = push({type: 'f', f, key: 'f:' + f, open: !!isOpen('f:' + f), n: fl.length, span: null});
    let s = null, e = null;
    for (const l of fl) { const sp = addList(l, fr.open ? null : fr); if (sp) { if (!s || sp.s < s) s = sp.s; if (!e || sp.e > e) e = sp.e; } }
    fr.span = s ? {s, e} : null;
  }
  return {rows, lists, taskRow, listNode, groupOf, nGroups, po, def};
}
function rmHead(G) {
  const t0 = today();
  let top = '', bot = '', lastM = '', lastQ = '';
  if (G.z === 'week') {
    for (let i = 0; i < G.days; i++) {
      const d = addDays(G.start, i), dd = pd(d), we = dd.getDay() === 0 || dd.getDay() === 6;
      bot += `<div class="tl-d ${d === t0 ? 'today' : ''} ${we ? 'we' : ''}"><span>${WD[dd.getDay()].slice(0, 1)}</span>${dd.getDate()}</div>`;
      if (d.slice(0, 7) !== lastM) { top += `<div class="tl-m" style="left:${i * G.dw}px">${MON[dd.getMonth()]} ${dd.getFullYear()}</div>`; lastM = d.slice(0, 7); }
    }
    return [tlStickyMonths(top, G.days * G.dw), bot];
  }
  for (let i = 0; i < G.days; i += 7) {  // week columns (month: the first weekday's date, quarter: empty ticks)
    const d = addDays(G.start, i), cur = d <= t0 && t0 < addDays(d, 7);
    bot += `<div class="rm-w ${cur ? 'today' : ''}" title="${esc(tr('Week {0}', isoWeek(addDays(d, 3))))}">${G.z === 'month' ? pd(d).getDate() : ''}</div>`;
  }
  for (let i = 0; i < G.days; i++) {  // month labels (quarter: in the lower row, the quarters above)
    const d = addDays(G.start, i), dd = pd(d), m = d.slice(0, 7), q = `${dd.getFullYear()}-${Math.floor(dd.getMonth() / 3)}`;
    if (m === lastM) continue;
    lastM = m;
    if (G.z === 'month') top += `<div class="tl-m" style="left:${i * G.dw}px">${MON[dd.getMonth()]} ${dd.getFullYear()}</div>`;
    else {
      bot += `<div class="rm-ml" style="left:${i * G.dw}px">${MONS[dd.getMonth()]}</div>`;
      if (q !== lastQ) { top += `<div class="tl-m" style="left:${i * G.dw}px">${tr('Q{0} {1}', Math.floor(dd.getMonth() / 3) + 1, dd.getFullYear())}</div>`; lastQ = q; }
    }
  }
  return [tlStickyMonths(top, G.days * G.dw), bot];
}
// the span bar of a list (or a folder: thin, no drag) clipped to the window; caps only at real ends
function rmBarBox(G, sp) {
  const W = G.days * G.dw, x1 = rmX(G, sp.s), x2 = rmX(G, sp.e) + G.dw;
  if (x2 <= 0 || x1 >= W) return null;
  return {L: Math.max(x1, -4), R: Math.min(x2, W + 4), cl: x1 < 0, cr: x2 > W};
}
function rmPct(l) { const p = l.progress || {done: 0, total: 0}; return progressFor(l) && p.total > 0 ? Math.round(p.done / p.total * 100) : null; }
function rmSumHtml(G, r) {
  const l = r.l, sp = r.span;
  if (!sp) return `<span class="rm-none">${r.undated ? trn('{0} task without a date', '{0} tasks without a date', r.undated) : tr('No dates yet')}</span>`;
  const b = rmBarBox(G, sp), when = `${fmtDayAbs(sp.s)} – ${fmtDayAbs(sp.e)}`;
  if (!b) return `<button type="button" class="rm-off ${rmX(G, sp.s) < 0 ? 'l' : 'r'}" data-act="rm-jump" data-d="${sp.s}" title="${esc(tr('Show {0}', when))}">${ic(rmX(G, sp.s) < 0 ? 'left' : 'right', 's')}<span>${esc(when)}</span></button>`;
  const pct = rmPct(l), col = cssColor(l.color), em = leadEmoji(l.name), ed = canEditList(l.id);
  const tip = [lname(l), when, trn('{0} open task', '{0} open tasks', r.n), pct != null ? tr('{0} % done', pct) : ''].filter(Boolean).join(' · ');
  return `<div class="rm-sum${ed ? '' : ' ro'}${b.cl ? ' cl-l' : ''}${b.cr ? ' cl-r' : ''}" data-lid="${l.id}" style="left:${b.L}px;width:${b.R - b.L}px${col ? ';--lc:' + col : ''}" tabindex="0" role="button" aria-haspopup="menu" aria-label="${esc(tip)}" title="${esc(tip + (ed ? ' · ' + (isTouch() ? tr('Long-press to move the project') : tr('Drag to move the whole project')) : ''))}"><i class="rm-fill" style="width:${pct ?? 0}%"></i><i class="cap l"></i><i class="cap r"></i></div>` +
    `<span class="rm-lbl" style="left:${b.R + 6}px">${em ? (sbiMode() === 'emoji' ? `<span class="rm-em">${em}</span>` : licMark(l, 'rmlic')) : ''}${pct != null ? `<b>${pct}%</b>` : ''}<span class="rm-dt">${esc(when)}</span></span>`;
}
// 2.7.2: the milestones of a project (2.7.1, #410) as markers in its summary row of the "All" timeline too
function rmMsHtml(G, l, r) {
  if (l.kind !== 'project') return '';
  const t0 = today();
  // 2.18.0: an open list shows its milestone tasks as diamonds in their rows: no second marker for them here
  return (l.milestones || []).filter(m => m.day >= G.start && m.day <= G.end && !(r?.open && tlMsDrawn(m, r.ts))).map(m => `<i class="tl-ms rm-ms ${m.done ? 'done' : m.day < t0 ? 'over' : ''}" style="left:${rmX(G, m.day) + G.dw / 2}px" title="${esc(m.name + ' · ' + fmtDateLoc(m.day))}" role="img" aria-label="${esc(tr('Milestone') + ': ' + m.name + ', ' + fmtDateLoc(m.day))}"></i>`).join('');
}
function rmRowHtml(G, M, r) {
  const y = G.hh + r.i * G.rh;
  if (r.type === 'f') {
    const b = r.span && rmBarBox(G, r.span);
    return `<div class="tl-row rm-row rm-f" style="top:${y}px"><div class="tl-name rm-gname" data-act="rm-toggle" data-key="${esc(r.key)}" role="button" tabindex="0" aria-expanded="${r.open}">${ic('chev', 's rm-car' + (r.open ? '' : ' closed'))}${ic('folder', 's')}<span class="n">${esc(fDisp(r.f))}</span><span class="c">${r.n}</span></div><div class="tl-track">${b ? `<i class="rm-fspan" style="left:${b.L}px;width:${b.R - b.L}px"></i>` : ''}</div></div>`;
  }
  if (r.type === 'g') {
    const l = r.l, col = cssColor(l.color), em = leadEmoji(l.name);
    const sw = licMark(l, 'rmlic', true) || (em ? '' : `<span class="sw" style="${col ? 'background:' + col : ''}"></span>`);  // 2.36.2 (#1135)
    // 2.18.0 review (R13): the fold toggle and "Open list" are siblings (a button inside role=button was nested-interactive)
    return `<div class="tl-row rm-row rm-g${r.open ? ' open' : ''}" data-l="${l.id}" style="top:${y}px"><div class="tl-name rm-gwrap" title="${esc(lname(l))}"><div class="rm-gname" data-act="rm-toggle" data-key="${esc(r.key)}" role="button" tabindex="0" aria-expanded="${r.open}">${ic('chev', 's rm-car' + (r.open ? '' : ' closed'))}${sw}<span class="n">${esc(lname(l))}</span>${l.role === 'view' ? `<span class="rm-ro" title="${esc(tr('View only'))}">${ic('eye', 's')}</span>` : ''}</div><button type="button" class="iconbtn rm-go" data-go="l/${l.id}" title="${esc(tr('Open list'))}" aria-label="${esc(tr('Open list'))}">${ic('arrow', 's')}</button></div>${tlCrTrack(l.id, null, 'g:' + l.id, rmCrGeo(G), canAddTo(l.id) && !S.tlPick, rmSumHtml(G, r) + rmMsHtml(G, l, r))}</div>`;
  }
  if (r.type === 's') return tlSecRow(r.l, r.sg, r.open, canAddTo(r.l.id) && !S.tlPick, rmCrGeo(G), y, r.n);
  if (r.type === 'a') return tlAddRow(r.l, rmCrGeo(G), y);
  if (r.type === 'nh') return `<div class="tl-row rm-row rm-nh" data-l="${r.l.id}" style="top:${y}px"><div class="tl-name rm-gname" data-act="rm-ndfold" data-key="${esc(r.key)}" role="button" tabindex="0" aria-expanded="${r.open}">${ic('chev', 's rm-car' + (r.open ? '' : ' closed'))}<span class="n">${tr('No date')}</span><span class="c">${r.n}</span></div><div class="tl-track"></div></div>`;
  if (r.type === 'u') {
    const t = r.t, ed = canEditList(r.l.id) && canEdit(t);
    return `<div class="tl-row rm-row rm-u" data-l="${r.l.id}" style="top:${y}px"><div class="tl-name rm-tname" data-act="open" data-id="${t.id}">${r.sub ? '<span class="muted">↳ </span>' : ''}<span class="tln">${esc(t.title)}</span></div><div class="tl-track ndt${ed ? ' ed' : ''}" data-nd="${t.id}" data-s0="${G.start}" data-dw="${G.dw}" data-days="${G.days}" title="${ed ? esc(isTouch() ? tr('Tap a day to set the date; hold and drag for a range') : tr('Click a day to set the date, drag across days for a range')) : ''}"></div></div>`;
  }
  const t = r.t, s0 = tlStart0(t), inWin = t.due >= G.start && s0 <= G.end;
  const name = `<div class="tl-name rm-tname" data-act="open" data-id="${t.id}">${t.parent_id ? '<span class="muted">↳ </span>' : ''}${esc(t.title)}</div>`;
  let bar = '';
  if (inWin) { bar = t.ms ? tlMsHtml(t, G.start, G.dw) : tlBarHtml(t, G.start, G.end, G.dw, S.tlPick && depsOn() ? S.tlPick : null, depsOn()); S.tlL.bars.set(t.id, 1); }
  else bar = `<button type="button" class="rm-off ${t.due < G.start ? 'l' : 'r'}" data-act="rm-jump" data-d="${s0}" title="${esc(tr('Show {0}', fmtDayAbs(s0)))}">${ic(t.due < G.start ? 'left' : 'right', 's')}<span>${esc(fmtDayAbs(t.due < G.start ? t.due : s0))}</span></button>`;
  return `<div class="tl-row rm-row rm-t${t.ms ? ' tl-msrow' : ''}${r.insec ? ' rm-insec' : ''}" data-l="${r.l.id}" style="top:${y}px">${name}<div class="tl-track">${bar}</div></div>`;
}
function rmChips(M) {
  const P = rmP(), n = (P.ls || []).length, who = rmWho();
  const whoLbl = !who ? tr('Everyone') : who === 'me' ? tr('Me') : who === 'none' ? tr('Unassigned') : (rmPeople().find(p => p.user_id === +who)?.name || '?');
  const noProj = !rmProjects().length;
  return `<div class="rm-chips fchips" role="toolbar" aria-label="${esc(tr('Filters'))}">
    <button class="${M.po ? 'on' : ''}" data-act="rm-po" aria-pressed="${M.po}" ${noProj && !M.po ? `title="${esc(tr('Make a list a project to plan it here'))}"` : ''}>${tr('Projects only')}</button>
    <button class="${rmHD() ? 'on' : ''}" data-act="rm-hd" aria-pressed="${rmHD()}">${tr('Hide done')}</button>
    <button class="${rmNdOn() ? 'on' : ''}" data-act="rm-nd" aria-pressed="${rmNdOn()}" title="${esc(tr('Show tasks without a date as rows to draw into'))}">${ic('cal', 's')}${tr('No date')}</button>
    ${collab() ? `<button class="${who ? 'on' : ''}" data-act="rm-who" aria-haspopup="menu">${ic('user', 's')}${esc(whoLbl)}</button>` : ''}
    <button class="${n ? 'on' : ''}" data-act="rm-lists" aria-haspopup="dialog">${ic('filter', 's')}${n ? esc(trn('{0} list', '{0} lists', n)) : tr('All lists')}</button>
    ${noProj ? `<span class="rm-hint">${ic('help', 's')}${tr('Make a list a project to plan it here')}</span>` : ''}
    <span class="rm-ce"><button class="iconbtn" data-act="rm-collapse" title="${tr('Collapse all')}" aria-label="${tr('Collapse all')}">${ic('collapse')}</button><button class="iconbtn" data-act="rm-expand" title="${tr('Expand all')}" aria-label="${tr('Expand all')}">${ic('expand')}</button></span></div>`;
}
function rmPeople() {
  const m = new Map();
  for (const l of S.lists) if (l.shared && !l.archived) for (const p of listPeople(l)) if (p.user_id && !m.has(p.user_id)) m.set(p.user_id, p);
  return [...m.values()].filter(p => !S.me || p.user_id !== S.me.id).sort((a, b) => a.name.localeCompare(b.name));
}
function viewRoadmap() {
  const G = rmGeo(), M = rmModel(), t0 = today();
  S.rmV = {G, M, a: -1, b: -1};
  S.tlL = {bars: new Map()};
  const H = G.hh + M.rows.length * G.rh, [mt, mb] = rmHead(G), todayX = rmX(G, t0);
  const zs = [['week', N_('Week')], ['month', N_('Month')], ['quarter', N_('Quarter')]];
  const bar = `<div class="calbar rm-bar"><div class="seg" role="group" aria-label="${esc(tr('Zoom'))}">${zs.map(([k, n]) => `<button class="${G.z === k ? 'on' : ''}" data-act="rm-zoom" data-k="${k}" aria-pressed="${G.z === k}">${tr(n)}</button>`).join('')}</div>
    <div class="calnav"><button class="iconbtn" data-act="rm-prev" title="${tr('Earlier')}" aria-label="${tr('Earlier')}">${ic('left')}</button><button class="btn sm" data-act="rm-today">${tr('Today')}</button><button class="iconbtn" data-act="rm-next" title="${tr('Later')}" aria-label="${tr('Later')}">${ic('right')}</button></div>
    </div>`;
  const from = S.tlPick && S.tasks.get(S.tlPick.from);
  const pick = from ? `<div class="tl-pick" role="status">${ic('deps', 's')}<span>${tr('Tap the task that “{0}” blocks', esc(from.title))}</span><span class="spacer"></span><button class="btn sm" data-act="tl-pick-list">${ic('search', 's')} ${tr('Pick from a list…')}</button><button class="btn sm" data-act="tl-pick-cancel">${tr('Cancel')}</button></div>` : '';
  if (!M.rows.length) return `${bar}${rmChips(M)}<div class="rm-empty muted">${M.po && !rmProjects().length ? tr('Make a list a project to plan it here') : tr('Nothing to show with these filters')}</div>`;
  const hint = isTouch() ? tr('Long-press a project bar to move the whole project. Tap a name to open or close it.') : tr('Drag a project bar to move all its open tasks with a date. Click a name to open or close it.');
  return `${bar}${rmChips(M)}${pick}
    <div class="tl rm z-${G.z}${S.tlPick ? ' picking' : ''}" style="--dw:${G.dw}px;--days:${G.days};--rh:${G.rh}px;--hh:${G.hh}px;--grid:${G.z === 'week' ? G.dw : 7 * G.dw}px;--rm-h:${H + 2}px">
    <div class="tl-scroll rm-scroll" id="tlscroll"><div class="tl-inner" style="height:${H}px">
      <div class="tl-row tl-headrow"><div class="tl-name rm-hname">${esc(trn('{0} list', '{0} lists', M.nGroups))}</div><div class="tl-track tl-headtrack"><div class="tl-months">${mt}</div><div class="tl-days">${mb}</div></div></div>
      <div id="rm-rows"></div>
      ${todayX >= 0 && todayX < G.days * G.dw ? `<i class="tl-now" style="left:calc(var(--tl-name) + ${todayX + G.dw / 2}px)"></i>` : ''}
      <svg class="tl-deps" id="tl-deps" aria-hidden="true"></svg>
    </div></div>
    <div class="muted tl-foot">${hint}</div></div>`;
}
// only the rows in view (+ a margin, in chunks) are in the DOM; called after a render and on scroll
function rmRows(force) {
  const V = S.rmV, sc = $('#tlscroll'), box = $('#rm-rows');
  if (!V || !sc || !box) return;
  const {G, M} = V, n = M.rows.length, CH = 16;
  const top = sc.scrollTop || 0, h = sc.clientHeight || 900;  // jsdom has no layout: a phone-sized page
  let a = Math.max(0, Math.floor((top - G.hh) / G.rh) - 8), b = Math.min(n, Math.ceil((top + h) / G.rh) + 8);
  a = Math.floor(a / CH) * CH; b = Math.min(n, Math.ceil(b / CH) * CH);
  if (!force && a === V.a && b === V.b) return;
  const had = document.activeElement && box.contains(document.activeElement) ? document.activeElement : null;
  const focusSel = had?.id === 'tl-new-in' ? '#tl-new-in' : had?.dataset.id ? `.tl-bar[data-id="${had.dataset.id}"]` : had?.dataset.lid ? `.rm-sum[data-lid="${had.dataset.lid}"]` : had?.dataset.key ? `[data-key="${rmEsc(had.dataset.key)}"]` : had?.dataset.k ? `[data-act="tl-add"][data-k="${rmEsc(had.dataset.k)}"]` : '';  // 2.18.0: + the section folds, "+" and the new-task field
  V.a = a; V.b = b;
  S.tlL = {bars: new Map()};
  let html = '';
  for (let i = a; i < b; i++) html += rmRowHtml(G, M, M.rows[i]);
  box.innerHTML = html;
  if (focusSel) $(focusSel, box)?.focus({preventScroll: true});
  tlFocKeep();
}
function rmAfterRender(el, left, top) {
  const V = S.rmV; if (!V) return;
  const {G} = V;
  el.scrollTop = top ?? 0;
  const at = S.rmFocus && S.rmFocus >= G.start && S.rmFocus <= G.end ? S.rmFocus : today();
  el.scrollLeft = left ?? Math.max(0, (diffDays(G.start, at) - (G.z === 'week' ? 2 : G.z === 'month' ? 7 : 21)) * G.dw);
  rmRows(true);
  if (!el.__rm) { el.__rm = 1; el.addEventListener('scroll', () => { if (!rmRaf) rmRaf = requestAnimationFrame(() => { rmRaf = 0; rmRows(); }); }, {passive: true}); }
  if (tlRO && !el.__ro) { el.__ro = 1; tlRO.observe(el); }
  rmArrows();
}
let rmRaf = 0;
// arrows: computed from the model (dates + row index), all edges at once; the SVG spans the whole inner box
function rmArrows() {
  const svg = $('#tl-deps'), V = S.rmV;
  if (!svg || !V || !isRoadmap()) return;
  if (!depsOn()) { svg.innerHTML = ''; return; }
  if (S.depAll.v !== S.v) loadDepAll();
  const {G, M} = V, W = G.days * G.dw, cache = new Map();
  const drag = $('.tl-bar.drag');
  const node = id => {
    if (cache.has(id)) return cache.get(id);
    let out = null;
    const tr_ = M.taskRow.get(id);
    if (tr_) {
      const t = tr_.t, s0 = tlStart0(t);
      if (t.due >= G.start && s0 <= G.end) {
        const s = s0 < G.start ? G.start : s0, e = t.due > G.end ? G.end : t.due, pad = G.dw >= 12 ? 2 : .5;
        let x = rmX(G, s) + pad, w = Math.max(4, (diffDays(s, e) + 1) * G.dw - 2 * pad);
        if (drag && +drag.dataset.id === id) { x = parseFloat(drag.style.left) || x; w = parseFloat(drag.style.width) || w; }
        out = {k: 't' + id, x, w, y: G.hh + tr_.i * G.rh + G.rh / 2, h: G.rh};
      }
    } else {
      const lid = M.groupOf.get(id) ?? S.tasks.get(id)?.list_id ?? S.depAll.closed.get(id)?.list_id;
      const r = lid != null ? M.listNode.get(lid) : null;
      if (r && (r.type === 'f' || !r.open) && r.span) { const b = rmBarBox(G, r.span); if (b) out = {k: 'r' + r.i, x: b.L, w: b.R - b.L, y: G.hh + r.i * G.rh + G.rh / 2, h: G.rh, agg: true}; }
    }
    cache.set(id, out);
    return out;
  };
  const agg = new Map();
  for (const e of tlEdges({has: id => !!node(id)})) {
    const Wn = node(e.w), Bn = node(e.b);
    if (Wn && Bn && Wn.k === Bn.k) continue;  // both inside the same collapsed list
    const k = (Bn ? Bn.k : 'x' + e.b) + '>' + (Wn ? Wn.k : 'x' + e.w);
    let a = agg.get(k); if (!a) agg.set(k, a = {W: Wn, B: Bn, list: []});
    a.list.push(e);
  }
  const title = id => S.tasks.get(id)?.title || S.depAll.closed.get(id)?.title || tr('a task you cannot see');
  const confOf = ({w, b, closed}) => { const wt = S.tasks.get(w), bt = S.tasks.get(b); return !closed && bt && bt.status === 0 && bt.due && wt?.due && tlStart0(wt) < bt.due; };
  let out = '';
  for (const {W: Wn, B: Bn, list} of agg.values()) {
    const conf = list.some(confOf), kind = conf ? 'conf' : list.every(e => e.closed) ? 'done' : 'ok', both = Wn && Bn;
    let d;
    if (both) d = tlRoute(Bn.x + Bn.w, Bn.y, Wn.x - 1, Wn.y, Wn.h);
    else if (Wn) d = `M${Math.max(-8, Wn.x - 20)},${Wn.y}H${Wn.x - 1}`;
    else d = `M${Bn.x + Bn.w},${Bn.y}H${Math.min(W + 8, Bn.x + Bn.w + 20)}`;
    let tip;
    if (list.length > 1) tip = trn('{0} dependency', '{0} dependencies', list.length) + ': ' + list.slice(0, 4).map(e => tr('“{0}” is blocked by “{1}”', title(e.w), title(e.b))).join(' · ') + (list.length > 4 ? ' …' : '');
    else { const e = list[0]; tip = e.closed ? tr('“{0}” is blocked by “{1}” (done)', title(e.w), title(e.b)) : conf ? tr('“{0}” starts before “{1}” is due', title(e.w), title(e.b)) : tr('“{0}” is blocked by “{1}”', title(e.w), title(e.b)); }
    if (!both) tip += ' · ' + tr('outside this view');
    const attr = list.length > 1 ? `data-rmdep="${list.map(e => e.w + ':' + e.b).join(',')}"` : `data-dep="${list[0].w}:${list[0].b}"`;
    const bx = both ? Wn.x - 12 : Wn ? Math.max(-8, Wn.x - 20) : Math.min(W + 8, Bn.x + Bn.w + 20), by = both ? Wn.y : (Wn || Bn).y;
    const badge = list.length > 1 ? `<g class="rm-badge" transform="translate(${Math.round(bx)},${Math.round(by - 9)})"><circle r="7.5"/><text text-anchor="middle" dy="3.5">${list.length > 99 ? '99+' : list.length}</text></g>` : '';
    out += `<g class="dep ${kind}${both ? '' : ' stub'}${Wn?.agg || Bn?.agg ? ' agg' : ''}" ${attr}><title>${esc(tip)}</title><path class="hit" d="${d}"/><path class="ln" d="${d}" marker-end="url(#tl-ah-${kind})"/>${both ? '' : `<circle class="st" cx="${Wn ? Math.max(-8, Wn.x - 20) : Math.min(W + 8, Bn.x + Bn.w + 20)}" cy="${(Wn || Bn).y}" r="2.5"/>`}${badge}</g>`;
  }
  const mk = k => `<marker id="tl-ah-${k}" class="ah ${k}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0.5L7.5,4L0,7.5z"/></marker>`;
  svg.innerHTML = `<defs>${mk('ok')}${mk('conf')}${mk('done')}</defs>${out}<path class="rubber" d=""/>`;
}
function rmDepPop(g) {
  const pairs = g.dataset.rmdep.split(',').map(p => p.split(':').map(Number));
  const nm = id => { const x = S.tasks.get(id)?.title || S.depAll.closed.get(id)?.title || '?'; return x.length > 28 ? x.slice(0, 27) + '…' : x; };
  menu(g, pairs.slice(0, 12).map(([w, b]) => ({label: tr('“{0}” is blocked by “{1}”', nm(w), nm(b)), icon: 'deps', fn: () => openTaskById(w)})));
}
function rmToggle(key) {
  const V = S.rmV; if (!V) return;
  const r = V.M.rows.find(x => x.key === key); if (!r) return;
  rmSet({t: {...(rmP().t || {}), [key]: r.open ? 0 : 1}});
  $(`.rm-gname[data-key="${rmEsc(key)}"]`)?.focus();
}
function rmAll(open) {
  const t = {...(rmP().t || {})};
  for (const k of Object.keys(t)) if (open || k.startsWith('l')) delete t[k];
  rmSet({def: open ? 'e' : 'c', t});
  toast(open ? tr('All projects expanded') : tr('All projects collapsed'));
}
function rmNav(dir) {  // prev / next keep the scroll position (the window moves under it); Today = back to the start
  const z = RM_Z[rmZoom()];
  rmGeo();
  S.rmStart = dir ? addDays(S.rmStart, dir * z.step) : addDays(weekStartOf(today()), -z.lead);
  if (!dir) { S.rmFocus = null; S.rmScrollReset = true; }
  renderView();
}
function rmJump(d) {  // the arrow of a bar outside the window: the window moves there
  S.rmStart = addDays(weekStartOf(d), -RM_Z[rmZoom()].lead);
  S.rmFocus = d; S.rmScrollReset = true;
  renderView();
}
// "Move project by…": touch (long-press), the bar's menu, Enter on a focused bar
function rmMoveDialog(lid) {
  const l = listById(lid); if (!l) return;
  if (!canEditList(lid)) { roToast(); return; }
  const open = openTasks().filter(t => t.list_id === lid && t.due), sp = rmSpan(open);
  if (!open.length) { toast(tr('No open tasks with a date in this list')); return; }
  if (open.length > RM_SHIFT_MAX) { toast(tr('This list has {0} tasks with a date, at most {1} can be moved at once', open.length, RM_SHIFT_MAX)); return; }
  const md = modal(`<h3>${tr('Move project by…')}</h3>
    <div class="shint keep">${esc(lname(l))} · ${esc(trn('{0} open task with a date', '{0} open tasks with a date', open.length))} · ${tr('tasks without a date stay')}</div>
    <div class="rm-mv"><button type="button" class="btn rm-step" data-st="-1" aria-label="${tr('Earlier')}">−</button><input id="rm-n" type="number" inputmode="numeric" value="1" step="1" aria-label="${tr('Move by')}"><button type="button" class="btn rm-step" data-st="1" aria-label="${tr('Later')}">+</button>
      <div class="seg" id="rm-unit" role="group"><button type="button" class="on" data-u="7">${tr('weeks')}</button><button type="button" data-u="1">${tr('days')}</button></div></div>
    <div class="rm-quick">${[[-7, tr('1 week earlier')], [1, tr('1 day later')], [7, tr('1 week later')], [14, tr('2 weeks later')], [28, tr('4 weeks later')]].map(([n, t]) => `<button type="button" class="btn sm" data-q="${n}">${t}</button>`).join('')}</div>
    <div class="rm-prev" id="rm-prev" aria-live="polite"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" id="rm-ok">${tr('Move')}</button></div>`);
  md.classList.add('rmmodal');
  let unit = 7;
  const days = () => { const n = parseInt($('#rm-n', md).value, 10); return Number.isFinite(n) ? Math.max(-3650, Math.min(3650, n * unit)) : 0; };
  const upd = () => {
    const d = days();
    $('#rm-prev', md).textContent = d ? `${fmtDayAbs(sp.s)} – ${fmtDayAbs(sp.e)}  →  ${fmtDayAbs(addDays(sp.s, d))} – ${fmtDayAbs(addDays(sp.e, d))}` : tr('Choose how far to move it');
    $('#rm-ok', md).disabled = !d;
  };
  upd();
  md.addEventListener('input', upd);
  md.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.st) { const i = $('#rm-n', md); i.value = (parseInt(i.value, 10) || 0) + +b.dataset.st; upd(); return; }
    if (b.dataset.u) { unit = +b.dataset.u; $$('#rm-unit button', md).forEach(x => x.classList.toggle('on', x === b)); upd(); return; }
    if (b.dataset.q) { const n = +b.dataset.q; unit = n % 7 === 0 ? 7 : 1; $('#rm-n', md).value = n / unit; $$('#rm-unit button', md).forEach(x => x.classList.toggle('on', +x.dataset.u === unit)); upd(); return; }
    if (b.id === 'rm-ok') { const d = days(); if (!d) return; md.remove(); rmShift(lid, d); }
  });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.id === 'rm-n') { e.preventDefault(); $('#rm-ok', md).click(); } });
  setTimeout(() => { const i = $('#rm-n', md); if (i && !isMobile()) { i.focus(); i.select?.(); } }, 30);
}
async function rmShift(lid, days) {
  if (!canEditList(lid)) { roToast(); renderView(); return; }
  let j;
  try { j = await api('POST', `/api/lists/${lid}/shift`, {days}); } catch { renderView(); return; }  // api() showed the reason
  await load().catch(() => {}); render();
  const all = [...(j.moved || []), ...(j.shifted || [])];
  if (!all.length) { toast(tr('No open tasks with a date in this list')); return; }
  const msg = [trn('{0} task moved', '{0} tasks moved', j.count), j.shifted?.length ? trn('{0} dependent task moved', '{0} dependent tasks moved', j.shifted.length) : ''].filter(Boolean).join(' · ');
  // one step: every task back to its own dates (and forward again), one request (one transaction) each way
  const pairs = all.map(x => [{id: x.id, start: x.prev_start, due: x.prev_due}, {id: x.id, start: x.start, due: x.due}, ['start', 'due']]);
  offerUndo(msg, histFields(trn('Shifted project {1} by {0} day', 'Shifted project {1} by {0} days', days, qn(lname(listById(lid)) || '')), pairs, {res: j}));
}
function rmSumMenu(el) {
  const lid = +el.dataset.lid, l = listById(lid); if (!l) return;
  const V = S.rmV, r = V?.M.rows.find(x => x.type === 'g' && x.l.id === lid);
  menu(el, [...(canEditList(lid) ? [{label: tr('Move project by…'), icon: 'timeline', fn: () => rmMoveDialog(lid)}] : []),
    {label: tr('Open list'), icon: 'arrow', fn: () => go('l/' + lid)},
    ...(r ? [{label: r.open ? tr('Collapse') : tr('Expand'), icon: r.open ? 'collapse' : 'expand', fn: () => rmToggle(r.key)}] : [])]);
}
function rmListsPop(anchor) {
  const sel = new Set(rmP().ls || []), po = rmPO();
  const ls = [inbox(), ...sideOrder()].filter(l => l && !l.archived && (!po || l.kind === 'project'));
  const row = l => `<label class="rm-lrow"><input type="checkbox" data-l="${l.id}" ${sel.has(l.id) ? 'checked' : ''}><span>${esc(lname(l))}</span></label>`;
  let h = ls.filter(l => l.is_inbox || !l.folder).map(row).join('');
  for (const f of folderNames()) {
    const fl = ls.filter(l => !l.is_inbox && l.folder === f); if (!fl.length) continue;
    h += `<label class="rm-lrow rm-lf"><input type="checkbox" data-f="${esc(f)}" ${fl.every(l => sel.has(l.id)) ? 'checked' : ''}>${ic('folder', 's')}<span>${esc(fDisp(f))}</span></label>` + fl.map(row).join('');
  }
  const p = openPop(anchor, `<div class="rm-lpop" role="dialog" aria-label="${esc(tr('Lists'))}"><div class="rm-lhead"><b>${tr('Show these lists')}</b><button class="btn sm" data-all>${tr('All lists')}</button></div>${h || `<div class="muted">${tr('No lists yet')}</div>`}</div>`);
  p.addEventListener('change', e => {
    const x = e.target; if (x.type !== 'checkbox') return;
    if (x.dataset.f != null) for (const c of $$(`input[data-l]`, p)) { if (ls.find(l => l.id === +c.dataset.l)?.folder === x.dataset.f) c.checked = x.checked; }
    rmSet({ls: $$('input[data-l]', p).filter(c => c.checked).map(c => +c.dataset.l)});
  });
  p.onclick = e => { if (e.target.closest('[data-all]')) { closePop(); rmSet({ls: []}); } };
}
function rmWhoMenu(anchor) {
  const w = rmWho();
  menu(anchor, [{label: tr('Everyone'), on: !w, fn: () => rmSet({who: ''})}, {label: tr('Me'), icon: 'user', on: w === 'me', fn: () => rmSet({who: 'me'})},
    {label: tr('Unassigned'), on: w === 'none', fn: () => rmSet({who: 'none'})}, ...(rmPeople().length ? ['-'] : []),
    ...rmPeople().map(p => ({label: p.name, icon: 'user', on: w === String(p.user_id), fn: () => rmSet({who: String(p.user_id)})}))]);
}
// ---- summary bar: drag (mouse / pen), long-press (touch), click / Enter = menu
let rmDrag = null, rmDragged = false;
function rmDragReset(d) {
  if (!d?.els) return;
  for (const el of d.els) if (el) el.style.transform = '';
  d.sb.classList.remove('drag'); $('.tl.rm')?.classList.remove('shifting');
  const lb = d.sb.nextElementSibling; if (lb && d.lbl != null) lb.innerHTML = d.lbl;
}
document.addEventListener('pointerdown', e => {
  const sb = e.target.closest?.('.rm-sum');
  if (!sb || e.button !== 0 || e.pointerType === 'touch' || S.tlPick) return;
  e.preventDefault();
  rmDrag = {sb, lid: +sb.dataset.lid, x: e.clientX, n: 0, moved: false, ed: canEditList(+sb.dataset.lid), els: null};
  sb.setPointerCapture?.(e.pointerId);
});
document.addEventListener('pointermove', e => {
  const d = rmDrag; if (!d || !S.rmV) return;
  if (!d.moved && Math.abs(e.clientX - d.x) < 4) return;
  d.moved = true;
  if (!d.ed) return;
  const G = S.rmV.G, snap = G.z === 'quarter' ? 7 : 1, n = Math.round((e.clientX - d.x) / G.dw / snap) * snap;
  if (!d.els) {
    const lb = d.sb.nextElementSibling;
    d.els = [d.sb, ...$$(`.rm-row[data-l="${d.lid}"] .tl-bar, .rm-row[data-l="${d.lid}"] .tl-knob`)];
    d.lbl = lb ? lb.innerHTML : null; if (lb) d.els.push(lb);
    d.sb.classList.add('drag'); $('.tl.rm')?.classList.add('shifting');
  }
  if (n === d.n) return;
  d.n = n;
  for (const el of d.els) el.style.transform = n ? `translateX(${n * G.dw}px)` : '';
  const lb = d.sb.nextElementSibling;
  if (lb) lb.innerHTML = `<b class="rm-delta">${esc(n > 0 ? trn('{0} day later', '{0} days later', n) : n < 0 ? trn('{0} day earlier', '{0} days earlier', -n) : tr('no change'))}</b>`;
});
document.addEventListener('pointerup', () => {
  const d = rmDrag; if (!d) return;
  rmDrag = null;
  if (!d.moved) return;  // a click: the menu (click handler)
  rmDragged = true; setTimeout(() => { rmDragged = false; }, 400);
  if (!d.ed) { roToast(); return; }
  const n = d.n;
  if (!n) { rmDragReset(d); return; }
  rmShift(d.lid, n);
});
document.addEventListener('pointercancel', () => { if (rmDrag) { rmDragReset(rmDrag); rmDrag = null; } });
let rmTouch = null;
document.addEventListener('touchstart', e => {
  const sb = e.target.closest?.('.rm-sum'); if (!sb || S.tlPick) return;
  const p = e.touches[0];
  rmTouch = {sb, x: p.clientX, y: p.clientY, fired: false};
  rmTouch.timer = setTimeout(() => {
    if (!rmTouch) return;
    rmTouch.fired = true;
    if (navigator.vibrate) navigator.vibrate(12);
    rmMoveDialog(+sb.dataset.lid);
  }, 450);
}, {passive: true});
document.addEventListener('touchmove', e => {
  if (!rmTouch || rmTouch.fired) return;
  const p = e.touches[0];
  if (Math.hypot(p.clientX - rmTouch.x, p.clientY - rmTouch.y) > 8) { clearTimeout(rmTouch.timer); rmTouch = null; }
}, {passive: true});
function rmTouchEnd(e) {
  if (!rmTouch) return;
  clearTimeout(rmTouch.timer);
  const f = rmTouch.fired; rmTouch = null;
  if (f) { rmDragged = true; setTimeout(() => { rmDragged = false; }, 400); if (e.cancelable) e.preventDefault(); }  // no click after the hold
}
document.addEventListener('touchend', rmTouchEnd);
document.addEventListener('touchcancel', rmTouchEnd);
document.addEventListener('contextmenu', e => {
  const sb = e.target.closest?.('.rm-sum'); if (!sb || isTouch()) return;
  e.preventDefault(); rmSumMenu(sb);
});
document.addEventListener('keydown', e => {
  const t = e.target; if (!t?.closest || e.ctrlKey || e.metaKey || e.altKey) return;
  const sb = t.closest('.rm-sum'), gn = t.closest('.rm-gname');
  if (sb && (e.key === 'Enter' || e.key === ' ' || e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey))) rmSumMenu(sb);
  else if (sb && (e.key === 'm' || e.key === 'M')) rmMoveDialog(+sb.dataset.lid);
  else if (gn && !e.target.closest('.rm-go') && (e.key === 'Enter' || e.key === ' ')) { if (gn.dataset.act === 'rm-ndfold') gn.click(); else rmToggle(gn.dataset.key); }
  else if ((sb || gn) && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    const all = $$(sb ? '#rm-rows .rm-sum' : '#rm-rows .rm-gname'), i = all.indexOf(sb || gn);
    all[i + (e.key === 'ArrowDown' ? 1 : -1)]?.focus();
  } else return;
  e.preventDefault(); e.stopPropagation();
}, true);
