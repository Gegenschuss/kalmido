/* Kalmido web client: Documents (2.48.0, #1111): the list (cards with a preview), filters, full-text search, upload by
   dragging, the document sheet (preview, fields with "automatic" marks, suggestions "To review", recognised text) and the
   settings of a workspace (level per feature, rules, the forwarding address). Routes #ablage/docs, #ablage/review,
   #ablage/v/<id> and a document #ablage/<id> (2.752.0 #4887: one area "Files", areas.js; the old #docs… lead there, core.js);
   a folder with recognition shows this list too (abdocs.js abd_foldHtml). Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

const DC = {docs: null, total: 0, review: 0, waiting: 0, facets: null, err: null, loading: false, seq: 0, q: '',
  f: dc_f0(), more: false, poll: null, doc: null, set: null, drag: 0,
  page: 200};  // 2.476.0 (#3935): the documents of one load (the server's PAGE_MAX), the next ones follow at the list's end
const DC_FEATS = [['sender', N_('Sender')], ['type', N_('Document type')], ['tags', N_('Tags')], ['folder', N_('Folder')]];
const DC_LEVELS = [['learn', N_('Learns from your documents')], ['rules', N_('Rules only')], ['agent', N_('Left to an agent')], ['off', N_('Off')]];
const DC_KINDS = [['any', N_('contains one of the words')], ['all', N_('contains all words')], ['exact', N_('contains the exact phrase')],
  ['fuzzy', N_('contains the phrase (tolerates typos)')], ['regex', N_('matches the pattern (regular expression)')]];
// 2.153.0 (#2179): the types of the custom fields of documents (docs/fields.py DF_TYPES; DC_FTYPES = the file types of the filter)
const DC_CFTYPES = [['text', N_('Text')], ['number', N_('Number')], ['money', N_('Amount')], ['date', N_('Date')], ['checkbox', N_('Checkbox')], ['select', N_('Selection')], ['url', N_('Link')], ['longtext', N_('Long text')], ['documentlink', N_('Link to documents')]];  // 2.635.0 (#4807 c): + long text, link to documents
const DC_STATE = {wait: N_('Waiting for recognition'), run: N_('Recognising…'), done: N_('Recognised'), failed: N_('Recognition failed')};
const DC_BY = {rule: N_('set by a rule'), learn: N_('learnt from your documents'), agent: N_('set by an agent'), import: N_('imported'), code: N_('read from the code on the document'), photo: N_('from the capture date of the photo')};  // 2.61.0 B (#1819): photo

// the module switch (Settings > Modules), off by default like the other areas
// 2.65.0 (#1823): the module switch (FEATS, FEAT_DESC) and dc_shareOk are in lazyload.js (this file loads on demand)
const dc_ws = () => (typeof wsCur === 'function' ? wsCur() : 'all');
const dc_upWs = () => { const w = dc_ws(); return w.startsWith('org:') ? w : 'private'; };
const dc_hashId = () => { try { const m = location.hash.match(/^#(docs|ablage)\/(\d+)/); return m && (m[1] === 'docs' || AB_FILEIDS.has(+m[2])) ? +m[2] : null; } catch { return null; } };  // the sheet may close after its window is gone; 2.752.0 (#4887): #ablage/<id> of a file (core.js AB_FILEIDS)
const dc_money = (a, cur) => curMoney(a, cur);  // 2.189.0 (#2475): + £; 2.368.0 C (#2983): one money format (i18n.js curMoney)
const dc_day = d => { const s = String(d || '').slice(0, 10); return /^\d{4}-\d\d-\d\d$/.test(s) ? fmtDateNum(pd(s)) : ''; };  // 2.583.0 (#4877): always the whole date with the year (06.11.2026), no Today / weekday
const dc_isPdf = d => d && (d.mime === 'application/pdf' || /\.pdf$/i.test(d.name));
// 2.750.0 (#4876): what a document is called: its own title, else its file name without the ending of a known type (the
// server sends title so, docs/store.py doc_title - the same endings). The file name (name) is for downloads, ZIPs, the file store
const DC_TITLE_EXT = /\.(pdf|jpe?g|png|heic|heif|tiff?|webp|gif|bmp|txt|md|csv|xml|json|eml|msg|html?|rtf|odt|ods|odp|docx?|xlsx?|pptx?|zip)$/i;
const dc_title = d => (d?.title || '').trim() || (d?.name || '').replace(DC_TITLE_EXT, '').trim() || d?.name || '';
const dc_fileExt = name => (/\.[^.\s/]{1,8}$/.exec(name || '') || [''])[0];  // "Brief.pdf" -> ".pdf"
const dc_fileUrl = (d, dl) => d.file ? `/api/files/nodes/${d.id}/content?v=${d.version || 1}${dl ? '&dl=1' : ''}` : `/api/docs/${d.id}/file?v=${d.size}${dl ? '&dl=1' : ''}`;  // 2.583.0 (#4832): a plain file of the file store too
// 2.583.0 (#4832): the small picture of a document or of a plain file (the file store's own, its version keeps it fresh)
const dc_thumbUrl = (d, l) => (d.file ? `/api/files/nodes/${d.id}/thumb?v=${encodeURIComponent(d.version || 1)}` : `/api/docs/${d.id}/thumb?v=${encodeURIComponent(d.updated_at || '')}`) + (l ? '&size=l' : '');  // 2.583.0 (#4812): l = the sharp preview of big cards
// 2.583.0 (#4832): a file of the file store that is no document, in the shape the document view draws (no fields: "Recognise")
const dc_fileDoc = n => ({id: n.id, name: n.name, mime: n.mime || '', size: n.size || 0, version: n.version || 1, role: n.role, org_id: n.org_id || null,
  parent_id: n.parent_id, updated_at: n.updated_at, owner: n.owner, up: n.up, locked: n.locked, _enc: n._enc, file: true, state: 'none', tags: [], thumb: /^image\//.test(n.mime || '')});

// ---- 2.428.0 (#3579): the sort of the list, sorted by the server (the pages stay right), remembered per device
const DC_SORTS = [['date', N_('Document date')], ['added', N_('Date of arrival')], ['sender', N_('Sender')], ['amount', N_('Amount')], ['due', N_('Due date')], ['title', N_('Title')],
  ['type', N_('Document type')], ['review', N_('To review')]];  // 2.769.0 (#5340): + type and "to review" (the columns of a folder's list)
const dc_sortDir0 = k => (k === 'title' || k === 'sender' || k === 'type' ? 'asc' : 'desc');
function dc_sort() {
  if (DC.vsort && DC_SORTS.some(x => x[0] === DC.vsort.k)) return DC.vsort;  // 2.579.0 (#4802): a saved view keeps its own sort (docviews.js)
  const s = LS.get('dc.sort', null) || {}, k = DC_SORTS.some(x => x[0] === s.k) ? s.k : 'date';
  return {k, d: s.d === 'asc' || s.d === 'desc' ? s.d : dc_sortDir0(k)};
}
function dc_sortSet(k, d) {
  if (DC.vsort) { DC.vsort = {k, d}; DC.at = 0; dc_load(); dc_draw(); return; }  // 2.579.0 (#4802): in a view the sort changes the view's search, not the device's
  if (k === 'date' && d === 'desc') LS.del('dc.sort'); else LS.set('dc.sort', {k, d});
  DC.at = 0; dc_load(); dc_draw();
}
const dc_sortPick = k => { const s = dc_sort(); dc_sortSet(k, s.k === k ? (s.d === 'asc' ? 'desc' : 'asc') : dc_sortDir0(k)); };  // the chosen one again: the other direction
function dc_sortBtn() {
  const s = dc_sort(), name = tr(DC_SORTS.find(x => x[0] === s.k)[1]), dir = s.d === 'asc' ? tr('ascending|sort') : tr('descending|sort');
  return `<button type="button" class="btn sm dc-sortb ${s.k !== 'date' || s.d !== 'desc' ? 'on' : ''}" data-dc="sort" aria-haspopup="menu" title="${esc(tr('Sorting') + ': ' + name + ', ' + dir)}" aria-label="${esc(tr('Sorting') + ': ' + name + ', ' + dir)}">${ic('sort', 's')} <span>${esc(name)}</span> ${s.d === 'asc' ? '↑' : '↓'}</button>`;
}
function dc_sortMenu(anchor) {
  const s = dc_sort();
  menu(anchor, [...DC_SORTS.map(([k, n]) => ({label: tr(n), on: s.k === k, cls: 'dc-sorti', title: s.k === k ? tr('Click again to reverse the direction') : '', fn: () => dc_sortPick(k)})), '-',
    {label: tr('ascending|sort'), on: s.d === 'asc', fn: () => dc_sortSet(s.k, 'asc')}, {label: tr('descending|sort'), on: s.d === 'desc', fn: () => dc_sortSet(s.k, 'desc')}]);
}
function dc_sortHtml() {  // phones: the sort at the top of the filter sheet
  const s = dc_sort();
  return `<h4>${tr('Sorting')}</h4><div class="tsgrp">${DC_SORTS.map(([k, n]) => `<button type="button" class="tsp ${s.k === k ? 'tsp-in' : ''}" data-dcsort="${k}" aria-pressed="${s.k === k}">${esc(tr(n))}</button>`).join('')}</div>
    <div class="tsrow"><div class="seg" role="radiogroup" aria-label="${esc(tr('Sorting'))}">${['asc', 'desc'].map(d => `<button type="button" role="radio" data-dcsortd="${d}" aria-checked="${s.d === d}">${d === 'asc' ? tr('ascending|sort') : tr('descending|sort')}</button>`).join('')}</div></div>`;
}

// ---- loading
function dc_params() {
  const p = new URLSearchParams({ws: dc_ws(), limit: String(DC.page)});
  if (DC.q.trim()) p.set('q', DC.q.trim());
  for (const k of ['tag', 'from', 'to']) if (DC.f[k]) p.set(k, DC.f[k]);
  dc_fParams(p);  // 2.122.0 B (#2294): several values, more filters
  if (DC.f.review) p.set('review', '1');
  // 2.752.0 (#4887): a folder with recognition (abdocs.js abd_foldHtml): its own documents; a search or a filter takes its
  // subfolders along (under); the folder is named, so the file store's filter of the receipts is not needed there
  if (DC.folder) { if (DC.q.trim() || dc_fEntries().length) p.set('under', String(DC.folder)); else p.append('folder', String(DC.folder)); }
  else if (dc_ws() === 'all' || dc_ws() === 'private') p.set('area', 'private');  // 2.522.0 (#4433): the file store shows no receipts (no office: no filter)
  if (DC.under && !DC.folder) p.set('under', DC.under);  // 2.199.0 B (#2742): a saved view's folder (with its subfolders); 2.752.0 (#4887): no tree of its own any more
  const so = dc_sort(); if (so.k !== 'date' || so.d !== 'desc') { p.set('sort', so.k); p.set('dir', so.d); }  // 2.428.0 (#3579)
  if (DC.dv) p.set('view', String(DC.dv));  // 2.857.0 (#5518): a saved view's filter (the server reads it with the person's rights, docviews.js)
  return p;
}
async function dc_load() {
  const seq = ++DC.seq, ws = dc_ws();  // 2.66.1 (#1945): the workspace of this load, held from its start
  DC.loading = true; DC.ws = ws;
  try {
    const p = dc_params(), key = dc_key(p);
    const j = await api('GET', '/api/docs?' + p);
    if (seq !== DC.seq || ws !== dc_ws()) return;  // 2.66.1 (#1945): an answer for a workspace no longer shown is dropped
    const rv0 = DC.review;
    // 2.476.0 (#3935): the same list loaded again (the poll, a change) keeps the pages loaded after the first one
    let docs = j.docs;
    if (DC.docs && DC.key === key && DC.docs.length > docs.length && docs.length >= DC.page) { const have = new Set(docs.map(x => x.id)); docs = docs.concat(DC.docs.slice(docs.length).filter(x => !have.has(x.id))); }
    Object.assign(DC, {docs, total: j.total, review: j.review, waiting: j.waiting, facets: j.facets || DC.facets, err: null, key});
    if (rv0 !== DC.review && typeof sbb_sync === 'function') setTimeout(() => sbb_sync('ablage'), 0);  // 2.353.0 D (#2759): the counter of the saved filter To review
    if (j.facets && typeof dfc_take === 'function') dfc_take(p, j.facets);  // 2.772.0 (#4890): the numbers below the tree follow the list
  } catch (x) { if (seq !== DC.seq || ws !== dc_ws()) return; DC.err = x.message || tr('unknown'); }
  DC.loading = false; DC.at = Date.now(); DC.atWs = ws;  // 2.62.0 (#1844)
  dc_draw();
  dc_pollSet();
}
// 2.979.0 (#5667): after an undo / redo the server took back by its group (the step's own undo no longer runs): the open
// document (DC.doc, the view / sheet .dc-md) reads itself again and draws only when it changed (a calm view); a file follows a
// new version / name like after its own restore (docview.js dcv_verAfter). The list: undo.js histRedraw (ab_relist), viewDocs
// loads it on every opening
histReloader('docs', async () => {
  const d = DC.doc, md = $('.dc-md'); if (!d?.id || !md) return;
  const x = await rawFetch('GET', d.file ? `/api/files/nodes/${d.id}` : `/api/docs/${d.id}`).catch(() => null);
  if (!x || DC.doc?.id !== d.id) return;
  if (d.file) {
    if ((x.version !== d.version || x.name !== d.name || (x.parent_id ?? null) !== (d.parent_id ?? null)) && typeof dcv_verAfter === 'function') await dcv_verAfter(d.id, x.version !== d.version);
    return;
  }
  const own = o => JSON.stringify(Object.entries(o).filter(([k]) => !k.startsWith('_')));  // without the view's own marks (_fv)
  if (own(x) === own(d)) return;
  DC.doc = {...x, _fv: d._fv}; dc_mdDraw($('.dc-md'));
});
// 2.476.0 (#3935): the next page of the list (scrolled to its end, the button there, swiped past the last loaded document);
// one at a time, an answer for a list loaded anew in between is dropped. Resolves true when documents were added.
const dc_key = p => { const q = new URLSearchParams(p); q.delete('limit'); q.delete('offset'); return q.toString(); };
function dc_more() {
  if (DC.moreP) return DC.moreP;
  const ds = DC.docs; if (!ds || DC.loading || ds.length >= DC.total) return Promise.resolve(false);
  const seq = DC.seq, ws = dc_ws(), p = dc_params();
  p.set('offset', String(ds.length)); p.set('facets', '0');
  DC.moreP = (async () => {
    try {
      const j = await api('GET', '/api/docs?' + p);
      if (seq !== DC.seq || ws !== dc_ws() || DC.docs !== ds) return false;
      const have = new Set(ds.map(x => x.id)), add = j.docs.filter(x => !have.has(x.id));
      DC.docs = ds.concat(add); DC.total = j.total;
      dc_draw();
      return add.length > 0;
    } catch { return false; } finally { DC.moreP = null; }
  })();
  return DC.moreP;
}
function dc_moreWatch() {  // the list's end coming near loads the next page (no observer: the button there)
  DC.io?.disconnect(); DC.io = null;
  const s = $('.dc-view .dc-moreld'); if (!s || typeof IntersectionObserver !== 'function') return;
  DC.io = new IntersectionObserver(es => { if (es.some(x => x.isIntersecting)) dc_more(); }, {root: $('#view'), rootMargin: '0px 0px 600px 0px'});  // #view scrolls (like render.js rowMoreIO)
  DC.io.observe(s);
}
// 2.87.9 (#1934): a hit of the search (palette.js palSubItems): the documents filtered by one sender / type / tag
function dc_filterGo(k, v) {
  DC.f = {...dc_f0(), from: DC.f.from, to: DC.f.to, ...(k === 'tag' ? {tg: {[v]: 'in'}} : {[k]: v})}; DC.more = true; DC.at = 0;  // 2.122.0 B (#2294)
  if (S.route.mod === 'docs') dc_load(); else go('ablage/docs');  // 2.752.0 (#4887)
}
// 2.772.0 (#4890): a filter of the file store's sidebar (docfacets.js): "All documents" with only this filter (part: a
// part of dc_f0, e.g. {sender: ['1,7']}); the search, a saved view and a folder's list are left
function dc_facetGo(part) {
  dc_ctxSet('list');
  if (DC.dv) { DC.dv = null; DC.vsort = null; if (typeof DCV === 'object') DCV.applied = null; }  // the view's own sort goes with it
  DC.f = {...dc_f0(), ...part}; DC.q = ''; DC.under = null; DC.at = 0; DC.facets = null;
  const qi = $('#dc-q'); if (qi) qi.value = '';
  // the list on screen (a saved view, To review) is not loaded again by viewDocs: loaded here; from elsewhere viewDocs loads it
  const here = S.route.mod === 'docs' && !dc_hashId();
  if (here && (S.route.review || S.route.dv)) go('ablage/docs');
  if (here) dc_load(); else go('ablage/docs');
  if (typeof sbb_sync === 'function') sbb_sync('ablage');
}
// 2.66.1 (#1945): the workspace switch (here, or on another device) drops the list, the counters, the filters (their values
// are ids of the old workspace) and an open document of the old workspace; viewDocs then loads the new one at once
function p61b_dcReset() {
  DC.seq++; clearTimeout(DC.poll);
  Object.assign(DC, {docs: null, total: 0, review: 0, waiting: 0, facets: null, set: null, err: null, loading: false, ws: null, atWs: null, more: false,
    sel: new Map(), selOn: false,  // 2.96.0 A (#1941): a choice of the old workspace goes
    f: dc_f0()});  // 2.122.0 B (#2294)
  const md = $('.dc-md');
  if (md && DC.doc && !wsObjIn(DC.doc)) { if (dc_hashId()) history.replaceState(history.state, '', '#ablage/docs'); md.remove(); }
}
function dc_pollSet() {  // while documents are being recognised, look again every few seconds
  clearTimeout(DC.poll);
  if (DC.waiting && dc_listOn() && !document.hidden) DC.poll = setTimeout(() => dc_listOn() && dc_load(), 4000);
}
// 2.752.0 (#4887): the list's context: 'list' (all documents, to review, a saved view: #ablage/docs|review|v/<id>) or
// 'f:<id>' (a folder with recognition, abdocs.js abd_foldHtml). Entering or leaving a folder starts its search empty
function dc_ctxSet(c) {
  if (DC.ctx === c) return false;
  const was = DC.ctx || 'list'; DC.ctx = c;
  DC.folder = c.startsWith('f:') ? +c.slice(2) : null;
  if (was !== c && (was.startsWith('f:') || c.startsWith('f:'))) {
    DC.seq++;  // a load of the context left is dropped (a pending search of it only loads the new one again)
    Object.assign(DC, {q: '', f: {...dc_f0(), review: false}, under: null, more: false, docs: null, total: 0, err: null, loading: false, key: null, sel: new Map(), selOn: false, dv: null, vsort: null});
    if (typeof DCV === 'object') DCV.applied = null;  // a saved view applied before is left (docviews.js applies it again on its route)
  }
  return true;
}
const dc_inFold = () => S.route.mod === 'ablage' && !!DC.folder && DC.ctx === 'f:' + S.route.nid && typeof abd_recogHere === 'function' && abd_recogHere('n:' + S.route.nid);
const dc_listOn = () => S.route.mod === 'docs' || dc_inFold();  // the list is on screen (its own route or a folder's)
function dc_draw() {
  const fold = dc_inFold();
  if (!fold && S.route.mod !== 'docs') return;
  const el = $('#view'); if (!el) return;
  if (fold) ab_draw();  // 2.752.0 (#4887): the folder draws its documents (ablage.js viewAblage)
  else keepFocus(el, () => setHtml(el, typeof mg_wrap === 'function' ? mg_wrap('docs', viewDocs()) : viewDocs()));
  dc_fSheetDraw();  // 2.122.0 B (#2294): the filter sheet (phones) follows the list
  dc_moreWatch(); dc_navSync();  // 2.476.0 (#3935)
}

// ---- the view
function viewDocs() {
  // 2.62.0 (#1844): opening the tab always loads again (the list shown before could be empty / old: files that arrived since, a
  // changed workspace, an earlier error); the old list stays until the new one is there, redraws within 3 s do not reload
  // (review: only when the tab is opened anew - a redraw of the open tab never reloads; an error waits for the next opening)
  // 2.583.0 (#4835): #docs/<id> = the document view (docview.js); the list is loaded behind it (its "3 of 128", its strip)
  const id = dc_hashId();
  const open = !id && !document.querySelector('.dc-view');  // not on screen yet = the tab is being opened
  if (!id) dc_ctxSet('list');  // 2.752.0 (#4887): all documents, to review, a saved view (a folder's list stays behind its document)
  if (!id && typeof ab_selKeep === 'function') ab_selKeep();  // 2.768.0 (#4888): another list ends the area's one selection
  if (DC.ws != null && DC.ws !== dc_ws()) p61b_dcReset();  // 2.66.1 (#1945): another workspace -> its data, open or not
  if (!DC.loading && ((!DC.docs && !DC.err) || (open && (Date.now() - (DC.at || 0) > 3000 || DC.atWs !== dc_ws())))) setTimeout(dc_load, 0);
  if (S.route.mod === 'docs' && (S.route.dv || null) !== (DC.dv || null)) { if (typeof dcv_routeSync === 'function') dcv_routeSync(); else if (typeof ld_later === 'function') ld_later('docviews'); }  // 2.579.0 (#4802): #docs/v/<id> = a saved view
  if (!id && S.route.mod === 'docs' && !S.route.dv && !DC.dv && !!DC.f.review !== !!S.route.review) { DC.f.review = !!S.route.review; if (!DC.loading) setTimeout(dc_load, 0); }  // 2.353.0 D (#2759): the saved filters Documents / To review of the file store (the view keeps the list's filter)
  if (id && typeof dcv_html === 'function') return dcv_html(id);
  if (DC.doc && typeof dcv_left === 'function') dcv_left();  // back from the view (the browser's Back): the list at the same place
  if (typeof dcv_restore === 'function') setTimeout(dcv_restore, 0);
  return `<div class="dc-wrap"><div class="dc-view">${typeof ab_phoneNav === 'function' ? ab_phoneNav() : '' /* 2.752.0 (#4887): phones: the spaces and the saved filters on top */}${dc_headHtml()}${dc_bodyHtml()}<div class="dc-drop" aria-hidden="true"><span>${ic('plus')} ${tr('Drop to add as documents')}</span></div></div></div>`;
}
// 2.752.0 (#4887): the documents' bar, also on top of a folder with recognition (fold = its node, abdocs.js abd_foldHtml): there
// "Add documents" and "Scan" put the files into that folder (the file store's upload and scan, ONE way), no "All | To review"
// (the sidebar has them; on phones the switch stays in the documents' own list, #4472)
function dc_headHtml(fold) {
  const active = dc_fEntries().length > 0;  // 2.122.0 B (#2294): the filters are drawn by dc_fltHtml / dc_fbarHtml
  const seg = fold || (typeof sbb_on === 'function' && sbb_on()) ? '' : `<div class="seg dc-seg" role="tablist"><button type="button" role="tab" data-dc="all" aria-selected="${!DC.f.review}" class="${DC.f.review ? '' : 'on'}">${tr('All')}</button><button type="button" role="tab" data-dc="review" aria-selected="${DC.f.review}" class="${DC.f.review ? 'on' : ''}">${tr('To review')}${DC.review ? ` <span class="dc-count">${DC.review}</span>` : ''}</button></div>`;
  const add = !fold ? `<label class="btn pri dc-up" title="${esc(tr('Add documents'))}">${ic('plus', 's')} <span>${tr('Add documents')}</span><input type="file" id="dc-file" multiple accept="application/pdf,image/*,.pdf,.txt,.xml,application/xml,text/xml" hidden></label>
      <button type="button" class="btn sm" data-dc="scan" title="${esc(tr('Scan'))}">${ic('camera', 's')} <span>${tr('Scan')}</span></button>`
    : fold.canAdd ? `<button type="button" class="btn pri dc-up" data-ab="upload" title="${esc(tr('Add documents'))}">${ic('plus', 's')} <span>${tr('Add documents')}</span></button><input type="file" id="ab-file" multiple hidden>
      <button type="button" class="btn sm" data-ab="scan" title="${esc(tr('Scan'))}">${ic('camera', 's')} <span>${tr('Scan')}</span></button>` : '';
  return `
    <div class="dc-bar">
      <div class="ctsearch">${ic('search', 's')}<input type="search" id="dc-q" value="${esc(DC.q)}" placeholder="${esc(fold ? tr('Search in this folder…') : tr('Search in the documents…'))}" aria-label="${esc(fold ? tr('Search in this folder') : tr('Search in the documents'))}" autocomplete="off"></div>
      ${seg}
      <button type="button" class="btn sm ${active ? 'on' : ''}" data-dc="more" aria-expanded="${!!DC.more}">${ic('filter', 's')} <span>${tr('Filter')}</span>${active ? ` <span class="dc-count">${dc_fEntries().length}</span>` : ''}</button>${dc_sortBtn()}${typeof dcv_barHtml === 'function' ? dcv_barHtml() : '' /* 2.579.0 (#4802) */}${typeof ts_barHtml === 'function' && !fold?.list ? ts_barHtml() : '' /* 2.583.0 (#4812); 2.769.0 (#5340): no card size above the list */}
      <span class="dc-acts2">${add}${dc_smvBtn()}<button type="button" class="iconbtn" data-dc="lists" aria-label="${esc(tr('Senders, types and fields'))}" title="${esc(tr('Senders, types and fields'))}">${ic('list')}</button><button type="button" class="iconbtn" data-dc="settings" aria-label="${esc(tr('Settings of the documents'))}" title="${esc(tr('Settings of the documents'))}">${ic('gear')}</button></span>
    </div>
    ${DC.more && !isMobile() ? `<div class="dc-fpanel dc-flt">${dc_fltHtml()}</div>` : ''}${dc_fbarHtml()}${dc_learnBar() /* 2.607.0 (#4872) */}
    ${DC.waiting ? `<p class="muted dc-wait" role="status">${ic('hourglass', 's')} ${esc(trn('{0} document is being recognised…', '{0} documents are being recognised…', DC.waiting))}</p>` : ''}`;
}
// the cards of the list; fold (a folder with recognition): its subfolders before them and its files that are no documents
// (yet) after them (abdocs.js), a document card with the file store's menu; a search / filter shows the documents found only
function dc_bodyHtml(fold) {
  const active = dc_fEntries().length > 0 || !!DC.q.trim();
  const card = fold?.card || dc_card;
  const more = DC.docs?.length && DC.total > DC.docs.length ? `<p class="muted dc-moreld"><button type="button" class="linkbtn" data-dc="loadmore">${esc(tr('Load more ({0} of {1})', DC.docs.length, DC.total))}</button></p>` /* 2.476.0 (#3935) */ : '';
  const grid = DC.docs?.length ? `<ul class="dc-grid${AB.selOn ? ' dc-selon' : ''}" aria-label="${esc(tr('Documents'))}">${DC.docs.map(d => card(d)).join('')}</ul>${more}` : '';
  if (DC.err) return `<div class="empty">${ic('alert')}<span>${esc(DC.err)}</span></div>`;
  if (fold) {
    const before = active ? '' : fold.before || '', after = active ? '' : fold.after || '';
    if (!DC.docs && !before && !after) return `<p class="muted lempty">${tr('Loading…')}</p>`;
    if (!DC.docs?.length && !before && !after) return `<div class="empty nempty dc-empty abempty">${ic('folder')}<span>${active ? tr('No documents found') : fold.canAdd ? tr('Drop files here or use “Upload”') : tr('This folder is empty')}</span></div>`;
    if (fold.list) return fold.list(before, after) + more + ab_selBar();  // 2.769.0 (#5340): a recognising folder as a list (abdocs.js abd_listHtml)
    return before + grid + after + ab_selBar();  // 2.768.0 (#4888): the area's one bar (ablage.js)
  }
  if (!DC.docs) return `<p class="muted lempty">${tr('Loading…')}</p>`;
  if (!DC.docs.length) return `<div class="empty nempty dc-empty">${ic('file')}<span>${active || DC.f.review ? tr('No documents found') : tr('Drop PDFs or photos of letters here, or add them with the button. Kalmido reads the text, finds date and amount and sorts them.')}</span>${/*html-ok*/ active || DC.f.review ? '' : hlp_linkHtml('files')/* 2.1086.0 (#5820): How it works */}</div>`;
  return grid + ab_selBar();
}
// 2.768.0 (#4888): the choosing mark of every card (documents, files, folders): ablage.js ab_selPick
const dc_selMark = d => { const on = AB.selOn && AB.sel.has(d.id); return `<button type="button" class="dc-selmark" data-dcchk="${d.id}" role="checkbox" aria-checked="${on}" aria-label="${esc(tr('Select') + ': ' + d.name)}" tabindex="${AB.selOn ? 0 : -1}">${on ? ic('check', 's') : ''}</button>`; };
// 2.583.0 (#4832): THE card of documents and of the file store: a document with its fields; o.file = a plain file or a folder of
// the file store ({thumb, meta, attrs, after}: its picture, size and date, the button's own attributes, the menu after it)
// 2.768.0 (#4888): a card the person may change can be dragged onto a folder (a mouse: the browser's drag; a finger: drag.js, data-abmv;
// ablage.js ab_dragSrc / the cards' drg_attach), never in the trash
function dc_dragAttr(d) {
  if (typeof ab_canWrite !== 'function' || (S.route.mod === 'ablage' && !S.route.nid && typeof ab_curSpace === 'function' && ab_curSpace() === 'trash')) return '';
  const n = typeof ab_item === 'function' ? ab_item(d.id) : null;
  return ab_canWrite(n?.role || d.role) ? (typeof rowd_touch === 'function' && rowd_touch() ? ' data-abmv="1"' : ' draggable="true"') : '';
}
function dc_card(d, o = {}) {
  const f = o.file;
  if (f) return `<li class="dc-card abcf${AB.sel.has(d.id) ? ' dc-on' : ''}" data-k="f${d.id}"${dc_dragAttr(d)}>${dc_selMark(d)}<button type="button" ${f.attrs} aria-label="${esc(d.name)}"><span class="dc-th">${f.thumb}</span><span class="dc-ct"><b class="dc-nm">${esc(d.name)}</b>${f.meta ? `<span class="dc-mt">${esc(f.meta)}</span>` : ''}</span></button>${f.after || ''}</li>`;
  const big = d.file || d.thumb_l ? dc_thumbUrl(d, true) : '';  // 2.583.0 (#4812): the sharp preview of big cards (tilesize.js)
  const thumb = d.thumb ? (typeof ts_img === 'function' ? ts_img(dc_thumbUrl(d), big) : `<img src="${esc(dc_thumbUrl(d))}" alt="" loading="lazy">`) : `<span class="dc-ph">${ic(dc_isPdf(d) ? 'file' : 'picture')}</span>`;
  const st = d.state === 'done' ? '' : `<span class="dc-st ${esc(d.state)}">${esc(tr(DC_STATE[d.state] || d.state))}</span>`;
  const meta = [d.date ? dc_day(d.date) : '', d.type?.name || '', d.asn ? `${DC.set?.asn_prefix || 'ASN'} ${d.asn}` : ''].filter(Boolean).map(esc).join(' · ');
  // 2.430.0 (#3582): a click always opens; the box (shown on hover, while choosing, or ticked) chooses, like Ctrl-/Shift-click and a long press
  const on = AB.selOn && AB.sel.has(d.id), cur = DC.lastId === d.id;  // 2.583.0 (#4835): the one looked at last; 2.768.0 (#4888): the area's one selection
  return `<li class="dc-card${d.review ? ' rev' : ''}${on ? ' dc-on' : ''}${cur ? ' dc-cur' : ''}" data-k="dc${d.id}"${dc_dragAttr(d)}>${dc_selMark(d)}<button type="button" data-dco="${d.id}" aria-label="${esc(dc_title(d))}">
    <span class="dc-th">${thumb}</span><span class="dc-ct"><b class="dc-nm" title="${esc(dc_title(d))}">${esc(dc_title(d))}</b>${d.sender?.name ? `<span class="dc-snd" title="${esc(d.sender.name)}">${esc(d.sender.name)}</span>` : '' /* 2.583.0 (#4870): always the title, the sender below it */}
    <span class="dc-mt">${meta}${d.amount ? ` · ${esc(dc_money(d.amount, d.currency))}` : ''}</span>
    ${d.tags.length ? `<span class="dc-tags">${d.tags.map(t => `<span class="dc-tag">${esc(t.name)}</span>`).join('')}</span>` : ''}
    ${d.shared ? `<span class="dc-shared abbadge" title="${esc(tr('Shared'))}" aria-label="${esc(tr('Shared'))}">${ic('users', 's')}</span>` : ''}${st}${d.review ? `<span class="dc-revdot">${tr('To review')}</span>` : ''}${d.split?.stack ? `<span class="dc-revdot dsp-dot">${tr('Stack - split?')}</span>` : '' /* 2.154.0 A (#1111) */}</span></button></li>`;
}

// ---- upload (button, dragging, the share sheet)
async function dc_upload(files, ws, source) {
  files = [...files].filter(f => f && f.size);
  if (!files.length) return [];
  const fd = new FormData();
  for (const f of files.slice(0, 50)) fd.append('files', f, f.name);
  fd.append('ws', ws || dc_upWs());
  if ((ws || dc_upWs()) === 'private') fd.append('sort', '1');  // 2.522.0 (#4433): the general input sorts (office / private; no office: nothing)
  if (source) fd.append('source', source);
  let j;
  try { j = await api('POST', '/api/docs', fd); } catch { return []; }
  for (const e of j.errors || []) toast(e);
  if (j.ids?.length) {
    const ids = j.ids;
    histToast(trn('{0} document added', '{0} documents added', ids.length), histAdd({label: trn('{0} document added', '{0} documents added', ids.length),
      undo: async () => { for (const id of ids) await api('DELETE', `/api/files/nodes/${id}`); dc_load(); return {}; },
      redo: async () => { for (const id of ids) await api('POST', `/api/files/nodes/${id}/restore`); dc_load(); return {}; }}));
  }
  const dup = (j.dups || [])[0];  // 2.146.0 B (#2452): the same file is not stored twice -- Open shows the one there
  if (dup) toast(j.dups.length === 1 ? tr('This file already exists: {0}', dup.name) : trn('{0} file already exists', '{0} files already exist', j.dups.length), () => dc_open(dup.id), 8000, tr('Open'));
  if (dc_listOn()) dc_load();
  return j.ids || [];
}
async function dc_shareFiles(files) {  // the share sheet: "File as document"
  const ids = await dc_upload(files, dc_upWs(), 'share');
  if (ids.length) location.hash = '#ablage/docs';  // 2.752.0 (#4887)
}

// ---- the document sheet
async function dc_open(id, o = {}) {
  // 2.683.0 (#5150): o.list = the ids of the documents shown where it was opened (the file store's cards): leafing goes through
  // them; 2.583.0: the view is #docs/<id> then, so the list counts while the view is open (dcv_left drops it)
  if (o.tab && typeof DVW === 'object') DVW.tab = o.tab;  // 2.768.0 (#4888): o.tab = the tab it opens on ('hist': "Details and history" of a file)
  if (o.list) DC.navSrc = {mod: 'docs', docs: o.list.map(x => ({id: +x}))};
  else if (S.route.mod !== 'docs' || !dc_hashId()) DC.navSrc = null;  // opened from the documents' list or a link: their list
  // 2.583.0 (#4835): a document opens as its own view #docs/<id> (docview.js) -- from the list, the file store (#4832), a link;
  // in the view another one takes its place (leafing: the address follows, Back still leads to the list). DC.opening = the
  // document being fetched (a later one wins)
  if (S.route.mod !== 'docs' || !dc_hashId()) { if (typeof dcv_go === 'function') dcv_go(id); return; }
  if (dc_hashId() !== id) { AB_FILEIDS.add(id); history.replaceState(history.state, '', `#ablage/${id}`); S.route.id = id; }  // 2.752.0 (#4887)
  DC.opening = id;
  const pre = dc_nbFresh(id);  // 2.736.0 (#5212): a neighbour fetched ahead opens without a request (its drawn body is taken over)
  let d = pre?.d;
  if (!d) try { d = await rawFetch('GET', `/api/docs/${id}`); } catch (x) {
    // 2.583.0 (#4832): no document: a plain file of the file store opens the same view (its fields only once recognised)
    const n = x?.status === 404 ? await rawFetch('GET', `/api/files/nodes/${id}`).catch(() => null) : null;
    // 2.583.0 (#4835 review): a locked (encrypted folder) or malware-locked file keeps its own way, not the view
    if (n?.kind === 'file' && !n.in_trash && (n.locked || n._enc || (typeof upLocked === 'function' && upLocked(n)))) { DC.opening = null; if (typeof DVW === 'object') DVW.par = n.parent_id || null; if (typeof dcv_close === 'function') dcv_close(); if (n.locked && typeof fslPrepNode === 'function') await fslPrepNode(n, true); if (typeof ab_openFile === 'function') ab_openFile(n, {raw: true}); return; }
    if (n?.kind === 'file' && !n.in_trash) d = dc_fileDoc(n);
    else { if (DC.opening === id) { DC.opening = null; if (!(typeof DVW === 'object' && DVW.gone?.has(id))) toast(x?.message || tr('Not found')); }  // #5478: removed here a moment ago: no toast over its Undo
      if (dc_hashId() === id && !DC.doc && typeof dcv_close === 'function') dcv_close(); return; }
  }
  // 2.603.0 (#4912): a redraw while the module still loads (docs.js runs before receipts.js ...) drew the sheet without its
  // later parts (receipt hints, suggestions): first the whole module
  if (typeof LD_P === 'object' && LD_P.docs) await LD_P.docs.catch(() => {});
  if (DC.opening !== id) return;
  const ws = d.org_id ? 'org:' + d.org_id : 'private';
  if (!d.file && (!DC.set || DC.set.ws !== ws)) { const s = pre?.set?.ws === ws ? pre.set : await api('GET', `/api/docs/settings?ws=${ws}`).catch(() => null); if (DC.opening !== id) return; DC.set = s; }
  DC.opening = null;
  if (dc_hashId() !== id) return;  // the view was left meanwhile
  DC.doc = d;
  if (typeof DVW === 'object') DVW.par = d.parent_id || null;  // 2.752.0 (#4887): Close without a way back (a link, a reload) leads into its folder
  if (pre && Date.now() - pre.at > DC_NBOLD) dc_nbRecheck(d);  // 2.736.0 (#5212): fetched a while ago: compared quietly behind the drawn body
  const ni = dc_navIdx(d); if (ni >= 0) { DC.navAt = ni; DC.navFor = d.id; }  // 2.521.0 (#4476): where it stands in the list (it may leave it: checked, filtered)
  else if (DC.navFor !== d.id) DC.navAt = null;  // 2.683.0 (#5150): never the place of the one before
  dc_navSeek();
  const v = $('.dv-view'); if (v) dc_mdDraw(v);
}
// ---- 2.476.0 (#3935): leafing through the open document -- always in the list as shown (filtered, sorted: DC.docs, like
// the arrow keys). "3 of 48" and two arrow buttons above the preview; a swipe sideways (2.882.0, #5557: anywhere in the view,
// not only on the preview) turns to the next / previous one, which glides in; past the last loaded one the next page loads, at the real end
// the page springs back. A preview enlarged with two fingers moves with one finger instead; normal size again = swipes.
// 2.882.0 (#5557): the swipe is the shared one of swipenav.js (as the task panel, detail.js dswInit) over the whole view:
// preview, head and fields (dc_swArea decides the exceptions); DCW keeps the zoom with two fingers and the pan of an enlarged
// preview. h = the swipe's handle (swn_attach); end / snap read it, zEnd = the end of a zoom / pan (its lift is no tap either)
const DCW = {sw: null, pz: null, zEnd: 0, h: null, get end() { return Math.max(this.zEnd, this.h?.at() || 0); }, get snap() { return !!this.h?.snapping(); }};
// 2.683.0 (#5150): the list it was opened from: a folder of the file store (its document cards as shown there, DC.navSrc from
// abdocs.js, the route stays on the file store) or the documents' list (DC.docs with its filter, sorting and next pages)
function dc_nav() {
  const v = DC.navSrc;
  if (v && S.route.mod === v.mod) return {docs: v.docs, total: v.docs.length, more: null};
  return S.route.mod === 'docs' && DC.docs ? {docs: DC.docs, total: DC.total, more: dc_more} : null;
}
const dc_navIdx = d => { const v = d && dc_nav(); return v ? v.docs.findIndex(x => x.id === d.id) : -1; };
const dc_navN = () => { const v = dc_nav(); return v ? Math.max(v.total || 0, v.docs.length) : 0; };
function dc_navHtml(d) {
  const i = dc_navIdx(d); if (i < 0) return '';
  const n = dc_navN();
  return `<div class="dc-nav" data-sig="${i}/${n}" role="group" aria-label="${esc(tr('{0} of {1}', i + 1, n))}"><button type="button" class="iconbtn dc-navb" data-dc="step:-1" aria-label="${esc(tr('Previous document'))}" title="${esc(tr('Previous document'))}"${i > 0 ? '' : ' disabled'}>${ic('left', 's')}</button><span class="dc-navn" aria-hidden="true">${esc(tr('{0} of {1}', i + 1, n))}</span><button type="button" class="iconbtn dc-navb" data-dc="step:1" aria-label="${esc(tr('Next document'))}" title="${esc(tr('Next document'))}"${i < n - 1 ? '' : ' disabled'}>${ic('right', 's')}</button></div>`;
}
function dc_navSync() {  // the list changed (loaded again, the next page): the counter of the open document follows
  dc_navSeek();
  const fi = dc_navIdx(DC.doc); if (fi >= 0) { DC.navAt = fi; DC.navFor = DC.doc.id; }  // 2.683.0 (#5150, review): found later, it may leave the list too
  if (typeof dcv_sync === 'function') dcv_sync();  // 2.583.0 (#4835): the counter and the strip of the view
}
// 2.683.0 (#5150): opened with an address (a link, a reload, a search hit) the document may stand further down the list
// than its loaded first page: the next pages follow until it is found (at most DC_SEEK pages per document) - then the
// counter, the arrows and the swipe are there; not in the list at all (another filter): none, as before
const DC_SEEK = 5;
function dc_navSeek() {
  const d = DC.doc;
  if (!d || S.route.mod !== 'docs' || DC.navSrc || !DC.docs || DC.loading || DC.moreP || DC.docs.length >= DC.total || dc_navIdx(d) >= 0) return;
  if (DC.navAt != null && DC.navFor === d.id) return;  // it stood in the list and left it (checked, filtered): no search
  const sk = d.id + '|' + DC.key;  // (review) per document and list: the same list loaded again (the poll) searches no more
  if (DC.seekFor !== sk) { DC.seekFor = sk; DC.seekN = 0; }
  if (DC.seekN >= DC_SEEK) return;
  DC.seekN++;
  dc_more().then(ok => { if (ok) dc_navSeek(); });  // the next page while it is still missing (its dc_draw already drew the counter)
}
// opens another document of the list in the view (the address follows, dc_open)
function dc_goTo(id, dir) {
  DC.slide = dir;
  return dc_open(id);
}
async function dc_step(dir, snapped) {  // true = turned; the real end springs back; 2.727.0 (#5202): snapped = the swipe already brought it in
  const cur = DC.opening ?? DC.doc?.id;
  let v = dc_nav();  // 2.683.0 (#5150): the list it was opened from (the file store's folder or the documents)
  if (!v) return false;
  let i = v.docs.findIndex(x => x.id === cur);
  if (i < 0) {  // 2.521.0 (#4476): the open one left the list ("To review": checked or accepted; a filter): on from where it stood
    const at = DC.doc?.id === cur && DC.navFor === cur && DC.navAt != null ? DC.navAt : -1, n = at < 0 ? null : v.docs[dir > 0 ? at : at - 1];
    if (at < 0) return false;
    if (!n) { dc_bounce(dir); return false; }
    await dc_goTo(n.id, snapped ? 0 : dir);
    return true;
  }
  if (dir > 0 && i + 1 >= v.docs.length && v.docs.length < v.total && v.more) { await v.more(); v = dc_nav(); i = v ? v.docs.findIndex(x => x.id === cur) : -1; }
  const n = i < 0 ? null : v.docs[i + dir];
  if (!n) { dc_bounce(dir); return false; }
  await dc_goTo(n.id, snapped ? 0 : dir);
  return true;
}
const dc_mdOpen = () => $('.dv-view');
function dc_anim(el, cls, ms) {
  if (!el) return;
  el.classList.remove('dc-in-n', 'dc-in-p', 'dc-bnc-n', 'dc-bnc-p');
  void el.offsetWidth;  // the class again starts the animation anew
  el.classList.add(cls);
  clearTimeout(el._dcAn); el._dcAn = setTimeout(() => el.classList.remove(cls), ms);
}
function dc_slideIn(md) { const dir = DC.slide; DC.slide = 0; dc_anim($('.dc-body', md), dir > 0 ? 'dc-in-n' : 'dc-in-p', 400); }
function dc_bounce(dir) { const b = $('.dc-body', dc_mdOpen()); if (b) { b.style.transform = ''; dc_anim(b, dir > 0 ? 'dc-bnc-n' : 'dc-bnc-p', 450); } }

// the zoom of the preview: k = the size (1 = normal), x / y = the shift of the picture inside its box
function dc_zoomSet(box, k, x, y) {
  const el = box?.firstElementChild;
  if (!box) return;
  if (!el || k <= 1.02) { k = 1; x = 0; y = 0; }
  else {
    const w = el.offsetWidth, h = el.offsetHeight, bw = box.clientWidth, bh = box.clientHeight, l = el.offsetLeft, t = el.offsetTop;
    // the enlarged picture keeps covering what it covered: no empty edge drawn into the box
    x = Math.min(-l, Math.max(bw - l - w * k, x)); if (w * k < bw) x = (bw - w * k) / 2 - l;
    y = Math.min(-t, Math.max(bh - t - h * k, y)); if (h * k < bh) y = -t;
  }
  box._z = {k, x, y};
  box.classList.toggle('dc-zoomed', k > 1);
  if (el) { el.style.transformOrigin = '0 0'; el.style.transform = k > 1 ? `translate(${Math.round(x)}px, ${Math.round(y)}px) scale(${k.toFixed(3)})` : ''; }
}
const dc_pvBox = t => t?.closest?.('.dv-view .dv-pages');  // 2.583.0 (#4835): the preview of the view
// two fingers on the preview zoom it; one finger moves the enlarged picture (2.882.0, #5557: the swipe itself is swipenav.js)
document.addEventListener('touchstart', e => {
  if (!e.touches) return;  // a plain Event("touchstart") (tests, synthetic taps) has no touch list
  const box = dc_pvBox(e.target);
  if (!box || DCW.snap) { DCW.sw = null; return; }  // 2.727.0 (#5202): not while the last one still snaps in
  const z = box._z || {k: 1, x: 0, y: 0};
  if (e.touches.length >= 2) {  // two fingers: enlarge / shrink the preview around their middle
    const [p, q] = e.touches, r = box.getBoundingClientRect(), el = box.firstElementChild;
    DCW.sw = null;
    DCW.pz = {box, l: el?.offsetLeft || 0, t: el?.offsetTop || 0, d0: Math.max(1, Math.hypot(p.clientX - q.clientX, p.clientY - q.clientY)), k0: z.k, x0: z.x, y0: z.y,
      mx: (p.clientX + q.clientX) / 2 - r.left, my: (p.clientY + q.clientY) / 2 - r.top};
    return;
  }
  const t = e.touches[0];
  if (DCW.pz || z.k <= 1) { DCW.sw = null; return; }  // normal size: one finger is the swipe of swipenav.js (dc_swArea)
  DCW.sw = {box, x0: t.clientX, y0: t.clientY, pan: true, z};
}, {passive: true});
document.addEventListener('touchmove', e => {
  const p = DCW.pz;
  if (p) {
    if (e.touches.length < 2) return;
    if (e.cancelable) e.preventDefault();
    const [a, b] = e.touches, r = p.box.getBoundingClientRect();
    const k = Math.min(5, Math.max(1, p.k0 * Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) / p.d0));
    const mx = (a.clientX + b.clientX) / 2 - r.left, my = (a.clientY + b.clientY) / 2 - r.top;
    // the point of the picture under the fingers' middle stays under it
    dc_zoomSet(p.box, k, mx - p.l - (p.mx - p.l - p.x0) * k / p.k0, my - p.t - (p.my - p.t - p.y0) * k / p.k0);
    return;
  }
  const s = DCW.sw; if (!s || e.touches.length !== 1) return;
  const t = e.touches[0], dx = t.clientX - s.x0, dy = t.clientY - s.y0;
  // enlarged: one finger moves the picture
  if (e.cancelable) e.preventDefault();
  s.moved = s.moved || Math.hypot(dx, dy) > 8;
  dc_zoomSet(s.box, s.z.k, s.z.x + dx, s.z.y + dy);
}, {passive: false});
// ---- 2.882.0 (#5557): the swipe over the whole document view with the shared helper (swipenav.js swn_attach, as the task
// panel): one finger sideways on the preview, the head or the fields leafs. Not: typing / marking in a field, a select, a part
// that scrolls sideways (the preview zoomed wider than its box, the tabs), marked text (swn_skip), an enlarged preview (one
// finger moves it), two fingers (the zoom), a start within 16 px of the screen's edge (the phone's Back), a dialog on top.
// The body of the document is the frame that stays (inside): its parts glide, the neighbours lie inside it (dc_swPeek).
function dc_swArea(t) {
  if (!t?.closest || $('.modal') || $('#pop:not(.hidden)') || DCW.pz) return null;
  const md = t.closest('.dv-view'); if (!md || t.closest('.swn-nb, .dc-nb, .dpg')) return null;  // 2.959.0 (#4805): + the page strip (a finger drags its pages)
  const body = /** @type {HTMLElement|null} */ (md.querySelector(':scope > .dc-body'));
  if (!body || body.dataset.id !== String(DC.doc?.id) || dc_navIdx(DC.doc) < 0) return null;  // it left the list: the arrows still lead on
  if ((dc_pvBox(t)?._z?.k || 1) > 1) return null;  // enlarged: one finger moves the picture
  return typeof swn_skip === 'function' && swn_skip(t, md) ? null : body;
}
function dc_swCan(dir) {
  const v = dc_nav(), i = dc_navIdx(DC.doc); if (!v || i < 0) return false;
  return dir > 0 ? !!v.docs[i + 1] || v.docs.length < v.total : i > 0;  // past the loaded ones the next page loads (dc_step)
}
// the neighbour beside the open one: drawn ahead whole (2.736.0, #5212: the real body with all its fields) or a placeholder
// (title, type, date, its small picture; an empty sheet while the next page is not loaded yet)
function dc_swPeek(dir) {
  const v = dc_nav(), i = dc_navIdx(DC.doc); if (!v || i < 0) return null;
  const x = v.docs[i + dir], e = x && dc_nbFresh(x.id);
  if (e?.el?.firstChild) { e.el.classList.remove('dc-nb-n', 'dc-nb-p'); return {el: e.el}; }
  const nb = document.createElement('div');
  nb.className = 'dc-nb'; nb.setAttribute('aria-hidden', 'true');
  nb.innerHTML = x ? dc_nbHtml(x) : '<div class="dc-nbv"></div>';
  return {el: nb};
}
// a body drawn ahead that was not turned to waits on outside the page (docview.js dcv_nbPark); a placeholder goes with its frame
function dc_swBack(el) { if (/** @type {any} */ (el)._dcnb && typeof dcv_nbPark === 'function') dcv_nbPark(el); }
function dc_swInit() {
  if (DCW.h) return;
  // lazy-ok-begin: runs only once swipenav.js is in (the typeof / loadModule below)
  if (typeof swn_attach === 'function') DCW.h = swn_attach(document, {area: dc_swArea, can: dc_swCan, go: dir => dc_step(dir, true), peek: dc_swPeek, back: dc_swBack, inside: true, busy: () => !!DCW.pz});
  // lazy-ok-end
  else if (!dc_swInit.wait && typeof loadModule === 'function') { dc_swInit.wait = true; loadModule('swipenav').then(() => { dc_swInit.wait = false; dc_swInit(); }, () => { dc_swInit.wait = false; }); }
}
// ---- 2.727.0 (#5202): leafing like turning a page. While the finger swipes, the previous / next document of the list lies
// left / right of the open one as a placeholder (title, type, date, its small picture - fetched ahead when the document was
// drawn - or an empty sheet) inside .dc-body, so all three glide together over the whole width. Let go far enough: the new one
// snaps fully into place and only then its content loads (dc_step, no glide-in afterwards); short of it: all springs back.
// prefers-reduced-motion: no snapping animation, it changes at once. At the real end the short spring back stays (dc_bounce).
function dc_nbThumb(x) {
  if (!x) return '';
  if (x.thumb) return `/api/docs/${x.id}/thumb?v=${encodeURIComponent(x.updated_at || '')}`;
  return x.thumb === undefined ? $(`[data-dco="${x.id}"] img`)?.getAttribute('src') || '' : '';  // the file store's cards: only {id}, their picture
}
function dc_nbHtml(x) {
  const u = dc_nbThumb(x), meta = [x.type?.name, x.date ? dc_day(x.date) : ''].filter(Boolean).join(' · ');
  return `<div class="lhdr dc-nbh"><h3>${esc(x.name || x.sender?.name || '')}</h3></div>${meta ? `<p class="dc-nbm muted">${esc(meta)}</p>` : ''}<div class="dc-nbv">${u ? `<img src="${esc(u)}" alt="">` : ''}</div>`;  // sprung-ok: fixed box, docs.css .dc-nbv (aspect-ratio, max-height, #5227)
}
// the new document is drawn into the body that still stands where its neighbour snapped in: its parts back in place at once,
// the neighbours laid in by the swipe (swipenav.js, 2.882.0 #5557) out of it (a body drawn ahead waits on, dc_swBack)
function dc_nbLand(body) {
  for (const w of body.querySelectorAll(':scope > .swn-nb')) { const x = w.firstElementChild; if (x) dc_swBack(/** @type {HTMLElement} */ (x)); w.remove(); }
  for (const x of body.children) {
    const p = /** @type {HTMLElement} */ (x); if (!p.style.transform) continue;
    p.style.transition = 'none'; p.style.transform = ''; void p.offsetWidth; p.style.transition = '';
  }
}
// the small pictures of the two neighbours are fetched while the open one is read (the browser keeps them; at most a few)
function dc_nbPre(d) {
  const v = dc_nav(), i = dc_navIdx(d); if (!v || i < 0) return;
  const pre = DCW.pre || (DCW.pre = new Map());
  for (const x of [v.docs[i + 1], v.docs[i - 1]]) {
    const u = dc_nbThumb(x); if (!u || pre.has(u)) continue;
    const im = new Image(); im.decoding = 'async'; im.src = u; pre.set(u, im);
    if (pre.size > 6) pre.delete(pre.keys().next().value);
  }
  dc_nbAhead(v, i);
}
// ---- 2.736.0 (#5212): leafing without a seam. On a touch screen (where the swipe is) the two direct neighbours of the open
// document are fetched whole (data, the settings of their workspace) and drawn by docview.js (dcv_nbDraw: the same lines as
// the open one, the preview at its final size) - DCW.nb: id -> {id, d, set, at, ctrl, el, pdf}. A swipe lays that body beside
// the open one, dc_open / dcv_draw take it over as it is after the snap: no request, no picture that moves, no text that comes
// later. Only the direct neighbours: whatever leaves that place is stopped (AbortController) and freed. Older than DC_NBOLD:
// compared quietly after the swap (dc_nbRecheck), drawn anew only when something changed; older than DC_NBMAX: fetched anew.
const DC_NBOLD = 20000, DC_NBMAX = 600000;
// a neighbour fetched ahead that may stand for the document: its data are there, not too old, and the list knows no newer state
function dc_nbFresh(id) {
  const e = DCW.nb?.get(id); if (!e?.d || Date.now() - e.at > DC_NBMAX) return null;
  const x = dc_nav()?.docs.find(y => y.id === id);
  return x?.updated_at && e.d.updated_at && x.updated_at !== e.d.updated_at ? null : e;
}
const dc_nbOn = () => typeof dcv_nbDraw === 'function' && (navigator.maxTouchPoints > 0 || isTouch());
function dc_nbAhead(v, i) {
  if (!dc_nbOn()) return;
  const want = [v.docs[i + 1], v.docs[i - 1]].filter(x => x?.id), nb = DCW.nb || (DCW.nb = new Map());
  for (const [id, e] of nb) if (!want.some(x => x.id === id)) { dcv_nbFree(e); nb.delete(id); }
  for (const x of want) {
    const e = nb.get(x.id);
    if (e && (!e.d || dc_nbFresh(x.id))) continue;  // on its way or still good
    if (e) { dcv_nbFree(e); nb.delete(x.id); }
    dc_nbFetch(x.id);
  }
}
function dc_nbStop() { for (const e of DCW.nb?.values() || []) dcv_nbFree(e); DCW.nb?.clear(); $('.dv-nbhold')?.remove(); }  // the view left: nothing more ahead
async function dc_nbFetch(id) {
  const ctrl = new AbortController(), e = {id, ctrl, at: Date.now(), d: null, set: null, el: null, pdf: null};
  DCW.nb.set(id, e);
  const gone = () => ctrl.signal.aborted || DCW.nb.get(id) !== e;
  try {
    await DC_Q.get(id)?.catch(() => {});  // a change of this one still on its way (it was open just now) first
    const d = await rawFetch('GET', `/api/docs/${id}`); if (gone() || !d?.id) { if (!gone()) DCW.nb.delete(id); return; }
    const ws = d.org_id ? 'org:' + d.org_id : 'private';
    const set = DC.set?.ws === ws ? DC.set : await rawFetch('GET', `/api/docs/settings?ws=${ws}`).catch(() => null); if (gone()) return;
    if (typeof LD_P === 'object' && LD_P.docs) await LD_P.docs.catch(() => {});  // every part of the module draws along (as dc_open)
    if (gone() || !dc_mdOpen()) return;
    e.d = d; e.set = set; e.at = Date.now();
    dcv_nbDraw(e);
  } catch { if (DCW.nb.get(id) === e) DCW.nb.delete(id); }  // a plain file of the file store (404) or offline: the placeholder stays
}
// fetched a while ago: the server's state quietly behind the drawn body; drawn anew (a morph) only when it differs
async function dc_nbRecheck(d) {
  let x; try { x = await rawFetch('GET', `/api/docs/${d.id}`); } catch { return; }
  if (DC.doc !== d || !x?.id || JSON.stringify(x) === JSON.stringify(d)) return;  // changed here meanwhile: its own save goes on
  DC.doc = x; dc_mdDraw(dc_mdOpen());
}
function dc_touchEnd(e) {
  if (DCW.pz) {
    if (e.touches?.length >= 2) return;
    const b = DCW.pz.box; DCW.pz = null; DCW.zEnd = Date.now();
    if ((b._z?.k || 1) <= 1.05) dc_zoomSet(b, 1, 0, 0);
    if (e.touches?.length === 1) DCW.sw = null;  // the finger left on the picture does not swipe
    return;
  }
  const s = DCW.sw; DCW.sw = null;
  if (s?.moved) DCW.zEnd = Date.now();  // the enlarged picture moved: its lift is no tap
}
document.addEventListener('touchend', dc_touchEnd, {passive: true});
document.addEventListener('touchcancel', dc_touchEnd, {passive: true});

function dc_auto(d, f) {
  const by = d.auto?.[f];
  return by ? `<button type="button" class="dc-auto" data-dc="edit:${esc(f)}" title="${esc(tr(DC_BY[by] || by))}">${tr('automatic')}</button>` : '';
}
// 2.583.0 (#4835): the document is drawn by the view (docview.js dcv_draw: head, strip, the fields in tabs, the preview of
// every page); the action row (2.497.0 A, #4046) is its head, the preview (2.430.0, #3582) its right column
function dc_mdDraw(md) { if (md && DC.doc && typeof dcv_draw === 'function') dcv_draw(md); }
// 2.591.0 B (#4863): a code on the document carries an archive number another document has already (docs/web.py asn_taken_view)
function dc_asnTakenHtml(d) {
  const t = d.asn_taken; if (!t || d.asn) return '';
  const no = `${DC.set?.asn_prefix || 'ASN'} ${+t.asn}`, o = t.doc;
  const who = !o ? esc(tr('a document you cannot open')) : o.trash ? `<b>${esc(o.name)}</b> ${esc(tr('(in the trash)'))}` : `<a href="#docs/${+o.id}">${esc(o.name)}</a>`;
  return `<p class="dc-asnt muted" role="note">${ic('info', 's')} ${esc(tr('Archive number {0} found, already used by', no))} ${who}</p>`;
}
function dc_cfRow(d, f, ro) {  // 2.153.0 (#2179): one custom field of the document
  const id = `dc-cf${f.id}`, v = f.value ?? '', a = `data-dcf="${f.id}"`;
  const input = f.type === 'checkbox' ? `<input type="checkbox" id="${id}" ${a} ${v === '1' ? 'checked' : ''} ${ro}>`
    : f.type === 'select' ? `<select id="${id}" ${a} ${ro}><option value=""></option>${(f.options || []).map(o => `<option value="${esc(o.id)}" ${o.id === v ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>`
    : f.type === 'date' ? dateIn(id, v, {label: f.name, ro: !!ro, attrs: a})
    : f.type === 'money' ? `<input id="${id}" ${a} inputmode="decimal" value="${esc(v ? v.replace(/^-?[\d.]+/, x => numField(x, 2, 2)) : '')}" placeholder="${esc(curMoney(0, 'EUR'))}" ${ro}>`
    : f.type === 'number' ? `<input id="${id}" ${a} inputmode="decimal" value="${esc(v ? numField(v) : '')}" ${ro}>`
    : f.type === 'longtext' ? `<textarea id="${id}" ${a} rows="3" maxlength="10000" ${ro}>${esc(v)}</textarea>`  // 2.635.0 (#4807 c)
    : f.type === 'documentlink' ? dc_cfLinksHtml(f, id, ro)
    : f.type === 'url' ? `<span class="dc-amt"><input type="url" id="${id}" ${a} value="${esc(v)}" placeholder="https://" ${ro}>${v && /^https?:\/\//i.test(v) ? `<a class="iconbtn" href="${esc(v)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(tr('Open'))}">${ic('link')}</a>` : ''}</span>`
    : `<input id="${id}" ${a} value="${esc(v)}" maxlength="1000" ${ro}>`;
  return `<div class="row dc-f dc-cf"><label for="${id}">${esc(f.name)}</label>${input}${dc_auto(d, 'cf' + f.id)}</div>`;
}
// 2.635.0 (#4807 c): a field linking documents of the same workspace: each one opens with a click (#docs/<id>); the server
// shows only the ones this person sees (f.links) and checks every new one; "Link a document" searches by name (datalist)
function dc_cfLinksHtml(f, id, ro) {
  const ls = (f.links || []).map(l => `<span class="dc-cfl"><a href="#docs/${+l.id}">${ic('file', 's')} ${esc(l.name)}</a>${ro ? '' : `<button type="button" class="iconbtn" data-dc="cflx:${+f.id}:${+l.id}" aria-label="${esc(tr('Remove the link to {0}', l.name))}" title="${esc(tr('Remove the link to {0}', l.name))}">${ic('x', 's')}</button>`}</span>`).join('');
  const more = f.hidden ? `<span class="muted">${esc(tr('+{0} you cannot open', f.hidden))}</span>` : '';
  const add = ro ? '' : `<input id="${id}" data-dcfl="${+f.id}" list="${id}-l" autocomplete="off" placeholder="${esc(tr('Link a document…'))}"><datalist id="${id}-l"></datalist>`;
  return `<span class="dc-cflinks">${ls}${more}${add}</span>`;
}
async function dc_cfLinkFind(el) {  // the documents whose name / text has the words typed, as choices "Name · #id"
  const q = el.value.trim(); if (q.length < 2 || /#\d+$/.test(q)) return;
  let j; try { j = await api('GET', `/api/docs?facets=0&limit=10&q=${encodeURIComponent(q)}${DC.doc?.org_id ? `&ws=org:${DC.doc.org_id}` : '&ws=private'}`); } catch { return; }
  const dl = document.getElementById(el.getAttribute('list') || ''); if (!dl || !el.isConnected) return;
  dl.innerHTML = (j.docs || []).filter(x => x.id !== DC.doc?.id).map(x => `<option value="${esc(`${x.name} · #${x.id}`)}">`).join('');
}
const dc_cfLinkFindLater = debounce(dc_cfLinkFind, 250);  // #4807: debounce instead of a clearTimeout / setTimeout pair (perf budget)
document.addEventListener('input', e => {
  const el = e.target.closest?.('[data-dcfl]'); if (!el) return;
  dc_cfLinkFindLater(el);
});
function dc_val(f, el) {
  const v = el.value.trim();
  if (f === 'tags') return v ? v.split(',').map(x => x.trim()).filter(Boolean) : [];
  if (f === 'amount') return v ? numBody(v) : '';  // 2.263.0 (#2976)
  if (f === 'folder') return v ? +v : '';
  if (f === 'asn') return v ? +v : null;
  return v;
}
function dc_cur(d, f, only) {  // the value of a field as the server takes it back (for the undo)
  if (f === 'sender' || f === 'type') return d[f]?.name || '';
  if (f === 'tags') return d.tags.map(t => t.name);
  if (f === 'folder') return d.folder?.id || '';
  if (f === 'asn') return d.asn || null;
  if (f === 'title') return d.title_own === false ? '' : d.title ?? '';  // 2.750.0 (#4876): a title taken from the file name comes back as none
  if (f === 'custom_fields') return Object.fromEntries((d.custom_fields || []).filter(x => !only || String(x.id) in only).map(x => [x.id, x.value ?? null]));  // only the changed ones (their marks stay)
  return d[f] ?? '';
}
// 2.559.0 (#4659): the open document with the new values as the sheet shows them, before the answer (sender / type / tags by name,
// a known folder, custom fields); what the server alone knows (a new folder, the next archive number) waits for its answer
function dc_localDoc(d, body) {
  const x = {...d}, set = DC.set || {};
  for (const [k, v] of Object.entries(body)) {
    if (k === 'sender' || k === 'type') x[k] = v ? (d[k]?.name === v ? d[k] : {name: v}) : null;
    else if (k === 'tags') x.tags = (v || []).map(n => (d.tags || []).find(t => t.name === n) || (set.tags || []).find(t => t.name === n) || {name: n});
    else if (k === 'folder') { if (v === '' || v == null) x.folder = null; else if (typeof v === 'number') { const f = (set.folders || []).find(y => y.id === v); if (f) x.folder = f; } }
    else if (k === 'custom_fields') x.custom_fields = (d.custom_fields || []).map(f => String(f.id) in v ? {...f, value: v[f.id]} : f);
    else if (k === 'title') { x.title_own = !!String(v || '').trim(); x.title = x.title_own ? String(v).trim() : dc_title({name: x.name}); }  // 2.750.0 (#4876)
    else if (k === 'name') { x.name = v; if (x.title_own === false) x.title = dc_title({name: v}); }  // the file name; a title from it follows
    else if (!(k === 'asn' && v === 'next')) x[k] = v;
  }
  return x;
}
// 2.559.0 (#4659): the changes of a document still on their way (id -> bodies): an earlier answer keeps the later ones on top
const DC_PEND = new Map();
const DC_VER = new Map(), DC_Q = new Map();  // 2.564.0 D (#4701): id -> the version the sheet saves against / its chain of changes
// the newest version this sheet knows: its own last answer or the document as the sheet shows it (opened, undo, accept);
// ISO texts compare in time order (".123" after the same second without)
// 2.570.0 (#4770): the version is edited_at (people's changes; a recognition run moves updated_at only)
const dc_ver = id => { const a = DC_VER.get(id) || '', b = DC.doc?.id === id ? DC.doc.edited_at || '' : ''; return a > b ? a : b; };
async function dc_patch(id, body, label) {
  const before = DC.doc && DC.doc.id === id ? Object.fromEntries(Object.keys(body).map(k => [k, dc_cur(DC.doc, k, body[k])])) : null;
  const d0 = DC.doc?.id === id ? DC.doc : null, pend = DC_PEND.get(id) || [];
  DC_PEND.set(id, pend); pend.push(body);
  const done = () => { pend.splice(pend.indexOf(body), 1); if (!pend.length && DC_PEND.get(id) === pend) DC_PEND.delete(id); };
  if (d0) { DC.doc = dc_localDoc(d0, body); dc_mdDraw($('.dc-md')); }  // at once, the request behind it
  let d;
  // 2.564.0 D (#4701): one change after the other, each against the version the sheet has (the last answer): saved meantime
  // elsewhere = 409, api() says why and the sheet shows the current document instead of overwriting it
  const run = (DC_Q.get(id) || Promise.resolve()).catch(() => {}).then(async () => {
    const v = dc_ver(id), x = await api('PATCH', `/api/docs/${id}`, v ? {...body, expect_updated_at: v} : body);
    if (x?.edited_at) DC_VER.set(id, x.edited_at);
    return x;
  });
  DC_Q.set(id, run);
  try { d = await run; } catch (x) {  // the fields of this change as they were (the others stay)
    done();
    const cur = x?.status === 409 ? x.data?.doc : null;
    if (cur) { DC_VER.set(id, cur.edited_at); if (DC.doc?.id === id) DC.doc = pend.reduce(dc_localDoc, cur); }
    else if (d0 && DC.doc?.id === id) DC.doc = {...DC.doc, ...Object.fromEntries(Object.keys(body).map(k => [k, d0[k]]))};
    dc_mdDraw($('.dc-md')); return;
  }
  done();
  if (DC.doc?.id === id) { DC.doc = pend.reduce(dc_localDoc, d); dc_mdDraw($('.dc-md')); }
  if (before) {
    // 2.570.0 (#4770): only the changed keys, against the version the step before left (edited_at: a recognition run in the
    // background is no change; core.js undoStep): changed in another session since -> said, their change stays
    let ver = d?.edited_at || '';
    const put = (v, from) => () => undoStep(`/api/docs/${id}`, v, ver, {now: from, label, then: x => { ver = x?.edited_at || ver; if (x?.id && DC.doc?.id === id) { DC.doc = x; dc_mdDraw($('.dc-md')); } }}).finally(dc_load);
    const he = histAdd({label, undo: put(before, body), redo: put(body, before)});
    histToast(label, he);
    if (typeof dcv_saved === 'function' && DC.doc?.id === id) dcv_saved(he);  // 2.583.0 (#4835): "Saved (Undo)" in the view's head
  }
  dc_load();
}
async function dc_mdChange(e) {
  const lk = e.target.closest('[data-dcfl]');
  if (lk && DC.doc) {  // 2.635.0 (#4807 c): a document chosen to link
    const m = /#(\d+)$/.exec(lk.value.trim()); if (!m) return;
    const f = (DC.doc.custom_fields || []).find(x => x.id === +lk.dataset.dcfl); if (!f) return;
    const ids = [...(f.links || []).map(l => l.id), +m[1]];
    return dc_patch(DC.doc.id, {custom_fields: {[f.id]: [...new Set(ids)].join(',')}}, tr('Edited {0}', DC.doc.name));
  }
  const cf = e.target.closest('[data-dcf]');
  if (cf && DC.doc) {  // 2.153.0 (#2179)
    const v = cf.type === 'checkbox' ? cf.checked : cf.value.trim();
    return dc_patch(DC.doc.id, {custom_fields: {[cf.dataset.dcf]: v === '' ? null : v}}, tr('Edited {0}', DC.doc.name));
  }
  const el = e.target.closest('[data-dcp]'); if (!el || !DC.doc) return;
  const f = el.dataset.dcp, id = DC.doc.id;
  if (f === 'folder' && (el.value === 'new' || el.value === 'newsub')) {  // 2.199.0 B (#2742): also a subfolder of the current one (a path)
    const sub = el.value === 'newsub' && DC.doc.folder?.path;
    const name = (await askPrompt(sub ? tr('New subfolder in {0}', DC.doc.folder.name) : tr('New folder'), '', {ok: tr('Create')}) || '').trim().replace(/\//g, '-');
    if (!name) { el.value = DC.doc.folder?.id || ''; return; }
    await dc_patch(id, {folder: sub ? `${DC.doc.folder.path} / ${name}` : name}, tr('Moved {0} to {1}', DC.doc.name, name));
    if (typeof ab_ptStale === 'function') ab_ptStale();  // 2.752.0 (#4887): the one tree of the panel shows the new folder
    DC.set = await api('GET', `/api/docs/settings?ws=${DC.doc.org_id ? 'org:' + DC.doc.org_id : 'private'}`).catch(() => DC.set);
    dc_mdDraw($('.dc-md'));
    return;
  }
  if (f === 'currency') return dc_patch(id, {currency: el.value.trim().toUpperCase()}, tr('Edited {0}', DC.doc.name));
  const label = {sender: tr('Sender of {0} changed', DC.doc.name), type: tr('Type of {0} changed', DC.doc.name), tags: tr('Tags of {0} changed', DC.doc.name),
    folder: tr('Folder of {0} changed', DC.doc.name), asn: tr('Archive number of {0}', DC.doc.name),
    title: tr('Title of {0} changed', dc_title(DC.doc)), name: tr('File name of {0} changed', dc_title(DC.doc))}[f] || tr('Edited {0}', DC.doc.name);  // 2.750.0 (#4876)
  await dc_patch(id, {[f]: dc_val(f, el)}, label);
}
async function dc_c168Refresh(id) {  // 2.210 C (#2761): re-read the open document and the list ("shared" mark)
  try { const d = await api('GET', `/api/docs/${id}`); if (DC.doc?.id === id) { DC.doc = d; dc_mdDraw($('.dc-md')); } const i = DC.docs.findIndex(x => x.id === id); if (i >= 0) { DC.docs[i].shared = d.shared; if (typeof dc_draw === 'function') dc_draw(); } } catch { /* shown */ }
}
// 2.554.0 A (#4469): "New task" from the button "Task…" (docsplit.js menu) and the plain button
async function dc_newTask(d, md) {
  const x = await api('POST', `/api/docs/${d.id}/task`).catch(() => null); if (!x) return;
  DC.doc = {...d, task_id: x.task_id}; dc_mdDraw(md);
  if (typeof load === 'function') load();
  histToast(tr('Task created: {0}', x.title), histAdd({label: tr('Task created: {0}', x.title),
    undo: async () => { await api('DELETE', `/api/tasks/${x.task_id}`); await api('DELETE', `/api/docs/${d.id}/task`); if (DC.doc?.id === d.id) { DC.doc.task_id = null; dc_mdDraw($('.dc-md')); } return {}; },
    redo: async () => { const y = await api('POST', `/api/docs/${d.id}/task`); x.task_id = y.task_id; return {}; }}));
}
async function dc_mdClick(e) {
  const b = e.target.closest('[data-dc]'); if (!b || !DC.doc) return;
  const d = DC.doc, a = b.dataset.dc, md = b.closest('.dc-md');
  if (a === 'close') { md.remove(); return; }
  if (a === 'share' || a === 'xlink') {  // 2.210 C (#2761): the file store's dialogs, refresh the card afterwards
    if (a === 'xlink') { xl_newDlg(d.id, () => dc_c168Refresh(d.id)); return; }
    await ab_share(d.id);
    const dlg = $('.abshdlg'); if (dlg) onRemove(dlg, () => dc_c168Refresh(d.id));
    return;
  }
  if (a === 'space') { if (await dc_smvMove(new Map([[d.id, d.org_id || null]]), `“${d.name}”`)) md.remove(); return; }  // 2.96.0 A (#1941)
  if (a.startsWith('step:')) { dc_step(+a.slice(5)); return; }  // 2.476.0 (#3935): the arrow buttons above the preview
  if (a.startsWith('cflx:')) {  // 2.635.0 (#4807 c): one link of a link field removed (the ones this person cannot see stay)
    const [fid, lid] = a.slice(5).split(':').map(Number), f = (d.custom_fields || []).find(x => x.id === fid); if (!f) return;
    const rest = (f.links || []).map(l => l.id).filter(x => x !== lid);
    dc_patch(d.id, {custom_fields: {[fid]: rest.length ? rest.join(',') : null}}, tr('Edited {0}', d.name));
    return;
  }
  if (a === 'view') {
    if (Date.now() - (DCW.end || 0) < 700) return;  // 2.476.0 (#3935): the end of a swipe / zoom on the preview is no tap
    if (d.einvoice?.source === 'xml') { window.open(`/api/docs/${d.id}/einvoice`, '_blank', 'noopener'); return; }  // 2.146.0 A (#2451)
    if (typeof dcv_full === 'function' && dcv_full(d)) return;  // 2.521.0 (#4476): the full screen leafs through the list (2.583.0: docview.js)
    if (dc_isPdf(d) && typeof pdfView === 'function') pdfView({url: dc_fileUrl(d), name: d.name, size: d.size, dlUrl: dc_fileUrl(d, true)});
    else if (/^image\//.test(d.mime) && typeof attLightbox === 'function') attLightbox('d', [{id: 'd', name: d.name, size: d.size}], (a, dl) => dc_fileUrl(d, dl));  // 2.537.0 (#4574)
    else if (typeof dv_is === 'function' && dv_is(d)) dpvOpen({url: `/api/files/nodes/${encodeURIComponent(d.id)}/preview`, name: d.name, size: d.size, dlUrl: dc_fileUrl(d, true)});  // 2.635.0 (#4807): Word / Excel / OpenDocument
    else window.open(dc_fileUrl(d), '_blank', 'noopener');
    return;
  }
  if (a === 'actsmore') { dcv_actsMenu(b, d, d.role !== 'view'); return; }  // 2.1011.0 (#5688): the shared menu (docview.js)
  if (a.startsWith('showopt:')) {  // 2.497.0 A (#4046): the chip of one optional field (due date / amount) opens it
    const f = a.slice(8);
    if (DC.optOpen?.id !== d.id) DC.optOpen = {id: d.id};
    DC.optOpen[f] = true;
    const row = md.querySelector(`.dc-opt[data-opt="${f}"]`); if (row) row.hidden = false;
    b.remove();
    const ob = md.querySelector('.dc-optbtn'); if (ob && !ob.children.length) ob.hidden = true;
    row?.querySelector('input')?.focus();
    return;
  }
  if (a === 'nametitle') {  // 2.750.0 (#4876): the file name from the title, its ending stays (the server keeps it unique in its folder)
    const nm = (dc_title(d).replace(/[\\/]/g, '-') + dc_fileExt(d.name)).trim();
    if (nm && nm !== d.name) await dc_patch(d.id, {name: nm}, tr('File name of {0} changed', dc_title(d)));
    return;
  }
  if (a === 'asnnext') { await dc_patch(d.id, {asn: 'next'}, tr('Archive number of {0}', d.name)); return; }
  if (a === 'titlesug') {  // 2.783.0 (#4882): the area's title pattern once (with undo: the title before and whether it was set by hand)
    const x = await api('GET', `/api/docs/${d.id}/title-suggest`).catch(() => null); if (!x) return;
    if (!x.title) { toast(tr('Nothing to suggest yet: sender, type and date are empty')); return; }
    if (x.title === dc_title(d) && !d.title_manual) { toast(tr('The title already follows the pattern')); return; }
    await dc_patch(d.id, {title: x.title, title_manual: false}, tr('Title of {0} suggested', dc_title(d)));
    return;
  }
  if (a.startsWith('edit:')) { $(`#dc-${a.slice(5)}`, md)?.focus(); return; }
  if (a === 'redo') {
    // 2.273.0 C (#3047): values set by hand stay -- say so before and after the new run
    const names = {date: tr('Date'), due: tr('Due'), amount: tr('Amount'), currency: tr('Currency')};
    const hand = (d.hand || []).map(f => names[f]).filter(Boolean).join(', ');
    if (hand && !await askConfirm(tr('Recognise again?'), tr('Values set by hand stay: {0}', hand), {ok: tr('Recognise again')})) return;
    const r = await api('POST', `/api/docs/${d.id}/redo`).catch(() => null);
    DC.doc = r || d; dc_mdDraw(md); dc_load();
    if (!r) return;
    const redraw = x => { if (DC.doc?.id === d.id) { DC.doc = x; if (md.isConnected) dc_mdDraw(md); } dc_load(); return {}; };
    // 2.363.3 (#3134): the run can be taken back (server: the values from before, kept 24 h)
    histToast(r.kept?.length ? tr('Not replaced, set by hand: {0}', r.kept.map(f => names[f]).filter(Boolean).join(', ')) : tr('Recognising again'),
      histAdd({label: tr('Recognising again'),
        undo: async () => redraw(await api('POST', `/api/docs/${d.id}/redo/undo`)),
        redo: async () => redraw(await api('POST', `/api/docs/${d.id}/redo`))}));
    return;
  }
  if (a === 'take' || a.startsWith('take:') || a === 'takeall') {
    const feats = a === 'takeall' ? null : [a.slice(5)];
    const before = Object.fromEntries((feats || Object.keys(d.suggest || {})).map(k => [k, dc_cur(d, k)]));
    const x = await api('POST', `/api/docs/${d.id}/accept`, feats ? {features: feats} : {}).catch(() => null); if (!x) return;
    DC.doc = x; dc_mdDraw(md); dc_load();
    histToast(tr('Suggestion accepted'), histAdd({label: tr('Suggestion accepted'),
      undo: async () => { await api('PATCH', `/api/docs/${d.id}`, before); await api('POST', `/api/docs/${d.id}/review`, {done: false}); dc_load(); return {}; },
      redo: async () => { await api('POST', `/api/docs/${d.id}/accept`, feats ? {features: feats} : {}); dc_load(); return {}; }}));
    return;
  }
  if (a === 'checked') {
    const ds = DC.docs || [], ci = ds.findIndex(x => x.id === d.id), nx = ci < 0 ? null : ds[ci + 1] || ds[ci - 1], nxDir = nx && ds[ci + 1] ? 1 : -1;
    // 2.559.0 (#4659): checked at once (the sheet, the card, the counter); in "To review" the next document follows at once, the
    // request runs behind it; an error marks it "To review" again (api() said why)
    const it = ds[ci], rv = DC.review;
    if (it) it.review = false;
    if (DC.review > 0) DC.review--;
    DC.doc = {...d, review: false}; dc_mdDraw(md); dc_draw();
    // 2.476.0 (#3935): in "To review" the next document follows at once (the one before at the end, none left = back to the list)
    if (DC.f.review) { if (nx && S.route.mod === 'docs') dc_goTo(nx.id, nxDir); else md.remove(); }
    const x = await api('POST', `/api/docs/${d.id}/review`, {done: true}).catch(() => null);
    if (!x) {
      if (it) it.review = d.review; DC.review = rv;
      if (DC.doc?.id === d.id) { DC.doc = d; dc_mdDraw($('.dc-md')); }
      dc_draw(); return;
    }
    if (DC.doc?.id === d.id) { DC.doc = {...DC.doc, ...x, text: d.text}; dc_mdDraw($('.dc-md')); }
    dc_load();
    histToast(tr('Marked as checked'), histAdd({label: tr('Marked as checked'),
      undo: async () => { await api('POST', `/api/docs/${d.id}/review`, {done: false}); dc_load(); return {}; },
      redo: async () => { await api('POST', `/api/docs/${d.id}/review`, {done: true}); dc_load(); return {}; }}));
    return;
  }
  if (a === 'task') { await dc_newTask(d, md); return; }
  if (a === 'del') {  // 2.768.0 (#4888): the area's one way into the trash (ablage.js abm_trash: POST /api/files/trash, ONE undo)
    if (await abm_trash([{...ab_selInfo(d), role: d.role || 'edit'}])) md.remove();
  }
}

// ---- settings of a workspace: level per feature, archive numbers, rules, the lists and custom fields
// 2.365.2 B (#2789): the settings live in Settings > Documents (dcs_paneHtml / dcs_draw, the workspace shown in the sidebar),
// the inboxes (folder, folder watcher, mail) in Settings > Integrations (docscan.js); the module keeps the dialog for its
// lists (senders, types, tags) and custom fields. dc_sDraw draws both, the handlers below serve both.
async function dc_settings(ws = dc_upWs()) {
  let s; try { s = await api('GET', `/api/docs/settings?ws=${encodeURIComponent(ws)}`); } catch { return; }
  DC.set = s;
  const md = modal('<div class="dc-sbody"></div>');
  md.classList.add('dc-smd');
  md.addEventListener('click', dc_sClick);
  md.addEventListener('change', dc_sChange);
  dc_sDraw(md);
}
function dcs_paneHtml() {
  if (!feat('docs')) return '';
  return `<div id="s-dcs" class="dc-smd dcs-pane"><p class="muted" data-dcsp="head">${tr('Loading…')}</p>
    <h4 id="s-dcs-auto-h">${tr('Sorting automatically')}</h4><div data-dcsp="auto"></div>
    <h4 id="s-dcs-asn-h">${tr('Archive numbers')}</h4><div data-dcsp="asn"></div>
    <h4 id="s-dcs-rules-h">${tr('Rules')}</h4><div data-dcsp="rules"></div>
    <h4 id="s-dcs-lists-h">${tr('Senders, types and tags')}</h4>
    <div class="row"><span class="muted">${tr('Senders, document types, tags and custom fields are kept in Documents.')}</span><button type="button" class="btn sm" data-dcs="lists">${ic('list', 's')} ${tr('Open in Documents')}</button></div>
    <h4 id="s-dcs-in-h">${tr('Inboxes')}</h4>
    <div class="row"><span class="muted">${tr('The folder of the file store, the folder watcher, scan inboxes and the e-mail address: Settings > Integrations.')}</span><button type="button" class="btn sm" data-dcs="go-integr">${ic('link', 's')} ${tr('Open Integrations')}</button></div>
    <div data-dcsp="pl"></div></div>`;
}
async function dcs_draw(md) {
  const box = $('.dcs-pane', md); if (!box) return;
  if (!box._on) { box._on = true; box.addEventListener('click', dc_sClick); box.addEventListener('change', dc_sChange); }
  let s; try { s = await api('GET', `/api/docs/settings?ws=${encodeURIComponent(dc_upWs())}`); } catch { $('[data-dcsp="head"]', box).textContent = ''; return; }
  if (!box.isConnected) return;
  DC.set = s; dc_sDraw(box);
}
function dc_wsName(ws) {
  if (ws === 'private') return tr('Private|workspace');  // 2.582.0 (#4831): same name as in the file store
  const w = (S.me?.workspaces || []).find(x => 'org:' + x.id === ws);
  return w ? w.name : ws;
}
function dc_sDraw(md) {
  const s = DC.set; if (!s || !md) return;
  const can = s.can_manage, dis = can ? '' : 'disabled';
  const rule = r => {
    const sets = [r.sender && `${tr('Sender')}: ${r.sender}`, r.type && `${tr('Document type')}: ${r.type}`, r.tags?.length && `${tr('Tags')}: ${r.tags.join(', ')}`, r.folder && `${tr('Folder')}: ${r.folder}`].filter(Boolean);
    return `<li class="dc-rule"><span><span class="muted">${esc(tr(DC_KINDS.find(k => k[0] === r.kind)?.[1] || r.kind))}</span> <b>${esc(r.match)}</b>${r.case ? ` <span class="muted">(${tr('case-sensitive')})</span>` : ''} → ${esc(sets.join(' · '))}</span>${can ? `<button type="button" class="iconbtn" data-dcs="rdel:${r.id}" aria-label="${esc(tr('Delete rule'))}">${ic('trash')}</button>` : ''}</li>`;
  };
  const head = `${esc(dc_wsName(s.ws))}${can ? '' : ` · ${tr('Only admins of this workspace can change this')}`}`;
  if (md.classList.contains('dcs-pane')) {  // Settings > Documents: the parts into their places under the headings
    const P = {head,
      auto: `<p class="shint">${tr('Per feature: rules first, then what Kalmido learnt from your corrections. Sure matches are set directly, unsure ones wait in “To review”. “Left to an agent”: a connected agent with access may fill it in.')}</p>
        ${DC_FEATS.map(([f, n]) => `<div class="row"><label for="dcs-l-${f}">${tr(n)}</label><select id="dcs-l-${f}" data-dcl="${f}" ${dis}>${DC_LEVELS.map(([v, l]) => `<option value="${v}" ${s.levels[f] === v ? 'selected' : ''}>${tr(l)}</option>`).join('')}</select></div>`).join('')}
        ${s.ocr_missing?.length ? `<p class="muted">${esc(tr('Text recognition is missing: {0}', s.ocr_missing.join(', ')))}</p>` : ''}${dcs_ocrHtml(s, dis)}${/*html-ok*/ dcs_titleHtml(s, dis)}${/*html-ok*/ typeof po_setHtml === 'function' ? po_setHtml(s, dis) : '' /* 2.892.0 (#4873) */}`,
      asn: `<div class="row"><label for="dcs-asn">${tr('Prefix of the archive numbers')}</label><input id="dcs-asn" data-dcs="asnprefix" value="${esc(s.asn_prefix || 'ASN')}" maxlength="10" autocomplete="off" ${dis}></div>
        <p class="muted">${esc(tr('Next free number: {0}. A QR code or text like {1} on a scan fills it in.', s.asn_next, `${s.asn_prefix || 'ASN'}${String(s.asn_next).padStart(5, '0')}`))}</p>
        <p class="muted">${esc(tr('A stack scan with several codes can be split into documents; a separator sheet between two letters splits there too.'))} <a href="/api/docs/split-sheet.pdf" target="_blank" rel="noopener">${tr('Separator sheet to print (PDF)')}</a></p>${'' /* 2.154.0 A (#1111) */}`,
      rules: `${s.rules.length ? `<ul class="dc-rules">${s.rules.map(r => typeof dfl_ruleHtml === 'function' ? dfl_ruleHtml(r, can) : rule(r)).join('')}</ul>`  /* 2.581.0 (#4803): flows (docflows.js) */ : `<p class="muted">${tr('No rules yet. When you correct a document, Kalmido learns from it.')}</p>`}
    ${can && typeof dfl_formHtml === 'function' ? dfl_formHtml(s) : can ? `<details class="dc-radd"><summary>${tr('New rule')}</summary>
      <div class="row"><label for="dcr-kind">${tr('If the document')}</label><select id="dcr-kind">${DC_KINDS.map(([v, l]) => `<option value="${v}">${tr(l)}</option>`).join('')}</select></div>
      <div class="row"><label for="dcr-match">${tr('Words or pattern')}</label><input id="dcr-match" maxlength="200" autocomplete="off"></div>
      <div class="row"><label for="dcr-sender">${tr('then sender')}</label><input id="dcr-sender" maxlength="120" list="dcr-sl" autocomplete="off"><datalist id="dcr-sl">${s.senders.map(x => `<option value="${esc(x.name)}">`).join('')}</datalist></div>
      <div class="row"><label for="dcr-type">${tr('then document type')}</label><input id="dcr-type" maxlength="120" list="dcr-tl" autocomplete="off"><datalist id="dcr-tl">${s.types.map(x => `<option value="${esc(x.name)}">`).join('')}</datalist></div>
      <div class="row"><label for="dcr-tags">${tr('then tags')}</label><input id="dcr-tags" maxlength="300" placeholder="${esc(tr('comma-separated'))}" autocomplete="off"></div>
      <div class="row"><label for="dcr-folder">${tr('then folder')}</label><input id="dcr-folder" maxlength="120" list="dcr-fl" autocomplete="off"><datalist id="dcr-fl">${s.folders.map(x => `<option value="${esc(x.name)}">`).join('')}</datalist></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-dcs="radd">${tr('Add rule')}</button></div></details>` : ''}`,
      pl: typeof pl_slot === 'function' ? pl_slot(s) : ''};  // 2.48.0 (#1152): Paperless-ngx (paperless.js), the progress of an import
    for (const [k, h] of Object.entries(P)) { const el = $(`[data-dcsp="${k}"]`, md); if (el) el.innerHTML = h; }
    return;
  }
  $('.dc-sbody', md).innerHTML = `<div class="lhdr"><h3>${tr('Senders, types and fields')}</h3><span class="spacer"></span><button class="iconbtn" data-dcs="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="muted">${head}</p>
    ${can ? `<h4>${tr('Senders, types and tags')}</h4>${[['sender', 'senders', N_('Senders')], ['type', 'types', N_('Document types')], ['tag', 'tags', N_('Tags')]].map(([k, key, n]) =>
      `<details class="dc-lbls"><summary>${tr(n)} (${(s[key] || []).length})</summary>${(s[key] || []).length ? `<ul class="dc-rules">${s[key].map(x => `<li class="dc-rule"><span>${esc(x.name)}</span><span class="ms-phacts">
        <button type="button" class="iconbtn" data-dcs="lren:${k}:${x.id}" aria-label="${esc(tr('Rename'))}" title="${esc(tr('Rename'))}">${ic('edit')}</button>
        <button type="button" class="iconbtn" data-dcs="ldel:${k}:${x.id}" aria-label="${esc(tr('Delete {0}', x.name))}" title="${esc(tr('Delete {0}', x.name))}">${ic('trash')}</button>${/*html-ok*/ ms_dots(':scope > button', x.name) /* 2.1151.0 C (#3835): one "…" on a phone */}</span></li>`).join('')}</ul>` : ''}</details>`).join('')}` : ''}
    ${can ? dc_cfSettings(s) : ''}
    <div class="row dcs-to"><span class="muted">${tr('Sorting automatically, archive numbers and rules: Settings > Documents.')}</span><button type="button" class="btn sm" data-dcs="go-set">${ic('gear', 's')} ${tr('Settings of the documents')}</button></div>`;
}
// 2.783.0 (#4882): the title pattern of the area and "Title automatically" (a title set by hand is never replaced)
function dcs_titleHtml(s, dis) {
  if (!s.title_pattern) return '';
  return `<fieldset class="dcs-title"><legend>${esc(tr('Title of new documents'))}</legend>
    <label class="dcs-ocrc"><input type="checkbox" id="dcs-tauto" data-dcs="tauto" ${s.title_auto ? 'checked' : ''} ${/*html-ok*/ dis}> ${esc(tr('Title automatically'))}</label>
    <div class="row"><label for="dcs-tpat">${esc(tr('Title pattern'))}</label><input id="dcs-tpat" data-dcs="tpat" value="${esc(s.title_pattern)}" maxlength="120" autocomplete="off" placeholder="${esc(s.title_pattern_default || '')}" ${/*html-ok*/ dis}></div>
    <p class="shint">${esc(tr('Placeholders: {0} sender, {1} type, {2} date (DD.MM.YYYY). An empty part goes with its separator. Recognition, rules and “Apply what was learned” set the title from it; a title typed by hand stays.', '{Absender}', '{Typ}', '{Datum}'))}</p></fieldset>`;
}
// 2.635.0 (#4807 b): the languages of the text recognition of this workspace (the installed ones, deu+eng by default)
function dcs_ocrHtml(s, dis) {
  const o = s.ocr_langs; if (!o || !(o.choices || []).length) return '';
  return `<fieldset class="dcs-ocr"><legend>${esc(tr('Languages of the text recognition'))}</legend>
    <p class="shint">${esc(tr('Scans and photos are read in these languages (at most {0}; fewer read faster).', o.max))}${o.custom ? '' : ` ${esc(tr('Default: {0}.', o.default.join(', ')))}`}</p>
    <div class="dcs-ocrl">${o.choices.map(x => `<label class="dcs-ocrc"><input type="checkbox" data-dco="${esc(x.code)}" ${o.chosen.includes(x.code) ? 'checked' : ''} ${dis}> ${esc(x.name)}</label>`).join('')}</div></fieldset>`;
}
function dc_cfSettings(s) {  // 2.153.0 (#2179): the custom fields of the workspace (nothing preset)
  const fs = s.fields || [];
  return `<h4>${tr('Custom fields')}</h4>
    <p class="muted">${tr('Extra fields every document of this workspace can have, e.g. a contract or client number.')}</p>
    ${fs.length ? `<ul class="dc-rules">${fs.map(f => `<li class="dc-rule"><span>${esc(f.name)} <span class="muted">${esc(tr(DC_CFTYPES.find(t => t[0] === f.type)?.[1] || f.type))}${f.type === 'select' ? `: ${esc((f.options || []).map(o => o.name).join(', '))}` : ''}</span></span><span class="ms-phacts">
      ${f.type === 'select' ? `<button type="button" class="iconbtn" data-dcs="fopt:${f.id}" aria-label="${esc(tr('Options'))}" title="${esc(tr('Options'))}">${ic('list')}</button>` : ''}
      <button type="button" class="iconbtn" data-dcs="fren:${f.id}" aria-label="${esc(tr('Rename'))}" title="${esc(tr('Rename'))}">${ic('edit')}</button>
      <button type="button" class="iconbtn" data-dcs="fdel:${f.id}" aria-label="${esc(tr('Delete {0}', f.name))}" title="${esc(tr('Delete {0}', f.name))}">${ic('trash')}</button>${/*html-ok*/ ms_dots(':scope > button', f.name) /* 2.1151.0 C (#3835): one "…" on a phone */}</span></li>`).join('')}</ul>` : ''}
    <details class="dc-radd dc-fadd"><summary>${tr('New field')}</summary>
      <div class="row"><label for="dcf-name">${tr('Name')}</label><input id="dcf-name" maxlength="60" autocomplete="off"></div>
      <div class="row"><label for="dcf-type">${tr('Type')}</label><select id="dcf-type" data-dcs="ftype">${DC_CFTYPES.map(([v, l]) => `<option value="${v}">${tr(l)}</option>`).join('')}</select></div>
      <div class="row dcf-opts" hidden><label for="dcf-opts">${tr('Options')}</label><input id="dcf-opts" maxlength="600" placeholder="${esc(tr('comma-separated'))}" autocomplete="off"></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-dcs="fadd">${tr('Add field')}</button></div></details>`;
}
async function dc_cfAct(a, s, md) {  // 2.153.0 (#2179): add / rename / options / delete a custom field
  const draw = j => { if (DC.set && j?.fields) { DC.set.fields = j.fields; dc_sDraw($('.dc-smd')); } if (DC.doc && typeof dc_open === 'function') dc_open(DC.doc.id); };
  if (a === 'fadd') {
    const b = {ws: s.ws, name: ($('#dcf-name', md)?.value || '').trim(), type: $('#dcf-type', md)?.value || 'text', options: ($('#dcf-opts', md)?.value || '')};
    if (!b.name) { $('#dcf-name', md)?.focus(); return; }
    let j; try { j = await api('POST', '/api/docs/fields', b); } catch { return; }
    draw(j);
    const st = {id: j.id};
    histToast(tr('Field added: {0}', b.name), histAdd({label: tr('Field added: {0}', b.name), sett: true,
      undo: async () => { draw(await api('DELETE', `/api/docs/fields/${st.id}`)); return {}; },
      redo: async () => { const x = await api('POST', '/api/docs/fields', b); st.id = x.id; draw(x); return {}; }}));
    return;
  }
  const id = +a.split(':')[1], f = (s.fields || []).find(x => x.id === id); if (!f) return;
  if (a.startsWith('fren:')) {
    const name = ((await askPrompt(tr('Rename'), f.name, {ok: tr('Rename')})) || '').trim();
    if (!name || name === f.name) return;
    const put = v => async () => { draw(await api('PATCH', `/api/docs/fields/${id}`, {name: v})); return {}; };
    try { await put(name)(); } catch { return; }
    histToast(tr('Renamed: {0}', name), histAdd({label: tr('Renamed: {0}', name), sett: true, undo: put(f.name), redo: put(name)}));
    return;
  }
  if (a.startsWith('fopt:')) {
    const old = (f.options || []).map(o => o.name).join(', ');
    const txt = ((await askPrompt(tr('Options'), old, {ok: tr('Save')})) || '').trim();
    if (!txt || txt === old) return;
    const opts = txt.split(',').map(x => x.trim()).filter(Boolean).map(n => ({name: n, id: (f.options || []).find(o => o.name.toLowerCase() === n.toLowerCase())?.id}));
    const gone = (f.options || []).filter(o => !opts.some(x => x.id === o.id));
    if (gone.length && !await askConfirm(tr('Remove options?'), tr('Documents with {0} lose this value.', gone.map(o => o.name).join(', ')), {ok: tr('Save'), danger: true})) return;
    try { draw(await api('PATCH', `/api/docs/fields/${id}`, {options: opts})); } catch { /* the server said why */ }
    return;
  }
  if (a.startsWith('fdel:')) {
    if (!await askConfirm(tr('Delete {0}', f.name), tr('The field and its values on every document of this workspace are deleted.'), {ok: tr('Delete'), danger: true})) return;
    try { draw(await api('DELETE', `/api/docs/fields/${id}`)); } catch { return; }
    toast(tr('Deleted: {0}', f.name));
  }
}
async function dc_sChange(e) {
  if (typeof dfl_change === 'function' && dfl_change(e)) return;  // 2.581.0 (#4803): the parts of the flow form
  const s = DC.set, md = e.target.closest('.dc-smd');
  const l = e.target.closest('[data-dcl]');
  if (l) {
    const f = l.dataset.dcl, from = s.levels[f], to = l.value;
    const put = v => async () => { DC.set = await api('PUT', '/api/docs/settings', {ws: s.ws, levels: {[f]: v}}); dc_sDraw($('.dc-smd')); return {}; };
    await put(to)();
    histToast(tr('Changed setting: {0}', tr(DC_FEATS.find(x => x[0] === f)[1])), histAdd({label: tr('Changed setting: {0}', tr(DC_FEATS.find(x => x[0] === f)[1])), sett: true, undo: put(from), redo: put(to)}));
    return;
  }
  if (e.target.matches('[data-dcs="asnprefix"]')) {
    const from = s.asn_prefix, to = e.target.value.trim();
    const put = v => async () => { DC.set = await api('PUT', '/api/docs/settings', {ws: s.ws, asn_prefix: v}); dc_sDraw($('.dc-smd')); return {}; };
    try { await put(to)(); } catch { e.target.value = from; return; }
    histToast(tr('Changed setting: {0}', tr('Prefix of the archive numbers')), histAdd({label: tr('Changed setting: {0}', tr('Prefix of the archive numbers')), sett: true, undo: put(from), redo: put(to)}));
    return;
  }
  if (e.target.matches('[data-dcs="tpat"], [data-dcs="tauto"]')) {  // 2.783.0 (#4882): the title pattern / "Title automatically"
    const k = e.target.dataset.dcs === 'tpat' ? 'title_pattern' : 'title_auto', from = s[k];
    const to = k === 'title_auto' ? e.target.checked : e.target.value.trim() || s.title_pattern_default;
    const pane = e.target.closest('.dcs-pane');
    const put = v => async () => { DC.set = await api('PUT', '/api/docs/settings', {ws: s.ws, [k]: v}); dc_sDraw(pane || $('.dc-smd')); return {}; };
    try { await put(to)(); } catch { if (k === 'title_auto') e.target.checked = from; else e.target.value = from; return; }
    const lb = tr('Changed setting: {0}', tr(k === 'title_auto' ? 'Title automatically' : 'Title pattern'));
    histToast(lb, histAdd({label: lb, sett: true, undo: put(from), redo: put(to)}));
    return;
  }
  if (e.target.matches('[data-dcs="ftype"]')) { const o = md.querySelector('.dcf-opts'); if (o) o.hidden = e.target.value !== 'select'; return; }  // 2.153.0 (#2179)
  if (e.target.matches('[data-dco]')) {  // 2.635.0 (#4807 b): the text recognition languages (none ticked = the default)
    const box = e.target.closest('.dcs-ocr'), o = s.ocr_langs;
    const from = o.custom ? o.chosen : [], to = [...box.querySelectorAll('[data-dco]:checked')].map(x => x.dataset.dco);
    const val = to.length && to.join('+') !== o.default.join('+') ? to : [];
    const put = v => async () => { DC.set = await api('PUT', '/api/docs/settings', {ws: s.ws, ocr_langs: v}); dc_sDraw(box.closest('.dcs-pane') || $('.dc-smd')); return {}; };
    try { await put(val)(); } catch { e.target.checked = !e.target.checked; return; }
    histToast(tr('Changed setting: {0}', tr('Languages of the text recognition')), histAdd({label: tr('Changed setting: {0}', tr('Languages of the text recognition')), sett: true, undo: put(from), redo: put(val)}));
  }
}
async function dc_sClick(e) {
  const b = e.target.closest('[data-dcs]'); if (!b || b.matches('input')) return;
  const s = DC.set, md = b.closest('.dc-smd'), a = b.dataset.dcs;
  if (a === 'close') { md.remove(); return; }
  // 2.365.2 B (#2789): the ways between Settings > Documents, Integrations and the lists of the module
  if (a === 'go-set') { md.remove(); settingsModal('docs'); return; }
  if (a === 'lists' || a === 'go-integr') { const sm = md.closest('.modal'); if (sm) modalClose(sm); if (a === 'lists') { go('ablage/docs'); dc_settings(s?.ws); } else settingsModal('scans'); return; }
  if (a === 'fadd' || /^f(ren|opt|del):/.test(a)) return dc_cfAct(a, s, md);  // 2.153.0 (#2179)
  if (a.startsWith('redit:') && typeof dfl_edit === 'function') { dfl_edit(md, s, +a.slice(6)); return; }  // 2.635.0 (#4856): edit a flow
  if (a === 'radd' && typeof dfl_save === 'function' && b.closest('.dfl-add')?.dataset.edit) { await dfl_save(md, s, +b.closest('.dfl-add').dataset.edit); return; }
  if (a === 'radd') {
    const v = id => ($(`#${id}`, md)?.value || '').trim();
    const r = typeof dfl_collect === 'function' ? dfl_collect(md, s) : {ws: s.ws, kind: v('dcr-kind'), match: v('dcr-match'), sender: v('dcr-sender'), type: v('dcr-type'), tags: v('dcr-tags'), folder: v('dcr-folder')};  // 2.581.0 (#4803)
    let j; try { j = await api('POST', '/api/docs/rules', r); } catch { return; }
    s.rules = j.rules; dc_sDraw(md);
    if (j.hook_secret && typeof dfl_secret === 'function') dfl_secret(j.hook_secret);  // 2.581.0 (#4803): shown once
    histToast(tr('Rule added'), histAdd({label: tr('Rule added'), sett: true,
      undo: async () => { const x = await api('DELETE', `/api/docs/rules/${j.id}`); if (DC.set) { DC.set.rules = x.rules; dc_sDraw($('.dc-smd')); } return {}; },
      redo: async () => { const x = await api('POST', '/api/docs/rules', r); j.id = x.id; if (DC.set) { DC.set.rules = x.rules; dc_sDraw($('.dc-smd')); } return {}; }}));
    return;
  }
  if (a.startsWith('rtog:')) {  // 2.581.0 (#4803): a flow off / on again
    const id = +a.slice(5), r = s.rules.find(x => x.id === id); if (!r) return;
    // 2.635.0 (#4856): sends the flow's current version (expect_updated_at): 409 = changed elsewhere -> the list as it is now
    const put = off => async () => {
      const cur = (DC.set?.rules || s.rules).find(x => x.id === id) || r;
      try { const x = await api('PATCH', `/api/docs/rules/${id}`, {...cur, id: undefined, updated_at: undefined, expect_updated_at: cur.updated_at || undefined, off}); s.rules = x.rules; if (DC.set) DC.set.rules = x.rules; dc_sDraw($('.dc-smd') || md); } catch (e) { if (e?.status === 409 && e.data?.rules) { s.rules = e.data.rules; if (DC.set) DC.set.rules = e.data.rules; dc_sDraw($('.dc-smd') || md); } throw e; }
      return {};
    };
    try { await put(!r.off)(); } catch { return; }
    histToast(r.off ? tr('Switched on') : tr('Switched off'), histAdd({label: r.off ? tr('Switched on') : tr('Switched off'), sett: true, undo: put(!!r.off), redo: put(!r.off)}));
    return;
  }
  if (a.startsWith('rdel:')) {
    const id = +a.slice(5), r = s.rules.find(x => x.id === id);
    let j; try { j = await api('DELETE', `/api/docs/rules/${id}`); } catch { return; }
    s.rules = j.rules; dc_sDraw(md);
    if (r) histToast(tr('Rule deleted'), histAdd({label: tr('Rule deleted'), sett: true,
      undo: async () => { const x = await api('POST', '/api/docs/rules', {...r, ws: s.ws}); r.id = x.id; if (DC.set) { DC.set.rules = x.rules; dc_sDraw($('.dc-smd')); } return {}; },
      redo: async () => { const x = await api('DELETE', `/api/docs/rules/${r.id}`); if (DC.set) { DC.set.rules = x.rules; dc_sDraw($('.dc-smd')); } return {}; }}));
    return;
  }
  if (a.startsWith('lren:') || a.startsWith('ldel:')) {
    const [, kind, sid] = a.split(':'), id = +sid, key = {sender: 'senders', type: 'types', tag: 'tags'}[kind];
    const old = (s[key] || []).find(x => x.id === id)?.name || '';
    const reload = async () => { DC.set = await api('GET', `/api/docs/settings?ws=${encodeURIComponent(s.ws)}`).catch(() => DC.set); dc_sDraw($('.dc-smd')); DC.facets = null; dc_load(); };
    if (a.startsWith('lren:')) {
      const name = ((await askPrompt(tr('Rename'), old, {ok: tr('Rename')})) || '').trim();
      if (!name || name === old) return;
      const put = v => async () => { await api('PATCH', `/api/docs/labels/${kind}/${id}`, {name: v}); await reload(); return {}; };
      try { await put(name)(); } catch { return; }
      histToast(tr('Renamed: {0}', name), histAdd({label: tr('Renamed: {0}', name), sett: true, undo: put(old), redo: put(name)}));
      return;
    }
    let j; try { j = await api('DELETE', `/api/docs/labels/${kind}/${id}`); } catch { return; }
    await reload();
    const st = {id};
    histToast(tr('Deleted: {0}', old), histAdd({label: tr('Deleted: {0}', old), sett: true,
      undo: async () => { const x = await api('POST', `/api/docs/labels/${kind}`, {ws: s.ws, name: j.name || old, ids: j.ids || []}); st.id = x.id; await reload(); return {}; },
      redo: async () => { await api('DELETE', `/api/docs/labels/${kind}/${st.id}`); await reload(); return {}; }}));
    return;
  }
}

// ---- events of the view (delegated once)
let dc_qTimer = null;
document.addEventListener('click', e => {
  const v = e.target.closest('.dc-view'); if (!v) return;
  // 2.768.0 (#4888): the box, Ctrl/Cmd-click, Shift-click and a tap while choosing are the area's one selection (ablage.js, before this)
  const o = e.target.closest('[data-dco]');
  if (o) { dc_open(+o.dataset.dco, v.classList.contains('dc-infold') && typeof abd_navIds === 'function' ? {list: abd_navIds()} : {}); return; }  // 2.583.0 (#4835): the document view; 2.752.0 (#4887): in a folder it leafs through the folder's cards
  const b = e.target.closest('[data-dc]'); if (!b) return;
  const a = b.dataset.dc;
  if (a === 'scan') { abm_scanOpen({docs: true}); return; }  // 2.112.1 A (#2058): photographed pages -> one PDF -> a document
  if (a === 'settings') settingsModal('docs');  // 2.365.2 B (#2789): Settings > Documents
  else if (a === 'lists') dc_settings();
  else if (a === 'all' || a === 'review') { const rv = a === 'review'; if (S.route.mod === 'docs' && !!S.route.review !== rv) { go(rv ? 'ablage/review' : 'ablage/docs'); return; } DC.f.review = rv; dc_load(); dc_draw(); }  // 2.353.0 D (#2759): the route = the saved filter (viewDocs takes it over and loads)
  else if (a === 'sort') dc_sortMenu(b);  // 2.428.0 (#3579)
  else if (a === 'more') { if (isMobile()) dc_fSheet(); else { DC.more = !DC.more; dc_draw(); } }  // 2.122.0 B (#2294): phones: a sheet
  else if (a === 'clear') { DC.f = {...dc_f0(), review: DC.f.review}; DC.q = ''; dc_load(); }
  else if (a === 'loadmore') dc_more();  // 2.476.0 (#3935)
  else if (a === 'learnall') dc_learnReview();  // 2.607.0 (#4872)
});
document.addEventListener('change', e => {
  if (!e.target.closest('.dc-view')) return;
  if (e.target.id === 'dc-file') { const fs = [...e.target.files]; e.target.value = ''; dc_upload(fs); return; }
  const f = e.target.closest('[data-dcf]');
  if (f) { DC.f[f.dataset.dcf] = f.value; dc_load(); }
});
document.addEventListener('input', e => {
  if (e.target.id !== 'dc-q') return;
  DC.q = e.target.value;
  clearTimeout(dc_qTimer); dc_qTimer = setTimeout(dc_load, 300);
});
// dragging files onto the view adds them as documents (the drop zone shows while dragging)
const dc_hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files') && !kn_has(e);  // 2.750.0 (#4879): a drag begun in Kalmido never uploads
// 2.752.0 (#4887): a folder's documents (.dc-infold) take a drop the file store's way (ablage.js: ab_upload into the folder)
const dc_dropV = e => { const v = e.target.closest?.('.dc-view'); return v && !v.classList.contains('dc-infold') ? v : null; };
document.addEventListener('dragenter', e => { const v = dc_dropV(e); if (!v || !dc_hasFiles(e)) return; DC.drag++; v.classList.add('dragging'); });
document.addEventListener('dragleave', e => { const v = dc_dropV(e); if (!v) return; DC.drag = Math.max(0, DC.drag - 1); if (!DC.drag) v.classList.remove('dragging'); });
document.addEventListener('dragover', e => { if (dc_dropV(e) && dc_hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
document.addEventListener('drop', e => {
  const v = dc_dropV(e); if (!v || !dc_hasFiles(e)) return;
  e.preventDefault(); e.stopPropagation(); DC.drag = 0; v.classList.remove('dragging');
  dc_upload(e.dataTransfer.files);
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && DC.waiting) dc_pollSet(); });

// ---- 2.96.0 A (#1941): choose documents (one, several, or every one the filters find) and move them into the other workspace
// (private <-> organisation): into the documents folder there, with sender, type and tags. ONE undo step (back to the old folders).
// 2.768.0 (#4888): the choice is the area's one selection (ablage.js AB.sel, ab_selPick, ab_selBar); here what only documents have
const DC_SMV_MAX = 2000;  // the server's limit per move (accounts/spacemove.py SMV_MAX)
const dc_selIds = () => [...AB.sel.values()].filter(x => x.isdoc).map(x => x.id);  // the chosen documents
const dc_smvBtn = () => DC.docs?.length || (ab_selFold() && AB.data?.items?.length) ? `<button type="button" class="btn sm ${AB.selOn ? 'on' : ''}" data-absel="mode" aria-pressed="${!!AB.selOn}">${ic('check', 's')} <span>${tr('Select')}</span></button>` : '';
async function dc_smvAll() {  // every document the search and the filters find (page by page, at most DC_SMV_MAX), added to the choice
  const p = dc_params();
  p.set('facets', '0'); p.set('limit', '200');
  for (let off = 0; off < DC_SMV_MAX; off += 200) {
    p.set('offset', String(off));
    let j; try { j = await api('GET', '/api/docs?' + p); } catch { return; }
    for (const d of j.docs || []) if (!AB.sel.has(d.id)) AB.sel.set(d.id, ab_selInfo(d));
    if ((j.docs || []).length < 200) break;
  }
  if (DC.total > DC_SMV_MAX) toast(tr('Too many at once: at most {0}', DC_SMV_MAX));
}
async function dc_smvMove(sel, what) {
  const orgs = new Set(sel.values());
  if (orgs.size !== 1) { toast(tr('Select items of one workspace')); return null; }
  const ids = [...sel.keys()], from = [...orgs][0];
  let last = null;
  const r = await smv_open({what, from, total: ids.length,  // 2.147.1 B (#2230): batches + progress
    check: async to => { try { return await rawFetch('POST', '/api/files/move-space', {ids, to: smv_ws(to), parent: 'docs', dry: 1}); } catch (x) { return {block: x.message || tr('The check failed. Please try again.')}; } },
    run: (to, _p, _o, step) => { last = {ids, to: smv_ws(to), parent: 'docs'}; return smv_post('/api/files/move-space', last, 'ids', step); }});
  if (!r?.moved || !last) return null;
  ab_selEnd(); DC.facets = null;
  dc_load();
  const req = async (b, key) => { try { await smv_post('/api/files/move-space', b, key); } catch { /* shown */ } DC.facets = null; dc_load(); return {}; };
  const back = {items: r.moved.map(m => ({id: m.id, parent: m.parent_was, name: m.name_was})), to: smv_ws(r.org_was)}, again = last;
  offerUndo(smv_label(r, ids.length), histAdd({label: tr('Move to another workspace'), undo: () => req(back, 'items'), redo: () => req(again, 'ids')}));
  return r;
}

// 2.122.0 (#2100): the chosen documents as a CSV file (the server leaves out what the person may not see)
async function dcx_csv(ids = dc_selIds()) {
  if (!ids.length) return;
  try {
    const r = await fetch('/api/docs/export.csv', {method: 'POST', headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/json'}, body: JSON.stringify({ids})});
    if (!r.ok) throw new Error(String(r.status));
    const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = 'documents.csv';
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  } catch { toast(tr('The check failed. Please try again.')); }
}
// ---- 2.122.0 B (#2294): the search of an archive -- several tags (with / without, every one / one of them), several senders,
// types, folders and file types, the document date and the date of arrival, without tag / sender, the search syntax in the
// search field (tag:, absender:, typ:, datum:, "exact", -word; docs/dsearch.py). The filters chosen stand in a line above the
// list (each one to take out, the number of hits); phones: the filters in a sheet. The chosen documents get tags / a type /
// a sender at once (ONE undo step) or come as one ZIP.
function dc_f0() {  // the empty filters (sender / type / folder: ids lists "1,7" per name; tg: {"1,7": 'in' | 'not'}; tag: the old single value)
  return {sender: [], type: [], tag: '', tg: {}, tmode: 'any', from: '', to: '', afrom: '', ato: '', folder: [], ftype: [], notag: false, nosender: false, review: false,
    asn: '', asnHas: '', cf: []};  // 2.772.0 (#4890): archive number or range, 'with' | 'without' one, custom fields ["<field ids>:<value>"]
}
// 2.772.0 (#4890): "143" or "140-150" (the server's dsearch.py dsr_asn), else ''
const dc_asnOk = v => { const m = /^\s*(\d{1,9})\s*(?:[-–]\s*(\d{1,9})\s*)?$/.exec(String(v || '')); return m ? (m[2] ? `${m[1]}-${m[2]}` : m[1]) : ''; };
const dc_cfName = (fc, v) => { const [ids, ...rest] = v.split(':'), val = rest.join(':'), x = (fc.fields || []).find(e => e.ids.join(',') === ids); const o = x?.values.find(y => y.value === val); return x ? `${x.name}: ${o ? o.name : val}` : val; };
const dc_arr = v => Array.isArray(v) ? v : v ? [v] : [];
const DC_FTYPES = [['pdf', N_('PDF')], ['image', N_('Image')], ['office', N_('Office files')], ['text', N_('Text')], ['other', N_('Other')]];
function dc_fParams(p) {
  const f = DC.f;
  for (const k of ['sender', 'type', 'folder']) for (const v of dc_arr(f[k])) p.append(k, v);
  for (const [ids, st] of Object.entries(f.tg || {})) p.append(st === 'not' ? 'not_tag' : 'tag', ids);
  if (f.tmode === 'all') p.set('tag_mode', 'all');
  if (f.afrom) p.set('added_from', f.afrom);
  if (f.ato) p.set('added_to', f.ato);
  if (f.notag) p.set('no_tag', '1');
  if (f.nosender) p.set('no_sender', '1');
  if (dc_arr(f.ftype).length) p.set('ftype', dc_arr(f.ftype).join(','));
  if (dc_asnOk(f.asn)) p.set('asn', dc_asnOk(f.asn));  // 2.772.0 (#4890)
  if (f.asnHas) p.set(f.asnHas === 'with' ? 'has_asn' : 'no_asn', '1');
  for (const v of dc_arr(f.cf)) p.append('cf', v);
}
const dc_fName = (list, ids) => (list || []).find(x => x.ids.join(',') === ids)?.name || '?';
function dc_fEntries() {  // the chosen filters: [{label, not, rm}]
  const f = DC.f, fc = DC.facets || {}, out = [];
  const multi = (k, list) => { for (const v of dc_arr(f[k])) out.push({label: dc_fName(list, v), rm: () => { f[k] = dc_arr(f[k]).filter(x => x !== v); }}); };
  for (const [ids, st] of Object.entries(f.tg || {})) out.push({label: dc_fName(fc.tags, ids), not: st === 'not', rm: () => { delete f.tg[ids]; }});
  if (f.tag) out.push({label: dc_fName(fc.tags, f.tag), rm: () => { f.tag = ''; }});
  multi('sender', fc.senders); multi('type', fc.types); multi('folder', fc.folders);
  for (const v of dc_arr(f.ftype)) out.push({label: tr(DC_FTYPES.find(x => x[0] === v)?.[1] || v), rm: () => { f.ftype = dc_arr(f.ftype).filter(x => x !== v); }});
  for (const [k, lab] of [['from', N_('Document date from {0}')], ['to', N_('Document date to {0}')], ['afrom', N_('Arrived from {0}')], ['ato', N_('Arrived to {0}')]]) if (f[k]) out.push({label: tr(lab, dc_day(f[k])), rm: () => { f[k] = ''; }});
  if (f.notag) out.push({label: tr('Without tag'), rm: () => { f.notag = false; }});
  if (f.nosender) out.push({label: tr('Without sender'), rm: () => { f.nosender = false; }});
  if (dc_asnOk(f.asn)) out.push({label: tr('Archive number {0}', dc_asnOk(f.asn)), rm: () => { f.asn = ''; }});  // 2.772.0 (#4890)
  if (f.asnHas) out.push({label: f.asnHas === 'with' ? tr('With archive number') : tr('Without archive number'), rm: () => { f.asnHas = ''; }});
  for (const v of dc_arr(f.cf)) out.push({label: dc_cfName(fc, v), rm: () => { f.cf = dc_arr(f.cf).filter(x => x !== v); }});
  return out;
}
function dc_fbarHtml() {
  const es = dc_fEntries(), q = DC.q.trim();
  if (!es.length && !q) return '';
  return `<div class="tsfbar dc-fbar" role="group" aria-label="${esc(tr('Filter'))}">${q ? `<button type="button" class="tsfx" data-dcx="q" aria-label="${esc(tr('Remove filter {0}', q))}">${esc(tr('“{0}”', q))} ${ic('x', 's')}</button>` : ''}
    ${es.map((e, i) => `<button type="button" class="tsfx ${e.not ? 'not' : ''}" data-dcx="${i}" aria-label="${esc(tr('Remove filter {0}', e.label))}">${e.not ? `${tr('not')} ` : ''}${esc(e.label)} ${ic('x', 's')}</button>`).join('')}
    ${Object.values(DC.f.tg || {}).filter(x => x === 'in').length > 1 ? `<span class="tsfn">${DC.f.tmode === 'all' ? tr('every one') : tr('one of them')}</span>` : ''}
    ${DC.docs ? `<span class="tsfn" aria-live="polite">${esc(trn('{0} hit', '{0} hits', DC.total))}</span>` : ''}<button type="button" class="linkbtn" data-dc="clear">${tr('Reset filters')}</button></div>`;
}
function dc_fltHtml() {  // the filters (desktop: below the bar; phones: the sheet)
  const f = DC.f, fc = DC.facets || {senders: [], types: [], tags: [], folders: []};
  const st = (list, sel) => Object.fromEntries((list || []).filter(x => sel(x.ids.join(','))).map(x => [x.name, sel(x.ids.join(','))]));
  const tagSt = st(fc.tags, ids => (f.tg || {})[ids]), on = Object.values(f.tg || {}).filter(x => x === 'in').length;
  const two = (k, list) => dt_pills(list, st(list, ids => dc_arr(f[k]).includes(ids) ? 'in' : ''), 'dcf' + k, false, k !== 'folder');  // 2.772.0 (#4890): with numbers
  const sec = (title, inner) => inner ? `<h4>${esc(tr(title))}</h4><div class="tsgrp">${inner}</div>` : '';
  const pick = typeof dt_pills === 'function';
  return `<div class="tsflt">${isMobile() ? dc_sortHtml() : ''}
    ${pick ? sec(N_('Tags'), dt_pills(fc.tags, tagSt, 'dcftg', true, true)) : ''}${pick && on > 1 ? `<div class="tsrow"><div class="seg" role="radiogroup" aria-label="${esc(tr('Several tags'))}">${['any', 'all'].map(m => `<button type="button" role="radio" data-dcfm="${m}" aria-checked="${(f.tmode || 'any') === m}">${m === 'all' ? tr('every one') : tr('one of them')}</button>`).join('')}</div></div>` : ''}
    ${pick ? sec(N_('Sender'), two('sender', fc.senders)) + sec(N_('Document type'), two('type', fc.types)) + sec(N_('Folder'), two('folder', fc.folders)) : ''}
    <h4>${tr('File type')}</h4><div class="tsgrp">${DC_FTYPES.map(([k, l]) => `<button type="button" class="tsp ${dc_arr(f.ftype).includes(k) ? 'tsp-in' : ''}" data-dcfft="${k}" aria-pressed="${dc_arr(f.ftype).includes(k)}">${esc(tr(l))}</button>`).join('')}</div>
    <h4>${tr('Document date')}</h4><div class="tsrow"><span class="dc-range">${tr('from')} ${dateIn('dc-ffrom', f.from, {label: tr('Document date from {0}', ''), attrs: 'data-dcf2="from"'})}</span><span class="dc-range">${tr('to')} ${dateIn('dc-fto', f.to, {label: tr('Document date to {0}', ''), attrs: 'data-dcf2="to"'})}</span></div>
    <h4>${tr('Date of arrival')}</h4><div class="tsrow"><span class="dc-range">${tr('from')} ${dateIn('dc-fafrom', f.afrom, {label: tr('Arrived from {0}', ''), attrs: 'data-dcf2="afrom"'})}</span><span class="dc-range">${tr('to')} ${dateIn('dc-fato', f.ato, {label: tr('Arrived to {0}', ''), attrs: 'data-dcf2="ato"'})}</span></div>
    <div class="tsrow"><label><input type="checkbox" data-dcf2="notag" ${f.notag ? 'checked' : ''}> ${tr('Without tag')}</label><label><input type="checkbox" data-dcf2="nosender" ${f.nosender ? 'checked' : ''}> ${tr('Without sender')}</label></div>
    ${dc_fltMore(f, fc)}
    <div class="dc-synw"><p class="shint dc-syn">${esc(tr('In the search field: tag:Name, absender:Name, typ:Name, datum:2025 or datum:2025-01..2025-03, "exact text", -word'))}</p></div></div>`;  // 2.298.0 C (#3187): the search syntax behind (i)
}
// 2.772.0 (#4890): the archive number (a number or a range, with / without one) and the custom fields of type selection /
// checkbox, with their numbers like the filters below the file store's tree (docfacets.js); every field one row of pills
function dc_fltMore(f, fc) {
  const a = fc.asn, cnt = n => n != null ? ` <span class="tsc">${n}</span>` : '';
  const has = (k, lab, n) => `<button type="button" class="tsp ${f.asnHas === k ? 'tsp-in' : ''}" data-dcfasn="${k}" aria-pressed="${f.asnHas === k}">${esc(lab)}${cnt(n)}</button>`;
  const asn = `<h4>${tr('Archive number')}</h4><div class="tsrow"><input type="text" inputmode="numeric" class="dc-asnin" data-dcf2="asn" value="${esc(f.asn || '')}" placeholder="${esc(tr('Number or range'))}" aria-label="${esc(tr('Archive number: number or range, e.g. 140-150'))}"></div>
    <div class="tsgrp">${has('without', tr('Without archive number'), a?.without)}${has('with', tr('With archive number'), a?.with)}</div>`;
  const fields = (fc.fields || []).map(x => `<h4>${esc(x.name)}</h4><div class="tsgrp">${x.values.map(v => { const k = x.ids.join(',') + ':' + v.value, on = dc_arr(f.cf).includes(k); return `<button type="button" class="tsp ${on ? 'tsp-in' : ''}" data-dcfcf="${esc(k)}" aria-pressed="${on}">${esc(v.name)}${cnt(v.count)}</button>`; }).join('')}</div>`).join('');
  return asn + fields;
}
function dc_fSheet() {  // phones: the filters in a sheet; every change applies at once, the foot shows the hits
  $('.dc-fsheet')?.remove();
  const md = modal(`<div class="lhdr"><h3>${tr('Filter')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div><div class="dc-flt"></div>
    <div class="foot stfoot"><button type="button" class="btn" data-dc="clear">${tr('Reset filters')}</button><span class="spacer"></span><button type="button" class="btn pri" data-m="close"></button></div>`);
  md.classList.add('dc-fsheet');
  md.addEventListener('click', e => {
    if (e.target.closest('[data-m="close"]')) { modalClose(md); return; }
    if (e.target.closest('[data-dc="clear"]')) { DC.f = {...dc_f0(), review: DC.f.review}; dc_load(); dc_fSheetDraw(); }
  });
  dc_fSheetDraw();
}
function dc_fSheetDraw() {
  const md = $('.dc-fsheet'); if (!md) return;
  const box = $('.dc-flt', md), y = md.querySelector('.card')?.scrollTop || 0;
  if (box) box.innerHTML = dc_fltHtml();
  const ok = $('.foot [data-m="close"]', md); if (ok) ok.textContent = DC.docs ? trn('Show {0} document', 'Show {0} documents', DC.total) : tr('Done');
  const card = md.querySelector('.card'); if (card) card.scrollTop = y;
}
function dc_fChanged() { DC.at = 0; dc_load(); dc_fSheetDraw(); if (!isMobile()) dc_draw(); }
document.addEventListener('click', e => {
  const x = e.target.closest?.('[data-dcx]');
  if (x && x.closest('.dc-view')) {
    if (x.dataset.dcx === 'q') { DC.q = ''; const qi = $('#dc-q'); if (qi) qi.value = ''; clearTimeout(dc_qTimer); }  // 2.138.4 A (#2362): a focused field keeps its text in the redraw (iOS: the tap leaves the focus there)
    else dc_fEntries()[+x.dataset.dcx]?.rm();
    dc_fChanged(); return;
  }
  const box = e.target.closest?.('.dc-flt'); if (!box) return;
  const so = e.target.closest('[data-dcsort], [data-dcsortd]');  // 2.428.0 (#3579): the sort in the phone's sheet
  if (so) { if (so.dataset.dcsort) dc_sortPick(so.dataset.dcsort); else dc_sortSet(dc_sort().k, so.dataset.dcsortd); return; }
  const f = DC.f, fc = DC.facets || {};
  const b = e.target.closest('[data-dcftg], [data-dcfsender], [data-dcftype], [data-dcffolder], [data-dcfft], [data-dcfm], [data-dcfasn], [data-dcfcf]'); if (!b) return;
  const ids = (list, name) => (list || []).find(x => x.name === name)?.ids.join(',');
  if (b.dataset.dcftg != null) {
    const k = ids(fc.tags, b.dataset.dcftg); if (!k) return;
    f.tg = {...(f.tg || {})}; const s = f.tg[k]; if (!s) f.tg[k] = 'in'; else if (s === 'in') f.tg[k] = 'not'; else delete f.tg[k];
    if (f.tag === k) f.tag = '';
  } else if (b.dataset.dcfm) f.tmode = b.dataset.dcfm;
  else if (b.dataset.dcfft) { const v = b.dataset.dcfft, a = dc_arr(f.ftype); f.ftype = a.includes(v) ? a.filter(x => x !== v) : [...a, v]; }
  else if (b.dataset.dcfasn) f.asnHas = f.asnHas === b.dataset.dcfasn ? '' : b.dataset.dcfasn;  // 2.772.0 (#4890)
  else if (b.dataset.dcfcf) { const v = b.dataset.dcfcf, a = dc_arr(f.cf); f.cf = a.includes(v) ? a.filter(x => x !== v) : [...a, v]; }
  else {
    const kind = b.dataset.dcfsender != null ? 'sender' : b.dataset.dcftype != null ? 'type' : 'folder';
    const k = ids(fc[{sender: 'senders', type: 'types', folder: 'folders'}[kind]], b.dataset['dcf' + kind]); if (!k) return;
    const a = dc_arr(f[kind]); f[kind] = a.includes(k) ? a.filter(x => x !== k) : [...a, k];
  }
  dc_fChanged();
});
document.addEventListener('change', e => {
  const el = e.target.closest?.('[data-dcf2]'); if (!el || !el.closest('.dc-flt')) return;
  const k = el.dataset.dcf2;
  DC.f[k] = el.type === 'checkbox' ? el.checked : k === 'asn' ? dc_asnOk(el.value) : el.value;  // 2.772.0 (#4890): a wrong number is no filter
  dc_fChanged();
});
// ---- 2.122.0 B (#2294): the chosen documents at once (POST /api/docs/bulk in parts of 500; ONE undo step) and as a ZIP
const DC_BULK = 500;
async function dc_bulkSend(bodies) {  // [{...}] one request each -> {changed, denied, before}
  const out = {changed: [], denied: 0, before: []};
  for (const b of bodies) {
    const r = await api('POST', '/api/docs/bulk', b);
    out.changed.push(...(r.changed || [])); out.denied += r.denied || 0; out.before.push(...(r.before || []));
  }
  return out;
}
// 2.768.0 (#4888): after a change of several: the documents' list, and a folder's list where the documents were chosen
const dc_relist = () => { DC.facets = null; if (S.route.mod === 'ablage') ab_reload(); else dc_load(); };
const dc_chunks = (a, n) => Array.from({length: Math.ceil(a.length / n)}, (_, i) => a.slice(i * n, i * n + n));
async function dc_bulk(change, label) {
  const ids = dc_selIds(); if (!ids.length) return;
  const req = dc_chunks(ids, DC_BULK).map(part => ({ids: part, ...change}));
  let r; try { r = await dc_bulkSend(req); } catch { dc_relist(); return; }
  dc_relist();
  if (r.denied) toast(trn('{0} document may only be viewed by you and stays as it is', '{0} documents may only be viewed by you and stay as they are', r.denied));
  if (!r.changed.length) { if (!r.denied) toast(tr('Nothing to change')); return; }
  const back = dc_chunks(r.before, DC_BULK).map(part => ({restore: part}));
  const step = bodies => async () => { try { await dc_bulkSend(bodies); } catch { /* shown */ } dc_relist(); return {}; };
  histToast(`${label}: ${trn('{0} document', '{0} documents', r.changed.length)}`, histAdd({label, undo: step(back), redo: step(req)}));
}
function dc_bulkMenu(anchor) {
  menu(anchor, [{label: tr('Add tags…'), icon: 'tag', fn: () => dc_bulkTags(true)}, {label: tr('Remove tags…'), icon: 'tag', fn: () => dc_bulkTags(false)},
    {label: tr('Set document type…'), icon: 'file', fn: () => dc_bulkSet('type')}, {label: tr('Set sender…'), icon: 'user', fn: () => dc_bulkSet('sender')},
    {label: tr('Set title from pattern'), icon: 'edit', cls: 'dc-titlesel', fn: () => dc_bulk({title_pattern: true}, tr('Title set from pattern'))},  // 2.783.0 (#4882)
    {label: tr('Apply what was learned'), icon: 'sparkle', cls: 'dc-learnsel', fn: () => dc_learn(dc_selIds())}], null, null, tr('Edit'));  // 2.607.0 (#4872)
}
// 2.607.0 (#4872): "Apply what was learned": only the sorting (rules + what was learned) with the stored text, no new recognition
// (POST /api/docs/apply-learned in parts of DC_LEARN with the progress as a message; ONE undo step: the run token of all parts)
const DC_LEARN = 100;
const dc_learnBar = () => DC.f.review && DC.docs?.length && !AB.selOn ? `<p class="muted dc-wait dc-learnbar"><button type="button" class="btn sm" data-dc="learnall" title="${esc(tr('Sorts every document in To review again with the rules and what was learned (no new text recognition)'))}">${ic('sparkle', 's')} <span>${tr('Apply what was learned')}</span></button></p>` : '';
async function dc_learnSend(ids, b, onStep) {  // -> the summed answers ({run, set, suggested, changed, denied, skipped, back})
  const out = {run: b.run || null, set: 0, suggested: 0, changed: [], denied: 0, skipped: 0, back: 0};
  for (let i = 0; i < ids.length; i += DC_LEARN) {
    const r = await api('POST', '/api/docs/apply-learned', {...b, ids: ids.slice(i, i + DC_LEARN), ...(out.run ? {run: out.run} : {})});
    out.run = r.run; out.changed.push(...(r.changed || []));
    for (const k of ['set', 'suggested', 'denied', 'skipped', 'back']) out[k] += r[k] || 0;
    if (onStep) onStep(Math.min(i + DC_LEARN, ids.length), ids.length);
  }
  return out;
}
async function dc_learn(ids) {
  if (!ids.length) return;
  const prog = (a, n) => { if (a < n) toast(tr('Applying what was learned… {0} of {1}', a, n), null, 60000); };
  prog(0, ids.length > DC_LEARN ? ids.length : 0);
  let r; try { r = await dc_learnSend(ids, {}, prog); } catch { DC.facets = null; dc_load(); return; }
  DC.facets = null; dc_load();
  const deny = r.denied ? ' · ' + trn('{0} document may only be viewed by you and stays as it is', '{0} documents may only be viewed by you and stay as they are', r.denied) : '';
  if (!r.changed.length) { toast(tr('Nothing new to sort') + deny, null, deny ? 6000 : 0); return; }
  let run = r.run, changed = r.changed;
  const label = tr('Apply what was learned');
  const msg = trn('{0} document sorted', '{0} documents sorted', r.set) + ', ' + trn('{0} suggestion', '{0} suggestions', r.suggested) + deny;
  histToast(msg, histAdd({label,
    undo: async () => { try { await dc_learnSend(changed, {undo: true, run}); } catch { /* shown */ } DC.facets = null; dc_load(); return {}; },
    redo: async () => { try { const x = await dc_learnSend(ids, {}); run = x.run; changed = x.changed; } catch { /* shown */ } DC.facets = null; dc_load(); return {}; }}), 8000);
}
async function dc_learnReview() {  // every document of "To review" the search and the filters find (as "All" of the selection)
  const p = dc_params(), ids = [];
  p.set('facets', '0'); p.set('limit', '200'); p.set('review', '1');
  for (let off = 0; off < DC_SMV_MAX; off += 200) {
    p.set('offset', String(off));
    let j; try { j = await api('GET', '/api/docs?' + p); } catch { return; }
    for (const d of j.docs || []) if (d.review) ids.push(d.id);
    if ((j.docs || []).length < 200) break;
  }
  dc_learn(ids);
}
async function dc_bulkTags(add) {
  const known = [...(DC.docs || []), ...(AB.data?.items || []).map(n => n.doc).filter(x => x?.tags)].filter(d => AB.sel.has(d.id)).flatMap(d => d.tags.map(t => t.name));
  const all = add ? (DC.facets?.tags || []) : [...new Set(known)].map(name => ({name}));
  const n = dc_selIds().length;
  const names = await dt_pick({title: add ? trn('Add tags to {0} document', 'Add tags to {0} documents', n) : trn('Remove tags from {0} document', 'Remove tags from {0} documents', n),
    all: add ? all : (all.length ? all : DC.facets?.tags || []), cur: [], ok: add ? tr('Add') : tr('Remove'), known: !add});  // 2.742.0 (#4862): removing offers only the given tags
  if (!names?.length) return;
  dc_bulk(add ? {add_tags: names} : {remove_tags: names}, add ? tr('Tags added') : tr('Tags removed'));
}
async function dc_bulkSet(kind) {
  const list = (kind === 'type' ? DC.facets?.types : DC.facets?.senders) || [];
  const v = await askDialog({title: kind === 'type' ? tr('Document type of the selected documents ({0})', dc_selIds().length) : tr('Sender of the selected documents ({0})', dc_selIds().length), ok: tr('Save'),
    input: {value: '', max: 120, placeholder: kind === 'type' ? tr('e.g. Invoice, Contract, Letter') : tr('Sender')},
    after: md => { const i = $('#cdlg-in', md); if (!i) return; const dl = document.createElement('datalist'); dl.id = 'dc-bulkdl'; dl.innerHTML = list.map(x => `<option value="${esc(x.name)}">`).join(''); i.setAttribute('list', dl.id); i.after(dl); }});
  if (v == null || !String(v).trim()) return;
  dc_bulk({[kind]: String(v).trim()}, kind === 'type' ? tr('Document type set') : tr('Sender set'));
}
async function dc_zip(ids = dc_selIds()) {
  if (!ids.length) return;
  let r; try { r = await api('POST', '/api/docs/zip', {ids}); } catch { return; }  // too many / too large: the server's hint is the toast
  toast(trn('The ZIP with {0} document is being prepared…', 'The ZIP with {0} documents is being prepared…', r.files));
  const a = document.createElement('a'); a.href = r.url; a.download = ''; document.body.appendChild(a); a.click(); a.remove();
}

// 2.752.0 (#4887): the documents' own folder tree in the panel (2.199.0 B, #2742: dc_panelTree, ?under= of the sidebar) is
// gone: the file store's tree is the one tree, a folder with recognition shows its documents itself (abdocs.js abd_foldHtml)
