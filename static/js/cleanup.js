/* Kalmido web client: "Tidy up the list" (2.39.0, #1151).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// The list's tidy agent (#379) gets the open top-level tasks (all, or the selected ones) in packages of 50 and answers with
// ONE proposal per package (merge, rename, move, close). Nothing changes until the person applies the ticked entries in the
// usual proposal sheet (agents.js propOpen); one undo step takes everything back. Tasks someone is editing right now or that
// changed since the request are skipped on the server and listed with the reason.
const CLN_PACK = 50, CLN_MAX = 250;
const clnAgent = l => { const cs = l ? tidyCands(l) : []; return cs.find(a => a.id === l.tidy_agent_id) || cs[0] || null; };
function clnOk(l) {  // the entry points: a list with a tidy agent, where I may write; never a health list, the inbox, an archive
  return !!l && collab() && agentsOn() && !l.archived && !l.is_inbox && l.life !== 'health' && canEditList(l.id) && !!clnAgent(l);
}
function clnSel() {  // the selection: open top-level tasks of ONE such list -> that list, else null
  const ts = [...S.multi].map(i => S.tasks.get(i));
  if (!ts.length || ts.some(t => !t || t.id < 0 || t.parent_id || t.status !== 0 || t.deleted_at)) return null;
  const l = listById(ts[0].list_id);
  return ts.every(t => t.list_id === ts[0].list_id) && clnOk(l) ? l : null;
}
function clnRequest(lid, ids = null) {
  const l = listById(lid), ag = clnAgent(l); if (!clnOk(l)) return;
  const n = ids ? ids.length : [...S.tasks.values()].filter(t => t.list_id === lid && !t.parent_id && t.status === 0 && !t.deleted_at && t.id > 0).length;
  if (!n) { toast(tr('There are no open tasks to tidy up')); return; }
  const sent = Math.min(n, CLN_MAX), packs = Math.ceil(sent / CLN_PACK);
  const md = modal(`<h3>${ic('bot', 's')} ${esc(ids ? tr('Tidy up with {0}', ag.name) : tr('Tidy up the list with {0}', ag.name))}</h3>
    <div class="pptask">${ic('list', 's')}<b>${esc(lname(l))}</b><span class="muted">${esc(ids ? trn('{0} selected task', '{0} selected tasks', n) : trn('{0} open task', '{0} open tasks', n))}</span></div>
    <div class="row ppcol"><label for="cln-hint">${tr('Hint (optional)')}</label><textarea id="cln-hint" rows="3" maxlength="2000" placeholder="${esc(tr('e.g. merge duplicates, close what is older than a year'))}"></textarea></div>
    ${packs > 1 ? `<div class="shint" id="cln-pack">${esc(tr('The tasks go to {0} in {1} packages of up to {2}: each package comes back as its own proposal.', ag.name, packs, CLN_PACK))}${n > CLN_MAX ? ' ' + esc(tr('Only the first {0} tasks are sent; ask again for the rest afterwards.', CLN_MAX)) : ''}</div>` : ''}
    <div class="shint" id="cln-priv">${tr('{0} gets the titles, notes, sections, tags and dates of these tasks (and the list’s playbook) and proposes what to merge, rename, move or close. Nothing changes until you apply it; one step, undo takes it back.', `<b>${esc(ag.name)}</b>`)}</div>
    <div class="calerr" role="alert" id="cln-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${ic('bot', 's')} ${tr('Ask for a proposal')}</button></div>`);
  md.classList.add('ppreq', 'clnreq');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const q = {kind: 'cleanup', list_id: lid, hint: $('#cln-hint', md).value.trim() || null};
    if (ids) q.task_ids = ids;
    b.disabled = true;
    let r;
    try { r = await calReq('POST', '/api/proposals', q); } catch (x) { const er = $('#cln-err', md); er.textContent = x.message; er.hidden = false; b.disabled = false; return; }
    md.remove();
    toast(r.packages > 1 ? tr('Sent to {0} in {1} packages: you get a notification for each proposal', r.agent?.name || ag.name, r.packages)
      : tr('Sent to {0}: you get a notification when the proposal is ready', r.agent?.name || ag.name));
    if (ids) { S.multi.clear(); S.multiMode = false; render(); }
    if (S.route.mod === 'agents') loadJobs();
  });
  setTimeout(() => $('#cln-hint', md)?.focus(), 50);
}
// ---- the review (inside the proposal sheet): one clear sentence per entry, the title editable for rename / merge
function clnTitle(id) {
  const t = taskById(id); if (t) return t.title;
  return ((S.prop?.v.input.items || []).find(x => x.task_id === id) || {}).title || '#' + id;
}
function clnSec(sid) {
  if (sid === null || sid === undefined) return tr('No section');
  return ((S.prop?.v.input.list?.sections || []).find(s => s.id === sid) || {}).name || tr('No section');
}
function clnSentence(x) {
  const q = s => '“' + s + '”';
  if (x.op === 'merge') return tr('Merge: {0} → {1}', x.task_ids.map(i => q(clnTitle(i))).join(' + '), q(clnTitle(x.task_ids[0])));
  if (x.op === 'rename') return tr('Rename: {0}', q(clnTitle(x.task_id)));
  if (x.op === 'close') return tr('Close as won’t do: {0}', q(clnTitle(x.task_id)));
  const t = q(clnTitle(x.task_id));  // move: the section and / or the place inside the section (two different things)
  if (x.section && x.position) return tr('Move {0} to section {1}, place {2}', t, q(clnSec(x.section_id)), x.position);
  if (x.section) return tr('Move {0} to section {1}', t, q(clnSec(x.section_id)));
  return tr('Move {0} to place {1} in its section', t, x.position);
}
const CLN_ICON = {merge: 'deps', rename: 'edit', move: 'arrow', close: 'x'};
function clnItemsHtml() {
  const p = S.prop.v.proposal;
  return p.items.map((x, i) => {
    const k = String(i), on = S.prop.sel.has(k), edit = x.op === 'rename' || x.op === 'merge';
    const title = S.prop.ed[k]?.title ?? (x.title || (x.op === 'merge' ? clnTitle(x.task_ids[0]) : ''));
    return `<div class="ppi clni ${on ? '' : 'off'}" data-k="${k}" data-op="${x.op}">
      <label class="ppcl"><input type="checkbox" class="ppc" id="ppc-${k}" ${on ? 'checked' : ''} aria-label="${esc(tr('Select {0}', clnSentence(x)))}"></label>
      <div class="ppb"><div class="clns">${ic(CLN_ICON[x.op] || 'bot', 's')}<span>${esc(clnSentence(x))}</span></div>
        ${edit ? `<div class="pprow"><input class="ppt" data-f="title" value="${esc(title)}" maxlength="300" aria-label="${esc(tr('New title'))}"></div>` : ''}
        ${x.reason ? `<div class="ppn muted clnr">${esc(x.reason)}</div>` : ''}</div></div>`;
  }).join('');
}
const clnPack = v => (v.input?.package?.of || 1) > 1 ? tr('Package {0} of {1}', v.input.package.n, v.input.package.of) : '';
function clnDone(r) {  // after applying: what happened, and what was skipped (with the reason)
  const n = (r.merge || 0) + (r.rename || 0) + (r.move || 0) + (r.close || 0), sk = r.skipped || [];
  if (!sk.length) return trn('{0} change applied', '{0} changes applied', n);
  const md = modal(`<h3>${ic('check', 's')} ${esc(trn('{0} change applied', '{0} changes applied', n))}</h3>
    <p class="muted">${esc(trn('{0} task was skipped:', '{0} tasks were skipped:', sk.length))}</p>
    <ul class="clnsk">${sk.map(s => `<li><b>${esc(s.title)}</b> <span class="muted">${esc(s.why_text || s.why)}</span></li>`).join('')}</ul>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('OK')}</button></div>`);
  md.classList.add('clnres');
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) md.remove(); });
  return trn('{0} change applied', '{0} changes applied', n) + ' · ' + tr('{0} skipped', sk.length);
}
