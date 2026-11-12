// @ts-check
// 2.1041.0 (#5812): "Adjust prices…" of a quotation draft (Nachkalkulieren), module "reprice" (lazyload.js), opened from the
// document's "More" menu (office_docs.js ofdMoreItems). The unit prices themselves change, no discount line: by x %, to a
// target sum (net / gross) or to a surplus of x % (admins, with external costs). The server computes everything
// (POST /api/office/docs/<id>/reprice, kalmido/office/reprice.py): every change of the dialog asks it for a preview
// (apply false), "Apply" writes it as one undo step. The positions to change are ticked in the dialog (the editor has no
// selection of its own); a quotation with parts chooses whose prices: the title page or one part.
'use strict';

const ORP = {seq: 0, t: 0};
const orp_scopes = d => [[0, tr('Title page')], ...(d.parts || []).filter(p => p.kind === 'items').map(p => [p.id, p.title || tr('Part {0}', p.id)])];
const orp_items = (d, pid) => ((pid ? (d.parts || []).find(p => p.id === pid)?.items : d.items) || []).filter(it => (it.kind || 'service') === 'service' && it.unit !== 'percent' && it.id);
const orp_sym = () => ({EUR: '€', USD: '$', GBP: '£'})[ofcHome()] || ofcHome();
const orp_pct = n => fmtNum(n, 2);
const orp_hasCosts = d => +(d.totals?.costs || 0) > 0;

function orp_open(d) {
  const admin = OFD.role === 'admin', vat = d.vat_mode !== 'novat', costs = orp_hasCosts(d);
  const prodOn = !!d.producing_on && +(d.totals?.producing_days || 0) > 0;
  const scopes = orp_scopes(d);
  const seg = (name, opts, cur) => `<div class="seg" role="radiogroup" data-orp-seg="${esc(name)}">${opts.map(([v, n, dis]) => `<button type="button" role="radio" data-v="${esc(v)}" aria-checked="${v === cur ? 'true' : 'false'}" class="${v === cur ? 'on' : ''}" ${dis ? 'disabled' : ''}>${esc(n)}</button>`).join('')}</div>`;
  const modes = [['pct', tr('By percent')], ['target', tr('Target sum')], ...(admin ? [['margin', tr('Surplus'), !costs]] : [])];
  const body = `<div class="orp" data-mode="pct">
    ${/*html-ok*/ seg('mode', modes, 'pct') /* orp_open's seg: every value escaped */}
    ${admin && !costs ? `<p class="muted orp-nocost">${esc(tr('The surplus can only be aimed at when the quotation has external costs (purchase prices).'))}</p>` : ''}
    <div class="row"><label for="orp-v" class="orp-vl">${esc(tr('Change in %'))}</label><input id="orp-v" type="text" inputmode="decimal" autocomplete="off" value="" placeholder="${esc(tr('e.g. {0}', '10'))}"></div>
    <div class="row orp-net" hidden>${/*html-ok*/ vat ? seg('net', [['net', tr('net')], ['gross', tr('gross')]], 'net') : '' /* seg escapes */}</div>
    <div class="row"><label for="orp-round">${esc(tr('Rounding'))}</label><select id="orp-round"><option value="cent">${esc(tr('to the cent'))}</option><option value="euro">${esc(tr('to whole {0}', orp_sym()))}</option><option value="five">${esc(tr('to 5 {0}', orp_sym()))}</option></select></div>
    <div class="row orp-rest" hidden><label class="chkl"><input type="checkbox" id="orp-rest" checked> ${esc(tr('Put the rest on one position'))}</label></div>
    ${prodOn ? `<div class="row"><label class="chkl"><input type="checkbox" id="orp-prod" checked> ${esc(tr('Adjust the producing day rate too'))}</label></div>` : ''}
    ${scopes.length > 1 ? `<div class="row"><label for="orp-scope">${esc(tr('Prices of'))}</label><select id="orp-scope">${scopes.map(([v, n]) => `<option value="${esc(v)}">${esc(n)}</option>`).join('')}</select></div>` : ''}
    <details class="orp-pos"><summary>${esc(tr('Positions'))} <span class="muted orp-cnt"></span></summary><ul class="orp-list" role="list"></ul></details>
    <div class="orp-prev" aria-live="polite"></div></div>`;
  const md = /** @type {any} */ (ofdDlg(tr('Adjust prices…'), body, tr('Apply'), m => orp_apply(m, d)));
  md.classList.add('orp-dlg');
  const st = {mode: 'pct', net: 'net'};
  md._orp = st;
  const list = () => {
    const pid = +($('#orp-scope', md)?.value || 0), its = orp_items(d, pid);
    $('.orp-list', md).innerHTML = its.map(it => `<li><label class="chkl"><input type="checkbox" data-orp-it="${esc(it.id)}" checked> ${esc(it.title || tr('Position'))} <span class="muted">${esc(ofdMoney(it.rate, d))}</span></label></li>`).join('')
      || `<li class="muted">${esc(tr('No position with a price'))}</li>`;
    orp_count(md);
  };
  list();
  md.addEventListener('click', e => {
    const b = /** @type {any} */ (e.target).closest('[data-orp-seg] button'); if (!b || b.disabled) return;
    const g = b.closest('[data-orp-seg]');
    $$('button', g).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-checked', String(x === b)); });
    st[g.dataset.orpSeg] = b.dataset.v;
    if (g.dataset.orpSeg === 'mode') orp_modeSync(md, d);
    orp_ask(md, d);
  });
  md.addEventListener('input', e => { if (/** @type {any} */ (e.target).id === 'orp-v') orp_ask(md, d, 350); });
  md.addEventListener('change', e => { const t = /** @type {any} */ (e.target); if (t.id === 'orp-scope') list(); if (t.dataset.orpIt) orp_count(md); if (t.id !== 'orp-v') orp_ask(md, d); });
  orp_modeSync(md, d);
  return md;
}

function orp_count(md) {
  const all = $$('[data-orp-it]', md), on = all.filter(x => x.checked).length;
  $('.orp-cnt', md).textContent = all.length ? tr('{0} of {1}', on, all.length) : '';
}

function orp_modeSync(md, d) {
  const m = md._orp.mode, v = $('#orp-v', md);
  $('.orp', md).dataset.mode = m;
  $('.orp-vl', md).textContent = m === 'pct' ? tr('Change in %') : m === 'margin' ? tr('Surplus in %') : tr('Target sum');
  v.placeholder = m === 'target' ? ofdMoney(d.totals?.net || 0, d) : tr('e.g. {0}', m === 'margin' ? '30' : '10');
  $('.orp-net', md).hidden = m !== 'target' || d.vat_mode === 'novat';
  $('.orp-rest', md).hidden = m === 'pct';
}

// the request of the dialog's state (null: no valid number yet)
function orp_body(md) {
  const st = md._orp, v = ofcNum($('#orp-v', md).value, 2);
  if (v == null || !isFinite(v)) return null;
  const all = $$('[data-orp-it]', md), on = all.filter(x => x.checked).map(x => +x.dataset.orpIt);
  const pid = +($('#orp-scope', md)?.value || 0);
  return {mode: st.mode === 'target' ? (md.querySelector('.orp-net:not([hidden])') && st.net === 'gross' ? 'gross' : 'net') : st.mode, value: v,
    round: $('#orp-round', md).value, rest: st.mode !== 'pct' && !!$('#orp-rest', md)?.checked, producing: !!$('#orp-prod', md)?.checked,
    ...(on.length === all.length ? {} : {item_ids: on}), ...(pid ? {part_id: pid} : {})};
}

// a preview from the server; an older answer than the last question is dropped
function orp_ask(md, d, wait = 0) {
  clearTimeout(ORP.t);
  ORP.t = setTimeout(async () => {
    const b = orp_body(md), out = $('.orp-prev', md), n = ++ORP.seq;
    if (!b) { out.innerHTML = ''; return; }
    if (b.item_ids && !b.item_ids.length) { out.innerHTML = `<p class="muted">${esc(tr('Select at least one position.'))}</p>`; return; }
    out.classList.add('busy');
    try {
      const j = await rawFetch('POST', `/api/office/docs/${d.id}/reprice`, {...b, apply: false});
      if (n === ORP.seq && md.isConnected) { out.innerHTML = orp_prevHtml(j, d); md._orpLast = j; }
    } catch (x) { if (n === ORP.seq && md.isConnected) out.innerHTML = `<p class="err">${esc(ofcErrHere(x))}</p>`; }
    finally { if (n === ORP.seq) out.classList.remove('busy'); }
  }, wait);
}

function orp_prevHtml(j, d) {
  const row = (lbl, a, b) => `<tr><th scope="row">${esc(lbl)}</th><td>${esc(a)}</td><td aria-hidden="true">→</td><td><b>${esc(b)}</b></td></tr>`;
  const m = v => ofdMoney(v, d);
  if (!j.reachable) return `<p class="err orp-why">${esc(j.reason || '')}</p>`;
  const rows = [row(tr('Net'), m(j.before.net), m(j.after.net))];
  if (d.vat_mode !== 'novat') rows.push(row(tr('Gross'), m(j.before.gross), m(j.after.gross)));
  if (j.after.margin != null) rows.push(row(tr('Surplus'), `${m(j.before.margin)} (${orp_pct(j.before.margin_pct ?? 0)} %)`, `${m(j.after.margin)} (${orp_pct(j.after.margin_pct ?? 0)} %)`));
  if (j.producing_rate) rows.push(row(tr('Producing day rate'), m(j.producing_rate.before), m(j.producing_rate.after)));
  const dev = j.deviation == null ? '' : +j.deviation === 0 ? `<p class="orp-dev ok">${esc(tr('The target is met exactly.'))}</p>`
    : `<p class="orp-dev">${esc(tr('Deviation from the target: {0}', j.mode === 'margin' ? orp_pct(j.deviation) + ' %' : m(j.deviation)))}</p>`;
  const ch = (j.items || []).filter(x => x.before !== x.after);
  return `<p class="orp-pct">${esc(tr('Prices change by {0} %', orp_pct(j.pct)))}</p><table class="orp-sum">${/*html-ok*/ rows.join('') /* row() escapes */}</table>${/*html-ok*/ dev /* built from esc() */}`
    + (ch.length ? `<ul class="orp-chg muted" role="list">${ch.slice(0, 8).map(x => `<li>${esc(x.title || tr('Position'))}: ${esc(m(x.before))} → ${esc(m(x.after))}</li>`).join('')}${ch.length > 8 ? `<li>${esc(trn('and {0} more', 'and {0} more', ch.length - 8))}</li>` : ''}</ul>` : '');
}

async function orp_apply(md, d) {
  const b = orp_body(md);
  if (!b) throw new Error(tr('Enter a number.'));
  if (b.item_ids && !b.item_ids.length) throw new Error(tr('Select at least one position.'));
  const j = await ofdSave('POST', `/api/office/docs/${d.id}/reprice`, {...b, apply: true, expect_updated_at: OFD.doc?.updated_at});
  if (!j) return false;  // said by ofdSave (a conflict shows its bar)
  if (j.doc && OFD.doc && j.doc.id === OFD.doc.id) { OFD.doc = j.doc; OFD.log = null; ofdDraw(); }
  toast(tr('Prices changed by {0} %', orp_pct(j.pct)));
  return true;
}
