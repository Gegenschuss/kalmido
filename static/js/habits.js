/* Kalmido web client: The Eisenhower matrix, habits and the pomodoro timer.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ matrix
const QUADS = [[5, N_('Urgent & important')], [3, N_('Not urgent, but important')], [1, N_('Urgent, not important')], [0, N_('Neither urgent nor important')]];
// 1.5.3: the matrix can be narrowed (per device, LS 'mx'): scope = all | a list | a folder | a saved filter (same
// filter engine), "only mine" (assigned to me, or created by me and unassigned; only with collaboration) and "due by"
const MX_DUE = [['', N_('Any date')], ['today', N_('Overdue and today')], ['7', N_('Next 7 days')], ['30', N_('Next 30 days')]];
function mxGet() {
  const o = {scope: '', mine: false, due: '', ...(LS.get('mx', {}) || {})};
  if (o.scope.startsWith('l:') && !(listById(+o.scope.slice(2)) && !listById(+o.scope.slice(2)).archived)) o.scope = '';
  if (o.scope.startsWith('f:') && !S.filters.some(f => f.id === +o.scope.slice(2))) o.scope = '';
  if (o.scope.startsWith('folder:') && !folderNames().includes(o.scope.slice(7))) o.scope = '';
  if (!collab()) o.mine = false;
  return o;
}
function mxSet(p) { LS.set('mx', {...mxGet(), ...p}); if (S.route.mod === 'matrix') render(); }
const mxMineOk = () => collab() && (hasSharing() || S.lists.some(l => l.shared));
function mxScopeName(sc) {
  if (!sc) return tr('All lists');
  if (sc.startsWith('l:')) return lname(listById(+sc.slice(2)));
  if (sc.startsWith('folder:')) return tr('Folder {0}', fDisp(sc.slice(7)));
  if (sc.startsWith('f:')) return tr('Filter {0}', S.filters.find(f => f.id === +sc.slice(2))?.name || '');
  return '';
}
function mxTasks() {
  const o = mxGet(), t0 = today();
  let all = openTasks().filter(t => !t.parent_id);
  if (o.scope.startsWith('l:')) all = all.filter(t => t.list_id === +o.scope.slice(2));
  else if (o.scope.startsWith('folder:')) { const ids = new Set(folderLists(o.scope.slice(7)).map(l => l.id)); all = all.filter(t => ids.has(t.list_id)); }
  else if (o.scope.startsWith('f:')) { const f = S.filters.find(x => x.id === +o.scope.slice(2)); if (f) all = all.filter(t => filterMatch(t, f.rules)); }
  if (o.mine && mxMineOk() && S.me) all = all.filter(t => t.assignee_id === S.me.id || (!t.assignee_id && t.created_by === S.me.id));
  if (o.due) { const hi = o.due === 'today' ? t0 : addDays(t0, +o.due - 1); all = all.filter(t => t.due && t.due <= hi); }
  return all;
}
const mxList = () => {  // where quick add in the matrix puts a task: the scoped list / the folder's first list
  const sc = mxGet().scope;
  if (sc.startsWith('l:') && canAddTo(+sc.slice(2))) return +sc.slice(2);
  if (sc.startsWith('folder:')) return folderLists(sc.slice(7)).find(l => canAddTo(l.id))?.id;
  return undefined;
};
const mxActive = o => !!(o.scope || (o.mine && mxMineOk()) || o.due);
function mxTitle() {
  const o = mxGet(); if (!mxActive(o)) return '';
  return [o.scope ? mxScopeName(o.scope) : '', o.mine && mxMineOk() ? tr('only mine') : '', o.due ? tr(MX_DUE.find(x => x[0] === o.due)[1]) : ''].filter(Boolean).join(' · ');
}
function mxBar() {
  const o = mxGet();
  return `<div class="mxbar"><button class="btn sm mxscope ${o.scope ? 'on' : ''}" data-act="mx-scope" aria-haspopup="menu">${ic(o.scope.startsWith('folder:') ? 'folder' : o.scope.startsWith('f:') ? 'filter' : 'list', 's')}<span>${esc(mxScopeName(o.scope))}</span>${ic('chev', 's')}</button>
    ${mxMineOk() ? `<button class="btn sm chip ${o.mine ? 'on' : ''}" data-act="mx-mine" aria-pressed="${o.mine}">${ic('user', 's')} ${tr('Only mine')}</button>` : ''}
    <div class="seg mxdue" role="group" aria-label="${esc(tr('Due by'))}">${MX_DUE.map(([k, n]) => `<button class="${o.due === k ? 'on' : ''}" data-act="mx-due" data-k="${k}" aria-pressed="${o.due === k}">${tr(n)}</button>`).join('')}</div>
    ${mxActive(o) ? `<button class="iconbtn" data-act="mx-reset" title="${esc(tr('Show everything'))}" aria-label="${esc(tr('Show everything'))}">${ic('x', 's')}</button>` : ''}</div>`;
}
function mxScopeMenu(a) {
  const cur = mxGet().scope, lists = sideOrder().filter(l => !l.archived);
  menu(a, [{label: tr('All lists'), icon: 'all', on: !cur, fn: () => mxSet({scope: ''})}, '-',
    ...[inbox(), ...lists.filter(l => !l.is_inbox)].filter(Boolean).map(l => ({label: lname(l), icon: 'list', on: cur === 'l:' + l.id, fn: () => mxSet({scope: 'l:' + l.id})})),
    ...(folderNames().length ? ['-', ...folderNames().map(f => ({label: fDisp(f), icon: 'folder', on: cur === 'folder:' + f, fn: () => mxSet({scope: 'folder:' + f})}))] : []),
    ...(S.filters.length ? ['-', ...S.filters.map(f => ({label: f.name, icon: 'filter', on: cur === 'f:' + f.id, fn: () => mxSet({scope: 'f:' + f.id})}))] : [])]);
}
function viewMatrix() {
  const all = mxTasks();
  const dueKey = t => (t.due || '9999') + (t.due_time || '99');
  // 2.15.1 (#633): on a phone (one column) a tap on a quadrant's heading folds it; remembered per device
  const fold = isMobile() ? new Set(LS.get('mxFold', [])) : null;
  return `${mxBar()}<div class="matrix">${QUADS.map(([p, n]) => {
    const ts = all.filter(t => t.priority === p).sort((a, b) => dueKey(a).localeCompare(dueKey(b)) || bySort(a, b));
    const hd = `<span class="${p ? 'flag-' + p : 'muted'}">${ic('flag', 's')}</span>${tr(n)} <span class="c">${ts.length}</span>`;
    return `<div class="quad q${p} ${fold?.has(p) ? 'fold' : ''}" data-quad="${p}"><h3>${fold ? `<button type="button" class="qfold" data-act="mx-fold" data-p="${p}" aria-expanded="${!fold.has(p)}">${hd}${ic('chev', 's qcar')}</button>` : hd}</h3>
      <div class="qlist">${ts.map(t => taskRow(t, {showList: true, compact: true})).join('') || `<div class="muted" style="padding:.5rem .375rem;font-size:var(--fs-m)">${tr('empty')}</div>`}</div>
      <div class="kadd"><input placeholder="${tr('+ Task')}" aria-label="${esc(tr('New task'))}" data-qadd="${p}" enterkeyhint="done"></div></div>`;
  }).join('')}</div>`;
}

// ------------------------------------------------------------------ habits
const HCOLORS = ['#2dd4bf', '#6d8cff', '#6ee7b7', '#4ade80', '#f5b041', '#f87171', '#c084fc', '#f472b6', '#94a3b8'];
const habitScheduled = (h, d) => h.per_week ? true : h.days.includes(String(((pd(d).getDay() + 6) % 7) + 1));
const weekDone = (h, mon) => [...Array(7)].reduce((n, _, i) => n + ((h.logs[addDays(mon, i)] || 0) >= h.goal ? 1 : 0), 0);
function weekStreak(h) {  // "x times a week": consecutive weeks that reached the target (this week counts once reached)
  let mon = mondayOf(today()), n = 0, guard = 0;
  if (weekDone(h, mon) < h.per_week) mon = addDays(mon, -7);
  while (guard++ < 300 && weekDone(h, mon) >= h.per_week) { n++; mon = addDays(mon, -7); }
  return n;
}
const streakUnit = h => h.per_week ? trn('week', 'weeks', habitStreak(h)) : trn('day', 'days', habitStreak(h));
function habitStreak(h) {
  if (h.per_week) return weekStreak(h);
  const t0 = today(); let d = t0, n = 0, guard = 0;
  if ((h.logs[t0] || 0) < h.goal) d = addDays(t0, -1);
  while (guard++ < 800) {
    if (habitScheduled(h, d)) { if ((h.logs[d] || 0) >= h.goal) n++; else break; }
    d = addDays(d, -1);
    if (d < h.created_at.slice(0, 10)) break;
  }
  return n;
}
function habitStats(h) {
  const days = Object.entries(h.logs).filter(([, c]) => c >= h.goal).map(([d]) => d).sort();
  let best = 0, cur = 0, prev = null;
  for (const d of days) {
    if (prev) { let x = addDays(prev, 1); while (x < d && !habitScheduled(h, x)) x = addDays(x, 1); cur = x === d ? cur + 1 : 1; } else cur = 1;
    best = Math.max(best, cur); prev = d;
  }
  let sched = 0, hit = 0;
  if (h.per_week) {  // best run of weeks + share of the last 4 full weeks that hit the target
    const first = mondayOf(h.created_at.slice(0, 10)); let mon = mondayOf(today()), run = 0; best = 0;
    for (let g = 0; g < 300 && mon >= first; g++, mon = addDays(mon, -7)) { if (weekDone(h, mon) >= h.per_week) { run++; best = Math.max(best, run); } else if (g) run = 0; }
    for (let w = 1; w <= 4; w++) { const m = addDays(mondayOf(today()), -7 * w); if (m < first) break; sched++; if (weekDone(h, m) >= h.per_week) hit++; }
    return {total: days.length, best, streak: habitStreak(h), rate: sched ? Math.round(100 * hit / sched) : 0};
  }
  for (let i = 0; i < 30; i++) { const d = addDays(today(), -i); if (d < h.created_at.slice(0, 10)) break; if (habitScheduled(h, d)) { sched++; if ((h.logs[d] || 0) >= h.goal) hit++; } }
  return {total: days.length, best, streak: habitStreak(h), rate: sched ? Math.round(100 * hit / sched) : 0};
}
function viewHabits() {
  const hs = S.habits.filter(h => !h.archived);
  if (!S.habits.length) return `<div class="empty">${ic('habit')}${tr('No habits yet.')}<br><br><button class="btn pri" data-act="habit-new">${ic('plus', 's')} ${tr('Create habit')}</button></div>`;
  const mon = mondayOf(today()), t0 = today();
  // U10: the last 7 days up to today (yesterday can always be ticked, also on a Monday)
  const days = [...Array(7)].map((_, i) => addDays(t0, i - 6));
  let h = `<div class="hweek head"><span class="hnh"></span>${days.map(d => `<span class="${d === t0 ? 'today' : ''}" aria-label="${esc(dayLabel(d, true))}">${WD[pd(d).getDay()]}<br>${pd(d).getDate()}</span>`).join('')}<span style="text-align:right">${tr('Streak')}</span></div>`;
  for (const x of hs) {
    const col = cssColor(x.color) || HCOLORS[0];
    h += `<div class="hweek" style="--hc:${col}"><div class="hname" data-act="habit-open" data-id="${x.id}"><span class="sw" style="background:${col}"></span><div style="min-width:0"><b>${esc(x.name)}</b><small>${x.per_week ? tr('{0}/{1} this week', weekDone(x, mon), x.per_week) : x.goal > 1 ? tr('{0}/{1} today', x.logs[t0] || 0, x.goal) : habitScheduled(x, t0) ? ((x.logs[t0] || 0) >= 1 ? tr('done today') : tr('open today')) : tr('day off today')}</small></div></div>
      ${days.map(d => {
        const c = x.logs[d] || 0, sch = habitScheduled(x, d);
        const cls = [d > t0 ? 'future' : '', !sch ? 'off' : '', c >= x.goal ? 'full' : c ? 'part' : '', d === t0 ? 'today' : ''].join(' ');
        const note = (x.notes || {})[d];
        return `<button class="hc ${cls} ${note ? 'noted' : ''}" data-act="habit-tick" data-id="${x.id}" data-day="${d}" aria-label="${esc(`${x.name}, ${dayLabel(d, true)}: ${c >= x.goal ? tr('done') : c ? `${c}/${x.goal}` : sch ? tr('open') : tr('day off')}`)}" ${note ? `title="${esc(note)}"` : ''}>${c >= x.goal ? ic('check') : c ? c : ''}</button>`;
      }).join('')}
      <div class="hstreak"><b>${habitStreak(x)}</b>${streakUnit(x)}</div></div>`;
  }
  const arch = S.habits.filter(x => x.archived);
  h += `<button class="iconbtn hnew" data-act="habit-new" style="margin:.5rem 0 0 -.25rem">${ic('plus', 's')} ${tr('New habit')}</button>`;  // U26: a labelled button, like "+ Section"
  if (arch.length) h += `<div class="ghead" style="margin-top:1rem">${tr('Archived')}</div>` + arch.map(x => `<div class="srow" data-act="habit-open" data-id="${x.id}"><span class="sw" style="background:${cssColor(x.color) || HCOLORS[0]}"></span><span class="n muted">${esc(x.name)}</span></div>`).join('');
  return h;
}
function habitModal(id) {
  const x = id ? S.habits.find(h => h.id === id) : {name: '', goal: 1, days: '1234567', per_week: 0, color: HCOLORS[1], remind_at: '', logs: {}, notes: {}, created_at: new Date().toISOString()};
  x.notes = x.notes || {};
  let selDay = null, noteTimer;
  const st = id ? habitStats(x) : null;
  let month = S.habitMonth || today().slice(0, 7);
  const heat = () => {
    const [y, m] = month.split('-').map(Number);
    const first = ds(new Date(y, m - 1, 1)), lead = (pd(first).getDay() - weekStart() + 7) % 7;
    const n = new Date(y, m, 0).getDate();
    let g = wdOrder().map(i => `<div class="wd">${WD[i]}</div>`).join('') + '<div class="d blank"></div>'.repeat(lead);
    for (let i = 1; i <= n; i++) {
      const d = `${month}-${pad(i)}`, c = x.logs[d] || 0;
      g += `<div class="d ${c >= x.goal ? 'full' : c ? 'part' : ''} ${d === today() ? 'today' : ''} ${x.notes[d] ? 'noted' : ''} ${d === selDay ? 'selday' : ''} ${d > today() ? 'fut' : ''}" data-hday="${d}">${i}</div>`;
    }
    const c = selDay ? (x.logs[selDay] || 0) : 0;
    const panel = selDay ? `<div class="hday"><div class="hdh"><b>${dayLabel(selDay, true)}</b><span class="muted">${fmtDate(selDay)}</span><span class="spacer"></span>
      ${x.goal > 1 ? `<button class="iconbtn" data-hcnt="-1">−</button><span class="mono">${c}/${x.goal}</span><button class="iconbtn" data-hcnt="1">+</button>` : `<button class="btn sm ${c >= 1 ? 'pri' : ''}" data-hcnt="toggle">${c >= 1 ? ic('check', 's') + ' ' + tr('done') : tr('not done')}</button>`}</div>
      <textarea id="h-note" rows="2" placeholder="${tr('Note for this day')}">${esc(x.notes[selDay] || '')}</textarea></div>` : hintSeen('hday') ? '' : `<div class="muted hdhint">${tr('Tap a day: check it off or write a note')}</div>`;
    return `<div class="mcal"><div class="mh"><button class="iconbtn" data-hm="-1">${ic('left')}</button>${MON[m - 1]} ${y}<button class="iconbtn" data-hm="1">${ic('right')}</button></div></div><div class="heat" style="--hc:${cssColor(x.color) || HCOLORS[0]}">${g}</div>${panel}`;
  };
  const md = modal(`<h3>${id ? esc(x.name) : tr('New habit')}</h3>
    ${st ? `<div class="hstats"><div><b>${st.streak}</b><span>${tr('current streak')}</span></div><div><b>${st.best}</b><span>${tr('best streak')}</span></div><div><b>${st.total}</b><span>${tr('days total')}</span></div><div><b>${st.rate}%</b><span>${tr('last 30 days')}</span></div></div><div id="heatwrap">${heat()}</div><h4>${tr('Settings')}</h4>` : ''}
    <div class="row"><label for="h-name">${tr('Name')}</label><input id="h-name" value="${esc(x.name)}" placeholder="${tr('e.g. reading, workout, water')}"></div>
    <div class="row"><label for="h-goal">${tr('Goal per day')}</label><input id="h-goal" type="number" min="1" max="50" value="${esc(x.goal)}"></div>
    <div class="row"><label>${tr('Frequency')}</label><div class="seg" id="h-freq"><button data-freq="days" class="${x.per_week ? '' : 'on'}">${tr('Fixed days')}</button><button data-freq="week" class="${x.per_week ? 'on' : ''}">${tr('X times a week')}</button></div></div>
    <div class="row ${x.per_week ? 'hidden' : ''}" id="h-daysrow"><label>${tr('days|label')}</label><div class="wdays" id="h-days">${WD_MO().map((w, i) => `<button class="${x.days.includes(String(i + 1)) ? 'on' : ''}" data-wd="${i + 1}">${w}</button>`).join('')}</div></div>
    <div class="row ${x.per_week ? '' : 'hidden'}" id="h-pwrow"><label for="h-pw">${tr('Times per week')}</label><input id="h-pw" type="number" min="1" max="7" value="${esc(x.per_week || 3)}" style="max-width:5.625rem"><span class="muted" style="font-size:var(--fs-s)">${tr('on any days')}</span></div>
    <div class="row"><label for="h-rem">${tr('Reminder')}</label>${timeIn('h-rem', x.remind_at, {label: tr('Reminder'), empty: tr('off')})}</div>
    <div class="row"><label>${tr('Color')}</label><div class="colors" id="h-col" role="group" aria-label="${esc(tr('Color'))}">${HCOLORS.map((c, i) => `<button type="button" style="background:${c}" class="${(cssColor(x.color) || HCOLORS[0]) === c ? 'on' : ''}" aria-pressed="${(cssColor(x.color) || HCOLORS[0]) === c}" aria-label="${esc(tr('Color {0}', i + 1))}" data-c="${c}"></button>`).join('')}</div></div>
    <div class="foot">${id ? `<button class="btn danger" data-m="del">${tr('Delete')}</button><button class="btn" data-m="arch">${x.archived ? tr('Reactivate') : tr('Archive')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('button,[data-hday]'); if (!b) return;
    if (b.dataset.wd) b.classList.toggle('on');
    if (b.dataset.c) { $$('#h-col button', md).forEach(x => { x.classList.toggle('on', x === b); x.setAttribute('aria-pressed', String(x === b)); }); }
    if (b.dataset.hm) { const [y, m] = month.split('-').map(Number); const d = new Date(y, m - 1 + +b.dataset.hm, 1); month = ds(d).slice(0, 7); S.habitMonth = month; $('#heatwrap', md).innerHTML = heat(); }
    if (b.dataset.freq) {
      $$('#h-freq button', md).forEach(y => y.classList.toggle('on', y === b));
      $('#h-daysrow', md).classList.toggle('hidden', b.dataset.freq === 'week');
      $('#h-pwrow', md).classList.toggle('hidden', b.dataset.freq !== 'week');
      return;
    }
    if (b.dataset.hday) {  // select the day: tick / note panel below the month
      hintDone('hday');
      if (b.dataset.hday > today()) return;
      selDay = selDay === b.dataset.hday ? null : b.dataset.hday;
      $('#heatwrap', md).innerHTML = heat();
      return;
    }
    if (b.dataset.hcnt && selDay) {
      const c = x.logs[selDay] || 0;
      const n = b.dataset.hcnt === 'toggle' ? (c >= 1 ? 0 : x.goal) : Math.max(0, Math.min(x.goal, c + +b.dataset.hcnt));
      if (n) x.logs[selDay] = n; else delete x.logs[selDay];
      $('#heatwrap', md).innerHTML = heat(); render();
      await api('POST', `/api/habits/${x.id}/log`, {day: selDay, count: n});
      return;
    }
    const act = b.dataset.m;
    if (act === 'close') md.remove();
    if (act === 'save') {
      const days = $$('#h-days button.on', md).map(b => b.dataset.wd).join('') || '1234567';
      const perWeek = $('#h-freq button.on', md)?.dataset.freq === 'week' ? Math.max(1, Math.min(7, +$('#h-pw', md).value || 1)) : 0;
      const body = {name: $('#h-name', md).value.trim(), goal: Math.max(1, +$('#h-goal', md).value || 1), days, per_week: perWeek, remind_at: $('#h-rem', md).value, color: $('#h-col button.on', md)?.dataset.c || HCOLORS[0]};
      if (!body.name) return $('#h-name', md).focus();
      if (id) await api('PATCH', '/api/habits/' + id, body); else await api('POST', '/api/habits', body);
      md.remove(); await load(); render();
    }
    if (act === 'arch') { await api('PATCH', '/api/habits/' + id, {archived: x.archived ? 0 : 1}); md.remove(); await load(); render(); }
    if (act === 'del' && await askConfirm(tr('Delete “{0}” including its history?', x.name), tr('Every tick and note of this habit is deleted. Archive it instead to keep the history.'), {ok: tr('Delete'), danger: true})) { await api('DELETE', '/api/habits/' + id); md.remove(); await load(); render(); }
  });
  md.addEventListener('input', e => {
    if (e.target.id !== 'h-note' || !selDay || !id) return;
    const day = selDay, v = e.target.value;
    if (v.trim()) x.notes[day] = v.trim(); else delete x.notes[day];
    clearTimeout(noteTimer);
    noteTimer = setTimeout(async () => { await api('POST', `/api/habits/${x.id}/log`, {day, note: v}); render(); }, 600);
  });
  if (!isTouch() && (!id))  setTimeout(() => $('#h-name', md).focus(), 50);
}

// ------------------------------------------------------------------ pomodoro
let pomoKind = LS.get('pomoKind', 'focus'), pomoTask = LS.get('pomoTask', ''), pomoCount = 0, pomoStatsCache = null;
const fmtMS = s => { s = Math.max(0, Math.round(s)); return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`; };
function pomoElapsed(p) {
  const end = p.end ? new Date(p.end) : p.paused_at ? new Date(p.paused_at) : new Date();
  return Math.max(0, (end - new Date(p.start)) / 1000 - p.paused_s);
}
const pomoRemaining = () => S.pomo ? S.pomo.minutes * 60 - pomoElapsed(S.pomo) : pomoMinutes(pomoKind) * 60;
const fmtT = s => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600); return h ? `${h}:${pad(Math.floor(s % 3600 / 60))}:${pad(s % 60)}` : fmtMS(s); };
const isSW = () => S.pomo ? S.pomo.kind === 'stopwatch' : pomoKind === 'stopwatch';
const pomoDisplay = () => S.pomo?.kind === 'stopwatch' ? fmtT(pomoElapsed(S.pomo)) : fmtMS(pomoRemaining());
const pomoMinutes = k => +(S.settings['pomo_' + ({focus: 'focus', short: 'short', long: 'long'}[k])] || 25);
function viewPomo() {
  const p = S.pomo, kind = p ? (p.kind === 'focus' || p.kind === 'stopwatch' ? p.kind : pomoKind) : pomoKind;
  const sw = kind === 'stopwatch', el = p ? pomoElapsed(p) : 0;
  const total = sw ? 3600 : p ? p.minutes * 60 : pomoMinutes(kind) * 60;
  const rem = sw ? total - (el % 3600) : pomoRemaining();
  const C = 2 * Math.PI * 46;
  const opts = sortTasks(openTasks().filter(t => !t.parent_id)).map(t => `<option value="${t.id}" ${String(p ? p.task_id : pomoTask) === String(t.id) ? 'selected' : ''}>${esc(t.title)}</option>`).join('');
  const tt = p && p.task_id && S.tasks.get(p.task_id);
  return `<div class="pomo">
    <div class="seg">${[['focus', N_('Focus')], ['short', N_('Short break')], ['long', N_('Long break')], ['stopwatch', N_('Stopwatch')]].map(([k, n]) => `<button class="${kind === k ? 'on' : ''}" data-act="pomo-kind" data-k="${k}" ${p ? 'disabled' : ''}>${tr(n)}</button>`).join('')}</div>
    <div class="ring"><svg viewBox="0 0 100 100"><circle class="bgc" cx="50" cy="50" r="46"/><circle class="fgc" id="pring" cx="50" cy="50" r="46" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - rem / total)}"/></svg>
      <div class="t"><b id="ptime">${sw ? fmtT(el) : fmtMS(rem)}</b><span>${p ? (p.paused_at ? tr('paused') : tt ? esc(tt.title) : p.kind === 'focus' ? tr('Focus') : sw ? tr('stopwatch running') : tr('Break')) : sw ? tr('Stopwatch') : kind === 'focus' ? tr('ready') : tr('Break')}</span></div></div>
    <div class="ctrls">${!p ? `<button class="btn pri" data-act="pomo-start" aria-label="${sw ? tr('Start stopwatch') : kind === 'focus' ? tr('Start focus session') : tr('Start break')}">${ic('play', 's')} ${sw ? tr('Start stopwatch') : kind === 'focus' ? tr('Start focus session') : tr('Start break')}</button>`
      : `${p.paused_at ? `<button class="btn pri" data-act="pomo-resume">${ic('play', 's')} ${tr('Resume')}</button>` : `<button class="btn" data-act="pomo-pause">${ic('pause', 's')} ${tr('Pause')}</button>`}<button class="btn" data-act="pomo-stop">${ic('stop', 's')} ${tr('Stop')}</button>`}</div>
    ${kind === 'focus' || sw ? `<select id="pomo-task" aria-label="${esc(tr('Task'))}" ${p ? 'disabled' : ''}><option value="">${tr('No task')}</option>${opts}</select>` : ''}
    <div id="pstats">${pomoStatsCache ? pomoStatsHtml(pomoStatsCache) : ''}</div>
  </div>`;
}
function pomoStatsHtml(j) {
  const days = [...Array(7)].map((_, i) => addDays(today(), i - 6));
  const max = Math.max(1, ...days.map(d => j.per_day[d] || 0));
  return `<div class="pstats"><div><b>${j.today.count}</b><span>${tr('Pomos today')}</span></div><div><b>${fmtH(j.today.minutes)}</b><span>${tr('Focus time today')}</span></div><div><b>${j.week.count}</b><span>${tr('Pomos 7 days')}</span></div><div><b>${fmtH(j.week.minutes)}</b><span>${tr('Focus 7 days')}</span></div></div>
    <div class="bars">${days.map(d => `<div><i style="height:${Math.round(100 * (j.per_day[d] || 0) / max)}%" title="${j.per_day[d] || 0} min"></i><span>${WD[pd(d).getDay()]}</span></div>`).join('')}</div>
    ${j.per_task.length ? `<div class="ptasks"><div class="muted" style="border:0;font-size:var(--fs-s)">${tr('Focus by task (30 days)')}</div>${j.per_task.map(([n, m]) => `<div><span>${esc(n)}</span><span class="muted">${fmtH(m)}</span></div>`).join('')}</div>` : ''}`;
}
const fmtH = m => m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
async function loadPomoStats() { try { pomoStatsCache = await api('GET', '/api/pomo/stats'); const el = $('#pstats'); if (el) el.innerHTML = pomoStatsHtml(pomoStatsCache); } catch { /* ignore */ } }
let finishing = false;
setInterval(async () => {
  if (!S.pomo) return;
  const C = 2 * Math.PI * 46;
  if (S.pomo.kind === 'stopwatch') {  // counts up, no end
    const el = pomoElapsed(S.pomo);
    const t = $('#ptime'); if (t) t.textContent = fmtT(el);
    const r = $('#pring'); if (r) r.setAttribute('stroke-dashoffset', C * ((el % 3600) / 3600));
    $$('[data-pomo-mini]').forEach(x => { x.textContent = fmtT(el); });
    document.title = S.pomo.paused_at ? APP_NAME : `${fmtT(el)} · ${APP_NAME}`;
    return;
  }
  const rem = pomoRemaining();
  const t = $('#ptime'); if (t) t.textContent = fmtMS(rem);
  const r = $('#pring'); if (r) r.setAttribute('stroke-dashoffset', C * (1 - rem / (S.pomo.minutes * 60)));
  $$('[data-pomo-mini]').forEach(x => { x.textContent = fmtMS(Math.max(0, rem)); });
  document.title = S.pomo.paused_at ? APP_NAME : `${fmtMS(rem)} · ${APP_NAME}`;
  if (rem <= 0 && !S.pomo.paused_at && !finishing) {
    finishing = true;
    const wasFocus = S.pomo.kind === 'focus';
    try {
      const j = await api('POST', `/api/pomo/${S.pomo.id}/finish`);
      S.pomo = j.pomo; S.pomoToday = j.today;
      beep();
      if (wasFocus) { pomoCount++; pomoKind = pomoCount % (+S.settings.pomo_long_every || 4) === 0 ? 'long' : 'short'; }
      else pomoKind = 'focus';
      LS.set('pomoKind', pomoKind);
      document.title = APP_NAME;
      toast(wasFocus ? tr('Focus done. Time for a break.') : tr('Break is over.'));
      if ('Notification' in window && Notification.permission === 'granted' && document.hidden) new Notification(wasFocus ? tr('Focus done') : tr('Break is over'));
      render();
    } finally { finishing = false; }
  }
}, 1000);
function beep() {
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    [0, .25, .5].forEach(off => { const o = ac.createOscillator(), g = ac.createGain(); o.frequency.value = 880; g.gain.setValueAtTime(.2, ac.currentTime + off); g.gain.exponentialRampToValueAtTime(.001, ac.currentTime + off + .2); o.connect(g); g.connect(ac.destination); o.start(ac.currentTime + off); o.stop(ac.currentTime + off + .2); });
  } catch { /* no audio */ }
}
async function pomoStart(taskId) {
  const kind = taskId ? (pomoKind === 'stopwatch' ? 'stopwatch' : 'focus') : pomoKind;
  const tid = taskId || (kind === 'focus' || kind === 'stopwatch' ? ($('#pomo-task')?.value || '') : '');
  if (kind === 'focus' || kind === 'stopwatch') { pomoTask = tid; LS.set('pomoTask', tid); }
  S.pomo = await api('POST', '/api/pomo/start', {kind: kind === 'focus' || kind === 'stopwatch' ? kind : 'break', minutes: kind === 'stopwatch' ? 0 : pomoMinutes(kind), task_id: tid ? +tid : null});
  if (tid && tFor(taskById(tid)) && S.timer && (kind === 'focus' || kind === 'stopwatch')) setTimeout(() => toast(tr('A timer is running: this session is not tracked a second time')), 60);
  if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission();
  render(); if (S.sel) renderDetail();
}
