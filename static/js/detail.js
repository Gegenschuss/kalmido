/* Kalmido web client: The detail panel of a task.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ detail panel
let saveTimers = {};
function openDetail(id) {
  if (S.me?.kid) return;  // 2.19.0: a child ticks in its own view, no task panel
  const other = S.sel !== id;
  if (other) { S.editLink = false; S.cedit = null; S.mp = null; recentPush('t', id); wpOpened(id); }
  S.sel = id; S.editContent = false;
  const d = $('#detail');
  d.classList.remove('hidden');
  $('#app').classList.add('detail-open'); fitLayout();
  renderDetail();
  if (other) d.scrollTop = 0;  // 2.18.0 review (R7): a different task starts at its top, not at the previous one's scroll position
  requestAnimationFrame(() => d.classList.add('open'));
  // 2.16.0 (#473): the panel is a named region; opened with the keyboard (Enter / o on a row) or on a phone (it covers the
  // list) it takes the focus, closing it gives the focus back to the row (closeDetail)
  d.setAttribute('aria-label', tr('Task details'));
  const kb = S.kbOpen; S.kbOpen = false;
  if (kb || isMobile()) setTimeout(() => { if (document && S.sel === id && !d.contains(document.activeElement)) { d.tabIndex = -1; try { d.focus({preventScroll: true}); } catch { d.focus(); } } }, 60);
  $$('.trow.sel').forEach(r => r.classList.remove('sel'));
  $$(`.trow[data-id="${id}"]`).forEach(r => r.classList.add('sel'));
  if (isMobile()) history.pushState({detail: id}, '', location.hash);
  if (cmtOn() && id > 0 && S.tl.id !== id) S.tl = {id};
  loadTimeline(id);
  loadTaskTime(id);
  if (S.dp.id !== id) S.dp = {id: null};
  loadDeps(id);
}
function closeDetail(fromPop) {
  flushSaves();
  const was = S.sel, a = document.activeElement, back = was && (!a || a === document.body || $('#detail').contains(a) || a.matches?.('.pgrip'));
  if (back) setTimeout(() => { if (!document) return; const t = $(`#view .trow[data-id="${was}"] .ttl[data-kt]`); const b = document.activeElement; if (t && !S.sel && (!b || b === document.body || !b.isConnected || $('#detail').contains(b) || b.matches?.('.pgrip'))) { rowRove(t); try { t.focus({preventScroll: true}); } catch { t.focus(); } } }, isMobile() ? 260 : 0);
  S.sel = null; S.tl = {id: null}; S.cedit = null; S.editLink = false; mentionClose();
  if ($('#stale.indet')) staleDraw();  // 2.13.2 (#478 F8): back to the bottom edge
  const d = $('#detail');
  d.classList.remove('open');
  $('#app').classList.remove('detail-open'); fitLayout();
  $$('.trow.sel').forEach(r => r.classList.remove('sel'));
  setTimeout(() => { if (!S.sel) d.classList.add('hidden'); }, isMobile() ? 230 : 0);
  if (isMobile() && !fromPop && history.state && history.state.detail) history.back();
  if (S.bellBack) { S.bellBack = false; setTimeout(() => { const b = $('#top .bell'); if (b && !S.sel && $('#pop').classList.contains('hidden')) bellPop(b); }, isMobile() ? 260 : 0); }  // 2.13.0 (#453 A5)
}
window.addEventListener('popstate', () => { if (S.sel && isMobile()) closeDetail(true); });
// U02 (owner decision 1), 2.8.0 (#434): sidebar + list + task panel side by side only while the list keeps ~420 px (Fold
// unfolded, small laptop windows, large font sizes). Otherwise the sidebar becomes a drawer: the header's menu button opens
// it as an overlay (like the phone drawer). An unfolded Fold (~904 px) keeps the sidebar next to the list.
const LIST_MIN_PX = 420;
function fitLayout(quiet) {
  const app = $('#app'); if (!app) return;
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, det = app.classList.contains('detail-open');
  // 2.13.2 (#478 N1): list | task | chat side by side. The panel's room comes off the whole app (#app, not only the list
  // area: the task panel used to sit under the chat with ~400 px empty next to it). Where list + task + chat do not fit,
  // the task takes the chat's place (body.chat-yield hides the panel, the task header's chat button / the agent pill /
  // closing the task bring it back)
  panelVars(); requestAnimationFrame(placeGrips);  // 2.16.0 (#639): the widths of the task panel and the chat per device
  const chatOn = document.body.classList.contains('chat-open') && !(isMobile() || innerWidth < 1000), chatW = chatOn ? Math.min(panelRem('chat') * rem, innerWidth * .4) : 0;
  const detR = panelRem('det');
  const yieldC = chatOn && det && innerWidth - chatW - detR * rem < LIST_MIN_PX;
  document.body.classList.toggle('chat-yield', yieldC);
  // 2.13.0: the open chat panel takes its room too: the sidebar folds into the drawer instead of squeezing the list
  const narrow = innerWidth - (15 + (det ? detR : 0)) * rem - (yieldC ? 0 : chatW) < LIST_MIN_PX;
  // 2.13.0 (#453 A15): below ~1100 px (an unfolded Fold, small windows) the sidebar can be folded away by hand (remembered
  // per device); the header's menu button opens it as a drawer then, like on a phone
  const on = !isMobile() && (narrow || (innerWidth < 1100 && !!LS.get('sideFold', false)));
  if (app.classList.contains('side-rail') === on) return;
  app.classList.toggle('side-rail', on);
  if (!on && $('#side').classList.contains('open') && !isMobile()) closeSide();
  if (S.settings && !quiet) renderTop();
}
let fitT = null;
window.addEventListener('resize', () => { clearTimeout(fitT); fitT = setTimeout(() => fitLayout(), 80); });
// ---- 2.16.0 (#639): grips between list | task | chat (desktop, an unfolded Fold): drag to make the task panel or the chat
// wider / narrower, remembered per device (localStorage), a double-click = the standard width. The grip is a separator
// for the keyboard and screen readers: ← → change the width by 1 rem (Shift: 4 rem), Home / End = narrowest / widest,
// Enter = the standard width. The list never gets narrower than LIST_MIN_PX; phones keep the full-screen panels.
const PW = {det: [25.5, 20, 48], chat: [26, 20, 44]};  // rem: standard, min, max
const panelRem = k => { const v = +LS.get('pw.' + k, 0); return v ? Math.max(PW[k][1], Math.min(PW[k][2], v)) : PW[k][0]; };
function panelVars() { const r = document.documentElement.style; r.setProperty('--detW', panelRem('det') + 'rem'); r.setProperty('--chatW', panelRem('chat') + 'rem'); }
function panelMax(k) {  // the widest the panel may get now, in rem (the list keeps LIST_MIN_PX)
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, app = $('#app');
  const side = app.classList.contains('side-rail') || isMobile() ? 0 : 15 * rem;
  const other = k === 'det' ? (document.body.classList.contains('chat-open') && !document.body.classList.contains('chat-yield') && innerWidth >= 1000 ? Math.min(panelRem('chat') * rem, innerWidth * .4) : 0)
    : (app.classList.contains('detail-open') ? panelRem('det') * rem : 0);
  const room = (innerWidth - side - other - LIST_MIN_PX) / rem;
  return Math.max(PW[k][1], Math.min(PW[k][2], k === 'chat' ? Math.min(room, innerWidth * .4 / rem) : room));
}
function panelSet(k, v, quiet) {
  const x = v == null ? null : Math.round(Math.max(PW[k][1], Math.min(panelMax(k), v)) * 4) / 4;
  if (x == null || x === PW[k][0]) LS.del('pw.' + k); else LS.set('pw.' + k, x);
  panelVars(); if (!quiet) fitLayout(); placeGrips();
}
function placeGrips() {
  if (typeof gripWatch === 'function') gripWatch();
  const want = {det: !isMobile() && $('#app')?.classList.contains('detail-open') && !$('#detail').classList.contains('hidden'),
    chat: !isMobile() && innerWidth >= 1000 && document.body.classList.contains('chat-open') && !document.body.classList.contains('chat-yield') && !!$('#achat:not(.hidden)')};
  for (const k of ['det', 'chat']) {
    let g = $('#pgrip-' + k);
    if (!want[k]) { if (g) g.hidden = true; continue; }
    if (!g) {
      g = document.createElement('div'); g.id = 'pgrip-' + k; g.className = 'pgrip'; g.dataset.k = k; g.tabIndex = 0;
      g.setAttribute('role', 'separator'); g.setAttribute('aria-orientation', 'vertical');
      document.body.appendChild(g); gripWire(g);
    }
    const el = k === 'det' ? $('#detail') : $('#achat'), r = el.getBoundingClientRect();
    g.hidden = !r.width;
    g.style.left = Math.round(r.left - 5) + 'px'; g.style.top = Math.round(r.top) + 'px'; g.style.height = Math.round(r.height) + 'px';
    const v = panelRem(k);
    g.setAttribute('aria-label', k === 'det' ? tr('Width of the task panel') : tr('Width of the chat'));
    g.setAttribute('aria-valuenow', String(v)); g.setAttribute('aria-valuemin', String(PW[k][1])); g.setAttribute('aria-valuemax', String(Math.round(panelMax(k) * 4) / 4));
    g.setAttribute('aria-valuetext', tr('{0} rem', String(v)));
    g.title = (k === 'det' ? tr('Width of the task panel') : tr('Width of the chat')) + ' · ' + tr('drag; double-click = standard width');
  }
}
function gripWire(g) {
  const k = g.dataset.k;
  g.addEventListener('dblclick', () => { g._dbl = Date.now(); clearTimeout(g._mt); panelSet(k, null); });
  g.addEventListener('keydown', e => {
    const step = e.shiftKey ? 4 : 1, v = panelRem(k);
    const to = {ArrowLeft: v + step, ArrowRight: v - step, Home: PW[k][1], End: panelMax(k)}[e.key];
    if (to != null) { e.preventDefault(); e.stopPropagation(); panelSet(k, to); announce(tr('{0} rem', String(panelRem(k)))); }
    else if (e.key === 'Enter') { e.preventDefault(); panelSet(k, null); announce(tr('Standard width')); }
  });
  g.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    e.preventDefault(); g.setPointerCapture?.(e.pointerId); g.classList.add('drag'); document.body.classList.add('pgdrag');
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const right = (k === 'det' ? $('#detail') : $('#achat')).getBoundingClientRect().right;
    const mv = ev => { panelSet(k, (right - ev.clientX) / rem, true); };
    let moved = false; const x0 = e.clientX;
    const mv2 = ev => { if (Math.abs(ev.clientX - x0) > 3) moved = true; if (moved) mv(ev); };
    const up = () => { g.removeEventListener('pointermove', mv2); g.classList.remove('drag'); document.body.classList.remove('pgdrag'); fitLayout(); placeGrips();
      // a tap without dragging: a small menu (the way without dragging, WCAG 2.5.7); a double-click resets instead
      if (!moved) { clearTimeout(g._mt); g._mt = setTimeout(() => { if (Date.now() - (g._dbl || 0) < 400) return; menu(g, [{label: tr('Wider'), icon: 'left', fn: () => panelSet(k, panelRem(k) + 4)}, {label: tr('Narrower'), icon: 'right', fn: () => panelSet(k, panelRem(k) - 4)}, {label: tr('Standard width'), icon: 'undo', fn: () => panelSet(k, null)}]); }, 320); } };
    g.addEventListener('pointermove', mv2); g.addEventListener('pointerup', up, {once: true}); g.addEventListener('pointercancel', up, {once: true});
  });
}
let gripRO = null;
try { gripRO = new ResizeObserver(() => placeGrips()); gripRO.observe(document.documentElement); } catch { /* old engine */ }
// 2.16.2: the panels change size without the page doing so (the chat opens next to the task): watch them too
const gripWatch = () => { if (!gripRO) return; for (const id of ['detail', 'achat']) { const el = document.getElementById(id); if (el && !el.dataset.gripRo) { el.dataset.gripRo = '1'; gripRO.observe(el); } } };
['transitionend'].forEach(t => document.addEventListener(t, e => { if (e.target?.id === 'detail' || e.target?.id === 'achat') placeGrips(); }));
function sideFold(on) { LS.set('sideFold', !!on); fitLayout(); closeSide(); render(); }
// 2.13.2 (#478 N3): the same within the phone layout: the docked "Add task" box of a tablet / an unfolded Fold in portrait
// (600-899 px) disappears on a narrower screen without crossing 899 px (Fold 880 -> 390): its text moves into the quick
// sheet; when the box comes back (unfolding) the text goes back into it
// (only on a width change: a keyboard changes the height alone and must never move what is being typed)
let qdT = 0, qdW = innerWidth;
window.addEventListener('resize', () => { clearTimeout(qdT); qdT = setTimeout(() => {
  const wch = innerWidth !== qdW; qdW = innerWidth;
  if (!S.booted || !wch) return;
  const qi = $('#qinput'), qs = $('#qsheet');
  if (qi && qi.value.trim() && !qi.offsetParent && !qs) {
    const v = qi.value, sel = [qi.selectionStart, qi.selectionEnd]; qi.value = '';
    openQuickSheet(v); S.qMoved = true;
    setTimeout(() => { try { $('#qsheet')?.setSelectionRange(...sel); } catch { /* no caret */ } }, 40);
  } else if (S.qMoved && qs && qi && qi.offsetParent) {
    const v = qs.value; closePop(); qi.value = v; updateChips(qi);
    requestAnimationFrame(() => { qi.focus({preventScroll: true}); try { qi.setSelectionRange(v.length, v.length); } catch { /* no caret */ } });
  }
}, 150); });
// 2.13.0 (#453 A15): folding / unfolding a Fold while typing switches between the phone and the tablet layout; the field
// that had the focus gets it back (same id), with its text and caret
try {
  matchMedia('(max-width:899px)').addEventListener('change', () => {
    const a = document.activeElement, id = a && a.id && editFocused() ? a.id : null, v = id ? a.value : null, sel = id ? [a.selectionStart, a.selectionEnd] : null;
    if (!S.booted) return;
    // 2.13.2 (#478 N3): a half-typed quick add moves along: the tablet's "Add task" box -> the phone's quick sheet (same
    // text, caret, focus = keyboard) when folding, and back into the box when unfolding
    const qv = $('#qinput')?.value || '', qsv = $('#qsheet')?.value || '', qf = id === 'qinput' || id === 'qsheet';
    render();
    if (qv && isMobile() && !$('#qinput')?.offsetParent) {
      const q0 = $('#qinput'); if (q0) q0.value = '';
      openQuickSheet(qv); S.qMoved = true;
      const n = $('#qsheet'); if (n && qf && sel) setTimeout(() => { try { n.setSelectionRange(...sel); } catch { /* no caret */ } }, 40);
      return;
    }
    if (qsv && !isMobile() && $('#qinput')) {
      closePop(); const n = $('#qinput'); n.value = qsv; updateChips(n);
      if (qf) requestAnimationFrame(() => { n.focus({preventScroll: true}); try { n.setSelectionRange(...(sel || [qsv.length, qsv.length])); } catch { /* no caret */ } });
      return;
    }
    if (!id) return;
    requestAnimationFrame(() => { const n = document.getElementById(id); if (!n || !n.offsetParent) return; if (n.value !== v && v != null) n.value = v; try { n.focus({preventScroll: true}); if (sel) n.setSelectionRange(...sel); } catch { /* not a text field */ } });
  });
} catch { /* old browsers */ }
function taskById(id) { return S.tasks.get(id) || (S.extra || []).find(t => t.id === id); }
// 2.0.6 (#316 / #322): the task panel below the title and the description, top to bottom; the comments and
// the history come last, the comment box stays at the bottom edge of the panel (sticky, see cmComposer())
const DETAIL_ORDER = ['family', 'life', 'subtasks', 'deps', 'links', 'tags', 'attachments', 'paperless', 'fields', 'custom', 'time', 'code', 'history', 'comments'];  // code: 2.2.0 (#271)  // history: private lists only (2.0.7)
// 2.7.2 (#424): where a task lives, at the top of its panel: Folder › List › Section › (parent task). Every part jumps
// there (the list, scrolled to the section / the parent) and closes the bell's dropdown. Only lists the viewer has.
function crumbsHtml(t, l, parent) {
  if (!l || t.id <= 0) return '';
  const sec = t.section_id && S.sections.find(x => x.id === t.section_id && x.list_id === l.id);
  const b = (k, id, icon, label, title) => `<button type="button" class="dcb" data-act="crumb" data-k="${k}" data-id="${esc(String(id))}" title="${esc(title || label)}">${icon ? ic(icon, 's') : ''}<span>${esc(label)}</span></button>`;
  const parts = [];
  if (l.folder && !l.is_inbox) parts.push(b('folder', l.folder, 'folder', fDisp(l.folder)));
  parts.push(b('list', l.id, l.is_inbox ? 'inbox' : 'list', lname(l)));
  if (sec) parts.push(b('sec', sec.id, '', sec.name));
  if (parent) parts.push(b('parent', parent.id, 'sub', parent.title));
  // 2.13.0: the task number, always: a tap copies the link to the task (#t/<id>)
  const num = `<button type="button" class="dcid" data-act="copy-id" data-id="${t.id}" title="${esc(tr('Copy the link to this task'))}" aria-label="${esc(tr('Task {0}: copy the link', '#' + t.id))}">#${t.id}</button>`;
  return `<nav class="dcrumbs" aria-label="${esc(tr('Where this task is'))}">${parts.join(`<span class="dcsep" aria-hidden="true">›</span>`)}${num}</nav>`;
}
async function copyTaskLink(id) {
  const url = `${location.origin}/#t/${id}`;
  try { if (isTouch() && navigator.share) { await navigator.share({url, title: '#' + id + ' ' + (taskById(id)?.title || '')}); return; } await navigator.clipboard.writeText(url); toast(tr('Link to {0} copied', '#' + id)); }
  catch { toast(url, null, 6000); }
}
function crumbGo(k, id) {
  closePop();
  const t = taskById(S.sel), l = t && listById(t.list_id); if (!l) return;
  if (k === 'folder') { if (isMobile()) closeDetail(); go('folder/' + encodeURIComponent(id)); return; }
  const where = k === 'sec' ? `#view .ghead[data-section="${+id}"]` : k === 'parent' ? `#view .trow[data-id="${+id}"]` : '';
  if (k === 'parent') { go(keyToHash('l:' + l.id)); setTimeout(() => { openDetail(+id); $(where)?.scrollIntoView?.({block: 'center'}); }, 120); return; }
  if (isMobile()) closeDetail();
  go(keyToHash(l.is_inbox ? 'inbox' : 'l:' + l.id));
  if (where) setTimeout(() => { const el = $(where); if (el) { if (el.classList.contains('closed')) el.click(); el.scrollIntoView?.({block: 'start'}); } }, 150);
}
// 2.18.0 (#408 F): a NEW bug ticket (open, created in the last 30 minutes) whose title shares at least 70 % of its words
// with an open ticket of the same list gets a small hint "Similar open ticket: #id title" (client only, one pass over
// the loaded tasks, only for such tickets). Dismissed per ticket, remembered on this device.
const DUP_MIN = 0.7, DUP_NEW_MS = 30 * 60000;
let DUP_OFF = null;
const dupWords = s => new Set(String(s || '').toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(w => w.length > 1));
function dupOf(t) {
  if (t.ttype !== 'bug' || t.status !== 0 || !(t.id > 0) || t.deleted_at || !ticketsOn(t.list_id)) return null;
  if (!t.created_at || Date.now() - Date.parse(t.created_at) > DUP_NEW_MS) return null;
  DUP_OFF ||= new Set(LS.get('dupOff', []));
  if (DUP_OFF.has(t.id)) return null;
  const w = dupWords(t.title); if (!w.size) return null;
  let best = null, bs = 0;
  for (const x of S.tasks.values()) {
    if (x.id === t.id || x.id <= 0 || x.list_id !== t.list_id || x.status !== 0 || x.deleted_at || !x.ttype) continue;
    const v = dupWords(x.title); if (!v.size) continue;
    let n = 0; for (const a of w) if (v.has(a)) n++;
    const sc = n / Math.max(w.size, v.size);
    if (sc >= DUP_MIN && (sc > bs || (sc === bs && x.id < best.id))) { bs = sc; best = x; }
  }
  return best;
}
function dupHintHtml(t) {
  const d = dupOf(t); if (!d) return '';
  return `<div class="ddup" role="note">${ic('copy', 's')}<span class="ddupt">${tr('Similar open ticket:')} <button type="button" class="linkbtn" data-act="open-id" data-id="${d.id}">#${d.id} ${esc(d.title.slice(0, 120))}</button></span><button type="button" class="iconbtn" data-act="dup-x" data-id="${t.id}" aria-label="${esc(tr('Dismiss'))}" title="${esc(tr('Dismiss'))}">${ic('x', 's')}</button></div>`;
}
function renderDetail() { return keepFocus($('#detail'), renderDetail0); }
function renderDetail0() {
  const t = taskById(S.sel); if (!t) return;
  const l = listById(t.list_id);
  const kids = children(t.id);
  const parent = t.parent_id && S.tasks.get(t.parent_id);
  const secs = S.sections.filter(s => s.list_id === t.list_id);
  const dueTxt = t.due ? dueLabel(t) : tr('Date');
  const mdMode = t.content && !S.editContent;
  const ro = !canEdit(t), shared = l && l.shared;
  // U07 (owner decision 3) applied to the checklist type; 2.7.2 (#414): the type is gone, every item is a full task
  const ck = false;
  // 2.0.6 (#315): comments everywhere (module "comments"), also in private lists and without collaboration (personal
  // notes); never in checklists. Replaces U18 (comments only in shared lists). Without comments a private task shows
  // only "+ Comment"; a shared list with collaboration keeps the whole section (its history of changes lives there)
  const ncm = S.tl.id === t.id && S.tl.comments ? S.tl.comments.length : t.comment_count || 0;
  // the list of comments shows once there is something in it (comments; in shared lists the history; elsewhere the changes
  // others made); the box itself is always there (sticky at the bottom), a single line until it is used
  const cmOk = cmtOn() && t.id > 0 && !ck && !t.context, cm = cmOk && (ncm || cmSocial(t) || tlForeign(t).length) ? 'full' : '';
  // 2.0.7: private lists with collaboration keep the folded "History" of 2.0.5 (every change, mine included, the
  // import line too); it stays out of the notes above, so they have no activity noise
  const hist = collab() && t.id > 0 && !ck && !t.context && !shared;
  const mdOpen = !ro && !ck && t.content && /^\s*[-*]\s+\[ \]\s*\S/m.test(t.content) && depthOf(t) < 2;
  // 2.0.2 (#242): the comments sit right below the description, folded to the newest one (per device); long descriptions
  // fold after ~8 lines; phones get "Details | Comments" on top
  const mdLong = mdMode && mdIsLong(t.content), mdClamp = mdLong && !(S.mdMore || new Set()).has(t.id);
  const dtab = cm === 'full' && isMobile() ? LS.get('dTab', 'details') : 'details';
  // 2.18.0 (#430): a milestone (no subtasks; its own section with progress, burndown, release notes) / the milestone a task
  // of a list with milestones belongs to (open ones + the current one)
  const msT = isMs(t), msSel = !msT && !t.context ? msOfList(t.list_id).filter(m => m.status === 0 || m.id === t.milestone_id) : [];
  const msTog = !t.context && (msT || (isProject(t.list_id) && !t.parent_id && !kids.length && t.id > 0));
  // 2.0.6 (#316 / #322): the order of the sections below the description, in one place
  const SEC = {
    subtasks: ck || msT ? '' : `<div class="dsec subsec"><h5>${isOcc(t) && famOn() ? tr('Gift ideas') : tr('Subtasks')}</h5><div class="subs">${kids.map(k => taskRow(k, {compact: true, subRow: true})).join('')}
        ${ro ? '' : depthOf(t) < 2 ? `<div class="subadd">${ic('plus', 's')}<input id="d-sub" placeholder="${isOcc(t) && famOn() ? tr('Add a gift idea') : tr('Add subtask')}" aria-label="${esc(isOcc(t) && famOn() ? tr('Add a gift idea') : tr('Add subtask'))}" enterkeyhint="done"></div>` : `<div class="muted" style="font-size:var(--fs-s);padding:.25rem">${tr('At most 3 levels')}</div>`}</div></div>`,
    comments: cm === 'full' ? `<div class="dsec cmsec ${cmtNew() ? 'cmnew' : ''}" id="d-tl">${timelineHtml(t)}</div>` : '',
    history: hist ? `<details class="dsec cmsec cmro" id="d-hist"><summary><span>${tr('History')}</span></summary><div class="cms" id="d-hist-items">${S.tl.id === t.id ? histItems() : `<div class="muted cmempty">${tr('Loading…')}</div>`}</div></details>` : '',
    deps: ck ? '' : `${t.id > 0 && dFor(t) && !t.context ? `<div class="dsec depsec" id="d-deps">${depsHtml(t)}</div>` : waitExtHtml(t, ro, true)}`,  // 2.22.0 (#686)
    tags: ck ? '' : `<div class="dsec"><h5>${tr('Tags')}${shared && collab() && t.tags.length ? ` <span class="muted h5note">${ic('user', 's')} ${tr('= only visible to you')}</span>` : ''}</h5>${tagEditHtml(t, ro)}</div>`,
    attachments: ck ? '' : `<div class="dsec attsec"><h5>${tr('Attachments')}</h5><div class="atts">${(t.attachments || []).map(attHtml).join('')}
        ${t.id > 0 && !ro ? `<label class="attadd" title="${esc(isTouch() ? tr('Images, PDFs, documents') : tr('Images, PDFs, documents') + ' · ' + tr('or drop files here / paste an image with Ctrl+V'))}">${ic('clip', 's')}<span>${tr('Add file')}</span><input type="file" id="d-file" multiple hidden></label>` : ''}</div>
</div>`,
    paperless: ck ? '' : `${plOn() || (t.paperless?.length && feat('paperless')) ? `<div class="dsec plsec"><h5>Paperless</h5><div class="plinks">${(t.paperless || []).map(plHtml).join('')}</div>
        ${t.id > 0 && !ro && plOn() ? `<button class="attadd" data-act="pl-search">${ic('archive', 's')}<span>${tr('Link document')}</span></button>` : ''}</div>` : ''}`,
    fields: ck ? (collab() && shared ? `<div class="dsec fields"><label for="d-assignee">${tr('Assignee')}</label><select id="d-assignee" data-sheet-av ${ro || !canAssign(t) ? 'disabled' : ''}><option value="">${tr('Nobody')}</option>${assigneeOpts(t, l)}</select>${myGroup(t.assignee_group_id) ? `<button class="btn sm dtake" data-act="take" type="button">${ic('check', 's')} ${tr('Take it')}</button>` : ''}</div>` : '') : `<div class="dsec fields">
        <label for="d-list">${tr('List')}</label><select id="d-list" data-sheet-ico="list" ${ro || !canEditList(t.list_id) ? 'disabled' : ''}>${S.lists.filter(x => (!x.archived && canEditList(x.id)) || x.id === t.list_id).map(x => `<option value="${x.id}" ${x.is_inbox ? 'data-ico="inbox"' : ''} ${x.id === t.list_id ? 'selected' : ''}>${esc(lname(x))}</option>`).join('')}</select>
        ${ticketsOn(t.list_id) ? `<label for="d-ttype">${tr('Type')}</label><select id="d-ttype" data-sheet-ico="bug" ${ro ? 'disabled' : ''}><option value="">${tr('None')}</option>${TTYPES.map(([k, n, i]) => `<option value="${k}" data-ico="${i}" ${t.ttype === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>` : ''}
        ${msTog ? `<label for="d-ms">${tr('Milestone')}</label><label class="chkl dmsl"><input type="checkbox" id="d-ms" ${msT ? 'checked' : ''} ${ro ? 'disabled' : ''}><i class="msd" aria-hidden="true"></i>${tr('This task is a milestone')}</label>` : ''}
        ${msSel.length ? `<label for="d-msel">${msTog ? tr('Belongs to') : tr('Milestone')}</label><select id="d-msel" data-sheet-ico="flag" ${ro ? 'disabled' : ''}><option value="">${tr('None')}</option>${msSel.map(m => `<option value="${m.id}" ${m.id === t.milestone_id ? 'selected' : ''}>${esc(m.title + (m.due ? ' · ' + fmtDateLoc(m.due) : ''))}</option>`).join('')}</select>` : ''}
        ${secs.length ? `<label for="d-sec">${tr('Section')}</label><select id="d-sec" data-sheet-ico="columns" ${ro ? 'disabled' : ''}><option value="">${tr('Unassigned')}</option>${secs.map(s => `<option value="${s.id}" ${s.id === t.section_id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>` : ''}
        <label>${tr('Link')}</label>${linkField(t, ro)}
        ${collab() && (shared || t.assignee_id) ? `<label for="d-assignee">${tr('Assignee')}</label><select id="d-assignee" data-sheet-av ${ro || !canAssign(t) ? 'disabled' : ''}><option value="">${tr('Nobody')}</option>${assigneeOpts(t, l)}</select>${myGroup(t.assignee_group_id) ? `<button class="btn sm dtake" data-act="take" type="button">${ic('check', 's')} ${tr('Take it')}</button>` : ''}` : ''}
        ${t.id > 0 && !t.context ? aiuTaskLine(t) : ''}
      </div>`,
    custom: ck ? '' : `${fieldsOf(t.list_id).length ? `<div class="dsec cfsec"><h5>${tr('Fields')}</h5><div class="fields cf">${fieldsOf(t.list_id).map(f => fieldEditor(f, t, ro)).join('')}</div></div>` : ''}`,
    time: ck ? '' : `${tFor(t) && t.id > 0 && !t.context ? `<div class="dsec tesec" id="d-time">${taskTimeHtml(t)}</div>` : ''}`,
    code: ck ? '' : codeHtml(t),
    family: ck ? '' : famDetailHtml(t, l, ro),  // 2.19.0 (#653)
    life: ck ? '' : lifeDetailHtml(t, l, ro),  // 2.22.0 (#663)
    links: ck ? '' : linksDetailHtml(t, ro)};  // 2.21.0 (#659 / #658): events + contacts of the task
  setHtml($('#detail'), `
    <div class="dtop">
      <button class="iconbtn back" data-act="close-detail" aria-label="${tr('Back')}">${ic('back')}</button>
      <button class="chk ${t.status === 2 ? 'on' : t.status === -1 ? 'wont' : 'p' + t.priority}${msT ? ' ms' : ''}" data-act="toggle" data-id="${t.id}" role="checkbox" aria-checked="${t.status === 2}" aria-label="${esc(msT ? tr('Complete milestone: {0}', t.title) : tr('Complete: {0}', t.title))}" title="${esc(kt(msT ? tr('Complete milestone') : tr('Complete task'), 'x'))}" ${ro ? 'disabled' : ''}>${t.status === 2 ? ic('check') : ''}</button>
      ${ck ? '' : `<button class="dchip ${t.due ? 'set ' + dueClass(t) : ''}" data-act="date" data-id="${t.id}" title="${esc((t.due ? dueTxt + ' · ' : '') + kt(tr('Change date'), 'd'))}" ${ro ? 'disabled' : ''}>${ic('cal', 's')}<span class="dct">${dueTxt}</span>${t.repeat ? ' ' + ic('repeat', 's') : ''}${t.reminders && t.due ? ' ' + ic('bell', 's') : ''}</button>`}
      ${ck || ro ? '' : [[0, 'sun', tr('Today')], [1, 'sunrise', tr('Tomorrow')]].map(([n, i, lab]) => `<button class="iconbtn dq ${t.due === addDays(today(), n) ? 'on' : ''}" data-act="due-q" data-d="${n}" data-id="${t.id}" title="${esc(kt(tr('Due: {0}', lab), n ? 'Shift+T' : 't'))}" aria-label="${esc(tr('Due: {0}', lab))}">${ic(i, 's')}<span class="dql">${esc(lab)}</span></button>`).join('')}
      ${ck ? '' : '<span class="dbr" aria-hidden="true"></span>'}<span class="spacer"></span>
      ${ro ? (t.context ? `<span class="rotag" title="${esc(tr('The main task of a subtask assigned to you: read-only, without notes, files and comments'))}">${ic('sub', 's')}${tr('Context')}</span>`
        : `<span class="rotag" title="${esc(tr('View only, shared by {0}', l?.owner_name || ''))}">${ic('eye', 's')}${tr('View only')}</span>`) : `${ck ? '' : `<button class="iconbtn ${t.pinned ? 'on' : ''}" data-act="pin" data-id="${t.id}" title="${t.pinned ? tr('Unpin') : tr('Pin')}" aria-label="${tr('Pin')}" aria-pressed="${!!t.pinned}">${ic('pin')}</button>
      <button class="iconbtn ${t.priority ? 'flag-' + t.priority : ''}" data-act="prio" data-id="${t.id}" aria-haspopup="menu" title="${esc(tr('Priority') + ': ' + prioWord(t.priority))}" aria-label="${esc(tr('Priority') + ': ' + prioWord(t.priority))}">${ic('flag')}</button>`}
      <button class="iconbtn" data-act="task-menu" data-id="${t.id}" title="${tr('More')}" aria-label="${tr('More')}">${ic('dots')}</button>`}
      <button class="iconbtn dchatb" data-act="chat-unyield" title="${esc(tr('Chat'))}" aria-label="${esc(tr('Chat'))}">${ic('bot')}</button>
      <button class="iconbtn dclose" data-act="close-detail" title="${tr('Close (Esc)')}" aria-label="${tr('Close (Esc)')}">${ic('x')}</button>
    </div>
    <div class="dbody ${ck ? 'ckbody' : ''} ${dtab === 'comments' ? 'dtab-c' : ''}">
      ${cm === 'full' && isMobile() ? `<div class="seg dtabs" role="tablist" aria-label="${esc(tr('Task'))}"><button role="tab" data-act="d-tab" data-tab="details" class="${dtab === 'details' ? 'on' : ''}" aria-selected="${dtab === 'details'}">${tr('Details')}</button><button role="tab" data-act="d-tab" data-tab="comments" class="${dtab === 'comments' ? 'on' : ''}" aria-selected="${dtab === 'comments'}">${tr('Comments')}<span class="c" id="d-tab-count">${ncm || ''}</span></button></div>` : ''}
      ${crumbsHtml(t, l, parent)}
      <div class="dtitle"><textarea id="d-title" rows="1" placeholder="${tr('Title')}" aria-label="${tr('Title')}" ${ro ? 'readonly' : ''}>${esc(t.title)}</textarea></div>
      ${!ck && t.due && (t.deadline || nagOf(t)) && t.status === 0 ? `<div class="ddl">${dlChip(t, 'big')}${nagOf(t) ? `<button type="button" class="dnag" data-act="date" data-id="${t.id}" title="${esc(tr('Change'))}">${ic('repeat', 's')}${esc(tr('Repeat reminder') + ': ' + nagLabel(nagOf(t)))}</button>` : ''}</div>` : ''}
      ${!ck && planOf(t) ? `<div class="dplan">${ic('clock', 's')}<span class="dplt">${esc(tr('Planned: {0}', planLabel(t)))}</span>${ro ? '' : `<button type="button" class="linkbtn" data-act="unplan" data-id="${t.id}">${tr('Unplan')}</button>`}</div>` : ''}
      ${t.waiting_at && !ck ? waitBar(t, ro) : ''}
      ${ck ? '' : approvalBar(t, ro)}
      ${ck || ro ? '' : dupHintHtml(t)}
      <div class="md ${mdMode ? '' : 'hidden'} ${mdClamp ? 'clamp' : ''}" id="d-md" title="${tr('Click to edit')}">${mdMode ? mdMentions(renderMd(t.content, false, {lid: t.list_id}), t) : ''}</div>
      ${mdLong ? `<button class="linkbtn mdmore" data-act="md-more" aria-expanded="${!mdClamp}">${mdClamp ? tr('Show more') : tr('Show less')}</button>` : ''}
      ${mdOpen && mdMode ? `<button class="btn sm mdsub" data-act="md-subtasks">${ic('sub', 's')} ${tr('Turn the open checklist items into subtasks')}</button>` : ''}
      <textarea id="d-content" class="dcontent ${mdMode ? 'hidden' : ''}" placeholder="${ck ? tr('Note') : tr('Description')}" aria-label="${ck ? tr('Note') : tr('Description')}" ${ro ? 'readonly' : ''}>${esc(t.content)}</textarea>
      ${msT && t.id > 0 ? `<div class="dsec mssec" id="d-ms">${msReportHtml(t)}</div>` : ''}
      ${DETAIL_ORDER.map(k => SEC[k]).join('\n      ')}
    </div>
    <div class="dbot">${cmOk && !(cm === 'full' && cmtNew()) ? cmComposer(t) : ''}<div class="dfoot"><span class="dfc">${t.status === 2 && t.completed_at ? tr('Completed {0}', new Date(t.completed_at).toLocaleString(LOCALE(), {dateStyle: 'medium', timeStyle: 'short'})) : tr('Created {0}', new Date(t.created_at).toLocaleString(LOCALE(), {dateStyle: 'medium', timeStyle: 'short'}))}</span>
      <span class="spacer"></span>
      ${ck ? '' : runItems().filter(x => x.tid === t.id).map(x => `<button class="drun k-${x.k}" data-act="run-pop" title="${esc(tr(RUN_KIND[x.k][1]))}">${ic(RUN_KIND[x.k][0], 's')}<span ${x.attr}>${x.txt}</span><span class="drl">${tr(RUN_KIND[x.k][1])}</span></button>`).join('')}
      </div></div>`);
  // 2.4.1 (#385): no Delete / Track time in the footer any more (Delete sat right below the comment box's Send on a phone);
  // both are in the task's "…" menu (Delete with undo), a running timer still shows here as its pill
  autosize($('#d-title')); autosize($('#d-content')); autosize($('#c-input'));
  if (isMobile() && $('#stale')) staleDraw();
}
// U17: the open "- [ ]" lines of a description become real subtasks (one undo step); ticked lines stay in the text
async function mdToSubtasks() {
  const t = taskById(S.sel); if (!t || !canEdit(t) || depthOf(t) >= 2) return;
  const keep = [], items = [];
  for (const ln of String(t.content || '').split('\n')) { const m = ln.match(/^\s*[-*]\s+\[ \]\s*(.*\S)/); if (m) items.push(m[1].trim()); else keep.push(ln); }
  if (!items.length) return;
  flushSaves();
  await histGroup(async () => {
    for (const title of items) await createTask({title: title.slice(0, 500), parent_id: t.id, list_id: t.list_id, section_id: t.section_id});
    await patchUndoable(t.id, {content: keep.join('\n').replace(/\n{3,}/g, '\n\n').trim()});
  }, trn('{0} checklist item of {1} is now a subtask', '{0} checklist items of {1} are now subtasks', items.length, qn(t.title.slice(0, 40))));
  S.editContent = false; renderDetail();
  offerUndo(trn('{0} subtask added', '{0} subtasks added', items.length), HIST.undo[HIST.undo.length - 1]);
}
function linkField(t, ro) {
  if (t.url && !S.editLink) return `<div class="linkf"><a class="linkchip" href="${esc(t.url)}" target="_blank" rel="noopener noreferrer" title="${esc(t.url)}">${ic('link', 's')}<span>${esc(urlHost(t.url))}</span></a>${ro ? '' : `<button class="iconbtn" data-act="link-edit" title="${tr('Edit link')}">${ic('edit', 's')}</button><button class="iconbtn" data-act="link-rm" title="${tr('Remove website link')}">${ic('x', 's')}</button>`}</div>`;
  return ro ? '<span class="muted">–</span>' : `<input id="d-url" type="url" inputmode="url" autocomplete="off" placeholder="https://…" aria-label="${esc(tr('Link'))}" value="${esc(t.url || '')}" enterkeyhint="done">`;
}
async function saveLink(v) {
  const t = taskById(S.sel); if (!t) return;
  v = (v || '').trim();
  if (v && !/^https?:\/\//i.test(v) && /^[\w-]+(\.[\w-]+)+(\/\S*)?$/.test(v)) v = 'https://' + v;  // "github.com/x" -> https://
  if (v && !validUrl(v)) { toast(tr('The link must start with http:// or https://')); return; }
  S.editLink = false;
  if ((t.url || '') === v) { renderDetail(); return; }
  await patchTask(t.id, {url: v || null});
}
