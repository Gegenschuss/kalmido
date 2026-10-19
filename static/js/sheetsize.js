/* Kalmido web client: tables, the frame (2.98.0 C, #2181). On a computer the frame of a table has a grip at its bottom right
   corner: drag it (or focus it and use the arrow keys, Shift = bigger steps) to make the frame wider / narrower and higher /
   lower, also while the table is empty; the size is kept per table on this device (LS shzSize, rem), a double click on the
   grip (or Home / Delete) goes back to the automatic size. Empty columns and rows fill the frame (display only: nothing is
   created until something is typed into one of them; then the missing rows / columns are added like at the edge today and
   the value is written, ONE undo step). Two buttons next to "Dependencies": "Open in its own window" (/?mini=1#sheets/<id>,
   miniwin.js: no sidebar, live like any tab through the area "sheets" of /api/version) and full screen. Phones: none of it.
   Hangs into sheets.js through typeof checks (shz_plan, shz_colsHtml, shz_headHtml, shz_rowTail, shz_bodyHtml,
   shz_boxAttr, shz_gripHtml, shz_btnsHtml, shz_fill).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const SHZ = {plan: null, live: null, w: {}, ro: null, el: null, ph: null, t: 0};
const SHZ_MIN_W = 16, SHZ_MIN_H = 8, SHZ_AUTO_H = 22, SHZ_COL = 7;  // rem; SHZ_AUTO_H = the automatic frame's height (CSS)
const shz_on = () => !isMobile();
const shz_rem = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
const shz_mini = () => typeof MW_ON !== 'undefined' && MW_ON && /^#sheets\/\d+/.test(location.hash);
const shz_full = () => document.documentElement.classList.contains('shzfull') || shz_mini();  // the frame = the window
// the size of a table's frame in rem ({w, h}) or null = automatic; while the grip is dragged its live size
function shz_size(id) {
  if (SHZ.live?.id === id) return SHZ.live;
  const s = (LS.get('shzSize', {}) || {})[id];
  return s && s.w > 0 && s.h > 0 ? s : null;
}
function shz_save(id, s) {
  const o = LS.get('shzSize', {}) || {};
  if (s) o[id] = {w: Math.round(s.w * 4) / 4, h: Math.round(s.h * 4) / 4}; else delete o[id];
  LS.set('shzSize', o);
}
// the letter of the n-th column (0 = A): what the next columns will be called
const shz_letter = n => { let s = ''; for (let i = n + 1; i > 0; i = Math.floor((i - 1) / 26)) s = String.fromCharCode(65 + (i - 1) % 26) + s; return s; };

// ---- the empty cells: how many columns / rows fill the frame (worked out from the sizes, not measured from the grid, so
// the cells never feed back into the frame's own size)
function shz_plan(sh) {
  SHZ.plan = null;
  if (!sh || !shz_on()) return false;
  const s = shz_full() ? null : shz_size(sh.id), el = document.getElementById('shv-scroll'), rem = shz_rem();
  const W = s ? s.w : el && el.closest('.shvsheet')?.dataset.k === 'shv-' + sh.id ? el.clientWidth / rem : SHZ.w[sh.id] || 0;
  const H = s ? s.h : shz_full() ? (el ? el.clientHeight / rem : 0) : SHZ_AUTO_H;
  if (el) SHZ.w[sh.id] = el.clientWidth / rem;
  if (!(W > 0)) return false;  // no frame measured yet (first draw, no layout): no empty cells
  const rowH = matchMedia('(hover: none)').matches ? 2.75 : 2;
  const tw = 2.75 + sh.columns.reduce((a, c) => a + shvW(c) / 16, 0) + (sh.can_write ? 2.5 : 0);
  const n = shvVisRows(sh).length, free = H - rowH * (n + 1) - .125;
  const c = Math.max(0, Math.min(30, Math.ceil((W - tw - .125) / SHZ_COL)));
  const r = Math.max(0, Math.min(80, s ? Math.ceil(free / rowH) : Math.floor(free / rowH)));
  SHZ.plan = {id: sh.id, c, r, n};
  return c > 0 || r > 0;
}
const shz_p = sh => SHZ.plan?.id === sh.id ? SHZ.plan : null;
const shz_rep = (n, f) => Array.from({length: n}, (_, i) => f(i)).join('');
const shz_colsHtml = sh => shz_rep(shz_p(sh)?.c || 0, () => '<col class="shzcol">');
const shz_headHtml = sh => shz_rep(shz_p(sh)?.c || 0, j => `<th class="shzph" aria-hidden="true"><span class="shvlet">${shz_letter(sh.columns.length + j)}</span></th>`);
const shz_td = (a, j) => `<td class="shzph" ${a} data-shzc="${j}"></td>`;
const shz_rowTail = (sh, r) => shz_rep(shz_p(sh)?.c || 0, j => shz_td(`data-shzr="${r.id}"`, j));
function shz_bodyHtml(sh) {
  const p = shz_p(sh); if (!p?.r) return '';
  return `<tbody class="shzrows" aria-hidden="true">${shz_rep(p.r, i => `<tr class="shzph"><th class="shvrh shzrh" scope="row"><span>${p.n + i + 1}</span></th>${sh.columns.map(col => `<td class="shzph" data-shzp="${i}" data-shzcid="${col.id}"></td>`).join('')}${sh.can_write ? '<td class="shvpad"></td>' : ''}${shz_rep(p.c, j => shz_td(`data-shzp="${i}"`, j))}</tr>`)}</tbody>`;
}
// the frame: its size (or the automatic one) and the grip
function shz_boxAttr(sh) {
  if (!shz_on() || shz_full()) return '';
  const s = shz_size(sh.id); return s ? ` data-shzset="1" style="width:${s.w}rem;height:${s.h}rem"` : '';
}
function shz_gripHtml(sh) {
  if (!shz_on() || shz_full()) return '';
  return `<button type="button" class="shzgrip" id="shz-grip" data-shzgrip="${sh.id}" aria-label="${esc(tr('Resize (arrow keys; double-click: default size)'))}" title="${esc(tr('Drag to resize · double-click: default size'))}"></button>`;
}
// the buttons next to "Dependencies": its own window (not in that window itself), full screen
function shz_btnsHtml(sh) {
  if (!shz_on()) return '';
  const fs = document.documentElement.classList.contains('shzfull');
  return `${typeof MW_ON !== 'undefined' && MW_ON ? '' : `<button type="button" class="iconbtn" data-shz="win" title="${esc(tr('Open in its own window'))}" aria-label="${esc(tr('Open in its own window'))}">${ic('panel', 's')}</button>`}`
    + `${shz_mini() ? '' : `<button type="button" class="iconbtn" data-shz="full" aria-pressed="${fs}" title="${esc(fs ? tr('Leave full screen') : tr('Full screen'))}" aria-label="${esc(fs ? tr('Leave full screen') : tr('Full screen'))}">${ic(fs ? 'collapse' : 'expand', 's')}</button>`}`;
}
// after a draw: watch the frame; a frame of another width (window, panel, grip) gets its cells anew
function shz_fill() {
  const el = document.getElementById('shv-scroll'); if (!el || !SHV.sh) return;
  if (SHZ.el === el) return;
  SHZ.ro?.disconnect(); SHZ.el = el;
  if (typeof ResizeObserver !== 'function') return;
  SHZ.ro = new ResizeObserver(() => {
    const sh = SHV.sh; if (!sh || !el.isConnected) return;
    const was = SHZ.plan ? SHZ.plan.c + ':' + SHZ.plan.r : '';
    shz_plan(sh);
    if ((SHZ.plan ? SHZ.plan.c + ':' + SHZ.plan.r : '') !== was) { cancelAnimationFrame(SHZ.t); SHZ.t = requestAnimationFrame(() => shvRender()); }
  });
  SHZ.ro.observe(el);
}

// ---- the grip: drag, keys, double click
function shz_maxW(box) { const g = box.closest('.shvgridw'); return g ? g.clientWidth / shz_rem() : 200; }
function shz_set(id, s, keep) {
  const box = $('.shvsheet .shzbox'); if (!box) return;
  const w = Math.max(SHZ_MIN_W, Math.min(shz_maxW(box), s.w)), h = Math.max(SHZ_MIN_H, Math.min(200, s.h));
  if (keep) { SHZ.live = {id, w, h}; box.dataset.shzset = '1'; box.style.width = w + 'rem'; box.style.height = h + 'rem'; return; }
  SHZ.live = null; shz_save(id, {w, h}); shvRender();
}
function shz_auto(id) { SHZ.live = null; shz_save(id, null); shvRender(); requestAnimationFrame(() => $('#shz-grip')?.focus({preventScroll: true})); }
document.addEventListener('pointerdown', e => {
  const g = e.target.closest?.('[data-shzgrip]'); if (!g || e.button !== 0) return;
  e.preventDefault();
  const id = +g.dataset.shzgrip, box = g.closest('.shzbox'), rem = shz_rem(), b = box.getBoundingClientRect(), x0 = e.clientX, y0 = e.clientY;
  let moved = false;
  const mv = ev => { moved = true; shz_set(id, {w: (b.width + ev.clientX - x0) / rem, h: (b.height + ev.clientY - y0) / rem}, true); };
  const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); const s = SHZ.live; if (moved && s) shz_set(id, s); else SHZ.live = null; };
  addEventListener('pointermove', mv); addEventListener('pointerup', up);
});
document.addEventListener('dblclick', e => { const g = e.target.closest?.('[data-shzgrip]'); if (g) { e.preventDefault(); shz_auto(+g.dataset.shzgrip); } });

// ---- typing into an empty cell of the frame: choose it with a click, then type (or Enter / F2 / double click); Enter or
// leaving the field adds the missing rows and columns and writes the value, Esc leaves it empty
function shz_phOf(td) {
  const d = td.dataset;
  return {r: d.shzr ? +d.shzr : null, p: d.shzp != null ? +d.shzp : null, cid: d.shzcid ? +d.shzcid : null, c: d.shzc != null ? +d.shzc : null};
}
function shz_choose(td) {
  if (SHV.ed) shvEditEnd(true);
  SHV.cur = SHV.anc = null; shvPaintSel();
  $$('#shv-scroll td.shzon').forEach(x => x.classList.remove('shzon'));
  td.classList.add('shzon'); td.tabIndex = -1; td.focus({preventScroll: true});
  SHZ.ph = {td, ...shz_phOf(td)};
}
function shz_edit(typed) {
  const ph = SHZ.ph; if (!ph?.td.isConnected || !SHV.sh?.can_write) return;
  ph.td.innerHTML = `<input class="shvin" id="shz-ed" value="${esc(typed || '')}" autocomplete="off" spellcheck="false" aria-label="${esc(tr('Content of the cell'))}">`;
  const i = $('#shz-ed'); i.focus({preventScroll: true}); i.setSelectionRange(i.value.length, i.value.length);
}
async function shz_done(save) {
  const ph = SHZ.ph, inp = $('#shz-ed'); if (!ph || !inp) return;
  const v = inp.value; SHZ.ph = null;
  inp.remove(); $('#shv-scroll')?.focus({preventScroll: true});
  if (save && v.trim()) await shz_put(ph, v);
}
async function shz_put(ph, raw) {
  const sh = SHV.sh; if (!sh?.can_write) return;
  const sid = sh.id, rows = [], cols = [];
  const drop = async () => { for (const x of cols) await rawFetch('DELETE', `/api/sheets/${sid}/columns/${x}`).catch(() => {}); for (const x of rows) await rawFetch('DELETE', `/api/sheets/${sid}/rows/${x}`).catch(() => {}); };
  try {
    if (ph.p != null) {
      const before = new Set(sh.rows.map(r => r.id));
      await rawFetch('POST', `/api/sheets/${sid}/rows`, {after_row_id: sh.rows[sh.rows.length - 1]?.id ?? null, count: ph.p + 1});
      rows.push(...((await rawFetch('GET', '/api/sheets/' + sid)).rows || []).map(r => r.id).filter(x => !before.has(x)));
    }
    for (let k = 0; ph.c != null && k <= ph.c; k++) {
      const last = cols[cols.length - 1] || sh.columns[sh.columns.length - 1]?.id || null, before = new Set([...sh.columns.map(c => c.id), ...cols]);
      const r = await rawFetch('POST', `/api/sheets/${sid}/columns`, {title: '', kind: 'text', ...(last ? {after_col_id: last} : {})});
      const cid = r?.id || r?.column?.id || ((await rawFetch('GET', '/api/sheets/' + sid)).columns || []).map(c => c.id).find(x => !before.has(x));
      if (!cid) throw new Error(tr('Error'));
      cols.push(cid);
    }
    const row = ph.r ?? rows[ph.p], col = ph.cid ?? cols[ph.c];
    if (!row || !col) throw new Error(tr('Error'));
    await rawFetch('PUT', `/api/sheets/${sid}/cells`, {cells: [{row_id: row, col_id: col, raw}]});
    await shvLoad(sid, true);
    const addr = shvAddr(row, col);
    histAdd({label: tr('Cell {0} changed', addr), ids: [], snaps: [], lids: [],
      undo: async () => { await drop(); if (SHV.sh?.id === sid) await shvLoad(sid, true); return {skipped: []}; },
      redo: async () => {
        for (const x of rows) await rawFetch('POST', `/api/sheets/${sid}/rows/${x}/restore`);
        for (const x of cols) await rawFetch('POST', `/api/sheets/${sid}/columns/${x}/restore`);
        if (SHV.sh?.id === sid) await shvLoad(sid, true); return {skipped: []};
      }});
    if (SHV.sh?.id === sid) { SHV.cur = SHV.anc = {r: row, c: col}; shvRender(); requestAnimationFrame(() => $('#shv-scroll')?.focus({preventScroll: true})); }
  } catch (e) {
    await drop(); if (e.message !== 'auth') toast(e.message);
    if (SHV.sh?.id === sid) await shvLoad(sid, true);
  }
}
document.addEventListener('pointerdown', e => {
  const td = e.target.closest?.('#shv-scroll td.shzph'); if (!td || e.button > 0 || !SHV.sh) return;
  if (td.querySelector('#shz-ed')) return;
  if (SHZ.ph && $('#shz-ed')) shz_done(true);
  e.preventDefault(); shz_choose(td);
});
document.addEventListener('dblclick', e => { const td = e.target.closest?.('#shv-scroll td.shzph'); if (td && SHZ.ph?.td === td && !$('#shz-ed')) shz_edit(''); });
// keys (window capture, before the grid's own keys): the grip, a chosen empty cell, its field
window.addEventListener('keydown', e => {
  const t = e.target;
  if (t?.matches?.('[data-shzgrip]')) {
    const id = +t.dataset.shzgrip, box = t.closest('.shzbox'), rem = shz_rem(), st = e.shiftKey ? 4 : 1;
    const d = {ArrowRight: [st, 0], ArrowLeft: [-st, 0], ArrowDown: [0, st], ArrowUp: [0, -st]}[e.key];
    if (d && box) {
      e.preventDefault(); e.stopPropagation();
      const b = box.getBoundingClientRect(); shz_set(id, {w: b.width / rem + d[0], h: b.height / rem + d[1]});
      requestAnimationFrame(() => $('#shz-grip')?.focus({preventScroll: true}));
    } else if (e.key === 'Home' || e.key === 'Delete') { e.preventDefault(); e.stopPropagation(); shz_auto(id); }
    return;
  }
  if (t?.id === 'shz-ed') {
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); shz_done(true); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); shz_done(false); }
    else e.stopPropagation();
    return;
  }
  if (!t?.matches?.('#shv-scroll td.shzph') || SHZ.ph?.td !== t) return;
  e.stopPropagation();
  if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
  if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); shz_edit(''); }
  else if (e.key.length === 1) { e.preventDefault(); shz_edit(e.key); }
  else if (e.key === 'Escape' || e.key.startsWith('Arrow')) { e.preventDefault(); t.classList.remove('shzon'); SHZ.ph = null; $('#shv-scroll')?.focus({preventScroll: true}); }
}, true);
document.addEventListener('focusout', e => { if (e.target.id === 'shz-ed') setTimeout(() => { if ($('#shz-ed') && document.activeElement?.id !== 'shz-ed') shz_done(true); }, 120); });

// ---- its own window and full screen
function shz_win(id) {
  const w = Math.min(1100, screen.availWidth || 1100), h = Math.min(760, screen.availHeight || 760);
  const x = Math.max(0, (window.screenX || 0) + 60), y = Math.max(0, (window.screenY || 0) + 60);
  const win = window.open(`/?mini=1#sheets/${id}`, 'kalmido-sheet-' + id, `popup,width=${w},height=${h},left=${x},top=${y}`);
  if (!win) { toast(tr('The browser blocked the window. Allow pop-ups for this page.')); return null; }
  try { win.focus(); } catch { /* closed */ }
  return win;
}
function shz_fullSet(on) {
  const h = document.documentElement; if (h.classList.contains('shzfull') === on) return;
  h.classList.toggle('shzfull', on);
  try { if (on && !document.fullscreenElement) h.requestFullscreen?.()?.catch?.(() => {}); else if (!on && document.fullscreenElement) document.exitFullscreen?.()?.catch?.(() => {}); } catch { /* not allowed */ }
  if (S.route.mod === 'sheets') shvRender();
}
document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) shz_fullSet(false); });
window.addEventListener('hashchange', () => { if (!/^#sheets\/\d+/.test(location.hash)) shz_fullSet(false); });
window.addEventListener('keydown', e => { if (e.key === 'Escape' && document.documentElement.classList.contains('shzfull') && !document.fullscreenElement && !e.target.closest?.('input,textarea,.menu-list,#pop,.smodal')) shz_fullSet(false); });
document.addEventListener('click', e => {
  const b = e.target.closest?.('button[data-shz]'); if (!b || !SHV.sh) return;
  e.preventDefault(); e.stopPropagation();
  if (b.dataset.shz === 'win') shz_win(SHV.sh.id);
  else if (b.dataset.shz === 'full') shz_fullSet(!document.documentElement.classList.contains('shzfull'));
}, true);
// the table's own window: only this table (miniwin.js keeps the window's UI state to itself), its name as the title
if (shz_mini()) {
  document.documentElement.classList.add('mini-sheet');
  const title = () => { if (SHV.sh && document.title !== `${SHV.sh.title || tr('Table')} · ${APP_NAME}`) document.title = `${SHV.sh.title || tr('Table')} · ${APP_NAME}`; };
  setInterval(title, 1000);
}
