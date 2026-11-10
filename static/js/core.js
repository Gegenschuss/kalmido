/* Kalmido web client: Dates, the client state, the API + offline outbox, edit conflicts, routing.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ------------------------------------------------------------------ 2.191.0 B (#2505): start blocks after all start scripts
// index.html loads the start scripts with defer: they run in order after the page is parsed, while document.readyState is
// already 'interactive' but before DOMContentLoaded. A start block that must run after every start script (main.js
// included) waits for DOMContentLoaded until it has fired and runs at once afterwards (a module loaded on demand).
let domLoaded = document.readyState === 'complete';
document.addEventListener('DOMContentLoaded', () => { domLoaded = true; }, {once: true});
function domReady(fn) {
  if (domLoaded) fn(); else document.addEventListener('DOMContentLoaded', () => fn(), {once: true});
}

// ------------------------------------------------------------------ drags (2.87.9, #1965)
// A drag follows the pointer once per frame: the moves of one frame collapse into the last one, so a fast mouse (or a
// 120 Hz touch screen) costs one layout per frame, not one per event. f.flush() runs a pending move at once (on release),
// f.cancel() drops it. DRAGSTAT counts the frames that ran (a test hook).
const DRAGSTAT = {frames: 0};
function rafThrottle(fn) {
  let id = 0, args = null;
  const run = () => { id = 0; const a = args; args = null; if (a) { DRAGSTAT.frames++; fn(...a); } };
  const f = (...a) => { args = a; if (!id) id = requestAnimationFrame(run); };
  f.flush = () => { if (id) cancelAnimationFrame(id); run(); };
  f.cancel = () => { if (id) cancelAnimationFrame(id); id = 0; args = null; };
  return f;
}
// 2.586.0 A (#4860): while a grip is dragged (body.pgdrag) the content still reflows live every frame, but the watchers that fit
// bars and modes to a new width (fitTop, fitDtop, lsd_sync, the agents band, the inline title field) do not measure every
// frame: dragRest(key, fn) runs fn at once outside a drag; during one each key runs at most once per DRAG_REST_MS (its last
// call), and everything pending runs once more right after release (dragRestFlush, called where the drag ends)
const DRAG_REST_MS = 200, DRAGREST = {fns: new Map(), t: 0, n: 0};
function dragRest(key, fn) {
  if (!document.body || !document.body.classList.contains('pgdrag')) { fn(); return; }
  DRAGREST.fns.set(key, fn);
  if (!DRAGREST.t) DRAGREST.t = setTimeout(dragRestRun, DRAG_REST_MS);
}
function dragRestRun() {
  DRAGREST.t = 0; const fs = [...DRAGREST.fns.values()]; DRAGREST.fns.clear();
  for (const f of fs) { DRAGREST.n++; try { f(); } catch (e) { console.error(e); } }
}
function dragRestFlush() { clearTimeout(DRAGREST.t); dragRestRun(); }
// 2.599.0 (#4506): the one delay helper. f(...) runs fn once, ms after the last call, with the latest arguments (and this);
// f.flush() runs a waiting call at once (a dialog closes, the page hides) and returns its result, f.cancel() drops it,
// f.pending() says whether one waits. New code uses it instead of a hand-made clearTimeout / setTimeout pair:
// tools/perf_budget.py counts the calls of clearTimeout in static/js and that count may only go down.
function debounce(fn, ms) {
  let id = 0, args = null, self = null;
  const stop = () => { clearTimeout(id); id = 0; };
  const run = () => { stop(); const a = args, t = self; args = self = null; return a ? fn.apply(t, a) : undefined; };
  const f = function (...a) { stop(); args = a; self = this; id = setTimeout(run, ms); };
  f.flush = run;
  f.cancel = () => { stop(); args = self = null; };
  f.pending = () => !!args;
  return f;
}

// ------------------------------------------------------------------ dates
// 2.223.3 A (#2877): while the server's deletion runs only count (KALMIDO_RETENTION_PURGE off), no trash promises a period
const trashKeeps = () => S.trashPurge === false;
const trashNote = (txt, off) => off || trashKeeps() ? tr('Deleted items stay in the trash until the deletion runs of the server are switched on.') : txt;
const pad = n => String(n).padStart(2, '0');
const ds = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const pd = s => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
const addDays = (s, n) => { const d = pd(s); d.setDate(d.getDate() + n); return ds(d); };
const today = () => ds(new Date());
// ------------------------------------------------------------------ numbers
// 2.263.0 (#2976): ONE reader for numbers typed by people (fields, office, settings; the server: core/numtext.py, same rules).
// The decimal sign comes from the app language (every comma language like German). "1.234,50" / "1,234.50": the last sign
// is the decimal one - it must be the language's (else wrong order = not a number, nothing is cut silently). A sign used
// once is a thousands separator only when it is not the decimal one, 1-3 digits stand before it (not a lone 0) and exactly
// three after it ("1.500" in German, "1,500" in English); else it is the decimal sign ("12,5" in English = 12.5).
// frac = a field with up to four decimals (rate, factor): a sign used once is always the decimal one.
const numDec = () => { try { return (1.5).toLocaleString(LOCALE()).charAt(1) === ',' ? ',' : '.'; } catch { return '.'; } };
function parseNum(v, frac) {
  let s = String(v ?? '').trim().replace(/[\s\u00a0\u202f']/g, '');
  if (!/^[+-]?(\d[\d.,]*|[.,]\d+)$/.test(s)) return null;
  const dec = numDec(), grp = dec === ',' ? '.' : ',', sign = /^[+-]/.test(s) ? s[0] : '';
  s = s.replace(/^[+-]/, '');
  const nd = s.split(dec).length - 1, ng = s.split(grp).length - 1, groups = new RegExp(`^\\d{1,3}(\\${grp}\\d{3})+$`);
  if (nd > 1) return null;
  if (nd && ng) {  // both: the groups stand before the decimal sign
    const [a, b] = s.split(dec);
    if (!groups.test(a) || b.includes(grp)) return null;
    s = a.split(grp).join('') + '.' + b;
  } else if (nd) s = s.replace(dec, '.');
  else if (ng > 1) { if (!groups.test(s)) return null; s = s.split(grp).join(''); }
  else if (ng) s = !frac && groups.test(s) && !/^0\D/.test(s) ? s.replace(grp, '') : s.replace(grp, '.');
  const n = parseFloat(sign + s); return Number.isFinite(n) ? n : null;
}
// a typed number for a request body: '' = null, a number = the number, anything else = the text (the server names the field)
// 2.450.0 (#3770): a stored number as the text of an input field in the app language, without groups ("1234,5"); parseNum reads it back
const numField = (v, d = 6, min = 0) => v == null || v === '' ? '' : Number.isFinite(+v) ? (+v).toLocaleString(LOCALE(), {useGrouping: false, minimumFractionDigits: min, maximumFractionDigits: d}) : String(v);
// 2.450.0 (#3770): ONE order for names, tags and titles: the app language's (Spanish ñ after n, Swedish ä at the end), never a fixed one
const cmpColl = {};
const cmpText = (a, b) => (cmpColl[LOCALE()] ||= new Intl.Collator(LOCALE())).compare(String(a ?? ''), String(b ?? ''));
const numBody = v => { const t = String(v ?? '').trim(); if (!t) return null; const n = parseNum(t); return n == null ? t : n; };
// weekday / month names + date patterns come from the language file (i18n.js: WD, WDL, MON, MONS, fmtDay), weeks still start on Monday
const WD_MO = () => [1, 2, 3, 4, 5, 6, 0].map(i => WD[i]);  // calendar header, Monday first
const fmtDate = s => fmtDateNum(pd(s));  // 2.368.0 B (#2982): the chosen order of numbers
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
const dueLabel = (t, range = true) => !t.due ? '' : (range && t.start && t.start < t.due ? dayLabel(t.start) + ' – ' : '') + dayLabel(t.due) + (t.due_time ? ', ' + fmtTimeLoc(t.due_time) : '');  // 2.368.0 B (#2982): fmtTimeLoc
const dueClass = t => !t.due || t.status ? '' : t.due < today() ? 'over' : t.due === today() ? 'today' : '';
// 2.16.0 (#473, WCAG 1.4.1): the priority as a shape too (! / !! / !!!, like the quick add), named for screen readers
const PRIO_NAME = {7: N_('Urgent priority'), 5: N_('High priority'), 3: N_('Medium priority'), 1: N_('Low priority')};  // 2.574.0 (#3376): + Urgent
const prioWord = p => tr({7: N_('Urgent'), 5: N_('High'), 3: N_('Medium'), 1: N_('Low')}[p] || N_('None'));
const prioMark = p => PRIO_NAME[p] ? `<span class="prm p${p}" role="img" aria-label="${esc(tr(PRIO_NAME[p]))}" title="${esc(tr(PRIO_NAME[p]))}">${{7: '!!!!', 5: '!!!', 3: '!!', 1: '!'}[p]}</span>` : '';
// timeline, roadmap, statistics and time reports use weekStartOf (the locale's first weekday, 1.5.1); habits keep Mondays
function mondayOf(s) { const d = pd(s); const k = (d.getDay() + 6) % 7; d.setDate(d.getDate() - k); return ds(d); }

// a date without its weekday in the language's own short pattern ("4. Okt" / "Oct 4"), with the year if it is not this one
// 2.368.0 B (#2982): the leading weekday is cut by its name ("Mon 26 Oct" -> "26 Oct": the old pattern kept "Mon" when a
// number followed it without a comma, as in English, Dutch); the old pattern stays for a language that writes it elsewhere
const dayNoWd = (d, year) => { const s = fmtDay(year ? 'year' : 'short', d), w = WD[d.getDay()];
  return (s.startsWith(w) ? s.slice(w.length) : s.replace(/^[^\d{]*?(?=\d|[A-Za-zÀ-ÿ]+\s\d)/, '')).replace(/^\s*[,.]?\s*/, ''); };
function weekTitle(first) {
  const a = pd(first), b = pd(addDays(first, 6)), y = new Date().getFullYear(), other = a.getFullYear() !== y || b.getFullYear() !== y;
  return `${dayNoWd(a, other && a.getFullYear() !== b.getFullYear())} – ${dayNoWd(b, other)} · ${tr('Week {0}', isoWeek(addDays(first, 3)))}`;
}
// ------------------------------------------------------------------ state
/** @type {KalmidoState} */  // 2.102.0 (#1995): the type for the type check (jsconfig.json, tools/tsc/kalmido.d.ts)
const S = {
  lists: [], sections: [], tasks: new Map(), habits: [], pomo: null, pomoToday: {count: 0, minutes: 0},
  settings: {}, counts: {}, v: 0, ntfyUrl: 'https://ntfy.sh', me: null,
  route: {mod: 'tasks', key: 'inbox'}, sel: null, extra: null,
  collapsed: new Set(LS.get('collapsed', []).filter(x => x !== 'side:arch-open')),  // 1.6.1: the archive fold is gone
  calMonth: null, calSel: today(), quick: {ignore: new Set()},
  filters: [], views: [], multi: new Set(), multiMode: false, occ: {key: '', items: []}, cal: {key: '', loading: '', items: [], subs: {}, evcals: {}}, calendars: {enabled: false, subs: 0},
  calMode: LS.get('calMode', 'month'), tlStart: null, quickPreset: {}, editContent: false,
  tl: {id: null}, drafts: {}, cfiles: {}, cedit: null, editLink: false,  // comments timeline of the open task
};
const FEATS = [['cal', N_('Calendar')], ['timeline', N_('Timeline')], ['matrix', N_('Eisenhower matrix')], ['habits', N_('Habits')], ['pomo', N_('Focus timer')], ['kanban', N_('Kanban')], ['collab', N_('Collaboration')], ['stats', N_('Statistics')], ['time', N_('Time tracking')], ['progress', N_('Project progress')], ['deps', N_('Dependencies')], ['fields', N_('Custom fields')], ['agents', N_('Agents')], ['comments', N_('Comments')], ['family', N_('Family')], ['events', N_('Events')], ['contacts', N_('Contacts')],
  // 2.22.0 (#663): Home & life, each off by default
  ['contracts', N_('Contracts')], ['home', N_('Home & devices')], ['care', N_('Staying in touch')], ['health', N_('Health')], ['review', N_('Review & journal')], ['travel', N_('Travel')], ['reading', N_('Read later')],
  ['budget', N_('Budget')],  // 2.72.0 (#1333): the household budget, off by default
  ['feeds', N_('Feeds')],  // 2.85.0 B (#1162): feeds, off by default
  // 2.23.0 (#463): package "Team, family, clients", each off by default
  ['clients', N_('Clients')], ['workload', N_('Workload & absences')] /* 2.380.2 (#3407): the view's name (de: Einsatzplan) */, ['forms', N_('Forms')],
  // 2.36.1 (#1021): Office & finance (business area: needs an organisation), off by default
  ['office', N_('Office & finance')],
  // 2.49.0 (#1199): knowledge pages (a small wiki per organisation), off by default
  ['wiki', N_('Knowledge pages')],
  ['files', N_('File store')],  // 2.48.0 (#1207): folders and files with shares (ablage.js), on for everyone
  // 2.50.0 (#1194): resources and disposition (a tab of the workload view), off by default
  ['dispo', N_('Disposition')],
  ['sheets', N_('Tables')],  // 2.89.0 (#1916): tables with Kalmido variables (sheets.js), off by default
  ['videos', N_('Approval')]];  // 2.623.0 (#4765): the approval (video sign-offs, videorev.js), on for everyone once (features_rev 12)
const FEAT_DESC = {deps: N_('“Blocked by” in the task details, arrows and linking in the timeline, what is stuck in the project status, a notice when a task is unblocked'),
  fields: N_('Own fields per project (text, number, selection, date, person, link), as columns and in the task details'),collab: N_('Comments, history, @mentions, News, sharing projects and assigning tasks'), stats: N_('Completed tasks, on-time rate, overdue trend, focus time and habit streaks'),
  time: N_('Timer on tasks, manual entries, reports per project and task, CSV export and a printable timesheet'),
  clients: N_('Clients above the projects: contact, hourly rate, budget in hours or money, estimate vs. actual and the timesheet per client and month (only within the workspace)'),
  workload: N_('How much each person of the workspace has on their plate per week, against their hours per week'),
  forms: N_('A link with a small form (requests, bug reports) that creates a task in a project; agents can sort it in'),
  dispo: N_('Book crew and equipment for shoot days as option or firm, see who and what is free per day, double bookings and absences as warnings (a tab of the workload)'),  // 2.50.0 (#1194)
  agents: N_('A tab with the agents (AI assistants, bots) you share projects with: their status, jobs to approve and the chat'),
  office: N_('Quotations with a calculator, services and rates, equipment, text blocks, framework contracts and PDF documents - your own or your organisation\'s'),
  wiki: N_('Pages in Markdown for processes, checklists and know-how of your organisation (or only for you), with links between them and to tasks'),  // 2.49.0 (#1199)
  sheets: N_('Simple tables with formulas like a spreadsheet; every cell can fetch figures from Kalmido (hours booked, budget, open tasks), for quotations, budgets and lists'),  // 2.89.0 (#1916)
  progress: N_('Progress bar in the project header and the project status (“Where is it stuck?”); with collaboration also a status per project')};
// 2.364.0 B (#3018): a person without an organisation reads no "only within the organisation" sentence (their clients are their own)
const FEAT_DESC_SOLO = {clients: N_('Clients above the projects: contact, hourly rate, budget in hours or money, estimate vs. actual and the timesheet per client and month')};
// 2.409.0 (#3490): + the areas switched off in the shown workspace (areas.js wsa_featOff; the module switch stays the main switch)
const feat = f => (S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').includes(f) && !(typeof wsa_featOff === 'function' && wsa_featOff(f));
// collaboration off (own switch, or the admin's switch for the whole server): no comments / activity / mentions /
// sharing / assigning in the UI (data stays; with the server switch off the API refuses them too)
const collab = () => feat('collab') && S.collabAll !== false;
// 2.364.0 D (#3036): "has collaborators": a project of mine is shared with another person or an agent, or one of my
// organisations has someone else. Without it the team entries (assign, waiting on someone, approval) stay out of the menus.
const hasPeers = () => collab() && (!!S.orgPeers || (S.lists || []).some(l => l.shared));
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
const modOn = m => m === 'tasks' || m === 'home' || m === 'msv' || m === 'notes' || m === 'tags' || (m === 'team' ? teamOn() : m === 'agents' ? agentsTab() : m === 'news' ? collab() : m === 'overview' ? overviewOn() : m === 'time' ? timeOn() : m === 'family' ? feat(m) || !!S.me?.kid : m === 'life' ? lifeOn() : m === 'bookmarks' ? feat('reading') : m === 'workload' ? workloadOn() : m === 'office' ? officeOn() : m === 'ablage' ? ab_on() : m === 'docs' ? typeof viewDocs === 'function' && feat('docs') : feat(m));  // 2.48.0 (#1207, #1111); 2.97.0 A (#1950): bookmarks = module reading
// no "+" button on views without tasks
// views of the tasks module that are not a task list (no quick add, no selection, no open-count)
const NOLIST_KEYS = ['done', 'trash', 'search', 'archived', 'projects', 'favorites', 'steps'];  // 2.773.0 (#5250): + the page "Recent steps"  // 2.417.0 A (#3559): + the start page of Projects
// 2.0.6 (#188): tablets in portrait (phone layout, but >= 600 x 600 px) get the docked composer of the desktop instead of
// the "+" button wherever a view has one; phones keep the "+"
// 2.19.0 (#669, a regression of 2.7.2): the tablet layout with the docked "Add task" bar (600-899 px wide, 600 px high) is
// decided on the height WITHOUT the on-screen keyboard. With interactive-widget=resizes-content the keyboard shrinks the
// layout height below 600 px (an unfolded Fold in portrait), the bar flipped to the phone layout, was hidden and took
// the focus (and the keyboard) with it. The height is taken while nothing is being typed, or when the width changes.
const TD = {on: null, w: -1};
function tdockSync() {
  if (TD.on === null || innerWidth !== TD.w || !editFocused()) { TD.on = /[?&]mini=1\b/.test(location.search) || matchMedia('(min-width:600px) and (min-height:600px)').matches;  /* 2.39.1 (#1294): the list window keeps its composer */ TD.w = innerWidth; }
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
const noFab = () => ['habits', 'pomo', 'news', 'stats', 'time', 'overview', 'agents', 'team', 'notes', 'family', 'contacts', 'life', 'review', 'clients', 'workload', 'office', 'ablage', 'docs', 'wiki', 'tags', 'budget', 'msv', 'feeds', 'sheets', 'bookmarks', 'reading'].includes(S.route.mod) || NOLIST_KEYS.includes(S.route.key) || isOverview()
  || (/^l:\d+$/.test(S.route.key || '') && !!listById(+S.route.key.slice(2)) && !canAddTo(+S.route.key.slice(2)));  // 2.147.2 A (#2500): no + in a list I may not add to
// package 3: progress bar / overview (switch "progress"), project status (+ collaboration), custom fields, dependencies
// 2.13.0 (#453, Fold screenshots): the round + only on phones; tablets / an unfolded Fold add with the docked "Add task"
// bar or, in views without it (calendar, Kanban, timeline), the header's "New task" button
const dockView = () => S.route.mod === 'tasks' && !isKanban() && !isTimeline() && !isRoadmap() && !isOverview() && !noFab();
const fabOff = () => noFab() || (isTouch() && (!isMobile() || tabletDock()));
const progressOn = () => feat('progress');
const statusOn = () => progressOn();  // 2.395.0 (#3379): a project status also without collaboration (one person / freelancer)
// "Where is it stuck?" only pays off with several projects: 2+ active lists, or a shared list
// 2.352.0 B (#2752): every list but the inbox is a project (kind is not read any more); tracked = has a status
const isTracked = l => !!l && !l.is_inbox && !!l.status && !life_store(l);  // 2.609.0 (#4613): an area's store list is in no project list
const overviewOn = () => progressOn() && (S.lists.filter(l => !l.archived && isTracked(l) && inWs(l)).length >= 2 || (collab() && S.lists.some(l => l.shared && !l.archived && isTracked(l) && inWs(l))));  // 2.380.2 (#3407): inWs
// modules "deps" / "fields" (1.2): off = hidden in the app, the data and the API stay
const depsOn = () => feat('deps');
const fieldsOn = () => feat('fields');
// list type (1.2): list | checklist | project. Time tracking, dependencies, custom fields and progress / status only
// show in project lists, and only while their module is on (the module stays the outer switch)
const isProject = lid => { const l = listById(lid); return !!l && !l.is_inbox; };
// 2.412.0 (#3552): + the project's properties (props.js); a task with tracked time / dependencies keeps showing them
const tFor = t => !!t && timeOn() && mtTime(t.list_id) && pz_show(t, 'time', taskTime(t.id)[0]);    // time tracking for this task (2.41.0 #1471: the list's switch)
const dFor = t => !!t && depsOn() && isProject(t.list_id) && pz_show(t, 'deps', (t.blockers || []).length);    // dependencies for this task
const progressFor = l => !!l && progressOn() && !l.is_inbox;
const statusFor = l => !!l && statusOn() && !l.is_inbox;
const fieldsAll = lid => (S.fields || []).filter(f => f.list_id === lid).sort((a, b) => a.sort - b.sort || a.id - b.id);
// 2.39.1 (#1217): custom fields in every list (plain lists too); time tracking and dependencies stay project-only
const fieldsOf = lid => !fieldsOn() ? [] : td_rc('fo' + lid, () => (S.fields || []).filter(f => f.list_id === lid).sort((a, b) => a.sort - b.sort || a.id - b.id));  // 2.40.0 (#1430): once per render
const fieldById = id => (S.fields || []).find(f => f.id === id);
const inbox = () => td_rc('inbox', () => S.lists.find(l => l.is_inbox));  // 2.579.0 (#4199): once per draw (it runs per task in counts)
// 2.579.0 (#4199): a lookup through a map instead of a scan (it runs several times per task and draw). S.lists is replaced, pushed
// to, spliced and its entries swapped in many places: the map is built again when the array or its length changed, and a hit
// counts only when the entry at its place still carries that id (else built again); an id not in the map is looked up the old way
// 2.609.0 (#4613): a list an area uses as its store (lists.life: contracts, home, health, travel, reading, budget): never shown as
// a project (sidebar, pickers, "Move to …", filters, project lists), only through its area; #l/<id> opens the area (parseHash).
// Its tasks stay in Today / Upcoming / Search. life_read: only Read later leaves the statistics (server: stats.py, life review)
const life_store = l => !!l?.life;
const life_read = l => l?.life === 'reading';
const LIFE_STORE_GO = {reading: 'reading', budget: 'budget', contracts: 'life', home: 'life', health: 'life'};  // travel: the trip's list IS the trip view (life.js), it stays #l/<id>
let _lbx = {a: null, n: -1, m: new Map()};
function listById(id) {
  const a = S.lists; if (!a) return undefined;
  if (_lbx.a !== a || _lbx.n !== a.length) { const m = new Map(); a.forEach((l, i) => { if (l && !m.has(l.id)) m.set(l.id, i); }); _lbx = {a, n: a.length, m}; }  // the first one with an id, as find
  const i = _lbx.m.get(id);
  if (i !== undefined) { const l = a[i]; if (l && l.id === id) return l; }
  const l = a.find(x => x.id === id);
  if (l || i !== undefined) _lbx.a = null;  // the map is out of date (an entry swapped or moved): built again on the next lookup
  return l;
}
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
// notes, subtasks, sort order, pin (2.542.0, #4609: completing / reopening only after unlocking, tlkDone). Whoever may change the task may lock / unlock it. tlkHits =
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
// 2.542.0 (#4609): a locked task is not completed / reopened on any way (tick, swipe, x, selection, subtask tick; the server refuses it too)
function tlkDoneToast(t) { toast(tr('This task is locked. Unlock it to complete or reopen it.'), canEdit(t) ? () => tlkSet(t.id, false) : undefined, 6000, canEdit(t) ? tr('Unlock') : undefined); }
const tlkDone = t => { if (!tlkIs(t)) return false; tlkDoneToast(t); return true; };
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
const personName = (lid, uid) => listPeople(listById(lid)).find(p => p.user_id === uid)?.name || (uid && o3a_ovAssignable(listById(lid)) ? o3a_name(uid) : '');  // 2.83.0 (#1725): + assigned without joining
const initials = n => String(n || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase() || '?';
// 1.9.0 profile pictures: S.avatars = {user id: URL} (me + everybody sharing a list with me, from /api/state; the News
// answer adds its people). av() = the round picture, or the initials as before. cls/attrs: the caller's classes + title.
const avUrl = id => (id && ((S.avatars || {})[id] || (S.me && +id === S.me.id ? S.me.avatar : ''))) || '';
function av(id, name, cls = 'avatar', attrs = '', inner = '', eager = false) {  // 2.47.0 (#1654): eager = always visible (sidebar), no lazy load
  const u = avUrl(id), ag = id ? agentDot(id) : '';  // 2.0.0: agents get a status dot
  if (ag || (id && isAgentUser(id))) { cls += ' agent'; inner += ag + botBadge(); }  // 2.28.0 (#985): + the robot badge
  const col = id ? ac_color(id) : '';  // 2.47.1 (#1721): the fixed account colour: the fill behind the initials, a ring around a photo
  if (col) { cls += ' acol' + (ac_darkInk(col) ? ' acdk' : ''); attrs += ` style="--acol:${col}"`; }
  return `<span class="${cls}${u ? ' pic' : ''}" ${attrs}>${u ? `<img src="${esc(u)}" alt="" ${eager ? 'decoding="sync"' : 'loading="lazy" decoding="async"'} draggable="false">` : esc(initials(name))}${inner}</span>`;
}
// 2.47.1 (#1721): the fixed colour of an account (S.colors from /api/state, one of the palette below = AC_COLORS in
// kalmido/accounts/colors.py), '' = none: unknown, or a person while "Show colours for people" is off (agents keep theirs)
const AC_COLORS = ['#3e63dd', '#f76b15', '#30a46c', '#a43cb4', '#cf3539', '#12a594', '#e2a336', '#c2307f', '#2aa7dc', '#8d5f3e', '#6e56cf', '#99b13a'];
function ac_color(uid) {
  const c = uid ? (S.colors || {})[uid] || '' : '';
  if (!c || !/^#[0-9a-f]{6}$/i.test(c)) return '';
  return S.settings?.person_colors === '0' && !isAgentUser(uid) ? '' : c;
}
const ac_mi = uid => { const c = ac_color(uid); return c ? {swc: c} : {icon: 'user'}; };  // a menu entry: the person's colour, else the person icon
const ac_mk = uid => { const c = ac_color(uid); return c ? ` data-acol style="--acol:${c}"` : ''; };  // a sidebar dot / job card mark in the colour
function ac_darkInk(c) {  // light colours carry dark initials (contrast >= 4.5 either way for the palette)
  const l = [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16) / 255).map(x => x <= .03928 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4);
  return .2126 * l[0] + .7152 * l[1] + .0722 * l[2] > .18;
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
  toast(lid && isPart(lid) ? tr('Your role in this shared project does not allow this change') : tr('Read-only: you cannot change this shared project'));
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
const bySort = (a, b) => ((a.also || b.also) ? ml_sortOf(a, ml_viewList()) - ml_sortOf(b, ml_viewList()) : a.sort - b.sort) || a.id - b.id;  // 2.71.0 B (#1459): a linked task's place in a further list
// 1.5.1: the tasks of an archived list are hidden everywhere except in that list itself (Today, Tomorrow, Next 7 days,
// counts, Assigned, filters, tags, calendar, matrix, overview); unarchiving brings them back
const archivedTask = t => !!t && !!listById(t.list_id)?.archived;
const archHidden = t => archivedTask(t) && !(S.route.mod === 'tasks' && S.route.key === 'l:' + t.list_id);
// ctx: include the read-only context parents of a participant's subtasks (only the list view shows them, above their subtask)
function openTasks(ctx = false) { return td_rc(ctx ? 'ot1' : 'ot0', () => [...S.tasks.values()].filter(t => t.status === 0 && !archHidden(t) && !wsHidden(t) && !ovHidden(t) && (ctx || !t.context))).slice(); }  // 2.28.0 (#935): + the workspace; 2.579.0 (#4199): once per draw (td_rc), a copy for the caller

// ------------------------------------------------------------------ api + offline outbox
// While offline, task/habit writes are applied locally and queued (localStorage outbox); on reconnect
// they are replayed in order (last write wins, `_prev` detects edits made elsewhere). Tasks created
// offline get a negative temp id that is mapped to the real id during replay. The last server state is
// cached for offline start. Every queued op carries the user id: ops of another user are never replayed.
class Offline extends Error {}
const ML_WAITS = N_('The task was moved meanwhile: it is shown in that project again if it moves back within 24 hours.');  // 2.363.3 (#3133): POST .../links answers link_waits
const MO_KEPT = N_('Your order of My tasks was changed on another device: that order stays, this change was not applied.');  // 2.363.3 (#3133): PUT /api/tasks/mine-order answers order_kept
// 2.306.0 B (#2889): the session ended (401 / the login proxy's page): the stored state of the account (cache, tabs, chat
// windows, session keys) goes like at logout, so the next person on this browser does not find it. Changes still waiting
// to be sent (outbox, conflicts) keep everything as before: they go out after the next login of the same account.
async function authGone() {
  try { outSync(); } catch { /* storage gone */ }
  if (OUT.q.length || (S.conflicts || []).length || fdAny()) return;  // 2.527.0 (#4304 A5): + input kept for after the sign-in
  await Promise.race([clearLocal(), new Promise(ok => setTimeout(ok, 1500))]);
}
const OUT = {q: LS.get('outbox', []), online: true, flushing: false};
// 2.126.0 D (#1989): every tab and list window of the browser shares the queue, localStorage is the truth: outSync takes over
// what the others wrote (an entry keeps its object, known by its key k, so undo steps still find it; one that left the queue
// elsewhere counts as done), outSave changes the fresh copy and writes it back, and only one tab replays (flush, Web Locks)
const outKey = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
// 2.528.0 (#4305 B1): a write that brings its own idempotency key (body._idem: one per press) sends it online and in the queue
const oxaKey = b => b && typeof b === 'object' && !(b instanceof FormData) && typeof b._idem === 'string' ? b._idem : undefined;
function outSync() {
  if (OBX.on) { obxAdopt(); return OUT.q; }  // 2.143.0 C (#2153): the other tabs' changes arrive on the channel
  const mine = new Map(OUT.q.map(x => [x.k, x])), q = LS.get('outbox', []);
  let fix = false;
  OUT.q = q.map(x => {
    if (!x.k) { x.k = outKey(); fix = true; }
    const o = mine.get(x.k); mine.delete(x.k);
    if (!o) return x;
    if (!x.sending) delete o.sending;
    return Object.assign(o, x);
  });
  for (const o of mine.values()) o.done = true;
  if (fix) LS.set('outbox', OUT.q);
  return OUT.q;
}
function outSave(fn) {
  if (OBX.on) { obxSave(fn); return; }
  outSync(); fn(); LS.set('outbox', OUT.q);
}
window.addEventListener('storage', ev => { if (ev.key === 'tasks.outbox') { outSync(); if (S.booted) renderTop(); } });
// 2.143.0 C (#2153): the queue lives in IndexedDB (database "kalmido-outbox": store "ops" = one record per entry, key k, order n;
// store "meta" = the user of the queue, the id map), so the service worker can send it by Background Sync while no tab is
// open. In memory OUT.q stays the working copy (every caller stays synchronous); outSave writes only the changed entries and
// tells the other tabs on the BroadcastChannel "kalmido-outbox" (put / del by key), the service worker uses the same channel.
// A queue of an earlier version in localStorage is taken over once at the start (and later, should an old tab still write
// one). Without IndexedDB (old browser, private mode, jsdom) everything stays in localStorage as before.
const OBX = {on: false, st: null, ch: null, c: 0, ready: null};
const obxSeq = () => Date.now() * 1000 + (OBX.c = (OBX.c + 1) % 1000);
const obxRec = x => { const {done, res, ...r} = x; return JSON.parse(JSON.stringify(r, typeof le2eRepl === 'function' ? le2eRepl() : undefined)); };  // like LS.set: ciphers only
const obxReq = r => new Promise((ok, no) => { r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
// the small store over IndexedDB: all(), write(put, del), meta(k), setMeta(k, v), clear(); tests hand in their own (__obxStore)
function obxIdb() {
  if (!globalThis.indexedDB) return null;
  let dbp = null;
  const db = () => dbp ||= new Promise((ok, no) => {
    const r = indexedDB.open('kalmido-outbox', 1);
    r.onupgradeneeded = () => { const d = r.result; if (!d.objectStoreNames.contains('ops')) d.createObjectStore('ops', {keyPath: 'k'}); if (!d.objectStoreNames.contains('meta')) d.createObjectStore('meta', {keyPath: 'k'}); };
    r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); r.onblocked = () => no(new Error('blocked'));
  });
  const tx = async (st, mode, fn) => { const t = (await db()).transaction(st, mode), out = fn(t); await new Promise((ok, no) => { t.oncomplete = ok; t.onerror = t.onabort = () => no(t.error); }); return out instanceof IDBRequest ? out.result : out; };
  return {
    all: async () => obxReq((await db()).transaction('ops').objectStore('ops').getAll()),
    write: (put, del) => tx('ops', 'readwrite', t => { const o = t.objectStore('ops'); for (const r of put) o.put(r); for (const k of del) o.delete(k); }),
    meta: async k => (await obxReq((await db()).transaction('meta').objectStore('meta').get(k)))?.v,
    setMeta: (k, v) => tx('meta', 'readwrite', t => { const o = t.objectStore('meta'); if (v === undefined) o.delete(k); else o.put({k, v}); }),
    clear: () => tx(['ops', 'meta'], 'readwrite', t => { t.objectStore('ops').clear(); t.objectStore('meta').clear(); }),
  };
}
async function outOpen() {
  return OBX.ready ||= (async () => {
    const st = globalThis.__obxStore || obxIdb(); if (!st) return;
    let rows;
    try { rows = await st.all(); } catch { return; }  // no IndexedDB (private mode): localStorage as before
    OBX.st = st; OBX.on = true;
    const mine = new Map(OUT.q.map(x => [x.k, x]));
    OUT.q = rows.sort((a, b) => a.n - b.n).map(r => mine.has(r.k) ? Object.assign(mine.get(r.k), r) : r);
    obxAdopt();
    try { OBX.ch = new BroadcastChannel('kalmido-outbox'); OBX.ch.onmessage = ev => obxRecv(ev.data || {}); } catch { /* no BroadcastChannel: each tab on its own */ }
    await obxDrain();
  })();
}
// entries an earlier version left in localStorage: into IndexedDB (before anything new), then out of localStorage
function obxAdopt() {
  const old = LS.get('outbox', null);
  if (!Array.isArray(old) || !old.length) return;
  const have = new Set(OUT.q.map(x => x.k)), n0 = Math.min(obxSeq(), ...OUT.q.map(x => x.n));
  const add = old.map((x, i) => ({...x, k: x.k || outKey(), n: x.n ?? n0 - old.length + i})).filter(x => !have.has(x.k));
  // 2.359.0 (#3024, review): what outStash put there carries its number (a newer change): after the queue, never before it
  const late = add.filter(x => x.n > n0);
  OUT.q = [...add.filter(x => !late.includes(x)), ...OUT.q, ...late.sort((a, b) => a.n - b.n)];
  obxWrite(add.map(obxRec), []).then(() => LS.del('outbox'), () => {});
}
function obxSave(fn) {
  obxAdopt();
  const before = new Map(OUT.q.map(x => [x.k, JSON.stringify(obxRec(x))]));
  fn();
  const put = [];
  for (const x of OUT.q) {
    if (!x.k) x.k = outKey();
    if (x.n == null) x.n = obxSeq();
    const r = obxRec(x);
    if (before.get(x.k) !== JSON.stringify(r)) put.push(r);
    before.delete(x.k);
  }
  if (put.length || before.size) obxWrite(put, [...before.keys()]);
}
function obxWrite(put, del) {
  return OBX.st.write(put, del).then(() => { try { OBX.ch?.postMessage({put, del}); } catch { /* closed */ } },
    e => { console.warn('outbox: IndexedDB write failed', e); LS.set('outbox', OUT.q.map(obxRec)); });  // the next start takes it over
}
// what another tab (or the service worker) wrote: the same merge as outSync (an entry keeps its object; gone elsewhere = done)
function obxRecv(d) {
  if (d.clear) { for (const o of OUT.q) o.done = true; OUT.q = []; }
  const by = new Map(OUT.q.map(x => [x.k, x]));
  for (const k of d.del || []) { const o = by.get(k); if (o) { o.done = true; by.delete(k); } }
  for (const r of d.put || []) { const o = by.get(r.k); if (o) { if (!r.sending) delete o.sending; Object.assign(o, r); } else by.set(r.k, r); }
  OUT.q = [...by.values()].sort((a, b) => a.n - b.n);
  if (d.sw) obxDrain();
  if (S.booted) renderTop();
}
// what the service worker sent while no tab was open: its new task ids, conflicts and skipped repeats (shown here)
async function obxDrain() {
  if (!OBX.on) return;
  let map, res;
  try { [map, res] = [await OBX.st.meta('swmap'), await OBX.st.meta('swres')]; } catch { return; }
  if (map && Object.keys(map).length) { const idm = LS.get('idmap', {}); Object.assign(idm, map); Object.assign(HIST.ids, map); LS.set('idmap', idm); OBX.st.setMeta('swmap', undefined).catch(() => {}); }
  if (res?.length) {
    OBX.st.setMeta('swres', undefined).catch(() => {});
    setTimeout(() => { for (const j of res) if (j.conflicts?.length) addConflicts(j.id, j.conflicts, j.title); if (res.some(j => j.skipped)) toast(tr('Recurring task was already checked off, not advanced twice')); if (res.some(j => j.nouid)) toast(tr('Offline changes made before the sign-in were kept and are sent from here')); }, 0);  // 2.533.0 A2 (#4318 A15)
  }
  if (map && Object.keys(map).length && typeof qfSend === 'function') qfSend();  // 2.359.0 A (#3023): files of a quick add made offline
}
const obxMeta = (k, v) => { if (OBX.on) OBX.st.setMeta(k, v).catch(() => {}); };
// logout / another user in this browser (clearLocal): the queue goes with the rest of the local data
function obxClear() { if (!OBX.on) return Promise.resolve(); for (const o of OUT.q) o.done = true; OUT.q = []; return OBX.st.clear().then(() => { try { OBX.ch?.postMessage({clear: true}); } catch { /* closed */ } }, () => {}); }  // 2.143.0 C2 (#2153): a Promise (awaited before leaving the page)
// Background Sync: the service worker sends the queue once the device is online again (it leaves it to an open tab)
// 2.238.0 B (#2872): the offline copies belong to one sign-in. The knowledge pages' copy (wiki.js, IndexedDB "kalmido-wiki")
// carries the server's sign-in mark (me.sgen: session, password state, organisations); LS "wko" = {g, at} = that mark and the last
// online sync. Online with another mark, or 14 days without an online sync (also at an offline start), the copy goes. The outbox
// (own changes not sent yet) stays at a new sign-in of the same account (the server checks every entry when it is sent); it goes
// with the copy when the session is gone (401 / account disabled). 2.505 (#4298): an organisation of the account that is gone
// empties it no more: it goes out as usual, the private entries arrive, what the server refuses waits in the conflicts dialog.
const WKO_MAX_AGE = 14 * 864e5;
function wkoDrop() {
  LS.del('wko');
  if (typeof wko_reset === 'function') return wko_reset();
  if (globalThis.__wkoStore) return globalThis.__wkoStore.clear().catch(() => {});  // tests: the stand-in for IndexedDB
  return new Promise(ok => { try { const r = indexedDB.deleteDatabase('kalmido-wiki'); r.onsuccess = r.onerror = r.onblocked = () => ok(); } catch { ok(); } });
}
function startDrop() { LS.del('cache'); S.lpCache = null; if (typeof oc_drop === 'function') oc_drop(); else if (globalThis.indexedDB) { try { indexedDB.deleteDatabase('kalmido-start'); } catch { /* none */ } } }  // 2.663.0 (#4200): + its IndexedDB record
// 2.663.0 (#4200): the offline start state (S.lpCache) goes to IndexedDB when the browser is idle (offcache.js, loaded on demand);
// an own window (miniwin.js) writes none; without IndexedDB or the module localStorage as before
function startSave() {
  if (!S.lpCache || (typeof MW_ON !== 'undefined' && MW_ON)) return;
  if (typeof loadModule !== 'function' || !globalThis.indexedDB) { LS.set('cache', S.lpCache); return; }
  if (typeof oc_soon === 'function') { oc_soon(); return; }
  // the start fetches no module (p265_b): the first write waits for the idle preload (lazyload.js, 5 s), it takes the newest state then
  const wait = 6000 - performance.now();
  if (wait > 0) { if (!startSave.t) startSave.t = setTimeout(() => { startSave.t = 0; startSave(); }, wait); return; }
  loadModule('offcache').then(() => oc_soon(), e => { console.warn('Kalmido: offline start state: module not loaded, localStorage', e); if (S.lpCache) LS.set('cache', S.lpCache); });
}
async function startRead() {
  if (typeof loadModule === 'function' && globalThis.indexedDB) { try { await loadModule('offcache'); return await oc_get(); } catch (e) { console.warn('Kalmido: offline start state: module not loaded, localStorage', e); } }
  return LS.get('cache', null);
}
const wkoOld = m => !m || !(Date.now() - Date.parse(m.at) < WKO_MAX_AGE);
function sessGuard(me) {
  if (!me) return;
  const m = LS.get('wko', null);
  if (wkoOld(m) || m.g !== (me.sgen || '')) { wkoDrop(); startDrop(); LS.set('wko', {g: me.sgen || '', at: new Date().toISOString()}); }
}
// the session is gone (401 / account disabled at /api/state): the knowledge pages' copy goes before the sign-in page.
// 2.306.0 B (#2889): the outbox stays (authGone keeps what waits; it goes out after the next login of the same account)
// 2.360.2 (#3226): the offline start state (LS "cache", S.lpCache: all tasks of the last load) goes the same way; load() writes it anew
function sessGone() { startDrop(); return Promise.race([wkoDrop(), new Promise(ok => setTimeout(ok, 3000))]); }
function obxSyncReg() { if (OBX.on && navigator.serviceWorker?.ready) navigator.serviceWorker.ready.then(r => r.sync?.register('kalmido-outbox')).catch(() => {}); }
if (globalThis.navigator?.serviceWorker) navigator.serviceWorker.addEventListener('message', e => { if (e.data?.type === 'outbox-flush' && OUT.q.length) flush(); });
// 2.21.0 (#673): before the first render there is no top bar to update (renderTop on an empty state threw, so a start while
// the server was down showed the error page instead of the cached data); the boot's render shows the state
function setOnline(b) { if (OUT.online !== b) { OUT.online = b; if (S.booted) renderTop(); if (!b && S.booted && typeof botStartle === 'function') botStartle();  /* 2.165.0 (#2613) */ if (b) flush(); setTimeout(() => typeof staleDraw === 'function' && staleDraw(), 0); } }
// 2.13.4 (p210 flake, a real race): every write counts up when it starts and when it ends (S.wseq), so load() can tell that
// a write finished while its GET /api/state was on the way: that answer may predate the write and would undo it locally
// (S.settings went back to the old value; an Undo right after then saw "changed elsewhere" and skipped the step)
// 2.369.0 A (#3200): every page of GET /api/office/docs (a list that must not stop at one page; f: rawFetch or api)
async function docsAll(url, f = rawFetch) {
  const rows = [];
  for (let cur = null, i = 0; i < 200; i++) {
    const j = await f('GET', url + (cur ? `&before=${encodeURIComponent(cur)}` : ''));
    rows.push(...(j.docs || [])); cur = j.next_cursor;
    if (!cur) break;
  }
  return rows;
}
// 2.577.0 (#4638): the office's area open under "All workspaces" (#office/s/<space>) goes along with every /api/office/ request
// (header X-Kalmido-Office-Space, office/model.py office_space); '' = the server's choice from the setting workspace
const ofc_spOpen = () => S.route?.mod === 'office' && S.route.wsp && typeof wsCur === 'function' && wsCur() === 'all' ? S.route.wsp : '';
const ofc_spHdr = url => /^\/api\/(office\/|docs[/?])/.test(String(url || '')) ? ofc_spOpen() : '';  // 2.654.0 (#4823): + /api/docs/ (docs/area.py ar_office: receipts sorted into the open office)
// 2.577.0 (#4638, review): links, window.open, images and pdfView cannot send the header: the same area as ?_osp= (once);
// raw fetch() calls outside rawFetch0 go through ofc_spFetch (header); any <a href="/api/office/..."> gets it on its click
const ofc_spUrl = url => { const u = String(url || ''), sp = ofc_spHdr(u); return sp && !/[?&]_osp=/.test(u) ? `${u}${u.includes('?') ? '&' : '?'}_osp=${encodeURIComponent(sp)}` : u; };
const ofc_spFetch = (url, opt = {}) => { const sp = ofc_spHdr(url); if (sp) opt = {...opt, headers: {...(opt.headers || {}), 'X-Kalmido-Office-Space': sp}}; return fetch(url, opt); };
['click', 'auxclick', 'contextmenu'].forEach(t => document.addEventListener(t, e => {
  const a = e.target?.closest?.('a[href^="/api/office/"]'), h = a?.getAttribute('href'); if (!h) return;
  const u = ofc_spUrl(h); if (u !== h) a.setAttribute('href', u);
}, true));
async function rawFetch(method, url, body, key, osp) {  // key: 2.270.0 C (#3022) the outbox entry's idempotency key; osp: 2.577.0 (#4638) its office area
  // 2.64.1 (#1817): texts of a locked list leave encrypted, ciphers in answers become plain texts in memory (liste2e.js)
  if (typeof le2eOut === 'function') body = await le2eOut(method, url, body);
  const in_ = j => typeof le2eIn === 'function' ? le2eIn(j, url) : j;
  if (method === 'GET') return in_(await rawFetch0(method, url, body, undefined, osp));
  S.wseq = (S.wseq || 0) + 1;
  try { return in_(await rawFetch0(method, url, body, key, osp)); }
  catch (e) {  // 2.64.1 (#1817): a move missed texts (a subtask in the trash): fetched, converted, sent once more
    const b2 = e.data?.code === 'list_e2e_move' && e.data.need && typeof le2eFix === 'function' ? await le2eFix(url, body, e.data.need).catch(() => null) : null;
    if (!b2) throw e;
    return in_(await rawFetch0(method, url, b2, key, osp));
  } finally { S.wseq++; }
}
// 2.298.0 C (#3187): a status code in words when the server sent no text (413 / 429 / 5xx; any other stays "Error 404").
function httpErrText(st) {
  return st === 413 ? tr('File too large') : st === 429 ? tr('Too many requests, wait a moment') : st >= 500 ? tr('Server error, please try again later') : tr('Error {0}', st);
}
async function rawFetch0(method, url, body, key, osp) {
  const opt = {method, headers: {'X-Requested-With': 'kalmido'}, redirect: 'manual'};
  const sp = osp !== undefined ? osp : ofc_spHdr(url); if (sp) opt.headers['X-Kalmido-Office-Space'] = sp;  // 2.577.0 (#4638)
  if (key) opt.headers['Idempotency-Key'] = key;  // 2.270.0 C (#3022): a replay the server already applied comes back as its first answer
  const dev = wpDevHeader(url); if (dev) opt.headers['X-Kalmido-Device'] = dev;
  if (method !== 'GET' && S.me && S.me.kind !== 'agent') opt.headers['X-Kalmido-Device-Name'] = histDevice();  // 2.773.0 (#5250): the device of a step in the list "Recent steps" (undo.js)
  const un = (typeof oun_hdr === 'function' ? oun_hdr(method, url) : '') || (typeof obj_hdr === 'function' ? obj_hdr(method, url) : ''); if (un) opt.headers['X-Kalmido-Undo'] = un;  // 2.111.0 A (#2233): office_undo.js; 2.558.0 (#4709): objsave.js
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  let r;
  // 2.363.3 (#3134): a form with files of some size goes with a progress bar and Cancel (upbar.js); Cancel is no lost connection
  // 2.655.0 (#5045): an answer that arrives after the page is gone (its window closed: no document) goes nowhere: it never settles,
  // so no caller draws into a page that is not there (outFlush -> renderTop, chatReact, rel_load, ld_go -> applyState, ...)
  try { r = await (body instanceof FormData && typeof upSend === 'function' && upWanted(body) ? upSend(url, opt, body) : fetch(url, opt)); } catch (e) { if (!globalThis.document) return new Promise(() => {}); if (e.cancelled) throw e; const ch = OUT.down; OUT.down = false; setOnline(false); if (ch && S.booted) renderTop(); throw new Offline('offline'); }
  // 2.21.0 (#673): the device is online but the server is not (a proxy answers 502 / 503 / 504 without Kalmido's JSON): the
  // same as offline (cached data, changes wait), the hint says "server not reachable"; never a reload loop on a proxy page
  // 2.24.0 (#907): 503 (the proxy's maintenance page) or a notice of the kind "maintenance": "server in maintenance"
  // 2.359.0 A (#3023): an HTML page with a server error (500, a database restart) the same way (the change waits, no reload)
  // 2.360.2 L (#2561): the write lock of a key rotation too (JSON for API clients, the header X-Kalmido-Maint marks it)
  if (!globalThis.document) return new Promise(() => {});  // 2.655.0 (#5045)
  const ctype = r.headers.get('content-type') || '';
  if (([502, 503, 504].includes(r.status) || (r.status >= 500 && ctype.includes('text/html'))) && (!ctype.includes('application/json') || r.headers.get('X-Kalmido-Maint'))) { const ch = !OUT.down; OUT.down = true; OUT.maint = r.status === 503 || S.announce?.level === 'maintenance'; setOnline(false); if (ch && S.booted) renderTop(); throw new Offline('down'); }
  if (OUT.down) { OUT.down = false; if (S.booted && !OUT.online) renderTop(); }
  setOnline(true);
  // 2.359.0 A (#3023): an HTML 404 / 405 / 4xx (an address without a route, e.g. a temporary id; a proxy's page) is an error
  // like any other, never "session expired": the reload came back to the same write and reloaded again and again
  if (r.type !== 'opaqueredirect' && ctype.includes('text/html') && r.status >= 400 && r.status !== 401 && r.status !== 403) { const e = new Error(httpErrText(r.status)); e.status = r.status; e.data = {}; throw e; }
  // 2.359.0 A (#3024): the session ended in the middle of a write: the write and typed text not saved yet go into the queue
  // first (sent after the next sign-in of the same account; another account is asked first), then the page reloads
  const keepW = () => { if (key === undefined && method !== 'GET' && queueable(method, url) && !(body instanceof FormData)) outStash([{method, url, body: outPrev(method, url, body), uid: S.me?.id, k: outKey()}]); if (typeof savesStash === 'function') savesStash(false); };
  if (r.type === 'opaqueredirect' || ctype.includes('text/html')) {
    if (r.type === 'opaqueredirect' || r.status === 401 || r.status === 403) { keepW(); await authGone(); }  // 2.306.0 B (#2889); N25: not for any other page (captive portal, proxy error): only reload
    location.reload();  // login session expired -> login page
    throw new Error('auth');
  }
  const j = await r.json().catch(() => ({}));
  if (!globalThis.document) return new Promise(() => {});  // 2.655.0 (#5045): the page went while the body was read
  if (String(url).split('?')[0] === '/api/state' && (r.status === 401 || (r.status === 403 && j.auth))) await sessGone();  // 2.238.0 B (#2872); 2.369.2 (#3136): with its query (lz, auto)
  if ((r.status === 401 || r.status === 403) && j.auth) { keepW(); await authGone(); authScreen(j); throw new Error('auth'); }  // built-in login
  if (r.status === 401) { keepW(); await authGone(); location.reload(); throw new Error('auth'); }
  if (!r.ok) { const e = new Error(j.error || httpErrText(r.status)); e.status = r.status; e.data = j;
    if ((method !== 'GET' || r.status >= 500) && typeof botStartle === 'function') botStartle();  // 2.165.0 (#2613): a refused write or a server error
    if (j.code === 'quota_exceeded') { e.shown = true; setTimeout(() => quotaDialog(j), 0); }  // 2.24.0 (#910): storage full
    if (j.code === 'agent_bridge') e.shown = true;  // 2.30.0 (#919): bridgeTry asks and repeats it
    if (j.code === 'support_session') e.message = tr('Not possible in a support session') + (j.error ? ': ' + j.error : '');  // 2.538.0 (#4365)
    if (j.pin && S.me?.kid) { e.shown = true; kd_pinClosed(); }  // 2.49.0 (#1551): the PIN time ran out: ask again
    throw e; }
  if (method !== 'GET' && typeof oun_ok === 'function') oun_ok(method, url, j);  // 2.111.0 A (#2233)
  if (method !== 'GET' && typeof lpOwnNote === 'function') lpOwnNote(r.headers.get('X-Kalmido-Lv'));  // 2.280.0 A (#3109): liveparts.js
  return j;
}
// 2.284.2: a job number read from a chat text / a job tag / the address: only a positive whole number is asked for (never 0,
// NaN or "undefined"); such lookups go through rawFetch (no toast: they run in the background on every drawing)
const jobNoOk = n => Number.isInteger(n) && n > 0 && n <= 2147483647;
const queueable = (method, url) => method !== 'GET' && /^\/api\/(tasks|habits\/\d+\/log|time\/(start|stop|entries))/.test(url) && !/\/(comments|seen|timeline)$/.test(url);
// 2.25.0 (UX-56): a write of the open task that reached the server shows "Saved" in its header for a moment
const savedPingOff = debounce(el => el.classList.remove('on'), 1600);  // 2.599.0 (#4506)
function savedPing() {
  const top = S.sel && $('#detail .dtop'); if (!top) return;
  let el = $('.dsaved', top);
  if (!el) { el = document.createElement('span'); el.className = 'dsaved'; el.setAttribute('role', 'status'); (top.querySelector('.spacer') || top.lastElementChild).after(el); }
  el.innerHTML = `${ic('check', 's')}<span>${esc(tr('Saved'))}</span>`; el.classList.add('on');
  savedPingOff(el);
}
// 2.298.0 A1 (#3186): a field that saves itself confirms with a quiet tick right after it (no toast over the bottom bar);
// screen readers hear "Saved". el = the field or a selector (looked up again after a redraw); no field on the page = the toast
function savedTick(el, again) {
  if (typeof el === 'string' || (el && !el.isConnected && el.id)) el = $(typeof el === 'string' ? el : '#' + CSS.escape(el.id));
  if (!el?.isConnected || el === document.body || el === document.documentElement) { if (!again) toast(tr('Saved')); return; }
  const at = el.closest('label') || el, id = el.id;
  let m = at.nextElementSibling?.classList.contains('svtick') ? at.nextElementSibling : null;
  if (!m) { m = document.createElement('span'); m.className = 'svtick'; at.after(m); }
  m.innerHTML = `${ic('check', 's')}<span class="sr">${esc(tr('Saved'))}</span>`; m.classList.remove('on'); void m.offsetWidth; m.classList.add('on');
  if (!again && typeof announce === 'function') announce(tr('Saved'));
  clearTimeout(m._t); m._t = setTimeout(() => m.remove(), 2200);
  // a redraw right after the save (a reload of the view) replaces the field: the tick follows it to the new one
  const follow = n => setTimeout(() => { if (m.isConnected) { if (n < 2) follow(n + 1); return; } const x = id && document.getElementById(id); if (x && x !== el) savedTick(x, true); }, [150, 400, 900][n]);
  if (!again && id) follow(0);
}
/** @param {string} method @param {string} url @param {any} [body] @returns {Promise<any>} */  // 2.102.0 (#1995)
async function api(method, url, body) {
  const lk = tlkGuard(method, url, body); if (lk) throw lk;  // 2.36.0 (#1118)
  // 2.64.1 (#1817): encrypted before the outbox (it holds ciphers only); a Promise only when there is something to encrypt, so
  // an offline edit is still applied locally at once
  const lo = typeof le2eOut === 'function' ? le2eOut(method, url, body) : body;
  if (lo instanceof Promise) { try { body = await lo; } catch (e) { if (e.message !== 'auth') { toast(e.message); e.shown = true; } throw e; } } else body = lo;  // 2.855.0 (#5451): said once
  // 2.126.0 D (#1990): a new task carries its own id from the first try on: sent again (the answer got lost) = the same task
  if (method === 'POST' && url === '/api/tasks' && body && typeof body === 'object' && !(body instanceof FormData) && !body.client_ref) body = {...body, client_ref: Date.now().toString(36) + Math.random().toString(36).slice(2, 10)};
  // 2.359.0 A (#3023): a temporary id (created offline) never goes to the server as such: the real id once its create went out,
  // behind the create while it still waits; a create that failed = the change waits in the conflicts dialog (its text kept)
  const tu = tmpUrl(url);
  if (tu === null && method !== 'GET' && queueable(method, url) && !(body instanceof FormData)) return enqueue(method, url, body);
  if (tu === null || tu === false) {
    const e = new Error(tu === null ? tr('Still syncing, try again in a moment') : tr('The new task could not be created, the change was not saved')); e.status = 409; e.data = {code: 'tmp_id'};
    if (method !== 'GET') { if (tu === false) { outReject({method, url, body}, e); renderTop(); } toast(e.message); }
    e.shown = true; throw e;
  }
  url = tu;
  if (queueable(method, url) && !(body instanceof FormData) && OUT.q.length) return enqueue(method, url, body);
  if (outNow(method, url, body)) {  // 2.537.0 (#4568)
    // 2.549.0 (#4568, #4305 A9): the base as an online change had it (oxbPrev: a custom field on its own, a value already shown
    // is no base); without one an empty _prev, so the queue adds none of its own (a caller's own _prev stays as it is; offline
    // the queue's own as before)
    const ob = body._prev || !OUT.online ? body : (o => o.on ? o.body : {...body, _prev: {}})(oxbPrev(method, url, body));
    const r = enqueue(method, url, ob);
    if (OUT.online && r?._q) r._q.live = 1;  // 2.551.0 (#4649): sent online: a refusal of its first try is said as api() said it (outFlush); offline after all / a later try = the dialog as before
    if (OUT.online && S.sel && url === '/api/tasks/' + S.sel) savedPing(); return r;
  }
  const ox = oxbPrev(method, url, body); body = ox.body;  // 2.528.0 B (#4305)
  try { let j = await rawFetch(method, url, body, oxaKey(body)); if (ox.on && j?.conflicts?.length && typeof le2eRekeyConflicts === 'function') j = await le2eRekeyConflicts(url, body, j, b2 => rawFetch(method, url, b2));  // 2.543.0 (#4632): a key change is no conflict
    if (ox.on && j?.conflicts?.length) addConflicts(j.id || +url.split('/').pop(), j.conflicts, j.title); if (method !== 'GET' && S.sel && new RegExp(`^/api/tasks/${S.sel}(/|$)`).test(url)) savedPing(); return method === 'GET' ? mvResp(url, j) : j; }  // 2.436.0 (#3620)
  catch (e) {
    if (e instanceof Offline) {
      if (queueable(method, url) && !(body instanceof FormData)) return enqueue(method, url, body);
      if (method !== 'GET') { toast(tr('Offline: only works again with a connection')); e.shown = true; }  // 2.855.0 (#5451)
    } else if (e.message !== 'auth' && !e.shown) {
      if (e.data?.out_request && typeof oor_ask === 'function') toast(e.message, () => oor_ask(e.data.out_request), 10000, tr('Ask an admin'));  // 2.361.2 (#2923)
      else toast(e.message);
      e.shown = true;  // 2.855.0 (#5451): said once - a caller's catch sees it (office.js ofcErr)
    }
    throw e;
  }
}
// 2.566.0 (#4704): an undo (or redo) of a save as a second write that never overwrites what someone else saved meanwhile:
// only the keys this step changed go back (old = the values before, o.now = what the save sent; without o.now all of old),
// with expect_updated_at = seenAt (the updated_at of the own save's answer; empty = an old row without one, no check).
// o.method PATCH (default) | PUT, o.full = all of old (a PUT route that needs the whole state), o.label = what the message
// names, o.hist = a history step (no own message: it returns {none, skipped}), o.verKey = a route with its own version key
// (the events: expect; their 409 carries no state). -> the answer; changed since (409 with the current state, or any 409
// of a verKey route) -> null and "Changed elsewhere, not undone"; any other error is said and thrown (like api())
async function undoWrite(url, old, seenAt, o = {}) {
  const now = o.now, back = {};
  for (const k of Object.keys(old || {})) if (o.full || !now || (k in now && JSON.stringify(old[k] ?? null) !== JSON.stringify(now[k] ?? null))) back[k] = old[k];
  if (!Object.keys(back).length && !o.full) return {};  // nothing changed: nothing to send (o.full: a POST without fields)
  try { return await rawFetch(o.method || 'PATCH', url, seenAt ? {...back, [o.verKey || 'expect_updated_at']: seenAt} : back); }
  catch (x) {
    if (x?.status === 409 && ((o.verKey && seenAt) || (x.data && Object.keys(x.data).some(k => k !== 'error' && k !== 'code')))) {
      if (!o.hist) toast(o.label ? tr('Changed elsewhere, not undone: {0}', o.label) : tr('Changed elsewhere, not undone'));
      return null;
    }
    if (x instanceof Offline) toast(tr('Offline: only works again with a connection'));
    else if (x?.message !== 'auth' && !x?.shown) toast(x?.message || tr('unknown'));
    if (x) x.shown = true;
    throw x;
  }
}
// the same as a history step's undo / redo: changed since -> {none, skipped: [label]} (histStep says "Changed elsewhere, not
// undone: …" and drops the step); ok -> {} (j = the answer through o.then)
async function undoStep(url, old, seenAt, o = {}) {
  const j = await undoWrite(url, old, seenAt, {...o, hist: true});
  if (j === null) return {none: true, skipped: [o.label || tr('Change')]};
  if (o.then) await o.then(j);
  return {};
}
// 2.436.0 (#3620): "View as member": the one place the own admin marks read as a member's (display only; settings.js mvSet)
const MV = {me: null};
const mvOn = () => S.settings?.member_view === '1';
const mvOrg = o => o?.role === 'admin' ? {...o, role: 'member', real_role: 'admin'} : o;
const mvMe = me => me ? {...me, real_admin: !!me.is_admin, is_admin: false, ...(Array.isArray(me.workspaces) ? {workspaces: me.workspaces.map(mvOrg)} : {})} : me;
function mvResp(url, j) {
  if (!j || typeof j !== 'object') return j;
  const p = String(url).split('?')[0];
  if (p === '/api/state') { if (j.me) MV.me = j.me; return j.me && j.settings?.member_view === '1' ? {...j, me: mvMe(j.me)} : j; }
  if (!mvOn()) return j;
  if (p === '/api/me') return mvMe(j);
  return p === '/api/orgs' && Array.isArray(j.orgs) ? {...j, orgs: j.orgs.map(mvOrg)} : j;
}
// 2.359.0 A (#3023): the address with a temporary id replaced: the real id once its create went out (this tab or another,
// the service worker); null = its create still waits in the queue; false = no create waits for it (it failed)
function tmpUrl(url) {
  const m = url.match(/\/(-\d+)(?=[/?]|$)/); if (!m) return url;
  const real = HIST.ids[m[1]] || LS.get('idmap', {})[m[1]];
  if (real) return url.replace(m[0], '/' + real);
  return outSync().some(x => x.tmp === +m[1] && !x.done) ? null : false;
}
// remember what this device saw before the edit, so the server can detect edits made elsewhere
function outPrev(method, url, body) {
  const pm = method === 'PATCH' && url.match(/^\/api\/tasks\/(-?\d+)$/);
  if (pm && body && typeof body === 'object' && !body._prev && +pm[1] > 0) {
    const t = S.tasks.get(+pm[1]);
    if (t) body = {...body, _prev: Object.fromEntries(Object.keys(body).filter(k => !k.startsWith('_')).map(k => [k, k === 'tags' ? [...(t.tags || [])] : t._enc && k in t._enc ? t._enc[k] : (t[k] ?? null)]))};  // 2.64.1 (#1817): a locked list's text = its cipher
  }
  return body;
}
// 2.528.0 B (#4305): an online change of a task carries what this device saw (_prev) like the queue does, so a field changed on
// another device meanwhile is kept and lands in the conflicts dialog instead of being overwritten. A field whose seen value
// equals its new one is no base (a caller showed the change before sending it) and stays out (last write, as before).
// on = the _prev was added here: its conflicts go into the dialog (callers with their own _prev handle theirs)
// a custom field's value as the server has it (a locked list: its cipher, the others as they are)
const oxbField = (t, fk) => t?._enc?.fields?.[fk] ?? t?.fields?.[fk] ?? null;
function oxbPrev(method, url, body) {
  const b = outPrev(method, url, body);
  if (b === body || !b?._prev) return {body, on: false};
  const same = (x, y) => JSON.stringify(Array.isArray(x) ? [...x].map(String).sort() : x ?? null) === JSON.stringify(Array.isArray(y) ? [...y].map(String).sort() : y ?? null);
  const p = {};
  for (const [k, v] of Object.entries(b._prev)) {
    if (k === 'sort') continue;  // a position is never a conflict (as batch / reorder)
    if (k === 'fields') {
      const nf = b.fields && typeof b.fields === 'object' ? b.fields : {}, t = S.tasks.get(+url.split('/').pop());
      const f = Object.fromEntries(Object.keys(nf).map(fk => [fk, oxbField(t, fk)]).filter(([fk, o]) => !same(o, nf[fk] ?? null)));
      if (Object.keys(f).length) p.fields = f;
    } else if (!same(v, b[k])) p[k] = v;
  }
  if (!Object.keys(p).length) return {body, on: false};
  return {body: {...body, _prev: p}, on: true};
}
// 2.359.0 A (#3024): entries that must survive a page going away right now (pagehide, an ended session before the reload):
// without IndexedDB straight into the queue (localStorage), with it into localStorage first, which the IndexedDB queue takes
// over (obxAdopt: now, and at the next start should the page be gone before its write)
function outStash(list) {
  if (!list.length) return;
  // 2.359.0 (review): numbered, so they go after what already waits (obxAdopt)
  if (OBX.on) { LS.set('outbox', [...LS.get('outbox', []), ...list.map(x => ({...x, n: x.n ?? obxSeq()}))]); obxAdopt(); } else outSave(() => OUT.q.push(...list));
}
// a write that outlives the page: fetch with keepalive (sent after the tab closed; the browser allows about 64 KB per page),
// the queue entry's key with it: the queued copy sent at the next start gets the server's first answer (never applied twice)
function keepSend(method, url, body, key) {
  const h = key ? {'Idempotency-Key': key} : {};
  try { fetch(url, {method, keepalive: true, credentials: 'same-origin', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido', ...h}, body: JSON.stringify(body)}).catch(() => {}); return true; } catch { return false; }
}
// a write that waits for its debounce (notes, the diary): into the queue and out with keepalive (url without a temporary id)
function outKeep(method, url, body) {
  const e = {method, url, body, uid: S.me?.id, k: outKey()};
  outStash([e]);
  if (!/\/-\d+(?=[/?]|$)/.test(url)) keepSend(method, url, body, e.k);
  return e;
}
// 2.538.0 (#4369): the queue entries of one organisation (its projects, their tasks, /api/orgs/<id>/..., org_id in the body), also
// what hangs on a task created offline in one of its projects; entries on their way (sending) are left to the flush
function outOrgEntries(oid) {
  const lists = new Set(S.lists.filter(l => l.org_id === oid).map(l => l.id)), tasks = new Set();
  for (const t of S.tasks.values()) if (lists.has(t.list_id)) tasks.add(t.id);
  const tmps = new Set(), mine = e => {
    const u = String(e.url || ''), m = u.match(/^\/api\/(tasks|lists)\/(-?\d+)/), b = e.body && typeof e.body === 'object' ? e.body : {};
    return u.startsWith(`/api/orgs/${oid}/`) || b.org_id === oid || lists.has(b.list_id) || (!!m && (m[1] === 'lists' ? lists.has(+m[2]) : tasks.has(+m[2]) || tmps.has(+m[2])));
  };
  const out = [];
  for (const e of outSync()) if (!e.done && !e.sending && mine(e)) { out.push(e); if (e.tmp) tmps.add(+e.tmp); }
  return out.length ? outSync().filter(e => !e.done && !e.sending && (out.includes(e) || mine(e))) : out;
}
function outOrgDrop(oid) {
  const gone = new Set(outOrgEntries(oid));
  if (!gone.size) return 0;
  outSave(() => { OUT.q = OUT.q.filter(x => !gone.has(x)); });
  if (typeof renderTop === 'function' && S.booted) renderTop();
  return gone.size;
}
// ------------------------------------------------------------------ kept input (2.527.0 #4304 A5 + A6)
// Input that is not on the server yet and has no offline queue behind it (a dialog, a comment, a setting, a letter) is kept
// in this browser (localStorage, per account, the "tasks." prefix: gone at logout / another account) until the server has
// it: it survives the sign-in page of an ended session (401 -> reload), a closed tab and a failed save. The pattern of the
// letters (2.269.0 C #3017, office_letters.js). kind names the form ('ltpend' letters, 'fdf' dialogs (formguard.js fdDialog),
// 'fdc' comment drafts, 'fdw' kept writes), id the record; base = the server's updated_at the input builds on.
const FD_KINDS = ['ltpend', 'fdf', 'fdc', 'fdw'];
// review (#4304): before /api/me answered (a 401 at the start) the account of this browser (uid), else authGone found nothing and wiped
const FD_KEY = (kind, id) => `tasks.${kind}.${S.me?.id || LS.get('uid', 0) || 0}.${id}`;
function fdKeep(kind, id, b, base = '') { try { localStorage.setItem(FD_KEY(kind, id), JSON.stringify({base: base || '', b, at: Date.now()})); } catch { /* full or private mode */ } }
function fdGet(kind, id) { try { return JSON.parse(localStorage.getItem(FD_KEY(kind, id)) || 'null'); } catch { return null; } }
function fdDrop(kind, id) { try { localStorage.removeItem(FD_KEY(kind, id)); } catch { /* private mode */ } }
// the kept records of a kind of this account: [{id, base, b, at}]
function fdList(kind) {
  const pre = FD_KEY(kind, ''), out = [];
  try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k?.startsWith(pre)) { const r = fdGet(kind, k.slice(pre.length)); if (r) out.push({...r, id: k.slice(pre.length)}); } } } catch { /* no storage */ }
  return out;
}
const fdAny = () => FD_KINDS.some(k => fdList(k).length > 0);
// the kept input while it is still news: none when the server has it already (cur: every kept field equal) or the record
// was saved elsewhere since (base differs: dropped, with the hint "Changed in the meantime")
function fdTake(kind, id, cur, base) {
  const k = fdGet(kind, id);
  if (k == null || k.b == null) { if (k) fdDrop(kind, id); return null; }
  if (cur && typeof k.b === 'object' && Object.keys(k.b).every(x => String(k.b[x] ?? '') === String(cur[x] ?? ''))) { fdDrop(kind, id); return null; }
  if (base !== undefined && k.base !== (base || '')) { fdDrop(kind, id); toast(tr('Changed in the meantime')); return null; }
  return k.b;
}
// a write that has no queue (settings, a list's dialog): out with keepalive at once AND kept here under the same key, so it is
// sent again after the next sign-in / start (fdWriteFlush; the server answers a repeat of the key with its first answer).
// o.sv = {setting: value seen before}: a setting changed elsewhere meanwhile is not overwritten by the kept one; o.slot = the
// record's name (a newer write of the same form replaces it), o.send = false: only kept (the caller sends it and drops the
// slot when the server has it). Returns the slot.
function fdWrite(method, url, body, o = {}) {
  const k = outKey(), slot = o.slot || k;
  fdKeep('fdw', slot, {method, url, body, k, ...(o.sv ? {sv: o.sv} : {})});
  if (o.send !== false) keepSend(method, url, body, k);
  return slot;
}
async function fdWriteFlush() {
  if (fdWriteFlush.busy || !S.me) return;
  fdWriteFlush.busy = true;
  try {
    for (const r of fdList('fdw').sort((a, b) => a.at - b.at)) {
      let body = r.b?.body;
      if (r.b?.sv && body && typeof body === 'object') {  // a setting someone changed elsewhere since stays theirs
        const cur = r.b.url === '/api/me' ? S.me : S.settings;  // review (#4304): the name too (sv = what the page saw)
        body = Object.fromEntries(Object.entries(body).filter(([k, v]) => String(cur?.[k] ?? '') === String(r.b.sv[k] ?? '') && String(cur?.[k] ?? '') !== String(v ?? '')));
        if (!Object.keys(body).length) { fdDrop('fdw', r.id); continue; }
      }
      // 2.552.0 (#4547): 'fdw-sent' tells the open view (a document, a table) that a kept write went out (detail: url, res or err)
      const sent = d => window.dispatchEvent(new CustomEvent('fdw-sent', {detail: {url: r.b.url, ...d}}));
      try { const res = await rawFetch(r.b.method, r.b.url, body, r.b.k || r.id); fdDrop('fdw', r.id); sent({res}); }
      catch (e) { if (e instanceof Offline || e.message === 'auth') return; if (!(e.status >= 500 || e.status === 429 || e.status === 408)) { fdDrop('fdw', r.id); sent({err: e}); } }
    }
  } finally { fdWriteFlush.busy = false; }
}
window.addEventListener('online', () => setTimeout(fdWriteFlush, 500));
// 2.537.0 (#4568): a change of one task (title, description, dates, tags, fields, priority, assignees ...) goes into the outbox
// online too: shown and kept here at once, the server gets it in the background and its answer follows (outLater). Not: a
// locked list (only ciphers leave, straight to the server as before), a move to another list / organisation, a task this page
// does not hold, steps the server works out itself (_act, le2e_move, snippets). Deleting is no PATCH.
function outNow(method, url, body) {
  const m = method === 'PATCH' && /^\/api\/tasks\/(\d+)$/.exec(url);
  if (!m || !body || typeof body !== 'object' || body instanceof FormData) return false;
  const t = S.tasks.get(+m[1]); if (!t || t._enc) return false;
  if ((typeof LE2E === 'object' && LE2E.on.has(t.list_id)) || (typeof listById === 'function' && listById(t.list_id)?.e2e)) return false;
  if ((body.list_id != null && body.list_id !== t.list_id) || 'org_id' in body) return false;
  return !['_act', 'le2e_move', 'snippets'].some(k => k in body);
}
// 2.537.0 (#4568): the server's answer to an outbox entry, for the one who wrote it (the dependent tasks a date moved along,
// shifted / chain): a Promise of the answer, null when the change was refused (it waits in the conflicts dialog) or this page
// went away first (the entry lives on, its waiter not)
const OUT_LATER = new Map();
function outLater(e) {
  if (!e?.k) return Promise.resolve(null);
  if (e.done) return Promise.resolve(e.res || null);
  let w = OUT_LATER.get(e.k);
  if (!w) { let res; const p = new Promise(r => { res = r; }); w = {p, res}; OUT_LATER.set(e.k, w); }
  return w.p;
}
// 2.551.0 (#4649): for a caller that keeps a typed value when its save fails: a Promise of the server's refusal (an Error) of
// the change r stands for (r = what api() gave back, r._q its outbox entry), null once it is saved or waits for another try
function outFail(r) {
  const e = r?._q; if (!e?.live) return Promise.resolve(null);
  return outLater(e).then(j => j ? null : e.err || null);
}
// an entry's answer came (j) or it was refused (null): its waiter gets it; a task's own answer is put in place (the server's
// computed fields), when no newer change of the same task waits behind it. true = settled, no whole new state needed.
function outAnswer(e, j) {
  const w = OUT_LATER.get(e.k); if (w) { OUT_LATER.delete(e.k); w.res(j); }
  // 2.551.0 (#4650): the calendar's ghosts of a recurring task were maybe fetched before the server had its new repeat / date
  // (calendar.js ensureOcc): asked again with the next drawing, one still on its way is dropped
  if (S.occ && e.method === 'PATCH' && /^\/api\/tasks\/\d+$/.test(e.url) && ['repeat', 'repeat_from', 'due', 'status'].some(k => k in (e.body || {}))) { S.occ.key = ''; S.occ.want = ''; }
  const m = j && e.method === 'PATCH' && /^\/api\/tasks\/(\d+)$/.exec(e.url);
  if (!m || j.id !== +m[1] || j.shifted?.length || j.chain?.skipped?.length) return false;
  if (j.conflicts?.length) {  // the calm bar under the field the detail shows (as a save straight from the detail did)
    const keep = {...j};
    for (const c of j.conflicts) {
      const el = (c.field === 'title' || c.field === 'content') && S.sel === j.id && $(c.field === 'title' ? '#d-title' : '#d-content');
      if (!el) continue;
      if (document.activeElement === el) keep[c.field] = el.value;  // the draft stays where it is typed
      setTimeout(() => cfInline(j.id, c.field, c, el.value), 0);
    }
    if (!OUT.q.some(x => x.url === e.url)) putTask(keep);
    return false;
  }
  if (!OUT.q.some(x => x.url === e.url)) putTask(j);
  return true;
}
function enqueue(method, url, body) {
  body = outPrev(method, url, body);
  const pm = method === 'PATCH' && url.match(/^\/api\/tasks\/(-?\d+)$/);
  // 2.13.0 (#453): typed text waiting in the outbox is coalesced: a newer title / description of the same task replaces
  // the queued one (which keeps its _prev = the base the server last confirmed), so a replay sends only the latest text
  const tk = pm && body ? Object.keys(body).filter(k => !k.startsWith('_')) : [];
  if (tk.length === 1 && (tk[0] === 'title' || tk[0] === 'content')) {
    const q = outSync().find((x, i) => (i > 0 || !OUT.flushing) && !x.sending && x.method === 'PATCH' && x.url === url && !x.done && Object.keys(x.body || {}).filter(k => !k.startsWith('_')).join() === tk[0]);  // 2.126.0 D (#1989): sending = on its way from another tab
    if (q) { outSave(() => { q.body = {...q.body, [tk[0]]: body[tk[0]]}; }); return applyLocal({method, url, body}); }  // 2.143.0 C (#2153): outSave (IndexedDB)
  }
  // 2.363.3 (#3133): a whole new order of "My tasks" replaces the one still waiting, whose _prev stays the base the server confirmed
  const mo = method === 'PUT' && url === '/api/tasks/mine-order' && outSync().find((x, i) => (i > 0 || !OUT.flushing) && !x.sending && !x.done && x.url === url);
  if (mo) { outSave(() => { mo.body = {...mo.body, ids: body.ids}; }); return {ok: true}; }
  const e = {method, url, body, uid: S.me?.id, k: oxaKey(body) || outKey()};  // 2.528.0 (#4305 B1): the key the press chose
  const osp = ofc_spHdr(url); if (osp) e.osp = osp;  // 2.577.0 (#4638): a change sent later lands in the office it was made in
  if (method === 'POST' && (url === '/api/tasks' || /^\/api\/lists\/\d+\/notes$/.test(url))) e.tmp = -Date.now() - Math.floor(Math.random() * 1000);  // 2.143.0 C (#2153): + a note
  outSave(() => OUT.q.push(e));  // 2.126.0 D (#1989)
  obxSyncReg();  // 2.143.0 C (#2153)
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
  if (typeof ntLocal === 'function' && NT_URL.test(url)) return ntLocal(e);  // 2.143.0 C (#2153): notes (chat.js)
  if (method === 'POST' && url === '/api/tasks') {
    const par = body.parent_id && S.tasks.get(body.parent_id);
    const t = {id: e.tmp, list_id: body.list_id || (par ? par.list_id : inbox().id), section_id: body.section_id ?? null, parent_id: body.parent_id ?? null,
      title: body.title, content: body.content || '', priority: body.priority || 0, status: 0, due: body.due || null, due_time: body.due_time || null, start: body.start || null,  // 2.18.0 (#431): a range drawn in the timeline offline
      reminders: body.reminders || '', repeat: body.repeat || '', repeat_from: body.repeat_from || 'due', url: body.url || null,
      sort: par ? 1e9 : Math.min(0, ...[...S.tasks.values()].map(x => x.sort)) - 1,
      created_at: nowIso, updated_at: nowIso, completed_at: null, deleted_at: null, tags: body.tags || [], fields: body.fields || {}, blocked: 0, blockers: [], blocking: 0,
      ...(body.ms ? {ms: 1} : {}), ...(body.milestone_id ? {milestone_id: body.milestone_id} : {}),  // 2.18.0 (#430)
      ...(body.fam ? {fam: body.fam} : {})};  // 2.140.0 A (#2131): the amount of an item added offline in shopping mode
    S.tasks.set(t.id, t); return t;
  }
  if (url === '/api/tasks/batch') {
    for (const tid of body.ids || []) {
      const t = S.tasks.get(tid); if (!t) continue;
      if (body.action === 'patch') { const {add_tags, prev, ...d} = body.data || {}; Object.assign(t, d); if (add_tags) t.tags = [...new Set([...t.tags, ...add_tags])]; }  // 2.270.0 D (#3028): prev = what it saw
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
  if (url === '/api/tasks/reorder') { for (const {_prev, ...it} of body.items || []) { const t = S.tasks.get(it.id); if (t) Object.assign(t, it); } return {ok: true}; }  // 2.270.0 D (#3028)
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
  if (OUT.flushing || !outSync().length) return;
  if (OUT.retryAt && Date.now() < OUT.retryAt) return;  // 2.359.0 A (#3023): after a server error the next try waits (outRetry)
  // 2.126.0 D (#1992 O5): only once the server has said who is logged in on this page (load() comes back here)
  if (!S.me || OUT.me !== S.me.id) { if (!OUT.meCheck) { OUT.meCheck = true; load().catch(() => {}).finally(() => { OUT.meCheck = false; }); } return; }
  // 2.126.0 D (#1989): one tab of the browser replays the queue, the others see it shrink (without Web Locks: as before)
  if (navigator.locks) return navigator.locks.request('kalmido-outbox', {ifAvailable: true}, l => l && !OUT.flushing ? outFlush() : null);
  return outFlush();
}
async function outFlush() {
  OUT.flushing = true;
  netDotDraw();  // 2.31.0 (#378): yellow while the changes go out
  const fix = v => (typeof v === 'number' && v < 0 && idmap[v]) ? idmap[v] : v;
  const idmap = LS.get('idmap', {});
  let dropped = 0, wdropped = 0, skipped = 0, sent = 0, sentNt = 0;
  const ntU = u => typeof NT_URL === 'object' && NT_URL.test(u);  // 2.536.0 (#4567): a note's address (chat.js, not on every page)
  let sentTk = 0;  // 2.537.0 (#4568): changes of a task whose answer settled it (outAnswer): no whole new state for them
  const refused = [];  // 2.551.0 (#4649): changes sent online the server refused (said at once): the page takes the server's state, then their callers hear it
  try {
    while (outSync().length) {
      const e = OUT.q[0];
      if (e.uid && S.me && e.uid !== S.me.id) { outSave(() => { OUT.q = OUT.q.filter(x => x !== e); }); continue; }  // another user's op
      outSave(() => { e.sending = 1; });
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
      // 2.359.0 A (#3023): a temporary id still in the entry: its create failed (a create always waits ahead of its changes) ->
      // not sent (no PATCH /api/tasks/-123), the change waits in the conflicts dialog
      const tmpLeft = /\/-\d+(?=[/?]|$)/.test(url) || [body?.parent_id, body?.task_id, ...(body?.ids || []), ...(body?.items || []).map(it => it?.id)].some(v => typeof v === 'number' && v < 0);
      if (tmpLeft) { console.warn('outbox: its new task was not created', e); dropped++; outReject(e, new Error(tr('The new task could not be created'))); outSave(() => { OUT.q = OUT.q.filter(x => x !== e); }); e.res = null; e.done = true; outAnswer(e, null); continue; }
      const wiki = /^\/api\/wiki\/pages\/\d+$/.test(e.url);  // 2.169.0 (#2671): a knowledge page's text (wiki.js, loaded for it)
      if (wiki && typeof wkoSent !== 'function' && typeof loadModule === 'function') await loadModule('wiki').catch(() => {});
      if (wiki && typeof wkoReseal === 'function') body = await wkoReseal(e).catch(() => body);  // 2.577.0 (#4708 9): the current key generation
      try {
        let j = await rawFetch(e.method, url, body, e.ik || e.k, e.osp || '');  // 2.577.0 (#4638): + its office area (never the one open now)  // 2.270.0 C (#3022): the same key as the service worker's send; 2.551.0 (#4646): ik = the rebased send's own
        sent++; OUT.tries = 0; OUT.retryAt = 0;
        if (ntU(e.url)) sentNt++;  // 2.536.0 (#4567): a note's change (they go out online too now)
        if (wiki && typeof wkoSent === 'function') await wkoSent(e, j).catch(() => {});
        if (typeof ntSent === 'function' && NT_URL.test(e.url)) ntSent(e, j);  // 2.143.0 C (#2153): notes (chat.js)
        if (e.tmp) { idmap[e.tmp] = j.id; HIST.ids[e.tmp] = j.id; LS.set('idmap', idmap); obxMeta('idmap', idmap); if (S.sel === e.tmp) S.sel = j.id; }  // 2.143.0 C (#2153): the service worker maps with it too
        if (j && j.conflicts?.length && e.url === '/api/tasks/batch' && body?.action === 'complete') { skipped++; j.conflicts = []; }  // 2.270.0 C (#3022): already ticked = not advanced twice
        if (j && j.conflicts?.length && typeof le2eRekeyConflicts === 'function') j = await le2eRekeyConflicts(url, body, j, b2 => rawFetch(e.method, url, b2));  // 2.543.0 (#4632): a key change is no conflict
        if (j && j.conflicts?.length) {
          // 2.13.0: a "conflict" with a text this device sent itself (its answer got lost) is replayed on top of it
          const own = j.conflicts.filter(c => ownVal(cfTid(c, j.id) + ':' + c.field, c.server) && body && c.field in body);  // 2.527.0 (#4304): the entry's task
          // 2.551.0 (#4646): with a new idempotency key (the same one would only bring back the stored answer with its conflict)
          if (own.length === j.conflicts.length && !e.rebased) { outSave(() => { e.rebased = true; e.ik = outKey(); e.body = {...body, _prev: Object.fromEntries(own.map(c => [c.field, c.server]))}; }); continue; }
          addConflicts(j.id, j.conflicts, j.title);
        }
        if (j && j.skipped) skipped++;
        if (j?.link_waits) toast(tr(ML_WAITS));  // 2.363.3 (#3133): "also in" sent after a move: kept for the way back
        if (j?.order_kept) toast(tr(MO_KEPT));  // 2.363.3 (#3133)
        outSave(() => { OUT.q = OUT.q.filter(x => x !== e); });  // 2.126.0 D (#1989): out of the shared queue first
        e.res = j; if (e.tries) outUnsaved(e, false);  // 2.574.0 (#4589)
        if (outAnswer(e, j)) sentTk++;  // 2.537.0 (#4568): the answer for the one who wrote it
      } catch (err) {
        if (err instanceof Offline || err.message === 'auth') { outSave(() => { delete e.sending; delete e.live; }); if (err instanceof Offline) flushSoon(); return; }  // 2.25.0 (UX-55): try again in 2 s
        // 2.359.0 A (#3023): a server error (5xx, the maintenance / restore 503, too many requests 429, a timeout 408) is no
        // answer about the change: it stays first in the queue and goes again later (the idempotency key keeps a write the
        // server did apply from being applied twice). Only an entry that failed with a 500 OUT_MAX_TRIES times in a row goes
        // to the conflicts dialog (with its whole content), so it does not hold back everything behind it forever.
        const st = err.status || 0;
        if (st >= 500 || st === 429 || st === 408) {
          const tries = (e.tries || 0) + 1;
          if (st === 503 || st === 429 || tries < OUT_MAX_TRIES) { outSave(() => { delete e.sending; delete e.live; e.tries = tries; }); outUnsaved(e, true); outRetry(); return; }  // 2.574.0 (#4589): the field says it waits  // 2.551.0 (#4649): a later try is no "at once" any more (a refusal then waits in the dialog)
        }
        if (err.data?.code === 'skip_stale') {  // 2.528.0 (#4305 B1): skipped elsewhere already = not skipped twice, the current date
          if (err.data.task && typeof putTask === 'function') putTask(err.data.task);
          setTimeout(() => toast(err.message), 400); outSave(() => { OUT.q = OUT.q.filter(x => x !== e); }); e.res = null; e.done = true; outAnswer(e, null); continue;  // 2.537.0 (#4568): its waiter hears it
        }
        // 2.551.0 (#4649): a change sent online whose value the server refused (400 / 422, e.g. "number expected": sending it again
        // would only be refused again) is said with the server's words as api() did before #4568; the page goes back to the
        // server's state (load), nothing waits in the conflicts dialog, its caller hears it (outFail). Deleted elsewhere (404), no
        // right (403), a conflict (409): the dialog as before, the change is kept there
        if (e.live && (st === 400 || st === 422) && !wiki && !ntU(e.url)) {
          console.warn('outbox: refused', e, err); if (globalThis.document) $('#detail .dsaved')?.classList.remove('on');  // its "Saved" was too early
          if (err.message !== 'auth' && !err.shown) { if (err.data?.out_request && typeof oor_ask === 'function') toast(err.message, () => oor_ask(err.data.out_request), 10000, tr('Ask an admin')); else toast(err.message); }
          outSave(() => { OUT.q = OUT.q.filter(x => x !== e); }); e.res = null; e.err = err; e.done = true; refused.push(e); continue;
        }
        console.warn('outbox: dropped', e, err);  // e.g. 404: deleted on another device
        if (typeof ntReject === 'function' && ntU(e.url) && ntReject(e, err)) { /* 2.536.0 (#4567): 409 = the note's own dialog (chat.js) */ }
        else if (!(wiki && typeof wkoReject === 'function' && await wkoReject(e, err).catch(() => false))) { if (wiki) wdropped++; else dropped++; outReject(e, err); }  // 2.169.0 (#2671): changed elsewhere = waits at the page; 2.169.1 (#2672): own words for a page
        outSave(() => { OUT.q = OUT.q.filter(x => x !== e); });
        e.res = null; if (e.tries) outUnsaved(e, false);  // 2.574.0 (#4589): it waits in the conflicts dialog now
        outAnswer(e, null);  // 2.537.0 (#4568): refused: its waiter hears it (the change waits in the conflicts dialog)
      }
      e.done = true;
    }
    LS.set('idmap', Object.fromEntries(Object.entries(idmap).filter(([k]) => -k > Date.now() - 86400000)));  // 2.126.0 D (#1989): another tab may still hold a new task's temporary id for a while; 2.380 H (#3387): 24 h, not 10 min
    obxMeta('idmap', LS.get('idmap', {}));  // 2.143.0 C (#2153)
  } finally {
    OUT.flushing = false;
    if (sent && !OUT.q.length && globalThis.document) { S.syncOk = Date.now(); staleDraw(); }  // 2.25.0 (UX-55): the "waiting" chip goes at once
    renderTop();
    if (sent && sent > sentNt + sentTk && !OUT.q.length && !dropped && !wdropped && !skipped && !refused.length) savedChip();  // 2.536.0 (#4567): a note says "Saved" itself; 2.537.0 (#4568): a task's change said "Saved" already
    if (dropped) setTimeout(() => toast(trn('{0} change not applied (task deleted or invalid)', '{0} changes not applied (task deleted or invalid)', dropped)), 400);
    else if (wdropped) setTimeout(() => toast(trn('{0} offline change of a knowledge page not applied (page deleted or no right)', '{0} offline changes of knowledge pages not applied (page deleted or no right)', wdropped)), 400);
    else if (skipped) setTimeout(() => toast(tr('Recurring task was already checked off, not advanced twice')), 400);
    // 2.551.0 (#4649): left early (an entry behind it waits for the connection / another try): the refused ones are settled here
    if (OUT.q.length && refused.length) { const r = refused.splice(0); load().then(() => render(), () => {}).finally(() => { for (const e of r) outAnswer(e, null); }); }
  }
  // 2.536.0 (#4567): only notes went out (every few seconds while typing): no whole new state, the notes are drawn already;
  // 2.537.0 (#4568): the same for task changes the answers settled
  try {
    if (!(sent && sent === sentNt + sentTk && !dropped && !wdropped && !refused.length)) await load();
    render();
  } finally { for (const e of refused) outAnswer(e, null); }  // 2.551.0 (#4649): after the server's state is drawn (a kept typed value stays)
  if (typeof qfSend === 'function') qfSend();  // 2.359.0 A (#3023): files of a quick add made offline (attachments.js)
}
window.addEventListener('online', () => { OUT.retryAt = 0; flush(); });
// 2.574.0 (#4589): a task's typed title / description whose send failed with a server error waits first in the queue for
// another try: its field says "Not saved yet, trying again" (attachments.js unsavedMark) until it went out or was refused
function outUnsaved(e, on) {
  const m = e?.method === 'PATCH' && /^\/api\/tasks\/(\d+)$/.exec(e.url);
  if (!m || typeof unsavedMark !== 'function' || !globalThis.document) return;
  for (const f of ['title', 'content']) if (e.body && f in e.body) unsavedMark({id: +m[1], field: f}, on);
}
// 2.359.0 A (#3023): the next try after a server error: 2 s, 4 s, 8 s ... at most a minute (a success starts again at 2 s)
const OUT_MAX_TRIES = 12;
function outRetry() {
  OUT.tries = (OUT.tries || 0) + 1;
  const ms = Math.min(60000, 2000 * 2 ** (OUT.tries - 1));
  OUT.retryAt = Date.now() + ms;
  clearTimeout(outRetry.t); outRetry.t = setTimeout(() => { OUT.retryAt = 0; if (OUT.q.length) flush(); }, ms);
}
// 2.25.0 (UX-55): after waiting changes went out: "All saved ✓" for a moment where the "waiting" chip was (not as a toast,
// which would push away an Undo that is still on screen)
const savedChipOff = debounce(el => el.classList.remove('on'), 2500);  // 2.599.0 (#4506)
function savedChip() {
  let el = $('#savedok');
  if (!el) { el = document.createElement('div'); el.id = 'savedok'; el.setAttribute('role', 'status'); document.body.appendChild(el); }
  el.innerHTML = `${ic('check', 's')}<span>${esc(tr('All saved'))}</span>`; el.classList.add('on');
  savedChipOff(el);
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
  // 2.138.2 C (#2392): the dot sits in the sidebar's head now (shown only offline / syncing), no longer on the picture;
  // 2.152.3 A (#2619): on a computer in the head bar
  for (const d of $$('#side .netdot, #kbar .netdot')) { d.className = 'netdot n-' + n.k; d.setAttribute('aria-label', n.label); d.title = n.label; }
  for (const b of $$('.sbacct, .kbacct')) { b.setAttribute('aria-label', acctLabel()); b.title = acctLabel(); }
}
// 2.25.0 (UX-55): while changes wait, the server is asked again every 2 s (not only on the 4 s poll)
function flushSoon() { if (flushSoon.t) return; flushSoon.t = setTimeout(() => { flushSoon.t = null; if (globalThis.document && OUT.q.length && !document.hidden) flush(); }, 2000); }

// ------------------------------------------------------------------ conflicts (edited here and elsewhere)
S.conflicts = LS.get('conflicts', []);
const FIELD_NAMES = {ttype: N_('Type'), title: N_('Title'), content: N_('Description'), due: N_('Due'), due_time: N_('Time'), priority: N_('Priority'), list_id: N_('Project'), tags: N_('Tags'), reminders: N_('Reminder'), repeat: N_('Repeat'), repeat_from: N_('Repeat from'), start: N_('Start|date'), section_id: N_('Section'), parent_id: N_('Parent task'), pinned: N_('Pinned'), duration: N_('Duration'), url: N_('Link'), deadline: N_('Deadline'), nag: N_('Repeat reminder'), ms: N_('Milestone'), milestone_id: N_('Milestone')};
// 2.527.0 (#4304): an entry with its own task id (the answer of /api/tasks/batch and /reorder: conflicts[{id, title, ...}],
// the answer itself has no id) belongs to that task; tid / title are only the fallback for a PATCH of one task
const cfTid = (c, tid) => Number.isInteger(+c?.id) && +c.id > 0 ? +c.id : tid;
function addConflicts(tid, list, title) {
  for (const c of list) {
    const id = cfTid(c, tid);
    S.conflicts = S.conflicts.filter(x => !(x.tid === id && x.field === c.field));
    S.conflicts.push({tid: id, title: (id === tid ? title : c.title) || c.title || S.tasks.get(id)?.title || '', field: c.field, server: c.server, mine: c.mine, at: Date.now()});
  }
  LS.set('conflicts', S.conflicts);
  renderTop();
  // 2.13.2 (#478 F7): no toast on top of the calm bar under the field (it said the same and covered "Waiting for …")
  setTimeout(() => { if (list.every(c => S.sel === cfTid(c, tid) && $(`#detail .cfbar[data-f="${c.field}"]`))) return; toast(list.length === 1 ? tr('A field was changed elsewhere in the meantime, please review') : tr('{0} fields were changed elsewhere in the meantime, please review', list.length)); }, 300);
}
// 2.126.0 D (#1992 O8): an offline change the server refused (deleted, no right any more, invalid) is not lost silently:
// its text waits in the conflicts dialog with the reason, to copy
// 2.359.0 A (#3023): the whole change, also lists and objects (tags, fields, a batch, a new order, a completion), never only a
// count; a new task's own title is its heading
function outReject(e, err) {
  const b = e.body && typeof e.body === 'object' ? e.body : {};
  const val = v => typeof v === 'object' ? JSON.stringify(v) : String(v);
  let txt = Object.entries(b).filter(([k, v]) => !k.startsWith('_') && k !== 'client_ref' && k !== 'expect_updated_at' && v != null && v !== '' && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => (k === 'title' || k === 'content' || k === 'body') && typeof v !== 'object' ? String(v) : `${k}: ${val(v)}`).join('\n');  // 2.143.0 C (#2153): + a note's text
  const um = e.url.match(/^\/api\/tasks\/(-?\d+)(?:\/(\w+))?/) || [], raw = +um[1] || 0, act = um[2] || (e.url === '/api/tasks/batch' ? b.action : e.url === '/api/tasks/reorder' ? 'reorder' : '');
  if (act) txt = [`${tr('Action')}: ${act}`, txt].filter(Boolean).join('\n');
  if (!txt) return;
  const id = raw > 0 ? raw : 0;
  const nt = !id && (S.nt?.notes || S.notes || []).find(n => '/api/notes/' + n.id === e.url);  // 2.143.0 C (#2153)
  S.conflicts.push({tid: id, title: b.title || S.tasks.get(raw)?.title || nt?.title || '', field: 'rejected', server: err?.message || '', mine: txt, at: Date.now()});
  LS.set('conflicts', S.conflicts);
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
  if (field === 'priority') return tr([N_('None'), N_('Low'), '', N_('Medium'), '', N_('High'), '', N_('Urgent')][+v] || '') || String(v);
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
    <div class="muted" style="font-size:var(--fs-m);margin-bottom:.625rem">${tr('These fields were changed on another device while you entered something else here. The other version is saved.')}</div>
    <div id="cf-list"></div>
    <div class="foot"><button class="btn" data-m="all-server">${tr('All: keep the other version')}</button><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  const draw = () => {
    $('#cf-list', md).innerHTML = S.conflicts.map((c, i) => c.field === 'rejected' ? `<div class="cfitem"><div class="cfh"><b>${esc(c.title)}</b><span class="muted">${esc(tr('Offline change not saved'))}</span></div>
      <div class="cfv"><div><span>${tr('reason')}</span>${esc(c.server)}</div><div><span>${tr('your version')}</span><span style="white-space:pre-wrap">${esc(c.mine)}</span></div></div>
      <div class="cfb"><button class="btn sm" data-cf="server" data-i="${i}">${tr('Dismiss')}</button>${c.qf ? `<button class="btn sm" data-cf="dl" data-i="${i}">${ic('download', 's')} ${tr('Download')}</button>` : '' /* 2.380 H (#3387) */}<button class="btn sm pri" data-cf="copy" data-i="${i}">${ic('copy', 's')} ${tr('Copy')}</button></div></div>` : `<div class="cfitem"><div class="cfh"><b>${esc(c.title)}</b><span class="muted">${esc(histFieldName(c.field))}</span></div>
      <div class="cfv"><div><span>${tr('saved')}</span>${esc(fmtVal(c.field, c.server))}</div><div><span>${tr('your version')}</span>${esc(fmtVal(c.field, c.mine))}</div></div>
      <div class="cfb"><button class="btn sm" data-cf="server" data-i="${i}">${tr('Keep saved')}</button><button class="btn sm pri" data-cf="mine" data-i="${i}">${tr('Use mine')}</button></div></div>`).join('') || `<div class="muted" style="padding:.625rem 0">${tr('No open conflicts.')}</div>`;
  };
  draw();
  md.addEventListener('click', async e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.m === 'all-server') { if (typeof qfForget === 'function') qfForget(S.conflicts.map(c => c.qf)); S.conflicts = []; }
    if (b.dataset.cf) {
      const c = S.conflicts[+b.dataset.i];
      if (b.dataset.cf === 'copy') { try { await navigator.clipboard.writeText(c.mine); toast(tr('Copied')); } catch { toast(c.mine); } return; }  // 2.126.0 D (#1992 O8)
      if (b.dataset.cf === 'dl') { if (typeof qfDownload === 'function') await qfDownload(c.qf); return; }  // 2.380 H (#3387)
      if (c.qf && typeof qfForget === 'function') qfForget([c.qf]);
      if (b.dataset.cf === 'mine') {
        // 2.537.0 (#4568): the base = the other version shown here (the change goes through the outbox, which would take the page's)
        const fk = c.field.startsWith('field:') && c.field.slice(6);
        try { const t = await api('PATCH', '/api/tasks/' + c.tid, fk ? {fields: {[fk]: c.mine}, _prev: {fields: {[fk]: c.server}}} : {[c.field]: c.mine, _prev: {[c.field]: c.server}}); putTask(t); } catch { return; }
      }
      S.conflicts.splice(+b.dataset.i, 1);
    }
    LS.set('conflicts', S.conflicts); draw(); render();
    if (!S.conflicts.length) setTimeout(() => md.remove(), 300);
  });
}

// 2.359.0 A (#3023): another account signs in while changes of the previous one wait on this device: they go only after a
// yes (only their number shows); "Cancel" signs out again, so the previous person can sign in and send them
async function userSwitchAsk(id, n) {
  if (typeof bootDone === 'function') bootDone();
  try { await i18nLoad(uiLang()); } catch { /* English */ }
  const ok = await askConfirm(trn('{0} change of the previous account on this device is not synced yet', '{0} changes of the previous account on this device are not synced yet', n),
    tr('Signing in with another account deletes them from this device, a copy is downloaded as a text file first. Cancel signs out again: the previous account can then sign in and send them.'), {ok: tr('Delete and continue'), danger: true});
  if (ok) { try { cfDownload(id); } catch (e) { console.warn('conflict copies: download failed', e); } userSwitch(id); return; }  // 2.527.0 (#4304 A20)
  try { await fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}); } catch { /* offline */ }
  location.reload();
}
// 2.527.0 (#4304 A20): the conflict copies and the changes still waiting of the previous account are not deleted silently at
// the switch: they leave as a text file (downloaded) first - each with its task, field, the saved and the own version
function cfDownload(uid) {
  for (const e of outSync().filter(x => x.uid !== uid && !x.done)) outReject(e, {message: tr('Not synced yet')});
  const list = S.conflicts || []; if (!list.length) return false;
  const val = (f, v) => { try { return fmtVal(f, v); } catch { return typeof v === 'object' ? JSON.stringify(v) : String(v ?? ''); } };
  const txt = [`${APP_NAME} · ${new Date().toLocaleString()}`, ''].concat(...list.map(c => c.field === 'rejected'
    ? [`== ${c.title || '?'} · ${tr('Offline change not saved')}`, `${tr('reason')}: ${c.server || ''}`, `${tr('your version')}:`, String(c.mine ?? ''), '']
    : [`== ${c.title || '?'} · ${histFieldName(c.field)}`, `${tr('saved')}: ${val(c.field, c.server)}`, `${tr('your version')}: ${val(c.field, c.mine)}`, ''])).join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([txt], {type: 'text/plain'}));
  a.download = `${APP_NAME.toLowerCase()}-conflicts-${today()}.txt`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  return true;
}
// another user than last time in this browser: drop everything local of the previous one, then the app loads again
function userSwitch(id) {
  clearLocal(); LS.set('uid', id);
  // 2.126.0 C (#1991): the previous person's push subscription and remembered keys in this browser go too
  const gone = Promise.allSettled([typeof wpDisable === 'function' && wpDisable(), typeof e2eForget === 'function' && e2eForget(),
    // 2.190.0 A (#2496): and the Cache Storage like at the logout (shared files waiting, kept pages); the app loads again
    (async () => { if (typeof caches !== 'undefined') for (const k of await caches.keys()) await caches.delete(k); })()]);
  Promise.race([gone, new Promise(r => setTimeout(r, 3000))]).finally(() => location.reload());
}
// 2.489.0 C (#2656): public links of this kind may be made (the instance switch and the kind's switch; the server checks too)
const pubOn = kind => !!S.publicLinks && !(S.publicLinksOff || []).includes(kind);
function applyState(j, w0) {  // w0: S.wseq when its GET /api/state started (ld_go), 2.607.0 (#4901)
  if (j.me) {  // another user than last time in this browser: drop everything local of the previous one (userSwitch)
    const last = LS.get('uid', null);
    if (last !== null && last !== j.me.id) {
      // 2.359.0 A (#3023): changes of the previous account still wait on this device: asked first (only their number shows);
      // "Cancel" signs out again, so the previous person can sign in and send them
      const n = outSync().filter(x => x.uid !== j.me.id).length + (S.conflicts || []).length;  // 2.359.0 A (#3023)
      if (!n) userSwitch(j.me.id); else if (!OUT.switchAsk) OUT.switchAsk = userSwitchAsk(j.me.id, n);  // 2.359.0 (review): one question, not one per poll
      throw new Error('auth');
    }
    if (last === null) LS.set('uid', j.me.id);
    S.me = j.me;
    const rw = LS.get('rcWarn', null);  // logged in with a recovery code, only a few left
    if (rw !== null) { LS.del('rcWarn'); setTimeout(() => toast(trn('Only {0} recovery code left: create new ones under Settings > Account.', 'Only {0} recovery codes left: create new ones under Settings > Account.', +rw), null, 8000), 1500); }
  }
  S.lists = j.lists; S.inboxNames = j.inbox_names || []; S.sections = j.sections; S.habits = j.habits; S.habitsTrash = j.habits_trash || []; S.pomo = j.pomo;
  S.notes = j.notes || []; S.team = j.team || {enabled: false, unread: 0};  // 2.17.0 (#442 #419)
  S.pomoToday = j.pomo_today; S.avatars = j.avatars || {}; S.colors = j.colors || {}; S.share = j.share || null; S.settings = j.settings; S.mineOrder = moFromState(j); S.languages = j.languages || [{code: 'en', name: 'English'}]; LS.set('lang', j.settings.lang || 'en'); document.documentElement.lang = j.settings.lang || 'en'; S.counts = j.counts; S.v = j.v; S.ntfyUrl = j.ntfy_url;
  S.trashPurge = j.trash_purge !== false;  // 2.223.3 A (#2877)
  lookAdopt();  // 2.143.0 D (#2155)
  o3c_ringsMigrate();  // 2.118.0 (#2297): old device switch for rings -> account setting, once
  foldSync();  // 2.4.0 (#361): folded folders follow the user (all devices)
  scl_sync();  // 2.156.0 C (#2073): folded sections too (listedit.js)
  // 2.280.0 A (#3108): a long note is not in the state (no content, content_n); one loaded already stays while the task is unchanged
  // 2.280.0 F (#3108): ... and its length is the server's (a save that failed, two changes in one second: loaded again), unless
  // it is being typed / waits to be saved
  const was = S.tasks, tkNoteBusy = id => !!saveTimers[id + ':content'] || (S.sel === id && document.activeElement?.id === 'd-content');
  if (j.tdef) S.tdef = j.tdef; tdFill(j.tasks);  // 2.575.0 B (#3966): the defaults back first (liveparts.js; the offline cache is filled too)
  S.tasks = new Map(j.tasks.map(t => { if (!('content' in t)) { const o = was?.get(t.id); if (o && 'content' in o && o.updated_at === t.updated_at && (String(o.content).length === t.content_n || tkNoteBusy(t.id))) t.content = o.content; } return [t.id, t]; }));
  lzTake(j);  // 2.369.2 (#3136): the lists whose tasks are not all here (liveparts.js)
  S.filters = j.filters || [];
  S.views = j.views || [];  // 2.577.0 (#3356): the shared views of the projects I see
  S.notify = j.notify || null;  // 2.1.0 (#317) the notification matrix (the server's view)
  S.webpush = j.webpush || {enabled: false};
  S.news = j.news || {unread: 0, sig: ''};
  S.templates = j.templates || [];
  S.org_labels = j.org_labels || [];  // 2.609.0 (#3373): the labels of the organisations whose projects I see
  S.timer = j.timer || null; S.timeTotals = j.time_totals || {};
  S.timeLists = j.time_lists || {}; S.timeDayH = +j.time_day_h || 8;  // 2.7.0 (#407)
  S.maxFileMb = +j.max_file_mb || 50;  // 2.273.0 D (#3051): server upload limit per file
  S.maxDepth = +j.max_depth || 3;  // 2.156.0 A (#1949): the levels of tasks (kalmido/core/schema.py MAX_DEPTH)
  S.fields = j.fields || [];
  tty_load();  // 2.609.0 (#3372): the own ticket types (ttypes.js; at most every five minutes)
  S.folderOrders = j.folder_orders || {};  // 2.27.0 (#988): the order of other people's folders I see their lists in
  S.folderProps = j.folder_props || {}; S.foldersSharedIn = j.folders_shared_in || []; S.folderShares = j.folder_shares || {};  /* 2.41.0 (#1428) */  // 2.29.0 (#1030 / #929)
  S.collabAll = j.collab_all !== false; S.timeAll = j.time_all !== false; S.about = j.about || {};
  S.orgPeers = !!j.org_peers;  // 2.364.0 D (#3036): see hasPeers
  S.calendars = j.calendars || {enabled: false, subs: 0};
  S.api = j.api || {enabled: false}; S.caldav = j.caldav || {enabled: false}; S.webhooks = j.webhooks || {enabled: false}; S.publicLinks = !!j.public_links; S.publicLinksOff = j.public_links_off || [];
  S.sample = j.sample || null;
  S.industry = j.industry || null;  // 2.578.0 (#4573): the app's industry {code: '' | 'film', can_set, choices, updated_at}; 2.828.0 (#5511): + codes (several)
  S.agents = j.agents || []; S.agentsAt = Date.now(); S.setupPending = !!j.setup_pending;  // 2.13.0 (#453 A16)
  S.proposers = j.proposers || [];  // 2.3.0: agents I may ask for a proposal
  S.assistant = j.assistant || null;  // 2.75.0 (#1411): only with a configured assistant
  S.groups = j.groups || []; S.myGroups = j.my_groups || [];  // 2.10.0 (#441)
  S.dayplan = j.dayplan || {work_start: '09:00', work_end: '17:00', review_time: '', default_duration: 30};  // 2.10.0 (#440)
  S.kids = j.kids || []; S.kidIds = new Set(j.kid_ids || []);  // 2.19.0 (#653)
  S.peopleVis = j.people_visibility || 'all';  // 2.22.0 (#752)
  S.instanceMode = j.instance_mode || 'workspaces';  // 2.46.0 (#1592)
  S.workspaces = !!j.workspaces; S.wsMismatches = j.ws_mismatches || {};  // 2.28.0 (#935)
  S.notifAsk = j.notif_ask || [];  // 2.33.0 (#927): the one-time question about notification templates
  S.storage = j.storage || null; S.announce = j.announce || null;  // 2.24.0 (#910 / #907)  // 2.23.0 (#799): organisation | shared | multi
  S.clients = j.clients || [];  // 2.23.0 (#463): the clients I see, with their lists
  if (S.booted && typeof OIM !== 'undefined' && OIM.clients && S.route?.mod === 'office' && S.route.tab === 'import') fx8a_oimClients(true);  // 2.80.0 (#1836): the import's client choice too
  if (S.booted && S.route?.mod === 'office' && typeof onumListFresh === 'function') onumListFresh();  // 2.138.0 D (#2256): the document list follows changes made elsewhere
  if (S.booted && S.route?.mod === 'clients') ms_clLive();  // a change elsewhere: the client's sums again; 2.431.0 C (#3602): quietly, drawn only when changed
  if (S.booted && S.route?.mod === 'contacts' && typeof ct_live === 'function') ct_live();  // 2.431.0 C (#3602)
  // 2.50.0 (#1195, #1194); 2.50.1: the shown tab loads again and keeps its rows until the new ones are there (a null
  // without a redraw left absence and booking rows that no longer opened on a tap)
  if (S.booted && S.route?.mod === 'workload') { const t = WLV.tab === 'dispo' && !dp_on() ? 'wl' : WLV.tab, ld = typeof AB2 !== 'undefined'; if (ld && t !== 'abs') AB2.data = null; if (ld && t !== 'dispo') DPV.data = null; if (t !== 'wl') WLV.data = null; if (t === 'wl') wlLoad(); else if (ld) { if (t === 'abs') ab2_load(); else dp_load(); } }  // 2.149.0 F (#2518): absence.js / dispo.js load on demand (not there yet: their stand-in loads and fetches); lazy-ok: ld = the module is loaded
  // 2.21.0 (#659 / #658): event calendars (a changed event refetches the calendar range), address books, links of tasks
  S.evcals = j.evcals || []; S.evlinks = j.evlinks || {}; S.books = j.books || []; S.tcontacts = j.tcontacts || {};
  if (j.evsig !== undefined && j.evsig !== S.evsig) { S.evsig = j.evsig; if (S.booted) calInvalidate(); }
  // language changed on another device: switch once its file is loaded (the boot awaits it itself)
  if (S.booted && (j.settings.lang || 'en') !== I18N.code) i18nLoad(j.settings.lang).then(ok => { if (ok) render(); });
  for (const p of OPT_DONE) { if ((w0 != null && p.end <= w0) || Date.now() - p.at > 120000) OPT_DONE.delete(p); else p.put(); }  // 2.607.0 (#4901)
  for (const p of OPT) p.put();  // 2.41.2 (#1501): own changes still on the way stay on top of a state fetched meanwhile
  if (typeof le2eState === 'function') le2eState();  // 2.64.1 (#1817): locked lists, ciphers of the offline cache
}
// 2.41.2 (#1501): optimistic writes. A click shows at once: put() changes the local state and returns how to take it back,
// the request runs behind it (no GET /api/state afterwards; other devices / tabs get it with the live update). An error
// (api() said why) puts the old state back. While the request runs, a state that arrives (the poll's load()) gets the
// change again on top, so the own change never flickers back; a state fetched across the write's end is fetched again (wseq).
const OPT = new Set();
// 2.607.0 (#4901, CI red p271_ui): a load() that began before an own write and was overtaken by writes three times in a row
// is applied all the same (ld_go); the write's change was no longer in OPT then and flipped back (a list's view went back to
// "list" after "Timeline"). A finished write stays here with S.wseq at its end until a state arrives whose GET began after
// it (applyState's w0 >= end: the server's answer holds it), at most two minutes.
const OPT_DONE = new Set();
// 2.651.0 (#5064, #5076): o.mod = the change lives in a module's own data (RSS, BW, BG ...), not in S: applyState never
// overwrites it and the module's loader puts what is still on its way (OPT) itself, so a finished write is not kept for
// applyState; it used to come back over a later own step (an undo of "Mark all read", a duplicate's provisional row)
async function optWrite(put, req, draw = render, o) {  // draw: how the screen follows (default: everything)
  const p = {put}, back = put();
  OPT.add(p); draw();
  try { const r = await req(); p.end = S.wseq || 0; p.at = Date.now(); if (!o?.mod) OPT_DONE.add(p); return r; }
  catch (e) { OPT.delete(p); back?.(); draw(); throw e; }
  finally { OPT.delete(p); }
}
// the usual put: set vals on the object get() finds (looked up again after a reload); the values before are kept once
function optSet(get, vals) {
  let old = null;
  return () => {
    const o = get(); if (!o) return null;
    if (!old) old = Object.fromEntries(Object.keys(vals).map(k => [k, o[k]]));
    Object.assign(o, vals);
    return () => { const x = get(); if (x) Object.assign(x, old); };
  };
}
// auto: 2.280.0 A (#3109) a reload of the live update (not after an own action): the server may hold it back ({brake}: it
// loaded this person's whole state a moment ago); nothing changes then and the next poll asks again
// 2.545.0 (#4483): a reload of the live update while another load() is on its way does not fetch /api/state a second time:
// it waits for that one and fetches once more only when the version the poll saw (want) is still newer afterwards
let ld_run = null;
async function load(auto, want) {
  if (auto && ld_run) {
    const r = await ld_run.catch(() => {});
    if (ld_run || r === 'brake' || !(want > (S.v || 0))) { if (ld_run) await ld_run.catch(() => {}); return r; }
  }
  const p = ld_go(auto); ld_run = p;
  try { return await p; } finally { if (ld_run === p) ld_run = null; }
}
async function ld_go(auto) {
  let j, ld_w0 = null;
  try {
    if (typeof lgo_pending === 'function') await lgo_pending();  // 2.743.0 (#4284): a sign-out made offline ends its session first
    let crossed = false;
    for (let i = 0; i < 3; i++) {  // 2.13.4: an answer that a write overtook is fetched again (see rawFetch)
      const w0 = ld_w0 = S.wseq || 0;  // 2.607.0 (#4901): for applyState (OPT_DONE)
      j = await api('GET', (auto && !i ? '/api/state?auto=1&' : '/api/state?') + 'td=1&' + lzQuery());  // 2.575.0 B (#3966): + td  // 2.369.2 (#3136): + the start set  // 2.280.0 F (#3109): a repeat is no herd reload (it would brake itself)
      crossed = (S.wseq || 0) !== w0;
      if (!crossed) break;
    }
    // 2.350.0 C (#2806): still crossed by a write after the third try: the own settings win over that answer (it may predate
    // the save); the next load brings changes made elsewhere
    if (crossed && j?.settings && S.settings && j.me?.id === S.me?.id) j.settings = {...j.settings, ...S.settings};
    if (j?.brake) return 'brake';  // 2.280.0 F (#3109): the caller keeps the change pending
    OUT.me = j?.me?.id;  // 2.126.0 D (#1992 O5)
    if (j?.me?.id === LS.get('uid', j?.me?.id)) sessGuard(j?.me);  // 2.238.0 B (#2872): before the outbox is sent (another account: applyState clears all)
    if (OUT.me && OBX.uid !== OUT.me) { OBX.uid = OUT.me; obxMeta('uid', OUT.me); }  // 2.143.0 C (#2153): the service worker sends only this user's entries
  }
  catch (e) {
    if (!(e instanceof Offline)) throw e;
    if (!S.tasks.size) {  // offline start: last cached state + still-queued edits
      const c = await startRead(); if (!c) throw e;  // 2.663.0 (#4200): IndexedDB (offcache.js), the old localStorage copy taken over once
      if (S.tasks.size) return;  // another load came first meanwhile
      if (wkoOld(LS.get('wko', null))) wkoDrop();  // 2.238.0 B (#2872): 14 days without an online sync
      applyState(c); OUT.q.forEach(applyLocal);
    }
    return;
  }
  if (OUT.q.length) {  // flush() reloads once the queue is through
    if (!S.tasks.size || j?.me?.id !== S.me?.id) { applyState(j, ld_w0); OUT.q.forEach(applyLocal); }  // 2.126.0 D (#1992 O5): another user = applyState's switch
    flush(); return;
  }
  applyState(j, ld_w0);
  if (j?.lva && !S.lpA) S.lpA = j.lva;  // 2.619.0 (#3890): the areas of this state (read before its v): the first poll takes a delta, not the whole state again
  if (S.qfWait && typeof qfSend === 'function') qfSend();  // 2.376.1 CI fix: files of a quick add whose new task was not loaded yet
  S.lpCache = j; startSave();  // 2.663.0 (#4200): written when idle (IndexedDB); 2.42.0 (#1376): the delta keeps the cache current (liveparts.js)
  if (S.extra) await loadExtra().catch(() => {});
  if (S.sel && (cmtOn() || collab()) && S.tl.id === S.sel && S.tl.v !== S.v) loadTimeline(S.sel);
  if (S.sel && timeOn() && S.te.tid === S.sel && S.te.v !== S.v) loadTaskTime(S.sel);
  if (S.sel && S.dp.id === S.sel && S.dp.v !== S.v) loadDeps(S.sel);
  if (S.chat.aid && collab()) chatLoad();
  if (S.route.mod === 'agents' && S.jobs.items !== null) loadJobs();
  if (typeof staleLoad === 'function') staleLoad(S.route.key === 'stale');  // 2.34.0 (#266): at most every 5 minutes, at once in its view
  mwLoad(S.route.key === 'mine_wait');  // 2.392.0 D (#3369): at most once a minute, at once in its view
}
// 2.40.0 (#1432): Completed / Trash show 100 tasks first, "Load more" adds 100; a change reloads as many as are shown
const HIST_PAGE = 100;
S.hist = {k: null, n: HIST_PAGE, next: null, deletable: null, kept: null};
async function loadExtra() {
  const k = S.route.key;
  if (S.route.mod === 'tasks' && (k === 'done' || k === 'trash')) {
    if (S.hist.k !== k) S.hist = {k, n: HIST_PAGE, next: null, deletable: null, kept: null};
    const j = await api('GET', `/api/tasks?scope=${k}&limit=${Math.min(S.hist.n, 2000)}`);
    if (S.hist.k !== k) return;
    Object.assign(S.hist, {next: j.next || null, deletable: j.deletable ?? null, kept: j.kept ?? null, others: j.others ?? 0, days: j.days ?? null, purge_on: j.purge_on ?? null});  // 2.116.0 A (#2063): + trash period; 2.223.3 A (#2877): + whether it deletes
    S.extra = j.tasks;
  } else if (S.route.mod !== 'news' && S.route.mod !== 'time') {  // News / time reports: tasks fetched on demand stay
    const o = (S.extra || []).filter(t => t.id === S.sel);  // 2.509.0 (#4324): elsewhere only the open one, a reload does not close it
    S.extra = o.length ? o : null;
  }
}
async function histMore(b) {
  const k = S.hist.k; if (!S.hist.next || !k) return;
  if (b) b.disabled = true;
  try {
    const j = await api('GET', `/api/tasks?scope=${k}&limit=${HIST_PAGE}&before=${encodeURIComponent(S.hist.next)}`);
    if (S.hist.k !== k) return;
    const ids = new Set((S.extra || []).map(t => t.id));
    S.extra = [...(S.extra || []), ...(j.tasks || []).filter(t => !ids.has(t.id))];
    S.hist.n += HIST_PAGE; S.hist.next = j.next || null;
  } catch (e) { if (e instanceof Offline) toast(tr('Only available online.')); if (b) b.disabled = false; return; }
  renderView();
}
function putTask(t) {
  S.tasks.set(t.id, t); _kidsIx = null;
  if (t.id === S.sel && S.extra) { const i = S.extra.findIndex(x => x.id === t.id); if (i >= 0) S.extra[i] = t; }  // 2.509.0 (#4324): the open task fetched alone: the next reload shows the edit, not the copy of before
}

// poll for changes made elsewhere (phone <-> desktop)
// 2.40.0 (#1430): changes from elsewhere are drawn bundled: what arrives within TD_RS_MS is one render (a render that runs
// anyway in between takes it along, see render())
const TD_RS_MS = 300;
let td_rsT = 0;
// 2.41.0 (#1376): unsaved form input (formguard) holds the redraw back like a focused field; office / clients views are not
// redrawn by a change of someone else (only the sidebar, header and tabs follow)
function td_renderSoon() { if (td_rsT) return; td_rsT = setTimeout(() => { td_rsT = 0; if (lpBusy()) S.viewStale = true; else if (lpKeepView()) { renderSide(); renderTop(); renderTabs(); badgeSync(); } else { S.lpN.render++; render(); } }, TD_RS_MS); }
let td_polling = false;  // 2.40.0 (#1430): a slow answer (many changes elsewhere) does not start a second load + render on top
setInterval(async () => {
  if (document.hidden || td_polling) return;
  td_polling = true;
  try {
    if (OUT.q.length) { flush(); staleDraw(); return; }  // 2.13.0 (#453 A13): the chip says how many changes wait
    const {v, vs, n, c, t, ty, app, sp, a} = await api('GET', '/api/version');
    S.vNow = v;  // 2.565.0 (#4705): the server's counter even while the state waits (typing): an open dialog's version watch (objsave.js dlgStale)
    const lpCh = lpChanged(a);  // 2.41.0 (#1376): the areas that changed since the last poll
    lpSkip(v, vs);  // 2.369.4 (#2507): changes only elsewhere: S.v follows, nothing is fetched
    if (sp !== undefined && sp !== S.stepsSig) { const first = S.stepsSig === undefined; S.stepsSig = sp; if (!first) stepsChanged(); }  // 2.32.0 (#1081)
    verCheck(app);  // 2.27.0 (#968)
    if (ty !== undefined) { const sig = JSON.stringify(ty); if (sig !== S.ctypingSig) { S.ctypingSig = sig; S.ctyping = ty; if (S.sel) agentLive(); } }  // 2.22.0 (#693)
    if (t !== undefined && t !== S.teamSig) { const first = S.teamSig === undefined && S.route?.mod !== 'team'; S.teamSig = t; if (!first && (!editing() || ['tc-in', 'ms-q'].includes(document.activeElement?.id))) teamChanged(); }  // 2.17.0 (#419); 2.82.0 (#1862): typing a new message / search still takes live changes (tcPatch leaves those fields alone; an inline edit .tc-edit would be redrawn)  // 2.145.0 B (#2424): an open conversation takes the first poll too (a message sent in the window's first seconds came only with the next one)
    if (c !== undefined && c !== S.calSig) {  // calendar subscriptions synced / changed: fetch the shown range again
      const first = S.calSig === undefined; S.calSig = c;
      if (!first && calEvOn() && !editing()) { calInvalidate(); if (S.route.mod === 'cal' || S.route.key === 'today') renderView(); }
    }
    const chg = v !== S.v || (n !== undefined && collab() && n !== S.news?.sig);
    // 2.41.0 (#1376): only light areas: their parts, the rest bundled; 2.42.0 (#1376): the tasks area: only the changed tasks (delta)
    if (chg && v !== S.v && !editing() && (lpLive(v, lpCh, n) || await lpDelta(v, lpCh, n))) { /* drawn there */ }
    else if (chg && !editing()) { S.viewStale = lpHold(); const lpBack = lpFull(); S.lpN.state++; if (await load(true, v) === 'brake') lpBack(); td_renderSoon(); }  // 2.40.0 (#1430): bundled; 2.280.0 F (#3109): braked: the follow-up stays; #3402: a held element keeps the view stale (drawn after letting go)
    else if (v !== S.v && editing() && S.sel > 0 && (cmtOn() || collab()) && S.tl.id === S.sel && S.tlPollV !== v) { S.tlPollV = v; loadTimeline(S.sel); agentPoll(); }  // 1.9.0
    else if (chg && editing() && S.chat.aid && collab() && S.chatPollV !== `${v}/${n}`) { S.chatPollV = `${v}/${n}`; chatLoad(); agentPoll(); }  // 2.12.2 (#451): typing, the chat still updates (patched)
    else if (S.viewStale && !editing()) viewSafeRender();
    if (v !== S.v && editing() && S.route.mod === 'agents' && S.jobs.items !== null && S.jobsPollV !== v) { S.jobsPollV = v; loadJobs(); }  // 2.37.0 (#1161)
    lpSettle(v);  // 2.280.0 F (#3109)
    S.syncOk = Date.now(); staleDraw();
  } catch { staleDraw(); /* offline */ } finally { td_polling = false; }
}, 4000);
// 2.7.2 (#433): instead of a refresh button in the header of shared lists, a small hint once the change check has failed
// for more than 30 s: "Offline – last update N min ago"; a tap tries again (refreshNow). "…" keeps "Refresh".
S.syncOk = Date.now();
// 2.13.0 (#453 A13): offline (or changes not sent yet) is said in words too, not only with the cloud icon: "Offline · 2
// changes waiting"; a tap explains it and tries again
function staleDraw() {
  if (typeof document === 'undefined' || !document) return;  // 2.609.0 (#4929): a poll that ends after its window was closed (the tests' late rejection)
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
// 2.273.0 C (#3051): + every other text field / text area whose typed value differs from what it was drawn with (also one
// out of view: a collapsed panel, a background tab of a dialog); search fields do not count
const VER_DRAFT_SEL = 'textarea, input:not([type]), input[type="text"], input[type="url"], input[type="email"], input[type="tel"]';
// 2.359.0 A (#3024): + a draft kept in memory only (S.drafts: a comment / chat message typed in a task or chat not shown now)
const verDraft = () => ['#c-input', '#tc-in', '#chat-in', '#qinput', '#qsheet', '#d-sub'].some(s => ($(s)?.value || '').trim())
  || Object.values(S.drafts || {}).some(v => typeof v === 'string' && v.trim() !== '')
  || [...document.querySelectorAll(VER_DRAFT_SEL)].some(e => !e.readOnly && !e.disabled && e.value !== e.defaultValue && e.value.trim() !== '');
const verQuiet = () => !editing() && !editFocused() && !$('.modal') && !$('#pop:not(.hidden)') && !$('.qadd.sheet') && !OUT.q.length && !S.multiMode && !verDraft();
let verBusy = false;
async function verReload() {
  if (verBusy) return;
  verBusy = true;
  try { if (OUT.q.length) await flush(); } catch { /* offline: the outbox stays in this browser and is sent after the reload */ }
  try { if (typeof flushSaves === 'function') await flushSaves(); } catch { /* nothing waiting */ }
  // 2.45.0 (#1529): only reload once the page and the stylesheet are really served (the container may still be restarting)
  if (typeof rl_waitServer === 'function' && !await rl_waitServer()) { verBusy = false; const b = $('#newver [data-nv]'); if (b) b.disabled = false; return; }
  try { sessionStorage.setItem('kalmido-reloaded', S.serverVer); } catch { /* private mode */ }
  try { const reg = await navigator.serviceWorker?.getRegistration(); await reg?.update(); } catch { /* no service worker */ }
  location.reload();
}
// 2.35.0 (#1094): the automatic reload waits until /api/version reported the new version twice in a row (not in the middle of
// an update, while single requests still fail); after a reload the language file is checked against the code (i18nRetry)
S.verSeen = {v: '', n: 0};
// 2.619.0 (#3890): an update makes every open window reload by itself within the same poll (all start pages and whole
// states at once): each window waits a random part of VER_SPREAD_MS first (once per new version; the bar shows meanwhile,
// "Reload" works at once). Tests set it to 0.
let VER_SPREAD_MS = 30000;
function verSpreadDue() {
  if (S.verSpread?.v !== S.serverVer) S.verSpread = {v: S.serverVer, at: Date.now() + Math.random() * VER_SPREAD_MS};
  return Date.now() >= S.verSpread.at;
}
function verCheck(app) {
  if (app) { if (app === S.verSeen.v) S.verSeen.n++; else S.verSeen = {v: app, n: 1}; S.serverVer = app; }
  let el = $('#newver');
  if (!verStale()) { if (el) el.remove(); if (typeof I18N !== 'undefined' && I18N.stale) i18nRetry(); return; }
  let once = ''; try { once = sessionStorage.getItem('kalmido-reloaded') || ''; } catch { /* private mode */ }
  if (once !== S.serverVer && S.verSeen.n >= 2 && verQuiet() && (document.hidden || Date.now() - verIdle > 20000) && verSpreadDue()) { verReload(); return; }  // 2.619.0 (#3890): + the spread
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
// 2.41.0 (#1376): also while a form in the view has unsaved input (formguard)
function viewSafeRender() { if (lpHold() || (editing() && $('#view')?.contains(document.activeElement)) || lpFormBusy($('#view'))) { S.viewStale = true; return; } S.viewStale = false; renderView(); }
// 1.9.0 pull-to-refresh (touch, shared lists): pull down at the very top of the list by 4.5rem and let go
(() => {
  let y0 = null, x0 = 0, pull = 0, el = null;
  const view = () => $('#view'), max = () => 4.5 * parseFloat(getComputedStyle(document.documentElement).fontSize || 16);
  document.addEventListener('touchstart', e => {
    const v = view(); y0 = null;
    if (!v || !v.contains(e.target) || e.touches.length !== 1 || v.scrollTop > 0 || e.target.closest('.ofbody')?.scrollTop > 0 || !sharedRoute() || S.multiMode || $('.modal') || e.target.closest('input,textarea,select,[draggable="true"],.trow.drag')) return;
    y0 = e.touches[0].clientY; x0 = e.touches[0].clientX; pull = 0;
  }, {passive: true});
  document.addEventListener('touchmove', e => {
    if (y0 === null) return;
    const dy = e.touches[0].clientY - y0, dx = Math.abs(e.touches[0].clientX - x0);
    if (dy <= 0 || dx > dy || view().scrollTop > 0 || $('.ofbody')?.scrollTop > 0) { if (el) el.classList.remove('on'); pull = 0; return; }
    pull = dy;
    // 2.165.0 (#2614): the bot figure instead of the turning arrow: it comes down with the finger, looks up once it is far
    // enough and hops while the refresh runs (app.css, nothing moves by itself with reduced motion)
    if (!el) { el = document.createElement('div'); el.className = 'ptr pbot'; el.setAttribute('aria-hidden', 'true'); el.innerHTML = botFig('ruhig'); $('#main').style.position ||= 'relative'; $('#main').appendChild(el); }
    const k = Math.min(1, dy / max());
    el.classList.toggle('on', dy > 12); el.style.transform = `translateY(${Math.round(k * 3.5 * 16)}px) scale(${(0.7 + k * 0.3).toFixed(2)})`;
    if (k >= 1 !== el.classList.contains('far')) { el.classList.toggle('far', k >= 1); el.innerHTML = botFig(k >= 1 ? 'wartet' : 'ruhig'); }
  }, {passive: true});
  const end = async () => {
    if (y0 === null) return; y0 = null;
    const go = pull >= max(); pull = 0;
    if (!el) return;
    if (!go) { el.classList.remove('on', 'far'); el.innerHTML = botFig('ruhig'); return; }
    el.classList.add('go'); el.style.transform = 'translateY(3rem)';
    try { await refreshNow(); } finally { el?.classList.remove('on', 'go', 'far'); if (el) el.innerHTML = botFig('ruhig'); }
  };
  document.addEventListener('touchend', end, {passive: true});
  document.addEventListener('touchcancel', () => { y0 = null; pull = 0; el?.classList.remove('on', 'far'); }, {passive: true});
})();

// ------------------------------------------------------------------ routing
// 1.8.1: the Inbox comes first (sidebar, tab choices, palette) and is the start view (START_KEY) until another view
// was opened: the app reopens on the last task view of the device (LS 'lastKey')
const START_KEY = 'inbox';
// 2.364.0 B (#3031): the app opened without a page in its address shows the chosen start page (setting start_page): Start
// (default), the basket, Today or 'last' = the last task view of this device (the way before); a link with a page keeps it
const START_PAGES = [['home', N_('Start|home')], ['inbox', N_('Basket')], ['today', N_('Today')], ['last', N_('The last opened view')]];
// A fresh account whose welcome tour is still to come opens in Projects as before: the tour starts only there (tourAuto,
// #2821), so Start comes from the next opening on
function st_landing() {
  const p = S.settings?.start_page || 'home';
  // 2.575.0 D (#4051): "a:<area>" = an area set as the start (its icon's menu): the page its icon opens, Start while it is not shown
  const h = p.startsWith('a:') ? (typeof sbb_startHash === 'function' ? sbb_startHash(p.slice(2)) : 'home') : START_PAGES.some(x => x[0] === p) ? p : '';
  if (location.hash.length > 1 || S.me?.kid || p === 'last' || !h || S.settings?.tour === 'pending') return;
  history.replaceState(history.state, '', location.pathname + location.search + '#' + h);
}
const SMART = {
  inbox: {name: N_('Basket'), icon: 'inbox'},
  today: {name: N_('Today'), icon: 'sun'},
  tomorrow: {name: N_('Tomorrow'), icon: 'sunrise'},
  week: {name: N_('Next 7 days'), icon: 'week'},
  doable: {name: N_('Now doable'), icon: 'zap'},  // 1.7.0
  waiting: {name: N_('Waiting on someone'), icon: 'hourglass'},  // 2.1.0 (#335)
  stale: {name: N_('Lying idle'), icon: 'clock'},  // 2.34.0 (#266)
  mine_wait: {name: N_('Waiting for me'), icon: 'flag'},  // 2.392.0 D (#3369): minewait.js
  pinned: {name: N_('Pinned|view'), icon: 'pin'},  // 2.16.0 (#648): every pinned task of every list
  assigned: {name: N_('My tasks'), icon: 'user'},
  byme: {name: N_('Assigned by me'), icon: 'send'},  // 2.36.2 (#1138)
  all: {name: N_('All'), icon: 'all'},
  done: {name: N_('Completed'), icon: 'done'},
  trash: {name: N_('Trash'), icon: 'trash'},
  archived: {name: N_('Archived'), icon: 'archive'},  // 1.6.1: the archived lists (main view)
  search: {name: N_('Search'), icon: 'search'},
};
// 2.752.0 (#4887): files and documents are ONE area "Files" under ONE address: #ablage/docs (all documents), #ablage/review
// (to review), #ablage/v/<id> (a saved view, docviews.js) and #ablage/<id> of a FILE (the document view, docview.js; the id of a
// folder stays the folder). The ids known to be files (opened from a card or a link, found by ab_load) are kept here, the
// route of a file is the internal module docs. The old links #docs, #docs/<id>, #docs/review, #docs/v/<id> lead here for good
const AB_FILEIDS = new Set();
const AB_DOCSUB = ['docs', 'review', 'v'];
function ab_docsHash(h) {  // 'docs/…' -> 'ablage/…' (null: not an old documents' address)
  const p = h.split('/'); if (p[0] !== 'docs') return null;
  if (+p[1]) { AB_FILEIDS.add(+p[1]); return 'ablage/' + +p[1]; }
  return 'ablage/' + (p[1] === 'review' ? 'review' : p[1] === 'v' && +p[2] ? 'v/' + +p[2] : 'docs');
}
// 2.787.0 (#5438): a task opened by its address on a fresh load (link, push, reload, bookmark) stands over its own project, not over the empty Inbox;
// inside the running app the view stays (S.lastRouteKey is set after the first route()); no list of its own (unknown / area store list) = as before
function th_ownKey(id) { const t = S.lastRouteKey ? null : taskById(id), l = t && listById(t.list_id); return l && !LIFE_STORE_GO[l.life] && l.life !== 'budget' ? 'l:' + l.id : null; }
function parseHash() {
  let h = decodeURIComponent(location.hash.slice(1));
  if (!h) return {mod: 'tasks', key: LS.get('lastKey', START_KEY)};
  const dh = ab_docsHash(h); if (dh) { history.replaceState(history.state, '', '#' + dh); h = dh; }  // 2.752.0 (#4887): the old address replaced, no extra entry
  const [a, b] = h.split('/');
  if (a === 't' && b && S.route.mod === 'home') return {mod: 'home', key: 'home', task: +b};  // 2.542.0 (#4579): from Start the detail opens over Start
  if (a === 't' && b) return {mod: 'tasks', key: th_ownKey(+b) || S.route.key || START_KEY, task: +b};
  if (a === 'home') return {mod: 'home', key: 'home'};  // 2.17.0 (#475): the dashboard (the logo)
  if (a === 'projects') return {mod: 'tasks', key: 'projects'};  // 2.417.0 A (#3559): the start page of Projects (render.js viewProjStart)
  if (a === 'steps') return {mod: 'tasks', key: 'steps'};  // 2.773.0 (#5250): the page "Recent steps" (undolist.js viewSteps)
  if (a === 'favorites') return {mod: 'tasks', key: 'favorites'};  // 2.441.0 (#3592): the page of a phone (favtiles.js viewFavPage)
  if (a === 'team') return {mod: 'team', key: 'team', rid: +b || null};  // 2.17.0 (#419)
  if (a === 'msg' && (b === 'a' || b === 't')) { const p = h.split('/'); return {mod: 'tasks', key: S.route.key || LS.get('lastKey', START_KEY), msg: {art: b, place: +p[2], id: +p[3]}}; }  // 2.37.0 (#1159): link back to a saved message
  if (a === 'notes' && +b) return {mod: 'notes', key: 'notes', lid: +b};  // 2.17.0 (#442)
  if (a === 'notes' && !b) return {mod: 'notes', key: 'notes', lid: null};  // 2.45.0 (#1516): the notes of all lists (notesall.js)
  if (a === 'note' && +b === QN_DRAFT) { const d = S.nt.draft; return d ? {mod: 'notes', key: 'notes', lid: d.list_id, nid: QN_DRAFT} : {mod: 'notes', key: 'notes', lid: qn_list()?.id || null}; }  // 2.477.0 (#3881): the quick note being written
  if (a === 'note' && +b) { const n = (S.notes || []).find(x => x.id === +b); return n ? {mod: 'notes', key: 'notes', lid: n.list_id, nid: n.id} : {mod: 'tasks', key: LS.get('lastKey', START_KEY), noteMissing: true}; }
  if (a === 'reply' && b) return {mod: 'tasks', key: th_ownKey(+b) || S.route.key || START_KEY, task: +b, reply: true};  // 2.0.8 (#331): push button "Reply"
  if (a === 'snooze' && b) return {mod: 'tasks', key: LS.get('lastKey', START_KEY), snooze: +b};
  if (a === 'done' && b) return {mod: 'tasks', key: LS.get('lastKey', START_KEY), complete: +b};
  if (a === 'nagoff' && b) return {mod: 'tasks', key: LS.get('lastKey', START_KEY), nagoff: +b};  // 2.7.0 (#413): push "Stop reminding"
  if (a === 'prop' && b) return {mod: 'tasks', key: LS.get('lastKey', START_KEY), prop: +b};  // 2.3.0: push "Proposal ready"
  if (a === 'f' && b) return {mod: 'tasks', key: 'f:' + b};
  if (a === 'l' && listById(+b)?.life === 'budget') return {mod: 'budget', key: 'budget'};  // 2.72.0 (#1333): a budget list opens its budget
  if (a === 'l' && LIFE_STORE_GO[listById(+b)?.life]) { const m = LIFE_STORE_GO[listById(+b).life]; return {mod: m, key: m, lsGo: m}; }  // 2.609.0 (#4613): an area's store list opens its area
  if (a === 'budget') return {mod: 'budget', key: 'budget'};  // 2.72.0 (#1333): budget/<list id> (budget.js reads the id)
  if (b === 's' && ['ablage', 'reading', 'bookmarks', 'feeds', 'life', 'workload'].includes(a)) return {mod: a, key: a, nid: null, wsp: h.split('/')[2] || ''};  // 2.540.0 (#4575 #4588): <view>/s/<space>, the space open under "All workspaces" (areas.js spo_html)  // 2.543.0 (#4606): + workload/s/<space> (Workload, Absences, Disposition)
  if (a === 'feeds') return {mod: 'feeds', key: 'feeds'};  // 2.85.0 B (#1162)
  if (a === 'bookmarks') return {mod: 'bookmarks', key: 'bookmarks'};  // 2.97.0 A (#1950)
  if (a === 'reading') return {mod: 'reading', key: 'reading'};  // 2.172.0 B (#2679): read later (readlater.js)
  if (a === 'l') return {mod: 'tasks', key: 'l:' + b};
  if (a === 'tag') return {mod: 'tasks', key: 'tag:' + b};
  if (a === 'who' && +b) return {mod: 'tasks', key: 'who:' + +b};  // 2.7.2 (#418): "Tasks of …"
  if (a === 'grp' && +b) return {mod: 'tasks', key: 'grp:' + +b};  // 2.10.0 (#441): the tasks of a group
  if (a === 'today' && b === 'review') return {mod: 'tasks', key: 'today', review: true};  // 2.10.0 (#440): push "Daily review"
  if (a === 'folder' && b) return {mod: 'tasks', key: 'folder:' + h.slice(7)};  // 2.4.0: a path has a slash
  if (a === 'lists' && b) return {mod: 'tasks', key: 'lists:' + b};  // 2.47.3 (#1727): several marked lists (sidebar.js)
  if (a === 'srv' && +b) return {mod: 'msv', key: 'msv', sid: +b, lid: +(h.split('/')[2]) || null};  // 2.73.0 C (#661): a list on another server (msvview.js)
  if (a === 'agents') return {mod: 'agents', key: 'agents', agent: +b || null};
  if (a === 'job' && +b) return {mod: 'agents', key: 'agents', job: +b};  // 2.36.2 (#1141): one job, unfolded with its history
  if (a === 'ev' && +b) return {mod: 'cal', key: 'cal', ev: +b};  // 2.21.0 (#659): a push / News about an event
  if (a === 'contacts') return {mod: 'contacts', key: 'contacts', contact: +b || null, ...((b === 'f' || b === 'b') && +h.split('/')[2] ? {[b === 'f' ? 'ctf' : 'ctb']: +h.split('/')[2]} : {})};  // 2.21.0 (#658); 2.351.0 B (#2749): contacts/f/<folder>, contacts/b/<book>
  if (a === 'client' && +b) return {mod: 'clients', key: 'clients', client: +b};  // 2.23.0 (#463)
  if (a === 'mailhub') return {mod: 'clients', key: 'clients', client: 'mailhub', ...(+b ? {mail: +b} : {})};  // 2.84.0 A (#1198): the hub's e-mail inbox (hubmail.js); 2.754.0 (#5268): mailhub/<id> opens that mail
  if (a === 'wiki' && b === 's') { const p = h.split('/'); return {mod: 'wiki', key: 'wiki', wid: null, wsp: p[2] || '', ...(p[3] === 'd' ? {wdir: p.slice(4).join('/')} : p[3] === 't' ? {wtag: p.slice(4).join('/')} : {})}; }  // 2.198.0 A (#2743): wiki/s/<space>[/d/<folder path>] under "All"
  if (a === 'wiki') return {mod: 'wiki', key: 'wiki', wid: +b || null, ...(b === 'd' ? {wdir: h.split('/').slice(2).join('/')} : b === 't' ? {wtag: h.split('/').slice(2).join('/')} : {})};  // 2.49.0 (#1199): wiki/<page id>; 2.152.3 B (#2620): wiki/d/<folder path>
  if (a === 'sheets') return {mod: 'sheets', key: 'sheets', sh: b === 'l' || b === 'f' ? null : +b || null, shl: b === 'l' ? +(h.split('/')[2]) || null : null, shf: b === 'f' ? +(h.split('/')[2]) || null : null};  // 2.89.0 (#1916): sheets/<id>, sheets/l/<list id>; 2.199.0 C (#2742): sheets/f/<folder id>
  if (a === 'ablage' && (AB_DOCSUB.includes(b) || AB_FILEIDS.has(+b))) return {mod: 'docs', key: 'docs', id: AB_FILEIDS.has(+b) ? +b : null, ...(b === 'review' ? {review: true} : {}), ...(b === 'v' && +h.split('/')[2] ? {dv: +h.split('/')[2]} : {})};  // 2.752.0 (#4887): ablage/docs|review|v/<id>|<file id>  // 2.579.0 (#4802): docs/v/<id> = a saved view (docviews.js)  // 2.48.0 (#1111): documents (docs.js); 2.353.0 D (#2759): docs/review = the saved filter To review
  if (a === 'ablage') return {mod: 'ablage', key: 'ablage', nid: +b || null, ...(/^aus-[a-z]{2,12}$/.test(b || '') ? {aus: b.slice(4)} : {})};  // 2.48.0 (#1207): ablage/<folder or file id>; 2.429.0 (#3580): ablage/aus-<key> (a collection)
  if (a === 'office' && b === 's') { const p = h.split('/'); return {mod: 'office', key: 'office', wsp: p[2] || '', tab: p[3] || '', id: +p[4] || null}; }  // 2.577.0 (#4638): office/s/<space>[/<tab>[/<id>]] under "All workspaces"
  if (a === 'office' && b && S.route?.mod === 'office' && S.route.wsp && typeof wsCur === 'function' && wsCur() === 'all') {  // 2.577.0 (#4638): a link inside an open area keeps it (the address says it too)
    history.replaceState(history.state, '', '#office/s/' + S.route.wsp + '/' + h.slice(7));
    return {mod: 'office', key: 'office', wsp: S.route.wsp, tab: b, id: +(h.split('/')[2]) || null};
  }
  if (a === 'office') return {mod: 'office', key: 'office', tab: b || '', id: +(h.split('/')[2]) || null};  // 2.36.1 (#1021): office/<tab>/<id>
  if (['cal', 'matrix', 'habits', 'pomo', 'news', 'stats', 'time', 'overview', 'family', 'life', 'review', 'clients', 'workload', 'tags'].includes(a)) return {mod: a, key: a};  // 2.22.0 (#663): life, review
  if (SMART[a]) return {mod: 'tasks', key: a};
  return {mod: 'tasks', key: START_KEY};
}
function go(hash, rep = false) {  // 2.743.0 (#5235): rep = replace the current entry instead of a new one (navUp, backnav.js)
  if (typeof f8d_defer === 'function' && f8d_defer(() => goNow(hash, rep))) return;  // #3506: after the Back of a closed menu on its way (backclose.js)
  goNow(hash, rep);
}
function goNow(hash, rep = false) { const was = location.hash; if (was !== '#' + hash) { if (rep) { if (typeof BN === 'object') BN.nt = 'replace'; location.replace('#' + hash); } else location.hash = hash; if (location.hash === was) route(); } else route(); }  // 2.619.0 (#4943): the same address in another spelling (a browser that keeps the hash decoded) fires no hashchange: route() itself (it closes the drawer)
async function route() {
  vm_leave();  // 2.413.0 A (#3439): the view left keeps its place (viewmem.js)
  const r = parseHash();
  if (r.lsGo) history.replaceState(null, '', '#' + r.lsGo);  // 2.609.0 (#4613): the address says the area, not the hidden project
  if (S.me?.kid && r.mod !== 'family' && !r.complete && !r.snooze) { r.mod = 'family'; r.key = 'family'; }  // 2.19.0 (#653): a kid's home
  o3a_toPrivate(r.mod);  // 2.83.0 (#1845): a private module in an organisation's view -> Private
  wsa_routeHint(r.mod);  // 2.409.0 (#3490): an area off in this workspace: a hint with the way to the workspace where it is on
  const mgAlt = !modOn(r.mod) && mg_alt(r.mod); if (mgAlt) { if (S.booted && r.mod === 'time') setTimeout(() => toast(tr('Time tracking is off (Settings > Modules)')), 0); r.mod = mgAlt; r.key = mgAlt; delete r.client; delete r.contact; } mg_seen(r.mod);  // 2.44.0 (#1187): a part that is off: its area's other tab
  if (!modOn(r.mod)) {  // e.g. the "News" app shortcut while collaboration is off
    const off = r.mod;
    if (S.booted && (off === 'news' || off === 'stats' || off === 'time' || off === 'overview')) setTimeout(() => toast(off === 'news' ? tr('News are part of collaboration, which is off (Settings > Modules)') : off === 'time' ? tr('Time tracking is off (Settings > Modules)') : off === 'overview' ? tr('The project status needs “Project progress” (Settings > Modules) and at least two projects') : tr('Statistics are off (Settings > Modules)')), 50);
    // 2.217.0 (#2797): a link to an agent's chat (or the Agents view, "Agents and jobs" in the header menu) with the module
    // off asks to turn it on; the hash goes to the fallback so a later re-route does not ask again
    const acAsk = off === 'agents' && !r.job && (r.agent ? !!agentById(r.agent) : S.booted), aid = r.agent;
    if (acAsk) setTimeout(() => aid ? chatOpen(aid) : ac_modOff(null), 0);
    r.mod = 'tasks'; r.key = LS.get('lastKey', START_KEY);
    if (acAsk) history.replaceState(null, '', '#' + keyToHash(r.key));
  }
  if (r.key.startsWith('f:') && !S.filters.some(f => f.id === +r.key.slice(2))) r.key = START_KEY;
  wsv_leave();  // 2.397.0 (#3404): the page being left stays its workspace's view
  if (r.mod === 'tasks' && wsOn()) wsFollow(r.key);  // 2.49.0 (#1770): a list of another workspace switches the filter along
  if (!r.task) S.bellBack = false;
  S.route = {mod: r.mod, key: r.key, ...(r.agent ? {agent: r.agent} : {}), ...(r.review ? {review: true} : {}), ...(r.client ? {client: r.client} : {}), ...(r.mod === 'office' ? {tab: r.tab, id: r.id} : {}), ...(r.mod === 'ablage' ? {nid: r.nid, ...(r.aus ? {aus: r.aus} : {})} : r.mod === 'docs' ? {id: r.id, ...(r.dv ? {dv: r.dv} : {})} : {}), ...(r.mod === 'wiki' ? {wid: r.wid, ...(r.wdir != null ? {wdir: r.wdir} : {}), ...(r.wtag != null ? {wtag: r.wtag} : {}), ...(r.wsp ? {wsp: r.wsp} : {})} : {}), ...(r.wsp && r.mod !== 'wiki' ? {wsp: r.wsp} : {}), ...(r.mod === 'sheets' ? {sh: r.sh, shl: r.shl, shf: r.shf} : {}), ...(r.mod === 'msv' ? {sid: r.sid, lid: r.lid} : {}), ...(r.mod === 'contacts' && (r.ctf || r.ctb) ? {ctf: r.ctf, ctb: r.ctb} : {})};  // 2.36.1 (#1021): office/<tab>/<id>; 2.48.0 (#1207, #1111): ablage/<id>, docs/<id>; 2.49.0 (#1199): wiki/<id>; 2.351.0 B (#2749): contacts/f|b/<id>
  sbb_seen(r);  // 2.152.2 (#2622): the area keeps this page (sidebar B, areas.js)
  wsv_seen();  // 2.397.0 (#3404): and its workspace (workspace.js)
  if (r.mod === 'team') teamRoute(r.rid || null); else if (S.tc.rid) teamRoute(null);  // 2.17.0
  if (r.mod === 'notes') noteRoute(r.lid, r.nid || null); else if (S.nt.id) { if (!qn_leave()) noteFlush(); S.nt.id = null; }  // 2.477.0 (#3881): qn_leave
  if (r.noteMissing) setTimeout(() => toast(tr('This note does not exist or you cannot see it.')), 0);  // 2.10.0: review = #today/review
  if (r.mod === 'agents') S.jobs.items = null;
  S.jobFocus = r.job || null;  // 2.36.2 (#1141): #job/<id>
  if (S.route.mod !== 'tasks' || r.key !== S.lastRouteKey) { S.multi.clear(); S.multiMode = false; }
  if (r.key === 'search' && S.lastRouteKey !== 'search') S.searchFocus = true;  // 2.15.1 (#633): opening Search focuses its field on a phone too (a re-render or a task closed on top of it does not)
  S.lastRouteKey = r.key;
  if (r.mod === 'tasks' && r.key !== 'search') LS.set('lastKey', r.key);
  if (r.mod === 'tasks' && r.key.startsWith('l:')) recentPush('l', +r.key.slice(2));
  S.extra = (r.key === 'done' || r.key === 'trash' || r.mod === 'news' || r.mod === 'time') ? [] : null;
  S.hist.k = null;  // 2.40.0 (#1432): entering Completed / Trash starts with the first page again
  if (S.extra) await loadExtra().catch(() => { S.extra = []; });
  // 2.26.x (#953): back to an entry that was left from the open drawer (phone / folded sidebar): the drawer opens again
  // and stays; the next Back goes on as before
  if (history.state?.side && !r.task && (isMobile() || $('#app')?.classList.contains('side-rail'))) setTimeout(() => { if (!history.state?.side) return; try { const {side, ...st} = history.state; history.replaceState(Object.keys(st).length ? st : null, '', location.href); } catch { /* old browser */ } if (!$('#side.open')) sideDrawerOpen(); }, 0);  // 2.534.0 (#4344): side is used up once - a later route() without a Back does not reopen the drawer
  if (!(typeof sbm_hold === 'function' && sbm_hold())) closeSide();  // 2.196.0 A (#2737): an area icon in the phone's drawer keeps it open
  tch_overlaysClose();  // 2.38.0 (#1155)
  // 2.622.0 (#4948): the #t/<id> entry becomes the list's own entry BEFORE the task opens. It used to stay behind as a second entry
  // (the task's {detail} entry got the list's address and lost its mark): the phone's system Back landed on #t/<id>, which opened
  // the task again (or, after the Back of an overlay, did nothing). A link / go() inside the app (a new entry without a state) puts
  // the task into that entry (here: one Back closes it, the next one is the view before); a page load or a step onto an old
  // #t/<id> keeps the list entry and the task gets its own entry on top (openDetail)
  if (r.task) { render(); if (taskById(r.task)?.unread || r.reply) S.tlScroll = r.task; const here = history.state == null; history.replaceState(null, '', '#' + keyToHash(S.route.key)); openDetail(r.task, {here}); if (r.reply) replyFocus(r.task); return; }
  if (r.prop) { history.replaceState(null, '', '#' + keyToHash(S.route.key)); render(); propOpen(r.prop); return; }
  if (r.msg) { history.replaceState(null, '', '#' + keyToHash(S.route.key)); render(); msgJump({art: r.msg.art, id: r.msg.id, chat: r.msg.art === 't' ? r.msg.place : null, agent: r.msg.art === 'a' ? r.msg.place : null}); return; }  // 2.37.0 (#1159)
  if (r.snooze || r.complete || r.nagoff) {
    history.replaceState(null, '', '#' + keyToHash(S.route.key));
    render();
    const t = taskById(r.snooze || r.complete || r.nagoff);
    if (!t) { toast(tr('Task not found')); return; }
    // 2.190.0 C (#2496): links too: confirm first
    if (r.nagoff) { if (!nagOf(t)) toast(tr('This task does not repeat its reminder')); else if (await askConfirm(tr('Stop repeated reminders for “{0}”?', t.title), '', {ok: tr('Stop reminding')})) await patchUndoable(t.id, {nag: 'off'}, tr('No more repeated reminders for “{0}”', t.title)); return; }
    if (r.complete) { if (t.status !== 0) toast(tr('Already completed')); else if (await askConfirm(tr('Complete “{0}”?', t.title), '', {ok: tr('Complete')})) toggleTask(t.id); }
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
const keyToHash = k => k.startsWith('lists:') ? 'lists/' + k.slice(6) : k.startsWith('who:') ? 'who/' + k.slice(4) : k.startsWith('grp:') ? 'grp/' + k.slice(4) : k.startsWith('l:') ? 'l/' + k.slice(2) : k.startsWith('f:') ? 'f/' + k.slice(2) : k.startsWith('tag:') ? 'tag/' + encodeURIComponent(k.slice(4)) : k.startsWith('folder:') ? 'folder/' + encodeURIComponent(k.slice(7)) : k;
// 1.5.2: folder view (key "folder:<name>"): the open tasks of every active list in that sidebar folder, grouped by list
const folderLists = f => sideOrder().filter(l => fUnder(l.folder, f) && !l.archived && !l.is_inbox);  // 2.4.0: subfolders too
window.addEventListener('hashchange', route);

// 2.461 (#3773): the holiday picker of Settings and the Absences tab: first the country, then its region. What is stored is one
// code (the select `id`): a region, or the country itself ("only the nationwide ones"); `blank` names "no choice"; `attrs` go on
// the select `id`, which fires the usual change. cs: the answer's countries.
let HOL_CS = [];
function hol_country(cs, v) { return cs.find(c => c.code === v || v in c.regions); }
function hol_regions(c, v, blank) {
  if (!c) return `<option value="">${esc(blank)}</option>`;
  return `<option value="${esc(c.code)}">${tr('Nationwide holidays only')}</option>` + Object.entries(c.regions).map(([k, n]) => `<option value="${esc(k)}" ${k === v ? 'selected' : ''}>${esc(n)}</option>`).join('');
}
function hol_selects(id, cs, v, blank, attrs = '') {
  HOL_CS = cs;
  const c = hol_country(cs, v), off = /\bdisabled\b/.test(attrs) ? 'disabled' : '';
  return `<span class="holsel"><select id="${id}-cc" aria-label="${esc(tr('Country'))}" ${off}><option value="">${esc(blank)}</option>${cs.map(x => `<option value="${esc(x.code)}" ${x === c ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select>
    <select id="${id}" aria-label="${esc(tr('Region'))}" ${attrs} ${c && Object.keys(c.regions).length ? '' : 'hidden'}>${hol_regions(c, v, blank)}</select></span>`;
}
document.addEventListener('change', e => {  // the country changed: its regions, starting on the nationwide holidays
  const t = /** @type {any} */ (e.target), box = t.closest?.('.holsel');
  if (!box || t !== box.firstElementChild) return;
  const rg = /** @type {any} */ (t.nextElementSibling), c = HOL_CS.find(x => x.code === t.value);
  rg.innerHTML = hol_regions(c, '', t.options[0].textContent);
  rg.hidden = !c || !Object.keys(c.regions).length;
  rg.value = t.value;
  rg.dispatchEvent(new Event('change', {bubbles: true}));
});
