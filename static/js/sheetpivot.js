// @ts-check
// 2.671.0 (#3463 b): the pivot sheet of a table, loaded on demand (lazyload.js, module sheetpivot) when a pivot sheet is shown
// or the sheet bar's menu asks for a new one. A pivot sheet has no cells: the server computes its table from the source
// sheet on every read (sheets/shpivot.py) and the view draws it read-only, with the totals. Its setting: a small dialog
// (source sheet, up to three row fields, one column field, up to six values sum / count / average, one filter). A change of
// the source reloads the open pivot by the usual live way (the table's rev / the area). New and changed settings are one
// Undo step each; a setting changed meanwhile elsewhere answers 409 (the dialog's version, expect_updated_at).
const SPV_AGGS = /** @type {const} */ (['sum', 'count', 'avg']);
const spvAggName = a => a === 'sum' ? tr('Sum') : a === 'avg' ? tr('Average') : tr('Count');

function spv_html(sh) {
  const p = sh.pivot || {}, res = p.result || {}, w = sh.can_write;
  const back = sh.list_id ? `<a class="btn sm" href="#sheets/l/${sh.list_id}" data-navup>${ic('back', 's')}<span class="shvbk">${esc(sh.list_title || tr('Project'))}</span></a>` : `<a class="btn sm" href="#sheets" data-navup>${ic('back', 's')}<span class="shvbk">${tr('Tables')}</span></a>`;
  const top = `<div class="shvtop">${back}<h2 class="shvh">${esc((sh.book_title ?? sh.title) || tr('Untitled table'))}</h2>${w ? '' : `<span class="shvro">${ic('eye', 's')}${tr('Read-only')}</span>`}<span class="spacer"></span>
    ${w ? `<button type="button" class="btn sm" data-spv="edit">${ic('edit', 's')}${tr('Edit pivot…')}</button>` : ''}
    <button type="button" class="iconbtn" data-spv="menu" aria-haspopup="menu" title="${esc(tr('More'))}" aria-label="${esc(tr('More'))}">${ic('dots')}</button></div>`;
  const src = res.source ? `<p class="muted spv-src">${ic('sheet', 's')}${esc(tr('Pivot of the sheet {0}, always up to date. Change the values there.', qn(res.source.name)))}</p>` : '';
  const k = res.keys || 0;
  const td = (x, i, row) => i < k && row ? `<th scope="row">${esc(x.d)}</th>` : `<td class="${typeof x.v === 'number' ? 'num' : ''}">${esc(x.d)}</td>`;
  const head = (res.header || []).map((h, i) => `<th scope="col" class="${i < k ? '' : 'num'}">${esc(h)}</th>`).join('');
  const body = (res.rows || []).map(r => `<tr>${r.map((x, i) => td(x, i, true)).join('')}</tr>`).join('');
  const foot = res.total ? `<tfoot><tr>${res.total.map((x, i) => i === 0 ? `<th scope="row">${esc(x.d)}</th>` : td(x, i, false)).join('')}</tr></tfoot>` : '';
  const empty = !res.error && !(res.rows || []).length ? `<p class="muted mhint">${tr('No rows in the source match.')}</p>` : '';
  const tbl = res.error ? `<p class="muted mhint" role="status">${esc(res.error)}</p>`
    : `<div class="spv-scroll" tabindex="0" role="region" aria-label="${esc(sh.tab_name || tr('Pivot'))}"><table class="spv-grid"><thead><tr>${head}</tr></thead><tbody>${body}</tbody>${foot}</table></div>${empty}${res.truncated ? `<p class="muted mhint">${tr('Only the first rows and columns are shown.')}</p>` : ''}`;
  return `<div class="shvwrap spv-view" data-k="spv-${sh.id}">${top}${src}<div class="spv-body">${tbl}</div>${typeof shb_barHtml === 'function' ? shb_barHtml(sh) : ''}</div>`;
}

const spvColName = (c, i) => c.title || c.letter || tr('Column {0}', i + 1);
function spvDefault(src) {  // a first setting: the first text-like column as rows, the first number column summed
  const cols = src.columns || [], num = c => ['number', 'currency', 'percent'].includes(c.kind);
  const r = cols.find(c => !num(c)), v = cols.find(num);
  return {rows: r ? [r.id] : [], cols: null, values: [v ? {col: v.id, agg: 'sum'} : {col: null, agg: 'count'}], filter: null};
}
function spvLabels(src, cid) {  // the texts a column shows (the filter's choice), the empty one as ''
  const out = new Set(), at = new Map((src.cells || []).filter(x => x.col_id === cid).map(x => [x.row_id, x.error ? tr('Error') : x.display || '']));
  for (const r of src.rows || []) { if ((src.cells || []).some(x => x.row_id === r.id && (x.raw || ''))) out.add(at.get(r.id) || ''); }
  return [...out].sort((a, b) => a === '' ? 1 : b === '' ? -1 : a.localeCompare(b, undefined, {numeric: true}));
}

async function spv_dialog(sh, pv) {  // pv = the setting of the open pivot sheet, or null for a new one from sheet sh
  if (!sh?.can_write) return;
  const bid = sh.book_id || sh.id, tabs = (sh.tabs || []).filter(t => t.kind !== 'pivot');
  if (!tabs.length) return;
  const st = {source: pv ? pv.source : (sh.kind === 'pivot' ? tabs[0].id : sh.id), rows: [], cols: null, values: [], filter: null};
  if (pv) Object.assign(st, {rows: [...(pv.rows || [])], cols: pv.cols ?? null, values: (pv.values || []).map(v => ({...v})), filter: (pv.filter || [])[0] || null});
  /** @type {any} */ let src = null;
  const load = async first => {
    try { src = await rawFetch('GET', '/api/sheets/' + st.source); } catch (e) { toast(e.message); return false; }
    if (first && !pv) Object.assign(st, spvDefault(src));
    return true;
  };
  if (!await load(true)) return;
  /** @type {string[]} */ let labels = [];
  const md = modal('<div class="spv-dlg"></div>');
  md.classList.add('spvdlg');
  const opts = (sel, none) => `${none ? `<option value="">${esc(none)}</option>` : ''}${(src.columns || []).map((c, i) => `<option value="${c.id}" ${sel === c.id ? 'selected' : ''}>${esc(spvColName(c, i))}</option>`).join('')}`;
  const draw = () => {
    const fl = st.filter, box = md.querySelector('.spv-dlg');
    labels = fl ? spvLabels(src, fl.col) : [];
    if (box) box.innerHTML = `<h3>${pv ? tr('Edit pivot') : tr('New pivot sheet')}</h3>
      <div class="row"><label for="spv-src">${tr('Source sheet')}</label><select id="spv-src">${tabs.map(t => `<option value="${t.id}" ${t.id === st.source ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></div>
      <fieldset><legend>${tr('Rows')}</legend>${[0, 1, 2].map(i => i <= st.rows.length ? `<div class="row"><select data-spv-row="${i}" aria-label="${esc(tr('Row field {0}', i + 1))}">${opts(st.rows[i], tr('None'))}</select></div>` : '').join('')}</fieldset>
      <div class="row"><label for="spv-cols">${tr('Columns')}</label><select id="spv-cols">${opts(st.cols, tr('None'))}</select></div>
      <fieldset><legend>${tr('Values')}</legend>${st.values.map((v, i) => `<div class="row spv-val"><select data-spv-vcol="${i}" aria-label="${esc(tr('Column'))}">${opts(v.col, tr('Rows (count)'))}</select><select data-spv-vagg="${i}" aria-label="${esc(tr('Calculation'))}">${SPV_AGGS.map(a => `<option value="${a}" ${v.agg === a ? 'selected' : ''}>${esc(spvAggName(a))}</option>`).join('')}</select>${st.values.length > 1 ? `<button type="button" class="iconbtn" data-m="vrm" data-i="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>` : ''}</div>`).join('')}
        ${st.values.length < 6 ? `<button type="button" class="btn sm" data-m="vadd">${ic('plus', 's')}${tr('Add value')}</button>` : ''}</fieldset>
      <fieldset><legend>${tr('Filter')}</legend><div class="row"><select id="spv-fcol" aria-label="${esc(tr('Filter by'))}">${opts(fl?.col, tr('No filter'))}</select></div>
        ${fl ? `<div class="spv-fvals">${labels.map((l, i) => `<label class="chkl"><input type="checkbox" data-spv-fv="${i}" ${fl.values.includes(l) ? 'checked' : ''}> ${esc(l || tr('(empty)'))}</label>`).join('')}</div>` : ''}</fieldset>
      <p class="muted mhint" id="spv-err" role="alert"></p>
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="save">${pv ? tr('Save') : tr('Create')}</button></div>`;
  };
  draw();
  md.addEventListener('change', async e => {
    const t = /** @type {HTMLSelectElement} */ (e.target), d = t.dataset;
    if (t.id === 'spv-src') { st.source = +t.value; if (await load(false)) { Object.assign(st, spvDefault(src)); draw(); } return; }
    if (d.spvRow != null) { const i = +d.spvRow; if (t.value) st.rows[i] = +t.value; else st.rows.splice(i); st.rows = [...new Set(st.rows)]; draw(); return; }
    if (t.id === 'spv-cols') { st.cols = t.value ? +t.value : null; return; }
    if (d.spvVcol != null) { st.values[+d.spvVcol].col = t.value ? +t.value : null; if (!t.value) st.values[+d.spvVcol].agg = 'count'; draw(); return; }
    if (d.spvVagg != null) { st.values[+d.spvVagg].agg = t.value; return; }
    if (t.id === 'spv-fcol') { st.filter = t.value ? {col: +t.value, values: spvLabels(src, +t.value)} : null; draw(); return; }
    if (d.spvFv != null && st.filter) {
      const l = labels[+d.spvFv], on = /** @type {HTMLInputElement} */ (/** @type {unknown} */ (t)).checked;
      st.filter.values = on ? [...new Set([...st.filter.values, l])] : st.filter.values.filter(x => x !== l);
    }
  });
  md.addEventListener('click', async e => {
    const b = e.target instanceof Element ? /** @type {HTMLElement|null} */ (e.target.closest('button[data-m]')) : null; if (!b) return;
    const a = b.dataset.m;
    if (a === 'close') { md.remove(); return; }
    if (a === 'vadd') { st.values.push({col: null, agg: 'count'}); draw(); return; }
    if (a === 'vrm') { st.values.splice(+(b.dataset.i || 0), 1); draw(); return; }
    if (a !== 'save') return;
    const err = md.querySelector('#spv-err');
    if (st.cols != null && st.rows.includes(st.cols)) { if (err) err.textContent = tr('A column cannot be a row and a column field at once'); return; }
    if (st.values.some(v => v.col == null && v.agg !== 'count')) { if (err) err.textContent = tr('Select a column for a sum or an average'); return; }
    const spec = {source: st.source, rows: st.rows, cols: st.cols, values: st.values.map(v => ({col: v.col, agg: v.agg})), filter: st.filter ? [st.filter] : []};
    try { if (pv) await spvSave(sh, spec); else await spvCreate(sh, bid, spec); md.remove(); }
    catch (x) { if (err) err.textContent = x.message; }
  });
}

async function spvCreate(sh, bid, spec) {
  const names = new Set((sh.tabs || []).map(t => t.name.toLowerCase()));
  let name = tr('Pivot'), n = 2;
  while (names.has(name.toLowerCase())) name = tr('Pivot') + ' ' + n++;
  const r = await rawFetch('POST', shbUrl(bid), {after_id: sh.id, name, pivot: spec}), tid = r.tab.id, from = sh.id;
  await shbAfter(tid);
  histToast(tr('Sheet {0} created', qn(r.tab.name)), histAdd({label: tr('Created {0}', qn(r.tab.name)), ids: [], snaps: [], lids: [],
    undo: async () => { await rawFetch('DELETE', shbUrl(bid, tid)); await shbAfter(from); return {skipped: []}; },
    redo: async () => { await rawFetch('POST', shbUrl(bid, tid, 'restore')); await shbAfter(tid); return {skipped: []}; },
    post: dir => shbAfter(dir === 'undo' ? from : tid)}));  // 2.979.0 (#5667): after a step the server took back: the sheet to show
}
async function spvSave(sh, spec) {  // one Undo step: the setting before comes back (with the version read then)
  const bid = sh.book_id || sh.id, tid = sh.id, p = sh.pivot || {};
  const old = {source: p.source, rows: p.rows, cols: p.cols, values: p.values, filter: p.filter};
  const set = async (v, ver) => { const r = await rawFetch('PUT', shbUrl(bid, tid, 'pivot'), {...v, expect_updated_at: ver}); await shbAfter(); return r.pivot?.updated_at; };
  let ver = await set(spec, p.updated_at);
  histToast(tr('Pivot changed'), histAdd({label: tr('Pivot changed'), ids: [], snaps: [], lids: [],
    undo: async () => { ver = await set(old, ver); return {skipped: []}; }, redo: async () => { ver = await set(spec, ver); return {skipped: []}; }}));
}

document.addEventListener('click', e => {
  const a = e.target instanceof Element ? /** @type {HTMLElement|null} */ (e.target.closest('[data-spv]')) : null, sh = SHV.sh;
  if (!a || !sh || sh.kind !== 'pivot' || !$('#view')?.contains(a)) return;
  if (a.dataset.spv === 'edit') spv_dialog(sh, sh.pivot);
  else if (a.dataset.spv === 'menu') menu(a, [...typeof shp_dialog === 'function' ? [{label: tr('Print / PDF…'), icon: 'printer', fn: () => shp_dialog(sh)}] : [],  // 2.693.0 (#5148)
    {label: tr('Export as Excel (.xlsx)'), icon: 'download', fn: () => shxUiExport(sh, 'xlsx')},
    {label: tr('Export as CSV'), icon: 'download', fn: () => shxUiExport(sh, 'csv')}]);
});
