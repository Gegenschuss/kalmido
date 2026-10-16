/* Kalmido web client: resources and disposition (2.50.0, #1194) -- a tab of the workload view (module "dispo", off by
   default): crew (members, contacts) and equipment (devices, sets) booked for shoot days as option or firm, a week grid
   with one row per resource (phones: a list per day), double bookings and absences marked as warnings (never blocked),
   "Who is free on ...?" and "My bookings".
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const DPV = {data: null, start: null, days: 7, org: null, seq: 0, loading: false, filter: 'all', mine: null, free: null};
const dp_on = () => feat('dispo');
const DP_GROUPS = [['people', N_('People')], ['contacts', N_('Contacts')], ['equipment', N_('Equipment')], ['sets', N_('Equipment sets')]];

async function dp_load() {
  const seq = ++DPV.seq;
  DPV.loading = true;
  const st = DPV.start || dp_monday(today());
  const q = new URLSearchParams({start: st, days: DPV.days, ...(DPV.org ? {org: DPV.org} : {})});
  try {
    const [j, m] = await Promise.all([api('GET', '/api/team/dispo?' + q), api('GET', '/api/team/bookings/mine').catch(() => ({bookings: []}))]);
    if (seq === DPV.seq) { DPV.data = j; DPV.mine = m.bookings || []; }
  } catch { if (seq === DPV.seq) DPV.data = {error: true}; }
  DPV.loading = false;
  dp_redraw(seq);
}
function dp_redraw(seq) { if (S.route.mod === 'workload' && WLV.tab === 'dispo' && (seq === undefined || seq === DPV.seq)) { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, viewWorkload())); } }
const dp_monday = s => { const d = pd(s); d.setDate(d.getDate() - (d.getDay() + 6) % 7); return ds(d); };
const dp_time = s => s.includes('T') ? s.slice(11, 16) : '';
function dp_when(b) {
  const a = b.start.slice(0, 10), e = b.end.slice(0, 10), ta = dp_time(b.start), te = dp_time(b.end);
  if (a === e) return fmtDayAbs(a) + (ta ? ` ${ta}${te ? '–' + te : ''}` : '');
  return `${fmtDayAbs(a)}${ta ? ' ' + ta : ''} – ${fmtDayAbs(e)}${te ? ' ' + te : ''}`;
}
const dp_warn = b => b.conflicts?.length || b.away;
const dp_warnText = b => [b.conflicts?.length ? tr('Double booking') : '', b.away ? tr('Away on this day') : ''].filter(Boolean).join(' · ');
const dp_status = b => b.status === 'firm' ? tr('Firm') : tr('Option');

function dp_view() {
  if (!DPV.data && !DPV.loading) setTimeout(dp_load, 0);
  const d = DPV.data;
  if (!d) return `<div class="dash wload dp">${ab2_tabs('dispo')}<p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (d.error) return `<div class="dash wload dp">${ab2_tabs('dispo')}<div class="empty">${tr('The disposition could not be loaded.')}</div></div>`;
  const days = [];
  for (let x = d.start; x <= d.end; x = addDays(x, 1)) days.push(x);
  const hol = Object.fromEntries((d.holidays || []).map(h => [h.date, h.name]));
  const covers = (b, day) => b.start.slice(0, 10) <= day && b.end.slice(0, 10) >= day;
  const setItems = Object.fromEntries(d.resources.sets.map(s => [s.id, s.items]));
  const rowsOf = (kind, r) => d.bookings.filter(b => (b.kind === kind && b.rid === r.id) || (kind === 'equipment' && b.kind === 'set' && (setItems[b.rid] || []).includes(r.id)));
  const groups = DP_GROUPS.filter(([g]) => DPV.filter === 'all' || (DPV.filter === 'people' ? ['people', 'contacts'].includes(g) : ['equipment', 'sets'].includes(g)));
  const kindOf = {people: 'user', contacts: 'contact', equipment: 'equipment', sets: 'set'};
  const bar = (b, via) => `<button type="button" class="dpbk ${b.status}${dp_warn(b) ? ' warn' : ''}" data-act="dp-edit" data-id="${b.id}" title="${esc([b.title, dp_when(b), dp_status(b), via ? tr('via {0}', via) : '', dp_warnText(b)].filter(Boolean).join(' · '))}">${dp_warn(b) ? ic('alert', 's') : ''}<span>${esc(b.title)}</span></button>`;
  let body = '';
  for (const [g, gname] of groups) {
    let list = d.resources[g];
    if (g === 'contacts' || g === 'sets') list = list.filter(r => d.bookings.some(b => b.kind === kindOf[g] && b.rid === r.id));  // only the booked ones
    if (!list.length) continue;
    body += `<tr class="dpgrp"><th scope="rowgroup" colspan="${days.length + 1}">${esc(tr(gname))}</th></tr>`;
    for (const r of list) {
      const bs = rowsOf(kindOf[g], r), away = g === 'people' ? d.away[String(r.id)] || {} : {};
      body += `<tr><th scope="row"><span class="wlp">${g === 'people' ? av(r.id, r.name) : `<span class="dpic">${ic(g === 'contacts' ? 'users' : 'brief', 's')}</span>`}<b>${esc(r.name)}</b></span></th>${days.map(x => {
        const here = bs.filter(b => covers(b, x)), dt = pd(x), we = dt.getDay() === 0 || dt.getDay() === 6;
        return `<td class="dpc${we ? ' we' : ''}${hol[x] ? ' hol' : ''}${away[x] ? ' away' : ''}"${away[x] ? ` title="${esc(tr('Away'))}"` : hol[x] ? ` title="${esc(hol[x])}"` : ''}>${here.map(b => bar(b, b.kind === 'set' && kindOf[g] === 'equipment' ? b.label : '')).join('')}</td>`;
      }).join('')}</tr>`;
    }
  }
  const head = days.map(x => { const dt = pd(x); return `<th scope="col" class="${x === d.today ? 'tdy' : ''}${hol[x] ? ' hol' : ''}">${esc(dt.toLocaleDateString(LOCALE(), {weekday: 'short', day: 'numeric'}))}</th>`; }).join('');
  // phones: one list per day, grouped by job
  const dayList = days.map(x => {
    const bs = d.bookings.filter(b => covers(b, x)); if (!bs.length) return '';
    const jobs = {};
    for (const b of bs) (jobs[b.job] = jobs[b.job] || []).push(b);
    return `<li><h4>${esc(fmtDayAbs(x))}${hol[x] ? ` <small class="muted">${esc(hol[x])}</small>` : ''}</h4>${Object.values(jobs).map(js => `<button type="button" class="dpjob${js.some(dp_warn) ? ' warn' : ''}" data-act="dp-edit" data-id="${js[0].id}"><b>${esc(js[0].title)}</b><span class="muted">${esc(dp_when(js[0]))} · ${esc(dp_status(js[0]))}</span><span class="dpres">${js.map(b => `<span class="${dp_warn(b) ? 'warn' : ''}">${dp_warn(b) ? ic('alert', 's') : ''}${esc(b.label)}</span>`).join('')}</span></button>`).join('')}</li>`;
  }).join('');
  const mine = (DPV.mine || []).map(b => `<li class="dpmine ${b.status}"><b>${esc(b.title)}</b><span class="muted">${esc(dp_when(b))}${b.org ? ' · ' + esc(b.org) : ''}</span><span class="dpst ${b.status}">${esc(dp_status(b))}</span></li>`).join('');
  const f = (k, label) => `<button type="button" data-act="dp-filter" data-v="${k}" class="${DPV.filter === k ? 'on' : ''}" aria-pressed="${DPV.filter === k}">${esc(tr(label))}</button>`;
  const fr = DPV.free;
  const freeHtml = fr ? `<div class="dpfree"><p><b>${esc(tr('Free on {0}', fmtDayAbs(fr.date)))}</b></p>${[['people', 'People'], ['contacts', 'Contacts'], ['equipment', 'Equipment'], ['sets', 'Equipment sets']].map(([k, n]) => fr[k].length ? `<p><span class="muted">${esc(tr(n))}:</span> ${fr[k].map(r => esc(r.name)).join(', ')}</p>` : '').join('') || `<p class="muted">${tr('Nobody and nothing is free.')}</p>`}${fr.away.length ? `<p class="muted">${esc(tr('Away: {0}', fr.away.map(id => d.resources.people.find(p => p.id === id)?.name || '?').join(', ')))}</p>` : ''}</div>` : '';
  return `<div class="dash wload dp">${ab2_tabs('dispo')}<div class="clhead"><div class="seg" role="group" aria-label="${esc(tr('Show'))}">${f('all', N_('All'))}${f('people', N_('People'))}${f('tech', N_('Equipment'))}</div><span class="spacer"></span>
      ${d.orgs.length > 1 ? `<select id="dp-org" aria-label="${esc(tr('Organisation'))}">${d.orgs.map(o => `<option value="${o.id}" ${o.id === d.org_id ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>` : ''}
      <button class="iconbtn" data-act="dp-move" data-d="-1" aria-label="${esc(tr('Earlier'))}" title="${esc(tr('Earlier'))}">${ic('left', 's')}</button><button class="btn sm" data-act="dp-move" data-d="0">${tr('This week')}</button><button class="iconbtn" data-act="dp-move" data-d="1" aria-label="${esc(tr('Later'))}" title="${esc(tr('Later'))}">${ic('right', 's')}</button>
      <button class="btn sm pri" data-act="dp-new">${ic('plus', 's')} ${tr('Book')}</button></div>
    <div class="wlwrap dpgrid"><table class="wltable dptable"><thead><tr><th scope="col">${tr('Resource')}</th>${head}</tr></thead><tbody>${body || `<tr><td colspan="${days.length + 1}" class="muted">${tr('Nothing to show yet: add people to the organisation or equipment in Office & finance.')}</td></tr>`}</tbody></table></div>
    <ul class="dpdays">${dayList || `<li class="muted">${tr('No bookings this week.')}</li>`}</ul>
    <p class="muted dplegend"><span class="dpk firm"></span>${tr('Firm')} <span class="dpk option"></span>${tr('Option')} <span class="dpk away"></span>${tr('Away')} ${ic('alert', 's')} ${tr('Double booking or away: a warning, the booking stays')}</p>
    <div class="dpfreebox"><label for="dp-freeday">${tr('Who is free on …?')}</label>${dateIn('dp-freeday', fr?.date || d.today)}<button class="btn sm" data-act="dp-free">${tr('Show')}</button></div>${freeHtml}
    <h4 class="ab2h">${tr('My bookings')}</h4>${mine ? `<ul class="ab2list dpminel">${mine}</ul>` : `<p class="muted">${tr('You are not booked.')}</p>`}</div>`;
}

// book: one sheet -- what, when, option / firm, who and what (people, contacts, equipment, sets)
async function dp_sheet(day) {
  const d = DPV.data; if (!d) return;
  const st = day || d.today;
  const res = d.resources;
  const lists = (S.lists || []).filter(l => !l.archived && !l.deleted_at).slice(0, 300);
  const grp = (g, kind, label) => res[g].length ? `<fieldset class="dppick"><legend>${esc(tr(label))}</legend>${res[g].map(r => `<label class="dpopt"><input type="checkbox" data-k="${kind}" value="${r.id}"><span>${esc(r.name)}</span><small class="dpbusy" data-k="${kind}" data-id="${r.id}"></small></label>`).join('')}</fieldset>` : '';
  const md = modal(`<h3>${tr('Book')}</h3>
    <div class="row"><label for="dp-title">${tr('What')}</label><input id="dp-title" maxlength="200" placeholder="${esc(tr('e.g. Shoot day, interview'))}"></div>
    <div class="row ab2dates"><label>${tr('From')}${dateIn('dp-from', st)}</label><label>${tr('To')}${dateIn('dp-to', st)}</label></div>
    <div class="row ab2dates"><label>${tr('Start time')}${timeIn('dp-t0', '')}</label><label>${tr('End time')}${timeIn('dp-t1', '')}</label></div>
    <div class="row"><span class="lbl">${tr('Status')}</span><div class="seg dpstat" role="group" aria-label="${esc(tr('Status'))}"><button type="button" data-s="option" class="on" aria-pressed="true">${tr('Option')}</button><button type="button" data-s="firm" aria-pressed="false">${tr('Firm')}</button></div></div>
    ${lists.length ? `<div class="row"><label for="dp-list">${tr('Project')}</label><select id="dp-list"><option value="">${tr('None')}</option>${lists.map(l => `<option value="${l.id}">${esc(lname(l))}</option>`).join('')}</select></div>` : ''}
    <div class="dppicks">${grp('people', 'user', 'People')}${grp('contacts', 'contact', 'Contacts')}${grp('equipment', 'equipment', 'Equipment')}${grp('sets', 'set', 'Equipment sets')}</div>
    <div class="row"><label for="dp-note">${tr('Note')}</label><input id="dp-note" maxlength="1000" placeholder="${esc(tr('optional'))}"></div>
    <div class="shint lhint keep">${tr('Firm bookings show up in the News of the people booked. Double bookings and absences are only warnings.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${ic('check', 's')} ${tr('Book')}</button></div>`);
  md.classList.add('ab2md', 'dpmd');
  const busy = async () => {  // mark who / what is taken on the first day
    const day0 = $('#dp-from', md).value; if (!day0) return;
    try {
      const fr = await api('GET', `/api/team/dispo/free?date=${day0}${d.org_id ? '&org=' + d.org_id : ''}`);
      const free = new Set([...fr.people.map(r => 'user:' + r.id), ...fr.contacts.map(r => 'contact:' + r.id), ...fr.equipment.map(r => 'equipment:' + r.id), ...fr.sets.map(r => 'set:' + r.id)]);
      $$('.dpbusy', md).forEach(el => { const k = el.dataset.k + ':' + el.dataset.id; el.textContent = free.has(k) ? '' : el.dataset.k === 'user' && fr.away.includes(+el.dataset.id) ? tr('away') : tr('booked'); });
    } catch { /* no marks offline */ }
  };
  busy();
  md.addEventListener('change', e => { if (e.target.id === 'dp-from') { if ($('#dp-to', md).value < e.target.value) { $('#dp-to', md).value = e.target.value; dpSync($('#dp-to', md)); } busy(); } });
  md.addEventListener('click', async e => {
    const s = e.target.closest('[data-s]');
    if (s) { $$('.dpstat button', md).forEach(b => { b.classList.toggle('on', b === s); b.setAttribute('aria-pressed', b === s); }); return; }
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const t0 = $('#dp-t0', md).value, t1 = $('#dp-t1', md).value, a = $('#dp-from', md).value, z = $('#dp-to', md).value || a;
    const v = {title: $('#dp-title', md).value.trim(), start: a + (t0 ? 'T' + t0 : ''), end: z + (t1 ? 'T' + t1 : t0 ? 'T23:59' : ''), status: $('.dpstat button.on', md)?.dataset.s || 'option',
      note: $('#dp-note', md).value, list_id: $('#dp-list', md)?.value || null, org: d.org_id, resources: $$('.dppick input:checked', md).map(x => ({kind: x.dataset.k, id: +x.value}))};
    if (!v.title) { toast(tr('Please enter a name')); $('#dp-title', md).focus(); return; }
    if (!v.resources.length) { toast(tr('Choose at least one person or device')); return; }
    b.disabled = true;
    try {
      const r = await api('POST', '/api/team/dispo/bookings', v);
      const ids = r.bookings.map(x => x.id);
      histAdd({label: tr('Booked: {0}', v.title), undo: async () => { await api('DELETE', `/api/team/dispo/bookings/${ids[0]}?all=1`); dp_reload(); },
        redo: async () => { await api('POST', '/api/team/dispo/bookings/restore', {ids}); dp_reload(); }});
      md.remove(); dp_reload();
      toast(r.warnings ? trn('Booked, {0} warning: double booking or away', 'Booked, {0} warnings: double booking or away', r.warnings) : tr('Booked'));
    } catch { b.disabled = false; /* api() said it */ }
  });
}

// a booking: change the job (title, period, option / firm) or delete it (one resource or the whole job), with Undo
function dp_editSheet(b) {
  const d = DPV.data, job = d.bookings.filter(x => x.job === b.job);
  const md = modal(`<h3>${esc(b.title)}</h3><p class="muted">${esc(dp_when(b))}</p>
    <ul class="dpjobres">${job.map(x => `<li class="${dp_warn(x) ? 'warn' : ''}"><span>${dp_warn(x) ? ic('alert', 's') : ''}${esc(x.label)}</span>${dp_warn(x) ? `<small>${esc(dp_warnText(x))}</small>` : ''}<button type="button" class="iconbtn" data-m="delone" data-id="${x.id}" aria-label="${esc(tr('Remove {0}', x.label))}" title="${esc(tr('Remove {0}', x.label))}">${ic('x', 's')}</button></li>`).join('')}</ul>
    <div class="row"><label for="dpe-title">${tr('What')}</label><input id="dpe-title" maxlength="200" value="${esc(b.title)}"></div>
    <div class="row ab2dates"><label>${tr('From')}${dateIn('dpe-from', b.start.slice(0, 10))}</label><label>${tr('To')}${dateIn('dpe-to', b.end.slice(0, 10))}</label></div>
    <div class="row ab2dates"><label>${tr('Start time')}${timeIn('dpe-t0', dp_time(b.start))}</label><label>${tr('End time')}${timeIn('dpe-t1', dp_time(b.end) === '23:59' && !dp_time(b.start) ? '' : dp_time(b.end))}</label></div>
    <div class="row"><span class="lbl">${tr('Status')}</span><div class="seg dpstat" role="group" aria-label="${esc(tr('Status'))}">${['option', 'firm'].map(s => `<button type="button" data-s="${s}" class="${b.status === s ? 'on' : ''}" aria-pressed="${b.status === s}">${s === 'firm' ? tr('Firm') : tr('Option')}</button>`).join('')}</div></div>
    <div class="row"><label for="dpe-note">${tr('Note')}</label><input id="dpe-note" maxlength="1000" value="${esc(b.note || '')}"></div>
    <div class="foot"><button class="btn danger" data-m="del">${ic('trash', 's')} ${tr('Delete')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${ic('check', 's')} ${tr('Save')}</button></div>`);
  md.classList.add('ab2md', 'dpmd');
  const del = async (id, all) => {
    try {
      const r = await api('DELETE', `/api/team/dispo/bookings/${id}${all ? '?all=1' : ''}`);
      const e = histAdd({label: tr('Booking deleted'), undo: async () => { await api('POST', '/api/team/dispo/bookings/restore', {ids: r.ids}); dp_reload(); },
        redo: async () => { for (const x of r.ids) await api('DELETE', `/api/team/dispo/bookings/${x}`); dp_reload(); }});
      md.remove(); dp_reload(); offerUndo(tr('Booking deleted'), e);
    } catch { /* api() said it */ }
  };
  md.addEventListener('click', async e => {
    const s = e.target.closest('[data-s]');
    if (s) { $$('.dpstat button', md).forEach(x => { x.classList.toggle('on', x === s); x.setAttribute('aria-pressed', x === s); }); return; }
    const k = e.target.closest('[data-m]'); if (!k) return;
    if (k.dataset.m === 'close') { md.remove(); return; }
    if (k.dataset.m === 'delone') { del(+k.dataset.id, false); return; }
    if (k.dataset.m === 'del') { del(b.id, true); return; }
    const t0 = $('#dpe-t0', md).value, t1 = $('#dpe-t1', md).value, a = $('#dpe-from', md).value, z = $('#dpe-to', md).value || a;
    const v = {title: $('#dpe-title', md).value.trim(), start: a + (t0 ? 'T' + t0 : ''), end: z + (t1 ? 'T' + t1 : t0 ? 'T23:59' : ''), status: $('.dpstat button.on', md)?.dataset.s || b.status, note: $('#dpe-note', md).value, all: true};
    const before = {title: b.title, start: b.start, end: b.end, status: b.status, note: b.note || '', all: true};
    k.disabled = true;
    try {
      await api('PATCH', `/api/team/dispo/bookings/${b.id}`, v);
      const put = x => async () => { await api('PATCH', `/api/team/dispo/bookings/${b.id}`, x); dp_reload(); };
      histAdd({label: tr('Booking changed'), undo: put(before), redo: put(v)});
      md.remove(); dp_reload(); toast(tr('Saved'));
    } catch { k.disabled = false; /* api() said it */ }
  });
}

function dp_reload() { DPV.data = null; DPV.free = null; if (S.route.mod === 'workload') dp_load(); }

document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-act^="dp-"]'); if (!a || a.disabled) return;
  e.preventDefault(); e.stopPropagation();
  const k = a.dataset.act;
  if (k === 'dp-move') { const n = +a.dataset.d; DPV.start = n === 0 ? null : addDays(DPV.data?.start || dp_monday(today()), 7 * n); DPV.data = null; DPV.free = null; dp_load(); }
  else if (k === 'dp-filter') { DPV.filter = a.dataset.v; dp_redraw(); }
  else if (k === 'dp-new') dp_sheet(null);
  else if (k === 'dp-edit') { const b = DPV.data?.bookings.find(x => x.id === +a.dataset.id); if (b) dp_editSheet(b); }
  else if (k === 'dp-free') {
    const day = $('#dp-freeday')?.value; if (!day) return;
    try { DPV.free = await api('GET', `/api/team/dispo/free?date=${day}${DPV.data?.org_id ? '&org=' + DPV.data.org_id : ''}`); dp_redraw(); } catch { /* api() said it */ }
  }
});
document.addEventListener('change', e => { if (e.target.id === 'dp-org') { DPV.org = +e.target.value; DPV.data = null; DPV.free = null; dp_load(); } });
