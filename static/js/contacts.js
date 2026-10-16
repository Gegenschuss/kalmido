/* Kalmido web client: Contacts (module "contacts"): the contacts view (search, groups, address books), the editor, the
   contact card, links between contacts and tasks, import / export.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.21.0 (#658): the contacts live in Kalmido's own address books (S.books from /api/state) and sync with the phone over
// CardDAV. The view loads its page of contacts (GET /api/contacts, never part of /api/state: contacts are personal data
// and can be many); a contact opens as a card (desktop: next to the list, phone: the whole view), "Edit" opens the editor.
const CT = {q: '', group: '', book: '', items: null, total: 0, groups: [], sel: null, card: null, loading: false, seq: 0, pick: null};  // 2.46.1 (#1554): pick = the selected ids (Set) in the selection mode
const ctOn = () => feat('contacts');
const CT_LINK = [['waiting', N_('Waiting on')], ['responsible', N_('Responsible')], ['about', N_('About')]];
const CT_TYPES = {emails: [['home', N_('Home')], ['work', N_('Work')], ['other', N_('Other')]],
  phones: [['cell', N_('Mobile')], ['home', N_('Home')], ['work', N_('Work')], ['other', N_('Other')]],
  addresses: [['home', N_('Home')], ['work', N_('Work')], ['other', N_('Other')]], urls: [['home', N_('Home')], ['work', N_('Work')], ['other', N_('Other')]]};
const ctTypeWord = (k, it) => { const t = (it.type || [])[0], o = (CT_TYPES[k] || []).find(x => x[0] === t); return it.label && !/^_\$!</.test(it.label) ? it.label : o ? tr(o[1]) : t ? t : ''; };
const ctBook = id => (S.books || []).find(b => b.id === id);
const ctWrite = b => !!b && (b.role === 'owner' || b.role === 'edit');
function ctAv(c, cls = 'avatar ctav') {
  return c.photo && typeof c.photo === 'string' && c.photo.startsWith('data:image/') ? `<span class="${cls} pic"><img src="${esc(c.photo)}" alt="" loading="lazy" decoding="async"></span>`
    : `<span class="${cls}">${esc(initials(c.fn || c.org || '?'))}</span>`;
}
function ctDate(v) {  // '1980-05-12' / '--05-12' -> "12 May 1980" / "12 May"
  if (!v) return '';
  if (v.startsWith('--')) { const d = new Date(2000, +v.slice(2, 4) - 1, +v.slice(5, 7)); try { return d.toLocaleDateString(LOCALE(), {day: 'numeric', month: 'long'}); } catch { return v.slice(2); } }  // no year: no weekday either
  return fmtDay('year', pd(v));
}
// 2.46.4 (#1732): an address book that is gone (deleted, left, or so on another device): its contacts, a filter on it, an open card
// and selected ids of it leave the view at once - before, ctLoad failed on the filter and kept the old items until a reload
let ct_seenBooks = null;
function ct_prune() {
  if (!Array.isArray(S.books)) return;
  const now = new Set(S.books.map(b => b.id)), was = ct_seenBooks; ct_seenBooks = now;
  if (CT.book && !now.has(+CT.book)) CT.book = '';
  const gone = was ? new Set([...was].filter(id => !now.has(id))) : new Set();
  if (!gone.size) return;
  if (CT.items) {
    const out = CT.items.filter(c => gone.has(c.book_id));
    if (CT.pick) for (const c of out) CT.pick.delete(c.id);
    CT.items = CT.items.filter(c => !gone.has(c.book_id)); CT.total = Math.max(0, CT.total - out.length);
  }
  if (CT.card && gone.has(CT.card.book_id)) {
    CT.sel = null; CT.card = null;
    if (S.route.mod === 'contacts' && S.route.contact) setTimeout(() => go('contacts'), 0);
  }
}
async function ctLoad() {
  const seq = ++CT.seq;
  ct_prune();
  CT.loading = true;
  const qs = new URLSearchParams({q: CT.q, limit: '500'});
  if (CT.group) qs.set('group', CT.group);
  if (CT.book) qs.set('book_id', CT.book);
  try {
    const j = await api('GET', '/api/contacts?' + qs);
    if (seq !== CT.seq) return;
    CT.items = j.items; CT.total = j.total; CT.groups = j.groups || [];
  } catch (e) {
    if (seq === CT.seq && e?.status === 404 && CT.book) { CT.book = ''; CT.loading = false; return ctLoad(); }  // 2.46.4 (#1732): the filtered book is gone
    if (seq === CT.seq) CT.items = CT.items || [];
  }
  CT.loading = false;
  if (S.route.mod === 'contacts') ctDraw();
}
async function ctRoute(id) {
  if (CT.items === null && !CT.loading) ctLoad();
  if (id) await ctOpen(id); else if (isMobile()) { CT.sel = null; CT.card = null; ctDraw(); }
}
async function ctOpen(id) {
  CT.sel = id;
  try { CT.card = await api('GET', `/api/contacts/${id}`); } catch { CT.card = null; CT.sel = null; toast(tr('This contact does not exist or you cannot see it.')); }
  if (S.route.mod === 'contacts') ctDraw();
}
function ctDraw() { if (S.route.mod === 'contacts') { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('contacts', viewContacts()))); } }
function viewContacts() {
  if (CT.items === null && !CT.loading) setTimeout(ctLoad, 0);
  ct_prune();  // 2.46.4 (#1732): also after a live update
  const books = (S.books || []).filter(b => wsObjIn(b));  // 2.30.0 (#1036): the address books of the shown workspace
  const items = CT.items === null ? null : CT.items.filter(c => !ctBook(c.book_id) || wsObjIn(ctBook(c.book_id)));
  const mob = isMobile(), showCard = CT.card && (!mob || CT.sel);
  const bar = `<div class="ctbar"><div class="ctsearch">${ic('search', 's')}<input id="ct-q" type="search" value="${esc(CT.q)}" placeholder="${esc(tr('Search contacts'))}" aria-label="${esc(tr('Search contacts'))}" autocomplete="off" enterkeyhint="search"></div>
    ${CT.groups.length ? `<select id="ct-group" aria-label="${esc(tr('Group'))}"><option value="">${tr('All groups')}</option>${CT.groups.map(g => `<option value="${esc(g)}" ${g === CT.group ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select>` : ''}
    ${books.length > 1 ? `<select id="ct-book" aria-label="${esc(tr('Address book'))}"><option value="">${tr('All address books')}</option>${books.map(b => `<option value="${b.id}" ${String(b.id) === String(CT.book) ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select>` : ''}
    <span class="spacer"></span>${books.some(ctWrite) ? `<button class="iconbtn ${CT.pick ? 'on' : ''}" data-ct="pick" aria-pressed="${!!CT.pick}" aria-label="${esc(tr(CT.pick ? 'End selection' : 'Select'))}" title="${esc(tr(CT.pick ? 'End selection' : 'Select'))}">${ic('select')}</button>` : ''}<button class="btn sm pri" data-ct="new">${ic('plus', 's')}<span class="cdl">${tr('New contact')}</span></button>
    <button class="iconbtn" data-ct="menu" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>`;
  const list = items === null ? `<div class="muted ctempty">${tr('Loading…')}</div>` : !items.length
    ? `<div class="empty">${ic('users')}${CT.q || CT.group ? tr('No contact matches.') : tr('No contacts yet. Add one, import a vCard file, or connect the phone.')}</div>`
    : `<ul class="ctlist" role="list" aria-label="${esc(tr('Contacts'))}">${items.map(c => `<li><button type="button" class="ctrow ${c.id === CT.sel ? 'on' : ''} ${bk_rowCls(c)}" data-ctopen="${c.id}" ${CT.pick ? `aria-pressed="${CT.pick.has(c.id)}"` : `aria-current="${c.id === CT.sel}"`}>${CT.pick ? bk_chk(c) : ''}${ctAv(c)}<span class="ctn"><b>${esc(c.fn || c.org || '?')}</b><small class="muted">${esc([c.org !== c.fn ? c.org : '', c.email || c.phone].filter(Boolean).join(' · '))}</small></span>${(books.length > 1 && ctBook(c.book_id)) ? `<i class="cevdot" style="--cc:${cssColor(ctBook(c.book_id).color) || 'var(--accent)'}" title="${esc(ctBook(c.book_id).name)}"></i>` : ''}</button></li>`).join('')}</ul>
      ${CT.total > CT.items.length ? `<div class="muted ctmore">${tr('{0} of {1} shown: search to narrow it down', items.length, CT.total)}</div>` : ''}`;
  return `<div class="ctview ${showCard ? 'withcard' : ''} ${CT.pick ? 'ctpicking' : ''}"><h2 class="sr">${tr('Contacts')}</h2>${CT.pick && !(mob && showCard) ? bk_barHtml() : ''}${mob && showCard ? '' : bar}<div class="ctcols">${mob && showCard ? '' : `<div class="ctlistw">${list}</div>`}${showCard ? ctCardHtml(CT.card) : mob ? '' : `<div class="ctcard ctnone muted">${ic('user')}${tr('Choose a contact')}</div>`}</div></div>`;
}
function ctCardHtml(c) {
  const b = ctBook(c.book_id), w = ctWrite(b);
  const it = (k, icon, href) => (c[k] || []).map(x => `<div class="ctf">${ic(icon, 's')}<span class="ctfl muted">${esc(ctTypeWord(k, x))}</span>${href(x)}</div>`).join('');
  const adr = (c.addresses || []).map(a => { const t = [a.street, [a.code, a.city].filter(Boolean).join(' '), a.region, a.country].filter(Boolean).join(', ');
    return `<div class="ctf">${ic('mappin', 's')}<span class="ctfl muted">${esc(ctTypeWord('addresses', a))}</span><span>${esc(t)}</span></div>`; }).join('');
  const kinds = Object.fromEntries(CT_LINK);
  return `<article class="ctcard" aria-labelledby="ct-h">
    <div class="cthead">${isMobile() ? `<button class="iconbtn" data-ct="back" aria-label="${esc(tr('Back'))}">${ic('back')}</button>` : ''}${ctAv(c, 'avatar ctav big')}<div class="cthn"><h3 id="ct-h">${esc(c.fn || c.org || '?')}</h3>${feat('clients') ? `<div class="mstags">${ms_tag('contact')}</div>` : ''}${[c.title, c.org !== c.fn ? c.org : '', c.dept].filter(Boolean).length ? `<div class="muted">${esc([c.title, c.org !== c.fn ? c.org : '', c.dept].filter(Boolean).join(' · '))}</div>` : ''}</div>
      <span class="ctacts">${w ? `<button class="btn sm" data-ct="edit">${ic('edit', 's')} ${tr('Edit')}</button>` : `<span class="rotag">${ic('eye', 's')}${tr('View only')}</span>`}<button class="iconbtn" data-ct="cmenu" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button></span></div>
    <div class="ctfields">
      ${it('phones', 'phone', x => `<a href="tel:${esc(x.value.replace(/[^\d+]/g, ''))}">${esc(x.value)}</a>`)}
      ${it('emails', 'at', x => `<a href="mailto:${esc(x.value)}">${esc(x.value)}</a>`)}
      ${adr}
      ${it('urls', 'link', x => /^https?:/i.test(x.value) ? `<a href="${esc(x.value)}" target="_blank" rel="noopener noreferrer">${esc(x.value)}</a>` : `<span>${esc(x.value)}</span>`)}
      ${c.bday ? `<div class="ctf">${ic('cake', 's')}<span class="ctfl muted">${tr('Birthday')}</span><span>${esc(ctDate(c.bday))}</span></div>` : ''}
      ${c.anniversary ? `<div class="ctf">${ic('gift', 's')}<span class="ctfl muted">${tr('Anniversary')}</span><span>${esc(ctDate(c.anniversary))}</span></div>` : ''}
      ${c.nickname ? `<div class="ctf">${ic('user', 's')}<span class="ctfl muted">${tr('Nickname')}</span><span>${esc(c.nickname)}</span></div>` : ''}
      ${(c.groups || []).length ? `<div class="ctf">${ic('tag', 's')}<span class="ctfl muted">${tr('Groups')}</span><span>${c.groups.map(g => `<button type="button" class="tagchip" data-ctgroup="${esc(g)}">${esc(g)}</button>`).join(' ')}</span></div>` : ''}
      ${b ? `<div class="ctf">${ic('folder', 's')}<span class="ctfl muted">${tr('Address book')}</span><span>${esc(b.name)}</span></div>` : ''}
    </div>
    ${c.note ? `<div class="ctnote md">${renderMd(c.note, false, {})}</div>` : ''}
    ${lifeCareHtml(c)}
    <div class="ctsec"><h4>${tr('Tasks')}</h4>${(c.tasks || []).length ? `<ul class="ctlinks">${c.tasks.map(t => `<li><button type="button" class="linkbtn ${t.status ? 'done' : ''}" data-cttask="${t.task_id}">${ic(t.status ? 'done' : 'list', 's')} ${esc(t.title)}</button><span class="muted"> · ${esc(tr(kinds[t.kind] || 'About'))}</span></li>`).join('')}</ul>` : `<p class="muted">${tr('No linked tasks yet: “Link a contact” in a task’s panel.')}</p>`}</div>
    ${(c.events || []).length ? `<div class="ctsec"><h4>${tr('Events')}</h4><ul class="ctlinks">${c.events.map(e => `<li><button type="button" class="linkbtn" data-evopen="${e.event_id}">${ic('cal', 's')} ${esc(e.title)}</button><span class="muted"> · ${esc(e.all_day ? fmtDayAbs(e.start.slice(0, 10)) : fmtDayAbs(e.start.slice(0, 10)) + ' ' + fmtTimeLoc(e.start.slice(11, 16)))}</span></li>`).join('')}</ul></div>` : ''}
  </article>`;
}
document.addEventListener('input', e => {
  if (e.target.id !== 'ct-q') return;
  CT.q = e.target.value;
  clearTimeout(CT.t); CT.t = setTimeout(ctLoad, 200);
});
document.addEventListener('change', e => {
  if (e.target.id === 'ct-group') { CT.group = e.target.value; ctLoad(); }
  if (e.target.id === 'ct-book') { CT.book = e.target.value; ctLoad(); }
});
document.addEventListener('click', async e => {
  const bb = e.target.closest('#ct-sbar [data-ctb]');
  if (bb) { bk_barAct(bb.dataset.ctb, bb); return; }
  const o = e.target.closest('[data-ctopen]');
  if (o && (CT.pick || (ms_modClick(e) && !isMobile() && bk_canPick()))) { e.preventDefault(); if (!ms_lpRecent(bk_lpS)) bk_click(+o.dataset.ctopen, e.shiftKey); return; }  // 2.46.1 (#1554): the selection mode; 2.47.3 (#1733): Shift- / Cmd-click
  if (o && ms_lpRecent(bk_lpS)) { e.preventDefault(); return; }  // the click that ends a long press
  if (o) { e.preventDefault(); if (isMobile()) go('contacts/' + o.dataset.ctopen); else ctOpen(+o.dataset.ctopen); return; }
  const tk = e.target.closest('[data-cttask]');
  if (tk) { e.preventDefault(); const id = +tk.dataset.cttask; if (taskById(id)) openDetail(id); else go('t/' + id); return; }
  const gp = e.target.closest('[data-ctgroup]');
  if (gp) { CT.group = gp.dataset.ctgroup; CT.sel = null; CT.card = null; if (isMobile()) go('contacts'); ctLoad(); return; }
  const b = e.target.closest('#view [data-ct]'); if (!b) return;
  const k = b.dataset.ct;
  if (k === 'pick') { CT.pick = CT.pick ? null : new Set(); ctDraw(); return; }
  if (k === 'new') ctEditor(null);
  else if (k === 'edit' && CT.card) ctEditor(CT.card);
  else if (k === 'back') { CT.sel = null; CT.card = null; go('contacts'); }
  else if (k === 'menu') {
    menu(b, [{label: tr('Address books…'), icon: 'folder', fn: ctBooksModal},
      {label: tr('Import a vCard file…'), icon: 'upload', fn: () => ctImport()},
      ...(S.books || []).map(x => ({label: tr('Export {0} (vCard)', x.name), icon: 'download', fn: () => { location.href = `/api/books/${x.id}/export.vcf`; }})),
      {label: tr('On the phone…'), icon: 'phone', fn: davGuide}]);
  } else if (k === 'cmenu' && CT.card) {
    const c = CT.card, w = ctWrite(ctBook(c.book_id));
    menu(b, [w && {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: async () => {
      if (!await askConfirm(tr('Delete the contact “{0}”?', c.fn), tr('It is also removed from the phones that sync this address book.'), {ok: tr('Delete'), danger: true})) return;
      try { await api('DELETE', `/api/contacts/${c.id}`); } catch { return; }
      CT.sel = null; CT.card = null; toast(tr('Contact deleted')); await load().catch(() => {}); if (isMobile()) go('contacts'); ctLoad(); }},
      feat('events') && {label: tr('Invite to a new event'), icon: 'cal', fn: () => evEditor({attendees: [{contact_id: c.id, name: c.fn, email: c.emails?.[0]?.value || '', partstat: 'needs-action'}]})}]);
  }
});

// ---- 2.46.1 (#1554): several contacts at once. The selection mode (the select button in the bar; on the phone a long
// press on a row) shows a tick per row; a tap adds / removes a contact. The floating bar (like the tasks' selection bar)
// shows the count, "All" (every contact matching the search, group and address book, also beyond the shown 500), Move
// (an address book one may change) and Delete (one question with the count). One request each (POST /api/contacts/bulk);
// contacts in read-only address books cannot be ticked. Contacts have no undo (the single delete has none either).
// 2.47.3 (#1733): the bar, the long press and Shift- / Cmd-click come from multisel.js (shared with the clients)
const bk_can = c => ctWrite(ctBook(c.book_id));
const bk_rowCls = c => !CT.pick ? '' : CT.pick.has(c.id) ? 'picked' : bk_can(c) ? '' : 'ctro';
const bk_chk = c => `<span class="ctchk ${CT.pick.has(c.id) ? 'on' : ''}" aria-hidden="true">${CT.pick.has(c.id) ? ic('check', 's') : ''}</span>`;
function bk_toggle(id) {
  const c = (CT.items || []).find(x => x.id === id); if (!c || !CT.pick) return;
  if (!bk_can(c)) { toast(tr('You can only read this address book')); return; }
  if (CT.pick.has(id)) CT.pick.delete(id); else CT.pick.add(id);
  CT.last = id;
  ctDraw();
}
const bk_canPick = () => (S.books || []).some(b => ctWrite(b) && wsObjIn(b));
function bk_click(id, shift) {  // 2.47.3 (#1733): Shift-click ticks the rows between the last ticked one and this one
  if (!CT.pick) { CT.pick = new Set(); CT.last = null; }
  if (!shift || CT.last == null) { bk_toggle(id); return; }
  const shown = bk_shown(CT.items || []);
  for (const x of ms_range(shown.map(c => c.id), CT.last, id)) CT.pick.add(x);
  CT.last = id; ctDraw();
}
function bk_start(id) { CT.pick = new Set(); bk_toggle(id); if (!CT.pick.size) ctDraw(); }
function bk_end() { CT.pick = null; ctDraw(); }
function bk_barHtml() {
  return ms_barHtml('ct-sbar', 'ctb', CT.pick.size, tr('Tap contacts'), [['all', 'all', bk_allOn() ? tr('Select none') : tr('All')], ['edit', 'edit', tr('Edit')], ['move', 'folder', tr('Move')], ['del', 'trash', tr('Delete'), 'danger']]);
}
// every contact of the current search / group / address book (the list shows 500, an import has more): fetched as pages
async function bk_matching() {
  if (CT.items && CT.total <= CT.items.length) return CT.items;
  const out = [];
  for (let off = 0; off < CT.total && off < 20000; off += 2000) {
    const qs = new URLSearchParams({q: CT.q, limit: '2000', offset: String(off)});
    if (CT.group) qs.set('group', CT.group);
    if (CT.book) qs.set('book_id', CT.book);
    const j = await api('GET', '/api/contacts?' + qs); out.push(...j.items);
    if (j.items.length < 2000) break;
  }
  return out;
}
const bk_shown = items => items.filter(c => bk_can(c) && (!ctBook(c.book_id) || wsObjIn(ctBook(c.book_id))));
const bk_allOn = () => !!CT.pick?.size && CT.items !== null && CT.total <= CT.items.length && bk_shown(CT.items).every(c => CT.pick.has(c.id)) && CT.pick.size >= bk_shown(CT.items).length;
async function bk_barAct(k, el) {
  if (!CT.pick) return;
  if (k === 'close') { bk_end(); return; }
  if (k === 'all') {
    if (bk_allOn()) { CT.pick.clear(); ctDraw(); return; }
    let all; try { all = bk_shown(await bk_matching()); } catch { return; }
    for (const c of all) CT.pick.add(c.id);
    ctDraw(); return;
  }
  const ids = [...CT.pick]; if (!ids.length) return;
  if (k === 'del') {
    if (!await askConfirm(trn('Delete {0} contact?', 'Delete {0} contacts?', ids.length), tr('They are also removed from the phones that sync these address books.'), {ok: tr('Delete'), danger: true})) return;
    try { await bk_send({action: 'delete'}, ids); } catch { return; }
    toast(trn('{0} contact deleted', '{0} contacts deleted', ids.length));
    if (CT.pick && CT.sel && ids.includes(CT.sel)) { CT.sel = null; CT.card = null; }
    bk_end(); await load().catch(() => {}); ctLoad();
  } else if (k === 'edit') bk_edit(ids);
  else if (k === 'move') {
    const books = (S.books || []).filter(b => ctWrite(b) && wsObjIn(b) && !b.imported);
    if (!books.length) { toast(tr('No address book you may change')); return; }
    menu(el, books.map(b => ({label: b.name, icon: 'folder', fn: () => bk_move(ids, b)})), null, null, tr('Move'));
  }
}
async function bk_send(body, ids) {  // one request per 5000 (the server's limit; an address book holds up to 20000)
  const out = {moved: 0, conflicts: []};
  for (let i = 0; i < ids.length; i += 5000) { const j = await api('POST', '/api/contacts/bulk', {...body, ids: ids.slice(i, i + 5000)}); out.moved += j.moved || 0; out.conflicts.push(...(j.conflicts || [])); }
  return out;
}
// 2.47.3 (#1731): properties of the selected contacts at once (groups added / removed, company, department, kind, a note
// appended); POST /api/contacts/bulk action set answers with the old values, the undo (toast, Ctrl+Z) sends them back
// (action restore) as ONE step. Contacts of imported address books stay as they are (counted)
const bk_csv = v => v.split(',').map(x => x.trim()).filter(Boolean);
function bk_edit(ids) {
  const dl = `<datalist id="ms-ct-groups">${CT.groups.map(g => `<option value="${esc(g)}">`).join('')}</datalist>`;
  const inp = (k, ph = '', more = '') => `<input id="ms-f-${k}" data-msf="${k}" maxlength="300" placeholder="${esc(ph)}" autocomplete="off" ${more}>`;
  ms_sheet(trn('Edit {0} contact', 'Edit {0} contacts', ids.length), tr('Only what you fill in or tick changes; everything else stays as it is.'), [
    {k: 'groups_add', label: tr('Add to groups'), input: inp('groups_add', tr('Group, another group'), 'list="ms-ct-groups"') + dl, fill: true},
    {k: 'groups_remove', label: tr('Remove from groups'), input: inp('groups_remove', tr('Group, another group'), 'list="ms-ct-groups"'), fill: true},
    {k: 'org', label: tr('Company'), input: inp('org', tr('empty = remove'))},
    {k: 'dept', label: tr('Department'), input: inp('dept', tr('empty = remove'))},
    {k: 'kind', label: tr('Kind'), input: `<select id="ms-f-kind" data-msf="kind"><option value="individual">${tr('Person')}</option><option value="org">${tr('Company')}</option></select>`},
    {k: 'note_append', label: tr('Append to the note'), input: `<textarea id="ms-f-note_append" data-msf="note_append" rows="3" maxlength="4000"></textarea>`, fill: true}],
  async v => {
    const body = {action: 'set'};
    if (v.groups_add) body.groups_add = bk_csv(v.groups_add);
    if (v.groups_remove) body.groups_remove = bk_csv(v.groups_remove);
    for (const k of ['org', 'dept', 'kind', 'note_append']) if (k in v) body[k] = v[k];
    let undo = await bk_set(body, ids);
    const n = undo.changed;
    bk_end(); await load().catch(() => {}); ctLoad(); if (CT.sel) ctOpen(CT.sel);
    const msg = [trn('{0} contact changed', '{0} contacts changed', n), undo.skipped ? trn('{0} in an imported address book stayed', '{0} in imported address books stayed', undo.skipped) : ''].filter(Boolean).join(' · ');
    const back = async () => { await bk_set({action: 'restore'}, null, undo.undo); ctLoad(); if (CT.sel) ctOpen(CT.sel); };
    const again = async () => { undo = await bk_set(body, ids); ctLoad(); if (CT.sel) ctOpen(CT.sel); };
    if (n) ms_hist(msg, tr('Contacts changed'), back, again); else toast(msg);
    return true;
  });
}
async function bk_set(body, ids, items) {  // 5000 per request; restore sends the old values (items) instead of ids
  const out = {changed: 0, skipped: 0, undo: []}, all = items || ids;
  for (let i = 0; i < all.length; i += 5000) {
    const part = all.slice(i, i + 5000);
    const j = await rawFetch('POST', '/api/contacts/bulk', items ? {...body, items: part} : {...body, ids: part});
    out.changed += j.changed || 0; out.skipped += j.skipped || 0; out.undo.push(...(j.undo || []));
  }
  return out;
}
async function bk_move(ids, b) {
  let j; try { j = await bk_send({action: 'move', book_id: b.id}, ids); } catch { return; }
  const conf = (j.conflicts || []).length;
  toast([trn('{0} contact moved to {1}', '{0} contacts moved to {1}', j.moved, b.name), conf ? trn('{0} was there already and stayed', '{0} were there already and stayed', conf) : ''].filter(Boolean).join(' · '));
  bk_end(); await load().catch(() => {}); ctLoad(); if (CT.sel) ctOpen(CT.sel);
}
document.addEventListener('keydown', e => {  // capture: before the global Esc (an open menu / dialog closes first)
  if (e.key === 'Escape' && CT.pick && S.route.mod === 'contacts' && !$('.modal, .lightbox') && $('#pop')?.classList.contains('hidden')) { e.preventDefault(); bk_end(); }
}, true);
// the phone: a long press on a row starts the selection with it (the click after it does nothing)
const bk_lpS = ms_longPress('#view .ctrow[data-ctopen]', () => !!CT.pick, r => bk_start(+r.dataset.ctopen));

// ---- the editor
async function ctEditor(c) {
  const books = (S.books || []).filter(b => ctWrite(b) && (wsObjIn(b) || (c && b.id === c.book_id)));  // 2.30.0 (#1036): of the shown workspace (+ the contact's own)
  if (!books.length) { try { const bk = await api('POST', '/api/books', {name: tr('Contacts'), org_id: wsDefaultOrg()}); await load(); books.push(bk); } catch { return; } }
  const st = c ? JSON.parse(JSON.stringify(c)) : {book_id: +(CT.book || LS.get('ctBook', 0)) || books[0].id, given: '', family: '', fn: '', org: '', title: '', dept: '', nickname: '',
    emails: [{value: '', type: ['home']}], phones: [{value: '', type: ['cell']}], addresses: [], urls: [], bday: '', anniversary: '', note: '', groups: [], photo: ''};
  if (!books.some(b => b.id === st.book_id)) st.book_id = books[0].id;
  const custom = st.fn && st.fn !== [st.prefix, st.given, st.middle, st.family, st.suffix].filter(Boolean).join(' ');
  const typeSel = (k, i, it) => `<select class="ctty" data-ctk="${k}" data-ci="${i}" aria-label="${esc(tr('Kind'))}">${CT_TYPES[k].map(([v, n]) => `<option value="${v}" ${(it.type || [])[0] === v ? 'selected' : ''}>${tr(n)}</option>`).join('')}${(it.type || [])[0] && !CT_TYPES[k].some(x => x[0] === it.type[0]) ? `<option value="${esc(it.type[0])}" selected>${esc(ctTypeWord(k, it))}</option>` : ''}</select>`;
  const multi = (k, label, ph, inputType) => `<fieldset class="ctmulti" data-ctm="${k}"><legend>${label}</legend>${(st[k] || []).map((it, i) => `<div class="ctmi">${typeSel(k, i, it)}<input data-ctk="${k}" data-ci="${i}" data-cf="value" value="${esc(it.value || '')}" type="${inputType}" ${inputType === 'tel' ? 'inputmode="tel"' : inputType === 'email' ? 'inputmode="email"' : ''} placeholder="${esc(ph)}" aria-label="${esc(label)}" autocomplete="off"><button type="button" class="iconbtn" data-ctrm="${k}" data-ci="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`).join('')}
    <button type="button" class="linkbtn" data-ctadd="${k}">${ic('plus', 's')} ${tr('Add')}</button></fieldset>`;
  const adrs = () => `<fieldset class="ctmulti" data-ctm="addresses"><legend>${tr('Addresses')}</legend>${(st.addresses || []).map((a, i) => `<div class="ctadr">${typeSel('addresses', i, a)}
      <input data-ctk="addresses" data-ci="${i}" data-cf="street" value="${esc(a.street || '')}" placeholder="${esc(tr('Street'))}" aria-label="${esc(tr('Street'))}" autocomplete="off">
      <input data-ctk="addresses" data-ci="${i}" data-cf="code" value="${esc(a.code || '')}" placeholder="${esc(tr('Postcode'))}" aria-label="${esc(tr('Postcode'))}" class="ctzip" autocomplete="off">
      <input data-ctk="addresses" data-ci="${i}" data-cf="city" value="${esc(a.city || '')}" placeholder="${esc(tr('City'))}" aria-label="${esc(tr('City'))}" autocomplete="off">
      <input data-ctk="addresses" data-ci="${i}" data-cf="country" value="${esc(a.country || '')}" placeholder="${esc(tr('Country'))}" aria-label="${esc(tr('Country'))}" autocomplete="off">
      <button type="button" class="iconbtn" data-ctrm="addresses" data-ci="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button></div>`).join('')}
    <button type="button" class="linkbtn" data-ctadd="addresses">${ic('plus', 's')} ${tr('Add')}</button></fieldset>`;
  const dateRow = (k, label) => { const v = st[k] || '', noy = v.startsWith('--'); const full = noy ? `2000-${v.slice(2, 4)}-${v.slice(5, 7)}` : v;
    return `<div class="row ctdate"><span class="rlab">${label}</span>${dateIn('ct-' + k, full, {label, empty: tr('none')})}<label class="chkl"><input type="checkbox" id="ct-${k}-noy" ${noy ? 'checked' : ''}> ${tr('without the year')}</label></div>`; };
  const md = modal(`<div class="lhdr"><h3>${c ? tr('Edit contact') : tr('New contact')}</h3><span class="spacer"></span><button class="iconbtn" data-ctm2="close" aria-label="${tr('Close')}">${ic('x')}</button></div>
    <div class="ctphoto"><span id="ct-ph">${ctAv(st, 'avatar ctav big')}</span><label class="btn sm">${ic('upload', 's')} ${tr('Photo')}<input type="file" id="ct-photo" accept="image/*" hidden></label>${st.photo ? `<button type="button" class="linkbtn" data-ctm2="nophoto">${tr('Remove')}</button>` : ''}</div>
    <div class="row"><label for="ct-given">${tr('First name')}</label><input id="ct-given" value="${esc(st.given || '')}" autocomplete="off" maxlength="300"></div>
    <div class="row"><label for="ct-family">${tr('Last name')}</label><input id="ct-family" value="${esc(st.family || '')}" autocomplete="off" maxlength="300"></div>
    <div class="row"><label for="ct-org">${tr('Company')}</label><input id="ct-org" value="${esc(st.org || '')}" autocomplete="off" maxlength="300"></div>
    <div class="row"><label for="ct-title">${tr('Job title')}</label><input id="ct-title" value="${esc(st.title || '')}" autocomplete="off" maxlength="300"></div>
    ${multi('phones', tr('Phone'), '+49 …', 'tel')}${multi('emails', tr('E-mail'), 'name@example.org', 'email')}${adrs()}
    ${dateRow('bday', tr('Birthday'))}${dateRow('anniversary', tr('Anniversary'))}
    <div class="row"><label for="ct-groups">${tr('Groups')}</label><input id="ct-groups" value="${esc((st.groups || []).join(', '))}" list="ct-gl" placeholder="${esc(tr('e.g. Family, Customers'))}" autocomplete="off"><datalist id="ct-gl">${CT.groups.map(g => `<option value="${esc(g)}"></option>`).join('')}</datalist></div>
    <div class="row ppcol"><label for="ct-note">${tr('Notes')}</label><textarea id="ct-note" rows="3" maxlength="20000">${esc(st.note || '')}</textarea></div>
    <details class="evmore" ${custom || st.nickname || st.dept || (st.urls || []).length ? 'open' : ''}><summary>${tr('More')}</summary>
      <div class="row"><label for="ct-fn">${tr('Display name')}</label><input id="ct-fn" value="${esc(custom ? st.fn : '')}" placeholder="${esc(tr('from the name parts'))}" autocomplete="off" maxlength="300"></div>
      <div class="row"><label for="ct-nick">${tr('Nickname')}</label><input id="ct-nick" value="${esc(st.nickname || '')}" autocomplete="off" maxlength="300"></div>
      <div class="row"><label for="ct-dept">${tr('Department')}</label><input id="ct-dept" value="${esc(st.dept || '')}" autocomplete="off" maxlength="300"></div>
      ${multi('urls', tr('Website'), 'https://…', 'url')}
      <div class="row"><label for="ct-bk">${tr('Address book')}</label><select id="ct-bk">${books.map(b => `<option value="${b.id}" ${b.id === st.book_id ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select></div></details>
    <div class="foot"><span class="spacer"></span><button class="btn" data-ctm2="close">${tr('Cancel')}</button><button class="btn pri" data-ctm2="save">${tr('Save')}</button></div>`);
  md.classList.add('ctmodal');
  const redraw = () => {  // the repeatable rows after adding / removing one
    const m = multi;
    for (const k of ['phones', 'emails', 'urls']) { const f = $(`[data-ctm="${k}"]`, md); if (f) f.outerHTML = m(k, f.querySelector('legend').textContent, f.querySelector('input')?.placeholder || (k === 'phones' ? '+49 …' : k === 'emails' ? 'name@example.org' : 'https://…'), k === 'phones' ? 'tel' : k === 'emails' ? 'email' : 'url'); }
    const a = $('[data-ctm="addresses"]', md); if (a) a.outerHTML = adrs();
  };
  md.addEventListener('input', e => {
    const x = e.target; if (!x.dataset.ctk) return;
    const it = st[x.dataset.ctk][+x.dataset.ci]; if (!it) return;
    if (x.classList.contains('ctty')) it.type = [x.value]; else it[x.dataset.cf] = x.value;
  });
  md.addEventListener('change', async e => {
    const x = e.target;
    if (x.classList.contains('ctty')) { const it = st[x.dataset.ctk][+x.dataset.ci]; if (it) { it.type = [x.value]; it.label = ''; } return; }
    if (x.id === 'ct-photo' && x.files[0]) {
      const url = await ctPhoto(x.files[0]); if (!url) { toast(tr('The photo could not be read')); return; }
      st.photo = url; $('#ct-ph', md).innerHTML = ctAv(st, 'avatar ctav big');
    }
  });
  md.addEventListener('click', async e => {
    const ad = e.target.closest('[data-ctadd]');
    if (ad) { const k = ad.dataset.ctadd; (st[k] ||= []).push(k === 'addresses' ? {type: ['home']} : {value: '', type: [CT_TYPES[k][0][0]]}); redraw(); $$(`[data-ctm="${k}"] input`, md).filter(i => !i.value).pop()?.focus(); return; }
    const rm = e.target.closest('[data-ctrm]');
    if (rm) { st[rm.dataset.ctrm].splice(+rm.dataset.ci, 1); redraw(); return; }
    const b = e.target.closest('[data-ctm2]'); if (!b) return;
    if (b.dataset.ctm2 === 'close') { md.remove(); return; }
    if (b.dataset.ctm2 === 'nophoto') { st.photo = ''; $('#ct-ph', md).innerHTML = ctAv(st, 'avatar ctav big'); b.remove(); return; }
    if (b.dataset.ctm2 !== 'save') return;
    const v = id => $('#' + id, md)?.value.trim() || '';
    const dt = k => { const d = $('#ct-' + k, md)?.value || ''; return !d ? '' : $(`#ct-${k}-noy`, md)?.checked ? `--${d.slice(5, 7)}-${d.slice(8, 10)}` : d; };
    const clean = (k, addr) => (st[k] || []).map(x => ({...x})).filter(x => addr ? ['street', 'city', 'code', 'country'].some(f => (x[f] || '').trim()) : (x.value || '').trim());
    const body = {given: v('ct-given'), family: v('ct-family'), org: v('ct-org'), title: v('ct-title'), fn: v('ct-fn'), nickname: v('ct-nick'), dept: v('ct-dept'),
      phones: clean('phones'), emails: clean('emails'), urls: clean('urls'), addresses: clean('addresses', true), bday: dt('bday'), anniversary: dt('anniversary'),
      note: $('#ct-note', md).value, groups: v('ct-groups').split(',').map(x => x.trim()).filter(Boolean), photo: st.photo || '', book_id: +v('ct-bk') || st.book_id};
    if (!body.given && !body.family && !body.org && !body.fn) { toast(tr('A name or a company, please')); $('#ct-given', md).focus(); return; }
    try {
      const r = c ? await api('PATCH', `/api/contacts/${c.id}`, {...body, expect: c.updated_at}) : await api('POST', '/api/contacts', body);
      LS.set('ctBook', body.book_id);
      md.remove(); CT.sel = r.id; CT.card = r;
      toast(c ? tr('Contact saved') : tr('Contact created'));
      await load().catch(() => {}); ctLoad();
      if (S.route.mod === 'contacts' && isMobile() && !c) go('contacts/' + r.id);
    } catch { /* api() showed it */ }
  });
  setTimeout(() => { if (!c && !isTouch()) $('#ct-given', md)?.focus(); }, 40);
}
function ctPhoto(file) {  // a square JPEG of at most 256 px (small enough for every phone's contact card)
  return new Promise(res => {
    const r = new FileReader();
    r.onload = () => {
      const img = new Image();
      img.onload = () => {
        const n = Math.min(256, img.width, img.height), cv = document.createElement('canvas'); cv.width = cv.height = n;
        const s = Math.min(img.width, img.height), x = (img.width - s) / 2, y = (img.height - s) / 2;
        cv.getContext('2d').drawImage(img, x, y, s, s, 0, 0, n, n);
        try { res(cv.toDataURL('image/jpeg', .85)); } catch { res(''); }
      };
      img.onerror = () => res('');
      img.src = r.result;
    };
    r.onerror = () => res('');
    r.readAsDataURL(file);
  });
}
function ctImport(bookId) {
  const books = (S.books || []).filter(b => ctWrite(b) && wsObjIn(b));
  const run = async bid => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.vcf,text/vcard,text/x-vcard';
    inp.onchange = () => { const f = inp.files[0]; if (f) ctImpRun(bid, f); };
    inp.click();
  };
  if (bookId) { run(bookId); return; }
  if (books.length === 1) { run(books[0].id); return; }
  if (!books.length) { api('POST', '/api/books', {name: tr('Contacts'), org_id: wsDefaultOrg()}).then(async b => { await load(); run(b.id); }).catch(() => {}); return; }
  menu($('#view [data-ct="menu"]') || $('#view'), books.map(b => ({label: tr('Into {0}', b.name), icon: 'folder', fn: () => run(b.id)})));
}
// 2.41.0 (#1437): the import shows "Import running ..." at once with its progress (upload, then the cards stored in the
// background) and always ends with a message that stays until it is closed (no 6-second toast): new / updated / not readable,
// or what went wrong. A large file is imported in the background (?background=1 -> import id, GET /api/books/imports/<id>).
function ctImpPanel() {
  let el = $('#ctimp');
  if (!el) {
    el = document.createElement('div'); el.id = 'ctimp'; el.className = 'ctimp'; el.setAttribute('role', 'status');
    el.innerHTML = '<div class="ctimp-t"></div><div class="pbar"><i></i></div><button class="iconbtn" data-ctimp="close" hidden></button>';
    document.body.appendChild(el);
    const x = el.querySelector('[data-ctimp="close"]'); x.innerHTML = ic('x'); x.setAttribute('aria-label', tr('Close')); x.title = tr('Close');
    x.onclick = () => el.remove();
  }
  const set = (text, frac, end) => {
    el.querySelector('.ctimp-t').textContent = text;
    const bar = el.querySelector('.pbar'); bar.hidden = frac == null; if (frac != null) bar.firstChild.style.width = Math.round(Math.min(1, frac) * 100) + '%';
    el.querySelector('[data-ctimp="close"]').hidden = !end; el.classList.toggle('done', !!end);
    if (end) announce(text);
  };
  return {el, set};
}
function ctImpRun(bid, f) {
  const p = ctImpPanel();
  const done = async j => {
    p.set(tr('Imported: {0} new, {1} updated', j.created, j.updated) + (j.errors ? ' · ' + trn('{0} not readable', '{0} not readable', j.errors) : ''), null, true);
    await load().catch(() => {}); ctLoad();
  };
  const fail = msg => p.set(tr('Import failed') + (msg ? ': ' + msg : ''), null, true);
  p.set(tr('Import running…'), 0);
  const x = new XMLHttpRequest();
  x.open('POST', `/api/books/${bid}/import?background=1`); x.setRequestHeader('X-Requested-With', 'kalmido'); x.withCredentials = true;
  x.upload.onprogress = e => { if (e.lengthComputable) p.set(tr('Import running…') + ' ' + tr('Uploading {0} %', Math.round(e.loaded / e.total * 100)), e.loaded / e.total * .3); };
  x.onerror = () => fail(tr('The connection was interrupted'));
  x.onload = async () => {
    let j = {}; try { j = JSON.parse(x.responseText); } catch {}
    // 2.41.0 (#1437): 413 from a proxy in front comes without JSON -> still say why
    if (x.status >= 400) { fail(j.error || (x.status === 413 ? tr('File too large') : '')); return; }
    if (!j.import_id) { await done(j); return; }  // small file: answered at once
    let misses = 0;
    for (;;) {
      await new Promise(r => setTimeout(r, 1000));
      let st;
      try { st = await rawFetch('GET', `/api/books/imports/${encodeURIComponent(j.import_id)}`); misses = 0; }
      catch { if (++misses >= 30) { fail(tr('The connection was interrupted')); return; } continue; }
      if (st.state === 'done') { await done(st); return; }
      if (st.state === 'failed') { fail(st.error); if (st.created || st.updated) load().catch(() => {}); return; }
      p.set(tr('Import running…') + ' ' + tr('{0} of {1} contacts', st.done, st.total), .3 + .7 * (st.total ? st.done / st.total : 0));
    }
  };
  x.send((() => { const fd = new FormData(); fd.append('file', f); return fd; })());
}
async function ctBooksModal() {
  let users = [];
  if (collab()) users = await evPeople();
  const names = new Map(users.map(u => [u.id, u.display_name]));
  const md = modal(`<div class="lhdr"><h3>${ic('folder', 's')} ${tr('Address books')}</h3><span class="spacer"></span><button class="iconbtn" data-cb="close" aria-label="${tr('Close')}">${ic('x')}</button></div><div id="cb-body"></div>
    <div class="foot"><button class="btn" data-cb="phone">${ic('phone', 's')} ${tr('On the phone…')}</button><span class="spacer"></span><button class="btn pri" data-cb="new">${ic('plus', 's')} ${tr('New address book')}</button></div>`);
  const draw = () => {
    const bs = S.books || [];
    $('#cb-body', md).innerHTML = bs.length ? `<ul class="evclist">${bs.map(b => `<li class="evcrow" style="--cc:${cssColor(b.color) || 'var(--accent)'}"><i class="cevdot"></i><span class="evcn">${esc(b.name)} <span class="muted">· ${esc(trn('{0} contact', '{0} contacts', b.count))}${wsOn() && b.role === 'owner' ? ' · ' + esc(wsLabel(b.org_id)) : ''}${b.role !== 'owner' ? ' · ' + esc(b.owner_name || '') + ' · ' + esc(b.role === 'edit' ? tr('can edit') : tr('can view')) : b.members?.length ? ' · ' + esc(trn('shared with {0} person', 'shared with {0} people', b.members.length)) : ''}${b.imported ? ' · ' + esc(tr('imported')) : ''}</span></span>
      <button class="iconbtn" data-cbmenu="${b.id}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', b.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('No address book yet. A new contact creates one.')}</p>`;
  };
  draw();
  const refresh = async () => { await load().catch(() => {}); draw(); ctLoad(); };
  md.addEventListener('click', async e => {
    const m = e.target.closest('[data-cbmenu]');
    if (m) {
      const b = ctBook(+m.dataset.cbmenu); if (!b) return;
      const own = b.role === 'owner';
      menu(m, [own && {label: tr('Rename…'), icon: 'edit', fn: async () => { const n = await askPrompt(tr('Rename the address book'), b.name, {input: {max: 100}}); if (n && n.trim()) { const nm = n.trim(); optWrite(optSet(() => ctBook(b.id), {name: nm}), () => api('PATCH', `/api/books/${b.id}`, {name: nm}), () => { draw(); ctDraw(); }).catch(() => {}); } }},  // 2.46.2 (#1659): at once
        own && wsOn() && {label: tr('Workspace…'), icon: 'brief', fn: () => wsMoveMenu(m, b.org_id, async org => { try { await api('PATCH', `/api/books/${b.id}`, {org_id: org}); } catch { return; } refresh(); })},
        own && collab() && {label: tr('Share…'), icon: 'users', fn: () => ctShareModal(b, users, names, refresh)},
        own && famOn() && !b.imported && {label: tr('Birthdays as tasks…'), icon: 'cake', fn: () => ctBdayModal(b, refresh)},
        ctWrite(b) && {label: tr('Import a vCard file…'), icon: 'upload', fn: () => ctImport(b.id)},
        {label: tr('Export (vCard)'), icon: 'download', fn: () => { location.href = `/api/books/${b.id}/export.vcf`; }},
        !own && {label: tr('Leave this address book'), icon: 'logout', fn: async () => { try { await api('DELETE', `/api/books/${b.id}/members/${S.me.id}`); } catch { return; } refresh(); }},
        own && {label: tr('Delete…'), icon: 'trash', cls: 'danger', fn: async () => { if (!await askConfirm(tr('Delete the address book “{0}” with all its contacts?', b.name), tr('This cannot be undone.'), {ok: tr('Delete'), danger: true})) return; try { await api('DELETE', `/api/books/${b.id}`); } catch { return; } refresh(); }}]);
      return;
    }
    const k = e.target.closest('[data-cb]')?.dataset.cb; if (!k) return;
    if (k === 'close') md.remove();
    if (k === 'phone') { md.remove(); davGuide(); }
    if (k === 'new') {
      const n = await wsAskNew(tr('New address book'));  // 2.30.0 (#1036): with its workspace
      if (!n) return;
      try { await api('POST', '/api/books', n); } catch { return; }
      refresh();
    }
  });
}
function ctShareModal(b, users, names, done) {
  const bOrg = () => b.imported || b.src_id ? null : b.org_id || null;  // 2.46.4 (#1737): a book mirrored from a connected account is always private
  const md = modal(`<h3>${tr('Share {0}', esc(b.name))}</h3><div class="shws"></div><div id="cbs-list"></div>
    <div class="row"><label for="cbs-user">${tr('Person')}</label><select id="cbs-user" data-sheet-av>${shWsOptions(users, bOrg(), b.members)}</select>
      <select id="cbs-role" aria-label="${esc(tr('Role'))}"><option value="view">${tr('can view')}</option><option value="edit">${tr('can edit')}</option></select><button class="btn sm pri" data-cbs="add">${tr('Share')}</button></div>
    <div class="shint">${tr('Contacts are personal data: share an address book only with people who may see all of it.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-cbs="close">${tr('Done')}</button></div>`);
  const draw = () => { $('#cbs-list', md).innerHTML = (b.members || []).length ? `<ul class="evclist">${b.members.map(m => `<li class="evcrow">${av(m.user_id, names.get(m.user_id) || '')}<span class="evcn">${esc(names.get(m.user_id) || '?')} <span class="muted">· ${esc(m.role === 'edit' ? tr('can edit') : tr('can view'))}</span></span><button class="iconbtn" data-cbsrm="${m.user_id}" aria-label="${esc(tr('Stop sharing with {0}', names.get(m.user_id) || ''))}">${ic('x', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('Not shared yet.')}</p>`; };
  const wsDraw = () => {  // 2.46.4 (#1737)
    shWsFill($('.shws', md), bOrg(), b.imported || b.src_id ? null : a => wsMoveMenu(a, b.org_id, async org => {
      try { await api('PATCH', `/api/books/${b.id}`, {org_id: org}); } catch { return; }
      b.org_id = org; wsDraw(); $('#cbs-user', md).innerHTML = shWsOptions(users, bOrg(), b.members); shWsPick($('#cbs-user', md)); done();
    }));
  };
  wsDraw(); shWsPick($('#cbs-user', md));
  draw();
  md.addEventListener('click', async e => {
    const rm = e.target.closest('[data-cbsrm]');
    if (rm) { try { await api('DELETE', `/api/books/${b.id}/members/${rm.dataset.cbsrm}`); } catch { return; } b.members = b.members.filter(m => m.user_id !== +rm.dataset.cbsrm); draw(); done(); return; }
    const k = e.target.closest('[data-cbs]')?.dataset.cbs; if (!k) return;
    if (k === 'close') md.remove();
    if (k === 'add' && $('#cbs-user', md).value) {
      try { const j = await api('PUT', `/api/books/${b.id}/members`, {user_id: +$('#cbs-user', md).value, role: $('#cbs-role', md).value}); b.members = j.members; } catch { return; }
      draw(); done();
    }
  });
}
function ctBdayModal(b, done) {  // module Family: the birthdays + anniversaries of this book become yearly tasks of a list
  const ls = S.lists.filter(l => !l.archived && canEditList(l.id));
  const md = modal(`<h3>${ic('cake', 's')} ${tr('Birthdays as tasks')}</h3>
    <p class="muted">${tr('Birthdays and anniversaries of the contacts in {0} become yearly tasks with the age and a reminder a week before.', esc(b.name))}</p>
    <div class="row"><label for="cbd-list">${tr('List')}</label><select id="cbd-list"><option value="">${tr('Off')}</option>${ls.map(l => `<option value="${l.id}" ${l.id === b.birthdays_list_id ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-cbd="close">${tr('Cancel')}</button><button class="btn pri" data-cbd="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async e => {
    const k = e.target.closest('[data-cbd]')?.dataset.cbd; if (!k) return;
    if (k === 'close') { md.remove(); return; }
    try { await api('PATCH', `/api/books/${b.id}`, {birthdays_list_id: $('#cbd-list', md).value ? +$('#cbd-list', md).value : null}); } catch { return; }
    md.remove(); done(); toast(tr('Saved'));
  });
}

// ---- the task panel: "Contacts" (waiting on / responsible / about) and "Events" of a task
function linksDetailHtml(t, ro) {
  if (!t || t.id <= 0 || t.context) return '';
  const cts = ctOn() ? (S.tcontacts || {})[t.id] || [] : [];
  const kinds = Object.fromEntries(CT_LINK);
  const ctHtml = ctOn() ? `<div class="lkgrp"><span class="lklab">${tr('Contacts')}</span><div class="lkitems">${cts.map(x => `<span class="lkchip ctlk"><button type="button" class="linkbtn" data-ctgo="${x.contact_id}">${ic('user', 's')}<span>${esc(x.fn)}</span></button><span class="muted">${esc(tr(kinds[x.kind] || 'About'))}</span>${ro ? '' : `<button type="button" class="iconbtn" data-ctunlink="${x.contact_id}" aria-label="${esc(tr('Remove the link to {0}', x.fn))}">${ic('x', 's')}</button>`}</span>`).join('')}
    ${ro ? '' : `<button type="button" class="attadd" data-act="ct-link">${ic('plus', 's')}<span>${tr('Link a contact')}</span></button>`}</div></div>` : '';
  const evHtml = typeof evTaskHtml === 'function' ? evTaskHtml(t, ro) : '';
  return ctHtml || evHtml ? `<div class="dsec lksec"><h5>${tr('People and dates')}</h5>${ctHtml}${evHtml}</div>` : '';
}
function ctLinkPop(anchor, tid) {
  const p = openPop(anchor, `<div class="ctpick"><div class="row"><input id="ctp-q" type="search" placeholder="${esc(tr('Search contacts'))}" aria-label="${esc(tr('Search contacts'))}" autocomplete="off"></div>
    <div class="seg ctpk" role="radiogroup" aria-label="${esc(tr('Kind of link'))}">${CT_LINK.map(([k, n], i) => `<button type="button" role="radio" data-ctpk="${k}" class="${i === 2 ? 'on' : ''}" aria-checked="${i === 2}">${tr(n)}</button>`).join('')}</div>
    <div class="ctpl" id="ctp-l" role="listbox" aria-label="${esc(tr('Contacts'))}"><div class="muted">${tr('Loading…')}</div></div>
    <button type="button" class="linkbtn" data-ctpnew>${ic('plus', 's')} ${tr('New contact')}</button></div>`);
  let kind = 'about', seq = 0;
  const find = async q => {
    const s = ++seq;
    let j; try { j = await api('GET', `/api/contacts?limit=30&q=${encodeURIComponent(q || '')}`); } catch { return; }
    if (s !== seq || !$('#ctp-l')) return;
    $('#ctp-l').innerHTML = j.items.length ? j.items.map(c => `<button type="button" role="option" class="ctrow" data-ctpick="${c.id}">${ctAv(c)}<span class="ctn"><b>${esc(c.fn)}</b><small class="muted">${esc(c.org || c.email || c.phone || '')}</small></span></button>`).join('') : `<div class="muted">${tr('No contact matches.')}</div>`;
  };
  find('');
  p.oninput = e => { if (e.target.id === 'ctp-q') { clearTimeout(p._t); p._t = setTimeout(() => find(e.target.value.trim()), 180); } };
  p.onclick = async e => {
    const k = e.target.closest('[data-ctpk]');
    if (k) { kind = k.dataset.ctpk; $$('[data-ctpk]', p).forEach(x => { x.classList.toggle('on', x === k); x.setAttribute('aria-checked', String(x === k)); }); return; }
    if (e.target.closest('[data-ctpnew]')) { closePop(); ctEditor(null); return; }
    const c = e.target.closest('[data-ctpick]'); if (!c) return;
    try { const j = await api('POST', `/api/tasks/${tid}/contacts`, {contact_id: +c.dataset.ctpick, kind}); S.tcontacts = {...(S.tcontacts || {}), [tid]: j.items}; } catch { return; }
    closePop(); renderDetail();
  };
  setTimeout(() => { if (!isTouch()) $('#ctp-q')?.focus(); }, 30);
}
document.addEventListener('click', async e => {
  const a = e.target.closest('[data-act="ct-link"]');
  if (a) { e.preventDefault(); if (S.sel) ctLinkPop(a, S.sel); return; }
  const g = e.target.closest('[data-ctgo]');
  if (g) { e.preventDefault(); go('contacts/' + g.dataset.ctgo); return; }
  const u = e.target.closest('[data-ctunlink]');
  if (u && S.sel) {
    e.preventDefault();
    const tid = S.sel, cid = +u.dataset.ctunlink;
    try { await api('DELETE', `/api/tasks/${tid}/contacts/${cid}`); } catch { return; }
    S.tcontacts = {...(S.tcontacts || {}), [tid]: ((S.tcontacts || {})[tid] || []).filter(x => x.contact_id !== cid)};
    renderDetail();
  }
});
