// tasks service worker: cache the app shell so the PWA opens offline;
// API calls always go to the network (data must be live). Language files: de.json is precached,
// any other static/i18n/<code>.json lands in the cache via the network-first handler on first use
// (the client also keeps the active one in localStorage as a last offline fallback).
const CACHE = 'tasks-shell-v74';
const SHELL = ['/', '/manifest.json', '/static/app.css', '/static/i18n.js', '/static/i18n/de.json', '/static/app.js', '/static/icon-192.png', '/static/icon-512.png',
  '/static/icon.svg', '/static/badge-96.png', '/static/fonts/Geist-Variable.woff2', '/static/fonts/GeistMono-Variable.woff2', '/static/sloth-quips.json',
  // Atkinson Hyperlegible (Appearance > Font): regular + bold precached (35 KB), the italics are cached on first use
  '/static/fonts/AtkinsonHyperlegible-Regular.woff2', '/static/fonts/AtkinsonHyperlegible-Bold.woff2'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
// Android share sheet (share_target POST): keep the shared files in a cache and open the app,
// which then creates the task + uploads with the normal (login) session.
async function handleShare(req) {
  try {
    const fd = await req.formData();
    const cache = await caches.open('tasks-share');
    for (const k of await cache.keys()) await cache.delete(k);
    const files = [...fd.values()].filter(f => typeof f !== 'string' && f.size);  // any field name
    const meta = {title: fd.get('title') || '', text: fd.get('text') || '', url: fd.get('url') || '', files: []};
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      await cache.put(`/share-inbox/${i}`, new Response(f, {headers: {'Content-Type': f.type || 'application/octet-stream'}}));
      meta.files.push({name: f.name || `datei-${i + 1}`, type: f.type || '', size: f.size});
    }
    await cache.put('/share-inbox/meta', new Response(JSON.stringify(meta), {headers: {'Content-Type': 'application/json'}}));
    return Response.redirect('/?share=1', 303);
  } catch (e) {
    return Response.redirect('/?share=err', 303);
  }
}
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method === 'POST' && url.pathname === '/share') { e.respondWith(handleShare(e.request)); return; }
  // /s/ = public list links: never cached (no-store pages of one list; the service worker stays out of them)
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/') || url.pathname.startsWith('/s/')) return;
  // network first, fall back to cache (a new deploy shows up immediately when online)
  e.respondWith(fetch(e.request).then(r => { if (r.ok && !r.redirected && r.type === 'basic') { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); } return r; }).catch(() => caches.match(e.request, {ignoreSearch: url.pathname === '/'})
    // 2.4.0 (#187): the quick capture page is the app shell too (offline: the capture goes to the outbox)
    .then(r => r || (url.pathname === '/capture' ? caches.match('/', {ignoreSearch: true}) : r))));
});

// ---- Web Push: the server sends {title, body, url ('/#t/12'), tag, prio, task, due, actions: [{action, title, url}]}
// (end-to-end encrypted, see app.py "Web Push"). Priority 5 stays on screen until dismissed. A push with the
// same tag (same task, the focus timer, the digest) replaces the previous notification.
const SAME = u => { try { const x = new URL(u, self.location.origin); return x.origin === self.location.origin ? x.pathname + x.search + x.hash : '/'; } catch { return '/'; } };
function pushOptions(d) {
  const o = {body: d.body || '', icon: '/static/icon-192.png', badge: '/static/badge-96.png', lang: d.lang || undefined,
    data: {url: SAME(d.url || '/'), task: d.task || null, due: d.due || null, actions: {}}, timestamp: d.ts || Date.now()};
  if (d.tag) { o.tag = d.tag; o.renotify = true; }
  if (+d.prio >= 5) o.requireInteraction = true;
  // 2.7.0 (#413): nags carry three buttons (Done, Stop reminding, Snooze); as many as the platform shows (at least 2)
  const max = Math.max(2, Math.min(3, (self.Notification && +self.Notification.maxActions) || 2));
  const acts = Array.isArray(d.actions) ? d.actions.slice(0, max) : [];
  if (acts.length) {
    o.actions = acts.map(a => ({action: String(a.action), title: String(a.title)}));
    for (const a of acts) o.data.actions[a.action] = SAME(a.url || '/');
  }
  return o;
}
// 2.0.5: notifications handled on another device (task completed / opened, News read) are closed by tag: a push
// {type: 'dismiss', tags} only closes them (never sent to iOS), a normal push may carry "dismiss": [tags] as well
async function closeTags(tags) {
  if (!Array.isArray(tags) || !tags.length) return 0;
  const want = new Set(tags.map(String));
  let n = 0;
  for (const x of await self.registration.getNotifications()) if (x.tag && want.has(x.tag)) { x.close(); n++; }
  return n;
}
self.addEventListener('push', e => {
  let d;
  try { d = e.data ? e.data.json() : {}; } catch { d = {body: e.data ? e.data.text() : ''}; }
  if (d && d.type === 'dismiss') { e.waitUntil(closeTags(d.tags).catch(() => 0)); return; }
  e.waitUntil(closeTags(d.dismiss).catch(() => 0).then(() => self.registration.showNotification(d.title || 'Kalmido', pushOptions(d))));
});
// focus an open Kalmido window and hand it the in-app link, else open a new one
async function openApp(path) {
  const wins = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
  const w = wins.find(c => new URL(c.url).origin === self.location.origin);
  if (w) {
    try { await w.focus(); } catch { /* not allowed without user gesture */ }
    w.postMessage({type: 'open', url: path});
    return w;
  }
  return self.clients.openWindow(path);
}
// "Done" completes the task in the background with the session cookie (+ the CSRF header, like the app);
// without a valid session (login proxy expired, logged out) it opens the app at #done/<id> instead, which is
// what the ntfy button does. "Snooze" and every other button open their link (#snooze/<id> = snooze sheet, 2.0.8:
// #reply/<id> = the task with the comment box focused). Comment pushes carry Reply + Done, reminders Done + Snooze,
// nags (2.7.0) Done + Stop reminding + Snooze.
async function pushClick(action, data) {
  // 2.7.0 (#413): "Stop reminding" switches the task's nags off in the background (else: the app at #nagoff/<id>)
  if (action === 'nagoff' && data.task) {
    try {
      const r = await fetch(`/api/tasks/${data.task}`, {method: 'PATCH', credentials: 'same-origin', redirect: 'manual',
        headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/json'}, body: JSON.stringify({nag: 'off'})});
      if (r.ok && (r.headers.get('content-type') || '').includes('json')) {
        (await self.clients.matchAll({type: 'window'})).forEach(w => w.postMessage({type: 'refresh'}));
        return 'nagoff';
      }
    } catch { /* offline -> open the app */ }
  }
  if (action === 'done' && data.task) {
    try {
      // X-Kalmido-Device: this device closed its notification itself, the others get theirs closed (2.0.5)
      let sub = null;
      try { sub = await self.registration.pushManager.getSubscription(); } catch { /* unknown: the server just cannot tell */ }
      const r = await fetch(`/api/tasks/${data.task}/complete`, {method: 'POST', credentials: 'same-origin', redirect: 'manual',
        headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/json', ...(sub ? {'X-Kalmido-Device': sub.endpoint} : {})},
        body: JSON.stringify(data.due ? {expect_due: data.due} : {})});
      if (r.ok && (r.headers.get('content-type') || '').includes('json')) {
        const wins = await self.clients.matchAll({type: 'window'});
        wins.forEach(w => w.postMessage({type: 'refresh'}));
        return 'done';
      }
    } catch { /* offline -> open the app */ }
  }
  const url = (action && data.actions && data.actions[action]) || data.url || '/';
  await openApp(url);
  return 'open';
}
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(pushClick(e.action, e.notification.data || {}));
});
// the push service renewed / dropped the subscription: subscribe again and tell the server (session cookie)
const b64uBytes = s => { const b = atob((s + '='.repeat((4 - s.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(b, c => c.charCodeAt(0)); };
async function resubscribe(oldSub, newSub) {
  let sub = newSub;
  if (!sub) {
    const r = await fetch('/api/push/vapid', {credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido'}});
    const j = await r.json();
    if (!j.enabled || !j.key) return;
    sub = await self.registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64uBytes(j.key)});
  }
  await fetch('/api/push/subs', {method: 'POST', credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido', 'Content-Type': 'application/json'},
    body: JSON.stringify({...sub.toJSON(), replaces: oldSub ? oldSub.endpoint : undefined})});
}
self.addEventListener('pushsubscriptionchange', e => { e.waitUntil(resubscribe(e.oldSubscription, e.newSubscription).catch(() => {})); });
