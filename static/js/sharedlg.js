// 2.1156.0 (#4280): the Share dialog of a folder (folderShareModal: people, groups, agents, notifications) moved to foldershare.js (loaded on demand, static/js/lazyload.js)
// ---- 2.46.0 (#1605): a group's picture (S.groups[].avatar: a preset SVG, an own photo, '' = the group symbol). fg_gav = the
// round picture of a group wherever groups stand (share dialogs, group admin, a task assigned to a group).
const fg_gUrl = gid => (S.groups || []).find(x => x.id === +gid)?.avatar || '';
const fg_gav = (gid, cls = 'avatar gav') => { const u = fg_gUrl(gid); return `<span class="${cls}${u ? ' pic' : ''}">${u ? `<img src="${esc(u)}" alt="" loading="lazy" decoding="async" draggable="false">` : ic('users', 's')}</span>`; };
const fg_gico = gid => { const u = fg_gUrl(gid); return u ? `<img class="fggimg" src="${esc(u)}" alt="" loading="lazy" decoding="async" draggable="false">` : ic('users', 's'); };
// the picker of the group dialog: presets, an own photo, none; the choice is saved with the group (Save / Create)
function fg_pickHtml(cur) {
  const up = cur.startsWith('/api/group-avatar/');
  return [...AV_PRESETS, ...AV_BOTS].map(([k]) => `<button type="button" class="avopt ${cur === `/static/avatars/${k}.svg` ? 'on' : ''}" data-fgav="${k}" title="${esc(avTitle(k))}" aria-label="${esc(avTitle(k))}" aria-pressed="${cur === `/static/avatars/${k}.svg`}"><img src="/static/avatars/${k}.svg" alt=""></button>`).join('')
    + `<input type="file" id="gr-avfile" accept="image/jpeg,image/png,image/webp,image/gif" hidden><button type="button" class="avopt up ${up ? 'on' : ''}" data-fgav="upload" title="${esc(tr('Upload a photo…'))}" aria-label="${esc(tr('Upload a photo…'))}" aria-pressed="${up}">${up ? `<img src="${esc(cur)}" alt="">` : ic('plus')}</button>`
    + `<button type="button" class="avopt none ${cur ? '' : 'on'}" data-fgav="none" title="${esc(tr('No picture (group symbol)'))}" aria-label="${esc(tr('No picture (group symbol)'))}" aria-pressed="${!cur}">${ic('users', 's')}</button>`;
}
const fg_pickRow = g => `<div class="row avrow"><label>${tr('Picture')}</label><div class="avpick" id="gr-avpick">${fg_pickHtml(g?.avatar || '')}</div></div>`;
function fg_pickWire(md, g) {  // -> () => the pending choice: null (unchanged) | {preset} | {none: true} | {blob, url}
  let pend = null;
  const box = $('#gr-avpick', md); if (!box) return () => null;
  const show = cur => { box.innerHTML = fg_pickHtml(cur); };
  box.addEventListener('click', e => {
    const b = e.target.closest('[data-fgav]'); if (!b) return;
    const k = b.dataset.fgav;
    if (k === 'none') { pend = {none: true}; show(''); return; }
    if (k !== 'upload') { pend = {preset: k}; show(`/static/avatars/${k}.svg`); return; }
    $('#gr-avfile', box)?.click();  // 2.633.0 (#4920): fixed hidden file input, its change uploads (a drop onto the window too, dropany.js)
  });
  box.addEventListener('change', async e => {
    const t = e.target; if (t.id !== 'gr-avfile' || !t.files?.length) return;
    const f = t.files[0]; t.value = '';
    if (f.size > 8 * 1024 * 1024) { toast(tr('The picture is too large (at most {0} MB)', 8)); return; }
    const bl = await avCropModal(f); if (!bl || !md.isConnected) return;
    if (pend?.url) URL.revokeObjectURL(pend.url);
    pend = {blob: bl, url: URL.createObjectURL(bl)};
    box.innerHTML = fg_pickHtml('/api/group-avatar/new');
    const im = $('[data-fgav="upload"] img', box); if (im) im.src = pend.url;
  });
  onRemove(md, () => { if (pend?.url) URL.revokeObjectURL(pend.url); });
  return () => pend;
}
async function fg_pickSave(gid, pend) {  // after Save / Create; a failed picture keeps the group (api() says why)
  if (!pend || !gid) return;
  try {
    if (pend.none) await api('DELETE', `/api/admin/groups/${gid}/avatar`);
    else if (pend.preset) await api('PUT', `/api/admin/groups/${gid}/avatar`, {preset: pend.preset});
    else if (pend.blob) { const fd = new FormData(); fd.append('file', pend.blob, 'avatar.jpg'); await api('POST', `/api/admin/groups/${gid}/avatar`, fd); }
  } catch { /* api() said it */ }
}
// the old entry points stay (notification question, older links): they open the one dialog
function folderPeopleModal(f, opt = {}) { return folderShareModal(f, opt); }
// ---- 2.41.0 (#1428): a folder shows whether it is shared, with the symbols of a list (licShareHtml: people grey, the robot
// blue): my folder shared itself (people, groups, agents; a subfolder also by its top folder) -- "New lists here are shared
// with …"; a folder someone shared with me; a weaker sign when only lists inside are shared. Shown folded too.
function folderShareOf(f) {  // -> {people, groups, agents: [names]} or null
  if (!f) return null;
  const all = S.folderShares || {}, own = all[f], top = fParent(f) ? all[fParent(f)] : null;
  const people = (own?.people || 0) + (top?.people || 0), groups = (own?.groups || 0) + (top?.groups || 0);
  const agents = (own?.agents || []).length ? own.agents : top?.agents || [];
  return people || groups || agents.length ? {people, groups, agents} : null;
}
function folderShareTxt(sh) {  // "3 people, 1 group", "agent Claude" -> [persons part, agents part]
  const pp = [sh.people ? trn('{0} person', '{0} people', sh.people) : '', sh.groups ? trn('{0} group', '{0} groups', sh.groups) : ''].filter(Boolean).join(', ');
  const ap = sh.agents.length ? trn('agent {1}', 'agents {1}', sh.agents.length, sh.agents.join(', ')) : '';
  return [pp, ap];
}
function folderShareSay(sh, one, two) { const [pp, ap] = folderShareTxt(sh); return pp && ap ? tr(two, pp, ap) : tr(one, pp || ap); }
function folderShrHtml(f) {
  const sh = folderShareOf(f), si = !sh && folderSharedIn(f);
  if (sh || si) {
    const tip = sh ? folderShareSay(sh, N_('New projects here are shared with {0}'), N_('New projects here are shared with {0} and {1}')) : tr('Shared by {0}', si.owner_name);
    return sbc_slots('shr shk fshr', tip, sh?.agents.length ? licBot() : '', !sh || sh.people || sh.groups ? ic('users', 's') : '');  // 2.56.0 (#1797): fixed columns
  }
  const ls = (S.lists || []).filter(l => !l.archived && !l.is_inbox && fUnder(l.folder, f) && l.shared);
  if (!ls.length || !collab()) return sbc_ph();  // 2.56.0 (#1797)
  const tip = trn('{0} project in here is shared; new projects stay private', '{0} projects in here are shared; new projects stay private', ls.length);
  return sbc_slots('shr shk fshr fshweak', tip, ls.some(l => (l.shared_agents || []).length) ? licBot() : '', ic('users', 's'));
}
// moved / dragged one of my lists into a shared folder: say so (the caller offers Undo)
function folderNowShared(id, f) {
  const l = listById(id), sh = f && folderShareOf(f);
  return l && sh && isOwner(l) ? folderShareSay(sh, N_('Now shared with {0}'), N_('Now shared with {0} and {1}')) : '';
}
