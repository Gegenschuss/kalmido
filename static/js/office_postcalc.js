// @ts-check
// 2.1158.0 (#4566 B): the post-calculation of an accepted quotation, module "postcalc" (lazyload.js), opened by the button
// "Post-calculation" next to "Create invoice" (office_docs.js kvaNextHtml). The server computes everything
// (kalmido/office/postcalc.py): GET .../postcalc = the preview with planned / actual per position, "Create invoice draft" =
// POST .../postcalc, then the new draft opens. Nothing is finalised.
'use strict';

const OPC_STATE = {time: N_('by time'), not_time: N_('not by time'), none: N_('no task'), part: N_('part with one amount')};

function opc_rowHtml(x, d) {
  const unit = x.unit ? ofdUnit(x.unit, d) : '';
  const diff = x.state === 'time' && x.diff_qty ? `<span class="opc-diff ${x.diff_qty > 0 ? 'up' : 'down'}">${esc((x.diff_qty > 0 ? '+' : '') + x.diff_text)}</span>` : '';
  return `<tr class="opc-${esc(x.state)}" data-opc-key="${esc(x.key || '')}"><th scope="row">${esc(x.title || tr('Position'))}<small class="muted opc-st">${esc(tr(OPC_STATE[x.state] || x.state))}</small></th>`
    + `<td class="num">${esc(x.plan_text)} ${esc(unit)}</td><td class="num opc-act">${esc(x.actual_text)} ${esc(unit)}${x.actual_h != null && x.state !== 'time' ? `<small class="muted">${esc(tr('{0} h tracked', fmtNum(x.actual_h, 2)))}</small>` : ''}</td>`
    + `<td class="num">${/*html-ok*/ diff /* every value esc() */}</td><td class="num">${esc(x.plan_net_text)}</td><td class="num opc-actnet">${esc(x.actual_net_text)}</td></tr>`;
}

function opc_html(j, d) {
  const s = j.sums || {};
  const rows = j.rows || [];
  if (!rows.length) return emptyState({title: tr('No positions to invoice.'), size: 'sec'});
  const hint = s.timed ? tr('Positions in hours with a linked task carry the tracked hours (rounded to {0} h) at the quotation\'s rate.', fmtNum(s.step_h || 0.25, 2))
    : tr('No position in hours has a linked task with tracked time: the draft takes the quotation\'s quantities.');
  return `<p class="muted opc-hint">${esc(hint)}</p><div class="opc-wrap"><table class="opc-tab"><thead><tr><th scope="col">${esc(tr('Position'))}</th>`
    + `<th scope="col" class="num">${esc(tr('Planned'))}</th><th scope="col" class="num">${esc(tr('Actual'))}</th><th scope="col" class="num">${esc(tr('Difference'))}</th>`
    + `<th scope="col" class="num">${esc(tr('Planned'))} ${esc(tr('net'))}</th><th scope="col" class="num">${esc(tr('Actual'))} ${esc(tr('net'))}</th></tr></thead>`
    + `<tbody>${/*html-ok*/ rows.map(x => opc_rowHtml(x, d)).join('') /* opc_rowHtml escapes every value */}</tbody>`
    + `<tfoot><tr><th scope="row">${esc(tr('Sum'))}</th><td></td><td></td><td class="num opc-sumdiff">${esc(s.diff_net_text || '')}</td><td class="num opc-sumplan">${esc(s.plan_net_text || '')}</td><td class="num opc-sumact">${esc(s.actual_net_text || '')}</td></tr></tfoot></table></div>`
    + `<p class="muted">${esc(tr('Before tax. The automatic lines (producing, raw data, discount) keep the quotation\'s amounts. The draft is not finalised.'))}</p>`;
}

async function opc_open(d) {
  const md = /** @type {any} */ (ofdDlg(tr('Post-calculation'), `<div class="opc" aria-live="polite">${/*html-ok*/ loadingHtml('sec')}</div>`, tr('Create invoice draft'), () => opc_create(d)));
  md.classList.add('opc-dlg');
  const ok = $('[data-m="ok"]', md);
  ok.disabled = true;
  let j;
  try { j = await api('GET', `/api/office/docs/${d.id}/postcalc`); }
  catch (x) { $('.opc', md).innerHTML = errorState({sub: ofcErrHere(x), size: 'sec'}); return; }
  $('.opc', md).innerHTML = opc_html(j, d);
  ok.disabled = !(j.rows || []).length;
}

// the draft; another invoice of this quotation exists -> the server's 409 asks once (as oil_post)
async function opc_create(d) {
  const call = extra => ofdRefCall(`opc${d.id}`, ref => rawFetch('POST', `/api/office/docs/${d.id}/postcalc`, {...extra, client_ref: ref}));
  let j;
  try { j = await call({}); } catch (x) {
    if (x.data?.code !== 'invoice_exists') throw x;
    if (!await askConfirm(x.message, '', {ok: tr('Create another invoice')})) return false;
    j = await call({force: true});
  }
  if (!j) return false;
  OFD.list = null; OFD.kind = 'invoice'; OFD.doc = j;
  go(ofd_href(j.id, j.kind));
  return true;
}
