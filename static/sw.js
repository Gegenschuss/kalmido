// tasks service worker: cache the app shell so the PWA opens offline;
// API calls always go to the network (data must be live). Language files: de.json is precached,
// any other static/i18n/<code>.json lands in the cache via the network-first handler on first use
// (the client also keeps the active one in localStorage as a last offline fallback).
// 2.191.0 A (#1410 #2518): the client loads the core texts (de.core.json is precached) and the texts of each module
// (<code>.mod-<name>.json, fetched in the background by i18n.js i18nWarm, kept by swI18n); 2.191.0 F2: an update keeps them (swKeepI18n)
const CACHE = 'tasks-shell-v400';  // app 2.401.1 (2.126.0 D, #1992: count both up with every version, tools/check_layout.py)
const SHELL = ['/', '/manifest.json', '/static/app.css', '/static/i18n.js', '/static/i18n/de.core.json', '/static/icon-192.png',
  '/static/icon-512.png', '/static/icon.svg', '/static/badge-96.png', '/static/fonts/Geist-Variable.woff2', '/static/fonts/GeistMono-Variable.woff2',
  '/static/quips.json', '/static/favicon.svg', '/static/favicon-32.png', '/static/apple-touch-icon.png', '/static/icon-maskable-512.png',
  '/static/fonts/AtkinsonHyperlegible-Regular.woff2', '/static/fonts/AtkinsonHyperlegible-Bold.woff2', '/static/js/reloadguard.js',
  '/static/js/clienterr.js', '/static/js/icons.js', '/static/js/core.js', '/static/js/lazyload.js', '/static/js/lyopts.js', '/static/js/workspace.js',
  '/static/js/sharews.js', '/static/js/spacemove.js', '/static/js/quickadd.js', '/static/js/quickadd2.js', '/static/js/views.js',
  '/static/js/render.js', '/static/js/vlist.js', '/static/js/calendar.js', '/static/js/habits.js', '/static/js/detail.js', '/static/js/collab.js',
  '/static/js/attachments.js', '/static/js/mdtitle.js', '/static/js/undo.js', '/static/js/popovers.js', '/static/js/dialogs.js',
  '/static/js/dlgmove.js', '/static/js/setcore.js', '/static/js/custview.js', '/static/js/signoff.js', '/static/js/account.js',
  '/static/js/templates.js', '/static/js/time.js', '/static/js/projects.js', '/static/js/sprints.js', '/static/js/events.js', '/static/js/sidebar.js',
  '/static/js/sharedlg.js', '/static/js/drag.js', '/static/js/dnd.js', '/static/js/secdrag.js', '/static/js/dragmulti.js', '/static/js/palette.js',
  '/static/js/ftsearch.js', '/static/js/backclose.js', '/static/js/agents.js', '/static/js/cleanup.js', '/static/js/dayplan.js',
  '/static/js/choicecard.js', '/static/js/chatbase.js', '/static/js/jobchat.js', '/static/js/agentview.js', '/static/js/propkinds2.js',
  '/static/js/listedit.js', '/static/js/git.js', '/static/js/chat.js', '/static/js/refs.js', '/static/js/tagsview.js', '/static/js/cfnew.js',
  '/static/js/richcopy.js', '/static/js/dashboard.js', '/static/js/widgets.js', '/static/js/pinboard.js', '/static/js/lysets.js',
  '/static/js/family.js', '/static/js/tapdone.js', '/static/js/listhead.js', '/static/js/purposemods.js', '/static/js/calevents.js',
  '/static/js/davwrite.js', '/static/js/multisel.js', '/static/js/ctlinks.js', '/static/js/formguard.js', '/static/js/liveparts.js',
  '/static/js/countries.js', '/static/js/clients.js', '/static/js/agentplan.js', '/static/js/lyprop.js', '/static/js/clientpage.js',
  '/static/js/portal.js', '/static/js/areas.js', '/static/js/multiedit.js', '/static/js/basket.js', '/static/js/sbnav.js', '/static/js/notesall.js',
  '/static/js/favorites.js', '/static/js/favtiles.js', '/static/js/mineorder.js', '/static/js/tablecells.js', '/static/js/sheetgrid.js',
  '/static/js/formula.js', '/static/js/listadmin.js', '/static/js/orgexport.js', '/static/js/move.js', '/static/js/orgcrypt.js',
  '/static/js/cryptscope.js', '/static/js/sheetdrag.js', '/static/js/sheetmotion.js', '/static/js/miniwin.js', '/static/js/chatwin.js',
  '/static/js/chatwins.js', '/static/js/chatplus.js', '/static/js/taskbell.js', '/static/js/e2e.js', '/static/js/notelock.js',
  '/static/js/related.js', '/static/js/liste2e.js', '/static/js/liste2eui.js', '/static/js/liste2efile.js', '/static/js/liste2echan.js',
  '/static/js/wikie2e.js', '/static/js/orgvis.js', '/static/js/discover.js', '/static/js/ablage.js', '/static/js/listcolor.js',
  '/static/js/wscolor.js', '/static/js/rowsym.js', '/static/js/review.js', '/static/js/wip.js', '/static/js/swimlanes.js', '/static/js/points.js',
  '/static/js/photometa.js', '/static/js/ablinks.js', '/static/js/filetext.js', '/static/js/depchain.js', '/static/js/importprop.js',
  '/static/js/meetprop.js', '/static/js/dupprop.js', '/static/js/contractprop.js', '/static/js/multilist.js', '/static/js/rules.js',
  '/static/js/supporter.js', '/static/js/assistant.js', '/static/js/main.js'];
// 2.53.0 (#1410): the modules loaded on demand (static/js/lazyload.js LD_MODS; no script tag in index.html, tools/check_layout.py
// compares): cached right after the shell, so they open offline too; a failure there does not drop the install
const LAZY = ['/static/js/acctset.js', '/static/js/sesview.js', '/static/js/oinvview.js', '/static/js/servers.js', '/static/js/settings.js',
  '/static/js/contacts.js', '/static/js/ctfold.js', '/static/js/newsletter.js', '/static/js/office.js', '/static/js/office_docs.js',
  '/static/js/office_tree.js', '/static/js/office_import.js', '/static/js/office_sheet.js', '/static/js/office_parts.js',
  '/static/js/office_travel.js', '/static/js/office_cashflow.js', '/static/js/office_doctpl.js', '/static/js/office_logbook.js',
  '/static/js/office_cashbook.js', '/static/js/office_pipeline.js', '/static/js/office_kpi.js', '/static/js/office_datev.js',
  '/static/js/office_datevimp.js', '/static/js/office_periods.js', '/static/js/officeagents.js', '/static/js/office_packs.js',
  '/static/js/office_books.js', '/static/js/office_receipts.js', '/static/js/office_bank.js', '/static/js/office_taxdates.js',
  '/static/js/office_banknorc.js', '/static/js/office_recurring.js', '/static/js/office_subs.js', '/static/js/office_dunning.js',
  '/static/js/office_peppol.js', '/static/js/office_bankrules.js', '/static/js/office_docproject.js', '/static/js/office_agreements.js',
  '/static/js/office_assets.js', '/static/js/office_meals.js', '/static/js/office_leads.js', '/static/js/office_cfiles.js',
  '/static/js/office_letterhead.js', '/static/js/office_numranges.js', '/static/js/office_terms.js', '/static/js/office_procdoc.js',
  '/static/js/office_letters.js', '/static/js/office_letterlinks.js', '/static/js/office_lettermail.js', '/static/js/office_rights.js',
  '/static/js/agentchat.js', '/static/js/agentsetup.js', '/static/js/agentrotate.js', '/static/js/agentwork.js', '/static/js/agentcontrol.js',
  '/static/js/agentlock.js', '/static/js/agentrules.js', '/static/js/pdfview.js', '/static/js/docpreview.js', '/static/js/mindmap.js',
  '/static/js/diagram.js', '/static/js/wkshare.js', '/static/js/wkhist.js', '/static/js/wkembed.js', '/static/js/wklive.js', '/static/js/wiki.js',
  '/static/js/wkimport.js', '/static/js/stats.js', '/static/js/calview.js', '/static/js/caldrag.js', '/static/js/apptbook.js',
  '/static/js/calyear.js', '/static/js/listcal.js', '/static/js/calgest.js', '/static/js/calrrule.js', '/static/js/calabs.js', '/static/js/docs.js',
  '/static/js/paperless.js', '/static/js/receipts.js', '/static/js/letterdoc.js', '/static/js/letteragent.js', '/static/js/docsplit.js',
  '/static/js/docscan.js', '/static/js/abdocs.js', '/static/js/life.js', '/static/js/devlink.js', '/static/js/budget.js',
  '/static/js/integrations.js', '/static/js/playbook.js', '/static/js/timeline.js', '/static/js/roadmap.js', '/static/js/feeds.js',
  '/static/js/bookmarks.js', '/static/js/readlater.js', '/static/js/cfkinds.js', '/static/js/mineboard.js', '/static/js/sectpl.js',
  '/static/js/asstprop.js', '/static/js/sheetprop.js', '/static/js/sheetfold.js', '/static/js/sheets.js', '/static/js/sheets2.js',
  '/static/js/sheetsio.js', '/static/js/sheetsize.js', '/static/js/sheetshare.js', '/static/js/sheetchart.js', '/static/js/sheetkinds.js',
  '/static/js/sheetbook.js', '/static/js/fslock.js', '/static/js/tagsel.js', '/static/js/filereq.js', '/static/js/fsshare.js',
  '/static/js/videorev.js', '/static/js/abscan.js', '/static/js/pubvideo.js', '/static/js/hookin.js', '/static/js/polls.js', '/static/js/formq.js',
  '/static/js/office_undo.js', '/static/js/voice.js', '/static/js/hubmailbox.js', '/static/js/listprint.js', '/static/js/evinvite.js',
  '/static/js/projtime.js', '/static/js/envs.js', '/static/js/dpmodal.js', '/static/js/gitrepo.js', '/static/js/timesheet.js',
  '/static/js/absence.js', '/static/js/leave.js', '/static/js/dispo.js', '/static/js/hubmail.js', '/static/js/msvview.js', '/static/js/sprints2.js',
  '/static/js/sideviews.js', '/static/js/notetrash.js', '/static/js/trashui.js'];
// 2.45.0 (#1529): the new cache is filled completely first (addAll fails on any non-2xx -> this install is dropped and the
// old worker and cache stay); old caches are deleted only when the new one holds the whole shell
// 2.65.0 (#1824): the stylesheets of the modules loaded on demand (static/css/, LD_CSS in lazyload.js, same order)
const LAZY_CSS = ['/static/css/settings.css', '/static/css/contacts.css', '/static/css/office.css', '/static/css/agentchat.css',
  '/static/css/pdf.css', '/static/css/mindmap.css', '/static/css/wiki.css', '/static/css/stats.css', '/static/css/calendar.css',
  '/static/css/docs.css', '/static/css/life.css', '/static/css/integrations.css', '/static/css/playbook.css', '/static/css/timeline.css',
  '/static/css/feeds.css', '/static/css/bookmarks.css', '/static/css/sheets.css', '/static/css/videorev.css', '/static/css/tagsel.css',
  '/static/css/filereq.css', '/static/css/abscan.css', '/static/css/calabs.css', '/static/css/sideviews.css'];
self.addEventListener('install', e => { e.waitUntil(swInstall().then(() => self.skipWaiting())); });
// 2.149.0 B (#2506): the server names every precached static file with its content hash (/sw-manifest.json). A file is kept
// under "<url>?v=<hash>" (the address index.html asks for), so an update copies every unchanged file from the old cache and
// loads only the changed ones. Without the manifest (an older server, a sign-in page in between) everything is loaded as before.
const SW_HASH = /^[0-9a-f]{12}$/;
async function swManifest() {
  try {
    const r = await fetch('/sw-manifest.json', {cache: 'no-store', credentials: 'same-origin'});
    if (!r.ok || r.redirected || !/json/.test(r.headers.get('content-type') || '')) return null;
    const m = await r.json();
    return m && m.v === 1 && m.files && typeof m.files === 'object' ? m.files : null;
  } catch { return null; }
}
// one precached file: an unchanged copy from an old cache, else from the network (non-2xx = an error, like addAll)
async function swPrecache(c, url, files) {
  const h = files[url];
  if (!SW_HASH.test(h || '')) { await c.add(url); return; }
  const key = `${url}?v=${h}`, old = await caches.match(key);
  if (old) { await c.put(key, old); return; }
  const r = await fetch(key, {credentials: 'same-origin'});
  if (!r.ok || r.redirected) throw new TypeError(`precache ${url}: ${r.status}`);
  // the server confirms the hash with an immutable answer; else (an update in between) the copy is kept without a hash
  await c.put(/immutable/.test(r.headers.get('cache-control') || '') ? key : url, r);
}
async function swInstall() {
  const c = await caches.open(CACHE), files = await swManifest();
  if (!files) return c.addAll(SHELL).then(() => c.addAll(LAZY.concat(LAZY_CSS)).catch(() => 0)).then(() => swDone(c));
  await Promise.all(SHELL.map(u => swPrecache(c, u, files)));  // a failure drops this install (the old worker and cache stay)
  await Promise.all(LAZY.concat(LAZY_CSS).map(u => swPrecache(c, u, files).catch(() => 0)));
  await swKeepI18n(c, files['/static/i18n/de.core.json']).catch(() => 0);
  await swDone(c);
}
// 2.209.0 E (#1627): a marker written last by a finished install; a fallback never reads a half-filled cache (swAnyCache)
const SW_DONE = '/sw-install-done';
async function swDone(c) { try { await c.put(SW_DONE, new Response('1')); } catch { /* no marker = no fallback to this cache */ } }
// 2.191.0 F2 (#2518): the texts of the modules (<code>.mod-<name>.json, fetched by i18n.js i18nWarm) move from an old cache
// while their version (?v=) is still the current one, so an update keeps every module translated offline
async function swKeepI18n(c, ver) {
  if (!SW_HASH.test(ver || '')) return;
  for (const k of await caches.keys()) {
    if (k === CACHE) continue;
    const old = await caches.open(k);
    for (const req of await old.keys()) {
      const u = new URL(req.url);
      if (/^\/static\/i18n\/[\w-]+\.mod-[\w-]+\.json$/.test(u.pathname) && u.searchParams.get('v') === ver && !(await c.match(req))) {
        const r = await old.match(req);
        if (r) await c.put(req, r);
      }
    }
  }
}
self.addEventListener('activate', e => { e.waitUntil(swCleanup().then(() => self.clients.claim())); });
async function swCleanup() {
  const c = await caches.open(CACHE);
  for (const u of ['/', '/static/app.css']) if (!await c.match(u, {ignoreSearch: true})) return;  // incomplete: keep the old caches as a fallback
  for (const k of await caches.keys()) if (k !== CACHE && k !== 'tasks-share') await caches.delete(k);
}
// any cached copy of a request: this worker's cache first, then the other shell caches, the newest first.
// 2.209.0 E (#1627): another cache only when its install finished (SW_DONE) or it is older than this one (it was the active
// cache once), so the half-filled cache of a newer install that broke off never answers
const swVer = k => { const m = /^tasks-shell-v(\d+)$/.exec(k); return m ? +m[1] : -1; };
async function swAnyCache(req, opt) {
  const hit = await (await caches.open(CACHE)).match(req, opt);
  if (hit) return hit;
  for (const k of (await caches.keys()).reverse()) {
    if (k === CACHE || swVer(k) < 0) continue;
    const c = await caches.open(k);
    if (swVer(k) >= swVer(CACHE) && !(await c.match(SW_DONE))) continue;
    const r = await c.match(req, opt);
    if (r) return r;
  }
  return undefined;
}
async function swShell(req, url) {
  // 2.53.0 (#1410): modules on demand come with ?v=; 2.149.0 B (#2505): every start script / stylesheet too (a content hash)
  const opt = {ignoreSearch: url.pathname === '/' || url.pathname === '/capture' || url.pathname.startsWith('/static/')};
  // 2.190.0 A (#2496): the app page and the quick capture page are kept without their query (a captured page's title and
  // address never become a cache key)
  const key = (url.pathname === '/' || url.pathname === '/capture') && url.search ? url.pathname : req;
  // 2.149.0 B (#2506): ?v=<content hash> never changes: a kept copy of exactly that address is the file, no network needed
  const hashed = url.pathname.startsWith('/static/') && SW_HASH.test(url.searchParams.get('v') || '');
  if (hashed) { const hit = await caches.match(req); if (hit) return hit; }
  let r = null;
  try { r = await fetch(req); } catch { r = null; }
  // 2.149.0 B (#2506): a hashed address is kept only when the server confirmed the hash (immutable), so it never holds other bytes
  const keep = r && r.ok && !r.redirected && r.type === 'basic' && (!hashed || /immutable/.test(r.headers.get('cache-control') || ''));
  if (keep) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(key, copy)).catch(() => {}); return r; }  // 2.138.0 A (#2257): a refused put is no uncaught error
  if (r && r.ok) return r;
  // network error or 5xx (server restarting): any cached copy beats a broken answer; 2.4.0 (#187): the quick capture page is the app shell too
  if (!r || r.status >= 500) {
    const hit = (await swAnyCache(req, opt)) || (url.pathname === '/capture' ? await swAnyCache('/', {ignoreSearch: true}) : undefined);
    if (hit) return hit;
    if (!r) throw new TypeError('network error');
  }
  return r;
}
// Android share sheet (share_target POST): keep the shared files in a cache and open the app,
// which then creates the task + uploads with the normal (login) session.
// 2.126.0 D (#1992 O6): only the system's share sheet (no referrer) or the app itself fills the capture form
function shareFromOutside(req) {
  const site = req.headers.get('Sec-Fetch-Site');
  if (site && site !== 'none' && site !== 'same-origin') return true;
  try { return !!req.referrer && req.referrer !== 'about:client' && new URL(req.referrer).origin !== self.location.origin; } catch { return true; }
}
// 2.143.0 C (#2154): every kind of file can be shared now: the name is cleaned (no path, no control characters, as the server's
// safe_name), a type that could run in the page (HTML, SVG, XML, scripts) is kept as a plain download (the server checks the
// bytes again on upload and never shows such a file inline)
const shareName = n => String(n || '').replace(/\\/g, '/').split('/').pop().replace(/[\x00-\x1f:*?"<>|]/g, '_').trim().slice(0, 150);
const shareType = t => { t = String(t || '').toLowerCase().split(';')[0].trim(); return !/^[\w.+-]+\/[\w.+-]+$/.test(t) || /^(text\/html|application\/xhtml\+xml|image\/svg\+xml|(text|application)\/(xml|javascript|ecmascript|x-javascript))$/.test(t) ? '' : t; };
// 2.143.0 C2 (#2154): the upload limit per file comes with the manifest (kept in the shell cache); 50 MB = the server's default
const SHARE_MAX_FILES = 20;
async function shareMaxMb() {
  try { const r = await caches.match('/manifest.json') || await fetch('/manifest.json'); const n = +(await r.json()).kalmido_max_file_mb; return n > 0 ? n : 50; } catch { return 50; }
}
async function handleShare(req) {
  if (shareFromOutside(req)) return Response.redirect('/', 303);
  try {
    const fd = await req.formData();
    const cache = await caches.open('tasks-share');
    for (const k of await cache.keys()) await cache.delete(k);
    const files = [...fd.values()].filter(f => typeof f !== 'string' && f.size);  // any field name
    const meta = {title: fd.get('title') || '', text: fd.get('text') || '', url: fd.get('url') || '', files: [], refused: [], max_mb: await shareMaxMb(), max_files: SHARE_MAX_FILES};
    // 2.143.0 C2 (#2154): a file above the server's upload limit or beyond the first SHARE_MAX_FILES is not kept (the app names it)
    for (let i = 0; i < files.length; i++) {
      const f = files[i], type = shareType(f.type), name = shareName(f.name) || `datei-${i + 1}`;
      if (meta.files.length >= SHARE_MAX_FILES || f.size > meta.max_mb * 1048576) { meta.refused.push({name, size: f.size}); continue; }
      await cache.put(`/share-inbox/${meta.files.length}`, new Response(f, {headers: {'Content-Type': type || 'application/octet-stream'}}));
      meta.files.push({name, type, size: f.size});
    }
    await cache.put('/share-inbox/meta', new Response(JSON.stringify(meta), {headers: {'Content-Type': 'application/json'}}));
    return Response.redirect('/?share=1', 303);
  } catch (e) {
    return Response.redirect('/?share=err', 303);
  }
}
const SW_SHELL_PATHS = new Set(['/', '/capture', '/manifest.json']);
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;  // 2.138.0 A (#2257): extensions (chrome-extension://) and other origins: the browser handles them
  if (e.request.method === 'POST' && url.pathname === '/share') { e.respondWith(handleShare(e.request)); return; }
  // /s/ = public list links: never cached (no-store pages of one list; the service worker stays out of them)
  // 2.63.0 (#1513): the same for the forms, a report's status page and the customer portal
  // 2.122.0 A (#2097): and the file requests (/u/)
  // 2.126.0 D (#1992 O4): and the calendar feed / sync addresses (private data, never kept on the device)
  // 2.238.0 B (#2872): an allow list instead: only the app shell (/, /capture, /manifest.json, /static/) is ever kept
  if (e.request.method !== 'GET' || !(SW_SHELL_PATHS.has(url.pathname) || url.pathname.startsWith('/static/'))) return;
  // 2.35.0 (#1094): language files come with the version of the code (?v=). Offline only the exact version is served as is;
  // a copy of another version is marked (X-Kalmido-I18n-Stale) so the client uses it as a stopgap and fetches it again later.
  // A response that is no JSON (a sign-in page) is never cached for a language file.
  if (url.pathname.startsWith('/static/i18n/') && url.search) { e.respondWith(swI18n(e.request)); return; }
  // network first, fall back to cache (a new deploy shows up immediately when online)
  e.respondWith(swShell(e.request, url));
});

async function swI18n(req) {
  try {
    const r = await fetch(req);
    if (r.ok && !r.redirected && r.type === 'basic' && /json/.test(r.headers.get('content-type') || '')) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {}); }  // 2.138.0 A (#2257): a refused put is no uncaught error
    return r;
  } catch (err) {
    const hit = await caches.match(req);
    if (hit) return hit;
    const old = await caches.match(req, {ignoreSearch: true});
    if (!old) throw err;
    const h = new Headers(old.headers); h.set('X-Kalmido-I18n-Stale', '1');
    return new Response(await old.blob(), {status: 200, headers: h});
  }
}

// ---- Web Push: the server sends {title, body, url ('/#t/12'), tag, prio, task, due, actions: [{action, title, url}]}
// (end-to-end encrypted, see kalmido/notify/push.py "Web Push"). Priority 5 stays on screen until dismissed. A push with the
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
  const want = new Set(tags.map(String)), all = want.has('*');  // 2.19.0 (#668): "*" = every Kalmido notification
  let n = 0;
  for (const x of await self.registration.getNotifications()) if (all || (x.tag && want.has(x.tag))) { x.close(); n++; }
  return n;
}
// 2.19.0 (#668): the number on the app icon (unread News + chat) comes with every push; 0 clears it
async function setBadge(n) {
  const nav = self.navigator;
  if (typeof n !== 'number' || !nav || !nav.setAppBadge) return;
  try { if (n > 0) await nav.setAppBadge(n); else await nav.clearAppBadge(); } catch { /* not supported here */ }
}
self.addEventListener('push', e => {
  let d;
  try { d = e.data ? e.data.json() : {}; } catch { d = {body: e.data ? e.data.text() : ''}; }
  if (d && d.type === 'dismiss') { e.waitUntil(closeTags(d.tags).catch(() => 0).then(() => setBadge(d.badge))); return; }
  e.waitUntil(closeTags(d.dismiss).catch(() => 0).then(() => self.registration.showNotification(d.title || 'Kalmido', pushOptions(d))).then(() => setBadge(d.badge)));
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
// 2.143.0 C (#2153): Background Sync of the offline queue (static/js/core.js, IndexedDB "kalmido-outbox"). An open tab sends it
// itself (with its whole conflict handling): it is only asked to. Without a tab the worker sends the entries of the user that is
// signed in on this device, in order, with the app's own request header and the session cookie, under the same Web Lock as the
// tabs. It stops at the first answer it cannot handle alone (an error, a sign-in page): that entry and the rest wait for the
// app. Ids of new tasks / notes, conflicts and skipped repeats are kept for the app (meta swmap / swres).
self.addEventListener('sync', e => { if (e.tag === 'kalmido-outbox') e.waitUntil(swOutbox()); });
const swReq = r => new Promise((ok, no) => { r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error); });
function swIdb() {
  return new Promise((ok, no) => {
    const r = indexedDB.open('kalmido-outbox', 1);
    r.onupgradeneeded = () => { const d = r.result; if (!d.objectStoreNames.contains('ops')) d.createObjectStore('ops', {keyPath: 'k'}); if (!d.objectStoreNames.contains('meta')) d.createObjectStore('meta', {keyPath: 'k'}); };
    r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error);
  });
}
const swMeta = async (db, k) => (await swReq(db.transaction('meta').objectStore('meta').get(k)))?.v;
const swPut = (db, st, v) => swReq(db.transaction(st, 'readwrite').objectStore(st).put(v));
async function swOutbox() {
  const wins = await self.clients.matchAll({type: 'window'});
  if (wins.length) { for (const w of wins) w.postMessage({type: 'outbox-flush'}); return; }
  if (!self.indexedDB) return;
  const locks = self.navigator && self.navigator.locks;
  return locks ? locks.request('kalmido-outbox', {ifAvailable: true}, l => l ? swOutboxSend() : null) : swOutboxSend();
}
const SW_OBX_URL = /^\/api\/(?!v1\/)[\w/-]+(\?[\w=&%.,-]*)?$/, SW_OBX_METHODS = ['POST', 'PATCH', 'PUT', 'DELETE'];
async function swOutboxSend() {
  const db = await swIdb(), uid = await swMeta(db, 'uid');
  if (!uid) return;
  const me = await fetch('/api/me', {credentials: 'same-origin', redirect: 'manual', headers: {'X-Requested-With': 'kalmido'}});  // offline: throws = tried again later
  if (!me.ok || !/json/.test(me.headers.get('content-type') || '') || (await me.json()).id !== uid) return;  // signed out / someone else
  const idm = {...(await swMeta(db, 'idmap') || {})}, swmap = {...(await swMeta(db, 'swmap') || {})}, res = [...(await swMeta(db, 'swres') || [])];
  Object.assign(idm, swmap);
  const fix = v => (typeof v === 'number' && v < 0 && idm[v]) ? idm[v] : v;
  const ch = typeof BroadcastChannel === 'function' ? new BroadcastChannel('kalmido-outbox') : null;
  const rows = (await swReq(db.transaction('ops').objectStore('ops').getAll())).sort((a, b) => a.n - b.n);
  try {
    for (const e of rows) {
      if (!e.uid) { await swReq(db.transaction('ops', 'readwrite').objectStore('ops').delete(e.k)); if (ch) ch.postMessage({del: [e.k], sw: true}); continue; }  // 2.306.0 D4 (#2875): an entry of nobody is dropped, never sent
      if (e.uid !== uid) continue;  // another user's entry: the app drops it
      // 2.143.0 C2 (#2153): only the app's own write routes are sent again (no API v1, no other origin, no GET)
      if (typeof e.url !== 'string' || !SW_OBX_URL.test(e.url) || !SW_OBX_METHODS.includes(e.method)) break;
      const url = e.url.replace(/\/(-\d+)(?=\/|$)/, (_, n) => '/' + (idm[n] || n));
      let body = e.body;
      if (body && typeof body === 'object') {
        body = {...body};
        if (body.parent_id) body.parent_id = fix(body.parent_id);
        if (body.task_id) body.task_id = fix(body.task_id);
        if (body.items) body.items = body.items.map(it => ({...it, id: fix(it.id)}));
        if (body.ids) body.ids = body.ids.map(fix);
        if (body.data && typeof body.data === 'object') {
          const d = {...body.data};
          for (const k of ['items', 'expect', 'guard']) if (d[k] && !Array.isArray(d[k])) d[k] = Object.fromEntries(Object.entries(d[k]).map(([id, v]) => [fix(+id), v]));
          body.data = d;
        }
      }
      // 2.359.0 A (#3023): a temporary id without its real one (its create failed or waits for the app): never sent as such
      if (/\/-\d+(?=[/?]|$)/.test(url) || (body && [body.parent_id, body.task_id, ...(body.ids || []), ...(body.items || []).map(it => it && it.id)].some(v => typeof v === 'number' && v < 0))) break;
      const opt = {method: e.method, credentials: 'same-origin', redirect: 'manual', headers: {'X-Requested-With': 'kalmido'}};
      if (e.k) opt.headers['Idempotency-Key'] = String(e.k);  // 2.270.0 C (#3022): stopped before the delete below = the tab's resend is not applied twice
      if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
      const r = await fetch(url, opt);  // offline again: throws, the browser tries again later
      // 2.359.0 A (#3023): a server error / too many requests: the browser tries the sync again later (the entry stays first)
      if (r.status >= 500 || r.status === 429 || r.status === 408) throw new Error('outbox: server error ' + r.status);
      if (!r.ok || !/json/.test(r.headers.get('content-type') || '')) break;  // for the app (its own handling of errors)
      const j = await r.json().catch(() => ({}));
      if (j.conflicts && j.conflicts.length && url === '/api/tasks/batch' && body && body.action === 'complete') { j.conflicts = []; j.skipped = true; }  // 2.270.0 C (#3022): already ticked
      if (e.tmp && j.id) { idm[e.tmp] = j.id; swmap[e.tmp] = j.id; await swPut(db, 'meta', {k: 'swmap', v: swmap}); }
      if ((j.conflicts && j.conflicts.length) || j.skipped) { res.push({id: j.id, title: j.title || '', conflicts: j.conflicts || [], skipped: !!j.skipped}); await swPut(db, 'meta', {k: 'swres', v: res}); }
      await swReq(db.transaction('ops', 'readwrite').objectStore('ops').delete(e.k));
      if (ch) ch.postMessage({del: [e.k], sw: true});
    }
  } finally { if (ch) ch.close(); }
}
self.addEventListener('pushsubscriptionchange', e => { e.waitUntil(resubscribe(e.oldSubscription, e.newSubscription).catch(() => {})); });
