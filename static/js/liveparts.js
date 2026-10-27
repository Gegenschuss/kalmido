// 2.41.0 (#1376): live updates per area. /api/version carries a change counter per area (a: tasks, comments, agentchat,
// team, office, calendar, news, other) besides the old total v. A change in an area that only feeds parts of the screen
// (comments, the agent chat, the team chat, news, calendars) no longer reloads the whole state and redraws everything:
// the open task's comments, the open chat / channel are fetched at once; the state (counters on rows and in the sidebar)
// follows bundled (at most every LP_DEFER_MS) and is drawn only where a counter changed (rows of the view, the sidebar);
// the sidebar keeps its nodes (no avatar flicker, #1225). Office / clients views are never redrawn by a change of someone
// else. Unsaved form input (formguard.js, #1371) holds every redraw back like a focused field. Tasks / lists / "other"
// keep the full reload. S.lpOff = true switches it off (the old way, used by the measurement in the tests).
// 2.280.0 A (#3109): the bundled follow-up takes the delta since the version before the light changes + the sidebar's parts
// (agents, team chat, News, calendars: ?side=1) instead of the whole state; the knowledge pages are light (not in the state).
const LP_LIGHT = new Set(['comments', 'agentchat', 'team', 'news', 'calendar', 'budget', 'sheets', 'wiki']);  // 2.72.0 (#1333): + the household budget (its own fetch); 2.89.0 (#1916): + tables
const LP_KEEP = new Set(['office', 'clients']);  // views a change of someone else never redraws
const LP_DEFER_MS = 15000;
S.lpN = {render: 0, state: 0, light: 0};  // counters for the measurement (render() calls, full state loads, light updates)
let lpT = 0, lpAreas = new Set();
// a form on the screen with unsaved input (formguard.js); drafts of forms not shown any more do not count
const lpFormBusy = (root = document) => !!root && typeof fgDirty === 'function' && [...root.querySelectorAll('[data-fg]')].some(f => fgDirty(f.dataset.fg));
// 2.358 (#3402): a press / drag that holds an element (drag.js: the timeline's bars and its new-task ghost .tl-ghost; the
// calendar's held event .cgghost / .cgsrc): a redraw would replace it under the finger (on a phone the held event dropped)
const lpHold = () => !!((typeof drg_cur !== 'undefined' && drg_cur) || (typeof CG !== 'undefined' && CG.st?.active));
const lpBusy = () => editing() || lpFormBusy() || lpHold();
// the areas whose counter moved since the last poll (null: unknown -> the full way)
// 2.280.0 F (#3109): + those of earlier polls not taken yet (typing, a dialog, a braked reload: S.v stayed behind); lpSettle
// forgets them once the state reached the polled version
S.lpPend = new Set(); S.lpUnk = false;
function lpChanged(a) {
  const p = S.lpA; S.lpA = a || null;
  if (!a || !p || S.lpOff) { S.lpUnk = true; return null; }
  for (const k of Object.keys(a)) if (a[k] !== p[k] && !(k === 'self' && lpOwnSelf(p[k], a[k]))) S.lpPend.add(k);
  return S.lpUnk ? null : [...S.lpPend];
}
function lpSettle(v) { if (S.v != null && S.v >= v) { S.lpPend.clear(); S.lpUnk = false; } }
// 2.280.0 A (#3109): "self" (my own settings, habits, layouts: one counter per account) moved only by writes of this window
// (their answers carry the new counter, X-Kalmido-Lv): nothing to reload; a write of another device of mine: the full way
const lpSelfOwn = new Set();
function lpOwnNote(h) { const m = /^self:(\d+)$/.exec(h || ''); if (m) lpSelfOwn.add(+m[1]); }
function lpOwnSelf(from, to) {
  let n = 0;
  for (const x of lpSelfOwn) { if (x > from && x <= to) n++; if (x <= to) lpSelfOwn.delete(x); }
  return to > from && n === to - from;
}
// called by the poll when v moved, with lpChanged's areas: true = handled here (only light areas changed)
// inDelta: 2.280.0 A (#3109) called by lpDelta for the light areas next to tasks (the delta fetched the sidebar's parts)
function lpLive(v, ch, n, inDelta) {
  if (!ch || !ch.length || ch.some(k => !LP_LIGHT.has(k))) return false;
  S.lpN.light++;
  if (!inDelta) {
    if (!lpT) S.lpBase = S.v;  // 2.280.0 A (#3109): the follow-up's delta starts here
    S.v = v;  // the change is known; the state follows bundled
    for (const k of ch) lpAreas.add(k);
  }
  // 2.41.1 (#1376): news arise from comments / chats (their area moves, not "news"): a new news signature fetches the
  // news at once (bell badge, tabs, an open News view), not only with the bundled state; with unsaved input the next poll
  // takes the held-back full way as before
  if (n !== undefined && collab() && n !== S.news?.sig && !lpBusy()) loadNews();
  if (ch.includes('comments') && S.sel > 0 && (cmtOn() || collab()) && S.tl.id === S.sel) loadTimeline(S.sel);
  if (ch.includes('agentchat') && S.chat.aid && collab()) chatLoad();
  if (ch.includes('budget') && typeof bg_live === 'function') bg_live();  // 2.72.0 (#1333)
  if (ch.includes('sheets') && typeof shvLive === 'function') shvLive();  // 2.89.0 (#1916): the open table (sheets.js)
  if (ch.includes('wiki') && S.route.mod === 'wiki') td_renderSoon();  // 2.280.0 A (#3109): drawn as after the full reload before
  if (!lpT && !inDelta) lpT = setTimeout(lpFollow, LP_DEFER_MS);
  return true;
}
// what the sidebar and the rows show of the light areas (a change of it is drawn, nothing else)
const lpSideSig = () => JSON.stringify([(S.agents || []).map(x => [x.id, x.chat_unread, x.approvals_open, x.waiting, x.status]), S.team, S.news?.unread, S.news?.unread_me]);
// 2.351.1: the tasks as one order-free number (ids + change times): a whole-state follow-up redraws the view only when they moved
const lpTaskSig = () => { let n = 0, h = 0; for (const t of S.tasks.values()) { n++; h = (h + t.id * 7919 + (Date.parse(t.updated_at) || 0) % 1e9) % 2147483647; } return n + ':' + h; };
function lpRowSig() { const o = []; for (const t of S.tasks.values()) if (t.comment_count || t.unread || t.approvals_open) o.push(t.id, t.comment_count, t.unread, t.approvals_open || 0); return o.join(','); }
async function lpFollow() {
  clearTimeout(lpT); lpT = 0;  // 2.351.0 D (#2785): called early (not by its timer): the timer must not run it a second time later
  if (document.hidden || lpBusy()) { lpT = setTimeout(lpFollow, 4000); return; }
  const side = lpSideSig(), rows = lpRowSig(), areas = lpAreas, since = S.lpBase ?? S.v; lpAreas = new Set();
  let ok = false;
  try { ok = await lpDelta(S.v, ['tasks', ...areas], undefined, since); } catch { ok = false; }  // 2.280.0 A (#3109)
  if (!ok) {  // the server answered full: as before
    S.lpN.state++;
    const ts = lpTaskSig();
    let r; try { r = await load(true); } catch { return; }
    if (r === 'brake') { for (const k of areas) lpAreas.add(k); if (!lpT) lpT = setTimeout(lpFollow, 4000); return; }  // 2.280.0 F (#3109): held back: again later
    // 2.351.0 D (#2785): the whole state may bring more than the light counters (a task deleted on another device meanwhile):
    // it took S.v, so the poll sees nothing new any more -> drawn bundled like the poll's full way (lpDraw checks only counters);
    // 2.351.1: only when the tasks moved - else a redraw dropped what the view held (the timeline's hold ghost, its scroll)
    if (lpTaskSig() !== ts) { if (lpHold()) S.viewStale = true; else td_renderSoon(); }  // 2.358 (#3402): held: drawn after letting go
  }
  lpDraw(side, rows, areas);
}
function lpDraw(side, rows, areas) {
  if (lpSideSig() !== side) { renderSide(); badgeSync(); renderTabs(); }
  if (LP_KEEP.has(S.route.mod)) return;
  if (lpRowSig() !== rows && (S.route.mod === 'tasks' || S.route.mod === 'home')) lpViewSafe();  // 2.42.0 (#1376): morphed
}
// the full way also counts (measurement); a full load ends a pending light follow-up
// 2.280.0 F (#3109): returns what plans it again (the full load was braked)
function lpFull() {
  if (!lpT) return () => {};
  const a = lpAreas; clearTimeout(lpT); lpT = 0; lpAreas = new Set();
  return () => { for (const k of a) lpAreas.add(k); if (!lpT) lpT = setTimeout(lpFollow, 4000); };
}
// views a change of someone else must not redraw: the poll's full way skips the view there (the sidebar etc. still follow)
const lpKeepView = () => !S.lpOff && LP_KEEP.has(S.route.mod);

// 2.42.0 (#1376): the delta state. When the tasks area moved (alone or with light areas), the poll asks GET /api/state/delta
// ?since=S.v for the tasks that changed since the state this window has, puts them into S.tasks (gone ones out), takes the
// lists' progress, the counts and "My tasks" order along and redraws only what shows them: the view by morphing (rows that
// did not change keep their nodes), the sidebar / header / tabs only when a counter there moved, the open task when it changed.
// The server answers full (a share or list changed, too many changes, too old a state, a participant ...) -> false: the
// caller takes the full way as before. Unsaved input holds every redraw back (the view is marked stale, as before).
// 2.280.0 A (#3109): + time entries / the timer (were "other"): the delta has the changed tasks and my own timer; ch = [] (only
// changes counted for another account, "self"): the delta tells whether anything I see changed. An open time / workload /
// office / clients view reloads its own data with the full state: there the full way stays.
const LP_DELTA = new Set(['tasks', 'time', ...LP_LIGHT]);
const LP_TIMEVIEW = new Set(['time', 'workload', 'office', 'clients']);
const LP_NOTASKS = new Set(['office', 'clients', 'team', 'contacts', 'habits', 'pomo', 'notes', 'news', 'agents']);  // views that show no tasks
S.lpN.delta = 0;
let lpCacheT = 0;
const lpSideCnt = () => JSON.stringify([counts(), (S.lists || []).map(l => l.progress), S.counts]);
// since: 2.280.0 A (#3109) the follow-up of light changes (lpFollow) asks from the version before them
async function lpDelta(v, ch, n, since) {
  if (S.lpOff || S.v == null || !ch || ch.some(k => !LP_DELTA.has(k)) || OUT.q.length) return false;
  if (ch.includes('time') && LP_TIMEVIEW.has(S.route.mod)) return false;
  const light = ch.filter(k => LP_LIGHT.has(k)), follow = since !== undefined, wside = follow || light.length > 0;
  const w0 = S.wseq || 0;
  let j;
  try { j = await api('GET', `/api/state/delta?since=${follow ? since : S.v}&lean=1${wside ? '&side=1' : ''}`); } catch { return false; }
  if (!j || j.full !== false || (S.wseq || 0) !== w0 || OUT.q.length) return false;  // a write of mine overtook it: the full way
  if (light.length && !follow) lpLive(v, light, n, true);  // comments of the open task, the open chat, news (their own fetches)
  S.lpN.delta++;
  const side = lpSideCnt() + (wside ? lpSideSig() : ''), sel = S.sel, changed = new Set();
  if (wside && j.team) lpSideTake(j);
  for (const t of j.tasks || []) { S.tasks.set(t.id, t); changed.add(t.id); }
  for (const id of j.gone || []) if (S.tasks.delete(id)) changed.add(id);
  _kidsIx = null;
  const pr = j.progress || {};
  for (const l of S.lists || []) if (pr[l.id]) l.progress = pr[l.id];
  if (j.counts) S.counts = j.counts;
  if (!j.lean) S.mineOrder = moFromState(j);  // 2.191.0 C (#2507): lean = nothing of mine changed, the order stays
  for (const [k, src] of [['evlinks', j.evlinks || {}], ['tcontacts', j.tcontacts || {}]]) {
    const m = S[k] || (S[k] = {});
    for (const id of changed) { if (src[id]) m[id] = src[id]; else delete m[id]; }
  }
  if (j.timer !== undefined) { S.timer = j.timer || null; S.timeTotals = j.time_totals || {}; S.timeLists = j.time_lists || {}; }
  S.v = Math.max(S.v, j.v);
  lpCacheSoon();
  if (!changed.size) {
    if (wside && !follow && lpSideCnt() + lpSideSig() !== side) { renderSide(); renderTop(); renderTabs(); badgeSync(); }  // lpFollow draws itself
    return true;
  }
  if (S.extra) await loadExtra().catch(() => {});
  if (sel && changed.has(sel)) {  // the open task: its timeline / time / dependencies follow like after a full load
    if ((cmtOn() || collab()) && S.tl.id === sel && !light.includes('comments')) loadTimeline(sel);
    if (timeOn() && S.te.tid === sel) loadTaskTime(sel);
    if (S.dp.id === sel) loadDeps(sel);
  }
  if (lpBusy()) { S.viewStale = true; return true; }  // unsaved input: drawn once it is saved or dropped
  if (lpSideCnt() + (wside ? lpSideSig() : '') !== side) { renderSide(); renderTop(); renderTabs(); badgeSync(); }
  if (!LP_KEEP.has(S.route.mod) && !LP_NOTASKS.has(S.route.mod)) lpMorphView();
  if (sel && changed.has(sel)) {
    if (S.tasks.has(sel)) { if (!$('#detail')?.contains(document.activeElement)) renderDetail(); }
    else if (!(S.extra || []).some(t => t.id === sel)) closeDetail();
  }
  return true;
}
// 2.280.0 A (#3109): the sidebar's parts of the delta (?side=1), taken as applyState takes them from the whole state; the
// agents come from their own route
function lpSideTake(j) {
  if (typeof agentPoll === 'function' && S.me?.kind !== 'agent') agentPoll();  // the agents (chat unread, approvals, status): GET /api/agents
  S.team = j.team || {enabled: false, unread: 0};
  S.news = j.news || {unread: 0, sig: ''};
  S.evcals = j.evcals || [];
  if (j.evsig !== undefined && j.evsig !== S.evsig) { S.evsig = j.evsig; if (S.booted) calInvalidate(); }
}
// the view redrawn by morphing unless a field / form in it is busy (then marked stale, drawn later like viewSafeRender)
function lpViewSafe() { if (lpHold() || (editing() && $('#view')?.contains(document.activeElement)) || lpFormBusy($('#view'))) { S.viewStale = true; return; } lpMorphView(); }
// the view redrawn by morphing: unchanged rows keep their nodes (2.46.2 #1718: calendar and timeline too)
function lpMorphView() {
  const el = $('#view'); if (!el) return;
  const prev = morphRoot;
  morphRoot = el;
  try { S.viewStale = false; renderView(); } finally { morphRoot = prev; }
}
// the offline start cache (the last full state) follows the delta, written at most every 30 s
function lpCacheSoon() {
  if (lpCacheT || !S.lpCache) return;
  lpCacheT = setTimeout(() => {
    lpCacheT = 0;
    const c = S.lpCache; if (!c) return;
    Object.assign(c, {v: S.v, tasks: [...S.tasks.values()], lists: S.lists, counts: S.counts});
    LS.set('cache', c);
  }, 30000);
}
