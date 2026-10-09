/* Kalmido web client: Events (module "events"): own calendars next to the tasks, the event editor and popover, the
   agenda, creating events in the week grid, calendars (share, import, export) and the phone setup.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.21.0 (#659): events live in the server's own calendars (S.evcals from /api/state). The calendar views fetch them per
// visible range together with the subscriptions (/api/calendars/events, items with own: true), so month / week / day /
// timeline / Today show them like the external ones; a click opens evPop (details, reply, edit, delete), "+ Event", the
// week grid (drag over free time) and the quick sheet's "Event" button open the editor (evEditor).
const evOn = () => feat('events');
const evCal = id => (S.evcals || []).find(c => c.id === id);
const evWrite = c => !!c && (c.role === 'owner' || c.role === 'edit');
const evWritable = () => (S.evcals || []).filter(c => evWrite(c) && !c.hidden && wsObjIn(c));  // 2.30.0 (#1036): of the shown workspace
const EV_PS = [['accepted', N_('Accept'), 'check'], ['tentative', N_('Maybe'), 'help'], ['declined', N_('Decline'), 'x']];
const EV_PS_WORD = {accepted: N_('Accepted'), tentative: N_('Maybe'), declined: N_('Declined'), 'needs-action': N_('No answer yet')};
// all-day reminders: minutes before the day's midnight (-540 = 9:00 on the day)
const EV_REM_TIMED = ['0', '5', '10', '15', '30', '60', '120', '1440', '2880', '10080'];
const EV_REM_DAY = [['-540', N_('On the day at 9:00')], ['900', N_('1 day before at 9:00')], ['2340', N_('2 days before at 9:00')], ['9540', N_('1 week before at 9:00')]];
// timed: how long before the start (the row says "Reminders"; the same short form for every chip)
const EV_REM_TXT = {'0': N_('At the start'), '5': N_('5 min'), '10': N_('10 min'), '15': N_('15 min'), '30': N_('30 min'), '60': N_('1 h'), '120': N_('2 h'),
  '1440': N_('1 day'), '2880': N_('2 days'), '10080': N_('1 week')};
const evRemLabel = (m, allDay) => { if (allDay) { const o = EV_REM_DAY.find(x => x[0] === String(m)); if (o) return tr(o[1]); } return EV_REM_TXT[String(m)] ? tr(EV_REM_TXT[String(m)]) : remLabel(String(m)); };
const evCalColor = e => cssColor((S.cal.evcals || {})[e.cal]?.color) || cssColor(evCal(e.cal)?.color) || 'var(--accent)';
const evCalName = e => e.cal == null ? tr('Invitation') : (S.cal.evcals || {})[e.cal]?.name || evCal(e.cal)?.name || tr('Calendar');

// ---- the popover of an own event (occurrence e from S.cal.items)
function evWhen(e) {
  return cevWhen(e.d0 ? e : cevPrep({...e}));
}
async function evPop(anchor, e) {
  const p = openPop(anchor, `<div class="cevpop evpop" style="--cc:${evCalColor(e)}"><div class="cevh"><i class="cevdot"></i><b>${esc(cevTitle(e))}</b></div><div class="muted">${tr('Loading…')}</div></div>`);
  let ev;
  try { ev = await api('GET', `/api/events/${e.eid}`); } catch { closePop(); return; }
  if ($('#pop').classList.contains('hidden')) return;
  const role = ev.role, w = role === 'owner' || role === 'edit', me = (ev.attendees || []).find(a => a.user_id === S.me?.id);
  const att = ev.attendees || [];
  const t = ev.task_id ? taskById(ev.task_id) : null;
  const desc = (e.description || '').slice(0, 2000);
  p.innerHTML = `<div class="cevpop evpop" style="--cc:${evCalColor(e)}">
    <div class="cevh"><i class="cevdot"></i><b>${esc(cevTitle(e))}</b>${e.status === 'cancelled' ? `<span class="evst">${tr('Cancelled')}</span>` : e.status === 'tentative' ? `<span class="evst">${tr('Tentative')}</span>` : ''}</div>
    <div class="cevm">${ic('clock', 's')}<span>${esc(evWhen(e))}</span></div>
    ${e.recurring ? `<div class="cevm">${ic('repeat', 's')}<span>${esc(repeatLabel(ev.rrule) || tr('Repeats'))}${e.changed ? ' · ' + esc(tr('this date changed')) : ''}</span></div>` : ''}
    ${e.location ? `<div class="cevm">${ic('mappin', 's')}<span>${esc(e.location)}</span></div>` : ''}
    <div class="cevm">${ic('cal', 's')}<span>${esc(evCalName(e))}${w ? '' : ' · ' + esc(tr('read-only'))}</span></div>
    ${att.length ? `<div class="cevm evatt">${ic('users', 's')}<span>${att.slice(0, 8).map(a => `<span class="evap ps-${esc(a.partstat)}" title="${esc(tr(EV_PS_WORD[a.partstat] || ''))}">${esc(a.name || a.email)}</span>`).join(', ')}${att.length > 8 ? ' …' : ''}</span></div>` : ''}
    ${ev.reminders?.length ? `<div class="cevm">${ic('bell', 's')}<span>${esc(ev.reminders.map(m => evRemLabel(m, ev.all_day)).join(', '))}</span></div>` : ''}
    ${desc ? `<div class="cevdesc">${cevLinkify(desc)}</div>` : ''}
    ${t ? `<button class="linkbtn evtask" data-evp="task">${ic('done', 's')} ${esc(tr('Preparation: {0}', t.title))}</button>` : ''}
    ${me ? `<div class="evrsvp" role="group" aria-label="${esc(tr('Your answer'))}">${EV_PS.map(([k, n, i]) => `<button class="btn sm ${me.partstat === k ? 'on' : ''}" data-evps="${k}" aria-pressed="${me.partstat === k}">${ic(i, 's')} ${tr(n)}</button>`).join('')}</div>` : ''}
    <div class="cevact">${w ? `<button class="btn sm pri" data-evp="edit">${ic('edit', 's')} ${tr('Edit')}</button>${!ev.task_id ? `<button class="btn sm" data-evp="prep">${ic('plus', 's')} ${tr('Preparation task')}</button>` : ''}<button class="btn sm danger" data-evp="del">${ic('trash', 's')} ${tr('Delete')}</button>` : `<button class="btn sm" data-evp="totask">${ic('plus', 's')} ${tr('Create task from event')}</button>`}</div></div>`;
  p.onclick = async ev2 => {
    const ps = ev2.target.closest('[data-evps]');
    if (ps) { try { await api('POST', `/api/events/${ev.id}/rsvp`, {partstat: ps.dataset.evps}); } catch { return; } closePop(); toast(tr('Answer sent: {0}', tr(EV_PS_WORD[ps.dataset.evps]))); calInvalidate(); renderView(); return; }
    const b = ev2.target.closest('[data-evp]'); if (!b) return;
    const k = b.dataset.evp;
    closePop();
    if (k === 'edit') evEditor({ev, occ: e.recurring ? e.occ : null});
    else if (k === 'del') evDelete(ev, e.recurring ? e.occ : null);
    else if (k === 'task') openDetail(ev.task_id);
    else if (k === 'prep') evPrepTask(ev);
    else if (k === 'totask') cevToTask(cevPrep({...e}));
  };
}
async function evDelete(ev, occ) {
  let mode = 'all';
  if (occ) {
    const r = await evAskScope(tr('Delete a repeating event'), tr('Delete'));
    if (!r) return;
    mode = r;
  } else if (!await askConfirm(tr('Delete the event “{0}”?', ev.title), '', {ok: tr('Delete'), danger: true})) return;
  try { await api('DELETE', `/api/events/${ev.id}` + (mode === 'one' ? `?occ=${encodeURIComponent(occ)}` : '')); } catch { return; }
  calInvalidate(); await load().catch(() => {}); renderView();
  if (mode === 'all') toast(tr('Event deleted'), async () => { try { await api('POST', `/api/events/${ev.id}/restore`); } catch { return; } calInvalidate(); await load().catch(() => {}); renderView(); });
  else toast(tr('This date was removed'));
}
function evAskScope(title, ok) {  // a repeating event: only this date or every date
  return new Promise(res => {
    const md = modal(`<h3>${esc(title)}</h3><p class="muted">${tr('This event repeats.')}</p>
      <div class="foot evscope"><button class="btn" data-sc="">${tr('Cancel')}</button><span class="spacer"></span><button class="btn" data-sc="one">${tr('Only this date')}</button><button class="btn pri" data-sc="all">${esc(ok === tr('Delete') ? tr('All dates') : tr('All dates'))}</button></div>`);
    let done = false;
    const fin = v => { if (done) return; done = true; res(v); md.remove(); };
    md.addEventListener('click', e => { const b = e.target.closest('[data-sc]'); if (b) fin(b.dataset.sc || null); });
    onRemove(md, () => fin(null));
  });
}
async function evPrepTask(ev) {
  try {
    const j = await api('POST', `/api/events/${ev.id}/prep-task`, {days_before: 1});
    await load(); calInvalidate(); render(); toast(tr('Preparation task created'), () => openDetail(j.task.id), 5000, tr('Open'));
  } catch { /* api() showed it */ }
}

// ---- the editor (new event: o.start / o.end / o.all_day / o.title / o.task_id; existing: o.ev, o.occ = the date it was opened from)
let EVU = null;  // people for attendees (GET /api/users, once per session)
async function evPeople() {
  if (EVU) return EVU;
  try { EVU = (await api('GET', '/api/users')).users.filter(u => !u.agent && !u.disabled && u.id !== S.me?.id); } catch { EVU = []; }
  return EVU;
}
const evTz = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch { return ''; } };
function evZones(cur) {
  let z = [];
  try { z = Intl.supportedValuesOf('timeZone'); } catch { z = []; }
  return [...new Set([cur, evTz(), ...z].filter(Boolean))];
}
const EV_REP = [['', N_('Does not repeat')], ['FREQ=DAILY', N_('Daily')], ['FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR', N_('Weekdays')], ['W', N_('Weekly')],
  ['W2', N_('Every 2 weeks')], ['M', N_('Monthly')], ['FREQ=YEARLY', N_('Yearly')]];
function evRepRule(k, start) {
  const d = pd(start.slice(0, 10));
  if (k === 'W') return `FREQ=WEEKLY;BYDAY=${RR_WD[d.getDay()]}`;
  if (k === 'W2') return `FREQ=WEEKLY;INTERVAL=2;BYDAY=${RR_WD[d.getDay()]}`;
  if (k === 'M') return `FREQ=MONTHLY;BYMONTHDAY=${d.getDate()}`;
  return k;
}
function evRepKey(rule, start) {
  const b = rrBase(rule || '');
  if (!b) return '';
  for (const [k] of EV_REP) if (k && evRepRule(k, start) === b) return k;
  return 'custom';
}
async function evEditor(o = {}) {
  const ev = o.ev || null, cals = evWritable().concat(ev && !evWritable().some(c => c.id === ev.cal_id) && evCal(ev.cal_id) ? [evCal(ev.cal_id)] : []);
  if (!cals.length) { try { const c = await api('POST', '/api/evcals', {name: tr('Calendar'), org_id: wsDefaultOrg()}); await load(); cals.push(c); } catch { return; } }
  const t0 = today();
  const st = ev ? {...ev} : {title: o.title || '', all_day: !!o.all_day, start: o.start || `${S.calSel || t0}T09:00`, end: o.end || '', location: '',
    description: o.description || '', rrule: '', reminders: o.all_day ? [-540] : [15], attendees: [], cal_id: o.cal_id || +LS.get('evCal', 0) || cals[0].id,
    task_id: o.task_id || null, status: 'confirmed', busy: true, url: null, tz: evTz()};
  if (!ev && o.attendees) st.attendees = o.attendees;
  if (!cals.some(c => c.id === st.cal_id)) st.cal_id = cals[0].id;
  if (!st.end) st.end = st.all_day ? addDays(st.start.slice(0, 10), 1) : evAddMin(st.start, 60);
  let scope = o.occ ? 'all' : null;
  if (o.occ && ev) {  // opened from one date of a repeating event: that date's times are the ones shown for "Only this date"
    const ov = (ev.overrides || []).find(x => x.rid === o.occ);
    st.occStart = ov?.start || o.occ;
    st.occEnd = ov?.end || (ev.all_day ? addDays(o.occ, Math.max(1, diffDays(ev.start.slice(0, 10), ev.end.slice(0, 10)))) : evAddMin(o.occ, evMin(ev.start, ev.end)));
  }
  const people = await evPeople();
  const ppl = new Map(people.map(u => [u.id, u.display_name]));
  const atts = (st.attendees || []).map(a => ({...a}));
  const endDay = s => st.all_day ? addDays(s, -1) : s.slice(0, 10);  // all day: the shown end is the last day (stored exclusive)
  const repK = evRepKey(st.rrule, st.start);
  const md = modal(`<div class="lhdr"><h3>${ev ? tr('Edit event') : tr('New event')}</h3><span class="spacer"></span><button class="iconbtn" data-evm="close" aria-label="${tr('Close')}">${ic('x')}</button></div>
    ${o.occ ? `<div class="row"><span class="rlab">${tr('Change')}</span><div class="seg" role="radiogroup" aria-label="${esc(tr('Change'))}"><button type="button" role="radio" data-evsc="one" aria-checked="false">${tr('Only this date')}</button><button type="button" role="radio" data-evsc="all" class="on" aria-checked="true">${tr('All dates')}</button></div></div>` : ''}
    <div class="row"><label for="ev-title">${tr('Title')}</label><input id="ev-title" maxlength="500" value="${esc(st.title)}" autocomplete="off" enterkeyhint="done"></div>
    <div class="row"><label for="ev-cal">${tr('Calendar')}</label><select id="ev-cal" data-sheet-ico="cal">${cals.map(c => `<option value="${c.id}" ${c.id === st.cal_id ? 'selected' : ''}>${esc(c.name)}${c.role !== 'owner' ? ' · ' + esc(c.owner_name || '') : ''}</option>`).join('')}</select></div>
    <div class="row"><label for="ev-allday">${tr('All day')}</label><label class="swc"><input type="checkbox" id="ev-allday" ${st.all_day ? 'checked' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('All day'))}</span></label></div>
    <div class="row evdt"><span class="rlab">${tr('Starts')}</span>${dateIn('ev-sd', st.start.slice(0, 10), {label: tr('Start date'), clear: false})}<span class="evtm" ${st.all_day ? 'hidden' : ''}>${timeIn('ev-stm', st.all_day ? '09:00' : st.start.slice(11, 16), {label: tr('Start time'), clear: false})}</span></div>
    <div class="row evdt"><span class="rlab">${tr('Ends')}</span>${dateIn('ev-ed', endDay(st.end), {label: tr('End date'), clear: false})}<span class="evtm" ${st.all_day ? 'hidden' : ''}>${timeIn('ev-etm', st.all_day ? '10:00' : st.end.slice(11, 16), {label: tr('End time'), clear: false})}</span></div>
    <div class="row evrep"><label for="ev-rep">${tr('Repeat')}</label><select id="ev-rep" data-sheet-ico="repeat">${EV_REP.map(([k, n]) => `<option value="${k}" ${k === repK ? 'selected' : ''}>${tr(n)}</option>`).join('')}${repK === 'custom' ? `<option value="custom" selected>${esc(repeatLabelBase(rrBase(st.rrule)))}</option>` : ''}</select>
      <select id="ev-repend" aria-label="${esc(tr('Ends'))}" ${repK ? '' : 'hidden'}><option value="">${tr('forever')}</option><option value="until" ${rrEnd(st.rrule).type === 'until' ? 'selected' : ''}>${tr('until a date')}</option><option value="count" ${rrEnd(st.rrule).type === 'count' ? 'selected' : ''}>${tr('a number of times')}</option></select>
      <span id="ev-reu" ${rrEnd(st.rrule).type === 'until' ? '' : 'hidden'}>${dateIn('ev-until', rrEnd(st.rrule).type === 'until' ? rrEnd(st.rrule).val : '', {label: tr('until a date'), clear: false})}</span>
      <input id="ev-count" class="numin" type="number" inputmode="numeric" min="1" max="999" value="${rrEnd(st.rrule).type === 'count' ? esc(rrEnd(st.rrule).val) : '10'}" aria-label="${esc(tr('a number of times'))}" ${rrEnd(st.rrule).type === 'count' ? '' : 'hidden'}></div>
    <div class="row"><label for="ev-loc">${tr('Location')}</label><input id="ev-loc" maxlength="500" value="${esc(st.location || '')}" autocomplete="off"></div>
    <div class="row evrems"><span class="rlab" id="ev-rem-l">${tr('Reminders')}</span><div class="evchips" id="ev-rems" role="group" aria-labelledby="ev-rem-l"></div></div>
    <div class="row evatts"><span class="rlab" id="ev-att-l">${tr('People')}</span><div class="evatt-w"><div class="evchips" id="ev-atts" role="group" aria-labelledby="ev-att-l"></div>
      <div class="evattadd"><input id="ev-attin" list="ev-attl" autocomplete="off" placeholder="${esc(tr('Name or e-mail'))}" aria-label="${esc(tr('Add a person'))}" enterkeyhint="done"><datalist id="ev-attl"></datalist><button type="button" class="btn sm" data-evm="attadd">${ic('plus', 's')} ${tr('Add')}</button></div></div></div>
    <div class="row ppcol"><label for="ev-desc">${tr('Notes')}</label><textarea id="ev-desc" rows="3" maxlength="20000">${esc(st.description || '')}</textarea></div>
    <details class="evmore"><summary>${tr('More')}</summary>
      <div class="row"><label for="ev-tz">${tr('Time zone')}</label><select id="ev-tz">${evZones(st.tz).map(z => `<option value="${esc(z)}" ${z === (st.tz || evTz()) ? 'selected' : ''}>${esc(z.replace(/_/g, ' '))}</option>`).join('')}</select></div>
      <div class="row"><label for="ev-status">${tr('Status')}</label><select id="ev-status"><option value="confirmed">${tr('Confirmed')}</option><option value="tentative" ${st.status === 'tentative' ? 'selected' : ''}>${tr('Tentative')}</option><option value="cancelled" ${st.status === 'cancelled' ? 'selected' : ''}>${tr('Cancelled')}</option></select></div>
      <div class="row"><label for="ev-busy">${tr('Show as busy')}</label><label class="swc"><input type="checkbox" id="ev-busy" ${st.busy !== false ? 'checked' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Show as busy'))}</span></label></div>
      <div class="row"><label for="ev-url">${tr('Link')}</label><input id="ev-url" type="url" inputmode="url" value="${esc(st.url || '')}" placeholder="https://…" autocomplete="off"></div>
      ${st.task_id && taskById(st.task_id) ? `<div class="row"><span class="rlab">${tr('Preparation')}</span><button type="button" class="linkbtn" data-evm="task">${ic('done', 's')} ${esc(taskById(st.task_id).title)}</button><button type="button" class="iconbtn" data-evm="untask" aria-label="${esc(tr('Remove the link to the task'))}" title="${esc(tr('Remove the link to the task'))}">${ic('x', 's')}</button></div>` : ''}
    </details>
    <div class="foot">${ev && evWrite(evCal(ev.cal_id)) ? `<button class="btn danger" data-evm="del">${ic('trash', 's')} ${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-evm="close">${tr('Cancel')}</button><button class="btn pri" data-evm="save">${tr('Save')}</button></div>`);
  md.classList.add('evmodal');
  const val = id => $('#' + id, md)?.value || '';
  const drawRems = () => {
    const ad = $('#ev-allday', md).checked, opts = ad ? EV_REM_DAY.map(x => x[0]) : EV_REM_TIMED;
    const on = new Set((st.reminders || []).map(String));
    const all = [...new Set([...opts, ...on])];
    $('#ev-rems', md).innerHTML = all.map(m => `<button type="button" class="chip evchip ${on.has(m) ? 'on' : ''}" data-evrem="${m}" aria-pressed="${on.has(m)}">${esc(evRemLabel(m, ad))}</button>`).join('');
  };
  const drawAtts = () => {
    $('#ev-atts', md).innerHTML = atts.length ? atts.map((a, i) => `<span class="evatp ps-${esc(a.partstat || 'needs-action')}">${a.user_id ? av(a.user_id, a.name || ppl.get(a.user_id) || '') : ic(a.contact_id ? 'user' : 'at', 's')}<span>${esc(a.name || ppl.get(a.user_id) || a.email)}</span><span class="muted evps">${esc(tr(EV_PS_WORD[a.partstat || 'needs-action']))}</span><button type="button" class="iconbtn" data-evatrm="${i}" aria-label="${esc(tr('Remove {0}', a.name || a.email || ''))}">${ic('x', 's')}</button></span>`).join('')
      : `<span class="muted">${tr('Only you')}</span>`;
  };
  drawRems(); drawAtts();
  const attList = async q => {  // suggestions: people of this server + contacts (name / e-mail)
    const opts = people.filter(u => !atts.some(a => a.user_id === u.id) && (!q || u.display_name.toLowerCase().includes(q.toLowerCase()))).slice(0, 8).map(u => ({v: u.display_name, k: 'u' + u.id}));
    if (feat('contacts') && q.length >= 2) {
      try { (await api('GET', `/api/contacts?q=${encodeURIComponent(q)}&limit=8`)).items.forEach(c => opts.push({v: c.fn + (c.email ? ` <${c.email}>` : ''), k: 'c' + c.id, c})); } catch { /* offline */ }
    }
    md._sugg = opts;
    $('#ev-attl', md).innerHTML = opts.map(x => `<option value="${esc(x.v)}"></option>`).join('');
  };
  const attAdd = () => {
    const inp = $('#ev-attin', md), v = inp.value.trim(); if (!v) return;
    const s = (md._sugg || []).find(x => x.v === v) || people.filter(u => u.display_name.toLowerCase() === v.toLowerCase()).map(u => ({k: 'u' + u.id, v: u.display_name}))[0];
    if (s && s.k[0] === 'u') atts.push({user_id: +s.k.slice(1), name: s.v, partstat: 'needs-action'});
    else if (s && s.k[0] === 'c') atts.push({contact_id: +s.k.slice(1), name: s.c.fn, email: s.c.email, partstat: 'needs-action'});
    else if (/^[^@\s<>"]+@[^@\s<>"]+$/.test(v)) atts.push({email: v, partstat: 'needs-action'});
    else { toast(tr('Pick a person from the list or type an e-mail address')); return; }
    inp.value = ''; drawAtts(); inp.focus();
  };
  md.addEventListener('input', e => { if (e.target.id === 'ev-attin') attList(e.target.value.trim()); });
  md.addEventListener('keydown', e => { if (e.target.id === 'ev-attin' && e.key === 'Enter') { e.preventDefault(); attAdd(); } });
  md.addEventListener('change', e => {
    const id = e.target.id;
    if (id === 'ev-allday') { const ad = e.target.checked; $$('.evtm', md).forEach(x => { x.hidden = ad; }); st.reminders = ad ? [-540] : [15]; drawRems(); }
    if (id === 'ev-rep') { const k = e.target.value; $('#ev-repend', md).hidden = !k; if (!k) { $('#ev-reu', md).hidden = true; $('#ev-count', md).hidden = true; } }
    if (id === 'ev-repend') { $('#ev-reu', md).hidden = e.target.value !== 'until'; $('#ev-count', md).hidden = e.target.value !== 'count'; }
    if (id === 'ev-sd' && val('ev-ed') < val('ev-sd')) dpSet($('#ev-ed', md), val('ev-sd'));
    if (id === 'ev-stm' && val('ev-ed') === val('ev-sd') && val('ev-etm') <= val('ev-stm')) dpSet($('#ev-etm', md), evAddMin(`2000-01-01T${val('ev-stm')}`, 60).slice(11, 16));
  });
  md.addEventListener('click', async e => {
    const r = e.target.closest('[data-evrem]');
    if (r) { const m = +r.dataset.evrem, s = new Set((st.reminders || []).map(Number)); s.has(m) ? s.delete(m) : s.add(m); st.reminders = [...s].slice(0, 10); drawRems(); $(`[data-evrem="${m}"]`, md)?.focus(); return; }
    const ar = e.target.closest('[data-evatrm]');
    if (ar) { atts.splice(+ar.dataset.evatrm, 1); drawAtts(); $('#ev-attin', md).focus(); return; }
    const sc = e.target.closest('[data-evsc]');
    if (sc) {
      scope = sc.dataset.evsc;
      $$('[data-evsc]', md).forEach(x => { x.classList.toggle('on', x === sc); x.setAttribute('aria-checked', String(x === sc)); });
      const s = scope === 'one' ? st.occStart : st.start, en = scope === 'one' ? st.occEnd : st.end;
      dpSet($('#ev-sd', md), s.slice(0, 10)); dpSet($('#ev-ed', md), endDay(en));
      if (!st.all_day) { dpSet($('#ev-stm', md), s.slice(11, 16)); dpSet($('#ev-etm', md), en.slice(11, 16)); }
      $('.evrep', md).hidden = $('.evatts', md).hidden = $('.evrems', md).hidden = scope === 'one';
      return;
    }
    const b = e.target.closest('[data-evm]'); if (!b) return;
    const k = b.dataset.evm;
    if (k === 'close') md.remove();
    else if (k === 'attadd') attAdd();
    else if (k === 'task') { md.remove(); openDetail(st.task_id); }
    else if (k === 'untask') { st.task_id = null; b.closest('.row').remove(); }
    else if (k === 'del') { md.remove(); evDelete(ev, o.occ); }
    else if (k === 'save') {
      const ad = $('#ev-allday', md).checked, sd = val('ev-sd'), ed = val('ev-ed') || sd;
      const body = {title: val('ev-title').trim() || tr('(no title)'), all_day: ad, location: val('ev-loc').trim(), description: val('ev-desc')};
      if (ad) { body.start = sd; body.end = addDays(ed < sd ? sd : ed, 1); }
      else {
        body.start = `${sd}T${val('ev-stm') || '09:00'}`; body.end = `${ed}T${val('ev-etm') || '10:00'}`;
        if (body.end < body.start) { toast(tr('The end must be after the start')); return; }
      }
      if (scope === 'one') {
        try { await api('PATCH', `/api/events/${ev.id}?occ=${encodeURIComponent(o.occ)}`, body); } catch { return; }
      } else {
        const rk = val('ev-rep');
        let rule = rk === 'custom' ? rrBase(st.rrule) : rk ? evRepRule(rk, body.start) : '';
        if (rule) rule = rrSetEnd(rule, {type: val('ev-repend'), val: val('ev-repend') === 'until' ? val('ev-until') : val('ev-count')});
        Object.assign(body, {rrule: rule, reminders: st.reminders || [], cal_id: +val('ev-cal'), tz: val('ev-tz'), status: val('ev-status'), busy: $('#ev-busy', md).checked,
          url: val('ev-url').trim() || null, task_id: st.task_id || null,
          attendees: atts.map(a => a.user_id ? {user_id: a.user_id, partstat: a.partstat || 'needs-action'} : a.contact_id ? {contact_id: a.contact_id, partstat: a.partstat || 'needs-action'} : {email: a.email, name: a.name || '', partstat: a.partstat || 'needs-action'})});
        if (body.url && !validUrl(body.url)) { toast(tr('The link must start with http:// or https://')); return; }
        try {
          if (ev) await api('PATCH', `/api/events/${ev.id}`, {...body, expect: ev.updated_at});
          else await api('POST', '/api/events', body);
        } catch { return; }
        LS.set('evCal', body.cal_id);
      }
      md.remove();
      calInvalidate(); await load().catch(() => {}); render();
      toast(ev ? tr('Event saved') : tr('Event created'));
    }
  });
  setTimeout(() => { if (!ev) $('#ev-title', md)?.focus(); }, 40);
  return md;
}
const evMin = (a, b) => Math.max(0, Math.round((new Date(b) - new Date(a)) / 60000));
function evAddMin(s, m) { const d = new Date(s.length === 10 ? s + 'T00:00' : s); d.setMinutes(d.getMinutes() + m); return `${ds(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }

// ---- creating: the "+ Event" button of the calendar bar, the quick sheet ("Event"), dragging over free time in the week grid
function evNewAt(day, hm, endHm) {
  if (!evOn()) return;
  if (!hm) { evEditor({all_day: true, start: day, end: addDays(day, 1)}); return; }
  evEditor({start: `${day}T${hm}`, end: endHm ? `${day}T${endHm}` : ''});
}
const EVD = {on: false};
document.addEventListener('pointerdown', e => {
  if (!evOn() || e.button !== 0 || e.pointerType === 'touch') return;
  const col = e.target.closest?.('#view .week .wcol');
  if (!col || e.target.closest('.wev, .wcev')) return;
  const top = col.getBoundingClientRect().top, H = weekH();
  const at = y => Math.max(0, Math.min(24 * 60, Math.round((y - top) / H * 4) * 15));
  Object.assign(EVD, {on: true, col, a: at(e.clientY), b: at(e.clientY), y0: e.clientY, moved: false, at, ghost: null});
});
document.addEventListener('pointermove', e => {
  if (!EVD.on) return;
  if (!EVD.moved && Math.abs(e.clientY - EVD.y0) < 8) return;
  EVD.moved = true;
  EVD.b = EVD.at(e.clientY);
  if (!EVD.ghost) { EVD.ghost = document.createElement('div'); EVD.ghost.className = 'evghost'; EVD.col.appendChild(EVD.ghost); }
  const s = Math.min(EVD.a, EVD.b), en = Math.max(EVD.a, EVD.b, s + 15), H = weekH();
  EVD.ghost.style.top = s / 60 * H + 'px'; EVD.ghost.style.height = (en - s) / 60 * H + 'px';
  EVD.ghost.textContent = `${pad(Math.floor(s / 60))}:${pad(s % 60)}–${pad(Math.floor(en / 60) % 24)}:${pad(en % 60)}`;
});
document.addEventListener('pointerup', e => {
  if (!EVD.on) return;
  EVD.on = false;
  const g = EVD.ghost; EVD.ghost = null;
  if (!EVD.moved) return;
  e.preventDefault();
  EVD.swallow = Date.now();  // the click that follows the drag does not open the quick sheet
  const s = Math.min(EVD.a, EVD.b), en = Math.min(Math.max(EVD.a, EVD.b, s + 15), 24 * 60 - 1);
  const day = EVD.col.dataset.day;
  setTimeout(() => g?.remove(), 300);
  evNewAt(day, `${pad(Math.floor(s / 60))}:${pad(s % 60)}`, `${pad(Math.floor(en / 60))}:${pad(en % 60)}`);
});
document.addEventListener('click', e => {
  if (EVD.swallow && Date.now() - EVD.swallow < 400 && e.target.closest?.('#view .week .wcol')) { e.stopImmediatePropagation(); e.preventDefault(); EVD.swallow = 0; }
}, true);
// the quick sheet opened from a free slot of the calendar: "Event" turns what was typed into an event at that time
function evSheetBtn(preset) {
  const q = $('.qadd.sheet'); if (!q || !evOn() || !preset?.due || q.querySelector('.qevbtn')) return;
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'btn sm qevbtn'; b.innerHTML = `${ic('cal', 's')}<span>${esc(tr('Event'))}</span>`;
  b.title = tr('Create an event at this time instead'); b.setAttribute('aria-label', tr('Create an event at this time instead'));
  b.addEventListener('click', () => {
    const title = ($('#qsheet')?.value || '').trim(), p = {...preset};
    closePop();
    evEditor({title, all_day: !p.due_time, start: p.due_time ? `${p.due}T${p.due_time}` : p.due, end: p.due_time ? '' : addDays(p.due, 1)});
  });
  q.querySelector('.box')?.appendChild(b);
}

// ---- the agenda: the coming days, events and dated tasks together
function viewAgenda() {
  const from = S.calSel || today(), days = 14, to = addDays(from, days - 1);
  if (calEvOn()) ensureCalEv(from, to);
  const byDay = calByDay(from, to);
  let h = '';
  for (let i = 0; i < days; i++) {
    const d = addDays(from, i), evs = calEvOn() ? cevOn(d).sort(cevSort) : [], ts = (byDay.get(d) || []).filter(t => !t.ghost);
    if (!evs.length && !ts.length) continue;
    h += `<section class="agday ${d === today() ? 'today' : ''}" aria-label="${esc(dayLabel(d, true) + ' ' + fmtDate(d))}"><h3>${esc(dayLabel(d, true))} <span class="muted">${esc(fmtDate(d))}</span></h3>
      ${evs.length ? `<div class="cevlist">${evs.map(e => cevRow(e, d)).join('')}</div>` : ''}${ts.map(t => taskRow(t, {showList: true, drag: false})).join('')}</section>`;
  }
  return calBar(tr('Agenda') + ` <span class="muted agrange">${esc(fmtDayAbs(from))} – ${esc(fmtDayAbs(to))}</span>`) + `<div class="agenda agview">${h || `<div class="empty">${ic('cal')}${tr('Nothing in the next two weeks.')}</div>`}</div>`;
}

// ---- calendars: list, new, rename / colour, hide, share, import (ICS), export, delete; the phone setup
async function evCalsModal() {
  // 2.36.1 (#1127 #956): ONE window for everything the calendar shows: "Tasks" (all dated tasks, fold-out: per list), my own
  // calendars, then the subscriptions; each calendar row has three switches: in my calendar (evcals.hidden /
  // cal_subs.visible, the same field as in the settings), on Today (today_cals_hidden) and when planning (plan_cals_off).
  // On a phone the dialog is the usual sheet from below.
  let users = [];
  if (collab()) users = await evPeople();
  const md = modal(`<div class="lhdr"><h3>${ic('cal', 's')} ${tr('Calendars')}</h3><span class="spacer"></span><button class="iconbtn" data-evc="close" aria-label="${tr('Close')}">${ic('x')}</button></div><div id="evc-body"></div>
    <div class="foot">${feat('events') ? `<button class="btn" data-evc="phone">${ic('phone', 's')} ${tr('On the phone…')}</button>` : ''}<span class="spacer"></span>${S.calendars?.enabled ? `<button class="btn" data-evc="subs">${ic('gear', 's')} ${tr('Subscriptions…')}</button>` : ''}${feat('events') ? `<button class="btn pri" data-evc="new">${ic('plus', 's')} ${tr('New calendar')}</button>` : ''}</div>`);
  md.classList.add('evcmodal');
  const st = {lists: false};
  const sw = (key, kind, on, dis, label) => `<label class="swc ${dis ? 'off' : ''}" title="${esc(label)}"><input type="checkbox" data-cvx="${kind}" data-key="${key}" ${on ? 'checked' : ''} ${dis ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(label)}</span></label>`;
  const three = c => {  // Today + planning (off while the calendar is hidden: hidden = gone from Today and the planner too)
    const off = !c.on;
    return sw(c.key, 'today', c.on && !cvxList('today_cals_hidden').includes(c.key), off, tr('Show {0} on Today', c.name))
      + sw(c.key, 'plan', c.on && !cvxList('plan_cals_off').includes(c.key), off, tr('Consider {0} when planning', c.name));
  };
  const head = `<div class="cvxhead"><span class="cvxhn"></span><span title="${esc(tr('In my calendar'))}">${tr('Calendar|col')}</span><span title="${esc(tr('On Today'))}">${tr('Today')}</span><span title="${esc(tr('When planning'))}">${tr('Plan|col')}</span></div>`;
  const draw = () => {
    const cs = S.evcals || [], hidL = cvxList('cal_lists_hidden'), tasksOn = S.settings.cal_tasks !== '0';
    const lists = [...S.lists.filter(l => !l.archived && !l.is_inbox), ...S.lists.filter(l => !l.archived && l.is_inbox)];
    // tasks: one switch for all dated tasks, fold-out: one per list (the lists are only listed, never changed here)
    const tl = `<div class="cvxgrp">${tr('Tasks')}</div><div class="cvxrow" style="--cc:var(--accent)">
      ${sw('tasks', 'tasks', tasksOn, false, tr('Show tasks in my calendar'))}<i class="cevdot"></i><span class="evcn">${tr('Tasks with a date')}${hidL.length && tasksOn ? `<span class="muted"> · ${esc(trn('{0} list hidden', '{0} lists hidden', hidL.length))}</span>` : ''}</span>
      <button class="iconbtn cvxfold" data-evc="lists" aria-expanded="${st.lists}" aria-label="${esc(tr('Per list'))}" title="${esc(tr('Per list'))}">${ic('right', 's')}</button></div>
      ${st.lists ? lists.map(l => `<div class="cvxrow sub" style="--cc:${cssColor(l.color) || 'var(--muted)'}">${sw(String(l.id), 'list', !hidL.includes(l.id), !tasksOn, tr('Show {0} in my calendar', lname(l)))}<i class="cevdot"></i><span class="evcn">${esc(lname(l))}</span></div>`).join('') : ''}`;
    const own = !feat('events') ? '' : `<div class="cvxgrp">${tr('My calendars')}</div>${cs.length ? head + `<ul class="evclist">${cs.map(c => `<li class="evcrow" style="--cc:${cssColor(c.color) || 'var(--accent)'}">
      <i class="cevdot"></i><span class="evcn">${esc(c.name)}${wsOn() && c.role === 'owner' ? `<span class="muted wslbl"> · ${esc(wsLabel(c.org_id))}</span>` : ''}${c.role !== 'owner' ? `<span class="muted"> · ${esc(c.owner_name || '')} · ${esc(c.role === 'edit' ? tr('can edit') : tr('can view'))}</span>` : c.members?.length ? `<span class="muted"> · ${esc(trn('shared with {0} person', 'shared with {0} people', c.members.length))}</span>` : ''}</span>
      <label class="swc" title="${esc(tr('Show in my calendar'))}"><input type="checkbox" data-evcshow="${c.id}" ${c.hidden ? '' : 'checked'}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Show {0} in my calendar', c.name))}</span></label>
      ${three({key: `e:${c.id}`, name: c.name, on: !c.hidden})}
      <button class="iconbtn" data-evcmenu="${c.id}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', c.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></li>`).join('')}</ul>`
      : `<p class="muted">${tr('No calendar yet. A new event creates one.')}</p>`}`;
    const subs = cvxVisibleCals(true).filter(c => !c.own);
    const sb = !S.calendars?.enabled ? '' : `<div class="cvxgrp">${tr('Subscriptions')}</div>${subs.length ? (cs.length && feat('events') ? '' : head) + subs.map(c => `<div class="cvxrow" style="--cc:${cssColor(c.color)}">
      <i class="cevdot"></i><span class="evcn">${esc(c.name)}</span>${sw(c.key, 'show', c.on, false, tr('Show {0} in my calendar', c.name))}${three(c)}
      <button class="iconbtn" data-cvxmenu="${c.key}" data-name="${esc(c.name)}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', c.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>`).join('')
      : `<p class="muted">${tr('No subscriptions yet. Add one under Settings > Integrations > Calendars.')}</p>`}`;
    $('#evc-body', md).innerHTML = tl + own + sb;
  };
  await cvxCals(true).catch(() => {});
  draw();
  const redraw = () => { cvxRedraw(); draw(); };
  const refresh = async () => { await load().catch(() => {}); await cvxCals(true).catch(() => {}); redraw(); };
  md.addEventListener('change', async e => {
    const s = e.target.closest('[data-evcshow]');
    if (s) {
      try { await api('PATCH', `/api/evcals/${s.dataset.evcshow}`, {hidden: !s.checked}); } catch { s.checked = !s.checked; return; }
      const c = evCal(+s.dataset.evcshow); if (c) c.hidden = !s.checked;
      redraw(); return;
    }
    const x = e.target.closest('[data-cvx]'); if (!x) return;
    const kind = x.dataset.cvx, key = x.dataset.key, on = x.checked;
    if (kind === 'tasks') { await cvxSave('cal_tasks', on ? '1' : '0'); redraw(); return; }
    if (kind === 'list') { await cvxOff('cal_lists_hidden', +key, !on); redraw(); return; }
    if (kind === 'today') { await cvxOff('today_cals_hidden', key, !on); renderView(); return; }
    if (kind === 'plan') { await cvxOff('plan_cals_off', key, !on); return; }
    if (kind === 'show') { if (!await cvxShow(key, on)) { x.checked = !on; return; } draw(); }
  });
  md.addEventListener('click', async e => {
    const sm = e.target.closest('[data-cvxmenu]');
    if (sm) {
      const key = sm.dataset.cvxmenu;
      menu(sm, [{label: tr('Only this calendar'), icon: 'eye', fn: async () => { await cvxOnly(key); draw(); }},
        {label: tr('Show all calendars'), icon: 'all', fn: async () => { await cvxAll(); draw(); }}, '-',
        {label: tr('Subscriptions…'), icon: 'gear', sub: tr('Settings > Integrations > Calendars'), fn: () => { md.remove(); settingsModal('calendars'); }}]);
      return;
    }
    const m = e.target.closest('[data-evcmenu]');
    if (m) {
      const c = evCal(+m.dataset.evcmenu); if (!c) return;
      const own = c.role === 'owner';
      menu(m, [own && {label: tr('Rename…'), icon: 'edit', fn: async () => { const n = await askPrompt(tr('Rename the calendar'), c.name, {input: {max: 100}}); if (n && n.trim()) { try { await api('PATCH', `/api/evcals/${c.id}`, {name: n.trim()}); } catch { return; } refresh(); } }},
        own && {label: tr('Colour…'), icon: 'palette', fn: () => calColorPop(m, LCOLORS.filter(Boolean), c.color, async col => { try { await api('PATCH', `/api/evcals/${c.id}`, {color: col}); } catch { return; } refresh(); })},
        own && wsOn() && {label: tr('Workspace…'), icon: 'brief', fn: () => wsMoveMenu(m, c.org_id, async org => { try { await api('PATCH', `/api/evcals/${c.id}`, {org_id: org}); } catch { return; } refresh(); })},
        own && collab() && {label: tr('Share…'), icon: 'users', fn: () => evShareModal(c, users, refresh)},
        evWrite(c) && {label: tr('Import a calendar file (ICS)…'), icon: 'upload', fn: () => evImport(c, refresh)},
        {label: tr('Export (ICS)'), icon: 'download', fn: () => { location.href = `/api/evcals/${c.id}/export.ics`; }},
        {label: tr('Only this calendar'), icon: 'eye', fn: async () => { await cvxOnly(`e:${c.id}`); draw(); }},  // 2.36.1 (#1127)
        {label: tr('Show all calendars'), icon: 'all', fn: async () => { await cvxAll(); draw(); }},
        !own && {label: tr('Leave this calendar'), icon: 'logout', fn: async () => { if (!await askConfirm(tr('Leave the calendar “{0}”?', c.name), '', {ok: tr('Leave'), danger: true})) return; try { await api('DELETE', `/api/evcals/${c.id}/members/${S.me.id}`); } catch { return; } refresh(); }},
        own && {label: tr('Delete…'), icon: 'trash', cls: 'danger', fn: async () => { if (!await askConfirm(tr('Delete the calendar “{0}” with all its events?', c.name), tr('This cannot be undone.'), {ok: tr('Delete'), danger: true})) return; try { await api('DELETE', `/api/evcals/${c.id}`); } catch { return; } refresh(); }}]);
      return;
    }
    const b = e.target.closest('[data-evc]'); if (!b) return;
    if (b.dataset.evc === 'close') md.remove();
    if (b.dataset.evc === 'lists') { st.lists = !st.lists; draw(); }
    if (b.dataset.evc === 'phone') { md.remove(); davGuide(); }
    if (b.dataset.evc === 'subs') { md.remove(); settingsModal('calendars'); }
    if (b.dataset.evc === 'new') {
      const n = await wsAskNew(tr('New calendar'));  // 2.30.0 (#1036): with its workspace
      if (!n) return;
      try { await api('POST', '/api/evcals', n); } catch { return; }
      refresh();
    }
  });
}
function evShareModal(c, users, done) {
  const md = modal(`<h3>${tr('Share {0}', esc(c.name))}</h3><div id="evs-list"></div>
    <div class="row"><label for="evs-user">${tr('Person')}</label><select id="evs-user" data-sheet-av>${users.filter(u => !(c.members || []).some(m => m.user_id === u.id)).map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join('')}</select>
      <select id="evs-role" aria-label="${esc(tr('Role'))}"><option value="view">${tr('can view')}</option><option value="edit">${tr('can edit')}</option></select><button class="btn sm pri" data-evs="add">${tr('Share')}</button></div>
    <div class="shint">${tr('People with “can view” see the events, with “can edit” they also change them. In their phone the calendar appears next to their own.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-evs="close">${tr('Done')}</button></div>`);
  const names = new Map(users.map(u => [u.id, u.display_name]));
  const draw = () => { $('#evs-list', md).innerHTML = (c.members || []).length ? `<ul class="evclist">${c.members.map(m => `<li class="evcrow">${av(m.user_id, names.get(m.user_id) || '')}<span class="evcn">${esc(names.get(m.user_id) || '?')} <span class="muted">· ${esc(m.role === 'edit' ? tr('can edit') : tr('can view'))}</span></span><button class="iconbtn" data-evsrm="${m.user_id}" aria-label="${esc(tr('Stop sharing with {0}', names.get(m.user_id) || ''))}">${ic('x', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('Not shared yet.')}</p>`; };
  draw();
  md.addEventListener('click', async e => {
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
function evImport(c, done) {
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = '.ics,text/calendar';
  inp.onchange = async () => {
    const f = inp.files[0]; if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await fetch(`/api/evcals/${c.id}/import`, {method: 'POST', body: fd, headers: {'X-Requested-With': 'kalmido'}, credentials: 'same-origin'});
      const j = await r.json();
      if (!r.ok) { toast(j.error || tr('Import failed')); return; }
      toast(tr('Imported: {0} new, {1} updated', j.created, j.updated) + (j.errors ? ' · ' + trn('{0} not readable', '{0} not readable', j.errors) : ''), null, 6000);
      done();
    } catch { toast(tr('Import failed')); }
  };
  inp.click();
}
// "Calendar & contacts on the phone": the addresses and the steps for iPhone, Android (DAVx5) and Thunderbird
function davGuide() {
  const c = S.caldav || {}, base = c.url || location.origin + '/dav/', host = c.server || location.host, user = c.username || S.me?.username || '';
  const step = (h, items) => `<details class="dgstep"><summary>${h}</summary><ol>${items.map(x => `<li>${x}</li>`).join('')}</ol></details>`;
  const md = modal(`<div class="lhdr"><h3>${ic('phone', 's')} ${tr('Calendar and contacts on the phone')}</h3><span class="spacer"></span><button class="iconbtn" data-dg="close" aria-label="${tr('Close')}">${ic('x')}</button></div>
    <p class="muted">${tr('Your phone’s own calendar and contacts apps sync directly with Kalmido (CalDAV and CardDAV): events, task lists and address books, in both directions.')}</p>
    <div class="dgaddr"><div><span class="muted">${tr('Server')}</span><code>${esc(host)}</code><button class="iconbtn" data-copy="${esc(host)}" aria-label="${esc(tr('Copy'))}">${ic('copy', 's')}</button></div>
      <div><span class="muted">${tr('Address')}</span><code>${esc(base)}</code><button class="iconbtn" data-copy="${esc(base)}" aria-label="${esc(tr('Copy'))}">${ic('copy', 's')}</button></div>
      <div><span class="muted">${tr('User name')}</span><code>${esc(user)}</code><button class="iconbtn" data-copy="${esc(user)}" aria-label="${esc(tr('Copy'))}">${ic('copy', 's')}</button></div>
      <div><span class="muted">${tr('Password')}</span><span>${tr('an app password (Settings > Account > App passwords), never your account password')}</span><button class="btn sm" data-dg="apppw">${ic('key', 's')} ${tr('App passwords…')}</button></div></div>
    ${step(tr('iPhone and iPad'), [tr('Settings > Apps > Calendar > Calendar Accounts > Add Account > Other > Add CalDAV Account.'),
      tr('Server: {0}, user name and app password as above, then Next.', `<code>${esc(host)}</code>`),
      tr('For the contacts: Settings > Apps > Contacts > Contacts Accounts > Add Account > Other > Add CardDAV Account, with the same three entries.'),
      tr('Your calendars and task lists appear in Calendar and Reminders, your address books in Contacts.')])}
    ${step(tr('Android (DAVx⁵)'), [tr('Install DAVx⁵ (Play Store or F-Droid) and open it, then + > Login with URL and user name.'),
      tr('Base URL: {0}, user name and app password as above.', `<code>${esc(base)}</code>`),
      tr('Pick the calendars and address books to sync. They appear in the phone’s calendar and contacts apps (tasks with Tasks.org or jtx Board).')])}
    ${step(tr('Thunderbird'), [tr('Calendar: New Calendar > On the network, user name and the address {0}; Thunderbird finds every calendar.', `<code>${esc(base)}</code>`),
      tr('Contacts: Address book > New address book > Add CardDAV address book, the same address and user name.'),
      tr('Enter the app password when Thunderbird asks for it.')])}
    <div class="shint">${tr('Sharing a calendar or an address book with someone puts it into their phone too. Events you are invited to appear in a calendar “Invitations” (read-only).')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-dg="close">${tr('Done')}</button></div>`);
  md.classList.add('dgmodal');
  md.addEventListener('click', e => {
    const cp = e.target.closest('[data-copy]'); if (cp) { copyText(cp.dataset.copy); return; }
    const b = e.target.closest('[data-dg]'); if (!b) return;
    md.remove();
    if (b.dataset.dg === 'apppw') settingsModal('apppw');
  });
}

// ---- News, the task panel ("Events" of a task) and routes
function evNewsText(it, who, q) {
  const d = it.data || {};
  if (it.kind === 'evinvite') return tr('{0} invited you: {1}', who, q(d.title || ''));
  if (it.kind === 'evshare') return d.role === 'edit' ? tr('{0} shared the calendar {1} with you', who, q(d.name || '')) : tr('{0} shared the calendar {1} with you (view only)', who, q(d.name || ''));
  return '';
}
function evOpen(id) {  // #ev/<id> (a push, News): the calendar on that day, the event's popover
  api('GET', `/api/events/${id}`).then(ev => {
    S.calSel = ev.start.slice(0, 10); S.calMonth = S.calSel.slice(0, 7);
    if (S.route.mod !== 'cal') go('cal');
    setTimeout(() => {
      const anchor = $('#view .calbar h2') || $('#view');
      const e = {eid: ev.id, occ: ev.start, cal: ev.cal_id, title: ev.title, location: ev.location, description: ev.description, all_day: ev.all_day,
        start: ev.all_day ? ev.start : new Date(ev.start).toISOString(), end: ev.all_day ? ev.end : new Date(ev.end).toISOString(), recurring: !!ev.rrule, status: ev.status, role: ev.role};
      if (!ev.all_day) { const s = new Date(`${ev.start}:00`), en = new Date(`${ev.end}:00`); e.start = s.toISOString(); e.end = en.toISOString(); }
      evPop(anchor, cevPrep(e));
    }, 120);
  }).catch(() => toast(tr('This event does not exist or you cannot see it.')));
}
function evTaskHtml(t, ro) {  // the events a task prepares + "Schedule as an event"
  if (!evOn() || !t || t.id <= 0 || t.context) return '';
  const evs = (S.evlinks || {})[t.id] || [];
  const when = e => e.all_day ? fmtDayAbs(e.start.slice(0, 10)) : `${fmtDayAbs(e.start.slice(0, 10))} ${fmtTimeLoc(e.start.slice(11, 16))}`;
  return `<div class="lkgrp"><span class="lklab">${tr('Events')}</span><div class="lkitems">${evs.map(e => `<button type="button" class="lkchip" data-evopen="${e.id}">${ic('cal', 's')}<span>${esc(e.title)}</span><span class="muted">${esc(when(e))}</span></button>`).join('')}
    ${ro ? '' : `<button type="button" class="attadd" data-act="ev-from-task">${ic('plus', 's')}<span>${tr('Schedule as an event')}</span></button>`}</div></div>`;
}
document.addEventListener('click', e => {
  const o = e.target.closest('[data-evopen]');
  if (o) { e.preventDefault(); evOpen(+o.dataset.evopen); return; }
  const a = e.target.closest('[data-act="ev-from-task"]');
  if (a) {
    const t = taskById(S.sel); if (!t) return;
    const day = t.due || today();
    // the people who come along (module Family) are invited
    const att = (t.people || []).filter(u => u !== S.me?.id).map(u => ({user_id: u, name: personName(t.list_id, u), partstat: 'needs-action'}));
    evEditor({title: t.title, task_id: t.id, all_day: !t.due_time, start: t.due_time ? `${day}T${t.due_time}` : day, end: t.due_time ? evAddMin(`${day}T${t.due_time}`, t.duration || 60) : addDays(day, 1), attendees: att});
    return;
  }
  const n = e.target.closest('[data-act="ev-new"]');
  if (n) { const d = S.calSel || today(); evEditor({start: `${d}T${pad(Math.min(22, new Date().getHours() + 1))}:00`}); return; }
  const m = e.target.closest('[data-act="ev-cals"]');
  if (m) { evCalsModal(); return; }
  if (e.target.closest('[data-act="dav-guide"]')) davGuide();
});
