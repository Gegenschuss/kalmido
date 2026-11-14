// @ts-check
/* Kalmido web client: the view "Read later" (area Reading, part of the module "reading", loaded on demand with bookmarks.js:
   lazyload.js LD_MODS, styles in static/css/bookmarks.css): the links saved to read later in the shown space (Private or
   an organisation), save a link, open it, tick it off (one undo step), the ticked ones; saving from the share sheet.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.172.0 B (#2679): an entry is a task (title + link) of the space's read-later project (life/reading.py): private = the
// person's "Read later" projects, an organisation's = its own project open to every member. The view asks the server for
// ONE space (rd_space: the shown workspace; under "All workspaces" the one opened from the overview, 2.540.0 #4588),
// never a mixed view.
// Everything comes as plain text (always esc()), links only http(s).
const RDL = {items: [], more: false, count: 0, doneN: 0, list: null, sp: '', done: false, loading: false, at: 0, seq: 0,
  busy: false, ticked: false, pend: /** @type {Promise<any>|null} */ (null)};  // pend: 2.559.0 (#4660) the last tick still on its way
const rdl_sp = () => rd_space();
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
    for (const p of OPT) p.put();  // 2.559.0 (#4660): own changes still on the way stay on top of the fresh list
  } catch (e) { if (seq === RDL.seq && e.status === 404 && rd_open()) go('reading'); }  // 2.540.0 (#4588): a space not open to me: the overview
  if (seq !== RDL.seq) return;
  RDL.loading = false; RDL.done = true; RDL.at = Date.now();
  rdl_draw();
}
function rdl_draw() {
  if (S.route.mod !== 'reading') return;
  const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('reading', viewReading())));
}
const rdl_reload = () => rdl_load(false);
// 2.979.0 (#5667): an undo / redo the server did (undo.js histRedraw): the shown list comes again, a list not shown is old (the next view fetches)
histReloader('reading', () => { if (!RDL.done) return; if (S.route.mod === 'reading') return rdl_reload(); RDL.at = 0; });
const rdl_item = id => RDL.items.find(x => x.id === id);

// ---- the view
function viewReading() {
  if (S.route.zle) return `<div class="bmview rlview">${/*html-ok*/ spo_recentPage('reading', rd_rows())}</div>`;  // 2.880.0 (#5561): #reading/recent
  if (rd_ovr()) return `<div class="bmview rlview">${rd_recentHtml('reading')}</div>`;  // 2.540.0 (#4588): "All workspaces": the spaces first; 2.769.0 (#5352): "Recently edited"
  if (!RDL.loading && (!RDL.done || Date.now() - RDL.at > 60000 || RDL.sp !== rdl_sp())) setTimeout(rdl_reload, 0);
  const add = `<form class="bmadd" data-rl-form><label class="sr" for="rl-url">${tr('Link')}</label><input id="rl-url" type="url" inputmode="url" autocomplete="off" placeholder="${esc(tr('Paste a link to read later'))}" maxlength="2000"><button type="submit" class="btn pri" ${RDL.busy ? 'disabled' : ''}>${ic('plus', 's')}<span>${tr('Add')}</span></button></form>`;
  const seg = `<div class="seg bmseg rlseg" role="group" aria-label="${esc(tr('Show'))}"><button type="button" data-rl="open-list" class="${RDL.ticked ? '' : 'on'}" aria-pressed="${!RDL.ticked}">${tr('To read')}${RDL.count ? ` <span class="muted">${RDL.count}</span>` : ''}</button><button type="button" data-rl="done-list" class="${RDL.ticked ? 'on' : ''}" aria-pressed="${RDL.ticked}">${tr('Read|done')}${RDL.doneN ? ` <span class="muted">${RDL.doneN}</span>` : ''}</button></div>`;
  const head = `${rd_crumb('reading')}<div class="bmhead">${add}</div><div class="bmbar">${seg}<span class="spacer"></span></div>`;  // 2.609.0 (#4613): no "Show as project" any more (the list is only the area's store)
  if (!RDL.done) return `<div class="bmview rlview">${head}<p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (!RDL.items.length) return `<div class="bmview rlview">${head}<div class="empty nempty">${ic('book')}<span>${RDL.ticked ? tr('Nothing ticked off yet.') : tr('Nothing to read later. Save a link above, from a feed or with the share button of your phone.')}</span></div></div>`;
  const row = x => {
    const u = rdl_href(x.url);
    const t = u ? `<a class="bmtitle" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>` : `<span class="bmtitle">${esc(x.title)}</span>`;
    const tick = x.can_edit && x.id > 0 ? `<button type="button" class="iconbtn" data-rl="tick" data-id="${x.id}" aria-pressed="${x.done}" title="${esc(x.done ? tr('Unread') : tr('Read|done'))}" aria-label="${esc((x.done ? tr('Unread') : tr('Read|done')) + ': ' + x.title)}">${ic(x.done ? 'undo' : 'check', 's')}</button>` : '';
    return `<li class="bmrow rlrow ${x.done ? 'st-read' : ''}" data-id="${x.id}"><span class="bmthumb bmnopic" aria-hidden="true">${ic(u ? 'link' : 'book', 's')}</span>
      <div class="bmbody">${t}<span class="muted bmsite">${esc([x.site, fmtWhen(x.done ? x.completed_at : x.created_at)].filter(Boolean).join(' · '))}</span>${x.summary ? `<p class="bmdesc">${esc(x.summary)}</p>` : ''}</div>
      <span class="bmacts">${u ? `<a class="iconbtn" href="${esc(u)}" target="_blank" rel="noopener noreferrer" title="${esc(tr('Open the link'))}" aria-label="${esc(tr('Open {0}', x.title))}">${ic('link', 's')}</a>` : ''}${tick}${x.id > 0 ? `<a data-rowmenu="rlrow" class="iconbtn" href="#t/${x.id}" title="${esc(tr('Details'))}" aria-label="${esc(tr('Details: {0}', x.title))}">${ic('dots', 's')}</a>` : ''}</span></li>`;  // 2.559.0 (#4660): a row still on its way (negative id) has no actions yet
  };
  return `<div class="bmview rlview">${head}<ul class="bmlist rllist">${RDL.items.map(row).join('')}</ul>${RDL.more ? `<button type="button" class="btn bmmore" data-rl="more">${tr('Show more')}</button>` : ''}</div>`;
}

// ---- actions (each one undo step)
// share: from the share sheet -- the toast names the workspace it went to (2.172.1 A, #2690)
// 2.490.0 C (#4025): to = the space picked in the share question (else the shown one)
async function rdl_save(url, title, share = false, to = '') {
  const space = to || rdl_sp();
  const j = await api('POST', '/api/reading', {url, space, ...(title ? {title: title.slice(0, 300)} : {})});
  const where = share ? wsName(j.space || space) : '';
  if (!j.created) { toast(where ? tr('Already in “Read later” in “{0}”', where) : tr('Already in your reading list')); return j; }
  let tid = j.task_id;
  offerUndo(where ? tr('Saved to “Read later” in “{0}”', where) : tr('Saved to “Read later”'), histAdd({label: tr('Read later: {0}', title || url),
    undo: async () => { await api('DELETE', `/api/tasks/${tid}`); if (S.route.mod === 'reading') await rdl_reload(); },
    redo: async () => { tid = (await api('POST', '/api/reading', {url, space, ...(title ? {title: title.slice(0, 300)} : {})})).task_id; if (S.route.mod === 'reading') await rdl_reload(); }}));
  return j;
}
// 2.559.0 (#4660): a pasted link shows at once as a row still on its way (negative id, the link as its title, no actions);
// the answer gives it the real id, a refusal takes it out again (api() said why); the server's title / site follow with a
// reload in the background (the row stays until the fresh list is there)
const rdl_host = u => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
const rdl_tmpPut = tmp => () => {
  if (RDL.ticked || rdl_item(tmp.id)) return null;  // the ticked ones shown: a new entry is not one of them
  RDL.items.unshift(tmp); RDL.count++;
  return () => { if (!rdl_item(tmp.id)) return; RDL.items = RDL.items.filter(y => y.id !== tmp.id); RDL.count = Math.max(0, RDL.count - 1); };
};
async function rdl_add(url) {
  const tmp = {id: -Date.now(), title: url, url, site: rdl_host(url), created_at: new Date().toISOString(), done: false, can_edit: false, summary: ''};
  let j; try { j = await optWrite(rdl_tmpPut(tmp), () => rdl_save(url, ''), rdl_draw, {mod: true}); } catch { return false; }  // api() showed the reason
  const x = rdl_item(tmp.id);
  if (x && (!j?.created || rdl_item(j.task_id))) { RDL.items = RDL.items.filter(y => y.id !== tmp.id); if (!j?.created) RDL.count = Math.max(0, RDL.count - 1); }
  else if (x) x.id = j.task_id;
  rdl_draw();
  if (S.route.mod === 'reading') rdl_reload();  // in the background: title, site and the count are the server's
  return true;
}
// 2.559.0 (#4660): ticking off (and back) takes the row out at once, the request runs behind it; a refusal brings it back
// at its place (api() said why). Idempotent: optWrite puts it again on a state that arrives meanwhile.
const rdl_tickPut = (id, done) => () => {
  const i = RDL.items.findIndex(y => y.id === id); if (i < 0) return null;
  const x = RDL.items[i]; RDL.items = RDL.items.filter(y => y.id !== id);
  if (done) { RDL.count = Math.max(0, RDL.count - 1); RDL.doneN++; } else { RDL.doneN = Math.max(0, RDL.doneN - 1); RDL.count++; }
  return () => {
    if (rdl_item(id)) return;
    RDL.items.splice(Math.min(i, RDL.items.length), 0, x);
    if (done) { RDL.count++; RDL.doneN = Math.max(0, RDL.doneN - 1); } else { RDL.doneN++; RDL.count = Math.max(0, RDL.count - 1); }
  };
};
async function rdl_tick(id) {
  const x = rdl_item(id); if (!x || id < 0) return;
  const done = !x.done, path = id => `/api/tasks/${id}/${done ? 'complete' : 'reopen'}`, back = id => `/api/tasks/${id}/${done ? 'reopen' : 'complete'}`;
  const req = RDL.pend = optWrite(rdl_tickPut(id, done), () => api('POST', path(id)), rdl_draw, {mod: true});
  await req;
  // 2.809.0 (#5476): srv = the server lists the step itself (a task completed / reopened: tasks/tundo.py)
  offerUndo(done ? tr('Read: {0}', x.title) : tr('Unread: {0}', x.title), histAdd({label: done ? tr('Read: {0}', x.title) : tr('Unread: {0}', x.title), srv: true,
    undo: async () => { await api('POST', back(id)); await rdl_reload(); },
    redo: async () => { await api('POST', path(id)); await rdl_reload(); }}));
}
// the share sheet of the phone: a shared link goes to read later in the picked space (2.490.0 C, #4025: Private unless an
// organisation is picked; the server refuses an organisation the person may not add to)
async function rdl_shareSave(url, title, space = 'private') {
  if (!feat('reading')) { toast(tr('Read later is switched off in your settings')); return; }
  const u = rdl_href(url); if (!u) return;
  const t = (title || '').trim();
  let j; try { j = await rdl_save(u, t && t !== u ? t : '', true, space || 'private'); } catch { return; }  // api() showed the reason
  RDL.done = false;
  go(rd_home('reading', j?.space || space || 'private'));  // under "All workspaces" the view shows where it went (2.540.0 #4588: its address)
}

document.addEventListener('submit', async e => {
  const f = /** @type {HTMLElement|null} */ (/** @type {HTMLElement} */ (e.target).closest?.('[data-rl-form]')); if (!f) return;
  e.preventDefault();
  const inp = /** @type {HTMLInputElement} */ ($('#rl-url', /** @type {any} */ (f))), v = inp.value.trim(); if (!v || RDL.busy) return;
  inp.value = '';  // 2.559.0 (#4660): the field empties at once, a refusal gives the link back
  if (!await rdl_add(v)) { const i = /** @type {HTMLInputElement|null} */ ($('#rl-url')); if (i) { if (!i.value) i.value = v; i.focus(); } }
});
document.addEventListener('click', async e => {
  const a = /** @type {HTMLButtonElement|null} */ (/** @type {HTMLElement} */ (e.target).closest?.('[data-rl]')); if (!a || a.disabled) return;
  e.preventDefault();
  const k = a.dataset.rl, id = +(a.dataset.id || 0);
  // 2.559.0 (#4660): the other list loads once a tick still on its way is through (else it would miss that entry)
  if (k === 'open-list' || k === 'done-list') { RDL.ticked = k === 'done-list'; RDL.items = []; RDL.done = false; RDL.loading = true; rdl_draw(); Promise.resolve(RDL.pend).catch(() => {}).then(rdl_reload); return; }
  a.disabled = true;
  try {
    if (k === 'more') await rdl_load(true);
    else if (k === 'tick') await rdl_tick(id);
  } catch { /* api() showed it */ }
  a.disabled = false;
});
// 2.695.0 (#4619): a long press (phone) / right click (computer) on a row opens what its "…" opens (multisel.js lm_btnMenu)
// 2.1151.0 C (#3835): on a phone the symbols are hidden (bookmarks.css): the long press opens the menu of all of them (ms_btnMenu)
if (typeof lm_btnMenu === 'function') lm_btnMenu('#view .rlrow', 'a.iconbtn[href^="#t/"]', lm_keep, r => ms_btnMenu(r, '.bmacts .iconbtn', rdl_item(+r.dataset.id)?.title));  // the details of a read-later entry (its task)
