/* Kalmido web client: the statistics view (module "stats", loaded on demand, 2.65.0 #1823; moved unchanged from
   templates.js, whose charts barChart / lineChart / hbarChart the time tracking and the agent usage share and keep).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';
S.st = {data: null, loading: false, err: null, v: -1, sp: '', mode: LS.get('statsMode', 'week')};
// 2.398.0 (#3406): the statistics of the shown workspace (its projects; Private: also focus and time without a project);
// "All workspaces" = everything. A switch loads again (S.st.sp = the workspace the data is of)
const st_space = () => typeof wsCur === 'function' ? wsCur() : 'all';
async function loadStats() {
  if (S.st.loading) return;
  S.st.loading = true;
  const v = S.v, sp = st_space();
  try { S.st.data = await rawFetch('GET', '/api/stats?ws=' + weekStart() + (sp !== 'all' ? '&space=' + encodeURIComponent(sp) : '')); S.st.err = null; S.st.v = v; S.st.sp = sp; }
  catch (e) { if (e.message !== 'auth') S.st.err = e instanceof Offline ? 'offline' : e.message; S.st.v = v; S.st.sp = sp; }
  finally { S.st.loading = false; }
  if (S.route.mod === 'stats') renderView();
}
function heatmap(weeks, perDay, t0, {unit}) {  // weeks: first days (locale week start); columns = weeks, rows = weekdays
  const z = uiZ(), W = chartW(), lab = Math.round(30 * z), gap = 3, cs = Math.max(10, Math.min(22 * z, Math.floor((W - lab) / weeks.length) - gap));
  const H = 7 * (cs + gap) + Math.round(20 * z), max = Math.max(1, ...Object.values(perDay));
  const lvl = v => !v ? 0 : Math.min(4, Math.ceil(4 * v / max));
  let h = [0, 2, 4, 6].map(r => `<text class="ch-ax" x="${lab - 6}" y="${r * (cs + gap) + cs * .75}" text-anchor="end">${esc(WD[(pd(weeks[0]).getDay() + r) % 7])}</text>`).join('');
  weeks.forEach((w, c) => {
    for (let r = 0; r < 7; r++) {
      const d = addDays(w, r); if (d > t0) continue;
      const v = perDay[d] || 0;
      h += `<rect class="hm l${lvl(v)}" x="${lab + c * (cs + gap)}" y="${r * (cs + gap)}" width="${cs}" height="${cs}" rx="3"><title>${esc(`${fmtDate(d)}: ${unit(v)}`)}</title></rect>`;
    }
  });
  h += `<text class="ch-ax" x="${lab}" y="${H - 4}">${esc(shortDay(weeks[0]))}</text><text class="ch-ax" x="${lab + weeks.length * (cs + gap) - gap}" y="${H - 4}" text-anchor="end">${esc(tr('Today'))}</text>`;
  return `<svg class="chart" width="${Math.min(W, lab + weeks.length * (cs + gap))}" height="${H}" role="img" aria-label="${esc(tr('Completed per day'))}">${h}</svg>
    <div class="hmleg muted">${tr('less')}${[0, 1, 2, 3, 4].map(l => `<i class="hm l${l}"></i>`).join('')}${tr('more')}</div>`;
}
const listLabel = x => x.id === -1 ? tr('No task') : x.id === 0 ? tr('Other projects') : x.is_inbox && inboxDef(x.name) ? tr('Basket') : listName(x.name);
function viewStats() {
  const st = S.st;
  if ((st.v !== S.v || st.sp !== st_space() || !st.data) && !st.loading) setTimeout(loadStats, 0);
  const j = st.sp === st_space() ? st.data : null;  // 2.398.0 (#3406): never another workspace's numbers
  if (!j && S.ly.view === 'stats') return `<div class="stats">${lyHtml('stats', {})}</div>`;  // 2.55.0 (#1067)
  if (!j) return `<div class="stats"><div class="empty">${st.err ? (st.err === 'offline' ? tr('Statistics are only available online.') : esc(st.err)) : tr('Loading…')}</div></div>`;
  const wl = j.weeks.map(shortDay), tipW = (i, s) => `${tr('Week of {0}', fmtDate(j.weeks[i]))}: ${s}`;
  const tiles = [
    [j.done.this_week, tr('completed this week'), trn('{0} today', '{0} today', j.done.today)],
    [j.ontime.rate == null ? '–' : j.ontime.rate + '%', tr('on time'), j.ontime.with_due ? tr('{0} of {1} with a date', j.ontime.ontime, j.ontime.with_due) : tr('no completed tasks with a date')],
    [j.streak.current, trn('day in a row', 'days in a row', j.streak.current), tr('best: {0}', j.streak.best)],
    ...(feat('pomo') ? [[fmtH(j.focus.this_week), tr('focus this week'), tr('12 weeks: {0}', fmtH(j.focus.total))]] : []),
    ...(timeOn() && j.time ? [[fmtH(j.time.this_week), tr('tracked this week'), tr('12 weeks: {0}', fmtH(j.time.total))]] : []),
  ];
  const mode = st.mode;
  // 2.55.0 (#1067): the tiles and cards are blocks of the view builder (same order and width as before: one under the other)
  const P = {};
  P.tiles = `<div class="sttiles">${tiles.map(([v, l, s]) => `<div><b>${esc(String(v))}</b><span>${esc(l)}</span><small>${esc(s)}</small></div>`).join('')}</div>`;
  P.done = `<section class="stcard"><div class="sthead"><h3>${tr('Completed tasks')}</h3><p class="muted shint stnote">${tr('Last 12 weeks. Counts for the person who ticks it off. On time = by the due day. Overdue = your open tasks past the date.')}</p><span class="muted">${trn('{0} in 12 weeks', '{0} in 12 weeks', j.done.total)}</span><span class="spacer"></span>
      <div class="seg"><button class="${mode === 'week' ? 'on' : ''}" data-act="stats-mode" data-k="week">${tr('Weeks')}</button><button class="${mode === 'day' ? 'on' : ''}" data-act="stats-mode" data-k="day">${tr('Days')}</button></div></div>
      ${mode === 'day' ? heatmap(j.weeks, j.done.per_day, j.today, {unit: v => trn('{0} completed', '{0} completed', v)})
        : barChart(j.done.per_week, wl, {tip: i => tipW(i, trn('{0} completed', '{0} completed', j.done.per_week[i])), label: tr('Completed per week')})}</section>`;
  P.bylist = `<section class="stcard"><div class="sthead"><h3>${tr('By project')}</h3><span class="muted">${tr('last 12 weeks')}</span></div>
      ${hbarChart(j.done.by_list.map(x => ({name: listLabel(x), v: x.n})), {label: tr('Completed by project')})}</section>`;
  P.overdue = `<section class="stcard"><div class="sthead"><h3>${tr('Overdue')}</h3><span class="muted">${trn('{0} overdue now', '{0} overdue now', j.overdue[j.overdue.length - 1].n)}</span></div>
      ${lineChart(j.overdue.map(x => x.n), j.overdue.map((x, i) => i === j.overdue.length - 1 ? tr('Today') : shortDay(x.date)), {label: tr('Overdue tasks at the end of each week'), tip: i => `${i === j.overdue.length - 1 ? tr('Today') : fmtDate(j.overdue[i].date)}: ${trn('{0} overdue', '{0} overdue', j.overdue[i].n)}`})}</section>`;
  if (feat('pomo')) P.focus = `<section class="stcard"><div class="sthead"><h3>${tr('Focus time')}</h3><span class="muted">${trh('12 weeks: {0}', fmtH(j.focus.total))}</span></div>
      ${barChart(j.focus.per_week, wl, {fmt: v => fmtH(Math.round(v)), tip: i => tipW(i, fmtH(j.focus.per_week[i])), label: tr('Focus minutes per week'), time: true})}
      <h4>${tr('By project')}</h4>${hbarChart(j.focus.by_list.map(x => ({name: listLabel(x), v: x.minutes})), {fmt: fmtH, label: tr('Focus by project')})}</section>`;
  if (timeOn() && j.time) P.time = `<section class="stcard"><div class="sthead"><h3>${tr('Tracked time')}</h3><span class="muted">${trh('12 weeks: {0}', fmtH(j.time.total))}</span><span class="spacer"></span><button class="btn sm" data-go="time">${ic('clock', 's')} ${tr('Reports')}</button></div>
      ${barChart(j.time.per_week, wl, {fmt: v => fmtH(Math.round(v)), tip: i => tipW(i, fmtH(j.time.per_week[i])), label: tr('Tracked minutes per week'), time: true})}
      <h4>${tr('By project')}</h4>${hbarChart(j.time.by_list.map(x => ({name: listLabel(x), v: x.minutes})), {fmt: fmtH, label: tr('Tracked time by project')})}</section>`;
  const hs = feat('habits') && !o3a_orgView() ? S.habits.filter(x => !x.archived) : [];  // 2.398.0 (#3406): habits are private (not in an organisation's view)
  if (hs.length) P.habits = `<section class="stcard"><div class="sthead"><h3>${tr('Habits')}</h3></div><div class="sthabits">
      <div class="shh muted"><span></span><span>${tr('rate')}</span><span>${tr('streak')}</span><span>${tr('best')}</span></div>
      ${hs.map(x => { const s = habitStats(x), col = cssColor(x.color) || HCOLORS[0]; return `<div class="shr" data-act="habit-open" data-id="${x.id}" title="${esc(x.per_week ? tr('Share of the last 4 weeks that reached the target') : tr('Share of the scheduled days of the last 30 days'))}"><span class="n"><i class="sw" style="background:${col}"></i>${esc(x.name)}</span>
        <span class="rate"><svg width="64" height="8" viewBox="0 0 64 8" preserveAspectRatio="none" aria-hidden="true"><rect class="ch-track" width="64" height="8" rx="4"/><rect class="ch-bar" width="${Math.round(64 * s.rate / 100)}" height="8" rx="4"/></svg><b>${s.rate}%</b></span><span><b>${s.streak}</b> ${esc(streakUnit(x))}</span><span>${s.best}</span></div>`; }).join('')}</div></section>`;
  // 2.630.0 (#4617): Home & life -- the API sends a block's key only while its module is on (health never to an organisation's view)
  if (j.contracts) P.contracts = stl_contracts(j.contracts);
  if (j.health) P.health = stl_health(j.health, wl, tipW);
  if (j.travel) P.travel = stl_travel(j.travel);
  // 2.39.1 (#1180): the long note sits behind the (i) next to the first heading (infoize, icons.js), closed by default
  return `<div class="stats">${S.ly.view === 'stats' ? '' : `<div class="lybar"><span class="spacer"></span>${lyCustomBtn('stats')}</div>`}${lyHtml('stats', P)}</div>`;
}
// 2.630.0 (#4617): the blocks contracts, health and travel (kalmido/personal/statslife.py)
const stl_tiles = ts => `<div class="sttiles">${ts.map(([v, l, x]) => `<div><b>${esc(String(v))}</b><span>${esc(l)}</span><small>${esc(x)}</small></div>`).join('')}</div>`;
const stl_when = d => esc(dayLabel(d));
function stl_contracts(c) {
  const rows = c.notice.map(x => `<li><a href="#t/${x.task_id}">${esc(x.name)}</a>${x.provider ? ` <span class="muted">${esc(x.provider)}</span>` : ''}<span class="spacer"></span><span class="muted">${stl_when(x.due)}</span></li>`).join('');
  return `<section class="stcard stl-contracts"><div class="sthead"><h3>${tr('Contracts')}</h3></div>
    ${stl_tiles([[c.count, trn('running contract', 'running contracts', c.count), tr('Deadlines to cancel in the next {0} days: {1}', c.notice_days, c.notice.length)],
      [fmtMoney(c.monthly), tr('per month'), tr('{0} per year', fmtMoney(c.yearly))]])}
    <h4>${tr('Deadlines to cancel')}</h4>${rows ? `<ul class="stlist">${rows}</ul>` : `<div class="muted stempty">${trh('No deadline to cancel in the next {0} days.', c.notice_days)}</div>`}
    <h4>${tr('By provider')}</h4>${hbarChart(c.by_provider.map(x => ({name: `${x.name || tr('No provider')} (${x.n})`, v: x.monthly})), {fmt: fmtMoney, label: tr('Cost per month by provider')})}</section>`;
}
function stl_health(h, wl, tipW) {
  const rows = h.people.map(p => `<div class="stlr"><span class="n">${esc(p.name || tr('Me'))}</span><span>${trh('{0} done', p.done)}</span>
    <span>${p.next ? `<a href="#t/${p.next.task_id}">${esc(p.next.title)}</a> <span class="muted">${stl_when(p.next.due)}</span>` : `<span class="muted">${tr('nothing due')}</span>`}</span>
    <span class="${p.overdue ? 'od' : 'muted'}">${trn('{0} overdue', '{0} overdue', p.overdue)}</span>
    <span class="muted">${p.med_due ? esc(tr('Intakes done {0} of {1}', p.med_done, p.med_due)) : ''}</span></div>`).join('');
  return `<section class="stcard stl-health"><div class="sthead"><h3>${tr('Health')}</h3><span class="muted">${trn('{0} in 12 weeks', '{0} in 12 weeks', h.done)}</span></div>
    ${barChart(h.per_week, wl, {tip: i => tipW(i, tr('{0} done', h.per_week[i])), label: tr('Appointments, check-ups and vaccinations done per week')})}
    <h4>${tr('By person')}</h4>${rows ? `<div class="stlrows">${rows}</div>` : `<div class="muted stempty">${tr('Nothing in this period.')}</div>`}</section>`;
}
function stl_travel(t) {
  const cost = w => w.costs.map(x => curMoney(x.amount, x.currency)).join(' + ');
  const n = t.next, tiles = [[t.last12.trips, trn('trip in the last 12 months', 'trips in the last 12 months', t.last12.trips), trn('{0} travel day', '{0} travel days', t.last12.days)],
    [t.year.trips, tr('trips in {0}', t.year.year), trn('{0} travel day', '{0} travel days', t.year.days)]];
  if (t.last12.costs.length || t.year.costs.length) tiles.push([cost(t.year) || '–', tr('travel expenses {0}', t.year.year), tr('12 months: {0}', cost(t.last12) || '–')]);
  return `<section class="stcard stl-travel"><div class="sthead"><h3>${tr('Travel')}</h3></div>${stl_tiles(tiles)}
    <h4>${tr('Next trip')}</h4>${n ? `<ul class="stlist"><li><a href="#l/${n.list_id}">${esc(n.name)}</a>${n.where ? ` <span class="muted">${esc(n.where)}</span>` : ''}<span class="spacer"></span><span class="muted">${esc(fmtDate(n.from))} – ${esc(fmtDate(n.to))}</span></li></ul>` : `<div class="muted stempty">${tr('No trip planned.')}</div>`}</section>`;
}
let statsResize;
window.addEventListener('resize', () => { if (S.route.mod !== 'stats') return; clearTimeout(statsResize); statsResize = setTimeout(renderView, 150); });
