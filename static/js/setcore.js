/* Kalmido web client: the parts of the settings the app needs from the start (2.53.0, #1410): Web Push on this device,
   the app badge, the service worker's messages, the list of the settings sections and modules, the project links.
   The settings dialog itself (settings.js) is loaded on demand (lazyload.js).
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
const SET_SECS = [['account', 'user', N_('Account')], ['org', 'building', N_('Organisation')], ['general', 'sliders', N_('General')], ['look', 'palette', N_('Appearance')], ['modules', 'grid', N_('Modules')],
  ['notify', 'bell', N_('Notifications')], ['integr', 'link', N_('Integrations')], ['ai', 'bot', N_('Agents')], ['assistant', 'sparkle', N_('Assistant')], ['data', 'download', N_('Data')], ['users', 'users', N_('Administration')], ['help', 'help', N_('Help')]];
const MOD_GROUPS = [[N_('Views'), ['cal', 'timeline', 'kanban', 'matrix']], [N_('Calendar and people'), ['events']], [N_('For you'), ['habits', 'comments']],
  [N_('Projects and team'), ['collab', 'progress', 'deps', 'fields', 'agents', 'workload', 'dispo', 'forms', 'wiki', 'sheets']], [N_('Areas|nav'), ['a:office', 'a:ablage', 'a:time', 'a:review', 'a:life']]];  // 2.48.0 (#1207): + the file store
const aiPaneOn = () => !!S.me && (feat('agents') || (!!S.me.is_admin && (S.agents || []).length > 0));
const ABOUT_LINKS = [['https://kalmido.com', N_('Website'), 'link'], ['https://github.com/Gegenschuss/kalmido', N_('Source code on GitHub'), 'file'], ['https://github.com/Gegenschuss/kalmido/issues', N_('Report a problem'), 'alert']];
const openExt = u => { const w = window.open(u, '_blank', 'noopener,noreferrer'); if (w) w.opener = null; };
