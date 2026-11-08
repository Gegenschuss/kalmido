// @ts-check
/* Kalmido web client: tables, grouping by one column with subtotals (2.671.0, #3463 a). A view only, like the filter: kept
   per table in SHG.by for as long as the app runs, nothing is saved, nothing goes to the server. The rows shown (filters,
   then the saved sorting) are bundled by the value of one column (a date by month - or day / year -, a selection by its
   option in the column's order, a person / text by what the cell reads, numbers by value; empty cells last). Each group has
   a head (open / closed, its number of rows) and a subtotal row: sum / count / average of every number column (the kind
   per column, sum by default). Heads and subtotals are no data rows: no cell ids, no data-r / data-c, so they are never
   chosen, edited, copied or used in a formula, and the export (server side) never sees them. Moving rows waits while
   grouped (sheetmove.js), merged cells keep only their columns while grouped (sheetfmt.js).
   Hangs into sheets.js through typeof checks (shg_rows, shg_bodyHtml, shg_btnHtml, shg_patch) and SHV_HOOKS.colmenu.
   Classic script sharing the global scope with the others (load order: lazyload.js LAZY sheets). */
'use strict';

/** @typedef {{c: number, unit: string, shut: Object<string, number>, agg: Object<string, string>}} ShgCfg c: the column, unit: 'day' | 'month' | 'year' (dates), shut: closed group keys, agg: column id -> 'sum' | 'count' | 'avg' */
/** @typedef {{k: string, label: string, o: [number, string|number]}} ShgKey a row's group: key, text, [rank, value] for the order */
/** @type {{by: Object<string, ShgCfg>}} sheet id -> its grouping */
const SHG = {by: {}};
const SHG_AGG = [['sum', N_('Sum')], ['count', N_('Count')], ['avg', N_('Average')]];
const SHG_UNITS = [['day', N_('Day')], ['month', N_('Month')], ['year', N_('Year')]];

function shg_cfg(sh) {  // the grouping of a sheet (null: none; a deleted column ends it)
  const g = sh && SHG.by[sh.id]; if (!g) return null;
  if (!sh._col?.has(g.c)) { delete SHG.by[sh.id]; return null; }
  return g;
}
const shg_on = sh => !!shg_cfg(sh);

function shg_dateLabel(k) {  // 'YYYY' | 'YYYY-MM' | 'YYYY-MM-DD' -> its text in the app's language
  const [y, m, d] = k.split('-').map(Number);
  if (!m) return String(y);
  try { return new Intl.DateTimeFormat(LOCALE(), d ? {day: 'numeric', month: 'long', year: 'numeric'} : {month: 'long', year: 'numeric'}).format(new Date(Date.UTC(y, m - 1, d || 1))); }
  catch { return k; }
}
// one row's group; empty / errors last
/** @returns {ShgKey} */
function shg_key(sh, col, r, unit) {
  /** @type {ShgKey} */
  const empty = {k: '', label: tr('(empty)'), o: [9, '']};
  const c = shvCell(r.id, col.id, sh);
  if (!c) return empty;
  if (c.error) return {k: 'e:', label: tr('Error'), o: [8, '']};
  if (col.kind === 'select') {
    const o = shvOpt(col, c);
    if (o) return {k: 'o:' + o.id, label: o.label || '', o: [0, (col.options || []).indexOf(o)]};
  }
  if (col.kind === 'date') {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(c.value ?? ''));
    if (m) { const k = unit === 'year' ? m[1] : unit === 'day' ? m[0] : m[1] + '-' + m[2]; return {k: 'd:' + k, label: shg_dateLabel(k), o: [0, k]}; }
  }
  if (typeof c.value === 'number') return {k: 'n:' + c.value, label: String(c.display ?? c.value), o: [1, c.value]};
  const t = String(c.display ?? c.value ?? '').trim();
  return t ? {k: 't:' + t.toLowerCase(), label: t, o: [2, t.toLowerCase()]} : empty;
}
/**
 * @param {ShgKey} a
 * @param {ShgKey} b
 */
function shg_cmp(a, b) {
  const x = a.o[1], y = b.o[1];
  return a.o[0] - b.o[0] || (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), LOCALE(), {numeric: true}));
}
// the groups of the rows shown: [{k, label, rows, shut}] in their order; the rows keep the order of the filter + sorting
function shg_groups(sh) {
  const g = shg_cfg(sh); if (!g) return [];
  /** @type {Map<string, ShgKey & {rows: any[]}>} */
  const by = new Map();
  const col = sh._col.get(g.c);
  for (const r of shvVisRows(sh)) {
    const x = shg_key(sh, col, r, g.unit || 'month');
    if (!by.has(x.k)) by.set(x.k, {...x, rows: []});
    by.get(x.k).rows.push(r);
  }
  return [...by.values()].sort(shg_cmp).map(x => ({...x, shut: !!g.shut?.[x.k]}));
}
// sheets.js: the data rows on screen in their order (the arrows, a range, copy / paste follow it); closed groups leave theirs out
function shg_rows(sh) {
  if (!shg_on(sh)) return shvVisRows(sh);
  return shg_groups(sh).flatMap(x => x.shut ? [] : x.rows);
}

// ---- the subtotals
function shg_aggOf(sh, cid) { const g = shg_cfg(sh), a = g?.agg?.[cid]; return a && SHG_AGG.some(x => x[0] === a) ? a : 'sum'; }
function shg_calc(sh, col, rows, how) {  // the numbers of a column in these rows (text, empty and errors do not count)
  let s = 0, n = 0;
  for (const r of rows) { const c = shvCell(r.id, col.id, sh); if (c && !c.error && typeof c.value === 'number' && Number.isFinite(c.value)) { s += c.value; n++; } }
  if (how === 'count') return n;
  if (how === 'avg') return n ? s / n : null;
  return Math.round(s * 1e10) / 1e10;
}
function shg_fmt(sh, col, v, how) {
  if (v == null) return '–';
  try {
    if (how === 'count') return new Intl.NumberFormat(LOCALE()).format(v);
    if (col.kind === 'currency') return new Intl.NumberFormat(LOCALE(), {style: 'currency', currency: sh.currency || 'EUR'}).format(v);
    if (col.kind === 'percent') return new Intl.NumberFormat(LOCALE(), {style: 'percent', maximumFractionDigits: 2}).format(v);
    return new Intl.NumberFormat(LOCALE(), {maximumFractionDigits: 4}).format(v);
  } catch { return String(v); }
}

// ---- drawing (sheets.js shvSheetHtml: the body, the button in the top bar)
const shg_tail = (sh, k) => typeof shz_rowTail === 'function' ? shz_rowTail(sh, {id: 'g' + k}) : '';
function shg_headHtml(sh, x, i) {
  const n = x.rows.length, w = sh.columns.length + (sh.can_write ? 1 : 0);
  return `<tr class="shgh${x.shut ? ' shut' : ''}" data-gi="${i}" role="row"><th class="shvrh shgrh" scope="row"><button type="button" data-shg="tog" data-gi="${i}" aria-expanded="${!x.shut}" title="${esc(x.shut ? tr('Show {0}', x.label) : tr('Hide {0}', x.label))}" aria-label="${esc(x.shut ? tr('Show {0}', x.label) : tr('Hide {0}', x.label))}">${ic(x.shut ? 'right' : 'down', 's')}</button></th>
    <td class="shghc" colspan="${w}"><button type="button" class="shgt" data-shg="tog" data-gi="${i}" tabindex="-1"><b>${esc(x.label)}</b><span class="muted shgn">${trn('{0} row', '{0} rows', n)}</span></button></td>${shg_tail(sh, 'h' + i)}</tr>`;
}
function shg_sumHtml(sh, x, i) {
  const cells = sh.columns.map(col => {
    if (!SHV_NUM.includes(col.kind)) return '<td class="shgsc"></td>';
    const how = shg_aggOf(sh, col.id), v = shg_calc(sh, col, x.rows, how), lab = tr((SHG_AGG.find(a => a[0] === how) || SHG_AGG[0])[1]);
    return `<td class="shgsc num" data-c="${col.id}" data-agg="${how}" data-v="${v ?? ''}"><button type="button" class="shgag" data-shg="agg" data-c="${col.id}" title="${esc(tr('Subtotal') + ' · ' + lab)}"><small>${esc(lab)}</small><span class="shgv">${esc(shg_fmt(sh, col, v, how))}</span></button></td>`;
  }).join('');
  return `<tr class="shgs" data-gi="${i}" role="row" aria-readonly="true"><th class="shvrh shgsh" scope="row" title="${esc(tr('Subtotal'))}"><span aria-hidden="true">Σ</span><span class="sr">${tr('Subtotal')}</span></th>${cells}${sh.can_write ? '<td class="shvpad" aria-hidden="true"></td>' : ''}${shg_tail(sh, 's' + i)}</tr>`;
}
function shg_bodyHtml(sh) {
  return shg_groups(sh).map((x, i) => shg_headHtml(sh, x, i) + (x.shut ? '' : x.rows.map(r => shvTr(sh, r)).join('')) + shg_sumHtml(sh, x, i)).join('');
}
function shg_btnHtml(sh) {
  const g = shg_cfg(sh); if (!g) return '';
  const col = sh._col.get(g.c);
  return `<button type="button" class="btn sm on" data-shg="bar" aria-haspopup="menu" title="${esc(tr('Grouped by {0}', col.title || col.letter || ''))}">${ic('list', 's')}<span class="shvbk">${esc(tr('Grouped by {0}', col.title || col.letter || ''))}</span></button>`;
}
// sheets.js shvPatchAll: after a write the heads (their counts) and the subtotals follow; false = the groups changed (a redraw)
function shg_patch(sh) {
  if (!shg_on(sh)) return true;
  const tb = $('#shv-scroll tbody'); if (!tb) return true;
  const gs = shg_groups(sh), hs = tb.querySelectorAll('tr.shgh'), ss = tb.querySelectorAll('tr.shgs');  // in the groups' order
  if (hs.length !== gs.length || ss.length !== gs.length) return false;
  /**
   * @param {Element} el
   * @param {string} html
   */
  const swap = (el, html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); const n = t.content.firstElementChild; if (n && n.outerHTML !== el.outerHTML) el.replaceWith(n); };
  gs.forEach((x, i) => { swap(hs[i], shg_headHtml(sh, x, i)); swap(ss[i], shg_sumHtml(sh, x, i)); });
  return true;
}

// ---- changes of the view
function shg_draw(open) {  // a redraw; the rows of a group that opens fade in (sheetmotion.js an_on / an_desk, keyframes an_rowin)
  const trs = () => /** @type {HTMLElement[]} */ ([...document.querySelectorAll('#shv-scroll tbody tr[data-id]')]);
  const had = new Set(trs().map(t => t.dataset.id));
  shvRender();
  const mo = open && typeof an_on === 'function' && (an_on() || an_desk());
  if (mo) trs().forEach(t => { if (!had.has(t.dataset.id)) t.classList.add('an-rowin'); });
}
function shg_set(sh, cid) {
  const old = SHG.by[sh.id];
  SHG.by[sh.id] = {c: cid, unit: old?.c === cid ? old.unit : 'month', shut: {}, agg: old?.agg || {}};
  shg_draw(false);
}
function shg_off(sh) { delete SHG.by[sh.id]; shg_draw(false); }
function shg_toggle(sh, i) {
  const g = shg_cfg(sh), x = shg_groups(sh)[i]; if (!g || !x) return;
  g.shut = g.shut || {};
  if (x.shut) delete g.shut[x.k]; else g.shut[x.k] = 1;
  shg_draw(x.shut);
  const b = /** @type {HTMLElement|null} */ (document.querySelector(`#shv-scroll tr.shgh[data-gi="${i}"] th button`)); b?.focus({preventScroll: true});
}
function shg_all(sh, open) {
  const g = shg_cfg(sh); if (!g) return;
  g.shut = open ? {} : Object.fromEntries(shg_groups(sh).map(x => [x.k, 1]));
  shg_draw(open);
}
function shg_barMenu(sh, a) {
  const g = shg_cfg(sh); if (!g) return;
  const col = sh._col.get(g.c);
  menu(a, [{label: tr('Expand all'), icon: 'down', fn: () => shg_all(sh, true)}, {label: tr('Collapse all'), icon: 'right', fn: () => shg_all(sh, false)},
    ...(col.kind === 'date' ? [{head: tr('Group dates by')}, ...SHG_UNITS.map(([u, l]) => ({label: tr(l), on: (g.unit || 'month') === u, act: 'shg-unit-' + u, fn: () => { g.unit = u; g.shut = {}; shg_draw(false); }}))] : []),
    '-', {label: tr('Remove grouping'), icon: 'x', act: 'shg-off', fn: () => shg_off(sh)}], null, null, tr('Grouped by {0}', col.title || col.letter || ''));
}
function shg_aggMenu(sh, cid, a) {
  const col = sh._col.get(cid), g = shg_cfg(sh); if (!col || !g) return;
  const cur = shg_aggOf(sh, cid);
  menu(a, SHG_AGG.map(([k, l]) => ({label: tr(l), on: cur === k, act: 'shg-agg-' + k, fn: () => { g.agg = {...g.agg, [cid]: k}; if (!shg_patch(sh)) shvRender(); }})), null, null, tr('Subtotal') + ': ' + (col.title || col.letter || ''));
}
document.addEventListener('click', e => {
  const a = /** @type {HTMLElement|null} */ (/** @type {any} */ (e.target).closest?.('[data-shg]')); if (!a || !$('#view')?.contains(a)) return;
  const sh = SHV.sh; if (!sh) return;
  e.preventDefault();
  const k = a.dataset.shg;
  if (k === 'tog') shg_toggle(sh, +a.dataset.gi);
  else if (k === 'agg') shg_aggMenu(sh, +a.dataset.c, a);
  else if (k === 'bar') shg_barMenu(sh, a);
});
(SHV_HOOKS.colmenu = SHV_HOOKS.colmenu || []).push((sh, col) => {
  const g = shg_cfg(sh);
  return ['-', {label: tr('Group by this column'), icon: 'list', act: 'shg-by', on: g?.c === col.id, fn: () => shg_set(sh, col.id)},
    ...(g ? [{label: tr('Remove grouping'), icon: 'x', act: 'shg-off', fn: () => shg_off(sh)}] : [])];
});
