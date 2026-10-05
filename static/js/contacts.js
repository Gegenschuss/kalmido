/* Kalmido web client: Contacts (module "contacts"): the contacts view (search, groups, address books), the editor, the
   contact card, links between contacts and tasks, import / export.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.21.0 (#658): the contacts live in Kalmido's own address books (S.books from /api/state) and sync with the phone over
// CardDAV. The view loads its page of contacts (GET /api/contacts, never part of /api/state: contacts are personal data
// and can be many); a contact opens as a card (desktop: next to the list, phone: the whole view), "Edit" opens the editor.
const CT = {q: '', group: '', book: '', items: null, total: 0, groups: [], sel: null, card: null, loading: false, seq: 0};
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
async function ctLoad() {
  const seq = ++CT.seq;
  CT.loading = true;
  const qs = new URLSearchParams({q: CT.q, limit: '500'});
  if (CT.group) qs.set('group', CT.group);
  if (CT.book) qs.set('book_id', CT.book);
  try {
    const j = await api('GET', '/api/contacts?' + qs);
    if (seq !== CT.seq) return;
    CT.items = j.items; CT.total = j.total; CT.groups = j.groups || [];
  } catch { if (seq === CT.seq) CT.items = CT.items || []; }
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
function ctDraw() { if (S.route.mod === 'contacts') { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, viewContacts())); } }
function viewContacts() {
  if (CT.items === null && !CT.loading) setTimeout(ctLoad, 0);
  const books = S.books || [];
  const mob = isMobile(), showCard = CT.card && (!mob || CT.sel);
  const bar = `<div class="ctbar"><div class="ctsearch">${ic('search', 's')}<input id="ct-q" type="search" value="${esc(CT.q)}" placeholder="${esc(tr('Search contacts'))}" aria-label="${esc(tr('Search contacts'))}" autocomplete="off" enterkeyhint="search"></div>
    ${CT.groups.length ? `<select id="ct-group" aria-label="${esc(tr('Group'))}"><option value="">${tr('All groups')}</option>${CT.groups.map(g => `<option value="${esc(g)}" ${g === CT.group ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select>` : ''}
    ${books.length > 1 ? `<select id="ct-book" aria-label="${esc(tr('Address book'))}"><option value="">${tr('All address books')}</option>${books.map(b => `<option value="${b.id}" ${String(b.id) === String(CT.book) ? 'selected' : ''}>${esc(b.name)}</option>`).join('')}</select>` : ''}
    <span class="spacer"></span><button class="btn sm pri" data-ct="new">${ic('plus', 's')}<span class="cdl">${tr('New contact')}</span></button>
    <button class="iconbtn" data-ct="menu" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button></div>`;
  const list = CT.items === null ? `<div class="muted ctempty">${tr('Loading…')}</div>` : !CT.items.length
    ? `<div class="empty">${ic('users')}${CT.q || CT.group ? tr('No contact matches.') : tr('No contacts yet. Add one, import a vCard file, or connect the phone.')}</div>`
    : `<ul class="ctlist" role="list" aria-label="${esc(tr('Contacts'))}">${CT.items.map(c => `<li><button type="button" class="ctrow ${c.id === CT.sel ? 'on' : ''}" data-ctopen="${c.id}" aria-current="${c.id === CT.sel}">${ctAv(c)}<span class="ctn"><b>${esc(c.fn || c.org || '?')}</b><small class="muted">${esc([c.org !== c.fn ? c.org : '', c.email || c.phone].filter(Boolean).join(' · '))}</small></span>${(books.length > 1 && ctBook(c.book_id)) ? `<i class="cevdot" style="--cc:${cssColor(ctBook(c.book_id).color) || 'var(--accent)'}" title="${esc(ctBook(c.book_id).name)}"></i>` : ''}</button></li>`).join('')}</ul>
      ${CT.total > CT.items.length ? `<div class="muted ctmore">${tr('{0} of {1} shown: search to narrow it down', CT.items.length, CT.total)}</div>` : ''}`;
  return `<div class="ctview ${showCard ? 'withcard' : ''}"><h2 class="sr">${tr('Contacts')}</h2>${mob && showCard ? '' : bar}<div class="ctcols">${mob && showCard ? '' : `<div class="ctlistw">${list}</div>`}${showCard ? ctCardHtml(CT.card) : mob ? '' : `<div class="ctcard ctnone muted">${ic('user')}${tr('Choose a contact')}</div>`}</div></div>`;
}
function ctCardHtml(c) {
  const b = ctBook(c.book_id), w = ctWrite(b);
  const it = (k, icon, href) => (c[k] || []).map(x => `<div class="ctf">${ic(icon, 's')}<span class="ctfl muted">${esc(ctTypeWord(k, x))}</span>${href(x)}</div>`).join('');
  const adr = (c.addresses || []).map(a => { const t = [a.street, [a.code, a.city].filter(Boolean).join(' '), a.region, a.country].filter(Boolean).join(', ');
    return `<div class="ctf">${ic('mappin', 's')}<span class="ctfl muted">${esc(ctTypeWord('addresses', a))}</span><span>${esc(t)}</span></div>`; }).join('');
  const kinds = Object.fromEntries(CT_LINK);
  return `<article class="ctcard" aria-labelledby="ct-h">
    <div class="cthead">${isMobile() ? `<button class="iconbtn" data-ct="back" aria-label="${esc(tr('Back'))}">${ic('back')}</button>` : ''}${ctAv(c, 'avatar ctav big')}<div class="cthn"><h3 id="ct-h">${esc(c.fn || c.org || '?')}</h3>${[c.title, c.org !== c.fn ? c.org : '', c.dept].filter(Boolean).length ? `<div class="muted">${esc([c.title, c.org !== c.fn ? c.org : '', c.dept].filter(Boolean).join(' · '))}</div>` : ''}</div>
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
  const o = e.target.closest('[data-ctopen]');
  if (o) { e.preventDefault(); if (isMobile()) go('contacts/' + o.dataset.ctopen); else ctOpen(+o.dataset.ctopen); return; }
  const tk = e.target.closest('[data-cttask]');
  if (tk) { e.preventDefault(); const id = +tk.dataset.cttask; if (taskById(id)) openDetail(id); else go('t/' + id); return; }
  const gp = e.target.closest('[data-ctgroup]');
  if (gp) { CT.group = gp.dataset.ctgroup; CT.sel = null; CT.card = null; if (isMobile()) go('contacts'); ctLoad(); return; }
  const b = e.target.closest('#view [data-ct]'); if (!b) return;
  const k = b.dataset.ct;
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

// ---- the editor
async function ctEditor(c) {
  const books = (S.books || []).filter(ctWrite);
  if (!books.length) { try { const bk = await api('POST', '/api/books', {name: tr('Contacts')}); await load(); books.push(bk); } catch { return; } }
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
  const books = (S.books || []).filter(ctWrite);
  const run = async bid => {
    const inp = document.createElement('input');
    inp.type = 'file'; inp.accept = '.vcf,text/vcard,text/x-vcard';
    inp.onchange = async () => {
      const f = inp.files[0]; if (!f) return;
      const fd = new FormData(); fd.append('file', f);
      try {
        const r = await fetch(`/api/books/${bid}/import`, {method: 'POST', body: fd, headers: {'X-Requested-With': 'kalmido'}, credentials: 'same-origin'});
        const j = await r.json();
        if (!r.ok) { toast(j.error || tr('Import failed')); return; }
        toast(tr('Imported: {0} new, {1} updated', j.created, j.updated) + (j.errors ? ' · ' + trn('{0} not readable', '{0} not readable', j.errors) : ''), null, 6000);
        await load().catch(() => {}); ctLoad();
      } catch { toast(tr('Import failed')); }
    };
    inp.click();
  };
  if (bookId) { run(bookId); return; }
  if (books.length === 1) { run(books[0].id); return; }
  if (!books.length) { api('POST', '/api/books', {name: tr('Contacts')}).then(async b => { await load(); run(b.id); }).catch(() => {}); return; }
  menu($('#view [data-ct="menu"]') || $('#view'), books.map(b => ({label: tr('Into {0}', b.name), icon: 'folder', fn: () => run(b.id)})));
}
async function ctBooksModal() {
  let users = [];
  if (collab()) users = await evPeople();
  const names = new Map(users.map(u => [u.id, u.display_name]));
  const md = modal(`<div class="lhdr"><h3>${ic('folder', 's')} ${tr('Address books')}</h3><span class="spacer"></span><button class="iconbtn" data-cb="close" aria-label="${tr('Close')}">${ic('x')}</button></div><div id="cb-body"></div>
    <div class="foot"><button class="btn" data-cb="phone">${ic('phone', 's')} ${tr('On the phone…')}</button><span class="spacer"></span><button class="btn pri" data-cb="new">${ic('plus', 's')} ${tr('New address book')}</button></div>`);
  const draw = () => {
    const bs = S.books || [];
    $('#cb-body', md).innerHTML = bs.length ? `<ul class="evclist">${bs.map(b => `<li class="evcrow" style="--cc:${cssColor(b.color) || 'var(--accent)'}"><i class="cevdot"></i><span class="evcn">${esc(b.name)} <span class="muted">· ${esc(trn('{0} contact', '{0} contacts', b.count))}${b.role !== 'owner' ? ' · ' + esc(b.owner_name || '') + ' · ' + esc(b.role === 'edit' ? tr('can edit') : tr('can view')) : b.members?.length ? ' · ' + esc(trn('shared with {0} person', 'shared with {0} people', b.members.length)) : ''}${b.imported ? ' · ' + esc(tr('imported')) : ''}</span></span>
      <button class="iconbtn" data-cbmenu="${b.id}" aria-haspopup="menu" aria-label="${esc(tr('More for {0}', b.name))}" title="${esc(tr('More'))}">${ic('dots')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('No address book yet. A new contact creates one.')}</p>`;
  };
  draw();
  const refresh = async () => { await load().catch(() => {}); draw(); ctLoad(); };
  md.addEventListener('click', async e => {
    const m = e.target.closest('[data-cbmenu]');
    if (m) {
      const b = ctBook(+m.dataset.cbmenu); if (!b) return;
      const own = b.role === 'owner';
      menu(m, [own && {label: tr('Rename…'), icon: 'edit', fn: async () => { const n = await askPrompt(tr('Rename the address book'), b.name, {input: {max: 100}}); if (n && n.trim()) { try { await api('PATCH', `/api/books/${b.id}`, {name: n.trim()}); } catch { return; } refresh(); } }},
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
      const n = await askPrompt(tr('New address book'), '', {input: {max: 100, placeholder: tr('Name')}, ok: tr('Create')});
      if (!n || !n.trim()) return;
      try { await api('POST', '/api/books', {name: n.trim()}); } catch { return; }
      refresh();
    }
  });
}
function ctShareModal(b, users, names, done) {
  const md = modal(`<h3>${tr('Share {0}', esc(b.name))}</h3><div id="cbs-list"></div>
    <div class="row"><label for="cbs-user">${tr('Person')}</label><select id="cbs-user" data-sheet-av>${users.filter(u => !(b.members || []).some(m => m.user_id === u.id)).map(u => `<option value="${u.id}">${esc(u.display_name)}</option>`).join('')}</select>
      <select id="cbs-role" aria-label="${esc(tr('Role'))}"><option value="view">${tr('can view')}</option><option value="edit">${tr('can edit')}</option></select><button class="btn sm pri" data-cbs="add">${tr('Share')}</button></div>
    <div class="shint">${tr('Contacts are personal data: share an address book only with people who may see all of it.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-cbs="close">${tr('Done')}</button></div>`);
  const draw = () => { $('#cbs-list', md).innerHTML = (b.members || []).length ? `<ul class="evclist">${b.members.map(m => `<li class="evcrow">${av(m.user_id, names.get(m.user_id) || '')}<span class="evcn">${esc(names.get(m.user_id) || '?')} <span class="muted">· ${esc(m.role === 'edit' ? tr('can edit') : tr('can view'))}</span></span><button class="iconbtn" data-cbsrm="${m.user_id}" aria-label="${esc(tr('Stop sharing with {0}', names.get(m.user_id) || ''))}">${ic('x', 's')}</button></li>`).join('')}</ul>` : `<p class="muted">${tr('Not shared yet.')}</p>`; };
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
