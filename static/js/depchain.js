// 2.67.0 B (#1865): the dependency chain moves along. The server moves every task waiting on a task whose due date got
// later (list setting "Move dependent tasks along", the whole chain by the same days, see tasks/depchain.py); here:
// the preview while a timeline bar is dragged, the "not moved" part of the message, and "Pull the chain in" (POST
// /api/tasks/<id>/chain/pull: the chain moves earlier by the buffer behind the task), one undo step each.

// waiting tasks of `id` I could move (the same stay-put rules as the server; ends a branch like there)
function dch_waiting(id) { return openTasks().filter(x => (x.blockers || []).includes(id) && dFor(x)); }
const dch_movable = x => x.status === 0 && x.due && !x.ms && canEdit(x);
function dch_on(t) { const l = t && listById(t.list_id); return !!l && depsOn() && l.kind === 'project' && !!l.dep_shift; }
// every task the server would move along when t's due date moves `days` later: [task]
function dch_chainOf(t, days) {
  if (!(days > 0) || !dch_on(t)) return [];
  const by = new Map();
  for (const x of openTasks()) for (const b of x.blockers || []) { if (!by.has(b)) by.set(b, []); by.get(b).push(x); }
  const seen = new Set([t.id]), out = [], todo = [t.id];
  while (todo.length && out.length < 500) {
    for (const x of by.get(todo.shift()) || []) {
      if (seen.has(x.id)) continue;
      seen.add(x.id);
      if (!isProject(x.list_id) || !dch_movable(x)) continue;
      out.push(x); todo.push(x.id);
    }
  }
  return out;
}
// timeline drag (tlApply): the bars that will move along slide with it (transform only, no layout jump)
function dch_preview(d) {
  const days = d.mode === 'm' || d.mode === 'r' ? d.days : 0;
  if (d.dchDays === days) return;
  dch_clear(d); d.dchDays = days;
  const px = days * tlDW();  // lazy-ok: 2.149.0 F (#2519): runs in the timeline drag (timeline.js loaded)
  d.dchEls = dch_chainOf(d.t, days).flatMap(x => $$(`.tl-bar[data-id="${x.id}"]`));
  for (const el of d.dchEls) { el.classList.add('dch-ghost'); el.style.transform = `translateX(${px}px)`; }
}
function dch_clear(d) {
  for (const el of d?.dchEls || []) { el.classList.remove('dch-ghost'); el.style.transform = ''; }
  if (d) { d.dchEls = []; d.dchDays = 0; }
}
// "2 not moved: no permission / completed" (chain.skipped of a PATCH / pull answer), '' when nothing stayed
function dch_skipText(ch) {
  const sk = ch?.skipped || [];
  if (!sk.length) return '';
  const why = {no_access: N_('no permission'), done: N_('completed'), milestone: N_('milestone'), no_date: N_('without a date'), limit: N_('limit of 500 reached'), error: N_('error')};
  return trn('{0} not moved', '{0} not moved', sk.length) + ': ' + [...new Set(sk.map(x => tr(why[x.reason] || why.error)))].join(' / ');
}
// may "Pull the chain in" be offered for t (it has a date, and waiting tasks I can move)?
function dch_canPull(t) { return !!t && t.status === 0 && !!t.due && dFor(t) && dch_waiting(t.id).some(dch_movable); }
async function dch_pull(id) {
  let r;
  try { r = await api('POST', `/api/tasks/${id}/chain/pull`, {}); } catch (e) { toast(e.message || tr('Dependencies are only available online.')); return; }
  const sh = r?.shifted || [];
  if (!sh.length) { toast([tr('Nothing to pull in: the waiting tasks already follow right after it'), dch_skipText(r?.chain)].filter(Boolean).join(' · ')); return; }
  await load().catch(() => {}); render();
  if (S.sel && typeof loadDeps === 'function') loadDeps(S.sel);
  const msg = [trn('{0} task pulled in', '{0} tasks pulled in', sh.length), dch_skipText(r.chain)].filter(Boolean).join(' · ');
  const e = histFields(msg, sh.map(x => [{id: x.id, start: x.prev_start, due: x.prev_due}, {id: x.id, start: x.start, due: x.due}, ['start', 'due']]));
  histToast(msg, e);
}
// after a drag made t EARLIER: the waiting tasks stay (no automatic sliding back) - the message offers to pull them in
function dch_afterEarlier(t, oldDue, newDue) {  // true: moved earlier while tasks wait on it (they stay)
  return !!(oldDue && newDue && newDue < oldDue && dch_canPull({...t, due: newDue}));
}
// the task panel (Dependencies): a button under "Blocking" while there are waiting tasks to pull in
function dch_pullBtn(t, D) {
  if (!canEdit(t) || !t.due || t.status || !(D?.blocking || []).some(x => !x.hidden && x.status === 0 && x.due && canEditList(x.list_id))) return '';
  return `<button class="btn sm dadd dch-pull" data-dch-pull="${t.id}" title="${esc(tr('The tasks waiting on this one move up to the day after it is due (the gaps between them stay)'))}">${ic('deps', 's')} ${tr('Pull the chain in')}</button>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-dch-pull]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); dch_pull(+b.dataset.dchPull);
});
