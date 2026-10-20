/* Kalmido browser demo: an in-browser stand-in for the server. Loaded before the app (see tools/build_demo.py); it replaces
   window.fetch, so the unchanged app (static/app.js) talks to this file instead of a server. Everything lives in
   localStorage of this browser (key kalmido-demo.db); nothing is ever sent anywhere (the page's CSP also forbids it:
   connect-src 'none').
   Implemented: lists, sections, tasks (subtasks, tags, fields, dependencies, repeats, trash), Today / Upcoming / kanban /
   timeline / calendar data, comments (local), time tracking, habits, filters, milestones and project status, day plan,
   settings (appearance, language, modules) and a simulated agent with one approval.
   2.74.0 (#1653): the demo starts like a new account (empty Basket, "Getting started" list, welcome tour); the sample
   project comes on request (tour, Settings > Data) and the office (clients, services, quotations, invoices, payments,
   print view instead of the server's PDF) runs here too, see demo-office below. Everything that needs a server
   (push, CalDAV, calendar subscriptions, real agents, Git, webhooks, OIDC, more users, imports, backups) answers
   with a calm "not available in the demo" notice and a link to the install page. */
'use strict';
(() => {
  const KEY = 'kalmido-demo.db', VER = 2;  // 2.74.0 (#1653): 2 = starts as a new account, + office (1 is migrated)
  const TX = window.KDEMO_TEXTS, LANGS = ['en', 'de', 'fr', 'es', 'it', 'nl'];
  const SITE = window.KDEMO_SITE || '../';
  const browserLang = () => {
    for (const l of navigator.languages || [navigator.language || 'en']) { const c = String(l).slice(0, 2).toLowerCase(); if (LANGS.includes(c)) return c; }
    return 'en';
  };
  const T = () => TX[(DB && DB.settings.lang) || browserLang()] || TX.en;
  const pad = n => String(n).padStart(2, '0');
  const ds = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const today = () => ds(new Date());
  const day = n => { const d = new Date(); d.setHours(12, 0, 0, 0); d.setDate(d.getDate() + n); return ds(d); };
  const iso = d => (d || new Date()).toISOString().replace(/\.\d{3}Z$/, '+00:00');
  const atLocal = (n, h, m = 0) => { const d = new Date(); d.setDate(d.getDate() + n); d.setHours(h, m, 0, 0); return iso(d); };
  const clone = o => JSON.parse(JSON.stringify(o));
  let DB = null;

  // ---------------------------------------------------------------- storage
  function save() { try { localStorage.setItem(KEY, JSON.stringify(DB)); } catch { /* full / private mode: stays in memory */ } }
  function loadDb() {
    try { const j = JSON.parse(localStorage.getItem(KEY)); if (j && j.ver === VER && j.tasks) return j; if (j && j.ver === 1 && j.tasks) return migrate1(j); } catch { /* broken: new seed */ }
    return null;
  }
  // 2.74.0 (#1653): a visitor of the old demo (version 1: the sample data from the start) keeps the data; the tour and the
  // "Getting started" list are behind them, the sample counts as their own (no "Remove sample project")
  function migrate1(j) {
    j.ver = VER; j.settings = {...j.settings, onboard: 'done', tour: 'done', sample_ask: '0'};
    j.sample = null; j.office = null;
    return j;
  }
  const bump = () => { DB.v++; save(); };
  const nid = k => { DB.seq[k] = (DB.seq[k] || 0) + 1; return DB.seq[k]; };

  // ---------------------------------------------------------------- seed (sample data in the visitor's language)
  const TASK_DEF = {assigned_by: null, assignee_group_id: null, assignee_id: null, attachments: [], completed_at: null, completed_by: null,
    content: '', created_by: 1, deadline: 0, deleted_at: null, due: null, due_time: null, duration: null, fields: {}, ltags: [], nag: '',
    parent_id: null, pinned: 0, plan_start: null, priority: 0, reminders: '', repeat: '', repeat_from: 'due', section_id: null,
    sort: 0, start: null, status: 0, tags: [], tt_id: null, ttype: '', unread: 0, url: null, wait_by: null, wait_fired: '', wait_note: '',
    wait_until: null, waiting_at: null};
  const LIST_DEF = {agent_tidy: 'off', columns: null, archived: 0, archived_at: null, bell: 'default', bell_custom: {}, checklist: 0, color: '', day_hours: null,
    dep_shift: 0, description: '', folder: '', groups: [], icon: '', is_inbox: 0, kind: 'list', milestones: [], nag: '', owner_id: 1, rate: null,
    repos: [], role: 'owner', sort: 0, status: '', status_at: null, status_by: null, status_note: '', tags: [], ticket_tpl: '', tickets: 0,
    tidy_agent_id: null, view: 'list', family: ''};
  const SETTINGS_DEF = {agent_share: '{}', agents_hidden: '', allday_time: '09:00', cal_today: '1', celebrate: '1', comment_order: 'old',
    date_confirm: '0', default_reminder: '0', digest_time: '', features: 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,comments,events,contacts,files,docs,agents',  // 2.125.0 D (#1653): USER_DEFAULTS + agents
    features_rev: '11', show_done_default: '0', folders: '[]', folders_closed: '[]', hide_blocked_today: '0', hide_progress: '', ical_alarms: '1', ical_scope: 'all',
    lang: 'en', nav_order: 'tasks,cal,matrix,habits', news_kinds: 'mention,assign,comment,unblock,share,status', notify: '', ntfy_topic: '',
    onboard: 'pending', pomo_focus: '25', pomo_long: '15', pomo_long_every: '4', pomo_short: '5', progress_subtasks: '0',
    push_channel: 'webpush', push_priority: '4', quiet_from: '22:00', quiet_to: '07:00', review_time: '', roadmap: '', sample_ask: '1',
    show_done_views: '{}', time_autostop_h: '12', time_currency: '€', time_focus: '1', time_remind_h: '4', time_rounding: '0', time_target: '0',
    tour: 'pending', work_end: '17:00', work_start: '09:00',
    setup: 'pending'};  // 2.125.0 D (#1653): the first start shows the intro + module choice of a new account (an older storage has no key = done)
  const AGENT = 2;

  // 2.74.0 (#1653): a new account: the Basket (named in the visitor's language), the simulated agent with its hello; the
  // "Getting started" list follows on the first start (POST /api/onboarding), the sample on request (POST /api/sample)
  function seed(lang) {
    const x = TX[lang] || TX.en;
    DB = {ver: VER, v: 1, seq: {}, settings: {...SETTINGS_DEF, lang}, me: {id: 1, username: 'demo', display_name: 'Demo', avatar: ''},
      lists: [], sections: [], tasks: [], fields: [], deps: [], comments: [], activity: [], time: [], timer: null, habits: [], filters: [],
      status: [], chat: [], jobs: [], agent: {status: 'idle', status_text: '', status_task: null, step: 0}, sample: null, office: null};
    DB.lists.push({...clone(LIST_DEF), id: nid('list'), created_at: iso(), name: x.inbox, is_inbox: 1, sort: -1});
    DB.chat.push({id: nid('chat'), agent_id: AGENT, user_id: 1, from: 'agent', body: x.agentChatHello, task_id: null, created_at: iso(), delivered_at: null, reactions: [], read: 0});
    save();
  }

  // the sample (Café Aurora) in the visitor's language; every row it creates is recorded in DB.sample (removal takes exactly that)
  function sampleMake() {
    const x = T(), t = x.t, now = iso(), inbox = DB.lists.find(l => l.is_inbox) || DB.lists[0];
    const rec = DB.sample = {lists: [], tasks: [], sections: [], fields: [], time: [], jobs: []};
    const list = o => { const l = {...clone(LIST_DEF), id: nid('list'), created_at: now, ...o}; DB.lists.push(l); rec.lists.push(l.id); return l; };
    const sec = (lid, name, sort) => { const s = {id: nid('section'), list_id: lid, name, sort}; DB.sections.push(s); rec.sections.push(s.id); return s.id; };
    const task = o => { const k = {...clone(TASK_DEF), id: nid('task'), created_at: now, updated_at: now, ...o}; if (k.status && !k.completed_at) { k.completed_at = now; k.completed_by = 1; } DB.tasks.push(k); rec.tasks.push(k.id); return k; };
    const base = Math.max(0, ...DB.lists.map(l => l.sort));
    const p = list({name: x.project, kind: 'project', time_tracking: 1, color: '#7c5cff', sort: base + 1, tickets: 1, status: 'on_track', status_at: now, status_by: 1, status_note: x.status,  // 2.41.0 (#1471): time_tracking; 2.74.0 (#1653): the status was inside this comment
      description: '', milestones: [{id: 1, name: x.ms1, day: day(4), done: 0}, {id: 2, name: x.ms2, day: day(20), done: 0}]});
    DB.seq.ms = Math.max(DB.seq.ms || 0, 2);
    const priv = list({name: x.personal, color: '#22c55e', sort: base + 2});
    const S = x.secs.map((n, i) => sec(p.id, n, i + 1));
    const fb = {id: nid('field'), list_id: p.id, name: x.budget, type: 'number', options: {unit: '€'}, pinned: 1, sort: 1};
    const fe = {id: nid('field'), list_id: p.id, name: x.effort, type: 'select', pinned: 1, sort: 2,
      options: {options: [{id: 's', name: x.small, color: '#22c55e'}, {id: 'm', name: x.medium, color: '#f59e0b'}, {id: 'l', name: x.large, color: '#ef4444'}]}};
    DB.fields.push(fb, fe); rec.fields.push(fb.id, fe.id);
    const cl = x.tags.client, web = x.tags.web;
    const tk = (o, type) => task({list_id: p.id, ...o, ...(type ? {ttype: type} : {})});
    const kick = tk({section_id: S[0], title: t.kickoff, priority: 3, status: 2, due: day(-9), completed_at: atLocal(-9, 16), completed_by: 1, tags: [cl], sort: 1}, 'task');
    const site = tk({section_id: S[0], title: t.sitemap, priority: 3, status: 2, due: day(-6), completed_at: atLocal(-6, 15), completed_by: 1, sort: 2, fields: {[fe.id]: 's'}}, 'task');
    tk({section_id: S[1], title: t.moodboard, priority: 1, status: 2, due: day(-4), completed_at: atLocal(-3, 11), completed_by: 1, sort: 3}, 'task');
    const lay = tk({section_id: S[1], title: t.layouts, content: t.layoutsNote, priority: 5, start: day(-3), due: day(0), sort: 4, tags: [web], fields: {[fb.id]: '2400', [fe.id]: 'l'}}, 'feature');
    task({list_id: p.id, section_id: S[1], parent_id: lay.id, title: t.subA, status: 2, sort: 1});
    task({list_id: p.id, section_id: S[1], parent_id: lay.id, title: t.subB, sort: 2});
    task({list_id: p.id, section_id: S[1], parent_id: lay.id, title: t.subC, sort: 3});
    const appr = tk({section_id: S[1], title: t.approval, priority: 5, due: day(4), sort: 5, tags: [cl]}, 'task');
    const cms = tk({section_id: S[2], title: t.cms, priority: 3, start: day(1), due: day(6), sort: 6, fields: {[fb.id]: '900', [fe.id]: 'm'}}, 'task');
    const form = tk({section_id: S[2], title: t.form, priority: 5, due: day(1), sort: 7, tags: [web]}, 'bug');
    tk({section_id: S[2], title: t.booking, priority: 3, start: day(7), due: day(12), sort: 8, fields: {[fe.id]: 'l'}}, 'feature');
    tk({section_id: S[2], title: t.images, priority: 1, due: day(10), sort: 9}, 'task');
    tk({section_id: S[2], title: t.menuBug, priority: 3, due: day(2), sort: 10, tags: [web]}, 'bug');
    tk({section_id: S[3], title: t.seo, priority: 1, due: day(15), sort: 11}, 'task');
    const live = tk({section_id: S[3], title: t.golive, priority: 5, due: day(20), due_time: '09:00', duration: 60, sort: 12, tags: [cl]}, 'task');
    tk({section_id: S[3], title: t.training, priority: 0, due: day(21), due_time: '14:00', duration: 90, sort: 13}, 'task');
    const wd = new Date().getDay(), tue = (2 - wd + 7) % 7;
    task({list_id: p.id, title: t.call, due: day(tue), due_time: '10:00', duration: 30, repeat: 'FREQ=WEEKLY;BYDAY=TU', sort: 14});
    DB.deps.push([appr.id, lay.id], [cms.id, appr.id], [live.id, cms.id]);
    DB.comments.push({id: nid('comment'), task_id: appr.id, user_id: 1, body: t.comment, created_at: atLocal(0, 9, 12), edited_at: null, mentions: [], reactions: [], attachments: [], suggestion: null});
    DB.status.push({id: nid('status'), list_id: p.id, user_id: 1, status: 'on_track', note: x.status, created_at: now});
    // time entries (the last days)
    const te = (n, h, mins, tid, note) => { const st = new Date(); st.setDate(st.getDate() + n); st.setHours(h, 0, 0, 0); const en = new Date(st.getTime() + mins * 60000);
      const e = {id: nid('time'), user_id: 1, task_id: tid, list_id: p.id, start: iso(st), end: iso(en), seconds: mins * 60, note, source: 'manual', created_at: now, updated_at: now}; DB.time.push(e); rec.time.push(e.id); };
    te(-9, 10, 120, kick.id, t.time1); te(-6, 14, 90, site.id, ''); te(-2, 9, 150, lay.id, t.time2); te(-1, 13, 105, lay.id, ''); te(-1, 16, 45, cms.id, t.time3);
    // personal list + inbox
    const home = x.tags.home;
    task({list_id: priv.id, title: t.gift, priority: 3, due: day(1), sort: 1});
    task({list_id: priv.id, title: t.dentist, priority: 1, due: day(7 - ((wd + 6) % 7)), sort: 2});
    task({list_id: priv.id, title: t.plants, due: day(0), repeat: 'FREQ=WEEKLY', sort: 3, tags: [home]});
    task({list_id: priv.id, title: t.book, sort: 4});
    task({list_id: priv.id, title: t.grandma, due: day(0), due_time: '18:30', sort: 5});
    task({list_id: inbox.id, title: t.groceries, sort: 1, tags: [home]});
    task({list_id: inbox.id, title: t.idea, sort: 2});
    // the simulated agent works in the project: status on the form bug, one job waiting for approval
    DB.agent.status_task = form.id; DB.agent.status = 'working'; DB.agent.status_text = x.agentTexts[0];
    p.members = [{user_id: AGENT, name: x.agentName, role: 'editor', username: 'demo-agent', via_group: false, group_role: null}];
    p.shared = true;
    const jid = nid('job'); rec.jobs.push(jid);
    DB.jobs.push({id: jid, agent_id: AGENT, task_id: cms.id, user_id: 1, title: x.jobTitle, state: 'waiting', log: x.jobLog, action: null, action_by: null,
      action_at: null, created_at: atLocal(0, 8, 40), updated_at: atLocal(0, 8, 40), kind: null, prop_state: null});
    return p.id;
  }
  function sampleState() {
    const r = DB.sample; if (!r) return null;
    const own = new Set(r.tasks), tasks = DB.tasks.filter(t => own.has(t.id)).length;
    const lists = DB.lists.filter(l => r.lists.includes(l.id)).map(l => ({id: l.id, name: l.name, extra: DB.tasks.filter(t => t.list_id === l.id && !own.has(t.id)).length}));
    return tasks || lists.length ? {tasks, lists} : null;
  }
  function sampleRemove() {
    const r = DB.sample, own = new Set(r.tasks);
    const gone = DB.tasks.filter(t => own.has(t.id)).length; let lists = 0, kept = 0;
    DB.tasks = DB.tasks.filter(t => !own.has(t.id)); DB.deps = DB.deps.filter(d => taskById(d[0]) && taskById(d[1]));
    DB.comments = DB.comments.filter(c => taskById(c.task_id));
    DB.time = DB.time.filter(e => !r.time.includes(e.id)); if (DB.timer && !DB.time.some(e => e.id === DB.timer)) DB.timer = null;
    DB.fields = DB.fields.filter(f => !r.fields.includes(f.id));
    DB.jobs = DB.jobs.filter(j => !r.jobs.includes(j.id)); DB.agent = {...DB.agent, status: 'idle', status_text: '', status_task: null};
    for (const lid of r.lists) {
      const l = listById(lid); if (!l) continue;
      if (DB.tasks.some(t => t.list_id === lid)) { kept++; continue; }
      DB.lists = DB.lists.filter(x => x !== l); DB.sections = DB.sections.filter(x => x.list_id !== lid); DB.status = DB.status.filter(x => x.list_id !== lid); lists++;
    }
    DB.sample = null;
    return {ok: true, tasks: gone, lists, kept_lists: kept, kept_tasks: DB.tasks.filter(t => r.lists.includes(t.list_id)).length};
  }

  // the "Getting started" list of a new account (kalmido/accounts/onboarding.py onboarding_tasks, same texts via the app's translations)
  function onboardTasks(feats, touch, mac) {
    const tt = [
      [touch ? 'Tap the square on the left, or swipe the task to the right.' : 'Click the square on the left to complete a task.', 'Tick me off', 5, true, []],
      ['Everything about a task lives in this panel:\n\n- a description with **Markdown**\n- [ ] checklists like this one\n- files, links, dates and reminders',
        touch ? 'Tap me for details, notes and subtasks' : 'Click me for details, notes and subtasks', 3, true, ['Subtasks work like tasks', 'Tick this one off, too']],
      ['Type it into the add bar (the + button on a phone): dates, times, !priority, #tags and ~list are recognized while you type.', 'Try quick add: Dentist tomorrow 3pm !high #private', 3, true, []],
      [touch ? 'Swipe left for snooze, other dates and delete; long-press for the task’s menu, long-press and drag to reorder.'
        : 'Drag tasks onto a day, a list or another place in the list. Right-click is not needed: the … menu has the rest.', touch ? 'Swipe me left to reschedule' : 'Drag me onto Tomorrow in the sidebar', 1, true, []],
    ];
    if (!touch) tt.push(['Lists, tasks, views and actions in one box. Press ? for all keyboard shortcuts.', 'Press {0} to search and run commands', 0, false, []]);
    const mods = [['habits', 'Create a habit under Habits', 'Daily or a few times a week, with streaks.'],
      ['pomo', 'Start a focus timer on a task', 'Task menu (…) > Start focus, or the Focus timer module.'],
      ['collab', 'Share this list with someone', 'List menu (…) > Sharing. Tasks in shared lists can be assigned and commented.'],
      ['time', 'Start a timer on a task', 'Task menu (…) > Start timer; reports under Time tracking.'],
      ['timeline+deps', 'Plan a project in the timeline', touch ? 'Edit list > Type: Project, View: Timeline. Long-press a bar and choose “Connect to…”, then tap the task it blocks.'
        : 'Edit list > Type: Project, View: Timeline. Drag the dot at the end of one bar onto another: the second task is then blocked by the first.']];
    for (const [k, title, d] of mods) if (k.split('+').every(f => feats.includes(f))) tt.push([d, title, 0, false, []]);
    tt.push(['List menu (…) > Delete. Nothing else is affected.', 'Delete this list when you are done', 0, false, []]);
    return tt;
  }
  function onboard(b) {
    if (DB.settings.onboard !== 'pending') return {ok: true, created: false};
    const feats = DB.settings.features.split(',').filter(Boolean), touch = b.touch === true, mac = b.mac === true;
    const kind = ['time', 'deps', 'fields'].some(f => feats.includes(f)) ? 'project' : 'list';
    const l = {...clone(LIST_DEF), id: nid('list'), created_at: iso(), name: tx('Getting started'), color: '#2dd4bf', kind, sort: Math.max(0, ...DB.lists.map(x => x.sort)) + 1};
    DB.lists.push(l);
    onboardTasks(feats, touch, mac).forEach(([content, title, priority, due, subs], i) => {
      const t = {...clone(TASK_DEF), id: nid('task'), created_at: iso(), updated_at: iso(), list_id: l.id, title: tx(title).replace('{0}', mac ? '⌘K' : 'Ctrl+K'),
        content: tx(content), priority, due: due ? today() : null, sort: i};
      DB.tasks.push(t);
      subs.forEach((st, j) => DB.tasks.push({...clone(TASK_DEF), id: nid('task'), created_at: iso(), updated_at: iso(), list_id: l.id, parent_id: t.id, title: tx(st), sort: j}));
    });
    DB.settings.onboard = 'done';
    return {ok: true, created: true, list_id: l.id};
  }

  // ---------------------------------------------------------------- views of the data (shapes of the server's JSON)
  const listById = id => DB.lists.find(l => l.id === +id);
  const taskById = id => DB.tasks.find(t => t.id === +id);
  const live = () => DB.tasks.filter(t => !t.deleted_at);
  const agentName = () => T().agentName + ' · ' + T().simulated;
  function taskOut(t) {
    const blockers = DB.deps.filter(d => d[0] === t.id).map(d => d[1]).filter(b => { const x = taskById(b); return x && !x.deleted_at && x.status === 0; });
    const blocking = DB.deps.filter(d => d[1] === t.id && t.status === 0).length;
    return {...clone(t), blockers, blocked: blockers.length ? 1 : 0, blocking: blocking ? 1 : 0,
      comment_count: DB.comments.filter(c => c.task_id === t.id).length};
  }
  function listOut(l) {
    const ts = live().filter(t => t.list_id === l.id && !t.parent_id);
    const open = ts.filter(t => t.status === 0), t0 = today();
    const nd = open.map(t => t.due).filter(Boolean).sort()[0] || null;
    return {...clone(l), owner_name: DB.me.display_name, members: (l.members || []).map(m => ({...m, name: m.user_id === AGENT ? agentName() : m.name})),
      shared: !!(l.members || []).length, progress: {done: ts.length - open.length, total: ts.length, overdue: open.filter(t => t.due && t.due < t0).length, next_due: nd}};
  }
  function secsOf(e) { return e.end ? e.seconds : Math.max(0, Math.round((Date.now() - Date.parse(e.start)) / 1000)); }
  function entryOut(e) {
    const t = taskById(e.task_id), s = secsOf(e);
    return {auto_stopped: false, client_id: null, end: e.end, id: e.id, list_id: e.list_id, mine: true, note: e.note || '', rounded: s, running: !e.end,
      seconds: s, source: e.source, start: e.start, task_id: e.task_id, title: t ? t.title : (e.title || ''), user_id: 1, user_name: DB.me.display_name};
  }
  function agentOut() {
    const a = DB.agent, w = DB.jobs.filter(j => j.state === 'waiting').length, r = DB.jobs.filter(j => j.state === 'running').length;
    return {id: AGENT, username: 'demo-agent', name: agentName(), display_name: agentName(), avatar: 'static/avatars/robot.svg', enabled: true,
      status: a.status, status_text: a.status_text, status_at: iso(), status_task: a.status_task, job_tasks: [], running: r, waiting: w,
      chat_unread: DB.chat.filter(m => m.from === 'agent' && !m.read).length, limit_reached: false, online: true, last_poll_at: iso(), typing: 0,
      webhook: false, contact_age: 0, poll_age: 0, my_job: false};
  }
  function jobOut(j) {
    const t = taskById(j.task_id);
    return {id: j.id, agent_id: j.agent_id, agent_name: agentName(), task_id: j.task_id, task_title: t ? t.title : null, list_id: t ? t.list_id : null,
      user_id: j.user_id, title: j.title, state: j.state, log: j.log, action: j.action, action_by: j.action_by, action_by_name: j.action_by ? DB.me.display_name : '',
      action_at: j.action_at, created_at: j.created_at, updated_at: j.updated_at, kind: j.kind, proposal_state: null, can_act: true, can_stop: true};
  }
  function state() {
    const cutoff = new Date(Date.now() - 14 * 864e5).toISOString();
    const tasks = live().filter(t => t.status === 0 || (t.completed_at && t.completed_at >= cutoff) || listById(t.list_id)?.checklist).map(taskOut);
    const tt = {}, tl = {};
    for (const e of DB.time) {
      const s = secsOf(e);
      if (e.task_id) { const a = tt[e.task_id] || [0, 0]; a[0] += s; a[1] += s; tt[e.task_id] = a; }
      if (e.list_id) { const b = tl[e.list_id] || {b: null, s: 0}; b.s += s; tl[e.list_id] = b; }
    }
    const me = DB.me;
    return {
      v: DB.v, me: {auth: 'session', avatar: me.avatar, display_name: me.display_name, has_password: true, id: 1, is_admin: false, ntfy_inbox: false, username: me.username},
      lists: DB.lists.map(listOut).sort((a, b) => b.is_inbox - a.is_inbox || a.sort - b.sort || a.id - b.id),
      filters: clone(DB.filters), sections: clone(DB.sections).sort((a, b) => a.sort - b.sort || a.id - b.id), fields: clone(DB.fields),
      tasks, habits: clone(DB.habits), pomo: null, pomo_today: {count: 0, minutes: 0},
      counts: {done: live().filter(t => t.status !== 0).length, trash: DB.tasks.filter(t => t.deleted_at).length},
      settings: clone(DB.settings), notify: {},
      mine_hidden: [...(DB.mineHidden || [])],  // 2.41.0 (#1365)
      ntfy_inbox: {enabled: false, server: '', topic: ''}, ntfy_url: '', webpush: {devices: 0, enabled: false, key: ''},
      languages: [{beta: false, code: 'de', name: 'Deutsch'}, {beta: false, code: 'en', name: 'English'}, {beta: true, code: 'es', name: 'Español'},
        {beta: true, code: 'fr', name: 'Français'}, {beta: true, code: 'it', name: 'Italiano'}, {beta: true, code: 'nl', name: 'Nederlands'}],
      news: {unread: 0, sig: '0'}, avatars: {[AGENT]: 'static/avatars/robot.svg'}, templates: [],
      timer: DB.timer ? entryOut(DB.time.find(e => e.id === DB.timer)) : null, time_totals: tt, time_lists: tl, time_day_h: 8, collab_all: DB.inst?.collab_all !== false, time_all: DB.inst?.time_all !== false,
      about: {available: false, latest: '', checked_at: '', error: '', collab_all: DB.inst?.collab_all !== false, cal_on: false, oidc: {configured: false},
        org_name_env: true},  // 2.125.0 D (#1653): the demo has no organisation to name (the intro does not ask)
      calendars: {enabled: false, subs: 0}, api: {enabled: false}, webhooks: {enabled: false}, caldav: {enabled: false}, public_links: false,
      share: {drop_url: '', ios_shortcut: ''}, sample: sampleState(), agents: [agentOut()], proposers: [], groups: [], my_groups: [],
      dayplan: {default_duration: 30, review_time: '', work_end: DB.settings.work_end, work_start: DB.settings.work_start},
      kids: [], kid_ids: [],  // 2.19.0 (#653): no other accounts in the demo
      clients: DB.settings.features.split(',').includes('clients') ? (DB.clients || []).map(clientBrief) : [], workspaces: false,  // 2.74.0 (#1653)
      setup_pending: DB.settings.setup === 'pending', books: fon('contacts') ? books().map(bookOut) : [], evcals: fon('events') ? evcals().map(evcalOut) : [],  // 2.125.0 D (#1653): the intro (static/js/account.js setupChoices)
    };
  }

  // ---------------------------------------------------------------- helpers for writes
  class Http extends Error { constructor(status, body) { super(body.error || String(status)); this.status = status; this.body = body; } }
  const bad = msg => { throw new Http(400, {error: msg}); };
  const gone = () => { throw new Http(404, {error: 'Not found'}); };
  const needTask = id => { const t = taskById(id); if (!t) gone(); return t; };
  const TASK_FIELDS = ['title', 'content', 'priority', 'due', 'due_time', 'start', 'duration', 'reminders', 'repeat', 'repeat_from', 'url', 'list_id',
    'section_id', 'parent_id', 'sort', 'pinned', 'tags', 'ttype', 'deadline', 'nag', 'plan_start', 'assignee_id', 'status', 'fam', 'stars'];
  TASK_FIELDS.push('remind_at');  // 2.111.0 C (#2057): the fixed-time reminder
  function applyFields(t, b) {
    for (const k of TASK_FIELDS) if (k in b) t[k] = b[k];
    if ('title' in b && !String(b.title || '').trim()) bad('Title missing');
    if ('due' in b && !b.due) t.due_time = null;
    if (b.fields) { t.fields = {...(t.fields || {})}; for (const [k, v] of Object.entries(b.fields)) { if (v == null || v === '' || v === false) delete t.fields[k]; else t.fields[k] = v === true ? '1' : String(v); } }
    if ('list_id' in b && !('section_id' in b)) { const s = DB.sections.find(x => x.id === t.section_id); if (!s || s.list_id !== t.list_id) t.section_id = null; }
    if ('list_id' in b) for (const k of DB.tasks.filter(x => x.parent_id === t.id)) { k.list_id = t.list_id; k.section_id = t.section_id; }
    t.updated_at = iso();
  }
  // the next date of a repeat rule after `from` (the subset the sample data and quick add use: DAILY / WEEKLY (BYDAY) /
  // MONTHLY / YEARLY with INTERVAL)
  function nextDate(rule, from) {
    const r = Object.fromEntries(String(rule).split(';').map(p => p.split('='))), n = +(r.INTERVAL || 1);
    const d = new Date(from + 'T12:00:00');
    if (r.FREQ === 'WEEKLY' && r.BYDAY) {
      const days = r.BYDAY.split(',').map(x => ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'].indexOf(x));
      for (let i = 1; i < 7 * n + 8; i++) { const c = new Date(d); c.setDate(d.getDate() + i); if (days.includes(c.getDay()) && (n === 1 || i > 7 * (n - 1) || days.length > 1)) return ds(c); }
    }
    if (r.FREQ === 'DAILY') d.setDate(d.getDate() + n);
    else if (r.FREQ === 'WEEKLY') d.setDate(d.getDate() + 7 * n);
    else if (r.FREQ === 'MONTHLY') d.setMonth(d.getMonth() + n);
    else d.setFullYear(d.getFullYear() + n);
    return ds(d);
  }
  function complete(t, status = 2) {
    if (t.repeat && t.due && status === 2) {
      let nd = nextDate(t.repeat, t.due); while (nd <= today() && t.due < today()) nd = nextDate(t.repeat, nd);
      if (t.start) { const shift = (Date.parse(nd) - Date.parse(t.due)) / 864e5; const s = new Date(t.start + 'T12:00:00'); s.setDate(s.getDate() + shift); t.start = ds(s); }
      t.due = nd; t.updated_at = iso();
      return {...taskOut(t), next_due: nd};
    }
    t.status = status; t.completed_at = iso(); t.completed_by = 1; t.updated_at = iso();
    return {...taskOut(t), next_due: null};
  }
  const delTask = (t, hard) => { const ids = [t.id, ...DB.tasks.filter(x => x.parent_id === t.id).map(x => x.id)];
    if (hard) { DB.tasks = DB.tasks.filter(x => !ids.includes(x.id)); DB.deps = DB.deps.filter(d => !ids.includes(d[0]) && !ids.includes(d[1])); }
    else for (const x of DB.tasks) if (ids.includes(x.id)) x.deleted_at = iso(); };
  function newTask(b) {
    if (!String(b.title || '').trim()) bad('Title missing');
    const par = b.parent_id ? taskById(b.parent_id) : null;
    const lid = b.list_id || (par ? par.list_id : 1);
    if (!listById(lid)) bad('List not found');
    const t = {...clone(TASK_DEF), id: nid('task'), created_at: iso(), updated_at: iso(), list_id: lid,
      sort: par ? Math.max(0, ...DB.tasks.filter(x => x.parent_id === par.id).map(x => x.sort)) + 1 : Math.min(0, ...DB.tasks.filter(x => x.list_id === lid).map(x => x.sort)) - 1};
    applyFields(t, {...b, list_id: lid, section_id: b.section_id ?? (par ? par.section_id : null)});
    t.tags = [...new Set(b.tags || [])];
    if (t.repeat && !t.due) t.due = today();
    DB.tasks.push(t);
    return taskOut(t);
  }
  function timeline(id) {
    const cm = DB.comments.filter(c => c.task_id === id).map(c => ({...clone(c), reactions: c.reactions || []}));
    return {activity: DB.activity.filter(a => a.task_id === id), agents: [AGENT], approver: true, can_write: true, comments: cm, moderator: true,
      people: [{id: 1, name: DB.me.display_name}, {id: AGENT, name: agentName()}], seen: cm.length ? cm[cm.length - 1].id : 0,
      users: {1: DB.me.display_name, [AGENT]: agentName()}};
  }
  function occurrences(from, to) {
    const items = [];
    for (const t of live()) {
      if (!t.repeat || !t.due || t.status !== 0) continue;
      let d = t.due;
      for (let i = 0; i < 400; i++) { d = nextDate(t.repeat, d); if (d > to) break; if (d >= from) items.push({date: d, id: t.id}); }
    }
    return {items};
  }
  function timeReport(q) {
    const from = q.get('from'), to = q.get('to'), lid = q.get('list_id') ? +q.get('list_id') : null;
    const es = DB.time.filter(e => (!from || e.start.slice(0, 10) >= from) && (!to || e.start.slice(0, 10) <= to) && (!lid || e.list_id === lid)).map(e => ({...entryOut(e), amount: null, day: ds(new Date(e.start))}));
    const days = {}, lists = {};
    for (const e of es) {
      const d = days[e.day] || (days[e.day] = {date: e.day, rounded: 0, seconds: 0}); d.seconds += e.seconds; d.rounded += e.seconds;
      const l = listById(e.list_id) || {id: 0, name: '', color: '', is_inbox: 0};
      const L = lists[l.id] || (lists[l.id] = {amount: 0, color: l.color, id: l.id, is_inbox: !!l.is_inbox, name: l.name, rate: null, rounded: 0, seconds: 0, tasks: [], users: [[DB.me.display_name, 0]]});
      L.seconds += e.seconds; L.rounded += e.seconds; L.users[0][1] += e.seconds;
      let tk = L.tasks.find(x => x.id === e.task_id); if (!tk) L.tasks.push(tk = {amount: 0, id: e.task_id, rounded: 0, seconds: 0, title: e.title, users: [[DB.me.display_name, 0]]});
      tk.seconds += e.seconds; tk.rounded += e.seconds; tk.users[0][1] += e.seconds;
    }
    const tot = es.reduce((a, e) => a + e.seconds, 0);
    const tday = DB.time.filter(e => ds(new Date(e.start)) === today()).reduce((a, e) => a + secsOf(e), 0);
    return {currency: DB.settings.time_currency || '€', days: Object.values(days).sort((a, b) => a.date.localeCompare(b.date)), entries: es, from, to,
      lists: Object.values(lists), me: {...DB.me}, now: iso(), rounding: 0, scope: q.get('scope') || 'mine', today: {seconds: tday, target_h: +DB.settings.time_target || 0},
      total: {amount: 0, count: es.length, rounded: tot, seconds: tot}, users: [{id: 1, name: DB.me.display_name, rounded: tot, seconds: tot}]};
  }
  function dayplan(q) {
    const date = q.get('date') || today(), mode = q.get('mode') || 'day', dur = 30;
    const now = new Date(), t0 = today();
    let m = Math.max(...[DB.settings.work_start || '09:00'].map(s => +s.slice(0, 2) * 60 + +s.slice(3)), date === t0 ? Math.ceil((now.getHours() * 60 + now.getMinutes()) / 15) * 15 : 0);
    const end = +(DB.settings.work_end || '17:00').slice(0, 2) * 60 + +(DB.settings.work_end || '17:00').slice(3);
    const hm = x => `${pad(Math.floor(x / 60))}:${pad(x % 60)}`, P = {5: 'high', 3: 'medium', 1: 'low', 0: 'none'};
    const cand = live().filter(t => t.status === 0 && !t.parent_id && !t.due_time && t.due && t.due <= date).sort((a, b) => b.priority - a.priority || a.due.localeCompare(b.due));
    const plan = [], nofit = [], from = hm(m);
    for (const t of cand) {
      const d = t.duration || dur;
      if (m + d > end) { nofit.push({task_id: t.id, title: t.title}); continue; }
      plan.push({deadline: !!t.deadline, due: t.due, due_time: null, duration: d, end: hm(m + d), estimated: !t.duration, list: listById(t.list_id)?.name || '', list_id: t.list_id,
        priority: P[t.priority] || 'none', reason: t.due < t0 ? 'overdue' : 'today', start: hm(m), task_id: t.id, title: t.title});
      m += d;
    }
    return {candidates: cand.length, date, default_duration: dur, events: [], fixed: [], free_min: Math.max(0, end - m), from, mode, nofit, open_today: cand.length, plan,
      work: {end: DB.settings.work_end, start: DB.settings.work_start}};
  }

  // ---------------------------------------------------------------- the simulated agent
  function agentTick() {
    if (!DB) return;
    const a = DB.agent, w = DB.jobs.some(j => j.state === 'waiting');
    if (!w) return;
    a.step = (a.step + 1) % T().agentTexts.length;
    a.status = a.step === 2 ? 'waiting' : 'working';
    a.status_text = T().agentTexts[a.step];
    bump();
  }
  function jobAction(j, action) {
    j.action = action; j.action_by = 1; j.action_at = iso(); j.updated_at = iso();
    const x = T(), ok = action === 'approve';
    j.state = ok ? 'done' : action === 'reject' ? 'stopped' : 'stopped';
    DB.agent.status = 'idle'; DB.agent.status_text = ok ? x.agentDone : '';
    DB.chat.push({id: nid('chat'), agent_id: AGENT, user_id: 1, from: 'agent', body: ok ? x.agentChatOk : x.agentChatNo, task_id: j.task_id, created_at: iso(), delivered_at: null, reactions: [], read: 0});
    if (ok && j.task_id) DB.comments.push({id: nid('comment'), task_id: j.task_id, user_id: AGENT, body: x.agentChatOk, created_at: iso(), edited_at: null, mentions: [], reactions: [], attachments: [], suggestion: null});
  }

  // ---------------------------------------------------------------- routes
  const GATED = /^\/api\/(push|ical|calendars(?!\/events)|admin|import|imports|repos|me\/(webhooks|tokens|app-passwords|2fa|passkeys|drop-token)|my\/agents|users$|users\/|backups|public|oidc|attachments|list-files|templates|news\/|pomo|ntfy|proposals|folders\/groups|agents\/usage|family\/contacts)|\/(members|groups|owner|public-link|repos|paperless|files|icon|git-undo|attachments|take|wake|waiting|duplicate)(\/|$|\?)/;
  // automatic background calls of the app: answered quietly (no notice)
  const QUIET = {
    'GET /api/push/subs': () => ({subs: []}), 'GET /api/push/vapid': () => ({key: ''}), 'GET /api/my/agents': () => ({allowed: false, max: 0, count: 0, agents: [], api: false}),
    'GET /api/imports': () => ({imports: []}), 'GET /api/templates': () => ({templates: []}), 'GET /api/calendars': () => ({subs: [], enabled: false}),
    'GET /api/me/tokens': () => ({tokens: []}), 'GET /api/me/webhooks': () => ({webhooks: []}), 'GET /api/me/app-passwords': () => ({passwords: []}),
    'GET /api/me/2fa': () => ({totp: false, passkeys: [], recovery_left: 0}),
    'GET /api/agents/usage': () => ({days: [], agents: []}), 'POST /api/news/read': () => ({ok: true}),
    'GET /api/pomo/stats': () => ({days: [], total: 0}), 'GET /api/stale': () => ({tasks: [], count: 0, default_days: 7}),
    'GET /api/briefing': () => ({}), 'GET /api/layouts/saved': () => ({saved: []}), 'GET /api/layouts/std': () => ({layouts: {}, can: false}),
    'POST /api/favorites/suggestion': () => ({list_id: null}),  // 2.74.0 (#1653): was a write -> the notice popped up 8 s after the start 'GET /api/ical': () => ({enabled: false}),
  };
  const R = [], MISS = [], GATE = [], UNKNOWN = [], CALLS = [];  // 2.125.0 D (#1653): UNKNOWN = reads no route here knows (console.warn + a line)  // MISS: calls answered by the fallback (tests list them); GATE (2.74.0): office reads gated on purpose
  const on = (m, re, fn) => R.push([m, new RegExp('^' + re + '$'), fn]);
  on('GET', '/api/state', () => state());
  // 2.74.0 (#1653): the first start of a new account and the sample project on request
  on('POST', '/api/onboarding', (q, b) => onboard(b));
  on('POST', '/api/sample', () => { const st = sampleState(); if (st) return {ok: true, created: false, exists: true, list_id: st.lists[0]?.id ?? null, sample: st};
    const lid = sampleMake(); return {ok: true, created: true, list_id: lid, sample: sampleState()}; });
  on('DELETE', '/api/sample', () => { if (!sampleState()) { DB.sample = null; throw new Http(404, {error: tx('There is no sample project')}); } return sampleRemove(); });
  on('GET', '/api/version', () => ({v: DB.v, n: '0', c: '0'}));
  on('GET', '/api/servers', () => ({links: [], self: {name: 'Kalmido', short: 'K', color: '#6e56cf'}}));  // 2.73.0 (#661): no other servers in the demo
  on('GET', '/api/me', () => ({auth: 'session', avatar: DB.me.avatar, display_name: DB.me.display_name, has_password: true, id: 1, is_admin: false, username: DB.me.username, twofa: [], via: 'password', drop_token: '', proxy_login: '', ntfy_topic: ''}));
  on('PATCH', '/api/me', (q, b) => { for (const k of ['display_name', 'avatar']) if (k in b) DB.me[k] = b[k]; return {ok: true}; });
  on('PATCH', '/api/settings', (q, b) => { for (const [k, v] of Object.entries(b)) DB.settings[k] = typeof v === 'string' ? v : typeof v === 'boolean' ? (v ? '1' : '0') : typeof v === 'object' ? JSON.stringify(v) : String(v); return {ok: true}; });
  on('GET', '/api/news', () => ({avatars: {}, enabled: true, items: [], sig: '0', unread: 0, users: {}}));
  on('GET', '/api/users', () => ({users: [{id: 1, username: DB.me.username, display_name: DB.me.display_name, avatar: '', kind: 'user', is_admin: false, disabled: false}]}));
  // tasks
  on('GET', '/api/tasks', q => {
    const sc = q.get('scope') || 'done', lim = +(q.get('limit') || 300);
    if (sc === 'trash') return {tasks: DB.tasks.filter(t => t.deleted_at).sort((a, b) => b.deleted_at.localeCompare(a.deleted_at)).slice(0, lim).map(taskOut)};
    if (sc === 'search') { const s = (q.get('q') || '').toLowerCase(); return {tasks: live().filter(t => (t.title + ' ' + t.content + ' ' + (t.url || '')).toLowerCase().includes(s)).slice(0, lim).map(taskOut)}; }
    return {tasks: live().filter(t => t.status !== 0).sort((a, b) => String(b.completed_at).localeCompare(String(a.completed_at))).slice(0, lim).map(taskOut)};
  });
  on('POST', '/api/tasks', (q, b) => newTask(b));
  on('GET', '/api/tasks/(\\d+)', (q, b, id) => { const t = needTask(id); if (t.deleted_at) gone(); return taskOut(t); });
  on('PATCH', '/api/tasks/(\\d+)', (q, b, id) => { const t = needTask(id); applyFields(t, b); return {...taskOut(t), conflicts: [], shifted: []}; });
  on('DELETE', '/api/tasks/(\\d+)', (q, b, id) => { delTask(needTask(id), q.get('hard') === '1'); return {ok: true}; });
  on('POST', '/api/tasks/(\\d+)/complete', (q, b, id) => complete(needTask(id), b.status ?? 2));
  on('POST', '/api/tasks/(\\d+)/skip', (q, b, id) => complete(needTask(id)));
  on('POST', '/api/tasks/(\\d+)/reopen', (q, b, id) => { const t = needTask(id); t.status = 0; t.completed_at = null; t.completed_by = null; return taskOut(t); });
  on('POST', '/api/tasks/(\\d+)/undo', (q, b, id) => { const t = needTask(id); for (const k of ['due', 'start', 'status', 'completed_at']) if (k in b) t[k] = b[k]; return taskOut(t); });
  on('POST', '/api/tasks/(\\d+)/restore', (q, b, id) => { const t = needTask(id); for (const x of DB.tasks) if (x.id === t.id || x.parent_id === t.id) x.deleted_at = null; return {ok: true}; });
  on('POST', '/api/tasks/(\\d+)/seen', () => ({ok: true}));
  on('POST', '/api/tasks/purge-done', () => { const n = live().filter(t => t.status !== 0).length; for (const t of live()) if (t.status !== 0) t.deleted_at = iso(); return {ok: true, count: n}; });
  on('DELETE', '/api/trash', () => { DB.tasks = DB.tasks.filter(t => !t.deleted_at); return {ok: true}; });
  on('POST', '/api/tasks/reorder', (q, b) => { for (const it of b.items || []) { const t = taskById(it.id); if (t) applyFields(t, it); } return {ok: true}; });
  on('POST', '/api/tasks/batch', (q, b) => {
    for (const id of b.ids || []) {
      const t = taskById(id); if (!t) continue;
      const a = b.action, d = b.data || {};
      if (a === 'patch') { const {add_tags, ...rest} = d; applyFields(t, rest); if (add_tags) t.tags = [...new Set([...t.tags, ...add_tags])]; }
      else if (a === 'patch_each' && d.items?.[id]) { const {_prev, ...rest} = d.items[id]; applyFields(t, rest); }
      else if (a === 'complete') complete(t, d.status ?? 2);
      else if (a === 'reopen') { t.status = 0; t.completed_at = null; }
      else if (a === 'delete') delTask(t, false);
    }
    return {ok: true};
  });
  on('GET', '/api/tasks/(\\d+)/timeline', (q, b, id) => timeline(+id));
  on('POST', '/api/tasks/(\\d+)/comments', (q, b, id) => {
    needTask(id); const body = String(b.body || '').trim(); if (!body) bad('Comment is empty');
    const c = {id: nid('comment'), task_id: +id, user_id: 1, body, created_at: iso(), edited_at: null, mentions: [], reactions: [], attachments: [], suggestion: null};
    DB.comments.push(c); return clone(c);
  });
  on('PATCH', '/api/comments/(\\d+)', (q, b, id) => { const c = DB.comments.find(x => x.id === +id) || gone(); if ('body' in b) { c.body = String(b.body); c.edited_at = iso(); } return clone(c); });
  on('DELETE', '/api/comments/(\\d+)', (q, b, id) => { DB.comments = DB.comments.filter(x => x.id !== +id); return {ok: true}; });
  on('POST', '/api/comments/(\\d+)/reactions', (q, b, id) => {
    const c = DB.comments.find(x => x.id === +id) || gone(); c.reactions = c.reactions || [];
    const r = c.reactions.find(x => x.emoji === b.emoji);
    if (r) c.reactions = c.reactions.filter(x => x !== r); else c.reactions.push({emoji: b.emoji, count: 1, users: [{id: 1, name: DB.me.display_name}]});
    return {reactions: c.reactions};
  });
  // dependencies
  on('GET', '/api/deps', () => ({closed: [], edges: DB.deps.filter(d => taskById(d[0]) && taskById(d[1]))}));
  on('GET', '/api/tasks/(\\d+)/deps', (q, b, id) => {
    const mini = t => ({assignee_id: null, due: t.due, hidden: false, id: t.id, list_id: t.list_id, status: t.status, title: t.title});
    return {blocked_by: DB.deps.filter(d => d[0] === +id).map(d => taskById(d[1])).filter(Boolean).map(mini),
      blocking: DB.deps.filter(d => d[1] === +id).map(d => taskById(d[0])).filter(Boolean).map(mini)};
  });
  on('POST', '/api/deps', (q, b) => { const a = +b.task_id, c = +b.blocker_id; needTask(a); needTask(c); if (a === c) bad('A task cannot wait on itself');
    if (!DB.deps.some(d => d[0] === a && d[1] === c)) DB.deps.push([a, c]); return {ok: true}; });
  on('DELETE', '/api/deps/(\\d+)/(\\d+)', (q, b, a, c) => { DB.deps = DB.deps.filter(d => !(d[0] === +a && d[1] === +c)); return {ok: true}; });
  on('GET', '/api/occurrences', q => occurrences(q.get('from'), q.get('to')));
  // 2.125.0 D (#1653): + the own events (module events, see demo-modules)
  on('GET', '/api/calendars/events', q => evRange(q.get('from') || today(), q.get('to') || today()));
  on('GET', '/api/tags/count', q => { const tg = q.get('tag'); const ts = live().filter(t => t.tags.includes(tg)); return {open: ts.filter(t => t.status === 0).length, tasks: ts.length}; });
  on('POST', '/api/tags/delete', (q, b) => { const tg = b.tag || b.name; for (const t of DB.tasks) t.tags = t.tags.filter(x => x !== tg); return {ok: true, tasks: 0}; });
  on('POST', '/api/tags/rename', (q, b) => { for (const t of DB.tasks) t.tags = [...new Set(t.tags.map(x => x === b.old ? b.new : x))]; return {ok: true}; });
  // lists, sections, fields, milestones, status
  on('POST', '/api/lists', (q, b) => {
    if (!String(b.name || '').trim()) bad('Name missing');
    const l = {...clone(LIST_DEF), id: nid('list'), created_at: iso(), sort: Math.max(0, ...DB.lists.map(x => x.sort)) + 1};
    for (const k of ['name', 'color', 'folder', 'view', 'kind', 'checklist', 'tickets', 'nag', 'family']) if (k in b) l[k] = b[k];
    if (b.kind === 'checklist') { l.kind = 'list'; l.checklist = 1; }
    DB.lists.push(l);
    if (l.family === 'shopping' || l.family === 'packing') l.checklist = 1;
    if (l.family === 'shopping') shopAreas(l);
    return listOut(l);
  });
  // 2.41.0 (#1365): "Show in My tasks" per list; (#1205): the recent "Waiting on" entries (from the demo's own tasks)
  on('PUT', '/api/lists/(\\d+)/in-mine', (q, b, id) => { listById(id) || gone(); const h = new Set(DB.mineHidden || []); if (b.on) h.delete(+id); else h.add(+id); DB.mineHidden = [...h]; return {ok: true, on: !!b.on, mine_hidden: DB.mineHidden}; });
  const waitSugg = () => { const hid = new Set(DB.waitHidden || []), seen = new Set(); return DB.tasks.filter(t => t.wait_note).sort((a, b) => (b.waiting_at || '').localeCompare(a.waiting_at || '')).map(t => ({note: t.wait_note, at: t.waiting_at})).filter(x => { const k = x.note.toLowerCase(); if (hid.has(k) || seen.has(k)) return false; seen.add(k); return true; }).slice(0, 50); };
  on('GET', '/api/me/wait-suggestions', () => ({items: waitSugg()}));
  on('DELETE', '/api/me/wait-suggestions', (q, b) => { DB.waitHidden = [...new Set([...(DB.waitHidden || []), String(b.note || '').trim().toLowerCase()])]; return {ok: true, items: waitSugg()}; });
  on('PATCH', '/api/lists/(\\d+)', (q, b, id) => {
    const l = listById(id) || gone();
    for (const k of ['name', 'color', 'folder', 'sort', 'view', 'archived', 'checklist', 'dep_shift', 'kind', 'tickets', 'nag', 'description', 'agent_tidy', 'rate', 'day_hours', 'family', 'time_tracking', 'tap_done']) if (k in b) l[k] = typeof b[k] === 'boolean' ? (b[k] ? 1 : 0) : b[k];
    if ('done_at_bottom' in b) l.checklist = b.done_at_bottom ? 1 : 0;
    if ('archived' in b) l.archived_at = b.archived ? iso() : null;
    if ('columns' in b) l.columns = Array.isArray(b.columns) ? [...new Set(b.columns)] : null;  // 2.14.0 (#425)
    return listOut(l);
  });
  on('DELETE', '/api/lists/(\\d+)', (q, b, id) => { const l = listById(id) || gone(); if (l.is_inbox) bad('The inbox cannot be deleted');
    for (const t of DB.tasks) if (t.list_id === l.id) t.deleted_at = t.deleted_at || iso();
    DB.lists = DB.lists.filter(x => x !== l); DB.tasks = DB.tasks.filter(t => t.list_id !== l.id); DB.sections = DB.sections.filter(s => s.list_id !== l.id); return {ok: true}; });
  on('POST', '/api/lists/reorder', (q, b) => { for (const it of b.items || b.lists || []) { const l = listById(it.id); if (l) Object.assign(l, it); } return {ok: true}; });
  on('PUT', '/api/lists/(\\d+)/bell', (q, b, id) => { const l = listById(id) || gone(); l.bell = b.bell || b.mode || 'default'; return {ok: true}; });
  on('POST', '/api/lists/(\\d+)/checklist', (q, b, id) => { const l = listById(id) || gone(); l.checklist = b.on === false ? 0 : 1; return {ok: true}; });
  on('POST', '/api/lists/(\\d+)/shift', () => ({ok: true, moved: []}));
  on('POST', '/api/folders/rename', (q, b) => { for (const l of DB.lists) if (l.folder === b.old || l.folder.startsWith(b.old + '/')) l.folder = b.new + l.folder.slice(b.old.length); return {ok: true}; });
  on('POST', '/api/folders/delete', (q, b) => { for (const l of DB.lists) if (l.folder === b.name || l.folder === b.folder) l.folder = ''; return {ok: true}; });
  on('POST', '/api/sections', (q, b) => { if (!String(b.name || '').trim()) bad('Name missing'); listById(b.list_id) || gone();
    const s = {id: nid('section'), list_id: +b.list_id, name: b.name.trim(), sort: b.sort ?? Math.max(0, ...DB.sections.filter(x => x.list_id === +b.list_id).map(x => x.sort)) + 1};
    DB.sections.push(s); return {...s, moved: [], skipped: []}; });
  on('PATCH', '/api/sections/(\\d+)', (q, b, id) => { const s = DB.sections.find(x => x.id === +id) || gone(); for (const k of ['name', 'sort', 'collapsed']) if (k in b) s[k] = b[k]; return {...s}; });
  on('DELETE', '/api/sections/(\\d+)', (q, b, id) => { DB.sections = DB.sections.filter(x => x.id !== +id); for (const t of DB.tasks) if (t.section_id === +id) t.section_id = null; return {ok: true}; });
  on('POST', '/api/lists/(\\d+)/sections/order', (q, b) => { (b.ids || []).forEach((id, i) => { const s = DB.sections.find(x => x.id === id); if (s) s.sort = i + 1; }); return {ok: true}; });
  on('POST', '/api/lists/(\\d+)/fields', (q, b, id) => { const f = {id: nid('field'), list_id: +id, name: b.name, type: b.type || 'text', options: b.options || {}, pinned: b.pinned ? 1 : 0, sort: DB.fields.length + 1}; DB.fields.push(f); return clone(f); });
  on('PATCH', '/api/fields/(\\d+)', (q, b, id) => { const f = DB.fields.find(x => x.id === +id) || gone(); for (const k of ['name', 'options', 'pinned', 'sort', 'type']) if (k in b) f[k] = b[k]; return clone(f); });
  on('DELETE', '/api/fields/(\\d+)', (q, b, id) => { DB.fields = DB.fields.filter(x => x.id !== +id); return {ok: true}; });
  on('GET', '/api/lists/(\\d+)/overview', (q, b, id) => {
    const l = listById(id) || gone(), sec = DB.time.filter(e => e.list_id === l.id).reduce((a, e) => a + secsOf(e), 0);
    return {can_edit: true, description: l.description || '', files: [], links: [], list_id: l.id, members: [{name: DB.me.display_name, role: 'owner', user_id: 1}, ...(l.members || []).map(m => ({name: agentName(), role: m.role, user_id: m.user_id}))],
      milestones: clone(l.milestones || []), name: l.name, role: 'owner',
      status: {at: l.status_at, current: l.status, note: l.status_note, history: DB.status.filter(s => s.list_id === l.id).map(s => ({...s, name: DB.me.display_name})).reverse()},
      task_files: [], time: {budget_h: null, day_hours: 8, seconds: sec}};
  });
  on('PATCH', '/api/lists/(\\d+)/overview', (q, b, id) => { const l = listById(id) || gone(); if ('description' in b) l.description = String(b.description || ''); return {ok: true}; });
  on('POST', '/api/lists/(\\d+)/milestones', (q, b, id) => { const l = listById(id) || gone(); if (!String(b.name || '').trim()) bad('Name missing');
    const m = {id: nid('ms'), name: b.name.trim(), day: b.day, done: b.done ? 1 : 0}; l.milestones = [...(l.milestones || []), m]; return m; });
  on('PATCH', '/api/lists/(\\d+)/milestones/(\\d+)', (q, b, id, mid) => { const l = listById(id) || gone(), m = (l.milestones || []).find(x => x.id === +mid) || gone();
    for (const k of ['name', 'day']) if (k in b) m[k] = b[k]; if ('done' in b) m.done = b.done ? 1 : 0; return {...m}; });
  on('DELETE', '/api/lists/(\\d+)/milestones/(\\d+)', (q, b, id, mid) => { const l = listById(id) || gone(); l.milestones = (l.milestones || []).filter(x => x.id !== +mid); return {ok: true}; });
  // 2.17.0 (#442): notes per list, in memory like the rest of the demo
  const NT = () => DB.notes || (DB.notes = []);
  const noteOut = n => ({...n, tags: [...n.tags], created_name: DB.me.display_name, updated_name: DB.me.display_name});
  on('GET', '/api/lists/(\\d+)/notes', (q, b, id) => { listById(id) || gone(); return {notes: NT().filter(n => n.list_id === +id).sort((x, y) => (y.pinned - x.pinned) || y.updated_at.localeCompare(x.updated_at)).map(noteOut), may_write: true}; });
  on('POST', '/api/lists/(\\d+)/notes', (q, b, id) => { listById(id) || gone(); const t = iso();
    const n = {id: nid('note'), list_id: +id, title: String(b.title || '').trim(), body: String(b.body || ''), tags: (b.tags || []).map(String), pinned: !!b.pinned, created_by: 1, updated_by: 1, created_at: t, updated_at: t};
    NT().push(n); return noteOut(n); });
  on('GET', '/api/notes/(\\d+)', (q, b, nid_) => noteOut(NT().find(n => n.id === +nid_) || gone()));
  on('PATCH', '/api/notes/(\\d+)', (q, b, nid_) => { const n = NT().find(x => x.id === +nid_) || gone();
    for (const k of ['title', 'body']) if (k in b) n[k] = String(b[k] ?? ''); if ('tags' in b) n.tags = (b.tags || []).map(String); if ('pinned' in b) n.pinned = !!b.pinned;
    if ('list_id' in b) { listById(b.list_id) || gone(); n.list_id = +b.list_id; } n.updated_at = iso(); return noteOut(n); });
  on('DELETE', '/api/notes/(\\d+)', (q, b, nid_) => { DB.notes = NT().filter(n => n.id !== +nid_); return {ok: true}; });
  on('GET', '/api/notes', q => { const s = String(q.get?.('q') || q.q || '').toLowerCase(); return {notes: NT().filter(n => !s || (n.title + ' ' + n.body).toLowerCase().includes(s)).map(noteOut)}; });
  on('GET', '/api/lists/(\\d+)/status', (q, b, id) => ({items: DB.status.filter(s => s.list_id === +id).map(s => ({...s, name: DB.me.display_name})).reverse()}));
  on('POST', '/api/lists/(\\d+)/status', (q, b, id) => { const l = listById(id) || gone(); l.status = b.status || ''; l.status_note = b.note || ''; l.status_at = iso(); l.status_by = 1;
    DB.status.push({id: nid('status'), list_id: l.id, user_id: 1, status: l.status, note: l.status_note, created_at: iso()}); return {ok: true}; });
  // time tracking
  on('GET', '/api/time/entries', q => { const tid = q.get('task_id') ? +q.get('task_id') : null; const es = DB.time.filter(e => !tid || e.task_id === tid).map(entryOut);
    const s = es.reduce((a, e) => a + e.seconds, 0); return {entries: es.reverse(), mine: s, seconds: s}; });
  on('GET', '/api/time/report', q => timeReport(q));
  const stopTimer = () => { const e = DB.time.find(x => x.id === DB.timer); DB.timer = null; if (!e) return null;
    e.end = iso(); e.seconds = Math.max(0, Math.round((Date.parse(e.end) - Date.parse(e.start)) / 1000)); if (e.seconds < 60) { DB.time = DB.time.filter(x => x !== e); return null; } return entryOut(e); };
  on('POST', '/api/time/start', (q, b) => { const st = DB.timer ? stopTimer() : null; const t = b.task_id ? needTask(b.task_id) : null;
    const e = {id: nid('time'), user_id: 1, task_id: t ? t.id : null, list_id: t ? t.list_id : (b.list_id || null), start: iso(), end: null, seconds: 0, note: b.note || '', source: 'timer', created_at: iso(), updated_at: iso()};
    DB.time.push(e); DB.timer = e.id; return {entry: entryOut(e), stopped: st, timer: entryOut(e)}; });
  on('POST', '/api/time/stop', () => { if (!DB.timer) return {already: true, entry: null, timer: null}; const e = stopTimer(); return e ? {entry: e, timer: null} : {discarded: true, entry: null, timer: null}; });
  on('POST', '/api/time/entries', (q, b) => { const t = b.task_id ? needTask(b.task_id) : null;
    const st = b.start, en = b.end || (b.seconds ? new Date(Date.parse(b.start) + b.seconds * 1000).toISOString() : null); if (!st || !en) bad('Start and end missing');
    const e = {id: nid('time'), user_id: 1, task_id: t ? t.id : null, list_id: t ? t.list_id : (b.list_id || null), start: st, end: en, seconds: Math.round((Date.parse(en) - Date.parse(st)) / 1000), note: b.note || '', source: 'manual', created_at: iso(), updated_at: iso()};
    DB.time.push(e); return entryOut(e); });
  on('PATCH', '/api/time/entries/(\\d+)', (q, b, id) => { const e = DB.time.find(x => x.id === +id) || gone(); for (const k of ['start', 'end', 'note', 'task_id']) if (k in b) e[k] = b[k];
    if (e.task_id) e.list_id = taskById(e.task_id)?.list_id ?? e.list_id; if (e.end) e.seconds = Math.round((Date.parse(e.end) - Date.parse(e.start)) / 1000); return entryOut(e); });
  on('DELETE', '/api/time/entries/(\\d+)', (q, b, id) => { if (DB.timer === +id) DB.timer = null; DB.time = DB.time.filter(x => x.id !== +id); return {ok: true}; });
  // habits, filters, day plan
  on('POST', '/api/habits', (q, b) => { if (!String(b.name || '').trim()) bad('Name missing');
    const h = {id: nid('habit'), name: b.name.trim(), color: b.color || '', goal: b.goal || 1, days: b.days || '1234567', remind_at: b.remind_at || '', per_week: b.per_week || 0,
      sort: DB.habits.length + 1, archived: 0, created_at: iso(), user_id: 1, logs: {}, notes: {}}; DB.habits.push(h); return {id: h.id}; });
  on('PATCH', '/api/habits/(\\d+)', (q, b, id) => { const h = DB.habits.find(x => x.id === +id) || gone(); for (const k of ['name', 'color', 'goal', 'days', 'remind_at', 'per_week', 'sort', 'archived']) if (k in b) h[k] = b[k]; return {ok: true}; });
  on('DELETE', '/api/habits/(\\d+)', (q, b, id) => { DB.habits = DB.habits.filter(x => x.id !== +id); return {ok: true}; });
  on('POST', '/api/habits/(\\d+)/log', (q, b, id) => { const h = DB.habits.find(x => x.id === +id) || gone(), d = b.day || today();
    if ('count' in b) { if (+b.count) h.logs[d] = +b.count; else delete h.logs[d]; } if ('note' in b) { if (b.note) h.notes[d] = b.note; else delete h.notes[d]; } return {ok: true}; });
  on('POST', '/api/filters', (q, b) => { const f = {id: nid('filter'), user_id: 1, name: b.name || '', rules: b.rules || {}, sort: DB.filters.length + 1, icon: b.icon || '', color: b.color || ''}; DB.filters.push(f); return clone(f); });
  on('PATCH', '/api/filters/(\\d+)', (q, b, id) => { const f = DB.filters.find(x => x.id === +id) || gone(); Object.assign(f, b); return clone(f); });
  on('DELETE', '/api/filters/(\\d+)', (q, b, id) => { DB.filters = DB.filters.filter(x => x.id !== +id); return {ok: true}; });
  on('GET', '/api/stats', q => {
    const ws = +(q.get('ws') ?? 1), t0 = new Date(); t0.setHours(12, 0, 0, 0);
    const w0 = new Date(t0); w0.setDate(w0.getDate() - ((w0.getDay() - ws + 7) % 7));
    const weeks = Array.from({length: 12}, (_, i) => { const d = new Date(w0); d.setDate(d.getDate() - 7 * (11 - i)); return ds(d); });
    const wi = dd => { for (let i = 11; i >= 0; i--) if (dd >= weeks[i]) return i; return -1; };
    const done = live().filter(t => t.status === 2 && t.completed_at), perDay = {}, perWeek = Array(12).fill(0), byL = {};
    for (const t of done) { const dd = ds(new Date(t.completed_at)); perDay[dd] = (perDay[dd] || 0) + 1; const i = wi(dd); if (i >= 0) perWeek[i]++;
      const l = listById(t.list_id); if (l) (byL[l.id] = byL[l.id] || {color: l.color, id: l.id, is_inbox: !!l.is_inbox, n: 0, name: l.name}).n++; }
    const tw = Array(12).fill(0), tl = {};
    for (const e of DB.time) { const m = Math.round(secsOf(e) / 60), i = wi(ds(new Date(e.start))); if (i >= 0) tw[i] += m; const l = listById(e.list_id);
      if (l) (tl[l.id] = tl[l.id] || {color: l.color, id: l.id, is_inbox: !!l.is_inbox, minutes: 0, name: l.name}).minutes += m; }
    const wd = done.filter(t => t.due), ot = wd.filter(t => ds(new Date(t.completed_at)) <= t.due).length;
    let cur = 0; for (let d = new Date(t0); perDay[ds(d)]; d.setDate(d.getDate() - 1)) cur++;
    return {done: {by_list: Object.values(byL), per_day: perDay, per_week: perWeek, this_week: perWeek[11], today: perDay[today()] || 0, total: done.length},
      focus: {by_list: [], per_day: {}, per_week: Array(12).fill(0), this_week: 0, total: 0}, ontime: {ontime: ot, rate: wd.length ? Math.round(100 * ot / wd.length) : 0, with_due: wd.length},
      overdue: weeks.map(d => ({date: d, n: 0})), streak: {best: Math.max(cur, 1), current: cur},
      time: {by_list: Object.values(tl), per_week: tw, this_week: tw[11], total: tw.reduce((a, b) => a + b, 0)}, today: today(), weeks};
  });
  on('GET', '/api/dayplan', q => dayplan(q));
  on('GET', '/api/dayplan/review', () => { const t0 = today();
    return {date: t0, done: live().filter(t => t.completed_at && ds(new Date(t.completed_at)) === t0).map(t => ({task_id: t.id, title: t.title})), moved: [],
      open: live().filter(t => t.status === 0 && t.due && t.due <= t0).map(t => ({due: t.due, overdue: t.due < t0, task_id: t.id, title: t.title})),
      tomorrow: {date: addDays(t0, 1), plan: [], events: 0, count: 0}}; });  // 2.80.1: the review card needs tomorrow (CI after 17:00)
  // the simulated agent
  on('GET', '/api/agents', () => ({agents: [agentOut()]}));
  on('GET', '/api/agents/jobs', q => ({jobs: DB.jobs.filter(j => q.get('state') !== 'open' || ['running', 'waiting'].includes(j.state)).map(jobOut).reverse()}));
  on('POST', '/api/agents/jobs/(\\d+)/action', (q, b, id) => { const j = DB.jobs.find(x => x.id === +id) || gone(); if (['done', 'failed', 'stopped'].includes(j.state)) bad('Already finished'); jobAction(j, b.action); return {ok: true, job: jobOut(j)}; });
  on('GET', '/api/agents/(\\d+)/chat', () => { for (const m of DB.chat) m.read = 1; return {agent: agentOut(), messages: DB.chat.map(m => ({...m})), now: new Date().toISOString()}; });
  on('POST', '/api/agents/(\\d+)/chat', (q, b) => {
    const m = {id: nid('chat'), agent_id: AGENT, user_id: 1, from: 'user', body: String(b.body || ''), task_id: b.task_id || null, created_at: iso(), delivered_at: iso(), reactions: [], read: 1};
    DB.chat.push(m);
    setTimeout(() => { DB.chat.push({id: nid('chat'), agent_id: AGENT, user_id: 1, from: 'agent', body: T().agentChatReply, task_id: null, created_at: iso(), delivered_at: null, reactions: [], read: 0}); bump(); }, 1200);
    return {...m};
  });
  on('PUT', '/api/agents/(\\d+)/autoshare', () => ({ok: true}));
  // 2.19.0 (#653): the module Family (one person: no kids, no taking turns); the texts come from the app's translations (tr)
  const tx = k => (typeof tr === 'function' ? tr(k) : k);
  const SHOP_AREAS = ['Fruit & vegetables', 'Bread & bakery', 'Dairy & eggs', 'Meat & fish', 'Frozen', 'Pantry', 'Drinks', 'Household & drugstore'];
  function shopAreas(l) {
    const have = new Set(DB.sections.filter(x => x.list_id === l.id).map(x => x.name.toLowerCase())); let n = 0;
    for (const a of SHOP_AREAS) { if (have.has(tx(a).toLowerCase())) continue; DB.sections.push({id: nid('section'), list_id: l.id, name: tx(a), sort: DB.sections.length + 1}); n++; }
    return n;
  }
  const famList = (kind, name) => DB.lists.find(l => l.family === kind && !l.archived) || (() => { const l = {...clone(LIST_DEF), id: nid('list'), created_at: iso(), sort: Math.max(0, ...DB.lists.map(x => x.sort)) + 1, name: tx(name), family: kind, checklist: kind === 'shopping' || kind === 'packing' ? 1 : 0}; DB.lists.push(l); if (kind === 'shopping') shopAreas(l); return l; })();
  const nextYearly = (m, d) => { const t0 = today(); for (const y of [0, 1]) { const x = `${new Date().getFullYear() + y}-${pad(m)}-${pad(d)}`; if (x >= t0) return x; } return `${new Date().getFullYear() + 1}-${pad(m)}-${pad(d)}`; };
  on('POST', '/api/family/occasions', (q, b) => {
    const name = String(b.name || '').trim(); if (!name) bad('Name missing');
    const m = String(b.date || '').match(/^(\d{4}|--)-?(\d{2})-?(\d{2})/); if (!m) bad('Invalid date');
    const year = b.year || (/^\d{4}$/.test(m[1]) ? +m[1] : null), kind = b.kind === 'anniversary' ? 'anniversary' : 'birthday', lead = b.lead_days ?? 7;
    const l = b.list_id ? listById(b.list_id) || gone() : famList('birthdays', 'Birthdays');
    const t = newTask({title: tx(kind === 'birthday' ? 'Birthday: {0}' : 'Anniversary: {0}').replace('{0}', name), list_id: l.id, due: nextYearly(+m[2], +m[3]), repeat: 'FREQ=YEARLY',
      reminders: [lead ? lead * 1440 : null, 0].filter(x => x !== null).join(','), fam: {kind, name, lead, ...(year ? {year} : {})}});
    for (const g of b.gifts || []) newTask({title: g, parent_id: t.id});
    return taskOut(taskById(t.id));
  });
  const DL = {passport: ['Renew the passport: {0}', 90, '', 0, 'Passport'], id_card: ['Renew the ID card: {0}', 60, '', 0, 'ID card'], car: ['Car inspection: {0}', 30, 'FREQ=YEARLY;INTERVAL=2', 0, 'Car inspection'],
    insurance: ['Cancel or renew the insurance: {0}', 21, 'FREQ=YEARLY', 3, 'Insurance'], contract: ['Cancel or renew the contract: {0}', 14, 'FREQ=YEARLY', 1, 'Contract'], other: ['{0}', 14, '', 0, 'Other deadline']};
  on('POST', '/api/family/deadlines', (q, b) => {
    const d = DL[b.type || 'other'] || bad('Invalid type'); if (!b.expires) bad('Date missing');
    const notice = b.notice_months ?? d[3], due = new Date(b.expires + 'T12:00:00'); due.setMonth(due.getMonth() - notice);
    const l = b.list_id ? listById(b.list_id) || gone() : famList('household', 'Household');
    const who = String(b.who || '').trim(), title = d[0] === '{0}' ? (who || bad('Name missing')) : tx(d[0]).replace('{0}', who || tx(d[4]));
    return newTask({title, list_id: l.id, due: ds(due), repeat: d[2], deadline: 2, priority: 3, reminders: `${d[1] * 1440},0`,
      fam: {kind: 'deadline', type: b.type || 'other', who, expires: b.expires, notice, lead: d[1]}});
  });
  const PACK = {holiday: ['Holiday', ['Passports or ID cards', 'Tickets and bookings', 'Health insurance cards', 'Cash and cards', 'Underwear and socks', 'T-shirts', 'Trousers', 'Jumper', 'Rain jacket', 'Pyjamas', 'Swimwear', 'Toothbrush and toothpaste', 'Sun cream', 'Medicines', 'Phone chargers', 'Power bank']],
    pool: ['Swimming pool', ['Swimwear', 'Towels', 'Shower gel and shampoo', 'Flip-flops', 'Swimming goggles', 'Sun cream', 'Water bottle', 'Snacks', 'Coin for the locker', 'Hairbrush']],
    daycare: ['Daycare', ['Change of clothes', 'Nappies and wipes', 'Indoor shoes', 'Rain gear', 'Sun hat', 'Water bottle', 'Lunch box', 'Cuddly toy', 'Sun cream']],
    camping: ['Camping', ['Tent', 'Sleeping bags', 'Sleeping mats', 'Pillows', 'Camping stove and gas', 'Lighter', 'Pots and cutlery', 'Torch or head torch', 'First aid kit', 'Insect repellent']],
    business: ['Business trip', ['Laptop and charger', 'Phone chargers', 'Business clothes', 'Documents for the meeting', 'Tickets and bookings', 'Toiletries', 'Headphones']]};
  on('POST', '/api/family/packing', (q, b) => {
    const p = PACK[b.template] || bad('Invalid template');
    const l = {...clone(LIST_DEF), id: nid('list'), created_at: iso(), sort: Math.max(0, ...DB.lists.map(x => x.sort)) + 1, name: b.name || tx('Packing list: {0}').replace('{0}', tx(p[0])), family: 'packing', checklist: 1};
    DB.lists.push(l); p[1].forEach((it, i) => newTask({title: tx(it), list_id: l.id, sort: i + 1}));
    return {ok: true, list_id: l.id};
  });
  const shopKey = s => String(s).replace(/^\s*[\d½¼¾.,/]+\s*(x|kg|g|l|ml|stk|pck|el|tl)?\.?\s+/i, '').trim().toLowerCase();
  on('POST', '/api/tasks/(\\d+)/to-shopping', (q, b, id) => {
    const t = needTask(id), lines = String(t.content || '').split('\n');
    let items = lines.map(x => x.match(/^\s*(?:[-*+]|\d+[.)])\s+(?:\[( |x|X)\]\s*)?(.*\S)/)).filter(x => x && !/x/i.test(x[1] || '')).map(x => x[2]);
    if (!items.length) items = lines.map(x => x.trim()).filter(x => x && !x.startsWith('#'));
    if (!items.length) bad(tx('No ingredients found: write them as a list in the notes'));
    const l = b.list_id ? listById(b.list_id) || gone() : famList('shopping', 'Shopping list');
    const have = new Set(live().filter(x => x.list_id === l.id && x.status === 0).map(x => shopKey(x.title))), added = [], skipped = [];
    for (const it of items) { if (have.has(shopKey(it))) { skipped.push(it); continue; } have.add(shopKey(it)); const n = newTask({title: it, list_id: l.id, sort: 1e6 + added.length}); added.push({id: n.id, title: it}); }
    return {list_id: l.id, added, skipped};
  });
  on('POST', '/api/lists/(\\d+)/shop-areas', (q, b, id) => { const l = listById(id) || gone(); l.family = 'shopping'; return {ok: true, added: shopAreas(l)}; });
  on('GET', '/api/family/kids', () => ({kids: []}));
  // 2.74.0 (#1653): "What do you use Kalmido for?" like kalmido/family/family.py purpose_apply (+ office, all_modules); the
  // modules that need a server (files, documents, contacts, events, life areas ...) stay off in the demo
  const LIFE = ['contracts', 'home', 'care', 'health', 'review', 'travel', 'reading'];
  const PURPOSE_MODS = ['cal', 'timeline', 'matrix', 'kanban', 'habits', 'pomo', 'stats', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'family', 'events', 'contacts', ...LIFE];
  const TEAM = ['cal', 'timeline', 'kanban', 'comments', 'collab', 'time', 'progress', 'deps', 'fields', 'events', 'contacts'];
  const PURPOSE = {me: ['cal', 'events', 'contacts'], home: ['cal', 'events', 'contacts', 'habits', ...LIFE],
    family: ['cal', 'habits', 'comments', 'collab', 'family', 'events', 'contacts', 'contracts', 'home', 'travel'], team: TEAM, software: TEAM, office: TEAM};
  const PURPOSE_EXTRA = {office: ['clients', 'workload', 'forms', 'office']};
  // 2.125.0 D (#1653): every module runs in the demo now; PM_FULL = kalmido/family/family.py PM_FULL
  const DEMO_OFF = new Set();
  const PM_FULL = ['cal', 'timeline', 'matrix', 'habits', 'pomo', 'kanban', 'collab', 'stats', 'time', 'progress', 'deps', 'fields', 'agents', 'comments',
    'family', 'events', 'contacts', ...LIFE, 'budget', 'feeds', 'clients', 'workload', 'forms', 'office', 'wiki', 'files', 'dispo', 'sheets'];
  on('POST', '/api/me/purpose', (q, b) => {
    const p = b.purpose, am = b.all_modules; if (!PURPOSE[p]) bad('Invalid purpose');
    const extra = PURPOSE_EXTRA[p] || [], onS = new Set(am == null ? [...PURPOSE[p], ...extra] : am ? PM_FULL : []);  // 2.125.0 D (#1653): all = PM_FULL like the server
    const sw = [...PURPOSE_MODS, ...(am === false ? PM_FULL : [])];
    let fs = DB.settings.features.split(',').filter(Boolean);
    fs = [...fs.filter(x => !sw.includes(x) || onS.has(x)), ...PURPOSE_MODS.filter(x => onS.has(x) && !fs.includes(x))];
    fs = [...fs, ...extra.filter(x => onS.has(x) && !fs.includes(x))];
    fs = [...fs, ...PM_FULL.filter(x => onS.has(x) && !fs.includes(x))].filter(x => !DEMO_OFF.has(x));
    if (am != null) DB.settings.mods_all = am ? '1' : '0';
    DB.settings.features = fs.join(','); DB.settings.purpose = p;
    const created = [];
    if (p === 'family') { for (const [k, n] of [['shopping', 'Shopping list'], ['household', 'Household']]) if (!DB.lists.some(l => l.family === k)) created.push(famList(k, n).id); }
    else if (b.examples === true && ['team', 'office', 'software'].includes(p) && !sampleState()) created.push(sampleMake());
    return {features: DB.settings.features, created};
  });

  // 2.125.0 D (#1653): "Start" of the intro (static/js/account.js setupChoices) like kalmido/core/instance.py admin_setup: the
  // language, the two switches for everybody, the modules (USER_DEFAULTS features + family, the life areas only when picked),
  // the purpose with its extras ("all modules" = PM_FULL), the start (empty, sample project, a project of a type)
  const SETUP_FEATS = ['cal', 'timeline', 'matrix', 'habits', 'pomo', 'kanban', 'collab', 'stats', 'time', 'progress', 'deps', 'fields', 'comments', 'events', 'contacts', 'files', 'docs', 'family'];
  on('POST', '/api/admin/setup', (q, b) => {
    const mods = b.modules; if (!Array.isArray(mods)) bad(tx('Invalid value: {0}').replace('{0}', 'modules'));
    if (b.lang && LANGS.includes(b.lang)) DB.settings.lang = b.lang;
    DB.inst = {...DB.inst, ...(typeof b.collab_all === 'boolean' ? {collab_all: b.collab_all} : {}), ...(typeof b.time_all === 'boolean' ? {time_all: b.time_all} : {})};
    let fs = SETUP_FEATS.filter(f => f === 'collab' || f === 'time' || mods.includes(f));
    fs = [...fs, ...LIFE.filter(m => mods.includes(m) && !fs.includes(m))];
    if (b.purpose && PURPOSE[b.purpose]) {
      DB.settings.purpose = b.purpose;
      let on = PURPOSE[b.purpose].filter(m => LIFE.includes(m) && !fs.includes(m));
      on = [...on, ...(PURPOSE_EXTRA[b.purpose] || []).filter(m => !on.includes(m) && !fs.includes(m))];
      if (typeof b.all_modules === 'boolean') { on = b.all_modules ? PM_FULL.filter(m => !fs.includes(m)) : []; DB.settings.mods_all = b.all_modules ? '1' : '0'; }
      fs = [...fs, ...on];
      if (b.purpose === 'family') for (const [k, n] of [['shopping', 'Shopping list'], ['household', 'Household']]) if (!DB.lists.some(l => l.family === k)) famList(k, n);
    }
    DB.settings.features = fs.filter(x => !DEMO_OFF.has(x)).join(',');
    if (b.project_type) { const n = {agency: 'Agency', software: 'Software / AI dev', private: 'Personal|project type'}[b.project_type] || 'Project';
      DB.lists.push({...clone(LIST_DEF), id: nid('list'), created_at: iso(), name: tx(n), kind: 'project', ptype: b.project_type, sort: Math.max(0, ...DB.lists.map(x => x.sort)) + 1}); }
    if (b.sample === true && !sampleState()) sampleMake(); else if ('sample' in b) DB.settings.sample_ask = '0';
    DB.settings.setup = 'done';
    return {ok: true};
  });

  // ---------------------------------------------------------------- demo-office (2.74.0, #1653)
  // Office & finance of a person without an organisation (the personal office, the person is its admin): clients,
  // services, quotations, invoices, payments. Sums and VAT like kalmido/office/calc.py (office_calc / inv_calc): every
  // position money(qty x rate), the tax per rate on the sum of that rate, half up to cents (BigInt cents here). Numbers
  // KVA-/RE-/GS-{yyyy}-{seq:03} like the German country pack. The PDF of the server becomes a print view (printView).
  // Everything else of the office (DATEV, e-invoice XML, mail, agents, imports, cash flow, KPI, travel ...) is gated.
  const OF = () => DB.office || (DB.office = {settings: {}, company: {}, services: [], docs: [], counters: {}});
  const CL = () => DB.clients || (DB.clients = []);
  const TAX = {standard: 19, reduced: 7, exempt: 0};
  const SCHEME = {offer: 'KVA', invoice: 'RE', credit: 'GS', reminder: 'MA'};
  const OF_DEF = {currency: 'EUR', lang: 'de', fx_usd: 1.09, offer_scheme: 'KVA-{yyyy}-{seq:03}', invoice_scheme: 'RE-{yyyy}-{seq:03}', credit_scheme: 'GS-{yyyy}-{seq:03}',
    reminder_scheme: 'MA-{yyyy}-{seq:03}', offer_number_at: 'create', offer_valid_days: 30, payment_days: 14, reminder_fee: 0, reminder_deadline_days: 10, small_business: 0,
    producing_on: 0, raw_on: 0, prod_quotient: 3, raw_factor: 0.25, producing_rate: 600, producing_service_id: null, logo: '', color: '', einvoice_format: 'zugferd',
    datev_email: '', datev_auto: 0, intro_text_id: {de: null, en: null}, closing_text_id: {de: null, en: null}, rights_default: {time_id: null, territory_id: null, media_id: null},
    industry_packs: [], invoice_closing_de: '', invoice_closing_en: '', reminder_text_de: '', reminder_text_en: '', agents_read: 0, datev_extf: 0, parts_invoice_mode: ''};
  const CO_KEYS = ['name', 'street', 'zip', 'city', 'country', 'email', 'phone', 'tax_number', 'vat_id', 'iban', 'bic', 'bank_name', 'register_court', 'register_no', 'managing_directors', 'md_label'];
  // an example sender, so a quotation can be finalised right away (Settings of the office: change it)
  const coDefault = () => ({name: T().coName || 'Demo Studio', street: 'Musterstraße 1', zip: '10115', city: 'Berlin', country: 'DE', email: 'office@example.com', phone: '',
    tax_number: '12/345/67890', vat_id: '', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Demo Bank', register_court: '', register_no: '', managing_directors: '', md_label: ''});
  const ofSettings = () => { const o = OF(); if (!o.company.name) o.company = coDefault(); const co = o.company;
    return {...OF_DEF, ...o.settings, company: {name: co.name, lines: [co.street, [co.zip, co.city].filter(Boolean).join(' ')].filter(Boolean), contact_lines: [co.email, co.phone].filter(Boolean),
      register_lines: [co.tax_number ? 'St.-Nr. ' + co.tax_number : '', co.vat_id ? 'USt-IdNr. ' + co.vat_id : ''].filter(Boolean), bank_lines: [co.bank_name, co.iban ? 'IBAN ' + co.iban : '', co.bic ? 'BIC ' + co.bic : ''].filter(Boolean), ...(o.settings.company || {})}}; };
  // money in cents (BigInt), half up like Decimal ROUND_HALF_UP
  const C = v => BigInt(Math.round((+v || 0) * 100));
  const divR = (a, b) => { const neg = (a < 0n) !== (b < 0n), x = a < 0n ? -a : a, y = b < 0n ? -b : b, q = (2n * x + y) / (2n * y); return neg ? -q : q; };
  const mulQ = (qty, cents) => divR(BigInt(Math.round((+qty || 0) * 10000)) * cents, 10000n);  // money(qty x rate)
  const pctOf = (cents, pct) => divR(cents * BigInt(Math.round(pct * 100)), 10000n);
  const cs = c => { const n = c < 0n ? -c : c, s = (c < 0n ? '-' : '') + (n / 100n) + '.' + String(n % 100n).padStart(2, '0'); return s; };  // "1428.00"
  const cn = c => Number(cs(c));
  const fmtM = (c, lang, cur) => { const en = lang === 'en', neg = c < 0n, [w, f] = cs(neg ? -c : c).split('.'), g = w.replace(/\B(?=(\d{3})+(?!\d))/g, en ? ',' : '.'), sym = cur === 'USD' ? '$' : '€';
    return en ? `${neg ? '-' : ''}${sym}${g}.${f}` : `${neg ? '-' : ''}${g},${f} ${sym}`; };
  const fmtQ = (q, lang) => { const s = String(+(+q || 0).toFixed(4)); return lang === 'en' ? s : s.replace('.', ','); };
  const LBL = {de: {net: 'Summe Netto', gross: 'Gesamt Brutto', discount: 'Rabatt', producing: 'Producing', net_incl_raw: 'Summe netto mit Option Rohdaten', net_excl_raw: 'ohne Rohdaten',
    tax: p => `MwSt. ${p} %`, exempt: 'steuerfrei', vat_note: 'Alle Preise zuzüglich 7 % bzw. 19 % MwSt.', novat_note: 'Nicht im Inland steuerbar / Reverse-Charge-Verfahren.',
    units: {day: 'Tage', hour: 'Std.', piece: 'Stk.', minute: 'Min.', flat: 'pauschal'}, producing_detail: (d, q, k) => `${d} Tage = ${q} Produktionstage / ${k}, auf halbe Tage gerundet`,
    raw_optional: 'Optional: Bereitstellung der Rohdaten', raw_included: 'Bereitstellung der Rohdaten', raw_detail: p => `${p} % der Positionen mit Rohdaten`, discount_detail: p => `${p} % auf die markierten Positionen`},
  en: {net: 'Net Total', gross: 'Gross Total', discount: 'Discount', producing: 'Producing', net_incl_raw: 'Net total with option raw data', net_excl_raw: 'excluding raw data',
    tax: p => `VAT ${p} %`, exempt: 'tax exempt', vat_note: 'All prices plus 7 % or 19 % VAT.', novat_note: 'Not taxable domestically / reverse charge.',
    units: {day: 'days', hour: 'h', piece: 'pcs', minute: 'min', flat: 'flat'}, producing_detail: (d, q, k) => `${d} days = ${q} production days / ${k}, rounded to half days`,
    raw_optional: 'Optional: Delivery of raw data', raw_included: 'Delivery of raw data', raw_detail: p => `${p} % of the positions with raw data`, discount_detail: p => `${p} % on the marked positions`}};
  const flag = v => ![null, undefined, 0, '0', '', false, 'false', 'off'].includes(v);
  // the calculator of quotations (office_calc) and of invoices / credit notes (inv_calc)
  function ofCalc(d, inv) {
    const lang = d.lang === 'en' ? 'en' : 'de', L = LBL[lang], cur = d.currency === 'USD' ? 'USD' : 'EUR', fx = cur === 'USD' ? (+d.fx_rate || 1.09) : 1;
    const novat = d.vat_mode === 'novat', rates = Object.fromEntries(Object.entries(TAX).map(([k, v]) => [k, novat ? 0 : v]));
    const conv = r => C(cur === 'USD' ? +((+r || 0) * fx).toFixed(2) : r);
    const its = d.items || [];
    let ext = 0n; for (const it of its) if ((it.kind || 'service') === 'service' && it.unit !== 'percent' && it.intext === 'extern') ext += mulQ(it.qty ?? 1, conv(it.rate));
    const base = {standard: 0n, reduced: 0n, exempt: 0n}, disc = {standard: 0n, reduced: 0n, exempt: 0n}, lines = [];
    let pos = 0, net = 0n, raw = 0n, prodQ = 0, costs = 0n;
    for (const it of its) {
      const kind = it.kind || 'service';
      if (kind === 'heading') { lines.push({kind, title: it.title || ''}); continue; }
      if (kind === 'text') { lines.push({kind, text: it.detail || it.title || ''}); continue; }
      if (kind === 'discount' && !inv) continue;
      const pct = kind === 'service' && it.unit === 'percent' ? +it.rate || 0 : null, qty = pct == null ? (it.qty ?? 1) : 1;
      let total = pct == null ? mulQ(qty, conv(it.rate)) : pctOf(ext, pct);
      if (kind === 'discount') total = total < 0n ? total : -total;
      const tax = TAX[it.tax] != null ? it.tax : 'standard';
      pos++; net += total; base[tax] += total;
      if (!inv && flag(it.raw_fee)) raw += total;
      if (!inv && flag(it.producing) && pct == null) prodQ += +qty || 0;
      if (!inv && flag(it.discountable ?? 1)) disc[tax] += total;
      if (kind !== 'discount') costs += mulQ(qty, C(it.cost));
      const rate = pct == null ? conv(it.rate) : total, unit = it.unit || 'day';
      lines.push({kind: kind === 'discount' ? 'discount' : 'item', pos, id: it.id, service_id: it.service_id || null, title: it.title || (kind === 'discount' ? L.discount : ''), detail: it.detail || '',
        qty: +qty, qty_text: pct == null ? fmtQ(qty, lang) : fmtQ(pct, lang) + ' %', unit, unit_text: pct == null ? (L.units[unit] || unit) : '', ...(pct != null ? {pct, base: cn(ext)} : {}),
        rate: cn(rate), rate_text: fmtM(rate, lang, cur), tax, tax_pct: rates[tax], total: cn(total), total_text: fmtM(total, lang, cur), net: cs(total), intext: it.intext || 'intern'});
    }
    let prodTotal = 0n, rawAmt = 0n, discount = 0n;
    const rawMode = inv ? 'none' : (['optional', 'included', 'none'].includes(d.raw_mode) ? d.raw_mode : 'optional');
    if (!inv) {
      const quot = +(d.prod_quotient ?? 3) || 0, days = d.producing_on !== 0 && quot > 0 && prodQ > 0 ? Math.round((prodQ / quot / 5) * 10 + 1e-9) / 10 * 5 : 0;
      if (days > 0) { const pr = conv(d.producing_rate ?? 600); prodTotal = mulQ(days, pr); base.standard += prodTotal; net += prodTotal;
        lines.push({kind: 'producing', title: L.producing, qty: days, qty_text: fmtQ(days, lang), unit: 'day', unit_text: L.units.day, rate: cn(pr), tax: 'standard', tax_pct: rates.standard, total: cn(prodTotal), total_text: fmtM(prodTotal, lang, cur), detail: L.producing_detail(fmtQ(days, lang), fmtQ(prodQ, lang), fmtQ(quot, lang))}); }
      if (rawMode !== 'none') rawAmt = mulQ(+(d.raw_factor ?? 0.25), raw);
      if (rawMode !== 'none' && raw > 0n) { const incl = rawMode === 'included'; if (incl) { base.standard += rawAmt; net += rawAmt; }
        lines.push({kind: 'raw', optional: !incl, title: incl ? L.raw_included : L.raw_optional, qty: incl ? 1 : null, qty_text: incl ? '1' : '', unit: 'flat', unit_text: '', rate: cn(rawAmt), tax: 'standard', tax_pct: rates.standard, total: cn(rawAmt), total_text: fmtM(rawAmt, lang, cur), detail: L.raw_detail(fmtQ((+(d.raw_factor ?? 0.25)) * 100, lang))}); }
      const dp = +d.discount_pct || 0;
      if (dp > 0) { for (const k of Object.keys(base)) { const x = pctOf(disc[k], dp); base[k] -= x; discount += x; } net -= discount;
        if (discount > 0n) lines.push({kind: 'discount', title: L.discount, pct: dp, total: cn(-discount), total_text: fmtM(-discount, lang, cur), detail: L.discount_detail(fmtQ(dp, lang))}); }
    }
    const taxLines = []; let taxSum = 0n;
    if (!novat) for (const k of Object.keys(base)) { if (base[k] === 0n) continue; const amt = pctOf(base[k], rates[k]); taxSum += amt;
      taxLines.push({rate_key: k, pct: inv ? String(rates[k]) : rates[k], base: inv ? cs(base[k]) : cn(base[k]), amount: inv ? cs(amt) : cn(amt), base_text: fmtM(base[k], lang, cur), amount_text: fmtM(amt, lang, cur), label: k === 'exempt' ? L.exempt : L.tax(rates[k])}); }
    const gross = net + taxSum, N = inv ? cs : cn;
    const out = {lang, currency: cur, fx_rate: cur === 'USD' ? fx : null, fx_note: cur === 'USD' ? (lang === 'en' ? `Exchange rate €1: $${fmtQ(fx, lang)}` : `Wechselkurs 1 €: ${fmtQ(fx, lang)} $`) : '',
      vat_mode: novat ? 'novat' : 'vat', raw_mode: rawMode, net: N(net), net_text: fmtM(net, lang, cur), tax_lines: taxLines, tax: cs(taxSum), tax_total: N(taxSum), tax_text: fmtM(taxSum, lang, cur),
      gross: N(gross), gross_text: fmtM(gross, lang, cur), costs: N(costs), margin: N(net - costs), items_net: N(net - prodTotal - (rawMode === 'included' ? rawAmt : 0n) + discount),
      discount: N(discount), raw_amount: N(rawAmt), producing_total: N(prodTotal), lines,
      net_incl_raw: !inv && rawMode === 'optional' && raw > 0n ? cn(net + rawAmt) : null, net_excl_raw: !inv && rawMode === 'included' && raw > 0n ? cn(net - rawAmt) : null,
      vat_note: novat ? L.novat_note : inv ? '' : L.vat_note, labels: {net: L.net, gross: L.gross, discount: L.discount, producing: L.producing, net_incl_raw: L.net_incl_raw, net_excl_raw: L.net_excl_raw}};
    return out;
  }
  const isInv = d => d.kind !== 'offer';
  const OFD_STATE = {done: 'Settled', draft: 'Draft', issued: 'Finalised', sent: 'Sent', paid: 'Paid', partial: 'Partly paid', overdue: 'Overdue', cancelled: 'Cancelled', accepted: 'Accepted', declined: 'Declined'};
  const totalsOf = d => d.locked && d.frozen ? d.frozen : ofCalc(d, isInv(d));
  const paidC = d => (d.payments || []).reduce((a, p) => a + C(p.amount), 0n);
  function stateOf(d) {
    if (!isInv(d)) return d.status;
    if (['draft', 'paid', 'cancelled'].includes(d.status)) return d.status;
    if (d.kind === 'invoice' && paidC(d) > 0n) return 'partial';
    if (d.due_date && d.due_date < today()) return 'overdue';
    return d.status;
  }
  const docLine = d => { const t = totalsOf(d), st = stateOf(d), open = isInv(d) ? C(t.gross) - paidC(d) : 0n, o = open > 0n && d.status !== 'cancelled' ? open : 0n;
    return {id: d.id, kind: d.kind, number: d.number, status: d.status, state: st, status_text: tx(OFD_STATE[st] || st), date: d.date, due_date: d.due_date || null, valid_until: d.valid_until,
      recipient_name: d.recipient?.name || '', project_title: d.project_title, project_ref: d.project_ref, client_id: d.client_id, locked: !!d.locked,
      net: t.net, gross: t.gross, net_text: t.net_text, gross_text: t.gross_text, open: cs(o), open_text: fmtM(o, t.lang, t.currency), paid: cs(paidC(d)), credits: '0.00'}; };
  function docOut(d) {
    const t = totalsOf(d), ln = docLine(d), editable = !d.locked && d.status !== 'sent';
    const items = (d.items || []).map(it => ({...clone(it), margin: it.kind === 'service' || !it.kind ? cn(mulQ(it.qty ?? 1, C(it.rate)) - mulQ(it.qty ?? 1, C(it.cost))) : null}));
    const out = {...clone(d), frozen: undefined, totals: t, state: ln.state, status_text: ln.status_text, net_text: t.net_text, gross_text: t.gross_text,
      statuses: d.kind === 'offer' ? ['draft', 'sent', 'accepted', 'declined'] : d.kind === 'invoice' ? ['draft', 'issued', 'sent', 'paid', 'cancelled'] : ['draft', 'issued', 'sent', 'paid'],
      items, items_margin: items.reduce((a, it) => a + (it.margin || 0), 0), parts: [], parts_shoot: null, client_contacts: [], contract: null, locked: !!d.locked,
      locked_by_name: d.locked ? DB.me.display_name : '', can_edit: editable, can_delete: editable, number_at_finalize: isInv(d) && !d.number, agent_name: '', list_name: ''};
    delete out.frozen;
    if (isInv(d)) Object.assign(out, {paid: ln.paid, credits: '0.00', open: ln.open, open_text: ln.open_text, credits_of: [], fee_reminders: [], fee_open: '0.00',
      payments: (d.payments || []).map(p => ({...p, created_by_name: DB.me.display_name}))});
    return out;
  }
  const needDoc = id => OF().docs.find(x => x.id === +id) || gone();
  const conflict = msg => { throw new Http(409, {error: tx(msg)}); };
  function nextNumber(kind, date) {
    const y = String(date || today()).slice(0, 4), k = kind + ':' + y, o = OF(); o.counters[k] = (o.counters[k] || 0) + 1;
    return `${SCHEME[kind]}-${y}-${String(o.counters[k]).padStart(3, '0')}`;
  }
  const addDays = (d, n) => { const x = new Date(d + 'T12:00:00'); x.setDate(x.getDate() + n); return ds(x); };
  function newDoc(kind, extra = {}) {
    const s = ofSettings(), t0 = today();
    const d = {id: nid('ofdoc'), org_id: 1, kind, number: '', status: 'draft', lang: s.lang, currency: s.currency, fx_rate: s.fx_usd, vat_mode: s.small_business ? 'novat' : 'vat',
      vat_note: s.small_business ? 'small' : '', client_id: null, recipient: {name: '', lines: []}, project_title: '', project_ref: '', date: t0, valid_until: kind === 'offer' ? addDays(t0, +s.offer_valid_days || 30) : '',
      contract_id: null, raw_mode: s.raw_on ? 'optional' : 'none', raw_factor: s.raw_factor, prod_quotient: s.prod_quotient, producing_rate: s.producing_rate, producing_on: s.producing_on ? 1 : 0,
      discount_pct: 0, intro: '', closing: '', rights: {time: {id: null, text: ''}, territory: {id: null, text: ''}, media: {id: null, text: ''}, exceptions: '', exclusive: 0, note: ''}, fields: [],
      created_by: 1, created_at: iso(), updated_at: iso(), sent_at: null, locked_at: null, locked_by: null, service_from: '', service_to: '', order_ref: '', due_date: null,
      payment_days: kind === 'invoice' ? +s.payment_days || 14 : null, source_doc_id: null, paid_at: null, einvoice_format: s.einvoice_format, contact_id: null, items: [], payments: [], ...extra};
    if (kind === 'offer' && s.offer_number_at !== 'finalize') d.number = nextNumber('offer', d.date);
    OF().docs.push(d); return d;
  }
  // 2.97.0 B (#1951): the fixed address fields only (as the server)
  const recipientOf = cl => ({name: cl.name, lines: [cl.name, ...(cl.contacts || []).filter(k => k.is_default).map(k => k.name), cl.street || '', cl.address_extra || '', [cl.zip, cl.city].filter(Boolean).join(' ')].map(x => String(x || '').trim()).filter(Boolean).filter((x, i, a) => a.indexOf(x) === i)});
  const DOC_FIELDS = ['lang', 'currency', 'fx_rate', 'vat_mode', 'vat_note', 'project_title', 'project_ref', 'date', 'valid_until', 'contract_id', 'raw_mode', 'raw_factor', 'prod_quotient', 'producing_rate',
    'producing_on', 'discount_pct', 'intro', 'closing', 'rights', 'fields', 'service_from', 'service_to', 'order_ref', 'due_date', 'payment_days', 'einvoice_format', 'contact_id'];
  function patchDoc(d, b) {
    if (d.locked || d.status === 'sent') conflict('Sent documents cannot be changed; duplicate it for a new version.');
    for (const k of DOC_FIELDS) if (k in b) d[k] = b[k];
    if ('recipient' in b) d.recipient = {name: String(b.recipient?.name || ''), lines: (b.recipient?.lines || []).map(String)};
    if ('client_id' in b) { d.client_id = b.client_id ? +b.client_id : null; const cl = CL().find(c => c.id === d.client_id);
      if (cl) d.recipient = recipientOf(cl); if (cl && d.kind === 'invoice' && cl.payment_terms_days != null) d.payment_days = +cl.payment_terms_days; }
    d.updated_at = iso();
  }
  const svcRate = (s, unit) => unit === 'hour' ? s.hourly_rate : s.daily_rate ?? s.hourly_rate;
  function putItems(d, items) {
    if (d.locked || d.status === 'sent') conflict('Sent documents cannot be changed; duplicate it for a new version.');
    d.items = (items || []).map(it => {
      const s = it.service_id ? OF().services.find(x => x.id === +it.service_id) : null, kind = ['service', 'text', 'heading', 'discount'].includes(it.kind) ? it.kind : 'service';
      const unit = it.unit || s?.unit || 'day';
      return {id: it.id || nid('ofitem'), kind, service_id: s ? s.id : null, title: String(it.title ?? '') || (s ? (d.lang === 'en' ? s.name_en || s.name_de : s.name_de) : ''), detail: String(it.detail ?? ''),
        qty: it.qty == null || it.qty === '' ? 1 : +it.qty, unit, rate: it.rate == null || it.rate === '' ? (s ? +(svcRate(s, unit) || 0) : 0) : +it.rate, tax: it.tax || s?.tax || 'standard',
        raw_fee: flag(it.raw_fee) ? 1 : 0, producing: flag(it.producing) ? 1 : 0, intext: it.intext || s?.intext || 'intern', cost: it.cost == null || it.cost === '' ? 0 : +it.cost,
        discountable: flag(it.discountable ?? 1) ? 1 : 0, ref_part_id: null};
    });
    d.updated_at = iso();
  }
  // ---- clients (module clients)
  const CL_BILL = ['street', 'address_extra', 'zip', 'city', 'country', 'vat_id', 'customer_no', 'buyer_reference', 'email_invoice', 'payment_terms_days'];
  const clientOut = c => ({...clone(c), archived: !!c.archived, org_name: '', lists: DB.lists.filter(l => l.client_id === c.id).map(l => l.id), can_delete: true,
    billing: Object.fromEntries(CL_BILL.map(k => [k, c[k] ?? null])),
    stats: {seconds: 0, rounded: 0, amount: 0, month: today().slice(0, 7), month_seconds: 0, month_amount: 0, estimate_min: 0, estimated: 0, open: 0, done: 0}, budget: {pct_h: null, pct_amount: null, level: 'none'}});
  const clientBrief = c => ({id: c.id, name: c.name, display_name: c.display_name || '', icon: c.icon || '', color: c.color || '', org_id: null, archived: !!c.archived, lists: DB.lists.filter(l => l.client_id === c.id).map(l => l.id)});
  function clientSet(c, b) {
    if ('name' in b) { if (!String(b.name || '').trim()) bad(tx('Name missing')); c.name = String(b.name).trim(); }
    for (const k of ['display_name', 'icon', 'color', 'email', 'phone', 'address', 'note', 'rate', 'budget_h', 'budget_amount', ...CL_BILL]) if (k in b) c[k] = b[k];
    if ('archived' in b) c.archived = b.archived ? 1 : 0;
    if (Array.isArray(b.contacts)) c.contacts = b.contacts.filter(k => String(k.name || '').trim()).map((k, i) => ({id: k.id || nid('clcontact'), name: String(k.name).trim(), role: k.role || '', email: k.email || '', phone: k.phone || '', is_default: !!k.is_default || (i === 0 && !b.contacts.some(x => x.is_default))}));
    c.contact = (c.contacts || []).find(k => k.is_default)?.name || ''; c.updated_at = iso();
  }
  on('GET', '/api/clients', () => ({clients: CL().map(clientOut)}));
  on('GET', '/api/clients/(\\d+)', (q, b, id) => ({...clientOut(CL().find(c => c.id === +id) || gone()), per_list: []}));
  on('POST', '/api/clients', (q, b) => { const c = {id: nid('client'), name: '', org_id: null, created_by: 1, created_at: iso(), contacts: [], archived: 0}; clientSet(c, {...b, name: b.name ?? ''}); CL().push(c); return clientOut(c); });
  on('PATCH', '/api/clients/(\\d+)', (q, b, id) => { const c = CL().find(x => x.id === +id) || gone(); clientSet(c, b); return clientOut(c); });
  on('DELETE', '/api/clients/(\\d+)', (q, b, id) => { DB.clients = CL().filter(c => c.id !== +id); for (const l of DB.lists) if (l.client_id === +id) l.client_id = null; return {ok: true}; });
  // 2.84.0 (#1198): filed e-mails - the demo has no mailbox, so the sections stay empty and offer no address
  on('GET', '/api/hubmail/mails', () => ({enabled: false, address: '', can_address: false, total: 0, mails: []}));
  on('GET', '/api/hubmail/inbox', () => ({enabled: false, spaces: [], total: 0, mails: []}));
  // 2.96.3 (#1959): video sign-offs - the demo has none (creating one gets the calm "not in the demo" notice)
  on('GET', '/api/videos', () => ({reviews: []}));
  // ---- the office
  const ofInfo = () => ({settings: ofSettings(), company_fields: {...OF().company}, org_id: 1, role: 'admin', personal: 1, org_offices: [], can_move: false, industry: [],
    pack: {code: 'DE', name: 'Deutschland', tax: {...TAX}, currency: 'EUR', formats: {}}, number_preview: `KVA-${today().slice(0, 4)}-${String((OF().counters['offer:' + today().slice(0, 4)] || 0) + 1).padStart(3, '0')}`});
  on('GET', '/api/office/settings', () => ofInfo());
  on('PUT', '/api/office/settings', (q, b) => { const o = OF();
    if (b.company_fields) for (const k of CO_KEYS) if (k in b.company_fields) o.company[k] = String(b.company_fields[k] ?? '');
    const {company_fields, pack, ...rest} = b; o.settings = {...o.settings, ...rest}; return ofInfo(); });
  on('GET', '/api/office/number-preview', q => { const k = q.get('kind') || 'offer'; return {preview: `${SCHEME[k] || 'KVA'}-${today().slice(0, 4)}-001`, valid: true, yearly: true}; });
  // 2.125.0 D (#1653): roles, crew, equipment, sets, texts and contracts are collections now (demo-modules below)
  on('GET', '/api/office/services', () => ({items: clone(OF().services)}));
  const SVC = ['name_de', 'name_en', 'category', 'sort', 'unit', 'daily_rate', 'hourly_rate', 'raw_fee', 'producing', 'intext', 'role', 'role_id', 'tax', 'archived'];
  const svcSet = (s, b) => { for (const k of SVC) if (k in b) s[k] = b[k]; if (!String(s.name_de || '').trim()) bad(tx('Name missing')); s.updated_at = iso(); };
  on('POST', '/api/office/services', (q, b) => { const s = {id: nid('ofsvc'), org_id: 1, name_de: '', name_en: '', category: '', sort: 0, unit: 'day', daily_rate: null, hourly_rate: null, raw_fee: 0, producing: 0,
    intext: 'extern', role: '', role_id: null, tax: 'standard', archived: 0, created_at: iso(), import_run_id: null}; svcSet(s, b); OF().services.push(s); return clone(s); });
  on('PATCH', '/api/office/services/(\\d+)', (q, b, id) => { const s = OF().services.find(x => x.id === +id) || gone(); svcSet(s, b); return clone(s); });
  on('DELETE', '/api/office/services/(\\d+)', (q, b, id) => { OF().services = OF().services.filter(x => x.id !== +id); return {ok: true}; });
  on('GET', '/api/office/pay-props', () => ({items: [], admin: true}));
  on('GET', '/api/office/mail-status', () => ({smtp: false, datev_email: '', datev_auto: 0}));
  on('GET', '/api/office/log', () => ({log: []}));
  on('GET', '/api/office/docs', q => { const k = q.get('kind') || 'offer', st = q.get('status');
    return {docs: OF().docs.filter(d => d.kind === k).map(docLine).filter(r => !st || r.status === st || r.state === st).sort((a, b) => b.id - a.id)}; });
  on('POST', '/api/office/docs', (q, b) => { const k = ['offer', 'invoice'].includes(b.kind) ? b.kind : 'offer', d = newDoc(k); if (b.client_id) patchDoc(d, {client_id: b.client_id, recipient_from_client: true}); return docOut(d); });
  on('GET', '/api/office/docs/(\\d+)', (q, b, id) => docOut(needDoc(id)));
  on('PATCH', '/api/office/docs/(\\d+)', (q, b, id) => { const d = needDoc(id); patchDoc(d, b); return docOut(d); });
  on('PUT', '/api/office/docs/(\\d+)/items', (q, b, id) => { const d = needDoc(id); putItems(d, b.items); return docOut(d); });
  on('DELETE', '/api/office/docs/(\\d+)', (q, b, id) => { const d = needDoc(id); if (d.locked || d.status === 'sent') conflict('Sent documents cannot be changed; duplicate it for a new version.'); OF().docs = OF().docs.filter(x => x !== d); return {ok: true}; });
  on('GET', '/api/office/docs/(\\d+)/signoffs', () => ({signoffs: []}));
  on('GET', '/api/office/docs/(\\d+)/log', () => ({log: []}));
  on('POST', '/api/office/docs/(\\d+)/number', (q, b, id) => { const d = needDoc(id); if (!d.number && !isInv(d)) d.number = nextNumber(d.kind, d.date); return {id: d.id, number: d.number}; });
  on('POST', '/api/office/docs/(\\d+)/status', (q, b, id) => { const d = needDoc(id), s = b.status;
    if (!docOut(d).statuses.includes(s)) bad(tx('Invalid value: {0}').replace('{0}', 'status'));
    if (isInv(d) && !d.locked && s !== 'draft') conflict('Finalise the document first');
    if (d.kind === 'offer' && s === 'draft' && d.status !== 'draft') conflict('Sent documents cannot be changed; duplicate it for a new version.');
    d.status = s; if (s === 'sent' && !d.sent_at) d.sent_at = iso(); if (s === 'paid') d.paid_at = d.paid_at || iso(); d.updated_at = iso();
    const o = docOut(d); delete o.items; return o; });
  on('POST', '/api/office/docs/(\\d+)/finalize', (q, b, id) => { const d = needDoc(id); if (d.locked) conflict('Already finalised');
    const miss = [];
    if (!String(d.recipient?.name || '').trim()) miss.push(tx('Recipient'));
    if (!d.date) miss.push(tx('Date'));
    if (isInv(d) && !(d.items || []).some(it => (it.kind || 'service') === 'service')) miss.push(tx('Service'));
    if (miss.length) bad(tx('Missing before finalising: {0}').replace('{0}', miss.join(', ')));
    if (d.date > today()) bad(tx('Invalid value: {0}').replace('{0}', tx('Date')));
    if (!d.number) d.number = nextNumber(d.kind, d.date);
    if (isInv(d)) { if (!d.service_from && !d.service_to) d.service_from = d.service_to = d.date; if (!d.due_date && d.kind === 'invoice') d.due_date = addDays(d.date, +d.payment_days || 14); d.status = 'issued'; }
    d.frozen = ofCalc(d, isInv(d)); d.locked = 1; d.locked_at = iso(); d.locked_by = 1; d.updated_at = iso();
    return docOut(d); });
  on('POST', '/api/office/docs/(\\d+)/invoice', (q, b, id) => { const o = needDoc(id); if (o.kind !== 'offer') bad(tx('Invalid value: {0}').replace('{0}', 'kind'));
    const cl = CL().find(c => c.id === o.client_id), t = ofCalc(o, false);
    const d = newDoc('invoice', {lang: o.lang, currency: o.currency, fx_rate: o.fx_rate, vat_mode: o.vat_mode, vat_note: o.vat_note, client_id: o.client_id, recipient: clone(o.recipient),
      project_title: o.project_title, project_ref: o.project_ref, order_ref: o.project_ref, rights: clone(o.rights), fields: clone(o.fields), service_from: o.service_from, service_to: o.service_to,
      contact_id: o.contact_id, source_doc_id: o.id, payment_days: cl && cl.payment_terms_days != null ? +cl.payment_terms_days : +ofSettings().payment_days || 14});
    const its = o.items.filter(it => it.kind !== 'discount').map(it => ({...clone(it), id: undefined, raw_fee: 0, producing: 0}));
    for (const l of t.lines) {
      if (l.kind === 'producing') its.push({kind: 'service', title: l.title, detail: l.detail, qty: l.qty, unit: 'day', rate: l.rate, tax: 'standard', intext: 'intern', cost: 0});
      if (l.kind === 'raw' && !l.optional) its.push({kind: 'service', title: l.title, detail: l.detail, qty: 1, unit: 'flat', rate: l.total, tax: 'standard', intext: 'intern', cost: 0});
      if (l.kind === 'discount') its.push({kind: 'discount', title: l.title, detail: l.detail, qty: 1, unit: 'flat', rate: -l.total, tax: 'standard', intext: 'intern', cost: 0});
    }
    putItems(d, its); return docOut(d); });
  on('POST', '/api/office/docs/(\\d+)/duplicate', (q, b, id) => { const o = needDoc(id);
    const {id: _i, number: _n, status: _s, locked: _l, locked_at: _la, locked_by: _lb, frozen: _f, payments: _p, sent_at: _sa, paid_at: _pa, due_date: _dd, ...rest} = clone(o);
    const d = newDoc(o.kind, {...rest, date: today(), items: []}); putItems(d, o.items.map(it => ({...clone(it), id: undefined}))); return docOut(d); });
  on('POST', '/api/office/docs/(\\d+)/payments', (q, b, id) => { const d = needDoc(id);
    if (d.kind !== 'invoice' || !d.locked || ['cancelled', 'paid'].includes(d.status)) conflict('Finalise the document first');
    const amt = C(b.amount), open = C(totalsOf(d).gross) - paidC(d);
    if (!(amt > 0n) || amt > open) bad(tx('Invalid value: {0}').replace('{0}', tx('Amount')));
    if (!b.date || b.date > today()) bad(tx('Invalid value: {0}').replace('{0}', tx('Date')));
    d.payments.push({id: nid('ofpay'), date: b.date, amount: cs(amt), method: b.method || 'transfer', note: String(b.note || ''), created_by: 1, created_at: iso()});
    if (paidC(d) >= C(totalsOf(d).gross)) { d.status = 'paid'; d.paid_at = iso(); }
    return docOut(d); });
  on('DELETE', '/api/office/docs/(\\d+)/payments/(\\d+)', (q, b, id, pid) => { const d = needDoc(id); d.payments = d.payments.filter(p => p.id !== +pid);
    if (d.status === 'paid' && paidC(d) < C(totalsOf(d).gross)) { d.status = 'issued'; d.paid_at = null; } return docOut(d); });

  // ---- the print view (instead of the server's PDF): the document as HTML in an overlay, the browser prints it
  const PL = {de: {offer: 'Angebot', invoice: 'Rechnung', credit: 'Gutschrift', reminder: 'Mahnung', date: 'Datum', valid: 'Gültig bis', due: 'Fällig am', period: 'Leistungszeitraum',
    pos: 'Pos.', desc: 'Leistung', qty: 'Menge', rate: 'Einzelpreis', total: 'Gesamt', paid: 'Bezahlt', open: 'Offen', ref: 'Ihr Zeichen', draft: 'Entwurf'},
  en: {offer: 'Quotation', invoice: 'Invoice', credit: 'Credit note', reminder: 'Reminder', date: 'Date', valid: 'Valid until', due: 'Due on', period: 'Service period',
    pos: 'Pos.', desc: 'Description', qty: 'Qty', rate: 'Unit price', total: 'Amount', paid: 'Paid', open: 'Open', ref: 'Your reference', draft: 'Draft'}};
  const h = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const dfmt = (s, lang) => { if (!s) return ''; const [y, m, d] = String(s).slice(0, 10).split('-'); return lang === 'en' ? `${y}-${m}-${d}` : `${d}.${m}.${y}`; };
  function printHtml(d) {
    const o = docOut(d), t = o.totals, lg = t.lang, P = PL[lg], s = ofSettings(), co = s.company;
    const rows = t.lines.map(l => l.kind === 'heading' ? `<tr class="kp-hd"><td></td><td colspan="4"><b>${h(l.title)}</b></td></tr>`
      : l.kind === 'text' ? `<tr><td></td><td colspan="4" class="kp-tx">${h(l.text)}</td></tr>`
      : `<tr><td>${h(l.pos || '')}</td><td><b>${h(l.title)}</b>${l.detail ? `<br><small>${h(l.detail)}</small>` : ''}</td><td class="kp-n">${h(l.qty_text || '')} ${h(l.unit_text || '')}</td><td class="kp-n">${l.rate != null && l.kind !== 'discount' ? h(fmtM(C(l.rate), lg, t.currency)) : ''}</td><td class="kp-n">${h(l.total_text || fmtM(C(l.total), lg, t.currency))}</td></tr>`).join('');
    const sums = [[t.labels.net, t.net_text || fmtM(C(t.net), lg, t.currency)], ...t.tax_lines.map(x => [x.label, x.amount_text]), ...(t.vat_mode === 'novat' ? [] : [[t.labels.gross, t.gross_text]])];
    if (o.kind === 'invoice' && +o.paid) sums.push([P.paid, fmtM(C(o.paid), lg, t.currency)], [P.open, o.open_text]);
    const meta = [[P.date, dfmt(o.date, lg)], o.kind === 'offer' ? [P.valid, dfmt(o.valid_until, lg)] : null, o.kind === 'invoice' && o.due_date ? [P.due, dfmt(o.due_date, lg)] : null,
      isInv(o) && (o.service_from || o.service_to) ? [P.period, [dfmt(o.service_from, lg), dfmt(o.service_to, lg)].filter(Boolean).join(' – ')] : null, o.project_ref || o.order_ref ? [P.ref, o.project_ref || o.order_ref] : null].filter(Boolean);
    return `<div class="kp-page" lang="${lg}">
      <header class="kp-head"><div class="kp-from"><b>${h(co.name)}</b><br>${co.lines.map(h).join(' · ')}</div></header>
      <div class="kp-addr"><small>${h([co.name, ...co.lines].join(' · '))}</small><br>${(o.recipient.lines.length ? o.recipient.lines : [o.recipient.name]).map(h).join('<br>')}</div>
      <dl class="kp-meta">${meta.map(([k, v]) => `<div><dt>${h(k)}</dt><dd>${h(v)}</dd></div>`).join('')}</dl>
      <h1>${h(P[o.kind] || o.kind)} ${h(o.number || P.draft)}</h1>${o.project_title ? `<h2>${h(o.project_title)}</h2>` : ''}
      ${o.intro ? `<p class="kp-tx">${h(o.intro)}</p>` : ''}
      <table class="kp-items"><thead><tr><th>${P.pos}</th><th>${P.desc}</th><th class="kp-n">${P.qty}</th><th class="kp-n">${P.rate}</th><th class="kp-n">${P.total}</th></tr></thead><tbody>${rows}</tbody></table>
      <dl class="kp-sums">${sums.map(([k, v], i) => `<div class="${i === sums.length - 1 || k === t.labels.gross ? 'kp-g' : ''}"><dt>${h(k)}</dt><dd>${h(v)}</dd></div>`).join('')}</dl>
      ${t.vat_note ? `<p class="kp-note">${h(t.vat_note)}</p>` : ''}${o.closing ? `<p class="kp-tx">${h(o.closing)}</p>` : ''}
      <footer class="kp-foot"><div>${[co.name, ...co.lines].map(h).join('<br>')}</div><div>${co.contact_lines.map(h).join('<br>')}</div><div>${co.register_lines.map(h).join('<br>')}</div><div>${co.bank_lines.map(h).join('<br>')}</div></footer></div>`;
  }
  function printView(id) {
    const d = OF().docs.find(x => x.id === +id); if (!d) { notice(); return; }
    const x = T(); document.getElementById('kd-print')?.remove();
    const el = document.createElement('div'); el.id = 'kd-print'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-label', x.printTitle);
    el.innerHTML = `<div class="kd-pbar"><b></b><span class="kd-ptxt"></span><span class="kd-sp"></span><button type="button" class="kd-btn kd-pri" data-kp="print"></button><button type="button" class="kd-btn" data-kp="close"></button></div><div class="kd-pscroll">${printHtml(d)}</div>`;
    el.querySelector('.kd-pbar b').textContent = x.printTitle; el.querySelector('.kd-ptxt').textContent = x.printNote;
    el.querySelector('[data-kp="print"]').textContent = x.print; el.querySelector('[data-kp="close"]').textContent = x.close;
    const back = document.activeElement, close = () => { el.remove(); document.documentElement.classList.remove('kd-printing'); back?.focus?.(); };
    el.addEventListener('click', e => { const b = e.target.closest('[data-kp]'); if (!b) return; if (b.dataset.kp === 'print') window.print(); else close(); });
    el.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
    document.body.appendChild(el); document.documentElement.classList.add('kd-printing');
    el.querySelector('[data-kp="print"]').focus();
  }
  const PDF_RE = /^\/api\/office\/docs\/(\d+)\/pdf$/;
  const pdfId = url => { try { const m = new URL(url, 'https://demo.invalid/').pathname.match(PDF_RE); return m ? +m[1] : null; } catch { return null; } };
  // the app opens a PDF with its viewer (pdfView), window.open or a download link: all of them become the print view
  window.addEventListener('load', () => {
    const pv = window.pdfView;
    if (typeof pv === 'function') window.pdfView = o => { const id = pdfId(o?.url || ''); return id ? printView(id) : pv(o); };
  });
  const wopen = window.open;
  window.open = (url, ...rest) => { const id = pdfId(String(url || '')); if (id) { printView(id); return null; }
    if (/^\/api\//.test(String(url || ''))) { if (!fileOpen(String(url))) notice(); return null; } return wopen.call(window, url, ...rest); };

  // ---------------------------------------------------------------- demo-modules (2.125.0 D, #1653)
  // Every module of a new account runs in the demo (shapes of the server's JSON, read off the Flask routes): contacts, home &
  // life, review & journal, budget, feeds (no fetching: the notice), bookmarks, workload with absences and disposition,
  // knowledge pages, tables (a small evaluator for the common formulas), the file store and documents (small files kept as
  // data URLs in this browser) and the office's pages beyond quotes / invoices (pipeline, cash flow, figures, bookkeeping,
  // subscriptions, travel, meals, agreements, equipment). A new route: one on(...) line (or crud(...) for a plain
  // collection); tools/build_demo.py lists the app's calls that no route here answers.
  const MD = () => DB.m || (DB.m = {});
  const mcol = k => MD()[k] || (MD()[k] = []);
  const mfind = (k, id) => mcol(k).find(x => x.id === +id) || gone();
  const fon = f => DB.settings.features.split(',').includes(f);
  const num = v => { if (typeof v === 'number') return v; const s = String(v ?? '').replace(/[^\d,.-]/g, ''); if (!s) return 0; return +(s.includes(',') ? s.replace(/\./g, '').replace(',', '.') : s) || 0; };
  const m2 = v => (Math.round((+v || 0) * 100) / 100).toFixed(2);
  const daysTo = d => d ? Math.round((Date.parse(String(d).slice(0, 10) + 'T12:00:00') - Date.parse(today() + 'T12:00:00')) / 864e5) : null;
  const addD = (d, n) => { const x = new Date(String(d).slice(0, 10) + 'T12:00:00'); x.setDate(x.getDate() + n); return ds(x); };
  const addM = (d, n) => { const x = new Date(String(d).slice(0, 10) + 'T12:00:00'); x.setMonth(x.getMonth() + n); return ds(x); };
  const monday = d => { const x = new Date(String(d || today()).slice(0, 10) + 'T12:00:00'); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return ds(x); };
  const monthEnd = m => { const [y, mo] = m.split('-').map(Number); return `${m}-${pad(new Date(y, mo, 0).getDate())}`; };
  const monthAdd = (m, n) => { const [y, mo] = m.split('-').map(Number), x = new Date(y, mo - 1 + n, 1); return `${x.getFullYear()}-${pad(x.getMonth() + 1)}`; };
  // crud(base, key, opts): a plain collection in DB.m[key]: GET base -> {[list]: items}, POST -> the new one, GET / PATCH / PUT /
  // DELETE base/<id>, POST base/<id>/restore (deleted_at, so undo works)
  function crud(base, key, {list = 'items', def = () => ({}), out = x => clone(x), keep = () => true, index = null, post = null, one = null, del = null} = {}) {
    on('GET', base, q => index ? index(q) : {[list]: mcol(key).filter(x => !x.deleted_at && keep(x, q)).map(out)});
    on('POST', base, (q, b) => { const x = {...def(b), ...b, id: nid(key), created_at: iso(), updated_at: iso(), deleted_at: null}; mcol(key).push(x); return post ? post(x) : out(x); });
    on('GET', base + '/(\\d+)', (q, b, id) => out(mfind(key, id)));
    const upd = (q, b, id) => { const x = mfind(key, id), before = clone(x); Object.assign(x, b, {updated_at: iso()}); return one ? one(x, before) : out(x); };
    on('PATCH', base + '/(\\d+)', upd); on('PUT', base + '/(\\d+)', upd);
    on('DELETE', base + '/(\\d+)', (q, b, id) => { const x = mfind(key, id); x.deleted_at = iso(); return del ? del(x) : {ok: true, item: out(x)}; });
    on('POST', base + '/(\\d+)/restore', (q, b, id) => { const x = mfind(key, id); x.deleted_at = null; return out(x); });
  }

  // ---- events in own calendars (kalmido/events/model.py cal_public / ev_dict / occ_out): no CalDAV, no invitations by mail in
  // the demo; repeating events are expanded with the task repeat rules (DAILY / WEEKLY / MONTHLY / YEARLY, INTERVAL, BYDAY)
  const evcals = () => { const k = mcol('evcals'); if (!k.length) k.push({id: nid('evcals'), name: tx('Calendar'), color: '#7c5cff', description: '', sort: 0, deleted_at: null}); return k.filter(x => !x.deleted_at); };
  const evcalOut = k => ({id: k.id, name: k.name, color: k.color, description: k.description || '', owner_id: 1, role: 'owner', sort: k.sort || 0, org_id: null, owner_name: DB.me.display_name, members: [], hidden: false});
  const evOut = e => ({id: e.id, cal_id: e.cal_id, uid: 'demo-' + e.id, title: e.title, location: e.location || '', description: e.description || '', all_day: !!e.all_day, start: e.start, end: e.end,
    tz: e.tz || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', rrule: e.rrule || '', exdates: [], overrides: [], reminders: e.reminders || [], status: e.status || 'confirmed', busy: e.busy !== false,
    url: e.url || null, task_id: e.task_id || null, attendees: [], role: 'owner', created_by: 1, created_at: e.created_at, updated_at: e.updated_at});
  const utcZ = local => new Date(local).toISOString().replace(/\.\d{3}Z$/, 'Z');
  function evRange(lo, hi) {
    const out = [], cals = new Set(evcals().map(k => k.id));
    for (const e of mcol('events').filter(x => !x.deleted_at && cals.has(x.cal_id))) {
      const d0 = e.start.slice(0, 10), len = Math.round((Date.parse(e.end.slice(0, 10) + 'T12:00:00') - Date.parse(d0 + 'T12:00:00')) / 864e5), tm = s => s.length > 10 ? s.slice(10) : '';
      let d = d0, n = 0;
      while (d <= hi && n < 400) {
        if (addD(d, len) >= lo) out.push({id: 'k' + out.length, own: true, eid: e.id, occ: d, cal: e.cal_id, title: e.title, location: e.location || '', description: (e.description || '').slice(0, 2000), all_day: !!e.all_day,
          start: e.all_day ? d : utcZ(d + tm(e.start)), end: e.all_day ? addD(d, Math.max(1, len)) : utcZ(addD(d, len) + tm(e.end)), recurring: !!e.rrule, changed: false, status: e.status || 'confirmed', role: 'owner', task_id: e.task_id || null, att: 0});
        if (!e.rrule) break; d = nextDate(e.rrule, d); n++;
      }
    }
    return {events: out, subs: {}, evcals: Object.fromEntries(evcals().map(k => [k.id, {name: k.name, color: k.color, role: 'owner'}])), errors: []};
  }
  const evSet = (e, b) => { for (const k of ['title', 'location', 'description', 'all_day', 'start', 'end', 'tz', 'rrule', 'reminders', 'status', 'busy', 'url', 'task_id']) if (k in b) e[k] = b[k];
    if (b.cal_id) e.cal_id = +b.cal_id; if (!e.cal_id) e.cal_id = evcals()[0].id; if (!e.start) bad(tx('Invalid value: {0}').replace('{0}', 'start')); if (!e.end || e.end < e.start) e.end = e.start; e.updated_at = iso(); };
  on('GET', '/api/events/(\\d+)', (q, b, id) => { const e = mfind('events', id); if (e.deleted_at) gone(); return evOut(e); });
  on('POST', '/api/events', (q, b) => { const e = {id: nid('events'), created_at: iso(), deleted_at: null}; evSet(e, b); mcol('events').push(e); return evOut(e); });
  on('PATCH', '/api/events/(\\d+)', (q, b, id) => { const e = mfind('events', id); if (b.expect && b.expect !== e.updated_at) throw new Http(409, {error: tx('Changed in the meantime')}); evSet(e, b); return evOut(e); });
  on('DELETE', '/api/events/(\\d+)', (q, b, id) => { mfind('events', id).deleted_at = iso(); return {ok: true}; });
  on('POST', '/api/events/(\\d+)/restore', (q, b, id) => { const e = mfind('events', id); e.deleted_at = null; return evOut(e); });
  on('POST', '/api/events/(\\d+)/prep-task', (q, b, id) => { const e = mfind('events', id), inbox = DB.lists.find(l => l.is_inbox) || DB.lists[0];
    const t = newTask({title: e.title, list_id: inbox.id, due: addD(e.start.slice(0, 10), -1)}); return {task_id: t.id, ...taskOut(t)}; });
  on('POST', '/api/evcals', (q, b) => { const k = {id: nid('evcals'), name: String(b.name || '').trim() || tx('Calendar'), color: b.color || '#22c55e', description: '', sort: mcol('evcals').length, deleted_at: null}; mcol('evcals').push(k); return evcalOut(k); });
  on('PATCH', '/api/evcals/(\\d+)', (q, b, id) => { const k = mfind('evcals', id); for (const f of ['name', 'color', 'description']) if (f in b) k[f] = b[f]; return evcalOut(k); });

  // ---- time: the "days without entries" card stays empty (kalmido/personal/timegaps.py)
  on('GET', '/api/time/gaps', () => ({from: day(-14), to: day(-1), days: []}));

  // ---- contacts + address books (kalmido/contacts/web.py, model.py contact_brief / contact_dict / book_public)
  const books = () => { const b = mcol('books'); if (!b.length) b.push({id: nid('books'), name: tx('Contacts'), color: '#7c5cff', created_at: iso(), deleted_at: null}); return b.filter(x => !x.deleted_at); };
  const bookOut = b => ({id: b.id, name: b.name, color: b.color, owner_id: 1, role: 'owner', org_id: null, imported: false, birthdays_list_id: null,
    count: mcol('contacts').filter(c => !c.deleted_at && c.book_id === b.id).length, owner_name: DB.me.display_name, org_owned: false, org_role: null, can_org: false, members: []});
  const CT_ARR = ['emails', 'phones', 'urls', 'addresses', 'groups'];
  const ctFn = c => String(c.fn || [c.prefix, c.given, c.middle, c.family, c.suffix].filter(Boolean).join(' ') || c.org || '').trim();
  const ctBrief = c => ({id: c.id, book_id: c.book_id, fn: ctFn(c), org: c.org || '', kind: c.kind || 'individual', email: c.emails?.[0]?.value || '', phone: c.phones?.[0]?.value || '',
    photo: false, bday: c.bday || '', groups: c.groups || []});
  const careOut = c => { const k = c.care || {every_days: 0, last: null, note: ''}; return {every_days: k.every_days || 0, last: k.last || null, note: k.note || '', due: k.every_days && k.last ? addD(k.last, k.every_days) : null}; };
  const ctFull = c => ({given: '', family: '', middle: '', prefix: '', suffix: '', nickname: '', org: '', dept: '', title: '', bday: '', anniversary: '', note: '', uid: 'demo-' + c.id,
    ...clone(c), photo: '', ...Object.fromEntries(CT_ARR.map(k => [k, c[k] || []])), fn: ctFn(c), kind: c.kind || 'individual', tasks: [], events: [], clients: [], role: 'owner',
    newsletter: false, ...(fon('care') ? {care: careOut(c)} : {})});
  const ctSet = (c, b) => { for (const [k, v] of Object.entries(b)) if (!['id', 'expect', 'role'].includes(k)) c[k] = v; c.fn = ''; c.fn = ctFn({...c, fn: b.fn}); if (!c.fn) bad(tx('Please enter a name')); c.updated_at = iso(); };
  const liveCt = () => mcol('contacts').filter(c => !c.deleted_at);
  on('GET', '/api/contacts', q => {
    const s = (q.get('q') || '').toLowerCase(), g = q.get('group'), bk = +q.get('book_id') || 0, off = +q.get('offset') || 0, lim = Math.min(+q.get('limit') || 500, 2000);
    const all = liveCt().filter(c => (!s || [ctFn(c), c.org, ...(c.emails || []).map(e => e.value), ...(c.phones || []).map(e => e.value)].join(' ').toLowerCase().includes(s))
      && (!g || (c.groups || []).includes(g)) && (!bk || c.book_id === bk)).sort((a, b) => ctFn(a).localeCompare(ctFn(b)));
    return {items: all.slice(off, off + lim).map(ctBrief), total: all.length, groups: [...new Set(liveCt().flatMap(c => c.groups || []))].sort()};
  });
  on('GET', '/api/contacts/groups', () => ({items: [...new Set(liveCt().flatMap(c => c.groups || []))].sort().map(name => ({name, count: liveCt().filter(c => (c.groups || []).includes(name)).length}))}));
  on('POST', '/api/contacts/groups', (q, b) => { let n = 0;
    for (const c of liveCt()) if ((c.groups || []).includes(b.name)) { c.groups = b.action === 'rename' ? [...new Set(c.groups.map(x => x === b.name ? b.to : x))] : c.groups.filter(x => x !== b.name); n++; }
    return {action: b.action, changed: n, skipped: 0, undo: null}; });
  on('POST', '/api/contacts/dupcheck', (q, b) => { const fn = String(b.fn || [b.given, b.family].filter(Boolean).join(' ')).trim().toLowerCase(), em = (b.emails || []).map(x => String(x).toLowerCase());
    return {items: liveCt().filter(c => (fn && ctFn(c).toLowerCase() === fn) || (c.emails || []).some(e => em.includes(String(e.value).toLowerCase())))
      .map(c => ({id: c.id, fn: ctFn(c), org: c.org || '', book_id: c.book_id, reasons: [(c.emails || []).some(e => em.includes(String(e.value).toLowerCase())) ? 'email' : 'name']}))}; });
  on('POST', '/api/contacts', (q, b) => { const c = {id: nid('contacts'), book_id: +b.book_id || books()[0].id, created_at: iso(), deleted_at: null}; ctSet(c, b); mcol('contacts').push(c); return ctFull(c); });
  on('GET', '/api/contacts/(\\d+)', (q, b, id) => { const c = mfind('contacts', id); if (c.deleted_at) gone(); return ctFull(c); });
  on('GET', '/api/contacts/(\\d+)/history', () => ({items: [], more: false}));
  on('PATCH', '/api/contacts/(\\d+)', (q, b, id) => { const c = mfind('contacts', id); if (b.expect && b.expect !== c.updated_at) throw new Http(409, {error: tx('Changed in the meantime')}); ctSet(c, b); return ctFull(c); });
  on('DELETE', '/api/contacts/(\\d+)', (q, b, id) => { mfind('contacts', id).deleted_at = iso(); return {ok: true}; });
  on('POST', '/api/contacts/(\\d+)/restore', (q, b, id) => { const c = mfind('contacts', id); c.deleted_at = null; return ctFull(c); });
  on('PUT', '/api/contacts/(\\d+)/care', (q, b, id) => { const c = mfind('contacts', id), k = c.care || (c.care = {every_days: 0, last: null, note: ''});
    if ('every_days' in b) k.every_days = Math.max(0, +b.every_days || 0); if ('note' in b) k.note = String(b.note || ''); if ('last' in b) k.last = b.last === 'today' ? today() : b.last || null; return careOut(c); });
  on('GET', '/api/books', () => ({items: books().map(bookOut)}));
  on('POST', '/api/books', (q, b) => { const x = {id: nid('books'), name: String(b.name || tx('Contacts')), color: b.color || '#7c5cff', created_at: iso(), deleted_at: null}; mcol('books').push(x); return bookOut(x); });
  on('PATCH', '/api/books/(\\d+)', (q, b, id) => { const x = mfind('books', id); if (b.name) x.name = String(b.name); if (b.color) x.color = b.color; return bookOut(x); });
  on('DELETE', '/api/books/(\\d+)', (q, b, id) => { if (books().length < 2) bad(tx('Invalid value: {0}').replace('{0}', 'book')); mfind('books', id).deleted_at = iso(); return {ok: true}; });

  // ---- home & life (kalmido/life/model.py life_overview): the rows are tasks with fam {kind: contract | device | upkeep | health}
  const LIFE_LIST = {contract: 'Contracts', device: 'Home & devices', upkeep: 'Home & devices', health: 'Health', travel: 'Travel', reading: 'Read later'};
  const lifeList = (kind, lid) => (lid && listById(lid)) || DB.lists.find(l => l.life === kind && !l.archived) || (() => {
    const l = {...clone(LIST_DEF), id: nid('list'), created_at: iso(), name: tx(LIFE_LIST[kind] || 'Home & life'), life: kind, sort: Math.max(0, ...DB.lists.map(x => x.sort)) + 1}; DB.lists.push(l); return l; })();
  const famTasks = k => live().filter(t => t.status === 0 && t.fam && t.fam.kind === k);
  const PERM = {month: 1, quarter: 3, year: 12};
  const lifeTask = (kind, b, o) => newTask({list_id: lifeList(kind === 'upkeep' || kind === 'device' ? 'device' : kind, b.list_id).id, ...o});
  on('GET', '/api/life', () => {
    const out = {modules: LIFE.filter(m => fon(m) && m !== 'review')};
    if (fon('contracts')) { const items = famTasks('contract').map(t => { const f = t.fam, mo = (+f.cost || 0) / (PERM[f.per] || 1);
      return {task_id: t.id, list_id: t.list_id, title: t.title, name: f.name, provider: f.provider || '', cost: +f.cost || 0, per: f.per || 'month', monthly: +m2(mo), yearly: +m2(mo * 12), notice: f.notice || 0,
        notice_unit: f.nu || 'm', due: t.due, ends: f.ends || null, renew_months: f.renew || 0, days: daysTo(t.due), account: f.account || '', start: f.start || null}; });
      out.contracts = {items, monthly: +m2(items.reduce((a, x) => a + x.monthly, 0)), yearly: +m2(items.reduce((a, x) => a + x.yearly, 0))}; }
    if (fon('home')) out.home = {devices: famTasks('device').map(t => ({task_id: t.id, list_id: t.list_id, title: t.title, name: t.fam.name, model: t.fam.model || '', bought: t.fam.bought || null, warranty: t.fam.warranty || null, days: daysTo(t.fam.warranty || t.due)})),
      upkeep: famTasks('upkeep').map(t => ({task_id: t.id, list_id: t.list_id, title: t.title, item: t.fam.item || '', due: t.due, every_months: t.fam.every || 0, days: daysTo(t.due)}))};
    if (fon('care')) out.care = {contacts: fon('contacts'), items: liveCt().filter(c => c.care?.every_days).map(c => { const k = careOut(c); return {contact_id: c.id, fn: ctFn(c), photo: false, ...k, days: k.due ? daysTo(k.due) : 0}; })};
    if (fon('health')) out.health = {items: famTasks('health').map(t => ({task_id: t.id, list_id: t.list_id, title: t.title, type: t.fam.type || 'appointment', who: t.fam.who || '', due: t.due, time: t.due_time, repeat: t.repeat || '', days: daysTo(t.due)}))};
    if (fon('travel')) out.travel = {trips: DB.lists.filter(l => l.life === 'travel' && l.trip && !l.archived).map(l => { const tr0 = l.trip, ts = live().filter(t => t.list_id === l.id && !t.parent_id);
      return {list_id: l.id, name: l.name, where: tr0.where || '', from: tr0.from, to: tr0.to, days: daysTo(tr0.from), state: tr0.to < today() ? 'past' : tr0.from <= today() ? 'now' : 'upcoming', open: ts.filter(t => t.status === 0).length, total: ts.length}; })};
    if (fon('reading')) { const ls = DB.lists.filter(l => l.life === 'reading' && !l.archived).map(l => l.id), items = live().filter(t => ls.includes(t.list_id) && t.status === 0);
      out.reading = {lists: ls, items: items.slice(0, 5).map(t => ({task_id: t.id, list_id: t.list_id, title: t.title, url: t.url || ''})), count: items.length, karakeep: {connected: false}}; }
    return out;
  });
  on('GET', '/api/life/upkeep-presets', () => ({presets: []}));
  on('GET', '/api/life/karakeep', () => ({connected: false}));
  const noticeAt = (ends, n, u) => !ends ? null : u === 'd' ? addD(ends, -n) : u === 'w' ? addD(ends, -7 * n) : addM(ends, -n);
  on('POST', '/api/life/contracts', (q, b) => { const name = String(b.name || '').trim() || bad(tx('Please enter a name')), n = +b.notice || 0;
    return lifeTask('contract', b, {title: tx('Cancel or renew the contract: {0}').replace('{0}', name), due: noticeAt(b.ends, n, b.notice_unit) || b.ends || null,
      repeat: +b.renew_months ? `FREQ=MONTHLY;INTERVAL=${+b.renew_months}` : '', fam: {kind: 'contract', name, provider: b.provider || '', cost: num(b.cost), per: b.per || 'month', notice: n, nu: b.notice_unit || 'm',
        lead: +b.lead_days || 0, account: b.account || '', start: b.start || null, ends: b.ends || null, renew: +b.renew_months || 0}}); });
  on('POST', '/api/life/devices', (q, b) => { const name = String(b.name || '').trim() || bad(tx('Please enter a name'));
    return lifeTask('device', b, {title: b.warranty ? tx('Warranty ends: {0}').replace('{0}', name) : name, due: b.warranty || null, fam: {kind: 'device', name, model: b.model || '', bought: b.bought || null, warranty: b.warranty || null, lead: +b.lead_days || 0}}); });
  on('POST', '/api/life/upkeep', (q, b) => { const title = String(b.title || '').trim() || bad(tx('Please enter a name')), ev = +b.every_months || 12;
    return lifeTask('upkeep', b, {title, due: b.next || today(), repeat: `FREQ=MONTHLY;INTERVAL=${ev}`, fam: {kind: 'upkeep', item: '', every: ev, lead: +b.lead_days || 0}}); });
  on('POST', '/api/life/health', (q, b) => { const title = String(b.title || '').trim() || bad(tx('Please enter a name')), times = Array.isArray(b.times) && b.times.length ? b.times : [b.time || null];
    return {tasks: times.map(tm => lifeTask('health', b, {title, due: b.date || today(), due_time: tm || null, repeat: b.type === 'medication' ? 'FREQ=DAILY' : +b.every_months ? `FREQ=MONTHLY;INTERVAL=${+b.every_months}` : '',
      fam: {kind: 'health', type: b.type || 'appointment', who: b.who || ''}}))}; });
  on('POST', '/api/life/trips', (q, b) => { const name = String(b.name || '').trim() || bad(tx('Please enter a name'));
    const l = {...clone(LIST_DEF), id: nid('list'), created_at: iso(), name, life: 'travel', trip: {from: b.from || today(), to: b.to || b.from || today(), where: b.where || ''}, sort: Math.max(0, ...DB.lists.map(x => x.sort)) + 1};
    DB.lists.push(l); return {list_id: l.id, event_id: null}; });

  // ---- review & journal (kalmido/life/model.py review / journal_set)
  on('GET', '/api/life/review', q => {
    const period = q.get('period') === 'week' ? 'week' : 'day', date = q.get('date') || today(), from = period === 'week' ? monday(date) : date, to = period === 'week' ? addD(from, 6) : date;
    const ref = t => ({task_id: t.id, title: t.title, list_id: t.list_id});
    return {period, from, to,
      done: live().filter(t => t.status !== 0 && t.completed_at && ds(new Date(t.completed_at)) >= from && ds(new Date(t.completed_at)) <= to).map(t => ({...ref(t), at: t.completed_at})),
      open: live().filter(t => t.status === 0 && t.due && t.due <= to && !t.parent_id).map(t => ({...ref(t), due: t.due, overdue: t.due < today()})),
      moved: [], next: live().filter(t => t.status === 0 && t.due && t.due > to && t.due <= addD(to, 7) && !t.parent_id).map(t => ({...ref(t), due: t.due, time: t.due_time})),
      journal: mcol('journal').filter(j => j.day >= from && j.day <= to).map(j => ({day: j.day, text: j.text, mood: j.mood}))};
  });
  on('PUT', '/api/life/journal/([0-9-]{10})', (q, b, dd) => { if (dd > addD(today(), 1)) bad(tx('Invalid value: {0}').replace('{0}', 'day'));
    const J = mcol('journal'), text = String(b.text || ''), mood = b.mood == null ? null : Math.min(5, Math.max(1, +b.mood)), i = J.findIndex(j => j.day === dd);
    if (!text && mood == null) { if (i >= 0) J.splice(i, 1); return {day: dd, text: '', mood: null}; }
    const j = {id: i >= 0 ? J[i].id : nid('journal'), day: dd, text, mood}; if (i >= 0) J[i] = j; else J.push(j); return {day: dd, text, mood}; });

  // ---- budget (kalmido/life/budget.py): household budgets of their own (not in the sidebar), categories, entries, recurring entries
  const bgEntries = (lid, m) => mcol('bentries').filter(e => !e.deleted_at && e.list_id === lid && (!m || e.day.slice(0, 7) === m));
  const recDue = (r, m) => !r.deleted_at && r.start <= m && (!r.until || r.until >= m) && ((+m.slice(0, 4) - +r.start.slice(0, 4)) * 12 + (+m.slice(5) - +r.start.slice(5))) % (PERM[r.per] || 1) === 0;
  const bgTotals = (lid, m) => { const es = bgEntries(lid, m), cats = mcol('bcats').filter(c => !c.deleted_at && c.list_id === lid), recs = mcol('brec').filter(r => r.list_id === lid && recDue(r, m));
    const soll = c => c.limit != null ? +c.limit : recs.filter(r => r.cat_id === c.id).reduce((a, r) => a + +r.amount, 0);
    const sum = k => +m2(es.filter(e => e.kind === k).reduce((a, e) => a + +e.amount, 0));
    const t = {soll_in: +m2(cats.filter(c => c.kind === 'in').reduce((a, c) => a + soll(c), 0)), ist_in: sum('in'), soll_out: +m2(cats.filter(c => c.kind === 'out').reduce((a, c) => a + soll(c), 0)), ist_out: sum('out')};
    t.saldo = +m2(t.ist_in - t.ist_out); return {t, es, cats, recs, soll}; };
  const bgEntry = e => ({id: e.id, list_id: e.list_id, day: e.day, amount: +e.amount, kind: e.kind, title: e.title || '', note: e.note || '', counterpart: e.counterpart || '', cat_id: e.cat_id ?? null,
    recurring_id: e.recurring_id ?? null, source: e.source || '', files: [], created_by: 1, updated_at: e.updated_at});
  const bgCat = c => ({id: c.id, list_id: c.list_id, name: c.name, kind: c.kind, limit: c.limit ?? null, sort: c.sort || 0});
  const bgRec = r => ({id: r.id, list_id: r.list_id, title: r.title, amount: +r.amount, kind: r.kind, cat_id: r.cat_id ?? null, per: r.per, start: r.start, until: r.until || null, contract_task_id: r.contract_task_id || null, contract_changed: false, contract: null});
  const bgList = id => mcol('budgets').find(x => x.id === +id && !x.deleted_at) || gone();
  on('GET', '/api/budget', q => { const m = q.get('month') || today().slice(0, 7), ls = mcol('budgets').filter(x => !x.deleted_at);
    return {lists: ls.map(l => ({id: l.id, name: l.name, color: '#7c5cff', owner_id: 1, shared: false, can_write: true})), month: m, summary: ls[0] ? bgTotals(ls[0].id, m).t : null}; });
  on('GET', '/api/budget/(\\d+)', (q, b, id) => { const l = bgList(id), m = q.get('month') || today().slice(0, 7), {t, es, cats, recs, soll} = bgTotals(l.id, m);
    return {list_id: l.id, name: l.name, month: m, can_write: true, totals: t,
      cats: cats.sort((a, c) => (a.sort || 0) - (c.sort || 0) || a.id - c.id).map(c => ({...bgCat(c), soll: +m2(soll(c)), ist: +m2(es.filter(e => e.cat_id === c.id).reduce((a, e) => a + +e.amount, 0)), planned: 0})),
      none: {ist_in: +m2(es.filter(e => !e.cat_id && e.kind === 'in').reduce((a, e) => a + +e.amount, 0)), ist_out: +m2(es.filter(e => !e.cat_id && e.kind === 'out').reduce((a, e) => a + +e.amount, 0))},
      entries: es.sort((a, c) => c.day.localeCompare(a.day) || c.id - a.id).map(bgEntry),
      open_recurring: recs.filter(r => !es.some(e => e.recurring_id === r.id)).map(r => ({recurring: bgRec(r), amount: +r.amount, day: m + '-01'})),
      trend: [5, 4, 3, 2, 1, 0].map(n => { const mm = monthAdd(m, -n), x = bgTotals(l.id, mm).t; return {month: mm, ist_in: x.ist_in, ist_out: x.ist_out}; })}; });
  on('POST', '/api/budget/lists', () => { const l = {id: nid('budgets'), name: tx('Budget'), created_at: iso(), deleted_at: null}; mcol('budgets').push(l); return {list_id: l.id}; });
  const bgSet = (e, b) => { for (const k of ['day', 'kind', 'title', 'note', 'counterpart', 'cat_id', 'recurring_id', 'source']) if (k in b) e[k] = b[k]; if ('amount' in b) e.amount = Math.abs(num(b.amount));
    if (!/^\d{4}-\d\d-\d\d$/.test(e.day || '')) bad(tx('Invalid value: {0}').replace('{0}', 'day')); e.updated_at = iso(); };
  on('POST', '/api/budget/(\\d+)/entries', (q, b, id) => { const e = {id: nid('bentries'), list_id: bgList(id).id, kind: 'out', deleted_at: null}; bgSet(e, b); mcol('bentries').push(e); return bgEntry(e); });
  on('PATCH', '/api/budget/entries/(\\d+)', (q, b, id) => { const e = mfind('bentries', id); bgSet(e, b); return bgEntry(e); });
  on('DELETE', '/api/budget/entries/(\\d+)', (q, b, id) => { const e = mfind('bentries', id); e.deleted_at = iso(); return {ok: true, entry: bgEntry(e)}; });
  on('POST', '/api/budget/(\\d+)/cats', (q, b, id) => { const c = {id: nid('bcats'), list_id: bgList(id).id, name: String(b.name || '').trim() || bad(tx('Please enter a name')), kind: b.kind === 'in' ? 'in' : 'out',
    limit: b.limit == null || b.limit === '' ? null : num(b.limit), sort: mcol('bcats').length, deleted_at: null}; mcol('bcats').push(c); return bgCat(c); });
  on('PATCH', '/api/budget/cats/(\\d+)', (q, b, id) => { const c = mfind('bcats', id); for (const k of ['name', 'kind', 'sort']) if (k in b) c[k] = b[k]; if ('limit' in b) c.limit = b.limit == null || b.limit === '' ? null : num(b.limit); return bgCat(c); });
  on('DELETE', '/api/budget/cats/(\\d+)', (q, b, id) => { const c = mfind('bcats', id); c.deleted_at = iso(); const ids = mcol('bentries').filter(e => e.cat_id === c.id).map(e => e.id);
    mcol('bentries').forEach(e => { if (e.cat_id === c.id) e.cat_id = null; }); return {ok: true, cat: bgCat(c), entry_ids: ids, recurring_ids: []}; });
  on('GET', '/api/budget/(\\d+)/recurring', (q, b, id) => ({items: mcol('brec').filter(r => r.list_id === +id && !r.deleted_at).map(bgRec)}));
  const recSet = (r, b) => { for (const k of ['title', 'kind', 'cat_id', 'per', 'start', 'until', 'contract_task_id']) if (k in b) r[k] = b[k]; if ('amount' in b) r.amount = Math.abs(num(b.amount)); r.start = r.start || today().slice(0, 7); };
  on('POST', '/api/budget/(\\d+)/recurring', (q, b, id) => { const r = {id: nid('brec'), list_id: bgList(id).id, kind: 'out', per: 'month', deleted_at: null}; recSet(r, b); mcol('brec').push(r); return bgRec(r); });
  on('PATCH', '/api/budget/recurring/(\\d+)', (q, b, id) => { const r = mfind('brec', id); recSet(r, b); return bgRec(r); });
  on('DELETE', '/api/budget/recurring/(\\d+)', (q, b, id) => { const r = mfind('brec', id); r.deleted_at = iso(); return {ok: true, item: bgRec(r)}; });
  on('POST', '/api/budget/recurring/(\\d+)/book', (q, b, id) => { const r = mfind('brec', id), e = {id: nid('bentries'), list_id: r.list_id, deleted_at: null};
    bgSet(e, {day: b.day || (b.month || today().slice(0, 7)) + '-01', amount: r.amount, kind: r.kind, title: r.title, cat_id: r.cat_id, recurring_id: r.id}); mcol('bentries').push(e); return bgEntry(e); });
  const bgContracts = lid => famTasks('contract').map(t => ({task_id: t.id, name: t.fam.name, provider: t.fam.provider || '', cost: +t.fam.cost || 0, per: t.fam.per || 'month',
    monthly: +m2((+t.fam.cost || 0) / (PERM[t.fam.per] || 1)), taken: mcol('brec').some(r => r.list_id === lid && !r.deleted_at && r.contract_task_id === t.id)}));
  on('GET', '/api/budget/(\\d+)/contracts', (q, b, id) => ({items: bgContracts(+id)}));
  on('POST', '/api/budget/(\\d+)/contracts', (q, b, id) => { const lid = bgList(id).id, want = Array.isArray(b.task_ids) ? b.task_ids.map(Number) : null; let n = 0;
    for (const c of bgContracts(lid)) if (!c.taken && (!want || want.includes(c.task_id))) { const r = {id: nid('brec'), list_id: lid, deleted_at: null}; recSet(r, {title: c.name, amount: c.cost, kind: 'out', per: c.per, contract_task_id: c.task_id}); mcol('brec').push(r); n++; }
    return {created: n, items: bgContracts(lid)}; });

  // ---- feeds: fetching needs a server (the notice on "Add"), the views stay calm
  on('GET', '/api/feeds', () => ({feeds: [], unread: 0, max: 100}));
  on('GET', '/api/feeds/items', () => ({items: [], more: false, unread: 0}));
  on('POST', '/api/feeds/read', () => ({ids: []}));

  // ---- bookmarks (kalmido/life/bookmarks.py bm_out): no page preview in the demo (preview "done", no image)
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
  const bmOut = x => ({id: x.id, url: x.url, title: x.title || host(x.url) || x.url, description: x.description || '', site: host(x.url), tags: x.tags || [], note: x.note || '', state: x.state || 'unread',
    image: '', preview: 'done', preview_error: '', has_text: false, src: '', space: 'private', mine: true, can_edit: true, created_at: x.created_at, updated_at: x.updated_at});
  const bmLive = () => mcol('bm').filter(x => !x.deleted_at);
  on('GET', '/api/bookmarks', q => { const s = (q.get('q') || '').toLowerCase(), tag = q.get('tag'), st = q.get('state') || '', off = +q.get('offset') || 0;
    const all = bmLive().filter(x => (st === 'all' || (st ? x.state === st : x.state !== 'archived')) && (!tag || (x.tags || []).includes(tag))
      && (!s || [x.title, x.url, x.description, x.note].join(' ').toLowerCase().includes(s))).sort((a, b) => b.id - a.id);
    const tags = {}; for (const x of bmLive()) for (const t of x.tags || []) tags[t] = (tags[t] || 0) + 1;
    return {items: all.slice(off, off + 50).map(bmOut), more: all.length > off + 50, count: all.length, tags: Object.entries(tags).map(([tag, n]) => ({tag, n})).sort((a, b) => b.n - a.n)}; });
  on('POST', '/api/bookmarks', (q, b) => { const url = String(b.url || '').trim(); if (!/^https?:\/\/\S+$/i.test(url)) bad(tx('Invalid value: {0}').replace('{0}', 'url'));
    const ex = bmLive().find(x => x.url === url); if (ex) return {bookmark: bmOut(ex), existed: true};
    const x = {id: nid('bm'), url, title: String(b.title || ''), tags: [], state: 'unread', created_at: iso(), updated_at: iso(), deleted_at: null}; mcol('bm').push(x); return {bookmark: bmOut(x), existed: false}; });
  on('GET', '/api/bookmarks/(\\d+)', (q, b, id) => ({...bmOut(mfind('bm', id)), text: ''}));
  on('PATCH', '/api/bookmarks/(\\d+)', (q, b, id) => { const x = mfind('bm', id); for (const k of ['title', 'url', 'description', 'note', 'tags', 'state']) if (k in b) x[k] = b[k]; x.updated_at = iso(); return bmOut(x); });
  on('DELETE', '/api/bookmarks/(\\d+)', (q, b, id) => { mfind('bm', id).deleted_at = iso(); return {ok: true, id: +id}; });
  on('POST', '/api/bookmarks/(\\d+)/restore', (q, b, id) => { const x = mfind('bm', id); x.deleted_at = null; return bmOut(x); });
  on('POST', '/api/bookmarks/(\\d+)/refresh', (q, b, id) => bmOut(mfind('bm', id)));

  // ---- workload (kalmido/team/workload.py): one person (the demo has no team), the open tasks with a date and an estimate
  const absDays = (from, to) => { let n = 0; for (const a of mcol('absences').filter(x => !x.deleted_at)) for (let d = from; d <= to; d = addD(d, 1)) {
    const wd = new Date(d + 'T12:00:00').getDay(); if (wd && wd < 6 && d >= a.start_date && d <= a.end_date) n += a.half_day ? 0.5 : 1; } return n; };
  const wlCell = (ts, cap, absent) => { const min = ts.reduce((a, t) => a + (+t.duration || 0), 0), capW = cap * Math.max(0, 5 - absent) / 5, pct = min && capW ? Math.round(min / 60 / capW * 100) : min ? 100 : null;
    return {minutes: min, tasks: ts.length, unestimated: ts.filter(t => !t.duration).length, ids: ts.map(t => t.id), capacity_h: +m2(capW), absent_days: absent, pct, level: !ts.length ? 'none' : pct > 100 ? 'over' : pct > 85 ? 'warn' : 'ok'}; };
  on('GET', '/api/workload', q => { const n = Math.min(12, +q.get('weeks') || 4), st = monday(q.get('start') || today()), cap = num(DB.settings.capacity_h) || 40;
    const weeks = Array.from({length: n}, (_, i) => ({start: addD(st, 7 * i), end: addD(st, 7 * i + 6)}));
    const mine = live().filter(t => t.status === 0 && !t.parent_id && (!t.assignee_id || t.assignee_id === 1));
    return {weeks, org_id: null, orgs: [], today: today(), people: [{id: 1, username: DB.me.username, display_name: DB.me.display_name, avatar: '', capacity_h: cap, own: true,
      weeks: weeks.map(w => wlCell(mine.filter(t => t.due && t.due >= w.start && t.due <= w.end), cap, absDays(w.start, w.end))),
      nodate: (() => { const ts = mine.filter(t => !t.due); return {minutes: ts.reduce((a, t) => a + (+t.duration || 0), 0), tasks: ts.length, unestimated: ts.filter(t => !t.duration).length, ids: ts.map(t => t.id)}; })()}]}; });
  on('PUT', '/api/workload/capacity/(\\d+)', (q, b) => { DB.settings.capacity_h = b.hours == null || b.hours === '' ? '' : String(num(b.hours)); return {id: 1, capacity_h: num(DB.settings.capacity_h) || 40}; });
  // absences (kalmido/hub/absence.py): own ones, holidays of a chosen German state (the nationwide days + Easter based)
  const STATES = {BW: 'Baden-Württemberg', BY: 'Bayern', BE: 'Berlin', BB: 'Brandenburg', HB: 'Bremen', HH: 'Hamburg', HE: 'Hessen', MV: 'Mecklenburg-Vorpommern', NI: 'Niedersachsen',
    NW: 'Nordrhein-Westfalen', RP: 'Rheinland-Pfalz', SL: 'Saarland', SN: 'Sachsen', ST: 'Sachsen-Anhalt', SH: 'Schleswig-Holstein', TH: 'Thüringen'};
  const easter = y => { const a = y % 19, b = Math.floor(y / 100), c = y % 100, d = Math.floor(b / 4), e = b % 4, f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30,
    i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451), mo = Math.floor((h + l - 7 * m + 114) / 31), da = ((h + l - 7 * m + 114) % 31) + 1; return `${y}-${pad(mo)}-${pad(da)}`; };
  const holidays = (from, to) => { if (!MD().state) return []; const out = [];
    for (let y = +from.slice(0, 4); y <= +to.slice(0, 4); y++) { const e = easter(y);
      for (const [d, n] of [[`${y}-01-01`, 'Neujahr'], [addD(e, -2), 'Karfreitag'], [addD(e, 1), 'Ostermontag'], [`${y}-05-01`, 'Tag der Arbeit'], [addD(e, 39), 'Christi Himmelfahrt'],
        [addD(e, 50), 'Pfingstmontag'], [`${y}-10-03`, 'Tag der Deutschen Einheit'], [`${y}-12-25`, '1. Weihnachtstag'], [`${y}-12-26`, '2. Weihnachtstag']]) if (d >= from && d <= to) out.push({date: d, name: n}); }
    return out.sort((a, b) => a.date.localeCompare(b.date)); };
  const absOut = a => ({id: a.id, user_id: 1, start_date: a.start_date, end_date: a.end_date, half_day: a.half_day || '', kind: a.kind || 'vacation', note: a.note || '', can_edit: true});
  const absSet = (a, b) => { for (const k of ['kind', 'start_date', 'end_date', 'half_day', 'note']) if (k in b) a[k] = b[k]; if (!a.end_date) a.end_date = a.start_date;
    if (!/^\d{4}-\d\d-\d\d$/.test(a.start_date || '') || a.end_date < a.start_date) bad(tx('Invalid value: {0}').replace('{0}', 'date')); };
  on('GET', '/api/team/absences', q => { const st = q.get('start') || today().slice(0, 8) + '01', en = q.get('end') || monthEnd(today().slice(0, 7));
    return {org_id: null, orgs: [], personal: 1, admin: true, state: MD().state || '', states: STATES, today: today(), start: st, end: en,
      people: [{id: 1, username: DB.me.username, display_name: DB.me.display_name, avatar: '', own: true}],
      items: mcol('absences').filter(a => !a.deleted_at && a.end_date >= st && a.start_date <= en).map(absOut), holidays: holidays(st, en)}; });
  on('GET', '/api/team/absences/check', q => { const d = q.get('date') || today(), a = mcol('absences').find(x => !x.deleted_at && d >= x.start_date && d <= x.end_date);
    return a ? {absent: true, half_day: a.half_day || '', until: a.end_date} : {absent: false}; });
  on('PUT', '/api/team/absences/holidays', (q, b) => { MD().state = STATES[b.state] ? b.state : ''; return {org_id: null, state: MD().state}; });
  on('POST', '/api/team/absences', (q, b) => { const a = {id: nid('absences'), deleted_at: null}; absSet(a, b); mcol('absences').push(a); return absOut(a); });
  on('PATCH', '/api/team/absences/(\\d+)', (q, b, id) => { const a = mfind('absences', id); absSet(a, b); return absOut(a); });
  on('DELETE', '/api/team/absences/(\\d+)', (q, b, id) => { mfind('absences', id).deleted_at = iso(); return {ok: true}; });
  on('POST', '/api/team/absences/(\\d+)/restore', (q, b, id) => { const a = mfind('absences', id); a.deleted_at = null; return absOut(a); });
  // 2.125.0 (#2117 #2118): the vacation account + the working week of the one person (a personal area: its own admin, no
  // requests -- every vacation is approved at once, like kalmido/hub/leave.py for a person without an organisation)
  const wtDays = () => (MD().workdays ?? '0,1,2,3,4').split(',').filter(x => x !== '').map(Number);
  const lvCount = (s, e, half, wd, hol) => { let n = 0; for (let d = s; d <= e; d = addD(d, 1)) { const w = (new Date(d + 'T12:00:00Z').getUTCDay() + 6) % 7;
    if (wd.includes(w) && !hol.has(d)) n += half ? 0.5 : 1; } return n; };
  const lvAcc = year => { const y0 = `${year}-01-01`, y1 = `${year}-12-31`, q = (MD().quota || {})[year] || null, hol = new Set(holidays(y0, y1).map(h => h.date));
    const taken = mcol('absences').filter(a => !a.deleted_at && (a.kind || 'vacation') === 'vacation' && a.end_date >= y0 && a.start_date <= y1)
      .reduce((s, a) => s + lvCount(a.start_date < y0 ? y0 : a.start_date, a.end_date > y1 ? y1 : a.end_date, a.half_day, wtDays(), hol), 0);
    return {quota: q, taken, requested: 0, rest: q ? q.days + (q.carry || 0) - taken : null}; };
  const capH = () => +(DB.settings?.capacity_h || MD().capacity_h || 0) || 40;
  on('GET', '/api/team/leave', q => { const year = +(q.get('year') || today().slice(0, 4));
    return {org_id: null, year, admin: true, personal: true, approval: false, pending: [],
      people: [{id: 1, display_name: DB.me.display_name || DB.me.username, own: true, workdays: wtDays(), capacity_h: capH(), capacity_set: !!MD().capacity_h, ...lvAcc(year)}]}; });
  on('PUT', '/api/team/leave/quota', (q, b) => { const year = +b.year, m = MD().quota = MD().quota || {};
    if (b.days === null || b.days === '' || b.days === undefined) delete m[year]; else m[year] = {days: +b.days || 0, carry: +b.carry || 0};
    return {org_id: null, user_id: 1, year, quota: m[year] || null}; });
  on('PUT', '/api/team/leave/approval', () => bad(tx('Only admins of the organisation can change this')));
  on('PUT', '/api/team/leave/worktime/(\\d+)', (q, b) => { if ('workdays' in b) MD().workdays = Array.isArray(b.workdays) ? b.workdays.join(',') : String(b.workdays || '');
    if ('hours' in b) MD().capacity_h = b.hours === null ? '' : String(b.hours); return {id: 1, workdays: wtDays(), capacity_h: capH(), capacity_set: !!MD().capacity_h}; });
  on('POST', '/api/team/absences/(\\d+)/decide', (q, b, id) => absOut(mfind('absences', id)));
  // 2.125.0 (#2119): the monthly timesheet of the one person (no organisation: closing locks, no approval step)
  const tslOut = m => { const r = (MD().sheets || {})[m]; return r ? {state: r.state, note: '', closed_at: r.closed_at, decided_at: null, decided_by: null,
    decided_by_name: '', org_id: null, org_name: '', log: [], user_id: 1} : {state: 'open', note: '', closed_at: null, decided_at: null, decided_by: null, decided_by_name: '', org_id: null, org_name: '', log: []}; };
  on('GET', '/api/time/sheets', q => { const m = /^\d{4}-\d\d$/.test(q.get('month') || '') ? q.get('month') : today().slice(0, 7), st = tslOut(m).state;
    return {month: m, sheet: tslOut(m), locked: Object.keys(MD().sheets || {}).sort(), can: {close: st === 'open' && m <= today().slice(0, 7), reopen: st !== 'open'}, org: false, review: []}; });
  on('POST', '/api/time/sheets', (q, b) => { const m = b.month, s = MD().sheets = MD().sheets || {};
    if (!/^\d{4}-\d\d$/.test(m || '')) bad(tx('Invalid value: {0}').replace('{0}', 'month'));
    if (b.action === 'close') s[m] = {state: 'closed', closed_at: iso()}; else delete s[m]; return {ok: true, month: m, sheet: tslOut(m)}; });
  on('POST', '/api/time/sheets/decide', () => bad(tx('Only admins of the organisation can change this')));
  // disposition (kalmido/hub/dispo.py): the person, the contacts and the office's equipment as resources
  const dpRes = () => ({people: [{kind: 'user', id: 1, name: DB.me.display_name, avatar: ''}], contacts: liveCt().slice(0, 50).map(c => ({kind: 'contact', id: c.id, name: ctFn(c)})),
    equipment: mcol('of_equipment').filter(x => !x.deleted_at && !x.archived).map(x => ({kind: 'equipment', id: x.id, name: x.name, category: x.category || ''})),
    sets: mcol('of_sets').filter(x => !x.deleted_at && !x.archived).map(x => ({kind: 'set', id: x.id, name: x.name, items: (x.items || []).map(i => i.equipment_id)}))});
  const resName = (k, id) => (dpRes()[{user: 'people', contact: 'contacts', equipment: 'equipment', set: 'sets'}[k]] || []).find(r => r.id === +id)?.name || '?';
  const bkLive = () => mcol('bookings').filter(x => !x.deleted_at);
  const bkOut = x => ({id: x.id, job: x.job, title: x.title, start: x.start, end: x.end, kind: x.kind, rid: x.rid, label: resName(x.kind, x.rid), status: x.status || 'option', note: x.note || '',
    list_id: x.list_id || null, event_id: null, conflicts: bkLive().filter(o => o.id !== x.id && o.kind === x.kind && o.rid === x.rid && o.start.slice(0, 10) <= x.end.slice(0, 10) && o.end.slice(0, 10) >= x.start.slice(0, 10)).map(o => o.id),
    away: x.kind === 'user' && absDays(x.start.slice(0, 10), x.end.slice(0, 10)) > 0});
  const awayMap = (from, to) => { const m = {}; for (let d = from; d <= to; d = addD(d, 1)) { const a = mcol('absences').find(x => !x.deleted_at && d >= x.start_date && d <= x.end_date); if (a) (m['1'] = m['1'] || {})[d] = a.half_day ? 0.5 : 1; } return m; };
  on('GET', '/api/team/dispo', q => { const st = q.get('start') || monday(), en = addD(st, (+q.get('days') || 7) - 1);
    return {org_id: null, orgs: [], can_book: true, admin: true, today: today(), start: st, end: en, resources: dpRes(),
      bookings: bkLive().filter(x => x.end.slice(0, 10) >= st && x.start.slice(0, 10) <= en).map(bkOut), away: awayMap(st, en), holidays: holidays(st, en)}; });
  on('GET', '/api/team/bookings/mine', () => ({bookings: bkLive().filter(x => x.kind === 'user' && x.rid === 1 && x.end >= today()).map(x => ({...bkOut(x), org: ''}))}));
  on('GET', '/api/team/dispo/free', q => { const d = q.get('date') || today(), busy = bkLive().filter(x => x.start.slice(0, 10) <= d && x.end.slice(0, 10) >= d), r = dpRes(), free = (k, arr) => arr.filter(x => !busy.some(b => b.kind === k && b.rid === x.id));
    return {date: d, people: free('user', r.people), contacts: free('contact', r.contacts), equipment: free('equipment', r.equipment), sets: free('set', r.sets), away: Object.keys(awayMap(d, d)).map(Number)}; });
  on('POST', '/api/team/dispo/bookings', (q, b) => { if (!String(b.title || '').trim()) bad(tx('Please enter a title')); const job = 'j' + nid('bookjob');
    const made = (b.resources || []).map(r => { const x = {id: nid('bookings'), job, title: String(b.title).trim(), start: b.start || today(), end: b.end || b.start || today(), kind: r.kind, rid: +r.id, status: b.status || 'option', note: b.note || '', list_id: b.list_id || null, deleted_at: null}; mcol('bookings').push(x); return x; });
    const out = made.map(bkOut); return {bookings: out, warnings: out.filter(x => x.conflicts.length || x.away).length}; });
  on('PATCH', '/api/team/dispo/bookings/(\\d+)', (q, b, id) => { const x0 = mfind('bookings', id), xs = b.all ? bkLive().filter(x => x.job === x0.job) : [x0];
    for (const x of xs) for (const k of ['title', 'start', 'end', 'status', 'note']) if (k in b) x[k] = b[k]; return {bookings: xs.map(bkOut)}; });
  on('DELETE', '/api/team/dispo/bookings/(\\d+)', (q, b, id) => { const x0 = mfind('bookings', id), xs = q.get('all') === '1' ? bkLive().filter(x => x.job === x0.job) : [x0]; xs.forEach(x => { x.deleted_at = iso(); }); return {ids: xs.map(x => x.id)}; });
  on('POST', '/api/team/dispo/bookings/restore', (q, b) => { let n = 0; for (const id of b.ids || []) { const x = mcol('bookings').find(y => y.id === +id); if (x) { x.deleted_at = null; n++; } } return {restored: n}; });

  // ---- knowledge pages (kalmido/wiki/pages.py): one private space, links [[Path]], backlinks, rename relinks, trash
  const wkClean = p => String(p || '').trim().replace(/\.md$/i, '').split('/').map(s => s.replace(/[[\]|#^\\]/g, '').trim()).filter(Boolean).join('/');
  const wkLive = () => mcol('wiki').filter(p => !p.deleted_at);
  const wkAttrs = body => { const m = /^---\n([\s\S]*?)\n---/.exec(body || ''), o = {}; if (m) for (const l of m[1].split('\n')) { const i = l.indexOf(':'); if (i > 0) o[l.slice(0, i).trim()] = l.slice(i + 1).trim(); } return o; };
  const wkOut = (p, body) => ({id: p.id, space: 'private', org_id: null, path: p.path, attrs: wkAttrs(p.body), created_by: 1, updated_by: 1, created_at: p.created_at, updated_at: p.updated_at,
    template: /^(Templates|Vorlagen)\//.test(p.path), updated_by_name: DB.me.display_name, shared: 0, ...(body ? {body: p.body || ''} : {})});
  const wkLinks = p => { const re = new RegExp('\\[\\[' + p.path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(\\]\\]|\\||#)', 'i'); return wkLive().filter(o => o.id !== p.id && re.test(o.body || '')).map(o => ({id: o.id, path: o.path})); };
  const wkFull = p => ({...wkOut(p, true), backlinks: wkLinks(p), moved: null, files: [], shares: 0});
  const wkTaken = (path, not) => wkLive().some(o => o.id !== not && o.path.toLowerCase() === path.toLowerCase());
  const wkRelink = (from, to, not) => { let n = 0; const re = new RegExp('\\[\\[' + from.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '(?=\\]\\]|\\||#)', 'gi');
    for (const o of wkLive()) if (o.id !== not && re.test(o.body || '')) { o.body = o.body.replace(re, '[[' + to); n++; } return n; };
  on('GET', '/api/wiki', q => ({space: 'private', may_write: true, e2e: null, pages: wkLive().sort((a, b) => a.path.localeCompare(b.path)).map(p => wkOut(p, q.get('bodies') === '1'))}));
  on('GET', '/api/wiki/shared', () => ({pages: []}));
  on('GET', '/api/wiki/search', q => { const s = (q.get('q') || '').toLowerCase(); return {pages: wkLive().filter(p => (p.path + ' ' + p.body).toLowerCase().includes(s)).map(p => wkOut(p))}; });
  on('GET', '/api/wiki/mentions', q => ({pages: wkLive().filter(p => new RegExp('#' + (+q.get('task') || 0) + '\\b').test(p.body || '')).map(p => ({id: p.id, path: p.path}))}));
  on('GET', '/api/wiki/pages/(\\d+)', (q, b, id) => { const p = mfind('wiki', id); if (p.deleted_at) gone(); return wkFull(p); });
  on('POST', '/api/wiki/pages', (q, b) => { const path = wkClean(b.path); if (!path) bad(tx('Please enter a name')); if (wkTaken(path)) throw new Http(409, {error: tx('Folder already exists')});
    const tpl = b.template_id ? mcol('wiki').find(x => x.id === +b.template_id) : null;
    const p = {id: nid('wiki'), path, body: String(b.body || (tpl ? tpl.body : '') || ''), created_at: iso(), updated_at: iso(), deleted_at: null}; mcol('wiki').push(p); return {...wkOut(p, true), moved: null, files: [], shares: 0}; });
  on('PATCH', '/api/wiki/pages/(\\d+)', (q, b, id) => { const p = mfind('wiki', id);
    if (b.expect_updated_at && b.expect_updated_at !== p.updated_at) throw new Http(409, {error: tx('Changed in the meantime'), page: wkFull(p)});
    let relinked = 0;
    if ('path' in b) { const to = wkClean(b.path); if (!to) bad(tx('Please enter a name')); if (wkTaken(to, p.id)) throw new Http(409, {error: tx('Folder already exists')}); relinked = wkRelink(p.path, to, p.id); p.path = to; }
    if ('body' in b) p.body = String(b.body || ''); p.updated_at = iso(); return {...wkFull(p), relinked}; });
  on('POST', '/api/wiki/move', (q, b) => { const from = wkClean(b.from), to = wkClean(b.to), moved = []; let relinked = 0;
    for (const p of wkLive()) if (p.path === from || p.path.startsWith(from + '/')) { const np = to + p.path.slice(from.length); relinked += wkRelink(p.path, np, p.id); moved.push({id: p.id, from: p.path, to: np}); p.path = np; p.updated_at = iso(); }
    return {ok: true, moved, relinked}; });
  on('DELETE', '/api/wiki/pages/(\\d+)', (q, b, id) => { const p = mfind('wiki', id); p.deleted_at = iso(); return {ok: true, page: wkOut(p, true)}; });
  on('POST', '/api/wiki/trash', (q, b) => { const ids = []; for (const id of b.ids || []) { const p = mcol('wiki').find(x => x.id === +id); if (p) { p.deleted_at = iso(); ids.push(p.id); } } return {ok: true, ids, skipped: [], files: [], files_skipped: []}; });
  on('POST', '/api/wiki/restore', (q, b) => { const ids = [], skipped = []; for (const id of b.ids || []) { const p = mcol('wiki').find(x => x.id === +id); if (!p) continue; if (wkTaken(p.path, p.id)) skipped.push(p.id); else { p.deleted_at = null; ids.push(p.id); } }
    return {ok: true, ids, skipped, files: [], files_skipped: []}; });
  on('POST', '/api/wiki/pages/(\\d+)/refs', () => ({files: {}, links: {}}));

  // ---- tables (kalmido/sheets): the grid, cell names, freezing; formulas evaluated here for the common cases (numbers, text, + - * / & %,
  // comparisons, A1 / A1:B5 / names, SUM AVERAGE MIN MAX COUNT IF ROUND TODAY DAYS with their German names); other functions and
  // Kalmido variables answer with a clear "only in your own Kalmido" text in the cell
  const shLetter = i => { let s = ''; i++; while (i) { const r = (i - 1) % 26; s = String.fromCharCode(65 + r) + s; i = Math.floor((i - 1) / 26); } return s; };
  const shNew = (b = {}) => { const sh = {id: nid('sheets'), title: String(b.title || '').trim() || tx('Table'), list_id: b.list_id || null, cols: [], rows: [], cells: {}, rev: 1, created_at: iso(), updated_at: iso(), deleted_at: null, freeze_rows: 0, freeze_cols: 0, chart: null};
    for (let i = 0; i < 3; i++) sh.cols.push({id: nid('shcol'), pos: i + 1, title: '', kind: 'text', options: [], color_mode: 'cell', width: null, deleted_at: null});
    for (let i = 0; i < 10; i++) sh.rows.push({id: nid('shrow'), pos: i + 1, deleted_at: null}); return sh; };
  const shGet = id => { const s = mfind('sheets', id); if (s.deleted_at) gone(); return s; };
  const SH_ERR = {syntax: 'Formula error', div0: 'Division by zero', ref: 'Reference not found', type: 'Wrong type of value', cycle: 'Circular reference', na: 'Not found', deleted: 'Source deleted', denied: 'No access'};
  class ShErr { constructor(k, text) { this.k = k; this.text = text; } }
  const SH_FN = {SUM: 'SUM', SUMME: 'SUM', AVERAGE: 'AVG', MITTELWERT: 'AVG', MIN: 'MIN', MAX: 'MAX', COUNT: 'COUNT', ANZAHL: 'COUNT', IF: 'IF', WENN: 'IF', ROUND: 'ROUND', RUNDEN: 'ROUND', TODAY: 'TODAY', HEUTE: 'TODAY', DAYS: 'DAYS', TAGE: 'DAYS'};
  const shNum = v => { if (v == null || v === '') return 0; if (typeof v === 'number') return v; if (typeof v === 'boolean') return v ? 1 : 0; if (v && v.date) return Date.parse(v.date + 'T12:00:00Z') / 864e5;
    const n = num(v); if (/^\s*-?[\d.,]+\s*%?\s*€?\s*$/.test(String(v))) return String(v).includes('%') ? n / 100 : n; throw new ShErr('type'); };
  function shPlain(raw, col) {
    const k = col.kind, s = String(raw);
    if (k === 'select') { const o = (col.options || []).find(x => String(x.id) === s); return o ? o.label : s; }
    if (k === 'date') { const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(s.trim()); const d = m ? `${m[3]}-${pad(+m[2])}-${pad(+m[1])}` : /^\d{4}-\d\d-\d\d$/.test(s.trim()) ? s.trim() : null; return d ? {date: d} : s; }
    if (/^\s*[+-]?[\d.,]+\s*(%|€|EUR)?\s*$/.test(s)) { const n = num(s); return k === 'percent' || s.includes('%') ? n / 100 : n; }
    if (k === 'checkbox') return s === '1' || s.toLowerCase() === 'true';
    return s;
  }
  function shTokens(f) {
    const out = [], semi = f.includes(';'); let i = 0;
    while (i < f.length) { const c = f[i];
      if (/\s/.test(c)) { i++; continue; }
      let m = /^(\d+(?:[.,]\d+)?)/.exec(f.slice(i)); if (m && (semi || !m[1].includes(','))) { out.push(['n', +m[1].replace(',', '.')]); i += m[1].length; continue; }
      if (m) { out.push(['n', +m[1].split(',')[0]]); i += m[1].split(',')[0].length; continue; }
      if (c === '"') { const j = f.indexOf('"', i + 1); if (j < 0) throw new ShErr('syntax'); out.push(['s', f.slice(i + 1, j)]); i = j + 1; continue; }
      m = /^(<=|>=|<>|[-+*/&=<>%():;,])/.exec(f.slice(i)); if (m) { out.push(['o', m[1] === ';' ? ',' : m[1]]); i += m[1].length; continue; }
      m = /^\$?[A-Za-zÄÖÜäöüß_][\wÄÖÜäöüß.$]*/.exec(f.slice(i)); if (m) { out.push(['w', m[0]]); i += m[0].length; continue; }
      throw new ShErr('syntax'); }
    return out;
  }
  function shEval(sh) {
    const cols = sh.cols.filter(c => !c.deleted_at).sort((a, b) => a.pos - b.pos), rows = sh.rows.filter(r => !r.deleted_at).sort((a, b) => a.pos - b.pos);
    const colOf = Object.fromEntries(cols.map((c, i) => [shLetter(i), c])), res = {}, busy = new Set();
    const names = {}; for (const [k, c] of Object.entries(sh.cells)) if (c.name) names[c.name.toLowerCase()] = k;
    const keyOf = a => { const m = /^\$?([A-Z]+)\$?(\d+)$/.exec(a.toUpperCase()); if (!m) return null; const c = colOf[m[1]], r = rows[+m[2] - 1]; if (!c || !r) throw new ShErr('ref'); return r.id + ':' + c.id; };
    const val = (k, refs) => { const c = sh.cells[k]; if (c) refs.add(c.id); if (!c || !String(c.raw ?? '').length) return null; const r = calc(k); if (r.err) throw new ShErr(r.err.k, r.err.text); return r.v; };
    function calc(k) {
      if (res[k]) return res[k];
      const c = sh.cells[k], [rid, cid] = k.split(':').map(Number), col = sh.cols.find(x => x.id === cid);
      if (c.frozen) return (res[k] = {v: c.fv ?? null, refs: []});
      const raw = String(c.raw ?? '');
      if (!raw.startsWith('=')) return (res[k] = {v: shPlain(raw, col || {kind: 'text'}), refs: [], plain: true});
      if (busy.has(k)) throw new ShErr('cycle');
      busy.add(k); const refs = new Set();
      try {
        const tk = shTokens(raw.slice(1)); let p = 0;
        const peek = () => tk[p], take = o => { if (tk[p] && tk[p][0] === 'o' && tk[p][1] === o) { p++; return true; } return false; };
        const need = o => { if (!take(o)) throw new ShErr('syntax'); };
        const range = (a, b) => { const ka = keyOf(a), kb = keyOf(b); const [r1, c1] = ka.split(':').map(Number), [r2, c2] = kb.split(':').map(Number);
          const ri = [rows.findIndex(r => r.id === r1), rows.findIndex(r => r.id === r2)].sort((x, y) => x - y), ci = [cols.findIndex(x => x.id === c1), cols.findIndex(x => x.id === c2)].sort((x, y) => x - y), out = [];
          for (let i = ri[0]; i <= ri[1]; i++) for (let j = ci[0]; j <= ci[1]; j++) out.push(val(rows[i].id + ':' + cols[j].id, refs)); return {range: out}; };
        const prim = () => { const t = tk[p++]; if (!t) throw new ShErr('syntax');
          if (t[0] === 'n' || t[0] === 's') return t[1];
          if (t[0] === 'o' && t[1] === '(') { const v = expr(); need(')'); return v; }
          if (t[0] !== 'w') throw new ShErr('syntax');
          const w = t[1], W = w.toUpperCase().replace(/\$/g, '');
          if (['TRUE', 'WAHR'].includes(W)) return true; if (['FALSE', 'FALSCH'].includes(W)) return false;
          if (take('(')) { const args = []; if (!take(')')) { do { args.push(expr()); } while (take(',')); need(')'); } return fn(W, args); }
          if (/^[A-Z]+\d+$/.test(W)) { if (take(':')) { const t2 = tk[p++]; if (!t2 || t2[0] !== 'w') throw new ShErr('syntax'); return range(W, t2[1].replace(/\$/g, '')); } return val(keyOf(W), refs); }
          if (names[w.toLowerCase()]) return val(names[w.toLowerCase()], refs);
          if (/^(projekt|liste|kunde|hier|aufgabe|project|list|client|here|task)\./i.test(w)) throw new ShErr('denied', T().sheetVar);
          throw new ShErr('ref'); };
        const unary = () => { if (take('-')) return -shNum(unary()); if (take('+')) return shNum(unary()); let v = prim(); while (take('%')) v = shNum(v) / 100; return v; };
        const mul = () => { let v = unary(); for (;;) { if (take('*')) v = shNum(v) * shNum(unary()); else if (take('/')) { const d = shNum(unary()); if (!d) throw new ShErr('div0'); v = shNum(v) / d; } else return v; } };
        const add = () => { let v = mul(); for (;;) { if (take('+')) { const r = mul(); v = v && v.date ? {date: addD(v.date, shNum(r))} : shNum(v) + shNum(r); } else if (take('-')) { const r = mul(); v = v && v.date ? (r && r.date ? shNum(v) - shNum(r) : {date: addD(v.date, -shNum(r))}) : shNum(v) - shNum(r); } else return v; } };
        const txt = v => v == null ? '' : v.date ? v.date : typeof v === 'boolean' ? (v ? 'TRUE' : 'FALSE') : String(v);
        const cat = () => { let v = add(); while (take('&')) v = txt(v) + txt(add()); return v; };
        const cmp = (a, o, b) => { const x = typeof a === 'string' || typeof b === 'string' ? [txt(a).toLowerCase(), txt(b).toLowerCase()] : [shNum(a), shNum(b)];
          return {'=': x[0] === x[1], '<>': x[0] !== x[1], '<': x[0] < x[1], '>': x[0] > x[1], '<=': x[0] <= x[1], '>=': x[0] >= x[1]}[o]; };
        function expr() { const a = cat(), t = peek(); if (t && t[0] === 'o' && ['=', '<>', '<', '>', '<=', '>='].includes(t[1])) { p++; return cmp(a, t[1], cat()); } return a; }
        function fn(W, args) {
          const f = SH_FN[W]; if (!f) throw new ShErr('syntax', T().sheetFn);
          const flat = () => args.flatMap(a => a && a.range ? a.range.filter(v => typeof v === 'number' || (v && v.date)).map(shNum) : [shNum(a)]);
          if (f === 'SUM') return flat().reduce((a, b) => a + b, 0);
          if (f === 'AVG') { const xs = flat(); if (!xs.length) throw new ShErr('div0'); return xs.reduce((a, b) => a + b, 0) / xs.length; }
          if (f === 'MIN' || f === 'MAX') { const xs = flat(); return xs.length ? Math[f.toLowerCase()](...xs) : 0; }
          if (f === 'COUNT') return args.flatMap(a => a && a.range ? a.range : [a]).filter(v => typeof v === 'number' || (v && v.date)).length;
          if (f === 'IF') return (args[0] && args[0].range ? false : shNum(args[0])) ? args[1] ?? true : args[2] ?? false;
          if (f === 'ROUND') { const d = Math.round(shNum(args[1] ?? 0)), m = 10 ** d, x = shNum(args[0]); return Math.sign(x) * Math.round(Math.abs(x) * m + 1e-9) / m; }
          if (f === 'TODAY') return {date: today()};
          if (f === 'DAYS') return Math.round(shNum(args[0]) - shNum(args[1]));
          throw new ShErr('syntax');
        }
        const v = expr(); if (p < tk.length) throw new ShErr('syntax');
        if (v && v.range) throw new ShErr('type');
        return (res[k] = {v, refs: [...refs]});
      } catch (e) { if (!(e instanceof ShErr)) throw e; if (e.k === 'cycle' && !busy.has(k)) throw e; return (res[k] = {err: e, refs: [...refs]}); }
      finally { busy.delete(k); }
    }
    for (const k of Object.keys(sh.cells)) { try { calc(k); } catch (e) { if (e instanceof ShErr) res[k] = {err: e, refs: []}; else throw e; } }
    return {res, cols, rows};
  }
  // kalmido/sheets/formula.py sh_fmt_number / sh_fmt_currency / sh_fmt_date (up to 4 decimals, thousands per language)
  const shFmt = (v, kind, cur) => { const lg = DB.settings.lang || 'en', en = lg === 'en';
    const nf = (n, dec) => { let t = Math.abs(n).toFixed(dec ?? 4); if (dec == null) t = t.replace(/0+$/, '').replace(/\.$/, ''); const [w, f] = t.split('.'), th = en ? ',' : lg === 'fr' ? ' ' : '.';
      const r = w.replace(/\B(?=(\d{3})+(?!\d))/g, th) + (f ? (en ? '.' : ',') + f : ''); return (n < 0 && +t ? '-' : '') + r; };
    if (v == null) return ''; if (v.date) { const [y, m, d] = v.date.split('-'); return en ? v.date : ['fr', 'es', 'it'].includes(lg) ? `${d}/${m}/${y}` : lg === 'nl' ? `${d}-${m}-${y}` : `${d}.${m}.${y}`; }
    if (typeof v === 'boolean') return tx(v ? 'Yes' : 'No');
    if (typeof v !== 'number') return String(v);
    if (kind === 'currency') { const sym = {EUR: '€', USD: '$', GBP: '£', CHF: 'CHF'}[cur] || cur || '€', s = nf(Math.abs(v), 2), neg = v < 0 && Math.round(Math.abs(v) * 100) ? '-' : ''; return en ? `${neg}${sym}${s}` : `${neg}${s} ${sym}`; }
    if (kind === 'percent') { const s = nf(v * 100); return en ? `${s}%` : `${s} %`; }
    return nf(v); };
  function shOut(sh) {
    const {res, cols, rows} = shEval(sh), idOf = {}, cells = [];
    for (const [k, c] of Object.entries(sh.cells)) idOf[c.id] = k;
    for (const [k, c] of Object.entries(sh.cells)) {
      if (!String(c.raw ?? '').length && !c.name && !c.frozen) continue;
      const [rid, cid] = k.split(':').map(Number), col = sh.cols.find(x => x.id === cid) || {kind: 'text'}, ri = rows.findIndex(r => r.id === rid), ci = cols.findIndex(x => x.id === cid), r = res[k] || {v: null, refs: []};
      if (ri < 0 || ci < 0) continue;
      const v = r.err ? null : r.v, vtype = r.err || v == null || v === '' ? 'empty' : typeof v === 'number' ? 'number' : typeof v === 'boolean' ? 'bool' : v.date ? 'date' : 'text';
      const etext = r.err ? r.err.text || tx(SH_ERR[r.err.k] || 'Formula error') : null;
      cells.push({id: c.id, row_id: rid, col_id: cid, addr: shLetter(ci) + (ri + 1), raw: String(c.raw ?? ''), name: c.name || null, frozen: !!c.frozen, agent: null, updated_by: 1, updated_by_name: DB.me.display_name,
        updated_at: c.updated_at, option: col.kind === 'select' && (col.options || []).some(o => String(o.id) === String(c.raw)) ? c.raw : null,
        value: v && v.date ? v.date : v === '' ? null : v, vtype, display: r.err ? etext : col.kind === 'text' && r.plain ? String(c.raw) : shFmt(v, col.kind, sh.currency || 'EUR'),
        origin: c.frozen ? 'frozen' : String(c.raw).startsWith('=') ? 'formula' : 'own', error: r.err ? r.err.k : null, error_text: etext, last_value: null, refs: (r.refs || []).filter(x => idOf[x]), sources: []});
    }
    return {id: sh.id, title: sh.title, space: 'private', org_id: null, list_id: sh.list_id, list_title: sh.list_id ? listById(sh.list_id)?.name || null : null, can_write: true, currency: sh.currency || 'EUR',
      columns: cols.map((c, i) => ({id: c.id, pos: c.pos, title: c.title, kind: c.kind, options: c.options || [], color_mode: c.color_mode || 'cell', width: c.width ?? null, letter: shLetter(i)})),
      rows: rows.map(r => ({id: r.id, pos: r.pos})), cells, names: Object.fromEntries(Object.values(sh.cells).filter(c => c.name).map(c => [c.name, c.id])), presence: [], sources: [], batches: [], rev: sh.rev,
      deleted_at: null, updated_at: sh.updated_at, freeze_rows: sh.freeze_rows || 0, freeze_cols: sh.freeze_cols || 0, agent: null, chart: sh.chart || null, book_id: sh.id, book_title: sh.title, tab_name: sh.title,
      tabs: [{id: sh.id, name: sh.title, pos: 0, first: true}], moved: null, shared_in: false, can_share: false, shared: 0};
  }
  const shBrief = s => ({id: s.id, title: s.title, space: 'private', list_id: s.list_id, list_title: s.list_id ? listById(s.list_id)?.name || null : null, updated_at: s.updated_at, updated_by_name: DB.me.display_name,
    agent: null, shared: 0, shared_in: false, sheets: 1});
  const shBump = s => { s.rev++; s.updated_at = iso(); return {ok: true, rev: s.rev}; };
  on('GET', '/api/sheets', q => ({sheets: mcol('sheets').filter(s => !s.deleted_at && (!q.get('list_id') || s.list_id === +q.get('list_id'))).sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(shBrief)}));
  on('POST', '/api/sheets', (q, b) => { const s = shNew(b); mcol('sheets').push(s); return shOut(s); });
  on('GET', '/api/sheets/(\\d+)', (q, b, id) => shOut(shGet(id)));
  on('PATCH', '/api/sheets/(\\d+)', (q, b, id) => { const s = shGet(id); for (const k of ['title', 'list_id', 'freeze_rows', 'freeze_cols', 'chart', 'currency']) if (k in b) s[k] = b[k]; shBump(s); return shOut(s); });
  on('DELETE', '/api/sheets/(\\d+)', (q, b, id) => { const s = shGet(id); s.deleted_at = iso(); return shBump(s); });
  on('POST', '/api/sheets/(\\d+)/restore', (q, b, id) => { const s = mfind('sheets', id); s.deleted_at = null; return shBump(s); });
  on('GET', '/api/sheets/(\\d+)/links', () => ({links: [], lists: [], office: false, clients: [], row_lists: []}));
  on('GET', '/api/sheets/(\\d+)/vars', () => ({vars: []}));
  on('POST', '/api/sheets/(\\d+)/presence', () => ({ok: true, seconds: 15}));
  on('PUT', '/api/sheets/(\\d+)/cells', (q, b, id) => { const s = shGet(id), gone0 = [];
    for (const x of b.cells || []) { const k = (+x.row_id) + ':' + (+x.col_id); if (!s.rows.some(r => r.id === +x.row_id) || !s.cols.some(c => c.id === +x.col_id)) bad(tx('Reference not found'));
      const c = s.cells[k] || (s.cells[k] = {id: nid('shcell'), raw: '', name: null, frozen: false}); c.raw = String(x.raw ?? ''); c.updated_at = iso();
      if (!c.raw && !c.name && !c.frozen) { gone0.push({id: c.id, row_id: +x.row_id, col_id: +x.col_id, raw: '', name: null, frozen: false}); delete s.cells[k]; } }
    shBump(s); return {cells: [...shOut(s).cells, ...gone0], rev: s.rev}; });
  on('POST', '/api/sheets/(\\d+)/rows', (q, b, id) => { const s = shGet(id), live0 = s.rows.filter(r => !r.deleted_at).sort((a, c) => a.pos - c.pos), at = b.after_row_id ? live0.findIndex(r => r.id === +b.after_row_id) + 1 : live0.length, ids = [];
    const n = Math.min(100, Math.max(1, +b.count || 1)), news = Array.from({length: n}, () => { const r = {id: nid('shrow'), pos: 0, deleted_at: null}; ids.push(r.id); return r; });
    live0.splice(at, 0, ...news); live0.forEach((r, i) => { r.pos = i + 1; }); s.rows.push(...news); return {...shBump(s), ids}; });
  on('DELETE', '/api/sheets/(\\d+)/rows/(\\d+)', (q, b, id, rid) => { const s = shGet(id), r = s.rows.find(x => x.id === +rid) || gone(); r.deleted_at = iso(); return shBump(s); });
  on('POST', '/api/sheets/(\\d+)/rows/(\\d+)/restore', (q, b, id, rid) => { const s = shGet(id), r = s.rows.find(x => x.id === +rid) || gone(); r.deleted_at = null; return shBump(s); });
  on('POST', '/api/sheets/(\\d+)/rows/order', (q, b, id) => { const s = shGet(id), ids = (b.ids || []).map(Number), rest = s.rows.filter(r => !ids.includes(r.id)).sort((a, c) => a.pos - c.pos);
    [...ids.map(i => s.rows.find(r => r.id === i)).filter(Boolean), ...rest].forEach((r, i) => { r.pos = i + 1; }); return shBump(s); });
  const colOut = (s, c) => shOut(s).columns.find(x => x.id === c.id) || {...c};
  on('POST', '/api/sheets/(\\d+)/columns', (q, b, id) => { const s = shGet(id), live0 = s.cols.filter(c => !c.deleted_at).sort((a, c) => a.pos - c.pos), at = b.after_col_id ? live0.findIndex(c => c.id === +b.after_col_id) + 1 : live0.length;
    const c = {id: nid('shcol'), pos: 0, title: String(b.title || ''), kind: b.kind || 'text', options: [], color_mode: 'cell', width: null, deleted_at: null}; live0.splice(at, 0, c); live0.forEach((x, i) => { x.pos = i + 1; }); s.cols.push(c);
    shBump(s); return {column: colOut(s, c), rev: s.rev}; });
  on('PATCH', '/api/sheets/(\\d+)/columns/(\\d+)', (q, b, id, cid) => { const s = shGet(id), c = s.cols.find(x => x.id === +cid) || gone();
    for (const k of ['title', 'kind', 'options', 'color_mode', 'width']) if (k in b) c[k] = b[k];
    if ('pos' in b) { const live0 = s.cols.filter(x => !x.deleted_at && x !== c).sort((a, x) => a.pos - x.pos); live0.splice(Math.max(0, +b.pos - 1), 0, c); live0.forEach((x, i) => { x.pos = i + 1; }); }
    shBump(s); return {column: colOut(s, c), rev: s.rev}; });
  on('DELETE', '/api/sheets/(\\d+)/columns/(\\d+)', (q, b, id, cid) => { const s = shGet(id), c = s.cols.find(x => x.id === +cid) || gone(); c.deleted_at = iso(); return shBump(s); });
  on('POST', '/api/sheets/(\\d+)/columns/(\\d+)/restore', (q, b, id, cid) => { const s = shGet(id), c = s.cols.find(x => x.id === +cid) || gone(); c.deleted_at = null; return shBump(s); });
  const shCell = (s, cellId) => { const e = Object.entries(s.cells).find(([, c]) => c.id === +cellId) || gone(); return e; };
  on('POST', '/api/sheets/(\\d+)/cells/(\\d+)/freeze', (q, b, id, cellId) => { const s = shGet(id), [k, c] = shCell(s, cellId);
    if (b.frozen) { const v = shEval(s).res[k]; c.fv = v && !v.err ? v.v : null; c.frozen = true; } else { c.frozen = false; delete c.fv; } shBump(s); const o = shOut(s); return {cell: o.cells.find(x => x.id === c.id), cells: o.cells, rev: s.rev}; });
  on('POST', '/api/sheets/(\\d+)/cells/(\\d+)/name', (q, b, id, cellId) => { const s = shGet(id), [, c] = shCell(s, cellId), n = String(b.name || '').trim();
    if (n && Object.values(s.cells).some(x => x !== c && (x.name || '').toLowerCase() === n.toLowerCase())) throw new Http(409, {error: tx('Folder already exists')});
    c.name = n || null; shBump(s); const o = shOut(s); return {cell: o.cells.find(x => x.id === c.id), cells: o.cells, rev: s.rev}; });

  // ---- file store + documents (kalmido/files/web.py fs_node_json, kalmido/docs/web.py doc_json): one tree of nodes; uploads arrive
  // as {files: [{name, type, size, data}]} (the fetch replacement reads FormData), small files keep their content as a data URL
  const FILE_MAX = 400 * 1024;
  const nodes = () => mcol('nodes');
  const nodeLive = () => nodes().filter(n => !n.deleted_at);
  const nodeOut = n => ({id: n.id, parent_id: n.parent_id ?? null, kind: n.kind, name: n.name, org_id: null, owner_id: 1, owner: DB.me.display_name, created_by: 1, created_by_name: DB.me.display_name,
    agent_id: null, mime: n.mime || null, size: n.size || 0, version: n.version || 1, created_at: n.created_at, updated_at: n.updated_at, deleted_at: n.deleted_at || null, org_access: '', role: 'owner', shared: false, tags: n.tags || []});
  const crumbs = n => { const out = []; let x = n; while (x) { out.unshift({id: x.id, name: x.name}); x = x.parent_id ? nodes().find(y => y.id === x.parent_id) : null; } return out; };
  const nodeSort = (a, b) => (a.kind === 'folder' ? 0 : 1) - (b.kind === 'folder' ? 0 : 1) || a.name.toLowerCase().localeCompare(b.name.toLowerCase());
  const needNode = id => { const n = nodes().find(x => x.id === +id); if (!n) gone(); return n; };
  const nodeDetails = n => ({...nodeOut(n), crumbs: crumbs(n), in_trash: !!n.deleted_at, versions: n.kind === 'file' ? (n.versions || []).map(v => ({no: v.no, created_at: v.created_at, size: v.size, by: DB.me.display_name})) : undefined,
    shares: [], inherited: [], org_access_from: null, log: [{name: DB.me.display_name, agent: false, action: n.kind === 'folder' ? 'create' : 'upload', at: n.created_at}]});
  const putFile = (parent, f, extra = {}) => { const same = nodeLive().find(n => n.kind === 'file' && (n.parent_id ?? null) === (parent ?? null) && n.name === f.name && !n.doc === !extra.doc);
    const v = {no: 1, created_at: iso(), size: f.size, data: f.data};
    if (same) { same.versions = [...(same.versions || []), {...v, no: (same.version || 1) + 1}]; same.version = (same.version || 1) + 1; Object.assign(same, {size: f.size, mime: f.type, data: f.data, updated_at: iso()}); return same; }
    const n = {id: nid('nodes'), parent_id: parent ?? null, kind: 'file', name: f.name || 'file', mime: f.type || 'application/octet-stream', size: f.size || 0, version: 1, data: f.data, versions: [v], tags: [],
      created_at: iso(), updated_at: iso(), deleted_at: null, ...extra}; nodes().push(n); return n; };
  on('GET', '/api/files', q => { const par = q.get('parent'), sp = q.get('space') || 'private';
    if (par) { const n = needNode(par); if (n.deleted_at) gone(); if (n.kind !== 'folder') gone(); return {items: nodeLive().filter(x => x.parent_id === n.id).sort(nodeSort).map(nodeOut), node: nodeOut(n), crumbs: crumbs(n), space: 'private', role: 'owner'}; }
    if (sp === 'trash') return {items: nodes().filter(n => n.deleted_at && !(n.parent_id && nodes().find(p => p.id === n.parent_id)?.deleted_at)).map(nodeOut), node: null, crumbs: [], space: 'trash', role: 'owner'};
    return {items: sp === 'private' ? nodeLive().filter(x => !x.parent_id).sort(nodeSort).map(nodeOut) : [], node: null, crumbs: [], space: sp, role: 'owner'}; });
  on('GET', '/api/files/nodes/(\\d+)', (q, b, id) => nodeDetails(needNode(id)));
  on('GET', '/api/files/nodes/(\\d+)/share-targets', () => ({people: [], groups: [], agents: []}));
  on('GET', '/api/files/folders', () => ({folders: nodeLive().filter(n => n.kind === 'folder').map(n => ({id: n.id, name: n.name, path: crumbs(n).map(c => c.name).join('/'), org_id: null, owner_id: 1}))}));
  on('GET', '/api/files/search', q => { const s = (q.get('q') || '').toLowerCase(); return {items: nodeLive().filter(n => n.name.toLowerCase().includes(s)).slice(0, 50).map(nodeOut)}; });
  on('POST', '/api/files/folders', (q, b) => { const name = String(b.name || '').trim() || bad(tx('Please enter a name')), par = b.parent_id ? needNode(b.parent_id).id : null;
    if (nodeLive().some(n => n.kind === 'folder' && (n.parent_id ?? null) === par && n.name.toLowerCase() === name.toLowerCase())) throw new Http(409, {error: tx('Folder already exists')});
    const n = {id: nid('nodes'), parent_id: par, kind: 'folder', name, size: 0, version: 1, tags: [], created_at: iso(), updated_at: iso(), deleted_at: null}; nodes().push(n); return nodeOut(n); });
  on('POST', '/api/files/upload', (q, b) => { const par = b.parent_id ? needNode(b.parent_id).id : null; return {items: (b.files || []).map(f => nodeOut(putFile(par, f)))}; });
  on('POST', '/api/files/nodes/(\\d+)/versions', (q, b, id) => { const n = needNode(id), f = (b.files || [])[0] || bad(tx('Invalid value: {0}').replace('{0}', 'file'));
    putFile(n.parent_id, {...f, name: n.name}, n.doc ? {doc: n.doc} : {}); return nodeDetails(n); });
  on('POST', '/api/files/nodes/(\\d+)/versions/(\\d+)/restore', (q, b, id, no) => { const n = needNode(id), v = (n.versions || []).find(x => x.no === +no) || gone();
    putFile(n.parent_id, {name: n.name, type: n.mime, size: v.size, data: v.data}, n.doc ? {doc: n.doc} : {}); return {version: n.version}; });
  on('PATCH', '/api/files/nodes/(\\d+)', (q, b, id) => { const n = needNode(id); if ('name' in b) n.name = String(b.name || '').trim() || n.name; if ('parent_id' in b) n.parent_id = b.parent_id ? needNode(b.parent_id).id : null; n.updated_at = iso(); return nodeOut(n); });
  on('DELETE', '/api/files/nodes/(\\d+)', (q, b, id) => { const n = needNode(id); if (q.get('purge') === '1') { const all = new Set([n.id]); let k = 0; while (k !== all.size) { k = all.size; for (const x of nodes()) if (all.has(x.parent_id)) all.add(x.id); }
    MD().nodes = nodes().filter(x => !all.has(x.id)); } else n.deleted_at = iso(); return {ok: true}; });
  on('POST', '/api/files/nodes/(\\d+)/restore', (q, b, id) => { const n = needNode(id); n.deleted_at = null; return nodeOut(n); });
  // documents: file nodes with doc fields, in the folder "Documents"
  const docRoot = () => nodeLive().find(n => n.kind === 'folder' && n.docroot) || (() => { const n = {id: nid('nodes'), parent_id: null, kind: 'folder', name: tx('Documents'), docroot: true, size: 0, version: 1, tags: [], created_at: iso(), updated_at: iso(), deleted_at: null}; nodes().push(n); return n; })();
  const lbl = (k, name) => { if (!name) return null; const L = mcol('dl_' + k), x = L.find(y => y.name.toLowerCase() === String(name).toLowerCase()) || (() => { const y = {id: nid('dl_' + k), name: String(name)}; L.push(y); return y; })(); return {id: x.id, name: x.name}; };
  const dcOut = n => { const d = n.doc || {}; return {id: n.id, name: n.name, mime: n.mime, size: n.size, org_id: null, ws: 'private', state: 'done', error: '', error_text: '', method: 'text', pages: 1, date: d.date || n.created_at.slice(0, 10),
    due: d.due || null, taken_at: null, amount: d.amount ?? null, currency: d.currency || null, sender: d.sender || null, type: d.type || null, tags: d.tags || [], folder: d.folder || null, auto: {}, suggest: {}, review: !!d.review,
    thumb: false, task_id: d.task_id || null, asn: d.asn ?? null, source: 'upload', created_at: n.created_at, updated_at: n.updated_at, parent_id: n.parent_id}; };
  const docLive = () => nodeLive().filter(n => n.doc);
  const dcSettings = () => ({ws: 'private', can_manage: true, levels: {sender: 'learn', type: 'learn', tags: 'learn', folder: 'learn'}, inbox: false, rules: [], senders: mcol('dl_sender'), types: mcol('dl_type'), tags: mcol('dl_tag'), folders: [],
    root_id: docRoot().id, ocr: false, ocr_missing: [], asn_prefix: 'ASN', asn_next: (MD().asn || 0) + 1, mail: {enabled: false, address: ''}, ...(MD().dcset || {})});
  on('GET', '/api/docs', q => { const s = (q.get('q') || '').toLowerCase(), tag = q.get('tag'), lim = +q.get('limit') || 200;
    const all = docLive().filter(n => (!s || n.name.toLowerCase().includes(s)) && (!tag || (n.doc.tags || []).some(t => t.name === tag || String(t.id) === tag)) && (q.get('review') !== '1' || n.doc.review)).sort((a, b) => b.id - a.id);
    const facet = k => { const m = {}; for (const n of docLive()) for (const x of k === 'tags' ? n.doc.tags || [] : [n.doc[k]].filter(Boolean)) (m[x.name] = m[x.name] || []).push(x.id); return Object.entries(m).map(([name, ids]) => ({name, ids: [...new Set(ids)]})); };
    return {docs: all.slice(0, lim).map(dcOut), total: all.length, review: docLive().filter(n => n.doc.review).length, waiting: 0, facets: {senders: facet('sender'), types: facet('type'), tags: facet('tags'), folders: []}}; });
  on('GET', '/api/docs/settings', () => dcSettings());
  on('PUT', '/api/docs/settings', (q, b) => { const {ws, ...rest} = b; MD().dcset = {...(MD().dcset || {}), ...rest}; return dcSettings(); });
  on('POST', '/api/docs', (q, b) => { const root = docRoot(); return {ids: (b.files || []).map(f => putFile(root.id, f, {doc: {review: true, tags: []}}).id), errors: []}; });
  const dcFull = n => ({...dcOut(n), role: 'owner', text: '', extracted: null});
  const needDc = id => { const n = needNode(id); if (!n.doc || n.deleted_at) gone(); return n; };
  on('GET', '/api/docs/(\\d+)', (q, b, id) => dcFull(needDc(id)));
  on('GET', '/api/docs/(\\d+)/receipt', () => gone());
  on('GET', '/api/paperless', () => gone());
  on('PATCH', '/api/docs/(\\d+)', (q, b, id) => { const n = needDc(id), d = n.doc;
    if ('name' in b) n.name = String(b.name || '').trim() || n.name;
    for (const k of ['date', 'due', 'currency']) if (k in b) d[k] = b[k] || null;
    if ('amount' in b) d.amount = b.amount === '' || b.amount == null ? null : m2(num(b.amount));
    if ('sender' in b) d.sender = lbl('sender', b.sender); if ('type' in b) d.type = lbl('type', b.type);
    if ('tags' in b) d.tags = (b.tags || []).map(t => lbl('tag', t)).filter(Boolean);
    if ('asn' in b) d.asn = b.asn === 'next' ? (MD().asn = (MD().asn || 0) + 1) : b.asn ? +b.asn : null;
    n.updated_at = iso(); return dcFull(n); });
  on('POST', '/api/docs/(\\d+)/accept', (q, b, id) => dcFull(needDc(id)));
  on('POST', '/api/docs/(\\d+)/redo', (q, b, id) => dcFull(needDc(id)));
  on('POST', '/api/docs/(\\d+)/review', (q, b, id) => { const n = needDc(id); n.doc.review = b.done === false; return dcFull(n); });
  on('POST', '/api/docs/(\\d+)/task', (q, b, id) => { const n = needDc(id), inbox = DB.lists.find(l => l.is_inbox) || DB.lists[0], t = newTask({title: n.name, list_id: inbox.id}); n.doc.task_id = t.id; return {task_id: t.id, title: t.title}; });
  on('DELETE', '/api/docs/(\\d+)/task', (q, b, id) => { needDc(id).doc.task_id = null; return {ok: true}; });
  // the content of a file: a download / a new tab from the stored data URL (or the notice when the file was too big for the demo)
  function fileOpen(href) {
    const m = /\/api\/(?:files\/nodes|docs)\/(\d+)\/(content|file|preview)/.exec(href); if (!m) return false;
    const n = nodes().find(x => x.id === +m[1]); if (!n) return false;
    if (!n.data) { notice(); return true; }
    const bin = atob(n.data.split(',')[1] || ''), u8 = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([u8], {type: n.mime || 'application/octet-stream'}));
    if (/dl=1/.test(href)) { const a = document.createElement('a'); a.href = url; a.download = n.name; document.body.appendChild(a); a.click(); a.remove(); } else wopen.call(window, url, '_blank');
    setTimeout(() => URL.revokeObjectURL(url), 60000); return true;
  }

  // ---- the office's further pages (kalmido/office/*): pipeline, cash flow, figures, bookkeeping, subscriptions, travel, meals, agreements, equipment
  const ofLines = () => OF().docs.filter(d => d.kind === 'invoice' && d.status !== 'draft' && d.status !== 'cancelled').map(d => ({d, ln: docLine(d)}));
  for (const k of ['roles', 'crew', 'equipment', 'sets', 'texts', 'contracts'])
    crud('/api/office/' + k, 'of_' + k, {def: () => ({org_id: 1, archived: 0}), keep: (x, q) => q.get('archived') === '1' || !x.archived, post: x => ({id: x.id}), one: x => ({id: x.id}), del: () => ({result: 'deleted'})});
  on('GET', '/api/office/contracts/(\\d+)/files', () => ({items: []}));
  on('GET', '/api/office/equipment/policies', () => ({items: []}));
  // pipeline
  const dealOut = x => ({id: x.id, title: x.title || '', stage: x.stage || 'inquiry', client_id: x.client_id || null, client_name: (CL().find(c => c.id === x.client_id) || {}).name || '', contact: x.contact || '', value: m2(num(x.value)),
    probability: +x.probability || 0, expected_date: x.expected_date || null, offer_id: x.offer_id || null, offer_number: '', offer_status: '', list_id: x.list_id || null, note: x.note || '', lost_reason: x.lost_reason || '',
    follow_up: x.follow_up || null, next_step: x.next_step || '', source: x.source || '', company: x.company || ''});
  crud('/api/office/deals', 'deals', {out: dealOut, post: x => ({id: x.id, stage: x.stage || 'inquiry'}), one: (x, before) => ({before: dealOut(before)}), index: () => {
    const items = mcol('deals').filter(x => !x.deleted_at), open = items.filter(x => !['won', 'lost', 'lead'].includes(x.stage)), fc = {};
    for (const x of open) if (x.expected_date) { const m = x.expected_date.slice(0, 7); fc[m] = (fc[m] || 0) + num(x.value) * (+x.probability || 0) / 100; }
    return {summary: {open: m2(open.reduce((a, x) => a + num(x.value), 0)), weighted: m2(open.reduce((a, x) => a + num(x.value) * (+x.probability || 0) / 100, 0)), count_open: open.length,
      forecast: Object.keys(fc).sort().map((m, i) => ({month: m, weighted: m2(fc[m]), next: i === 0})), undated: open.filter(x => !x.expected_date).length, leads: items.filter(x => x.stage === 'lead').length, leads_due: 0}, items: items.map(dealOut)}; }});
  on('POST', '/api/office/deals/(\\d+)/offer', (q, b, id) => { const x = mfind('deals', id), d = newDoc('offer', {client_id: x.client_id || null, project_title: x.title || ''}); x.offer_id = d.id; return {doc_id: d.id}; });
  on('POST', '/api/office/deals/(\\d+)/project', (q, b, id) => { const x = mfind('deals', id), l = {...clone(LIST_DEF), id: nid('list'), created_at: iso(), name: x.title || tx('Project'), kind: 'project', sort: Math.max(0, ...DB.lists.map(y => y.sort)) + 1};
    DB.lists.push(l); x.list_id = l.id; return {list_id: l.id, modules_on: []}; });
  // generated documents need the server's templates: the page shows its empty state, creating one = the notice
  on('GET', '/api/office/gen-docs', () => ({docs: [], templates: [], clients: CL().map(c => ({id: c.id, name: c.name})), lists: [], offers: [], vars: []}));
  // cash flow: invoices (paid = actual, open = plan by due month), fixed costs every month, own adjustments
  const fixedLive = sub => mcol('fixed').filter(x => !x.deleted_at && (sub == null || !!x.sub === sub));
  const fixedIn = (x, m) => (x.start || '0000-00').slice(0, 7) <= m && (!x.until || x.until.slice(0, 7) >= m) && (x.repeat !== 'yearly' || (x.start || '').slice(5, 7) === m.slice(5, 7)) && (x.repeat !== 'quarterly' || ((+m.slice(5) - +(x.start || '2000-01').slice(5, 7)) % 3 + 3) % 3 === 0);
  const fxOut = x => ({id: x.id, label: x.label || '', amount: m2(num(x.amount)), vat_rate: +x.vat_rate || 0, gross: m2(num(x.amount) * (1 + (+x.vat_rate || 0) / 100)), repeat: x.repeat || 'monthly', start: x.start || today(),
    until: x.until || null, category: x.category || '', sub: x.sub ? 1 : 0, notice_days: +x.notice_days || 0, seats: x.seats || [], seat_names: [], low_use: x.low_use ? 1 : 0, remind_days: +x.remind_days || 0,
    remind_user: x.remind_user || null, url: x.url || ''});
  crud('/api/office/fixed-costs', 'fixed', {out: fxOut, post: x => ({id: x.id}), one: x => fxOut(x), del: x => ({item: fxOut(x)}), index: () => ({items: fixedLive().map(fxOut), agreements: []})});
  crud('/api/office/cashflow/adjust', 'cfadj', {post: x => ({id: x.id}), del: x => ({item: clone(x)})});
  on('GET', '/api/office/cashflow', q => { const from = q.get('from') || today().slice(0, 7), n = Math.min(24, +q.get('months') || 3), gross = q.get('basis') !== 'net'; let bal = num((MD().cfstart || {}).amount);
    const L = ofLines(), entries = [];
    const rows = Array.from({length: n}, (_, i) => { const m = monthAdd(from, i); let ia = 0, ip = 0, op = 0;
      for (const {d, ln} of L) { for (const p of d.payments || []) if (String(p.date || '').slice(0, 7) === m) { ia += num(p.amount); entries.push({month: m, dir: 'in', state: 'actual', kind: 'invoice', number: d.number, date: p.date, label: ln.recipient_name, amount: m2(num(p.amount)), overdue: false, open_offer: false, doc_id: d.id}); }
        const open = num(ln.open); if (open > 0 && String(d.due_date || d.date).slice(0, 7) === m) { ip += open; entries.push({month: m, dir: 'in', state: 'plan', kind: 'invoice', number: d.number, date: d.due_date, label: ln.recipient_name, amount: m2(open), overdue: ln.state === 'overdue', open_offer: false, doc_id: d.id}); } }
      for (const x of fixedLive()) if (fixedIn(x, m)) { const a = num(x.amount) * (gross ? 1 + (+x.vat_rate || 0) / 100 : 1); op += a; entries.push({month: m, dir: 'out', state: 'plan', kind: 'fixed', number: '', date: m + '-01', label: x.label, amount: m2(a), overdue: false, open_offer: false, doc_id: null}); }
      for (const a of mcol('cfadj').filter(x => !x.deleted_at && x.month === m)) { if (a.dir === 'out') op += num(a.amount); else ip += num(a.amount); }
      bal += ia + ip - op; return {month: m, current: m === today().slice(0, 7), balance: m2(bal), in: {actual: m2(ia), plan: m2(ip)}, out: {actual: '0.00', plan: m2(op)}}; });
    return {basis: gross ? 'gross' : 'net', rows, entries, adjust: mcol('cfadj').filter(x => !x.deleted_at).map(clone)}; });
  on('GET', '/api/office/cashflow/check', () => ({on: 0, user_id: null, people: [], lost: false}));
  on('PUT', '/api/office/cashflow/check', (q, b) => ({on: b.on ? 1 : 0, user_id: null, people: [], lost: false}));
  on('PUT', '/api/office/cashflow/actual', (q, b) => { MD().cfstart = {month: b.month, amount: num(b.amount)}; return {ok: true}; });
  on('GET', '/api/office/cashflow/start', () => ({start: MD().cfstart || null}));
  // figures (kalmido/office/kpi.py) from the invoices, the pipeline and the cash flow
  on('GET', '/api/office/kpi', q => { const y = +q.get('year') || +today().slice(0, 4), L = ofLines(), mk = today().slice(0, 7), rev = m => L.filter(({d}) => String(d.date).slice(0, 7) === m).reduce((a, {ln}) => a + num(ln.net), 0);
    const months = Array.from({length: 12}, (_, i) => { const m = `${y}-${pad(i + 1)}`; return {month: m, amount: m2(rev(m)), prev: m2(rev(`${y - 1}-${pad(i + 1)}`))}; });
    const yr = yy => L.filter(({d}) => String(d.date).slice(0, 4) === String(yy)).reduce((a, {ln}) => a + num(ln.net), 0);
    const open = L.filter(({ln}) => num(ln.open) > 0), od = open.filter(({ln}) => ln.state === 'overdue'), deals = mcol('deals').filter(x => !x.deleted_at && !['won', 'lost', 'lead'].includes(x.stage));
    return {year: y, today: today(), revenue: {month: m2(rev(mk)), month_prev: m2(rev(monthAdd(mk, -1))), year: m2(yr(y)), year_prev: m2(yr(y - 1)), to_date: true, month_key: mk, months},
      invoices: {open: {amount: m2(open.reduce((a, {ln}) => a + num(ln.open), 0)), count: open.length}, overdue: {amount: m2(od.reduce((a, {ln}) => a + num(ln.open), 0)), count: od.length}},
      pipeline: {weighted: m2(deals.reduce((a, x) => a + num(x.value) * (+x.probability || 0) / 100, 0)), open: m2(deals.reduce((a, x) => a + num(x.value), 0))},
      cashflow: [0, 1, 2].map(() => ({balance: '0.00'})), clients: []}; });
  // bank: the import needs a file of the bank (the notice); the list stays calm
  on('GET', '/api/office/bank/tx', () => ({items: [], counts: {open: 0, matched: 0}}));
  on('GET', '/api/office/bank/imports', () => ({items: []}));
  // bookkeeping: income from the paid invoices of the year
  on('GET', '/api/office/books', () => ({receipts: [], missing: [], small_business: !!flag(ofSettings().small_business), upload_ws: 'private'}));
  on('GET', '/api/office/books/euer', q => { const y = String(+q.get('year') || today().slice(0, 4)), L = ofLines().filter(({d}) => String(d.date).slice(0, 4) === y);
    const net = L.reduce((a, {ln}) => a + num(ln.net), 0), gr = L.reduce((a, {ln}) => a + num(ln.gross), 0);
    return {year: +y, income: L.length ? [{label: tx('Invoices'), count: L.length, net: m2(net), vat: m2(gr - net), gross: m2(gr)}] : [], income_total: {net: m2(net), vat: m2(gr - net), gross: m2(gr)},
      expenses: [], expense_total: {net: '0.00', vat: '0.00', gross: '0.00'}, profit: m2(net), small_business: !!flag(ofSettings().small_business), tax_reserve_pct: +ofSettings().tax_reserve_pct || 0,
      tax_reserve: m2(net * (+ofSettings().tax_reserve_pct || 0) / 100), missing_vat: 0, notes: ['', '']}; });
  on('GET', '/api/office/books/ustva', () => ({small_business: !!flag(ofSettings().small_business), kz: {81: '0.00', 86: '0.00', 66: '0.00', 83: '0.00'}, tax: {19: '0.00', 7: '0.00'}, basis: 'ist', exempt_other: '0.00', missing_vat: 0, items: []}));
  const TXD = () => ({ustva: 'quarter', ustva_ext: 0, est: 0, gewst: 0, lead_days: 7, user: null, people: [], tasks: {}, next: [], small_business: false, lost: false, ...(MD().txd || {})});
  on('GET', '/api/office/tax-dates', () => TXD());
  on('PUT', '/api/office/tax-dates', (q, b) => { MD().txd = {...(MD().txd || {}), ...b}; return TXD(); });
  on('GET', '/api/office/receipts/billed', () => ({billed: {}}));
  // subscriptions = fixed costs with sub 1
  on('GET', '/api/office/subs', () => { const items = fixedLive(true).map(x => { const o = fxOut(x), pm = num(o.amount) / ({yearly: 12, quarterly: 3}[o.repeat] || 1);
      return {...o, running: !o.until || o.until >= today(), next_renewal: null, cancel_by: null, per_month: m2(pm * (1 + o.vat_rate / 100)), per_month_net: m2(pm)}; });
    const s = k => items.reduce((a, x) => a + num(x[k]), 0);
    return {items, candidates: [], today: today(), people: [], remind_people: [], totals: {per_month: m2(s('per_month')), per_year: m2(s('per_month') * 12), per_month_net: m2(s('per_month_net')), per_year_net: m2(s('per_month_net') * 12),
      low_use_count: 0, low_use_per_year: '0.00', low_use_per_year_net: '0.00'}}; });
  // travel expenses (without the per-diem tables of the server: no meal allowance in the demo)
  const TRIP_CATS = [['hotel', 'Hotel'], ['train', 'Train'], ['flight', 'Flight'], ['parking', 'Parking'], ['food', 'Food'], ['other', 'Other']];
  const tripOut = x => { const items = (x.items || []).filter(i => !i.deleted_at).map(i => ({id: i.id, date: i.date || x.date_from, category: i.category || 'other', text: i.text || '', amount: m2(num(i.amount)), currency: 'EUR',
      amount_home: m2(num(i.amount)), fx_rate: 1, datev: 0, datev_no: '', billed: null}));
    return {id: x.id, date_from: x.date_from || today(), date_to: x.date_to || x.date_from || today(), dest: x.dest || '', overnight: x.overnight ? 1 : 0, people: x.people || [{id: 1, name: DB.me.display_name}], purpose: x.purpose || '',
      client_id: x.client_id || null, project: x.project || '', km: x.km ?? null, note: x.note || '', missing: 0, items, total: m2(items.reduce((a, i) => a + num(i.amount), 0)), vma: null, vma_off: 1, country: x.country || 'DE',
      place: x.place || '', t_start: x.t_start || '', t_end: x.t_end || '', vma_days: []}; };
  crud('/api/office/trips', 'trips', {out: tripOut, post: x => ({id: x.id}), del: x => ({trip: tripOut(x)}), index: q => { const y = q.get('year');
    return {trips: mcol('trips').filter(x => !x.deleted_at && (!y || String(x.date_from || '').startsWith(y))).map(tripOut), missing: 0, categories: TRIP_CATS.map(([key, l]) => ({key, label: tx(l)})), currency: 'EUR',
      clients: CL().map(c => ({id: c.id, name: c.name})), people: [{id: 1, name: DB.me.display_name}], purposes: []}; }});
  on('POST', '/api/office/trips/(\\d+)/items', (q, b, id) => { const x = mfind('trips', id), i = {...b, id: nid('tripitem'), deleted_at: null}; (x.items = x.items || []).push(i); return {item_id: i.id}; });
  on('PATCH', '/api/office/trips/(\\d+)/items/(\\d+)', (q, b, id, iid) => { const i = (mfind('trips', id).items || []).find(y => y.id === +iid) || gone(); Object.assign(i, b); return {ok: true}; });
  on('DELETE', '/api/office/trips/(\\d+)/items/(\\d+)', (q, b, id, iid) => { const i = (mfind('trips', id).items || []).find(y => y.id === +iid) || gone(); i.deleted_at = iso(); return {ok: true, item: clone(i)}; });
  on('GET', '/api/office/trips/purposes', () => ({purposes: []}));
  on('GET', '/api/office/trips/report', () => { const ts = mcol('trips').filter(x => !x.deleted_at).map(tripOut); return {rows: [], count: ts.length, total: m2(ts.reduce((a, t) => a + num(t.total), 0))}; });
  on('GET', '/api/office/trips/vma', () => ({people: [], total: '0.00', rates: true, source: []}));
  on('GET', '/api/office/vehicles', () => ({vehicles: [], note: ''}));
  // entertainment receipts
  const mealOut = x => { const g = (x.amounts || []).reduce((a, r) => a + num(r.gross ?? r.amount), 0) + num(x.tip);
    return {id: x.id, date: x.date || today(), place_name: x.place_name || '', place_address: x.place_address || '', occasion: x.occasion || '', host: x.host || {id: 1, name: DB.me.display_name}, guests: x.guests || [],
      amounts: x.amounts || [], tip: m2(num(x.tip)), note: x.note || '', locked: x.locked ? 1 : 0, calc: {gross: m2(g)}}; };
  crud('/api/office/meals', 'meals', {out: mealOut, index: q => { const y = q.get('year'), ms = mcol('meals').filter(x => !x.deleted_at && (!y || String(x.date || '').startsWith(y)));
    return {meals: ms.map(mealOut), people: [{id: 1, name: DB.me.display_name}], choices: {places: [...new Set(ms.map(x => x.place_name).filter(Boolean))].map(name => ({name, address: ''})), persons: []}}; }});
  on('POST', '/api/office/meals/(\\d+)/approve', (q, b, id) => { const x = mfind('meals', id); x.locked = 1; return mealOut(x); });
  on('POST', '/api/office/meals/(\\d+)/unlock', (q, b, id) => { const x = mfind('meals', id); x.locked = 0; return mealOut(x); });
  on('GET', '/api/office/meals/choices', () => ({places: [], persons: []}));
  on('GET', '/api/office/meals/report', () => { const ms = mcol('meals').filter(x => !x.deleted_at).map(mealOut), g = m2(ms.reduce((a, x) => a + num(x.calc.gross), 0));
    return {count: ms.length, drafts: ms.filter(x => !x.locked).length, total: {gross: g, vat: '0.00', deductible: '0.00', not_deductible: '0.00', food: '0.00', drinks: '0.00', tip: '0.00', net: g}, rates: [], months: []}; });
  // framework agreements / insurances
  const agOut = x => { const c = num(x.cost), mo = c / (PERM[x.per] || 1); return {id: x.id, kind: x.kind || 'other', name: x.name || '', provider: x.provider || '', number: x.number || '', archived: x.archived ? 1 : 0, cost: m2(c), per: x.per || 'month',
    monthly: m2(mo), vat_pct: x.vat_pct ?? null, start: x.start || null, ends: x.ends || null, notice: +x.notice || 0, notice_unit: x.notice_unit || 'm', renew_months: +x.renew_months || 0, lead_days: +x.lead_days || 0,
    cashflow: x.cashflow === 0 ? 0 : 1, task: null, doc: null, deadline: noticeAt(x.ends, +x.notice || 0, x.notice_unit || 'm'), covered: null}; };
  crud('/api/office/agreements', 'agreements', {out: agOut, post: x => ({id: x.id}), index: q => ({items: mcol('agreements').filter(x => !x.deleted_at && (q.get('archived') === '1' || !x.archived)).map(agOut),
    lists: DB.lists.filter(l => !l.archived).slice(0, 30).map(l => ({id: l.id, name: l.name, inbox: !!l.is_inbox}))})});
  // the office settings' further parts
  on('GET', '/api/office/letterhead', () => ({letterhead: {on: false}}));
  on('GET', '/api/office/packs', () => ({packs: [], industry: null}));
  on('GET', '/api/office/catalog', () => ({items: [], configured: false, can_manage: false}));

  // ---------------------------------------------------------------- the notice for server features
  function notice() {
    const x = T();
    let el = document.getElementById('kd-note');
    if (!el) {
      el = document.createElement('div'); el.id = 'kd-note'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'false'); el.setAttribute('aria-labelledby', 'kd-note-t');
      document.body.appendChild(el);
    }
    el.innerHTML = `<b id="kd-note-t"></b><p></p><div class="kd-row"><a class="kd-btn kd-pri" target="_top"></a><button type="button" class="kd-btn"></button></div>`;
    el.querySelector('b').textContent = x.gated; el.querySelector('p').textContent = x.gatedMore;
    const a = el.querySelector('a'); a.textContent = x.installLink; a.href = installUrl();
    const c = el.querySelector('button'); c.textContent = x.close; c.onclick = () => el.remove();
    setTimeout(() => { const t = document.getElementById('toast'); if (t) t.classList.add('hidden'); }, 0);
    a.focus();
  }
  // 2.125.0 D (#1653): a part of the app the demo does not imitate yet: a calm line at the bottom (once per page view), never silent
  function unknownNote() {
    if (document.getElementById('kd-unk')) return;
    const el = document.createElement('div'); el.id = 'kd-unk'; el.className = 'kd-unknown'; el.setAttribute('role', 'status');
    el.innerHTML = '<span></span><button type="button" class="kd-btn"></button>';
    el.querySelector('span').textContent = T().unknown; const c = el.querySelector('button'); c.textContent = T().close; c.onclick = () => el.remove();
    (document.body || document.documentElement).appendChild(el);
    setTimeout(() => el.remove(), 8000);
  }
  const installUrl = () => SITE + ((DB && DB.settings.lang) === 'de' ? 'de/installation.html' : 'install.html');

  // ---------------------------------------------------------------- fetch replacement
  // a small Response look-alike (what the app reads: ok, status, type, headers.get, json, text)
  const json = (status, body) => { const txt = JSON.stringify(body);
    return {ok: status >= 200 && status < 300, status, type: 'basic', redirected: false, url: '', headers: {get: k => /content-type/i.test(k) ? 'application/json' : null, has: k => /content-type/i.test(k)},
      json: async () => JSON.parse(txt), text: async () => txt, clone() { return json(status, body); }}; };
  async function staticFile(path) {
    // i18n and the celebration one-liners come as small scripts (CSP: no connect), loaded on demand
    const m = path.match(/i18n\/([a-z]{2,3})\.json$/);
    if (m) {
      window.KDEMO_I18N = window.KDEMO_I18N || {};
      if (!window.KDEMO_I18N[m[1]]) await new Promise(res => { const s = document.createElement('script'); s.src = `static/i18n/${m[1]}.js`; s.onload = s.onerror = res; document.head.appendChild(s); });
      return window.KDEMO_I18N[m[1]] ? json(200, window.KDEMO_I18N[m[1]]) : json(404, {});
    }
    if (/\/quips\.json$/.test(path)) return window.KDEMO_QUIPS ? json(200, window.KDEMO_QUIPS) : json(404, {});
    return json(404, {});
  }
  function handle(method, url, body) {
    const u = new URL(url, 'https://demo.invalid/'), path = u.pathname, key = method + ' ' + path;
    CALLS.push(key); if (CALLS.length > 60) CALLS.shift();  // 2.125.0 D (#1653): the last calls (tests, a look in the console)
    if (QUIET[key]) return [200, QUIET[key]()];
    for (const [m, re, fn] of R) {
      if (m !== method) continue;
      const mm = path.match(re);
      if (mm) {
        const out = fn(u.searchParams, body || {}, ...mm.slice(1));
        if (method !== 'GET') bump();
        return [200, out];
      }
    }
    // 2.74.0 (#1653): the office's server-only parts (KPI, cash flow, travel, pipeline, DATEV, imports ...) answer a read with
    // the calm "not available" text (the tab shows it), without the notice popping up while browsing
    if (/^\/api\/office\//.test(path)) { GATE.push(key); if (method !== 'GET') notice(); return [409, {error: T().gated, demo: 'gated'}]; }
    MISS.push(key);
    if (GATED.test(path) || method !== 'GET') { notice(); return [409, {error: T().gated, demo: 'gated'}]; }
    // 2.125.0 D (#1653): an unknown read (a route newer than this shim): console.warn + a small visible line, an empty answer
    UNKNOWN.push(key); console.warn('demo: no stand-in for', key, '(add it in tools/demo/shim.js)'); unknownNote();
    return [200, {}];
  }
  const FD_OK = /^\/api\/(files\/upload|files\/nodes\/\d+\/versions|docs)$/;
  async function fdBody(fd) {
    const out = {files: []};
    for (const [k, v] of fd.entries()) {
      if (typeof v === 'string') { out[k] = v; continue; }
      const data = v.size <= FILE_MAX ? await new Promise(res => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.onerror = () => res(null); r.readAsDataURL(v); }) : null;
      out.files.push({name: v.name || 'file', type: v.type || 'application/octet-stream', size: v.size || 0, data});
    }
    return out;
  }
  window.fetch = async (input, opt = {}) => {
    const url = typeof input === 'string' ? input : input.url, method = (opt.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    const p = new URL(url, 'https://demo.invalid/').pathname;
    if (!p.startsWith('/api/')) return staticFile(p);
    let body = {};
    if (opt.body instanceof FormData || opt.body instanceof Blob) {
      // 2.125.0 D (#1653): uploads into the file store and the documents stay in this browser (small files with their content)
      if (!(opt.body instanceof FormData) || !FD_OK.test(p)) { notice(); return json(409, {error: T().gated, demo: 'gated'}); }
      body = await fdBody(opt.body);
    }
    if (typeof opt.body === 'string') { try { body = JSON.parse(opt.body); } catch { body = {}; } }
    await new Promise(r => setTimeout(r, 0));
    try { const [st, out] = handle(method, url, body); return json(st, out); }
    catch (e) { if (e instanceof Http) return json(e.status, e.body); console.error('demo:', method, p, e); return json(500, {error: String(e.message || e)}); }
  };
  // download links of the app (JSON export, CSV, backups) point at the server: the notice instead
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (a && /^\/api\//.test(a.getAttribute('href') || '')) { e.preventDefault(); e.stopImmediatePropagation(); const id = pdfId(a.getAttribute('href')); if (id) printView(id); else if (!fileOpen(a.getAttribute('href'))) notice(); }  // 2.125.0 D (#1653): + stored files  // 2.74.0 (#1653): a PDF = the print view
  }, true);

  // ---------------------------------------------------------------- banner + reset
  function banner() {
    const x = T(), b = document.createElement('div');
    b.id = 'kd-bar'; b.setAttribute('role', 'region'); b.setAttribute('aria-label', 'Demo');
    b.innerHTML = '<span class="kd-dot" aria-hidden="true"></span><span class="kd-txt"></span><span class="kd-sp"></span><a class="kd-btn kd-pri" target="_top"></a><button type="button" class="kd-btn" id="kd-reset"></button>';
    b.querySelector('.kd-txt').textContent = x.banner;
    const a = b.querySelector('a'); a.textContent = x.install; a.href = installUrl();
    const r = b.querySelector('button'); r.textContent = x.reset;
    r.onclick = () => { if (window.confirm(T().resetAsk)) reset(); };
    document.body.insertBefore(b, document.body.firstChild);
    document.documentElement.classList.add('kdemo');
  }
  function reset() {
    const lang = (DB && DB.settings.lang) || browserLang();
    try {
      for (let i = localStorage.length - 1; i >= 0; i--) { const k = localStorage.key(i); if (k && (k === KEY || (k.startsWith('tasks.') && !['tasks.theme', 'tasks.accent', 'tasks.fsize', 'tasks.font', 'tasks.density'].includes(k)))) localStorage.removeItem(k); }
    } catch { /* private mode */ }
    seed(lang);
    try { localStorage.setItem('tasks.lang', JSON.stringify(lang)); } catch { /* private mode */ }
    location.reload();
  }
  const CSPV = [];  // blocked by the page's CSP (tests: must stay empty)
  document.addEventListener('securitypolicyviolation', e => CSPV.push(e.violatedDirective + ' ' + e.blockedURI));
  window.KDEMO = {reset, db: () => DB, miss: MISS, gated: GATE, unknown: UNKNOWN, calls: CALLS, csp: CSPV, printView, routes: () => R.map(([m, re]) => m + ' ' + re.source)};

  DB = loadDb();
  if (DB && DB.ver === VER) save();  // 2.74.0 (#1653): a migrated storage is written back once
  if (!DB) {
    seed(browserLang());
    try { localStorage.setItem('tasks.lang', JSON.stringify(DB.settings.lang)); localStorage.removeItem('tasks.cache'); localStorage.removeItem('tasks.uid'); } catch { /* private mode */ }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', banner); else banner();
  setInterval(agentTick, 25000);
})();
