/* Kalmido web client: the selection mode of a list of records (2.47.3, #1731 / #1733 / #1734), shared by the contacts
   (contacts.js bk_*) and the clients (clientpage.js): the floating bar, a long press on the phone, Shift- / Cmd-click.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// the floating bar (like the tasks' selection bar): the count, then the buttons [key, icon, label, class?] with
// data-<attr>="key" (disabled while nothing is ticked, except "all"), then the close button (Esc).
// 2.428.0 A (#3581): every selection uses it (documents, file store, knowledge, users, trip receipts): class mselbar = its look
function ms_barHtml(id, attr, n, hint, btns) {
  // 2.66.0 A (#1835): min = the ticks a button needs (Merge: 2)
  const btn = ([k, i, lab, cls = '', min = 1]) => `<button type="button" class="mbb ${cls}" data-${attr}="${k}" title="${esc(lab)}" aria-label="${esc(lab)}" ${n >= min || k === 'all' ? '' : 'disabled'}>${ic(i, 's')}<span class="mbl">${esc(lab)}</span></button>`;
  return `<div id="${id}" class="mselbar" role="toolbar" aria-label="${esc(tr('Selection'))}"><span class="mcount" role="status">${n ? trh('{0} selected', n) : hint}</span>
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
// 2.627.0 (#4961): a drag's hold (drag.js) took the press: the long press of st opens nothing now, and the browser's menu
// event of the same press (Android) is swallowed as after a long press; the drag opens the menu itself when let go unmoved
const ms_lpTake = st => { if (!st) return; clearTimeout(st.lp?.t); st.lp = null; st.done = Date.now(); };
// 2.452.0 (#3836): a long press opens the menu of a row (open(row) calls menu()); the click that ends the press does nothing,
// a click of the menu on a button of the row (detail 0) goes through
function ms_rowMenu(sel, open) {
  const st = ms_longPress(sel, () => false, open);
  window.addEventListener('click', e => { if (e.detail && ms_lpRecent(st) && /** @type {any} */ (e.target).closest?.(sel)) { e.preventDefault(); e.stopPropagation(); } }, true);
  return st;  // 2.627.0 (#4962): ms_lpTake
}
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
      ${df.length ? `<p class="muted">${tr('Select which value stays where the entries differ.')}</p>` : ''}
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
  const back1 = () => { st.step = 1; draw1(); };  // 2.962.0 (#5232): the overview's Back = the choices again
  md.addEventListener('change', e => {
    const n = e.target.name || '';
    if (n === 'mg-t') { st.target = e.target.value; st.pick = {}; draw1(); }
    else if (n.startsWith('mg-f-')) st.pick[n.slice(5)] = e.target.value;
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    const err = () => $('.aerr', md);
    if (b.dataset.m === 'close') { close(); return; }
    if (b.dataset.m === 'back') { f8d_backBtn(md, back1); return; }  // 2.962.0 (#5232): = Android Back
    b.disabled = true;
    try {
      const pick = Object.fromEntries(diff().map(f => [f.k, Number(st.pick[f.k])]));
      if (b.dataset.m === 'next') { const r = await o.preview(Number(st.target), pick); st.step = 2; draw2(r); f8d_step(md, back1); }
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
// 2.428.0 A (#3581): pick(row) given = a long press selects the row (like everywhere), the right click keeps the menu
// 2.607.0 (#4612): a long press opens the menu like the right click (open puts "Select" on top, cm_selHead); pick(row) only
// while choosing runs: it ticks the row and returns true (a tap ticks as well, #3581)
function cm_bind(sel, open, pick, keep) {  // 2.571.0 (#4608): keep(e, row) true = the browser's menu stays for this right click
  const lp = r => (pick && pick(r)) || open(r);
  const st = ms_longPress(sel, () => false, lp);
  document.addEventListener('contextmenu', e => {
    const r = e.target.closest?.(sel); if (!r || e.target.closest('input, textarea, [contenteditable="true"]') || keep?.(e, r)) return;
    if (st.lp) { clearTimeout(st.lp.t); st.lp = null; st.done = Date.now(); if (lp(r)) { e.preventDefault(); navigator.vibrate?.(10); } return; }  // Android: its menu event comes before the timer - one menu, not two
    if (ms_lpRecent(st)) { e.preventDefault(); return; }
    if (open(r)) e.preventDefault();
  });
  window.addEventListener('click', e => { if (ms_lpRecent(st) && e.target.closest?.(sel)) { e.preventDefault(); e.stopPropagation(); } }, true);  // the click ending the press does not open the row
  return st;
}
// 2.607.0 (#4612): the top of a row menu opened by a long press / right click where rows can be chosen (like tasks, o.select):
// the name as head, "Select" (starts choosing with this row), a line. pick() missing = no "Select" (head and line only)
function cm_selHead(name, pick) {
  const n = String(name || '').trim(), head = n ? [{label: n.length > 60 ? n.slice(0, 59) + '…' : n, cls: 'mhead', dis: true, fn: () => {}}] : [];
  return [...head, ...(pick ? [{label: tr('Select'), icon: 'select', act: 'cm-select', fn: pick}] : []), '-'];
}
// 2.571.0 (#4608): a long press (phone) / a right click (computer) opens the row's own "…" menu everywhere the row has one (like tasks
// since 2.25.0); where a long press drags or selects (calendar grid, timeline, roadmap, tiles, tables, file store, knowledge,
// contacts, clients, documents #3581) nothing changes. open(row) finds the row's menu button and returns true when a menu came.
// A right click on a link inside the row or with selected text in it keeps the browser's menu (copy, open link); a row in edit
// mode (textarea) has no row menu. Rows: team chat messages (also in a thread), comments of a task, agent chat messages, the
// section heads of a list, the calendar names of the timeline.
const lm_btn = (r, sel) => r.querySelector('textarea, input') ? null : r.querySelector(sel);
const lm_keep = (e, r) => { const a = e.target.closest?.('a[href]'); if (a && a !== r) return true; const s = getSelection?.(); return !!s && !s.isCollapsed && r.contains(s.anchorNode); };
const lm_open = (sel, fn) => r => { const b = lm_btn(r, sel); if (!b) return false; return fn(b, r) !== false; };  // the menu sits at the row (its "…" button can be hidden)
// 2.695.0 (#4619): a long press (phone) / a right click (computer) on a row (sel) opens what its "…" button (btn) opens: the
// click on that button, which the click guard of the press lets through for that one click (as #4616). Every row's "…" button
// carries data-rowmenu="<a word of sel>": tests/p2695_a_rowmenu_coverage_test.py finds a "…" without it or without a binding.
// keep: as cm_bind (default lm_keep: a link or a selection inside the row keeps the browser's menu)
function lm_btnMenu(sel, btn, keep = lm_keep) {
  const st = cm_bind(sel, r => { const b = r.querySelector(btn); if (!b) return false; const d = st.done; st.done = 0; b.click(); st.done = d; return true; }, null, keep);
  return st;
}
const lm_selKeep = (e, r) => { const s = getSelection?.(); return !!s && !s.isCollapsed && r.contains(s.anchorNode); };  // a row that is a link as a whole
cm_bind('#tc-msgs .cmsg, .tthview .cmsg', lm_open('[data-act="tc-msg-menu"]', (b, r) => tcMsgMenu(r, +b.dataset.mid)), null, lm_keep);
cm_bind('#detail .cm:not(.cedit)', lm_open('[data-act="cm-copy"]', (b, r) => cmCopyMenu(b, r)), null, lm_keep);
cm_bind('#chat-msgs .cmsg', lm_open('[data-act="chat-msg-menu"]', (b, r) => { const m = (S.chat?.msgs || []).find(x => x.id === +b.dataset.mid); if (!m) return false; acMsgMenu(r, m); }), null, lm_keep);
// 2.725.0 (#5177): the long press of a section head is taken by dnd.js's hold (drag / menu on release, ms_lpTake): one menu, not two
const LM_SECHEAD = cm_bind('#view .ghead[data-section]', lm_open('[data-act="section-menu"]', (b, r) => sectionMenu(r, +b.dataset.id)), null, lm_keep);
cm_bind('#view .tl-cal .tl-name', lm_open('[data-act="cvx-tlmenu"]', (b, r) => cvxTlMenu(r, b.dataset.key, b.dataset.name)), null, lm_keep);
// 2.963.0 (#5234): a selection mode is one step of the page on a touch screen (backclose.js f8d_step on #view): Back ends the
// selection and stays on the page (it went one page back before). Each row: [key, on() = the selection is shown, end() = what
// Esc does there]. ms_stepSync runs after every change of the page (a mutation, the tasks' bar): a selection that starts
// gets its step, one ended another way (the bar's X, Esc, an action) loses it again (its history entry goes: no dead Back)
const MS_STEPS = /** @type {Array<[string, () => any, () => void]>} */ ([
  ['tasks', () => S.multiMode || S.multi.size, () => { S.multi.clear(); S.multiMode = false; render(); }],  // events.js ev_escGlobal
  ['contacts', () => typeof CT === 'object' && CT.pick && S.route.mod === 'contacts', () => bk_end()],
  ['clients', () => typeof MSC === 'object' && MSC.pick && S.route.mod === 'clients', () => ms_clEnd()],
  // the documents and the file store share one selection (ablage.js AB, 2.768.0 #4888)
  ['ablage', () => typeof AB === 'object' && AB.selOn && $('#view .abview, #view .dc-view'), () => { ab_selEnd(); ab_selDraw(); }],
  ['wiki', () => typeof WK === 'object' && WK.selOn && S.route.mod === 'wiki', () => { wk_selEnd(); renderView(); }],
  ['travel', () => typeof RK === 'object' && RK.sel.size && $('#view #rk-sbar'), () => { RK.sel.clear(); ofcDraw(); }],  // lazy-ok: only while the receipts of office_travel.js are shown
]);
function ms_stepSync() {
  const v = $('#view'); if (!v || typeof f8d_step !== 'function') return;
  for (const [key, on, end] of MS_STEPS) {
    const i = (v._stk || []).findIndex(f => f._ms === key);
    if (on() && i < 0) { const f = () => end(); f._ms = key; f8d_step(v, f); }
    else if (!on() && i >= 0) { v._stk.splice(i, 1); f8d_queue(); }
  }
}
if (isTouch()) {
  new MutationObserver(ms_stepSync).observe(document.body, {childList: true, subtree: true});
  new MutationObserver(ms_stepSync).observe(document.body, {attributes: true, attributeFilter: ['class']});  // the tasks' bar (sidebar.js renderMultiBar: body.msel)
}
