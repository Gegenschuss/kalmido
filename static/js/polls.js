/* Kalmido web client: scheduling polls (2.98.0 A, #1953) -- several proposed times, people vote through a public link,
   the winning time becomes an event with one click. Classic script sharing the global scope with the others (load order:
   index.html, docs/ARCHITECTURE.md). */
'use strict';

// Start points: "Find a date" in the calendar bar (the list of polls), "Find a date" next to "Schedule as an event" in a
// task and in a client's "…" menu (the poll is about it). The server (calendars/polls.py) keeps the times as wall clock in
// the poll's zone; the dialogs show them as they are and name the zone when it is not the device's. Every action is ONE undo
// step: create (undo = trash), change (undo = the fields before), delete (undo = restore), choose a time (undo = reopen, its
// event goes to the trash), move to another workspace (undo = the move back). Agents get no access (people only).
const tpo_on = () => feat('events') && S.me?.kind !== 'agent';
const TPO_DUR = [15, 30, 45, 60, 90, 120, 180, 240];
const tpo_tzNote = p => p.tz && p.tz !== evTz() ? ` (${p.tz})` : '';
function tpo_when(o, p) {
  const d0 = o.start.slice(0, 10), d1 = o.end.slice(0, 10);
  return `${fmtDayAbs(d0)} ${fmtTimeLoc(o.start.slice(11, 16))}–${d1 !== d0 ? fmtDayAbs(d1) + ' ' : ''}${fmtTimeLoc(o.end.slice(11, 16))}${p ? tpo_tzNote(p) : ''}`;
}
function tpo_status(p) {
  if (p.closed_at) { const o = p.options.find(x => x.id === p.chosen_id); return o ? tr('Chosen: {0}', tpo_when(o, p)) : tr('Closed'); }
  return trn('{0} vote', '{0} votes', p.votes_n) + (p.link_on ? '' : ' · ' + tr('Link turned off'));
}
async function tpo_get(id) { return (await api('GET', `/api/polls/${id}`)).poll; }
function tpo_redraw() { calInvalidate(); render(); }

// ---- the list of polls (the calendar bar's "Find a date")
async function tpo_list() {
  await loadCss('calendar').catch(() => {});
  let items = [];
  try { items = (await api('GET', '/api/polls')).items || []; } catch { return; }
  const md = modal(`<div class="lhdr"><h3 id="tpo-lt">${esc(tr('Find a date'))}</h3><span class="spacer"></span><button class="iconbtn" data-tpo="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="muted mhint">${esc(tr('Propose several times, send the link, and the time that suits most becomes an event.'))}</p>
    <div class="tpo-list">${items.length ? items.map(p => `<button type="button" class="tpo-li${p.closed_at ? ' tpo-closed' : ''}" data-tpo-open="${p.id}">
      <span class="tpo-lt">${esc(p.title)}</span><span class="muted tpo-ls">${esc(tpo_status(p))}</span></button>`).join('')
      : `<p class="empty">${esc(tr('No polls yet'))}</p>`}</div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-tpo="new">${ic('plus', 's')} ${esc(tr('New poll'))}</button></div>`);
  md.classList.add('tpo-dlg');
  md.setAttribute('aria-labelledby', 'tpo-lt');
  md.addEventListener('click', e => {
    if (e.target.closest('[data-tpo="close"]')) md.remove();
    else if (e.target.closest('[data-tpo="new"]')) { md.remove(); tpo_edit(); }
    else { const b = e.target.closest('[data-tpo-open]'); if (b) { md.remove(); tpo_show(+b.dataset.tpoOpen); } }
  });
}

// ---- create / change
function tpo_defTimes() {  // three proposals: the next three working days at 10:00
  const out = []; let d = new Date(); d.setHours(10, 0, 0, 0);
  while (out.length < 3) { d = new Date(d.getTime() + 864e5); if (d.getDay() % 6) out.push({start: `${ds(d)}T10:00`}); }
  return out;
}
function tpo_rowHtml(o = {}) {
  return `<div class="tpo-row" data-id="${o.id || ''}"><input type="date" class="tpo-d" value="${esc((o.start || '').slice(0, 10))}" aria-label="${esc(tr('Date'))}" required>
    <input type="time" class="tpo-t" value="${esc((o.start || '').slice(11, 16))}" aria-label="${esc(tr('Time'))}" required>
    <button type="button" class="iconbtn" data-tpo="rm" aria-label="${esc(tr('Remove'))}" title="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`;
}
async function tpo_edit(p = null, o = {}) {
  await loadCss('calendar').catch(() => {});
  const spaces = wsOn() ? wsOptions().filter(w => w !== 'all') : [];
  const sp0 = o.space || (wsCur() !== 'all' ? wsCur() : 'private');
  const dur = p ? p.duration : 60, closed = !!p?.closed_at;
  const times = p ? p.options : tpo_defTimes();
  const md = modal(`<form class="tpo-form" novalidate><div class="lhdr"><h3 id="tpo-et">${esc(p ? tr('Change poll') : tr('New poll'))}</h3><span class="spacer"></span><button type="button" class="iconbtn" data-tpo="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="row"><label for="tpo-title">${esc(tr('Title'))}</label><input id="tpo-title" maxlength="200" required value="${esc(p?.title ?? o.title ?? '')}" placeholder="${esc(tr('e.g. Kick-off meeting'))}"></div>
    <div class="row"><label for="tpo-desc">${esc(tr('Description'))}</label><textarea id="tpo-desc" rows="2" maxlength="4000">${esc(p?.description || '')}</textarea></div>
    <div class="row"><label for="tpo-loc">${esc(tr('Place or video link'))}</label><input id="tpo-loc" maxlength="500" value="${esc(p?.location || '')}"></div>
    <div class="row"><label for="tpo-dur">${esc(tr('Duration'))}</label><select id="tpo-dur">${[...new Set([...TPO_DUR, dur])].sort((a, b) => a - b).map(m => `<option value="${m}" ${m === dur ? 'selected' : ''}>${esc(m < 60 ? tr('{0} min', m) : m % 60 ? tr('{0} h {1} min', Math.floor(m / 60), m % 60) : tr('{0} h', m / 60))}</option>`).join('')}</select></div>
    ${!p && spaces.length > 1 ? `<div class="row"><label for="tpo-sp">${esc(tr('Workspace'))}</label><select id="tpo-sp">${spaces.map(w => `<option value="${w}" ${w === sp0 ? 'selected' : ''}>${esc(wsName(w))}</option>`).join('')}</select></div>` : ''}
    <fieldset class="tpo-times"${closed ? ' disabled' : ''}><legend>${esc(tr('Proposed times'))}</legend><div class="tpo-rows">${times.map(tpo_rowHtml).join('')}</div>
      <button type="button" class="attadd" data-tpo="add">${ic('plus', 's')}<span>${esc(tr('Add a time'))}</span></button>
      ${closed ? `<p class="muted mhint">${esc(tr('The poll is closed: reopen it to change the times'))}</p>` : ''}</fieldset>
    <div class="row"><label for="tpo-exp">${esc(tr('Voting ends'))}</label><input type="date" id="tpo-exp" value="${esc(p?.expires_at ? ds(new Date(p.expires_at)) : '')}"></div>
    <label class="chkl"><input type="checkbox" id="tpo-names" ${p ? (p.show_votes ? 'checked' : '') : 'checked'}> ${esc(tr('Voters see the names and answers of the others'))}</label>
    <p class="tpo-err err" role="alert" hidden></p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-tpo="close">${esc(tr('Cancel'))}</button><button type="submit" class="btn pri">${esc(p ? tr('Save') : tr('Create'))}</button></div></form>`);
  md.classList.add('tpo-dlg');
  md.setAttribute('aria-labelledby', 'tpo-et');
  const rows = $('.tpo-rows', md), fail = t => { const x = $('.tpo-err', md); x.textContent = t; x.hidden = !t; };
  md.addEventListener('click', e => {
    if (e.target.closest('[data-tpo="close"]')) md.remove();
    else if (e.target.closest('[data-tpo="add"]')) {
      if ($$('.tpo-row', rows).length >= 20) { fail(tr('Please propose between {0} and {1} times', 2, 20)); return; }
      const last = $$('.tpo-row', rows).pop(), d = last ? $('.tpo-d', last).value : '', t = last ? $('.tpo-t', last).value : '10:00';
      rows.insertAdjacentHTML('beforeend', tpo_rowHtml({start: d ? `${addDays(d, 1)}T${t || '10:00'}` : ''}));
      $('.tpo-row:last-child .tpo-d', rows)?.focus();
    } else { const r = e.target.closest('[data-tpo="rm"]'); if (r && $$('.tpo-row', rows).length > 2) r.closest('.tpo-row').remove(); }
  });
  $('form', md).addEventListener('submit', async e => {
    e.preventDefault(); fail('');
    const title = $('#tpo-title', md).value.trim();
    if (!title) { fail(tr('Title missing')); $('#tpo-title', md).focus(); return; }
    const opts = $$('.tpo-row', rows).map(r => ({...(r.dataset.id ? {id: +r.dataset.id} : {}), d: $('.tpo-d', r).value, t: $('.tpo-t', r).value}));
    if (!closed && (opts.some(x => !x.d || !x.t) || opts.length < 2)) { fail(tr('Please propose between {0} and {1} times', 2, 20)); return; }
    const exp = $('#tpo-exp', md).value;
    const b = {title, description: $('#tpo-desc', md).value, location: $('#tpo-loc', md).value, duration: +$('#tpo-dur', md).value,
      show_votes: $('#tpo-names', md).checked, expires_at: exp || null,
      ...(closed ? {} : {options: opts.map(x => ({...(x.id ? {id: x.id} : {}), start: `${x.d}T${x.t}`}))})};
    const btn = $('button[type=submit]', md); btn.disabled = true;
    try {
      if (p) {
        const was = {title: p.title, description: p.description, location: p.location, duration: p.duration, show_votes: p.show_votes,
          expires_at: p.expires_at, ...(closed ? {} : {options: p.options.map(x => ({id: x.id, start: x.start, end: x.end}))})};
        const r = (await rawFetch('PATCH', `/api/polls/${p.id}`, b)).poll;
        md.remove();
        histToast(tr('Poll saved'), histAdd({label: tr('Poll “{0}” changed', r.title), undo: () => api('PATCH', `/api/polls/${p.id}`, was), redo: () => api('PATCH', `/api/polls/${p.id}`, b)}));
        tpo_show(r);
      } else {
        const sp = $('#tpo-sp', md)?.value || (spaces.length ? sp0 : 'private');
        const r = (await rawFetch('POST', '/api/polls', {...b, tz: evTz() || undefined, space: sp,
          ...(o.task_id ? {task_id: o.task_id} : {}), ...(o.client_id ? {client_id: o.client_id} : {}), ...(o.list_id ? {list_id: o.list_id} : {})})).poll;
        md.remove();
        histToast(tr('Poll created'), histAdd({label: tr('Poll “{0}” created', r.title), undo: () => api('DELETE', `/api/polls/${r.id}`), redo: () => api('POST', `/api/polls/${r.id}/restore`)}));
        tpo_show(r);
      }
    } catch (x) { btn.disabled = false; fail(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message); }
  });
  $('#tpo-title', md).focus();
}

// ---- one poll: link, results, choosing the time
async function tpo_show(p) {
  if (typeof p === 'number') { try { p = await tpo_get(p); } catch { return; } }
  await loadCss('calendar').catch(() => {});
  const md = modal('');
  md.classList.add('tpo-dlg');
  md.setAttribute('aria-labelledby', 'tpo-st');
  const draw = () => {
    const best = p.best_id, open = !p.closed_at, max = Math.max(1, ...p.options.map(o => o.y + o.m));
    const who = id => { const y = [], m = []; for (const v of p.votes || []) { const a = v.answers[String(id)]; if (a === 'y') y.push(v.name); else if (a === 'm') m.push(v.name); } return {y, m}; };
    const opt = o => { const w = who(o.id); return `<li class="tpo-o${o.id === best ? ' tpo-best' : ''}${o.id === p.chosen_id ? ' tpo-chosen' : ''}">
      <div class="tpo-oh"><span class="tpo-ow">${esc(tpo_when(o, p))}</span>${o.id === best && open ? `<span class="tpo-tag">${esc(tr('Best time'))}</span>` : ''}${o.id === p.chosen_id ? `<span class="tpo-tag">${esc(tr('Chosen'))}</span>` : ''}</div>
      <div class="tpo-bar" aria-hidden="true"><span class="tpo-by" style="width:${(o.y / max * 100).toFixed(1)}%"></span><span class="tpo-bm" style="width:${(o.m / max * 100).toFixed(1)}%"></span></div>
      <div class="tpo-oc muted">${esc(tr('{0} yes · {1} maybe · {2} no', o.y, o.m, o.n))}</div>
      ${w.y.length || w.m.length ? `<div class="tpo-on">${w.y.length ? `<span><b>${esc(tr('Yes'))}:</b> ${esc(w.y.join(', '))}</span>` : ''}${w.m.length ? `<span><b>${esc(tr('Maybe'))}:</b> ${esc(w.m.join(', '))}</span>` : ''}</div>` : ''}
      ${open && p.can_edit ? `<button type="button" class="btn sm${o.id === best ? ' pri' : ''}" data-tpo-pick="${o.id}">${ic('cal', 's')} ${esc(tr('Choose this time'))}</button>` : ''}</li>`; };
    md.querySelector('.card').innerHTML = `<div class="lhdr"><h3 id="tpo-st">${esc(p.title)}</h3><span class="spacer"></span>
      ${p.can_edit ? `<button class="iconbtn" data-tpo="menu" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button>` : ''}
      <button class="iconbtn" data-tpo="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
      <p class="muted tpo-sub">${esc(tpo_status(p))}${p.location ? ' · ' + esc(p.location) : ''}${wsOn() ? ' · ' + esc(wsName(p.space)) : ''}</p>
      ${p.url ? `<div class="tpo-link"><input readonly value="${esc(p.url)}" aria-label="${esc(tr('Link to the poll'))}"${p.live ? '' : ' class="tpo-off"'}>
        <button type="button" class="btn sm" data-tpo="copy">${ic('copy', 's')} ${esc(tr('Copy'))}</button><button type="button" class="iconbtn" data-tpo="qr" aria-label="${esc(tr('QR code'))}" title="${esc(tr('QR code'))}">${ic('grid', 's')}</button></div>
        ${p.live ? '' : `<p class="muted mhint">${esc(!p.link_on ? tr('The link is turned off: nobody can vote.') : p.expires_at && new Date(p.expires_at) < new Date() ? tr('Voting has ended: the link no longer opens.') : tr('Public links are turned off on this server'))}</p>`}
        <div class="tpo-qr" hidden></div>` : ''}
      ${p.description ? `<p class="tpo-desc">${esc(p.description)}</p>` : ''}
      <ul class="tpo-opts">${p.options.map(opt).join('')}</ul>
      ${p.votes_n ? '' : `<p class="empty">${esc(tr('No votes yet. Send the link to the people you want to meet.'))}</p>`}
      <div class="foot">${p.closed_at && p.event_id ? `<button type="button" class="btn" data-tpo="event">${ic('cal', 's')} ${esc(tr('Open event'))}</button>` : ''}
        ${p.closed_at && p.can_edit ? `<button type="button" class="btn" data-tpo="reopen">${ic('undo', 's')} ${esc(tr('Reopen poll'))}</button>` : ''}
        <span class="spacer"></span><button type="button" class="btn" data-tpo="close">${esc(tr('Close'))}</button></div>`;
  };
  const reload = async () => { try { p = await tpo_get(p.id); } catch { md.remove(); return; } if (md.isConnected) draw(); };
  draw();
  md.addEventListener('click', async e => {
    const k = e.target.closest('[data-tpo]')?.dataset.tpo;
    const pick = e.target.closest('[data-tpo-pick]');
    if (pick) { tpo_decide(p, +pick.dataset.tpoPick, reload); return; }
    if (k === 'close') md.remove();
    else if (k === 'copy') copyText(p.url);
    else if (k === 'qr') {
      const box = $('.tpo-qr', md); if (!box) return;
      if (!box.hidden) { box.hidden = true; return; }
      try { const r = await api('POST', '/api/qr', {text: p.url}); box.innerHTML = `<img src="${esc(r.qr)}" alt="${esc(tr('QR code of the link'))}">`; box.hidden = false; } catch { /* the toast said it */ }
    } else if (k === 'event') { md.remove(); evOpen(p.event_id); }
    else if (k === 'reopen') {
      const was = {option_id: p.chosen_id, ...tpo_target(p)};
      try { await api('POST', `/api/polls/${p.id}/reopen`); } catch { return; }
      // 2.98.0 review (L1): an event in a CalDAV subscription goes the calendar's own delete way (else choosing again doubles it)
      const dav = /^s(\d+):(.+)$/.exec(p.event_ref || '');
      if (dav) { try { await api('DELETE', `/api/calendars/${dav[1]}/events?uid=${encodeURIComponent(dav[2])}`); } catch { /* the toast said it */ } }
      histToast(tr('Poll open again'), histAdd({label: tr('Poll “{0}” reopened', p.title), undo: () => api('POST', `/api/polls/${p.id}/decide`, was).then(tpo_redraw),
        redo: () => api('POST', `/api/polls/${p.id}/reopen`).then(tpo_redraw)}));
      tpo_redraw(); reload();
    } else if (k === 'menu') {
      const b = e.target.closest('[data-tpo="menu"]');
      menu(b, [{label: tr('Edit'), icon: 'edit', fn: () => { md.remove(); tpo_edit(p); }},
        {label: tr('New link (the old one stops)'), icon: 'link', fn: () => tpo_patch(p, {regenerate: true}, tr('New link created'), null).then(reload)},
        {label: p.link_on ? tr('Turn the link off') : tr('Turn the link on'), icon: p.link_on ? 'ban' : 'link',
          fn: () => tpo_patch(p, {link_on: !p.link_on}, p.link_on ? tr('Link turned off') : tr('Link turned on'), {link_on: p.link_on}).then(reload)},
        typeof smv_can === 'function' && p.mine && smv_can(p.org_id ?? null) ? {label: tr('Move to another workspace…'), icon: 'brief', fn: () => tpo_move(p).then(reload)} : null,
        {label: tr('Delete'), icon: 'trash', fn: () => tpo_delete(p, md)}]);
    }
  });
}
function tpo_target(p) {  // the calendar of the chosen event (for the redo of a reopen)
  const r = String(p.event_ref || '');
  if (/^s\d+:/.test(r)) return {sub_id: +r.slice(1, r.indexOf(':'))};
  return p.event_cal_id ? {cal_id: p.event_cal_id} : {};
}
async function tpo_patch(p, body, msg, back) {
  try { await api('PATCH', `/api/polls/${p.id}`, body); } catch { return; }
  if (back) histToast(msg, histAdd({label: msg, undo: () => api('PATCH', `/api/polls/${p.id}`, back), redo: () => api('PATCH', `/api/polls/${p.id}`, body)}));
  else toast(msg);
}
async function tpo_delete(p, md) {
  try { await api('DELETE', `/api/polls/${p.id}`); } catch { return; }
  md?.remove();
  histToast(tr('Poll deleted'), histAdd({label: tr('Poll “{0}” deleted', p.title), undo: () => api('POST', `/api/polls/${p.id}/restore`), redo: () => api('DELETE', `/api/polls/${p.id}`)}));
}
async function tpo_move(p) {
  const from = p.org_id ?? null, url = `/api/polls/${p.id}/move-space`;
  const r = await smv_open({what: `“${p.title}”`, from, check: to => rawFetch('POST', url, {to: to ?? 'private', dry: 1}),
    run: to => rawFetch('POST', url, {to: to ?? 'private'})});
  if (!r || !r.ok) return;
  histToast(tr('Poll moved'), histAdd({label: tr('Poll “{0}” moved', p.title), undo: () => api('POST', url, {to: from ?? 'private'}), redo: () => api('POST', url, {to: r.space})}));
}

// ---- "Choose this time": the calendar, the optional invitation
function tpo_cals() {  // Kalmido calendars the person may write + CalDAV subscriptions with "Allow writing"
  const own = (S.evcals || []).filter(evWrite).map(c => ({id: String(c.id), name: c.name + (c.role !== 'owner' && c.owner_name ? ' · ' + c.owner_name : '')}));
  return {own, subs: typeof dvw_cals === 'function' ? dvw_cals({}) : []};
}
function tpo_decide(p, oid, done) {
  const o = p.options.find(x => x.id === oid); if (!o) return;
  const {own, subs} = tpo_cals();
  const mails = (p.votes || []).filter(v => v.email && ['y', 'm'].includes(v.answers[String(oid)])).length;
  const pc = (S.evcals || []).find(c => evWrite(c) && (c.org_id ?? null) === (p.org_id ?? null)) || (S.evcals || []).find(c => evWrite(c) && !c.org_id);
  const md = modal(`<form class="tpo-form" novalidate><div class="lhdr"><h3 id="tpo-dt">${esc(tr('Choose this time'))}</h3><span class="spacer"></span><button type="button" class="iconbtn" data-tpo="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="tpo-dw"><b>${esc(tpo_when(o, p))}</b></p>
    <p class="muted mhint">${esc(tr('The event is created in the calendar you choose; the voters are named in its description. The poll then closes and its link shows only this time.'))}</p>
    <div class="row"><label for="tpo-cal">${esc(tr('Calendar'))}</label><select id="tpo-cal">${own.length || subs.length ? '' : `<option value="">${esc(tr('Calendar'))}</option>`}${own.map(c => `<option value="${c.id}" ${pc && String(pc.id) === c.id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}
      ${subs.length ? `<optgroup label="${esc(tr('Subscribed calendars'))}">${subs.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</optgroup>` : ''}</select></div>
    ${mails ? `<label class="chkl"><input type="checkbox" id="tpo-mail"> ${esc(trn('Send an invitation to the {0} voter with an e-mail address', 'Send an invitation to the {0} voters with an e-mail address', mails))}</label>` : ''}
    <p class="tpo-err err" role="alert" hidden></p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-tpo="close">${esc(tr('Cancel'))}</button><button type="submit" class="btn pri">${esc(tr('Create event'))}</button></div></form>`);
  md.classList.add('tpo-dlg');
  md.setAttribute('aria-labelledby', 'tpo-dt');
  md.addEventListener('click', e => { if (e.target.closest('[data-tpo="close"]')) md.remove(); });
  $('form', md).addEventListener('submit', async e => {
    e.preventDefault();
    const v = $('#tpo-cal', md).value, btn = $('button[type=submit]', md), err = $('.tpo-err', md);
    const target = dvw_isSub(v) ? {sub_id: +v.slice(1)} : v ? {cal_id: +v} : {};
    btn.disabled = true;
    let r; try { r = await rawFetch('POST', `/api/polls/${p.id}/decide`, {option_id: oid, ...target, mail: !!$('#tpo-mail', md)?.checked}); }
    catch (x) { btn.disabled = false; err.textContent = x instanceof Offline ? tr('Offline: only works again with a connection') : x.message; err.hidden = false; return; }
    md.remove();
    const again = {option_id: oid, ...target, mail: false};  // a redo never mails twice
    histToast(r.mailed ? trn('Event created, {0} invitation sent', 'Event created, {0} invitations sent', r.mailed) : tr('Event created'),
      histAdd({label: tr('Time chosen for “{0}”', p.title), undo: () => api('POST', `/api/polls/${p.id}/reopen`).then(tpo_redraw),
        redo: () => api('POST', `/api/polls/${p.id}/decide`, again).then(tpo_redraw)}));
    tpo_redraw();
    done && done();
  });
}

// ---- the start points
document.addEventListener('click', e => {
  if (e.target.closest('[data-act="tpo-list"]')) { tpo_list(); return; }
  if (e.target.closest('[data-act="tpo-task"]')) {
    const t = taskById(S.sel); if (!t) return;
    const l = listById(t.list_id);
    tpo_edit(null, {task_id: t.id, title: t.title, space: wsOf(l)});
  }
});
// a client's "…" menu (clientpage.js): the poll is about this client, in its workspace
function tpo_forClient(c) { tpo_edit(null, {client_id: c.id, title: c.name, space: c.org_id ? 'org:' + c.org_id : 'private'}); }
