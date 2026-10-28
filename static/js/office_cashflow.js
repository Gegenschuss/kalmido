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
  if (!ofcAdmin()) return ofcLockedHtml();  // 2.356.0 D (#3006): why, and the way to hand in receipts
  if (!RKF.from) RKF.from = rk_ym();
  if (RKF.err) return `<div class="empty">${esc(RKF.err)}</div>`;
  if (!RKF.data || RKF.q !== rk_cfQ()) { setTimeout(() => { if (RKF.q !== rk_cfQ() || !RKF.data) rk_cfLoad(); }, 0); if (!RKF.data) return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const d = RKF.data;
  const bar = `<div class="ofcbar rkcfbar"><button class="iconbtn" data-rkf="prev" aria-label="${esc(tr('Earlier'))}" title="${esc(tr('Earlier'))}">${ic('left', 's')}</button><b class="rkcfrange">${esc(rk_month(d.rows[0]?.month))} – ${esc(rk_month(d.rows[d.rows.length - 1]?.month))}</b><button class="iconbtn" data-rkf="next" aria-label="${esc(tr('Later'))}" title="${esc(tr('Later'))}">${ic('right', 's')}</button>
    ${RKF.from !== rk_ym() ? `<button class="btn sm ghost" data-rkf="now">${tr('Today')}</button>` : ''}<span class="spacer"></span>
    <div class="seg" role="group" aria-label="${esc(tr('Preview'))}">${[3, 6].map(n => `<button type="button" data-rkf="months" data-v="${n}" class="${RKF.months === n ? 'on' : ''}" aria-pressed="${RKF.months === n}">${esc(trn('{0} month', '{0} months', n))}</button>`).join('')}</div>
    <div class="seg fcibasis" role="group" aria-label="${esc(tr('Amounts'))}">${[['net', tr('Net')], ['gross', tr('Gross')]].map(([k, n]) => `<button type="button" data-rkf="basis" data-v="${k}" class="${RKF.basis === k ? 'on' : ''}" aria-pressed="${RKF.basis === k}">${esc(n)}</button>`).join('')}</div></div>`;
  const val = (mo, dir, st, v, cls = '') => +v ? `<button type="button" class="rkcfv ${cls}" data-rkf="open" data-k="${mo}|${dir}|${st}" aria-expanded="${RKF.open === `${mo}|${dir}|${st}`}">${ofcMoney(v)}</button>` : `<span class="rkcfv rkcfz muted">–</span>`;
  const max = Math.max(1, ...d.rows.flatMap(r => [+r.in.actual + +r.in.plan, +r.out.actual + +r.out.plan]));
  const bars = r => `<div class="rkcfbars" aria-hidden="true"><span class="rkcfbin" style="transform:scaleX(${((+r.in.actual + +r.in.plan) / max).toFixed(3)})"></span><span class="rkcfbout" style="transform:scaleX(${((+r.out.actual + +r.out.plan) / max).toFixed(3)})"></span></div>`;
  const cards = d.rows.map(r => {
    const k = RKF.open?.startsWith(r.month + '|') ? RKF.open : null;
    // 2.330 (#3296): the balance in the head counts the month's corrections by hand too (like the account balance below)
    const bal = r.manual ? Math.round((+r.balance + +(r.manual.in || 0) - +(r.manual.out || 0)) * 100) / 100 : +r.balance;
    return `<section class="rkcfm ${r.current ? 'cur' : ''}" aria-label="${esc(rk_month(r.month))}"><header><b>${esc(rk_month(r.month))}</b>${r.current ? `<span class="rotag">${tr('this month')}</span>` : ''}<span class="spacer"></span>
      <span class="rkcfbal ${bal < 0 ? 'neg' : ''}"${r.manual ? ` title="${esc(tr('Corrections by hand'))}"` : ''}>${tr('Balance')} ${ofcMoney(bal)}</span></header>${bars(r)}
      <table class="rkcftab"><thead><tr><th></th><th class="num" title="${esc(tr('Paid or already past'))}">${tr('Actual')}</th><th class="num" title="${esc(tr('Expected'))}">${tr('Planned')}</th></tr></thead><tbody>
      <tr><th>${tr('In|cashflow')}</th><td class="num">${val(r.month, 'in', 'actual', r.in.actual)}</td><td class="num">${val(r.month, 'in', 'plan', r.in.plan, 'plan')}</td></tr>
      <tr><th>${tr('Out|cashflow')}</th><td class="num">${val(r.month, 'out', 'actual', r.out.actual)}</td><td class="num">${val(r.month, 'out', 'plan', r.out.plan, 'plan')}</td></tr>${bk_cfReserveRows(r)}${cfs_accRows(r)}${cfb_rows(r)}</tbody></table>${cfb_realBar(r)}
      ${rk_cfOpenHtml(r.month)}${cfs_adjHtml(r.month)}${k ? rk_cfEntries(k) : ''}</section>`;
  }).join('');
  // 2.298.0 A2 (#3186): the legend of actual / planned and net / gross sits behind (i) under the bar with the net / gross
  // switch (the column heads carry a short title), no longer as a paragraph under the months
  return bar + `<div class="shint rkcfleg">${tr('Actual = paid or already past; planned = expected (open invoices on their due date, sent and accepted quotations without an invoice at the end of their period of service, one version per quotation).')} ${d.basis === 'net' ? tr('Net: documents and fixed costs without VAT; purchases and travel receipts as entered.') : tr('Gross: documents and fixed costs incl. VAT; purchases and travel receipts as entered.')}</div>` + cfb_boxHtml(d) + `<div class="rkcfms">${cards}</div>` + rk_fixedHtml() + fci_checkHtml();
}
// 2.90.0 A (#1921): with a tax reserve (Bookkeeping, tax_reserve_pct > 0): the month's reserve and what is free after all reserves so far
const bk_cfReserveRows = r => r.reserve == null ? '' : `<tr class="bk-cfres"><th>${tr('Tax reserve')}</th><td class="num" colspan="2">${ofcMoney(r.reserve)}</td></tr>
      <tr class="bk-cffree"><th>${tr('Freely available')}</th><td class="num ${+r.free < 0 ? 'neg' : ''}" colspan="2">${ofcMoney(r.free)}</td></tr>`;
function rk_cfEntries(k) {
  const [mo, dir, st] = k.split('|');
  const es = (RKF.data.entries || []).filter(e => e.month === mo && e.dir === dir && e.state === st);
  const go = e => e.doc_id ? `href="#office/invoices/${e.doc_id}"` : e.series_id ? `href="#office/invoices" data-rin-go="${e.series_id}"` : e.trip_id ? `href="#office/travel" data-rkf="trip" data-id="${e.trip_id}"` : e.fixed_id ? `href="#" data-rkf="fixed" data-id="${e.fixed_id}"` : e.agreement_id ? `href="#office/agreements/${e.agreement_id}"` : e.node_id ? `href="#docs/${e.node_id}"` : '';  // 2.92.0 A (#1925); 2.114.1 B (#2018): a receipt opens the document
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
    ${ofcRowF('cf-amount', tr('Amount'), ofcIn('cf-amount', f ? fmtNum(+f.amount, 2) : '', {num: true}), ofcCur(), {keep: 1})}
    ${ofcRowF('cf-category', tr('Category'), ofcIn('cf-category', f?.category, {max: 100, list: 'cf-cats', ph: tr('e.g. Insurances')}) + `<datalist id="cf-cats">${[...new Set((RKF.fixed || []).map(x => x.category).filter(Boolean))].map(k => `<option value="${esc(k)}">`).join('')}</datalist>`)}
    ${ofcRowF('cf-vat', tr('VAT rate'), ofcSel('cf-vat', f?.vat_rate ?? 0, FCI_VATS.map(v => [v, `${v} %`])), tr('The amount is net.'), {keep: 1})}
    ${ofcRowF('cf-repeat', tr('Repeat'), ofcSel('cf-repeat', f?.repeat || 'monthly', RK_CF_REPEATS.map(([k, n]) => [k, tr(n)])))}
    <div class="row"><label id="cf-startl">${tr('First due date')}</label>${dateIn('cf-start', f?.start || today(), {label: tr('First due date'), clear: false})}</div>
    <div class="row"><label id="cf-untill">${tr('Ends on')}</label>${dateIn('cf-until', f?.until || '', {label: tr('Ends on'), empty: tr('open-ended'), after: 'cf-start'})}</div>
    <div class="aerr" role="alert"></div>
    <div class="foot">${f ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}${f && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom()) ? `<button class="btn" data-m="move">${ic('brief', 's')} ${esc(tr('Move to another workspace…'))}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${f ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    if (b.dataset.m === 'move') { md.remove(); ofm_move({what: 'fixed', ids: [f.id], from: ofm_officeFrom(), label: qn(f.label), after: async () => rk_cfReload()}); return; }  // 2.356.0 A (#2926)
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
    const items = rows.filter(r => r.sel && r.status !== 'error').map(r => ({label: r.label, amount: r.amount, repeat: r.repeat, start: r.start, category: r.category, vat_rate: r.vat_rate, sub: r.sub || 0, notice_days: r.notice_days || 0, ...(r.status === 'dup' ? {dup_ok: 1} : {})}));  // 2.91.0 B (#1924): + sub, notice_days; 2.269.0 D (#3046): + dup_ok (ticked on purpose)
    if (!await importTargetConfirm({what: trn('{0} fixed cost', '{0} fixed costs', items.length), ws: ofcWs(), place: tr('Office')})) return;  // 2.87.9 (#1940)
    b.disabled = true;
    try {
      const j = await api('POST', '/api/office/fixed-costs/import', {items});
      md.remove(); rk_cfReload();
      toast(trn('{0} fixed cost imported', '{0} fixed costs imported', j.created), async () => { const u = await api('POST', '/api/office/fixed-costs/delete', {ids: j.ids}); rk_cfReload();
        if (u.kept) toast(trn('{0} fixed cost stays: changed since the import', '{0} fixed costs stay: changed since the import', u.kept)); });  // 2.272.0 C (#3027)
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
    <p class="muted ofchint">${tr('On the 1st of every month in the Basket of the person, without amounts.')}</p></div>`;
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

// ---- 2.123.0 D (#2341): the account balance -- start balance (office settings), corrections by hand per month, the real
// balance at the end of a month against the computed one. Server: kalmido/office/cfstart.py. Without a start balance and
// without corrections the cards stay as before. Every change = one undo step.
const CFS = {st: undefined, oid: null};
const CFS_DIRS = [['in', N_('Other money in|cashflow')], ['out', N_('Other money out|cashflow')]];
const cfs_amt = v => { const n = ofcNum(v); return n == null ? null : n; };
// the account rows of a month card: computed balance at the month's end, the real one (by hand, optional) and the difference
function cfs_accRows(r) {
  if (r.account == null) return '';
  const real = r.real != null ? fmtNum(+r.real, 2) : '', d = r.diff != null ? +r.diff : null;
  return `<tr class="cfs-acc"><th>${tr('Account balance at the end of the month')} <small class="muted">${tr('computed')}</small></th><td class="num ${+r.account < 0 ? 'neg' : ''}" colspan="2">${ofcMoney(r.account)}</td></tr>
      <tr class="cfs-real"><th><label for="cfs-real-${r.month}">${tr('Real balance')} <span class="cfs-hand">${tr('by hand')}</span></label></th><td class="num" colspan="2"><input id="cfs-real-${r.month}" class="numin cfs-realin" inputmode="decimal" maxlength="20" data-cfs-real="${r.month}" value="${esc(real)}" placeholder="${esc(tr('optional'))}" aria-describedby="cfs-diff-${r.month}"></td></tr>
      ${d != null ? `<tr class="cfs-diff"><th>${tr('Difference')}</th><td class="num ${d ? 'cfs-off' : ''}" colspan="2" id="cfs-diff-${r.month}">${d > 0 ? '+' : ''}${ofcMoney(d)}</td></tr>` : ''}`;
}
// the corrections by hand of a month (marked "by hand"), a tap edits one; "+ Correction" adds one
function cfs_adjHtml(mo) {
  const es = (RKF.data?.adjust || []).filter(a => a.month === mo);
  const row = a => `<li><button type="button" class="ofcrow" data-cfs="edit" data-id="${a.id}"><span class="ofcn"><b>${esc(tr(CFS_DIRS.find(x => x[0] === a.dir)?.[1] || a.dir))} <span class="cfs-hand">${tr('by hand')}</span></b>${a.note ? `<small class="muted">${esc(a.note)}</small>` : ''}</span><span class="rksum">${a.dir === 'out' ? '−' : '+'}${ofcMoney(a.amount)}</span>${ic('chev', 's')}</button></li>`;
  return `${es.length ? `<ul class="ofclist cfs-adj" role="list" aria-label="${esc(tr('Corrections by hand'))}">${es.map(row).join('')}</ul>` : ''}<div class="cfs-add"><button type="button" class="btn sm ghost" data-cfs="new" data-month="${mo}">${ic('plus', 's')}<span>${tr('Correction')}</span></button></div>`;
}
function cfs_modal(a, mo) {
  const md = modal(`<h3>${a ? tr('Edit correction') : tr('New correction')}</h3>
    <div class="shint">${esc(tr('For money outside Kalmido in {0}. Counts in the balance of the month and in the account balance; money in and out stay as they are.', rk_month(a?.month || mo)))}</div>
    ${ofcRowF('cfs-dir', tr('Kind'), ofcSel('cfs-dir', a?.dir || 'in', CFS_DIRS.map(([k, n]) => [k, tr(n)])))}
    ${ofcRowF('cfs-amount', tr('Amount'), ofcIn('cfs-amount', a ? fmtNum(+a.amount, 2) : '', {num: true}), ofcCur(), {keep: 1})}
    ${ofcRowF('cfs-note', tr('Note'), ofcIn('cfs-note', a?.note, {max: 200, ph: tr('e.g. cash payment')}))}
    <div class="aerr" role="alert"></div>
    <div class="foot">${a ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${a ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  const keep = x => ({month: x.month, dir: x.dir, amount: x.amount, note: x.note || ''});
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        const j = await api('DELETE', `/api/office/cashflow/adjust/${a.id}`); md.remove(); rk_cfReload();
        let id = a.id;
        offerUndo(tr('Deleted'), histAdd({label: tr('Correction deleted'), undo: async () => { id = (await api('POST', '/api/office/cashflow/adjust', keep(j.item))).id; rk_cfReload(); },
          redo: async () => { await api('DELETE', `/api/office/cashflow/adjust/${id}`); rk_cfReload(); }}));
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const body = {month: a?.month || mo, dir: v('#cfs-dir'), amount: cfs_amt(v('#cfs-amount')), note: v('#cfs-note')};
      if (a) {
        const old = keep(a);
        await api('PATCH', `/api/office/cashflow/adjust/${a.id}`, body); md.remove(); rk_cfReload();
        offerUndo(tr('Saved'), histAdd({label: tr('Correction changed'), undo: async () => { await api('PATCH', `/api/office/cashflow/adjust/${a.id}`, old); rk_cfReload(); },
          redo: async () => { await api('PATCH', `/api/office/cashflow/adjust/${a.id}`, body); rk_cfReload(); }}));
      } else {
        const j = await api('POST', '/api/office/cashflow/adjust', body); md.remove(); rk_cfReload();
        let id = j.id;
        offerUndo(tr('Added'), histAdd({label: tr('Correction added'), undo: async () => { await api('DELETE', `/api/office/cashflow/adjust/${id}`); rk_cfReload(); },
          redo: async () => { id = (await api('POST', '/api/office/cashflow/adjust', body)).id; rk_cfReload(); }}));
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-cfs]'); if (!b) return;
  e.preventDefault();
  if (b.dataset.cfs === 'new') cfs_modal(null, b.dataset.month);
  else if (b.dataset.cfs === 'edit') { const a = (RKF.data?.adjust || []).find(x => x.id === +b.dataset.id); if (a) cfs_modal(a); }
});
// the real balance at the end of a month: saved on change (empty = removed), one undo step
async function cfs_realPut(mo, amount) { await api('PUT', '/api/office/cashflow/actual', {month: mo, amount}); rk_cfReload(); }
document.addEventListener('change', async e => {
  const t = e.target.closest?.('[data-cfs-real]'); if (!t) return;
  const mo = t.dataset.cfsReal, raw = t.value.trim(), amount = raw ? cfs_amt(raw) : null;
  if (raw && amount == null) { toast(tr('Invalid value: {0}', tr('Real balance'))); return; }
  const was = RKF.data?.rows?.find(r => r.month === mo)?.real ?? null;
  if ((was == null && amount == null) || (was != null && amount != null && +was === +amount)) return;
  try { await cfs_realPut(mo, amount); } catch (x) { toast(x.message || tr('unknown')); return; }
  offerUndo(tr('Saved'), histAdd({label: tr('Real balance changed'), undo: () => cfs_realPut(mo, was), redo: () => cfs_realPut(mo, amount)}));
});
document.addEventListener('keydown', e => { const x = e.target; if (e.key === 'Enter' && !e.isComposing && x.dataset?.cfsReal) { e.preventDefault(); x.blur(); } });

// the start balance in the office settings (own section, saved on change like the travel purposes; admins only)
async function cfs_load() {
  CFS.oid = OFC.info?.org_id;
  try { CFS.st = (await api('GET', '/api/office/cashflow/start')).start; } catch (x) { CFS.st = null; }
  const sec = $('.cfsset'); if (sec) sec.outerHTML = cfs_settingsHtml();  // only this section: the settings form keeps what is typed there
}
function cfs_settingsHtml() {
  if (!ofcAdmin()) return '';
  if (CFS.oid !== OFC.info?.org_id) { CFS.oid = OFC.info?.org_id; CFS.st = undefined; setTimeout(cfs_load, 0); }
  const st = CFS.st;
  return `<section class="cfsset" data-fg-skip aria-labelledby="cfs-h"><h3 id="cfs-h">${tr('Cash flow')}</h3>
    <p class="muted ofchint">${tr('From this day the cash flow shows the account balance at the end of every month. Empty = off.')}</p>
    ${st === undefined ? `<p class="muted">${tr('Loading…')}</p>` : `${ofcRowF('cfs-amount-set', tr('Starting balance'), `<span class="lacts">${ofcIn('cfs-amount-set', st ? fmtNum(+st.amount, 2) : '', {num: true, ph: tr('optional')})}<span class="muted">${ofcSym(ofcHome())}</span></span>`)}
    <div class="row"><label id="cfs-dayl">${tr('Reference date')}</label>${dateIn('cfs-day', st?.day || today(), {label: tr('Reference date'), clear: false})}</div>`}</section>`;
}
async function cfs_startSet(v) {
  CFS.st = v ? (await api('PUT', '/api/office/cashflow/start', {amount: v.amount, day: v.day})).start : (await api('DELETE', '/api/office/cashflow/start'), null);
  RKF.data = null; const sec = $('.cfsset'); if (sec) sec.outerHTML = cfs_settingsHtml();
}
document.addEventListener('change', async e => {
  const t = e.target; if (!(t.id === 'cfs-amount-set' || t.id === 'cfs-day') || !t.closest?.('.cfsset')) return;
  const raw = $('#cfs-amount-set')?.value.trim() || '', amount = raw ? cfs_amt(raw) : null, day = $('#cfs-day')?.value || '';
  if (raw && amount == null) { toast(tr('Invalid value: {0}', tr('Starting balance'))); return; }
  const was = CFS.st ? {amount: CFS.st.amount, day: CFS.st.day} : null, now = amount == null ? null : {amount: String(amount), day};
  if (!was && !now) return;
  if (was && now && +was.amount === +now.amount && was.day === now.day) return;
  try { await cfs_startSet(now); } catch (x) { toast(x.message || tr('unknown')); return; }
  offerUndo(tr('Saved'), histAdd({label: tr('Starting balance changed'), undo: () => cfs_startSet(was), redo: () => cfs_startSet(now)}));
});
document.addEventListener('keydown', e => { const x = e.target; if (e.key === 'Enter' && !e.isComposing && x.id === 'cfs-amount-set') { e.preventDefault(); e.stopPropagation(); x.blur(); } }, true);  // never the settings form's submit

// ---- 2.124.0 D (#2342): the balance according to the bank (the closing balances of the imported statements, every account
// added up) against the computed one; it only suggests: "use as starting balance" (no start balance yet) and per month "use as
// real balance" (no real balance by hand yet) save through the routes of #2341, one undo step each. Without balances nothing
// changes. Server: kalmido/office/cfbank.py.
const cfb_signed = v => `${+v > 0 ? '+' : ''}${ofcMoney(v)}`;
// 2.144.1 B (#2446): "Import bank statement" opens the dialog of the bank reconciliation (office_bank.js, same hint), the
// cash flow loads again afterwards; without a bank balance yet a small button above the months
const cfb_impBtn = (cls = 'ghost') => typeof bnkPick === 'function' ? `<button type="button" class="btn sm ${cls}" data-cfb-imp>${ic('upload', 's')}<span>${tr('Import bank statement')}</span></button>` : '';
document.addEventListener('click', e => {
  if (!e.target.closest?.('[data-cfb-imp]')) return;
  e.preventDefault();
  bnkPick(() => { if (typeof BNK === 'object') BNK.data = null; rk_cfReload(); });
});
function cfb_boxHtml(d) {
  const b = d.bank; if (!b) return cfb_impBtn() ? `<div class="cfb-imp">${cfb_impBtn()}</div>` : '';
  const accs = b.accounts || [];
  return `<section class="cfb-box" aria-label="${esc(tr('Account balance according to the bank'))}"><div class="cfb-head"><b>${esc(tr('Account balance according to the bank on {0}: {1}', cfb_day(b.day), ofcMoney(b.amount)))}</b><span class="cfs-hand">${tr('from the bank reconciliation')}</span></div>
    ${accs.length > 1 ? `<small class="muted">${esc(accs.map(a => `${cfb_acct(a.account)}: ${ofcMoney(a.amount)} (${cfb_day(a.day)})`).join(' · '))}</small>` : ''}
    ${b.diff != null ? `<p class="cfb-diff">${esc(tr('Difference to the computed balance: {0}', cfb_signed(b.diff)))}</p>` : ''}
    <div class="cfs-add">${b.suggest_start ? `<button type="button" class="btn sm" data-cfb="start">${tr('Use as starting balance')}</button>` : ''}${cfb_impBtn()}</div></section>`;
}
function cfb_rows(r) {
  const b = r.bank; if (!b) return '';
  return `<tr class="cfb-row"><th>${esc(tr('According to the bank on {0}', cfb_day(b.day)))} <span class="cfs-hand">${tr('from the bank reconciliation')}</span></th><td class="num" colspan="2">${ofcMoney(b.amount)}</td></tr>
      ${b.diff != null ? `<tr class="cfb-row"><th>${tr('Difference to the computed balance')}</th><td class="num ${+b.diff ? 'cfs-off' : ''}" colspan="2">${cfb_signed(b.diff)}</td></tr>` : ''}`;
}
// 2.144.2 B (#2372): "Use as real balance" in its own bar below the month's table (a table cell cannot stick above the
// phone's tab bar; the bar can)
const cfb_realBar = r => r.bank && r.account != null && r.real == null ? `<div class="cfs-add cfb-real"><button type="button" class="btn sm ghost" data-cfb="real" data-month="${r.month}">${tr('Use as real balance')}</button></div>` : '';
document.addEventListener('click', async e => {
  const t = e.target.closest?.('[data-cfb]'); if (!t) return;
  e.preventDefault();
  const d = RKF.data; if (!d?.bank) return;
  t.disabled = true;
  try {
    if (t.dataset.cfb === 'start') {
      const now = {amount: d.bank.amount, day: d.bank.day};
      const set = async v => { await cfs_startSet(v); rk_cfReload(); };
      await set(now);
      offerUndo(tr('Saved'), histAdd({label: tr('Starting balance changed'), undo: () => set(null), redo: () => set(now)}));
    } else if (t.dataset.cfb === 'real') {
      const mo = t.dataset.month, amount = d.rows.find(r => r.month === mo)?.bank?.amount; if (amount == null) return;
      await cfs_realPut(mo, amount);
      offerUndo(tr('Saved'), histAdd({label: tr('Real balance changed'), undo: () => cfs_realPut(mo, null), redo: () => cfs_realPut(mo, amount)}));
    }
  } catch (x) { t.disabled = false; toast(x.message || tr('unknown')); }
});
