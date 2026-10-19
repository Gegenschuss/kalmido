// 2.48.0 (#1356): receipts in the document sheet (docs.js dc_mdDraw): project + category of a document, set by people;
// an agent's suggestion waits here with Accept / Reject (one undo step each: reopen). Agents never set it themselves.
const RC = {id: null, d: null, seq: 0};

function rc_slot(doc) {
  if (RC.id !== doc.id) { RC.id = doc.id; RC.d = null; rc_load(); }
  return `<div class="rc-slot">${rc_html()}</div>`;
}
async function rc_load() {
  const id = RC.id, seq = ++RC.seq;
  let d = null; try { d = await rawFetch('GET', `/api/docs/${id}/receipt`); } catch { d = null; }
  if (seq !== RC.seq) return;
  RC.d = d; rc_draw();
}
function rc_draw() { const el = $('.rc-slot'); if (el) el.innerHTML = rc_html(); }
function rc_html() {
  const d = RC.d; if (!d) return '';
  const r = d.receipt, w = d.can_edit;
  const sug = d.suggestions.map(s => `<div class="rc-sug" role="group" aria-label="${esc(tr('Suggestion of {0}', s.agent?.name || ''))}">
      <span><span class="muted">${esc(tr('Suggestion of {0}', s.agent?.name || tr('an agent')))}:</span> ${[s.project && `<b>${esc(s.project.name || tr('Project #{0}', s.project.id))}</b>`, s.category && `<b>${esc(s.category)}</b>`].filter(Boolean).join(' · ')}
      ${s.note ? `<br><span class="muted">${esc(s.note)}</span>` : ''}
      ${rc_money(s, w)}</span>
      ${w ? `<span class="rc-acts"><button type="button" class="btn sm" data-rc="reject:${s.id}">${tr('Reject')}</button><button type="button" class="btn sm pri" data-rc="accept:${s.id}">${tr('Accept')}</button></span>` : ''}</div>`).join('');
  const projOpts = `<option value="">${tr('No project')}</option>` + d.projects.map(p => `<option value="${p.id}" ${r.project?.id === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')
    + (r.project && !d.projects.some(p => p.id === r.project.id) ? `<option value="${r.project.id}" selected>${esc(r.project.name || tr('Project #{0}', r.project.id))}</option>` : '');
  return `<h4 class="rc-h">${tr('Receipt')}</h4>${sug}
    <div class="row"><label for="rc-proj">${tr('Project')}</label><select id="rc-proj" data-rcf="project" ${w ? '' : 'disabled'}>${projOpts}</select></div>
    <div class="row"><label for="rc-cat">${tr('Category')}</label><input id="rc-cat" data-rcf="category" value="${esc(r.category || '')}" maxlength="60" list="rc-cl" autocomplete="off" placeholder="${esc(tr('e.g. Travel, Material, Software'))}" ${w ? '' : 'disabled'}><datalist id="rc-cl">${d.categories.map(c => `<option value="${esc(c)}">`).join('')}</datalist></div>
    <div class="row"><label for="rc-vat">${tr('VAT rate')}</label><select id="rc-vat" data-rcf="vat" ${w ? '' : 'disabled'}><option value="">${tr('unknown')}</option>${['19', '7', '0'].map(v => `<option value="${v}" ${r.vat_pct === v ? 'selected' : ''}>${v} %</option>`).join('')}</select></div>`;  // 2.90.0 A (#1921)
}
// 2.121.0 C (#2096): amount, currency and VAT rate of a suggestion, changeable before Accept
function rc_money(s, w) {
  if (!s.amount && !s.vat_pct && !s.currency) return '';
  if (!w) return `<br><b>${esc([s.amount, s.currency].filter(Boolean).join(' '))}</b>${s.vat_pct ? ` · ${esc(s.vat_pct)} %` : ''}`;
  return `<span class="rc-money"><input inputmode="decimal" data-rcs="amount" value="${esc(s.amount || '')}" aria-label="${esc(tr('Amount'))}" placeholder="${esc(tr('Amount'))}" autocomplete="off">
    <input data-rcs="currency" value="${esc(s.currency || '')}" maxlength="3" aria-label="${esc(tr('Currency'))}" placeholder="${esc(tr('Currency'))}" autocomplete="off">
    <select data-rcs="vat_pct" aria-label="${esc(tr('VAT rate'))}"><option value="">${tr('unknown')}</option>${['19', '7', '0'].map(v => `<option value="${v}" ${s.vat_pct === v ? 'selected' : ''}>${v} %</option>`).join('')}</select></span>`;
}
function rc_accBody(b) {
  const box = b.closest('.rc-sug'), o = {};
  if (!box) return o;
  box.querySelectorAll('[data-rcs]').forEach(f => { o[f.dataset.rcs] = f.value.trim(); });
  return o;
}
const rc_cur = () => ({project_id: RC.d?.receipt?.project?.id || null, category: RC.d?.receipt?.category || '', vat_pct: RC.d?.receipt?.vat_pct ?? null});  // 2.90.0 A (#1921): + VAT rate
async function rc_put(id, v) {
  const j = await api('PUT', `/api/docs/${id}/receipt`, v);
  if (RC.id === id) { RC.d = j; rc_draw(); }
  return {};
}
async function rc_post(id, sid, act, body) {
  const j = await api('POST', `/api/receipt-suggestions/${sid}/${act}`, body);
  if (RC.id === id) { RC.d = j; rc_draw(); }
  return {};
}
document.addEventListener('change', async e => {
  const f = e.target.closest('.rc-slot [data-rcf]'); if (!f || !RC.d) return;
  const id = RC.id, from = rc_cur(), to = {...from};
  if (f.dataset.rcf === 'project') to.project_id = f.value ? +f.value : null;
  else if (f.dataset.rcf === 'vat') to.vat_pct = f.value || null;
  else to.category = f.value.trim();
  try { await rc_put(id, to); } catch { rc_draw(); return; }
  const label = tr('Changed receipt');
  histToast(label, histAdd({label, undo: () => rc_put(id, from), redo: () => rc_put(id, to)}));
});
document.addEventListener('click', async e => {
  const b = e.target.closest('.rc-slot [data-rc]'); if (!b) return;
  const [act, sid] = b.dataset.rc.split(':'), id = RC.id;
  b.disabled = true;
  const body = act === 'accept' ? rc_accBody(b) : undefined;
  try { await rc_post(id, +sid, act, body); } catch { b.disabled = false; return; }
  const label = act === 'accept' ? tr('Suggestion accepted') : tr('Suggestion rejected');
  histToast(label, histAdd({label, undo: () => rc_post(id, +sid, 'reopen'), redo: () => rc_post(id, +sid, act, body)}));
});
// 2.121.0 A (#2092): what the recognition read off a receipt (supplier, number, net, VAT rate, gross) -- one line
// "Recognised: ..." with Take over / Discard while it would change something (doc.extracted.new); Take over and Discard are
// one undo step each. The invoice number stays visible (copy button) even after the take-over.
function rx_html(d) {
  const x = d?.extracted; if (!x) return '';
  const w = d.role !== 'view', cur = x.currency || d.currency;
  const parts = [x.supplier && `<b>${esc(x.supplier)}</b>`, x.invoice_no && esc(tr('No. {0}', x.invoice_no)),
    x.net && `${tr('net')} ${esc(dc_money(x.net, cur))}`, x.vat_pct && esc(tr('VAT {0} %', x.vat_pct)), x.gross && `${tr('gross')} ${esc(dc_money(x.gross, cur))}`].filter(Boolean);
  const line = w && !x.hidden && x.new?.length && parts.length ? `<div class="rx-sug" role="group" aria-label="${esc(tr('Recognised'))}">
    <span><span class="muted">${tr('Recognised')}:</span> ${parts.join(' · ')}</span>
    <span class="rc-acts"><button type="button" class="btn sm" data-rx="dismiss:${d.id}">${tr('Discard')}</button><button type="button" class="btn sm pri" data-rx="apply:${d.id}">${tr('Take over')}</button></span></div>` : '';
  const no = x.invoice_no ? `<div class="rx-no"><span class="muted">${tr('Invoice number')}:</span> <span class="rx-nov">${esc(x.invoice_no)}</span>
    <button type="button" class="linkbtn" data-rx="copy:${d.id}" aria-label="${esc(tr('Copy'))}">${tr('Copy')}</button></div>` : '';
  return line || no ? `<div class="rx-slot">${line}${no}</div>` : '';
}
async function rx_post(id, b) {
  const j = await api('POST', `/api/docs/${id}/extracted`, b);
  if (typeof DC === 'object' && DC.doc?.id === id && j.doc) { DC.doc = j.doc; dc_mdDraw($('.dc-md')); dc_load(); }
  if (RC.id === id) rc_load();
  if (typeof bkRxAfter === 'function') bkRxAfter(id);
  return j;
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-rx]'); if (!b) return;
  const [act, sid] = b.dataset.rx.split(':'), id = +sid;
  if (act === 'copy') {
    const v = b.closest('.rx-no')?.querySelector('.rx-nov')?.textContent || '';
    try { await navigator.clipboard.writeText(v); toast(tr('Copied')); } catch { toast(tr('Copying is blocked in this browser')); }
    return;
  }
  b.disabled = true;
  let j; try { j = await rx_post(id, {do: act}); } catch { b.disabled = false; return; }
  if (act === 'apply') {
    const before = j.before, label = tr('Recognised values taken over');
    histToast(label, histAdd({label, undo: () => rx_post(id, {do: 'restore', before}), redo: () => rx_post(id, {do: 'apply'})}));
  } else {
    const label = tr('Suggestion discarded');
    histToast(label, histAdd({label, undo: () => rx_post(id, {do: 'show'}), redo: () => rx_post(id, {do: 'dismiss'})}));
  }
});
