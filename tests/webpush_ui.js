// Web Push in the browser (1.1.3): the service worker (push -> notification, clicks, Done in the background,
// pushsubscriptionchange) in a Node vm with stubbed SW globals, and Settings > Notifications in jsdom with a fake
// Notification / PushManager / service worker registration. Needs the container + users of webpush_test.py
// (fake push service on 127.0.0.1:9997 inside it).
// usage: node webpush_ui.js <datadir>
const fs = require('fs'), path = require('path'), vm = require('vm'), crypto = require('crypto');
const {boot, errs, sleep} = require('./boot');
const DATA = process.argv[2] || path.join(__dirname, '.data');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const api = async (w, method, url, body) => (await w.fetch(url, {method, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: body ? JSON.stringify(body) : undefined})).json();
const wpLog = () => { try { return fs.readFileSync(path.join(DATA, 'webpush.log'), 'utf8').split('\n').filter(Boolean).map(JSON.parse); } catch { return []; } };

// ------------------------------------------------------------------ service worker (vm)
const SW = fs.readFileSync(process.env.KALMIDO_SW || path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
function swEnv({fetchImpl = async () => new Response('{}', {status: 200, headers: {'content-type': 'application/json'}}), wins = []} = {}) {
  const L = {}, shown = [], opened = [], fetches = [], subscribed = [];
  const self = {
    location: {origin: 'https://kalmido.example'},
    addEventListener: (t, f) => { L[t] = f; },
    skipWaiting() {},
    registration: {showNotification: async (t, o) => { shown.push([t, o]); },
      pushManager: {subscribe: async o => { subscribed.push(o); return {endpoint: 'https://fcm.googleapis.com/fcm/send/new', toJSON: () => ({endpoint: 'https://fcm.googleapis.com/fcm/send/new', keys: {p256dh: 'x', auth: 'y'}})}; }}},
    clients: {matchAll: async () => wins, openWindow: async u => { opened.push(u); return {}; }, claim() {}},
  };
  const ctx = {self, caches: {open: async () => ({addAll: async () => {}, put() {}, keys: async () => [], delete() {}}), keys: async () => [], match: async () => null},
    fetch: async (u, o) => { fetches.push([u, o]); return fetchImpl(u, o); }, URL, Response, atob, Uint8Array, JSON, Promise, console, setTimeout};
  vm.createContext(ctx);
  vm.runInContext(SW, ctx);
  return {L, shown, opened, fetches, subscribed};
}
const ev = (extra = {}) => { const e = {...extra, waitUntil(p) { this.p = p; }}; return e; };
const pushEv = d => ev({data: {json: () => d, text: () => JSON.stringify(d)}});
const win = () => { const w = {url: 'https://kalmido.example/#today', msgs: [], focused: 0, focus: async () => { w.focused++; }, postMessage: m => w.msgs.push(m)}; return w; };

async function swTests() {
  // push -> notification
  let S = swEnv();
  let e = pushEv({title: 'Pay rent', body: 'Due today at 09:00 · Home', url: '/#t/5', tag: 't-5', prio: 5, task: 5, due: '2026-09-28', ts: 1,
    actions: [{action: 'done', title: 'Done', url: '/#done/5'}, {action: 'snooze', title: 'Snooze', url: '/#snooze/5'}]});
  S.L.push(e); await e.p;
  const [title, o] = S.shown[0] || [];
  check(title === 'Pay rent' && o.body.startsWith('Due today'), 'push: title + body');
  check(o.tag === 't-5' && o.renotify === true, 'push: tag per task (replaces the previous one) + renotify');
  check(o.requireInteraction === true, 'priority 5 -> requireInteraction');
  check(o.icon === '/static/icon-192.png' && o.badge === '/static/badge-96.png', 'icon + monochrome badge');
  check(JSON.stringify(o.actions) === JSON.stringify([{action: 'done', title: 'Done'}, {action: 'snooze', title: 'Snooze'}]), 'actions: Done, Snooze');
  check(o.data.url === '/#t/5' && o.data.task === 5 && o.data.due === '2026-09-28' && o.data.actions.snooze === '/#snooze/5', 'data: link, task, due, action links');
  e = pushEv({title: 'x', body: 'y', prio: 4, url: 'https://evil.example/#t/1'}); S.L.push(e); await e.p;
  check(!S.shown[1][1].requireInteraction && !S.shown[1][1].tag && S.shown[1][1].data.url === '/', 'priority 4: no requireInteraction; foreign link -> /');
  e = ev({data: {json: () => { throw new Error('no json'); }, text: () => 'plain text'}}); S.L.push(e); await e.p;
  check(S.shown[2][0] === 'Kalmido' && S.shown[2][1].body === 'plain text', 'non-JSON push still shows a notification');

  // click on the body: focus an open window + hand it the link
  const w1 = win();
  S = swEnv({wins: [w1]});
  let closed = 0;
  const note = (data, action = '') => ev({action, notification: {data, close: () => { closed++; }}});
  e = note({url: '/#t/5', task: 5, actions: {}}); S.L.notificationclick(e); await e.p;
  check(closed === 1 && w1.focused === 1 && w1.msgs[0]?.type === 'open' && w1.msgs[0].url === '/#t/5' && !S.opened.length, 'click: focus the open window, open the task there');
  // no window -> openWindow
  S = swEnv();
  e = note({url: '/#habits', actions: {}}); S.L.notificationclick(e); await e.p;
  check(S.opened[0] === '/#habits', 'click without an open window: openWindow(link)');
  // Snooze -> open #snooze/<id>
  e = note({url: '/#t/5', task: 5, actions: {snooze: '/#snooze/5', done: '/#done/5'}}, 'snooze'); S.L.notificationclick(e); await e.p;
  check(S.opened[1] === '/#snooze/5' && !S.fetches.length, 'Snooze opens the snooze sheet (#snooze/5)');
  // Done -> background complete with the CSRF header + expect_due; windows refresh
  const w2 = win();
  S = swEnv({wins: [w2]});
  e = note({url: '/#t/5', task: 5, due: '2026-09-28', actions: {done: '/#done/5'}}, 'done'); S.L.notificationclick(e); await e.p;
  const [u, opt] = S.fetches[0] || [];
  check(u === '/api/tasks/5/complete' && opt.method === 'POST' && opt.headers['X-Requested-With'] === 'kalmido' && opt.credentials === 'same-origin'
    && JSON.parse(opt.body).expect_due === '2026-09-28', 'Done: POST /api/tasks/5/complete with CSRF header + expect_due');
  check(!S.opened.length && w2.msgs.some(m => m.type === 'refresh') && !w2.msgs.some(m => m.type === 'open'), 'Done: no window opened, open windows refresh');
  // Done without a session (401 / login redirect) -> open #done/<id> like the ntfy button
  S = swEnv({fetchImpl: async () => new Response('{"auth":"login"}', {status: 401, headers: {'content-type': 'application/json'}})});
  e = note({url: '/#t/5', task: 5, actions: {done: '/#done/5'}}, 'done'); S.L.notificationclick(e); await e.p;
  check(S.opened[0] === '/#done/5', 'Done without a session: opens the app at #done/5');
  S = swEnv({fetchImpl: async () => new Response('<html>login</html>', {status: 200, headers: {'content-type': 'text/html'}})});
  e = note({url: '/#t/5', task: 5, actions: {done: '/#done/5'}}, 'done'); S.L.notificationclick(e); await e.p;
  check(S.opened[0] === '/#done/5', 'Done answered by a login page (proxy): opens the app');
  S = swEnv({fetchImpl: async () => { throw new TypeError('offline'); }});
  e = note({url: '/#t/5', task: 5, actions: {done: '/#done/5'}}, 'done'); S.L.notificationclick(e); await e.p;
  check(S.opened[0] === '/#done/5', 'Done offline: opens the app');

  // pushsubscriptionchange: resubscribe with the server key, tell the server (replaces = old endpoint)
  const key = Buffer.alloc(65, 4).toString('base64url');
  S = swEnv({fetchImpl: async u => new Response(u === '/api/push/vapid' ? JSON.stringify({enabled: true, key}) : '{}', {status: 200, headers: {'content-type': 'application/json'}})});
  e = ev({oldSubscription: {endpoint: 'https://fcm.googleapis.com/fcm/send/old'}, newSubscription: null}); S.L.pushsubscriptionchange(e); await e.p;
  const post = S.fetches.find(([u]) => u === '/api/push/subs');
  check(S.subscribed[0]?.userVisibleOnly === true && S.subscribed[0].applicationServerKey.length === 65, 'pushsubscriptionchange: subscribes again with the VAPID key');
  check(post && post[1].headers['X-Requested-With'] === 'kalmido' && JSON.parse(post[1].body).replaces === 'https://fcm.googleapis.com/fcm/send/old'
    && JSON.parse(post[1].body).endpoint === 'https://fcm.googleapis.com/fcm/send/new', 'pushsubscriptionchange: POST /api/push/subs with replaces');
}

// ------------------------------------------------------------------ Settings > Notifications (jsdom)
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36';
const IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
function browserKeys() {
  const {publicKey} = crypto.generateKeyPairSync('ec', {namedCurve: 'prime256v1'});
  const j = publicKey.export({format: 'jwk'});
  const raw = Buffer.concat([Buffer.from([4]), Buffer.from(j.x, 'base64url'), Buffer.from(j.y, 'base64url')]);
  return {p256dh: raw.toString('base64url'), auth: crypto.randomBytes(16).toString('base64url')};
}
function fakePush({ua = ANDROID, perm = 'default', grant = 'granted', push = true, endpoint = 'http://127.0.0.1:9997/push/ui-1'} = {}) {
  const f = {sub: null, subscribed: [], unsub: 0, listeners: {}, keys: browserKeys(), asked: 0};
  const mk = () => ({endpoint, options: {applicationServerKey: null}, toJSON: () => ({endpoint, expirationTime: null, keys: f.keys}),
    unsubscribe: async () => { f.unsub++; f.sub = null; return true; }});
  f.setup = w => {
    Object.defineProperty(w.navigator, 'userAgent', {get: () => ua, configurable: true});
    const reg = {active: {}, pushManager: {getSubscription: async () => f.sub, subscribe: async o => { f.subscribed.push(o); f.sub = mk(); return f.sub; }}};
    if (push) {
      w.Notification = {permission: perm, requestPermission: async () => { f.asked++; w.Notification.permission = grant; return grant; }};
      w.PushManager = function PushManager() {};
    }
    Object.defineProperty(w.navigator, 'serviceWorker', {configurable: true, value: {register: () => Promise.resolve(reg), getRegistration: async () => reg,
      ready: Promise.resolve(reg), addEventListener: (t, fn) => { f.listeners[t] = fn; }, controller: null}});
  };
  return f;
}
const pane = async w => { w.eval(`settingsModal('notify')`); await sleep(700); return w.document.querySelector('.smodal [data-pane="notify"]'); };
const text = el => (el?.textContent || '').replace(/\s+/g, ' ');

async function uiTests() {
  // carol: channel webpush (migrated), no device, ntfy topic -> "using ntfy for now"
  let f = fakePush();
  let w = await boot({user: 'carol', setup: f.setup});
  let p = await pane(w);
  check(p.querySelector('#s-pushch')?.value === 'webpush', 'channel select: Web Push');
  check(/No device subscribed yet — using ntfy for now\./.test(text(p.querySelector('#s-wpstate'))) && p.querySelector('#s-wpstate').classList.contains('warn'), 'no device yet: "using ntfy for now" shown');
  check(p.querySelector('#s-wpdev') && !p.querySelector('#s-wpdev').checked && !p.querySelector('[data-m="wp-test"]'), 'toggle off, no device test button yet');
  check(/Your browser asks for permission once/.test(text(p)), 'permission hint');
  check(p.querySelector('.topic') && p.querySelector('[data-m="test"]'), 'ntfy topic + ntfy test still there');
  // turn on
  const tg = p.querySelector('#s-wpdev'); tg.checked = true; tg.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1200);
  check(f.asked === 1 && f.subscribed.length === 1 && f.subscribed[0].userVisibleOnly === true, 'toggle: permission asked, subscribed (userVisibleOnly)');
  const vk = (await api(w, 'GET', '/api/push/vapid')).key;
  check(Buffer.from(f.subscribed[0].applicationServerKey).toString('base64url') === vk, 'subscribed with the server VAPID key');
  let subs = (await api(w, 'GET', '/api/push/subs')).subs;
  check(subs.length === 1 && subs[0].label === 'Chrome on Android' && subs[0].endpoint === 'http://127.0.0.1:9997/push/ui-1', 'server: device stored with label "Chrome on Android"');
  p = w.document.querySelector('.smodal [data-pane="notify"]');
  check(p.querySelector('#s-wpdev').checked && p.querySelector('[data-m="wp-test"]'), 'toggle on + "Send test to this device"');
  check(/Web Push to 1 device\. ntfy only if no device accepts a push\./.test(text(p.querySelector('#s-wpstate'))), 'state: Web Push to 1 device');
  check(/Chrome on Android/.test(text(p.querySelector('.wpdevs'))) && p.querySelector('.wpdevs .devtag'), 'device list: this device tagged');
  check(/Notifications on for this device/.test(text(w.document.querySelector('#toast'))), 'toast: on');
  // test to this device
  const n0 = wpLog().filter(x => x.path === '/push/ui-1').length;
  click(w, p.querySelector('[data-m="wp-test"]')); await sleep(900);
  check(wpLog().filter(x => x.path === '/push/ui-1').length === n0 + 1 && /Test sent to this device/.test(text(w.document.querySelector('#toast'))), 'device test reached the push service');
  // channel select: state follows, saved at once (1.5); the ntfy details only when ntfy is a channel
  check(p.querySelector('#s-ntfy').classList.contains('hidden'), 'channel Web Push: ntfy details hidden');
  const ch = p.querySelector('#s-pushch'); ch.value = 'ntfy'; ch.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(600);
  check(/Everything goes to ntfy\./.test(text(p.querySelector('#s-wpstate'))) && (await api(w, 'GET', '/api/state')).settings.push_channel === 'ntfy' && !p.querySelector('#s-ntfy').classList.contains('hidden'), 'channel ntfy: state, saved at once, ntfy details shown');
  ch.value = 'both'; ch.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(600);
  check(/Web Push to 1 device and ntfy\./.test(text(p.querySelector('#s-wpstate'))), 'channel both: state');
  check((await api(w, 'GET', '/api/state')).settings.push_channel === 'both', 'the channel is stored at once');
  await api(w, 'PATCH', '/api/settings', {push_channel: 'webpush'});
  // message from the SW: open a link in this window; foreign origins ignored
  f.listeners.message?.({data: {type: 'open', url: '/#habits'}}); await sleep(300);
  check(w.location.hash === '#habits', 'SW message "open" navigates this window');
  f.listeners.message?.({data: {type: 'open', url: 'https://evil.example/#trash'}}); await sleep(100);
  check(w.location.hash === '#habits', 'SW message with a foreign URL ignored');
  // remove this device from the list -> browser subscription dropped too
  p = await pane(w);
  click(w, p.querySelector('.wpdevs [data-m="wp-del"]')); await sleep(900);
  p = w.document.querySelector('.smodal [data-pane="notify"]');
  check(f.unsub === 1 && !(await api(w, 'GET', '/api/push/subs')).subs.length && !p.querySelector('.wpdevs'), 'remove: server + browser subscription gone');
  check(/using ntfy for now/.test(text(p.querySelector('#s-wpstate'))) && !p.querySelector('#s-wpdev').checked, 'back to "using ntfy for now"');
  // on again, then off with the toggle
  let t2 = p.querySelector('#s-wpdev'); t2.checked = true; t2.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1200);
  check((await api(w, 'GET', '/api/push/subs')).subs.length === 1 && f.asked === 1, 'on again (permission not asked twice)');
  p = w.document.querySelector('.smodal [data-pane="notify"]');
  t2 = p.querySelector('#s-wpdev'); t2.checked = false; t2.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1000);
  check(!(await api(w, 'GET', '/api/push/subs')).subs.length && f.unsub === 2 && /Notifications off for this device/.test(text(w.document.querySelector('#toast'))), 'toggle off: unsubscribed everywhere');
  // daily check-in: a device removed elsewhere is not re-added
  t2 = w.document.querySelector('#s-wpdev'); t2.checked = true; t2.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1200);
  subs = (await api(w, 'GET', '/api/push/subs')).subs;
  await api(w, 'DELETE', `/api/push/subs/${subs[0].id}`);
  w.localStorage.setItem('tasks.wpSync', '0');
  await w.eval('wpSync()'); await sleep(300);
  check(!(await api(w, 'GET', '/api/push/subs')).subs.length && w.localStorage.getItem('tasks.wpUser') === null, 'check-in: removed device stays removed');
  w.close();

  // permission denied
  f = fakePush({perm: 'default', grant: 'denied'});
  w = await boot({user: 'carol', setup: f.setup});
  p = await pane(w);
  const t3 = p.querySelector('#s-wpdev'); t3.checked = true; t3.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900);
  check(/Notifications are blocked for this site/.test(text(w.document.querySelector('#toast'))) && !f.subscribed.length, 'denied: toast, no subscription');
  check(/Notifications are blocked for this site/.test(text(w.document.querySelector('#s-wp'))) && !w.document.querySelector('#s-wpdev').checked, 'denied: hint in the pane');
  w.close();

  // iPhone in Safari (not on the Home Screen): hint, no toggle
  f = fakePush({ua: IPHONE, push: false});
  w = await boot({user: 'carol', setup: f.setup});
  p = await pane(w);
  check(/Add Kalmido to your Home Screen to get notifications on iPhone/.test(text(p)) && !p.querySelector('#s-wpdev'), 'iOS Safari: Home Screen hint');
  w.close();
  // iPhone, Home Screen app (standalone, iOS 16.4+): toggle
  f = fakePush({ua: IPHONE});
  w = await boot({user: 'carol', setup: f.setup, media: {'(display-mode: standalone)': true}});
  p = await pane(w);
  check(p.querySelector('#s-wpdev') && !/Add Kalmido to your Home Screen/.test(text(p)), 'iOS Home Screen app: toggle, no hint');
  w.close();
  // other browser without Web Push
  f = fakePush({ua: 'Mozilla/5.0 (X11; Linux x86_64) Old/1.0', push: false});
  w = await boot({user: 'carol', setup: f.setup});
  p = await pane(w);
  check(/This browser does not support Web Push/.test(text(p)) && !p.querySelector('#s-wpdev'), 'no Web Push support: hint');
  w.close();

  // German
  f = fakePush();
  w = await boot({user: 'carol', setup: f.setup});
  await api(w, 'PATCH', '/api/settings', {lang: 'de'});
  w.close();
  w = await boot({user: 'carol', setup: f.setup});
  p = await pane(w);
  check(/Auf diesem Gerät benachrichtigen/.test(text(p)) && /Noch kein Gerät angemeldet – bis dahin kommt alles über ntfy\./.test(text(p)) && /Zustellung/.test(text(p)), 'German strings');
  await api(w, 'PATCH', '/api/settings', {lang: 'en'});
  w.close();
}

(async () => {
  await swTests();
  await uiTests();
  const e = errs.filter(x => !/Could not load|ECONNREFUSED/.test(x));
  check(!e.length, 'no script errors: ' + e.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
