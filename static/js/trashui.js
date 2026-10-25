// @ts-check
/* Kalmido web client: the trash dialogs and views of 2.272.0 (#3025-#3045), loaded on demand (2.272.0 G, #3038: the start
   budget). Classic script sharing the global scope with the others; lazyload.js LD_MODS trashui. The start files call in
   through stand-ins (LD_CALL, LD_VIEW) or `await loadModule('trashui')` before the call: the clients' trash and the delete
   dialog of their selection (clientpage.js; its text stays in clients.js cl_delText), the trash of a task's / a project's
   files (detail.js, events.js, projects.js), "Delete completed" (render.js) and a checklist's "Clear done" (events.js). */
'use strict';
// 2.272.0 D (#3029): deleting clients from the list's selection (clientpage.js ms_clAct): the dialog names what points at them
async function ms_clDel(ids) {
  const u = await api('GET', `/api/clients/usage?ids=${ids.join(',')}`).catch(() => null);  // 2.272.0 D (#3029): what points at them
  if (!await askConfirm(trn('Delete {0} client?', 'Delete {0} clients?', ids.length), cl_delText(u, ids.length), {ok: tr('Delete'), danger: true})) return;
  let j; try { j = await ms_clSend({action: 'delete', ids}); } catch (x) { toast(x.message || ''); return; }
  if (S.route.client && ids.includes(S.route.client) && !j.undo.some(x => x.id === S.route.client)) go('clients');
  ms_clEnd(); await ms_clAfter(); MSC.tItems = null;
  const back = async () => { if (j.trashed?.length) await ms_clSend({action: 'untrash', ids: j.trashed}); if (j.undo.length) await ms_clSend({action: 'restore', items: j.undo}); MSC.tItems = null; await ms_clAfter(); };
  if (j.trashed?.length || j.undo.length) { const m = trn('{0} deleted', '{0} deleted', j.deleted); ms_hist(m, m, back, async () => { j = await ms_clSend({action: 'delete', ids}); MSC.tItems = null; await ms_clAfter(); }); }
  toast([trn('{0} deleted', '{0} deleted', j.deleted), j.archived ? trn('{0} archived (in use)', '{0} archived (in use)', j.archived) : '', j.skipped ? trn('{0} skipped (only the creator or an admin may delete it)', '{0} skipped (only the creator or an admin may delete them)', j.skipped) : ''].filter(Boolean).join(' · '));
}
// 2.272.0 D (#3029): the clients' trash (box "Trash" in the list bar): restore, delete for good (asks with the numbers)
async function ms_clTrashLoad() {
  MSC.tItems = [];
  try { const j = await api('GET', '/api/clients/trash'); MSC.tItems = (j.clients || []).filter(ms_inWs); MSC.tDays = j.trash_days || 0; } catch { /* quiet: the list stays empty */ }
  ms_clDraw();
}
function ms_clTrashHtml() {
  if (MSC.tItems === null) { setTimeout(ms_clTrashLoad, 0); return `<div class="muted ctempty">${tr('Loading…')}</div>`; }
  const hint = MSC.tDays ? `<p class="muted mscltrdays">${esc(trashNote(tr('Clients in the trash are deleted for good after {0} days.', MSC.tDays)))}</p>` : '';
  if (!MSC.tItems.length) return `<div class="empty">${ic('trash')}${tr('The trash is empty')}</div>${hint}`;
  return `<ul class="ctlist mscltrash" role="list" aria-label="${esc(tr('Trash'))}">${MSC.tItems.map(c => `<li><div class="ctrow msarch">${ms_clAv(c)}<span class="ctn"><b>${esc(c.label || c.name)}</b><small class="muted">${esc(tr('In the trash since {0}', fmtDate((c.deleted_at || '').slice(0, 10))))}</small></span>
    ${c.can_delete ? `<button type="button" class="btn sm" data-mscl="trest" data-id="${c.id}">${ic('undo', 's')} ${tr('Restore')}</button><button type="button" class="iconbtn" data-mscl="tpurge" data-id="${c.id}" aria-label="${esc(tr('Delete for good'))}" title="${esc(tr('Delete for good'))}">${ic('trash', 's')}</button>` : ''}</div></li>`).join('')}</ul>${hint}`;
}
async function ms_clTrashAct(k, id) {
  const c = (MSC.tItems || []).find(x => x.id === id); if (!c) return;
  if (k === 'trest') {
    try { await api('POST', `/api/clients/${id}/restore`); } catch (x) { toast(x.message || ''); return; }
    toast(tr('Restored')); MSC.tItems = null; await ms_clAfter(); return;
  }
  const u = await api('GET', `/api/clients/usage?ids=${id}`).catch(() => null);
  if (!await askConfirm(tr('Delete the client “{0}” for good?', c.label || c.name), [u?.text ? tr('Linked: {0}.', u.text) : '', tr('This cannot be undone.')].filter(Boolean).join(' '), {ok: tr('Delete for good'), danger: true})) return;
  try { await api('DELETE', `/api/clients/${id}/purge`); } catch (x) { toast(x.message || ''); MSC.tItems = null; await ms_clAfter(); return; }
  toast(tr('Deleted for good')); MSC.tItems = null; ms_clDraw();
}
// 2.272.0 E2 (#3038): the task's files in the trash (task and comment files), each with "Restore", and the trash period
function attTrashHtml(t) {
  const arr = t.attachments_trash || [];
  if (!arr.length) return '';
  // 2.272.0 F (#3038, review E2-M6 / E2-H2): a comment's file only for its author or a project manager (as the server), + "Delete for good"
  const may = a => canEdit(t) && (!a.comment_id || a.mine || canManage(listById(t.list_id)));
  const rows = arr.map(a => `<li><span class="an">${esc(String(a.name).startsWith('e2e1:') ? tr('Encrypted file') : a.name)}</span> <span class="muted">${fmtSize(a.size || 0)}</span>${may(a) ? ` <button class="linkbtn" type="button" data-act="att-restore" data-att="${a.id}">${esc(tr('Restore'))}</button> <button class="linkbtn" type="button" data-act="att-purge" data-att="${a.id}">${esc(tr('Delete for good'))}</button>` : ''}</li>`).join('');
  const d = arr[0].days || 30;
  return `<details class="atrash"><summary class="muted">${ic('trash', 's')} ${esc(tr('Trash'))} (${arr.length})</summary><ul>${rows}</ul><p class="muted">${esc(trashNote(trn('Files in the trash are deleted for good after {0} day.', 'Files in the trash are deleted for good after {0} days.', d)))}</p></details>`;
}
// 2.272.0 F (#3038, review E2-H2): a file in the trash deleted for good by the person (asked first)
async function attPurge(aid, name) {
  if (!await askConfirm(tr('Delete “{0}” for good?', name || ''), tr('This cannot be undone.'), {ok: tr('Delete for good'), danger: true})) return;
  let j; try { j = await api('DELETE', `/api/attachments/${aid}/purge`); } catch { return; }
  if (j && j.id) putTask(j); render(); renderDetail();
}
async function attRestore(aid) {
  let j; try { j = await api('POST', `/api/attachments/${aid}/restore`); } catch { return; }
  if (j && j.id) putTask(j); render(); renderDetail();
  if (S.tl) loadTimeline(S.sel);  // a comment file shows in its comment again
  toast(tr('Restored'));
}
// 2.272.0 E2 (#3038): the project files in the trash, each with "Restore", and the trash period
function povTrashHtml(j, can) {
  const arr = j.files_trash || [];
  if (!arr.length) return '';
  const rows = arr.map(f => `<li><span class="an">${esc(String(f.name).startsWith('e2e1:') ? tr('Encrypted file') : f.name)}</span> <span class="muted">${fmtSize(f.size || 0)}</span>${can ? ` <button class="linkbtn" type="button" data-pov="file-restore" data-id="${f.id}">${esc(tr('Restore'))}</button> <button class="linkbtn" type="button" data-pov="file-purge" data-id="${f.id}">${esc(tr('Delete for good'))}</button>` : ''}</li>`).join('');  // 2.272.0 F (#3038, E2-H2)
  const d = j.files_trash_days || 30;  // 2.272.0 F (#3038, review E2-N4): plural
  return `<details class="atrash"><summary class="muted">${ic('trash', 's')} ${esc(tr('Trash'))} (${arr.length})</summary><ul>${rows}</ul><p class="muted">${esc(trashNote(trn('Files in the trash are deleted for good after {0} day.', 'Files in the trash are deleted for good after {0} days.', d)))}</p></details>`;
}
// 1.5.2: "Delete completed…" on the Completed view: all, or those completed more than 30 / 90 days ago, go to the
// trash (restorable, one undo step). Only what the user may change; items of checklists stay (the reusable part of such
// a list). Completions of recurring tasks are done copies of their own, so the open series is never touched.
async function doneCleanup() {
  let all;
  try { all = (await api('GET', '/api/tasks?scope=done&limit=2000')).tasks || []; } catch { return; }
  const isCk = t => !!listById(t.list_id)?.checklist;  // 2.7.2 (#414): lists with "Show completed at the bottom"
  const cand = all.filter(t => !isCk(t));
  const pick = days => { const c = days ? new Date(Date.now() - days * 864e5).toISOString() : null; return cand.filter(t => !c || (t.completed_at || '') < c); };
  // 2.272.0 B (#3045): only my own ones (created by me, without a creator or assigned to me); the other members' ones only
  // when I chose them and manage their project (owner / admin), else they stay
  const own = t => !t.created_by || t.created_by === S.me.id || t.assignee_id === S.me.id || (l => !!l && !l.shared && !l.org_id)(listById(t.list_id));  // a project shared with nobody: all mine
  let age = 0, oth = false;
  const editable = arr => arr.filter(t => canEdit(t)), ro = arr => arr.length - editable(arr).length;
  const may = arr => editable(arr).filter(t => own(t) || (oth && canManage(listById(t.list_id))));
  const who = arr => { const e = editable(arr), n = e.filter(own).length; return e.length > n ? tr('{0} of your own, {1} of other members', n, e.length - n) : ''; };
  const othOk = cand.some(t => !own(t) && canEdit(t) && canManage(listById(t.list_id)));
  const opts = [[0, tr('All')], [30, tr('Completed more than 30 days ago')], [90, tr('Completed more than 90 days ago')]];
  const okLabel = () => trn('Move {0} task to the trash', 'Move {0} tasks to the trash', may(pick(age)).length);
  const html = `<div class="dcopts" role="radiogroup">${opts.map(([d, n]) => `<label class="chkl"><input type="radio" name="dc-age" value="${d}" ${d === age ? 'checked' : ''}> ${esc(n)} <span class="muted" data-dcn="${d}">(${may(pick(d)).length})</span></label>`).join('')}</div>
    <p class="muted" id="dc-who">${esc(who(pick(age)))}</p>${othOk ? `<label class="chkl"><input type="checkbox" id="dc-oth"> ${esc(tr('Also delete the tasks of other members'))}</label>` : cand.some(t => !own(t) && canEdit(t)) ? `<p class="muted">${esc(tr('Tasks of other members stay.'))}</p>` : ''}
    <p class="muted" id="dc-note">${[tr('They can be restored from the trash.'), ro(pick(age)) ? trn('{0} task in a project you may only view stays.', '{0} tasks in projects you may only view stay.', ro(pick(age))) : '', all.length > cand.length ? tr('Items of projects that show completed tasks at the bottom stay.') : ''].filter(Boolean).map(esc).join(' ')}</p>`;
  const onCh = e => {
    if (e.target.id === 'dc-oth') oth = e.target.checked;  // 2.272.0 B (#3045)
    else if (e.target.name !== 'dc-age') return;
    else age = +e.target.value;
    const w = $('#dc-who'); if (w) w.textContent = who(pick(age));
    for (const x of document.querySelectorAll('.cdlg [data-dcn]')) x.textContent = `(${may(pick(+x.dataset.dcn)).length})`;
    const yes = $('.cdlg [data-cd="yes"]'); if (yes) { yes.textContent = okLabel(); yes.disabled = !may(pick(age)).length; }
  };
  document.addEventListener('change', onCh);
  const pr = askConfirm(tr('Delete completed tasks'), '', {html, ok: okLabel(), danger: true});
  setTimeout(() => { const yes = $('.cdlg [data-cd="yes"]'); if (yes) yes.disabled = !may(pick(age)).length; }, 0);
  const ok = await pr;
  document.removeEventListener('change', onCh);
  const sel = may(pick(age)), skipped = ro(pick(age));
  if (!ok || !sel.length) return;
  const ids = sel.map(t => t.id), snaps = sel.map(snapTask);
  let j;
  try { j = await api('POST', '/api/tasks/batch', {ids, action: 'delete', data: {guard: Object.fromEntries(sel.filter(t => t.updated_at).map(t => [t.id, t.updated_at])), own_only: !oth}}); } catch { return; }  // 2.272.0 B (#3045), F: own_only (review M7)
  await load(); render();
  const n = ids.length - (j.errors?.length || 0) - (j.conflicts?.length || 0) - (j.skipped?.length || 0);
  const kept = skipped + (j.errors?.length || 0) + (j.conflicts?.length || 0) + (j.skipped?.length || 0);
  const msg = trn('{0} completed task moved to the trash', '{0} completed tasks moved to the trash', n) + (kept ? ' · ' + trn('{0} task skipped', '{0} tasks skipped', kept) : '');
  offerUndo(msg, histTrash(trn('Deleted {0} completed task', 'Deleted {0} completed tasks', n), ids, snaps, j));
}
// 'Uncheck all' / 'Clear done' of a checklist (events.js ck-uncheck / ck-clear; 2.272.0 G #3038: moved here from events.js)
async function ck_clearAct(act, id) {
  let dn = [...S.tasks.values()].filter(t => t.list_id === id && t.status !== 0 && !t.parent_id).map(t => t.id), r, oth = false;
  if (act === 'ck-clear') {  // 2.272.0 E2 (#3038): only my own done items; the other members' ones only on the owner's / an admin's choice
    let d; try { d = await api('POST', `/api/lists/${id}/checklist`, {action: 'clear_done', dry: true}); } catch { return; }
    if (d?.others && d.may_others && !await askConfirm(tr('Delete completed tasks'), '', {ok: tr('Move to the trash'), danger: true, html: `<p class="muted">${esc(tr('{0} of your own, {1} of other members', d.own, d.others))}</p><label class="chkl"><input type="checkbox" id="ck-oth"> ${esc(tr('Also delete the tasks of other members'))}</label>`,
      after: md => md.addEventListener('change', e => { if (e.target.id === 'ck-oth') oth = e.target.checked; })})) return;
  }
  try { r = await api('POST', `/api/lists/${id}/checklist`, {action: act === 'ck-clear' ? 'clear_done' : 'uncheck_all', ...(oth ? {others: true} : {})}); } catch { return; }
  if (act === 'ck-clear' && Array.isArray(r?.ids)) { const set = new Set(r.ids); dn = dn.filter(x => set.has(x)); }
  const snaps = dn.flatMap(withKids);
  await load(); render();
  if (act === 'ck-clear' && r?.kept && !dn.length) { toast(tr('Tasks of other members stay.')); return; }
  if (act === 'ck-clear' && dn.length) offerUndo(tr('Done items moved to the trash'), histTrash(trn('{0} done item moved to the trash', '{0} done items moved to the trash', dn.length), dn, snaps, r));
  else toast(act === 'ck-clear' ? tr('Done items moved to the trash') : tr('Everything is back on the list'));
}
