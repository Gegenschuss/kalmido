/* Kalmido web client: bookmarks (part of the module "reading", area Reading since 2.172.0, loaded on demand: lazyload.js LD_MODS, styles in
   static/css/bookmarks.css): the view "Bookmarks" (save a link, cards or a list, search, tags, read / archived, a note,
   the reading text, move to another workspace), saving from the share sheet / the bookmarklet.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.97.0 A (#1950): the server fetches the preview (title, description, picture, the plain reading text) in the background
// (life/bookmarks.py) -- while one is pending the view looks again a few times. Everything comes as plain text (always esc()),
// links only http(s); the picture is the app's own copy (/api/bookmarks/<id>/image). A bookmark lives in a space like a
// table: private, or an organisation's (every member reads it, its owner / the organisation's admins change it).
const BM = {items: [], more: false, tags: [], count: 0, q: '', tag: '', state: '', space: null, done: false, loading: false, seq: 0,
  busy: false, at: 0, polls: 0, pollT: 0};
const bm_href = u => /^https?:\/\//i.test(u || '') ? u : '';
const bm_view = () => LS.get('bmView', 'cards') === 'list' ? 'list' : 'cards';
const bm_sp = () => rd_space(BM.space);  // 2.172.0 B (#2679): the shown workspace only (under "All workspaces": Private or the picked one), no mixed view
const bm_addSp = () => { const s = bm_sp(); return s === 'all' ? 'private' : s; };
const bm_spOrg = sp => sp && sp !== 'private' ? +sp.slice(4) : null;
const BM_STATES = [['', N_('Unread and read')], ['unread', N_('Unread')], ['read', N_('Read|bookmark')], ['archived', N_('Archived')], ['all', N_('All')]];

// ---- loading
async function bm_load(more) {
  const seq = ++BM.seq; BM.loading = true;
  try {
    const sp = bm_sp(), q = new URLSearchParams({space: sp});
    if (BM.q) q.set('q', BM.q);
    if (BM.tag) q.set('tag', BM.tag);
    if (BM.state) q.set('state', BM.state);
    if (more) q.set('offset', BM.items.length);
    const j = await api('GET', '/api/bookmarks?' + q);
    if (seq !== BM.seq) return;
    BM.items = more ? BM.items.concat(j.items) : j.items; BM.more = j.more; BM.tags = j.tags; BM.count = j.count; BM.sp = sp;
  } catch (e) { if (seq === BM.seq && e.status === 404) BM.space = null; }
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
  if (!BM.loading && (!BM.done || Date.now() - BM.at > 60000 || BM.sp !== bm_sp())) setTimeout(bm_reload, 0);  // 2.172.0 B (#2679): + another workspace shown
  const spSel = rd_pick(bm_sp(), 'data-bm-space');  // 2.172.0 B (#2679)
  const add = `<form class="bmadd" data-bm-form><label class="sr" for="bm-url">${tr('Link')}</label><input id="bm-url" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('Paste a link'))}" maxlength="2000"><button type="submit" class="btn pri" ${BM.busy ? 'disabled' : ''}>${ic('plus', 's')}<span>${tr('Save')}</span></button></form>`;
  const menu = `<details class="bgmenu bmmenu"><summary class="iconbtn" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</summary><div class="bgmenul" role="menu">
    <button type="button" role="menuitem" data-bm="bmlet">${ic('bookmark', 's')}<span>${tr('Bookmark button for the browser')}</span></button>
    <button type="button" role="menuitem" data-bm="kk">${ic('link', 's')}<span>${tr('Karakeep…')}</span></button></div></details>`;
  const view = bm_view();
  const bar = `<div class="bmbar"><input type="search" class="bmq" data-bm-q value="${esc(BM.q)}" placeholder="${esc(tr('Search bookmarks'))}" aria-label="${esc(tr('Search bookmarks'))}">
    <select data-bm-state aria-label="${esc(tr('Show'))}">${BM_STATES.map(([k, n]) => `<option value="${k}" ${k === BM.state ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select>${spSel}
    <span class="seg bmseg" role="group" aria-label="${esc(tr('View'))}"><button type="button" data-bm="cards" class="${view === 'cards' ? 'on' : ''}" aria-pressed="${view === 'cards'}" title="${esc(tr('Cards'))}" aria-label="${esc(tr('Cards'))}">${ic('grid', 's')}</button><button type="button" data-bm="list" class="${view === 'list' ? 'on' : ''}" aria-pressed="${view === 'list'}" title="${esc(tr('List'))}" aria-label="${esc(tr('List'))}">${ic('list', 's')}</button></span></div>`;
  const tags = BM.tags.length ? `<div class="bmtags" role="group" aria-label="${esc(tr('Tags'))}">${BM.tags.slice(0, 40).map(t => `<button type="button" class="bmtag ${t.tag === BM.tag ? 'on' : ''}" data-bm-tag="${esc(t.tag)}" aria-pressed="${t.tag === BM.tag}">#${esc(t.tag)} <span class="muted">${t.n}</span></button>`).join('')}</div>` : '';
  const head = `<div class="bmhead">${add}${menu}</div>${bar}${tags}`;
  if (!BM.done) return `<div class="bmview">${head}<p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (!BM.items.length) {
    const filtered = BM.q || BM.tag || BM.state;
    return `<div class="bmview">${head}<div class="empty nempty">${ic('bookmark')}<span>${filtered ? tr('No bookmarks match.') : tr('No bookmarks yet. Paste a link above, share one from another app or use the bookmark button in your browser.')}</span></div></div>`;
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
    <div class="bmfoot">${bm_tagsHtml(x)}<span class="spacer"></span>${bm_acts(x)}<button type="button" class="iconbtn" data-bm="open" data-id="${x.id}" title="${esc(tr('Details'))}" aria-label="${esc(tr('Details: {0}', x.title))}">${ic('dots', 's')}</button></div></div></li>`;
}
function bm_row(x) {
  const u = bm_href(x.url);
  return `<li class="bmrow st-${x.state}" data-id="${x.id}">${x.image ? `<img class="bmthumb" src="${esc(x.image)}" alt="" loading="lazy" decoding="async">` : `<span class="bmthumb bmnopic" aria-hidden="true">${ic('bookmark', 's')}</span>`}
    <div class="bmbody"><a class="bmtitle" href="${esc(u)}" target="_blank" rel="noopener noreferrer" data-bm-link="${x.id}">${esc(x.title)}</a>
    <span class="muted bmsite">${esc(x.site)}${x.note ? ' · ' + esc(x.note.slice(0, 80)) : ''}</span>${bm_pend(x)}${bm_tagsHtml(x)}</div>
    ${bm_acts(x)}<button type="button" class="iconbtn" data-bm="open" data-id="${x.id}" title="${esc(tr('Details'))}" aria-label="${esc(tr('Details: {0}', x.title))}">${ic('dots', 's')}</button></li>`;
}

// ---- actions (each one undo step)
const bm_item = id => BM.items.find(x => x.id === id);
async function bm_add(url, extra = {}) {
  BM.busy = true; bm_draw();
  try {
    const j = await api('POST', '/api/bookmarks', {url, space: bm_addSp(), ...extra});
    const b = j.bookmark;
    BM.busy = false;
    if (j.existed) toast(tr('Already saved: {0}', b.title), () => bm_detail(b.id), 6000, tr('Open'));
    else offerUndo(tr('Saved: {0}', b.title), histAdd({label: tr('Save bookmark {0}', qn(b.title)),
      undo: async () => { await api('DELETE', `/api/bookmarks/${b.id}`); await bm_reload(); },
      redo: async () => { await api('POST', `/api/bookmarks/${b.id}/restore`, {}); await bm_reload(); }}));
    BM.polls = 0; await bm_reload();
    return b;
  } catch { BM.busy = false; bm_draw(); return null; }  // api() showed the reason
}
async function bm_patch(id, ch, label) {
  const x = bm_item(id) || await api('GET', `/api/bookmarks/${id}`);
  const old = {}; for (const k of Object.keys(ch)) old[k] = x[k];
  const nx = await api('PATCH', `/api/bookmarks/${id}`, ch);
  offerUndo(label, histAdd({label,
    undo: async () => { await api('PATCH', `/api/bookmarks/${id}`, old); await bm_reload(); },
    redo: async () => { await api('PATCH', `/api/bookmarks/${id}`, ch); await bm_reload(); }}));
  await bm_reload();
  return nx;
}
async function bm_del(id) {
  const x = bm_item(id) || await api('GET', `/api/bookmarks/${id}`);
  await api('DELETE', `/api/bookmarks/${id}`);
  offerUndo(tr('Deleted: {0}', x.title), histAdd({label: tr('Delete bookmark {0}', qn(x.title)),
    undo: async () => { await api('POST', `/api/bookmarks/${id}/restore`, {}); await bm_reload(); },
    redo: async () => { await api('DELETE', `/api/bookmarks/${id}`); await bm_reload(); }}));
  await bm_reload();
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
    ${x.image ? `<img class="bmdpic" src="${esc(x.image)}" alt="">` : ''}
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
        if (Object.keys(ch).length) {
          try { await rawFetch('PATCH', `/api/bookmarks/${id}`, ch); } catch (er) { $('.aerr', md).textContent = er.message || ''; b.disabled = false; return; }
          const old = {}; for (const f of Object.keys(ch)) old[f] = x[f];
          offerUndo(tr('Saved: {0}', nw.title || x.title), histAdd({label: tr('Edit bookmark {0}', qn(x.title)),
            undo: async () => { await api('PATCH', `/api/bookmarks/${id}`, old); await bm_reload(); },
            redo: async () => { await api('PATCH', `/api/bookmarks/${id}`, ch); await bm_reload(); }}));
          if (ch.url) BM.polls = 0;
          await bm_reload();
        }
        md.remove(); return;
      }
      if (k === 'refresh') { await api('POST', `/api/bookmarks/${id}/refresh`, {}); toast(tr('The preview is being loaded again')); BM.polls = 0; md.remove(); await bm_reload(); return; }
      if (k === 'move') { md.remove(); await bm_move(x); return; }
      if (k === 'del') { md.remove(); await bm_del(id); return; }
    } catch { /* api() showed it */ }
    b.disabled = false;
  });
  setTimeout(() => $(ro ? '[data-m="close"]' : '#bmd-title', md)?.focus(), 30);
}

// ---- the bookmarklet (a link that opens /share?bm=1 with the page in a small window; the normal sign-in, no token)
const bm_bookmarklet = () => `javascript:(()=>{window.open(${JSON.stringify(location.origin + '/share')}+'?bm=1&title='+encodeURIComponent(document.title)+'&url='+encodeURIComponent(location.href),'kalmido_bm','popup,width=560,height=680')})()`;
function bm_bookmarkletHelp() {
  const md = modal(`<div class="lhdr"><h3>${ic('bookmark', 's')} ${tr('Bookmark button for the browser')}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <div class="row caprow"><a class="btn pri capbm" href="${esc(bm_bookmarklet())}" data-m="hint" draggable="true">${ic('bookmark', 's')} ${tr('Save to Kalmido')}</a></div>
    <div class="shint keep">${tr('Drag the button to your bookmarks bar. On any page, click it: a small window shows the page, Save keeps it as a bookmark and opens it for tags and a note. It runs no code of ours on that page and uses your normal sign-in.')}</div>
    <div class="shint keep">${tr('On the phone: share a link from any app to Kalmido and choose “Save as bookmark”.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Close')}</button></div>`);
  md.classList.add('capmodal');
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'hint') { e.preventDefault(); toast(tr('Drag the button to your bookmarks bar')); return; }
    if (b.dataset.m === 'close') md.remove();
  });
}

// ---- from the share sheet / the bookmarklet (main.js): save, then open the bookmark for tags and a note
async function bm_shareSave(url, title) {
  if (!feat('reading')) { toast(tr('Bookmarks are part of the module “Read later” (Settings > Modules)')); return; }
  go('bookmarks');
  const t = (title || '').trim();
  const b = await bm_add(url, t && t !== url ? {title: t.slice(0, 300)} : {});
  if (b) bm_detail(b.id);
}

// the bookmark button of the browser: the page it names is shown first and saved only with "Save" (Enter) -- a link to
// /share?bm=1 from another site never saves anything by itself
function bm_confirmSave(url, title) {
  if (!feat('reading')) { toast(tr('Bookmarks are part of the module “Read later” (Settings > Modules)')); return; }
  const u = bm_href(url); if (!u) return;
  const md = modal(`<form class="bmconf" novalidate><h3 id="bmc-t">${ic('bookmark', 's')} ${tr('Save as bookmark')}</h3>
    <p class="bmctitle"><b>${esc(title || u)}</b></p><p class="muted bmcurl">${esc(u)}</p>
    <div class="foot"><span class="spacer"></span><button type="button" class="btn" data-m="close">${tr('Cancel')}</button><button type="submit" class="btn pri" data-m="save">${tr('Save')}</button></div></form>`);
  md.classList.add('bmdlg', 'bmconfdlg');
  md.setAttribute('role', 'dialog'); md.setAttribute('aria-modal', 'true'); md.setAttribute('aria-labelledby', 'bmc-t');
  md.addEventListener('click', e => { if (e.target.closest('[data-m="close"]')) md.remove(); });
  $('form', md).addEventListener('submit', e => { e.preventDefault(); md.remove(); bm_shareSave(u, title); });
  setTimeout(() => $('[data-m="save"]', md)?.focus(), 30);
}

// ---- events
document.addEventListener('submit', async e => {
  const f = e.target.closest?.('[data-bm-form]'); if (!f) return;
  e.preventDefault();
  const inp = $('#bm-url', f), v = inp.value.trim(); if (!v || BM.busy) return;
  if (await bm_add(v)) { const i = $('#bm-url'); if (i) i.value = ''; } else $('#bm-url')?.focus();
});
let bm_qT = 0;
document.addEventListener('input', e => {
  if (!e.target.matches?.('[data-bm-q]')) return;
  clearTimeout(bm_qT);
  bm_qT = setTimeout(() => { BM.q = e.target.value.trim(); BM.items = []; bm_reload(); }, 250);
});
document.addEventListener('change', e => {
  if (e.target.matches?.('[data-bm-state]')) { BM.state = e.target.value; bm_reload(); }
  else if (e.target.matches?.('[data-bm-space]')) { BM.space = e.target.value; BM.tag = ''; bm_reload(); }
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
  if (k === 'kk') { if (typeof kkModal === 'function') kkModal(); else { await loadModule('life'); kkModal(); } return; }
  if (k === 'open') { bm_detail(id); return; }
  a.disabled = true;
  try {
    if (k === 'more') await bm_load(true);
    else if (k === 'read' && x) await bm_patch(id, {state: x.state === 'unread' ? 'read' : 'unread'}, x.state === 'unread' ? tr('Marked read: {0}', x.title) : tr('Marked unread: {0}', x.title));
    else if (k === 'arch' && x) await bm_patch(id, {state: x.state === 'archived' ? 'read' : 'archived'}, x.state === 'archived' ? tr('Restored from the archive: {0}', x.title) : tr('Archived: {0}', x.title));
  } catch { /* api() showed it */ }
  a.disabled = false;
});
