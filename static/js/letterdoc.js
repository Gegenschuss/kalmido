// @ts-check
// 2.153.0 (#2028): at a document of the documents space (docs.js calls ltd_slot): "Write an answer", the linked letters
// (both directions, clickable), the deadline found in the text -> a task. D (#2031) adds its button through lta_docBtn.
'use strict';
const LTD = {id: null, d: null, info: null, seq: 0};
function ltd_slot(d) {
  if (LTD.id !== d.id) { LTD.id = d.id; LTD.info = null; ltd_load(); }
  LTD.d = d;
  return `<div class="ltd" data-nid="${d.id}">${ltd_html()}</div>`;
}
async function ltd_load() {
  const id = LTD.id, seq = ++LTD.seq;
  let x = null; try { x = await rawFetch('GET', `/api/office/letters/doc/${id}`); } catch { x = null; }
  if (seq !== LTD.seq) return;
  LTD.info = x && x.available ? x : null; ltd_draw();
}
function ltd_draw() { const el = $$(`.ltd[data-nid="${LTD.id}"]`).find(x => !x.closest('.dc-nb')); if (el) el.innerHTML = ltd_html(); }  // 2.755.0 (#5236): not a neighbour's frame
// ---- 2.755.0 (#5236): a neighbour drawn ahead (docview.js dcv_nbDraw) gets its letters in its own frame with its own data
// (e.ltd, nothing of LTD); after the snap ltd_take hands them over, so ltd_slot draws the same and loads nothing
async function ltd_nbFill(e, el) {
  const id = e.d.id, sig = e.ctrl.signal;
  const ag = typeof lta_nbLoad === 'function' ? lta_nbLoad(id) : Promise.resolve(undefined);  // letteragent.js: its own "draft the answer"
  let x = null; try { x = await rawFetch('GET', `/api/office/letters/doc/${id}`); } catch { x = null; }
  const a = await ag;
  if (sig.aborted || e.taken) return;
  e.ltd = {info: x && x.available ? x : null, lta: a};
  const box = el.querySelector(`.ltd[data-nid="${id}"]`); if (box) dcv_nbSet(box, ltd_html(e.ltd.info, e.d, a === undefined ? '' : lta_slotHtml(a)));
}
function ltd_take(id, x) {
  LTD.seq++; LTD.id = id; LTD.info = x.info;
  if (x.lta !== undefined && typeof lta_take === 'function') lta_take(id, x.lta);
}
const ltd_now = id => LTD.id === id && LTD.info ? {info: LTD.info, lta: typeof LTA === 'object' && LTA.id === id && LTA.d ? LTA.d : undefined} : null;
const ltd_day = v => typeof dc_day === 'function' ? dc_day(v) : (v || '');
const LTD_STATUS = {draft: 'Draft', sent: 'Sent', delivered: 'Delivered'};
function ltd_html(x = LTD.info, d = LTD.d, nbExt) {  // 2.755.0 (#5236): or a neighbour's (nbExt: its agents' slot, LTA stays the open one's)
  if (!x || !d) return '';
  const ext = nbExt !== undefined ? nbExt : typeof lta_docBtn === 'function' ? lta_docBtn(d) : '';
  const acts = `<div class="ltd-acts"><button type="button" class="btn sm" data-ltd="answer">${ic('mail', 's')} ${tr('Write an answer')}</button>${ext}</div>`;
  const list = x.letters.length ? `<ul class="ltd-list" aria-label="${esc(tr('Linked letters'))}">${x.letters.map(l => `<li><a href="${esc(l.href)}">${esc(l.subject || tr('Letter'))}</a>
      <span class="muted">${esc([l.kind === 'reply' ? tr('Answer to our letter') : tr('Our answer'), ltd_day(l.date), tr(LTD_STATUS[l.status] || l.status)].filter(Boolean).join(' · '))}</span></li>`).join('')}</ul>` : '';
  const dl = x.deadline, t = x.task;
  // the documents area already offers "Create task" for its due date: the deadline only when it says something new
  const showDl = dl && x.can_write && !(dl.date === d.due && !d.task_id && !t) && !(t && t.due === dl.date);
  const dlRow = showDl ? `<div class="ltd-dl">${ic('alarm', 's')} <span>${esc(tr('Deadline found: {0}', ltd_day(dl.date)))}</span>
      <button type="button" class="btn sm" data-ltd="dltask">${t ? tr('Set as due date') : tr('Create task')}</button>
      ${dl.text ? `<span class="muted ltd-src">${esc(dl.text)}</span>` : ''}</div>` : '';
  return `<h4 class="ltd-h">${tr('Correspondence')}</h4>${acts}${list}${dlRow}`;
}
async function ltd_click(e) {
  const b = e.target.closest('[data-ltd]'); if (!b) return;
  const box = b.closest('.ltd'); if (!box) return;
  const nid = +box.dataset.nid, a = b.dataset.ltd;
  if (a === 'answer') { location.hash = `#office/letters/new?answers=${nid}`; return; }
  if (a === 'dltask') {
    b.disabled = true;
    let x = null; try { x = await api('POST', `/api/office/letters/doc/${nid}/deadline-task`, {}); } catch { b.disabled = false; return; }
    if (LTD.d && LTD.d.id === nid && typeof DC !== 'undefined' && DC.doc?.id === nid) DC.doc.task_id = x.task_id;
    if (typeof load === 'function') load();
    const msg = x.existing ? tr('Due date set: {0}', ltd_day(x.due)) : tr('Task created: {0}', x.title);
    histToast(msg, histAdd({label: msg,
      undo: async () => {
        if (x.existing) await api('PATCH', `/api/tasks/${x.task_id}`, {due: x.old_due || null});
        else { await api('DELETE', `/api/tasks/${x.task_id}`); await api('DELETE', `/api/docs/${nid}/task`); if (typeof DC !== 'undefined' && DC.doc?.id === nid) DC.doc.task_id = null; }
        ltd_refresh(nid); return {};
      },
      redo: async () => { const y = await api('POST', `/api/office/letters/doc/${nid}/deadline-task`, {due: x.due}); x.task_id = y.task_id; ltd_refresh(nid); return {}; }}));
    ltd_refresh(nid);
  }
}
function ltd_refresh(nid) {
  if (LTD.id !== nid) return;
  ltd_load();
  if (typeof DC !== 'undefined' && DC.doc?.id === nid && typeof dc_mdDraw === 'function' && $('.dc-md')) dc_mdDraw($('.dc-md'));
}
document.addEventListener('click', ltd_click);
