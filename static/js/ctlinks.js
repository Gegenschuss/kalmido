/* Kalmido web client: the contacts in the task panel (2.53.0, #1410): "People and dates" of a task and linking a contact.
   Loaded at start; the contacts view, the editor and the address books (contacts.js) are loaded on demand (lazyload.js).
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const ctOn = () => feat('contacts');
const CT_LINK = [['waiting', N_('Waiting on')], ['responsible', N_('Responsible')], ['about', N_('About')]];
function ctAv(c, cls = 'avatar ctav') {
  return c.photo && typeof c.photo === 'string' && c.photo.startsWith('data:image/') ? `<span class="${cls} pic"><img src="${esc(c.photo)}" alt="" loading="lazy" decoding="async"></span>`
    : `<span class="${cls}">${esc(initials(c.fn || c.org || '?'))}</span>`;
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
