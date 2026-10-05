/* Kalmido web client: Modals: the app's own dialogs, the list dialog and the share dialog.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ modals
function modal(html) {
  const m = document.createElement('div');
  m.className = 'modal';
  m.innerHTML = `<div class="card">${html}</div>`;
  m.addEventListener('mousedown', e => { if (e.target === m) m.remove(); });
  document.body.appendChild(m);
  vvSync();
  modalA11y(m);
  return m;
}
// 2.16.0 (#473): every dialog is a modal dialog for screen readers (role, name from its heading), keeps Tab inside, gets the
// focus (its own field if it focuses one, else the dialog itself, so a phone keyboard does not pop up) and gives it back to
// where it came from when it closes (Esc, backdrop, a button, code)
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"]),[contenteditable="true"]';
const focusables = root => $$(FOCUSABLE, root).filter(x => x.offsetParent !== null || x === document.activeElement || !x.getClientRects);
function modalA11y(m) {
  const card = m.querySelector('.card');
  if (!m.hasAttribute('role')) m.setAttribute('role', 'dialog');
  m.setAttribute('aria-modal', 'true');
  const h = card && card.querySelector('h1,h2,h3,h4');
  if (h && !m.hasAttribute('aria-labelledby')) { if (!h.id) h.id = 'mh-' + Math.random().toString(36).slice(2, 8); m.setAttribute('aria-labelledby', h.id); }
  const prev = document.activeElement;
  m.addEventListener('keydown', e => {
    if (e.key !== 'Tab' || e.defaultPrevented) return;
    const f = focusables(m).filter(x => x.tabIndex >= 0 || x === document.activeElement); e.preventDefault(); if (!f.length) return;
    // 2.19.0: the dialog moves the focus itself (DOM order, wraps): after an earlier dialog was removed, Firefox's own
    // navigation could start from a stale point and bounce between two buttons or leave the dialog
    const i = f.indexOf(document.activeElement);
    (i < 0 ? f[e.shiftKey ? f.length - 1 : 0] : f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length]).focus();
  });
  setTimeout(() => {
    if (!document || !m.isConnected || m.contains(document.activeElement) || $('#pop:not(.hidden)')?.contains(document.activeElement)) return;
    if (card) { card.tabIndex = -1; try { card.focus({preventScroll: true}); } catch { card.focus(); } }
  }, 90);
  onRemove(m, () => {
    if (!document) return;  // the window is gone
    const a = document.activeElement;
    if (prev && prev.isConnected && prev !== document.body && (!a || a === document.body || !a.isConnected)) { try { prev.focus({preventScroll: true}); } catch { /* gone */ } }
  });
}
// ---- UX1 (U12): the app's own dialogs instead of window.confirm / window.prompt. askConfirm resolves true / false,
// askPrompt the text or null. Esc, a click next to it and "Cancel" say no; a destructive action is red and not focused.
function onRemove(el, fn) {  // runs fn once el left the page (removed by any path: Esc, backdrop, code)
  const mo = new MutationObserver(() => { if (!el.isConnected) { mo.disconnect(); fn(); } });
  mo.observe(document.body, {childList: true});
  return mo;
}
function askDialog({title, body = '', html = '', ok, danger = false, input = null, cancel}) {
  return new Promise(res => {
    let done = false;
    const md = modal(`<form class="cdlg-f" novalidate><h3 id="cdlg-t">${esc(title)}</h3>${body || html ? `<div class="cdlg-b" id="cdlg-b">${html || esc(body)}</div>` : ''}
      ${input ? `<input id="cdlg-in" value="${esc(input.value || '')}" placeholder="${esc(input.placeholder || '')}" aria-labelledby="cdlg-t" autocomplete="off" ${input.type ? `type="${input.type}"` : ''} ${input.max ? `maxlength="${input.max}"` : ''}>` : ''}
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-cd="no">${esc(cancel || tr('Cancel'))}</button><button type="submit" class="btn ${danger ? 'danger solid' : 'pri'}" data-cd="yes">${esc(ok || tr('OK'))}</button></div></form>`);
    md.classList.add('cdlg');
    md.setAttribute('role', input ? 'dialog' : 'alertdialog'); md.setAttribute('aria-modal', 'true'); md.setAttribute('aria-labelledby', 'cdlg-t');
    if (body || html) md.setAttribute('aria-describedby', 'cdlg-b');
    const prev = document.activeElement;
    const fin = v => { if (done) return; done = true; res(v); if (md.isConnected) md.remove(); try { if (prev && prev.isConnected) prev.focus({preventScroll: true}); } catch { /* gone */ } };
    md.querySelector('form').addEventListener('submit', e => { e.preventDefault(); fin(input ? $('#cdlg-in', md).value : true); });
    md.addEventListener('click', e => { if (e.target.closest('[data-cd="no"]')) fin(input ? null : false); });
    md.addEventListener('keydown', e => {  // keep Tab inside the dialog
      if (e.key !== 'Tab') return;
      const f = $$('input,button', md).filter(x => !x.disabled); if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    });
    onRemove(md, () => fin(input ? null : false));
    setTimeout(() => { const f = input ? $('#cdlg-in', md) : $(danger ? '[data-cd="no"]' : '[data-cd="yes"]', md); f?.focus(); if (input) f?.select?.(); }, 30);
  });
}
const askConfirm = (title, body = '', o = {}) => askDialog({title, body, ...o});
const askPrompt = (title, value = '', o = {}) => askDialog({title, ...o, input: {value, ...(o.input || {})}, ok: o.ok || tr('OK')});
const LCOLORS = ['', '#2dd4bf', '#6d8cff', '#6ee7b7', '#4ade80', '#f5b041', '#f87171', '#c084fc', '#f472b6', '#94a3b8'];
const EMOJIS = ['📥', '📌', '⭐', '🔥', '✅', '📅', '⏰', '🎯', '💡', '🧠', '🏠', '🏡', '🛒', '🍎', '🍳', '☕', '💼', '🖥️', '💻', '📱', '📞', '✉️', '📝', '📚', '📖', '✏️', '🎓', '💰', '💳', '🧾', '🏦', '📊', '🚗', '🚲', '✈️', '🏖️', '🧳', '🗺️', '🎁', '🎉', '🎵', '🎹', '🎧', '🎬', '📷', '🎨', '🌀', '🧵', '🛠️', '🔧', '🏃', '🏋️', '🧘', '❤️', '🩺', '💊', '👶', '🧒', '👪', '🐶', '🐱', '🐭', '🌱', '🌻', '☀️', '🌙', '♻️', '🔒', '🤶', '🎄'];
const EMO_RE = /^((?:\p{Extended_Pictographic}|\p{Emoji_Modifier}|\uFE0F|\u200D)+)\s*/u;
// list type (1.2): the choices, a hint per type (project: only the features whose module is on), the menu
// 2.7.2 (#414): two types only; the old checklist type is the list option "Show completed at the bottom" (lists.checklist)
const LKINDS = [['list', N_('List')], ['project', N_('Project')]];
const LKIND_ICON = {list: 'list', checklist: 'cart', project: 'pulse'};
// 2.4.0 (#243): project types = built-in project templates (server: PTYPES); '' = a blank project. Offered in the "New list"
// dialog (type Project, next to the person's own list templates, #328), the setup and the welcome tour.
const PTYPE_UI = [['', N_('Blank'), 'list', N_('An empty project: add sections and fields as you go')],
  ['agency', N_('Agency'), 'brief', N_('Request, concept, production, approval, billing; client and budget fields; time tracking')],
  ['software', N_('Software / AI dev'), 'code', N_('Backlog to Done on a board, bug / feature tickets, dependencies, a repository and coding agents')],
  ['private', N_('Personal|project type'), 'home', N_('Ideas, planning, to do: a light project without fields')]];
const MOD_NAMES = {time: N_('Time tracking'), fields: N_('Custom fields'), kanban: N_('Kanban'), deps: N_('Dependencies')};
// after a project type switched modules on for this person: say which
function modulesOnToast(on) { if (on?.length) toast(tr('Switched on for you: {0}', on.map(m => tr(MOD_NAMES[m] || m)).join(', '))); }
// 2.4.0 (#243): a new Software / AI dev project: the next steps (repository of the 2.2.0 Git integration, a coding agent)
async function projectNextSteps(lid) {
  let ags = [];
  if (collab()) { try { ags = (await api('GET', '/api/users')).users.filter(u => u.agent && !u.disabled); } catch { /* offline */ } }
  const md = modal(`<h3>${ic('code', 's')} ${tr('Next steps for {0}', esc(lname(listById(lid))))}</h3>
    <div class="nsteps"><div class="nstep"><b>${tr('Connect a repository')}</b><span class="muted">${tr('GitHub, GitLab, Gitea / Forgejo or Bitbucket: pull requests, commits and CI show up at the tickets, “fixes #id” completes them.')}</span><button class="btn sm" data-m="repo">${ic('git', 's')} ${tr('Repository…')}</button></div>
    ${ags.length ? `<div class="nstep"><b>${tr('Share with a coding agent')}</b><span class="muted">${tr('Optional: the agent gets the tickets of this list as events, works in the repository and asks for approval before merging.')}</span><div class="row"><select id="ns-agent" aria-label="${esc(tr('Agent'))}">${ags.map(a => `<option value="${a.id}">${esc(a.display_name)}</option>`).join('')}</select><button class="btn sm" data-m="share">${ic('bot', 's')} ${tr('Share')}</button></div></div>` : ''}</div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('nsmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') md.remove();
    if (b.dataset.m === 'repo') { md.remove(); listModal(lid); setTimeout(() => { const r = $('.lmodal #l-repos-h'); r?.scrollIntoView?.({block: 'start'}); }, 150); }
    if (b.dataset.m === 'share') {
      try { await api('PUT', `/api/lists/${lid}/members`, {user_id: +$('#ns-agent', md).value, role: 'edit'}); } catch { return; }
      b.disabled = true; b.textContent = tr('Shared'); await load(); render();
    }
  });
}
// 2.4.0 (#340): the note templates of new bug / feature tickets of a list (empty = the built-in text)
function ticketTplModal(lid) {
  const l = listById(lid); if (!l) return;
  let cur = {}; try { cur = JSON.parse(l.ticket_tpl || '{}') || {}; } catch { /* bad json */ }
  const def = {bug: tr('**Steps to reproduce**\n1. \n\n**Expected**\n\n**Actual**\n\n**Environment**\n\n**Version / found in**\n'), feature: tr('**Goal**\n\n**Acceptance criteria**\n- [ ] \n')};
  const md = modal(`<h3>${tr('Ticket templates')}</h3><div class="shint">${tr('New tickets of this type start with these notes (Markdown) when their notes are empty. Empty = the built-in text.')}</div>
    ${['bug', 'feature'].map(k => `<div class="row ppcol"><label for="tt-${k}">${ic(k === 'bug' ? 'bug' : 'bulb', 's')} ${ttName(k)}</label><textarea id="tt-${k}" rows="6" maxlength="5000" placeholder="${esc(def[k])}">${esc(cur[k] || '')}</textarea></div>`).join('')}
    <div class="foot"><button class="btn" data-m="reset">${tr('Built-in texts')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('ttmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'reset') { $('#tt-bug', md).value = ''; $('#tt-feature', md).value = ''; return; }
    if (b.dataset.m === 'save') {
      try { await api('PATCH', '/api/lists/' + lid, {ticket_tpl: {bug: $('#tt-bug', md).value, feature: $('#tt-feature', md).value}}); } catch { return; }
      md.remove(); await load(); render(); toast(tr('Saved'));
    }
  });
}
function projectParts() {
  return [timeOn() && tr('time tracking'), depsOn() && (feat('timeline') ? tr('dependencies with the Gantt timeline') : tr('dependencies')),
    fieldsOn() && tr('custom fields'), progressOn() && tr('progress and status')].filter(Boolean);
}
function kindHint(k) {
  if (k === 'project') { const p = projectParts(); return p.length ? tr('This list gets {0}.', esc(p.join(', '))) : tr('The project features are switched off (Settings > Modules).'); }
  return tr('A plain task list. Make it a project for time tracking, dependencies, custom fields and progress.');
}
async function setListKind(id, kind) {
  const l = listById(id); if (!l || (l.kind || 'list') === kind) return;
  const e = await listPatch(id, {kind}, tr('Type of {0}: {1}', qn(lname(l)), tr(LKINDS.find(x => x[0] === kind)[1])));
  if (e !== false) offerUndo(tr('Type: {0}', tr(LKINDS.find(x => x[0] === kind)[1])), e);
}
// 2.18.0 (#408): the project type of an existing list ('' = none), shown and changed in the list dialog (owner / list
// admins). The server switches on what the type needs (type Project, ticket types for software, the type's view while
// the list is empty, its modules for this person) and never deletes anything; one history step takes all of it back.
const ptypeName = k => k ? tr(PTYPE_UI.find(x => x[0] === k)?.[1] || k) : tr('None|project type');
const ptypeHint = k => tr(PTYPE_UI.find(x => x[0] === (k || ''))?.[3] || PTYPE_UI[0][3]);
// the Repository area of a project: for software projects and for every list that already has a repository
const repoShown = l => (l.ptype === 'software' && (l.kind || 'list') === 'project') || !!(l.repos || []).length;
// 2.22.0 (#746): the software parts of a list's properties (ticket types, repository) only for a software project or a list
// that has a repository; never for family / household lists, kids or people who set Kalmido up for home or family
const swArea = l => repoShown(l);
const swOffer = l => !!l && !l.is_inbox && !l.family && !l.life && !S.me?.kid && !['family', 'home'].includes(S.settings.purpose || '') && !swArea(l);
function ptypeRowHtml(l) {
  const may = canManage(l), why = may ? '' : tr('Only the owner and list admins can change the project type');
  return `<div class="row lptrow"><label for="l-ptype">${tr('Project type')}</label><select id="l-ptype" ${may ? '' : `disabled title="${esc(why)}"`}>${PTYPE_UI.map(([k, n]) => `<option value="${k}" ${(l.ptype || '') === k ? 'selected' : ''}>${k ? tr(n) : tr('None|project type')}</option>`).join('')}</select></div>
    <div class="shint lhint" id="l-pthint">${esc(ptypeHint(l.ptype || ''))}</div><div id="l-ptoffer" aria-live="polite"></div>`;
}
async function setListPtype(id, pt, o = {}) {  // o.post: runs after an undo / redo (the open dialog follows)
  const l = listById(id); if (!l) return false;
  const old = l.ptype || '';
  if (old === pt) return false;
  let r; try { r = await api('PATCH', '/api/lists/' + id, {ptype: pt}); } catch { return false; }
  await load(); render();
  modulesOnToast(r.modules_on);
  const prev = r.ptype_prev || {}, x = listById(id) || l;
  const before = {ptype: old, ...prev}, after = {ptype: pt};
  for (const k in prev) after[k] = lv(k, x[k]);  // 0 / 1 for the ticket types, as stored (the server's _prev check)
  // list admins: only the type itself (kind / ticket types / view are the owner's settings; they stay switched on)
  const go = (to, from) => async () => {
    const own = isOwner(listById(id) || l), pick = o => own ? o : {ptype: o.ptype};
    const res = await api('PATCH', '/api/lists/' + id, {...pick(to), _prev: pick(from)});
    return {skipped: (res.conflicts || []).length ? [`${qn(lname(listById(id)) || '')}: ${tr('Project type')}`] : []};
  };
  const e = histAdd({label: tr('Project type of {0}: {1}', qn(lname(x)), ptypeName(pt)), undo: go(before, after), redo: go(after, before), lids: [id], post: o.post});
  return {e, missing: r.ptype_missing || {sections: [], fields: []}};
}
// after a type change: offer (never force) the type's sections the list does not have yet; added = one undo step
function ptypeOfferDraw(box, id, k, names) {
  if (!names.length || !canEditList(id)) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="shint keep lhint ptoffer"><span>${esc(tr('Add the sections of {0}: {1}?', ptypeName(k), names.join(', ')))}</span>
    <span class="ptobtns"><button type="button" class="btn sm pri" data-pto="add">${ic('plus', 's')} ${tr('Add sections')}</button><button type="button" class="btn sm" data-pto="no">${tr('No thanks')}</button></span></div>`;
  box.onclick = async e => {
    const b = e.target.closest('[data-pto]'); if (!b) return;
    if (b.dataset.pto === 'no') { box.innerHTML = ''; return; }
    b.disabled = true;
    const made = await ptypeAddSections(id, names);
    box.innerHTML = '';
    if (made) $('#l-ptype', box.closest('.modal') || document)?.focus();
  };
}
async function ptypeAddSections(id, names) {
  const made = [];
  for (const n of names) { try { made.push({id: (await api('POST', '/api/sections', {list_id: id, name: n})).id, name: n}); } catch { break; } }
  if (!made.length) return null;
  await load(); render();
  const del = async () => {
    let skip = 0;
    for (const s of made) { const r = await api('DELETE', '/api/sections/' + s.id, {_prev: {name: s.name, tasks: []}}); if (r && r.ok === false) skip++; }
    return {skipped: skip ? [tr('Sections of {0}', qn(lname(listById(id)) || ''))] : []};
  };
  const add = async () => { for (const s of made) s.id = (await api('POST', '/api/sections', {list_id: id, name: s.name})).id; return {}; };
  offerUndo(trn('{0} section added', '{0} sections added', made.length), histAdd({label: tr('Sections of {0}', qn(lname(listById(id)) || '')), undo: del, redo: add, lids: [id]}));
  return made;
}
// list settings (type, name, colour, folder, view, "move dependent tasks along", hourly rate, archived) as one history
// step; _prev = the values after, so a setting changed elsewhere meanwhile stays. false = the request failed
const LIST_HIST = ['name', 'color', 'folder', 'view', 'kind', 'dep_shift', 'rate', 'archived', 'tickets', 'nag', 'day_hours', 'checklist'];  // 2.7.0: nag, day_hours; 2.7.2: checklist = "Show completed at the bottom"
const lv = (k, v) => k === 'dep_shift' || k === 'archived' || k === 'tickets' || k === 'checklist' ? (v ? 1 : 0) : k === 'rate' || k === 'day_hours' ? (v === '' || v == null ? null : +String(v).replace(',', '.')) : v ?? '';
async function listPatch(id, body, label, o = {}) {
  const l = listById(id); if (!l) return false;
  const before = {}, after = {};
  for (const k of LIST_HIST) if (k in body && lv(k, l[k]) !== lv(k, body[k])) { before[k] = lv(k, l[k]); after[k] = lv(k, body[k]); }
  try { await api('PATCH', '/api/lists/' + id, body); } catch { return false; }
  await load(); render();
  if (!Object.keys(before).length) return null;
  const go = (to, from) => async () => {
    const r = await api('PATCH', '/api/lists/' + id, {...to, _prev: from});
    return {skipped: (r.conflicts || []).map(c => `${qn(lname(listById(id)) || '')}: ${tr({name: N_('Name'), color: N_('Colour'), folder: N_('Folder'), view: N_('View'), kind: N_('Type'), checklist: N_('Show completed at the bottom'), dep_shift: N_('Move dependent tasks along'), rate: N_('Hourly rate'), archived: N_('Archived')}[c.field] || c.field)}`)};
  };
  return histAdd({label: label || tr('Settings of {0}', qn(lname(l))), undo: go(before, after), redo: go(after, before), post: o.post});
}
// per user and list: the "x" on the progress bar (stored server-side, so it follows to every device)
const progHidden = id => (S.settings.hide_progress || '').split(',').includes(String(id));
async function setProgHidden(id, hide) {
  const ids = (S.settings.hide_progress || '').split(',').filter(x => x && x !== String(id));
  if (hide) ids.push(String(id));
  S.settings.hide_progress = ids.join(',');
  render();
  try { await api('PATCH', '/api/settings', {hide_progress: S.settings.hide_progress}); } catch { await load(); render(); }
}
// the list's "…" menu (header) and the sidebar's context menu
const colItem = id => ({label: tr('Columns…'), icon: 'columns', cls: 'mcols', fn: () => colModal(id)});
function listMenuItems(id, anchor) {
  const l = listById(id); if (!l) return [];
  const own = isOwner(l), k = l.kind || 'list', at = () => typeof anchor === 'function' ? anchor() : anchor;
  const items = [{label: tr('Edit list…'), icon: 'edit', fn: () => listModal(id)}, ...(shareOk(l) && !l.archived ? [{label: tr(collab() ? N_('Share…') : N_('Ownership…')), icon: 'users', fn: () => shareModal(id)}] : [])];
  // 2.14.0 (#425): "Columns…" replaces "Show task numbers" and "Hide / Show assignee column" (per device until then); high up
  if (!l.archived) items.push(colItem(id));
  // 2.17.0 (#442 #419): the list's notes and (shared) its team chat
  if (notesOn(l) && !l.archived) { const n = notesOf(id).length; items.push({label: n ? tr('Notes ({0})', n) : tr('Notes'), icon: 'edit', fn: () => go('notes/' + id)}); }
  if (teamOn() && l.shared && !l.archived && l.role !== 'participant') items.push({label: tr('Team chat'), icon: 'comment', fn: () => listChat(id)});
  if (!l.is_inbox && !l.archived) items.push({label: tr('Move to folder…'), icon: 'folder', fn: () => folderPick(at(), id)});
  if (propOn() && !l.archived) {  // 2.3.0 (#262 #263)
    if (l.is_inbox && own) items.push({label: propWith(N_('Sort the inbox with {0}…'), N_('Sort the inbox with an agent…')), icon: 'bot', fn: () => propRequest('triage', {})});
    else if (!l.is_inbox && canEditList(id)) items.push({label: tr('Tasks from notes…'), icon: 'bot', fn: () => propRequest('extract', {lid: id})});
  }
  // 2.13.0 (#453 A7): not a second "List"; 2.18.0 review: "As a list / As a project", "Type: Project" read like the project type
  if (own) items.push('-', ...LKINDS.map(([v]) => ({label: v === 'project' ? tr('As a project') : tr('As a list'), icon: LKIND_ICON[v], on: k === v, fn: () => setListKind(id, v)})));
  if (collab() && l.shared) items.push({label: tr('Notifications: {0}', bellLabel(l.bell)), icon: BELL_ICON[l.bell || 'default'], fn: () => bellMenu(at(), id)});
  if (progressFor(l) && !l.is_inbox) items.push('-', progHidden(id) ? {label: tr('Show progress'), icon: 'eye', fn: () => setProgHidden(id, false)} : {label: tr('Hide progress'), icon: 'x', fn: () => setProgHidden(id, true)});
  // U12: archive (with undo) instead of delete; deleting for good only from the archive
  if (own && !l.is_inbox) items.push('-', l.archived ? {label: tr('Restore from the archive'), icon: 'undo', fn: () => listArchive(id, false)} : {label: tr('Archive'), icon: 'archive', fn: () => listArchive(id, true)},
    ...(l.archived ? [{label: tr('Delete permanently…'), icon: 'trash', cls: 'flag-5', fn: () => listDeleteForGood(id)}] : []));
  return items;
}
// 2.1.0 (#317): the bell of a list (mine only): all / default (the matrix in Settings > Notifications) / mute
// 2.6.1 (#404): + custom = my own choice per event (News and Push each), for this list only
const BELLS = [['all', N_('All activity'), N_('every comment, new task and change in this list')], ['default', N_('Default'), N_('as in Settings > Notifications')],
  ['mute', N_('Mute'), N_('only mentions of me and tasks assigned to me')], ['custom', N_('Custom selection…'), N_('your own choice per event, for News and Push')]];
const BELL_ICON = {all: 'bellring', default: 'bell', mute: 'belloff', custom: 'sliders'};
const bellLabel = m => tr(BELLS.find(b => b[0] === (m || 'default'))[1]).replace(/…$/, '');
// the events of the custom bell (server: BELL_CUSTOM_ROWS); a ticked one comes from every task of the list
const BELL_ROWS = [['newtask', N_('New tasks'), N_('created by someone else')], ['comment', N_('Comments'), N_('every comment in this list, replies included')],
  ['mention', N_('Mentions of me')], ['assign', N_('Tasks assigned to me (or taken away)')], ['complete', N_('Completed tasks'), N_('completed by someone else')],
  ['status', N_('Project status changes')], ['unblock', N_('A task I wait on was completed'), '', 'deps'], ['approval', N_('An agent waits for my approval'), N_('proposals and approvals of agents'), 'agents']];
// what a custom bell starts with: the stored choice, else what the matrix (Settings > Notifications) says today
function bellCustomOf(l) {
  const m = notifMatrix(S.settings), c = l?.bell_custom || {}, out = {};
  for (const [r] of BELL_ROWS) out[r] = {news: 'news' in (c[r] || {}) ? !!c[r].news : !!m[r]?.news, push: 'push' in (c[r] || {}) ? !!c[r].push : !!m[r]?.push};
  return out;
}
async function bellSet(id, mode, custom) {
  const l = listById(id); if (!l || ((l.bell || 'default') === mode && !custom)) return;
  const prev = l.bell || 'default', prevC = l.bell_custom || {};
  let j;
  try { j = await api('PUT', `/api/lists/${id}/bell`, custom ? {mode, custom} : {mode}); } catch { return; }
  l.bell = mode; if (j?.custom) l.bell_custom = j.custom;
  renderSide(); render();
  const sel = $('#l-bell'); if (sel) { sel.value = mode; sel.dispatchEvent(new Event('bell-sync')); }
  toast(tr('Notifications for {0}: {1}', lname(l), bellLabel(mode)), async () => {
    const r = await api('PUT', `/api/lists/${id}/bell`, prev === 'custom' || custom ? {mode: prev, custom: prevC} : {mode: prev});
    l.bell = prev; l.bell_custom = r?.custom || prevC; renderSide(); render(); const s2 = $('#l-bell'); if (s2) { s2.value = prev; s2.dispatchEvent(new Event('bell-sync')); }
  });
}
function bellMenu(anchor, id) {
  const l = listById(id); if (!l) return;
  menu(anchor, BELLS.map(([m, n, h]) => ({label: tr(n), title: tr(h), icon: BELL_ICON[m], on: (l.bell || 'default') === m, fn: () => m === 'custom' ? bellCustomModal(id) : bellSet(id, m)})));
}
// "Custom selection…": the events x News / Push for this list (same table as Settings > Notifications)
function bellCustomModal(id) {
  const l = listById(id); if (!l) return;
  const v = bellCustomOf(l), social = collab();
  const rows = BELL_ROWS.filter(([, , , f]) => !f || (f === 'deps' ? depsOn() : feat('agents') && (S.agents || []).length));
  const box = (r, ch, lab) => `<label class="nmhit"><input type="checkbox" data-bc="${r}" data-ch="${ch}" ${v[r][ch] ? 'checked' : ''} aria-label="${esc(tr(lab) + ': ' + (ch === 'news' ? tr('News') : tr('Push')))}"></label>`;
  const md = modal(`<h3 id="bc-h">${esc(tr('Notifications for {0}', lname(l)))}</h3>
    <div class="shint">${tr('Ticked events reach you from every task of this list, unticked ones never. News = under the bell, Push = on your devices. Only for you; reminders and lists shared with you follow Settings > Notifications.')}</div>
    <div class="nmx bcmx" role="table" aria-labelledby="bc-h"><div class="nmh" role="row"><span role="columnheader">${tr('Event')}</span><span role="columnheader">${tr('News')}</span><span role="columnheader">${tr('Push')}</span></div>
    ${rows.map(([r, n, d]) => `<div class="nmr" role="row"><span class="nml" role="cell">${tr(n)}${d ? `<small>${tr(d)}</small>` : ''}</span><span role="cell">${social ? box(r, 'news', n) : '<span class="nmna">–</span>'}</span><span role="cell">${box(r, 'push', n)}</span></div>`).join('')}</div>
    <div class="row mfoot"><button class="btn sm" data-bcq="none">${tr('Tick none')}</button><span class="spacer"></span><button class="btn" data-bcq="cancel">${tr('Cancel')}</button><button class="btn pri" data-bcq="save">${tr('Save')}</button></div>`);
  md.classList.add('bcmodal');
  onRemove(md, () => { const sel = $('#l-bell'); if (sel) { sel.value = listById(id)?.bell || 'default'; sel.dispatchEvent(new Event('bell-sync')); } });  // closed without saving: the list dialog shows the bell as it is
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-bcq]'); if (!b) return;
    if (b.dataset.bcq === 'none') { $$('[data-bc]', md).forEach(x => { x.checked = false; }); return; }
    if (b.dataset.bcq === 'cancel') { md.remove(); return; }
    const custom = {};
    for (const x of $$('[data-bc]', md)) (custom[x.dataset.bc] ||= {})[x.dataset.ch] = x.checked ? 1 : 0;
    md.remove();
    await bellSet(id, 'custom', custom);
  });
  setTimeout(() => $('[data-bc]', md)?.focus(), 30);
}
function listMenu(anchor, id) { const it = listMenuItems(id, anchor); if (it.length) menu(anchor, it); }
// archive / restore a list: one history step (undo brings it back), the toast offers the undo too
async function listArchive(id, on) {
  const l = listById(id); if (!l) return;
  const e = await listPatch(id, {archived: on ? 1 : 0}, on ? tr('Archived {0}', qn(lname(l))) : tr('Restored {0} from the archive', qn(lname(l))));
  if (e === false) return;
  if (on && S.route.key === 'l:' + id) go(START_KEY);
  offerUndo(on ? tr('“{0}” archived. Find it under “Archived” in the sidebar.', lname(l)) : tr('“{0}” is back in your lists', lname(l)), e);
}
// deleting for good: only archived lists; the dialog names what is lost
async function listDeleteForGood(id) {
  const l = listById(id); if (!l || !l.archived) return false;
  const all = [...S.tasks.values()].filter(t => t.list_id === id), open = all.filter(t => t.status === 0).length;
  const lost = [tr('the list itself, its sections, colour, folder and type'), fieldsOf(id).length && trn('{0} custom field and its values', '{0} custom fields and their values', fieldsOf(id).length),
    l.shared && tr('the sharing: members lose access at once'), l.status && tr('the project status'), tr('its public link, if there is one')].filter(Boolean);
  const ok = await askConfirm(tr('Delete “{0}” permanently?', lname(l)), '', {danger: true, ok: tr('Delete permanently'),
    html: `<p>${tr('This cannot be undone. Lost for good:')}</p><ul class="cdlg-l">${lost.map(x => `<li>${esc(x)}</li>`).join('')}</ul><p class="muted">${all.length ? trn('Its {0} task goes to the trash of your inbox ({1} open) and can be restored from there.', 'Its {0} tasks go to the trash of your inbox ({1} open) and can be restored from there.', all.length, open) : tr('The list has no tasks.')}</p>`});
  if (!ok) return false;
  try { await api('DELETE', '/api/lists/' + id); } catch { return false; }
  if (S.route.key === 'l:' + id) go(START_KEY);
  await load(); render(); toast(tr('“{0}” deleted', lname(l)));
  return true;
}
// ---- 2.6.0 (K12): the Share dialog, out of the long list dialog: people + roles and inviting, the agents of the list (share /
// stop sharing, the tidy agent), the public link, transferring the ownership. From the list's "…" menu, the header's Share
// button and the list dialog (Sharing > Share…). Admins without collaboration only see the ownership part.
const shareOk = l => !!l && !l.is_inbox && (collab() || !!S.me?.is_admin);
function shareSummary(l) {
  const ppl = listPeople(l).filter(p => !(S.me && p.user_id === S.me.id) && !agentById(p.user_id) && !p.agent), ags = listAgents(l);
  if (!collab()) return tr('Owner: {0}', l.owner_name || S.me?.display_name || '');
  return [ppl.length ? trn('Shared with {0} person', 'Shared with {0} people', ppl.length) : tr('Not shared with anyone yet'), ags.length ? trn('{0} agent', '{0} agents', ags.length) : ''].filter(Boolean).join(' · ');
}
function shareModal(id) {
  const l0 = listById(id); if (!shareOk(l0)) return;
  const own = isOwner(l0), hint = t => `<div class="shint lhint">${t}</div>`;
  const md = modal(`<div class="lhdr"><h3>${esc(tr(collab() ? N_('Share “{0}”') : N_('Owner of “{0}”'), lname(l0)))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    ${collab() ? `<h4 id="sh-people-h">${tr('People')}</h4><div class="members" id="l-members" aria-labelledby="sh-people-h"></div>` : ''}
    ${collab() && S.peopleVis === 'contacts' && canManage(l0) ? `<div class="row shmail"><input id="sh-email" type="email" autocomplete="off" placeholder="${esc(tr('Share by e-mail address'))}" aria-label="${esc(tr('Share by e-mail address'))}"><button type="button" class="btn sm" data-m="share-mail">${ic('send', 's')} ${tr('Share')}</button></div>` : ''}
    ${collab() ? `<div id="sh-grpwrap"></div>` : ''}
    ${collab() && agentsOn() ? `<div id="sh-agwrap"></div>` : ''}
    ${own && S.publicLinks ? `<h4 id="l-pub-h">${tr('Public link')}</h4><div id="l-pub"><div class="muted mhint">${tr('Loading…')}</div></div>` : ''}
    <div id="sh-ownwrap"><h4 id="sh-own-h">${tr('Owner')}</h4><div class="muted mhint" id="sh-owner"></div><div id="l-owner"></div></div>
    <div class="foot"><button class="btn" data-m="list-edit">${ic('edit', 's')} ${tr('List settings…')}</button><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.classList.add('shmodal');
  let users = null;
  const roleSel = (attr, cur_, lab) => `<select ${attr} aria-label="${esc(lab || tr('Role'))}">${ROLES.map(([v, n, h]) => `<option value="${v}" title="${esc(tr(h))}" ${v === cur_ ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>`;
  const isAg = p => !!(p.agent || agentById(p.user_id));
  const row = (cur, p, mng) => `<div class="mrow" data-uid="${p.user_id}">${avBtn(p.user_id, p.name)}<span class="n">${esc(p.name)}${S.me && p.user_id === S.me.id ? ' ' + tr('(me)') : ''}${isAg(p) ? agentBadge() : ''}${p.via_group ? ` <span class="muted">${tr('via a group')}</span>` : ''}</span>${mng && p.role !== 'owner' && !(S.me && p.user_id === S.me.id) && !p.via_group
      ? `${roleSel(`data-mrole="${p.user_id}"`, p.role, tr('Role of {0}', p.name))}<button class="iconbtn" data-mrm="${p.user_id}" title="${esc(isAg(p) ? tr('Stop sharing with {0}', p.name) : tr('Remove from list'))}" aria-label="${esc(isAg(p) ? tr('Stop sharing with {0}', p.name) : tr('Remove {0} from this list', p.name))}">${ic('x', 's')}</button>`
      : `<span class="muted" title="${esc(roleHelp(p.role))}">${esc(roleLabel(p.role))}</span>`}</div>`;
  const draw = () => {
    if (!md.isConnected) return;
    const cur = listById(id) || l0, people = listPeople(cur), mng = canManage(cur);
    const box = $('#l-members', md);
    if (box) {
      const ppl = people.filter(p => !isAg(p));
      const cand = users && users.filter(u => !u.agent && u.id !== S.me?.id && !people.some(p => p.user_id === u.id));
      box.innerHTML = ppl.map(p => row(cur, p, mng)).join('') +
        (mng ? (users === null ? `<div class="muted mhint">${tr('Loading…')}</div>` : cand.length ? `<div class="mrow madd"><select id="l-adduser" aria-label="${esc(tr('Invite'))}"><option value="">${tr('Share with …')}</option>${cand.map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join('')}</select>${roleSel('id="l-addrole"', 'edit')}<button class="btn sm" data-m="share">${ic('plus', 's')} ${tr('Add')}</button></div>`
          : `<div class="muted mhint">${users.filter(u => !u.agent).length > 1 ? tr('Shared with everyone') : tr('No other users yet. An admin can add them in the settings.')}</div>`) + `<details class="rolehelp sdet"><summary>${tr('What the roles may do')}</summary>${ROLES.map(([, n, h]) => `<div><b>${tr(n)}</b> <span class="muted">${tr(h)}</span></div>`).join('')}</details>`
          : `<div class="muted mhint olock"><span>${esc(tr('Owner'))}: ${esc(cur.owner_name)}</span><button type="button" class="iconbtn" data-m="owner-info" title="${esc(tr('Owner: {0}. Only the owner can rename or archive this list; the owner and list admins manage who is in it.', cur.owner_name))}" aria-label="${esc(tr('Owner: {0}. Only the owner can rename or archive this list; the owner and list admins manage who is in it.', cur.owner_name))}">${ic('lock', 's')}</button></div>`);
    }
    const aw = $('#sh-agwrap', md);
    if (aw) {
      const ags = people.filter(isAg), acand = users ? users.filter(u => u.agent && !people.some(p => p.user_id === u.id)) : [];
      aw.innerHTML = ags.length || (mng && acand.length) ? `<h4 id="sh-ag-h">${tr('Agents')}</h4>${hint(tr('An agent sees exactly the lists shared with it, nothing else. Stopping the sharing ends its access at once.'))}
        <div class="members" id="sh-agents">${ags.map(p => row(cur, p, mng)).join('')}${mng && acand.length ? `<div class="mrow madd"><select id="sh-addagent" aria-label="${esc(tr('Share with an agent'))}"><option value="">${tr('Share with an agent …')}</option>${acand.map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join('')}</select>${roleSel('id="sh-agrole"', 'edit')}<button class="btn sm" data-m="share-ag">${ic('plus', 's')} ${tr('Add')}</button></div>` : ''}</div>
        <div id="l-tidyrow">${tidyRowHtml(cur)}</div>` : '';
    }
    const gw = $('#sh-grpwrap', md);  // 2.10.0 (#441)
    if (gw) { const gh = shareGroupsHtml(cur, mng, roleSel); gw.innerHTML = gh ? `<h4 id="sh-grp-h">${tr('Groups')}</h4><div class="members" id="sh-groups" aria-labelledby="sh-grp-h">${gh}</div>` : ''; }
    const ow = $('#sh-owner', md); if (ow) ow.textContent = cur.owner_name || (own ? S.me?.display_name || '' : '');
    const sum = $('#l-shsum'); if (sum) sum.textContent = shareSummary(cur);
  };
  // "Transfer ownership…" (owner) / "Take over…" (admins, owner = agent or disabled user) + the history (2.1.2, #349)
  const drawOwner = async () => {
    const box = $('#l-owner', md); if (!box) return;
    let j; try { j = await calReq('GET', `/api/lists/${id}/owner`); } catch { box.innerHTML = ''; return; }
    if (!md.isConnected) return;
    box._j = j;
    const hist = j.history.slice(0, 3).map(h => `<div class="muted mhint owhist">${esc(tr('Ownership transferred from {0} to {1}', h.from, h.to))} · ${esc(relTime(h.at))}</div>`).join('');
    const why = j.owner.agent ? tr('The owner is the agent {0}: agents cannot manage who is in a list. As an admin you can take it over.', j.owner.name)
      : tr('The owner {0} is disabled. As an admin you can take the list over.', j.owner.name);
    box.innerHTML = (j.mode === 'owner' ? `<div class="row owrow"><button class="btn sm" data-m="own-xfer">${ic('user', 's')} ${tr('Transfer ownership…')}</button></div>`
      : j.mode === 'takeover' ? `<div class="shint keep lhint">${esc(why)}</div><div class="row owrow"><button class="btn sm" data-m="own-xfer">${ic('user', 's')} ${tr('Take over…')}</button></div>` : '') + hist;
  };
  draw(); drawOwner();
  if (own && S.publicLinks) pubWire(md, id);
  if (collab()) {
    tidyWire(md, id);
    if (canManage(l0)) api('GET', '/api/users').then(j => { users = j.users.filter(u => !u.disabled).map(u => ({id: u.id, display_name: u.display_name, agent: !!u.agent})); draw(); }).catch(() => { users = []; draw(); });
  }
  const act = async (fn, msg) => { try { await fn(); await load(); render(); draw(); if (msg) toast(msg); } catch { /* api() showed it */ } };
  md.addEventListener('change', e => {
    const r = e.target.closest('[data-mrole]');
    if (r) act(() => api('PUT', `/api/lists/${id}/members`, {user_id: +r.dataset.mrole, role: r.value}));
    const gr = e.target.closest('[data-grole]');
    if (gr) act(() => api('PUT', `/api/lists/${id}/groups/${gr.dataset.grole}`, {role: gr.value}));
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    const m = b.dataset.m;
    if (m === 'close') { md.remove(); return; }
    if (m === 'list-edit') { md.remove(); listModal(id); return; }
    if (m === 'share-mail') {  // 2.22.0 (#752): mode "own contacts": share by address; the answer never says whether it has an account
      const em = $('#sh-email', md).value.trim(); if (!em) { $('#sh-email', md).focus(); return; }
      try { await api('PUT', `/api/lists/${id}/members`, {email: em, role: 'edit'}); } catch { return; }
      $('#sh-email', md).value = ''; toast(tr('If there is an account with this address, the list is now shared with it.')); await load(); render(); return;
    }
    if (m === 'share' || m === 'share-ag') {
      const [us, rs] = m === 'share' ? ['#l-adduser', '#l-addrole'] : ['#sh-addagent', '#sh-agrole'];
      const u = +$(us, md).value; if (!u) return;
      act(() => api('PUT', `/api/lists/${id}/members`, {user_id: u, role: $(rs, md).value}), tr('Shared')); return;
    }
    if (b.dataset.mrm) {
      const p = listPeople(listById(id)).find(x => x.user_id === +b.dataset.mrm), ag = p && isAg(p);
      if (!await askConfirm(ag ? tr('Stop sharing with {0}?', p?.name || '') : tr('Remove {0} from this list?', p?.name || ''), ag ? tr('The agent loses access to this list and its tasks at once.') : tr('They no longer see the list and its tasks; their tasks stay.'), {ok: ag ? tr('Stop sharing') : tr('Remove'), danger: true})) return;
      act(() => api('DELETE', `/api/lists/${id}/members/${b.dataset.mrm}`)); return;
    }
    if (m === 'share-grp') { const g = +$('#l-addgrp', md).value; if (g) act(() => api('PUT', `/api/lists/${id}/groups/${g}`, {role: $('#l-grprole', md).value}), tr('Shared')); return; }
    if (b.dataset.grm) {
      const g = (listById(id)?.groups || []).find(x => x.group_id === +b.dataset.grm);
      if (!await askConfirm(tr('Stop sharing with the group {0}?', g?.name || ''), tr('Its members lose access unless they have it personally or through another group.'), {ok: tr('Stop sharing'), danger: true})) return;
      act(() => api('DELETE', `/api/lists/${id}/groups/${b.dataset.grm}`)); return;
    }
    if (m === 'owner-info') { toast(b.title); return; }
    if (m === 'own-xfer') { const j = $('#l-owner', md)?._j; if (j) ownerModal(id, lname(listById(id) || l0), j, () => md.remove()); return; }
  });
  return md;
}
// 2.22.0 (#682): a new list / project gets a fitting emoji from its name (a local word list in the six languages, no AI):
// suggested in the dialog as soon as a word matches, one tap on it changes or removes it; existing lists stay as they are
const AUTO_EMO = [
  ['🛒', 'einkauf shopping grocer groceries supermarkt supermarket courses épicerie compra compras spesa boodschappen'],
  ['💼', 'arbeit work job büro office travail trabajo oficina lavoro ufficio werk kantoor business'],
  ['👨‍👩‍👧', 'familie family famille familia famiglia gezin kinder kids enfants niños bambini'],
  ['🏖️', 'urlaub holiday vacation ferien vacances vacaciones vacanze vakantie strand beach plage playa spiaggia'],
  ['✈️', 'reise trip travel flug flight voyage viaje viaggio reis'],
  ['🏠', 'haus house home zuhause haushalt household maison casa hogar huis wohnung apartment appartement'],
  ['🌱', 'garten garden jardin jardín giardino tuin pflanzen plants'],
  ['🚗', 'auto car voiture coche macchina wagen kfz'],
  ['💰', 'geld money finanzen finance finances dinero soldi geld budget steuer tax taxes impôts impuestos tasse belasting bank'],
  ['🩺', 'gesundheit health arzt doctor santé médecin salud médico salute medico gezondheid dokter'],
  ['🏃', 'sport fitness training laufen running gym deporte allenamento hardlopen'],
  ['📚', 'lesen reading bücher books lecture livres lectura libros lettura libri lezen boeken studium study school schule uni université universidad università'],
  ['🎁', 'geschenk geschenke gift gifts cadeau cadeaux regalo regali'],
  ['🎂', 'geburtstag birthday anniversaire cumpleaños compleanno verjaardag party feier fête fiesta festa feest'],
  ['🍳', 'kochen cooking rezepte recipes essen meals cuisine recettes cocina recetas cucina ricette koken recepten'],
  ['🐾', 'haustier pet pets hund dog katze cat chien chat perro gato cane gatto hond kat'],
  ['🔧', 'reparatur repair renovierung renovation werkzeug diy bricolage reparación riparazione klussen'],
  ['💻', 'software code coding dev entwicklung development app website web it programmierung'],
  ['📝', 'notizen notes ideen ideas idées ideas idee ideeën'],
  ['🎵', 'musik music musique música musica muziek'],
  ['📦', 'umzug moving déménagement mudanza trasloco verhuizing'],
  ['💍', 'hochzeit wedding mariage boda matrimonio bruiloft'],
  ['🎄', 'weihnachten christmas noël navidad natale kerst'],
  ['📄', 'verträge contracts vertrag contract contrats contratos contratti contracten versicherung insurance assurance seguro assicurazione verzekering'],
  ['👶', 'baby bébé bebé neonato'],
  ['🧹', 'putzen cleaning ménage limpieza pulizie schoonmaken'],
];
function autoEmoji(name) {
  const words = String(name || '').toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(w => w.length > 2);
  if (!words.length) return '';
  const hit = f => AUTO_EMO.find(([, ks]) => ks.split(' ').some(k => words.some(w => f(w, k))));  // the beginning of a word first
  return (hit((w, k) => w === k || (k.length > 3 && w.startsWith(k))) || hit((w, k) => k.length > 4 && w.endsWith(k)) || [''])[0];
}
function listModal(id, folder = '', o = {}) {
  const l = id ? listById(id) : {name: '', color: '', folder, view: 'list', kind: o.kind || 'list', tickets: 0};
  const own = isOwner(l), dis = own ? '' : 'disabled';
  const m0 = l.name.match(EMO_RE);
  let emo = m0 ? m0[1] : '';
  const base = l.is_inbox && inboxDef(l.name) ? tr('Inbox') : m0 ? l.name.slice(m0[0].length) : l.name;  // inbox keeps its stored name unless renamed
  // 1.5.1: an existing list saves itself like the settings (every change at once, "Saved · Undo", one history step each);
  // a new list keeps Cancel / Create
  const md = modal(`${id ? `<div class="lhdr"><h3>${tr('Edit list')}</h3><span class="ssaved" role="status" aria-live="polite"></span><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>` : `<h3>${tr('New list')}</h3>`}
    <div class="row"><label for="l-name">${tr('Name')}</label><button class="emobtn" id="l-emo" title="${tr('Choose icon')}" ${dis}>${id && l.icon ? licon(l, 'licon m') : emo || ic('list')}</button><input id="l-name" value="${esc(base)}" ${dis}></div>
    <div class="emogrid hidden" id="l-emogrid"><button data-emo="" class="none" title="${tr('No icon')}">${ic('ban', 's')}</button>${EMOJIS.map(e => `<button data-emo="${e}" class="${e === emo && !l.icon ? 'on' : ''}">${e}</button>`).join('')}<input id="l-emocustom" placeholder="${tr('custom')}" maxlength="8">
      ${id && own ? `<div class="lipickw"><span class="muted lipl">${tr('Or a picture')}</span>${liconPickHtml(l)}</div>` : ''}</div>
    <div class="row"><label for="l-folder">${tr('Folder')}</label><input id="l-folder" value="${esc(fDisp(l.folder))}" list="l-folders" placeholder="${esc(tr('optional · Folder / Subfolder'))}"><datalist id="l-folders">${folderNames().map(f => `<option value="${esc(fDisp(f))}">`).join('')}</datalist></div>
    <div class="row"><label for="l-view">${tr('View')}</label><select id="l-view"><option value="list">${tr('List')}</option>${feat('kanban') ? `<option value="kanban" ${l.view === 'kanban' ? 'selected' : ''}>${tr('Kanban')}</option>` : ''}${feat('timeline') ? `<option value="timeline" ${l.view === 'timeline' ? 'selected' : ''}>${tr('Timeline')}</option>` : ''}</select></div>
    <div class="row"><label for="l-kind">${tr('List or project')}</label><select id="l-kind" ${dis}>${LKINDS.map(([k, n]) => `<option value="${k}" ${(l.kind || 'list') === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div class="shint lhint" id="l-khint">${kindHint(l.kind || 'list')}</div>
    ${famOn() && own && !l.is_inbox ? `<div class="row"><label for="l-fam">${tr('Used for')}</label><select id="l-fam">${FAM_KINDS.map(([k, n]) => `<option value="${k}" ${(l.family || o.family || '') === k ? 'selected' : ''} ${FAM_KIND_ICON[k] ? `data-ico="${FAM_KIND_ICON[k]}"` : ''}>${tr(n)}</option>`).join('')}</select></div>` : ''}
    ${id ? '' : `<div class="lptype" ${(l.kind || 'list') === 'project' ? '' : 'hidden'}><div class="ptlab">${tr('Start from')}</div><div class="ptcards" role="radiogroup" aria-label="${esc(tr('Start from'))}">${PTYPE_UI.map(([k, n, i, dsc]) => `<button type="button" class="ptcard ${k === (o.ptype || '') ? 'on' : ''}" role="radio" aria-checked="${k === (o.ptype || '')}" data-pt="${k}">${ic(i, 's')}<b>${tr(n)}</b><small class="muted">${tr(dsc)}</small></button>`).join('')}${tplOf('list').map(tp => `<button type="button" class="ptcard" role="radio" aria-checked="false" data-pt="tpl:${tp.id}">${ic('copy', 's')}<b>${esc(tp.name)}</b><small class="muted" data-ptd="${tp.id}">${tr('Your template')}</small></button>`).join('')}</div>
      <div class="ptdates" hidden><div class="row"><label>${tr('Project start')}</label>${dateIn('l-pstart', today(), {label: tr('Project start'), clear: false})}</div><div class="row"><label>${tr('End (optional)')}</label>${dateIn('l-pend', '', {label: tr('End (optional)'), empty: tr('none')})}<span class="muted">${tr('stretches or squeezes the dates')}</span></div></div></div>`}
    <div class="kproj" ${(l.kind || 'list') === 'project' ? '' : 'hidden'}>
    ${id && !l.is_inbox ? ptypeRowHtml(l) : ''}
    ${own && !l.is_inbox ? `<div class="row ltkrow" ${swArea(l) || l.tickets ? '' : 'hidden'}><label>${tr('Ticket types')}</label><label class="chkl"><input type="checkbox" id="l-tickets" ${l.tickets ? 'checked' : ''}> ${tr('Bug, feature, task')}</label>${id ? `<button class="btn sm" data-m="tt-tpl" type="button">${tr('Templates…')}</button>` : ''}</div>
    <div class="shint lhint ltkhint" ${swArea(l) || l.tickets ? '' : 'hidden'}>${tr('Tasks get a type with an icon, a filter and quick add !bug / !feature; new bugs and features start with a note template.')}</div>` : ''}
    ${id && progressOn() ? `<div class="row"><label>${tr('Progress')}</label><label class="chkl"><input type="checkbox" id="l-showprog" ${progHidden(id) ? '' : 'checked'}> ${tr('Show the progress bar')}</label><span class="muted">${tr('only for you')}</span></div>` : ''}
    ${id && timeOn() && (own || l.day_hours) ? `<div class="row"><label for="l-dayh">${tr('Hours per day')}</label><input id="l-dayh" inputmode="decimal" value="${l.day_hours != null ? esc(String(l.day_hours).replace('.', LOCALE().startsWith('de') ? ',' : '.')) : ''}" placeholder="${esc(fmtNum(S.timeDayH || 8))}" style="max-width:5rem" ${dis}><span class="muted">${tr('h per day / shift, for the time sum in the header · empty = {0} h (server)', fmtNum(S.timeDayH || 8))}</span></div>` : ''}
    ${timeOn() && (own || l.rate) ? `<div class="row"><label for="l-rate">${tr('Hourly rate')}</label><input id="l-rate" inputmode="decimal" value="${l.rate != null ? esc(String(l.rate).replace('.', LOCALE().startsWith('de') ? ',' : '.')) : ''}" placeholder="${tr('optional')}" style="max-width:6.875rem" ${dis}><span class="muted">${esc(S.settings.time_currency || '')} · ${tr('time reports')}</span></div>` : ''}
    <div class="row"><label>${tr('Color')}</label><div class="colors" id="l-col" role="group" aria-label="${esc(tr('Color'))}">${LCOLORS.map((c, i) => `<button type="button" style="background:${c || 'var(--bg4)'}" class="${(l.color || '') === c ? 'on' : ''}" aria-pressed="${(l.color || '') === c}" aria-label="${esc(c ? tr('Color {0}', i) : tr('No color'))}" data-c="${c}" ${dis}></button>`).join('')}</div></div>
    ${id && !l.is_inbox && statusOn() && l.kind === 'project' ? `<div class="row"><label>${tr('Project status')}</label>${statusPill(l, true, true)}</div>` : ''}
    ${id && own && depsOn() ? `<div class="row"><label>${tr('Dependencies')}</label><label class="chkl"><input type="checkbox" id="l-depshift" ${l.dep_shift ? 'checked' : ''}> ${tr('Move dependent tasks along')}</label></div>
    <div class="shint lhint">${tr('When a task is postponed, the tasks of this list that wait on it and would now start too early move by the same number of days (also in the timeline). One undo takes the whole chain back.')}</div>` : ''}
    ${id && own && fieldsOn() ? `<h4 title="${esc(tr('Own columns for this list: budget, stage, client, …'))}">${tr('Custom fields')}</h4><div class="members" id="l-fields">${fieldsBox(id)}</div>` : id && fieldsOf(id).length ? `<h4>${tr('Custom fields')}</h4><div class="muted mhint">${esc(fieldsOf(id).map(f => f.name).join(', '))} · ${tr('only the owner can change them')}</div>` : ''}
    ${id && !l.is_inbox && (l.kind || 'list') === 'project' ? `<div class="lrepo" ${repoShown(l) ? '' : 'hidden'}><div class="shint keep lhint lrepohint" hidden>${ic('git', 's')} ${tr('Connect a repository (optional)')}</div>${repoBoxHtml(l)}</div>` : ''}
    </div>
    ${id && !l.is_inbox && (l.kind || 'list') !== 'project' && (l.repos || []).length ? repoBoxHtml(l) : ''}
    ${id && own && swOffer(l) ? `<div class="row lswoffer"><span></span><button type="button" class="linkbtn" data-m="sw-setup">${ic('code', 's')} ${tr('Set up as a software project…')}</button></div>` : ''}
    ${own ? `<div class="row ldabrow"><label>${tr('Completed')}</label><label class="chkl"><input type="checkbox" id="l-dab" ${l.checklist ? 'checked' : ''}> ${tr('Show completed at the bottom')}</label></div>
    <div class="shint lhint">${ic('cart', 's')} ${tr('What you tick off stays visible at the bottom and comes back with one tap: handy for shopping and packing lists.')}</div>` : ''}
    <div class="row lnagrow"><label for="l-nag">${tr('Repeat reminders')}</label><select id="l-nag" ${dis}><option value="">${tr('Off|nag')}</option>${NAG_OPTS.slice(1).map(([v, n]) => `<option value="${v}" ${(l.nag || '') === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div class="shint lhint">${tr('Default for the tasks of this list with a date: the reminder repeats until the task is done (a task can choose otherwise in its date dialog). Quiet hours: Settings > Notifications.')}</div>
    ${id && shareOk(l) ? `<h4>${tr(collab() ? N_('Sharing') : N_('Owner'))}</h4><div class="row shsum"><span class="muted" id="l-shsum">${esc(shareSummary(l))}</span><button class="btn sm" data-m="share-open">${ic('users', 's')} ${tr(collab() ? N_('Share…') : N_('Ownership…'))}</button></div>` : ''}
    ${id && !l.is_inbox && collab() && l.shared ? `<h4>${tr('Notifications')}</h4><div class="row"><label for="l-bell">${ic(BELL_ICON[l.bell || 'default'], 's')} ${tr('This list')}</label><select id="l-bell" data-native>${BELLS.map(([m, n]) => `<option value="${m}" ${(l.bell || 'default') === m ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div class="shint lhint" id="l-bellhint">${tr(BELLS.find(b => b[0] === (l.bell || 'default'))[2])} · ${tr('only for you')}</div>
    <div class="row" id="l-bellc" ${l.bell === 'custom' ? '' : 'hidden'}><span class="spacer"></span><button type="button" class="btn sm" data-m="bell-custom">${ic('sliders', 's')} ${tr('Choose events…')}</button></div>` : ''}
    ${id && !l.is_inbox && collab() && (l.shared || listTags(id).length) ? `<h4>${tr('List tags')}</h4><div class="shint lhint">${tr('Tags of this list: everyone in it sees them, with their colour. Personal tags (with the person icon) stay yours.')}</div><div class="members" id="l-ltags">${ltagsBoxHtml(l)}</div>` : ''}
    <div class="foot">${id && !l.is_inbox && own ? (l.archived ? `<button class="btn" data-m="arch">${ic('undo', 's')} ${tr('Restore from the archive')}</button><button class="btn danger" data-m="del">${ic('trash', 's')} ${tr('Delete permanently…')}</button>` : `<button class="btn" data-m="arch" title="${tr('Hidden from your lists; undo or restore any time. Deleting for good is only possible from the archive.')}">${ic('archive', 's')} ${tr('Archive')}</button>`) : ''}${id && !own ? `<button class="btn danger" data-m="leave">${ic('logout', 's')} ${tr('Leave list')}</button>` : ''}${id ? `<button class="btn" data-m="tpl" title="${tr('Save the sections and open tasks as a template')}">${ic('copy', 's')} ${tr('Save as template')}</button>` : ''}<span class="spacer"></span>${id ? '' : `<button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Create')}</button>`}</div>`);
  if (id) md.classList.add('lmodal'); else md.classList.add('lnew');
  if (!id && tplOf('list').length) api('GET', '/api/templates').then(j => {  // 2.4.0 (#328): what each own template brings
    for (const tp of j.templates || []) { const el = $(`[data-ptd="${tp.id}"]`, md); if (el) el.textContent = tp.data?.rel ? tr('Dates from the project start · {0} days', tp.data.span || 0) : trn('{0} task', '{0} tasks', tp.count); }
  }).catch(() => {});
  if (id && !l.is_inbox) repoWire(md, id);  // 2.2.0 (#271)
  if (id && !l.is_inbox && collab()) ltagsWire(md, id);
  const bellHint = v => { const h = $('#l-bellhint', md); if (h) h.textContent = tr(BELLS.find(x => x[0] === v)[2]) + ' · ' + tr('only for you'); const c = $('#l-bellc', md); if (c) c.hidden = v !== 'custom'; };
  $('#l-bell', md)?.addEventListener('change', async e => { e.stopPropagation(); if (e.target.value === 'custom') { bellHint('custom'); bellCustomModal(id); return; } await bellSet(id, e.target.value); bellHint(e.target.value); });
  $('#l-bell', md)?.addEventListener('bell-sync', e => bellHint(e.target.value));
  $('[data-m="bell-custom"]', md)?.addEventListener('click', e => { e.stopPropagation(); bellCustomModal(id); });
  // ---- autosave (existing lists)
  const pend = new Map();
  const formBody = () => {
    const nm = $('#l-name', md).value.trim().replace(EMO_RE, '');
    const body = own ? {name: l.is_inbox && !emo && nm === tr('Inbox') ? (inboxDef(l.name) ? l.name : 'Eingang') : emo + nm, folder: fNorm($('#l-folder', md).value), view: $('#l-view', md).value, color: $('#l-col button.on', md)?.dataset.c || '', kind: $('#l-kind', md).value, ...($('#l-depshift', md) ? {dep_shift: $('#l-depshift', md).checked} : {}), ...($('#l-rate', md) ? {rate: $('#l-rate', md).value.trim()} : {}), ...($('#l-tickets', md) ? {tickets: $('#l-tickets', md).checked} : {}),
      ...($('#l-nag', md) ? {nag: $('#l-nag', md).value} : {}), ...($('#l-dayh', md) ? {day_hours: $('#l-dayh', md).value.trim()} : {}), ...($('#l-dab', md) ? {checklist: $('#l-dab', md).checked} : {}),
      ...($('#l-fam', md) ? {family: $('#l-fam', md).value} : {})}
      : {folder: fNorm($('#l-folder', md).value), view: $('#l-view', md).value};  // members: only their own placement / view
    if (own && !nm) delete body.name;  // an empty name is never saved (leaving the field puts the saved one back)
    return body;
  };
  const lsaved = e => {
    const el = $('.ssaved', md); if (!el) return;
    el.innerHTML = `${ic('check', 's')}<span>${tr('Saved')}</span>${e ? `<button type="button" class="linkbtn" data-m="l-undo">${tr('Undo')}</button>` : ''}`;
    el.classList.add('on'); el._e = e;
    clearTimeout(el._t); el._t = setTimeout(() => { el.classList.remove('on'); el._e = null; }, 6000);
  };
  let ptKeys = false, ptPend = false, ptRun = Promise.resolve();  // 2.18.0 review (R1): project type select, see ptCommit
  const lsync = (force = false) => {  // after an undo / redo or a failed save: the dialog shows what is saved
    if (!md.isConnected) return;
    const x = listById(id); if (!x) return;
    const m1 = x.name.match(EMO_RE);
    if (force || document.activeElement !== $('#l-name', md)) { emo = m1 ? m1[1] : ''; $('#l-name', md).value = x.is_inbox && inboxDef(x.name) ? tr('Inbox') : m1 ? x.name.slice(m1[0].length) : x.name; $('#l-emo', md).innerHTML = emo || ic('list'); }
    if (document.activeElement !== $('#l-folder', md)) $('#l-folder', md).value = fDisp(x.folder || '');
    $('#l-view', md).value = listView(x); $('#l-kind', md).value = x.kind || 'list';
    $('#l-khint', md).innerHTML = kindHint(x.kind || 'list'); $('.kproj', md).hidden = (x.kind || 'list') !== 'project';
    $$('#l-col button', md).forEach(b => { b.classList.toggle('on', (x.color || '') === b.dataset.c); b.setAttribute('aria-pressed', String((x.color || '') === b.dataset.c)); });
    if ($('#l-depshift', md)) $('#l-depshift', md).checked = !!x.dep_shift;
    if ($('#l-tickets', md)) $('#l-tickets', md).checked = !!x.tickets;
    if ($('#l-ptype', md) && !ptPend) { $('#l-ptype', md).value = x.ptype || ''; $('#l-pthint', md).textContent = ptypeHint(x.ptype || ''); }
    if ($('.lrepo', md)) $('.lrepo', md).hidden = !repoShown(x);
    $$('.ltkrow, .ltkhint', md).forEach(r => { r.hidden = !(swArea(x) || x.tickets); });  // 2.22.0 (#746)
    if ($('#l-tickets', md)) $('#l-tickets', md).checked = !!x.tickets;
    if ($('#l-rate', md) && document.activeElement !== $('#l-rate', md)) $('#l-rate', md).value = x.rate != null ? String(x.rate).replace('.', LOCALE().startsWith('de') ? ',' : '.') : '';
    if ($('#l-dayh', md) && document.activeElement !== $('#l-dayh', md)) $('#l-dayh', md).value = x.day_hours != null ? String(x.day_hours).replace('.', LOCALE().startsWith('de') ? ',' : '.') : '';
    if ($('#l-nag', md)) $('#l-nag', md).value = x.nag || '';
    if ($('#l-dab', md)) $('#l-dab', md).checked = !!x.checklist;
    if ($('#l-fam', md)) $('#l-fam', md).value = x.family || '';
  };
  let saving = Promise.resolve();
  const autosave = () => {
    if (!id) return saving;
    saving = saving.then(async () => {
      for (const t of pend.values()) clearTimeout(t);
      pend.clear();
      const cur = listById(id); if (!cur) return;
      const body = formBody(), diff = {};
      for (const k in body) if (lv(k, cur[k]) !== lv(k, body[k])) diff[k] = body[k];
      if (!Object.keys(diff).length) return;
      if (diff.folder && !folderNames().includes(diff.folder)) await api('PATCH', '/api/settings', {folders: JSON.stringify([...folderNames(), diff.folder])}).catch(() => {});
      const e = await listPatch(id, diff, null, {post: lsync});
      if (e === false) { lsync(); return; }
      lsaved(e);
    }).catch(() => {});
    return saving;
  };
  const later = el => { clearTimeout(pend.get(el.id)); pend.set(el.id, setTimeout(autosave, 900)); };
  if (id) {
    md.addEventListener('input', e => { if (['l-name', 'l-folder', 'l-rate', 'l-dayh'].includes(e.target.id)) later(e.target); });
    md.addEventListener('focusout', e => { if (['l-name', 'l-folder', 'l-rate', 'l-dayh'].includes(e.target.id)) { const empty = e.target.id === 'l-name' && !e.target.value.trim().replace(EMO_RE, ''); autosave().then(() => { if (empty) lsync(true); }); } });
    onRemove(md, () => { if (pend.size) autosave(); });
  }
  md.addEventListener('change', e => {
    if (e.target.id === 'l-kind') { const k = e.target.value; $('#l-khint', md).innerHTML = kindHint(k); $('.kproj', md).hidden = k !== 'project'; if ($('.lptype', md)) $('.lptype', md).hidden = k !== 'project'; if (id) autosave(); return; }
    if (id && e.target.id === 'l-ptype') {
      // 2.18.0 review (R1): arrow keys on a closed select fire "change" for every value passed; while the keyboard
      // walks the options only the hint follows, the type is saved once on Enter / leaving the field
      if (ptKeys) { ptPend = true; $('#l-pthint', md).textContent = ptypeHint(e.target.value); return; }
      ptypeChange(e.target.value); return;
    }
    if (id && ['l-view', 'l-depshift', 'l-tickets', 'l-nag', 'l-dab', 'l-fam'].includes(e.target.id)) { autosave(); return; }
    if (!id && e.target.id === 'l-fam' && ['shopping', 'packing'].includes(e.target.value) && $('#l-dab', md)) $('#l-dab', md).checked = true;
    if (id && e.target.id === 'l-showprog') { setProgHidden(id, !e.target.checked).then(() => lsaved(null)); return; }
  });
  // 2.18.0 (#408): the project type of an existing list: saved at once (one history step), then the dialog shows what
  // the server switched on, offers the type's missing sections and, for Software, the repository area
  const ptCommit = () => { const sel = $('#l-ptype', md); ptKeys = false; if (!ptPend || !sel) return; ptPend = false; ptypeChange(sel.value); };
  md.addEventListener('keydown', e => {
    if (e.target.id !== 'l-ptype') return;
    if (e.key === 'Enter') { if (ptPend) { e.preventDefault(); ptCommit(); } return; }
    // walking a CLOSED select (Alt+arrows / Space open the option list: its choice comes as one change)
    ptKeys = !e.altKey && (/^(Arrow(Up|Down|Left|Right)|Home|End|Page(Up|Down))$/.test(e.key) || (e.key.length === 1 && e.key !== ' '));
  });
  md.addEventListener('pointerdown', e => { if (e.target.id === 'l-ptype') ptKeys = false; });
  md.addEventListener('focusout', e => { if (e.target.id === 'l-ptype') ptCommit(); });
  if (id) onRemove(md, () => { const sel = $('#l-ptype', md); if (ptPend && sel) { ptPend = false; setListPtype(id, sel.value); } });  // closed while walking the options: still saved once
  // changes run one after the other; a change superseded meanwhile is skipped, so the offer always matches the type shown
  const ptypeChange = v => (ptRun = ptRun.then(() => { const sel = $('#l-ptype', md); if (md.isConnected && sel && sel.value === v) return ptypeChange1(v); }).catch(() => {}));
  const ptypeChange1 = async v => {
    await autosave();
    const sel = $('#l-ptype', md), r = await setListPtype(id, v, {post: () => lsync()});
    if (!md.isConnected) return;
    if (!r) { lsync(); return; }
    lsaved(r.e); lsync(); drawFields();
    const off = $('#l-ptoffer', md);
    if (off) ptypeOfferDraw(off, id, v, r.missing?.sections || []);
    if (v === 'software' && $('.lrepo', md)) {
      $('.lrepohint', md).hidden = false;
      $('.lrepo', md).scrollIntoView?.({block: 'nearest'});
    }
    sel?.focus();
  };
  const drawFields = () => { const box = $('#l-fields', md); if (box) box.innerHTML = fieldsBox(id); };
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'field-add') {  // the type was just switched to Project in this dialog: save it first (fields need a project)
      if (!isProject(id)) { try { await api('PATCH', '/api/lists/' + id, {kind: 'project'}); await load(); } catch { return; } }
      fieldModal(id, null, drawFields); return;
    }
    if (b.dataset.fedit) { fieldModal(id, fieldById(+b.dataset.fedit), drawFields); return; }
    if (b.dataset.fpin) {
      const f = fieldById(+b.dataset.fpin);
      try { await api('PATCH', '/api/fields/' + f.id, {pinned: !f.pinned}); } catch { return; }
      await load(); render(); drawFields(); return;
    }
    if (b.dataset.fup) {
      const fs = fieldsOf(id), i = fs.findIndex(f => f.id === +b.dataset.fup); if (i < 1) return;
      try { await api('PATCH', '/api/fields/' + fs[i].id, {sort: fs[i - 1].sort}); await api('PATCH', '/api/fields/' + fs[i - 1].id, {sort: fs[i].sort === fs[i - 1].sort ? fs[i].sort + 1 : fs[i].sort}); } catch { return; }
      await load(); render(); drawFields(); return;
    }
    if (b.dataset.m === 'share-open') { await autosave(); md.remove(); shareModal(id); return; }  // 2.6.0 (K12)
    if (b.dataset.m === 'tt-tpl') { await autosave(); ticketTplModal(id); return; }
    if (b.dataset.pt !== undefined) {  // 2.4.0 (#243 / #328): what the new project starts from
      $$('.ptcard', md).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', x === b); });
      const tp = b.dataset.pt.startsWith('tpl:');
      $('.ptdates', md).hidden = !tp;
      const pt = PTYPE_UI.find(x => x[0] === b.dataset.pt);
      // 2.22.0 (#749): every new list opens as a list (the board is one tap away)
      if ($('#l-tickets', md)) { $('#l-tickets', md).checked = b.dataset.pt === 'software'; $('#l-tickets', md).closest('.row').hidden = !!b.dataset.pt; }
      if (!$('#l-name', md).value.trim() && (tp || (pt && pt[0]))) $('#l-name', md).value = tp ? $('b', b).textContent : tr(pt[1]);
      return;
    }
    if (b.dataset.m === 'leave') {
      if (!await askConfirm(tr('Leave the list “{0}”?', listName(l.name)), tr('You will no longer see its tasks. The owner can share it with you again.'), {ok: tr('Leave list'), danger: true})) return;
      try { await api('DELETE', `/api/lists/${id}/members/${S.me.id}`); } catch { return; }
      md.remove(); await load(); go(START_KEY); return;
    }
    if (b.dataset.m === 'l-undo') { const el = $('.ssaved', md); if (el?._e && HIST.undo[HIST.undo.length - 1] === el._e) { el.classList.remove('on'); histStep('undo'); } return; }
    if (b.dataset.c !== undefined) { $$('#l-col button', md).forEach(x => x.classList.remove('on')); b.classList.add('on'); if (id) autosave(); }
    if (b.id === 'l-emo') { $('#l-emogrid', md).classList.toggle('hidden'); return; }
    if (b.dataset.licon) {  // 2.0.2: a picture instead of the emoji (the emoji leaves the name)
      const k = b.dataset.licon;
      const url = k === 'upload' ? await liconUpload(id) : await liconSet(id, k);
      if (url === null) return;
      if (!md.isConnected) return;
      const x = listById(id) || l;
      if (url && emo) { emo = ''; $$('#l-emogrid [data-emo]', md).forEach(y => y.classList.remove('on')); await autosave(); }
      $('#l-emo', md).innerHTML = x.icon ? licon(x, 'licon m') : emo || ic('list');
      const w = $('.lipickw', md); if (w) w.innerHTML = `<span class="muted lipl">${tr('Or a picture')}</span>${liconPickHtml(x)}`;
      if (url) $('#l-emogrid', md).classList.add('hidden');
      return;
    }
    if (b.dataset.emo !== undefined) {
      if (id && listById(id)?.icon && b.dataset.emo) await liconSet(id, 'none');  // 2.0.2: an emoji replaces the picture
      const w = $('.lipickw', md); if (w && listById(id)) w.innerHTML = `<span class="muted lipl">${tr('Or a picture')}</span>${liconPickHtml(listById(id))}`;
      emo = b.dataset.emo;
      $$('#l-emogrid button', md).forEach(x => x.classList.toggle('on', x === b && !!emo));
      $('#l-emo', md).innerHTML = emo || ic('list');
      $('#l-emogrid', md).classList.add('hidden');
      if (id) autosave();
      return;
    }
    const a = b.dataset.m;
    if (a === 'close') { if (id) await autosave(); md.remove(); }
    if (a === 'tpl') { await autosave(); md.remove(); saveTemplate({list_id: id, ...((listById(id) || l).kind === 'project' ? {relative: true} : {})}, lname(l)); return; }  // 2.4.0 (#328): projects keep their dates relative to the project start
    if (a === 'save' && !id) {  // a new list (an existing one saves itself)
      const nm = $('#l-name', md).value.trim().replace(EMO_RE, '');
      if (!nm) return $('#l-name', md).focus();
      const body = own ? {name: l.is_inbox && !emo && nm === tr('Inbox') ? (inboxDef(l.name) ? l.name : 'Eingang') : emo + nm, folder: fNorm($('#l-folder', md).value), view: $('#l-view', md).value, color: $('#l-col button.on', md)?.dataset.c || '', kind: $('#l-kind', md).value, ...($('#l-depshift', md) ? {dep_shift: $('#l-depshift', md).checked} : {}), ...($('#l-rate', md) ? {rate: $('#l-rate', md).value.trim()} : {}), ...($('#l-nag', md)?.value ? {nag: $('#l-nag', md).value} : {}), ...($('#l-dab', md)?.checked ? {checklist: true} : {}), ...($('#l-fam', md)?.value ? {family: $('#l-fam', md).value} : {})}
        : {folder: fNorm($('#l-folder', md).value), view: $('#l-view', md).value};  // members: only their own placement / view
      if (body.folder && !folderNames().includes(body.folder)) await api('PATCH', '/api/settings', {folders: JSON.stringify([...folderNames(), body.folder])});
      const {rate, nag, day_hours: _dh, ...b0} = body;
      const pt = body.kind === 'project' ? $('.ptcard.on', md)?.dataset.pt || '' : '';
      let n;
      if (pt.startsWith('tpl:')) {  // 2.4.0 (#328): the person's own template, dates from the project start (optionally to an end)
        try { n = {id: (await api('POST', `/api/templates/${+pt.slice(4)}/apply`, {name: body.name, folder: body.folder, ...(body.color ? {color: body.color} : {}), start: $('#l-pstart', md).value || today(), ...($('#l-pend', md).value ? {end: $('#l-pend', md).value} : {})})).list_id}; } catch { return; }
      } else {
        try { n = await api('POST', '/api/lists', pt ? {name: b0.name, folder: b0.folder, color: b0.color, ptype: pt} : b0); } catch { return; }
      }
      if (rate || nag) await api('PATCH', '/api/lists/' + n.id, {...(rate ? {rate} : {}), ...(nag ? {nag} : {})}).catch(() => {});
      md.remove(); await load(); go('l/' + n.id);
      modulesOnToast(n.modules_on);
      if (pt === 'software') projectNextSteps(n.id);
      return;
    }
    if (a === 'arch') { await autosave(); md.remove(); await listArchive(id, !l.archived); }
    if (a === 'sw-setup') { await autosave(); md.remove(); if (await setListPtype(id, 'software')) listModal(id); }  // 2.22.0 (#746)
    if (a === 'del') { if (await listDeleteForGood(id)) md.remove(); }
  });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT' && e.target.id !== 'l-emocustom' && !e.target.id.startsWith('lp-')) { if (id) { e.preventDefault(); autosave(); } else $('[data-m="save"]', md).click(); } });
  if (!own) { if (!isTouch()) setTimeout(() => $('#l-folder', md).focus(), 50); return; }
  let emoTouched = !!id;  // 2.22.0 (#682): the suggestion follows the name until the person picks something themselves
  md.addEventListener('click', e => { if (e.target.closest('#l-emogrid [data-emo]')) emoTouched = true; }, true);
  md.addEventListener('input', e => {
    if (e.target.id !== 'l-name' || emoTouched) return;
    const s = autoEmoji(e.target.value);
    if (s === emo) return;
    emo = s;
    const b = $('#l-emo', md); b.innerHTML = emo || ic('list'); b.title = emo ? tr('Suggested icon: tap to change or remove it') : tr('Choose icon');
    b.classList.toggle('sugg', !!emo);
    $$('#l-emogrid button', md).forEach(x => x.classList.toggle('on', !!emo && x.dataset.emo === emo));
  });
  md.addEventListener('input', e => {  // any emoji typed (or picked from the OS keyboard) into the custom field
    if (e.target.id !== 'l-emocustom') return;
    emoTouched = true;
    const m = e.target.value.match(EMO_RE);
    if (m) { emo = m[1]; $('#l-emo', md).innerHTML = emo; $$('#l-emogrid button', md).forEach(x => x.classList.remove('on')); if (id) later(e.target); }
  });
  if (!isTouch()) setTimeout(() => $('#l-name', md).focus(), 50);  // 2.13.0: touch: no keyboard popping up on open
}
// 2.1.2 (#349): hand a list to another person. j = GET /api/lists/{id}/owner (mode owner | takeover, candidates: active
// people, members first with their role). Two steps: pick the person, then confirm.
async function ownerModal(lid, name, j, done) {
  const take = j.mode === 'takeover', cands = j.candidates || [];
  if (!cands.length) { toast(tr('There is no other active person to hand it to')); return; }
  const def = (take ? cands.find(c => S.me && c.id === S.me.id) : cands.find(c => c.role)) || cands[0];
  const md = modal(`<h3>${esc(take ? tr('Take over “{0}”', name) : tr('Transfer ownership of “{0}”', name))}</h3>
    <div class="row"><label for="ow-to">${tr('New owner')}</label><select id="ow-to">${cands.map(c => `<option value="${c.id}" ${c.id === def.id ? 'selected' : ''}>${esc(c.name)}${S.me && c.id === S.me.id ? ' ' + tr('(me)') : ''}${c.role ? ' · ' + esc(roleLabel(c.role)) : ''}</option>`).join('')}</select></div>
    <div class="shint keep">${esc(take ? tr('The new owner can rename, archive and delete the list and decides who is in it. {0} stays in the list: an agent as a member, a person as a list admin.', j.owner?.name || '')
      : tr('The new owner can rename, archive and delete the list and decides who is in it. You stay in the list as a list admin. Agents cannot own lists.'))}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${take ? tr('Take over') : tr('Transfer')}</button></div>`);
  md.classList.add('owmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const to = cands.find(c => c.id === +$('#ow-to', md).value); if (!to) return;
    if (!await askConfirm(tr('Make {0} the owner of “{1}”?', to.name, name), take ? '' : tr('Only the new owner can hand it back.'), {ok: take ? tr('Take over') : tr('Transfer ownership'), danger: !take})) return;
    b.disabled = true;
    try { await api('POST', `/api/lists/${lid}/owner`, {user_id: to.id}); } catch { b.disabled = false; return; }
    md.remove(); toast(tr('{0} is now the owner of “{1}”', to.name, name));
    done && done(); await load(); render();
  });
}
// Settings > Administration: the lists nobody can manage (owner = an agent or a disabled user), with "Take over"
const orphHtml = () => `<h4 id="s-orph-h">${tr('Lists owned by agents or disabled users')}</h4>
  <div class="shint">${tr('Nobody can manage who is in these lists: agents cannot share, disabled users cannot log in. Take a list over for yourself or hand it to another person.')}</div>
  <div class="members" id="s-orph"><div class="muted mhint">${tr('Loading…')}</div></div>`;
async function orphDraw(md) {
  const box = $('#s-orph', md); if (!box) return;
  let j; try { j = await calReq('GET', '/api/admin/lists/orphaned'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  box.innerHTML = j.lists.length ? j.lists.map(l => `<div class="mrow" data-olid="${l.id}">${av(l.owner_id, l.owner_name)}<span class="n"><b>${esc(listName(l.name))}</b>
      <small class="muted">${esc(l.reason === 'agent' ? tr('owned by the agent {0}', l.owner_name) : tr('owned by the disabled user {0}', l.owner_name))} · ${esc(trn('{0} member', '{0} members', l.members))} · ${esc(trn('{0} task', '{0} tasks', l.tasks))}${l.archived ? ' · ' + esc(tr('archived')) : ''}</small></span>
      <button class="btn sm" data-orph="${l.id}">${ic('user', 's')} ${tr('Take over')}</button></div>`).join('')
    : `<div class="muted mhint">${tr('None: every list is owned by an active person.')}</div>`;
}
function orphWire(md) {
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-orph]'); if (!b) return;
    const j = $('#s-orph', md)?._j, l = j?.lists.find(x => x.id === +b.dataset.orph); if (!l) return;
    ownerModal(l.id, listName(l.name), {mode: 'takeover', owner: {id: l.owner_id, name: l.owner_name}, candidates: j.candidates.filter(c => c.id !== l.owner_id)}, () => orphDraw(md));
  });
}
// Settings > Appearance: all per-device visual settings, applied instantly (no Save), with a live preview
const LOOK_KEYS = ['theme', 'density', 'densitySide', 'densityRows', 'densSideV', 'densRowsV', 'fsize', 'font', 'accent'];  // 2.18.0: densSideV / densRowsV
const THEMES = [['auto', N_('Automatic')], ['dark', N_('Dark')], ['light', N_('Light')]];
const DENSITIES = [['compact', N_('Compact')], ['comfortable', N_('Comfortable')], ['custom', N_('Custom|density')]];
const FSIZE_ORDER = ['s', 'm', 'l', 'xl'];
const zPct = z => `${Math.round(z * 100)} %`;
function lookHtml() {
  const on = (k, v) => `data-look="${k}" data-v="${v}" aria-pressed="${lookCur(k) === v}" class="${lookCur(k) === v ? 'on' : ''}"`;
  const seg = (k, opts) => `<div class="seg wrap" id="s-${k}" role="group">${opts.map(([v, n]) => `<button ${on(k, v)}>${tr(n)}</button>`).join('')}</div>`;
  return `<div class="lookpv" inert aria-hidden="true">
      <div class="lpv-head"><b>${tr('Today')}</b><span class="lpv-n">2</span></div>
      <div class="trow pr5"><span class="chk p5"></span><div class="tmain"><div class="ttl">${tr('Call the plumber about the kitchen tap')}</div><div class="meta"><span class="dt today">${ic('cal', 's')}${tr('Today')} 09:30</span><span class="tag">#${tr('home')}</span></div></div></div>
      <div class="trow pr1"><span class="chk p1"></span><div class="tmain"><div class="ttl">${tr('Renew the library books')}</div><div class="meta"><span class="dt">${ic('cal', 's')}${dayLabel(addDays(today(), 3))}</span><span class="subc">${ic('sub', 's')}1/3</span></div></div></div>
      <div class="lpv-foot"><span class="btn sm pri">${ic('plus', 's')} ${tr('Add task')}</span><span class="lpv-link">${tr('Show completed')}</span><span class="lpv-prio flag-5">${ic('flag', 's')}${tr('high')}</span></div>
    </div>
    <h4>${tr('Color scheme')}<span class="devtag">${tr('This device')}</span></h4>
    <div class="row">${seg('theme', THEMES)}</div>
    <h4>${tr('Density')}</h4>
    <div class="row">${seg('density', DENSITIES)}</div>
    ${densityMode() === 'custom' ? ['side', 'rows'].map(k => `<div class="row lkdens"><label class="lkdl" for="s-dens-${k}">${k === 'side' ? tr('Sidebar row spacing') : tr('Task row spacing')}</label><span class="lkA" aria-hidden="true">${tr('tight|spacing')}</span><input type="range" id="s-dens-${k}" data-dens="${k}" min="0" max="100" step="1" value="${densV(k)}" aria-valuetext="${densV(k)} %"><span class="lkA" aria-hidden="true">${tr('airy|spacing')}</span><output id="s-dens-${k}-v" for="s-dens-${k}">${densV(k)} %</output></div>`).join('') : ''}
    <div class="shint">${tr('Compact fits more lists and tasks on the screen; comfortable has more room. Custom: a slider each for the spacing of the sidebar and of the task rows. Touch targets stay 44 px. Default: comfortable on phones, compact on computers.')}</div>
    <h4>${tr('Font size')}</h4>
    <div class="row lkfs"><span class="lkA" aria-hidden="true">A</span><input type="range" id="s-fsize" min="${FS_MIN}" max="${FS_MAX}" step="5" value="${fsPct()}" aria-label="${esc(tr('Font size'))}" aria-valuetext="${fsPct()} %"><span class="lkA lkA2" aria-hidden="true">A</span><output id="s-fsv" for="s-fsize">${fsPct()} %</output><button class="btn sm" data-m="fs-reset" ${fsPct() === 100 ? 'disabled' : ''}>${tr('Reset (100 %)')}</button></div>
    <div class="shint">${tr('Scales the whole interface: text, rows, icons, spacing and dialogs.')}</div>
    <h4>${tr('Font')}</h4>
    <div class="lkopts lkfont" id="s-font" role="group">${LOOK.font.map(([v, n]) => `<button ${on('font', v)}><span class="lkAa lkf-${v}">Aa</span><span class="lkn">${tr(n)}</span></button>`).join('')}</div>
    <div class="shint">${tr('Atkinson Hyperlegible is designed for low vision readers. Dates, times, counters and tags always stay in Geist Mono.')}</div>
    <h4>${tr('Accent color')}</h4>
    <div class="lkopts lkacc" id="s-accent" role="group">${LOOK.accent.map(([v, n, d, l]) => `<button ${on('accent', v)} style="--sw-d:${d};--sw-l:${l}" title="${tr(n)}"><i class="lksw"></i><span class="lkn">${tr(n)}</span></button>`).join('')}</div>
    <div class="row lkreset"><button class="btn sm" data-m="look-reset">${ic('undo', 's')} ${tr('Reset to defaults')}</button><span class="muted">${tr('Applies to this device only.')}</span></div>`;
}
const lookCur = k => k === 'theme' ? LS.get('theme', 'auto') : k === 'density' ? densityMode() : k === 'densitySide' ? sideDensityPref() : k === 'densityRows' ? densityPref() : k === 'fsize' ? fsPct() : lookPref(k);
function lookRedraw(md, focusSel) {  // re-render the pane (states + preview) and keep the keyboard focus
  const p = $('#s-lookin', md); if (!p) return;
  p.innerHTML = lookHtml();
  if (focusSel) $(focusSel, p)?.focus();
}
