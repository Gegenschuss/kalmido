/* Kalmido web client: Dates, the client state, the API + offline outbox, edit conflicts, routing.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ dates
const pad = n => String(n).padStart(2, '0');
const ds = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const pd = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const addDays = (s, n) => { const d = pd(s); d.setDate(d.getDate() + n); return ds(d); };
const today = () => ds(new Date());
// weekday / month names + date patterns come from the language file (i18n.js: WD, WDL, MON, MONS, fmtDay), weeks still start on Monday
const WD_MO = () => [1, 2, 3, 4, 5, 6, 0].map(i => WD[i]);  // calendar header, Monday first
const fmtDate = s => pd(s).toLocaleDateString(LOCALE());
const RR_WD = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'];
function dayLabel(s, long) {
  const t = today();
  if (s === t) return tr('Today');
  if (s === addDays(t, 1)) return tr('Tomorrow');
  if (s === addDays(t, -1)) return tr('Yesterday');
  const d = pd(s), diff = (d - pd(t)) / 864e5;
  if (diff > 1 && diff < 7 && long) return WDL[d.getDay()];
  return fmtDay(d.getFullYear() !== new Date().getFullYear() ? 'year' : 'short', d);
}
// 2.6.0 (K07): one way to write a task's date everywhere (rows, the date column, the task panel): "Mo, 5. Okt", a range
// "So, 4. Okt – Mo, 5. Okt", a time after a comma ("Heute, 17:30")
const dueLabel = (t, range = true) => !t.due ? '' : (range && t.start && t.start < t.due ? dayLabel(t.start) + ' – ' : '') + dayLabel(t.due) + (t.due_time ? ', ' + t.due_time : '');
const dueClass = t => !t.due || t.status ? '' : t.due < today() ? 'over' : t.due === today() ? 'today' : '';
// 2.16.0 (#473, WCAG 1.4.1): the priority as a shape too (! / !! / !!!, like the quick add), named for screen readers
const PRIO_NAME = {5: N_('High priority'), 3: N_('Medium priority'), 1: N_('Low priority')};
const prioWord = p => tr({5: N_('High'), 3: N_('Medium'), 1: N_('Low')}[p] || N_('None'));
const prioMark = p => PRIO_NAME[p] ? `<span class="prm p${p}" role="img" aria-label="${esc(tr(PRIO_NAME[p]))}" title="${esc(tr(PRIO_NAME[p]))}">${{5: '!!!', 3: '!!', 1: '!'}[p]}</span>` : '';
// timeline, roadmap, statistics and time reports use weekStartOf (the locale's first weekday, 1.5.1); habits keep Mondays
function mondayOf(s) { const d = pd(s); const k = (d.getDay() + 6) % 7; d.setDate(d.getDate() - k); return ds(d); }

// a date without its weekday in the language's own short pattern ("4. Okt" / "Oct 4"), with the year if it is not this one
const dayNoWd = (d, year) => fmtDay(year ? 'year' : 'short', d).replace(/^[^\d{]*?(?=\d|[A-Za-zÀ-ÿ]+\s\d)/, '').replace(/^\s*[,.]\s*/, '');
function weekTitle(first) {
  const a = pd(first), b = pd(addDays(first, 6)), y = new Date().getFullYear(), other = a.getFullYear() !== y || b.getFullYear() !== y;
  return `${dayNoWd(a, other && a.getFullYear() !== b.getFullYear())} – ${dayNoWd(b, other)} · ${tr('Week {0}', isoWeek(addDays(first, 3)))}`;
}
// ------------------------------------------------------------------ state
const S = {
  lists: [], sections: [], tasks: new Map(), habits: [], pomo: null, pomoToday: {count: 0, minutes: 0},
  settings: {}, counts: {}, v: 0, ntfyUrl: 'https://ntfy.sh', me: null,
  route: {mod: 'tasks', key: 'inbox'}, sel: null, extra: null,
  collapsed: new Set(LS.get('collapsed', []).filter(x => x !== 'side:arch-open')),  // 1.6.1: the archive fold is gone
  calMonth: null, calSel: today(), quick: {ignore: new Set()},
  filters: [], multi: new Set(), multiMode: false, occ: {key: '', items: []}, cal: {key: '', loading: '', items: [], subs: {}, evcals: {}}, calendars: {enabled: false, subs: 0},
  calMode: LS.get('calMode', 'month'), tlStart: null, quickPreset: {}, editContent: false,
  tl: {id: null}, drafts: {}, cfiles: {}, cedit: null, editLink: false,  // comments timeline of the open task
};
const FEATS = [['cal', N_('Calendar')], ['timeline', N_('Timeline')], ['matrix', N_('Eisenhower matrix')], ['habits', N_('Habits')], ['pomo', N_('Focus timer')], ['kanban', N_('Kanban')], ['collab', N_('Collaboration')], ['stats', N_('Statistics')], ['time', N_('Time tracking')], ['progress', N_('Project progress')], ['deps', N_('Dependencies')], ['fields', N_('Custom fields')], ['agents', N_('Agents')], ['comments', N_('Comments')], ['family', N_('Family')], ['events', N_('Events')], ['contacts', N_('Contacts')],
  // 2.22.0 (#663): Home & life, each off by default
  ['contracts', N_('Contracts')], ['home', N_('Home & devices')], ['care', N_('Staying in touch')], ['health', N_('Health')], ['review', N_('Review & journal')], ['travel', N_('Travel')], ['reading', N_('Read later')],
  // 2.23.0 (#463): package "Team, family, clients", each off by default
  ['clients', N_('Clients')], ['workload', N_('Workload')], ['forms', N_('Forms')]];
const FEAT_DESC = {deps: N_('“Blocked by” in the task details, arrows and linking in the timeline, what is stuck in the project status, a notice when a task is unblocked'),
  fields: N_('Own fields per list (text, number, selection, date, person, link), as columns and in the task details'),collab: N_('Comments, activity history, @mentions, News, sharing lists and assigning tasks'), stats: N_('Completed tasks, on-time rate, overdue trend, focus time and habit streaks'),
  time: N_('Timer on tasks, manual entries, reports per list and task, CSV export and a printable timesheet'),
  clients: N_('Clients above the lists: contact, hourly rate, budget in hours or money, estimate vs. actual and the timesheet per client and month (only within your organisation)'),
  workload: N_('How much each person of your organisation has on their plate per week, against their hours per week'),
  forms: N_('A link with a small form (requests, bug reports) that creates a task in a list; agents can sort it in'),
  agents: N_('A tab with the agents (AI assistants, bots) you share lists with: their status, jobs to approve and the chat'),
  progress: N_('Progress bar in the list header and the project status (“Where is it stuck?”); with collaboration also a status per list')};
const feat = f => (S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').includes(f);
// collaboration off (own switch, or the admin's switch for the whole server): no comments / activity / mentions /
// sharing / assigning in the UI (data stays; with the server switch off the API refuses them too)
const collab = () => feat('collab') && S.collabAll !== false;
// 2.0.6 (#315): comments are a module of their own (personal notes); mentions, activity, reactions and the typing
// indicator only where people work together: collaboration on and the task's list shared
const cmtOn = () => feat('comments');
const cmSocial = t => !!t && collab() && !!listById(t.list_id)?.shared;
// outside shared lists only the changes someone else made show between the notes (API tokens, the public link, a list
// that was shared before); my own changes there are noise
const tlForeign = t => !!t && collab() && S.tl.id === t.id ? (S.tl.activity || []).filter(a => (S.me && a.user_id !== S.me.id) || a.data?.via) : [];
// admins: a newer release was found by the server's daily update check (dot on the settings gear)
const updDot = () => !!(S.me?.is_admin && S.about?.available);
// module views: tasks always, News with the collaboration module, the overview with "progress" (see overviewOn), the rest by their own switch
const modOn = m => m === 'tasks' || m === 'home' || m === 'notes' || (m === 'team' ? teamOn() : m === 'agents' ? agentsTab() : m === 'news' ? collab() : m === 'overview' ? overviewOn() : m === 'time' ? timeOn() : m === 'family' ? feat(m) || !!S.me?.kid : m === 'life' ? lifeOn() : m === 'workload' ? workloadOn() : feat(m));
// no "+" button on views without tasks
// views of the tasks module that are not a task list (no quick add, no selection, no open-count)
const NOLIST_KEYS = ['done', 'trash', 'search', 'archived'];
// 2.0.6 (#188): tablets in portrait (phone layout, but >= 600 x 600 px) get the docked composer of the desktop instead of
// the "+" button wherever a view has one; phones keep the "+"
// 2.19.0 (#669, a regression of 2.7.2): the tablet layout with the docked "Add task" bar (600-899 px wide, 600 px high) is
// decided on the height WITHOUT the on-screen keyboard. With interactive-widget=resizes-content the keyboard shrinks the
// layout height below 600 px (an unfolded Fold in portrait), the bar flipped to the phone layout, was hidden and took
// the focus (and the keyboard) with it. The height is taken while nothing is being typed, or when the width changes.
const TD = {on: null, w: -1};
function tdockSync() {
  if (TD.on === null || innerWidth !== TD.w || !editFocused()) { TD.on = matchMedia('(min-width:600px) and (min-height:600px)').matches; TD.w = innerWidth; }
  const on = isMobile() && TD.on;
  document.documentElement.classList.toggle('tdock', on);
  return on;
}
const tabletDock = () => tdockSync();
window.addEventListener('resize', tdockSync);
tdockSync();
// 2.19.0 (#669): typing in the docked "Add task" bar (it sticks to the bottom of the scrolling list) must not move the
// list. Chrome reveals the caret of a sticky field by scrolling its scroll container, a line per key on a short visible
// area (Fold unfolded with the keyboard up). The list's position is taken before each key and put back right after.
const QS = {top: null, at: 0};
document.addEventListener('beforeinput', e => {
  if (e.target?.id !== 'qinput' || !e.target.closest('.qdock')) return;
  const v = document.getElementById('view'); if (v) { QS.top = v.scrollTop; QS.at = Date.now(); }
}, true);
document.addEventListener('scroll', e => {
  const v = document.getElementById('view');
  if (e.target !== v || QS.top == null || Date.now() - QS.at > 400 || document.activeElement?.id !== 'qinput') return;
  if (Math.abs(v.scrollTop - QS.top) > 1) v.scrollTop = QS.top;
}, true);
const noFab = () => ['habits', 'pomo', 'news', 'stats', 'time', 'overview', 'agents', 'team', 'notes', 'family', 'contacts', 'life', 'review', 'clients', 'workload'].includes(S.route.mod) || NOLIST_KEYS.includes(S.route.key) || isOverview();
// package 3: progress bar / overview (switch "progress"), project status (+ collaboration), custom fields, dependencies
// 2.13.0 (#453, Fold screenshots): the round + only on phones; tablets / an unfolded Fold add with the docked "Add task"
// bar or, in views without it (calendar, Kanban, timeline), the header's "New task" button
const dockView = () => S.route.mod === 'tasks' && !isKanban() && !isTimeline() && !isRoadmap() && !isOverview() && !noFab();
const fabOff = () => noFab() || (isTouch() && (!isMobile() || tabletDock()));
const progressOn = () => feat('progress');
const statusOn = () => progressOn() && collab();
// "Where is it stuck?" only pays off with several projects: 2+ active lists, or a shared list
const overviewOn = () => progressOn() && (S.lists.filter(l => !l.is_inbox && !l.archived && l.kind === 'project').length >= 2 || (collab() && S.lists.some(l => l.shared && !l.archived && l.kind === 'project')));
// modules "deps" / "fields" (1.2): off = hidden in the app, the data and the API stay
const depsOn = () => feat('deps');
const fieldsOn = () => feat('fields');
// list type (1.2): list | checklist | project. Time tracking, dependencies, custom fields and progress / status only
// show in project lists, and only while their module is on (the module stays the outer switch)
const isProject = lid => listById(lid)?.kind === 'project';
const tFor = t => !!t && timeOn() && isProject(t.list_id);    // time tracking for this task
const dFor = t => !!t && depsOn() && isProject(t.list_id);    // dependencies for this task
const progressFor = l => !!l && progressOn() && l.kind === 'project';
const statusFor = l => !!l && statusOn() && l.kind === 'project';
const fieldsAll = lid => (S.fields || []).filter(f => f.list_id === lid).sort((a, b) => a.sort - b.sort || a.id - b.id);
const fieldsOf = lid => !fieldsOn() || !isProject(lid) ? [] : (S.fields || []).filter(f => f.list_id === lid).sort((a, b) => a.sort - b.sort || a.id - b.id);
const fieldById = id => (S.fields || []).find(f => f.id === id);
const inbox = () => S.lists.find(l => l.is_inbox);
const listById = id => S.lists.find(l => l.id === id);
// sharing: role of the logged-in user in a list. 1.10.0: owner | admin | edit ("Member") | participant | view ("Viewer").
// admin / edit change the whole list; a participant sees and changes only the tasks assigned to them (the server sends
// no others) and may add tasks there; the parents of their subtasks come as read-only context (t.context).
const WRITE_ROLES = ['owner', 'admin', 'edit'];
const listRole = id => listById(id)?.role || 'owner';
const canEditList = id => WRITE_ROLES.includes(listRole(id));              // sections, moving tasks in, list-wide actions
const isPart = id => listRole(id) === 'participant';
const canAddTo = id => canEditList(id) || isPart(id);                     // new tasks (a participant's become theirs)
const canEdit = t => !!t && (canEditList(t.list_id) || (isPart(t.list_id) && !t.context));
// 2.36.0 (#1118): the lock of a task (t.locked = 1, stored at the server, the same on every device and for everybody sharing
// the list). Locked: title, notes, date / time, priority, list, tags, repeat, assignee; free: comments, checkboxes in the
// notes, completing / reopening, subtasks, sort order, pin. Whoever may change the task may lock / unlock it. tlkHits =
// would this change touch a locked field (checkbox ticks are no change of the notes); api() stops such a write with the
// hint + "Unlock", the openers (date, priority, assign, move, title, notes) stop before anything opens (tlkStop).
const TLK_FIELDS = ['title', 'content', 'due', 'due_time', 'start', 'priority', 'list_id', 'repeat', 'repeat_from', 'assignee_id', 'assignee_group_id', 'rotation', 'tags', 'add_tags', 'ltags'];
const tlkIs = t => !!t && !!t.locked;
const tlkCb = s => String(s || '').replace(/^(\s*(?:[-*+]|\d+[.)])\s+\[)[ xX](\])/gm, '$1 $2').trimEnd();
const tlkSet0 = a => JSON.stringify([...(a || [])].map(x => String(x).toLowerCase()).sort());
function tlkHits(t, b) {
  if (!tlkIs(t) || !b || typeof b !== 'object' || ('locked' in b && !b.locked)) return false;
  const n = x => x === '' || x === undefined ? null : x;
  return TLK_FIELDS.some(k => {
    if (!(k in b)) return false;
    const v = b[k];
    if (k === 'content') return tlkCb(v) !== tlkCb(t.content);
    if (k === 'list_id') return !!v && +v !== +t.list_id;
    if (k === 'tags') return tlkSet0(v) !== tlkSet0(t.tags);
    if (k === 'ltags') return tlkSet0(v) !== tlkSet0(t.ltags);
    if (k === 'add_tags') return (v || []).some(x => !(t.tags || []).includes(x));
    return String(n(v)) !== String(n(t[k]));
  });
}
function tlkToast(t) { toast(tr('This task is locked. Unlock it to change it.'), () => tlkSet(t.id, false), 6000, tr('Unlock')); }
const tlkStop = t => { if (!tlkIs(t) || !canEdit(t)) return false; tlkToast(t); return true; };
async function tlkSet(id, on) {
  const t = taskById(id); if (!t || !(t.id > 0)) return;
  if (!canEdit(t)) { roToast(); return; }
  await patchUndoable(id, {locked: on ? 1 : 0}, on ? tr('Task locked') : tr('Task unlocked'));
}
// the safety net in api(): a write of the app that would change a locked field is not sent (the server refuses it too)
function tlkGuard(method, url, body) {
  if (method === 'GET' || !body || typeof body !== 'object' || body instanceof FormData) return null;
  const pm = method === 'PATCH' && url.match(/^\/api\/tasks\/(\d+)$/);
  let hit = null;
  if (pm) { const t = S.tasks.get(+pm[1]); if (tlkHits(t, body)) hit = t; }
  else if (url === '/api/tasks/batch' && (body.action === 'patch' || body.action === 'patch_each')) {
    hit = (body.ids || []).map(i => S.tasks.get(+i)).find(t => tlkHits(t, body.action === 'patch' ? body.data : (body.data?.items || {})[t?.id]));
  } else if (url === '/api/tasks/reorder') {
    hit = (body.items || []).map(it => [S.tasks.get(+it.id), it]).find(([t, it]) => tlkHits(t, Object.fromEntries(Object.entries(it).filter(([k]) => ['list_id', 'priority', 'due', 'start', 'due_time'].includes(k)))))?.[0];
  }
  if (!hit) return null;
  tlkToast(hit);
  const e = new Error(tr('This task is locked. Unlock it to change it.')); e.shown = true; e.locked = true;
  return e;
}
const canManage = l => !!l && ['owner', 'admin'].includes(l.role || 'owner');  // members + roles
const canAssign = t => !!t && collab() && canEditList(t.list_id);
const isOwner = l => !l || !l.role || l.role === 'owner';
const hasSharing = () => collab() && S.lists.some(l => l.shared);
const listPeople = l => !l ? [] : [{user_id: l.owner_id, name: l.owner_name || S.me?.display_name || '', role: 'owner'}, ...(l.members || [])];
const personName = (lid, uid) => listPeople(listById(lid)).find(p => p.user_id === uid)?.name || '';
const initials = n => String(n || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase() || '?';
// 1.9.0 profile pictures: S.avatars = {user id: URL} (me + everybody sharing a list with me, from /api/state; the News
// answer adds its people). av() = the round picture, or the initials as before. cls/attrs: the caller's classes + title.
const avUrl = id => (id && ((S.avatars || {})[id] || (S.me && +id === S.me.id ? S.me.avatar : ''))) || '';
function av(id, name, cls = 'avatar', attrs = '', inner = '') {
  const u = avUrl(id), ag = id ? agentDot(id) : '';  // 2.0.0: agents get a status dot
  if (ag || (id && isAgentUser(id))) { cls += ' agent'; inner += ag + botBadge(); }  // 2.28.0 (#985): + the robot badge
  return `<span class="${cls}${u ? ' pic' : ''}" ${attrs}>${u ? `<img src="${esc(u)}" alt="" loading="lazy" decoding="async" draggable="false">` : esc(initials(name))}${inner}</span>`;
}
// 2.7.2 (#418): a person's picture as a button: a tap / click opens the person card (agents: status, chat, current task;
// people: their tasks, mention). The capture handler below takes the click before the row / dialog under it.
const avBtn = (id, name, cls = 'avatar', attrs = '') => id ? `<button type="button" class="avb" data-mcard="${+id}" data-mname="${esc(name || '')}" aria-haspopup="dialog" title="${esc(tr('Show {0}', name || '?'))}" aria-label="${esc(tr('Show {0}', name || '?'))}">${av(id, name, cls, attrs)}</button>` : av(id, name, cls, attrs);
function personNameAny(id) {
  id = +id;
  if (S.me && S.me.id === id) return S.me.display_name;
  const a = agentById(id); if (a) return a.name;
  for (const l of S.lists) { const p = listPeople(l).find(x => x.user_id === id); if (p?.name) return p.name; }
  return '';
}
function roToast() {  // participants: their role, not "view only", keeps them from the change
  const k = S.route.key, lid = k.startsWith('l:') ? +k.slice(2) : taskById(S.sel)?.list_id;
  toast(lid && isPart(lid) ? tr('Your role in this shared list does not allow this change') : tr('View only: you cannot change this shared list'));
}
// 2.17.0 (#649): children by parent from an index built once per tick (was a scan of every task per call: a view with
// thousands of rows took seconds, "All" with 20 000 tasks minutes). The index is dropped after the current task (a
// change to S.tasks is seen by the next render) and whenever the task map is replaced.
let _kidsIx = null, _kidsMap = null;
function kidsIndex() {
  if (_kidsIx && _kidsMap === S.tasks) return _kidsIx;
  const ix = new Map();
  for (const t of S.tasks.values()) if (t.parent_id) { const a = ix.get(t.parent_id); if (a) a.push(t); else ix.set(t.parent_id, [t]); }
  for (const a of ix.values()) a.sort(bySort);
  _kidsIx = ix; _kidsMap = S.tasks;
  setTimeout(() => { _kidsIx = null; }, 0);
  return ix;
}
const children = id => (kidsIndex().get(id) || []).slice();
const bySort = (a, b) => a.sort - b.sort || a.id - b.id;
// 1.5.1: the tasks of an archived list are hidden everywhere except in that list itself (Today, Tomorrow, Next 7 days,
// counts, Assigned, filters, tags, calendar, matrix, overview); unarchiving brings them back
const archivedTask = t => !!t && !!listById(t.list_id)?.archived;
const archHidden = t => archivedTask(t) && !(S.route.mod === 'tasks' && S.route.key === 'l:' + t.list_id);
// ctx: include the read-only context parents of a participant's subtasks (only the list view shows them, above their subtask)
function openTasks(ctx = false) { return [...S.tasks.values()].filter(t => t.status === 0 && !archHidden(t) && !wsHidden(t) && (ctx || !t.context)); }  // 2.28.0 (#935): + the workspace

// ------------------------------------------------------------------ api + offline outbox
// While offline, task/habit writes are applied locally and queued (localStorage outbox); on reconnect
// they are replayed in order (last write wins, `_prev` detects edits made elsewhere). Tasks created
// offline get a negative temp id that is mapped to the real id during replay. The last server state is
// cached for offline start. Every queued op carries the user id: ops of another user are never replayed.
class Offline extends Error {}
const OUT = {q: LS.get('outbox', []), online: true, flushing: false};
// 2.21.0 (#673): before the first render there is no top bar to update (renderTop on an empty state threw, so a start while
// the server was down showed the error page instead of the cached data); the boot's render shows the state
function setOnline(b) { if (OUT.online !== b) { OUT.online = b; if (S.booted) renderTop(); if (b) flush(); setTimeout(() => typeof staleDraw === 'function' && staleDraw(), 0); } }
// 2.13.4 (p210 flake, a real race): every write counts up when it starts and when it ends (S.wseq), so load() can tell that
// a write finished while its GET /api/state was on the way: that answer may predate the write and would undo it locally
// (S.settings went back to the old value; an Undo right after then saw "changed elsewhere" and skipped the step)
async function rawFetch(method, url, body) {
  if (method === 'GET') return rawFetch0(method, url, body);
  S.wseq = (S.wseq || 0) + 1;
  try { return await rawFetch0(method, url, body); } finally { S.wseq++; }
}
async function rawFetch0(method, url, body) {
  const opt = {method, headers: {'X-Requested-With': 'kalmido'}, redirect: 'manual'};
  const dev = wpDevHeader(url); if (dev) opt.headers['X-Kalmido-Device'] = dev;
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  let r;
  try { r = await fetch(url, opt); } catch { const ch = OUT.down; OUT.down = false; setOnline(false); if (ch && S.booted) renderTop(); throw new Offline('offline'); }
  // 2.21.0 (#673): the device is online but the server is not (a proxy answers 502 / 503 / 504 without Kalmido's JSON): the
  // same as offline (cached data, changes wait), the hint says "server not reachable"; never a reload loop on a proxy page
  // 2.24.0 (#907): 503 (the proxy's maintenance page) or a notice of the kind "maintenance": "server in maintenance"
  if ([502, 503, 504].includes(r.status) && !(r.headers.get('content-type') || '').includes('application/json')) { const ch = !OUT.down; OUT.down = true; OUT.maint = r.status === 503 || S.announce?.level === 'maintenance'; setOnline(false); if (ch && S.booted) renderTop(); throw new Offline('down'); }
  if (OUT.down) { OUT.down = false; if (S.booted && !OUT.online) renderTop(); }
  setOnline(true);
  if (r.type === 'opaqueredirect' || (r.headers.get('content-type') || '').includes('text/html')) {
    location.reload();  // login session expired -> login page
    throw new Error('auth');
  }
  const j = await r.json().catch(() => ({}));
  if ((r.status === 401 || r.status === 403) && j.auth) { authScreen(j); throw new Error('auth'); }  // built-in login
  if (r.status === 401) { location.reload(); throw new Error('auth'); }
  if (!r.ok) { const e = new Error(j.error || tr('Error {0}', r.status)); e.status = r.status; e.data = j;
    if (j.code === 'quota_exceeded') { e.shown = true; setTimeout(() => quotaDialog(j), 0); }  // 2.24.0 (#910): storage full
    if (j.code === 'agent_bridge') e.shown = true;  // 2.30.0 (#919): bridgeTry asks and repeats it
    throw e; }
  return j;
}
const queueable = (method, url) => method !== 'GET' && /^\/api\/(tasks|habits\/\d+\/log|time\/(start|stop|entries))/.test(url) && !/\/(comments|seen|timeline)$/.test(url);
// 2.25.0 (UX-56): a write of the open task that reached the server shows "Saved" in its header for a moment
function savedPing() {
  const top = S.sel && $('#detail .dtop'); if (!top) return;
  let el = $('.dsaved', top);
  if (!el) { el = document.createElement('span'); el.className = 'dsaved'; el.setAttribute('role', 'status'); (top.querySelector('.spacer') || top.lastElementChild).after(el); }
  el.innerHTML = `${ic('check', 's')}<span>${esc(tr('Saved'))}</span>`; el.classList.add('on');
  clearTimeout(savedPing.t); savedPing.t = setTimeout(() => el.classList.remove('on'), 1600);
}
async function api(method, url, body) {
  const lk = tlkGuard(method, url, body); if (lk) throw lk;  // 2.36.0 (#1118)
  if (queueable(method, url) && !(body instanceof FormData) && OUT.q.length) return enqueue(method, url, body);
  try { const j = await rawFetch(method, url, body); if (method !== 'GET' && S.sel && new RegExp(`^/api/tasks/${S.sel}(/|$)`).test(url)) savedPing(); return j; }
  catch (e) {
    if (e instanceof Offline) {
      if (queueable(method, url) && !(body instanceof FormData)) return enqueue(method, url, body);
      if (method !== 'GET') toast(tr('Offline: only works again with a connection'));
    } else if (e.message !== 'auth' && !e.shown) toast(e.message);
    throw e;
  }
}
function enqueue(method, url, body) {
  // remember what this device saw before the edit, so the server can detect edits made elsewhere
  const pm = method === 'PATCH' && url.match(/^\/api\/tasks\/(-?\d+)$/);
  if (pm && body && !body._prev && +pm[1] > 0) {
    const t = S.tasks.get(+pm[1]);
    if (t) body = {...body, _prev: Object.fromEntries(Object.keys(body).filter(k => !k.startsWith('_')).map(k => [k, k === 'tags' ? [...(t.tags || [])] : (t[k] ?? null)]))};
  }
  // 2.13.0 (#453): typed text waiting in the outbox is coalesced: a newer title / description of the same task replaces
  // the queued one (which keeps its _prev = the base the server last confirmed), so a replay sends only the latest text
  const tk = pm && body ? Object.keys(body).filter(k => !k.startsWith('_')) : [];
  if (tk.length === 1 && (tk[0] === 'title' || tk[0] === 'content')) {
    const q = OUT.q.find((x, i) => (i > 0 || !OUT.flushing) && x.method === 'PATCH' && x.url === url && !x.done && Object.keys(x.body || {}).filter(k => !k.startsWith('_')).join() === tk[0]);
    if (q) { q.body = {...q.body, [tk[0]]: body[tk[0]]}; LS.set('outbox', OUT.q); return applyLocal({method, url, body}); }
  }
  const e = {method, url, body, uid: S.me?.id};
  if (method === 'POST' && url === '/api/tasks') e.tmp = -Date.now() - Math.floor(Math.random() * 1000);
  OUT.q.push(e); LS.set('outbox', OUT.q);
  renderTop();
  if (OUT.online) setTimeout(flush, 50);
  const r = applyLocal(e);
  if (r && typeof r === 'object') Object.defineProperty(r, '_q', {value: e, configurable: true});  // for undo (see HIST)
  return r;
}
function applyLocal(e) {
  const {method, url, body = {}} = e;
  const m = url.match(/^\/api\/tasks\/(-?\d+)(?:\/(\w+))?/);
  const nowIso = new Date().toISOString();
  if (url.startsWith('/api/time/')) return timeLocal(e);
  if (method === 'POST' && url === '/api/tasks') {
    const par = body.parent_id && S.tasks.get(body.parent_id);
    const t = {id: e.tmp, list_id: body.list_id || (par ? par.list_id : inbox().id), section_id: body.section_id ?? null, parent_id: body.parent_id ?? null,
      title: body.title, content: body.content || '', priority: body.priority || 0, status: 0, due: body.due || null, due_time: body.due_time || null, start: body.start || null,  // 2.18.0 (#431): a range drawn in the timeline offline
      reminders: body.reminders || '', repeat: body.repeat || '', repeat_from: body.repeat_from || 'due', url: body.url || null,
      sort: par ? 1e9 : Math.min(0, ...[...S.tasks.values()].map(x => x.sort)) - 1,
      created_at: nowIso, updated_at: nowIso, completed_at: null, deleted_at: null, tags: body.tags || [], fields: body.fields || {}, blocked: 0, blockers: [], blocking: 0,
      ...(body.ms ? {ms: 1} : {}), ...(body.milestone_id ? {milestone_id: body.milestone_id} : {})};  // 2.18.0 (#430)
    S.tasks.set(t.id, t); return t;
  }
  if (url === '/api/tasks/batch') {
    for (const tid of body.ids || []) {
      const t = S.tasks.get(tid); if (!t) continue;
      if (body.action === 'patch') { const {add_tags, ...d} = body.data || {}; Object.assign(t, d); if (add_tags) t.tags = [...new Set([...t.tags, ...add_tags])]; }
      if (body.action === 'complete') { t.status = body.data?.status ?? 2; t.completed_at = nowIso; }
      if (body.action === 'reopen') { t.status = 0; t.completed_at = null; }
      if (body.action === 'patch_each' && body.data?.items?.[tid]) {
        const {_prev, fields, ...b} = body.data.items[tid]; Object.assign(t, b);
        if (fields) { t.fields = {...(t.fields || {})}; for (const [k, v] of Object.entries(fields)) { if (v == null || v === '') delete t.fields[k]; else t.fields[k] = String(v); } }
      }
      if (body.action === 'delete') S.tasks.delete(tid);
    }
    return {ok: true};
  }
  if (url === '/api/tasks/reorder') { for (const it of body.items || []) { const t = S.tasks.get(it.id); if (t) Object.assign(t, it); } return {ok: true}; }
  if (m) {
    const t = S.tasks.get(+m[1]);
    if (method === 'DELETE') { S.tasks.delete(+m[1]); return {ok: true}; }
    if (!t) return {ok: true};
    if (method === 'PATCH') {
      const {_prev, fields, ...b} = body; Object.assign(t, b); if ('due' in b && !b.due) t.due_time = null;
      if (fields) { t.fields = {...(t.fields || {})}; for (const [k, v] of Object.entries(fields)) { if (v == null || v === '' || v === false) delete t.fields[k]; else t.fields[k] = v === true ? '1' : String(v); } }
    }
    if (m[2] === 'complete') { t.status = body.status ?? 2; t.completed_at = nowIso; }
    if (m[2] === 'reopen') { t.status = 0; t.completed_at = null; }
    return {...t, next_due: null};
  }
  return {ok: true};  // habit log: caller already updated S.habits
}
async function flush() {
  if (OUT.flushing || !OUT.q.length) return;
  OUT.flushing = true;
  netDotDraw();  // 2.31.0 (#378): yellow while the changes go out
  const fix = v => (typeof v === 'number' && v < 0 && idmap[v]) ? idmap[v] : v;
  const idmap = LS.get('idmap', {});
  let dropped = 0, skipped = 0, sent = 0;
  try {
    while (OUT.q.length) {
      const e = OUT.q[0];
      if (e.uid && S.me && e.uid !== S.me.id) { OUT.q.shift(); LS.set('outbox', OUT.q); continue; }  // another user's op
      const url = e.url.replace(/\/(-\d+)(?=\/|$)/, (_, n) => '/' + (idmap[n] || n));
      let body = e.body;
      if (body && body.parent_id) body = {...body, parent_id: fix(body.parent_id)};
      if (body && body.task_id) body = {...body, task_id: fix(body.task_id)};
      if (body && body.items) body = {...body, items: body.items.map(it => ({...it, id: fix(it.id)}))};
      if (body && body.ids) body = {...body, ids: body.ids.map(fix)};
      if (body && body.data && typeof body.data === 'object') {  // history steps: per task maps keyed by id
        const d = {...body.data};
        for (const k of ['items', 'expect', 'guard']) if (d[k] && !Array.isArray(d[k])) d[k] = Object.fromEntries(Object.entries(d[k]).map(([id, v]) => [fix(+id), v]));
        body = {...body, data: d};
      }
      try {
        const j = await rawFetch(e.method, url, body);
        sent++;
        if (e.tmp) { idmap[e.tmp] = j.id; HIST.ids[e.tmp] = j.id; LS.set('idmap', idmap); if (S.sel === e.tmp) S.sel = j.id; }
        if (j && j.conflicts?.length) {
          // 2.13.0: a "conflict" with a text this device sent itself (its answer got lost) is replayed on top of it
          const own = j.conflicts.filter(c => ownVal(j.id + ':' + c.field, c.server) && body && c.field in body);
          if (own.length === j.conflicts.length && !e.rebased) { e.rebased = true; e.body = {...body, _prev: Object.fromEntries(own.map(c => [c.field, c.server]))}; continue; }
          addConflicts(j.id, j.conflicts, j.title);
        }
        if (j && j.skipped) skipped++;
        e.res = j;
      } catch (err) {
        if (err instanceof Offline || err.message === 'auth') { if (err instanceof Offline) flushSoon(); return; }  // 2.25.0 (UX-55): try again in 2 s
        console.warn('outbox: dropped', e, err);  // e.g. 404: deleted on another device
        dropped++; e.res = null;
      }
      e.done = true;
      OUT.q.shift(); LS.set('outbox', OUT.q);
    }
    LS.set('idmap', {});
  } finally {
    OUT.flushing = false;
    if (sent && !OUT.q.length && globalThis.document) { S.syncOk = Date.now(); staleDraw(); }  // 2.25.0 (UX-55): the "waiting" chip goes at once
    renderTop();
    if (sent && !OUT.q.length && !dropped && !skipped) savedChip();
    if (dropped) setTimeout(() => toast(trn('{0} offline change not applied (task deleted or invalid)', '{0} offline changes not applied (task deleted or invalid)', dropped)), 400);
    else if (skipped) setTimeout(() => toast(tr('Recurring task was already checked off, not advanced twice')), 400);
  }
  await load(); render();
}
window.addEventListener('online', () => flush());
// 2.25.0 (UX-55): after waiting changes went out: "All saved ✓" for a moment where the "waiting" chip was (not as a toast,
// which would push away an Undo that is still on screen)
function savedChip() {
  let el = $('#savedok');
  if (!el) { el = document.createElement('div'); el.id = 'savedok'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
  el.innerHTML = `${ic('check', 's')}<span>${esc(tr('All saved'))}</span>`; el.classList.add('on');
  clearTimeout(savedChip.t); savedChip.t = setTimeout(() => el.classList.remove('on'), 2500);
}
// 2.31.0 (#378): the own connection as a small dot at the own picture (sidebar / drawer, desktop and phone): green online,
// grey offline (with the number of waiting changes), yellow while changes go out. The colour is never the only sign: the dot
// and the picture's button carry the state as text (aria-label, tooltip), the account menu shows it as its first line.
function netState() {
  const q = OUT.q.length;
  if (!OUT.online) return {k: 'off', label: [OUT.down ? (OUT.maint ? tr('Server in maintenance') : tr('Server not reachable')) : tr('Offline'), q ? trn('{0} change waiting', '{0} changes waiting', q) : ''].filter(Boolean).join(' · ')};
  if (q || OUT.flushing) return {k: 'sync', label: tr('Syncing')};
  return {k: 'on', label: tr('Online')};
}
const netDotHtml = () => { const n = netState(); return `<span class="netdot n-${n.k}" role="img" aria-label="${esc(n.label)}" title="${esc(n.label)}"></span>`; };
const acctLabel = () => tr('Account') + ': ' + (S.me?.display_name || '') + ' · ' + netState().label;
function netDotDraw() {
  if (!globalThis.document) return;
  const n = netState();
  for (const d of $$('.sbacct .netdot')) { d.className = 'netdot n-' + n.k; d.setAttribute('aria-label', n.label); d.title = n.label; }
  for (const b of $$('.sbacct')) { b.setAttribute('aria-label', acctLabel()); b.title = acctLabel(); }
}
// 2.25.0 (UX-55): while changes wait, the server is asked again every 2 s (not only on the 4 s poll)
function flushSoon() { if (flushSoon.t) return; flushSoon.t = setTimeout(() => { flushSoon.t = null; if (globalThis.document && OUT.q.length && !document.hidden) flush(); }, 2000); }

// ------------------------------------------------------------------ conflicts (edited here and elsewhere)
S.conflicts = LS.get('conflicts', []);
const FIELD_NAMES = {ttype: N_('Type'), title: N_('Title'), content: N_('Description'), due: N_('Date'), due_time: N_('Time'), priority: N_('Priority'), list_id: N_('List'), tags: N_('Tags'), reminders: N_('Reminder'), repeat: N_('Repeat'), repeat_from: N_('Repeat from'), start: N_('Start|date'), section_id: N_('Section'), parent_id: N_('Parent task'), pinned: N_('Pinned'), duration: N_('Duration'), url: N_('Link'), deadline: N_('Deadline'), nag: N_('Repeat reminder'), ms: N_('Milestone'), milestone_id: N_('Milestone')};
function addConflicts(tid, list, title) {
  for (const c of list) {
    S.conflicts = S.conflicts.filter(x => !(x.tid === tid && x.field === c.field));
    S.conflicts.push({tid, title: title || S.tasks.get(tid)?.title || '', field: c.field, server: c.server, mine: c.mine, at: Date.now()});
  }
  LS.set('conflicts', S.conflicts);
  renderTop();
  // 2.13.2 (#478 F7): no toast on top of the calm bar under the field (it said the same and covered "Waiting for …")
  setTimeout(() => { if (S.sel === tid && list.every(c => $(`#detail .cfbar[data-f="${c.field}"]`))) return; toast(list.length === 1 ? tr('A field was changed elsewhere in the meantime, please review') : tr('{0} fields were changed elsewhere in the meantime, please review', list.length)); }, 300);
}
// the calm bar under a field that was changed elsewhere while it was being edited (2.13.0)
function cfInline(id, field, c, mine) {
  const el = $(field === 'title' ? '#d-title' : '#d-content'); if (!el || !c) return;
  el.parentElement.querySelector(`.cfbar[data-f="${field}"]`)?.remove();
  const b = document.createElement('div'); b.className = 'cfbar'; b.dataset.f = field; b.setAttribute('role', 'status');
  b.innerHTML = `<span>${esc(tr('Changed elsewhere in the meantime'))}</span><button type="button" class="btn sm" data-cfi="mine">${tr('Keep mine')}</button><button type="button" class="btn sm" data-cfi="other">${tr('Show the other')}</button>${field === 'content' ? `<button type="button" class="btn sm" data-cfi="merge">${tr('Merge')}</button>` : ''}`;
  el.after(b);
  const done = () => { b.remove(); S.conflicts = S.conflicts.filter(x => !(x.tid === id && x.field === field)); LS.set('conflicts', S.conflicts); renderTop(); };
  b.addEventListener('mousedown', e => e.preventDefault());  // the field keeps its focus (and the keyboard)
  b.addEventListener('click', async e => {
    const a = e.target.closest('[data-cfi]')?.dataset.cfi; if (!a) return;
    const cur = el.value;
    if (a === 'other') { conflictModal(); return; }
    if (a === 'merge') { el.value = cur + (cur.endsWith('\n') ? '' : '\n') + '\n' + String(c.server ?? ''); el.dispatchEvent(new Event('input', {bubbles: true})); }
    const t = taskById(id); if (t) t[field] = c.server;  // the other version is now the base of the next save
    saveTimers[id + ':' + field] && clearTimeout(saveTimers[id + ':' + field].t);
    saveTimers[id + ':' + field] = {t: 0, id, field, value: el.value, base: c.server, sess: HIST.sess};
    done(); await doSave(id + ':' + field, true).catch(() => {});
    if (a !== 'merge') toast(tr('Saved'));
  });
}
function fmtVal(field, v) {
  if (v == null || v === '' || (Array.isArray(v) && !v.length)) return tr('(empty)');
  if (field === 'priority') return tr([N_('None'), N_('Low'), '', N_('Medium'), '', N_('High')][+v] || '') || String(v);
  if (field === 'list_id') return lname(listById(+v)) || String(v);
  if (field === 'due' || field === 'start') return fmtDate(v);
  if (field === 'tags') return v.map(g => '#' + g).join(' ');
  if (field === 'repeat') return repeatLabel(v);
  if (field === 'pinned') return +v ? tr('yes') : tr('no');
  if (field === 'parent_id') return S.tasks.get(+v)?.title || String(v);
  return String(v);
}
function conflictModal() {
  const md = modal(`<h3>${tr('Conflicts')}</h3>
    <div class="muted" style="font-size:var(--fs-m);margin-bottom:.625rem">${tr('These fields were changed on another device while you entered something else here (offline). The other version is saved.')}</div>
    <div id="cf-list"></div>
    <div class="foot"><button class="btn" data-m="all-server">${tr('All: keep the other version')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  const draw = () => {
    $('#cf-list', md).innerHTML = S.conflicts.map((c, i) => `<div class="cfitem"><div class="cfh"><b>${esc(c.title)}</b><span class="muted">${esc(histFieldName(c.field))}</span></div>
      <div class="cfv"><div><span>${tr('saved')}</span>${esc(fmtVal(c.field, c.server))}</div><div><span>${tr('your version')}</span>${esc(fmtVal(c.field, c.mine))}</div></div>
      <div class="cfb"><button class="btn sm" data-cf="server" data-i="${i}">${tr('Keep saved')}</button><button class="btn sm pri" data-cf="mine" data-i="${i}">${tr('Use mine')}</button></div></div>`).join('') || `<div class="muted" style="padding:.625rem 0">${tr('No open conflicts.')}</div>`;
  };
  draw();
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'all-server') { S.conflicts = []; }
    if (b.dataset.cf) {
      const c = S.conflicts[+b.dataset.i];
      if (b.dataset.cf === 'mine') {
        try { const t = await api('PATCH', '/api/tasks/' + c.tid, c.field.startsWith('field:') ? {fields: {[c.field.slice(6)]: c.mine}} : {[c.field]: c.mine}); putTask(t); } catch { return; }
      }
      S.conflicts.splice(+b.dataset.i, 1);
    }
    LS.set('conflicts', S.conflicts); draw(); render();
    if (!S.conflicts.length) setTimeout(() => md.remove(), 300);
  });
}

function applyState(j) {
  if (j.me) {  // another user than last time in this browser: drop everything local of the previous one
    const last = LS.get('uid', null);
    if (last !== null && last !== j.me.id) { clearLocal(); LS.set('uid', j.me.id); location.reload(); throw new Error('auth'); }
    if (last === null) LS.set('uid', j.me.id);
    S.me = j.me;
    const rw = LS.get('rcWarn', null);  // logged in with a recovery code, only a few left
    if (rw !== null) { LS.del('rcWarn'); setTimeout(() => toast(trn('Only {0} recovery code left: create new ones under Settings > Account.', 'Only {0} recovery codes left: create new ones under Settings > Account.', +rw), null, 8000), 1500); }
  }
  S.lists = j.lists; S.inboxNames = j.inbox_names || []; S.sections = j.sections; S.habits = j.habits; S.pomo = j.pomo;
  S.notes = j.notes || []; S.team = j.team || {enabled: false, unread: 0};  // 2.17.0 (#442 #419)
  S.pomoToday = j.pomo_today; S.avatars = j.avatars || {}; S.share = j.share || null; S.settings = j.settings; S.languages = j.languages || [{code: 'en', name: 'English'}]; LS.set('lang', j.settings.lang || 'en'); document.documentElement.lang = j.settings.lang || 'en'; S.counts = j.counts; S.v = j.v; S.ntfyUrl = j.ntfy_url;
  foldSync();  // 2.4.0 (#361): folded folders follow the user (all devices)
  S.tasks = new Map(j.tasks.map(t => [t.id, t]));
  S.filters = j.filters || [];
  S.notify = j.notify || null;  // 2.1.0 (#317) the notification matrix (the server's view)
  S.ntfyInbox = j.ntfy_inbox || {enabled: false};
  S.webpush = j.webpush || {enabled: false};
  S.news = j.news || {unread: 0, sig: ''};
  S.templates = j.templates || [];
  S.timer = j.timer || null; S.timeTotals = j.time_totals || {};
  S.timeLists = j.time_lists || {}; S.timeDayH = +j.time_day_h || 8;  // 2.7.0 (#407)
  S.fields = j.fields || [];
  S.folderOrders = j.folder_orders || {};  // 2.27.0 (#988): the order of other people's folders I see their lists in
  S.folderProps = j.folder_props || {}; S.foldersSharedIn = j.folders_shared_in || [];  // 2.29.0 (#1030 / #929)
  S.collabAll = j.collab_all !== false; S.timeAll = j.time_all !== false; S.about = j.about || {};
  S.calendars = j.calendars || {enabled: false, subs: 0};
  S.api = j.api || {enabled: false}; S.caldav = j.caldav || {enabled: false}; S.webhooks = j.webhooks || {enabled: false}; S.publicLinks = !!j.public_links;
  S.sample = j.sample || null;
  S.agents = j.agents || []; S.agentsAt = Date.now(); S.setupPending = !!j.setup_pending;  // 2.13.0 (#453 A16)
  S.proposers = j.proposers || [];  // 2.3.0: agents I may ask for a proposal
  S.groups = j.groups || []; S.myGroups = j.my_groups || [];  // 2.10.0 (#441)
  S.dayplan = j.dayplan || {work_start: '09:00', work_end: '17:00', review_time: '', default_duration: 30};  // 2.10.0 (#440)
  S.kids = j.kids || []; S.kidIds = new Set(j.kid_ids || []);  // 2.19.0 (#653)
  S.peopleVis = j.people_visibility || 'all';  // 2.22.0 (#752)
  S.instanceMode = j.instance_mode || 'organisation';
  S.workspaces = !!j.workspaces; S.wsMismatches = j.ws_mismatches || {};  // 2.28.0 (#935)
  S.notifAsk = j.notif_ask || [];  // 2.33.0 (#927): the one-time question about notification templates
  S.storage = j.storage || null; S.announce = j.announce || null;  // 2.24.0 (#910 / #907)  // 2.23.0 (#799): organisation | shared | multi
  S.clients = j.clients || [];  // 2.23.0 (#463): the clients I see, with their lists
  if (S.booted && S.route?.mod === 'clients') clReload();  // a change elsewhere: the client's sums again
  if (S.booted && S.route?.mod === 'workload') { WLV.data = null; }
  // 2.21.0 (#659 / #658): event calendars (a changed event refetches the calendar range), address books, links of tasks
  S.evcals = j.evcals || []; S.evlinks = j.evlinks || {}; S.books = j.books || []; S.tcontacts = j.tcontacts || {};
  if (j.evsig !== undefined && j.evsig !== S.evsig) { S.evsig = j.evsig; if (S.booted) calInvalidate(); }
  // language changed on another device: switch once its file is loaded (the boot awaits it itself)
  if (S.booted && (j.settings.lang || 'en') !== I18N.code) i18nLoad(j.settings.lang).then(ok => { if (ok) render(); });
}
async function load() {
  let j;
  try {
    for (let i = 0; i < 3; i++) {  // 2.13.4: an answer that a write overtook is fetched again (see rawFetch)
      const w0 = S.wseq || 0;
      j = await api('GET', '/api/state');
      if ((S.wseq || 0) === w0) break;
    }
  }
  catch (e) {
    if (!(e instanceof Offline)) throw e;
    if (!S.tasks.size) {  // offline start: last cached state + still-queued edits
      const c = LS.get('cache', null); if (!c) throw e;
      applyState(c); OUT.q.forEach(applyLocal);
    }
    return;
  }
  if (OUT.q.length) {  // flush() reloads once the queue is through
    if (!S.tasks.size) { applyState(j); OUT.q.forEach(applyLocal); }
    flush(); return;
  }
  applyState(j);
  LS.set('cache', j);
  if (S.extra) await loadExtra().catch(() => {});
  if (S.sel && (cmtOn() || collab()) && S.tl.id === S.sel && S.tl.v !== S.v) loadTimeline(S.sel);
  if (S.sel && timeOn() && S.te.tid === S.sel && S.te.v !== S.v) loadTaskTime(S.sel);
  if (S.sel && S.dp.id === S.sel && S.dp.v !== S.v) loadDeps(S.sel);
  if (S.chat.aid && collab()) chatLoad();
  if (S.route.mod === 'agents' && S.jobs.items !== null) loadJobs();
  if (typeof staleLoad === 'function') staleLoad(S.route.key === 'stale');  // 2.34.0 (#266): at most every 5 minutes, at once in its view
}
async function loadExtra() {
  const k = S.route.key;
  if (S.route.mod === 'tasks' && (k === 'done' || k === 'trash')) {
    S.extra = (await api('GET', `/api/tasks?scope=${k}`)).tasks;
  } else if (S.route.mod !== 'news' && S.route.mod !== 'time') S.extra = null;  // News / time reports: tasks fetched on demand stay
}
function putTask(t) { S.tasks.set(t.id, t); _kidsIx = null; }

// poll for changes made elsewhere (phone <-> desktop)
setInterval(async () => {
  if (document.hidden) return;
  try {
    if (OUT.q.length) { flush(); staleDraw(); return; }  // 2.13.0 (#453 A13): the chip says how many changes wait
    const {v, n, c, t, ty, app, sp} = await api('GET', '/api/version');
    if (sp !== undefined && sp !== S.stepsSig) { const first = S.stepsSig === undefined; S.stepsSig = sp; if (!first) stepsChanged(); }  // 2.32.0 (#1081)
    verCheck(app);  // 2.27.0 (#968)
    if (ty !== undefined) { const sig = JSON.stringify(ty); if (sig !== S.ctypingSig) { S.ctypingSig = sig; S.ctyping = ty; if (S.sel) agentLive(); } }  // 2.22.0 (#693)
    if (t !== undefined && t !== S.teamSig) { const first = S.teamSig === undefined; S.teamSig = t; if (!first && !editing()) teamChanged(); }  // 2.17.0 (#419)
    if (c !== undefined && c !== S.calSig) {  // calendar subscriptions synced / changed: fetch the shown range again
      const first = S.calSig === undefined; S.calSig = c;
      if (!first && calEvOn() && !editing()) { calInvalidate(); if (S.route.mod === 'cal' || S.route.key === 'today') renderView(); }
    }
    const chg = v !== S.v || (n !== undefined && collab() && n !== S.news?.sig);
    if (chg && !editing()) { S.viewStale = false; await load(); render(); }
    else if (v !== S.v && editing() && S.sel > 0 && (cmtOn() || collab()) && S.tl.id === S.sel && S.tlPollV !== v) { S.tlPollV = v; loadTimeline(S.sel); agentPoll(); }  // 1.9.0
    else if (chg && editing() && S.chat.aid && collab() && S.chatPollV !== `${v}/${n}`) { S.chatPollV = `${v}/${n}`; chatLoad(); agentPoll(); }  // 2.12.2 (#451): typing, the chat still updates (patched)
    else if (S.viewStale && !editing()) viewSafeRender();
    S.syncOk = Date.now(); staleDraw();
  } catch { staleDraw(); /* offline */ }
}, 4000);
// 2.7.2 (#433): instead of a refresh button in the header of shared lists, a small hint once the change check has failed
// for more than 30 s: "Offline – last update N min ago"; a tap tries again (refreshNow). "…" keeps "Refresh".
S.syncOk = Date.now();
// 2.13.0 (#453 A13): offline (or changes not sent yet) is said in words too, not only with the cloud icon: "Offline · 2
// changes waiting"; a tap explains it and tries again
function staleDraw() {
  const age = Date.now() - (S.syncOk || Date.now()), q = OUT.q.length, off = !OUT.online;
  const on = !document.hidden && (age > 30000 || off || (q && age > 8000));
  let el = $('#stale');
  if (!on) { if (el) el.remove(); return; }
  if (!el) { el = document.createElement('button'); el.id = 'stale'; el.type = 'button'; el.setAttribute('role', 'status'); el.addEventListener('click', () => { if (OUT.q.length || !OUT.online) toast(tr('Changes are sent as soon as the server is reachable'), null, 4000); refreshNow().then(staleDraw).catch(() => {}); }); document.body.appendChild(el); }
  const min = Math.floor(age / 60000);
  const txt = off && OUT.down ? (q ? tr('Server not reachable') + ' · ' + trn('{0} change waiting', '{0} changes waiting', q) : tr('Server not reachable – changes are sent later'))
    : (off || age > 30000) ? (q ? tr('Offline') + ' · ' + trn('{0} change waiting', '{0} changes waiting', q) : min < 1 ? tr('Offline – last update less than a minute ago') : trn('Offline – last update {0} min ago', 'Offline – last update {0} min ago', min))
    : trn('{0} change waiting', '{0} changes waiting', q);
  el.innerHTML = `${ic(off ? 'cloudoff' : 'sync', 's')}<span>${esc(txt)}</span>`;
  el.title = tr('Tap to try again');
  // 2.13.2 (#478 F8): with a task open on a phone it sits in the task's header (the keyboard covers the bottom edge)
  const dtop = isMobile() && S.sel ? $('#detail .dtop') : null, host = dtop || document.body;
  if (el.parentElement !== host) { if (dtop) (dtop.querySelector('.spacer') || dtop.lastElementChild).after(el); else host.appendChild(el); }
  el.classList.toggle('indet', !!dtop);
}
// 2.27.0 (#968): the code in the browser vs. the server. index.html carries the version of the code it came with; /api/version
// says what the server runs. Differ they (a window open across an update, a service worker that still served the old code):
// a bar "New version available – Reload"; once nobody types (no field, dialog or unsent change, 20 s without input, or the app
// comes back to the front) it reloads by itself, once per new version. Help shows both versions.
const APP_VER = document.querySelector?.('meta[name="kalmido-version"]')?.content || '';
S.serverVer = '';
let verIdle = Date.now();
for (const t of ['keydown', 'pointerdown', 'input']) document.addEventListener(t, () => { verIdle = Date.now(); }, true);
function verStale() { return !!(APP_VER && S.serverVer && APP_VER !== S.serverVer); }
// text typed but not sent / saved (a comment, a chat message, the quick add) also holds the automatic reload back
const verDraft = () => ['#c-input', '#tc-in', '#chat-in', '#qinput', '#qsheet', '#d-sub'].some(s => ($(s)?.value || '').trim());
const verQuiet = () => !editing() && !editFocused() && !$('.modal') && !$('#pop:not(.hidden)') && !$('.qadd.sheet') && !OUT.q.length && !S.multiMode && !verDraft();
async function verReload() {
  try { if (OUT.q.length) await flush(); } catch { /* offline: the outbox stays in this browser and is sent after the reload */ }
  try { if (typeof flushSaves === 'function') await flushSaves(); } catch { /* nothing waiting */ }
  try { sessionStorage.setItem('kalmido-reloaded', S.serverVer); } catch { /* private mode */ }
  try { const reg = await navigator.serviceWorker?.getRegistration(); await reg?.update(); } catch { /* no service worker */ }
  location.reload();
}
// 2.35.0 (#1094): the automatic reload waits until /api/version reported the new version twice in a row (not in the middle of
// an update, while single requests still fail); after a reload the language file is checked against the code (i18nRetry)
S.verSeen = {v: '', n: 0};
function verCheck(app) {
  if (app) { if (app === S.verSeen.v) S.verSeen.n++; else S.verSeen = {v: app, n: 1}; S.serverVer = app; }
  let el = $('#newver');
  if (!verStale()) { if (el) el.remove(); if (typeof I18N !== 'undefined' && I18N.stale) i18nRetry(); return; }
  let once = ''; try { once = sessionStorage.getItem('kalmido-reloaded') || ''; } catch { /* private mode */ }
  if (once !== S.serverVer && S.verSeen.n >= 2 && verQuiet() && (document.hidden || Date.now() - verIdle > 20000)) { verReload(); return; }
  if (!el) {
    el = document.createElement('div'); el.id = 'newver'; el.setAttribute('role', 'status');
    el.innerHTML = `${ic('sync', 's')}<span>${esc(tr('New version available'))}</span><button type="button" class="btn sm pri" data-nv="go">${esc(tr('Reload'))}</button>`;
    document.body.appendChild(el);
  }
  el.title = tr('This window runs v{0}, the server v{1}', APP_VER, S.serverVer);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && verStale()) verCheck(); });
document.addEventListener('click', e => { const b = e.target.closest?.('[data-nv="go"]'); if (b) { b.disabled = true; verReload(); } });
document.addEventListener('visibilitychange', async () => {
  if (!document.hidden && !editing()) { try { await load(); render(); } catch { /* offline */ } }
  if (!document.hidden) wpSweep();  // 2.19.0 (#668)
});
// 2.12.2 (#451, #453 B2/B3): live updates wait while someone types ANYWHERE: the task panel, the add sheet, dialogs and
// popovers as before, plus any other focused field (Kanban "+ Task", search, inline editors; only an empty "Add task" box
// on a desktop lets updates through, renderView keeps it), an IME composition and an open editor of the project overview
let imeOn = false;
document.addEventListener('compositionstart', () => { imeOn = true; }, true);
document.addEventListener('compositionend', () => { imeOn = false; }, true);
const editing = () => {
  if (imeOn || (S.povEdit && $('#pov-desc-in'))) return true;
  const a = document.activeElement; if (!a || !editFocused()) return false;
  return !!a.closest('#detail,.qadd,.modal,#pop') || a.id !== 'qinput' || !!a.value || isTouch();  // an empty composer of the list survives a re-render (renderView)
};
// a re-render of the view a live update asked for while someone types in it: done once the field is left (the poll)
function viewSafeRender() { if (editing() && $('#view')?.contains(document.activeElement)) { S.viewStale = true; return; } S.viewStale = false; renderView(); }
// 1.9.0 pull-to-refresh (touch, shared lists): pull down at the very top of the list by 4.5rem and let go
(() => {
  let y0 = null, x0 = 0, pull = 0, el = null;
  const view = () => $('#view'), max = () => 4.5 * parseFloat(getComputedStyle(document.documentElement).fontSize || 16);
  document.addEventListener('touchstart', e => {
    const v = view(); y0 = null;
    if (!v || !v.contains(e.target) || e.touches.length !== 1 || v.scrollTop > 0 || !sharedRoute() || S.multiMode || $('.modal') || e.target.closest('input,textarea,select,[draggable="true"],.trow.drag')) return;
    y0 = e.touches[0].clientY; x0 = e.touches[0].clientX; pull = 0;
  }, {passive: true});
  document.addEventListener('touchmove', e => {
    if (y0 === null) return;
    const dy = e.touches[0].clientY - y0, dx = Math.abs(e.touches[0].clientX - x0);
    if (dy <= 0 || dx > dy || view().scrollTop > 0) { if (el) el.classList.remove('on'); pull = 0; return; }
    pull = dy;
    if (!el) { el = document.createElement('div'); el.className = 'ptr'; el.setAttribute('aria-hidden', 'true'); el.innerHTML = ic('sync', 's'); $('#main').style.position ||= 'relative'; $('#main').appendChild(el); }
    const k = Math.min(1, dy / max());
    el.classList.toggle('on', dy > 12); el.style.transform = `translateY(${Math.round(k * 3.5 * 16)}px) rotate(${Math.round(k * 270)}deg)`;
  }, {passive: true});
  const end = async () => {
    if (y0 === null) return; y0 = null;
    const go = pull >= max(); pull = 0;
    if (!el) return;
    if (!go) { el.classList.remove('on'); return; }
    el.classList.add('go'); el.style.transform = 'translateY(3rem)';
    try { await refreshNow(); } finally { el?.classList.remove('on', 'go'); }
  };
  document.addEventListener('touchend', end, {passive: true});
  document.addEventListener('touchcancel', () => { y0 = null; pull = 0; el?.classList.remove('on'); }, {passive: true});
})();

// ------------------------------------------------------------------ routing
// 1.8.1: the Inbox comes first (sidebar, tab choices, palette) and is the start view (START_KEY) until another view
// was opened: the app reopens on the last task view of the device (LS 'lastKey')
const START_KEY = 'inbox';
const SMART = {
  inbox: {name: N_('Inbox'), icon: 'inbox'},
  today: {name: N_('Today'), icon: 'sun'},
  tomorrow: {name: N_('Tomorrow'), icon: 'sunrise'},
  week: {name: N_('Next 7 days'), icon: 'week'},
  doable: {name: N_('Now doable'), icon: 'zap'},  // 1.7.0
  waiting: {name: N_('Waiting on someone'), icon: 'hourglass'},  // 2.1.0 (#335)
  stale: {name: N_('Lying idle'), icon: 'clock'},  // 2.34.0 (#266)
  pinned: {name: N_('Pinned|view'), icon: 'pin'},  // 2.16.0 (#648): every pinned task of every list
  assigned: {name: N_('My tasks'), icon: 'user'},
  all: {name: N_('All'), icon: 'all'},
  done: {name: N_('Completed'), icon: 'done'},
  trash: {name: N_('Trash'), icon: 'trash'},
  archived: {name: N_('Archived'), icon: 'archive'},  // 1.6.1: the archived lists (main view)
  search: {name: N_('Search'), icon: 'search'},
};
function parseHash() {
  const h = decodeURIComponent(location.hash.slice(1));
  if (!h) return {mod: 'tasks', key: LS.get('lastKey', START_KEY)};
  const [a, b] = h.split('/');
  if (a === 't' && b) return {mod: 'tasks', key: S.route.key || START_KEY, task: +b};
  if (a === 'home') return {mod: 'home', key: 'home'};  // 2.17.0 (#475): the dashboard (the logo)
  if (a === 'team') return {mod: 'team', key: 'team', rid: +b || null};  // 2.17.0 (#419)
  if (a === 'notes' && +b) return {mod: 'notes', key: 'notes', lid: +b};  // 2.17.0 (#442)
  if (a === 'note' && +b) { const n = (S.notes || []).find(x => x.id === +b); return n ? {mod: 'notes', key: 'notes', lid: n.list_id, nid: n.id} : {mod: 'tasks', key: LS.get('lastKey', START_KEY), noteMissing: true}; }
  if (a === 'reply' && b) return {mod: 'tasks', key: S.route.key || START_KEY, task: +b, reply: true};  // 2.0.8 (#331): push button "Reply"
  if (a === 'snooze' && b) return {mod: 'tasks', key: LS.get('lastKey', START_KEY), snooze: +b};
  if (a === 'done' && b) return {mod: 'tasks', key: LS.get('lastKey', START_KEY), complete: +b};
  if (a === 'nagoff' && b) return {mod: 'tasks', key: LS.get('lastKey', START_KEY), nagoff: +b};  // 2.7.0 (#413): push "Stop reminding"
  if (a === 'prop' && b) return {mod: 'tasks', key: LS.get('lastKey', START_KEY), prop: +b};  // 2.3.0: push "Proposal ready"
  if (a === 'f' && b) return {mod: 'tasks', key: 'f:' + b};
  if (a === 'l') return {mod: 'tasks', key: 'l:' + b};
  if (a === 'tag') return {mod: 'tasks', key: 'tag:' + b};
  if (a === 'who' && +b) return {mod: 'tasks', key: 'who:' + +b};  // 2.7.2 (#418): "Tasks of …"
  if (a === 'grp' && +b) return {mod: 'tasks', key: 'grp:' + +b};  // 2.10.0 (#441): the tasks of a group
  if (a === 'today' && b === 'review') return {mod: 'tasks', key: 'today', review: true};  // 2.10.0 (#440): push "Daily review"
  if (a === 'folder' && b) return {mod: 'tasks', key: 'folder:' + h.slice(7)};  // 2.4.0: a path has a slash
  if (a === 'agents') return {mod: 'agents', key: 'agents', agent: +b || null};
  if (a === 'ev' && +b) return {mod: 'cal', key: 'cal', ev: +b};  // 2.21.0 (#659): a push / News about an event
  if (a === 'contacts') return {mod: 'contacts', key: 'contacts', contact: +b || null};  // 2.21.0 (#658)
  if (a === 'client' && +b) return {mod: 'clients', key: 'clients', client: +b};  // 2.23.0 (#463)
  if (['cal', 'matrix', 'habits', 'pomo', 'news', 'stats', 'time', 'overview', 'family', 'life', 'review', 'clients', 'workload'].includes(a)) return {mod: a, key: a};  // 2.22.0 (#663): life, review
  if (SMART[a]) return {mod: 'tasks', key: a};
  return {mod: 'tasks', key: START_KEY};
}
function go(hash) { if (location.hash !== '#' + hash) location.hash = hash; else route(); }
async function route() {
  const r = parseHash();
  if (S.me?.kid && r.mod !== 'family' && !r.complete && !r.snooze) { r.mod = 'family'; r.key = 'family'; }  // 2.19.0 (#653): a kid's home
  if (!modOn(r.mod)) {  // e.g. the "News" app shortcut while collaboration is off
    const off = r.mod;
    if (S.booted && (off === 'news' || off === 'stats' || off === 'time' || off === 'overview')) setTimeout(() => toast(off === 'news' ? tr('News are part of collaboration, which is off (Settings > Modules)') : off === 'time' ? tr('Time tracking is off (Settings > Modules)') : off === 'overview' ? tr('The project status needs “Project progress” (Settings > Modules) and at least two lists') : tr('Statistics are off (Settings > Modules)')), 50);
    r.mod = 'tasks'; r.key = LS.get('lastKey', START_KEY);
  }
  if (r.key.startsWith('f:') && !S.filters.some(f => f.id === +r.key.slice(2))) r.key = START_KEY;
  if (!r.task) S.bellBack = false;
  S.route = {mod: r.mod, key: r.key, ...(r.agent ? {agent: r.agent} : {}), ...(r.review ? {review: true} : {}), ...(r.client ? {client: r.client} : {})};
  if (r.mod === 'team') teamRoute(r.rid || null); else if (S.tc.rid) teamRoute(null);  // 2.17.0
  if (r.mod === 'notes') noteRoute(r.lid, r.nid || null); else if (S.nt.id) { noteFlush(); S.nt.id = null; }
  if (r.noteMissing) setTimeout(() => toast(tr('This note does not exist or you cannot see it.')), 0);  // 2.10.0: review = #today/review
  if (r.mod === 'agents') S.jobs.items = null;
  if (S.route.mod !== 'tasks' || r.key !== S.lastRouteKey) { S.multi.clear(); S.multiMode = false; }
  if (r.key === 'search' && S.lastRouteKey !== 'search') S.searchFocus = true;  // 2.15.1 (#633): opening Search focuses its field on a phone too (a re-render or a task closed on top of it does not)
  S.lastRouteKey = r.key;
  if (r.mod === 'tasks' && r.key !== 'search') LS.set('lastKey', r.key);
  if (r.mod === 'tasks' && r.key.startsWith('l:')) recentPush('l', +r.key.slice(2));
  S.extra = (r.key === 'done' || r.key === 'trash' || r.mod === 'news' || r.mod === 'time') ? [] : null;
  if (S.extra) await loadExtra().catch(() => { S.extra = []; });
  // 2.26.x (#953): back to an entry that was left from the open drawer (phone / folded sidebar): the drawer opens again
  // and stays; the next Back goes on as before
  if (history.state?.side && !r.task && (isMobile() || $('#app')?.classList.contains('side-rail'))) setTimeout(() => { if (history.state?.side && !$('#side.open')) sideDrawerOpen(); }, 0);
  closeSide();
  if (r.task) { render(); if (taskById(r.task)?.unread || r.reply) S.tlScroll = r.task; openDetail(r.task); history.replaceState(null, '', '#' + keyToHash(S.route.key)); if (r.reply) replyFocus(r.task); return; }
  if (r.prop) { history.replaceState(null, '', '#' + keyToHash(S.route.key)); render(); propOpen(r.prop); return; }
  if (r.snooze || r.complete || r.nagoff) {
    history.replaceState(null, '', '#' + keyToHash(S.route.key));
    render();
    const t = taskById(r.snooze || r.complete || r.nagoff);
    if (!t) { toast(tr('Task not found')); return; }
    if (r.nagoff) { if (nagOf(t)) await patchUndoable(t.id, {nag: 'off'}, tr('No more repeated reminders for “{0}”', t.title)); else toast(tr('This task does not repeat its reminder')); return; }
    if (r.complete) { if (t.status === 0) toggleTask(t.id); else toast(tr('Already completed')); }
    else snoozeSheet(t.id);
    return;
  }
  render();
  if (r.ev) evOpen(r.ev);  // 2.21.0
  if (r.mod === 'contacts') ctRoute(r.contact);
  // 2.13.0 (#453 A10): #agents/<id> (the push "… answered") opens the chat right away on Fold / desktop too
  if (r.mod === 'agents' && r.agent && !chatFull() && !$('#achat:not(.hidden)') && agentById(r.agent)) chatOpen(r.agent);
}
// 2.0.8 (#331): the push button "Reply" opens the task with the comment box focused (the sticky box of 2.0.6); the panel may still be loading, so it tries for a moment
function replyFocus(id, n = 0) {
  if (S.sel !== id) return;
  const ci = $('#detail #c-input');
  if (!ci) { if (n < 20) setTimeout(() => replyFocus(id, n + 1), 150); else if (!taskById(id)) toast(tr('Task not found')); return; }
  if ($('#detail.dsfold')) dsFoldToggle(false);  // 2.31.0 (#344): a folded comments area opens
  ci.closest('.ccomp')?.classList.add('used');
  try { ci.focus({preventScroll: true}); } catch { ci.focus(); }
  ci.scrollIntoView?.({block: 'nearest'});
}
const keyToHash = k => k.startsWith('who:') ? 'who/' + k.slice(4) : k.startsWith('grp:') ? 'grp/' + k.slice(4) : k.startsWith('l:') ? 'l/' + k.slice(2) : k.startsWith('f:') ? 'f/' + k.slice(2) : k.startsWith('tag:') ? 'tag/' + encodeURIComponent(k.slice(4)) : k.startsWith('folder:') ? 'folder/' + encodeURIComponent(k.slice(7)) : k;
// 1.5.2: folder view (key "folder:<name>"): the open tasks of every active list in that sidebar folder, grouped by list
const folderLists = f => sideOrder().filter(l => fUnder(l.folder, f) && !l.archived && !l.is_inbox);  // 2.4.0: subfolders too
window.addEventListener('hashchange', route);
