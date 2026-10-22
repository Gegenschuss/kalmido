/* Kalmido web client: sprints of a project list (2.60.0, #343).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md).
   Off until a list switches them on (list dialog > Sprints). Then the list and its Kanban get a sprint header (name, dates,
   goal, progress, a small burndown with the milestone curve msBurnSvg), a filter Current sprint / Backlog, "Close" with a
   review, and tasks go into a sprint by the task menu, the multi-selection panel or by dropping them on the header.
   Every task change is one undo step (histFields over sprint_id); sprint settings and edits are undo steps too. */
'use strict';

// sprint_id is a task field the undo history restores (the multi-selection panel and histFields use these lists)
if (!UNDO_FIELDS.includes('sprint_id')) { UNDO_FIELDS.push('sprint_id'); HIST_FIELDS.push('sprint_id'); }

const SPR = {j: {}, busy: {}};  // sprint id -> {sig, j} (GET /api/sprints/<id>: progress + burndown)
const spr_on = l => !!(l && l.sprint_cfg && l.sprint_cfg.on);
const spr_list = lid => listById(lid);
const spr_all = l => (l && l.sprints) || [];
const spr_active = l => spr_all(l).find(s => s.state === 'active') || null;
const spr_open = l => spr_all(l).filter(s => s.state !== 'closed').sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : a.num - b.num));
const spr_byId = (l, id) => spr_all(l).find(s => s.id === id) || null;
const spr_flt = lid => (LS.get('sprFlt', {}) || {})[lid] || '';
const spr_rowOn = lid => !!(LS.get('sprRow', {}) || {})[lid];
const spr_unit = lid => (LS.get('sprUnit', {}) || {})[lid] === 'points' && !!spr_list(lid)?.points_on ? 'points' : 'count';
const spr_opened = lid => { const v = (LS.get('sprOpen', {}) || {})[lid]; return v == null ? !isMobile() : !!v; };
function spr_lsSet(k, lid, v) { const o = LS.get(k, {}) || {}; if (v) o[lid] = v; else delete o[lid]; LS.set(k, o); }
const spr_range = s => `${fmtDate(s.start)} – ${fmtDate(s.end)}`;
const spr_name = s => s ? (s.title || tr('Sprint {0}', s.num)) : '';

// the tasks of a sprint the client has (milestones left out, like the server)
const spr_tasks = sid => [...S.tasks.values()].filter(t => t.sprint_id === sid && !isMs(t) && !t.deleted_at);

// ---- the list filter "Current sprint" / "Backlog" (views.js pick, calendar.js Kanban)
function sprKeep(t, rk = S.route.key) {
  if (!rk || !rk.startsWith('l:') || t.list_id !== +rk.slice(2)) return true;
  const l = spr_list(t.list_id); if (!spr_on(l)) return true;
  const f = spr_flt(l.id); if (!f) return true;
  const a = spr_active(l);
  if (f === 'cur') return !!a && t.sprint_id === a.id;
  return !t.sprint_id || !spr_open(l).some(s => s.id === t.sprint_id);  // backlog: no open sprint
}

// ---- the sprint header above the list / Kanban (projects.js listHead)
function sprHead(l) {
  if (!spr_on(l)) return '';
  const a = spr_active(l), ed = canEditList(l.id), f = spr_flt(l.id), open = spr_opened(l.id);
  const seg = `<div class="sprseg" role="group" aria-label="${esc(tr('Show'))}">${[['', N_('All')], ['cur', N_('Current sprint')], ['back', N_('Backlog|sprint')]].map(([k, n]) =>
    `<button type="button" class="${f === k ? 'on' : ''}" data-spr="flt" data-v="${k}" aria-pressed="${f === k}">${esc(tr(n))}</button>`).join('')}</div>`;
  if (!a) return `<div class="sprh" role="region" aria-label="${esc(tr('Sprint'))}"><div class="sprtop"><span class="muted">${esc(tr('No sprint is running'))}</span><span class="spacer"></span>${seg}<button type="button" class="iconbtn" data-spr="more" aria-label="${esc(tr('Sprint options'))}">${ic('dots', 's')}</button></div></div>`;
  const unit = spr_unit(l.id), c = spr_cache(a), p = spr_prog(a, c);
  const pts = unit === 'points';
  const done = pts ? p.points_done : p.done, total = pts ? p.points_total : p.total;
  const pct = total ? Math.round(100 * done / total) : 0;
  const soon = a.start > today() ? `<span class="muted sprsoon">${esc(tr('starts {0}', fmtDate(a.start)))}</span>` : '';
  const progTxt = pts ? tr('{0} of {1} points done', done, total) : tr('{0} of {1} done', done, total);
  const burn = c?.j?.burndown?.days?.length && total ? msBurnSvg(c.j.burndown, total) : c?.err ? `<div class="muted">${esc(tr('The burndown is available online.'))}</div>` : !c?.j ? `<div class="muted">${esc(tr('Loading…'))}</div>`
    : `<div class="muted">${esc(p.total ? tr('The burndown starts on {0}.', fmtDate(a.start)) : tr('No tasks in this sprint yet. Drop tasks here or use “Sprint…” in a task’s menu.'))}</div>`;
  return `<div class="sprh${open ? ' open' : ''}" data-sprdrop="${a.id}" role="region" aria-label="${esc(spr_name(a))}">
    <div class="sprtop"><button type="button" class="sprtg" data-spr="tog" aria-expanded="${open}">${ic('target', 's')}<b>${esc(spr_name(a))}</b><span class="muted">${esc(spr_range(a))}</span></button>${soon}
      <span class="sprp"><span class="pbar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="${esc(tr('Progress'))}"><i style="width:${pct}%"></i></span><span class="muted">${esc(progTxt)}</span></span>
      <span class="spacer"></span>
      ${ed ? `<button type="button" class="btn sm" data-spr="close">${esc(tr('Close sprint'))}</button>` : ''}
      <button type="button" class="iconbtn" data-spr="more" aria-label="${esc(tr('Sprint options'))}">${ic('dots', 's')}</button></div>
    ${seg}
    ${open ? `<div class="sprbody">${a.goal ? `<p class="sprgoal"><span class="muted">${esc(tr('Goal'))}:</span> ${esc(a.goal)}</p>` : ''}${l.points_on ? `<div class="sprunit" role="group" aria-label="${esc(tr('Count'))}"><button type="button" class="${pts ? '' : 'on'}" data-spr="unit" data-v="" aria-pressed="${!pts}">${esc(tr('Tasks'))}</button><button type="button" class="${pts ? 'on' : ''}" data-spr="unit" data-v="points" aria-pressed="${pts}">${esc(tr('Points'))}</button></div>` : ''}${burn}</div>` : ''}
  </div>`;
}
// progress: the server's when loaded, else counted from the tasks the client has
function spr_prog(s, c) {
  if (c?.j?.progress) return c.j.progress;
  const ts = spr_tasks(s.id), dn = ts.filter(t => t.status !== 0), pt = t => +t.points || 0;
  return {done: dn.length, total: ts.length, points_done: dn.reduce((a, t) => a + pt(t), 0), points_total: ts.reduce((a, t) => a + pt(t), 0)};
}
// GET /api/sprints/<id> again whenever the sprint's tasks change here (another device: the state reload changes them too)
function spr_cache(s) {
  const lid = +String(S.route.key).slice(2), unit = spr_unit(lid);
  const sig = unit + '|' + s.start + '|' + s.end + '|' + spr_tasks(s.id).map(t => `${t.id}:${t.status}:${t.points || 0}`).join(',');
  const c = SPR.j[s.id];
  if ((!c || c.sig !== sig) && !SPR.busy[s.id]) {
    SPR.busy[s.id] = true;
    api('GET', `/api/sprints/${s.id}?unit=${unit}`).then(j => { SPR.j[s.id] = {sig, j}; SPR.busy[s.id] = false; if (!c || JSON.stringify(c.j) !== JSON.stringify(j)) spr_redraw(); })
      .catch(() => { SPR.j[s.id] = {sig, j: c?.j || null, err: true}; SPR.busy[s.id] = false; spr_redraw(); });
  }
  return c || null;
}
function spr_redraw() { if (S.route.mod === 'tasks' && String(S.route.key).startsWith('l:')) render(); }

// ---- the task row: the sprint in the row (only when the list shows it: "Show the sprint in the task row")
function spr_rowChip(t, opts = {}) {
  if (!t.sprint_id || opts.trash || opts.subRow) return '';
  const l = spr_list(t.list_id); if (!spr_on(l) || !spr_rowOn(l.id)) return '';
  const s = spr_byId(l, t.sprint_id); if (!s || s.state === 'closed') return '';
  return `<span class="sprm${s.state === 'active' ? ' cur' : ''}" title="${esc(tr('Sprint') + ': ' + spr_name(s))}">${ic('target', 's')}${esc(spr_name(s))}</span>`;
}

// ---- assigning: task menu, multi-selection, drop on the header; one undo step each (spr_assign / spr_pick: sprints2.js)
function spr_menuItems(t, anchor) {
  const l = t && spr_list(t.list_id);
  if (!t || t.id < 0 || t.context || isMs(t) || !spr_on(l) || !canEditList(l.id) || !spr_open(l).length) return [];
  return [{label: tr('Sprint…'), icon: 'target', fn: () => spr_pick(anchor, [t.id])}];
}
// multiedit.js: the "Sprint" field when all selected tasks are in one list with sprints on
function spr_meField(lid) {
  const l = lid && spr_list(lid);
  if (!spr_on(l) || !canEditList(lid) || !spr_open(l).length) return [];
  return [{k: 'sprint', lab: N_('Sprint'), icon: 'target', get: t => t.sprint_id || 0, perm: t => canEditList(t.list_id) && !isMs(t),
    text: v => v ? spr_name(spr_byId(l, v)) || '?' : tr('Backlog|sprint'),
    open: a => menu(a, [...spr_open(l).map(s => ({label: spr_name(s) + ' · ' + spr_range(s), icon: 'target', fn: () => meApply('sprint', t => !isMs(t) && t.sprint_id !== s.id ? {sprint_id: s.id} : null, tr('Sprint'))})),
      '-', {label: tr('Backlog|sprint'), icon: 'x', fn: () => meApply('sprint', t => t.sprint_id ? {sprint_id: null} : null, tr('Backlog|sprint'))}])}];
}
// dnd.js: a task dropped on the sprint header
function spr_dropTask(id, sid) {
  const ids = S.multi?.has(id) ? [...S.multi] : [id];
  const t = S.tasks.get(id), l = t && spr_list(t.list_id);
  if (!l || !canEditList(l.id) || !spr_byId(l, sid)) return;
  return spr_assign(ids.filter(i => S.tasks.get(i)?.list_id === l.id), sid);
}

// ---- the list dialog: Sprints on / off + settings (dialogs.js listModal, project area)
function spr_dlgRow(l) {
  if (!l || l.is_inbox || (l.kind || 'list') !== 'project' || !canEditList(l.id)) return '';
  return `<div class="row lsprrow"><label>${tr('Sprints')}</label><label class="chkl"><input type="checkbox" id="l-spr" data-lid="${l.id}" ${spr_on(l) ? 'checked' : ''}> ${tr('Plan in sprints')}</label><button type="button" class="linkbtn" data-spr="cfg" data-lid="${l.id}">${tr('Settings…')}</button></div>
    <div class="shint lhint">${tr('Time boxes of one or two weeks with a goal, a burndown and a review at the end. Off by default; for everyone in the project.')}</div>`;
}
// 2.149.0 F (#2518): the settings, editing, planning, the list of sprints and closing are in sprints2.js (loaded on their first use)
// clicks on the header and the list dialog's row (own attribute data-spr: the global data-act switch stays untouched)
document.addEventListener('click', e => {
  const b = e.target.closest('[data-spr]'); if (!b) return;
  const k = b.dataset.spr, lid = b.dataset.lid ? +b.dataset.lid : +String(S.route.key).slice(2), l = spr_list(lid);
  if (!l) return;
  if (k === 'cfg') { spr_cfgModal(lid); return; }
  if (k === 'flt') { spr_lsSet('sprFlt', lid, b.dataset.v); render(); return; }
  if (k === 'tog') { const o = LS.get('sprOpen', {}) || {}; o[lid] = spr_opened(lid) ? 0 : 1; LS.set('sprOpen', o); render(); return; }
  if (k === 'unit') { spr_lsSet('sprUnit', lid, b.dataset.v); render(); return; }
  if (k === 'close') { const a = spr_active(l); if (a) spr_closeModal(l, a); return; }
  if (k === 'more') spr_moreMenu(b, l);
});
document.addEventListener('change', e => {
  if (e.target.id !== 'l-spr') return;
  const lid = +e.target.dataset.lid;
  spr_cfgSet(lid, {on: e.target.checked}, e.target.checked ? tr('Sprints are on') : tr('Sprints are off')).then(j => { if (!j) e.target.checked = !e.target.checked; });
});
