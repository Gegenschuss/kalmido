/* Kalmido web client: feeds (module "feeds", part of the area Reading since 2.172.0, loaded on demand: lazyload.js LD_MODS, styles in
   static/css/feeds.css): the view "Feeds" (follow a feed, OPML import /
   export, the articles with "Read later") and the card on Home & life.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.85.0 B (#1162): the server fetches every feed about once an hour (life/rss.py) and keeps the articles 30 days. Titles and
// summaries come as plain text (always esc()), links only http(s); no pictures, no foreign HTML. Feeds are the person's own
// (never shared, never an agent's). "Read later" makes a task in the reading list, once per article.
// 2.172.0 B (#2677): feeds live in a space -- the view shows the feeds of the shown workspace only (rd_space: Private or an
// organisation; under "All workspaces" the one opened from the overview, 2.540.0 #4588); an organisation's sources are managed by its admins
// (manage), every member reads them with an own read mark. "Read later" lands in the article's space.
const RSS = {feeds: null, items: [], more: false, unread: 0, feed: 0, only: false, loading: false, done: false, seq: 0, busy: false, at: 0,  // at: when loaded (older than a minute = again on the next draw)
  sp: '', manage: true};  // 2.172.0 B (#2677): sp = the space loaded
const rss_sp = () => rd_space();
const rss_href = u => /^https?:\/\//i.test(u || '') ? u : '';
const rss_when = s => { if (!s) return ''; const d = new Date(s); if (isNaN(d)) return ''; const n = Math.round((Date.now() - d) / 60000); return n < 60 ? trn('{0} min ago', '{0} min ago', Math.max(1, n)) : n < 1440 ? trn('{0} h ago', '{0} h ago', Math.round(n / 60)) : fmtDateLoc(rss_day(d)); };
const rss_day = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// ---- loading
async function rss_load(more) {
  const seq = ++RSS.seq; RSS.loading = true;
  const sp = rss_sp();
  if (sp !== RSS.sp) { RSS.feed = 0; more = false; }
  try {
    const q = new URLSearchParams({space: sp});
    if (RSS.feed) q.set('feed', RSS.feed);
    if (RSS.only) q.set('unread', '1');
    if (more) q.set('offset', RSS.items.length);
    const [f, j] = await Promise.all([more ? Promise.resolve(null) : api('GET', '/api/feeds?space=' + encodeURIComponent(sp)), api('GET', '/api/feeds/items?' + q)]);
    if (seq !== RSS.seq) return;
    if (f) { RSS.feeds = f.feeds; RSS.max = f.max; RSS.manage = f.manage !== false; }
    RSS.sp = sp;
    RSS.items = more ? RSS.items.concat(j.items) : j.items; RSS.more = j.more; RSS.unread = j.unread;
    for (const p of OPT) p.put();  // 2.559.0 (#4660): own changes still on the way stay on top of the fresh list
  } catch (e) { if (seq === RSS.seq && e.status === 404) { RSS.feed = 0; if (rd_open() && S.route.mod === 'feeds') go('feeds'); } }  // 2.540.0 (#4588): a space not open to me: the overview
  if (seq !== RSS.seq) return;
  RSS.loading = false; RSS.done = true; RSS.at = Date.now();
  rss_draw();
}
function rss_draw() {
  if (S.route.mod === 'feeds') { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('feeds', viewFeeds()))); }
  if (S.route.mod === 'life' && typeof viewLife === 'function') { const el = $('#view'); if (el && typeof LF !== 'undefined' && LF.data) keepFocus(el, () => setHtml(el, mg_wrap('life', viewLife()))); }
}
const rss_reload = () => rss_load(false);
// 2.979.0 (#5667): an undo / redo the server did (undo.js histRedraw): the feeds shown (view or the card on Home & life) come again, else they are old (the next draw fetches)
histReloader('feeds', () => { if (!RSS.done) return; if (S.route.mod === 'feeds' || S.route.mod === 'life') return rss_reload(); RSS.at = 0; });
const rss_stale = () => !RSS.loading && (!RSS.done || Date.now() - RSS.at > 60000 || RSS.sp !== rss_sp());

// ---- the card on Home & life
function rss_homeCard() {
  if (rss_stale()) setTimeout(rss_reload, 0);
  const n = RSS.unread || 0;
  const top = RSS.items.filter(x => !x.read).slice(0, 4);
  const body = !RSS.done ? `<p class="muted">${tr('Loading…')}</p>`
    : !(RSS.feeds || []).length ? `<p class="muted">${tr('Follow blogs and news sites: their new articles show up here.')}</p>`
    : top.length ? `<ul class="flist">${top.map(x => `<li><a href="#${esc(rd_home('feeds'))}" class="frow"><span class="ft"><b>${esc(x.title)}</b><span class="muted">${esc([x.feed, rss_when(x.published)].filter(Boolean).join(' · '))}</span></span></a></li>`).join('')}</ul>`
    : `<p class="muted">${tr('Nothing new to read.')}</p>`;
  return `<section class="dcard fcard lcard lc-feeds" aria-labelledby="lh-feeds"><h2 id="lh-feeds">${ic('news', 's')}<span>${esc(tr('Feeds|panel'))}</span>${n ? `<span class="dcn">${n}</span>` : ''}<span class="spacer"></span></h2>${body}<div class="fcfoot"><a class="btn sm" href="#${esc(rd_home('feeds'))}">${ic('news', 's')}<span>${tr('Open')}</span></a></div></section>`;
}

// ---- the view
function viewFeeds() {
  if (rd_ovr()) return `<div class="rssview">${rd_ovrHtml('feeds')}</div>`;  // 2.540.0 (#4588): "All workspaces": the spaces first
  if (rss_stale()) setTimeout(rss_reload, 0);
  const add = !RSS.manage ? `<p class="muted rssro">${ic('lock', 's')} ${esc(tr('The admins of the organisation select its feeds.'))}</p>` : `<form class="rssadd" data-rss-form><label class="sr" for="rss-url">${tr('Feed address')}</label><input id="rss-url" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('Feed address'))}" maxlength="2000"><button type="submit" class="btn pri" data-rss-addbtn ${RSS.busy ? 'disabled' : ''}>${ic('plus', 's')}<span>${tr('Follow')}</span></button></form>`;
  // 2.1012.0 (#5690): the shared menu() (opened by data-rss="omenu" below); the hidden file field stays in the view, its entry clicks it
  const imp = RSS.manage ? `<input type="file" accept=".opml,.xml,text/xml,application/xml,text/x-opml" data-rss-opml hidden tabindex="-1" aria-hidden="true">` : '';
  const menu = RSS.manage || (RSS.feeds || []).length ? `<button type="button" class="iconbtn" data-rss="omenu" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button>${imp}` : '';
  const head = `${rd_crumb('feeds')}<div class="rsshead">${add}${menu}</div>`;
  if (!RSS.done) return `<div class="rssview">${head}<p class="muted lempty">${tr('Loading…')}</p></div>`;
  const feeds = RSS.feeds || [];
  if (!feeds.length) return `<div class="rssview">${head}<div class="empty nempty">${ic('news')}<span>${RSS.manage ? tr('No feeds yet. Paste an address above or import OPML.') : tr('No feeds in this organisation yet.')}</span></div></div>`;
  const pick = `<div class="rssbar"><select data-rss-feed aria-label="${esc(tr('Feed'))}"><option value="0">${esc(tr('All feeds'))}</option>${feeds.map(f => `<option value="${f.id}" ${f.id === RSS.feed ? 'selected' : ''}>${esc(f.title)}${f.unread ? ` (${f.unread})` : ''}</option>`).join('')}</select>
    <button type="button" class="btn sm ${RSS.only ? 'on' : ''}" data-rss="only" aria-pressed="${RSS.only}">${tr('Unread only')}</button>
    <span class="spacer"></span><button type="button" class="btn sm" data-rss="allread" ${RSS.unread ? '' : 'disabled'}>${ic('check', 's')}<span>${tr('Mark all read')}</span></button></div>`;
  const row = x => {
    const u = rss_href(x.url);
    return `<li class="rssitem ${x.read ? 'read' : 'unread'}" data-id="${x.id}"><div class="rsst">${u ? `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" data-rss-open="${x.id}"><b>${esc(x.title)}</b></a>` : `<b>${esc(x.title)}</b>`}
      <span class="muted rssmeta">${esc([x.feed, rss_when(x.published)].filter(Boolean).join(' · '))}</span>${x.summary ? `<p class="rsssum">${esc(x.summary)}</p>` : ''}</div>
      <div class="rssacts">${u ? `<a class="btn sm" href="${esc(u)}" target="_blank" rel="noopener noreferrer" data-rss-open="${x.id}">${ic('link', 's')}<span>${tr('Open')}</span></a>` : ''}
      <button type="button" class="btn sm" data-rss="later" data-id="${x.id}" ${x.task_id ? 'aria-pressed="true"' : ''}>${ic(x.task_id ? 'check' : 'bookmark', 's')}<span>${x.task_id ? tr('Saved') : tr('Read later')}</span></button>
      <button type="button" class="btn sm" data-rss="read" data-id="${x.id}">${ic(x.read ? 'eye' : 'check', 's')}<span>${x.read ? tr('Unread') : tr('Read|done')}</span></button></div></li>`;
  };
  const list = RSS.items.length ? `<ul class="rsslist">${RSS.items.map(row).join('')}</ul>${RSS.more ? `<button type="button" class="btn rssmore" data-rss="more">${tr('Show more')}</button>` : ''}`
    : `<p class="muted lempty">${RSS.only ? tr('Nothing new to read.') : tr('No articles yet. New ones are fetched about once an hour.')}</p>`;
  const mng = `<details class="rssfeeds"><summary>${tr('Manage feeds')} <span class="muted">${feeds.length} / ${RSS.max || 100}</span></summary><ul class="rssfl">${feeds.map(f => `<li><span class="rssfn"><b>${esc(f.title)}</b><span class="muted">${esc(f.error ? f.error : f.last_ok ? tr('fetched {0}', rss_when(f.last_ok)) : tr('waiting for the first fetch'))}</span></span>${RSS.manage ? `<button type="button" class="iconbtn" data-rss="del" data-id="${f.id}" aria-label="${esc(tr('Unfollow {0}', f.title))}" title="${esc(tr('Unfollow'))}">${ic('trash', 's')}</button>` : ''}</li>`).join('')}</ul></details>`;
  return `<div class="rssview">${head}${pick}${list}${mng}</div>`;
}

// ---- actions
const rss_item = id => RSS.items.find(x => x.id === id);
// 2.1151.0 C (#3835): on a phone the buttons of an article are hidden (feeds.css): a long press opens their menu
ms_rowMenu('#view .rssitem', r => ms_btnMenu(r, '.rssacts .btn', rss_item(+r.dataset.id)?.title));
async function rss_add(url) {
  RSS.busy = true; rss_draw();
  try {
    const j = await api('POST', '/api/feeds', {url, space: rss_sp()});
    const f = j.feed;
    offerUndo(tr('Following: {0}', f.title), histAdd({label: tr('Follow feed “{0}”', f.title),
      undo: async () => { await api('DELETE', `/api/feeds/${f.id}`); await rss_reload(); },
      redo: async () => { await api('POST', `/api/feeds/${f.id}/restore`, {}); await rss_reload(); }}));
    RSS.busy = false; await rss_reload();
    return true;
  } catch { RSS.busy = false; rss_draw(); return false; }  // api() showed the reason
}
async function rss_del(id) {
  const f = (RSS.feeds || []).find(x => x.id === id); if (!f) return;
  await api('DELETE', `/api/feeds/${id}`);
  if (RSS.feed === id) RSS.feed = 0;
  offerUndo(tr('Unfollowed: {0}', f.title), histAdd({label: tr('Unfollow feed “{0}”', f.title), srv: true,  // 2.809.0 (#5476): life/rssundo.py
    undo: async () => { await api('POST', `/api/feeds/${id}/restore`, {}); await rss_reload(); },
    redo: async () => { await api('DELETE', `/api/feeds/${id}`); await rss_reload(); }}));
  await rss_reload();
}
// 2.559.0 (#4660): read / unread shows at once (the article, the unread counts of the view, the feed choice and the card on
// Home & life), the request runs behind it; a refusal puts the old marks and counts back (api() said why). Idempotent: an
// article already marked is left alone, so a state arriving meanwhile (optWrite puts again) counts nothing twice.
const rss_readPut = (ids, read) => () => {
  const ch = ids.map(rss_item).filter(x => x && !!x.read !== read);
  if (!ch.length) return null;
  const d = read ? -1 : 1, fu = (RSS.feeds || []).map(f => [f, f.unread]), u0 = RSS.unread;
  for (const x of ch) x.read = read;
  RSS.unread = Math.max(0, RSS.unread + d * ch.length);
  for (const f of RSS.feeds || []) f.unread = Math.max(0, (f.unread || 0) + d * ch.filter(x => x.feed_id === f.id).length);
  return () => { for (const x of ch) x.read = !read; RSS.unread = u0; for (const [f, n] of fu) f.unread = n; };
};
let rss_q = Promise.resolve();  // the marks go out one after the other: read and back quickly reach the server in this order
async function rss_mark(ids, read) {
  const want = ids.filter(id => { const x = rss_item(id); return x && !!x.read !== read; });
  const sp = rss_sp(), go = () => api('POST', '/api/feeds/read', {ids, read, space: sp});
  const j = await optWrite(rss_readPut(ids, read), () => (rss_q = rss_q.catch(() => {}).then(go)), rss_draw, {mod: true});
  // the server changed others than shown (another device was quicker): its counts in the background
  if (j.ids.length !== want.length || j.ids.some(id => !want.includes(id))) rss_reload();
  return j.ids;
}
// 2.559.0 (#4660): "Mark all read" marks the shown articles at once (of the chosen feed, or all) and the counts go to 0; the
// list comes again in the background (articles not loaded yet are the server's); a refusal puts everything back
const rss_allPut = feed => () => {
  const ch = RSS.items.filter(x => !x.read && (!feed || x.feed_id === feed)), fs = (RSS.feeds || []).filter(f => !feed || f.id === feed);
  if (!ch.length && !fs.some(f => f.unread)) return null;
  const fu = (RSS.feeds || []).map(f => [f, f.unread]), u0 = RSS.unread;
  for (const x of ch) x.read = true;
  RSS.unread = feed ? Math.max(0, RSS.unread - (fs[0]?.unread || 0)) : 0;
  for (const f of fs) f.unread = 0;
  return () => { for (const x of ch) x.read = false; RSS.unread = u0; for (const [f, n] of fu) f.unread = n; };
};
async function rss_allRead() {
  const space = rss_sp(), feed = RSS.feed;
  const j = await optWrite(rss_allPut(feed), () => api('POST', '/api/feeds/read', feed ? {feed_id: feed, read: true, space} : {read: true, space}), rss_draw, {mod: true});
  rss_reload();  // in the background
  if (!j.ids.length) return;
  let ids = j.ids;
  offerUndo(trn('{0} article marked read', '{0} articles marked read', ids.length), histAdd({label: tr('Mark all read'),
    undo: async () => { await api('POST', '/api/feeds/read', {ids, read: false, space}); await rss_reload(); },
    redo: async () => { ids = (await api('POST', '/api/feeds/read', {ids, read: true, space})).ids; await rss_reload(); }}));
}
// 2.559.0 (#4660): "Read later" says "Saved" at once (the article counts as read), the request runs behind it; a refusal
// puts button and mark back. The undo step comes with the answer (it needs the task's id).
const rss_laterPut = id => () => {
  const x = rss_item(id); if (!x || x.task_id) return null;
  const was = !!x.read; x.task_id = -1;
  if (!was) { x.read = true; RSS.unread = Math.max(0, RSS.unread - 1); const f = (RSS.feeds || []).find(f => f.id === x.feed_id); if (f) f.unread = Math.max(0, (f.unread || 0) - 1); }
  return () => {
    const y = rss_item(id); if (!y || y.task_id !== -1) return;
    y.task_id = null;
    if (!was) { y.read = false; RSS.unread++; const f = (RSS.feeds || []).find(f => f.id === y.feed_id); if (f) f.unread = (f.unread || 0) + 1; }
  };
};
async function rss_later(id) {
  const x = rss_item(id); if (!x) return;
  const j = await optWrite(rss_laterPut(id), () => api('POST', `/api/feeds/items/${id}/later`, {}), rss_draw, {mod: true});
  const y = rss_item(id) || x;
  y.task_id = j.task_id; if (!y.read) { y.read = true; RSS.unread = Math.max(0, RSS.unread - 1); }
  rss_draw();
  if (!j.created) { toast(tr('Already in your reading list')); return; }
  let tid = j.task_id;
  offerUndo(tr('Saved to “Read later”'), histAdd({label: tr('Read later: {0}', x.title),
    undo: async () => { await api('DELETE', `/api/tasks/${tid}`); x.task_id = null; rss_draw(); },
    redo: async () => { tid = (await api('POST', `/api/feeds/items/${id}/later`, {})).task_id; x.task_id = tid; rss_draw(); }}));
}
async function rss_opml(file) {
  const space = rss_sp();
  if (!await importTargetConfirm({what: tr('the feeds'), ws: space})) return;  // 2.87.9 (#1940); 2.172.0 B (#2677): the shown space
  const fd = new FormData(); fd.append('file', file, file.name); fd.append('space', space);
  try {
    const j = await api('POST', '/api/feeds/opml', fd);
    toast(tr('OPML: {0} new, {1} already there, {2} not taken', j.added, j.skipped, j.errors));
    await rss_reload();
  } catch { /* api() showed it */ }
}

document.addEventListener('submit', async e => {
  const f = e.target.closest?.('[data-rss-form]'); if (!f) return;
  e.preventDefault();
  const inp = $('#rss-url', f), v = inp.value.trim(); if (!v || RSS.busy) return;
  if (await rss_add(v)) { const i = $('#rss-url'); if (i) i.value = ''; } else $('#rss-url')?.focus();
});
document.addEventListener('change', e => {
  if (e.target.matches?.('[data-rss-feed]')) { RSS.feed = +e.target.value || 0; RSS.items = []; rss_reload(); }
  else if (e.target.matches?.('[data-rss-opml]') && e.target.files.length) { const fl = e.target.files[0]; e.target.value = ''; rss_opml(fl); }
});
// 2.1012.0 (#5690): the "..." menu of the feeds: import clicks the hidden file field, export downloads by fn (no link in the menu)
function rss_omenu(anchor) {
  menu(anchor, [
    RSS.manage ? {label: tr('Import OPML file'), icon: 'upload', fn: () => $('[data-rss-opml]')?.click()} : null,
    (RSS.feeds || []).length ? {label: tr('Export OPML file'), icon: 'download', fn: () => { const l = document.createElement('a'); l.href = `/api/feeds/opml?space=${encodeURIComponent(rss_sp())}`; l.download = 'kalmido-feeds.opml'; document.body.appendChild(l); l.click(); l.remove(); }} : null,
  ].filter(Boolean), null, null, tr('More'));
}
document.addEventListener('click', async e => {
  const o = e.target.closest?.('[data-rss-open]');
  if (o) { const x = rss_item(+o.dataset.rssOpen); if (x && !x.read) rss_mark([x.id], true).catch(() => {}); return; }  // the link opens as usual
  const a = e.target.closest?.('[data-rss]'); if (!a || a.disabled) return;
  e.preventDefault();
  const k = a.dataset.rss, id = +a.dataset.id || 0;
  a.disabled = true;
  try {
    if (k === 'omenu') rss_omenu(a);
    else if (k === 'only') { RSS.only = !RSS.only; RSS.items = []; await rss_reload(); }
    else if (k === 'more') await rss_load(true);
    else if (k === 'allread') await rss_allRead();
    else if (k === 'read') { const x = rss_item(id); if (x) await rss_mark([id], !x.read); }
    else if (k === 'later') await rss_later(id);
    else if (k === 'del') await rss_del(id);
  } catch { /* api() showed it */ }
  a.disabled = false;
});
