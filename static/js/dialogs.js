/* Kalmido web client: Modals: the app's own dialogs, the list dialog and the share dialog.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ modals
function modal(html) {
  const m = document.createElement('div');
  m.className = 'modal';
  m.innerHTML = `<div class="card">${html}</div>`;
  an_flush(); m.remove = () => an_remove(m);  // 2.46.1 (#1558): phones: the dialog folds away before it leaves the page
  m.addEventListener('mousedown', e => { if (e.target === m) modalClose(m); });
  document.body.appendChild(m);
  kb_push('dialog', m);  // 2.630.0 (#4510): on the key registry's scope stack (keys.js): Esc closes the innermost open thing
  document.body.classList.add('modal-open');  // 2.28.0 (#976): the grips step aside while a dialog is open
  onRemove(m, () => { kb_pop(m); /* 2.630.0 (#4510) */ const dc = m.ownerDocument; if (dc && dc.body && !dc.querySelector('.modal')) dc.body.classList.remove('modal-open'); });
  vvSync();
  modalA11y(m);
  queueMicrotask(() => dlg_resizable(m));  // after the caller added its classes (they name the dialog kind)
  return m;
}
// 2.138.0 E (#2234): desktop: a grip at the bottom right resizes the dialog (pointer events: mouse + pen); the size is kept per
// dialog kind (its own classes; none = not kept); double click on the grip = back to the default size. Phones: no grip.
const DLG_SKIP = /^(modal|cdlg|authscreen|shopmode|smodal|lmodal|fgrqdlg|hidden|open|closing)$/;
const dlg_key = m => { const c = [...m.classList].filter(x => !DLG_SKIP.test(x)).sort().join('.'); return c ? 'kalmido.dlgsize.' + c : ''; };
const dlg_wide = () => { try { return matchMedia('(min-width: 768px) and (pointer: fine)').matches; } catch { return false; } };  // 2.364.0 B (#3040): was 900 px
// 2.161.2 (#2615): only a dialog whose content can grow gets the grip: a text field, an editor, a preview, a scrolling list / table,
// or content that already overflows; a short one (confirm, password, one input) has none and forgets a size kept earlier
const DLG_GROWS = 'textarea,[contenteditable="true"],[contenteditable=""],.editor,iframe,img,embed,object,canvas,table,.tbl,.list,.scroll,[class*="editor"]';
function dlg_grows(card) {
  if ($$(DLG_GROWS, card).some(x => !x.closest('.foot') && !x.classList.contains('dlggrip'))) return true;
  return [card, ...$$('*', card)].some(x => x.scrollHeight > x.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(x).overflowY));
}
function dlg_resizable(m, again) {
  const card = m.querySelector(':scope > .card');
  if (card && m.isConnected && dlg_wide() && m.dataset.dlgsz) { dlg_sizer(m, card, m.dataset.dlgsz); return; }  // 2.805.0 (#5357)
  if (!card || !m.isConnected || !dlg_wide() || m.classList.contains('authscreen') || m.classList.contains('cdlg') || m.classList.contains('shopmode') || m.classList.contains('smodal') || m.classList.contains('lmodal')) return;
  if (!dlg_grows(card)) {
    if (!again) { const k = dlg_key(m); if (k) try { localStorage.removeItem(k); } catch { /* private mode */ } setTimeout(() => dlg_resizable(m, true), 600); }  // content that loads after opening
    return;
  }
  const key = dlg_key(m);
  const mk = () => { const g = document.createElement('div'); g.className = 'dlggrip'; g.setAttribute('role', 'separator'); g.setAttribute('aria-label', tr('Drag to resize · double-click: default size')); g.title = tr('Drag to resize · double-click: default size'); return g; };
  card.style.transition = 'none';  // a size change must not glide (a drag follows the pointer, a reset is at once)
  let grip = mk(); card.appendChild(grip);
  const base = card.getBoundingClientRect();  // the default size = the minimum
  const lim = () => ({w: window.innerWidth - 32, h: (window.visualViewport?.height || window.innerHeight) - 32});
  const apply = (w, h) => {
    const L = lim(); w = Math.round(Math.max(base.width, Math.min(w, L.w))); h = Math.round(Math.max(base.height, Math.min(h, L.h)));
    card.style.width = w + 'px'; card.style.height = h + 'px'; card.classList.add('dlg-sized'); return [w, h];
  };
  const reset = () => { card.style.width = card.style.height = ''; card.classList.remove('dlg-sized'); if (key) try { localStorage.removeItem(key); } catch { /* private mode */ } };
  if (key) try { const v = JSON.parse(localStorage.getItem(key) || 'null'); if (v && v.w > 0 && v.h > 0) apply(v.w, v.h); } catch { /* bad value */ }
  card.addEventListener('pointerdown', e => {
    if (!e.target.closest?.('.dlggrip') || e.button) return;
    e.preventDefault();
    const x0 = e.clientX, y0 = e.clientY, r0 = card.getBoundingClientRect(), pid = e.pointerId;
    try { e.target.setPointerCapture(pid); } catch { /* gone */ }
    // the card is centred: its edges move half the growth each way, so the grip follows the pointer at twice the speed
    const mv = ev => { if (ev.pointerId === pid) apply(r0.width + (ev.clientX - x0) * 2, r0.height + (ev.clientY - y0) * 2); };
    const up = ev => {
      if (ev.pointerId !== pid) return;
      document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); document.removeEventListener('pointercancel', up);
      const r = card.getBoundingClientRect();
      if (key && card.classList.contains('dlg-sized')) try { localStorage.setItem(key, JSON.stringify({w: Math.round(r.width), h: Math.round(r.height)})); } catch { /* private mode */ }
    };
    document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up); document.addEventListener('pointercancel', up);
  });
  card.addEventListener('dblclick', e => { if (e.target.closest?.('.dlggrip')) reset(); });
  // a dialog that redraws its card's content keeps its grip
  new MutationObserver(() => { if (!grip.isConnected) { grip = mk(); card.appendChild(grip); } }).observe(card, {childList: true});
}
// 2.805.0 (#5357): the full grip, opt-in per dialog: the caller sets data-dlgsz="<name>" on the dialog right after modal()
// (Settings, Edit contact, a mail of the hub, Video review, Set up an agent). Two grips lie on the card's edge: the right edge
// (width) and the bottom right corner (width and height); they are children of the backdrop, placed over the card from its
// box, so they stay put when the card's content scrolls. The default size when it opens is the minimum, the window minus
// 4rem the maximum; the size is kept per dialog and device (localStorage kalmido.dlgsize.<name>, h 0 = default height; a name
// is never a class name, so the automatic grip's keys of other dialogs with the same class never share or clear it) and
// applied before the first paint (no jump); double click or Enter / Space on a grip = default size; arrow keys resize (the
// edge: left / right, the corner: all four), Home / End = smallest / largest. Mouse and pen only: phones and touch keep the
// sheet without a grip. The card is centred, so both of its sides move: a drag counts twice.
const DLGSZ_STEP = 24;
function dlg_sizer(m, card, name) {
  if (card._dlgsz) return;
  const key = 'kalmido.dlgsize.' + name, lbl = tr('Drag to resize · double-click: default size');
  const base = card.getBoundingClientRect();  // the default size = the minimum
  let w = 0, h = 0;  // 0 = default
  const lim = () => ({w: (document.documentElement.clientWidth || innerWidth) - 64, h: (window.visualViewport?.height || innerHeight) - 32});
  const mk = (cls, or) => {
    const g = document.createElement('div'); g.className = 'dlgsz ' + cls; g.tabIndex = 0;
    g.setAttribute('role', 'separator'); g.setAttribute('aria-orientation', or); g.setAttribute('aria-label', lbl); g.title = lbl;
    g.setAttribute('aria-valuemin', '0'); g.setAttribute('aria-valuemax', '100'); g.setAttribute('aria-valuenow', '0');  // a focusable separator needs a value (axe aria-required-attr)
    m.appendChild(g); return g;
  };
  const edge = mk('dlgsz-e', 'vertical'), corner = mk('dlgsz-c', 'horizontal');
  const place = () => {
    if (!card.isConnected) return;
    const r = card.getBoundingClientRect();
    edge.style.cssText = `left:${r.right - 4}px;top:${r.top + 8}px;height:${Math.max(0, r.height - 28)}px`;
    corner.style.cssText = `left:${r.right - 16}px;top:${r.bottom - 16}px`;
  };
  card._dlgPlace = place;
  const apply = (nw, nh) => {
    const L = lim();
    w = nw > 0 ? Math.round(Math.max(base.width, Math.min(nw, L.w))) : 0;
    h = nh > 0 ? Math.round(Math.max(base.height, Math.min(nh, L.h))) : 0;
    if (w <= base.width + .5) w = 0;
    if (h <= base.height + .5) h = 0;
    card.style.width = w ? w + 'px' : ''; card.style.maxWidth = w ? 'none' : '';
    card.style.height = h ? h + 'px' : ''; card.style.maxHeight = h ? 'none' : '';
    card.classList.toggle('dlgsz-w', !!w); card.classList.toggle('dlgsz-h', !!h);
    const pct = (v, b0, l) => v && l > b0 ? String(Math.round(Math.min(100, (v - b0) * 100 / (l - b0)))) : '0';
    edge.setAttribute('aria-valuenow', pct(w, base.width, L.w)); corner.setAttribute('aria-valuenow', pct(w, base.width, L.w));
    if (card._dw && typeof dw_set === 'function') dw_set(card, card._dw.x, card._dw.y);  // a moved dialog stays inside the window
    place();
  };
  const save = () => { try { if (w || h) localStorage.setItem(key, JSON.stringify({w, h})); else localStorage.removeItem(key); } catch { /* private mode */ } };
  const reset = () => { apply(0, 0); save(); };
  card._dlgsz = {apply, reset, get: () => ({w, h})};
  card.style.transition = 'none';  // a size change must not glide
  try { const v = JSON.parse(localStorage.getItem(key) || 'null'); if (v && (v.w > 0 || v.h > 0)) apply(v.w || 0, v.h || 0); } catch { /* bad value */ }
  place();
  for (const g of [edge, corner]) {
    const both = g === corner;
    g.addEventListener('pointerdown', e => {
      if (e.button || e.pointerType === 'touch') return;
      e.preventDefault(); e.stopPropagation();
      const x0 = e.clientX, y0 = e.clientY, r0 = card.getBoundingClientRect(), pid = e.pointerId, h0 = both ? r0.height : h;
      try { g.setPointerCapture(pid); } catch { /* gone */ }
      g.classList.add('on'); card.classList.add('dlgsz-drag');
      const put = rafThrottle((x, y) => apply(r0.width + (x - x0) * 2, both ? h0 + (y - y0) * 2 : h));
      const mv = ev => { if (ev.pointerId === pid) put(ev.clientX, ev.clientY); };
      const up = ev => {
        if (ev.pointerId !== pid) return;
        put.flush(); g.classList.remove('on'); card.classList.remove('dlgsz-drag');
        document.removeEventListener('pointermove', mv); document.removeEventListener('pointerup', up); document.removeEventListener('pointercancel', up);
        try { g.releasePointerCapture(pid); } catch { /* released */ }
        save();
      };
      document.addEventListener('pointermove', mv); document.addEventListener('pointerup', up); document.addEventListener('pointercancel', up);
    });
    g.addEventListener('dblclick', e => { e.preventDefault(); reset(); });
    g.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); reset(); return; }
      const r = card.getBoundingClientRect(), L = lim();
      const dw = {ArrowLeft: -DLGSZ_STEP, ArrowRight: DLGSZ_STEP}[e.key], dh = both ? {ArrowUp: -DLGSZ_STEP, ArrowDown: DLGSZ_STEP}[e.key] : undefined;
      if (e.key === 'Home') apply(0, both ? 0 : h);
      else if (e.key === 'End') apply(L.w, both ? L.h : h);
      else if (dw !== undefined) apply(r.width + dw, h);
      else if (dh !== undefined) apply(w || r.width, r.height + dh);
      else return;
      e.preventDefault(); e.stopPropagation(); save();
    });
  }
  // the card moves (opening animation, the dialog dragged by its header, its content changes its height): the grips follow
  card.addEventListener('animationend', place);
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => place()).observe(card);
}
// a smaller window keeps every sized dialog inside it (the size applied again, clamped) and the grips on its edge
// 2.805 (#5357): debounce of core.js instead of a clearTimeout / setTimeout pair (perf budget)
window.addEventListener('resize', debounce(() => { for (const c of document.querySelectorAll('.modal > .card')) if (c._dlgsz) { const s = c._dlgsz.get(); c._dlgsz.apply(s.w, s.h); } }, 60));
// 2.38.0 (#1170): touch: a button in a dialog's foot (Save, Cancel ...) does not take the focus from the field being typed in, like
// Send in the chat (#478): on iOS the first tap otherwise only closed the keyboard, the dialog moved and the tap missed Save
for (const ev of ['pointerdown', 'mousedown']) document.addEventListener(ev, e => {
  const b = e.target.closest?.('.modal .foot button'); if (!b || !isTouch()) return;
  const a = document.activeElement;
  if (a && b.closest('.modal').contains(a) && (/^(INPUT|TEXTAREA)$/.test(a.tagName) || a.isContentEditable)) e.preventDefault();
});
// 2.16.0 (#473): every dialog is a modal dialog for screen readers (role, name from its heading), keeps Tab inside, gets the
// focus (its own field if it focuses one, else the dialog itself, so a phone keyboard does not pop up) and gives it back to
// where it came from when it closes (Esc, backdrop, a button, code)
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type="hidden"]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"]),[contenteditable="true"]';
const focusables = root => $$(FOCUSABLE, root).filter(x => x.offsetParent !== null || x === document.activeElement || !x.getClientRects);
function modalA11y(m) {
  const card = m.querySelector('.card');
  if (!m.hasAttribute('role')) m.setAttribute('role', 'dialog');
  m.setAttribute('aria-modal', 'true');
  const h = card && card.querySelector('h1,h2,h3,h4');
  if (h && !m.hasAttribute('aria-labelledby')) { if (!h.id) h.id = 'mh-' + Math.random().toString(36).slice(2, 8); m.setAttribute('aria-labelledby', h.id); }
  const prev = document.activeElement;
  // 2.46.2 (#1659 #1718): a redraw while the dialog is open (an optimistic save draws the header again) can replace the opener;
  // the focus then goes to its new copy (same signature and position as in keepFocus)
  let psig = null, pi = 0;
  if (prev && prev !== document.body) try { psig = focusSig(prev); pi = [...document.querySelectorAll(psig)].indexOf(prev); } catch { psig = null; }
  m.addEventListener('keydown', e => {
    if (e.key !== 'Tab' || e.defaultPrevented) return;
    const f = focusables(m).filter(x => x.tabIndex >= 0 || x === document.activeElement); e.preventDefault(); if (!f.length) return;
    // 2.19.0: the dialog moves the focus itself (DOM order, wraps): after an earlier dialog was removed, Firefox's own
    // navigation could start from a stale point and bounce between two buttons or leave the dialog
    const i = f.indexOf(document.activeElement);
    (i < 0 ? f[e.shiftKey ? f.length - 1 : 0] : f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length]).focus();
  });
  setTimeout(() => {
    if (!document || !m.isConnected || m.contains(document.activeElement) || $('#pop:not(.hidden)')?.contains(document.activeElement) || $('#dpop')?.contains(document.activeElement)) return;  // 2.910.0 (#5442): + the date picker opened at once
    // CI of 2.223.2: a dialog's own first focus (data-mfocus) wins over the card when the focus got lost before (a redraw)
    const own = m.querySelector('[data-mfocus]:not([disabled])');
    if (own) { try { own.focus({preventScroll: true}); } catch { own.focus(); } return; }
    if (card) { card.tabIndex = -1; try { card.focus({preventScroll: true}); } catch { card.focus(); } }
  }, 90);
  onRemove(m, () => {
    if (!document) return;  // the window is gone
    const a = document.activeElement;
    let t = prev;
    if (t && !t.isConnected && psig) try { const all = document.querySelectorAll(psig); t = all[Math.max(0, Math.min(pi, all.length - 1))] || null; } catch { t = null; }
    if (t && t.isConnected && t !== document.body && (!a || a === document.body || !a.isConnected)) { try { t.focus({preventScroll: true}); } catch { /* gone */ } }
  });
}
// ---- UX1 (U12): the app's own dialogs instead of window.confirm / window.prompt. askConfirm resolves true / false,
// askPrompt the text or null. Esc, a click next to it and "Cancel" say no; a destructive action is red and not focused.
function onRemove(el, fn) {  // runs fn once el left the page (removed by any path: Esc, backdrop, code)
  const mo = new MutationObserver(() => { if (!el.isConnected) { mo.disconnect(); fn(); } });
  mo.observe(document.body, {childList: true});
  return mo;
}
// 2.37.0 (#1158): closing a dialog by Esc / the backdrop goes through its own close (md._close, see modalGuard) if it has one
const modalClose = m => { if (m._close) m._close(); else m.remove(); };
// a dialog with unsaved input: closing it (Cancel, Esc, the backdrop) asks "Discard changes?" while dirty() is true.
// Returns the close function for the dialog's own Cancel button.
function modalGuard(md, dirty) {
  md._close = async () => {
    if (md._asking) return;
    if (dirty()) {
      md._asking = true;
      const ok = await askConfirm(tr('Discard changes?'), tr('Your changes in this dialog are not saved yet.'), {ok: tr('Discard'), danger: true, cancel: tr('Keep editing')});
      md._asking = false;
      if (!ok) return;
    }
    md.remove();
  };
  return md._close;
}
// a dialog opened from inside another one: the first one steps aside (hidden, its unsaved input kept) and comes back when
// the sub-dialog closes ("Back", Esc, the backdrop). open() returns the sub-dialog (or a promise of it; nothing = no dialog).
function modalSub(parent, open) {
  const from = document.activeElement;
  parent.style.display = 'none'; parent.setAttribute('aria-hidden', 'true');
  const show = () => {
    if (!parent.isConnected) return;
    parent.style.display = ''; parent.removeAttribute('aria-hidden');
    setTimeout(() => { try { (from && parent.contains(from) ? from : parent.querySelector('.card'))?.focus({preventScroll: true}); } catch { /* gone */ } }, 0);
  };
  Promise.resolve(open()).then(ch => { if (ch && ch.isConnected) onRemove(ch, show); else show(); }, show);
}
// 2.359.2 B (#3049): submit(value) = the write behind "OK": the dialog closes once it worked; false / an error keeps it open with its text
function askDialog({title, body = '', html = '', ok, danger = false, input = null, cancel, after, submit = null}) {  // after(md): 2.47.3 (#1729) extra wiring of an html body
  return new Promise(res => {
    let done = false;
    const md = modal(`<form class="cdlg-f" novalidate><h3 id="cdlg-t">${esc(title)}</h3>${body || html ? `<div class="cdlg-b" id="cdlg-b">${html || esc(body)}</div>` : ''}
      ${input ? `<input id="cdlg-in" value="${esc(input.value || '')}" placeholder="${esc(input.placeholder || '')}" aria-labelledby="cdlg-t" autocomplete="off" ${input.type ? `type="${input.type}"` : ''} ${input.max ? `maxlength="${input.max}"` : ''}>` : ''}
      <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-cd="no">${esc(cancel || tr('Cancel'))}</button><button type="submit" class="btn ${danger ? 'danger solid' : 'pri'}" data-cd="yes">${esc(ok || tr('OK'))}</button></div></form>`);
    md.classList.add('cdlg');
    if (after) after(md);
    md.setAttribute('role', input ? 'dialog' : 'alertdialog'); md.setAttribute('aria-modal', 'true'); md.setAttribute('aria-labelledby', 'cdlg-t');
    if (body || html) md.setAttribute('aria-describedby', 'cdlg-b');
    const prev = document.activeElement;
    const fin = v => { if (done) return; done = true; res(v); if (md.isConnected) md.remove(); try { if (prev && prev.isConnected) prev.focus({preventScroll: true}); } catch { /* gone */ } };
    md.querySelector('form').addEventListener('submit', async e => {
      e.preventDefault(); const v = input ? $('#cdlg-in', md).value : true;
      if (submit) {
        if (md._busy) return;
        md._busy = 1; let r; try { r = await submit(v); } catch { r = false; } md._busy = 0;
        if (r === false) return;
      }
      fin(v);
    });
    md.addEventListener('click', e => { if (e.target.closest('[data-cd="no"]')) fin(input ? null : false); });
    md.addEventListener('keydown', e => {  // keep Tab inside the dialog
      if (e.key !== 'Tab') return;
      const f = $$('input,button', md).filter(x => !x.disabled); if (!f.length) return;
      if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
      else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
    });
    onRemove(md, () => fin(input ? null : false));
    setTimeout(() => { const f = input ? $('#cdlg-in', md) : $(danger ? '[data-cd="no"]' : '[data-cd="yes"]', md); f?.focus(); if (input) f?.select?.(); }, 30);
  });
}
const askConfirm = (title, body = '', o = {}) => askDialog({title, body, ...o});
const askPrompt = (title, value = '', o = {}) => askDialog({title, ...o, input: {value, ...(o.input || {})}, ok: o.ok || tr('OK')});
const LCOLORS = ['', '#2dd4bf', '#6d8cff', '#6ee7b7', '#4ade80', '#f5b041', '#f87171', '#c084fc', '#f472b6', '#94a3b8'];
const EMOJIS = ['📥', '📌', '⭐', '🔥', '✅', '📅', '⏰', '🎯', '💡', '🧠', '🏠', '🏡', '🛒', '🍎', '🍳', '☕', '💼', '🖥️', '💻', '📱', '📞', '✉️', '📝', '📚', '📖', '✏️', '🎓', '💰', '💳', '🧾', '🏦', '📊', '🚗', '🚲', '✈️', '🏖️', '🧳', '🗺️', '🎁', '🎉', '🎵', '🎹', '🎧', '🎬', '📷', '🎨', '🌀', '🧵', '🛠️', '🔧', '🏃', '🏋️', '🧘', '❤️', '🩺', '💊', '👶', '🧒', '👪', '🐶', '🐱', '🐭', '🌱', '🌻', '☀️', '🌙', '♻️', '🔒', '🤶', '🎄'];
const EMO_RE = /^((?:\p{Extended_Pictographic}|\p{Emoji_Modifier}|\uFE0F|\u200D)+)\s*/u;
// list type (1.2): the choices, a hint per type (project: only the features whose module is on), the menu
// 2.7.2 (#414): two types only; the old checklist type is the list option "Show completed at the bottom" (lists.checklist)
const LKIND_ICON = {list: 'list', checklist: 'cart', project: 'pulse'};
// 2.4.0 (#243): project types = built-in project templates (server: PTYPES); '' = a blank project. Offered in the "New list"
// dialog (type Project, next to the person's own list templates, #328), the setup and the welcome tour.
const PTYPE_UI = [['', N_('Blank'), 'list', N_('Sections and fields as needed')],
  ['agency', N_('Agency'), 'brief', N_('Client, budget, time tracking')],
  ['software', N_('Software / AI dev'), 'code', N_('Board, tickets, repository')],
  ['private', N_('Personal|project type'), 'home', N_('No fields')],
  ['social', N_('Social media plan'), 'megaphone', N_('Calendar, channels, approval by the client')]];  // 2.387.0 (#1957)
// 2.636.0 (#4565): the shoot (server PTYPE_INDUSTRY): offered only with the industry Film & Video; keep = the list's own type
const PTYPE_SHOOT = ['shoot', N_('Shoot|project type'), 'film', N_('One card per shot, one column per shooting day, shot list as PDF')];
const ptypeUi = keep => indOn('film') || keep === 'shoot' ? [...PTYPE_UI, PTYPE_SHOOT] : PTYPE_UI;
// 2.27.0 (#972): the standard sections of each built-in project type (kalmido/lists/templates.py PTYPES), named next to the
// box "With the standard sections" in the New list dialog; a new project gets them only when the box is ticked
const PTYPE_SECS = {agency: [N_('Request'), N_('Concept'), N_('Production'), N_('Approval'), N_('Billing')],
  software: [N_('Backlog'), N_('Next|section'), N_('In progress'), N_('Review'), N_('Done|section')], private: [N_('Ideas'), N_('Planning'), N_('To do|section')],
  social: [N_('Idea|section'), N_('Draft|section'), N_('For approval|section'), N_('Approved|section'), N_('Scheduled|section'), N_('Published|section')],  // 2.387.0 (#1957)
  shoot: [N_('Shooting day 1'), N_('Shooting day 2')]};  // 2.636.0 (#4565)
// 2.1156.0 (#4280): the project dialog (listModal: name, type, sections, stale days, the webhook box) and its parts moved to listmodal.js (loaded on demand, static/js/lazyload.js)
const ptSecsLine = k => (PTYPE_SECS[k] || []).map(x => tr(x)).join(', ');
const MOD_NAMES = {time: N_('Time tracking'), fields: N_('Custom fields'), kanban: N_('Kanban'), deps: N_('Dependencies'), cal: N_('Calendar')};  // 2.387.0 (#1957): + cal
// after a project type switched modules on for this person: say which
function modulesOnToast(on) { if (on?.length) toast(tr('Switched on for you: {0}', on.map(m => tr(MOD_NAMES[m] || m)).join(', '))); }
// 2.4.0 (#340) ticketTplModal, the ticket types and templates of a project: sectpl.js (on demand, start budget #4198)
function projectParts() {
  return [depsOn() && (feat('timeline') ? tr('dependencies with the Gantt timeline') : tr('dependencies')),
    progressOn() && tr('progress and status')].filter(Boolean);  // 2.39.1 (#1217): custom fields are in every list
}
// 2.18.0 (#408): the project type of an existing list ('' = none), shown and changed in the list dialog (owner / list
// admins). The server switches on what the type needs (type Project, ticket types for software, the type's view while
// the list is empty, its modules for this person) and never deletes anything; one history step takes all of it back.
const ptypeName = k => k ? tr(ptypeUi('shoot').find(x => x[0] === k)?.[1] || k) : tr('None|project type');
// list settings (type, name, colour, folder, view, "move dependent tasks along", hourly rate, archived) as one history
// step; _prev = the values after, so a setting changed elsewhere meanwhile stays. false = the request failed
// 2.34.0 (#266): after how many idle days an open task of the list shows in "Lying idle" (owner / list admins)
const STALE_OPTS = [3, 5, 14, 30];
const LIST_HIST = ['name', 'color', 'folder', 'view', 'kind', 'dep_shift', 'rate', 'archived', 'tickets', 'nag', 'day_hours', 'checklist', 'family'];  // 2.7.0: nag, day_hours; 2.7.2: checklist = "Show completed at the bottom"; 2.396.0 (#3385): family (the shopping-list offer)
const LIST_LOCAL = ['name', 'color', 'view', 'dep_shift', 'rate', 'tickets', 'nag', 'day_hours', 'checklist', 'sort_mode', 'done_in_section', 'columns', 'stale_days'];  // 2.41.2 (#1501)
const lv = (k, v) => k === 'dep_shift' || k === 'archived' || k === 'tickets' || k === 'checklist' ? (v ? 1 : 0) : k === 'rate' || k === 'day_hours' ? (v === '' || v == null ? null : parseNum(v) ?? NaN) : v ?? '';
const lp_fieldName = f => tr({name: N_('Name'), color: N_('Colour'), folder: N_('Folder'), view: N_('View'), kind: N_('Type'), checklist: N_('Show completed at the bottom'), dep_shift: N_('Move dependent tasks along'), rate: N_('Hourly rate'), archived: N_('Archived')}[f] || f);
// 2.474.0 (#3917): the writes of one list go out one after the other: a second quick choice on a slow connection could overtake
// the first on the server, and the older value stayed while the screen showed the newer one
const LP_TAIL = new Map();
function lpSend(id, body) {
  const p = (LP_TAIL.get(id) || Promise.resolve()).catch(() => {}).then(() => api('PATCH', '/api/lists/' + id, body));
  LP_TAIL.set(id, p);
  const end = () => { if (LP_TAIL.get(id) === p) LP_TAIL.delete(id); };
  p.then(end, end);
  return p;
}
async function listPatch(id, body, label, o = {}) {
  const l = listById(id); if (!l) return false;
  const ws0 = l.org_id || null;  // 2.53.0 (#1474)
  const before = {}, after = {};
  for (const k of LIST_HIST) if (k in body && lv(k, l[k]) !== lv(k, body[k])) { before[k] = lv(k, l[k]); after[k] = lv(k, body[k]); }
  // 2.283.0 (#3119): the history step comes at once with the change on screen; an undo meanwhile waits for the write
  // (and its reload), a failed write takes the step out again
  let e = null, run, res;  // 2.270.0 A (#3019): res = the answer (conflicts of a save with _prev)
  const pend = new Promise(r => { run = r; });
  const go = (to, from) => async () => {
    await pend;
    const r = await api('PATCH', '/api/lists/' + id, {...to, _prev: from});
    return {skipped: (r.conflicts || []).map(c => `${qn(lname(listById(id)) || '')}: ${lp_fieldName(c.field)}`)};
  };
  const vals = Object.fromEntries(Object.keys(body).filter(k => !k.startsWith('_') && k !== 'folder_adopt').map(k => [k, LIST_HIST.includes(k) ? lv(k, body[k]) : body[k]]));
  try {  // 2.41.2 (#1501): optimistic, shows at once
    res = await optWrite(() => {
      const back = optSet(() => listById(id), vals)();
      if (!e && Object.keys(before).length) { e = histAdd({label: label || tr('Settings of {0}', qn(lname(l))), undo: go(before, after), redo: go(after, before), post: o.post}); o.step?.(e); }
      return back;
    }, () => lpSend(id, body));
  } catch {
    if (e) { HIST.undo = HIST.undo.filter(x => x !== e); renderHist(); }
    run(); return false;
  }
  if (e && res?.undo_group) histOwn(e, +res.undo_group);  // 2.809.0 (#5476): the server lists the step; 2.905.0 (#5255): and takes it back (its group)
  // 2.1074.0 (#5493): a save with side effects only (workspace, time tracking, agents ...) is a server step too: its entry
  else if (!e && res?.undo_group) { e = histAdd({label: label || ('org_id' in body ? tr('Workspace of {0}', qn(lname(l))) : tr('Settings of {0}', qn(lname(l)))), res, lids: [id], post: o.post}); o.step?.(e); }
  const cf = (res?.conflicts || []).map(c => c.field);  // 2.270.0 A (#3019): changed elsewhere meanwhile: kept, said, not in the undo step
  if (cf.length) {
    for (const k of cf) { delete before[k]; delete after[k]; }
    if (e && !Object.keys(before).length && !histGids(e).length) { HIST.undo = HIST.undo.filter(x => x !== e); renderHist(); e = null; }  // 2.1074.0 (#5493): a server step stays (it holds what did change)
  }
  // what only changes the list itself needs no GET /api/state; folder, type, archive and time tracking have side effects
  // on the server (sharing, modules, hidden tasks): 2.46.2 (#1659) the reload for them runs behind; a conflict reloads too
  // (what stayed replaces the optimistic value)
  try { if (cf.length || !Object.keys(body).every(k => k === '_prev' || LIST_LOCAL.includes(k))) { await load(); render(); } } finally { run(); }
  if (cf.length) { o.conflicts?.(res.conflicts); toast(`${tr('Changed elsewhere in the meantime')}: ${cf.map(lp_fieldName).join(', ')}`); }
  // 2.273.0 B (#3042): what the workspace change ended; its Undo brings it back. 2.1074.0 (#5493): the Undo is the save's own
  // server step (lists/lpside.py takes the workspace back with what the move ended), no second entry with its own write
  if ('org_id' in body && !cf.includes('org_id') && res?.move_ended) offerUndo(tmm_msg('', res), e);
  else if ('org_id' in body && !cf.includes('org_id')) wsc_listMoved(id, ws0, body.org_id || null, e);  // 2.53.0 (#1474): moved into an organisation: who sees it now
  return e;
}
// per user and project: the progress bar is off by default (2.40.0, #1190) and switched on in the list options / settings
// (show_progress, stored server-side, so it follows to every device; the old hide_progress is no longer read)
const progHidden = id => !(S.settings.show_progress || '').split(',').includes(String(id));
async function setProgHidden(id, hide) {
  const ids = (S.settings.show_progress || '').split(',').filter(x => x && x !== String(id));
  if (!hide) ids.push(String(id));
  S.settings.show_progress = ids.join(',');
  render();
  try { await api('PATCH', '/api/settings', {show_progress: S.settings.show_progress}); } catch { await load(); render(); }
}
// the list's "…" menu (header) and the sidebar's context menu
const colItem = id => ({label: tr('Shown fields…'), icon: 'columns', cls: 'mcols', fn: () => colModal(id)});
function listMenuItems(id, anchor) {
  const l = listById(id); if (!l) return [];
  const own = isOwner(l), k = l.kind || 'list', at = () => typeof anchor === 'function' ? anchor() : anchor;
  // 2.25.0 (UX-12): only what works here: the inbox has no "Edit list…" and no list / project switch
  const items = [...(l.is_inbox ? [] : [{label: tr('Edit project…'), icon: 'edit', fn: () => listModal(id)}]), ...(shareOk(l) && !l.archived ? [{label: tr(collab() ? N_('Share…') : N_('Ownership…')), icon: 'users', cls: 'mshare', fn: () => shareModal(id)}] : [])];
  // 2.27.0 (#974): "Agent: <name>…" right under "Share…": opens the share dialog at its Agents part (one place for the setting)
  // 2.36.2 (#1135): from the sidebar (right-click / long press): the colour in one tap (the 9 fixed colours + none)
  if (own && !l.is_inbox && !l.archived && typeof anchor !== 'function' && anchor?.closest?.('#side')) items.unshift(lp_menuRow(lp_col(l), c => licColor(id, c)), '-');  // 2.53.0 (#1426): the 12 tones (listcolor.js)
  if (agentsOn() && shareOk(l) && canManage(l) && !l.is_inbox && !l.archived) {
    const ag = listAgents(l)[0];
    items.push({label: ag ? tr('Agent: {0}…', ag.name) : tr('Agent…'), ...(ag ? {sub: listenLabel(l)} : {}), icon: 'bot', cls: 'magent', fn: () => shareModal(id, {focus: 'agents'}),  // 2.30.0 (#1034)
      ...(l.e2e ? {dis: true, title: tr('Not available in encrypted projects')} : {})});  // 2.64.1 (#1817)
  }
  const pbi = pbMenuItem(l); if (pbi) items.push(l.e2e ? {...pbi, dis: true, title: tr('Not available in encrypted projects')} : pbi);  // 2.39.0 (#1168): the list's playbook; 2.64.1 (#1817): not in a locked list
  if (agentsOn() && !l.is_inbox && listAgents(l).length) items.push({label: tr('Agent access'), icon: 'eye', cls: 'magacc', rare: 1, fn: () => agAccessModal(id)});  // 2.30.0 (#919): the access log
  // 2.27.0 (#990): a section can be added from here too (also in an empty list)
  // 2.31.0 (#1053): "Set status" left the list header; here (and on the project page) it stays one tap away
  if (statusFor(l) && !l.is_inbox && !l.archived && canEditList(id)) items.push({label: tr('Set status'), icon: 'pulse', cls: 'mstatus', fn: () => statusModal(id)});
  if (!l.is_inbox && !l.archived && canEditList(id)) items.push({label: tr('Add section…'), icon: 'plus', cls: 'msecadd', fn: async () => {
    const n = await askPrompt(tr('Name of the section / column'), '', {ok: tr('Add')}); if (n && n.trim()) await sectionCreate(id, n.trim());
  }});
  // 2.156.0 C (#2073): save the sections as a template / add a template's sections (sectpl.js, people in the app only)
  if (!l.is_inbox && !l.archived && canEditList(id) && !S.me?.kid && S.me?.kind !== 'agent') items.push({label: tr('Section templates…'), icon: 'copy', cls: 'msectpl', fn: () => sct_open(id), ...(l.e2e ? {dis: true, title: tr('Not available in encrypted projects')} : {})});
  // 2.14.0 (#425): "Columns…" replaces "Show task numbers" and "Hide / Show assignee column" (per device until then); high up
  if (!l.archived) items.push(colItem(id));
  // 2.17.0 (#442 #419): the list's notes and (shared) its team chat
  if (notesOn(l) && !l.archived) { const n = notesOf(id).length; items.push({label: n ? tr('Notes ({0})', n) : tr('Notes'), icon: 'edit', fn: () => go('notes/' + id)}); }
  if (teamOn() && l.shared && !l.archived && l.role !== 'participant') items.push({label: tr('Team chat'), icon: 'comment', fn: () => listChat(id)});
  if (feat('sheets') && !l.is_inbox && !l.archived && !l.e2e) items.push({label: tr('Attached tables'), icon: 'sheet', cls: 'msheets', fn: () => go('sheets/l/' + id)});  // 2.89.0 (#1916): the tables attached to it
  if (!l.archived && typeof mw_ok === 'function' && mw_ok()) items.push({label: tr('Open in its own window'), icon: 'panel', cls: 'mminiwin', fn: () => mw_open(id)});  // 2.39.1 (#1294): desktop, miniwin.js
  if (!l.archived && typeof spl_item === 'function') items.push(...spl_item('#l/' + id));  // 2.742.0 (#4858): the split view's right half
  if (!l.is_inbox && !l.archived) items.push({label: tr('Move to folder…'), icon: 'folder', next: 1, fn: () => folderPick(at(), id)});
  if (!l.is_inbox && !l.archived && !S.listReorder && typeof listReorderSet === 'function') items.push({label: tr('Sort projects'), icon: 'sort', cls: 'mlsort', fn: () => listReorderSet(true)});  // 2.482.0 (#3951): the sort mode of sidebar + Projects page
  // 2.116.0 C (#2064): the list as a CSV file / a printable page (listprint.js); a list with the lock has only ciphertext on the server
  items.push({label: tr('Export as CSV'), icon: 'download', cls: 'mlexcsv', fn: () => lexCsv(id), ...(l.e2e ? {dis: true, title: tr('Not available in encrypted projects')} : {})},
    {label: tr('Print'), icon: 'file', cls: 'mlexprint', fn: () => lexPrint(id)});
  if (dupOk(l)) items.push({label: tr('Duplicate project…'), icon: 'copy', cls: 'mdup', fn: () => listDuplicate(id)});  // 2.78.0 (#1881, templates.js)
  if (!l.is_inbox && !l.archived && typeof dx_start === 'function' && typeof anchor !== 'function' && anchor?.closest?.('#side')) items.push({label: tr('Select several projects'), icon: 'check', fn: () => dx_start(id)});  // 2.47.3 (#1727)
  // 2.27.0 (#991): from the sidebar (right-click / long press): its place among the lists of its folder
  if (!l.is_inbox && !l.archived && typeof anchor !== 'function' && anchor?.closest?.('#side')) items.push('-', mpo_posItem(listMoveItems(id)), '-');  // 2.62.0 (#1853): one entry, the four moves in a second level
  if (propOn() && !l.archived) {  // 2.3.0 (#262 #263)
    if (l.is_inbox && own) items.push({label: propWith(N_('Sort the basket with {0}…'), N_('Sort the basket with an agent…')), icon: 'bot', rare: 1, fn: () => propRequest('triage', {})});
    else if (!l.is_inbox && canEditList(id)) items.push({label: tr('Tasks from notes…'), icon: 'bot', rare: 1, fn: () => propRequest('extract', {lid: id}), ...(l.e2e ? {dis: true, title: tr('Not available in encrypted projects')} : {})});  // 2.64.1 (#1817)
  }
  if (clnOk(l)) items.push({label: tr('Tidy up the project…'), icon: 'bot', cls: 'mclean', fn: () => clnRequest(id)});  // 2.39.0 (#1151): cleanup.js
  // 2.13.0 (#453 A7): not a second "List"; 2.18.0 review: "As a list / As a project", "Type: Project" read like the project type
  // 2.25.0 (UX-52): list or project is the switch "Project features" in "Edit list…" (no "As a list / As a project" here)
  void k;
  if (collab() && l.shared) items.push({label: tr('Notifications: {0}', bellLabel(l.bell)), icon: BELL_ICON[l.bell || 'default'], rare: 1, next: 1, fn: () => bellMenu(at(), id)});
  { const fv = favMenuItem(l), o = items.findIndex(x => x && x.label === tr('Open')), c = items.findIndex(x => x?.rcls === 'mcols'); if (fv) items.splice(o >= 0 ? o + 1 : c >= 0 ? c + 2 : 0, 0, fv); }  // 2.40.0 (#1361): the personal star; 2.441.0 (#3592): second, right after Open
  if (progressFor(l) && !l.is_inbox) items.push(progHidden(id) ? {label: tr('Show progress'), icon: 'eye', rare: 1, fn: () => setProgHidden(id, false)} : {label: tr('Hide progress'), icon: 'x', rare: 1, fn: () => setProgHidden(id, true)});
  // U12: archive (with undo) instead of delete; deleting for good only from the archive
  // 2.25.0 (UX-13): delete from every list menu; 2.39.1 (#1188): also list admins, organisation admins (listadmin.js)
  items.push(...lmDangerItems(l, id));
  return listMenuSort(items);
}
// 2.31.0 (#1056): the list menu in three parts: the everyday entries (in their order; a new one lands here), the rare ones
// (notifications, progress, agent access, tasks from notes: rare: 1) in a second level "More list options…" (one alone stays
// inline), and what cannot simply be taken back (archive, delete: danger: 1) last, set apart
async function licColor(id, c) {  // 2.36.2 (#1135): the list colour from the sidebar menu, undoable
  const l = listById(id); if (!l || lp_col(l) === c) return;  // 2.53.0 (#1426): the shown tone
  const e = await listPatch(id, {color: c}, tr('Colour of {0}', qn(lname(l))));
  if (e) offerUndo(tr('Colour of {0}', lname(l)), e);
}
function listMenuSort(items) {
  const rare = items.filter(x => x && x.rare), dang = items.filter(x => x && x.danger), main = items.filter(x => x && !x.rare && !x.danger);
  while (main[main.length - 1] === '-') main.pop();
  return [...main, ...(rare.length > 1 ? [{label: tr('More project options…'), icon: 'sliders', cls: 'mlmore', more: rare}] : rare), ...(dang.length ? ['-', ...dang] : [])];
}
// 2.1.0 (#317): the bell of a list (mine only): all / default (the matrix in Settings > Notifications) / mute
// 2.6.1 (#404): + custom = my own choice per event (News and Push each), for this list only
const BELLS = [['all', N_('All activity'), N_('every comment, new task and change in this project')], ['default', N_('Default'), N_('as in Settings > Notifications')],
  ['mute', N_('Mute'), N_('only mentions of me and tasks assigned to me')], ['custom', N_('Custom selection…'), N_('your own choice per event, for News and Push')]];
const BELL_ICON = {all: 'bellring', default: 'bell', mute: 'belloff', custom: 'sliders'};
const bellLabel = m => tr(BELLS.find(b => b[0] === (m || 'default'))[1]).replace(/…$/, '');
// the events of the custom bell (server: BELL_CUSTOM_ROWS); a ticked one comes from every task of the list
const BELL_ROWS = [['newtask', N_('New tasks'), N_('created by someone else')], ['comment', N_('Comments'), N_('every comment in this project, replies included')],
  ['mention', N_('Mentions of me')], ['assign', N_('Tasks assigned to me (or taken away)')], ['complete', N_('Completed tasks'), N_('completed by someone else')],
  ['status', N_('Project status changes')], ['unblock', N_('A task blocking mine was completed'), '', 'deps'], ['approval', N_('An agent waits for my approval'), N_('proposals and approvals of agents'), 'agents']];
// what a custom bell starts with: the stored choice, else what the matrix (Settings > Notifications) says today
function bellCustomOf(l) {
  const m = notifMatrix(S.settings), c = l?.bell_custom || {}, out = {};
  for (const [r] of BELL_ROWS) out[r] = {news: 'news' in (c[r] || {}) ? !!c[r].news : !!m[r]?.news, push: 'push' in (c[r] || {}) ? !!c[r].push : !!m[r]?.push};
  return out;
}
async function bellSet(id, mode, custom) {  // 2.359.2 B (#3049): true = saved (or nothing to save)
  const l = listById(id); if (!l || ((l.bell || 'default') === mode && !custom)) return true;
  const prev = l.bell || 'default', prevC = l.bell_custom || {};
  let j;
  try { j = await api('PUT', `/api/lists/${id}/bell`, custom ? {mode, custom} : {mode}); } catch { return false; }
  l.bell = mode; if (j?.custom) l.bell_custom = j.custom;
  renderSide(); render();
  const sel = $('#l-bell'); if (sel) { sel.value = mode; sel.dispatchEvent(new Event('bell-sync')); }
  toast(tr('Notifications for {0}: {1}', lname(l), bellLabel(mode)), async () => {
    const r = await api('PUT', `/api/lists/${id}/bell`, prev === 'custom' || custom ? {mode: prev, custom: prevC} : {mode: prev});
    l.bell = prev; l.bell_custom = r?.custom || prevC; renderSide(); render(); const s2 = $('#l-bell'); if (s2) { s2.value = prev; s2.dispatchEvent(new Event('bell-sync')); }
  });
  return true;
}
function bellMenu(anchor, id) {
  const l = listById(id); if (!l) return;
  const cap = l.notif_cap ? [{label: tr('{0} has limited the notifications for this project', l.notif_cap.by || l.owner_name || '') + ': ' + ntfName(l.notif_cap.tpl), icon: 'lock', fn: () => toast(tr('Pushes allowed: {0}', (l.notif_cap.allowed || []).map(ntfRowName).join(', ') || tr('none')))}] : [];  // 2.33.0 (#927)
  menu(anchor, [...BELLS.map(([m, n, h]) => ({label: tr(n), title: tr(h), icon: BELL_ICON[m], on: (l.bell || 'default') === m, fn: () => m === 'custom' ? bellCustomModal(id) : bellSet(id, m)})), ...cap]);
}
// "Custom selection…": the events x News / Push for this list (same table as Settings > Notifications)
function bellCustomModal(id) {
  const l = listById(id); if (!l) return;
  const v = bellCustomOf(l), social = collab();
  const rows = BELL_ROWS.filter(([, , , f]) => !f || (f === 'deps' ? depsOn() : feat('agents') && (S.agents || []).length));
  const box = (r, ch, lab) => `<label class="nmhit"><input type="checkbox" data-bc="${r}" data-ch="${ch}" ${v[r][ch] ? 'checked' : ''} aria-label="${esc(tr(lab) + ': ' + (ch === 'news' ? tr('News') : tr('Push')))}"></label>`;
  const md = modal(`<h3 id="bc-h">${esc(tr('Notifications for {0}', lname(l)))}</h3>
    <div class="shint">${tr('Ticked = reaches you from every task of this project. Only for you.')}</div>
    <div class="nmx bcmx" role="table" aria-labelledby="bc-h"><div class="nmh" role="row"><span role="columnheader">${tr('Event')}</span><span role="columnheader">${tr('News')}</span><span role="columnheader">${tr('Push')}</span></div>
    ${rows.map(([r, n, d]) => `<div class="nmr" role="row"><span class="nml" role="cell">${tr(n)}${d ? `<small>${tr(d)}</small>` : ''}</span><span role="cell">${social ? box(r, 'news', n) : '<span class="nmna">–</span>'}</span><span role="cell">${box(r, 'push', n)}</span></div>`).join('')}</div>
    <div class="row mfoot"><button class="btn sm" data-bcq="none">${tr('Tick none')}</button><span class="spacer"></span><button class="btn" data-bcq="cancel">${tr('Cancel')}</button><button class="btn pri" data-bcq="save">${tr('Save')}</button></div>`);
  md.classList.add('bcmodal');
  onRemove(md, () => { const sel = $('#l-bell'); if (sel) { sel.value = listById(id)?.bell || 'default'; sel.dispatchEvent(new Event('bell-sync')); } });  // closed without saving: the list dialog shows the bell as it is
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-bcq]'); if (!b) return;
    if (b.dataset.bcq === 'none') { $$('[data-bc]', md).forEach(x => { x.checked = false; }); return; }
    if (b.dataset.bcq === 'cancel') { md.remove(); return; }
    const custom = {};
    for (const x of $$('[data-bc]', md)) (custom[x.dataset.bc] ||= {})[x.dataset.ch] = x.checked ? 1 : 0;
    if (b.disabled) return;
    b.disabled = true;  // 2.359.2 B (#3049): closed once saved; on an error the ticks stay (api() said why)
    const ok = await bellSet(id, 'custom', custom);
    b.disabled = false;
    if (ok) md.remove();
  });
  setTimeout(() => $('[data-bc]', md)?.focus(), 30);
}
function listMenu(anchor, id) { const it = listMenuItems(id, anchor); if (it.length) menu(anchor, it); }
// archive / restore a list: one history step (undo brings it back), the toast offers the undo too
async function listArchive(id, on) {
  const l = listById(id); if (!l) return;
  if (!canManage(l) && lmOrgAdmin(l)) return lmOrgAct(l, on ? 'archive' : 'restore');  // 2.39.1 (#1188)
  const msg = on ? tr('“{0}” archived. Find it under “Archived” in the sidebar.', lname(l)) : tr('“{0}” is back in your projects', lname(l));
  // 2.283.0 (#3119): the toast with its undo comes with the step, not after the reload
  const e = await listPatch(id, {archived: on ? 1 : 0}, on ? tr('Archived {0}', qn(lname(l))) : tr('Restored {0} from the archive', qn(lname(l))), {step: x => offerUndo(msg, x)});
  if (e === false) return;
  if (on && S.route.key === 'l:' + id) go(START_KEY);
}
// deleting for good: only archived lists; the dialog names what is lost
async function listDeleteForGood(id) {
  const l = listById(id); if (!l || l.is_inbox) return false;  // 2.25.0 (UX-13): also an active list (archived first)
  if (!canManage(l)) return lmOrgAdmin(l) && l.archived ? lmOrgAct(l, 'delete') : false;  // 2.39.1 (#1188): owner, list admins; organisation admins
  const all = [...S.tasks.values()].filter(t => t.list_id === id), open = all.filter(t => t.status === 0).length;
  const lost = [tr('the project itself, its sections, colour, folder and type'), fieldsOf(id).length && trn('{0} custom field and its values', '{0} custom fields and their values', fieldsOf(id).length),
    l.shared && tr('the sharing: members lose access at once'), l.status && tr('the project status'), tr('its public link, if there is one'),
    l.e2e && all.length && tr('its tasks, comments and notes: they are encrypted in the browser and do not go to the trash')].filter(Boolean);  // 2.64.1 (#1817)
  // 2.102.0 A (#1988): a list without the lock goes into the list trash (restorable, undo below); with the lock: for good
  const ok = !l.e2e ? await askConfirm(tr('Delete “{0}”?', lname(l)), '', {danger: true, ok: tr('Delete'), html: `<p>${esc(otr_note(l))}</p>${lmDeleteNotes(l, all.length, open)}`})
    : await askConfirm(tr('Delete “{0}” permanently?', lname(l)), '', {danger: true, ok: tr('Delete permanently'),
    html: `<p>${tr('This cannot be undone. Lost permanently:')}</p><ul class="cdlg-l">${lost.map(x => `<li>${esc(x)}</li>`).join('')}</ul>${isOwner(l) ? '' : lmDeleteNotes(l, all.length, open)}<p class="muted" ${isOwner(l) && !l.e2e ? '' : 'hidden'}>${all.length ? trnh('Its {0} task goes to the trash of your basket ({1} open) and can be restored from there.', 'Its {0} tasks go to the trash of your inbox ({1} open) and can be restored from there.', all.length, open) : tr('The project has no tasks.')}</p>${isOwner(l) ? lmDeleteNotes(l, all.length, open) : ''}`});
  if (!ok) return false;
  // 2.46.2 (#1659): the list (and its tasks) leave the screen at once; archive + delete + the reload run behind it, an
  // error brings the list back (optWrite: a state that arrives meanwhile gets it removed again)
  const nm = lname(l), active = !l.archived;  // 2.119.1 C (#2304): the undo brings an active list back active
  if (S.route.key === 'l:' + id) go(START_KEY);
  const put = () => {
    const i = S.lists.findIndex(x => x.id === id); if (i < 0) return null;
    const [x] = S.lists.splice(i, 1), ts = [...S.tasks.values()].filter(t => t.list_id === id);
    for (const t of ts) S.tasks.delete(t.id);
    return () => { if (!listById(id)) S.lists.splice(Math.min(i, S.lists.length), 0, x); for (const t of ts) if (!S.tasks.has(t.id)) S.tasks.set(t.id, t); };
  };
  let inTrash = false;
  optWrite(put, async () => {
    if (active) await api('PATCH', '/api/lists/' + id, {archived: 1});
    inTrash = !!(await api('DELETE', '/api/lists/' + id))?.trash;
  }).then(() => inTrash ? otr_offerUndo(id, nm) : toast(tr('“{0}” deleted', nm)), () => {})  // an error: api() said why, the list is back
    .then(() => load()).then(render, () => {});  // half done (archived, not deleted) shows the real state
  return true;  // gone from the screen: the dialog closes at once
}
// ---- 2.6.0 (K12): the Share dialog, out of the long list dialog: people + roles and inviting, the agents of the list (share /
// stop sharing, the tidy agent), the public link, transferring the ownership. From the list's "…" menu, the header's Share
// button and the list dialog (Sharing > Share…). Admins without collaboration only see the ownership part.
const shareOk = l => !!l && !l.is_inbox && !l.quicknote && (collab() || !!S.me?.is_admin);  // 2.477.0 (#3881): the list Notes stays private
function shareSummary(l) {
  const ppl = listPeople(l).filter(p => !(S.me && p.user_id === S.me.id) && !agentById(p.user_id) && !p.agent), ags = listAgents(l);
  if (!collab()) return tr('Owner: {0}', l.owner_name || S.me?.display_name || '');
  return [ppl.length ? trn('Shared with {0} person', 'Shared with {0} people', ppl.length) : tr('Not shared with anyone yet'), ags.length ? trn('{0} agent', '{0} agents', ags.length) : '', ags.length ? listenLabel(l) : ''].filter(Boolean).join(' · ');
}
// 2.1156.0 (#4280): the Share dialog of a project (shareModal: people, groups, agents, notifications, public link) moved to sharemodal.js (loaded on demand, static/js/lazyload.js)
// 2.910.0 (#5442): the Share dialogs of a project (here) and of a folder (sharedlg.js, moves over in #5587) are one building block: the same frame
// (shFrameHtml: head with the cross, the parts, the foot "… settings…" | "Done"), the same folded part (shSecHtml) and the same
// role choice (shRoleSel); each dialog passes its adapter (the ids of its parts, its title and settings button). The ids stay
// (sh-sec-* / fsh-sec-*, fp-sec-ntf) for links and tests. Every part keeps a minimum height (start-polish-listen-2910.css), so the
// dialog does not grow in steps while its people, agents and links load.
function shSecHtml(a, k, title, inner, hide = false, open = false) {
  return `<details class="shsec" id="${esc(a.sec(k))}" ${hide ? 'hidden' : ''} ${open ? 'open' : ''}><summary><h4 id="${esc(a.hid[k])}">${/*html-ok*/ title/* tr() of the caller */}</h4><span class="shsecst muted" id="${esc(a.st(k))}"></span>${ic('chev', 's shchev')}</summary>${/*html-ok*/ inner/* the part's markup */}</details>`;
}
function shFrameHtml(a) {
  return `<div class="lhdr"><h3>${esc(a.title)}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}" title="${esc(tr('Close'))}">${ic('x')}</button></div>${/*html-ok*/ a.body/* the parts */}
    <div class="foot"><button class="btn" data-m="${esc(a.setAct)}">${ic(a.setIcon, 's')} ${esc(a.setLabel)}</button><span class="spacer"></span><button class="btn pri" data-m="close">${esc(tr('Done'))}</button></div>`;  // a dialog that saves by itself closes with "Done" (was "Back" when opened from the settings)
}
const shRoleSel = (attr, cur, lab) => `<select ${attr} aria-label="${esc(lab || tr('Role'))}">${ROLES.map(([v, n, h]) => `<option value="${v}" title="${esc(tr(h))}" ${v === cur ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>`;
// 2.1071.0 (#5658): the open shares by e-mail address of a project / folder (nobody confirmed the address yet, core/addrshare.py):
// the address and "invited", with a button to take it back; the share is made once the address is confirmed
async function adsFill(box, q) {
  if (!box) return;
  let j; try { j = await rawFetch('GET', '/api/addr-shares?' + q); } catch { box.innerHTML = ''; return; }
  if (!box.isConnected) return;
  box.innerHTML = (j.open || []).map(x => `<div class="mrow"><span class="n">${esc(x.email || '?')} <span class="muted">${esc(tr('Invited: gets access once the address is confirmed'))}</span></span><button type="button" class="iconbtn" data-adsrm="${esc(x.id)}" title="${esc(tr('Remove the invitation to {0}', x.email || '?'))}" aria-label="${esc(tr('Remove the invitation to {0}', x.email || '?'))}">${ic('x', 's')}</button></div>`).join('');
  box.onclick = async e => { const b = /** @type {any} */ (e.target).closest('[data-adsrm]'); if (!b) return; e.stopPropagation(); try { await api('DELETE', `/api/addr-shares/${b.dataset.adsrm}`); } catch { return; } toast(tr('Invitation removed')); adsFill(box, q); };
}
// ---- 2.33.0 (#927): the owner's notification template for the other people of a list / a shared folder: a ceiling for
// their pushes (they can be quieter, never louder; the News stay complete). The server checks it (notif_ok -> cap_ok).
// The same block sits in the Share dialog and in "Share folder"; per person another template; a list in a folder follows
// the folder until it gets its own. Members see who limited it (list menu > Notifications, Share dialog).
const NTF_TPLS = [['read', N_('Read-only'), N_('Pushes only for mentions, assignments and direct replies')],
  ['work', N_('Collaborate'), N_('Also comments on their own or assigned tasks and due reminders')],
  ['all', N_('Everything'), N_('Nothing limited, as in their own settings')], ['custom', N_('Custom selection'), N_('You select the events')]];  // 2.34.0 (#1089): own key ("Custom" is the date range)
const NTF_CUSTOM = ['mention', 'reply', 'assign', 'approval', 'comment', 'follow', 'newtask', 'complete', 'status', 'unblock', 'chat', 'reminder', 'errreport', 'share'];
const NTF_WORK = ['mention', 'reply', 'assign', 'approval', 'comment', 'reminder'];
const ntfName = t => tr((NTF_TPLS.find(x => x[0] === t) || NTF_TPLS[0])[1]);
const ntfRowName = r => { const x = NOTIF_ROWS.find(y => y[0] === r); return x ? tr(x[1]) : r; };
function ntfMemberHint(l) {
  const c = l?.notif_cap; if (!c) return '';
  return `<div class="shint keep ntfhint">${ic('belloff', 's')} <span>${esc(tr('{0} has limited the notifications for this project', c.by || l.owner_name || ''))}: <b>${esc(ntfName(c.tpl))}</b></span></div>`;
}
function ntfHtml(j, scope) {
  const inh = j.inherited || {tpl: 'read'}, own = j.own, cur = own ? own.tpl : (inh.folder ? 'inherit' : inh.tpl);
  const eff = j.effective || {tpl: 'read', custom: {}};
  const opts = [...(inh.folder ? [['inherit', tr('As the folder “{0}”', fDisp(inh.folder)), ntfName(inh.tpl)]] : []), ...NTF_TPLS.map(([v, n, d]) => [v, tr(n), tr(d)])];
  const cust = eff.tpl === 'custom' ? eff.custom || {} : Object.fromEntries(NTF_WORK.map(r => [r, 1]));
  const pOpt = (p, v, n) => `<option value="${v}" ${(p.own?.tpl || '') === v ? 'selected' : ''}>${esc(n)}</option>`;
  const people = (j.people || []).map(p => `<div class="mrow ntfp"><span class="n">${esc(p.name)}</span><select data-ntfu="${p.user_id}" aria-label="${esc(tr('Notifications for {0}', p.name))}">${pOpt(p, '', scope === 'list' ? tr('As the project') : tr('As the folder'))}${NTF_TPLS.filter(([v]) => v !== 'custom' || p.own?.tpl === 'custom').map(([v, n]) => pOpt(p, v, tr(n))).join('')}</select></div>`).join('');
  return `<div class="shint lhint keep">${esc(tr('The most the other people get as a push about this. They can make it quieter, not louder; their News list stays complete.') + ' ' + tr('New shares start with “{0}”.', ntfName(j.default || 'read')))}</div>
    <div class="ntfopts" role="radiogroup" aria-label="${esc(tr('Notifications for members'))}">${opts.map(([v, n, d]) => `<label class="ntfopt"><input type="radio" name="ntf-tpl" value="${v}" ${cur === v ? 'checked' : ''}><span><b>${esc(n)}</b><small class="muted">${esc(d)}</small></span></label>`).join('')}</div>
    <div class="ntfcust" ${eff.tpl === 'custom' && cur !== 'inherit' ? '' : 'hidden'} role="group" aria-label="${esc(tr('Custom selection'))}">${NTF_CUSTOM.map(r => `<label class="chkl"><input type="checkbox" data-ntfc="${r}" ${cust[r] ? 'checked' : ''}> ${esc(ntfRowName(r))}</label>`).join('')}</div>
    ${scope === 'folder' && j.lists_own ? `<div class="shint keep">${esc(trn('{0} project in this folder has its own template.', '{0} projects in this folder have their own template.', j.lists_own))} <button type="button" class="btn sm" data-ntf="reset">${esc(tr('Use the folder’s for all'))}</button></div>` : ''}
    ${people ? `<details class="sdet ntfppl"><summary>${esc(tr('Per person'))}</summary><div class="members">${people}</div></details>` : ''}`;
}
const ntfUrl = (scope, key) => scope === 'list' ? `/api/lists/${key}/notify-template` : '/api/folders/notify-template?folder=' + encodeURIComponent(key);
async function ntfLoad(box, scope, key, onSync) {
  let j; try { j = await api('GET', ntfUrl(scope, key)); } catch { box.innerHTML = ''; return null; }
  if (!box.isConnected) return null;
  const draw = jj => { box._j = jj; const open = !!$('.ntfppl', box)?.open; box.innerHTML = ntfHtml(jj, scope); if (open) { const d = $('.ntfppl', box); if (d) d.open = true; } onSync?.(jj); };
  draw(j);
  const put = async b => {
    try { const jj = await api('PUT', scope === 'list' ? ntfUrl(scope, key) : '/api/folders/notify-template', scope === 'list' ? b : {folder: key, ...b}); draw(jj); S.notifAsk = []; ntfAskSync(); toast(tr('Saved')); }
    catch { draw(box._j); }
  };
  const custNow = () => Object.fromEntries($$('[data-ntfc]', box).map(x => [x.dataset.ntfc, x.checked ? 1 : 0]));
  box.addEventListener('change', e => {
    const t = e.target;
    if (t.name === 'ntf-tpl') { put(t.value === 'inherit' ? {tpl: null} : t.value === 'custom' ? {tpl: 'custom', custom: custNow()} : {tpl: t.value}); return; }
    if (t.dataset.ntfc) { put({tpl: 'custom', custom: custNow()}); return; }
    if (t.dataset.ntfu) put({user_id: +t.dataset.ntfu, tpl: t.value || null});
  });
  box.addEventListener('click', async e => {
    if (!e.target.closest('[data-ntf="reset"]')) return;
    if (!await askConfirm(tr('All projects in this folder follow the folder’s template?'), tr('Their own templates for everyone are removed; templates per person stay.'), {ok: tr('Apply')})) return;
    put({reset_lists: true});
  });
  return j;
}
// the one-time question to owners of lists shared before 2.33 (kept on "Everything"): choose a template or keep it
function ntfAskSync() {
  const main = $('#main'); if (!main) return;
  const items = S.notifAsk || []; let bar = $('#ntfask');
  if (!items.length || S.me?.kid) { if (bar) barKeep(() => bar.remove()); return; }  // 2.940.0 (#5226): barKeep (render.js) - the view does not move
  const html = `${ic('bell', 's')}<span class="annt">${esc(tr('Your shared projects still notify everyone about everything. You can now limit that per project or folder.'))}</span><span class="ntfaskb"><button type="button" class="btn sm pri" data-act="ntfask-choose">${esc(tr('Select template'))}</button><button type="button" class="btn sm" data-act="ntfask-keep">${esc(tr('Keep as it is'))}</button></span>`;
  if (!bar || bar.innerHTML !== html) barKeep(() => { if (!bar) { bar = document.createElement('div'); bar.id = 'ntfask'; bar.className = 'annbar ntfask'; bar.setAttribute('role', 'region'); bar.setAttribute('aria-label', tr('Notifications for members')); const ab = $('#annbar'); if (ab) ab.after(bar); else main.prepend(bar); } bar.innerHTML = html; });
}
document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-act="ntfask-choose"], [data-act="ntfask-keep"]'); if (!b) return;
  const items = S.notifAsk || [];
  const open = it => it.kind === 'folder' ? folderPeopleModal(it.folder, {focus: 'ntf'}) : shareModal(it.id, {focus: 'ntf'});
  if (b.dataset.act === 'ntfask-choose' && items.length > 1) {
    menu(b, items.map(it => ({label: it.kind === 'folder' ? fDisp(it.folder) : it.name, icon: it.kind === 'folder' ? 'folder' : 'list', fn: () => open(it)})));
    return;
  }
  if (b.dataset.act === 'ntfask-choose') { if (items[0]) open(items[0]); return; }  // answered once a template is chosen (the server notes it)
  try { await api('POST', '/api/notify-templates/asked', {}); } catch { return; }
  S.notifAsk = []; ntfAskSync();
});
// 2.36.0 (#1117): with line icons in the sidebar (the default) the list dialog shows and offers line icons too; each one stands
// for an emoji that stays the start of the name, so the other sidebar styles (emoji, dot) keep working with the same lists
const sbiEmo = e => { const k = e && sbiMode() === 'line' ? sbiIconFor(e) : ''; return k ? ic(k, 'l') + `<span class="sr">${esc(e)}</span>` : e; };  // the emoji stays the button's name
function sbiGrid() {  // the grid's emojis: in line mode one per line icon (the first emoji that maps to it), else the emoji set
  if (sbiMode() !== 'line') return EMOJIS;
  const seen = new Set(), out = [];
  for (const e of [...EMOJIS, ...AUTO_EMO.map(x => x[0]), ...Object.values(SBI_EMO).map(x => x.split(' ')[0])]) {
    const k = sbiIconFor(e); if (k && !seen.has(k)) { seen.add(k); out.push(e); }
  }
  return out;
}
// 2.411.0 (#3516): a new project in a folder with a project type (folderPtype) starts as that type with its standard sections,
// chosen in the dialog (the person can pick another one; once picked by hand a folder change keeps it)
function lmFolderPtype(md, folder) {
  if (!md || $('.lhdr', md) || md._ptUser || !$('.ptcards', md)) return;
  const t = folderPtype(folder), card = $(`.ptcard[data-pt="${t}"]`, md);
  if (!card) return;
  $$('.ptcard', md).forEach(x => { x.classList.toggle('on', x === card); x.setAttribute('aria-checked', x === card); });
  $('.ptsecs', md).hidden = !PTYPE_SECS[t]; $('#l-ptsecsl', md).textContent = ptSecsLine(t);
  $('.ptbug', md).hidden = t !== 'software';  // 2.473.0 (#3378)
  if ($('#l-ptsecs', md)) $('#l-ptsecs', md).checked = !!t;
  if ($('#l-tickets', md)) { $('#l-tickets', md).checked = t === 'software'; $('#l-tickets', md).closest('.row').hidden = !!t; }
}
// 2.1.2 (#349): hand a list to another person. j = GET /api/lists/{id}/owner (mode owner | takeover, candidates: active
// people, members first with their role). Two steps: pick the person, then confirm.
async function ownerModal(lid, name, j, done) {
  const take = j.mode === 'takeover', cands = j.candidates || [];
  if (!cands.length) { toast(tr('There is no other active person to hand it to')); return; }
  const def = (take ? cands.find(c => S.me && c.id === S.me.id) : cands.find(c => c.role)) || cands[0];
  const md = modal(`<h3>${esc(take ? tr('Take over “{0}”', name) : tr('Transfer ownership of “{0}”', name))}</h3>
    <div class="row"><label for="ow-to">${tr('New owner')}</label><select id="ow-to">${cands.map(c => `<option value="${c.id}" ${c.id === def.id ? 'selected' : ''}>${esc(c.name)}${S.me && c.id === S.me.id ? ' ' + tr('(me)') : ''}${c.role ? ' · ' + esc(roleLabel(c.role)) : ''}</option>`).join('')}</select></div>
    <div class="shint keep">${esc(take ? tr('The new owner can rename, archive and delete the project and decides who is in it. {0} stays in the project: an agent as a member, a person as a project admin.', j.owner?.name || '')
      : tr('The new owner can rename, archive and delete the project and decides who is in it. You stay in the project as a project admin. Agents cannot own projects.'))}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="ok">${take ? tr('Take over') : tr('Transfer')}</button></div>`);
  md.classList.add('owmodal');
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const to = cands.find(c => c.id === +$('#ow-to', md).value); if (!to) return;
    if (!await askConfirm(tr('Make {0} the owner of “{1}”?', to.name, name), take ? '' : tr('Only the new owner can hand it back.'), {ok: take ? tr('Take over') : tr('Transfer ownership'), danger: !take})) return;
    b.disabled = true;
    try { await api('POST', `/api/lists/${lid}/owner`, {user_id: to.id}); } catch { b.disabled = false; return; }
    md.remove(); toast(tr('{0} is now the owner of “{1}”', to.name, name));
    done && done(); await load(); render();
  });
}
// Settings > Administration: the lists nobody can manage (owner = an agent or a disabled user), with "Take over"
const orphHtml = () => `<h4 id="s-orph-h">${tr('Projects owned by agents or disabled accounts')}</h4>
  <div class="shint">${tr('Nobody can manage who is in these projects: agents cannot share, disabled users cannot sign in. Take a project over for yourself or hand it to another person.')}</div>
  <div class="members" id="s-orph"><div class="muted mhint">${tr('Loading…')}</div></div>`;
async function orphDraw(md) {
  const box = $('#s-orph', md); if (!box) return;
  let j; try { j = await calReq('GET', '/api/admin/lists/orphaned'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  box.innerHTML = j.lists.length ? j.lists.map(l => `<div class="mrow" data-olid="${l.id}">${av(l.owner_id, l.owner_name)}<span class="n"><b>${esc(listName(l.name))}</b>
      <small class="muted">${esc(l.reason === 'agent' ? tr('owned by the agent {0}', l.owner_name) : tr('owned by the disabled account {0}', l.owner_name))} · ${esc(trn('{0} member', '{0} members', l.members))} · ${esc(trn('{0} task', '{0} tasks', l.tasks))}${l.archived ? ' · ' + esc(tr('archived')) : ''}</small></span>
      <button class="btn sm" data-orph="${l.id}">${ic('user', 's')} ${tr('Take over')}</button></div>`).join('')
    : `<div class="muted mhint">${tr('None: every project is owned by an active person.')}</div>`;
}
function orphWire(md) {
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-orph]'); if (!b) return;
    const j = $('#s-orph', md)?._j, l = j?.lists.find(x => x.id === +b.dataset.orph); if (!l) return;
    ownerModal(l.id, listName(l.name), {mode: 'takeover', owner: {id: l.owner_id, name: l.owner_name}, candidates: j.candidates.filter(c => c.id !== l.owner_id)}, () => orphDraw(md));
  });
}
// Settings > Appearance: all per-device visual settings, applied instantly (no Save), with a live preview
const LOOK_KEYS = ['theme', 'density', 'densitySide', 'densityRows', 'densSideV', 'densRowsV', 'fsize', 'font', 'accent', 'pack', 'headShow', 'chatHuman', 'chatAgent', 'railLabels', 'wkEd', 'wkSt', 'wkW', 'ntW', 'split', 'splW', 'splR', 'splMin'];  // 2.1040.0 (#5813): splMin = split from window width (px)  // 2.742.0 (#4858): the split view (miniwin.js / splitview.js): on, width of the right half (rem), its route  // 2.599.0 (#4808): the default page width of knowledge pages / notes (chat.js pgw_*)  // 2.371.3 (#3152): the own reading style of knowledge pages  // 2.350.0 B (#3147): the knowledge editor (live preview / plain text)  // 2.319.0 B (#3288): app bar labels  // 2.233.0 C (#3196): chat colours  // 2.18.0: densSideV / densRowsV; 2.83.0 C (#1427): theme, header pictures, rings
// 2.143.0 D (#2155): the appearance follows the account (setting "look"), unless this device keeps its own (LS lookLocal).
// Every LOOK_KEYS change (LS.set / LS.del) is sent after a short pause; a state from the server is adopted when it differs.
let lookTimer = 0, lookApplying = false;
const lookLocal = () => LS.get('lookLocal', false) === true;
const lookSnap = () => Object.fromEntries(LOOK_KEYS.map(k => [k, LS.get(k, null)]).filter(([, v]) => v != null));
function lookQueue(k) {
  if (lookApplying || !LOOK_KEYS.includes(k) || typeof S === 'undefined' || !S.settings || lookLocal()) return;
  clearTimeout(lookTimer); lookTimer = setTimeout(lookPush, 800);
}
function lookPush(auto) {  // 2.1013.0 (#5773): auto = the device's look handed to the account (lookAdopt), no undo step
  lookTimer = 0; if (lookLocal() || !S.settings) return;
  const v = JSON.stringify(lookSnap()); S.settings.look = v;
  // 2.997.0 (#5704): the app's own sync of the look is no step of an entry: its group (X-Kalmido-Undo-Gid) leaves HIST.fresh
  // at once - else the next entry of an area without server steps (a new event) took it and Ctrl+Z put the look back instead
  api('PATCH', '/api/settings', {look: v, ...(auto === true ? {_auto: 1} : {})}).then(r => { const g = r?._ugid; if (g && typeof HIST === 'object') HIST.fresh = HIST.fresh.filter(f => f.gid !== g); }).catch(() => {});
}
function lookAdopt() {  // after a state load: first time the account has none -> upload this device's; otherwise the account wins
  if (lookLocal() || lookTimer || !S.settings) return;
  const v = S.settings.look || '';
  if (!v) { if (Object.keys(lookSnap()).length) lookPush(true); return; }
  let o; try { o = JSON.parse(v); } catch { return; }
  if (!o || typeof o !== 'object' || JSON.stringify(o) === JSON.stringify(lookSnap())) return;
  lookApplying = true;
  try { for (const k of LOOK_KEYS) { if (o[k] != null) LS.set(k, o[k]); else LS.del(k); } } finally { lookApplying = false; }
  applyTheme(); applyDensity(); applyLook(); o3c_meta();
  if (S.booted) render();
}
const THEMES = [['auto', N_('Automatic')], ['dark', N_('Dark')], ['light', N_('Light')]];
const DENSITIES = [['compact', N_('Compact')], ['comfortable', N_('Comfortable')], ['custom', N_('Custom|density')]];
const FSIZE_ORDER = ['s', 'm', 'l', 'xl'];
const zPct = z => `${Math.round(z * 100)} %`;
function lookHtml() {
  const on = (k, v) => `data-look="${k}" data-v="${v}" aria-pressed="${lookCur(k) === v}" class="${lookCur(k) === v ? 'on' : ''}"`;
  const seg = (k, opts) => `<div class="seg wrap" id="s-${k}" role="group">${opts.map(([v, n]) => `<button ${on(k, v)}>${tr(n)}</button>`).join('')}</div>`;
  return `<div class="lookpv" inert aria-hidden="true">
      <div class="lpv-head"><b>${tr('Today')}</b><span class="lpv-n">2</span></div>
      <div class="trow pr5"><span class="chk p5"></span><div class="tmain"><div class="ttl">${tr('Call the plumber about the kitchen tap')}</div><div class="meta">${rsy_pv(0) /* 2.56.1 (#1799) */}</div></div></div>
      <div class="trow pr1"><span class="chk p1"></span><div class="tmain"><div class="ttl">${tr('Renew the library books')}</div><div class="meta">${rsy_pv(1)}</div></div></div>
      <div class="lpv-foot"><span class="btn sm pri">${ic('plus', 's')} ${tr('Add task')}</span><span class="lpv-link">${tr('Show completed')}</span><span class="lpv-prio flag-5">${ic('flag', 's')}${tr('high')}</span></div>
    </div>
    ${o3c_packHtml() /* 2.83.0 C (#1427): themes (listhead.js) */}
    <h4>${tr('Colour scheme')}</h4>
    <div class="row">${seg('theme', THEMES)}</div>
    <h4>${tr('Density')}</h4>
    <div class="row">${seg('density', DENSITIES)}</div>
    ${densityMode() === 'custom' ? ['side', 'rows'].map(k => `<div class="row lkdens"><label class="lkdl" for="s-dens-${k}">${k === 'side' ? tr('Sidebar row spacing') : tr('Task row spacing')}</label><span class="lkA" aria-hidden="true">${tr('tight|spacing')}</span><input type="range" id="s-dens-${k}" data-dens="${k}" min="0" max="100" step="1" value="${densV(k)}" aria-valuetext="${densV(k)} %"><span class="lkA" aria-hidden="true">${tr('airy|spacing')}</span><output id="s-dens-${k}-v" for="s-dens-${k}">${densV(k)} %</output></div>`).join('') : ''}
    <div class="shint">${tr('Custom: a slider each for the sidebar and the tasks. Default: comfortable on phones, compact on computers.')}</div>
    <h4>${tr('Font size')}</h4>
    <div class="row lkfs"><span class="lkA" aria-hidden="true">A</span><input type="range" id="s-fsize" min="${FS_MIN}" max="${FS_MAX}" step="5" value="${fsPct()}" aria-label="${esc(tr('Font size'))}" aria-valuetext="${fsPct()} %"><span class="lkA lkA2" aria-hidden="true">A</span><output id="s-fsv" for="s-fsize">${fsPct()} %</output><button class="btn sm" data-m="fs-reset" ${fsPct() === 100 ? 'disabled' : ''}>${tr('Reset (100 %)')}</button></div>
    <div class="shint">${tr('Scales the whole interface: text, rows, icons, spacing and dialogs.')}</div>
    ${tch_standalone() ? `<div class="shint">${tr('In the installed app, zooming with two fingers is off. For bigger text, set the font size here.')}</div>` : ''}
    ${vpLookHtml() /* 2.310.0 (#3270) */}
    ${sbb_labelsHtml() /* 2.319.0 B (#3288) */}
    <h4>${tr('Font')}</h4>
    <div class="lkopts lkfont" id="s-font" role="group">${LOOK.font.map(([v, n]) => `<button ${on('font', v)}><span class="lkAa lkf-${v}">Aa</span><span class="lkn">${tr(n)}</span></button>`).join('')}</div>
    <div class="shint">${tr('Atkinson Hyperlegible is especially easy to read.')}</div>
    <h4>${tr('Accent colour')}</h4>
    <div class="lkopts lkacc" id="s-accent" role="group">${LOOK.accent.map(([v, n, d, l]) => `<button ${on('accent', v)} style="--sw-d:${d};--sw-l:${l}" title="${tr(n)}"><i class="lksw"></i><span class="lkn">${tr(n)}</span></button>`).join('')}</div>
    ${lkChatHtml() /* 2.233.0 C (#3196) */}
    ${o3c_lookHtml() /* 2.83.0 C (#1427): header pictures + progress rings */}
    <div class="row"><label class="chkl"><input type="checkbox" id="s-look-local" ${lookLocal() ? 'checked' : ''}> ${tr('Only on this device')}</label></div>
    <div class="shint">${tr('Off: your appearance is saved to your account and used on all your devices. On: this device keeps its own and neither sends nor receives.')}</div>
    <div class="row lkreset"><button class="btn sm" data-m="look-reset">${ic('undo', 's')} ${tr('Reset to defaults')}</button></div>`;
}
// 2.310.0 (#3270): the view of this device (icons.js vpMode / stableViewport): Automatic / Phone / Computer, kept only in
// this browser (LS vmode, in LS_KEEP, not part of the account's appearance), with a grey line of what the screen reports
const VP_NAMES = {auto: N_('Automatic'), phone: N_('Phone|device'), desktop: N_('Computer')};
const vpInfo = () => tr('Screen {0} × {1} px · layout width {2} px · view: {3}', screen.width, screen.height, document.documentElement.clientWidth || innerWidth, isMobile() ? tr('Phone|device') : tr('Computer'));
function vpLookHtml() {
  const cur = vpMode();
  return `<h4>${tr('View on this device')}</h4>
    <div class="row"><div class="seg wrap" id="s-vmode" role="group" aria-label="${esc(tr('View on this device'))}">${VP_MODES.map(v => `<button data-vmode="${v}" aria-pressed="${cur === v}" class="${cur === v ? 'on' : ''}">${tr(VP_NAMES[v])}</button>`).join('')}</div></div>
    <div class="shint">${tr('Automatic: from 768 px wide (a tablet, an unfolded foldable) the computer view, phones the phone view. Computer: the computer view, scaled down to fit.')}</div>
    <div class="shint vpinfo" id="s-vpinfo">${esc(vpInfo())}</div>`;
}
function vpSet(md, v) {
  if (v === 'auto') LS.del('vmode'); else LS.set('vmode', v);
  stableViewport();  // the layout width changes; the (max-width:767px) listener (detail.js) renders the new layout
  lookRedraw(md, `[data-vmode="${v}"]`);
  const upd = () => { const el = $('#s-vpinfo', md); if (el) el.textContent = vpInfo(); };
  addEventListener('resize', upd, {once: true}); requestAnimationFrame(() => requestAnimationFrame(upd));
}
// 2.233.0 C (#3196): chat bubble colours of people / agents (the same palette as the accent; own messages keep the accent), with a live preview
function lkChatHtml() {
  const on = (k, v) => `data-look="${k}" data-v="${v}" aria-pressed="${lookCur(k) === v}" class="${lookCur(k) === v ? 'on' : ''}"`;
  const pick = (k, id) => `<div class="lkopts lkacc" id="${id}" role="group" aria-label="${esc(tr(k === 'chatHuman' ? 'Messages from people' : 'Messages from agents'))}">${LOOK[k].map(([v, n, d, l]) => `<button ${on(k, v)} style="--sw-d:${d || 'var(--bg3)'};--sw-l:${l || 'var(--bg3)'}" title="${tr(n)}"><i class="lksw${d ? '' : ' lkswd'}"></i><span class="lkn">${tr(n)}</span></button>`).join('')}</div>`;
  return `<h4>${tr('Chat')}</h4>
    <div class="shint">${tr('Own messages keep the accent colour.')}</div>
    <div class="lkcpv" inert aria-hidden="true"><div class="cmsg ag"><div class="cbub">${tr('Can you take a look at this?')}</div></div><div class="cmsg ag agc"><div class="cbub">${tr('Done, it is in the list.')}</div></div><div class="cmsg me"><div class="cbub">${tr('Thanks!')}</div></div></div>
    <h5 class="lkch">${tr('Messages from people')}</h5>${pick('chatHuman', 's-chatHuman')}
    <h5 class="lkch">${tr('Messages from agents')}</h5>${pick('chatAgent', 's-chatAgent')}`;
}
const lookCur = k => k === 'theme' ? LS.get('theme', 'auto') : k === 'density' ? densityMode() : k === 'densitySide' ? sideDensityPref() : k === 'densityRows' ? densityPref() : k === 'fsize' ? fsPct() : lookPref(k);
function lookRedraw(md, focusSel) {  // re-render the pane (states + preview) and keep the keyboard focus
  const p = $('#s-lookin', md); if (!p) return;
  p.innerHTML = lookHtml();
  if (focusSel) $(focusSel, p)?.focus();
}
