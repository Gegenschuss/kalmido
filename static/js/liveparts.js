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
function lpLive(v, ch) {
  if (!ch || !ch.length || ch.some(k => !LP_LIGHT.has(k))) return false;
  S.lpN.light++;
  S.v = v;  // the change is known; the state follows bundled
  for (const k of ch) lpAreas.add(k);
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
  if (lpRowSig() !== rows && (S.route.mod === 'tasks' || S.route.mod === 'home')) viewSafeRender();
}
// the full way also counts (measurement); a full load ends a pending light follow-up
function lpFull() { if (lpT) { clearTimeout(lpT); lpT = 0; lpAreas = new Set(); } }
// views a change of someone else must not redraw: the poll's full way skips the view there (the sidebar etc. still follow)
const lpKeepView = () => !S.lpOff && LP_KEEP.has(S.route.mod);
