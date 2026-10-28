/* Kalmido web client: 2.94.0 B (#1929) the booking page ("Terminbuchung"): customers book an appointment on a public page
   without an account (/s/b/<address>, server-rendered). Here the person sets it up: on / off, the link, title and text, the
   calendar the bookings go into, the office area that gets a lead per booking, the weekly hours, the appointment types and
   the list of bookings (cancel). Opened from the Calendars dialog (calevents.js). Lazy module "calendar" (lazyload.js). */
'use strict';

const APB = {data: null, types: [], bookings: [], md: null};
const APB_DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];

async function apbLoad() {
  const [p, t, b] = await Promise.all([api('GET', '/api/appt/page'), api('GET', '/api/appt/types'), api('GET', '/api/appt/bookings')]);
  APB.data = p; APB.types = t.types || []; APB.bookings = b.bookings || [];
}
async function apbOpen() {
  try { await apbLoad(); } catch { return; }
  APB.md?.remove();
  const md = APB.md = modal(`<div class="lhdr"><h3>${ic('cal', 's')} ${tr('Booking page')}</h3><span class="spacer"></span><button class="iconbtn" data-apb="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div><div class="apb-body"></div>`);
  md.classList.add('apb-dlg');
  apbDraw();
  md.addEventListener('click', apbClick);
  md.addEventListener('change', e => { if (e.target.id === 'apb-on') apbToggle(e.target); if (e.target.matches('[data-apbday]')) apbDayRow(e.target); });
}
function apbReload() { return apbLoad().then(apbDraw).catch(() => {}); }

const apbWhen = iso => { const d = new Date(iso); return `${WDL[d.getDay()]}, ${fmtStamp(d)}`; };
// 2.94.1 (#1929): the app's own time picker (ux1: no native time inputs); the hidden input keeps data-apbhm
const apbHM = (v, n) => timeIn('apb-hm-' + n, v || '', {label: n.endsWith('a') ? tr('From') : tr('To'), empty: '--:--', attrs: `data-apbhm="${n}"`});
function apbDayHtml(d, rows) {
  const on = rows.length > 0, r1 = rows[0] || ['09:00', '17:00'], r2 = rows[1];
  const name = WDL[(APB_DAYS.indexOf(d) + 1) % 7];
  return `<div class="apb-day ${on ? '' : 'off'}" data-day="${d}"><label class="chkl"><input type="checkbox" data-apbday="${d}" ${on ? 'checked' : ''}><span>${esc(name)}</span></label>
    <span class="apb-hm">${apbHM(r1[0], d + '1a')}<span aria-hidden="true">–</span>${apbHM(r1[1], d + '1b')}</span>
    <span class="apb-hm apb-hm2 ${r2 ? '' : 'hidden'}">${apbHM(r2?.[0] || '', d + '2a')}<span aria-hidden="true">–</span>${apbHM(r2?.[1] || '', d + '2b')}</span>
    <button type="button" class="iconbtn" data-apb="${r2 ? 'rm2' : 'add2'}" data-d="${d}" aria-label="${esc(r2 ? tr('Remove the second time') : tr('Add a second time'))}" title="${esc(r2 ? tr('Remove the second time') : tr('Add a second time'))}">${ic(r2 ? 'x' : 'plus', 's')}</button></div>`;
}
function apbDayRow(cb) { cb.closest('.apb-day')?.classList.toggle('off', !cb.checked); }

function apbDraw() {
  const md = APB.md, D = APB.data; if (!md || !D) return;
  const p = D.page, el = $('.apb-body', md);
  const warn = !D.mail_ok ? tr('This server sends no e-mail: the booking page cannot be switched on') : !D.links_ok ? tr('Public links are turned off on this server') : '';
  const link = D.exists ? `<div class="apb-link"><code>${esc(p.url)}</code><button class="btn sm" data-apb="copy">${ic('copy', 's')} ${tr('Copy link')}</button><a class="btn sm" href="${esc(p.url)}" target="_blank" rel="noopener">${ic('link', 's')} ${tr('Open')}</a></div>` : '';
  const cals = D.calendars.map(c => `<option value="${c.id}" ${c.id === p.cal_id ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
  const offs = D.offices.map(o => `<option value="${o.personal ? 'personal' : o.id}" ${p.office_org_id && (o.id === p.office_org_id) ? 'selected' : ''}>${esc(o.name)}</option>`).join('');
  const types = APB.types.length ? `<ul class="apb-list">${APB.types.map(t => `<li class="${t.active ? '' : 'off'}"><button class="apb-main" data-apbtype="${t.id}"><b>${esc(t.name)}</b><span class="muted">${esc(apbTypeSub(t))}</span></button>
      <button class="iconbtn" data-apbdel="${t.id}" aria-label="${esc(tr('Delete {0}', t.name))}" title="${esc(tr('Delete'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>`
    : `<p class="muted">${tr('No appointment type yet. Customers choose one of them first.')}</p>`;
  const now = Date.now();
  const bk = APB.bookings.filter(b => new Date(b.end).getTime() >= now).slice(0, 100);
  const books = bk.length ? `<ul class="apb-list apb-books">${bk.map(b => `<li class="${b.status}"><div class="apb-main"><b>${esc(apbWhen(b.start))}</b>
      <span>${esc(b.type_name || '')} · ${esc(b.name)}</span><span class="muted">${esc(b.email)}${b.phone ? ' · ' + esc(b.phone) : ''}</span>
      ${b.status !== 'confirmed' ? `<span class="apb-st">${esc(b.status === 'pending' ? tr('Waiting for the customer to confirm') : b.cancelled_by === 'guest' ? tr('Cancelled by the customer') : tr('Cancelled'))}</span>` : ''}</div>
      ${b.status === 'confirmed' || b.status === 'pending' ? `<button class="btn sm" data-apbcancel="${b.id}">${tr('Call off…')}</button>` : ''}</li>`).join('')}</ul>`
    : `<p class="muted">${tr('No bookings yet.')}</p>`;
  el.innerHTML = `${warn ? `<p class="apb-warn" role="note">${esc(warn)}</p>` : ''}
    <label class="mmain apb-onrow"><span class="swc"><input type="checkbox" id="apb-on" ${p.enabled ? 'checked' : ''} ${warn && !p.enabled ? 'disabled' : ''}><span class="swt" aria-hidden="true"></span></span>
      <span><b>${tr('Customers can book appointments')}</b>${APB.types.length ? '' : `<small class="muted">${tr('A public page without login: free times come from your calendars, every booking is confirmed by e-mail.')}</small>`}</span></label>
    ${link}
    <h4>${tr('Page')}</h4>
    <div class="row"><label for="apb-slug">${tr('Address')}</label><span class="apb-slug"><span class="muted">/s/b/</span><input id="apb-slug" maxlength="40" autocomplete="off" spellcheck="false" value="${esc(p.slug)}"></span></div>
    <div class="row"><label for="apb-title">${tr('Title')}</label><input id="apb-title" maxlength="120" value="${esc(p.title)}" placeholder="${esc(S.me?.display_name || '')}"></div>
    <div class="row"><label for="apb-intro">${tr('Text')}</label><textarea id="apb-intro" rows="3" maxlength="1000">${esc(p.intro)}</textarea></div>
    <div class="row"><label for="apb-cal">${tr('Calendar')}</label><select id="apb-cal"><option value="">${tr('My first calendar')}</option>${cals}</select></div>
    ${D.offices.length ? `<div class="row"><label for="apb-office">${tr('Leads in')}</label><select id="apb-office"><option value="">${tr('No lead')}</option>${offs}</select></div>` : ''}
    <div class="row"><label for="apb-tz">${tr('Time zone')}</label><input id="apb-tz" maxlength="64" value="${esc(p.tz)}" spellcheck="false"></div>
    <h4>${tr('Opening hours')}</h4>
    <div class="apb-hours">${APB_DAYS.map(d => apbDayHtml(d, p.hours?.[d] || [])).join('')}</div>
    <div class="aerr" role="alert"></div>
    <div class="apb-save"><button class="btn pri" data-apb="save">${tr('Save')}</button></div>
    <h4>${tr('Appointment types')}</h4>${types}
    <div class="apb-save"><button class="btn" data-apb="newtype">${ic('plus', 's')} ${tr('New appointment type')}</button></div>
    <h4>${tr('Bookings')}</h4>${books}`;
}
const apbTypeSub = t => [tr('{0} min', t.duration_min), t.buffer_min ? tr('{0} min buffer', t.buffer_min) : '', t.location, t.active ? '' : tr('inactive')].filter(Boolean).join(' · ');

function apbRead() {
  const md = APB.md, v = id => $(id, md)?.value ?? '';
  const hours = {};
  for (const d of APB_DAYS) {
    const on = $(`[data-apbday="${d}"]`, md)?.checked, rows = [];
    if (on) {
      const hm = n => $(`[data-apbhm="${d}${n}"]`, md)?.value || '';
      if (hm('1a') && hm('1b')) rows.push([hm('1a'), hm('1b')]);
      if (!$(`.apb-day[data-day="${d}"] .apb-hm2`, md)?.classList.contains('hidden') && hm('2a') && hm('2b')) rows.push([hm('2a'), hm('2b')]);
    }
    hours[d] = rows;
  }
  const b = {slug: v('#apb-slug').trim().toLowerCase(), title: v('#apb-title'), intro: v('#apb-intro'), cal_id: v('#apb-cal') ? +v('#apb-cal') : null, tz: v('#apb-tz').trim(), hours};
  if ($('#apb-office', md)) { const o = v('#apb-office'); b.office_org_id = o === 'personal' ? 'personal' : o ? +o : null; }
  return b;
}
const apbBody = p => ({slug: p.slug, title: p.title, intro: p.intro, cal_id: p.cal_id, tz: p.tz, hours: p.hours, office_org_id: p.office_org_id});
async function apbSave() {
  const md = APB.md, D = APB.data, old = D.exists ? apbBody(D.page) : null, body = apbRead();
  const er = $('.aerr', md); if (er) er.textContent = '';
  try { APB.data = await api('PUT', '/api/appt/page', body); } catch (x) { if (er) er.textContent = x.message || ''; return; }
  apbDraw();
  offerUndo(tr('Saved'), histAdd({label: tr('Booking page changed'),
    undo: async () => { if (old) await api('PUT', '/api/appt/page', old); if (APB.md?.isConnected) apbReload(); },
    redo: async () => { await api('PUT', '/api/appt/page', body); if (APB.md?.isConnected) apbReload(); }}));
}
async function apbToggle(cb) {
  const on = cb.checked;
  try { APB.data = await api('PUT', '/api/appt/page', on && !APB.data.exists ? {...apbRead(), enabled: true} : {enabled: on}); } catch { cb.checked = !on; return; }
  apbDraw();
  offerUndo(on ? tr('Booking page on') : tr('Booking page off'), histAdd({label: on ? tr('Booking page on') : tr('Booking page off'),
    undo: async () => { await api('PUT', '/api/appt/page', {enabled: !on}); if (APB.md?.isConnected) apbReload(); },
    redo: async () => { await api('PUT', '/api/appt/page', {enabled: on}); if (APB.md?.isConnected) apbReload(); }}));
}

async function apbClick(e) {
  const md = APB.md;
  const b = e.target.closest('[data-apb]');
  if (b) {
    const a = b.dataset.apb;
    if (a === 'close') { md.remove(); APB.md = null; return; }
    if (a === 'copy') { try { await navigator.clipboard.writeText(APB.data.page.url); toast(tr('Copied')); } catch { toast(tr('Copy failed')); } return; }
    if (a === 'save') { apbSave(); return; }
    if (a === 'newtype') { apbTypeDlg(null); return; }
    if (a === 'add2' || a === 'rm2') {
      const row = $(`.apb-day[data-day="${b.dataset.d}"]`, md), two = $('.apb-hm2', row);
      two.classList.toggle('hidden', a === 'rm2');
      if (a === 'add2' && !$(`[data-apbhm="${b.dataset.d}2a"]`, md).value) { dpSet($(`[data-apbhm="${b.dataset.d}2a"]`, md), '14:00'); dpSet($(`[data-apbhm="${b.dataset.d}2b"]`, md), '17:00'); }
      b.dataset.apb = a === 'add2' ? 'rm2' : 'add2'; b.innerHTML = ic(a === 'add2' ? 'x' : 'plus', 's');
      const lbl = a === 'add2' ? tr('Remove the second time') : tr('Add a second time'); b.setAttribute('aria-label', lbl); b.title = lbl;
      return;
    }
  }
  const t = e.target.closest('[data-apbtype]');
  if (t) { apbTypeDlg(APB.types.find(x => x.id === +t.dataset.apbtype)); return; }
  const d = e.target.closest('[data-apbdel]');
  if (d) { apbTypeDelete(APB.types.find(x => x.id === +d.dataset.apbdel)); return; }
  const c = e.target.closest('[data-apbcancel]');
  if (c) apbCancel(APB.bookings.find(x => x.id === +c.dataset.apbcancel));
}

// ---- appointment types
const apbTypeBody = t => ({name: t.name, duration_min: t.duration_min, buffer_min: t.buffer_min, notice_h: t.notice_h, days_ahead: t.days_ahead, location: t.location, note: t.note, active: t.active});
function apbTypeDlg(t) {
  const num = (id, label, v, min, max, hint) => `<div class="row"><label for="${id}">${label}</label><input id="${id}" type="number" inputmode="numeric" min="${min}" max="${max}" value="${v}">${hint ? `<span class="muted">${hint}</span>` : ''}</div>`;
  const md = modal(`<h3>${t ? tr('Edit appointment type') : tr('New appointment type')}</h3>
    <div class="row"><label for="apt-name">${tr('Name')}</label><input id="apt-name" maxlength="100" value="${esc(t?.name || '')}" placeholder="${esc(tr('e.g. First meeting'))}"></div>
    ${num('apt-dur', tr('Duration'), t?.duration_min ?? 30, 5, 480, tr('minutes'))}
    ${num('apt-buf', tr('Buffer before and after'), t?.buffer_min ?? 0, 0, 240, tr('minutes'))}
    ${num('apt-notice', tr('Bookable from'), t?.notice_h ?? 12, 0, 720, tr('hours ahead'))}
    ${num('apt-days', tr('Bookable up to'), t?.days_ahead ?? 30, 1, 365, tr('days ahead'))}
    <div class="row"><label for="apt-loc">${tr('Location')}</label><input id="apt-loc" maxlength="200" value="${esc(t?.location || '')}" placeholder="${esc(tr('e.g. phone, video call or an address'))}"></div>
    <div class="row"><label for="apt-note">${tr('Note')}</label><textarea id="apt-note" rows="2" maxlength="1000">${esc(t?.note || '')}</textarea></div>
    <label class="chkl"><input type="checkbox" id="apt-active" ${!t || t.active ? 'checked' : ''}><span>${tr('Customers can book it')}</span></label>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${t ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('apb-tdlg');
  const close = fgModal(md);
  const v = id => $(id, md)?.value ?? '';
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    const body = {name: v('#apt-name'), duration_min: +v('#apt-dur') || 0, buffer_min: +v('#apt-buf') || 0, notice_h: +v('#apt-notice') || 0, days_ahead: +v('#apt-days') || 0,
      location: v('#apt-loc'), note: v('#apt-note'), active: !!$('#apt-active', md)?.checked};
    try { await apbTypeSave(t, body); md.remove(); } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
async function apbTypeSave(t, body) {
  if (!t) {
    const j = await api('POST', '/api/appt/types', body); apbReload();
    offerUndo(tr('Added'), histAdd({label: tr('Appointment type added'), undo: async () => { await api('DELETE', `/api/appt/types/${j.id}`); apbReload(); },
      redo: async () => { await api('POST', `/api/appt/types/${j.id}/restore`, {}); apbReload(); }}));
    return j;
  }
  const old = apbTypeBody(t);
  const j = await api('PATCH', `/api/appt/types/${t.id}`, body); apbReload();
  offerUndo(tr('Saved'), histAdd({label: tr('Appointment type changed'), undo: async () => { await api('PATCH', `/api/appt/types/${t.id}`, old); apbReload(); },
    redo: async () => { await api('PATCH', `/api/appt/types/${t.id}`, body); apbReload(); }}));
  return j;
}
async function apbTypeDelete(t) {
  if (!t) return;
  try { await api('DELETE', `/api/appt/types/${t.id}`); } catch { return; }
  apbReload();
  offerUndo(tr('Deleted'), histAdd({label: tr('Appointment type deleted'), undo: async () => { await api('POST', `/api/appt/types/${t.id}/restore`, {}); apbReload(); },
    redo: async () => { await api('DELETE', `/api/appt/types/${t.id}`); apbReload(); }}));
}

// ---- bookings: the person cancels (the customer gets a mail; cannot be undone, so it asks first)
async function apbCancel(b) {
  if (!b) return;
  const reason = await askPrompt(tr('Cancel the appointment with {0}?', b.name), '', {input: {max: 1000, placeholder: tr('Reason for the customer (optional)')}, ok: tr('Cancel the appointment'), cancel: tr('Back'), danger: true,
    body: b.status === 'confirmed' ? tr('The event is removed from your calendar and the customer gets an e-mail. This cannot be undone.') : tr('The customer has not confirmed yet; the time becomes free again.')});
  if (reason === null || reason === undefined) return;
  try { await api('POST', `/api/appt/bookings/${b.id}/cancel`, {reason: reason || ''}); } catch { return; }
  toast(tr('Appointment cancelled'));
  apbReload();
}
