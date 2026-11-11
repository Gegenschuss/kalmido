/* Kalmido web client: bookmarks (part of the module "reading", area Reading since 2.172.0, loaded on demand: lazyload.js LD_MODS, styles in
   static/css/bookmarks.css): the view "Bookmarks" (save a link, cards or a list, search, tags, read / archived, a note,
   the reading text, move to another workspace), saving from the share sheet / the bookmarklet.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.97.0 A (#1950): the server fetches the preview (title, description, picture, the plain reading text) in the background
// (life/bookmarks.py) -- while one is pending the view looks again a few times. Everything comes as plain text (always esc()),
// links only http(s); the picture is the app's own copy (/api/bookmarks/<id>/image). A bookmark lives in a space like a
// table: private, or an organisation's (every member reads it, its owner / the organisation's admins change it).
const BM = {items: [], more: false, tags: [], count: 0, q: '', tag: '', state: '', done: false, loading: false, seq: 0,
  busy: false, at: 0, polls: 0, pollT: 0};
const bm_href = u => /^https?:\/\//i.test(u || '') ? u : '';
const bm_view = () => LS.get('bmView', 'cards') === 'list' ? 'list' : 'cards';
const bm_sp = () => rd_space();  // 2.172.0 B (#2679): the shown workspace only, no mixed view; 2.540.0 (#4588): under "All workspaces" the one opened from the overview
const bm_addSp = () => { const s = bm_sp(); return s === 'all' ? 'private' : s; };
const bm_spOrg = sp => sp && sp !== 'private' ? +sp.slice(4) : null;
const BM_STATES = [['', N_('Unread and read')], ['unread', N_('Unread')], ['read', N_('Read|bookmark')], ['archived', N_('Archived')], ['all', N_('All')]];

// ---- loading
async function bm_load(more) {
  const seq = ++BM.seq; BM.loading = true;
  try {
    const sp = bm_sp(), q = new URLSearchParams({space: sp});
    if (BM.sp && sp !== BM.sp) BM.tag = '';  // 2.540.0 (#4588): another space opened (was the picker's change): its own tags
    if (BM.q) q.set('q', BM.q);
    if (BM.tag) q.set('tag', BM.tag);
    if (BM.state) q.set('state', BM.state);
    if (more) q.set('offset', BM.items.length);
    const j = await api('GET', '/api/bookmarks?' + q);
    if (seq !== BM.seq) return;
    BM.items = more ? BM.items.concat(j.items) : j.items; BM.more = j.more; BM.tags = j.tags; BM.count = j.count; BM.sp = sp;
    for (const p of OPT) p.put();  // 2.559.0 (#4660): own changes still on the way stay on top of the fresh list
  } catch (e) { if (seq === BM.seq && e.status === 404 && rd_open()) go('bookmarks'); }  // 2.540.0 (#4588): a space not open to me: the overview
  if (seq !== BM.seq) return;
  BM.loading = false; BM.done = true; BM.at = Date.now();
  bm_draw();
  bm_poll();
}
function bm_draw() {
  if (S.route.mod !== 'bookmarks') return;
  const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('bookmarks', viewBookmarks())));
}
const bm_reload = () => bm_load(false);
// a preview still being fetched: look again (2 s, then slower; at most 12 times per pending batch)
function bm_poll() {
  clearTimeout(BM.pollT);
  if (!BM.items.some(x => x.preview === 'pending' || x.preview === 'image')) { BM.polls = 0; return; }
  if (BM.polls >= 12) return;
  BM.pollT = setTimeout(() => { BM.polls++; if (S.route.mod === 'bookmarks' && !document.hidden) bm_reload(); }, BM.polls < 4 ? 2000 : 5000);
}

// ---- the view
function viewBookmarks() {
  if (rd_ovr()) return `<div class="bmview">${rd_ovrHtml('bookmarks')}</div>`;  // 2.540.0 (#4588): "All workspaces": the spaces first
  if (!BM.loading && (!BM.done || Date.now() - BM.at > 60000 || BM.sp !== bm_sp())) setTimeout(bm_reload, 0);  // 2.172.0 B (#2679): + another workspace shown
  const add = `<form class="bmadd" data-bm-form><label class="sr" for="bm-url">${tr('Link')}</label><input id="bm-url" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('Paste a link'))}" maxlength="2000"><button type="submit" class="btn pri" ${BM.busy ? 'disabled' : ''}>${ic('plus', 's')}<span>${tr('Add')}</span></button></form>`;
  const menu = `<details class="bgmenu bmmenu"><summary class="iconbtn" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</summary><div class="bgmenul" role="menu">
    <button type="button" role="menuitem" data-bm="bmlet">${ic('bookmark', 's')}<span>${tr('Save button for the browser')}</span></button>
    <button type="button" role="menuitem" data-bm="kk">${ic('link', 's')}<span>${tr('Karakeep…')}</span></button></div></details>`;
  const view = bm_view();
  const bar = `<div class="bmbar"><input type="search" class="bmq" data-bm-q value="${esc(BM.q)}" placeholder="${esc(tr('Search bookmarks'))}" aria-label="${esc(tr('Search bookmarks'))}">
    <select data-bm-state aria-label="${esc(tr('Show'))}">${BM_STATES.map(([k, n]) => `<option value="${k}" ${k === BM.state ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select>
    <span class="seg bmseg" role="group" aria-label="${esc(tr('View'))}"><button type="button" data-bm="cards" class="${view === 'cards' ? 'on' : ''}" aria-pressed="${view === 'cards'}" title="${esc(tr('Cards'))}" aria-label="${esc(tr('Cards'))}">${ic('grid', 's')}</button><button type="button" data-bm="list" class="${view === 'list' ? 'on' : ''}" aria-pressed="${view === 'list'}" title="${esc(tr('List'))}" aria-label="${esc(tr('List'))}">${ic('list', 's')}</button></span></div>`;
  const tags = BM.tags.length ? `<div class="bmtags" role="group" aria-label="${esc(tr('Tags'))}">${BM.tags.slice(0, 40).map(t => `<button type="button" class="bmtag ${t.tag === BM.tag ? 'on' : ''}" data-bm-tag="${esc(t.tag)}" aria-pressed="${t.tag === BM.tag}">#${esc(t.tag)} <span class="muted">${t.n}</span></button>`).join('')}</div>` : '';
  const head = `${rd_crumb('bookmarks')}<div class="bmhead">${add}${menu}</div>${bar}${tags}`;
  if (!BM.done) return `<div class="bmview">${head}<p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (!BM.items.length) {
    const filtered = BM.q || BM.tag || BM.state;
    return `<div class="bmview">${head}<div class="empty nempty">${ic('bookmark')}<span>${filtered ? tr('No bookmarks match.') : tr('No bookmarks yet. Paste a link above or share one from an app.')}</span></div></div>`;
  }
  const list = BM.items.map(view === 'cards' ? bm_card : bm_row).join('');
  return `<div class="bmview">${head}<ul class="${view === 'cards' ? 'bmgrid' : 'bmlist'}">${list}</ul>${BM.more ? `<button type="button" class="btn bmmore" data-bm="more">${tr('Show more')}</button>` : ''}</div>`;
}
const bm_tagsHtml = x => x.tags.length ? `<span class="bmtl">${x.tags.slice(0, 6).map(t => `<span class="bmt">#${esc(t)}</span>`).join('')}</span>` : '';
const bm_pend = x => x.preview === 'pending' || x.preview === 'image' ? `<span class="muted bmpend">${tr('Loading preview…')}</span>` : '';
function bm_acts(x) {
  if (!x.can_edit) return '';
  return `<span class="bmacts"><button type="button" class="iconbtn" data-bm="read" data-id="${x.id}" title="${esc(x.state === 'unread' ? tr('Mark read') : tr('Mark unread'))}" aria-label="${esc(x.state === 'unread' ? tr('Mark read') : tr('Mark unread'))}">${ic(x.state === 'unread' ? 'check' : 'eye', 's')}</button><button type="button" class="iconbtn" data-bm="arch" data-id="${x.id}" title="${esc(x.state === 'archived' ? tr('Restore from archive') : tr('Archive'))}" aria-label="${esc(x.state === 'archived' ? tr('Restore from archive') : tr('Archive'))}">${ic(x.state === 'archived' ? 'undo' : 'archive', 's')}</button></span>`;
}
function bm_card(x) {
  const u = bm_href(x.url);
  return `<li class="bmcard st-${x.state}" data-id="${x.id}"><button type="button" class="bmpic" data-bm="open" data-id="${x.id}" aria-label="${esc(tr('Details: {0}', x.title))}">${x.image ? `<img src="${esc(x.image)}" alt="" loading="lazy" decoding="async">` : `<span class="bmnopic" aria-hidden="true">${ic('bookmark')}</span>`}</button>
    <div class="bmbody"><a class="bmtitle" href="${esc(u)}" target="_blank" rel="noopener noreferrer" data-bm-link="${x.id}">${esc(x.title)}</a>
    <span class="muted bmsite">${esc(x.site)}${x.state === 'archived' ? ' · ' + esc(tr('Archived')) : ''}</span>${bm_pend(x)}
    ${x.description ? `<p class="bmdesc">${esc(x.description)}</p>` : ''}${x.note ? `<p class="bmnote">${ic('note', 's')} ${esc(x.note)}</p>` : ''}
    <div class="bmfoot">${bm_tagsHtml(x)}<span class="spacer"></span>${bm_acts(x)}<button data-rowmenu="bmcard" type="button" class="iconbtn" data-bm="open" data-id="${x.id}" title="${esc(tr('Details'))}" aria-label="${esc(tr('Details: {0}', x.title))}">${ic('dots', 's')}</button></div></div></li>`;
}
function bm_row(x) {
  const u = bm_href(x.url);
  return `<li class="bmrow st-${x.state}" data-id="${x.id}">${x.image ? `<img class="bmthumb" src="${esc(x.image)}" alt="" loading="lazy" decoding="async">` : `<span class="bmthumb bmnopic" aria-hidden="true">${ic('bookmark', 's')}</span>`}
    <div class="bmbody"><a class="bmtitle" href="${esc(u)}" target="_blank" rel="noopener noreferrer" data-bm-link="${x.id}">${esc(x.title)}</a>
    <span class="muted bmsite">${esc(x.site)}${x.note ? ' · ' + esc(x.note.slice(0, 80)) : ''}</span>${bm_pend(x)}${bm_tagsHtml(x)}</div>
    ${bm_acts(x)}<button data-rowmenu="bmrow" type="button" class="iconbtn" data-bm="open" data-id="${x.id}" title="${esc(tr('Details'))}" aria-label="${esc(tr('Details: {0}', x.title))}">${ic('dots', 's')}</button></li>`;
}

// ---- actions (each one undo step)
const bm_item = id => BM.items.find(x => x.id === id);
// 2.490.0 C (#4025): extra.space = the space picked when sharing (else the shown one); where = its name for the message
// 2.559.0 (#4660): the link shows at once as a card still on its way (negative id, the link as its title, "Loading preview…",
// no actions) in the list it belongs to (the shown space, no search / tag / read-only filter); the answer puts the server's
// bookmark in its place, a refusal takes it out (api() said why); the preview follows with the reload in the background
const bm_host = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
const bm_tmpPut = (tmp, sp) => () => {
  if (bm_item(tmp.id) || BM.sp !== sp || BM.q || BM.tag || !['', 'unread', 'all'].includes(BM.state)) return null;
  BM.items.unshift(tmp); BM.count++;
  return () => { if (!bm_item(tmp.id)) return; BM.items = BM.items.filter(y => y.id !== tmp.id); BM.count = Math.max(0, BM.count - 1); };
};
async function bm_add(url, extra = {}, where = '') {
  const sp = extra.space || bm_addSp();
  const tmp = {id: -Date.now(), url, title: extra.title || url, site: bm_host(url), description: '', note: '', tags: [], state: 'unread', preview: 'pending', image: '', can_edit: false, space: sp};
  try {
    const j = await optWrite(bm_tmpPut(tmp, sp), () => api('POST', '/api/bookmarks', {url, space: bm_addSp(), ...extra}), bm_draw, {mod: true});
    const b = j.bookmark;
    const i = BM.items.findIndex(y => y.id === tmp.id);
    if (i >= 0) { if (j.existed || bm_item(b.id)) { BM.items.splice(i, 1); BM.count = Math.max(0, BM.count - 1); } else BM.items[i] = b; }
    if (j.existed) toast(tr('Already saved: {0}', b.title), () => bm_detail(b.id), 6000, tr('Open'));
    else offerUndo(where ? tr('Saved in “{0}”: {1}', where, b.title) : tr('Saved: {0}', b.title), histAdd({label: tr('Save bookmark {0}', qn(b.title)),
      undo: async () => { await api('DELETE', `/api/bookmarks/${b.id}`); await bm_reload(); },
      redo: async () => { await api('POST', `/api/bookmarks/${b.id}/restore`, {}); await bm_reload(); }}));
    bm_draw();
    BM.polls = 0; bm_reload();  // in the background: the preview, the count
    return b;
  } catch { return null; }  // api() showed the reason (optWrite took the card out)
}
// 2.559.0 (#4660): a change (read / unread, archive, the details) shows at once on the card, the request runs behind it; a
// refusal puts the old values back (api() said why). The list comes again in the background only where the server decides
// what it shows: the state (the filter / the default list hide archived ones), tags (their counts), a new link (its preview).
// The changes go out one after the other (read and back quickly reach the server in this order). hl: the undo step's name.
let bm_q = Promise.resolve();
async function bm_patch(id, ch, label, hl = label, x0 = null) {
  const x = bm_item(id) || x0 || await api('GET', `/api/bookmarks/${id}`);
  const old = {}; for (const k of Object.keys(ch)) old[k] = x[k];
  const go = () => api('PATCH', `/api/bookmarks/${id}`, ch);
  const nx = await optWrite(optSet(() => bm_item(id), ch), () => (bm_q = bm_q.catch(() => {}).then(go)), bm_draw, {mod: true});
  // 2.570.0 (#4770): undo / redo send only the changed keys against the version the step before left (core.js undoStep; the
  // preview fetch no longer moves it): changed in another session since -> "Changed elsewhere, not undone", their change stays
  let ver = nx?.updated_at || '';
  const st = (v, from) => undoStep(`/api/bookmarks/${id}`, v, ver, {now: from, label: hl, then: j => { ver = j?.updated_at || ver; }}).finally(bm_reload);
  offerUndo(label, histAdd({label: hl, srv: true, undo: () => st(old, ch), redo: () => st(ch, old)}));  // 2.809.0 (#5476): srv = the server lists the step (life/bmundo.py)
  if ('url' in ch) BM.polls = 0;
  if ('state' in ch || 'tags' in ch || 'url' in ch) bm_reload();
  return nx;
}
// 2.559.0 (#4660): deleting takes the card out at once; a refusal brings it back at its place; the tag counts follow in the
// background
const bm_delPut = id => () => {
  const i = BM.items.findIndex(y => y.id === id); if (i < 0) return null;
  const x = BM.items[i]; BM.items = BM.items.filter(y => y.id !== id); BM.count = Math.max(0, BM.count - 1);
  return () => { if (bm_item(id)) return; BM.items.splice(Math.min(i, BM.items.length), 0, x); BM.count++; };
};
async function bm_del(id, x0 = null) {
  const x = bm_item(id) || x0 || await api('GET', `/api/bookmarks/${id}`);
  await optWrite(bm_delPut(id), () => api('DELETE', `/api/bookmarks/${id}`), bm_draw, {mod: true});
  offerUndo(tr('Deleted: {0}', x.title), histAdd({label: tr('Delete bookmark {0}', qn(x.title)), srv: true,  // 2.809.0 (#5476)
    undo: async () => { await api('POST', `/api/bookmarks/${id}/restore`, {}); await bm_reload(); },
    redo: async () => { await api('DELETE', `/api/bookmarks/${id}`); await bm_reload(); }}));
  bm_reload();
}
async function bm_move(x) {
  const from = bm_spOrg(x.space);
  const req = (to, extra) => rawFetch('POST', '/api/bookmarks/move-space', {ids: [x.id], to: smv_ws(to), ...extra});
  const r = await smv_open({what: qn(x.title), from, check: to => req(to, {dry: 1}),
    run: async to => { try { return await req(to, {}); } catch (e) { toast(e.message); throw e; } }});
  if (!r || !r.ok) return false;
  await bm_reload();
  const e = histAdd({label: tr('Moved {0}', qn(x.title)),
    undo: async () => { await req(from, {}); await bm_reload(); return {skipped: []}; },
    redo: async () => { await req(bm_spOrg(r.space), {}); await bm_reload(); return {skipped: []}; }});
  histToast(tr('Moved to {0}', wsName(r.space)), e);
  return true;
}

// ---- the details (edit, the reading text, move, delete)
async function bm_detail(id) {
  let x; try { x = await api('GET', `/api/bookmarks/${id}`); } catch { return; }
  const ro = !x.can_edit, u = bm_href(x.url);
  const text = x.text ? `<details class="bmtext"><summary>${ic('book', 's')} ${tr('Reading text')}</summary><div class="bmtextb">${x.text.split(/\n{2,}/).slice(0, 2000).map(p => `<p>${esc(p)}</p>`).join('')}</div></details>` : '';
  const md = modal(`<div class="lhdr"><h3 id="bmd-t">${ic('bookmark', 's')} ${tr('Bookmark')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    ${x.image ? `<img class="bmdpic" src="${esc(x.image)}" alt="">` : ''/* sprung-ok: fixed 12rem box, bookmarks.css .bmdpic (#5227) */}
    <div class="row"><label for="bmd-title">${tr('Title')}</label><input id="bmd-title" maxlength="300" value="${esc(x.title)}" ${ro ? 'readonly' : ''}></div>
    <div class="row"><label for="bmd-url">${tr('Link')}</label><input id="bmd-url" type="url" inputmode="url" maxlength="2000" value="${esc(x.url)}" ${ro ? 'readonly' : ''}></div>
    <div class="row"><label for="bmd-desc">${tr('Description')}</label><textarea id="bmd-desc" rows="2" maxlength="1000" ${ro ? 'readonly' : ''}>${esc(x.description)}</textarea></div>
    <div class="row"><label for="bmd-tags">${tr('Tags')}</label><input id="bmd-tags" maxlength="900" autocomplete="off" value="${esc(x.tags.join(', '))}" placeholder="${esc(tr('e.g. recipes, work'))}" ${ro ? 'readonly' : ''}></div>
    <div class="row"><label for="bmd-note">${tr('Note')}</label><textarea id="bmd-note" rows="3" maxlength="5000" ${ro ? 'readonly' : ''}>${esc(x.note)}</textarea></div>
    <div class="row"><label for="bmd-state">${tr('State')}</label><select id="bmd-state" ${ro ? 'disabled' : ''}>${BM_STATES.slice(1, 4).map(([k, n]) => `<option value="${k}" ${k === x.state ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select></div>
    <p class="muted bmdmeta">${esc([wsName(x.space), x.src === 'karakeep' ? tr('from Karakeep') : '', fmtWhen(x.created_at)].filter(Boolean).join(' · '))}${x.preview_error ? ` · ${ic('alert', 's')} ${esc(tr('No preview: {0}', x.preview_error))}` : ''}${bm_pend(x) ? ' · ' + bm_pend(x) : ''}${ro ? ` · ${esc(tr('Only who saved it or an admin of the organisation can change it'))}` : ''}</p>
    ${text}
    <div class="aerr" role="alert"></div>
    <div class="foot bmdfoot">${u ? `<a class="btn" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${ic('link', 's')}<span>${tr('Open')}</span></a>` : ''}
      ${ro ? '' : `<button class="btn" data-m="refresh">${ic('sync', 's')}<span>${tr('Reload preview')}</span></button>`}
      ${!ro && smv_can(bm_spOrg(x.space)) ? `<button class="btn" data-m="move">${ic('brief', 's')}<span>${tr('Move to another workspace…')}</span></button>` : ''}
      ${ro ? '' : `<button class="btn danger" data-m="del">${ic('trash', 's')}<span>${tr('Delete')}</span></button>`}
      <span class="spacer"></span>${ro ? '' : `<button class="btn pri" data-m="save">${tr('Save')}</button>`}</div>`);
  md.classList.add('bmdlg');
  md.setAttribute('role', 'dialog'); md.setAttribute('aria-modal', 'true'); md.setAttribute('aria-labelledby', 'bmd-t');
  // 2.122.4 C (#2223): the soft keyboard must not hide the focused field / Save (iOS)
  md.addEventListener('focusin', e => { if (e.target.matches('input,textarea,select')) setTimeout(() => e.target.scrollIntoView?.({block: 'center'}), 300); });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-m]'); if (!b) return;
    const k = b.dataset.m;
    if (k === 'close') { md.remove(); return; }
    b.disabled = true;
    try {
      if (k === 'save') {
        const v = s => $(s, md).value;
        const nw = {title: v('#bmd-title').trim(), url: v('#bmd-url').trim(), description: v('#bmd-desc').trim(), note: v('#bmd-note').trim(),
          tags: v('#bmd-tags').split(/[,\s]+/).map(t => t.replace(/^#/, '')).filter(Boolean), state: v('#bmd-state')};
        const ch = {};
        for (const [f, val] of Object.entries(nw)) if (JSON.stringify(val) !== JSON.stringify(f === 'tags' ? x.tags : x[f])) ch[f] = val;
        // 2.559.0 (#4660): the dialog closes at once, the card shows the new values; a refusal puts them back (api() says why)
        md.remove();
        if (Object.keys(ch).length) bm_patch(id, ch, tr('Saved: {0}', nw.title || x.title), tr('Edit bookmark {0}', qn(x.title)), x).catch(() => {});
        return;
      }
      if (k === 'refresh') { await api('POST', `/api/bookmarks/${id}/refresh`, {}); toast(tr('The preview is being loaded again')); BM.polls = 0; md.remove(); await bm_reload(); return; }
      if (k === 'move') { md.remove(); await bm_move(x); return; }
      if (k === 'del') { md.remove(); await bm_del(id, x); return; }
    } catch { /* api() showed it */ }
    b.disabled = false;
  });
  setTimeout(() => $(ro ? '[data-m="close"]' : '#bmd-title', md)?.focus(), 30);
}

// ---- the bookmarklet: 2.365.2 B (#2789): in Settings > Integrations next to sharing from the phone (integrations.js bmls_html)
function bm_bookmarkletHelp() { settingsModal('bookmarklet'); }

// ---- from the share sheet / the bookmarklet (main.js): save, then open the bookmark for tags and a note
// 2.490.0 C (#4025): into the picked space (Private unless an organisation is picked; the server checks the organisation)
async function bm_shareSave(url, title, space = 'private') {
  if (!feat('reading')) { toast(tr('Bookmarks are part of the module “Read later” (Settings > Modules)')); return; }
  space = space || 'private';
  go(rd_home('bookmarks', space));  // under "All workspaces" the view shows where it went (2.540.0 #4588: its address)
  const t = (title || '').trim();
  const b = await bm_add(url, {space, ...(t && t !== url ? {title: t.slice(0, 300)} : {})}, wsOn() ? wsName(space) : '');
  if (b) bm_detail(b.id);
}

// the bookmark button of the browser: the page it names is shown first and saved only with "Save" (Enter) -- a link to
// /share?bm=1 from another site never saves anything by itself
function bm_confirmSave(url, title) {
  if (!feat('reading')) { toast(tr('Bookmarks are part of the module “Read later” (Settings > Modules)')); return; }
  const u = bm_href(url); if (!u) return;
  const md = modal(`<form class="bmconf" novalidate><h3 id="bmc-t">${ic('bookmark', 's')} ${tr('Save as bookmark')}</h3>
    <p class="bmctitle"><b>${esc(title || u)}</b></p><p class="muted bmcurl">${esc(u)}</p>${rd_tgtSel('bookmark', 'bmc-sp')}
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="submit" class="btn pri" data-m="save">${tr('Save')}</button></div></form>`);
  md.classList.add('bmdlg', 'bmconfdlg');
  md.setAttribute('role', 'dialog'); md.setAttribute('aria-modal', 'true'); md.setAttribute('aria-labelledby', 'bmc-t');
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) md.remove(); });
  $('form', md).addEventListener('submit', e => { e.preventDefault(); const sp = $('#bmc-sp', md)?.value || 'private'; md.remove(); bm_shareSave(u, title, sp); });  // 2.490.0 C (#4025): the picked space
  setTimeout(() => $('[data-m="save"]', md)?.focus(), 30);
}

// ---- events
document.addEventListener('submit', async e => {
  const f = e.target.closest?.('[data-bm-form]'); if (!f) return;
  e.preventDefault();
  const inp = $('#bm-url', f), v = inp.value.trim(); if (!v || BM.busy) return;
  inp.value = '';  // 2.559.0 (#4660): the field empties at once, a refusal gives the link back
  if (!await bm_add(v)) { const i = $('#bm-url'); if (i) { if (!i.value) i.value = v; i.focus(); } }
});
let bm_qT = 0;
document.addEventListener('input', e => {
  if (!e.target.matches?.('[data-bm-q]')) return;
  clearTimeout(bm_qT);
  bm_qT = setTimeout(() => { BM.q = e.target.value.trim(); BM.items = []; bm_reload(); }, 250);
});
document.addEventListener('change', e => {
  if (e.target.matches?.('[data-bm-state]')) { BM.state = e.target.value; bm_reload(); }
});
document.addEventListener('click', async e => {
  const l = e.target.closest?.('[data-bm-link]');
  if (l) { const x = bm_item(+l.dataset.bmLink); if (x && x.can_edit && x.state === 'unread') api('PATCH', `/api/bookmarks/${x.id}`, {state: 'read'}).then(() => { x.state = 'read'; bm_draw(); }).catch(() => {}); return; }  // the link opens as usual
  const t = e.target.closest?.('[data-bm-tag]');
  if (t) { BM.tag = BM.tag === t.dataset.bmTag ? '' : t.dataset.bmTag; bm_reload(); return; }
  const a = e.target.closest?.('[data-bm]'); if (!a || a.disabled) return;
  e.preventDefault();
  const k = a.dataset.bm, id = +a.dataset.id || 0, x = bm_item(id);
  a.closest('details')?.removeAttribute('open');
  if (k === 'cards' || k === 'list') { LS.set('bmView', k); bm_draw(); return; }
  if (k === 'bmlet') { bm_bookmarkletHelp(); return; }
  if (k === 'kk') { settingsModal('karakeep'); return; }  // 2.365.2 B (#2789)
  if (k === 'open') { if (id > 0) bm_detail(id); return; }  // 2.559.0 (#4660): a card still on its way has no details yet
  a.disabled = true;
  try {
    if (k === 'more') await bm_load(true);
    else if (k === 'read' && x) await bm_patch(id, {state: x.state === 'unread' ? 'read' : 'unread'}, x.state === 'unread' ? tr('Marked read: {0}', x.title) : tr('Marked unread: {0}', x.title));
    else if (k === 'arch' && x) await bm_patch(id, {state: x.state === 'archived' ? 'read' : 'archived'}, x.state === 'archived' ? tr('Restored from the archive: {0}', x.title) : tr('Archived: {0}', x.title));
  } catch { /* api() showed it */ }
  a.disabled = false;
});
// 2.695.0 (#4619): a long press (phone) / right click (computer) on a row opens what its "…" opens (multisel.js lm_btnMenu)
if (typeof lm_btnMenu === 'function') lm_btnMenu('#view .bmcard, #view .bmrow:not(.rlrow)', '.iconbtn[data-bm="open"]');  // the details of a bookmark (card and row)
