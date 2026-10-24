/* Kalmido web client: feeds (module "feeds", part of the area Reading since 2.172.0, loaded on demand: lazyload.js LD_MODS, styles in
   static/css/feeds.css): the view "Feeds" (follow a feed, OPML import /
   export, the articles with "Read later") and the card on Home & life.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.85.0 B (#1162): the server fetches every feed about once an hour (life/rss.py) and keeps the articles 30 days. Titles and
// summaries come as plain text (always esc()), links only http(s); no pictures, no foreign HTML. Feeds are the person's own
// (never shared, never an agent's). "Read later" makes a task in the reading list, once per article.
// 2.172.0 B (#2677): feeds live in a space -- the view shows the feeds of the shown workspace only (rd_space: Private or an
// organisation; under "All workspaces" Private or the one picked here); an organisation's sources are managed by its admins
// (manage), every member reads them with an own read mark. "Read later" lands in the article's space.
const RSS = {feeds: null, items: [], more: false, unread: 0, feed: 0, only: false, loading: false, done: false, seq: 0, busy: false, at: 0,  // at: when loaded (older than a minute = again on the next draw)
  space: '', sp: '', manage: true};  // 2.172.0 B (#2677): space = picked under "All workspaces", sp = the space loaded
const rss_sp = () => rd_space(RSS.space);
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
  } catch (e) { if (seq === RSS.seq && e.status === 404) { RSS.feed = 0; RSS.space = ''; } }
  if (seq !== RSS.seq) return;
  RSS.loading = false; RSS.done = true; RSS.at = Date.now();
  rss_draw();
}
function rss_draw() {
  if (S.route.mod === 'feeds') { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('feeds', viewFeeds()))); }
  if (S.route.mod === 'life' && typeof viewLife === 'function') { const el = $('#view'); if (el && typeof LF !== 'undefined' && LF.data) keepFocus(el, () => setHtml(el, mg_wrap('life', viewLife()))); }
}
const rss_reload = () => rss_load(false);
const rss_stale = () => !RSS.loading && (!RSS.done || Date.now() - RSS.at > 60000 || RSS.sp !== rss_sp());

// ---- the card on Home & life
function rss_homeCard() {
  if (rss_stale()) setTimeout(rss_reload, 0);
  const n = RSS.unread || 0;
  const top = RSS.items.filter(x => !x.read).slice(0, 4);
  const body = !RSS.done ? `<p class="muted">${tr('Loading…')}</p>`
    : !(RSS.feeds || []).length ? `<p class="muted">${tr('Follow blogs and news sites: their new articles show up here.')}</p>`
    : top.length ? `<ul class="flist">${top.map(x => `<li><a href="#feeds" class="frow"><span class="ft"><b>${esc(x.title)}</b><span class="muted">${esc([x.feed, rss_when(x.published)].filter(Boolean).join(' · '))}</span></span></a></li>`).join('')}</ul>`
    : `<p class="muted">${tr('Nothing new to read.')}</p>`;
  return `<section class="dcard fcard lcard lc-feeds" aria-labelledby="lh-feeds"><h2 id="lh-feeds">${ic('news', 's')}<span>${esc(tr('Feeds|panel'))}</span>${n ? `<span class="dcn">${n}</span>` : ''}<span class="spacer"></span></h2>${body}<div class="fcfoot"><a class="btn sm" href="#feeds">${ic('news', 's')}<span>${tr('Open')}</span></a></div></section>`;
}

// ---- the view
function viewFeeds() {
  if (rss_stale()) setTimeout(rss_reload, 0);
  const spSel = rd_pick(rss_sp(), 'data-rss-space');  // 2.172.0 B (#2677): only under "All workspaces"
  const add = !RSS.manage ? `<p class="muted rssro">${ic('lock', 's')} ${esc(tr('The admins of the organisation choose its feeds.'))}</p>` : `<form class="rssadd" data-rss-form><label class="sr" for="rss-url">${tr('Feed address')}</label><input id="rss-url" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('Feed address'))}" maxlength="2000"><button type="submit" class="btn pri" data-rss-addbtn ${RSS.busy ? 'disabled' : ''}>${ic('plus', 's')}<span>${tr('Follow')}</span></button></form>`;
  const imp = RSS.manage ? `<label class="rssmi" role="menuitem" tabindex="0">${ic('upload', 's')}<span>${tr('Import OPML file')}</span><input type="file" accept=".opml,.xml,text/xml,application/xml,text/x-opml" data-rss-opml hidden></label>` : '';
  const exp = (RSS.feeds || []).length ? `<a role="menuitem" href="/api/feeds/opml?space=${encodeURIComponent(rss_sp())}" download="kalmido-feeds.opml">${ic('download', 's')}<span>${tr('Export OPML file')}</span></a>` : '';
  const menu = imp || exp ? `<details class="bgmenu rssmenu"><summary class="iconbtn" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</summary><div class="bgmenul" role="menu">
    ${imp}${exp}</div></details>` : '';
  const head = `<div class="rsshead">${spSel}${add}${menu}</div>`;
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
  offerUndo(tr('Unfollowed: {0}', f.title), histAdd({label: tr('Unfollow feed “{0}”', f.title),
    undo: async () => { await api('POST', `/api/feeds/${id}/restore`, {}); await rss_reload(); },
    redo: async () => { await api('DELETE', `/api/feeds/${id}`); await rss_reload(); }}));
  await rss_reload();
}
async function rss_mark(ids, read) {
  const j = await api('POST', '/api/feeds/read', {ids, read, space: rss_sp()});
  for (const id of j.ids) { const x = rss_item(id); if (x) x.read = read; }
  RSS.unread = Math.max(0, RSS.unread + (read ? -j.ids.length : j.ids.length));
  for (const f of RSS.feeds || []) f.unread = Math.max(0, f.unread + (read ? -1 : 1) * RSS.items.filter(x => j.ids.includes(x.id) && x.feed_id === f.id).length);
  rss_draw();
  return j.ids;
}
async function rss_allRead() {
  const space = rss_sp();
  const j = await api('POST', '/api/feeds/read', RSS.feed ? {feed_id: RSS.feed, read: true, space} : {read: true, space});
  if (!j.ids.length) return;
  let ids = j.ids;
  offerUndo(trn('{0} article marked read', '{0} articles marked read', ids.length), histAdd({label: tr('Mark all read'),
    undo: async () => { await api('POST', '/api/feeds/read', {ids, read: false, space}); await rss_reload(); },
    redo: async () => { ids = (await api('POST', '/api/feeds/read', {ids, read: true, space})).ids; await rss_reload(); }}));
  await rss_reload();
}
async function rss_later(id) {
  const x = rss_item(id); if (!x) return;
  const j = await api('POST', `/api/feeds/items/${id}/later`, {});
  x.task_id = j.task_id; if (!x.read) { x.read = true; RSS.unread = Math.max(0, RSS.unread - 1); }
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
  else if (e.target.matches?.('[data-rss-space]')) { RSS.space = e.target.value; RSS.feed = 0; RSS.items = []; rss_reload(); }  // 2.172.0 B (#2677)
  else if (e.target.matches?.('[data-rss-opml]') && e.target.files.length) { const fl = e.target.files[0]; e.target.closest('details')?.removeAttribute('open'); e.target.value = ''; rss_opml(fl); }
});
document.addEventListener('keydown', e => {  // the label of the file input acts as a button
  const l = e.target.closest?.('.rssmi'); if (!l || (e.key !== 'Enter' && e.key !== ' ')) return;
  e.preventDefault(); $('input[type=file]', l)?.click();
});
document.addEventListener('click', async e => {
  const o = e.target.closest?.('[data-rss-open]');
  if (o) { const x = rss_item(+o.dataset.rssOpen); if (x && !x.read) rss_mark([x.id], true).catch(() => {}); return; }  // the link opens as usual
  const a = e.target.closest?.('[data-rss]'); if (!a || a.disabled) return;
  e.preventDefault();
  const k = a.dataset.rss, id = +a.dataset.id || 0;
  a.disabled = true;
  try {
    if (k === 'only') { RSS.only = !RSS.only; RSS.items = []; await rss_reload(); }
    else if (k === 'more') await rss_load(true);
    else if (k === 'allread') await rss_allRead();
    else if (k === 'read') { const x = rss_item(id); if (x) await rss_mark([id], !x.read); }
    else if (k === 'later') await rss_later(id);
    else if (k === 'del') await rss_del(id);
  } catch { /* api() showed it */ }
  a.disabled = false;
});
