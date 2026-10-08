/* Kalmido web client: Settings: notifications, Web Push, autosave settings, personal agents, import, Paperless.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// ---- Web Push (Settings > Notifications > This device). Opt-in per device: permission, subscribe with the
// server's VAPID key, subscription stored for the current user (with a label). The service worker shows the
// pushes (sw.js). iOS / iPadOS: only in the app added to the Home Screen (16.4+). LS wpUser = the account this
// device subscribed for (a daily check-in keeps the server copy current, logout removes it).
const wpSupported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
const isIOS = () => /iPad|iPhone|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const b64uBytes = s => { const b = atob((s + '='.repeat((4 - s.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(b, c => c.charCodeAt(0)); };
function deviceLabel() {
  const u = navigator.userAgent;
  const b = /SamsungBrowser/.test(u) ? 'Samsung Internet' : /Edg(A|iOS)?\//.test(u) ? 'Edge' : /OPR\/|Opera/.test(u) ? 'Opera' : /Firefox\/|FxiOS/.test(u) ? 'Firefox'
    : /Chrome\/|CriOS/.test(u) ? 'Chrome' : /Safari\//.test(u) ? 'Safari' : tr('Browser');
  const o = /Android/.test(u) ? 'Android' : /iPad/.test(u) || (/Macintosh/.test(u) && navigator.maxTouchPoints > 1) ? 'iPad' : /iPhone|iPod/.test(u) ? 'iPhone'
    : /Windows/.test(u) ? 'Windows' : /CrOS/.test(u) ? 'ChromeOS' : /Mac OS X|Macintosh/.test(u) ? 'macOS' : /Linux/.test(u) ? 'Linux' : '';
  return o ? tr('{0} on {1}', b, o) : b;
}
async function swReg(wait = 8000) {
  if (!('serviceWorker' in navigator)) return null;
  const reg = await navigator.serviceWorker.getRegistration().catch(() => null);
  if (reg?.active) return reg;
  return Promise.race([navigator.serviceWorker.ready, new Promise(r => setTimeout(() => r(null), wait))]);
}
async function wpSub() {
  if (!wpSupported()) return null;
  const reg = await swReg(1500);
  return reg ? reg.pushManager.getSubscription().catch(() => null) : null;
}
const sameKey = (sub, key) => { const a = sub?.options?.applicationServerKey; if (!a) return true; const x = new Uint8Array(a), y = b64uBytes(key); return x.length === y.length && x.every((v, i) => v === y[i]); };
async function wpEnable() {
  if (!wpSupported()) throw new Error(tr('This browser does not support Web Push'));
  const perm = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
  if (perm !== 'granted') throw new Error(tr('Notifications are blocked for this site. Allow them in the browser or system settings.'));
  const {enabled, key} = await api('GET', '/api/push/vapid');
  if (!enabled || !key) throw new Error(tr('Web Push is turned off on this server'));
  const reg = await swReg();
  if (!reg) throw new Error(tr('The service worker is not ready yet, try again in a moment'));
  let sub = await reg.pushManager.getSubscription();
  if (sub && !sameKey(sub, key)) { await sub.unsubscribe().catch(() => {}); sub = null; }
  if (!sub) sub = await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64uBytes(key)});
  await api('POST', '/api/push/subs', {...sub.toJSON(), label: deviceLabel()});
  LS.set('wpUser', S.me?.id ?? 0); LS.set('wpEp', sub.endpoint); LS.set('wpSync', Date.now());
  S.webpush.devices = (S.webpush.devices || 0) + 1;
  return true;
}
async function wpDisable() {
  const sub = await wpSub();
  LS.del('wpUser'); LS.del('wpEp');
  if (!sub) return true;
  await api('POST', '/api/push/unsubscribe', {endpoint: sub.endpoint}).catch(() => {});
  await sub.unsubscribe().catch(() => {});
  return true;
}
// once a day: tell the server this device's current subscription (the push service may have renewed it
// without a pushsubscriptionchange); a device removed meanwhile is not re-added (sync: true).
async function wpSync() {
  if (!wpSupported() || !S.me || Notification.permission !== 'granted' || LS.get('wpUser', null) !== S.me.id) return;
  const sub = await wpSub();
  if (!sub) { LS.del('wpUser'); return; }
  if (sub.endpoint === LS.get('wpEp', '') && Date.now() - LS.get('wpSync', 0) < 86400e3) return;
  try {
    const j = await rawFetch('POST', '/api/push/subs', {...sub.toJSON(), sync: true, replaces: LS.get('wpEp', '') || undefined});
    if (j.known === false) LS.del('wpUser'); else { LS.set('wpEp', sub.endpoint); LS.set('wpSync', Date.now()); }
  } catch { /* offline: next start */ }
}
// 2.0.5 (#311): a task handled here (opened, completed, its News read) closes its notification (tag t-<id>) on this device
// right away; the server closes it on the user's other devices. X-Kalmido-Device tells the server which device this is.
function wpDevHeader(url) { return /\/(complete|seen)$|^\/api\/(news\/read|push\/handled|team\/rooms\/\d+\/read)$/.test(url) && S.me && LS.get('wpUser', null) === S.me.id ? LS.get('wpEp', '') : ''; }
async function wpCloseLocal(ids) {
  const tags = new Set(ids.filter(Boolean).map(i => 't-' + i)); if (!tags.size || !('serviceWorker' in navigator)) return;
  try { const reg = await navigator.serviceWorker.getRegistration(); for (const n of reg ? await reg.getNotifications() : []) if (tags.has(n.tag)) n.close(); } catch { /* not supported */ }
}
// 2.19.0 (#668): Android counts the notifications still in the shade on the app icon. When the app is seen (start, back in
// front, News read, a chat opened) every notification that needs nothing any more is closed: tasks that are done / gone,
// or open but neither unread in News nor due by today; chats without unread messages; everything else (agents, proposals,
// lists, digest, review, habits) was seen with the app. Kept: unread News, due reminders, unread chats.
async function wpSweep(only = null, all = false) {
  if (!('serviceWorker' in navigator) || !S.me) return 0;
  let n = 0;
  try {
    const reg = await navigator.serviceWorker.getRegistration(); if (!reg) return 0;
    const unreadT = new Set((S.nf.items || []).filter(x => !x.read).map(x => x.task_id));
    for (const x of await reg.getNotifications()) {
      const tag = x.tag || '', m = /^t-(\d+)$/.exec(tag), r = /^team-(\d+)$/.exec(tag);
      if (only && !only(tag)) continue;
      let keep = false;
      if (all) keep = false;
      else if (m) { const t = S.tasks.get(+m[1]); keep = !!t && t.status === 0 && !t.deleted_at && (unreadT.has(t.id) || (S.nf.items === null && (S.news?.unread || 0) > 0) || (!!t.due && t.due <= today())); }
      else if (r) keep = ((S.tc.rooms || []).find(z => z.id === +r[1])?.unread || 0) > 0 || (S.tc.rooms == null && (S.team?.unread || 0) > 0);
      if (!keep) { x.close(); n++; }
    }
  } catch { /* not supported */ }
  return n;
}
// the number on the app icon: unread News + unread chat messages (Badging API where there is one; 0 clears it)
let badgeN = -1;
function badgeSync() {
  const n = (collab() ? S.news?.unread || 0 : 0) + (teamOn() ? S.team?.unread || 0 : 0);
  if (n === badgeN || !navigator.setAppBadge) return;
  badgeN = n;
  (n > 0 ? navigator.setAppBadge(n) : navigator.clearAppBadge()).catch(() => {});
}
const WP_OPENED = new Map();  // task id -> time the server was told (once a minute at most)
function wpOpened(id) {
  if (!(id > 0)) return;
  wpCloseLocal([id]);
  if (!S.webpush?.enabled || !S.webpush.devices || Date.now() - (WP_OPENED.get(id) || 0) < 60e3) return;
  WP_OPENED.set(id, Date.now());
  rawFetch('POST', '/api/push/handled', {tasks: [id]}).catch(() => {});
}
// messages from the service worker: a notification was clicked (open its link here) / "Done" completed a task
function swMessage(e) {
  const d = e.data || {};
  if (d.type === 'open' && typeof d.url === 'string') {
    const u = new URL(d.url, location.origin);
    if (u.origin !== location.origin) return;
    if (location.hash !== u.hash) location.hash = u.hash; else route();
  }
  if (d.type === 'refresh') load().then(render).catch(() => {});
}
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
const SET_SECS = [['account', 'user', N_('Account')], ['general', 'sliders', N_('General')], ['look', 'palette', N_('Appearance')], ['modules', 'grid', N_('Modules')],
  ['notify', 'bell', N_('Notifications')], ['integr', 'link', N_('Integrations')], ['ai', 'bot', N_('Agents')], ['data', 'download', N_('Data')], ['users', 'users', N_('Administration')], ['help', 'help', N_('Help')]];
// 2.25.0 (UX-17): what each area holds, shown in the overview a phone opens with
const SET_DESC = {account: N_('Name, password, sign-in, storage'), general: N_('Language, Today, dates and reminders'), look: N_('Theme, font size, tab bar and sidebar'),
  modules: N_('What Kalmido shows'), notify: N_('Push, News and quiet hours'), integr: N_('Calendar on the phone, sharing, e-mail'), ai: N_('Agents and what they do'),
  data: N_('Import, export, templates, backups'), users: N_('People, sign-in, server'), help: N_('How things work, about Kalmido')};
// ---- UX1 (U03, owner decision 2): settings save themselves. Every control applies at once, "Saved · Undo" shows in the
// dialog header and each change is one step in the undo history ("Changed setting: …"). Text, number and time fields save
// on blur or Enter (and after a short pause while typing); closing the dialog saves whatever is still pending.
const SETS = {  // control id -> [setting key, label, kind]
  's-celebrate': ['celebrate', N_('Celebrate completions'), 'chk'], 's-tinbox': ['today_inbox', N_('Show the inbox in Today'), 'chk'],  // 2.22.0 (#681)
  's-hideblk': ['hide_blocked_today', N_('Hide tasks that are still blocked by another task'), 'chk'], 's-progsub': ['progress_subtasks', N_('Count subtasks in the progress of a list'), 'chk'],
  's-pushch': ['push_channel', N_('Channel'), 'sel'], 's-pushprio': ['push_priority', N_('How urgent'), 'sel'],
  's-allday': ['allday_time', N_('All-day reminder at'), 'time'], 's-defrem': ['default_reminder', N_('Default reminder'), 'sel'], 's-digest': ['digest_time', N_('Daily digest at'), 'time'],
  's-pf': ['pomo_focus', N_('Focus session'), 'pos'], 's-ps': ['pomo_short', N_('Short break'), 'pos'], 's-pl': ['pomo_long', N_('Long break'), 'pos'], 's-pe': ['pomo_long_every', N_('Long break after'), 'pos'],
  's-trnd': ['time_rounding', N_('Rounding'), 'sel'], 's-tcur': ['time_currency', N_('Currency'), 'text'], 's-ttarget': ['time_target', N_('Daily target'), 'num'],
  's-trem': ['time_remind_h', N_('Reminder after'), 'num'], 's-tstop': ['time_autostop_h', N_('Stop automatically after'), 'num'], 's-tfocus': ['time_focus', N_('Focus sessions'), 'chk'],
  's-icalscope': ['ical_scope', N_('Calendar subscription'), 'sel'], 's-icalalarm': ['ical_alarms', N_('as calendar alarms'), 'chk'],
  's-plkeep': ['paperless_keep', N_('Also keep the attachment in Kalmido'), 'chk'], 's-caltoday': ['cal_today', N_('Events on Today'), 'chk'],
  's-dateok': ['date_confirm', N_('Confirm changes of the date with OK'), 'chk'],  // 2.6.1 (#401)
  's-qfrom': ['quiet_from', N_('Quiet from'), 'time'], 's-qto': ['quiet_to', N_('Quiet until'), 'time'],  // 2.7.0 (#413)
  's-wfrom': ['work_start', N_('Working hours from'), 'time'], 's-wto': ['work_end', N_('Working hours until'), 'time'],  // 2.10.0 (#440)
  's-review': ['review_time', N_('Daily review at'), 'time'],
};
const SET_RENDER = ['sidebar', 'features', 'nav_order', 'show_done_views', 'hide_blocked_today', 'today_inbox', 'progress_subtasks', 'cal_today', 'time_target', 'lang', 'agents_hidden'];
function setVal(el, kind) {  // the value a control stands for; undefined = not valid (nothing is saved)
  const v = el.value;
  if (kind === 'chk') return el.checked ? '1' : '0';
  if (kind === 'pos') return /^\d+$/.test(String(v).trim()) && +v >= 1 ? String(Math.min(999, +v)) : undefined;
  if (kind === 'num') { const n = +String(v).replace(',', '.'); return String(v).trim() === '' || !Number.isFinite(n) ? undefined : String(Math.max(0, n)); }
  if (kind === 'time') return v || '';
  if (kind === 'text') return v.trim();
  return v;
}
// apply + remember a change of server settings; label = what the history shows
async function setApply(patch, label, o = {}) {
  const before = {};
  for (const k in patch) before[k] = S.settings[k] ?? '';
  if (Object.keys(patch).every(k => String(before[k]) === String(patch[k]))) return null;
  try { await api('PATCH', '/api/settings', patch); } catch { settingsSync(); return false; }
  Object.assign(S.settings, patch);
  await setAfter(patch);
  const e = histAdd({label: tr('Changed setting: {0}', label), sett: true, post: settingsSync,
    undo: () => setStep(before, patch, label), redo: () => setStep(patch, before, label)});
  if (!o.quiet) setSaved(e);
  return e;
}
async function setStep(to, from, label) {  // one way of a settings step; a value changed elsewhere meanwhile stays
  const body = {}, skip = [];
  for (const k in to) { if (String(S.settings[k] ?? '') !== String(from[k] ?? '')) skip.push(label); else body[k] = to[k]; }
  if (!Object.keys(body).length) return {skipped: skip, none: true};
  await api('PATCH', '/api/settings', body);
  Object.assign(S.settings, body);
  await setAfter(body);
  return {skipped: skip};
}
async function setAfter(patch) {
  if ('lang' in patch) { await i18nLoad(patch.lang); LS.set('lang', patch.lang); document.documentElement.lang = patch.lang; }
  if ('features' in patch || 'nav_order' in patch) { try { await load(); } catch { /* offline: the local copy is right */ } await route(); return; }  // route: a view whose module went off
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
    if (kind === 'chk') el.checked = k === 'celebrate' || k === 'ical_alarms' || k === 'cal_today' || k === 'time_focus' ? s[k] !== '0' : s[k] === '1';
    else { el.value = s[k] ?? ''; if (el.dataset.dp) dpSync(el); }
  }
  for (const el of $$('[data-feat]', md)) el.checked = feat(el.dataset.feat);
  for (const el of $$('[data-agvis]', md)) el.checked = !agentHidden().has(+el.dataset.agvis);
  $$('[data-modrow]', md).forEach(r => r.classList.toggle('off', !feat(r.dataset.modrow)));
  modCountsSync(md);  // 2.25.0 (UX-19)
  const nm = $('#a-name', md); if (nm && nm !== document.activeElement && S.me) nm.value = S.me.display_name;
  $$('#s-lang [data-lang-set]', md).forEach(b => b.classList.toggle('on', b.dataset.langSet === (s.lang || 'en')));
  ntfyShow(md);
  const lk = $('#s-lookin', md); if (lk) lk.innerHTML = lookHtml();
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
const MOD_GROUPS = [[N_('Views'), ['cal', 'timeline', 'kanban', 'matrix']], [N_('Calendar and people'), ['events', 'contacts']], [N_('For you'), ['habits', 'pomo', 'stats', 'comments']],
  [N_('Projects and team'), ['collab', 'time', 'progress', 'deps', 'fields', 'agents', 'clients', 'workload', 'forms']], [N_('At home'), ['family', 'contracts', 'home', 'care', 'health', 'review', 'travel', 'reading']], [N_('Connections'), ['paperless']]];
const MOD_DESC = {cal: N_('Month, week and day view of your tasks'), timeline: N_('Tasks with start and end as bars over time'), kanban: N_('Lists as boards with columns'),
  matrix: N_('Urgent and important in four quadrants'), habits: N_('Daily and weekly habits with streaks'), pomo: N_('Pomodoro timer and stopwatch'),
  stats: N_('Completions, on-time rate, focus time and streaks'), collab: N_('Share lists, assign tasks, @mentions, activity and News'),
  comments: N_('Timestamped notes on your tasks; in shared lists with collaboration also @mentions and News'),
  time: N_('Timers and manual time entries on tasks, reports and CSV export'), progress: N_('Progress per list and the project status (“Where is it stuck?”)'),
  deps: N_('Tasks blocked by other tasks, with arrows in the timeline (Gantt)'), fields: N_('Own fields per list, such as budget, client or phase'),
  paperless: N_('Link documents from Paperless-ngx to tasks'),
  events: N_('Appointments in your own calendars next to the tasks, shared calendars, invitations, synced with the phone’s calendar'),
  contacts: N_('Your address books: contacts linked to tasks and events, birthdays, synced with the phone’s contacts'),
  family: N_('Birthdays, household chores taking turns, shopping lists with shop areas, a meal plan, deadlines, packing lists and accounts for children'),
  // 2.22.0 (#663): Home & life
  contracts: N_('Contracts and subscriptions with their cost, notice period and a reminder before the last day to cancel'),
  home: N_('Devices with their warranty and receipt, and upkeep that comes back: heating, smoke detectors, tyres'),
  care: N_('Stay in touch with the people who matter: how often, the last time, a nudge when it has been too long (needs Contacts)'),
  health: N_('Appointments, check-ups, vaccinations and medication reminders in a private list, never visible to agents'),
  review: N_('Your day and week in review (done, still open, coming up) with a private journal'),
  travel: N_('Trips as lists with dates, bookings, things to do before you leave and a packing list'),
  reading: N_('A “Read later” list, filled from Karakeep if you like (bookmarks become tasks)')};
// 2.25.0 (UX-20): Integrations start with what people want to do, in plain words; a tap jumps to the part that does it
// (the technical parts below stay for those who need them)
function integrCardsHtml() {
  const C = [['cal', N_('Calendar on your phone'), N_('Your tasks with a date in the phone’s calendar app'), S.caldav?.enabled && S.me ? '#s-dav-h' : '#s-ical-h'],
    ['phone', N_('Share from your phone'), N_('Text, links and pictures from other apps into Kalmido'), '#s-share-h'],
    ['send', N_('Send by e-mail'), N_('Forward an e-mail and it becomes a task'), '#s-mail-h']];
  return `<div class="icards">${C.map(([i, n, d, to]) => `<button type="button" class="icard" data-jump="${to}">${ic(i, 's')}<span><b>${tr(n)}</b><small>${tr(d)}</small></span>${ic('chev', 's fcar')}</button>`).join('')}</div>`;
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
      ${hint(tr('Rounding applies to the report, the CSV export and the timesheet; the tracked times stay exact. Hourly rate: in the list dialog (owner).'))}
      <div class="row"><label for="s-tcur">${tr('Currency')}</label><input id="s-tcur" value="${esc(s.time_currency ?? '€')}" maxlength="8" class="numin"></div>
      <div class="row"><label for="s-ttarget">${tr('Daily target')}</label><input type="number" id="s-ttarget" value="${esc(s.time_target || '0')}" min="0" max="24" step="0.25" class="numin"><span class="muted">${tr('hours, 0 = none')}</span></div>
      <div class="row"><label for="s-trem">${tr('Reminder after')}</label><input type="number" id="s-trem" value="${esc(s.time_remind_h ?? '4')}" min="0" max="48" step="0.5" class="numin"><span class="muted">${tr('hours, push “still running?”, 0 = off')}</span></div>
      <div class="row"><label for="s-tstop">${tr('Stop automatically after')}</label><input type="number" id="s-tstop" value="${esc(s.time_autostop_h ?? '12')}" min="0" max="72" step="0.5" class="numin"><span class="muted">${tr('hours, end = start + value, 0 = off')}</span></div>
      <div class="row"><label>${tr('Focus sessions')}</label><label class="chkl"><input type="checkbox" id="s-tfocus" ${s.time_focus !== '0' ? 'checked' : ''}> ${tr('count as time entries (not while a timer runs)')}</label></div></details>` : '';
  const row = k => modRowHtml(k, opt);
  return `<h4 id="s-purpose-h">${tr('What do you use Kalmido for?')}</h4>${purposeCards(S.settings.purpose || '')}
    ${hint(tr('Switch on only what you need; everything else disappears from the menus. Nothing is deleted: switched back on, everything is there again.'))}
    <div class="modtot muted" id="s-modtot">${esc(modCount())}</div>
    ${MOD_GROUPS.map(([g, ks], gi) => { const r = modGroupKeys(ks); return r.length ? `<details class="modgrp" data-modgrp="${gi}"><summary><span class="mgn">${tr(g)}</span><span class="mgc muted">${esc(modGroupCount(r))}</span>${ic('chev', 's fcar')}</summary><div class="modlist">${r.map(row).join('')}</div></details>` : ''; }).join('')}`;
}
// 2.25.0 (UX-19): the module groups start folded and say how many are on ("3 of 4 on"); the total on top counts the same
// switches (every module shown here), and the setup counts against it too
const modGroupKeys = ks => ks.filter(k => k !== 'paperless' || S.paperless?.enabled || feat('paperless'));
const modGroupCount = r => tr('{0} of {1} on', r.filter(k => feat(k)).length, r.length);
const modAll = () => MOD_GROUPS.flatMap(([, ks]) => modGroupKeys(ks));
const modCount = () => { const a = modAll(); return tr('{0} of {1} modules on', a.filter(k => feat(k)).length, a.length); };
function modCountsSync(md) {
  const t = $('#s-modtot', md); if (t) t.textContent = modCount();
  for (const d of $$('[data-modgrp]', md)) { const r = modGroupKeys(MOD_GROUPS[+d.dataset.modgrp][1]), c = $('.mgc', d); if (c) c.textContent = modGroupCount(r); }
}
// one module switch (Settings > Modules; 2.6.0 (K09): the agents switch only there, Settings > Agents links to it)
function modRowHtml(k, opt = () => '') {
  const adm = !!S.me?.is_admin;
  const n = FEATS.find(x => x[0] === k)?.[1] || k, srv = k === 'collab' ? S.collabAll !== false : k === 'time' ? S.timeAll !== false : true;
  const all = adm && (k === 'collab' || k === 'time') ? `<label class="mall" title="${esc(k === 'collab' ? tr('Off: nobody can share lists, assign tasks, comment, or get News and collaboration notifications; shared lists are then only visible to their owner.') : tr('Off: nobody sees timers, time entries or reports; running timers are stopped at that moment, focus sessions no longer become time entries.'))}"><span class="swc"><input type="checkbox" id="${k === 'collab' ? 's-collaball' : 's-timeall'}" ${srv ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${tr('for everyone')}</span></label>` : '';
  return `<div class="modrow ${feat(k) ? '' : 'off'}" data-modrow="${k}"><label class="mmain"><span class="swc"><input type="checkbox" data-feat="${k}" ${feat(k) ? 'checked' : ''} ${srv ? '' : 'disabled'}><span class="swt" aria-hidden="true"></span></span><span><b>${tr(n)}</b><small class="muted">${tr(MOD_DESC[k] || FEAT_DESC[k] || '')}</small>${srv ? '' : `<small class="muted cnote" id="${k === 'collab' ? 's-collabnote' : 's-timenote'}">${tr('Turned off on this server, for everyone. Your own setting applies again once an admin turns it back on.')}</small>`}</span></label>${all}${opt(k)}</div>`;
}
// 2.0.5 (#313): Settings > Agents bundles the agents: what they are, the switch, how they get lists, their status;
// admins also manage them here (was Settings > Administration > Agents; settingsModal('agents') still lands here).
// 2.5.1 (#393): four sub-tabs instead of one long page: Agents (cards, Add agent + Setup guide), Lists (sharing + tidy table),
// Usage (one summary card per agent, the charts behind "Details"), Log (admins). The last one is remembered per device;
// settingsModal('agents' / 'usage' / 'activity') opens the matching one. Each sub-tab loads its data only when shown.
// 2.7.0 (#405 S2): the Agents page only with the module on, or for an admin while agents exist (they manage them there)
const aiPaneOn = () => !!S.me && (feat('agents') || (!!S.me.is_admin && (S.agents || []).length > 0));
const AI_SUBS = [['agents', 'bot', N_('Status|agents')], ['lists', 'list', N_('Lists')], ['usage', 'chart', N_('Usage')], ['log', 'clock', N_('Log')], ['setup', 'help', N_('Set up|agents')]];  // 2.7.2 (#420): Set up
const aiSubs = () => AI_SUBS.filter(([k]) => k === 'log' ? !!S.me?.is_admin : k === 'usage' ? !!S.me?.is_admin || (S.agents || []).length > 0 : true);
function aiSubCur(want) { const ks = aiSubs().map(x => x[0]), k = want || LS.get('aiSub', 'agents'); return ks.includes(k) ? k : 'agents'; }
function aiHtml(hint, want) {
  const adm = !!S.me?.is_admin, ags = S.agents || [], cur = aiSubCur(want);
  const mine = S.lists.some(l => !l.archived && !l.is_inbox && canManage(l));
  const pane = (k, body) => `<div class="aisp" data-aisp="${k}" id="aisp-${k}" role="tabpanel" aria-labelledby="ais-${k}" ${k === cur ? '' : 'hidden'}>${body}</div>`;
  const subs = aiSubs();
  return `<div class="seg aisub" role="tablist" aria-label="${esc(tr('Agents'))}">${subs.map(([k, i, n]) => `<button type="button" role="tab" id="ais-${k}" data-aisub="${k}" aria-controls="aisp-${k}" aria-selected="${k === cur}" class="${k === cur ? 'on' : ''}">${ic(i, 's')}<span>${tr(n)}</span></button>`).join('')}</div>
    ${pane('agents', `<details class="shelp sdet aiexp" ${ags.length ? '' : 'open'}><summary>${tr('Agents are AI team members: they work only through the API and see only the lists shared with them.')}</summary>
      <p>${tr('An agent is a team member for an AI assistant or a bot (Claude Code, Codex, n8n, a local model …): it works only through the API, is never an admin, gets no Paperless access and sees only the lists shared with it. Kalmido tells it about mentions, assignments, chat messages and reactions by webhook or through an event queue it polls; Kalmido itself never starts an AI.')} <a href="${API_DOCS.replace('API.md', 'AGENTS.md')}" target="_blank" rel="noopener noreferrer">${tr('How to connect an agent')}</a></p></details>
    ${feat('agents') ? '' : `<div class="shint aimodoff">${ic('grid', 's')} <span>${tr('The Agents module (the tab with their status, jobs to approve and the chat) is switched off for you.')}</span> <button class="btn sm" data-m="go-modules">${tr('Open Modules')}</button></div>`}
    ${collab() ? '' : hint(tr('Agents work together with you in shared lists: switch on Collaboration (Settings > Modules) as well.'))}
    <div class="members aglist" id="${adm ? 's-ags' : 's-myags'}"><div class="muted mhint">${tr('Loading…')}</div></div>
    <div class="row aibtns">${adm ? `<button class="btn sm" data-ag="new" aria-haspopup="menu">${ic('plus', 's')} ${tr('Add agent…')}</button>` : `<button class="btn sm" data-aigo="setup">${ic('plus', 's')} ${tr('Personal agent…')}</button>`}<button class="btn sm" data-m="ag-guide" title="${esc(tr('Set up an agent step by step, or let Claude Code do it'))}">${ic('help', 's')} ${tr('Setup guide')}</button></div>
    ${agDotsHtml(hint)}`)}
    ${pane('lists', `<h4 id="s-ai-lists-h">${ags.length > 1 ? tr('Which lists they see') : tr('Which lists it sees')}</h4>
    ${hint(tr('An agent sees exactly the lists shared with it, nothing else. Share or stop sharing below or in the list’s Share dialog; taking a list out ends the access at once.'))}
    ${mine && collab() ? `<div class="aishare" id="s-ai-share"></div><div class="aitblctl" id="s-ai-tblctl"></div>
    <div class="aitbl" id="s-ai-tbl" role="table" aria-labelledby="s-ai-lists-h"><div class="muted mhint">${tr('Loading…')}</div></div>` : `<div class="muted mhint">${tr('You do not manage any list yet.')}</div>`}`)}
    ${subs.some(x => x[0] === 'usage') ? pane('usage', `${hint(adm ? tr('What the agents report about their model usage: tokens and, if they send it, the cost. You see every agent; limits are set per agent (Edit).') : tr('What the agents in your lists report about their model usage, counted in the lists you see.'))}
    <div class="aiu" id="s-aiu"></div>`) : ''}
    ${adm ? pane('log', audHtml()) : ''}
    ${pane('setup', agSetupPaneHtml(hint))}`;
}
// ---- 2.7.2 (#420) Settings > Agents > Set up: my personal agents (when an admin allows them), the admins' switch for
// that, and the two guides (a team agent on a server / a personal agent on your own computer), each for Linux, macOS and
// Windows. The texts of the guides: AG_GUIDES (the same steps as docs/AGENTS.md).
function agSetupPaneHtml(hint) {
  const adm = !!S.me?.is_admin, g = LS.get('agGuide', adm ? 'team' : 'own'), os = LS.get('agOs', /Win/.test(navigator.platform || '') ? 'win' : /Mac/.test(navigator.platform || '') ? 'mac' : 'linux');
  const seg = (k, cur, opts) => `<div class="seg agsseg" role="tablist" data-agseg="${k}">${opts.map(([v, n, i]) => `<button type="button" role="tab" data-agsv="${v}" aria-selected="${v === cur}" class="${v === cur ? 'on' : ''}">${i ? ic(i, 's') : ''}<span>${tr(n)}</span></button>`).join('')}</div>`;
  return `<h4 id="s-myown-h">${tr('Your personal agents')}</h4>
    ${hint(tr('A personal agent is yours: it sees only the lists you share with it, only you can chat with it, and it is never an admin. You run it on your own computer.'))}
    <div class="members aglist" id="s-myown" aria-labelledby="s-myown-h"><div class="muted mhint">${tr('Loading…')}</div></div>
    ${adm ? `<h4 id="s-uag-h">${tr('Personal agents for everyone')}</h4>
    <div class="row"><label class="chkl swl"><span class="swc"><input type="checkbox" id="s-uag"><span class="swt" aria-hidden="true"></span></span><span>${tr('Users may create their own agents')}</span></label></div>
    <div class="row"><label for="s-uagmax">${tr('Per person at most')}</label><input id="s-uagmax" type="number" inputmode="numeric" min="1" max="20" value="2" class="numin"></div>
    ${hint(tr('Off by default. You see every agent under Status and can pause or delete it; usage limits apply to them like to every agent.'))}
    <h4 id="s-sclim-h">${tr('Permission limit')}</h4>
    ${hint(tr('What agents and API tokens may get at most on this server. A permission switched off here stops working for every existing token at once; turned on again it comes back.'))}
    <div id="s-sclim" aria-labelledby="s-sclim-h"></div>` : ''}
    <h4 id="s-agg-h">${tr('Guides')}</h4>
    ${seg('guide', g, [['team', N_('Team agent on a server'), 'users'], ['own', N_('Personal agent on your computer'), 'user']])}
    ${seg('os', os, [['linux', 'Linux'], ['mac', 'macOS'], ['win', 'Windows']])}
    <div class="agguidebox" id="s-agguide" role="tabpanel">${agSetupHtml(g, os)}</div>
    <div class="row aibtns"><button class="btn sm" data-m="ag-guide-cc" title="${esc(tr('Set up an agent step by step, or let Claude Code do it'))}">${ic('bot', 's')} ${tr('Let Claude Code set it up (Linux)')}</button></div>`;
}
async function agSetupDraw(md) {
  const box = $('#s-myown', md); if (!box) return;
  let j;
  try { j = await api('GET', '/api/my/agents'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; }
  box._j = j;
  const row = a => `<div class="mrow agsrow ${a.enabled ? '' : 'off'}" data-myag="${a.id}">${avBtn(a.id, a.name)}<span class="n"><span class="agnm"><b>${esc(a.name)}</b> <span class="muted">${esc(a.username)}</span></span>
      <small class="muted agfacts">${hdot(agentHst(a))}${((t) => `<span class="agft" title="${esc(t)}">${esc(t)}</span>`)([a.enabled ? agentSt(a) : a.admin_paused ? tr('paused by an admin') : tr('paused'), trn('{0} list', '{0} lists', (a.lists || []).length), scopeSummary(a.effective_scopes || a.scopes)].join(' · '))}</small></span>
    <span class="agacts"><button class="iconbtn" data-myag-act="perm" title="${esc(tr('Permissions'))}" aria-label="${esc(tr('Permissions of {0}', a.name))}">${ic('lock', 's')}</button><button class="iconbtn" data-myag-act="token" title="${esc(tr('New API token'))}" aria-label="${esc(tr('New API token'))}">${ic('key', 's')}</button>
      <button class="iconbtn ${a.enabled ? 'danger' : ''}" data-myag-act="pause" title="${esc(a.enabled ? tr('Pause') : tr('Resume'))}" aria-label="${esc(a.enabled ? tr('Pause') : tr('Resume'))}" ${!a.enabled && a.admin_paused ? 'disabled' : ''}>${ic(a.enabled ? 'pause' : 'play', 's')}</button>
      <button class="iconbtn danger" data-myag-act="del" title="${esc(tr('Delete'))}" aria-label="${esc(tr('Delete'))}">${ic('trash', 's')}</button></span></div>`;
  const add = j.allowed && j.count < j.max ? `<div class="row myagnew"><input id="myag-name" placeholder="${esc(tr('Display name'))}" aria-label="${esc(tr('Display name'))}" maxlength="60"><input id="myag-user" placeholder="${esc(tr('Username, e.g. my-claude'))}" aria-label="${esc(tr('Username'))}" title="${esc(tr('for the login and @mentions'))}" maxlength="32" autocapitalize="off" autocomplete="off" spellcheck="false"><input id="myag-prov" placeholder="${esc(tr('Where it runs, e.g. Claude (Anthropic, USA)'))}" aria-label="${esc(tr('Where it runs'))}" maxlength="80"><button class="btn sm pri" data-myag-act="new">${ic('plus', 's')} ${tr('Create agent')}</button></div>
    <div class="shint keep">${esc(trn('You can have {0} personal agent.', 'You can have {0} personal agents.', j.max))} ${esc(tr('You connect it yourself (your own provider and key): what it reads in your lists goes to that provider, and you are responsible for it. Everyone in a list you share with it is told where it runs.'))}</div>` : '';
  box.innerHTML = (j.agents.map(row).join('') || (j.allowed ? '' : `<div class="muted mhint">${tr('Your organisation does not let members connect agents (an admin can allow it: Administration > Organisation).')}</div>`)) + add;
  userNameFollow(box, 'myag-name', 'myag-user');  // 2.28.0 (#926)
  if (S.me?.is_admin) {
    try {
      const p = await api('GET', '/api/admin/agent-policy'); const sw = $('#s-uag', md), mx = $('#s-uagmax', md); if (sw) sw.checked = p.user_agents; if (mx) { mx.value = p.max_per_user; mx.disabled = !p.user_agents; }
      const lb = $('#s-sclim', md);  // 2.15.0 (#479): the admin's limit, one grid for agents and one for personal tokens
      if (lb && p.scope_limit) lb.innerHTML = [['agents', N_('Agents')], ['tokens', N_('Personal API tokens')]].map(([k, n]) => `<fieldset class="sclim"><legend>${tr(n)}</legend><div class="scgrid">${p.scopes.filter(x => k !== 'agents' || x !== 'account').map(x => `<label class="chkl sc"><input type="checkbox" data-sclim="${k}" data-scope="${x}" ${p.scope_limit[k].includes(x) ? 'checked' : ''} ${x === 'read' ? 'disabled' : ''}><span>${esc(tr(SCOPE_SHORT[x] || x))}</span></label>`).join('')}</div></fieldset>`).join('');
    } catch { /* offline */ }
  }
}
function agSetupWire(md) {
  md.addEventListener('click', async e => {
    const sg = e.target.closest('[data-agsv]');
    if (sg) {
      const k = sg.closest('[data-agseg]').dataset.agseg; LS.set(k === 'guide' ? 'agGuide' : 'agOs', sg.dataset.agsv);
      $$(`[data-agseg="${k}"] [data-agsv]`, md).forEach(b => { const on = b === sg; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
      const box = $('#s-agguide', md); if (box) box.innerHTML = agSetupHtml($('[data-agseg="guide"] .on', md)?.dataset.agsv || 'own', $('[data-agseg="os"] .on', md)?.dataset.agsv || 'linux');
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
        secretModal(tr('API token of {0}', r.name), r.token, tr('Copy it now into the agent’s configuration: it is shown only this once.') + ' ' + tr('Then share lists with the agent (list dialog > Sharing).'));
        await load(); render();
      }
      if (!a) { agSetupDraw(md); return; }
      if (k === 'token') { agTokenModal(a, `/api/my/agents/${a.id}/token`); return; }
      if (k === 'perm') {  // 2.15.0 (#479): what my agent may do (within the admin's limit) and from where
        permModal(tr('Permissions of {0}', a.name), box._j.scopes || [], a.scopes, a.allowed_ips, async (scopes, ips) => {
          await calReq('PATCH', `/api/my/agents/${a.id}`, {scopes, allowed_ips: ips}); toast(tr('Saved')); agSetupDraw(md);
        }, `<div class="shint keep">${tr('Deleting lists or fields, emptying the trash, changing 10 or more tasks at once, moving lists, folders and sharing always wait for your approval.')}</div>`);
        return;
      }
      if (k === 'pause') {
        if (a.enabled && !await askConfirm(tr('Pause {0}?', a.name), tr('Its API token is refused and no events are sent until you resume it. Nothing is deleted.'), {ok: tr('Pause'), danger: true})) return;
        await api('PATCH', `/api/my/agents/${a.id}`, {enabled: !a.enabled}); toast(a.enabled ? tr('Paused') : tr('Resumed'));
        await load(); render();
      }
      if (k === 'del') {
        if (!await askConfirm(tr('Delete the agent “{0}”?', a.name), tr('Its tokens, events, jobs and chats are deleted; lists it owns come to you. Its comments stay.'), {ok: tr('Delete'), danger: true})) return;
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
// shows one sub-tab and loads what it needs (save: remember it for this device)
function aiSubShow(md, want, save) {
  const k = aiSubCur(want); if (save) LS.set('aiSub', k);
  $$('[data-aisub]', md).forEach(b => { const on = b.dataset.aisub === k; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
  $$('[data-aisp]', md).forEach(p => { p.hidden = p.dataset.aisp !== k; });
  if (k === 'agents') return agDraw(md);
  if (k === 'lists') return aiTblDraw(md);
  if (k === 'usage') return aiuDraw(md);
  if (k === 'log') return audDraw(md);
  if (k === 'setup') return agSetupDraw(md);
}
// ---- 2.24.0 (#826): Settings > Administration in five sub-tabs (the pattern of Agents): People, Sign-in, Organisation,
// Server, Log & errors. The last one is remembered per device; the settings search opens the sub-tab of its hit.
const ADM_SUBS = [['users', 'users', N_('People|admin')], ['signin', 'key', N_('Sign-in')], ['org', 'home', N_('Organisation')], ['server', 'grid', N_('Server')], ['log', 'alert', N_('Log & errors')]];
function admSubCur(want) { const k = want || LS.get('admSub', 'users'); return ADM_SUBS.some(x => x[0] === k) ? k : 'users'; }
function admSubsHtml(parts, want) {
  const cur = admSubCur(want);
  return `<div class="seg aisub admsub" role="tablist" aria-label="${esc(tr('Administration'))}">${ADM_SUBS.map(([k, i, n]) => `<button type="button" role="tab" id="adms-${k}" data-admsub="${k}" aria-controls="admp-${k}" aria-selected="${k === cur}" class="${k === cur ? 'on' : ''}">${ic(i, 's')}<span>${tr(n)}</span></button>`).join('')}</div>
    ${ADM_SUBS.map(([k]) => `<div class="aisp admp" data-admp="${k}" id="admp-${k}" role="tabpanel" aria-labelledby="adms-${k}" ${k === cur ? '' : 'hidden'}>${parts[k] || ''}</div>`).join('')}`;
}
function admSubShow(md, want, save) {
  const k = admSubCur(want); if (save) LS.set('admSub', k);
  $$('[data-admsub]', md).forEach(b => { const on = b.dataset.admsub === k; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); });
  $$('[data-admp]', md).forEach(p => { p.hidden = p.dataset.admp !== k; });
}
// Organisation: whether members may connect their own agents (#896, the policy user_agents of #420, off by default)
function orgAgentsHtml(hint) {
  if (!S.api?.enabled) return '';
  return `<h4 id="s-orgag-h">${tr('Agents')}</h4>
    <div class="featgrid"><label class="wide"><input type="checkbox" id="s-orgagents" ${S.about?.user_agents ? 'checked' : ''}><span>${tr('Members may connect agents')}<small class="muted">${tr('People can then connect their own AI agent (their own provider, key and computer) and share lists with it. They are responsible for what that provider receives; everyone in a list is told when an agent joins it and where it runs. Off by default.')}</small></span></label></div>`;
}
// Server: storage per person (#910), the support address, the daily e-mail limit (#899) and the notice above the app (#907)
function hostHtml(hint) {
  const a = S.about || {}, ann = a.announce_all || {};
  const gb = mb => mb ? (mb >= 1024 ? fmtNum(mb / 1024, 1) + ' GB' : mb + ' MB') : tr('unlimited');
  const toLoc = x => { if (!x) return ''; const d = new Date(x); return isNaN(d) ? '' : new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
  return `<h4 id="s-ann-h">${tr('Notice to everyone')}</h4>
    ${hint(tr('Shown above the app for everyone, e.g. before planned maintenance. People can hide it; a changed notice shows again. Scripts can set it too (API or the command “python app.py announce”).'))}
    <div class="row"><textarea id="s-ann-text" rows="2" maxlength="500" aria-labelledby="s-ann-h" placeholder="${esc(tr('e.g. Maintenance tonight from 22:00, Kalmido is unavailable for about 10 minutes.'))}">${esc(ann.text || '')}</textarea></div>
    <div class="row"><label for="s-ann-level">${tr('Kind')}</label><select id="s-ann-level"><option value="info">${tr('Notice')}</option><option value="maintenance" ${ann.level === 'maintenance' ? 'selected' : ''}>${tr('Maintenance')}</option></select></div>
    <div class="row"><label for="s-ann-from">${tr('From')}</label><input type="datetime-local" id="s-ann-from" value="${esc(toLoc(ann.starts_at))}"><label for="s-ann-to" class="qtol">${tr('until|time')}</label><input type="datetime-local" id="s-ann-to" value="${esc(toLoc(ann.ends_at))}"></div>
    <div class="row"><label>${tr('Push')}</label><label class="chkl"><input type="checkbox" id="s-ann-push"> ${tr('Also send it as a push to everyone (once)')}</label></div>
    <div class="row"><span class="spacer"></span>${ann.text ? `<button class="btn sm" data-m="ann-clear">${ic('x', 's')} ${tr('Remove')}</button>` : ''}<button class="btn sm pri" data-m="ann-save">${ic('check', 's')} ${tr('Publish')}</button></div>
    <h4 id="s-quota-h">${tr('Storage per person')}</h4>
    ${hint(tr('Counts every file a person uploaded. From 80 % they see a warning, at 100 % new uploads are refused (nothing is deleted) and they can contact support. Empty = the server default ({0}).', gb(a.storage_quota_env)))}
    <div class="row"><label for="s-quota">${tr('Storage per person')}</label><input id="s-quota" inputmode="numeric" class="numin" value="${a.storage_quota_mb == null ? '' : esc(String(a.storage_quota_mb))}" placeholder="${esc(String(a.storage_quota_env || 0))}"><span class="muted">${tr('MB (0 = unlimited)')}</span></div>
    <div class="row"><label for="s-qpool">${tr('Shared by')}</label><select id="s-qpool"><option value="user">${tr('each person on their own')}</option><option value="org" ${a.storage_pool === 'org' ? 'selected' : ''}>${tr('the organisation (amount × members)')}</option></select></div>
    <div class="row"><label for="s-support">${tr('Support address')}</label><input id="s-support" type="email" value="${esc(a.support_email || '')}" placeholder="${esc(a.support_email_env || tr('the first admin’s address'))}" autocomplete="off"></div>
    <h4 id="s-maillim-h">${tr('E-mails per day')}</h4>
    ${hint(tr('Invitations and new sign-in links a person can have sent per day (at most 5 a day go to one address). Over the limit the link is shown to copy instead.'))}
    <div class="row"><label for="s-maillim">${tr('Per account and day')}</label><input id="s-maillim" inputmode="numeric" class="numin" value="${esc(String(a.mail_day_limit || 30))}"></div>
    ${a.hosted ? `<div class="shint keep">${ic('alert', 's')} ${tr('Hosted server (KALMIDO_HOSTED): integrations only reach public HTTPS addresses.')}</div>` : ''}`;
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
    const p = $('[data-admp="server"]', md); if (p) { p.innerHTML = instanceHtml((id, on, label) => `<label class="chkl"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${label}</label>`, t => `<div class="shint">${t}</div>`) + hostHtml(t => `<div class="shint">${t}</div>`) + plaHtml() + bkHtml() + stoHtml(); plaDraw(md); bkDraw(md); }
  });
}
function settingsModal(focus) {
  const s = S.settings;
  const topicUrl = `${S.ntfyUrl}/${s.ntfy_topic}`;
  const dev = `<span class="devtag">${tr('This device')}</span>`, hint = t => `<div class="shint">${t}</div>`;
  const chk = (id, on, label) => `<label class="chkl"><input type="checkbox" id="${id}" ${on ? 'checked' : ''}> ${label}</label>`;
  const devbox = (inner, open = false) => inner ? `<details class="sdev" ${open ? 'open' : ''}><summary>${ic('key', 's')}${tr('Advanced · for developers')}</summary>${inner}</details>` : '';
  const prio = `<div class="row"><label for="s-pushprio">${tr('How urgent')}</label><select id="s-pushprio">${[['3', N_('Normal')], ['4', N_('Loud')], ['5', N_('Urgent')]].map(([v, n]) => `<option value="${v}" ${(s.push_priority || '4') === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
      ${hint(tr('Loud rings and vibrates longer; Urgent may also break through “Do not disturb” on some phones.'))}`;
  const pane = {
    account: S.me ? accountHtml() : '',
    look: `<div id="s-lookin">${lookHtml()}</div>
      <h4>${tr('Tips')}</h4><div class="row"><label>${tr('Hints')}</label><button class="btn sm" data-m="hints-reset">${ic('undo', 's')} ${tr('Show tips again')}</button></div>
      ${hint(tr('Brings back the one-time hints on this device (touch screens show helper texts once).'))}
      <h4 id="s-tabbar-h">${tr('Tab bar')}${dev}</h4>
      ${hint(tr('At the bottom on a phone (the desktop shows every module in the sidebar). A phone fits {0} tabs, the rest goes under “More”.', TAB_MAX))}
      <div class="navlist" id="s-tabbar"></div>
      <div class="row" style="margin-top:.5rem"><select id="s-tabadd" style="flex:1" aria-label="${tr('+ Add tab …')}"></select><button class="btn sm" data-m="tab-reset">${tr('Default')}</button></div>
      <h4 id="s-side-h">${tr('Sidebar')}</h4>
      ${hint(tr('The order of the groups and what they show; the same on every device. The eye hides a group, the boxes single entries.'))}
      <div class="navlist sidecfg" id="s-sidebar"></div>
      <div class="row" style="margin-top:.5rem"><span class="spacer"></span><button class="btn sm" data-m="side-reset">${tr('Default')}</button></div>`,
    general: `<h4 id="s-lang-h">${tr('Language')}</h4>
      <div class="row"><div class="seg" id="s-lang" role="group" aria-labelledby="s-lang-h">${(S.languages || []).map(L => `<button data-lang-set="${esc(L.code)}" class="${(s.lang || 'en') === L.code ? 'on' : ''}" lang="${esc(L.code)}">${langName(L)}</button>`).join('')}</div></div>
      ${hint(tr('Applies to all devices and to the notifications. Quick add understands English, German and the language chosen here.'))}
      <h4 id="s-today-h">${tr('Today')}</h4>
      <div class="row">${chk('s-tinbox', s.today_inbox === '1', tr('Show the inbox in Today'))}</div>
      ${hint(tr('Tasks without a date that are still in the inbox get their own section under today’s tasks, with quick buttons to sort them; they count in Today’s number.'))}
      ${depsOn() ? `<div class="row">${chk('s-hideblk', s.hide_blocked_today === '1', tr('Hide tasks that are still blocked by another task'))}</div>` : ''}
      <h4 id="s-dates-h">${tr('Changing and completing tasks')}</h4>
      <div class="row">${chk('s-dateok', s.date_confirm === '1', tr('Confirm changes of the date with OK'))}</div>
      ${hint(tr('Off: a new day, time, start, repeat or reminder is saved as soon as you pick it; “Undo” in the message takes the whole change back. On: changes wait for OK.'))}
      <div class="row">${chk('s-celebrate', s.celebrate !== '0', tr('Celebrate completions'))}</div>
      ${hint(tr('When Today is cleared or a list or project is complete, the heron flies by with a one-liner. With reduced motion (system setting) it just says hello.'))}
      <div class="row">${chk('s-progsub', s.progress_subtasks === '1', tr('Count subtasks in the progress of a list'))}</div>
      <h4 id="s-plan-h">${tr('Day planning')}</h4>
      <div class="row"><label for="s-wfrom">${tr('Working hours')}</label>${timeIn('s-wfrom', s.work_start || '09:00', {label: tr('Working hours from'), clear: false})}<label for="s-wto" class="qtol">${tr('until|time')}</label>${timeIn('s-wto', s.work_end || '17:00', {label: tr('Working hours until'), clear: false})}</div>
      <div class="row"><label for="s-review">${tr('Daily review at')}</label>${timeIn('s-review', s.review_time || '', {label: tr('Daily review at'), empty: tr('off')})}</div>
      ${hint(tr('“Plan my day” in Today fills the free time between your calendar events within these hours with your open tasks (a task without a duration counts 30 minutes). The daily review shows in Today after the end of your working hours; with a time set it also comes as a push.'))}`,
    modules: modulesHtml(hint),
    notify: `${S.webpush?.enabled ? `<div class="pushnow" id="s-pushnow" role="status" aria-live="polite"></div>` : ''}${S.webpush?.enabled ? `<h4>${tr('Delivery')}</h4>
      <div class="row"><label for="s-pushch">${tr('Channel')}</label><select id="s-pushch">${[['webpush', N_('Web Push')], ['ntfy', 'ntfy'], ['both', N_('Both')]].map(([v, n]) => `<option value="${v}" ${(s.push_channel || 'webpush') === v ? 'selected' : ''}>${v === 'ntfy' ? n : tr(n)}</option>`).join('')}</select><button class="btn sm" data-m="ptest">${ic('bell', 's')} ${tr('Send test')}</button></div>
      ${prio}
      <div class="shint wpstate" id="s-wpstate"></div>
      ${hint(tr('Web Push comes straight from the browser or the installed app, no extra app needed. Turn it on below on every device that should ring.'))}
      <h4>${tr('This device')}</h4>
      <div id="s-wp"><div class="muted">${tr('Loading…')}</div></div>` : ''}
      <div id="s-ntfy"><h4>${S.webpush?.enabled ? 'ntfy' : tr('Notifications (ntfy)')}</h4>
      <div class="row"><label>${tr('Topic')}</label><code class="topic">${esc(s.ntfy_topic)}</code><button class="btn sm" data-m="test">${ic('bell', 's')} ${tr('Send test')}</button></div>
      ${S.webpush?.enabled ? '' : prio}
      ${hint(`${tr('Subscribe in the ntfy app: server {0}, topic as above', esc(S.ntfyUrl))}${/ntfy\.sh/.test(S.ntfyUrl) || !S.me?.ntfy_inbox ? '' : tr(', with a user that has read access')}. <a href="${esc(topicUrl)}" target="_blank" rel="noopener">${tr('Web view')}</a>`)}</div>
      ${notifMatrixHtml(s, hint)}
      <h4>${tr('Reminders')}</h4>
      <div class="row"><label for="s-allday">${tr('All-day reminder at')}</label>${timeIn('s-allday', s.allday_time, {label: tr('All-day reminder at'), clear: false})}</div>
      <div class="row"><label for="s-defrem">${tr('Default reminder')}</label><select id="s-defrem"><option value="">${tr('none')}</option>${REM_OPTS.map(([v, n]) => `<option value="${v}" ${s.default_reminder === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}${s.default_reminder && !REM_OPTS.some(o => o[0] === s.default_reminder) ? `<option value="${esc(s.default_reminder)}" selected>${esc(s.default_reminder.split(',').map(fmtRem).join(', '))}</option>` : ''}</select></div>
      <div class="row"><label for="s-digest">${tr('Daily digest at')}</label>${timeIn('s-digest', s.digest_time, {label: tr('Daily digest at'), empty: tr('off')})}</div>
      <div id="s-digmail-w"></div>
      <h4 id="s-quiet-h">${tr('Repeated reminders')}</h4>
      <div class="row"><label for="s-qfrom">${tr('Quiet from')}</label>${timeIn('s-qfrom', s.quiet_from ?? '22:00', {label: tr('Quiet from'), empty: tr('none')})}<label for="s-qto" class="qtol">${tr('until|time')}</label>${timeIn('s-qto', s.quiet_to ?? '07:00', {label: tr('Quiet until'), empty: tr('none')})}</div>
      ${hint(tr('A task or a list can repeat its reminder until the task is done (date dialog > Repeat reminder; list dialog for all its tasks). During the quiet hours nothing repeats; the next one comes when they end.'))}`,
    integr: integrCardsHtml() + calsHtml(chk, hint) + `<h4 id="s-ical-h">${tr('Calendar subscription')}</h4>
      ${hint(tr('Your open tasks with a date as a calendar for Google Calendar, Apple Calendar, Outlook or Thunderbird: read-only, the calendar app refreshes it by itself (usually every few hours, some apps every 15 minutes). Timed tasks appear with their duration, all-day tasks as all-day events, recurring tasks with all future dates.'))}
      <div id="s-ical"><div class="muted mhint">${tr('Loading…')}</div></div>
      <div class="row"><label for="s-icalscope">${tr('Tasks')}</label><select id="s-icalscope"><option value="all">${tr('All visible tasks (incl. shared lists)')}</option><option value="mine" ${s.ical_scope === 'mine' ? 'selected' : ''}>${tr('Only mine and assigned to me')}</option></select></div>
      <div class="row"><label>${tr('Reminders')}</label>${chk('s-icalalarm', s.ical_alarms !== '0', tr('as calendar alarms'))}</div>
      <details class="shelp sdet"><summary>${tr('How to subscribe')}</summary><ul class="slist">
        <li>${tr('<b>Android / Google Calendar:</b> on a computer open calendar.google.com > Other calendars > + > From URL, paste the link. It then shows up in the Calendar app on the phone (tap the calendar under Settings to sync it).')}</li>
        <li>${tr('<b>iPhone / iPad:</b> Settings > Apps > Calendar > Calendar Accounts > Add Account > Other > Add Subscribed Calendar, paste the link. <b>Mac:</b> Calendar > File > New Calendar Subscription.')}</li>
        <li>${tr('<b>Thunderbird:</b> Calendar > New Calendar > On the Network, paste the link.')}</li>
        <li>${tr('<b>Outlook:</b> Add calendar > Subscribe from web.')}</li>
        <li>${tr('<b>Only reachable at home or over a VPN?</b> Google Calendar, iCloud and Outlook.com fetch the feed from their own servers and then cannot reach it. Use an app that fetches on the device instead: on Android ICSx⁵ (the calendar then shows up in every calendar app), on a Mac the location “On My Mac” instead of iCloud, or Thunderbird.')}</li></ul></details>
      ${hintK(tr('Anyone who knows the link sees these tasks. If it got out, create a new link: the old one stops working at once.'))}
      ${caldavHtml(hint)}
      ${S.paperless?.personal || S.paperless?.enabled ? `<h4 id="s-pl-h">Paperless</h4>
      ${hint(tr('Link documents from Paperless-ngx to tasks. Your connections: the ones an admin set up for you (you enter your own API token, so Paperless shows you exactly what you may see there) and your own, which only you see and use.'))}
      ${S.paperless?.hosted ? `<div class="shint keep">${ic('alert', 's')} ${tr('On this hosted server only Paperless servers that are reachable over the internet with HTTPS can be connected, none in your own network.')} <a href="https://github.com/Gegenschuss/kalmido#readme" target="_blank" rel="noopener noreferrer">${tr('Self-hosting Kalmido reaches servers in your own network too.')}</a></div>` : ''}
      <div class="members" id="s-plc"><div class="muted mhint">${tr('Loading…')}</div></div>
      ${S.paperless?.enabled ? `<div class="row"><label>${tr('After upload')}</label>${chk('s-plkeep', s.paperless_keep === '1', tr('Also keep the attachment in Kalmido'))}</div>` : ''}` : ''}
      <h4 id="s-mail-h">${tr('Tasks by e-mail')}</h4><div id="s-mail"></div>
      ${shareHtml(hint)}
      <ul class="slist">
        ${S.ntfyInbox?.enabled && S.me?.ntfy_inbox ? `<li>${tr('Single files also via the ntfy app:')} ${tr('In the ntfy app, add server {0} once', `<code class="topic">${esc(S.ntfyInbox.server)}</code>`)}${tr(' and log in with a user that may write to the topic (Settings > Manage users).')} ${tr('Then: share an image or text > ntfy > server as above, topic {0}. A few seconds later it is a task in the inbox, files as attachments.', `<code class="topic">${esc(S.ntfyInbox.topic)}</code>`)}</li>` : ''}</ul>
      ${devbox(whHtml())}`,
    data: `<h4 id="s-imp-h">${tr('Import')}</h4>
      ${hint(tr('Move your tasks over from another app. You see a preview first; importing the same file again skips what is already there, and an import can be undone for 24 hours. Nothing inside the file is fetched from the internet.'))}
      <div class="row"><label for="s-imp-src">${tr('From')}</label><select id="s-imp-src">${IMP_SRC.map(([k, n]) => `<option value="${k}">${esc(tr(n))}</option>`).join('')}</select></div>
      <div class="shelp impHelp" id="s-imp-help">${impHelp('todoist')}</div>
      <div class="row"><label for="s-import">${tr('File')}</label>${fileBtn('s-import', IMP_ACCEPT.todoist)}</div>
      <div id="s-imp-out"></div>
      <div class="members" id="s-imp-hist"></div>
      <h4>${tr('Export')}</h4>
      <div class="row"><label>${tr('Export')}</label><a class="btn sm" href="/api/export.json" download>${ic('download', 's')} ${tr('Download JSON')}</a></div>
      <h4 id="s-tpl-h">${tr('Templates')}</h4>
      ${hint(tr('Private to you. Save a task (with subtasks) from its menu (…) or a list from the list dialog; use them from the template button in the add bar or under Lists > +. Dates are kept as “days after use”.'))}
      <div class="members" id="s-tpls"><div class="muted mhint">${tr('Loading…')}</div></div>
      ${sampleHtml(hint)}`,
    ai: aiPaneOn() ? aiHtml(hint, {agents: 'agents', agentdots: 'agents', usage: 'usage', activity: 'log'}[focus]) : '',  // 2.7.0 (#405 S2)
    users: S.me?.is_admin ? admSubsHtml({  // 2.24.0 (#826): Administration in sub-tabs like Agents
      users: usersHtml() + grpHtml() + orphHtml(),
      signin: `<div id="s-signin">${signinHtml(hint)}</div>`,
      org: orgsHtml() + orgAgentsHtml(hint),
      server: instanceHtml(chk, hint) + hostHtml(hint) + plaHtml() + bkHtml() + stoHtml(),
      log: aaHtml()}, {users: 'users', groups: 'users'}[focus]) : '',  // 1.9.0: users first
    help: `<h4>${tr('Getting started')}</h4>
      <div class="row"><button class="btn sm" data-m="tour">${ic('arrow', 's')} ${tr('Restart the welcome tour')}</button>${isMobile() ? '' : `<button class="btn sm" data-m="keys">${ic('help', 's')} ${tr('Keyboard shortcuts')} ${kb('?')}</button>`}<button class="btn sm" data-m="cele-try">${ic('check', 's')} ${tr('Show the celebration')}</button></div>
      ${isMobile() ? '' : `<div class="shelp">${tr('{0}: search and commands for everything (tasks, lists, views, settings). j / k move through the tasks, x completes, s snoozes, g t goes to Today.', kbText('Mod+K'))}</div>`}
      <h4>${tr('Quick add')}</h4>
      <div class="shelp">${tr('today, tomorrow, day after tomorrow, friday, next monday, in 3 days, 12.10., 3pm, at 15:00<br>daily, weekdays, weekly, every monday, every 2 weeks, monthly, yearly<br>!high / !medium / !low (or !!!, !!, !) · #tag · ~list, “in list Work” or “… in Work” at the end<br>German works too: morgen 15 uhr, jeden montag, !hoch<br>Keyboard: n = new task, / = search, Esc = close')}</div>
      <h4>${tr('Undo')}</h4>
      <div class="shelp">${tr('Every change can be undone: the ← / → buttons at the top (on a phone in the “…” menu), the “Undo” in the message, Ctrl+Z / ⌘Z. Settings too. Offline, the change is simply not sent.')}</div>
      <h4>${tr('Formatting (Markdown)')}</h4>
      <div class="shelp">${tr('<b>Descriptions:</b> <code>**bold**</code>, <code>*italic*</code>, <code>~~strikethrough~~</code>, <code>&#96;code&#96;</code>, links as <code>[text](https://…)</code> or a plain https:// address, headings <code>#</code> / <code>##</code> / <code>###</code>, lists <code>- item</code> or <code>1. item</code>, checklists <code>- [ ]</code> / <code>- [x]</code> (tick them right in the formatted text). “Turn the open checklist items into subtasks” below the formatted description makes real subtasks of the unticked items.')}${collab() ? '<br>' + tr('<b>Comments:</b> the same bold, italic, strikethrough, code and links, plus line breaks and @mentions; no headings, lists or checklists.') : ''}</div>
      <h4>${tr('Lists and projects')}</h4>
      <div class="shelp">${tr('A list is a plain task list; a project adds the project modules you switched on (list menu … > Project). For shopping or packing lists: list menu … (or Sort) > Show completed at the bottom: what you tick off stays visible at the bottom and comes back with one tap.')}</div>
      <h4>${tr('Templates')}</h4>
      <div class="shelp">${tr('Task menu (…) or list dialog > Save as template. The template button in the add bar creates the task in the current list, Lists > + > New list from template a whole list. Manage them under Settings > Data.')}</div>
      ${timeOn() ? `<h4>${tr('Time tracking')}</h4><div class="shelp">${tr('Start a timer from a task (detail panel, task menu …) or add time by hand; the running timer shows in the top bar on every device. Sidebar > Time tracking: hours per list and task for a week, month or any range, CSV export and a printable timesheet. In shared lists everyone sees the time of all members, but only changes their own entries. Finished focus sessions on a task count as time unless a timer ran at the same time.')}</div>` : ''}
      ${depsOn() || fieldsOn() || progressOn() ? `<h4>${tr('Projects')}</h4><div class="shelp">${tr('<b>Dependencies:</b> in a task, “Waiting on…” > “Another task” picks the tasks that have to be done first; the task shows “blocked” until they are, and whoever it is assigned to gets a message once the last one is done. “Waiting on…” > “Someone outside” marks a task that waits on a person (a client, an office, a delivery) with a follow-up day. <b>Custom fields</b> (list dialog, owner): text, number, selection, date, checkbox, person or link per task; pin up to two as chips on the rows, sort and filter by them. <b>Status and progress</b> (Project progress module): the list header shows the progress; with collaboration, owner and editors set a status with a short note, and the project status (“Where is it stuck?”) lists overdue, blocked and unassigned tasks of all lists.')}</div>` : ''}
      ${feat('stats') ? `<h4>${tr('Statistics')}</h4><div class="shelp">${tr('Sidebar > Statistics (or pin it as a tab): completions per week / day and per list, on-time rate, overdue trend, focus time and habit streaks of the last 12 weeks.')}</div>` : ''}
      <h4>${tr('Gestures (phone)')}</h4>
      <div class="shelp">${tr('Swipe right: complete · swipe left: snooze / delete · long-press: the task’s menu (with “Select” for several) · long-press and drag: reorder, move to another column, quadrant or onto a day; drag to the left edge and hold briefly to open the lists (dropping a subtask there = standalone task in that list).')}</div>`,
  };
  pane.help += aboutHtml(chk, hint);
  const secs = SET_SECS.filter(([k]) => pane[k]);
  let cur = {tabbar: 'look', sidebar: 'look', layout: 'modules', collab: 'modules', focus: 'modules', time: 'modules', templates: 'data', sample: 'data', newskinds: 'notify', agents: 'ai', agentdots: 'ai', usage: 'ai', activity: 'ai', share: 'integr', ical: 'integr', calendars: 'integr', webhooks: 'integr', caldav: 'integr', tokens: 'account', apppw: 'account', about: 'help', groups: 'users', dayplan: 'general'}[focus] || focus;
  if (!secs.some(([k]) => k === cur)) cur = LS.get('settingsSec', 'general');
  if (!secs.some(([k]) => k === cur)) cur = 'general';
  const md = modal(`<div class="shdr"><button type="button" class="iconbtn sback" data-m="s-index" title="${esc(tr('All settings'))}" aria-label="${esc(tr('All settings'))}">${ic('back', 's')}</button><h3>${tr('Settings')}</h3><span class="ssaved" role="status" aria-live="polite"></span><span class="spacer"></span><span class="ssearch">${ic('search', 's')}<input type="search" id="s-search" placeholder="${esc(tr('Search settings'))}" aria-label="${esc(tr('Search settings'))}" autocomplete="off" aria-controls="s-sres"></span><div class="ssres hidden" id="s-sres" role="listbox" aria-label="${esc(tr('Search settings'))}"></div><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <div class="sbody"><nav class="snav" role="tablist" aria-label="${tr('Settings')}">${secs.map(([k, i, n]) => `<button role="tab" id="st-${k}" aria-controls="sp-${k}" aria-selected="${k === cur}" data-sec="${k}" class="${k === cur ? 'on' : ''}">${ic(i, 's')}<span>${tr(n)}</span>${SET_DESC[k] ? `<small class="sndesc">${esc(tr(SET_DESC[k]))}</small>` : ''}</button>`).join('')}</nav>
      <div class="spanes">${secs.map(([k]) => `<section class="spane ${k === cur ? '' : 'hidden'}" role="tabpanel" id="sp-${k}" aria-labelledby="st-${k}" data-pane="${k}">${pane[k]}</section>`).join('')}</div></div>`);
  md.classList.add('smodal');
  // 2.25.0 (UX-17): a phone opens on an overview of the areas (name + what is in it); a tap opens one, ‹ goes back
  const idx = on => { md.classList.toggle('sidx', on); if (on) $('.snav [data-sec].on', md)?.setAttribute('aria-selected', 'false'); };
  if (isMobile() && !focus) idx(true);
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
  if (focus === 'caldav' || focus === 'apppw') setTimeout(() => $(focus === 'caldav' ? '#s-dav-h' : '#s-apw-h', md)?.scrollIntoView({block: 'start'}), 0);
  // 2.7.0 (#405 S8): the module keys land on their row (and open its options), not just on top of Modules
  const modFocus = {layout: 'cal', collab: 'collab', focus: 'pomo', time: 'time'}[focus];
  if (modFocus) setTimeout(() => { const r = $(`[data-pane="modules"] [data-modrow="${modFocus}"]`, md); if (!r) return; const gd = r.closest('details.modgrp'); if (gd) gd.open = true; const o = $('details.mopt', r); if (o) o.open = true; r.scrollIntoView?.({block: 'start'}); r.classList.add('flash'); }, 0);
  const show = k => {
    cur = k; LS.set('settingsSec', k);
    $$('.snav button', md).forEach(b => { b.classList.toggle('on', b.dataset.sec === k); b.setAttribute('aria-selected', b.dataset.sec === k); });
    $$('.spane', md).forEach(p => p.classList.toggle('hidden', p.dataset.pane !== k));
    $('.spanes', md).scrollTop = 0;
    if (k === 'data') templatesDraw(md);
    if (k === 'integr') { icalDraw(md); calsDraw(md); whDraw(md); }
    if (k === 'notify') wpDraw(md);
    if (k === 'users') { aaDraw(md); bkDraw(md); orphDraw(md); grpDraw(md); }
    if (k === 'ai') aiSubShow(md);  // 2.5.1 (#393): only the shown sub-tab loads
    if (k === 'users') admSubShow(md);
    if (k === 'account') { tfaDraw(md); tokDraw(md); apwDraw(md); }
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
      setApply({agents_hidden: [...hid].sort((a, b) => a - b).join(',')}, `${tr('In the header')} · ${agentById(aid)?.name || aid}`);
      return;
    }
    if (el.dataset.nm) {  // 2.1.0 (#317) the notification matrix
      const row = NOTIF_ROWS.find(x => x[0] === el.dataset.nm);
      setApply(notifPatch(S.settings, el.dataset.nm, el.dataset.ch, el.checked), `${tr(row[1])} · ${el.dataset.ch === 'news' ? tr('News') : tr('Push')}`)
        .then(() => { S.notify = notifMatrix(S.settings); });
      return;
    }
    if (el.dataset.feat) {
      const on = el.checked, k = el.dataset.feat, n = tr(FEATS.find(x => x[0] === k)?.[1] || k);
      const fs = new Set((S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean));
      on ? fs.add(k) : fs.delete(k);
      $$(`[data-feat="${k}"]`, md).forEach(x => { x.checked = on; x.closest('[data-modrow]')?.classList.toggle('off', !on); });  // 2.0.5: agents twice
      setApply({features: FEATS.map(x => x[0]).filter(x => fs.has(x)).join(',')}, on ? tr('{0} on', n) : tr('{0} off', n)).then(() => {
        const r = el.closest('[data-modrow]'); if (r && k === 'time' && on && !$('#s-trnd', md)) { const cur = LS.get('settingsSec'); md._noflush = true; md.remove(); settingsModal(cur); }
      });
    }
  });
  md.addEventListener('keydown', e => { if (e.key === 'Enter' && (SETS[e.target.id] || e.target.id === 'a-name') && isText(e.target)) { e.preventDefault(); e.target.id === 'a-name' ? saveName() : saveEl(e.target); } });
  md.addEventListener('change', e => { if (['s-collaball', 's-timeall', 's-updcheck', 's-2fareq', 's-pklogin', 's-oidcauto', 's-publinks'].includes(e.target.id)) adminSwitch(md, e.target); });
  md.addEventListener('change', async e => {  // 2.7.0 (#407): hours per day / shift for the whole server, one history step
    if (e.target.id !== 's-dayh') return;
    const from = S.timeDayH || 8, to = +String(e.target.value).replace(',', '.');
    if (!(to >= 1 && to <= 24)) { toast(tr('Hours per day: a number from 1 to 24')); e.target.value = fmtNum(from, 2); return; }
    if (to === from) return;
    const put = async v => { const j = await api('PATCH', '/api/admin/settings', {time_day_h: v}); S.about = {...S.about, ...j}; S.timeDayH = +j.time_day_h || v; const f = $('#s-dayh'); if (f && f !== document.activeElement) f.value = fmtNum(S.timeDayH, 2); render(); return {skipped: []}; };
    try { await put(to); } catch { return; }
    setSaved(histAdd({label: tr('Changed setting: {0}', tr('Hours per day')), sett: true, undo: () => put(from), redo: () => put(to)}));
  });
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
  $('#s-search', md).addEventListener('input', e => {
    const q = e.target.value.trim().toLowerCase(), sb = $('.sbody', md);
    if (!q) { sres.classList.add('hidden'); sres.innerHTML = ''; sb.classList.remove('snores'); return; }
    const hits = [], seen = new Set();
    const add = (el, k) => { if (!el || seen.has(el) || hits.length >= 14) return; const t = (el.matches('input,textarea') ? el.getAttribute('placeholder') || el.getAttribute('aria-label') || '' : el.textContent).replace(/\s+/g, ' ').trim(); if (!t) return; seen.add(el); hits.push({el, t, k}); };
    for (const [ws, sel] of SYN) if (ws.some(w => w.startsWith(q) || (q.length > 3 && q.includes(w)))) { const el = $(sel, md); if (el) add(el, el.closest('.spane')?.dataset.pane); }
    for (const p of $$('.spane', md)) for (const el of $$('h4, .row > label, label.chkl, .featgrid label > span, .modrow b, .modrow small, summary, button:not(.iconbtn), .shint, option, th', p)) {
      if (!shown(el) || el.closest('.ssres')) continue;
      const own = el.matches('.featgrid label > span') ? (el.firstChild?.textContent || '') + ' ' + (el.querySelector('small')?.textContent || '') : el.textContent;
      if (own.toLowerCase().includes(q)) add(el.matches('option') ? el.closest('select') : el, p.dataset.pane);
      if (hits.length >= 14) break;
    }
    const tab = k => $(`.snav [data-sec="${k}"] span`, md)?.textContent || k;
    const lab = h => (h.el.matches('select') ? (h.el.closest('.row')?.querySelector('label')?.textContent || h.t) : h.t).slice(0, 80);
    sres.innerHTML = hits.length ? hits.map((h, i) => `<button type="button" role="option" data-hit="${i}"><span class="muted">${esc(tab(h.k))} ›</span> ${esc(lab(h))}</button>`).join('') : `<div class="muted mhint">${esc(tr('Nothing found for “{0}”', e.target.value.trim()))}</div>`;
    sb.classList.toggle('snores', !hits.length); sb.dataset.nores = hits.length ? '' : tr('Nothing found for “{0}”', e.target.value.trim());
    sres._hits = hits; sres.classList.remove('hidden');
  });
  sres.addEventListener('click', e => {
    const b = e.target.closest('[data-hit]'); if (!b) return;
    const h = sres._hits[+b.dataset.hit]; sres.classList.add('hidden'); $('#s-search', md).value = ''; $('.sbody', md).classList.remove('snores');
    show(h.k); idx(false);
    const ap = h.el.closest('[data-admp]'); if (ap) admSubShow(md, ap.dataset.admp, true);
    const ai = h.el.closest('[data-aisp]'); if (ai) aiSubShow(md, ai.dataset.aisp, true);
    for (let det = h.el.closest('details'); det; det = det.parentElement?.closest('details')) if (!(det === h.el.closest('details') && h.el.matches('summary'))) det.open = true;  // 2.25.0: also the folded module group around it
    const r = h.el.closest('.row, .modrow, details, h4, label') || h.el;
    setTimeout(() => { r.scrollIntoView?.({block: 'center'}); r.classList.add('flash'); setTimeout(() => r.classList.remove('flash'), 1600); }, 30);
  });
  setTimeout(() => $(`.snav [data-sec="${cur}"]`, md)?.scrollIntoView({block: 'nearest', inline: 'nearest'}), 0);
  if (cur === 'data') templatesDraw(md).then(() => { if (focus === 'templates') $('#s-tpl-h', md)?.scrollIntoView({block: 'start'}); });
  if (focus === 'sample') setTimeout(() => $('#s-sample-h', md)?.scrollIntoView({block: 'start'}), 0);
  if (cur === 'integr') { icalDraw(md); calsDraw(md); whDraw(md); }
  calsWire(md); whWire(md); if (S.me?.is_admin) { agWire(md); audWire(md); }
  agSetupWire(md);  // 2.7.2 (#420)
  plcWire(md); if (S.me?.is_admin) plaWire(md);
  if (cur === 'notify') wpDraw(md);
  ntfyShow(md);
  if (cur === 'users') { aaDraw(md); bkDraw(md); orphDraw(md); grpDraw(md); }
  aiTblWire(md);
  if (cur === 'ai') aiSubShow(md, {agents: 'agents', usage: 'usage', activity: 'log'}[focus]);  // 2.5.1 (#393)
  md.addEventListener('click', e => { const b = e.target.closest('[data-aisub]'); if (b) aiSubShow(md, b.dataset.aisub, true); const g = e.target.closest('[data-aigo]'); if (g) aiSubShow(md, g.dataset.aigo, true); });
  md.addEventListener('click', e => { const b = e.target.closest('[data-admsub]'); if (b) admSubShow(md, b.dataset.admsub, true); });  // 2.24.0 (#826)
  if (S.me?.is_admin) hostWire(md);
  aiuWire(md, only => { const box = $('#s-aiu', md); if (only && box && S.aiu.data) box.innerHTML = aiuHtml(S.aiu.data, Math.max(240, Math.min(720, (box.clientWidth || 560) - 8))); else aiuDraw(md); });  // 2.1.1 (#326)
  if (cur === 'account' && S.me) { tfaDraw(md); tokDraw(md); apwDraw(md); }
  if (S.me) { tfaWire(md); tokWire(md); apwWire(md); }
  if (S.me?.is_admin) oidcWire(md);
  if (S.me?.is_admin) { aaWire(md); bkWire(md); orphWire(md); }
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
    const opt = (id, n) => ids.includes(id) ? '' : `<option value="${esc(id)}">${esc(n)}</option>`;
    const grp = (n, o) => o ? `<optgroup label="${tr(n)}">${o}</optgroup>` : '';
    $('#s-tabadd', md).innerHTML = `<option value="">${tr('+ Add tab …')}</option>` +
      grp(N_('Sections'), MODS.filter(([m]) => m === 'tasks' || feat(m)).map(([m, , n]) => opt('m:' + m, tr(n))).join('')) +
      grp(N_('Smart lists'), SMART_TABS.filter(k => k !== 'assigned' || collab()).map(k => opt('s:' + k, tr(SMART[k].name))).join('')) +
      grp(N_('Lists'), S.lists.filter(l => !l.is_inbox && !l.archived).map(l => opt('l:' + l.id, listName(l.name))).join('')) +
      grp(N_('Filters'), S.filters.map(f => opt('f:' + f.id, f.name)).join('')) +
      grp(N_('Folders'), folderNames().map(f => opt('folder:' + f, fDisp(f))).join('')) +
      grp(N_('Tags'), Object.keys(counts().tags).sort((a, b) => a.localeCompare(b, 'de')).map(t => opt('tag:' + t, '#' + t)).join('')) +
      grp(N_('Other'), opt('home', tr('Start|home')) + (teamOn() ? opt('team', tr('Team chat')) : '') + (collab() ? opt('news', tr('News')) : '') + (feat('agents') && agentsOn() ? opt('agents', tr('Agents')) : '') + (overviewOn() ? opt('overview', tr('Project status')) : '') + (feat('stats') ? opt('stats', tr('Statistics')) : '') + (timeOn() ? opt('time', tr('Time tracking')) : '') + opt('search', tr('Search')) + opt('lists', tr('Lists')) + opt('settings', tr('Settings')));
  };
  md._tabDraw = tabDraw;
  // 2.25.0 (UX-03): the sidebar: groups up / down, an eye per group, check boxes for the entries of Plan and Views
  const sideDraw = () => {
    const box = $('#s-sidebar', md); if (!box) return;
    const p = sidePref(), ord = sideGroupOrder();
    const ent = g => (g === 'focus' ? SIDE_PLAN : g === 'views' ? sideViewEntries() : []).map(([x, n]) => `<label class="chkl sidee"><input type="checkbox" data-side-e="${x}" ${p.hidden.includes('e:' + x) ? '' : 'checked'}> ${esc(tr(n))}</label>`).join('');
    box.innerHTML = ord.map((g, i) => { const n = tr(SIDE_NAMES[g]), shown = !p.hidden.includes('g:' + g), e = shown ? ent(g) : '';
      return `<div class="navrow sidegrp ${shown ? '' : 'off'}" data-sideg="${g}">${g === 'lists' ? `<span class="iconbtn sideye" aria-hidden="true">${ic('list', 's')}</span>` : `<button class="iconbtn sideye" data-side-eye aria-pressed="${shown}" title="${esc(shown ? tr('Hide {0}', n) : tr('Show {0}', n))}" aria-label="${esc(tr('Show {0}', n))}">${ic(shown ? 'eye' : 'eyeoff', 's')}</button>`}<span>${esc(n)}</span><button class="iconbtn" data-smove="-1" ${i ? '' : 'disabled'} title="${tr('move up')}" aria-label="${esc(tr('Move {0} up', n))}">${ic('chev', 's up')}</button><button class="iconbtn" data-smove="1" ${i < ord.length - 1 ? '' : 'disabled'} title="${tr('move down')}" aria-label="${esc(tr('Move {0} down', n))}">${ic('chev', 's')}</button></div>${e ? `<div class="sideents">${e}</div>` : ''}`; }).join('');
  };
  md._sideDraw = sideDraw;
  const sideSave = o => setApply({sidebar: o ? JSON.stringify(o) : ''}, tr('Sidebar')).then(() => { sideDraw(); renderSide(); });
  sideDraw();
  md.addEventListener('change', e => {
    const x = e.target.dataset?.sideE; if (!x) return;
    const p = sidePref(), h = new Set(p.hidden); e.target.checked ? h.delete('e:' + x) : h.add('e:' + x);
    sideSave({order: p.order, hidden: [...h]});
  });
  const tabApply = ids => { if (ids) LS.set('tabbar', ids); else LS.set('tabbar', null); tabDraw(); renderTabs(); };
  const tabSet = ids => setLocal(tr('Tab bar'), () => LS.get('tabbar', null), tabApply, ids);
  tabDraw();
  $('#s-tabadd', md).addEventListener('change', e => { if (e.target.value) tabSet([...tabIds(), e.target.value]); });
  if (S.me) accountWire(md);
  mailWire(md);  // 2.17.0 (#443)
  md.addEventListener('click', async e => {
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
    if (b.dataset.look) {
      const k = b.dataset.look, v = b.dataset.v, n = {theme: N_('Color scheme'), density: N_('Density'), densitySide: N_('Density'), densityRows: N_('Density'), fsize: N_('Font size'), font: N_('Font'), accent: N_('Accent color')}[k];
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
    if (b.dataset.m === 'go-share') { $('.snav [data-sec="integr"]', md)?.click(); setTimeout(() => $('#s-share-h', md)?.scrollIntoView?.({block: 'start'}), 50); return; }  // 2.7.0 (#405 S3)
    if (b.dataset.m === 'go-modules') { $('.snav [data-sec="modules"]', md)?.click(); setTimeout(() => $('[data-pane="modules"] [data-modrow="agents"]', md)?.scrollIntoView?.({block: 'center'}), 50); return; }  // 2.6.0 (K09)
    if (b.dataset.m === 'cele-try') { celebrate('today', {force: true}); return; }
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
      if (a === 'drop-copy-tok' && !i.dataset.real) { try { const j = await api('GET', '/api/me'); i.value = j.drop_token || ''; i.type = 'text'; i.dataset.real = '1'; } catch { return; } }
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
  return md;
}
// ---- Settings > Data > Import (package C): pick the source, choose a file, preview (dry run on the server), import, undo
const IMP_SRC = [['todoist', 'Todoist'], ['trello', 'Trello'], ['asana', 'Asana'], ['mstodo', 'Microsoft To Do'],
  ['ics', N_('ICS / VTODO (Apple Reminders, Nextcloud, Thunderbird …)')], ['ticktick', 'TickTick']];
const IMP_ACCEPT = {todoist: '.csv,.zip,.json,text/csv,application/zip,application/json', trello: '.json,application/json', asana: '.csv,text/csv',
  mstodo: '.csv,.ics,text/csv,text/calendar', ics: '.ics,.ical,.ifb,text/calendar', ticktick: '.csv,text/csv'};
function impHelp(src) {
  return {
    todoist: tr('<b>Todoist:</b> open the project > … > Export as a CSV file (one file per project), or Settings > Backups > download a backup (a ZIP with every project). Sections, subtasks, @labels, priorities, dates (English and German date texts, also recurring ones), durations and comments are taken over; attachments stay links. The list is named after the file.'),
    trello: tr('<b>Trello:</b> open the board > Menu > Print, export and share > Export as JSON. Lists become sections of one list (or one list each, see below), cards tasks, checklists subtasks, labels tags, due dates and “complete” are kept; comments and attachment links go into the notes. Archived cards are skipped unless you choose otherwise.'),
    asana: tr('<b>Asana:</b> open the project > arrow next to its name > Export / Print > CSV. Sections, subtasks, tags, start and due dates and completion are taken over, other fields go into the notes. An assignee is assigned when they are a member of the target list (same e-mail or name), otherwise their name goes into the notes.'),
    mstodo: tr('<b>Microsoft To Do</b> has no export of its own. Recommended: classic Outlook for Windows > File > Open & Export > Import/Export > Export to a file > Comma Separated Values > your Tasks folder (Outlook for Mac: File > Export > Tasks). CSV files of export tools (columns such as Title, List, Status, Importance, Due) and ICS files work too. English and German Outlook columns are recognized, also in Windows-1252.'),
    ics: tr('<b>ICS files with tasks (VTODO):</b> Nextcloud Tasks (calendar > … > Export), Thunderbird (right-click the calendar > Export), Apple Reminders via an export app or a CalDAV server, Tasks.org via its CalDAV account. Each calendar becomes a list; subtasks, repetitions, reminders, categories (tags), priorities and completion are taken over.'),
    ticktick: tr('<b>TickTick:</b> Settings > Account > Generate backup (CSV). Imported directly, without a preview.'),
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
    const ls = j.lists.map(l => `<div class="mrow"><span class="n">${esc(l.name)}</span><span class="muted">${trn('{0} task', '{0} tasks', l.tasks)}${l.skipped ? ' · ' + tr('{0} skipped', l.skipped) : ''}${l.sections ? ' · ' + trn('{0} new section', '{0} new sections', l.sections) : ''} · ${l.existing ? tr('existing list') : tr('new list')}</span></div>`).join('');
    const opts = j.dry_run ? sel('s-imp-target', tr('Into'), [['new', tr('New lists (an own list with the same name is reused)')], ...lists().map(l => [String(l.id), lname(l)])], I.opts.target || 'new')
      + (I.src === 'trello' ? sel('s-imp-mode', tr('Trello lists'), [['sections', tr('as sections of one list')], ['lists', tr('as separate lists (in a folder)')]], I.opts.mode || 'sections')
        + sel('s-imp-archived', tr('Archived cards'), [['skip', tr('skip')], ['done', tr('import as completed')]], I.opts.archived || 'skip') : '')
      + sel('s-imp-completed', tr('Completed tasks'), [['import', tr('import as completed')], ['skip', tr('skip')]], I.opts.completed || 'import')
      + (I.src === 'todoist' ? sel('s-imp-priority_scale', tr('Todoist priorities'), [['auto', tr('detect automatically')], ['1', tr('1 = p1 (highest)')], ['4', tr('4 = p1 (highest)')]], I.opts.priority_scale || 'auto') : '')
      + (j.lists.length === 1 && !(I.opts.target && I.opts.target !== 'new') ? `<div class="row"><label for="s-imp-name">${tr('List name')}</label><input id="s-imp-name" data-io="list_name" maxlength="200" value="${esc(I.opts.list_name ?? j.lists[0].name)}"></div>` : '') : '';
    const sm = j.dry_run && j.samples.length ? `<div class="imptab"><div class="muted">${tr('Examples')}</div>${j.samples.map(t => `<div class="impr${t.subtask ? ' sub' : ''}"><span class="n">${esc(t.title)}</span><span class="muted">${esc([t.section, t.due ? fmtDayAbs(t.due) + (t.due_time ? ' ' + t.due_time : '') : '', t.repeat ? repeatLabel(t.repeat) : '', t.status ? tr('Done') : ''].filter(Boolean).join(' · '))}</span>${prio(t.priority)}${t.tags.map(g => `<span class="tag">#${esc(g)}</span>`).join('')}</div>`).join('')}</div>` : '';
    const btns = j.dry_run
      ? `<div class="row"><button class="btn sm pri" data-imp="go" ${n ? '' : 'disabled'}>${ic('download', 's')} ${trn('Import {0} task', 'Import {0} tasks', n)}</button><button class="btn sm" data-imp="cancel">${tr('Cancel')}</button></div>`
      : (j.import_id ? `<div class="row"><button class="btn sm" data-imp="undo" data-id="${+j.import_id}">${tr('Undo this import')}</button><span class="muted">${tr('possible for 24 hours')}</span></div>` : '');
    out.innerHTML = `<div class="impbox" role="status"><div class="imphead"><b>${esc(head)}</b></div>${ls}${warns(j.warnings)}${opts}${sm}${btns}</div>`;
  }
  async function preview() {
    if (!I.file) return;
    out.innerHTML = `<div class="muted mhint">${tr('Reading the file…')}</div>`;
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
      const fd = new FormData(); fd.append('file', f);
      const j = await api('POST', '/api/import/ticktick', fd);
      toast(tr('Import: {0} tasks, {1} new lists', j.tasks, j.lists) + (j.skipped ? tr(', {0} already there', j.skipped) : ''));
      inp.value = ''; await load(); render(); return;
    }
    I.file = f; I.opts = {}; await preview();
  });
  out.addEventListener('change', e => {
    const k = e.target.dataset.io; if (!k) return;
    I.opts[k] = e.target.value;
    if (k === 'target' && e.target.value !== 'new') delete I.opts.list_name;
    if (k !== 'list_name') preview();
  });
  const undo = async id => {
    if (!await askConfirm(tr('Remove everything this import created?'), tr('Tasks you changed since then are removed too; tasks others added below them stay.'), {ok: tr('Remove'), danger: true})) return;
    const j = await api('POST', `/api/imports/${id}/undo`);
    toast(trn('Import undone: {0} task removed', 'Import undone: {0} tasks removed', j.tasks));
    out.innerHTML = ''; await load(); render(); hist();
  };
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-imp]'); if (!b || !md.contains(b)) return;
    const a = b.dataset.imp;
    if (a === 'cancel') { out.innerHTML = ''; I.file = null; inp.value = ''; return; }
    if (a === 'undo') { await undo(+b.dataset.id); return; }
    if (a === 'go') {
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
function instanceHtml(chk, hint) {
  const a = S.about || {};
  return `<h4 id="s-instance-h">${tr('Whole server')}</h4>
    ${hint(tr('Apply to every user at once. Nothing is deleted: switched back on, everything is there again.') + ' ' + tr('Collaboration and time tracking for everyone: Settings > Modules.'))}
    <div class="featgrid">
      <label class="wide"><input type="checkbox" id="s-publinks" ${a.public_links !== false && a.public_links_env !== false ? 'checked' : ''} ${a.public_links_env === false ? 'disabled' : ''}><span>${tr('Public links to lists')}<small class="muted">${a.public_links_env === false ? `<span title="KALMIDO_PUBLIC_LINKS=0">${tr('Switched off by the server operator.')}</span>` : tr('List owners can share a list with people without an account through a secret link (view only or tick off). Off: every public link stops working at once; nothing is deleted.')}</small></span></label>
      <label class="wide"><input type="checkbox" id="s-updcheck" ${a.update_check !== false && a.update_env !== false ? 'checked' : ''} ${a.update_env === false ? 'disabled' : ''}><span>${tr('Check daily for a new version')}<small class="muted">${a.update_env === false ? `<span title="KALMIDO_UPDATE_CHECK=0">${tr('Switched off by the server operator.')}</span>` : tr('The server asks GitHub once a day for the latest release; nothing is installed automatically and the browser never contacts GitHub. Result under Help.')}</small></span></label>
    </div>
    ${S.timeAll !== false ? `<h4 id="s-dayh-h">${tr('Time sums')}</h4>
    <div class="row"><label for="s-dayh">${tr('Hours per day')}</label><input id="s-dayh" inputmode="decimal" class="numin" value="${esc(fmtNum(a.time_day_h || S.timeDayH || 8, 2))}"><span class="muted">${tr('h per working day / shift')}</span></div>
    ${hint(tr('Project lists show their tracked time in hours and in days of this length. A list can set its own value (list dialog); it then applies to everyone in that list.'))}` : ''}
    ${a.cal_on || S.webhooks?.enabled ? `<details class="sdev"><summary>${ic('key', 's')}${tr('Advanced · for developers')}</summary><h4 id="s-calhosts-h">${tr('Allowed internal hosts')}</h4>
    ${hint(tr('Calendar subscriptions and webhooks may only reach public addresses. List servers in your own network here (host or host:port, separated by commas), for example your own Nextcloud, Radicale or n8n; every user can then use them. Webhooks may use http:// only for these hosts.') + (a.cal_allow_env ? ' ' + esc(tr('Also allowed by the server configuration: {0}', a.cal_allow_env)) : ''))}
    <div class="row"><textarea id="s-calhosts" rows="2" spellcheck="false" autocapitalize="off" aria-labelledby="s-calhosts-h" placeholder="nextcloud.home.arpa, 10.0.0.20:5232">${esc(a.cal_allow_hosts || '')}</textarea></div>
    </details>` : ''}`;
}
// Settings > Users > Whole server > Admin alerts: operational warnings to the admins via ntfy (server side, own
// "Save"; loaded when the pane opens). Recent alerts below, with "Clear".
// ---- 2.1.0 (#180): Paperless connections. Tokens are write-only: the page only ever learns "set" / "not set".
const plTokenIn = (id, ph) => `<input type="password" id="${id}" autocomplete="off" spellcheck="false" placeholder="${esc(ph || tr('API token'))}" maxlength="400">`;
function plcRowHtml(c) {
  const kind = c.kind === 'legacy' ? tr('set up on the server') : c.kind === 'server' ? tr('set up by an admin · your own token') : tr('personal · only you');
  const tok = c.kind === 'legacy' ? '' : c.token_set ? (c.token_ok ? `<span class="pltok ok">•••• ${tr('set')}</span>` : `<span class="pltok bad">${tr('token unreadable, enter it again')}</span>`) : `<span class="pltok">${tr('no token yet')}</span>`;
  return `<div class="mrow plc" data-plc="${c.id}">${ic('archive', 's')}<span class="n"><b>${esc(c.name)}</b><small class="muted">${esc(c.url)} · ${esc(kind)}</small>${tok}</span>
    ${c.kind === 'legacy' ? '' : `<button class="btn sm" data-plc-act="token">${ic('key', 's')} ${c.token_set ? tr('Replace token') : tr('Enter token')}</button>`}
    ${c.usable ? `<button class="iconbtn" data-plc-act="test" title="${esc(tr('Test the connection'))}" aria-label="${esc(tr('Test the connection'))}">${ic('check', 's')}</button>` : ''}
    ${c.kind !== 'legacy' && c.token_set ? `<button class="iconbtn" data-plc-act="untoken" title="${esc(tr('Remove my token'))}" aria-label="${esc(tr('Remove my token'))}">${ic('x', 's')}</button>` : ''}
    ${c.kind === 'personal' ? `<button class="iconbtn" data-plc-act="del" title="${esc(tr('Delete connection'))}" aria-label="${esc(tr('Delete connection'))}">${ic('trash', 's')}</button>` : ''}</div>`;
}
async function plcDraw(md) {
  const box = $('#s-plc', md); if (!box) return;
  let j;
  try { j = await api('GET', '/api/paperless/conns'); } catch { box.innerHTML = ''; return; }
  S.paperless = {...S.paperless, conns: j.conns, key: j.key, enabled: j.conns.some(c => c.usable)};
  box.innerHTML = (j.conns.length ? j.conns.map(plcRowHtml).join('') : `<div class="muted mhint">${tr('No Paperless connection yet.')}</div>`) +
    (j.key ? `<details class="plnew"><summary>${ic('plus', 's')} ${tr('Add my own connection')}</summary>
      <div class="row"><label for="plc-name">${tr('Name')}</label><input id="plc-name" maxlength="60" placeholder="${esc(tr('e.g. Private'))}"></div>
      <div class="row"><label for="plc-url">${tr('Address')}</label><input id="plc-url" type="url" inputmode="url" placeholder="https://paperless.example.com"></div>
      <div class="row"><label for="plc-tok">${tr('API token')}</label>${plTokenIn('plc-tok')}</div>
      <div class="shint keep">${tr('In Paperless: your profile (top right) > My Profile > API Auth Token. The token is stored encrypted and never shown again; only you can use this connection.')}</div>
      <div class="row"><label></label><button class="btn sm pri" data-plc-act="add">${ic('plus', 's')} ${tr('Add')}</button></div></details>`
      : `<div class="shint keep">${tr('Tokens cannot be stored on this server yet: the server operator has to set a secret key first (KALMIDO_SECRET_KEY, see the installation guide).')}</div>`);
}
function plcWire(md) {
  if (!$('#s-plc', md)) return;
  plcDraw(md);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-plc-act]'); if (!b || !b.closest('#s-plc')) return;
    const act = b.dataset.plcAct, id = +b.closest('[data-plc]')?.dataset.plc;
    b.disabled = true;
    try {
      if (act === 'add') {
        const body = {name: $('#plc-name', md).value.trim(), url: $('#plc-url', md).value.trim(), token: $('#plc-tok', md).value.trim()};
        if (!body.name || !body.url || !body.token) { toast(tr('Name, address and token are needed')); return; }
        await api('POST', '/api/paperless/conns', body); toast(tr('Connection added'));
      } else if (act === 'token') {
        const t = await askPrompt(tr('Your API token for this connection'), '', {input: {type: 'password', max: 400}, ok: tr('Save')}); if (!t) return;
        await api('PATCH', `/api/paperless/conns/${id}`, {token: t.trim()}); toast(tr('Token saved'));
      } else if (act === 'untoken') {
        if (!await askConfirm(tr('Remove your token?'), tr('You can no longer search or link documents of this connection until you enter it again.'), {ok: tr('Remove')})) return;
        await api('DELETE', `/api/paperless/conns/${id}/token`);
      } else if (act === 'del') {
        if (!await askConfirm(tr('Delete this connection?'), tr('Documents linked through it stay on the tasks, without title.'), {ok: tr('Delete'), danger: true})) return;
        await api('DELETE', `/api/paperless/conns/${id}`);
      } else if (act === 'test') {
        const j = await api('POST', `/api/paperless/conns/${id}/test`); toast(j.ok ? tr('Connection works') : j.error || tr('Error'), null, 5000); return;
      }
      await plcDraw(md); render(); if (S.sel) renderDetail();
    } catch { /* api() showed it */ } finally { b.disabled = false; }
  });
}
// admins: server connections (name + address + who may use it); never a token, never anyone's personal connection
const plaHtml = () => `<h4 id="s-pla-h">${tr('Paperless connections')}</h4><div id="s-pla"><div class="muted mhint">${tr('Loading…')}</div></div>`;
async function plaDraw(md) {
  const box = $('#s-pla', md); if (!box) return;
  let j, users;
  try { [j, users] = await Promise.all([api('GET', '/api/admin/paperless'), api('GET', '/api/users').then(x => x.users.filter(u => !u.disabled && !u.agent))]); } catch { box.innerHTML = ''; return; }
  const ulist = (sel, cid) => `<div class="plusers">${users.map(u => `<label class="chkl"><input type="checkbox" data-pla-user="${u.id}" ${cid != null ? `data-pla-conn="${cid}"` : ''} ${sel.includes(u.id) ? 'checked' : ''}> ${esc(u.display_name)}</label>`).join('')}</div>`;
  box.innerHTML = `<div class="shint">${tr('A connection names a Paperless server; every user you allow enters their own API token for it (Settings > Integrations), so Paperless decides what each one sees. Users can also add personal connections, which you never see.')}</div>
    ${j.key ? '' : `<div class="shint warn">${j.key_problem === 'invalid' ? tr('KALMIDO_SECRET_KEY is invalid (it must be 32 random bytes, base64).') : tr('Set KALMIDO_SECRET_KEY (32 random bytes, base64, e.g. openssl rand -base64 32) in the environment and restart: without it no token can be stored. Keep a copy: if it is lost, everyone has to enter their tokens again.')}</div>`}
    ${j.legacy.configured ? `<div class="mrow plc">${ic('archive', 's')}<span class="n"><b>Paperless</b><small class="muted">${esc(j.legacy.url)} · ${tr('token in the environment, for users with “Paperless access”')}</small></span></div>` : ''}
    ${j.servers.map(c => `<details class="plsrv" data-pla="${c.id}"><summary>${ic('archive', 's')}<b>${esc(c.name)}</b> <span class="muted">${esc(c.url)} · ${trn('{0} user', '{0} users', c.users.length)} · ${trn('{0} token set', '{0} tokens set', c.tokens)}</span></summary>
      <div class="row"><label>${tr('Name')}</label><input data-pla-f="name" maxlength="60" value="${esc(c.name)}"></div>
      <div class="row"><label>${tr('Address')}</label><input data-pla-f="url" type="url" value="${esc(c.url)}"></div>
      <div class="shint keep">${tr('A new address removes the tokens stored for it.')}</div>
      <div class="row"><label>${tr('Who may use it')}</label>${ulist(c.users, c.id)}</div>
      <div class="row"><label></label><button class="btn sm danger" data-pla-act="del">${ic('trash', 's')} ${tr('Remove connection')}</button></div></details>`).join('')}
    <details class="plnew"><summary>${ic('plus', 's')} ${tr('New server connection')}</summary>
      <div class="row"><label for="pla-name">${tr('Name')}</label><input id="pla-name" maxlength="60" placeholder="${esc(tr('e.g. Office'))}"></div>
      <div class="row"><label for="pla-url">${tr('Address')}</label><input id="pla-url" type="url" inputmode="url" placeholder="https://paperless.example.com"></div>
      <div class="row"><label>${tr('Who may use it')}</label>${ulist([], null)}</div>
      <div class="row"><label></label><button class="btn sm pri" data-pla-act="add">${ic('plus', 's')} ${tr('Add')}</button></div></details>`;
}
function plaWire(md) {
  if (!$('#s-pla', md)) return;
  plaDraw(md);
  const users = el => [...el.querySelectorAll('[data-pla-user]:checked')].map(x => +x.dataset.plaUser);
  md.addEventListener('change', async e => {
    const d = e.target.closest('[data-pla]'); if (!d || !d.closest('#s-pla')) return;
    const id = +d.dataset.pla, f = e.target.dataset.plaF;
    try {
      if (f) await api('PATCH', `/api/admin/paperless/${id}`, {[f]: e.target.value.trim()});
      else if (e.target.dataset.plaUser) await api('PATCH', `/api/admin/paperless/${id}`, {users: users(d)});
      setSaved(null);
    } catch { plaDraw(md); }
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-pla-act]'); if (!b || !b.closest('#s-pla')) return;
    b.disabled = true;
    try {
      if (b.dataset.plaAct === 'add') {
        const box = b.closest('.plnew');
        await api('POST', '/api/admin/paperless', {name: $('#pla-name', md).value.trim(), url: $('#pla-url', md).value.trim(), users: users(box)});
      } else {
        const id = +b.closest('[data-pla]').dataset.pla;
        if (!await askConfirm(tr('Remove this Paperless connection?'), tr('The users lose it and their tokens for it are deleted. Linked documents stay on the tasks, without title.'), {ok: tr('Remove'), danger: true})) return;
        await api('DELETE', `/api/admin/paperless/${id}`);
      }
      await plaDraw(md); await load(); render();
    } catch { /* api() showed it */ } finally { b.disabled = false; }
  });
}
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
  if (st.total || qc.at) h += hint([st.total ? tr('Data volume: {0} free ({1} %).', st.free >= 1e9 ? (st.free / 1e9).toFixed(1) + ' GB' : Math.round(st.free / 1e6) + ' MB', st.pct) : '', qc.at ? (qc.ok ? tr('Database check ok ({0}).', aaWhen(qc.at)) : tr('Database check FAILED ({0}).', aaWhen(qc.at))) : ''].filter(Boolean).join(' '));
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
const ABOUT_LINKS = [['https://kalmido.com', N_('Website'), 'link'], ['https://github.com/Gegenschuss/kalmido', N_('Source code on GitHub'), 'file'], ['https://github.com/Gegenschuss/kalmido/issues', N_('Report a problem'), 'alert']];
const openExt = u => { const w = window.open(u, '_blank', 'noopener,noreferrer'); if (w) w.opener = null; };
// 2.27.0 (#968): the code in this window (index.html) next to the server's version; differ they: marked + "Reload"
function aboutVerRows(a) {
  const srv = S.serverVer || a.version || '', app = APP_VER || '';
  if (!app) return '';
  const off = srv && app !== srv;
  return `<div class="row aboutapp${off ? ' off' : ''}"><label>${tr('App in this window')}</label><span>v${esc(app)}${off ? ` · <b>${esc(tr('Server: v{0}', srv))}</b> <button type="button" class="btn sm pri" data-nv="go">${esc(tr('Reload'))}</button>` : ` · <span class="muted">${esc(tr('up to date'))}</span>`}</span></div>`;
}
// Settings > Help: version, and for admins the result of the daily update check (server side, never automatic)
function aboutHtml(chk, hint) {
  const a = S.about || {};
  let h = `<h4 id="s-about-h">${tr('About')}</h4><div class="row"><label>${tr('Version')}</label><span class="aboutver">Kalmido v${esc(a.version || '?')}</span></div>${aboutVerRows(a)}
    <div class="row aboutcopy"><label>©</label><span class="muted">2026 Gegenschuss Doberenz Enders Grund eGbR · AGPL-3.0</span></div>
    <div class="row aboutlinks"><label></label>${ABOUT_LINKS.map(([u, n, i]) => `<a class="btn sm" href="${u}" target="_blank" rel="noopener noreferrer">${ic(i, 's')} ${tr(n)}</a>`).join('')}</div>`;
  if (!S.me?.is_admin) return h;
  if (a.available) {
    h += `<div class="shint updline"><b>${tr('v{0} installed — v{1} available', esc(a.version), esc(a.latest))}</b>${a.url ? ` · <a href="${esc(a.url)}" target="_blank" rel="noopener">${tr('Release notes')}</a>` : ''}</div>
      <div class="shelp">${tr('To update, run <code>~/kalmido/update.sh</code> (installed with the installer; it backs up the database first), or in the folder with docker-compose.yml: <code>docker compose pull && docker compose up -d</code> (prebuilt image) or <code>git pull && docker compose up -d --build</code> (built from source).')}</div>`;
  } else if (a.update_env && a.update_check && a.checked_at) {
    const when = new Date(a.checked_at).toLocaleString(I18N.code || 'en');
    h += hint(a.error ? tr('The last update check failed ({0}); it tries again later.', esc(a.error)) : a.latest ? tr('Up to date (checked {0}).', esc(when)) : tr('Checked {0}.', esc(when)));
  }
  if (!a.update_env || !a.update_check) h += hintK(tr('The update check is off (Settings > Administration).'));
  return h;
}
const ADMIN_SW = {'s-collaball': ['collab_all', N_('Collaboration for everyone')], 's-timeall': ['time_all', N_('Time tracking for everyone')], 's-updcheck': ['update_check', N_('Check daily for a new version')],
  's-2fareq': ['twofa_required', N_('Require two-factor authentication')], 's-pklogin': ['passkey_login', N_('Passkey login')], 's-oidcauto': ['oidc_autocreate', N_('Create accounts on first OIDC login')], 's-publinks': ['public_links', N_('Public links to lists')]};
async function adminSwitch(md, el, fromHist) {
  const on = el.checked;
  const ask = async (t, b, ok) => fromHist || await askConfirm(t, b, {ok, danger: true});
  if (el.id === 's-collaball' && !on && !await ask(tr('Turn collaboration off for everyone?'), tr('Shared lists are then only visible to their owner; nothing is deleted.'), tr('Turn off'))) { el.checked = true; return; }
  if (el.id === 's-timeall' && !on && !await ask(tr('Turn time tracking off for everyone?'), tr('Running timers are stopped now; entries are kept.'), tr('Turn off'))) { el.checked = true; return; }
  if (el.id === 's-2fareq' && on && !await ask(tr('Require two-factor authentication?'), tr('Everyone who logs in with a password must set it up at the next login (sessions that are open now stay open).'), tr('Require'))) { el.checked = false; return; }
  if (el.id === 's-publinks' && !on && !await ask(tr('Turn public links off for everyone?'), tr('Every public link stops working at once; nothing is deleted.'), tr('Turn off'))) { el.checked = true; return; }
  const key = ADMIN_SW[el.id][0];
  try {
    const j = await api('PATCH', '/api/admin/settings', {[key]: on});
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
    const sec = LS.get('settingsSec', 'modules'), sc = $('.spanes', md)?.scrollTop || 0; md._noflush = true; md.remove();
    const n = settingsModal(sec), p = $('.spanes', n); if (p) p.scrollTop = sc;
    if (!fromHist) setSaved(HIST.undo[HIST.undo.length - 1]);
  }
}
// calendar subscription (Settings > Integrations): the secret feed link, copy / new link / off
async function icalDraw(md, j) {
  const box = $('#s-ical', md); if (!box) return;
  if (!j) { try { j = await api('GET', '/api/ical'); } catch { box.innerHTML = `<div class="muted mhint">${tr('Only available online.')}</div>`; return; } }
  if (!j.url) { box.innerHTML = `<div class="row"><button class="btn sm pri" data-m="ical-create">${ic('cal', 's')} ${tr('Create subscription link')}</button></div>`; return; }
  box.innerHTML = `<div class="row icalrow"><input id="s-icalurl" readonly value="${esc(j.url)}" aria-label="${tr('Subscription link')}"><button class="btn sm pri" data-m="ical-copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <div class="row"><a class="btn sm" href="${esc(j.url.replace(/^https?:/, 'webcal:'))}">${ic('cal', 's')} ${tr('Open in calendar app')}</a><button class="btn sm" data-m="ical-rotate">${ic('key', 's')} ${tr('New link')}</button><button class="btn sm danger" data-m="ical-off">${tr('Turn off')}</button></div>`;
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
