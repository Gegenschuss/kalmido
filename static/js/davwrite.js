// 2.52.0 (#1128): events in CalDAV subscriptions with "Allow writing": new / change / delete from the event window, the
// popover and dragging (calendar part A calls dvw_commit). The server writes with ETags; a conflict reloads, nothing is overwritten.
const dvw_isSub = v => /^s\d+$/.test(String(v || ''));
const dvw_sub = id => (S.cal?.subs || {})[id];
// the writable subscriptions for the "Calendar" field of the event window (only shown subscriptions, they come with the events)
function dvw_cals(o = {}) {
  if (o.ev) return [];  // a Kalmido event does not move into another service
  const subs = S.cal?.subs || {};
  const ids = o.dvw ? [o.dvw.sub] : Object.keys(subs).filter(k => subs[k].w).map(Number);
  return ids.filter(id => subs[id]).map(id => ({id: 's' + id, name: subs[id].name || tr('Calendar')}));
}
function dvw_options(o, cur) {
  const list = dvw_cals(o); if (!list.length) return '';
  return `<optgroup label="${esc(tr('Subscribed calendars'))}">${list.map(c => `<option value="${c.id}" ${c.id === cur ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</optgroup>`;
}
// fields a subscribed calendar does not get from Kalmido (repeat, reminders, people, more) are hidden while it is chosen
function dvw_rows(md) {
  const on = dvw_isSub($('#ev-cal', md)?.value);
  $$('.evrep, .evrems, .evatts, .evmore', md).forEach(x => { x.hidden = on; });
}
const dvw_wall = d => `${ds(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
const dvw_utc = s => new Date(s).toISOString().replace(/\.\d{3}Z$/, 'Z');
const dvw_occ = (start, ad) => ad ? start.slice(0, 10) : dvw_utc(start);  // a start as the server stores it (cal_events)
function dvw_was(e) {  // a subscription event as the fields the routes take
  return e.all_day ? {title: e.title, location: e.location || '', description: e.description || '', all_day: true, start: e.start, end: e.end}
    : {title: e.title, location: e.location || '', description: e.description || '', all_day: false, start: dvw_wall(e.s), end: dvw_wall(e.e)};
}
async function dvw_req(method, url, body) {
  try { return await api(method, url, body); } catch (e) {
    if (e.status === 409 || e.status === 404) { calInvalidate(); render(); }  // changed elsewhere: show what the calendar has now
    throw e;
  }
}
async function dvw_patch(sid, uid, occ, body) {
  return dvw_req('PATCH', `/api/calendars/${sid}/events`, {...body, uid, occ, scope: 'all', tz: evTz()});
}
// the event window's Save for a subscribed calendar: o = the evEditor options (o.dvw = the event when it is changed)
async function dvw_save(o, sel, body) {
  const sid = +String(sel).slice(1), name = dvw_sub(sid)?.name || tr('Calendar');
  const b = {title: body.title, location: body.location || '', description: body.description || '', all_day: body.all_day, start: body.start, end: body.end};
  try {
    if (o.dvw) {
      const e = o.dvw, was = dvw_was(e);
      await dvw_patch(sid, e.uid, e.start, b);
      histToast(tr('Event saved'), histAdd({label: tr('Event changed in “{0}”', name), undo: () => dvw_patch(sid, e.uid, dvw_occ(b.start, b.all_day), was).then(dvw_redraw),
        redo: () => dvw_patch(sid, e.uid, dvw_occ(was.start, was.all_day), b).then(dvw_redraw)}));
    } else {
      const r = await dvw_req('POST', `/api/calendars/${sid}/events`, {...b, tz: evTz()});
      let tok = '';
      histToast(tr('Event created'), histAdd({label: tr('Event created in “{0}”', name),
        undo: async () => { tok = (await dvw_req('DELETE', `/api/calendars/${sid}/events?uid=${encodeURIComponent(r.uid)}`)).undo; dvw_redraw(); },
        redo: async () => { await dvw_req('POST', `/api/calendars/${sid}/events/restore`, {undo: tok}); dvw_redraw(); }}));
    }
  } catch { return false; }
  dvw_redraw();
  return true;
}
function dvw_redraw() { calInvalidate(); render(); }
// dragging (part A, caldrag.js cg_commit): patch = {start, end, all_day} as for own events; scope 'one' is not offered for a series
async function dvw_commit(ev, patch, scope) {
  if (!ev?.dvw_write) return false;
  if (scope === 'one' && ev.dvw_rec) { toast(tr('For calendars of other services only the whole series can be changed')); return false; }
  const name = dvw_sub(ev.sub)?.name || tr('Calendar'), was = dvw_was(ev);
  const b = {all_day: !!patch.all_day, start: patch.start, end: patch.end};
  const back = {all_day: was.all_day, start: was.start, end: was.end};
  try { await dvw_patch(ev.sub, ev.uid, ev.start, b); } catch { return false; }
  histToast(tr('Event moved'), histAdd({label: tr('Event changed in “{0}”', name),
    undo: () => dvw_patch(ev.sub, ev.uid, dvw_occ(b.start, b.all_day), back).then(dvw_redraw),
    redo: () => dvw_patch(ev.sub, ev.uid, dvw_occ(back.start, back.all_day), b).then(dvw_redraw)}));
  dvw_redraw();
  return true;
}
async function dvw_delete(e) {
  const msg = e.dvw_rec ? tr('This event repeats: every date is removed from the calendar “{0}”.', cevCal(e)) : tr('It is removed from the calendar “{0}”.', cevCal(e));
  if (!await askConfirm(tr('Delete the event “{0}”?', cevTitle(e)), msg, {ok: tr('Delete'), danger: true})) return;
  let tok;
  try { tok = (await dvw_req('DELETE', `/api/calendars/${e.sub}/events?uid=${encodeURIComponent(e.uid)}`)).undo; } catch { return; }
  dvw_redraw();
  histToast(tr('Event deleted'), histAdd({label: tr('Event deleted'),
    undo: async () => { await dvw_req('POST', `/api/calendars/${e.sub}/events/restore`, {undo: tok}); dvw_redraw(); },
    redo: async () => { tok = (await dvw_req('DELETE', `/api/calendars/${e.sub}/events?uid=${encodeURIComponent(e.uid)}`)).undo; dvw_redraw(); }}));
}
// the popover of an event from a writable subscription (calendar.js cevPop hands over)
function dvw_pop(anchor, e) {
  const desc = (e.description || '').slice(0, 2000);
  const p = openPop(anchor, `<div class="cevpop" style="--cc:${cevColor(e)}">
    <div class="cevh"><i class="cevdot"></i><b>${esc(cevTitle(e))}</b></div>
    <div class="cevm">${ic('clock', 's')}<span>${esc(cevWhen(e))}</span></div>
    ${e.location ? `<div class="cevm">${ic('mappin', 's')}<span>${esc(e.location)}</span></div>` : ''}
    <div class="cevm">${ic('cal', 's')}<span>${esc(cevCal(e))}</span></div>
    ${desc ? `<div class="cevdesc">${cevLinkify(desc)}${e.description.length > 2000 ? '…' : ''}</div>` : ''}
    <div class="cevact dvwact"><button class="btn sm" data-dvw="edit">${ic('edit', 's')} ${tr('Edit')}</button><button class="btn sm danger" data-dvw="del">${ic('trash', 's')} ${tr('Delete')}</button>
      <button class="btn sm pri" data-cevtask>${ic('plus', 's')} ${tr('Create task from event')}</button></div></div>`);
  p.onclick = ev => {
    const b = ev.target.closest('[data-dvw], [data-cevtask]'); if (!b) return;
    closePop();
    if (b.hasAttribute('data-cevtask')) cevToTask(e);
    else if (b.dataset.dvw === 'del') dvw_delete(e);
    else dvw_edit(e);
  };
}
function dvw_edit(e) {
  const w = dvw_was(e);
  evEditor({dvw: e, cal_id: 's' + e.sub, title: w.title, location: w.location, description: w.description, all_day: w.all_day, start: w.start, end: w.end});
}
// "Allow writing" in the subscription's edit window (CalDAV only; switched at once, the server checks the privileges first)
function dvw_editRow(x) {
  if (x.kind !== 'caldav') return '';
  const on = x.write && x.can_write;
  return `<div class="row"><label for="ce-dvw">${tr('Allow writing')}</label><label class="swc"><input type="checkbox" id="ce-dvw" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span><span class="sr">${esc(tr('Allow writing'))}</span></label></div>
    <p class="muted mhint dvwhint">${tr('New events can be saved into this calendar, and its events can be changed, moved and deleted in Kalmido. Off: read-only.')}</p>`;
}
function dvw_editWire(md, x, done) {
  md.addEventListener('change', async e => {
    if (e.target.id !== 'ce-dvw') return;
    const inp = e.target, on = inp.checked, er = $('#ce-err', md);
    inp.disabled = true; if (er) er.hidden = true;
    const put = v => api('POST', `/api/calendars/${x.id}/write`, {on: v}).then(r => { Object.assign(x, r); dvw_redraw(); done && done(); return r; });
    try {
      await rawFetch('POST', `/api/calendars/${x.id}/write`, {on}).then(r => { Object.assign(x, r); });
      dvw_redraw(); done && done();
      histToast(on ? tr('Writing allowed') : tr('Read-only'), histAdd({label: tr('Changed setting: {0}', tr('Allow writing')), sett: true, undo: () => put(!on), redo: () => put(on)}));
    } catch (err) {
      inp.checked = !on;
      if (er) { er.textContent = err instanceof Offline ? tr('Offline: only works again with a connection') : err.message; er.hidden = false; }
    } finally { inp.disabled = false; }
  });
}
