/* Kalmido web client: the calendar views month / week / day and Settings > Integrations > Calendars (module "calendar",
   loaded on demand with caldrag.js, 2.65.0 #1823; moved unchanged from calendar.js, which keeps the events' data, the
   kanban board, the agenda's bar and what other views show of the calendar).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';
// Settings > Integrations > Calendars (own requests, applied at once) + the admin allow-list (Settings > Users)
function calsHtml(chk, hint) {
  if (!S.calendars?.enabled) return `<h4 id="s-cals-h">${tr('Calendars')}</h4>${hintK(tr('Calendar subscriptions are turned off on this server'))}`;
  return `<h4 id="s-cals-h">${tr('Calendars')}</h4>
    ${hint(tr('Show events from Google Calendar, iCloud, Outlook or any CalDAV server next to your tasks: in the calendar, the timeline and on Today. Only you see them. Read-only, unless you allow writing for a CalDAV calendar (Edit).'))}
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
    ${dvw_editRow(x)}
    <div class="calerr" role="alert" id="ce-err" hidden></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  dvw_editWire(md, x, done);  // 2.52.0 (#1128): "Allow writing"
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
  msvvCalEnsure(start, addDays(start, 41));  // 2.73.0 C (#661): the other servers' events
  let cells = '';
  for (let i = 0; i < 42; i++) {
    const d = addDays(start, i);
    if (i === 35 && pd(d).getMonth() !== m - 1) break;
    const ts = byDay.get(d) || [];
    const out = pd(d).getMonth() !== m - 1;
    const evs = evOn ? cevOn(d).sort(cevSort) : [];
    const chips = [...evs.map(e => cevChip(e, d)), ...msvvCalChips(d), ...ts.map(t => `<div class="ev p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}${lp_cls(t)}" data-id="${t.id}"${lp_attr(t) /* 2.53.0 (#1426) */} draggable="${t.status || t.ghost || isMobile() || !canEdit(t) ? 'false' : 'true'}">${msGlyph(t)}${t.due_time ? `<span class="muted">${t.due_time}</span> ` : ''}${mdTitleNL(t.title)}</div>`)];
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
      ${msvvCalDay(S.calSel)}
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
  const chip = t => `<div class="ev p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}${lp_cls(t)}" data-id="${t.id}"${lp_attr(t) /* 2.53.0 (#1426) */} draggable="${t.status || t.ghost || isMobile() || !canEdit(t) ? 'false' : 'true'}">${msGlyph(t)}${mdTitleNL(t.title)}</div>`;
  const now = new Date(), nowTop = (now.getHours() * 60 + now.getMinutes()) / 60 * H;
  const cols = days.map(d => {
    const blocks = layoutDay((map.get(d) || []).filter(t => t.due_time), evsOf(d).filter(e => cevTimed(e, d)).map(e => ({c: e, ...cevMin(e, d)}))).map(it => {
      const t = it.t, top = it.s / 60 * H, h = Math.max((it.e - it.s) / 60 * H, 20);
      if (it.c) return `<div class="wcev${ap_draftCls(it.c)}${cg_canDrag(it.c) ? ' cgok' : ''}" data-cev="${it.c.id}" style="--cc:${cevColor(it.c)};top:${top}px;height:${h}px;left:calc(${it.lane} * 100% / ${it.n});width:calc(100% / ${it.n} - 2px)"><b>${it.c.d0 === d ? fmtHM(it.c.s) : '…'}</b> ${esc(cevTitle(it.c))}</div>`;  // 2.52.0 (#1016): cgok = may be moved / resized (caldrag.js)
      return `<div class="wev p${t.priority} ${t.status ? 'done' : ''} ${t.ghost ? 'ghost' : ''} ${isMs(t) ? 'ms' : ''}${lp_cls(t)}" data-id="${t.id}" draggable="${t.status || t.ghost || isMobile() || !canEdit(t) ? 'false' : 'true'}" style="${lp_sty(t) ? lp_sty(t) + ';' : '' /* 2.53.0 (#1426) */}top:${top}px;height:${h}px;left:calc(${it.lane} * 100% / ${it.n});width:calc(100% / ${it.n} - 2px)">${msGlyph(t)}<b>${t.due_time}</b> ${mdTitleNL(t.title)}</div>`;
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
