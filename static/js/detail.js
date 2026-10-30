/* Kalmido web client: The detail panel of a task.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ detail panel
let saveTimers = {};
function openDetail(id, o = {}) {
  if (S.me?.kid) return;  // 2.19.0: a child ticks in its own view, no task panel
  meEnd();  // 2.26.0 (#936): one task opened (a plain click, a title of the multi panel): the selection ends
  const other = S.sel !== id;
  if (other) { S.editLink = false; S.cedit = null; S.mp = null; recentPush('t', id); wpOpened(id); }
  S.sel = id; S.editContent = false;
  const d = $('#detail');
  d.classList.remove('hidden');
  $('#app').classList.add('detail-open'); fitLayout();
  renderDetail();
  if (other) { d.scrollTop = 0; if (d.classList.contains('dsplit')) $('.dbody', d).scrollTop = 0; }  // 2.18.0 review (R7): a different task starts at its top, not at the previous one's scroll position
  requestAnimationFrame(() => d.classList.add('open'));
  // 2.16.0 (#473): the panel is a named region; opened with the keyboard (Enter / o on a row) or on a phone (it covers the
  // list) it takes the focus, closing it gives the focus back to the row (closeDetail)
  d.setAttribute('aria-label', tr('Task details'));
  const kb = S.kbOpen; S.kbOpen = false;
  if (kb || isMobile()) setTimeout(() => { if (document && S.sel === id && !d.contains(document.activeElement)) { d.tabIndex = -1; try { d.focus({preventScroll: true}); } catch { d.focus(); } } }, 60);
  $$('.trow.sel').forEach(r => r.classList.remove('sel'));
  $$(`.trow[data-id="${id}"]`).forEach(r => r.classList.add('sel'));
  // 2.26.x (#953): touch tablets / the unfolded Fold too: the open task is its own history entry, so Back (Android's key /
  // gesture) closes only the task and keeps the view + sidebar; phones as before (one entry per opened task)
  if (isMobile()) history[o.replace && history.state?.detail ? 'replaceState' : 'pushState']({detail: id}, '', location.hash);  // 2.32.0 (#1071): a swipe to the next task replaces the entry (Back closes the task)
  else if (isTouch() && !history.state?.detail) history.pushState({detail: id}, '', location.hash);
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
  S.sel = null; S.nswTask = null; S.tl = {id: null}; S.cedit = null; S.editLink = false; mentionClose();
  if ($('#stale.indet')) staleDraw();  // 2.13.2 (#478 F8): back to the bottom edge
  const d = $('#detail');
  d.classList.remove('open');
  $('#app').classList.remove('detail-open'); fitLayout();
  $$('.trow.sel').forEach(r => r.classList.remove('sel'));
  setTimeout(() => { if (!S.sel) d.classList.add('hidden'); }, isMobile() ? 230 : 0);
  if ((isMobile() || isTouch()) && !fromPop && history.state && history.state.detail) history.back();  // closed by X / Back button: the entry goes
  if (S.bellBack) { S.bellBack = false; setTimeout(() => { const b = $('#kbar .bell, #top .bell'); if (b && !S.sel && $('#pop').classList.contains('hidden')) bellPop(b); }, isMobile() ? 260 : 0); }  // 2.13.0 (#453 A5)
}
// 2.152.7 (#2710): a Back step that lands on the open task's own entry ({detail: id}) leaves the panel open: closing a menu
// sheet in the panel (priority, assignee …) takes its own entry away again (backclose.js); should that step ever reach this
// listener, the task stays open instead of vanishing
window.addEventListener('popstate', e => { if (S.sel && (isMobile() || isTouch()) && e.state?.detail !== S.sel) closeDetail(true); });
// U02 (owner decision 1), 2.8.0 (#434): sidebar + list + task panel side by side only while the list keeps ~420 px (Fold
// unfolded, small laptop windows, large font sizes). Otherwise the sidebar becomes a drawer: the header's menu button opens
// it as an overlay (like the phone drawer). An unfolded Fold (~904 px) keeps the sidebar next to the list.
const LIST_MIN_PX = 420;
// 2.209.0 A (#2772): short of room the list may shrink further, down to LIST_SQUEEZE_PX (together with the task panel and
// the chat, see lay2209); LIST_MIN_PX stays the floor for dragging a grip
const LIST_SQUEEZE_PX = 320;
// 2.290.0 C (#3163): narrower than this with a task open, sidebar B shows no panel next to the list (layNow)
const SBB_FOUR_PX = 1200;
// 2.209.0 A (#2772): the order when the window gets too narrow (owner decision 23.10.2026: the sidebar floats LAST):
//   1. the chat, the task panel and the list get narrower together (each by its share of the room it has above its
//      minimum: panels down to PW[k][1], the list from LIST_MIN_PX down to LIST_SQUEEZE_PX)
//   2. still too narrow with a task open: the chat steps aside (chat-yield, the task takes its place), the rest as in 1.
//   3. still too narrow: the sidebar becomes the drawer (side-rail), first with the chat again, then without it.
// The stored widths (LS pw.*) stay as they are; only the widths in use (--detW / --chatW) shrink and come back with room.
// px in, px out: {yieldC, rail, det, chat, sq} (sq = shrunk); pure, so the tests can call it with any numbers
function lay2209({W, bar, barRail, side, det, detMin, chat, chatMin, fold, floor = LIST_SQUEEZE_PX}) {
  let sq = false;
  const fit = (room, ps) => {  // the panels' widths for this room, null = even the minimums do not fit
    const want = ps.reduce((a, p) => a + p.w, 0) + LIST_MIN_PX;
    if (room >= want) return ps.map(p => p.w);
    sq = true;
    if (floor < LIST_SQUEEZE_PX) {  // 2.350.0 D (#2750): a wide chat / sidebar: the list gives way first, down to the floor, then the panels
      const sum = want - LIST_MIN_PX, need = sum + floor - room, slack = ps.reduce((a, p) => a + Math.max(0, p.w - p.min), 0);
      return need <= 0 ? ps.map(p => p.w) : need > slack ? null : ps.map(p => p.w - Math.max(0, p.w - p.min) * need / slack);
    }
    const slack = ps.reduce((a, p) => a + Math.max(0, p.w - p.min), 0) + LIST_MIN_PX - floor, f = (want - room) / slack;
    return f > 1 ? null : ps.map(p => p.w - Math.max(0, p.w - p.min) * f);
  };
  const both = chat > 0 && det > 0, tries = [];
  if (!fold) { tries.push([false, false]); if (both) tries.push([true, false]); }
  tries.push([false, true]); if (both) tries.push([true, true]);
  for (const [y, r] of tries) {
    sq = false;
    const c = y ? 0 : chat, w = fit(W - (r ? barRail : bar + side), [{w: det, min: Math.min(det, detMin)}, {w: c, min: Math.min(c, chatMin)}]);
    if (w) return {yieldC: y, rail: r, det: w[0], chat: w[1], sq};
  }
  return {yieldC: both, rail: true, det: Math.min(det, detMin), chat: both ? 0 : Math.min(chat, chatMin), sq: true};
}
// 2.26.x: the fixed line at the bottom of the task panel: "Created by <name> on <date>" (agents by their name; no known
// creator: the date only), plus "Completed <date>" once done
function createdLine(t) {
  const f = v => fmtMoment(new Date(v));  // 2.368.0 B (#2982): one locale source
  const who = t.created_by ? personNameAny(t.created_by) : '';
  const c = !t.created_at ? '' : who ? tr('Created by {0} on {1}', who, f(t.created_at)) : tr('Created {0}', f(t.created_at));
  const d = t.status === 2 && t.completed_at ? tr('Completed {0}', f(t.completed_at)) : '';
  return [c, d].filter(Boolean).join(' · ');
}
// 2.13.0: the open chat panel takes its room too. 2.13.0 (#453 A15) / 2.161.2 A (#2607): the sidebar can be folded away
// by hand (remembered per device); the header's menu button opens it as a drawer then, like on a phone.
// 2.209.0 A (#2772): panels and list shrink first, the chat steps aside next, the sidebar floats last (lay2209). o = stored
// widths to try instead (rem, panelWish)
function layNow(o = {}) {
  const app = $('#app'), rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, det = app.classList.contains('detail-open');
  const chatOn = document.body.classList.contains('chat-open') && !(isMobile() || innerWidth < 1000), sbb = app.classList.contains('sb-b') ? srW() * rem : 0;
  const np = typeof sbb_noPan === 'function' && sbb_noPan();  // 2.224.0 A (#2817): an area without a panel: no panel width, the bar stays
  // 2.290.0 C (#3163): below SBB_FOUR_PX with a task open the panel of sidebar B folds into the drawer (never bar | panel |
  // list | task: an unfolded Fold 8 showed the project names as bare icons, titles broke after each word); the bar stays
  // and opens the drawer (its panel button, the open area's icon). Before (#2622) the bar stepped aside below 1140 px.
  const four = !!sbb && det && innerWidth < SBB_FOUR_PX;
  const L = lay2209({W: innerWidth, bar: sbb, barRail: sbb, side: np ? 0 : panelRem('side') * rem,
    det: det ? (o.det ?? panelRem('det')) * rem : 0, detMin: PW.det[1] * rem, chat: chatOn ? (o.chat ?? panelRem('chat')) * rem : 0, chatMin: PW.chat[1] * rem, floor: listFloor(), fold: (!!LS.get('sideFold', false) || four) && !np});
  return {L, rem, det, chatOn};
}
function fitLayout(quiet) {
  const app = $('#app'); if (!app) return;
  if (S.settings && app.classList.contains('sb-b') !== sbb_on()) renderSide();  // 2.152.2 (#2622): the bar of sidebar B comes and goes with the phone layout
  const det = app.classList.contains('detail-open'), rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  // 2.13.2 (#478 N1): list | task | chat side by side. The panel's room comes off the whole app (#app, not only the list
  // area: the task panel used to sit under the chat with ~400 px empty next to it). Where list + task + chat do not fit,
  // the task takes the chat's place (body.chat-yield hides the panel, the task header's chat button / the agent pill /
  // closing the task bring it back)
  const {L, chatOn} = layNow();
  const yieldC = L.yieldC && !isMobile();
  document.body.classList.toggle('chat-yield', yieldC);
  PWE.det = det && !isMobile() ? L.det / rem : null; PWE.chat = chatOn && !yieldC ? L.chat / rem : null; PWE.sq = L.sq && !isMobile();
  panelVars(); requestAnimationFrame(placeGrips);  // 2.16.0 (#639): the widths of the task panel and the chat per device
  const on = !isMobile() && L.rail;
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
// 2.26.0 (#932): the sidebar too (grip on its right edge; ← → reversed there: → = wider). Only next to the list: the drawer
// (side-rail) and phones keep their fixed widths.
// 2.350.0 D (#2750): chat and sidebar have no upper limit any more (1000 rem = never reached); the list keeps LIST_FLOOR_PX
// 2.406.0 A (#3504): usable minimums: the sidebar at least 14 rem, the list at least 18 rem (288 px); stored narrower widths
// are lifted on load (panelRem), a window too narrow for both folds the sidebar into the drawer (lay2209)
const PW = {det: [25.5, 20, 48], chat: [26, 20, 1000], side: [15, 14, 1000]};  // rem: standard, min, max
const LIST_FLOOR_PX = 288, OLD_MAX = {chat: 44, side: 26};  // 18 rem; the former maximums
// 2.350.0 D (#2750): a chat / sidebar wider than the former maximum may squeeze the list down to 18 rem (else 320 px as before)
const listFloor = () => (document.body.classList.contains('chat-open') && panelRem('chat') > OLD_MAX.chat) || panelRem('side') > OLD_MAX.side ? LIST_FLOOR_PX : LIST_SQUEEZE_PX;
// 2.319.0 B (#3288): the app bar's width in rem (app.css --srW: narrower without its labels)
const srW = () => document.documentElement.classList.contains('rail-nolabel') ? 3.25 : 4.5;
const panelRem = k => { const v = +LS.get('pw.' + k, 0); return v ? Math.max(PW[k][1], Math.min(PW[k][2], v)) : PW[k][0]; };
// 2.209.0 A (#2772): the widths in use when fitLayout had to shrink a panel (rem, null = the stored width)
const PWE = {det: null, chat: null, sq: false};
const panelEff = k => PWE[k] != null ? Math.round(Math.min(PWE[k], panelRem(k)) * 100) / 100 : panelRem(k);
function panelVars() { const r = document.documentElement.style; r.setProperty('--detW', panelEff('det') + 'rem'); r.setProperty('--chatW', panelEff('chat') + 'rem'); r.setProperty('--sideW', panelRem('side') + 'rem'); }
function panelMax(k) {  // the widest the panel may get now, in rem (the list keeps LIST_MIN_PX; 2.209.0 A (#2772): next to the
  // widths in use of the other panels, and while fitLayout shrinks them the list keeps LIST_SQUEEZE_PX)
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16, app = $('#app');
  const side = (k === 'side' || app.classList.contains('side-rail') || isMobile() ? 0 : panelRem('side') * rem) + (app.classList.contains('sb-b') ? srW() * rem : 0);  // 2.152.2 (#2622): the bar of sidebar B comes on top of the panel
  const chatW = document.body.classList.contains('chat-open') && !document.body.classList.contains('chat-yield') && innerWidth >= 1000 ? panelEff('chat') * rem : 0;
  const detW = app.classList.contains('detail-open') ? panelEff('det') * rem : 0;
  const other = k === 'det' ? chatW : k === 'side' ? detW + chatW : detW;
  const room = (innerWidth - side - other - (k === 'det' ? (PWE.sq ? LIST_SQUEEZE_PX : LIST_MIN_PX) : LIST_FLOOR_PX)) / rem;  // 2.350.0 D (#2750): chat + sidebar down to LIST_FLOOR_PX
  return Math.max(PW[k][1], Math.min(PW[k][2], room));
}
// 2.209.0 A (#2772): the stored width that shows v rem while fitLayout shrinks the panels (so a dragged edge stays where it
// was let go); without shrinking it is v itself
function panelWish(k, v) {
  if (k === 'side' || PWE[k] == null || !PWE.sq) return v;
  const shows = w => { const {L, rem} = layNow({[k]: w}); return L[k] / rem; };
  let lo = PW[k][1], hi = PW[k][2];
  if (shows(hi) < v) return hi;
  for (let i = 0; i < 16; i++) { const m = (lo + hi) / 2; if (shows(m) < v) lo = m; else hi = m; }
  return hi;
}
function panelSet(k, v, quiet) {  // v = the width to show, in rem
  const x = v == null ? null : Math.round(Math.max(PW[k][1], Math.min(PW[k][2], panelWish(k, Math.max(PW[k][1], Math.min(panelMax(k), v))))) * 4) / 4;
  if (x == null || x === PW[k][0]) LS.del('pw.' + k); else LS.set('pw.' + k, x);
  panelVars(); if (!quiet) fitLayout(); placeGrips();
}
let gripDrag = null;  // 2.87.9 (#1965): the panel whose grip is being dragged (placed on release, not per frame)
function placeGrips() {
  if (gripDrag) return;
  if (typeof gripWatch === 'function') gripWatch();
  const want = {det: !isMobile() && $('#app')?.classList.contains('detail-open') && !$('#detail').classList.contains('hidden'),
    chat: !isMobile() && innerWidth >= 1000 && document.body.classList.contains('chat-open') && !document.body.classList.contains('chat-yield') && !!$('#achat:not(.hidden)'),
    side: !isMobile() && !!$('#app') && !$('#app').classList.contains('side-rail') && !$('#app').classList.contains('sbb-nopan') && !document.body.classList.contains('kidmode') && !!$('#side')};  // 2.26.0 (#932); 2.224.0 A (#2817): sbb-nopan
  const GRIP_LAB = {det: N_('Width of the task panel'), chat: N_('Width of the chat'), side: N_('Width of the sidebar')};
  for (const k of ['det', 'chat', 'side']) {
    let g = $('#pgrip-' + k);
    if (!want[k]) { if (g) g.hidden = true; continue; }
    if (!g) {
      g = document.createElement('div'); g.id = 'pgrip-' + k; g.className = 'pgrip'; g.dataset.k = k; g.tabIndex = 0;
      g.setAttribute('role', 'separator'); g.setAttribute('aria-orientation', 'vertical');
      document.body.appendChild(g); gripWire(g);
    }
    const el = gripEl(k), r = el.getBoundingClientRect();
    g.hidden = !r.width;
    g.style.left = Math.round((k === 'side' ? r.right : r.left) - 5) + 'px'; g.style.top = Math.round(r.top) + 'px'; g.style.height = Math.round(r.height) + 'px';
    const v = panelEff(k);  // 2.209.0 A (#2772): the width in use
    g.setAttribute('aria-label', tr(GRIP_LAB[k]));
    g.setAttribute('aria-valuenow', String(v)); g.setAttribute('aria-valuemin', String(PW[k][1])); g.setAttribute('aria-valuemax', String(Math.round(panelMax(k) * 4) / 4));
    g.setAttribute('aria-valuetext', tr('{0} rem', String(v)));
    g.dataset.tip = tr(GRIP_LAB[k]) + ' · ' + tr('drag; double-click = standard width');  // 2.99.0 B (#2185): own label (w299_gripTip), no native title
  }
}
// 2.99.0 B (#2185): label left of / above the grip so it never covers the send button
function w299_gripTip(g, on) {
  let t = $('#griptip');
  if (!on || !g?.dataset.tip) { if (t) t.classList.add('hidden'); return; }
  if (!t) { t = document.createElement('div'); t.id = 'griptip'; t.setAttribute('role', 'tooltip'); document.body.appendChild(t); }
  t.textContent = g.dataset.tip; t.classList.remove('hidden');
  const r = g.getBoundingClientRect();
  t.style.left = Math.max(t.offsetWidth + 8, Math.round(r.left - 4)) + 'px'; t.style.top = Math.max(8, Math.round(r.top + 8)) + 'px';
}
document.addEventListener('mouseover', e => { const g = e.target.closest?.('.pgrip'); if (g) w299_gripTip(g, true); });
document.addEventListener('mouseout', e => { if (e.target.closest?.('.pgrip')) w299_gripTip(null, false); });
document.addEventListener('mousedown', e => { if (e.target.closest?.('.pgrip')) w299_gripTip(null, false); }, true);
const gripEl = k => k === 'det' ? $('#detail') : k === 'side' ? $('#side') : $('#achat');
function gripWire(g) {
  const k = g.dataset.k;
  g.addEventListener('dblclick', () => { g._dbl = Date.now(); clearTimeout(g._mt); panelSet(k, null); });
  g.addEventListener('keydown', e => {
    const step = (e.shiftKey ? 4 : 1) * (k === 'side' ? -1 : 1), v = panelEff(k);  // the sidebar grows to the right
    const to = {ArrowLeft: v + step, ArrowRight: v - step, Home: PW[k][1], End: panelMax(k)}[e.key];
    if (to != null) { e.preventDefault(); e.stopPropagation(); panelSet(k, to); announce(tr('{0} rem', String(panelEff(k)))); }
    else if (e.key === 'Enter') { e.preventDefault(); panelSet(k, null); announce(tr('Standard width')); }
  });
  g.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    e.preventDefault(); g.setPointerCapture?.(e.pointerId); g.classList.add('drag'); document.body.classList.add('pgdrag');
    // 2.87.9 (#1965): measured once at the start; a move sets only this panel's width variable, once per frame (no
    // localStorage, no measuring of the other grips, no aria per move); the grip slides along by transform; storing,
    // the layout check and placing the grips happen on release
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const box = gripEl(k).getBoundingClientRect(), right = box.right, left = box.left, max = panelMax(k), w0 = panelEff(k);  // 2.209.0 A (#2772): from the width in use
    const px = w => w * rem, px0 = px(w0);
    let w = w0; gripDrag = k;
    const mv = rafThrottle(x => {
      w = Math.round(Math.max(PW[k][1], Math.min(max, (k === 'side' ? x - left : right - x) / rem)) * 4) / 4;
      document.documentElement.style.setProperty({det: '--detW', chat: '--chatW', side: '--sideW'}[k], w + 'rem');
      g.style.transform = `translateX(${(k === 'side' ? 1 : -1) * (px(w) - px0)}px)`;
    });
    let moved = false; const x0 = e.clientX;
    const mv2 = ev => { if (Math.abs(ev.clientX - x0) > 3) moved = true; if (moved) mv(ev.clientX); };
    const up = () => { g.removeEventListener('pointermove', mv2); mv.flush(); gripDrag = null; g.style.transform = '';
      g.classList.remove('drag'); document.body.classList.remove('pgdrag');
      if (moved) panelSet(k, w, true); fitLayout(); placeGrips();
      // a tap without dragging: a small menu (the way without dragging, WCAG 2.5.7); a double-click resets instead
      if (!moved) { clearTimeout(g._mt); g._mt = setTimeout(() => { if (Date.now() - (g._dbl || 0) < 400) return; menu(g, [{label: tr('Wider'), icon: k === 'side' ? 'right' : 'left', fn: () => panelSet(k, panelEff(k) + 4)}, {label: tr('Narrower'), icon: k === 'side' ? 'left' : 'right', fn: () => panelSet(k, panelEff(k) - 4)}, {label: tr('Standard width'), icon: 'undo', fn: () => panelSet(k, null)}]); }, 320); } };
    g.addEventListener('pointermove', mv2); g.addEventListener('pointerup', up, {once: true}); g.addEventListener('pointercancel', up, {once: true});
  });
}
let gripRO = null;
try { gripRO = new ResizeObserver(() => placeGrips()); gripRO.observe(document.documentElement); } catch { /* old engine */ }
// 2.16.2: the panels change size without the page doing so (the chat opens next to the task): watch them too
const gripWatch = () => { if (!gripRO) return; for (const id of ['detail', 'achat', 'side']) { const el = document.getElementById(id); if (el && !el.dataset.gripRo) { el.dataset.gripRo = '1'; gripRO.observe(el); } } };
['transitionend'].forEach(t => document.addEventListener(t, e => { if (e.target?.id === 'detail' || e.target?.id === 'achat' || e.target?.id === 'side') placeGrips(); }));
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
  matchMedia('(max-width:767px)').addEventListener('change', () => {  // 2.364.0 B (#3040): the phone layout ends at 767 px (was 899)
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
const DETAIL_ORDER = ['family', 'life', 'subtasks', 'deps', 'links', 'tags', 'attachments', 'fields', 'custom', 'time', 'snippets', 'code', 'history', 'comments'];  // snippets: 2.35.0 (#1095)
// 2.24.0 (UX-41): what a task needs first comes first: description, subtasks, comments (the assignee sits in the header).
// The rest folds into "More details" (open state per device); a section that holds something worth seeing at once
// (files, a waiting-on, events / contacts) stays outside the fold.
// 2.27.0 (#957, back to #322): the comments come LAST again, below "More details" (the box stays at the bottom edge); the fold
// says in its summary line what it holds, so nothing is overlooked
const DETAIL_TOP = ['family', 'life', 'subtasks'];
const DETAIL_MORE = ['deps', 'links', 'attachments', 'video', 'tags', 'fields', 'custom', 'time', 'snippets', 'code', 'history'];  // code: 2.2.0 (#271)  // history: private lists only (2.0.7)
// 2.27.0 (#957): the summary line of the folded "More details": what is set inside it ("3 tags · Link · 2 fields")
function moreSummary(t, ks) {
  const out = [], has = k => ks.includes(k);
  const ntag = (t.tags || []).length + (t.ltags || []).length;
  if (has('tags') && ntag) out.push(trn('{0} tag', '{0} tags', ntag));
  if (has('fields') && t.url) out.push(tr('Link'));
  const nf = has('custom') ? fieldsOf(t.list_id).filter(f => { const v = (t.fields || {})[f.id]; return v !== undefined && v !== null && v !== ''; }).length : 0;
  if (nf) out.push(trn('{0} field', '{0} fields', nf));
  if (has('snippets') && snipCount(t)) out.push(trn('{0} code snippet', '{0} code snippets', snipCount(t)));  // 2.35.0 (#1095)
  return out.join(' · ');
}
// ---- 2.380 F (#3435): every section with a heading folds on its own (not the description); the folded ones are ONE account
// setting for all tasks and lists, on every device (detail_fold: the keys, comma separated). A folded head says in short what
// it holds ("2 open", "3 files", "12:00 of 10 h", red when over, "blocked"). Nothing opens by itself; "Fold all sections" /
// "Unfold all sections" in the task's "…" menu. The comments of the desktop's split keep their own fold (detail_cm_fold).
const DFOLD_KEYS = ['subtasks', 'deps', 'links', 'attachments', 'video', 'tags', 'custom', 'time', 'comments'];
const DFOLD_BUDGET = ['budget h', 'budget (h)', 'budget hours', 'budget std', 'budget (std)', 'budget-stunden', 'budgetstunden'];  // timetrack.py BUDGET_FIELD_NAMES
let dfPend = null;  // a change of this device until the server has it (a state reload in between keeps it)
const dfSet = () => new Set(String(dfPend ?? S.settings?.detail_fold ?? '').split(',').filter(k => DFOLD_KEYS.includes(k)));
function dfSave(set) {
  const v = DFOLD_KEYS.filter(k => set.has(k)).join(',');
  dfPend = v; if (S.settings) S.settings.detail_fold = v;
  renderDetail();
  api('PATCH', '/api/settings', {detail_fold: v}).then(() => { if (dfPend === v) dfPend = null; }, () => { /* api() showed it; the local value stays */ });
}
// the short line of a folded section: [text, class]
function dfSum(k, t, ncm) {
  const n = (x, txt) => x ? [txt, ''] : ['', ''];  // (literal tr / trn calls: tools/i18n_check.py finds the keys)
  if (k === 'subtasks') { const ks = children(t.id), o = ks.filter(x => x.status === 0).length; return !ks.length ? ['', ''] : o ? [tr('{0} open', o), ''] : [tr('all done'), '']; }
  if (k === 'attachments') { const c = (t.attachments || []).length; return n(c, trn('{0} file', '{0} files', c)); }
  if (k === 'tags') { const c = (t.tags || []).length + (t.ltags || []).length; return n(c, trn('{0} tag', '{0} tags', c)); }
  if (k === 'custom') { const c = fieldsOf(t.list_id).filter(f => { const v = (t.fields || {})[f.id]; return v !== undefined && v !== null && v !== ''; }).length; return n(c, trn('{0} field', '{0} fields', c)); }
  if (k === 'deps') { const c = (t.blockers || []).length; return t.blocked && !t.status ? [tr('blocked'), 'dfbad'] : c ? [trn('{0} dependency', '{0} dependencies', c), ''] : t.waiting_at ? [tr('Waiting'), 'dfwait'] : ['', '']; }
  if (k === 'links') { const c = ((S.tcontacts || {})[t.id] || []).length + ((S.evlinks || {})[t.id] || []).length; return n(c, trn('{0} entry', '{0} entries', c)); }
  if (k === 'video') { const c = typeof vdr_count === 'function' ? vdr_count(t) : 0; return n(c, trn('{0} sign-off', '{0} sign-offs', c)); }
  if (k === 'comments') return n(ncm, trn('{0} comment', '{0} comments', ncm));
  if (k === 'time') {
    const sec = typeof taskTime === 'function' ? taskTime(t.id)[0] : 0, f = fieldsOf(t.list_id).find(x => x.type === 'number' && DFOLD_BUDGET.includes(String(x.name || '').trim().toLowerCase()));
    const b = f ? +((t.fields || {})[f.id]) || 0 : 0, hm = `${Math.floor(sec / 3600)}:${pad(Math.floor(sec % 3600 / 60))}`;
    if (!b) return sec >= 60 ? [hm, ''] : ['', ''];
    return [tr('{0} of {1} h', hm, fmtNum(b, 1)), sec > b * 3600 ? 'dfbad' : ''];
  }
  return ['', ''];
}
// a section's html with the fold: data-dfold on its element, the chevron in front of its heading, the short line when folded
function dfWrap(k, html, t, ncm) {
  if (!html || !html.trim()) return html;
  const i = html.indexOf('<h5'), d = i < 0 ? -1 : html.lastIndexOf('class="dsec', i), j = i < 0 ? -1 : html.indexOf('>', i), e = j < 0 ? -1 : html.indexOf('</h5>', j);
  if (d < 0 || e < 0) return html;
  const on = dfSet().has(k), [sum, cls] = on ? dfSum(k, t, ncm) : ['', ''], lab = on ? tr('Unfold') : tr('Fold');
  const btn = `<button type="button" class="iconbtn dfbtn" data-dfb="${k}" aria-expanded="${!on}" title="${esc(lab)}" aria-label="${esc(lab)}">${ic('chev', 's fcar')}</button>`;
  const inner = html.slice(j + 1, e), sp = inner.indexOf('<span class="spacer">'), sm = sum ? `<span class="dfsum muted ${cls}">${esc(sum)}</span>` : '';
  return html.slice(0, d) + `data-dfold="${k}" class="dsec dfold${on ? ' dfolded' : ''}` + html.slice(d + 11, i) + html.slice(i, j + 1) + btn
    + (sp < 0 ? inner + sm : inner.slice(0, sp) + sm + inner.slice(sp)) + html.slice(e);
}
const df_menuItem = () => {  // both while some are folded and some open
  const f = dfSet(), ks = $$('#detail [data-dfold]').map(x => x.dataset.dfold), out = [];
  if (ks.some(k => f.has(k))) out.push({label: tr('Unfold all sections'), icon: 'chev', fn: () => dfSave(new Set([...f].filter(k => !ks.includes(k))))});
  if (ks.some(k => !f.has(k))) out.push({label: tr('Fold all sections'), icon: 'chev', fn: () => dfSave(new Set([...f, ...ks]))});
  return out;
};
document.addEventListener('click', e => {
  const h = e.target.closest?.('#detail .dfold > h5'); if (!h) return;
  const b = e.target.closest('button, a, input, select, label, textarea'); if (b && !b.matches('.dfbtn')) return;
  const k = h.parentElement.dataset.dfold, f = dfSet(); if (f.has(k)) f.delete(k); else f.add(k);
  dfSave(f);
});
// 2.7.2 (#424): where a task lives, at the top of its panel: Folder › List › Section › (parent task). Every part jumps
// there (the list, scrolled to the section / the parent) and closes the bell's dropdown. Only lists the viewer has.
function crumbsHtml(t, l, parent) {
  if (!l || t.id <= 0) return '';
  const sec = t.section_id && S.sections.find(x => x.id === t.section_id && x.list_id === l.id);
  const b = (k, id, icon, label, title) => `<button type="button" class="dcb" data-act="crumb" data-k="${k}" data-id="${esc(String(id))}" title="${esc(title || label)}">${icon ? (icon[0] === '<' ? icon : ic(icon, 's')) : ''}<span>${esc(label)}</span></button>`;
  const parts = [];
  if (l.folder && !l.is_inbox) parts.push(b('folder', l.folder, 'folder', fDisp(l.folder)));
  // 2.25.0 (UX-44): the path is where the task's place is changed: list and section open a menu (open / move)
  const mv = canEdit(t) && canEditList(t.list_id) && t.status === 0 && !t.context;
  const bm = (k, id, icon, label) => mv ? `<button type="button" class="dcb" data-act="crumb-menu" data-k="${k}" data-id="${esc(String(id))}" aria-haspopup="menu" title="${esc(tr('Open or move: {0}', label))}">${icon ? (icon[0] === '<' ? icon : ic(icon, 's')) : ''}<span>${esc(label)}</span></button>` : b(k, id, icon, label);
  parts.push(bm('list', l.id, l.is_inbox ? 'inbox' : licMark(l, 's', true) || 'list', lname(l)));  // 2.36.2 (#1135)
  if (sec) parts.push(bm('sec', sec.id, '', sec.name));
  else if (mv && !t.parent_id && (S.sections.some(x => x.list_id === l.id) || canEditList(l.id)) && !l.is_inbox) parts.push(`<button type="button" class="dcb dcadd" data-act="crumb-menu" data-k="sec" data-id="" aria-haspopup="menu" title="${esc(tr('Move to section…'))}">${ic('columns', 's')}<span class="sr">${esc(tr('Move to section…'))}</span></button>`);
  if (parent) parts.push(b('parent', parent.id, 'sub', parent.title));
  // 2.13.0: the task number, a tap copies the link; 2.218.0 A (#2799): only in the task's "…" menu now ("Copy link · #18"), also on a desktop
  return `<nav class="dcrumbs" aria-label="${esc(tr('Where this task is'))}">${parts.join(`<span class="dcsep" aria-hidden="true">›</span>`)}</nav>`;
}
async function copyTaskLink(id) {
  const url = `${location.origin}/#t/${id}`;
  const k = tkOf(taskById(id)) || '#' + id;  // 2.390.0 (#3353): the key when the project has one
  try { if (isTouch() && navigator.share) { await navigator.share({url, title: k + ' ' + (taskById(id)?.title || '')}); return; } await navigator.clipboard.writeText(url); toast(tr('Link to {0} copied', k)); }
  catch { toast(url, null, 6000); }
}
function crumbMenu(anchor, k, id) {  // 2.25.0 (UX-44)
  const t = taskById(S.sel), l = t && listById(t.list_id); if (!l) return;
  const sec = k === 'sec' && id ? S.sections.find(x => x.id === +id) : null;
  menu(anchor, [...(k === 'list' ? [{label: tr('Open {0}', lname(l)), icon: l.is_inbox ? 'inbox' : 'list', fn: () => crumbGo('list', l.id)}] : sec ? [{label: tr('Open {0}', sec.name), icon: 'columns', fn: () => crumbGo('sec', sec.id)}] : []), '-',
    moveListItem(anchor, t.id), ...ml_menuItems(anchor, t), ...(!t.parent_id && (S.sections.some(x => x.list_id === t.list_id) || canEditList(t.list_id)) ? [{label: tr('Move to section…'), icon: 'columns', fn: () => sectionPicker(anchor, t.id)}] : [])].filter((x, i, a) => x !== '-' || i > 0));
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
// 2.24.0 (UX-41): who does it, right under the title (the header has no room left on a phone / in the side panel): the
// picture + the name, a tap = the assign menu
function dWhoChip(t, ro) {
  const name = t.assignee_group_id ? (S.groups || []).find(g => g.id === t.assignee_group_id)?.name || tr('Group') : t.assignee_id ? personName(t.list_id, t.assignee_id) || personNameAny(t.assignee_id) || '?' : '';
  const inner = t.assignee_id ? av(t.assignee_id, name, 'avatar who') : ic(t.assignee_group_id ? 'users' : 'user', 's');
  const lab = name ? tr('Assigned to {0}', name) : tr('Nobody assigned');
  const lock = (ro || !canAssign(t)) && !myGroup(t.assignee_group_id);  // 2.31.0 (#1054): the only assignee control: says when it is locked
  return `<button type="button" class="dchip dwho ${name ? 'set' : ''} ${lock ? 'ro' : ''}" data-act="assign" data-id="${t.id}" aria-haspopup="menu" ${lock ? 'aria-disabled="true"' : ''} title="${esc(lab + (lock ? '' : ' · ' + tr('Assign…')))}" aria-label="${esc(lab + (lock ? '' : ' · ' + tr('Assign…')))}">${inner}<span class="dct">${esc(name || tr('Assign'))}</span></button>`;
}
// ---- 2.31.0 (#344): desktop (not phones, the Fold, touch tablets): the properties on top, the comments with the history and
// its switch in their own area below, the line between them dragged with the mouse or moved with the keyboard (a separator:
// ↑ ↓ 5 %, Shift 10 %, Home / End, Enter or a double-click folds the comments area, a drag unfolds it). The properties' share
// (settings detail_split, %) and the fold (detail_cm_fold) are saved per user on the server, so every desktop gets them.
// Without the comments module (or a read-only context task) there is no split: the panel stays one stream.
const CSPL_MIN = 20, CSPL_MAX = 85, CSPL_DEF = 60;
const cmSplitOn = t => !!t && cmtOn() && t.id > 0 && !t.context && !isTouch();
// a change of this device: wins over a state reload that still has the old value, until the server's state has it too
let dsPend = null;
const dsVal = k => {
  if (dsPend && Object.keys(dsPend).every(x => String(S.settings?.[x]) === String(dsPend[x]))) dsPend = null;
  return dsPend && k in dsPend ? dsPend[k] : S.settings?.[k];
};
const dsTop = () => { const v = +dsVal('detail_split'); return v ? Math.max(CSPL_MIN, Math.min(CSPL_MAX, Math.round(v))) : CSPL_DEF; };
const dsFold = () => String(dsVal('detail_cm_fold')) === '1';
function dsApply(v = dsTop()) {
  const d = $('#detail'), g = $('#d-sgrip'), f = dsFold(); if (!d) return;
  d.style.setProperty('--dsT', String(v)); d.style.setProperty('--dsC', String(100 - v));
  d.classList.toggle('dsfold', f);
  if (g) { g.setAttribute('aria-valuenow', String(v)); g.setAttribute('aria-valuetext', f ? tr('Comments folded') : tr('{0} % properties, {1} % comments', v, 100 - v)); }
  const b = $('#d-tl .dsfoldb');
  if (b) { b.setAttribute('aria-expanded', String(!f)); const lab = f ? tr('Show the comments') : tr('Fold the comments'); b.title = lab; b.setAttribute('aria-label', lab); }
}
let dsT = null;
function dsSave(patch) {
  dsPend = {...dsPend, ...patch};
  dsApply();
  clearTimeout(dsT);
  dsT = setTimeout(() => {
    const body = {detail_split: String(dsTop()), detail_cm_fold: dsFold() ? '1' : '0'};
    dsPend = {...body};
    api('PATCH', '/api/settings', body).catch(() => { /* api() showed it; the local value stays */ });
  }, 400);
}
function dsFoldToggle(on = !dsFold()) {
  dsSave({detail_cm_fold: on ? '1' : '0'});
  if (!on) { const p = $('#d-cpane'); if (p && !cmtNew()) p.scrollTop = p.scrollHeight; }
}
document.addEventListener('keydown', e => {
  const g = e.target.closest?.('#d-sgrip'); if (!g || e.altKey || e.ctrlKey || e.metaKey) return;
  const v = dsTop(), st = e.shiftKey ? 10 : 5;
  const to = {ArrowUp: v - st, ArrowDown: v + st, Home: CSPL_MIN, End: CSPL_MAX}[e.key];
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); dsFoldToggle(); return; }
  if (to == null) return;
  e.preventDefault();
  dsSave({detail_split: Math.max(CSPL_MIN, Math.min(CSPL_MAX, to)), ...(dsFold() ? {detail_cm_fold: '0'} : {})});
});
document.addEventListener('dblclick', e => { if (e.target.closest?.('#d-sgrip')) dsFoldToggle(); });
document.addEventListener('pointerdown', e => {
  const g = e.target.closest?.('#d-sgrip'); if (!g || e.button) return;
  const body = $('#detail .dbody'), bot = $('#detail .dbot'); if (!body) return;
  e.preventDefault();
  const top = body.getBoundingClientRect().top, end = bot ? bot.getBoundingClientRect().top : $('#detail').getBoundingClientRect().bottom;
  const y0 = e.clientY; let v = dsTop(), moved = false;
  try { g.setPointerCapture(e.pointerId); } catch { /* old browsers */ }
  g.classList.add('drag');
  const show = rafThrottle(dsApply);  // 2.87.9 (#1965): once per frame, only when the share changes
  const mv = ev => {
    if (!moved && Math.abs(ev.clientY - y0) < 3) return;
    const first = !moved;
    if (first && dsFold()) dsPend = {...dsPend, detail_cm_fold: '0'};
    moved = true;
    const was = v;
    v = Math.max(CSPL_MIN, Math.min(CSPL_MAX, Math.round((ev.clientY - top) / Math.max(1, end - top) * 100)));
    if (first || v !== was) show(v);
  };
  const up = () => {
    g.removeEventListener('pointermove', mv); g.removeEventListener('pointerup', up); g.removeEventListener('pointercancel', up);
    show.flush();
    g.classList.remove('drag');
    if (moved) dsSave({detail_split: v, detail_cm_fold: '0'});
  };
  g.addEventListener('pointermove', mv); g.addEventListener('pointerup', up); g.addEventListener('pointercancel', up);
  g.focus({preventScroll: true});
});
document.addEventListener('toggle', e => { if (e.target.id === 'd-more') LS.set('dMore', e.target.open); }, true);
// 2.36.0 (#1120): a rebuild of the open task (the poll after a new chat message or comment) keeps the scroll positions of
// the panel, its body and the comments area; who was at the very end (newest comments) stays there, also when a comment
// arrives. Only for the same task: another task starts at its top (openDetail)
let cmxShown = null;
function cmxScrollGet() {
  const d = $('#detail'); if (!d || cmxShown == null || cmxShown !== S.sel) return null;
  const m = el => el && {top: el.scrollTop, end: el.scrollHeight - el.clientHeight > 4 && el.scrollHeight - el.clientHeight - el.scrollTop < 4};
  return {id: cmxShown, d: m(d), b: m($('.dbody', d)), p: m($('#d-cpane', d))};
}
function cmxScrollSet(s, endOnly = false) {
  const d = $('#detail'); if (!s || !d || s.id !== S.sel) return;
  const put = (el, v) => { if (!el || !v || (endOnly && !v.end)) return; const want = v.end ? el.scrollHeight : v.top; if (Math.abs(el.scrollTop - want) > 1) el.scrollTop = want; };
  put(d, s.d); put($('.dbody', d), s.b); put($('#d-cpane', d), s.p);
}
function renderDetail() {
  const s = cmxScrollGet(), r = keepFocus($('#detail'), renderDetail0);
  cmxShown = S.sel; cmxScrollSet(s);
  wsc_detail();  // 2.53.0 (#1474): the comment field framed in the colour of the task's workspace
  return r;
}
// 2.280.0 A (#3108): a long note is not in the start state (no content, content_n = its length): the detail loads it
// (GET /api/tasks/<id>). Until it is there - or offline - the detail shows no note field at all, so an empty note is never
// typed over or saved (the offline queue, the autosave). TKN_OFF: when loading failed (tried again after TKN_RETRY_MS).
// 2.280.0 F (#3108): TKN_ERR = the server refused (not found, no access): its message instead of "Only available online."; back
// online the open task tries again at once
const TKN_OFF = new Map(), TKN_WAIT = new Map(), TKN_ERR = new Map(), TKN_RETRY_MS = 10000;
window.addEventListener('online', () => { if (!TKN_OFF.size) return; TKN_OFF.clear(); TKN_ERR.clear(); if (S.sel && tkNoteMissing(taskById(S.sel))) renderDetail(); });
const tkNoteMissing = t => !!t && t.id > 0 && !t.context && !('content' in t);
function tkNoteLoad(id) {
  const t = taskById(id); if (!tkNoteMissing(t)) return Promise.resolve(t?.content ?? '');
  if (TKN_WAIT.has(id)) return TKN_WAIT.get(id);
  const p = rawFetch('GET', `/api/tasks/${id}`).then(j => {
    const x = taskById(id);
    if (x && tkNoteMissing(x) && typeof j?.content === 'string' && !(String(x.updated_at || '') > String(j.updated_at || ''))) x.content = j.content;  // 2.280.0 F (#3108): not an answer older than the task (a full load came in between)
    TKN_OFF.delete(id); TKN_ERR.delete(id);
    return x && 'content' in x ? x.content : j?.content ?? '';
  }, e => { TKN_OFF.set(id, Date.now()); if (e instanceof Offline) TKN_ERR.delete(id); else TKN_ERR.set(id, e?.message || ''); throw e; }).finally(() => TKN_WAIT.delete(id));
  TKN_WAIT.set(id, p);
  return p;
}
// 2.280.0 F (#3108): at most TKN_PAR requests at once (printing a big project asked for every note at the same time)
const TKN_PAR = 6;
async function tkNotesLoad(ids) {
  const todo = ids.filter(id => tkNoteMissing(taskById(id)) && !(Date.now() - (TKN_OFF.get(id) || 0) < TKN_RETRY_MS)), out = [];
  let i = 0;
  const run = async () => { while (i < todo.length) { const k = i++; try { out[k] = {status: 'fulfilled', value: await tkNoteLoad(todo[k])}; } catch (e) { out[k] = {status: 'rejected', reason: e}; } } };
  await Promise.all(Array.from({length: Math.min(TKN_PAR, todo.length)}, run));
  return out;
}
function renderDetail0() {
  const t = taskById(S.sel); if (!t) return;
  const noteOut = tkNoteMissing(t);
  if (noteOut && !TKN_WAIT.has(t.id) && !(Date.now() - (TKN_OFF.get(t.id) || 0) < TKN_RETRY_MS)) {
    const id = t.id, done = () => { if (S.sel === id) renderDetail(); };
    tkNoteLoad(id).then(done, done);
  }
  const l = listById(t.list_id);
  const kids = children(t.id);
  const parent = t.parent_id && S.tasks.get(t.parent_id);
  const dueTxt = t.due ? dueLabel(t) : tr('Date');
  const mdMode = t.content && !S.editContent;
  const ro = !canEdit(t), shared = l && l.shared;
  // 2.36.0 (#1118): a locked task: title, notes, date, priority, list, tags, repeat, assignee read-only (tlkR); the lock
  // button next to Pin switches it; comments, checkboxes, completing and subtasks stay free
  const tlkL = !ro && tlkIs(t), tlkR = ro || tlkL;
  const le2uLk = typeof le2u_locked === 'function' && le2u_locked(t);  // 2.64.1 (#1817): a locked list, texts not decrypted
  // U07 (owner decision 3) applied to the checklist type; 2.7.2 (#414): the type is gone, every item is a full task
  const ck = false;
  // 2.0.6 (#315): comments everywhere (module "comments"), also in private lists and without collaboration (personal
  // notes); never in checklists. Replaces U18 (comments only in shared lists). Without comments a private task shows
  // only "+ Comment"; a shared list with collaboration keeps the whole section (its history of changes lives there)
  const ncm = S.tl.id === t.id && S.tl.comments ? S.tl.comments.length : t.comment_count || 0;
  // the list of comments shows once there is something in it (comments; in shared lists the history; elsewhere the changes
  // others made); the box itself is always there (sticky at the bottom), a single line until it is used
  // 2.31.0 (#344): desktop: the comments in their own area below the properties (split), shown even without comments
  const split = !ck && cmSplitOn(t);
  const cmOk = cmtOn() && t.id > 0 && !ck && !t.context, cm = cmOk && (split || ncm || cmSocial(t) || tlForeign(t).length) ? 'full' : '';
  // 2.0.7: private lists with collaboration keep the folded "History" of 2.0.5 (every change, mine included, the
  // import line too); it stays out of the notes above, so they have no activity noise
  const hist = collab() && t.id > 0 && !ck && !t.context && !shared;
  const mdOpen = !tlkR && !ck && t.content && /^\s*[-*]\s+\[ \]\s*\S/m.test(t.content) && depthOf(t) < maxDepth() - 1;
  // 2.0.2 (#242): the comments sit right below the description, folded to the newest one (per device); long descriptions
  // fold after ~8 lines. 2.31.0 (#1054): no "Details | Comments" tabs on phones any more, a small jump to the comments instead
  const mdLong = mdMode && mdIsLong(t.content), mdClamp = mdLong && !LS.get('mdOpen', false);  // 2.101.0 (#2157): one device setting for all tasks
  // 2.31.0 (#1054): the assignee once, as the chip under the title (people, agents, groups, "Take it"; no select below)
  const whoOn = !ck && t.id > 0 && collab() && (shared || t.assignee_id) && pz_show(t, 'who', t.assignee_id || t.assignee_group_id);  // 2.412.0 (#3552)
  const jump = cm === 'full' && !split ? `<button type="button" class="linkbtn djump" data-act="d-jump-cm" aria-controls="d-tl">${ic('down', 's')}<span>${tr('To the comments')}</span><span class="c" id="d-jump-count">${ncm || ''}</span></button>` : '';
  // 2.18.0 (#430): a milestone (no subtasks; its own section with progress, burndown, release notes) / the milestone a task
  // of a list with milestones belongs to (open ones + the current one)
  const msT = isMs(t), msSel = !msT && !t.context ? msOfList(t.list_id).filter(m => m.status === 0 || m.id === t.milestone_id) : [];
  const msTog = !t.context && (msT || (isProject(t.list_id) && !t.parent_id && !kids.length && t.id > 0));
  // 2.0.6 (#316 / #322): the order of the sections below the description, in one place
  const SEC = {
    subtasks: ck || msT ? '' : `<div class="dsec subsec"><h5>${isOcc(t) && famOn() ? tr('Gift ideas') : tr('Subtasks')}</h5><div class="subs">${kids.map(k => taskRow(k, {compact: true, subRow: true})).join('')}
        ${ro ? '' : depthOf(t) < maxDepth() - 1 ? `<div class="subadd">${ic('plus', 's')}<input id="d-sub" placeholder="${isOcc(t) && famOn() ? tr('Add a gift idea') : tr('Add subtask')}" aria-label="${esc(isOcc(t) && famOn() ? tr('Add a gift idea') : tr('Add subtask'))}" enterkeyhint="done"></div>` : `<div class="muted" style="font-size:var(--fs-s);padding:.25rem">${tr('At most {0} levels', maxDepth())}</div>`}</div></div>`,
    comments: cm === 'full' ? `<div class="dsec cmsec ${cmtNew() ? 'cmnew' : ''}" id="d-tl">${timelineHtml(t)}</div>` : '',
    history: hist ? `<details class="dsec cmsec cmro" id="d-hist"><summary><span>${tr('History')}</span></summary><div class="cms" id="d-hist-items">${S.tl.id === t.id ? histItems() : `<div class="muted cmempty">${tr('Loading…')}</div>`}</div></details>` : '',
    deps: ck ? '' : `${t.id > 0 && dFor(t) && !t.context ? `<div class="dsec depsec" id="d-deps">${depsHtml(t)}</div>` : waitExtHtml(t, ro, true)}`,  // 2.22.0 (#686)
    tags: ck || !pz_show(t, 'tags', (t.tags || []).length + (t.ltags || []).length) ? '' : `<div class="dsec"><h5>${tr('Tags')}</h5>${tagEditHtml(t, tlkR)}</div>`,
    attachments: ck ? '' : `<div class="dsec attsec"><h5>${tr('Attachments')}</h5>${typeof le2uAttHead === 'function' ? le2uAttHead(t) : ''}<div class="atts">${(t.attachments || []).map(attHtml).join('')}
        ${t.id > 0 && !ro ? `<label class="attadd" title="${esc(isTouch() ? tr('Images, PDFs, documents') : tr('Images, PDFs, documents') + ' · ' + tr('or drop files here / paste an image with Ctrl+V'))}">${ic('clip', 's')}<span>${tr('Add file')}</span><input type="file" id="d-file" multiple hidden></label>${typeof le2eOn === 'function' && le2eOn(t.list_id) ? '' : e2eAttAddHtml(t)}` : ''}</div>${t.attachments_trash?.length ? (typeof attTrashHtml === 'function' ? attTrashHtml(t) : (loadModule('trashui').then(() => renderDetail(), () => {}), '')) : '' /* 2.272.0 G (#3038): trashui.js */}
</div>`,
    fields: ck ? '' : `<div class="dsec fields">
        ${''/* 2.25.0 (UX-44): list and section are changed in the path on top (a tap on it), no fields here any more */}
        ${ticketsOn(t.list_id) && pz_show(t, 'ttype', t.ttype) ? `<label for="d-ttype">${tr('Type')}</label><select id="d-ttype" data-sheet-ico="bug" ${ro ? 'disabled' : ''}><option value="">${tr('None')}</option>${TTYPES.map(([k, n, i]) => `<option value="${k}" data-ico="${i}" ${t.ttype === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select>` : ''}
        ${pz_show(t, 'points', t.points) ? spt_detailHtml(t, ro) : ''}${''/* 2.60.0 (#1511): story points */}
        ${msTog ? `<label for="d-ms">${tr('Milestone')}</label><label class="chkl dmsl"><input type="checkbox" id="d-ms" ${msT ? 'checked' : ''} ${ro ? 'disabled' : ''}><i class="msd" aria-hidden="true"></i>${tr('This task is a milestone')}</label>` : ''}
        ${msSel.length ? `<label for="d-msel">${msTog ? tr('Belongs to') : tr('Milestone')}</label><select id="d-msel" data-sheet-ico="flag" ${ro ? 'disabled' : ''}><option value="">${tr('None')}</option>${msSel.map(m => `<option value="${m.id}" ${m.id === t.milestone_id ? 'selected' : ''}>${esc(m.title + (m.due ? ' · ' + fmtDateLoc(m.due) : ''))}</option>`).join('')}</select>${typeof env_taskNote === 'function' ? env_taskNote(t) : ''}` : ''}
        ${t.url || S.editLink ? `<label>${tr('Link')}</label>${linkField(t, ro)}` : ro ? '' : `<button type="button" class="btn sm linkadd" data-act="link-edit">${ic('link', 's')} ${tr('Add link')}</button>`}${''/* 2.41.0 (#1475): the Link row only with a link */}
        ${t.id > 0 && !t.context ? aiuTaskLine(t) : ''}
      </div>`,
    custom: ck ? '' : `${fieldsOf(t.list_id).length ? `<div class="dsec cfsec"><h5>${tr('Fields')}</h5><div class="fields cf">${fieldsOf(t.list_id).map(f => fieldEditor(f, t, ro)).join('')}</div></div>` : ''}`,
    time: ck ? '' : `${tFor(t) && t.id > 0 && !t.context ? `<div class="dsec tesec" id="d-time">${taskTimeHtml(t)}</div>` : ''}`,
    code: ck || !pz_show(t, 'repo', (t.code?.prs || []).length || (t.code?.commits || []).length) ? '' : codeHtml(t),  // 2.412.0 (#3552): the project's properties
    snippets: ck || !pz_show(t, 'repo', snipCount(t)) ? '' : snipHtml(t, ro),  // 2.35.0 (#1095): code snippets
    family: ck ? '' : famDetailHtml(t, l, ro),  // 2.19.0 (#653)
    life: ck ? '' : lifeDetailHtml(t, l, ro),  // 2.22.0 (#663)
    video: ck || typeof vdr_taskHtml !== 'function' || !pz_show(t, 'video', typeof vdr_count === 'function' && vdr_count(t)) ? '' : vdr_taskHtml(t, ro),  // 2.99.1 A (#1959): video sign-offs (videorev.js, loaded on demand)
    links: ck ? '' : linksDetailHtml(t, ro)};  // 2.21.0 (#659 / #658): events + contacts of the task
  setHtml($('#detail'), `
    <div class="dtop">
      <button class="iconbtn back" data-act="close-detail" aria-label="${tr('Back')}">${ic('back')}</button>
      <button class="chk ${t.status === 2 ? 'on' : t.status === -1 ? 'wont' : 'p' + t.priority}${msT ? ' ms' : ''}" data-act="toggle" data-id="${t.id}" role="checkbox" aria-checked="${t.status === 2}" aria-label="${esc(msT ? tr('Complete milestone: {0}', mdPlain(t.title)) : tr('Complete: {0}', mdPlain(t.title)))}" title="${esc(kt(msT ? tr('Complete milestone') : tr('Complete task'), 'x'))}" ${ro ? 'disabled' : ''}>${t.status === 2 ? ic('check') : ''}</button>
      ${ck ? '' : `<button class="dchip ${t.due ? 'set ' + dueClass(t) : ''}" data-act="date" data-id="${t.id}" title="${esc((t.due ? dueTxt + ' · ' : '') + kt(tr('Change date'), 'd'))}" ${ro ? 'disabled' : ''}>${ic('cal', 's')}<span class="dct">${dueTxt}</span>${t.repeat ? ' ' + ic('repeat', 's') : ''}${rat_has(t) ? ' ' + ic('bell', 's') : ''}</button>`}
      ${ck || tlkR ? '' : [[0, 'sun', tr('Today')], [1, 'sunrise', qdLabel(t)], [-1, 'back', tr('-1 day')]].filter(([n]) => (n === -1 ? qdMinus(t) : n || t.due !== today())).map(([n, i, lab]) => `<button class="iconbtn dq ${t.due === addDays(today(), n) && n >= 0 ? 'on' : ''}" data-act="due-q" data-d="${n}" data-id="${t.id}" title="${esc(n === -1 ? tr('Set to {0}', dayLabel(addDays(t.due, -1))) : kt(n ? qdTitle(t) : tr('Due: {0}', lab), n ? 'Shift+T' : 't'))}" aria-label="${esc(n === -1 ? lab + ': ' + tr('Set to {0}', dayLabel(addDays(t.due, -1))) : n ? (qdPlus(t) ? lab + ': ' : '') + qdTitle(t) : tr('Due: {0}', lab))}">${ic(i, 's')}<span class="dql">${esc(lab)}</span></button>`).join('')}
      ${''/* 2.218.0 A (#2799): "Today" is left out when the task is due today (the date chip says it); "Tomorrow" stays, a further click adds a day */}${ck ? '' : '<span class="dbr" aria-hidden="true"></span>'}<span class="spacer"></span>
      ${ro ? (t.context ? `<span class="rotag" title="${esc(tr('The main task of a subtask assigned to you: read-only, without notes, files and comments'))}">${ic('sub', 's')}${tr('Context')}</span>`
        : `<span class="rotag" title="${esc(tr('View only, shared by {0}', l?.owner_name || ''))}">${ic('eye', 's')}${tr('View only')}</span>`) : `${ck ? '' : `<button class="iconbtn ${t.pinned ? 'on' : ''}" data-act="pin" data-id="${t.id}" title="${t.pinned ? tr('Unpin') : tr('Pin')}" aria-label="${tr('Pin')}" aria-pressed="${!!t.pinned}">${ic(t.pinned ? 'pinf' : 'pin')}<span class="dpw dpin">${esc(t.pinned ? tr('Pinned') : tr('Pin'))}</span></button>
      <button class="iconbtn ${t.priority ? 'flag-' + t.priority : ''}" data-act="prio" data-id="${t.id}" aria-haspopup="menu" title="${esc(tr('Priority') + ': ' + prioWord(t.priority))}" aria-label="${esc(tr('Priority') + ': ' + prioWord(t.priority))}">${ic('flag')}<span class="dpw">${esc(t.priority ? prioWord(t.priority) : tr('Priority'))}</span></button>`}
      ${''/* 2.364.0 D (#3036): Lock lives in "…"; here only a set lock (to unlock) - else "Time" when the module is on */}${ck || !(t.id > 0) ? '' : !tlkL ? (tFor(t) ? ((run) => `<button class="iconbtn dtime ${run ? 'on' : ''}" data-act="timer-toggle" data-id="${t.id}" title="${esc(run ? tr('Stop timer') : tr('Start time tracking'))}" aria-label="${esc(run ? tr('Stop timer') : tr('Start time tracking'))}" aria-pressed="${run}">${ic(run ? 'stop' : 'clock')}<span class="dpw">${esc(tr('Time|menu'))}</span></button>`)(!!S.timer && S.timer.task_id === t.id) : '') : `<button class="iconbtn tlkb ${tlkL ? 'on' : ''}" data-act="tlk-toggle" data-id="${t.id}" title="${esc(tlkL ? tr('Locked: tap to unlock') : tr('Lock: title, description, date and more stay as they are'))}" aria-label="${esc(tr('Lock'))}" aria-pressed="${tlkL}">${ic('lock')}<span class="dpw">${esc(tlkL ? tr('Locked') : tr('Lock'))}</span></button>`}
      <button class="iconbtn" data-act="task-menu" data-id="${t.id}" title="${tr('More')}" aria-label="${tr('More')}">${ic('dots')}</button>`}
      ${asst_detailBtn(t, ck)}${''/* 2.75.0 (#1411): the assistant's menu */}${typeof tbl_btnHtml === 'function' ? tbl_btnHtml(t, ck) : ''}${''/* 2.53.0 C (#1424): the bell of this task (taskbell.js) */}
      ${typeof mw_ok === 'function' && mw_ok() && t.id > 0 ? `<button class="iconbtn" data-mwtask="${t.id}" title="${esc(tr('Open in its own window'))}" aria-label="${esc(tr('Open in its own window'))}">${ic('panel')}</button>` : ''}
      <button class="iconbtn dchatb" data-act="chat-unyield" title="${esc(tr('Chat'))}" aria-label="${esc(tr('Chat'))}">${ic('bot')}</button>
      <button class="iconbtn dclose" data-act="close-detail" title="${tr('Close (Esc)')}" aria-label="${tr('Close (Esc)')}">${ic('x')}</button>
    </div>
    <div class="dbody ${ck ? 'ckbody' : ''}">
      ${crumbsHtml(t, l, parent)}
      ${ml_detailHtml(t)}${''/* 2.320.0 (#3289): the field Projects (multilist.js) */}
      ${le2uLk ? le2u_detailHtml(t) : ''}<div class="dtitle" ${le2uLk ? 'hidden' : ''}><textarea id="d-title" rows="1" placeholder="${tr('Title')}" aria-label="${tr('Title')}" ${tlkR ? 'readonly' : ''}>${esc(t.title)}</textarea></div>
      ${whoOn || jump ? `<div class="dmeta">${whoOn ? dWhoChip(t, tlkR) : ''}${whoOn && myGroup(t.assignee_group_id) ? `<button class="btn sm dtake" data-act="take" type="button">${ic('check', 's')} ${tr('Take it')}</button>` : ''}${jump}</div>` : ''}
      ${!ck && t.due && (t.deadline || nagOf(t)) && t.status === 0 ? `<div class="ddl">${dlChip(t, 'big')}${nagOf(t) ? `<button type="button" class="dnag" data-act="date" data-id="${t.id}" title="${esc(tr('Change'))}">${ic('repeat', 's')}${esc(tr('Repeat reminder') + ': ' + nagLabel(nagOf(t)))}</button>` : ''}</div>` : ''}
      ${!ck && planOf(t) ? `<div class="dplan">${ic('clock', 's')}<span class="dplt">${esc(tr('Planned: {0}', planLabel(t)))}</span>${ro ? '' : `<button type="button" class="linkbtn" data-act="unplan" data-id="${t.id}">${tr('Unplan')}</button>`}</div>` : ''}
      ${t.working ? `<div class="dagw">${agwChip(t)}</div>` : ''}${''/* 2.407.0 A (#3513): an agent works on it */}
      ${t.waiting_at && !ck ? waitBar(t, ro) : ''}
      ${ck ? '' : approvalBar(t, ro)}
      ${ck ? '' : rvw_barHtml(t, ro)}${''/* 2.60.0 C (#1512): reviewer + review state (review.js) */}
      ${ck || ro ? '' : dupHintHtml(t)}
      ${le2uLk ? '' : t.note_locked && typeof ln_html === 'function' ? ln_html(t, ro) : noteOut ? `<div class="muted" id="d-note-wait">${esc(TKN_ERR.has(t.id) ? TKN_ERR.get(t.id) || tr('Not found') : TKN_OFF.has(t.id) ? tr('Only available online.') : tr('Loading…'))}</div>` : `${''/* 2.48.0 (#1642): a locked note replaces the description (notelock.js); 2.280.0 A (#3108): a note still loading: no field */}
      ${mdMode && !ro && (isTouch() || td_mdPenOnly()) ? `<div class="mdbox"><button type="button" class="iconbtn mdpen" data-act="md-edit" title="${esc(tr('Edit description'))}" aria-label="${esc(tr('Edit description'))}">${ic('edit', 's')}</button>` : ''}
      <div class="md ${mdMode ? '' : 'hidden'} ${mdClamp ? 'clamp' : ''}" id="d-md" title="${tlkL ? esc(tr('Locked')) : td_mdPenOnly() ? '' : tr('Click to edit')}">${mdMode ? mdMentions(mdTaskRefs(renderMd(t.content, false, {lid: t.list_id}), true), t) : ''}</div>${mdMode && !ro && (isTouch() || td_mdPenOnly()) ? '</div>' : ''}
      ${mdLong ? `<button class="linkbtn mdmore" data-act="md-more" aria-expanded="${!mdClamp}">${mdClamp ? tr('Show more') : tr('Show less')}</button>` : ''}
      ${mdOpen && mdMode ? `<button class="btn sm mdsub" data-act="md-subtasks">${ic('sub', 's')} ${tr('Turn the open checklist items into subtasks')}</button>` : ''}
      <textarea id="d-content" class="dcontent ${mdMode ? 'hidden' : ''}" placeholder="${ck ? tr('Note') : tr('Description')}" aria-label="${ck ? tr('Note') : tr('Description')}" ${tlkR ? 'readonly' : ''}>${esc(t.content)}</textarea>
      ${''/* 2.364.0 D (#3036): "Lock note" is in the "…" menu */}${typeof rf_btnHtml === 'function' ? rf_btnHtml('d', ro || tlkR || t.id < 0) : '' /* 2.53.0 (#1449): Insert reference (touch) */}`}
      ${ck ? '' : e2eNoteHtml(t)}${''/* 2.42.0 (#828): my encrypted note (e2e.js) */}
      ${ck ? '' : wk_mentionHtml(t)}${''/* 2.49.0 (#1199): mentioned in knowledge pages (wiki.js) */}
      ${ck || typeof hbm_taskLinkHtml !== 'function' ? '' : hbm_taskLinkHtml(t)}${''/* 2.141.0 B (#2139): the e-mail the task was made from (hubmail.js) */}
      ${ck || !pz_show(t, 'docs', (DLK[t.id]?.docs || []).length) ? '' : dlk_taskHtml(t)}${''/* 2.154.0 A (#1111): the documents linked with the task */}
      ${ck || typeof rt9_detailHtml !== 'function' ? '' : rt9_detailHtml(t)}${''/* 2.59.0 B (#1375): related tasks (related.js) */}
      ${msT && t.id > 0 ? `<div class="dsec mssec" id="d-ms">${msReportHtml(t)}</div>` : ''}
      ${(() => {  // 2.24.0 (UX-41)
        // 2.380 F (#3435): every section with content stands on its own above "More details" (it holds only the empty ones)
        for (const k of DFOLD_KEYS) if (k !== 'comments' || !split) SEC[k] = dfWrap(k, SEC[k], t, ncm);
        const keep = k => (k === 'snippets' && (snipCount(t) || S.snip?.tid === t.id || (listById(t.list_id)?.ptype === 'software' && pz_on(t.list_id, 'repo'))))  // 2.35.0 (#1095)
          || (k === 'custom' && (dfSum('custom', t)[0] || fieldsOf(t.list_id).some(cfst_on)))  // 2.410.0 A (#3514): a stage bar is seen at once
          || (k === 'attachments' && (t.attachments || []).length) || (k === 'video' && typeof vdr_count === 'function' && vdr_count(t)) || (k === 'deps' && (t.waiting_at || (t.blockers || []).length)) || (k === 'links' && (((S.tcontacts || {})[t.id] || []).length || ((S.evlinks || {})[t.id] || []).length))
          || (k === 'tags' && (t.tags || []).length + (t.ltags || []).length) || (k === 'time' && dfSum('time', t)[0])
          || (k === 'fields' && (t.url || t.ttype || t.milestone_id || isMs(t)));
        const top = DETAIL_TOP.map(k => SEC[k]).concat(DETAIL_MORE.filter(keep).map(k => SEC[k]));
        const rest = DETAIL_MORE.filter(k => !keep(k)).map(k => SEC[k]).filter(x => x && x.trim());
        const sum = moreSummary(t, DETAIL_MORE.filter(k => !keep(k)));
        return top.join('\n      ') + (rest.length ? `<details class="dmore" id="d-more" ${LS.get('dMore', false) ? 'open' : ''}><summary>${ic('chev', 's fcar')}<span>${tr('More details')}</span>${sum ? `<span class="dmsum muted">${esc(sum)}</span>` : ''}</summary>${rest.join('\n')}</details>` : '') + (split ? '' : SEC.comments);
      })()}
    </div>
    ${split ? `<div class="dsgrip" id="d-sgrip" role="separator" tabindex="0" aria-orientation="horizontal" aria-controls="d-cpane" aria-label="${esc(tr('Size of the comments area'))}" title="${esc(tr('Drag to resize; double-click or Enter folds the comments'))}" aria-valuemin="${CSPL_MIN}" aria-valuemax="${CSPL_MAX}" aria-valuenow="${dsTop()}"></div><div class="dcpane" id="d-cpane">${SEC.comments}</div>` : ''}
    <div class="dbot">${cmOk && !(cm === 'full' && cmtNew()) ? cmComposer(t) : ''}<div class="dfoot"><span class="dfc" title="${esc(createdLine(t))}">${esc(createdLine(t))}</span>
      <span class="spacer"></span>
      ${ck ? '' : runItems().filter(x => x.tid === t.id).map(x => `<button class="drun k-${x.k}" data-act="run-pop" title="${esc(tr(RUN_KIND[x.k][1]))}">${ic(RUN_KIND[x.k][0], 's')}<span ${x.attr}>${x.txt}</span><span class="drl">${tr(RUN_KIND[x.k][1])}</span></button>`).join('')}
      </div></div>`);
  // 2.4.1 (#385): no Delete / Track time in the footer any more (Delete sat right below the comment box's Send on a phone);
  // both are in the task's "…" menu (Delete with undo), a running timer still shows here as its pill
  $('#detail').classList.toggle('tlk', tlkL);  // 2.36.0 (#1118)
  $('#detail').classList.toggle('dsplit', split); if (split) dsApply(); else $('#detail').classList.remove('dsfold');
  autosize($('#d-title')); autosize($('#d-content')); autosize($('#c-input'));
  if (isMobile() && $('#stale')) staleDraw();
}
// U17: the open "- [ ]" lines of a description become real subtasks (one undo step); ticked lines stay in the text
async function mdToSubtasks() {
  if (typeof flushSaves === 'function') await flushSaves();  // 2.273.0 C (#3051): the typed description is saved first, then read (else it was lost)
  const t = taskById(S.sel); if (!t || !canEdit(t) || depthOf(t) >= maxDepth() - 1) return;
  const keep = [], items = [];
  // 2.40.0 (#1409): the lines indented below an item (up to the next line that is not) become the new subtask's description
  const lines = String(t.content || '').split('\n'), ind = x => x.match(/^\s*/)[0].replace(/\t/g, '    ').length;
  for (let i = 0; i < lines.length; i++) {
    const ln = lines[i], m = ln.match(/^\s*[-*]\s+\[ \]\s*(.*\S)/); if (!m) { keep.push(ln); continue; }
    const body = []; let j = i + 1;
    for (; j < lines.length; j++) {
      if (!lines[j].trim()) { let k = j + 1; while (k < lines.length && !lines[k].trim()) k++; if (k < lines.length && ind(lines[k]) > ind(ln)) { body.push(''); continue; } break; }
      if (ind(lines[j]) <= ind(ln)) break;
      body.push(lines[j]);
    }
    const cut = Math.min(...body.filter(x => x.trim()).map(x => x.match(/^\s*/)[0].length));
    items.push({title: m[1].trim(), content: body.map(x => x.slice(cut)).join('\n').trim()});
    i = j - 1;
  }
  if (!items.length) return;
  await histGroup(async () => {
    for (const it of items) await createTask({title: it.title.slice(0, 500), ...(it.content ? {content: it.content} : {}), parent_id: t.id, list_id: t.list_id, section_id: t.section_id});
    await patchUndoable(t.id, {content: keep.join('\n').replace(/\n{3,}/g, '\n\n').trim(), _act: 'md_subtasks'});
  }, trn('{0} checklist item of {1} is now a subtask', '{0} checklist items of {1} are now subtasks', items.length, qn(t.title.slice(0, 40))));
  S.editContent = false; renderDetail();
  offerUndo(trn('{0} subtask added', '{0} subtasks added', items.length), HIST.undo[HIST.undo.length - 1]);
}
function linkField(t, ro) {
  if (t.url && !S.editLink) return `<div class="linkf">${flkLink(t.url, 'linkchip', `${ic(flkIs(t.url) ? 'folder' : 'link', 's')}<span>${esc(urlHost(t.url))}</span>`)}${ro ? '' : `<button class="iconbtn" data-act="link-edit" title="${tr('Edit link')}">${ic('edit', 's')}</button><button class="iconbtn" data-act="link-rm" title="${tr('Remove website link')}">${ic('x', 's')}</button>`}</div>`;
  return ro ? '' : `<input id="d-url" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('https://… or smb://…'))}" aria-label="${esc(tr('Link'))}" value="${esc(t.url || '')}" enterkeyhint="done">`;
}
// 2.41.0 (#1475): "Add link" (task menu, More details): opens the panel's link field; Enter saves, Esc / empty cancels
function linkAdd(id) {
  if (!canEdit(taskById(id))) { roToast(); return; }
  if (S.sel !== id) openDetail(id);
  S.editLink = true; renderDetail();
  const m = $('#d-more'); if (m) m.open = true;
  setTimeout(() => $('#d-url')?.focus(), 0);
}
document.addEventListener('focusout', e => {  // an empty link field that loses the focus folds away again
  if (e.target.id !== 'd-url' || !S.editLink) return;
  setTimeout(() => { if (S.editLink && !taskById(S.sel)?.url && !($('#d-url')?.value || '').trim() && document.activeElement?.id !== 'd-url') { S.editLink = false; renderDetail(); } }, 0);
});
async function saveLink(v) {
  const t = taskById(S.sel); if (!t) return;
  v = (v || '').trim();
  if (v && !/^https?:\/\//i.test(v) && /^[\w-]+(\.[\w-]+)+(\/\S*)?$/.test(v)) v = 'https://' + v;  // "github.com/x" -> https://
  if (v && !validLink(v)) { toast(tr('The link must be a web address (https://…) or a file link (smb://…, file://…)')); return; }  // 2.35.0 (#186)
  S.editLink = false;
  if ((t.url || '') === v) { renderDetail(); return; }
  await patchTask(t.id, {url: v || null});
}
// 2.27.0 (#999): while a field of the task panel has the focus (title, description, subtasks, fields), the server learns
// "someone is editing this task" (every 20 s while typing): an agent's automatic tidy-up waits until it is left alone
{
  let last = 0, lastId = 0;
  const ping = () => {
    const a = document.activeElement, id = S.sel;
    if (!(id > 0) || !a || !a.closest?.('#detail') || !editFocused() || document.hidden || !collab()) return;
    const t = taskById(id); if (!t || !listById(t.list_id)?.agent_tidy || listById(t.list_id).agent_tidy === 'off') return;
    if (id === lastId && Date.now() - last < 20000) return;
    last = Date.now(); lastId = id;
    fetch(`/api/tasks/${id}/editing`, {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).catch(() => {});  // never queued offline
  };
  document.addEventListener('focusin', ping);
  document.addEventListener('input', ping);
}

// ---- 2.32.0 (#1071): phones: a sideways swipe on the properties of the open task (title, date, list, assignee …, not the
// comments, the comment box or a field) goes to the next (left) / previous (right) task of the view it was opened from, in its
// order (sorting, filter). The panel follows the finger and slides; at the first / last task it springs back. "3 of 12"
// shows for a moment at the top. Not from the screen edges (the phone's own Back gesture), not while text is selected, not
// in areas that scroll sideways (tables, code, images). What was typed is saved first (flushSaves).
const DSW_EDGE = 28, DSW_MIN = 70;
let dsw = null;
function dswIds() { return [...new Set(vl_ids())].filter(i => S.tasks.has(i)); }  // 2.65.0 (#1825): vl_ids = also the rows a long list does not draw
function dswBlocked(el) {
  const f = el.closest('textarea, input, select, [contenteditable="true"]');
  if (f && (f === document.activeElement || f.matches('select, input[type="range"]'))) return true;  // typing / marking in a field (a field without the focus, e.g. the title, may be swiped over)
  if (el.closest('pre, table, img, video, .dsgrip, #d-tl, .dcpane, .dbot, .subs .trow, .menu-list')) return true;
  for (let x = el; x && x.id !== 'detail'; x = x.parentElement) {
    if (x.scrollWidth > x.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(x).overflowX)) return true;
  }
  return false;
}
document.addEventListener('touchstart', e => {
  dsw = null;
  if (!S.sel || !isMobile() || e.touches.length !== 1 || $('.modal') || $('#pop:not(.hidden)') || (typeof nswOn === 'function' && nswOn())) return;  // 2.122.0 (#2314): opened from the news: collab.js swipes
  const d = $('#detail'), el = e.target;
  if (!d || d.classList.contains('multi') || !el.closest?.('#detail .dbody, #detail .dtop') || dswBlocked(el)) return;
  const t0 = e.touches[0];
  if (t0.clientX < DSW_EDGE || t0.clientX > innerWidth - DSW_EDGE) return;
  const sel = getSelection?.(); if (sel && !sel.isCollapsed && String(sel).trim()) return;
  dsw = {x: t0.clientX, y: t0.clientY, dx: 0, lock: null, d};
  // 2.32 review: the non-passive move listener only lives while a swipe may start (scrolling elsewhere stays passive)
  document.addEventListener('touchmove', dswTouchMove, {passive: false});
}, {passive: true});
function dswTouchMove(e) {
  if (!dsw || (typeof lp !== 'undefined' && lp?.active)) return;
  const t = e.touches[0], dx = t.clientX - dsw.x, dy = t.clientY - dsw.y;
  if (!dsw.lock) {
    if (Math.hypot(dx, dy) < 10) return;
    dsw.lock = Math.abs(dx) > Math.abs(dy) * 1.5 ? 'x' : 'y';
    if (dsw.lock === 'y') { dsw = null; return; }
    const ids = dswIds(), i = ids.indexOf(S.sel);
    if (i < 0) { dsw = null; return; }
    dsw.ids = ids; dsw.i = i;
    dsw.d.classList.add('dswipe');
  }
  if (e.cancelable) e.preventDefault();
  const end = (dx < 0 && dsw.i >= dsw.ids.length - 1) || (dx > 0 && dsw.i <= 0);
  dsw.dx = end ? dx / 3 : dx;  // at the first / last task it only gives a little
  dswMove(dsw.d, dsw.dx);
}
function dswOff() { document.removeEventListener('touchmove', dswTouchMove, {passive: false}); }
function dswMove(d, x, anim) {
  for (const el of $$(':scope > .dtop, :scope > .dbody, :scope > .dsgrip, :scope > .dcpane, :scope > .dbot', d)) {
    el.style.transition = anim && !reducedMotion() ? 'transform .18s ease-out, opacity .18s ease-out' : 'none';
    el.style.transform = x ? `translateX(${x}px)` : '';
    el.style.opacity = x ? String(Math.max(.4, 1 - Math.abs(x) / innerWidth)) : '';
  }
}
function dswEnd() {
  const st = dsw; dsw = null;
  if (!st || st.lock !== 'x') return;
  st.d.classList.remove('dswipe');
  dswAt = Date.now();
  const dir = st.dx < -DSW_MIN ? 1 : st.dx > DSW_MIN ? -1 : 0, next = dir ? st.ids[st.i + dir] : null;
  if (!next) { dswMove(st.d, 0, true); return; }  // too short, or the first / last task: springs back
  const w = innerWidth, slow = !reducedMotion();
  dswMove(st.d, -dir * w, true);
  setTimeout(async () => {
    await flushSaves();
    openDetail(next, {replace: true});
    const d = $('#detail'); if (!d) return;
    dswMove(d, dir * w * .35); d.offsetWidth;  // the new one comes in from the other side
    dswMove(d, 0, true);
    setTimeout(() => dswMove(d, 0), 220);
    dswPos(st.ids.indexOf(next) + 1, st.ids.length);
  }, slow ? 170 : 0);
}
// "3 of 12" for a moment at the top of the panel (and for screen readers)
function dswPos(n, of) {
  const d = $('#detail'); if (!d) return;
  let p = $('#dswpos');
  if (!p) { p = document.createElement('div'); p.id = 'dswpos'; p.className = 'dswpos'; p.setAttribute('role', 'status'); p.setAttribute('aria-live', 'polite'); document.body.appendChild(p); }
  p.textContent = tr('{0} of {1}', n, of);
  p.classList.add('on'); clearTimeout(dswPos.t); dswPos.t = setTimeout(() => p.classList.remove('on'), 1600);
}
// the lift that ends a swipe does not also press what is under the finger
let dswAt = 0;
document.addEventListener('click', e => { if (Date.now() - dswAt < 400 && e.target.closest?.('#detail')) { e.stopPropagation(); e.preventDefault(); } }, true);
document.addEventListener('touchend', () => { dswOff(); dswEnd(); });
document.addEventListener('touchcancel', () => { dswOff(); if (dsw?.lock === 'x') { dsw.d.classList.remove('dswipe'); dswMove(dsw.d, 0, true); } dsw = null; });


// ---- 2.33.0 (#1087): iPhone: the focus in the comment box made iOS pan the page up by the keyboard (visualViewport.offsetTop
// ~310 px) to reveal the box -- the task panel is fixed to the layout viewport, so its header went out of sight above. While
// a real keyboard is up, the page is panned (offsetTop > 0) and the focus is in the task panel's bottom box, the panel itself
// sits exactly in the visible part (top --vvt, height --vvh, like the phone chat, #478 N8): header at the top, the box right
// above the keyboard (it is visible then, vvPin leaves it alone). Android (the layout shrinks, offsetTop 0) never gets it.
function detailKbFit(kb) {
  const d = $('#detail'); if (!d) return;
  const vv = window.visualViewport, a = document.activeElement;
  const on = !!(kb && vv && vv.offsetTop > 1 && isMobile() && editFocused() && a?.closest?.('#detail .dbot'));
  if (d.classList.contains('vvfix') !== on) d.classList.toggle('vvfix', on);
}
// 2.154.0 A (#1111): "Document: <title>" for every document linked with the task that I may see (a tap opens it; the server
// names none of the others). Filled after the answer (cached a minute), the detail is not redrawn
const DLK = {};  // task id -> {at, docs}
function dlk_taskHtml(t) {
  if (!t || t.context || !(t.id > 0) || !S.me) return '';
  const c = DLK[t.id];
  if (!c || Date.now() - c.at > 60000) dlk_load(t.id);
  return `<div class="dlklnk" data-dlklnk="${t.id}">${c ? dlk_inner(c.docs) : ''}</div>`;
}
const dlk_inner = docs => (docs || []).map(x => `<a class="linkbtn" href="#docs/${+x.id}">${ic('file', 's')}<span>${esc(tr('Document: {0}', x.name))}</span></a>`).join('');
async function dlk_load(tid) {
  DLK[tid] = {at: Date.now(), docs: DLK[tid]?.docs || []};
  let j; try { j = await rawFetch('GET', `/api/tasks/${tid}/docs`); } catch { return; }
  DLK[tid] = {at: Date.now(), docs: j.docs || []};
  for (const el of document.querySelectorAll(`[data-dlklnk="${tid}"]`)) el.innerHTML = dlk_inner(j.docs);
}
