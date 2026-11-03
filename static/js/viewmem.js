// @ts-check
/* Kalmido web client: 2.413.0 A (#3439) -- every view keeps its place. Leaving a view (Office, Projects, a list, the
   calendar, documents, the chat overview, an open office document, ...) stores where it stood; coming back shows the same
   picture again, also after a reload (localStorage, this browser only, at most VM_MAX views, the oldest goes).
   - What is kept per view: the main area's place and the place of every box inside it that was scrolled (the preview of
     an office document, a list with its own scroll), the search text of its search field, and the task open in the panel
     (opened again only while it is still open: a completed or deleted task is not).
   - The left sidebar keeps its own place per area (its panel changes with the area; a click inside the same area never
     moves it).
   - A place is the entry at the top of the box (an anchor: a row's data-id, a heading, ...) and how far it stood from the
     top; the pixel height is only the fallback (rows added above do not shift the picture).
   - Restoring waits for the real view: it runs after each drawing of the view (renderView, a module loaded later, the
     office data arriving) until the anchor is there, and ends at the first own scroll, key or tap.
   - A workspace switch starts its views from the top (the workspace is part of the key).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const VM_MAX = 50, VM_LS = 'viewMem';
/** @type {any} */
const VM = {key: '', side: '', want: null, wantSide: null, obs: null, t: 0, ts: 0, until: 0, boxes: new Set(), keep: null, hash: '', fresh: '', noSel: false};
// the entries a place is anchored on (the first one at the top of a box)
const VM_SEL = '[data-id],[data-vlg],[data-key],[data-go],[data-k],[id],h1,h2,h3,h4,.ghead,li,tr,label';
const VM_ATTR = ['data-id', 'data-vlg', 'data-key', 'data-go', 'data-k'];
const vm_ws = () => typeof wsCur === 'function' ? wsCur() : 'all';
// the key of the view shown now: a task view by its key, any other by its address (office/offers/12 = that document)
function vm_key() {
  const r = S.route; if (!r || !r.mod || r.mod === 'team' || (r.mod === 'agents' && r.agent)) return '';  // a conversation opens at its newest message
  return vm_ws() + '|' + (r.mod === 'tasks' ? 't:' + r.key : location.hash.slice(1).split('?')[0] || r.mod);
}
const vm_sideKey = () => 'side|' + vm_ws() + '|' + (typeof sbb_area === 'function' ? sbb_area() : 'tasks');
const vm_all = () => { const o = LS.get(VM_LS, {}); return o && typeof o === 'object' && !Array.isArray(o) ? o : {}; };
function vm_store(k, rec) {
  if (!k) return;
  const o = vm_all(); o[k] = {...rec, at: Date.now()};
  const ks = Object.keys(o); if (ks.length > VM_MAX) ks.sort((a, b) => (o[a].at || 0) - (o[b].at || 0)).slice(0, ks.length - VM_MAX).forEach(x => delete o[x]);
  LS.set(VM_LS, o);
}
// a selector that finds el again inside root: {s, i: its index among the matches, t: the text of an entry without its own name}
// #3506 (main red, after #3439): CSS.escape where the browser has it, else a plain escape (jsdom of the tests has no CSS object)
const vm_esc = v => typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(v) : String(v).replace(/[^\w-]/g, c => '\\' + c);
/** @param {Element} el @param {Element} root */
function vm_sel(el, root) {
  const tag = el.tagName.toLowerCase(), cls = el.classList[0] ? '.' + vm_esc(el.classList[0]) : '';
  let s = '', t = '';
  if (el.id && !/^\d/.test(el.id)) s = '#' + vm_esc(el.id);
  else { const a = VM_ATTR.find(x => el.hasAttribute(x)); if (a) s = `${tag}${cls}[${a}="${vm_esc(el.getAttribute(a) || '')}"]`; }
  if (!s) { s = tag + cls; t = (el.textContent || '').trim().slice(0, 40); }
  const i = [...root.querySelectorAll(s)].indexOf(el);
  return i < 0 ? null : {s, i, ...(t ? {t} : {})};
}
/** @param {Element} root @param {any} a */
function vm_find(root, a) {
  if (!a?.s) return null;
  let all; try { all = [...root.querySelectorAll(a.s)]; } catch { return null; }
  const txt = x => (x.textContent || '').trim().slice(0, 40), el = all[a.i || 0];
  if (el && (!a.t || txt(el) === a.t)) return el;
  return a.t ? all.find(x => txt(x) === a.t) || null : all[0] || null;
}
// the entry at the top of a box (not a sticky head, not a wrapper taller than the box)
/** @param {Element} box */
function vm_anchor(box) {
  const br = box.getBoundingClientRect();
  for (const el of box.querySelectorAll(VM_SEL)) {
    const r = el.getBoundingClientRect();
    if (!r.height || r.top < br.top - 1 || r.top >= br.bottom || r.height >= box.clientHeight) continue;
    const ps = getComputedStyle(el).position, pp = el.parentElement ? getComputedStyle(el.parentElement).position : '';
    if (ps === 'sticky' || ps === 'fixed' || pp === 'sticky' || pp === 'fixed') continue;
    const s = vm_sel(el, box); if (s) return {...s, o: Math.round(r.top - br.top)};
  }
  return null;
}
/** @param {Element} box */
const vm_box = box => ({y: Math.round(box.scrollTop), ...(box.scrollTop > 0 ? {a: vm_anchor(box)} : {})});
// back to a kept place; true = the anchor was found (or nothing to do)
/** @param {Element} box @param {any} m */
function vm_put(box, m) {
  if (!m) return true;
  if (!box.clientHeight) return false;  // hidden (the phone's closed drawer): later
  if (!m.y) { if (box.scrollTop) box.scrollTop = 0; return true; }
  if (Math.abs(box.scrollTop - m.y) >= 1) box.scrollTop = m.y;
  if (box.id === 'view' && typeof vl_sync === 'function') vl_sync();  // a long list draws the rows near the place first
  const el = m.a && vm_find(box, m.a);
  if (!el) return !m.a && box.scrollHeight - box.clientHeight >= m.y - 1;
  const d = el.getBoundingClientRect().top - box.getBoundingClientRect().top - m.a.o;
  if (Math.abs(d) >= 1) box.scrollTop += d;
  return true;
}
const vm_selNow = () => S.route.mod !== 'tasks' ? null : S.sel || (VM.keep?.key === VM.key ? VM.keep.sel : null);
// the place of the view shown now (main area, its scrolled boxes, search fields, the open task)
function vm_snap() {
  const v = document.getElementById('view'); if (!v) return null;
  const rec = {...vm_box(v), in: /** @type {any[]} */ ([]), q: /** @type {any[]} */ ([]), sel: vm_selNow()};
  for (const b of VM.boxes) if (b.isConnected && v.contains(b) && b !== v) { const s = vm_sel(b, v); if (s) rec.in.push({...s, ...vm_box(b)}); }
  for (const f of v.querySelectorAll('input[type="search"], .search input, .ctsearch input')) {
    const x = /** @type {HTMLInputElement} */ (f); if (x.value) { const s = vm_sel(x, v); if (s) rec.q.push({...s, v: x.value}); }
  }
  return rec;
}
function vm_save() {
  clearTimeout(VM.t); VM.t = 0;
  if (VM.want || !VM.key) return;
  const r = vm_snap(); if (r) vm_store(VM.key, r);
}
function vm_saveSide() {
  clearTimeout(VM.ts); VM.ts = 0;
  const sd = document.getElementById('side'); if (VM.wantSide || !VM.side || !sd || !sd.clientHeight) return;
  vm_store(VM.side, vm_box(sd));
}
// route(): the view on screen is left (its place is written at once, the next drawing is already the new view); the
// sidebar too (its panel may change with the view)
function vm_leave() {
  if (VM.key && !VM.want) vm_save();
  else if (VM.key) { const o = vm_all()[VM.key], sel = vm_selNow(); if (o && o.sel !== sel) vm_store(VM.key, {...o, sel}); }  // still on its way back: only the open task
  if (VM.side && !VM.wantSide) vm_saveSide();
}
// on a phone / touch screen the task panel closes on any change of the address (detail.js popstate) before route() runs:
// a change to another view keeps the task as the view's open task (capture: before the other popstate listeners)
addEventListener('popstate', () => { if (S.sel && VM.key && location.hash !== VM.hash) VM.keep = {key: VM.key, sel: S.sel}; }, true);
// after each drawing of the view (renderView): a view entered anew gets its kept place
function vm_after() {
  const k = vm_key(), sk = vm_sideKey();
  if (sk !== VM.side) { clearTimeout(VM.ts); VM.ts = 0; VM.side = sk; VM.wantSide = vm_all()[sk] || null; }  // (the panel before was written by vm_leave)
  VM.hash = location.hash;
  const fresh = !!VM.fresh && location.hash.slice(1) === VM.fresh;
  if (k !== VM.key) {
    clearTimeout(VM.t); VM.t = 0;  // a save still waiting belonged to the view before
    VM.key = k; VM.boxes = new Set(); VM.keep = null; if (fresh) VM.fresh = '';
    const rec = k && !fresh ? vm_all()[k] || null : null;  // 2.484.0 (#3949): a call through the bar starts at the top
    VM.want = rec ? {...rec, opened: !!VM.noSel} : null;  // 2.497.0 (#4048): VM.noSel = entered by a workspace switch
  }
  vm_try();
}
// 2.484.0 (#3949): a tap on a button of the phone's bottom bar is a new call (the computer's area bar keeps bringing the place back, #3439): the page it opens starts at the top; Back
// (no tap on the bar) and links inside a page bring a view back at its place as before
window.addEventListener('click', e => { VM.fresh = (e.target instanceof Element && e.target.closest('#tabs [data-go]')?.getAttribute('data-go')) || ''; }, true);
function vm_try() {
  if (!document) return;  // #3506 (after #3439): a late observer call after the window closed (tests) finds no document
  const v = document.getElementById('view'), sd = document.getElementById('side');
  if (VM.wantSide && sd && vm_put(sd, VM.wantSide)) VM.wantSide = null;
  const w = VM.want;
  if (w && v) {
    let ok = vm_put(v, w);
    for (const b of w.in || []) if (!b.done) { const el = vm_find(v, b); if (el && vm_put(el, b)) b.done = true; else ok = false; }
    for (const q of w.q || []) {
      const f = /** @type {HTMLInputElement|null} */ (vm_find(v, q));
      if (f && !f.value && !q.done) { f.value = q.v; q.done = true; f.dispatchEvent(new Event('input', {bubbles: true})); }
    }
    const t = w.sel && !w.opened && !S.sel && S.route.mod === 'tasks' ? taskById(w.sel) : null;
    if (w.sel && !w.opened && (t || S.tasks.size)) {  // (before the first load: later)
      w.opened = true;
      if (t && t.status === 0 && !t.deleted_at && !S.sel) openDetail(w.sel);
    }
    if (ok) VM.want = null;
  }
  vm_watch();
}
// while a place waits, every change of the view / sidebar tries again (the real drawing, no fixed time); 10 s at most
function vm_watch() {
  const on = !!(VM.want || VM.wantSide);
  if (!on) { VM.obs?.disconnect(); VM.obs = null; return; }
  if (!VM.obs) {
    VM.until = Date.now() + 10000;
    VM.obs = new MutationObserver(() => { if (Date.now() > VM.until) { VM.want = VM.wantSide = null; vm_watch(); } else vm_try(); });
    const v = document.getElementById('view'), sd = document.getElementById('side');
    if (v) VM.obs.observe(v, {childList: true, subtree: true});
    if (sd) VM.obs.observe(sd, {childList: true, subtree: true, attributes: true, attributeFilter: ['class']});
  }
}
// an own scroll, key or tap ends the waiting (the person moves on from there)
/** @param {Event} e */
const vm_mine = e => {
  if (!VM.want && !VM.wantSide) return;
  const sd = document.getElementById('side'), inSide = !!(sd && e.target instanceof Node && sd.contains(e.target));
  if (inSide) VM.wantSide = null; else VM.want = null;
  vm_watch();
};
for (const ev of ['wheel', 'touchstart', 'keydown', 'mousedown']) document.addEventListener(ev, vm_mine, {capture: true, passive: true});
document.addEventListener('scroll', e => {
  const t = e.target; if (!(t instanceof Element)) return;
  const v = document.getElementById('view'), sd = document.getElementById('side');
  if (v && (t === v || v.contains(t))) { if (t !== v) VM.boxes.add(t); if (!VM.want) { clearTimeout(VM.t); VM.t = setTimeout(vm_save, 250); } }
  else if (sd && t === sd && !VM.wantSide) { clearTimeout(VM.ts); VM.ts = setTimeout(vm_saveSide, 250); }
}, {capture: true, passive: true});
addEventListener('pagehide', () => { if (VM.t) vm_save(); if (VM.ts) vm_saveSide(); });
