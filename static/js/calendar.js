/* Kalmido web client: Kanban, the calendar views and external calendar events.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ kanban
function viewKanban() {
  const k = S.route.key;
  const lid = k === 'inbox' ? inbox().id : +k.slice(2);
  const secs = S.sections.filter(s => s.list_id === lid), ro = !canEditList(lid);
  const tasks = sortTasks(openTasks().filter(t => (t.list_id === lid || ml_in(t, lid)) && !t.parent_id && sprKeep(t, k)));  // 2.60.0 (#343): the sprint filter; 2.71.0 B (#1459): + linked tasks
  const cols = [], sc = t => ml_sec(t, lid);  // (a linked task in the column of its link)
  const loose = tasks.filter(t => !sc(t) || !secs.some(s => s.id === sc(t)));
  if (loose.length || !secs.length) cols.push({id: null, name: secs.length ? tr('Unassigned') : tr('Tasks'), tasks: loose});
  for (const s of secs) cols.push({id: s.id, name: s.name, tasks: tasks.filter(t => sc(t) === s.id)});
  return `${listHead(listById(lid))}<div class="kanban">${cols.map(c => `
    <div class="kcol" data-kcol="${c.id ?? ''}">
      <div class="khead" ${c.id ? `data-ksec="${c.id}"` : ''}>${c.id && !ro ? secHandle(c.id) : ''}${esc(c.name)} ${wip_kHead(c)}${spt_kSum(c, lid)}${c.id && !ro ? `<button class="iconbtn" data-act="section-menu" data-id="${c.id}" title="${esc(tr('More') + ': ' + c.name)}" aria-label="${esc(tr('More') + ': ' + c.name)}">${ic('dots', 's')}</button>` : ''}</div>
      <div class="kcards">${c.tasks.map(t => taskRow(t, {compact: true})).join('')}</div>
      ${ro ? '' : `<div class="kadd"><input placeholder="${tr('+ Task')}" aria-label="${esc(tr('New task in {0}', c.name))}" data-kadd="${c.id ?? ''}" enterkeyhint="done"></div>`}
    </div>`).join('')}
    ${ro ? '' : `<div class="knew"><button class="btn sm" data-act="section-new">${ic('plus', 's')} ${tr('Column')}</button></div>`}</div>`;
}

// ------------------------------------------------------------------ calendar
const weekH = () => Math.round(44 * uiZ());  // px per hour in the week / day grid (scales with the font size)
const diffDays = (a, b) => Math.round((pd(b) - pd(a)) / 864e5);
const hm = s => { const [h, m] = s.split(':').map(Number); return h * 60 + m; };
function calByDay(lo, hi) {
  const byDay = new Map();
  const add = (d, t) => { if (!byDay.has(d)) byDay.set(d, []); byDay.get(d).push(t); };
  for (const t of S.tasks.values()) {
    if (!t.due || t.due < lo || t.due > hi || archivedTask(t) || t.context) continue;  // a participant's context parent is not theirs
    if (t.status && !showDoneCal()) continue;
    if (!cvxTaskOn(t)) continue;  // 2.36.1 (#1127): tasks / lists switched off for the calendar views
    add(t.due, t);
  }
  // future repeats of recurring tasks (server-computed RRULE), shown as ghosts. While a newer answer loads, the old
  // items stay visible; one whose task lost its repeat or moved past that day is dropped right away
  for (const o of S.occ.items) {
    const t = S.tasks.get(o.id);
    if (t && t.status === 0 && t.repeat && t.due && o.date > t.due && o.date >= lo && o.date <= hi && !archivedTask(t) && cvxTaskOn(t)) add(o.date, {...t, due: o.date, ghost: true});
  }
  for (const a of byDay.values()) a.sort((a, b) => a.status - b.status || (a.due_time || '99').localeCompare(b.due_time || '99') || b.priority - a.priority);
  ensureOcc(lo, hi);
  return byDay;
}
// 1.5.1: the ghosts depend on the visible range AND on the open recurring tasks: a task that gets or changes its repeat,
// due date or "repeat from", is completed, created, deleted or changed on another device (sync) refetches them
function occSig() {
  let h = 0;
  const ts = [...S.tasks.values()].filter(t => t.repeat && t.status === 0 && t.due).sort((a, b) => a.id - b.id);
  for (const t of ts) { const x = `${t.id}|${t.due}|${t.repeat}|${t.repeat_from || ''}|${t.status};`; for (let i = 0; i < x.length; i++) h = (Math.imul(h, 31) + x.charCodeAt(i)) | 0; }
  return ts.length + ':' + (h >>> 0).toString(36);
}
async function ensureOcc(lo, hi) {
  const key = lo + '|' + hi + '|' + occSig();
  if (S.occ.key === key || S.occ.want === key) return;
  S.occ.want = key;
  try {
    const j = await api('GET', `/api/occurrences?from=${lo}&to=${hi}`);
    if (S.occ.want !== key) return;  // a newer request replaced this one
    S.occ = {key, items: j.items, want: ''};
    if (S.route.mod === 'cal') renderView();
  } catch { if (S.occ.want === key) S.occ.want = ''; }
}
// ------------------------------------------------------------------ external calendars (read-only events)
// Events of the user's calendar subscriptions (Settings > Integrations > Calendars), synced by the server. Fetched
// per visible range (not part of /api/state), kept in S.cal; the last few ranges stay in localStorage for offline
// use. Events never behave like tasks: no drag, no checkbox; a click opens a small popover (cevPop).
const calEvOn = () => !!((S.calendars?.enabled && S.calendars.subs > 0) || (feat('events') && ((S.evcals || []).length || S.cal.items.some(e => e.own) || +String(S.evsig || '').split('|')[0] > 0)));  // 2.21.0 (#659): own events too; 2.102.0 A (#2006): invitations alone
const fmtHM = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
function cevPrep(e) {  // local first / last day (+ Date objects for timed events)
  if (e.all_day) { e.d0 = e.start; e.d1 = e.end > e.start ? addDays(e.end, -1) : e.start; }
  else { e.s = new Date(e.start); e.e = new Date(e.end); if (!(e.e >= e.s)) e.e = e.s; e.d0 = ds(e.s); e.d1 = ds(new Date(Math.max(+e.s, +e.e - 1))); }
  return e;
}
function cevApply(j, key) { S.cal = {key, loading: '', items: (j.events || []).map(cevPrep), subs: j.subs || {}, evcals: j.evcals || {}}; }
function cevCached(lo, hi) {
  const c = LS.get('calev', {});
  if (c[lo + '|' + hi]) return c[lo + '|' + hi];
  const k = Object.keys(c).find(x => { const [a, b] = x.split('|'); return a <= lo && b >= hi; });
  return k ? c[k] : null;
}
async function ensureCalEv(lo, hi) {
  if (!calEvOn() && !feat('events')) { if (S.cal.items.length) S.cal = {key: '', loading: '', items: [], subs: {}, evcals: {}}; return; }
  const key = `${lo}|${hi}`;
  if (S.cal.key === key || S.cal.loading === key) return;
  S.cal.loading = key;
  try {
    const j = await api('GET', `/api/calendars/events?from=${addDays(lo, -1)}&to=${addDays(hi, 1)}`);
    if (S.cal.loading !== key) return;
    cevApply(j, key);
    const c = LS.get('calev', {});
    c[lo + '|' + hi] = {at: Date.now(), events: j.events, subs: j.subs, evcals: j.evcals};
    Object.keys(c).sort((a, b) => c[b].at - c[a].at).slice(6).forEach(k => delete c[k]);
    LS.set('calev', c);
  } catch {
    const hit = cevCached(lo, hi);  // offline: the last copy of this range
    if (!hit || S.cal.loading !== key) { S.cal.loading = ''; return; }
    cevApply(hit, key);
  }
  if (S.route.mod === 'cal' || (S.route.mod === 'tasks' && S.route.key === 'today')) renderView();
}
function calInvalidate() { S.cal.key = ''; S.cal.loading = ''; }
// 2.30.0 (#1036): an own event of a calendar outside the shown workspace is left out (subscriptions and invitations stay)
const cevWs = e => !e.own || e.cal == null || wsObjIn(evCal(e.cal));
const cevOn = d => S.cal.items.filter(e => e.d0 <= d && e.d1 >= d && cevWs(e));
const cevSort = (a, b) => (b.all_day - a.all_day) || a.start.localeCompare(b.start) || a.title.localeCompare(b.title);
const cevColor = e => e.booking ? 'var(--accent)' : e.own ? evCalColor(e) : cssColor(S.cal.subs[e.sub]?.color) || '#94a3b8';  // 2.50.0 (#1194): bookings
const cevCal = e => e.booking ? tr('Disposition') : e.own ? evCalName(e) : S.cal.subs[e.sub]?.name || tr('Calendar');
const cevTitle = e => e.title || tr('(no title)');
// a timed event on day d is a block in the week grid, except on the middle days of a multi-day event (all-day row)
const cevTimed = (e, d) => !e.all_day && !(e.d0 < d && e.d1 > d);
function cevMin(e, d) {
  const s = e.d0 === d ? e.s.getHours() * 60 + e.s.getMinutes() : 0;
  const en = e.d1 === d ? e.e.getHours() * 60 + e.e.getMinutes() : 1440;
  return {s, e: Math.max(en || 1440, s + 15)};
}
function cevTime(e, d) {
  if (!cevTimed(e, d)) return tr('all day');
  return `${e.d0 === d ? fmtHM(e.s) : '…'}–${e.d1 === d ? fmtHM(e.e) : '…'}`;
}
// 2.52.0 (#1016): cgok = may be dragged into other days (caldrag.js)
const cevChip = (e, d) => `<div class="cev${cevTimed(e, d) ? '' : ' allday'}${ap_draftCls(e)}${cg_canDrag(e) ? ' cgok' : ''}" data-cev="${e.id}" style="--cc:${cevColor(e)}" title="${esc(cevTitle(e))}">${cevTimed(e, d) && e.d0 === d ? `<span class="muted">${fmtHM(e.s)}</span> ` : ''}${esc(cevTitle(e))}</div>`;
const cevRow = (e, d) => `<div class="cevrow${ap_draftCls(e)}" data-cev="${e.id}" style="--cc:${cevColor(e)}" role="button" tabindex="0"><i class="cevdot"></i><span class="cevt">${cevTime(e, d)}</span><span class="cevn">${esc(cevTitle(e))}</span>${e.location ? `<span class="cevl">${esc(e.location)}</span>` : ''}<span class="cevc">${esc(cevCal(e))}</span></div>`;
function cevTodayBlock() {  // "Events today" at the top of Today (setting cal_today)
  if (!feat('cal') || !calEvOn() || S.settings.cal_today === '0') return '';  // Calendar module off: gone here too
  const t0 = today();
  ensureCalEv(t0, t0);
  const all = cevOn(t0), evs = all.filter(cvxTodayOn).sort(cevSort);  // 2.36.1 (#1127): calendars switched off for Today
  if (!all.length) return '';
  const closed = S.collapsed.has('cev-today');
  // the head's "…" menu switches single calendars off / on here (the block stays while a calendar is switched off)
  const mn = `<button class="iconbtn gact cvxtm" data-act="cvx-today-menu" aria-haspopup="menu" title="${esc(tr('Calendars on Today'))}" aria-label="${esc(tr('Calendars on Today'))}">${ic('dots', 's')}</button>`;
  return `<div class="group cevtoday"><div class="ghead ${closed ? 'closed' : ''}" data-act="collapse" data-key="cev-today">${ic('chev', 's')}${tr('Events today')} <span class="c">${evs.length}</span>${mn}</div>${closed ? '' : `<div class="cevlist">${evs.map(e => cevRow(e, t0)).join('') || `<div class="muted mhint">${tr('All calendars are switched off here. Switch one on in the menu.')}</div>`}</div>`}</div>`;
}
function cevLinkify(s) {  // escaped text; only http(s) URLs become links
  const re = /https?:\/\/[^\s<>"'`\\]+/gi;
  let out = '', i = 0, m;
  while ((m = re.exec(s))) {
    const u = m[0].replace(/[.,;:!?)\]]+$/, '');
    out += esc(s.slice(i, m.index));
    const safe = mdSafeUrl(u);
    out += safe && /^https?:/i.test(safe) ? mdLink(safe, esc(u)) : esc(u);
    i = m.index + u.length; re.lastIndex = i;
  }
  return out + esc(s.slice(i));
}
function cevWhen(e) {
  if (e.all_day) return e.d0 === e.d1 ? fmtDayAbs(e.d0) : `${fmtDayAbs(e.d0)} – ${fmtDayAbs(e.d1)}`;
  return e.d0 === e.d1 ? `${fmtDayAbs(e.d0)}, ${fmtHM(e.s)}–${fmtHM(e.e)}` : `${fmtDayAbs(e.d0)} ${fmtHM(e.s)} – ${fmtDayAbs(e.d1)} ${fmtHM(e.e)}`;
}
function cevPop(anchor, id) {
  const e = S.cal.items.find(x => x.id === id); if (!e) return;
  if (e.own) { evPop(anchor, e); return; }  // 2.21.0 (#659): an own event (calevents.js)
  if (e.dvw_write) { dvw_pop(anchor, e); return; }  // 2.52.0 (#1128): a writable CalDAV subscription (davwrite.js)
  const desc = (e.description || '').slice(0, 2000);
  const p = openPop(anchor, `<div class="cevpop" style="--cc:${cevColor(e)}">
    <div class="cevh"><i class="cevdot"></i><b>${esc(cevTitle(e))}</b></div>
    <div class="cevm">${ic('clock', 's')}<span>${esc(cevWhen(e))}</span></div>
    ${e.location ? `<div class="cevm">${ic('mappin', 's')}<span>${esc(e.location)}</span></div>` : ''}
    <div class="cevm">${ic('cal', 's')}<span>${esc(cevCal(e))} · ${tr('read-only')}</span></div>
    ${desc ? `<div class="cevdesc">${cevLinkify(desc)}${e.description.length > 2000 ? '…' : ''}</div>` : ''}
    <div class="cevact"><button class="btn sm pri" data-cevtask>${ic('plus', 's')} ${tr('Create task from event')}</button></div></div>`);
  p.onclick = ev => { if (ev.target.closest('[data-cevtask]')) { closePop(); cevToTask(e); } };
}
// the task gets the event's title and start (date + time + duration), in the inbox; the panel opens to edit it
async function cevToTask(e) {
  const inb = inbox(); if (!inb) return;
  const body = {title: cevTitle(e).slice(0, 500), list_id: inb.id, due: e.d0,
    content: [e.location ? tr('Location: {0}', e.location) : '', tr('From calendar: {0}', cevCal(e))].filter(Boolean).join('\n')};
  if (!e.all_day) {
    body.due_time = fmtHM(e.s);
    const m = Math.round((e.e - e.s) / 60000);
    if (m >= 5) body.duration = Math.min(m, 7 * 1440);
  }
  try { const t = await createTask(body); toast(tr('Task created from the event')); openDetail(t.id); } catch { /* api() showed it */ }
}
function tlCalRows(start, end, DW) {  // calendar timeline: one row per calendar (overlaps in extra lanes, at most 6)
  if (!calEvOn()) return '';
  ensureCalEv(start, end);
  // 2.36.1 (#1127): own calendars get their own rows too (before: every own event sat in one nameless row)
  const byCal = new Map();
  for (const e of S.cal.items) if (e.d1 >= start && e.d0 <= end && cevWs(e)) { const k = cvxKey(e); if (!byCal.has(k)) byCal.set(k, []); byCal.get(k).push(e); }
  if (!byCal.size) return '';
  const days = diffDays(start, end) + 1;
  let h = `<div class="tl-row tl-grp"><div class="tl-name">${tr('Calendars')}</div><div class="tl-track"></div></div>`;
  for (const [key, list] of byCal) {
    // all-day / multi-day events claim the first lanes, the (short) timed ones fill the rest; an event that overlaps
    // another one of its lane goes to the next lane (#1126: never two titles over each other)
    list.sort((a, b) => (b.all_day - a.all_day) || a.d0.localeCompare(b.d0) || cevSort(a, b));
    const lanes = [];
    const placed = list.map(e => {
      const s = e.d0 < start ? start : e.d0, en = e.d1 > end ? end : e.d1;
      // the first lane with no event on these days (not only after its last one: a short event before the others fits too)
      let l = lanes.findIndex(x => !x.some(([a, b]) => s <= b && en >= a));
      if (l < 0) { l = lanes.length; lanes.push([]); }
      lanes[l].push([s, en]);
      return {e, s, en, l};
    });
    const cc = cevColor(list[0]), name = cevCal(list[0]), inv = list[0].own && list[0].cal == null;  // inv: invitations (no calendar of mine)
    for (let l = 0; l < Math.min(lanes.length, 6); l++) {
      const inLane = placed.filter(p => p.l === l).sort((a, b) => a.s.localeCompare(b.s));
      // #1127: a tap on the name hides the calendar (toast with Undo), "…" offers "Only this one" / "Show all"
      const nm = l ? '' : inv ? `<i class="cevdot"></i><span class="tln">${esc(name)}</span>`
        : `<button type="button" class="cvxtln" data-act="cvx-tlhide" data-key="${key}" data-name="${esc(name)}" title="${esc(tr('Hide this calendar'))}"><i class="cevdot"></i><span class="tln">${esc(name)}</span></button><button type="button" class="iconbtn cvxtlm" data-act="cvx-tlmenu" data-key="${key}" data-name="${esc(name)}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', name))}" title="${esc(tr('More'))}">${ic('dots', 's')}</button>`;
      h += `<div class="tl-row tl-cal" style="--cc:${cc}"><div class="tl-name">${nm}</div><div class="tl-track">${inLane.map((p, i) => {
        // #1126: the bar is as wide as the event; its title stays inside the element and may only run on over the free
        // track up to the next bar of the same lane (cut with "…" there), never outside the row
        const x = diffDays(start, p.s) * DW, w = (diffDays(p.s, p.en) + 1) * DW;
        const nx = inLane[i + 1] ? diffDays(start, inLane[i + 1].s) * DW : days * DW;
        const free = Math.max(w, nx - x);
        return `<div class="tl-cev${ap_draftCls(p.e)}" data-cev="${p.e.id}" style="left:${x + 2}px;width:${free - 4}px;--bw:${w - 4}px" title="${esc(cevTitle(p.e))}"><i class="cvxbar"></i><span>${esc(cevTitle(p.e))}</span></div>`;
      }).join('')}</div></div>`;
    }
  }
  return h;
}

// 2.65.0 (#1823): Settings > Integrations > Calendars, viewCal / viewWeek / layoutDay: calview.js (module "calendar")
// direct request without the api() toast: the dialogs show the error themselves
async function calReq(method, url, body) {
  try { return await rawFetch(method, url, body); }
  catch (e) { throw new Error(e instanceof Offline ? tr('Offline: only works again with a connection') : e.message); }
}
function calBar(title, done = true, extra = '') {
  // 1.8.1: completed tasks in the calendar, per user (show_done_views entry "cal", shown unless hidden here)
  const on = showDoneCal(), dn = done ? `<button class="btn sm chip ${on ? 'on' : ''}" data-act="cal-done" aria-pressed="${on}" aria-label="${esc(tr('Completed'))}" title="${esc(on ? tr('Hide completed') : tr('Show completed'))}">${ic('eye', 's')}<span class="cdl">${tr('Completed')}</span></button>` : '';
  const modes = [['month', N_('Month')], ['week', N_('Week')], ['day', N_('Day')], ...(feat('events') ? [['agenda', N_('Agenda')]] : []), ...(feat('timeline') ? [['timeline', N_('Timeline')]] : [])].map(([k, n]) => [k, tr(n)]);
  // 2.21.0 (#659): "+ Event" and the calendars (own, shared: show, share, import, the phone)
  // 2.36.1 (#1127): the "Calendars" window (own calendars, subscriptions, tasks) opens here too, also without own events
  const evb = (feat('events') ? `<button class="btn sm pri evnew" data-act="ev-new" title="${esc(tr('New event'))}" aria-label="${esc(tr('New event'))}">${ic('plus', 's')}<span class="cdl">${tr('Event')}</span></button>` : '')
    + (feat('events') || S.calendars?.enabled ? `<button class="btn sm" data-act="ev-cals" title="${esc(tr('Calendars'))}" aria-label="${esc(tr('Calendars'))}">${ic('cal', 's')}<span class="cdl">${tr('Calendars')}</span></button>` : '');
  return `<div class="calbar"><h2>${title}</h2><div class="seg">${modes.map(([k, n]) => `<button class="${S.calMode === k ? 'on' : ''}" data-act="cal-mode" data-k="${k}">${n}</button>`).join('')}</div>${dn}${evb}${extra}
    <div class="calnav"><button class="iconbtn" data-act="cal-prev" title="${esc(tr('Previous period'))}" aria-label="${esc(tr('Previous period'))}">${ic('left')}</button><button class="btn sm" data-act="cal-today">${tr('Today')}</button><button class="iconbtn" data-act="cal-next" title="${esc(tr('Next period'))}" aria-label="${esc(tr('Next period'))}">${ic('right')}</button></div></div>`;
}
function isoWeek(s) { const d = pd(s); d.setDate(d.getDate() + 3 - (d.getDay() + 6) % 7); const w1 = new Date(d.getFullYear(), 0, 4); return 1 + Math.round(((d - w1) / 864e5 - 3 + (w1.getDay() + 6) % 7) / 7); }
const cvxKey = e => e.own ? `e:${e.cal}` : `s:${e.sub}`;
function cvxList(k) { try { const a = JSON.parse(S.settings?.[k] || '[]'); return Array.isArray(a) ? a : []; } catch { return []; } }
const cvxTodayOn = e => (e.own && e.cal == null) || !cvxList('today_cals_hidden').includes(cvxKey(e));
const cvxTaskOn = t => S.settings?.cal_tasks !== '0' && !cvxList('cal_lists_hidden').includes(t.list_id);
// stores one of the json lists (the local copy first, so the views redraw at once)
function cvxSave(k, arr) {
  S.settings[k] = typeof arr === 'string' ? arr : JSON.stringify(arr);
  return api('PATCH', '/api/settings', {[k]: arr}).catch(() => { /* api() showed it; the local value stays until the next load */ });
}
const cvxOff = (k, key, off) => cvxSave(k, [...cvxList(k).filter(x => x !== key), ...(off ? [key] : [])]);  // off = listed
// every calendar I have: own ones from the state, subscriptions from GET /api/calendars (cached in S.cvxSubs)
async function cvxCals(fresh) {
  if (S.calendars?.enabled && (fresh || !S.cvxSubs)) { try { S.cvxSubs = (await api('GET', '/api/calendars')).subs || []; } catch { S.cvxSubs = S.cvxSubs || null; } }
  return cvxVisibleCals(true);
}
// sync: own calendars + subscriptions (from the cache, else the last events answer = the visible ones); all = hidden ones too
function cvxVisibleCals(all) {
  const out = (S.evcals || []).filter(c => all || !c.hidden).map(c => ({key: `e:${c.id}`, id: c.id, name: c.name, color: cssColor(c.color) || 'var(--accent)', on: !c.hidden, own: true, c}));
  if (!S.calendars?.enabled && !S.cvxSubs) return out;
  const subs = S.cvxSubs ? S.cvxSubs.map(x => [x.id, x, !!x.visible]) : Object.entries(S.cal.subs || {}).map(([id, x]) => [+id, x, true]);
  for (const [id, x, on] of subs) if (all || on) out.push({key: `s:${id}`, id, name: x.name || tr('Calendar'), color: cssColor(x.color) || '#94a3b8', on, own: false, c: x});
  return out;
}
// "Show in my calendar" for one calendar; draw = redraw the views (false while several are switched in a row)
async function cvxShow(key, on, draw = true) {
  const [k, id] = key.split(':'), n = +id;
  try {
    if (k === 'e') { await api('PATCH', `/api/evcals/${n}`, {hidden: !on}); const c = evCal(n); if (c) c.hidden = !on; }
    else {
      await api('PATCH', `/api/calendars/${n}`, {visible: on});
      const x = (S.cvxSubs || []).find(s => s.id === n); if (x) x.visible = on;
      const cnt = S.cvxSubs ? S.cvxSubs.filter(s => s.visible).length : Math.max(0, (S.calendars?.subs || 0) + (on ? 1 : -1));
      S.calendars = {...(S.calendars || {}), enabled: true, subs: cnt};
    }
  } catch { return false; }
  if (draw) cvxRedraw();
  return true;
}
function cvxRedraw() { calInvalidate(); renderView(); }  // the events are fetched again (hidden calendars send none)
async function cvxTlHide(key, name) {  // timeline: a tap on the name hides the calendar, the toast takes it back
  if (!await cvxShow(key, false)) return;
  toast(tr('Calendar “{0}” hidden', name), () => cvxShow(key, true));
}
async function cvxOnly(key) {  // "Only this one": every other calendar off (the toast shows all again)
  const cs = await cvxCals();
  for (const c of cs) if (c.on !== (c.key === key)) await cvxShow(c.key, c.key === key, false);
  cvxRedraw();
  toast(tr('Only this calendar is shown'), cvxAll, null, tr('Show all'));
}
async function cvxAll() {
  const cs = await cvxCals();
  for (const c of cs) if (!c.on) await cvxShow(c.key, true, false);
  cvxRedraw();
}
function cvxTlMenu(anchor, key, name) {
  menu(anchor, [{label: tr('Hide this calendar'), icon: 'eyeoff', fn: () => cvxTlHide(key, name)},
    {label: tr('Only this calendar'), icon: 'eye', fn: () => cvxOnly(key)},
    {label: tr('Show all calendars'), icon: 'all', fn: cvxAll}, '-',
    {label: tr('Calendars…'), icon: 'cal', fn: evCalsModal}]);
}
// Today: the "…" of "Events today" switches single calendars off / on in this block only
function cvxTodayMenu(anchor) {
  const cs = cvxVisibleCals(), off = cvxList('today_cals_hidden');
  menu(anchor, [...cs.map(c => ({label: c.name, on: !off.includes(c.key), fn: async () => { await cvxOff('today_cals_hidden', c.key, !off.includes(c.key)); renderView(); }})),
    cs.length ? '-' : null, off.length ? {label: tr('Show all calendars'), icon: 'all', fn: async () => { await cvxSave('today_cals_hidden', []); renderView(); }} : null,
    {label: tr('Calendars…'), icon: 'cal', fn: evCalsModal}].filter(Boolean));
}
// the day plan dialog (#956): a fold-out "Calendars" line, each switch = counts as busy when planning (also for an agent)
function cvxPlanRow(open) {
  const cs = cvxVisibleCals(); if (!cs.length) return '';
  const off = cvxList('plan_cals_off'), n = cs.filter(c => !off.includes(c.key)).length;
  return `<details class="cvxdp" ${open ? 'open' : ''}><summary>${ic('cal', 's')} ${tr('Calendars')} <span class="muted">${esc(tr('{0} of {1} considered', n, cs.length))}</span></summary>
    <div class="cvxdpl">${cs.map(c => `<label class="cvxdpr" style="--cc:${cssColor(c.color)}"><input type="checkbox" data-cvxplan="${c.key}" ${off.includes(c.key) ? '' : 'checked'}><i class="cevdot"></i><span>${esc(c.name)}</span><small class="muted">${tr('consider when planning')}</small></label>`).join('')}</div></details>`;
}
