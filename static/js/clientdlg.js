// @ts-check
/* Kalmido web client: the client dialog (clientModal) and the forms dialog of a list (formsModal) (2.1156.0, #4280: moved here from clients.js, loaded on demand for the start budget).
   Classic script sharing the global scope with the others; static/js/lazyload.js loads it (LD_MODS, the stand-ins of LD_CALL). */
'use strict';

// 2.218.0 C (#2804): a client's symbol is an app icon ("ic:" + name, at most 8 characters in all) or, as before, a saved emoji
const CL_ICONS = ['brief', 'home', 'users', 'bank', 'shop', 'tool', 'bag', 'cart', 'car', 'book', 'globe', 'star', 'heart', 'bulb', 'code', 'film'];
// ---- the client dialog
// 2.433.0 (#3604): the automatic short code of a name, as the server's client_short_code: the first three letters in capitals, umlauts written out
const CL_UML = {'Ä': 'AE', 'Ö': 'OE', 'Ü': 'UE', 'ß': 'SS'};
const cl_autoCode = n => String(n || '').toUpperCase().replace(/[ÄÖÜß]/g, m => CL_UML[m]).normalize('NFKD').replace(/[^A-Z]/g, '').slice(0, 3);
function cl_iconPickHtml(cur) {
  const old = cur && !cur.startsWith('ic:') ? `<button type="button" class="avopt on" data-clico="${esc(cur)}" aria-pressed="true" aria-label="${esc(cur)}"><span class="semo" aria-hidden="true">${esc(cur)}</span></button>` : '';
  return `<input type="hidden" id="cl-icon" value="${esc(cur)}"><div class="lipick clico" role="group" aria-labelledby="cl-icon-l"><button type="button" class="avopt none ${cur ? '' : 'on'}" data-clico="" aria-pressed="${!cur}" title="${esc(tr('No icon'))}" aria-label="${esc(tr('No icon'))}">${ic('ban', 's')}</button>${old}${CL_ICONS.map(k => `<button type="button" class="avopt ${cur === 'ic:' + k ? 'on' : ''}" data-clico="ic:${k}" aria-pressed="${cur === 'ic:' + k}" aria-label="${k}">${ic(k)}</button>`).join('')}</div>`;
}
function clientModal(c, o = {}) {  // 2.80.0 (#1842): o.org_id (the office's area, null = private), o.stay (no jump to the client)
  if (c && typeof loadModule === 'function') loadModule('ofundo').catch(() => {});  // 2.111.0 A (#2233): "Saved · Undo" after the save
  // 2.218.0 C (#2804): a new client starts short (name, e-mail, city); the rest sits under "More details" (values stay while it folds)
  const nm = `<div class="row"><label for="cl-name">${tr('Name')}</label><input id="cl-name" maxlength="80" value="${esc(c?.name || '')}" autocomplete="organization"></div>`;
  const nx = `<div class="row"><label for="cl-nx">${tr('Name addition')}</label><input id="cl-nx" maxlength="120" value="${esc(c?.name_extra || '')}" autocomplete="off" placeholder="${esc(tr('optional'))}" aria-describedby="cl-nx-h"></div>
    <div class="shint lhint" id="cl-nx-h">${tr('Printed as its own line under the name, e.g. the legal form or the partners.')}</div>`;
  const em = `<div class="row"><label for="cl-email">${tr('E-mail')}</label><input id="cl-email" type="email" maxlength="200" value="${esc(c?.email || '')}" autocomplete="email"></div>`;
  const short = !c && !o.quick, bb = c?.billing || {};
  // 2.433.0 (#3599): the e-mail for invoices sits next to E-mail / Phone (also when adding), no longer in the billing details
  const emi = cdn_invMailOk(bb, c) ? cdn_fieldHtml(bb)(OFX_CL_FIELDS.find(([k]) => k === 'email_invoice')) : '';
  const city = short ? cdn_fieldHtml(bb)(OFX_CL_FIELDS.find(([k]) => k === 'city')) : '';
  const addr = short ? `<div class="cdnaddr">${OFX_CL_FIELDS.filter(([k]) => CDN_ADDR.includes(k) && k !== 'city').map(cdn_fieldHtml(bb)).join('')}</div>` : cdn_addrHtml(bb);
  const dn = `<div class="row"><label for="cl-dname">${tr('Display name (optional)')}</label><input id="cl-dname" maxlength="80" value="${esc(c?.display_name || '')}" autocomplete="off" aria-describedby="cl-dname-h"></div>
    <div class="shint lhint" id="cl-dname-h">${tr('Shown in pickers and lists, not on the invoice.')}</div>`;
  // 2.433.0 (#3604): the short code for the number block {kuerzel} (with the office); empty = the first three letters of the name
  const sc = typeof officeOn === 'function' && officeOn() ? `<div class="row"><label for="cl-sc">${tr('Short code')}</label><input id="cl-sc" maxlength="6" value="${esc(c?.short_code || '')}" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="${esc(cl_autoCode(c?.name || ''))}" aria-describedby="cl-sc-h"></div>
    <div class="shint lhint" id="cl-sc-h">${tr('In numbers as {kuerzel}, e.g. 673_TNP_R. Empty = the first three letters of the name.')}</div>` : '';
  const ico = `<div class="row"><label id="cl-icon-l">${tr('Symbol')}</label>${cl_iconPickHtml(c?.icon || '')}</div>`;
  const rest = `${ico}
    <div class="row clkrow"><label>${tr('Contact persons')}</label><div class="clk" id="cl-contacts"></div></div>
    ${short ? '' : em + emi}
    <div class="row"><label for="cl-phone">${tr('Phone')}</label><input id="cl-phone" type="tel" maxlength="60" value="${esc(c?.phone || '')}" autocomplete="tel"></div>
    ${addr}${timeOn() ? `<div class="row"><label for="cl-rate">${tr('Hourly rate')}</label><input id="cl-rate" inputmode="decimal" class="numin" value="${c?.rate != null ? esc(fmtNum(c.rate, 2)) : ''}" placeholder="${esc(tr('optional'))}"><span class="muted">${esc(S.settings.time_currency || '')} · ${tr('for projects without their own rate')}</span></div>
    <div class="row"><label for="cl-bh">${tr('Budget')}</label><span class="lacts"><input id="cl-bh" inputmode="decimal" class="numin" value="${c?.budget_h != null ? esc(fmtNum(c.budget_h, 2)) : ''}" placeholder="–" aria-label="${esc(tr('Budget in hours'))}"><span class="muted">h</span><input id="cl-ba" inputmode="decimal" class="numin" value="${c?.budget_amount != null ? esc(fmtNum(c.budget_amount, 2)) : ''}" placeholder="–" aria-label="${esc(tr('Budget as an amount'))}"><span class="muted">${esc(S.settings.time_currency || '€')}</span></span></div>
    <div class="shint lhint">${tr('At 80 % of the budget the bar turns amber, over 100 % red.')}</div>` : ''}
    <div class="row"><label for="cl-note">${tr('Note')}</label><textarea id="cl-note" rows="3" maxlength="4000">${esc(c?.note || '')}</textarea></div>
    ${typeof officeOn === 'function' && officeOn() ? ofxClientBillingHtml(bb, c) : ''}
    ${c ? `<div class="row"><label>${tr('Archive')}</label><label class="chkl"><input type="checkbox" id="cl-arch" ${c.archived ? 'checked' : ''}> ${tr('Archived (hidden from the sidebar)')}</label></div>` : ''}`;
  /** @type {any} */
  const md = modal(`<h3>${c ? tr('Edit client') : tr('New client')}</h3>
    ${nm}
    ${o.quick ? `${nx}${addr}` : short ? `${em}${emi}${city}<details class="clmore" id="cl-more"><summary>${ic('chev', 's fcar')}<span>${tr('More details')}</span></summary>${nx}${dn}${sc}${rest}</details>` : `${nx}${dn}${sc}${rest}`}
    <div class="aerr" role="alert"></div>
    <div class="foot ${short ? 'clfoot' : ''}">${c?.can_delete ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${c ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('cldlg');
  if (c && c.bill_edit === false) for (const el of md.querySelectorAll('.clbill [data-clb], [data-clb="email_invoice"]')) { el.disabled = true; el.removeAttribute('data-clb'); }  // 2.187.1 A (#2735): read only, never sent
  clkInit(md, c);
  if (c?.updated_at) loadModule('objsave').then(() => dlgStale(md, `/api/clients/${c.id}`, () => (md._objBase || c._objBase || c).updated_at)).catch(() => {});  // 2.576.0 (#4764): saved elsewhere meanwhile -> the calm bar
  const scIn = $('#cl-sc', md), nmIn = $('#cl-name', md);  // 2.433.0 (#3604): capitals while typing, the automatic code as placeholder
  if (scIn) { scIn.addEventListener('input', () => { scIn.value = scIn.value.toUpperCase().replace(/[^A-Z0-9]/g, ''); }); nmIn?.addEventListener('input', () => { scIn.placeholder = cl_autoCode(nmIn.value); }); }
  const close = fgModal(md);  // 2.40.0 (#1371): the client card asks before unsaved input is lost
  // 2.552.0 (#4547): + the contact persons (rows drawn by clkDraw) and the symbol (a hidden field set by its buttons)
  const clX = () => { clkRead(md); return JSON.stringify({icon: $('#cl-icon', md)?.value ?? null, k: md._clk, rm: md._clkRm}); }, clX0 = clX();
  fdDialog(md, 'cl.' + (c?.id || 'new'), c?.updated_at || '', {get: () => { const v = clX(); return v === clX0 ? undefined : JSON.parse(v); }, put: v => cl_fdPut(md, v)});  // 2.527.0 (#4304 A5): the input survives an ended session / a closed tab
  const num = numBody;  // 2.263.0 (#2976)
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const ib = e.target.closest('[data-clico]');
    if (ib) { cl_icoSet(md, ib.dataset.clico); $('#cl-icon', md).dispatchEvent(new Event('change', {bubbles: true})); return; }  // 2.218.0 C (#2804); 2.552.0 (#4547): "change" = kept (fdDialog)
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        // 2.152.0 C (#2168): a client used in quotations / invoices / contracts is archived instead (the answer says so)
        // 2.272.0 D (#3029): the dialog names what points at it (server: foreign-key catalogue); deleting = the clients' trash
        const u = await api('GET', `/api/clients/usage?ids=${c.id}`).catch(() => null);
        // 2.223.3 B (#2878): a client finalised documents keep can be anonymised instead (its own button, confirmed again)
        let anon = false;
        const addAnon = m => { const x = document.createElement('button'); x.type = 'button'; x.className = 'btn'; x.textContent = tr('Anonymise'); x.addEventListener('click', () => { anon = true; m.remove(); }); $('.foot .spacer', m).after(x); };
        const yes = await askConfirm(tr('Delete the client “{0}”?', c.name), cl_delText(u), {ok: tr('Delete'), danger: true, after: u?.in_use === 1 ? addAnon : undefined});
        if (anon) {
          if (!await askConfirm(tr('Anonymise the client “{0}”?', c.name), tr('Its finalised documents stay as the law asks, with their own copy of the address. Name, contact details, address, note and contact persons of the client are removed permanently.'), {ok: tr('Anonymise'), danger: true})) return;
          await api('POST', `/api/clients/${c.id}/anonymize`); md.remove(); await load(); render(); clReload(); toast(tr('Client anonymised'));
          return;
        }
        if (!yes) return;
        const j = await api('DELETE', `/api/clients/${c.id}`); md.remove(); await load(); if (S.route.client === c.id) go('clients'); else render(); clReload();
        if (j?.archived) toast(j.message, c.archived ? undefined : async () => { await api('PATCH', `/api/clients/${c.id}`, {archived: 0}); await load(); render(); clReload(); });
        else if (j?.trashed) toast(tr('“{0}” moved to the trash', c.name), async () => { await api('POST', `/api/clients/${c.id}/restore`); await load(); render(); clReload(); });
        return;
      }
      const v = s => $(s, md)?.value ?? '';  // 2.97.0 B (#1951): the quick dialog (a document's "Add client") has name + address only
      const body = o.quick ? {name: v('#cl-name'), name_extra: v('#cl-nx')} : {name: v('#cl-name'), name_extra: v('#cl-nx'), icon: v('#cl-icon'), contacts: clkValue(md), email: v('#cl-email'),
        phone: v('#cl-phone'), display_name: v('#cl-dname'), note: v('#cl-note')};  // 2.99.0 D (#2188): + name_extra
      if ($('#cl-sc', md)) body.short_code = v('#cl-sc').trim().toUpperCase();  // 2.433.0 (#3604)
      if (!c && 'org_id' in o) body.org_id = o.org_id;
      if (!o.quick && md._clkRm?.length) body.contacts_removed = md._clkRm.slice();  // only these are deleted (missing ones stay)
      if ($('#cl-rate', md)) Object.assign(body, {rate: num($('#cl-rate', md).value), budget_h: num($('#cl-bh', md).value), budget_amount: num($('#cl-ba', md).value)});
      if ($('#cl-arch', md)) body.archived = $('#cl-arch', md).checked;
      for (const el of md.querySelectorAll('[data-clb]')) if (!(el.dataset.clb === 'country' && !ctyValid(el.value) && el.value === (c?.billing?.country || ''))) body[el.dataset.clb] = el.dataset.clb === 'payment_terms_days' ? (el.value.trim() === '' ? null : +el.value.trim()) : el.value;
      let r, gone = false;
      // 2.576.0 (#4794): a change through objsave.js (only the fields that differ from the client as opened, with
      // expect_updated_at; saved elsewhere meanwhile -> the merge bar, never overwritten)
      const send = async () => { if (!c) return rawFetch('POST', '/api/clients', body); await loadModule('objsave'); objSess(`/api/clients/${c.id}`, c.updated_at); return (await objSaveForm(md, `/api/clients/${c.id}`, c, body)) || c; };  // 2.747.0 (#5246): objSess = the undo session of this save
      try { r = await send(); }
      catch (x) {
        // 2.81.0 (#1852): a linked contact was deleted elsewhere -> drop that link, save once more, tell the person
        if (x.data?.code !== 'contact_gone' || !body.contacts.some(k => k.contact_id === x.data.contact_id)) throw x;
        body.contacts = body.contacts.map(k => k.contact_id === x.data.contact_id ? {...k, contact_id: null} : k);
        r = await send();
        gone = true;
      }
      md.remove(); await load(); render(); clReload();
      if (gone || !(c && r !== c && typeof objSaved === 'function' && objSaved(`/api/clients/${c.id}`, r.name, async () => { await load(); render(); clReload(); }))) toast(gone ? tr('The linked contact no longer exists; link removed.') : c ? tr('Saved') : tr('Added: {0}', r.name));  // 2.111.0 A (#2233); 2.747.0 (#5246): objsave.js objSaved
      if (!c && !o.stay) go('client/' + r.id);
      if (o.done) await o.done(r);
    } catch (x) {
      if (typeof objConflict === 'function' && await objConflict(md, x, rec => clientModal(rec, o), cl_field)) return;  // 2.576.0 (#4794): the merge bar
      const el = $('.aerr', md); if (el) el.textContent = x.message || '';
    }
  });
  setTimeout(() => { if (!isTouch()) $('#cl-name', md)?.focus(); }, 50);
}

// 2.218.0 C (#2804): the chosen symbol (the hidden field and the pressed button)
function cl_icoSet(md, v) {
  const el = $('#cl-icon', md); if (!el) return;
  el.value = v; for (const x of $$('[data-clico]', md)) { const on = x.dataset.clico === v; x.classList.toggle('on', on); x.setAttribute('aria-pressed', on); }
}
// 2.552.0 (#4547): the kept contact persons and symbol back into the dialog (fdDialog)
function cl_fdPut(md, v) {
  if (!v || typeof v !== 'object') return;
  if (Array.isArray(v.k)) { md._clk = v.k; md._clkRm = Array.isArray(v.rm) ? v.rm : []; clkDraw(md); }
  if (typeof v.icon === 'string') cl_icoSet(md, v.icon);
  const det = $('#cl-more', md); if (det && !det.open) det.open = true;
}
// 2.269.0 C (#3017): someone else saved the client in between -- a bar instead of overwriting; "Reload" opens the dialog with
// the saved state (the own input of this dialog is not saved, the bar says so)
// 2.576.0 (#4764): the input of client field k in dialog md (for the merge bar's marks)
const CL_IDS = {name: 'cl-name', name_extra: 'cl-nx', icon: 'cl-icon', email: 'cl-email', phone: 'cl-phone', display_name: 'cl-dname', note: 'cl-note', short_code: 'cl-sc', rate: 'cl-rate', budget_h: 'cl-bh', budget_amount: 'cl-ba', archived: 'cl-arch'};
const cl_field = (md, k) => (CL_IDS[k] && $('#' + CL_IDS[k], md)) || md.querySelector(`[data-clb="${CSS.escape(k)}"]`);
// 2.40.0 (#1380): the contact persons of a client in its dialog -- name, function / department, e-mail, phone; one is the
// default (it fills "contact" and the attention line of new documents). Saved with the client as the whole list.
function clkInit(md, c) {
  const ks = (c?.contacts || []).map(k => ({...k}));
  if (!ks.length && c?.contact) ks.push({name: c.contact, role: '', email: '', phone: '', is_default: true});
  md._clk = ks;
  md._clkRm = [];  // 2.269.0 C (#3017): the ids removed in this dialog (sent as contacts_removed)
  md._clId = c?.id || 0;  // 2.59.0 (#1735): the address book search needs a saved client (its organisation)
  clkDraw(md);
}
function clkValue(md) {
  clkRead(md);
  for (const k of md._clk) if (k.id && !(k.name || '').trim() && !md._clkRm.includes(k.id)) md._clkRm.push(k.id);  // 2.269.0 C (#3017): a cleared name = removed
  return md._clk.filter(k => (k.name || '').trim()).map(k => ({...(k.id ? {id: k.id} : {}), name: k.name.trim(), role: (k.role || '').trim(), email: (k.email || '').trim(), phone: (k.phone || '').trim(), is_default: !!k.is_default, contact_id: k.contact_id || null,
    ...(clk_invOn() ? {gets_invoices: !!k.gets_invoices} : {})}));  // 2.433.0 (#3599): without the office the mark stays as saved
}
// ---- forms of a list (#463 / #341)
async function formsModal(lid) {
  // 2.102.0 C (#2208): the questions' part of the dialog (formq.js) loads with it
  let j; try { [j] = await Promise.all([api('GET', `/api/lists/${lid}/forms`), loadModule('formq', () => formsModal(lid))]); } catch { return; }
  const l = listById(lid), secs = S.sections.filter(s => s.list_id === lid);
  const row = f => `<div class="mrow fmrow ${f.live ? '' : 'off'}" data-fid="${f.id}"><span class="n"><b>${esc(f.title)}</b> <span class="muted">${esc(f.access === 'public' ? tr('anyone with the link') : tr('people who see the project'))} · ${esc(trn('{0} sent', '{0} sent', f.count))}${f.live ? '' : ' · ' + esc(tr('off'))}</span></span>
    <button class="iconbtn ms-phsr" data-fm="copy" title="${esc(tr('Copy the link'))}" aria-label="${esc(tr('Copy the link of {0}', f.title))}">${ic('copy', 's')}</button><button class="iconbtn ms-phsr" data-fm="edit" title="${esc(tr('Edit form'))}" aria-label="${esc(tr('Edit {0}', f.title))}">${ic('edit', 's')}</button>${/*html-ok*/ ms_dots('[data-fm]', f.title) /* 2.1151.0 B (#3835): the phone's one "…" (escaped inside) */}</div>`;
  // 2.298.0 A2 (#3186): the explanation of a form only while there is none; the status link's how behind (i), its privacy
  // promise stays visible word for word
  /** @type {any} */
  const md = modal(`<div class="lhdr"><h3>${tr('Forms')} · ${esc(lname(l))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    ${j.forms.length ? '' : `<p class="muted">${tr('A form is a link with a small page (subject, description, name, e-mail): what someone sends becomes a task in this project. Agents of the project sort it in.')}</p>`}
    <div class="members" id="fm-list">${j.forms.map(row).join('') || `<div class="muted mhint">${tr('No form yet.')}</div>`}</div>
    <div class="row"><button class="btn sm" data-fm="new">${ic('plus', 's')} ${tr('New form')}</button></div><div id="fm-rqm"></div>`);
  rqm_load(md, lid);  // 2.553.0 B (#3460): requests by e-mail
  const edit = f => {
    /** @type {any} */
    const ed = modal(`<h3>${f ? tr('Edit form') : tr('New form')}</h3>
      <div class="row"><label for="fm-title">${tr('Title')}</label><input id="fm-title" maxlength="120" value="${esc(f?.title || '')}" placeholder="${esc(tr('e.g. IT request, bug report'))}"></div>
      <div class="row"><label for="fm-intro">${tr('Intro')}</label><textarea id="fm-intro" rows="3" maxlength="2000">${esc(f?.intro || '')}</textarea></div>
      ${fq_dialogHtml(f)}${''/* lazy-ok: 2.149.0 F (#2519): formsModal loaded formq first */}
      <div class="row"><label for="fm-access">${tr('Who can send it')}</label><select id="fm-access"><option value="org">${tr('Signed-in people who see the project')}</option><option value="public" ${f?.access === 'public' ? 'selected' : ''} ${j.public_links ? '' : 'disabled'}>${tr('Anyone with the link (no sign-in)')}</option></select></div>
      ${secs.length ? `<div class="row"><label for="fm-sec">${tr('Section')}</label><select id="fm-sec"><option value="">${tr('None')}</option>${secs.map(s => `<option value="${s.id}" ${s.id === f?.section_id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>` : ''}
      <div class="row"><label>${tr('E-mail')}</label><label class="chkl"><input type="checkbox" id="fm-email" ${f?.ask_email !== false ? 'checked' : ''} ${f?.portal ? 'disabled' : ''}> ${tr('Ask for an e-mail address (without sign-in)')}</label></div>
      <div class="row"><label for="fm-ttype">${tr('Type of report')}</label><select id="fm-ttype"><option value="">${tr('None')}</option>${TTYPES.map(([k, n]) => `<option value="${k}" ${f?.ttype === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
      <div class="row"><label>${tr('Attachment')}</label><label class="chkl"><input type="checkbox" id="fm-files" ${f?.files ? 'checked' : ''}> ${tr('Allow one file (at most 10 MB)')}</label></div>
      <div class="row"><label>${tr('Status link')}</label><label class="chkl"><input type="checkbox" id="fm-portal" ${f?.portal ? 'checked' : ''}> ${tr('The sender gets a link to the status')}</label></div>
      <div class="shint">${tr('Without sign-in, the sender sees a link after sending and gets it by e-mail (e-mail becomes required).')}</div><p class="muted mhint frm-hint">${tr('It shows only their report: title, status and the answers you send to them, never internal comments or your team.')}</p>
      ${f ? `<div class="row"><label>${tr('Status')}</label><label class="chkl"><input type="checkbox" id="fm-on" ${f.enabled ? 'checked' : ''}> ${tr('Open (accepts requests)')}</label></div>` : ''}
      ${f ? `<div class="row"><label>${tr('Link')}</label><input readonly value="${esc(f.url)}" aria-label="${esc(tr('Link'))}"><button type="button" class="btn sm" data-m="regen">${tr('New link')}</button></div>
      <div class="row qrrow"><label>${tr('QR code')}</label><button type="button" class="btn sm" data-m="qr">${ic('eye', 's')} ${tr('Show QR code')}</button></div>` : ''}
      <div class="aerr" role="alert"></div>
      <div class="foot">${f ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${f ? tr('Save') : tr('Create')}</button></div>`);
    // 2.63.0 (#1513): the status link goes by mail -> the e-mail field is on while it is
    fq_bind(ed, f);  // 2.98.0 B (#1954): the own questions (formq.js); lazy-ok: formsModal loaded it first
    $('#fm-portal', ed).addEventListener('change', (/** @type {any} */ e) => { const m = $('#fm-email', ed); if (e.target.checked) m.checked = true; m.disabled = e.target.checked; });
    ed.addEventListener('click', async (/** @type {any} */ e) => {
      const b = e.target.closest('[data-m]'); if (!b) return;
      if (b.dataset.m === 'close') { ed.remove(); return; }
      try {
        if (b.dataset.m === 'qr') { qrModal(f.url, f.title); return; }
        if (b.dataset.m === 'del') { if (!await askConfirm(tr('Delete the form “{0}”?', f.title), tr('The link stops working; tasks it created stay.'), {ok: tr('Delete'), danger: true})) return; await api('DELETE', `/api/forms/${f.id}`); }
        else if (b.dataset.m === 'regen') { if (!await askConfirm(tr('A new link?'), tr('The old link stops working at once.'), {ok: tr('New link')})) return; await api('PATCH', `/api/forms/${f.id}`, {regenerate: true}); }
        else {
          const body = {title: $('#fm-title', ed).value, intro: $('#fm-intro', ed).value, access: $('#fm-access', ed).value, ask_email: $('#fm-email', ed).checked,
            ttype: $('#fm-ttype', ed).value, files: $('#fm-files', ed).checked, portal: $('#fm-portal', ed).checked,  // 2.63.0 (#1513)
            ...fq_body(ed),  // 2.98.0 B (#1954)
            ...($('#fm-sec', ed) ? {section_id: $('#fm-sec', ed).value ? +$('#fm-sec', ed).value : null} : {}), ...($('#fm-on', ed) ? {enabled: $('#fm-on', ed).checked} : {})};
          await rawFetch(f ? 'PATCH' : 'POST', f ? `/api/forms/${f.id}` : `/api/lists/${lid}/forms`, body);
        }
        ed.remove(); md.remove(); formsModal(lid);
      } catch (x) { const el = $('.aerr', ed); if (el) el.textContent = x.message || ''; }
    });
  };
  md.addEventListener('click', async (/** @type {any} */ e) => {
    const b = e.target.closest('[data-fm],[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const f = j.forms.find(x => x.id === +b.closest('[data-fid]')?.dataset.fid);
    if (b.dataset.fm === 'new') edit(null);
    if (b.dataset.fm === 'edit' && f) edit(f);
    if (b.dataset.fm === 'copy' && f) { try { await navigator.clipboard.writeText(f.url); toast(tr('Copied')); } catch { toast(f.url, null, 8000); } }
  });
}
// 2.553.0 B (#3460): the project's switch "Requests by e-mail" below its forms: one request address; a mail to it becomes a task with
// a status link for the sender, the public answers go back by mail, the sender's replies become comments of the same request
const rqm_why = w => w === 'portal' ? tr('Public links are switched off on this server') : w === 'kind' ? tr('Only projects have an e-mail address')
  : w === 'e2e' ? tr('Not available in a project with end-to-end encryption') : tr('E-mail to tasks is not set up on this server');
async function rqm_load(md, lid) {
  const box = $('#fm-rqm', md); if (!box) return;
  let st; try { st = await api('GET', `/api/lists/${lid}/request-mail`); } catch { box.innerHTML = ''; return; }
  const off = !st.available && !st.on;
  box.innerHTML = `<section class="rqmbox" aria-label="${esc(tr('Requests by e-mail'))}"><h4>${ic('mail', 's')} ${tr('Requests by e-mail')}</h4>
    <label class="chkl"><input type="checkbox" data-rqm="on" ${st.on ? 'checked' : ''} ${off ? 'disabled' : ''}> ${tr('Accept requests by e-mail')}</label>
    <p class="muted mhint">${tr('An e-mail to the request address becomes a task with a status link for the sender. Your answers “To the client” go back by e-mail, the sender’s replies become comments of the same request. Internal comments never leave the app.')}</p>
    ${off ? `<p class="muted mhint">${esc(rqm_why(st.why))}</p>` : ''}
    ${st.on && st.address ? `<div class="row"><input readonly value="${esc(st.address)}" aria-label="${esc(tr('Request address'))}"><button type="button" class="btn sm" data-rqm="copy">${ic('copy', 's')} ${tr('Copy')}</button><button type="button" class="btn sm" data-rqm="renew">${tr('New address')}</button></div>
    <label class="chkl"><input type="checkbox" data-rqm="done" ${st.done_mail ? 'checked' : ''}> ${tr('Also an e-mail to the sender when the request is done')}</label>` : ''}</section>`;
  box.onchange = async e => {
    const k = e.target.dataset.rqm; if (k !== 'on' && k !== 'done') return;
    try { await api('PATCH', `/api/lists/${lid}/request-mail`, k === 'on' ? {on: e.target.checked} : {done_mail: e.target.checked}); } catch { e.target.checked = !e.target.checked; return; }
    rqm_load(md, lid);
  };
  box.onclick = async e => {
    const k = e.target.closest('[data-rqm]')?.dataset.rqm;
    if (k === 'copy') { try { await navigator.clipboard.writeText(st.address); toast(tr('Copied')); } catch { toast(st.address, null, 8000); } }
    if (k === 'renew') {
      if (!await askConfirm(tr('Make a new address?'), tr('The old address stops working at once.'), {ok: tr('New address')})) return;
      try { await api('PATCH', `/api/lists/${lid}/request-mail`, {renew: true}); } catch { return; }
      rqm_load(md, lid);
    }
  };
}
// 2.36.2 (#1021, E): billing details of a client for office & finance (structured address, VAT ID, customer number, buyer
// reference, invoice e-mail, payment terms); folded away, the free address above stays
/** @type {any[]} */
const OFX_CL_FIELDS = [['street', N_('Street'), 200], ['address_extra', N_('Address extra'), 200], ['zip', N_('Postcode'), 20], ['city', N_('City'), 120], ['country', N_('Country'), 2],
  ['vat_id', N_('VAT ID'), 20], ['customer_no', N_('Client no.|customer'), 40], ['buyer_reference', N_('Buyer reference (e.g. routing ID)'), 60],
  ['email_invoice', N_('E-mail for invoices'), 200], ['payment_terms_days', N_('Payment terms (days)'), 3],
  ['peppol_id', N_('Peppol ID'), 90], ['doc_lang', N_('Document language'), 5]];  // 2.154.0 B (#1960): e-invoices over the Peppol network
// 2.97.0 B (#1951): the address (street, extra line, postcode, city, country) stands in the form itself, the rest of the
// billing details below it; the free "Address" text is gone (the server keeps it in its column)
const CDN_ADDR = ['street', 'address_extra', 'zip', 'city', 'country'];
const cdn_fieldHtml = b => ([k, n, mx]) => k === 'doc_lang' ? `<div class="row"><label for="clb-doc_lang">${esc(tr(n))}</label><select id="clb-doc_lang" data-clb="doc_lang"><option value="">${esc(tr('As in the office settings'))}</option>${(S.languages || []).map(L => `<option value="${esc(L.code)}" ${L.code === b.doc_lang ? 'selected' : ''}>${esc(L.name)}</option>`).join('')}</select><div class="shint">${esc(tr('Used for new documents of this client and for its portal e-mails.'))}</div></div>` : (k === 'country' ? `<div class="row"><label for="clb-country-q">${esc(tr(n))}</label>${ctyField('clb-country', b.country, {attrs: 'data-clb="country"', label: tr(n)})}</div>` : `<div class="row"><label for="clb-${k}">${esc(tr(n))}</label><input id="clb-${k}" data-clb="${k}" maxlength="${mx}" value="${esc(b[k] ?? '')}" ${k === 'payment_terms_days' ? 'inputmode="numeric" class="numin"' : k === 'country' ? 'class="numin" autocapitalize="characters"' : k === 'email_invoice' ? 'type="email" autocomplete="off"' : ''}></div>`) + (typeof ofcII === 'function' ? ofcII('cl_' + k) : '');  // 2.40.0 (#1382): (i) of the terms
const cdn_addrHtml = b => `<div class="cdnaddr">${OFX_CL_FIELDS.filter(([k]) => CDN_ADDR.includes(k)).map(cdn_fieldHtml(b)).join('')}</div>`;
// 2.433.0 (#3599): the e-mail for invoices is shown (next to E-mail) with the office and the rights of its billing details
const cdn_invMailOk = (b, c) => typeof officeOn === 'function' && officeOn() && (c ? 'email_invoice' in b : !(typeof ofr_grp === 'function' && ofr_grp() && !['edit', 'manage'].includes(ofr_lvOf('offers'))));
function ofxClientBillingHtml(b, c) {
  // 2.187.1 A (#2735): without the office area "Quotes & invoices" the server leaves the invoicing keys out -> no block (never saved empty)
  let rest = OFX_CL_FIELDS.filter(([k]) => !CDN_ADDR.includes(k) && k !== 'email_invoice');  // 2.433.0 (#3599): email_invoice above
  if (c) rest = rest.filter(([k]) => k in b);
  else if (typeof ofr_grp === 'function' && ofr_grp() && !['edit', 'manage'].includes(ofr_lvOf('offers'))) rest = [];
  if (!rest.length) return '';
  const filled = rest.some(([k]) => b[k] != null && b[k] !== '');
  return `<details class="clbill" ${filled ? 'open' : ''}><summary>${tr('Billing details')}</summary>${rest.map(cdn_fieldHtml(b)).join('')}</details>`;
}
