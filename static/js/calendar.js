/* Kalmido web client: Kanban, the calendar views and external calendar events.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ kanban
function viewKanban() {
  const k = S.route.key;
  const lid = k === 'inbox' ? inbox().id : +k.slice(2);
  const secs = S.sections.filter(s => s.list_id === lid), ro = !canEditList(lid);
  const tasks = sortTasks(openTasks().filter(t => t.list_id === lid && !t.parent_id));
  const cols = [];
  const loose = tasks.filter(t => !t.section_id || !secs.some(s => s.id === t.section_id));
  if (loose.length || !secs.length) cols.push({id: null, name: secs.length ? tr('Unassigned') : tr('Tasks'), tasks: loose});
  for (const s of secs) cols.push({id: s.id, name: s.name, tasks: tasks.filter(t => t.section_id === s.id)});
  return `${listHead(listById(lid))}<div class="kanban">${cols.map(c => `
    <div class="kcol" data-kcol="${c.id ?? ''}">
      <div class="khead" ${c.id ? `data-ksec="${c.id}"` : ''}>${c.id && !ro ? secHandle(c.id) : ''}${esc(c.name)} <span class="c">${c.tasks.length}</span>${c.id && !ro ? `<button class="iconbtn" data-act="section-menu" data-id="${c.id}" title="${esc(tr('More') + ': ' + c.name)}" aria-label="${esc(tr('More') + ': ' + c.name)}">${ic('dots', 's')}</button>` : ''}</div>
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
const calEvOn = () => !!((S.calendars?.enabled && S.calendars.subs > 0) || (feat('events') && ((S.evcals || []).length || S.cal.items.some(e => e.own))));  // 2.21.0 (#659): own events too
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
const cevColor = e => e.own ? evCalColor(e) : cssColor(S.cal.subs[e.sub]?.color) || '#94a3b8';
const cevCal = e => e.own ? evCalName(e) : S.cal.subs[e.sub]?.name || tr('Calendar');
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
const cevChip = (e, d) => `<div class="cev${cevTimed(e, d) ? '' : ' allday'}" data-cev="${e.id}" style="--cc:${cevColor(e)}" title="${esc(cevTitle(e))}">${cevTimed(e, d) && e.d0 === d ? `<span class="muted">${fmtHM(e.s)}</span> ` : ''}${esc(cevTitle(e))}</div>`;
const cevRow = (e, d) => `<div class="cevrow" data-cev="${e.id}" style="--cc:${cevColor(e)}" role="button" tabindex="0"><i class="cevdot"></i><span class="cevt">${cevTime(e, d)}</span><span class="cevn">${esc(cevTitle(e))}</span>${e.location ? `<span class="cevl">${esc(e.location)}</span>` : ''}<span class="cevc">${esc(cevCal(e))}</span></div>`;
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
        return `<div class="tl-cev" data-cev="${p.e.id}" style="left:${x + 2}px;width:${free - 4}px;--bw:${w - 4}px" title="${esc(cevTitle(p.e))}"><i class="cvxbar"></i><span>${esc(cevTitle(p.e))}</span></div>`;
      }).join('')}</div></div>`;
    }
  }
  return h;
}

// Settings > Integrations > Calendars (own requests, applied at once) + the admin allow-list (Settings > Users)
function calsHtml(chk, hint) {
  if (!S.calendars?.enabled) return `<h4 id="s-cals-h">${tr('Calendars')}</h4>${hintK(tr('Calendar subscriptions are turned off on this server'))}`;
  return `<h4 id="s-cals-h">${tr('Calendars')}</h4>
    ${hint(tr('Show events from Google Calendar, iCloud, Outlook or any CalDAV server next to your tasks: in the calendar, the timeline and on Today. Read-only, and only you see them.'))}
    <div class="members" id="s-cals"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="row"><button class="btn sm pri" data-m="cal-add">${ic('plus', 's')} ${tr('Add calendar')}</button></div>
    ${feat('cal') ? `<div class="row"><label>${tr('Today')}</label>${chk('s-caltoday', S.settings.cal_today !== '0', tr('show today’s events at the top'))}</div>` : ''}
    <details class="shelp sdet"><summary>${tr('Where do I find the link?')}</summary><ul class="slist">
      <li>${tr('<b>Google Calendar:</b> on a computer, calendar.google.com > Settings > your calendar > Integrate calendar > “Secret address in iCal format”.')}</li>
      <li>${tr('<b>iCloud:</b> in the Calendar app, share the calendar as a public calendar and copy the link (webcal://…). Or add your whole account via CalDAV: server caldav.icloud.com, your Apple ID and an app-specific password (account.apple.com).')}</li>
      <li>${tr('<b>Outlook / Microsoft 365:</b> Settings > Calendar > Shared calendars > Publish a calendar > copy the ICS link.')}</li>
      <li>${tr('<b>Nextcloud, Radicale, Baïkal, Fastmail, mailbox.org …:</b> CalDAV account with the server address, your username and password (an app password where possible).')}</li>
      <li>${tr('Servers in your own network (for example 10.x.x.x or a VPN address) are blocked for safety until an admin allows the host under Settings > Administration > Advanced.')}</li></ul></details>`;
}
function calStatus(x) {
  if (x.status === 'error') return `<span class="calerr" role="alert">${esc(x.error_text || tr('Error'))}</span>` + (x.synced_at ? ' · ' + esc(tr('last synced {0}', relTime(x.synced_at))) : '');
  if (!x.synced_at) return esc(tr('Not synced yet'));
  return esc(tr('synced {0}', relTime(x.synced_at))) + ' · ' + esc(trn('{0} event', '{0} events', x.events)) + (x.truncated ? ' ' + esc(tr('(limit reached)')) : '');
}
async function calsDraw(md, j) {
  const box = $('#s-cals', md); if (!box) return;
  if (!j) { try { j = await api('GET', '/api/calendars'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; } }
  box._j = j;
  S.calendars = {...(S.calendars || {}), enabled: j.enabled, subs: j.subs.filter(x => x.visible).length};
  calInvalidate();
  box.innerHTML = j.subs.length ? j.subs.map(x => `<div class="calsub ${x.visible ? '' : 'off'}" data-cal="${x.id}" style="--cc:${cssColor(x.color) || '#94a3b8'}">
      <button class="cswatch" data-calact="color" title="${tr('Color')}" aria-label="${tr('Color')}"></button>
      <div class="calsub-main"><b>${esc(x.name)}</b><small class="muted">${esc(x.kind === 'caldav' ? `CalDAV · ${x.username}` : x.url_hint)} · ${calStatus(x)}</small></div>
      <label class="calvis" title="${tr('Show')}"><input type="checkbox" data-calact="vis" ${x.visible ? 'checked' : ''} aria-label="${tr('Show')}"></label>
      <button class="iconbtn" data-calact="refresh" title="${tr('Refresh now')}" aria-label="${tr('Refresh now')}">${ic('repeat', 's')}</button>
      <button class="iconbtn" data-calact="edit" title="${tr('Edit')}" aria-label="${tr('Edit')}">${ic('edit', 's')}</button>
      <button class="iconbtn" data-calact="del" title="${tr('Remove')}" aria-label="${tr('Remove')}">${ic('trash', 's')}</button></div>`).join('')
    : `<div class="muted mhint">${tr('No calendars yet.')}</div>`;
}
async function calPatch(md, id, body) {
  try { await api('PATCH', `/api/calendars/${id}`, body); } catch { await calsDraw(md); return false; }
  await calsDraw(md); return true;
}
function calColorPop(anchor, colors, cur, fn) {
  const p = openPop(anchor, `<div class="cpal">${colors.map(c => `<button data-c="${c}" style="--cc:${c}" class="${c === cur ? 'on' : ''}" aria-label="${c}"></button>`).join('')}</div>`);
  p.onclick = ev => { const b = ev.target.closest('[data-c]'); if (b) { closePop(); fn(b.dataset.c); } };
}
function calsWire(md) {
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-calact], [data-m="cal-add"]'); if (!b) return;
    if (b.dataset.m === 'cal-add') { calAddModal(() => calsDraw(md)); return; }
    const row = b.closest('[data-cal]'); if (!row) return;
    const box = $('#s-cals', md), id = +row.dataset.cal, x = (box._j?.subs || []).find(s => s.id === id); if (!x) return;
    const act = b.dataset.calact;
    if (act === 'color') calColorPop(b, box._j.colors, x.color, c => calPatch(md, id, {color: c}));
    if (act === 'refresh') {
      b.disabled = true;
      try { const r = await api('POST', `/api/calendars/${id}/refresh`); toast(r.status === 'ok' ? tr('Calendar updated') : r.error_text); } catch { /* api() showed it */ }
      await calsDraw(md);
    }
    if (act === 'edit') calEditModal(x, box._j.colors, () => calsDraw(md));
    if (act === 'del') {
      if (!await askConfirm(tr('Remove the calendar “{0}”?', x.name), tr('Its events disappear from Kalmido; the calendar itself does not change.'), {ok: tr('Remove'), danger: true})) return;
      try { await calsDraw(md, await api('DELETE', `/api/calendars/${id}`)); toast(tr('Calendar removed')); } catch { /* api() showed it */ }
    }
  });
  md.addEventListener('change', e => { const i = e.target.closest('[data-calact="vis"]'); if (i) calPatch(md, +i.closest('[data-cal]').dataset.cal, {visible: i.checked}); });
  // allowed internal hosts (admins): saved when leaving the field, one history step
  md.addEventListener('change', async e => {
    if (e.target.id !== 's-calhosts') return;
    const from = S.about?.cal_allow_hosts || '', to = e.target.value;
    if (from.trim() === to.trim()) return;
    const put = async v => { const j = await api('PATCH', '/api/admin/settings', {cal_allow_hosts: v}); S.about = {...S.about, ...j}; const f = $('#s-calhosts'); if (f && f !== document.activeElement) f.value = j.cal_allow_hosts || ''; return {skipped: []}; };
    try { await put(to); } catch { return; }
    setSaved(histAdd({label: tr('Changed setting: {0}', tr('Allowed internal hosts')), sett: true, undo: () => put(from), redo: () => put(to)}));
  });
}
// direct request without the api() toast: the dialogs show the error themselves
async function calReq(method, url, body) {
  try { return await rawFetch(method, url, body); }
  catch (e) { throw new Error(e instanceof Offline ? tr('Offline: only works again with a connection') : e.message); }
}
function calAddModal(done) {
  const md = modal(`<h3>${tr('Add calendar')}</h3>
    <div class="row"><div class="seg" id="ca-kind"><button class="on" data-k="ics">${tr('Link (ICS / iCal)')}</button><button data-k="caldav">${tr('CalDAV account')}</button></div></div>
    <div id="ca-ics"><div class="row"><label for="ca-url">${tr('Link')}</label><input id="ca-url" type="url" placeholder="https://… / webcal://…" autocomplete="off" autocapitalize="off" spellcheck="false"></div>
      <div class="row"><label for="ca-name">${tr('Name')}</label><input id="ca-name" maxlength="100" placeholder="${tr('from the calendar')}"></div></div>
    <div id="ca-dav" hidden><div class="row"><label for="ca-srv">${tr('Server')}</label><input id="ca-srv" type="url" placeholder="https://caldav.example.com" autocomplete="off" autocapitalize="off" spellcheck="false"></div>
      <div class="row"><label for="ca-user">${tr('Username')}</label><input id="ca-user" autocomplete="off" autocapitalize="off"></div>
      <div class="row"><label for="ca-pw">${tr('Password')}</label><input id="ca-pw" type="password" autocomplete="new-password" placeholder="${tr('an app password where possible')}"></div>
      <div id="ca-cals" class="featgrid"></div></div>
    <div class="row"><label for="ca-int">${tr('Refresh')}</label><select id="ca-int"><option value="15">${tr('every 15 minutes')}</option><option value="60">${tr('every hour')}</option></select></div>
    <div class="shint">${tr('The link and the password are stored encrypted and never shown again. Kalmido only reads the calendar.')}</div>
    <div class="calerr" role="alert" id="ca-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Add')}</button></div>`);
  let kind = 'ics', found = null;
  const errBox = $('#ca-err', md), ok = $('[data-m="ok"]', md);
  const showErr = m => { errBox.textContent = m || ''; errBox.hidden = !m; };
  const setKind = k => {
    kind = k; found = null; showErr('');
    $$('#ca-kind button', md).forEach(b => b.classList.toggle('on', b.dataset.k === k));
    $('#ca-ics', md).hidden = k !== 'ics'; $('#ca-dav', md).hidden = k !== 'caldav'; $('#ca-cals', md).innerHTML = '';
    ok.textContent = k === 'caldav' ? tr('Find calendars') : tr('Add');
  };
  md.addEventListener('input', e => { if (kind === 'caldav' && found && ['ca-srv', 'ca-user', 'ca-pw'].includes(e.target.id)) { found = null; $('#ca-cals', md).innerHTML = ''; ok.textContent = tr('Find calendars'); } });
  md.addEventListener('click', async e => {
    const kb = e.target.closest('#ca-kind [data-k]'); if (kb) { setKind(kb.dataset.k); return; }
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m !== 'ok') return;
    showErr(''); b.disabled = true;
    const interval = +$('#ca-int', md).value;
    try {
      if (kind === 'ics') {
        const url = $('#ca-url', md).value.trim();
        if (!url) { showErr(tr('Paste the calendar link first')); return; }
        const j = await calReq('POST', '/api/calendars', {kind, url, name: $('#ca-name', md).value.trim(), interval});
        md.remove(); toast(tr('Calendar added')); done && done(j); return;
      }
      const auth = {url: $('#ca-srv', md).value.trim(), username: $('#ca-user', md).value.trim(), password: $('#ca-pw', md).value};
      if (!found) {
        found = (await calReq('POST', '/api/calendars/discover', auth)).calendars;
        $('#ca-cals', md).innerHTML = `<div class="shint keep">${tr('Which calendars should be shown?')}</div>` + found.map((c, i) => `<label class="wide"><input type="checkbox" data-ci="${i}" checked><span><i class="cevdot" style="--cc:${cssColor(c.color) || '#94a3b8'}"></i> ${esc(c.name)}</span></label>`).join('');
        b.textContent = tr('Add'); return;
      }
      const cals = found.filter((_, i) => $(`[data-ci="${i}"]`, md)?.checked);
      if (!cals.length) { showErr(tr('Choose at least one calendar')); return; }
      const j = await calReq('POST', '/api/calendars', {kind, ...auth, interval, calendars: cals});
      md.remove();
      toast(j.errors?.length ? tr('{0} added, {1} failed: {2}', j.created.length, j.errors.length, j.errors[0].error) : trn('{0} calendar added', '{0} calendars added', j.created.length));
      done && done(j);
    } catch (x) { showErr(x.message); } finally { b.disabled = false; }
  });
  if (!isTouch()) setTimeout(() => $('#ca-url', md)?.focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
function calEditModal(x, colors, done) {
  let color = x.color;
  const md = modal(`<h3>${tr('Edit calendar')}</h3>
    <div class="row"><label for="ce-name">${tr('Name')}</label><input id="ce-name" maxlength="100" value="${esc(x.name)}"></div>
    <div class="row"><label>${tr('Color')}</label><div class="cpal inline">${colors.map(c => `<button data-c="${c}" style="--cc:${c}" class="${c === color ? 'on' : ''}" aria-label="${c}"></button>`).join('')}</div></div>
    <div class="row"><label for="ce-int">${tr('Refresh')}</label><select id="ce-int"><option value="15">${tr('every 15 minutes')}</option><option value="60" ${x.interval === 60 ? 'selected' : ''}>${tr('every hour')}</option></select></div>
    ${x.kind === 'ics' ? `<div class="row"><label for="ce-url">${tr('Link')}</label><input id="ce-url" type="url" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${tr('saved ({0}), empty = keep', x.url_hint)}"></div>`
    : `<div class="row"><label for="ce-user">${tr('Username')}</label><input id="ce-user" autocomplete="off" autocapitalize="off" value="${esc(x.username)}"></div>
      <div class="row"><label for="ce-pw">${tr('Password')}</label><input id="ce-pw" type="password" autocomplete="new-password" placeholder="${x.password_saved ? tr('saved, empty = keep') : ''}"></div>`}
    <div class="calerr" role="alert" id="ce-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async e => {
    const cb = e.target.closest('[data-c]');
    if (cb) { color = cb.dataset.c; $$('.cpal [data-c]', md).forEach(b => b.classList.toggle('on', b === cb)); return; }
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const body = {name: $('#ce-name', md).value.trim(), color, interval: +$('#ce-int', md).value};
    if (x.kind === 'ics' && $('#ce-url', md).value.trim()) body.url = $('#ce-url', md).value.trim();
    if (x.kind === 'caldav') { body.username = $('#ce-user', md).value.trim(); if ($('#ce-pw', md).value) body.password = $('#ce-pw', md).value; }
    if (x.kind === 'caldav' && body.username === x.username) delete body.username;
    b.disabled = true;
    try {
      const r = await calReq('PATCH', `/api/calendars/${x.id}`, body);
      if (r.status === 'error' && (body.url || body.password || body.username)) { $('#ce-err', md).textContent = r.error_text; $('#ce-err', md).hidden = false; done && done(); return; }
      md.remove(); toast(tr('Saved')); done && done();
    } catch (err) { $('#ce-err', md).textContent = err.message; $('#ce-err', md).hidden = false; } finally { b.disabled = false; }
  });
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
function viewCal() {
  if (S.calMode === 'timeline' && !feat('timeline')) S.calMode = 'month';
  if (S.calMode === 'agenda') { if (feat('events')) return viewAgenda(); S.calMode = 'month'; }
  if (S.calMode === 'week' || S.calMode === 'day') return viewWeek();
  if (S.calMode === 'timeline') return calBar(tr('Timeline'), false, tlNdBtn(tlNdOn(null), openTasks().filter(t => !t.due).length)) + viewTimeline(null, true);
  const t0 = today();
  if (!S.calMonth) S.calMonth = t0.slice(0, 7);
  const [y, m] = S.calMonth.split('-').map(Number);
  const first = new Date(y, m - 1, 1);
  const start = weekStartOf(ds(first));  // UX1: the locale's first weekday (Monday in German, Sunday in en-US)
  const byDay = calByDay(start, addDays(start, 41));
  const evOn = calEvOn();
  if (evOn) ensureCalEv(start, addDays(start, 41));
  let cells = '';
  for (let i = 0; i < 42; i++) {
    const d = addDays(start, i);
    if (i === 35 && pd(d).getMonth() !== m - 1) break;
    const ts = byDay.get(d) || [];
    const out = pd(d).getMonth() !== m - 1;
    const evs = evOn ? cevOn(d).sort(cevSort) : [];
    const chips = [...evs.map(e => cevChip(e, d)), ...ts.map(t => `<div class="ev p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}" data-id="${t.id}" draggable="${t.status || t.ghost || isMobile() || !canEdit(t) ? 'false' : 'true'}">${msGlyph(t)}${t.due_time ? `<span class="muted">${t.due_time}</span> ` : ''}${esc(t.title)}</div>`)];
    cells += `<div class="cell ${out ? 'out' : ''} ${d === t0 ? 'today' : ''} ${d === S.calSel ? 'sel' : ''}" data-day="${d}">
      <span class="dn">${pd(d).getDate()}</span>
      ${chips.slice(0, 3).join('')}
      ${chips.length > 3 ? `<div class="more">+${chips.length - 3}</div>` : ''}
      <div class="dots">${evs.slice(0, 2).map(e => `<i class="ce" style="--cc:${cevColor(e)}"></i>`).join('')}${ts.filter(t => !t.status).slice(0, 4 - Math.min(2, evs.length)).map(t => `<i class="p${t.priority}${isMs(t) ? ' ms' : ''}"></i>`).join('')}</div>
    </div>`;
  }
  const sel = (byDay.get(S.calSel) || []).filter(t => !t.ghost);
  const selEv = evOn ? cevOn(S.calSel).sort(cevSort) : [];
  return `${calBar(`${MON[m - 1]} ${y}`)}
    <div class="cal">${wdOrder().map(i => `<div class="wd">${WD[i]}</div>`).join('')}${cells}</div>
    <div class="agenda"><h3>${dayLabel(S.calSel, true)}${S.calSel !== t0 && dayLabel(S.calSel, true) === WDL[pd(S.calSel).getDay()] ? '' : ''} <span class="muted" style="font-weight:400;font-size:var(--fs-m)">${fmtDate(S.calSel)}</span></h3>
      ${selEv.length ? `<div class="cevlist">${selEv.map(e => cevRow(e, S.calSel)).join('')}</div>` : ''}
      ${qaddBox()}
      ${sel.length ? sel.map(t => taskRow(t, {showList: true, drag: false})).join('') : `<div class="muted" style="padding:.5rem .25rem">${tr('No tasks on this day.')}</div>`}
    </div>`;
}

function viewWeek() {
  const day = S.calMode === 'day';
  const days = day ? [S.calSel] : [...Array(7)].map((_, i) => addDays(weekStartOf(S.calSel), i));
  const map = calByDay(days[0], days[days.length - 1]);
  const evOn = calEvOn();
  if (evOn) ensureCalEv(days[0], days[days.length - 1]);
  const evsOf = d => evOn ? cevOn(d).sort(cevSort) : [];
  const t0 = today(), H = weekH();
  const chip = t => `<div class="ev p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}" data-id="${t.id}" draggable="${t.status || t.ghost || isMobile() || !canEdit(t) ? 'false' : 'true'}">${msGlyph(t)}${esc(t.title)}</div>`;
  const now = new Date(), nowTop = (now.getHours() * 60 + now.getMinutes()) / 60 * H;
  const cols = days.map(d => {
    const blocks = layoutDay((map.get(d) || []).filter(t => t.due_time), evsOf(d).filter(e => cevTimed(e, d)).map(e => ({c: e, ...cevMin(e, d)}))).map(it => {
      const t = it.t, top = it.s / 60 * H, h = Math.max((it.e - it.s) / 60 * H, 20);
      if (it.c) return `<div class="wcev" data-cev="${it.c.id}" style="--cc:${cevColor(it.c)};top:${top}px;height:${h}px;left:calc(${it.lane} * 100% / ${it.n});width:calc(100% / ${it.n} - 2px)"><b>${it.c.d0 === d ? fmtHM(it.c.s) : '…'}</b> ${esc(cevTitle(it.c))}</div>`;
      return `<div class="wev p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}" data-id="${t.id}" draggable="${t.status || t.ghost || isMobile() || !canEdit(t) ? 'false' : 'true'}" style="top:${top}px;height:${h}px;left:calc(${it.lane} * 100% / ${it.n});width:calc(100% / ${it.n} - 2px)">${msGlyph(t)}<b>${t.due_time}</b> ${esc(t.title)}</div>`;
    }).join('');
    return `<div class="wcol ${d === t0 ? 'today' : ''}" data-day="${d}">${blocks}${d === t0 ? `<i class="nowline" style="top:${nowTop}px"></i>` : ''}</div>`;
  }).join('');
  // 2.6.0 (K25): the week's own dates ("28. Sep – 4. Okt · KW 40"), short enough for one line on a phone; the month and
  // year of a week that spans two follow its middle (Thursday) where only one is shown
  const title = day ? fmtDay('long', pd(S.calSel)) : weekTitle(days[0]);
  return `${calBar(title)}<div class="week ${day ? 'oneday' : ''}" style="--cols:${days.length};--h:${H}px">
    <div class="whead"><div></div>${days.map(d => `<div class="wh ${d === t0 ? 'today' : ''}" data-day="${d}"><span>${WD[pd(d).getDay()]}</span><b>${pd(d).getDate()}</b></div>`).join('')}</div>
    <div class="wallday"><div class="wlbl">${tr('all day|short')}</div>${days.map(d => `<div class="wad" data-day="${d}">${evsOf(d).filter(e => !cevTimed(e, d)).map(e => cevChip(e, d)).join('')}${(map.get(d) || []).filter(t => !t.due_time).map(chip).join('')}</div>`).join('')}</div>
    <div class="wbody" id="wbody" tabindex="0" role="region" aria-label="${esc(tr('Hours of the week'))}"><div class="wgutter">${[...Array(24)].map((_, h) => `<div class="wtime" style="top:${h * H}px">${pad(h)}:00</div>`).join('')}</div>${cols}</div></div>`;
}
function isoWeek(s) { const d = pd(s); d.setDate(d.getDate() + 3 - (d.getDay() + 6) % 7); const w1 = new Date(d.getFullYear(), 0, 4); return 1 + Math.round(((d - w1) / 864e5 - 3 + (w1.getDay() + 6) % 7) / 7); }
function layoutDay(evs, extra = []) {  // side-by-side lanes for overlapping timed tasks (+ calendar events: {c, s, e})
  const items = evs.map(t => { const s = hm(t.due_time); return {t, s, e: s + Math.max(15, t.duration || 30)}; }).concat(extra).sort((a, b) => a.s - b.s || b.e - a.e);
  const out = []; let cluster = [], lanes = [], end = -1;
  const close = () => { cluster.forEach(x => { x.n = lanes.length; }); out.push(...cluster); cluster = []; lanes = []; end = -1; };
  for (const it of items) {
    if (cluster.length && it.s >= end) close();
    let lane = lanes.findIndex(e => e <= it.s);
    if (lane < 0) { lane = lanes.length; lanes.push(it.e); } else lanes[lane] = it.e;
    it.lane = lane; cluster.push(it); end = Math.max(end, it.e);
  }
  if (cluster.length) close();
  return out;
}

// ------------------------------------------------------------------ 2.36.1 (#1126 #1127 #956): which calendars show where
// Four user settings (server, every device): cal_tasks + cal_lists_hidden (tasks in the calendar views), today_cals_hidden
// (the "Events today" block) and plan_cals_off (the day planner, also the agent's). A calendar is keyed "e:<own calendar id>"
// or "s:<subscription id>". "Show in my calendar" stays what it was (evcals.hidden / cal_subs.visible, one field each);
// a calendar hidden there is gone from Today and the planner as well (the server does not even send its events).
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
