// @ts-check
// 2.155.0 C (#2078): the calendar's year view: twelve small months, a day with events or tasks tinted in the accent colour
// (the more, the stronger), today ringed. A tap on a day opens the day view, a tap on a month name the month view; the
// arrows turn the year. One request for the whole year (the same events call the other views use), only counted per day.

// day -> number of events + open tasks (ghosts of repeating tasks included) of the year
function cyr_counts(lo, hi) {
  const cnt = /** @type {Map<string, number>} */ (new Map());
  const add = (d, n) => cnt.set(d, (cnt.get(d) || 0) + n);
  for (const [d, ts] of calByDay(lo, hi)) add(d, ts.length);
  if (calEvOn()) {
    ensureCalEv(lo, hi);
    for (const e of S.cal.items) {
      if (!cevWs(e)) continue;
      const a = e.d0 < lo ? lo : e.d0, b = e.d1 > hi ? hi : e.d1;
      for (let d = a, i = 0; d <= b && i < 370; d = addDays(d, 1), i++) add(d, 1);
    }
  }
  return cnt;
}
function cyr_month(y, m, cnt, t0) {
  const first = `${y}-${pad(m + 1)}-01`, start = weekStartOf(first), mk = first.slice(0, 7);
  const days = new Date(y, m + 1, 0).getDate(), lead = diffDays(start, first);
  const head = wdOrder().map(i => `<i class="cywd" aria-hidden="true">${esc(WD[i].slice(0, 2))}</i>`).join('');
  let cells = '<i class="cyd gap"></i>'.repeat(lead);
  for (let n = 1; n <= days; n++) {
    const d = `${mk}-${pad(n)}`, c = cnt.get(d) || 0, lv = c ? c > 4 ? 3 : c > 1 ? 2 : 1 : 0;
    cells += `<button type="button" class="cyd ${lv ? 'lv' + lv : ''} ${d === t0 ? 'today' : ''} ${d === S.calSel ? 'sel' : ''}" data-cyd="${d}" aria-label="${esc(fmtDay('long', pd(d)) + (c ? ', ' + trn('{0} entry', '{0} entries', c) : ''))}">${n}</button>`;
  }
  return `<section class="cymon" aria-label="${esc(MON[m] + ' ' + y)}"><button type="button" class="cym" data-cym="${mk}">${esc(MON[m])}</button><div class="cygrid">${head}${cells}</div></section>`;
}
function cyr_view() {
  const y = +(S.calSel || today()).slice(0, 4), lo = `${y}-01-01`, hi = `${y}-12-31`, t0 = today();
  const cnt = cyr_counts(lo, hi);
  return `${calBar(String(y))}<div class="cyear" id="cyear">${[...Array(12).keys()].map(m => cyr_month(y, m, cnt, t0)).join('')}</div>`;
}
document.addEventListener('click', e => {
  const b = /** @type {HTMLElement|null} */ (e.target instanceof Element ? e.target.closest('[data-cyd], [data-cym]') : null);
  if (!b || !b.closest('#cyear')) return;
  if (b.dataset.cyd) { S.calSel = b.dataset.cyd; S.calMode = 'day'; }
  else if (b.dataset.cym) { S.calSel = `${b.dataset.cym}-01`; S.calMonth = b.dataset.cym; S.calMode = 'month'; }
  LS.set('calMode', S.calMode); renderView();
});
