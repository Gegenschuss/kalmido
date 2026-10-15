/* Kalmido web client: 2.46.0 (#1603) who sees an organisation list -- "Only invited people" / "Everyone in the organisation".
   The list dialog's row (owner / list admins change it), the "Join" bar in a list seen only that way (org_reader) and the
   quiet sidebar mark. Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

// a list that can open itself to its organisation: of an organisation, not the basket, not Home & life / "Used for"
const ovOk = l => !!l && !!l.org_id && !l.is_inbox && !l.family && !l.life && collab();
// tasks of a list seen only through the organisation stay out of the smart lists (Today, All, ...) until one joins
const ovHidden = t => { const l = t && listById(t.list_id); return !!l?.org_reader && !(S.route.mod === 'tasks' && S.route.key === 'l:' + l.id); };

function ovRowHtml(l) {
  if (!ovOk(l)) return '';
  const mng = canManage(l), on = l.org_visibility === 'org', dis = mng ? '' : 'disabled';
  return `<div class="row ovrow"><label for="l-ovis">${tr('Visibility')}</label><select id="l-ovis" ${dis}>
      <option value="" ${on ? '' : 'selected'}>${tr('Only invited people')}</option>
      <option value="org" ${on ? 'selected' : ''}>${tr('Everyone in the organisation')}</option></select></div>
    <div class="row ovedit" ${on ? '' : 'hidden'}><span></span><label class="chkl"><input type="checkbox" id="l-ovedit" ${l.org_edit ? 'checked' : ''} ${dis}> ${tr('Members of the organisation may edit')}</label></div>
    <div class="shint lhint" id="l-ovhint">${ovHint(on, !!l.org_edit)}</div>`;
}
const ovHint = (on, ed) => !on ? tr('Only the people you share the list with see it.')
  : ed ? tr('Every member of the organisation sees and edits this list without an invitation. Notifications only for those who join.')
  : tr('Every member of the organisation sees this list read-only and can join it. Notifications only for those who join.');

function ovWire(md, id) {
  const sel = $('#l-ovis', md), chk = $('#l-ovedit', md);
  const sync = () => { const l = listById(id); if (!l || !md.isConnected) return; const on = l.org_visibility === 'org';
    if (sel) sel.value = on ? 'org' : ''; if (chk) chk.checked = !!l.org_edit;
    const r = $('.ovedit', md); if (r) r.hidden = !on; const h = $('#l-ovhint', md); if (h) h.textContent = ovHint(on, !!l.org_edit); };
  sel?.addEventListener('change', e => { e.stopPropagation(); ovSet(id, {org_visibility: sel.value}).then(sync); });
  chk?.addEventListener('change', e => { e.stopPropagation(); ovSet(id, {org_edit: chk.checked ? 1 : 0}).then(sync); });
}

// one change, one undo step (like dsxSet)
async function ovSet(id, body) {
  const l = listById(id); if (!l) return;
  const was = {};
  for (const k of Object.keys(body)) was[k] = k === 'org_edit' ? (l.org_edit ? 1 : 0) : (l[k] || '');
  try { await optWrite(optSet(() => listById(id), body), () => api('PATCH', '/api/lists/' + id, body)); } catch { return; }
  const msg = 'org_visibility' in body ? (body.org_visibility === 'org' ? tr('Visible to everyone in the organisation') : tr('Visible only to invited people'))
    : body.org_edit ? tr('Members of the organisation may edit') : tr('Members of the organisation may only read');
  offerUndo(msg, histAdd({label: tr('Visibility'),
    undo: async () => { await api('PATCH', '/api/lists/' + id, was); await load(); render(); return {skipped: []}; },
    redo: async () => { await api('PATCH', '/api/lists/' + id, body); await load(); render(); return {skipped: []}; }}));
}

// the bar above a list seen only through the organisation (instead of "View only")
function ovJoinBar(l) {
  const txt = l.role === 'edit' ? tr('Visible to everyone in the organisation. Join to get its notifications.')
    : tr('Visible to everyone in the organisation, read-only. Join to work in it.');
  return `<div class="rohint ovbar">${ic('eye', 's')}<span>${esc(txt)}</span><button type="button" class="btn sm pri" data-ovjoin="${l.id}">${ic('plus', 's')} ${tr('Join')}</button></div>`;
}
const ovSideMark = l => l.org_reader ? `<span class="shr ovmark" title="${esc(tr('Not joined'))}" aria-label="${esc(tr('Not joined'))}">${ic('eye', 's')}</span>` : '';

async function ovJoin(id) {
  const l = listById(id); if (!l || !S.me) return;
  try { await api('POST', `/api/lists/${id}/join`); } catch { return; }
  await load(); render();
  offerUndo(tr('You joined “{0}”', lname(l)), histAdd({label: tr('Join'),
    undo: async () => { await api('DELETE', `/api/lists/${id}/members/${S.me.id}`); await load(); render(); return {skipped: []}; },
    redo: async () => { await api('POST', `/api/lists/${id}/join`); await load(); render(); return {skipped: []}; }}));
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-ovjoin]'); if (!b) return;
  e.preventDefault(); e.stopPropagation(); b.disabled = true; ovJoin(+b.dataset.ovjoin).finally(() => { b.disabled = false; });
});
