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
    <div class="ast-tile"><small class="muted">${trh('Depreciation {0}', yr)}</small><b>${ofcMoney(sum('afa_year'))}</b></div></div>
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
  const cap = r?.method === 'gwg' ? tr('Low-value asset: written off in the purchase year') : r?.method === 'declining'  // 2.480.0 C (#3528), 2.570.0 (#4750): r? - a new device has no r
    ? tr('Declining depreciation at {0} %, linear from the year it gives more', fmtNum(+r?.declining_pct, 2).replace(/[.,]00$/, '')) : tr('Linear depreciation over {0} months', r?.life_eff);
  const tbl = plan.length ? `<table class="ast-plan"><caption>${cap}</caption>
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
    ${r?.receipt_missing ? `<p class="bk-warn ast-norc">${esc(tr('Depreciated without a linked receipt: link the purchase receipt here, else it may count twice in the income/expense statement (as a receipt and as depreciation).'))}</p>` : ''}
    ${ofcRowF('of-vendor', tr('Vendor'), ofcIn('of-vendor', r?.vendor, {max: 120}))}
    ${ofcRowF('of-serial_no', tr('Serial number'), ofcIn('of-serial_no', r?.serial_no, {max: 120}))}
    ${ofcRowF('of-life_months', tr('Useful life (months)'), ofcIn('of-life_months', r?.life_months ?? '', {num: true, ph: r?.life_suggest ? String(r.life_suggest) : ''}), life)}
    <div class="ast-meth" id="ast-meth">${ofcRowF('of-afa_method', tr('Depreciation'),
      ofcSel('of-afa_method', ['declining', 'none'].includes(r?.afa_method) ? r.afa_method : 'auto', [['auto', tr('linear')], ['declining', tr('declining, up to 30 %')], ['none', tr('none (no expense)')]]),
      tr('Declining: for purchases from July 2025 to December 2027. None: the price is only for the value and the insurance list, the receipt counts as a normal expense. No tax advice.'))}</div>
    ${tbl}
    ${ofcRowF('of-new_value', tr('New value'), ofcIn('of-new_value', astM(r?.new_value), {num: true, ph: astM(r?.purchase_net)}), tr('Default: the purchase price. Only for the insurance list: a value here is no expense and is not depreciated.'))}
    ${ofcRowF('of-current_value', tr('Current value'), ofcIn('of-current_value', astM(r?.current_value), {num: true, ph: astM(r?.book_value)}), tr('Current value = book value, unless you enter your own value.'))}
    ${ofcRowF('of-agreement_id', tr('Insured by'), ofcSel('of-agreement_id', r?.agreement_id, r?.agreement_id ? [[r.agreement_id, r.agreement_name || `#${r.agreement_id}`]] : [], tr('none')))}
    ${astNote()}</details>${astCare(r)}${r?.id ? `<div class="astlink dlbox" id="ast-link" data-eq="${r.id}"></div>` : ''}`;  // 2.140.0 B (#2136): the private device link
}
// 2.558.0 C (#4591): warranty end + maintenance (office/eqcare.py) as with a private device: every date keeps a task (in the
// inbox of whoever saves, with a reminder), a maintenance repeats every N months; the next date follows the task when it is done
const AST_MK = () => [['inspection', tr('Inspection')], ['service', tr('Service|maintenance')], ['calibration', tr('Calibration')], ['other', tr('Other')]];
const astTaskLink = t => t ? `<a class="muted ast-task" href="#t/${+t.id}">${ic('check', 's')} ${esc(t.done ? tr('Task done') : tr('Task due {0}', fmtDateLoc(t.due)))}</a>` : '';
let astMn = 0;
function astMaintRow(x) {
  const n = ++astMn, nx = x?.task && !x.task.done ? x.task.due : (x?.next || '');
  return `<div class="ast-mrow" data-mid="${esc(x?.id ?? '')}">${ofcSel(`ast-mk${n}`, x?.kind || 'inspection', AST_MK(), null, tr('Kind'))}
    <input id="ast-ml${n}" class="ast-ml" value="${esc(x?.label || '')}" maxlength="80" placeholder="${esc(tr('Label (optional)'))}" aria-label="${esc(tr('Label (optional)'))}">
    <label class="ast-me">${esc(tr('Every (months)'))} <input id="ast-me${n}" class="numin" inputmode="numeric" maxlength="3" value="${esc(x?.every_months ?? 12)}"></label>
    ${dateIn(`ast-mn${n}`, nx, {label: tr('Next date'), attrs: 'data-ast-next="1"'})}
    <button type="button" class="iconbtn" data-ast="m-del" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>${astTaskLink(x?.task)}</div>`;
}
function astCare(r) {
  if (!ofcAdmin()) return '';
  return `<details class="ast-sec ast-care" ${r?.warranty_until || r?.maint?.length ? 'open' : ''}><summary>${tr('Warranty and maintenance')}</summary>
    <div class="row"><label id="of-warranty_untill">${tr('Warranty until')}</label>${dateIn('of-warranty_until', r?.warranty_until || '', {label: tr('Warranty until'), empty: tr('optional')})}${astTaskLink(r?.warranty_task)}</div>
    <p class="muted">${esc(tr('Every date becomes a task in your basket with a reminder; a maintenance repeats.'))}</p>
    <div class="ast-maint">${(r?.maint || []).map(astMaintRow).join('')}</div>
    <button type="button" class="btn sm" data-ast="m-add">${ic('plus', 's')} ${tr('Add maintenance')}</button></details>`;
}
// 2.480.0 C (#3528): declining depreciation is a choice for a purchase from 01.07.2025 to 31.12.2027 above the low-value limit
// (the server checks the window as well). 2.536.0 (#4335): the choice is always there (linear / none), declining only then
const astDeclOk = (d, net) => !!d && d >= '2025-07-01' && d <= '2027-12-31' && !(net !== '' && net != null && +net <= 800);
// fills the policy choice, wires the receipt picker
function astBind(md, r) {
  if (!ofcAdmin() || !$('#of-agreement_id', md)) return;
  const meth = () => {
    const sel = $('#of-afa_method', md), o = sel && $('option[value="declining"]', sel); if (!o) return;
    const ok = astDeclOk($('#of-purchase_date', md)?.value, ofcNum($('#of-purchase_net', md)?.value ?? ''));
    o.hidden = o.disabled = !ok;
    if (!ok && sel.value === 'declining') sel.value = 'auto';
  };
  meth();
  for (const id of ['#of-purchase_date', '#of-purchase_net']) $(id, md)?.addEventListener('change', meth);  // 2.480.0 C (#3528)
  $('#of-purchase_net', md)?.addEventListener('input', meth);
  api('GET', `${AST_URL}/policies`).then(j => {
    const sel = $('#of-agreement_id', md); if (!sel) return;
    const cur = String(r?.agreement_id ?? '');
    sel.innerHTML = `<option value="">${esc(tr('none'))}</option>` + (j.items || []).filter(a => !a.archived || String(a.id) === cur)
      .map(a => `<option value="${a.id}" ${String(a.id) === cur ? 'selected' : ''}>${esc(a.name + (a.provider ? ` (${a.provider})` : ''))}</option>`).join('');
  }).catch(() => {});
  if (r?.id) astLinkLoad(md, r.id);  // 2.140.0 B (#2136)
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-ast]'); if (!b || !md.contains(b)) return;
    if (b.dataset.ast.startsWith('dl-')) { astLinkAct(md, b); return; }
    if (b.dataset.ast === 'm-add') { $('.ast-maint', md)?.insertAdjacentHTML('beforeend', astMaintRow(null)); return; }  // 2.558.0 C (#4591)
    if (b.dataset.ast === 'm-del') { b.closest('.ast-mrow')?.remove(); return; }
    if (b.dataset.ast === 'unlink') { $('#of-receipt_node_id', md).value = ''; $('#ast-rcname', md).innerHTML = `<span class="muted">${esc(tr('none'))}</span>`; b.hidden = true; }
    else if (b.dataset.ast === 'pick') modalSub(md, () => astPick(md));
  });
}
// the receipt picker: documents of the office's document space; a choice proposes date, net price and vendor
function astPick(md) {
  const pk = modal(`<h3>${tr('Take from receipt')}</h3><div class="ctsearch">${ic('search', 's')}<input id="ast-rq" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" autocomplete="off" enterkeyhint="search"></div>
    <ul class="ast-rcl" role="list"><li>${/*html-ok*/ loadingHtml('row')}</li></ul><div class="foot"><span class="spacer"></span><button class="btn" data-ast="close">${tr('Cancel')}</button></div>`);
  pk.classList.add('ast-pick');
  const list = $('.ast-rcl', pk);
  let seq = 0;
  const load = async q => {
    const n = ++seq;
    try {
      const j = await api('GET', `${AST_URL}/receipts?q=${encodeURIComponent(q || '')}`);
      if (n !== seq) return;
      list.innerHTML = (j.items || []).map(d => `<li><button type="button" class="ofcrow" data-ast="take" data-id="${d.id}"><span class="ofcn"><b>${esc(d.name)}</b><small class="muted">${esc([d.date ? fmtDateLoc(d.date) : '', d.sender, d.amount ? `${fmtNum(+d.amount, 2)} ${d.currency || ''}`.trim() : '', d.receipt ? tr('Receipt') : ''].filter(Boolean).join(' · '))}</small></span></button></li>`).join('')
        || `<li>${/*html-ok*/ q ? ofcNoHit('', 'row') : emptyState({title: tr('No documents in this office yet.'), size: 'row'})}</li>`;  // 2.1076.0 (#5450)
    } catch (x) { list.innerHTML = `<li class="aerr">${esc(ofcErrHere(x))}</li>`; }
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
    } catch (x) { ofcErr(x); }
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
  $('#of-purchase_net', md)?.dispatchEvent(new Event('change'));  // 2.480.0 C (#3528): the depreciation choice follows
  $('#ast-hint', md).textContent = s.hint || (s.vat_pct != null ? tr('Net price from {0} gross with {1} % VAT.', fmtNum(+s.gross, 2), s.vat_pct) : '');
}
// the fields to save (only when the part is in the dialog)
function astBody(md) {
  if (!$('#of-purchase_net', md)) return {};
  const v = id => $(id, md)?.value ?? '';
  return {purchase_date: v('#of-purchase_date'), purchase_net: ofcNum(v('#of-purchase_net')), receipt_node_id: +v('#of-receipt_node_id') || null,
    vendor: v('#of-vendor'), serial_no: v('#of-serial_no'), life_months: ofcNum(v('#of-life_months')), new_value: ofcNum(v('#of-new_value')),
    current_value: ofcNum(v('#of-current_value')), agreement_id: +v('#of-agreement_id') || null,
    afa_method: ['declining', 'none'].includes(v('#of-afa_method')) ? v('#of-afa_method') : 'auto',  // 2.480.0 C (#3528); 2.536.0 (#4335): none
    ...($('#of-warranty_until', md) ? {warranty_until: v('#of-warranty_until'), maint: $$('.ast-mrow', md).map(row => ({...(+row.dataset.mid ? {id: +row.dataset.mid} : {}),  // 2.558.0 C (#4591)
      kind: $('select', row).value, label: $('.ast-ml', row).value.trim(), every_months: +$('.ast-me input', row).value || 12, next: $('[data-ast-next]', row)?.value || ''}))} : {})};
}
// one undo step for a saved device: the fields before back (members never edit)
// 2.566.0 (#4704): only the keys this save changed, each way against the version the step before left (sv = the save's
// answer); changed elsewhere since -> "Changed elsewhere, not undone" (core.js undoStep), never written over
function astUndo(r, body, sv) {
  const url = `${AST_URL}/${r.id}`, old = {}, now = {...body};
  delete now.expect_updated_at;
  for (const k of Object.keys(now)) old[k] = r[k] ?? null;
  let ver = sv?.updated_at || '';
  const go = (b, from) => undoStep(url, b, ver, {now: from, label: tr('Edit device'), then: j => { ver = j?.updated_at || ver; }}).finally(() => ofcReload('equipment'));
  offerUndo(tr('Saved'), histAdd({label: tr('Edit device'), undo: () => go(old, now), redo: () => go(now, old)}));
}

// ---- 2.140.0 B (#2136): the own private device linked with this piece of equipment (life/devlink.py; the device side is
// devlink.js). Only the person's own link ever shows; "Add as a private device" needs the module "home".
async function astLinkLoad(md, id) {
  const box = $('#ast-link', md); if (!box) return;
  let j; try { j = await rawFetch('GET', `${AST_URL}/${id}/link`); } catch { box.innerHTML = ''; return; }
  const l = j.link, o = l?.other, row = v => `<div class="row"><label>${esc(tr('Private'))}</label><span class="lacts">${v}</span></div>`;
  const rm = l ? `<button type="button" class="btn sm" data-ast="dl-unlink" data-link="${l.id}">${ic('x', 's')}<span>${tr('Remove link')}</span></button>` : '';
  box.innerHTML = !l ? (j.can_take ? row(`<button type="button" class="btn sm" data-ast="dl-take" data-eq="${id}">${ic('tool', 's')}<span>${tr('Add as a private device')}</span></button>`) : '')
    : o.state !== 'ok' ? row(`<span class="muted dlhint">${ic('alert', 's')} ${esc(tr('The linked private device does not exist any more.'))}</span>${rm}`)
      : row(`<span class="dllink">${ic('link', 's')} ${esc(tr('Linked with your private device “{0}”', o.name))}</span>
        <button type="button" class="btn sm" data-ast="dl-open" data-task="${o.task_id}">${ic('right', 's')}<span>${tr('Open')}</span></button>
        <button type="button" class="btn sm" data-ast="dl-pull" data-link="${l.id}">${ic('repeat', 's')}<span>${tr('Update from there')}</span></button>${rm}`);
}
async function astLinkAct(md, b) {
  const a = b.dataset.ast, id = +$('#ast-link', md)?.dataset.eq;
  if (a === 'dl-open') {  // the editor closes the usual way (it asks before unsaved input is lost), then the device opens
    const tid = +b.dataset.task, wait = setInterval(() => { if (!md.isConnected) { clearInterval(wait); go(`t/${tid}`); } }, 100);
    setTimeout(() => clearInterval(wait), 30000);
    $('[data-m="close"]', md)?.click();
    return;
  }
  if (a === 'dl-pull' && !await askConfirm(tr('Update from the private device?'), tr('Name, serial number and purchase date are copied from there; the prices stay.'), {ok: tr('Update')})) return;
  if (a === 'dl-unlink' && !await askConfirm(tr('Remove the link?'), tr('The device and the office equipment both stay; only the link goes.'), {ok: tr('Remove link')})) return;
  b.disabled = true;
  try {
    if (a === 'dl-take') { const j = await rawFetch('POST', `${AST_URL}/${id}/to-device`, {}); toast(tr('Added as a private device'), () => go(`t/${j.task.id}`), 0, tr('Open')); }
    else if (a === 'dl-pull') { await rawFetch('POST', `/api/life/device-links/${+b.dataset.link}/pull`, {into: 'equipment'}); toast(tr('Updated')); ofcReload('equipment'); }
    else if (a === 'dl-unlink') await rawFetch('DELETE', `/api/life/device-links/${+b.dataset.link}`);
  } catch (er) { ofcErr(er); }
  b.disabled = false;
  astLinkLoad(md, id);
}
