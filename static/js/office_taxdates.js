// 2.90.0 C (#1922): tax dates as tasks (section in the bookkeeping tab; 2.365.2 D (#2789): in Settings > Company & office > Bank & taxes)
const TXD = {data: null, loading: false, gen: 0};  // gen: 2.506.1 (#1922): counts the saves, a load begun before one is dropped
async function txdLoad() {
  if (TXD.loading) return;
  TXD.loading = true;
  const gen = TXD.gen;
  // 2.506.1 (#1922, CI red of 2.506.0): a load still under way while a change is saved answered with the old state after the
  // save's answer and put it back for good (the page showed "None" although "Monthly" was saved)
  let d = null; try { d = await api('GET', '/api/office/tax-dates'); } catch (x) { d = null; }
  if (gen === TXD.gen) TXD.data = d;
  TXD.loading = false;
  if (typeof ofcDraw === 'function') ofcDraw();
}
const TXD_NAMES = {ustva: N_('VAT return'), est: N_('Income tax prepayment'), gewst: N_('Trade tax prepayment')};
function txdSectionHtml() {
  if (TXD.oid !== OFC.info?.org_id) { TXD.oid = OFC.info?.org_id; TXD.data = null; }  // 2.365.2 D (#2789): Settings follow the workspace
  const d = TXD.data;
  if (!d) { if (!TXD.loading) setTimeout(txdLoad, 0); return ''; }
  const ppl = d.people || [], tasksOn = Object.values(d.tasks || {}).some(Boolean);
  const yr = d.ustva === 'year';  // 2.122.0 D (#2315): only the annual VAT return, no extension
  const nxt = (d.next || []).map(n => `<li><b>${esc(yr && n.kind === 'ustva' ? tr('Annual VAT return') : tr(TXD_NAMES[n.kind]))}</b> <span class="muted">${esc(tr('Deadline {0}', fmtDateLoc(n.date)))} · ${esc(tr('Task due {0}', fmtDateLoc(n.due)))}</span></li>`).join('');
  const sel = (v, o) => `<option value="${v}" ${d.ustva === v ? 'selected' : ''}>${esc(o)}</option>`;
  return `<div class="txd" data-txd-root><div class="ofcbar"><h3 class="ofcgrp">${tr('Tax dates')}</h3></div>
    <div class="row"><label for="txd-ustva">${tr('VAT return')}</label><select id="txd-ustva" data-txd="ustva">${sel('none', tr('None'))}${sel('month', tr('Monthly'))}${sel('quarter', tr('Quarterly'))}${sel('year', tr('Yearly (annual return only)'))}</select></div>
    ${d.small_business && d.ustva === 'none' ? `<p class="muted ofchint">${tr('As a small business you usually do not need a VAT return.')}</p>` : ''}
    ${yr ? `<p class="muted ofchint">${tr('With a tax adviser the deadline is usually later; please agree it with your tax adviser.')}</p>` : `<label class="chkl"><input type="checkbox" data-txd="ustva_ext" ${d.ustva_ext ? 'checked' : ''} ${d.ustva === 'none' ? 'disabled' : ''}><span>${tr('Permanent deadline extension (one month later)')}</span></label>`}
    <label class="chkl"><input type="checkbox" data-txd="est" ${d.est ? 'checked' : ''}><span>${tr('Income tax prepayments (10 Mar, 10 Jun, 10 Sep, 10 Dec)')}</span></label>
    <label class="chkl"><input type="checkbox" data-txd="gewst" ${d.gewst ? 'checked' : ''}><span>${tr('Trade tax prepayments (15 Feb, 15 May, 15 Aug, 15 Nov)')}</span></label>
    <div class="row"><label for="txd-lead">${tr('Days in advance')}</label><input id="txd-lead" type="number" min="0" max="30" inputmode="numeric" data-txd="lead_days" value="${+d.lead_days}"></div>
    ${ppl.length > 1 ? `<div class="row"><label for="txd-user">${tr('Assignee|person')}</label><select id="txd-user" data-txd="user">${ppl.map(p => `<option value="${p.id}" ${p.id === (d.user || S.me?.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>` : ''}
    ${d.lost ? `<p class="aerr" role="alert">${tr('The person responsible is no longer an administrator. Please choose someone else.')}</p>` : ''}
    ${nxt ? `<ul class="txdnext" role="list">${nxt}</ul>` : ''}
    ${tasksOn ? `<p class="muted ofchint"><a href="#inbox">${tr('The tasks are in the Basket of the person.')}</a></p>` : ''}
    <p class="muted ofchint">${tr('Each date is a repeating task. Off: the task is ended, not deleted.')}</p></div>`;  // 2.298.0 A2 (#3186): the tax note once at the end of the bookkeeping page
}
document.addEventListener('change', async e => {
  const t = e.target.closest?.('[data-txd]'); if (!t || !TXD.data) return;
  const k = t.dataset.txd, old = {ustva: TXD.data.ustva, ustva_ext: TXD.data.ustva_ext, est: TXD.data.est, gewst: TXD.data.gewst, lead_days: TXD.data.lead_days, user: TXD.data.user};
  let v = t.type === 'checkbox' ? (t.checked ? 1 : 0) : (k === 'ustva' ? t.value : +t.value);
  if (k === 'lead_days') v = Math.max(0, Math.min(30, Math.round(v) || 0));
  const put = async b => {
    const gen = ++TXD.gen;
    const d = await api('PUT', '/api/office/tax-dates', b);
    if (gen !== TXD.gen) return;  // a later change has answered or is under way: its answer counts
    TXD.data = d;
    const st = typeof OFC === 'object' && OFC.info?.settings;  // 2.122.0 D (#2315): the VAT period of the bookkeeping follows
    if (st) st.tax_dates = Object.assign({}, st.tax_dates, {ustva: TXD.data.ustva});
    if ('ustva' in b && typeof BK === 'object') BK.period = null;  // the bookkeeping picks its period anew
    if (typeof ofcDraw === 'function') ofcDraw();
  };
  try {
    await put({[k]: v});
    const undo = {}; for (const f in old) if (old[f] != null) undo[f] = old[f];
    toast(tr('Tax dates saved'), async () => { await put(undo); });
  } catch (x) { toast(x.message || tr('unknown')); if (typeof ofcDraw === 'function') ofcDraw(); }
});
