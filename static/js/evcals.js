// @ts-check
/* Kalmido web client: the dialog Calendars (evCalsModal: own calendars, shares, the calendar filter) (2.1156.0, #4280: moved here from calevents.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

// 2.46.2 (#1659): a calendar's new name shows at once (optimistic, an error puts the old one back), no reload of everything
function evCalRename(id, name, draw) {
  const put = () => {
    const x = evCal(id), y = (S.cal.evcals || {})[id], o1 = x?.name, o2 = y?.name;
    if (x) x.name = name; if (y) y.name = name;
    return () => { if (x) x.name = o1; if (y) y.name = o2; };
  };
  return optWrite(put, () => evcPatch(id, {name}), draw).then(() => cvxCals(true).then(draw), () => {});
}
// 2.559.0 (#4659): "Show in my calendar" of an own calendar: c.hidden at once; hidden, its events leave the shown range (shown,
// they come with the range fetched after the answer)
function evCalShowPut(id, on) {
  return () => {
    const c = evCal(id), its = S.cal.items, keep = on ? its : its.filter(x => !(x.own && x.cal === id));
    if (!c || (c.hidden === !on && keep.length === its.length)) return null;
    const h0 = c.hidden; c.hidden = !on; S.cal.items = keep;
    return () => { const x = evCal(id); if (x) x.hidden = h0; if (S.cal.items === keep) S.cal.items = its; };
  };
}
// ---- 2.624.0 (#3946): "Per project" in the Calendars window: the lists grouped by folder (sidebar.js folderNames, the own
// sidebar paths), a switch per folder (cal_folders_hidden); a list or subfolder below a folder that is off shows its switch
// greyed with "Off through the folder". From CVF_SEARCH_MIN lists a search on top filters by list and folder names (data-cvfq:
// the name + the folder path), hits with their folder path. In a list's own calendar view the rule does not apply (lcal_has).
const CVF_SEARCH_MIN = 8;
function cvf_lists(lists, hidL, hidF, tasksOn, sw, q) {
  const ind = d => d ? `padding-left:${(1.5 + d * 1.25).toFixed(2)}rem` : '';
  const viaTxt = `<span class="muted"> · ${esc(tr('Off through the folder'))}</span>`;
  const path = f => f ? `<span class="muted cvfpath" hidden> · ${esc(fDisp(f))}</span>` : '';
  const lrow = l => {
    const via = cvxFolderOff(l.folder, hidF);
    return `<div class="cvxrow sub" data-cvfq="${esc((lname(l) + ' ' + (l.folder || '')).toLowerCase())}" style="--cc:${cssColor(lp_col(l)) || 'var(--muted)'};${ind(fDepth(l.folder || ''))}">${sw(String(l.id), 'list', !via && !hidL.includes(l.id), !tasksOn || via, tr('Show {0} in my calendar', lname(l)))}<i class="cevdot"></i><span class="evcn">${esc(lname(l))}${path(l.folder)}${via ? viaTxt : ''}</span></div>`;
  };
  const frow = f => {
    const via = cvxFolderOff(fParent(f), hidF);
    return `<div class="cvxrow cvfrow" data-cvfq="${esc(f.toLowerCase())}" data-folder="${esc(f)}" style="${ind(fDepth(f) - 1) || 'padding-left:1.5rem'}">${sw(esc(f), 'folder', !via && !hidF.includes(f), !tasksOn || via, tr('Show folder {0} in my calendar', fName(f)))}${ic('folder', 's')}<span class="evcn">${esc(fName(f))}${path(fParent(f))}${via ? viaTxt : ''}</span></div>`;
  };
  const own = lists.filter(l => !l.is_inbox);
  const rows = [...own.filter(l => !l.folder).map(lrow),
    ...folderNames().filter(f => own.some(l => fUnder(l.folder, f))).flatMap(f => [frow(f), ...own.filter(l => l.folder === f).map(lrow)]),
    ...lists.filter(l => l.is_inbox).map(lrow)];
  const srch = lists.length >= CVF_SEARCH_MIN ? `<div class="cvxrow cvfsrch"><input type="search" data-cvfq-in value="${esc(q || '')}" placeholder="${esc(tr('Search projects and folders'))}" aria-label="${esc(tr('Search projects and folders'))}" autocomplete="off" maxlength="200" style="flex:1;min-width:0"></div>` : '';
  return `<div class="cvflists">${srch}${rows.join('')}<p class="muted cvfnone" hidden>${esc(tr('No project or folder found'))}</p></div>`;
}
function cvf_filter(md, q) {
  const box = $('.cvflists', md); if (!box) return;
  const s = String(q || '').trim().toLowerCase(); let n = 0;
  for (const r of box.querySelectorAll('[data-cvfq]')) {
    const hit = !s || r.dataset.cvfq.includes(s); r.hidden = !hit; n += hit;
    for (const p of r.querySelectorAll('.cvfpath')) p.hidden = !s;
  }
  $('.cvfnone', box).hidden = !s || n > 0;
}

// ---- calendars: list, new, rename / colour, hide, share, import (ICS), export, delete; the phone setup
async function evCalsModal() {
  // 2.36.1 (#1127 #956): ONE window for everything the calendar shows: "Tasks" (all dated tasks, fold-out: per list), my own
  // calendars, then the subscriptions; each calendar row has three switches: in my calendar (evcals.hidden /
  // cal_subs.visible, the same field as in the settings), on Today (today_cals_hidden) and when planning (plan_cals_off).
  // On a phone the dialog is the usual sheet from below.
  // 2.828.0 (#5464): readable column heads (Calendar / Today / Plan, never cut), on a phone one switch "Show" per calendar and the
  // other two in its "…" menu; "Done" closes as the main button, the side paths are quiet links, "New calendar" and the trash
  // are rows at the end of my calendars, "Tasks with a date" a row like the others (its "…" opens the projects)
  // 2.1077.0 (#5461): the window opens at once (it said nothing while the people loaded); only "Share…" waits for them
  const usersP = collab() ? evPeople() : Promise.resolve([]);
  await loadCss('calendar').catch(() => {});  // the window's styles (calendar.css), also when it opens outside the calendar
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${ic('cal', 's')} ${tr('Calendars')}</h3><span class="spacer"></span><button class="iconbtn" data-evc="close" aria-label="${tr('Close')}">${ic('x')}</button></div><div id="evc-body">${/*html-ok*/ loadingHtml('sec') /* 2.1077.0 (#5461) */}</div>
    <div class="foot evcfoot"><span class="evclinks">${feat('events') ? `<button type="button" class="linkbtn" data-evc="phone">${tr('On the phone…')}</button>` : ''}${feat('events') && !S.me?.kid ? `<button type="button" class="linkbtn" data-evc="booking">${tr('Booking page…')}</button>` : ''}${S.calendars?.enabled ? `<button type="button" class="linkbtn" data-evc="subs">${tr('Subscriptions…')}</button>` : ''}</span><span class="spacer"></span><button type="button" class="btn pri" data-evc="done">${tr('Done')}</button></div>`);
  md.classList.add('evcmodal');
  const narrow = () => matchMedia('(max-width: 599px)').matches;  // a phone: one switch per row, Today / Plan in the menu
  const st = {lists: false, trash: null};  // 2.566.0 (#4707): trash = the calendars in the trash once opened
  const sw = (key, kind, on, dis, label) => `<label class="swc cvx-${/*html-ok*/ kind /* a constant of this file */} ${dis ? 'off' : ''}" title="${esc(label)}"><input type="checkbox" data-cvx="${kind}" data-key="${key}" ${on ? 'checked' : ''} ${dis ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(label)}</span></label>`;
  const three = c => {  // Today + planning (off while the calendar is hidden: hidden = gone from Today and the planner too)
    const off = !c.on;
    return sw(c.key, 'today', c.on && !cvxList('today_cals_hidden').includes(c.key), off, tr('Show {0} on Today', c.name))
      + sw(c.key, 'plan', c.on && !cvxList('plan_cals_off').includes(c.key), off, tr('Consider {0} when planning', c.name));
  };
  const pad = '<span class="cvxpad" aria-hidden="true"></span>';  // an empty cell of the Today / Plan columns
  const head = `<div class="cvxhead"><span class="cvxhn"></span><span class="cvxc cvx-show" title="${esc(tr('In my calendar'))}"><span class="cvxwide">${tr('Calendar|col')}</span><span class="cvxnarrow">${tr('Show')}</span></span><span class="cvxc cvx-today" title="${esc(tr('On Today'))}">${tr('Today')}</span><span class="cvxc cvx-plan" title="${esc(tr('When planning'))}">${tr('Plan|col')}</span><span class="cvxc cvxm" aria-hidden="true"></span></div>`;
  const draw = () => {
    const cs = S.evcals || [], hidL = cvxList('cal_lists_hidden'), hidF = cvxList('cal_folders_hidden'), tasksOn = S.settings.cal_tasks !== '0';
    const lists = [...S.lists.filter(l => !l.archived && !l.is_inbox), ...S.lists.filter(l => !l.archived && l.is_inbox)];
    const nOff = lists.filter(l => cvxListOff(l.id, hidL, hidF)).length;  // 2.624.0 (#3946): also the ones off through a folder
    // tasks: one switch for all dated tasks, fold-out: one per list (the lists are only listed, never changed here);
    // 2.624.0 (#3946): grouped by folder like the sidebar (own lists first, then folder by folder, subfolders indented, the
    // inbox last), a switch per folder (cal_folders_hidden: its lists and subfolders off, also later ones); from 8 lists a search
    const tl = `<div class="cvxgrp">${tr('Tasks')}</div>${/*html-ok*/ head /* tr() only */}<div class="cvxrow cvxtasks" style="--cc:var(--accent)">
      <i class="cevdot"></i><span class="evcn">${tr('Tasks with a date')}${nOff && tasksOn ? `<span class="muted"> · ${esc(trn('{0} project hidden', '{0} projects hidden', nOff))}</span>` : ''}</span>
      ${sw('tasks', 'tasks', tasksOn, false, tr('Show tasks in my calendar'))}${/*html-ok*/ pad + pad /* constant markup */}${''/* menu-ok: unfolds the per-project switches in place (view options, no menu) */}<button class="iconbtn cvxfold" data-evc="lists" aria-expanded="${st.lists}" aria-label="${esc(tr('Per project'))}" title="${esc(tr('Per project'))}">${ic('dots')}</button></div>
      ${st.lists ? cvf_lists(lists, hidL, hidF, tasksOn, sw, st.q) : ''}`;
    const own = !feat('events') ? '' : `<div class="cvxgrp">${tr('My calendars')}</div>${cs.length ? `<ul class="evclist">${cs.map(c => `<li class="evcrow" style="--cc:${cssColor(c.color) || 'var(--accent)'}">
      <i class="cevdot"></i><span class="evcn">${esc(c.name)}${wsOn() && c.role === 'owner' ? `<span class="muted wslbl"> · ${esc(wsLabel(c.org_id))}</span>` : ''}${c.role !== 'owner' ? `<span class="muted"> · ${esc(c.owner_name || '')} · ${esc(c.role === 'edit' ? tr('can edit') : tr('can view'))}</span>` : c.members?.length ? `<span class="muted"> · ${esc(trn('shared with {0} person', 'shared with {0} people', c.members.length))}</span>` : ''}</span>
      <label class="swc cvx-show" title="${esc(tr('Show in my calendar'))}"><input type="checkbox" data-evcshow="${c.id}" ${c.hidden ? '' : 'checked'}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Show {0} in my calendar', c.name))}</span></label>
      ${three({key: `e:${c.id}`, name: c.name, on: !c.hidden})}
      <button data-rowmenu="evcrow" class="iconbtn" data-evcmenu="${c.id}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', c.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></li>`).join('')}</ul>`
      : `<p class="muted">${tr('No calendar yet. A new event creates one.')}</p>`}
      <button type="button" class="evcrowbtn" data-evc="new">${ic('plus', 's')}<span>${tr('New calendar')}</span></button>`;
    const subs = cvxVisibleCals(true).filter(c => !c.own);
    const sb = !S.calendars?.enabled ? '' : `<div class="cvxgrp">${tr('Subscriptions')}</div>${subs.length ? subs.map(c => `<div class="cvxrow" style="--cc:${cssColor(c.color)}">
      <i class="cevdot"></i><span class="evcn">${esc(c.name)}</span>${sw(c.key, 'show', c.on, false, tr('Show {0} in my calendar', c.name))}${three(c)}
      <button data-rowmenu="cvxrow" class="iconbtn" data-cvxmenu="${c.key}" data-name="${esc(c.name)}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', c.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>`).join('')
      : `<p class="muted">${tr('No subscriptions yet. Add one under Settings > Integrations > Calendars.')}</p>`}`;
    // 2.566.0 (#4707): the calendars in the trash (the shared core's trash): opened on demand, restore with their events
    const tr2 = !feat('events') ? '' : `<button type="button" class="evcrowbtn evctrbtn" data-evc="trash" aria-expanded="${!!st.trash}">${ic('trash', 's')}<span>${tr('Trash')}</span>${ic('right', 's')}</button>${!st.trash ? ''
      : st.trash.items.length ? `<ul class="evclist evctrash" aria-label="${esc(tr('Trash'))}">${st.trash.items.map(c => `<li class="evcrow" style="--cc:${cssColor(c.color) || 'var(--accent)'}"><i class="cevdot"></i><span class="evcn">${esc(c.name)}<span class="muted"> · ${esc(trn('{0} event', '{0} events', c.events))} · ${esc(tr('In the trash since {0}', fmtDate((c.deleted_at || '').slice(0, 10))))}</span></span><button type="button" class="btn sm" data-evctr="${c.id}">${ic('undo', 's')} ${tr('Restore')}</button></li>`).join('')}</ul>`
      : st.trash.err ? errorState({size: 'row', retry: async () => { st.trash = await evcTrash(); draw(); }})  // 2.1077.0 (#5461): not "empty" when it failed
      : `<p class="muted">${tr('The trash is empty')}</p>`}${st.trash?.trash_days ? `<p class="muted">${esc(trashNote(tr('Calendars in the trash are deleted permanently after {0} days, with their events.', st.trash.trash_days)))}</p>` : ''}`;
    $('#evc-body', md).innerHTML = tl + own + tr2 + sb + (typeof abc_group === 'function' ? abc_group() : '');  // 2.155.0 B (#2076)
    cvf_filter(md, st.q);  // 2.624.0 (#3946)
  };
  const redraw = () => { cvxRedraw(); draw(); };
  // 2.828.0 (#5464): a phone's row menu carries the switches "On Today" and "When planning" (ticked = on; off while hidden)
  const cvxNarrowItems = (key, on) => !narrow() ? [] : [
    {label: tr('On Today'), icon: 'sun', on: on && !cvxList('today_cals_hidden').includes(key), dis: !on, fn: async () => { await cvxOff('today_cals_hidden', key, !cvxList('today_cals_hidden').includes(key)); draw(); renderView(); }},
    {label: tr('When planning'), icon: 'clock', on: on && !cvxList('plan_cals_off').includes(key), dis: !on, fn: async () => { await cvxOff('plan_cals_off', key, !cvxList('plan_cals_off').includes(key)); draw(); }}, '-'];
  const refresh = async () => { await load().catch(() => {}); await cvxCals(true).catch(() => {}); redraw(); };
  md.addEventListener('input', (/** @type {any} */ e) => { if (e.target.matches?.('[data-cvfq-in]')) { st.q = e.target.value; cvf_filter(md, st.q); } });  // 2.624.0 (#3946)
  md.addEventListener('change', async (/** @type {any} */ e) => {
    const s = e.target.closest('[data-evcshow]');
    if (s) {  // 2.559.0 (#4659): switched at once (a hidden calendar's events leave the views), an error switches it back
      const id = +s.dataset.evcshow, on = s.checked;
      try { await evOpt(evCalShowPut(id, on), () => evcPatch(id, {hidden: !on}), () => { draw(); renderView(); }); } catch { s.checked = !on; draw(); return; }
      redraw(); return;
    }
    const x = e.target.closest('[data-cvx]'); if (!x) return;
    const kind = x.dataset.cvx, key = x.dataset.key, on = x.checked;
    if (kind === 'tasks') { await cvxSave('cal_tasks', on ? '1' : '0'); redraw(); return; }
    if (kind === 'list') { await cvxOff('cal_lists_hidden', +key, !on); redraw(); return; }
    if (kind === 'folder') { await cvxOff('cal_folders_hidden', key, !on); redraw(); return; }  // 2.624.0 (#3946)
    if (kind === 'today') { await cvxOff('today_cals_hidden', key, !on); renderView(); return; }
    if (kind === 'plan') { await cvxOff('plan_cals_off', key, !on); return; }
    if (kind === 'show') { if (!await cvxShow(key, on)) { x.checked = !on; return; } draw(); }
  });
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const sm = e.target.closest('[data-cvxmenu]');
    if (sm) {
      const key = sm.dataset.cvxmenu;
      menu(sm, [...cvxNarrowItems(key, cvxVisibleCals(true).find(x => x.key === key)?.on !== false), {label: tr('Only this calendar'), icon: 'eye', fn: async () => { await cvxOnly(key); draw(); }},
        {label: tr('Show all calendars'), icon: 'all', fn: async () => { await cvxAll(); draw(); }}, ...(typeof spl_item === 'function' ? spl_item('#cal') : []) /* 2.742.0 (#4858) */, '-',
        {label: tr('Subscriptions…'), icon: 'gear', sub: tr('Settings > Integrations > Calendars'), fn: () => { md.remove(); settingsModal('calendars'); }}]);
      return;
    }
    const m = e.target.closest('[data-evcmenu]');
    if (m) {
      const c = evCal(+m.dataset.evcmenu); if (!c) return;
      const own = c.role === 'owner';
      menu(m, [...cvxNarrowItems(`e:${c.id}`, !c.hidden), own && {label: tr('Rename…'), icon: 'edit', fn: async () => { const n = await askPrompt(tr('Rename the calendar'), c.name, {input: {max: 100}}); if (n && n.trim()) evCalRename(c.id, n.trim(), redraw); }},  // 2.46.2 (#1659): at once
        own && {label: tr('Colour…'), icon: 'palette', next: 1, fn: () => calColorPop(m, LCOLORS.filter(Boolean), c.color, async col => { try { await evcPatch(c.id, {color: col}); } catch { return; } refresh(); })},
        own && wsOn() && {label: tr('Workspace…'), icon: 'brief', next: 1, fn: () => wsMoveMenu(m, c.org_id, async org => { try { await evcPatch(c.id, {org_id: org}); } catch { return; } refresh(); })},
        own && collab() && {label: tr('Share…'), icon: 'users', fn: async () => evShareModal(c, await usersP, refresh)},
        evWrite(c) && {label: tr('Import a calendar file (ICS)…'), icon: 'upload', fn: () => evImport(c, refresh)},
        {label: tr('Export (ICS)'), icon: 'download', fn: () => { location.href = `/api/evcals/${c.id}/export.ics`; }},
        {label: tr('Subscription link…'), icon: 'link', fn: () => evf_modal(c)},  // 2.111.0 B (#2056): evinvite.js
        {label: tr('Only this calendar'), icon: 'eye', fn: async () => { await cvxOnly(`e:${c.id}`); draw(); }},  // 2.36.1 (#1127)
        {label: tr('Show all calendars'), icon: 'all', fn: async () => { await cvxAll(); draw(); }},
        !own && {label: tr('Leave this calendar'), icon: 'logout', fn: async () => { if (!await askConfirm(tr('Leave the calendar “{0}”?', c.name), '', {ok: tr('Leave'), danger: true})) return; try { await api('DELETE', `/api/evcals/${c.id}/members/${S.me.id}`); } catch { return; } refresh(); }},
        own && {label: tr('Delete…'), icon: 'trash', cls: 'danger', fn: async () => { if (!await askConfirm(tr('Delete the calendar “{0}” with all its events?', c.name), tr('They can be restored from the trash.'), {ok: tr('Delete'), danger: true})) return; try { await api('DELETE', `/api/evcals/${c.id}`); } catch { return; } st.trash = null; calInvalidate(); await refresh(); renderView();
          // 2.800.0 (#5466): the toast takes it back (the trash's restore, with its events)
          toast(tr('Calendar “{0}” deleted', c.name), async () => { try { await api('POST', `/api/evcals/${c.id}/restore`); } catch { return; } st.trash = null; calInvalidate(); if (md.isConnected) await refresh(); else await cvxCals(true).catch(() => {}); renderView(); }); }}]);  // 2.566.0 (#4707): into the trash
      return;
    }
    const rb = e.target.closest('[data-evctr]');
    if (rb) {  // 2.566.0 (#4707): out of the trash with its events
      try { await api('POST', `/api/evcals/${+rb.dataset.evctr}/restore`); } catch { return; }
      toast(tr('Restored')); st.trash = null; calInvalidate(); await refresh(); renderView(); return;
    }
    const b = e.target.closest('[data-evc]'); if (!b) return;
    if (b.dataset.evc === 'trash') { st.trash = st.trash ? null : await evcTrash(); draw(); return; }
    if (b.dataset.evc === 'close' || b.dataset.evc === 'done') md.remove();
    if (b.dataset.evc === 'lists') { st.lists = !st.lists; draw(); }
    if (b.dataset.evc === 'phone') { md.remove(); settingsModal('caldav'); }  // 2.365.2 B (#2789): the steps live in Settings > Integrations
    if (b.dataset.evc === 'booking') { md.remove(); apbOpen(); }  // 2.94.0 B (#1929): apptbook.js (lazy module calendar)
    if (b.dataset.evc === 'subs') { md.remove(); settingsModal('calendars'); }
    if (b.dataset.evc === 'new') {
      const n = await wsAskNew(tr('New calendar'));  // 2.30.0 (#1036): with its workspace
      if (!n) return;
      try { await api('POST', '/api/evcals', n); } catch { return; }
      refresh();
    }
  });
  // 2.520.0 (#3506): the buttons are in the dialog from the start, so the handlers come before the wait for the calendars (a click
  // in that gap was lost: CI of 2.520.0, p2365_2_b_ui "On the phone…")
  await cvxCals(true).catch(() => {});
  draw();
  loadModule('calabs').then(() => { abc_wire(md, draw); draw(); }).catch(() => {});  // 2.155.0 B (#2076): holidays + absences
}
// 2.1077.0 (#5461): the calendars in the trash; a failed fetch is marked (err), the window then says so with "Try again"
const evcTrash = () => api('GET', '/api/evcals/trash').catch(() => ({items: [], err: 1}));
function evShareModal(c, users, done) {
  // 2.800.0 (#5466): the X on top like every other dialog
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${tr('Share {0}', esc(c.name))}</h3><span class="spacer"></span><button class="iconbtn" data-evs="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div><div class="shws"></div><div id="evs-list"></div>
    <div class="row"><label for="evs-user">${tr('Person')}</label><select id="evs-user" data-sheet-av>${shWsOptions(users, c.org_id || null, c.members)}</select>
      <select id="evs-role" aria-label="${esc(tr('Role'))}"><option value="view">${tr('can view')}</option><option value="edit">${tr('can edit')}</option></select><button class="btn sm pri" data-evs="add">${tr('Share')}</button></div>
    <div class="shint">${tr('People with “can view” see the events, with “can edit” they also change them. In their phone the calendar appears next to their own.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-evs="close">${tr('Done')}</button></div>`);
  const names = new Map(users.map(u => [u.id, u.display_name]));
  const draw = () => { $('#evs-list', md).innerHTML = (c.members || []).length ? `<ul class="evclist">${c.members.map(m => `<li class="evcrow">${av(m.user_id, names.get(m.user_id) || '')}<span class="evcn">${esc(names.get(m.user_id) || '?')} <span class="muted">· ${esc(m.role === 'edit' ? tr('can edit') : tr('can view'))}</span></span><button class="iconbtn" data-evsrm="${m.user_id}" aria-label="${esc(tr('Stop sharing with {0}', names.get(m.user_id) || ''))}">${ic('x', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('Not shared yet.')}</p>`; };
  const wsDraw = () => {  // 2.46.4 (#1737)
    shWsFill($('.shws', md), c.org_id || null, a => wsMoveMenu(a, c.org_id, async org => {
      try { await evcPatch(c.id, {org_id: org}); } catch { return; }
      c.org_id = org; wsDraw(); $('#evs-user', md).innerHTML = shWsOptions(users, c.org_id || null, c.members); shWsPick($('#evs-user', md)); done();
    }));
  };
  wsDraw(); shWsPick($('#evs-user', md));
  draw();
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const rm = e.target.closest('[data-evsrm]');
    if (rm) { try { await api('DELETE', `/api/evcals/${c.id}/members/${rm.dataset.evsrm}`); } catch { return; } c.members = c.members.filter(m => m.user_id !== +rm.dataset.evsrm); draw(); done(); return; }
    const b = e.target.closest('[data-evs]'); if (!b) return;
    if (b.dataset.evs === 'close') md.remove();
    if (b.dataset.evs === 'add' && $('#evs-user', md).value) {
      try { const j = await api('PUT', `/api/evcals/${c.id}/members`, {user_id: +$('#evs-user', md).value, role: $('#evs-role', md).value}); c.members = j.members; } catch { return; }
      draw(); done();
    }
  });
}
