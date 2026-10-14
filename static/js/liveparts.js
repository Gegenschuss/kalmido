// 2.41.0 (#1376): live updates per area. /api/version carries a change counter per area (a: tasks, comments, agentchat,
// team, office, calendar, news, other) besides the old total v. A change in an area that only feeds parts of the screen
// (comments, the agent chat, the team chat, news, calendars) no longer reloads the whole state and redraws everything:
// the open task's comments, the open chat / channel are fetched at once; the state (counters on rows and in the sidebar)
// follows bundled (at most every LP_DEFER_MS) and is drawn only where a counter changed (rows of the view, the sidebar);
// the sidebar keeps its nodes (no avatar flicker, #1225). Office / clients views are never redrawn by a change of someone
// else. Unsaved form input (formguard.js, #1371) holds every redraw back like a focused field. Tasks / lists / "other"
// keep the full reload. S.lpOff = true switches it off (the old way, used by the measurement in the tests).
const LP_LIGHT = new Set(['comments', 'agentchat', 'team', 'news', 'calendar']);
const LP_KEEP = new Set(['office', 'clients']);  // views a change of someone else never redraws
const LP_DEFER_MS = 15000;
S.lpN = {render: 0, state: 0, light: 0};  // counters for the measurement (render() calls, full state loads, light updates)
let lpT = 0, lpAreas = new Set();
// a form on the screen with unsaved input (formguard.js); drafts of forms not shown any more do not count
const lpFormBusy = (root = document) => !!root && typeof fgDirty === 'function' && [...root.querySelectorAll('[data-fg]')].some(f => fgDirty(f.dataset.fg));
const lpBusy = () => editing() || lpFormBusy();
// the areas whose counter moved since the last poll (null: unknown -> the full way)
function lpChanged(a) {
  const p = S.lpA; S.lpA = a || null;
  if (!a || !p || S.lpOff) return null;
  return Object.keys(a).filter(k => a[k] !== p[k]);
}
// called by the poll when v moved, with lpChanged's areas: true = handled here (only light areas changed)
function lpLive(v, ch, n) {
  if (!ch || !ch.length || ch.some(k => !LP_LIGHT.has(k))) return false;
  S.lpN.light++;
  S.v = v;  // the change is known; the state follows bundled
  for (const k of ch) lpAreas.add(k);
  // 2.41.1 (#1376): news arise from comments / chats (their area moves, not "news"): a new news signature fetches the
  // news at once (bell badge, tabs, an open News view), not only with the bundled state; with unsaved input the next poll
  // takes the held-back full way as before
  if (n !== undefined && collab() && n !== S.news?.sig && !lpBusy()) loadNews();
  if (ch.includes('comments') && S.sel > 0 && (cmtOn() || collab()) && S.tl.id === S.sel) loadTimeline(S.sel);
  if (ch.includes('agentchat') && S.chat.aid && collab()) chatLoad();
  if (!lpT) lpT = setTimeout(lpFollow, LP_DEFER_MS);
  return true;
}
// what the sidebar and the rows show of the light areas (a change of it is drawn, nothing else)
const lpSideSig = () => JSON.stringify([(S.agents || []).map(x => [x.id, x.chat_unread, x.approvals_open, x.waiting, x.status]), S.team, S.news?.unread, S.news?.unread_me]);
function lpRowSig() { const o = []; for (const t of S.tasks.values()) if (t.comment_count || t.unread || t.approvals_open) o.push(t.id, t.comment_count, t.unread, t.approvals_open || 0); return o.join(','); }
async function lpFollow() {
  lpT = 0;
  if (document.hidden || lpBusy()) { lpT = setTimeout(lpFollow, 4000); return; }
  const side = lpSideSig(), rows = lpRowSig(), areas = lpAreas; lpAreas = new Set();
  S.lpN.state++;
  try { await load(); } catch { return; }
  lpDraw(side, rows, areas);
}
function lpDraw(side, rows, areas) {
  if (lpSideSig() !== side) { renderSide(); badgeSync(); renderTabs(); }
  if (LP_KEEP.has(S.route.mod)) return;
  if (lpRowSig() !== rows && (S.route.mod === 'tasks' || S.route.mod === 'home')) lpViewSafe();  // 2.42.0 (#1376): morphed
}
// the full way also counts (measurement); a full load ends a pending light follow-up
function lpFull() { if (lpT) { clearTimeout(lpT); lpT = 0; lpAreas = new Set(); } }
// views a change of someone else must not redraw: the poll's full way skips the view there (the sidebar etc. still follow)
const lpKeepView = () => !S.lpOff && LP_KEEP.has(S.route.mod);

// 2.42.0 (#1376): the delta state. When the tasks area moved (alone or with light areas), the poll asks GET /api/state/delta
// ?since=S.v for the tasks that changed since the state this window has, puts them into S.tasks (gone ones out), takes the
// lists' progress, the counts and "My tasks" order along and redraws only what shows them: the view by morphing (rows that
// did not change keep their nodes), the sidebar / header / tabs only when a counter there moved, the open task when it changed.
// The server answers full (a share or list changed, too many changes, too old a state, a participant ...) -> false: the
// caller takes the full way as before. Unsaved input holds every redraw back (the view is marked stale, as before).
const LP_DELTA = new Set(['tasks', ...LP_LIGHT]);
const LP_NOTASKS = new Set(['office', 'clients', 'team', 'contacts', 'habits', 'pomo', 'notes', 'news', 'agents']);  // views that show no tasks
S.lpN.delta = 0;
let lpCacheT = 0;
const lpSideCnt = () => JSON.stringify([counts(), (S.lists || []).map(l => l.progress), S.counts]);
async function lpDelta(v, ch, n) {
  if (S.lpOff || S.v == null || !ch || !ch.includes('tasks') || ch.some(k => !LP_DELTA.has(k)) || OUT.q.length) return false;
  const w0 = S.wseq || 0;
  let j;
  try { j = await api('GET', `/api/state/delta?since=${S.v}`); } catch { return false; }
  if (!j || j.full !== false || (S.wseq || 0) !== w0 || OUT.q.length) return false;  // a write of mine overtook it: the full way
  const light = ch.filter(k => k !== 'tasks');
  if (light.length) lpLive(v, light, n);  // comments of the open task, the open chat, news (their own fetches)
  S.lpN.delta++;
  const side = lpSideCnt(), sel = S.sel, changed = new Set();
  for (const t of j.tasks || []) { S.tasks.set(t.id, t); changed.add(t.id); }
  for (const id of j.gone || []) if (S.tasks.delete(id)) changed.add(id);
  _kidsIx = null;
  const pr = j.progress || {};
  for (const l of S.lists || []) if (pr[l.id]) l.progress = pr[l.id];
  if (j.counts) S.counts = j.counts;
  S.mineOrder = moFromState(j);
  for (const [k, src] of [['evlinks', j.evlinks || {}], ['tcontacts', j.tcontacts || {}]]) {
    const m = S[k] || (S[k] = {});
    for (const id of changed) { if (src[id]) m[id] = src[id]; else delete m[id]; }
  }
  if (j.timer !== undefined) { S.timer = j.timer || null; S.timeTotals = j.time_totals || {}; S.timeLists = j.time_lists || {}; }
  S.v = Math.max(S.v, j.v);
  lpCacheSoon();
  if (!changed.size) return true;
  if (S.extra) await loadExtra().catch(() => {});
  if (sel && changed.has(sel)) {  // the open task: its timeline / time / dependencies follow like after a full load
    if ((cmtOn() || collab()) && S.tl.id === sel && !light.includes('comments')) loadTimeline(sel);
    if (timeOn() && S.te.tid === sel) loadTaskTime(sel);
    if (S.dp.id === sel) loadDeps(sel);
  }
  if (lpBusy()) { S.viewStale = true; return true; }  // unsaved input: drawn once it is saved or dropped
  if (lpSideCnt() !== side) { renderSide(); renderTop(); renderTabs(); badgeSync(); }
  if (!LP_KEEP.has(S.route.mod) && !LP_NOTASKS.has(S.route.mod)) lpMorphView();
  if (sel && changed.has(sel)) {
    if (S.tasks.has(sel)) { if (!$('#detail')?.contains(document.activeElement)) renderDetail(); }
    else if (!(S.extra || []).some(t => t.id === sel)) closeDetail();
  }
  return true;
}
// the view redrawn by morphing unless a field / form in it is busy (then marked stale, drawn later like viewSafeRender)
function lpViewSafe() { if ((editing() && $('#view')?.contains(document.activeElement)) || lpFormBusy($('#view'))) { S.viewStale = true; return; } lpMorphView(); }
// the view redrawn by morphing: unchanged rows keep their nodes (views that wire their DOM after rendering are rebuilt)
function lpMorphView() {
  const el = $('#view'); if (!el) return;
  const prev = morphRoot;
  morphRoot = S.route.mod === 'cal' || $('#tlscroll', el) ? null : el;
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
