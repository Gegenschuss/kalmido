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
  const arch = l.archived ? {label: tr('Restore project from the archive'), icon: 'undo', danger: 1, fn: () => listArchive(id, false)}
    : {label: tr('Archive project'), icon: 'archive', danger: 1, fn: () => listArchive(id, true)};
  const del = {label: l.archived && l.e2e ? tr('Delete project permanently…') : tr('Delete project…') /* 2.102.0 (#1988): plain lists go to the trash */, icon: 'trash', cls: 'flag-5', danger: 1, fn: () => listDeleteForGood(id)};
  return ['-', arch, ...(mine || l.archived ? [del] : [])];  // an organisation admin deletes from the archive only (as in #1101)
}
// the delete dialog: who loses the list, where the tasks go when I am not the owner
function lmDeleteNotes(l, n, open) {
  const others = listPeople(l).filter(p => p.user_id !== S.me?.id && !p.agent && !agentById(p.user_id)).length;
  // 2.102.0 A (#1988): the tasks stay in the list (list trash), so only "the owner is told" is left here
  const tasks = isOwner(l) ? '' : `<p class="muted">${esc(tr('{0} is told.', l.owner_name || '?'))}</p>`;
  return tasks + (others ? `<p class="shint keep lmshared">${ic('users', 's')} ${esc(trn('The project is shared: {0} other person loses it.', 'The project is shared: all {0} other people lose it.', others))}</p>` : '');
}
// an organisation admin (not owner / list admin): archive, restore, delete for good through /api/orgs/{id}/lists
async function lmOrgAct(l, k) {
  const base = `/api/orgs/${l.org_id}/lists/${l.id}`, nm = lname(l);
  try {
    if (k === 'archive') {
      if (!await askConfirm(tr('Archive “{0}”?', nm), tr('The project leaves the sidebar of everyone in it; nothing is deleted. {0} and the members are told. You or the owner can restore it.', l.owner_name || '?'), {ok: tr('Archive project')})) return false;
      await api('POST', base + '/archive', {archived: true}); toast(tr('Archived'));
      if (S.route.key === 'l:' + l.id) go(START_KEY);
    } else if (k === 'restore') { await api('POST', base + '/archive', {archived: false}); toast(tr('Restored')); }
    else if (k === 'delete') {
      const v = await askDialog({title: l.e2e ? tr('Delete “{0}” permanently?', nm) : tr('Delete “{0}”?', nm), danger: true, ok: l.e2e ? tr('Delete permanently') : tr('Delete'),
        html: `<p>${esc(l.e2e ? tr('This cannot be undone. Its tasks go to the trash in the basket of {0} and can be restored from there; its files and the sharing are lost. {0} and the members are told.', l.owner_name || '?') : otr_orgNote(l.owner_name || '?'))}</p>${lmDeleteNotes({...l, owner_name: l.owner_name, role: 'owner'}, 0, 0)}<p>${esc(tr('Type the name of the project to delete it'))}</p>`,
        input: {placeholder: l.name, max: 200}});  // 2.102.0 A (#1988): into the organisation's list trash (end-to-end lists: for good)
      if (v === null) return false;
      if (v.trim() !== l.name.trim()) { toast(tr('The name does not match: nothing was deleted')); return false; }
      const j = await api('DELETE', base, {confirm: v.trim()});
      if (S.route.key === 'l:' + l.id) go(START_KEY);
      if (j?.trash) otr_offerUndo(l.id, nm); else toast(tr('“{0}” deleted', nm));
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
    html: `<p>${esc(tr('The folder has defaults that change this project:'))}</p><ul class="cdlg-l lmmove">${li}</ul><p class="muted">${esc(tr('Moving into a workspace changes who can be in the project; members and agents outside it may lose access. Cancel leaves the project where it is.'))}</p>`});
  return ok ? ask.map(x => x.l.id) : null;
}
// ---- Settings > Organisation (only for people in an organisation): members and roles, "Lists of the organisation" and the
// history (organisation admins). The old place (Account > Workspaces) links here.
const lmOrgPaneOn = () => typeof wsPaneOn === 'function' && wsPaneOn() && (S.me?.workspaces || []).length > 0;
function lmOrgLinkHtml() {
  return `<h4 id="s-ws-h">${tr('Workspaces')}</h4><div class="row"><span class="muted">${esc(tr('Members, roles and the projects of your organisation are now under Settings > Organisation.'))}</span><button type="button" class="btn sm" data-lmorg="1">${ic('building', 's')} ${tr('Organisation')}</button></div>`;
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
  return groups.map(g => `<div class="lmoown"><h4 class="lmoh">${av(g[0].owner_id, g[0].owner_name)} ${esc(g[0].owner_name || '?')}${g[0].owner_agent ? ' ' + agentBadge() : ''} <span class="muted">${esc(trn('{0} project', '{0} projects', g.length))}</span></h4>${g.map(row).join('')}</div>`).join('');
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
// 2.46.1 (#1422): an own choice on my list in a folder with "Hide completed" differs from the folder (the server marks
// folder_own the same way): the list dialog then says "This list differs" with "Back to the folder"
function lc_doneOwnSync(key) {
  const m = /^l:(\d+)$/.exec(key || ''), l = m && listById(+m[1]);
  if (!l || !isOwner(l) || !l.folder || typeof folderEff !== 'function') return;
  const e = folderEff(l.folder); if (!('hide_done' in e)) return;
  let own = []; try { own = JSON.parse(l.folder_own || '[]'); } catch { /* none */ }
  const v = doneViews()[key];
  own = own.filter(k => k !== 'hide_done');
  if (v !== undefined && !!+v === !!e.hide_done) own.push('hide_done');
  l.folder_own = JSON.stringify(own.sort());
}
function lmDoneResetItems(key = S.route.key) {
  if (!lmDoneOwn(key)) return [];
  return [{label: tr('Completed: like the default ({0})', lmDoneDefault(key) ? tr('shown') : tr('hidden')), icon: 'undo', cls: 'mdonedef', fn: () => lmDoneReset(key)}];
}
async function lmDoneReset(key) {
  const was = doneViews()[key];
  const put = async v => {
    const o = doneViews(); if (v === undefined) delete o[key]; else o[key] = v;
    S.settings.show_done_views = JSON.stringify(o); lc_doneOwnSync(key); render();
    try { await api('PATCH', '/api/settings', {show_done_views: S.settings.show_done_views}); } catch { try { await load(); } catch { /* offline */ } render(); }
    return {skipped: []};
  };
  await put(undefined);
  offerUndo(tr('Completed tasks follow the default here'), histAdd({label: `${tr('Completed: like the default')}: ${titleFor(key)}`, sett: true, undo: () => put(was), redo: () => put(undefined)}));
}

// ---- 2.102.0 A (#1988): the trash of deleted lists (lists/listtrash.py). Deleting an archived list moves it with its tasks,
// fields, tags and chat into the trash of its place (private: the owner's; an organisation's list: the organisation's, for
// its admins); "Deleted lists" on the Trash page restores it or deletes it for good; the undo right after the delete restores.
S.otr = {items: null, at: 0, days: 30};
const otr_orgNote = owner => owner ? tr('The project goes to the organisation’s trash with its tasks, fields and chat; the organisation’s admins can restore it there. {0} and the members are told.', owner)
  : tr('The project goes to the organisation’s trash with its tasks, fields and chat; the organisation’s admins can restore it there.');
const otr_note = l => l.org_id ? otr_orgNote('') : tr('The project goes to the trash with its tasks, fields, tags and chat. It can be restored there for {0} days, then it is deleted for good.', S.otr.days || 30);
async function otr_load(force) {
  if (!force && S.otr.at && Date.now() - S.otr.at < 30000) return;
  S.otr.at = Date.now();
  try { const j = await api('GET', '/api/trash/lists'); S.otr.items = j.lists || []; S.otr.days = j.days || 30; } catch { S.otr.items = S.otr.items || []; return; }
  if (S.route.key === 'trash') renderView();
}
// 2.119.1 C (#2304): `active` = the list was not archived before the delete (archived first by it): the undo brings it back
// active (folder and position stay with the row), the redo archives it again first; restoring from the trash page stays archive
function otr_offerUndo(id, nm, active = false) {
  S.otr.at = 0;
  offerUndo(tr('“{0}” moved to the trash', nm), histAdd({label: tr('Delete “{0}”', nm),
    undo: async () => { await api('POST', `/api/trash/lists/${id}/restore`); if (active) await api('PATCH', '/api/lists/' + id, {archived: 0}); S.otr.at = 0; return {}; },
    redo: async () => { if (active) await api('PATCH', '/api/lists/' + id, {archived: 1}); await api('DELETE', '/api/lists/' + id); S.otr.at = 0; return {}; }}));
}
function otr_html() {
  otr_load();
  const xs = (S.otr.items || []).filter(x => wsObjIn({org_id: x.org_id}));
  if (!xs.length) return '';
  return `<div class="group otrlists"><div class="ghead">${esc(tr('Deleted projects'))} <span class="c">${xs.length}</span></div>`
    + xs.map(x => `<div class="mrow otrrow" data-otr="${x.id}"><span class="n"><b>${esc(x.name)}</b><small class="muted">${esc([tr('Deleted {0} by {1}', fmtWhen(x.deleted_at), x.by_name || '?'), trn('{0} task', '{0} tasks', x.tasks), x.org_id && wsLabel(x.org_id), x.retain_until && tr('Receipts kept until {0}', fmtDate(x.retain_until))].filter(Boolean).join(' · '))}</small></span>`
      // 2.186.1 (#2732): a kept project of a deleted account (x.held: I am its custodian) -- download it, delete it before the end
      + `<span class="oadmb">${x.held ? `<a class="btn sm" href="/api/trash/lists/${+x.id}/export.zip" download>${ic('download', 's')}<span>${tr('Download')}</span></a>` : ''}<button type="button" class="btn sm" data-otra="restore">${ic('undo', 's')}<span>${tr('Restore')}</span></button><button type="button" class="btn sm danger" data-otra="purge">${ic('trash', 's')}<span>${tr('Delete permanently…')}</span></button></span></div>`).join('')
    + `<div class="muted otrnote">${esc(tr('Projects in the trash are deleted for good after {0} days.', S.otr.days))}</div></div>`;
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-otra]'); if (!b) return;
  const row = b.closest('[data-otr]'), id = +row?.dataset.otr, x = (S.otr.items || []).find(y => y.id === id); if (!x) return;
  e.preventDefault();
  try {
    if (b.dataset.otra === 'restore') {
      await api('POST', `/api/trash/lists/${id}/restore`);
      toast(tr('“{0}” is back in the archive', x.name));
    } else if (x.held) {  // 2.186.1 (#2732): before the end of the retention period -- type the name, like deleting an account
      const nm = await askPrompt(tr('Delete “{0}” permanently?', x.name), '', {danger: true, ok: tr('Delete permanently'),
        body: tr('The receipts of this project are kept by law until {0}. The duty to keep them lay with the person whose account was deleted; you may delete the project before that. Download it first if it should be kept. The project, its receipts, files and bookings are deleted for good, and the deletion is noted in the security log. Type the project name to confirm.', fmtDate(x.retain_until)),
        input: {placeholder: x.name}});
      if (nm == null) return;
      await api('DELETE', `/api/trash/lists/${id}?confirm=${encodeURIComponent(nm)}`);
      toast(tr('“{0}” deleted', x.name));
    } else {
      if (!await askConfirm(tr('Delete “{0}” permanently?', x.name), tr('The project, its tasks, comments, files, fields and chat are deleted for good. This cannot be undone.'), {danger: true, ok: tr('Delete permanently')})) return;
      await api('DELETE', `/api/trash/lists/${id}`);
      toast(tr('“{0}” deleted', x.name));
    }
  } catch { return; }  // api() said why
  S.otr.at = 0;
  await load(); render();
});
