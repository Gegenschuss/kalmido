// @ts-check
/* Kalmido web client: the dialog of a time entry (entryModal: add / edit tracked time, its target and billing) (2.1156.0, #4280: moved here from time.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

const fmtClock = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;  // HH:MM for fields and comparisons; shown times use fmtTimeAt (2.368.0 B, #2982)
// "1:30" = 90 min, "45m" = 45 min, "1.5" / "1,5h" = 90 min (a bare number means hours)
function parseDur(v) {
  v = String(v || '').trim().toLowerCase(); if (!v) return null;
  let m;
  if ((m = v.match(/^(\d+):(\d{1,2})$/))) return +m[1] * 60 + +m[2];
  if ((m = v.match(/^(\d+)\s*m(in)?$/))) return +m[1];
  const f = parseFloat(v.replace(',', '.').replace(/\s*h$/, ''));
  return isNaN(f) || f <= 0 ? null : Math.round(f * 60);
}
function targetOptions(tid, lid) {
  const lists = S.lists.filter(l => (mtTime(l.id) || l.id === lid) && (!l.archived || l.id === lid || (tid && taskById(tid)?.list_id === l.id)));
  const cur = tid && taskById(tid);
  return lists.map(l => {
    const ts = sortTasks(openTasks().filter(t => t.list_id === l.id && !t.parent_id));
    if (cur && cur.list_id === l.id && !ts.includes(cur)) ts.unshift(cur);
    const sub = x => [x, ...children(x.id).filter(k => k.status === 0 || k.id === tid).flatMap(sub)];
    return `<optgroup label="${esc(lname(l))}"><option value="l:${l.id}" ${!tid && lid === l.id ? 'selected' : ''}>${esc(tr('(whole project, no task)'))}</option>${ts.flatMap(sub).map(t => `<option value="t:${t.id}" ${t.id === tid ? 'selected' : ''}>${' '.repeat(depthOf(t))}${esc(t.title)}</option>`).join('')}</optgroup>`;
  }).join('');
}
// 2.576.0 (#4764): an entry as its dialog sees it (objsave.js saveDialog compares these keys): the target, start / end to the
// minute, note, billable; teSrv turns the changed ones into the PATCH body with _prev = what the dialog showed (the server's
// field check, timetrack.py oxb_time_prev)
const teMin = v => { if (!v) return ''; const d = new Date(v); if (isNaN(+d)) return ''; d.setSeconds(0, 0); return d.toISOString(); };
const teView = x => ({target: x.task_id ? 't:' + x.task_id : 'l:' + x.list_id, start: teMin(x.start), ...(x.running ? {} : {end: teMin(x.end)}), note: x.note || '', billable: x.billable !== false, updated_at: x.updated_at});
function teSrv(b, now, x) {
  const o = {};
  if ('target' in b) { const [k, v] = String(b.target).split(':'); Object.assign(o, k === 't' ? {task_id: +v} : {list_id: +v}); }
  if ('start' in b || 'end' in b) { o.start = now.start; if ('end' in now) o.end = now.end; }
  if ('note' in b) o.note = b.note;
  if ('billable' in b) o.billable = b.billable;
  o._prev = Object.fromEntries(Object.keys(o).map(k => [k, k === 'billable' ? x.billable !== false : x[k] ?? null]));
  return o;
}
// what a conflict's own input (the dialog's keys) makes of the server's entry: the dialog is drawn from it
function teOver(x, mine) {
  const o = {...x};
  if (mine.target) { const [k, v] = String(mine.target).split(':'); Object.assign(o, k === 't' ? {task_id: +v, list_id: taskById(+v)?.list_id ?? x.list_id} : {task_id: null, list_id: +v}); }
  for (const k of ['start', 'end', 'note', 'billable']) if (k in mine && mine[k] !== '') o[k] = mine[k];
  return o;
}
// new entry (e = null; preset {task_id} | {list_id}) or edit my entry (a running timer: start time, note, task)
// 2.576.0 (#4764): cf = a conflict of objsave.js saveDialog: the dialog shows the saved entry (cf.raw) with the own input over
// it, the other's fields marked; an open dialog shows the bar "Changed ..." with "Take over"
function entryModal(e, preset = {}, cf) {
  const raw = cf ? cf.raw : e; if (cf) e = teOver(cf.raw, cf.mine || {});
  const run = !!(e && e.running), s = e ? new Date(e.start) : null, en = e && e.end ? new Date(e.end) : null;
  const tid = e ? e.task_id : preset.task_id || null, lid = e ? e.list_id : preset.list_id || (tid ? taskById(tid)?.list_id : null) || (mtTime(routeList()?.id) ? routeList().id : null) || S.lists.find(l => mtTime(l.id) && !l.archived)?.id;  // 2.41.0 (#1471)
  /** @type {any} */
  const md = modal(`<h3>${run ? tr('Running timer') : e ? tr('Edit time entry') : tr('Add time')}</h3>
    <div class="row"><label for="te-target">${tr('Task')}</label><select id="te-target">${targetOptions(tid, lid)}</select></div>
    <div class="row"><label>${tr('Date')}</label>${dateIn('te-date', s ? ds(s) : preset.date || ds(new Date()), {max: today(), label: tr('Date'), clear: false})}</div>
    <div class="row"><label>${run ? tr('Started at') : tr('From – to')}</label>${timeIn('te-from', s ? fmtClock(s) : '', {label: run ? tr('Started at') : tr('From'), empty: '–'})}${run ? '' : `<span class="muted">–</span>${timeIn('te-to', en ? fmtClock(en) : '', {label: tr('To'), empty: '–'})}`}</div>
    ${run ? '' : `<div class="row"><label for="te-dur">${tr('or duration')}</label><input id="te-dur" placeholder="${tr('e.g. 1:30, 45m or 1.5')}" inputmode="decimal" autocomplete="off"></div>`}
    <div class="row" id="te-noterow"><label for="te-note">${tr('Note')}</label><input id="te-note" value="${esc(e?.note || '')}" maxlength="500" autocomplete="off"></div>
    <div class="row"><label for="te-bill">${tr('Billable')}</label><label class="swc"><input type="checkbox" id="te-bill" ${e?.billable === false ? '' : 'checked'} ${e?.billed ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Billable'))}</span></label></div>
    ${e?.billed ? `<div class="shint tebill-hint">${esc(e.billed.id ? tr('On invoice {0}: duration, date and task are locked, the note can still change.', e.billed.number || tr('Draft')) : tr('Already billed: duration, date and task are locked, the note can still change.'))}</div>` : ''}
    ${run ? '' : `<div class="shint">${tr('An end before the start means the next day. Only a duration: the entry ends now (today) or starts at 9:00.')}</div>`}
    <div class="foot">${e && !run && !e.billed ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  if (e?.billed) $$('#te-target, #te-date, #te-from, #te-to, #te-dur', md).forEach(x => { x.disabled = true; });  // 2.144.6 A (#2053)
  const noteSync = () => {  // 2.538.0 (#4372): no note field for a project with the lock (follows the chosen task / project)
    const [k, v] = $('#te-target', md).value.split(':');
    $('#te-noterow', md).hidden = te_locked(k === 't' ? {task_id: +v} : {list_id: +v});
  };
  noteSync();
  $('#te-target', md).addEventListener('change', noteSync);
  const times = () => {
    const date = $('#te-date', md).value, from = $('#te-from', md).value, to = $('#te-to', md)?.value, dur = parseDur($('#te-dur', md)?.value);
    if (!date) return null;
    let a = from ? new Date(`${date}T${from}`) : null, b = null;
    if (run) return a ? {start: a} : null;
    if (a && to && !dur) { b = new Date(`${date}T${to}`); if (b <= a) b = new Date(b.getTime() + 864e5); }
    else if (dur) {
      if (a) b = new Date(a.getTime() + dur * 6e4);
      else if (date === today()) { b = new Date(); b.setSeconds(0, 0); a = new Date(b.getTime() - dur * 6e4); }
      else { a = new Date(`${date}T09:00`); b = new Date(a.getTime() + dur * 6e4); }
    }
    return a && b ? {start: a, end: b} : null;
  };
  md.addEventListener('click', async ev => {
    const b = ev.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'del') { md.remove(); teDelete(e.id); return; }
    if (b.dataset.m !== 'save') return;
    /** @type {any} */
    const tm = times();
    if (!tm) { toast(run ? tr('Please enter the start time') : tr('Please enter start and end, or a duration')); return; }
    if (tm.end && tm.end - tm.start < 6e4) { toast(tr('The end is before the start')); return; }
    if (tm.start > new Date()) { toast(tr('Entries cannot lie in the future')); return; }
    const [k, v] = $('#te-target', md).value.split(':'), body = {note: $('#te-noterow', md).hidden ? '' : $('#te-note', md).value.trim()};
    const target = k === 't' ? {task_id: +v} : {list_id: +v};
    if (!e || (k === 't' ? +v !== e.task_id : e.task_id || +v !== e.list_id)) Object.assign(body, target);
    const bill = $('#te-bill', md).checked;  // 2.144.6 A (#2053)
    if (!e || bill !== (e.billable !== false)) body.billable = bill;
    const iso = d => d.toISOString();
    if (!e || fmtClock(tm.start) !== fmtClock(s) || ds(tm.start) !== ds(s) || (!run && (!en || fmtClock(tm.end) !== fmtClock(en) || ds(tm.end) !== ds(en)))) {
      body.start = iso(tm.start); if (!run) body.end = iso(tm.end);
    }
    // 2.576.0 (#4764): a change goes through objsave.js saveDialog (only the changed fields, _prev = what the dialog showed): changed
    // elsewhere meanwhile = 409, the dialog comes again with the saved entry, the own input over it, the other's fields marked
    if (e && typeof saveDialog !== 'function') await loadModule('objsave').catch(() => { /* offline without the copy: saved as before */ });
    if (e && typeof saveDialog === 'function') {  // lazy-ok-begin: objsave.js is loaded just above
      const now = form(), d = objDiff(base, now), url = `/api/time/entries/${e.id || 0}`;
      let j;
      try { j = await saveDialog(url, teView(raw), now, {key: 'entry', base, view: teView, send: x => api('PATCH', url, teSrv(x, now, raw))}); } catch { return; }  // api() said it
      if (j?.conflict) { md.remove(); entryModal(j.conflict.raw, {}, j.conflict); return; }
      md.remove();
      if (!Object.keys(d).length) return;  // nothing changed: no request
      toast(j.queued ? tr('Will be sent as soon as the server is reachable') : tr('Saved'));
      await timeChanged(j);
      if ('billable' in d) teBillStep(e, j, bill);
      return;
    }  // lazy-ok-end
    if (e) body._prev = Object.fromEntries(Object.keys(body).map(k => [k, k === 'billable' ? e.billable !== false : e[k] ?? null]));
    let j;
    try { j = e ? await api('PATCH', `/api/time/entries/${e.id || 0}`, body) : await api('POST', '/api/time/entries', {...target, ...body, client_id: newCid()}); }  // 2.143.0 C (#2153): sent again from the outbox = one entry
    catch { return; }  // api() said it (a 409 without objsave.js: the dialog stays with its input)
    md.remove();
    toast(j.queued ? tr('Will be sent as soon as the server is reachable') : e ? tr('Saved') : tr('Time added: {0}', hmm(j.seconds)));
    await timeChanged(j);
    if (e && 'billable' in body) teBillStep(e, j, bill);
  });
  // 2.576.0 (#4764): what the dialog would save now (teView's keys); the form as it opened (fields typed before a conflict always
  // count as changed); the version watch and the marks of a conflict once objsave.js is in
  function form() {
    const tm = times(), o = {target: $('#te-target', md).value, start: tm ? teMin(tm.start) : ''};
    if (!run) o.end = tm?.end ? teMin(tm.end) : '';
    return {...o, note: $('#te-noterow', md).hidden ? '' : $('#te-note', md).value.trim(), billable: $('#te-bill', md).checked};
  }
  const base = e ? (typeof objBase === 'function' ? objBase(form(), cf?.mine) : form()) : null;  // lazy-ok: cf only comes from objsave.js
  if (e && e.id) loadModule('objsave').then(() => {  // lazy-ok-begin: loaded here
    if (!md.isConnected) return;
    const open = teView(raw), again = (x, theirs, mine) => { md.remove(); entryModal(x, {}, {raw: x, cur: teView(x), theirs, mine, both: []}); };
    dlgStale(md, `/api/time/entries/${e.id}`, () => raw.updated_at, x => { const c = teView(x); again(x, Object.keys(form()).filter(k => !objSame(open[k], c[k])), objDiff(base, form())); });
    if (cf?.theirs.length) objMerge(md, cf, () => {}, {field: k => ({target: $('#te-target', md), start: $('#te-from', md), end: $('#te-to', md), note: $('#te-noterow', md), billable: $('#te-bill', md)})[k]?.closest('.row') || null,
      take: keys => again(cf.raw, [], Object.fromEntries(Object.entries(cf.mine || {}).filter(([k]) => !keys.includes(k))))});
  }, () => { /* offline without the copy: saved as before */ });  // lazy-ok-end
  md.addEventListener('keydown', ev => { if (ev.key === 'Enter' && ev.target.tagName === 'INPUT') $('[data-m="save"]', md).click(); });
  if (!isTouch()) setTimeout(() => $(e ? '#te-note' : run ? '#te-from' : '#te-dur', md)?.focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
// 2.144.6 A (#2053): the billable switch of a saved change is one undo step
function teBillStep(e, j, bill) {
  const set = async v => { const r = await api('PATCH', `/api/time/entries/${e.id}`, {billable: v}); await timeChanged(r); return {q: r?._q || null}; };
  histAdd({label: bill ? tr('Time marked billable') : tr('Time marked not billable'), res: j, lids: e.list_id ? [e.list_id] : [], ...(j?.undo_group ? {srv: true} : {}),  // 2.809.0 (#5476): the server lists the step
    undo: () => set(!bill), redo: () => set(bill)});
}
