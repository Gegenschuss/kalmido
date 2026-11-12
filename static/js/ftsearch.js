// @ts-check
// 2.116.0 B (#2065): the command palette's group "Everywhere": the server's ranked full-text hits (GET /api/search: tasks by
// title, notes, comments, custom fields, file texts -- also completed tasks and tasks of areas that are not loaded), below the
// local hits. From 2 characters, 250 ms after the last key; a newer query aborts the older request; offline: nothing (the
// local hits stay). Tasks the palette already lists come once. Lists with the lock are never on the server (it holds only
// ciphertexts): the local search of the palette covers them.
// 2.250.0 A (#2992): + the group "Office": clients and quotations / invoices of the office the person works in (the
// server's key office: only when the person sees the office), above the task hits; a pick opens the client / the document.
// 2.1026.0 (#5280, Q6c): "Everywhere" finds what a search of an area finds -- from ONE request (GET /api/search: the tasks + the
// groups of every kind) and the browser's sources of the end-to-end areas (SEARCH_SOURCES below), in groups below the local hits.
const FTSP = {q: '', r: null, t: 0, ctl: null};
PAL_GROUP.fts = N_('Everywhere');
PAL_GROUP.office = N_('Office');
Object.assign(PAL_GROUP, {srwiki: N_('Knowledge pages'), srfiles: N_('Files'), srcontacts: N_('Contacts'), srevents: N_('Events'), srnotes: N_('Notes'), srcomments: N_('Comments'), srbm: N_('Bookmarks')});
const BS_KIND = {client: N_('Client'), offer: N_('Quotation'), invoice: N_('Invoice'), credit: N_('Credit note'), reminder: N_('Reminder'), delivery: N_('Delivery note')};

// ---- 2.1026.0 (#5280, Q6c): ONE registry of the search. A source is {id, kinds?, search: async (q, f) => ({<kind>: [hits], …,
// more?: {<kind>: {total, next}}})}; kinds = the kinds it can give (none: every kind). The server source asks GET /api/search
// once: without f.kind the tasks + the groups of every kind (office, wiki, comments, contacts, notes, files, events, messages, bookmarks),
// with f.kind that kind alone in the shape of its old route (kept whole in raw). The areas with end-to-end texts, which the
// server cannot read, search in the browser and register here (liste2e.js: comments of locked lists = messages; wikie2e.js:
// pages of the unlocked locked spaces = wiki). Users: the command palette (ftsPalItems), msgSearch (chat.js: the chat's search
// field, the search page), wk_search (wiki.js).
const SRCH_KINDS = ['tasks', 'office', 'wiki', 'comments', 'contacts', 'notes', 'files', 'events', 'messages', 'bookmarks'];
const SRCH_ARGS = ['art', 'sender', 'room', 'agent', 'task', 'limit', 'offset', 'space', 'glimit', 'cursor'];
async function srchServer(q, f = {}) {
  const p = new URLSearchParams({q});
  if (f.kind && f.kind !== 'tasks') p.set('kind', f.kind);
  for (const k of SRCH_ARGS) if (f[k] != null && f[k] !== '') p.set(k, String(f[k]));
  const url = '/api/search?' + p;
  /** @type {any} */ let j;
  if (f.signal) { const r = await fetch(url, {headers: {'X-Requested-With': 'kalmido'}, signal: f.signal}); if (!r.ok) throw new Error(String(r.status)); j = await r.json(); }
  else j = await rawFetch('GET', url);
  if (!j) j = {};
  const k = f.kind || 'tasks';
  if (k === 'tasks') return {...(j.groups || {}), tasks: j.hits || [], more: {tasks: {next: j.next ?? null}}, raw: j};
  if (k === 'messages') return {messages: j.hits || [], more: {messages: {total: j.total || 0, next: j.next_offset ?? null}}, raw: j};
  if (k === 'files') return {files: j.items || [], raw: j};
  if (k === 'wiki') return {wiki: j.pages || [], more: {wiki: {total: j.total || 0, next: j.more ? (j.offset || 0) + (j.pages || []).length : null}}, raw: j};
  return {[k]: j[k] || [], raw: j};
}
const SEARCH_SOURCES = [{id: 'server', search: srchServer}];
// every source that can give f.kind (all of them without), merged per kind; only when every source failed, the first error
async function srchRun(q, f = {}) {
  const src = SEARCH_SOURCES.filter(s => !f.kind || !s.kinds || s.kinds.includes(f.kind));
  const rs = await Promise.allSettled(src.map(s => s.search(q, f)));
  const ok = rs.filter(r => r.status === 'fulfilled').map(r => r.value || {});
  if (!ok.length && rs.length) throw /** @type {PromiseRejectedResult} */ (rs[0]).reason;
  const out = {more: {}, raw: null};
  for (const r of ok) {
    if (r.raw && !out.raw) out.raw = r.raw;
    for (const k of SRCH_KINDS) if (Array.isArray(r[k])) out[k] = (out[k] || []).concat(r[k]);
    for (const [k, m] of Object.entries(r.more || {})) {
      const o = out.more[k] || (out.more[k] = {total: 0, next: null});
      o.total += m.total || 0; if (o.next == null && m.next != null) o.next = m.next;
    }
  }
  return out;
}
// a snippet of the server ({text, marks} or snippet + marks beside it) as HTML with its hits marked (chat.js msgSnip)
const srchSnip = (h, s = h.snippet) => s ? msgSnip(typeof s === 'object' ? {snippet: s.text, marks: s.marks} : {snippet: s, marks: h.marks}) : '';
const srchSub = (pre, snip) => esc(pre) + (pre && snip ? ' · ' : '') + snip;
// the comments of other objects: where a hit opens (its kind's address); a kind without one is not listed
const SRCH_CMT_GO = {video: r => loadModule('videos').then(() => vdr_open(r)), wiki_page: r => go('wiki/' + r), contact: r => go('contacts/' + r), event: r => go('ev/' + r), note: r => go('note/' + r), doc: r => go('docs/' + r), file: r => go('docs/' + r)};
const SRCH_CMT_KIND = {video: N_('Approval'), wiki_page: N_('Knowledge page'), contact: N_('Contact'), event: N_('Appointment'), note: N_('Note'), doc: N_('Document'), file: N_('File')};
function ftsPalItems(q, shown) {
  q = q.trim();
  if (q.length < 2 || S.me?.kid || !OUT.online || OUT.down) return [];
  if (FTSP.q !== q) {
    FTSP.q = q; FTSP.r = null; clearTimeout(FTSP.t); FTSP.ctl?.abort(); FTSP.ctl = null;
    FTSP.t = setTimeout(async () => {
      const ctl = FTSP.ctl = new AbortController();
      // glimit 6, 5 shown: a sixth hit says there are more messages ("All messages" opens the search page)
      let r; try { r = await srchRun(q, {limit: 8, glimit: 6, signal: ctl.signal}); } catch { return; }  // aborted, offline, error: no group
      if (FTSP.q !== q) return;
      FTSP.r = r;
      if ($('.palette') && PAL.q.trim() === q) palDraw();
    }, 250);
    return [];
  }
  const r = FTSP.r || {}, five = xs => (Array.isArray(xs) ? xs : []).slice(0, 5);
  const ids = shown.map(x => String(x.id)), have = new Set(ids.map(x => x.replace(/^t(id)?:/, ''))), wkHave = new Set(ids.filter(x => x.startsWith('wk:')).map(x => x.slice(3)));
  const office = (r.office || []).filter(h => /^(client|office\/offers)\/\d+$/.test(String(h.go))).map(h => ({id: 'bs:' + h.kind + ':' + h.id, kind: 'view', group: 'office', label: h.label || '…',
    sub: [tr(BS_KIND[h.kind] || 'Office'), h.sub].filter(Boolean).join(' · '), icon: h.kind === 'client' ? 'brief' : 'receipt', fn: () => go(h.go)}));
  const tasks = (r.tasks || []).filter(h => h.task && !have.has(String(h.task.id))).map(h => {
    const t = h.task, l = listById(t.list_id), snip = h.where !== 'title' && h.snippet?.text ? msgSnip({snippet: h.snippet.text, marks: h.snippet.marks}) : '';
    const pre = [l ? lname(l) : '', t.status !== 0 ? tr('Completed') : '', {comment: tr('Comment'), field: tr('Field'), file: tr('File')}[h.where] || ''].filter(Boolean).join(' · ');
    return {id: 'fts:' + t.id, kind: 'tasks', group: 'fts', label: t.title || '…', icon: 'check', subHtml: srchSub(pre, snip), fn: () => ftsOpen(h)};
  });
  const spn = sp => sp && typeof wk_spaceName === 'function' ? wk_spaceName(sp) : '';
  const wiki = five((r.wiki || []).filter(p => !wkHave.has(String(p.id)))).map(p => ({id: 'srw:' + p.id, kind: 'view', group: 'srwiki', label: p.name || String(p.path || '').split('/').pop() || '…', icon: p.e2e ? 'lock' : 'book',
    subHtml: srchSub([spn(p.space), String(p.path || '').includes('/') ? p.path.split('/').slice(0, -1).join('/') : ''].filter(Boolean).join(' · '), srchSnip(p)), fn: () => go('wiki/' + p.id)}));
  const why = h => h === 'text' ? tr('Found in the text') : h === 'doc' ? tr('Found in sender, type or tags') : '';
  const files = five(r.files).map(n => ({id: 'srf:' + n.id, kind: 'view', group: 'srfiles', label: n.name || '…', icon: n.kind === 'folder' ? 'folder' : 'file',
    subHtml: srchSub([why(n.hit), n.folder ? tr('in {0}', n.folder) : ''].filter(Boolean).join(' · '), srchSnip(n)), fn: () => go((n.kind === 'folder' ? 'ablage/' : 'docs/') + n.id)}));
  const contacts = five(r.contacts).map(c => ({id: 'src:' + c.id, kind: 'view', group: 'srcontacts', label: c.fn || c.org || '…', icon: 'user',
    subHtml: srchSub([c.fn && c.org ? c.org : '', c.email || c.phone || ''].filter(Boolean).join(' · '), srchSnip(c)), fn: () => go('contacts/' + c.id)}));
  const events = five(r.events).map(e => ({id: 'sre:' + e.id, kind: 'view', group: 'srevents', label: e.title || '…', icon: 'cal',
    subHtml: srchSub([e.start ? (e.all_day ? dayLabel(String(e.start).slice(0, 10)) : fmtWhen(e.start)) : '', e.location || '', e.role === 'attendee' ? tr('Invitation') : ''].filter(Boolean).join(' · '), srchSnip(e)),
    fn: () => go('ev/' + e.id)}));
  const notes = five(r.notes).map(n => ({id: 'srn:' + n.id, kind: 'view', group: 'srnotes', label: n.title || '…', icon: 'edit',
    subHtml: srchSub(lname(listById(n.list_id)) || '', srchSnip(n)), fn: () => srchNoteGo(n)}));
  const ms = (r.messages || []).slice().sort((a, b) => (b.created_at || '').localeCompare(a.created_at || '') || b.id - a.id);
  const msgs = ms.slice(0, 5).map((h, i) => ({id: 'msg:' + h.art + h.id + ':' + i, kind: 'msg', group: 'msgs', label: `${h.sender?.name || '?'} · ${h.chat_name || tr(MSG_KIND[h.chat_type])}`, subHtml: msgSnip(h), icon: msgIcon(h), fn: () => msgOpen(h)}));
  if (ms.length > 5) msgs.push({id: 'msg:all', kind: 'msg', group: 'msgs', label: tr('All messages'), icon: 'search', fn: () => { go('search'); setTimeout(() => { const i = $('#searchq'); if (i) i.value = q; doSearch(q); }, 0); }});
  const comments = five((r.comments || []).filter(c => SRCH_CMT_GO[c.kind])).map(c => ({id: 'srk:' + c.id, kind: 'view', group: 'srcomments', label: tr(SRCH_CMT_KIND[c.kind] || 'Comment'), icon: 'comment',
    subHtml: srchSnip(c), fn: () => SRCH_CMT_GO[c.kind](c.ref_id)}));
  const bms = five(r.bookmarks).map(b => ({id: 'srb:' + b.id, kind: 'view', group: 'srbm', label: b.title || b.url || '…', icon: 'bookmark',
    sub: b.site || '', fn: () => { go('bookmarks'); loadModule('bookmarks').then(() => bm_detail(b.id)); }}));  // the bookmark's card over its view
  return [...office, ...tasks, ...wiki, ...files, ...contacts, ...events, ...notes, ...bms, ...msgs, ...comments];
}
// a note the state does not list yet (shared meanwhile): its entry first, so #note/<id> opens it (core.js parseHash looks it up there)
function srchNoteGo(n) {
  if (!(S.notes || []).some(x => x.id === n.id) && n.list_id) S.notes = [{id: n.id, list_id: n.list_id, title: n.title || '', tags: n.tags || [], pinned: !!n.pinned, updated_at: n.updated_at || ''}, ...(S.notes || [])];
  go('note/' + n.id);
}
async function ftsOpen(h) {
  const tid = h.task.id;
  if (h.where === 'comment' && h.comment_id) return window.msgJump?.({art: 'c', id: h.comment_id, task: tid});  // opens + shows the comment
  openDetail(tid);  // 2.509.0 (#4324): fetches a task that is not loaded
}
