/* Kalmido web client: absences (2.50.0, #1195) -- a tab of the workload view: who is away when (vacation, sick leave, days
   off), public holidays of the organisation's state, "Enter an absence" as a sheet. The team sees "away" only; the kind and
   the note only the person and the organisation's admins (the server leaves them out). Also: the hint in "Plan my day"
   and the warning when a task is assigned to somebody who is away on its day (it never blocks).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const AB2 = {data: null, start: null, org: null, seq: 0, loading: false};


async function ab2_load() {
  const seq = ++AB2.seq;
  AB2.loading = true;
  const st = AB2.start || today().slice(0, 7) + '-01', d = pd(st);
  const end = ds(new Date(d.getFullYear(), d.getMonth() + 1, 0));
  const q = new URLSearchParams({start: st, end, ...(AB2.org ? {org: AB2.org} : {})});
  try { const j = await api('GET', '/api/team/absences?' + q); if (seq === AB2.seq) AB2.data = j; } catch { if (seq === AB2.seq) AB2.data = {error: true}; }
  AB2.loading = false;
  if (S.route.mod === 'workload' && WLV.tab === 'abs' && seq === AB2.seq) { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, viewWorkload())); }
}

function ab2_view() {
  if (!AB2.data && !AB2.loading) setTimeout(ab2_load, 0);
  const d = AB2.data;
  if (!d) return `<div class="dash wload ab2">${ab2_tabs('abs')}<p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (d.error) return `<div class="dash wload ab2">${ab2_tabs('abs')}<div class="empty">${tr('The absences could not be loaded.')}</div></div>`;
  const first = pd(d.start), days = [];
  for (let x = new Date(first); ds(x) <= d.end; x.setDate(x.getDate() + 1)) days.push(ds(x));
  const hol = Object.fromEntries((d.holidays || []).map(h => [h.date, h.name]));
  const byUser = {};
  for (const it of d.items) (byUser[it.user_id] = byUser[it.user_id] || []).push(it);
  const cellOf = (uid, day) => (byUser[uid] || []).find(it => it.start_date <= day && it.end_date >= day && it.status !== 'rejected');  // 2.125.0 A (#2117)
  const head = days.map(x => { const dt = pd(x), we = dt.getDay() === 0 || dt.getDay() === 6; return `<th scope="col" class="${we ? 'we' : ''}${hol[x] ? ' hol' : ''}${x === d.today ? ' tdy' : ''}" title="${esc(hol[x] || fmtDayAbs(x))}">${dt.getDate()}</th>`; }).join('');
  const rows = d.people.map(p => `<tr><th scope="row"><span class="wlp">${av(p.id, p.display_name)}<b>${esc(p.display_name)}</b></span></th>${days.map(x => {
    const it = cellOf(p.id, x), dt = pd(x), we = dt.getDay() === 0 || dt.getDay() === 6;
    const tip = it ? `${esc(p.display_name)}: ${esc(it.kind ? ab2_kindName(it.kind) : tr('Away'))} ${esc(ab2_span(it))}${esc(lv_mark(it))}` : esc(hol[x] || '');
    return `<td class="ab2c${we ? ' we' : ''}${hol[x] ? ' hol' : ''}${it ? ' off' + (it.half_day ? ' half' : '') + lv_cls(it) : ''}"${tip ? ` title="${tip}"` : ''}>${it && it.can_edit ? `<button type="button" class="ab2b" data-act="ab2-edit" data-id="${it.id}" aria-label="${tip}"></button>` : ''}</td>`;
  }).join('')}</tr>`).join('');
  const mon = first.toLocaleDateString(LOCALE(), {month: 'long', year: 'numeric'});
  const list = d.items.map(it => {
    const p = d.people.find(x => x.id === it.user_id);
    const what = it.kind ? ab2_kindName(it.kind) : tr('Away');
    const inner = `${av(it.user_id, p?.display_name || '?')}<span class="ab2lt"><b>${esc(p?.display_name || '?')}</b><span class="muted">${esc(ab2_span(it))} · ${esc(what)}${it.note ? ' · ' + esc(it.note) : ''}${esc(lv_mark(it))}</span></span>`;
    return `<li>${it.can_edit ? `<button type="button" class="ab2li" data-act="ab2-edit" data-id="${it.id}">${inner}${ic('edit', 's')}</button>` : `<div class="ab2li">${inner}</div>`}</li>`;
  }).join('');
  const hl = (d.holidays || []).map(h => `<li class="muted">${esc(fmtDayAbs(h.date))} · ${esc(h.name)}</li>`).join('');
  const stSel = d.admin ? `<label class="ab2st"><span class="muted">${tr('Public holidays')}</span><select id="ab2-state" aria-label="${esc(tr('Public holidays'))}"><option value="">${tr('None')}</option>${Object.entries(d.states).map(([k, v]) => `<option value="${k}" ${k === d.state ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`
    : d.state ? `<span class="muted ab2st">${esc(tr('Public holidays: {0}', d.states[d.state] || d.state))}</span>` : '';
  // 2.96.0 D (#1941): the own personal area next to the organisations (the workspace switch on "Private" opens it)
  const areas = [...(d.personal ? [{id: d.personal, name: tr('Private|workspace')}] : []), ...d.orgs];
  return `<div class="dash wload ab2">${ab2_tabs('abs')}<div class="clhead"><h3 class="ab2mon">${esc(mon)}</h3><span class="spacer"></span>
      ${areas.length > 1 ? `<select id="ab2-org" aria-label="${esc(tr('Organisation'))}">${areas.map(o => `<option value="${o.id}" ${o.id === d.org_id ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>` : ''}
      <button class="iconbtn" data-act="ab2-move" data-d="-1" aria-label="${esc(tr('Earlier'))}" title="${esc(tr('Earlier'))}">${ic('left', 's')}</button><button class="btn sm" data-act="ab2-move" data-d="0">${tr('This month')}</button><button class="iconbtn" data-act="ab2-move" data-d="1" aria-label="${esc(tr('Later'))}" title="${esc(tr('Later'))}">${ic('right', 's')}</button>
      <button class="btn sm pri" data-act="ab2-new">${ic('plus', 's')} ${tr('Enter an absence')}</button></div>
    <p class="muted">${tr('Only the person and the admins see the reason and the note.')}</p>
    ${lv_html(d)}
    <div class="wlwrap ab2grid"><table class="wltable ab2table"><thead><tr><th scope="col">${tr('Person')}</th>${head}</tr></thead><tbody>${rows || `<tr><td colspan="${days.length + 1}" class="muted">${tr('Nobody to show.')}</td></tr>`}</tbody></table></div>
    <h4 class="ab2h">${tr('Absences this month')}</h4>
    ${list ? `<ul class="ab2list">${list}</ul>` : `<p class="muted">${tr('Nobody is away this month.')}</p>`}
    ${hl ? `<h4 class="ab2h">${tr('Public holidays')}</h4><ul class="ab2hol">${hl}</ul>` : ''}
    <div class="ab2foot">${stSel}</div></div>`;
}

function ab2_span(it) {
  const half = it.half_day === 'am' ? tr('morning') : it.half_day === 'pm' ? tr('afternoon') : '';
  return it.start_date === it.end_date ? fmtDayAbs(it.start_date) + (half ? ` (${half})` : '') : `${fmtDayAbs(it.start_date)} – ${fmtDayAbs(it.end_date)}`;
}

// "Enter an absence" / edit: a sheet (phones) / dialog
function ab2_sheet(it) {
  const d = AB2.data || {people: [], admin: false};
  const kind = it?.kind || 'vacation', st = it?.start_date || today(), en = it?.end_date || st;
  const ppl = d.admin && !it ? d.people : [];
  const md = modal(`<h3>${it ? tr('Edit absence') : tr('Enter an absence')}</h3>
    ${ppl.length > 1 ? `<div class="row"><label for="ab2-who">${tr('Person')}</label><select id="ab2-who">${ppl.map(p => `<option value="${p.id}" ${p.own ? 'selected' : ''}>${esc(p.display_name)}</option>`).join('')}</select></div>` : ''}
    <div class="row"><span class="lbl">${tr('Kind')}</span><div class="seg ab2kinds" role="group" aria-label="${esc(tr('Kind'))}">${AB2_KINDS.map(([k, n]) => `<button type="button" data-k="${k}" class="${k === kind ? 'on' : ''}" aria-pressed="${k === kind}">${esc(tr(n))}</button>`).join('')}</div></div>
    <div class="row ab2dates"><label>${tr('From')}${dateIn('ab2-from', st)}</label><label>${tr('To')}${dateIn('ab2-to', en)}</label></div>
    <div class="row" id="ab2-halfrow"><label for="ab2-half">${tr('Duration')}</label><select id="ab2-half"><option value="">${tr('Whole day')}</option><option value="am" ${it?.half_day === 'am' ? 'selected' : ''}>${tr('Half day (morning)')}</option><option value="pm" ${it?.half_day === 'pm' ? 'selected' : ''}>${tr('Half day (afternoon)')}</option></select></div>
    <div class="row"><label for="ab2-note">${tr('Note')}</label><input id="ab2-note" maxlength="500" value="${esc(it?.note || '')}" placeholder="${esc(tr('optional'))}"></div>
    <div class="shint lhint keep">${tr('The team only sees that you are away. The kind and the note stay with you and the admins of the organisation.')}</div>
    ${lv_sheetHint()}
    <div class="foot">${it ? `<button class="btn danger" data-m="del">${ic('trash', 's')} ${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${ic('check', 's')} ${tr('Save')}</button></div>`);
  md.classList.add('ab2md');
  const sync = () => { const one = $('#ab2-from', md).value && $('#ab2-from', md).value === $('#ab2-to', md).value; $('#ab2-halfrow', md).hidden = !one; if (!one) $('#ab2-half', md).value = ''; };
  sync();
  md.addEventListener('change', e => { if (e.target.id === 'ab2-from' && $('#ab2-to', md).value < e.target.value) { $('#ab2-to', md).value = e.target.value; dpSync($('#ab2-to', md)); } sync(); });
  md.addEventListener('click', async e => {
    const k = e.target.closest('[data-k]');
    if (k) { $$('.ab2kinds button', md).forEach(b => { b.classList.toggle('on', b === k); b.setAttribute('aria-pressed', b === k); }); return; }
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'del') { md.remove(); ab2_delete(it); return; }
    const v = {kind: $('.ab2kinds button.on', md)?.dataset.k || 'vacation', start_date: $('#ab2-from', md).value, end_date: $('#ab2-to', md).value || $('#ab2-from', md).value, half_day: $('#ab2-half', md).value, note: $('#ab2-note', md).value};
    if (!it && $('#ab2-who', md)) v.user_id = +$('#ab2-who', md).value;
    if (!it && AB2.data?.org_id) v.org = AB2.data.org_id;
    b.disabled = true;
    try {
      if (it) {
        const before = {kind: it.kind, start_date: it.start_date, end_date: it.end_date, half_day: it.half_day, note: it.note};
        await api('PATCH', `/api/team/absences/${it.id}`, v);
        const put = x => async () => { await api('PATCH', `/api/team/absences/${it.id}`, x); ab2_reload(); };
        histAdd({label: tr('Absence changed'), undo: put(before), redo: put(v)});
      } else {
        const r = await api('POST', '/api/team/absences', v);
        AB2.req = r.status === 'pending';  // 2.125.0 A (#2117): a request, not yet away
        histAdd({label: tr('Absence entered'), undo: async () => { await api('DELETE', `/api/team/absences/${r.id}`); ab2_reload(); },
          redo: async () => { await api('POST', `/api/team/absences/${r.id}/restore`); ab2_reload(); }});
      }
      md.remove(); ab2_reload(); toast(!it && AB2.req ? tr('Vacation requested') : tr('Saved'));
    } catch { b.disabled = false; /* api() said it */ }
  });
}

async function ab2_delete(it) {
  try {
    await api('DELETE', `/api/team/absences/${it.id}`);
    const e = histAdd({label: tr('Absence deleted'), undo: async () => { await api('POST', `/api/team/absences/${it.id}/restore`); ab2_reload(); },
      redo: async () => { await api('DELETE', `/api/team/absences/${it.id}`); ab2_reload(); }});
    ab2_reload(); offerUndo(tr('Absence deleted'), e);
  } catch { /* api() said it */ }
}

function ab2_reload() { AB2.data = null; lv_reset(); if (S.route.mod === 'workload') { WLV.data = null; ab2_load(); } }


// assigning: a warning when the person is away on the task's day (the assignment stays)
async function ab2_warnAssign(uid, t) {
  const day = t?.due || (t?.plan_start || '').slice(0, 10);
  if (!uid || !day || !collab()) return;
  try {
    const r = await rawFetch('GET', `/api/team/absences/check?user=${uid}&date=${day}`);
    if (r.absent) toast(uid === S.me?.id ? tr('Note: you are away on {0}', fmtDayAbs(day)) : tr('Note: {0} is away on {1}', apName(uid), fmtDayAbs(day)));
  } catch { /* no hint offline */ }
}

document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-act^="ab2-"]'); if (!a || a.disabled) return;
  e.preventDefault(); e.stopPropagation();
  const k = a.dataset.act;
  if (k === 'ab2-move') { const n = +a.dataset.d, d = pd(AB2.data?.start || today().slice(0, 7) + '-01'); AB2.start = n === 0 ? null : ds(new Date(d.getFullYear(), d.getMonth() + n, 1)); AB2.data = null; ab2_load(); }
  else if (k === 'ab2-new') ab2_sheet(null);
  else if (k === 'ab2-edit') { const it = AB2.data?.items.find(x => x.id === +a.dataset.id); if (it) ab2_sheet(it); }
});
document.addEventListener('change', async e => {
  if (e.target.id === 'ab2-org') { AB2.org = +e.target.value; AB2.data = null; ab2_load(); }
  else if (e.target.id === 'ab2-state') {
    const from = AB2.data?.state || '', to = e.target.value, org = AB2.data?.org_id;
    const put = v => async () => { await api('PUT', '/api/team/absences/holidays', {state: v, org}); ab2_reload(); };
    try { await put(to)(); histAdd({label: tr('Changed setting: {0}', tr('Public holidays')), sett: true, undo: put(from), redo: put(to)}); toast(tr('Saved')); } catch { /* api() said it */ }
  }
});
