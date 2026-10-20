// 2.47.3 (#1652, part B): the cash flow in the office (tab "Cash flow", admins of the office area only): per month what comes
// in and goes out, actual (paid / past) and planned (expected) apart, 3 or 6 months ahead; a tap on a value lists the entries
// behind it (invoice, quotation, purchase, trip, fixed cost) with a jump to them. Fixed costs (rent, software) are entered
// here, with a repeat. Server: kalmido/office/cashflow.py. No bank access.
const RKF = {data: null, q: '', months: 3, from: '', open: null, fixed: null, agr: null, err: null, oid: null, basis: LS.get('cfBasis', 'gross') === 'net' ? 'net' : 'gross', check: null};  // 2.67.0 (#1838): basis, check
const RK_CF_KINDS = {payment: N_('Payment'), credit: N_('Refund on a credit note'), invoice: N_('Invoice'), offer: N_('Quotation, not yet invoiced'),
  purchase: N_('Purchase'), trip: N_('Travel expenses'), fixed: N_('Fixed cost'), series: N_('Invoice series|cashflow'), agreement: N_('Contract or insurance'), receipt: N_('Receipt')};  // 2.91.0 A (#1923): series; 2.92.0 A (#1925): agreement; 2.114.1 B (#2018): receipt
const RK_CF_REPEATS = [['monthly', N_('monthly')], ['quarterly', N_('quarterly')], ['yearly', N_('yearly')], ['once', N_('once')]];
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['cashflow', 'trend', N_('Cash flow'), 1, () => rk_cashflowHtml()]);  // admins only

const rk_ym = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
const rk_ymAdd = (ym, n) => { const [y, m] = ym.split('-').map(Number); return rk_ym(new Date(y, m - 1 + n, 1)); };
async function rk_cfLoad() {
  const q = rk_cfQ(); RKF.q = q;
  try { const j = await api('GET', '/api/office/cashflow?' + q); if (RKF.q === q) { RKF.data = j; RKF.err = null; } }
  catch (x) { RKF.err = x.message || tr('unknown'); }
  try { const fj = await api('GET', '/api/office/fixed-costs'); RKF.fixed = fj.items || []; RKF.agr = fj.agreements || []; } catch (x) { RKF.fixed = []; RKF.agr = []; }  // 2.92.0 A (#1925): agr
  try { RKF.check = await api('GET', '/api/office/cashflow/check'); } catch (x) { RKF.check = null; }  // 2.67.0 (#1838)
  ofcDraw();
}
const rk_cfReload = () => { RKF.data = null; ofcDraw(); };
const rk_cfQ = () => `from=${RKF.from}&months=${RKF.months}&basis=${RKF.basis}`;  // 2.67.0 (#1838): net | gross

function rk_cashflowHtml() {
  if (RKF.oid !== OFC.info?.org_id) Object.assign(RKF, {oid: OFC.info?.org_id, data: null, fixed: null, open: null, err: null});  // another office area
  if (!ofcAdmin()) return `<div class="empty">${tr('Only the admins of the office see the cash flow.')}</div>`;
  if (!RKF.from) RKF.from = rk_ym();
  if (RKF.err) return `<div class="empty">${esc(RKF.err)}</div>`;
  if (!RKF.data || RKF.q !== rk_cfQ()) { setTimeout(() => { if (RKF.q !== rk_cfQ() || !RKF.data) rk_cfLoad(); }, 0); if (!RKF.data) return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = RKF.data;
  const bar = `<div class="ofcbar rkcfbar"><button class="iconbtn" data-rkf="prev" aria-label="${esc(tr('Earlier'))}">${ic('left', 's')}</button><b class="rkcfrange">${esc(rk_month(d.rows[0]?.month))} – ${esc(rk_month(d.rows[d.rows.length - 1]?.month))}</b><button class="iconbtn" data-rkf="next" aria-label="${esc(tr('Later'))}">${ic('right', 's')}</button>
    ${RKF.from !== rk_ym() ? `<button class="btn sm ghost" data-rkf="now">${tr('Today')}</button>` : ''}<span class="spacer"></span>
    <div class="seg" role="group" aria-label="${esc(tr('Preview'))}">${[3, 6].map(n => `<button type="button" data-rkf="months" data-v="${n}" class="${RKF.months === n ? 'on' : ''}" aria-pressed="${RKF.months === n}">${esc(trn('{0} month', '{0} months', n))}</button>`).join('')}</div>
    <div class="seg fcibasis" role="group" aria-label="${esc(tr('Amounts'))}">${[['net', tr('Net')], ['gross', tr('Gross')]].map(([k, n]) => `<button type="button" data-rkf="basis" data-v="${k}" class="${RKF.basis === k ? 'on' : ''}" aria-pressed="${RKF.basis === k}">${esc(n)}</button>`).join('')}</div></div>`;
  const val = (mo, dir, st, v, cls = '') => +v ? `<button type="button" class="rkcfv ${cls}" data-rkf="open" data-k="${mo}|${dir}|${st}" aria-expanded="${RKF.open === `${mo}|${dir}|${st}`}">${ofcMoney(v)}</button>` : `<span class="rkcfv rkcfz muted">–</span>`;
  const max = Math.max(1, ...d.rows.flatMap(r => [+r.in.actual + +r.in.plan, +r.out.actual + +r.out.plan]));
  const bars = r => `<div class="rkcfbars" aria-hidden="true"><span class="rkcfbin" style="transform:scaleX(${((+r.in.actual + +r.in.plan) / max).toFixed(3)})"></span><span class="rkcfbout" style="transform:scaleX(${((+r.out.actual + +r.out.plan) / max).toFixed(3)})"></span></div>`;
  const cards = d.rows.map(r => {
    const k = RKF.open?.startsWith(r.month + '|') ? RKF.open : null;
    return `<section class="rkcfm ${r.current ? 'cur' : ''}" aria-label="${esc(rk_month(r.month))}"><header><b>${esc(rk_month(r.month))}</b>${r.current ? `<span class="rotag">${tr('this month')}</span>` : ''}<span class="spacer"></span>
      <span class="rkcfbal ${+r.balance < 0 ? 'neg' : ''}">${tr('Balance')} ${ofcMoney(r.balance)}</span></header>${bars(r)}
      <table class="rkcftab"><thead><tr><th></th><th class="num">${tr('Actual')}</th><th class="num">${tr('Planned')}</th></tr></thead><tbody>
      <tr><th>${tr('In|cashflow')}</th><td class="num">${val(r.month, 'in', 'actual', r.in.actual)}</td><td class="num">${val(r.month, 'in', 'plan', r.in.plan, 'plan')}</td></tr>
      <tr><th>${tr('Out|cashflow')}</th><td class="num">${val(r.month, 'out', 'actual', r.out.actual)}</td><td class="num">${val(r.month, 'out', 'plan', r.out.plan, 'plan')}</td></tr>${bk_cfReserveRows(r)}</tbody></table>
      ${rk_cfOpenHtml(r.month)}${k ? rk_cfEntries(k) : ''}</section>`;
  }).join('');
  return bar + `<div class="rkcfms">${cards}</div><p class="muted ofchint">${tr('Actual = paid or already past; planned = expected (open invoices on their due date, sent and accepted quotations without an invoice at the end of their period of service, one version per quotation).')} ${d.basis === 'net' ? tr('Net: documents and fixed costs without VAT; purchases and travel receipts as entered.') : tr('Gross: documents and fixed costs incl. VAT; purchases and travel receipts as entered.')}</p>` + rk_fixedHtml() + fci_checkHtml();
}
// 2.90.0 A (#1921): with a tax reserve (Bookkeeping, tax_reserve_pct > 0): the month's reserve and what is free after all reserves so far
const bk_cfReserveRows = r => r.reserve == null ? '' : `<tr class="bk-cfres"><th>${tr('Tax reserve')}</th><td class="num" colspan="2">${ofcMoney(r.reserve)}</td></tr>
      <tr class="bk-cffree"><th>${tr('Freely available')}</th><td class="num ${+r.free < 0 ? 'neg' : ''}" colspan="2">${ofcMoney(r.free)}</td></tr>`;
function rk_cfEntries(k) {
  const [mo, dir, st] = k.split('|');
  const es = (RKF.data.entries || []).filter(e => e.month === mo && e.dir === dir && e.state === st);
  const go = e => e.doc_id ? `href="#office/offers/${e.doc_id}"` : e.series_id ? `href="#office/offers" data-rin-go="${e.series_id}"` : e.trip_id ? `href="#office/travel" data-rkf="trip" data-id="${e.trip_id}"` : e.fixed_id ? `href="#" data-rkf="fixed" data-id="${e.fixed_id}"` : e.agreement_id ? `href="#office/agreements/${e.agreement_id}"` : e.node_id ? `href="#docs/${e.node_id}"` : '';  // 2.92.0 A (#1925); 2.114.1 B (#2018): a receipt opens the document
  // 2.88.0 (#1915): a sent quotation = an open quotation (dashed, lighter); a chain with an invoice no longer shows a rest
  return `<ul class="ofclist rkcfents" role="list">${es.map(e => `<li${e.open_offer ? ' class="rkcfopen"' : ''}><a class="ofcrow" ${go(e)}><span class="ofcn"><b>${esc(e.open_offer ? tr('Open quotation|cashflow') : tr(RK_CF_KINDS[e.kind] || e.kind))}${e.number ? ` ${esc(e.number)}` : ''}</b>
    <small class="muted">${esc([fmtDateLoc(e.date), e.label, e.overdue ? tr('Overdue') : ''].filter(Boolean).join(' · '))}</small></span><span class="rksum">${ofcMoney(e.amount)}</span>${ic('chev', 's')}</a></li>`).join('')}</ul>`;
}
// 2.88.0 (#1915): the share of open (sent, not yet accepted) quotations in a month's planned income, marked apart
function rk_cfOpenHtml(mo) {
  const sum = (RKF.data.entries || []).filter(e => e.month === mo && e.open_offer).reduce((a, e) => a + +e.amount, 0);
  return sum ? `<p class="rkcfopenl muted">${esc(tr('Planned incl. open quotations: {0}', ofcMoney(sum)))}</p>` : '';
}
// 2.88.0 (#1915): in a quotation's editor, the choice "In the cash flow" (automatic / yes / no) and which version counts;
// planning only (not printed), so also for sent and finalised quotations; one undo step
const CF8_OPTS = [['auto', N_('Automatic')], ['yes', N_('Yes')], ['no', N_('No')]];
function cf8_box(d) {
  const ch = d.cf_chain; if (d.kind !== 'offer' || !ch) return '';
  const vs = ch.versions || [], others = vs.filter(v => v.counts && v.id !== d.id).map(v => v.number || tr('Draft'));
  const hint = ch.invoiced ? tr('An invoice exists for this quotation or one of its versions: the invoice counts, no version of the quotation.')
    : ch.counts ? (d.status === 'sent' ? tr('This version counts in the cash flow as an open quotation.') : tr('This version counts in the cash flow.'))
    : others.length ? tr('Counts instead: {0}', others.join(', '))
    : ['sent', 'accepted'].includes(d.status) || !vs.some(v => ['sent', 'accepted'].includes(v.status)) ? tr('No version counts at the moment; only sent and accepted quotations count.') : tr('This version does not count.');
  const ver = vs.length > 1 ? `<p class="muted cf8vers">${esc(tr('Version {0} of {1}', vs.findIndex(v => v.id === d.id) + 1, vs.length))}</p>` : '';
  return `<section class="ofdsec open cf8sec"><h3>${tr('In the cash flow')}</h3><div class="seg" role="group" aria-label="${esc(tr('In the cash flow'))}">${CF8_OPTS.map(([k, n]) => `<button type="button" data-cf8="${k}" data-doc="${d.id}" class="${ch.cashflow === k ? 'on' : ''}" aria-pressed="${ch.cashflow === k}">${esc(tr(n))}</button>`).join('')}</div>
    <p class="cf8hint ofchint" role="status">${esc(hint)}</p>${ver}</section>`;
}
async function cf8_set(did, v) {
  const j = await api('POST', `/api/office/docs/${did}/cashflow`, {cashflow: v});
  if (OFD.doc?.id === did) { OFD.doc.cashflow = j.cashflow; OFD.doc.cf_chain = j.cf_chain; ofdDraw(); }
  RKF.data = null;  // the plan is computed again when it is opened
  return j;
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-cf8]'); if (!b) return;
  const did = +b.dataset.doc, v = b.dataset.cf8, from = OFD.doc?.id === did ? OFD.doc.cf_chain?.cashflow || 'auto' : 'auto';
  if (v === from) return;
  try { await cf8_set(did, v); } catch (x) { toast(x.message || tr('unknown')); return; }
  offerUndo(tr('Saved'), histAdd({label: tr('Cash flow choice changed'), undo: () => cf8_set(did, from), redo: () => cf8_set(did, v)}));
});
function rk_fixedHtml() {
  const fx = RKF.fixed || [], rp = k => tr(RK_CF_REPEATS.find(x => x[0] === k)?.[1] || k);
  // 2.67.0 (#1838): grouped by category (without one last), net and gross per row; import from a spreadsheet + its template
  // 2.122.3 A (#2335): template + import moved to Settings > Import legacy data (office_import.js), here only a link to it
  const cats = [...new Set(fx.map(f => f.category || ''))].sort((a, b) => !a - !b || a.localeCompare(b, undefined, {sensitivity: 'base'}));
  const row = f => `<li><button type="button" class="ofcrow" data-rkf="fixed" data-id="${f.id}"><span class="ofcn"><b>${esc(f.label)}${f.sub ? ` <span class="abo-tag">${tr('Subscription')}</span>` : ''}</b><small class="muted">${esc([rp(f.repeat), tr('from {0}', fmtDateLoc(f.start)), f.until ? tr('until {0}', fmtDateLoc(f.until)) : '', +f.vat_rate ? tr('VAT {0} %', f.vat_rate) : tr('without VAT')].filter(Boolean).join(' · '))}</small></span>${rk_fixedSum(f)}${ic('chev', 's')}</button></li>`;
  return `<div class="ofcbar fcibar"><h3 class="ofcgrp">${tr('Fixed costs')}</h3><span class="spacer"></span>${fx.some(f => f.sub) ? `<a class="btn sm ghost" href="#office/subs" data-abo="go">${ic('repeat', 's')}<span>${tr('Subscriptions & tools')}</span></a>` : ''}<button class="btn sm pri" data-rkf="fnew">${ic('plus', 's')}<span>${tr('New fixed cost')}</span></button></div>`
    + (fx.length ? cats.map(k => `${cats.length > 1 || k ? `<h4 class="fcicat">${esc(k || tr('Without category'))}</h4>` : ''}<ul class="ofclist" role="list">${fx.filter(f => (f.category || '') === k).map(row).join('')}</ul>`).join('')
      : `<p class="muted lempty">${tr('No fixed costs yet, e.g. rent or software subscriptions.')}</p>`) + oim_link('fixed', !fx.length) + rk_agrFixedHtml();
}
// 2.122.3 A (#2333): without VAT net and gross are the same, so one amount without "net"/"gross" (like the contracts row)
function rk_fixedSum(f) {
  if (!+f.vat_rate) return `<span class="rksum fcisum"><span>${ofcMoney(f.amount)}</span></span>`;
  return `<span class="rksum fcisum"><span>${ofcMoney(f.amount)} <small class="muted">${tr('net')}</small></span><small class="muted">${ofcMoney(f.gross ?? f.amount)} ${tr('gross')}</small></span>`;
}
// 2.92.0 A (#1925): the contributions of business contracts and insurances, read-only here (edited in Contracts & insurance)
function rk_agrFixedHtml() {
  const ag = RKF.agr || [], rp = k => tr(RK_CF_REPEATS.find(x => x[0] === k)?.[1] || k);
  if (!ag.length) return '';
  return `<h4 class="fcicat">${tr('From contracts')}</h4><ul class="ofclist agr-fixed" role="list">${ag.map(f => `<li><a class="ofcrow" href="#office/agreements/${f.id}"><span class="ofcn"><b>${esc(f.label)}</b><small class="muted">${esc([rp(f.repeat), tr('from {0}', fmtDateLoc(f.start)), f.until ? tr('until {0}', fmtDateLoc(f.until)) : '', f.vat_rate ? tr('VAT {0} %', f.vat_rate) : ''].filter(Boolean).join(' · '))}</small></span><span class="rksum fcisum"><span>${ofcMoney(f.amount)}${f.vat_rate ? ` <small class="muted">${tr('net')}</small>` : ''}</span>${f.vat_rate ? `<small class="muted">${ofcMoney(f.gross)} ${tr('gross')}</small>` : ''}</span>${ic('chev', 's')}</a></li>`).join('')}</ul>`;
}
function rk_fixedModal(f) {
  const md = modal(`<h3>${f ? tr('Edit fixed cost') : tr('New fixed cost')}</h3>
    ${ofcRowF('cf-label', tr('Name'), ofcIn('cf-label', f?.label, {ph: tr('e.g. Rent')}))}
    ${ofcRowF('cf-amount', tr('Amount'), ofcIn('cf-amount', f ? fmtNum(+f.amount, 2) : '', {num: true}), ofcCur())}
    ${ofcRowF('cf-category', tr('Category'), ofcIn('cf-category', f?.category, {max: 100, list: 'cf-cats', ph: tr('e.g. Insurances')}) + `<datalist id="cf-cats">${[...new Set((RKF.fixed || []).map(x => x.category).filter(Boolean))].map(k => `<option value="${esc(k)}">`).join('')}</datalist>`)}
    ${ofcRowF('cf-vat', tr('VAT rate'), ofcSel('cf-vat', f?.vat_rate ?? 0, FCI_VATS.map(v => [v, `${v} %`])), tr('The amount is net.'))}
    ${ofcRowF('cf-repeat', tr('Repeat'), ofcSel('cf-repeat', f?.repeat || 'monthly', RK_CF_REPEATS.map(([k, n]) => [k, tr(n)])))}
    <div class="row"><label id="cf-startl">${tr('First due date')}</label>${dateIn('cf-start', f?.start || new Date().toISOString().slice(0, 10), {label: tr('First due date'), clear: false})}</div>
    <div class="row"><label id="cf-untill">${tr('Ends on')}</label>${dateIn('cf-until', f?.until || '', {label: tr('Ends on'), empty: tr('open-ended'), after: 'cf-start'})}</div>
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
        const o = j.item; toast(tr('Deleted'), async () => { await api('POST', '/api/office/fixed-costs', {label: o.label, amount: o.amount, start: o.start, until: o.until, repeat: o.repeat, category: o.category || '', vat_rate: o.vat_rate || 0, ...aboFields(o)}); rk_cfReload(); });  // 2.91.0 B (#1924): + the subscription fields
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const body = {label: v('#cf-label'), amount: ofcNum(v('#cf-amount')), repeat: v('#cf-repeat'), start: v('#cf-start'), until: v('#cf-until'), category: v('#cf-category'), vat_rate: +v('#cf-vat') || 0};
      if (f) {
        const old = {label: f.label, amount: f.amount, repeat: f.repeat, start: f.start, until: f.until, category: f.category || '', vat_rate: f.vat_rate || 0};
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

// ---- 2.67.0 (#1838): fixed costs from a spreadsheet: pick a file -> preview (nothing stored) -> take over the ticked rows
const FCI_VATS = [0, 7, 19];
function fci_pick() {
  const i = document.createElement('input'); i.type = 'file'; i.accept = '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  i.onchange = () => { if (i.files[0]) fci_preview(i.files[0]); }; i.click();
}
async function fci_preview(file) {
  const fd = new FormData(); fd.append('file', file);
  let j;
  try {
    const r = await fetch('/api/office/fixed-costs/import/preview', {method: 'POST', body: fd, credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido'}});
    j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
  } catch (x) { toast(x.message || tr('unknown')); return; }
  fci_modal(j.rows || [], file.name);
}
function fci_modal(rows, name) {
  const md = modal(''), card = $('.card', md), rp = k => tr(RK_CF_REPEATS.find(x => x[0] === k)?.[1] || k);
  md.classList.add('ofcdlg', 'fcidlg');
  const draw = () => {
    const n = rows.filter(r => r.sel && r.status !== 'error').length;
    const cnt = k => rows.filter(r => r.status === k).length;
    card.innerHTML = `<h3>${tr('Import fixed costs')}</h3><p class="muted">${esc(name)} · ${esc([trn('{0} new', '{0} new', cnt('new')), cnt('dup') ? trn('{0} already there', '{0} already there', cnt('dup')) : '', cnt('error') ? trn('{0} with an error', '{0} with an error', cnt('error')) : ''].filter(Boolean).join(' · '))}</p>
      <ul class="fcilist" role="list">${rows.map((r, i) => r.status === 'error'
        ? `<li class="fcirow err"><span class="fcick" aria-hidden="true">${ic('x', 's')}</span><span class="ofcn"><b>${esc(r.label || tr('Row {0}', r.row))}</b><small>${esc(tr('Row {0}', r.row))} · ${esc(r.reason)}</small></span></li>`
        : `<li class="fcirow ${r.sel ? 'on' : ''} ${r.status}"><label class="fcick"><input type="checkbox" data-fci="sel" data-i="${i}" ${r.sel ? 'checked' : ''} aria-label="${esc(tr('Take over {0}', r.label))}"></label>
          <span class="ofcn"><b>${esc(r.label)}${r.part ? ` <small class="muted">${esc(r.part)}</small>` : ''}</b><small class="muted">${esc([rp(r.repeat), tr('from {0}', fmtDateLoc(r.start)), r.category, r.sub ? tr('Subscription') : '', r.notice_days ? tr('notice {0} days', r.notice_days) : '', r.status === 'dup' ? r.reason : ''].filter(Boolean).join(' · '))}</small></span>
          <span class="fciamt"><span>${ofcMoney(r.amount)} <small class="muted">${tr('net')}</small></span><select data-fci="vat" data-i="${i}" aria-label="${esc(tr('VAT rate'))}">${FCI_VATS.map(v => `<option value="${v}" ${+r.vat_rate === v ? 'selected' : ''}>${v} %</option>`).join('')}</select></span></li>`).join('')}</ul>
      <div class="aerr" role="alert"></div>
      <div class="foot"><span class="spacer"></span><button class="btn" data-fci="close">${tr('Cancel')}</button><button class="btn pri" data-fci="go" ${n ? '' : 'disabled'}>${esc(trn('Take over {0} row', 'Take over {0} rows', n))}</button></div>`;
  };
  draw();
  md.addEventListener('change', e => {
    const t = e.target.closest('[data-fci]'); if (!t) return;
    const r = rows[+t.dataset.i]; if (!r) return;
    if (t.dataset.fci === 'sel') r.sel = t.checked; else if (t.dataset.fci === 'vat') r.vat_rate = +t.value;
    draw(); $(`[data-fci="${t.dataset.fci}"][data-i="${t.dataset.i}"]`, md)?.focus();
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-fci]'); if (!b) return;
    if (b.dataset.fci === 'close') { md.remove(); return; }
    const items = rows.filter(r => r.sel && r.status !== 'error').map(r => ({label: r.label, amount: r.amount, repeat: r.repeat, start: r.start, category: r.category, vat_rate: r.vat_rate, sub: r.sub || 0, notice_days: r.notice_days || 0}));  // 2.91.0 B (#1924): + sub, notice_days
    if (!await importTargetConfirm({what: trn('{0} fixed cost', '{0} fixed costs', items.length), ws: ofcWs(), place: tr('Office')})) return;  // 2.87.9 (#1940)
    b.disabled = true;
    try {
      const j = await api('POST', '/api/office/fixed-costs/import', {items});
      md.remove(); rk_cfReload();
      toast(trn('{0} fixed cost imported', '{0} fixed costs imported', j.created), async () => { await api('POST', '/api/office/fixed-costs/delete', {ids: j.ids}); rk_cfReload(); });
    } catch (x) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}

// ---- 2.67.0 (#1838): the optional monthly task "Cash flow: check the actual state" for one person (only a link, no amounts)
function fci_checkHtml() {
  const k = RKF.check; if (!k) return '';
  const ppl = k.people || [];
  return `<div class="ofcbar"><h3 class="ofcgrp">${tr('Monthly check')}</h3></div><div class="fcichk">
    <label class="chkl"><input type="checkbox" data-fcc="on" ${k.on ? 'checked' : ''} ${ppl.length ? '' : 'disabled'}><span>${tr('Monthly task: check the actual state of the cash flow')}</span></label>
    ${k.on || ppl.length ? `<div class="row"><label for="fcc-user">${tr('Responsible person')}</label><select id="fcc-user" data-fcc="user">${k.user_id && !ppl.some(p => p.id === k.user_id) ? `<option value="${k.user_id}" selected>${esc(tr('Person without access'))}</option>` : ''}${ppl.map(p => `<option value="${p.id}" ${p.id === (k.user_id || S.me?.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>` : ''}
    ${k.lost ? `<p class="aerr" role="alert">${tr('The person responsible no longer has access to the cash flow. Please choose someone else.')}</p>` : ''}
    <p class="muted ofchint">${tr('Due on the 1st of every month in the Basket of the person, with a link to the cash flow and no amounts. Off: the task is ended, not deleted.')}</p></div>`;
}
document.addEventListener('change', async e => {
  const t = e.target.closest?.('[data-fcc]'); if (!t || !RKF.check) return;
  const old = {on: RKF.check.on ? 1 : 0, user_id: RKF.check.user_id};
  const on = $('[data-fcc="on"]')?.checked ? 1 : 0, uid = +($('#fcc-user')?.value || 0) || null;
  if (!on && !old.on) return;  // another person while off: kept for the next switch on
  const put = async b => { RKF.check = await api('PUT', '/api/office/cashflow/check', b); ofcDraw(); };
  try {
    await put(on ? {on: 1, user_id: uid} : {on: 0});
    toast(on ? tr('Monthly check on') : tr('Monthly check off'), async () => { await put(old.on && old.user_id ? old : {on: 0}); });
  } catch (x) { toast(x.message || tr('unknown')); ofcDraw(); }
});

document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-rkf]'); if (!b) return;
  const a = b.dataset.rkf;
  if (a === 'prev' || a === 'next') { RKF.from = rk_ymAdd(RKF.from || rk_ym(), a === 'prev' ? -1 : 1); RKF.open = null; ofcDraw(); }
  else if (a === 'now') { RKF.from = rk_ym(); RKF.open = null; ofcDraw(); }
  else if (a === 'months') { RKF.months = +b.dataset.v; ofcDraw(); }
  else if (a === 'basis') { RKF.basis = b.dataset.v === 'net' ? 'net' : 'gross'; LS.set('cfBasis', RKF.basis); ofcDraw(); }  // 2.67.0 (#1838)
  else if (a === 'fimp') fci_pick();
  else if (a === 'open') { RKF.open = RKF.open === b.dataset.k ? null : b.dataset.k; ofcDraw(); }
  else if (a === 'fnew') rk_fixedModal(null);
  else if (a === 'fixed') { const f = (RKF.fixed || []).find(x => x.id === +b.dataset.id); if (f) rk_fixedModal(f); }
  else if (a === 'trip') { if (typeof RK === 'object') { RK.open = +b.dataset.id; RK.view = 'trips'; RK.year = ''; RK.data = null; } return; }  // the link itself opens the tab
  else return;
  e.preventDefault();
});
