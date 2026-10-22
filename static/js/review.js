/* Kalmido web client: the review step of a list (2.60.0, #1512).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- 2.60.0 C (#1512): a list switches the review step on (lists.review_cfg json {on, reviewer, section, gate}, editors of
// the list change it in its settings). A task shows its reviewer and the review state in the task panel; the reviewer (or
// an owner / admin of the list, never the assignee on their own task) approves it or sends it back. Moving a task into the
// review section asks for the review (server). With "Done only after approval" ticking off waits for the approval: the
// tick explains it and offers "Send for review". Every step here is one undo step (action restore on the server).
const RVW_TXT = {pending: N_('Waiting for the approval of {0}'), approved: N_('Approved by {0}'), changes: N_('{0} sent it back')};
function rvw_cfgOf(l) {
  if (!l || !l.review_cfg) return null;
  try { const o = JSON.parse(l.review_cfg); return o && o.on ? o : null; } catch { return null; }
}
const rvw_name = id => id === S.me?.id ? tr('you') : apName(id);
// may I approve / send back? (the server decides; this only shows the buttons)
function rvw_may(t) {
  const admin = canManage(listById(t.list_id));
  if (t.assignee_id === S.me?.id && !admin) return false;
  return t.reviewer_id === S.me?.id || admin;
}
// a tick that the server would refuse (409) -- explained before the request
const rvw_blocked = t => !!t && t.status === 0 && !!t.reviewer_id && t.review !== 'approved' && !!rvw_cfgOf(listById(t.list_id))?.gate;
async function rvw_blockedAsk(t) {
  const send = t.review !== 'pending' && canEdit(t);
  if (!send) { toast(tr('Waiting for approval by {0}', rvw_name(t.reviewer_id))); return; }
  if (await askConfirm(tr('Waiting for approval by {0}', rvw_name(t.reviewer_id)), tr('In this project a task is done only after the approval of its reviewer.'),
    {ok: tr('Send for review')})) rvw_do(t.id, 'request');
}
// the bar in the task panel (detail.js, under the approval bar)
function rvw_barHtml(t, ro) {
  if (!t || !(t.id > 0) || !collab()) return '';
  const l = listById(t.list_id), cfg = rvw_cfgOf(l);
  if (!cfg && !t.reviewer_id) return '';
  const st = t.review || '', who = t.reviewer_id ? rvw_name(t.reviewer_id) : '';
  const txt = st === 'approved' && !t.review_by ? tr('Approved by a linked pull request')
    : st === 'pending' && t.reviewer_id === S.me?.id ? tr('Waiting for your approval')
      : st ? tr(RVW_TXT[st], st === 'pending' ? who : rvw_name(t.review_by || t.reviewer_id))
      : t.reviewer_id ? tr('Reviewer: {0}', who) : tr('No reviewer yet');
  const may = rvw_may(t) && t.status === 0, b = (k, h) => `<button type="button" class="btn sm${k === 'approve' ? ' pri' : ''}" data-rvw="${k}" data-id="${t.id}">${h}</button>`;
  const acts = [
    may && (st === 'pending' || st === 'changes') ? b('approve', `${thumbIc(true)} ${tr('Approve')}`) : '',
    may && (st === 'pending' || st === 'approved') ? b('changes', `${thumbIc(false)} ${tr('Back|review')}`) : '',
    !ro && t.status === 0 && st !== 'pending' && (t.reviewer_id || cfg?.reviewer) ? `<button type="button" class="linkbtn" data-rvw="request" data-id="${t.id}">${tr('Send for review')}</button>` : '',
    !ro ? `<button type="button" class="linkbtn" data-rvw="pick" data-id="${t.id}">${t.reviewer_id ? tr('Change reviewer') : tr('Choose reviewer')}</button>` : ''].join('');
  return `<div class="apbar rvwbar rvw-${st || 'none'}" role="status">${st === 'approved' ? thumbIc(true) : st === 'changes' ? thumbIc(false) : ic('eye', 's')}<span class="apt">${esc(txt)}</span>${acts ? `<span class="apacts">${acts}</span>` : ''}</div>`;
}
const rvw_snap = t => ({reviewer_id: t.reviewer_id ?? null, review: t.review || '', section_id: t.section_id ?? null});
async function rvw_post(id, b) { const r = await api('POST', `/api/tasks/${id}/review`, b); putTask(r); return r; }
async function rvw_after(id) { await load(); render(); if (S.sel === id) renderDetail(); }
// one step + its undo (restore the state before / after)
async function rvw_do(id, act, extra = {}) {
  const t = taskById(id); if (!t) return;
  const before = rvw_snap(t);
  let note = '';
  if (act === 'changes') {
    const v = await askPrompt(tr('What should change?'), '', {body: tr('optional, the assignee sees it'), input: {max: 2000}});
    if (v === null) return;
    note = v;
  }
  let r; try { r = await rvw_post(id, {action: act, ...extra, ...(note ? {note} : {})}); } catch { return; }
  const after = rvw_snap(r);
  await rvw_after(id);
  const msg = {approve: tr('Approved'), changes: tr('Sent back for changes'), request: tr('Sent for review'), reviewer: tr('Reviewer changed')}[act];
  offerUndo(msg, histAdd({label: msg, ids: [id],
    undo: async () => { await rvw_post(id, {action: 'restore', ...before}); await rvw_after(id); return {skipped: []}; },
    redo: async () => { await rvw_post(id, {action: 'restore', ...after}); await rvw_after(id); return {skipped: []}; }}));
}
function rvw_pick(id) {
  const t = taskById(id), l = t && listById(t.list_id); if (!l) return;
  const ppl = listPeople(l).filter((p, i, a) => a.findIndex(x => x.user_id === p.user_id) === i);
  const md = modal(`<h3>${tr('Reviewer')}</h3><p class="muted">${esc(t.title)}</p>
    <div class="row"><label for="rvw-who">${tr('Who reviews?')}</label><select id="rvw-who"><option value="">${tr('No reviewer')}</option>${ppl.map(p => `<option value="${p.user_id}" ${p.user_id === t.reviewer_id ? 'selected' : ''}>${esc(p.name)}${p.agent ? ' · ' + esc(tr('Agent')) : ''}</option>`).join('')}</select></div>
    <div class="shint lhint keep">${tr('A person or an agent of this project. They approve the task or send it back.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    const v = $('#rvw-who', md).value;
    md.remove();
    if (b.dataset.m === 'save') rvw_do(id, 'reviewer', {reviewer_id: v ? +v : null});
  });
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-rvw]'); if (!a) return;
  e.preventDefault(); e.stopPropagation();
  const id = +a.dataset.id, k = a.dataset.rvw;
  if (k === 'pick') rvw_pick(id);
  else rvw_do(id, k);
});

// ---- the setting in the list's settings (dialogs.js listModal), editors of the list
function rvw_rowHtml(l) {
  if (!l || l.is_inbox || !collab() || !canEditList(l.id)) return '';
  const cfg = rvw_cfgOf(l) || {}, secs = S.sections.filter(s => s.list_id === l.id), ppl = listPeople(l);
  return `<div class="row lrvwrow"><label>${tr('Review')}</label><label class="chkl"><input type="checkbox" id="l-rvw" ${cfg.on ? 'checked' : ''}> ${tr('Review step')}</label></div>
    <div class="lrvwx" ${cfg.on ? '' : 'hidden'}>
    <div class="row"><label for="l-rvw-who">${tr('Default reviewer')}</label><select id="l-rvw-who"><option value="">${tr('None')}</option>${ppl.map(p => `<option value="${p.user_id}" ${p.user_id === cfg.reviewer ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>
    <div class="row"><label for="l-rvw-sec">${tr('Review section')}</label><select id="l-rvw-sec"><option value="">${tr('The section named “Review”')}</option>${secs.map(s => `<option value="${s.id}" ${s.id === cfg.section ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
    <div class="row"><span></span><label class="chkl"><input type="checkbox" id="l-rvw-gate" ${cfg.gate ? 'checked' : ''}> ${tr('Done only after approval')}</label></div></div>
    <div class="shint lhint">${tr('Moving a task into the review section asks its reviewer for the approval. Pull requests that are merged or approved count too.')}</div>`;
}
function rvw_val(md) {
  if (!$('#l-rvw', md)?.checked) return {on: false};
  const w = $('#l-rvw-who', md).value, s = $('#l-rvw-sec', md).value;
  return {on: true, reviewer: w ? +w : null, section: s ? +s : null, gate: $('#l-rvw-gate', md).checked};
}
function rvw_wire(md, id) {
  if (!$('#l-rvw', md)) return;
  const go = async () => {
    const l = listById(id); if (!l) return;
    const was = rvw_cfgOf(l) || {on: false}, v = rvw_val(md);
    $('.lrvwx', md).hidden = !v.on;
    const put = async b => { const j = await api('PUT', `/api/lists/${id}/review`, b); const x = listById(id); if (x) x.review_cfg = j.review_cfg; return j; };
    try { await put(v); } catch { $('#l-rvw', md).checked = !!was.on; $('.lrvwx', md).hidden = !was.on; return; }
    render();
    const old = was.on ? {on: true, reviewer: was.reviewer ?? null, section: was.section ?? null, gate: !!was.gate} : {on: false};
    offerUndo(v.on ? tr('Review step saved') : tr('Review step off'), histAdd({label: tr('Review step'),
      undo: async () => { await put(old); await load(); render(); return {skipped: []}; },
      redo: async () => { await put(v); await load(); render(); return {skipped: []}; }}));
  };
  for (const s of ['#l-rvw', '#l-rvw-who', '#l-rvw-sec', '#l-rvw-gate']) $(s, md)?.addEventListener('change', e => { e.stopPropagation(); go(); });
}

// ---- the notification row "review" (account.js matrix, dialogs.js owner templates) and the News / activity lines
NOTIF_ROWS.splice(NOTIF_ROWS.findIndex(r => r[0] === 'approval') + 1, 0, ['review', N_('Reviews'), N_('a review is asked of me, or my task comes back from its review')]);
NM_NEWS_NEW.review = 1; NM_PUSH.review = 1; NM_SOCIAL.push('review');
NTF_CUSTOM.push('review'); NTF_WORK.push('review');
NEWS_ICON.review = 'eye';
NEWS_CHIPS.find(x => x[0] === 'assign')?.[3].push('review');
function rvw_newsText(it, d, who, q) {
  return d.state === 'changes' ? tr('{0} sent back {1} from review', who, q(it.task_title || '')) + (d.note ? ': ' + q(d.note) : '')
    : tr('{0} asks you to review {1}', who, q(it.task_title || ''));
}
function rvw_actText(d, who, q, U) {
  if (d.state === 'approved' && d.pr) return tr('A linked pull request approved the review: {0}', q(d.pr));
  const t = {pending: tr('{0} asked {1} for a review', who, q(uname(d.reviewer, U))), approved: tr('{0} approved the review', who),
    changes: tr('{0} sent the task back from review', who), reviewer: d.reviewer ? tr('{0} made {1} the reviewer', who, q(uname(d.reviewer, U))) : tr('{0} removed the reviewer', who),
    '': tr('{0} reset the review', who)}[d.state] || '';
  return t + (d.note ? ': ' + q(d.note) : '');
}
