// @ts-check
/* Kalmido web client: the document view (2.583.0, #4835, includes #4829 and #4832). A click on a document's card (the
   documents, the file store's cards) leaves the cards and opens the document as a page of its own with its own address
   #docs/<id> (reload, the browser's Back and a link open it again). The head: back to the list (Esc, the same place of the
   list), the title, "3 of 128" with two arrow buttons and the arrow keys left / right through the list as shown (filters,
   sort: docs.js dc_navHtml / dc_step, the next page loads at its end, a document that left the list leafs on from where it
   stood, #4476), right: Download / Actions / Delete. Below three columns: a narrow strip of the neighbouring documents (can
   be folded away, a click jumps), the fields in tabs (Details / Content / History / Shares; the rare fields under "More
   fields"; no Save button - every change saves at once with an undo, docs.js dc_patch), and the large preview: every page
   of a PDF one below the other, drawn sharp at the size shown (again after a zoom or a new width, a page only when it comes
   near, a limit per page's canvas), the page counter, zoom, Width, Whole page, Full screen; an image in its original. Grips
   between the columns set their widths (kept per device, a double click / Home = the standard). Phones: one column, the
   preview on top, the fields below, a swipe sideways on the preview leafs (docs.js dc_touchEnd), two fingers zoom.
   Replaces the pane beside the list (2.430.0, #3582), the phone's sheet and the reading view (2.521.0, #4476: its preview
   of every page, its grips and its full screen live on here). The file is part of the module docs (lazyload.js), docs.js
   asks it through typeof checks. Classic script sharing the global scope with the others. */
'use strict';

const DVW = {back: null, tab: 'details', pdf: null, ro: null, drag: null, he: null, node: null, more: false, notext: null};  // notext: 2.742.0 (#4861)
// the tabs of the fields; History and Shares come from the file store's node (GET /api/files/nodes/<id>, its rights)
const DCV_TABS = [['details', N_('Details')], ['text', N_('Content')], ['hist', N_('History')], ['share', N_('Shares')]];
const DCV_ZMIN = 0.1, DCV_ZMAX = 8, DCV_CVMAX = 12e6;  // the zoom's limits; the most pixels one page's canvas gets
// the grips: their device key, the CSS variable on .dv-view, the smallest width (rem). 2.583.0 (#4829): every grip
// goes up to the edge; the neighbours keep only their small rest (DCV_KEEP rem of the preview, the other column its smallest)
const DCV_GRIPS = {strip: {k: 'dv.stripW', v: '--dv-sw', min: 4}, mask: {k: 'dv.maskW', v: '--dv-mw', min: 12}};
const DCV_KEEP = 6;
const dcv_rem = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
const dcv_stripOff = () => !!LS.get('dv.stripOff', false);
function dcv_zoom() { const z = LS.get('dv.zoom', 'width'); return z === 'page' || z === 'width' || +z > 0 ? z : 'width'; }
const dcv_in = el => !!el?.closest?.('input, textarea, select, [contenteditable="true"], [contenteditable=""]');

// ---- the frame (viewDocs draws it for #docs/<id>; its content is drawn here and kept through redraws: data-fl-fill)
function dcv_colStyle() {
  // 2.547.0 (#4492, from the reading view): while a grip is dragged, a redraw (a live update, the preview loaded) keeps the dragged width
  const st = Object.entries(DCV_GRIPS).map(([w, g]) => { const px = DVW.drag?.which === w && DVW.drag.px != null ? DVW.drag.px : +LS.get(g.k, 0); return px > 0 ? `${g.v}:${Math.round(px)}px` : ''; }).filter(Boolean).join(';');
  return st ? ` style="${st}"` : '';
}
function dcv_html(id) {
  setTimeout(() => dcv_fill(id), 0);
  return `<div class="dv-view dc-md" data-k="dv" data-fl-fill role="region" aria-labelledby="dc-h"${dcv_colStyle()}></div>`;
}
// its remove() leaves the view (the callers of the old sheet -- Close, Delete, a split, a move -- call md.remove())
function dcv_hook(v) { if (v && !v._dv) { v._dv = true; v.remove = () => dcv_close(v); } }
function dcv_fill(id) {
  const v = $('.dv-view'); if (!v || dc_hashId() !== id) return;
  dcv_hook(v);
  if (DC.doc?.id === id) { if (!v.firstChild) dc_mdDraw(v); return; }
  if (DC.opening !== id) dc_open(id);
}
// from the list / the file store / a link inside the app: a new entry in the browser's history, the place of the list kept
function dcv_go(id) {
  const v = $('#view'), inList = S.route.mod === 'docs' && !dc_hashId();
  DVW.back = {hash: location.hash || '#docs', y: inList && v ? v.scrollTop : null, id, pushed: true};
  location.hash = `#docs/${id}`;
}
function dcv_close(v) {
  v = v || $('.dv-view');
  if (v?.isConnected) Element.prototype.remove.call(v);
  if (S.route.mod !== 'docs' || !dc_hashId()) return;  // the route left already (a redraw took it away)
  const b = DVW.back;
  dcv_left();
  if (b?.pushed && history.length > 1) history.back();
  else location.hash = b?.hash && !/^#docs\/\d/.test(b.hash) ? b.hash : DC.f.review ? '#docs/review' : '#docs';
}
// the view was left (Esc, Back, another area): free the PDF, the list comes back at the same place with its card in view
function dcv_left() {
  const id = DC.doc?.id ?? DC.opening ?? DVW.back?.id;
  if (DC.doc) DC.lastId = DC.doc.id;
  DC.doc = null; DC.opening = null; DC.actsMore = null; DC.navSrc = null; dcv_free();
  if (typeof dc_nbStop === 'function') dc_nbStop();  // 2.736.0 (#5212): the neighbours drawn ahead go along
  DVW.back = {...(DVW.back || {}), id, pushed: false, restore: true};
}
// another area (a link of a field, the sidebar): the view's document and its PDF go along
window.addEventListener('hashchange', () => { if (!/^#docs\/\d/.test(location.hash) && (DC.doc || DVW.pdf)) dcv_left(); });
function dcv_restore() {
  const b = DVW.back; if (!b?.restore || !$('.dc-view')) return;
  b.restore = false;
  requestAnimationFrame(() => {
    const v = $('#view'); if (b.y != null && v) v.scrollTop = b.y;
    const c = b.id && $(`.dc-view [data-dco="${b.id}"]`);
    if (c) { c.scrollIntoView?.({block: 'nearest'}); c.focus({preventScroll: true}); }
  });
}

// ---- drawing the document (docs.js dc_mdDraw)
function dcv_draw(md) {
  const d = DC.doc; if (!d || !md) return;
  dcv_hook(md);
  const w = d.role !== 'view';
  let body = $('.dc-body', md);
  if (body && body.dataset.id !== String(d.id)) {
    DVW.he = null; DVW.node = null; const s = $('.dv-saved', md); if (s) s.textContent = '';
    if (typeof dc_nbLand === 'function') dc_nbLand(body);  // 2.727.0 (#5202): the swiped body back in place
    body = dcv_nbTake(d, body) || body;  // 2.736.0 (#5212): the neighbour drawn ahead takes its place as it stands
  }
  const tabs = dcv_tabs(d);
  if (!tabs.some(([t]) => t === DVW.tab)) DVW.tab = 'details';
  // the body is keyed by the document: another one is drawn anew (its preview, its fields), the same one morphed (a field
  // keeps its focus while the one before saves); the head stays (the focus on the arrow buttons while leafing)
  fl_set(md, `${dcv_headHtml(d, w)}
    ${dcv_bodyHtml(d, null)}`);
  body = $('.dc-body', md); if (body) body._dcv = {d, set: DC.set};  // 2.736.0 (#5212): what it shows (it may become a neighbour)
  if (DVW.tab === 'hist' || DVW.tab === 'share') dcv_tabLoad(md, d);
  dcv_pvDraw(md, d);
  if (typeof dfl_runs === 'function' && !d.file) dfl_runs(md, d);  // 2.581.0 (#4803): the runs of flows with Undo (docflows.js)
  if (typeof dn_draw === 'function' && !d.file) dn_draw(md, d);  // 2.635.0 (#4807 d): the notes (docnotes.js), under the fields
  const cur = $('.dv-strip .dv-th.on', md); if (cur) cur.scrollIntoView?.({block: 'nearest'});
  if (DC.slide) dc_slideIn(md);  // 2.476.0 (#3935): the next document glides in from the side (2.727.0, #5202: only the arrows / keys; a swipe snapped it in)
  if (typeof dc_nbPre === 'function') dc_nbPre(d);  // 2.727.0 (#5202): the neighbours' small pictures ahead (2.736.0, #5212: and the neighbours drawn whole)
}
// 2.583.0 (#4832): a plain file has no recognised text
const dcv_tabs = d => DCV_TABS.filter(([t]) => t === 'details' || (t === 'text' && !d.file) || (t === 'hist' && d.role !== 'view') || (t === 'share' && d.role === 'owner'));
// the body: the strip, the fields in tabs, the preview. 2.736.0 (#5212): nb = a neighbour drawn ahead ({d, set}) by the same lines
function dcv_bodyHtml(d, nb) {
  const w = d.role !== 'view', tabs = dcv_tabs(d), off = dcv_stripOff();
  const tab = tabs.some(([t]) => t === DVW.tab) ? DVW.tab : 'details';
  return `<div class="dc-body dv-cols${off ? ' dv-nostrip' : ''}" data-k="b${d.id}" data-id="${d.id}">${dcv_stripHtml(d, off)}${off ? '' : dcv_gripHtml('strip', tr('In the list'))}
      <section class="dv-mask dc-props" id="dc-props" aria-label="${esc(tr('Properties'))}">
        <div class="dv-tabs" role="tablist" aria-label="${esc(tr('Properties'))}">${tabs.map(([t, l]) => `<button type="button" role="tab" id="dv-t-${t}" data-dvtab="${t}" aria-controls="dv-p-${t}" aria-selected="${tab === t}" tabindex="${tab === t ? 0 : -1}">${tr(l)}</button>`).join('')}</div>
        ${tabs.map(([t]) => `<div class="dv-tp" role="tabpanel" id="dv-p-${t}" aria-labelledby="dv-t-${t}"${tab === t ? '' : ' hidden'}${t === 'hist' || t === 'share' ? ' data-fl-fill' : ''}>${t === 'details' ? dcv_detailsHtml(d, w, nb) : t === 'text' ? dcv_textHtml(d, w) : ''}</div>`).join('')}
      </section>${dcv_gripHtml('mask', tr('Properties'))}
      ${dcv_pvHtml(d)}
    </div>`;
}
// ---- 2.736.0 (#5212): leafing without a seam. The direct neighbours of the open document are fetched whole (docs.js
// dc_nbAhead) and drawn here by the same lines as the open one (dcv_bodyHtml, the preview by dcv_pvDraw at the width it
// will have) into a body of their own. It waits outside the page in a holder of the open body's size (laid out, so the
// pages get their final size; no ids while it waits: the page's own fields stay the only ones), a swipe lays it beside the
// open body (docs.js dc_nbAdd) and after the snap it takes the open body's place as it is (dcv_nbTake): no request, no
// picture that moves, no text that comes later. The body left behind waits as the neighbour on the other side.
function dcv_nbHold() {
  let h = $('.dv-nbhold');
  if (!h) { h = document.createElement('div'); h.className = 'dv-nbhold'; h.setAttribute('aria-hidden', 'true'); h.inert = true; document.body.appendChild(h); }
  const md = $('.dv-view'), b = md && $('.dc-body', md);
  if (b?.offsetWidth) h.style.cssText = `${md.getAttribute('style') || ''};width:${b.offsetWidth}px;height:${b.offsetHeight}px`;  // the grips' widths (--dv-sw / --dv-mw) too
  return h;
}
// a body made a waiting neighbour: its ids kept aside (data-dvid), out of reach (inert, aria-hidden), into the holder
function dcv_nbPark(el) {
  for (const x of el.querySelectorAll('[id]')) { /** @type {HTMLElement} */ (x).dataset.dvid = x.id; x.removeAttribute('id'); }
  el.classList.remove('dc-body', 'dc-nb-n', 'dc-nb-p'); el.classList.add('dc-nb');
  el.setAttribute('aria-hidden', 'true'); el.inert = true; el.style.transform = ''; el.style.transition = ''; el.style.position = '';
  /** @type {any} */ (el)._dcnb = true;
  dcv_nbHold().appendChild(el);
}
// e = {id, d, set, ctrl}: its body drawn (the preview fetches its file with e.ctrl's signal)
function dcv_nbDraw(e) {
  const t = document.createElement('template'); t.innerHTML = dcv_bodyHtml(e.d, e).trim();
  const el = /** @type {HTMLElement} */ (t.content.firstElementChild); if (!el) return;
  e.el = el;
  dcv_nbHold().appendChild(el);
  if (typeof dn_draw === 'function' && !e.d.file) dn_draw(/** @type {any} */ (el), e.d);  // the notes (docnotes.js) as on the open one
  dcv_nbPark(el);
  dcv_pvDraw(el, e.d, e);
  const box = el.querySelector('.dv-pages'); if (box) DVW.ro?.observe(box);
}
// the neighbour gone (no direct neighbour any more, the view closed): its file freed, its body away
function dcv_nbFree(e) {
  e.ctrl?.abort();
  if (e.pdf) { e.pdf.off = true; e.pdf.io?.disconnect(); try { e.pdf.doc?.destroy(); } catch { /* gone */ } }
  const box = e.el && $('.dv-pages', e.el); if (box) DVW.ro?.unobserve(box);
  e.el?.remove(); e.el = null;
}
// the document now drawn was drawn ahead (dc_open took its data): its body takes the open one's place; the open one waits
// as a neighbour (the way back), unless a change of it is still on its way
function dcv_nbTake(d, old) {
  const e = DCW.nb?.get(d.id); if (!e?.el || e.d !== d || !e.el.firstChild) return null;
  DCW.nb.delete(d.id); e.taken = true;  // a preview still on its way becomes the view's (dcv_pvDraw)
  const el = e.el;
  for (const x of el.querySelectorAll('[data-dvid]')) { const y = /** @type {HTMLElement} */ (x); y.id = y.dataset.dvid || ''; delete y.dataset.dvid; }
  el.classList.remove('dc-nb', 'dc-nb-n', 'dc-nb-p'); el.classList.add('dc-body');
  el.removeAttribute('aria-hidden'); el.inert = false; /** @type {any} */ (el)._dcnb = false;
  const was = /** @type {any} */ (old)._dcv, pdf = DVW.pdf?.box && old.contains(DVW.pdf.box) ? DVW.pdf : null;
  old.replaceWith(el);
  DVW.pdf = e.pdf || null;
  if (e.pdf) e.pdf.nb = false;
  if (was?.d && was.d.id !== d.id && !DC_PEND.has(was.d.id) && $('.dv-pages', old)?._base) {  // its preview finished
    const o = {id: was.d.id, d: was.d, set: was.set, at: Date.now(), ctrl: new AbortController(), el: old, pdf};
    if (pdf) pdf.nb = true;
    const pz = $('.dv-pages', old); if (pz && typeof dc_zoomSet === 'function') dc_zoomSet(pz, 1, 0, 0);
    dcv_nbPark(old);
    DCW.nb.set(o.id, o);
  } else if (pdf) { DVW.pdf = pdf; dcv_free(); DVW.pdf = e.pdf || null; }
  return el;
}
function dcv_headHtml(d, w) {
  const fromAb = /^#ablage/.test(DVW.back?.hash || '');
  return `<header class="dv-head"><button type="button" class="btn dv-back" data-dc="close" aria-keyshortcuts="Escape" title="${esc(tr('Back to the list (Esc)'))}">${ic('back', 's')} <span>${esc(fromAb ? tr('File store') : tr('Documents'))}</span></button>
    <h2 id="dc-h" class="dv-title" title="${esc(d.name)}">${esc(d.name)}</h2><span class="dv-navslot">${dc_navHtml(d)}</span>
    <span class="dv-keys muted" aria-hidden="true">${esc(tr('Arrow keys ← → leaf through, Esc back'))}</span><span class="spacer"></span>
    <span class="dv-saved" role="status" data-fl-fill></span><span class="dv-hacts">${dcv_actsHtml(d, w)}</span></header>`;
}
// 2.497.0 A (#4046) moved to the head: Download, the rarer actions behind "Actions", Delete apart as the last
function dcv_actsHtml(d, w) {
  const more = [d.einvoice ? `<a class="btn sm dc-einv" href="/api/docs/${d.id}/einvoice" target="_blank" rel="noopener">${ic('receipt', 's')} ${tr('Readable view')}</a>` : '',  // 2.146.0 A (#2451)
    typeof dsp_actBtn === 'function' && !d.file ? dsp_actBtn(d, w) : '',  // 2.154.0 A (#1111): split a stack
    d.parent_id ? `<a class="btn sm" href="#ablage/${d.parent_id}">${ic('folder', 's')} ${tr('Show in the file store')}</a>` : '',
    d.role === 'owner' && typeof ab_share === 'function' ? `<button type="button" class="btn sm" data-dc="share">${ic('users', 's')} ${tr('Share…')}</button>` : '',
    d.role === 'owner' && typeof xl_newDlg === 'function' ? `<button type="button" class="btn sm" data-dc="xlink">${ic('link', 's')} ${tr('Link for external people…')}</button>` : '',  // 2.210 C (#2761)
    w && !d.file && smv_can(d.org_id) ? `<button type="button" class="btn sm" data-dc="space">${ic('building', 's')} ${tr('Move to another workspace…')}</button>` : ''].filter(Boolean);
  const open = DC.actsMore === d.id;
  return `<a class="btn sm dv-dl" href="${dc_fileUrl(d, true)}" download title="${esc(tr('Download'))}">${ic('download', 's')} <span>${tr('Download')}</span></a>${more.length ? `<span class="dv-actw"><button type="button" class="btn sm" data-dc="actsmore" aria-expanded="${open}" aria-controls="dc-amore" aria-haspopup="true">${tr('Actions')}${ic('chev', 's dc-chev')}</button><div class="dc-ag dc-amore dv-amenu" id="dc-amore" ${open ? '' : 'hidden'}>${more.join('')}</div></span>` : ''}${w ? `<button type="button" class="btn sm danger dc-adel" data-dc="del" aria-label="${esc(tr('Delete'))}" title="${esc(tr('Delete'))}">${ic('trash', 's')} <span>${tr('Delete')}</span></button>` : ''}`;
}
const dcv_gripHtml = (which, label) => `<button type="button" class="dv-grip" data-dvgrip="${which}" aria-label="${esc(label + ': ' + tr('Resize (arrow keys; double-click: default size)'))}" title="${esc(tr('Drag to resize · double-click: default size'))}"></button>`;
// the strip: the neighbours in the list as shown (up to 15 on each side), the open one marked; a document outside the list alone
function dcv_stripHtml(d, off) {
  const ds = DC.docs || [], i = DC.navSrc ? -1 : dc_navIdx(d), list = i < 0 ? [d] : ds.slice(Math.max(0, i - 15), i + 16);  // 2.683.0 (#5150): a file store folder's list has ids only
  const t = off ? tr('Show the list') : tr('Hide the list');
  return `<nav class="dv-strip" aria-label="${esc(tr('In the list'))}"><div class="dv-sthd"><span class="dv-stt">${tr('In the list')}</span><button type="button" class="iconbtn" data-dc="dvstrip" aria-expanded="${!off}" aria-label="${esc(t)}" title="${esc(t)}">${ic(off ? 'panelshow' : 'panelhide', 's')}</button></div>${off ? '' : `<ul>${list.map(x => {
    const on = x.id === d.id, nm = x.sender?.name || x.name;
    return `<li data-k="s${x.id}"><button type="button" class="dv-th${on ? ' on' : ''}" data-dvgo="${x.id}"${on ? ' aria-current="true"' : ''} aria-label="${esc(nm)}" title="${esc(x.name)}"><span class="dv-thi">${x.thumb ? `<img src="${esc(dc_thumbUrl(x))}" alt="" loading="lazy">` : `<span class="dc-ph">${ic(dc_isPdf(x) ? 'file' : 'picture', 's')}</span>`}</span><span class="dv-tn">${esc(nm)}</span></button></li>`;
  }).join('')}</ul>`}</nav>`;
}
// Details: what is used often first; due date, archive number, amount, custom fields and the capture date under "More fields"
function dcv_detailsHtml(d, w, nb) {  // 2.736.0 (#5212): nb = a neighbour drawn ahead (its workspace's lists: nb.set)
  if (d.file) return dcv_fileHtml(d, w);  // 2.583.0 (#4832)
  const set = (nb ? nb.set : DC.set) || {senders: [], types: [], tags: [], folders: []}, ro = w ? '' : 'disabled';
  const dl = (id, list) => `<datalist id="${id}">${list.map(x => `<option value="${esc(x.name)}">`).join('')}</datalist>`;
  const field = (f, label, input) => `<div class="row dc-f"><label for="dc-${f}">${label}</label>${input}${dc_auto(d, f)}</div>`;
  const sug = Object.entries(d.suggest || {});
  // 2.554.0 A (#4469): a compact line: the text left, the buttons right; with a stack the stack question is part of the box
  const stackQ = w && d.split?.stack && typeof dsp_stackBtns === 'function';
  const sugHtml = d.review ? `<div class="dc-rev${stackQ ? ' dsp-hint' : ''}" role="group" aria-label="${esc(tr('To review'))}">
    <span class="dc-revt"><b>${tr('To review')}</b> ${stackQ ? `<span class="dc-ht">${ic('scissors', 's')} <span>${esc(tr('Stack - split? Several archive numbers were found on its pages.'))}</span></span>` : sug.length ? '' : `<span class="muted">${tr('Check sender and type, then mark the document as checked.')}</span>`}</span>
    ${sug.map(([f, s]) => `<div class="dc-sug"><span>${esc(tr(DC_FEATS.find(x => x[0] === f)?.[1] || f))}: <b>${esc(s.label)}</b>${s.by === 'agent' ? ` <span class="muted">(${tr('from the agent')})</span>` : ''}</span>${w ? `<button type="button" class="btn sm" data-dc="take:${esc(f)}">${tr('Accept|suggestion')}</button>` : ''}</div>`).join('')}
    ${w ? `<div class="dc-revact">${sug.length > 1 ? `<button type="button" class="btn sm" data-dc="takeall">${tr('Accept all')}</button>` : ''}${stackQ ? dsp_stackBtns() : `<button type="button" class="btn sm pri" data-dc="checked">${ic('check', 's')} ${tr('Checked')}</button>`}</div>` : ''}</div>` : '';
  // 2.154.0 A (#1111): docsplit.js draws the due date / task line (+ link with an existing task)
  const task = typeof dsp_sheetHtml === 'function' && (d.task !== undefined || !d.task_id) ? dsp_sheetHtml(d, w) : d.due && !d.task_id && w ? `<div class="dc-due"><span class="dc-ht">${ic('alarm', 's')} <span>${esc(tr('Due on {0}', dc_day(d.due)))}</span></span><button type="button" class="btn sm" data-dc="task">${tr('Create task')}</button></div>`
    : d.task_id ? `<div class="dc-due muted">${ic('done', 's')} <a href="#t/${d.task_id}">${tr('Task created')}</a></div>` : '';
  const busy = d.state !== 'done' ? `<p class="dc-state ${esc(d.state)}" role="status">${esc(tr(DC_STATE[d.state] || d.state))}${d.state === 'failed' && d.error_text ? `: ${esc(d.error_text)}` : ''}</p>` : '';
  const main = [field('name', tr('Title'), `<input id="dc-name" data-dcp="name" value="${esc(d.name)}" maxlength="150" ${ro}>`),
    field('date', tr('Date'), dateIn('dc-date', d.date || '', {label: tr('Date'), ro: !!ro, attrs: 'data-dcp="date"'})),
    field('sender', tr('Sender'), `<input id="dc-sender" data-dcp="sender" value="${esc(d.sender?.name || '')}" list="dc-sl" autocomplete="off" maxlength="120" ${ro}>${dl('dc-sl', set.senders)}`),
    field('type', tr('Document type'), `<input id="dc-type" data-dcp="type" value="${esc(d.type?.name || '')}" list="dc-tl" autocomplete="off" maxlength="120" placeholder="${esc(tr('e.g. Invoice, Contract, Letter'))}" ${ro}>${dl('dc-tl', set.types)}`),
    field('folder', tr('Folder'), `<select id="dc-folder" data-dcp="folder" ${ro}><option value="">${tr('Documents (no subfolder)')}</option>${(set.folders || []).map(f => `<option value="${f.id}" ${d.folder?.id === f.id ? 'selected' : ''}>${esc(tr('Documents') + ' / ' + (f.path || f.name))}</option>`).join('')}${w ? `<option value="new">${tr('New folder…')}</option>${d.folder?.id ? `<option value="newsub">${esc(tr('New subfolder in {0}…', d.folder.name))}</option>` : ''}` : ''}</select>`),
    field('tags', tr('Tags'), typeof tf_html === 'function' ? tf_html({id: 'dc-tags', vals: d.tags.map(t => t.name), all: set.tags, ro: !!ro, attrs: 'data-dcp="tags"', ph: tr('Add a tag…')})  // 2.742.0 (#4862): the tag field (tagsel.js)
      : `<input id="dc-tags" data-dcp="tags" value="${esc(d.tags.map(t => t.name).join(', '))}" list="dc-gl" autocomplete="off" placeholder="${esc(tr('comma-separated'))}" ${ro}>${dl('dc-gl', set.tags)}`)].join('');
  const rare = [field('due', tr('Due'), dateIn('dc-due', d.due || '', {label: tr('Due'), ro: !!ro, attrs: 'data-dcp="due"'})),
    field('amount', tr('Amount'), `<span class="dc-amt"><input id="dc-amount" data-dcp="amount" inputmode="decimal" value="${esc(d.amount ? numField(d.amount, 6, 2) : '')}" ${ro}><input id="dc-currency" data-dcp="currency" value="${esc(d.currency || '')}" maxlength="3" aria-label="${esc(tr('Currency'))}" placeholder="EUR" ${ro}></span>`),
    field('asn', tr('Archive number'), `<span class="dc-amt"><input type="number" min="1" id="dc-asn" data-dcp="asn" value="${esc(d.asn || '')}" ${ro}>${w && !d.asn ? `<button type="button" class="btn sm" data-dc="asnnext">${tr('Next free number')}</button>` : ''}</span>${typeof dc_asnTakenHtml === 'function' ? dc_asnTakenHtml(d) : '' /* 2.591.0 B (#4863) */}`),
    ...(d.custom_fields || []).map(f => dc_cfRow(d, f, ro)), typeof pmeta_takenHtml === 'function' ? pmeta_takenHtml(d) : ''].join('');
  const n = [d.due, d.amount, d.asn].filter(Boolean).length + (d.custom_fields || []).filter(f => f.value != null && f.value !== '').length;
  return `${busy}${sugHtml}${task}${typeof rx_html === 'function' ? rx_html(d) : ''}${typeof rc_slot === 'function' ? (nb ? `${rc_alsoHtml(d)}<div class="rc-slot"></div><p class="rc-cb muted" hidden></p>` : rc_slot(d)) : ''}${typeof ltd_slot === 'function' ? (nb ? `<div class="ltd" data-nid="${d.id}"></div>` : ltd_slot(d)) : '' /* 2.736.0 (#5212): a neighbour drawn ahead: their frames only (they keep one document's state each) */}${typeof ast_docSlot === 'function' ? ast_docSlot(d) : '' /* 2.126.1 A (#2123) */}
    <div class="dc-form">${main}</div>
    <details class="dv-more"${DVW.more ? ' open' : ''}><summary>${ic('chev', 's dc-chev')}<span>${tr('More fields')}</span>${n ? `<span class="muted dv-cnt">${esc(tr('{0} filled in', n))}</span>` : ''}</summary><div class="dc-form">${rare}</div></details>
    <div class="dc-notes" data-fl-fill></div>${w ? `<p class="muted dv-hint">${tr('Every change saves at once, with undo.')}</p>` : ''}`;
}
// 2.583.0 (#4832): a plain file of the file store: what it is, its fields come with the recognition
function dcv_fileHtml(d, w) {
  const facts = [fmtSize(d.size || 0), d.updated_at ? tr('Changed {0}', fmtDay('short', new Date(d.updated_at))) : '', d.owner ? tr('Owner: {0}', d.owner) : ''].filter(Boolean);
  return `<div class="abfacts">${facts.map(x => `<span>${esc(x)}</span>`).join('')}</div>
    <p class="muted dv-hint">${esc(tr('A file of the file store. Recognised, it gets the fields of a document (sender, type, date).'))}</p>
    ${w ? `<div class="row"><button type="button" class="btn sm" data-dc="dvrecog">${ic('sparkle', 's')} ${tr('Recognise')}</button></div>` : ''}`;
}
// Content: the state of the recognition and the recognised text
function dcv_textHtml(d, w) {
  return `<p class="dc-state ${esc(d.state)}" role="status">${esc(tr(DC_STATE[d.state] || d.state))}${d.state === 'failed' && d.error_text ? `: ${esc(d.error_text)}` : ''}${d.method === 'ocr' ? ` · ${tr('text recognition')}` : d.method === 'e-invoice' ? ` · ${tr('E-invoice')}` : ''}${d.state === 'done' && d.method === 'none' ? `<span class="dc-notext muted" role="note"> · ${tr('No text can be read from this kind of file (older Office formats, PowerPoint, RTF): it stays a file without text. Download it to open it.')}</span>` : '' /* 2.635.0 (#4807) */}
      ${w && (d.state === 'done' || d.state === 'failed') ? `<button type="button" class="linkbtn" data-dc="redo">${tr('Recognise again')}</button>` : ''}</p>
    <div class="dc-text"><h4>${tr('Recognised text')}</h4>${d.text ? `<pre>${esc(d.text)}</pre>` : `<p class="muted">${tr('No text recognised.')}</p>`}</div><div class="dc-flows" data-fl-fill></div>`;  // 2.581.0 (#4803): the runs of flows (docflows.js dfl_runs)
}
// History and Shares: the file store's node of the document (versions, shares, the history), fetched when the tab is opened
async function dcv_tabLoad(md, d) {
  const p = $(`#dv-p-${DVW.tab}`, md); if (!p) return;
  if (DVW.node?.id === d.id && DVW.node.n) { dcv_tabFill(p, DVW.node.n, DVW.tab); return; }
  if (DVW.node?.id === d.id) return;  // on its way
  if (!p.firstChild) p.innerHTML = `<p class="muted">${tr('Loading…')}</p>`;
  DVW.node = {id: d.id, n: null};
  let n; try { n = await api('GET', `/api/files/nodes/${d.id}`); } catch { DVW.node = null; p.innerHTML = ''; return; }
  if (DVW.node?.id !== d.id) return;
  DVW.node.n = n;
  for (const t of ['hist', 'share']) { const q = $(`.dv-view #dv-p-${t}`); if (q) dcv_tabFill(q, n, t); }
}
function dcv_tabFill(p, n, t) {
  const when = iso => `${fmtDay('short', new Date(iso))} ${fmtTimeAt(new Date(iso))}`;
  if (t === 'hist') {
    const vers = (n.versions || []).map(v => `<div class="abvrow"><span><b>v${v.no}</b> · ${esc(when(v.created_at))} · ${fmtSize(v.size)}${v.by ? ' · ' + esc(v.by) : ''}</span></div>`).join('');
    const log = (n.log || []).map(x => `<div class="ablrow ${x.agent ? 'abag' : ''}">${x.agent ? ic('bot', 's') : ic('user', 's')}<span><b>${esc(x.name || (typeof xl_logWho === 'function' && xl_logWho(x)) || '?')}</b> ${esc(tr((typeof AB_ACT === 'object' && AB_ACT[x.action]) || x.action))}</span><span class="spacer"></span><small class="muted">${esc(when(x.at))}</small></div>`).join('');
    p.innerHTML = `${vers ? `<h4>${tr('Versions')}</h4><div class="abvers">${vers}</div>` : ''}<h4>${tr('History')}</h4><div class="ablog">${log || `<span class="muted">${tr('Nothing yet')}</span>`}</div>`;
    return;
  }
  const shares = [...(n.shares || []), ...(n.inherited || [])], role = r => typeof ab_role === 'function' ? ab_role(r) : r;
  p.innerHTML = `<div class="abshsum">${shares.length || n.org_access || n.org_access_from ? shares.map(s => `<span class="abshp">${s.agent_id ? ic('bot', 's') : s.group_id ? ic('users', 's') : ic('user', 's')}${esc(s.name)} · ${esc(role(s.role))}${s.from ? ` <small class="muted">${esc(tr('from “{0}”', s.from))}</small>` : ''}</span>`).join('') + (n.org_access || n.org_access_from ? `<span class="abshp">${ic('building', 's')}${esc(tr('Whole organisation'))}</span>` : '') : `<span class="muted">${tr('Only you')}</span>`}</div>
    <div class="row">${typeof ab_share === 'function' ? `<button type="button" class="btn sm" data-dc="share">${ic('users', 's')} ${tr('Share…')}</button>` : ''}${typeof xl_newDlg === 'function' ? `<button type="button" class="btn sm" data-dc="xlink">${ic('link', 's')} ${tr('Link for external people…')}</button>` : ''}</div>`;
}
function dcv_tab(md, t, focus) {
  if (!$(`#dv-p-${t}`, md)) return;
  DVW.tab = t;
  for (const b of $$('[data-dvtab]', md)) { const on = b.dataset.dvtab === t; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus(); }
  for (const p of $$('.dv-tp', md)) p.hidden = p.id !== `dv-p-${t}`;
  if ((t === 'hist' || t === 'share') && DC.doc) dcv_tabLoad(md, DC.doc);
}
// "Saved (Undo)" in the head after a change (docs.js dc_patch); the same step as the toast's undo
function dcv_saved(he) {
  const s = $('.dv-view .dv-saved'); if (!s) return;
  DVW.he = he;
  s.innerHTML = `${ic('check', 's')} <span>${tr('Saved')}</span> <button type="button" class="linkbtn" data-dc="dvundo">${tr('Undo')}</button>`;
}
async function dcv_undo() {
  const he = DVW.he; DVW.he = null;
  const s = $('.dv-view .dv-saved'); if (s) s.textContent = '';
  if (!he) return;
  await histIdle();
  if (HIST.undo[HIST.undo.length - 1] === he) histStep('undo');
}
// the list changed (loaded again, the next page, a field saved): the counter and the strip follow (docs.js dc_navSync)
function dcv_sync() {
  const v = $('.dv-view'), d = DC.doc; if (!v || !d || $('.dc-body', v)?.dataset.id !== String(d.id)) return;
  const slot = $('.dv-navslot', v), h = dc_navHtml(d), sig = (h.match(/data-sig="([^"]*)"/) || [])[1], old = $('.dc-nav', slot);
  if (slot && !(old?.dataset.sig === sig || (!old && !h))) {
    const f = old && old.contains(document.activeElement) ? document.activeElement.dataset.dc : null;
    slot.innerHTML = h;
    if (f) $(`.dc-nav [data-dc="${f}"]`, slot)?.focus({preventScroll: true});
  }
  const st = $('.dv-strip', v); if (st) { const t = document.createElement('template'); t.innerHTML = dcv_stripHtml(d, dcv_stripOff()); const n = t.content.firstElementChild; if (n && st.innerHTML !== n.innerHTML) st.replaceWith(n); }
}

// ---- the preview: an image as itself, a PDF with every page (drawn when it comes near, sharp at the size shown)
function dcv_pvHtml(d) {
  return `<section class="dv-pv" aria-label="${esc(tr('Preview'))}"><div class="dv-pvbar" role="group" aria-label="${esc(tr('Zoom'))}"><span class="dv-pgn" data-fl-fill></span><span class="spacer"></span>
    <button type="button" class="iconbtn" data-dc="dvz:out" aria-label="${esc(tr('Zoom out'))}" title="${esc(tr('Zoom out'))}">${ic('minus', 's')}</button><span class="dv-zp" data-fl-fill></span><button type="button" class="iconbtn" data-dc="dvz:in" aria-label="${esc(tr('Zoom in'))}" title="${esc(tr('Zoom in'))}">${ic('plus', 's')}</button>
    <button type="button" class="btn sm" data-dc="dvz:width" aria-pressed="${dcv_zoom() === 'width'}" title="${esc(tr('Fit to width'))}">${tr('Width')}</button><button type="button" class="btn sm" data-dc="dvz:page" aria-pressed="${dcv_zoom() === 'page'}" title="${esc(tr('Show the whole page'))}">${tr('Whole page')}</button><span class="spacer"></span>
    ${dcv_copyOn(d) ? `<button type="button" class="btn sm" data-dc="dvcopy" title="${esc(tr('Copy the recognised text'))}">${ic('copy', 's')} <span>${tr('Copy text')}</span></button>` : '' /* 2.742.0 (#4861) */}<button type="button" class="btn sm" data-dc="view" title="${esc(tr('Show {0}', d.name))}">${ic('expand', 's')} <span>${tr('Full screen')}</span></button></div>
    <div class="dv-pages" data-fl-fill tabindex="0" role="region" aria-label="${esc(tr('Show {0}', d.name))}"></div></section>`;
}
// 2.742.0 (#4861): "Copy text" with the recognised text: an image, a scanned PDF (recognised by OCR, or its first page has no
// text layer); a PDF with text is marked in the preview itself. #4806 (the archive version with a text layer) is not built yet.
const dcv_copyOn = d => !!(d?.text && !d.file && (/^image\//.test(d.mime || '') || (dc_isPdf(d) && (d.method === 'ocr' || DVW.notext === d.id))));
async function dcv_copyText(text) {
  let ok = false;
  try { if (typeof clipCopy === 'function') ok = await clipCopy(text); else { await navigator.clipboard.writeText(text); ok = true; } } catch { ok = false; }
  toast(ok ? tr('Copied') : tr('Copy failed, select the text by hand'));
}
// Cmd / Ctrl+A inside the preview: the text of every page (pdfview.js pv_selAll), not the whole app
document.addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || (e.key || '').toLowerCase() !== 'a' || !DVW.pdf || typeof pv_selAll !== 'function') return;
  const box = DVW.pdf.box, t = /** @type {any} */ (e.target), an = getSelection()?.anchorNode;
  if (!box?.isConnected || !(box.contains(t) || (an && box.contains(an)))) return;
  e.preventDefault(); e.stopPropagation();
  pv_selAll(DVW.pdf.doc, $('.dv-pgcol', box));
});
function dcv_free() { if (DVW.pdf) DVW.pdf.off = true; try { DVW.pdf?.doc?.destroy(); } catch { /* gone */ } DVW.pdf?.io?.disconnect(); DVW.pdf = null; }
// 2.736.0 (#5212): nb = a neighbour drawn ahead ({ctrl}): its own PDF (nb.pdf, the open one's stays), stopped by nb.ctrl
async function dcv_pvDraw(md, d, nb) {
  const box = $('.dv-pages', md); if (!box) return;
  const key = `${d.id}:${d.size}`;  // a field saved does not draw it again
  if (box._pv === key && box.firstChild) return;
  box._pv = key;
  if (!nb && DVW.pdf && DVW.pdf.box !== box) dcv_free();
  if (!DVW.ro && typeof ResizeObserver === 'function') DVW.ro = new ResizeObserver(es => { for (const e of es) if (/** @type {any} */ (e.target).isConnected) { const t = /** @type {any} */ (e.target); (t._rt ||= debounce(() => dcv_layout(t), 80))(); } });
  DVW.ro?.observe(box);
  if (!box._sc) { box._sc = true; box.addEventListener('scroll', () => dcv_pgn(box), {passive: true}); }
  const live = () => (nb && !nb.taken ? !nb.ctrl.signal.aborted : box.isConnected && !box.closest('.dv-nbhold')) && box._pv === key;
  box.dataset.pages = ''; box._base = null;
  box.innerHTML = `<div class="dv-pgcol">${d.thumb ? `<div class="dv-pg dv-img dv-thumb"><img src="${esc(dc_thumbUrl(d))}" alt=""></div>` : `<span class="dc-ph">${ic(dc_isPdf(d) ? 'file' : 'picture')}</span>`}</div>`;
  dcv_pgn(box); dcv_zbar(box);
  if (/^image\//.test(d.mime || '') && d.thumb) {  // the original, not the small picture
    const im = new Image(); im.alt = d.name;
    im.onload = () => { if (!live()) return; box.innerHTML = '<div class="dv-pgcol"><div class="dv-pg dv-img"></div></div>'; $('.dv-pg', box).appendChild(im); box._base = [{w: im.naturalWidth || 600, h: im.naturalHeight || 800, img: true}]; dcv_layout(box, false, true); };
    im.src = dc_fileUrl(d);
    return;
  }
  if (!dc_isPdf(d) || d.size > 40e6 || typeof loadModule !== 'function') return;
  try {
    await loadModule('pdf');
    const lib = typeof pv_load === 'function' ? await pv_load() : null; if (!lib || !live()) return;
    const r = await fetch(dc_fileUrl(d), {credentials: 'same-origin', signal: nb?.ctrl.signal}); if (!r.ok || !live()) return;
    // as in pdfview.js: nothing in the file runs (no eval, no scripts, no links)
    const doc = await lib.getDocument({data: new Uint8Array(await r.arrayBuffer()), isEvalSupported: false, enableScripting: false, disableAutoFetch: true, stopAtErrors: false, useSystemFonts: true}).promise;
    if (!live()) { doc.destroy(); return; }
    const base = [];
    const np = Math.min(doc.numPages, 2000);  // 2.583.0 (#4835 review): a forged page count (/Count) must not freeze the tab
    for (let i = 1; i <= np; i++) {  // every page's own size; the first 30 read up front, later ones like the one before
      const vp = i <= 30 ? (await doc.getPage(i)).getViewport({scale: 1}) : null;
      base.push(vp ? {w: vp.width, h: vp.height} : {...base[base.length - 1]});
      if (!live()) { doc.destroy(); return; }
    }
    if (nb && !nb.taken) { nb.pdf = {doc, box, gen: 0, nb: true}; }  // 2.736.0 (#5212): the neighbour's own (dcv_nbTake makes it the view's)
    else { if (DVW.pdf) dcv_free(); DVW.pdf = {doc, box, gen: 0}; }
    box._base = base;
    box.innerHTML = `<div class="dv-pgcol">${base.map((_, i) => `<div class="dv-pg" data-i="${i}"></div>`).join('')}</div>`;
    box.dataset.pages = String(base.length);
    dcv_layout(box, false, true);
  } catch { /* the small picture stays */ }
}
// the pages get their final size before they are drawn (no jumps): Width = the widest page fills the box, Whole page = the
// first page fits in it, else the zoom chosen (pdf.js scale: 1 = one point per CSS pixel; an image: 1 = its pixels)
function dcv_scale(box) {
  const z = dcv_zoom(), b = box._base, b0 = b[0], mw = Math.max(...b.map(x => x.w));
  if (z === 'width') return Math.min(b0.img ? 2 : DCV_ZMAX, box._aw / mw);
  if (z === 'page') return Math.min(b0.img ? 2 : DCV_ZMAX, box._aw / b0.w, box._ah / b0.h);
  return +z;
}
function dcv_layout(box, keep, force) {
  if (!box?.isConnected || !box._base) return;
  const cs = getComputedStyle(box), px = k => parseFloat(cs[k] || '0') || 0;
  const aw = Math.max(120, box.clientWidth - px('paddingLeft') - px('paddingRight') - 2), ah = Math.max(120, box.clientHeight - px('paddingTop') - px('paddingBottom') - 2);
  if (!force && !keep && Math.abs((box._aw || 0) - aw) < 2 && Math.abs((box._ah || 0) - ah) < 2) return;
  box._aw = aw; box._ah = ah;
  const s = dcv_scale(box), top = box.scrollTop / Math.max(1, box.scrollHeight);
  if (!force && !keep && box._s === s) return;
  box._s = s;
  const pages = $$('.dv-pg', box);
  pages.forEach((p, i) => { const b = box._base[i] || box._base[0]; p.style.width = Math.floor(b.w * s) + 'px'; p.style.height = Math.floor(b.h * s) + 'px'; });
  if (keep) box.scrollTop = top * box.scrollHeight;
  if (typeof pv_textScale === 'function') pv_textScale(box, s);  // 2.742.0 (#4861): the text layers stay on their page
  dcv_zbar(box); dcv_pgn(box);
  const pdf = DVW.pdf?.box === box ? DVW.pdf : [...(DCW.nb?.values() || [])].find(e => e.pdf?.box === box)?.pdf; if (!pdf || pdf.off) return;  // 2.736.0 (#5212): + a neighbour's
  pdf.gen++; pdf.s = s;
  for (const p of pages) p.dataset.s = '';
  pdf.io?.disconnect();
  // a page coming near is drawn; one far away gives its canvas back (the memory of a long PDF stays small)
  pdf.io = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) dcv_page(pdf, en.target); else if (en.target.firstChild) { en.target.textContent = ''; en.target.dataset.s = ''; } }), {root: box, rootMargin: '600px 0px'});
  pages.forEach(p => pdf.io.observe(p));
}
async function dcv_page(pdf, p) {
  const s = pdf.s, my = pdf.gen, i = +p.dataset.i;
  if (p.dataset.s === String(s)) return;
  p.dataset.s = String(s);
  try {
    const page = await pdf.doc.getPage(i + 1);
    if (my !== pdf.gen || pdf.off) return;  // 2.736.0 (#5212): pdf.off = freed (the view's or a neighbour's)
    const vp = page.getViewport({scale: s});
    // sharp: the screen's own pixel density (up to 3), at most DCV_CVMAX pixels per page
    const dpr = Math.min(window.devicePixelRatio || 1, 3, Math.sqrt(DCV_CVMAX / (vp.width * vp.height)));
    const cv = document.createElement('canvas');
    cv.width = Math.floor(vp.width * dpr); cv.height = Math.floor(vp.height * dpr);
    cv.setAttribute('aria-label', tr('Page {0}', i + 1));
    await page.render({canvas: cv, canvasContext: cv.getContext('2d'), viewport: vp, transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null}).promise;
    if (my !== pdf.gen || pdf.off || p.dataset.s !== String(s)) return;
    p.replaceChildren(cv);
    // 2.742.0 (#4861): the text layer over the page (pdfview.js pv_text); page 1 without any text = a scan: "Copy text"
    if (typeof pv_text === 'function') await pv_text(typeof pv_libNow === 'undefined' ? null : pv_libNow, page, vp, p, () => my === pdf.gen && !pdf.off && p.dataset.s === String(s) && p.isConnected);
    const d = DC.doc;
    if (i === 0 && p._pvnt && d && DVW.notext !== d.id && pdf.box.closest('.dv-view') && $('.dc-body', pdf.box.closest('.dv-view'))?.dataset.id === String(d.id)) { DVW.notext = d.id; if (dcv_copyOn(d)) dc_mdDraw(pdf.box.closest('.dv-view')); }
  } catch { if (my === pdf.gen) p.dataset.s = ''; }
}
function dcv_pgn(box) {  // "Page 3 / 12": the page at the upper third of the box
  const el = box.closest('.dv-pv')?.querySelector('.dv-pgn'); if (!el) return;
  const n = +(box.dataset.pages || 0);
  if (!n) { el.textContent = ''; return; }
  const ps = $$('.dv-pg', box), mid = box.scrollTop + box.clientHeight / 3;
  let i = 0;
  while (i < ps.length - 1 && ps[i].offsetTop + ps[i].offsetHeight < mid) i++;
  const t = tr('Page {0} / {1}', i + 1, n);
  if (el.textContent !== t) el.textContent = t;
}
function dcv_zbar(box) {
  const bar = box.closest('.dv-pv')?.querySelector('.dv-pvbar'); if (!bar) return;
  const z = dcv_zoom(), s = box._s, on = !!box._base;
  const zp = $('.dv-zp', bar); if (zp) zp.textContent = on && s ? Math.round(s * 100) + ' %' : '';
  for (const k of ['width', 'page']) $(`[data-dc="dvz:${k}"]`, bar)?.setAttribute('aria-pressed', String(z === k));
  const o = $('[data-dc="dvz:out"]', bar), n = $('[data-dc="dvz:in"]', bar);
  if (o) o.disabled = !on || s <= DCV_ZMIN; if (n) n.disabled = !on || s >= DCV_ZMAX;
}
function dcv_zoomSet(box, z) {
  if (!box?._base) return;
  if (typeof z === 'number') z = Math.max(DCV_ZMIN, Math.min(DCV_ZMAX, +z.toFixed(3)));
  LS.set('dv.zoom', z);
  dcv_layout(box, true, true);
}
// Ctrl / Cmd + wheel and + / - / 0 on the preview zoom it (0 = the width)
document.addEventListener('wheel', e => {
  const box = /** @type {any} */ (e.target).closest?.('.dv-pages'); if (!box || !(e.ctrlKey || e.metaKey) || !box._s) return;
  e.preventDefault(); dcv_zoomSet(box, box._s * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
}, {passive: false});

// ---- events of the view: the clicks of the fields and buttons are docs.js dc_mdClick (data-dc), the view's own ones here
document.addEventListener('click', e => {
  const v = /** @type {any} */ (e.target).closest?.('.dv-view'); if (!v) { if (DC.actsMore && !/** @type {any} */ (e.target).closest?.('.dv-actw')) dcv_menuClose(); return; }
  const g = /** @type {any} */ (e.target).closest('[data-dvgo]');
  if (g) { const to = +g.dataset.dvgo, i = (DC.docs || []).findIndex(x => x.id === to), j = dc_navIdx(DC.doc); if (DC.doc && to !== DC.doc.id) dc_goTo(to, i > j ? 1 : -1); return; }
  const t = /** @type {any} */ (e.target).closest('[data-dvtab]');
  if (t) { dcv_tab(v, t.dataset.dvtab); return; }
  if (DC.actsMore && !/** @type {any} */ (e.target).closest('.dv-actw')) dcv_menuClose();
  const b = /** @type {any} */ (e.target).closest('[data-dc]'); if (!b) return;
  const a = b.dataset.dc;
  if (a.startsWith('dvz:')) {
    const box = $('.dv-pages', v), k = a.slice(4); if (!box?._s) return;
    dcv_zoomSet(box, k === 'in' ? box._s * 1.25 : k === 'out' ? box._s / 1.25 : k);
    return;
  }
  if (a === 'dvstrip') {
    if (dcv_stripOff()) LS.del('dv.stripOff'); else LS.set('dv.stripOff', true);
    dc_mdDraw(v); $('.dv-view [data-dc="dvstrip"]')?.focus({preventScroll: true});
    return;
  }
  if (a === 'dvundo') { dcv_undo(); return; }
  if (a === 'dvcopy') { if (DC.doc?.text) dcv_copyText(DC.doc.text); return; }  // 2.742.0 (#4861)
  if (a === 'dvrecog' && DC.doc?.file) {  // 2.583.0 (#4832): a plain file becomes a document (the view shows its fields then)
    const id = DC.doc.id;
    api('PUT', `/api/files/nodes/${id}/recognition`, {mode: 'on'}).then(() => { toast(tr('“{0}” is being recognised', DC.doc?.name || '')); if (DC.doc?.id === id) dc_open(id); }).catch(() => {});
    return;
  }
  if (a.startsWith('edit:')) {  // "automatic": its field, also when it waits under "More fields"
    const f = $(`#dc-${a.slice(5)}`, v); if (!f) return;
    dcv_tab(v, 'details'); const m = f.closest('.dv-more'); if (m && !m.open) { m.open = true; DVW.more = true; }
    f.focus(); return;
  }
  if (DC.actsMore && b.closest('.dv-amenu')) dcv_menuClose();  // an action of the menu: the menu closes
  dc_mdClick(e);
});
document.addEventListener('change', e => { if (/** @type {any} */ (e.target).closest?.('.dv-view')) dc_mdChange(e); });
document.addEventListener('toggle', e => { if (/** @type {any} */ (e.target)?.classList?.contains('dv-more')) DVW.more = /** @type {any} */ (e.target).open; }, true);
function dcv_menuClose() {
  DC.actsMore = null;
  const b = $('.dv-view [data-dc="actsmore"]'); if (b) b.setAttribute('aria-expanded', 'false');
  const m = $('.dv-view #dc-amore'); if (m) m.hidden = true;
}
// 2.655.0 (#4998): the view's keys sit in the key registry (keys.js, scope view:docs): an open dialog / menu (the stack) has
// them first; returning false hands the key on (selection, detail, global)
const dcv_keyView = (/** @type {any} */ e) => { const v = $('.dv-view'); return v && S.route.mod === 'docs' && dc_hashId() && !e.altKey && !e.ctrlKey && !e.metaKey && !$('.modal') && !$('.lightbox') && !$('#pop:not(.hidden)') && !e.target?.closest?.('[data-dvgrip]') ? v : null; };
kb_on('view:docs', 'Escape', e => {
  const v = dcv_keyView(e); if (!v) return false;
  const t = /** @type {any} */ (e.target);
  if (DC.actsMore) { dcv_menuClose(); $('.dv-view [data-dc="actsmore"]')?.focus(); return; }
  if (dcv_in(t)) { t.blur(); return; }  // the first Esc leaves the field (it saves), the next one the view
  dcv_close(v);
});
for (const k of ['+', '=', '-', '0']) kb_on('view:docs', k, e => {  // + / - / 0 on the preview zoom it (0 = the width)
  const box = dcv_keyView(e) && /** @type {any} */ (e.target).closest?.('.dv-pages'); if (!box || !box._s) return false;
  dcv_zoomSet(box, e.key === '0' ? 'width' : box._s * (e.key === '-' ? 1 / 1.25 : 1.25));
});
for (const k of ['ArrowLeft', 'ArrowRight']) kb_on('view:docs', k, e => {
  const v = dcv_keyView(e), t = /** @type {any} */ (e.target); if (!v || dcv_in(t)) return false;
  const dir = e.key === 'ArrowRight' ? 1 : -1, tab = t.closest?.('[role="tab"]');
  if (tab) {  // the tabs: left / right moves among them
    const ts = $$('[data-dvtab]', v), i = ts.indexOf(tab), n = ts[(i + dir + ts.length) % ts.length];
    if (n) dcv_tab(v, n.dataset.dvtab, true);
    return;
  }
  const box = t.closest?.('.dv-pages');
  if (box && box.scrollWidth > box.clientWidth + 2) return false;  // zoomed wider than the box: the keys scroll it sideways
  dc_step(dir);
});

// ---- the grips (drag, arrow keys, double click / Home = the standard width), kept per device
function dcv_gripMax(g, which, v) {  // the room of the columns minus the other column, the grips and the preview's rest
  const rem = dcv_rem(), cols = $('.dv-cols', v), other = $(which === 'strip' ? '.dv-mask' : '.dv-strip', v);
  const grips = $$('.dv-grip', v).reduce((a, x) => a + x.getBoundingClientRect().width, 0);
  return Math.max(g.min * rem, (cols?.clientWidth || 0) - (other?.getBoundingClientRect().width || 0) - grips - DCV_KEEP * rem);
}
function dcv_gripSet(which, px, save) {
  const g = DCV_GRIPS[which], v = $('.dv-view'); if (!g || !v) return;
  if (px == null) { v.style.removeProperty(g.v); LS.del(g.k); }
  else {
    px = Math.round(Math.max(g.min * dcv_rem(), Math.min(dcv_gripMax(g, which, v), px)));
    v.style.setProperty(g.v, px + 'px');
    if (save) LS.set(g.k, px); else if (DVW.drag?.which === which) DVW.drag.px = px;  // 2.547.0 (#4492): see dcv_colStyle
  }
}
// 2.547.0 (#4492, from the reading view): the width the grip set last when it set one - Firefox applies a changed width only
// with the next frame, measured before (a drag or an arrow key right after the one before) the old width came back
function dcv_gripNow(which) {
  const set = parseFloat($('.dv-view')?.style.getPropertyValue(DCV_GRIPS[which]?.v || '') || '');
  if (set > 0) return set;
  return $(which === 'strip' ? '.dv-view .dv-strip' : '.dv-view .dv-mask')?.getBoundingClientRect().width || 0;
}
document.addEventListener('pointerdown', e => {
  const gr = /** @type {any} */ (e.target).closest?.('[data-dvgrip]'); if (!gr || e.button !== 0) return;
  e.preventDefault();
  const which = gr.dataset.dvgrip;
  DVW.drag = {which, x0: e.clientX, w0: dcv_gripNow(which), px: null};
  try { gr.setPointerCapture(e.pointerId); } catch { /* a synthetic event */ }
  document.documentElement.classList.add('dv-resizing');
});
document.addEventListener('pointermove', e => {
  const d = DVW.drag; if (!d) return;
  d.px = d.w0 + e.clientX - d.x0;  // both columns grow to the right
  dcv_gripSet(d.which, d.px, false);
});
function dcv_dragEnd() {
  const d = DVW.drag; if (!d) return;
  DVW.drag = null; document.documentElement.classList.remove('dv-resizing');
  if (d.px != null) dcv_gripSet(d.which, d.px, true);
}
document.addEventListener('pointerup', dcv_dragEnd);
document.addEventListener('pointercancel', dcv_dragEnd);
document.addEventListener('dblclick', e => { const gr = /** @type {any} */ (e.target).closest?.('[data-dvgrip]'); if (gr) { e.preventDefault(); dcv_gripSet(gr.dataset.dvgrip, null); } });
document.addEventListener('keydown', e => {
  const gr = /** @type {any} */ (e.target).closest?.('[data-dvgrip]'); if (!gr) return;
  const which = gr.dataset.dvgrip, step = (e.shiftKey ? 4 : 1) * dcv_rem();
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); dcv_gripSet(which, dcv_gripNow(which) + (e.key === 'ArrowRight' ? step : -step), true); }
  else if (e.key === 'Home' || e.key === 'Delete') { e.preventDefault(); dcv_gripSet(which, null); }
});

// ---- Full screen: the document in the viewer of pdfview.js; the arrow keys left / right and two buttons leaf through the
// list as shown (the view follows), without closing it (2.521.0, #4476)
function dcv_fullOpts(d) {
  const o = {url: dc_fileUrl(d), name: d.name, size: d.size, dlUrl: dc_fileUrl(d, true)};
  if (!dc_isPdf(d)) { o.img = /^image\//.test(d.mime || '') ? dc_fileUrl(d) : null; o.kind = o.img ? 'img' : 'file'; }
  // 2.652.0 (#5071): phones too (before: no leafing there) - a swipe sideways leafs on every touch screen (pdfview.js)
  const i = dc_navIdx(d);
  if (i >= 0) {
    const n = dc_navN();  // 2.683.0 (#5150): the list it was opened from (the file store's folder or the documents)
    o.pos = tr('{0} of {1}', i + 1, n); o.first = i <= 0; o.last = i >= n - 1;
    o.prevT = tr('Previous document'); o.nextT = tr('Next document');
    o.step = async dir => (await dc_step(dir)) && DC.doc ? dcv_fullOpts(DC.doc) : null;
    o.peek = dir => ({img: dc_nbThumb(dc_nav()?.docs[i + dir])});  // 2.727.0 (#5202): its small picture glides in with the swipe
    o.near = dir => { const x = dc_nav()?.docs[i + dir], e = x && typeof dc_nbFresh === 'function' ? dc_nbFresh(x.id) : null; return e?.d ? dcv_fullOpts(e.d) : null; };  // 2.736.0 (#5212): fetched ahead by docs.js, made ready by pdfview.js
  }
  return o;
}
function dcv_full(d) {  // true = shown here (else docs.js opens it as before)
  // 2.583.0 (#4832): a plain file that is no PDF / picture: the file store's own viewer (text, office preview, download)
  if (d.file && !dc_isPdf(d) && !/^image\//.test(d.mime || '') && typeof ab_openFile === 'function') { ab_openFile({...d, kind: 'file'}, {raw: true}); return true; }
  if (typeof pdfView !== 'function' || (typeof dv_is === 'function' && dv_is(d))) return false;  // 2.635.0 (#4807): Office files: docs.js
  const o = dcv_fullOpts(d);
  if (o.kind && !o.step) return false;  // an image / another file without leafing: as before
  pdfView(o);
  return true;
}
