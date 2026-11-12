/* Kalmido web client: the calendar views month / week / day and Settings > Integrations > Calendars (module "calendar",
   loaded on demand with caldrag.js, 2.65.0 #1823; moved unchanged from calendar.js, which keeps the events' data, the
   kanban board, the agenda's bar and what other views show of the calendar).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';
// Settings > Integrations > Calendars (own requests, applied at once) + the admin allow-list (Settings > Users)
function calsHtml(chk, hint) {
  if (!S.calendars?.enabled) return `<h4 id="s-cals-h">${tr('Calendars')}</h4>${hintK(tr('Calendar subscriptions are switched off on this server'))}`;
  return `<h4 id="s-cals-h">${tr('Calendars')}</h4>
    ${hint(tr('Show events from Google Calendar, iCloud, Outlook or any CalDAV server next to your tasks: in the calendar, the timeline and on Today. Only you see them. Read-only, unless you allow writing for a CalDAV calendar (Edit).'))}
    <div class="members" id="s-cals">${/*html-ok*/ loadingHtml() /* 2.1077.0 (#5461): the shared block */}</div>
    <div class="row"><button class="btn sm pri" data-m="cal-add">${ic('plus', 's')} ${tr('Add calendar')}</button></div>
    ${feat('cal') ? `<div class="row"><label>${tr('Today')}</label>${chk('s-caltoday', S.settings.cal_today !== '0', tr('show today’s events at the top'))}</div>` : ''}
    <details class="shelp sdet"><summary>${tr('Where do I find the link?')}</summary><ul class="slist">
      <li>${tr('<b>Google Calendar:</b> on a computer, calendar.google.com > Settings > your calendar > Integrate calendar > “Secret address in iCal format”.')}</li>
      <li>${tr('<b>iCloud:</b> in the Calendar app, share the calendar as a public calendar and copy the link (webcal://…). Or add your whole account via CalDAV: server caldav.icloud.com, your Apple ID and an app-specific password (account.apple.com).')}</li>
      <li>${tr('<b>Outlook / Microsoft 365:</b> Settings > Calendar > Shared calendars > Publish a calendar > copy the ICS link.')}</li>
      <li>${tr('<b>Nextcloud, Radicale, Baïkal, Fastmail, mailbox.org …:</b> CalDAV account with the server address, your username and password (an app password where possible).')}</li>
      <li>${tr('Servers in your own network (for example 10.x.x.x or a VPN address) are blocked for safety until an admin allows the host under Settings > Server > Server > Advanced.')}</li></ul></details>`;
}
function calStatus(x) {
  if (x.status === 'error') return `<span class="calerr" role="alert">${esc(x.error_text || tr('Error'))}</span>` + (x.synced_at ? ' · ' + esc(tr('last synced {0}', relTime(x.synced_at))) : '');
  if (!x.synced_at) return esc(tr('Not synced yet'));
  return esc(tr('synced {0}', relTime(x.synced_at))) + ' · ' + esc(trn('{0} event', '{0} events', x.events)) + (x.truncated ? ' ' + esc(tr('(limit reached)')) : '');
}
async function calsDraw(md, j) {
  const box = $('#s-cals', md); if (!box) return;
  // 2.1077.0 (#5461): a failed fetch says so with "Try again" (offline: "You are offline"), not always "Only available online."
  if (!j) { try { j = await api('GET', '/api/calendars'); } catch { box.innerHTML = errorState({size: 'row', retry: () => { box.innerHTML = loadingHtml(); calsDraw(md); }}); return; } }
  box._j = j;
  if (typeof intr_st === 'function') intr_st('cals', j.subs.length > 0);  // 2.625.0 (#4489): the state on its folded row in Settings > Integrations
  S.calendars = {...(S.calendars || {}), enabled: j.enabled, subs: j.subs.filter(x => x.visible).length};
  calInvalidate();
  // 2.884.0 (#5469): cssColor() passes only a checked colour, the fallback is a fixed variable; the day list below is built from taskRow() (esc inside) - both html-ok
  box.innerHTML = j.subs.length ? j.subs.map(x => `<div class="calsub ${x.visible ? '' : 'off'}" data-cal="${x.id}" style="--cc:${/*html-ok*/ cssColor(x.color) || 'var(--muted)'}">
      <button class="cswatch" data-calact="color" title="${tr('Colour')}" aria-label="${tr('Colour')}"></button>
      <div class="calsub-main"><b>${esc(x.name)}</b><small class="muted">${esc(x.kind === 'caldav' ? `CalDAV · ${x.username}` : x.url_hint)} · ${calStatus(x)}${x.write && x.can_write ? ' · ' + esc(tr('writable')) : ''}</small></div>
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
// 2.559.0 (#4659): "Show" of a subscription switches at once (its row, the count, its events leave the shown range), the request
// runs behind it (evOpt, calevents.js); an error switches it back. The list is read again in the background afterwards.
function calVis(md, id, inp) {
  const on = inp.checked, box = $('#s-cals', md);
  const put = () => {
    const x = (box?._j?.subs || []).find(s => s.id === id), y = (S.cvxSubs || []).find(s => s.id === id), its = S.cal.items;
    const keep = on ? its : its.filter(e => e.own || String(e.sub) !== String(id));
    if (x?.visible === on && keep.length === its.length) return null;
    const o1 = x?.visible, o2 = y?.visible, c0 = S.calendars;
    const cnt = () => { if (box?._j) S.calendars = {...(S.calendars || {}), subs: box._j.subs.filter(s => s.visible).length}; };
    if (x) x.visible = on; if (y) y.visible = on; cnt(); S.cal.items = keep;
    box?.querySelector(`[data-cal="${id}"]`)?.classList.toggle('off', !on);
    return () => { if (x) x.visible = o1; if (y) y.visible = o2; S.calendars = c0; if (S.cal.items === keep) S.cal.items = its; box?.querySelector(`[data-cal="${id}"]`)?.classList.toggle('off', !o1); };
  };
  evOpt(put, () => api('PATCH', `/api/calendars/${id}`, {visible: on}), () => {}).then(() => { calInvalidate(); calsDraw(md); }, () => { inp.checked = !on; calsDraw(md); });
}
// 2.828.0 (#5464): ONE palette for every calendar (subscription and own: the colour pop and the edit dialog), each colour named
// in its aria-label (not its hex code); a swatch is 44 px under a finger (calendar.css .cpal)
const CAL_PAL = [['#6d8cff', N_('Blue')], ['#2dd4bf', N_('Teal')], ['#6ee7b7', N_('Mint')], ['#4ade80', N_('Green')], ['#f5b041', N_('Orange')],
  ['#f87171', N_('Red')], ['#f472b6', N_('Pink')], ['#c084fc', N_('Purple')], ['#94a3b8', N_('Grey')]];
function calPalHtml(cur, cls = '') {
  const k = String(cur || '').toLowerCase();
  return `<div class="cpal${/*html-ok*/ cls /* a constant class */}" role="group" aria-label="${esc(tr('Colour'))}">${CAL_PAL.map(([c, n]) => `<button type="button" data-c="${c}" style="--cc:${c}" class="${c === k ? 'on' : ''}" aria-pressed="${c === k ? 'true' : 'false'}" aria-label="${esc(tr(n))}" title="${esc(tr(n))}"></button>`).join('')}</div>`;
}
function calColorPop(anchor, _colors, cur, fn) {  // _colors: no longer used (the callers keep their argument)
  const p = openPop(anchor, calPalHtml(cur));
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
      // 2.800.0 (#5466): the toast takes it back (POST /api/calendars/restore with the answer's token, within 15 minutes)
      let j; try { j = await api('DELETE', `/api/calendars/${id}`); await calsDraw(md, j); } catch { return; /* api() showed it */ }
      calInvalidate(); await cvxCals(true).catch(() => {}); renderView();
      toast(tr('Calendar removed'), j?.undo ? async () => { let r; try { r = await api('POST', '/api/calendars/restore', {undo: j.undo}); } catch { return; } if (md.isConnected) await calsDraw(md, r); calInvalidate(); await cvxCals(true).catch(() => {}); renderView(); } : undefined);
    }
  });
  md.addEventListener('change', e => { const i = e.target.closest('[data-calact="vis"]'); if (i) calVis(md, +i.closest('[data-cal]').dataset.cal, i); });
  // allowed internal hosts (admins): saved when leaving the field, one history step. 2.380 G (#3389): one field per service
  md.addEventListener('change', async e => {
    const k = e.target.dataset?.allowp; if (!k) return;
    const from = S.about?.allow_hosts_by_purpose?.[k] ?? '', to = e.target.value;
    if (from.trim() === to.trim()) return;
    const put = async v => { const j = await api('PATCH', '/api/admin/settings', {allow_hosts_by_purpose: {[k]: v}}); S.about = {...S.about, ...j};
      const f = $(`[data-allowp="${k}"]`); if (f && f !== document.activeElement) f.value = j.allow_hosts_by_purpose?.[k] ?? ''; return {skipped: []}; };
    try { await put(to); } catch { return; }
    setSaved(histAdd({label: tr('Changed setting: {0}', tr('Allowed internal hosts')), sett: true, undo: () => put(from), redo: () => put(to)}));
  });
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
        $('#ca-cals', md).innerHTML = `<div class="shint keep">${tr('Which calendars should be shown?')}</div>` + found.map((c, i) => `<label class="wide"><input type="checkbox" data-ci="${i}" checked><span><i class="cevdot" style="--cc:${/*html-ok*/ cssColor(c.color) || 'var(--muted)'}"></i> ${esc(c.name)}</span></label>`).join('');
        b.textContent = tr('Add'); return;
      }
      const cals = found.filter((_, i) => $(`[data-ci="${i}"]`, md)?.checked);
      if (!cals.length) { showErr(tr('Select at least one calendar')); return; }
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
    <div class="row"><label>${tr('Colour')}</label>${/*html-ok*/ calPalHtml(color, ' inline') /* names via esc(tr()) */}</div>
    <div class="row"><label for="ce-int">${tr('Refresh')}</label><select id="ce-int"><option value="15">${tr('every 15 minutes')}</option><option value="60" ${x.interval === 60 ? 'selected' : ''}>${tr('every hour')}</option></select></div>
    ${x.kind === 'ics' ? `<div class="row"><label for="ce-url">${tr('Link')}</label><input id="ce-url" type="url" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="${trh('saved ({0}), empty = keep', x.url_hint)}"></div>`
    : `<div class="row"><label for="ce-user">${tr('Username')}</label><input id="ce-user" autocomplete="off" autocapitalize="off" value="${esc(x.username)}"></div>
      <div class="row"><label for="ce-pw">${tr('Password')}</label><input id="ce-pw" type="password" autocomplete="new-password" placeholder="${x.password_saved ? tr('saved, empty = keep') : ''}"></div>`}
    ${dvw_editRow(x)}
    <div class="calerr" role="alert" id="ce-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  dvw_editWire(md, x, done);  // 2.52.0 (#1128): "Allow writing"
  md.addEventListener('click', async e => {
    const cb = e.target.closest('[data-c]');
    if (cb) { color = cb.dataset.c; $$('.cpal [data-c]', md).forEach(b => { b.classList.toggle('on', b === cb); b.setAttribute('aria-pressed', String(b === cb)); }); return; }
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const body = {name: $('#ce-name', md).value.trim(), color, interval: +$('#ce-int', md).value};
    if (x.kind === 'ics' && $('#ce-url', md).value.trim()) body.url = $('#ce-url', md).value.trim();
    if (x.kind === 'caldav') { body.username = $('#ce-user', md).value.trim(); if ($('#ce-pw', md).value) body.password = $('#ce-pw', md).value; }
    if (x.kind === 'caldav' && body.username === x.username) delete body.username;
    b.disabled = true;
    try {
      // 2.564.0 D (#4701): against the version the dialog opened with; 409 = saved meantime elsewhere: the reason, the current state opens
      let r; try { r = await rawFetch('PATCH', `/api/calendars/${x.id}`, x.updated_at ? {...body, expect_updated_at: x.updated_at} : body); }
      catch (e2) { if (e2.status === 409 && e2.data?.calendar) { md.remove(); toast(e2.message); done && done(); calEditModal(e2.data.calendar, colors, done); return; } throw new Error(e2 instanceof Offline ? tr('Offline: only works again with a connection') : e2.message); }
      if (r.status === 'error' && (body.url || body.password || body.username)) { $('#ce-err', md).textContent = r.error_text; $('#ce-err', md).hidden = false; done && done(); return; }
      md.remove(); toast(tr('Saved')); done && done();
    } catch (err) { $('#ce-err', md).textContent = err.message; $('#ce-err', md).hidden = false; } finally { b.disabled = false; }
  });
}
function viewCal() {
  if (S.calMode === 'year') return cyr_view();  // 2.155.0 C (#2078): calyear.js
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
  msvvCalEnsure(start, addDays(start, 41));  // 2.73.0 C (#661): the other servers' events
  let cells = '';
  for (let i = 0; i < 42; i++) {
    const d = addDays(start, i);
    if (i === 35 && pd(d).getMonth() !== m - 1) break;
    const ts = byDay.get(d) || [];
    const out = pd(d).getMonth() !== m - 1;
    const evs = evOn ? cevOn(d).sort(cevSort) : [];
    const chips = [...evs.map(e => cevChip(e, d)), ...msvvCalChips(d), ...ts.map(t => `<div class="ev p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}${lp_cls(t)}" data-id="${t.id}"${lp_attr(t) /* 2.53.0 (#1426) */} draggable="${t.status || t.ghost || isTouch() || !canEdit(t) ? 'false' : 'true'}">${msGlyph(t)}${t.due_time ? `<span class="muted">${esc(fmtTimeLoc(t.due_time))}</span> ` : ''}${mdTitleNL(t.title)}</div>`)];
    cells += `<div class="cell ${out ? 'out' : ''} ${d === t0 ? 'today' : ''} ${d === S.calSel ? 'sel' : ''}" data-day="${d}">
      <span class="dn">${pd(d).getDate()}</span>
      ${chips.slice(0, 3).join('')}
      ${chips.length > 3 ? `<button type="button" class="more" data-calday="${/*html-ok*/ d /* a date */}">${esc(tr('{0} more', chips.length - 3))}</button>` : ''}
      <div class="dots">${evs.slice(0, 2).map(e => `<i class="ce" style="--cc:${cevColor(e)}"></i>`).join('')}${ts.filter(t => !t.status).slice(0, 4 - Math.min(2, evs.length)).map(t => `<i class="p${t.priority}${isMs(t) ? ' ms' : ''}"></i>`).join('')}</div>
    </div>`;
  }
  const sel = (byDay.get(S.calSel) || []).filter(t => !t.ghost);
  const selEv = evOn ? cevOn(S.calSel).sort(cevSort) : [];
  // 2.1077.0 (#5461): the day list says "nothing" only when the day has neither tasks nor events (events alone: no line)
  const selOther = msvvCalDay(S.calSel), none = !sel.length && !selEv.length && !selOther;
  return `${calBar(`${MON[m - 1]} ${y}`)}${/*html-ok*/ calEvState(start, addDays(start, 41)) /* calendar.js: the shared block */}
    <div class="cal calv">${wdOrder().map(i => `<div class="wd">${WD[i]}</div>`).join('')}${cells}</div>
    <div class="agenda"><h3>${dayLabel(S.calSel, true)}<span class="muted agdate"> ${fmtDate(S.calSel)}</span></h3>
      ${selEv.length ? `<div class="cevlist">${selEv.map(e => cevRow(e, S.calSel)).join('')}</div>` : ''}
      ${qaddBox()}
      ${/*html-ok*/ sel.length ? sel.map(t => taskRow(t, {showList: true, drag: false})).join('') : none ? `<div class="muted agnone">${tr('Nothing planned on this day.')}</div>` : ''}
      ${/*html-ok*/ selOther /* msvv.js */}
    </div>`;
}

function viewWeek() {
  // 2.290.0 A (#3144): 1..14 days (calendar.js calGridDays); while fingers spread them the count is fractional (the last column cut)
  const {days, nf} = calGridDays(), day = days.length === 1 && nf === 1, live = nf !== days.length;
  const map = calByDay(days[0], days[days.length - 1]);
  const evOn = calEvOn();
  if (evOn) ensureCalEv(days[0], days[days.length - 1]);
  msvvCalEnsure(days[0], days[days.length - 1]);  // 2.73.0 C (#661)
  const evsOf = d => evOn ? cevOn(d).sort(cevSort) : [];
  const t0 = today(), H = weekH();
  const chip = t => `<div class="ev p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}${lp_cls(t)}" data-id="${t.id}"${lp_attr(t) /* 2.53.0 (#1426) */} draggable="${t.status || t.ghost || isTouch() || !canEdit(t) ? 'false' : 'true'}">${msGlyph(t)}${mdTitleNL(t.title)}</div>`;
  const now = new Date(), nowTop = (now.getHours() * 60 + now.getMinutes()) / 60 * H;
  // 2.828.0 (#5463): where the hours start: the first timed entry of the days shown or 07:00, the earlier one (render.js cvw_scroll)
  let first = 7 * 60;
  // 2.828.0 (#5463): a block of two lines or more shows its time above a one-line title (cut with "…", never word stumps); a
  // short one keeps both in one line. Three lanes and more: on a phone strips without letters and one "+N" over the group
  // (calendar.css .wn3 / .wmore), a tap on it opens the day
  const two = Math.round(2.25 * remPx()), lane = it => `left:calc(${it.lane} * 100% / ${it.n});width:calc(100% / ${it.n} - 2px)`;
  const cols = days.map(d => {
    const lay = layoutDay((map.get(d) || []).filter(t => t.due_time), evsOf(d).filter(e => cevTimed(e, d)).map(e => ({c: e, ...cevMin(e, d)})));
    for (const it of lay) if (!it.c || it.c.d0 === d) first = Math.min(first, it.s);
    const blocks = lay.map(it => {
      const t = it.t, top = it.s / 60 * H, h = Math.max((it.e - it.s) / 60 * H, 20), cls = `${h >= two ? ' w2' : ''}${it.n >= 3 ? ' wn3' : ''}`;
      const more = it.n >= 3 && it.cl[0] === it ? `<button type="button" class="wmore" data-calday="${/*html-ok*/ d /* a date */}" style="top:${Math.round(top)}px" aria-label="${esc(trn('{0} event', '{0} events', it.cl.length))}" title="${esc(trn('{0} event', '{0} events', it.cl.length))}">+${it.cl.length}</button>` : '';
      if (it.c) return `<div class="wcev${/*html-ok*/ cls /* constant classes */}${ap_draftCls(it.c)}${cg_canDrag(it.c) ? ' cgok' : ''}" data-cev="${it.c.id}" role="button" tabindex="0" title="${esc(cevTitle(it.c))}" style="--cc:${cevColor(it.c)};top:${top}px;height:${h}px;${/*html-ok*/ lane(it) /* numbers */}">${/*html-ok*/ cevSubMark(it.c)}<b>${it.c.d0 === d ? fmtTimeAt(it.c.s) : '…'}</b> <span class="wct">${esc(cevTitle(it.c))}</span></div>${/*html-ok*/ more /* built above with esc() */}`;  // 2.52.0 (#1016): cgok = may be moved / resized (caldrag.js)
      return `<div class="wev${/*html-ok*/ cls /* constant classes */} p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}${lp_cls(t)}" data-id="${t.id}" draggable="${t.status || t.ghost || isTouch() || !canEdit(t) ? 'false' : 'true'}" style="${lp_sty(t) ? lp_sty(t) + ';' : '' /* 2.53.0 (#1426) */}top:${top}px;height:${h}px;${/*html-ok*/ lane(it) /* numbers */}">${msGlyph(t)}<b>${esc(fmtTimeLoc(t.due_time))}</b> <span class="wct">${mdTitleNL(t.title)}</span></div>${/*html-ok*/ more /* built above with esc() */}`;
    }).join('');
    return `<div class="wcol ${d === t0 ? 'today' : ''}" data-day="${d}">${blocks}${d === t0 ? `<i class="nowline" style="top:${nowTop}px"></i>` : ''}</div>`;
  }).join('');
  // 2.6.0 (K25): the week's own dates ("28. Sep – 4. Okt · KW 40"), short enough for one line on a phone; the month and
  // year of a week that spans two follow its middle (Thursday) where only one is shown
  const title = day ? fmtDay('long', pd(days[0])) : days.length === 7 && days[0] === weekStartOf(days[0]) ? weekTitle(days[0]) : calRangeTitle(days[0], days[days.length - 1]);
  CVW.start = {k: `${S.calMode}|${days[0]}|${days.length}`, m: first};
  // 2.1077.0 (#5461): nothing in the days shown = a quiet hint over the grid (the hours stay, for a tap that adds)
  const empty = !days.some(d => (map.get(d) || []).length || evsOf(d).length || msvvCalChips(d).length);
  const st = calEvState(days[0], days[days.length - 1], empty ? (day ? tr('Nothing planned on this day.') : tr('Nothing planned in these days.')) : '');
  return `${calBar(title)}${/*html-ok*/ st /* calendar.js: the shared block */}<div class="week calv ${day ? 'oneday' : ''}${live ? ' cgs-dz' : ''}${CAL_LIVE?.arm ? ' cgs-arm' : ''}" style="--cols:${days.length};--h:${H}px${live ? `;--nf:${nf}` : ''}">
    <div class="whead"><div></div>${days.map(d => `<div class="wh ${d === t0 ? 'today' : ''}" data-day="${d}"><span>${WD[pd(d).getDay()]}</span><b>${pd(d).getDate()}</b></div>`).join('')}</div>
    <div class="wallday"><div class="wlbl" title="${esc(tr('All day'))}">${tr('all day|short')}</div>${days.map(d => `<div class="wad" data-day="${d}">${evsOf(d).filter(e => !cevTimed(e, d)).map(e => cevChip(e, d)).join('')}${(map.get(d) || []).filter(t => !t.due_time).map(chip).join('')}${msvvCalChips(d).join('') /* 2.73.0 C (#661): other servers, in the all-day row */}</div>`).join('')}</div>
    <div class="wbody" id="wbody" tabindex="0" role="region" aria-label="${esc(tr('Hours of the week'))}"><div class="wgutter">${[...Array(24)].map((_, h) => `<div class="wtime" style="top:${h * H}px">${esc(fmtTimeLoc(pad(h) + ':00'))}</div>`).join('')}</div>${cols}</div></div>`;
}
// 2.828.0 (#5463): the hour grid's scroll position after a render (render.js): a new grid (other mode, days or their count)
// starts at CVW.start (the first entry or 07:00, the earlier); the same grid keeps where the person scrolled to, but follows a
// new start while nobody scrolled (the events arrive after the first drawing)
const CVW = {start: /** @type {{k: string, m: number}|null} */ (null), last: /** @type {{k: string, top: number}|null} */ (null), live: false};
function cvw_scroll(wb, keep) {
  const st = CVW.start, l = CVW.last, mode = k => k.split('|')[0];
  // fingers changing the number of days (calgest.js, CAL_LIVE) and the drawing after they let go keep the hours where they are
  const pinch = !!CAL_LIVE || (CVW.live && !!l && !!st && mode(l.k) === mode(st.k));
  CVW.live = !!CAL_LIVE;
  if (!st) { wb.scrollTop = keep ?? 7 * weekH() - 12; return; }
  if (keep != null && l && (pinch || (l.k === st.k && Math.abs(keep - l.top) > 2))) { wb.scrollTop = keep; if (pinch) CVW.last = {k: st.k, top: -1e9}; return; }
  wb.scrollTop = Math.max(0, st.m / 60 * weekH() - 12);  // 2.15.1 (#633): the hour's label in full, not cut at the top
  CVW.last = {k: st.k, top: wb.scrollTop};
}
// "+N" in the month and over a group of three lanes and more: the day view of that day (before the cell's / column's own click)
document.addEventListener('click', e => {
  const b = e.target instanceof Element ? e.target.closest('#view [data-calday]') : null; if (!b) return;
  e.stopPropagation(); e.preventDefault();
  S.calSel = /** @type {HTMLElement} */ (b).dataset.calday; S.calMode = 'day'; LS.set('calMode', 'day'); renderView();
}, true);
// 2.290.0 A (#3144): "28. Sep – 1. Okt" for a grid of other than a week's days (the week number only while it is one week)
function calRangeTitle(a, b) {
  const x = pd(a), z = pd(b), y = new Date().getFullYear(), other = x.getFullYear() !== y || z.getFullYear() !== y, w = isoWeek(a);
  return `${dayNoWd(x, other && x.getFullYear() !== z.getFullYear())} – ${dayNoWd(z, other)}${w === isoWeek(b) ? ` · ${tr('Week {0}', w)}` : ''}`;
}
function layoutDay(evs, extra = []) {  // side-by-side lanes for overlapping timed tasks (+ calendar events: {c, s, e})
  const items = evs.map(t => { const s = hm(t.due_time); return {t, s, e: s + Math.max(15, t.duration || 30)}; }).concat(extra).sort((a, b) => a.s - b.s || b.e - a.e);
  const out = []; let cluster = [], lanes = [], end = -1;
  const close = () => { const cl = cluster; cl.forEach(x => { x.n = lanes.length; x.cl = cl; }); out.push(...cl); cluster = []; lanes = []; end = -1; };  // 2.828.0 (#5463): + cl = its group
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
// 2.624.0 (#3946): + cal_folders_hidden (json list of my sidebar folder paths): every list in such a folder or a subfolder of
// it is off too, also lists added later (calendar.js cvxListOff); the switches sit under "Per project" (calevents.js cvf_lists).
// A list's own calendar view (S.lcal, lcal_has) always shows its tasks.
