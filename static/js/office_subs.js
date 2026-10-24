// 2.91.0 B (#1924): subscriptions and tools in the office (tab "Subscriptions & tools", admins of the office area only): the
// fixed costs marked as a subscription with price, repeat, notice period, users, "hardly used" and a reminder before the
// last day to cancel; sums per month / year and what the hardly used ones cost a year. The rows ARE fixed costs: every
// change goes through /api/office/fixed-costs (the cash flow counts them once). Server: kalmido/office/subs.py.
const ABO = {data: null, err: null, oid: null, low: false, loading: false, basis: LS.get('cfBasis', 'gross') === 'net' ? 'net' : 'gross'};
const ABO_SOON = 14;  // "cancel by" in red below this many days
OFC_TABS.splice(Math.max(0, OFC_TABS.findIndex(t => t[0] === 'cashflow' || t[0] === 'settings')), 0, ['subs', 'repeat', N_('Subscriptions & tools'), 1, () => aboHtml(), 'money']);  // admins only; 2.92.1 (#1917): in the menu group Money

// the subscription fields of a fixed cost as the routes take them (the undo of a delete posts them again)
const aboFields = o => ({sub: o.sub || 0, notice_days: o.notice_days || 0, seats: o.seats || [], low_use: o.low_use || 0, remind_days: o.remind_days || 0, remind_user: o.remind_user || null, url: o.url || ''});
async function aboLoad() {
  if (ABO.loading) return;
  ABO.loading = true;
  try { ABO.data = await api('GET', '/api/office/subs'); ABO.err = null; } catch (x) { ABO.err = x.message || tr('unknown'); }
  ABO.loading = false;
  ofcDraw();
}
const aboReload = () => { ABO.data = null; if (typeof RKF === 'object') RKF.data = null; ofcDraw(); };
const aboDays = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
const aboNet = () => ABO.basis === 'net';
const aboPer = (o, k) => o[aboNet() ? k + '_net' : k];
const aboRp = k => tr(({monthly: N_('monthly'), quarterly: N_('quarterly'), yearly: N_('yearly'), once: N_('once')})[k] || k);
function aboSeatsShort(f) {
  const n = (f.seat_names || []).map(x => x || tr('former member'));
  return n.length > 3 ? `${n.slice(0, 3).join(', ')} +${n.length - 3}` : n.join(', ');
}

function aboHtml() {
  if (ABO.oid !== OFC.info?.org_id) Object.assign(ABO, {oid: OFC.info?.org_id, data: null, err: null});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only for admins of the office.')}</div>`;
  if (ABO.err) return `<div class="empty">${esc(ABO.err)}</div>`;
  if (!ABO.data) { setTimeout(aboLoad, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = ABO.data, t = d.totals, net = aboNet();
  const bar = `<div class="ofcbar abo-bar"><h3 class="ofcgrp">${tr('Subscriptions & tools')}</h3><span class="spacer"></span>
    <div class="seg fcibasis" role="group" aria-label="${esc(tr('Amounts'))}">${[['net', tr('Net')], ['gross', tr('Gross')]].map(([k, n]) => `<button type="button" data-abo="basis" data-v="${k}" class="${ABO.basis === k ? 'on' : ''}" aria-pressed="${ABO.basis === k}">${esc(n)}</button>`).join('')}</div>
    ${d.items.length ? `<a class="btn sm ghost" href="/api/office/subs.csv" download>${ic('download', 's')}<span>CSV</span></a>` : ''}
    <button class="btn sm pri" data-abo="new">${ic('plus', 's')}<span>${tr('Subscription')}</span></button></div>`;
  if (!d.items.length) return bar + `<div class="abo-empty"><p class="muted">${tr('No subscriptions yet. Mark fixed costs as a subscription to see their monthly and yearly cost.')}</p><button class="btn pri" data-abo="new">${ic('plus', 's')}<span>${tr('Add a subscription')}</span></button>${oim_link('fixed', true)}</div>` + aboCandHtml(d);  // 2.122.3 A (#2335): + the import link
  const head = `<div class="abo-sums"><div class="abo-sum"><span class="muted">${tr('per month')}</span><b>${ofcMoney(net ? t.per_month_net : t.per_month)}</b></div><div class="abo-sum"><span class="muted">${tr('per year')}</span><b>${ofcMoney(net ? t.per_year_net : t.per_year)}</b></div></div>
    ${t.low_use_count ? `<button type="button" class="abo-low ${ABO.low ? 'on' : ''}" data-abo="lowf" aria-pressed="${ABO.low}">${ic('bulb', 's')}<span>${esc(trn('Hardly used: {0} subscription, {1} a year', 'Hardly used: {0} subscriptions, {1} a year', t.low_use_count, ofcMoney(net ? t.low_use_per_year_net : t.low_use_per_year)))}</span>${ABO.low ? `<small class="muted">${tr('show all')}</small>` : ''}</button>` : ''}
    <div class="muted ofchint">${net ? tr('Net, without VAT.') : tr('Gross, incl. VAT.')}<div class="shint">${tr('Quarterly and yearly amounts are spread over the months; one-off costs are not counted.')}</div></div>`;  // 2.298.0 A2 (#3186): the spreading rule behind (i)
  const items = ABO.low ? d.items.filter(f => f.low_use && f.running) : d.items;
  return bar + head + `<ul class="ofclist abo-list" role="list">${items.map(f => aboRowHtml(f, d.today)).join('')}</ul>` + oim_link('fixed') + aboCandHtml(d);
}
// 2.122.3 A (#2333): without VAT the amount says "without VAT" instead of "net"
function aboRowHtml(f, today) {
  // 2.144.5 C (#2021): a missed notice period shows the next chance instead of the past date
  const cb = f.cancel_missed ? f.cancel_next : f.cancel_by, left = cb ? aboDays(today, cb) : null;
  const when = [f.next_renewal ? tr('renews {0}', fmtDateLoc(f.next_renewal)) : f.running ? '' : tr('ended')];
  const ctxt = f.cancel_missed ? (cb ? tr('Notice period missed, next chance {0}', fmtDateLoc(cb)) : tr('Notice period missed')) : cb ? tr('cancel by {0}', fmtDateLoc(cb)) : '';
  const cancel = ctxt ? `<span class="abo-cancel${f.cancel_missed ? ' missed' : ''} ${cb && left < ABO_SOON ? 'soon' : ''}">${esc(ctxt)}</span>` : '';
  const users = aboSeatsShort(f);
  return `<li class="abo-row ${f.running ? '' : 'arch'} ${f.low_use ? 'low' : ''}"><button type="button" class="ofcrow abo-main" data-abo="edit" data-id="${f.id}">
      <span class="ofcn"><b>${esc(f.label)}${f.url ? ` ${ic('link', 's')}` : ''}${f.remind_days && f.remind_user ? ` <span class="abo-bell" title="${esc(tr('Reminder on'))}">${ic('bell', 's')}</span>` : ''}</b>
      <small class="muted">${esc([`${ofcMoney(f.amount)} ${+f.vat_rate ? tr('net') : tr('without VAT')} ${aboRp(f.repeat)}`, ...when].filter(Boolean).join(' · '))}</small>
      ${cancel || users ? `<small class="abo-meta">${cancel}${users ? `<span class="muted">${ic('users', 's')} ${esc(users)}</span>` : ''}</small>` : ''}</span>
      <span class="rksum abo-per"><span>${ofcMoney(aboPer(f, 'per_month'))}</span><small class="muted">${tr('per month')}</small></span></button>
    <label class="chkl swl abo-sw"><span class="swc"><input type="checkbox" role="switch" data-abo-low="${f.id}" ${f.low_use ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('hardly used')}</span></label></li>`;
}
function aboCandHtml(d) {
  if (!d.candidates.length) return '';
  return `<div class="ofcbar"><h3 class="ofcgrp">${tr('Suggestions')}</h3></div><p class="muted ofchint">${tr('These fixed costs look like a subscription or a tool.')}</p>
    <ul class="ofclist abo-cands" role="list">${d.candidates.map(f => `<li class="abo-cand"><span class="ofcn"><b>${esc(f.label)}</b><small class="muted">${esc([f.category, `${ofcMoney(aboNet() ? f.per_month_net : f.per_month)} ${tr('per month')}`].filter(Boolean).join(' · '))}</small></span><button class="btn sm" data-abo="mark" data-id="${f.id}">${tr('Mark as subscription')}</button></li>`).join('')}</ul>`;
}

async function aboPatch(id, body, old, msg) {
  await api('PATCH', `/api/office/fixed-costs/${id}`, body); aboReload();
  toast(msg, async () => { await api('PATCH', `/api/office/fixed-costs/${id}`, old); aboReload(); });
}
function aboModal(f) {
  const d = ABO.data || {}, ppl = d.people || [], rp = d.remind_people || [];
  const ids = new Set((f?.seats || []).filter(x => typeof x === 'number')), free = (f?.seats || []).filter(x => typeof x === 'string');
  const gone = [...ids].filter(i => !ppl.some(p => p.id === i));  // people no longer in the area stay ticked until unticked
  const seat = (id, name) => `<label class="chkl"><input type="checkbox" data-abo-seat="${id}" ${ids.has(id) ? 'checked' : ''}> ${esc(name)}</label>`;
  const md = modal(`<h3>${f ? tr('Edit subscription') : tr('New subscription')}</h3>
    ${ofcRowF('abo-label', tr('Name'), ofcIn('abo-label', f?.label, {ph: tr('e.g. Design software')}))}
    ${ofcRowF('abo-amount', tr('Amount'), ofcIn('abo-amount', f ? fmtNum(+f.amount, 2) : '', {num: true}), ofcCur(), {keep: 1})}
    ${ofcRowF('abo-vat', tr('VAT rate'), ofcSel('abo-vat', f?.vat_rate ?? 19, FCI_VATS.map(v => [v, `${v} %`])), tr('The amount is net.'), {keep: 1})}
    ${ofcRowF('abo-repeat', tr('Repeat'), ofcSel('abo-repeat', f?.repeat || 'monthly', RK_CF_REPEATS.map(([k, n]) => [k, tr(n)])))}
    ${ofcRowF('abo-category', tr('Category'), ofcIn('abo-category', f ? f.category : tr('Software'), {max: 100}))}
    <div class="row"><label id="abo-startl">${tr('First due date')}</label>${dateIn('abo-start', f?.start || today(), {label: tr('First due date'), clear: false})}</div>
    <div class="row"><label id="abo-untill">${tr('Ends on')}</label>${dateIn('abo-until', f?.until || '', {label: tr('Ends on'), empty: tr('open-ended'), after: 'abo-start'})}</div>
    <div class="row"><label for="abo-notice">${tr('Notice period (days)')}</label><span class="abo-notice"><input id="abo-notice" type="number" inputmode="numeric" min="0" max="730" step="1" value="${+f?.notice_days || 0}">
      ${[[30, tr('approx. 1 month')], [90, tr('approx. 3 months')]].map(([n, l]) => `<button type="button" class="btn sm ghost" data-abo-nd="${n}">${esc(l)}</button>`).join('')}</span><span class="muted ofchint">${tr('Days before the renewal; 0 = none.')}</span></div>
    <div class="row"><label>${tr('Used by')}</label><div class="abo-seats">${ppl.map(p => seat(p.id, p.name)).join('')}${gone.map(i => seat(i, tr('former member'))).join('')}</div></div>
    ${ofcRowF('abo-free', tr('Further people'), ofcIn('abo-free', free.join(free.some(x => x.includes(',')) ? '; ' : ', '), {max: 2000, ph: tr('Names, separated by commas')}))}
    <div class="row"><label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" id="abo-low" ${f?.low_use ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('hardly used')}</span></label></div>
    <div class="row"><label for="abo-rdays">${tr('Reminder')}</label><span class="abo-notice"><input id="abo-rdays" type="number" inputmode="numeric" min="0" max="90" step="1" value="${+f?.remind_days || 0}">
      ${ofcSel('abo-ruser', f?.remind_user || (f ? '' : S.me?.id), rp.map(p => [p.id, p.name]).concat(f?.remind_user && !rp.some(p => p.id === f.remind_user) ? [[f.remind_user, tr('Person without access')]] : []), tr('nobody'))}</span>
      <span class="muted ofchint">${tr('Days before the last day to cancel; 0 = no reminder.')}</span></div>
    ${ofcRowF('abo-url', tr('Web address'), `<input id="abo-url" type="url" inputmode="url" maxlength="500" value="${esc(f?.url || '')}" placeholder="https://">`)}
    <div class="aerr" role="alert"></div>
    <div class="foot">${f ? `<button class="btn danger" data-m="del">${tr('Delete')}</button><button class="btn ghost" data-m="unsub">${tr('No subscription')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${f ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg', 'abo-dlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const nd = e.target.closest('[data-abo-nd]'); if (nd) { $('#abo-notice', md).value = nd.dataset.aboNd; return; }
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        const j = await api('DELETE', `/api/office/fixed-costs/${f.id}`); md.remove(); aboReload();
        const o = j.item; toast(tr('Deleted'), async () => { await api('POST', '/api/office/fixed-costs', {label: o.label, amount: o.amount, start: o.start, until: o.until, repeat: o.repeat, category: o.category || '', vat_rate: o.vat_rate || 0, ...aboFields(o)}); aboReload(); });
        return;
      }
      if (b.dataset.m === 'unsub') { md.remove(); await aboPatch(f.id, {sub: 0}, {sub: 1}, tr('No longer a subscription')); return; }
      const v = id => $(id, md)?.value ?? '';
      const seats = [...md.querySelectorAll('[data-abo-seat]')].filter(x => x.checked).map(x => +x.dataset.aboSeat)
        .concat((x => x.split(x.includes(';') ? ';' : ','))(v('#abo-free')).map(x => x.trim()).filter(Boolean));  // 2.91.0 review L5: a name with a comma survives (shown and split with ';')
      const body = {label: v('#abo-label'), amount: ofcNum(v('#abo-amount')), repeat: v('#abo-repeat'), start: v('#abo-start'), until: v('#abo-until'), category: v('#abo-category'),
        vat_rate: +v('#abo-vat') || 0, sub: 1, notice_days: Math.max(0, Math.round(+v('#abo-notice') || 0)), seats, low_use: $('#abo-low', md).checked ? 1 : 0,
        remind_days: Math.max(0, Math.round(+v('#abo-rdays') || 0)), remind_user: +v('#abo-ruser') || null, url: v('#abo-url').trim()};
      if (f) {
        const old = {label: f.label, amount: f.amount, repeat: f.repeat, start: f.start, until: f.until, category: f.category || '', vat_rate: f.vat_rate || 0, ...aboFields(f)};
        await api('PATCH', `/api/office/fixed-costs/${f.id}`, body); md.remove(); aboReload();
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/fixed-costs/${f.id}`, old); aboReload(); });
      } else {
        const j = await api('POST', '/api/office/fixed-costs', body); md.remove(); aboReload();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/fixed-costs/${j.id}`); aboReload(); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}

document.addEventListener('change', async e => {
  const t = e.target.closest?.('[data-abo-low]'); if (!t) return;
  const id = +t.dataset.aboLow, on = t.checked ? 1 : 0;
  try { await aboPatch(id, {low_use: on}, {low_use: on ? 0 : 1}, on ? tr('Marked as hardly used') : tr('No longer marked as hardly used')); }
  catch (x) { toast(x.message || tr('unknown')); aboReload(); }
});
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-abo]'); if (!b) return;
  const a = b.dataset.abo;
  if (a === 'go') { ABO.data = null; return; }  // the link itself opens the tab
  e.preventDefault();
  if (a === 'basis') { ABO.basis = b.dataset.v === 'net' ? 'net' : 'gross'; LS.set('cfBasis', ABO.basis); if (typeof RKF === 'object') RKF.basis = ABO.basis; ofcDraw(); }
  else if (a === 'lowf') { ABO.low = !ABO.low; ofcDraw(); }
  else if (a === 'new') aboModal(null);
  else if (a === 'edit') { const f = (ABO.data?.items || []).find(x => x.id === +b.dataset.id); if (f) aboModal(f); }
  else if (a === 'mark') {
    try { await aboPatch(+b.dataset.id, {sub: 1}, {sub: 0}, tr('Marked as subscription')); } catch (x) { toast(x.message || tr('unknown')); }
  }
});
