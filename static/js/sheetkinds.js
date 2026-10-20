// @ts-check
/* Kalmido web client: tables, 2.124.0 B (#2110, #2111, #2112) -- more column kinds, rows / columns kept in view, print and
   the history of the cells. Loaded with sheets.js (lazyload.js, module "sheets"); hooks into sheets.js through shk_td (a cell's
   content), shk_edit (Enter / a second tap on a cell), shk_after (after each redraw) and SHV_HOOKS (menus, panel).
   - checkbox: a tap on the box (or Space / Enter on the cell) ticks it; the server stores 1 / 0 (SUMME counts the ticks)
   - person: a menu of the people who may see the table (GET …/people); shown with the picture and the name
   - link: typed like text (http, https, mailto; the server refuses anything else), the arrow opens it in a new tab
   - file: a menu (upload, open, remove); the file is uploaded into the cell (POST …/files), Undo puts the cell back
   - "Keep in view up to here" in the column / row menu: the first N columns / rows stay put while scrolling (sticky)
   - "Print / PDF": a plain print view of the shown rows (the browser's print dialog also saves a PDF; header row repeated)
   - "History": the latest changes of the chosen cell, "Recent changes" of the whole table (who, when, before -> after)
   Every change is one Undo step. Classic script sharing the global scope with the others. */
'use strict';

const SHK = {people: {}, fix: null};
SHV_KINDS.push(['checkbox', N_('Checkbox')], ['person', N_('Person')], ['link', N_('Link')], ['file', N_('File')]);
Object.assign(SHV_KICON, {checkbox: 'check', person: 'user', link: 'link', file: 'clip'});
const SHK_KINDS = ['checkbox', 'person', 'link', 'file'];
const shk_isF = c => String(c?.raw || '').startsWith('=');
const shk_on = c => !!c && !shk_isF(c) && !c.error && c.value === 1;
const shk_fileId = c => { const m = /^file:(\d+)$/.exec(String(c?.raw || '').trim()); return m ? +m[1] : null; };
const shk_fileUrl = (sid, fid, dl) => `/api/sheets/${sid}/files/${fid}${dl ? '?dl=1' : ''}`;
const shk_short = u => { const s = String(u || '').replace(/^mailto:/i, '').replace(/^https?:\/\/(www\.)?/i, '').replace(/\/$/, ''); return s.length > 48 ? s.slice(0, 46) + '…' : s; };

// ---- a cell's content (sheets.js shvTd): null = as before
function shk_td(sh, col, c, rid, cls) {
  if (!SHK_KINDS.includes(col.kind) || (c && (shk_isF(c) || c.error))) return null;
  if (col.kind === 'checkbox') {
    const on = shk_on(c);
    cls.push('shkcb');
    return `<span class="shkbox${on ? ' on' : ''}" data-shkbox role="checkbox" aria-checked="${on}" aria-label="${esc(on ? tr('Yes') : tr('No'))}">${on ? ic('check', 's') : ''}</span>`;
  }
  if (!c || !String(c.raw || '').trim()) return col.kind === 'file' && sh.can_write ? `<span class="shkadd" aria-hidden="true">${ic('upload', 's')}</span>` : '';
  if (col.kind === 'person') {
    const id = /^\d+$/.test(String(c.raw).trim()) ? +c.raw : 0;
    return id ? `${av(id, c.display || '?', 'avatar shkav')}<span class="shvv">${esc(c.display || '')}</span>` : null;
  }
  if (col.kind === 'link') {
    const u = String(c.raw).trim();
    if (!/^(https?:\/\/|mailto:)/i.test(u)) return null;
    return `<span class="shvv">${esc(shk_short(u))}</span><a class="shklnk" href="${esc(u)}" target="_blank" rel="noopener noreferrer" title="${esc(tr('Open {0}', u))}" aria-label="${esc(tr('Open {0}', u))}">${ic('arrow', 's')}</a>`;
  }
  const fid = shk_fileId(c); if (!fid) return null;
  return `${ic('clip', 's')}<span class="shvv">${esc(c.display || '')}</span><a class="shklnk" href="${shk_fileUrl(sh.id, fid)}" target="_blank" rel="noopener noreferrer" title="${esc(tr('Open {0}', c.display || ''))}" aria-label="${esc(tr('Open {0}', c.display || ''))}">${ic('arrow', 's')}</a>`;
}

// ---- editing (sheets.js shvEditStart): true = handled here
function shk_edit(cur, col, typed) {
  const sh = SHV.sh; if (!sh?.can_write || !col || !SHK_KINDS.includes(col.kind)) return false;
  if (col.kind === 'link') return false;  // typed like text
  const c = shvCell(cur.r, cur.c); if (shk_isF(c) && typed == null) return false;  // a formula stays editable as text
  if (col.kind === 'checkbox') { if (typed == null || typed === ' ' || /^[xX1]$/.test(typed)) shk_toggle(cur.r, cur.c); return true; }
  if (col.kind === 'person') { shk_personMenu(cur.r, cur.c); return true; }
  shk_fileMenu(cur.r, cur.c); return true;
}
async function shk_toggle(r, c) {
  const on = shk_on(shvCell(r, c)), label = tr('Cell {0} changed', shvAddr(r, c));
  const e = await shvPut([{row_id: r, col_id: c, raw: on ? '0' : '1'}], label);
  if (e) histToast(label, e);  // 2.138.3 B (#2371): the Undo hint like other cell changes
  return e;
}
async function shk_peopleOf(sid) {
  const x = SHK.people[sid]; if (x && Date.now() - x.at < 60000) return x.list;
  const j = await rawFetch('GET', `/api/sheets/${sid}/people`);
  SHK.people[sid] = {at: Date.now(), list: j.people || []};
  return SHK.people[sid].list;
}
async function shk_personMenu(r, c) {
  const sh = SHV.sh, col = sh._col.get(c), cell = shvCell(r, c), addr = shvAddr(r, c);
  let ps; try { ps = await shk_peopleOf(sh.id); } catch (e) { toast(e.message); return; }
  const cur = String(cell?.raw || '').trim();
  const items = ps.map(p => ({label: p.name || '?', icon: 'user', on: cur === String(p.id), fn: () => shvPut([{row_id: r, col_id: c, raw: String(p.id)}], tr('Cell {0} changed', addr))}));
  if (!items.length) items.push({label: tr('Nobody can be chosen here'), dis: true, fn: () => {}});
  items.push('-', {label: tr('(empty)'), icon: 'x', fn: () => shvPut([{row_id: r, col_id: c, raw: ''}], tr('Cell {0} emptied', addr))});
  menu(document.getElementById(`shv-c-${r}-${c}`) || $('#shv-scroll'), items, null, null, col?.title || col?.letter);
}
function shk_fileMenu(r, c) {
  const sh = SHV.sh, col = sh._col.get(c), cell = shvCell(r, c), fid = shk_fileId(cell), addr = shvAddr(r, c);
  /** @type {any[]} */
  const items = [{label: fid ? tr('Replace file…') : tr('Upload file…'), icon: 'upload', fn: () => shk_pick(r, c)}];
  if (fid) items.push({label: tr('Open'), icon: 'file', fn: () => window.open(shk_fileUrl(sh.id, fid), '_blank', 'noopener')},
    {label: tr('Download'), icon: 'download', fn: () => { location.href = shk_fileUrl(sh.id, fid, true); }},
    '-', {label: tr('Remove file'), icon: 'trash', cls: 'flag-5', fn: () => shvPut([{row_id: r, col_id: c, raw: ''}], tr('Cell {0} emptied', addr))});
  menu(document.getElementById(`shv-c-${r}-${c}`) || $('#shv-scroll'), items, null, null, col?.title || col?.letter);
}
function shk_pick(r, c) {
  const inp = document.createElement('input'); inp.type = 'file';
  inp.addEventListener('change', () => { const f = inp.files?.[0]; if (f) shk_upload(r, c, f); });
  inp.click();
}
async function shk_upload(r, c, f) {
  const sh = SHV.sh; if (!sh?.can_write) return;
  const sid = sh.id, addr = shvAddr(r, c), fd = new FormData();
  fd.append('file', f); fd.append('row_id', String(r)); fd.append('col_id', String(c));
  let j; try { j = await rawFetch('POST', `/api/sheets/${sid}/files`, fd); } catch (e) { toast(e.message); return; }
  shvMerge(sid, j, [{row_id: r, col_id: c, raw: 'file:' + j.file.id}]);
  const now = [{row_id: r, col_id: c, raw: 'file:' + j.file.id}], old = [{row_id: r, col_id: c, raw: j.old_raw || ''}];
  const e = histAdd({label: tr('File {0} added', f.name), ids: [], snaps: [], lids: [],
    undo: async () => { await shvSend(sid, old); return {skipped: []}; }, redo: async () => { await shvSend(sid, now); return {skipped: []}; }});
  histToast(tr('File {0} added to {1}', f.name, addr), e);
}
// a tap / click on a checkbox ticks it at once (window capture: before the grid's own tap handling)
// 2.138.3 B (#2371): on the phone a tap anywhere in the cell ticks (the box alone was too small a target); with the mouse
// only the box (plus its 44 px square), so a click beside it still chooses the cell and Shift / dragging still select a
// range; a long press still shows the cell, a tap while writing a formula still inserts the reference
window.addEventListener('click', e => {
  const t = /** @type {any} */ (e.target);
  let b = t.closest?.('#shv-scroll [data-shkbox]');
  if (!b && isTouch() && !SHV.ed && Date.now() - (SHV.lpDone || 0) >= 600) b = t.closest?.('#shv-scroll td.shvc.shkcb[data-r]')?.querySelector('[data-shkbox]');
  if (!b) return;
  const td = b.closest('td.shvc[data-r]'), sh = SHV.sh; if (!td || !sh) return;
  e.preventDefault(); e.stopPropagation();
  const r = +td.dataset.r, c = +td.dataset.c;
  if (!SHV.cur || SHV.cur.r !== r || SHV.cur.c !== c) shvSelect(r, c);
  if (sh.can_write) shk_toggle(r, c); else roToast();
}, true);
// a file dropped on a file cell goes into it (computer)
document.addEventListener('dragover', e => { const td = /** @type {any} */ (e.target).closest?.('#shv-scroll td.shvc.k-file'); if (td && SHV.sh?.can_write && e.dataTransfer?.types?.includes('Files')) e.preventDefault(); });
document.addEventListener('drop', e => {
  const td = /** @type {any} */ (e.target).closest?.('#shv-scroll td.shvc.k-file'); if (!td || !SHV.sh?.can_write) return;
  const f = e.dataTransfer?.files?.[0]; if (!f) return;
  e.preventDefault(); shk_upload(+td.dataset.r, +td.dataset.c, f);
});

// ---- rows / columns kept in view (sticky), changed in the column / row menu
async function shk_fixSet(body, label) {
  const sh = SHV.sh; if (!sh?.can_write) return;
  const sid = sh.id, old = {rows: sh.freeze_rows || 0, cols: sh.freeze_cols || 0}, now = {...old, ...body};
  const set = async v => { const j = await rawFetch('POST', `/api/sheets/${sid}/fixed`, v); if (SHV.sh?.id === sid) { SHV.sh.freeze_rows = j.freeze_rows; SHV.sh.freeze_cols = j.freeze_cols; SHV.sh.rev = j.rev; shk_after(); } };
  try { await set(now); } catch (e) { toast(e.message); return; }
  const e = histAdd({label, ids: [], snaps: [], lids: [], undo: async () => { await set(old); return {skipped: []}; }, redo: async () => { await set(now); return {skipped: []}; }});
  histToast(label, e);
}
function shk_after() {  // after each redraw: the sticky rules of the kept rows / columns (offsets measured in the grid)
  let st = document.getElementById('shk-fix');
  const sh = SHV.sh, tb = $('#shv-scroll .shvgrid');
  const nr = sh && tb ? Math.min(sh.freeze_rows || 0, shvVisRows(sh).length) : 0, nc = sh && tb ? Math.min(sh.freeze_cols || 0, sh.columns.length) : 0;
  if (!nr && !nc) { if (st) st.textContent = ''; return; }
  if (!st) { st = document.createElement('style'); st.id = 'shk-fix'; document.head.appendChild(st); }
  const out = [], rows = shvVisRows(sh).slice(0, nr), cols = sh.columns.slice(0, nc);
  for (const r of rows) {
    const tr0 = tb.querySelector(`tbody tr[data-id="${r.id}"]`); if (!tr0) continue;
    out.push(`#shv-scroll tbody tr[data-id="${r.id}"]>*{position:sticky;top:${tr0.offsetTop}px;z-index:2}`, `#shv-scroll tbody tr[data-id="${r.id}"]>th.shvrh{z-index:4}`);
  }
  if (rows.length) out.push(`#shv-scroll tbody tr[data-id="${rows[rows.length - 1].id}"]>*{box-shadow:inset 0 -.125rem 0 var(--line2)}`);
  for (const c of cols) {
    const th = tb.querySelector(`thead th[data-c="${c.id}"]`); if (!th) continue;
    out.push(`#shv-scroll td[data-c="${c.id}"],#shv-scroll th[data-c="${c.id}"]{position:sticky;left:${th.offsetLeft}px;z-index:1}`, `#shv-scroll thead th[data-c="${c.id}"]{z-index:4}`);
    for (const r of rows) out.push(`#shv-scroll tbody tr[data-id="${r.id}"]>td[data-c="${c.id}"]{z-index:3}`);
  }
  if (cols.length) out.push(`#shv-scroll [data-c="${cols[cols.length - 1].id}"]:is(td,th){box-shadow:inset -.125rem 0 0 var(--line2)}`);
  st.textContent = out.join('\n');
}
(SHV_HOOKS.colmenu = SHV_HOOKS.colmenu || []).push((sh, col) => {
  if (!sh.can_write) return [];
  const i = sh.columns.findIndex(c => c.id === col.id) + 1, n = sh.freeze_cols || 0;
  return ['-', {label: tr('Keep columns in view up to here'), icon: 'pin', on: n === i, fn: () => shk_fixSet({cols: n === i ? 0 : i}, n === i ? tr('Columns released') : trn('{0} column kept in view', '{0} columns kept in view', i))},
    ...(n ? [{label: tr('Release the kept columns'), icon: 'x', fn: () => shk_fixSet({cols: 0}, tr('Columns released'))}] : [])];
});
(SHV_HOOKS.rowmenu = SHV_HOOKS.rowmenu || []).push((sh, rid) => {
  if (!sh.can_write) return [];
  const i = shvVisRows(sh).findIndex(r => r.id === rid) + 1, n = sh.freeze_rows || 0;
  if (i < 1) return [];
  return ['-', {label: tr('Keep rows in view up to here'), icon: 'pin', on: n === i, fn: () => shk_fixSet({rows: n === i ? 0 : i}, n === i ? tr('Rows released') : trn('{0} row kept in view', '{0} rows kept in view', i))},
    ...(n ? [{label: tr('Release the kept rows'), icon: 'x', fn: () => shk_fixSet({rows: 0}, tr('Rows released'))}] : [])];
});

// ---- print / PDF: a plain view of the shown rows (the browser's dialog prints or saves a PDF)
/** @type {null|(() => void)} */
let shkPrintDone = null;
function shk_print() {
  const sh = SHV.sh; if (!sh) return;
  const rows = shvVisRows(sh), cols = sh.columns;
  const txt = (r, col) => { const c = shvCell(r.id, col.id, sh); if (!c) return ''; if (c.error) return c.error_text || tr(SHV_ERR[c.error] || N_('Error'));
    if (col.kind === 'select') return shvOpt(col, c)?.label || ''; if (col.kind === 'checkbox' && !shk_isF(c)) return shk_on(c) ? tr('Yes') : ''; return String(c.display ?? c.value ?? ''); };
  shkPrintDone?.(); document.getElementById('shk-print')?.remove();
  const box = document.createElement('div'); box.id = 'shk-print';
  box.innerHTML = `<h1>${esc(sh.title || tr('Untitled table'))}</h1><p class="shkpm">${esc(fmtWhen(new Date().toISOString()))}${rows.length < sh.rows.length ? ' · ' + esc(tr('{0} of {1} rows shown', rows.length, sh.rows.length)) : ''}</p>
    <table><thead><tr><th></th>${cols.map(c => `<th>${esc(c.title || c.letter || '')}</th>`).join('')}</tr></thead>
    <tbody>${rows.map(r => `<tr><th>${sh._rowNo.get(r.id)}</th>${cols.map(col => `<td class="${SHV_NUM.includes(col.kind) ? 'num' : ''}">${esc(txt(r, col))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  document.body.appendChild(box);
  document.body.classList.add('shkprint');
  // 2.138.3 A (#2370): Android Chrome fires afterprint ~30 ms after print(), before the preview is made -> keep the view until
  // the print media really ends (matchMedia change); without it, a fallback timer after afterprint
  /** @type {any} */
  const mq = window.matchMedia?.('print') || {matches: false}; let timer = 0, t0 = Infinity;
  const done = () => { clearTimeout(timer); document.body.classList.remove('shkprint'); box.remove(); removeEventListener('afterprint', onAfter); mq.removeEventListener?.('change', onMq); if (shkPrintDone === done) shkPrintDone = null; };
  const onMq = () => { clearTimeout(timer); if (!mq.matches) done(); };
  const onAfter = () => { clearTimeout(timer); if (mq.matches || performance.now() - t0 < 500) timer = setTimeout(done, 30000); else done(); };  // desktop: print() blocks until the dialog closes
  shkPrintDone = done;
  addEventListener('afterprint', onAfter);
  mq.addEventListener?.('change', onMq);
  setTimeout(() => { t0 = performance.now(); window.print(); }, 50);  // the view goes after printing (afterprint); on screen it is never shown
}

// ---- history
async function shh_open(cell) {
  const sh = SHV.sh; if (!sh) return;
  const url = cell ? `/api/sheets/${sh.id}/cells/${cell.id}/history` : `/api/sheets/${sh.id}/history`;
  let j; try { j = await rawFetch('GET', url); } catch (e) { toast(e.message); return; }
  const es = j.entries || [];
  const val = v => v === '' || v == null ? `<span class="muted">${tr('(empty)')}</span>` : `<span class="shhv">${esc(v)}</span>`;
  /** @type {any} */
  const md = modal(`<h3>${cell ? esc(tr('History of cell {0}', cell.addr || '')) : tr('Recent changes')}</h3>
    ${es.length ? `<ul class="shhlist">${es.map(x => `<li><div class="shhwho">${x.agent ? ic('bot', 's') : av(x.user_id, x.user_name, 'avatar shkav')}<b>${esc(x.user_name || '')}</b><span class="muted">${esc(relTime(x.at))}</span>${!cell && x.addr ? `<button type="button" class="linkbtn" data-shh-go="${x.row_id}:${x.col_id}">${esc(x.addr)}${x.col_title ? ' · ' + esc(x.col_title) : ''}</button>` : !cell ? `<span class="muted">${tr('Cell removed')}</span>` : ''}</div>
      <div class="shhchg">${val(x.old)}<span class="shharr" aria-label="${esc(tr('becomes'))}">→</span>${val(x.new)}</div></li>`).join('')}</ul>` : `<p class="muted mhint">${tr('No changes recorded yet.')}</p>`}
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('shhmd');
  md.addEventListener('click', e => {
    const b = /** @type {any} */ (e.target).closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.shhGo) { const [r, c] = b.dataset.shhGo.split(':').map(Number); md.remove(); if (SHV.sh?._col.has(c) && SHV.sh._rowNo.has(r)) { shvSelect(r, c); $('#shv-scroll')?.focus({preventScroll: true}); } }
  });
}
document.addEventListener('click', e => {
  const b = /** @type {any} */ (e.target).closest?.('[data-shh]'); if (!b || !SHV.sh) return;
  e.preventDefault();
  if (b.dataset.shh === 'cell') { const c = SHV.cur && shvCell(SHV.cur.r, SHV.cur.c); if (c) shh_open(c); } else shh_open(null);
});
(SHV_HOOKS.side = SHV_HOOKS.side || []).push(sh => {  // the panel: the cell's history and the table's recent changes
  const c = SHV.cur && sh._col.has(SHV.cur.c) && sh._rowNo.has(SHV.cur.r) ? shvCell(SHV.cur.r, SHV.cur.c, sh) : null;
  return `<section class="shvsec shhsec">${c ? `<button type="button" class="btn sm" data-shh="cell">${ic('clock', 's')}${tr('History of the cell')}</button>` : ''}<button type="button" class="btn sm" data-shh="sheet">${ic('undo', 's')}${tr('Recent changes')}</button></section>`;
});
SHV_HOOKS.menu.push(sh => [{label: tr('Recent changes'), icon: 'clock', fn: () => shh_open(null)}, {label: tr('Print / PDF…'), icon: 'printer', fn: shk_print},
  ...(sh.can_write && (sh.freeze_rows || sh.freeze_cols) ? [{label: tr('Release the kept rows and columns'), icon: 'pin', fn: () => shk_fixSet({rows: 0, cols: 0}, tr('Rows and columns released'))}] : [])]);
window.addEventListener('dblclick', e => { if (/** @type {any} */ (e.target).closest?.('#shv-scroll [data-shkbox]')) e.stopPropagation(); }, true);  // two clicks on a box = two ticks, no third
