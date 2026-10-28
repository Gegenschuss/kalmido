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
  an_watch(b);  // 2.46.1 (#1559): the bar slides in and out (watched after its first state is set)
  document.body.classList.toggle('msel', !!(S.multiMode || n));  // 2.26.0: the docked quick add steps back while selecting
  $('#fab').classList.toggle('gone', fabOff() || S.multiMode || n > 0 || (!!$('#view .qdock') && (tabletDock() || !isMobile())));
  // 2.26.0 (#936): the selection is edited in the task panel (from two tasks: their common fields, see multiedit.js); the
  // bar keeps only what the panel does not have: the count, Complete, Delete and Clear selection. A phone opens the panel
  // as a sheet with "Edit"; with nothing selected yet (select mode) it offers "All".
  const mob = isMobile();
  const btn = ([act, i, lab, cls]) => `<button class="mbb ${cls || ''}" data-act="${act}" data-ico="${i}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic(i, 's')}<span class="mbl">${esc(lab)}</span></button>`;
  b.setAttribute('role', 'toolbar'); b.setAttribute('aria-label', tr('Selection'));
  // 2.32.0 (#1055): a phone's bar is Move, Date, Complete and More (Edit, Select all, the task's menu, Delete); a long press
  // on a row starts the selection, more rows join with a tap
  const acts = !n ? btn(['mb-all', 'all', tr('All')])
    : mob ? btn(['mb-move', 'folder', tr('Move')]) + btn(['mb-date', 'cal', tr('Date')]) + btn(['mb-done', 'done', tr('Complete')]) + btn(['mb-menu', 'dots', tr('More')])
      : btn(['mb-done', 'done', tr('Complete')]) + btn(['mb-del', 'trash', tr('Delete'), 'danger']);
  b.classList.toggle('mb4', mob && n > 0);
  b.innerHTML = `<span class="mcount" role="status">${n ? tr('{0} selected', n) : tr('Tap tasks')}</span>
    ${acts}
    <button class="iconbtn mbx" data-act="mb-close" title="${esc(tr('Clear selection') + ' (Esc)')}" aria-label="${esc(tr('Clear selection'))}">${ic('x')}</button>`;
  meSync();
}
// 2.270.0 D (#3028): {id: {field: the value this device saw}} for a multi-select change (server: batch "patch" data.prev)
const btcPrev = (ids, data) => Object.fromEntries(ids.map(i => [i, S.tasks.get(i)]).filter(([, t]) => t).map(([i, t]) =>
  [i, Object.fromEntries(Object.keys(data).filter(k => k in t && k !== 'tags').map(k => [k, typeof t[k] === 'boolean' ? +t[k] : t[k] ?? null]))]));
async function batch(action, data, clear, ids = [...S.multi], note = '') {
  if (!ids.length) return;
  if (action === 'patch') {  // 2.36.0 (#1118): locked tasks keep their locked fields; the others change
    const lk = ids.filter(i => tlkHits(S.tasks.get(i), data));
    if (lk.length === ids.length) { tlkToast(S.tasks.get(lk[0])); return; }
    if (lk.length) { ids = ids.filter(i => !lk.includes(i)); note = [note, trn('{0} locked task skipped', '{0} locked tasks skipped', lk.length)].filter(Boolean).join(' · '); }
    data = {...data, prev: btcPrev(ids, data)};  // 2.270.0 D (#3028): what each task showed here; changed elsewhere = kept + reported
  }
  if (action === 'complete' && !data?.expect) {  // 2.270.0 C (#3022): the date each recurring task had here -- a repeated send never advances it twice
    const ex = Object.fromEntries(ids.map(i => [i, S.tasks.get(i)]).filter(([, t]) => t?.repeat && t.status === 0)
      .map(([i, t]) => [i, /TIMES=/.test(t.repeat) ? {due: t.due ?? null, due_time: t.due_time ?? null} : {due: t.due ?? null}]));
    if (Object.keys(ex).length) data = {...data, expect: ex};
  }
  const snaps = ids.flatMap(withKids);
  const cs = action === 'complete' ? celeSnap(ids) : null;
  if (action === 'delete' && !data?.guard) data = {...data, guard: Object.fromEntries(ids.map(i => [i, S.tasks.get(i)?.updated_at]).filter(x => x[1]))};  // 2.272.0 B (#3045): changed by someone else since = stays
  const j = await api('POST', '/api/tasks/batch', {ids, action, data});
  if (j.errors?.length) toast(j.errors[0]);
  const twice = action === 'complete' ? (j.conflicts || []).filter(c => ['due', 'due_time', 'status'].includes(c.field)).length : 0;
  if (twice) note = [note, tr('Recurring task was already checked off, not advanced twice')].filter(Boolean).join(' · ');
  if (clear) { S.multi.clear(); S.multiMode = false; }
  await load(); render();
  if (cs && !j.errors?.length) celeCheck(cs);
  if (j.errors?.length) return;
  const cf = action === 'delete' ? (j.conflicts || []).length : 0;  // 2.272.0 B (#3045)
  if (cf) { ids = ids.filter(i => !j.conflicts.some(x => x.id === i)); note = [note, trn('{0} task stays: changed by someone else', '{0} tasks stay: changed by someone else', cf)].filter(Boolean).join(' · '); if (!ids.length) { toast(note); return; } }
  { const wn = action === 'patch' && data?.list_id ? snaps.filter(b => ids.includes(b.id)).map(b => wsc_moveMsg(b.list_id, data.list_id, '')).find(Boolean) : ''; if (wn) note = [note, wn].filter(Boolean).join(' · '); }  // 2.53.0 (#1474)
  const msg = (action === 'complete' ? trn('{0} task completed', '{0} tasks completed', ids.length - twice) : action === 'delete' ? trn('{0} task deleted', '{0} tasks deleted', ids.length) : trn('{0} task changed', '{0} tasks changed', ids.length)) + (note ? ' · ' + note : '');
  const one = ids.length === 1 ? qn((snaps.find(x => x.id === ids[0])?.title || '').slice(0, 40)) : '';
  if (action === 'complete') offerUndo(msg, histDone(one ? tr('Completed {0}', one) : trn('Completed {0} task', 'Completed {0} tasks', ids.length), ids, snaps, j, data?.status ?? 2));
  else if (action === 'delete') offerUndo(msg, histTrash(one ? tr('Deleted {0}', one) : trn('Deleted {0} task', 'Deleted {0} tasks', ids.length), ids, snaps, j));
  else if (action === 'patch') {
    for (const c of j.conflicts || []) addConflicts(c.id, [c], c.title);  // 2.270.0 D (#3028)
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
  if (!may.length) { toast(trn('{0} overdue task is in a project you may only view', '{0} overdue tasks are in projects you may only view', ro)); return; }
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
// 2.32.0 (#1055): the lists the selection can move to (the bar's Move, the key m without the multi panel)
function multiMoveMenu(a) {
  tch_listPicker(a, {filter: l => canEditList(l.id), pick: l => { const ids = [...S.multi]; S.multi.clear(); S.multiMode = false; dgToList(ids, l.id); }});  // 2.38.0 (#1177); 2.43.0 (#1003): subtasks leave their parent (one batch, one undo)
}
// 2.32.0 (#1055): the phone bar's More: what does not fit into the four buttons
function multiMoreMenu(a) {
  const ids = [...S.multi], one = ids.length === 1 ? taskById(ids[0]) : null;
  menu(a, [
    ...(ids.length >= 2 ? [{label: tr('Edit'), icon: 'edit', fn: () => { ME.sheet = true; meSync(); }}] : []),
    ...tp_menuItems(one, a),  // 2.46.4 (#1751): "Open details" in a list where a tap ticks off
    ...(one && one.id > 0 && canEdit(one) ? [{label: tr('More actions'), icon: 'dots', fn: () => taskMenu($(`#view .trow[data-id="${one.id}"] .ttl`) || a, one.id)}] : []),
    ...(ids.length && ids.some(i => canEdit(taskById(i))) ? dgMenuItems(ids) : []),  // 2.43.0 (#1003): Subtasks of… / Out of the parent task
    ...ml_multiItems(ids, a),  // 2.320.0 (#3289): Show also in project…
    {label: tr('Select all'), icon: 'all', fn: () => { vl_ids().forEach(i => S.multi.add(i)); render(); }},  // 2.65.0 (#1825): also the rows a long list does not draw
    ...(clnSel() ? [{label: tr('Tidy up…'), icon: 'bot', cls: 'mclean', fn: () => clnRequest(clnSel().id, ids)}] : []),  // 2.39.0 (#1151)
    '-',
    {label: tr('Delete'), icon: 'trash', cls: 'flag-5', fn: () => batch('delete', {}, true)},
  ]);
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
  const r = {op: 'and', lists: [], dates: [], prios: [], types: [], tags: [], who: [], secs: [], sprints: [], ms: [], text: '', ...JSON.parse(JSON.stringify(f.rules || {}))};
  r.cf = r.cf && typeof r.cf === 'object' ? r.cf : {};
  // custom fields of the visible lists that the filter engine understands
  const cfs = (fieldsOn() ? S.fields || [] : []).filter(x => ['select', 'checkbox', 'date', 'number', 'multiselect', 'currency', 'rating'].includes(x.type) && listById(x.list_id) && !listById(x.list_id).archived);
  const cfChips = (fd, kind, opts) => `<div class="fchips" data-cf="${fd.id}" data-cfk="${kind}">${opts.map(([v, n]) => `<button class="${(r.cf[fd.id]?.[kind] || []).includes(v) ? 'on' : ''}" data-v="${esc(v)}">${esc(n)}</button>`).join('')}</div>`;
  const cfRow = fd => {
    const cur = r.cf[fd.id] || {};
    const ctl = fd.type === 'select' || fd.type === 'multiselect' ? cfChips(fd, 'sel', [...(fd.options?.options || []).map(o => [o.id, o.name]), ['', tr('empty')]])
      : fd.type === 'checkbox' ? cfChips(fd, 'chk', [['1', tr('checked')], ['0', tr('not checked')]])
      : fd.type === 'date' ? cfChips(fd, 'date', DATE_OPTS.map(([v, n]) => [v, tr(n)]))
      : `<div class="cfnumf"><select data-cfnum="${fd.id}"><option value="">–</option>${[['gt', '>'], ['lt', '<'], ['eq', '='], ['set', tr('has a value')], ['empty', tr('empty')]].map(([k, n]) => `<option value="${k}" ${cur.num?.op === k ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select><input data-cfnumv="${fd.id}" inputmode="decimal" value="${esc(cur.num?.v ?? '')}" style="max-width:6.875rem">${fd.options?.unit ? `<span class="muted">${esc(fd.options.unit)}</span>` : ''}</div>`;
    return `<div class="cfrow"><div class="cfn">${esc(lname(listById(fd.list_id)))} › <b>${esc(fd.name)}</b></div>${ctl}</div>`;
  };
  const tags = [...new Set([...S.tasks.values()].flatMap(t => t.tags))].sort((a, b) => a.localeCompare(b, 'de'));
  // 2.390.0 B (#3355): assignee, column, sprint, milestone (only what occurs in the visible projects, or is chosen already)
  const liveL = id => { const l = listById(id); return l && !l.archived ? l : null; };
  const whoIds = [...new Set([...S.tasks.values()].filter(t => t.assignee_id && t.assignee_id !== S.me?.id && liveL(t.list_id)).map(t => t.assignee_id))];
  const who = [['me', tr('Me')], ['none', tr('Nobody')], ...whoIds.map(id => [String(id), personNameAny(id) || '#' + id]).sort((a, b) => a[1].localeCompare(b[1], 'de'))];
  const secs = S.sections.filter(s => liveL(s.list_id) && (!r.lists.length || r.lists.includes(s.list_id))).map(s => [String(s.id), `${lname(liveL(s.list_id))} › ${s.name}`]);
  const mss = [...S.tasks.values()].filter(t => t.ms && !t.deleted_at && liveL(t.list_id)).map(t => [String(t.id), t.title]);
  const sprOn = S.lists.some(l => !l.archived && spr_on(l)) || r.sprints.length;
  const chips = (key, opts, translate) => `<div class="fchips" data-key="${key}">${opts.map(([v, n]) => (translate ? [v, tr(n)] : [v, n])).map(([v, n]) => `<button class="${r[key].includes(v) ? 'on' : ''}" data-v="${esc(String(v))}">${esc(n)}</button>`).join('')}</div>`;
  const md = modal(`<h3>${id ? tr('Edit filter') : tr('New filter')}</h3>
    <div class="row"><label for="f-name">${tr('Name')}</label><input id="f-name" value="${esc(f.name)}" placeholder="${tr('e.g. Important this week')}"></div>
    <div class="row"><label>${tr('Match')}</label><div class="seg" id="f-op"><button data-op="and" class="${r.op !== 'or' ? 'on' : ''}">${tr('AND: all conditions')}</button><button data-op="or" class="${r.op === 'or' ? 'on' : ''}">${tr('OR: any one')}</button></div></div>
    <h4>${tr('Projects')}</h4>${chips('lists', S.lists.filter(l => !l.archived).map(l => [l.id, lname(l)]))}
    <h4>${tr('Date')}</h4>${chips('dates', DATE_OPTS, true)}
    <h4>${tr('Priority')}</h4>${chips('prios', [[5, N_('High')], [3, N_('Medium')], [1, N_('Low')], [0, N_('None')]], true)}
    ${ticketsAny() || r.types.length ? `<h4>${tr('Ticket type')}</h4>${chips('types', [...TTYPES.map(([k, n]) => [k, n]), ['', N_('No type')]], true)}` : ''}
    ${tags.length ? `<h4>${tr('Tags')}</h4>${chips('tags', tags.map(g => [g, '#' + g]))}` : ''}
    ${cfs.length ? `<h4>${tr('Custom fields')}</h4><div class="cffilters">${cfs.map(cfRow).join('')}</div>` : ''}
    <h4>${tr('Assignee')}</h4>${chips('who', who)}
    ${secs.length || r.secs.length ? `<h4>${tr('Column')}</h4>${chips('secs', [...secs, ['none', tr('No column')]])}` : ''}
    ${sprOn ? `<h4>${tr('Sprint')}</h4>${chips('sprints', [['cur', tr('Current sprint')], ['none', tr('Backlog')]])}` : ''}
    ${mss.length || r.ms.length ? `<h4>${tr('Milestone')}</h4>${chips('ms', [...mss, ['none', tr('No milestone')]])}` : ''}
    <h4><label for="f-text">${tr('Text')}</label></h4><input id="f-text" value="${esc(r.text)}" placeholder="${esc(tr('Title or notes contain …'))}" autocomplete="off">
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
  md.addEventListener('input', e => { if (e.target.dataset.cfnumv) numRule(e.target.dataset.cfnumv); if (e.target.id === 'f-text') { r.text = e.target.value; count(); } });
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
// 2.32.0 (#362): files dropped anywhere else on an open list (its main area, not the project page) or on a list in the
// sidebar: one new task per file in that list, the file name without its extension as the title, the file attached.
// The project page keeps its own drop on "Project files"; the agents' chat keeps its own.
function fileListTarget(e) {
  const sr = e.target.closest?.('#side .srow[data-drop]');
  if (sr) { const k = sr.dataset.drop, l = k === 'inbox' ? inbox() : k.startsWith('l:') ? listById(+k.slice(2)) : null; return l && !l.archived && canAddTo(l.id) ? {l, el: sr} : null; }
  const v = e.target.closest?.('#view'); if (!v || e.target.closest('#pov-files, .chview, .pov, input, textarea')) return null;
  const l = routeList(); if (!l || l.archived || !canAddTo(l.id) || curView(l) === 'overview') return null;
  return {l, el: v};
}
function fileDropHint(t) {
  let h = $('#fdhint');
  if (!t) { h?.remove(); return; }
  if (!h) { h = document.createElement('div'); h.id = 'fdhint'; h.setAttribute('role', 'status'); document.body.appendChild(h); }
  const txt = tr('Drop: one new task per file in {0}', lname(t.l));
  if (h.textContent !== txt) h.innerHTML = `${ic('upload', 's')}<span>${esc(txt)}</span>`;
  const r = (t.el.id === 'view' ? t.el : $('#view') || t.el).getBoundingClientRect();
  h.style.left = Math.round(r.left + r.width / 2) + 'px'; h.style.top = Math.round(r.top + 12) + 'px';
}
async function filesToTasks(l, files) {
  files = noEmpty(files);
  if (!files.length) return;
  if (!OUT.online) { toast(tr('Offline: only works again with a connection')); return; }
  const max = 50 * 1024 * 1024, big = files.find(f => f.size > max);
  if (big) { toast(tr('{0} is larger than 50 MB', big.name)); return; }
  toast(files.length === 1 ? tr('Uploading…') : tr('Uploading {0} files…', files.length));
  let n = 0;
  await histGroup(async () => {
    for (const f of files) {
      let t = null;
      try {
        t = await createTask({title: (f.name || tr('File')).replace(/\.[^.]+$/, '') || f.name, list_id: l.id, priority: 0});
        const fd = new FormData(); fd.append('file', f, f.name);
        // 2.64.2 B (#1817): a list with the lock takes the file encrypted with the list key
        putTask(typeof le2eFileUpload === 'function' && le2eOn(l.id) ? await le2eFileUpload(t.id, [f], null, true) : await api('POST', `/api/tasks/${t.id}/attachments`, fd)); n++;
      } catch {
        // 2.32 review: the upload failed (size limit of the server, network): no task without its file stays behind
        if (t?.id) { try { await api('DELETE', `/api/tasks/${t.id}`); S.tasks.delete(t.id); } catch {} }
        break; /* api() showed it */
      }
    }
  });
  render();
  if (n) toast(trn('{0} task created with its file', '{0} tasks created with their files', n));
}
document.addEventListener('dragover', e => {
  if (!hasFiles(e)) return;
  const tgt = e.target.closest('#detail, #view .trow');
  $$('.filedrop').forEach(x => x.classList.remove('filedrop'));
  if (!tgt || (tgt.id === 'detail' && !S.sel)) {
    const lt = !tgt && fileListTarget(e); fileDropHint(lt || null);
    if (lt) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; lt.el.classList.add('filedrop'); }
    return;
  }
  fileDropHint(null);
  e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
  tgt.classList.add('filedrop');
});
document.addEventListener('dragleave', e => { if (hasFiles(e) && !e.relatedTarget) { $$('.filedrop').forEach(x => x.classList.remove('filedrop')); fileDropHint(null); } });
document.addEventListener('drop', e => {
  if (!hasFiles(e)) return;
  $$('.filedrop').forEach(x => x.classList.remove('filedrop')); fileDropHint(null);
  const tgt = e.target.closest('#detail, #view .trow');
  if (!tgt) {
    const lt = fileListTarget(e); if (!lt) return;
    e.preventDefault(); e.stopImmediatePropagation();
    filesToTasks(lt.l, e.dataTransfer.files); return;
  }
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
// 2.4.0 (#361): a folder is a path "Clients/Company X" (FSEP; a name never holds the separator), per user as before.
// 2.352.0 E (#2748): any depth (the folders are folders of the file store, lists/lffolder.py). Tree order: each folder, then
// its subfolders, depth first (settings order first, then any other folder a list uses; a subfolder's parents always exist).
// The sidebar shows a folder's own lists first, then its subfolders.
const FSEP = '/';
const fParent = p => String(p || '').includes(FSEP) ? p.slice(0, p.lastIndexOf(FSEP)) : '';
const fName = p => String(p || '').includes(FSEP) ? p.slice(p.lastIndexOf(FSEP) + 1) : String(p || '');
const fDisp = p => String(p || '').split(FSEP).join(' / ');
const fUnder = (p, top) => !!top && (p === top || String(p || '').startsWith(top + FSEP));
const fNorm = v => String(v || '').split(FSEP).map(x => x.trim()).filter(Boolean).join(FSEP);  // typed " A / b " -> "A/b"
const fDepth = p => p ? String(p).split(FSEP).length : 0;
function folderNames() {
  let arr = [];
  try { arr = JSON.parse(S.settings.folders || '[]'); } catch { /* bad json */ }
  const used = S.lists.filter(l => !l.is_inbox && !l.archived && l.folder).map(l => l.folder);
  const all = [...new Set([...arr.filter(x => typeof x === 'string' && x), ...used])];
  for (const p of [...all]) for (let t = fParent(p); t; t = fParent(t)) if (!all.includes(t)) all.push(t);
  const walk = par => folderMirror(all.filter(p => fParent(p) === par)).flatMap(t => [t, ...walk(t)]);
  return walk('');
}
// 2.352.0 E (#2748): the whole folder order with the folders below par in the order sibs (moving / sorting among siblings)
function fOrderWith(par, sibs) {
  const all = folderNames(), walk = p => (p === par ? sibs : all.filter(x => fParent(x) === p)).flatMap(t => [t, ...walk(t)]);
  return walk('');
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
const mirroredMsg = l => tr('{0} arranges the projects of this shared folder for everyone.', l?.owner_name || tr('The owner'));
const folderSubs = t => folderNames().filter(p => fParent(p) === t);
function sideOrder() {  // lists as shown: top-level lists first, then folder by folder (a folder's lists, then its subfolders)
  const ls = S.lists.filter(l => !l.is_inbox && !l.archived);
  return [...ls.filter(l => !l.folder), ...folderNames().flatMap(f => ls.filter(l => l.folder === f))];
}
// open / closed folders: S.collapsed "fold:<path>" (as before) + the user setting folders_closed (all devices)
const foldClosed = p => sv_fold(p) ?? S.collapsed.has('fold:' + p);  // 2.156.0 D (#2186): in a sidebar view only for now (sideviews.js)
function foldSet(p, closed) {
  if (sv_foldSet(p, closed)) return;
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
  const now = folderNowShared(id, f);  // 2.41.0 (#1428): into a shared folder -> "Now shared with …" + Undo
  const e = await saveListOrder(order, {[id]: f}, f ? tr('Moved {0} to folder {1}', qn(lname(l)), fDisp(f)) : tr('Took {0} out of its folder', qn(lname(l))));
  if (f) await api('PATCH', '/api/settings', {folders: JSON.stringify(folderNames())});
  if (e && now) { offerUndo(now, e); e._said = true; }
  return e;
}
async function newFolder(thenList, parent = '') {
  const n = ((await askPrompt(parent ? tr('Subfolder of {0}', fDisp(parent)) : tr('Folder name'), '', {ok: tr('Create')})) || '').trim().split(FSEP).join('∕'); if (!n) return;
  const p = parent ? parent + FSEP + n : n;
  if (folderNames().includes(p)) { toast(tr('Folder already exists')); return; }
  const arr = folderNames();
  if (parent) arr.splice(arr.map(x => fUnder(x, parent)).lastIndexOf(true) + 1, 0, p); else arr.push(p);  // 2.352.0 E (#2748): after the parent's last subfolder
  sb_folderWs(p);
  await saveFolders(arr);
  await sb_folderWsSave(p);
  await lf_ensure(p);  // 2.352.0 E (#2748): the folder node in the file store at once (it can be shared while still empty)
  if (thenList) setListFolder(thenList, p);
}
// 2.352.0 E (#2748): the projects trees of the server (GET /api/lists/tree, asked for before an action: the sidebar itself
// draws from the paths): my folder node of a path for sharing it and for a new folder
let LF_TREE = null;
async function lf_tree() { try { LF_TREE = (await api('GET', '/api/lists/tree')).spaces || []; } catch { LF_TREE = LF_TREE || []; } return LF_TREE; }
// the workspace of folder f: its setting "Workspace", else the shown one (All = private)
const lf_wsOf = f => { const e = folderEff(f); if ('org_id' in e) return e.org_id ? 'org:' + e.org_id : 'private'; const w = wsCur(); return w === 'all' ? 'private' : w; };
const lf_space = ws => (LF_TREE || []).find(x => ws === 'private' ? x.org_id == null : 'org:' + x.org_id === ws) || null;
// -> the node id of my folder at path f in the tree of its workspace (made on the way, also its parents; the same path in
// another workspace is another node there), null = not possible (offline, no tree)
async function lf_ensure(f, fresh = true) {
  if (!f) return null;
  if (fresh || !LF_TREE) await lf_tree();
  const sp = lf_space(lf_wsOf(f)) || lf_space('private'); if (!sp) return null;
  const n = (sp.folders || []).find(y => y.mine && y.path === f); if (n) return n.id;
  const pid = fParent(f) ? await lf_ensure(fParent(f), false) : sp.root; if (!pid) return null;
  try { const j = await api('POST', '/api/lists/folders', {parent_id: pid, name: fName(f)}); (sp.folders = sp.folders || []).push({id: j.id, parent_id: pid, name: fName(f), path: j.path || f, mine: true}); return j.id; } catch { return null; }
}
// 2.45.0 (#1532): a new folder belongs to the shown workspace (its folder setting "Workspace", private = 0), so it shows there
// at once while still empty; a subfolder of a folder with a workspace inherits it
function sb_folderWs(p) {
  const ws = wsCur(); if (ws === 'all' || 'org_id' in folderEff(p)) return null;
  const org = ws === 'private' ? 0 : +ws.slice(4);
  S.folderProps = {...(S.folderProps || {}), [p]: {...((S.folderProps || {})[p] || {}), org_id: org}};
  return org;
}
async function sb_folderWsSave(p) {
  const v = (S.folderProps || {})[p]?.org_id; if (v === undefined || !wsOn()) return;
  try { await api('PUT', '/api/folders/props', {folder: p, props: {org_id: v}, apply: 'new'}); } catch { /* offline: the folder still shows under All */ }
}
// does the folder (or one below it) belong to workspace ws by its own setting (an empty folder has no lists to tell)
const sb_folderInWs = (f, ws = wsCur()) => folderNames().some(x => fUnder(x, f) && 'org_id' in folderEff(x) && (folderEff(x).org_id ? 'org:' + folderEff(x).org_id : 'private') === ws);
// rename / move a folder (with its lists and subfolders) and delete it (lists and subfolders move up one level)
async function folderMove(from, to, label, noReload) {
  if (!to || to === from) return;
  { const m = S.lists.find(l => l.mirrored && fUnder(l.folder, from)); if (m) { toast(mirroredMsg(m)); return; } }  // 2.27.0 (#988)
  if (folderNames().includes(to) && !await askConfirm(tr('Merge into “{0}”?', fDisp(to)), tr('A folder of that name exists: the projects go into it.'), {ok: tr('Merge')})) return;
  // 2.41.2 (#1501): the sidebar shows the new name / place at once; what goes along on the server (shares, templates,
  // repositories, playbook) follows with a reload behind it
  const mv = p => fUnder(p, from) ? to + p.slice(from.length) : p;
  const put = () => {
    const f0 = S.settings.folders, l0 = S.lists.map(l => [l.id, l.folder]);
    S.settings.folders = JSON.stringify([...new Set(folderNames().map(mv))]);
    for (const l of S.lists) l.folder = mv(l.folder);
    return () => { S.settings.folders = f0; for (const [id, f] of l0) { const l = listById(id); if (l) l.folder = f; } };
  };
  try { await optWrite(put, () => api('POST', '/api/folders/rename', {old: from, new: to})); } catch { return; }
  if (label) toast(label);
  if (noReload) return true;  // 2.46.2 (#1664): the caller saves the order first, then reloads (no stale order from the reload)
  load().then(() => render()).catch(() => {});
}
function folderMenu(anchor, f) { menu(anchor, folderMenuItems(f, () => anchor)); }
// 2.352.0 E (#2748): the folder's menu items (its "…", a right click, the tree's hold: areas.js sbb_tmenu); any depth: a
// subfolder in every folder, moving into any folder that is not below it
function folderMenuItems(f, anchorOf = () => $(`#side .fhead[data-folder="${rmEsc(f)}"]`) || $('#side')) {
  const sub = !!fParent(f), hasSubs = folderSubs(f).length > 0;
  const into = folderNames().filter(t => t !== f && !fUnder(t, f) && t !== fParent(f));
  const own = folderLists(f).some(l => isOwner(l)) || !folderLists(f).length, noOwn = tr('Only your own projects can be shared');  // 2.352.0 E (#2748): an empty folder of mine can be shared (its node)
  // 2.352.0 E (#2748): someone else's folder (its projects are arranged by its owner, #988): only its owner renames, moves,
  // dissolves it or adds a subfolder (the server says 403), so those entries are not offered
  const theirs = folderLists(f).some(l => l.mirrored);
  return [
    ...lp_folderMenuRow(f),  // 2.53.0 (#1426): the folder's colour (new lists in it take it)
    ...fv2_menuRow('folder:' + f),  // 2.57.0 (#1798): a folder can be a favourite
    ...o3c_folderMenuRow(f),  // 2.83.0 C (#1427): the folder's header strip
    {label: tr('New project in this folder'), icon: 'plus', fn: () => listModal(null, f)},
    // 2.37.0 (#1158): the folder settings always (they hold for new lists too); without lists of my own the share entries
    // stay visible but greyed out with the reason (lists of others cannot be shared)
    // 2.41.0 (#1420): one Share dialog for people, groups and agents (sharedlg.js); the separate group dialog is part of it
    ...(collab() ? [{label: tr('Share folder…'), icon: 'users', dis: !own, sub: own ? '' : noOwn, fn: () => lf_share(f)}] : []),  // 2.22.0 (#740); 2.352.0 E (#2748): the one Share dialog
    {label: tr('Folder settings…'), icon: 'sliders', fn: () => folderPropsModal(f)},  // 2.29.0 (#1030 / #929)
    ...(theirs ? [] : [{label: tr('New subfolder…'), icon: 'folder', fn: () => newFolder(null, f)}]),
    ...(theirs ? [] : [{label: tr('Rename'), icon: 'edit', fn: async () => {
      const n = ((await askPrompt(tr('Rename folder'), fName(f), {ok: tr('Rename')})) || '').trim().split(FSEP).join('∕'); if (!n || n === fName(f)) return;
      folderMove(f, sub ? fParent(f) + FSEP + n : n);
    }}]),
    // move into another folder (subfolders, and folders without subfolders) / out to the top level
    ...(into.length && !theirs ? [{label: sub ? tr('Move to another folder…') : tr('Move into a folder…'), icon: 'folder', fn: () => menu(anchorOf(), into.map(t => ({label: fDisp(t), icon: 'folder', fn: () => lf_moveInto(f, t)})))}] : []),
    ...(sub && !theirs ? [{label: tr('Move to the top level'), icon: 'outdent', fn: () => lf_moveInto(f, '')}] : []),
    ...(theirs ? [] : ['-', {label: tr('Dissolve folder (projects stay)'), icon: 'trash', cls: 'flag-5', fn: async () => {
      if (!await askConfirm(tr('Dissolve folder “{0}”?', fDisp(f)), hasSubs ? (sub ? tr('Its projects and subfolders move up to {0}.', fDisp(fParent(f))) : tr('The projects stay; its subfolders become top-level folders.')) : sub ? tr('Its projects move up to {0}.', fDisp(fParent(f))) : tr('The projects stay.'), {ok: tr('Dissolve')})) return;
      await api('POST', '/api/folders/delete', {name: f}); await load(); render();
    }}]),
  ];
}
// 2.352.0 E (#2748): folder f with its lists and subfolders into folder `into` ('' = the top level), any depth; the server
// moves its node, its shares go along (rights at runtime), the settings follow the path
async function lf_moveInto(f, into, place) {
  if (into === fParent(f) && !place) return;
  if (into && fUnder(into, f)) { toast(tr('A folder cannot go into itself')); return; }
  { const m = into && folderLists(into).find(l => l.mirrored); if (m) { toast(mirroredMsg(m)); return; } }  // 2.27.0 (#988)
  const to = (into ? into + FSEP : '') + fName(f);
  if (to !== f && !await folderMove(f, to, into ? tr('Moved {0} to folder {1}', qn(fName(f)), fDisp(into)) : tr('{0} is a top-level folder now', qn(fName(f))), true)) return;
  if (place && folderNames().includes(to)) {  // before / after a sibling there
    const sibs = folderNames().filter(x => fParent(x) === into && x !== to), i = sibs.indexOf(place.at);
    sibs.splice(i < 0 ? sibs.length : i + (place.after ? 1 : 0), 0, to);
    await saveFolders(fOrderWith(into, sibs)).catch(() => {});
  }
  if (to !== f) load().then(() => render()).catch(() => {});
}
// the tree's handlers (areas.js sbb_treeReg, registered by the sidebar's draw: areas.js loads after this file): ids are the
// folder paths, par = the parent's path ('' = the top level)
const LF_TREE_H = {
  move: (f, into) => lf_moveInto(f, into),
  order: (f, o) => lf_moveInto(f, 'into' in o ? o.into : fParent(f), {at: o.before ?? o.after, after: o.after != null}),
  menu: f => folderMenuItems(f),
};
// 2.352.0 E (#2748): "Share folder…" = the one Share dialog of the file store on the folder's node (people, groups, several
// agents, a list role each); what only the projects have (default agent, notifications, public link, owner) stays in the
// folder's own dialog, one link away. Someone else's folder / no node (offline): the folder's own dialog as before.
async function lf_share(f) {
  const nid = folderLists(f).some(l => l.mirrored) ? null : await lf_ensure(f);
  if (!nid) { folderShareModal(f); return; }
  fs_shareDialog(nid, {listRole: true, org: false, hint: tr('Applies at runtime to every project in the folder, also ones added later; moving a project out or ending the share takes it away again.'),
    onChange: () => load().then(() => render()).catch(() => {}),
    extra: box => { box.innerHTML = `<div class="row lfshx"><span class="muted">${esc(tr('Default agent, notifications, public link and owner'))}</span><span class="spacer"></span><button type="button" class="linkbtn" data-m="lf-more">${ic('sliders', 's')} ${tr('More')}</button></div>`;
      $('[data-m="lf-more"]', box).addEventListener('click', () => { const md = box.closest('.modal'); if (md) modalSub(md, () => folderShareModal(f, {back: true})); else folderShareModal(f); }); }});
}
// 2.22.0 (#740) / 2.41.0 (#1420): sharing a whole folder -> folderShareModal (sharedlg.js)
// the sidebar order (+ folder moves) in one request, as one history step (label: what it was)
const listOrderNow = () => S.lists.filter(l => !l.is_inbox).sort((a, b) => (a.sort || 0) - (b.sort || 0) || a.id - b.id).map(l => l.id);
async function saveListOrder(order, folder, label) {
  const adopt = folder ? await lmFolderAsk(folder) : [];  // 2.39.1 (#1188): the folder's workspace / agent only after asking
  if (adopt === null) { renderSide(); return null; }
  const before = listOrderNow(), f0 = folder ? Object.fromEntries(Object.keys(folder).map(id => [id, listById(+id)?.folder || ''])) : null;
  const rest = S.lists.filter(l => !l.is_inbox && !order.includes(l));
  order.concat(rest).forEach((l, i) => { l.sort = i; });
  if (folder) for (const [id, f] of Object.entries(folder)) listById(+id).folder = f;
  S.lists.sort((a, b) => b.is_inbox - a.is_inbox || a.sort - b.sort || a.id - b.id);
  renderSide();
  const ids = order.concat(rest).map(l => l.id);
  await api('POST', '/api/lists/reorder', {ids, folder, ...(adopt.length ? {folder_adopt: adopt} : {})});
  const same = before.join() === ids.join() && (!folder || Object.keys(folder).every(k => f0[k] === folder[k]));
  if (same) return null;
  const go = (to, tf, from, ff) => async () => {
    const r = await api('POST', '/api/lists/reorder', {ids: to, ...(tf ? {folder: tf} : {}), _prev: {ids: from, ...(ff ? {folder: ff} : {})}});
    return {skipped: (r.conflicts || []).map(c => c.field === 'folder' ? `${lname(listById(c.id)) || '?'}: ${tr('Folder')}` : tr('Project order'))};
  };
  return histAdd({label: label || tr('Projects reordered'), undo: go(before, f0, ids, folder), redo: go(ids, folder, before, f0)});
}
// 2.27.0 (#991): to the very top / bottom of its folder (keyboard, the list's menu in the sidebar)
function moveListEnd(id, dir) {
  const order = sideOrder(), l = order.find(x => x.id === id); if (!l) return;
  if (l.mirrored) { toast(mirroredMsg(l)); return; }
  const same = order.filter(x => (x.folder || '') === (l.folder || '')), j = dir < 0 ? order.indexOf(same[0]) : order.indexOf(same[same.length - 1]);
  if (order[j] === l) return;
  order.splice(order.indexOf(l), 1); order.splice(dir < 0 ? j : order.indexOf(same[same.length - 1]) + 1, 0, l);
  saveListOrder(order, undefined, tr('Moved project {0}', qn(lname(l))));
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
  saveListOrder(order, undefined, tr('Moved project {0}', qn(lname(listById(id)))));
}
// sidebar drag & drop (desktop): lists before lists, lists into folders (header or empty body), lists out of folders (onto
// the "Projects" header). 2.352.0 E (#2748): a folder is a node of the sidebar tree (areas.js sbb_treeReg 'lf'): it is
// dragged, sorted and given its menu there
let listDrag = null;
document.addEventListener('dragstart', e => {
  const r = e.target.closest && e.target.closest('#side .srow[data-list][draggable="true"]');
  if (r) { listDrag = +r.dataset.list; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'list:' + listDrag); }
});
const sideDropTarget = (el, y = null) => !el?.closest ? null : el.closest('#side .srow[data-list], #side .fhead[data-folder], #side .fempty, #side .shead.lroot') || sb_sideEnd(el, y);
// 2.46.1 (#1612 #1635): the targets in their order (list rows, sections, board columns) and the pointer (clientY, or clientX
// for columns): the target under it or, in a gap or up to `slack` px past the last one, the nearest; after = the pointer is
// past its middle (so the last one can be passed: dropped at the very end). null = outside.
function sb_dropNear(els, pos, axis = 'y', slack = 24) {
  const vis = els.filter(x => x.getBoundingClientRect().height > 0); if (!vis.length || pos == null) return null;
  const lo = axis === 'y' ? 'top' : 'left', hi = axis === 'y' ? 'bottom' : 'right', R = vis.map(x => x.getBoundingClientRect());
  if (pos < R[0][lo] || pos > R[R.length - 1][hi] + slack) return null;
  let i = R.findIndex(r => pos < r[hi]); if (i < 0) i = R.length - 1;
  return {el: vis[i], after: pos > (R[i][lo] + R[i][hi]) / 2};
}
// 2.46.1 (#1612): a list dragged off any row (below the last list of a folder or of the loose lists, in a gap) = the nearest list row
const sb_sideEnd = (el, y) => el.closest('#side') && sb_dropNear($$('#side .sg-lists .srow[data-list]'), y)?.el || null;
// 2.46.1 (#1612): a list dropped on its own folder's header (or on "Lists" while it has no folder) goes to the end there
function sb_listToEnd(id, f) {
  const l = listById(id), order = sideOrder(), was = order.map(x => x.id).join();
  order.splice(order.indexOf(l), 1);
  const last = order.map(x => x.folder || '').lastIndexOf(f);
  order.splice(last + 1, 0, l);
  if (order.map(x => x.id).join() !== was) saveListOrder(order, undefined, tr('Moved project {0}', qn(lname(l))));
}
// 2.27.0 (#991): the lower half of a list row = after it (so a list can go to the very end of a folder)
const sideAfter = (t, y) => !!t && t.classList.contains('srow') && y != null && (() => { const r = t.getBoundingClientRect(); return r.height > 0 && y > r.top + r.height / 2; })();
const sideMark = (t, drag, y) => {  // the same highlights for mouse and touch; false = not a valid target
  $$('#side .dropbefore, #side .dropafter, #side .drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  if (!t || (drag.list && t.dataset.list && +t.dataset.list === drag.list)) return false;
  t.classList.add(t.classList.contains('srow') ? (sideAfter(t, y) ? 'dropafter' : 'dropbefore') : 'drop');
  return true;
};
document.addEventListener('dragover', e => {
  if (!listDrag) return;
  if (sideMark(sideDropTarget(e.target, e.clientY), {list: listDrag}, e.clientY)) e.preventDefault();
});
document.addEventListener('drop', e => {
  if (!listDrag) return;
  e.preventDefault(); e.stopImmediatePropagation();
  const drag = {list: listDrag}; listDrag = null;
  $$('#side .dropbefore, #side .dropafter, #side .drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  const t = sideDropTarget(e.target, e.clientY);
  sideDrop(drag, t, sideAfter(t, e.clientY));
}, true);
// one drop of a list in the sidebar (mouse or touch): into a folder (its header or empty body), out of a folder (the
// "Projects" header), or before another list (taking over that list's folder). One request; moving into / out of a folder
// can be undone.
async function sideDrop(drag, t, after = false) {
  if (!t) return;
  const id = drag.list, l = listById(id); if (!l) return;
  if (l.mirrored) { toast(mirroredMsg(l)); return; }  // 2.27.0 (#988)
  const f0 = l.folder || '';
  const undoFolder = (f, e) => { if (f !== f0 && e && !e._said) offerUndo(folderNowShared(id, f) || (f ? tr('Moved to folder {0}', fDisp(f)) : tr('Removed from folder')), e); };  // 2.41.0 (#1428)
  if (t.classList.contains('fhead') || t.classList.contains('fempty')) { const f = (t.closest('[data-folder]') || t).dataset.folder; if (f === f0) { sb_listToEnd(id, f); return; } undoFolder(f, await setListFolder(id, f)); return; }
  if (t.classList.contains('lroot')) { if (!f0) { sb_listToEnd(id, ''); return; } undoFolder('', await setListFolder(id, '')); return; }
  const order = sideOrder(), moving = order.find(x => x.id === id), target = listById(+t.dataset.list);
  if (!moving || !target || moving === target) return;
  order.splice(order.indexOf(moving), 1);
  order.splice(order.indexOf(target) + (after ? 1 : 0), 0, moving);
  const nf = target.folder || '';
  const e = await saveListOrder(order, (moving.folder || '') !== nf ? {[moving.id]: nf} : undefined,
    (moving.folder || '') !== nf ? (nf ? tr('Moved {0} to folder {1}', qn(lname(moving)), fDisp(nf)) : tr('Took {0} out of its folder', qn(lname(moving)))) : tr('Moved project {0}', qn(lname(moving))));
  undoFolder(nf, e);
}
function folderPick(anchor, id) {
  const cur = listById(id)?.folder || '';
  menu(anchor, [{label: tr('No folder'), icon: 'list', on: !cur, fn: () => setListFolder(id, '')},
    ...folderNames().map(f => ({label: '\u2003'.repeat(fDepth(f) - 1) + fName(f), icon: 'folder', on: cur === f, fn: () => setListFolder(id, f)})),  // 2.352.0 E (#2748): any depth
    '-', {label: tr('New folder…'), icon: 'plus', fn: () => newFolder(id)}]);
}
// touch (phone drawer, tablets): long-press a list, then drag -- same targets and highlights as the mouse. Held and let go
// without moving: the list's menu (edit, type, "Move to folder…"). 2.352.0 E (#2748): a folder's hold is the tree's (areas.js).
// 2.28.0 (#976): a right-click on a list in the sidebar opens its menu (mouse; touch uses the long press below); a folder's: areas.js
document.addEventListener('contextmenu', e => {
  if (S.listReorder || e.shiftKey) return;
  const r = e.target.closest?.('#side .srow[data-list]');
  if (!r) return;
  if (e.pointerType === 'touch') { e.preventDefault(); return; }  // 2.38.0 (#1155): the long press below is the app's, no browser menu
  if (isTouch()) return;
  e.preventDefault();
  listMenu(r, +r.dataset.list);
});
let sd = null, sdHeld = false;
document.addEventListener('touchstart', e => {
  const r = e.target.closest?.('#side .srow[data-list]');
  // 2.25.0 (UX-02): in sort mode the grip drags at once; elsewhere in sort mode a touch scrolls
  const grip = S.listReorder && e.target.closest('.sgrip');
  if ((S.listReorder && !grip) || !r || e.target.closest('.iconbtn') || listById(+r.dataset.list)?.archived) { sd = null; return; }
  const p = e.touches[0];
  sd = {el: r, list: +r.dataset.list, x: p.clientX, y: p.clientY, active: false, reorder: !!grip};
  // CI of 2.223.2: a redraw of the sidebar during the hold replaces the touched row; a removed target's touchmove / touchend
  // no longer reach the document, so the row itself listens too (one handling per event, _sd)
  if (!sd.el._sdL) { sd.el._sdL = 1; sd.el.addEventListener('touchmove', sdMove, {passive: false}); sd.el.addEventListener('touchend', sdEnd); sd.el.addEventListener('touchcancel', sdEnd); }
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
function sdMove(e) {
  if (!sd || e._sd) return;
  e._sd = 1;
  const p = e.touches[0];
  if (!sd.active) { if (Math.hypot(p.clientX - sd.x, p.clientY - sd.y) > 8) { clearTimeout(sd.timer); sd = null; } return; }  // scrolling
  e.preventDefault();
  sd.moved = true; sd.lx = p.clientX; sd.ly = p.clientY;
  sdFrame(p.clientX, p.clientY);
}
document.addEventListener('touchmove', sdMove, {passive: false});
// 2.87.9 (#1965): once per frame: the ghost slides by transform, then one hit test (no layout forced by the move itself)
const sdFrame = rafThrottle((x, y) => {
  if (!sd?.active || !sd.ghost) return;
  sd.ghost.style.transform = `translateY(${y - sd.y}px)`;
  const t = sideDropTarget(document.elementFromPoint(x, y), y);
  sideMark(t, sd, y);
  const side = $('#side'), r = side.getBoundingClientRect();
  if (r.height && side.scrollBy) { if (y < r.top + 48) side.scrollBy(0, -12); else if (y > r.bottom - 48) side.scrollBy(0, 12); }
  // hovering a closed folder for a moment opens it
  const fh = t && sd.list && t.classList.contains('fhead') && t.classList.contains('closed') ? t.dataset.folder : null;
  if (fh !== sd.hover) { clearTimeout(sd.open); sd.hover = fh; if (fh) sd.open = setTimeout(() => { if (sd && sd.hover === fh) { foldSet(fh, false); renderSide(); } }, 600); }
});
function sdEnd(e) {
  if (!sd || e?._sd) return;
  if (e) e._sd = 1;
  if (sd.active) sdFrame.flush();
  clearTimeout(sd.timer); clearTimeout(sd.open);
  const st = sd; sd = null;
  if (!st.active) return;  // a tap: the row's own click (opens the list)
  if (e && e.cancelable) e.preventDefault();
  sdHeld = true; setTimeout(() => { sdHeld = false; }, 500);
  st.ghost.remove(); st.el.classList.remove('dragging');
  const t = st.moved ? sideDropTarget(document.elementFromPoint(st.lx, st.ly), st.ly) : null;
  $$('#side .dropbefore, #side .dropafter, #side .drop').forEach(x => x.classList.remove('dropbefore', 'dropafter', 'drop'));
  if (!st.moved && st.reorder) return;  // a tap on the grip
  if (!st.moved) { const el = $(`#side .srow[data-list="${st.list}"]`); if (el) listMenu(el, st.list); return; }
  if (t && e?.type === 'touchend') sideDrop({list: st.list}, t, sideAfter(t, st.ly));
}
document.addEventListener('touchend', sdEnd);
document.addEventListener('touchcancel', sdEnd);
document.addEventListener('dragend', () => { listDrag = null; });
// 2.220.0 B (#2807): a cut name in the sidebar shows in full as its tooltip (set on hover / focus, only while it is cut;
// folder names have theirs, "Open …")
const sbt_tip = e => {
  const n = e.target?.closest?.('#side .srow')?.querySelector('.n'); if (!n) return;
  if (n.scrollWidth > n.clientWidth + 1) n.title = n.textContent; else if (n.title === n.textContent) n.removeAttribute('title');
};
document.addEventListener('mouseover', sbt_tip);
document.addEventListener('focusin', sbt_tip);

// ---- 2.29.0 (#1030 / #929) folder settings: defaults of my folder for every list in it and its subfolders (workspace, agent,
// "Members may use it", tidying; 2.40.0 #1373: no "Agents may address each other" any more) next to its people and roles ("Share folder"). A new list
// in the folder gets them; on a change the existing lists follow (or only new ones); a list changed on its own keeps its
// value ("differs from the folder") until "Back to the folder" in its dialog.
const FP_ROLES = [['admin', N_('Admin')], ['edit', N_('Member')], ['participant', N_('Participant')], ['view', N_('Read-only')]];  // 2.364.0 C (#3041)
const FP_KEYS = {org_id: N_('Workspace'), agent_id: N_('Agent'), agent_members: N_('Members may see and use the agent'), agent_tidy: N_('Agent may tidy up entries'), agent_listen: N_('Agent listens in'), hide_done: N_('Hide completed'),  // 2.39.1 (#1214): hide_done
  agent_followup: N_('Agent follows up'), time_tracking: N_('Time tracking')};  // 2.41.0 (#1423): the list's texts; + agent_followup, time_tracking (#1471)
function folderEff(path) {
  const parts = String(path || '').split(FSEP).filter(Boolean), out = {};
  for (let i = 1; i <= parts.length; i++) Object.assign(out, (S.folderProps || {})[parts.slice(0, i).join(FSEP)] || {});
  return out;
}
function folderValTxt(k, v) {
  if (k === 'org_id') return wsName(v ? 'org:' + v : 'private');
  if (k === 'agent_id') return v ? agentById(v)?.name || personNameAny(v) : tr('No agent');
  if (k === 'agent_tidy') return tr(TIDY_SHORT[v] || v);
  return v ? tr('On') : tr('Off');
}
const folderSharedIn = f => (S.foldersSharedIn || []).find(x => f && (f === x.folder || f.startsWith(x.folder + FSEP)));
function folderHintHtml(l, id, folder) {
  const f = id ? l.folder || '' : folder || '';
  if (!f || (id && !isOwner(l))) return '';
  const eff = folderEff(f), keys = Object.keys(eff).filter(k => FP_KEYS[k] && (k !== 'org_id' || wsOn()));
  const own = id ? (() => { try { return JSON.parse(l.folder_own || '[]'); } catch { return []; } })().filter(k => keys.includes(k)) : [];
  const parts = [];
  // 2.352.0 C (#2751): one line (the folder and what it sets), the values and "Back to the folder" fold out; no crossed-out text
  if (keys.length) parts.push(`<details class="lfhd"><summary>${ic('folder', 's')} <span>${esc(tr('From the folder “{0}”:', fDisp(f)))} ${esc(keys.map(k => tr(FP_KEYS[k])).join(', '))}${own.length ? ' · ' + esc(tr('This project differs: {0}', own.map(k => tr(FP_KEYS[k])).join(', '))) : ''}</span></summary>`
    + `<ul class="lfhl">${keys.map(k => `<li>${esc(tr(FP_KEYS[k]))}: ${esc(folderValTxt(k, eff[k]))}${own.includes(k) ? ` <span class="muted">· ${esc(tr('Differs from the folder'))}</span>` : ''}</li>`).join('')}</ul>`
    + `${own.length ? `<button type="button" class="linkbtn" data-freset="${l.id}">${tr('Back to the folder')}</button>` : ''}</details>`);
  const sh = !id && folderSharedIn(f), mine = !id && !sh && folderShareOf(f);  // 2.41.0 (#1428): my shared folder names its people and agents
  if (mine) parts.push(`${ic('users', 's')} ${esc(folderShareSay(mine, N_('It will be shared with {0}.'), N_('It will be shared with {0} and {1}.')))} <button type="button" class="linkbtn" data-fnone="1">${tr('Create it without a folder instead')}</button>`);
  if (sh) parts.push(`${ic('users', 's')} ${esc(trn('It will be shared with everyone in the folder “{1}” ({0} person).', 'It will be shared with everyone in the folder “{1}” ({0} people).', sh.people, fDisp(sh.folder)))} <button type="button" class="linkbtn" data-fnone="1">${tr('Create it without a folder instead')}</button>`);
  return parts.join('<br>');
}
document.addEventListener('click', async e => {
  const r = e.target.closest?.('[data-freset]'), n = e.target.closest?.('[data-fnone]');
  if (r) { try { const j = await api('POST', `/api/lists/${+r.dataset.freset}/folder-reset`, {}); await load(); render(); const l = listById(+r.dataset.freset), h = $('#l-fhint'); if (h && l) { h.innerHTML = folderHintHtml(l, l.id); h.hidden = !h.innerHTML; } toast(j.skipped?.length ? j.skipped.map(x => `${tr(FP_KEYS[x.key])}: ${x.reason}`).join(' · ') : tr('Takes the folder’s settings again')); } catch { /* api() said it */ } }
  if (n) { const i = $('#l-folder'); if (i) { i.value = ''; i.dispatchEvent(new Event('input', {bubbles: true})); } }
});
document.addEventListener('input', e => {
  if (e.target.id !== 'l-folder') return;
  const h = $('#l-fhint'); if (!h || $('.lhdr', e.target.closest('.modal'))) return;  // a new list only (an existing one shows it after saving)
  h.innerHTML = folderHintHtml({}, 0, fNorm(e.target.value)); h.hidden = !h.innerHTML;
  const ws = $('#l-ws'); const fp = folderEff(fNorm(e.target.value)); if (ws && 'org_id' in fp) ws.value = fp.org_id ? String(fp.org_id) : '';
});
// 2.41.0 (#1423): like the list dialog: switches (a third state "Not set" for a folder), every change saved at once with
// "Saved · Undo", the same texts and order as the list's agent part. The agents themselves are chosen in the Share dialog
// (several per folder, #1420); here their switches, with a link there. "Apply to" stays: the existing lists follow or not.
async function folderPropsModal(f, opt = {}) {
  let info, ags = null;
  try { [info, ags] = await Promise.all([api('GET', '/api/folders/props?folder=' + encodeURIComponent(f)), collab() && agentsOn() ? api('GET', '/api/folders/agents?folder=' + encodeURIComponent(f)).catch(() => null) : null]); } catch { return; }
  const p = {...(info.props || {})}, inh = info.inherited || {};
  const ownN = (info.lists || []).filter(l => l.own.length).length, nL = (info.lists || []).length;
  const agNames = () => ags ? (ags.agents.length ? ags.agents : ags.inherited).map(a => a.name) : [];
  const hasAg = () => agNames().length > 0;
  const stTxt = k => k in p ? '' : inh[k] ? tr('As the folder above: {0}', folderValTxt(k, inh[k].value)) : tr('Not set (each project decides)');
  const effOn = k => k in p ? !!p[k] : !!inh[k]?.value;
  // a switch with a third state: not set (dimmed, says so) -> a tap sets it; "Not set" puts it back
  const fsw = (id, k, label, hint) => `<div class="fsw ${k in p ? '' : 'unset'}" data-fsw="${k}"><label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" id="${id}" data-fk="${k}" ${effOn(k) ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${esc(label)}</span></label><span class="fsst muted">${esc(stTxt(k))}</span><button type="button" class="linkbtn fsclr" data-fsclr="${k}" ${k in p ? '' : 'hidden'}>${tr('Not set')}</button></div>${hint ? `<div class="shint aghint">${hint}</div>` : ''}`;
  const sel = (id, k, opts, dis = '') => `<div class="row"><label for="${id}">${tr(FP_KEYS[k])}</label><select id="${id}" data-fk="${k}" ${dis}><option value="">${esc(inh[k] ? tr('As the folder above: {0}', folderValTxt(k, inh[k].value)) : tr('Not set (each project decides)'))}</option>${opts.map(([v, n]) => `<option value="${esc(String(v))}" ${k in p && String(p[k] === true ? 1 : p[k] === false ? 0 : p[k]) === String(v) ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>`;
  // 2.37.0 (#1158): a folder without lists of my own (e.g. only lists others shared with me): the settings hold for new lists
  const md = modal(`<div class="lhdr"><h3>${ic('sliders', 's')} ${esc(tr('Folder settings “{0}”', fDisp(f)))}</h3><span class="ssaved" role="status" aria-live="polite"></span><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    ${nL ? '' : `<div class="shint cnote fsnone">${ic('info', 's')} ${tr('Applies to new projects in this folder. Shared projects of others keep their settings.')}</div>`}
    <p class="muted">${tr('Defaults for every project in the folder, also new ones. Projects changed on their own keep their value.')}</p>
    <div class="shint">${tr('“Not set” again: the projects keep the value they have.')}</div>
    ${wsOn() ? sel('fs-ws', 'org_id', [[0, wsName('private')], ...(S.me.workspaces || []).map(w => [w.id, w.name])]) : ''}
    ${collab() && agentsOn() ? `<h4 id="fs-ag-h">${tr('Agents')}</h4>
      <div class="row fsagrow"><label>${tr('Agent')}</label><span class="fsags" id="fs-ags">${esc(agNames().join(', ') || tr('No agent'))}</span><button type="button" class="linkbtn" data-m="share-ag">${ic('users', 's')} ${tr('In the Share dialog…')}</button></div>
      <div class="shint lhint">${tr('Which agents work in this folder you choose in its Share dialog; the switches here are the defaults for its projects.')}</div>
      ${fsw('fs-am', 'agent_members', tr('Members may see and use the agent'), tr('Off: only you and project admins can chat with the agent, @mention it or assign it tasks here. Members still see what it does.') + (av_folderPersonal(f).length ? `<span class="avpers"> ${esc(av_personalHint(av_folderPersonal(f)))}</span>` : ''))}
      ${fsw('fs-af', 'agent_followup', tr('Agent follows up'), tr('Once a day the agent gets the tasks of this project that lie idle and asks about them in a comment or drafts a reminder. Nothing is sent to anyone outside. Off by default.'))}
      ${sel('fs-td', 'agent_tidy', TIDY.map(([k, n]) => [k, tr(n)]), hasAg() || 'agent_tidy' in p ? '' : 'disabled')}
      <div class="shint lhint" id="fs-tdhint">${hasAg() ? tr('Tidy up by: the agent of each project.') : tr('Add an agent in the Share dialog first.')}</div>
      ${fsw('fs-al', 'agent_listen', tr('Agent listens in'), tr('Off: the agent reacts only to an @mention, an assignment or a wake. Per agent in the Share dialog.'))}` : ''}
    <h4>${tr('Completed')}</h4>
    ${fsw('fs-hd', 'hide_done', tr('Hide completed'), '')}
    <div class="shint lhint fshdhint">${tr('Default for your projects in the folder. Shared projects of others and ones you changed yourself keep their setting.')}</div>
    ${typeof timeOn === 'function' && timeOn() ? `<h4>${tr('Time tracking')}</h4>${fsw('fs-tt', 'time_tracking', tr('Time tracking'), '')}` : ''}
    ${collab() ? `<div class="row"><label>${tr('People')}</label><button type="button" class="btn sm" data-m="people">${ic('users', 's')} ${tr('Share…')}</button></div>` : ''}
    <div class="row"><label>${tr('Repository')}</label><button type="button" class="btn sm" data-m="repos">${ic('git', 's')} ${tr('Repository…')}</button></div>
    <fieldset class="fsapply" ${nL ? '' : 'hidden'}><legend>${tr('Apply to')}</legend>
      <label class="chkl"><input type="radio" name="fs-ap" value="all" ${nL ? 'checked' : ''}> ${tr('New projects and the {0} projects in the folder', nL)}</label>
      <label class="chkl"><input type="radio" name="fs-ap" value="new" ${nL ? '' : 'checked'}> ${tr('Only new projects')}</label>
      ${ownN ? `<label class="chkl"><input type="checkbox" id="fs-force"> ${esc(trn('Also the {0} project changed on its own', 'Also the {0} projects changed on their own', ownN))}</label>` : ''}</fieldset>
    <div class="fsprev" id="fs-prev" role="status" hidden></div>
    ${pbOn() ? pbAreaHtml('folder') : ''}
    <div class="foot">${collab() ? `<button class="btn" data-m="people">${ic('users', 's')} ${tr('Share…')}</button>` : ''}<span class="spacer"></span><button class="btn pri" data-m="close">${opt.back ? ic('back', 's') + ' ' + tr('Back') : tr('Done')}</button></div>`);
  md.classList.add('fsmodal');
  if (pbOn()) pbMount(md, {folder: f});  // 2.39.0 (#1168): the folder's playbook (saved on its own)
  const saved = undo => {
    const el = $('.ssaved', md); if (!el) return;
    el.innerHTML = `${ic('check', 's')}<span>${tr('Saved')}</span>${undo ? `<button type="button" class="linkbtn" data-m="fs-undo">${tr('Undo')}</button>` : ''}`;
    el.classList.add('on'); el._undo = undo;
    clearTimeout(el._t); el._t = setTimeout(() => { el.classList.remove('on'); el._undo = null; }, 6000);
  };
  const sync = k => {  // the row of key k shows what is saved now
    const row = $(`[data-fsw="${k}"]`, md);
    if (row) { row.classList.toggle('unset', !(k in p)); $('input', row).checked = effOn(k); $('.fsst', row).textContent = stTxt(k); $('.fsclr', row).hidden = !(k in p); return; }
    const s = $(`select[data-fk="${k}"]`, md); if (s) s.value = k in p ? String(p[k] === true ? 1 : p[k] === false ? 0 : p[k]) : '';
  };
  const put = async (k, v, undo = true) => {
    const prev = k in p ? p[k] : null, er = $('#fs-prev', md);
    const body = {folder: f, props: {[k]: v}, apply: $('[name="fs-ap"]:checked', md)?.value || 'all', ...($('#fs-force', md)?.checked ? {force: true} : {})};
    let r; try { r = await api('PUT', '/api/folders/props', body); } catch { sync(k); return; }
    if (v === null) delete p[k]; else p[k] = v;
    sync(k);
    const bad = (r.lists || []).filter(l => l.skipped.length || l.own.length);
    er.innerHTML = bad.length ? `<b>${esc(trn('{0} project does not follow:', '{0} projects do not follow:', bad.length))}</b><ul>${bad.map(l => `<li>${esc(l.name)}: ${esc([...l.skipped.map(x => `${tr(FP_KEYS[x.key])} – ${x.reason}`), ...l.own.map(x => tr('{0} changed on its own', tr(FP_KEYS[x])))].join('; '))}</li>`).join('')}</ul>` : '';
    er.hidden = !bad.length;
    saved(undo ? () => put(k, prev, false) : null);
    if (v === null && nL) toast(tr('Not set: the projects keep the value they have.'));
    else if (r.changed) toast(trn('{0} project changed', '{0} projects changed', r.changed));  // 2.46.1 (#1422): the counter
    await load(); render();
  };
  md.addEventListener('change', e => {
    const t = e.target, k = t.dataset?.fk; if (!k) return;
    e.stopPropagation();
    if (t.type === 'checkbox') { put(k, t.checked).then(() => { if (k === 'agent_members' && t.checked && av_folderPersonal(f).length) toast(tr('Saved') + ' · ' + av_personalHint(av_folderPersonal(f)), undefined, 9000); }); return; }  // 2.46.6 (#1680)
    put(k, t.value === '' ? null : k === 'agent_tidy' ? t.value : +t.value);
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.fsclr) { put(b.dataset.fsclr, null); return; }
    if (b.dataset.m === 'fs-undo') { const el = $('.ssaved', md); const u = el?._undo; if (u) { el.classList.remove('on'); el._undo = null; u(); } return; }
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'people' || b.dataset.m === 'share-ag') { if (opt.back) { md.remove(); return; } modalSub(md, () => folderShareModal(f, {back: true, ...(b.dataset.m === 'share-ag' ? {focus: 'agents'} : {})})); return; }
    if (b.dataset.m === 'repos') { modalSub(md, () => folderRepoModal(f, {back: true})); return; }  // 2.33.0 (#934)
  });
  // the Share dialog (opened over this one) may have changed the agents: their names and the tidy row follow
  md.addEventListener('focusin', async () => {
    if (!ags || md._agt > Date.now() - 1500) return; md._agt = Date.now();
    try { ags = await api('GET', '/api/folders/agents?folder=' + encodeURIComponent(f)); } catch { return; }
    const n = $('#fs-ags', md); if (n) n.textContent = agNames().join(', ') || tr('No agent');
    const td = $('#fs-td', md); if (td) td.disabled = !(hasAg() || 'agent_tidy' in p);
    const h = $('#fs-tdhint', md); if (h) h.textContent = hasAg() ? tr('Tidy up by: the agent of each project.') : tr('Add an agent in the Share dialog first.');
  });
  return md;
}
// 2.47.3 (#1727): several lists marked at once. Shift-click marks a range (from the last clicked or the open list),
// Cmd/Ctrl-click adds or removes one list (like the Finder); the marked lists are the route "lists:<id>,<id>…" (one view
// of their tasks grouped by list, like a folder, with "Archive" and "Clear selection" in the header). Esc and a plain
// click clear the marks. Touch: the long-press menu's "Select" starts it; in that view a tap on a list adds / removes it.
// Dragging to reorder is untouched (a modifier click is no drag, a drag never reaches the click).
const DX = {anchor: null};
const dx_listIds = (k = S.route?.key || '') => k.startsWith('lists:') ? [...new Set(k.slice(6).split(',').map(Number).filter(id => id > 0 && listById(id) && !listById(id).archived))] : [];
// the key of the marked view from the address (the route follows a moment later; fast clicks see the newest marks)
const dx_key = () => (location.hash || '').startsWith('#lists/') ? 'lists:' + location.hash.slice(7) : S.route?.key || '';
const dx_marked = id => S.route?.mod === 'tasks' && dx_listIds().includes(id);
const dx_sideIds = () => $$('#side .srow[data-list]').map(r => +r.dataset.list).filter(id => listById(id) && !listById(id).archived);
function dx_show(ids) {
  ids = ids.filter(id => listById(id));
  if (!ids.length) return go(keyToHash(START_KEY));
  if (ids.length === 1 && !isTouch()) { DX.anchor = ids[0]; return go('l/' + ids[0]); }
  go('lists/' + ids.join(','));
}
const dx_start = id => go('lists/' + id);  // the long-press menu's "Select": the marked view with this one list
function dx_clear() {
  const ids = dx_listIds(dx_key()); DX.anchor = null;
  if (ids.length) go('l/' + ids[0]);
}
// what the click on list id with the modifier does: 'add' (Cmd / Ctrl) or 'range' (Shift)
function dx_pick(id, how) {
  const k = dx_key(), cur = dx_listIds(k), open = k.startsWith('l:') ? +k.slice(2) : null;
  const base = cur.length ? cur : open && listById(open) && !listById(open).is_inbox && !listById(open).archived ? [open] : [];
  if (how === 'range') {
    const order = dx_sideIds(), from = order.indexOf(DX.anchor ?? base[base.length - 1] ?? id), to = order.indexOf(id);
    if (from < 0 || to < 0) return dx_show([...new Set([...base, id])]);
    const rng = order.slice(Math.min(from, to), Math.max(from, to) + 1);
    return dx_show([...new Set([...base, ...rng])]);
  }
  DX.anchor = id;
  dx_show(base.includes(id) ? base.filter(x => x !== id) : [...base, id]);
}
document.addEventListener('click', e => {
  const r = e.target.closest?.('#side .srow[data-list]');
  if (!r || S.listReorder || e.target.closest('.iconbtn, [data-lsort], [data-lfolder]')) return;
  const id = +r.dataset.list, l = listById(id);
  if (!l || l.archived) return;
  const how = e.shiftKey ? 'range' : (e.metaKey || e.ctrlKey) ? 'add' : isTouch() && dx_key().startsWith('lists:') ? 'add' : '';
  if (!how) { DX.anchor = id; return; }  // a plain click opens the list (and leaves the marked view)
  if (l.is_inbox) return;
  e.preventDefault(); e.stopPropagation();
  dx_pick(id, how);
}, true);
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || !(S.route?.key || '').startsWith('lists:') || $('.modal') || $('.tsheet') || !$('#pop')?.classList.contains('hidden') || S.sel || S.multi?.size) return;
  if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName) || e.target.isContentEditable) return;
  e.preventDefault(); e.stopImmediatePropagation();
  dx_clear();
}, true);
// the header of the marked view: archive them, clear the selection
function dx_listsActs(k) {
  const ids = dx_listIds(k);
  return `<span class="dxbar tf"><button class="btn sm" data-act="dx-archive" data-ico="archive" aria-label="${esc(tr('Archive'))}" ${ids.length ? '' : 'disabled'}>${ic('archive', 's')}<span>${tr('Archive')}</span></button>`
    + `<button class="btn sm ghost" data-act="dx-clear" data-ico="x" aria-label="${esc(tr('Clear selection'))}">${ic('x', 's')}<span>${tr('Clear selection')}</span></button></span>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-act="dx-archive"], [data-act="dx-clear"]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  if (b.dataset.act === 'dx-clear') dx_clear(); else dx_archive(dx_listIds());
}, true);
// archive several lists: one question with the number, then one step back ("Undo") for all of them; lists without the
// right (not owner / list admin) are skipped and named; each list goes through PATCH /api/lists/<id> like a single one
async function dx_archive(ids) {
  const ls = ids.map(listById).filter(l => l && !l.archived && !l.is_inbox);
  if (!ls.length) return;
  const ok = ls.filter(canManage), no = ls.filter(l => !canManage(l));
  const nm = xs => xs.slice(0, 5).map(l => qn(lname(l))).join(', ') + (xs.length > 5 ? ' …' : '');
  if (!ok.length) { toast(tr('No right to archive: {0}', nm(no))); return; }
  const go2 = await askConfirm(trn('Archive {0} project?', 'Archive {0} projects?', ok.length), '', {ok: tr('Archive'),
    html: `<p>${esc(nm(ok))}</p>${no.length ? `<p class="muted">${esc(tr('Skipped (no right): {0}', nm(no)))}</p>` : ''}<p class="muted">${esc(tr('Archived projects are under “Archived” in the sidebar.'))}</p>`});
  if (!go2) return;
  const done = [], failed = [...no];
  for (const l of ok) {
    try { await api('PATCH', '/api/lists/' + l.id, {archived: 1}); done.push(l.id); } catch (x) { if (x instanceof Offline) break; failed.push(l); }
  }
  DX.anchor = null;
  if ((S.route?.key || '').startsWith('lists:')) go(keyToHash(START_KEY));
  await load().catch(() => {}); render();
  if (!done.length) { toast(tr('No right to archive: {0}', nm(failed))); return; }
  const set = (to, from) => async () => {
    const skipped = [];
    for (const id of done) {
      try { const r = await api('PATCH', '/api/lists/' + id, {archived: to, _prev: {archived: from}}); if ((r.conflicts || []).length) skipped.push(qn(lname(listById(id)) || '')); }
      catch (x) { if (x instanceof Offline) throw x; skipped.push(qn(lname(listById(id)) || '')); }
    }
    return {skipped};
  };
  const e = histAdd({label: trn('Archived {0} project', 'Archived {0} projects', done.length), undo: set(0, 1), redo: set(1, 0)});
  offerUndo(trn('{0} project archived. Find it under “Archived” in the sidebar.', '{0} projects archived. Find them under “Archived” in the sidebar.', done.length)
    + (failed.length ? ' ' + tr('Skipped (no right): {0}', nm(failed)) : ''), e);
}
