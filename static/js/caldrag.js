/* Kalmido web client: 2.52.0 (#1016) the calendar like macOS Calendar. Classic script sharing the global scope with the
   others (load order: index.html). Week / day grid: a drag over free time leaves a block "New event" with its title field
   in the grid (Enter saves, Esc / a click beside it without a title drops it, "Details" opens the editor); an own event is
   moved by dragging it (also into another day) and made longer / shorter at its lower edge; a drag over the all-day row
   or over days of the month makes an all-day event, an event there is dragged into other days. Mouse / pen at once (from a few pixels), touch after a 0.4 s hold
   (a swipe before that scrolls as before). Esc cancels a drag. Every save goes through cg_commit (B: dvw_commit for a
   writable CalDAV subscription). Tasks (.wev, .ev) keep their own drag (dnd.js). */
'use strict';

const CG = {st: null, nw: null, swallow: 0};
const CG_HOLD = 400, CG_TOL = 8;
const cg_TEV = typeof window !== 'undefined' && 'ontouchstart' in window;  // touch events exist: a touch drag ends with touchend
const cg_hm = m => `${pad(Math.floor(m / 60) % 24)}:${pad(m % 60)}`;
const cg_lab = m => m >= 1440 ? '24:00' : cg_hm(m);
const cg_wall = (day, m) => m >= 1440 ? `${addDays(day, Math.floor(m / 1440))}T${cg_hm(m % 1440)}` : `${day}T${cg_hm(m)}`;
const cg_snap = m => Math.round(m / 15) * 15;
// wall-clock arithmetic on "YYYY-MM-DDTHH:MM" without the device's time zone (no daylight-saving jumps)
function cg_wallAdd(s, m) { const d = new Date(s.slice(0, 16) + ':00Z'); d.setUTCMinutes(d.getUTCMinutes() + m); return d.toISOString().slice(0, 16); }
const cg_wallMin = (a, b) => Math.round((new Date(b.slice(0, 16) + ':00Z') - new Date(a.slice(0, 16) + ':00Z')) / 60000);
const cg_evOf = el => { const v = el?.dataset?.cev; if (v == null) return null; const id = /^\d+$/.test(v) ? +v : v; return S.cal.items.find(x => x.id === id) || null; };
// may this calendar item be dragged: an own event of a calendar I may change (not a booking, not an invitation), or an
// event of a CalDAV subscription that allows writing (part B sets dvw_write and supplies dvw_commit)
function cg_canDrag(e) {
  if (!e || e.booking) return false;
  if (e.own) return feat('events') && e.cal != null && (e.role === 'owner' || e.role === 'edit');
  return e.dvw_write === true && typeof dvw_commit === 'function';
}
const cg_at = (col, y) => Math.max(0, Math.min(1440, cg_snap((y - col.getBoundingClientRect().top) / weekH() * 60)));
const cg_cols = () => $$('#view .week .wcol');
function cg_colAt(x) {  // the day column under x (the nearest one beside the grid)
  let best = null, bd = Infinity;
  for (const c of cg_cols()) { const r = c.getBoundingClientRect(), d = x < r.left ? r.left - x : x > r.right ? x - r.right : 0; if (d < bd) { bd = d; best = c; } }
  return best;
}
const cg_dayEl = (sel, x, y) => document.elementFromPoint(x, y)?.closest?.(sel) || null;

// ---- saving a moved / resized event: patch = {start, end, all_day} as local wall times "YYYY-MM-DDTHH:MM" (all day: dates,
// end exclusive), scope = 'one' | 'all' | null. Kalmido events keep their own time zone: the change is applied as a shift of
// the stored times. True when saved (one undo step).
function cg_shiftRule(rule, n) {  // a repeating rule whose days are named moves with the series by n days (null: cannot)
  if (!n || !rule) return rule;
  const WD = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'];
  const parts = rule.split(';').map(p => p.split('='));
  if (parts.some(([k]) => ['BYYEARDAY', 'BYWEEKNO', 'BYSETPOS', 'BYHOUR', 'BYMINUTE'].includes(k))) return null;
  for (const p of parts) {
    if (p[0] === 'BYDAY') p[1] = p[1].split(',').map(t => { const m = /^([+-]?\d*)(MO|TU|WE|TH|FR|SA|SU)$/.exec(t); return m ? m[1] + WD[(((WD.indexOf(m[2]) + n) % 7) + 7) % 7] : t; }).join(',');
    if (p[0] === 'BYMONTHDAY') { const v = p[1].split(',').map(x => +x + n); if (v.some(x => !(x >= 1 && x <= 28))) return null; p[1] = v.join(','); }
  }
  return parts.map(p => p.join('=')).join(';');
}
async function cg_commit(e, patch, scope) {
  if (!e?.own) return e?.dvw_write === true && typeof dvw_commit === 'function' ? !!(await dvw_commit(e, patch, scope)) : false;
  let ev; try { ev = await api('GET', `/api/events/${e.eid}`); } catch { return false; }
  const one = scope === 'one' && e.recurring, all = e.recurring && !one;
  let fwd, back;
  if (e.all_day) {
    const dS = diffDays(e.start, patch.start), dE = diffDays(e.end, patch.end);
    if (one) { fwd = {start: patch.start, end: patch.end}; back = {start: e.start, end: e.end}; }
    else { fwd = {start: addDays(ev.start, dS), end: addDays(ev.end, dE)}; back = {start: ev.start, end: ev.end}; }
  } else {
    const dS = Math.round((new Date(patch.start) - e.s) / 60000), dE = Math.round((new Date(patch.end) - e.e) / 60000);
    if (one) {
      const ov = (ev.overrides || []).find(x => x.rid === e.occ);
      const s0 = ov?.start || e.occ, e0 = ov?.end || cg_wallAdd(e.occ, cg_wallMin(ev.start, ev.end));
      fwd = {start: cg_wallAdd(s0, dS), end: cg_wallAdd(e0, dE)}; back = {start: s0, end: e0};
    } else { fwd = {start: cg_wallAdd(ev.start, dS), end: cg_wallAdd(ev.end, dE)}; back = {start: ev.start, end: ev.end}; }
  }
  if (all && ev.rrule) {  // the whole series moved into other days: weekdays / month days of the rule move along
    const n = diffDays(ev.start.slice(0, 10), fwd.start.slice(0, 10)), r = cg_shiftRule(ev.rrule, n);
    if (r == null) { toast(tr('Only this date can be moved to another day')); return false; }
    if (r !== ev.rrule) { fwd.rrule = r; back.rrule = ev.rrule; }
  }
  const url = `/api/events/${ev.id}` + (one ? `?occ=${encodeURIComponent(e.occ)}` : '');
  try { await api('PATCH', url, one ? fwd : {...fwd, expect: ev.updated_at}); } catch { return false; }
  const re = () => { calInvalidate(); renderView(); };
  offerUndo(tr('Event changed'), histAdd({label: tr('Times of “{0}”', ev.title || tr('(no title)')), undo: () => api('PATCH', url, back), redo: () => api('PATCH', url, fwd), post: re}));
  return true;
}

// ---- the drag
function cg_down(e) {
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  const t = e.target;
  if (!t?.closest?.('#view .week, #view .cal')) return;
  if (CG.nw) {  // a block "New event" is open: a press beside it ends it (saved with a title), nothing else happens
    if (CG.nw.el.contains(t)) return;
    cg_newDone(true);
    CG.swallow = Date.now();
    return;
  }
  if (t.closest('input, textarea, button, select, a, .wev, .ev, .more, .cgnew')) return;
  const touch = e.pointerType === 'touch';
  let st = null;
  const wcev = t.closest('.week .wcev');
  if (wcev) {
    const ev = cg_evOf(wcev); if (!cg_canDrag(ev)) return;
    st = {kind: 'move', ev, el: wcev, col: wcev.closest('.wcol')};
    const r = wcev.getBoundingClientRect();
    if (ev.d1 === st.col?.dataset.day && !ev.all_day && r.bottom - e.clientY <= (touch ? 12 : 6)) st.kind = 'size';
  } else if (t.closest('.week .wcol')) {
    const col = t.closest('.wcol');
    // just below an event's lower edge (touch: the 24 px target reaches 12 px below it): that event's length
    const near = touch && [...col.querySelectorAll('.wcev')].find(x => { const r = x.getBoundingClientRect(), ev = cg_evOf(x); return e.clientX >= r.left && e.clientX <= r.right && e.clientY - r.bottom >= 0 && e.clientY - r.bottom <= 12 && cg_canDrag(ev) && ev.d1 === col.dataset.day; });
    if (near) st = {kind: 'size', ev: cg_evOf(near), el: near, col};
    else if (evOn()) st = {kind: 'new', col};
  } else if (t.closest('.week .wad .cev, .cal .cell .cev')) {  // an event in the all-day row / the month: into other days
    const ev = cg_evOf(t.closest('.cev')); if (!cg_canDrag(ev)) return;
    st = {kind: 'dmove', ev, el: t.closest('.cev'), sel: t.closest('.wad') ? '#view .week .wad' : '#view .cal .cell'};
  } else if (t.closest('.week .wad')) { if (evOn()) st = {kind: 'aday'}; }
  else if (t.closest('.cal .cell')) { if (evOn()) st = {kind: 'mday'}; }
  if (!st) return;
  if (st.kind === 'aday' || st.kind === 'mday' || st.kind === 'dmove') st.d0 = st.d1 = t.closest('[data-day]').dataset.day;
  Object.assign(st, {touch, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, active: false, pid: e.pointerId});
  CG.st = st;
  if (touch) st.timer = setTimeout(() => { if (CG.st === st) cg_start(); }, CG_HOLD);
}
function cg_start() {
  const st = CG.st; if (!st || st.active) return;
  st.active = true;
  document.body.classList.add('cgdrag');
  if (st.touch) { try { navigator.vibrate?.(10); } catch { /* not allowed */ } }
  try { window.getSelection?.()?.removeAllRanges(); } catch { /* none */ }
  if (st.kind === 'new') { st.a = cg_at(st.col, st.y0); st.ghost = document.createElement('div'); st.ghost.className = 'evghost'; st.col.appendChild(st.ghost); }
  else if (st.kind === 'move' || st.kind === 'size') {
    const day = st.col.dataset.day, m = cevMin(st.ev, day);
    Object.assign(st, {day, s: m.s, e: m.e, multi: st.ev.d0 !== st.ev.d1, sc0: $('#wbody')?.scrollTop || 0});
    st.ghost = st.el.cloneNode(true); st.ghost.classList.add('cgghost'); st.ghost.removeAttribute('data-cev');
    st.el.classList.add('cgsrc');
    st.col.appendChild(st.ghost);
  } else if (st.kind === 'dmove') st.el.classList.add('cgsrc');
  cg_move();
}
function cg_move() {
  const st = CG.st; if (!st?.active) return;
  const H = weekH();
  if (st.kind === 'new') {
    if (!st.col.isConnected) { const c = $(`#view .week .wcol[data-day="${st.col.dataset.day}"]`); if (!c) return cg_cancel(); st.col = c; }
    if (!st.ghost.isConnected) st.col.appendChild(st.ghost);
    const b = cg_at(st.col, st.y), s = Math.min(st.a, b, 1425), en = Math.min(1440, Math.max(st.a, b, s + 15));
    Object.assign(st, {ns: s, ne: en});
    st.ghost.style.top = s / 60 * H + 'px'; st.ghost.style.height = (en - s) / 60 * H + 'px';
    st.ghost.textContent = `${cg_lab(s)}–${cg_lab(en)}`;
  } else if (st.kind === 'move') {
    const col = cg_colAt(st.x) || st.col, dd = diffDays(st.day, col.dataset.day);
    let dm = cg_snap((st.y - st.y0 + ($('#wbody')?.scrollTop || 0) - st.sc0) / H * 60);  // the hours may have scrolled along
    if (!st.multi) dm = Math.max(-st.s, Math.min(1440 - st.e, dm));  // a one-day event stays inside its day
    Object.assign(st, {dd, dm});
    if (st.ghost.parentNode !== col) col.appendChild(st.ghost);
    const s = st.s + dm, en = st.e + dm;
    st.ghost.style.top = s / 60 * H + 'px'; st.ghost.style.height = Math.max(20, (st.e - st.s) / 60 * H) + 'px';
    st.ghost.style.left = '0'; st.ghost.style.width = 'calc(100% - 2px)';
    const b = st.ghost.querySelector('b'); if (b) b.textContent = `${cg_lab(((s % 1440) + 1440) % 1440)}–${cg_lab(en >= 1440 && !st.multi ? 1440 : ((en % 1440) + 1440) % 1440)}`;
  } else if (st.kind === 'size') {
    const en = Math.max(st.s + 15, Math.min(1440, cg_at(st.col, st.y)));
    st.ne = en;
    st.ghost.style.height = Math.max(20, (en - st.s) / 60 * H) + 'px';
    const b = st.ghost.querySelector('b'); if (b) b.textContent = `${cg_lab(st.s)}–${cg_lab(en)}`;
  } else if (st.kind === 'dmove') {  // the days the event will cover
    const el = cg_dayEl(st.sel, st.x, st.y);
    if (el?.dataset.day) st.d1 = el.dataset.day;
    const dd = diffDays(st.d0, st.d1), lo = addDays(st.ev.d0, dd), hi = addDays(st.ev.d1, dd);
    $$(st.sel).forEach(c => c.classList.toggle('cgsel', c.dataset.day >= lo && c.dataset.day <= hi));
  } else {
    const el = cg_dayEl(st.kind === 'aday' ? '#view .week .wad' : '#view .cal .cell', st.x, st.y);
    if (el?.dataset.day) st.d1 = el.dataset.day;
    const lo = st.d0 < st.d1 ? st.d0 : st.d1, hi = st.d0 < st.d1 ? st.d1 : st.d0;
    $$(st.kind === 'aday' ? '#view .week .wad' : '#view .cal .cell').forEach(c => c.classList.toggle('cgsel', c.dataset.day >= lo && c.dataset.day <= hi));
  }
  cg_edge();
}
function cg_edge() {  // near the top / bottom of the hours: they scroll along
  const st = CG.st, wb = $('#wbody');
  if (!st?.active || !wb || !['new', 'move', 'size'].includes(st.kind)) return;
  const r = wb.getBoundingClientRect(), z = 32;
  st.vs = st.y < r.top + z ? -Math.ceil((r.top + z - st.y) / 4) : st.y > r.bottom - z ? Math.ceil((st.y - r.bottom + z) / 4) : 0;
  if (st.vs && !st.raf) {
    const step = () => { if (CG.st !== st || !st.vs) { st.raf = 0; return; } wb.scrollTop += st.vs; cg_move(); st.raf = requestAnimationFrame(step); };
    st.raf = requestAnimationFrame(step);
  }
}
function cg_clear(st) {
  clearTimeout(st.timer); st.vs = 0;
  document.body.classList.remove('cgdrag');
  $$('#view .cgsel').forEach(c => c.classList.remove('cgsel'));
  st.el?.classList.remove('cgsrc');
}
function cg_cancel() {  // Esc / lost: everything back where it was
  const st = CG.st; CG.st = null; if (!st) return;
  cg_clear(st); st.ghost?.remove();
  if (st.active) CG.swallow = Date.now();
}
async function cg_end(e) {
  const st = CG.st; if (!st) return;
  CG.st = null;
  cg_clear(st);
  if (!st.active) return;  // no drag: the click does what it did (popover, quick sheet, the day)
  if (e?.cancelable) e.preventDefault();
  CG.swallow = Date.now();
  if (st.kind === 'new') { st.ghost.remove(); cg_newBlock({day: st.col.dataset.day, s: st.ns, e: st.ne}); return; }
  if (st.kind === 'aday' || st.kind === 'mday') { const lo = st.d0 < st.d1 ? st.d0 : st.d1, hi = st.d0 < st.d1 ? st.d1 : st.d0; cg_newBlock({d0: lo, d1: hi, month: st.kind === 'mday'}); return; }
  const ev = st.ev;
  let patch;
  if (st.kind === 'dmove') {
    const dd = diffDays(st.d0, st.d1); if (!dd) return;
    const sh = d => { const x = new Date(d); x.setDate(x.getDate() + dd); return `${ds(x)}T${fmtHM(x)}`; };
    patch = ev.all_day ? {start: addDays(ev.start, dd), end: addDays(ev.end, dd), all_day: true} : {start: sh(ev.s), end: sh(ev.e), all_day: false};
    st.ghost = document.createElement('i');  // a stand-in: the save below marks / drops it like the grid's ghost
  } else if (st.kind === 'move') {
    if (!st.dd && !st.dm) { st.ghost.remove(); return; }
    const mv = st.dd * 1440 + st.dm, sh = d => { const x = new Date(d); x.setMinutes(x.getMinutes() + mv); return `${ds(x)}T${fmtHM(x)}`; };
    // the shift in wall minutes of the day it was grabbed on: days + the snapped minutes (keeps the length)
    patch = {start: sh(ev.s), end: sh(ev.e), all_day: false};
  } else {
    if (st.ne === st.e) { st.ghost.remove(); return; }
    patch = {start: `${ds(ev.s)}T${fmtHM(ev.s)}`, end: cg_wall(st.day, st.ne), all_day: false};
  }
  let scope = null;
  if (ev.own && ev.recurring) { scope = await evAskScope(tr('Change a repeating event'), tr('Save')); if (!scope) { st.ghost.remove(); renderView(); return; } }
  else if (!ev.own && ev.dvw_rec) {  // a repeating event of a subscription: only every date (part B)
    if (!await askConfirm(tr('Change every date of this repeating event?'), tr('Single dates of a subscribed calendar cannot be changed here.'), {ok: tr('All dates')})) { st.ghost.remove(); renderView(); return; }
    scope = 'all';
  }
  st.ghost.classList.add('cgsaving');
  const ok = await cg_commit(ev, patch, scope).catch(() => false);
  st.ghost.remove();
  calInvalidate(); renderView();
  if (ok && !ev.own) toast(tr('Event changed'));
}

// ---- the block "New event" in the grid (o: {day, s, e} for times, {d0, d1, month} for whole days)
function cg_newWhen(o) {
  if (o.day) return `${cg_lab(o.s)}–${cg_lab(o.e)}`;
  return o.d0 === o.d1 ? fmtDayAbs(o.d0) : `${fmtDayAbs(o.d0)} – ${fmtDayAbs(o.d1)}`;
}
function cg_newBlock(o) {
  const el = document.createElement('div');
  el.className = 'cgnew' + (o.day ? '' : ' cgday');
  el.setAttribute('role', 'group'); el.setAttribute('aria-label', tr('New event'));
  el.innerHTML = `<span class="cgtm">${esc(cg_newWhen(o))}</span><input class="cgin" maxlength="500" placeholder="${esc(tr('New event'))}" aria-label="${esc(tr('Title of the new event'))}" autocomplete="off" enterkeyhint="done"><button type="button" class="btn sm cgdet">${esc(tr('Details'))}</button>`;
  CG.nw = {...o, el, focus: true};
  cg_place();
  const inp = el.querySelector('.cgin');
  inp.addEventListener('keydown', ev => {
    if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); ev.stopPropagation(); cg_newDone(true); }
    else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); cg_newDone(false); }
  });
  el.addEventListener('focusin', () => { if (CG.nw?.el === el) CG.nw.focus = true; });
  el.addEventListener('focusout', ev => {
    if (el.contains(ev.relatedTarget)) return;
    setTimeout(() => {  // gone by a re-render: it comes back (cg_watch); left for elsewhere: saved with a title, else dropped
      if (CG.nw?.el !== el || el.contains(document.activeElement) || !el.isConnected) return;
      if (document.activeElement?.closest?.('.modal, #pop')) return;
      cg_newDone(true);
    }, 0);
  });
  el.querySelector('.cgdet').addEventListener('click', ev => {
    ev.stopPropagation();
    const n = CG.nw; if (!n) return;
    const title = inp.value.trim();
    cg_newDone(false);
    if (n.day) evEditor({title, start: `${n.day}T${cg_hm(n.s)}`, end: cg_wall(n.day, n.e)});
    else evEditor({title, all_day: true, start: n.d0, end: addDays(n.d1, 1)});
  });
  inp.focus({preventScroll: true});
  cg_vv();
}
function cg_place() {  // into the grid as it is drawn now (again after a re-render)
  const n = CG.nw; if (!n) return false;
  const el = n.el;
  if (n.day) {
    const col = $(`#view .week .wcol[data-day="${n.day}"]`); if (!col) return false;
    const H = weekH();
    el.style.top = n.s / 60 * H + 'px'; el.style.minHeight = Math.max(44, (n.e - n.s) / 60 * H) + 'px';
    if (el.parentNode !== col) col.appendChild(el);
    return true;
  }
  const box = n.month ? $('#view .cal') : $('#view .week .wallday');
  const cells = $$(n.month ? '#view .cal .cell' : '#view .week .wad').filter(c => c.dataset.day >= n.d0 && c.dataset.day <= n.d1);
  if (!box || !cells.length) return false;
  cells.forEach(c => c.classList.add('cgsel'));
  const b = box.getBoundingClientRect(), r0 = cells[0].getBoundingClientRect();
  const row = cells.filter(c => Math.abs(c.getBoundingClientRect().top - r0.top) < 2), r1 = row[row.length - 1].getBoundingClientRect();
  Object.assign(el.style, {left: r0.left - b.left + 'px', width: Math.max(r1.right - r0.left, 160) + 'px', top: r0.top - b.top + (n.month ? r0.height / 3 : 0) + 'px'});
  if (el.parentNode !== box) box.appendChild(el);
  return true;
}
// the view is drawn anew (a poll, the events of the week arriving): the open block goes back into the new grid
const cg_mo = typeof MutationObserver === 'function' ? new MutationObserver(() => {
  const n = CG.nw; if (!n || n.el.isConnected) return;
  if (!cg_place()) { cg_newDone(true); return; }  // its day is no longer shown (another week): saved with a title, else dropped
  if (n.focus) n.el.querySelector('.cgin')?.focus({preventScroll: true});
}) : null;
const cg_obs = () => { const v = $('#view'); if (v && cg_mo) cg_mo.observe(v, {childList: true, subtree: true}); };
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', cg_obs); else cg_obs();
// the phone's keyboard opens: the block stays visible above it (#952)
function cg_vv() {
  const vv = window.visualViewport, n = CG.nw; if (!n) return;
  const go = () => { if (CG.nw === n && n.el.isConnected) n.el.scrollIntoView({block: 'center', behavior: 'auto'}); };
  if (!vv) return;
  const h = () => { if (CG.nw !== n) { vv.removeEventListener('resize', h); return; } go(); };
  vv.addEventListener('resize', h);
}
async function cg_newDone(save) {
  const n = CG.nw; if (!n) return;
  CG.nw = null;
  const title = n.el.querySelector('.cgin').value.trim();
  $$('#view .cgsel').forEach(c => c.classList.remove('cgsel'));
  if (!save || !title) { n.el.remove(); return; }
  const body = n.day ? {title, all_day: false, start: `${n.day}T${cg_hm(n.s)}`, end: cg_wall(n.day, n.e), reminders: [15]}
    : {title, all_day: true, start: n.d0, end: addDays(n.d1, 1), reminders: [-540]};
  const cals = evWritable();
  if (!cals.length) { n.el.remove(); evEditor(body); return; }  // no calendar yet: the editor makes one
  const pick = +LS.get('evCal', 0);
  Object.assign(body, {cal_id: cals.some(c => c.id === pick) ? pick : cals[0].id, tz: evTz()});
  n.el.classList.add('cgsaving'); n.el.querySelector('.cgin').disabled = true;
  let r;
  try { r = await api('POST', '/api/events', body); } catch { n.el.remove(); return; }
  n.el.remove();
  const re = () => { calInvalidate(); renderView(); };
  re();
  offerUndo(tr('Event created'), histAdd({label: tr('New event “{0}”', title), undo: () => api('DELETE', `/api/events/${r.id}`), redo: () => api('POST', `/api/events/${r.id}/restore`), post: re}));
}

// ---- wiring
document.addEventListener('pointerdown', cg_down);
document.addEventListener('pointermove', e => {
  const st = CG.st; if (!st || (st.pid != null && e.pointerId !== st.pid)) return;
  st.x = e.clientX; st.y = e.clientY;
  if (!st.active) {
    const d = Math.hypot(st.x - st.x0, st.y - st.y0);
    if (st.touch) { if (d > CG_TOL) { clearTimeout(st.timer); CG.st = null; } return; }  // a swipe: the page scrolls
    if (d < (['move', 'size', 'dmove'].includes(st.kind) ? 4 : CG_TOL)) return;
    cg_start();
  }
  e.preventDefault();
  cg_move();
});
document.addEventListener('pointerup', e => { const st = CG.st; if (!st || (st.touch && cg_TEV && st.active)) return; if (st.pid != null && e.pointerId !== st.pid) return; cg_end(e); });
document.addEventListener('pointercancel', e => {
  const st = CG.st; if (!st) return;
  if (st.touch && st.active && cg_TEV) return;  // the touch events carry on (the scroll is held back below)
  if (st.active) cg_cancel(); else { clearTimeout(st.timer); CG.st = null; }
});
// touch: once the hold is over, the finger drags and the page does not scroll
document.addEventListener('touchmove', e => {
  const st = CG.st; if (!st?.touch || !st.active) return;
  if (e.cancelable) e.preventDefault();
  const p = e.touches[0]; if (!p) return;
  st.x = p.clientX; st.y = p.clientY; cg_move();
}, {passive: false});
document.addEventListener('touchend', e => { const st = CG.st; if (st?.touch && st.active) cg_end(e); });
document.addEventListener('touchcancel', () => { const st = CG.st; if (st?.touch && st.active) cg_cancel(); });
document.addEventListener('contextmenu', e => { if (CG.st?.touch && e.target.closest?.('#view .week, #view .cal')) e.preventDefault(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && CG.st?.active) { e.preventDefault(); e.stopPropagation(); cg_cancel(); } }, true);
document.addEventListener('click', e => {  // the click that follows a drag (or the press that closed a block) does nothing more
  if (CG.swallow && Date.now() - CG.swallow < 500 && e.target.closest?.('#view .week, #view .cal')) { e.stopImmediatePropagation(); e.preventDefault(); CG.swallow = 0; }
}, true);
