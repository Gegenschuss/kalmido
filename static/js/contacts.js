/* Kalmido web client: Contacts (module "contacts"): the contacts view (search, groups, address books), the editor, the
   contact card, links between contacts and tasks, import / export.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.21.0 (#658): the contacts live in Kalmido's own address books (S.books from /api/state) and sync with the phone over
// CardDAV. The view loads its page of contacts (GET /api/contacts, never part of /api/state: contacts are personal data
// and can be many); a contact opens as a card (desktop: next to the list, phone: the whole view), "Edit" opens the editor.
const CT = {q: '', group: '', book: '', folder: null, items: null, total: 0, groups: [], sel: null, card: null, loading: false, seq: 0, pick: null};  // 2.46.1 (#1554): pick = the selected ids (Set) in the selection mode
// 2.53.0 (#1410): ctOn + CT_LINK live in ctlinks.js (loaded at start: the task panel shows the linked contacts)
const CT_TYPES = {emails: [['home', N_('Home')], ['work', N_('Work')], ['other', N_('Other')]],
  phones: [['cell', N_('Mobile')], ['home', N_('Home')], ['work', N_('Work')], ['other', N_('Other')]],
  addresses: [['home', N_('Home')], ['work', N_('Work')], ['other', N_('Other')]], urls: [['home', N_('Home')], ['work', N_('Work')], ['other', N_('Other')]]};
const ctTypeWord = (k, it) => { const t = (it.type || [])[0], o = (CT_TYPES[k] || []).find(x => x[0] === t); return it.label && !/^_\$!</.test(it.label) ? it.label : o ? tr(o[1]) : t ? t : ''; };
const ctBook = id => (S.books || []).find(b => b.id === id);
const ctWrite = b => !!b && (b.role === 'owner' || b.role === 'edit');
// 2.53.0 (#1410): ctAv lives in ctlinks.js
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
  // 2.119.1 A (#2081): a reload of the same search keeps the pages loaded so far (up to the server's 2000), the rest come by scrolling
  const key = ctx_key(), keep = CT.items && CT.qk === key ? Math.min(2000, CT.items.length) : 0;
  let fresh = false;
  const qs = new URLSearchParams({q: CT.q, limit: String(Math.max(CTX_PAGE, keep))});
  if (CT.group) qs.set('group', CT.group);
  if (CT.book) qs.set('book_id', CT.book);
  if (CT.folder) qs.set('folder', CT.folder);  // 2.351.0 B (#2749): the books / contacts filed in one folder
  try {
    const j = await api('GET', '/api/contacts?' + qs);
    if (seq !== CT.seq) return;
    fresh = CT.qk !== key;
    CT.items = j.items; CT.total = j.total; CT.groups = j.groups || []; CT.qk = key;
  } catch (e) {
    if (seq === CT.seq && e?.status === 404 && CT.book) { CT.book = ''; CT.loading = false; return ctLoad(); }  // 2.46.4 (#1732): the filtered book is gone
    if (seq === CT.seq) CT.items = CT.items || [];
  }
  CT.loading = false;
  if (S.route.mod === 'contacts') ctDraw();
  if (fresh) for (const w of [$('#view .ctlistw'), $('#view')]) if (w) w.scrollTop = 0;  // 2.119.1 A (#2081): another search starts at the top (not at the end, which would load page two)
}
async function ctRoute(id) {
  // 2.351.0 B (#2749): #contacts/f/<folder> filters by a folder (ctfold.js), #contacts/b/<book> by an address book; the plain
  // #contacts ends the folder filter, opening a contact keeps it
  const r = S.route, fo = r.ctf || (id ? CT.folder : null);
  if (fo !== CT.folder || (r.ctb && String(r.ctb) !== String(CT.book))) { CT.folder = fo; if (r.ctb) CT.book = String(r.ctb); CT.items = null; CT.loading = false; }
  if (typeof ctf_load === 'function') ctf_load();
  if (CT.items === null && !CT.loading) ctLoad();
  if (id) await ctOpen(id); else if (isMobile()) { CT.sel = null; CT.card = null; ctDraw(); }
}
async function ctOpen(id) {
  CT.sel = id;
  try { CT.card = await api('GET', `/api/contacts/${id}`); } catch { CT.card = null; CT.sel = null; toast(tr('This contact does not exist or you cannot see it.')); }
  if (S.route.mod === 'contacts') ctDraw();
}
function ctDraw() { if (S.route.mod === 'contacts') { const el = $('#view'); if (el) { keepFocus(el, () => setHtml(el, mg_wrap('contacts', viewContacts()))); vl_after(); } } }  // 2.65.0 (#1825): vl_after
function viewContacts() {
  if (CT.trash) return ctt_html();  // 2.272.0 E1 (#3038)
  if (CT.items === null && !CT.loading) setTimeout(ctLoad, 0);
  ct_prune();  // 2.46.4 (#1732): also after a live update
  const books = (S.books || []).filter(b => wsObjIn(b));  // 2.30.0 (#1036): the address books of the shown workspace
  const items = CT.items === null ? null : CT.items.filter(c => !ctBook(c.book_id) || wsObjIn(ctBook(c.book_id)));
  const mob = isMobile(), showCard = CT.card && (!mob || CT.sel);
  const bar = `<div class="ctbar"><div class="ctsearch">${ic('search', 's')}<input id="ct-q" type="search" value="${esc(CT.q)}" placeholder="${esc(tr('Search contacts'))}" aria-label="${esc(tr('Search contacts'))}" autocomplete="off" enterkeyhint="search"></div>
    ${CT.groups.length ? `<select id="ct-group" aria-label="${esc(tr('Group'))}"><option value="">${tr('All groups')}</option>${CT.groups.map(g => `<option value="${esc(g)}" ${g === CT.group ? 'selected' : ''}>${esc(g)}</option>`).join('')}<option value="${CTX_MANAGE}">${tr('Manage groups…')}</option></select>` : ''}
    ${books.length > 1 ? `<select id="ct-book" aria-label="${esc(tr('Address book'))}"><option value="">${tr('All address books')}</option>${books.map(b => `<option value="${b.id}" ${String(b.id) === String(CT.book) ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select>` : ''}
    <span class="spacer"></span>${books.some(ctWrite) ? `<button class="iconbtn ${CT.pick ? 'on' : ''}" data-ct="pick" aria-pressed="${!!CT.pick}" aria-label="${esc(tr(CT.pick ? 'End selection' : 'Select'))}" title="${esc(tr(CT.pick ? 'End selection' : 'Select'))}">${ic('select')}</button>` : ''}<button class="btn sm pri" data-ct="new">${ic('plus', 's')}<span class="cdl">${tr('New contact')}</span></button>
    <button class="iconbtn" data-ct="menu" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>`;
  const list = items === null ? `<div class="muted ctempty">${tr('Loading…')}</div>` : !items.length
    ? `<div class="empty">${ic('users')}${CT.q || CT.group ? tr('No contact matches.') : tr('No contacts yet. Add one, import a vCard file, or connect the phone.')}</div>`
    : `<ul class="ctlist" role="list" aria-label="${esc(tr('Contacts'))}">${ctRows(items, (c, vl) => `<li${vl}><button type="button" class="ctrow ${c.id === CT.sel ? 'on' : ''} ${bk_rowCls(c)}" data-ctopen="${c.id}" ${CT.pick ? `aria-pressed="${CT.pick.has(c.id)}"` : `aria-current="${c.id === CT.sel}"`}>${CT.pick ? bk_chk(c) : ''}${ctAv(c)}<span class="ctn"><b>${esc(c.fn || c.org || '?')}</b><small class="muted">${esc([c.org !== c.fn ? c.org : '', c.email || c.phone].filter(Boolean).join(' · '))}</small></span>${(books.length > 1 && ctBook(c.book_id)) ? `<i class="cevdot" style="--cc:${cssColor(ctBook(c.book_id).color) || 'var(--accent)'}" title="${esc(ctBook(c.book_id).name)}"></i>` : ''}</button></li>`)}</ul>
      ${CT.total > CT.items.length ? `<div class="muted ctmore">${tr('{0} of {1} loaded', CT.items.length, CT.total)} <button type="button" class="linkbtn" data-ctxmore ${CT.more ? 'disabled' : ''}>${tr('Show more')}</button></div>` : ''}`;  // 2.119.1 A (#2081): the next page comes when scrolling near the end
  const fbar = typeof ctf_barHtml === 'function' && !(mob && showCard) ? ctf_barHtml() : '';  // 2.351.0 B (#2749): the folder filter
  return `<div class="ctview ${showCard ? 'withcard' : ''} ${CT.pick ? 'ctpicking' : ''}"><h2 class="sr">${tr('Contacts')}</h2>${ct18_hintHtml()}${CT.pick && !(mob && showCard) ? bk_barHtml() : ''}${mob && showCard ? '' : bar}${fbar}<div class="ctcols">${mob && showCard ? '' : `<div class="ctlistw" data-vlsc>${list}</div>`}${showCard ? ctCardHtml(CT.card) : mob ? '' : `<div class="ctcard ctnone muted">${ic('user')}${tr('Choose a contact')}</div>`}</div></div>`;
}
// 2.364.0 B (#3018): Office & finance off: a line above the contacts that turns it on right here (instead of Settings >
// Modules > Areas > Parts); everyone but a child switches their own modules (without an organisation they are their own admin)
const ct18_hintHtml = () => S.me?.kid || officeOn() || LS.get('ct18Hide') ? '' : `<div class="ct18" data-ct18>${ic('receipt', 's')}<span>${esc(tr('Quotations and invoices?'))}</span>
  <label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" data-ct18on><span class="swt" aria-hidden="true"></span></span><span>${esc(tr('Turn on Office & finance'))}</span></label>
  <button type="button" class="iconbtn" data-ct18x aria-label="${esc(tr('Hide'))}" title="${esc(tr('Hide'))}">${ic('x', 's')}</button></div>`;
document.addEventListener('change', async e => {
  const el = e.target.closest?.('[data-ct18on]'); if (!el || !el.checked) return;
  el.disabled = true;
  await loadModule('settings');
  const fs = new Set((S.settings.features ?? FEATS.map(x => x[0]).join(',')).split(',').filter(Boolean)); fs.add('office');
  const ok = await setApply({features: FEATS.map(x => x[0]).filter(x => fs.has(x)).join(',')}, tr('{0} on', tr('Office & finance')));
  if (ok === false) { el.checked = false; el.disabled = false; return; }
  go('office');
});
document.addEventListener('click', e => { if (!e.target.closest?.('[data-ct18x]')) return; LS.set('ct18Hide', true); $('[data-ct18]')?.remove(); });
// 2.272.0 E1 (#3038): the contacts' trash (More > Trash): the deleted contacts and address books, Restore, Delete for good
// (asks with the number); after the trash period the server deletes them for good (trash_days)
async function ctt_load() {
  const [j, bj] = await Promise.all([api('GET', '/api/contacts?trash=1&limit=2000').catch(() => null), api('GET', '/api/books?trash=1').catch(() => null)]);
  if (!CT.trash) return;
  CT.trash = {items: j?.items || [], books: bj?.items || [], days: j?.trash_days || bj?.trash_days || 0};
  ctDraw();
}
function ctt_html() {
  const t = CT.trash, since = x => esc(tr('In the trash since {0}', fmtDate((x.deleted_at || '').slice(0, 10))));
  const bar = `<div class="ctbar"><button class="iconbtn" data-ct="tback" aria-label="${esc(tr('Back'))}">${ic('back')}</button><h2 class="sr">${tr('Trash')}</h2><b>${tr('Trash')}</b><span class="spacer"></span>${t.items?.length ? `<button class="btn sm" data-ct="tempty">${ic('trash', 's')} ${tr('Empty trash')}</button>` : ''}</div>`;
  if (!t.items) { setTimeout(ctt_load, 0); return `<div class="ctview">${bar}<div class="muted ctempty">${tr('Loading…')}</div></div>`; }
  const row = (x, k, name, sub) => `<li><div class="ctrow msarch">${k === 'b' ? `<i class="cevdot" style="--cc:${cssColor(x.color) || 'var(--accent)'}"></i>` : ctAv(x)}<span class="ctn"><b>${esc(name)}</b><small class="muted">${sub}</small></span>
    <button type="button" class="btn sm" data-ctt="${k}rest" data-id="${x.id}">${ic('undo', 's')} ${tr('Restore')}</button><button type="button" class="iconbtn" data-ctt="${k}purge" data-id="${x.id}" aria-label="${esc(tr('Delete for good'))}" title="${esc(tr('Delete for good'))}">${ic('trash', 's')}</button></div></li>`;
  const list = t.books.length || t.items.length ? `<ul class="ctlist" role="list" aria-label="${esc(tr('Trash'))}">${t.books.map(b => row(b, 'b', b.name, esc(trn('{0} contact', '{0} contacts', b.count)) + ' · ' + since(b))).join('')}${t.items.map(c => row(c, 'c', c.fn || c.org || '?', [esc(ctBook(c.book_id)?.name || ''), since(c)].filter(Boolean).join(' · '))).join('')}</ul>` : `<div class="empty">${ic('trash')}${tr('The trash is empty')}</div>`;
  return `<div class="ctview">${bar}<div class="ctlistw">${list}${t.days ? `<p class="muted mscltrdays">${esc(trashNote(trn('Contacts in the trash are deleted for good after {0} day.', 'Contacts in the trash are deleted for good after {0} days.', t.days)))}</p>` : ''}</div></div>`;
}
async function ctt_act(k, id) {
  const t = CT.trash; if (!t?.items) return;
  const again = async () => { CT.trash = {}; await load().catch(() => {}); ctLoad(); };
  try {
    if (k === 'crest') await api('POST', `/api/contacts/${id}/restore`);
    else if (k === 'brest') await api('POST', `/api/books/${id}/restore`);
    else if (k === 'bpurge') {
      const b = t.books.find(x => x.id === id); if (!b) return;
      if (!await askConfirm(tr('Delete the address book “{0}” for good?', b.name), trn('Its {0} contact is deleted with it. This cannot be undone.', 'Its {0} contacts are deleted with it. This cannot be undone.', b.count), {ok: tr('Delete for good'), danger: true})) return;
      await api('POST', `/api/books/${id}/purge`);
    } else {
      const ids = k === 'call' ? t.items.map(c => c.id) : [id]; if (!ids.length) return;
      if (!await askConfirm(trn('Delete {0} contact for good?', 'Delete {0} contacts for good?', ids.length), tr('This cannot be undone.'), {ok: tr('Delete for good'), danger: true})) return;
      await bk_send({action: 'purge'}, ids);
    }
  } catch (x) { toast(x.message || ''); again(); return; }
  if (k.endsWith('rest')) toast(tr('Restored'));
  again();
}
// 2.119.1 A (#2081): every contact is reachable: the list loads pages of CTX_PAGE (GET /api/contacts offset / limit); scrolling
// near the end of the list (or "Show more") appends the next page. A new search / group / address book starts again at page one
const CTX_PAGE = 500;
const ctx_key = () => [CT.q, CT.group, CT.book, CT.folder].join('\u0001');  // 2.351.0 B (#2749): + the folder
async function ctx_more() {
  if (!CT.items || CT.loading || CT.more || CT.items.length >= CT.total) return;
  const seq = CT.seq, key = ctx_key();
  if (CT.qk !== key) return;
  CT.more = true;
  const qs = new URLSearchParams({q: CT.q, limit: String(CTX_PAGE), offset: String(CT.items.length)});
  if (CT.group) qs.set('group', CT.group);
  if (CT.book) qs.set('book_id', CT.book);
  if (CT.folder) qs.set('folder', CT.folder);  // 2.351.0 B (#2749): the books / contacts filed in one folder
  try {
    const j = await api('GET', '/api/contacts?' + qs);
    if (seq === CT.seq && key === ctx_key() && CT.items) {
      const have = new Set(CT.items.map(c => c.id));
      CT.items.push(...j.items.filter(c => !have.has(c.id)));
      CT.total = j.items.length ? j.total : CT.items.length;  // an empty page: the rest is gone meanwhile
    }
  } catch { /* api() showed it; scrolling tries again */ }
  CT.more = false;
  if (seq === CT.seq && S.route.mod === 'contacts') ctDraw();
}
function ctx_near(sc) { return sc.scrollHeight - sc.scrollTop - sc.clientHeight < Math.max(600, sc.clientHeight * 1.5); }
document.addEventListener('scroll', e => {
  if (S.route.mod !== 'contacts' || !CT.items || CT.more || CT.items.length >= CT.total) return;
  const sc = e.target; if (!(sc instanceof Element) || !(sc.matches('.ctlistw') || sc.id === 'view')) return;
  if (ctx_near(sc)) ctx_more();
}, {capture: true, passive: true});
document.addEventListener('click', e => { if (e.target.closest('[data-ctxmore]')) { e.preventDefault(); ctx_more(); } });
// 2.65.0 (#1825): a long address book draws only the rows near the visible part (vlist.js); row(c, attrs) = one <li>
function ctRows(items, row) {
  if (!vl_begin(items.length)) return items.map(c => row(c, '')).join('');
  return vl_seg('ct', items, (c, i) => row(c, ` data-vlg="${c.id}" aria-setsize="${items.length}" aria-posinset="${i + 1}"`), false, 'li');
}
function ctCardHtml(c) {
  const b = ctBook(c.book_id), w = c.role ? c.role === 'owner' || c.role === 'edit' : ctWrite(b);  // 2.351.0 B (#2749): also through a folder
  const it = (k, icon, href) => (c[k] || []).map(x => `<div class="ctf">${ic(icon, 's')}<span class="ctfl muted">${esc(ctTypeWord(k, x))}</span>${href(x)}</div>`).join('');
  const adr = (c.addresses || []).map(a => { const t = [a.street, [a.code, a.city].filter(Boolean).join(' '), a.region, a.country].filter(Boolean).join(', ');
    return `<div class="ctf">${ic('mappin', 's')}<span class="ctfl muted">${esc(ctTypeWord('addresses', a))}</span>${ctk_mapLink(t)}</div>`; }).join('');  // 2.119.1 B (#2086): a map link
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
      ${typeof nwl_ctf === 'function' ? nwl_ctf(c, w) : ''}${''/* 2.55.0 (#1455): the newsletter consent (newsletter.js) */}
    </div>
    ${c.note ? `<div class="ctnote md">${renderMd(c.note, false, {})}</div>` : ''}
    ${lifeCareHtml(c)}
    ${(c.clients || []).length ? `<div class="ctsec cklsec"><h4>${tr('Contact person at')}</h4><ul class="ctlinks">${c.clients.map(x => `<li><a class="linkbtn" href="#client/${x.client_id}">${ic('brief', 's')} ${esc(x.name)}</a>${x.role ? `<span class="muted"> · ${esc(x.role)}</span>` : ''}</li>`).join('')}</ul></div>` : ''}${''/* 2.59.0 (#1735): the clients this contact is a contact person of (only who may open them) */}
    <div class="ctsec"><h4>${tr('Tasks')}</h4>${(c.tasks || []).length ? `<ul class="ctlinks">${c.tasks.map(t => `<li><button type="button" class="linkbtn ${t.status ? 'done' : ''}" data-cttask="${t.task_id}">${ic(t.status ? 'done' : 'list', 's')} ${esc(t.title)}</button><span class="muted"> · ${esc(tr(kinds[t.kind] || 'About'))}</span></li>`).join('')}</ul>` : `<p class="muted">${tr('No linked tasks yet: “Link a contact” in a task’s panel.')}</p>`}</div>
    ${(c.events || []).length ? `<div class="ctsec"><h4>${tr('Events')}</h4><ul class="ctlinks">${c.events.map(e => `<li><button type="button" class="linkbtn" data-evopen="${e.event_id}">${ic('cal', 's')} ${esc(e.title)}</button><span class="muted"> · ${esc(e.all_day ? fmtDayAbs(e.start.slice(0, 10)) : fmtDayAbs(e.start.slice(0, 10)) + ' ' + fmtTimeLoc(e.start.slice(11, 16)))}</span></li>`).join('')}</ul></div>` : ''}
    ${ctk_histHtml(c)}
    ${w && (c.merges || []).length ? ctm_histHtml(c) : ''}
  </article>`;
}
// 2.119.1 B (#2083): "History" on the card -- filed mails from / to the contact, the quotations / invoices / credit notes of
// its clients and its events, newest first (GET /api/contacts/<id>/history, only what the person may see; "Show more"
// fetches the next page). Loaded once per opened card (a new card object = a new load); hidden while empty.
const CTK = {card: null, items: [], more: false, loading: false};
function ctk_histHtml(c) {
  if (S.me?.kid || S.me?.kind === 'agent') return '';
  if (CTK.card !== c) { CTK.card = c; CTK.items = []; CTK.more = false; setTimeout(() => ctk_histLoad(c, 0), 0); return `<div class="ctsec ctkhist" data-ctkh hidden></div>`; }
  if (!CTK.items.length) return `<div class="ctsec ctkhist" data-ctkh hidden></div>`;
  const icon = {mail: 'mail', offer: 'file', invoice: 'receipt', credit: 'receipt', event: 'cal'};
  const word = {mail: tr('E-mail'), offer: tr('Quotation'), invoice: tr('Invoice'), credit: tr('Credit note'), event: tr('Appointment')};
  const when = x => !x.at ? '' : x.kind === 'event' && !x.all_day && x.at.length > 10 ? `${fmtDayAbs(x.at.slice(0, 10))} ${fmtTimeLoc(x.at.slice(11, 16))}` : fmtDayAbs(x.at.slice(0, 10));
  const title = x => x.title || (x.kind === 'mail' ? tr('(no subject)') : x.kind === 'event' ? '?' : tr('Draft'));
  const open = x => x.kind === 'event' ? `<button type="button" class="linkbtn" data-evopen="${x.id}">` : x.kind === 'mail' ? `<button type="button" class="linkbtn" data-ctkmail="${x.id}">`
    : `<a class="linkbtn" href="#office/offers/${x.id}">`;
  return `<div class="ctsec ctkhist" data-ctkh><h4>${tr('Contact history')}</h4><ul class="ctlinks">${CTK.items.map(x => `<li>${open(x)}${ic(icon[x.kind] || 'file', 's')} ${esc(title(x))}${x.kind === 'event' || x.kind === 'mail' ? '</button>' : '</a>'}<span class="muted"> · ${esc([word[x.kind], x.sub, when(x)].filter(Boolean).join(' · '))}</span></li>`).join('')}</ul>
    ${CTK.more ? `<button type="button" class="linkbtn" data-ctkmore ${CTK.loading ? 'disabled' : ''}>${tr('Show more')}</button>` : ''}</div>`;
}
async function ctk_histLoad(c, offset) {
  CTK.loading = true;
  let j; try { j = await rawFetch('GET', `/api/contacts/${c.id}/history?offset=${offset}`); } catch { j = null; }  // quiet: no section
  CTK.loading = false;
  if (CTK.card !== c || !j) return;
  CTK.items = offset ? [...CTK.items, ...j.items] : j.items; CTK.more = !!j.more;
  const el = $('#view [data-ctkh]'); if (el) el.outerHTML = ctk_histHtml(c);
}
// 2.119.1 B (#2082): "Create as client" in the card's menu (people with the module Clients): a client with the contact's
// company (else its name), first e-mail, phone and address, and the contact as its default contact person, linked when
// the address book fits the client (POST /api/clients checks it, office/contacts_cl.py ckl_book_fits: an organisation's
// book -> a client of that organisation, an own private book -> a private client). Other books (a personal book in an
// organisation's workspace, one shared by somebody else): the client of the book's workspace without the link. One undo
// step (delete the client again). A linked contact shows "Open client" instead.
function ctk_clientItem(c, b) {
  if (typeof clientsOn !== 'function' || !clientsOn() || S.me?.kid || S.me?.kind === 'agent' || c.kind === 'group') return false;
  const cl = (c.clients || [])[0];
  if (cl) return {label: tr('Open client'), icon: 'brief', fn: () => go('client/' + cl.client_id)};
  return {label: tr('Create as client'), icon: 'brief', fn: () => ctk_makeClient(c, b)};
}
function ctk_cty(v) {  // a contact's country (a code or a name in any app language) -> its ISO code, '' when unknown
  const s = String(v || '').trim(); if (!s || typeof ctyValid !== 'function') return '';
  if (s.length <= 3 && ctyValid(s)) return ctyCode(s);
  const f = ctyFold(s);
  return Object.entries(ctyNames()).find(([, n]) => ctyFold(n) === f)?.[0] || '';
}
function ctk_clientBody(c, b, link) {
  const pick = (k, pref) => { const xs = (c[k] || []).filter(x => (x.value || '').trim()); return (xs.find(x => (x.type || []).includes(pref)) || xs[0])?.value?.trim() || ''; };
  const okMail = v => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v) ? v : '';
  const email = okMail(pick('emails', 'work')), phone = pick('phones', 'work');
  const as = c.addresses || [], a = as.find(x => (x.type || []).includes('work')) || as[0] || {};
  const name = (c.org || c.fn || '').trim().slice(0, 80);
  const body = {name, email: email.slice(0, 200), phone: phone.slice(0, 60), street: (a.street || '').slice(0, 200), zip: (a.code || '').slice(0, 20),
    city: (a.city || '').slice(0, 120), org_id: link ? (b.org_owned ? b.org_id : null) : (b?.org_id ?? null),
    contacts: [{name: (c.fn || c.org || name).trim().slice(0, 120), role: (c.title || '').slice(0, 120), email: email.slice(0, 200), phone: phone.slice(0, 60),
      is_default: true, contact_id: link ? c.id : null}]};
  const cty = ctk_cty(a.country); if (cty) body.country = cty;
  return body;
}
async function ctk_makeClient(c, b) {
  const link = !!b && (b.org_owned ? !!b.org_id : !b.org_id && b.owner_id === S.me?.id);
  const body = ctk_clientBody(c, b, link);
  if (!body.name) return;
  let id = 0;
  const after = async () => { await load().catch(() => {}); if (CT.card?.id === c.id) await ctOpen(c.id); if (typeof clReload === 'function') clReload(); };
  const make = async () => {
    let r;
    try { r = await rawFetch('POST', '/api/clients', body); }
    catch (x) {  // the contact went away / its book no longer fits: the client without the link
      if (x.data?.code !== 'contact_gone') throw x;
      body.contacts[0].contact_id = null; r = await rawFetch('POST', '/api/clients', body);
    }
    id = r.id; await after(); return r;
  };
  let r; try { r = await make(); } catch (x) { toast(x.message || ''); return; }
  offerUndo(tr('Added: {0}', r.name), histAdd({label: tr('Create as client'), undo: async () => { await api('DELETE', `/api/clients/${id}`); await after(); }, redo: make}));
}
document.addEventListener('input', e => {
  if (e.target.id !== 'ct-q') return;
  CT.q = e.target.value;
  clearTimeout(CT.t); CT.t = setTimeout(ctLoad, 200);
});
document.addEventListener('change', e => {
  if (e.target.id === 'ct-group' && e.target.value === CTX_MANAGE) { e.target.value = CT.group; ctx_groupsModal(); return; }  // 2.119.1 A (#2085)
  if (e.target.id === 'ct-group') { CT.group = e.target.value; ctLoad(); }
  if (e.target.id === 'ct-book') { CT.book = e.target.value; ctLoad(); }
});
document.addEventListener('click', async e => {
  const tt = e.target.closest('#view [data-ctt]');  // 2.272.0 E1 (#3038): the trash's rows
  if (tt) { ctt_act(tt.dataset.ctt, +tt.dataset.id); return; }
  const mu = e.target.closest('[data-ctmundo]');  // 2.66.0 A (#1835): undo a merge from the card's history
  if (mu) { ctm_undoCard(+mu.dataset.ctmundo, mu); return; }
  const bb = e.target.closest('#ct-sbar [data-ctb]');
  if (bb) { bk_barAct(bb.dataset.ctb, bb); return; }
  const o = e.target.closest('[data-ctopen]');
  if (o && (CT.pick || (ms_modClick(e) && !isMobile() && bk_canPick()))) { e.preventDefault(); if (!ms_lpRecent(bk_lpS)) bk_click(+o.dataset.ctopen, e.shiftKey); return; }  // 2.46.1 (#1554): the selection mode; 2.47.3 (#1733): Shift- / Cmd-click
  if (o && ms_lpRecent(bk_lpS)) { e.preventDefault(); return; }  // the click that ends a long press
  if (o) { e.preventDefault(); if (isMobile()) go('contacts/' + o.dataset.ctopen); else ctOpen(+o.dataset.ctopen); return; }
  const hm = e.target.closest('[data-ctkmail]');  // 2.119.1 B (#2083): a mail of the card's history
  if (hm) { if (typeof hbm_open === 'function') hbm_open(+hm.dataset.ctkmail); return; }
  if (e.target.closest('[data-ctkmore]') && CTK.card && !CTK.loading) { ctk_histLoad(CTK.card, CTK.items.length); return; }
  const tk = e.target.closest('[data-cttask]');
  if (tk) { e.preventDefault(); const id = +tk.dataset.cttask; if (taskById(id)) openDetail(id); else go('t/' + id); return; }
  const gp = e.target.closest('[data-ctgroup]');
  if (gp) { CT.group = gp.dataset.ctgroup; CT.sel = null; CT.card = null; if (isMobile()) go('contacts'); ctLoad(); return; }
  const b = e.target.closest('#view [data-ct]'); if (!b) return;
  const k = b.dataset.ct;
  if (k === 'pick') { CT.pick = CT.pick ? null : new Set(); ctDraw(); return; }
  if (k === 'tback') { CT.trash = null; ctDraw(); return; }  // 2.272.0 E1 (#3038)
  if (k === 'tempty') { ctt_act('call'); return; }
  if (k === 'new') ctEditor(null);
  else if (k === 'edit' && CT.card) ctEditor(CT.card);
  else if (k === 'back') { CT.sel = null; CT.card = null; go('contacts'); }
  else if (k === 'menu') {
    menu(b, [{label: tr('Address books…'), icon: 'folder', fn: ctBooksModal},
      {label: tr('Trash'), icon: 'trash', fn: () => { CT.trash = {}; CT.pick = null; ctDraw(); }},  // 2.272.0 E1 (#3038)
      {label: tr('Import a vCard file…'), icon: 'upload', fn: () => ctImport()},
      {label: tr('Import a CSV file…'), icon: 'upload', fn: () => ctImport(null, 'csv')},  // 2.119.1 A (#2080): Outlook, Google, a spreadsheet
      ...(S.books || []).map(x => ({label: tr('Export {0} (vCard)', x.name), icon: 'download', fn: () => { location.href = `/api/books/${x.id}/export.vcf`; }})),
      ...(S.books || []).map(x => ({label: tr('Export {0} (CSV)', x.name), icon: 'download', fn: () => { location.href = `/api/books/${x.id}/export.csv`; }})),
      {label: tr('On the phone…'), icon: 'phone', fn: davGuide},
      CT.groups.length && {label: tr('Manage groups…'), icon: 'tag', fn: ctx_groupsModal},  // 2.119.1 A (#2085)
      typeof nwl_open === 'function' && {label: tr('Newsletter…'), icon: 'mail', fn: nwl_open},  // 2.55.0 (#1455)
      typeof dup_open === 'function' && propOn() && dup_books().length && {label: tr('Find duplicates with an agent…'), icon: 'bot', fn: () => dup_open()}]);  // 2.70.0 B (#1357)
  } else if (k === 'cmenu' && CT.card) {
    const c = CT.card, w = ctWrite(ctBook(c.book_id));
    menu(b, [w && {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: async () => {
      // 2.272.0 E1 (#3038): into the trash; Undo takes it out again (with its notes and links)
      if (!await askConfirm(tr('Delete the contact “{0}”?', c.fn), tr('It goes to the trash and is removed from the phones that sync this address book.'), {ok: tr('Delete'), danger: true})) return;
      try { await api('DELETE', `/api/contacts/${c.id}`); } catch { return; }
      CT.sel = null; CT.card = null; await load().catch(() => {}); if (isMobile()) go('contacts'); ctLoad();
      toast(tr('Contact deleted'), async () => { try { await api('POST', `/api/contacts/${c.id}/restore`); } catch (x) { toast(x.message || ''); return; } await load().catch(() => {}); ctLoad(); }); }},
      feat('events') && {label: tr('Invite to a new event'), icon: 'cal', fn: () => evEditor({attendees: [{contact_id: c.id, name: c.fn, email: c.emails?.[0]?.value || '', partstat: 'needs-action'}]})},
      typeof nwl_ctItem === 'function' && nwl_ctItem(c, w, b),  // 2.55.0 (#1455): the newsletter consent
      ctk_clientItem(c, ctBook(c.book_id)),  // 2.119.1 B (#2082): create a client from the contact / open its client
      ...(typeof ctf_cardItems === 'function' ? ctf_cardItems(c) : [])]);  // 2.351.0 B (#2749): into a folder, share it there
  }
});

// ---- 2.46.1 (#1554): several contacts at once. The selection mode (the select button in the bar; on the phone a long
// press on a row) shows a tick per row; a tap adds / removes a contact. The floating bar (like the tasks' selection bar)
// shows the count, "All" (every contact matching the search, group and address book, also beyond the shown 500), Move
// (an address book one may change) and Delete (one question with the count). One request each (POST /api/contacts/bulk);
// contacts in read-only address books cannot be ticked. 2.272.0 E1 (#3038): deleted contacts lie in the trash (Undo in the toast).
// 2.47.3 (#1733): the bar, the long press and Shift- / Cmd-click come from multisel.js (shared with the clients)
const bk_can = c => ctWrite(ctBook(c.book_id));
const bk_rowCls = c => !CT.pick ? '' : CT.pick.has(c.id) ? 'picked' : bk_can(c) ? '' : 'ctro';
const bk_chk = c => `<span class="ctchk ${CT.pick.has(c.id) ? 'on' : ''}" aria-hidden="true">${CT.pick.has(c.id) ? ic('check', 's') : ''}</span>`;
function bk_toggle(id) {
  const c = (CT.items || []).find(x => x.id === id); if (!c || !CT.pick) return;
  if (!bk_can(c)) { toast(tr('You can only read this address book')); return; }
  if (CT.pick.has(id)) CT.pick.delete(id); else CT.pick.add(id);
  CT.last = id; CT.pickAll = null;
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
function bk_end() { CT.pick = null; CT.pickAll = null; ctDraw(); }
function bk_barHtml() {
  return ms_barHtml('ct-sbar', 'ctb', CT.pick.size, tr('Tap contacts'), [['all', 'all', bk_allOn() ? tr('Select none') : tr('All')], ['edit', 'edit', tr('Edit')], ['move', 'folder', tr('Move')], ['merge', 'collapse', tr('Merge'), '', 2], ['del', 'trash', tr('Delete'), 'danger']]);
}
// every contact of the current search / group / address book (also the pages the list has not loaded yet): fetched as pages
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
const bk_allOn = () => !!CT.pick?.size && CT.items !== null && (CT.pickAll === ctx_key() || CT.total <= CT.items.length && bk_shown(CT.items).every(c => CT.pick.has(c.id)) && CT.pick.size >= bk_shown(CT.items).length);  // 2.119.1 A (#2081): "All" also covers the pages not loaded yet
async function bk_barAct(k, el) {
  if (!CT.pick) return;
  if (k === 'close') { bk_end(); return; }
  if (k === 'all') {
    if (bk_allOn()) { CT.pick.clear(); CT.pickAll = null; ctDraw(); return; }
    let all; try { all = bk_shown(await bk_matching()); } catch { return; }
    for (const c of all) CT.pick.add(c.id);
    CT.pickAll = ctx_key();
    ctDraw(); return;
  }
  const ids = [...CT.pick]; if (!ids.length) return;
  if (k === 'del') {
    if (!await askConfirm(trn('Delete {0} contact?', 'Delete {0} contacts?', ids.length), tr('They go to the trash and are removed from the phones that sync these address books.'), {ok: tr('Delete'), danger: true})) return;
    try { await bk_send({action: 'delete'}, ids); } catch (e) { if (e.data?.code === 'partial') { bk_end(); await load().catch(() => {}); ctLoad(); } return; }  // 2.58.0 (#1656): some are gone already
    // 2.272.0 E1 (#3038): they lie in the trash; Undo takes them out again
    toast(trn('{0} contact deleted', '{0} contacts deleted', ids.length), async () => { try { await bk_send({action: 'undelete'}, ids); } catch (x) { toast(x.message || ''); return; } await load().catch(() => {}); ctLoad(); });
    if (CT.pick && CT.sel && ids.includes(CT.sel)) { CT.sel = null; CT.card = null; }
    bk_end(); await load().catch(() => {}); ctLoad();
  } else if (k === 'edit') bk_edit(ids);
  else if (k === 'merge') ctm_merge(ids);  // 2.66.0 A (#1835)
  else if (k === 'move') {
    const books = (S.books || []).filter(b => ctWrite(b) && wsObjIn(b) && !b.imported);
    if (!books.length) { toast(tr('No address book you may change')); return; }
    menu(el, books.map(b => ({label: b.name, icon: 'folder', fn: () => bk_move(ids, b)})), null, null, tr('Move'));
  }
}
async function bk_send(body, ids) {  // one request per 5000 (the server's limit; an address book holds up to 20000)
  const out = {moved: 0, copied: 0, conflicts: []};  // 2.138.4 C (#2378): copied = out of an imported (mirrored) address book
  for (let i = 0; i < ids.length; i += 5000) { const j = await api('POST', '/api/contacts/bulk', {...body, ids: ids.slice(i, i + 5000)}); out.moved += j.moved || 0; out.copied += j.copied || 0; out.conflicts.push(...(j.conflicts || [])); }
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
  const out = {changed: 0, skipped: 0, undo: [], conflicts: 0}, all = items || ids;
  for (let i = 0; i < all.length; i += 5000) {
    const part = all.slice(i, i + 5000);
    const j = await rawFetch('POST', '/api/contacts/bulk', items ? {...body, items: part} : {...body, ids: part});
    out.changed += j.changed || 0; out.skipped += j.skipped || 0; out.undo.push(...(j.undo || []));
    out.conflicts += (j.conflicts || []).length;  // 2.273.0 C (#3048): changed again meanwhile, the undo left them
  }
  if (out.conflicts) toast(trn('{0} contact was changed meanwhile and stayed as it is', '{0} contacts were changed meanwhile and stayed as they are', out.conflicts));
  return out;
}
async function bk_move(ids, b) {
  let j; try { j = await bk_send({action: 'move', book_id: b.id}, ids); } catch (e) { if (e.data?.code === 'partial') { bk_end(); await load().catch(() => {}); ctLoad(); } return; }  // 2.58.0 (#1656)
  const conf = (j.conflicts || []).length;
  toast([j.moved || !j.copied ? trn('{0} contact moved to {1}', '{0} contacts moved to {1}', j.moved, b.name) : '', j.copied ? trn('{0} copied from an imported address book', '{0} copied from imported address books', j.copied) : '', conf ? trn('{0} was there already and stayed', '{0} were there already and stayed', conf) : ''].filter(Boolean).join(' · '));
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
  const fold = !!c && !ctWrite(ctBook(c.book_id));  // 2.351.0 B (#2749): changed through its folder: stays in its address book
  if (!books.length && !fold) { try { const bk = await api('POST', '/api/books', {name: tr('Contacts'), org_id: wsDefaultOrg()}); await load(); books.push(bk); } catch { return; } }
  const st = c ? JSON.parse(JSON.stringify(c)) : {book_id: +(CT.book || LS.get('ctBook', 0)) || books[0].id, given: '', family: '', fn: '', org: '', title: '', dept: '', nickname: '',
    emails: [{value: '', type: ['home']}], phones: [{value: '', type: ['cell']}], addresses: [], urls: [], bday: '', anniversary: '', note: '', groups: [], photo: ''};
  if (!fold && !books.some(b => b.id === st.book_id)) st.book_id = books[0].id;
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
      ${fold ? '' : `<div class="row"><label for="ct-bk">${tr('Address book')}</label><select id="ct-bk">${books.map(b => `<option value="${b.id}" ${b.id === st.book_id ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select></div>`}</details>
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
      note: $('#ct-note', md).value, groups: v('ct-groups').split(',').map(x => x.trim()).filter(Boolean), photo: st.photo || '', book_id: fold ? st.book_id : +v('ct-bk') || st.book_id};
    if (!body.given && !body.family && !body.org && !body.fn) { toast(tr('A name or a company, please')); $('#ct-given', md).focus(); return; }
    if (!c && !await ctx_dupAsk(body, md)) return;  // 2.119.1 A (#2084): a look-alike first (the next Save creates it anyway)
    try {
      const r = c ? await api('PATCH', `/api/contacts/${c.id}`, {...body, expect: c.updated_at}) : await api('POST', '/api/contacts', body);
      LS.set('ctBook', body.book_id);
      md.remove(); CT.sel = r.id; CT.card = r;
      toast(r.copied ? tr('Copied from the imported address book') : c ? tr('Contact saved') : tr('Contact created'));  // 2.138.4 C (#2378)
      await load().catch(() => {}); ctLoad();
      if (S.route.mod === 'contacts' && isMobile() && !c) go('contacts/' + r.id);
    } catch { /* api() showed it */ }
  });
  setTimeout(() => { if (!c && !isTouch()) $('#ct-given', md)?.focus(); }, 40);
}
// 2.119.1 A (#2084): before a new contact is created, the address books one sees are asked for one with the same e-mail, phone
// or name (POST /api/contacts/dupcheck, reads only). A hit shows a quiet note in the editor: open the one there, or Save again
// = create anyway. Never merged by itself; a failed check never blocks the save
async function ctx_dupAsk(body, md) {
  const sig = JSON.stringify([body.fn, body.given, body.family, body.org, body.emails.map(x => x.value), body.phones.map(x => x.value)]);
  if (md.dataset.ctxok === sig) return true;
  let j; try { j = await rawFetch('POST', '/api/contacts/dupcheck', {fn: body.fn, given: body.given, family: body.family, org: body.org, emails: body.emails.map(x => x.value), phones: body.phones.map(x => x.value)}); } catch { return true; }
  const it = j.items || [];
  if (!it.length) return true;
  md.dataset.ctxok = sig;
  const why = {email: tr('same e-mail'), phone: tr('same phone'), name: tr('same name')};
  $('.ctxdup', md)?.remove();
  $('.foot', md).insertAdjacentHTML('beforebegin', `<div class="ctxdup" role="status"><p>${ic('users', 's')} ${tr('There is already a contact like this:')}</p><ul class="ctlinks">${it.map(x => `<li><button type="button" class="linkbtn" data-ctxdup="${x.id}">${esc(x.fn || x.org || '?')}</button><span class="muted"> · ${esc(x.reasons.map(r => why[r]).join(', '))}${ctBook(x.book_id) && (S.books || []).length > 1 ? ' · ' + esc(ctBook(x.book_id).name) : ''}</span></li>`).join('')}</ul><p class="muted">${tr('Save again to create it anyway.')}</p></div>`);
  $('[data-ctm2="save"]', md).textContent = tr('Create anyway');
  if (!md.dataset.ctxl) md.addEventListener('click', e => {
    const o = e.target.closest('[data-ctxdup]'); if (!o) return;
    md.remove(); if (S.route.mod === 'contacts' && isMobile()) go('contacts/' + o.dataset.ctxdup); else if (S.route.mod === 'contacts') ctOpen(+o.dataset.ctxdup); else go('contacts/' + o.dataset.ctxdup);
  });
  md.dataset.ctxl = '1';
  announce(tr('There is already a contact like this:'));
  return false;
}
// the import's answer names the new contacts that look like one already there; "Check" lists them, each opens the merge view
function ctx_dupBtn(el, groups) {
  el.querySelector('[data-ctimp="dup"]')?.remove();
  const b = document.createElement('button'); b.className = 'btn sm'; b.dataset.ctimp = 'dup'; b.textContent = tr('Check');
  b.onclick = () => ctx_dupList(groups);
  el.querySelector('[data-ctimp="close"]').before(b);
}
function ctx_dupList(groups) {
  const md = modal(`<div class="lhdr"><h3>${tr('Possible duplicates')}</h3><span class="spacer"></span><button class="iconbtn" data-ctxd="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="muted">${tr('These new contacts look like one already there. Merge them, or leave them as they are.')}</p>
    <ul class="evclist">${groups.map((g, i) => `<li class="evcrow"><span class="evcn"><b>${esc(g.fn || '?')}</b> <span class="muted">· ${esc(tr('like {0}', g.like.map(x => x.fn || '?').join(', ')))}</span></span><button class="btn sm" data-ctxdm="${i}">${tr('Merge')}</button></li>`).join('')}</ul>
    <div class="foot"><span class="spacer"></span><button class="btn" data-ctxd="close">${tr('Done')}</button></div>`);
  md.addEventListener('click', e => {
    if (e.target.closest('[data-ctxd="close"]')) { md.remove(); return; }
    const m = e.target.closest('[data-ctxdm]'); if (!m) return;
    const g = groups[+m.dataset.ctxdm]; md.remove();
    if (S.route.mod !== 'contacts') go('contacts');
    ctm_merge([g.id, ...g.like.map(x => x.id)].slice(0, CTM_MAX));
  });
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
function ctImport(bookId, kind, file) {  // 2.143.0 C (#2154): file = a .vcf shared from another app (no file picker)
  const books = (S.books || []).filter(b => ctWrite(b) && wsObjIn(b));
  const run = async bid => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = kind === 'csv' ? '.csv,.txt,.tsv,text/csv,text/plain' : '.vcf,.vcard,.zip,text/vcard,text/x-vcard,application/zip';  // 2.119.1 A (#2080)
    if (kind !== 'csv') inp.multiple = true;  // 2.146.0 E (#2457): one .vcf per contact (Outlook) or a ZIP (Google Takeout)
    inp.onchange = async () => {
      const fs = file ? [file] : [...inp.files], f = fs[0]; if (!f) return;
      // 2.87.9 (#1940): where the contacts go, in words; from an organisation's book also into an own private book
      const b = (S.books || []).find(x => x.id === bid);
      const ph = {};  // 2.306.0 C (#2889): vCard files only (a CSV has no pictures)
      const to = await importTargetConfirm({what: tr('the contacts'), ws: wsOf(b), place: b?.name || '', privOk: true,
        check: kind === 'csv' ? null : {label: tr('Import contact photos too'), hint: tr('For photos that are only linked in the file, this server fetches the pictures from the internet.'), out: ph}});
      if (!to) return;
      if (to === 'private') {
        let pb = (S.books || []).find(x => !x.org_id && x.role === 'owner');
        if (!pb) { try { pb = await api('POST', '/api/books', {name: tr('Contacts'), org_id: null}); await load(); } catch { return; } }
        bid = pb.id;
      }
      if (fs.length > 1 || /\.zip$/i.test(f.name)) ctImpRun(bid, fs, null, ph.on === false);  // 2.146.0 E (#2457): the server reads the vCards of all files
      else if (kind === 'csv' || !/\.vcf$/i.test(f.name)) ctx_csvMap(bid, f, ph.on === false); else ctImpRun(bid, f, null, ph.on === false);  // 2.119.1 A (#2080): CSV: the columns first
    };
    if (file) inp.onchange(); else inp.click();
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
    el.innerHTML = botBusy() + '<div class="ctimp-t"></div><div class="pbar"><i></i></div><button class="iconbtn" data-ctimp="close" hidden></button>';  // 2.161.2 (#2611): the bot at work (gone once it ended, app.css)
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
function ctImpRun(bid, f, mapping, noPhotos) {
  const p = ctImpPanel();
  let fi = null;  // 2.146.0 E (#2457): several files / a ZIP: how many were read, which not
  const done = async j => {
    const bad = fi?.errors?.length ? ' · ' + trn('{0} file not read', '{0} files not read', fi.errors.length) + ': ' + fi.errors.slice(0, 3).map(e => e.file).join(', ') : '';
    p.set((fi?.files > 1 ? trn('{0} file', '{0} files', fi.files) + ' · ' : '') + tr('Imported: {0} new, {1} updated', j.created, j.updated) + (j.errors ? ' · ' + trn('{0} not readable', '{0} not readable', j.errors) : '') + (j.dupes ? ' · ' + trn('{0} possible duplicate', '{0} possible duplicates', j.dupes) : '') + (j.kept_newer ? ' · ' + trn('{0} contact not overwritten, it is newer here', '{0} contacts not overwritten, they are newer here', j.kept_newer) : '') + bad, null, true);
    if (j.dupes && (j.dupe_groups || []).length) ctx_dupBtn(p.el, j.dupe_groups);  // 2.119.1 A (#2084)
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
    fi = j.files || null;
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
  x.send((() => { const fd = new FormData(); if (Array.isArray(f)) f.forEach(y => fd.append('files', y)); else fd.append('file', f); if (mapping) fd.append('mapping', JSON.stringify(mapping)); if (noPhotos) fd.append('photos', '0'); return fd; })());
}
// 2.119.1 A (#2080): a CSV file (Outlook, Google Contacts, a spreadsheet): the server reads it (delimiter, encoding) and suggests
// a field per column; here the person checks / changes them, then the rows take the vCard import's way (ctImpRun: progress, background)
const ctx_F = () => {
  const ty = (k, t) => `${tr(k === 'email' ? 'E-mail' : 'Phone')} (${tr(t)})`, ad = (t, p) => `${tr(p)} (${tr(t)})`;
  return [['', tr('Do not import')], ['fn', tr('Display name')], ['given', tr('First name')], ['middle', tr('Middle name')], ['family', tr('Last name')],
    ['prefix', tr('Name prefix')], ['suffix', tr('Name suffix')], ['nickname', tr('Nickname')], ['org', tr('Company')], ['dept', tr('Department')], ['title', tr('Job title')],
    ['email:home', ty('email', 'Home')], ['email:work', ty('email', 'Work')], ['email:other', ty('email', 'Other')],
    ['phone:cell', ty('phone', 'Mobile')], ['phone:home', ty('phone', 'Home')], ['phone:work', ty('phone', 'Work')], ['phone:fax', tr('Fax')], ['phone:other', ty('phone', 'Other')],
    ...[['home', 'Home'], ['work', 'Work'], ['other', 'Other']].flatMap(([t, n]) => [['street', 'Street'], ['code', 'Postcode'], ['city', 'City'], ['region', N_('Region')], ['country', 'Country']].map(([p, pn]) => [`adr:${t}:${p}`, ad(n, pn)])),
    ['url', tr('Website')], ['bday', tr('Birthday')], ['anniversary', tr('Anniversary')], ['note', tr('Notes')], ['groups', tr('Groups')]];
};
async function ctx_csvMap(bid, f, noPhotos) {
  let p;
  try { const fd = new FormData(); fd.append('file', f); p = await api('POST', `/api/books/${bid}/import?preview=1`, fd); } catch { return; }
  if (p.format !== 'csv') { ctImpRun(bid, f, null, noPhotos); return; }  // a vCard after all; 2.306.0 (#2889 review N20): the photo switch applies here too
  const F = ctx_F(), map = [...p.guess];
  const ex = i => p.sample.map(r => r[i]).find(Boolean) || '';
  const md = modal(`<div class="lhdr"><h3>${tr('Import a CSV file…').replace(/…$/, '')}</h3><span class="spacer"></span><button class="iconbtn" data-ctx="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div>
    <p class="muted">${esc(f.name)} · ${esc(trn('{0} contact', '{0} contacts', p.rows))} · ${tr('Which column holds what? Kalmido has guessed; please check.')}</p>
    <div class="ctxmap">${p.columns.map((c, i) => `<div class="row"><label for="ctx-c${i}">${esc(c || tr('Column {0}', i + 1))}${ex(i) ? `<small class="muted">${esc(ex(i))}</small>` : ''}</label><select id="ctx-c${i}" data-ctxcol="${i}">${F.map(([k, n]) => `<option value="${esc(k)}" ${map[i] === k ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>`).join('')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-ctx="close">${tr('Cancel')}</button><button class="btn pri" data-ctx="go">${esc(trn('Import {0} contact', 'Import {0} contacts', p.rows))}</button></div>`);
  md.classList.add('ctmodal');
  md.addEventListener('change', e => { const s = e.target.closest('[data-ctxcol]'); if (s) map[+s.dataset.ctxcol] = s.value; });
  md.addEventListener('click', e => {
    const k = e.target.closest('[data-ctx]')?.dataset.ctx; if (!k) return;
    if (k === 'close') { md.remove(); return; }
    if (!map.some(Boolean)) { toast(tr('Choose at least one column')); return; }
    md.remove(); ctImpRun(bid, f, map);
  });
}
// 2.119.1 A (#2085): the groups (CATEGORIES labels) over all contacts one sees: the count per group, rename and delete (only the
// label, the contacts stay) in the address books one may change. Each change is one undo step: the server answers the old
// labels, the undo puts them back (POST /api/contacts/bulk action restore), the redo does the change again
const CTX_MANAGE = '\u0001manage';
async function ctx_groupsModal() {
  const md = modal(`<div class="lhdr"><h3>${ic('tag', 's')} ${tr('Groups')}</h3><span class="spacer"></span><button class="iconbtn" data-ctg="close" aria-label="${esc(tr('Close'))}">${ic('x')}</button></div><div id="ctg-body"><p class="muted">${tr('Loading…')}</p></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-ctg="close">${tr('Done')}</button></div>`);
  let items = [];
  const draw = async () => {
    try { items = (await api('GET', '/api/contacts/groups')).items || []; } catch { md.remove(); return; }
    if (!md.isConnected) return;
    $('#ctg-body', md).innerHTML = items.length ? `<ul class="evclist">${items.map((g, i) => `<li class="evcrow"><span class="evcn">${esc(g.name)} <span class="muted">· ${esc(trn('{0} contact', '{0} contacts', g.count))}${g.writable < g.count ? ' · ' + esc(trn('{0} can only be read', '{0} can only be read', g.count - g.writable)) : ''}</span></span>${g.writable ? `<button class="iconbtn" data-ctgr="${i}" aria-label="${esc(tr('Rename {0}', g.name))}" title="${esc(tr('Rename…'))}">${ic('edit')}</button><button class="iconbtn" data-ctgd="${i}" aria-label="${esc(tr('Delete {0}', g.name))}" title="${esc(tr('Delete…'))}">${ic('trash')}</button>` : ''}</li>`).join('')}</ul>` : `<p class="muted">${tr('No groups yet. Groups are added in a contact or for several selected contacts.')}</p>`;
  };
  const after = async (from, to) => {
    if (CT.group && CT.group.toLowerCase() === from.toLowerCase()) CT.group = to || '';
    ctLoad(); if (CT.sel) ctOpen(CT.sel); if (md.isConnected) draw();
  };
  const run = async (g, to) => {
    const send = () => api('POST', '/api/contacts/groups', to ? {action: 'rename', name: g.name, to} : {action: 'delete', name: g.name});
    let j; try { j = await send(); } catch { return; }
    let undo = j.undo || [];
    await after(g.name, to);
    const msg = [to ? tr('Group renamed') : tr('Group deleted'), trn('{0} contact changed', '{0} contacts changed', j.changed), j.skipped ? trn('{0} in an imported address book stayed', '{0} in imported address books stayed', j.skipped) : ''].filter(Boolean).join(' · ');
    if (!j.changed) { toast(msg); return; }
    ms_hist(msg, to ? tr('Group renamed') : tr('Group deleted'),
      async () => { await bk_set({action: 'restore'}, null, undo); await after(to || g.name, g.name); },
      async () => { undo = (await send()).undo || []; await after(g.name, to); });
  };
  md.addEventListener('click', async e => {
    if (e.target.closest('[data-ctg="close"]')) { md.remove(); return; }
    const r = e.target.closest('[data-ctgr]'), d = e.target.closest('[data-ctgd]');
    if (r) {
      const g = items[+r.dataset.ctgr]; if (!g) return;
      const n = await askPrompt(tr('Rename the group'), g.name, {input: {max: 100}});
      if (n && n.trim() && n.trim() !== g.name) run(g, n.trim().replace(/,/g, ' '));
    } else if (d) {
      const g = items[+d.dataset.ctgd]; if (!g) return;
      if (!await askConfirm(tr('Delete the group “{0}”?', g.name), trn('The {0} contact stays; only the group is removed from it.', 'The {0} contacts stay; only the group is removed from them.', g.writable), {ok: tr('Delete'), danger: true})) return;
      run(g, '');
    }
  });
  draw();
}
async function ctBooksModal() {
  let users = [];
  if (collab()) users = await evPeople();
  const names = new Map(users.map(u => [u.id, u.display_name]));
  const md = modal(`<div class="lhdr"><h3>${ic('folder', 's')} ${tr('Address books')}</h3><span class="spacer"></span><button class="iconbtn" data-cb="close" aria-label="${tr('Close')}">${ic('x')}</button></div><div id="cb-body"></div>
    <div class="foot"><button class="btn" data-cb="phone">${ic('phone', 's')} ${tr('On the phone…')}</button><span class="spacer"></span><button class="btn pri" data-cb="new">${ic('plus', 's')} ${tr('New address book')}</button></div>`);
  const draw = () => {
    const bs = S.books || [];
    $('#cb-body', md).innerHTML = bs.length ? `<ul class="evclist">${bs.map(b => `<li class="evcrow" style="--cc:${cssColor(b.color) || 'var(--accent)'}"><i class="cevdot"></i><span class="evcn">${esc(b.name)} <span class="muted">· ${esc(trn('{0} contact', '{0} contacts', b.count))}${wsOn() && b.role === 'owner' ? ' · ' + esc(wsLabel(b.org_id)) : ''}${b.org_owned ? ' · ' + esc(tr('Belongs to {0}', wsLabel(b.org_id))) : ''}${b.role !== 'owner' ? (b.org_owned ? '' : ' · ' + esc(b.owner_name || '')) + ' · ' + esc(b.role === 'edit' ? tr('can edit') : tr('can view')) : b.members?.length ? ' · ' + esc(trn('shared with {0} person', 'shared with {0} people', b.members.length)) : ''}${b.imported ? ' · ' + esc(tr('imported')) : ''}</span></span>
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
        own && wsOn() && !b.org_owned && {label: tr('Workspace…'), icon: 'brief', fn: () => wsMoveMenu(m, b.org_id, async org => { try { await api('PATCH', `/api/books/${b.id}`, {org_id: org}); } catch { return; } refresh(); })},
        own && collab() && {label: tr('Share…'), icon: 'users', fn: () => ctShareModal(b, users, names, refresh)},
        ...(typeof ctf_bookItems === 'function' ? ctf_bookItems(b, m) : []),  // 2.351.0 B (#2749): into a folder of the address book
        b.can_org && {label: tr('Hand over to the organisation…'), icon: 'building', fn: () => ob_take(b, refresh)},  // 2.52.0 (#1438)
        own && b.org_owned && {label: tr('Members of the organisation'), icon: 'building', more: ob_roleItems(b, refresh)},
        own && b.org_owned && {label: tr('Make personal again…'), icon: 'home', fn: () => ob_drop(b, refresh)},
        own && famOn() && !b.imported && {label: tr('Birthdays as tasks…'), icon: 'cake', fn: () => ctBdayModal(b, refresh)},
        ctWrite(b) && {label: tr('Import a vCard file…'), icon: 'upload', fn: () => ctImport(b.id)},
        ctWrite(b) && {label: tr('Import a CSV file…'), icon: 'upload', fn: () => ctImport(b.id, 'csv')},  // 2.119.1 A (#2080)
        {label: tr('Export (vCard)'), icon: 'download', fn: () => { location.href = `/api/books/${b.id}/export.vcf`; }},
        {label: tr('Export (CSV)'), icon: 'download', fn: () => { location.href = `/api/books/${b.id}/export.csv`; }},
        !own && {label: tr('Leave this address book'), icon: 'logout', fn: async () => { try { await api('DELETE', `/api/books/${b.id}/members/${S.me.id}`); } catch { return; } refresh(); }},
        // 2.272.0 E1 (#3038): the question names the number; the book goes to the trash with its contacts (Undo, Contacts > More > Trash)
        own && {label: tr('Delete…'), icon: 'trash', cls: 'danger', fn: async () => { if (!await askConfirm(tr('Delete the address book “{0}” with all its contacts?', b.name), trn('Its {0} contact goes to the trash with it and is removed from the phones.', 'Its {0} contacts go to the trash with it and are removed from the phones.', b.count || 0), {ok: tr('Delete'), danger: true})) return; try { await api('DELETE', `/api/books/${b.id}`); } catch { return; } refresh(); toast(tr('“{0}” moved to the trash', b.name), async () => { try { await api('POST', `/api/books/${b.id}/restore`); } catch (x) { toast(x.message || ''); return; } refresh(); }); }}]);
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
// 2.351.0 B (#2749): + the agents of the book's workspace (like a list's Share dialog; the server already took them and
// refuses somebody else's personal agent): an agent sees the book only through this share, like every other share
async function ct_shareAgents() {
  try { return (await api('GET', '/api/users')).users.filter(u => u.agent && !u.disabled); } catch { return []; }
}
const ct_agentOpts = (ags, org, taken) => { const xs = ags.filter(u => (u.org_id || null) === org && !taken.some(m => m.user_id === u.id));
  return xs.length ? `<optgroup label="${esc(tr('Agents'))}">${xs.map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join('')}</optgroup>` : ''; };
async function ctShareModal(b, users, names, done) {
  const bOrg = () => b.imported || b.src_id ? null : b.org_id || null;  // 2.46.4 (#1737): a book mirrored from a connected account is always private
  const ags = await ct_shareAgents();
  for (const u of ags) names.set(u.id, u.display_name);
  const opts = () => shWsOptions(users, bOrg(), b.members || []) + ct_agentOpts(ags, bOrg(), b.members || []);
  const md = modal(`<h3>${tr('Share {0}', esc(b.name))}</h3><div class="shws"></div><div id="cbs-list"></div>
    <div class="row"><label for="cbs-user">${tr('Person or agent')}</label><select id="cbs-user" data-sheet-av>${opts()}</select>
      <select id="cbs-role" aria-label="${esc(tr('Role'))}"><option value="view">${tr('can view')}</option><option value="edit">${tr('can edit')}</option></select><button class="btn sm pri" data-cbs="add">${tr('Share')}</button></div>
    <div class="shint">${tr('Contacts are personal data: share an address book only with people who may see all of it.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-cbs="close">${tr('Done')}</button></div>`);
  const draw = () => { $('#cbs-list', md).innerHTML = (b.members || []).length ? `<ul class="evclist">${b.members.map(m => `<li class="evcrow">${av(m.user_id, names.get(m.user_id) || '')}<span class="evcn">${esc(names.get(m.user_id) || '?')}${ags.some(u => u.id === m.user_id) && typeof agentBadge === 'function' ? agentBadge() : ''} <span class="muted">· ${esc(m.role === 'edit' ? tr('can edit') : tr('can view'))}</span></span><button class="iconbtn" data-cbsrm="${m.user_id}" aria-label="${esc(tr('Stop sharing with {0}', names.get(m.user_id) || ''))}">${ic('x', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('Not shared yet.')}</p>`; };
  const wsDraw = () => {  // 2.46.4 (#1737)
    shWsFill($('.shws', md), bOrg(), b.imported || b.src_id ? null : a => wsMoveMenu(a, b.org_id, async org => {
      try { await api('PATCH', `/api/books/${b.id}`, {org_id: org}); } catch { return; }
      b.org_id = org; wsDraw(); $('#cbs-user', md).innerHTML = opts(); shWsPick($('#cbs-user', md)); done();
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
      $('#cbs-user', md).innerHTML = opts(); shWsPick($('#cbs-user', md));  // 2.351.0 B (#2749): the one just added leaves the select
      draw(); done();
    }
  });
}
function ctBdayModal(b, done) {  // module Family: the birthdays + anniversaries of this book become yearly tasks of a list
  const ls = S.lists.filter(l => !l.archived && canEditList(l.id));
  const md = modal(`<h3>${ic('cake', 's')} ${tr('Birthdays as tasks')}</h3>
    <p class="muted">${tr('Birthdays and anniversaries of the contacts in {0} become yearly tasks with the age and a reminder a week before.', esc(b.name))}</p>
    <div class="row"><label for="cbd-list">${tr('Project')}</label><select id="cbd-list"><option value="">${tr('Off')}</option>${ls.map(l => `<option value="${l.id}" ${l.id === b.birthdays_list_id ? 'selected' : ''}>${esc(lname(l))}</option>`).join('')}</select></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-cbd="close">${tr('Cancel')}</button><button class="btn pri" data-cbd="save">${tr('Save')}</button></div>`);
  md.addEventListener('click', async e => {
    const k = e.target.closest('[data-cbd]')?.dataset.cbd; if (!k) return;
    if (k === 'close') { md.remove(); return; }
    try { await api('PATCH', `/api/books/${b.id}`, {birthdays_list_id: $('#cbd-list', md).value ? +$('#cbd-list', md).value : null}); } catch { return; }
    md.remove(); done(); toast(tr('Saved'));
  });
}

// 2.53.0 (#1410): the task panel part ("People and dates", linking a contact) lives in ctlinks.js (loaded at start)

// 2.52.0 (#1438): address books an organisation owns. Its admins hand a book of its workspace over (ob_take) and make it
// personal again (ob_drop); the members read or change it as its role says (ob_roleItems). Each is one undo step.
const OB_ROLES = () => [['view', tr('They can view')], ['edit', tr('They can edit')], ['none', tr('Only admins and people it is shared with')]];
async function ob_take(b, done) {
  if (!await askConfirm(tr('Hand “{0}” over to {1}?', b.name, wsLabel(b.org_id)),
    tr('The address book then belongs to the organisation: its admins manage it, its members can view it, and it stays when you leave.'), {ok: tr('Hand over')})) return;
  const go = role => async () => { await api('POST', `/api/books/${b.id}/org`, {org_role: role}); done(); };  // the step is recorded before the reload
  const back = async () => { await api('DELETE', `/api/books/${b.id}/org`); done(); };
  try { await go('view')(); } catch { return; }
  offerUndo(tr('Handed over to {0}', wsLabel(b.org_id)), histAdd({label: tr('Address book handed over'), undo: back, redo: go('view')}));
}
async function ob_drop(b, done) {
  if (!await askConfirm(tr('Make “{0}” your personal address book again?', b.name),
    tr('The members of the organisation then only see it where it is shared with them.'), {ok: tr('Make personal')})) return;
  const back = async () => { await api('POST', `/api/books/${b.id}/org`, {}); done(); };  // keeps the members' role it had
  const go = async () => { await api('DELETE', `/api/books/${b.id}/org`); done(); };
  try { await go(); } catch { return; }
  offerUndo(tr('Personal address book again'), histAdd({label: tr('Address book made personal'), undo: back, redo: go}));
}
function ob_roleItems(b, done) {
  const put = v => async () => { await api('PATCH', `/api/books/${b.id}/org`, {org_role: v}); done(); };
  return OB_ROLES().map(([k, n]) => ({label: n, on: (b.org_role || 'view') === k, fn: async () => {
    const from = b.org_role || 'view'; if (from === k) return;
    try { await put(k)(); } catch { return; }
    offerUndo(tr('Saved'), histAdd({label: tr('Changed setting: {0}', tr('Members of the organisation')), undo: put(from), redo: put(k)}));
  }}));
}
// 2.66.0 A (#1835): merging duplicate contacts (the selection bar's Merge, 2 to 10 ticked): ms_merge (multisel.js) with the
// fields of the contacts, the overview from the server (dry run), then the merge. One undo step (toast, Ctrl+Z; redo = the
// same merge again) and on the target's card the history with Undo (30 days)
const CTM_MAX = 10;
const ctm_F = () => [['fn', tr('Name')], ['given', tr('First name')], ['family', tr('Last name')], ['middle', tr('Middle name')],
  ['prefix', tr('Name prefix')], ['suffix', tr('Name suffix')], ['nickname', tr('Nickname')], ['kind', tr('Kind')], ['org', tr('Company')],
  ['dept', tr('Department')], ['title', tr('Job title')], ['bday', tr('Birthday')], ['anniversary', tr('Anniversary')], ['photo', tr('Photo')],
  ['note', tr('Note')]];
const ctm_L = () => [['phones', tr('Phone')], ['emails', tr('E-mail')], ['addresses', tr('Addresses')], ['urls', tr('Website')], ['groups', tr('Groups')]];
const ctm_name = c => c.fn || c.org || '?';
const ctm_adr = a => [a.street, [a.code, a.city].filter(Boolean).join(' '), a.region, a.country].filter(Boolean).join(', ');
async function ctm_merge(ids) {
  if (ids.length < 2) { toast(tr('Choose at least two contacts')); return; }
  if (ids.length > CTM_MAX) { toast(tr('At most {0} contacts at once', CTM_MAX)); return; }
  let recs; try { recs = await Promise.all(ids.map(i => api('GET', `/api/contacts/${i}`))); } catch { return; }
  const photo = {}; for (const c of recs) if (c.photo && !(c.photo in photo)) photo[c.photo] = ctm_name(c);
  const val = (c, k) => k === 'photo' ? (c.photo ? tr('Photo of {0}', photo[c.photo]) : '') : k === 'kind' ? (c.kind === 'org' ? tr('Company') : tr('Person'))
    : k === 'bday' || k === 'anniversary' ? (c[k] ? ctDate(c[k]) : '') : k === 'note' ? ((c.note || '').length > 160 ? c.note.slice(0, 159) + '…' : c.note || '') : c[k] || '';
  const lv = (c, k) => (c[k] || []).map(x => typeof x === 'string' ? x : k === 'addresses' ? ctm_adr(x) : x.value || '');
  const body = (target, pick, dry) => ({target, ids: recs.map(c => c.id), pick, ...(dry ? {dry: true} : {})});
  const book = c => ctBook(c.book_id)?.name || '';
  ms_merge({title: trn('Merge {0} contact', 'Merge {0} contacts', recs.length),
    recs: recs.map(c => ({id: c.id, label: ctm_name(c), sub: [c.org !== c.fn ? c.org : '', lv(c, 'emails')[0] || lv(c, 'phones')[0], (S.books || []).length > 1 ? book(c) : ''].filter(Boolean).join(' · ')})),
    fields: ctm_F().map(([k, label]) => ({k, label, vals: Object.fromEntries(recs.map(c => [c.id, val(c, k)]))})),
    lists: ctm_L().map(([k, label]) => ({k, label, vals: Object.fromEntries(recs.map(c => [c.id, lv(c, k)]))})),
    preview: (target, pick) => rawFetch('POST', '/api/contacts/merge', body(target, pick, true)),
    run: async (target, pick) => {
      const j = await rawFetch('POST', '/api/contacts/merge', body(target, pick));
      let run = j.run_id;
      const show = async () => { await load().catch(() => {}); ctLoad(); if (isMobile()) go('contacts/' + target); else ctOpen(target); };
      bk_end(); show();
      ms_hist(trn('{0} contact merged', '{0} contacts merged', recs.length), tr('Contacts merged'),
        async () => { await api('POST', `/api/contacts/merges/${run}/undo`); await show(); },
        async () => { run = (await api('POST', '/api/contacts/merge', body(target, pick))).run_id; await show(); });
      return true;
    }});
}
function ctm_histHtml(c) {
  return `<div class="ctsec ctmsec"><h4>${tr('History')}</h4><ul class="ctlinks">${c.merges.map(m => `<li class="ctmrow"><span>${esc(tr('Merged with {0}', (m.summary?.merged || []).map(x => x.fn).join(', ') || '?'))}<small class="muted"> · ${esc([fmtWhen(m.at), m.by_name, m.summary?.proposal?.agent && tr('from a proposal by {0}', m.summary.proposal.agent)].filter(Boolean).join(' · '))}${m.undone_at ? ' · ' + esc(tr('undone')) : ''}</small></span>${m.undo === '' ? `<button type="button" class="btn sm" data-ctmundo="${m.id}">${ic('undo', 's')} ${tr('Undo')}</button>` : ''}</li>`).join('')}</ul></div>`;
}
async function ctm_undoCard(rid, el) {
  el.disabled = true;
  let j; try { j = await api('POST', `/api/contacts/merges/${rid}/undo`); } catch { el.disabled = false; return; }
  toast(j.note || tr('Merge undone'));
  await load().catch(() => {}); ctLoad();
  if (CT.sel) ctOpen(CT.sel);
}
