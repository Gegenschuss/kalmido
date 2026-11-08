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
// 2.657.0 (#5052): a calendar's settings with the version read (expect_updated_at; changed meanwhile = 409, its current version kept for the next try)
const evcVerKeep = (id, v) => { const x = evCal(id); if (x && v) x.updated_at = v; };
const evcPatch = (id, b) => api('PATCH', `/api/evcals/${id}`, {...b, expect_updated_at: evCal(id)?.updated_at || undefined})
  .then(j => { evcVerKeep(id, j?.updated_at); return j; }, e => { evcVerKeep(id, e?.data?.current?.updated_at); throw e; });
// 2.46.2 (#1659): a calendar's new name shows at once (optimistic, an error puts the old one back), no reload of everything
function evCalRename(id, name, draw) {
  const put = () => {
    const x = evCal(id), y = (S.cal.evcals || {})[id], o1 = x?.name, o2 = y?.name;
    if (x) x.name = name; if (y) y.name = name;
    return () => { if (x) x.name = o1; if (y) y.name = o2; };
  };
  return optWrite(put, () => evcPatch(id, {name}), draw).then(() => cvxCals(true).then(draw), () => {});
}
const evWrite = c => !!c && (c.role === 'owner' || c.role === 'edit');
const evWritable = () => (S.evcals || []).filter(c => evWrite(c) && !c.hidden && wsObjIn(c));  // 2.30.0 (#1036): of the shown workspace
const EV_PS = [['accepted', N_('Accept'), 'check'], ['tentative', N_('Maybe'), 'help'], ['declined', N_('Reject'), 'x']];
const EV_PS_WORD = {accepted: N_('Accepted'), tentative: N_('Maybe'), declined: N_('Rejected'), 'needs-action': N_('No answer yet')};
// all-day reminders: minutes before the day's midnight (-540 = 9:00 on the day)
const EV_REM_TIMED = ['0', '5', '10', '15', '30', '60', '120', '1440', '2880', '10080'];
const EV_REM_DAY = [['-540', N_('On the day at 9:00')], ['900', N_('1 day before at 9:00')], ['2340', N_('2 days before at 9:00')], ['9540', N_('1 week before at 9:00')]];
// timed: how long before the start (the row says "Reminders"; the same short form for every chip)
const EV_REM_TXT = {'0': N_('At the start'), '5': N_('5 min'), '10': N_('10 min'), '15': N_('15 min'), '30': N_('30 min'), '60': N_('1 h'), '120': N_('2 h'),
  '1440': N_('1 day'), '2880': N_('2 days'), '10080': N_('1 week')};
const evRemLabel = (m, allDay) => { if (allDay) { const o = EV_REM_DAY.find(x => x[0] === String(m)); if (o) return tr(o[1]); } return EV_REM_TXT[String(m)] ? tr(EV_REM_TXT[String(m)]) : remLabel(String(m)); };
const evCalColor = e => cssColor((S.cal.evcals || {})[e.cal]?.color) || cssColor(evCal(e.cal)?.color) || 'var(--accent)';
const evCalName = e => e.cal == null ? tr('Invitation') : (S.cal.evcals || {})[e.cal]?.name || evCal(e.cal)?.name || tr('Calendar');
// 2.559.0 (#4659): calendar writes show at once, like optWrite (core.js) for the state: put() changes the shown range (S.cal.items,
// S.evcals) and returns how to take it back; the request runs behind it (no GET /api/state). While it runs, a range fetched
// meanwhile (calInvalidate / evsig, then cevApply) and a state fetched meanwhile (core.js OPT) get the change again on top, so it
// never flickers back. An error (api() said why) puts the old state back and fetches the range again.
const EV_OPT = new Set();
if (typeof cevApply === 'function') { const ev_apply0 = cevApply; cevApply = (j, key) => { ev_apply0(j, key); for (const p of EV_OPT) p.put(); }; }  // calendar.js
async function evOpt(put, req, draw = renderView) {
  const backs = [], p = {put: () => { const b = put(); if (b) backs.push(b); }};
  p.put(); EV_OPT.add(p); OPT.add(p); draw();
  try { return await req(); }
  catch (e) { EV_OPT.delete(p); OPT.delete(p); for (const b of backs.reverse()) b(); calInvalidate(); draw(); throw e; }
  finally { EV_OPT.delete(p); OPT.delete(p); }
}
// several puts as one (each applied again on its own: one may find its part done already)
const evPuts = (...ps) => () => { const bs = ps.map(f => f()).filter(Boolean); return bs.length ? () => bs.reverse().forEach(b => b()) : null; };
// the task panel's events (S.evlinks: task id -> [{id, title, start, all_day}], from the state): event eid prepares task tid
// with v = {title, start, all_day}; tid / v null = it leaves every task's list
function evLinkPut(eid, tid, v) {
  return () => {
    const L = S.evlinks || (S.evlinks = {}), was = JSON.stringify(L);
    for (const k of Object.keys(L)) if (L[k].some(e => e.id === eid)) L[k] = L[k].filter(e => e.id !== eid);
    if (tid && v) (L[tid] = L[tid] || []).push({id: eid, ...v});
    if (JSON.stringify(L) === was) return null;
    return () => { S.evlinks = JSON.parse(was); };
  };
}
// the shown occurrences of event eid (all of them, or the one of date occ); a stand-in of a new one has a negative eid (evEditor)
const evItems = (eid, occ) => S.cal.items.filter(x => x.own && x.eid === eid && (occ == null || x.occ === occ));
// the put of a change of shown occurrences: pick() = the items, vals(x, o) = their new fields (o = the values before, kept from the
// first time, so a shift is never applied twice to a range fetched again); an item already changed by this put is left alone
function evItemsPut(pick, vals) {
  const tok = {}, old = new Map(), k = x => x.own ? x.eid + '|' + x.occ : 's' + x.id;
  return () => {
    let n = 0;
    for (const x of pick()) {
      if (x._evo === tok) continue;
      const o = old.get(k(x)) || {...x}, v = vals(x, o); if (!v) continue;
      if (!old.has(k(x))) old.set(k(x), Object.fromEntries(Object.keys(v).map(f => [f, x[f]])));
      Object.assign(x, v); x._evo = tok; cevPrep(x); n++;
    }
    return n ? () => { for (const x of pick()) if (x._evo === tok) { Object.assign(x, old.get(k(x)) || {}); delete x._evo; cevPrep(x); } } : null;
  };
}
// a local wall time "YYYY-MM-DDTHH:MM" as the range has it (UTC); all-day: the date as it is
const evIso = (s, allDay) => allDay ? s.slice(0, 10) : new Date(s.length === 10 ? s + 'T00:00' : s).toISOString().replace(/\.\d{3}Z$/, 'Z');

// ---- the popover of an own event (occurrence e from S.cal.items)
function evWhen(e) {
  return cevWhen(e.d0 ? e : cevPrep({...e}));
}
async function evPop(anchor, e) {
  if (e.eid < 0) return;  // 2.559.0 (#4659): the stand-in of a new event still on its way (evEditor) has nothing to open yet
  const p = openPop(anchor, `<div class="cevpop evpop" style="--cc:${evCalColor(e)}"><div class="cevh"><i class="cevdot"></i><b>${esc(cevTitle(e))}</b></div><div class="muted">${tr('Loading…')}</div></div>`);
  let ev;
  try { ev = await api('GET', `/api/events/${e.eid}`); } catch { closePop(); return; }
  if ($('#pop').classList.contains('hidden')) return;
  if (AP_EVPEND.has(ev.id)) { ev.status = AP_EVPEND.get(ev.id); e = {...e, status: ev.status}; }  // 2.144.2 B (#1811): a confirm still on its way
  const role = ev.role, w = role === 'owner' || role === 'edit', me = (ev.attendees || []).find(a => a.user_id === S.me?.id);
  const att = ev.attendees || [];
  const t = ev.task_id ? taskById(ev.task_id) : null;
  const desc = (e.description || '').slice(0, 2000);
  p.innerHTML = `<div class="cevpop evpop" style="--cc:${evCalColor(e)}">
    <div class="cevh"><i class="cevdot"></i><b>${esc(cevTitle(e))}</b>${e.status === 'cancelled' ? `<span class="evst">${tr('Cancelled')}</span>` : (ev.status || e.status) === 'tentative' ? `<span class="evst evdraftb">${tr('Draft')}</span>` : ''}</div>
    <div class="cevm">${ic('clock', 's')}<span>${esc(evWhen(e))}</span></div>
    ${e.recurring ? `<div class="cevm">${ic('repeat', 's')}<span>${esc(repeatLabel(ev.rrule) || tr('Repeats'))}${e.changed ? ' · ' + esc(tr('this date changed')) : ''}</span></div>` : ''}
    ${e.location ? `<div class="cevm">${ic('mappin', 's')}<span>${esc(e.location)}</span></div>` : ''}
    <div class="cevm">${ic('cal', 's')}<span>${esc(evCalName(e))}${w ? '' : ' · ' + esc(tr('read-only'))}</span>${cvxTodayBtn(e)}</div>
    ${att.length ? `<div class="cevm evatt">${ic('users', 's')}<span>${att.slice(0, 8).map(a => `<span class="evap ps-${esc(a.partstat)}" title="${esc(tr(EV_PS_WORD[a.partstat] || ''))}">${esc(a.name || a.email)}</span>`).join(', ')}${att.length > 8 ? ' …' : ''}</span></div>` : ''}
    ${ev.reminders?.length ? `<div class="cevm">${ic('bell', 's')}<span>${esc(ev.reminders.map(m => evRemLabel(m, ev.all_day)).join(', '))}</span></div>` : ''}
    ${desc ? `<div class="cevdesc">${cevLinkify(desc)}</div>` : ''}
    ${typeof hbm_linkHtml === 'function' ? hbm_linkHtml('event', ev.id) : ''}${''/* 2.141.0 B (#2139): the e-mail the event was made from (hubmail.js) */}
    ${t ? `<button class="linkbtn evtask" data-evp="task">${ic('done', 's')} ${esc(tr('Preparation: {0}', t.title))}</button>` : ''}
    ${me ? `<div class="evrsvp" role="group" aria-label="${esc(tr('Your answer'))}">${EV_PS.map(([k, n, i]) => `<button class="btn sm ${me.partstat === k ? 'on' : ''}" data-evps="${k}" aria-pressed="${me.partstat === k}">${ic(i, 's')} ${tr(n)}</button>`).join('')}</div>` : ''}
    ${w && ev.status === 'tentative' && !e.recurring ? `<div class="cevact apdraftact"><button class="btn sm pri" data-evp="apok">${ic('check', 's')} ${tr('Confirm')}</button><button class="btn sm" data-evp="del">${ic('x', 's')} ${tr('Discard')}</button></div>` : ''}
    <div class="cevact">${w ? `<button class="btn sm${ev.status === 'tentative' && !e.recurring ? '' : ' pri'}" data-evp="edit">${ic('edit', 's')} ${tr('Edit')}</button>${!ev.task_id ? `<button class="btn sm" data-evp="prep">${ic('plus', 's')} ${tr('Preparation task')}</button>` : ''}<button class="btn sm danger" data-evp="del">${ic('trash', 's')} ${tr('Delete')}</button>` : `<button class="btn sm" data-evp="totask">${ic('plus', 's')} ${tr('Create task from event')}</button>`}${feat('wiki') ? `<button class="btn sm" data-evp="minutes" title="${esc(tr('Minutes of this event as a knowledge page'))}">${ic('note', 's')} ${tr('Minutes|meeting')}</button>` : ''}</div></div>`;
  p.onclick = async ev2 => {
    const ps = ev2.target.closest('[data-evps]');
    if (ps) { try { await api('POST', `/api/events/${ev.id}/rsvp`, {partstat: ps.dataset.evps}); } catch { return; } closePop(); toast(tr('Answer sent: {0}', tr(EV_PS_WORD[ps.dataset.evps]))); calInvalidate(); renderView(); return; }
    const b = ev2.target.closest('[data-evp]'); if (!b) return;
    const k = b.dataset.evp;
    // 2.144.2 B (#1811): the draft marks leave the popover at once, so no picture of it (the phone sheet's exit, a sheet
    // shown again) still says Draft + Confirm after the tap
    if (k === 'apok') p.querySelectorAll('.apdraftact, .evdraftb').forEach(x => x.remove());
    closePop();
    if (k === 'edit') evEditor({ev, occ: e.recurring ? e.occ : null});
    else if (k === 'del') evDelete(ev, e.recurring ? e.occ : null);
    else if (k === 'task') openDetail(ev.task_id);
    else if (k === 'apok') ap_evConfirm(ev);  // 2.51.0 C (#1355): a draft (tentative) becomes confirmed (agentplan.js)
    else if (k === 'prep') evPrepTask(ev);
    else if (k === 'totask') cevToTask(cevPrep({...e}));
    // 2.384.0 (#1958): the minutes as a knowledge page (wiki.js wk_minutes; this date of a series)
    else if (k === 'minutes') wk_minutes({eid: ev.id, cal_id: ev.cal_id, day: e.d0 || String(e.start || ev.start).slice(0, 10), title: cevTitle(e), when: evWhen(e), location: e.location || '', description: e.description || '', attendees: att});
  };
}
// 2.484.0 (#3945): a date of a series with its own change (an override, RECURRENCE-ID) is a single event to the user: dragging,
// the editor and deleting change only it, never ask "Only this date / All dates"; the series' changes leave it as it is
const evOccOwn = (ev, occ) => !!occ && (ev?.overrides || []).some(x => x.rid === occ);
async function evDelete(ev, occ) {
  let mode = 'all';
  if (evOccOwn(ev, occ)) {
    if (!await askConfirm(tr('Delete the event “{0}”?', (ev.overrides.find(x => x.rid === occ).title) || ev.title), '', {ok: tr('Delete'), danger: true})) return;
    mode = 'one';
  } else if (occ) {
    const r = await evAskScope(tr('Delete a repeating event'), tr('Delete'));
    if (!r) return;
    mode = r;
  } else if (!await askConfirm(tr('Delete the event “{0}”?', ev.title), '', {ok: tr('Delete'), danger: true})) return;
  // 2.559.0 (#4659): the event leaves the calendar at once, the request runs behind it (an error brings it back); the undo
  // of the toast puts its dates back at once as well
  const gone = [], put = () => {
    const its = S.cal.items, keep = its.filter(x => !(x.own && x.eid === ev.id && (mode === 'all' || x.occ === occ)));
    if (keep.length === its.length) return null;
    for (const x of its) if (!keep.includes(x) && !gone.some(g => g.occ === x.occ)) gone.push(x);
    S.cal.items = keep; return () => { S.cal.items = its; };
  };
  const lk = mode === 'all' ? evLinkPut(ev.id, null, null) : () => null;
  try { await evOpt(evPuts(put, lk), () => api('DELETE', `/api/events/${ev.id}` + (mode === 'one' ? `?occ=${encodeURIComponent(occ)}` : '')), render); } catch { return; }
  calInvalidate(); render();
  const back = () => {
    const add = gone.filter(g => !S.cal.items.some(x => x.own && x.eid === g.eid && x.occ === g.occ));
    if (!add.length) return null;
    const its = S.cal.items; S.cal.items = its.concat(add); return () => { S.cal.items = its.filter(x => !add.includes(x)); };
  };
  if (mode === 'all') toast(tr('Event deleted'), async () => { try { await evOpt(back, () => api('POST', `/api/events/${ev.id}/restore`)); } catch { return; } calInvalidate(); renderView(); });
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
  ['W2', N_('Every 2 weeks')], ['M', N_('Monthly')], ['FREQ=YEARLY', N_('Yearly')], ['__custom', N_('Custom…')]];  // 2.155.0 C (#2075): the own rule (calrrule.js)
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
// 2.559.0 (#4659): the puts of the editor's save (evOpt). A new event: one stand-in (its first date) with a negative eid; left out
// once the range fetched meanwhile has the real one already
let EV_TMP = 0;
function evNewPut(body, natt) {
  const eid = --EV_TMP, id = 'evtmp' + -eid, start = evIso(body.start, body.all_day), end = evIso(body.end, body.all_day);
  const put = () => {
    if (S.cal.items.some(x => x.id === id || (x.own && x.eid > 0 && x.cal === body.cal_id && x.title === body.title && x.start === start))) return null;
    const x = cevPrep({id, eid, occ: body.start, own: true, cal: body.cal_id, title: body.title, location: body.location, description: body.description,
      all_day: body.all_day, start, end, recurring: !!body.rrule, changed: false, status: body.status || 'confirmed', role: 'owner', task_id: body.task_id || null, att: natt});
    S.cal.items = S.cal.items.concat(x);
    return () => { S.cal.items = S.cal.items.filter(y => y.id !== id); };
  };
  const all = evPuts(put, body.task_id ? evLinkPut(eid, body.task_id, {title: body.title, start: body.start, all_day: body.all_day}) : () => null);
  all.tmp = eid;
  return all;
}
// a changed event: its shown dates take the new title, place, calendar ...; the times only where one date is meant (a single event,
// "Only this date"): the series' new times come with the range fetched again
function evSavePut(ev, occ, body) {
  const one = occ != null || !ev.rrule, lk0 = Object.values(S.evlinks || {}).flat().find(e => e.id === ev.id);
  const lk = 'task_id' in body ? evLinkPut(ev.id, body.task_id, {title: body.title, start: one || !lk0 ? body.start : lk0.start, all_day: body.all_day}) : () => null;
  return evPuts(lk, evItemsPut(() => evItems(ev.id, occ), () => {
    const v = {title: body.title, location: body.location, description: body.description};
    if (body.cal_id != null) v.cal = body.cal_id;
    if (body.status) v.status = body.status;
    if (one) Object.assign(v, {all_day: body.all_day, start: evIso(body.start, body.all_day), end: evIso(body.end, body.all_day)});
    return v;
  }));
}
// 2.565.0 (#4705): one date of a series as the editor shows it for "Only this date" (its own change or the series' values)
function evOccView(ev, occ) {
  const ov = (ev.overrides || []).find(x => x.rid === occ);
  const end = ov?.end || (ev.all_day ? addDays(occ, Math.max(1, diffDays(ev.start.slice(0, 10), ev.end.slice(0, 10)))) : evAddMin(occ, evMin(ev.start, ev.end)));
  return {title: ov?.title ?? ev.title, location: ov?.location ?? ev.location, description: ov?.description ?? ev.description, all_day: ov?.all_day ?? ev.all_day,
    start: ov?.start || occ, end, updated_at: ev.updated_at};
}
// 2.565.0 (#4705): the editor's fields for the marks of a conflict (objsave.js objMerge)
const EV_FLD = {title: 'ev-title', cal_id: 'ev-cal', location: 'ev-loc', description: 'ev-desc', tz: 'ev-tz', status: 'ev-status', url: 'ev-url', all_day: 'ev-allday', busy: 'ev-busy'};
function evField(md, k) {
  const el = EV_FLD[k] ? $('#' + EV_FLD[k], md)?.closest('.row') : k === 'start' ? $('#ev-sd', md)?.closest('.row') : k === 'end' ? $('#ev-ed', md)?.closest('.row')
    : k === 'rrule' ? $('.evrep', md) : k === 'reminders' ? $('.evrems', md) : k === 'attendees' ? $('.evatts', md) : null;
  const d = el?.closest('details'); if (d) d.open = true;
  return el || null;
}
async function evEditor(o = {}) {
  const ev = o.ev || null, cals = evWritable().concat(ev && !evWritable().some(c => c.id === ev.cal_id) && evCal(ev.cal_id) ? [evCal(ev.cal_id)] : []);
  if (!cals.length && !o.dvw) { try { const c = await api('POST', '/api/evcals', {name: tr('Calendar'), org_id: wsDefaultOrg()}); await load(); cals.push(c); } catch { return; } }
  const t0 = today();
  const st = ev ? {...ev} : {title: o.title || '', all_day: !!o.all_day, start: o.start || `${S.calSel || t0}T09:00`, end: o.end || '', location: o.location || '',
    description: o.description || '', rrule: '', reminders: o.all_day ? [-540] : [15], attendees: [], cal_id: o.cal_id || +LS.get('evCal', 0) || cals[0].id,
    task_id: o.task_id || null, status: 'confirmed', busy: true, url: null, tz: evTz()};
  if (!ev && o.attendees) st.attendees = o.attendees;
  if (!cals.some(c => c.id === st.cal_id) && !dvw_cals(o).some(c => c.id === st.cal_id)) st.cal_id = cals[0].id;  // 2.52.0 (#1128): or a writable subscription
  if (!st.end) st.end = st.all_day ? addDays(st.start.slice(0, 10), 1) : evAddMin(st.start, 60);
  const single = evOccOwn(ev, o.occ);  // 2.484.0 (#3945): a changed date of a series: edited like a single event
  let scope = o.occ ? (single ? 'one' : 'all') : null;
  if (o.occ && ev) {  // opened from one date of a repeating event: that date's times are the ones shown for "Only this date"
    const ov = (ev.overrides || []).find(x => x.rid === o.occ);
    st.occStart = ov?.start || o.occ;
    st.occEnd = ov?.end || (ev.all_day ? addDays(o.occ, Math.max(1, diffDays(ev.start.slice(0, 10), ev.end.slice(0, 10)))) : evAddMin(o.occ, evMin(ev.start, ev.end)));
    if (single) Object.assign(st, {title: ov.title ?? st.title, location: ov.location ?? st.location, description: ov.description ?? st.description,
      all_day: ov.all_day ?? st.all_day, start: st.occStart, end: st.occEnd});
  }
  const [people] = await Promise.all([evPeople(), loadModule('evinvite').catch(() => {}),  // 2.149.0 F (#2518): evinvite.js loads with the people
    loadModule('calrrule').catch(() => { /* offline without the copy: the list has no own rules */ }),  // 2.155.0 C (#2075)
    ev ? loadModule('objsave').catch(() => { /* offline without the copy: saved as before */ }) : null]);  // 2.565.0 (#4705)
  const ppl = new Map(people.map(u => [u.id, u.display_name]));
  const atts = (st.attendees || []).map(a => ({...a}));
  const endDay = s => st.all_day ? addDays(s, -1) : s.slice(0, 10);  // all day: the shown end is the last day (stored exclusive)
  const repK = evRepKey(st.rrule, st.start);
  const md = modal(`<div class="lhdr"><h3>${ev || o.dvw ? tr('Edit event') : tr('New event')}</h3><span class="spacer"></span><button class="iconbtn" data-evm="close" aria-label="${tr('Close')}">${ic('x')}</button></div>
    ${o.occ && !single ? `<div class="row"><span class="rlab">${tr('Change')}</span><div class="seg" role="radiogroup" aria-label="${esc(tr('Change'))}"><button type="button" role="radio" data-evsc="one" aria-checked="false">${tr('Only this date')}</button><button type="button" role="radio" data-evsc="all" class="on" aria-checked="true">${tr('All dates')}</button></div></div>` : ''}
    <div class="row"><label for="ev-title">${tr('Title')}</label><input id="ev-title" maxlength="500" value="${esc(st.title)}" autocomplete="off" enterkeyhint="done"></div>
    <div class="row"><label for="ev-cal">${tr('Calendar')}</label><select id="ev-cal" data-sheet-ico="cal">${o.dvw ? '' : cals.map(c => `<option value="${c.id}" ${c.id === st.cal_id ? 'selected' : ''}>${esc(c.name)}${c.role !== 'owner' ? ' · ' + esc(c.owner_name || '') : ''}</option>`).join('')}${dvw_options(o, st.cal_id)}</select></div>
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
  // 2.484.0 (#3945): a changed date of a series shows the rows of "Only this date" (after dvw_rows, which shows them again)
  const rows = () => { dvw_rows(md); if (single) $('.evrep', md).hidden = $('.evatts', md).hidden = $('.evrems', md).hidden = true; };
  const val = id => $('#' + id, md)?.value || '';
  const drawRems = () => {
    const ad = $('#ev-allday', md).checked, opts = ad ? EV_REM_DAY.map(x => x[0]) : EV_REM_TIMED;
    const on = new Set((st.reminders || []).map(String));
    const all = [...new Set([...opts, ...on])];
    $('#ev-rems', md).innerHTML = all.map(m => `<button type="button" class="chip evchip ${on.has(m) ? 'on' : ''}" data-evrem="${m}" aria-pressed="${on.has(m)}">${esc(evRemLabel(m, ad))}</button>`).join('');
  };
  const drawAtts = () => {
    efb_go(md, atts, ev);  // 2.155.0 B (#2077): the availability bar (calabs.js)
    $('#ev-atts', md).innerHTML = atts.length ? atts.map((a, i) => `<span class="evatp ps-${esc(a.partstat || 'needs-action')}">${a.user_id ? av(a.user_id, a.name || ppl.get(a.user_id) || '') : ic(a.contact_id ? 'user' : 'at', 's')}<span>${esc(a.name || ppl.get(a.user_id) || a.email)}</span><span class="muted evps">${esc(tr(EV_PS_WORD[a.partstat || 'needs-action']))}</span><button type="button" class="iconbtn" data-evatrm="${i}" aria-label="${esc(tr('Remove {0}', a.name || a.email || ''))}">${ic('x', 's')}</button></span>`).join('')
      : `<span class="muted">${tr('Only you')}</span>`;
    if (typeof evi_draw === 'function') evi_draw(md, atts);  // 2.111.0 B (#2056): the invitation switch (evinvite.js)
  };
  drawRems(); drawAtts(); rows(); if (typeof evi_init === 'function') evi_init(md, ev, atts);
  // 2.565.0 (#4705): what the dialog would save now (sc = 'one': only this date's fields), read once as it opened (base); the
  // event the dialog builds on is the server's one (after a conflict: the current one, o.cf.raw)
  const form = sc => {
    const ad = $('#ev-allday', md).checked, sd = val('ev-sd'), ed = val('ev-ed') || sd;
    const body = {title: val('ev-title').trim() || tr('(no title)'), all_day: ad, location: val('ev-loc').trim(), description: val('ev-desc')};
    if (ad) { body.start = sd; body.end = addDays(ed < sd ? sd : ed, 1); } else { body.start = `${sd}T${val('ev-stm') || '09:00'}`; body.end = `${ed}T${val('ev-etm') || '10:00'}`; }
    if (sc === 'one') return body;
    const rk = val('ev-rep');
    let rule = rk === 'custom' ? rrBase(st.rrule) : rk ? evRepRule(rk, body.start) : '';
    if (rule) rule = rrSetEnd(rule, {type: val('ev-repend'), val: val('ev-repend') === 'until' ? val('ev-until') : val('ev-count')});
    Object.assign(body, {rrule: rule, reminders: st.reminders || [], cal_id: +val('ev-cal'), tz: val('ev-tz'), status: val('ev-status'), busy: $('#ev-busy', md).checked,
      url: val('ev-url').trim() || null, task_id: st.task_id || null,
      attendees: atts.map(a => a.user_id ? {user_id: a.user_id, partstat: a.partstat || 'needs-action'} : a.contact_id ? {contact_id: a.contact_id, partstat: a.partstat || 'needs-action'} : {email: a.email, name: a.name || '', partstat: a.partstat || 'needs-action'})});
    if (typeof evi_gv === 'function') { const gv = evi_gv(md); if (gv !== null) body.guests_visible = gv; }  // 2.380 H (#3392)
    return body;
  };
  const srv = o.cf?.raw || ev, dlg = ev && !o.dvw && typeof saveDialog === 'function' ? {base: objBase(form(scope), o.cf?.mine)} : null;
  const evAgain = (raw, mine, cf) => {  // the editor again on the current event, what was typed over it
    const m = {...mine}; delete m.send_invites;
    if (scope === 'one') { const ov = {rid: o.occ, ...evOccView(raw, o.occ), ...m}; delete ov.updated_at; return evEditor({ev: {...raw, overrides: [...(raw.overrides || []).filter(x => x.rid !== o.occ), ov]}, occ: o.occ, cf}); }
    return evEditor({ev: {...raw, ...m, ...(m.attendees ? {attendees: atts} : {})}, occ: o.occ, cf});
  };
  if (dlg) {  // lazy-ok-begin: dlg exists only once objsave.js is loaded (typeof saveDialog above, evEditor loads the module)
    const view = () => scope === 'one' ? (x => evOccView(x, o.occ)) : undefined, opened = () => scope === 'one' ? evOccView(srv, o.occ) : srv;
    dlg.save = (url, body) => saveDialog(url, opened(), body, {exp: 'expect', key: 'event', base: dlg.base, view: view(), get: `/api/events/${ev.id}`,
      send: x => rawFetch('PATCH', url, x).catch(e => { if (e.status !== 409 && e.message !== 'auth' && !e.shown) toast(e instanceof Offline ? tr('Offline: only works again with a connection') : e.message); throw e; })});
    dlgStale(md, `/api/events/${ev.id}`, () => srv.updated_at, raw => {
      const now = form(scope), cur = view() ? view()(raw) : raw, op = opened();
      md.remove(); evAgain(raw, objDiff(dlg.base, now), {raw, cur, mine: objDiff(dlg.base, now), theirs: Object.keys(now).filter(k => !objSame(op[k], cur[k])), both: []});
    });
    if (o.cf?.theirs.length) objMerge(md, o.cf, () => {}, {field: k => evField(md, k),
      take: keys => { md.remove(); evAgain(o.cf.raw, Object.fromEntries(Object.entries(o.cf.mine || {}).filter(([k]) => !keys.includes(k))), null); }});
  }  // lazy-ok-end
  if (typeof crr_wire === 'function') crr_wire(md, st, () => val('ev-sd') || st.start);  // 2.155.0 C (#2075)
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
    else { toast(tr('Select a person from the list or type an e-mail address')); return; }
    inp.value = ''; drawAtts(); inp.focus();
  };
  md.addEventListener('input', e => { if (e.target.id === 'ev-attin') attList(e.target.value.trim()); });
  md.addEventListener('keydown', e => { if (e.target.id === 'ev-attin' && e.key === 'Enter') { e.preventDefault(); attAdd(); } });
  md.addEventListener('change', e => {
    const id = e.target.id;
    if (id === 'ev-cal') rows();  // 2.52.0 (#1128)
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
      if (typeof evi_draw === 'function') evi_draw(md, atts);
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
      const sub = dvw_isSub(val('ev-cal')), body = form(scope === 'one' || sub ? 'one' : 'all');  // 2.565.0 (#4705): one reader of the form (form)
      if (!body.all_day && body.end < body.start) { toast(tr('The end must be after the start')); return; }
      if (typeof evi_on === 'function' && evi_on(md)) body.send_invites = true;  // 2.111.0 B (#2056)
      if (sub) { delete body.send_invites; b.disabled = true; if (await dvw_save(o, val('ev-cal'), body)) md.remove(); else b.disabled = false; return; }  // 2.52.0 (#1128): a subscribed CalDAV calendar
      let req;
      // 2.565.0 (#4705): an existing event sends only what was changed in the dialog, with the version it builds on; a conflict
      // comes back as e.cf (the dialog again on the current event)
      const dsave = url => () => dlg.save(url, body).then(j => { if (j?.conflict) throw Object.assign(new Error('conflict'), {cf: j.conflict}); return j; });
      if (scope === 'one') {
        const url = `/api/events/${ev.id}?occ=${encodeURIComponent(o.occ)}`;
        req = dlg ? dsave(url) : () => api('PATCH', url, {...body, expect: srv.updated_at});  // 2.273.0 C (#3051): like the series
      } else {
        if (body.url && !validUrl(body.url)) { toast(tr('The link must start with http:// or https://')); return; }
        req = ev && dlg ? dsave(`/api/events/${ev.id}`) : () => ev ? api('PATCH', `/api/events/${ev.id}`, {...body, expect: srv.updated_at}) : api('POST', '/api/events', body);
        LS.set('evCal', body.cal_id);
      }
      // 2.559.0 (#4659): the dialog closes at once and the event stands (a new one as a stand-in with a negative id until the
      // answer), no GET /api/state; an error puts the calendar back and opens the editor again with what was typed
      md.remove();
      const put = ev ? evSavePut(ev, scope === 'one' ? o.occ : null, body) : evNewPut(body, atts.length);
      let j;
      try { j = await evOpt(put, req, render); } catch (e) {  // nothing typed is lost (a conflict 409 too: api() said why)
        if (e?.cf) { toast(tr('Changed by someone else in the meantime')); evAgain(e.cf.raw, e.cf.mine, e.cf); return; }  // 2.565.0 (#4705)
        if (dlg) { const mine = objDiff(dlg.base, body); evAgain(srv, mine, {raw: srv, cur: srv, mine, theirs: [], both: []}); return; }  // lazy-ok: dlg only with objsave.js loaded; what was typed stays "changed" for the next save
        // "Only this date": what was typed comes back as that date's own change (the editor then saves only it again)
        const ov = {rid: o.occ, title: body.title, location: body.location, description: body.description, all_day: body.all_day, start: body.start, end: body.end};
        evEditor(!ev ? {...o, ...body, attendees: atts} : scope === 'one' ? {ev: {...ev, overrides: [...(ev.overrides || []).filter(x => x.rid !== o.occ), ov]}, occ: o.occ}
          : {ev: {...ev, ...body, cal_id: body.cal_id ?? ev.cal_id, attendees: atts}, occ: o.occ});
        return;
      }
      if (!ev && j?.id) {  // clickable before the range / the state come again
        for (const x of S.cal.items) if (x.eid === put.tmp) x.eid = j.id;
        for (const a of Object.values(S.evlinks || {})) for (const x of a) if (x.id === put.tmp) x.id = j.id;
      }
      calInvalidate(); render();
      toast(ev ? tr('Event saved') : tr('Event created'));
    }
  });
  setTimeout(() => { if (!ev) $('#ev-title', md)?.focus(); }, 40);
  return md;
}
const evMin = (a, b) => Math.max(0, Math.round((new Date(b) - new Date(a)) / 60000));
function evAddMin(s, m) { const d = new Date(s.length === 10 ? s + 'T00:00' : s); d.setMinutes(d.getMinutes() + m); return `${ds(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`; }

// ---- creating: the "+ Event" button of the calendar bar, the quick sheet ("Event")
function evNewAt(day, hm, endHm) {
  if (!evOn()) return;
  if (!hm) { evEditor({all_day: true, start: day, end: addDays(day, 1)}); return; }
  evEditor({start: `${day}T${hm}`, end: endHm ? `${day}T${endHm}` : ''});
}
// 2.52.0 (#1016): dragging over free time (and moving / resizing events) lives in caldrag.js: a block "New event" in the grid
// the quick sheet opened from a free slot of the calendar: "Event" turns what was typed into an event at that time
function evSheetBtn(preset) {
  const q = $('.qadd.sheet'); if (!q || !evOn() || !preset?.due || q.querySelector('.qevbtn') || isListCal()) return;  // 2.156.0 C (#2071): a list's calendar makes tasks only
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
  return calBar(tr('Agenda') + ` <span class="muted agrange">${esc(fmtDayAbs(from))} – ${esc(fmtDayAbs(to))}</span>`) + `<div class="agenda agendav">${h || `<div class="empty">${ic('cal')}${tr('Nothing in the next two weeks.')}</div>`}</div>`;
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
  let users = [];
  if (collab()) users = await evPeople();
  const md = modal(`<div class="lhdr"><h3>${ic('cal', 's')} ${tr('Calendars')}</h3><span class="spacer"></span><button class="iconbtn" data-evc="close" aria-label="${tr('Close')}">${ic('x')}</button></div><div id="evc-body"></div>
    <div class="foot">${feat('events') ? `<button class="btn" data-evc="phone">${ic('phone', 's')} ${tr('On the phone…')}</button>` : ''}${feat('events') && !S.me?.kid ? `<button class="btn" data-evc="booking">${ic('link', 's')} ${tr('Booking page…')}</button>` : ''}<span class="spacer"></span>${S.calendars?.enabled ? `<button class="btn" data-evc="subs">${ic('gear', 's')} ${tr('Subscriptions…')}</button>` : ''}${feat('events') ? `<button class="btn pri" data-evc="new">${ic('plus', 's')} ${tr('New calendar')}</button>` : ''}</div>`);
  md.classList.add('evcmodal');
  const st = {lists: false, trash: null};  // 2.566.0 (#4707): trash = the calendars in the trash once opened
  const sw = (key, kind, on, dis, label) => `<label class="swc ${dis ? 'off' : ''}" title="${esc(label)}"><input type="checkbox" data-cvx="${kind}" data-key="${key}" ${on ? 'checked' : ''} ${dis ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(label)}</span></label>`;
  const three = c => {  // Today + planning (off while the calendar is hidden: hidden = gone from Today and the planner too)
    const off = !c.on;
    return sw(c.key, 'today', c.on && !cvxList('today_cals_hidden').includes(c.key), off, tr('Show {0} on Today', c.name))
      + sw(c.key, 'plan', c.on && !cvxList('plan_cals_off').includes(c.key), off, tr('Consider {0} when planning', c.name));
  };
  const head = `<div class="cvxhead"><span class="cvxhn"></span><span title="${esc(tr('In my calendar'))}">${tr('Calendar|col')}</span><span title="${esc(tr('On Today'))}">${tr('Today')}</span><span title="${esc(tr('When planning'))}">${tr('Plan|col')}</span></div>`;
  const draw = () => {
    const cs = S.evcals || [], hidL = cvxList('cal_lists_hidden'), hidF = cvxList('cal_folders_hidden'), tasksOn = S.settings.cal_tasks !== '0';
    const lists = [...S.lists.filter(l => !l.archived && !l.is_inbox), ...S.lists.filter(l => !l.archived && l.is_inbox)];
    const nOff = lists.filter(l => cvxListOff(l.id, hidL, hidF)).length;  // 2.624.0 (#3946): also the ones off through a folder
    // tasks: one switch for all dated tasks, fold-out: one per list (the lists are only listed, never changed here);
    // 2.624.0 (#3946): grouped by folder like the sidebar (own lists first, then folder by folder, subfolders indented, the
    // inbox last), a switch per folder (cal_folders_hidden: its lists and subfolders off, also later ones); from 8 lists a search
    const tl = `<div class="cvxgrp">${tr('Tasks')}</div><div class="cvxrow" style="--cc:var(--accent)">
      ${sw('tasks', 'tasks', tasksOn, false, tr('Show tasks in my calendar'))}<i class="cevdot"></i><span class="evcn">${tr('Tasks with a date')}${nOff && tasksOn ? `<span class="muted"> · ${esc(trn('{0} project hidden', '{0} projects hidden', nOff))}</span>` : ''}</span>
      <button class="iconbtn cvxfold" data-evc="lists" aria-expanded="${st.lists}" aria-label="${esc(tr('Per project'))}" title="${esc(tr('Per project'))}">${ic('right', 's')}</button></div>
      ${st.lists ? cvf_lists(lists, hidL, hidF, tasksOn, sw, st.q) : ''}`;
    const own = !feat('events') ? '' : `<div class="cvxgrp">${tr('My calendars')}</div>${cs.length ? head + `<ul class="evclist">${cs.map(c => `<li class="evcrow" style="--cc:${cssColor(c.color) || 'var(--accent)'}">
      <i class="cevdot"></i><span class="evcn">${esc(c.name)}${wsOn() && c.role === 'owner' ? `<span class="muted wslbl"> · ${esc(wsLabel(c.org_id))}</span>` : ''}${c.role !== 'owner' ? `<span class="muted"> · ${esc(c.owner_name || '')} · ${esc(c.role === 'edit' ? tr('can edit') : tr('can view'))}</span>` : c.members?.length ? `<span class="muted"> · ${esc(trn('shared with {0} person', 'shared with {0} people', c.members.length))}</span>` : ''}</span>
      <label class="swc" title="${esc(tr('Show in my calendar'))}"><input type="checkbox" data-evcshow="${c.id}" ${c.hidden ? '' : 'checked'}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Show {0} in my calendar', c.name))}</span></label>
      ${three({key: `e:${c.id}`, name: c.name, on: !c.hidden})}
      <button data-rowmenu="evcrow" class="iconbtn" data-evcmenu="${c.id}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', c.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></li>`).join('')}</ul>`
      : `<p class="muted">${tr('No calendar yet. A new event creates one.')}</p>`}`;
    const subs = cvxVisibleCals(true).filter(c => !c.own);
    const sb = !S.calendars?.enabled ? '' : `<div class="cvxgrp">${tr('Subscriptions')}</div>${subs.length ? (cs.length && feat('events') ? '' : head) + subs.map(c => `<div class="cvxrow" style="--cc:${cssColor(c.color)}">
      <i class="cevdot"></i><span class="evcn">${esc(c.name)}</span>${sw(c.key, 'show', c.on, false, tr('Show {0} in my calendar', c.name))}${three(c)}
      <button data-rowmenu="cvxrow" class="iconbtn" data-cvxmenu="${c.key}" data-name="${esc(c.name)}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', c.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>`).join('')
      : `<p class="muted">${tr('No subscriptions yet. Add one under Settings > Integrations > Calendars.')}</p>`}`;
    // 2.566.0 (#4707): the calendars in the trash (the shared core's trash): opened on demand, restore with their events
    const tr2 = !feat('events') ? '' : `<button type="button" class="btn sm evctrbtn" data-evc="trash" aria-expanded="${!!st.trash}">${ic('trash', 's')} ${tr('Trash')}</button>${!st.trash ? ''
      : st.trash.items.length ? `<ul class="evclist evctrash" aria-label="${esc(tr('Trash'))}">${st.trash.items.map(c => `<li class="evcrow" style="--cc:${cssColor(c.color) || 'var(--accent)'}"><i class="cevdot"></i><span class="evcn">${esc(c.name)}<span class="muted"> · ${esc(trn('{0} event', '{0} events', c.events))} · ${esc(tr('In the trash since {0}', fmtDate((c.deleted_at || '').slice(0, 10))))}</span></span><button type="button" class="btn sm" data-evctr="${c.id}">${ic('undo', 's')} ${tr('Restore')}</button></li>`).join('')}</ul>`
      : `<p class="muted">${tr('The trash is empty')}</p>`}${st.trash?.trash_days ? `<p class="muted">${esc(trashNote(tr('Calendars in the trash are deleted permanently after {0} days, with their events.', st.trash.trash_days)))}</p>` : ''}`;
    $('#evc-body', md).innerHTML = tl + own + tr2 + sb + (typeof abc_group === 'function' ? abc_group() : '');  // 2.155.0 B (#2076)
    cvf_filter(md, st.q);  // 2.624.0 (#3946)
  };
  const redraw = () => { cvxRedraw(); draw(); };
  const refresh = async () => { await load().catch(() => {}); await cvxCals(true).catch(() => {}); redraw(); };
  md.addEventListener('input', e => { if (e.target.matches?.('[data-cvfq-in]')) { st.q = e.target.value; cvf_filter(md, st.q); } });  // 2.624.0 (#3946)
  md.addEventListener('change', async e => {
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
      menu(m, [own && {label: tr('Rename…'), icon: 'edit', fn: async () => { const n = await askPrompt(tr('Rename the calendar'), c.name, {input: {max: 100}}); if (n && n.trim()) evCalRename(c.id, n.trim(), redraw); }},  // 2.46.2 (#1659): at once
        own && {label: tr('Colour…'), icon: 'palette', fn: () => calColorPop(m, LCOLORS.filter(Boolean), c.color, async col => { try { await evcPatch(c.id, {color: col}); } catch { return; } refresh(); })},
        own && wsOn() && {label: tr('Workspace…'), icon: 'brief', fn: () => wsMoveMenu(m, c.org_id, async org => { try { await evcPatch(c.id, {org_id: org}); } catch { return; } refresh(); })},
        own && collab() && {label: tr('Share…'), icon: 'users', fn: () => evShareModal(c, users, refresh)},
        evWrite(c) && {label: tr('Import a calendar file (ICS)…'), icon: 'upload', fn: () => evImport(c, refresh)},
        {label: tr('Export (ICS)'), icon: 'download', fn: () => { location.href = `/api/evcals/${c.id}/export.ics`; }},
        {label: tr('Subscription link…'), icon: 'link', fn: () => evf_modal(c)},  // 2.111.0 B (#2056): evinvite.js
        {label: tr('Only this calendar'), icon: 'eye', fn: async () => { await cvxOnly(`e:${c.id}`); draw(); }},  // 2.36.1 (#1127)
        {label: tr('Show all calendars'), icon: 'all', fn: async () => { await cvxAll(); draw(); }},
        !own && {label: tr('Leave this calendar'), icon: 'logout', fn: async () => { if (!await askConfirm(tr('Leave the calendar “{0}”?', c.name), '', {ok: tr('Leave'), danger: true})) return; try { await api('DELETE', `/api/evcals/${c.id}/members/${S.me.id}`); } catch { return; } refresh(); }},
        own && {label: tr('Delete…'), icon: 'trash', cls: 'danger', fn: async () => { if (!await askConfirm(tr('Delete the calendar “{0}” with all its events?', c.name), tr('They can be restored from the trash.'), {ok: tr('Delete'), danger: true})) return; try { await api('DELETE', `/api/evcals/${c.id}`); } catch { return; } st.trash = null; refresh(); }}]);  // 2.566.0 (#4707): into the trash
      return;
    }
    const rb = e.target.closest('[data-evctr]');
    if (rb) {  // 2.566.0 (#4707): out of the trash with its events
      try { await api('POST', `/api/evcals/${+rb.dataset.evctr}/restore`); } catch { return; }
      toast(tr('Restored')); st.trash = null; calInvalidate(); await refresh(); renderView(); return;
    }
    const b = e.target.closest('[data-evc]'); if (!b) return;
    if (b.dataset.evc === 'trash') { st.trash = st.trash ? null : await api('GET', '/api/evcals/trash').catch(() => ({items: []})); draw(); return; }
    if (b.dataset.evc === 'close') md.remove();
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
function evShareModal(c, users, done) {
  const md = modal(`<h3>${tr('Share {0}', esc(c.name))}</h3><div class="shws"></div><div id="evs-list"></div>
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
function evImport(c, done, file) {  // 2.143.0 C (#2154): file = an .ics shared from another app (no file picker)
  const inp = document.createElement('input');
  inp.type = 'file'; inp.accept = '.ics,text/calendar';
  inp.onchange = async () => {
    const f = file || inp.files[0]; if (!f) return;
    // 2.87.9 (#1940): where the events go, in words; from an organisation's calendar also into an own private calendar
    // 2.144.5 B (#2002): also without one yet: it is made then (like the contact import's private address book)
    let pc = (S.evcals || []).find(x => !x.org_id && x.role === 'owner');
    const to = await importTargetConfirm({what: tr('the events'), ws: wsOf(c), place: c.name, privOk: true});
    if (!to) return;
    if (to === 'private' && !pc) { try { pc = await api('POST', '/api/evcals', {name: tr('Calendar'), org_id: null}); await load(); } catch { return; } }
    if (to === 'private') c = pc;
    const fd = new FormData(); fd.append('file', f);
    try {
      const r = await fetch(`/api/evcals/${c.id}/import`, {method: 'POST', body: fd, headers: {'X-Requested-With': 'kalmido'}, credentials: 'same-origin'});
      const j = await r.json();
      if (!r.ok) { toast(j.error || tr('Import failed')); return; }
      toast(tr('Imported: {0} new, {1} updated', j.created, j.updated) + (j.errors ? ' · ' + trn('{0} not readable', '{0} not readable', j.errors) : '') + (j.kept_newer ? ' · ' + trn('{0} event not overwritten, it is newer here', '{0} events not overwritten, they are newer here', j.kept_newer) : ''), null, 6000);
      done();
    } catch { toast(tr('Import failed')); }
  };
  if (file) return inp.onchange();  // 2.143.0 C2 (#2154): awaitable, several shared files go one after another
  inp.click();
}
// "Calendar & contacts on the phone": the addresses and the steps for iPhone, Android (DAVx5) and Thunderbird
function davGuide() {
  const c = S.caldav || {}, base = c.url || location.origin + '/dav/', host = c.server || location.host, user = c.username || S.me?.username || '';
  const step = (h, items) => `<details class="dgstep"><summary>${h}</summary><ol>${items.map(x => `<li>${x}</li>`).join('')}</ol></details>`;
  const md = modal(`<div class="lhdr"><h3>${ic('phone', 's')} ${tr('Calendar and contacts on the phone')}</h3><span class="spacer"></span><button class="iconbtn" data-dg="close" aria-label="${tr('Close')}">${ic('x')}</button></div>
    <p class="muted">${tr('Calendar and contacts apps sync directly, in both directions.')}</p>
    <div class="shint">${tr('Via CalDAV and CardDAV: events, projects and address books.')}</div>
    <div class="dgaddr"><div><span class="muted">${tr('Server')}</span><code>${esc(host)}</code><button class="iconbtn" data-copy="${esc(host)}" aria-label="${esc(tr('Copy'))}">${ic('copy', 's')}</button></div>
      <div><span class="muted">${tr('Address')}</span><code>${esc(base)}</code><button class="iconbtn" data-copy="${esc(base)}" aria-label="${esc(tr('Copy'))}">${ic('copy', 's')}</button></div>
      <div><span class="muted">${tr('User name')}</span><code>${esc(user)}</code><button class="iconbtn" data-copy="${esc(user)}" aria-label="${esc(tr('Copy'))}">${ic('copy', 's')}</button></div>
      <div><span class="muted">${tr('Password')}</span><span>${setLinkHtml(tr('an app password (Settings > Account > App passwords), never your account password'))}</span><button class="btn sm" data-dg="apppw">${ic('key', 's')} ${tr('App passwords…')}</button></div></div>
    ${step(tr('iPhone and iPad'), [tr('Settings > Apps > Calendar > Calendar Accounts > Add Account > Other > Add CalDAV Account.'),
      tr('Server: {0}, user name and app password as above, then Next.', `<code>${esc(host)}</code>`),
      tr('For the contacts: Settings > Apps > Contacts > Contacts Accounts > Add Account > Other > Add CardDAV Account, with the same three entries.'),
      tr('Your calendars and projects appear in Calendar and Reminders, your address books in Contacts.')])}
    ${step(tr('Android (DAVx⁵)'), [tr('Install DAVx⁵ (Play Store or F-Droid) and open it, then + > Login with URL and user name.'),
      tr('Base URL: {0}, user name and app password as above.', `<code>${esc(base)}</code>`),
      tr('Select the calendars and address books to sync. They appear in the phone’s calendar and contacts apps (tasks with Tasks.org or jtx Board).')])}
    ${step(tr('Thunderbird'), [tr('Calendar: New Calendar > On the network, user name and the address {0}; Thunderbird finds every calendar.', `<code>${esc(base)}</code>`),
      tr('Contacts: Address book > New address book > Add CardDAV address book, the same address and user name.'),
      tr('Enter the app password when Thunderbird asks for it.')])}
    <div class="shint">${tr('Sharing a calendar or an address book with someone puts it into their phone too. Events you are invited to appear in a calendar “Invitations”; answer them there or in the app.')}</div>
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
  if (it.kind === 'evchange') return {time: tr('{0} changed the time of {1}', who, q(d.title || '')), place: tr('{0} changed the place of {1}', who, q(d.title || '')),  // 2.367.2 (#2969)
    cancelled: tr('{0} cancelled {1}', who, q(d.title || '')), occ: tr('{0} cancelled one date of {1}', who, q(d.title || '')), removed: tr('{0} took you off the guest list of {1}', who, q(d.title || ''))}[d.what] || '';
  if (it.kind === 'evshare') return d.role === 'edit' ? tr('{0} shared the calendar {1} with you', who, q(d.name || '')) : tr('{0} shared the calendar {1} with you (read-only)', who, q(d.name || ''));
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
    ${ro ? '' : `<button type="button" class="attadd" data-act="ev-from-task">${ic('plus', 's')}<span>${tr('Schedule as an event')}</span></button>`}
    ${ro || typeof tpo_on !== 'function' || !tpo_on() ? '' : `<button type="button" class="attadd" data-act="tpo-task">${ic('users', 's')}<span>${tr('Find a date')}</span></button>`}</div></div>`;  // 2.98.0 A (#1953)
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
// 2.695.0 (#4619): a long press (phone) / right click (computer) on a row opens what its "…" opens (multisel.js lm_btnMenu)
// calevents.js loads before multisel.js (index.html): bound once every start script ran
domReady(() => { if (typeof lm_btnMenu === 'function') lm_btnMenu('.evcmodal .evcrow, .evcmodal .cvxrow', '[data-evcmenu], [data-cvxmenu]'); });  // the rows of the dialog Calendars
