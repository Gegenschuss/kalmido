/* Kalmido web client: the selection mode of a list of records (2.47.3, #1731 / #1733 / #1734), shared by the contacts
   (contacts.js bk_*) and the clients (clientpage.js): the floating bar, a long press on the phone, Shift- / Cmd-click.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// the floating bar (like the tasks' selection bar): the count, then the buttons [key, icon, label, class?] with
// data-<attr>="key" (disabled while nothing is ticked, except "all"), then the close button (Esc)
function ms_barHtml(id, attr, n, hint, btns) {
  // 2.66.0 A (#1835): min = the ticks a button needs (Merge: 2)
  const btn = ([k, i, lab, cls = '', min = 1]) => `<button type="button" class="mbb ${cls}" data-${attr}="${k}" title="${esc(lab)}" aria-label="${esc(lab)}" ${n >= min || k === 'all' ? '' : 'disabled'}>${ic(i, 's')}<span class="mbl">${esc(lab)}</span></button>`;
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
// 2.66.0 (#1835): merging several records into one (contacts.js, clientpage.js). Step 1: which record stays (target) and,
// per field whose values differ, which value it keeps; lists (phones, e-mails, addresses, ...) are joined, not replaced.
// Step 2: the overview the server computes (preview(target, pick) -> {lines: [text]}: what moves where), the note that the
// others are gone afterwards (Undo in the history), then run(target, pick) -> true closes. o = {title, recs: [{id, label,
// sub?}], fields: [{k, label, vals: {id: text}}], lists: [{k, label, vals: {id: [text]}}], preview, run}
function ms_merge(o) {
  const ids = o.recs.map(r => String(r.id));
  const st = {target: ids[0], pick: {}, step: 1};
  const md = modal('<div class="mgbody"></div>');
  md.classList.add('msdlg', 'mgdlg');
  let close;  // 2.66.0 A (#1835): the form guard starts after the first drawing (else Cancel always asked to discard)
  const body = $('.mgbody', md);
  const diff = () => o.fields.filter(f => new Set(ids.map(i => (f.vals[i] ?? '').trim()).filter(Boolean)).size > 1);
  const dflt = f => (f.vals[st.target] ?? '').trim() ? st.target : (ids.find(i => (f.vals[i] ?? '').trim()) || st.target);
  const radio = (name, val, on, label, sub = '') => `<label class="mgopt"><input type="radio" name="${name}" value="${esc(val)}" ${on ? 'checked' : ''}><span>${esc(label)}${sub ? `<small class="muted">${esc(sub)}</small>` : ''}</span></label>`;
  const joined = l => [...new Set(ids.flatMap(i => l.vals[i] || []).map(x => String(x).trim()).filter(Boolean))];
  const draw1 = () => {
    const df = diff();
    for (const f of df) if (!ids.includes(st.pick[f.k])) st.pick[f.k] = dflt(f);
    const same = o.fields.filter(f => !df.includes(f) && ids.some(i => (f.vals[i] ?? '').trim())).map(f => f.label);
    const lists = (o.lists || []).map(l => [l, joined(l)]).filter(([, v]) => v.length);
    body.innerHTML = `<h3>${esc(o.title)}</h3>
      <fieldset class="mgset"><legend>${tr('Keep')}</legend>${o.recs.map(r => radio('mg-t', r.id, String(r.id) === st.target, r.label, r.sub)).join('')}</fieldset>
      ${df.length ? `<p class="muted">${tr('Choose which value stays where the entries differ.')}</p>` : ''}
      ${df.map(f => `<fieldset class="mgset"><legend>${esc(f.label)}</legend>${ids.filter(i => (f.vals[i] ?? '').trim()).map(i => radio('mg-f-' + f.k, i, st.pick[f.k] === i, f.vals[i])).join('')}</fieldset>`).join('')}
      ${lists.length ? `<div class="mgjoin"><b>${tr('Joined')}</b>${lists.map(([l, v]) => `<div><span class="muted">${esc(l.label)}:</span> ${esc(v.slice(0, 6).join(', '))}${v.length > 6 ? ' …' : ''}</div>`).join('')}</div>` : ''}
      ${same.length ? `<p class="muted mgsame">${esc(tr('Same in all: {0}', same.join(', ')))}</p>` : ''}
      <div class="aerr" role="alert"></div>
      <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="next">${tr('Next')}</button></div>`;
  };
  const draw2 = r => {
    const t = o.recs.find(x => String(x.id) === st.target);
    body.innerHTML = `<h3>${esc(o.title)}</h3><p>${esc(tr('Everything moves to “{0}”:', t.label))}</p>
      <ul class="mglines">${(r.lines || []).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
      <p class="mgwarn">${esc(tr('The other entries are gone afterwards ({0}). You can undo the merge in the history for 30 days.', o.recs.filter(x => String(x.id) !== st.target).map(x => x.label).join(', ')))}</p>
      <div class="aerr" role="alert"></div>
      <div class="foot"><button class="btn" data-m="back">${tr('Back')}</button><span class="spacer"></span><button class="btn pri" data-m="run">${tr('Merge')}</button></div>`;
  };
  md.addEventListener('change', e => {
    const n = e.target.name || '';
    if (n === 'mg-t') { st.target = e.target.value; st.pick = {}; draw1(); }
    else if (n.startsWith('mg-f-')) st.pick[n.slice(5)] = e.target.value;
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    const err = () => $('.aerr', md);
    if (b.dataset.m === 'close') { close(); return; }
    if (b.dataset.m === 'back') { st.step = 1; draw1(); return; }
    b.disabled = true;
    try {
      const pick = Object.fromEntries(diff().map(f => [f.k, Number(st.pick[f.k])]));
      if (b.dataset.m === 'next') { const r = await o.preview(Number(st.target), pick); st.step = 2; draw2(r); }
      else if (b.dataset.m === 'run' && await o.run(Number(st.target), pick)) { md.remove(); return; }
    } catch (x) { if (err()) err().textContent = x.message || ''; }
    b.disabled = false;
  });
  draw1();
  close = fgModal(md);
  return md;
}
// 2.210 B (#2757): the row's own "…" menu by a right click (computer; Shift+F10 / the menu key on a focused row too) or a
// long press (phone) on a row matching sel: one menu, two ways, no own right-click list. open(row) -> true when a menu
// came, otherwise the browser's menu stays. Shared by the file store and the knowledge folders (later the office documents).
function cm_bind(sel, open) {
  const st = ms_longPress(sel, () => false, r => open(r));
  document.addEventListener('contextmenu', e => {
    const r = e.target.closest?.(sel); if (!r || e.target.closest('input, textarea, [contenteditable="true"]')) return;
    if (st.lp) { clearTimeout(st.lp.t); st.lp = null; st.done = Date.now(); if (open(r)) { e.preventDefault(); navigator.vibrate?.(10); } return; }  // Android: its menu event comes before the timer - one menu, not two
    if (ms_lpRecent(st)) { e.preventDefault(); return; }
    if (open(r)) e.preventDefault();
  });
  window.addEventListener('click', e => { if (ms_lpRecent(st) && e.target.closest?.(sel)) { e.preventDefault(); e.stopPropagation(); } }, true);  // the click ending the press does not open the row
  return st;
}
