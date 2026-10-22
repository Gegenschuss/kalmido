// @ts-check
/* Kalmido web client: the view "Read later" (area Reading, part of the module "reading", loaded on demand with bookmarks.js:
   lazyload.js LD_MODS, styles in static/css/bookmarks.css): the links saved to read later in the shown space (Private or
   an organisation), save a link, open it, tick it off (one undo step), the ticked ones; saving from the share sheet.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.172.0 B (#2679): an entry is a task (title + link) of the space's read-later project (life/reading.py): private = the
// person's "Read later" projects, an organisation's = its own project open to every member. The view asks the server for
// ONE space (rd_space: the shown workspace; under "All workspaces" Private or the one picked here), never a mixed view.
// Everything comes as plain text (always esc()), links only http(s).
const RDL = {items: [], more: false, count: 0, doneN: 0, list: null, space: '', sp: '', done: false, loading: false, at: 0, seq: 0,
  busy: false, ticked: false};
const rdl_sp = () => rd_space(RDL.space);
const rdl_href = u => /^https?:\/\//i.test(u || '') ? u : '';

// ---- loading
async function rdl_load(more) {
  const seq = ++RDL.seq; RDL.loading = true;
  const sp = rdl_sp();
  try {
    const q = new URLSearchParams({space: sp});
    if (RDL.ticked) q.set('done', '1');
    if (more && sp === RDL.sp) q.set('offset', String(RDL.items.length)); else more = false;
    const j = await api('GET', '/api/reading?' + q);
    if (seq !== RDL.seq) return;
    RDL.items = more ? RDL.items.concat(j.items) : j.items; RDL.more = j.more; RDL.count = j.count; RDL.doneN = j.done_count; RDL.list = j.list_id; RDL.sp = sp;
  } catch (e) { if (seq === RDL.seq && e.status === 404) RDL.space = ''; }
  if (seq !== RDL.seq) return;
  RDL.loading = false; RDL.done = true; RDL.at = Date.now();
  rdl_draw();
}
function rdl_draw() {
  if (S.route.mod !== 'reading') return;
  const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('reading', viewReading())));
}
const rdl_reload = () => rdl_load(false);
const rdl_item = id => RDL.items.find(x => x.id === id);

// ---- the view
function viewReading() {
  if (!RDL.loading && (!RDL.done || Date.now() - RDL.at > 60000 || RDL.sp !== rdl_sp())) setTimeout(rdl_reload, 0);
  const spSel = rd_pick(rdl_sp(), 'data-rl-space');
  const add = `<form class="bmadd" data-rl-form><label class="sr" for="rl-url">${tr('Link')}</label><input id="rl-url" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('Paste a link to read later'))}" maxlength="2000"><button type="submit" class="btn pri" ${RDL.busy ? 'disabled' : ''}>${ic('plus', 's')}<span>${tr('Save')}</span></button></form>`;
  const seg = `<div class="seg bmseg rlseg" role="group" aria-label="${esc(tr('Show'))}"><button type="button" data-rl="open-list" class="${RDL.ticked ? '' : 'on'}" aria-pressed="${!RDL.ticked}">${tr('To read')}${RDL.count ? ` <span class="muted">${RDL.count}</span>` : ''}</button><button type="button" data-rl="done-list" class="${RDL.ticked ? 'on' : ''}" aria-pressed="${RDL.ticked}">${tr('Read|done')}${RDL.doneN ? ` <span class="muted">${RDL.doneN}</span>` : ''}</button></div>`;
  const proj = RDL.list ? `<a class="btn sm" href="#l/${RDL.list}">${ic('list', 's')}<span>${tr('Show as project')}</span></a>` : '';
  const head = `<div class="bmhead">${add}</div><div class="bmbar">${seg}${spSel}<span class="spacer"></span>${proj}</div>`;
  if (!RDL.done) return `<div class="bmview rlview">${head}<p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (!RDL.items.length) return `<div class="bmview rlview">${head}<div class="empty nempty">${ic('book')}<span>${RDL.ticked ? tr('Nothing ticked off yet.') : tr('Nothing to read later. Save a link above, from a feed or with the share button of your phone.')}</span></div></div>`;
  const row = x => {
    const u = rdl_href(x.url);
    const t = u ? `<a class="bmtitle" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>` : `<span class="bmtitle">${esc(x.title)}</span>`;
    const tick = x.can_edit ? `<button type="button" class="iconbtn" data-rl="tick" data-id="${x.id}" aria-pressed="${x.done}" title="${esc(x.done ? tr('Unread') : tr('Read|done'))}" aria-label="${esc((x.done ? tr('Unread') : tr('Read|done')) + ': ' + x.title)}">${ic(x.done ? 'undo' : 'check', 's')}</button>` : '';
    return `<li class="bmrow rlrow ${x.done ? 'st-read' : ''}" data-id="${x.id}"><span class="bmthumb bmnopic" aria-hidden="true">${ic(u ? 'link' : 'book', 's')}</span>
      <div class="bmbody">${t}<span class="muted bmsite">${esc([x.site, fmtWhen(x.done ? x.completed_at : x.created_at)].filter(Boolean).join(' · '))}</span>${x.summary ? `<p class="bmdesc">${esc(x.summary)}</p>` : ''}</div>
      <span class="bmacts">${u ? `<a class="iconbtn" href="${esc(u)}" target="_blank" rel="noopener noreferrer" title="${esc(tr('Open the link'))}" aria-label="${esc(tr('Open {0}', x.title))}">${ic('link', 's')}</a>` : ''}${tick}<a class="iconbtn" href="#t/${x.id}" title="${esc(tr('Details'))}" aria-label="${esc(tr('Details: {0}', x.title))}">${ic('dots', 's')}</a></span></li>`;
  };
  return `<div class="bmview rlview">${head}<ul class="bmlist rllist">${RDL.items.map(row).join('')}</ul>${RDL.more ? `<button type="button" class="btn bmmore" data-rl="more">${tr('Show more')}</button>` : ''}</div>`;
}

// ---- actions (each one undo step)
async function rdl_save(url, title) {
  const space = rdl_sp();
  const j = await api('POST', '/api/reading', {url, space, ...(title ? {title: title.slice(0, 300)} : {})});
  if (!j.created) { toast(tr('Already in your reading list')); return j; }
  let tid = j.task_id;
  offerUndo(tr('Saved to “Read later”'), histAdd({label: tr('Read later: {0}', title || url),
    undo: async () => { await api('DELETE', `/api/tasks/${tid}`); if (S.route.mod === 'reading') await rdl_reload(); },
    redo: async () => { tid = (await api('POST', '/api/reading', {url, space, ...(title ? {title: title.slice(0, 300)} : {})})).task_id; if (S.route.mod === 'reading') await rdl_reload(); }}));
  return j;
}
async function rdl_add(url) {
  RDL.busy = true; rdl_draw();
  try { await rdl_save(url, ''); RDL.busy = false; await rdl_reload(); return true; }
  catch { RDL.busy = false; rdl_draw(); return false; }  // api() showed the reason
}
async function rdl_tick(id) {
  const x = rdl_item(id); if (!x) return;
  const done = !x.done, path = id => `/api/tasks/${id}/${done ? 'complete' : 'reopen'}`, back = id => `/api/tasks/${id}/${done ? 'reopen' : 'complete'}`;
  await api('POST', path(id));
  RDL.items = RDL.items.filter(y => y.id !== id);
  if (done) { RDL.count = Math.max(0, RDL.count - 1); RDL.doneN++; } else { RDL.doneN = Math.max(0, RDL.doneN - 1); RDL.count++; }
  rdl_draw();
  offerUndo(done ? tr('Read: {0}', x.title) : tr('Unread: {0}', x.title), histAdd({label: done ? tr('Read: {0}', x.title) : tr('Unread: {0}', x.title),
    undo: async () => { await api('POST', back(id)); await rdl_reload(); },
    redo: async () => { await api('POST', path(id)); await rdl_reload(); }}));
}
// the share sheet of the phone: a shared link goes to read later in the shown space
async function rdl_shareSave(url, title) {
  if (!feat('reading')) { toast(tr('Read later is turned off in your settings')); return; }
  const u = rdl_href(url); if (!u) return;
  const t = (title || '').trim();
  try { await rdl_save(u, t && t !== u ? t : ''); } catch { return; }  // api() showed the reason
  RDL.done = false;
  go('reading');
}

document.addEventListener('submit', async e => {
  const f = /** @type {HTMLElement|null} */ (/** @type {HTMLElement} */ (e.target).closest?.('[data-rl-form]')); if (!f) return;
  e.preventDefault();
  const inp = /** @type {HTMLInputElement} */ ($('#rl-url', /** @type {any} */ (f))), v = inp.value.trim(); if (!v || RDL.busy) return;
  if (await rdl_add(v)) { const i = /** @type {HTMLInputElement|null} */ ($('#rl-url')); if (i) i.value = ''; } else $('#rl-url')?.focus();
});
document.addEventListener('change', e => {
  const el = /** @type {HTMLSelectElement} */ (e.target);
  if (el.matches?.('[data-rl-space]')) { RDL.space = el.value; RDL.items = []; rdl_reload(); }
});
document.addEventListener('click', async e => {
  const a = /** @type {HTMLButtonElement|null} */ (/** @type {HTMLElement} */ (e.target).closest?.('[data-rl]')); if (!a || a.disabled) return;
  e.preventDefault();
  const k = a.dataset.rl, id = +(a.dataset.id || 0);
  if (k === 'open-list' || k === 'done-list') { RDL.ticked = k === 'done-list'; RDL.items = []; RDL.done = false; rdl_draw(); rdl_reload(); return; }
  a.disabled = true;
  try {
    if (k === 'more') await rdl_load(true);
    else if (k === 'tick') await rdl_tick(id);
  } catch { /* api() showed it */ }
  a.disabled = false;
});
