/* Kalmido browser demo: an in-browser stand-in for the server. Loaded before the app (see tools/build_demo.py); it replaces
   window.fetch, so the unchanged app (static/app.js) talks to this file instead of a server. Everything lives in
   localStorage of this browser (key kalmido-demo.db); nothing is ever sent anywhere (the page's CSP also forbids it:
   connect-src 'none').
   Implemented: lists, sections, tasks (subtasks, tags, fields, dependencies, repeats, trash), Today / Upcoming / kanban /
   timeline / calendar data, comments (local), time tracking, habits, filters, milestones and project status, day plan,
   settings (appearance, language, modules) and a simulated agent with one approval. Everything that needs a server
   (push, CalDAV, calendar subscriptions, real agents, Paperless, Git, webhooks, OIDC, more users, imports, backups) answers
   with a calm "not available in the demo" notice and a link to the install page. */
'use strict';
(() => {
  const KEY = 'kalmido-demo.db', VER = 1;
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
    try { const j = JSON.parse(localStorage.getItem(KEY)); if (j && j.ver === VER && j.tasks) return j; } catch { /* broken: new seed */ }
    return null;
  }
  const bump = () => { DB.v++; save(); };
  const nid = k => { DB.seq[k] = (DB.seq[k] || 0) + 1; return DB.seq[k]; };

  // ---------------------------------------------------------------- seed (sample data in the visitor's language)
  const TASK_DEF = {assigned_by: null, assignee_group_id: null, assignee_id: null, attachments: [], completed_at: null, completed_by: null,
    content: '', created_by: 1, deadline: 0, deleted_at: null, due: null, due_time: null, duration: null, fields: {}, ltags: [], nag: '',
    paperless: [], parent_id: null, pinned: 0, plan_start: null, priority: 0, reminders: '', repeat: '', repeat_from: 'due', section_id: null,
    sort: 0, start: null, status: 0, tags: [], tt_id: null, ttype: '', unread: 0, url: null, wait_by: null, wait_fired: '', wait_note: '',
    wait_until: null, waiting_at: null};
  const LIST_DEF = {agent_tidy: 'off', columns: null, archived: 0, archived_at: null, bell: 'default', bell_custom: {}, checklist: 0, color: '', day_hours: null,
    dep_shift: 0, description: '', folder: '', groups: [], icon: '', is_inbox: 0, kind: 'list', milestones: [], nag: '', owner_id: 1, rate: null,
    repos: [], role: 'owner', sort: 0, status: '', status_at: null, status_by: null, status_note: '', tags: [], ticket_tpl: '', tickets: 0,
    tidy_agent_id: null, view: 'list'};
  const SETTINGS_DEF = {agent_share: '{}', agents_hidden: '', allday_time: '09:00', cal_today: '1', celebrate: '1', comment_order: 'old',
    date_confirm: '0', default_reminder: '0', digest_time: '', features: 'cal,timeline,matrix,habits,kanban,collab,stats,time,progress,deps,fields,comments,agents',
    features_rev: '9', folders: '[]', folders_closed: '[]', hide_blocked_today: '0', hide_progress: '', ical_alarms: '1', ical_scope: 'all',
    lang: 'en', nav_order: 'tasks,cal,matrix,habits', news_kinds: 'mention,assign,comment,unblock,share,status', notify: '', ntfy_topic: '',
    onboard: 'done', paperless_keep: '0', pomo_focus: '25', pomo_long: '15', pomo_long_every: '4', pomo_short: '5', progress_subtasks: '0',
    push_channel: 'webpush', push_priority: '4', quiet_from: '22:00', quiet_to: '07:00', review_time: '', roadmap: '', sample_ask: '0',
    show_done_views: '{}', time_autostop_h: '12', time_currency: '€', time_focus: '1', time_remind_h: '4', time_rounding: '0', time_target: '0',
    tour: 'done', work_end: '17:00', work_start: '09:00'};
  const AGENT = 2;

  function seed(lang) {
    const x = TX[lang] || TX.en, t = x.t, now = iso();
    DB = {ver: VER, v: 1, seq: {}, settings: {...SETTINGS_DEF, lang}, me: {id: 1, username: 'demo', display_name: 'Demo', avatar: ''},
      lists: [], sections: [], tasks: [], fields: [], deps: [], comments: [], activity: [], time: [], timer: null, habits: [], filters: [],
      status: [], chat: [], jobs: [], agent: {status: 'working', status_text: x.agentTexts[0], status_task: null, step: 0}};
    const list = o => { const l = {...clone(LIST_DEF), id: nid('list'), created_at: now, ...o}; DB.lists.push(l); return l; };
    const sec = (lid, name, sort) => { const s = {id: nid('section'), list_id: lid, name, sort}; DB.sections.push(s); return s.id; };
    const task = o => { const k = {...clone(TASK_DEF), id: nid('task'), created_at: now, updated_at: now, ...o}; if (k.status && !k.completed_at) { k.completed_at = now; k.completed_by = 1; } DB.tasks.push(k); return k; };
    list({name: 'Eingang', is_inbox: 1, sort: -1});
    const p = list({name: x.project, kind: 'project', color: '#7c5cff', sort: 1, tickets: 1, status: 'on_track', status_at: now, status_by: 1, status_note: x.status,
      description: '', milestones: [{id: 1, name: x.ms1, day: day(4), done: 0}, {id: 2, name: x.ms2, day: day(20), done: 0}]});
    DB.seq.ms = 2;
    const priv = list({name: x.personal, color: '#22c55e', sort: 2});
    const S = x.secs.map((n, i) => sec(p.id, n, i + 1));
    const fb = {id: nid('field'), list_id: p.id, name: x.budget, type: 'number', options: {unit: '€'}, pinned: 1, sort: 1};
    const fe = {id: nid('field'), list_id: p.id, name: x.effort, type: 'select', pinned: 1, sort: 2,
      options: {options: [{id: 's', name: x.small, color: '#22c55e'}, {id: 'm', name: x.medium, color: '#f59e0b'}, {id: 'l', name: x.large, color: '#ef4444'}]}};
    DB.fields.push(fb, fe);
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
    DB.status.push({id: 1, list_id: p.id, user_id: 1, status: 'on_track', note: x.status, created_at: now});
    // time entries (the last days)
    const te = (n, h, mins, tid, note) => { const st = new Date(); st.setDate(st.getDate() + n); st.setHours(h, 0, 0, 0); const en = new Date(st.getTime() + mins * 60000);
      DB.time.push({id: nid('time'), user_id: 1, task_id: tid, list_id: p.id, start: iso(st), end: iso(en), seconds: mins * 60, note, source: 'manual', created_at: now, updated_at: now}); };
    te(-9, 10, 120, kick.id, t.time1); te(-6, 14, 90, site.id, ''); te(-2, 9, 150, lay.id, t.time2); te(-1, 13, 105, lay.id, ''); te(-1, 16, 45, cms.id, t.time3);
    // personal list + inbox
    const home = x.tags.home;
    task({list_id: priv.id, title: t.gift, priority: 3, due: day(1), sort: 1});
    task({list_id: priv.id, title: t.dentist, priority: 1, due: day(7 - ((wd + 6) % 7)), sort: 2});
    task({list_id: priv.id, title: t.plants, due: day(0), repeat: 'FREQ=WEEKLY', sort: 3, tags: [home]});
    task({list_id: priv.id, title: t.book, sort: 4});
    task({list_id: priv.id, title: t.grandma, due: day(0), due_time: '18:30', sort: 5});
    task({list_id: 1, title: t.groceries, sort: 1, tags: [home]});
    task({list_id: 1, title: t.idea, sort: 2});
    // the simulated agent works in the project: status on the form bug, one job waiting for approval
    DB.agent.status_task = form.id;
    p.members = [{user_id: AGENT, name: x.agentName, role: 'editor', username: 'demo-agent', via_group: false, group_role: null}];
    p.shared = true;
    DB.jobs.push({id: 1, agent_id: AGENT, task_id: cms.id, user_id: 1, title: x.jobTitle, state: 'waiting', log: x.jobLog, action: null, action_by: null,
      action_at: null, created_at: atLocal(0, 8, 40), updated_at: atLocal(0, 8, 40), kind: null, prop_state: null});
    DB.chat.push({id: 1, agent_id: AGENT, user_id: 1, from: 'agent', body: x.agentChatHello, task_id: null, created_at: atLocal(0, 8, 30), delivered_at: null, reactions: [], read: 0});
    DB.seq.job = 1; DB.seq.chat = 1;
    save();
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
      settings: clone(DB.settings), notify: {}, paperless: {configured: false, conns: [], enabled: false, key: false, personal: true, url: ''},
      ntfy_inbox: {enabled: false, server: '', topic: ''}, ntfy_url: '', webpush: {devices: 0, enabled: false, key: ''},
      languages: [{beta: false, code: 'de', name: 'Deutsch'}, {beta: false, code: 'en', name: 'English'}, {beta: true, code: 'es', name: 'Español'},
        {beta: true, code: 'fr', name: 'Français'}, {beta: true, code: 'it', name: 'Italiano'}, {beta: true, code: 'nl', name: 'Nederlands'}],
      news: {unread: 0, sig: '0'}, avatars: {[AGENT]: 'static/avatars/robot.svg'}, templates: [],
      timer: DB.timer ? entryOut(DB.time.find(e => e.id === DB.timer)) : null, time_totals: tt, time_lists: tl, time_day_h: 8, collab_all: true, time_all: true,
      about: {available: false, latest: '', checked_at: '', error: '', collab_all: true, cal_on: false, oidc: {configured: false}},
      calendars: {enabled: false, subs: 0}, api: {enabled: false}, webhooks: {enabled: false}, caldav: {enabled: false}, public_links: false,
      share: {drop_url: '', ios_shortcut: ''}, sample: null, agents: [agentOut()], proposers: [], groups: [], my_groups: [],
      dayplan: {default_duration: 30, review_time: '', work_end: DB.settings.work_end, work_start: DB.settings.work_start},
    };
  }

  // ---------------------------------------------------------------- helpers for writes
  class Http extends Error { constructor(status, body) { super(body.error || String(status)); this.status = status; this.body = body; } }
  const bad = msg => { throw new Http(400, {error: msg}); };
  const gone = () => { throw new Http(404, {error: 'Not found'}); };
  const needTask = id => { const t = taskById(id); if (!t) gone(); return t; };
  const TASK_FIELDS = ['title', 'content', 'priority', 'due', 'due_time', 'start', 'duration', 'reminders', 'repeat', 'repeat_from', 'url', 'list_id',
    'section_id', 'parent_id', 'sort', 'pinned', 'tags', 'ttype', 'deadline', 'nag', 'plan_start', 'assignee_id', 'status'];
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
  const GATED = /^\/api\/(push|ical|calendars(?!\/events)|paperless|admin|import|imports|repos|me\/(webhooks|tokens|app-passwords|2fa|passkeys|drop-token)|my\/agents|users$|users\/|backups|public|oidc|attachments|list-files|templates|news\/|pomo|ntfy|sample|onboarding|proposals|folders\/groups|agents\/usage)|\/(members|groups|owner|public-link|repos|paperless|files|icon|git-undo|attachments|take|wake|waiting)(\/|$|\?)/;
  // automatic background calls of the app: answered quietly (no notice)
  const QUIET = {
    'GET /api/push/subs': () => ({subs: []}), 'GET /api/push/vapid': () => ({key: ''}), 'GET /api/my/agents': () => ({allowed: false, max: 0, count: 0, agents: [], api: false}),
    'GET /api/imports': () => ({imports: []}), 'GET /api/templates': () => ({templates: []}), 'GET /api/calendars': () => ({subs: [], enabled: false}),
    'GET /api/me/tokens': () => ({tokens: []}), 'GET /api/me/webhooks': () => ({webhooks: []}), 'GET /api/me/app-passwords': () => ({passwords: []}),
    'GET /api/me/2fa': () => ({totp: false, passkeys: [], recovery_left: 0}), 'GET /api/paperless/conns': () => ({conns: []}),
    'GET /api/agents/usage': () => ({days: [], agents: []}), 'POST /api/onboarding': () => ({ok: true, created: false}), 'POST /api/news/read': () => ({ok: true}),
    'GET /api/pomo/stats': () => ({days: [], total: 0}), 'GET /api/ical': () => ({enabled: false}),
  };
  const R = [], MISS = [];  // MISS: calls answered by the fallback (tests list them)
  const on = (m, re, fn) => R.push([m, new RegExp('^' + re + '$'), fn]);
  on('GET', '/api/state', () => state());
  on('GET', '/api/version', () => ({v: DB.v, n: '0', c: '0'}));
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
    for (const k of ['name', 'color', 'folder', 'view', 'kind', 'checklist', 'tickets', 'nag']) if (k in b) l[k] = b[k];
    if (b.kind === 'checklist') { l.kind = 'list'; l.checklist = 1; }
    DB.lists.push(l); return listOut(l);
  });
  on('PATCH', '/api/lists/(\\d+)', (q, b, id) => {
    const l = listById(id) || gone();
    for (const k of ['name', 'color', 'folder', 'sort', 'view', 'archived', 'checklist', 'dep_shift', 'kind', 'tickets', 'nag', 'description', 'agent_tidy', 'rate', 'day_hours']) if (k in b) l[k] = typeof b[k] === 'boolean' ? (b[k] ? 1 : 0) : b[k];
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
      milestones: clone(l.milestones || []), name: l.name, paperless: [], role: 'owner',
      status: {at: l.status_at, current: l.status, note: l.status_note, history: DB.status.filter(s => s.list_id === l.id).map(s => ({...s, name: DB.me.display_name})).reverse()},
      task_files: [], task_paperless: [], time: {budget_h: null, day_hours: 8, seconds: sec}};
  });
  on('PATCH', '/api/lists/(\\d+)/overview', (q, b, id) => { const l = listById(id) || gone(); if ('description' in b) l.description = String(b.description || ''); return {ok: true}; });
  on('POST', '/api/lists/(\\d+)/milestones', (q, b, id) => { const l = listById(id) || gone(); if (!String(b.name || '').trim()) bad('Name missing');
    const m = {id: nid('ms'), name: b.name.trim(), day: b.day, done: b.done ? 1 : 0}; l.milestones = [...(l.milestones || []), m]; return m; });
  on('PATCH', '/api/lists/(\\d+)/milestones/(\\d+)', (q, b, id, mid) => { const l = listById(id) || gone(), m = (l.milestones || []).find(x => x.id === +mid) || gone();
    for (const k of ['name', 'day']) if (k in b) m[k] = b[k]; if ('done' in b) m.done = b.done ? 1 : 0; return {...m}; });
  on('DELETE', '/api/lists/(\\d+)/milestones/(\\d+)', (q, b, id, mid) => { const l = listById(id) || gone(); l.milestones = (l.milestones || []).filter(x => x.id !== +mid); return {ok: true}; });
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
    // i18n and the sloth lines come as small scripts (CSP: no connect), loaded on demand
    const m = path.match(/i18n\/([a-z]{2,3})\.json$/);
    if (m) {
      window.KDEMO_I18N = window.KDEMO_I18N || {};
      if (!window.KDEMO_I18N[m[1]]) await new Promise(res => { const s = document.createElement('script'); s.src = `static/i18n/${m[1]}.js`; s.onload = s.onerror = res; document.head.appendChild(s); });
      return window.KDEMO_I18N[m[1]] ? json(200, window.KDEMO_I18N[m[1]]) : json(404, {});
    }
    if (/sloth-quips\.json$/.test(path)) return window.KDEMO_QUIPS ? json(200, window.KDEMO_QUIPS) : json(404, {});
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
    if (a && /^\/api\//.test(a.getAttribute('href') || '')) { e.preventDefault(); e.stopPropagation(); notice(); }
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
  window.KDEMO = {reset, db: () => DB, miss: MISS, csp: CSPV};

  DB = loadDb();
  if (!DB) {
    seed(browserLang());
    try { localStorage.setItem('tasks.lang', JSON.stringify(DB.settings.lang)); localStorage.removeItem('tasks.cache'); localStorage.removeItem('tasks.uid'); } catch { /* private mode */ }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', banner); else banner();
  setInterval(agentTick, 25000);
})();
