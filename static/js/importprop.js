/* Kalmido web client: 2.68.0 (#1839) -- an agent reads old data (today: fixed costs) and proposes it as an import, the
   person decides. The proposal sheet of agents.js (propOpen / propDraw) shows for kind "import" the preview of the
   spreadsheet import (office_cashflow.js fci_modal): every row new / already there (unticked) / with an error (greyed out,
   with the reason), the VAT per row, net and gross, the office it goes into and "Take over N rows". The server judges the
   rows against the office when the card is opened and again when it is accepted (agents/importprop.py); one undo step.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const aim_is = v => v?.kind === 'import';
const AIM_VATS = [0, 7, 19];
const aim_rows = v => v.import?.rows || [];
const aim_keys = v => aim_rows(v).filter(r => r.sel).map(r => r.k);  // ticked at first: the new rows
// 2.149.0 F (#2519): the money format of the office (office.js) - propOpen loads it first; the plain one when that failed
const aim_money = n => typeof ofcMoney === 'function' ? ofcMoney(n) : fmtMoney(n);
function aim_gross(r, vat) { const n = +r.amount || 0; return (Math.round(n * (100 + vat) + Number.EPSILON) / 100).toFixed(2); }
function aim_rowHtml(r, P) {
  const rp = k => tr(RK_CF_REPEATS.find(x => x[0] === k)?.[1] || k);
  if (r.status === 'error') return `<li class="fcirow err"><span class="fcick" aria-hidden="true">${ic('x', 's')}</span><span class="ofcn"><b>${esc(r.label || tr('Row {0}', r.row))}</b><small>${esc(tr('Row {0}', r.row))} · ${esc(r.reason)}</small></span></li>`;
  const on = P.sel.has(r.k), vat = P.ed[r.k]?.vat_rate ?? r.vat_rate;
  return `<li class="fcirow aim-r ${on ? 'on' : ''} ${r.status}" data-k="${esc(r.k)}"><label class="fcick"><input type="checkbox" class="aim-ck" data-aim="sel" ${on ? 'checked' : ''} aria-label="${esc(tr('Take over {0}', r.label))}"></label>
    <span class="ofcn"><b>${esc(r.label)}</b><small class="muted">${esc([rp(r.repeat), tr('from {0}', fmtDateLoc(r.start)), r.until ? tr('until {0}', fmtDateLoc(r.until)) : '', r.category, r.status === 'dup' ? r.reason : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="fciamt"><span>${aim_money(r.amount)} <small class="muted">${tr('net')}</small></span><small class="muted aim-g">${aim_money(aim_gross(r, vat))} ${tr('gross')}</small><select data-aim="vat" aria-label="${esc(tr('VAT rate'))}">${AIM_VATS.map(x => `<option value="${x}" ${+vat === x ? 'selected' : ''}>${x} %</option>`).join('')}</select></span></li>`;
}
function aim_draw(v) {
  const P = S.prop, im = v.import || {}, p = v.proposal || {}, rows = aim_rows(v), cn = im.counts || {};
  const where = im.office ? `<div class="aim-to">${ic('building', 's')}<span>${esc(tr('Into: {0}', im.office.name))}</span></div>`
    : `<div class="calerr" role="alert">${esc(im.problem || tr('unknown'))}</div>`;
  const main = `<div class="lyp-head"><span class="lyp-by">${esc(tr('Proposal by {0}', v.agent.name))}</span> · ${esc(tr('Fixed costs'))}</div>
    ${p.summary ? `<div class="ppsum">${commentBody(p.summary, {})}</div>` : ''}
    ${p.note ? `<div class="shint aim-note">${esc(p.note)}</div>` : ''}
    ${where}
    <p class="muted">${esc([trn('{0} new', '{0} new', cn.new || 0), cn.dup ? trn('{0} already there', '{0} already there', cn.dup) : '', cn.error ? trn('{0} with an error', '{0} with an error', cn.error) : ''].filter(Boolean).join(' · '))}</p>
    <ul class="fcilist aim-l" role="list">${rows.map(r => aim_rowHtml(r, P)).join('')}</ul>
    <div class="shint keep">${esc(tr('Taking over creates the ticked fixed costs as you in this office; nothing else changes. One step, undo takes it back.'))}${im.expires_at ? ' ' + esc(tr('Open until {0}', dayLabel(im.expires_at.slice(0, 10)))) : ''}</div>`;
  const foot = `<button class="btn danger" data-pp="discard" aria-label="${esc(tr('Decline|proposal'))}">${thumbIc(false)} ${esc(tr('Decline|proposal'))}</button><span class="spacer"></span>
    <button class="btn" data-pp="close">${tr('Close')}</button><button class="btn pri" data-pp="apply" ${im.office ? '' : 'disabled'}></button>`;
  return {main, foot};
}
// the generic change / input handler of the sheet hands every field here first (agents.js propEdit)
function aim_propEdit(el) {
  const P = S.prop; if (!P || !aim_is(P.v)) return false;
  const row = el.closest?.('.aim-r'), f = el.dataset?.aim; if (!row || !f) return true;
  const k = row.dataset.k, r = aim_rows(P.v).find(x => x.k === k); if (!r) return true;
  if (f === 'sel') { el.checked ? P.sel.add(k) : P.sel.delete(k); row.classList.toggle('on', el.checked); }
  else if (f === 'vat') {
    const vat = +el.value; P.ed[k] = {vat_rate: vat};
    const g = $('.aim-g', row); if (g) g.innerHTML = `${aim_money(aim_gross(r, vat))} ${tr('gross')}`;
  }
  aim_count();
  return true;
}
function aim_count() {
  const P = S.prop, b = $('[data-pp="apply"]', P.md), n = P.sel.size; if (!b) return;
  b.textContent = trn('Take over {0} row', 'Take over {0} rows', n);
  b.disabled = !n || !P.v.import?.office;
}
// after accept / undo / redo: the cash flow shows the new fixed costs when it is open
function aim_after() { if (typeof rk_cfReload === 'function' && S.route?.mod === 'office') Promise.resolve(rk_cfReload()).catch(() => {}); }
const aim_toast = r => trn('{0} fixed cost imported', '{0} fixed costs imported', r.created || 0);
