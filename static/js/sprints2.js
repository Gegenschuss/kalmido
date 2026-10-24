// @ts-check
/* Kalmido web client: sprints of a project list (2.43.0), the dialogs and the writes: assigning (menu), the settings, editing,
   planning, the list of sprints, closing. Moved out of sprints.js and loaded on their first use (2.149.0 F, #2518; lazyload.js
   module sprints, stand-ins in LD_CALL). The filter, the header, the row chip, the menu entries and the clicks stay in
   sprints.js (loaded at start).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- assigning: task menu, multi-selection, drop on the header; one undo step each
async function spr_assign(ids, sid, lab) {
  ids = ids.filter(i => { const t = S.tasks.get(i); return t && (t.sprint_id || null) !== (sid || null) && !isMs(t); });
  if (!ids.length) return;
  const snaps = ids.map(i => snapTask(S.tasks.get(i)));
  let j;
  try { j = await api('POST', '/api/tasks/batch', {ids, action: 'patch', data: {sprint_id: sid || null}}); } catch { return; }
  if (j?.errors?.length) toast(j.errors[0]);
  await load(); render();
  const pairs = snaps.map(b => [b, snapTask(S.tasks.get(b.id)), ['sprint_id']]);
  const msg = lab || (sid ? tr('In {0}', spr_name(spr_byId(spr_list(snaps[0].list_id), sid))) : tr('Moved to the backlog'));
  const e = histFields(msg, pairs, {res: j, fields: ['sprint_id']});
  if (e) offerUndo(msg, e); else toast(msg);
}
function spr_pick(anchor, ids) {
  const t = S.tasks.get(ids[0]), l = t && spr_list(t.list_id); if (!l) return;
  const cur = ids.length === 1 ? t.sprint_id || null : undefined;
  menu(anchor, [...spr_open(l).map(s => ({label: spr_name(s) + ' · ' + spr_range(s) + (s.state === 'active' ? ' · ' + tr('running') : ''), icon: 'target', on: cur === s.id, fn: () => spr_assign(ids, s.id)})),
    '-', {label: tr('Backlog|sprint'), icon: 'x', on: cur === null, fn: () => spr_assign(ids, null)}], null, null, tr('Sprint'));
}
async function spr_cfgPut(lid, cfg) {
  const j = await api('PUT', `/api/lists/${lid}/sprint-settings`, cfg);
  await load(); render();
  return j;
}
async function spr_cfgSet(lid, ch, lab) {
  const l = spr_list(lid), before = {...(l?.sprint_cfg || {on: false, weeks: 2, dow: 0, carry: true})};
  let j; try { j = await spr_cfgPut(lid, ch); } catch { return null; }
  const after = j.settings;
  offerUndo(lab || tr('Saved'), histAdd({label: tr('Changed setting: {0}', tr('Sprints')), sett: true,
    undo: () => spr_cfgPut(lid, {on: before.on, weeks: before.weeks, dow: before.dow, carry: before.carry}), redo: () => spr_cfgPut(lid, after)}));
  return j;
}
const spr_dowName = i => new Date(2024, 0, 1 + i).toLocaleDateString(LOCALE(), {weekday: 'long'});  // 1 Jan 2024 = Monday
function spr_cfgModal(lid) {
  const l = spr_list(lid); if (!l) return;
  const c = {on: false, weeks: 2, dow: 0, carry: true, ...(l.sprint_cfg || {})};
  const md = /** @type {any} */ (modal(`<h3>${tr('Sprints')}</h3>
    <div class="row"><span></span><label class="chkl"><input type="checkbox" id="sp-on" ${c.on ? 'checked' : ''}> ${tr('Plan in sprints')}</label></div>
    <div class="row"><label for="sp-w">${tr('Length')}</label><select id="sp-w">${[[1, N_('1 week')], [2, N_('2 weeks')], [0, N_('Free (set the dates of each sprint)')]].map(([v, n]) => `<option value="${v}" ${c.weeks === v ? 'selected' : ''}>${esc(tr(String(n)))}</option>`).join('')}</select></div>
    <div class="row"><label for="sp-d">${tr('Starts on')}</label><select id="sp-d">${[0, 1, 2, 3, 4, 5, 6].map(i => `<option value="${i}" ${c.dow === i ? 'selected' : ''}>${esc(spr_dowName(i))}</option>`).join('')}</select></div>
    <div class="row"><span></span><label class="chkl"><input type="checkbox" id="sp-c" ${c.carry ? 'checked' : ''}> ${tr('When a sprint ends, open tasks move to the next sprint (otherwise to the backlog)')}</label></div>
    <div class="shint lhint">${tr('A sprint that reaches its last day is closed with a review and the next one starts.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`));
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const j = await spr_cfgSet(lid, {on: $('#sp-on', md).checked, weeks: +$('#sp-w', md).value, dow: +$('#sp-d', md).value, carry: $('#sp-c', md).checked});
    if (j) md.remove();
  });
}

// ---- editing, planning, the list of sprints, closing
async function spr_patch(sid, body) { await api('PATCH', `/api/sprints/${sid}`, body); await load(); render(); }
function spr_editModal(l, s) {
  const md = /** @type {any} */ (modal(`<h3>${esc(tr('Edit {0}', spr_name(s)))}</h3>
    <div class="row"><label for="se-n">${tr('Name')}</label><input id="se-n" maxlength="100" placeholder="${esc(tr('Sprint {0}', s.num))}" value="${esc(s.title === tr('Sprint {0}', s.num) ? '' : s.title || '')}"></div>
    <div class="row"><label for="se-g">${tr('Goal')}</label><input id="se-g" maxlength="300" placeholder="${esc(tr('One sentence: what this sprint is for'))}" value="${esc(s.goal || '')}"></div>
    ${s.state !== 'closed' ? `<div class="row"><label for="se-s">${tr('Start|date')}</label>${dateIn('se-s', s.start, {label: tr('Start|date'), clear: false})}</div>
    <div class="row"><label for="se-e">${tr('End|date')}</label>${dateIn('se-e', s.end, {label: tr('End|date'), clear: false})}</div>` : ''}
    <div class="foot">${s.state === 'planned' ? `<button class="btn danger" data-m="del">${tr('Remove')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`));
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'del') { md.remove(); spr_delete(l, s); return; }
    const before = {name: s.title === tr('Sprint {0}', s.num) ? '' : s.title || '', goal: s.goal || '', ...(s.state !== 'closed' ? {start: s.start, end: s.end} : {})};
    const after = {name: $('#se-n', md).value.trim(), goal: $('#se-g', md).value.trim(), ...(s.state !== 'closed' ? {start: $('#se-s', md).value, end: $('#se-e', md).value} : {})};
    try { await spr_patch(s.id, after); } catch { return; }
    md.remove();
    offerUndo(tr('Saved'), histAdd({label: tr('{0} changed', spr_name(s)), undo: () => spr_patch(s.id, before), redo: () => spr_patch(s.id, after)}));
  });
  if (!isMobile()) setTimeout(() => $('#se-g', md)?.focus(), 30);
}
async function spr_plan(l) {
  let j; try { j = await api('POST', `/api/lists/${l.id}/sprints`, {}); } catch { return; }
  await load(); render();
  let sid = j.id;
  const del = async () => { await api('DELETE', `/api/sprints/${sid}`); await load(); render(); };
  const re = async () => { const k = await api('POST', `/api/lists/${l.id}/sprints`, {start: j.start, end: j.end}); sid = k.id; await load(); render(); };
  offerUndo(tr('{0} planned: {1}', j.title, spr_range(j)), histAdd({label: tr('{0} planned: {1}', j.title, spr_range(j)), undo: del, redo: re}));
}
async function spr_delete(l, s) {
  let j; try { j = await api('DELETE', `/api/sprints/${s.id}`); } catch { return; }
  await load(); render();
  let sid = null;
  const back = async () => { const k = await api('POST', `/api/lists/${l.id}/sprints`, {name: j.sprint.name, goal: j.sprint.goal, start: j.sprint.start, end: j.sprint.end, tasks: j.tasks}); sid = k.id; await load(); render(); };
  const again = async () => { if (sid) await api('DELETE', `/api/sprints/${sid}`); await load(); render(); };
  offerUndo(tr('{0} removed', spr_name(s)), histAdd({label: tr('{0} removed', spr_name(s)), undo: back, redo: again}));
}
async function spr_start(s) {
  try { await api('POST', `/api/sprints/${s.id}/start`); } catch { return; }
  await load(); render(); toast(tr('{0} is running', spr_name(s)));
}
function spr_closeModal(l, a) {
  const ts = spr_tasks(a.id), dn = ts.filter(t => t.status === 2).length, op = ts.filter(t => t.status === 0).length;
  const add = ts.filter(t => t.sprint_at && t.sprint_at.slice(0, 10) > a.start).length;
  const carry = l.sprint_cfg?.carry !== false;
  const md = /** @type {any} */ (modal(`<h3>${esc(tr('Close {0}', spr_name(a)))}</h3>
    <ul class="sprrv"><li><b>${dn}</b> ${esc(tr('done'))}</li><li><b>${op}</b> ${esc(tr('still open'))}</li><li><b>${add}</b> ${esc(tr('added after the start'))}</li></ul>
    ${op ? `<fieldset class="sprto"><legend>${tr('Open tasks go')}</legend>
      <label class="chkl"><input type="radio" name="sp-to" value="next" ${carry ? 'checked' : ''}> ${tr('into the next sprint')}</label>
      <label class="chkl"><input type="radio" name="sp-to" value="backlog" ${carry ? '' : 'checked'}> ${tr('back to the backlog')}</label></fieldset>` : ''}
    <div class="shint lhint">${tr('The review is kept with the sprint (Sprint options > All sprints). The next sprint starts right away.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Close sprint')}</button></div>`));
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const to = md.querySelector('input[name="sp-to"]:checked')?.value || 'next';
    let j; try { j = await api('POST', `/api/sprints/${a.id}/close`, {target: to}); } catch { return; }
    md.remove(); await load(); render();
    toast(j.next ? tr('{0} closed. {1} is running.', spr_name(a), j.next.title) : tr('{0} closed.', spr_name(a)));
  });
}
async function spr_listModal(l) {
  let j; try { j = await api('GET', `/api/lists/${l.id}/sprints`); } catch { return; }
  const ed = canEditList(l.id), pts = !!j.points_on;
  const rv = s => s.review ? `<span class="muted">${esc(tr('{0} done · {1} moved · {2} added', s.review.count_done ?? s.review.done.length, s.review.moved.length, s.review.added.length))}${pts ? ' · ' + esc(tr('{0} of {1} points', s.review.points_done, s.review.points_total)) : ''}</span>` : `<span class="muted">${esc(tr('{0} of {1} done', s.progress.done, s.progress.total))}</span>`;
  const st = {planned: N_('planned'), active: N_('running'), closed: N_('closed')};
  const md = /** @type {any} */ (modal(`<h3>${tr('All sprints')}</h3>${j.sprints.length ? `<ul class="sprall">${j.sprints.map(s => `<li class="${s.state}"><div><b>${esc(s.title)}</b> <span class="muted">${esc(spr_range(s))} · ${esc(tr(st[s.state]))}</span></div>${s.goal ? `<div class="sprgoal">${esc(s.goal)}</div>` : ''}<div>${rv(s)}</div>${ed ? `<div class="spract">${s.state === 'planned' && !j.active_id ? `<button class="btn sm" data-m="start" data-id="${s.id}">${tr('Start')}</button>` : ''}<button class="btn sm" data-m="edit" data-id="${s.id}">${tr('Edit')}</button></div>` : ''}</li>`).join('')}</ul>` : `<p class="muted">${tr('No sprints yet.')}</p>`}
    <div class="foot">${ed && spr_on(l) ? `<button class="btn" data-m="plan">${ic('plus', 's')} ${tr('Plan a sprint')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`));
  md.addEventListener('click', (/** @type {any} */ e) => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    const s = j.sprints.find(x => x.id === +b.dataset.id);
    md.remove();
    if (b.dataset.m === 'start' && s) spr_start(s);
    else if (b.dataset.m === 'edit' && s) spr_editModal(l, s);
    else if (b.dataset.m === 'plan') spr_plan(l);
  });
}
function spr_moreMenu(anchor, l) {
  const a = spr_active(l), ed = canEditList(l.id);
  menu(anchor, [
    ...(a && ed ? [{label: tr('Edit sprint…'), icon: 'edit', fn: () => spr_editModal(l, a)}] : []),
    ...(ed ? [{label: tr('Plan a sprint'), icon: 'plus', fn: () => spr_plan(l)}] : []),
    {label: tr('All sprints'), icon: 'list', fn: () => spr_listModal(l)},
    {label: tr('Show the sprint in the task row'), icon: 'eye', on: spr_rowOn(l.id), fn: () => { spr_lsSet('sprRow', l.id, !spr_rowOn(l.id)); render(); }},
    ...(ed ? ['-', {label: tr('Sprint settings…'), icon: 'gear', fn: () => spr_cfgModal(l.id)}] : []),
  ], null, null, tr('Sprint'));
}

