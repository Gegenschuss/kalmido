/* Kalmido web client: Editing several selected tasks at once in the task panel.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.26.0 (#936): multi-edit in the task panel
// From two selected tasks the task panel (desktop: on the right; phone: a bottom sheet the selection bar opens) shows
// "12 tasks" with the fields they have in common. A value all of them share shows as usual, different values show a grey
// "Mixed". A change applies at once to every selected task the user may change (one batch request = ONE undo step) and
// the field keeps an accent marker "changed" until the selection changes. Tags are added / removed (never replaced): a
// tag only some have is half filled, a click adds it to all, the next one removes it from all. The date can be set or
// shifted (each task by itself, so different days stay different). Title, notes, comments, subtasks and files are not
// edited for many: the panel lists the selected titles instead (a click opens that one task alone). A field the user may
// not change on some of the tasks (view-only / participant role in a shared list) is locked with the number of them.
const ME = {key: '', chg: new Set(), sheet: false, on: false};
const meTasks = () => [...S.multi].map(taskById).filter(t => t && t.id > 0);
const meKey = () => [...S.multi].sort((a, b) => a - b).join(',');
const meOneList = ts => ts.length && new Set(ts.map(t => t.list_id)).size === 1 ? ts[0].list_id : 0;
// the people who can be assigned in every list of the selection
function mePeople(ts) {
  const lids = [...new Set(ts.map(t => t.list_id))];
  let ps = listPeople(listById(lids[0]));
  for (const lid of lids.slice(1)) { const ids = new Set(listPeople(listById(lid)).map(p => p.user_id)); ps = ps.filter(p => ids.has(p.user_id)); }
  return ps;
}
const REP_PRE = () => [['', N_('None')], ['FREQ=DAILY', N_('Daily')], ['FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR', N_('Weekdays')], ['FREQ=WEEKLY', N_('Weekly')], ['FREQ=MONTHLY', N_('Monthly')], ['FREQ=YEARLY', N_('Yearly')]];
const DL_TXT = [N_('Off|deadline'), N_('Deadline'), N_('Deadline, also on Today')];
// the fields of the multi panel: label, icon, value per task (compared as JSON), its text, who may change it, the editor
function meFields(ts) {
  const lid = meOneList(ts), anyDue = ts.some(t => t.due), shared = collab() && ts.some(t => listById(t.list_id)?.shared || t.assignee_id);
  const F = [
    {k: 'date', lab: N_('Date'), icon: 'cal', get: t => t.due ? t.due + (t.due_time ? ' ' + t.due_time : '') : '', text: v => v ? dueLabel({due: v.slice(0, 10), due_time: v.slice(11) || null}) : tr('No date'), open: meDateMenu},
    ...(anyDue ? [{k: 'deadline', lab: N_('Deadline'), icon: 'flag', get: t => t.deadline || 0, text: v => tr(DL_TXT[v] || DL_TXT[0]),
      open: a => menu(a, DL_TXT.map((n, i) => ({label: tr(n), icon: i ? 'flag' : 'x', fn: () => meApply('deadline', t => t.due && (t.deadline || 0) !== i ? {deadline: i} : null, tr('Deadline'))})))}] : []),
    {k: 'priority', lab: N_('Priority'), icon: 'flag', get: t => t.priority || 0, text: v => prioWord(v),
      open: a => menu(a, [[5, N_('High')], [3, N_('Medium')], [1, N_('Low')], [0, N_('None')]].map(([p, n]) => ({label: tr(n), icon: 'flag', cls: p ? 'flag-' + p : '', fn: () => meApply('priority', t => (t.priority || 0) !== p ? {priority: p} : null, tr('Priority'))})))},
    ...(shared ? [{k: 'assignee', lab: N_('Assignee'), icon: 'user', get: t => t.assignee_group_id ? 'g' + t.assignee_group_id : t.assignee_id || 0, perm: canAssign,
      text: v => !v ? tr('Nobody') : String(v)[0] === 'g' ? (S.groups || []).find(g => 'g' + g.id === v)?.name || tr('Group') : personNameAny(v) || '?',
      open: a => menu(a, [{label: tr('Nobody'), icon: 'x', fn: () => meApply('assignee', t => t.assignee_id || t.assignee_group_id ? {assignee_id: null, assignee_group_id: null} : null, tr('Assignee'))}, '-',
        ...mePeople(ts).map(p => ({label: p.name + (S.me && p.user_id === S.me.id ? ' ' + tr('(me)') : ''), icon: 'user', fn: () => meApply('assignee', t => t.assignee_id !== p.user_id || t.assignee_group_id ? {assignee_id: p.user_id, assignee_group_id: null} : null, tr('Assignee'))}))])}] : []),
    {k: 'list', lab: N_('List'), icon: 'list', get: t => t.list_id, text: v => lname(listById(v)) || '?', perm: t => canEditList(t.list_id),
      open: a => menu(a, S.lists.filter(l => !l.archived && canEditList(l.id)).map(l => ({label: lname(l), icon: l.is_inbox ? 'inbox' : 'list', fn: () => meApply('list', t => t.list_id !== l.id ? {list_id: l.id, section_id: null} : null, tr('Moved to {0}', lname(l)))})))},
    ...(lid && S.sections.some(s => s.list_id === lid) ? [{k: 'section', lab: N_('Section'), icon: 'columns', get: t => t.section_id || 0, text: v => v ? secName(v) : tr('No section'),
      open: a => menu(a, [{label: tr('No section'), icon: 'x', fn: () => meApply('section', t => t.section_id ? {section_id: null} : null, tr('Section'))}, '-',
        ...S.sections.filter(s => s.list_id === lid).map(s => ({label: s.name, icon: 'columns', fn: () => meApply('section', t => t.section_id !== s.id ? {section_id: s.id} : null, tr('Section'))}))])}] : []),
    ...(msBulkList() ? [{k: 'milestone', lab: N_('Milestone'), icon: 'flag', get: t => t.milestone_id || 0, text: v => v ? S.tasks.get(v)?.title || '?' : tr('None'), perm: t => canEditList(t.list_id),
      open: a => menu(a, [...msOfList(lid).filter(m => m.status === 0).map(m => ({label: m.title + (m.due ? ' · ' + fmtDateLoc(m.due) : ''), icon: 'flag', fn: () => meApply('milestone', t => t.milestone_id !== m.id ? {milestone_id: m.id} : null, tr('Milestone: {0}', m.title))})),
        '-', {label: tr('No milestone'), icon: 'x', fn: () => meApply('milestone', t => t.milestone_id ? {milestone_id: null} : null, tr('Milestone removed'))}])}] : []),
    {k: 'repeat', lab: N_('Repeat'), icon: 'repeat', get: t => t.repeat || '', text: v => v ? repeatLabel(v) : tr('None'),
      open: a => menu(a, REP_PRE().map(([r, n]) => ({label: tr(n), icon: r ? 'repeat' : 'x', fn: () => meApply('repeat', t => (t.repeat || '') !== r ? {repeat: r} : null, tr('Repeat'))})))},
    ...(anyDue ? [{k: 'reminders', lab: N_('Reminder'), icon: 'bell', get: t => t.reminders || '', text: v => v ? String(v).split(',').map(remLabel).join(', ') : tr('None'),
      open: a => menu(a, [['', N_('None')], ...REM_OPTS].map(([m, n]) => ({label: tr(n), icon: m === '' ? 'x' : 'bell', fn: () => meApply('reminders', t => t.due && (t.reminders || '') !== m ? {reminders: m} : null, tr('Reminder'))})))}] : []),
    {k: 'waiting', lab: N_('Waiting on'), icon: 'hourglass', get: t => t.waiting_at ? (t.wait_note || '') + '\u0001' + (t.wait_until || '') : '', text: v => !v ? tr('Nobody') : v.split('\u0001')[0] || tr('Waiting on someone'),
      open: a => menu(a, [{label: tr('Waiting on someone…'), icon: 'hourglass', fn: () => meWaitDialog()}, {label: tr('No longer waiting'), icon: 'x', fn: () => meWait(null)}])},
    {k: 'pinned', lab: N_('Pinned'), icon: 'pin', get: t => t.pinned ? 1 : 0, text: v => v ? tr('Pinned') : tr('Not pinned'), toggle: true,
      open: () => { const on = meTasks().every(t => t.pinned) ? 0 : 1; meApply('pinned', t => (t.pinned ? 1 : 0) !== on ? {pinned: on} : null, on ? tr('Pinned') : tr('Unpin')); }},
    ...(lid ? fieldsOf(lid).map(f => meCustom(f, lid)) : [])];
  return F.map(f => ({perm: canEdit, ...f}));
}
// a custom field of the one list all selected tasks are in
function meCustom(f, lid) {
  const k = 'cf' + f.id, set = v => meApply(k, t => (t.fields?.[f.id] ?? null) !== v ? {fields: {[f.id]: v}} : null, f.name);
  const open = a => {
    if (f.type === 'select') menu(a, [{label: '–', icon: 'x', fn: () => set(null)}, ...(f.options?.options || []).map(o => ({label: o.name, fn: () => set(o.id)}))]);
    else if (f.type === 'person') menu(a, [{label: '–', icon: 'x', fn: () => set(null)}, ...listPeople(listById(lid)).map(p => ({label: p.name, icon: 'user', fn: () => set(String(p.user_id))}))]);
    else if (f.type === 'checkbox') set(meTasks().every(t => t.fields?.[f.id] === '1') ? null : '1');
    else if (f.type === 'date') dpOpen(a, {kind: 'date', value: today(), clear: true, label: f.name, onPick: v => set(v || null)});
    else askPrompt(f.name, '', {ok: tr('Apply to all')}).then(v => {
      if (v == null) return;
      let x = v.trim() || null;
      if (x && f.type === 'number') x = numIn(x);
      if (x && f.type === 'url' && !/^https?:\/\//i.test(x)) x = 'https://' + x;
      set(x);
    });
  };
  return {k, lab: f.name, raw: true, icon: FT_ICON[f.type] || 'edit', get: t => t.fields?.[f.id] ?? '', text: v => fieldText(f, v, lid) || '–', open, toggle: f.type === 'checkbox'};
}
function meDateMenu(a) {
  const ts = meTasks(), times = new Set(ts.filter(t => t.due).map(t => t.due_time || ''));
  const setDue = v => meApply('date', t => t.due !== v ? {due: v} : null, v ? tr('Date: {0}', dayLabel(v)) : tr('No date'));
  menu(a, [
    {label: tr('Today'), icon: 'sun', fn: () => setDue(today())},
    {label: tr('Tomorrow'), icon: 'sunrise', fn: () => setDue(addDays(today(), 1))},
    {label: tr('Next week (Mon)'), icon: 'week', fn: () => setDue(nextWeekday(1))},
    {label: tr('Pick a date…'), icon: 'cal', fn: () => dpOpen(a, {kind: 'date', value: today(), clear: false, label: tr('Pick a date…'), onPick: v => { if (v) setDue(v); }})},
    ...(ts.some(t => t.due) ? [{label: tr('Time…'), icon: 'clock', fn: () => dpOpen(a, {kind: 'time', value: times.size === 1 ? [...times][0] : '', label: tr('Time'),
      onPick: v => meApply('date', t => t.due && (t.due_time || '') !== (v || '') ? {due_time: v || null} : null, v ? tr('Time: {0}', fmtTimeLoc(v)) : tr('No time'))})}] : []),
    '-', {label: tr('No date|clear'), icon: 'ban', fn: () => setDue(null)}]);
}
// the relative shift: every dated task by n days from its own date (a range keeps its length)
function meShift(n) {
  meApply('date', t => t.due ? {due: addDays(t.due, n), ...(t.start ? {start: addDays(t.start, n)} : {})} : null, tr('Date shifted: {0}', meShiftLab(n)));
}
const meShiftLab = n => n % 7 === 0 ? (n > 0 ? '+' : '−') + trn('{0} week', '{0} weeks', Math.abs(n / 7)) : (n > 0 ? '+' : '−') + trn('{0} day', '{0} days', Math.abs(n));
// one change for all the tasks the user may change: one batch request (patch when every task gets the same, else
// patch_each), one history step
async function meApply(k, fn, lab) {
  const ts = meTasks(), f = meFields(ts).find(x => x.k === k), may = ts.filter(t => (f?.perm || canEdit)(t));
  const items = {};
  for (const t of may) { const d = fn(t); if (d) items[t.id] = d; }
  const ids = Object.keys(items).map(Number);
  ME.chg.add(k);
  if (!ids.length) { meRender(); return; }
  const one = new Set(Object.values(items).map(x => JSON.stringify(x))).size === 1;
  const snaps = ids.flatMap(withKids);
  let j;
  try { j = await api('POST', '/api/tasks/batch', one ? {ids, action: 'patch', data: items[ids[0]]} : {ids, action: 'patch_each', data: {items}}); } catch { meRender(); return; }
  if (j?.errors?.length) toast(j.errors[0]);
  await load(); render();
  if (j?.errors?.length && !j.count) return;
  const pairs = snaps.filter(b => ids.includes(b.id)).map(b => [b, snapTask(S.tasks.get(b.id))]);
  const e = histFields(trn('{1}: {0} task changed', '{1}: {0} tasks changed', ids.length, lab), pairs, {res: j, fields: [...UNDO_FIELDS, 'tags', 'ltags', 'fields']});
  const msg = trn('{0} task changed', '{0} tasks changed', ids.length);
  if (e) offerUndo(msg, e); else toast(msg);
}
// tags: add to all / remove from all. A list tag of a task's list goes into its list tags, any other name is a personal tag
const meHas = (t, g) => hasTag(t, g);
function meTag(g, add) {
  const lo = g.toLowerCase();
  meApply('tags', t => {
    if (add) {
      if (meHas(t, g)) return null;
      const lt = listTags(t.list_id).find(x => x.name.toLowerCase() === lo);
      return lt ? {ltags: [...(t.ltags || []), lt.name]} : {tags: [...t.tags, g]};
    }
    const tg = t.tags.filter(x => x.toLowerCase() !== lo), lt = (t.ltags || []).filter(x => x.toLowerCase() !== lo);
    return tg.length === t.tags.length && lt.length === (t.ltags || []).length ? null : {...(tg.length !== t.tags.length ? {tags: tg} : {}), ...(lt.length !== (t.ltags || []).length ? {ltags: lt} : {})};
  }, add ? tr('Tag added: {0}', '#' + g) : tr('Tag removed: {0}', '#' + g));
}
// waiting on someone (its own endpoint per task): one history step that puts every task back
async function meWait(set) {
  const ts = meTasks().filter(canEdit).filter(t => set || t.waiting_at);
  ME.chg.add('waiting');
  if (!ts.length) { meRender(); return; }
  const before = new Map(ts.map(t => [t.id, t.waiting_at ? {note: t.wait_note || '', until: t.wait_until || null} : null]));
  const apply = async m => {
    const skipped = [];
    for (const [id, v] of m) { try { putTask(await api(v ? 'PUT' : 'DELETE', `/api/tasks/${id}/waiting`, v || undefined)); } catch { skipped.push(histTitle(id)); } }
    return {skipped, q: null, none: skipped.length === m.size};
  };
  const r = await apply(new Map(ts.map(t => [t.id, set])));
  render();
  if (r.none) return;
  const lab = set ? trn('Waiting on someone: {0} task', 'Waiting on someone: {0} tasks', ts.length) : trn('No longer waiting: {0} task', 'No longer waiting: {0} tasks', ts.length);
  offerUndo(lab, histAdd({label: lab, snaps: ts.map(snapTask), ids: ts.map(t => t.id), undo: () => apply(before), redo: () => apply(new Map(ts.map(t => [t.id, set])))}));
}
function meWaitDialog() {
  const ts = meTasks(), notes = new Set(ts.map(t => t.wait_note || '')), n0 = notes.size === 1 ? [...notes][0] : '';
  const md = modal(`<h3>${tr('Waiting on someone')}</h3>
    <div class="shint">${trn('For {0} selected task.', 'For all {0} selected tasks.', ts.length)}</div>
    <div class="row"><label for="mw-note">${tr('Waiting on')}</label><input id="mw-note" maxlength="300" value="${esc(n0)}" placeholder="${esc(tr('who or what, e.g. offer from the carpenter'))}" enterkeyhint="done"></div>
    <div class="row"><label for="mw-until">${tr('Follow up on')}</label>${dateIn('mw-until', addDays(today(), 7), {min: today(), label: tr('Follow up on'), empty: tr('none')})}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Save')}</button></div>`);
  md.classList.add('waitmodal');
  const save = () => { const v = {note: $('#mw-note', md).value.trim(), until: $('#mw-until', md).value || null}; md.remove(); meWait(v); };
  md.addEventListener('click', e => { const b = e.target.closest('[data-m]'); if (!b) return; if (b.dataset.m === 'close') md.remove(); else if (b.dataset.m === 'ok') save(); });
  $('#mw-note', md).addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
  if (!isMobile()) setTimeout(() => $('#mw-note', md).focus(), 50);
}
// ---- the panel
function meRow(f, ts) {
  const vals = ts.map(f.get), same = new Set(vals.map(v => JSON.stringify(v ?? null))).size === 1;
  const lock = ts.filter(t => !f.perm(t)).length, chg = ME.chg.has(f.k), lab = f.raw ? f.lab : tr(f.lab);
  const txt = same ? f.text(vals[0]) : tr('Mixed');
  const shift = f.k === 'date' && !lock ? `<span class="meshift" role="group" aria-label="${esc(tr('Shift each date'))}">${[-1, 1, 7].map(n => `<button type="button" class="btn sm" data-act="me-shift" data-n="${n}" ${ts.some(t => t.due) ? '' : 'disabled'} title="${esc(tr('Shift each date by {0}', meShiftLab(n)))}" aria-label="${esc(tr('Shift each date by {0}', meShiftLab(n)))}">${esc(meShiftLab(n))}</button>`).join('')}</span>` : '';
  return `<div class="mef ${chg ? 'chg' : ''} ${lock ? 'lock' : ''}" data-k="${esc(f.k)}"><span class="mel">${ic(f.icon, 's')}<span>${esc(lab)}</span></span>
    <button type="button" class="mev ${same ? '' : 'mixed'} ${f.toggle && same && vals[0] && vals[0] !== '' ? 'on' : ''}" data-act="me-f" data-f="${esc(f.k)}" ${f.toggle ? `aria-pressed="${same ? !!vals[0] : 'mixed'}"` : 'aria-haspopup="menu"'} ${lock ? 'disabled' : ''} aria-label="${esc(lab + ': ' + txt)}"><span class="mevt">${esc(txt)}</span>${f.toggle ? '' : ic('chev', 's')}</button>
    ${chg ? `<span class="mechg">${esc(tr('changed'))}</span>` : ''}${shift}
    ${lock ? `<span class="melock">${ic('lock', 's')}${esc(trn('No permission for {0} task', 'No permission for {0} tasks', lock))}</span>` : ''}</div>`;
}
function meTagsHtml(ts) {
  const all = new Map();
  for (const t of ts) for (const g of [...(t.ltags || []), ...t.tags]) { const k = g.toLowerCase(); if (!all.has(k)) all.set(k, g); }
  const lock = ts.filter(t => !canEdit(t)).length, chg = ME.chg.has('tags');
  const chips = [...all.values()].sort((a, b) => a.localeCompare(b)).map(g => {
    const n = ts.filter(t => meHas(t, g)).length, full = n === ts.length;
    return `<button type="button" class="metag ${full ? 'on' : 'half'}" data-act="me-tag" data-tag="${esc(g)}" aria-pressed="${full ? 'true' : 'mixed'}" ${lock ? 'disabled' : ''} title="${esc(full ? tr('All have {0} · click: remove from all', '#' + g) : tr('{0} of {1} have {2} · click: add to all', n, ts.length, '#' + g))}"><i aria-hidden="true"></i>#${esc(g)}</button>`;
  }).join('');
  return `<div class="dsec metags ${chg ? 'chg' : ''} ${lock ? 'lock' : ''}" data-k="tags"><h5>${ic('tag', 's')}${tr('Tags')}${chg ? `<span class="mechg">${esc(tr('changed'))}</span>` : ''}</h5>
    <div class="metagl">${chips}${lock ? '' : `<input id="me-tag" placeholder="${esc(tr('+ Tag'))}" aria-label="${esc(tr('Add a tag to all'))}" list="me-taglist" enterkeyhint="done" autocomplete="off"><datalist id="me-taglist">${[...new Set([...S.tasks.values()].flatMap(x => x.tags))].map(g => `<option value="${esc(g)}">`).join('')}</datalist>`}</div>
    ${lock ? `<span class="melock">${ic('lock', 's')}${esc(trn('No permission for {0} task', 'No permission for {0} tasks', lock))}</span>` : ''}</div>`;
}
function meHtml() {
  const ts = meTasks(), mob = isMobile();
  const fields = meFields(ts).map(f => meRow(f, ts)).join('');
  return `<div class="dtop metop"><h2 class="mecount" id="me-h">${esc(trn('{0} task', '{0} tasks', ts.length))}</h2><span class="spacer"></span>
      ${propInboxSel() ? `<button type="button" class="iconbtn" data-act="mb-sort" title="${esc(propWith(N_('Sort with {0}…'), N_('Sort with an agent…')))}" aria-label="${esc(propWith(N_('Sort with {0}…'), N_('Sort with an agent…')))}">${ic('bot')}</button>` : ''}
      <button type="button" class="iconbtn" data-act="mb-all" title="${esc(tr('Select all'))}" aria-label="${esc(tr('Select all'))}">${ic('all')}</button>
      ${mob ? `<button type="button" class="btn sm pri" data-act="me-sheet-close">${tr('Done')}</button>` : `<button type="button" class="iconbtn dclose" data-act="mb-close" title="${esc(tr('Clear selection') + ' (Esc)')}" aria-label="${esc(tr('Clear selection'))}">${ic('x')}</button>`}</div>
    <div class="dbody mebody" role="group" aria-labelledby="me-h">
      <p class="muted mehint">${esc(tr('Changes apply to all selected tasks at once.'))}</p>
      <div class="mefields">${fields}</div>
      ${meTagsHtml(ts)}
      <div class="dsec melist"><h5>${tr('Selected tasks')}</h5><ul>${ts.map(t => `<li data-id="${t.id}"><button type="button" class="metl" data-act="open-id" data-id="${t.id}" title="${esc(tr('Open only this task'))}">${t.status ? ic('check', 's') : ''}<span>${esc(t.title)}</span></button><button type="button" class="iconbtn" data-act="me-drop" data-id="${t.id}" title="${esc(tr('Remove from the selection'))}" aria-label="${esc(tr('Remove {0} from the selection', t.title))}">${ic('x', 's')}</button></li>`).join('')}</ul></div>
    </div>`;
}
function meRender() { const d = $('#detail'); if (!d || !ME.on) return; keepFocus(d, () => setHtml(d, meHtml())); }
// called with every change of the selection (renderMultiBar): shows / updates / closes the multi panel
function meSync() {
  const k = meKey();
  if (k !== ME.key) { ME.key = k; ME.chg = new Set(); }
  if (S.multi.size < 2) ME.sheet = false;
  const d = $('#detail'); if (!d) return;
  const want = S.multi.size >= 2 && meTasks().length >= 2 && !S.me?.kid && (!isMobile() || ME.sheet);
  if (!want) { if (ME.on) meClose(); return; }
  if (S.sel) {  // the single task gives the panel to the selection
    flushSaves(); S.sel = null; S.tl = {id: null}; S.cedit = null; S.editLink = false; mentionClose();
    $$('.trow.sel').forEach(r => r.classList.remove('sel'));
  }
  const first = !ME.on; ME.on = true;
  d.classList.add('multi'); d.classList.remove('hidden'); d.setAttribute('aria-label', tr('Edit the selected tasks'));
  if (!$('#app').classList.contains('detail-open')) { $('#app').classList.add('detail-open'); fitLayout(); }
  if (first || !(d.contains(document.activeElement) && editFocused())) meRender();
  if (first) { d.scrollTop = 0; requestAnimationFrame(() => d.classList.add('open')); if (isMobile()) setTimeout(() => { if (ME.on) { d.tabIndex = -1; try { d.focus({preventScroll: true}); } catch { d.focus(); } } }, 60); }
}
function meClose() {
  ME.on = false; ME.sheet = false;
  const d = $('#detail'); d.classList.remove('multi');
  if (S.sel) return;  // a single task took the panel
  d.classList.remove('open'); $('#app').classList.remove('detail-open'); fitLayout();
  setTimeout(() => { if (!S.sel && !ME.on) { d.classList.add('hidden'); d.innerHTML = ''; } }, isMobile() ? 230 : 0);
}
// a single task opens (plain click, a title of the panel): the selection ends
function meEnd() {
  if (!S.multi.size && !S.multiMode && !ME.on) return;
  S.multi.clear(); S.multiMode = false; ME.on = false; ME.sheet = false;
  $('#detail')?.classList.remove('multi');
  $$('#view .trow.msel').forEach(r => r.classList.remove('msel'));
  renderMultiBar();
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act^="me-"]'); if (!a) return;
  const act = a.dataset.act;
  if (act === 'me-f') { const f = meFields(meTasks()).find(x => x.k === a.dataset.f); if (f && !a.disabled) f.open(a); }
  else if (act === 'me-shift') meShift(+a.dataset.n);
  else if (act === 'me-tag') { const g = a.dataset.tag; meTag(g, !meTasks().every(t => meHas(t, g))); }
  else if (act === 'me-drop') { S.multi.delete(+a.dataset.id); $$(`#view .trow[data-id="${a.dataset.id}"]`).forEach(r => r.classList.remove('msel')); renderMultiBar(); }
  else if (act === 'me-sheet') { ME.sheet = true; meSync(); }
  else if (act === 'me-sheet-close') { ME.sheet = false; meClose(); }
});
document.addEventListener('keydown', e => {
  if (e.target?.id !== 'me-tag' || e.key !== 'Enter') return;
  e.preventDefault();
  const g = e.target.value.trim().replace(/^#/, ''); if (!g) return;
  e.target.value = '';
  meTag(g, true);
});
document.addEventListener('change', e => {  // a pick from the tag suggestions
  if (e.target?.id !== 'me-tag') return;
  const g = e.target.value.trim().replace(/^#/, ''); if (!g || !isTouch()) return;
  e.target.value = ''; meTag(g, true);
});
// Shift- / Ctrl- / Cmd-click on a row selects: no text selection, no drag start
document.addEventListener('mousedown', e => {
  if (e.button === 0 && (e.shiftKey || e.ctrlKey || e.metaKey) && e.target.closest?.('#view .trow') && !e.target.closest('input,textarea,[contenteditable="true"],a[href]')) e.preventDefault();
});
