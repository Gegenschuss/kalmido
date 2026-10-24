/* Kalmido web client: 2.51.0 C (#1352 #1353 #1355) -- what agents plan for a person: the review rows of the proposals
   "time" (entries from calendar events) and "shoot" (shoot days as event drafts + crew / equipment as options), drafts in
   the calendar (tentative events: pale, dashed, "Draft", Confirm / Discard) and the planned-job templates "Status on the
   pin board" and "Check time tracking and propose entries".
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const AP_KINDS = ['time', 'shoot'];
// planned jobs (agents.js SCHED_TPL): two more templates before "Own plan"
SCHED_TPL.splice(SCHED_TPL.findIndex(t => t.k === 'own'), 0,
  {k: 'pinstatus', t: N_('Status on the pin board'), freq: 'weekly', days: [1], time: '08:00', list: true,
    p: N_('Read the week of this plan’s project (tool get_weekly_status) and write the block “Status” on its project page (tool write_status_pad): done, what is stuck, overdue, who waits on whom. Short Markdown, the numbers first. Change nothing else.')},
  {k: 'timeprop', t: N_('Check time tracking and propose entries'), freq: 'weekly', days: [5], time: '15:00',
    p: N_('Check my time tracking of this week (tools check_time_entries and time_from_events with user_id = my id). Tell me in this chat what looks wrong, and send me ONE proposal with entries for events without time (tool propose_time_entries). Change nothing yourself.')});

// ---- the review rows (agents.js propItemsHtml / propEdit hand over for these kinds)
// 2.51.1: the app's own time picker (no native time inputs, ux1_ui); the hidden input carries data-f
const ap_hm = (id, v, label, f) => `<span class="aptime">${timeIn(id, v || '', {label, attrs: `data-f="${f}"`})}</span>`;
function ap_warn(w) {
  if (!w?.length) return '';
  return w.map(x => `<span class="ppchip apwarn">${ic('alert', 's')}${esc(x.kind === 'away' ? tr('Absent that day') : x.kind === 'double'
    ? tr('Already booked: {0}', (x.titles || []).join(', ')) : tr('Other projects that day: {0}', (x.titles || []).join(', ')))}</span>`).join('');
}
function ap_row(k, title, sub, fields, chips, cls = '') {
  const on = S.prop.sel.has(k);
  return `<div class="ppi apri ${cls} ${on ? '' : 'off'}" data-k="${k}">
    <label class="ppcl"><input type="checkbox" class="ppc" id="ppc-${ppSafe(k)}" ${on ? 'checked' : ''} aria-label="${esc(tr('Select {0}', title))}"></label>
    <div class="ppb"><div class="aph"><b>${esc(title)}</b>${sub ? `<span class="muted">${esc(sub)}</span>` : ''}</div>
      ${fields ? `<div class="ppf apf">${fields}</div>` : ''}${chips ? `<div class="ppf">${chips}</div>` : ''}</div></div>`;
}
function ap_propItemsHtml() {
  const v = S.prop.v, p = v.proposal, ed = S.prop.ed;
  if (v.kind === 'time') return p.items.map((x, i) => {
    const k = String(i), e = ed[k] || {}, id = 'apt-' + i;
    return ap_row(k, x.title || tr('Time entry'), fmtDate(x.date),
      `${ap_hm(id + 's', e.start ?? x.start, tr('Start'), 'start')}<span class="muted">–</span>${ap_hm(id + 'e', e.end ?? x.end, tr('End'), 'end')}
       <input class="apnote" data-f="note" maxlength="500" value="${esc(e.note ?? x.note ?? '')}" placeholder="${esc(tr('Note'))}" aria-label="${esc(tr('Note'))}">`,
      x.event_id ? `<span class="ppchip">${ic('cal', 's')}${esc(tr('From the calendar'))}</span>` : '');
  }).join('');
  return p.items.map((it, i) => {  // shoot: the days, each followed by its crew rows
    const k = String(i), e = ed[k] || {};
    if (it.type === 'day') {
      const d = p.days[it.i], alt = d.alt_of != null ? p.days[d.alt_of] : null;
      return ap_row(k, d.title, fmtDate(d.date) + (d.all_day ? ' · ' + tr('All day') : ''),
        `<input class="ppt" data-f="title" maxlength="200" value="${esc(e.title ?? d.title)}" aria-label="${esc(tr('Title'))}">
         ${d.all_day ? '' : `${ap_hm('aps-' + i, e.start ?? d.start, tr('Start'), 'start')}<span class="muted">–</span>${ap_hm('ape-' + i, e.end ?? d.end, tr('End'), 'end')}`}
         <input class="apnote" data-f="location" maxlength="200" value="${esc(e.location ?? d.location ?? '')}" placeholder="${esc(tr('Location'))}" aria-label="${esc(tr('Location'))}">`,
        (alt ? `<span class="ppchip">${ic('repeat', 's')}${esc(tr('Alternative to {0}', alt.title))}</span>` : '') + ap_warn(d.warnings), alt ? 'apalt' : '');
    }
    const x = p.crew[it.i], day = p.days[x.day];
    return ap_row(k, x.name, tr('Option for {0}', day ? day.title : ''), '', ap_warn(x.warnings), 'sub');
  }).join('');
}
function ap_propEdit(el) {  // true = handled (time / shoot fields)
  const f = el.dataset?.f, row = el.closest?.('.ppi'); if (!f || !row || !S.prop || !AP_KINDS.includes(S.prop.v.kind)) return false;
  const e = S.prop.ed[row.dataset.k] ||= {};
  if (f === 'start' || f === 'end') e[f] = el.value;
  else if (f === 'title') e.title = el.value.trim();
  else if (f === 'note' || f === 'location') e[f] = el.value;
  return true;
}
const ap_propHint = v => v.kind === 'time'
  ? tr('Applying adds the selected time entries as you (times and note can be changed above). Undo possible.')
  : tr('Applying creates per selected day a task in the project with a draft in your calendar, and pencils in the selected crew and equipment as options, never firm. Warnings never block. Undo possible.');

// ---- drafts in the calendar: tentative events
const ap_draftCls = e => e?.status === 'tentative' ? ' evdraft' : '';
// 2.144.2 B (#1811): the status on its way per event; a popover opened again meanwhile (the GET can overtake the PATCH) shows it
const AP_EVPEND = new Map();
async function ap_evStatus(ev, st, label) {
  const put = async x => { AP_EVPEND.set(ev.id, x); try { await api('PATCH', `/api/events/${ev.id}`, {status: x}); } finally { AP_EVPEND.delete(ev.id); } calInvalidate(); renderView(); return {}; };
  try { await put(st); } catch { return; }
  if (!$('#pop').classList.contains('hidden') && $('#pop .apdraftact')) closePop();  // 2.58.0 (#1811): a popup still showing the draft is closed, not left with Draft + Confirm
  histToast(label, histAdd({label, undo: () => put(ev.status), redo: () => put(st)}));
}
const ap_evConfirm = ev => ap_evStatus(ev, 'confirmed', tr('Draft confirmed'));
