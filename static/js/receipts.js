// 2.48.0 (#1356): receipts in the document sheet (docs.js dc_mdDraw): project + category of a document, set by people;
// an agent's suggestion waits here with Accept / Reject (one undo step each: reopen). Agents never set it themselves.
const RC = {id: null, d: null, seq: 0};

function rc_slot(doc) {
  if (RC.id !== doc.id) { RC.id = doc.id; RC.d = null; RC.cb = null; rc_load(); }
  return `<div class="rc-slot">${rc_html()}</div><p class="rc-cb muted" ${RC.cb?.length ? '' : 'hidden'}>${esc(rc_cbText())}</p>`;  // 2.121.0 B (#2095): + the cash book hint
}
async function rc_load() {
  const id = RC.id, seq = ++RC.seq;
  let d = null; try { d = await rawFetch('GET', `/api/docs/${id}/receipt`); } catch { d = null; }
  if (seq !== RC.seq) return;
  RC.d = d; rc_draw();
  if (d) rc_cbHint(id, seq);
}
// 2.121.0 B (#2095): "In the cash book no. X" under the receipt (the server answers office admins only; else an empty list)
async function rc_cbHint(id, seq) {
  let j = null; try { j = await rawFetch('GET', `/api/docs/${id}/cashbook`); } catch { j = null; }
  if (seq !== RC.seq) return;
  RC.cb = j?.entries || [];
  const el = $('.rc-cb'); if (el) { el.hidden = !RC.cb.length; el.textContent = rc_cbText(); }
}
const rc_cbText = () => (RC.cb || []).map(e => tr('In the cash book {0} no. {1}', e.book, e.no)).join(' · ');
function rc_draw() { const el = $('.rc-slot'); if (el) el.innerHTML = rc_html(); }
function rc_html() {
  const d = RC.d; if (!d) return '';
  const r = d.receipt, w = d.can_edit;
  const sug = d.suggestions.map(s => `<div class="rc-sug" role="group" aria-label="${esc(tr('Suggestion of {0}', s.agent?.name || ''))}">
      <span><span class="muted">${esc(tr('Suggestion of {0}', s.agent?.name || tr('an agent')))}:</span> ${[s.project && `<b>${esc(s.project.name || tr('Project #{0}', s.project.id))}</b>`, s.category && `<b>${esc(s.category)}</b>`].filter(Boolean).join(' · ')}
      ${s.note ? `<br><span class="muted">${esc(s.note)}</span>` : ''}</span>
      ${w ? `<span class="rc-acts"><button type="button" class="btn sm" data-rc="reject:${s.id}">${tr('Reject')}</button><button type="button" class="btn sm pri" data-rc="accept:${s.id}">${tr('Accept')}</button></span>` : ''}</div>`).join('');
  const projOpts = `<option value="">${tr('No project')}</option>` + d.projects.map(p => `<option value="${p.id}" ${r.project?.id === p.id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')
    + (r.project && !d.projects.some(p => p.id === r.project.id) ? `<option value="${r.project.id}" selected>${esc(r.project.name || tr('Project #{0}', r.project.id))}</option>` : '');
  return `<h4 class="rc-h">${tr('Receipt')}</h4>${sug}
    <div class="row"><label for="rc-proj">${tr('Project')}</label><select id="rc-proj" data-rcf="project" ${w ? '' : 'disabled'}>${projOpts}</select></div>
    <div class="row"><label for="rc-cat">${tr('Category')}</label><input id="rc-cat" data-rcf="category" value="${esc(r.category || '')}" maxlength="60" list="rc-cl" autocomplete="off" placeholder="${esc(tr('e.g. Travel, Material, Software'))}" ${w ? '' : 'disabled'}><datalist id="rc-cl">${d.categories.map(c => `<option value="${esc(c)}">`).join('')}</datalist></div>
    <div class="row"><label for="rc-vat">${tr('VAT rate')}</label><select id="rc-vat" data-rcf="vat" ${w ? '' : 'disabled'}><option value="">${tr('unknown')}</option>${['19', '7', '0'].map(v => `<option value="${v}" ${r.vat_pct === v ? 'selected' : ''}>${v} %</option>`).join('')}</select></div>`;  // 2.90.0 A (#1921)
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
  try { await rc_post(id, +sid, act, act === 'accept' ? {} : undefined); } catch { b.disabled = false; return; }
  const label = act === 'accept' ? tr('Suggestion accepted') : tr('Suggestion rejected');
  histToast(label, histAdd({label, undo: () => rc_post(id, +sid, 'reopen'), redo: () => rc_post(id, +sid, act, act === 'accept' ? {} : undefined)}));
});
