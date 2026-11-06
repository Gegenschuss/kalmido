// @ts-check
/* Kalmido web client: the format of a table's cells and its colour rules (2.578.0, #3462 part C), loaded with the tables
   (lazyload.js). A bar under the formula bar (only with the right to write): bold, italic, text colour, fill (the app's palette:
   the accent, a light accent and three cool greys - no free colour), align left / centre / right, wrap, merge cells, copy the
   format (the brush: the next choice gets it), clear the format and "Rules" (colour rules for the chosen columns). On a phone
   the bar scrolls sideways and "Select a range" makes the next taps grow a range. Every change is one Undo step and one write
   of the cells (PUT …/cells with fmt / prev_fmt; the server keeps the format in its own field, sheets/shfmt.py). sheets.js
   asks shfm_td (classes, rowspan / colspan of merged cells), shfm_barHtml and shfm_sync.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const SHFM_PAL = ['a', 'a2', 'g1', 'g2', 'g3'];  // kalmido/sheets/shfmt.py SHFM_PALETTE
const SHFM_PAL_N = {a: N_('Accent'), a2: N_('Light accent'), g1: N_('Dark grey'), g2: N_('Grey'), g3: N_('Light grey')};
const SHFM_OPS = [['gt', N_('Greater than')], ['lt', N_('Less than')], ['eq', N_('Equal to')], ['between', N_('Between')],
  ['contains', N_('Contains text')], ['empty', N_('Is empty')], ['overdue', N_('Date is overdue')]];
const SHFM = {paint: null, ext: false, mm: null, mmSh: null};
const SHFM_AL = {  // the three alignments as small line icons (the icon set has none)
  left: '<path d="M3 5h14M3 9h9M3 13h14M3 17h9"/>', center: '<path d="M3 5h14M5.5 9h9M3 13h14M5.5 17h9"/>', right: '<path d="M3 5h14M8 9h9M3 13h14M8 17h9"/>'};
const shfmAlIc = k => `<svg class="i s" viewBox="0 0 20 20" aria-hidden="true">${SHFM_AL[k]}</svg>`;

// ---- a format as data: keys only when set, in one order (the server stores them sorted, too)
function shfm_norm(f) {
  if (!f) return null;
  const o = {};
  for (const k of ['align', 'bold', 'color', 'fill', 'italic', 'merge', 'wrap']) {
    const v = f[k];
    if (v === true || (typeof v === 'string' && v) || (Array.isArray(v) && v.length === 2 && v[0] * v[1] > 1)) o[k] = v;
  }
  return Object.keys(o).length ? o : null;
}
const shfmKey = f => JSON.stringify(shfm_norm(f));

// ---- colour rules: does a rule colour this cell (the values the viewer already has; nothing is asked from the server)
function shfm_num(s) {
  s = String(s ?? '').trim().replace(/[\s%€$£]/g, '');
  if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) s = s.replace(/\./g, '').replace(',', '.');
  else s = s.replace(',', '.');
  const n = Number(s);
  return s !== '' && Number.isFinite(n) ? n : null;
}
function shfm_today() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
function shfm_text(col, c) { return String(col.kind === 'select' ? (shvOpt(col, c)?.label || '') : (c?.display ?? c?.raw ?? '')); }
function shfm_hit(sh, r, col, c, rid) {
  if (!(r.cols || []).includes(col.id)) return false;
  if (r.rows) {
    const n = sh._rowNo.get(rid), a = sh._rowNo.get(r.rows[0]), b = sh._rowNo.get(r.rows[1]);
    if (a == null || b == null || n < Math.min(a, b) || n > Math.max(a, b)) return false;
  }
  if (r.op === 'empty') return !c || (!c.error && shfm_text(col, c) === '' && (c.raw ?? '') === '');
  if (!c || c.error) return false;
  const txt = shfm_text(col, c);
  if (r.op === 'contains') return !!r.a && txt.toLowerCase().includes(String(r.a).toLowerCase());
  if (r.op === 'overdue') return c.vtype === 'date' && typeof c.value === 'string' && c.value < shfm_today();
  // numbers (a percent column holds 19 % as 0.19: "19" in a rule means 19 %), dates as ISO days, else text
  const pct = col.kind === 'percent', arg = s => { const n = shfm_num(s); return n == null ? null : pct ? n / 100 : n; };
  let v = /** @type {any} */ (null), a = /** @type {any} */ (null), b = /** @type {any} */ (null);
  if (c.vtype === 'date') { v = c.value; a = sgDay(String(r.a ?? '')); b = sgDay(String(r.b ?? '')); }
  else if (typeof c.value === 'number') { v = c.value; a = arg(r.a); b = arg(r.b); }
  if (v != null && a != null) {
    if (r.op === 'gt') return v > a;
    if (r.op === 'lt') return v < a;
    if (r.op === 'eq') return v === a || (typeof v === 'number' && Math.abs(v - a) < 1e-9);
    if (r.op === 'between') return b != null && v >= Math.min(a, b) && v <= Math.max(a, b);
  }
  if (r.op === 'eq') return txt.trim().toLowerCase() === String(r.a ?? '').trim().toLowerCase();
  return false;
}

// ---- merged cells: their spans in the rows / columns shown (worked out once per drawing)
function shfm_merges(sh) {
  if (SHFM.mm && SHFM.mmSh === sh) return SHFM.mm;
  const rs = shvVisRows(sh).map(r => r.id), cs = sh.columns.map(c => c.id);
  const ri = new Map(rs.map((x, i) => [x, i])), ci = new Map(cs.map((x, i) => [x, i]));
  const span = new Map(), hid = new Set();
  for (const c of sh.cells || []) {
    const m = c.fmt?.merge; if (!m) continue;
    const i = ri.get(c.row_id), j = ci.get(c.col_id), k = c.row_id + ':' + c.col_id;
    if (i == null || j == null || hid.has(k)) continue;
    const h = Math.min(m[0], rs.length - i), w = Math.min(m[1], cs.length - j); if (h * w < 2) continue;
    span.set(k, [h, w]);
    for (let a = 0; a < h; a++) for (let b = 0; b < w; b++) if (a || b) hid.add(rs[i + a] + ':' + cs[j + b]);
  }
  SHFM.mm = {span, hid}; SHFM.mmSh = sh;
  queueMicrotask(() => { SHFM.mm = null; });  // one drawing (the grid is drawn in one go)
  return SHFM.mm;
}
// sheets.js shvTd: the classes of a cell's format / its rule, the span of a merged block; hide = covered by a merged block
function shfm_td(sh, col, c, rid, cls) {
  const k = rid + ':' + col.id, mm = shfm_merges(sh);
  if (mm.hid.has(k)) return {hide: true};
  const f = c?.fmt || {}, out = {at: ''};
  if (f.bold) cls.push('shfm-b');
  if (f.italic) cls.push('shfm-i');
  if (f.wrap) cls.push('shfm-wr');
  if (f.align) cls.push('shfm-al-' + f.align);
  let ink = f.color, fill = f.fill;
  const r = (sh.rules || []).find(x => shfm_hit(sh, x, col, c, rid));  // the first rule that fits wins
  if (r) { if (r.color) ink = r.color; if (r.fill) fill = r.fill; cls.push('shfm-rule'); }
  if (ink) cls.push('shfm-c-' + ink);
  if (fill) cls.push('shfm-f-' + fill);
  const sp = mm.span.get(k);
  if (sp) { out.at = ` rowspan="${sp[0]}" colspan="${sp[1]}"`; cls.push('shfm-m'); }
  return out;
}

// ---- the bar
function shfm_barHtml(sh) {
  if (!sh?.can_write) return '';
  const b = (k, inner, label, extra = '') => `<button type="button" class="iconbtn shfmb" data-shfm="${k}" title="${esc(label)}" aria-label="${esc(label)}" ${extra}>${inner}</button>`;
  return `<div class="shfmbar" id="shfm-bar" role="toolbar" aria-label="${esc(tr('Cell format'))}">
    ${b('bold', '<b aria-hidden="true">B</b>', tr('Bold'), 'aria-pressed="false"')}${b('italic', '<i aria-hidden="true">I</i>', tr('Italic'), 'aria-pressed="false"')}
    ${b('color', '<span class="shfm-ink" aria-hidden="true">A</span>', tr('Text colour'), 'aria-haspopup="menu"')}${b('fill', ic('drop', 's'), tr('Fill'), 'aria-haspopup="menu"')}
    <span class="shfmsep" aria-hidden="true"></span>
    ${['left', 'center', 'right'].map(k => b('al-' + k, shfmAlIc(k), tr({left: 'Align left', center: 'Align centre', right: 'Align right'}[k]), 'aria-pressed="false"')).join('')}
    ${b('wrap', ic('turns', 's'), tr('Wrap text'), 'aria-pressed="false"')}${b('merge', ic('columns', 's'), tr('Merge cells'), 'aria-pressed="false"')}
    <span class="shfmsep" aria-hidden="true"></span>
    ${b('paint', ic('copy', 's'), tr('Copy format'), `aria-pressed="${!!SHFM.paint}"`)}${b('clear', ic('x', 's'), tr('Clear format'))}
    <button type="button" class="btn sm shfmrules" data-shfm="rules">${ic('sliders', 's')}<span>${tr('Rules')}</span></button>
    ${isTouch() ? b('ext', ic('select', 's'), tr('Select a range'), `aria-pressed="${SHFM.ext}"`) : ''}</div>`;
}
// sheets.js shvBarSync: the buttons show the active cell's format
function shfm_sync() {
  const bar = $('#shfm-bar'), sh = SHV.sh; if (!bar || !sh) return;
  const c = SHV.cur && shvCell(SHV.cur.r, SHV.cur.c), f = c?.fmt || {};
  const on = {bold: !!f.bold, italic: !!f.italic, wrap: !!f.wrap, merge: !!f.merge, 'al-left': f.align === 'left', 'al-center': f.align === 'center',
    'al-right': f.align === 'right', paint: !!SHFM.paint, ext: SHFM.ext};
  bar.querySelectorAll('[data-shfm]').forEach(x => {
    const k = x.dataset.shfm; if (k in on) { x.setAttribute('aria-pressed', String(on[k])); x.classList.toggle('on', on[k]); }
    x.disabled = !SHV.cur && k !== 'rules';
  });
  const ink = bar.querySelector('.shfm-ink'); if (ink) ink.className = 'shfm-ink' + (f.color ? ' shfm-c-' + f.color : '');
}

// ---- writing: one step for the chosen cells
const shfmCells = () => shvRangeCells().flat();
function shfm_local(sh, list) {  // the formats stand in the cells at once (an empty cell gets a stand-in)
  for (const x of list) {
    let c = shvCell(x.row_id, x.col_id, sh);
    if (!c) { if (!x.fmt) continue; c = {row_id: x.row_id, col_id: x.col_id, raw: '', display: '', value: null}; sh.cells.push(c); }
    c.fmt = x.fmt;
  }
  shvPrep(sh);
}
const shfmMerges = list => list.some(x => !!(x.fmt?.merge) !== !!(x.old?.merge) || shfmKey(x.fmt?.merge) !== shfmKey(x.old?.merge));
async function shfm_send(sid, list, merges) {  // one way: list = [{row_id, col_id, fmt, prev}]
  const r = await shvSend(sid, list.map(x => ({row_id: x.row_id, col_id: x.col_id, fmt: x.fmt, prev_fmt: x.prev})));
  if (merges && SHV.sh?.id === sid) shvRender();
  const cf = (r?.conflicts || []).filter(x => x.what === 'fmt');
  return {r, cf, skipped: cf.map(x => tr('Cell {0}', shvAddr(x.row_id, x.col_id))), none: cf.length > 0 && cf.length === list.length};
}
async function shfm_put(chg, label) {  // chg = [{row_id, col_id, fmt: the new format | null, old}]
  const sh = SHV.sh; if (!sh?.can_write) return null;
  chg = chg.filter(x => shfmKey(x.fmt) !== shfmKey(x.old)).map(x => ({...x, fmt: shfm_norm(x.fmt), old: shfm_norm(x.old)}));
  if (!chg.length) return null;
  const sid = sh.id, merges = shfmMerges(chg);
  shfm_local(sh, chg);
  if (merges) shvRender(); else shvPatchAll();
  let res;
  try { res = await shfm_send(sid, chg.map(x => ({row_id: x.row_id, col_id: x.col_id, fmt: x.fmt, prev: x.old})), merges); }
  catch (e) { shfm_local(sh, chg.map(x => ({...x, fmt: x.old}))); if (merges) shvRender(); else shvPatchAll(); toast(e.message); return null; }
  if (res.cf.length) toast(tr('Changed elsewhere in the meantime') + ': ' + res.skipped.join(', '));
  const keep = new Set(res.cf.map(x => x.row_id + ':' + x.col_id)), done = chg.filter(x => !keep.has(x.row_id + ':' + x.col_id));
  if (!done.length) return null;
  const back = done.map(x => ({row_id: x.row_id, col_id: x.col_id, fmt: x.old, prev: x.fmt})), fwd = done.map(x => ({row_id: x.row_id, col_id: x.col_id, fmt: x.fmt, prev: x.old}));
  return histAdd({label: label || tr('Format changed'), ids: [], snaps: [], lids: [],
    undo: () => shfm_send(sid, back, merges), redo: () => shfm_send(sid, fwd, merges)});
}
function shfm_apply(fn, label) {  // fn(format copy, cell {r, c}) -> the new format
  if (!SHV.cur) return null;
  return shfm_put(shfmCells().map(x => { const old = shvCell(x.r, x.c)?.fmt || null; return {row_id: x.r, col_id: x.c, old, fmt: fn({...(old || {})}, x)}; }), label);
}
function shfm_toggle(k, label) {
  const all = shfmCells().every(x => !!shvCell(x.r, x.c)?.fmt?.[k]);
  return shfm_apply(f => ({...f, [k]: !all}), label);
}
function shfm_merge() {
  const sh = SHV.sh, q = shvRect(); if (!sh || !q) return null;
  const [rs, cs] = shvGrid(), ar = rs[q.r0], ac = cs[q.c0], h = q.r1 - q.r0 + 1, w = q.c1 - q.c0 + 1;
  const was = shvCell(ar, ac)?.fmt?.merge;
  if (h * w === 1 || (was && was[0] === h && was[1] === w)) {  // one cell / the block itself: a merged block is split again
    if (!was) { toast(tr('Choose several cells to merge')); return null; }
    return shfm_apply((f, y) => (y.r === ar && y.c === ac ? {...f, merge: null} : f), tr('Cells split'));
  }
  const filled = shfmCells().filter(y => (y.r !== ar || y.c !== ac) && shvRaw(y.r, y.c) !== '').length;
  const e = shfm_apply((f, y) => (y.r === ar && y.c === ac ? {...f, merge: [h, w]} : {...f, merge: null}), tr('Cells merged'));  // blocks inside end
  if (filled) toast(tr('Merged: only the top left value is shown; the others stay and come back when split'));
  SHV.anc = {r: ar, c: ac}; SHV.cur = {r: ar, c: ac};
  return e;
}
function shfm_colorMenu(a, k) {
  const cur = SHV.cur && shvCell(SHV.cur.r, SHV.cur.c)?.fmt?.[k];
  menu(a, [{label: k === 'fill' ? tr('No fill') : tr('Automatic'), icon: 'ban', on: !cur, act: `shfm-${k}-none`, fn: () => shfm_apply(f => ({...f, [k]: null}), k === 'fill' ? tr('Fill removed') : tr('Text colour removed'))},
    ...SHFM_PAL.map(p => ({label: tr(SHFM_PAL_N[p]), cls: `shfm-mi shfm-mi-${k} shfm-p-${p}`, on: cur === p, act: `shfm-${k}-${p}`,
      fn: () => shfm_apply(f => ({...f, [k]: p}), k === 'fill' ? tr('Fill changed') : tr('Text colour changed'))}))], null, null, k === 'fill' ? tr('Fill') : tr('Text colour'));
}
// the brush: the active cell's format (without its merge) goes onto the next choice
function shfm_paintStart() {
  if (SHFM.paint) { SHFM.paint = null; shfm_sync(); return; }
  const c = SHV.cur && shvCell(SHV.cur.r, SHV.cur.c), f = {...(c?.fmt || {})}; delete f.merge;
  SHFM.paint = {f: shfm_norm(f), at: Date.now()};
  shfm_sync(); toast(tr('Now choose the cells that get this format'));
}
function shfm_paintDrop() {
  const p = SHFM.paint; if (!p || Date.now() - p.at < 150) return;
  SHFM.paint = null;
  shfm_apply(f => ({...(p.f || {}), merge: f.merge || null}), tr('Format copied'));
  shfm_sync();
}
document.addEventListener('pointerup', e => { if (SHFM.paint && shvTdOf(e.target) && e.pointerType !== 'touch') setTimeout(shfm_paintDrop, 0); });
// a phone: a tap on a cell while the brush or "Select a range" is on (before sheets.js picks the cell alone)
document.addEventListener('click', e => {
  const td = shvTdOf(e.target); if (!td || !SHV.sh || !isTouch() || SHV.ed) return;
  if (SHFM.ext && SHV.cur) { e.stopPropagation(); shvSelect(+td.dataset.r, +td.dataset.c, true); return; }
  if (SHFM.paint) { e.stopPropagation(); shvSelect(+td.dataset.r, +td.dataset.c, false); setTimeout(shfm_paintDrop, 0); }
}, true);
document.addEventListener('click', e => {
  const a = (/** @type {any} */ (e.target)).closest?.('[data-shfm]'); if (!a || !$('#view')?.contains(a) || !SHV.sh) return;
  const k = a.dataset.shfm;
  if (k === 'rules') { shfm_rulesDlg(); return; }
  if (k === 'ext') { SHFM.ext = !SHFM.ext; shfm_sync(); return; }
  if (!SHV.cur) return;
  if (k === 'bold') shfm_toggle('bold', tr('Bold'));
  else if (k === 'italic') shfm_toggle('italic', tr('Italic'));
  else if (k === 'wrap') shfm_toggle('wrap', tr('Wrap text'));
  else if (k === 'color' || k === 'fill') shfm_colorMenu(a, k);
  else if (k.startsWith('al-')) { const v = k.slice(3), all = shfmCells().every(x => shvCell(x.r, x.c)?.fmt?.align === v); shfm_apply(f => ({...f, align: all ? null : v}), tr('Alignment changed')); }
  else if (k === 'merge') shfm_merge();
  else if (k === 'paint') shfm_paintStart();
  else if (k === 'clear') shfm_apply(f => (f.merge ? {merge: f.merge} : null), tr('Format cleared'));
  $('#shv-scroll')?.focus({preventScroll: true});
});
// keys on the grid: Ctrl/Cmd+B bold, Ctrl/Cmd+I italic
window.addEventListener('keydown', e => {
  if (e.key === 'Escape' && SHFM.paint) { SHFM.paint = null; shfm_sync(); }
  if ((/** @type {any} */ (e.target))?.id !== 'shv-scroll' || !SHV.sh?.can_write || !SHV.cur || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
  const k = e.key.toLowerCase();
  if (k === 'b' || k === 'i') { e.preventDefault(); e.stopPropagation(); shfm_toggle(k === 'b' ? 'bold' : 'italic', tr(k === 'b' ? 'Bold' : 'Italic')); }
}, true);

// ---- the dialog "Rules": the rules of the chosen columns, new ones for the choice
function shfm_rulesDlg() {
  const sh = SHV.sh; if (!sh) return;
  const q = shvRect(), [rs, cs] = shvGrid();
  const cols = q ? cs.slice(q.c0, q.c1 + 1) : cs.slice(0, 1);
  const whole = !q || (q.r0 === 0 && q.r1 === rs.length - 1) || q.r0 === q.r1;
  const rows = q && !whole ? [rs[q.r0], rs[q.r1]] : null;
  const st = {rules: JSON.parse(JSON.stringify(sh.rules || [])), op: 'gt', color: '', fill: 'a2', scope: rows ? 'rows' : 'cols'};
  const colName = id => { const c = sh._col.get(id); return c ? (c.title ? `${c.letter} ${c.title}` : c.letter) : '?'; };
  const opName = op => tr((SHFM_OPS.find(x => x[0] === op) || ['', op])[1]);
  const where = r => r.cols.map(colName).join(', ') + (r.rows ? ' · ' + tr('Rows {0}-{1}', sh._rowNo.get(r.rows[0]) ?? '?', sh._rowNo.get(r.rows[1]) ?? '?') : '');
  const ruleTxt = r => opName(r.op) + (r.op === 'between' ? ` ${r.a} – ${r.b}` : r.a ? ` ${qn(r.a)}` : '');
  const sw = (k, p) => `<span class="shfm-sw shfm-sw-${k} shfm-p-${p}" aria-hidden="true"></span>`;
  const pal = (k, cur) => `<div class="shfm-pal" role="radiogroup" aria-label="${esc(k === 'fill' ? tr('Fill') : tr('Text colour'))}">
    <button type="button" role="radio" data-shfmr-${k}="" aria-checked="${!cur}" class="${!cur ? 'on' : ''}" title="${esc(k === 'fill' ? tr('No fill') : tr('Automatic'))}">${ic('ban', 's')}</button>
    ${SHFM_PAL.map(p => `<button type="button" role="radio" data-shfmr-${k}="${p}" aria-checked="${cur === p}" class="${cur === p ? 'on' : ''}" title="${esc(tr(SHFM_PAL_N[p]))}" aria-label="${esc(tr(SHFM_PAL_N[p]))}">${sw(k, p)}</button>`).join('')}</div>`;
  const md = modal(`<h3>${tr('Colour rules')}</h3><div id="shfm-rl"></div>
    <h4>${tr('New rule for {0}', esc(cols.map(colName).join(', ')))}</h4>
    ${rows ? `<fieldset class="shvmode"><legend class="sr">${tr('Where')}</legend><label class="chkl"><input type="radio" name="shfm-sc" value="rows" checked> ${tr('Only the chosen rows')}</label><label class="chkl"><input type="radio" name="shfm-sc" value="cols"> ${tr('Whole columns')}</label></fieldset>` : ''}
    <div class="row"><label for="shfm-op">${tr('If the cell')}</label><select id="shfm-op">${SHFM_OPS.map(([k, n]) => `<option value="${k}">${tr(n)}</option>`).join('')}</select></div>
    <div class="row" id="shfm-ab"><label for="shfm-a">${tr('Value')}</label><input id="shfm-a" maxlength="200" autocomplete="off"><input id="shfm-b" maxlength="200" autocomplete="off" aria-label="${esc(tr('and'))}" hidden></div>
    <div class="row"><span class="lbl">${tr('Text colour')}</span><div id="shfm-pc"></div></div>
    <div class="row"><span class="lbl">${tr('Fill')}</span><div id="shfm-pf"></div></div>
    <div class="foot"><button type="button" class="btn" data-m="add">${ic('plus', 's')}${tr('Add rule')}</button><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="button" class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('shfmdlg');
  const draw = () => {
    md.querySelector('#shfm-rl').innerHTML = st.rules.length ? `<ul class="shfm-rules">${st.rules.map((r, i) => `<li data-i="${i}"><span class="shfm-prev ${r.color ? 'shfm-c-' + r.color : ''} ${r.fill ? 'shfm-f-' + r.fill : ''}">${esc(ruleTxt(r))}</span><span class="muted">${esc(where(r))}</span><button type="button" class="iconbtn" data-shfmr-rm="${i}" title="${esc(tr('Remove'))}" aria-label="${esc(tr('Remove rule {0}', ruleTxt(r)))}">${ic('trash', 's')}</button></li>`).join('')}</ul>`
      : `<p class="muted">${tr('No rules yet. A rule colours the cells whose value fits.')}</p>`;
    md.querySelector('#shfm-pc').innerHTML = pal('color', st.color); md.querySelector('#shfm-pf').innerHTML = pal('fill', st.fill);
    const need = !['empty', 'overdue'].includes(st.op);
    (/** @type {any} */ (md.querySelector('#shfm-ab'))).hidden = !need; (/** @type {any} */ (md.querySelector('#shfm-b'))).hidden = st.op !== 'between';
  };
  draw();
  const add = () => {
    const a = (/** @type {any} */ (md.querySelector('#shfm-a'))).value.trim(), b = (/** @type {any} */ (md.querySelector('#shfm-b'))).value.trim();
    if (!['empty', 'overdue'].includes(st.op) && !a) { toast(tr('Enter a value for the rule')); (/** @type {any} */ (md.querySelector('#shfm-a'))).focus(); return false; }
    if (st.op === 'between' && !b) { toast(tr('Enter both values for the rule')); (/** @type {any} */ (md.querySelector('#shfm-b'))).focus(); return false; }
    if (!st.color && !st.fill) { toast(tr('Choose a text colour or a fill for the rule')); return false; }
    st.rules.push({cols: cols.slice(), rows: st.scope === 'rows' ? rows : null, op: st.op, ...(['empty', 'overdue'].includes(st.op) ? {} : {a}), ...(st.op === 'between' ? {b} : {}), color: st.color, fill: st.fill});
    (/** @type {any} */ (md.querySelector('#shfm-a'))).value = ''; (/** @type {any} */ (md.querySelector('#shfm-b'))).value = '';
    draw(); return true;
  };
  md.addEventListener('change', e => { const t = /** @type {any} */ (e.target); if (t.id === 'shfm-op') { st.op = t.value; draw(); } if (t.name === 'shfm-sc') st.scope = t.value; });
  md.addEventListener('click', async e => {
    const b = (/** @type {any} */ (e.target)).closest('button'); if (!b) return;
    if (b.dataset.shfmrColor !== undefined) { st.color = b.dataset.shfmrColor; draw(); return; }
    if (b.dataset.shfmrFill !== undefined) { st.fill = b.dataset.shfmrFill; draw(); return; }
    if (b.dataset.shfmrRm !== undefined) { st.rules.splice(+b.dataset.shfmrRm, 1); draw(); return; }
    const m = b.dataset.m;
    if (m === 'close') { md.remove(); return; }
    if (m === 'add') { add(); return; }
    if (m !== 'save') return;
    if ((/** @type {any} */ (md.querySelector('#shfm-a'))).value.trim() && !add()) return;  // a rule typed but not added yet goes along
    md.remove();
    await shfm_rulesPut(st.rules, tr('Colour rules changed'));
  });
  setTimeout(() => (/** @type {any} */ (md.querySelector('#shfm-op')))?.focus(), 30);
}
async function shfm_rulesPut(rules, label) {
  const sh = SHV.sh; if (!sh) return;
  const sid = sh.id, old = JSON.parse(JSON.stringify(sh.rules || []));
  const put = async (to, rev) => {
    const r = await rawFetch('PUT', `/api/sheets/${sid}/rules`, {rules: to, ...(rev != null ? {expect_rev: rev} : {})});
    if (SHV.sh?.id === sid) { SHV.sh.rules = r.rules || []; if (r.rev != null) SHV.sh.rev = r.rev; shvRender(); }
    return r;
  };
  let res; try { res = await put(rules, sh.rev); } catch (e) { toast(e.message); if (e.status === 409) await shvLoad(sid, true); return; }
  const now = res.rules || [];
  histToast(label, histAdd({label, ids: [], snaps: [], lids: [], undo: async () => { await put(old); return {skipped: []}; }, redo: async () => { await put(now); return {skipped: []}; }}));
}
