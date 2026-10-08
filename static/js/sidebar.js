/* Kalmido web client: Multi-select bar, filter lists and the list order in the sidebar.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ multi-select bar
// 2.3.0 (#262): the selection can go to an agent when it is only open main tasks of my inbox (at most 100)
function propInboxSel() {
  if (!propOn() || !S.multi.size || S.multi.size > 100) return false;
  const ib = S.lists.find(l => l.is_inbox && isOwner(l));
  return !!ib && [...S.multi].every(i => { const t = S.tasks.get(i); return t && t.list_id === ib.id && !t.parent_id && t.status === 0 && i > 0; });
}
function renderMultiBar() {
  let b = $('#mbar');
  if (!b) { b = document.createElement('div'); b.id = 'mbar'; document.body.appendChild(b); }
  const n = S.multi.size;
  b.classList.toggle('hidden', !(S.multiMode || n));
  document.body.classList.toggle('msel', !!(S.multiMode || n));  // 2.26.0: the docked quick add steps back while selecting
  $('#fab').classList.toggle('gone', fabOff() || S.multiMode || n > 0 || (!!$('#view .qdock') && (tabletDock() || !isMobile())));
  // 2.26.0 (#936): the selection is edited in the task panel (from two tasks: their common fields, see multiedit.js); the
  // bar keeps only what the panel does not have: the count, Complete, Delete and Clear selection. A phone opens the panel
  // as a sheet with "Edit"; with nothing selected yet (select mode) it offers "All".
  const mob = isMobile();
  const btn = ([act, i, lab, cls]) => `<button class="mbb ${cls || ''}" data-act="${act}" data-ico="${i}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic(i, 's')}<span class="mbl">${esc(lab)}</span></button>`;
  b.setAttribute('role', 'toolbar'); b.setAttribute('aria-label', tr('Selection'));
  b.innerHTML = `<span class="mcount" role="status">${n ? tr('{0} selected', n) : tr('Tap tasks')}</span>
    ${n ? '' : btn(['mb-all', 'all', tr('All')])}${n >= 2 && mob ? btn(['me-sheet', 'edit', tr('Edit'), 'pri']) : ''}
    ${n ? btn(['mb-done', 'done', tr('Complete')]) + btn(['mb-del', 'trash', tr('Delete'), 'danger']) : ''}
    <button class="iconbtn mbx" data-act="mb-close" title="${esc(tr('Clear selection') + ' (Esc)')}" aria-label="${esc(tr('Clear selection'))}">${ic('x')}</button>`;
  meSync();
}
async function batch(action, data, clear, ids = [...S.multi], note = '') {
  if (!ids.length) return;
  const snaps = ids.flatMap(withKids);
  const cs = action === 'complete' ? celeSnap(ids) : null;
  const j = await api('POST', '/api/tasks/batch', {ids, action, data});
  if (j.errors?.length) toast(j.errors[0]);
  if (clear) { S.multi.clear(); S.multiMode = false; }
  await load(); render();
  if (cs && !j.errors?.length) celeCheck(cs);
  if (j.errors?.length) return;
  const msg = (action === 'complete' ? trn('{0} task completed', '{0} tasks completed', ids.length) : action === 'delete' ? trn('{0} task deleted', '{0} tasks deleted', ids.length) : trn('{0} task changed', '{0} tasks changed', ids.length)) + (note ? ' · ' + note : '');
  const one = ids.length === 1 ? qn((snaps.find(x => x.id === ids[0])?.title || '').slice(0, 40)) : '';
  if (action === 'complete') offerUndo(msg, histDone(one ? tr('Completed {0}', one) : trn('Completed {0} task', 'Completed {0} tasks', ids.length), ids, snaps, j, data?.status ?? 2));
  else if (action === 'delete') offerUndo(msg, histTrash(one ? tr('Deleted {0}', one) : trn('Deleted {0} task', 'Deleted {0} tasks', ids.length), ids, snaps, j));
  else if (action === 'patch') {
    const pairs = snaps.filter(b => ids.includes(b.id)).map(b => [b, snapTask(S.tasks.get(b.id))]);
    const lab = data?.list_id ? trn('Moved {0} task to {1}', 'Moved {0} tasks to {1}', ids.length, lname(listById(data.list_id)) || '?')
      : data?.due !== undefined ? trn('Date of {0} task changed', 'Date of {0} tasks changed', ids.length) : data?.priority !== undefined ? trn('Priority of {0} task changed', 'Priority of {0} tasks changed', ids.length)
        : data?.add_tags ? trn('Tag added to {0} task', 'Tag added to {0} tasks', ids.length) : data?.pinned !== undefined ? trn('{0} task pinned', '{0} tasks pinned', ids.length) : trn('{0} task changed', '{0} tasks changed', ids.length);
    const e = histFields(lab, pairs, {res: j, fields: [...UNDO_FIELDS, 'tags']});
    if (e) offerUndo(msg, e); else toast(msg);
  } else toast(msg);
}
// 1.7.0: "n overdue -> Today / Tomorrow / Next week / Pick date…" on top of Today: moves every overdue task shown there
// that the user may change (view-only ones are skipped and counted), only the day (time, reminders, repeat stay, like
// the date popover), one batch request = one undo step. The x hides it until tomorrow (per device)
const overdueTasks = () => { const t0 = today(); return viewTasks().open.flatMap(function sub(t) { return [t, ...children(t.id).filter(k => k.status === 0).flatMap(sub)]; }).filter(t => t.due && t.due < t0); };
function overdueBanner() {
  if (LS.get('odHide', '') === today()) return '';
  const od = overdueTasks(); if (!od.length) return '';
  // 2.24.0 (UX-35): one slim line: "4 overdue · All to today · Another day…" (Tomorrow, Next week, Pick a date in its menu)
  return `<div class="odban" role="region" aria-label="${esc(tr('Overdue'))}">${ic('alert', 's')}<span class="odn">${esc(trn('{0} overdue', '{0} overdue', od.length))}</span>
    <button class="btn sm" data-act="od-move" data-d="0">${tr('All to today')}</button><button class="btn sm" data-act="od-other" aria-haspopup="menu">${tr('Another day…')}</button>
    <span class="spacer"></span><button class="iconbtn" data-act="od-hide" title="${esc(tr('Hide until tomorrow'))}" aria-label="${esc(tr('Hide until tomorrow'))}">${ic('x', 's')}</button></div>`;
}
async function overdueMove(due) {
  const od = overdueTasks(), may = od.filter(canEdit), ro = od.length - may.length;
  if (!may.length) { toast(trn('{0} overdue task is in a list you may only view', '{0} overdue tasks are in lists you may only view', ro)); return; }
  await batch('patch', {due}, false, may.map(t => t.id), ro ? trn('{0} task skipped (view only)', '{0} tasks skipped (view only)', ro) : '');
}
function overdueOther(a) {
  menu(a, [{label: tr('Tomorrow'), icon: 'sunrise', fn: () => overdueMove(addDays(today(), 1))}, {label: tr('Next week (Mon)'), icon: 'week', fn: () => overdueMove(nextWeekday(1))},
    {label: tr('Pick a date…'), icon: 'cal', fn: () => dpOpen(a, {kind: 'date', value: today(), min: today(), clear: false, label: tr('Pick a date…'), onPick: v => { if (v) overdueMove(v); }})}]);
}
function overdueAct(a) {
  const d = a.dataset.d;
  if (d === 'pick') { dpOpen(a, {kind: 'date', value: today(), min: today(), clear: false, label: tr('Pick a date…'), onPick: v => { if (v) overdueMove(v); }}); return; }
  overdueMove(d === 'w' ? nextWeekday(1) : addDays(today(), +d));
}
function multiDateMenu(a) {
  menu(a, [
    {label: tr('Today'), icon: 'sun', fn: () => batch('patch', {due: today()})},
    {label: tr('Tomorrow'), icon: 'sunrise', fn: () => batch('patch', {due: addDays(today(), 1)})},
    {label: tr('Next week (Mon)'), icon: 'week', fn: () => batch('patch', {due: nextWeekday(1)})},
    {label: tr('Pick a date…'), icon: 'cal', fn: () => {
      dpOpen(a, {kind: 'date', value: today(), clear: false, label: tr('Pick a date…'), onPick: v => { if (v) batch('patch', {due: v}); }});
    }},
    {label: tr('No date|clear'), icon: 'ban', fn: () => batch('patch', {due: null})},
  ]);
}

// ------------------------------------------------------------------ filter lists
function filterModal(id) {
  const f = id ? S.filters.find(x => x.id === id) : {name: '', rules: {}};
  if (!f) return;
  const r = {op: 'and', lists: [], dates: [], prios: [], types: [], tags: [], ...JSON.parse(JSON.stringify(f.rules || {}))};
  r.cf = r.cf && typeof r.cf === 'object' ? r.cf : {};
  // custom fields of the visible lists that the filter engine understands
  const cfs = (fieldsOn() ? S.fields || [] : []).filter(x => ['select', 'checkbox', 'date', 'number'].includes(x.type) && listById(x.list_id) && !listById(x.list_id).archived);
  const cfChips = (fd, kind, opts) => `<div class="fchips" data-cf="${fd.id}" data-cfk="${kind}">${opts.map(([v, n]) => `<button class="${(r.cf[fd.id]?.[kind] || []).includes(v) ? 'on' : ''}" data-v="${esc(v)}">${esc(n)}</button>`).join('')}</div>`;
  const cfRow = fd => {
    const cur = r.cf[fd.id] || {};
    const ctl = fd.type === 'select' ? cfChips(fd, 'sel', [...(fd.options?.options || []).map(o => [o.id, o.name]), ['', tr('empty')]])
      : fd.type === 'checkbox' ? cfChips(fd, 'chk', [['1', tr('checked')], ['0', tr('not checked')]])
      : fd.type === 'date' ? cfChips(fd, 'date', DATE_OPTS.map(([v, n]) => [v, tr(n)]))
      : `<div class="cfnumf"><select data-cfnum="${fd.id}"><option value="">–</option>${[['gt', '>'], ['lt', '<'], ['eq', '='], ['set', tr('has a value')], ['empty', tr('empty')]].map(([k, n]) => `<option value="${k}" ${cur.num?.op === k ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select><input data-cfnumv="${fd.id}" inputmode="decimal" value="${esc(cur.num?.v ?? '')}" style="max-width:6.875rem">${fd.options?.unit ? `<span class="muted">${esc(fd.options.unit)}</span>` : ''}</div>`;
    return `<div class="cfrow"><div class="cfn">${esc(lname(listById(fd.list_id)))} › <b>${esc(fd.name)}</b></div>${ctl}</div>`;
  };
  const tags = [...new Set([...S.tasks.values()].flatMap(t => t.tags))].sort((a, b) => a.localeCompare(b, 'de'));
  const chips = (key, opts, translate) => `<div class="fchips" data-key="${key}">${opts.map(([v, n]) => (translate ? [v, tr(n)] : [v, n])).map(([v, n]) => `<button class="${r[key].includes(v) ? 'on' : ''}" data-v="${esc(String(v))}">${esc(n)}</button>`).join('')}</div>`;
  const md = modal(`<h3>${id ? tr('Edit filter') : tr('New filter')}</h3>
    <div class="row"><label for="f-name">${tr('Name')}</label><input id="f-name" value="${esc(f.name)}" placeholder="${tr('e.g. Important this week')}"></div>
    <div class="row"><label>${tr('Match')}</label><div class="seg" id="f-op"><button data-op="and" class="${r.op !== 'or' ? 'on' : ''}">${tr('AND: all conditions')}</button><button data-op="or" class="${r.op === 'or' ? 'on' : ''}">${tr('OR: any one')}</button></div></div>
    <h4>${tr('Lists')}</h4>${chips('lists', S.lists.filter(l => !l.archived).map(l => [l.id, lname(l)]))}
    <h4>${tr('Date')}</h4>${chips('dates', DATE_OPTS, true)}
    <h4>${tr('Priority')}</h4>${chips('prios', [[5, N_('High')], [3, N_('Medium')], [1, N_('Low')], [0, N_('None')]], true)}
    ${ticketsAny() || r.types.length ? `<h4>${tr('Ticket type')}</h4>${chips('types', [...TTYPES.map(([k, n]) => [k, n]), ['', N_('No type')]], true)}` : ''}
    ${tags.length ? `<h4>${tr('Tags')}</h4>${chips('tags', tags.map(g => [g, '#' + g]))}` : ''}
    ${cfs.length ? `<h4>${tr('Custom fields')}</h4><div class="cffilters">${cfs.map(cfRow).join('')}</div>` : ''}
    <div class="muted" id="f-count" style="font-size:var(--fs-m);margin-top:.875rem"></div>
    <div class="foot">${id ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  const count = () => { const n = openTasks().filter(t => !t.parent_id && filterMatch(t, r)).length; $('#f-count', md).textContent = trn('Currently matches {0} open task. Within a category, “or” applies.', 'Currently matches {0} open tasks. Within a category, “or” applies.', n); };
  count();
  const numRule = fid => {
    const op = $(`[data-cfnum="${fid}"]`, md).value, v = numIn($(`[data-cfnumv="${fid}"]`, md).value.trim());
    if (op) r.cf[fid] = {num: {op, v}}; else delete r.cf[fid];
    count();
  };
  md.addEventListener('change', e => { if (e.target.dataset.cfnum) numRule(e.target.dataset.cfnum); });
  md.addEventListener('input', e => { if (e.target.dataset.cfnumv) numRule(e.target.dataset.cfnumv); });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    const cbox = b.closest('.fchips[data-cf]');
    if (cbox) {
      const fid = cbox.dataset.cf, k = cbox.dataset.cfk, v = b.dataset.v, cur = r.cf[fid] = r.cf[fid] || {};
      cur[k] = cur[k] || []; const i = cur[k].indexOf(v); i >= 0 ? cur[k].splice(i, 1) : cur[k].push(v);
      if (!cfRuleOn(cur)) delete r.cf[fid];
      b.classList.toggle('on', i < 0); count(); return;
    }
    const box = b.closest('.fchips');
    if (box) {
      const key = box.dataset.key, v = key === 'lists' || key === 'prios' ? +b.dataset.v : b.dataset.v;
      const i = r[key].indexOf(v); i >= 0 ? r[key].splice(i, 1) : r[key].push(v);
      b.classList.toggle('on', i < 0); count(); return;
    }
    if (b.dataset.op) { r.op = b.dataset.op; $$('#f-op button', md).forEach(x => x.classList.toggle('on', x === b)); count(); return; }
    const a = b.dataset.m;
    if (a === 'close') md.remove();
    if (a === 'save') {
      const name = $('#f-name', md).value.trim(); if (!name) return $('#f-name', md).focus();
      if (id) { await api('PATCH', '/api/filters/' + id, {name, rules: r}); md.remove(); await load(); render(); }
      else { const j = await api('POST', '/api/filters', {name, rules: r}); md.remove(); await load(); go('f/' + j.id); }
    }
    if (a === 'del' && await askConfirm(tr('Delete filter “{0}”?', f.name), tr('Tasks are kept.'), {ok: tr('Delete'), danger: true})) { await api('DELETE', '/api/filters/' + id); md.remove(); await load(); go('today'); }
  });
  if (!id) setTimeout(() => $('#f-name', md).focus(), 50);
}

// files from the desktop: drop on the open detail or on a task row; images from the clipboard
const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
document.addEventListener('dragover', e => {
  if (!hasFiles(e)) return;
  const tgt = e.target.closest('#detail, #view .trow');
  $$('.filedrop').forEach(x => x.classList.remove('filedrop'));
  if (!tgt || (tgt.id === 'detail' && !S.sel)) return;
  e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
  tgt.classList.add('filedrop');
});
document.addEventListener('dragleave', e => { if (hasFiles(e) && !e.relatedTarget) $$('.filedrop').forEach(x => x.classList.remove('filedrop')); });
document.addEventListener('drop', e => {
  if (!hasFiles(e)) return;
  $$('.filedrop').forEach(x => x.classList.remove('filedrop'));
  const tgt = e.target.closest('#detail, #view .trow');
  if (!tgt) return;
  e.preventDefault(); e.stopImmediatePropagation();
  if (e.target.closest('.ccomp')) { addCommentFiles(e.dataTransfer.files); return; }
  const id = tgt.id === 'detail' ? S.sel : +tgt.dataset.id;
  if (id) uploadFiles(id, e.dataTransfer.files);
}, true);
document.addEventListener('paste', e => {
  if (!S.sel || $('.modal') || !$('#detail').classList.contains('open') && !$('#app').classList.contains('detail-open')) return;
  if (['qinput', 'qsheet'].includes(document.activeElement?.id)) return;  // 2.22.0 (#678): the quick add box takes it itself
  const files = [...(e.clipboardData?.files || [])];
  if (!files.length) return;  // plain text paste stays normal
  e.preventDefault();
  if (document.activeElement?.id === 'c-input') { addCommentFiles(files); return; }  // image into the comment
  uploadFiles(S.sel, files);
});

// ------------------------------------------------------------------ list order (sidebar)
// 2.4.0 (#361): folders nest one level. A folder is a path "Clients/Company X" (FSEP; a name never holds the separator),
// per user as before. Tree order: each top folder, then its subfolders (settings order first, then any other folder a
// list uses; a subfolder's parent always exists). The sidebar shows a folder's own lists first, then its subfolders.
const FSEP = '/';
const fParent = p => String(p || '').includes(FSEP) ? p.slice(0, p.indexOf(FSEP)) : '';
const fName = p => String(p || '').includes(FSEP) ? p.slice(p.indexOf(FSEP) + 1) : String(p || '');
const fDisp = p => String(p || '').split(FSEP).join(' / ');
const fUnder = (p, top) => !!top && (p === top || String(p || '').startsWith(top + FSEP));
const fNorm = v => String(v || '').split(FSEP).map(x => x.trim()).filter(Boolean).join(FSEP);  // typed " A / b " -> "A/b"
const fDepth = p => p ? String(p).split(FSEP).length : 0;
function folderNames() {
  let arr = [];
  try { arr = JSON.parse(S.settings.folders || '[]'); } catch { /* bad json */ }
  const used = S.lists.filter(l => !l.is_inbox && !l.archived && l.folder).map(l => l.folder);
  const all = [...new Set([...arr.filter(x => typeof x === 'string' && x), ...used])];
  for (const p of [...all]) { const t = fParent(p); if (t && !all.includes(t)) all.push(t); }
  return folderMirror(all.filter(p => !fParent(p))).flatMap(t => [t, ...folderMirror(all.filter(p => fParent(p) === t))]);
}
// 2.27.0 (#988): the folders of another person (where I see their lists) keep THEIR order among each other, in the places
// they take in my sidebar; my own folders stay where I put them
function folderMirror(arr) {
  const out = [...arr];
  for (const order of Object.values(S.folderOrders || {})) {
    const theirs = order.filter(f => out.includes(f));
    if (theirs.length < 2) continue;
    const slots = out.map((f, i) => theirs.includes(f) ? i : -1).filter(i => i >= 0);
    slots.forEach((i, k) => { out[i] = theirs[k]; });
  }
  return out;
}
// 2.27.0 (#988): a list in someone else's folder sits where its owner put it; only the owner changes that
const mirroredMsg = l => tr('{0} arranges the lists of this shared folder for everyone.', l?.owner_name || tr('The owner'));
const folderSubs = t => folderNames().filter(p => fParent(p) === t);
function sideOrder() {  // lists as shown: top-level lists first, then folder by folder (a folder's lists, then its subfolders)
  const ls = S.lists.filter(l => !l.is_inbox && !l.archived);
  return [...ls.filter(l => !l.folder), ...folderNames().flatMap(f => ls.filter(l => l.folder === f))];
}
// open / closed folders: S.collapsed "fold:<path>" (as before) + the user setting folders_closed (all devices)
const foldClosed = p => S.collapsed.has('fold:' + p);
function foldSet(p, closed) {
  if (closed) S.collapsed.add('fold:' + p); else S.collapsed.delete('fold:' + p);
  LS.set('collapsed', [...S.collapsed]);
  S.settings.folders_closed = JSON.stringify([...S.collapsed].filter(k => k.startsWith('fold:')).map(k => k.slice(5)));
  clearTimeout(foldSet.t); foldSet.busy = true;
  foldSet.t = setTimeout(() => api('PATCH', '/api/settings', {folders_closed: S.settings.folders_closed}).catch(() => {}).finally(() => { foldSet.busy = false; }), 400);
}
function foldSync() {  // after a load: the server's list wins (the first time a device has closed folders the server lacks, they go up)
  if (foldSet.busy) return;
  let arr; try { arr = JSON.parse(S.settings.folders_closed || '[]'); } catch { return; }
  if (!Array.isArray(arr)) return;
  const mine = [...S.collapsed].filter(k => k.startsWith('fold:'));
  if (!arr.length && mine.length && !LS.get('foldUp', false)) { LS.set('foldUp', true); foldSet(mine[0].slice(5), true); return; }
  LS.set('foldUp', true);
  mine.forEach(k => S.collapsed.delete(k));
  arr.forEach(x => S.collapsed.add('fold:' + x));
}
async function saveFolders(arr) {
  S.settings.folders = JSON.stringify([...new Set(arr)]);
  renderSide();
  await api('PATCH', '/api/settings', {folders: S.settings.folders});
}
async function setListFolder(id, f) {
  const l = listById(id); if (!l || l.folder === f) return;
  if (l.mirrored) { toast(mirroredMsg(l)); return; }  // 2.27.0 (#988)
  const order = sideOrder().filter(x => x.id !== id);
  const last = order.map(x => x.folder).lastIndexOf(f);  // append at the end of the target folder
  if (last >= 0) order.splice(last + 1, 0, l);
  else {  // an empty folder: before the lists of the folders that follow it in the tree
    const fs = folderNames(), after = new Set(fs.slice(fs.indexOf(f) + 1));
    const i = f ? order.findIndex(x => x.folder && after.has(x.folder)) : 0;
    order.splice(i < 0 ? order.length : i, 0, l);
  }
  if (f && !folderNames().includes(f)) S.settings.folders = JSON.stringify([...folderNames(), f]);
  const e = await saveListOrder(order, {[id]: f}, f ? tr('Moved {0} to folder {1}', qn(lname(l)), fDisp(f)) : tr('Took {0} out of its folder', qn(lname(l))));
  if (f) await api('PATCH', '/api/settings', {folders: JSON.stringify(folderNames())});
  return e;
}
async function newFolder(thenList, parent = '') {
  const n = ((await askPrompt(parent ? tr('Subfolder of {0}', fDisp(parent)) : tr('Folder name'), '', {ok: tr('Create')})) || '').trim().split(FSEP).join('∕'); if (!n) return;
  const p = parent ? parent + FSEP + n : n;
  if (folderNames().includes(p)) { toast(tr('Folder already exists')); return; }
  const arr = folderNames();
  if (parent) { const subs = folderSubs(parent), at = arr.indexOf(subs.length ? subs[subs.length - 1] : parent); arr.splice(at + 1, 0, p); } else arr.push(p);
  await saveFolders(arr);
  if (thenList) setListFolder(thenList, p);
}
// rename / move a folder (with its lists and subfolders) and delete it (lists and subfolders move up one level)
async function folderMove(from, to, label) {
  if (!to || to === from) return;
  { const m = S.lists.find(l => l.mirrored && fUnder(l.folder, from)); if (m) { toast(mirroredMsg(m)); return; } }  // 2.27.0 (#988)
  if (folderNames().includes(to) && !await askConfirm(tr('Merge into “{0}”?', fDisp(to)), tr('A folder of that name exists: the lists go into it.'), {ok: tr('Merge')})) return;
  try { await api('POST', '/api/folders/rename', {old: from, new: to}); } catch { return; }
  await load(); render();
  if (label) toast(label);
}
function folderMenu(anchor, f) {
  const sub = !!fParent(f), hasSubs = folderSubs(f).length > 0;
  const into = folderNames().filter(t => !fParent(t) && t !== f && t !== fParent(f));
  menu(anchor, [
    {label: tr('New list in this folder'), icon: 'plus', fn: () => listModal(null, f)},
    ...(collab() && folderLists(f).some(l => isOwner(l)) ? [{label: tr('Share folder…'), icon: 'users', fn: () => folderPeopleModal(f)}] : []),  // 2.22.0 (#740)
    ...(collab() && (S.groups || []).length && folderLists(f).some(l => isOwner(l)) ? [{label: tr('Share with a group…'), icon: 'users', fn: () => folderGroupsModal(f)}] : []),  // 2.10.0 (#441)
    ...(sub ? [] : [{label: tr('New subfolder…'), icon: 'folder', fn: () => newFolder(null, f)}]),
    {label: tr('Rename'), icon: 'edit', fn: async () => {
      const n = ((await askPrompt(tr('Rename folder'), fName(f), {ok: tr('Rename')})) || '').trim().split(FSEP).join('∕'); if (!n || n === fName(f)) return;
      folderMove(f, sub ? fParent(f) + FSEP + n : n);
    }},
    // move into another folder (subfolders, and folders without subfolders) / out to the top level
    ...(!hasSubs && into.length ? [{label: sub ? tr('Move to another folder…') : tr('Move into a folder…'), icon: 'folder', fn: () => menu(anchor, into.map(t => ({label: fDisp(t), icon: 'folder', fn: () => folderMove(f, t + FSEP + fName(f), tr('Moved {0} to folder {1}', qn(fName(f)), fDisp(t)))})))}] : []),
    ...(sub ? [{label: tr('Move to the top level'), icon: 'outdent', fn: () => folderMove(f, fName(f), tr('{0} is a top-level folder now', qn(fName(f))))}] : []),
    '-',
    {label: tr('Dissolve folder (lists stay)'), icon: 'trash', cls: 'flag-5', fn: async () => {
      if (!await askConfirm(tr('Dissolve folder “{0}”?', fDisp(f)), hasSubs ? tr('The lists stay; its subfolders become top-level folders.') : sub ? tr('Its lists move up to {0}.', fDisp(fParent(f))) : tr('The lists stay.'), {ok: tr('Dissolve')})) return;
      await api('POST', '/api/folders/delete', {name: f}); await load(); render();
    }},
  ]);
}
// 2.22.0 (#740): share a whole folder with people: its lists now and every list that comes into it later (switchable off
// per person); the lists land with them in a folder of the same name
async function folderPeopleModal(f) {
  let users = [], have = [];
  try { users = (await api('GET', '/api/users')).users.filter(u => !u.disabled && S.me && u.id !== S.me.id && u.kind !== 'agent' && !u.agent); have = (await api('GET', '/api/folders/people?folder=' + encodeURIComponent(f))).people; } catch { return; }
  const md = modal(`<h3>${ic('users', 's')} ${esc(tr('Share folder “{0}”', fDisp(f)))}</h3>
    <p class="muted">${tr('Every list in this folder is shared now, and every list you add to it later. With them the lists land in a folder of the same name; they can move them freely.')}</p>
    <div class="fpl" id="fp-list"></div>
    <div class="row"><label for="fp-user">${tr('Person')}</label><select id="fp-user">${users.map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join('')}</select><select id="fp-role" aria-label="${esc(tr('Role'))}"><option value="edit">${tr('Member')}</option><option value="view">${tr('Viewer')}</option></select><button type="button" class="btn pri" data-m="add">${tr('Share')}</button></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Done')}</button></div>`);
  const draw = () => { $('#fp-list', md).innerHTML = have.length ? have.map(p => { const u = users.find(x => x.id === p.user_id); return `<div class="mrow">${av(p.user_id, u?.display_name || '?')}<span class="n">${esc(u?.display_name || '?')} <span class="muted">${esc(p.role === 'view' ? tr('Viewer') : tr('Member'))} · ${tr('new lists too')}</span></span><button class="iconbtn" data-rm="${p.user_id}" title="${esc(tr('Stop sharing new lists'))}" aria-label="${esc(tr('Stop sharing new lists with {0}', u?.display_name || '?'))}">${ic('x', 's')}</button></div>`; }).join('') : `<p class="muted">${tr('Not shared yet.')}</p>`; };
  draw();
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); await load(); render(); return; }
    if (b.dataset.m === 'add') {
      const uid = +$('#fp-user', md).value, role = $('#fp-role', md).value; if (!uid) return;
      try { const j = await api('PUT', '/api/folders/people', {folder: f, user_id: uid, role}); have = [...have.filter(x => x.user_id !== uid), {user_id: uid, role}]; draw(); toast(trn('{0} list shared', '{0} lists shared', j.shared)); } catch { /* api() said it */ }
    }
    if (b.dataset.rm) { try { await api('DELETE', '/api/folders/people', {folder: f, user_id: +b.dataset.rm}); have = have.filter(x => x.user_id !== +b.dataset.rm); draw(); } catch { /* api() said it */ } }
  });
}
// the sidebar order (+ folder moves) in one request, as one history step (label: what it was)
const listOrderNow = () => S.lists.filter(l => !l.is_inbox).sort((a, b) => (a.sort || 0) - (b.sort || 0) || a.id - b.id).map(l => l.id);
async function saveListOrder(order, folder, label) {
  const before = listOrderNow(), f0 = folder ? Object.fromEntries(Object.keys(folder).map(id => [id, listById(+id)?.folder || ''])) : null;
  const rest = S.lists.filter(l => !l.is_inbox && !order.includes(l));
  order.concat(rest).forEach((l, i) => { l.sort = i; });
  if (folder) for (const [id, f] of Object.entries(folder)) listById(+id).folder = f;
  S.lists.sort((a, b) => b.is_inbox - a.is_inbox || a.sort - b.sort || a.id - b.id);
  renderSide();
  const ids = order.concat(rest).map(l => l.id);
  await api('POST', '/api/lists/reorder', {ids, folder});
  const same = before.join() === ids.join() && (!folder || Object.keys(folder).every(k => f0[k] === folder[k]));
  if (same) return null;
  const go = (to, tf, from, ff) => async () => {
    const r = await api('POST', '/api/lists/reorder', {ids: to, ...(tf ? {folder: tf} : {}), _prev: {ids: from, ...(ff ? {folder: ff} : {})}});
    return {skipped: (r.conflicts || []).map(c => c.field === 'folder' ? `${lname(listById(c.id)) || '?'}: ${tr('Folder')}` : tr('List order'))};
  };
  return histAdd({label: label || tr('Lists reordered'), undo: go(before, f0, ids, folder), redo: go(ids, folder, before, f0)});
}
// 2.27.0 (#991): to the very top / bottom of its folder (keyboard, the list's menu in the sidebar)
function moveListEnd(id, dir) {
  const order = sideOrder(), l = order.find(x => x.id === id); if (!l) return;
  if (l.mirrored) { toast(mirroredMsg(l)); return; }
  const same = order.filter(x => (x.folder || '') === (l.folder || '')), j = dir < 0 ? order.indexOf(same[0]) : order.indexOf(same[same.length - 1]);
  if (order[j] === l) return;
  order.splice(order.indexOf(l), 1); order.splice(dir < 0 ? j : order.indexOf(same[same.length - 1]) + 1, 0, l);
  saveListOrder(order, undefined, tr('Moved list {0}', qn(lname(l))));
}
const listMoveItems = id => {
  const order = sideOrder(), i = order.findIndex(l => l.id === id), can = d => i >= 0 && order[i + d] && (order[i + d].folder || '') === (order[i].folder || '');
  return [{label: tr('Move up'), icon: 'chev', cls: 'mup', dis: !can(-1), fn: () => moveList(id, -1)}, {label: tr('Move down'), icon: 'chev', dis: !can(1), fn: () => moveList(id, 1)},
    {label: tr('Move to the top'), icon: 'chev', cls: 'mup mtop', dis: !can(-1), fn: () => moveListEnd(id, -1)}, {label: tr('Move to the bottom'), icon: 'chev', cls: 'mbot', dis: !can(1), fn: () => moveListEnd(id, 1)}];
};
function moveList(id, dir) {
  const order = sideOrder(), i = order.findIndex(l => l.id === id), j = i + dir;
  if (order[i]?.mirrored) { toast(mirroredMsg(order[i])); return; }  // 2.27.0 (#988)
  if (i < 0 || j < 0 || j >= order.length || order[j].folder !== order[i].folder) return;
  [order[i], order[j]] = [order[j], order[i]];
  saveListOrder(order, undefined, tr('Moved list {0}', qn(lname(listById(id)))));
}
// sidebar drag & drop (desktop): lists before lists, lists into folders (header or empty body),
// lists out of folders (onto the "Listen" header), folders before folders
let listDrag = null, folderDrag = null;
document.addEventListener('dragstart', e => {
  const r = e.target.closest && e.target.closest('#side .srow[data-list][draggable="true"]');
  const fh = e.target.closest && e.target.closest('#side .fhead[draggable="true"]');
  if (r) { listDrag = +r.dataset.list; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'list:' + listDrag); }
  else if (fh) { folderDrag = fh.dataset.folder; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'folder:' + folderDrag); }
});
const sideDropTarget = (el, folder = folderDrag !== null) => !el?.closest ? null : folder ? el.closest('#side .fhead, #side .shead.lroot') : el.closest('#side .srow[data-list], #side .fhead, #side .fempty, #side .shead.lroot');
// 2.4.0 (#361): what dropping folder `from` on target t does: 'before' (reorder among siblings), 'into' (a subfolder, or a
// folder without subfolders, goes into the top folder t; onto a subfolder elsewhere: into its parent, before it), 'top'
// (a subfolder onto the "Lists" header), null = nothing
function folderDropKind(from, t) {
  if (!t || from == null) return null;
  if (t.classList.contains('lroot')) return fParent(from) ? 'top' : null;
  const to = t.dataset.folder;
  if (!to || to === from || fUnder(to, from)) return null;
  if (fParent(to) === fParent(from)) return 'before';
  if (folderSubs(from).length) return null;  // a folder with subfolders stays top-level (two levels at most)
  return to === fParent(from) ? null : 'into';
}
// 2.27.0 (#991): the lower half of a list row = after it (so a list can go to the very end of a folder)
const sideAfter = (t, y) => !!t && t.classList.contains('srow') && y != null && (() => { const r = t.getBoundingClientRect(); return r.height > 0 && y > r.top + r.height / 2; })();
const sideMark = (t, drag, y) => {  // the same highlights for mouse and touch; false = not a valid target
  $$('#side .dropbefore, #side .dropafter, #side .drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  if (!t || (drag.list && t.dataset.list && +t.dataset.list === drag.list)) return false;
  if (drag.folder != null) {
    const kd = folderDropKind(drag.folder, t); if (!kd) return false;
    t.classList.add(kd === 'before' || (kd === 'into' && fParent(t.dataset.folder)) ? 'dropbefore' : 'drop');
    return true;
  }
  t.classList.add(t.classList.contains('srow') ? (sideAfter(t, y) ? 'dropafter' : 'dropbefore') : 'drop');
  return true;
};
document.addEventListener('dragover', e => {
  if (!listDrag && folderDrag === null) return;
  if (sideMark(sideDropTarget(e.target), {list: listDrag, folder: folderDrag}, e.clientY)) e.preventDefault();
});
document.addEventListener('drop', e => {
  if (!listDrag && folderDrag === null) return;
  e.preventDefault(); e.stopImmediatePropagation();
  const drag = {list: listDrag, folder: folderDrag}; listDrag = null; folderDrag = null;
  $$('#side .dropbefore, #side .dropafter, #side .drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  const t = sideDropTarget(e.target, drag.folder !== null);
  sideDrop(drag, t, sideAfter(t, e.clientY));
}, true);
// one drop in the sidebar (mouse or touch): a folder before a folder, a list into a folder (its header or empty body),
// out of a folder (the "Lists" header), or before another list (taking over that list's folder). One request; moving
// into / out of a folder can be undone.
async function sideDrop(drag, t, after = false) {
  if (!t) return;
  if (drag.folder != null) {
    const kd = folderDropKind(drag.folder, t), from = drag.folder;
    if (kd === 'before') {
      const arr = folderNames().filter(x => x !== from);
      arr.splice(arr.indexOf(t.dataset.folder), 0, from);
      saveFolders(fParent(from) ? arr : arr.filter(x => !fParent(x)).flatMap(x => [x, ...folderSubs(x)])); return;
    }
    if (kd === 'top') { folderMove(from, fName(from), tr('{0} is a top-level folder now', qn(fName(from)))); return; }
    if (kd === 'into') {
      const to = t.dataset.folder, par = fParent(to) || to, np = par + FSEP + fName(from);
      await folderMove(from, np, tr('Moved {0} to folder {1}', qn(fName(from)), fDisp(par)));
      if (fParent(to) && folderNames().includes(np)) { const arr = folderNames().filter(x => x !== np); arr.splice(arr.indexOf(to), 0, np); saveFolders(arr); }
    }
    return;
  }
  const id = drag.list, l = listById(id); if (!l) return;
  if (l.mirrored) { toast(mirroredMsg(l)); return; }  // 2.27.0 (#988)
  const f0 = l.folder || '';
  const undoFolder = (f, e) => { if (f !== f0 && e) offerUndo(f ? tr('Moved to folder {0}', fDisp(f)) : tr('Removed from folder'), e); };
  if (t.classList.contains('fhead') || t.classList.contains('fempty')) { const f = (t.closest('[data-folder]') || t).dataset.folder; undoFolder(f, await setListFolder(id, f)); return; }
  if (t.classList.contains('lroot')) { undoFolder('', await setListFolder(id, '')); return; }
  const order = sideOrder(), moving = order.find(x => x.id === id), target = listById(+t.dataset.list);
  if (!moving || !target || moving === target) return;
  order.splice(order.indexOf(moving), 1);
  order.splice(order.indexOf(target) + (after ? 1 : 0), 0, moving);
  const nf = target.folder || '';
  const e = await saveListOrder(order, (moving.folder || '') !== nf ? {[moving.id]: nf} : undefined,
    (moving.folder || '') !== nf ? (nf ? tr('Moved {0} to folder {1}', qn(lname(moving)), fDisp(nf)) : tr('Took {0} out of its folder', qn(lname(moving)))) : tr('Moved list {0}', qn(lname(moving))));
  undoFolder(nf, e);
}
function folderPick(anchor, id) {
  const cur = listById(id)?.folder || '';
  menu(anchor, [{label: tr('No folder'), icon: 'list', on: !cur, fn: () => setListFolder(id, '')},
    ...folderNames().map(f => ({label: fParent(f) ? '\u2003' + fName(f) : f, icon: 'folder', on: cur === f, fn: () => setListFolder(id, f)})),
    '-', {label: tr('New folder…'), icon: 'plus', fn: () => newFolder(id)}]);
}
// touch (phone drawer, tablets): long-press a list or a folder, then drag -- same targets and highlights as the mouse.
// Held and let go without moving: the list's menu (edit, type, "Move to folder…") / the folder's menu.
// 2.28.0 (#976): a right-click on a list or folder in the sidebar opens its menu (mouse; touch uses the long press below)
document.addEventListener('contextmenu', e => {
  if (isTouch() || S.listReorder || e.shiftKey) return;
  const r = e.target.closest?.('#side .srow[data-list]'), fh = !r && e.target.closest?.('#side .fhead[data-folder]');
  if (!r && !fh) return;
  e.preventDefault();
  if (r) listMenu(r, +r.dataset.list); else folderMenu(fh, fh.dataset.folder);
});
let sd = null, sdHeld = false;
document.addEventListener('touchstart', e => {
  const r = e.target.closest?.('#side .srow[data-list]'), fh = !r && e.target.closest?.('#side .fhead');
  // 2.25.0 (UX-02): in sort mode the grip drags at once; elsewhere in sort mode a touch scrolls
  const grip = S.listReorder && e.target.closest('.sgrip');
  if ((S.listReorder && !grip) || !(r || fh) || e.target.closest('.iconbtn') || (r && listById(+r.dataset.list)?.archived)) { sd = null; return; }
  const p = e.touches[0];
  sd = {el: r || fh, list: r ? +r.dataset.list : null, folder: fh ? fh.dataset.folder : null, x: p.clientX, y: p.clientY, active: false, reorder: !!grip};
  if (grip) sdStart(); else sd.timer = setTimeout(sdStart, 380);
}, {passive: true});
function sdStart() {
  if (!sd) return;
  sd.active = true;
  const rect = sd.el.getBoundingClientRect(), g = sd.el.cloneNode(true);
  g.classList.add('ghost-drag', 'side-ghost');
  g.style.cssText = `position:fixed;left:${rect.left}px;top:${rect.top}px;width:${rect.width}px;z-index:96;pointer-events:none`;
  document.body.appendChild(g);
  sd.ghost = g; sd.dy = sd.y - rect.top;
  sd.el.classList.add('dragging');
  if (navigator.vibrate) navigator.vibrate(12);
}
document.addEventListener('touchmove', e => {
  if (!sd) return;
  const p = e.touches[0];
  if (!sd.active) { if (Math.hypot(p.clientX - sd.x, p.clientY - sd.y) > 8) { clearTimeout(sd.timer); sd = null; } return; }  // scrolling
  e.preventDefault();
  sd.moved = true; sd.lx = p.clientX; sd.ly = p.clientY;
  sd.ghost.style.top = (p.clientY - sd.dy) + 'px';
  const t = sideDropTarget(document.elementFromPoint(p.clientX, p.clientY), sd.folder != null);
  sideMark(t, sd, p.clientY);
  const side = $('#side'), r = side.getBoundingClientRect();
  if (r.height && side.scrollBy) { if (p.clientY < r.top + 48) side.scrollBy(0, -12); else if (p.clientY > r.bottom - 48) side.scrollBy(0, 12); }
  // hovering a closed folder for a moment opens it
  const fh = t && sd.list && t.classList.contains('fhead') && t.classList.contains('closed') ? t.dataset.folder : null;
  if (fh !== sd.hover) { clearTimeout(sd.open); sd.hover = fh; if (fh) sd.open = setTimeout(() => { if (sd && sd.hover === fh) { foldSet(fh, false); renderSide(); } }, 600); }
}, {passive: false});
function sdEnd(e) {
  if (!sd) return;
  clearTimeout(sd.timer); clearTimeout(sd.open);
  const st = sd; sd = null;
  if (!st.active) return;  // a tap: the row's own click (opens the list)
  if (e && e.cancelable) e.preventDefault();
  sdHeld = true; setTimeout(() => { sdHeld = false; }, 500);
  st.ghost.remove(); st.el.classList.remove('dragging');
  const t = st.moved ? sideDropTarget(document.elementFromPoint(st.lx, st.ly), st.folder != null) : null;
  $$('#side .dropbefore, #side .dropafter, #side .drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  if (!st.moved && st.reorder) return;  // a tap on the grip
  if (!st.moved) { const el = st.list ? $(`#side .srow[data-list="${st.list}"]`) : $(`#side .fhead[data-folder="${rmEsc(st.folder)}"]`); if (el) st.list ? listMenu(el, st.list) : folderMenu(el, st.folder); return; }
  if (t && e?.type === 'touchend') sideDrop({list: st.list, folder: st.folder}, t, sideAfter(t, st.ly));
}
document.addEventListener('touchend', sdEnd);
document.addEventListener('touchcancel', sdEnd);
document.addEventListener('dragend', () => { listDrag = null; folderDrag = null; });
