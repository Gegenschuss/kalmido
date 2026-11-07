// @ts-check
/* Kalmido web client: quick entry in a table (2.578.0, #3462 part C point 6), loaded with the tables (lazyload.js). The chosen
   cells get a handle at their bottom right corner (mouse and finger): dragging it down or to the right fills the cells it
   passes. Two or more numbers continue their steps (1, 2 -> 3, 4), a date goes on by a day (or by the step / the months of
   the chosen dates), weekdays and months go on in their language and form (Mo, Di / Monday / Jan), "Item 1" counts up, a
   formula moves its relative references (A1 -> A2; $A$1 stays), anything else repeats. Ctrl/Cmd+D fills the first row of a
   range down into it (a copy, formulas moved). One Undo step (sheets.js shvPut). Values only: the format goes with the brush.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const SHFL_LISTS = [  // the cycles a fill continues (each list in one form; the match keeps the case of the source)
  ['montag', 'dienstag', 'mittwoch', 'donnerstag', 'freitag', 'samstag', 'sonntag'], ['mo', 'di', 'mi', 'do', 'fr', 'sa', 'so'],
  ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'], ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'],
  ['januar', 'februar', 'märz', 'april', 'mai', 'juni', 'juli', 'august', 'september', 'oktober', 'november', 'dezember'],
  ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'],
  ['jan', 'feb', 'mär', 'apr', 'mai', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dez'], ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']];
const SHFL = {d: null};

// ---- the series (pure: src = the inputs of one column / row of the choice, n = how many follow) -> n new inputs
function shfl_shift(f, dr, dc) {  // a formula's relative references moved (kalmido/sheets/io.py _shift_formula)
  const col = l => [...l.toUpperCase()].reduce((n, ch) => n * 26 + ch.charCodeAt(0) - 64, 0);
  const let_ = n => { let s = ''; for (; n > 0; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + ((n - 1) % 26)) + s; return s; };
  return String(f).split(/("(?:[^"]|"")*")/).map(p => p.startsWith('"') ? p : p.replace(/(?<![\w.])(\$?)([A-Za-z]{1,3})(\$?)(\d{1,7})(?![\w(])/g,
    (m, ca, l, ra, r) => `${ca}${ca ? l : let_(col(l) + dc)}${ra}${ra ? r : Math.max(1, +r + dr)}`)).join('');
}
function shfl_numOf(s) {
  s = String(s ?? '').trim();
  if (!/^-?\d+([.,]\d+)?$/.test(s)) return null;
  return {n: Number(s.replace(',', '.')), sep: s.match(/[.,]/)?.[0] || '.', dec: (s.split(/[.,]/)[1] || '').length};
}
function shfl_numText(x, like) {  // as many decimals as the source shows (1,5 -> 2,5), whole numbers stay whole
  const s = like.dec ? x.toFixed(like.dec) : String(+x.toFixed(10));
  return s.replace('.', like.sep || '.');  // the source's decimal sign (#4871), never a fixed comma
}
function shfl_cyc(s) {  // -> {li, i, up: 'upper' | 'title' | 'lower', dot} or null
  const t = String(s ?? '').trim(), dot = t.endsWith('.'), w = (dot ? t.slice(0, -1) : t).toLowerCase();
  if (!w) return null;
  for (let li = 0; li < SHFL_LISTS.length; li++) {
    const i = SHFL_LISTS[li].indexOf(w); if (i < 0) continue;
    const raw = dot ? t.slice(0, -1) : t;
    return {li, i, up: raw === raw.toUpperCase() && raw.length > 1 ? 'upper' : raw[0] === raw[0].toUpperCase() ? 'title' : 'lower', dot};
  }
  return null;
}
const shflCase = (w, up) => up === 'upper' ? w.toUpperCase() : up === 'title' ? w[0].toUpperCase() + w.slice(1) : w;
function shfl_dateText(iso, like) {
  if (/^\d{4}-/.test(like)) return iso;
  const [y, m, d] = iso.split('-');
  if (/^\d{1,2}\.\d{1,2}\.\d{2}$/.test(like)) return `${d}.${m}.${y.slice(2)}`;
  if (/^\d{1,2}\.\d{1,2}\.\d{4}$/.test(like)) return `${d}.${m}.${y}`;
  return iso;
}
function shfl_addDays(iso, n) { const [y, m, d] = iso.split('-').map(Number); return ds(new Date(y, m - 1, d + n)); }  // local calendar day (#2978 rule)
function shfl_addMonths(iso, n) {
  const [y, m, d] = iso.split('-').map(Number), t = new Date(y, m - 1 + n, 1), last = new Date(t.getFullYear(), t.getMonth() + 1, 0).getDate();
  t.setDate(Math.min(d, last)); return ds(t);
}
function shfl_series(src, n, vertical, plain) {  // plain: the column kind takes no series (selection, person, ...): repeat
  const k = src.length, out = [];
  if (!k || n < 1) return out;
  const steps = (i, s) => (k + i) - s;  // how far the copy of src[s] for the place k + i lies from it
  if (src.some(s => String(s).startsWith('='))) {  // formulas (and whatever stands between them): repeated, references moved
    for (let i = 0; i < n; i++) { const s = i % k, v = String(src[s]), d = steps(i, s); out.push(v.startsWith('=') ? shfl_shift(v, vertical ? d : 0, vertical ? 0 : d) : v); }
    return out;
  }
  const rep = () => { for (let i = 0; i < n; i++) out.push(src[i % k]); return out; };
  if (plain || src.some(s => String(s ?? '').trim() === '')) return rep();
  const nums = src.map(shfl_numOf);
  if (nums.every(Boolean)) {
    if (k === 1) return rep();  // one number is copied (like Excel); two give the step
    const step = (nums[k - 1].n - nums[0].n) / (k - 1), like = {sep: nums[0].sep, dec: Math.max(...nums.map(x => x.dec))};
    for (let i = 1; i <= n; i++) out.push(shfl_numText(nums[k - 1].n + step * i, like));
    return out;
  }
  const days = src.map(s => sgDay(String(s)));
  if (days.every(Boolean)) {
    const last = days[k - 1], like = String(src[k - 1]).trim();
    let byMonth = 0, step = 1;
    if (k > 1) {
      const ms = days.map(d => { const [y, m] = d.split('-').map(Number); return y * 12 + m; });
      const dm = ms[1] - ms[0];
      if (dm && days.every(d => d.slice(8) === days[0].slice(8)) && ms.every((m, i) => !i || m - ms[i - 1] === dm)) byMonth = dm;
      else step = Math.round((Date.parse(last) - Date.parse(days[0])) / 864e5 / (k - 1)) || 1;
    }
    for (let i = 1; i <= n; i++) out.push(shfl_dateText(byMonth ? shfl_addMonths(last, byMonth * i) : shfl_addDays(last, step * i), like));
    return out;
  }
  const cyc = src.map(shfl_cyc);
  if (cyc.every(c => c && c.li === cyc[0].li)) {
    const L = SHFL_LISTS[cyc[0].li], st = k > 1 ? ((cyc[k - 1].i - cyc[k - 2].i) % L.length + L.length) % L.length || 1 : 1, c = cyc[k - 1];
    for (let i = 1; i <= n; i++) out.push(shflCase(L[(c.i + st * i) % L.length], c.up) + (c.dot ? '.' : ''));
    return out;
  }
  const tn = src.map(s => String(s).match(/^(.*?\D)(\d{1,9})$/));
  if (tn.every(m => m && m[1] === tn[0][1])) {  // "Item 1", "KW 7": the number counts up
    const vs = tn.map(m => +m[2]), step = k > 1 ? (vs[k - 1] - vs[0]) / (k - 1) : 1, w = tn[k - 1][2].length;
    if (Number.isInteger(step)) {
      for (let i = 1; i <= n; i++) { const v = vs[k - 1] + step * i; out.push(tn[0][1] + (v < 0 ? String(v) : String(v).padStart(tn[k - 1][2].startsWith('0') ? w : 1, '0'))); }
      return out;
    }
  }
  return rep();
}

// ---- the handle
function shfl_place() {
  document.querySelectorAll('#shv-scroll .shfl-h').forEach(x => x.remove());
  const sh = SHV.sh; if (!sh?.can_write || !SHV.cur || SHV.ed || SHFL.d) return;
  const q = shvRect(); if (!q) return;
  const [rs, cs] = shvGrid(), td = document.getElementById(`shv-c-${rs[q.r1]}-${cs[q.c1]}`); if (!td) return;
  const h = document.createElement('span');
  h.className = 'shfl-h'; h.dataset.shfl = '1'; h.title = tr('Drag to fill'); h.setAttribute('aria-hidden', 'true');
  td.appendChild(h);
}
function shfl_paint(set) {
  document.querySelectorAll('#shv-scroll td.shfl-p').forEach(td => td.classList.remove('shfl-p'));
  for (const k of set || []) document.getElementById('shv-c-' + k.replace(':', '-'))?.classList.add('shfl-p');
}
function shfl_target(x, y) {  // -> {down, right} cells past the choice under the pointer (only one way)
  const d = SHFL.d, td = shvTdOf(document.elementFromPoint?.(x, y)); if (!td || !d) return null;
  const [rs, cs] = shvGrid(), i = rs.indexOf(+td.dataset.r), j = cs.indexOf(+td.dataset.c);
  if (i < 0 || j < 0) return null;
  const down = i - d.q.r1, right = j - d.q.c1;
  if (down > 0 && down >= right) return {down, right: 0};
  if (right > 0) return {down: 0, right};
  return {down: 0, right: 0};
}
function shfl_cells(q, t) {  // the cells a fill writes: [{r, c}]
  const [rs, cs] = shvGrid(), out = [];
  if (t.down > 0) for (let j = q.c0; j <= q.c1; j++) for (let a = 1; a <= t.down && q.r1 + a < rs.length; a++) out.push({r: rs[q.r1 + a], c: cs[j]});
  if (t.right > 0) for (let i = q.r0; i <= q.r1; i++) for (let a = 1; a <= t.right && q.c1 + a < cs.length; a++) out.push({r: rs[i], c: cs[q.c1 + a]});
  return out;
}
const SHFL_PLAIN = ['select', 'person', 'checkbox', 'link'];
async function shfl_fill(q, t, copy) {  // copy: Ctrl+D (the first row repeated, formulas moved)
  const sh = SHV.sh; if (!sh?.can_write) return;
  const [rs, cs] = shvGrid(), vert = t.down > 0, chg = [];
  const lines = vert ? cs.slice(q.c0, q.c1 + 1) : rs.slice(q.r0, q.r1 + 1);
  lines.forEach(ln => {
    const col = vert ? sh._col.get(ln) : null;
    const src = vert ? rs.slice(q.r0, q.r1 + 1).map(r => shvRaw(r, ln)) : cs.slice(q.c0, q.c1 + 1).map(c => shvRaw(ln, c));
    const n = vert ? Math.min(t.down, rs.length - 1 - q.r1) : Math.min(t.right, cs.length - 1 - q.c1);
    const plainOf = c => SHFL_PLAIN.includes(sh._col.get(c)?.kind);
    const vals = shfl_series(copy ? src.slice(0, 1) : src, n, vert, copy || (vert ? plainOf(ln) : cs.slice(q.c0, q.c1 + 1).some(plainOf)));
    vals.forEach((v, a) => {
      const r = vert ? rs[q.r1 + 1 + a] : ln, c = vert ? ln : cs[q.c1 + 1 + a];
      if ((vert ? col : sh._col.get(c))?.kind === 'file') return;  // a file belongs to its cell
      chg.push({row_id: r, col_id: c, raw: v ?? ''});
    });
  });
  if (!chg.length) return;
  const e = await shvPut(chg, trn('{0} cell filled', '{0} cells filled', chg.length));
  if (e) histToast(trn('{0} cell filled', '{0} cells filled', chg.length), e);
  if (!copy) { SHV.anc = {r: rs[q.r0], c: cs[q.c0]}; SHV.cur = {r: vert ? rs[Math.min(rs.length - 1, q.r1 + t.down)] : rs[q.r1], c: vert ? cs[q.c1] : cs[Math.min(cs.length - 1, q.c1 + t.right)]}; shvPaintSel(); }
}
document.addEventListener('pointerdown', e => {
  const h = (/** @type {any} */ (e.target)).closest?.('#shv-scroll .shfl-h'); if (!h || !SHV.sh?.can_write || e.button > 0) return;
  e.preventDefault(); e.stopPropagation();
  const q = shvRect(); if (!q) return;
  SHFL.d = {q, t: {down: 0, right: 0}, id: e.pointerId};
  try { h.setPointerCapture?.(e.pointerId); } catch { /* gone */ }
  $('#shv-scroll')?.classList.add('shfl-on');
}, true);
document.addEventListener('pointermove', e => {
  const d = SHFL.d; if (!d || e.pointerId !== d.id) return;
  e.preventDefault();
  const t = shfl_target(e.clientX, e.clientY); if (!t) return;
  d.t = t; shfl_paint(shfl_cells(d.q, t).map(x => x.r + ':' + x.c));
}, true);
const shflEnd = cancel => {
  const d = SHFL.d; if (!d) return;
  SHFL.d = null; shfl_paint(null); $('#shv-scroll')?.classList.remove('shfl-on');
  if (!cancel && (d.t.down > 0 || d.t.right > 0)) shfl_fill(d.q, d.t, false); else shfl_place();
};
document.addEventListener('pointerup', e => { if (SHFL.d && e.pointerId === SHFL.d.id) { e.stopPropagation(); shflEnd(false); } }, true);
document.addEventListener('pointercancel', e => { if (SHFL.d && e.pointerId === SHFL.d.id) shflEnd(true); }, true);
window.addEventListener('keydown', e => {  // Ctrl/Cmd+D: the first row of the range down into it
  if ((/** @type {any} */ (e.target))?.id !== 'shv-scroll' || !SHV.sh?.can_write || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== 'd') return;
  const q = shvRect(); if (!q || q.r1 === q.r0) return;
  e.preventDefault(); e.stopPropagation();
  shfl_fill({...q, r1: q.r0}, {down: q.r1 - q.r0, right: 0}, true);
}, true);
