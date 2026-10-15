// 2.47.3 (#1652, part B): the cash flow in the office (tab "Cash flow", admins of the office area only): per month what comes
// in and goes out, actual (paid / past) and planned (expected) apart, 3 or 6 months ahead; a tap on a value lists the entries
// behind it (invoice, quotation, purchase, trip, fixed cost) with a jump to them. Fixed costs (rent, software) are entered
// here, with a repeat. Server: kalmido/office/cashflow.py. No bank access.
const RKF = {data: null, q: '', months: 3, from: '', open: null, fixed: null, err: null, oid: null};
const RK_CF_KINDS = {payment: N_('Payment'), credit: N_('Refund on a credit note'), invoice: N_('Invoice'), offer: N_('Quotation, not yet invoiced'),
  purchase: N_('Purchase'), trip: N_('Travel expenses'), fixed: N_('Fixed cost')};
const RK_CF_REPEATS = [['monthly', N_('monthly')], ['quarterly', N_('quarterly')], ['yearly', N_('yearly')], ['once', N_('once')]];
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['cashflow', 'trend', N_('Cash flow'), 1, () => rk_cashflowHtml()]);  // admins only

const rk_ym = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
const rk_ymAdd = (ym, n) => { const [y, m] = ym.split('-').map(Number); return rk_ym(new Date(y, m - 1 + n, 1)); };
async function rk_cfLoad() {
  const q = `from=${RKF.from}&months=${RKF.months}`; RKF.q = q;
  try { const j = await api('GET', '/api/office/cashflow?' + q); if (RKF.q === q) { RKF.data = j; RKF.err = null; } }
  catch (x) { RKF.err = x.message || tr('unknown'); }
  try { RKF.fixed = (await api('GET', '/api/office/fixed-costs')).items || []; } catch (x) { RKF.fixed = []; }
  ofcDraw();
}
const rk_cfReload = () => { RKF.data = null; ofcDraw(); };

function rk_cashflowHtml() {
  if (RKF.oid !== OFC.info?.org_id) Object.assign(RKF, {oid: OFC.info?.org_id, data: null, fixed: null, open: null, err: null});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see the cash flow.')}</div>`;
  if (!RKF.from) RKF.from = rk_ym();
  if (RKF.err) return `<div class="empty">${esc(RKF.err)}</div>`;
  if (!RKF.data || RKF.q !== `from=${RKF.from}&months=${RKF.months}`) { setTimeout(() => { if (RKF.q !== `from=${RKF.from}&months=${RKF.months}` || !RKF.data) rk_cfLoad(); }, 0); if (!RKF.data) return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = RKF.data;
  const bar = `<div class="ofcbar cfbar"><button class="iconbtn" data-rkf="prev" aria-label="${esc(tr('Earlier'))}">${ic('left', 's')}</button><b class="cfrange">${esc(rk_month(d.rows[0]?.month))} – ${esc(rk_month(d.rows[d.rows.length - 1]?.month))}</b><button class="iconbtn" data-rkf="next" aria-label="${esc(tr('Later'))}">${ic('right', 's')}</button>
    ${RKF.from !== rk_ym() ? `<button class="btn sm ghost" data-rkf="now">${tr('Today')}</button>` : ''}<span class="spacer"></span>
    <div class="seg" role="group" aria-label="${esc(tr('Preview'))}">${[3, 6].map(n => `<button type="button" data-rkf="months" data-v="${n}" class="${RKF.months === n ? 'on' : ''}" aria-pressed="${RKF.months === n}">${esc(trn('{0} month', '{0} months', n))}</button>`).join('')}</div></div>`;
  const val = (mo, dir, st, v, cls = '') => +v ? `<button type="button" class="cfv ${cls}" data-rkf="open" data-k="${mo}|${dir}|${st}" aria-expanded="${RKF.open === `${mo}|${dir}|${st}`}">${ofcMoney(v)}</button>` : `<span class="cfv cfz muted">–</span>`;
  const max = Math.max(1, ...d.rows.flatMap(r => [+r.in.actual + +r.in.plan, +r.out.actual + +r.out.plan]));
  const bars = r => `<div class="cfbars" aria-hidden="true"><span class="cfbin" style="transform:scaleX(${((+r.in.actual + +r.in.plan) / max).toFixed(3)})"></span><span class="cfbout" style="transform:scaleX(${((+r.out.actual + +r.out.plan) / max).toFixed(3)})"></span></div>`;
  const cards = d.rows.map(r => {
    const k = RKF.open?.startsWith(r.month + '|') ? RKF.open : null;
    return `<section class="cfm ${r.current ? 'cur' : ''}" aria-label="${esc(rk_month(r.month))}"><header><b>${esc(rk_month(r.month))}</b>${r.current ? `<span class="rotag">${tr('this month')}</span>` : ''}<span class="spacer"></span>
      <span class="cfbal ${+r.balance < 0 ? 'neg' : ''}">${tr('Balance')} ${ofcMoney(r.balance)}</span></header>${bars(r)}
      <table class="cftab"><thead><tr><th></th><th class="num">${tr('Actual')}</th><th class="num">${tr('Planned')}</th></tr></thead><tbody>
      <tr><th>${tr('In|cashflow')}</th><td class="num">${val(r.month, 'in', 'actual', r.in.actual)}</td><td class="num">${val(r.month, 'in', 'plan', r.in.plan, 'plan')}</td></tr>
      <tr><th>${tr('Out|cashflow')}</th><td class="num">${val(r.month, 'out', 'actual', r.out.actual)}</td><td class="num">${val(r.month, 'out', 'plan', r.out.plan, 'plan')}</td></tr></tbody></table>
      ${k ? rk_cfEntries(k) : ''}</section>`;
  }).join('');
  return bar + `<div class="cfms">${cards}</div><p class="muted ofchint">${tr('Actual = paid or already past; planned = expected (open invoices on their due date, accepted quotations not yet invoiced at the end of their period of service). Amounts of documents incl. VAT.')}</p>` + rk_fixedHtml();
}
function rk_cfEntries(k) {
  const [mo, dir, st] = k.split('|');
  const es = (RKF.data.entries || []).filter(e => e.month === mo && e.dir === dir && e.state === st);
  const go = e => e.doc_id ? `href="#office/offers/${e.doc_id}"` : e.trip_id ? `href="#office/travel" data-rkf="trip" data-id="${e.trip_id}"` : e.fixed_id ? `href="#" data-rkf="fixed" data-id="${e.fixed_id}"` : '';
  return `<ul class="ofclist cfents" role="list">${es.map(e => `<li><a class="ofcrow" ${go(e)}><span class="ofcn"><b>${esc(tr(RK_CF_KINDS[e.kind] || e.kind))}${e.number ? ` ${esc(e.number)}` : ''}</b>
    <small class="muted">${esc([fmtDateLoc(e.date), e.label, e.overdue ? tr('Overdue') : '', e.partial ? tr('the rest after part invoices') : ''].filter(Boolean).join(' · '))}</small></span><span class="rksum">${ofcMoney(e.amount)}</span>${ic('chev', 's')}</a></li>`).join('')}</ul>`;
}
function rk_fixedHtml() {
  const fx = RKF.fixed || [], rp = k => tr(RK_CF_REPEATS.find(x => x[0] === k)?.[1] || k);
  return `<div class="ofcbar"><h3 class="ofcgrp">${tr('Fixed costs')}</h3><span class="spacer"></span><button class="btn sm pri" data-rkf="fnew">${ic('plus', 's')}<span>${tr('New fixed cost')}</span></button></div>`
    + (fx.length ? `<ul class="ofclist" role="list">${fx.map(f => `<li><button type="button" class="ofcrow" data-rkf="fixed" data-id="${f.id}"><span class="ofcn"><b>${esc(f.label)}</b><small class="muted">${esc([rp(f.repeat), tr('from {0}', fmtDateLoc(f.start)), f.until ? tr('until {0}', fmtDateLoc(f.until)) : ''].filter(Boolean).join(' · '))}</small></span><span class="rksum">${ofcMoney(f.amount)}</span>${ic('chev', 's')}</button></li>`).join('')}</ul>`
      : `<p class="muted lempty">${tr('No fixed costs yet, e.g. rent or software subscriptions.')}</p>`);
}
function rk_fixedModal(f) {
  const md = modal(`<h3>${f ? tr('Edit fixed cost') : tr('New fixed cost')}</h3>
    ${ofcRowF('cf-label', tr('Name'), ofcIn('cf-label', f?.label, {ph: tr('e.g. Rent')}))}
    ${ofcRowF('cf-amount', tr('Amount'), ofcIn('cf-amount', f ? fmtNum(+f.amount, 2) : '', {num: true}), ofcCur())}
    ${ofcRowF('cf-repeat', tr('Repeat'), ofcSel('cf-repeat', f?.repeat || 'monthly', RK_CF_REPEATS.map(([k, n]) => [k, tr(n)])))}
    <div class="row"><label id="cf-startl">${tr('First due date')}</label>${dateIn('cf-start', f?.start || new Date().toISOString().slice(0, 10), {label: tr('First due date'), clear: false})}</div>
    <div class="row"><label id="cf-untill">${tr('Ends on')}</label>${dateIn('cf-until', f?.until || '', {label: tr('Ends on'), empty: tr('open-ended')})}</div>
    <div class="aerr" role="alert"></div>
    <div class="foot">${f ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${f ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        const j = await api('DELETE', `/api/office/fixed-costs/${f.id}`); md.remove(); rk_cfReload();
        const o = j.item; toast(tr('Deleted'), async () => { await api('POST', '/api/office/fixed-costs', {label: o.label, amount: o.amount, start: o.start, until: o.until, repeat: o.repeat}); rk_cfReload(); });
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const body = {label: v('#cf-label'), amount: ofcNum(v('#cf-amount')), repeat: v('#cf-repeat'), start: v('#cf-start'), until: v('#cf-until')};
      if (f) {
        const old = {label: f.label, amount: f.amount, repeat: f.repeat, start: f.start, until: f.until};
        await api('PATCH', `/api/office/fixed-costs/${f.id}`, body); md.remove(); rk_cfReload();
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/fixed-costs/${f.id}`, old); rk_cfReload(); });
      } else {
        const j = await api('POST', '/api/office/fixed-costs', body); md.remove(); rk_cfReload();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/fixed-costs/${j.id}`); rk_cfReload(); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-rkf]'); if (!b) return;
  const a = b.dataset.rkf;
  if (a === 'prev' || a === 'next') { RKF.from = rk_ymAdd(RKF.from || rk_ym(), a === 'prev' ? -1 : 1); RKF.open = null; ofcDraw(); }
  else if (a === 'now') { RKF.from = rk_ym(); RKF.open = null; ofcDraw(); }
  else if (a === 'months') { RKF.months = +b.dataset.v; ofcDraw(); }
  else if (a === 'open') { RKF.open = RKF.open === b.dataset.k ? null : b.dataset.k; ofcDraw(); }
  else if (a === 'fnew') rk_fixedModal(null);
  else if (a === 'fixed') { const f = (RKF.fixed || []).find(x => x.id === +b.dataset.id); if (f) rk_fixedModal(f); }
  else if (a === 'trip') { if (typeof RK === 'object') { RK.open = +b.dataset.id; RK.view = 'trips'; RK.year = ''; RK.data = null; } return; }  // the link itself opens the tab
  else return;
  e.preventDefault();
});
