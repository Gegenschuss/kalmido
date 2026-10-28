/* Kalmido web client: Day planning and the evening review.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.10.0 (#440): day planning
// "Plan my day" / "Fill free time" in Today: the server's built-in planner (GET /api/dayplan) proposes slots between the
// day's calendar events and timed tasks within the working hours; the preview shows them as a timeline, every entry can be
// left out, "Apply" sets the planned start (plan_start) and the duration in one step (undo takes it back); 2.11.0: due
// dates, times and deadlines never change, tasks that do not fit are only listed. With an agent that is online, "Let an
// agent plan" sends the same input as a proposal (kind dayplan); its answer opens in the same timeline (proposal dialog).
const DP_REASON = {overdue: N_('overdue'), today: N_('due today'), deadline: N_('deadline'), due: N_('due soon'), priority: N_('priority'), fixed: N_('fixed'), planned: N_('planned')};
const dpMin = hm => { const [h, m] = String(hm || '0:0').split(':'); return +h * 60 + +m; };
const dpHm = m => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
function dayplanBar() {  // Today: the two buttons above the list
  if (S.route.key !== 'today') return '';
  return `<div class="dpbar"><button class="btn sm" data-act="dayplan" data-mode="day">${ic('cal', 's')} ${tr('Plan my day')}</button><button class="btn sm" data-act="dayplan" data-mode="fill">${ic('clock', 's')} ${tr('Fill free time')}</button></div>`;
}
// one timeline: rows sorted by time (events, fixed tasks, planned entries) + the entries that do not fit any more
function dpTimeline(rows, defer, o = {}) {
  const hgt = d => `style="min-height:${Math.min(8, 2.75 + Math.max(0, (d || 30) - 30) / 30 * 0.75).toFixed(2)}rem"`;
  const item = r => {
    const on = !o.sel || o.sel.has(r.key);
    if (r.kind === 'event' || r.kind === 'fixed') return `<div class="dprow ${r.kind}" ${hgt(dpMin(r.end) - dpMin(r.start))}><span class="dpt">${esc(r.start)}<small>${esc(r.end)}</small></span><span class="dpb">${ic(r.kind === 'event' ? 'cal' : 'lock', 's')}<span class="dpn">${mdTitleNL(r.title)}</span><span class="muted dps">${r.kind === 'event' ? tr('Event') : tr(DP_REASON[r.reason] || 'fixed')}</span></span></div>`;
    return `<div class="dprow plan ppi ${on ? '' : 'off'}" data-k="${esc(r.key)}" ${hgt(r.duration)}><span class="dpt">${esc(r.start)}<small>${esc(r.end)}</small></span>
      <label class="ppcl"><input type="checkbox" class="ppc" ${on ? 'checked' : ''} aria-label="${esc(tr('Select {0}', r.title))}"></label>
      <span class="dpb"><span class="dpn">${mdTitleNL(r.title)}</span><span class="muted dps">${esc(r.list || '')}${r.list ? ' · ' : ''}${r.estimated ? '≈ ' : ''}${esc(fmtH(r.duration))}${r.reason ? ' · ' + esc(tr(DP_REASON[r.reason] || r.reason)) : ''}${r.note ? ' · ' + esc(r.note) : ''}</span></span></div>`;
  };
  // 2.11.0: what does not fit is only listed (no checkbox): its due date, time and deadline stay as they are
  // 2.13.0 (#453 A8): no dead end: "Tomorrow" plans it for tomorrow's start of work (its due date stays), "Plan on …"
  // opens its date dialog
  const dfr = defer.map(r => `<div class="dprow nofit"><span class="dpt">${ic('clock', 's')}</span>
    <span class="dpb"><span class="dpn">${mdTitleNL(r.title)}</span><span class="muted dps">${[r.due ? tr('Due: {0}', fmtDayAbs(r.due)) : '', r.note || ''].filter(Boolean).map(esc).join(' · ')}</span></span>${o.acts && r.task_id ? `<span class="dpna"><button class="btn sm" data-dp="nofit-tm" data-id="${r.task_id}">${tr('Tomorrow')}</button><button class="btn sm" data-dp="nofit-date" data-id="${r.task_id}">${tr('Plan on …')}</button></span>` : ''}</div>`).join('');
  const all = rows.slice().sort((a, b) => dpMin(a.start) - dpMin(b.start) || (a.kind === 'plan') - (b.kind === 'plan'));
  return `<div class="dptl">${all.map(item).join('') || `<div class="muted mhint">${tr('Nothing to plan: no open tasks fit into the free time.')}</div>`}</div>
    ${dfr ? `<h4 class="dph">${tr('Does not fit today')}</h4><div class="dptl">${dfr}</div>` : ''}`;
}
const dpRowsOf = p => [...p.events.filter(e => !e.all_day).map(e => ({kind: 'event', start: e.start, end: e.end, title: e.title})),
  ...p.fixed.map(t => ({kind: 'fixed', start: t.start, end: t.end, title: t.title, reason: t.reason}))];
// 2.149.0 F (#2518): the dialog (dayplanModal, dpApply, dpAskAgent) is in dpmodal.js, loaded on its first use
// the dayplan proposal of an agent in the proposal dialog: the same timeline (keys = index into items; nofit only listed)
function propDayplanHtml() {
  const {v} = S.prop, p = v.proposal, inp = v.input, tk = id => (inp.tasks || []).find(t => t.task_id === id) || {};
  const plan = p.items.map((x, i) => { const t = tk(x.task_id), d = x.duration || t.duration || inp.default_duration || 30, e = S.prop.ed[String(i)] || {};
    const st = e.time || x.start, du = e.duration || d;
    return {kind: 'plan', key: String(i), start: st, end: dpHm(Math.min(1439, dpMin(st) + du)), title: t.title || '?', list: t.list, duration: du, estimated: !x.duration && t.estimated, note: x.note}; });
  const defer = (p.nofit || p.defer || []).map(x => ({title: tk(x.task_id).title || '?', due: tk(x.task_id).due, note: x.note}));
  const fake = {events: inp.events || [], fixed: inp.fixed || []};
  return `<div class="dpsum muted">${esc(tr('{0}, working hours {1}–{2}', fmtDayAbs(inp.date), inp.work?.start || '', inp.work?.end || ''))}</div>` + dpTimeline([...dpRowsOf(fake), ...plan], defer, {sel: S.prop.sel});
}
// ---- the evening review: a card in Today after the end of the working hours (or opened from its push)
S.review = {day: null, data: null, busy: false, hidden: null};
// 2.364.0 B (#3031): the evening review from the account's second week (older than 7 days; its push link still opens it)
const st_young = () => !!S.me?.since && (Date.parse(today()) - Date.parse(S.me.since)) / 864e5 <= 7;
function reviewCard() {
  if (S.route.key !== 'today' || !S.dayplan || (st_young() && !S.route.review)) return '';
  const now = new Date(), hm = dpHm(now.getHours() * 60 + now.getMinutes()), t0 = today();
  const want = S.route.review || hm >= (S.dayplan.work_end || '17:00');
  if (!want || LS.get('reviewHidden', '') === t0 && !S.route.review) return '';
  if (S.review.day !== t0 && !S.review.busy) {
    S.review.busy = true;
    calReq('GET', '/api/dayplan/review').then(j => { S.review = {day: t0, data: j, busy: false}; if (S.route.key === 'today') viewSafeRender(); }).catch(() => { S.review.busy = false; });
    return '';
  }
  const r = S.review.data; if (!r || !r.tomorrow) return '';  // 2.84.0: an answer without the day (the browser demo after work_end) shows no card
  const li = (arr, cls) => arr.slice(0, 5).map(x => `<li class="${cls}">${mdTitleNL(x.title)}</li>`).join('') + (arr.length > 5 ? `<li class="muted">${esc(trn('and {0} more', 'and {0} more', arr.length - 5))}</li>` : '');
  const tm = r.tomorrow;
  const plan = `<button class="btn sm" data-act="dayplan" data-mode="day" data-day="${esc(tm.date)}">${ic('cal', 's')} ${tm.date === addDays(today(), 1) ? tr('Plan tomorrow') : esc(tr('Plan {0}', fmtDayAbs(tm.date)))}</button>`;
  // 2.31.0 (#1052): after the first read (the visit of Today that showed it) the card folds to one line for the rest of the
  // day: "1 done · 7 still open · Plan tomorrow"; the line unfolds it again (remembered per device and day)
  if (LS.get('reviewSeen', '') !== t0) { LS.set('reviewSeen', t0); S.review.route = S.route; }
  const fold = !S.route.review && S.review.route !== S.route && LS.get('reviewOpen', '') !== t0;
  if (fold) return `<section class="rvcard fold" aria-label="${esc(tr('Daily review'))}"><button type="button" class="rvfold" data-act="review-fold" aria-expanded="false">${ic('chev', 's')}<span class="rvft">${esc(tr('Daily review'))}</span><span class="rvfn">${r.done.length} ${tr('done|review')} · ${r.open.length} ${tr('still open')}</span></button>${plan}<button class="iconbtn" data-act="review-hide" title="${esc(tr('Hide for today'))}" aria-label="${esc(tr('Hide for today'))}">${ic('x', 's')}</button></section>`;
  return `<section class="rvcard" aria-labelledby="rv-h"><div class="rvhd"><button type="button" class="rvfold" data-act="review-fold" aria-expanded="true" aria-label="${esc(tr('Daily review'))}">${ic('chev', 's')}</button><h3 id="rv-h">${ic('done', 's')} ${tr('Daily review')}</h3><span class="spacer"></span><button class="iconbtn" data-act="review-hide" title="${esc(tr('Hide for today'))}" aria-label="${esc(tr('Hide for today'))}">${ic('x', 's')}</button></div>
    <div class="rvnums"><span><b>${r.done.length}</b> ${tr('done|review')}</span><span><b>${r.open.length}</b> ${tr('still open')}</span><span><b>${r.moved.length}</b> ${tr('moved')}</span></div>
    ${r.done.length ? `<ul class="rvl">${li(r.done, 'ok')}</ul>` : ''}
    <div class="rvtm"><span class="muted">${esc(tm.count ? tr('Suggestion for {0}: {1}', fmtDayAbs(tm.date), tm.plan.slice(0, 3).map(x => x.start + ' ' + x.title).join(', ')) : tr('Nothing planned for {0} yet.', fmtDayAbs(tm.date)))}</span>
      ${plan}${feat('review') ? `<a class="btn sm" href="#review">${ic('journal', 's')} ${tr('Journal')}</a>` : ''}</div></section>`;
}

// ---- 2.34.0 (#264): the morning briefing, the first block of Today: the numbers (due today, overdue, blocked, new since
// yesterday, lying idle) and the short lists "New since yesterday", "Blocked", "Lying idle" (today's tasks are Today itself).
// "Read" is kept on the server per day (every device folds it); the folded line still opens it. Nothing to say: no block.
S.brief = {data: null, busy: false, v: null, at: 0, open: false};
const BRIEF_KINDS = {assigned: N_('assigned to you'), comment: N_('new comment'), status: N_('status changed'), due: N_('date changed')};
function briefLoad(force) {
  const b = S.brief;
  if (b.busy || (!force && b.data && b.data.date === today() && (b.v === S.v || Date.now() - b.at < 60000))) return;
  b.busy = true;
  rawFetch('GET', '/api/briefing').then(j => { Object.assign(b, {data: j, v: S.v, at: Date.now()}); if (S.route.key === 'today') viewSafeRender(); })
    .catch(() => {}).finally(() => { b.busy = false; });
}
function briefNums(n, fold) {
  const parts = [[n.today, trn('{0} due today', '{0} due today', n.today)], [n.overdue, trn('{0} overdue', '{0} overdue', n.overdue)],
    [n.blocked, trn('{0} blocked', '{0} blocked', n.blocked)], [n.changed, trn('{0} new since yesterday', '{0} new since yesterday', n.changed)],
    [n.stale, trn('{0} lying idle', '{0} lying idle', n.stale)]].filter(p => p[0]);
  if (fold) return esc(parts.map(p => p[1]).join(' · '));
  return parts.map(p => { const s = String(p[1]), i = s.indexOf(String(p[0])); return i < 0 ? `<span>${esc(s)}</span>` : `<span>${esc(s.slice(0, i))}<b>${p[0]}</b>${esc(s.slice(i + String(p[0]).length))}</span>`; }).join('');
}
// 2.218.0 A (#2803): due today / overdue counted from the groups Today shows (the server's numbers were up to a minute old
// after a tick, so the card said "4 overdue" over a section "Overdue 3"); blocked / new / idle stay the server's
function briefLiveNums(groups) {
  const t0 = today(), seen = new Set(), o = {today: 0, overdue: 0};
  for (const g of groups) for (const t of g.tasks) {
    if (seen.has(t.id) || t.status !== 0) continue;
    seen.add(t.id);
    if (t.due && t.due < t0) o.overdue++; else if (t.due === t0 || planToday(t, t0)) o.today++;
  }
  return o;
}
// 2.364.0 B (#3031): Start shows the day's overview; Today drops its briefing card while Start is in the bar (not hidden there)
const st_on = () => !S.me?.kid && !sideHidden('e:home');
function briefCard(groups) {
  if (S.route.key !== 'today' || st_on()) return '';
  briefLoad();
  const d = S.brief.data; if (!d || d.date !== today()) return '';
  const n = groups ? {...d.counts, ...briefLiveNums(groups)} : d.counts; if (!(n.today || n.overdue || n.blocked || n.changed || n.stale)) return '';
  // 2.218.0 A (#2803): on a phone (portrait and landscape) the briefing is one slim line until it is opened: the numbers and
  // "Read" (unread); a computer keeps the card
  const line = isMobile() && !S.brief.open, read = (d.read || line) && !S.brief.open;
  if (read) return `<section class="rvcard fold bfcard${line ? ' bfline' : ''}" aria-label="${esc(tr('Briefing'))}"><button type="button" class="rvfold" data-brief="open" aria-expanded="false">${ic('chev', 's')}<span class="rvft">${esc(tr('Briefing'))}</span><span class="rvfn">${briefNums(n, true)}</span></button>${d.read ? '' : `<button type="button" class="btn sm" data-brief="read">${ic('check', 's')} ${tr('Read|briefing')}</button>`}</section>`;
  const more = (all, shown) => all > shown ? `<li class="muted">${esc(trn('and {0} more', 'and {0} more', all - shown))}</li>` : '';
  const who = x => (x.by || []).map(u => u.name).filter(Boolean).slice(0, 2).join(', ');
  const ch = d.changed.slice(0, 5).map(x => `<li><a href="#t/${x.id}">${mdTitleNL(x.title)}</a> <span class="muted">${esc([who(x), x.kinds.map(k => tr(BRIEF_KINDS[k] || k)).join(', ')].filter(Boolean).join(' · '))}</span></li>`).join('') + more(n.changed, Math.min(5, d.changed.length));
  const bl = d.blocked.slice(0, 5).map(x => `<li><a href="#t/${x.id}">${mdTitleNL(x.title)}</a> <span class="muted">${esc(x.reason === 'waiting' ? (x.wait_note ? tr('waiting on: {0}', x.wait_note) : tr('waiting on someone')) : tr('waiting for another task'))}</span></li>`).join('') + more(n.blocked, Math.min(5, d.blocked.length));
  const st = d.stale.slice(0, 3).map(x => `<li><a href="#t/${x.id}">${mdTitleNL(x.title)}</a> <span class="muted">${esc(trn('for {0} day', 'for {0} days', x.idle_days))}</span></li>`).join('') + more(n.stale, Math.min(3, d.stale.length));
  return `<section class="rvcard bfcard" aria-labelledby="bf-h"><div class="rvhd">${d.read || isMobile() ? `<button type="button" class="rvfold" data-brief="close" aria-expanded="true" aria-label="${esc(tr('Briefing'))}">${ic('chev', 's')}</button>` : ''}<h3 id="bf-h">${ic('sunrise', 's')} ${tr('Briefing')}</h3><span class="spacer"></span>${d.read ? '' : `<button type="button" class="btn sm" data-brief="read">${ic('check', 's')} ${tr('Read|briefing')}</button>`}</div>
    <div class="rvnums">${briefNums(n)}</div>
    ${ch ? `<h4>${tr('New since yesterday')}</h4><ul class="rvl bfl">${ch}</ul>` : ''}
    ${bl ? `<h4>${tr('Blocked')}</h4><ul class="rvl bfl">${bl}</ul>` : ''}
    ${st ? `<h4>${tr('Lying idle')}</h4><ul class="rvl bfl">${st}</ul>` : ''}</section>`;
}
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-brief]'); if (!a) return;
  e.preventDefault();
  const k = a.dataset.brief;
  if (k === 'open') { S.brief.open = true; renderView(); setTimeout(() => $('#view [data-brief="close"]')?.focus(), 0); return; }
  if (k === 'close') { S.brief.open = false; renderView(); setTimeout(() => $('#view [data-brief="open"]')?.focus(), 0); return; }
  if (k === 'read') {
    try { S.brief.data = await api('POST', '/api/briefing/read', {read: true}); S.brief.at = Date.now(); } catch { return; }
    S.brief.open = false; announce(tr('Briefing read')); renderView(); setTimeout(() => $('#view [data-brief="open"]')?.focus(), 0);
  }
});
