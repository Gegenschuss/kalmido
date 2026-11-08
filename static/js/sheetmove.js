// @ts-check
/* Kalmido web client: move rows and columns of a table (2.631.0, #4620), loaded with the tables (lazyload.js). Drag a row's
   number or a column's head: the mouse at once, a finger after a long press on the head (then the row / column follows the
   finger, the grid scrolls at its edge). The head's menu has "Move up / down / left / right" too. Rows / columns that are
   chosen together (a range of cells) move together; every move is one Undo step (sheets.js shvStep). A long press in a cell
   stays as it is (sheets.js); only the heads lift. Formulas keep their references: a single one is stored by cell id and
   follows its cell, a range keeps its rows / columns (the server, kalmido/sheets/shorder.py). Reading only: no drag, no menu entries. A filtered view does not move rows (a hint says
   why: hidden rows would land in places one cannot see); a sorted column loses its arrow (the order is the own one now).
   The dragging itself is drag.js (drg_attach), the same as the sheet tabs (sheetbook.js).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

/** @type {{d: any, line: HTMLElement|null, st: HTMLStyleElement|null}} the running drag, its drop line, its style */
const SHMV = {d: null, line: null, st: null};

const shmv_filtered = (sh = SHV.sh) => !!sh && (Object.keys(shvFilt(sh)).length > 0 || (typeof shg_on === 'function' && shg_on(sh)));  // 2.671.0 (#3463): + grouped
const shmv_why = (sh = SHV.sh) => typeof shg_on === 'function' && shg_on(sh) ? tr('Remove the grouping to move rows') : tr('Reset the filters to move rows');
// the ids of the block that moves with id: the chosen rows / columns when id is one of them, else id alone
function shmv_block(sh, kind, id) {
  const q = shvRect(), [rs, cs] = shvGrid();
  if (q && SHV.sh === sh) {
    const ids = kind === 'row' ? rs.slice(q.r0, q.r1 + 1) : cs.slice(q.c0, q.c1 + 1);
    if (ids.length > 1 && ids.includes(id)) return ids;
  }
  return [id];
}
// the order after moving block to the place before all[at] (at = all.length: the end); null = nothing changes
function shmv_order(all, block, at) {
  const set = new Set(block), blk = all.filter(x => set.has(x)), rest = all.filter(x => !set.has(x));
  if (!blk.length) return null;
  const k = all.slice(0, Math.max(0, Math.min(all.length, at))).filter(x => !set.has(x)).length;
  const out = [...rest.slice(0, k), ...blk, ...rest.slice(k)];
  return out.join() === all.join() ? null : out;
}
// one move: the new order with the block named (the server keeps the ranges of formulas on their rows / columns,
// kalmido/sheets/shorder.py); its Undo is the old order with the formulas it changed (those still as the move left them get
// their text back). prev = the order this device saw: a move / sorting elsewhere meanwhile is refused (409, shvStep reloads)
async function shmv_go(kind, block, at) {
  const sh = SHV.sh; if (!sh?.can_write || !block.length) return;
  if (kind === 'row' && shmv_filtered(sh)) { toast(shmv_why()); return; }
  const sid = sh.id, all = kind === 'row' ? sh.rows.map(r => r.id) : sh.columns.map(c => c.id), ids = shmv_order(all, block, at); if (!ids) return;
  const url = `/api/sheets/${sid}/${kind === 'row' ? 'rows' : 'columns'}/order`;
  const msg = kind === 'row' ? trn('{0} row moved', '{0} rows moved', block.length) : trn('{0} column moved', '{0} columns moved', block.length);
  const srt = kind === 'row' && SHV.sorted?.sid === sid ? sh._col.get(SHV.sorted.c) : null;  // the arrow of a sorting does not hold any more
  if (srt) SHV.sorted = null;
  await shvStep(msg, () => rawFetch('POST', url, {ids, prev: all, moved: block}),
    res => rawFetch('POST', url, {ids: all, prev: ids, formulas: res?.formulas || []}),  // 2.658.0 (#5000): always named, else the server takes it for a sorting
    srt ? msg + ' · ' + tr('No longer sorted by {0}', srt.title || srt.letter) : msg);
}
const shmv_rows = (block, at) => shmv_go('row', block, at);
const shmv_cols = (block, at) => shmv_go('col', block, at);

// ---- dragging
function shmv_heads(kind) {  // [{id, r}] the shown heads in their order
  const sel = kind === 'row' ? '#shv-scroll tbody tr[data-id] > th.shvrh[data-r]' : '#shv-scroll thead th.shvch[data-c]';
  return [...document.querySelectorAll(sel)].map(th => ({id: +(kind === 'row' ? /** @type {HTMLElement} */ (th).dataset.r : /** @type {HTMLElement} */ (th).dataset.c), r: th.getBoundingClientRect()}));
}
// where a drop at (x, y) goes: {at (the index in the full order), line: the drop line in viewport coordinates}
function shmv_target(d, x, y) {
  const sh = SHV.sh, hs = shmv_heads(d.kind); if (!sh || !hs.length) return null;
  const all = d.kind === 'row' ? sh.rows.map(r => r.id) : sh.columns.map(c => c.id);
  const row = d.kind === 'row', i = hs.findIndex(h => row ? y < h.r.top + h.r.height / 2 : x < h.r.left + h.r.width / 2);
  const h = hs[i < 0 ? hs.length - 1 : i], at = i < 0 ? all.length : all.indexOf(h.id);
  const sc = $('#shv-scroll')?.getBoundingClientRect(); if (!sc || at < 0) return null;
  const edge = row ? (i < 0 ? h.r.bottom : h.r.top) : (i < 0 ? h.r.right : h.r.left);
  return {at, line: row ? {l: sc.left, t: edge - 1, w: sc.width, h: 3} : {l: edge - 1, t: sc.top, w: 3, h: sc.height}};
}
function shmv_mark(d) {  // the moving rows / columns pale, a line where they would go
  if (!SHMV.st) { SHMV.st = document.createElement('style'); SHMV.st.id = 'shmv-st'; document.head.appendChild(SHMV.st); }
  SHMV.st.textContent = d ? d.block.map(id => d.kind === 'row' ? `#shv-scroll tr[data-id="${id}"]>*` : `#shv-scroll [data-c="${id}"]:is(td,th)`).join(',') + '{opacity:.45}' : '';
  if (d && !SHMV.line) { SHMV.line = document.createElement('div'); SHMV.line.className = 'shmv-line'; SHMV.line.setAttribute('aria-hidden', 'true'); document.body.appendChild(SHMV.line); }
  if (!d && SHMV.line) { SHMV.line.remove(); SHMV.line = null; }
}
function shmv_line(t) {
  const el = SHMV.line; if (!el) return;
  el.hidden = !t;
  if (t) el.style.cssText = `left:${t.line.l}px;top:${t.line.t}px;width:${t.line.w}px;height:${t.line.h}px`;
}
function shmv_lift(d) {
  if (d.lifted) return;
  d.lifted = true;
  d.th.classList.add('drag');
  if (d.blocked) { toast(shmv_why()); return; }
  shmv_mark(d);
}
function shmv_clear(d) {
  d?.th?.classList.remove('drag');
  shmv_mark(null);
  SHMV.d = null;
}
const shmv_scroller = () => { const sc = $('#shv-scroll'); return sc && sc.scrollHeight > sc.clientHeight + 1 ? sc : /** @type {HTMLElement} */ (document.scrollingElement); };
drg_attach(document, {
  hold: ROWD_HOLD, holdMove: 8, onTarget: true, raf: true, ghost: {el: d => d.th, cls: 'ghost-drag shmv-ghost'},
  scroll: () => SHMV.d?.kind === 'row' ? shmv_scroller() : null, scrollX: () => SHMV.d?.kind === 'col' ? $('#shv-scroll') : null,
  scrollXInset: () => $('#shv-scroll th.shvcorner')?.getBoundingClientRect().width || 0, edge: 40, step: 12,
  start: (t, x, y, kind) => {
    const sh = SHV.sh;
    if (!sh?.can_write || S.route.mod !== 'sheets' || SHV.ed || t.closest?.('.shvrsz')) return null;
    const th = /** @type {HTMLElement} */ (t.closest?.('#shv-scroll th.shvrh[data-r], #shv-scroll th.shvch[data-c]')); if (!th) return null;
    const row = th.classList.contains('shvrh'), id = +(row ? th.dataset.r : th.dataset.c);
    const d = {th, kind: row ? 'row' : 'col', id, block: shmv_block(sh, row ? 'row' : 'col', id), touch: kind === 'touch', blocked: row && shmv_filtered(sh), lifted: false};
    SHMV.d = d;
    return d;
  },
  onHold: d => { shmv_lift(d); navigator.vibrate?.(12); },
  onStart: d => shmv_lift(d),
  onMove: (d, x, y) => { if (!d.blocked) shmv_line(shmv_target(d, x, y)); },
  onDrop: (d, x, y) => {
    const t = d.blocked ? null : shmv_target(d, x, y);
    shmv_clear(d);
    if (t) (d.kind === 'row' ? shmv_rows : shmv_cols)(d.block, t.at);
  },
  // a long press without moving: the head's menu (the touch's own click was swallowed); a mouse click opens it by itself
  onTap: d => { shmv_clear(d); if (d.touch && d.lifted && d.th.isConnected) d.th.querySelector('button')?.click(); },
  onCancel: d => shmv_clear(d),
});
// the phone's own menu of a long press (text selection, "copy") stays away from the heads
document.addEventListener('contextmenu', e => { if (/** @type {any} */ (e.target).closest?.('#shv-scroll th.shvrh, #shv-scroll th.shvch') && isTouch()) e.preventDefault(); });

// ---- the heads' menus
(SHV_HOOKS.rowmenu = SHV_HOOKS.rowmenu || []).push((sh, rid) => {
  if (!sh.can_write) return [];
  const all = sh.rows.map(r => r.id), blk = shmv_block(sh, 'row', rid), i = all.indexOf(blk[0]), j = all.indexOf(blk[blk.length - 1]);
  if (i < 0 || j < 0) return [];
  const it = [...(i > 0 ? [{label: tr('Move up'), act: 'shmv-up', icon: 'up', fn: () => shmv_rows(blk, i - 1)}] : []),
    ...(j < all.length - 1 ? [{label: tr('Move down'), act: 'shmv-down', icon: 'down', fn: () => shmv_rows(blk, j + 2)}] : [])];
  return it.length ? ['-', ...it] : [];
});
(SHV_HOOKS.colmenu = SHV_HOOKS.colmenu || []).push((sh, col) => {
  if (!sh.can_write) return [];
  const all = sh.columns.map(c => c.id), blk = shmv_block(sh, 'col', col.id), i = all.indexOf(blk[0]), j = all.indexOf(blk[blk.length - 1]);
  if (i < 0 || j < 0) return [];
  const it = [...(i > 0 ? [{label: tr('Move left'), act: 'shmv-left', icon: 'left', fn: () => shmv_cols(blk, i - 1)}] : []),
    ...(j < all.length - 1 ? [{label: tr('Move right'), act: 'shmv-right', icon: 'right', fn: () => shmv_cols(blk, j + 2)}] : [])];
  return it.length ? ['-', ...it] : [];
});
