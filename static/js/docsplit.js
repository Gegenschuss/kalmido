// @ts-check
/* Kalmido web client: Documents, 2.154.0 A (#1111). (1) A stack scan split into documents: the hint "Stack - split?" in the
   document sheet, the preview with page previews and cut lines (a cut moves / goes / comes with one tap between two pages),
   pages left out (separator sheets, blank pages on request, any page by a tap) and "Split" (one undo step: the documents into
   the trash, the stack back). (2) A document linked with an existing task (a task picker like the others, unlink with undo);
   the task side ("Document: <title>") lives in detail.js. Server: kalmido/docs/split.py, kalmido/docs/tasklink.py.
   Classic script sharing the global scope with the others (module docs, after docs.js). */
'use strict';

/** @type {{d: any, j: any, cuts: Set<number>, over: Map<number, boolean>, blank: boolean, thumbs: Object<number, string>}} */
const DSP = {d: null, j: null, cuts: new Set(), over: new Map(), blank: false, thumbs: {}};

// ---- the lines in the document sheet (docs.js dc_mdDraw: in place of the due-date line)
function dsp_sheetHtml(d, w) {
  const out = [];
  if (d.split?.stack && w) out.push(`<div class="dc-due dsp-hint" role="group" aria-label="${esc(tr('Stack - split?'))}">${ic('scissors', 's')} <span>${esc(tr('Stack - split? Several archive numbers were found on its pages.'))}</span>
    <button type="button" class="btn sm" data-dsp="dismiss">${tr('No stack')}</button><button type="button" class="btn sm pri" data-dsp="open">${tr('Split stack…')}</button></div>`);
  if (d.split?.no_asn) out.push(`<div class="dc-due muted dsp-noasn">${ic('info', 's')} <span>${esc(tr('Without an archive number: the pages before the first code of a stack.'))}</span></div>`);
  if (d.task) {
    out.push(`<div class="dc-due dsp-task">${ic(d.task.done ? 'done' : 'check', 's')} <span>${tr('Task')}: <a href="#t/${+d.task.id}">${esc(d.task.title)}</a></span>${w ? `<button type="button" class="btn sm" data-dsp="unlink">${tr('Unlink')}</button>` : ''}</div>`);
  } else if (w && !d.task_id) {
    const link = `<button type="button" class="btn sm" data-dsp="link">${ic('link', 's')} ${tr('Link with a task…')}</button>`;
    out.push(d.due ? `<div class="dc-due">${ic('alarm', 's')} <span>${esc(tr('Due on {0}', dc_day(d.due)))}</span><button type="button" class="btn sm" data-dc="task">${tr('Create task')}</button>${link}</div>`
      : `<div class="dc-due dsp-link">${link}</div>`);
  }
  return out.join('');
}
// the button in the sheet's actions: any PDF of two pages or more may be split by hand
const dsp_actBtn = (d, w) => w && !d.split?.stack && d.state === 'done' && (d.pages || 0) >= 2 && dc_isPdf(d)
  ? `<button type="button" class="btn sm" data-dsp="open">${ic('scissors', 's')} ${tr('Split stack…')}</button>` : '';

const dsp_redraw = async id => {
  for (const k of Object.keys(DLK)) delete DLK[k];  // the task side (detail.js) asks again
  if (DC.doc?.id !== id) return;
  try { DC.doc = await api('GET', `/api/docs/${id}`); } catch { return; }
  dc_mdDraw($('.dc-md'));
};

document.addEventListener('click', async e => {
  const b = /** @type {any} */ (e.target)?.closest?.('.dc-md [data-dsp]'); if (!b || !DC.doc) return;
  const d = DC.doc, act = b.dataset.dsp;
  if (act === 'open') { dsp_open(d); return; }
  if (act === 'link') { dsp_pick(d); return; }
  b.disabled = true;
  if (act === 'dismiss') {
    const go = undo => async () => { await api('POST', `/api/docs/${d.id}/split/dismiss`, undo ? {undo: true} : {}); await dsp_redraw(d.id); dc_load(); return {}; };
    try { await go(false)(); } catch { b.disabled = false; return; }
    const label = tr('Not a stack: {0}', d.name);
    histToast(label, histAdd({label, undo: go(true), redo: go(false)}));
  } else if (act === 'unlink') {
    const tid = d.task.id;
    const go = on => async () => { if (on) await api('POST', `/api/docs/${d.id}/task/link`, {task_id: tid}); else await api('DELETE', `/api/docs/${d.id}/task`); await dsp_redraw(d.id); return {}; };
    try { await go(false)(); } catch { b.disabled = false; return; }
    const label = tr('Task unlinked from {0}', d.name);
    histToast(label, histAdd({label, undo: go(true), redo: go(false)}));
  }
});

// ---- link with an existing task: the open tasks I may change, this workspace's (a private document: private lists only)
function dsp_pick(d) {
  const okList = l => !!l && (!l.org_id || (d.org_id && l.org_id === d.org_id));
  const md = /** @type {any} */ (modal(`<h3>${tr('Link with a task…')}</h3>
    <div class="shint keep">${esc(tr('“{0}” then shows in the task; who cannot see the document sees nothing of it.', d.name))}</div>
    <input id="dsp-q" placeholder="${esc(tr('Search open tasks'))}" autocomplete="off" aria-label="${esc(tr('Search open tasks'))}">
    <div class="dplist tpk" id="dsp-list" role="listbox" aria-label="${esc(tr('Open tasks'))}"></div>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button></div>`));
  md.classList.add('dpmodal', 'dsp-pick');
  const draw = () => {
    const q = norm(/** @type {any} */ ($('#dsp-q', md))?.value || '');
    const arr = openTasks().filter(x => x.id > 0 && okList(listById(x.list_id)) && (!q || norm(x.title).includes(q)))
      .sort((a, b) => (a.due || '9999').localeCompare(b.due || '9999') || bySort(a, b)).slice(0, 60);
    const row = x => `<button type="button" class="tpkrow" role="option" data-pick="${x.id}"><span class="tpkt">${esc(x.title)}</span><span class="tpkm">${esc(lname(listById(x.list_id)))}${x.due ? ' · ' + esc(dayLabel(x.due)) : ''}</span></button>`;
    const el = $('#dsp-list', md);
    if (el) el.innerHTML = arr.length ? arr.map(row).join('') : `<div class="muted mhint">${tr('No matching open task.')}</div>`;
  };
  draw();
  md.addEventListener('input', e => { if (/** @type {any} */ (e.target).id === 'dsp-q') draw(); });
  md.addEventListener('click', async e => {
    const b = /** @type {any} */ (e.target).closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (!b.dataset.pick) return;
    const tid = +b.dataset.pick;
    let j; try { j = await api('POST', `/api/docs/${d.id}/task/link`, {task_id: tid}); } catch (x) { const er = $('.aerr', md); if (er) er.textContent = x.message || ''; return; }
    md.remove();
    const prev = j.prev_task_id;
    const go = to => async () => { if (to) await api('POST', `/api/docs/${d.id}/task/link`, {task_id: to}); else await api('DELETE', `/api/docs/${d.id}/task`); await dsp_redraw(d.id); return {}; };
    await dsp_redraw(d.id);
    const label = tr('{0} linked with a task', d.name);
    histToast(label, histAdd({label, undo: go(prev), redo: go(tid)}));
  });
  setTimeout(() => { if (!isMobile()) /** @type {any} */ ($('#dsp-q', md))?.focus(); }, 50);
}

// ---- the preview of a stack
async function dsp_open(d) {
  let j; try { j = await api('GET', `/api/docs/${d.id}/split`); } catch { return; }
  Object.assign(DSP, {d, j, cuts: new Set(j.starts.filter(i => i > 0)), over: new Map(), blank: false, thumbs: {}});
  $('.dsp-md')?.remove();
  const md = /** @type {any} */ (modal(`<div class="lhdr"><h3>${tr('Split stack')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="muted">${esc(tr('A page with a new archive number starts a new document, pages without one belong to the one before. Tap between two pages to set or remove a cut, tap a page to leave it out.'))}</p>
    ${j.scan.some(p => p.blank) ? `<label class="chkl dsp-bl"><input type="checkbox" data-dspb="blank"> ${esc(tr('Remove blank pages ({0})', j.scan.filter(p => p.blank).length))}</label>` : ''}
    <ol class="dsp-grid" aria-label="${esc(tr('Pages'))}"></ol>
    <p class="dsp-sum" role="status" aria-live="polite"></p>
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="split">${ic('scissors', 's')} ${tr('Split')}</button></div>`));
  md.classList.add('dsp-md');
  dsp_draw(md);
  md.addEventListener('click', e => dsp_click(e, md));
  md.addEventListener('change', e => {
    const t = /** @type {any} */ (e.target);
    if (t.dataset?.dspb === 'blank') { DSP.blank = !!t.checked; DSP.j.scan.forEach((p, i) => { if (p.blank) DSP.over.delete(i); }); dsp_draw(md); }
  });
  dsp_thumbs(md, d.id, 1);
}
// a page is left out: a separator sheet, a blank page while the switch is on -- or what a tap on it said instead
const dsp_off = i => DSP.over.has(i) ? !!DSP.over.get(i) : DSP.j.drop.includes(i) || (DSP.blank && !!DSP.j.scan[i].blank);
// the parts as the server wants them: 1-based pages, a cut starts a new part, left-out pages are not in any
function dsp_parts() {
  const parts = []; let cur = [];
  DSP.j.scan.forEach((p, i) => {
    if (i > 0 && DSP.cuts.has(i) && cur.length) { parts.push(cur); cur = []; }
    if (!dsp_off(i)) cur.push(i + 1);
  });
  if (cur.length) parts.push(cur);
  return parts;
}
function dsp_draw(md) {
  const j = DSP.j, pre = j.prefix || 'ASN';
  let doc = 1;
  const grid = $('.dsp-grid', md); if (!grid) return;
  grid.innerHTML = j.scan.map((p, i) => {
    if (i > 0 && DSP.cuts.has(i)) doc++;
    const off = dsp_off(i), cut = i > 0 && DSP.cuts.has(i);
    const tag = p.sep ? tr('Separator sheet') : p.asn != null ? `${pre} ${p.asn}` : p.blank ? tr('blank') : '';
    const src = DSP.thumbs[i + 1];
    return `<li class="dsp-pg${off ? ' dsp-off' : ''}${cut ? ' dsp-new' : ''}">
      ${i > 0 ? `<button type="button" class="dsp-cut" data-dspc="${i}" aria-pressed="${cut}" aria-label="${esc(cut ? tr('Remove the cut before page {0}', i + 1) : tr('Cut before page {0}', i + 1))}" title="${esc(cut ? tr('Remove the cut') : tr('Cut here'))}">${ic('scissors', 's')}</button>` : ''}
      <button type="button" class="dsp-th" data-dspp="${i}" aria-pressed="${!off}" aria-label="${esc(tr('Page {0}', i + 1) + (off ? ' · ' + tr('left out') : ''))}">${src ? `<img src="${esc(src)}" alt="">` : `<span class="dc-ph">${ic('file')}</span>`}</button>
      <span class="dsp-cap">${cut || i === 0 ? `<b>${esc(tr('Document {0}', doc))}</b> · ` : ''}${esc(tr('Page {0}', i + 1))}${tag ? ` · <span class="dsp-tag">${esc(tag)}</span>` : ''}${off ? ` · <span class="muted">${tr('left out')}</span>` : ''}</span></li>`;
  }).join('');
  const n = dsp_parts().length, sum = $('.dsp-sum', md);
  if (sum) sum.textContent = trn('Makes {0} document', 'Makes {0} documents', n);
  const go = /** @type {any} */ ($('[data-m="split"]', md)); if (go) go.disabled = n < 2;
}
async function dsp_thumbs(md, id, from) {
  if (!md.isConnected || from > DSP.j.pages) return;
  let j; try { j = await api('GET', `/api/docs/${id}/split/thumbs?from=${from}`); } catch { return; }
  for (const t of j.thumbs || []) if (t.src) DSP.thumbs[t.page] = t.src;
  if (!md.isConnected || DSP.d?.id !== id) return;
  dsp_draw(md);
  if ((j.thumbs || []).length) dsp_thumbs(md, id, from + j.thumbs.length);
}
async function dsp_click(e, md) {
  const b = /** @type {any} */ (e.target).closest('button'); if (!b) return;
  if (b.dataset.m === 'close') { md.remove(); return; }
  if (b.dataset.dspc) { const i = +b.dataset.dspc; if (DSP.cuts.has(i)) DSP.cuts.delete(i); else DSP.cuts.add(i); dsp_draw(md); return; }
  if (b.dataset.dspp) {
    const i = +b.dataset.dspp;
    DSP.over.set(i, !dsp_off(i)); dsp_draw(md); return;
  }
  if (b.dataset.m !== 'split') return;
  const parts = dsp_parts(), d = DSP.d;
  if (parts.length < 2) return;
  b.disabled = true;
  const split = async () => { const r = await api('POST', `/api/docs/${d.id}/split`, {parts}); return r; };
  let r; try { r = await split(); } catch (x) { b.disabled = false; const er = $('.aerr', md); if (er) er.textContent = x.message || ''; return; }
  md.remove();
  $('.dc-md')?.remove();
  dc_load();
  const label = trn('{1} split into {0} document', '{1} split into {0} documents', r.ids.length, d.name);
  histToast(label, histAdd({label, undo: async () => { await api('POST', `/api/docs/${d.id}/unsplit`); dc_load(); return {}; },
    redo: async () => { await split(); dc_load(); return {}; }}));
}
