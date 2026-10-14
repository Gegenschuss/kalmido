// ---- 2.39.1 (#1188 / #1214): managing lists.
// Who archives and deletes a list: its owner and its list admins (the owner hears about it, the tasks go to the trash of the
// owner's basket), an organisation admin through the organisation's functions (same rules as "Lists of the organisation":
// archive first, delete with the name typed). A list moved into a folder with defaults takes the folder's workspace / agent
// only after a confirmation (both directions). Settings > Organisation. "Hide completed": the view's own choice, else the
// nearest folder default, else the person's default.
const lmOrgAdmin = l => !!l && !l.is_inbox && !!l.org_id && (S.me?.workspaces || []).some(o => o.id === l.org_id && o.role === 'admin');
const lmOrgName = oid => (S.me?.workspaces || []).find(o => o.id === oid)?.name || '';
// the last part of a list menu: what cannot simply be taken back (listMenuSort puts danger: 1 last)
function lmDangerItems(l, id) {
  if (!l || l.is_inbox) return [];
  const mine = canManage(l), org = !mine && lmOrgAdmin(l);
  if (!mine && !org) return [];
  const arch = l.archived ? {label: tr('Restore list from the archive'), icon: 'undo', danger: 1, fn: () => listArchive(id, false)}
    : {label: tr('Archive list'), icon: 'archive', danger: 1, fn: () => listArchive(id, true)};
  const del = {label: l.archived ? tr('Delete list permanently…') : tr('Delete list…'), icon: 'trash', cls: 'flag-5', danger: 1, fn: () => listDeleteForGood(id)};
  return ['-', arch, ...(mine || l.archived ? [del] : [])];  // an organisation admin deletes from the archive only (as in #1101)
}
// the delete dialog: who loses the list, where the tasks go when I am not the owner
function lmDeleteNotes(l, n, open) {
  const others = listPeople(l).filter(p => p.user_id !== S.me?.id && !p.agent && !agentById(p.user_id)).length;
  const tasks = isOwner(l) ? '' : `<p class="muted">${n ? trn('Its {0} task goes to the trash of the basket of {2} ({1} open), the owner, and can be restored there.', 'Its {0} tasks go to the trash of the basket of {2} ({1} open), the owner, and can be restored there.', n, open, esc(l.owner_name || '?')) : tr('The list has no tasks.')} ${esc(tr('{0} is told.', l.owner_name || '?'))}</p>`;
  return tasks + (others ? `<p class="shint keep lmshared">${ic('users', 's')} ${esc(trn('The list is shared: {0} other person loses it.', 'The list is shared: all {0} other people lose it.', others))}</p>` : '');
}
// an organisation admin (not owner / list admin): archive, restore, delete for good through /api/orgs/{id}/lists
async function lmOrgAct(l, k) {
  const base = `/api/orgs/${l.org_id}/lists/${l.id}`, nm = lname(l);
  try {
    if (k === 'archive') {
      if (!await askConfirm(tr('Archive “{0}”?', nm), tr('The list leaves the sidebar of everyone in it; nothing is deleted. {0} and the members are told. You or the owner can restore it.', l.owner_name || '?'), {ok: tr('Archive list')})) return false;
      await api('POST', base + '/archive', {archived: true}); toast(tr('Archived'));
      if (S.route.key === 'l:' + l.id) go(START_KEY);
    } else if (k === 'restore') { await api('POST', base + '/archive', {archived: false}); toast(tr('Restored')); }
    else if (k === 'delete') {
      const v = await askDialog({title: tr('Delete “{0}” permanently?', nm), danger: true, ok: tr('Delete permanently'),
        html: `<p>${esc(tr('This cannot be undone. Its tasks go to the trash in the basket of {0} and can be restored from there; its files and the sharing are lost. {0} and the members are told.', l.owner_name || '?'))}</p>${lmDeleteNotes({...l, owner_name: l.owner_name, role: 'owner'}, 0, 0)}<p>${esc(tr('Type the name of the list to delete it for good'))}</p>`,
        input: {placeholder: l.name, max: 200}});
      if (v === null) return false;
      if (v.trim() !== l.name.trim()) { toast(tr('The name does not match: nothing was deleted')); return false; }
      await api('DELETE', base, {confirm: v.trim()}); toast(tr('“{0}” deleted', nm));
      if (S.route.key === 'l:' + l.id) go(START_KEY);
    }
  } catch { return false; }  // api() said it
  await load(); render();
  return true;
}
// ---- moving lists into folders: before a list takes a folder's workspace / agent, ask (OK = take them, Cancel = no move).
// moves: {listId: folder}. -> null (cancelled) | [ids that take the folder's settings]
const LM_KEYS = {org_id: N_('Workspace'), agent_id: N_('Agent')};
function lmChangeTxt(x) {
  if (x.key === 'org_id') return `${tr('Workspace')}: ${x.from ? x.from_name || tr('Organisation') : tr('Private|workspace')} → ${x.to ? x.to_name || tr('Organisation') : tr('Private|workspace')}`;
  if (x.key === 'agent_id') return `${tr('Agent')}: ${x.from ? x.from_name || '?' : tr('No agent')} → ${x.to ? x.to_name || '?' : tr('No agent')}`;
  return null;
}
async function lmFolderAsk(moves) {
  const ask = [];
  for (const [id, f] of Object.entries(moves || {})) {
    const l = listById(+id); if (!l || l.is_inbox || !isOwner(l) || (l.folder || '') === (f || '')) continue;
    let j; try { j = await api('GET', `/api/lists/${l.id}/folder-preview?folder=${encodeURIComponent(f || '')}`); } catch { continue; }  // offline: moved without taking anything
    if (j.changes?.length) ask.push({l, f, ch: j.changes});
  }
  if (!ask.length) return [];
  const li = ask.map(({l, f, ch}) => {
    const named = ch.map(lmChangeTxt).filter(Boolean), more = ch.filter(x => !LM_KEYS[x.key]).length;
    return `<li><b>${esc(lname(l))}</b> → ${esc(fDisp(f))}<br>${named.map(esc).join('<br>')}${more ? `${named.length ? '<br>' : ''}${esc(trn('{0} more agent setting of the folder', '{0} more agent settings of the folder', more))}` : ''}</li>`;
  }).join('');
  const ok = await askConfirm(ask.length > 1 ? tr('Take the settings of the folder?') : tr('Take the settings of the folder “{0}”?', fDisp(ask[0].f)), '', {ok: tr('Move and take them'),
    html: `<p>${esc(tr('The folder has defaults that change this list:'))}</p><ul class="cdlg-l lmmove">${li}</ul><p class="muted">${esc(tr('Moving into a workspace changes who can be in the list; members and agents outside it may lose access. Cancel leaves the list where it is.'))}</p>`});
  return ok ? ask.map(x => x.l.id) : null;
}
// ---- Settings > Organisation (only for people in an organisation): members and roles, "Lists of the organisation" and the
// history (organisation admins). The old place (Account > Workspaces) links here.
const lmOrgPaneOn = () => typeof wsPaneOn === 'function' && wsPaneOn() && (S.me?.workspaces || []).length > 0;
function lmOrgLinkHtml() {
  return `<h4 id="s-ws-h">${tr('Workspaces')}</h4><div class="row"><span class="muted">${esc(tr('Members, roles and the lists of your organisation are now under Settings > Organisation.'))}</span><button type="button" class="btn sm" data-lmorg="1">${ic('building', 's')} ${tr('Organisation')}</button></div>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-lmorg]'); if (!b) return;
  $('.snav [data-sec="org"]', b.closest('.modal') || document)?.click();
});
// "Lists of the organisation": grouped by owner (the people first, then agents), the folder path of each list
function lmOadmBody(j, row) {
  const by = new Map();
  for (const x of j.lists) { if (!by.has(x.owner_id)) by.set(x.owner_id, []); by.get(x.owner_id).push(x); }
  const groups = [...by.values()].sort((a, b) => (a[0].owner_agent - b[0].owner_agent) || (a[0].owner_name || '').localeCompare(b[0].owner_name || ''));
  return groups.map(g => `<div class="lmoown"><h4 class="lmoh">${av(g[0].owner_id, g[0].owner_name)} ${esc(g[0].owner_name || '?')}${g[0].owner_agent ? ' ' + agentBadge() : ''} <span class="muted">${esc(trn('{0} list', '{0} lists', g.length))}</span></h4>${g.map(row).join('')}</div>`).join('');
}
// ---- #1214 "Hide completed": the view's own entry (show_done_views), else the nearest folder default, else the person's default
function lmDoneDefault(key) {
  const m = /^l:(\d+)$/.exec(key || '') || null, fm = /^folder:(.+)$/.exec(key || '') || null;
  let f = '';
  if (m) { const l = listById(+m[1]); f = l && isOwner(l) ? (l.folder || '') : ''; }  // 2.40.0 (#1422): only my own lists (shared lists of others keep theirs)
  else if (fm) f = fm[1];
  if (f && typeof folderEff === 'function') { const e = folderEff(f); if ('hide_done' in e) return !e.hide_done; }
  return S.settings?.show_done_default !== '0';
}
const lmDoneOwn = key => { try { return key in JSON.parse(S.settings.show_done_views || '{}'); } catch { return false; } };
function lmDoneResetItems(key = S.route.key) {
  if (!lmDoneOwn(key)) return [];
  return [{label: tr('Completed: like the default ({0})', lmDoneDefault(key) ? tr('shown') : tr('hidden')), icon: 'undo', cls: 'mdonedef', fn: () => lmDoneReset(key)}];
}
async function lmDoneReset(key) {
  const was = doneViews()[key];
  const put = async v => {
    const o = doneViews(); if (v === undefined) delete o[key]; else o[key] = v;
    S.settings.show_done_views = JSON.stringify(o); render();
    try { await api('PATCH', '/api/settings', {show_done_views: S.settings.show_done_views}); } catch { try { await load(); } catch { /* offline */ } render(); }
    return {skipped: []};
  };
  await put(undefined);
  offerUndo(tr('Completed tasks follow the default here'), histAdd({label: `${tr('Completed: like the default')}: ${titleFor(key)}`, sett: true, undo: () => put(was), redo: () => put(undefined)}));
}
