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
  return `<div class="row"><label>${tr('One-way steps')}</label><label class="chkl"><input type="checkbox" id="l-owyes" data-lid="${l.id}" ${l.irreversible_needs_yes ? 'checked' : ''}> ${tr('Tasks marked as one-way steps need a yes before integration and deployment')}</label></div>`
    // 2.574.0 (#3376): the four-eyes rule of the gates; alone in the project it would never approve -> a hint
    + `<div class="row"><label>${tr('Approvals')}</label><label class="chkl"><input type="checkbox" id="l-2eyes" data-lid="${l.id}" ${l.two_eyes ? 'checked' : ''}> ${tr('Integration, deployment and merge approvals need two people')}</label></div>`
    + `<div class="shint lhint" id="l-2eyes-h" ${l.two_eyes && !l.shared ? '' : 'hidden'}>${tr('Only useful with members: the second 👍 must come from another person who may approve (project owner, project admin or an admin). Share the project first.')}</div>`;
}
document.addEventListener('change', async e => {
  if (e.target.id === 'l-2eyes') {  // 2.574.0 (#3376)
    const on = e.target.checked, l = listById(+e.target.dataset.lid); if (!l) return;
    try { await api('PATCH', '/api/lists/' + l.id, {two_eyes: on}); } catch { e.target.checked = !on; return; }
    l.two_eyes = on ? 1 : 0; const h = document.getElementById('l-2eyes-h'); if (h) h.hidden = !(on && !l.shared);
    return;
  }
  if (e.target.id !== 'l-owyes') return;
  const on = e.target.checked, l = listById(+e.target.dataset.lid); if (!l) return;
  try { await api('PATCH', '/api/lists/' + l.id, {irreversible_needs_yes: on}); } catch { e.target.checked = !on; return; }
  l.irreversible_needs_yes = on ? 1 : 0; render();
});
// ---- 2.392.2 (#3365): the delivery state of a task (tasks/deliver.py): in progress (a job), parked (a reason), waiting (a
// task or a note); next to the build state of the code. A bar in the task panel, the menu, a list column, grouping and filter.
const DV_NAMES = {in_progress: N_('In progress'), parked: N_('Parked'), waiting: N_('Waiting')};
const DV_ICON = {in_progress: 'play', parked: 'pause', waiting: 'clock'};
const dv_state = t => t && DV_NAMES[t.delivery] ? t.delivery : '';
function dv_text(t) {  // "Parked: reason", "Waiting for #12 Title", "In progress (job 82)"
  const st = dv_state(t); if (!st) return '';
  const dep = t.delivery_task_id && taskById(t.delivery_task_id);
  const bits = [st === 'waiting' && t.delivery_task_id ? tr('for {0}', dep ? `#${dep.id} ${dep.title}` : '#' + t.delivery_task_id) : '',
    st === 'in_progress' && t.delivery_job_id ? tr('Job {0}', t.delivery_job_id) : '', t.delivery_note || ''].filter(Boolean);
  return bits.join(' · ');
}
function dv_barHtml(t, ro) {
  const st = dv_state(t); if (!st) return '';
  const tx = dv_text(t), since = t.delivery_at ? tr('since {0}', fmtWhen(t.delivery_at)) : '';
  const job = st === 'in_progress' && t.delivery_job_id ? ` <a class="jlink" href="#job/${+t.delivery_job_id}">${esc(tr('Open the job'))}</a>` : '';  // 2.392.2 (#3366): its chain on the job card
  return `<section class="owbar dvbar" aria-label="${esc(tr('Delivery state'))}">${ic(DV_ICON[st], 's')}<div class="owt"><b>${esc(tr(DV_NAMES[st]))}</b>${tx ? `<span>${esc(tx)}${job}</span>` : job}${since ? `<span class="muted">${esc(since)}</span>` : ''}</div>
    ${ro ? '' : `<div class="owb"><button type="button" class="btn sm" data-dv="${st === 'waiting' ? 'wait' : 'park'}">${esc(tr('Change'))}</button><button type="button" class="btn sm" data-dv="clear">${esc(tr('Clear'))}</button></div>`}</section>`;
}
function dv_draw() { const t = taskById(S.sel), b = $('#d-dv'); if (t && b) b.innerHTML = dv_barHtml(t, ow_ro(t)); }
function dv_setLocal(t, d) {
  t.delivery = d?.state || ''; t.delivery_note = d?.note || ''; t.delivery_job_id = d?.job_id ?? null;
  t.delivery_task_id = d?.task_id ?? null; t.delivery_at = d?.since ?? null; t.delivery_by = d?.by ?? null;
  dv_draw(); render();
}
async function dv_put(id, body) {
  const t = taskById(id); if (!t) return;
  const j = body ? await api('PUT', `/api/tasks/${id}/delivery`, body) : await api('DELETE', `/api/tasks/${id}/delivery`);
  dv_setLocal(t, j.delivery);
}
const dv_locked = t => !!listById(t.list_id)?.e2e;
async function dv_park(id) {
  const t = taskById(id); if (!t) return;
  if (dv_locked(t)) {  // a list with the lock: no text on the server
    if (await askConfirm(tr('Park with a reason'), tr('This project is encrypted: the state stays without a reason.'), {ok: tr('Park')})) await dv_put(id, {state: 'parked'});
    return;
  }
  const v = await askPrompt(tr('Why is it parked?'), dv_state(t) === 'parked' ? t.delivery_note : '', {ok: tr('Park'), input: {max: 500}});
  if (v === null || !v.trim()) return;
  await dv_put(id, {state: 'parked', note: v.trim()});
}
async function dv_wait(id) {
  const t = taskById(id); if (!t) return;
  if (dv_locked(t)) { await dv_put(id, {state: 'waiting'}); return; }
  const v = await askPrompt(tr('What does it wait for? A task number (#12) or a short note'), dv_state(t) === 'waiting' ? (t.delivery_task_id ? '#' + t.delivery_task_id : t.delivery_note) : '', {ok: tr('Save'), input: {max: 500}});
  if (v === null || !v.trim()) return;
  const m = /^#?(\d{1,12})$/.exec(v.trim());
  await dv_put(id, m ? {state: 'waiting', task_id: +m[1]} : {state: 'waiting', note: v.trim()});
}
const dv_menuItems = t => t.id > 0 && !ow_ro(t) && t.status === 0 ? [
  {label: dv_state(t) === 'parked' ? tr('Change the parking reason') : tr('Park with a reason'), icon: 'pause', fn: () => dv_park(t.id).catch(() => {})},
  {label: tr('Waiting for…|delivery'), icon: 'clock', fn: () => dv_wait(t.id).catch(() => {})},
  ...(dv_state(t) ? [{label: tr('Clear the delivery state'), icon: 'x', fn: () => dv_put(t.id, null).catch(() => {})}] : [])] : [];
// 2.525.0 (#4281): one-meaning guard: data-dv - park / wait / clear only (office_datev.js: inputs of its own change handler)
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-dv]'); if (!b) return;
  const id = S.sel;
  try {
    if (b.dataset.dv === 'park') await dv_park(id);
    else if (b.dataset.dv === 'wait') await dv_wait(id);
    else if (b.dataset.dv === 'clear') await dv_put(id, null);
  } catch { /* api() said it */ }
});
// the row: a chip for parked / waiting (in progress shows as the working dot); the list column "Delivery"
function dv_cell(t) {
  const st = dv_state(t); if (!st || t.status !== 0) return '';
  return `<span class="dvchip dv-${st}" title="${esc([tr(DV_NAMES[st]), dv_text(t)].filter(Boolean).join(': '))}">${ic(DV_ICON[st], 's')}<span class="lbl">${esc(tr(DV_NAMES[st]))}</span></span>`;
}
const dv_chip = t => dv_state(t) && dv_state(t) !== 'in_progress' ? dv_cell(t) : '';
// grouping (lists.group_field = "delivery"): In progress, Waiting, Parked, then the rest
function dv_groups(lid, arr, dn = []) {
  const mk = p => dsxMerge(arr.filter(p), dn.filter(p));
  return [...['in_progress', 'waiting', 'parked'].map(k => ({id: `dv:${lid}:${k}`, name: tr(DV_NAMES[k]), tasks: mk(t => dv_state(t) === k)})),
    {id: `dv:${lid}:n`, name: tr('No delivery state'), tasks: mk(t => !dv_state(t))}].filter(g => g.tasks.length).map(g => ({...g, cls: 'lgf'}));
}
