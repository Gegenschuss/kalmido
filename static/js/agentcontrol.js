// @ts-check
// 2.235.0 A (#2891 #2900 #2901): the section "Control" of the agent dialog "Work style and notifications" (awOpen in agentwork.js calls it with the dialog and the agent; it draws into its own container).
// Level per agent + exceptions per project, the one-way steps (four fixed, own ones), the deadline of approvals and the history of
// the agent's own decisions with Undo. Autosave per field: PATCH /api/agents/<id>/control with ONLY the changed key; the answer
// redraws the section. The server enforces the level (agents/control.py); a project allows at most the owner's own rights there.
const AWC_LEVELS = [
  ['approve_all', N_('Approve everything'), N_('Every change waits for your approval.')],
  ['routine', N_('Routine free'), N_('Creating, planning, commenting and ticking off tasks without asking; everything else by card.')],
  ['free', N_('Free run with a goal'), N_('Decides itself towards the goal; every decision is a line in the history.')],
];
const AWC_DEADLINES = [['off', N_('No deadline')], ['1h', N_('1 hour')], ['4h', N_('4 hours')], ['1d', N_('1 day')], ['3d', N_('3 days')]];
const AWC_THEN = [['reject', N_('Reject')], ['ask_again', N_('Ask again once')], ['recommend', N_('Take the recommendation')]];
const AWC_KIND = {
  task_created: N_('Created a task'), task_completed: N_('Ticked off'), task_planned: N_('Planned'), comment: N_('Commented'),
  other: N_('Changed'), deadline_rejected: N_('Approval expired: rejected'), deadline_approved: N_('Approval expired: recommendation taken'),
  deadline_asked_again: N_('Approval expired: asked again'),
};
const awc_lvName = v => tr((AWC_LEVELS.find(x => x[0] === v) || AWC_LEVELS[0])[1]);
const awc_opts = (list, v, max) => list.filter((x, i) => max == null || i <= AWC_LEVELS.findIndex(l => l[0] === max))
  .map(([o, n]) => `<option value="${o}" ${v === o ? 'selected' : ''}>${esc(tr(n))}</option>`).join('');
/** @param {any} st */
function awc_html(st) {
  const d = st.control || st.defaults, chosen = st.chosen;
  const pname = id => (st.projects.find(p => p.id === +id) || {name: tr('Project {0}', id)}).name;
  const pmax = id => (st.projects.find(p => p.id === +id) || {}).max_level || 'approve_all';
  const exc = Object.entries(chosen ? d.projects : {});
  const free = st.projects.filter(p => !(String(p.id) in (chosen ? d.projects : {})));
  const hist = st.history || [];
  return `<h4 id="awc-h">${tr('Control')}</h4>
    ${chosen ? '' : `<div class="awstate" role="status" data-awc-legacy>${esc(tr('No level chosen yet - works as before.'))}</div>`}
    <div class="awclv" role="radiogroup" aria-labelledby="awc-h">${AWC_LEVELS.map(([v, n, h]) => `<label class="chkl awcl"><input type="radio" name="awc-level" data-awc="level" value="${v}" ${chosen && d.level === v ? 'checked' : ''}><span><b>${esc(tr(n))}</b><small class="muted">${esc(tr(h))}</small></span></label>`).join('')}</div>
    <div class="awsub" ${chosen && d.level === 'free' ? '' : 'hidden'}><textarea id="awc-goal" data-awc="goal" rows="2" maxlength="500" placeholder="${esc(tr('e.g. keep the project free of bugs'))}" aria-label="${esc(tr('Goal'))}">${esc(d.goal || '')}</textarea></div>
    <div class="row"><label id="awc-ph">${tr('Exceptions per project')}</label></div>
    <div class="awcp" aria-labelledby="awc-ph">${exc.map(([id, lv]) => `<div class="mrow"><span class="n">${esc(pname(id))}</span><select data-awc-proj="${id}" aria-label="${esc(pname(id))}" ${chosen ? '' : 'disabled'}>${awc_opts(AWC_LEVELS, lv, pmax(id))}</select><button type="button" class="linkbtn" data-awc-unproj="${id}">${tr('Remove')}</button></div>`).join('')}
    ${chosen && free.length ? `<div class="mrow"><select id="awc-newp" aria-label="${esc(tr('Project'))}">${free.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select><button type="button" class="btn" data-awc-addproj>${tr('Add')}</button></div>` : ''}</div>
    <div class="shint">${tr('In a project the agent gets at most your own rights there.')}</div>
    <div class="row"><label id="awc-oh">${tr('One-way steps')}</label></div>
    <div class="awco" role="group" aria-labelledby="awc-oh">${st.one_way_fixed.map(x => `<label class="chkl"><input type="checkbox" checked disabled> ${esc(x.text)}</label>`).join('')}
    ${(chosen ? d.one_way : []).map((x, i) => `<div class="mrow"><label class="chkl"><input type="checkbox" checked disabled> ${esc(x)}</label><button type="button" class="linkbtn" data-awc-unow="${i}">${tr('Remove')}</button></div>`).join('')}
    ${chosen && d.one_way.length < 20 ? `<div class="mrow"><input id="awc-now" maxlength="120" autocomplete="off" placeholder="${esc(tr('e.g. send invoices'))}" aria-label="${esc(tr('Own one-way step'))}"><button type="button" class="btn" data-awc-addow>${tr('Add')}</button></div>` : ''}</div>
    <div class="shint">${tr('Always need an approval card, on every level.')}</div>
    <div class="row"><label for="awc-deadline">${tr('Deadline for approvals')}</label><select id="awc-deadline" data-awc="deadline" ${chosen ? '' : 'disabled'}>${awc_opts(AWC_DEADLINES, d.deadline)}</select></div>
    <div class="row" ${chosen && d.deadline !== 'off' ? '' : 'hidden'}><label for="awc-then">${tr('After the deadline')}</label><select id="awc-then" data-awc="then">${awc_opts(AWC_THEN, d.then)}</select></div>
    <div class="shint" ${chosen && d.deadline !== 'off' ? '' : 'hidden'}>${tr('One-way steps are always rejected.')}</div>
    <div class="row"><label id="awc-hh">${tr('History')}</label></div>
    <div class="awch" aria-labelledby="awc-hh">${hist.length ? hist.map(h => `<div class="mrow" data-awc-row="${h.id}"><span class="n">${esc(tr(AWC_KIND[h.kind] || AWC_KIND.other))}${h.title ? ': ' + esc(h.title) : h.kind === 'other' ? ' ' + esc(h.method + ' ' + h.path) : ''}<small class="muted">${esc(fmtWhen(h.created_at))}${h.list_name ? ' · ' + esc(h.list_name) : ''}${h.via === 'approval' ? ' · ' + esc(tr('approved')) : ''}</small></span>${h.undone_at ? `<span class="muted">${tr('taken back')}</span>` : h.can_undo ? `<button type="button" class="linkbtn" data-awc-undo="${h.id}">${tr('Undo')}</button>` : ''}</div>`).join('') : `<div class="muted mhint">${tr('No decisions yet.')}</div>`}</div>`;
}
/** @param {any} md @param {any} agent */
function awc_mount(md, agent) {
  const box = $('#aw-control', md); if (!box) return;
  const base = `/api/agents/${agent.id}/control`;
  /** @type {any} */ let st = null;
  const err = m => { const e = $('#aw-err', md); if (e) { e.textContent = m || ''; e.hidden = !m; } };
  const draw = (k) => { box.innerHTML = awc_html(st); const el = k && $(`[data-awc="${k}"]`, box); if (el) savedTick(el); };
  fetch(base, {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.ok ? r.json() : null).catch(() => null)
    .then(j => { if (j) { st = j; draw(); } });  // 404 / offline: no section
  let chain = Promise.resolve();
  const save = (k, v) => chain = chain.then(async () => {
    err('');
    try { st = await api('PATCH', base, {[k]: v}); draw(k); }
    catch (e) { err(e instanceof Offline ? tr('Only available online.') : e.message); draw(); }
  });
  const cur = () => st.control || st.defaults;
  box.addEventListener('change', e => {
    const el = /** @type {any} */ (e.target);
    if (el.dataset.awcProj) { save('projects', {[el.dataset.awcProj]: el.value}); return; }
    const k = el.dataset.awc; if (!k) return;
    if (k === 'goal' && el.value.trim() === (cur().goal || '')) return;
    save(k, el.value);
  });
  box.addEventListener('click', e => {
    const t = /** @type {any} */ (e.target).closest('button'); if (!t || !st) return;
    if (t.dataset.awcUnproj) save('projects', {[t.dataset.awcUnproj]: null});
    else if ('awcAddproj' in t.dataset) { const s = /** @type {any} */ ($('#awc-newp', box)); if (s && s.value) save('projects', {[s.value]: 'approve_all'}); }
    else if (t.dataset.awcUnow) save('one_way', cur().one_way.filter((_, i) => i !== +t.dataset.awcUnow));
    else if ('awcAddow' in t.dataset) { const v = /** @type {any} */ ($('#awc-now', box)).value.trim(); if (v) save('one_way', [...cur().one_way, v]); }
    else if (t.dataset.awcUndo) {
      chain = chain.then(async () => {
        err('');
        try { st = await api('POST', `${base}/history/${t.dataset.awcUndo}/undo`); draw(); toast(tr('Taken back')); }
        catch (e2) { err(e2 instanceof Offline ? tr('Only available online.') : e2.message); }
      });
    }
  });
  box.addEventListener('keydown', e => {
    const el = /** @type {any} */ (e.target);
    if (e.key === 'Enter' && el.id === 'awc-now') { e.preventDefault(); /** @type {any} */ ($('[data-awc-addow]', box)).click(); }
  });
}
