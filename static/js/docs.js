/* Kalmido web client: Documents (2.48.0, #1111): the list (cards with a preview), filters, full-text search, upload by
   dragging, the document sheet (preview, fields with "automatic" marks, suggestions "To review", recognised text) and the
   settings of a workspace (level per feature, rules, the forwarding address). Route #docs (area "Ablage", areas.js), a
   document: #docs/<id>. Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

const DC = {docs: null, total: 0, review: 0, waiting: 0, facets: null, err: null, loading: false, seq: 0, q: '',
  f: dc_f0(), more: false, poll: null, doc: null, set: null, drag: 0};
const DC_FEATS = [['sender', N_('Sender')], ['type', N_('Document type')], ['tags', N_('Tags')], ['folder', N_('Folder')]];
const DC_LEVELS = [['learn', N_('Learns from your documents')], ['rules', N_('Rules only')], ['agent', N_('Left to an agent')], ['off', N_('Off')]];
const DC_KINDS = [['any', N_('contains one of the words')], ['all', N_('contains all words')], ['exact', N_('contains the exact phrase')],
  ['fuzzy', N_('contains the phrase (tolerates typos)')], ['regex', N_('matches the pattern (regular expression)')]];
// 2.153.0 (#2179): the types of the custom fields of documents (docs/fields.py DF_TYPES; DC_FTYPES = the file types of the filter)
const DC_CFTYPES = [['text', N_('Text')], ['number', N_('Number')], ['money', N_('Amount')], ['date', N_('Date')], ['checkbox', N_('Checkbox')], ['select', N_('Selection')], ['url', N_('Link')]];
const DC_STATE = {wait: N_('Waiting for recognition'), run: N_('Recognising…'), done: N_('Recognised'), failed: N_('Recognition failed')};
const DC_BY = {rule: N_('set by a rule'), learn: N_('learnt from your documents'), agent: N_('set by an agent'), import: N_('imported'), code: N_('read from the code on the document'), photo: N_('from the capture date of the photo')};  // 2.61.0 B (#1819): photo

// the module switch (Settings > Modules), off by default like the other areas
// 2.65.0 (#1823): the module switch (FEATS, FEAT_DESC) and dc_shareOk are in lazyload.js (this file loads on demand)
const dc_ws = () => (typeof wsCur === 'function' ? wsCur() : 'all');
const dc_upWs = () => { const w = dc_ws(); return w.startsWith('org:') ? w : 'private'; };
const dc_hashId = () => { try { const m = location.hash.match(/^#docs\/(\d+)/); return m ? +m[1] : null; } catch { return null; } };  // the sheet may close after its window is gone
const dc_money = (a, cur) => a == null || a === '' ? '' : `${(+a).toLocaleString(LOCALE(), {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${({EUR: '€', USD: '$', GBP: '£'})[cur] || cur || ''}`.trim();  // 2.189.0 (#2475): + £
const dc_day = d => d ? dayLabel(d, true) : '';
const dc_isPdf = d => d && (d.mime === 'application/pdf' || /\.pdf$/i.test(d.name));
const dc_fileUrl = (d, dl) => `/api/docs/${d.id}/file?v=${d.size}${dl ? '&dl=1' : ''}`;

// ---- loading
function dc_params() {
  const p = new URLSearchParams({ws: dc_ws(), limit: '200'});
  if (DC.q.trim()) p.set('q', DC.q.trim());
  for (const k of ['tag', 'from', 'to']) if (DC.f[k]) p.set(k, DC.f[k]);
  dc_fParams(p);  // 2.122.0 B (#2294): several values, more filters
  if (DC.f.review) p.set('review', '1');
  if (DC.under) p.set('under', DC.under);  // 2.199.0 B (#2742): a folder of the panel's tree (with its subfolders)
  return p;
}
async function dc_load() {
  const seq = ++DC.seq, ws = dc_ws();  // 2.66.1 (#1945): the workspace of this load, held from its start
  DC.loading = true; DC.ws = ws;
  try {
    const j = await api('GET', '/api/docs?' + dc_params());
    if (seq !== DC.seq || ws !== dc_ws()) return;  // 2.66.1 (#1945): an answer for a workspace no longer shown is dropped
    Object.assign(DC, {docs: j.docs, total: j.total, review: j.review, waiting: j.waiting, facets: j.facets || DC.facets, err: null});
  } catch (x) { if (seq !== DC.seq || ws !== dc_ws()) return; DC.err = x.message || tr('unknown'); }
  DC.loading = false; DC.at = Date.now(); DC.atWs = ws;  // 2.62.0 (#1844)
  dc_draw();
  dc_pollSet();
}
// 2.87.9 (#1934): a hit of the search (palette.js palSubItems): the documents filtered by one sender / type / tag
function dc_filterGo(k, v) {
  DC.f = {...dc_f0(), from: DC.f.from, to: DC.f.to, ...(k === 'tag' ? {tg: {[v]: 'in'}} : {[k]: v})}; DC.more = true; DC.at = 0;  // 2.122.0 B (#2294)
  if (S.route.mod === 'docs') dc_load(); else go('docs');
}
// 2.66.1 (#1945): the workspace switch (here, or on another device) drops the list, the counters, the filters (their values
// are ids of the old workspace) and an open document of the old workspace; viewDocs then loads the new one at once
function p61b_dcReset() {
  DC.seq++; clearTimeout(DC.poll);
  Object.assign(DC, {docs: null, total: 0, review: 0, waiting: 0, facets: null, set: null, err: null, loading: false, ws: null, atWs: null, more: false,
    sel: new Map(), selOn: false,  // 2.96.0 A (#1941): a choice of the old workspace goes
    f: dc_f0()});  // 2.122.0 B (#2294)
  const md = $('.dc-md');
  if (md && DC.doc && !wsObjIn(DC.doc)) { if (dc_hashId()) history.replaceState(null, '', '#docs'); md.remove(); }
}
function dc_pollSet() {  // while documents are being recognised, look again every few seconds
  clearTimeout(DC.poll);
  if (DC.waiting && S.route.mod === 'docs' && !document.hidden) DC.poll = setTimeout(() => S.route.mod === 'docs' && dc_load(), 4000);
}
function dc_draw() {
  if (S.route.mod !== 'docs') return;
  const el = $('#view'); if (!el) return;
  keepFocus(el, () => setHtml(el, typeof mg_wrap === 'function' ? mg_wrap('docs', viewDocs()) : viewDocs()));
  dc_fSheetDraw();  // 2.122.0 B (#2294): the filter sheet (phones) follows the list
}

// ---- the view
function viewDocs() {
  // 2.62.0 (#1844): opening the tab always loads again (the list shown before could be empty / old: files that arrived since, a
  // changed workspace, an earlier error); the old list stays until the new one is there, redraws within 3 s do not reload
  // (review: only when the tab is opened anew - a redraw of the open tab never reloads; an error waits for the next opening)
  const open = !document.querySelector('.dc-view');  // not on screen yet = the tab is being opened
  if (DC.ws != null && DC.ws !== dc_ws()) p61b_dcReset();  // 2.66.1 (#1945): another workspace -> its data, open or not
  if (!DC.loading && ((!DC.docs && !DC.err) || (open && (Date.now() - (DC.at || 0) > 3000 || DC.atWs !== dc_ws())))) setTimeout(dc_load, 0);
  const id = dc_hashId();
  if (id && (!DC.doc || DC.doc.id !== id) && !$('.dc-md')) setTimeout(() => dc_open(id), 0);
  const active = dc_fEntries().length > 0;  // 2.122.0 B (#2294): the filters are drawn by dc_fltHtml / dc_fbarHtml
  const head = `
    <div class="dc-bar">
      <input type="search" id="dc-q" value="${esc(DC.q)}" placeholder="${esc(tr('Search in the documents…'))}" aria-label="${esc(tr('Search in the documents'))}" autocomplete="off">
      <div class="seg dc-seg" role="tablist"><button type="button" role="tab" data-dc="all" aria-selected="${!DC.f.review}">${tr('All')}</button><button type="button" role="tab" data-dc="review" aria-selected="${DC.f.review}">${tr('To review')}${DC.review ? ` <span class="dc-count">${DC.review}</span>` : ''}</button></div>
      <button type="button" class="btn sm ${active ? 'on' : ''}" data-dc="more" aria-expanded="${!!DC.more}">${ic('filter', 's')} ${tr('Filter')}${active ? ` <span class="dc-count">${dc_fEntries().length}</span>` : ''}</button>
      <span class="dc-acts2"><label class="btn pri dc-up" title="${esc(tr('Add documents'))}">${ic('plus', 's')} <span>${tr('Add documents')}</span><input type="file" id="dc-file" multiple accept="application/pdf,image/*,.pdf,.txt,.xml,application/xml,text/xml" hidden></label>
      <button type="button" class="btn sm" data-dc="scan" title="${esc(tr('Scan'))}">${ic('camera', 's')} <span>${tr('Scan')}</span></button>${dc_smvBtn()}<button type="button" class="iconbtn" data-dc="settings" aria-label="${esc(tr('Settings of the documents'))}" title="${esc(tr('Settings of the documents'))}">${ic('gear')}</button></span>
    </div>
    ${DC.more && !isMobile() ? `<div class="dc-fpanel dc-flt">${dc_fltHtml()}</div>` : ''}${dc_fbarHtml()}${dc_underHtml()}
    ${DC.waiting ? `<p class="muted dc-wait" role="status">${ic('hourglass', 's')} ${esc(trn('{0} document is being recognised…', '{0} documents are being recognised…', DC.waiting))}</p>` : ''}`;
  let body;
  if (DC.err) body = `<div class="empty">${ic('alert')}<span>${esc(DC.err)}</span></div>`;
  else if (!DC.docs) body = `<p class="muted lempty">${tr('Loading…')}</p>`;
  else if (!DC.docs.length) body = `<div class="empty nempty dc-empty">${ic('file')}<span>${DC.q || active || DC.f.review ? tr('No documents found') : tr('Drop PDFs or photos of letters here, or add them with the button. Kalmido reads the text, finds date and amount and sorts them.')}</span></div>`;
  else body = `<ul class="dc-grid${DC.selOn ? ' dc-selon' : ''}" aria-label="${esc(tr('Documents'))}">${DC.docs.map(dc_card).join('')}</ul>${DC.total > DC.docs.length ? `<p class="muted">${esc(tr('{0} of {1} shown, narrow the search', DC.docs.length, DC.total))}</p>` : ''}${dc_smvBar()}`;
  return `<div class="dc-view">${head}${body}<div class="dc-drop" aria-hidden="true"><span>${ic('plus')} ${tr('Drop to add as documents')}</span></div></div>`;
}
function dc_card(d) {
  const thumb = d.thumb ? `<img src="/api/docs/${d.id}/thumb?v=${esc(d.updated_at || '')}" alt="" loading="lazy">` : `<span class="dc-ph">${ic(dc_isPdf(d) ? 'file' : 'picture')}</span>`;
  const st = d.state === 'done' ? '' : `<span class="dc-st ${esc(d.state)}">${esc(tr(DC_STATE[d.state] || d.state))}</span>`;
  const meta = [d.date ? dc_day(d.date) : '', d.type?.name || '', d.asn ? `${DC.set?.asn_prefix || 'ASN'} ${d.asn}` : ''].filter(Boolean).map(esc).join(' · ');
  return `<li class="dc-card${d.review ? ' rev' : ''}${DC.selOn && DC.sel.has(d.id) ? ' dc-on' : ''}"><button type="button" data-dco="${d.id}" aria-label="${esc(d.name)}"${DC.selOn ? ` aria-pressed="${DC.sel.has(d.id)}"` : ''}>${DC.selOn ? `<span class="dc-selmark" aria-hidden="true">${DC.sel.has(d.id) ? ic('check', 's') : ''}</span>` : ''}
    <span class="dc-th">${thumb}</span><span class="dc-ct"><b class="dc-nm">${esc(d.sender?.name || d.name)}</b>
    <span class="dc-mt">${meta}${d.amount ? ` · ${esc(dc_money(d.amount, d.currency))}` : ''}</span>
    ${d.tags.length ? `<span class="dc-tags">${d.tags.map(t => `<span class="dc-tag">${esc(t.name)}</span>`).join('')}</span>` : ''}
    ${st}${d.review ? `<span class="dc-revdot">${tr('To review')}</span>` : ''}${d.split?.stack ? `<span class="dc-revdot dsp-dot">${tr('Stack - split?')}</span>` : '' /* 2.154.0 A (#1111) */}</span></button></li>`;
}

// ---- upload (button, dragging, the share sheet)
async function dc_upload(files, ws, source) {
  files = [...files].filter(f => f && f.size);
  if (!files.length) return [];
  const fd = new FormData();
  for (const f of files.slice(0, 50)) fd.append('files', f, f.name);
  fd.append('ws', ws || dc_upWs());
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
  if (dup) toast(j.dups.length === 1 ? tr('This file already exists: {0}', dup.name) : tr('{0} files already exist', j.dups.length), () => dc_open(dup.id), 8000, tr('Open'));
  if (S.route.mod === 'docs') dc_load();
  return j.ids || [];
}
async function dc_shareFiles(files) {  // the share sheet: "File as document"
  const ids = await dc_upload(files, dc_upWs(), 'share');
  if (ids.length) location.hash = '#docs';
}

// ---- the document sheet
async function dc_open(id) {
  let d;
  try { d = await api('GET', `/api/docs/${id}`); } catch { if (dc_hashId() === id) history.replaceState(null, '', '#docs'); return; }
  DC.doc = d;
  if (!DC.set || DC.set.ws !== (d.org_id ? 'org:' + d.org_id : 'private')) DC.set = await api('GET', `/api/docs/settings?ws=${d.org_id ? 'org:' + d.org_id : 'private'}`).catch(() => null);
  let md = $('.dc-md');
  if (!md) {
    md = modal('<div class="dc-body"></div>');
    md.classList.add('dc-md');
    onRemove(md, () => { DC.doc = null; if (dc_hashId()) history.replaceState(null, '', '#docs'); });
    md.addEventListener('click', dc_mdClick);
    md.addEventListener('change', dc_mdChange);
    if (dc_hashId() !== id) history.replaceState(null, '', `#docs/${id}`);
  }
  dc_mdDraw(md);
}
function dc_auto(d, f) {
  const by = d.auto?.[f];
  return by ? `<button type="button" class="dc-auto" data-dc="edit:${esc(f)}" title="${esc(tr(DC_BY[by] || by))}">${tr('automatic')}</button>` : '';
}
function dc_mdDraw(md) {
  const d = DC.doc; if (!d || !md) return;
  const set = DC.set || {senders: [], types: [], tags: [], folders: []};
  const w = d.role !== 'view';
  const dl = (id, list) => `<datalist id="${id}">${list.map(x => `<option value="${esc(x.name)}">`).join('')}</datalist>`;
  const field = (f, label, input) => `<div class="row dc-f"><label for="dc-${f}">${label}</label>${input}${dc_auto(d, f)}</div>`;
  // 2.98.0 D (#2178): an empty due date / amount stays hidden (a button opens them) -- they are guessed only for invoices / receipts
  const opt = (f, label, input, empty) => empty ? (ro ? '' : `<div class="row dc-f dc-opt" hidden><label for="dc-${f}">${label}</label>${input}</div>`) : field(f, label, input);
  const noDue = !d.due, noAmt = !d.amount;
  const sug = Object.entries(d.suggest || {});
  const sugHtml = d.review ? `<div class="dc-rev" role="group" aria-label="${esc(tr('To review'))}">
    <b>${tr('To review')}</b>
    ${sug.map(([f, s]) => `<div class="dc-sug"><span>${esc(tr(DC_FEATS.find(x => x[0] === f)?.[1] || f))}: <b>${esc(s.label)}</b>${s.by === 'agent' ? ` <span class="muted">(${tr('from the agent')})</span>` : ''}</span>${w ? `<button type="button" class="btn sm" data-dc="take:${esc(f)}">${tr('Accept|suggestion')}</button>` : ''}</div>`).join('')}
    ${sug.length ? '' : `<p class="muted">${tr('Check sender and type, then mark the document as checked.')}</p>`}
    ${w ? `<div class="dc-revact">${sug.length > 1 ? `<button type="button" class="btn sm" data-dc="takeall">${tr('Accept all')}</button>` : ''}<button type="button" class="btn sm pri" data-dc="checked">${ic('check', 's')} ${tr('Checked')}</button></div>` : ''}</div>` : '';
  // 2.154.0 A (#1111): docsplit.js draws the due date / task line (+ link with an existing task) and the stack hint; right
  // after "Create task" (no task title from the server yet) the line below
  const due = typeof dsp_sheetHtml === 'function' && (d.task !== undefined || !d.task_id) ? dsp_sheetHtml(d, w) : d.due && !d.task_id && w ? `<div class="dc-due">${ic('alarm', 's')} <span>${esc(tr('Due on {0}', dc_day(d.due)))}</span><button type="button" class="btn sm" data-dc="task">${tr('Create task')}</button></div>`
    : d.task_id ? `<div class="dc-due muted">${ic('done', 's')} <a href="#t/${d.task_id}">${tr('Task created')}</a></div>` : '';
  const ro = w ? '' : 'disabled';
  $('.dc-body', md).innerHTML = `<div class="lhdr"><h3 id="dc-h">${esc(d.name)}</h3><span class="spacer"></span><button class="iconbtn" data-dc="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="dc-top">
      <button type="button" class="dc-prev" data-dc="view" aria-label="${esc(tr('Show {0}', d.name))}">${d.thumb ? `<img src="/api/docs/${d.id}/thumb?v=${esc(d.updated_at || '')}" alt="">` : `<span class="dc-ph">${ic('file')}</span>`}</button>
      <div class="dc-acts">
        <button type="button" class="btn sm" data-dc="view">${ic('eye', 's')} ${tr('Show')}</button>
        ${d.einvoice ? `<a class="btn sm dc-einv" href="/api/docs/${d.id}/einvoice" target="_blank" rel="noopener">${ic('receipt', 's')} ${tr('Readable view')}</a>` /* 2.146.0 A (#2451) */ : ''}
        <a class="btn sm" href="${dc_fileUrl(d, true)}" download>${ic('archive', 's')} ${tr('Download')}</a>
        ${typeof dsp_actBtn === 'function' ? dsp_actBtn(d, w) : '' /* 2.154.0 A (#1111): split a stack */}
        ${d.parent_id ? `<a class="btn sm" href="#ablage/${d.parent_id}" data-dc="close">${ic('folder', 's')} ${tr('Show in the file store')}</a>` : ''}
        ${w && smv_can(d.org_id) ? `<button type="button" class="btn sm" data-dc="space">${ic('building', 's')} ${tr('Move to another workspace…')}</button>` : ''}
        ${w ? `<button type="button" class="btn sm danger" data-dc="del">${ic('trash', 's')} ${tr('Delete')}</button>` : ''}
      </div></div>
    <p class="dc-state ${esc(d.state)}" role="status">${esc(tr(DC_STATE[d.state] || d.state))}${d.state === 'failed' && d.error_text ? `: ${esc(d.error_text)}` : ''}${d.method === 'ocr' ? ` · ${tr('text recognition')}` : d.method === 'e-invoice' ? ` · ${tr('E-invoice')}` : ''}
      ${w && (d.state === 'done' || d.state === 'failed') ? `<button type="button" class="linkbtn" data-dc="redo">${tr('Recognise again')}</button>` : ''}</p>
    ${sugHtml}${due}${typeof rx_html === 'function' ? rx_html(d) : ''}${typeof rc_slot === 'function' ? rc_slot(d) : ''}${typeof ltd_slot === 'function' ? ltd_slot(d) : ''}${typeof ast_docSlot === 'function' ? ast_docSlot(d) : '' /* 2.126.1 A (#2123) */}
    <div class="dc-form">
      ${field('name', tr('Title'), `<input id="dc-name" data-dcp="name" value="${esc(d.name)}" maxlength="150" ${ro}>`)}
      ${field('sender', tr('Sender'), `<input id="dc-sender" data-dcp="sender" value="${esc(d.sender?.name || '')}" list="dc-sl" autocomplete="off" maxlength="120" ${ro}>${dl('dc-sl', set.senders)}`)}
      ${field('type', tr('Document type'), `<input id="dc-type" data-dcp="type" value="${esc(d.type?.name || '')}" list="dc-tl" autocomplete="off" maxlength="120" placeholder="${esc(tr('e.g. Invoice, Contract, Letter'))}" ${ro}>${dl('dc-tl', set.types)}`)}
      ${field('tags', tr('Tags'), `<input id="dc-tags" data-dcp="tags" value="${esc(d.tags.map(t => t.name).join(', '))}" list="dc-gl" autocomplete="off" placeholder="${esc(tr('comma-separated'))}" ${ro}>${dl('dc-gl', set.tags)}`)}
      ${field('folder', tr('Folder'), `<select id="dc-folder" data-dcp="folder" ${ro}><option value="">${tr('Documents (no subfolder)')}</option>${(set.folders || []).map(f => `<option value="${f.id}" ${d.folder?.id === f.id ? 'selected' : ''}>${esc(tr('Documents') + ' / ' + (f.path || f.name))}</option>`).join('')}${w ? `<option value="new">${tr('New folder…')}</option>${d.folder?.id ? `<option value="newsub">${esc(tr('New subfolder in {0}…', d.folder.name))}</option>` : ''}` : ''}</select>`)}
      ${field('date', tr('Date'), dateIn('dc-date', d.date || '', {label: tr('Date'), ro: !!ro, attrs: 'data-dcp="date"'}))}${typeof pmeta_takenHtml === 'function' ? pmeta_takenHtml(d) : ''}
      ${opt('due', tr('Due'), dateIn('dc-due', d.due || '', {label: tr('Due'), ro: !!ro, attrs: 'data-dcp="due"'}), noDue)}
      ${field('asn', tr('Archive number'), `<span class="dc-amt"><input type="number" min="1" id="dc-asn" data-dcp="asn" value="${esc(d.asn || '')}" ${ro}>${w && !d.asn ? `<button type="button" class="btn sm" data-dc="asnnext">${tr('Next free number')}</button>` : ''}</span>`)}
      ${opt('amount', tr('Amount'), `<span class="dc-amt"><input id="dc-amount" data-dcp="amount" inputmode="decimal" value="${esc(d.amount ? String(d.amount).replace('.', LOCALE().startsWith('en') ? '.' : ',') : '')}" ${ro}><input id="dc-currency" data-dcp="currency" value="${esc(d.currency || '')}" maxlength="3" aria-label="${esc(tr('Currency'))}" placeholder="EUR" ${ro}></span>`, noAmt)}
      ${!ro && (noDue || noAmt) ? `<div class="row dc-f dc-optbtn"><button type="button" class="linkbtn" data-dc="showopt">${tr('Add')}: ${tr('Due')} / ${tr('Amount')}</button></div>` : ''}
      ${(d.custom_fields || []).map(f => dc_cfRow(d, f, ro)).join('')}
    </div>
    <details class="dc-text"><summary>${tr('Recognised text')}</summary>${d.text ? `<pre>${esc(d.text)}</pre>` : `<p class="muted">${tr('No text recognised.')}</p>`}</details>`;
}
function dc_cfRow(d, f, ro) {  // 2.153.0 (#2179): one custom field of the document
  const id = `dc-cf${f.id}`, v = f.value ?? '', a = `data-dcf="${f.id}"`;
  const input = f.type === 'checkbox' ? `<input type="checkbox" id="${id}" ${a} ${v === '1' ? 'checked' : ''} ${ro}>`
    : f.type === 'select' ? `<select id="${id}" ${a} ${ro}><option value=""></option>${(f.options || []).map(o => `<option value="${esc(o.id)}" ${o.id === v ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>`
    : f.type === 'date' ? dateIn(id, v, {label: f.name, ro: !!ro, attrs: a})
    : f.type === 'money' ? `<input id="${id}" ${a} inputmode="decimal" value="${esc(v ? (LOCALE().startsWith('en') ? v : v.replace('.', ',')) : '')}" placeholder="0,00 EUR" ${ro}>`
    : f.type === 'number' ? `<input id="${id}" ${a} inputmode="decimal" value="${esc(v ? (LOCALE().startsWith('en') ? v : v.replace('.', ',')) : '')}" ${ro}>`
    : f.type === 'url' ? `<span class="dc-amt"><input type="url" id="${id}" ${a} value="${esc(v)}" placeholder="https://" ${ro}>${v && /^https?:\/\//i.test(v) ? `<a class="iconbtn" href="${esc(v)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(tr('Open'))}">${ic('link')}</a>` : ''}</span>`
    : `<input id="${id}" ${a} value="${esc(v)}" maxlength="1000" ${ro}>`;
  return `<div class="row dc-f dc-cf"><label for="${id}">${esc(f.name)}</label>${input}${dc_auto(d, 'cf' + f.id)}</div>`;
}
function dc_val(f, el) {
  const v = el.value.trim();
  if (f === 'tags') return v ? v.split(',').map(x => x.trim()).filter(Boolean) : [];
  if (f === 'amount') return v.replace(/\s/g, '').replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.');
  if (f === 'folder') return v ? +v : '';
  if (f === 'asn') return v ? +v : null;
  return v;
}
function dc_cur(d, f, only) {  // the value of a field as the server takes it back (for the undo)
  if (f === 'sender' || f === 'type') return d[f]?.name || '';
  if (f === 'tags') return d.tags.map(t => t.name);
  if (f === 'folder') return d.folder?.id || '';
  if (f === 'asn') return d.asn || null;
  if (f === 'custom_fields') return Object.fromEntries((d.custom_fields || []).filter(x => !only || String(x.id) in only).map(x => [x.id, x.value ?? null]));  // only the changed ones (their marks stay)
  return d[f] ?? '';
}
async function dc_patch(id, body, label) {
  const before = DC.doc && DC.doc.id === id ? Object.fromEntries(Object.keys(body).map(k => [k, dc_cur(DC.doc, k, body[k])])) : null;
  let d;
  try { d = await api('PATCH', `/api/docs/${id}`, body); } catch { dc_mdDraw($('.dc-md')); return; }
  if (DC.doc?.id === id) { DC.doc = d; dc_mdDraw($('.dc-md')); }
  if (before) {
    const put = v => async () => { const x = await api('PATCH', `/api/docs/${id}`, v); if (DC.doc?.id === id) { DC.doc = x; dc_mdDraw($('.dc-md')); } dc_load(); return {}; };
    histToast(label, histAdd({label, undo: put(before), redo: put(body)}));
  }
  dc_load();
}
async function dc_mdChange(e) {
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
    DC.pt = {};
    DC.set = await api('GET', `/api/docs/settings?ws=${DC.doc.org_id ? 'org:' + DC.doc.org_id : 'private'}`).catch(() => DC.set);
    dc_mdDraw($('.dc-md'));
    return;
  }
  if (f === 'currency') return dc_patch(id, {currency: el.value.trim().toUpperCase()}, tr('Edited {0}', DC.doc.name));
  const label = {sender: tr('Sender of {0} changed', DC.doc.name), type: tr('Type of {0} changed', DC.doc.name), tags: tr('Tags of {0} changed', DC.doc.name),
    folder: tr('Folder of {0} changed', DC.doc.name), asn: tr('Archive number of {0}', DC.doc.name)}[f] || tr('Edited {0}', DC.doc.name);
  await dc_patch(id, {[f]: dc_val(f, el)}, label);
}
async function dc_mdClick(e) {
  const b = e.target.closest('[data-dc]'); if (!b || !DC.doc) return;
  const d = DC.doc, a = b.dataset.dc, md = b.closest('.dc-md');
  if (a === 'close') { md.remove(); return; }
  if (a === 'space') { if (await dc_smvMove(new Map([[d.id, d.org_id || null]]), `“${d.name}”`)) md.remove(); return; }  // 2.96.0 A (#1941)
  if (a === 'view') {
    if (d.einvoice?.source === 'xml') { window.open(`/api/docs/${d.id}/einvoice`, '_blank', 'noopener'); return; }  // 2.146.0 A (#2451)
    if (dc_isPdf(d) && typeof pdfView === 'function') pdfView({url: dc_fileUrl(d), name: d.name, size: d.size, dlUrl: dc_fileUrl(d, true)});
    else if (/^image\//.test(d.mime) && typeof attLightbox === 'function') window.open(dc_fileUrl(d), '_blank', 'noopener');
    else window.open(dc_fileUrl(d), '_blank', 'noopener');
    return;
  }
  if (a === 'showopt') { md.querySelectorAll('.dc-opt').forEach(e => { e.hidden = false; }); const ob = md.querySelector('.dc-optbtn'); if (ob) ob.hidden = true; md.querySelector('.dc-opt input')?.focus(); return; }
  if (a === 'asnnext') { await dc_patch(d.id, {asn: 'next'}, tr('Archive number of {0}', d.name)); return; }
  if (a.startsWith('edit:')) { $(`#dc-${a.slice(5)}`, md)?.focus(); return; }
  if (a === 'redo') { DC.doc = await api('POST', `/api/docs/${d.id}/redo`).catch(() => d); dc_mdDraw(md); dc_load(); return; }
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
    const x = await api('POST', `/api/docs/${d.id}/review`, {done: true}).catch(() => null); if (!x) return;
    DC.doc = {...d, ...x, text: d.text}; dc_mdDraw(md); dc_load();
    histToast(tr('Marked as checked'), histAdd({label: tr('Marked as checked'),
      undo: async () => { await api('POST', `/api/docs/${d.id}/review`, {done: false}); dc_load(); return {}; },
      redo: async () => { await api('POST', `/api/docs/${d.id}/review`, {done: true}); dc_load(); return {}; }}));
    if (DC.f.review) md.remove();
    return;
  }
  if (a === 'task') {
    const x = await api('POST', `/api/docs/${d.id}/task`).catch(() => null); if (!x) return;
    DC.doc = {...d, task_id: x.task_id}; dc_mdDraw(md);
    if (typeof load === 'function') load();
    histToast(tr('Task created: {0}', x.title), histAdd({label: tr('Task created: {0}', x.title),
      undo: async () => { await api('DELETE', `/api/tasks/${x.task_id}`); await api('DELETE', `/api/docs/${d.id}/task`); if (DC.doc?.id === d.id) { DC.doc.task_id = null; dc_mdDraw($('.dc-md')); } return {}; },
      redo: async () => { const y = await api('POST', `/api/docs/${d.id}/task`); x.task_id = y.task_id; return {}; }}));
    return;
  }
  if (a === 'del') {
    try { await api('DELETE', `/api/files/nodes/${d.id}`); } catch { return; }
    md.remove(); dc_load();
    histToast(tr('Document {0} deleted', d.name), histAdd({label: tr('Document {0} deleted', d.name),
      undo: async () => { await api('POST', `/api/files/nodes/${d.id}/restore`); dc_load(); return {}; },
      redo: async () => { await api('DELETE', `/api/files/nodes/${d.id}`); dc_load(); return {}; }}));
  }
}

// ---- settings of a workspace: level per feature, inbox folder, rules, forwarding address
async function dc_settings() {
  const ws = dc_upWs();
  let s; try { s = await api('GET', `/api/docs/settings?ws=${ws}`); } catch { return; }
  DC.set = s;
  const md = modal('<div class="dc-sbody"></div>');
  md.classList.add('dc-smd');
  md.addEventListener('click', dc_sClick);
  md.addEventListener('change', dc_sChange);
  dc_sDraw(md);
}
function dc_wsName(ws) {
  if (ws === 'private') return tr('Your own documents');
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
  $('.dc-sbody', md).innerHTML = `<div class="lhdr"><h3>${tr('Settings of the documents')}</h3><span class="spacer"></span><button class="iconbtn" data-dcs="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="muted">${esc(dc_wsName(s.ws))}${can ? '' : ` · ${tr('Only admins of the organisation can change this')}`}</p>
    <h4>${tr('Sorting automatically')}</h4>
    <p class="muted">${tr('Per feature: rules first, then what Kalmido learnt from your corrections. Sure matches are set directly, unsure ones wait in “To review”. “Left to an agent”: a connected agent with access may fill it in.')}</p>
    ${DC_FEATS.map(([f, n]) => `<div class="row"><label for="dcs-l-${f}">${tr(n)}</label><select id="dcs-l-${f}" data-dcl="${f}" ${dis}>${DC_LEVELS.map(([v, l]) => `<option value="${v}" ${s.levels[f] === v ? 'selected' : ''}>${tr(l)}</option>`).join('')}</select></div>`).join('')}
    <label class="chkl"><input type="checkbox" data-dcs="inbox" ${s.inbox ? 'checked' : ''} ${dis}> ${tr('Recognise files put into the folder “Dokumente/Eingang” of the file store')}</label>
    <div class="row"><label for="dcs-asn">${tr('Prefix of the archive numbers')}</label><input id="dcs-asn" data-dcs="asnprefix" value="${esc(s.asn_prefix || 'ASN')}" maxlength="10" autocomplete="off" ${dis}></div>
    ${s.ocr_missing?.length ? `<p class="muted">${esc(tr('Text recognition is missing: {0}', s.ocr_missing.join(', ')))}</p>` : ''}
    <p class="muted">${esc(tr('Next free number: {0}. A QR code or text like {1} on a scan fills it in.', s.asn_next, `${s.asn_prefix || 'ASN'}${String(s.asn_next).padStart(5, '0')}`))}</p>
    <p class="muted">${esc(tr('A stack scan with several codes can be split into documents; a separator sheet between two letters splits there too.'))} <a href="/api/docs/split-sheet.pdf" target="_blank" rel="noopener">${tr('Separator sheet to print (PDF)')}</a></p>${'' /* 2.154.0 A (#1111) */}
    <h4>${tr('Rules')}</h4>
    ${s.rules.length ? `<ul class="dc-rules">${s.rules.map(rule).join('')}</ul>` : `<p class="muted">${tr('No rules yet.')}</p>`}
    ${can ? `<details class="dc-radd"><summary>${tr('New rule')}</summary>
      <div class="row"><label for="dcr-kind">${tr('If the document')}</label><select id="dcr-kind">${DC_KINDS.map(([v, l]) => `<option value="${v}">${tr(l)}</option>`).join('')}</select></div>
      <div class="row"><label for="dcr-match">${tr('Words or pattern')}</label><input id="dcr-match" maxlength="200" autocomplete="off"></div>
      <div class="row"><label for="dcr-sender">${tr('then sender')}</label><input id="dcr-sender" maxlength="120" list="dcr-sl" autocomplete="off"><datalist id="dcr-sl">${s.senders.map(x => `<option value="${esc(x.name)}">`).join('')}</datalist></div>
      <div class="row"><label for="dcr-type">${tr('then document type')}</label><input id="dcr-type" maxlength="120" list="dcr-tl" autocomplete="off"><datalist id="dcr-tl">${s.types.map(x => `<option value="${esc(x.name)}">`).join('')}</datalist></div>
      <div class="row"><label for="dcr-tags">${tr('then tags')}</label><input id="dcr-tags" maxlength="300" placeholder="${esc(tr('comma-separated'))}" autocomplete="off"></div>
      <div class="row"><label for="dcr-folder">${tr('then folder')}</label><input id="dcr-folder" maxlength="120" list="dcr-fl" autocomplete="off"><datalist id="dcr-fl">${s.folders.map(x => `<option value="${esc(x.name)}">`).join('')}</datalist></div>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn pri" data-dcs="radd">${tr('Add rule')}</button></div></details>` : ''}
    ${can ? `<h4>${tr('Senders, types and tags')}</h4>${[['sender', 'senders', N_('Senders')], ['type', 'types', N_('Document types')], ['tag', 'tags', N_('Tags')]].map(([k, key, n]) =>
      `<details class="dc-lbls"><summary>${tr(n)} (${(s[key] || []).length})</summary>${(s[key] || []).length ? `<ul class="dc-rules">${s[key].map(x => `<li class="dc-rule"><span>${esc(x.name)}</span><span>
        <button type="button" class="iconbtn" data-dcs="lren:${k}:${x.id}" aria-label="${esc(tr('Rename'))}" title="${esc(tr('Rename'))}">${ic('edit')}</button>
        <button type="button" class="iconbtn" data-dcs="ldel:${k}:${x.id}" aria-label="${esc(tr('Delete {0}', x.name))}" title="${esc(tr('Delete {0}', x.name))}">${ic('trash')}</button></span></li>`).join('')}</ul>` : ''}</details>`).join('')}` : ''}
    ${can ? dc_cfSettings(s) : ''}
    ${typeof dsc_slot === 'function' ? dsc_slot(s) : s.mail.enabled ? `<h4>${tr('Forward by e-mail')}</h4><p class="muted">${tr('PDFs and images attached to mails sent to this address become documents here.')}</p>
      ${s.mail.address ? `<p class="dc-mail"><code>${esc(s.mail.address)}</code> <button type="button" class="linkbtn" data-dcs="mailnew">${tr('New address')}</button> <button type="button" class="linkbtn" data-dcs="maildel">${tr('Turn off')}</button></p>`
        : `<button type="button" class="btn sm" data-dcs="mailnew">${tr('Create address')}</button>`}` : ''}${'' /* 2.207.0 A (#2763): docscan.js = scans from your computer + mail */}
    ${typeof pl_slot === 'function' ? pl_slot(s) : ''}`;  // 2.48.0 (#1152): Paperless-ngx (paperless.js, self-hosted only)
}
function dc_cfSettings(s) {  // 2.153.0 (#2179): the custom fields of the workspace (nothing preset)
  const fs = s.fields || [];
  return `<h4>${tr('Custom fields')}</h4>
    <p class="muted">${tr('Extra fields every document of this workspace can have, e.g. a contract or customer number.')}</p>
    ${fs.length ? `<ul class="dc-rules">${fs.map(f => `<li class="dc-rule"><span>${esc(f.name)} <span class="muted">${esc(tr(DC_CFTYPES.find(t => t[0] === f.type)?.[1] || f.type))}${f.type === 'select' ? `: ${esc((f.options || []).map(o => o.name).join(', '))}` : ''}</span></span><span>
      ${f.type === 'select' ? `<button type="button" class="iconbtn" data-dcs="fopt:${f.id}" aria-label="${esc(tr('Options'))}" title="${esc(tr('Options'))}">${ic('list')}</button>` : ''}
      <button type="button" class="iconbtn" data-dcs="fren:${f.id}" aria-label="${esc(tr('Rename'))}" title="${esc(tr('Rename'))}">${ic('edit')}</button>
      <button type="button" class="iconbtn" data-dcs="fdel:${f.id}" aria-label="${esc(tr('Delete {0}', f.name))}" title="${esc(tr('Delete {0}', f.name))}">${ic('trash')}</button></span></li>`).join('')}</ul>` : ''}
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
  if (e.target.matches('[data-dcs="ftype"]')) { const o = md.querySelector('.dcf-opts'); if (o) o.hidden = e.target.value !== 'select'; return; }  // 2.153.0 (#2179)
  if (e.target.matches('[data-dcs="inbox"]')) { DC.set = await api('PUT', '/api/docs/settings', {ws: s.ws, inbox: e.target.checked}).catch(() => s); dc_sDraw(md); }
}
async function dc_sClick(e) {
  const b = e.target.closest('[data-dcs]'); if (!b || b.matches('input')) return;
  const s = DC.set, md = b.closest('.dc-smd'), a = b.dataset.dcs;
  if (a === 'close') { md.remove(); return; }
  if (a === 'fadd' || /^f(ren|opt|del):/.test(a)) return dc_cfAct(a, s, md);  // 2.153.0 (#2179)
  if (a === 'radd') {
    const v = id => ($(`#${id}`, md)?.value || '').trim();
    const r = {ws: s.ws, kind: v('dcr-kind'), match: v('dcr-match'), sender: v('dcr-sender'), type: v('dcr-type'), tags: v('dcr-tags'), folder: v('dcr-folder')};
    let j; try { j = await api('POST', '/api/docs/rules', r); } catch { return; }
    s.rules = j.rules; dc_sDraw(md);
    histToast(tr('Rule added'), histAdd({label: tr('Rule added'), sett: true,
      undo: async () => { const x = await api('DELETE', `/api/docs/rules/${j.id}`); if (DC.set) { DC.set.rules = x.rules; dc_sDraw($('.dc-smd')); } return {}; },
      redo: async () => { const x = await api('POST', '/api/docs/rules', r); j.id = x.id; if (DC.set) { DC.set.rules = x.rules; dc_sDraw($('.dc-smd')); } return {}; }}));
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
  if (a === 'mailnew') {
    if (s.mail.address && !await askConfirm(tr('New address?'), tr('The old address stops working.'), {ok: tr('New address')})) return;
    const j = await api('POST', '/api/docs/mail', {ws: s.ws}).catch(() => null); if (!j) return;
    s.mail.address = j.address; dc_sDraw(md);
    return;
  }
  if (a === 'maildel') {
    if (!await askConfirm(tr('Turn off the address?'), tr('Mails to it no longer arrive.'), {ok: tr('Turn off'), danger: true})) return;
    await api('DELETE', `/api/docs/mail?ws=${encodeURIComponent(s.ws)}`).catch(() => null);
    s.mail.address = ''; dc_sDraw(md);
  }
}

// ---- events of the view (delegated once)
let dc_qTimer = null;
document.addEventListener('click', e => {
  const v = e.target.closest('.dc-view'); if (!v) return;
  const o = e.target.closest('[data-dco]');
  if (o && (DC.selOn || (e.shiftKey && typeof dt_rsMouse === 'function' && dt_rsMouse(e)))) { dc_rsClick(e, +o.dataset.dco); return; }  // 2.96.0 A (#1941): choosing, not opening; 2.122.0 B (#2295): Shift ranges
  if (o) { history.replaceState(null, '', `#docs/${o.dataset.dco}`); dc_open(+o.dataset.dco); return; }
  const b = e.target.closest('[data-dc]'); if (!b) return;
  const a = b.dataset.dc;
  if (a === 'scan') { abm_scanOpen({docs: true}); return; }  // 2.112.1 A (#2058): photographed pages -> one PDF -> a document
  if (a === 'settings') dc_settings();
  else if (a === 'all' || a === 'review') { DC.f.review = a === 'review'; dc_load(); dc_draw(); }
  else if (a === 'more') { if (isMobile()) dc_fSheet(); else { DC.more = !DC.more; dc_draw(); } }  // 2.122.0 B (#2294): phones: a sheet
  else if (a === 'clear') { DC.f = {...dc_f0(), review: DC.f.review}; DC.q = ''; dc_load(); }
  else if (a === 'under-off') { DC.under = null; dc_load(); if (typeof sbb_sync === 'function') sbb_sync('ablage'); }
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
const dc_hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
document.addEventListener('dragenter', e => { const v = e.target.closest?.('.dc-view'); if (!v || !dc_hasFiles(e)) return; DC.drag++; v.classList.add('dragging'); });
document.addEventListener('dragleave', e => { const v = e.target.closest?.('.dc-view'); if (!v) return; DC.drag = Math.max(0, DC.drag - 1); if (!DC.drag) v.classList.remove('dragging'); });
document.addEventListener('dragover', e => { if (e.target.closest?.('.dc-view') && dc_hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
document.addEventListener('drop', e => {
  const v = e.target.closest?.('.dc-view'); if (!v || !dc_hasFiles(e)) return;
  e.preventDefault(); e.stopPropagation(); DC.drag = 0; v.classList.remove('dragging');
  dc_upload(e.dataTransfer.files);
});
document.addEventListener('visibilitychange', () => { if (!document.hidden && DC.waiting) dc_pollSet(); });

// ---- 2.96.0 A (#1941): choose documents (one, several, or every one the filters find) and move them into the other workspace
// (private <-> organisation): into the documents folder there, with sender, type and tags. ONE undo step (back to the old folders).
DC.sel = new Map();  // id -> org_id of the chosen documents (also those beyond the shown page: "Select all")
DC.selOn = false;
const DC_SMV_MAX = 2000;  // the server's limit per move (accounts/spacemove.py SMV_MAX)
const dc_smvBtn = () => DC.docs?.length ? `<button type="button" class="btn sm ${DC.selOn ? 'on' : ''}" data-dcsel="mode" aria-pressed="${DC.selOn}">${ic('check', 's')} <span>${tr('Select')}</span></button>` : '';
function dc_smvToggle(id) {
  const d = (DC.docs || []).find(x => x.id === id); if (!d) return;
  if (DC.sel.has(id)) DC.sel.delete(id); else DC.sel.set(id, d.org_id || null);
  dc_draw();
}
function dc_smvBar() {
  if (!DC.selOn) return '';
  const n = DC.sel.size, orgs = new Set(DC.sel.values()), from = orgs.size === 1 ? [...orgs][0] : null;
  return `<div class="dc-selbar" role="toolbar" aria-label="${esc(tr('Selection'))}"><span class="dc-seln" aria-live="polite">${esc(tr('{0} selected', n))}</span>
    ${n < DC.total ? `<button type="button" class="linkbtn" data-dcsel="all">${esc(tr('Select all {0}', DC.total))}</button>` : `<button type="button" class="linkbtn" data-dcsel="none">${tr('Select none')}</button>`}<span class="spacer"></span>
    <button type="button" class="btn sm" data-dcsel="csv" ${n ? '' : 'disabled'}>${tr('Export as CSV')}</button>
    ${orgs.size <= 1 && smv_can(from) ? `<button type="button" class="btn sm" data-dcsel="space" ${n ? '' : 'disabled'}>${ic('building', 's')} ${tr('Move to another workspace…')}</button>` : ''}
    <button type="button" class="btn sm" data-dcsel="edit" aria-haspopup="menu" ${n ? '' : 'disabled'}>${ic('edit', 's')} ${tr('Edit')}</button><button type="button" class="btn sm" data-dcsel="zip" ${n ? '' : 'disabled'}>${ic('download', 's')} ${tr('ZIP')}</button>
    <button type="button" class="iconbtn" data-dcsel="off" aria-label="${esc(tr('Cancel'))}" title="${esc(tr('Cancel'))}">${ic('x')}</button></div>`;
}
async function dc_smvAll() {  // every document the search and the filters find (page by page, at most DC_SMV_MAX)
  const p = dc_params(), out = new Map();
  p.set('facets', '0'); p.set('limit', '200');
  for (let off = 0; off < DC_SMV_MAX; off += 200) {
    p.set('offset', String(off));
    let j; try { j = await api('GET', '/api/docs?' + p); } catch { return; }
    for (const d of j.docs || []) out.set(d.id, d.org_id || null);
    if ((j.docs || []).length < 200) break;
  }
  if (DC.total > DC_SMV_MAX) toast(tr('Too many at once: at most {0}', DC_SMV_MAX));
  DC.sel = out; dc_draw();
}
async function dc_smvMove(sel, what) {
  const orgs = new Set(sel.values());
  if (orgs.size !== 1) { toast(tr('Choose items of one workspace')); return null; }
  const ids = [...sel.keys()], from = [...orgs][0];
  let last = null;
  const r = await smv_open({what, from, total: ids.length,  // 2.147.1 B (#2230): batches + progress
    check: async to => { try { return await rawFetch('POST', '/api/files/move-space', {ids, to: smv_ws(to), parent: 'docs', dry: 1}); } catch (x) { return {block: x.message || tr('The check failed. Please try again.')}; } },
    run: (to, _p, _o, step) => { last = {ids, to: smv_ws(to), parent: 'docs'}; return smv_post('/api/files/move-space', last, 'ids', step); }});
  if (!r?.moved || !last) return null;
  DC.sel = new Map(); DC.selOn = false; DC.facets = null;
  dc_load();
  const req = async (b, key) => { try { await smv_post('/api/files/move-space', b, key); } catch { /* shown */ } DC.facets = null; dc_load(); return {}; };
  const back = {items: r.moved.map(m => ({id: m.id, parent: m.parent_was, name: m.name_was})), to: smv_ws(r.org_was)}, again = last;
  offerUndo(smv_label(r, ids.length), histAdd({label: tr('Move to another workspace'), undo: () => req(back, 'items'), redo: () => req(again, 'ids')}));
  return r;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-dcsel]'); if (!b || !b.closest('.dc-view')) return;
  const a = b.dataset.dcsel;
  if (a === 'mode') { DC.selOn = !DC.selOn; DC.sel = new Map(); dc_draw(); }
  else if (a === 'off') { DC.selOn = false; DC.sel = new Map(); dc_draw(); }
  else if (a === 'all') dc_smvAll();
  else if (a === 'none') { DC.sel = new Map(); dc_draw(); }
  else if (a === 'csv') dcx_csv();  // 2.122.0 (#2100)
  else if (a === 'space') dc_smvMove(DC.sel, trn('{0} document', '{0} documents', DC.sel.size));
  else if (a === 'edit') dc_bulkMenu(b);  // 2.122.0 B (#2294)
  else if (a === 'zip') dc_zip();
});

// 2.122.0 (#2100): the chosen documents as a CSV file (the server leaves out what the person may not see)
async function dcx_csv() {
  const ids = [...DC.sel.keys()]; if (!ids.length) return;
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
  return {sender: [], type: [], tag: '', tg: {}, tmode: 'any', from: '', to: '', afrom: '', ato: '', folder: [], ftype: [], notag: false, nosender: false, review: false};
}
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
  return out;
}
function dc_fbarHtml() {
  const es = dc_fEntries(), q = DC.q.trim();
  if (!es.length && !q) return '';
  return `<div class="tsfbar dc-fbar" role="group" aria-label="${esc(tr('Filter'))}">${q ? `<button type="button" class="tsfx" data-dcx="q" aria-label="${esc(tr('Remove filter {0}', q))}">„${esc(q)}“ ${ic('x', 's')}</button>` : ''}
    ${es.map((e, i) => `<button type="button" class="tsfx ${e.not ? 'not' : ''}" data-dcx="${i}" aria-label="${esc(tr('Remove filter {0}', e.label))}">${e.not ? `${tr('not')} ` : ''}${esc(e.label)} ${ic('x', 's')}</button>`).join('')}
    ${Object.values(DC.f.tg || {}).filter(x => x === 'in').length > 1 ? `<span class="tsfn">${DC.f.tmode === 'all' ? tr('every one') : tr('one of them')}</span>` : ''}
    ${DC.docs ? `<span class="tsfn" aria-live="polite">${esc(trn('{0} hit', '{0} hits', DC.total))}</span>` : ''}<button type="button" class="linkbtn" data-dc="clear">${tr('Reset filters')}</button></div>`;
}
function dc_fltHtml() {  // the filters (desktop: below the bar; phones: the sheet)
  const f = DC.f, fc = DC.facets || {senders: [], types: [], tags: [], folders: []};
  const st = (list, sel) => Object.fromEntries((list || []).filter(x => sel(x.ids.join(','))).map(x => [x.name, sel(x.ids.join(','))]));
  const tagSt = st(fc.tags, ids => (f.tg || {})[ids]), on = Object.values(f.tg || {}).filter(x => x === 'in').length;
  const two = (k, list) => dt_pills(list, st(list, ids => dc_arr(f[k]).includes(ids) ? 'in' : ''), 'dcf' + k, false);
  const sec = (title, inner) => inner ? `<h4>${esc(tr(title))}</h4><div class="tsgrp">${inner}</div>` : '';
  const pick = typeof dt_pills === 'function';
  return `<div class="tsflt">
    ${pick ? sec(N_('Tags'), dt_pills(fc.tags, tagSt, 'dcftg')) : ''}${pick && on > 1 ? `<div class="tsrow"><div class="seg" role="radiogroup" aria-label="${esc(tr('Several tags'))}">${['any', 'all'].map(m => `<button type="button" role="radio" data-dcfm="${m}" aria-checked="${(f.tmode || 'any') === m}">${m === 'all' ? tr('every one') : tr('one of them')}</button>`).join('')}</div></div>` : ''}
    ${pick ? sec(N_('Sender'), two('sender', fc.senders)) + sec(N_('Document type'), two('type', fc.types)) + sec(N_('Folder'), two('folder', fc.folders)) : ''}
    <h4>${tr('File type')}</h4><div class="tsgrp">${DC_FTYPES.map(([k, l]) => `<button type="button" class="tsp ${dc_arr(f.ftype).includes(k) ? 'tsp-in' : ''}" data-dcfft="${k}" aria-pressed="${dc_arr(f.ftype).includes(k)}">${esc(tr(l))}</button>`).join('')}</div>
    <h4>${tr('Document date')}</h4><div class="tsrow"><span class="dc-range">${tr('from')} ${dateIn('dc-ffrom', f.from, {label: tr('Document date from {0}', ''), attrs: 'data-dcf2="from"'})}</span><span class="dc-range">${tr('to')} ${dateIn('dc-fto', f.to, {label: tr('Document date to {0}', ''), attrs: 'data-dcf2="to"'})}</span></div>
    <h4>${tr('Date of arrival')}</h4><div class="tsrow"><span class="dc-range">${tr('from')} ${dateIn('dc-fafrom', f.afrom, {label: tr('Arrived from {0}', ''), attrs: 'data-dcf2="afrom"'})}</span><span class="dc-range">${tr('to')} ${dateIn('dc-fato', f.ato, {label: tr('Arrived to {0}', ''), attrs: 'data-dcf2="ato"'})}</span></div>
    <div class="tsrow"><label><input type="checkbox" data-dcf2="notag" ${f.notag ? 'checked' : ''}> ${tr('Without tag')}</label><label><input type="checkbox" data-dcf2="nosender" ${f.nosender ? 'checked' : ''}> ${tr('Without sender')}</label></div>
    <p class="muted dc-syn">${esc(tr('In the search field: tag:Name, absender:Name, typ:Name, datum:2025 or datum:2025-01..2025-03, "exact text", -word'))}</p></div>`;
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
  const f = DC.f, fc = DC.facets || {};
  const b = e.target.closest('[data-dcftg], [data-dcfsender], [data-dcftype], [data-dcffolder], [data-dcfft], [data-dcfm]'); if (!b) return;
  const ids = (list, name) => (list || []).find(x => x.name === name)?.ids.join(',');
  if (b.dataset.dcftg != null) {
    const k = ids(fc.tags, b.dataset.dcftg); if (!k) return;
    f.tg = {...(f.tg || {})}; const s = f.tg[k]; if (!s) f.tg[k] = 'in'; else if (s === 'in') f.tg[k] = 'not'; else delete f.tg[k];
    if (f.tag === k) f.tag = '';
  } else if (b.dataset.dcfm) f.tmode = b.dataset.dcfm;
  else if (b.dataset.dcfft) { const v = b.dataset.dcfft, a = dc_arr(f.ftype); f.ftype = a.includes(v) ? a.filter(x => x !== v) : [...a, v]; }
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
  DC.f[k] = el.type === 'checkbox' ? el.checked : el.value;
  dc_fChanged();
});
// ---- 2.122.0 B (#2295): Shift-click chooses a range of cards (tagsel.js dt_rsClick), Shift-click without choosing turns it on
function dc_rsClick(e, id) {
  if (typeof dt_rsClick !== 'function') { dc_smvToggle(id); return; }
  if (!DC.selOn) { DC.selOn = true; DC.sel = new Map(); dt_rsReset(); }
  const docs = DC.docs || [];
  dt_rsClick(e, 'dc:' + dc_params(), id, docs.map(d => d.id), x => DC.sel.has(x), (x, on) => {
    const d = docs.find(y => y.id === x);
    if (on && d) DC.sel.set(x, d.org_id || null); else if (!on) DC.sel.delete(x);
  });
  dc_draw();
}

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
const dc_chunks = (a, n) => Array.from({length: Math.ceil(a.length / n)}, (_, i) => a.slice(i * n, i * n + n));
async function dc_bulk(change, label) {
  const ids = [...DC.sel.keys()]; if (!ids.length) return;
  const req = dc_chunks(ids, DC_BULK).map(part => ({ids: part, ...change}));
  let r; try { r = await dc_bulkSend(req); } catch { dc_load(); return; }
  DC.facets = null; dc_load();
  if (r.denied) toast(trn('{0} document may only be viewed by you and stays as it is', '{0} documents may only be viewed by you and stay as they are', r.denied));
  if (!r.changed.length) { if (!r.denied) toast(tr('Nothing to change')); return; }
  const back = dc_chunks(r.before, DC_BULK).map(part => ({restore: part}));
  const step = bodies => async () => { try { await dc_bulkSend(bodies); } catch { /* shown */ } DC.facets = null; dc_load(); return {}; };
  histToast(`${label}: ${trn('{0} document', '{0} documents', r.changed.length)}`, histAdd({label, undo: step(back), redo: step(req)}));
}
function dc_bulkMenu(anchor) {
  menu(anchor, [{label: tr('Add tags…'), icon: 'tag', fn: () => dc_bulkTags(true)}, {label: tr('Remove tags…'), icon: 'tag', fn: () => dc_bulkTags(false)},
    {label: tr('Set document type…'), icon: 'file', fn: () => dc_bulkSet('type')}, {label: tr('Set sender…'), icon: 'user', fn: () => dc_bulkSet('sender')}], null, null, tr('Edit'));
}
async function dc_bulkTags(add) {
  const known = (DC.docs || []).filter(d => DC.sel.has(d.id)).flatMap(d => d.tags.map(t => t.name));
  const all = add ? (DC.facets?.tags || []) : [...new Set(known)].map(name => ({name}));
  const n = DC.sel.size;
  const names = await dt_pick({title: add ? trn('Add tags to {0} document', 'Add tags to {0} documents', n) : trn('Remove tags from {0} document', 'Remove tags from {0} documents', n),
    all: add ? all : (all.length ? all : DC.facets?.tags || []), cur: [], ok: add ? tr('Add') : tr('Remove')});
  if (!names?.length) return;
  dc_bulk(add ? {add_tags: names} : {remove_tags: names}, add ? tr('Tags added') : tr('Tags removed'));
}
async function dc_bulkSet(kind) {
  const list = (kind === 'type' ? DC.facets?.types : DC.facets?.senders) || [];
  const v = await askDialog({title: kind === 'type' ? tr('Document type of the chosen documents ({0})', DC.sel.size) : tr('Sender of the chosen documents ({0})', DC.sel.size), ok: tr('Save'),
    input: {value: '', max: 120, placeholder: kind === 'type' ? tr('e.g. Invoice, Contract, Letter') : tr('Sender')},
    after: md => { const i = $('#cdlg-in', md); if (!i) return; const dl = document.createElement('datalist'); dl.id = 'dc-bulkdl'; dl.innerHTML = list.map(x => `<option value="${esc(x.name)}">`).join(''); i.setAttribute('list', dl.id); i.after(dl); }});
  if (v == null || !String(v).trim()) return;
  dc_bulk({[kind]: String(v).trim()}, kind === 'type' ? tr('Document type set') : tr('Sender set'));
}
async function dc_zip() {
  const ids = [...DC.sel.keys()]; if (!ids.length) return;
  let r; try { r = await api('POST', '/api/docs/zip', {ids}); } catch { return; }  // too many / too large: the server's hint is the toast
  toast(trn('The ZIP with {0} document is being prepared…', 'The ZIP with {0} documents is being prepared…', r.files));
  const a = document.createElement('a'); a.href = r.url; a.download = ''; document.body.appendChild(a); a.click(); a.remove();
}

// 2.199.0 B (#2742): the folders of the documents in the panel (sbb_treeHtml, below the entry "Documents"): one entry per
// workspace under "All workspaces" (a single workspace: its folders directly), the whole tree below the documents folder
// (subfolders drawn once opened). A folder shows its documents and those of its subfolders (?under=); the workspace's
// entry all of them. The folders come from /api/docs/settings (folder_tree), loaded once per workspace, again after a change.
DC.pt = {};
async function dc_ptLoad(ws) {
  const e = DC.pt[ws] || (DC.pt[ws] = {}); if (e.busy) return;
  e.busy = true;
  try { const j = await rawFetch('GET', `/api/docs/settings?ws=${encodeURIComponent(ws)}`); e.items = j.folders || []; e.root = j.root_id || null; }
  catch { e.items = e.items || []; }
  finally { e.busy = false; e.stale = false; }
  if (typeof sbb_sync === 'function') sbb_sync('ablage');
}
const dc_ptGet = ws => { const e = DC.pt[ws]; if (!e || e.stale) dc_ptLoad(ws); return e?.items ? e : null; };
function dc_wsList() {
  const w = dc_ws();
  return w === 'all' ? ['private', ...(S.me?.workspaces || []).filter(x => x.id).map(x => 'org:' + x.id)] : [dc_upWs()];
}
function dc_panelTree() {
  const on = S.route.mod === 'docs', wss = dc_wsList();
  const node = (f, all) => ({k: 'dc:' + f.id, name: f.name, go: 'docs', on: on && DC.under === f.id, icon: 'folder', battrs: `data-dcunder="${f.id}"`,
    ns: 'dc', id: f.id, par: 'n:' + f.parent_id, drag: ab_canWrite(f.role), drop: ab_canWrite(f.role), menu: true,  // 2.199.0 A tree: drag / sort / menu
    kids: all.some(x => x.parent_id === f.id), sub: () => all.filter(x => x.parent_id === f.id).map(x => node(x, all))});
  const tops = e => e.items.filter(x => x.depth === 0).map(x => node(x, e.items));
  if (wss.length === 1) {
    const e = dc_ptGet(wss[0]);
    return `<div class="sbbtree dc-ptree" aria-label="${esc(tr('Folders'))}">${e ? sbb_treeHtml(tops(e), 1) : `<p class="muted sbbtl" style="--sbbl:1">${esc(tr('Loading…'))}</p>`}</div>`;
  }
  const wsNode = ws => { const e = DC.pt[ws];
    return {k: 'dc:w:' + ws, name: dc_wsName(ws), go: 'docs', on: on && !!e?.root && DC.under === e.root, icon: ws === 'private' ? 'home' : 'folder',
      battrs: `data-dcunder="${e?.root || ''}" data-dcws="${esc(ws)}"`, kids: e?.items ? e.items.length > 0 : true, sub: () => (x => x && tops(x))(dc_ptGet(ws))}; };
  return `<div class="sbbtree dc-ptree" aria-label="${esc(tr('Folders'))}">${sbb_treeHtml(wss.map(wsNode), 1)}</div>`;
}
// the tree's moves / order / menu (sbb_treeReg): the file store's own steps on the folder (ablage.js), then the tree loads again
function dc_ptItem(id) {
  for (const e of Object.values(DC.pt)) { const f = (e.items || []).find(x => String(x.id) === String(id)); if (f) return {...f, kind: 'folder', ws: e}; }
  return null;
}
function dc_ptStale() { for (const e of Object.values(DC.pt)) e.stale = true; if (typeof sbb_sync === 'function') sbb_sync('ablage'); }
sbb_treeReg('dc', {
  move: async (id, into) => { const n = dc_ptItem(id); if (n) { await ab_move(n, +into); dc_ptStale(); } },
  order: async (id, pos) => {
    const n = dc_ptItem(id); if (!n) return;
    const b = pos.before ? {before: +pos.before} : pos.after ? {after: +pos.after} : {};
    if (pos.into !== undefined && String(pos.into).startsWith('n:') && +String(pos.into).slice(2) !== n.parent_id) b.parent_id = +String(pos.into).slice(2);
    try { await api('POST', `/api/files/nodes/${n.id}/order`, b); } catch { return; }
    dc_ptStale();
  },
  menu: id => { const n = dc_ptItem(id); return n ? ab_menuItems(n, true).map(x => x && x.fn ? {...x, fn: async () => { await x.fn(); setTimeout(dc_ptStale, 400); }} : x) : []; }});
function dc_underPath() {
  for (const e of Object.values(DC.pt)) {
    if (e.root && e.root === DC.under) return tr('Documents');
    const f = (e.items || []).find(x => x.id === DC.under); if (f) return tr('Documents') + ' / ' + f.path;
  }
  return tr('Folder');
}
function dc_underHtml() {
  return DC.under ? `<p class="dc-under">${ic('folder', 's')} <span>${esc(dc_underPath())}</span> <button type="button" class="iconbtn sm" data-dc="under-off" aria-label="${esc(tr('Show all documents'))}" title="${esc(tr('Show all documents'))}">${ic('x', 's')}</button></p>` : '';
}
if (typeof sbb_sync === 'function') setTimeout(() => sbb_sync('ablage'), 0);  // the panel was drawn before this module came: its tree now
// a folder in the panel: picked before the click's data-go opens #docs (capture: ahead of the router's click)
document.addEventListener('click', e => {
  const b = e.target.closest?.('#side [data-dcunder]'); if (!b) return;
  if (!b.dataset.dcunder && b.dataset.dcws) { dc_ptLoad(b.dataset.dcws); return; }
  DC.under = +b.dataset.dcunder || null; DC.at = 0;
  if (S.route.mod === 'docs') setTimeout(dc_load, 0);
}, true);
