/* Kalmido web client: Settings: notifications, Web Push, autosave settings, personal agents, import.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.53.0 (#1410): Web Push, the app badge and the service worker messages live in setcore.js (loaded at start)
function wpState(md, j = md._wp) {
  const el = $('#s-wpstate', md); if (!el || !j) return;
  const ch = $('#s-pushch', md)?.value || j.channel, n = j.subs.length;
  el.textContent = ch === 'ntfy' ? tr('Everything goes to ntfy.')
    : !n ? (j.ntfy ? tr('No device subscribed for push yet. Until then, notifications go to your ntfy topic.') : tr('No device subscribed for push yet. Turn on “Notify on this device” above.'))
    : ch === 'both' ? trn('Web Push to {0} device and ntfy.', 'Web Push to {0} devices and ntfy.', n)
    : trn('Web Push to {0} device. ntfy only if no device accepts a push.', 'Web Push to {0} devices. ntfy only if no device accepts a push.', n);
  el.classList.remove('warn');  // 2.5.2 (K04): a neutral hint, not a red warning
}
async function wpDraw(md) {
  const box = $('#s-wp', md); if (!box || !S.webpush?.enabled) return;
  let j;
  try { j = await api('GET', '/api/push/subs'); } catch { box.innerHTML = `<div class="muted">${tr('Offline: only works again with a connection')}</div>`; return; }
  md._wp = j; S.webpush.devices = j.subs.length;
  const sub = await wpSub(), mine = sub && j.subs.find(x => x.endpoint === sub.endpoint);
  const hint = t => `<div class="shint">${t}</div>`;
  let h = '';
  if (isIOS() && !isStandalone()) h += hintK(tr('Add Kalmido to your Home Screen to get notifications on iPhone: Share > Add to Home Screen (iOS 16.4 or newer), then open it from there and turn it on here.'));
  else if (!wpSupported()) h += hintK(tr('This browser does not support Web Push'));
  else {
    h += `<div class="row"><label>${tr('Web Push')}</label><label class="chkl"><input type="checkbox" id="s-wpdev" ${mine ? 'checked' : ''}> ${tr('Notify on this device')}</label>${mine ? `<button class="btn sm" data-m="wp-test" data-sub="${mine.id}">${ic('bell', 's')} ${tr('Send test to this device')}</button>` : ''}</div>`;
    if (Notification.permission === 'denied') h += hintK(tr('Notifications are blocked for this site. Allow them in the browser or system settings.'));
    else if (!mine) h += hint(tr('Your browser asks for permission once. Pushes arrive even when Kalmido is closed.'));
  }
  if (j.subs.length) {
    h += `<h4>${tr('Devices')}</h4><div class="navlist wpdevs">${j.subs.map(x => `<div class="navrow" data-wpdev="${x.id}">${ic('bell', 's')}<span>${esc(x.label || x.host)}${mine && mine.id === x.id ? ` <span class="devtag">${tr('This device')}</span>` : ''}<small class="muted" style="display:block">${esc(x.host)} · ${tr('since {0}', dayLabel(x.created_at.slice(0, 10)))}${x.last_ok ? ' · ' + tr('last push {0}', dayLabel(x.last_ok.slice(0, 10))) : ''}</small></span><button class="iconbtn" data-m="wp-del" data-sub="${x.id}" data-ep="${esc(x.endpoint)}" title="${tr('remove')}" aria-label="${tr('remove')}">${ic('x', 's')}</button></div>`).join('')}</div>`;
  }
  box.innerHTML = h;
  wpState(md, j);
  // 2.25.0 (UX-46): on top of Notifications, in one line: does THIS device ring? With "Turn on" / "Send test"
  const now = $('#s-pushnow', md);
  if (now) {
    const can = wpSupported() && !(isIOS() && !isStandalone()) && Notification.permission !== 'denied';
    now.className = 'pushnow ' + (mine ? 'on' : 'off');
    now.innerHTML = `${ic(mine ? 'bellring' : 'belloff', 's')}<span><b>${mine ? tr('This device gets notifications') : tr('This device gets no notifications')}</b>${mine ? '' : `<small>${esc(!wpSupported() ? tr('This browser does not support Web Push') : isIOS() && !isStandalone() ? tr('Add Kalmido to the Home Screen first') : Notification.permission === 'denied' ? tr('Blocked in the browser or system settings') : j.subs.length ? trn('{0} other device does', '{0} other devices do', j.subs.length) : tr('No device is turned on yet'))}</small>`}</span>`
      + (mine ? `<button class="btn sm" data-m="wp-test" data-sub="${mine.id}">${ic('bell', 's')} ${tr('Send test')}</button>` : can ? `<button class="btn sm pri" data-m="wp-on">${tr('Turn on')}</button>` : '');
  }
}
// Settings: tabbed dialog (vertical tab list on the left on desktop, a horizontally scrollable tab strip on phones).
// Every pane stays in the DOM, so one "Save" stores the server settings of all sections at once;
// language, color scheme, tab bar and the account / user actions apply immediately, as before.
// The last opened section is remembered per device (LS settingsSec).
// U05: 9 sections (8 without admin rights); Layout, Collaboration, Focus and Time tracking live in Modules now
// 2.53.0 (#1410): SET_SECS lives in setcore.js (the command palette lists the sections)
// 2.25.0 (UX-17): what each area holds, shown in the overview a phone opens with
const SET_DESC = {account: N_('Name, password, sign-in, storage'), org: N_('Members, roles, projects of the organisation'), general: N_('Language, Today, dates and reminders'), look: N_('Theme, font size, tab bar and sidebar'),
  modules: N_('What Kalmido shows'), notify: N_('Push, News and quiet hours'), integr: N_('Calendar on the phone, sharing, e-mail'), access: N_('API tokens, webhooks and agent tokens'), ai: N_('Agents and what they do'),
  assistant: N_('The built-in assistant and the projects it may read'),  // 2.75.0 (#1411)
  data: N_('Import, export, templates, backups'), users: N_('People, sign-in, server'), help: N_('How things work, about Kalmido')};
// ---- UX1 (U03, owner decision 2): settings save themselves. Every control applies at once, "Saved · Undo" shows in the
// dialog header and each change is one step in the undo history ("Changed setting: …"). Text, number and time fields save
// on blur or Enter (and after a short pause while typing); closing the dialog saves whatever is still pending.
const SETS = {  // control id -> [setting key, label, kind]
  's-celebrate': ['celebrate', N_('Celebrate completions'), 'chk'], 's-tinbox': ['today_inbox', N_('Show the basket in Today'), 'chk'],  // 2.22.0 (#681)
  's-hideblk': ['hide_blocked_today', N_('Hide tasks that are still blocked by another task'), 'chk'], 's-progsub': ['progress_subtasks', N_('Count subtasks in the progress of a project'), 'chk'],
  's-pushch': ['push_channel', N_('Channel|push'), 'sel'], 's-pushprio': ['push_priority', N_('How urgent'), 'sel'],
  's-allday': ['allday_time', N_('All-day reminder at'), 'time'], 's-defrem': ['default_reminder', N_('Default reminder'), 'sel'], 's-digest': ['digest_time', N_('Daily digest at'), 'time'],
  's-pf': ['pomo_focus', N_('Focus session'), 'pos'], 's-ps': ['pomo_short', N_('Short break'), 'pos'], 's-pl': ['pomo_long', N_('Long break'), 'pos'], 's-pe': ['pomo_long_every', N_('Long break after'), 'pos'],
  's-trnd': ['time_rounding', N_('Rounding'), 'sel'], 's-tcur': ['time_currency', N_('Currency'), 'text'], 's-ttarget': ['time_target', N_('Daily target'), 'num'],
  's-trem': ['time_remind_h', N_('Reminder after'), 'num'], 's-tstop': ['time_autostop_h', N_('Stop automatically after'), 'num'], 's-tfocus': ['time_focus', N_('Focus sessions'), 'chk'],
  's-ttz': ['tz', N_('Time zone'), 'sel'], 's-tsplit': ['time_split_midnight', N_('Entries over midnight'), 'chk'],  // 2.125.0 B (#2120)
  's-icalscope': ['ical_scope', N_('Calendar subscription'), 'sel'], 's-icalalarm': ['ical_alarms', N_('as calendar alarms'), 'chk'],
  's-caltoday': ['cal_today', N_('Events on Today'), 'chk'],
  's-dateok': ['date_confirm', N_('Confirm changes of the date with OK'), 'chk'],  // 2.6.1 (#401)
  's-qfrom': ['quiet_from', N_('Quiet from'), 'time'], 's-qto': ['quiet_to', N_('Quiet until'), 'time'],  // 2.7.0 (#413)
  's-evm-assign': ['mail_assign', N_('Assigned to me'), 'sel'], 's-evm-mention': ['mail_mention', N_('Mentioned'), 'sel'],  // 2.142.0 A (#2146): integrations.js chn_mailHtml
  's-wfrom': ['work_start', N_('Working hours from'), 'time'], 's-wto': ['work_end', N_('Working hours until'), 'time'],  // 2.10.0 (#440)
  's-wthours': ['capacity_h', N_('Hours per week'), 'text'],  // 2.125.0 A (#2118): the working week (leave.js)
  's-review': ['review_time', N_('Daily review at'), 'time'],
  's-brief': ['brief_time', N_('Morning briefing at'), 'time'],  // 2.34.0 (#264)
  's-lemo': ['list_emoji', N_('Suggest icons for new projects'), 'chk'],  // 2.32.0 (#1077)
  's-sdn': ['show_done_new', N_('Hide completed tasks in new projects'), 'chk'],  // 2.49.0 (#1535)
  's-prbg': ['prio_bg', N_('Priority as background'), 'sel'],  // 2.40.0 (#1416)
  's-pcol': ['person_colors', N_('Show colours for people'), 'chk'],  // 2.47.1 (#1721)
  's-lpdot': ['list_color_dot', N_('Project colours only as a dot'), 'chk'],  // 2.53.0 (#1426)
  's-sideic': ['side_icons', N_('Project icons'), 'sel'], 's-sideprog': ['side_progress', N_('Progress in the sidebar'), 'chk'],  // 2.36.0 (#1117)
  's-sidecnt': ['side_count', N_('Task counts in the sidebar'), 'chk'], 's-sidedot': ['side_dots', N_('Status dots of projects'), 'chk'], 's-sideshr': ['side_share', N_('Share marks (person / robot)'), 'chk'],  // 2.56.1 (#1799)
  's-sdd': ['show_done_default', N_('Completed tasks'), 'sel'],  // 2.39.1 (#1214)
  's-favq': ['fav_quiet', N_('Quieter pushes from projects without a star'), 'chk'], 's-favs': ['fav_suggest', N_('Suggest favourites'), 'chk'],  // 2.46.1 (#1361)
  's-tblacc': ['tbl_accept', N_('Accept urgent markings from others'), 'chk'],  // 2.53.0 C (#1424)
  's-pmeta': ['photo_meta_strip', N_('Remove location data from photos'), 'chk'],  // 2.61.0 B (#1819)
  's-vext': ['video_ext_ok', N_('Load YouTube and Vimeo videos without asking'), 'chk'],  // 2.240.0 D (#2886)
  's-bl9ac': ['agent_comments', N_('Comments by agents'), 'sel'],  // 2.62.0 (#1854)
  's-asst-on': ['assistant_on', N_('Use the assistant'), 'chk'],  // 2.75.0 (#1411)
  's-trd': ['chat_read_receipts', N_('Send read receipts'), 'chk'],  // 2.139.0 A (#2129)
};
// 2.62.0 (#1854): comments by agents: all | only replies to me (people's comments stay as the matrix says)
const bl9SetHtml = (s, hint) => collab() && feat('agents') ? `<div class="row"><label for="s-bl9ac">${tr('Comments by agents')}</label><select id="s-bl9ac">${[['all', N_('All')], ['replies', N_('Only replies to me')]].map(([v, n]) => `<option value="${v}" ${(s.agent_comments || 'all') === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
      ${hint(tr('Only replies to me: a comment by an agent reaches you (News and push) only when it answers your comment, follows right after your comment or mentions you. Comments by people are not affected.'))}` : '';
const SET_RENDER = ['sidebar', 'row_icons', 'row_icons_custom', 'side_count', 'side_dots', 'side_share', 'prio_bg', 'person_colors', 'list_color_dot', 'side_icons', 'side_progress', 'features', 'nav_order', 'show_done_views', 'show_done_default', 'hide_blocked_today', 'today_inbox', 'progress_subtasks', 'cal_today', 'time_target', 'lang', 'agents_hidden', 'side_people', 'side_agents'];
const SET_SLOW = ['lang', 'features', 'nav_order'];  // 2.41.2 (#1501): drawn once their language file / state is there
function setVal(el, kind) {  // the value a control stands for; undefined = not valid (nothing is saved)
  const v = el.value;
  if (kind === 'chk') return el.checked ? '1' : '0';
  if (kind === 'pos') return /^\d+$/.test(String(v).trim()) && +v >= 1 ? String(Math.min(999, +v)) : undefined;
  if (kind === 'num') { const n = parseNum(v, true) ?? NaN;  // 2.263.0 (#2976): number inputs give a point (frac)
    return String(v).trim() === '' || !Number.isFinite(n) ? undefined : String(Math.max(0, n)); }
  if (kind === 'time') return v || '';
  if (kind === 'text') return v.trim();
  return v;
}
// apply + remember a change of server settings; label = what the history shows
async function setApply(patch, label, o = {}) {
  const before = {};
  for (const k in patch) before[k] = S.settings[k] ?? '';
  if (Object.keys(patch).every(k => String(before[k]) === String(patch[k]))) return null;
  // 2.41.2 (#1501): the value counts at once (a view that reads it while the request runs), put back on an error
  // 2.269.0 B (#3014): o.send / o.back = the request body of the change / of its undo (e.g. set_delta: one entry, not the whole value)
  try { await optWrite(optSet(() => S.settings, patch), () => api('PATCH', '/api/settings', o.send || patch), () => { if (Object.keys(patch).some(k => SET_RENDER.includes(k) && !SET_SLOW.includes(k))) render(); }); } catch { settingsSync(); return false; }
  await setAfter(patch);
  const e = histAdd({label: tr('Changed setting: {0}', label), sett: true, post: settingsSync,
    undo: () => setStep(before, patch, label, o.back), redo: () => setStep(patch, before, label, o.send)});
  if (!o.quiet) setSaved(e);
  return e;
}
async function setStep(to, from, label, wire) {  // one way of a settings step; a value changed elsewhere meanwhile stays
  const body = {}, skip = [];
  // 2.290.0 (#3197): a step sent as single entries (set_delta) needs no whole-value check: the server keeps its own order and
  // entries this client does not know, so the whole value never matches; the delta itself leaves other changes alone
  for (const k in to) { if (!wire?.set_delta?.[k] && String(S.settings[k] ?? '') !== String(from[k] ?? '')) skip.push(label); else body[k] = to[k]; }
  if (!Object.keys(body).length) return {skipped: skip, none: true};
  await api('PATCH', '/api/settings', wire && !skip.length ? wire : body);  // 2.269.0 B (#3014)
  Object.assign(S.settings, body);
  await setAfter(body);
  return {skipped: skip};
}
async function setAfter(patch) {
  if ('lang' in patch) { await i18nLoad(patch.lang); LS.set('lang', patch.lang); document.documentElement.lang = patch.lang; }
  if ('features' in patch || 'nav_order' in patch) { try { await load(); } catch { /* offline: the local copy is right */ } await route(); return; }  // route: a view whose module went off
  if ('assistant_on' in patch) asst_onSync(patch.assistant_on);  // 2.75.0 (#1411): the entry points follow the switch
  if (Object.keys(patch).some(k => SET_RENDER.includes(k))) render();
}
// local (per device) settings: appearance, tab bar
function setLocal(label, get, set, to) {
  const from = get();
  if (JSON.stringify(from) === JSON.stringify(to)) return null;
  set(to);
  const e = histAdd({label: tr('Changed setting: {0}', label), sett: true, post: settingsSync,
    undo: () => { set(from); return {skipped: []}; }, redo: () => { set(to); return {skipped: []}; }});
  setSaved(e);
  return e;
}
// "Saved · Undo" in the settings header (a status line for screen readers too)
function setSaved(e) {
  const el = $$('.smodal .ssaved').pop(); if (!el) return;
  el.innerHTML = `${ic('check', 's')}<span>${tr('Saved')}</span>${e ? `<button type="button" class="linkbtn" data-m="s-undo">${tr('Undo')}</button>` : ''}`;
  el.classList.add('on'); el._e = e;
  clearTimeout(el._t); el._t = setTimeout(() => { el.classList.remove('on'); el._e = null; }, 6000);
}
// the dialog shows what the settings are now (after an undo / redo or a change on another device)
function settingsSync() {
  const md = $$('.smodal').pop(); if (!md) return;
  const s = S.settings;
  for (const [id, [k, , kind]] of Object.entries(SETS)) {
    const el = $('#' + id, md); if (!el || el === document.activeElement) continue;
    if (kind === 'chk') el.checked = k === 'celebrate' || k === 'list_emoji' || k === 'show_done_new' || k === 'side_progress' || k === 'person_colors' || k === 'ical_alarms' || k === 'cal_today' || k === 'time_focus' || k === 'side_count' || k === 'side_dots' || k === 'side_share' ? s[k] !== '0' : s[k] === '1';  // 2.56.1 (#1799): side_*
    else { el.value = s[k] ?? ''; if (el.dataset.dp) dpSync(el); }
  }
  for (const el of $$('[data-feat]', md)) el.checked = feat(el.dataset.feat);
  for (const el of $$('[data-agvis]', md)) el.checked = !agentHidden().has(+el.dataset.agvis);
  $$('[data-modrow]', md).forEach(r => r.classList.toggle('off', !feat(r.dataset.modrow)));
  mg_setSync(md);  // 2.44.0 (#1187)
  modCountsSync(md);  // 2.25.0 (UX-19)
  const nm = $('#a-name', md); if (nm && nm !== document.activeElement && S.me) nm.value = S.me.display_name;
  $$('#s-lang [data-lang-set]', md).forEach(b => b.classList.toggle('on', b.dataset.langSet === (s.lang || 'en')));
  ntfyShow(md);
  const lk = $('#s-lookin', md); if (lk) lk.innerHTML = lookHtml();
  rsy_sync(md);  // 2.56.1 (#1799)
  if (typeof wt_sync === 'function') wt_sync(md);  // 2.125.0 A (#2118)
  md._tabDraw?.();
  md._sideDraw?.();
}
function ntfyShow(md) {  // U06: the ntfy details only when ntfy is (also) the channel
  const ch = $('#s-pushch', md)?.value || S.settings.push_channel || 'webpush';
  $('#s-ntfy', md)?.classList.toggle('hidden', !!S.webpush?.enabled && ch === 'webpush');
}
async function setLang(code) {
  if (code === (S.settings.lang || 'en')) return;
  const from = S.settings.lang || 'en';
  try { await api('PATCH', '/api/settings', {lang: code}); } catch { return; }
  S.settings.lang = code;
  await setAfter({lang: code});
  const md = $('.smodal');
  if (md) { md._noflush = true; md.remove(); settingsModal('general'); }
  const e = histAdd({label: tr('Changed setting: {0}', tr('Language')), sett: true, post: () => { const m = $('.smodal'); if (m) { m._noflush = true; m.remove(); settingsModal(LS.get('settingsSec', 'general')); } },
    undo: () => setStep({lang: from}, {lang: code}, tr('Language')), redo: () => setStep({lang: code}, {lang: from}, tr('Language'))});
  setSaved(e);
}
// U04: the modules, grouped, each with one sentence; admins also get the switch for the whole server (collaboration, time)
// 2.44.0 (#1187): Office, Time, Review and Home are ONE switch each ("a:<area>", areas.js), their parts below it
// 2.53.0 (#1410): MOD_GROUPS lives in setcore.js (the first-start setup counts the modules)
const MOD_DESC = {office: N_('Quotations, invoices, services, text blocks and PDF documents'),  // 2.36.1 (#1021)
  cal: N_('Month, week and day view of your tasks'), timeline: N_('Tasks with start and end as bars over time'), kanban: N_('Projects as boards with columns'),
  matrix: N_('Urgent and important in four quadrants'), habits: N_('Daily and weekly habits with streaks'), pomo: N_('Pomodoro timer and stopwatch'),
  stats: N_('Completions, on-time rate, focus time and streaks'), collab: N_('Share projects, assign tasks, @mentions, activity and News'),
  comments: N_('Timestamped notes on tasks'),
  time: N_('Timers and manual time entries on tasks, reports and CSV export'), progress: N_('Progress per project and the project status (“Where is it stuck?”)'),
  deps: N_('Tasks blocked by other tasks, with arrows in the timeline (Gantt)'), fields: N_('Own fields per project, such as budget, client or phase'),
  events: N_('Appointments and shared calendars, synced with the phone'),
  contacts: N_('Address books, synced with the phone'),
  family: N_('Shopping, chores taking turns, meal plan, birthdays, children\'s accounts'),
  // 2.22.0 (#663): Home & life
  contracts: N_('Contracts and subscriptions with their cost, notice period and a reminder before the last day to cancel'),
  home: N_('Devices with their warranty and receipt, and upkeep that comes back: heating, smoke detectors, tyres'),
  care: N_('Reminds you when you have not been in touch for long (needs Contacts)'),
  health: N_('Doctor\'s appointments, check-ups, medication – private, never for agents'),
  review: N_('Your day and week in review (done, still open, coming up) with a private journal'),
  travel: N_('Trips as projects with dates, bookings, things to do before you leave and a packing list'),
  reading: N_('Read later and bookmarks with a preview and tags – never for agents'),  // 2.97.0 A (#1950); 2.172.0 B (#2679)
  budget: N_('Income and expenses per month, with bank CSV – never for agents'),  // 2.72.0 (#1333)
  feeds: N_('Blogs and news sites in one list – never for agents')};  // 2.85.0 B (#1162); 2.172.0 B (#2677)
// 2.25.0 (UX-20): Integrations start with what people want to do, in plain words; a tap jumps to the part that does it
// (the technical parts below stay for those who need them)
function integrCardsHtml() {
  const C = [['cal', N_('Calendar on your phone'), N_('Your tasks with a date in the phone’s calendar app'), S.caldav?.enabled && S.me ? '#s-dav-h' : '#s-ical-h'],
    ['phone', N_('Share from your phone'), N_('Text, links and pictures from other apps into Kalmido'), '#s-share-h'],
    ['send', N_('Send by e-mail'), N_('Forward an e-mail and it becomes a task'), '#s-mail-h'],
    ...(feat('docs') && typeof dsc_integrHtml === 'function' ? [['download', N_('Scans from your computer'), N_('Folder watcher program for Mac and Windows, scan inboxes'), '#s-scan-h']] : []),  // 2.353.0 B (#2773)
    ...(feat('docs') && typeof pl_setHtml === 'function' ? [['file', N_('Documents from Paperless-ngx'), N_('Bring the documents of your Paperless-ngx server into Kalmido'), '#s-pl-h']] : [])];  // 2.87.9 (#1936)
  // 2.353.0 B (#2773): API tokens and webhooks live in Access: a link here, no second copy
  return `<div class="icards">${C.map(([i, n, d, to]) => `<button type="button" class="icard" data-jump="${to}">${ic(i, 's')}<span><b>${tr(n)}</b><small>${tr(d)}</small></span>${ic('chev', 's fcar')}</button>`).join('')}</div>${acz_linkHtml(S.api?.enabled || S.webhooks?.enabled)}`;
}
function modulesHtml(hint) {
  const s = S.settings;
  const opt = (k, body) => k === 'pomo' ? `<details class="mopt"><summary>${tr('Focus settings')}</summary>
      <div class="row"><label for="s-pf">${tr('Focus session')}</label><input type="number" id="s-pf" value="${esc(s.pomo_focus)}" min="1" inputmode="numeric" class="numin"><span class="muted">${tr('min')}</span></div>
      <div class="row"><label for="s-ps">${tr('Short break')}</label><input type="number" id="s-ps" value="${esc(s.pomo_short)}" min="1" inputmode="numeric" class="numin"><span class="muted">${tr('min')}</span></div>
      <div class="row"><label for="s-pl">${tr('Long break')}</label><input type="number" id="s-pl" value="${esc(s.pomo_long)}" min="1" inputmode="numeric" class="numin"><span class="muted">${tr('min')}</span></div>
      <div class="row"><label for="s-pe">${tr('Long break after')}</label><input type="number" id="s-pe" value="${esc(s.pomo_long_every)}" min="1" inputmode="numeric" class="numin"><span class="muted">${tr('pomos')}</span></div></details>`
    : k === 'time' && timeOn() ? `<details class="mopt"><summary>${tr('Time tracking settings')}</summary>
      <div class="row"><label for="s-trnd">${tr('Rounding')}</label><select id="s-trnd">${[0, 5, 6, 10, 15, 30].map(v => `<option value="${v}" ${String(v) === String(s.time_rounding || '0') ? 'selected' : ''}>${v ? tr('up to {0} min per entry', v) : tr('none')}</option>`).join('')}</select></div>
      ${hint(tr('Rounding applies to the report, the CSV export and the timesheet; the tracked times stay exact. Hourly rate: in the project dialog (owner).'))}
      <div class="row"><label for="s-tcur">${tr('Currency')}</label><input id="s-tcur" value="${esc(s.time_currency ?? '€')}" maxlength="8" class="numin"></div>
      <div class="row"><label for="s-ttarget">${tr('Daily target')}</label><input type="number" id="s-ttarget" value="${esc(s.time_target || '0')}" min="0" max="24" step="0.25" class="numin"><span class="muted">${tr('hours, 0 = none')}</span></div>
      <div class="row"><label for="s-trem">${tr('Reminder after')}</label><input type="number" id="s-trem" value="${esc(s.time_remind_h ?? '4')}" min="0" max="48" step="0.5" class="numin"><span class="muted">${tr('hours, push “still running?”, 0 = off')}</span></div>
      ${tsl_setRows(s, hint)}
      <div class="row"><label for="s-tstop">${tr('Stop automatically after')}</label><input type="number" id="s-tstop" value="${esc(s.time_autostop_h ?? '12')}" min="0" max="72" step="0.5" class="numin"><span class="muted">${tr('hours, end = start + value, 0 = off')}</span></div>
      <div class="row"><label>${tr('Focus sessions')}</label><label class="chkl wtfocus"><input type="checkbox" id="s-tfocus" ${s.time_focus !== '0' ? 'checked' : ''}> ${tr('count as time entries (not while a timer runs)')}</label></div></details>` : '';
  const row = k => k.startsWith('a:') ? mg_modAreaHtml(k.slice(2), x => modRowHtml(x, opt)) : modRowHtml(k, opt);  // 2.44.0 (#1187)
  return `<h4 id="s-purpose-h">${tr('What do you use Kalmido for?')}</h4>${purposeCards(S.settings.purpose || '')}${pm_allHtml('s-modsall', pm_allShown())}
    ${pk2_setupHtml()}
    ${hint(tr('Switched off disappears from the menus; nothing is deleted.'))}
    <div class="modtot muted" id="s-modtot">${esc(modCount())}</div>
    ${MOD_GROUPS.map(([g, ks], gi) => { const r = modGroupKeys(ks); return r.length ? `<details class="modgrp" data-modgrp="${gi}"><summary><span class="mgn">${tr(g)}</span><span class="mgc muted">${esc(modGroupCount(r))}</span>${ic('chev', 's fcar')}</summary><div class="modlist">${r.map(row).join('')}</div></details>` : ''; }).join('')}`;
}
// 2.25.0 (UX-19): the module groups start folded and say how many are on ("3 of 4 on"); the total on top counts the same
// switches (every module shown here), and the setup counts against it too
const modGroupKeys = ks => ks;
// 2.171.0 (#2676): the counts go by the single modules, an area by its parts (Home: home & life's six, family, budget,
// feeds), so "x of y" matches the switches; what the server switched off for everyone does not count (as pma_full)
const modUnits = r => { const f = new Set(pma_full()); return [...new Set(r.flatMap(k => k.startsWith('a:') ? mg_feats(k.slice(2)) : [k]))].filter(k => f.has(k)); };
const modGroupCount = r => { const u = modUnits(r); return tr('{0} of {1} on', u.filter(k => feat(k)).length, u.length); };
const modAll = () => MOD_GROUPS.flatMap(([, ks]) => modGroupKeys(ks));
const modCount = () => { const u = modUnits(modAll()); return tr('{0} of {1} modules on', u.filter(k => feat(k)).length, u.length); };
function modCountsSync(md) {
  const t = $('#s-modtot', md); if (t) t.textContent = modCount();
  const pma = $('#s-modsall', md); if (pma) pma.checked = pm_allShown();  // 2.171.0 (#2676)
  for (const d of $$('[data-modgrp]', md)) { const r = modGroupKeys(MOD_GROUPS[+d.dataset.modgrp][1]), c = $('.mgc', d); if (c) c.textContent = modGroupCount(r); }
}
// 2.306.0 B (#2887): health and journal entries are special categories of personal data: a plain note in the module row
// (2.312.0 B #3264: MOD_PRIV / modPrivHtml in lazyload.js, shared with the area switch and the first-run setup)
// one module switch (Settings > Modules; 2.6.0 (K09): the agents switch only there, Settings > Agents links to it)
function modRowHtml(k, opt = () => '') {
  const adm = !!S.me?.is_admin;
  const n = FEATS.find(x => x[0] === k)?.[1] || k, srv = k === 'collab' ? S.collabAll !== false : k === 'time' ? S.timeAll !== false : true;
  const all = adm && (k === 'collab' || k === 'time') ? `<label class="mall" title="${esc(k === 'collab' ? tr('Off: nobody can share projects, assign tasks, comment, or get News and collaboration notifications; shared projects are then only visible to their owner.') : tr('Off: nobody sees timers, time entries or reports; running timers are stopped at that moment, focus sessions no longer become time entries.'))}"><span class="swc"><input type="checkbox" id="${k === 'collab' ? 's-collaball' : 's-timeall'}" ${srv ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('for everyone')}</span></label>${ad_markHtml(k === 'collab' ? 's-collaball-a' : 's-timeall-a')}` : '';
  return `<div class="modrow ${feat(k) ? '' : 'off'}" data-modrow="${k}"><label class="mmain"><span class="swc"><input type="checkbox" data-feat="${k}" ${feat(k) ? 'checked' : ''} ${srv ? '' : 'disabled'}><span class="swt" aria-hidden="true"></span></span><span><b>${tr(n)}</b><small class="muted">${tr(MOD_DESC[k] || FEAT_DESC[k] || '')}</small>${modPrivHtml([k])}${srv ? '' : `<small class="muted cnote" id="${k === 'collab' ? 's-collabnote' : 's-timenote'}">${tr('Turned off on this server, for everyone. Your own setting applies again once an admin turns it back on.')}</small>`}</span></label>${all}${opt(k)}</div>`;
}
// 2.46.6 (#1710): an admin switch that stays next to the own setting says so: "Admin · applies to everyone" + a jump to
// the same switch under Administration (adSel = the id there)
const ad_markHtml = adSel => `<span class="ad-mark"><span class="ad-tag">${tr('Admin · applies to everyone')}</span><button type="button" class="linkbtn ad-open" data-adopen="${adSel}">${tr('Open in Administration')}</button></span>`;
// 2.46.6 (#1710): Administration > Server > Whole server: collaboration and time tracking for everyone (the same switches
// as in Modules, there with the mark above)
function ad_allSwHtml() {
  const sw = (id, on, n, d) => `<label class="wide"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}><span>${tr(n)}<small class="muted">${tr(d)}</small></span></label>`;
  return sw('s-collaball-a', S.collabAll !== false, N_('Collaboration for everyone'), N_('Off: nobody can share projects, assign tasks, comment, or get News and collaboration notifications; shared projects are then only visible to their owner.'))
    + sw('s-timeall-a', S.timeAll !== false, N_('Time tracking for everyone'), N_('Off: nobody sees timers, time entries or reports; running timers are stopped at that moment, focus sessions no longer become time entries.'));
}
// 2.0.5 (#313): Settings > Agents bundles the agents: what they are, the switch, how they get lists, their status;
// admins also manage them here (was Settings > Administration > Agents; settingsModal('agents') still lands here).
// 2.5.1 (#393): four sub-tabs instead of one long page: Agents (cards, Add agent + Setup guide), Lists (sharing + tidy table),
// Usage (one summary card per agent, the charts behind "Details"), Log (admins). The last one is remembered per device;
// settingsModal('agents' / 'usage' / 'activity') opens the matching one. Each sub-tab loads its data only when shown.
// 2.7.0 (#405 S2): the Agents page only with the module on, or for an admin while agents exist (they manage them there)
// 2.53.0 (#1410): aiPaneOn lives in setcore.js (the command palette asks it)
// 2.29.0 (#1024): ONE "Set up" (first question: for me / for the team); the server-wide switches are "Administration" (admins)
// 2.46.6 (#1710): Log and the server-wide rules moved to Settings > Administration > Agents (ADM_SUBS); old jumps land there
const AI_SUBS = [['agents', 'bot', N_('Status|agents')], ['lists', 'list', N_('Projects')], ['usage', 'chart', N_('Usage')], ['setup', 'help', N_('Set up|agents')], ['safe', 'lock', N_('Use safely')]];  // 2.30.0 (#920): Use safely  // 2.7.2 (#420): Set up
const aiSubs = () => AI_SUBS.filter(([k]) => k === 'usage' ? !!S.me?.is_admin || (S.agents || []).length > 0 : true);
function aiSubCur(want) { const ks = aiSubs().map(x => x[0]), k = want || LS.get('aiSub', 'agents'); return ks.includes(k) ? k : 'agents'; }
function aiHtml(hint, want) {
  const adm = !!S.me?.is_admin, ags = S.agents || [], cur = aiSubCur(want);
  const mine = S.lists.some(l => !l.archived && !l.is_inbox && (canManage(l) || l.owner_id !== S.me?.id));  // 2.29.0 (#345): shared ones too
  const pane = (k, body) => `<div class="aisp" data-aisp="${k}" id="aisp-${k}" role="tabpanel" aria-labelledby="ais-${k}" ${k === cur ? '' : 'hidden'}>${body}</div>`;
  const subs = aiSubs();
  return `<div class="seg aisub" role="tablist" aria-label="${esc(tr('Agents'))}">${subs.map(([k, i, n]) => `<button type="button" role="tab" id="ais-${k}" data-aisub="${k}" aria-controls="aisp-${k}" aria-selected="${k === cur}" class="${k === cur ? 'on' : ''}">${ic(i, 's')}<span>${tr(n)}</span></button>`).join('')}</div>
    ${pane('agents', `<details class="shelp sdet aiexp" ${ags.length ? '' : 'open'}><summary>${tr('What are agents?')}</summary>
      <p>${tr('An agent is a team member for an AI assistant or a bot (Claude Code, Codex, n8n, a local model …): it works only through the API, is never an admin and sees only the projects shared with it. Kalmido tells it about mentions, assignments, chat messages and reactions by webhook or through an event queue it polls; Kalmido itself never starts an agent.')} <a href="${API_DOCS.replace('API.md', 'AGENTS.md')}" target="_blank" rel="noopener noreferrer">${tr('How to connect an agent')}</a></p></details>
    ${pbHelpHtml()}
    ${feat('agents') ? '' : `<div class="shint aimodoff">${ic('grid', 's')} <span>${tr('The Agents module (the tab with their status, jobs to approve and the chat) is switched off for you.')}</span> <button class="btn sm" data-m="go-modules">${tr('Open Modules')}</button></div>`}
    ${collab() ? '' : hint(tr('Agents work together with you in shared projects: switch on Collaboration (Settings > Modules) as well.'))}
    <div class="members aglist" id="${adm ? 's-ags' : 's-myags'}"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="row aibtns">${adm ? `<button class="btn sm" data-ag="new" aria-haspopup="menu">${ic('plus', 's')} ${tr('Add agent…')}</button>` : `<button class="btn sm" data-aigo="setup">${ic('plus', 's')} ${tr('Personal agent…')}</button>`}<button class="btn sm" data-m="ag-guide" title="${esc(tr('Set up an agent step by step, or let Claude Code do it'))}">${ic('help', 's')} ${tr('How to set one up')}</button></div>
    ${acz_linkHtml(true)}${''/* 2.166.0 (#2633) */}
    ${agDotsHtml(hint)}`)}
    ${pane('lists', `<h4 id="s-ai-lists-h">${ags.length > 1 ? tr('Which projects they see') : tr('Which projects it sees')}</h4>
    ${hint(tr('Share below or in the project’s Share dialog; taking a project out ends the access at once.'))}
    ${mine && collab() ? `<div class="aishare" id="s-ai-share"></div><div class="aitblctl" id="s-ai-tblctl"></div>
    <div class="aitbl" id="s-ai-tbl" role="table" aria-labelledby="s-ai-lists-h"><div class="muted mhint">${tr('Loading…')}</div></div>` : `<div class="muted mhint">${tr('You do not manage any project yet.')}</div>`}`)}
    ${subs.some(x => x[0] === 'usage') ? pane('usage', `${hint(adm ? tr('What the agents report about their model usage: tokens and, if they send it, the cost. You see every agent; limits are set per agent (Edit).') : tr('What the agents in your projects report about their model usage, counted in the projects you see.'))}
    <div class="aiu" id="s-aiu"></div>`) : ''}
    ${pane('setup', agSetupPaneHtml(hint))}
    ${pane('safe', agSafeHtml())}`;
}
// ---- 2.7.2 (#420) Settings > Agents > Set up: my personal agents (when an admin allows them), the admins' switch for
// that, and the two guides (a team agent on a server / a personal agent on your own computer), each for Linux, macOS and
// Windows. The texts of the guides: AG_GUIDES (the same steps as docs/AGENTS.md).
function agSetupPaneHtml(hint) {
  const adm = !!S.me?.is_admin, g = LS.get('agGuide', adm ? 'team' : 'own'), os = LS.get('agOs', /Win/.test(navigator.platform || '') ? 'win' : /Mac/.test(navigator.platform || '') ? 'mac' : 'linux');
  const seg = (k, cur, opts) => `<div class="seg agsseg" role="tablist" data-agseg="${k}">${opts.map(([v, n, i]) => `<button type="button" role="tab" data-agsv="${v}" aria-selected="${v === cur}" class="${v === cur ? 'on' : ''}">${i ? ic(i, 's') : ''}<span>${tr(n)}</span></button>`).join('')}</div>`;
  return `<h4 id="s-agg-h">${tr('Who is the agent for?')}</h4>
    ${seg('guide', g, [['own', N_('For me'), 'user'], ['team', N_('For the team'), 'users']])}
    <p class="agwhy muted" id="s-agwhy">${agWhyHtml(g, adm)}</p>
    ${seg('os', os, [['linux', 'Linux'], ['mac', 'macOS'], ['win', 'Windows']])}
    <div class="agguidebox" id="s-agguide" role="tabpanel">${agSetupHtml(g, os)}</div>
    <div class="row aibtns"><button class="btn sm" data-m="ag-guide-cc" title="${esc(tr('Set up an agent step by step, or let Claude Code do it'))}">${ic('bot', 's')} ${tr('Let Claude Code set it up (Linux)')}</button></div>
    <h4 id="s-myown-h">${tr('Your personal agents')}</h4>
    ${hint(tr('Only you can chat with it; it runs on your own computer.'))}
    <div class="members aglist" id="s-myown" aria-labelledby="s-myown-h"><div class="muted mhint">${tr('Loading…')}</div></div>`;
}
// 2.29.0 (#1024): one sentence per choice, so the difference is clear before the steps
function agWhyHtml(g, adm) {
  return g === 'team' ? esc(tr('A team agent belongs to the team (in the workspaces: the organisation). An admin creates it under Status > Add agent; it works in the projects shared with it, for the people those projects allow.')) + (adm ? '' : ' ' + esc(tr('Ask an admin to create it.')))
    : esc(tr('A personal agent is only yours: only you see it, chat with it and share your projects with it. You create it below and run it on your own computer.'));
}
// 2.29.0 (#1024): the server-wide switches (admins), no longer mixed into "Set up"
function agAdminPaneHtml(hint) {
  return `${hint(tr('Server-wide rules for every agent. Agents themselves are created under Settings > Agents: Status (team) or Set up (personal).'))}
    <h4 id="s-uag-h">${tr('Personal agents for everyone')}</h4>
    <div class="row"><label class="chkl swl"><span class="swc"><input type="checkbox" id="s-uag"><span class="swt" aria-hidden="true"></span></span><span>${tr('Users may create their own agents')}</span></label></div>
    <div class="row"><label for="s-uagmax">${tr('Per person at most')}</label><input id="s-uagmax" type="number" inputmode="numeric" min="1" max="20" value="2" class="numin"></div>
    ${hint(tr('Off by default. You see every agent under Status and can pause or delete it.'))}
    <h4 id="s-sclim-h">${tr('Permission limit')}</h4>
    ${hint(tr('What agents and API tokens may get at most on this server. A permission switched off here applies to every existing token at once.'))}
    <div id="s-sclim" aria-labelledby="s-sclim-h"></div>`;
}
async function agSetupDraw(md) {
  if (S.me?.is_admin) ad_agPolicyDraw(md);  // 2.46.6 (#1710): the rules sit in Administration > Agents (no #s-myown needed)
  const box = $('#s-myown', md); if (!box) return;
  let j;
  try { j = await api('GET', '/api/my/agents'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  for (const a of j.agents || []) if (a.color) (S.colors ||= {})[a.id] = a.color;  // 2.47.1 (#1721)
  const row = a => `<div class="mrow agsrow ${a.enabled ? '' : 'off'}" data-myag="${a.id}">${avBtn(a.id, a.name)}<span class="n"><span class="agnm"><b>${esc(a.name)}</b> <span class="muted">${esc(a.username)}</span>${av_wsBtn(a)}</span>
      <small class="muted agfacts">${hdot(agentHst(a))}${((t) => `<span class="agft" title="${esc(t)}">${esc(t)}</span>`)([a.enabled ? agentSt(a) : a.admin_paused ? tr('paused by an admin') : tr('paused'), trn('{0} project', '{0} projects', (a.lists || []).length), scopeSummary(a.effective_scopes || a.scopes)].join(' · '))}</small></span>
    <span class="agacts">${av_setupBtn(a)}<button class="iconbtn" data-myag-act="work" title="${esc(tr('Work style and notifications'))}" aria-label="${esc(tr('Work style and notifications'))}">${ic('cog', 's')}</button><button class="iconbtn" data-myag-act="perm" title="${esc(tr('Permissions'))}" aria-label="${esc(tr('Permissions of {0}', a.name))}">${ic('lock', 's')}</button><button class="iconbtn" data-myag-act="token" title="${esc(tr('New API token'))}" aria-label="${esc(tr('New API token'))}">${ic('key', 's')}</button>
      <button class="iconbtn ${a.enabled ? 'danger' : ''}" data-myag-act="pause" title="${esc(a.enabled ? tr('Pause|agent') : tr('Resume'))}" aria-label="${esc(a.enabled ? tr('Pause|agent') : tr('Resume'))}" ${!a.enabled && a.admin_paused ? 'disabled' : ''}>${ic(a.enabled ? 'pause' : 'play', 's')}</button>
      <button class="iconbtn danger" data-myag-act="del" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete'))}">${ic('trash', 's')}</button></span></div>`;
  const add = j.allowed && j.count < j.max ? `<div class="row myagnew"><input id="myag-name" placeholder="${esc(tr('Display name'))}" aria-label="${esc(tr('Display name'))}" maxlength="60"><input id="myag-user" placeholder="${esc(tr('Username, e.g. my-claude'))}" aria-label="${esc(tr('Username'))}" title="${esc(tr('for the login and @mentions'))}" maxlength="32" autocapitalize="off" autocomplete="off" spellcheck="false"><input id="myag-prov" placeholder="${esc(tr('Where it runs, e.g. Claude (Anthropic, USA)'))}" aria-label="${esc(tr('Where it runs'))}" maxlength="80"><button class="btn sm pri" data-myag-act="new">${ic('plus', 's')} ${tr('Create agent')}</button></div>
    <div class="shint keep">${esc(trn('You can have {0} personal agent.', 'You can have {0} personal agents.', j.max))} ${esc(tr('You connect it yourself and are responsible for the provider; everyone in the project sees where it runs.'))}</div>${av_whichHtml()}` : '';  // 2.46.6 (#1716)
  box.innerHTML = (j.agents.map(row).join('') || (j.allowed ? '' : `<div class="muted mhint">${tr('Your organisation does not let members connect agents (an admin can allow it: Administration > Organisation).')}</div>`)) + add;
  userNameFollow(box, 'myag-name', 'myag-user');  // 2.28.0 (#926)
}
// 2.46.6 (#1710): the admins' agent rules (Administration > Agents), filled wherever the pane is
async function ad_agPolicyDraw(md) {
  if (!$('#s-uag', md)) return;
  try {
    const p = await api('GET', '/api/admin/agent-policy'); const sw = $('#s-uag', md), mx = $('#s-uagmax', md); if (sw) sw.checked = p.user_agents; if (mx) { mx.value = p.max_per_user; mx.disabled = !p.user_agents; }
    const lb = $('#s-sclim', md);  // 2.15.0 (#479): the admin's limit, one grid for agents and one for personal tokens
    if (lb && p.scope_limit) lb.innerHTML = [['agents', N_('Agents')], ['tokens', N_('Personal API tokens')]].map(([k, n]) => `<fieldset class="sclim"><legend>${tr(n)}</legend><div class="scgrid">${p.scopes.filter(x => (k !== 'agents' || (x !== 'account' && x !== 'private' && x !== 'docs:upload')) && (k !== 'tokens' || x !== 'office')).map(x => `<label class="chkl sc"><input type="checkbox" data-sclim="${k}" data-scope="${x}" ${p.scope_limit[k].includes(x) ? 'checked' : ''} ${x === 'read' ? 'disabled' : ''}><span>${esc(tr(SCOPE_SHORT[x] || x))}</span></label>`).join('')}</div></fieldset>`).join('');
  } catch { /* offline */ }
}
function agSetupWire(md) {
  md.addEventListener('click', async e => {
    const sg = e.target.closest('[data-agsv]');
    if (sg) {
      const k = sg.closest('[data-agseg]').dataset.agseg; LS.set(k === 'guide' ? 'agGuide' : 'agOs', sg.dataset.agsv);
      $$(`[data-agseg="${k}"] [data-agsv]`, md).forEach(b => { const on = b === sg; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
      const box = $('#s-agguide', md); if (box) box.innerHTML = agSetupHtml($('[data-agseg="guide"] .on', md)?.dataset.agsv || 'own', $('[data-agseg="os"] .on', md)?.dataset.agsv || 'linux');
      const why = $('#s-agwhy', md); if (why) why.innerHTML = agWhyHtml($('[data-agseg="guide"] .on', md)?.dataset.agsv || 'own', !!S.me?.is_admin);  // 2.29.0 (#1024)
      return;
    }
    if (e.target.closest('[data-m="ag-guide-cc"]')) { agGuideModal(); return; }
    const b = e.target.closest('[data-myag-act]'); if (!b) return;
    const box = $('#s-myown', md), k = b.dataset.myagAct, a = (box?._j?.agents || []).find(x => x.id === +b.closest('[data-myag]')?.dataset.myag);
    try {
      if (k === 'new') {
        const un = $('#myag-user', md).value.trim().toLowerCase(); if (!un) { need($('#myag-user', md)); return; }
        if (userNameBad(un)) { toast(userNameBad(un)); need($('#myag-user', md)); return; }  // 2.28.0 (#926)
        b.disabled = true;
        const r = await api('POST', '/api/my/agents', {username: un, display_name: $('#myag-name', md).value.trim(), provider: $('#myag-prov', md)?.value.trim() || ''});
        av_setupOffer(r, `/api/my/agents/${r.id}`, r.token);  // 2.46.6 (#1709): set it up now; the token only on request
        await load(); render();
      }
      if (!a) { agSetupDraw(md); return; }
      if (k === 'token') { agTokenModal(a, `/api/my/agents/${a.id}/token`); return; }
      if (k === 'setup') { ains_setupModal(a, `/api/my/agents/${a.id}`); return; }  // 2.44.0 (#1517)
      if (k === 'work') { awOpen(a); return; }  // 2.236.0 A (#2904-#2911)
      if (k === 'ws') { av_wsMenu(b, a, () => agSetupDraw(md)); return; }  // 2.46.6 (#1708): its workspace
      if (k === 'perm') {  // 2.15.0 (#479): what my agent may do (within the admin's limit) and from where
        const pmd = permModal(tr('Permissions of {0}', a.name), box._j.scopes || [], a.scopes, a.allowed_ips, async (scopes, ips, pm) => {
          await calReq('PATCH', `/api/my/agents/${a.id}`, {scopes, allowed_ips: ips, list_ids: listCapVal(pm, 'pm-lcap')}); toast(tr('Saved')); agSetupDraw(md);  // 2.30.0 (#919)
        }, `<div class="row"><label>${tr('Projects')}</label>${listCapHtml(a.list_ids, a.lists, 'pm-lcap')}</div>${bridgesHtml(a)}<div class="shint keep">${tr('Deleting projects or fields, emptying the trash, changing 10 or more tasks at once, moving projects, folders and sharing always wait for your approval.')}</div><div class="shint keep">${tr('{0} answers when it next looks at its events (right away with a webhook or long-polling). It only sees the projects shared with it.', esc(a.name))}</div>${typeof oa_switchRowHtml === 'function' ? oa_switchRowHtml(a.id) : ''}`);
        if (typeof oa_switchLoad === 'function') oa_switchLoad(pmd);  // 2.51.0 A (#1348): the office switch of my agent (saved at once)
        if (typeof agz_wire === 'function') { pmd.querySelector('.foot')?.insertAdjacentHTML('beforebegin', agz_html(a, true)); agz_wire(pmd, a, `/api/my/agents/${a.id}`); }  // 2.233.0 B (#3189): the interim summary (saved at once)
        return;
      }
      if (k === 'pause') {
        if (a.enabled && !await askConfirm(tr('Pause {0}?', a.name), tr('Its API token is refused and no events are sent until you resume it. Nothing is deleted.'), {ok: tr('Pause'), danger: true})) return;
        await api('PATCH', `/api/my/agents/${a.id}`, {enabled: !a.enabled}); toast(a.enabled ? tr('Paused') : tr('Resumed'));
        await load(); render();
      }
      if (k === 'del') {
        if (!await ains_askRemove(`/api/my/agents/${a.id}`, tr('Delete the agent “{0}”?', a.name), tr('Its tokens, events, jobs and chats are deleted; projects it owns come to you. Its comments stay.'), {ok: tr('Delete'), danger: true})) return;  // 2.47.3 (#1729): shows the uninstall commands of its computers
        await api('DELETE', `/api/my/agents/${a.id}`); toast(tr('Deleted'));
        await load(); render();
      }
    } catch { /* api() showed it */ } finally { b.disabled = false; }
    agSetupDraw(md);
  });
  md.addEventListener('change', async e => {
    const lk = e.target.dataset?.sclim;
    if (lk) {  // 2.15.0 (#479)
      const v = $$(`[data-sclim="${lk}"]:checked`, md).map(x => x.dataset.scope);
      try { await api('PUT', '/api/admin/agent-policy', {scope_limit: {[lk]: v}}); toast(tr('Saved')); } catch { /* shown */ }
      if (lk === 'agents') api('GET', '/api/admin/agents').then(j => { S.agOffer = j.scopes; }).catch(() => {});  // the agent dialog greys out what is no longer allowed
      return;
    }
    if (e.target.id !== 's-uag' && e.target.id !== 's-uagmax') return;
    const body = e.target.id === 's-uag' ? {user_agents: e.target.checked} : {max_per_user: Math.max(1, Math.min(20, +e.target.value || 2))};
    try { await api('PUT', '/api/admin/agent-policy', body); toast(tr('Saved')); } catch { /* shown */ }
    agSetupDraw(md);
  });
}
// 2.31.0 (#1046): a sub-tab strip wider than the screen scrolls sideways; the chosen tab is scrolled into view (only the strip
// moves, not the dialog)
function segReveal(b) {
  const st = b?.parentElement; if (!st) return;
  const go = () => { if (!b.isConnected || st.scrollWidth <= st.clientWidth + 1) return;
    const sr = st.getBoundingClientRect(), br = b.getBoundingClientRect();
    if (br.left < sr.left) st.scrollLeft -= sr.left - br.left + 8; else if (br.right > sr.right) st.scrollLeft += br.right - sr.right + 8; };
  requestAnimationFrame(go); setTimeout(go, 400);  // once more when the pane has loaded (a scrollbar of the dialog narrows the strip)
}
// shows one sub-tab and loads what it needs (save: remember it for this device)
function aiSubShow(md, want, save) {
  const k = aiSubCur(want); if (save) LS.set('aiSub', k);
  $$('[data-aisub]', md).forEach(b => { const on = b.dataset.aisub === k; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
  segReveal($(`[data-aisub="${k}"]`, md));
  $$('[data-aisp]', md).forEach(p => { p.hidden = p.dataset.aisp !== k; });
  if (k === 'agents') return agDraw(md);
  if (k === 'lists') return aiTblDraw(md);
  if (k === 'usage') return aiuDraw(md);
  if (k === 'log') return audDraw(md);
  if (k === 'setup' || k === 'admin') return agSetupDraw(md);  // 2.29.0 (#1024): the admin switches are filled there too
}
// ---- 2.24.0 (#826): Settings > Administration in five sub-tabs (the pattern of Agents): People, Sign-in, Organisation,
// Server, Log & errors. The last one is remembered per device; the settings search opens the sub-tab of its hit.
// 2.46.6 (#1710): + Agents (the server-wide agent rules, the API log and the admins' usage alert, before in Settings > Agents)
const ADM_SUBS = [['users', 'users', N_('People|admin')], ['signin', 'key', N_('Sign-in')], ['org', 'home', N_('Organisation')], ['agents', 'bot', N_('Agents')], ['server', 'grid', N_('Server')], ['log', 'alert', N_('Log & errors')]];
const ad_admSubs = () => ADM_SUBS.filter(([k]) => k !== 'agents' || !!S.api?.enabled);  // agents need the API
const ad_admFocus = f => ({users: 'users', groups: 'users', activity: 'agents', agentpolicy: 'agents', server: 'server'})[f];  // settingsModal(focus) -> sub-tab
function admSubCur(want) { const k = want || LS.get('admSub', 'users'); return ad_admSubs().some(x => x[0] === k) ? k : 'users'; }
function admSubsHtml(parts, want) {
  const cur = admSubCur(want);
  return `<div class="seg aisub admsub" role="tablist" aria-label="${esc(tr('Administration'))}">${ad_admSubs().map(([k, i, n]) => `<button type="button" role="tab" id="adms-${k}" data-admsub="${k}" aria-controls="admp-${k}" aria-selected="${k === cur}" class="${k === cur ? 'on' : ''}">${ic(i, 's')}<span>${tr(n)}</span></button>`).join('')}</div>
    ${ad_admSubs().map(([k]) => `<div class="aisp admp" data-admp="${k}" id="admp-${k}" role="tabpanel" aria-labelledby="adms-${k}" ${k === cur ? '' : 'hidden'}>${parts[k] || ''}</div>`).join('')}`;
}
function admSubShow(md, want, save) {
  const k = admSubCur(want); if (save) LS.set('admSub', k);
  $$('[data-admsub]', md).forEach(b => { const on = b.dataset.admsub === k; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
  segReveal($(`[data-admsub="${k}"]`, md));
  $$('[data-admp]', md).forEach(p => { p.hidden = p.dataset.admp !== k; });
  if (k === 'org') actDraw(md);  // 2.143.0 D (#2156)
  if (k === 'server' && typeof rt9_adminDraw === 'function') rt9_adminDraw(md);  // 2.59.0 B (#1375)
  if (k === 'agents') return Promise.all([ad_agPolicyDraw(md), audDraw(md)]);  // 2.46.6 (#1710): loaded when shown
}
// 2.46.6 (#1710): Administration > Agents: the rules for every agent, the admins' alert on usage limits, the API log
function ad_agentsHtml(hint) {
  if (!S.api?.enabled) return '';
  return `${agAdminPaneHtml(hint)}${notifMatrixHtml(S.settings, hint, true)}<h4 id="s-adlog-h">${tr('Log')}</h4>${audHtml()}`;
}
// Organisation: whether members may connect their own agents (#896, the policy user_agents of #420, off by default)
function orgAgentsHtml(hint) {
  if (!S.api?.enabled) return '';
  return `<h4 id="s-orgag-h">${tr('Agents')}</h4>
    <div class="featgrid"><label class="wide"><input type="checkbox" id="s-orgagents" ${S.about?.user_agents ? 'checked' : ''}><span>${tr('Members may connect agents')}<small class="muted">${tr('People can then connect their own AI agent (their own provider, key and computer) and share projects with it. They are responsible for what that provider receives; everyone in a project is told when an agent joins it and where it runs. Off by default.')}</small></span></label></div>`;
}
// Server: storage per person (#910), the support address, the daily e-mail limit (#899) and the notice above the app (#907)
function hostHtml(hint) {
  const a = S.about || {}, ann = a.announce_all || {};
  const gb = mb => mb ? (mb >= 1024 ? fmtNum(mb / 1024, 1) + ' GB' : mb + ' MB') : tr('unlimited');
  const toLoc = x => { if (!x) return ''; const d = new Date(x); return isNaN(d) ? '' : new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
  return `<h4 id="s-ann-h">${tr('Notice to everyone')}</h4>
    ${hint(tr('Shown above the app for everyone, e.g. before maintenance. People can hide it; a changed notice shows again.'))}
    <div class="row"><textarea id="s-ann-text" rows="2" maxlength="500" aria-labelledby="s-ann-h" placeholder="${esc(tr('e.g. Maintenance tonight from 22:00, Kalmido is unavailable for about 10 minutes.'))}">${esc(ann.text || '')}</textarea></div>
    <div class="row"><label for="s-ann-level">${tr('Kind')}</label><select id="s-ann-level"><option value="info">${tr('Notice')}</option><option value="maintenance" ${ann.level === 'maintenance' ? 'selected' : ''}>${tr('Maintenance')}</option></select></div>
    <div class="row"><label for="s-ann-from">${tr('From')}</label><input type="datetime-local" id="s-ann-from" value="${esc(toLoc(ann.starts_at))}"><label for="s-ann-to" class="qtol">${tr('until|time')}</label><input type="datetime-local" id="s-ann-to" value="${esc(toLoc(ann.ends_at))}"></div>
    <div class="row"><label>${tr('Push')}</label><label class="chkl"><input type="checkbox" id="s-ann-push"> ${tr('Also send it as a push to everyone (once)')}</label></div>
    <div class="row"><span class="spacer"></span>${ann.text ? `<button class="btn sm" data-m="ann-clear">${ic('x', 's')} ${tr('Remove')}</button>` : ''}<button class="btn sm pri" data-m="ann-save">${ic('check', 's')} ${tr('Publish')}</button></div>
    <h4 id="s-quota-h">${tr('Storage per person')}</h4>
    ${hint(tr('From 80 % a warning, at 100 % no new uploads (nothing is deleted). Empty = the server default ({0}).', gb(a.storage_quota_env)))}
    <div class="row"><label for="s-quota">${tr('Storage per person')}</label><input id="s-quota" inputmode="numeric" class="numin" value="${a.storage_quota_mb == null ? '' : esc(String(a.storage_quota_mb))}" placeholder="${esc(String(a.storage_quota_env || 0))}"><span class="muted">${tr('MB (0 = unlimited)')}</span></div>
    <div class="row"><label for="s-qpool">${tr('Shared by')}</label><select id="s-qpool"><option value="user">${tr('each person on their own')}</option><option value="org" ${a.storage_pool === 'org' ? 'selected' : ''}>${tr('the organisation (amount × members)')}</option></select></div>
    <div class="row"><label for="s-support">${tr('Support address')}</label><input id="s-support" type="email" value="${esc(a.support_email || '')}" placeholder="${esc(a.support_email_env || 'support@example.com')}" autocomplete="off"></div>
    <h4 id="s-legal-h">${tr('Privacy and imprint')}</h4>
    ${hint(tr('Links on the login page and under Help, e.g. to your privacy statement. Empty = no link (or the value from the server configuration).'))}
    <div class="row"><label for="s-privacy">${tr('Privacy statement')}</label><input id="s-privacy" type="url" value="${esc(a.privacy_url || '')}" placeholder="${esc(a.privacy_url_env || 'https://example.com/privacy')}" autocomplete="off"></div>
    <div class="row"><label for="s-imprint">${tr('Imprint')}</label><input id="s-imprint" type="url" value="${esc(a.imprint_url || '')}" placeholder="${esc(a.imprint_url_env || 'https://example.com/imprint')}" autocomplete="off"></div>
    <h4 id="s-maillim-h">${tr('E-mails per day')}</h4>
    ${hint(tr('Per person and day (at most 5 a day to one address). Over the limit the link is shown to copy.'))}
    <div class="row"><label for="s-maillim">${tr('Per account and day')}</label><input id="s-maillim" inputmode="numeric" class="numin" value="${esc(String(a.mail_day_limit || 30))}"></div>
    ${a.hosted ? `<div class="shint keep">${ic('alert', 's')} ${tr('Hosted server: integrations only reach public HTTPS addresses.')}</div>` : ''}
    <h4 id="s-ip-h">${tr('Your IP')}</h4><div id="s-ipbox" aria-labelledby="s-ip-h"><div class="muted mhint">${tr('Loading…')}</div></div>${(setTimeout(ipFill, 0), '')}`;
}
// 2.33.0 (#834): the address the server sees for me (self-test behind a reverse proxy) and the warning when many accounts
// sign in from one private address (the proxy does not pass the client's address on)
async function ipFill() {
  const box = $('#s-ipbox'); if (!box || box._busy) return;
  box._busy = true;
  let j; try { j = await api('GET', '/api/admin/client-ip'); } catch { box.innerHTML = ''; return; } finally { box._busy = false; }
  if (!box.isConnected) return;
  const warn = j.warning ? `<div class="shint keep ipwarn" role="alert">${ic('alert', 's')} <span><b>${esc(tr('Client addresses do not arrive – check the proxy'))}</b><br>${esc(tr('{0} of {1} accounts signed in from the one private address {2} in the last 7 days. The sign-in lockout then hits everyone at once. Run the reverse proxy with network_mode: host (or "userland-proxy": false) and set KALMIDO_TRUSTED_PROXIES, see the self-hosting guide.', j.warning.accounts, j.warning.total, j.warning.ip))}</span></div>` : '';
  box.innerHTML = `<div class="row"><label>${tr('As the server sees it')}</label><code class="ipv">${esc(j.ip || '?')}</code>${j.private ? ` <span class="muted">${esc(tr('private address'))}</span>` : ''}</div>
    ${j.via_proxy ? `<div class="row"><label>${tr('Via proxy')}</label><code class="ipv">${esc(j.peer)}</code> <span class="muted">${esc(j.peer_trusted ? tr('trusted (KALMIDO_TRUSTED_PROXIES)') : tr('not trusted'))}</span></div>` : ''}
    <div class="shint">${esc(tr('Compare it with your device’s address on the internet. If it shows a private address like 172.x.0.1 while you are outside, the reverse proxy hides the client addresses.'))}</div>${warn}`;
}
async function hostSave(md, patch, label) {
  try { const j = await api('PATCH', '/api/admin/settings', patch); S.about = {...S.about, ...j}; toast(label); return true; }
  catch { return false; }
}
function hostWire(md) {
  md.addEventListener('change', async e => {
    const id = e.target.id;
    if (id === 's-orgagents') {
      try { const j = await api('PUT', '/api/admin/agent-policy', {user_agents: e.target.checked}); S.about = {...S.about, user_agents: j.user_agents}; toast(e.target.checked ? tr('Members may connect agents') : tr('Only admins connect agents')); } catch { e.target.checked = !e.target.checked; }
      return;
    }
    if (id === 's-quota') { const v = e.target.value.trim(); if (v !== '' && !/^\d+$/.test(v)) { toast(tr('Invalid value: {0}', tr('Storage per person'))); return; } hostSave(md, {storage_quota_mb: v === '' ? null : +v}, tr('Saved')); return; }
    if (id === 's-qpool') { hostSave(md, {storage_pool: e.target.value}, tr('Saved')); return; }
    if (id === 's-support') { hostSave(md, {support_email: e.target.value.trim()}, tr('Saved')); return; }
    if (id === 's-privacy' || id === 's-imprint') { hostSave(md, {[id === 's-privacy' ? 'privacy_url' : 'imprint_url']: e.target.value.trim()}, tr('Saved')); return; }  // 2.306.0 B (#2887)
    if (id === 's-maillim') { const v = +e.target.value; if (!(v >= 1 && v <= 1000)) { toast(tr('Invalid value: {0}', tr('E-mails per day'))); e.target.value = S.about?.mail_day_limit || 30; return; } hostSave(md, {mail_day_limit: v}, tr('Saved')); }
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m="ann-save"], [data-m="ann-clear"]'); if (!b) return;
    const iso = id => { const v = $(id, md)?.value; return v ? new Date(v).toISOString() : ''; };
    const body = b.dataset.m === 'ann-clear' ? {text: ''} : {text: $('#s-ann-text', md).value.trim(), level: $('#s-ann-level', md).value, starts_at: iso('#s-ann-from'), ends_at: iso('#s-ann-to'), push: $('#s-ann-push', md).checked};
    if (b.dataset.m === 'ann-save' && !body.text) { toast(tr('Write the notice first')); return; }
    try { await api('PUT', '/api/admin/announcement', body); } catch { return; }
    try { const j = await api('GET', '/api/about'); S.about = {...S.about, ...j}; } catch { /* keep */ }
    await load(); render(); toast(body.text ? tr('Notice published') : tr('Notice removed'));
    const p = $('[data-admp="server"]', md); if (p) { p.innerHTML = instanceHtml((id, on, label) => `<label class="chkl"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${label}</label>`, t => `<div class="shint">${t}</div>`) + hostHtml(t => `<div class="shint">${t}</div>`) + bkHtml() + stoHtml(); bkDraw(md); }
  });
}
function settingsModal(focus) {
  if (kd_pinNeed()) return kd_pinAsk(() => settingsModal(focus));  // 2.49.0 (#1551): a child with the parents' PIN
  const s = S.settings;
  const topicUrl = httpUrl(`${S.ntfyUrl}/${s.ntfy_topic}`);  // 2.306.0 D4 (#2875): only http(s) in the link
  const dev = `<span class="devtag">${tr('This device')}</span>`, hint = t => `<div class="shint">${t}</div>`;
  const chk = (id, on, label) => `<label class="chkl"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${label}</label>`;
  const prio = `<div class="row"><label for="s-pushprio">${tr('How urgent')}</label><select id="s-pushprio">${[['3', N_('Normal')], ['4', N_('Loud')], ['5', N_('Urgent')]].map(([v, n]) => `<option value="${v}" ${(s.push_priority || '4') === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
      ${hint(tr('Loud rings and vibrates longer; Urgent may also break through “Do not disturb” on some phones.'))}`;
  const pane = {
    account: S.me ? accountHtml() : '',
    org: S.me && lmOrgPaneOn() ? wsPaneHtml(t => `<div class="shint">${t}</div>`) : '',  // 2.39.1 (#1188): Settings > Organisation
    look: `<div id="s-lookin">${lookHtml()}</div>
      <h4 id="s-lemo-h">${tr('New projects')}</h4><div class="row">${chk('s-lemo', s.list_emoji !== '0', tr('Suggest icons for new projects'))}</div>
      <div class="row">${chk('s-sdn', s.show_done_new !== '0', tr('Hide completed tasks in new projects'))}</div>
      ${hint(tr('A new project hides its completed tasks; its “…” menu shows them again. A folder default goes first.'))}
      ${hint(tr('A new project gets an icon matching its name; existing projects keep theirs.'))}
      <h4 id="s-sdd-h">${tr('Completed tasks')}</h4><div class="row"><label for="s-sdd">${tr('In projects and views')}</label><select id="s-sdd"><option value="1">${tr('Show completed')}</option><option value="0" ${s.show_done_default === '0' ? 'selected' : ''}>${tr('Hide completed')}</option></select></div>
      ${hint(tr('The default for every project and view; a folder or a single project can choose otherwise.'))}
      <h4>${tr('Tips')}</h4><div class="row"><label>${tr('Hints')}</label><button class="btn sm" data-m="hints-reset">${ic('undo', 's')} ${tr('Show tips again')}</button></div>
      ${hint(tr('Brings back the one-time hints on this device (touch screens show helper texts once).'))}
      <h4 id="s-tabbar-h">${tr('Tab bar')}${dev}</h4>
      ${hint(tr('A phone fits {0} tabs, the rest goes under “More”.', TAB_MAX))}
      <div class="navlist" id="s-tabbar"></div>
      <div class="row" style="margin-top:.5rem"><button type="button" class="btn sm tabaddb" id="s-tabadd" data-m="tab-add" style="flex:1" aria-haspopup="dialog">${tr('+ Add tab …')}</button><button class="btn sm" data-m="tab-reset">${tr('Default')}</button></div>
      <h4 id="s-prbg-h">${tr('Task rows')}</h4>
      <div class="row"><label for="s-prbg">${tr('Priority as background')}</label><select id="s-prbg">${[['', N_('Off')], ['soft', N_('Subtle')], ['strong', N_('Strong')]].map(([v, n]) => `<option value="${v}" ${(s.prio_bg || '') === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
      ${hint(tr('A light background in the priority colour; the bar at the edge stays.'))}
      <div class="row">${chk('s-pcol', s.person_colors !== '0', tr('Show colours for people'))}</div>
      ${hint(tr('The circle behind the initials, a thin ring around a photo. Off: only agents are coloured.'))}
      ${rsy_setHtml() /* 2.56.1 (#1799): symbols in the row */}
      <div class="row">${chk('s-lpdot', s.list_color_dot === '1', tr('Project colours only as a dot'))}</div>
      ${hint(tr('An open project takes its colour for header, ticks and buttons, tasks show it as a thin edge. On: only the dot in the sidebar.'))}
      <h4 id="s-side-h">${tr('Sidebar')}</h4>
      ${hint(tr('The eye hides a group, the boxes single entries.'))}
      <div class="navlist sidecfg" id="s-sidebar"></div>
      <div class="row" style="margin-top:.5rem"><span class="spacer"></span><button class="btn sm" data-m="side-reset">${tr('Default')}</button></div>
      <div class="row"><label for="s-sideic">${tr('Project icons')}</label><select id="s-sideic">${[['line', N_('Lines')], ['emoji', N_('Emoji')], ['dot', N_('Dot')]].map(([v, n]) => `<option value="${v}" ${(s.side_icons || 'line') === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
      <div class="row">${chk('s-sideprog', s.side_progress !== '0', tr('Progress in the sidebar'))}</div>
      ${hint(tr('Applies to the thin line and the progress rings.')) /* 2.118.0 (#2297) */}
      ${hint(tr('Lines: a calm grey icon instead of the emoji, its dot in the project colour. Dot: only the project colour.'))}
      ${rsy_sideSetHtml(chk) /* 2.56.1 (#1799) */}${lc_favSetHtml(chk, hint)}${sv_setHtml() /* 2.156.0 D (#2186) */}`,
    general: `<h4 id="s-lang-h">${tr('Language')}</h4>
      <div class="row"><div class="seg" id="s-lang" role="group" aria-labelledby="s-lang-h">${(S.languages || []).map(L => `<button data-lang-set="${esc(L.code)}" class="${(s.lang || 'en') === L.code ? 'on' : ''}" lang="${esc(L.code)}">${langName(L)}</button>`).join('')}</div></div>
      ${hint(tr('Quick add understands English, German and the language chosen here.'))}
      <h4 id="s-today-h">${tr('Today')}</h4>
      <div class="row">${chk('s-tinbox', s.today_inbox === '1', tr('Show the basket in Today'))}</div>
      ${hint(tr('Undated basket tasks as their own section in Today, with buttons to sort them.'))}
      ${depsOn() ? `<div class="row">${chk('s-hideblk', s.hide_blocked_today === '1', tr('Hide tasks that are still blocked by another task'))}</div>` : ''}
      <h4 id="s-dates-h">${tr('Changing and completing tasks')}</h4>
      <div class="row">${chk('s-dateok', s.date_confirm === '1', tr('Confirm changes of the date with OK'))}</div>
      ${hint(tr('Off: saved as soon as you pick it, “Undo” takes it back. On: changes wait for OK.'))}
      <div class="row">${chk('s-celebrate', s.celebrate !== '0', tr('Celebrate completions'))}</div>
      ${hint(tr('When Today is cleared or a project is complete, the Kalmido figure hops by with a one-liner. With reduced motion (system setting) it just says hello.'))}
      <div class="row">${chk('s-progsub', s.progress_subtasks === '1', tr('Count subtasks in the progress of a project'))}</div>
      <div class="row">${chk('s-mdpen', td_mdPenOnly(), tr('Edit the description only with the pen'))}</div>
      ${hint(tr('A tap on the description does not open the editor (handy while scrolling), the pen does. On by default on touch screens.'))}
      <h4 id="s-plan-h">${tr('Day planning')}</h4>
      <div class="row"><label for="s-wfrom">${tr('Working hours')}</label>${timeIn('s-wfrom', s.work_start || '09:00', {label: tr('Working hours from'), clear: false})}<label for="s-wto" class="qtol">${tr('until|time')}</label>${timeIn('s-wto', s.work_end || '17:00', {label: tr('Working hours until'), clear: false})}</div>
      <div class="row"><label for="s-review">${tr('Daily review at')}</label>${timeIn('s-review', s.review_time || '', {label: tr('Daily review at'), empty: tr('off')})}</div>
      ${hint(tr('“Plan my day” fills the free time within these hours with open tasks. The daily review comes after the end of your working hours.'))}
      ${typeof wt_setHtml === 'function' ? wt_setHtml(s, hint) : ''}`,
    modules: modulesHtml(hint),
    notify: `${S.webpush?.enabled ? `<div class="pushnow" id="s-pushnow" role="status" aria-live="polite"></div>` : ''}${S.webpush?.enabled ? `<h4>${tr('Delivery')}</h4>
      <div class="row"><label for="s-pushch">${tr('Channel|push')}</label><select id="s-pushch">${[['webpush', N_('Web Push')], ['ntfy', 'ntfy'], ['both', N_('Both')]].map(([v, n]) => `<option value="${v}" ${(s.push_channel || 'webpush') === v ? 'selected' : ''}>${v === 'ntfy' ? n : tr(n)}</option>`).join('')}</select><button class="btn sm" data-m="ptest">${ic('bell', 's')} ${tr('Send test')}</button></div>
      ${prio}
      <div class="shint wpstate" id="s-wpstate"></div>
      ${hint(tr('No extra app needed. Turn it on below on every device that should ring.'))}
      <h4>${tr('This device')}</h4>
      <div id="s-wp"><div class="muted">${tr('Loading…')}</div></div>` : ''}
      <div id="s-ntfy"><h4>${S.webpush?.enabled ? 'ntfy' : tr('Notifications (ntfy)')}</h4>
      <div class="row"><label>${tr('Topic')}</label><code class="topic">${esc(s.ntfy_topic)}</code><button class="btn sm" data-m="test">${ic('bell', 's')} ${tr('Send test')}</button></div>
      ${S.webpush?.enabled ? '' : prio}
      ${hint(`${tr('Subscribe in the ntfy app: server {0}, topic as above', esc(S.ntfyUrl))}${/ntfy\.sh/.test(S.ntfyUrl) || !S.me?.ntfy_inbox ? '' : tr(', logged in with the ntfy login your admin gave you')}. <a href="${esc(topicUrl)}" target="_blank" rel="noopener">${tr('Web view')}</a>`)}</div>
      <div id="s-ntfyin"></div>
      <div id="s-chn"></div>${''/* 2.142.0 A (#2145, #2146): channels + e-mail for single events (integrations.js chn_meDraw) */}
      ${notifMatrixHtml(s, hint)}${bl9SetHtml(s, hint)}${typeof tbl_setHtml === 'function' ? tbl_setHtml(chk, hint) : ''}
      ${typeof trd_setHtml === 'function' ? trd_setHtml(s, chk, hint) : ''}
      <h4>${tr('Reminders')}</h4>
      <div class="row"><label for="s-allday">${tr('All-day reminder at')}</label>${timeIn('s-allday', s.allday_time, {label: tr('All-day reminder at'), clear: false})}</div>
      <div class="row"><label for="s-defrem">${tr('Default reminder')}</label><select id="s-defrem"><option value="">${tr('none')}</option>${REM_OPTS.map(([v, n]) => `<option value="${v}" ${s.default_reminder === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}${s.default_reminder && !REM_OPTS.some(o => o[0] === s.default_reminder) ? `<option value="${esc(s.default_reminder)}" selected>${esc(s.default_reminder.split(',').map(fmtRem).join(', '))}</option>` : ''}</select></div>
      <div class="row"><label for="s-digest">${tr('Daily digest at')}</label>${timeIn('s-digest', s.digest_time, {label: tr('Daily digest at'), empty: tr('off')})}</div>
      <div id="s-digmail-w"></div>
      <div class="row"><label for="s-brief">${tr('Morning briefing at')}</label>${timeIn('s-brief', s.brief_time || '', {label: tr('Morning briefing at'), empty: tr('off')})}</div>
      ${hint(tr('One push with the numbers of your briefing (the first block of Today).'))}
      <h4 id="s-quiet-h">${tr('Repeated reminders')}</h4>
      <div class="row"><label for="s-qfrom">${tr('Quiet from')}</label>${timeIn('s-qfrom', s.quiet_from ?? '22:00', {label: tr('Quiet from'), empty: tr('none')})}<label for="s-qto" class="qtol">${tr('until|time')}</label>${timeIn('s-qto', s.quiet_to ?? '07:00', {label: tr('Quiet until'), empty: tr('none')})}</div>
      ${hint(tr('A task or a project can repeat its reminder until done (date dialog or project dialog). Nothing repeats during the quiet hours.'))}`,
    integr: integrCardsHtml() + calsHtml(chk, hint) + `<h4 id="s-ical-h">${tr('Calendar subscription')}</h4>
      ${hint(tr('Read-only. Calendar apps fetch changes every few hours.'))}
      <div id="s-ical"><div class="muted mhint">${tr('Loading…')}</div></div>
      <div class="row"><label for="s-icalscope">${tr('Tasks')}</label><select id="s-icalscope"><option value="all">${tr('All visible tasks (incl. shared projects)')}</option><option value="mine" ${s.ical_scope === 'mine' ? 'selected' : ''}>${tr('Only mine and assigned to me')}</option></select></div>
      <div class="row"><label>${tr('Reminders')}</label>${chk('s-icalalarm', s.ical_alarms !== '0', tr('as calendar alarms'))}</div>
      <details class="shelp sdet"><summary>${tr('How to subscribe')}</summary><ul class="slist">
        <li>${tr('Your open tasks with a date, for Google Calendar, Apple Calendar, Outlook or Thunderbird; some apps refresh every 15 minutes. Timed tasks appear with their duration, all-day tasks as all-day events, recurring tasks with all future dates.')}</li>
        <li>${tr('<b>Android / Google Calendar:</b> on a computer open calendar.google.com > Other calendars > + > From URL, paste the link. It then shows up in the Calendar app on the phone (tap the calendar under Settings to sync it).')}</li>
        <li>${tr('<b>iPhone / iPad:</b> Settings > Apps > Calendar > Calendar Accounts > Add Account > Other > Add Subscribed Calendar, paste the link. <b>Mac:</b> Calendar > File > New Calendar Subscription.')}</li>
        <li>${tr('<b>Thunderbird:</b> Calendar > New Calendar > On the Network, paste the link.')}</li>
        <li>${tr('<b>Outlook:</b> Add calendar > Subscribe from web.')}</li>
        <li>${tr('<b>Only reachable at home or over a VPN?</b> Google Calendar, iCloud and Outlook.com fetch the feed from their own servers and then cannot reach it. Use an app that fetches on the device instead: on Android ICSx⁵ (the calendar then shows up in every calendar app), on a Mac the location “On My Mac” instead of iCloud, or Thunderbird.')}</li></ul></details>
      ${hintK(tr('Anyone who knows the link sees these tasks. If it got out, create a new link: the old one stops working at once.'))}
      ${caldavHtml(hint)}
      ${feat('docs') && typeof dsc_integrHtml === 'function' ? dsc_integrHtml() : ''}${''/* 2.353.0 B (#2773): docscan.js, drawn by dsc_integrDraw */}
      ${feat('docs') && typeof pl_setHtml === 'function' ? pl_setHtml() : ''}
      <h4 id="s-mail-h">${tr('Tasks by e-mail')}</h4><div id="s-mail"></div>
      ${shareHtml(hint)}
      <ul class="slist">
        ${S.ntfyInbox?.enabled && S.me?.ntfy_inbox ? `<li>${tr('Single files also via the ntfy app:')} ${tr('In the ntfy app, add server {0} once', `<code class="topic">${esc(S.ntfyInbox.server)}</code>`)}${tr(' and log in with the ntfy login your admin gave you.')} ${tr('Then: share an image or text > ntfy > server as above, topic {0}. A few seconds later it is a task in the basket, files as attachments.', `<code class="topic">${esc(S.ntfyInbox.topic)}</code>`)}</li>` : ''}</ul>
      ${acz_linkHtml(S.webhooks?.enabled)}`,  // 2.166.0 (#2633): the webhooks moved to Access
    access: acz_html(),  // 2.166.0 (#2633): API tokens, webhooks and agent tokens in one place
    data: `<h4 id="s-imp-h">${tr('Import')}</h4>
      ${hint(tr('You see a preview first; an import can be undone for 24 hours. Nothing inside the file is fetched from the internet.'))}
      <div class="row"><label for="s-imp-src">${tr('From')}</label><select id="s-imp-src">${IMP_SRC.map(([k, n]) => `<option value="${k}">${esc(tr(n))}</option>`).join('')}</select></div>
      <div class="shelp impHelp" id="s-imp-help">${impHelp('todoist')}</div>
      <div class="row"><label for="s-import">${tr('File')}</label>${fileBtn('s-import', IMP_ACCEPT.todoist)}</div>
      <div id="s-imp-out"></div>
      <div class="members" id="s-imp-hist"></div>
      <h4>${tr('Export')}</h4>
      <div class="row"><label>${tr('Export')}</label><a class="btn sm" href="/api/export.json" download>${ic('download', 's')} ${tr('Download JSON')}</a><a class="btn sm" href="/api/export/todoist.zip" download>${ic('download', 's')} ${tr('Todoist CSV')}</a><a class="btn sm" href="/api/export/markdown.zip" download>${ic('download', 's')} ${tr('Markdown')}</a></div>
      ${hint(tr('One file per project in a ZIP: Todoist CSV for the import of Todoist, Markdown as checklists for any notes app. Projects locked with a password stay out.'))}
      <h4 id="s-pmeta-h">${tr('Photos')}</h4><div class="row">${chk('s-pmeta', s.photo_meta_strip !== '0', tr('Remove location data from photos'))}</div>
      ${hint(tr('Also removes camera details and capture time. In an organisation its admins decide.'))}
      <h4 id="s-vext-h">${tr('Videos')}</h4><div class="row">${chk('s-vext', s.video_ext_ok === '1', tr('Load YouTube and Vimeo videos without asking'))}</div>
      ${hint(tr('Off: a video sign-off first shows a note and loads the player only after your click. Loading sends data such as your IP address to the provider.'))}
      ${typeof umzHtml === 'function' ? umzHtml(hint) : ''}
      <h4 id="s-tpl-h">${tr('Templates')}</h4>
      ${hint(tr('Private to you. Save from a task’s menu (…) or the project dialog; use via the template button or Projects > +.'))}
      <div class="members" id="s-tpls"><div class="muted mhint">${tr('Loading…')}</div></div>
      ${sampleHtml(hint)}`,
    ai: aiPaneOn() ? aiHtml(hint, {agents: 'agents', agentdots: 'agents', usage: 'usage'}[focus]) : '',  // 2.7.0 (#405 S2)
    assistant: asst_paneHtml(hint),  // 2.75.0 (#1411): only with a configured assistant
    users: S.me?.is_admin ? admSubsHtml({  // 2.24.0 (#826): Administration in sub-tabs like Agents
      users: usersHtml() + grpHtml() + orphHtml(),
      signin: `<div id="s-signin">${signinHtml(hint)}</div>`,
      org: orgsHtml() + actHtml() + orgAgentsHtml(hint) + ocAdminHtml(hint),  // 2.42.0 (#828): + encryption of organisation data
      agents: ad_agentsHtml(hint),  // 2.46.6 (#1710)
      server: instanceHtml(chk, hint) + ad_updHtml(hint) + hostHtml(hint) + bkHtml() + stoHtml() + (typeof rt9_adminHtml === 'function' ? rt9_adminHtml(hint) : '') + asst_admHtml(),  // 2.75.0 (#1411): + asst_admHtml; 2.59.0 B (#1375): + related tasks  // 2.46.6 (#1710): + the update check result (was Help)
      log: aaHtml()}, ad_admFocus(focus)) : '',  // 1.9.0: users first
    help: `<h4>${tr('Getting started')}</h4>
      <div class="row"><button class="btn sm" data-m="tour">${ic('arrow', 's')} ${tr('Restart the welcome tour')}</button>${isMobile() ? '' : `<button class="btn sm" data-m="keys">${ic('help', 's')} ${tr('Keyboard shortcuts')} ${kb('?')}</button>`}<button class="btn sm" data-m="cele-try">${ic('check', 's')} ${tr('Show the celebration')}</button></div>
      ${isMobile() ? '' : `<div class="shelp">${tr('{0}: search and commands for everything (tasks, projects, views, settings). j / k move through the tasks, x completes, s snoozes, g t goes to Today.', kbText('Mod+K'))}</div>`}
      <h4>${tr('Quick add')}</h4>
      <div class="shelp">${tr('today, tomorrow, day after tomorrow, friday, next monday, in 3 days, 12.10., 3pm, at 15:00<br>daily, weekdays, weekly, every monday, every 2 weeks, monthly, yearly<br>!high / !medium / !low (or !!!, !!, !) · #tag · ~project, “in project Work” or “… in Work” at the end<br>German works too: morgen 15 uhr, jeden montag, !hoch<br>Keyboard: n = new task, / = search, Esc = close')}</div>
      <div class="shelp">${tr('@name assigns (people of the project) · 30 min, 2h, for 1.5 hours = duration<br>remind me 15 min before · remind me tomorrow 9am, remind me Tue 9:00 (also without a date)')}</div>  <!-- 2.111.0 C (#2057) -->
      <h4>${tr('Undo')}</h4>
      <div class="shelp">${tr('Every change can be undone: the ← / → buttons at the top (on a phone in the “…” menu), the “Undo” in the message, Ctrl+Z / ⌘Z. Settings too. Offline, the change is simply not sent.')}</div>
      <h4>${tr('Formatting (Markdown)')}</h4>
      <div class="shelp">${tr('<b>Descriptions:</b> <code>**bold**</code>, <code>*italic*</code>, <code>~~strikethrough~~</code>, <code>&#96;code&#96;</code>, links as <code>[text](https://…)</code> or a plain https:// address, headings <code>#</code> / <code>##</code> / <code>###</code>, lists <code>- item</code> or <code>1. item</code>, checklists <code>- [ ]</code> / <code>- [x]</code> (tick them right in the formatted text). “Turn the open checklist items into subtasks” below the formatted description makes real subtasks of the unticked items.')}${collab() ? '<br>' + tr('<b>Comments:</b> the same bold, italic, strikethrough, code and links, plus line breaks and @mentions; no headings, lists or checklists.') : ''}</div>
      <h4>${tr('Projects')}</h4>
      <div class="shelp">${tr('Every task list is a project; the switch Progress and status (project menu … > Edit) adds the project modules you switched on. For shopping or packing lists: project menu … (or Sort) > Show completed at the bottom: what you tick off stays visible at the bottom and comes back with one tap.')}</div>
      <h4>${tr('Favourites')}</h4>
      <div class="shelp">${tr(VW_FAV_HELP)}</div>
      <h4>${tr('Locked notes')}</h4>
      <div class="shelp">${tr('In a task of your own project that is not shared: “Lock note” under the description encrypts the note in your browser with your encryption passphrase (set up once, with a recovery code to print). The server keeps only the encrypted text; title, dates and project stay readable. Search, agents, exports, calendar apps, e-mails and public links leave a locked note out. Unlock once per session to read or change it; “Remove lock” makes it a normal note again. Passphrase and recovery code lost = the note is lost, nobody can restore it, not even the operator. Copies made before locking (older backups of the server) still hold the old text.')}</div>${''/* 2.48.0 (#1642) */}
      <h4>${tr('Templates')}</h4>
      <div class="shelp">${tr('Task menu (…) or project dialog > Save as template. The template button in the add bar creates the task in the current project, Projects > + > New project from template a whole project. Manage them under Settings > Data.')}</div>
      ${timeOn() ? `<h4>${tr('Time tracking')}</h4><div class="shelp">${tr('Start a timer from a task (detail panel, task menu …) or add time by hand; the running timer shows in the top bar on every device. Sidebar > Time tracking: hours per project and task for a week, month or any range, CSV export and a printable timesheet. In shared projects everyone sees the time of all members, but only changes their own entries. Finished focus sessions on a task count as time unless a timer ran at the same time.')}</div>` : ''}
      ${depsOn() || fieldsOn() || progressOn() ? `<h4>${tr('Projects')}</h4><div class="shelp">${tr('<b>Dependencies:</b> in a task, “Waiting on…” > “Another task” picks the tasks that have to be done first; the task shows “blocked” until they are, and whoever it is assigned to gets a message once the last one is done. “Waiting on…” > “Someone outside” marks a task that waits on a person (a client, an office, a delivery) with a follow-up day. <b>Custom fields</b> (project dialog, owner and project admins): text, number, selection, date, checkbox, person or link per task; show up to two in the task rows, sort and filter by them. <b>Status and progress</b> (Project progress module): the project header shows the progress; with collaboration, owner and editors set a status with a short note, and the project status (“Where is it stuck?”) lists overdue, blocked and unassigned tasks of all projects.')}</div>` : ''}
      ${feat('stats') ? `<h4>${tr('Statistics')}</h4><div class="shelp">${tr('Sidebar > Statistics (or pin it as a tab): completions per week / day and per project, on-time rate, overdue trend, focus time and habit streaks of the last 12 weeks.')}</div>` : ''}
      <h4>${tr('Gestures (phone)')}</h4>
      <div class="shelp">${tr('Swipe right: complete · swipe left: snooze / delete · long-press: selects the task (a bar with Move, Date, Complete and More; tap more tasks to add them, drag them by the grip) · long-press and drag: reorder, move to another column, quadrant or onto a day; drag to the left edge and hold briefly to open the projects (dropping a subtask there = standalone task in that project).')}</div>`,
  };
  pane.help += asst_helpHtml();  // 2.75.0 (#1411)
  pane.help += aboutHtml(chk, hint);
  const secs = SET_SECS.filter(([k]) => pane[k]);
  let cur = {tabbar: 'look', sidebar: 'look', layout: 'modules', collab: 'modules', focus: 'modules', time: 'modules', templates: 'data', sample: 'data', newskinds: 'notify', agents: 'ai', agentdots: 'ai', usage: 'ai', activity: S.me?.is_admin ? 'users' : 'ai', agentpolicy: 'users', server: 'users', agentsafe: 'ai', share: 'integr', ical: 'integr', calendars: 'integr', webhooks: 'access', caldav: 'integr', paperless: 'integr', scans: 'integr', tokens: 'access', apppw: 'account', about: 'help', groups: 'users', dayplan: 'general'}[focus] || focus;
  if (!secs.some(([k]) => k === cur)) cur = LS.get('settingsSec', 'general');
  if (!secs.some(([k]) => k === cur)) cur = 'general';
  const md = modal(`<div class="shdr"><button type="button" class="iconbtn sback" data-m="s-index" title="${esc(tr('All settings'))}" aria-label="${esc(tr('All settings'))}">${ic('back', 's')}</button><h3>${tr('Settings')}</h3><span class="ssaved" role="status" aria-live="polite"></span><span class="spacer"></span><span class="ssearch">${ic('search', 's')}<input type="search" id="s-search" name="kalmido-settings-search" data-1p-ignore data-lpignore="true" data-bwignore readonly placeholder="${esc(tr('Search settings'))}" aria-label="${esc(tr('Search settings'))}" autocomplete="off" aria-controls="s-sres"></span><div class="ssres hidden" id="s-sres" role="listbox" aria-label="${esc(tr('Search settings'))}"></div><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="sbody"><nav class="snav" role="tablist" aria-label="${tr('Settings')}">${secs.map(([k, i, n]) => `<button role="tab" id="st-${k}" aria-controls="sp-${k}" aria-selected="${k === cur}" data-sec="${k}" class="${k === cur ? 'on' : ''}">${ic(i, 's')}<span>${tr(n)}</span>${SET_DESC[k] ? `<small class="sndesc">${esc(tr(SET_DESC[k]))}</small>` : ''}</button>`).join('')}</nav>
      <div class="spanes">${secs.map(([k]) => `<section class="spane ${k === cur ? '' : 'hidden'}" role="tabpanel" id="sp-${k}" aria-labelledby="st-${k}" data-pane="${k}">${pane[k]}</section>`).join('')}</div></div>`);
  md.classList.add('smodal');
  mg_setSync(md);  // 2.171.0 (#2676): an area with only some parts on shows its switch half (indeterminate is no HTML attribute)
  // 2.25.0 (UX-17): a phone opens on an overview of the areas (name + what is in it); a tap opens one, ‹ goes back
  // 2.32.0 (#1060): a phone shows no area tabs inside an area, so the header names the area (the overview says "Settings")
  const head = () => { const h = $('.shdr h3', md); if (!h) return; const sec = isMobile() && !md.classList.contains('sidx') ? secs.find(x => x[0] === cur) : null; h.textContent = sec ? tr(sec[2]) : tr('Settings'); };
  const idx = on => { md.classList.toggle('sidx', on); if (on) $('.snav [data-sec].on', md)?.setAttribute('aria-selected', 'false'); head(); };
  if (isMobile() && !focus) idx(true); else head();
  md._idx = idx;
  // 2.13.2 (#478 F13): phones: a "More ›" at the right end of the cut tab strip while more tabs are hidden to the right
  { const nav = $('.snav', md); nav.insertAdjacentHTML('afterend', `<button type="button" class="snmore hidden" data-snmore tabindex="-1" aria-hidden="true">${tr('More')} ›</button>`);
    $('[data-snmore]', md).addEventListener('click', () => nav.scrollBy({left: nav.clientWidth * .7, behavior: reducedMotion() ? 'auto' : 'smooth'}));
    nav.addEventListener('scroll', () => snavMore(nav), {passive: true}); setTimeout(() => snavMore(nav), 0); }
  // 2.13.0 (#429): the font size slider applies live while it moves; the views drawn in px follow when it is let go
  // 2.18.0 (#642): the two spacing sliders of "Custom" apply live while dragging (per device)
  md.addEventListener('input', e => { const k = e.target.dataset?.dens; if (!k) return; const v = +e.target.value;
    LS.set(k === 'side' ? 'densSideV' : 'densRowsV', v); applyDensity(); e.target.setAttribute('aria-valuetext', v + ' %'); const o = $(`#s-dens-${k}-v`, md); if (o) o.textContent = v + ' %'; });
  md.addEventListener('input', e => { if (e.target.id !== 's-fsize') return; const v = +e.target.value; if (v === 100) LS.del('fsize'); else LS.set('fsize', v); applyLook(); fsLabel(v); });
  md.addEventListener('change', e => { if (e.target.id === 's-fsize' && S.settings) render(); });
  if (focus === 'tabbar') setTimeout(() => $('#s-tabbar-h', md)?.scrollIntoView({block: 'start'}), 0);
  if (focus === 'sidebar') setTimeout(() => $('#s-side-h', md)?.scrollIntoView({block: 'start'}), 0);  // 2.25.0 (UX-03)
  if (focus === 'newskinds' || focus === 'share') setTimeout(() => $(focus === 'share' ? '#s-share-h' : '#s-news-h', md)?.scrollIntoView({block: 'start'}), 0);
  if (focus === 'agentdots') setTimeout(() => $('#s-agdots-h', md)?.scrollIntoView({block: 'start'}), 0);
  if (focus === 'groups' || focus === 'dayplan') setTimeout(() => $(focus === 'groups' ? '#s-groups-h' : '#s-plan-h', md)?.scrollIntoView({block: 'start'}), 0);  // 2.10.0
  if (focus === 'scans') setTimeout(() => $('#s-scan-h', md)?.scrollIntoView({block: 'start'}), 50);  // 2.353.0 B (#2773)
  if (focus === 'caldav' || focus === 'apppw') setTimeout(() => $(focus === 'caldav' ? '#s-dav-h' : '#s-apw-h', md)?.scrollIntoView({block: 'start'}), 0);
  // 2.7.0 (#405 S8): the module keys land on their row (and open its options), not just on top of Modules
  const modFocus = {layout: 'cal', collab: 'collab', focus: 'pomo', time: 'time'}[focus];
  if (modFocus) setTimeout(() => { const r = $(`[data-pane="modules"] [data-modrow="${modFocus}"]`, md); if (!r) return; const gd = r.closest('details.modgrp'); if (gd) gd.open = true; const gp = r.closest('details.mgparts'); if (gp) gp.open = true; const o = $('details.mopt', r); if (o) o.open = true; r.scrollIntoView?.({block: 'start'}); r.classList.add('flash'); }, 0);
  const show = k => {
    cur = k; LS.set('settingsSec', k); head();
    $$('.snav button', md).forEach(b => { b.classList.toggle('on', b.dataset.sec === k); b.setAttribute('aria-selected', b.dataset.sec === k); });
    $$('.spane', md).forEach(p => p.classList.toggle('hidden', p.dataset.pane !== k));
    $('.spanes', md).scrollTop = 0;
    if (k === 'data') templatesDraw(md);
    if (k === 'integr') { icalDraw(md); calsDraw(md); if (typeof dsc_integrDraw === 'function') dsc_integrDraw(md); }
    if (k === 'access') acz_draw(md);  // 2.166.0 (#2633)
    if (k === 'notify') wpDraw(md);
    if (k === 'users') { aaDraw(md); bkDraw(md); orphDraw(md); grpDraw(md); ocAdminDraw(md); }
    if (k === 'ai') aiSubShow(md);  // 2.5.1 (#393): only the shown sub-tab loads
    if (k === 'users') admSubShow(md);
    if (k === 'assistant' || k === 'users') asst_paneDraw(md);  // 2.75.0 (#1411)
    if (k === 'account') { tfaDraw(md); apwDraw(md); e2eDraw(md); if (typeof msvDraw === 'function') msvDraw(md); if (typeof sesDraw === 'function') sesDraw(md); }  // 2.73.0 A (#661): + Servers; 2.115.0 B (#2062): + sessions
    $(`.snav [data-sec="${k}"]`, md)?.scrollIntoView({block: 'nearest', inline: 'nearest'});
  };
  // ---- autosave
  const pend = new Map();  // id -> timer of a text field that is being typed into
  const saveEl = async el => {
    clearTimeout(pend.get(el.id)); pend.delete(el.id);
    const d = SETS[el.id]; if (!d) return;
    const v = setVal(el, d[2]);
    if (v === undefined) { settingsSync(); return; }  // not a valid value: back to what is saved
    if (d[2] === 'time' && el.id === 's-allday' && !v) return;
    await setApply({[d[0]]: v}, tr(d[1]));
    if (d[0] === 'agent_comments') loadNews().then(render).catch(() => {});  // 2.66.1 (#1943): the bell's number depends on it
    if (d[0] === 'tz' || d[0] === 'time_split_midnight') S.tv.key = '';  // 2.125.0 B (#2120): the time report again
    if (d[0] === 'chat_read_receipts' && typeof teamChanged === 'function') teamChanged();  // 2.139.0 A (#2129): "Read by" comes / goes
  };
  const saveName = async () => {
    const el = $('#a-name', md); if (!el || !S.me) return;
    clearTimeout(pend.get('a-name')); pend.delete('a-name');
    const v = el.value.trim(), from = S.me.display_name;
    if (!v) { el.value = from; return; }
    if (v === from) return;
    try { await api('PATCH', '/api/me', {display_name: v}); } catch { return; }
    S.me.display_name = v; renderSide();
    const step = to => async () => { await api('PATCH', '/api/me', {display_name: to}); S.me.display_name = to; return {skipped: []}; };
    setSaved(histAdd({label: tr('Changed setting: {0}', tr('Display name')), sett: true, post: settingsSync, undo: step(from), redo: step(v)}));
  };
  const flush = () => { for (const id of [...pend.keys()]) { if (id === 'a-name') saveName(); else { const el = $('#' + id, md); if (el) saveEl(el); } } };
  const isText = el => el.matches?.('input:not([type=checkbox]):not([type=hidden]):not([type=file]):not([type=password]), textarea');
  md.addEventListener('input', e => {
    const el = e.target;
    if (!(SETS[el.id] || el.id === 'a-name') || !isText(el)) return;
    clearTimeout(pend.get(el.id));
    pend.set(el.id, setTimeout(() => el.id === 'a-name' ? saveName() : saveEl(el), 900));
  });
  md.addEventListener('change', e => {
    const el = e.target;
    if (el.id === 'a-name') { saveName(); return; }
    if (SETS[el.id]) { saveEl(el); if (el.id === 's-pushch') { ntfyShow(md); wpState(md); } return; }
    if (el.dataset.agvis) {  // 2.6.1 (#402): which agents show a status dot in the header
      const hid = agentHidden(), aid = +el.dataset.agvis;
      el.checked ? hid.delete(aid) : hid.add(aid);
      const sd = on => ({set_delta: {agents_hidden: {[on ? 'add' : 'remove']: [aid]}}});  // 2.269.0 B (#3014): only this agent
      setApply({agents_hidden: [...hid].sort((a, b) => a - b).join(',')}, `${tr('In the header')} · ${agentById(aid)?.name || aid}`, {send: sd(!el.checked), back: sd(el.checked)});
      return;
    }
    if (el.dataset.nm) {  // 2.1.0 (#317) the notification matrix
      const row = NOTIF_ROWS.find(x => x[0] === el.dataset.nm);
      const nm = on => ({notify: {[el.dataset.nm]: {[el.dataset.ch]: on ? 1 : 0}}});  // 2.269.0 B (#3014): the partial matrix (only this switch)
      setApply(notifPatch(S.settings, el.dataset.nm, el.dataset.ch, el.checked), `${tr(row[1])} · ${el.dataset.ch === 'news' ? tr('News') : tr('Push')}`, {send: nm(el.checked), back: nm(!el.checked)})
        .then(() => { S.notify = notifMatrix(S.settings); });
      return;
    }
    if (el.dataset.mgarea) { mg_areaSwitch(md, el); return; }  // 2.44.0 (#1187)
    if (el.dataset.feat) {
      const on = el.checked, k = el.dataset.feat, n = tr(FEATS.find(x => x[0] === k)?.[1] || k);
      const fs = new Set((S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean));
      on ? fs.add(k) : fs.delete(k);
      $$(`[data-feat="${k}"]`, md).forEach(x => { x.checked = on; x.closest('[data-modrow]')?.classList.toggle('off', !on); });  // 2.0.5: agents twice
      const fd = add => ({set_delta: {features: {[add ? 'add' : 'remove']: [k]}}});  // 2.269.0 B (#3014): only this module
      setApply({features: FEATS.map(x => x[0]).filter(x => fs.has(x)).join(',')}, on ? tr('{0} on', n) : tr('{0} off', n), {send: fd(on), back: fd(!on)}).then(() => {
        mg_setSync(md);  // 2.44.0 (#1187): the area's switch follows its parts
        modCountsSync(md);  // 2.171.0 (#2676): the counts and "Switch on all modules" too
        const r = el.closest('[data-modrow]'); if (r && k === 'time' && on && !$('#s-trnd', md)) { const cur = LS.get('settingsSec'); md._noflush = true; md.remove(); settingsModal(cur); }
      });
    }
  });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && (SETS[e.target.id] || e.target.id === 'a-name') && isText(e.target)) { e.preventDefault(); e.target.id === 'a-name' ? saveName() : saveEl(e.target); } });
  md.addEventListener('change', e => { if (['s-collaball', 's-timeall', 's-collaball-a', 's-timeall-a', 's-updcheck', 's-2fareq', 's-pklogin', 's-oidcauto', 's-publinks'].includes(e.target.id)) adminSwitch(md, e.target); });
  md.addEventListener('change', async e => {  // 2.7.0 (#407): hours per day / shift for the whole server, one history step
    if (e.target.id !== 's-dayh') return;
    const from = S.timeDayH || 8, to = +String(e.target.value).replace(',', '.');
    if (!(to >= 1 && to <= 24)) { toast(tr('Hours per day: a number from 1 to 24')); e.target.value = fmtNum(from, 2); return; }
    if (to === from) return;
    const put = async v => { const j = await api('PATCH', '/api/admin/settings', {time_day_h: v}); S.about = {...S.about, ...j}; S.timeDayH = +j.time_day_h || v; const f = $('#s-dayh'); if (f && f !== document.activeElement) f.value = fmtNum(S.timeDayH, 2); render(); return {skipped: []}; };
    try { await put(to); } catch { return; }
    setSaved(histAdd({label: tr('Changed setting: {0}', tr('Hours per day')), sett: true, undo: () => put(from), redo: () => put(to)}));
  });
  md.addEventListener('change', e => { if (e.target.id === 's-cerlist') cer_setList(e.target); });  // 2.102.0 E (#1999)
  onRemove(md, () => { if (!md._noflush) flush(); });
  $('.snav', md).addEventListener('click', e => { const b = e.target.closest('[data-sec]'); if (b) { show(b.dataset.sec); if (md.classList.contains('sidx')) { idx(false); setTimeout(() => $('.spane:not(.hidden) h4, .spane:not(.hidden) button, .spane:not(.hidden) input', md)?.focus?.({preventScroll: true}), 0); } } });
  md.addEventListener('click', e => { if (e.target.closest('[data-m="s-index"]')) { idx(true); $('.snav [data-sec]', md)?.focus(); } });
  // 2.13.0 (#453 P20): search every tab's headings, labels and options; a hit opens its tab and scrolls to it
  // 2.24.0 (UX-16): full text: also buttons, helper lines, the small texts of switches, select options and table heads,
  // plus a few synonyms (words people search for that the labels do not use); a hit inside a sub-tab (Administration,
  // Agents) or a folded section opens it; nothing found hides the panes behind one clear line
  const sres = $('#s-search', md) && $('#s-sres', md);
  const SYN = [[['logout', 'log out', 'sign out', 'abmelden', 'ausloggen'], '[data-acc="logout"]'], [['push', 'benachrichtigung', 'notification', 'glocke', 'bell'], '[data-pane="notify"] h4'],
    [['sidebar', 'seitenleiste'], '#s-side-h'], [['menü', 'menu', 'tab bar', 'tab-leiste'], '#s-tabbar-h'], [['wartet', 'waiting', 'warten', 'extern'], '[data-modrow="deps"]'], [['passwort', 'password', 'kennwort'], '#a-cur'],
    [['speicher', 'storage', 'quota', 'kontingent'], '#s-storage-h'], [['dunkel', 'dark', 'hell', 'light', 'theme'], '#s-lookin h4'], [['sprache', 'language'], '#s-lang-h']];
  const shown = el => !el.closest('[hidden]') || el.closest('[data-admp], [data-aisp]');
  // 2.46.2 (#1651): readonly until focus keeps password managers out; a value nobody typed is cleared
  const sq = $('#s-search', md);
  sq.addEventListener('focus', () => sq.removeAttribute('readonly'));
  sq.addEventListener('pointerdown', () => sq.removeAttribute('readonly'));
  setTimeout(() => { if (sq.value && !sq._typed) sq.value = ''; }, 300);
  sq.addEventListener('input', () => { sq._typed = true; });
  $('#s-search', md).addEventListener('input', e => {
    const q = e.target.value.trim().toLowerCase(), sb = $('.sbody', md);
    if (!q) { sres.classList.add('hidden'); sres.innerHTML = ''; sb.classList.remove('snores'); return; }
    const hits = ss_hits(md, q, shown, SYN);  // 2.250.0 C (#2994): titles / field names first, one explanation per section, synonyms
    hits.push(...ss_areaHits(q));  // 2.353.0 E (#2775): + the settings windows of the areas
    const tab = k => $(`.snav [data-sec="${k}"] span`, md)?.textContent || k;
    const lab = h => ss_cut(h.el?.matches('select') ? (h.el.closest('.row')?.querySelector('label')?.textContent || h.t) : h.t, 80);
    sres.innerHTML = hits.length ? hits.map((h, i) => `<button type="button" role="option" data-hit="${i}">${h.act === 'area' ? `<span class="muted">${esc(h.pre)} ›</span> ` : h.act ? '' : `<span class="muted">${esc(tab(h.k))} ›</span> `}${esc(lab(h))}</button>`).join('') : `<div class="muted mhint">${esc(tr('Nothing found for “{0}”', e.target.value.trim()))}</div>`;
    sb.classList.toggle('snores', !hits.length); sb.dataset.nores = hits.length ? '' : tr('Nothing found for “{0}”', e.target.value.trim());
    sres._hits = hits; sres.classList.remove('hidden');
  });
  sres.addEventListener('click', e => {
    const b = e.target.closest('[data-hit]'); if (!b) return;
    const h = sres._hits[+b.dataset.hit]; sres.classList.add('hidden'); $('#s-search', md).value = ''; $('.sbody', md).classList.remove('snores');
    if (h.act === 'area') { $('[data-m="close"]', md)?.click(); ss_areaOpen(h); return; }  // 2.353.0 E (#2775): the area's own window
    if (h.act === 'absence') { $('[data-m="close"]', md)?.click(); Promise.resolve(AB2.data || ab2_load()).then(() => ab2_sheet(null)); return; }  // 2.250.0 C (#2994): no setting for it: the sheet itself
    show(h.k); idx(false);
    const ap = h.el.closest('[data-admp]'); if (ap) admSubShow(md, ap.dataset.admp, true);
    const ai = h.el.closest('[data-aisp]'); if (ai) aiSubShow(md, ai.dataset.aisp, true);
    for (let det = h.el.closest('details'); det; det = det.parentElement?.closest('details')) if (!(det === h.el.closest('details') && h.el.matches('summary'))) det.open = true;  // 2.25.0: also the folded module group around it
    const r = h.el.closest('.row, .modrow, details, h4, label') || h.el;
    setTimeout(() => { r.scrollIntoView?.({block: 'center'}); r.classList.add('sflash'); setTimeout(() => r.classList.remove('sflash'), 1600); }, 30);  // 2.250.0 C (#2994): the soft ring (prefers-reduced-motion: a still ring)
  });
  setTimeout(() => $(`.snav [data-sec="${cur}"]`, md)?.scrollIntoView({block: 'nearest', inline: 'nearest'}), 0);
  if (cur === 'data') templatesDraw(md).then(() => { if (focus === 'templates') $('#s-tpl-h', md)?.scrollIntoView({block: 'start'}); });
  if (focus === 'sample') setTimeout(() => $('#s-sample-h', md)?.scrollIntoView({block: 'start'}), 0);
  if (cur === 'integr') { icalDraw(md); calsDraw(md); if (typeof dsc_integrDraw === 'function') dsc_integrDraw(md); }
  if (cur === 'access') acz_draw(md);  // 2.166.0 (#2633)
  calsWire(md); whWire(md); if (S.me?.is_admin) { agWire(md); audWire(md); }
  agSetupWire(md);  // 2.7.2 (#420)
  asst_setWire(md);  // 2.75.0 (#1411)
  if (cur === 'notify') wpDraw(md);
  ntfyShow(md);
  if (cur === 'users') { aaDraw(md); bkDraw(md); orphDraw(md); grpDraw(md); ocAdminDraw(md); Promise.resolve(admSubShow(md, ad_admFocus(focus))).then(() => { if (focus === 'activity') $('#s-adlog-h', md)?.scrollIntoView({block: 'start'}); }); }  // 2.42.0 (#828): + ocAdminDraw  // 2.46.6 (#1710): + the shown sub-tab's data; 'activity' = its log, once the rules above it are drawn
  aiTblWire(md);
  if (cur === 'ai') aiSubShow(md, {agents: 'agents', usage: 'usage', agentsafe: 'safe'}[focus]);  // 2.5.1 (#393)
  md.addEventListener('click', e => { const b = e.target.closest('[data-aisub]'); if (b) aiSubShow(md, b.dataset.aisub, true); const g = e.target.closest('[data-aigo]'); if (g) aiSubShow(md, g.dataset.aigo, true); });
  md.addEventListener('click', e => { const b = e.target.closest('[data-admsub]'); if (b) admSubShow(md, b.dataset.admsub, true); });  // 2.24.0 (#826)
  md.addEventListener('click', e => {  // 2.46.6 (#1710): "Open in Administration" next to an admin switch
    const b = e.target.closest('[data-adopen]'), el = b && $('#' + b.dataset.adopen, md); if (!el) return;
    show('users'); idx(false); const ap = el.closest('[data-admp]'); if (ap) admSubShow(md, ap.dataset.admp, true);
    const r = el.closest('label') || el;
    setTimeout(() => { r.scrollIntoView?.({block: 'center'}); r.classList.add('flash'); setTimeout(() => r.classList.remove('flash'), 1600); }, 30);
  });
  if (S.me?.is_admin) hostWire(md);
  aiuWire(md, only => { const box = $('#s-aiu', md); if (only && box && S.aiu.data) box.innerHTML = aiuHtml(S.aiu.data, Math.max(240, Math.min(720, (box.clientWidth || 560) - 8))); else aiuDraw(md); });  // 2.1.1 (#326)
  if (cur === 'account' && S.me) { tfaDraw(md); apwDraw(md); e2eDraw(md); if (typeof msvDraw === 'function') msvDraw(md); if (typeof sesDraw === 'function') sesDraw(md); }  // 2.73.0 A (#661); 2.115.0 B (#2062): + sessions
  if (S.me) { tfaWire(md); tokWire(md); apwWire(md); e2eWire(md); }  // 2.42.0 (#828): + end-to-end encryption
  if (S.me?.is_admin) oidcWire(md);
  if (S.me?.is_admin) { aaWire(md); bkWire(md); orphWire(md); }
  md.addEventListener('change', e => { if (e.target.id === 's-mdpen') { LS.set('mdPenOnly', e.target.checked); if (S.sel) renderDetail(); } });  // 2.40.0 (#1203): this device
  md.addEventListener('change', async e => {
    if (e.target.id !== 's-wpdev') return;
    e.target.disabled = true;
    try { if (e.target.checked ? await wpEnable() : await wpDisable()) toast(e.target.checked ? tr('Notifications on for this device') : tr('Notifications off for this device')); }
    catch (x) { if (x.message !== 'auth') toast(tr('Could not turn on notifications: {0}', x.message || x)); }
    await wpDraw(md);
  });
  const tabDraw = () => {
    const ids = tabIds(), box = $('#s-tabbar', md); if (!box) return;
    box.innerHTML = ids.map(tabItem).map((t, i) => t ? `<div class="navrow" data-tab="${esc(t.id)}">${t.icon}<span>${esc(t.label)}</span>${i === TAB_MAX - 1 && ids.length > TAB_MAX ? `<span class="muted" style="font-size:var(--fs-xs)">${tr('from here on “More”')}</span>` : ''}<button class="iconbtn" data-tmove="-1" title="${tr('move forward')}" aria-label="${esc(tr('move forward') + ': ' + t.label)}">${ic('chev', 's up')}</button><button class="iconbtn" data-tmove="1" title="${tr('move back')}" aria-label="${esc(tr('move back') + ': ' + t.label)}">${ic('chev', 's')}</button><button class="iconbtn" data-tdel title="${tr('remove')}" aria-label="${esc(tr('remove') + ': ' + t.label)}">${ic('x', 's')}</button></div>` : '').join('') || `<div class="muted" style="font-size:var(--fs-m)">${tr('Empty: only “More”')}</div>`;
  };
  md._tabDraw = tabDraw;
  // 2.25.0 (UX-03): the sidebar: groups up / down, an eye per group, check boxes for the entries of Plan and Views
  const sideDraw = () => {
    const box = $('#s-sidebar', md); if (!box) return;
    const p = sidePref(), ord = sideGroupOrder();
    const ent = g => (g === 'focus' ? SIDE_PLAN : g === 'views' ? sideViewEntries() : g === 'areas' ? sideAreaEntries() : []).map(([x, n]) => `<label class="chkl sidee"><input type="checkbox" data-side-e="${x}" ${x.split(',').every(y => p.hidden.includes('e:' + y)) ? '' : 'checked'}> ${esc(tr(n))}</label>`).join('');
    box.innerHTML = ord.map((g, i) => { const n = tr(SIDE_NAMES[g]), shown = !p.hidden.includes('g:' + g), e = shown ? ent(g) : '';
      return `<div class="navrow sidegrp ${shown ? '' : 'off'}" data-sideg="${g}">${g === 'lists' ? `<span class="iconbtn sideye" aria-hidden="true">${ic('list', 's')}</span>` : `<button class="iconbtn sideye" data-side-eye aria-pressed="${shown}" title="${esc(shown ? tr('Hide {0}', n) : tr('Show {0}', n))}" aria-label="${esc(tr('Show {0}', n))}">${ic(shown ? 'eye' : 'eyeoff', 's')}</button>`}<span>${esc(n)}</span><button class="iconbtn" data-smove="-1" ${i ? '' : 'disabled'} title="${tr('move up')}" aria-label="${esc(tr('Move {0} up', n))}">${ic('chev', 's up')}</button><button class="iconbtn" data-smove="1" ${i < ord.length - 1 ? '' : 'disabled'} title="${tr('move down')}" aria-label="${esc(tr('Move {0} down', n))}">${ic('chev', 's')}</button></div>${e ? `<div class="sideents">${e}</div>` : ''}`; }).join('');
  };
  md._sideDraw = sideDraw;
  const sideSave = o => setApply({sidebar: o ? JSON.stringify(o) : ''}, tr('Sidebar')).then(() => { sideDraw(); renderSide(); });
  sideDraw();
  md.addEventListener('change', e => {
    const x = e.target.dataset?.sideE; if (!x) return;
    const p = sidePref(), h = new Set(p.hidden);
    for (const y of x.split(',')) e.target.checked ? h.delete('e:' + y) : h.add('e:' + y);  // 2.44.0 (#1187): an area = all its parts
    sideSave({order: p.order, hidden: [...h]});
  });
  const tabApply = ids => { if (ids) LS.set('tabbar', ids); else LS.set('tabbar', null); tabDraw(); renderTabs(); };
  const tabSet = ids => setLocal(tr('Tab bar'), () => LS.get('tabbar', null), tabApply, ids);
  tabDraw();
  if (S.me) accountWire(md);
  mailWire(md);  // 2.17.0 (#443)
  niWire(md);  // 2.142.0 C (#2150)
  if (typeof chn_meDraw === 'function') chn_meDraw(md);  // 2.142.0 A (#2145)
  md.addEventListener('click', async e => {
    const hz = e.target.closest('#s-hszip'); if (hz) { tkh_zipClick(e, hz, md); return; }  // 2.138.0 C (#1907)
    const b = e.target.closest('button'); if (!b) return;
    const trow = b.closest('[data-tab]');
    if (trow && (b.dataset.tmove || 'tdel' in b.dataset)) {
      const ids = tabIds().filter(id => tabItem(id)), i = ids.indexOf(trow.dataset.tab);
      if ('tdel' in b.dataset) ids.splice(i, 1);
      else { const j = i + +b.dataset.tmove; if (j < 0 || j >= ids.length) return; [ids[i], ids[j]] = [ids[j], ids[i]]; }
      tabSet(ids); $$('[data-tab]', md).find(r => r.dataset.tab === trow.dataset.tab)?.querySelector(`[data-tmove="${b.dataset.tmove}"]`)?.focus(); return;
    }
    if (b.dataset.m === 's-undo') { const el = $('.ssaved', md); if (el?._e && HIST.undo[HIST.undo.length - 1] === el._e) { el.classList.remove('on'); histStep('undo'); } return; }
    if (b.dataset.m === 'tab-reset') { tabSet(null); return; }
    if (b.dataset.m === 'tab-add') { tabAddSheet(id => { tabSet([...tabIds(), id]); $('#s-tabadd', md)?.focus(); }); return; }  // 2.122.2 (#2329)
    if (b.dataset.m === 'sync-now') { b.disabled = true; try { if (OUT.q.length) await flush(); await refreshNow(); } finally { b.disabled = false; const st = $('#s-synced', md); if (st) st.textContent = syncedTxt(); } return; }  // 2.25.0 (UX-56)
    if (b.dataset.m === 'wp-on') { const c = $('#s-wpdev', md); if (c && !c.checked) c.click(); return; }  // 2.25.0 (UX-46)
    if (b.dataset.jump) { const t = $(b.dataset.jump, md); if (t) { t.scrollIntoView?.({block: 'start'}); t.classList.add('flash'); setTimeout(() => t.classList.remove('flash'), 1600); } return; }  // 2.25.0 (UX-20)
    const sg = b.closest('[data-sideg]');
    if (sg && (b.dataset.smove || 'sideEye' in b.dataset)) {  // 2.25.0 (UX-03)
      const p = sidePref(), g = sg.dataset.sideg;
      if ('sideEye' in b.dataset) { const h = new Set(p.hidden); h.has('g:' + g) ? h.delete('g:' + g) : h.add('g:' + g); await sideSave({order: p.order, hidden: [...h]}); }
      else { const o = sideGroupOrder(), i = o.indexOf(g), j = i + +b.dataset.smove; if (j < 0 || j >= o.length) return; [o[i], o[j]] = [o[j], o[i]]; await sideSave({order: o, hidden: p.hidden}); }
      $(`[data-sideg="${g}"] [data-${'sideEye' in b.dataset ? 'side-eye' : `smove="${b.dataset.smove}"`}]`, md)?.focus(); return;
    }
    if (b.dataset.m === 'side-reset') { await sideSave(null); return; }
    if (b.dataset.langSet) { setLang(b.dataset.langSet); return; }
    if (b.dataset.m === 'fs-reset') { fsStep(0); return; }  // 2.13.0 (#429)
    if (b.dataset.m === 'sto-check') { stoCheck(md); return; }  // 2.13.0
    if (b.dataset.vmode) { vpSet(md, b.dataset.vmode); return; }  // 2.310.0 (#3270)
    if (b.dataset.look === 'pack') { o3c_packPick(md, b.dataset.v); return; }  // 2.83.0 C (#1427): theme + scheme in one step
    if (b.dataset.look) {
      const k = b.dataset.look, v = b.dataset.v, n = {theme: N_('Color scheme'), density: N_('Density'), densitySide: N_('Density'), densityRows: N_('Density'), fsize: N_('Font size'), font: N_('Font'), accent: N_('Accent color'), chatHuman: N_('Messages from people'), chatAgent: N_('Messages from agents')}[k];
      setLocal(tr(n), () => lookCur(k), x => { lookSet(k, x); lookRedraw(md, `[data-look="${k}"][data-v="${x}"]`); }, v); return;
    }
    if (b.dataset.m === 'look-reset') {
      const snap = () => Object.fromEntries(LOOK_KEYS.map(k => [k, LS.get(k, null)]));
      const put = o => { for (const k of LOOK_KEYS) { if (o && o[k] != null) LS.set(k, o[k]); else LS.del(k); } applyTheme(); applyDensity(); applyLook(); render(); lookRedraw(md, '[data-m="look-reset"]'); };
      const e = setLocal(tr('Appearance'), snap, put, null); if (e) offerUndo(tr('Appearance reset to the defaults'), e); return;
    }
    if (b.dataset.m === 'tour') { md.remove(); tourStart(); return; }
    if (b.dataset.m === 'keys') { md.remove(); shortcutsModal(); return; }
    if (b.dataset.m === 'hints-reset') { LS.del('hintsSeen'); toast(tr('Done')); render(); return; }
    if (b.dataset.m === 'ag-guide') { aiSubShow(md, 'setup', true); return; }  // 2.4.2 (#392); 2.7.2 (#420): the Set up tab
    if (b.dataset.m === 'go-access') { $('.snav [data-sec="access"]', md)?.click(); return; }  // 2.166.0 (#2633)
    if (b.dataset.m === 'go-share') { $('.snav [data-sec="integr"]', md)?.click(); setTimeout(() => $('#s-share-h', md)?.scrollIntoView?.({block: 'start'}), 50); return; }  // 2.7.0 (#405 S3)
    if (b.dataset.m === 'go-modules') { $('.snav [data-sec="modules"]', md)?.click(); setTimeout(() => $('[data-pane="modules"] [data-modrow="agents"]', md)?.scrollIntoView?.({block: 'center'}), 50); return; }  // 2.6.0 (K09)
    if (b.dataset.m === 'cele-try') { const k = ['project', 'list', 'today'][(b._cele = ((b._cele ?? -1) + 1) % 3)]; celebrate(k, {force: true, name: k === 'project' ? tr('Example project') : tr('Example list')}); return; }  // 2.39.1 (#1292): each try shows the next level
    const trw = b.closest('[data-tpl]');
    if (trw) {
      const tp = ($('#s-tpls', md)._t || []).find(x => x.id === +trw.dataset.tpl); if (!tp) return;
      if ('tplUse' in b.dataset) { md.remove(); useTemplate(tp); }
      if ('tplEdit' in b.dataset) templateModal(tp, () => templatesDraw(md));
      return;
    }
    const a = b.dataset.m;
    if (a === 'close') md.remove();
    if (a === 'oidc-copy') { try { await navigator.clipboard.writeText($('#s-oidcredir', md).textContent); toast(tr('Copied')); } catch { toast(tr('Copy failed, select the codes by hand')); } return; }
    if (a && a.startsWith('ical-')) { icalAction(md, a.slice(5)); return; }
    if (a === 'drop-new-tok') { dropTokenNew(md); return; }
    if (a === 'drop-copy-url' || a === 'drop-copy-tok') {
      const i = $(a === 'drop-copy-url' ? '#s-dropurl' : '#s-droptok', md);
      if (!i) return;  // 2.138.0 C (#1907): the token field exists only right after creating a token
      try { await navigator.clipboard.writeText(i.value); toast(tr('Copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected text')); }
      return;
    }
    if (a === 'sample-add') { md.remove(); await sampleCreate(); return; }
    if (a === 'sample-rm') { b.disabled = true; try { await sampleRemove(); } finally { const r = $('#s-sample', md); if (r) r.innerHTML = sampleRowHtml(); } return; }
    if (a === 'test') { const j = await api('POST', '/api/ntfy/test'); toast(j.ok ? tr('Test sent') : tr('ntfy not reachable')); }
    if (a === 'ptest') { const j = await api('POST', '/api/push/test'); toast(j.ok ? tr('Test sent') : tr('Not delivered: no device accepted it and ntfy is not reachable')); }
    if (a === 'wp-test') { const j = await api('POST', '/api/push/test', {id: +b.dataset.sub}); toast(j.ok ? tr('Test sent to this device') : tr('The push service did not accept it')); if (!j.ok) wpDraw(md); }
    if (a === 'wp-del') {
      const cur = await wpSub();
      await api('DELETE', `/api/push/subs/${+b.dataset.sub}`);
      if (cur && b.dataset.ep === cur.endpoint) { await cur.unsubscribe().catch(() => {}); LS.del('wpUser'); }
      toast(tr('Device removed')); wpDraw(md);
    }
  });
  impInit(md);
  if (typeof umzInit === 'function') umzInit(md);  // 2.73.0 B (#1473): move / export everything (move.js)
  return md;
}
// ---- Settings > Data > Import (package C): pick the source, choose a file, preview (dry run on the server), import, undo
const IMP_SRC = [['todoist', 'Todoist'], ['trello', 'Trello'], ['asana', 'Asana'], ['mstodo', 'Microsoft To Do'],
  // 2.142.0 B (#2147): Notion, Google Tasks, ClickUp, Jira, any CSV, Markdown
  ['notion', 'Notion'], ['gtasks', 'Google Tasks'], ['clickup', 'ClickUp'], ['jira', 'Jira'],
  ['ics', N_('ICS / VTODO (Apple Reminders, Nextcloud, Thunderbird …)')], ['csv', N_('CSV file (any columns)')], ['markdown', N_('Markdown checklist')],
  ['ticktick', 'TickTick']];
const IMP_ACCEPT = {todoist: '.csv,.zip,.json,text/csv,application/zip,application/json', trello: '.json,application/json', asana: '.csv,text/csv',
  mstodo: '.csv,.ics,text/csv,text/calendar', ics: '.ics,.ical,.ifb,text/calendar', ticktick: '.csv,text/csv',
  notion: '.zip,.csv,.md,application/zip,text/csv,text/markdown', gtasks: '.zip,.json,application/zip,application/json', clickup: '.csv,text/csv',
  jira: '.csv,text/csv', csv: '.csv,.tsv,.txt,text/csv,text/tab-separated-values', markdown: '.md,.markdown,.txt,text/markdown,text/plain'};  // 2.142.0 B (#2147)
function impHelp(src) {
  return {
    todoist: tr('<b>Todoist:</b> open the project > … > Export as a CSV file (one file per project), or Settings > Backups > download a backup (a ZIP with every project). Sections, subtasks, @labels, priorities, dates (English and German date texts, also recurring ones), durations and comments are taken over; attachments stay links. The project is named after the file.'),
    trello: tr('<b>Trello:</b> open the board > Menu > Print, export and share > Export as JSON. Lists become sections of one project (or one project each, see below), cards tasks, checklists subtasks, labels tags, due dates and “complete” are kept; comments and attachment links go into the notes. Archived cards are skipped unless you choose otherwise.'),
    asana: tr('<b>Asana:</b> open the project > arrow next to its name > Export / Print > CSV. Sections, subtasks, tags, start and due dates and completion are taken over, other fields go into the notes. An assignee is assigned when they are a member of the target project (same e-mail or name), otherwise their name goes into the notes.'),
    mstodo: tr('<b>Microsoft To Do</b> has no export of its own. Recommended: classic Outlook for Windows > File > Open & Export > Import/Export > Export to a file > Comma Separated Values > your Tasks folder (Outlook for Mac: File > Export > Tasks). CSV files of export tools (columns such as Title, List, Status, Importance, Due) and ICS files work too. English and German Outlook columns are recognized, also in Windows-1252.'),
    ics: tr('<b>ICS files with tasks (VTODO):</b> Nextcloud Tasks (calendar > … > Export), Thunderbird (right-click the calendar > Export), Apple Reminders via an export app or a CalDAV server, Tasks.org via its CalDAV account. Each calendar becomes a project; subtasks, repetitions, reminders, categories (tags), priorities and completion are taken over.'),
    ticktick: tr('<b>TickTick:</b> Settings > Account > Generate backup (CSV). Imported directly, without a preview.'),
    // 2.142.0 B (#2147)
    notion: tr('<b>Notion:</b> Settings > Workspace > Export all workspace content (or … on a page > Export) > Markdown & CSV, include subpages. Choose the ZIP as it is (parts inside it are read too). Every database becomes a project (name, status, date, tags and priority are recognized, other properties go into the notes), pages with checkboxes become projects with tasks. People stay names in the notes.'),
    gtasks: tr('<b>Google Tasks:</b> takeout.google.com > deselect all > select Tasks > create the export, then choose the ZIP (or the Tasks.json inside it). Lists, subtasks, due dates, notes and completion are taken over.'),
    clickup: tr('<b>ClickUp:</b> open the list or space > … > Export > CSV, all columns. Lists (in folders), subtasks, checklists, tags, priorities, start and due dates, estimates and comments are taken over; assignees stay names in the notes.'),
    jira: tr('<b>Jira:</b> Filters > search the issues > Export > Export CSV (all fields). Each Jira project becomes a project; sub-tasks and child issues become subtasks, labels tags, priorities and due dates are kept; the issue key, description, sprint and components go into the notes, assignees stay names.'),
    csv: tr('<b>Any CSV file</b> (also from a spreadsheet): one row per task. Columns such as Title / Name / Task, Due / Date, Notes / Description, List / Project, Section, Priority, Tags and Done / Status are recognized in English and German; every other column goes into the notes. The preview shows which column went where.'),
    markdown: tr('<b>Markdown checklist</b> (Obsidian, Logseq, a README …): headings become projects (deeper headings sections), - [ ] and - [x] tasks, indented items subtasks, text below a task its notes. Only clear dates (2025-01-15 or 15.01.2025) and #tags are read.'),
  }[src] || '';
}
// 2.5.2 (K15): an own file button in the app's language (+ the chosen file's name) instead of the browser's "Browse… No file selected."
const fileBtn = (id, accept) => `<span class="filebtn"><label class="btn sm">${ic('file', 's')} ${tr('Choose a file…')}<input type="file" id="${id}" accept="${esc(accept)}" hidden></label><span class="muted fname" id="${id}-name">${tr('No file chosen')}</span></span>`;
document.addEventListener('change', e => {
  const f = e.target; if (!f?.matches?.('.filebtn input[type=file]')) return;
  const n = document.getElementById(f.id + '-name'); if (n) n.textContent = f.files?.[0]?.name || tr('No file chosen');
}, true);
function impInit(md) {
  const I = {src: 'todoist', file: null, opts: {}, last: null};
  const out = $('#s-imp-out', md), inp = $('#s-import', md);
  const form = dry => {
    const fd = new FormData(); fd.append('file', I.file);
    if (dry) fd.append('dry_run', '1');
    for (const [k, v] of Object.entries(I.opts)) if (v !== '' && v != null) fd.append(k, v);
    return fd;
  };
  const lists = () => (S.lists || []).filter(l => canEditList(l.id) && !l.archived);
  const sel = (id, label, opts, v) => `<div class="row"><label for="${id}">${label}</label><select id="${id}" data-io="${id.slice(6)}">${opts.map(([k, n]) => `<option value="${esc(k)}" ${String(v ?? '') === String(k) ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>`;
  const prio = p => p ? `<span class="imp-p p${p}">${tr(['', N_('Low'), '', N_('Medium'), '', N_('High')][p] || '')}</span>` : '';
  const warns = ws => ws.length ? `<ul class="slist impwarn">${ws.map(w => `<li>${esc(w.text)}${w.count > 1 ? ` <span class="muted">(${w.count}×)</span>` : ''}${w.examples?.length ? ` <span class="muted">– ${w.examples.map(esc).join(', ')}</span>` : ''}</li>`).join('')}</ul>` : '';
  function draw(j) {
    const c = j.created, n = c.tasks;
    const head = j.dry_run
      ? trn('Preview: {0} task will be created', 'Preview: {0} tasks will be created', n) + (j.skipped ? ' · ' + trn('{0} is already there and will be skipped', '{0} are already there and will be skipped', j.skipped) : '')
      : trn('Imported: {0} task', 'Imported: {0} tasks', n) + (j.skipped ? ' · ' + trn('{0} skipped (already there)', '{0} skipped (already there)', j.skipped) : '');
    const ls = j.lists.map(l => `<div class="mrow"><span class="n">${esc(l.name)}</span><span class="muted">${trn('{0} task', '{0} tasks', l.tasks)}${l.skipped ? ' · ' + tr('{0} skipped', l.skipped) : ''}${l.sections ? ' · ' + trn('{0} new section', '{0} new sections', l.sections) : ''} · ${l.existing ? tr('existing project') : tr('new project')}</span></div>`).join('');
    const opts = j.dry_run ? sel('s-imp-target', tr('Into'), [['new', tr('New projects (an own project with the same name is reused)')], ...lists().map(l => [String(l.id), lname(l)])], I.opts.target || 'new')
      + (wsOn() && !(I.opts.target && I.opts.target !== 'new') ? sel('s-imp-space', tr('Workspace'), wsOptions().filter(w => w !== 'all').map(w => [w, wsName(w)]), I.opts.space) : '')  // 2.87.9 (#1940)
      + (I.src === 'trello' ? sel('s-imp-mode', tr('Trello lists'), [['sections', tr('as sections of one project')], ['lists', tr('as separate projects (in a folder)')]], I.opts.mode || 'sections')
        + sel('s-imp-archived', tr('Archived cards'), [['skip', tr('skip')], ['done', tr('import as completed')]], I.opts.archived || 'skip') : '')
      + sel('s-imp-completed', tr('Completed tasks'), [['import', tr('import as completed')], ['skip', tr('skip')]], I.opts.completed || 'import')
      + (I.src === 'todoist' ? sel('s-imp-priority_scale', tr('Todoist priorities'), [['auto', tr('detect automatically')], ['1', tr('1 = p1 (highest)')], ['4', tr('4 = p1 (highest)')]], I.opts.priority_scale || 'auto') : '')
      + (j.lists.length === 1 && !(I.opts.target && I.opts.target !== 'new') ? `<div class="row"><label for="s-imp-name">${tr('Project name')}</label><input id="s-imp-name" data-io="list_name" maxlength="200" value="${esc(I.opts.list_name ?? j.lists[0].name)}"></div>` : '') : '';
    // 2.142.0 B (#2147): any CSV: which column went where
    const IMP_FIELD = {title: N_('Title'), id: N_('Id'), parent: N_('Parent task'), list: N_('Project'), section: N_('Section'), due: N_('Due date'), due_time: N_('Time'),
      start: N_('Start date'), notes: N_('Notes'), priority: N_('Priority'), tags: N_('Tags'), done: N_('Done'), done_at: N_('Completed at'), created: N_('Created'),
      assignee: N_('Assignee (as text)'), url: N_('Link')};
    const cols = j.dry_run && j.columns?.length ? `<div class="imptab impcols"><div class="muted">${tr('Columns')}</div>${j.columns.map(c => `<div class="impr" data-field="${esc(c.field)}"><span class="n">${esc(c.column)}</span><span class="muted">${esc(tr(IMP_FIELD[c.field] || c.field))}</span></div>`).join('')}</div>` : '';
    const sm = j.dry_run && j.samples.length ? `<div class="imptab"><div class="muted">${tr('Examples')}</div>${j.samples.map(t => `<div class="impr${t.subtask ? ' sub' : ''}"><span class="n">${esc(t.title)}</span><span class="muted">${esc([t.section, t.due ? fmtDayAbs(t.due) + (t.due_time ? ' ' + t.due_time : '') : '', t.repeat ? repeatLabel(t.repeat) : '', t.status ? tr('Done') : ''].filter(Boolean).join(' · '))}</span>${prio(t.priority)}${t.tags.map(g => `<span class="tag">#${esc(g)}</span>`).join('')}</div>`).join('')}</div>` : '';
    const btns = j.dry_run
      ? `<div class="row"><button class="btn sm pri" data-imp="go" ${n ? '' : 'disabled'}>${ic('download', 's')} ${trn('Import {0} task', 'Import {0} tasks', n)}</button><button class="btn sm" data-imp="cancel">${tr('Cancel')}</button></div>`
      : (j.import_id ? `<div class="row"><button class="btn sm" data-imp="undo" data-id="${+j.import_id}">${tr('Undo this import')}</button><span class="muted">${tr('possible for 24 hours')}</span></div>` : '');
    out.innerHTML = `<div class="impbox" role="status"><div class="imphead"><b>${esc(head)}</b></div>${ls}${warns(j.warnings)}${opts}${cols}${sm}${btns}</div>`;
  }
  async function preview() {
    if (!I.file) return;
    out.innerHTML = botBusy(`<div class="muted mhint">${tr('Reading the file…')}</div>`);  // 2.161.2 (#2611): the bot at work
    try { I.last = await api('POST', `/api/import/${I.src}`, form(true)); draw(I.last); }
    catch { out.innerHTML = ''; }
  }
  async function hist() {
    const box = $('#s-imp-hist', md); if (!box) return;
    let j; try { j = await api('GET', '/api/imports'); } catch { return; }
    const rows = j.imports.filter(x => x.can_undo).slice(0, 5);
    box.innerHTML = rows.length ? `<div class="muted mhint">${tr('Recent imports')}</div>` + rows.map(x => `<div class="mrow"><span class="n">${esc(x.source_name)}${x.file_name ? ' · ' + esc(x.file_name) : ''}</span><span class="muted">${trn('{0} task', '{0} tasks', x.counts.tasks || 0)}</span><button class="btn sm" data-imp="undo" data-id="${+x.id}">${tr('Undo')}</button></div>`).join('') : '';
  }
  hist();
  $('#s-imp-src', md).addEventListener('change', e => {
    I.src = e.target.value; I.opts = {}; I.file = null; inp.value = ''; const fn = $('#s-import-name', md); if (fn) fn.textContent = tr('No file chosen'); inp.accept = IMP_ACCEPT[I.src] || ''; out.innerHTML = '';
    $('#s-imp-help', md).innerHTML = impHelp(I.src);
  });
  inp.addEventListener('change', async e => {
    const f = e.target.files[0]; if (!f) return;
    if (I.src === 'ticktick') {
      // 2.87.9 (#1940): TickTick's lists always become private lists of the person
      if (!await importTargetConfirm({what: tr('the tasks'), ws: 'private'})) { inp.value = ''; const fn = $('#s-import-name', md); if (fn) fn.textContent = tr('No file chosen'); return; }
      const fd = new FormData(); fd.append('file', f);
      const j = await api('POST', '/api/import/ticktick', fd);
      toast(tr('Import: {0} tasks, {1} new projects', j.tasks, j.lists) + (j.skipped ? tr(', {0} already there', j.skipped) : ''));
      inp.value = ''; await load(); render(); return;
    }
    // 2.87.9 (#1940): new lists go into the workspace shown in the sidebar
    // 2.144.5 B (#2002): "All" = the private space (the dialog offers the first organisation instead)
    const cur = wsCur();
    I.file = f; I.opts = {space: cur !== 'all' ? cur : 'private'}; await preview();
  });
  out.addEventListener('change', e => {
    const k = e.target.dataset.io; if (!k) return;
    I.opts[k] = e.target.value;
    if (k === 'target' && e.target.value !== 'new') delete I.opts.list_name;
    if (k !== 'list_name') preview();
  });
  const undo = async id => {
    // 2.272.0 C (#3027): the undo moves into the trash and keeps what changed since -- the texts say exactly that
    if (!await askConfirm(tr('Undo this import?'), tr('The imported tasks nobody changed since go into the trash, where you can restore them; a new project only when nothing else is in it. Tasks changed since then or with new comments, files or times stay, and so does everything others added.'), {ok: tr('Undo'), danger: true})) return;
    const j = await api('POST', `/api/imports/${id}/undo`);
    toast([trn('Import undone: {0} task moved to the trash', 'Import undone: {0} tasks moved to the trash', j.tasks || 0),
      j.kept_tasks ? trn('{0} changed task stays', '{0} changed tasks stay', j.kept_tasks) : '',
      j.kept_lists ? trn('{0} project stays because something was added to it', '{0} projects stay because something was added to them', j.kept_lists) : ''].filter(Boolean).join('. '));
    out.innerHTML = ''; await load(); render(); hist();
  };
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-imp]'); if (!b || !md.contains(b)) return;
    const a = b.dataset.imp;
    if (a === 'cancel') { out.innerHTML = ''; I.file = null; inp.value = ''; return; }
    if (a === 'undo') { await undo(+b.dataset.id); return; }
    if (a === 'go') {
      // 2.87.9 (#1940): where the tasks go, in words; new lists from an organisation can go into the private space instead
      const tl = I.opts.target && I.opts.target !== 'new' ? listById(+I.opts.target) : null, n = I.last?.created?.tasks;
      const firstOrg = (S.me?.workspaces || [])[0], orgAlt = !tl && (I.opts.space || 'private') === 'private' && firstOrg ? 'org:' + firstOrg.id : '';  // 2.144.5 B (#2002)
      const to = await importTargetConfirm({what: n ? trn('{0} task', '{0} tasks', n) : tr('the tasks'), ws: tl ? wsOf(tl) : I.opts.space || 'private', place: tl ? lname(tl) : '', privOk: !tl, orgAlt});
      if (!to) return;
      if (to === 'private') I.opts.space = 'private';
      if (to === 'org') I.opts.space = orgAlt;
      b.disabled = true;
      try {
        const j = await api('POST', `/api/import/${I.src}`, form(false));
        I.file = null; inp.value = ''; draw(j);
        toast(trn('Imported: {0} task', 'Imported: {0} tasks', j.created.tasks));
        await load(); render(); hist();
      } catch { b.disabled = false; }
    }
  });
}
// Settings > Administration: the instance-wide switches, applied at once
// 2.45.0 (#1515): no server key = tokens, the sign-on secret and organisation encryption cannot be stored: say so loudly
const shKeyWarn = a => a.secret_key === false ? `<div class="shint warn shkey" role="alert"><b>${tr('The server key is missing')}</b> ${esc(a.secret_key_problem === 'invalid' ? tr('KALMIDO_SECRET_KEY (or the key file) is not valid: it must be 32 random bytes, base64.') : a.secret_key_problem === 'file_in_data' ? tr('KALMIDO_SECRET_FILE lies inside the data or backup folder and was ignored. Put it on its own volume.') : a.secret_key_problem === 'file_error' ? tr('The key file KALMIDO_SECRET_FILE cannot be read or written, see the server log. After an update: create the folder secret next to data and give it to the user 1000 (mkdir secret && chown 1000 secret), then restart.') : tr('Without KALMIDO_SECRET_KEY or KALMIDO_SECRET_FILE no access token can be stored and organisation data stays unencrypted. See SELF-HOSTING.md.'))}</div>` : a.secret_key_src === 'file' ? `<div class="shint shkey">${esc(tr('The server key is kept in the key file. Keep a copy of it apart from the backups: without it the encrypted data of a backup cannot be read.'))}</div>` : '';  // 2.45.0 (#1515): review: a new key file is announced
function instanceHtml(chk, hint) {
  const a = S.about || {};
  return `${shKeyWarn(a)}<h4 id="s-instance-h">${tr('Whole server')}</h4>
    ${hint(tr('Apply to every user at once. Nothing is deleted: switched back on, everything is there again.'))}
    <div class="featgrid">${ad_allSwHtml()}
      <label class="wide"><input type="checkbox" id="s-publinks" ${a.public_links !== false && a.public_links_env !== false ? 'checked' : ''} ${a.public_links_env === false ? 'disabled' : ''}><span>${tr('Public links to projects')}<small class="muted">${a.public_links_env === false ? `<span title="KALMIDO_PUBLIC_LINKS=0">${tr('Switched off by the server operator.')}</span>` : tr('Projects and files of the file store can be shared with people without an account through a secret link. Off: every public link stops working at once; nothing is deleted.')}</small></span></label>
      <label class="wide"><input type="checkbox" id="s-updcheck" ${a.update_check !== false && a.update_env !== false ? 'checked' : ''} ${a.update_env === false ? 'disabled' : ''}><span>${tr('Check daily for a new version')}<small class="muted">${a.update_env === false ? `<span title="KALMIDO_UPDATE_CHECK=0">${tr('Switched off by the server operator.')}</span>` : tr('The server asks GitHub once a day for the latest release; nothing is installed automatically and the browser never contacts GitHub. The result shows below.')}</small></span></label>
    </div>
    ${S.timeAll !== false ? `<h4 id="s-dayh-h">${tr('Time sums')}</h4>
    <div class="row"><label for="s-dayh">${tr('Hours per day')}</label><input id="s-dayh" inputmode="decimal" class="numin" value="${esc(fmtNum(a.time_day_h || S.timeDayH || 8, 2))}"><span class="muted">${tr('h per working day / shift')}</span></div>
    ${hint(tr('Projects with progress and status show their tracked time in hours and in days of this length. A project can set its own value (project dialog); it then applies to everyone in that project.'))}` : ''}
    ${cer_html(a, hint)}
    ${a.cal_on || S.webhooks?.enabled ? `<details class="sdev"><summary>${ic('key', 's')}${tr('Advanced · for developers')}</summary><h4 id="s-calhosts-h">${tr('Allowed internal hosts')}</h4>
    ${hint(tr('Calendar subscriptions and webhooks only reach public addresses. List servers in your own network here (host or host:port, comma-separated); webhooks may use http:// only for these.') + (a.cal_allow_env ? ' ' + esc(tr('Also allowed by the server configuration: {0}', a.cal_allow_env)) : ''))}
    <div class="row"><textarea id="s-calhosts" rows="2" spellcheck="false" autocapitalize="off" aria-labelledby="s-calhosts-h" placeholder="nextcloud.home.arpa, 10.0.0.20:5232">${esc(a.cal_allow_hosts || '')}</textarea></div>
    </details>` : ''}`;
}
// 2.102.0 E (#1999): the browser's own errors (static/js/clienterr.js) as bug tickets in one project list with error reports
// on (list dialog > Repository); only lists the admin manages. "Off" = the browsers send nothing.
function cer_html(a, hint) {
  const ls = a.client_errors_lists || [], cur = a.client_errors_list || 0;
  return `<h4 id="s-cer-h">${tr('Errors in the browser')}</h4>
    ${hint(tr('An unexpected error in the app becomes a bug ticket in this project: only the message, the place in the code, the version and the open area; never texts of tasks or form values. To choose from: projects with error reports on (project dialog > Repository).'))}
    <div class="row"><label for="s-cerlist">${tr('Report to')}</label><select id="s-cerlist"><option value="0">${tr('Off')}</option>${ls.map(l => `<option value="${l.id}"${l.id === cur ? ' selected' : ''}>${esc(l.name)}</option>`).join('')}</select></div>`;
}
async function cer_setList(el) {
  const from = (S.about || {}).client_errors_list || 0, to = +el.value || 0;
  if (to === from) return;
  const put = async v => { const j = await api('PATCH', '/api/admin/settings', {client_errors_list: v || null}); S.about = {...S.about, ...j}; const f = $('#s-cerlist'); if (f) f.value = String(j.client_errors_list || 0); return {skipped: []}; };
  try { await put(to); } catch { el.value = String(from); return; }
  setSaved(histAdd({label: tr('Changed setting: {0}', tr('Errors in the browser')), sett: true, undo: () => put(from), redo: () => put(to)}));
}
// Settings > Users > Whole server > Admin alerts: operational warnings to the admins via ntfy (server side, own
// "Save"; loaded when the pane opens). Recent alerts below, with "Clear".
const aaHtml = () => `<h4 id="s-aa-h">${tr('Admin alerts')}</h4><div id="s-aa"><div class="muted mhint">${tr('Loading…')}</div></div>`;
const AA_STATE = {sent: N_('delivered'), failed: N_('not delivered'), queued: N_('waiting for the summary'), summarized: N_('in the summary'), capped: N_('hourly limit reached'), listed: N_('only listed (no device or topic yet)')};
function aaWhen(x) { return x ? new Date(x).toLocaleString(I18N.code || 'en', {dateStyle: 'short', timeStyle: 'short'}) : ''; }
async function aaDraw(md, j) {
  const box = $('#s-aa', md); if (!box) return;
  if (!j) { try { j = await api('GET', '/api/admin/alerts'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; } }
  const hint = t => `<div class="shint">${t}</div>`, num = (id, v, lo, hi, w) => `<input type="number" class="aanum${w ? ' wide' : ''}" id="${id}" value="${esc(v)}" min="${lo}" max="${hi}">`;
  // 2.5.2 (K04): where the alerts really go per admin (Web Push devices and / or an ntfy topic); nowhere yet = a neutral hint
  const via = a => [a.devices ? trn('Web Push to {0} device', 'Web Push to {0} devices', a.devices) : '', a.topic ? `ntfy <code class="topic">${esc(a.topic)}</code>` : ''].filter(Boolean).join(' + ') || `<span class="muted">${tr('nowhere yet')}</span>`;
  const rc = j.topic ? tr('Goes to the admin topic {0}.', `<code class="topic">${esc(j.topic)}</code>`)
    : j.admins.length ? tr('Goes to each admin over their own notification channel: {0}.', j.admins.map(a => `${esc(a.username)}: ${via(a)}`).join(', ')) : '';
  const meA = j.admins.find(a => a.me), meNone = !j.topic && meA && !meA.devices && !meA.topic;
  let h = j.env ? '' : hint(tr('Admin alerts are switched off by the server operator.') + ' (KALMIDO_ADMIN_ALERTS=0)');
  h += `<div class="featgrid"><label class="wide"><input type="checkbox" id="aa-on" ${j.on && j.env ? 'checked' : ''} ${j.env ? '' : 'disabled'}><span>${tr('Admin alerts')}<small class="muted">${tr('Warnings about the server go to the admins over their own notification channel (Web Push to their devices, ntfy only if they chose it or an admin topic is set): updates, delivery problems, watchdog errors, integrations, security events, disk space. Only counts, ids, usernames, device labels and error classes, never task contents.')}</small></span></label></div>
    ${meNone && j.on && j.env ? `<div class="shint aanone">${ic('bell', 's')} <span>${tr('No device subscribed for push yet. Until you subscribe one, admin alerts are only listed here.')}</span> <button class="btn sm" data-aa="notify">${tr('Subscribe this device')}</button></div>` : ''}
    <div class="row"><label for="aa-topic">${tr('Admin topic')}</label><input id="aa-topic" value="${esc(j.topic)}" autocapitalize="off" placeholder="${tr('empty = each admin’s own topic')}" ${j.topic_env ? 'readonly' : ''}></div>
    ${rc || j.topic_env ? `<div class="shint iiok">${(j.topic_env ? tr('Set by the server operator.') + ' (KALMIDO_ADMIN_TOPIC) ' : '') + rc}</div>` : ''}
    <div class="row"><label for="aa-prio">${tr('How urgent')}</label><select id="aa-prio">${[['3', N_('Normal')], ['4', N_('Loud')], ['5', N_('Urgent')]].map(([v, n]) => `<option value="${v}" ${j.prio === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
    <div class="row"><label for="aa-mode">${tr('Delivery')}</label><select id="aa-mode"><option value="instant" ${j.mode === 'instant' ? 'selected' : ''}>${tr('Instantly')}</option><option value="digest" ${j.mode === 'digest' ? 'selected' : ''}>${tr('Daily summary')}</option></select>${timeIn('aa-dtime', j.digest_time, {label: tr('Time of the daily summary'), clear: false, hidden: j.mode !== 'digest'})}</div>
    <div class="featgrid" id="aa-kinds">${j.all_kinds.map(k => `<label><input type="checkbox" data-aakind="${esc(k.kind)}" ${j.kinds.includes(k.kind) ? 'checked' : ''}> ${esc(k.label)}</label>`).join('')}</div>
    <details class="aalimits"><summary class="muted">${tr('Limits and thresholds')}</summary>
      <div class="row"><label for="aa-cool">${tr('Cooldown')}</label>${num('aa-cool', j.cooldown_h, 0, 168)}<span class="muted">${tr('hours per identical alert')}</span></div>
      <div class="row"><label for="aa-max">${tr('At most')}</label>${num('aa-max', j.max_hour, 1, 100)}<span class="muted">${tr('alerts per hour')}</span></div>
      <div class="row"><label for="aa-dpct">${tr('Low disk space')}</label>${num('aa-dpct', j.disk_pct, 0, 99)}<span class="muted">%</span>${num('aa-dmb', j.disk_mb, 0, 10000000, 6.5)}<span class="muted">${tr('MB free (0 = off)')}</span></div>
      <div class="row"><label for="aa-imin">${tr('Integrations')}</label>${num('aa-imin', j.integ_min, 1, 1440)}<span class="muted">${tr('minutes failing before an alert')}</span></div>
    </details>
    <div class="row"><button class="btn sm" data-aa="test" ${j.env ? '' : 'disabled'}>${ic('bell', 's')} ${tr('Send test alert')}</button></div>`;
  const st = j.storage || {}, qc = j.quick_check || {};
  if (j.rls_off) h += hint(tr('Row-level security is OFF: the database user bypasses it and the role kalmido_app cannot be used. Allow the database user to create roles or create the role (see SELF-HOSTING), then restart.'));  // 2.37.0 (review W2-2)
  if (st.total || qc.at) h += hint([st.total ? tr('Data volume: {0} free ({1} %).', st.free >= 1e9 ? (st.free / 1e9).toFixed(1) + ' GB' : Math.round(st.free / 1e6) + ' MB', st.pct) : '', qc.at ? (!qc.ok ? tr('Database check FAILED ({0}).', aaWhen(qc.at)) : qc.checksums === false ? tr('Database check: data checksums are off ({0}).', aaWhen(qc.at)) : tr('Database check ok ({0}).', aaWhen(qc.at))) : ''].filter(Boolean).join(' '));
  h += `<h4>${tr('Recent admin alerts')}</h4>`;
  h += j.items.length ? `<div class="members aalist">${j.items.map(a => `<div class="mrow aarow ${a.delivered || a.state === 'queued' ? '' : 'off'}" data-aaid="${a.id}"><span class="n"><b>${esc(a.label)}</b> · ${esc(a.message)}<small class="muted" style="display:block">${esc(aaWhen(a.created_at))} · ${tr(AA_STATE[a.state] || a.state)}${a.repeats ? ' · ' + trn('repeated {0} time since', 'repeated {0} times since', a.repeats) : ''}</small></span></div>`).join('')}</div>
    <div class="row"><button class="btn sm" data-aa="clear">${ic('trash', 's')} ${tr('Clear list')}</button></div>` : `<div class="muted mhint">${tr('No admin alerts yet.')}</div>`;
  box.innerHTML = h;
  box._body = aaBody(md);
}
const aaBody = md => $('#aa-on', md) ? {on: $('#aa-on', md).checked, ...($('#aa-topic', md).readOnly ? {} : {topic: $('#aa-topic', md).value.trim()}), prio: $('#aa-prio', md).value,
  mode: $('#aa-mode', md).value, digest_time: $('#aa-dtime', md).value || '08:00', kinds: $$('[data-aakind]', md).filter(x => x.checked).map(x => x.dataset.aakind),
  cooldown_h: +$('#aa-cool', md).value || 0, max_hour: +$('#aa-max', md).value || 1, disk_pct: +$('#aa-dpct', md).value || 0, disk_mb: +$('#aa-dmb', md).value || 0, integ_min: +$('#aa-imin', md).value || 1} : null;
function aaWire(md) {
  const save = () => api('PATCH', '/api/admin/alerts', aaBody(md));
  // every change is saved at once (U03); undo puts the previous form back
  md.addEventListener('change', async e => {
    if (!e.target.closest('#s-aa') || !e.target.matches('input,select')) return;
    if (e.target.id === 'aa-mode') { const t = $('#aa-dtime-w', md); if (t) t.hidden = e.target.value !== 'digest'; }
    const box = $('#s-aa', md), from = box._body, to = aaBody(md);
    if (!to || JSON.stringify(from) === JSON.stringify(to)) return;
    try { await save(); } catch { return; }
    box._body = to;
    const put = v => async () => { const j = await api('PATCH', '/api/admin/alerts', v); const m = $('.smodal'); if (m) await aaDraw(m, j); return {skipped: []}; };
    setSaved(histAdd({label: tr('Changed setting: {0}', tr('Admin alerts')), sett: true, undo: put(from), redo: put(to)}));
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-aa]'); if (!b) return;
    if (b.dataset.aa === 'notify') { $('.snav [data-sec="notify"]', md)?.click(); return; }  // 2.5.2 (K04)
    b.disabled = true;
    try {
      if (b.dataset.aa === 'test') {
        await save();  // the test uses what the form shows
        const j = await api('POST', '/api/admin/alerts/test');
        toast(j.ok ? tr('Test alert sent') : tr('Test alert not delivered')); await aaDraw(md, j.alerts);
      }
      if (b.dataset.aa === 'clear') { if (!await askConfirm(tr('Clear the list of admin alerts?'), '', {ok: tr('Clear list'), danger: true})) return; await aaDraw(md, await api('DELETE', '/api/admin/alerts')); }
    } catch { /* api() showed it */ } finally { b.disabled = false; }
  });
}
// project links (Settings > Help, command palette); always a new tab without referrer
// 2.53.0 (#1410): ABOUT_LINKS + openExt live in setcore.js (the command palette opens them)
// 2.27.0 (#968): the code in this window (index.html) next to the server's version; differ they: marked + "Reload"
function aboutVerRows(a) {
  const srv = S.serverVer || a.version || '', app = APP_VER || '';
  if (!app) return '';
  const off = srv && app !== srv;
  return `<div class="row aboutapp${off ? ' off' : ''}"><label>${tr('App in this window')}</label><span>v${esc(app)}${off ? ` · <b>${esc(tr('Server: v{0}', srv))}</b> <button type="button" class="btn sm pri" data-nv="go">${esc(tr('Reload'))}</button>` : ` · <span class="muted">${esc(tr('up to date'))}</span>`}</span></div>`;
}
// Settings > Help: the version, 2.101.0 (#1964): the trademark note (2.46.6 (#1710): the admins' update check result moved to Administration > Server, ad_updHtml)
function aboutHtml(chk, hint) {
  const a = S.about || {};
  let h = `<h4 id="s-about-h">${tr('About')}</h4><div class="row"><label>${tr('Version')}</label><span class="aboutver">Kalmido v${esc(a.version || '?')}</span></div>${aboutVerRows(a)}
    <div class="row aboutcopy"><label>©</label><span class="muted">2026 Gegenschuss Doberenz Enders Grund eGbR · AGPL-3.0</span></div>
    <div class="row aboutmarks"><label></label><span class="muted">${tr('Product and company names mentioned in Kalmido are trademarks of their respective owners. Kalmido is an independent project, not affiliated with or endorsed by them.')}</span></div>
    <div class="row aboutlinks"><label></label>${ABOUT_LINKS.map(([u, n, i]) => `<a class="btn sm" href="${u}" target="_blank" rel="noopener noreferrer">${ic(i, 's')} ${tr(n)}</a>`).join('')}${legalLinks(a.legal, 'btn sm')}</div>`;
  h += sup_aboutHtml();  // 2.74.0 (#338): "Support Kalmido" (self-hosted only)
  return h;
}
// 2.46.6 (#1710): Administration > Server: the result of the daily update check (server side, never automatic)
function ad_updHtml(hint) {
  const a = S.about || {};
  let h = '';
  if (a.available) {
    h += `<div class="shint updline"><b>${tr('v{0} installed — v{1} available', esc(a.version), esc(a.latest))}</b>${a.url ? ` · <a href="${esc(a.url)}" target="_blank" rel="noopener">${tr('Release notes')}</a>` : ''}</div>
      <div class="shelp">${tr('To update, run <code>~/kalmido/update.sh</code> (installed with the installer; it backs up the database first), or in the folder with docker-compose.yml: <code>docker compose pull && docker compose up -d</code> (prebuilt image) or <code>git pull && docker compose up -d --build</code> (built from source).')}</div>`;
  } else if (a.update_env && a.update_check && a.checked_at) {
    const when = new Date(a.checked_at).toLocaleString(I18N.code || 'en');
    h += hint(a.error ? tr('The last update check failed ({0}); it tries again later.', esc(a.error)) : a.latest ? tr('Up to date (checked {0}).', esc(when)) : tr('Checked {0}.', esc(when)));
  }
  return h ? `<h4 id="s-upd-h">${tr('Updates')}</h4>${h}` : '';
}
const ADMIN_SW = {'s-collaball': ['collab_all', N_('Collaboration for everyone')], 's-timeall': ['time_all', N_('Time tracking for everyone')], 's-updcheck': ['update_check', N_('Check daily for a new version')],
  's-2fareq': ['twofa_required', N_('Require two-factor authentication')], 's-pklogin': ['passkey_login', N_('Passkey login')], 's-oidcauto': ['oidc_autocreate', N_('Create accounts on first OIDC login')], 's-publinks': ['public_links', N_('Public links to projects')],
  's-collaball-a': ['collab_all', N_('Collaboration for everyone')], 's-timeall-a': ['time_all', N_('Time tracking for everyone')]};  // 2.46.6 (#1710): the same switches under Administration > Server
async function adminSwitch(md, el, fromHist) {
  const on = el.checked;
  const ask = async (t, b, ok) => fromHist || await askConfirm(t, b, {ok, danger: true});
  const key = ADMIN_SW[el.id][0];
  if (key === 'collab_all' && !on && !await ask(tr('Turn collaboration off for everyone?'), tr('Shared projects are then only visible to their owner; nothing is deleted.'), tr('Turn off'))) { el.checked = true; return; }
  if (key === 'time_all' && !on && !await ask(tr('Turn time tracking off for everyone?'), tr('Running timers are stopped now; entries are kept.'), tr('Turn off'))) { el.checked = true; return; }
  if (el.id === 's-2fareq' && on && !await ask(tr('Require two-factor authentication?'), tr('Everyone who logs in with a password must set it up at the next login (sessions that are open now stay open).'), tr('Require'))) { el.checked = false; return; }
  if (el.id === 's-publinks' && !on && !await ask(tr('Turn public links off for everyone?'), tr('Every public link stops working at once; nothing is deleted.'), tr('Turn off'))) { el.checked = true; return; }
  try {
    // 2.306.0 Fix-1 (#2875 review): accounts by the sign-on's admin rule: switched on with the account password
    const pw = key === 'oidc_autocreate' && on;
    let j; try { j = await (pw ? rawFetch : api)('PATCH', '/api/admin/settings', {[key]: on}); } catch (x) {
      if (!pw || !x.data?.password_needed) { if (pw) toast(x instanceof Offline ? tr('Offline: only works again with a connection') : x.message); throw x; }
      const p = await pwPrompt(tr('Confirm with your password')); if (!p) throw x;
      j = await api('PATCH', '/api/admin/settings', {[key]: on, password: p.password});
    }
    if (j && j.version) S.about = j;
  } catch { el.checked = !on; return; }
  if (!fromHist) {  // one history step; undo / redo flip the switch back through the same path (no second question)
    const flip = v => async () => { const m = $('.smodal'), x = m && $('#' + el.id, m); if (x) { x.checked = v; await adminSwitch(m, x, true); } else { await api('PATCH', '/api/admin/settings', {[key]: v}); await load(); } return {skipped: []}; };
    setSaved(histAdd({label: tr('Changed setting: {0}', tr(ADMIN_SW[el.id][1])), sett: true, undo: flip(!on), redo: flip(on)}));
  }
  if (key === 'collab_all') S.collabAll = on;
  else if (key === 'time_all') S.timeAll = on;
  else if (key === 'public_links') { S.publicLinks = on; return; }
  else return;
  await load(); render();
  if ((key === 'collab_all' || key === 'time_all') && md.isConnected) {
    const sec = $('.snav [data-sec].on', md)?.dataset.sec || LS.get('settingsSec', 'modules'), sc = $('.spanes', md)?.scrollTop || 0; md._noflush = true; md.remove();  // 2.46.6 (#1710): sec = the area shown
    const n = settingsModal(sec === 'users' ? 'server' : sec), p = $('.spanes', n); if (p) p.scrollTop = sc;  // 2.46.6 (#1710): back on Administration > Server
    if (!fromHist) setSaved(HIST.undo[HIST.undo.length - 1]);
  }
}
// calendar subscription (Settings > Integrations): the secret feed link, copy / new link / off
async function icalDraw(md, j) {
  const box = $('#s-ical', md); if (!box) return;
  if (!j) { try { j = await api('GET', '/api/ical'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; } }
  // 2.138.0 C (#1907): the server keeps only a hash: the link is in the answer of create / rotate once, later only "active since"
  if (!j.url && !j.active) { box.innerHTML = `<div class="row"><button class="btn sm pri" data-m="ical-create">${ic('cal', 's')} ${tr('Create subscription link')}</button></div>`; return; }
  const at = j.created_at ? new Date(j.created_at) : null, btns = `<button class="btn sm" data-m="ical-rotate">${ic('key', 's')} ${tr('New link')}</button><button class="btn sm danger" data-m="ical-off">${tr('Turn off')}</button>`;
  if (!j.url) { box.innerHTML = `<div class="row"><span class="muted" id="s-icalact">${at && !isNaN(at) ? esc(tr('Subscription link active since {0}', at.toLocaleDateString(LOCALE()))) : tr('Subscription link active')}</span></div><div class="row">${btns}</div>`; return; }
  box.innerHTML = `<div class="row icalrow"><input id="s-icalurl" readonly value="${esc(j.url)}" aria-label="${tr('Subscription link')}"><button class="btn sm pri" data-m="ical-copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <div class="shint keep" role="status">${tr('Only visible now: copy it now. If you lose it, create a new one.')}</div>
    <div class="row"><a class="btn sm" href="${esc(j.url.replace(/^https?:/, 'webcal:'))}">${ic('cal', 's')} ${tr('Open in calendar app')}</a>${btns}</div>`;
}
async function icalAction(md, a) {
  if (a === 'copy') {
    const i = $('#s-icalurl', md);
    try { await navigator.clipboard.writeText(i.value); toast(tr('Link copied')); } catch { i.focus(); i.select(); toast(tr('Copy the selected link')); }
    return;
  }
  if (a === 'rotate' && !await askConfirm(tr('Create a new link?'), tr('Calendars subscribed with the old one stop updating.'), {ok: tr('New link'), danger: true})) return;
  if (a === 'off' && !await askConfirm(tr('Turn the calendar feed off?'), tr('Subscribed calendars stop updating.'), {ok: tr('Turn off'), danger: true})) return;
  try { icalDraw(md, await api('POST', '/api/ical', {action: a})); } catch { /* api() showed it */ }
  if (a === 'rotate') toast(tr('New link created, the old one no longer works'));
}

// 2.122.2 (#2329): "+ Add tab …" as a sheet instead of one long select: a search on top, the sections (areas, smart lists,
// lists, filters, folders, tags, other) folded except one, the lists below their folder, the app's icons (a list its own
// sign); tabs already in the bar are left out; a tap adds the tab and closes the sheet.
function tabAddGroups() {
  const ids = tabIds(), out = [];
  const it = (id, label, x = {}) => ids.includes(id) ? null : {id, label, icon: tabItem(id)?.icon || ic(x.ic || 'plus', 'l'), ...x};
  const grp = (k, n, items) => { items = items.filter(Boolean); if (items.some(x => !x.head)) out.push({k, n: tr(n), items}); };
  const mg = []; mg_tabOpts((id, n) => { mg.push(it(id, n)); return ''; });
  grp('m', N_('Modules'), [...MODS.filter(([m]) => m === 'tasks' || feat(m)).map(([m, , n]) => it('m:' + m, tr(n))), ...mg]);
  grp('s', N_('Smart lists'), SMART_TABS.filter(k => k !== 'assigned' || collab()).map(k => it('s:' + k, tr(SMART[k].name))));
  const ls = S.lists.filter(l => !l.is_inbox && !l.archived), li = (l, d) => it('l:' + l.id, listName(l.name), {d, f: l.folder || ''});
  grp('l', N_('Projects'), [...ls.filter(l => !l.folder).map(l => li(l, 0)), ...folderNames().flatMap(f => {
    const sub = ls.filter(l => l.folder === f).map(l => li(l, fDepth(f))).filter(Boolean);
    return sub.length ? [{head: true, label: fDisp(f), d: fDepth(f) - 1, f}, ...sub] : [];
  })]);
  grp('f', N_('Filters'), S.filters.map(f => it('f:' + f.id, f.name, {ic: 'filter'})));
  grp('folder', N_('Folders'), folderNames().map(f => it('folder:' + f, fDisp(f), {ic: 'folder'})));
  grp('tag', N_('Tags'), Object.keys(counts().tags).sort((a, b) => a.localeCompare(b, 'de')).map(t => it('tag:' + t, '#' + t, {ic: 'tag'})));
  grp('o', N_('Other'), [it('home', tr('Start|home')), teamOn() && it('team', tr('Team chat')), collab() && it('news', tr('News')), feat('agents') && agentsOn() && it('agents', tr('Agents')),
    overviewOn() && it('overview', tr('Project status')), feat('wiki') && it('wiki', tr('Knowledge pages')), it('search', tr('Search')), it('lists', tr('Projects')), it('settings', tr('Settings'))]);
  return out;
}
function tabAddSheet(onPick) {
  const groups = tabAddGroups();
  let open = groups[0]?.k || '';
  const md = modal(`<h3>${tr('Add tab')}</h3><div class="ctsearch">${ic('search', 's')}<input id="ta-q" type="search" placeholder="${esc(tr('Search'))}" aria-label="${esc(tr('Search'))}" autocomplete="off"></div><div class="tapick-l"></div>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('tapick');
  const row = x => x.head ? `<li class="tapick-h" style="--d:${x.d}">${ic('folder', 's')}<span>${esc(x.label)}</span></li>`
    : `<li><button type="button" class="tapick-i" data-tabadd="${esc(x.id)}" style="--d:${x.d || 0}"><span class="tapick-ic" aria-hidden="true">${x.icon}</span><span class="tapick-n">${esc(x.label)}</span></button></li>`;
  const draw = () => {
    const q = ($('#ta-q', md)?.value || '').trim().toLocaleLowerCase();
    const hit = x => !x.head && x.label.toLocaleLowerCase().includes(q);
    const html = groups.map(g => {
      const items = q ? g.items.filter(x => x.head ? g.items.some(y => !y.head && y.f === x.f && hit(y)) : hit(x)) : g.items;  // a folder head stays above its hits
      if (q && !items.some(x => !x.head)) return '';
      const on = !!q || g.k === open, n = items.filter(x => !x.head).length;
      return `<section class="tapick-g ${on ? 'on' : ''}" data-tag="${esc(g.k)}"><button type="button" class="tapick-gh" data-tagrp="${esc(g.k)}" aria-expanded="${on}"><b>${esc(g.n)}</b><span class="muted">${n}</span><span class="spacer"></span>${ic('chev', 's ' + (on ? 'up' : 'down'))}</button>${on ? `<ul role="list">${items.map(row).join('')}</ul>` : ''}</section>`;
    }).join('');
    $('.tapick-l', md).innerHTML = html || `<p class="muted lempty">${tr('Nothing matches.')}</p>`;
  };
  draw();
  setTimeout(() => { if (!matchMedia('(pointer:coarse)').matches) $('#ta-q', md)?.focus(); }, 0);
  md.addEventListener('input', e => { if (e.target.id === 'ta-q') draw(); });
  md.addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    if (b.dataset.tagrp) { open = open === b.dataset.tagrp && !$('#ta-q', md).value.trim() ? '' : b.dataset.tagrp; $('#ta-q', md).value = ''; draw(); $(`[data-tagrp="${b.dataset.tagrp}"]`, md)?.focus(); return; }
    if (b.dataset.tabadd) { md.remove(); onPick(b.dataset.tabadd); }
  });
  return md;
}

// 2.250.0 C (#2994): the settings search. Titles and field names first, the explanation lines after them (at most one per
// section), the same wording once, a few synonyms (the words people search for that the labels do not use).
const SS_SYN = [  // [the words in every language, the label(s) to look for instead | 'absence']
  [['logo', 'signet', 'emblem', 'emblema', 'emblème'], () => [tr('Symbol')]],
  [['mitglieder', 'mitglied', 'members', 'member', 'miembros', 'membres', 'membri', 'leden'], () => [tr('People|admin'), tr('People')]],
  // 2.353.0 E (#2775): the words people type for the integrations (the scan program is under Integrations since #2773)
  [['scanner', 'scannen', 'scan', 'wächter', 'waechter', 'ordner-wächter', 'watcher', 'folder watcher', 'download', 'herunterladen', 'mac', 'macos', 'windows', 'programm', 'program'], () => [tr('Scans from your computer')]],
  [['import', 'importieren', 'einlesen', 'importer', 'importar', 'importeren'], () => [tr('Import')]],
  [['export', 'exportieren', 'exporter', 'exportar', 'exporteren'], () => [tr('Export')]],
  [['token', 'tokens', 'api', 'api-key', 'api key', 'zugangsschlüssel', 'app-passwort'], () => [tr('API tokens'), tr('App passwords')]],
  [['kalender', 'calendar', 'calendrier', 'calendario', 'agenda', 'ical', 'ics', 'caldav', 'kalender-abo'], () => [tr('Calendar subscription'), tr('Calendar apps (CalDAV)'), tr('Calendars')]],
  [['mail', 'e-mail', 'email', 'mails', 'postfach', 'mailbox', 'correo', 'courriel'], () => [tr('Tasks by e-mail'), tr('E-mail for single events')]],
  [['urlaub', 'abwesenheit', 'krank', 'frei', 'vacation', 'absence', 'holiday', 'sick', 'leave', 'vacaciones', 'ausencia', 'congé', 'ferie', 'assenza', 'vakantie', 'afwezig'], 'absence']];
// the text of an element with a blank between its parts (textContent glues "Title" + "explanation" together)
function ss_text(el) {
  if (el.matches('input,textarea')) return (el.getAttribute('placeholder') || el.getAttribute('aria-label') || '').trim();
  const out = [], walk = n => { for (const c of n.childNodes) { if (c.nodeType === 3) out.push(c.nodeValue); else if (c.nodeType === 1 && !/^(SCRIPT|STYLE)$/.test(c.tagName)) { out.push(' '); walk(c); out.push(' '); } } };
  walk(el);
  return out.join('').replace(/\s+/g, ' ').trim();
}
// cut at a word boundary, never in the middle of a word
function ss_cut(t, n) {
  if (t.length <= n) return t;
  const c = t.slice(0, n), i = c.lastIndexOf(' ');
  return (i > n * 0.5 ? c.slice(0, i) : c).replace(/[\s,;:.\-–]+$/, '') + '…';
}
function ss_hits(md, q, shown, SYN) {
  const hits = [], seen = new Set(), said = new Set(), MAX = 14;
  const add = (el, k, extra) => {
    if (hits.length >= MAX) return false;
    if (el && seen.has(el)) return false;
    const t = extra?.t || ss_text(el); if (!t) return false;
    const key = (k || '') + '|' + t.toLowerCase();
    if (said.has(key)) return false;  // the same words in the same tab are one hit
    if (el) seen.add(el); said.add(key); hits.push({el, t, k, ...extra}); return true;
  };
  // synonyms: an exact word beats a word that merely starts with the query ("logo" is not "logout")
  const grp = SS_SYN.filter(([ws]) => ws.includes(q)), pre = SS_SYN.filter(([ws]) => q.length >= 3 && ws.some(w => w.startsWith(q)));
  const targets = [];
  for (const [, to] of (grp.length ? grp : pre)) {
    if (to === 'absence') { if (typeof workloadOn === 'function' && workloadOn() && typeof ab2_sheet === 'function') add(null, '', {act: 'absence', t: tr('Enter an absence')}); }
    else targets.push(...to().map(x => x.toLowerCase()));
  }
  if (!grp.length) for (const [ws, sel] of SYN) if (ws.some(w => w === q || (q.length >= 3 && w.startsWith(q)) || (q.length > 3 && q.includes(w)))) { const el = $(sel, md); if (el) add(el, el.closest('.spane')?.dataset.pane); }
  const heads = p => $$('h4', p);
  const secOf = (el, p) => { let last = null; for (const h of heads(p)) { if (h === el || (h.compareDocumentPosition(el) & 4)) last = h; else break; } return last; };
  const TITLES = 'h4, .row > label, label.chkl, .featgrid label > span, .modrow b, summary, button:not(.iconbtn), th, option', HINTS = '.shint, .modrow small';
  const own = el => el.matches('.featgrid label > span') ? (el.firstChild?.textContent || '') + ' ' + (el.querySelector('small')?.textContent || '') : ss_text(el);
  const okEl = el => shown(el) && !el.closest('.ssres');
  const terms = [q, ...targets];
  const hit = t => terms.some(x => t.toLowerCase().includes(x));
  for (const pass of [TITLES, HINTS]) {
    const perSec = new Set();
    for (const p of $$('.spane', md)) for (const el of $$(pass, p)) {
      if (hits.length >= MAX) break;
      if (!okEl(el) || !hit(own(el))) continue;
      if (pass === HINTS) { const sec = secOf(el, p) || p; if (perSec.has(sec)) continue; perSec.add(sec); }
      add(el.matches('option') ? el.closest('select') : el, p.dataset.pane);
    }
  }
  return hits;
}
// 2.353.0 E (#2775): the settings windows of the areas (they are not in this dialog): the search finds them too. One entry
// per window: src = the functions that draw it (tests/p2353_e_setsearch_guard_test.py: every area settings window has an
// entry here), on = its module is on and the person may open it, open = its area + the window, root = the window once drawn,
// secs = its sections [label, words people type (German + English), the element (else the heading with that label), office pane, gate]
const ss_ofm = k => { const i = typeof OFM_ITEMS !== 'undefined' && OFM_ITEMS.find(x => x.key === k); return !!i && i.on() && ofm_ok(i); };
const ss_ofcFeat = k => typeof ofcFeat !== 'function' || ofcFeat(k);  // office.js loads with the area
const SS_AREA = [
  {src: ['dc_settings', 'dc_sDraw', 'dc_cfSettings', 'dsc_slot'], area: N_('File store|area'), name: N_('Settings of the documents'), words: ['dokumente', 'documents', 'ablage', 'erkennung', 'recognition', 'paperless'],
    on: () => modOn('docs') && typeof dc_settings === 'function', open: async () => { go('docs'); await ss_until(() => $('[data-dc="settings"]')); return dc_settings(); }, root: '.dc-smd',
    secs: [[N_('Sorting automatically'), ['sortieren', 'sorting', 'erkennen', 'recognise', 'archivnummer', 'asn', 'trennblatt']], [N_('Rules'), ['regel', 'rule']],
      [N_('Senders, types and tags'), ['absender', 'sender', 'dokumenttyp', 'schlagwort', 'tags']], [N_('Custom fields'), ['feld', 'felder', 'field', 'fields']],
      [N_('Scans from your computer'), ['scanner', 'scannen', 'scan', 'wächter', 'watcher', 'download', 'mac', 'windows', 'programm', 'program', 'mail', 'e-mail', 'eingang']]]},
  {src: ['ofcSettingsHtml', 'agbSettingsHtml', 'bp_settingsHtml', 'dun_settingsHtml', 'tpSettingsHtml', 'pep_settingsHtml', 'dx_settingsHtml', 'dv_settingsHtml', 'brl_settingsHtml', 'bnr_settingsHtml',
    'ocf_settingsHtml', 'oa_settingsHtml', 'rk_settingsHtml', 'bw_settingsHtml', 'cfs_settingsHtml'], area: N_('Office|area'), name: N_('Settings'), words: ['büro', 'office', 'firma', 'company'],
    on: () => modOn('office') && ss_ofm('settings'), open: () => go('office/settings'), root: '#ofc-set',
    secs: [[N_('Company'), ['firma', 'adresse', 'address', 'logo', 'bank', 'iban'], '', 'company'], [N_('Terms and conditions (PDF)'), ['agb', 'terms'], '#agb-box', 'company'], [N_('Letterhead'), ['briefpapier', 'briefkopf', 'letterhead'], '#bp-h', 'company'],
      [N_('Master data file'), ['stammdaten', 'master data'], '', 'company'],
      [N_('Documents & numbers'), ['nummer', 'nummern', 'number', 'angebot', 'quotation', 'währung', 'currency'], '', 'docs'], [N_('Invoices'), ['rechnung', 'invoice'], '', 'docs'],
      [N_('Suggest payment reminders for overdue invoices'), ['mahnung', 'zahlungserinnerung', 'reminder', 'dunning', 'girocode'], '#os-dun-on', 'docs'],
      [N_('Invoice from a quotation with parts'), ['teile', 'parts'], '#os-parts-inv', 'docs'],
      [N_('E-invoices over the Peppol network'), ['peppol', 'e-rechnung', 'einvoice', 'xrechnung', 'zugferd'], '#pep-set', 'docs', () => ss_ofcFeat('docs.einvoice')],
      [N_('Calculation rules'), ['kalkulation', 'calculation', 'steuer', 'tax'], '', 'docs'], [N_('Default texts'), ['texte', 'texts', 'einleitung', 'schluss'], '', 'docs'],
      [N_('DATEV export (booking batch)'), ['datev', 'export', 'steuerberatung', 'tax advisor'], '.dxset', 'data', () => ss_ofcFeat('books.datev')],
      [N_('Bank rules'), ['bank', 'regel', 'rule', 'konto'], '#brl-h', 'data'], [N_('Bank bookings without a receipt'), ['beleg', 'receipt', 'bank'], '', 'data'],
      [N_('Country pack'), ['land', 'country', 'paket', 'pack'], '', 'packs'], [N_('Travel expenses'), ['reise', 'reisekosten', 'travel'], '#rkp-h', 'packs'],
      [N_('Entertainment receipts'), ['bewirtung', 'entertainment', 'meals'], '#bwc-h', 'packs'], [N_('Cash flow'), ['liquidität', 'cashflow', 'cash flow'], '#cfs-h', 'packs'],
      [N_('Functions'), ['funktion', 'function', 'module'], '', 'functions'], [N_('Agents'), ['agent', 'agenten', 'ki', 'ai'], '', 'access']]},
  {src: ['bkSettingsHtml'], area: N_('Office|area'), name: N_('Bookkeeping'), words: ['buchhaltung', 'bookkeeping', 'euer', 'ustva'],
    on: () => modOn('office') && ss_ofm('books'), open: () => go('office/books'), root: '#bk-sh', secs: [[N_('Settings'), ['einstellungen', 'settings', 'buchhaltung', 'bookkeeping'], '#bk-sh']]}];
// the hits of the area windows: a section beats its window, a word must start like the query, a label may hold it anywhere
function ss_areaHits(q, max = 6) {
  const out = [], lo = s => String(s || '').toLowerCase();
  const wOk = ws => ws.some(w => w === q || (q.length >= 3 && w.startsWith(q)));
  const lOk = l => q.length >= 3 ? lo(tr(l)).includes(q) || lo(l).includes(q) : lo(tr(l)).startsWith(q);
  for (const w of SS_AREA) {
    if (out.length >= max) break;
    try { if (!w.on()) continue; } catch { continue; }
    const pre = `${tr(w.area)} › ${tr(w.name)}`, secs = w.secs.filter(([l, ws, , , gate]) => (!gate || gate()) && (lOk(l) || wOk(ws)));
    for (const s of secs.slice(0, max - out.length)) out.push({el: null, k: '', act: 'area', w, s, pre, t: tr(s[0])});
    if (!secs.length && (lOk(w.name) || lOk(w.area) || wOk(w.words))) out.push({el: null, k: '', act: 'area', w, s: null, pre: tr(w.area), t: tr(w.name)});
  }
  return out;
}
// wait for a real state (the window drawn), never a fixed time; null after `ms`
function ss_until(fn, ms = 6000) {
  return new Promise(res => { const t0 = Date.now(), tick = () => { const v = fn(); if (v || Date.now() - t0 > ms) res(v || null); else setTimeout(tick, 60); }; tick(); });
}
// open the area + its window, then the section: unfold it, scroll to it and the soft ring of the settings search; a window
// that draws itself again (data arriving, the letterhead's own redraw) gets the ring again
async function ss_areaOpen(h) {
  const {w, s} = h;
  await w.open();
  if (!await ss_until(() => $(w.root))) return;
  if (s?.[3] && typeof ost_show === 'function') ost_show(s[3], true);  // the office pane (kept, so a redraw shows it too)
  const box = () => { const rt = $(w.root); return rt && (rt.closest('.modal, .card, .dash') || rt.parentElement || rt); };
  const head = (b, l) => $$('h3, h4, h5, summary, legend, .row > label', b).find(x => !x.closest('[hidden]') && ss_text(x).startsWith(tr(l)));
  const mark = () => {
    const b = box(), el = b && (s ? (s[2] ? $(s[2], b) : head(b, s[0])) : $(w.root)); if (!el) return null;
    for (let det = el.closest('details'); det; det = det.parentElement?.closest('details')) det.open = true;
    const r = el.closest('.row, details, h3, h4') || el; r.classList.add('sflash'); return r;
  };
  let r = await ss_until(mark, 3000); if (!r) return;
  r.scrollIntoView?.({block: 'center'});
  const mo = new MutationObserver(() => { if (!r.isConnected || !r.classList.contains('sflash')) { const n = mark(); if (n && n !== r) { r = n; r.scrollIntoView?.({block: 'center'}); } } });  // (a morphing redraw keeps the element, drops the class)
  mo.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['class']});
  setTimeout(() => { mo.disconnect(); r.classList.remove('sflash'); }, 1600);
}
