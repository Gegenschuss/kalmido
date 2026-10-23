// 2.93.0 B (#1928): the logbook in the office (filled by part B). The third view "Logbook" of the tab "Travel expenses"
// (office_travel.js renders lbHtml()): vehicles (private car used for business -> mileage allowance | company car), the drives
// of a vehicle and year (newest first, cards on the phone), a drive by km or by odometer (start prefilled with the last end;
// gap / overlap = a warning), its change log, "take over into the travel expenses" (business drives, once), the year
// report with the rate per km and the CSV / PDF export. Every action one undo step (toast). Server: kalmido/office/logbook.py.
const LB = {base: null, drives: null, rep: null, loading: false, err: null, vid: null, view: 'drives', q: ''};
const lbYear = () => RK.year || String(new Date().getFullYear());
const lbReload = (all) => { if (all) LB.base = null; LB.drives = null; LB.rep = null; ofcDraw(); };
const lbVeh = id => (LB.base?.vehicles || []).find(v => v.id === id);
const lbKind = k => (LB.base?.kinds || []).find(x => x.key === k)?.label || k;
const lbClient = id => cdn_label((LB.base?.clients || []).find(c => c.id === id));  // 2.97.0 B (#1951)
const lbKm = v => v == null || v === '' ? '' : fmtNum(+v, +v % 1 ? 1 : 0);
const lbRoute = d => [d.start_place, d.dest].filter(Boolean).join(' – ');
const lbWarn = w => !w ? '' : w.kind === 'gap' ? tr('Gap of {0} km to the previous drive', lbKm(w.km)) : tr('Overlap of {0} km with the previous drive', lbKm(w.km));

async function lbLoad() {
  if (LB.loading) return;
  LB.loading = true;
  try {
    if (!LB.base) LB.base = await api('GET', '/api/office/vehicles');
    const act = LB.base.vehicles.filter(v => !v.archived);
    if (!lbVeh(LB.vid)) LB.vid = (act[0] || LB.base.vehicles[0])?.id || null;
    const q = `year=${lbYear()}` + (LB.vid ? `&vehicle_id=${LB.vid}` : '');
    if (LB.vid && (!LB.drives || LB.q !== q)) { const j = await api('GET', '/api/office/drives?' + q); LB.drives = j.drives; LB.closed = j.closed || []; LB.q = q; }  // 2.152.0 C (#2169): + closed
    if (LB.view === 'report' && (!LB.rep || LB.rep.year !== +lbYear())) LB.rep = await api('GET', `/api/office/logbook/report?year=${lbYear()}`);
    LB.err = null;
  } catch (x) { LB.err = x.message || tr('unknown'); }
  LB.loading = false;
  ofcDraw();
}

// ---- the view
function lbHtml() {
  if (LB.oid !== OFC.info?.org_id) Object.assign(LB, {oid: OFC.info?.org_id, base: null, drives: null, rep: null, err: null, vid: null});  // another office area
  if (LB.err) return `<div class="empty">${esc(LB.err)}</div>`;
  const q = `year=${lbYear()}` + (LB.vid ? `&vehicle_id=${LB.vid}` : '');
  const ready = LB.base && (LB.view === 'report' ? LB.rep && LB.rep.year === +lbYear() : !LB.vid || (LB.drives && LB.q === q));
  if (!ready) { if (!LB.loading) setTimeout(lbLoad, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const vs = LB.base.vehicles, act = vs.filter(v => !v.archived || v.id === LB.vid);
  const y0 = new Date().getFullYear(), years = [y0 + 1, y0, y0 - 1, y0 - 2, y0 - 3].map(String);
  const note = `<details class="lgb-note"><summary>${ic('alert', 's')}<span>${tr('Note on the logbook')}</span></summary><p class="muted">${esc(LB.base.note)}</p></details>`;
  if (!vs.length) return `<div class="empty nempty eact">${ic('car')}<span>${tr('No vehicle yet. Add the car you drive for business first.')}</span>
    <button class="btn pri" data-lgb="vnew">${ic('plus', 's')}<span>${tr('Add vehicle')}</span></button></div>` + note;
  const bar = `<div class="ofcbar lgb-bar"><select id="lgb-year" aria-label="${esc(tr('Year'))}">${years.map(y => `<option ${y === lbYear() ? 'selected' : ''}>${y}</option>`).join('')}</select>
    ${LB.view === 'drives' ? `<select id="lgb-veh" aria-label="${esc(tr('Vehicle'))}">${act.map(v => `<option value="${v.id}" ${v.id === LB.vid ? 'selected' : ''}>${esc(v.name + (v.plate ? ` (${v.plate})` : '') + (v.archived ? ` · ${tr('archived')}` : ''))}</option>`).join('')}</select>
    <button class="btn sm ghost" data-lgb="vedit" aria-label="${esc(tr('Edit vehicle'))}" title="${esc(tr('Edit vehicle'))}">${ic('edit', 's')}</button>` : ''}
    <div class="seg" role="group" aria-label="${esc(tr('Show'))}">${[['drives', tr('Drives')], ['report', tr('Year report')]].map(([k, n]) => `<button type="button" data-lgb="view" data-v="${k}" class="${LB.view === k ? 'on' : ''}" aria-pressed="${LB.view === k}">${n}</button>`).join('')}</div>
    <span class="spacer"></span><button class="btn sm" data-lgb="vnew">${ic('plus', 's')}<span>${tr('Vehicle')}</span></button>
    ${LB.view === 'drives' && LB.vid ? `<button class="btn sm" data-lgb="close">${ic('check', 's')}<span>${tr('Close month')}</span></button>` : ''}
    ${LB.view === 'drives' && LB.vid ? `<button class="btn sm pri" data-lgb="new">${ic('plus', 's')}<span>${tr('New drive')}</span></button>` : ''}</div>`;
  return bar + (LB.view === 'report' ? lbReportHtml() : lbListHtml()) + note;
}
function lbListHtml() {
  const ds = LB.drives || [], v = lbVeh(LB.vid);
  if (!ds.length) return `<div class="empty nempty">${ic('car')}<span>${tr('No drives in this year.')}</span></div>`;
  const sum = ds.reduce((a, d) => a + (+d.km || 0), 0);
  return `<p class="muted lgb-sum">${esc([v ? (v.kind === 'private' ? tr('Private car used for business') : tr('Company car')) : '', trn('{0} drive', '{0} drives', ds.length), tr('{0} km', lbKm(sum))].filter(Boolean).join(' · '))}</p>
    <ul class="ofclist lgb-list" role="list">${ds.map(d => `<li><button type="button" class="ofcrow lgb-row" data-lgb="open" data-id="${d.id}"><span class="ofcn"><b>${esc(lbRoute(d) || d.purpose || tr('Drive'))}</b>
    <small class="muted">${esc([fmtDateLoc(d.day), d.purpose, lbClient(d.client_id), d.project, lbKind(d.kind), d.driver].filter(Boolean).join(' · '))}</small>
    ${d.odo_start != null || d.odo_end != null ? `<small class="muted">${esc(tr('Odometer {0} – {1}', lbKm(d.odo_start) || '?', lbKm(d.odo_end) || '?'))}</small>` : ''}
    ${d.warn ? `<small class="lgb-warn">${ic('alert', 's')} ${esc(lbWarn(d.warn))}</small>` : ''}</span>
    ${d.trip_id ? `<span class="rotag">${tr('In travel expenses')}</span>` : ''}${lbFixTag(d)}<span class="lgb-km">${esc(tr('{0} km', lbKm(d.km)))}</span></button></li>`).join('')}</ul>`;
}
function lbReportHtml() {
  const r = LB.rep, y = lbYear();
  const rate = `<div class="row lgb-rate"><label for="lgb-rate">${tr('Mileage allowance per business km in {0}', r.year)}</label><input id="lgb-rate" inputmode="decimal" class="numin" value="${esc(fmtNum(+r.km_rate, 2))}">
    <button class="btn sm" data-lgb="rate">${tr('Save')}</button></div>`;
  const cards = r.vehicles.map(v => `<div class="lgb-card"><h4>${esc(v.name)}${v.plate ? ` <span class="muted">${esc(v.plate)}</span>` : ''}</h4>
    <p class="muted">${esc(v.kind === 'private' ? tr('Private car used for business') : tr('Company car'))} · ${esc(trn('{0} drive', '{0} drives', v.drives))}</p>
    <dl class="lgb-dl"><dt>${tr('km total')}</dt><dd>${lbKm(v.km_total)}</dd><dt>${tr('Business')}</dt><dd>${lbKm(v.km_business)}</dd>
    <dt>${tr('Private|drive')}</dt><dd>${lbKm(v.km_private)}</dd><dt>${tr('Home - workplace')}</dt><dd>${lbKm(v.km_commute)}</dd>
    <dt>${tr('Business share')}</dt><dd>${v.business_pct} %</dd>${v.kind === 'private' ? `<dt>${tr('Mileage allowance')}</dt><dd><b>${ofcMoney(v.allowance)}</b></dd>` : ''}</dl></div>`).join('');
  return `<div class="ofcbar"><b>${tr('Year report')} ${esc(y)}</b><span class="spacer"></span>
    <a class="btn sm ghost" href="/api/office/logbook.csv?year=${y}" download>${ic('download', 's')}<span>CSV</span></a><a class="btn sm ghost" href="/api/office/logbook.pdf?year=${y}" download>${ic('download', 's')}<span>PDF</span></a></div>`
    + (cards ? `<div class="lgb-cards">${cards}</div>` : `<div class="empty nempty">${tr('No drives in this year.')}</div>`)
    + `<p class="lgb-total">${tr('Mileage allowance')} ${esc(y)}: <b>${ofcMoney(r.allowance)}</b></p><p class="muted ofchint">${tr('Goes into the income/expense statement as its own expense line.')}</p>` + rate;
}

// ---- dialogs
function lbVehModal(v) {
  const md = modal(`<h3>${v ? tr('Edit vehicle') : tr('Add vehicle')}</h3>
    ${ofcRowF('lgb-vname', tr('Name'), ofcIn('lgb-vname', v?.name, {max: 120, ph: tr('e.g. Golf')}))}
    ${ofcRowF('lgb-vplate', tr('Plate'), ofcIn('lgb-vplate', v?.plate, {max: 30}))}
    ${ofcRowF('lgb-vkind', tr('Kind'), ofcSel('lgb-vkind', v?.kind || 'private', [['private', tr('Private car used for business (mileage allowance)')], ['company', tr('Company car (costs through receipts)')]]))}
    ${ofcRowF('lgb-vodo', tr('Odometer at the start'), ofcIn('lgb-vodo', v?.odo_start != null ? lbKm(v.odo_start) : '', {num: true, ph: tr('optional')}))}
    <div class="aerr" role="alert"></div>
    <div class="foot">${v ? `<button class="btn" data-m="arch">${v.archived ? tr('Restore') : tr('Archive')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${v ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'arch') {
        const on = v.archived ? 0 : 1;
        await api('PATCH', `/api/office/vehicles/${v.id}`, {archived: on}); md.remove(); lbReload(true);
        toast(on ? tr('Archived') : tr('Restored'), async () => { await api('PATCH', `/api/office/vehicles/${v.id}`, {archived: on ? 0 : 1}); lbReload(true); });
        return;
      }
      const val = id => $(id, md)?.value ?? '';
      const body = {name: val('#lgb-vname'), plate: val('#lgb-vplate'), kind: val('#lgb-vkind'), odo_start: ofcNum(val('#lgb-vodo'))};
      if (v) {
        const old = {name: v.name, plate: v.plate, kind: v.kind, odo_start: v.odo_start};
        await api('PATCH', `/api/office/vehicles/${v.id}`, body); md.remove(); lbReload(true);
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/vehicles/${v.id}`, old); lbReload(true); });
      } else {
        const j = await api('POST', '/api/office/vehicles', body); md.remove(); LB.vid = j.id; LB.view = 'drives'; lbReload(true);
        toast(tr('Added'), async () => { await api('PATCH', `/api/office/vehicles/${j.id}`, {archived: 1}); lbReload(true); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
// 2.152.0 C (#2169): a closed drive (a week after it, or its month closed) is read-only; the fix is a new entry with a reason
const lbFixTag = d => d.corrected_by ? `<span class="rotag">${tr('Corrected')}</span>` : d.corrects_id ? `<span class="rotag">${tr('Correction')}</span>` : '';
const lbLockText = d => d.corrected_by ? tr('Corrected by entry {0}', d.corrected_by) : d.locked === 'month' ? tr('This month is closed in the logbook: correct the drive with a new entry.')
  : tr('This drive is closed (a week after the drive): correct it with a new entry.');
function lbDriveModal(d, fix) {
  // fix = the closed drive a new entry corrects (prefilled with its values; the reason is required)
  const ro = !!(d && (d.locked || d.corrected_by)), src = d || fix;
  const base = LB.base, v = lbVeh(src?.vehicle_id ?? LB.vid);
  const odo0 = src ? src.odo_start : v?.last_odo;
  const md = modal(`<h3>${fix ? tr('Correct drive') : ro ? tr('Drive') : d ? tr('Edit drive') : tr('New drive')}</h3>
    ${ro ? `<p class="lgb-lock">${ic('lock', 's')}<span>${esc(lbLockText(d))}</span></p>` : ''}
    ${src?.corrects_id && !fix ? `<p class="muted lgb-fixof">${esc(tr('Correction of entry {0}: {1}', src.corrects_id, src.correct_note || ''))}</p>` : ''}
    <div class="row"><label id="lgb-dl">${tr('Date')}</label>${dateIn('lgb-day', src?.day || new Date().toISOString().slice(0, 10), {label: tr('Date'), clear: false})}</div>
    ${ofcRowF('lgb-veh2', tr('Vehicle'), ofcSel('lgb-veh2', v?.id || '', base.vehicles.filter(x => !x.archived || x.id === v?.id).map(x => [x.id, x.name])))}
    ${ofcRowF('lgb-start', tr('Start'), ofcIn('lgb-start', src?.start_place, {max: 300}))}
    ${ofcRowF('lgb-dest', tr('Destination'), ofcIn('lgb-dest', src?.dest, {max: 300}))}
    ${ofcRowF('lgb-purpose', tr('Purpose'), ofcIn('lgb-purpose', src?.purpose, {max: 500, ph: tr('e.g. shoot, client meeting')}))}
    <div class="lgb-odo">${ofcRowF('lgb-o0', tr('Odometer start'), ofcIn('lgb-o0', odo0 != null ? lbKm(odo0) : '', {num: true}))}
    ${ofcRowF('lgb-o1', tr('Odometer end'), ofcIn('lgb-o1', src?.odo_end != null ? lbKm(src.odo_end) : '', {num: true}))}</div>
    ${ofcRowF('lgb-km', tr('Kilometres'), ofcIn('lgb-km', src ? lbKm(src.km) : '', {num: true, ph: tr('from the odometer')}))}
    ${d?.trip_hint ? `<p class="lgb-warn lgb-trip">${ic('alert', 's')} ${esc(d.trip_hint)}</p>` : ''}
    <p class="lgb-warn" id="lgb-w" aria-live="polite">${d?.warn ? `${ic('alert', 's')} ${esc(lbWarn(d.warn))}` : ''}</p>
    ${ofcRowF('lgb-kind', tr('Kind'), ofcSel('lgb-kind', src?.kind || 'business', base.kinds.map(k => [k.key, k.label])))}
    ${ofcRowF('lgb-client', tr('Client'), ofcSel('lgb-client', src?.client_id || '', base.clients.map(c => [c.id, cdn_label(c)]), tr('none')))}
    ${ofcRowF('lgb-project', tr('Project'), ofcIn('lgb-project', src?.project, {list: 'lgb-projs'}))}<datalist id="lgb-projs">${base.projects.map(p => `<option value="${esc(p)}">`).join('')}</datalist>
    ${ofcRowF('lgb-driver', tr('Driver'), ofcSel('lgb-driver', src?.user_id || base.me, base.people.map(p => [p.id, p.name])))}
    ${fix ? ofcRowF('lgb-fixnote', tr('Reason for the correction'), ofcIn('lgb-fixnote', '', {max: 500})) : ''}
    ${d ? `<details class="lgb-hist" open><summary>${ic('clock', 's')}<span>${tr('History')}</span></summary><ol class="lgb-hlist"><li class="muted">${tr('Loading…')}</li></ol></details>` : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot lgb-foot">${d ? `${ro ? '' : `<button class="btn danger" data-m="del">${tr('Delete')}</button>`}<button class="btn" data-m="log">${ic('clock', 's')}<span>${tr('History')}</span></button>` : ''}
    ${d && d.kind === 'business' ? `<button class="btn" data-m="trip">${ic('plane', 's')}<span>${d.trip_id ? tr('Open trip') : tr('Take over into travel expenses')}</span></button>` : ''}
    <span class="spacer"></span><button class="btn" data-m="close">${ro ? tr('Close') : tr('Cancel')}</button>${ro ? (d.corrected_by ? '' : `<button class="btn pri" data-m="fix">${tr('Correct|verb')}</button>`)
      : `<button class="btn pri" data-m="save">${d && !fix ? tr('Save') : tr('Add')}</button>`}</div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  if (ro) md.querySelectorAll('input, select, textarea').forEach(x => { if (!x.closest('.lgb-hist')) x.disabled = true; });
  if (d) lbHistInto(md, d);
  const val = id => $(id, md)?.value ?? '';
  // km follows the odometer while it was not typed by hand; the end below the start is shown at once
  let kmHand = !!d && d.odo_start == null;
  const sync = () => {
    const a = ofcNum(val('#lgb-o0')), z = ofcNum(val('#lgb-o1')), w = $('#lgb-w', md);
    if (a != null && z != null && z >= a && !kmHand) $('#lgb-km', md).value = lbKm(Math.round((z - a) * 10) / 10);
    if (w && a != null && z != null && z < a) w.textContent = tr('The odometer at the end is below the start');
    else if (w && w.dataset.t !== '1') w.textContent = '';
  };
  if (d?.warn) $('#lgb-w', md).dataset.t = '1';
  md.addEventListener('input', e => { if (e.target.id === 'lgb-km') kmHand = val('#lgb-km') !== ''; if (e.target.id === 'lgb-o0' || e.target.id === 'lgb-o1') sync(); });
  md.addEventListener('change', e => { if (e.target.id === 'lgb-veh2' && !d) { const nv = lbVeh(+e.target.value); $('#lgb-o0', md).value = nv?.last_odo != null ? lbKm(nv.last_odo) : ''; sync(); } });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'log') { lbLogModal(d); return; }
      if (b.dataset.m === 'fix') { md.remove(); lbDriveModal(null, d); return; }
      if (b.dataset.m === 'trip') {
        const j = await api('POST', `/api/office/drives/${d.id}/trip`); md.remove();
        if (!j.existing) toast(tr('Taken over into the travel expenses'), async () => { await api('DELETE', `/api/office/trips/${j.trip.id}`); lbReload(); RK.data = null; });
        RK.year = (j.trip.date_from || '').slice(0, 4); RK.view = 'trips'; RK.open = j.trip.id; LB.drives = null; rk_reload();
        return;
      }
      if (b.dataset.m === 'del') {
        await api('DELETE', `/api/office/drives/${d.id}`); md.remove(); lbReload(true);
        toast(tr('Deleted'), async () => { await api('POST', `/api/office/drives/${d.id}/restore`); lbReload(true); });
        return;
      }
      const km = val('#lgb-km').trim();
      const body = {day: val('#lgb-day'), vehicle_id: +val('#lgb-veh2') || null, start_place: val('#lgb-start'), dest: val('#lgb-dest'), purpose: val('#lgb-purpose'),
        odo_start: ofcNum(val('#lgb-o0')), odo_end: ofcNum(val('#lgb-o1')), km: km === '' ? null : ofcNum(km), kind: val('#lgb-kind'),
        client_id: +val('#lgb-client') || null, project: val('#lgb-project'), user_id: +val('#lgb-driver') || null};
      if (d) {
        const old = {day: d.day, vehicle_id: d.vehicle_id, start_place: d.start_place, dest: d.dest, purpose: d.purpose, odo_start: d.odo_start, odo_end: d.odo_end,
          km: d.km, kind: d.kind, client_id: d.client_id, project: d.project, user_id: d.user_id};
        const j = await api('PATCH', `/api/office/drives/${d.id}`, body); md.remove(); lbReload(true);
        // 2.93.0 B (#1928 review): a taken-over drive with other km -> the trip keeps the old km, said once here
        toast(j.trip_hint || (j.warn ? lbWarn(j.warn) : tr('Saved')), async () => { await api('PATCH', `/api/office/drives/${d.id}`, old); lbReload(true); });
      } else {
        if (fix) { body.corrects_id = fix.id; body.correct_note = val('#lgb-fixnote').trim(); if (!body.correct_note) { $('.aerr', md).textContent = tr('A correction needs its reason'); return; } }
        const j = await api('POST', '/api/office/drives', body); md.remove(); LB.vid = j.vehicle_id || LB.vid; RK.year = j.day.slice(0, 4); lbReload(true);
        toast(j.warn ? lbWarn(j.warn) : tr('Added'), async () => { await api('DELETE', `/api/office/drives/${j.id}`); lbReload(true); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
const LB_ACT = {create: N_('Created'), change: N_('Changed'), delete: N_('Deleted'), restore: N_('Restored'), trip: N_('Taken over into the travel expenses'),  // 2.93.0 B (#1928 review): trip
  corrected: N_('Corrected')};  // 2.152.0 C (#2169)
const LB_FLD = {vehicle_id: N_('Vehicle'), user_id: N_('Driver'), day: N_('Date'), start_place: N_('Start'), dest: N_('Destination'), purpose: N_('Purpose'),
  km: N_('Kilometres'), odo_start: N_('Odometer start'), odo_end: N_('Odometer end'), kind: N_('Kind'), client_id: N_('Client'), project: N_('Project'),
  by: N_('Corrected by'), note: N_('Reason')};  // 2.152.0 C (#2169): the "corrected" entry
function lbPrev(p) {
  return Object.entries(p || {}).map(([k, v]) => {
    const s = k === 'vehicle_id' ? lbVeh(v)?.name || v : k === 'client_id' ? lbClient(v) || v : k === 'kind' ? lbKind(v) : k === 'user_id' ? (LB.base.people.find(x => x.id === v)?.name || v)
      : k === 'day' ? (v ? fmtDateLoc(v) : '') : ['km', 'odo_start', 'odo_end'].includes(k) ? lbKm(v) : v;
    return `${tr(LB_FLD[k] || k)}: ${s ?? ''}`;
  }).join(' · ');
}
// 2.152.0 C (#2169): the change log right in the drive dialog (who, when, the values before) -- also for the tax office
async function lbHistInto(md, d) {
  const ol = $('.lgb-hlist', md); if (!ol) return;
  let rows;
  try { rows = (await api('GET', `/api/office/drives/${d.id}/log`)).log; } catch (x) { ol.innerHTML = `<li class="muted">${esc(x.message || '')}</li>`; return; }
  ol.innerHTML = rows.slice().reverse().map(r => `<li><b>${esc(tr(LB_ACT[r.action] || r.action))}</b> <span class="muted">${esc(new Date(r.at).toLocaleString(LOCALE(), {dateStyle: 'medium', timeStyle: 'short'}))} · ${esc(r.by)}</span>
    ${Object.keys(r.prev || {}).length ? `<small>${esc((r.action === 'create' || r.action === 'corrected' ? '' : tr('Before') + ': ') + lbPrev(r.prev))}</small>` : ''}</li>`).join('');
}
async function lbCloseModal() {
  const v = lbVeh(LB.vid), y = lbYear(), now = new Date().toISOString().slice(0, 7);
  const shut = new Set((LB.closed || []).filter(x => !x.vehicle_id || x.vehicle_id === LB.vid).map(x => x.month));
  // 2.186.0 B (#2601): only past months (closing is for good, the running month stays open)
  const all = Array.from({length: 12}, (_, i) => `${y}-${String(i + 1).padStart(2, '0')}`).filter(m => m < now);
  const ms = all.filter(m => !shut.has(m));
  if (!ms.length) { toast(all.length ? tr('Every month of this year is closed already.') : tr('Only past months can be closed.')); return; }
  const md = modal(`<h3>${tr('Close month')}</h3><p class="muted">${esc(tr('Drives of a closed month can no longer be changed or deleted, only corrected by a new entry with a reason. This cannot be undone.') + ' ' + tr('Only past months can be closed.'))}</p>
    ${ofcRowF('lgb-cm', tr('Month'), ofcSel('lgb-cm', ms[ms.length - 1], ms.map(m => [m, new Date(m + '-15').toLocaleDateString(LOCALE(), {month: 'long', year: 'numeric'})])))}
    ${ofcRowF('lgb-cv', tr('Vehicle'), ofcSel('lgb-cv', String(LB.vid || ''), [[String(LB.vid || ''), v?.name || ''], ['all', tr('All vehicles')]]))}
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${tr('Close month')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    const cv = $('#lgb-cv', md).value;
    try { const j = await api('POST', '/api/office/logbook/close', {month: $('#lgb-cm', md).value, vehicle_id: cv === 'all' ? null : +cv || null}); LB.closed = j.closed; md.remove(); lbReload(); toast(tr('Month closed')); }
    catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
async function lbLogModal(d) {
  let rows;
  try { rows = (await api('GET', `/api/office/drives/${d.id}/log`)).log; } catch (x) { toast(x.message || ''); return; }
  const md = modal(`<h3>${tr('History')}</h3><p class="muted">${esc([fmtDateLoc(d.day), lbRoute(d)].filter(Boolean).join(' · '))}</p>
    <ol class="lgb-log">${rows.slice().reverse().map(r => `<li><b>${esc(tr(LB_ACT[r.action] || r.action))}</b> <span class="muted">${esc(new Date(r.at).toLocaleString(LOCALE(), {dateStyle: 'medium', timeStyle: 'short'}))} · ${esc(r.by)}</span>
      ${Object.keys(r.prev || {}).length ? `<small>${esc((r.action === 'create' ? '' : tr('Before') + ': ') + lbPrev(r.prev))}</small>` : ''}</li>`).join('')}</ol>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) close(); });
}

// ---- events
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-lgb]'); if (!b || b.tagName === 'INPUT') return;
  const a = b.dataset.lgb;
  if (a === 'new') lbDriveModal(null);
  else if (a === 'open') { const d = (LB.drives || []).find(x => x.id === +b.dataset.id); if (d) lbDriveModal(d); }
  else if (a === 'vnew') lbVehModal(null);
  else if (a === 'vedit') { const v = lbVeh(LB.vid); if (v) lbVehModal(v); }
  else if (a === 'view') { LB.view = b.dataset.v; ofcDraw(); }
  else if (a === 'rate') lbSaveRate();
  else if (a === 'close') lbCloseModal();  // 2.152.0 C (#2169)
  else return;
  e.preventDefault();
});
document.addEventListener('change', e => {
  const x = e.target;
  if (x.id === 'lgb-year') { RK.year = x.value; RK.data = null; lbReload(); }
  else if (x.id === 'lgb-veh') { LB.vid = +x.value; lbReload(); }
});
async function lbSaveRate() {
  const el = $('#lgb-rate'), n = ofcNum(el?.value), old = LB.rep?.km_rate, year = LB.rep?.year || +lbYear();  // 2.93.0 B (#1928 review): rate per year
  if (n == null || n < 0) { toast(tr('Invalid value: {0}', tr('Mileage allowance per business km'))); return; }
  try {
    await api('PUT', '/api/office/logbook/settings', {km_rate: String(n), year}); lbReload(true);
    toast(tr('Saved'), async () => { await api('PUT', '/api/office/logbook/settings', {km_rate: old, year}); lbReload(true); });
  } catch (x) { toast(x.message || ''); }
}
