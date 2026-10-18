// 2.92.0 B (#1931): equipment value -- purchase, receipt, depreciation, new / current value, the insurance list. Admins only:
// members never get these fields (the server leaves them out). office.js hangs the editor part in (astFields / astBind /
// astBody / astUndo), the line under a device (astRowInfo) and the sums above the list (astSummaryHtml).
const AST_URL = '/api/office/equipment';
const astM = v => v != null && v !== '' ? fmtNum(+v, 2) : '';
const astNote = () => `<p class="muted ast-note">${esc(tr('No tax advice; figures without guarantee.'))}</p>`;

// the line under a device in the list: current value + depreciation of this year
const astRowInfo = r => !ofcAdmin() ? [] : [r.current_value_eff != null ? `${tr('Current value')} ${ofcMoney(r.current_value_eff)}` : '',
  r.afa_year != null && +r.afa_year ? `${tr('Depreciation {0}', r.year)} ${ofcMoney(r.afa_year)}` : ''].filter(Boolean);

// the sums above the equipment list + the export (CSV / PDF, filtered by policy)
function astSummaryHtml(rows) {
  if (!ofcAdmin()) return '';
  const live = (rows || []).filter(r => !r.archived);
  if (!live.some(r => r.new_value_eff != null || r.current_value_eff != null)) return '';
  const sum = k => live.reduce((a, r) => a + (+r[k] || 0), 0);
  const pol = [...new Map(live.filter(r => r.agreement_id).map(r => [r.agreement_id, r.agreement_name || `#${r.agreement_id}`])).entries()];
  const yr = live.find(r => r.year)?.year || new Date().getFullYear();
  return `<section class="ast-sum" aria-label="${esc(tr('Equipment value'))}">
    <div class="ast-tiles"><div class="ast-tile"><small class="muted">${tr('New value')}</small><b>${ofcMoney(sum('new_value_eff'))}</b></div>
    <div class="ast-tile"><small class="muted">${tr('Current value')}</small><b>${ofcMoney(sum('current_value_eff'))}</b></div>
    <div class="ast-tile"><small class="muted">${tr('Depreciation {0}', yr)}</small><b>${ofcMoney(sum('afa_year'))}</b></div></div>
    <div class="ast-exp">${pol.length ? `<select id="ast-pol" aria-label="${esc(tr('Insured by'))}"><option value="">${tr('All devices')}</option>${pol.map(([v, n]) => `<option value="${v}">${esc(n)}</option>`).join('')}<option value="0">${tr('Not insured')}</option></select>` : ''}
    <a class="btn sm" id="ast-csv" href="${AST_URL}/value.csv" download>${ic('download', 's')} CSV</a><a class="btn sm" id="ast-pdf" href="${AST_URL}/value.pdf" download>${ic('download', 's')} PDF</a></div>
    ${astNote()}</section>`;
}
document.addEventListener('change', e => {
  if (e.target.id !== 'ast-pol') return;
  const q = e.target.value !== '' ? `?agreement_id=${encodeURIComponent(e.target.value)}` : '';
  for (const [id, ext] of [['ast-csv', 'csv'], ['ast-pdf', 'pdf']]) { const a = $('#' + id); if (a) a.href = `${AST_URL}/value.${ext}${q}`; }
});

// ---- the editor part of a device (admins only)
function astFields(r) {
  if (!ofcAdmin()) return '';
  const plan = r?.afa_plan || [];
  const life = r?.life_suggest ? tr('Suggestion: {0} months', r.life_suggest) : tr('Suggested from the category');
  const tbl = plan.length ? `<table class="ast-plan"><caption>${r.method === 'gwg' ? tr('Low-value asset: written off in the purchase year') : tr('Linear depreciation over {0} months', r.life_eff)}</caption>
    <thead><tr><th scope="col">${tr('Year')}</th><th scope="col">${tr('Depreciation')}</th><th scope="col">${tr('Book value')}</th></tr></thead>
    <tbody>${plan.map(p => `<tr class="${p.year === r.year ? 'cur' : ''}"><td>${p.year}</td><td>${ofcMoney(p.afa)}</td><td>${ofcMoney(p.book)}</td></tr>`).join('')}</tbody></table>` : '';
  return `<details class="ast-sec" ${r?.purchase_net || r?.purchase_date ? 'open' : ''}><summary>${tr('Purchase and value')}</summary>
    <div class="row"><label id="of-purchase_datel">${tr('Purchase date')}</label>${dateIn('of-purchase_date', r?.purchase_date || '', {label: tr('Purchase date'), empty: tr('optional')})}</div>
    ${ofcRowF('of-purchase_net', tr('Purchase price (net)'), ofcIn('of-purchase_net', astM(r?.purchase_net), {num: true}), ofcCur())}
    <div class="row"><label>${tr('Receipt')}</label><input type="hidden" id="of-receipt_node_id" value="${esc(r?.receipt_node_id ?? '')}">
      <span class="ast-rc" id="ast-rcname">${r?.receipt_node_id ? esc(tr('Receipt linked')) : `<span class="muted">${tr('none')}</span>`}</span>
      <button type="button" class="btn sm" data-ast="pick">${ic('receipt', 's')} ${tr('Take from receipt')}</button>
      <button type="button" class="iconbtn" data-ast="unlink" aria-label="${esc(tr('Remove'))}" ${r?.receipt_node_id ? '' : 'hidden'}>${ic('x', 's')}</button></div>
    <p class="muted ast-hint" id="ast-hint" role="status"></p>
    ${ofcRowF('of-vendor', tr('Vendor'), ofcIn('of-vendor', r?.vendor, {max: 120}))}
    ${ofcRowF('of-serial_no', tr('Serial number'), ofcIn('of-serial_no', r?.serial_no, {max: 120}))}
    ${ofcRowF('of-life_months', tr('Useful life (months)'), ofcIn('of-life_months', r?.life_months ?? '', {num: true, ph: r?.life_suggest ? String(r.life_suggest) : ''}), life)}
    ${tbl}
    ${ofcRowF('of-new_value', tr('New value'), ofcIn('of-new_value', astM(r?.new_value), {num: true, ph: astM(r?.purchase_net)}), tr('Default: the purchase price'))}
    ${ofcRowF('of-current_value', tr('Current value'), ofcIn('of-current_value', astM(r?.current_value), {num: true, ph: astM(r?.book_value)}), tr('Current value = book value, unless you enter an own value.'))}
    ${ofcRowF('of-agreement_id', tr('Insured by'), ofcSel('of-agreement_id', r?.agreement_id, r?.agreement_id ? [[r.agreement_id, r.agreement_name || `#${r.agreement_id}`]] : [], tr('none')))}
    ${astNote()}</details>`;
}
// fills the policy choice, wires the receipt picker
function astBind(md, r) {
  if (!ofcAdmin() || !$('#of-agreement_id', md)) return;
  api('GET', `${AST_URL}/policies`).then(j => {
    const sel = $('#of-agreement_id', md); if (!sel) return;
    const cur = String(r?.agreement_id ?? '');
    sel.innerHTML = `<option value="">${esc(tr('none'))}</option>` + (j.items || []).filter(a => !a.archived || String(a.id) === cur)
      .map(a => `<option value="${a.id}" ${String(a.id) === cur ? 'selected' : ''}>${esc(a.name + (a.provider ? ` (${a.provider})` : ''))}</option>`).join('');
  }).catch(() => {});
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-ast]'); if (!b || !md.contains(b)) return;
    if (b.dataset.ast === 'unlink') { $('#of-receipt_node_id', md).value = ''; $('#ast-rcname', md).innerHTML = `<span class="muted">${esc(tr('none'))}</span>`; b.hidden = true; }
    else if (b.dataset.ast === 'pick') modalSub(md, () => astPick(md));
  });
}
// the receipt picker: documents of the office's document space; a choice proposes date, net price and vendor
function astPick(md) {
  const pk = modal(`<h3>${tr('Take from receipt')}</h3><div class="ctsearch">${ic('search', 's')}<input id="ast-rq" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" autocomplete="off" enterkeyhint="search"></div>
    <ul class="ast-rcl" role="list"><li class="muted">${tr('Loading…')}</li></ul><div class="foot"><span class="spacer"></span><button class="btn" data-ast="close">${tr('Cancel')}</button></div>`);
  pk.classList.add('ast-pick');
  const list = $('.ast-rcl', pk);
  let seq = 0;
  const load = async q => {
    const n = ++seq;
    try {
      const j = await api('GET', `${AST_URL}/receipts?q=${encodeURIComponent(q || '')}`);
      if (n !== seq) return;
      list.innerHTML = (j.items || []).map(d => `<li><button type="button" class="ofcrow" data-ast="take" data-id="${d.id}"><span class="ofcn"><b>${esc(d.name)}</b><small class="muted">${esc([d.date ? fmtDateLoc(d.date) : '', d.sender, d.amount ? `${fmtNum(+d.amount, 2)} ${d.currency || ''}`.trim() : '', d.receipt ? tr('Receipt') : ''].filter(Boolean).join(' · '))}</small></span></button></li>`).join('')
        || `<li class="muted">${q ? tr('Nothing matches.') : tr('No documents in this office yet.')}</li>`;
    } catch (x) { list.innerHTML = `<li class="aerr">${esc(x.message || '')}</li>`; }
  };
  let t;
  $('#ast-rq', pk).addEventListener('input', e => { clearTimeout(t); t = setTimeout(() => load(e.target.value.trim()), 250); });
  pk.addEventListener('click', async e => {
    const b = e.target.closest('[data-ast]'); if (!b) return;
    if (b.dataset.ast === 'close') { pk.remove(); return; }
    if (b.dataset.ast !== 'take') return;
    try {
      const s = await api('GET', `${AST_URL}/receipts/${b.dataset.id}`);
      astTake(md, s); pk.remove();
    } catch (x) { toast(x.message || ''); }
  });
  load('');
  return pk;
}
function astTake(md, s) {
  const set = (id, v) => { const el = $(id, md); if (el && v != null && v !== '') el.value = v; };
  $('#of-receipt_node_id', md).value = s.id;
  $('#ast-rcname', md).textContent = s.name;
  $('[data-ast="unlink"]', md).hidden = false;
  const dt = $('#of-purchase_date', md); if (dt && s.date) { dt.value = s.date; dpSync(dt); }
  set('#of-purchase_net', s.net != null ? fmtNum(+s.net, 2) : null);
  set('#of-vendor', s.vendor);
  $('#ast-hint', md).textContent = s.hint || (s.vat_pct != null ? tr('Net price from {0} gross with {1} % VAT.', fmtNum(+s.gross, 2), s.vat_pct) : '');
}
// the fields to save (only when the part is in the dialog)
function astBody(md) {
  if (!$('#of-purchase_net', md)) return {};
  const v = id => $(id, md)?.value ?? '';
  return {purchase_date: v('#of-purchase_date'), purchase_net: ofcNum(v('#of-purchase_net')), receipt_node_id: +v('#of-receipt_node_id') || null,
    vendor: v('#of-vendor'), serial_no: v('#of-serial_no'), life_months: ofcNum(v('#of-life_months')), new_value: ofcNum(v('#of-new_value')),
    current_value: ofcNum(v('#of-current_value')), agreement_id: +v('#of-agreement_id') || null};
}
// one undo step for a saved device: the fields before back (members never edit)
function astUndo(r, body) {
  const url = `${AST_URL}/${r.id}`, old = {};
  for (const k of Object.keys(body)) old[k] = r[k] ?? null;
  const go = b => api('PATCH', url, b).then(() => ofcReload('equipment'));
  offerUndo(tr('Saved'), histAdd({label: tr('Edit device'), undo: () => go(old), redo: () => go(body)}));
}
