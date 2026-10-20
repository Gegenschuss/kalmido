// @ts-check
/* Kalmido web client: working days per person and leave (2.125.0 A, #2118 / #2117) -- the working days + weekly hours in
   Settings (General, "Working week"), the vacation account, vacation requests and their approval in the absences tab of
   the workload view (absence.js draws the tab, this file the leave parts it hooks in).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- #2118: working days (Monday = 0 .. Sunday = 6, '' = Monday..Friday)
const WT_DEFAULT = [0, 1, 2, 3, 4];
const wt_parse = v => { const d = String(v || '').split(',').filter(x => /^[0-6]$/.test(x.trim())).map(Number); return d.length ? [...new Set(d)].sort() : WT_DEFAULT.slice(); };
const wt_dayName = (i, len = 'short') => (len === 'long' ? WDL : WD)[(i + 1) % 7];  // Monday = 0 here, Sunday = 0 in WD
function wt_daysHtml(id, sel, act = 'wt-day') {
  return `<div class="seg wtdays" id="${id}" role="group" aria-label="${esc(tr('Working days'))}">${[0, 1, 2, 3, 4, 5, 6].map(i => `<button type="button" data-act="${act}" data-d="${i}" class="${sel.includes(i) ? 'on' : ''}" aria-pressed="${sel.includes(i)}" title="${esc(wt_dayName(i, 'long'))}">${esc(wt_dayName(i))}</button>`).join('')}</div>`;
}
const wt_daysOf = el => $$('button.on', el).map(b => +b.dataset.d).sort();
const wt_str = d => (d.join(',') === WT_DEFAULT.join(',') ? '' : d.join(','));
// Settings > General: the working week next to the day planning (autosave like every other setting)
function wt_setHtml(s, hint) {
  if (!workloadOn() && !timeOn()) return '';
  return `<h4 id="s-wt-h">${tr('Working week')}</h4>
      <div class="row"><span class="lbl">${tr('Working days')}</span>${wt_daysHtml('s-wtdays', wt_parse(s.workdays))}</div>
      <div class="row"><label for="s-wthours">${tr('Hours per week')}</label><input id="s-wthours" value="${esc(s.capacity_h || '')}" inputmode="decimal" placeholder="${esc(fmtNum(5 * (S.timeDayH || 8), 1))}" class="numin"><span class="muted">${tr('Empty = 5 × the hours per day of the server')}</span></div>
      ${hint(tr('The workload spreads your hours per week over your working days; absences and public holidays on them lower it. The hint “Maybe forgotten” and the vacation account count only working days.'))}`;
}
function wt_sync(md) {
  const el = $('#s-wtdays', md); if (!el) return;
  const d = wt_parse(S.settings.workdays);
  $$('button', el).forEach(b => { const on = d.includes(+b.dataset.d); b.classList.toggle('on', on); b.setAttribute('aria-pressed', on); });
}
function wt_toggle(b) {
  const box = b.closest('.wtdays'), on = !b.classList.contains('on');
  if (!on && $$('button.on', box).length < 2) { toast(tr('Keep at least one working day')); return null; }
  b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
  return wt_daysOf(box);
}

// ---- #2117: the vacation account and requests (hooked into the absences tab, absence.js)
// the notification row "leave" (account.js matrix): a new request (admins), the decision on my own
NOTIF_ROWS.push(['leave', N_('Vacation requests'), N_('admins: a new request; everybody: the decision on their own')]);
NM_NEWS_NEW.leave = 1; NM_PUSH.leave = 1;
const LV = {data: null, key: '', seq: 0};
const lv_num = n => fmtNum(n || 0, 1);
function lv_reset() { LV.data = null; LV.key = ''; }
async function lv_load(org, year) {
  const seq = ++LV.seq, key = `${org || ''}:${year}`;
  LV.key = key;
  try { const j = await api('GET', '/api/team/leave?' + new URLSearchParams({year, ...(org ? {org} : {})})); if (seq === LV.seq) LV.data = j; } catch { if (seq === LV.seq) LV.data = {error: true}; }
  if (seq === LV.seq && S.route.mod === 'workload' && WLV.tab === 'abs') { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, viewWorkload())); }
}
// the status of an absence in the grid / the list (only the person and the admins see requests)
const lv_cls = it => (it.status === 'pending' ? ' req' : '');
const lv_mark = it => (it.status === 'pending' ? ' · ' + tr('requested') : it.status === 'rejected' ? ' · ' + tr('rejected') + (it.decision_note ? ': ' + it.decision_note : '') : '');
function lv_sheetHint() {
  const d = LV.data;
  return d && d.approval && !d.admin ? `<div class="shint keep lvhint">${tr('Vacation goes to the admins of the organisation as a request; it counts as away once it is approved.')}</div>` : '';
}
function lv_accLine(p) {
  if (!p.quota) return `<span class="muted">${tr('No vacation account')}</span>`;
  const tot = (p.quota.days || 0) + (p.quota.carry || 0);
  return `<span class="lvnums"><span>${tr('Entitlement')} <b>${lv_num(tot)}</b>${p.quota.carry ? ` <small class="muted">(${esc(tr('incl. {0} carried over', lv_num(p.quota.carry)))})</small>` : ''}</span>
    <span>${tr('taken|vacation')} <b>${lv_num(p.taken)}</b></span>${p.requested ? `<span>${tr('requested')} <b>${lv_num(p.requested)}</b></span>` : ''}<span class="${p.rest < 0 ? 'lvneg' : ''}">${tr('left')} <b>${lv_num(p.rest)}</b></span></span>`;
}
// the block under the intro of the absences tab: the account(s), open requests, the admins' switch
function lv_html(ad) {
  const year = +(ad.start || today()).slice(0, 4), key = `${ad.org_id || ''}:${year}`;
  if (LV.key !== key) { LV.data = null; setTimeout(() => lv_load(ad.org_id, year), 0); return ''; }
  const d = LV.data;
  if (!d || d.error) return '';
  const own = d.people.find(p => p.own);
  const pend = d.pending.map(it => {
    const p = d.people.find(x => x.id === it.user_id);
    const btns = d.admin ? `<span class="lvbtns"><button type="button" class="btn sm pri" data-act="lv-ok" data-id="${it.id}">${ic('check', 's')} ${tr('Approve|vacation')}</button><button type="button" class="btn sm" data-act="lv-no" data-id="${it.id}">${tr('Reject')}</button></span>` : '';
    return `<li class="lvreq">${av(it.user_id, p?.display_name || '?')}<span class="ab2lt"><b>${esc(p?.display_name || '?')}</b><span class="muted">${esc(ab2_span(it))} · ${esc(it.days === 1 ? tr('1 working day') : tr('{0} working days', lv_num(it.days)))}${it.note ? ' · ' + esc(it.note) : ''}</span></span>${btns}</li>`;
  }).join('');
  const pendHtml = pend ? `<h4 class="ab2h">${d.admin ? tr('Open vacation requests') : tr('Your open vacation requests')}</h4><ul class="ab2list lvlist">${pend}</ul>` : '';
  if (!d.admin) {
    return (own?.quota ? `<div class="lvacc"><span class="lvt">${esc(tr('Your vacation {0}', String(year)))}</span>${lv_accLine(own)}</div>` : '') + pendHtml;
  }
  const rows = d.people.map(p => `<li><button type="button" class="ab2li" data-act="lv-edit" data-uid="${p.id}">${av(p.id, p.display_name)}<span class="ab2lt"><b>${esc(p.display_name)}</b><span class="muted">${esc(lv_wtText(p))}</span>${lv_accLine(p)}</span>${ic('edit', 's')}</button></li>`).join('');
  const sw = d.personal ? '' : `<div class="row lvsw"><label class="chkl"><input type="checkbox" id="lv-approval" ${d.approval ? 'checked' : ''}> ${tr('Vacation of members needs an approval')}</label></div>
      <div class="shint">${tr('On: vacation a member enters is a request until an admin approves it. Sick leave and days off need no approval. Admins entering vacation for someone approve it at once.')}</div>`;
  return `${pendHtml}<details class="lvbox"><summary>${esc(tr('Vacation accounts {0}', String(year)))}</summary>
      <ul class="ab2list">${rows}</ul>${sw}</details>`;
}
const lv_wtText = p => { const wd = p.workdays || WT_DEFAULT; return `${wd.map(i => wt_dayName(i)).join(' ')} · ${tr('{0} h / week', fmtNum(p.capacity_h, 1))}`; };

// an admin (or a person without an organisation for themselves): the account, the working days and hours of one person
function lv_sheet(p) {
  const d = LV.data, year = d.year, q = p.quota || {days: '', carry: ''};
  const md = modal(`<h3>${esc(tr('Working time and vacation of {0}', p.display_name))}</h3>
    <div class="row"><label for="lv-days">${esc(tr('Vacation days {0}', String(year)))}</label><input id="lv-days" class="numin" inputmode="decimal" value="${esc(q.days === '' ? '' : fmtNum(q.days, 1))}" placeholder="${esc(tr('none'))}"></div>
    <div class="row"><label for="lv-carry">${tr('Carry-over from last year')}</label><input id="lv-carry" class="numin" inputmode="decimal" value="${esc(q.carry ? fmtNum(q.carry, 1) : '')}" placeholder="0"></div>
    <div class="shint keep">${tr('Empty = no vacation account. Half days are fine (for example 27.5).')}</div>
    <div class="row"><span class="lbl">${tr('Working days')}</span>${wt_daysHtml('lv-wd', p.workdays || WT_DEFAULT, 'wt-mday')}</div>
    <div class="row"><label for="lv-hours">${tr('Hours per week')}</label><input id="lv-hours" class="numin" inputmode="decimal" value="${esc(p.capacity_set ? fmtNum(p.capacity_h, 2) : '')}" placeholder="${esc(fmtNum(p.capacity_h, 1))}"><span class="muted">${tr('Empty = 5 × the hours per day of the server')}</span></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${ic('check', 's')} ${tr('Save')}</button></div>`);
  md.classList.add('lvmd');
  const mq = /** @type {any} */ (md);  // 2.125.1 (#2117): for the type check ($ takes a Document)
  const numOf = v => { const t = String(v).trim().replace(',', '.'); return t === '' ? null : +t; };
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const days = numOf($('#lv-days', mq).value), carry = numOf($('#lv-carry', mq).value) || 0, hours = $('#lv-hours', mq).value.trim().replace(',', '.');
    if (days !== null && !(days >= 0 && days <= 366 && Number.isInteger(days * 2))) { toast(tr('Vacation days: whole or half days')); return; }
    if (!(carry >= 0 && carry <= 366 && Number.isInteger(carry * 2))) { toast(tr('Vacation days: whole or half days')); return; }
    const org = d.org_id, wd = wt_str(wt_daysOf($('#lv-wd', mq)));
    const before = {q: p.quota ? {days: p.quota.days, carry: p.quota.carry} : null, wd: wt_str(p.workdays || WT_DEFAULT), hours: p.capacity_set ? String(p.capacity_h) : ''};
    const after = {q: days === null ? null : {days, carry}, wd, hours};
    const put = x => async () => {
      await api('PUT', '/api/team/leave/quota', {org, user_id: p.id, year, days: x.q ? x.q.days : null, carry: x.q ? x.q.carry : 0});
      await api('PUT', `/api/team/leave/worktime/${p.id}`, {org, workdays: x.wd, hours: x.hours === '' ? null : x.hours});
      if (p.own) { S.settings.workdays = x.wd; S.settings.capacity_h = x.hours; }
      ab2_reload();
    };
    b.disabled = true;
    try { await put(after)(); histAdd({label: tr('Vacation account changed'), undo: put(before), redo: put(after)}); md.remove(); toast(tr('Saved')); } catch { b.disabled = false; /* api() said it */ }
  });
}

async function lv_decide(it, ok) {
  let note = '';
  if (!ok) { note = await askPrompt(tr('Reject the vacation request?'), '', {body: tr('An optional note for the person (only they and the admins see it).'), ok: tr('Reject'), input: {placeholder: tr('optional'), max: 500}}); if (note === null) return; }
  const step = (action, n) => async () => { await api('POST', `/api/team/absences/${it.id}/decide`, {action, note: n}); ab2_reload(); };
  try {
    await step(ok ? 'approve' : 'reject', note)();
    histAdd({label: ok ? tr('Vacation approved') : tr('Vacation rejected'), undo: step('reopen', ''), redo: step(ok ? 'approve' : 'reject', note)});
    toast(ok ? tr('Vacation approved') : tr('Vacation rejected'));
  } catch { /* api() said it */ }
}

function lv_click(a, k) {
  const d = LV.data; if (!d || d.error) return;
  if (k === 'lv-edit') { const p = d.people.find(x => x.id === +a.dataset.uid); if (p) lv_sheet(p); }
  else if (k === 'lv-ok' || k === 'lv-no') { const it = d.pending.find(x => x.id === +a.dataset.id); if (it) lv_decide(it, k === 'lv-ok'); }
}
document.addEventListener('change', async ev => {
  const e = {target: /** @type {any} */ (ev.target)};  // 2.125.1 (#2117): for the type check
  if (e.target.id !== 'lv-approval') return;
  const org = LV.data?.org_id, to = e.target.checked, put = v => async () => { await api('PUT', '/api/team/leave/approval', {org, on: v}); ab2_reload(); };
  try { await put(to)(); histAdd({label: tr('Changed setting: {0}', tr('Vacation of members needs an approval')), sett: true, undo: put(!to), redo: put(to)}); toast(tr('Saved')); } catch { e.target.checked = !to; /* api() said it */ }
});

document.addEventListener('click', async e => {
  const a = /** @type {any} */ (e.target).closest?.('[data-act^="wt-"], [data-act^="lv-"]'); if (!a || a.disabled) return;
  e.preventDefault(); e.stopPropagation();
  const k = a.dataset.act;
  if (k === 'wt-day') { const d = wt_toggle(a); if (d) await setApply({workdays: wt_str(d)}, tr('Working days')); }
  else if (k === 'wt-mday') wt_toggle(a);  // in the sheet of a person: saved with the sheet
  else if (typeof lv_click === 'function') lv_click(a, k);
});
