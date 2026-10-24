// @ts-check
// 2.125.0 B (#2119): monthly timesheets on the time page. When the report shows one calendar month, a card says whether that
// month is open, closed or approved, with "Close month" / "Reopen" (the server locks the entries of a closed month: they show
// a lock instead of edit / delete). Admins of an organisation get a second card with the closed months of their members
// (hours on the organisation's lists) and approve them or send them back with a note. Every step is one Undo step. News items
// "tsheet" (event "timesheet" of the notification settings) open the time page on that month.
// 2.125.0 B (#2120): the time zone of time tracking (Settings > Modules > Time tracking) with the device's zone as a suggestion,
// and the switch "Entries over midnight" (count on each day with their share). The rules live in kalmido/personal/timesheet.py.
const TSL = {month: '', data: /** @type {any} */ (null), loading: false, key: ''};
const TSL_STATE = {open: N_('Open|month'), closed: N_('Closed|month'), approved: N_('Approved')};
const tsl_when = v => v ? fmtDate(ds(new Date(v))) : '';
// the month the report shows (YYYY-MM) when its range is exactly one calendar month, else ''
function tsl_monthOf() {
  const [f, t] = timeRange();
  return f.slice(8) === '01' && t === monthEnd(f) ? f.slice(0, 7) : '';
}
async function tsl_load() {
  if (TSL.loading) return;
  TSL.loading = true;
  const m = tsl_monthOf(), key = m + '|' + S.v;
  try { TSL.data = await rawFetch('GET', '/api/time/sheets' + (m ? '?month=' + m : '')); } catch { TSL.data = null; }
  finally { TSL.loading = false; TSL.key = key; TSL.month = m; }
  if (S.route.mod === 'time') renderView();
}
function tsl_reload() { TSL.key = ''; S.tv.key = ''; if (S.route.mod === 'time') renderView(); }
function tsl_card() {
  if (!timeOn()) return '';
  const m = tsl_monthOf();
  if (TSL.key !== m + '|' + S.v && !TSL.loading) setTimeout(tsl_load, 0);
  const j = TSL.data; if (!j) return '';
  let h = '';
  if (m && j.month === m) {
    const sh = j.sheet, st = sh.state;
    const info = st === 'approved' ? tr('Approved by {0} on {1}', sh.decided_by_name || '?', tsl_when(sh.decided_at))
      : st === 'closed' ? tr('Closed on {0}', tsl_when(sh.closed_at)) + (sh.org_id ? ' · ' + tr('Waiting for approval by an admin of {0}', sh.org_name) : '')
      : sh.decided_by && sh.note ? tr('Sent back by {0}: {1}', sh.decided_by_name || '?', sh.note)
      : sh.decided_by ? tr('Sent back by {0}', sh.decided_by_name || '?') : tr('Entries of this month can still be changed');
    const btn = j.can.close ? `<button type="button" class="btn" data-tsl="close" title="${esc(sh.org_id ? tr('Locks the entries and sends the timesheet to the admins') : tr('Locks the entries of this month'))}">${ic('lock', 's')} ${tr('Close month')}</button>`
      : j.can.reopen ? `<button type="button" class="btn" data-tsl="reopen">${tr('Reopen')}</button>`
      : st === 'approved' ? `<span class="muted">${esc(tr('Only an admin of the organisation can reopen it'))}</span>` : '';
    h += `<section class="stcard tslcard tsl-${esc(st)}" aria-label="${esc(tr('Timesheet'))}"><div class="tslrow">${ic(st === 'open' ? 'clock' : 'lock', 's')}<div class="tslinfo"><b>${esc(tr('Timesheet {0}', tsl_monthName(m)))} · ${esc(tr(TSL_STATE[st] || st))}</b><small class="muted">${esc(info)}</small></div>${btn}</div></section>`;
  }
  const rv = j.review || [];
  if (rv.length) {
    h += `<section class="stcard tslcard tslrev" aria-label="${esc(tr('Timesheets of your team'))}"><div class="sthead"><h3>${tr('Timesheets of your team')}</h3></div>
      ${rv.map(r => `<div class="tslrow" data-uid="${r.user_id}" data-month="${esc(r.month)}">${av(r.user_id, r.name)}<div class="tslinfo"><b>${esc(r.name)} · ${esc(tsl_monthName(r.month))}</b><small class="muted">${esc(tr(TSL_STATE[r.state] || r.state))} · ${esc(tr('{0} h', hmm(r.seconds)))}${r.state === 'open' && r.note ? ' · ' + esc(r.note) : ''}</small></div>
        ${r.state === 'closed' ? `<button type="button" class="btn pri sm" data-tsl="approve">${ic('check', 's')} ${tr('Approve')}</button><button type="button" class="btn sm" data-tsl="return">${tr('Send back')}</button>`
          : r.state === 'approved' ? `<button type="button" class="btn sm" data-tsl="return">${tr('Reopen')}</button>` : ''}</div>`).join('')}</section>`;
  }
  return h;
}
// a line on the printed timesheet: the state of the month it covers
function tsl_printNote(j) {
  const d = TSL.data, m = tsl_monthOf();
  if (!d || !m || d.month !== m || j.from !== m + '-01' || j.scope === 'all') return '';
  const sh = d.sheet;
  return sh.state === 'approved' ? `<div class="tssub">${esc(tr('Approved by {0} on {1}', sh.decided_by_name || '?', tsl_when(sh.decided_at)))}</div>`
    : sh.state === 'closed' ? `<div class="tssub">${esc(tr('Closed on {0}', tsl_when(sh.closed_at)))}</div>` : '';
}
async function tsl_own(month, action) {
  try { await api('POST', '/api/time/sheets', {month, action}); } catch { return false; }
  tsl_reload();
  return true;
}
async function tsl_decide(b) {
  try { await api('POST', '/api/time/sheets/decide', b); } catch { return false; }
  tsl_reload();
  return true;
}
const tsl_step = fn => async () => (await fn()) ? {skipped: []} : {skipped: [tr('Timesheet')], none: true};
async function tsl_act(a, row) {
  const m = TSL.month;
  if (a === 'close' || a === 'reopen') {
    if (!m || !(await tsl_own(m, a))) return;
    const back = a === 'close' ? 'reopen' : 'close', lab = a === 'close' ? tr('Month closed: {0}', tsl_monthName(m)) : tr('Month reopened: {0}', tsl_monthName(m));
    offerUndo(lab, histAdd({label: lab, undo: tsl_step(() => tsl_own(m, back)), redo: tsl_step(() => tsl_own(m, a))}));
    return;
  }
  if (!row) return;
  const user_id = +row.dataset.uid, month = row.dataset.month, who = (TSL.data?.review || []).find(r => r.user_id === user_id && r.month === month);
  if (a === 'approve') {
    if (!(await tsl_decide({user_id, month, action: 'approve'}))) return;
    const lab = tr('Timesheet approved: {0}', `${who?.name || ''} ${tsl_monthName(month)}`);
    offerUndo(lab, histAdd({label: lab, undo: tsl_step(() => tsl_decide({user_id, month, action: 'unapprove'})), redo: tsl_step(() => tsl_decide({user_id, month, action: 'approve'}))}));
  } else if (a === 'return') {
    const note = await askPrompt(tr('Send the timesheet back'), '', {body: tr('{0} can change the entries again. A note tells what to fix.', who?.name || ''), ok: tr('Send back'), input: {placeholder: tr('Note (optional)')}});
    if (note === null || note === undefined) return;
    const b = {user_id, month, action: 'return', note: String(note).trim()};
    if (!(await tsl_decide(b))) return;
    const lab = tr('Timesheet sent back: {0}', `${who?.name || ''} ${tsl_monthName(month)}`);
    offerUndo(lab, histAdd({label: lab, undo: tsl_step(() => tsl_decide({user_id, month, action: 'restore'})), redo: tsl_step(() => tsl_decide(b))}));
  }
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target)?.closest?.('[data-tsl]'); if (!b) return;
  if (b.dataset.tsl === 'tzdev') { tsl_tzDevice(b); return; }
  tsl_act(b.dataset.tsl, b.closest('[data-uid]'));
});
// ---- 2.125.0 B (#2120): settings rows (Settings > Modules > Time tracking)
const tsl_deviceTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch { return ''; } };
function tsl_setRows(s, hint) {
  const cur = s.tz || '', dev = tsl_deviceTz();
  let zones = []; try { zones = /** @type {any} */ (Intl).supportedValuesOf('timeZone'); } catch { zones = []; }
  if (cur && !zones.includes(cur)) zones = [cur, ...zones];
  return `<div class="row"><label for="s-ttz">${tr('Time zone')}</label><select id="s-ttz"><option value="">${tr('Time zone of the server')}</option>${zones.map(z => `<option value="${esc(z)}" ${z === cur ? 'selected' : ''}>${esc(z.replace(/_/g, ' '))}</option>`).join('')}</select>${dev && dev !== cur ? `<button type="button" class="linkbtn" data-tsl="tzdev" data-tz="${esc(dev)}">${esc(tr('Use this device: {0}', dev.replace(/_/g, ' ')))}</button>` : ''}</div>
      ${hint(tr('Decides on which day an entry counts and the periods of the report, the CSV and the timesheet.'))}
      <div class="row"><label>${tr('Entries over midnight')}</label><label class="chkl"><input type="checkbox" id="s-tsplit" ${s.time_split_midnight !== '0' ? 'checked' : ''}> ${tr('count on each day with their share')}</label></div>`;
}
function tsl_tzDevice(b) {
  const sel = /** @type {any} */ (document.getElementById('s-ttz')); if (!sel) return;
  const z = b.dataset.tz;
  if (![...sel.options].some(o => o.value === z)) sel.add(new Option(z.replace(/_/g, ' '), z));
  sel.value = z;
  sel.dispatchEvent(new Event('change', {bubbles: true}));
  b.remove();
}
// 2.144.2 B (#2375): another zone chosen: "Use this device" is there at once (it was only drawn when the page opened)
document.addEventListener('change', e => {
  const sel = /** @type {any} */ (e.target); if (sel?.id !== 's-ttz') return;
  const dev = tsl_deviceTz(), b = sel.parentElement?.querySelector('[data-tsl="tzdev"]');
  if (!dev || sel.value === dev) { b?.remove(); return; }
  if (!b) sel.insertAdjacentHTML('afterend', `<button type="button" class="linkbtn" data-tsl="tzdev" data-tz="${esc(dev)}">${esc(tr('Use this device: {0}', dev.replace(/_/g, ' ')))}</button>`);
});
