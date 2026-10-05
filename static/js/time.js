/* Kalmido web client: Time tracking (module "time").
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ time tracking (module "time")
// Timer (one per user, kept on the server, so it follows you across devices), manual entries, reports,
// CSV export and a printable timesheet. The rules (who sees which entries, focus vs. timer, days, rounding)
// are documented at the top of kalmido/personal/timetrack.py. Start / stop carry the device time and a client
// id, so they can wait in the offline outbox and still land at the right time.
const timeOn = () => feat('time') && S.timeAll !== false;  // own switch + the admin's switch for the whole server
const hmm = s => { s = Math.max(0, Math.round(s)); return `${Math.floor(s / 3600)}:${pad(Math.floor(s % 3600 / 60))}`; };
const fmtDur = s => fmtH(Math.floor(Math.max(0, s) / 60));
const fmtClock = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
const hoursDec = s => (s / 3600).toLocaleString(LOCALE(), {minimumFractionDigits: 2, maximumFractionDigits: 2});
const money = (v, cur) => v.toLocaleString(LOCALE(), {minimumFractionDigits: 2, maximumFractionDigits: 2}) + (cur ? ' ' + cur : '');
const timerElapsed = () => S.timer ? Math.max(0, (Date.now() - new Date(S.timer.start)) / 1000) : 0;
const newCid = () => (window.crypto?.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
function taskTime(id) {  // [everyone I can see, mine] in seconds, incl. my running timer
  const [a, m] = (S.timeTotals || {})[id] || [0, 0], run = S.timer && S.timer.task_id === id ? timerElapsed() : 0;
  return [a + run, m + run];
}
function addLocalTotal(tid, sec) {  // offline: keep the task chips right until the next sync
  if (!tid || !(sec > 0)) return;
  const [a, m] = (S.timeTotals ||= {})[tid] || [0, 0];
  S.timeTotals[tid] = [a + sec, m + sec];
}
function timeLocal(e) {  // applyLocal part of the outbox (start / stop / entries)
  const {url, body = {}} = e;
  if (url === '/api/time/start') {
    if (S.timer) addLocalTotal(S.timer.task_id, (new Date(body.at) - new Date(S.timer.start)) / 1000);
    const t = body.task_id ? S.tasks.get(body.task_id) : null;
    S.timer = {id: null, client_id: body.client_id, task_id: body.task_id || null, list_id: t ? t.list_id : body.list_id || null, title: t ? t.title : '',
      start: body.at, end: null, note: body.note || '', running: true, mine: true, source: 'timer', seconds: 0};
    return {entry: S.timer, timer: S.timer, stopped: null, queued: true};
  }
  if (url === '/api/time/stop') {
    if (S.timer && (!body.client_id || body.client_id === S.timer.client_id)) { addLocalTotal(S.timer.task_id, (new Date(body.at) - new Date(S.timer.start)) / 1000); S.timer = null; }
    return {entry: null, timer: null, queued: true};
  }
  return {ok: true, queued: true};
}
async function timeChanged(j) {
  if (!j || !j.queued) await load().catch(() => {});
  render();
  if (S.sel) { renderDetail(); loadTaskTime(S.sel); }
}
async function timerStart(target, note = '') {
  let j;
  try { j = await api('POST', '/api/time/start', {...target, note, at: new Date().toISOString(), client_id: newCid()}); } catch { return; }
  if (j.timer !== undefined) S.timer = j.timer;
  if (j.stopped) toast(tr('Previous timer stopped ({0})', hmm(j.stopped.seconds)));
  else if (j.queued) toast(tr('Timer started, will be sent as soon as the server is reachable'));
  await timeChanged(j);
}
async function timerStop() {
  const r = S.timer; if (!r) return;
  let j;
  try { j = await api('POST', '/api/time/stop', {...(r.id ? {id: r.id} : {}), ...(r.client_id ? {client_id: r.client_id} : {}), at: new Date().toISOString()}); } catch { return; }
  S.timer = j.timer ?? null;
  toast(j.discarded ? tr('Timer discarded (shorter than a second)') : tr('Timer stopped: {0}', hmm(j.entry ? j.entry.seconds : timerElapsed())));
  await timeChanged(j);
}
const timerToggle = tid => S.timer && S.timer.task_id === tid ? timerStop() : timerStart({task_id: tid});
// 1.2: one running indicator for everything that runs: the time-tracking timer, a focus session / break, the
// stopwatch. Its own icon per kind, the time, the task; a click opens a popover with the task and Pause / Stop.
// Top bar on every view (also on the phone), and in the Settings header.
const RUN_KIND = {time: ['clock', N_('Time tracking')], focus: ['timer', N_('Focus session')], break: ['sun', N_('Break')], stopwatch: ['stopwatch', N_('Stopwatch')]};
function runItems() {
  const out = [];
  if (S.timer && timeOn()) out.push({k: 'time', tid: S.timer.task_id, title: S.timer.title || tr('No task'), txt: fmtT(timerElapsed()), attr: 'data-timer-mini'});
  if (S.pomo && feat('pomo')) {  // module off: the session is not shown (the server ends it at its planned end)
    const k = S.pomo.kind === 'stopwatch' ? 'stopwatch' : S.pomo.kind === 'focus' ? 'focus' : 'break', tt = S.pomo.task_id && taskById(S.pomo.task_id);
    out.push({k, tid: S.pomo.task_id, title: tt ? tt.title : k === 'break' ? tr('Break') : tr('No task'), txt: pomoDisplay(), attr: 'data-pomo-mini', paused: !!S.pomo.paused_at});
  }
  return out;
}
function timerPill() {
  const it = runItems();
  if (!it.length) return '';
  if (it.length === 1) {
    const x = it[0], [icn, name] = RUN_KIND[x.k];
    return `<button class="tmini run k-${x.k} ${x.paused ? 'paused' : ''}" data-act="run-pop" title="${esc(`${tr(name)}: ${x.title}`)}" aria-label="${esc(`${tr(name)} · ${x.title}`)}">${x.k === 'time' ? '<span class="rec"></span>' : ''}${ic(icn, 's rk')}<span ${x.attr}>${x.txt}</span><span class="tmt">${esc(x.title)}</span></button>`;
  }
  return `<button class="tmini run multi" data-act="run-pop" title="${esc(it.map(x => `${tr(RUN_KIND[x.k][1])}: ${x.title}`).join(' · '))}" aria-label="${esc(trn('{0} running', '{0} running', it.length))}"><span class="rec"></span>${it.map(x => ic(RUN_KIND[x.k][0], 's rk')).join('')}<span class="tmt">${esc(trn('{0} running', '{0} running', it.length))}</span></button>`;
}
function runPop(a) {
  const it = runItems(); if (!it.length) return;
  const row = x => {
    const [icn, name] = RUN_KIND[x.k], t = x.tid && taskById(x.tid);
    const acts = x.k === 'time' ? `<button data-run="time-stop">${ic('stop', 's')}${tr('Stop timer')}</button>`
      : `${x.paused ? `<button data-run="pomo-resume">${ic('play', 's')}${tr('Resume')}</button>` : `<button data-run="pomo-pause">${ic('pause', 's')}${tr('Pause')}</button>`}<button data-run="pomo-stop">${ic('stop', 's')}${x.k === 'stopwatch' ? tr('Stop stopwatch') : x.k === 'focus' ? tr('Stop focus session') : tr('End break')}</button>`;
    return `<div class="runrow k-${x.k}"><div class="runh">${ic(icn, 's rk')}<b>${tr(name)}</b><span class="runt" ${x.attr}>${x.txt}</span>${x.paused ? `<span class="muted">${tr('paused')}</span>` : ''}</div>
      ${t ? `<button class="runtask" data-run="open" data-id="${t.id}">${ic('arrow', 's')}<span>${esc(t.title)}</span></button>` : `<div class="muted runtask">${esc(x.title)}</div>`}
      ${acts}${x.k === 'time' ? `<button data-run="time-page">${ic('clock', 's')}${tr('Time tracking')}</button>` : `<button data-run="pomo-page">${ic('timer', 's')}${tr('Focus')}</button>`}</div>`;
  };
  const p = openPop(a, `<div class="menu-list runlist">${it.map(row).join('<hr>')}</div>`);
  p.onclick = async e => {
    const b = e.target.closest('[data-run]'); if (!b) return;
    const r = b.dataset.run; closePop();
    if (r === 'time-stop') timerStop();
    else if (r === 'time-page') go('time');
    else if (r === 'pomo-page') go('pomo');
    else if (r === 'open') openTaskById(+b.dataset.id);
    else if (S.pomo) {
      const swStop = r === 'pomo-stop' && S.pomo.kind === 'stopwatch' ? Math.round(pomoElapsed(S.pomo) / 60) : null;
      try { const j = await api('POST', `/api/pomo/${S.pomo.id}/${r.slice(5)}`); S.pomo = j.pomo; S.pomoToday = j.today; } catch { return; }
      if (swStop !== null) setTimeout(() => toast(tr('Stopped: {0} logged', fmtH(swStop))), 50);
      document.title = APP_NAME; render(); if (S.sel) renderDetail();
    }
  };
}
function timerMenu(a) {
  const t = S.timer; if (!t) return;
  menu(a, [{label: tr('Stop timer'), icon: 'stop', fn: timerStop},
    ...(t.task_id && taskById(t.task_id) ? [{label: tr('Open task'), icon: 'edit', fn: () => openDetail(t.task_id)}] : []),
    ...(t.id ? [{label: tr('Change start time or note…'), icon: 'clock', fn: () => entryModal(t)}] : []),
    {label: tr('Time tracking'), icon: 'clock', fn: () => go('time')}]);
}
setInterval(() => {  // live timer: top pill, detail panel, the running task's chip
  if (!S.timer) return;
  const el = timerElapsed();
  $$('[data-timer-mini],[data-timer-live]').forEach(x => { x.textContent = fmtT(el); });
  $$(`[data-tt="${S.timer.task_id}"] b`).forEach(x => { x.textContent = fmtDur(taskTime(S.timer.task_id)[0]); });
}, 1000);

// ---- entries of the open task (detail panel)
S.te = {tid: null, items: null, v: -1, all: false, err: null};
async function loadTaskTime(id) {
  if (!tFor(taskById(id)) || !(id > 0) || taskById(id)?.context) return;
  const v = S.v;
  if (S.te.tid !== id) S.te = {tid: id, items: null, v: -1, all: false, err: null};
  try { const j = await rawFetch('GET', `/api/time/entries?task_id=${id}`); if (S.te.tid === id) Object.assign(S.te, {items: j.entries, v, err: null}); }
  catch (e) { if (S.te.tid === id) Object.assign(S.te, {v, err: e instanceof Offline ? 'offline' : e.message}); }
  drawTaskTime();
}
function drawTaskTime() { const el = $('#d-time'), t = taskById(S.sel); if (el && t && S.te.tid === t.id) el.innerHTML = taskTimeHtml(t); }
function taskTimeHtml(t) {
  const [all, mine] = taskTime(t.id), run = S.timer && S.timer.task_id === t.id;
  const items = S.te.tid === t.id ? S.te.items : null;
  let h = `<h5>${tr('Time|tracked')}${all >= 60 ? ` <span class="muted h5note">${all - mine >= 60 ? tr('{0} in total, {1} by you', fmtDur(all), fmtDur(mine)) : fmtDur(all)}</span>` : ''}</h5>
    <div class="tebtns"><button class="btn sm ${run ? 'recon' : ''}" data-act="timer-toggle" data-id="${t.id}">${run ? `${ic('stop', 's')} ${tr('Stop')} <span data-timer-live>${fmtT(timerElapsed())}</span>` : `${ic('play', 's')} ${tr('Start timer')}`}</button><button class="btn sm" data-act="te-add" data-id="${t.id}">${ic('plus', 's')} ${tr('Add time')}</button></div>`;
  if (items === null) return h + (S.te.err === 'offline' ? `<div class="muted mhint">${tr('Time entries are only available online.')}</div>` : '');
  const shown = S.te.all ? items : items.slice(0, 8);
  return h + `<div class="telist">${shown.map(e => teRow(e, {task: false})).join('')}</div>` +
    (items.length > shown.length ? `<button class="btn sm telink" data-act="te-more">${tr('Show all ({0})', items.length)}</button>` : '');
}
function teRow(e, {task = true, day = true} = {}) {
  const s = new Date(e.start), en = e.end ? new Date(e.end) : null;
  const src = e.source === 'focus' ? `<span class="tesrc" title="${tr('From a focus session')}">${ic('timer', 's')}</span>`
    : e.auto_stopped ? `<span class="tesrc warn" title="${tr('Stopped automatically, please check the end')}">${ic('alert', 's')}</span>` : '';
  const who = e.mine ? '' : avBtn(e.user_id, e.user_name, 'who', `title="${esc(e.user_name)}"`);
  const title = task ? `<span class="tett" ${e.task_id ? `data-act="te-open" data-id="${e.task_id}"` : ''}>${esc(e.title || tr('No task'))}</span>` : '';
  const acts = e.mine ? `<span class="teacts">${!e.running && (e.task_id || e.list_id) ? `<button class="iconbtn" data-act="te-resume" data-eid="${e.id}" title="${tr('Continue (same task and note)')}">${ic('play', 's')}</button>` : ''}<button class="iconbtn" data-act="te-edit" data-eid="${e.id}" title="${tr('Edit')}">${ic('edit', 's')}</button><button class="iconbtn danger" data-act="te-del" data-eid="${e.id}" title="${tr('Delete')}">${ic('trash', 's')}</button></span>` : '';
  return `<div class="terow ${e.running ? 'live' : ''}">${day ? `<span class="ted">${esc(dayLabel(ds(s)))}</span>` : ''}<span class="tet">${fmtClock(s)}–${en ? fmtClock(en) : tr('now')}</span>${title}<span class="ten">${esc(e.note)}</span>${src}${who}<b class="tedur" ${e.running ? 'data-timer-live' : ''}>${e.running ? fmtT(timerElapsed()) : hmm(e.seconds)}</b>${acts}</div>`;
}
const findEntry = id => [...(S.te.items || []), ...(S.tv.data?.entries || []), ...(S.timer ? [S.timer] : [])].find(e => e.id === id);
// "1:30" = 90 min, "45m" = 45 min, "1.5" / "1,5h" = 90 min (a bare number means hours)
function parseDur(v) {
  v = String(v || '').trim().toLowerCase(); if (!v) return null;
  let m;
  if ((m = v.match(/^(\d+):(\d{1,2})$/))) return +m[1] * 60 + +m[2];
  if ((m = v.match(/^(\d+)\s*m(in)?$/))) return +m[1];
  const f = parseFloat(v.replace(',', '.').replace(/\s*h$/, ''));
  return isNaN(f) || f <= 0 ? null : Math.round(f * 60);
}
function targetOptions(tid, lid) {
  const lists = S.lists.filter(l => (l.kind === 'project' || l.id === lid) && (!l.archived || l.id === lid || (tid && taskById(tid)?.list_id === l.id)));
  const cur = tid && taskById(tid);
  return lists.map(l => {
    const ts = sortTasks(openTasks().filter(t => t.list_id === l.id && !t.parent_id));
    if (cur && cur.list_id === l.id && !ts.includes(cur)) ts.unshift(cur);
    const sub = x => [x, ...children(x.id).filter(k => k.status === 0 || k.id === tid).flatMap(sub)];
    return `<optgroup label="${esc(lname(l))}"><option value="l:${l.id}" ${!tid && lid === l.id ? 'selected' : ''}>${esc(tr('(whole list, no task)'))}</option>${ts.flatMap(sub).map(t => `<option value="t:${t.id}" ${t.id === tid ? 'selected' : ''}>${' '.repeat(depthOf(t))}${esc(t.title)}</option>`).join('')}</optgroup>`;
  }).join('');
}
// new entry (e = null; preset {task_id} | {list_id}) or edit my entry (a running timer: start time, note, task)
function entryModal(e, preset = {}) {
  const run = !!(e && e.running), s = e ? new Date(e.start) : null, en = e && e.end ? new Date(e.end) : null;
  const tid = e ? e.task_id : preset.task_id || null, lid = e ? e.list_id : preset.list_id || (tid ? taskById(tid)?.list_id : null) || (isProject(routeList()?.id) ? routeList().id : null) || S.lists.find(l => l.kind === 'project' && !l.archived)?.id;
  const md = modal(`<h3>${run ? tr('Running timer') : e ? tr('Edit time entry') : tr('Add time')}</h3>
    <div class="row"><label for="te-target">${tr('Task')}</label><select id="te-target">${targetOptions(tid, lid)}</select></div>
    <div class="row"><label>${tr('Date')}</label>${dateIn('te-date', ds(s || new Date()), {max: today(), label: tr('Date'), clear: false})}</div>
    <div class="row"><label>${run ? tr('Started at') : tr('From – to')}</label>${timeIn('te-from', s ? fmtClock(s) : '', {label: run ? tr('Started at') : tr('From'), empty: '–'})}${run ? '' : `<span class="muted">–</span>${timeIn('te-to', en ? fmtClock(en) : '', {label: tr('To'), empty: '–'})}`}</div>
    ${run ? '' : `<div class="row"><label for="te-dur">${tr('or duration')}</label><input id="te-dur" placeholder="${tr('e.g. 1:30, 45m or 1.5')}" inputmode="decimal" autocomplete="off"></div>`}
    <div class="row"><label for="te-note">${tr('Note')}</label><input id="te-note" value="${esc(e?.note || '')}" maxlength="500" autocomplete="off"></div>
    ${run ? '' : `<div class="shint">${tr('An end before the start means the next day. Only a duration: the entry ends now (today) or starts at 9:00.')}</div>`}
    <div class="foot">${e && !run ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  const times = () => {
    const date = $('#te-date', md).value, from = $('#te-from', md).value, to = $('#te-to', md)?.value, dur = parseDur($('#te-dur', md)?.value);
    if (!date) return null;
    let a = from ? new Date(`${date}T${from}`) : null, b = null;
    if (run) return a ? {start: a} : null;
    if (a && to && !dur) { b = new Date(`${date}T${to}`); if (b <= a) b = new Date(b.getTime() + 864e5); }
    else if (dur) {
      if (a) b = new Date(a.getTime() + dur * 6e4);
      else if (date === today()) { b = new Date(); b.setSeconds(0, 0); a = new Date(b.getTime() - dur * 6e4); }
      else { a = new Date(`${date}T09:00`); b = new Date(a.getTime() + dur * 6e4); }
    }
    return a && b ? {start: a, end: b} : null;
  };
  md.addEventListener('click', async ev => {
    const b = ev.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'del') { md.remove(); teDelete(e.id); return; }
    if (b.dataset.m !== 'save') return;
    const tm = times();
    if (!tm) { toast(run ? tr('Please enter the start time') : tr('Please enter start and end, or a duration')); return; }
    if (tm.end && tm.end - tm.start < 6e4) { toast(tr('The end is before the start')); return; }
    if (tm.start > new Date()) { toast(tr('Entries cannot lie in the future')); return; }
    const [k, v] = $('#te-target', md).value.split(':'), body = {note: $('#te-note', md).value.trim()};
    const target = k === 't' ? {task_id: +v} : {list_id: +v};
    if (!e || (k === 't' ? +v !== e.task_id : e.task_id || +v !== e.list_id)) Object.assign(body, target);
    const iso = d => d.toISOString();
    if (!e || fmtClock(tm.start) !== fmtClock(s) || ds(tm.start) !== ds(s) || (!run && (!en || fmtClock(tm.end) !== fmtClock(en) || ds(tm.end) !== ds(en)))) {
      body.start = iso(tm.start); if (!run) body.end = iso(tm.end);
    }
    let j;
    try { j = e ? await api('PATCH', `/api/time/entries/${e.id || 0}`, body) : await api('POST', '/api/time/entries', {...target, ...body}); } catch { return; }
    md.remove();
    toast(j.queued ? tr('Will be sent as soon as the server is reachable') : e ? tr('Saved') : tr('Time added: {0}', hmm(j.seconds)));
    await timeChanged(j);
  });
  md.addEventListener('keydown', ev => { if (ev.key === 'Enter' && ev.target.tagName === 'INPUT') $('[data-m="save"]', md).click(); });
  if (!isTouch()) setTimeout(() => $(e ? '#te-note' : run ? '#te-from' : '#te-dur', md)?.focus(), 50);  // 2.13.0: no keyboard popping up on touch
}
async function teDelete(id) {
  const e = findEntry(id); if (!e) return;
  let r;
  try { r = await api('DELETE', `/api/time/entries/${id}`); } catch { return; }
  if (S.timer && S.timer.id === id) S.timer = null;
  const back = {...(e.task_id ? {task_id: e.task_id} : {list_id: e.list_id}), start: e.start, end: e.end, seconds: e.seconds, note: e.note, source: e.source};
  await timeChanged(r);
  if (e.end) {
    const x = histAdd({label: tr('Time entry deleted ({0})', hmm(e.seconds)), res: r, lids: e.list_id ? [e.list_id] : [],
      undo: async h => { const j = await api('POST', '/api/time/entries', back); h.eid = j?.id; await timeChanged(j); return {q: j?._q || null}; },
      redo: async h => { if (!h.eid) return {skipped: [tr('Time entry')], none: true}; const j = await api('DELETE', `/api/time/entries/${h.eid}`); await timeChanged(j); return {q: j?._q || null}; }});
    offerUndo(tr('Time entry deleted ({0})', hmm(e.seconds)), x);
  }
  else toast(tr('Timer discarded'));
}

// ---- reports view (#time)
S.tv = {data: null, loading: false, err: null, key: '', period: LS.get('timePeriod', 'week'), from: LS.get('timeFrom', ''), to: LS.get('timeTo', ''),
  scope: LS.get('timeScope', 'mine'), lists: LS.get('timeLists', []), entries: LS.get('timeEntries', false)};
const TPERIODS = [['week', N_('This week')], ['lastweek', N_('Last week')], ['month', N_('This month')], ['lastmonth', N_('Last month')], ['custom', N_('Custom')]];
const monthEnd = s => { const d = pd(s); return ds(new Date(d.getFullYear(), d.getMonth() + 1, 0)); };
function timeRange() {
  const t = today(), mon = weekStartOf(t), m0 = t.slice(0, 8) + '01';
  switch (S.tv.period) {
    case 'lastweek': return [addDays(mon, -7), addDays(mon, -1)];
    case 'month': return [m0, monthEnd(m0)];
    case 'lastmonth': { const d = pd(m0), p = ds(new Date(d.getFullYear(), d.getMonth() - 1, 1)); return [p, monthEnd(p)]; }
    case 'custom': if (S.tv.from && S.tv.to) return S.tv.from <= S.tv.to ? [S.tv.from, S.tv.to] : [S.tv.to, S.tv.from]; return [mon, addDays(mon, 6)];
    default: return [mon, addDays(mon, 6)];
  }
}
const timeScope = () => hasSharing() && S.tv.scope === 'all' ? 'all' : 'mine';
const tvLists = () => S.tv.lists.filter(id => id === 0 || listById(id));
function timeQuery() {
  const [f, t] = timeRange(), q = new URLSearchParams({from: f, to: t, scope: timeScope()});
  if (tvLists().length) q.set('lists', tvLists().join(','));
  return q.toString();
}
async function loadTime() {
  if (S.tv.loading) return;
  S.tv.loading = true;
  const q = timeQuery(), key = q + '|' + S.v;
  try { S.tv.data = await rawFetch('GET', '/api/time/report?' + q); S.tv.data._q = q; S.tv.err = null; }
  catch (e) { if (e.message !== 'auth') S.tv.err = e instanceof Offline ? 'offline' : e.message; }
  finally { S.tv.loading = false; S.tv.key = key; }
  if (S.route.mod === 'time') renderView();
}
const tvListName = l => l.id === 0 ? tr('No list') : l.is_inbox && inboxDef(l.name) ? tr('Inbox') : l.name;
const rangeLabel = (f, t) => f === t ? fmtDate(f) : `${fmtDate(f)} – ${fmtDate(t)}`;
function tvListsLabel() {
  const ids = tvLists();
  if (!ids.length) return tr('All lists');
  return ids.length === 1 ? (ids[0] === 0 ? tr('No list') : lname(listById(ids[0]))) : trn('{0} list', '{0} lists', ids.length);
}
// 1.5.2: the running timer as a large card on top of the time page: live time, task (opens it), list, start, Stop.
// Nothing running: a short hint with the tasks you tracked time on lately (one tap starts the timer again)
// 2.0.6 (#190): a running focus session, break or stopwatch gets the same card (own icon and colour per kind, live
// time, task, Pause / Resume, Stop), next to or instead of the time-tracking one
function tvPomoCard() {
  const p = S.pomo; if (!p || !feat('pomo')) return '';
  const k = p.kind === 'stopwatch' ? 'stopwatch' : p.kind === 'focus' ? 'focus' : 'break', [icn, name] = RUN_KIND[k];
  const t = p.task_id && taskById(p.task_id), l = t && listById(t.list_id), col = l && cssColor(l.color);
  const stop = k === 'stopwatch' ? tr('Stop stopwatch') : k === 'focus' ? tr('Stop focus session') : tr('End break');
  return `<section class="tvrun tvpomo k-${k}${p.paused_at ? ' paused' : ''}" aria-label="${esc(tr(name))}">
    <div class="tvr-time">${ic(icn, 's rk')}<b data-pomo-mini>${pomoDisplay()}</b></div>
    <div class="tvr-info"><span class="tvr-kind">${tr(name)}${p.paused_at ? ` · ${tr('paused')}` : ''}</span>${t ? `<button class="tvr-task" data-act="open-id" data-id="${t.id}" title="${esc(tr('Open task'))}">${esc(t.title)}</button>` : `<span class="tvr-task muted">${esc(k === 'break' ? tr('Break') : tr('No task'))}</span>`}
      <span class="tvr-meta">${l ? `<span class="tvr-list"><span class="sw" style="${col ? 'background:' + col : ''}"></span>${esc(lname(l))}</span>` : ''}<span>${esc(tr('since {0}', fmtClock(new Date(p.start))))}</span>${k !== 'stopwatch' ? `<span>${esc(tr('{0} min planned', p.minutes))}</span>` : ''}</span></div>
    <div class="tvr-acts">${p.paused_at ? `<button class="btn pri" data-act="pomo-resume">${ic('play', 's')} ${tr('Resume')}</button>` : `<button class="btn" data-act="pomo-pause">${ic('pause', 's')} ${tr('Pause')}</button>`}<button class="btn" data-act="pomo-stop">${ic('stop', 's')} ${stop}</button><button class="btn" data-go="pomo">${ic('timer', 's')} ${tr('Focus')}</button></div>
  </section>`;
}
function tvRunCard() {
  const r = S.timer, pc = tvPomoCard();
  if (!r && pc) return pc;
  if (!r) {
    const recent = Object.entries(S.timeTotals || {}).map(([id, v]) => [taskById(+id), v[1]]).filter(([x, m]) => x && x.status === 0 && m > 0 && tFor(x)).sort((a, b) => b[1] - a[1]).slice(0, 3);
    return `<section class="tvrun idle"><span class="tvr-idle">${ic('clock', 's')}${tr('No timer running')}</span>${recent.map(([x]) => `<button class="btn sm tvr-go" data-act="timer-toggle" data-id="${x.id}" title="${esc(tr('Start timer'))}">${ic('play', 's')}<span>${esc(x.title)}</span></button>`).join('')}</section>`;
  }
  const t = r.task_id && taskById(r.task_id), l = listById(r.list_id ?? t?.list_id), col = l && cssColor(l.color);
  return `<section class="tvrun" aria-label="${esc(tr('Timer running'))}">
    <div class="tvr-time"><span class="rec"></span><b data-timer-live>${fmtT(timerElapsed())}</b></div>
    <div class="tvr-info">${t ? `<button class="tvr-task" data-act="open-id" data-id="${t.id}" title="${esc(tr('Open task'))}">${esc(t.title)}</button>` : `<span class="tvr-task muted">${esc(r.title || tr('No task'))}</span>`}
      <span class="tvr-meta">${l ? `<span class="tvr-list"><span class="sw" style="${col ? 'background:' + col : ''}"></span>${esc(lname(l))}</span>` : ''}<span>${esc(tr('since {0}', fmtClock(new Date(r.start))))}</span>${r.note ? `<span>${esc(r.note)}</span>` : ''}</span></div>
    <div class="tvr-acts"><button class="btn pri" data-act="tv-stop">${ic('stop', 's')} ${tr('Stop timer')}</button>${t ? `<button class="btn" data-act="open-id" data-id="${t.id}">${ic('arrow', 's')} ${tr('Open task')}</button>` : ''}</div>
  </section>${pc}`;
}
function viewTime() {
  const tv = S.tv, [f, t] = timeRange(), q = timeQuery();
  if (tv.key !== q + '|' + S.v && !tv.loading) setTimeout(loadTime, 0);
  const j = tv.data && tv.data._q === q ? tv.data : null;
  let h = `<div class="stats timev">${tvRunCard()}<div class="tvbar"><div class="seg tvseg">${TPERIODS.map(([k, n]) => `<button class="${tv.period === k ? 'on' : ''}" data-act="tv-period" data-k="${k}">${tr(n)}</button>`).join('')}</div>
      ${tv.period === 'custom' ? `<span class="tvrange">${dateIn('tv-from', f, {label: tr('From'), clear: false})}<span class="muted">–</span>${dateIn('tv-to', t, {label: tr('To'), clear: false})}</span>` : `<span class="muted tvlabel">${esc(rangeLabel(f, t))}</span>`}</div>
    <div class="tvbar">${hasSharing() ? `<div class="seg"><button class="${timeScope() === 'mine' ? 'on' : ''}" data-act="tv-scope" data-k="mine">${tr('Only mine')}</button><button class="${timeScope() === 'all' ? 'on' : ''}" data-act="tv-scope" data-k="all">${tr('All members')}</button></div>` : ''}
      <button class="btn sm" data-act="tv-lists">${ic('filter', 's')} ${esc(tvListsLabel())}</button><span class="spacer"></span>
      <button class="btn sm" data-act="te-add">${ic('plus', 's')} ${tr('Entry')}</button>
      <a class="btn sm" href="/api/time/export.csv?${esc(q)}" download>${ic('download', 's')} CSV</a>
      <button class="btn sm" data-act="tv-sheet" ${j ? '' : 'disabled'}>${ic('file', 's')} ${tr('Timesheet')}</button></div>`;
  if (!j) return h + `<div class="empty">${tv.err ? (tv.err === 'offline' ? tr('Reports are only available online.') : esc(tv.err)) : tr('Loading…')}</div></div>`;
  const tot = j.total, rm = j.rounding, hasAmt = j.lists.some(l => l.rate), tgt = j.today.target_h;
  // U20: one tile for the range (time and decimal hours together), "today" only when the range is longer than today
  const tiles = [[hmm(tot.seconds), tr('tracked'), [rm ? tr('rounded: {0}', `${hmm(tot.rounded)} (${hoursDec(tot.rounded)} h)`) : `${hoursDec(tot.rounded)} h`, trn('{0} entry', '{0} entries', tot.count)].join(' · ')]];
  if (!(f === t && f === today())) tiles.push([hmm(j.today.seconds), tr('today'), tgt ? tr('{0}% of the daily target ({1} h)', Math.round(100 * j.today.seconds / 3600 / tgt), String(tgt).replace('.', LOCALE().startsWith('de') ? ',' : '.')) : tr('your time')]);
  else if (tgt) tiles[0][2] += ' · ' + tr('{0}% of the daily target ({1} h)', Math.round(100 * j.today.seconds / 3600 / tgt), String(tgt).replace('.', LOCALE().startsWith('de') ? ',' : '.'));
  if (hasAmt) tiles.push([money(tot.amount, j.currency), tr('amount'), tr('hourly rates of the lists')]);
  h += `<div class="sttiles">${tiles.map(([v, l, s]) => `<div><b>${esc(v)}</b><span>${esc(l)}</span><small>${esc(s)}</small></div>`).join('')}</div>`;
  // per day (per week for long ranges)
  const days = []; for (let d = f; d <= t && days.length < 400; d = addDays(d, 1)) days.push(d);
  const per = Object.fromEntries(j.days.map(x => [x.date, x.seconds / 60]));
  if (days.length > 1) {
    const weekly = days.length > 62, keys = weekly ? [...new Set(days.map(weekStartOf))] : days;
    const vals = keys.map(k => weekly ? days.filter(d => weekStartOf(d) === k).reduce((n, d) => n + (per[d] || 0), 0) : per[k] || 0);
    h += `<section class="stcard"><div class="sthead"><h3>${weekly ? tr('Per week') : tr('Per day')}</h3></div>${barChart(vals, keys.map(k => weekly ? shortDay(k) : days.length <= 7 ? WD[pd(k).getDay()] : String(pd(k).getDate())),
      {fmt: v => fmtH(Math.round(v)), tip: i => `${weekly ? tr('Week of {0}', fmtDate(keys[i])) : fmtDate(keys[i])}: ${fmtH(Math.round(vals[i]))}`, label: tr('Tracked time')})}</section>`;
  }
  if (!j.lists.length) return h + `<div class="empty">${ic('clock')}${tr('No time tracked in this period.')}</div></div>`;
  const all = j.scope === 'all', ppl = us => all && us.length ? `<small class="muted">${esc(us.map(([n, s]) => `${n} ${hmm(s)}`).join(', '))}</small>` : '';
  h += `<section class="stcard"><div class="sthead"><h3>${tr('By list and task')}</h3>${rm ? `<span class="muted">${tr('rounded up to {0} min per entry', rm)}</span>` : ''}</div>
    <table class="ttable"><thead><tr><th>${tr('List / task')}</th><th class="n">${tr('Time|tracked')}</th>${rm ? `<th class="n">${tr('Rounded')}</th>` : ''}${hasAmt ? `<th class="n">${tr('Amount')}</th>` : ''}</tr></thead><tbody>
    ${j.lists.map(l => { const closed = S.collapsed.has('tvl:' + l.id); return `<tr class="tvl ${closed ? 'closed' : ''}" data-act="tv-toggle" data-key="tvl:${l.id}"><td>${ic('chev', 's')}<span>${esc(tvListName(l))}</span>${ppl(l.users)}</td><td class="n">${hmm(l.seconds)}</td>${rm ? `<td class="n">${hmm(l.rounded)}</td>` : ''}${hasAmt ? `<td class="n">${l.rate ? money(l.amount, j.currency) : ''}</td>` : ''}</tr>` +
      (closed ? '' : l.tasks.map(x => `<tr class="tvt" ${x.id ? `data-act="te-open" data-id="${x.id}"` : ''}><td><span>${esc(x.title || tr('No task'))}</span>${ppl(x.users)}</td><td class="n">${hmm(x.seconds)}</td>${rm ? `<td class="n">${hmm(x.rounded)}</td>` : ''}${hasAmt ? `<td class="n">${l.rate ? money(x.amount, j.currency) : ''}</td>` : ''}</tr>`).join('')); }).join('')}
    <tr class="tvsum"><td>${tr('Total')}</td><td class="n">${hmm(tot.seconds)}</td>${rm ? `<td class="n">${hmm(tot.rounded)}</td>` : ''}${hasAmt ? `<td class="n">${money(tot.amount, j.currency)}</td>` : ''}</tr></tbody></table></section>`;
  const byDay = {}; for (const e of j.entries) (byDay[e.day] ||= []).push(e);
  h += `<section class="stcard"><div class="sthead tvtoggle" data-act="tv-entries"><h3>${ic('chev', 's' + (tv.entries ? '' : ' closedc'))} ${tr('Entries')}</h3><span class="muted">${tot.count}</span></div>
    ${tv.entries ? Object.keys(byDay).sort().reverse().map(d => `<div class="teday"><span>${esc(dayLabel(d))}</span><b>${hmm(byDay[d].reduce((n, e) => n + e.seconds, 0))}</b></div>${byDay[d].slice().reverse().map(e => teRow(e, {day: false})).join('')}`).join('') : ''}</section>`;
  return h + `<p class="muted stnote">${tr('An entry counts on the day it starts. Rounding and the hourly rate (list settings) only apply to the report, CSV and timesheet; the tracked times stay exact.')}</p></div>`;
}
function tvListsMenu(anchor) {
  const cur = new Set(tvLists());
  const ls = S.lists.filter(l => !l.archived || cur.has(l.id));
  const p = openPop(anchor, `<div class="menu-list tvlm"><label><input type="checkbox" data-l="all" ${cur.size ? '' : 'checked'}> ${tr('All lists')}</label><hr>${ls.map(l => `<label><input type="checkbox" data-l="${l.id}" ${cur.has(l.id) ? 'checked' : ''}> ${esc(lname(l))}</label>`).join('')}<label><input type="checkbox" data-l="0" ${cur.has(0) ? 'checked' : ''}> ${tr('No list')}</label></div>`, () => { S.tv.key = ''; renderView(); });
  p.onchange = e => {
    const x = e.target.closest('[data-l]'); if (!x) return;
    if (x.dataset.l === 'all') S.tv.lists = [];
    else { const id = +x.dataset.l, s = new Set(tvLists()); x.checked ? s.add(id) : s.delete(id); S.tv.lists = [...s]; }
    LS.set('timeLists', S.tv.lists);
    $$('[data-l]', p).forEach(c => { c.checked = c.dataset.l === 'all' ? !S.tv.lists.length : S.tv.lists.includes(+c.dataset.l); });
  };
}
async function openTaskById(id) {  // a task from the report may be completed long ago (not in the state)
  if (!taskById(id)) {
    try { (S.extra ||= []).push(await rawFetch('GET', `/api/tasks/${id}`)); }
    catch (e) { toast(e instanceof Offline ? tr('Only available online.') : tr('Task not found')); return; }
  }
  openDetail(id);
}
// printable timesheet ("Stundennachweis") of the current report; the browser's print dialog saves it as PDF
function timesheet() {
  const j = S.tv.data; if (!j) return;
  const rm = j.rounding, hasAmt = j.lists.some(l => l.rate), cur = j.currency, all = j.scope === 'all';
  const who = all ? tr('All members') : j.me.display_name;
  const filt = tvLists().length ? ' · ' + tvListsLabel() : '';
  const ustr = us => esc(us.map(([n, s]) => `${n} ${hmm(s)}`).join(', '));
  const cols = (x, rate, amt) => `<td class="n">${hmm(x.rounded)}</td><td class="n">${hoursDec(x.rounded)}</td>${hasAmt ? `<td class="n">${rate}</td><td class="n">${amt}</td>` : ''}`;
  const byList = {}; for (const e of j.entries) (byList[e.list_id || 0] ||= []).push(e);
  const lname2 = id => { const l = j.lists.find(x => x.id === id); return l ? tvListName(l) : tr('No list'); };
  const doc = `<h1>${tr('Timesheet')}</h1><div class="tssub">${esc(rangeLabel(j.from, j.to))} · ${esc(who)}${esc(filt)}${rm ? ' · ' + esc(tr('rounded up to {0} min per entry', rm)) : ''} · ${esc(tr('created {0}', fmtDate(today())))}</div>
    <div class="tskpi"><div><b>${hoursDec(j.total.rounded)} h</b><span>${rm ? tr('hours (rounded)') : tr('hours')}</span></div><div><b>${hmm(j.total.rounded)}</b><span>h:mm</span></div>${hasAmt ? `<div><b>${money(j.total.amount, cur)}</b><span>${tr('amount')}</span></div>` : ''}<div><b>${j.total.count}</b><span>${trn('entry', 'entries', j.total.count)}</span></div></div>
    <table><thead><tr><th>${tr('List / task')}</th><th>${tr('People')}</th><th class="n">h:mm</th><th class="n">${tr('Hours')}</th>${hasAmt ? `<th class="n">${tr('Rate')}</th><th class="n">${tr('Amount')}</th>` : ''}</tr></thead><tbody>
    ${j.lists.map(l => `<tr class="p"><td>${esc(tvListName(l))}</td><td class="muted">${ustr(l.users)}</td>${cols(l, l.rate ? money(l.rate, cur) : '', l.rate ? money(l.amount, cur) : '')}</tr>${l.tasks.map(x => `<tr class="t"><td>${esc(x.title || tr('No task'))}</td><td class="muted">${ustr(x.users)}</td>${cols(x, '', l.rate ? money(x.amount, cur) : '')}</tr>`).join('')}`).join('')}
    <tr class="g"><td>${tr('Total')}</td><td class="muted">${esc(j.users.map(u => `${u.name} ${hmm(u.rounded)}`).join(', '))}</td><td class="n">${hmm(j.total.rounded)}</td><td class="n">${hoursDec(j.total.rounded)}</td>${hasAmt ? `<td></td><td class="n">${money(j.total.amount, cur)}</td>` : ''}</tr></tbody></table>
    <h2>${tr('Per day')}</h2><table class="tsdays"><thead><tr><th>${tr('Date')}</th><th class="n">h:mm</th><th class="n">${tr('Hours')}</th></tr></thead><tbody>${j.days.map(d => `<tr><td>${esc(fmtDay('year', pd(d.date)))}</td><td class="n">${hmm(d.rounded)}</td><td class="n">${hoursDec(d.rounded)}</td></tr>`).join('')}</tbody></table>
    <div class="tsentries">${Object.keys(byList).map(id => `<h2>${esc(lname2(+id))}</h2><table class="entries"><thead><tr><th>${tr('Date')}</th><th>${tr('Time|tracked')}</th><th>${tr('Task')}</th><th>${tr('Note')}</th>${all ? `<th>${tr('User')}</th>` : ''}<th class="n">h:mm</th>${rm ? `<th class="n">${tr('Rounded')}</th>` : ''}</tr></thead><tbody>
      ${byList[id].map(e => { const s = new Date(e.start), en = e.end ? new Date(e.end) : null; return `<tr><td>${esc(fmtDate(ds(s)))}</td><td>${fmtClock(s)} – ${en ? fmtClock(en) : tr('running')}</td><td>${esc(e.title || tr('No task'))}</td><td class="note">${esc(e.note)}</td>${all ? `<td class="muted">${esc(e.user_name)}</td>` : ''}<td class="n">${hmm(e.seconds)}</td>${rm ? `<td class="n">${hmm(e.rounded)}</td>` : ''}</tr>`; }).join('')}</tbody></table>`).join('')}</div>`;
  $('.tsheet')?.remove();
  const el = document.createElement('div');
  el.className = 'tsheet';
  el.innerHTML = `<div class="tsbar"><button class="btn pri" data-ts="print">${ic('download', 's')} ${tr('Print / save as PDF')}</button><label class="chkl"><input type="checkbox" id="ts-entries" ${LS.get('tsEntries', true) ? 'checked' : ''}> ${tr('Individual entries')}</label><span class="spacer"></span><span class="muted tshint">${tr('In the print dialog choose “Save as PDF”.')}</span><button class="iconbtn" data-ts="close" aria-label="${tr('Close')}">${ic('x')}</button></div><div class="tspage ${LS.get('tsEntries', true) ? '' : 'noentries'}" lang="${esc(document.documentElement.lang)}">${doc}</div>`;
  document.body.appendChild(el);
  document.body.classList.add('tsprint');
  const close = () => { el.remove(); document.body.classList.remove('tsprint'); document.title = APP_NAME; };
  el.addEventListener('click', ev => { const b = ev.target.closest('[data-ts]'); if (!b) return; if (b.dataset.ts === 'close') close(); else window.print(); });
  el.addEventListener('change', ev => { if (ev.target.id === 'ts-entries') { LS.set('tsEntries', ev.target.checked); $('.tspage', el).classList.toggle('noentries', !ev.target.checked); } });
  el.addEventListener('keydown', ev => { if (ev.key === 'Escape') close(); });
  document.title = `${tr('Timesheet')} ${rangeLabel(j.from, j.to)}${all ? '' : ' ' + j.me.display_name}`;
}
