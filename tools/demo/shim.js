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
    date_confirm: '0', default_reminder: '0', digest_time: '', features: 'cal,timeline,matrix,habits,kanban,collab,stats,time,progress,deps,fields,comments,agents',
    features_rev: '11', show_done_default: '0', folders: '[]', folders_closed: '[]', hide_blocked_today: '0', hide_progress: '', ical_alarms: '1', ical_scope: 'all',
    lang: 'en', nav_order: 'tasks,cal,matrix,habits', news_kinds: 'mention,assign,comment,unblock,share,status', notify: '', ntfy_topic: '',
    onboard: 'pending', pomo_focus: '25', pomo_long: '15', pomo_long_every: '4', pomo_short: '5', progress_subtasks: '0',
    push_channel: 'webpush', push_priority: '4', quiet_from: '22:00', quiet_to: '07:00', review_time: '', roadmap: '', sample_ask: '1',
    show_done_views: '{}', time_autostop_h: '12', time_currency: '€', time_focus: '1', time_remind_h: '4', time_rounding: '0', time_target: '0',
    tour: 'pending', work_end: '17:00', work_start: '09:00'};
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
      timer: DB.timer ? entryOut(DB.time.find(e => e.id === DB.timer)) : null, time_totals: tt, time_lists: tl, time_day_h: 8, collab_all: true, time_all: true,
      about: {available: false, latest: '', checked_at: '', error: '', collab_all: true, cal_on: false, oidc: {configured: false}},
      calendars: {enabled: false, subs: 0}, api: {enabled: false}, webhooks: {enabled: false}, caldav: {enabled: false}, public_links: false,
      share: {drop_url: '', ios_shortcut: ''}, sample: sampleState(), agents: [agentOut()], proposers: [], groups: [], my_groups: [],
      dayplan: {default_duration: 30, review_time: '', work_end: DB.settings.work_end, work_start: DB.settings.work_start},
      kids: [], kid_ids: [],  // 2.19.0 (#653): no other accounts in the demo
      clients: DB.settings.features.split(',').includes('clients') ? (DB.clients || []).map(clientBrief) : [], workspaces: false,  // 2.74.0 (#1653)
    };
  }

  // ---------------------------------------------------------------- helpers for writes
  class Http extends Error { constructor(status, body) { super(body.error || String(status)); this.status = status; this.body = body; } }
  const bad = msg => { throw new Http(400, {error: msg}); };
  const gone = () => { throw new Http(404, {error: 'Not found'}); };
  const needTask = id => { const t = taskById(id); if (!t) gone(); return t; };
  const TASK_FIELDS = ['title', 'content', 'priority', 'due', 'due_time', 'start', 'duration', 'reminders', 'repeat', 'repeat_from', 'url', 'list_id',
    'section_id', 'parent_id', 'sort', 'pinned', 'tags', 'ttype', 'deadline', 'nag', 'plan_start', 'assignee_id', 'status', 'fam', 'stars'];
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
  const R = [], MISS = [], GATE = [];  // MISS: calls answered by the fallback (tests list them); GATE (2.74.0): office reads gated on purpose
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
  on('GET', '/api/calendars/events', () => ({events: [], errors: []}));
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
      open: live().filter(t => t.status === 0 && t.due && t.due <= t0).map(t => ({due: t.due, overdue: t.due < t0, task_id: t.id, title: t.title}))}; });
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
  const DEMO_OFF = new Set(['events', 'contacts', 'files', 'docs', 'workload', 'forms', ...LIFE]);
  on('POST', '/api/me/purpose', (q, b) => {
    const p = b.purpose, am = b.all_modules; if (!PURPOSE[p]) bad('Invalid purpose');
    const extra = PURPOSE_EXTRA[p] || [], onS = new Set(am == null ? [...PURPOSE[p], ...extra] : am ? [...PURPOSE_MODS, ...extra] : []);
    const sw = [...PURPOSE_MODS, ...(am === false ? Object.values(PURPOSE_EXTRA).flat() : [])];
    let fs = DB.settings.features.split(',').filter(Boolean);
    fs = [...fs.filter(x => !sw.includes(x) || onS.has(x)), ...PURPOSE_MODS.filter(x => onS.has(x) && !fs.includes(x))];
    fs = [...fs, ...extra.filter(x => onS.has(x) && !fs.includes(x))].filter(x => !DEMO_OFF.has(x));
    if (am != null) DB.settings.mods_all = am ? '1' : '0';
    DB.settings.features = fs.join(','); DB.settings.purpose = p;
    const created = [];
    if (p === 'family') { for (const [k, n] of [['shopping', 'Shopping list'], ['household', 'Household']]) if (!DB.lists.some(l => l.family === k)) created.push(famList(k, n).id); }
    else if (b.examples === true && ['team', 'office', 'software'].includes(p) && !sampleState()) created.push(sampleMake());
    return {features: DB.settings.features, created};
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
  const LBL = {de: {net: 'Summe Netto', gross: 'Gesamt Brutto', discount: 'Rabatt', producing: 'Producing', net_incl_raw: 'inklusive Rohdaten', net_excl_raw: 'ohne Rohdaten',
    tax: p => `MwSt. ${p} %`, exempt: 'steuerfrei', vat_note: 'Alle Preise zuzüglich 7 % bzw. 19 % MwSt.', novat_note: 'Nicht im Inland steuerbar / Reverse-Charge-Verfahren.',
    units: {day: 'Tage', hour: 'Std.', piece: 'Stk.', minute: 'Min.', flat: 'pauschal'}, producing_detail: (d, q, k) => `${d} Tage = ${q} Produktionstage / ${k}, auf halbe Tage gerundet`,
    raw_optional: 'Optional: Bereitstellung der Rohdaten', raw_included: 'Bereitstellung der Rohdaten', raw_detail: p => `${p} % der Positionen mit Rohdaten`, discount_detail: p => `${p} % auf die markierten Positionen`},
  en: {net: 'Net Total', gross: 'Gross Total', discount: 'Discount', producing: 'Producing', net_incl_raw: 'including raw data', net_excl_raw: 'excluding raw data',
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
  const recipientOf = cl => ({name: cl.name, lines: [cl.name, ...(cl.contacts || []).filter(k => k.is_default).map(k => k.name), cl.street || '', [cl.zip, cl.city].filter(Boolean).join(' '), ...String(cl.address || '').split('\n')].map(x => String(x || '').trim()).filter(Boolean).filter((x, i, a) => a.indexOf(x) === i)});
  const DOC_FIELDS = ['lang', 'currency', 'fx_rate', 'vat_mode', 'vat_note', 'project_title', 'project_ref', 'date', 'valid_until', 'contract_id', 'raw_mode', 'raw_factor', 'prod_quotient', 'producing_rate',
    'producing_on', 'discount_pct', 'intro', 'closing', 'rights', 'fields', 'service_from', 'service_to', 'order_ref', 'due_date', 'payment_days', 'einvoice_format', 'contact_id'];
  function patchDoc(d, b) {
    if (d.locked || d.status === 'sent') conflict('Sent documents cannot be changed; duplicate it for a new version.');
    for (const k of DOC_FIELDS) if (k in b) d[k] = b[k];
    if ('recipient' in b) d.recipient = {name: String(b.recipient?.name || ''), lines: (b.recipient?.lines || []).map(String)};
    if ('client_id' in b) { d.client_id = b.client_id ? +b.client_id : null; const cl = CL().find(c => c.id === d.client_id);
      if (cl && b.recipient_from_client) d.recipient = recipientOf(cl); if (cl && d.kind === 'invoice' && cl.payment_terms_days != null) d.payment_days = +cl.payment_terms_days; }
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
  const CL_BILL = ['street', 'zip', 'city', 'country', 'vat_id', 'customer_no', 'buyer_reference', 'email_invoice', 'payment_terms_days'];
  const clientOut = c => ({...clone(c), archived: !!c.archived, org_name: '', lists: DB.lists.filter(l => l.client_id === c.id).map(l => l.id), can_delete: true,
    billing: Object.fromEntries(CL_BILL.map(k => [k, c[k] ?? null])),
    stats: {seconds: 0, rounded: 0, amount: 0, month: today().slice(0, 7), month_seconds: 0, month_amount: 0, estimate_min: 0, estimated: 0, open: 0, done: 0}, budget: {pct_h: null, pct_amount: null, level: 'none'}});
  const clientBrief = c => ({id: c.id, name: c.name, icon: c.icon || '', color: c.color || '', org_id: null, archived: !!c.archived, lists: DB.lists.filter(l => l.client_id === c.id).map(l => l.id)});
  function clientSet(c, b) {
    if ('name' in b) { if (!String(b.name || '').trim()) bad(tx('Name missing')); c.name = String(b.name).trim(); }
    for (const k of ['icon', 'color', 'email', 'phone', 'address', 'note', 'rate', 'budget_h', 'budget_amount', ...CL_BILL]) if (k in b) c[k] = b[k];
    if ('archived' in b) c.archived = b.archived ? 1 : 0;
    if (Array.isArray(b.contacts)) c.contacts = b.contacts.filter(k => String(k.name || '').trim()).map((k, i) => ({id: k.id || nid('clcontact'), name: String(k.name).trim(), role: k.role || '', email: k.email || '', phone: k.phone || '', is_default: !!k.is_default || (i === 0 && !b.contacts.some(x => x.is_default))}));
    c.contact = (c.contacts || []).find(k => k.is_default)?.name || ''; c.updated_at = iso();
  }
  on('GET', '/api/clients', () => ({clients: CL().map(clientOut)}));
  on('GET', '/api/clients/(\\d+)', (q, b, id) => ({...clientOut(CL().find(c => c.id === +id) || gone()), per_list: []}));
  on('POST', '/api/clients', (q, b) => { const c = {id: nid('client'), name: '', org_id: null, created_by: 1, created_at: iso(), contacts: [], archived: 0}; clientSet(c, {...b, name: b.name ?? ''}); CL().push(c); return clientOut(c); });
  on('PATCH', '/api/clients/(\\d+)', (q, b, id) => { const c = CL().find(x => x.id === +id) || gone(); clientSet(c, b); return clientOut(c); });
  on('DELETE', '/api/clients/(\\d+)', (q, b, id) => { DB.clients = CL().filter(c => c.id !== +id); for (const l of DB.lists) if (l.client_id === +id) l.client_id = null; return {ok: true}; });
  // ---- the office
  const ofInfo = () => ({settings: ofSettings(), company_fields: {...OF().company}, org_id: 1, role: 'admin', personal: 1, org_offices: [], can_move: false, industry: [],
    pack: {code: 'DE', name: 'Deutschland', tax: {...TAX}, currency: 'EUR', formats: {}}, number_preview: `KVA-${today().slice(0, 4)}-${String((OF().counters['offer:' + today().slice(0, 4)] || 0) + 1).padStart(3, '0')}`});
  on('GET', '/api/office/settings', () => ofInfo());
  on('PUT', '/api/office/settings', (q, b) => { const o = OF();
    if (b.company_fields) for (const k of CO_KEYS) if (k in b.company_fields) o.company[k] = String(b.company_fields[k] ?? '');
    const {company_fields, pack, ...rest} = b; o.settings = {...o.settings, ...rest}; return ofInfo(); });
  on('GET', '/api/office/number-preview', q => { const k = q.get('kind') || 'offer'; return {preview: `${SCHEME[k] || 'KVA'}-${today().slice(0, 4)}-001`, valid: true, yearly: true}; });
  for (const k of ['roles', 'crew', 'equipment', 'sets', 'texts', 'contracts']) on('GET', `/api/office/${k}`, () => ({items: []}));
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
    if (/^\/api\//.test(String(url || ''))) { notice(); return null; } return wopen.call(window, url, ...rest); };

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
    return [200, {}];  // an unknown read: empty
  }
  window.fetch = async (input, opt = {}) => {
    const url = typeof input === 'string' ? input : input.url, method = (opt.method || (typeof input === 'object' && input.method) || 'GET').toUpperCase();
    const p = new URL(url, 'https://demo.invalid/').pathname;
    if (!p.startsWith('/api/')) return staticFile(p);
    let body = {};
    if (opt.body instanceof FormData || opt.body instanceof Blob) { notice(); return json(409, {error: T().gated, demo: 'gated'}); }
    if (typeof opt.body === 'string') { try { body = JSON.parse(opt.body); } catch { body = {}; } }
    await new Promise(r => setTimeout(r, 0));
    try { const [st, out] = handle(method, url, body); return json(st, out); }
    catch (e) { if (e instanceof Http) return json(e.status, e.body); console.error('demo:', method, p, e); return json(500, {error: String(e.message || e)}); }
  };
  // download links of the app (JSON export, CSV, backups) point at the server: the notice instead
  document.addEventListener('click', e => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (a && /^\/api\//.test(a.getAttribute('href') || '')) { e.preventDefault(); e.stopImmediatePropagation(); const id = pdfId(a.getAttribute('href')); if (id) printView(id); else notice(); }  // 2.74.0 (#1653): a PDF = the print view
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
  window.KDEMO = {reset, db: () => DB, miss: MISS, gated: GATE, csp: CSPV, printView};

  DB = loadDb();
  if (DB && DB.ver === VER) save();  // 2.74.0 (#1653): a migrated storage is written back once
  if (!DB) {
    seed(browserLang());
    try { localStorage.setItem('tasks.lang', JSON.stringify(DB.settings.lang)); localStorage.removeItem('tasks.cache'); localStorage.removeItem('tasks.uid'); } catch { /* private mode */ }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', banner); else banner();
  setInterval(agentTick, 25000);
})();
