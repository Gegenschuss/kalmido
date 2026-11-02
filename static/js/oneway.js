'use strict';
// 2.392.0 C (#3370): the mark "one-way step" of a task (reason, a person's yes) and the section "Decisions" at the top of the
// task panel; both come with the task / the timeline. The gate's card shows what blocks (git.js gateHtml).
const ow_marked = t => !!t?.irreversible;
const ow_decs = t => t && S.tl.id === t.id ? S.tl.decisions || [] : [];
const ow_ro = t => !canEdit(t) || !!t.context;
const ow_needsYes = t => !!listById(t.list_id)?.irreversible_needs_yes;
function ow_barHtml(t, ro) {
  if (!ow_marked(t)) return '';
  const yes = !!t.irreversible_yes_at, here = S.tl.id === t.id;
  const off = !ro && (!ow_needsYes(t) || (here && !!S.tl.may_yes));  // with the switch on only an approver takes the mark off
  return `<section class="owbar" aria-label="${esc(tr('One-way step'))}">${ic('alert', 's')}<div class="owt"><b>${tr('One-way step')}</b>${t.irreversible_reason ? `<span>${esc(t.irreversible_reason)}</span>` : ''}
    <span class="muted">${esc(yes ? tr('Yes given {0}', fmtWhen(t.irreversible_yes_at)) : ow_needsYes(t) ? tr('Waiting for a yes: integration and deployment stay closed') : tr('No yes needed in this project'))}</span></div>
    <div class="owb">${!yes && here && S.tl.may_yes ? `<button type="button" class="btn sm pri" data-ow="yes">${esc(tr('Give the yes'))}</button>` : ''}${ro ? '' : `<button type="button" class="btn sm" data-ow="edit">${esc(tr('Change the reason'))}</button>`}${off ? `<button type="button" class="btn sm" data-ow="off">${esc(tr('Take the mark off'))}</button>` : ''}</div></section>`;
}
function ow_decHtml(t) {
  const ds = ow_decs(t), ro = ow_ro(t);
  if (!ds.length) return '';
  const row = d => `<li class="owd${d.superseded_by ? ' old' : ''}" data-did="${d.id}"><div class="owdt">${esc(d.text)}</div><div class="muted owdm">${esc(d.by || tr('Unknown'))} · ${esc(fmtWhen(d.created_at))}${d.superseded_by || ro ? '' : ` · <button type="button" class="linkbtn" data-ow="dec-new" data-did="${d.id}">${esc(tr('Replace'))}</button>`}</div></li>`;
  return `<section class="owdec" aria-label="${esc(tr('Decisions'))}"><h5>${esc(tr('Decisions'))}</h5><ul>${ds.map(row).join('')}</ul>${ro ? '' : `<button type="button" class="linkbtn" data-ow="dec-new">${esc(tr('Add a decision'))}</button>`}</section>`;
}
// called by drawTimeline (the decisions and "may I decide" arrive with the comments)
function ow_draw() {
  const t = taskById(S.sel); if (!t) return;
  const b = $('#d-ow'); if (b) b.innerHTML = ow_barHtml(t, ow_ro(t));
  const d = $('#d-dec'); if (d) d.innerHTML = ow_decHtml(t);
}
function ow_set(t, irr) {
  t.irreversible = irr ? 1 : 0;
  t.irreversible_reason = irr?.reason || '';
  t.irreversible_yes_by = irr?.yes_by ?? null;
  t.irreversible_yes_at = irr?.yes_at ?? null;
  ow_draw();
}
async function ow_mark(id) {
  const t = taskById(id); if (!t) return;
  if (listById(t.list_id)?.e2e) {  // a list with the lock takes the mark without a text
    if (await askConfirm(tr('Mark as a one-way step'), tr('This project is encrypted: the mark stays without a reason.'), {ok: tr('Mark')})) ow_set(t, (await api('PUT', `/api/tasks/${id}/irreversible`, {})).irreversible);
    return;
  }
  const v = await askPrompt(tr('Reason of the one-way step'), t.irreversible_reason || '', {ok: tr('Mark'), input: {max: 500}});
  if (v === null) return;
  ow_set(t, (await api('PUT', `/api/tasks/${id}/irreversible`, {reason: v.trim()})).irreversible);
}
async function ow_unmark(id) {
  const t = taskById(id); if (!t) return;
  const j = await api('DELETE', `/api/tasks/${id}/irreversible`);
  ow_set(t, j.irreversible); toast(tr('Mark taken off'));
}
async function ow_decAdd(id, old) {
  const t = taskById(id); if (!t) return;
  const v = await askPrompt(old ? tr('Replace the decision') : tr('Add a decision'), '', {ok: tr('Save'), input: {max: 4000}});
  if (!v?.trim()) return;
  const j = await api('POST', `/api/tasks/${id}/decisions`, {text: v.trim(), ...(old ? {supersedes: old} : {})});
  if (S.tl.id !== id) return;
  S.tl.decisions = [...(S.tl.decisions || []).map(d => d.id === old ? {...d, superseded_by: j.id} : d), j];
  ow_draw();
}
const ow_menuItems = t => t.id > 0 && !ow_ro(t) ? [
  {label: tr('Add a decision'), icon: 'check', fn: () => ow_decAdd(t.id).catch(() => {})},
  ...(ow_marked(t) ? [] : [{label: tr('Mark as a one-way step'), icon: 'alert', fn: () => ow_mark(t.id).catch(() => {})}])] : [];
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-ow]'); if (!b) return;
  const id = S.sel, t = taskById(id); if (!t) return;
  try {
    switch (b.dataset.ow) {
      case 'yes': { const j = await api('POST', `/api/tasks/${id}/irreversible-yes`); ow_set(t, j.irreversible); await loadTimeline(id); break; }
      case 'edit': await ow_mark(id); break;
      case 'off': await ow_unmark(id); break;
      case 'dec-new': await ow_decAdd(id, +b.dataset.did || null); break;
    }
  } catch { /* api() said it */ }
});
// the project dialog's switch (saved at once, like story points)
function ow_listRow(l, own) {
  if (!own || !isProject(l.id)) return '';
  return `<div class="row"><label>${tr('One-way steps')}</label><label class="chkl"><input type="checkbox" id="l-owyes" data-lid="${l.id}" ${l.irreversible_needs_yes ? 'checked' : ''}> ${tr('Tasks marked as one-way steps need a yes before integration and deployment')}</label></div>`;
}
document.addEventListener('change', async e => {
  if (e.target.id !== 'l-owyes') return;
  const on = e.target.checked, l = listById(+e.target.dataset.lid); if (!l) return;
  try { await api('PATCH', '/api/lists/' + l.id, {irreversible_needs_yes: on}); } catch { e.target.checked = !on; return; }
  l.irreversible_needs_yes = on ? 1 : 0; render();
});
