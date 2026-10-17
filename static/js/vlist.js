/* Kalmido web client: long task lists draw only the rows near the visible part (2.65.0, #1825). A view with more than
   VL_MIN rows is built per group as [top spacer][the rows of the window][bottom spacer]; scrolling (once per frame) moves
   the window, measured row heights (an average for the rows not drawn yet) keep the scroll height. A row added or removed
   above the visible part changes its spacer by the same height, so nothing visible moves. The order of all rows, also of
   those not drawn, comes from the data: selection, keyboard and drops use vl_ids(), not the DOM. Below VL_MIN nothing
   changes. Browser search (Ctrl+F) only finds the drawn rows (accepted).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const VL_MIN = 300;  // rows of a view from which it is windowed
// on: the view drawn last is windowed; key: its fl_sig(); segs / by: its groups; wins: the window per view and group
// ({id, a, c, tp}); hs: measured item heights per view (task id -> px); st: the scroll position per view
const VL = {on: false, key: '', segs: [], by: new Map(), wins: new Map(), hs: new Map(), st: new Map(), est: 0, raf: 0, fresh: false, bud: 0, w: 0};
const vl_view = () => document.getElementById('view');
const vl_map = (m, k) => m.get(k) || m.set(k, new Map()).get(k);
// a view starts: true = it is windowed (n rows); the groups then call vl_seg instead of joining their rows
function vl_begin(n) {
  const v = vl_view();
  if (!(n > VL_MIN && v) || VL.off) { VL.on = false; return false; }  // VL.off: the drawing before 2.65.0, for measurements (tests)
  const k = typeof fl_sig === 'function' ? fl_sig() : S.route.key;
  VL.fresh = VL.key !== k || !v.querySelector('.vlpad');
  VL.on = true; VL.key = k; VL.segs = []; VL.by = new Map(); VL.w = VL.w || innerWidth;
  VL.bud = (v.clientHeight || innerHeight) * 2.5;  // a group without a window yet draws from the top (vl_after moves it)
  return true;
}
// the row ids an item stands for: the task and, in a tree, its open (dsx: all) subtasks that are shown
const vl_tree = dsx => function ids(t) {
  const kids = children(t.id), n = dsx ? kids.length : kids.filter(k => k.status === 0).length;
  const out = [t.id];
  if (n && !S.collapsed.has('t' + t.id)) for (const k of kids) if (k.status === 0 || dsx) out.push(...ids(k));
  return out;
};
const vl_hm = () => vl_map(VL.hs, VL.key);
const vl_h = (sg, t) => vl_hm().get(t.id) ?? (VL.est || 44) * (sg.ids ? sg.ids(t).length : 1);
function vl_sum(sg, a, b) { let s = 0; for (let i = a; i < b; i++) s += vl_h(sg, sg.arr[i]); return s; }
// every top-level node of an item carries data-vlg = its task id (the rows of a task and its subtasks, a list head)
const vl_mark = (html, id) => html.replace(/<div class="(trow|mthl)(?=[\s"])/g, `<div data-vlg="${id}" class="$1`);
const vl_padHtml = (sg, w, px) => `<${sg.tag} class="vlpad" data-k="vl${w}:${esc(sg.key)}" style="height:${Math.max(0, Math.round(px))}px" aria-hidden="true"></${sg.tag}>`;
// a group of a windowed view: arr = its items (tasks), fn(t, i) = the HTML of item i, ids(t) = the row ids of an item (false:
// the items are no task rows, e.g. contacts);
// tag = the spacers' element (li inside a list)
function vl_seg(key, arr, fn, ids, tag = 'div') {
  key = String(key); while (VL.by.has(key)) key += '+';
  const n = arr.length, w = vl_map(VL.wins, VL.key).get(key), sg = {key, arr, fn, ids, tag, a: 0, b: 0, tp: 0};
  VL.segs.push(sg); VL.by.set(key, sg);
  if (w) {
    const i = w.id != null ? arr.findIndex(t => t.id === w.id) : -1;
    sg.a = Math.min(n, i >= 0 ? i : w.a); sg.b = Math.min(n, sg.a + w.c);
    sg.tp = sg.a ? (i >= 0 && w.tp != null ? w.tp : vl_sum(sg, 0, sg.a)) : 0;
  } else { let b = 0; while (b < n && VL.bud > 0) VL.bud -= vl_h(sg, arr[b++]); sg.b = b; }
  let h = vl_padHtml(sg, 't', sg.tp);
  for (let i = sg.a; i < sg.b; i++) h += vl_mark(fn(arr[i], i), arr[i].id);
  return h + vl_padHtml(sg, 'b', vl_sum(sg, sg.b, n));
}
// the box that scrolls a group: a list with its own scroll (data-vlsc, e.g. the contacts beside the card) or the view
const vl_sc = (tp, v) => { const w = tp.closest('[data-vlsc]'); return w && w.scrollHeight > w.clientHeight + 1 ? w : v; };
const vl_pad = (v, sg, w) => v.querySelector(`.vlpad[data-k="vl${w}:${sg.key.replace(/["\\]/g, '\\$&')}"]`);
// the drawn nodes between a group's spacers, by item (task id as text -> nodes)
function vl_nodes(tp, bp) {
  const m = new Map();
  for (let n = tp.nextElementSibling; n && n !== bp; n = n.nextElementSibling) { const g = n.dataset.vlg; if (g != null) (m.get(g) || m.set(g, []).get(g)).push(n); }
  return m;
}
// measured heights of the drawn items (from the top of an item to the top of the next one: margins count)
function vl_measure(v) {
  const H = vl_hm(); let sum = 0, cnt = 0;
  for (const sg of VL.segs) {
    const tp = vl_pad(v, sg, 't'), bp = vl_pad(v, sg, 'b'); if (!tp || !bp) continue;
    const m = vl_nodes(tp, bp);
    let prev = null, py = 0;
    for (let i = sg.a; i <= sg.b; i++) {
      const el = i < sg.b ? m.get(String(sg.arr[i].id))?.[0] : bp; if (!el) { prev = null; continue; }
      const y = el.getBoundingClientRect().top;
      if (prev != null) { const h = y - py; if (h > 0) { H.set(prev, h); sum += h; cnt++; } }
      prev = i < sg.b ? sg.arr[i].id : null; py = y;
    }
  }
  if (cnt) VL.est = VL.est ? VL.est * .7 + (sum / cnt) * .3 : sum / cnt;
}
const vl_dragging = () => !!(document.body.classList.contains('tdrag') || (typeof lp !== 'undefined' && lp?.active) || document.querySelector('#view .dragging') || (typeof dragId !== 'undefined' && dragId));
// after a render of the view (renderView, the search results): restore the place of a view drawn anew, then fit the window
function vl_after() {
  const v = vl_view();
  if (!VL.on || !v || !v.querySelector('.vlpad')) { VL.on = false; return; }
  if (VL.fresh && VL.st.has(VL.key)) v.scrollTop = VL.st.get(VL.key);
  VL.fresh = false;
  vl_sync();
}
function vl_sched() { if (VL.on && !VL.raf) VL.raf = requestAnimationFrame(() => { VL.raf = 0; vl_sync(); }); }
function vl_sync() {
  const v = vl_view(); if (!VL.on || !v) return;
  if (!v.querySelector('.vlpad')) { VL.on = false; return; }
  vl_measure(v);
  for (let k = 0; k < 4 && vl_step(v); k++) vl_measure(v);
}
// one pass: every group whose window does not cover the visible part (plus half a screen) or is far too big gets the window
// of the visible part plus 1.5 screens above and below; returns true when something changed
function vl_step(v) {
  const drag = vl_dragging(), anc = new Map();
  // the first drawn row in view keeps its place on the screen (per scrolling box: the view, or a list with its own scroll)
  const ancOf = sc => {
    if (anc.has(sc)) return; const vr = sc.getBoundingClientRect(); anc.set(sc, null);
    for (const el of sc.querySelectorAll('[data-vlg], .ghead')) { const r = el.getBoundingClientRect(); if (r.bottom > vr.top + 1 && r.height) { anc.set(sc, [el, r.top]); break; } }
  };
  for (const sg of VL.segs) { const tp = vl_pad(v, sg, 't'); if (tp) ancOf(vl_sc(tp, v)); }
  let ch = false;
  for (const sg of VL.segs) {
    const tp = vl_pad(v, sg, 't'), bp = vl_pad(v, sg, 'b'); if (!tp || !bp) continue;
    const sc = vl_sc(tp, v), vr = sc.getBoundingClientRect(), st = sc.scrollTop, vh = sc.clientHeight || innerHeight;
    const need = [st - vh * .5, st + vh * 1.5], want = [st - vh * 1.5, st + vh * 2.5];
    const n = sg.arr.length, ya = tp.getBoundingClientRect().top - vr.top + st + sg.tp;  // the content y of item a
    const H = vl_hm(), hs = i => H.get(sg.arr[i].id) ?? vl_h(sg, sg.arr[i]);
    const yOf = i => { let y = ya; if (i < sg.a) for (let j = sg.a - 1; j >= i; j--) y -= hs(j); else for (let j = sg.a; j < i; j++) y += hs(j); return y; };
    const yb = yOf(sg.b);
    const covers = (sg.a === 0 || ya <= need[0]) && (sg.b === n || yb >= need[1]);
    if (covers && !(sg.b - sg.a > 30 && (ya < want[0] - vh * 2 || yb > want[1] + vh * 2))) continue;
    // the new window: walk from item a (its y is known) to the first item that reaches into want, then to the end of want
    let wa = sg.a, y = ya;
    while (wa > 0 && y > want[0]) y -= hs(--wa);
    while (wa < n && y + hs(wa) <= want[0]) y += hs(wa++);
    let wb = wa, y2 = y;
    while (wb < n && y2 < want[1]) y2 += hs(wb++);
    if (drag) { wa = Math.min(wa, sg.a); wb = Math.max(wb, sg.b); }  // a drag only adds rows (its row must stay)
    // an item in the middle of an edit (inline title, a focused control) stays drawn
    const m0 = vl_nodes(tp, bp), act = document.activeElement;
    for (const [g, ns] of m0) if (ns.some(x => x.classList.contains('iedit') || x.contains(act))) { const i = sg.arr.findIndex(t => String(t.id) === g); if (i >= 0 && (i < wa ? wa - i : i - wb) < 400) { wa = Math.min(wa, i); wb = Math.max(wb, i + 1); } }
    if (wa === sg.a && wb === sg.b) continue;
    const tpTop = ya - sg.tp, a0 = sg.a, fi = Math.max(wa, a0), ov = wa < sg.b && wb > a0;
    // overlapping windows: item fi, drawn before and after, stays where it was (the top spacer takes what the rows above
    // it take or leave); otherwise the top spacer is the estimate of the rows above
    let yf = ya; if (ov) for (let j = a0; j < fi; j++) yf += hs(j);
    vl_patch(sg, tp, bp, m0, wa, wb);
    vl_measure(v);
    if (!wa) sg.tp = 0;
    else if (ov) { let above = 0; for (let j = wa; j < fi; j++) above += hs(j); sg.tp = Math.max(0, yf - tpTop - above); }
    else sg.tp = Math.max(0, y - tpTop);
    tp.style.height = Math.round(sg.tp) + 'px';
    bp.style.height = Math.round(vl_sum(sg, sg.b, n)) + 'px';
    vl_map(VL.wins, VL.key).set(sg.key, {id: sg.arr[sg.a]?.id, a: sg.a, c: sg.b - sg.a, tp: sg.tp});
    ch = true;
  }
  if (!ch) return false;
  for (const [sc, a] of anc) if (a && a[0].isConnected) { const d = a[0].getBoundingClientRect().top - a[1]; if (Math.abs(d) >= 1) sc.scrollTop += d; }
  if (typeof rowRove === 'function') rowRove();
  return true;
}
// draws items [wa, wb) between the spacers: the ones still in the window keep their nodes, the others come or go
function vl_patch(sg, tp, bp, have, wa, wb) {
  const keep = new Set(); for (let i = wa; i < wb; i++) keep.add(String(sg.arr[i].id));
  for (const [g, ns] of have) if (!keep.has(g)) { ns.forEach(x => x.remove()); have.delete(g); }
  const miss = []; for (let i = wa; i < wb; i++) if (!have.has(String(sg.arr[i].id))) miss.push(i);
  if (miss.length) {
    const t = document.createElement('template');
    t.innerHTML = miss.map(i => vl_mark(sg.fn(sg.arr[i], i), sg.arr[i].id)).join('');
    for (const x of [...t.content.children]) { const g = x.dataset.vlg; (have.get(g) || have.set(g, []).get(g)).push(x); }
  }
  const par = tp.parentNode; let cur = tp.nextElementSibling;
  for (let i = wa; i < wb; i++) for (const x of have.get(String(sg.arr[i].id)) || []) { if (x === cur) cur = cur.nextElementSibling; else par.insertBefore(x, cur || bp); }
  sg.a = wa; sg.b = wb;
}
// the ids of all rows of the view in their order, drawn or not (falls back to the drawn rows)
function vl_ids() {
  const v = vl_view(); if (!v) return [];
  const els = v.querySelectorAll(VL.on ? '.trow[data-id], .vlpad' : '.trow[data-id]');
  if (!VL.on || !v.querySelector('.vlpad')) return [...els].map(r => +r.dataset.id);
  const out = [], one = t => [t.id];
  for (const el of els) {
    if (!el.classList.contains('vlpad')) { out.push(+el.dataset.id); continue; }
    const k = el.dataset.k, sg = VL.by.get(k.slice(4)); if (!sg || sg.ids === false) continue;  // false: not task rows (contacts)
    const [a, b] = k.startsWith('vlt:') ? [0, sg.a] : [sg.b, sg.arr.length], f = sg.ids || one;
    for (let i = a; i < b; i++) out.push(...f(sg.arr[i]));
  }
  return out;
}
// scrolls a row that is not drawn (keyboard, a jump to a task) into the window
function vl_reveal(id) {
  const v = vl_view(); if (!VL.on || !v || !id || v.querySelector(`.trow[data-id="${+id}"]`)) return;
  const vr = v.getBoundingClientRect(), st = v.scrollTop, vh = v.clientHeight || innerHeight;
  for (const sg of VL.segs) {
    if (sg.ids === false) continue;
    const f = sg.ids, i = sg.arr.findIndex(t => t.id === +id || (f && f(t).includes(+id))); if (i < 0) continue;
    const tp = vl_pad(v, sg, 't'); if (!tp) return;
    let y = tp.getBoundingClientRect().top - vr.top + st + sg.tp;
    if (i < sg.a) for (let j = sg.a - 1; j >= i; j--) y -= vl_h(sg, sg.arr[j]); else for (let j = sg.a; j < i; j++) y += vl_h(sg, sg.arr[j]);
    v.scrollTop = Math.max(0, y - vh / 3);
    vl_sync(); return;
  }
}
document.addEventListener('scroll', e => { if (!VL.on) return; if (e.target?.id === 'view') { VL.st.set(VL.key, e.target.scrollTop); vl_sched(); } else if (e.target?.hasAttribute?.('data-vlsc')) vl_sched(); }, {capture: true, passive: true});
addEventListener('resize', () => { if (!VL.on) return; if (innerWidth !== VL.w) { VL.w = innerWidth; VL.hs.clear(); VL.est = 0; } vl_sched(); });
