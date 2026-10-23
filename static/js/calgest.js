// @ts-check
/* Kalmido web client: 2.164.0 (#2625) gestures of the calendar (module "calendar", loaded with calview.js / caldrag.js).
   One finger sideways turns the page in month, week, day and year: the page follows the finger and snaps to the next /
   previous period (or back). Two fingers zoom without steps: in week / day the hour height follows the fingers live (the
   grid's --h, the blocks hang on it during the gesture), is taken over on release (bounds CAL_HMIN..CAL_HMAX, kept on the
   device, calendar.js weekH); pinched on beyond a bound, or pinched in month / year, the view changes (year - month - week -
   day) with a soft transition. The trackpad does the same: pinch / Ctrl + mouse wheel zoom, a two-finger swipe turns the
   page. A double tap on a day of the month opens that day. The long press of caldrag.js (events) and dnd.js (tasks) stays:
   a swipe starts only once the finger clearly moved sideways (after their 8 px tolerance), a second finger cancels a
   pending hold, and nothing starts while one of their drags runs. */
'use strict';

const CGS = {
  /** @type {any} */ sw: null,  // one-finger swipe {x0, y0, t0, dx, lock, els}
  /** @type {any} */ pz: null,  // zoom session {week|flat, k, src: 'touch'|'wheel'|'gesture', ...}
  /** @type {any} */ wx: null,  // trackpad swipe {acc, els, idle, done}
  /** @type {any} */ tap: null,  // last tap on a month day {day, x, y, at}
  hold: false,  // fingers of an ended pinch still on the screen: no swipe until all are lifted
};
const CGS_AREA = '#view .cal, #view .week, #view #cyear';
const CGS_STEP = 1.2;  // pinched on by this much beyond a bound (week / day) = the next view
const CGS_FLAT = 1.25;  // month / year: pinched by this factor = the next view
/** @param {EventTarget|null} t */
const cgs_el = t => t instanceof Element ? t : null;
/** @param {EventTarget|null} t */
const cgs_area = t => S.route?.mod === 'cal' ? cgs_el(t)?.closest(CGS_AREA) || null : null;
const cgs_hasYear = () => typeof (/** @type {any} */ (window)).cyr_view === 'function';  // 2.155.0 C (#2078): calyear.js
const cgs_still = () => { try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; } };
// another drag owns the finger: an event (caldrag.js), a task (dnd.js), the sidebar
const cgs_busy = () => !!CG.st?.active || !!CG.nw || document.body.classList.contains('cgdrag') || document.body.classList.contains('tdrag');
function cgs_dropHolds() {  // a second finger: the pending long presses of caldrag.js / dnd.js are off
  if (CG.st && !CG.st.active) { clearTimeout(CG.st.timer); CG.st = null; }
  if (lp && !lp.active) { clearTimeout(lp.timer); lp = null; }
}

// ---- changing the view (year < month < week < day); dir > 0 = nearer
function cgs_go(mode, day, dir, x, y) {
  if (day) S.calSel = day;
  S.calMode = mode; LS.set('calMode', mode);
  if (mode === 'month') S.calMonth = S.calSel.slice(0, 7);
  renderView();
  const v = $('#view'), g = $('#view > .calbar ~ *'); if (!v || !g || cgs_still()) return;
  v.classList.remove('cgs-zi', 'cgs-zo');
  const r = g.getBoundingClientRect();  // grows out of the point between the fingers (in the new grid's own box)
  v.style.setProperty('--cgs-o', `${Math.round(x - r.left)}px ${Math.round(Math.max(0, Math.min(r.height, y - r.top)))}px`);
  void v.offsetWidth;  // the animation starts again
  v.classList.add(dir > 0 ? 'cgs-zi' : 'cgs-zo');
  setTimeout(() => v.classList.remove('cgs-zi', 'cgs-zo'), 400);
}
// the next view nearer (dir > 0) / farther from where the fingers are (x, y): null at the end of the row
function cgs_next(dir, x, y) {
  const ms = cgs_modes(), i = ms.indexOf(S.calMode), to = ms[i + dir];
  if (i < 0 || !to) return null;
  const at = cgs_el(document.elementFromPoint?.(x, y) || null);
  let day = null;
  if (S.calMode === 'week' && to === 'day') day = at?.closest('#view .week [data-day]')?.getAttribute('data-day') || cg_colAt(x, null)?.dataset.day || null;
  if (S.calMode === 'month' && to === 'week') day = at?.closest('#view .cal .cell[data-day]')?.getAttribute('data-day') || null;
  if (S.calMode === 'year' && to === 'month') { const m = at?.closest('.cymon')?.querySelector('[data-cym]')?.getAttribute('data-cym'); if (m) day = `${m}-01`; }
  return {mode: to, day};
}
const cgs_modes = () => [...(cgs_hasYear() ? ['year'] : []), 'month', 'week', 'day'];

// ---- zoom: one session for fingers, the trackpad's pinch / Ctrl + wheel and Safari's gesture events
// k = the factor since the start; (x, y) = the point between the fingers / under the pointer
function cgs_pzStart(area, x, y, src) {
  const week = area.closest('.week') && $('#view .week'), wb = week && $('#wbody');
  if (week && wb) {
    const H0 = weekH(), r = wb.getBoundingClientRect();
    // every block of the hours hangs on --h while the fingers move (no step, no new drawing per frame)
    for (const el of wb.querySelectorAll('[style*="top"]')) {
      const s = /** @type {HTMLElement} */ (el).style, t = parseFloat(s.top), h = parseFloat(s.height);
      if (!s.top.endsWith('px')) continue;
      s.top = `calc(var(--h) * ${t / H0})`;
      if (s.height.endsWith('px') && h > 20.5) s.height = `max(20px, calc(var(--h) * ${h / H0}))`;
    }
    CGS.pz = {week, wb, src, H0, H: H0, k: 1, x, y, top: r.top, min: (wb.scrollTop + Math.max(0, Math.min(r.height, y - r.top))) / H0 * 60};
  } else {
    const box = /** @type {HTMLElement} */ (area), r = box.getBoundingClientRect();
    box.style.transformOrigin = `${Math.round(x - r.left)}px ${Math.round(y - r.top)}px`;
    box.style.transition = 'none';
    CGS.pz = {box, src, k: 1, x, y};
  }
}
const cgs_pzDraw = rafThrottle(() => {
  const p = CGS.pz; if (!p) return;
  if (p.week) {
    if (!p.week.isConnected) { cgs_pzEnd(); return; }  // drawn anew meanwhile (a live update): the height so far stays
    const z = uiZ(), want = p.H0 * p.k, H = Math.max(CAL_HMIN * z, Math.min(CAL_HMAX * z, want)), over = want / H;
    p.H = H;
    p.week.style.setProperty('--h', H + 'px');
    p.wb.scrollTop = p.min / 60 * H - Math.max(0, p.y - p.top);  // the hour between the fingers stays under them
    // beyond a bound: the grid gives a little, and once a release would change the view it says so
    p.next = over >= CGS_STEP ? 1 : over <= 1 / CGS_STEP ? -1 : 0;
    p.week.style.transformOrigin = `${Math.round(p.x - p.week.getBoundingClientRect().left)}px ${Math.round(p.y - p.week.getBoundingClientRect().top)}px`;
    p.week.style.transform = over === 1 ? '' : `scale(${1 + (Math.max(.8, Math.min(1.25, over)) - 1) * .25})`;
    p.week.classList.toggle('cgs-arm', !!p.next && !!cgs_next(p.next, p.x, p.y));
  } else {
    if (!p.box.isConnected) { CGS.pz = null; return; }
    p.next = p.k >= CGS_FLAT ? 1 : p.k <= 1 / CGS_FLAT ? -1 : 0;
    p.box.style.transform = `scale(${Math.max(.7, Math.min(1.4, p.k))})`;
    p.box.classList.toggle('cgs-arm', !!p.next && !!cgs_next(p.next, p.x, p.y));
  }
});
function cgs_pzEnd() {
  cgs_pzDraw.flush();
  const p = CGS.pz; if (!p) return;
  CGS.pz = null;
  clearTimeout(p.idle);
  const to = p.next ? cgs_next(p.next, p.x, p.y) : null;
  if (to) { cgs_go(to.mode, to.day, p.next, p.x, p.y); return; }
  if (p.week) {
    p.week.style.transform = ''; p.week.classList.remove('cgs-arm');
    const v = Math.round(p.H / uiZ());
    if (v !== calHourH()) LS.set('calHourH', v);
    if (p.week.isConnected) renderView();  // the blocks get their px again (the scroll position is kept)
    return;
  }
  p.box.classList.remove('cgs-arm');
  p.box.style.transition = 'transform .18s ease-out'; p.box.style.transform = '';
  setTimeout(() => { p.box.style.transition = ''; p.box.style.transformOrigin = ''; }, 200);
}

// ---- turning the page (fingers and trackpad): the content below the bar follows, then snaps
const cgs_pages = () => /** @type {HTMLElement[]} */ ($$('#view > .calbar ~ *'));
function cgs_shift(els, dx) { for (const el of els) { el.style.transition = 'none'; el.style.transform = dx ? `translateX(${Math.round(dx)}px)` : ''; } }
function cgs_back(els) {
  for (const el of els) { el.style.transition = 'transform .18s ease-out'; el.style.transform = ''; }
  setTimeout(() => els.forEach(el => { el.style.transition = ''; }), 200);
}
function cgs_turn(els, dir) {  // dir > 0: the next period (finger to the left)
  cgs_shift(els, 0);
  $(`#view [data-act="${dir > 0 ? 'cal-next' : 'cal-prev'}"]`)?.click();  // the bar's arrows (events.js; glides in, an_calSlide)
}

// ---- fingers
document.addEventListener('touchstart', e => {
  const n = e.touches.length;
  if (n >= 2) {
    if (CGS.sw) { if (CGS.sw.els) cgs_back(CGS.sw.els); CGS.sw = null; }
    if (CGS.pz || n > 2) { if (n > 2 && CGS.pz) cgs_pzEnd(); return; }
    const a = cgs_area(e.touches[0].target), b = cgs_area(e.touches[1].target);
    if (!a || a !== b || CG.st?.active || lp?.active || document.body.classList.contains('cgdrag') || document.body.classList.contains('tdrag')) return;
    cgs_dropHolds();
    const [p, q] = [e.touches[0], e.touches[1]];
    cgs_pzStart(a, (p.clientX + q.clientX) / 2, (p.clientY + q.clientY) / 2, 'touch');
    CGS.pz.d0 = Math.max(1, Math.hypot(p.clientX - q.clientX, p.clientY - q.clientY));
    return;
  }
  CGS.hold = false;
  const t = e.touches[0], a = cgs_area(e.target);
  // not from the screen's edges (the phone's own Back gesture), not in a field / the open "New event" block
  if (!a || cgs_busy() || cgs_el(e.target)?.closest('input, textarea, select, .cgnew') || t.clientX < 16 || t.clientX > innerWidth - 16) { CGS.sw = null; return; }
  CGS.sw = {x0: t.clientX, y0: t.clientY, t0: Date.now(), dx: 0, lock: null, els: null};
}, {passive: true});
document.addEventListener('touchmove', e => {
  const p = CGS.pz;
  if (p?.src === 'touch') {
    if (e.touches.length < 2) return;
    if (e.cancelable) e.preventDefault();  // no page zoom, no scroll: the fingers zoom the calendar
    const [a, b] = [e.touches[0], e.touches[1]];
    p.k = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) / p.d0;
    p.x = (a.clientX + b.clientX) / 2; p.y = (a.clientY + b.clientY) / 2;
    cgs_pzDraw();
    return;
  }
  const s = CGS.sw; if (!s || e.touches.length !== 1) return;
  const t = e.touches[0], dx = t.clientX - s.x0, dy = t.clientY - s.y0;
  if (!s.lock) {
    if (cgs_busy()) { CGS.sw = null; return; }
    if (Math.hypot(dx, dy) < 10) return;  // beyond the 8 px after which caldrag.js / dnd.js let go of their hold
    s.lock = Math.abs(dx) > Math.abs(dy) * 1.2 ? 'x' : 'y';
    if (s.lock === 'y') { CGS.sw = null; return; }  // up / down: the hours / the page scroll as before
    s.els = cgs_pages(); s.lx = t.clientX; s.lt = Date.now();
  }
  if (e.cancelable) e.preventDefault();
  s.v = (t.clientX - s.lx) / Math.max(1, Date.now() - s.lt); s.lx = t.clientX; s.lt = Date.now();
  s.dx = t.clientX - s.x0;
  cgs_shift(s.els, s.dx);
}, {passive: false});
function cgs_touchEnd(e) {
  if (CGS.pz?.src === 'touch') {
    if (e.touches.length >= 2) return;
    CGS.hold = e.touches.length > 0;
    cgs_pzEnd(); return;
  }
  const s = CGS.sw; CGS.sw = null;
  if (!s?.els || CGS.hold) return;
  const w = $('#view')?.clientWidth || innerWidth;
  // far enough (a fifth of the width) or a quick flick: the next / previous period, else back into place
  const go = e.type !== 'touchcancel' && (Math.abs(s.dx) > Math.min(90, w * .2) || (Math.abs(s.dx) > 30 && Math.abs(s.v || 0) > .35 && Math.sign(s.v) === Math.sign(s.dx)));
  if (go) cgs_turn(s.els, s.dx < 0 ? 1 : -1); else cgs_back(s.els);
}
document.addEventListener('touchend', cgs_touchEnd, {passive: true});
document.addEventListener('touchcancel', cgs_touchEnd, {passive: true});

// ---- trackpad / mouse: Ctrl + wheel (a trackpad pinch arrives so in Chrome, Edge, Firefox) zooms, sideways turns the page
($('#view') || document).addEventListener('wheel', e => {  // on the view only: scrolling elsewhere never waits for it
  const a = cgs_area(e.target); if (!a || cgs_busy()) return;
  const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
  if (e.ctrlKey) {
    e.preventDefault();  // not the browser's page zoom
    if (CGS.pz && CGS.pz.src !== 'wheel') return;
    if (!CGS.pz) cgs_pzStart(a, e.clientX, e.clientY, 'wheel');
    const p = CGS.pz;
    p.k *= Math.exp(-Math.max(-25, Math.min(25, e.deltaY * unit)) * .01);
    p.x = e.clientX; p.y = e.clientY;
    cgs_pzDraw();
    clearTimeout(p.idle); p.idle = setTimeout(() => { if (CGS.pz === p) cgs_pzEnd(); }, 220);  // the pinch has ended
    return;
  }
  const dx = e.deltaX * unit;
  if (!dx || Math.abs(dx) <= Math.abs(e.deltaY * unit)) return;
  e.preventDefault();  // not the browser's history swipe
  let w = CGS.wx;
  if (w?.done) { clearTimeout(w.idle); w.idle = setTimeout(() => { if (CGS.wx === w) CGS.wx = null; }, 250); return; }  // the swipe's run-out
  if (!w) w = CGS.wx = {acc: 0, els: cgs_pages()};
  w.acc += dx;
  clearTimeout(w.idle);
  if (Math.abs(w.acc) >= 110) {
    w.done = true;
    cgs_turn(w.els, w.acc > 0 ? 1 : -1);
    w.idle = setTimeout(() => { if (CGS.wx === w) CGS.wx = null; }, 250);
    return;
  }
  cgs_shift(w.els, -w.acc * .6);
  w.idle = setTimeout(() => { if (CGS.wx !== w) return; CGS.wx = null; cgs_back(w.els); }, 160);
}, {passive: false});
// Safari (Mac, iPad trackpad): a pinch comes as gesture events; on the phone the touch events started the zoom first (the
// gesture is only stopped then: no page zoom)
for (const [ev, fn] of /** @type {[string, (e: any) => void][]} */ ([
  ['gesturestart', e => { if (!CGS.pz && !cgs_busy()) cgs_pzStart(cgs_area(e.target), e.clientX, e.clientY, 'gesture'); }],
  ['gesturechange', e => { const p = CGS.pz; if (p?.src !== 'gesture') return; p.k = e.scale || 1; cgs_pzDraw(); }],
  ['gestureend', () => { if (CGS.pz?.src === 'gesture') cgs_pzEnd(); }],
])) {
  document.addEventListener(ev, e => {
    if (!cgs_area(e.target) && !(CGS.pz && ev !== 'gesturestart')) return;
    e.preventDefault();
    fn(e);
  });
}

// ---- a double tap (double click) on a day of the month opens that day
document.addEventListener('click', e => {
  const c = cgs_el(e.target)?.closest('#view .cal .cell[data-day]');
  if (!c || cgs_el(e.target)?.closest('.ev, .cev, .more, .cgnew, button, a, input')) { CGS.tap = null; return; }
  const d = c.getAttribute('data-day'), now = Date.now(), t = CGS.tap;
  if (t && t.day === d && now - t.at < 400 && Math.hypot(e.clientX - t.x, e.clientY - t.y) < 30) {
    e.stopImmediatePropagation(); e.preventDefault();
    CGS.tap = null;
    cgs_go('day', d, 1, e.clientX, e.clientY);
    return;
  }
  CGS.tap = {day: d, x: e.clientX, y: e.clientY, at: now};
}, true);
