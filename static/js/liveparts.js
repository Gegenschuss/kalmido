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
const LP_KEEP = new Set(['office', 'clients', 'contacts']);  // views a change of someone else never redraws (2.431.0 C, #3602: + contacts; clients / contacts follow with ms_clLive / ct_live)
const LP_DEFER_MS = 15000;
S.lpN = {render: 0, state: 0, light: 0};  // counters for the measurement (render() calls, full state loads, light updates)
let lpT = 0, lpAreas = new Set();
// a form on the screen with unsaved input (formguard.js); drafts of forms not shown any more do not count
const lpFormBusy = (root = document) => !!root && typeof fgDirty === 'function' && [...root.querySelectorAll('[data-fg]')].some(f => fgDirty(f.dataset.fg));
// 2.358 (#3402): a press / drag that holds an element (drag.js: the timeline's bars and its new-task ghost .tl-ghost; the
// calendar's held event .cgghost / .cgsrc): a redraw would replace it under the finger (on a phone the held event dropped)
const lpHold = () => !!((typeof drg_cur !== 'undefined' && drg_cur) || (typeof CG !== 'undefined' && CG.st?.active) || (typeof rswBusy === 'function' && rswBusy()));  // 2.542.0 (#4614): + a swipe to reply (collab.js draws after it)
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
// 2.369.4 (#2507): the total v moved, but vs (the newest version meant for me: my organisations, my lists, my own writes)
// did not pass the version my state has -> only changes elsewhere (another organisation, lists I do not see): the state
// is as new as v, nothing is fetched. A v below mine (a restored backup) or an older server without vs takes the old way.
function lpSkip(v, vs) {
  if (S.lpOff || vs === undefined || S.v == null || !(v > S.v) || vs > S.v) return false;
  S.v = v; S.lpN.skip = (S.lpN.skip || 0) + 1;
  return true;
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
    let r; try { r = await load(true, S.v); } catch { return; }  // 2.545.0 (#4483): a load() on its way: wait for it, fetch again only when it predates the known version
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
  try { j = await api('GET', `/api/state/delta?since=${follow ? since : S.v}&lean=1${wside ? '&side=1' : ''}${S.lz ? '&lz=1' : ''}&tt=1`); } catch { return false; }  // 2.369.2 (#3136): + lz
  if (!j || j.full !== false || (S.wseq || 0) !== w0 || OUT.q.length) return false;  // a write of mine overtook it: the full way
  if (light.length && !follow) lpLive(v, light, n, true);  // comments of the open task, the open chat, news (their own fetches)
  S.lpN.delta++;
  const side = lpSideCnt() + (wside ? lpSideSig() : ''), sel = S.sel, changed = new Set();
  if (wside && j.team) lpSideTake(j);
  tdFill(j.tasks);  // 2.575.0 B (#3966): the delta sends whole tasks; filled all the same (one way in)
  for (const t of j.tasks || []) { S.tasks.set(t.id, t); changed.add(t.id); }
  for (const id of j.gone || []) if (S.tasks.delete(id)) changed.add(id);
  _kidsIx = null;
  const pr = j.progress || {};
  for (const l of S.lists || []) if (pr[l.id]) l.progress = pr[l.id];
  if (j.counts) S.counts = j.counts;
  lzDelta(j);  // 2.369.2 (#3136)
  if (!j.lean) S.mineOrder = moFromState(j);  // 2.191.0 C (#2507): lean = nothing of mine changed, the order stays
  for (const [k, src] of [['evlinks', j.evlinks || {}], ['tcontacts', j.tcontacts || {}]]) {
    const m = S[k] || (S[k] = {});
    for (const id of changed) { if (src[id]) m[id] = src[id]; else delete m[id]; }
  }
  if (j.timer !== undefined) {  // 2.579.0 (#4184): time_ids = the delta has the totals of these tasks only: mix, not replace
    S.timer = j.timer || null; S.timeLists = j.time_lists || {};
    if (Array.isArray(j.time_ids)) { const m = S.timeTotals || (S.timeTotals = {}); for (const id of j.time_ids) delete m[id]; Object.assign(m, j.time_totals || {}); }
    else S.timeTotals = j.time_totals || {};
  }
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
    if (S.lz) c.lz = {pending: [...S.lz.pending], counts: S.lz.counts}; else delete c.lz;  // 2.369.2 (#3136): the loaded lists stay
    LS.set('cache', c);
  }, 30000);
}

// ---- 2.369.2 (#3136): the start set of a big account. /api/state?lz=1 answers a person with many tasks (server switch
// KALMIDO_STATE_LAZY_MIN) with the tasks Today / Upcoming / My tasks need plus the lists named in lzl; lz.pending = the
// lists whose tasks are not all here, lz.counts = their open top-level tasks and tags (the sidebar). A view loads what it
// shows before it is complete: a list its tasks, a folder its lists, every view not known to need less all of them
// (lzNeed). Loaded lists stay (the offline cache keeps them, the next /api/state names them in lzl). S.lz = null: the
// whole state (a small account, an old server).
S.lz = null;
const LZ_SET = new Set(['today', 'tomorrow', 'week', 'pinned', 'waiting', 'inbox']);  // covered by the start set
const LZ_FREE = new Set([...LP_NOTASKS, 'news', 'contacts', 'budget', 'feeds', 'bookmarks', 'reading', 'wiki', 'sheets', 'ablage', 'docs', 'msv']);
function lzTake(j) {
  S.lz = j.lz ? {pending: new Set(j.lz.pending || []), counts: j.lz.counts || {}} : null;
}
// 2.575.0 B (#3966): an answer asked with td=1 leaves out the keys a task holds at their default; its table (tdef, the server's
// serializers.TD_DEFAULTS) puts them back before anything reads the tasks (applyState, lzLoad, the delta), so a task is the one
// the whole state has (t.x === null, 'x' in t). content stays out where the note is long (content_n). The one fill function.
S.tdef = null;
function tdFill(ts, def = S.tdef) {
  if (!def || !ts) return ts;
  const ks = Object.keys(def);
  for (const t of ts) for (const k of ks) if (!(k in t) && !(k === 'content' && 'content_n' in t)) { const v = def[k]; t[k] = v !== null && typeof v === 'object' ? (Array.isArray(v) ? [] : {}) : v; }
  return ts;
}
// the query of the next /api/state: the lists this window has whole (all = every one, nothing is pending)
function lzQuery() {
  if (!S.lz) return S.booted && S.tasks.size ? 'lz=1&lzl=all' : 'lz=1&lzl=' + lzRecent().join(',');
  if (!S.lz.pending.size) return 'lz=1&lzl=all';
  return 'lz=1&lzl=' + (S.lists || []).map(l => l.id).filter(id => !S.lz.pending.has(id)).join(',');
}
// the lists opened last on this device (the first load of a new window keeps them whole: they are what is opened next)
const lzRecent = () => (LS.get('lzOpen', []) || []).filter(Number.isInteger).slice(0, 20);
function lzRemember(ids) { LS.set('lzOpen', [...new Set([...ids, ...lzRecent()])].slice(0, 20)); }
// what the current view needs loaded: [] = nothing more, [list ids], null = every list
function lzNeed(r = S.route) {
  const k = r?.key || '';
  if (r?.mod === 'tasks') {
    if (LZ_SET.has(k)) return [];
    if (k === 'assigned' || k === 'doable') return collab() ? (S.lists || []).filter(isOwner).map(l => l.id) : null;  // + the unassigned ones of my lists
    if (k.startsWith('l:')) return [+k.slice(2)];
    if (k.startsWith('folder:')) return folderLists(k.slice(7)).map(l => l.id);
    if (k.startsWith('lists:')) return dx_listIds(k);
    if (k === 'done' || k === 'trash') return [];  // their own pages (loadExtra)
    return null;
  }
  return LZ_FREE.has(r?.mod) ? [] : null;
}
// before a view draws: load what it needs (in the background, the view is drawn again when it is there)
function lzGate() {
  if (!S.lz?.pending.size) return;
  const need = lzNeed();
  if (need && !need.some(id => S.lz.pending.has(id))) return;
  lzLoad(need).then(ok => { if (ok) render(); });
}
const lzBusy = new Set();  // list ids being loaded ('all' = every pending one)
async function lzLoad(want) {
  if (!S.lz?.pending.size || lzBusy.has('all')) return false;
  const ids = want === null ? [...S.lz.pending] : want.filter(id => S.lz.pending.has(id) && !lzBusy.has(id));
  if (!ids.length) return false;
  const key = want === null ? 'all' : null;
  if (key) lzBusy.add(key);
  ids.forEach(id => lzBusy.add(id));
  let j;
  try { j = await api('GET', '/api/state/lists?td=1&ids=' + (key || ids.join(','))); tdFill(j.tasks, j.tdef || S.tdef); }  // 2.575.0 B (#3966): + td
  catch { return false; }  // offline: the view shows what it has
  finally { if (key) lzBusy.delete(key); ids.forEach(id => lzBusy.delete(id)); }
  if (!S.lz) return true;  // a whole state came meanwhile
  // a task changed after the answer was read (the live update brought it already) keeps its newer copy
  for (const t of j.tasks || []) { const o = S.tasks.get(t.id); if (!o || j.v >= S.v || !o.updated_at || o.updated_at <= t.updated_at) S.tasks.set(t.id, t); }
  for (const k of ['evlinks', 'tcontacts']) Object.assign(S[k] || (S[k] = {}), j[k] || {});  // their events / contacts, as the state has them
  _kidsIx = null;
  ids.forEach(id => { S.lz.pending.delete(id); delete S.lz.counts[id]; });
  if (want !== null) lzRemember(ids);
  lpCacheSoon();
  return true;
}
// the open task is not loaded (an address, a notification): its list comes first
// 2.509.0 (#4324): opening = true (renderDetail0): a task in no loaded list either (completed long ago) comes alone (S.extra);
// not there or offline: a hint and the panel closes. Without it (render, the task left the state) the panel closes as before
const lzSelBusy = new Set();
function lzSel(id, opening) {
  if (!(id > 0)) return false;
  if (lzSelBusy.has(id)) return true;
  if (!opening && !S.lz?.pending.size) return false;
  lzSelBusy.add(id);
  rawFetch('GET', `/api/tasks/${id}`).then(async t => {
    if (t?.list_id) await lzLoad([t.list_id]).catch(() => false);
    lzSelBusy.delete(id);
    if (S.tasks.has(id)) render();
    else if (S.sel !== id) return;
    else if (!opening) closeDetail();
    else if (t?.id !== id) { closeDetail(); toast(tr('Task not found')); }
    else { (S.extra ||= []).push(t); renderDetail(); }
  }, e => {
    lzSelBusy.delete(id);
    if (S.sel !== id || S.tasks.has(id)) return;
    closeDetail();
    if (opening) toast(e instanceof Offline ? tr('Only available online.') : tr('Task not found'));
  });
  return true;
}
// counts(): a list the server counts (pending, not one where only my own tasks show)
let lzRd = {lists: null, ids: null};  // the lists where only my own tasks show (org_reader), per S.lists (counts() runs per task)
const lzReader = lid => { if (lzRd.lists !== S.lists) lzRd = {lists: S.lists, ids: new Set((S.lists || []).filter(l => l.org_reader).map(l => l.id))}; return lzRd.ids.has(lid); };
const lzCounted = lid => !!S.lz?.pending.has(lid) && !lzReader(lid);
function lzCounts(c) {
  if (!S.lz?.pending.size) return;
  for (const lid of S.lz.pending) {
    const x = S.lz.counts[lid], t = {list_id: lid, status: 0};
    if (!x || !lzCounted(lid) || archHidden(t) || wsHidden(t)) continue;
    c.lists[lid] = (c.lists[lid] || 0) + x.n; c.all += x.n;
    for (const [g, n] of Object.entries(x.tags || {})) c.tags[g] = (c.tags[g] || 0) + n;
  }
  // over all tasks: not known while lists are missing (the row shows no number, the view loads them)
  c.doable = c.byme = undefined; c.filters = {};
}
// the delta's counts of the touched lists I have not loaded
function lzDelta(j) { if (S.lz && j.lzc) for (const [lid, x] of Object.entries(j.lzc)) if (S.lz.pending.has(+lid)) S.lz.counts[lid] = x; }
