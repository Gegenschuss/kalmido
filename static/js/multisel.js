/* Kalmido web client: the selection mode of a list of records (2.47.3, #1731 / #1733 / #1734), shared by the contacts
   (contacts.js bk_*) and the clients (clientpage.js): the floating bar, a long press on the phone, Shift- / Cmd-click.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// the floating bar (like the tasks' selection bar): the count, then the buttons [key, icon, label, class?] with
// data-<attr>="key" (disabled while nothing is ticked, except "all"), then the close button (Esc)
function ms_barHtml(id, attr, n, hint, btns) {
  const btn = ([k, i, lab, cls = '']) => `<button type="button" class="mbb ${cls}" data-${attr}="${k}" title="${esc(lab)}" aria-label="${esc(lab)}" ${n || k === 'all' ? '' : 'disabled'}>${ic(i, 's')}<span class="mbl">${esc(lab)}</span></button>`;
  return `<div id="${id}" role="toolbar" aria-label="${esc(tr('Selection'))}"><span class="mcount" role="status">${n ? tr('{0} selected', n) : hint}</span>
    ${btns.map(btn).join('')}
    <button type="button" class="iconbtn mbx" data-${attr}="close" title="${esc(tr('Clear selection') + ' (Esc)')}" aria-label="${esc(tr('Clear selection'))}">${ic('x')}</button></div>`;
}
// the phone: a long press on a row (selector sel) starts the selection with it, unless active() (the mode is on already);
// st.done = the time it fired: the click that ends the press does nothing (ms_lpRecent)
function ms_longPress(sel, active, start) {
  const st = {lp: null, done: 0};
  document.addEventListener('pointerdown', e => {
    const r = e.pointerType === 'touch' && !active() && e.target.closest?.(sel); if (!r) return;
    clearTimeout(st.lp?.t);
    st.lp = {x: e.clientX, y: e.clientY, t: setTimeout(() => { st.lp = null; st.done = Date.now(); navigator.vibrate?.(10); start(r); }, 500)};
  });
  document.addEventListener('pointermove', e => { if (st.lp && Math.hypot(e.clientX - st.lp.x, e.clientY - st.lp.y) > 10) { clearTimeout(st.lp.t); st.lp = null; } });
  for (const ev of ['pointerup', 'pointercancel']) document.addEventListener(ev, () => { if (st.lp) { clearTimeout(st.lp.t); st.lp = null; } });
  document.addEventListener('contextmenu', e => { if (e.target.closest?.(sel) && (st.lp || ms_lpRecent(st))) e.preventDefault(); });
  return st;
}
const ms_lpRecent = st => Date.now() - st.done < 600;
// Shift-click: the ids between the last ticked one and id in the shown order (both included); id alone without an anchor
function ms_range(order, from, id) {
  const a = order.indexOf(from), b = order.indexOf(id);
  return a < 0 || b < 0 ? [id] : order.slice(Math.min(a, b), Math.max(a, b) + 1);
}
// a click with Shift / Cmd / Ctrl on a row: it starts the selection (desktop) or extends it
const ms_modClick = e => e.shiftKey || e.metaKey || e.ctrlKey;
// "Edit" of several records: one sheet, every field changes only when its box is ticked (typing ticks it) or, for the
// fields with fill: true (add to groups, append a note), when something is filled in. rows: [{k, label, input (HTML
// with data-msf="k"), fill?, hint?}]; save(values {k: string}) -> true closes the sheet (an error shows in it)
function ms_sheet(title, sub, rows, save) {
  const row = r => `<div class="row msrow">${r.fill ? `<label for="ms-f-${r.k}">${esc(r.label)}</label>` : `<label class="chkl msuse"><input type="checkbox" data-msuse="${r.k}"> ${esc(r.label)}</label>`}<div class="msin">${r.input}${r.hint ? `<small class="muted">${esc(r.hint)}</small>` : ''}</div></div>`;
  const md = modal(`<h3>${esc(title)}</h3><p class="muted">${esc(sub)}</p>${rows.map(row).join('')}<div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Apply')}</button></div>`);
  md.classList.add('msdlg');
  const close = fgModal(md);
  const tick = e => { const k = e.target.dataset?.msf, cb = k && md.querySelector(`[data-msuse="${k}"]`); if (cb) cb.checked = true; };
  md.addEventListener('input', tick); md.addEventListener('change', tick);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    const vals = {};
    for (const r of rows) {
      const el = md.querySelector(`[data-msf="${r.k}"]`); if (!el) continue;
      if (r.fill ? el.value.trim() : md.querySelector(`[data-msuse="${r.k}"]`)?.checked) vals[r.k] = el.value;
    }
    const err = $('.aerr', md);
    if (!Object.keys(vals).length) { err.textContent = tr('Nothing to change'); return; }
    b.disabled = true;
    try { if (await save(vals)) md.remove(); } catch (x) { err.textContent = x.message || ''; }
    b.disabled = false;
  });
  setTimeout(() => { if (!isTouch()) md.querySelector('[data-msf]')?.focus(); }, 50);
  return md;
}
// a step of the history (undo / redo with the toast and Ctrl+Z): fn(dir) does the request
const ms_hist = (msg, label, undo, redo) => histToast(msg, histAdd({label, undo: async () => { await undo(); return {}; }, redo: async () => { await redo(); return {}; }}));
