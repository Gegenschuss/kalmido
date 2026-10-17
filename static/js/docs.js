/* Kalmido web client: Documents (2.48.0, #1111): the list (cards with a preview), filters, full-text search, upload by
   dragging, the document sheet (preview, fields with "automatic" marks, suggestions "To review", recognised text) and the
   settings of a workspace (level per feature, rules, the forwarding address). Route #docs (area "Ablage", areas.js), a
   document: #docs/<id>. Classic script sharing the global scope with the others (load order: index.html). */
'use strict';

const DC = {docs: null, total: 0, review: 0, waiting: 0, facets: null, err: null, loading: false, seq: 0, q: '',
  f: {sender: '', type: '', tag: '', from: '', to: '', review: false}, more: false, poll: null, doc: null, set: null, drag: 0};
const DC_FEATS = [['sender', N_('Sender')], ['type', N_('Document type')], ['tags', N_('Tags')], ['folder', N_('Folder')]];
const DC_LEVELS = [['learn', N_('Learns from your documents')], ['rules', N_('Rules only')], ['agent', N_('Left to an agent')], ['off', N_('Off')]];
const DC_KINDS = [['any', N_('contains one of the words')], ['all', N_('contains all words')], ['exact', N_('contains the exact phrase')],
  ['fuzzy', N_('contains the phrase (tolerates typos)')], ['regex', N_('matches the pattern (regular expression)')]];
const DC_STATE = {wait: N_('Waiting for recognition'), run: N_('Recognising…'), done: N_('Recognised'), failed: N_('Recognition failed')};
const DC_BY = {rule: N_('set by a rule'), learn: N_('learnt from your documents'), agent: N_('set by an agent'), import: N_('imported'), code: N_('read from the code on the document')};

// the module switch (Settings > Modules), off by default like the other areas
FEATS.push(['docs', N_('Documents')]);
FEAT_DESC.docs = N_('Scanned letters, invoices and contracts: text recognition, full-text search, sorting by rules and by what Kalmido learns from your corrections, due dates as tasks');
const dc_ws = () => (typeof wsCur === 'function' ? wsCur() : 'all');
const dc_upWs = () => { const w = dc_ws(); return w.startsWith('org:') ? w : 'private'; };
const dc_hashId = () => { try { const m = location.hash.match(/^#docs\/(\d+)/); return m ? +m[1] : null; } catch { return null; } };  // the sheet may close after its window is gone
const dc_money = (a, cur) => a == null || a === '' ? '' : `${(+a).toLocaleString(LOCALE(), {minimumFractionDigits: 2, maximumFractionDigits: 2})} ${cur === 'EUR' ? '€' : cur === 'USD' ? '$' : (cur || '')}`.trim();
const dc_day = d => d ? dayLabel(d, true) : '';
const dc_isPdf = d => d && (d.mime === 'application/pdf' || /\.pdf$/i.test(d.name));
const dc_fileUrl = (d, dl) => `/api/docs/${d.id}/file?v=${d.size}${dl ? '&dl=1' : ''}`;

// ---- loading
function dc_params() {
  const p = new URLSearchParams({ws: dc_ws(), limit: '200'});
  if (DC.q.trim()) p.set('q', DC.q.trim());
  for (const k of ['sender', 'type', 'tag', 'from', 'to']) if (DC.f[k]) p.set(k, DC.f[k]);
  if (DC.f.review) p.set('review', '1');
  return p;
}
async function dc_load() {
  const seq = ++DC.seq;
  DC.loading = true;
  try {
    const j = await api('GET', '/api/docs?' + dc_params());
    if (seq !== DC.seq) return;
    Object.assign(DC, {docs: j.docs, total: j.total, review: j.review, waiting: j.waiting, facets: j.facets || DC.facets, err: null});
  } catch (x) { if (seq === DC.seq) DC.err = x.message || tr('unknown'); }
  DC.loading = false;
  dc_draw();
  dc_pollSet();
}
function dc_pollSet() {  // while documents are being recognised, look again every few seconds
  clearTimeout(DC.poll);
  if (DC.waiting && S.route.mod === 'docs' && !document.hidden) DC.poll = setTimeout(() => S.route.mod === 'docs' && dc_load(), 4000);
}
function dc_draw() {
  if (S.route.mod !== 'docs') return;
  const el = $('#view'); if (!el) return;
  keepFocus(el, () => setHtml(el, typeof mg_wrap === 'function' ? mg_wrap('docs', viewDocs()) : viewDocs()));
}

// ---- the view
function viewDocs() {
  if (!DC.docs && !DC.loading && !DC.err) setTimeout(dc_load, 0);
  const id = dc_hashId();
  if (id && (!DC.doc || DC.doc.id !== id) && !$('.dc-md')) setTimeout(() => dc_open(id), 0);
  const fc = DC.facets || {senders: [], types: [], tags: []};
  const sel = (k, list, label) => `<select data-dcf="${k}" aria-label="${esc(tr(label))}"><option value="">${esc(tr(label))}</option>${list.map(x => {
    const v = x.ids.join(','); return `<option value="${esc(v)}" ${DC.f[k] === v ? 'selected' : ''}>${esc(x.name)}</option>`; }).join('')}</select>`;
  const active = ['sender', 'type', 'tag', 'from', 'to'].some(k => DC.f[k]);
  const head = `
    <div class="dc-bar">
      <input type="search" id="dc-q" value="${esc(DC.q)}" placeholder="${esc(tr('Search in the documents…'))}" aria-label="${esc(tr('Search in the documents'))}" autocomplete="off">
      <div class="seg dc-seg" role="tablist"><button type="button" role="tab" data-dc="all" aria-selected="${!DC.f.review}">${tr('All')}</button><button type="button" role="tab" data-dc="review" aria-selected="${DC.f.review}">${tr('To review')}${DC.review ? ` <span class="dc-count">${DC.review}</span>` : ''}</button></div>
      <button type="button" class="btn sm ${active ? 'on' : ''}" data-dc="more" aria-expanded="${DC.more || active}">${ic('search', 's')} ${tr('Filter')}</button>
      <span class="dc-acts2"><label class="btn pri dc-up" title="${esc(tr('Add documents'))}">${ic('plus', 's')} <span>${tr('Add documents')}</span><input type="file" id="dc-file" multiple accept="application/pdf,image/*,.pdf,.txt" hidden></label>
      <button type="button" class="iconbtn" data-dc="settings" aria-label="${esc(tr('Settings of the documents'))}" title="${esc(tr('Settings of the documents'))}">${ic('gear')}</button></span>
    </div>
    ${DC.more || active ? `<div class="dc-filters">${sel('sender', fc.senders, N_('Sender'))}${sel('type', fc.types, N_('Document type'))}${sel('tag', fc.tags, N_('Tag'))}
      <span class="dc-range">${tr('from')} ${dateIn('dc-ffrom', DC.f.from, {label: tr('from'), attrs: 'data-dcf="from"'})}</span><span class="dc-range">${tr('to')} ${dateIn('dc-fto', DC.f.to, {label: tr('to'), attrs: 'data-dcf="to"'})}</span>
      ${active ? `<button type="button" class="linkbtn" data-dc="clear">${tr('Reset filters')}</button>` : ''}</div>` : ''}
    ${DC.waiting ? `<p class="muted dc-wait" role="status">${ic('hourglass', 's')} ${esc(trn('{0} document is being recognised…', '{0} documents are being recognised…', DC.waiting))}</p>` : ''}`;
  let body;
  if (DC.err) body = `<div class="empty">${ic('alert')}<span>${esc(DC.err)}</span></div>`;
  else if (!DC.docs) body = `<p class="muted lempty">${tr('Loading…')}</p>`;
  else if (!DC.docs.length) body = `<div class="empty nempty dc-empty">${ic('file')}<span>${DC.q || active || DC.f.review ? tr('No documents found') : tr('Drop PDFs or photos of letters here, or add them with the button. Kalmido reads the text, finds date and amount and sorts them.')}</span></div>`;
  else body = `<ul class="dc-grid" aria-label="${esc(tr('Documents'))}">${DC.docs.map(dc_card).join('')}</ul>${DC.total > DC.docs.length ? `<p class="muted">${esc(tr('{0} of {1} shown, narrow the search', DC.docs.length, DC.total))}</p>` : ''}`;
  return `<div class="dc-view">${head}${body}<div class="dc-drop" aria-hidden="true"><span>${ic('plus')} ${tr('Drop to add as documents')}</span></div></div>`;
}
function dc_card(d) {
  const thumb = d.thumb ? `<img src="/api/docs/${d.id}/thumb?v=${esc(d.updated_at || '')}" alt="" loading="lazy">` : `<span class="dc-ph">${ic(dc_isPdf(d) ? 'file' : 'picture')}</span>`;
  const st = d.state === 'done' ? '' : `<span class="dc-st ${esc(d.state)}">${esc(tr(DC_STATE[d.state] || d.state))}</span>`;
  const meta = [d.date ? dc_day(d.date) : '', d.type?.name || '', d.asn ? `${DC.set?.asn_prefix || 'ASN'} ${d.asn}` : ''].filter(Boolean).map(esc).join(' · ');
  return `<li class="dc-card${d.review ? ' rev' : ''}"><button type="button" data-dco="${d.id}" aria-label="${esc(d.name)}">
    <span class="dc-th">${thumb}</span><span class="dc-ct"><b class="dc-nm">${esc(d.sender?.name || d.name)}</b>
    <span class="dc-mt">${meta}${d.amount ? ` · ${esc(dc_money(d.amount, d.currency))}` : ''}</span>
    ${d.tags.length ? `<span class="dc-tags">${d.tags.map(t => `<span class="dc-tag">${esc(t.name)}</span>`).join('')}</span>` : ''}
    ${st}${d.review ? `<span class="dc-revdot">${tr('To review')}</span>` : ''}</span></button></li>`;
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
  if (S.route.mod === 'docs') dc_load();
  return j.ids || [];
}
const dc_shareOk = () => typeof feat === 'function' && feat('docs') && !S.me?.kid;
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
  const sug = Object.entries(d.suggest || {});
  const sugHtml = d.review ? `<div class="dc-rev" role="group" aria-label="${esc(tr('To review'))}">
    <b>${tr('To review')}</b>
    ${sug.map(([f, s]) => `<div class="dc-sug"><span>${esc(tr(DC_FEATS.find(x => x[0] === f)?.[1] || f))}: <b>${esc(s.label)}</b>${s.by === 'agent' ? ` <span class="muted">(${tr('from the agent')})</span>` : ''}</span>${w ? `<button type="button" class="btn sm" data-dc="take:${esc(f)}">${tr('Accept')}</button>` : ''}</div>`).join('')}
    ${sug.length ? '' : `<p class="muted">${tr('Check sender and type, then mark the document as checked.')}</p>`}
    ${w ? `<div class="dc-revact">${sug.length > 1 ? `<button type="button" class="btn sm" data-dc="takeall">${tr('Accept all')}</button>` : ''}<button type="button" class="btn sm pri" data-dc="checked">${ic('check', 's')} ${tr('Checked')}</button></div>` : ''}</div>` : '';
  const due = d.due && !d.task_id && w ? `<div class="dc-due">${ic('alarm', 's')} <span>${esc(tr('Due on {0}', dc_day(d.due)))}</span><button type="button" class="btn sm" data-dc="task">${tr('Create task')}</button></div>`
    : d.task_id ? `<div class="dc-due muted">${ic('done', 's')} <a href="#t/${d.task_id}">${tr('Task created')}</a></div>` : '';
  const ro = w ? '' : 'disabled';
  $('.dc-body', md).innerHTML = `<div class="lhdr"><h3 id="dc-h">${esc(d.name)}</h3><span class="spacer"></span><button class="iconbtn" data-dc="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="dc-top">
      <button type="button" class="dc-prev" data-dc="view" aria-label="${esc(tr('Show {0}', d.name))}">${d.thumb ? `<img src="/api/docs/${d.id}/thumb?v=${esc(d.updated_at || '')}" alt="">` : `<span class="dc-ph">${ic('file')}</span>`}</button>
      <div class="dc-acts">
        <button type="button" class="btn sm" data-dc="view">${ic('eye', 's')} ${tr('Show')}</button>
        <a class="btn sm" href="${dc_fileUrl(d, true)}" download>${ic('archive', 's')} ${tr('Download')}</a>
        ${d.parent_id ? `<a class="btn sm" href="#ablage/${d.parent_id}" data-dc="close">${ic('folder', 's')} ${tr('Show in the file store')}</a>` : ''}
        ${w ? `<button type="button" class="btn sm danger" data-dc="del">${ic('trash', 's')} ${tr('Delete')}</button>` : ''}
      </div></div>
    <p class="dc-state ${esc(d.state)}" role="status">${esc(tr(DC_STATE[d.state] || d.state))}${d.state === 'failed' && d.error_text ? `: ${esc(d.error_text)}` : ''}${d.method === 'ocr' ? ` · ${tr('text recognition')}` : ''}
      ${w && (d.state === 'done' || d.state === 'failed') ? `<button type="button" class="linkbtn" data-dc="redo">${tr('Recognise again')}</button>` : ''}</p>
    ${sugHtml}${due}${typeof rc_slot === 'function' ? rc_slot(d) : ''}
    <div class="dc-form">
      ${field('name', tr('Title'), `<input id="dc-name" data-dcp="name" value="${esc(d.name)}" maxlength="150" ${ro}>`)}
      ${field('sender', tr('Sender'), `<input id="dc-sender" data-dcp="sender" value="${esc(d.sender?.name || '')}" list="dc-sl" autocomplete="off" maxlength="120" ${ro}>${dl('dc-sl', set.senders)}`)}
      ${field('type', tr('Document type'), `<input id="dc-type" data-dcp="type" value="${esc(d.type?.name || '')}" list="dc-tl" autocomplete="off" maxlength="120" placeholder="${esc(tr('e.g. Invoice, Contract, Letter'))}" ${ro}>${dl('dc-tl', set.types)}`)}
      ${field('tags', tr('Tags'), `<input id="dc-tags" data-dcp="tags" value="${esc(d.tags.map(t => t.name).join(', '))}" list="dc-gl" autocomplete="off" placeholder="${esc(tr('comma-separated'))}" ${ro}>${dl('dc-gl', set.tags)}`)}
      ${field('folder', tr('Folder'), `<select id="dc-folder" data-dcp="folder" ${ro}><option value="">${tr('Documents (no subfolder)')}</option>${(set.folders || []).map(f => `<option value="${f.id}" ${d.folder?.id === f.id ? 'selected' : ''}>${esc(f.name)}</option>`).join('')}${w ? `<option value="new">${tr('New folder…')}</option>` : ''}</select>`)}
      ${field('date', tr('Date'), dateIn('dc-date', d.date || '', {label: tr('Date'), ro: !!ro, attrs: 'data-dcp="date"'}))}
      ${field('due', tr('Due'), dateIn('dc-due', d.due || '', {label: tr('Due'), ro: !!ro, attrs: 'data-dcp="due"'}))}
      ${field('asn', tr('Archive number'), `<span class="dc-amt"><input type="number" min="1" id="dc-asn" data-dcp="asn" value="${esc(d.asn || '')}" ${ro}>${w && !d.asn ? `<button type="button" class="btn sm" data-dc="asnnext">${tr('Next free number')}</button>` : ''}</span>`)}
      ${field('amount', tr('Amount'), `<span class="dc-amt"><input id="dc-amount" data-dcp="amount" inputmode="decimal" value="${esc(d.amount ? String(d.amount).replace('.', LOCALE().startsWith('en') ? '.' : ',') : '')}" ${ro}><input id="dc-currency" data-dcp="currency" value="${esc(d.currency || '')}" maxlength="3" aria-label="${esc(tr('Currency'))}" placeholder="EUR" ${ro}></span>`)}
    </div>
    <details class="dc-text"><summary>${tr('Recognised text')}</summary>${d.text ? `<pre>${esc(d.text)}</pre>` : `<p class="muted">${tr('No text recognised.')}</p>`}</details>`;
}
function dc_val(f, el) {
  const v = el.value.trim();
  if (f === 'tags') return v ? v.split(',').map(x => x.trim()).filter(Boolean) : [];
  if (f === 'amount') return v.replace(/\s/g, '').replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.');
  if (f === 'folder') return v ? +v : '';
  if (f === 'asn') return v ? +v : null;
  return v;
}
function dc_cur(d, f) {  // the value of a field as the server takes it back (for the undo)
  if (f === 'sender' || f === 'type') return d[f]?.name || '';
  if (f === 'tags') return d.tags.map(t => t.name);
  if (f === 'folder') return d.folder?.id || '';
  if (f === 'asn') return d.asn || null;
  return d[f] ?? '';
}
async function dc_patch(id, body, label) {
  const before = DC.doc && DC.doc.id === id ? Object.fromEntries(Object.keys(body).map(k => [k, dc_cur(DC.doc, k)])) : null;
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
  const el = e.target.closest('[data-dcp]'); if (!el || !DC.doc) return;
  const f = el.dataset.dcp, id = DC.doc.id;
  if (f === 'folder' && el.value === 'new') {
    const name = (await askPrompt(tr('New folder'), '', {ok: tr('Create')}) || '').trim();
    if (!name) { el.value = DC.doc.folder?.id || ''; return; }
    await dc_patch(id, {folder: name}, tr('Moved {0} to {1}', DC.doc.name, name));
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
  if (a === 'view') {
    if (dc_isPdf(d) && typeof pdfView === 'function') pdfView({url: dc_fileUrl(d), name: d.name, size: d.size, dlUrl: dc_fileUrl(d, true)});
    else if (/^image\//.test(d.mime) && typeof attLightbox === 'function') window.open(dc_fileUrl(d), '_blank', 'noopener');
    else window.open(dc_fileUrl(d), '_blank', 'noopener');
    return;
  }
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
    <p class="muted">${esc(tr('Next free number: {0}. A QR code or text like {1} on a scan fills it in.', s.asn_next, `${s.asn_prefix || 'ASN'}${String(s.asn_next).padStart(5, '0')}`))}</p>
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
    ${s.mail.enabled ? `<h4>${tr('Forward by e-mail')}</h4><p class="muted">${tr('PDFs and images attached to mails sent to this address become documents here.')}</p>
      ${s.mail.address ? `<p class="dc-mail"><code>${esc(s.mail.address)}</code> <button type="button" class="linkbtn" data-dcs="mailnew">${tr('New address')}</button> <button type="button" class="linkbtn" data-dcs="maildel">${tr('Turn off')}</button></p>`
        : `<button type="button" class="btn sm" data-dcs="mailnew">${tr('Create address')}</button>`}` : ''}
    ${typeof pl_slot === 'function' ? pl_slot(s) : ''}`;  // 2.48.0 (#1152): Paperless-ngx (paperless.js, self-hosted only)
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
  if (e.target.matches('[data-dcs="inbox"]')) { DC.set = await api('PUT', '/api/docs/settings', {ws: s.ws, inbox: e.target.checked}).catch(() => s); dc_sDraw(md); }
}
async function dc_sClick(e) {
  const b = e.target.closest('[data-dcs]'); if (!b || b.matches('input')) return;
  const s = DC.set, md = b.closest('.dc-smd'), a = b.dataset.dcs;
  if (a === 'close') { md.remove(); return; }
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
  if (o) { history.replaceState(null, '', `#docs/${o.dataset.dco}`); dc_open(+o.dataset.dco); return; }
  const b = e.target.closest('[data-dc]'); if (!b) return;
  const a = b.dataset.dc;
  if (a === 'settings') dc_settings();
  else if (a === 'all' || a === 'review') { DC.f.review = a === 'review'; dc_load(); dc_draw(); }
  else if (a === 'more') { DC.more = !DC.more; dc_draw(); }
  else if (a === 'clear') { Object.assign(DC.f, {sender: '', type: '', tag: '', from: '', to: ''}); dc_load(); }
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
