/* Kalmido web client: Office > Clients in the layout of the contacts (2.47.3, #1734): the list on the left (search, archived,
   the selection mode of #1733), the client's card on the right (phone: the list, then the card). Clients and contacts
   stay apart: the heading "Office > Clients", a "Client" tag and the briefcase on every card (a contact: "Contact" and
   the person), the card shows rate, budget, contact persons, billing details and open invoices.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

const MSC = {items: null, loading: false, seq: 0, q: '', arch: false, pick: null, last: null, inv: null, invLoading: false};
async function ms_clLoad() {
  const seq = ++MSC.seq;
  MSC.loading = true;
  try { const j = await api('GET', '/api/clients?archived=1'); if (seq === MSC.seq) MSC.items = (j.clients || []).filter(ms_inWs); }
  catch { if (seq === MSC.seq) MSC.items = MSC.items || []; }
  MSC.loading = false;
  if (seq === MSC.seq) ms_clDraw();
}
// open invoices per client (office on): the organisation's invoices, loaded once per visit of the page
async function ms_clInvLoad() {
  MSC.invLoading = true;
  try { MSC.inv = (await rawFetch('GET', '/api/office/docs?kind=invoice')).docs || []; } catch { MSC.inv = []; }  // quiet: without an office (400) no section
  MSC.invLoading = false;
  ms_clDraw();
}
// 2.119.1 B (#2086): an address opens the map app on a tap (Apple devices: Apple Maps, else Google Maps); nothing is
// embedded or fetched before the tap (here: the contacts module loads on demand, the client card uses it too)
function ctk_mapLink(t) {
  if (!t) return '';
  const q = encodeURIComponent(t), apple = /iPad|iPhone|iPod|Macintosh/.test(navigator.userAgent);
  const url = apple ? `https://maps.apple.com/?q=${q}` : `https://www.google.com/maps/search/?api=1&query=${q}`;
  return `<a class="ctmap" href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="${esc(tr('Show on the map'))}">${esc(t)}</a>`;
}
// 2.93.0 A (#1927): the client's documents made from templates (office/doctpl.py; admins of the office only, else no section)
function ms_clGdHtml(c) {
  if (typeof officeOn !== 'function' || !officeOn()) return '';
  if (MSC.gd?.id !== c.id) { if (!MSC.gdLoading) setTimeout(() => ms_clGdLoad(c.id), 0); return ''; }
  const ds = MSC.gd.docs; if (!ds) return '';
  const st = {draft: tr('Draft'), final: tr('Finished'), signed: tr('Signed'), declined: tr('Declined')};
  return `<div class="ctsec"><h4>${tr('Documents')}</h4>${ds.length ? `<ul class="ctlinks">${ds.map(x => `<li><a class="linkbtn" href="#office/gendocs/${x.id}">${ic('file', 's')} ${esc(x.title || x.kind_label)}</a><span class="muted"> · ${esc([x.list_name, st[x.status] || x.status].filter(Boolean).join(' · '))}</span></li>`).join('')}</ul>` : `<p class="muted">${tr('No documents yet.')}</p>`}<a class="btn sm" href="#office/gendocs">${ic('plus', 's')} ${tr('New document')}</a></div>`;
}
async function ms_clGdLoad(id) {
  MSC.gdLoading = true;
  try { MSC.gd = {id, docs: (await rawFetch('GET', `/api/office/gen-docs?client_id=${id}&brief=1`)).docs || []}; } catch { MSC.gd = {id, docs: null}; }  // quiet: members (403) see no section
  MSC.gdLoading = false;
  ms_clDraw();
}
// 2.153.0 (#2028): the client's letters (office/letters.py; admins of the office only, else no section)
function ms_clLtHtml(c) {
  if (typeof officeOn !== 'function' || !officeOn()) return '';
  if (MSC.lt?.id !== c.id) { if (!MSC.ltLoading) setTimeout(() => ms_clLtLoad(c.id), 0); return ''; }
  const ls = MSC.lt.letters; if (!ls) return '';
  const st = {draft: tr('Draft'), sent: tr('Sent'), delivered: tr('Delivered')};
  return `<div class="ctsec"><h4>${tr('Letters')}</h4>${ls.length ? `<ul class="ctlinks">${ls.slice(0, 20).map(x => `<li><a class="linkbtn" href="#office/letters/${x.id}">${ic('mail', 's')} ${esc(x.subject || x.rcpt_name || tr('Letter'))}</a><span class="muted"> · ${esc([fmtDateLoc(x.letter_date), st[x.status] || x.status].filter(Boolean).join(' · '))}</span></li>`).join('')}</ul>` : `<p class="muted">${tr('No letters yet.')}</p>`}</div>`;
}
async function ms_clLtLoad(id) {
  MSC.ltLoading = true;
  try { MSC.lt = {id, letters: (await rawFetch('GET', `/api/office/letters?client_id=${id}&brief=1`)).letters || []}; } catch { MSC.lt = {id, letters: null}; }  // quiet: members (403) see no section
  MSC.ltLoading = false;
  ms_clDraw();
}
function ms_clDraw() { if (S.route.mod === 'clients') { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('clients', viewClients()))); } }
const ms_clDirty = () => { MSC.items = null; MSC.inv = null; };
const ms_clShown = () => (MSC.items || []).filter(c => (MSC.arch || !c.archived) && (!MSC.q.trim() || [c.name, c.name_extra, c.display_name, c.label, c.contact, c.email, c.phone, c.note, c.billing?.customer_no]
  .some(v => (v || '').toLowerCase().includes(MSC.q.trim().toLowerCase()))) && dsb_clPass(c));  // 2.154.0 C (#2192): + the data protection filter
const ms_clAv = (c, big) => `<span class="avatar ctav mscav ${big ? 'big' : ''}" style="${cssColor(c.color) ? '--cc:' + cssColor(c.color) : ''}" aria-hidden="true">${c.icon ? esc(c.icon) : ic('brief', big ? '' : 's')}</span>`;
const ms_tag = (kind) => kind === 'client' ? `<span class="mstag mstag-cl">${ic('brief', 's')}${tr('Client')}</span>` : `<span class="mstag">${ic('user', 's')}${tr('Contact')}</span>`;

// 2.47.3 (#1360): the page follows the workspace of the sidebar like the office (Private = the private clients, an
// organisation = its clients, All = every client one sees)
const ms_inWs = c => { const ws = typeof wsCur === 'function' ? wsCur() : 'all'; return ws === 'all' || (ws === 'private' ? c.org_id == null : 'org:' + c.org_id === ws); };
// 2.122.3 A (#2335): the way from a list of the office to its section of Settings > Import legacy data (#office/import/<area>):
// an empty list says "Already have a list? Import from Excel", a filled one ends with a quiet "Import…" (office admins only;
// lives here because the clients view draws it too without the office module loaded; the import page checks again)
function oim_link(area, empty, csv) {
  if (typeof officeOn !== 'function' || !officeOn() || (S.route.mod === 'office' && typeof ofcAdmin === 'function' && !ofcAdmin())) return '';
  const t = empty ? (csv ? tr('Already have a list? Import from CSV') : tr('Already have a list? Import from Excel')) : tr('Import…');
  return `<p class="oimlink ${empty ? 'e' : ''}"><a href="#office/import/${area}" data-oim-go="${area}">${empty ? ic('upload', 's') + ' ' : ''}${esc(t)}</a></p>`;
}
function ms_clView() {
  if (MSC.ws !== undefined && MSC.ws !== (typeof wsCur === 'function' ? wsCur() : 'all')) ms_clDirty();
  MSC.ws = typeof wsCur === 'function' ? wsCur() : 'all';
  if (S.route.client === 'mailhub' && typeof hbm_hubView === 'function') return hbm_hubView();  // 2.84.0 A (#1198)
  if (MSC.items === null && !MSC.loading) setTimeout(ms_clLoad, 0);
  const id = S.route.client || null, mob = isMobile();
  if (id && (!CLV.data || CLV.id !== id) && !CLV.loading) setTimeout(clLoad, 0);
  if (id && MSC.inv === null && !MSC.invLoading && typeof officeOn === 'function' && officeOn()) setTimeout(ms_clInvLoad, 0);
  const d = id && CLV.data && CLV.id === id ? CLV.data : null;
  const card = !id ? (mob ? '' : `<div class="ctcard ctnone muted">${ic('brief')}${tr('Choose a client')}</div>`)
    : !d ? `<div class="ctcard ctnone muted">${tr('Loading…')}</div>`
    : d.error ? `<div class="ctcard ctnone muted">${ic('brief')}${tr('This client does not exist or you cannot see it.')}${mob ? `<a class="btn" href="#clients">${tr('All clients')}</a>` : ''}</div>` : ms_clCard(d);
  const head = '';  // 2.87.9 (#1917): no "Office › Clients" heading (it looked like a way back); the office menu shows the place, the path only on a client
  const bar = `<div class="ctbar"><div class="ctsearch">${ic('search', 's')}<input id="mscl-q" type="search" value="${esc(MSC.q)}" placeholder="${esc(tr('Search clients'))}" aria-label="${esc(tr('Search clients'))}" autocomplete="off" enterkeyhint="search"></div>
    <label class="chkl"><input type="checkbox" id="mscl-arch" ${MSC.arch ? 'checked' : ''}> ${tr('Archived')}</label>${dsb_clFilter()}<span class="spacer"></span>${typeof hbm_hubBtn === 'function' ? hbm_hubBtn() : ''}
    ${(MSC.items || []).length ? `<button class="iconbtn ${MSC.pick ? 'on' : ''}" data-mscl="pick" aria-pressed="${!!MSC.pick}" aria-label="${esc(tr(MSC.pick ? 'End selection' : 'Select'))}" title="${esc(tr(MSC.pick ? 'End selection' : 'Select'))}">${ic('select')}</button>` : ''}
    <button class="btn sm pri" data-act="client-new">${ic('plus', 's')}<span class="cdl">${tr('New client')}</span></button></div>`;
  const items = MSC.items === null ? null : ms_clShown();
  const list = items === null ? `<div class="muted ctempty">${tr('Loading…')}</div>`
    : !MSC.items.length ? `<div class="empty nempty eact msclempty">${ic('brief')}<span>${tr('Clients are everyone you write quotations and invoices for: companies or private people.')}</span><button class="btn pri" data-act="client-new">${ic('plus', 's')} ${tr('New client')}</button>${feat('contacts') ? `<a class="btn" href="#contacts">${ic('users', 's')} ${tr('Contacts')}</a>` : ''}${oim_link('master', true)}</div>`
    : !items.length ? `<div class="empty">${ic('brief')}${tr('No client matches.')}</div>`
    : `<ul class="ctlist" role="list" aria-label="${esc(tr('Clients'))}">${items.map(c => `<li><button type="button" class="ctrow ${c.id === id ? 'on' : ''} ${MSC.pick?.has(c.id) ? 'picked' : ''} ${c.archived ? 'msarch' : ''}" data-clopen="${c.id}" ${MSC.pick ? `aria-pressed="${MSC.pick.has(c.id)}"` : `aria-current="${c.id === id}"`}>${MSC.pick ? `<span class="ctchk ${MSC.pick.has(c.id) ? 'on' : ''}" aria-hidden="true">${MSC.pick.has(c.id) ? ic('check', 's') : ''}</span>` : ''}${ms_clAv(c)}<span class="ctn"><b>${esc(cdn_label(c))}</b><small class="muted">${esc([cdn_label(c) !== c.name ? c.name : '', c.archived ? tr('archived') : '', c.contact, c.email].filter(Boolean).join(' · '))}</small></span>${c.budget && c.budget.level !== 'none' ? `<i class="msbud lv-${c.budget.level}" title="${esc(tr(BUDGET_TXT[c.budget.level]))}"></i>` : ''}</button></li>`).join('')}</ul>`;
  return `<div class="ctview msclients ${id ? 'withcard' : ''} ${MSC.pick ? 'ctpicking' : ''}">${mob && id ? '' : head}${MSC.pick && !(mob && id) ? ms_clBar() : ''}${mob && id ? '' : bar}<div class="ctcols">${mob && id ? '' : `<div class="ctlistw">${list}${MSC.items?.length && !MSC.pick ? oim_link('master') : ''}</div>`}${card}</div></div>`;
}
function ms_clCard(c) {
  const b = c.billing || {}, cur = S.settings.time_currency || '€';
  const ii = k => typeof ux_info === 'function' ? ux_info(k) : '';  // 2.47.3 (D, #1382): the (i) explanations of the office
  const f = (icon, label, val, k) => val ? `<div class="ctf">${ic(icon, 's')}<span class="ctfl muted">${esc(label)}</span><span>${val}</span></div>${k ? ii(k) : ''}` : '';
  const adr = cdn_addrLine(c);  // 2.97.0 B (#1951): the fixed fields only (with the extra line)
  const bud = [c.budget_h ? `${fmtNum(c.budget_h, 1)} h` : '', c.budget_amount ? `${fmtNum(c.budget_amount, 2)} ${cur}` : ''].filter(Boolean).join(' · ');
  const inv = (MSC.inv || []).filter(x => x.client_id === c.id && x.open > 0 && !['draft', 'cancelled'].includes(x.status));
  const ks = (c.contacts || []).filter(k => k.name);
  return `<article class="ctcard msclcard" aria-labelledby="mscl-h">
    <div class="cthead">${isMobile() ? `<button class="iconbtn" data-mscl="back" aria-label="${esc(tr('Back'))}">${ic('back')}</button>` : ''}${ms_clAv(c, true)}<div class="cthn"><h3 id="mscl-h">${esc(cdn_label(c))}</h3>${cdn_label(c) !== c.name ? `<small class="muted cdnlegal">${esc(c.name)}</small>` : ''}<div class="mstags">${ms_tag('client')}${c.archived ? `<span class="rotag">${tr('Archived')}</span>` : ''}${c.org_name ? `<span class="muted">${esc(c.org_name)}</span>` : ''}</div></div>
      <span class="ctacts"><button class="btn sm" data-act="client-edit" data-id="${c.id}">${ic('edit', 's')} ${tr('Edit')}</button><button class="iconbtn" data-mscl="cmenu" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('dots')}</button></span></div>
    <div class="mscly msclstats cldetail">${S.ly.view === 'clients' ? '' : `<div class="lybar"><span class="spacer"></span>${lyCustomBtn('clients')}</div>`}${lyHtml('clients', {  // 2.55.0 (#1067): the card's sections are blocks of the view builder
      details: `<div class="ctfields">
      ${f('money', tr('Hourly rate'), c.rate != null ? esc(`${fmtNum(c.rate, 2)} ${cur}`) : '')}
      ${f('chart', tr('Budget'), esc(bud))}
      ${f('at', tr('E-mail'), c.email ? `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : '')}
      ${f('phone', tr('Phone'), c.phone ? `<a href="tel:${esc(c.phone.replace(/[^\d+]/g, ''))}">${esc(c.phone)}</a>` : '')}
      ${f('mappin', tr('Address'), ctk_mapLink(adr))}${''/* 2.119.1 B (#2086): a map link */}
      ${f('hash', tr('Customer number'), esc(b.customer_no || ''), 'cl_customer_no')}
      ${f('receipt', tr('VAT ID'), esc(b.vat_id || ''), 'cl_vat_id')}
      ${f('tag', tr('Buyer reference (e.g. routing ID)'), esc(b.buyer_reference || ''), 'cl_buyer_reference')}
      ${f('send', tr('Peppol ID'), esc(b.peppol_id || ''), 'cl_peppol_id')}${''/* 2.154.0 B (#1960) */}
      ${f('at', tr('E-mail for invoices'), b.email_invoice ? `<a href="mailto:${esc(b.email_invoice)}">${esc(b.email_invoice)}</a>` : '', 'cl_email_invoice')}
      ${f('clock', tr('Payment terms (days)'), b.payment_terms_days != null ? esc(String(b.payment_terms_days)) : '', 'cl_payment_terms_days')}
    </div>`,
      persons: ks.length ? `<div class="ctsec"><h4>${tr('Contact persons')}</h4><ul class="ctlinks msclks">${ks.map(k => `<li>${ic('user', 's')} ${k.contact_id && feat('contacts') ? `<a href="#contacts/${k.contact_id}" title="${esc(tr('Open contact'))}"><b>${esc(k.name)}</b></a>` : `<b>${esc(k.name)}</b>`}${k.role ? ` <span class="muted">${esc(k.role)}</span>` : ''}${k.is_default && ks.length > 1 ? ` <span class="rotag">${tr('Default')}</span>` : ''}${k.email ? ` · <a href="mailto:${esc(k.email)}">${esc(k.email)}</a>` : ''}${k.phone ? ` · <a href="tel:${esc(k.phone.replace(/[^\d+]/g, ''))}">${esc(k.phone)}</a>` : ''}</li>`).join('')}</ul></div>` : '',
      invoices: typeof officeOn === 'function' && officeOn() && MSC.inv !== null ? `<div class="ctsec"><h4>${tr('Open invoices')}</h4>${inv.length ? `<ul class="ctlinks">${inv.map(x => `<li><a class="linkbtn" href="#office/offers/${x.id}">${ic('receipt', 's')} ${esc(x.number || tr('Draft'))}</a><span class="muted"> · ${esc(x.date ? fmtDateLoc(x.date) : '')} · ${esc(x.open_text || '')} · ${esc(x.status_text || '')}</span></li>`).join('')}</ul>` : `<p class="muted">${tr('No open invoices.')}</p>`}</div>` : '',
      privacy: dsb_clHtml(c),  // 2.154.0 C (#2192): the data protection sheets (office admins)
      tickets: typeof ptl_clientHtml === 'function' ? ptl_clientHtml(c) : '',  // 2.63.0 B (#1513): the client's reports
      gendocs: ms_clGdHtml(c) + ms_clLtHtml(c),  // 2.93.0 A (#1927): the documents made from templates (office admins); 2.153.0 (#2028): + letters
      ...clientDetailParts(c)})}${clm_histHtml(c)}${typeof hbm_clientHtml === 'function' ? hbm_clientHtml(c) : ''}${typeof vdr_clientHtml === 'function' ? vdr_clientHtml(c) : ''}${''/* 2.99.1 A (#1959): video sign-offs */}</div>
  </article>`;
}

// ---- 2.120.0 B (#2088): "Send portal link": the client gets the sign-in link of the customer portal by mail (office/portaldocs.py;
// the office setting "Show documents in the customer portal" must be on, else the server says so)
function kp_menuItem(c) {
  const to = c.billing?.email_invoice || c.email || '';
  if (!to || typeof officeOn !== 'function' || !officeOn() || S.me?.kid) return null;
  return {label: tr('Send portal link'), icon: 'mail', fn: async () => {
    if (!await askConfirm(tr('Send the portal link to {0}?', to), tr('The client sees the sent quotations, invoices and their payment status. The link is valid for 30 minutes.'), {ok: tr('Send|mail')})) return;
    try { const j = await rawFetch('POST', `/api/office/clients/${c.id}/portal-link`, {}); toast(tr('Portal link sent to {0}', j.to || to)); } catch (x) { toast(x.message || ''); }
  }};
}

// ---- #1733: several clients at once (the selection bar of the contacts, multisel.js): Edit (rate, budget, colour,
// a note appended), Archive / Restore, Delete (a client in use is archived instead); one undo step each except Delete
function ms_clBar() {
  const n = MSC.pick.size, sel = (MSC.items || []).filter(c => MSC.pick.has(c.id)), allArch = sel.length && sel.every(c => c.archived);
  const shown = ms_clShown(), allOn = n && shown.every(c => MSC.pick.has(c.id));
  return ms_barHtml('ct-sbar', 'clb', n, tr('Tap clients'), [['all', 'all', allOn ? tr('Select none') : tr('All')], ['edit', 'edit', tr('Edit')],
    ['arch', allArch ? 'undo' : 'archive', allArch ? tr('Restore') : tr('Archive')], ['merge', 'collapse', tr('Merge'), '', 2],
    ...(ofm_can(sel[0]?.org_id ?? null) ? [['move', 'brief', tr('Move to another workspace…')]] : []), ['del', 'trash', tr('Delete'), 'danger']]);  // 2.97.0 C (#2049)  // 2.66.0 (#1835): merge from two clients on (min 2)
}
function ms_clClick(id, shift) {
  if (!MSC.pick) { MSC.pick = new Set(); MSC.last = null; }
  if (shift && MSC.last != null) for (const x of ms_range(ms_clShown().map(c => c.id), MSC.last, id)) MSC.pick.add(x);
  else if (MSC.pick.has(id)) MSC.pick.delete(id); else MSC.pick.add(id);
  MSC.last = id; ms_clDraw();
}
const ms_clEnd = () => { MSC.pick = null; MSC.last = null; ms_clDraw(); };
const ms_clSend = body => rawFetch('POST', '/api/clients/bulk', body);
async function ms_clAfter() { ms_clDirty(); CLV.data = null; await load().catch(() => {}); ms_clDraw(); }
async function ms_clAct(k) {
  if (!MSC.pick) return;
  if (k === 'close') { ms_clEnd(); return; }
  const shown = ms_clShown();
  if (k === 'all') { if (MSC.pick.size && shown.every(c => MSC.pick.has(c.id))) MSC.pick.clear(); else for (const c of shown) MSC.pick.add(c.id); ms_clDraw(); return; }
  const ids = [...MSC.pick]; if (!ids.length) return;
  if (k === 'arch') {
    const sel = (MSC.items || []).filter(c => MSC.pick.has(c.id)), action = sel.every(c => c.archived) ? 'unarchive' : 'archive';
    let j; try { j = await ms_clSend({action, ids}); } catch (x) { toast(x.message || ''); return; }
    ms_clEnd(); await ms_clAfter();
    const msg = action === 'archive' ? trn('{0} client archived', '{0} clients archived', j.changed) : trn('{0} client restored', '{0} clients restored', j.changed);
    if (j.changed) ms_hist(msg, msg, async () => { await ms_clSend({action: 'restore', items: j.undo}); await ms_clAfter(); }, async () => { j = await ms_clSend({action, ids}); await ms_clAfter(); });
    else toast(msg);
  } else if (k === 'del') {
    if (!await askConfirm(trn('Delete {0} client?', 'Delete {0} clients?', ids.length), tr('Clients used in quotations, invoices or contracts are archived instead. Their projects stay; they only lose the client.'), {ok: tr('Delete'), danger: true})) return;
    let j; try { j = await ms_clSend({action: 'delete', ids}); } catch (x) { toast(x.message || ''); return; }
    if (S.route.client && ids.includes(S.route.client) && !j.undo.some(x => x.id === S.route.client)) go('clients');
    ms_clEnd(); await ms_clAfter();
    toast([trn('{0} deleted', '{0} deleted', j.deleted), j.archived ? trn('{0} archived (in use)', '{0} archived (in use)', j.archived) : '', j.skipped ? trn('{0} skipped (only the creator or an admin may delete it)', '{0} skipped (only the creator or an admin may delete them)', j.skipped) : ''].filter(Boolean).join(' · '));
  } else if (k === 'edit') ms_clEdit(ids);
  else if (k === 'merge') clm_merge(ids);  // 2.66.0 B (#1835)
  else if (k === 'move') ofm_clients(ids);  // 2.97.0 C (#2049)
}
// 2.66.0 B (#1835): merging duplicate clients (multisel.js ms_merge; server team/clientmerge.py): per differing field the value
// that stays, the contact persons are joined; the overview comes from the server (dry); one undo step (and Undo in the history)
function clm_merge(ids) {
  const sel = ids.map(i => (MSC.items || []).find(c => c.id === i)).filter(Boolean);
  if (sel.length < 2) { toast(tr('Choose at least two entries to merge')); return; }
  const cur = S.settings.time_currency || '€', num = (v, d, u) => v == null || v === '' ? '' : `${fmtNum(v, d)}${u ? ' ' + u : ''}`;
  const val = (k, fn) => Object.fromEntries(sel.map(c => [c.id, String(fn(c) ?? '')]));
  const fields = [['name', tr('Name'), c => c.name], ['contact', tr('Default contact person'), c => c.contact], ['email', tr('E-mail'), c => c.email],
    ['phone', tr('Phone'), c => c.phone],  // 2.97.0 B (#1951): no free address any more (street etc. below)
    ['rate', tr('Hourly rate'), c => num(c.rate, 2, cur)], ['budget_h', tr('Budget in hours'), c => num(c.budget_h, 1, 'h')],
    ['budget_amount', tr('Budget as an amount'), c => num(c.budget_amount, 2, cur)], ['note', tr('Note'), c => c.note],
    ...OFX_CL_FIELDS.map(([k, n]) => [k, tr(n), c => (c.billing || {})[k]])].map(([k, label, fn]) => ({k, label, vals: val(k, fn)}));
  const send = (target, pick, dry) => rawFetch('POST', '/api/clients/merge', {target, ids, pick, dry});
  ms_merge({title: trn('Merge {0} client', 'Merge {0} clients', sel.length),
    recs: sel.map(c => ({id: c.id, label: cdn_label(c), sub: [c.org_name, c.archived ? tr('Archived') : ''].filter(Boolean).join(' · ')})),
    fields, lists: [{k: 'contacts', label: tr('Contact persons'), vals: Object.fromEntries(sel.map(c => [c.id, (c.contacts || []).map(k => k.name)]))}],
    preview: (target, pick) => send(target, pick, true),
    run: async (target, pick) => {
      let j = await send(target, pick, false);
      ms_clEnd(); await ms_clAfter(); go('client/' + target);
      const msg = trn('{0} client merged', '{0} clients merged', sel.length);
      ms_hist(msg, tr('Clients merged'), async () => { await rawFetch('POST', `/api/clients/merges/${j.run_id}/undo`, {}); await ms_clAfter(); },
        async () => { j = await send(target, pick, false); await ms_clAfter(); });
      return true;
    }});
}
function ms_clEdit(ids) {
  const cur = esc(S.settings.time_currency || '€'), num = (k, unit, lab) => `<span class="lacts"><input id="ms-f-${k}" data-msf="${k}" inputmode="decimal" class="numin" placeholder="–" aria-label="${esc(lab)}"><span class="muted">${unit}</span></span>`;
  ms_sheet(trn('Edit {0} client', 'Edit {0} clients', ids.length), tr('Only what you fill in or tick changes; everything else stays as it is.'), [
    {k: 'rate', label: tr('Hourly rate'), input: num('rate', cur, tr('Hourly rate')), hint: tr('empty = remove')},
    {k: 'budget_h', label: tr('Budget in hours'), input: num('budget_h', 'h', tr('Budget in hours')), hint: tr('empty = remove')},
    {k: 'budget_amount', label: tr('Budget as an amount'), input: num('budget_amount', cur, tr('Budget as an amount')), hint: tr('empty = remove')},
    {k: 'color', label: tr('Colour'), input: `<input type="color" id="ms-f-color" data-msf="color" value="#4f7cff" aria-label="${esc(tr('Colour'))}">`},
    {k: 'note_append', label: tr('Append to the note'), input: `<textarea id="ms-f-note_append" data-msf="note_append" rows="3" maxlength="4000"></textarea>`, fill: true}],
  async v => {
    const body = {action: 'set', ids};
    for (const k of ['rate', 'budget_h', 'budget_amount']) if (k in v) body[k] = numBody(v[k]);  // 2.263.0 (#2976)
    if ('color' in v) body.color = v.color;
    if (v.note_append) body.note_append = v.note_append;
    let j = await ms_clSend(body);
    ms_clEnd(); await ms_clAfter();
    const msg = trn('{0} client changed', '{0} clients changed', j.changed);
    if (j.changed) ms_hist(msg, tr('Clients changed'), async () => { await ms_clSend({action: 'restore', items: j.undo}); await ms_clAfter(); }, async () => { j = await ms_clSend(body); await ms_clAfter(); });
    else toast(msg);
    return true;
  });
}

// ---- events
document.addEventListener('input', e => {
  if (e.target.id !== 'mscl-q') return;
  MSC.q = e.target.value; clearTimeout(MSC.t); MSC.t = setTimeout(ms_clDraw, 120);
});
document.addEventListener('change', e => { if (e.target.id === 'mscl-arch') { MSC.arch = e.target.checked; ms_clDraw(); } });
const ms_clLp = ms_longPress('#view .msclients .ctrow[data-clopen]', () => !!MSC.pick, r => ms_clClick(+r.dataset.clopen, false));
document.addEventListener('click', e => {
  if (S.route.mod !== 'clients') return;
  const bb = e.target.closest('#ct-sbar [data-clb]');
  if (bb) { ms_clAct(bb.dataset.clb); return; }
  const o = e.target.closest('#view [data-clopen]');
  if (o) {
    e.preventDefault();
    if (ms_lpRecent(ms_clLp)) return;  // the click that ends a long press
    if (MSC.pick || (ms_modClick(e) && !isMobile())) { ms_clClick(+o.dataset.clopen, e.shiftKey); return; }
    go('client/' + o.dataset.clopen); return;
  }
  const b = e.target.closest('#view [data-mscl]'); if (!b) return;
  const k = b.dataset.mscl;
  if (k === 'pick') { MSC.pick = MSC.pick ? null : new Set(); MSC.last = null; ms_clDraw(); }
  else if (k === 'back') go('clients');
  else if (k === 'cmenu' && CLV.data?.id) {
    const c = CLV.data;
    menu(b, [{label: c.archived ? tr('Restore') : tr('Archive'), icon: c.archived ? 'undo' : 'archive', fn: async () => {
      let j; try { j = await ms_clSend({action: c.archived ? 'unarchive' : 'archive', ids: [c.id]}); } catch (x) { toast(x.message || ''); return; }
      await ms_clAfter();
      const msg = c.archived ? trn('{0} client restored', '{0} clients restored', 1) : trn('{0} client archived', '{0} clients archived', 1);
      if (j.changed) ms_hist(msg, msg, async () => { await ms_clSend({action: 'restore', items: j.undo}); await ms_clAfter(); }, async () => { await ms_clSend({action: c.archived ? 'unarchive' : 'archive', ids: [c.id]}); await ms_clAfter(); });
    }}, ofm_can(c.org_id ?? null) ? {label: tr('Move to another workspace…'), icon: 'brief', fn: () => ofm_clients([c.id])} : null,  // 2.97.0 C (#2049)
    typeof tpo_on === 'function' && tpo_on() ? {label: tr('Find a date…'), icon: 'users', fn: () => tpo_forClient(c)} : null,  // 2.98.0 A (#1953)
    formsOn() && !S.me?.kid ? {label: tr('Copy questionnaire link for this client'), icon: 'copy', fn: () => fq_clientLink(c, b)} : null,  // 2.102.0 C (#2201)
    kp_menuItem(c)]);  // 2.120.0 B (#2088)
  }
});
document.addEventListener('keydown', e => {  // capture: before the global Esc (an open menu / dialog closes first)
  if (e.key === 'Escape' && MSC.pick && S.route.mod === 'clients' && !$('.modal, .lightbox') && $('#pop')?.classList.contains('hidden')) { e.preventDefault(); ms_clEnd(); }
}, true);

// ---- 2.97.0 C (#2049): office data into another workspace (office/officemove.py, POST /api/office/move-space): clients (with
// their contact persons and drafts), drafts, trips, templates. Issued documents stay where they were issued; on request a
// read-only copy goes into the target's archive. One undo step (the same move back); redo = the move again.
const ofm_on = () => typeof officeOn === 'function' && officeOn() && S.me?.kind !== 'agent';
const ofm_can = from => ofm_on() && smv_can(from);
function ofm_officeFrom() {  // the workspace of the office shown (org id | null = the personal office)
  if (typeof OFC !== 'undefined' && OFC.info?.personal) return null;
  const w = typeof wsCur === 'function' ? wsCur() : 'private', ws = S.me?.workspaces || [];
  return w.startsWith('org:') ? +w.slice(4) : w === 'all' && ws.length === 1 ? ws[0].id : null;
}
async function ofm_move({what, ids, from, label, after}) {
  const req = (to, extra) => rawFetch('POST', '/api/office/move-space', {what, ids, to: smv_ws(to), ...extra});
  const r = await smv_open({what: label, from, option: what === 'clients' ? {label: tr('Take issued documents along as a read-only copy')} : null,
    check: (to, _pl, opt) => req(to, {dry: 1, copy_issued: opt ? 1 : 0}),
    run: async (to, _pl, opt) => { try { return {...await req(to, {copy_issued: opt ? 1 : 0}), to, opt}; } catch (e) { toast(e.message); throw e; } }});
  if (!r || !r.ok) return null;
  let mid = r.move_id;
  await after();
  const e = histAdd({label: tr('Moved {0}', label), ids: [], snaps: [], lids: [], wsp: r.space,
    undo: async () => { await rawFetch('POST', '/api/office/move-space', {undo: mid}); await after(); return {skipped: []}; },
    redo: async () => { const b = await req(r.to, {copy_issued: r.opt ? 1 : 0}); mid = b.move_id; await after(); return {skipped: []}; }});
  histToast(tr('Moved to {0}', wsName(r.space)), e);
  return r;
}
function ofm_clients(ids) {
  const sel = ids.map(i => (MSC.items || []).find(c => c.id === i) || (CLV.data?.id === i ? CLV.data : null)).filter(Boolean);
  if (!sel.length) return;
  const from = sel[0].org_id ?? null;
  if (sel.some(c => (c.org_id ?? null) !== from)) { toast(tr('Choose items of one workspace')); return; }
  ofm_move({what: 'clients', ids: sel.map(c => c.id), from, label: sel.length === 1 ? qn(sel[0].name) : trn('{0} client', '{0} clients', sel.length),
    after: async () => { if (MSC.pick) ms_clEnd(); await ms_clAfter(); }});
}
// ---- 2.149.0 F (#2518): the e-mail filing (hubmail.js) loads on demand (lazyload.js module hubmail). What the start draws stays
// here: the link to the mail a task / an event was made from, its click, the entry in Office > Clients; the client's card and the
// project page draw their mail section once it has loaded (nothing before the first answer, as before)
// the entry in Office > Clients
const hbm_hubBtn = () => `<a class="btn sm" href="#mailhub" title="${esc(tr('E-mail filing'))}">${ic('inbox', 's')}<span class="cdl">${tr('E-mail filing')}</span></a>`;
// the mail a task / an event was made from: "E-mail: <subject>" (a tap opens it); only "E-mail" for who may not read the
// mail (the server sends neither subject nor id then). Filled after the answer (cached a minute), the detail is not redrawn
const HBML = {};  // 'task:<id>' | 'event:<id>' -> {at, links}
function hbm_linkHtml(kind, id) {
  if (!(id > 0)) return '';
  const k = `${kind}:${id}`, c = HBML[k];
  if (!c || Date.now() - c.at > 60000) hbm_linkLoad(k);
  return `<div class="hbmlnk" data-hbmlnk="${k}">${c ? hbm_linkInner(c.links) : ''}</div>`;
}
const hbm_linkInner = links => (links || []).map(x => x.mail_id
  ? `<button type="button" class="linkbtn" data-hbmopen="${x.mail_id}" data-hbmk="link">${ic('mail', 's')}<span>${esc(tr('E-mail: {0}', x.subject || tr('(no subject)')))}</span></button>`
  : `<span class="muted">${ic('mail', 's')} ${tr('E-mail')}</span>`).join('');
async function hbm_linkLoad(k) {
  const [kind, id] = k.split(':');
  HBML[k] = {at: Date.now(), links: HBML[k]?.links || []};
  let j; try { j = await rawFetch('GET', `/api/hubmail/links?${kind}_id=${id}`); } catch { return; }
  HBML[k] = {at: Date.now(), links: j.links || []};
  for (const el of document.querySelectorAll(`[data-hbmlnk="${k}"]`)) el.innerHTML = hbm_linkInner(j.links);
}
const hbm_taskLinkHtml = t => t && !t.context ? hbm_linkHtml('task', t.id) : '';
document.addEventListener('click', e => {
  const o = e.target.closest?.('[data-hbmopen]'); if (!o) return;
  e.preventDefault(); if (o.closest('#pop') && typeof closePop === 'function') closePop(); hbm_open(+o.dataset.hbmopen, o.dataset.hbmk);
});
window.hbm_clientHtml = c => { if (c) ld_later('hubmail'); return ''; };
window.hbm_projHtml = l => { if (l?.kind === 'project' && !l.e2e) ld_later('hubmail'); return ''; };

// ---- 2.154.0 C (#2192): data protection sheets of the client (office/privacy.py; office admins, else no section / filter):
// the section with each sheet's status and the filter of the list; the dialogs and the menu live in office_doctpl.js
const DSB = {cl: null, all: null, f: '', no: false};  // no = the server said no (a member): no filter
function dsb_clHtml(c) {
  if (typeof officeOn !== 'function' || !officeOn()) return '';
  if (DSB.cl?.id !== c.id) { if (!DSB.cl?.busy) { DSB.cl = {id: c.id, busy: 1}; dsb_clLoad(c.id); } return ''; }
  const ss = DSB.cl.sheets; if (!ss) return '';
  const li = x => `<li>${ic('shield', 's')} <b>${esc(x.kind_label)}</b> <span class="rotag dsb-st dsb-st-${esc(x.status)}${x.review ? ' dsb-rev' : ''}">${esc(x.gen_status === 'draft' ? tr('Draft') : x.status_label)}</span><button type="button" class="iconbtn" data-dsb="menu" data-id="${x.id}" aria-haspopup="menu" aria-label="${esc(tr('More'))}: ${esc(x.kind_label)}" title="${esc(tr('More'))}">${ic('dots', 's')}</button>${dsb_replyHtml(x.reply)}</li>`;
  return `<div class="ctsec dsbsec"><h4>${tr('Data protection')}</h4>${ss.length ? `<ul class="ctlinks">${ss.map(li).join('')}</ul>` : ''}<button type="button" class="btn sm" data-dsb="new" data-cl="${c.id}">${ic('plus', 's')} ${tr('Data protection sheet')}</button></div>`;
}
// 2.209.0 C (#2589): the newest reply mail that was not filed (e.g. a revocation) at its sheet -- the customer's text, escaped
function dsb_replyHtml(r) {
  if (!r) return '';
  const when = new Date(r.at || '').toLocaleDateString(LOCALE(), {dateStyle: 'medium'});
  return `<div class="dsb-reply muted"><span>${esc(tr('Reply of {0}', when))}${r.from ? ` · ${esc(r.from)}` : ''}${r.subject ? ` · ${esc(r.subject)}` : ''}</span>${r.text ? `<blockquote>${esc(r.text)}</blockquote>` : ''}</div>`;
}
async function dsb_clLoad(id) {
  let ss = null;
  try { ss = (await rawFetch('GET', `/api/office/privacy-sheets?client_id=${id}&brief=1`)).sheets || []; } catch { ss = null; DSB.no = true; }  // quiet: members (403) see no section
  DSB.cl = {id, sheets: ss};
  ms_clDraw();
}
const dsb_clReload = () => { DSB.cl = null; DSB.all = null; ms_clDraw(); };
// the list filter: the newest sheet of each kind counts (open = not yet signed / handed over)
function dsb_clFilter() {
  if (typeof officeOn !== 'function' || !officeOn() || DSB.no) return '';
  const o = [['', tr('Data protection')], ['dpa', tr('DPA open')], ['consent', tr('Consent open')], ['info', tr('Information not handed over')], ['review', tr('To check')]];
  return `<select id="mscl-dsb" class="dsbflt" aria-label="${esc(tr('Data protection'))}">${o.map(([k, l]) => `<option value="${k}" ${DSB.f === k ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
}
function dsb_clPass(c) {
  if (!DSB.f) return true;
  if (!DSB.all) return false;
  const ss = DSB.all.filter(x => x.client_id === c.id);
  if (DSB.f === 'review') return ss.some(x => x.review);
  const x = ss.find(y => y.kind === DSB.f);  // newest first
  return !!x && (DSB.f === 'info' ? x.status === 'open' : ['open', 'sent'].includes(x.status));
}
document.addEventListener('change', async e => {
  if (e.target.id !== 'mscl-dsb') return;
  DSB.f = e.target.value;
  if (DSB.f) { try { DSB.all = (await rawFetch('GET', '/api/office/privacy-sheets?brief=1')).sheets || []; } catch { DSB.f = ''; DSB.no = true; } }  // fresh on every choice (another device may have changed a sheet)
  ms_clDraw();
});
document.addEventListener('click', async e => {
  const b = e.target.closest?.('#view [data-dsb]'); if (!b) return;
  await loadModule('office');
  if (b.dataset.dsb === 'new') dsb_new(+b.dataset.cl);
  else dsb_menu(b, (DSB.cl?.sheets || []).find(x => x.id === +b.dataset.id));
});
