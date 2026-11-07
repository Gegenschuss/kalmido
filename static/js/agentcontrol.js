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
  other: N_('Entry changed'), task_changed: N_('Task changed'), decision: N_('Decided'), deadline_rejected: N_('Approval expired: rejected'), deadline_approved: N_('Approval expired: recommendation taken'),
  deadline_asked_again: N_('Approval expired: asked again'),
};
// 2.653.0 (#5079): the history in words -- never method + path. A task change names its field, a line of another area names the
// area; like steps of the agent in a row (same kind, same project, at most AWC_GAP apart) are one line that opens to the single
// steps (each with its own Undo). The dialog shows the newest AWC_DLG lines (a group counts as one), "Show whole history" the rest.
const AWC_FIELD = {
  title: N_('Title changed'), content: N_('Notes changed'), notes: N_('Notes changed'), description: N_('Notes changed'),
  priority: N_('Priority changed'), list_id: N_('Moved to another project'), section_id: N_('Moved to another section'),
  parent_id: N_('Moved under another task'), assignee_id: N_('Assignment changed'), assignee_group_id: N_('Assignment changed'),
  delegate_agent_id: N_('Assignment changed'), reviewer_id: N_('Assignment changed'), tags: N_('Tags changed'), ltags: N_('Tags changed'),
  labels: N_('Tags changed'), list_tags: N_('Tags changed'), milestone: N_('Milestone changed'), locked: N_('Lock changed'), fields: N_('Fields changed'), status: N_('Status changed'),
  sprint_id: N_('Sprint changed'), milestone_id: N_('Milestone changed'), ms: N_('Milestone changed'), points: N_('Points changed'),
  due: N_('Dates changed'), due_time: N_('Dates changed'), start: N_('Dates changed'), plan_start: N_('Dates changed'),
  deadline: N_('Dates changed'), duration: N_('Dates changed'), reminders: N_('Reminder changed'), remind_at: N_('Reminder changed'),
  repeat: N_('Repeat changed'), repeat_from: N_('Repeat changed'), ttype: N_('Type changed'), type: N_('Type changed'), url: N_('Link changed'),
};
const AWC_AREA = {
  tasks: N_('Tasks'), lists: N_('Projects'), comments: N_('Comments'), events: N_('Calendar'), calendars: N_('Calendar'),
  documents: N_('Documents'), files: N_('Files'), folders: N_('Files'), time: N_('Time tracking'), office: N_('Office'),
  team: N_('Team chat'), contacts: N_('Contacts'), videos: N_('Videos'), notes: N_('Notes'),
};
const AWC_GROUP = {  // [without a project, in project {1}]
  task_created: [N_('{0} tasks created'), N_('{0} tasks created in {1}')], task_completed: [N_('{0} tasks ticked off'), N_('{0} tasks ticked off in {1}')],
  task_planned: [N_('{0} tasks planned'), N_('{0} tasks planned in {1}')], task_changed: [N_('{0} tasks changed'), N_('{0} tasks changed in {1}')],
  comment: [N_('{0} comments written'), N_('{0} comments written in {1}')], decision: [N_('{0} decisions'), N_('{0} decisions')],
  other: [N_('{0} entries changed'), N_('{0} entries changed in {1}')], deadline: [N_('{0} approvals expired'), N_('{0} approvals expired')],
};
const AWC_GAP = 5 * 60000, AWC_DLG = 5;
const awc_gkind = h => /^deadline_/.test(h.kind) ? 'deadline' : (AWC_GROUP[h.kind] ? h.kind : 'other');
/** one line of the history in words -> [text, extra for the small line] @param {any} h */
function awc_text(h) {
  const fs = [...new Set((h.fields || []).map(f => AWC_FIELD[f]).filter(Boolean))];
  if (h.kind === 'task_changed') {
    const head = h.count > 1 ? tr('{0} tasks changed', h.count) : fs.length === 1 ? tr(fs[0]) : tr(AWC_KIND.task_changed);
    return [head + (h.title ? ': ' + h.title : ''), fs.length > 1 || (h.count > 1 && fs.length) ? fs.map(x => tr(x)).join(', ') : ''];
  }
  if (h.kind === 'decision') return [tr('Decided: {0}', h.title), h.ref || ''];
  if (!AWC_KIND[h.kind] || h.kind === 'other') return [tr(AWC_KIND.other), AWC_AREA[h.area] ? tr(AWC_AREA[h.area]) : ''];
  return [tr(AWC_KIND[h.kind]) + (h.title ? ': ' + h.title : ''), ''];
}
/** @param {any} h */
function awc_row(h) {
  const [t, x] = awc_text(h);
  return `<div class="mrow" data-awc-row="${h.id}"><span class="n">${esc(t)}<small class="muted">${esc(fmtWhen(h.created_at))}${x ? ' · ' + esc(x) : ''}${h.list_name ? ' · ' + esc(h.list_name) : ''}${h.via === 'approval' ? ' · ' + esc(tr('approved')) : ''}</small></span>${h.undone_at ? `<span class="muted">${tr('undone')}</span>` : h.can_undo ? `<button type="button" class="linkbtn" data-awc-undo="${h.id}">${tr('Undo')}</button>` : ''}</div>`;
}
/** the lines (newest first) in groups: like steps in a row, same project, at most AWC_GAP between two -> [[line, ...], ...] @param {any[]} hist */
function awc_groups(hist) {
  const out = [];
  for (const h of hist) {
    const g = out[out.length - 1], p = g && g[g.length - 1];
    if (p && awc_gkind(p) === awc_gkind(h) && p.list_id === h.list_id && (h.kind !== 'other' || p.area === h.area)
        && Math.abs(Date.parse(p.created_at) - Date.parse(h.created_at)) <= AWC_GAP) g.push(h);
    else out.push([h]);
  }
  return out;
}
/** @param {any[]} g */
function awc_group(g) {
  if (g.length === 1) return awc_row(g[0]);
  const h = g[0], keys = AWC_GROUP[awc_gkind(h)], area = h.kind === 'other' && AWC_AREA[h.area] ? ' · ' + tr(AWC_AREA[h.area]) : '';
  const n = g.reduce((a, x) => a + (x.kind === 'task_changed' && x.count > 1 ? x.count : 1), 0);
  const head = h.list_name ? tr(keys[1], n, h.list_name) : tr(keys[0], n);
  const span = fmtWhen(g[g.length - 1].created_at) === fmtWhen(h.created_at) ? fmtWhen(h.created_at) : fmtWhen(g[g.length - 1].created_at) + ' – ' + fmtWhen(h.created_at);
  return `<details class="awcg" data-awc-group="${h.id}"><summary class="mrow"><span class="n">${esc(head)}<small class="muted">${esc(span)}${esc(area)}</small></span></summary><div class="awcgl">${g.map(awc_row).join('')}</div></details>`;
}
/** @param {any[]} hist @param {number} [max] */
function awc_histHtml(hist, max) {
  const gs = awc_groups(hist), show = max ? gs.slice(0, max) : gs;
  return show.length ? show.map(awc_group).join('') : `<div class="muted mhint">${tr('No decisions yet.')}</div>`;
}
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
    ${chosen ? '' : `<div class="awstate" role="status" data-awc-legacy>${esc(tr('No level selected yet - works as before.'))}</div>`}
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
    <div class="awch" aria-labelledby="awc-hh">${awc_histHtml(hist, AWC_DLG)}</div>
    ${hist.length ? `<div class="row"><button type="button" class="linkbtn" data-awc-all>${tr('Show whole history')}</button></div>` : ''}`;
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
        try { st = await api('POST', `${base}/history/${t.dataset.awcUndo}/undo`); draw(); toast(tr('Undone')); }
        catch (e2) { err(e2 instanceof Offline ? tr('Only available online.') : e2.message); }
      });
    }
    else if ('awcAll' in t.dataset) modalSub(md, () => awc_all(agent, base, j => { st = j; draw(); }));
  });
  box.addEventListener('keydown', e => {
    const el = /** @type {any} */ (e.target);
    if (e.key === 'Enter' && el.id === 'awc-now') { e.preventDefault(); /** @type {any} */ ($('[data-awc-addow]', box)).click(); }
  });
}
// 2.653.0 (#5079): the view "Whole history" (a sub-dialog of the settings: "Done" goes back): all lines in groups, page by page
// (GET .../control/history?before=&limit=), Undo per single step; an undo also redraws the dialog below (back(state)).
/** @param {any} agent @param {string} base @param {(st: any) => void} back */
function awc_all(agent, base, back) {
  const md = /** @type {any} */ (modal(`<h3 id="awc-all-h">${esc(tr('History'))}</h3>
    <div class="shint keep">${esc(tr('What {0} did and decided, newest first.', agent.name))}</div>
    <div class="awch awcall" aria-labelledby="awc-all-h"><div class="muted mhint">${esc(tr('Loading…'))}</div></div>
    <div class="row" hidden><button type="button" class="btn" data-awc-more>${tr('Load more')}</button></div>
    <div class="calerr" role="alert" id="awc-all-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`));
  md.classList.add('awdlg', 'awcalldlg');
  /** @type {any[]} */ let rows = []; let more = false, busy = false;
  const box = $('.awcall', md), moreRow = $('[data-awc-more]', md).parentElement;
  const err = m => { const e = $('#awc-all-err', md); e.textContent = m || ''; e.hidden = !m; };
  const draw = () => {
    const open = new Set($$('details[open]', box).map(x => x.dataset.awcGroup));
    box.innerHTML = awc_histHtml(rows);
    $$('details', box).forEach(x => { if (open.has(x.dataset.awcGroup)) x.open = true; });
    moreRow.hidden = !more;
  };
  const load = async () => {
    if (busy) return; busy = true; err('');
    try {
      const j = await api('GET', `${base}/history?limit=100${rows.length ? '&before=' + rows[rows.length - 1].id : ''}`);
      rows = rows.concat(j.history || []); more = !!j.more; draw();
    } catch (e) { err(e instanceof Offline ? tr('Only available online.') : e.message); }
    busy = false;
  };
  md.addEventListener('click', async e => {
    const t = /** @type {any} */ (e.target).closest('button'); if (!t) return;
    if (t.dataset.m === 'close') { md.remove(); return; }
    if ('awcMore' in t.dataset) { load(); return; }
    if (t.dataset.awcUndo) {
      err('');
      try {
        const st = await api('POST', `${base}/history/${t.dataset.awcUndo}/undo`);
        const id = +t.dataset.awcUndo, h = rows.find(x => x.id === id);
        if (h) { h.undone_at = new Date().toISOString(); h.can_undo = false; }
        draw(); back(st); toast(tr('Undone'));
      } catch (e2) { err(e2 instanceof Offline ? tr('Only available online.') : e2.message); }
    }
  });
  load();
  return md;
}
