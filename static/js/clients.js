/* Kalmido web client: package "Team, family, clients" (#463): clients (view, dialog, the list's client, the timesheet of a
   client), the workload view, approvals in the task panel, forms of a list, sign-in links with a QR code.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// 2.23.0 (#463). Three modules, each off by default (Settings > Modules > Projects and team): clients (customers above the
// lists: hours, budget, estimate vs. actual, the timesheet per client and month), workload (planned hours per person and
// week against their capacity) and forms (a link whose page creates a task). Approvals are part of collaboration (a task
// waits for one person's decision). Everything stays within the organisation; the server decides what each person sees.
const clientsOn = () => feat('clients');
const workloadOn = () => feat('workload') && collab();
const formsOn = () => feat('forms');
const CLV = {data: null, id: null, loading: false, seq: 0, month: null};
const WLV = {data: null, start: null, weeks: 4, org: null, loading: false, seq: 0, tab: 'wl'};  // 2.50.0 (#1195, #1194): tab wl | abs | dispo
const clientById = id => (S.clients || []).find(c => c.id === id);
// 2.97.0 B (#1951): the name a client shows in pickers and lists: its display name, else its name ("name (city)" when two
// clients of one workspace share it, see team/clients.cdn_labels); documents keep the name. cdn_name: by id from S.clients
const cdn_label = c => !c ? '' : c.label || clientById(c.id)?.label || c.display_name || c.name || '';
const cdn_name = (id, name) => (id && clientById(id)?.label) || name || '';
const cdn_addrLine = c => { const b = c?.billing || {}; return [b.street, b.address_extra, [b.zip, b.city].filter(Boolean).join(' '), b.country].filter(Boolean).join(', '); };
const clientOfList = l => l && l.client_id ? clientById(l.client_id) : null;
const clientIco = c => c.icon ? `<span class="sic semo" aria-hidden="true">${esc(c.icon)}</span>` : `<span class="sic" aria-hidden="true"><span class="sw" style="${cssColor(c.color) ? 'background:' + cssColor(c.color) : ''}"></span></span>`;
const BUDGET_TXT = {ok: N_('within budget'), warn: N_('80 % of the budget used'), over: N_('over budget')};
const fmtHours = sec => fmtNum(sec / 3600, 1) + ' h';
const monthLabel = m => { if (!m) return ''; try { const d = new Date(m + '-01T12:00:00'); return isNaN(d) ? '' : d.toLocaleDateString(LOCALE(), {month: 'long', year: 'numeric'}); } catch { return ''; } }; // 2.46.2 (#1472): no 'Invalid Date'

// ---- the sidebar: clients above the lists
function clientsSideHtml(onTasks) {
  if (!clientsOn()) return '';
  const cs = (S.clients || []).filter(c => !c.archived);
  const on = S.route.mod === 'clients';
  const rows = cs.map(c => `<button class="srow scl ${on && S.route.client === c.id ? 'on' : ''}" data-go="client/${c.id}">${clientIco(c)}<span class="n">${esc(cdn_label(c))}</span><span class="c">${c.lists.length || ''}</span></button>`).join('');
  const head = `<div class="shead sgh ${sideOpen('clients') ? '' : 'closed'}"><button class="sgt" data-act="side-group" data-g="clients" aria-expanded="${sideOpen('clients')}">${ic('chev', 's fcar')}<span>${esc(tr('Clients'))}</span>${!sideOpen('clients') && cs.length ? `<span class="c">${cs.length}</span>` : ''}</button><span class="spacer"></span><button data-go="clients" class="${on && !S.route.client ? 'on' : ''}" title="${esc(tr('All clients'))}" aria-label="${esc(tr('All clients'))}">${ic('brief', 's')}</button><button data-act="client-new" title="${esc(tr('New client'))}" aria-label="${esc(tr('New client'))}">${ic('plus', 's')}</button></div>`;
  return `<div class="sgroup sg-clients">${head}${sideOpen('clients') ? rows || `<button class="srow" data-act="client-new">${ic('plus')}<span class="n">${tr('Add your first client')}</span></button>` : ''}</div>`;
}

// ---- the view: all clients / one client
async function clLoad() {
  const seq = ++CLV.seq, id = S.route.client || null;
  CLV.loading = true;
  const q = CLV.month ? `?month=${CLV.month}` : '';
  try { const j = await api('GET', id ? `/api/clients/${id}${q}` : `/api/clients${q}`); if (seq === CLV.seq) { CLV.data = j; CLV.id = id; } }
  catch { if (seq === CLV.seq) { CLV.data = {error: true}; CLV.id = id; } }
  CLV.loading = false;
  if (S.route.mod === 'clients' && seq === CLV.seq) { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, mg_wrap('clients', viewClients()))); }
}
const clReload = () => { CLV.data = null; ms_clDirty(); if (S.route.mod === 'clients') ms_clDraw(); };  // 2.47.3 (#1734): the page loads what it shows
function budgetBar(c) {
  const b = c.budget || {}, st = c.stats || {};
  if (!b || b.level === 'none') return '';
  const pc = Math.max(b.pct_h ?? 0, b.pct_amount ?? 0);
  const txt = [c.budget_h ? tr('{0} of {1} h', fmtNum(st.rounded / 3600, 1), fmtNum(c.budget_h, 1)) : '', c.budget_amount ? tr('{0} of {1}', fmtMoney(st.amount), fmtMoney(c.budget_amount)) : ''].filter(Boolean).join(' · ');
  return `<div class="clbud lv-${b.level}"><div class="clbar" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.min(100, pc)}" aria-label="${esc(tr('Budget used'))}"><i style="width:${Math.min(100, pc)}%"></i></div><span class="clbt"><b>${pc} %</b> ${esc(txt)} · ${esc(tr(BUDGET_TXT[b.level]))}</span></div>`;
}
function viewClients() {
  if (!clientsOn()) return `<div class="empty">${tr('Clients are off (Settings > Modules)')}</div>`;
  return ms_clView();  // 2.47.3 (#1734): list + card like the contacts (clientpage.js) instead of the grid / the detail page
}
function clientsGridHtml(cs) {
  if (!cs.length) return `<div class="dash clients"><div class="empty nempty eact">${ic('brief')}<span>${tr('Clients sit above your lists: hours, budget and the timesheet per client. Only people of your organisation see them.')}</span><button class="btn pri" data-act="client-new">${ic('plus', 's')} ${tr('New client')}</button></div></div>`;
  return `<div class="dash clients"><div class="clhead"><span class="spacer"></span><button class="btn sm" data-act="client-new">${ic('plus', 's')} ${tr('New client')}</button></div><div class="dgrid">${cs.map(c => `<section class="dcard clcard"><h2>${clientIco(c)}<a href="#client/${c.id}">${esc(c.name)}</a><span class="spacer"></span><span class="dcn">${c.lists.length || ''}</span></h2>
    ${c.contact || c.email ? `<p class="muted clsub">${esc([c.contact, c.email].filter(Boolean).join(' · '))}</p>` : ''}
    <div class="clnums"><span><b>${esc(fmtHours(c.stats.month_seconds))}</b><small>${esc(monthLabel(c.stats.month))}</small></span><span><b>${esc(fmtHours(c.stats.seconds))}</b><small>${tr('in total')}</small></span>${c.stats.amount ? `<span><b>${esc(fmtMoney(c.stats.amount))}</b><small>${tr('amount')}</small></span>` : ''}</div>
    ${budgetBar(c)}</section>`).join('')}</div></div>`;
}
// 2.55.0 (#1067): the parts of the client's card below its details (blocks of the view builder, clientpage.js)
function clientDetailParts(c) {
  const st = c.stats, est = st.estimate_min;
  const lists = (c.per_list || []).map(p => { const l = listById(p.id); return `<tr><td><a href="#l/${p.id}">${esc(l ? lname(l) : p.name)}</a></td><td class="n">${p.estimate_min ? esc(fmtH(p.estimate_min)) : '–'}</td><td class="n">${esc(hmm(p.seconds))}</td><td class="n">${p.estimate_min ? `<span class="${p.seconds / 60 > p.estimate_min ? 'over' : ''}">${Math.round(100 * p.seconds / 60 / p.estimate_min)} %</span>` : ''}</td><td class="n">${p.amount ? esc(fmtMoney(p.amount)) : ''}</td></tr>`; }).join('');
  const mon = c.stats.month;
  return {
    month: `<div class="clmon"><button class="iconbtn" data-act="client-month" data-d="-1" aria-label="${esc(tr('Previous month'))}" title="${esc(tr('Previous month'))}">${ic('left', 's')}</button><b>${esc(monthLabel(mon))}</b><button class="iconbtn" data-act="client-month" data-d="1" aria-label="${esc(tr('Next month'))}" title="${esc(tr('Next month'))}">${ic('right', 's')}</button></div>
      <div class="sttiles"><div><b>${esc(hmm(st.month_seconds))}</b><span>${esc(monthLabel(mon))}</span><small>${st.month_amount ? esc(fmtMoney(st.month_amount)) : ''}</small></div>
        <div><b>${esc(hmm(st.seconds))}</b><span>${tr('in total')}</span><small>${st.amount ? esc(fmtMoney(st.amount)) : ''}</small></div>
        <div><b>${est ? esc(fmtH(est)) : '–'}</b><span>${tr('estimated')}</span><small>${esc(trn('{0} task with an estimate', '{0} tasks with an estimate', st.estimated))}</small></div>
        <div><b>${st.open}</b><span>${tr('open')}</span><small>${esc(tr('{0} done', st.done))}</small></div></div>
      ${budgetBar(c)}
      <div class="clacts"><button class="btn pri" data-act="client-sheet" data-id="${c.id}" ${timeOn() ? '' : 'disabled'}>${ic('file', 's')} ${tr('Timesheet {0}', monthLabel(mon))}</button>
        <a class="btn" href="/api/time/export.csv?${esc(clientTimeQuery(c, mon))}" download ${timeOn() && c.lists.length ? '' : 'hidden'}>${ic('download', 's')} CSV</a>
        <a class="btn" href="/api/time/export.xlsx?${esc(clientTimeQuery(c, mon))}" download ${timeOn() && c.lists.length ? '' : 'hidden'}>${ic('download', 's')} ${tr('Excel (XLSX)')}</a></div>`,
    lists: `<section class="stcard"><div class="sthead"><h3>${tr('Lists and projects')}</h3><span class="muted">${tr('estimate vs. actual')}</span></div>
      ${lists ? `<table class="ttable cltable"><thead><tr><th>${tr('List')}</th><th class="n">${tr('Estimate')}</th><th class="n">${tr('Actual')}</th><th class="n">%</th><th class="n">${tr('Amount')}</th></tr></thead><tbody>${lists}</tbody></table>`
        : `<p class="muted">${tr('No list yet: open a list’s settings and choose this client.')}</p>`}</section>`,
    note: c.note ? `<section class="stcard"><div class="sthead"><h3>${tr('Note')}</h3></div><div class="md">${renderMd(c.note)}</div></section>` : ''};
}
function clientDetailHtml(c, inCard) {  // 2.47.3 (#1734): inCard = the lower part of the client's card (clientpage.js)
  const pt = clientDetailParts(c);
  const addr = [c.contact, c.email ? `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : '', c.phone ? `<a href="tel:${esc(c.phone)}">${esc(c.phone)}</a>` : ''].filter(Boolean);
  return `<div class="${inCard ? 'msclstats' : 'dash clients'} cldetail">
    ${inCard ? '' : `<div class="clhead">${clientIco(c)}<h2>${esc(cdn_label(c))}</h2>${c.org_name ? `<span class="muted">${esc(c.org_name)}</span>` : ''}<span class="spacer"></span>
      <button class="btn sm" data-act="client-edit" data-id="${c.id}">${ic('edit', 's')} ${tr('Edit')}</button></div>`}
    ${!inCard && (addr.length || cdn_addrLine(c)) ? `<p class="clsub">${addr.join(' · ')}${cdn_addrLine(c) ? `<br><span class="muted cladr">${esc(cdn_addrLine(c))}</span>` : ''}</p>` : ''}
    ${!inCard && (c.contacts || []).length > 1 ? `<ul class="clklist" role="list" aria-label="${esc(tr('Contact persons'))}">${c.contacts.map(k => `<li><b>${esc(k.name)}</b>${k.role ? ` <span class="muted">${esc(k.role)}</span>` : ''}${k.is_default ? ` <span class="rotag">${tr('Default')}</span>` : ''}${k.email ? ` · <a href="mailto:${esc(k.email)}">${esc(k.email)}</a>` : ''}${k.phone ? ` · <a href="tel:${esc(k.phone)}">${esc(k.phone)}</a>` : ''}</li>`).join('')}</ul>` : ''}
    ${pt.month}
    ${pt.lists}
    ${pt.note}
    ${clm_histHtml(c)}
  </div>`;
}
function clientTimeQuery(c, mon) {
  const f = mon + '-01', t = monthEnd(f);
  return new URLSearchParams({from: f, to: t, scope: 'all', lists: (c.lists || []).join(',') || '-1'}).toString();
}
function clientSheet(c) {  // the time view of the client's month, then its printable timesheet
  const mon = c.stats.month, f = mon + '-01';
  S.tv.period = 'custom'; S.tv.from = f; S.tv.to = monthEnd(f); S.tv.scope = 'all'; S.tv.client = c.id; S.tv.key = '';
  S.tv.sheetNext = true;
  go('time');
}

// ---- the client dialog
function clientModal(c, o = {}) {  // 2.80.0 (#1842): o.org_id (the office's area, null = private), o.stay (no jump to the client)
  if (c && typeof loadModule === 'function') loadModule('ofundo').catch(() => {});  // 2.111.0 A (#2233): "Saved · Undo" after the save
  const md = modal(`<h3>${c ? tr('Edit client') : tr('New client')}</h3>
    <div class="row"><label for="cl-name">${tr('Name')}</label><input id="cl-name" maxlength="80" value="${esc(c?.name || '')}" autocomplete="organization"></div>
    <div class="row"><label for="cl-nx">${tr('Name addition')}</label><input id="cl-nx" maxlength="120" value="${esc(c?.name_extra || '')}" autocomplete="off" placeholder="${esc(tr('optional'))}" aria-describedby="cl-nx-h"></div>
    <div class="shint lhint keep" id="cl-nx-h">${tr('Printed as its own line under the name, e.g. the legal form or the partners.')}</div>
    ${o.quick ? '' : `<div class="row"><label for="cl-dname">${tr('Display name (optional)')}</label><input id="cl-dname" maxlength="80" value="${esc(c?.display_name || '')}" autocomplete="off" aria-describedby="cl-dname-h"></div>
    <div class="shint lhint keep" id="cl-dname-h">${tr('Shown in pickers and lists, not on the invoice.')}</div>`}
    ${o.quick ? cdn_addrHtml({}) : `<div class="row"><label for="cl-icon">${tr('Symbol')}</label><input id="cl-icon" maxlength="8" class="numin" value="${esc(c?.icon || '')}" placeholder="🏢"></div>
    <div class="row clkrow"><label>${tr('Contact persons')}</label><div class="clk" id="cl-contacts"></div></div>
    <div class="row"><label for="cl-email">${tr('E-mail')}</label><input id="cl-email" type="email" maxlength="200" value="${esc(c?.email || '')}" autocomplete="email"></div>
    <div class="row"><label for="cl-phone">${tr('Phone')}</label><input id="cl-phone" type="tel" maxlength="60" value="${esc(c?.phone || '')}" autocomplete="tel"></div>
    ${cdn_addrHtml(c?.billing || {})}`}${o.quick ? '' : `
    ${timeOn() ? `<div class="row"><label for="cl-rate">${tr('Hourly rate')}</label><input id="cl-rate" inputmode="decimal" class="numin" value="${c?.rate != null ? esc(fmtNum(c.rate, 2)) : ''}" placeholder="${esc(tr('optional'))}"><span class="muted">${esc(S.settings.time_currency || '')} · ${tr('for lists without their own rate')}</span></div>
    <div class="row"><label for="cl-bh">${tr('Budget')}</label><span class="lacts"><input id="cl-bh" inputmode="decimal" class="numin" value="${c?.budget_h != null ? esc(fmtNum(c.budget_h, 2)) : ''}" placeholder="–" aria-label="${esc(tr('Budget in hours'))}"><span class="muted">h</span><input id="cl-ba" inputmode="decimal" class="numin" value="${c?.budget_amount != null ? esc(fmtNum(c.budget_amount, 2)) : ''}" placeholder="–" aria-label="${esc(tr('Budget as an amount'))}"><span class="muted">${esc(S.settings.time_currency || '€')}</span></span></div>
    <div class="shint lhint keep">${tr('At 80 % of the budget the bar turns amber, over 100 % red.')}</div>` : ''}
    <div class="row"><label for="cl-note">${tr('Note')}</label><textarea id="cl-note" rows="3" maxlength="4000">${esc(c?.note || '')}</textarea></div>
    ${typeof officeOn === 'function' && officeOn() ? ofxClientBillingHtml(c?.billing || {}) : ''}
    ${c ? `<div class="row"><label>${tr('Archive')}</label><label class="chkl"><input type="checkbox" id="cl-arch" ${c.archived ? 'checked' : ''}> ${tr('Archived (hidden from the sidebar)')}</label></div>` : ''}`}
    <div class="aerr" role="alert"></div>
    <div class="foot">${c?.can_delete ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${c ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('cldlg');
  clkInit(md, c);
  const close = fgModal(md);  // 2.40.0 (#1371): the client card asks before unsaved input is lost
  const num = v => v.trim() === '' ? null : v.trim().replace(',', '.');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        if (!await askConfirm(tr('Delete the client “{0}”?', c.name), tr('Its lists stay; they only lose the client.'), {ok: tr('Delete'), danger: true})) return;
        await api('DELETE', `/api/clients/${c.id}`); md.remove(); await load(); if (S.route.client === c.id) go('clients'); else render(); clReload(); return;
      }
      const v = s => $(s, md)?.value ?? '';  // 2.97.0 B (#1951): the quick dialog (a document's "Add client") has name + address only
      const body = o.quick ? {name: v('#cl-name'), name_extra: v('#cl-nx')} : {name: v('#cl-name'), name_extra: v('#cl-nx'), icon: v('#cl-icon'), contacts: clkValue(md), email: v('#cl-email'),
        phone: v('#cl-phone'), display_name: v('#cl-dname'), note: v('#cl-note')};  // 2.99.0 D (#2188): + name_extra
      if (!c && 'org_id' in o) body.org_id = o.org_id;
      if ($('#cl-rate', md)) Object.assign(body, {rate: num($('#cl-rate', md).value), budget_h: num($('#cl-bh', md).value), budget_amount: num($('#cl-ba', md).value)});
      if ($('#cl-arch', md)) body.archived = $('#cl-arch', md).checked;
      for (const el of md.querySelectorAll('[data-clb]')) if (!(el.dataset.clb === 'country' && !ctyValid(el.value) && el.value === (c?.billing?.country || ''))) body[el.dataset.clb] = el.dataset.clb === 'payment_terms_days' ? (el.value.trim() === '' ? null : +el.value.trim()) : el.value;
      let r, gone = false;
      try { r = await rawFetch(c ? 'PATCH' : 'POST', c ? `/api/clients/${c.id}` : '/api/clients', body); }
      catch (x) {
        // 2.81.0 (#1852): a linked contact was deleted elsewhere -> drop that link, save once more, tell the person
        if (x.data?.code !== 'contact_gone' || !body.contacts.some(k => k.contact_id === x.data.contact_id)) throw x;
        body.contacts = body.contacts.map(k => k.contact_id === x.data.contact_id ? {...k, contact_id: null} : k);
        r = await rawFetch(c ? 'PATCH' : 'POST', c ? `/api/clients/${c.id}` : '/api/clients', body);
        gone = true;
      }
      md.remove(); await load(); render(); clReload();
      if (gone || !(c && typeof oun_saved === 'function' && oun_saved('client:' + c.id, r.name))) toast(gone ? tr('The linked contact no longer exists; link removed.') : c ? tr('Saved') : tr('Added: {0}', r.name));  // 2.111.0 A (#2233)
      if (!c && !o.stay) go('client/' + r.id);
      if (o.done) await o.done(r);
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  setTimeout(() => { if (!isTouch()) $('#cl-name', md)?.focus(); }, 50);
}

// 2.40.0 (#1380): the contact persons of a client in its dialog -- name, function / department, e-mail, phone; one is the
// default (it fills "contact" and the attention line of new documents). Saved with the client as the whole list.
function clkInit(md, c) {
  const ks = (c?.contacts || []).map(k => ({...k}));
  if (!ks.length && c?.contact) ks.push({name: c.contact, role: '', email: '', phone: '', is_default: true});
  md._clk = ks;
  md._clId = c?.id || 0;  // 2.59.0 (#1735): the address book search needs a saved client (its organisation)
  clkDraw(md);
}
function clkRead(md) {
  for (const el of md.querySelectorAll('[data-clk]')) { const k = md._clk[+el.dataset.i]; if (k) k[el.dataset.clk] = el.type === 'radio' ? el.checked : el.value; }
}
function clkDraw(md) {
  const box = $('#cl-contacts', md); if (!box) return;
  const ks = md._clk;
  if (ks.length && !ks.some(k => k.is_default)) ks[0].is_default = true;
  const f = (i, k, label, v, mx, attrs = '') => `<label class="oimfl"><span>${esc(label)}</span><input data-clk="${k}" data-i="${i}" maxlength="${mx}" value="${esc(v || '')}" ${attrs}></label>`;
  box.innerHTML = ks.map((k, i) => `<div class="clkc"><div class="oimgrid">${f(i, 'name', tr('Name'), k.name, 120, 'autocomplete="off"')}${f(i, 'role', tr('Function or department'), k.role, 120)}${f(i, 'email', tr('E-mail'), k.email, 200, 'type="email" autocomplete="off"')}${f(i, 'phone', tr('Phone'), k.phone, 60, 'type="tel" autocomplete="off"')}</div>
    <div class="lacts"><label class="chkl"><input type="radio" name="cl-kdef" data-clk="is_default" data-i="${i}" ${k.is_default ? 'checked' : ''}> ${tr('Default')}</label>${ckl_html(md, k, i)}<span class="spacer"></span><button type="button" class="btn sm ghost" data-clk-rm="${i}" aria-label="${esc(tr('Remove {0}', k.name || tr('contact person')))}">${ic('trash', 's')} ${tr('Remove')}</button></div></div>`).join('')
    + `<button type="button" class="btn sm" data-clk-add>${ic('plus', 's')} ${tr('Add contact person')}</button>`;
  if (!box._clkOn) {
    box._clkOn = true;
    box.addEventListener('click', e => {
      const add = e.target.closest('[data-clk-add]'), rm = e.target.closest('[data-clk-rm]');
      if (ckl_click(md, e)) return;  // 2.59.0 (#1735): from the address book / unlink
      if (!add && !rm) return;
      clkRead(md);
      if (add) md._clk.push({name: '', role: '', email: '', phone: '', is_default: !md._clk.length});
      else md._clk.splice(+rm.dataset.clkRm, 1);
      clkDraw(md);
      if (add) $(`[data-clk="name"][data-i="${md._clk.length - 1}"]`, md)?.focus();
    });
    box.addEventListener('change', e => { if (e.target.dataset?.clk === 'is_default') { clkRead(md); } });
  }
}
function clkValue(md) {
  clkRead(md);
  return md._clk.filter(k => (k.name || '').trim()).map(k => ({...(k.id ? {id: k.id} : {}), name: k.name.trim(), role: (k.role || '').trim(), email: (k.email || '').trim(), phone: (k.phone || '').trim(), is_default: !!k.is_default, contact_id: k.contact_id || null}));
}
// 2.59.0 (#1735): a contact person linked to a contact of the address book -- "From the address book" searches the address
// books the server allows for this client (the organisation's, a freelancer's own) and copies name, function, e-mail and
// phone into the fields; the link is saved with the client (Cancel drops it again). Later changes of the contact do not follow.
function ckl_html(md, k, i) {
  if (k.contact_id) return `<span class="cklk" title="${esc(tr('Linked to a contact of the address book'))}">${ic('link', 's')} ${esc(tr('Linked'))}</span><button type="button" class="linkbtn" data-clk-unlink="${i}">${tr('Unlink')}</button>`;
  return md._clId && feat('contacts') ? `<button type="button" class="btn sm ghost" data-clk-pick="${i}">${ic('book', 's')} ${tr('From the address book')}</button>` : '';
}
function ckl_click(md, e) {
  const pk = e.target.closest('[data-clk-pick]'), un = e.target.closest('[data-clk-unlink]');
  if (un) { clkRead(md); const k = md._clk[+un.dataset.clkUnlink]; if (k) k.contact_id = null; clkDraw(md); return true; }
  if (!pk) return false;
  clkRead(md);
  ckl_pick(md, pk, +pk.dataset.clkPick);
  return true;
}
function ckl_pick(md, anchor, i) {
  const p = openPop(anchor, `<div class="ctpick cklpick"><div class="row"><input id="cklp-q" type="search" placeholder="${esc(tr('Search contacts'))}" aria-label="${esc(tr('Search contacts'))}" autocomplete="off"></div>
    <div class="ctpl" id="cklp-l" role="listbox" aria-label="${esc(tr('Contacts'))}"><div class="muted">${tr('Loading…')}</div></div></div>`);
  let seq = 0, items = [];
  const find = async q => {
    const s = ++seq;
    let j; try { j = await api('GET', `/api/clients/${md._clId}/book-contacts?q=${encodeURIComponent(q || '')}`); } catch { return; }
    if (s !== seq || !$('#cklp-l')) return;
    items = j.contacts;
    $('#cklp-l').innerHTML = items.length ? items.map(c => `<button type="button" role="option" class="ctrow" data-cklp="${c.id}">${ctAv(c)}<span class="ctn"><b>${esc(c.fn || c.org)}</b><small class="muted">${esc([c.title, c.email || c.phone, c.book].filter(Boolean).join(' · '))}</small></span></button>`).join('')
      : `<div class="muted">${esc(q ? tr('No contacts found') : tr('No contacts to choose from: only the address books of the organisation of the client can be linked (without an organisation: your own).'))}</div>`;
  };
  find('');
  p.oninput = e => { if (e.target.id === 'cklp-q') { clearTimeout(p._t); p._t = setTimeout(() => find(e.target.value.trim()), 180); } };
  p.onclick = e => {
    const b = e.target.closest('[data-cklp]'); if (!b) return;
    const c = items.find(x => x.id === +b.dataset.cklp), k = md._clk[i]; if (!c || !k) return;
    Object.assign(k, {contact_id: c.id, name: (c.fn || c.org || k.name).slice(0, 120), role: (c.title || k.role || '').slice(0, 120),
      email: (c.email || k.email || '').slice(0, 200), phone: (c.phone || k.phone || '').slice(0, 60)});
    closePop(); clkDraw(md);
  };
  setTimeout(() => { if (!isTouch()) $('#cklp-q')?.focus(); }, 30);
}

// ---- the list dialog: the client of the list, its forms
function listDlgTeamHtml(l, id) {
  if (!id || l.is_inbox) return '';
  const mng = ['owner', 'admin'].includes(l.role || 'owner');
  const cs = (S.clients || []).filter(c => !c.archived || c.id === l.client_id);
  let h = '';
  if (clientsOn() && (mng || l.client_id)) h += `<div class="row"><label for="l-client">${tr('Client')}</label><select id="l-client" data-lid="${id}" ${mng ? '' : 'disabled'}><option value="">${tr('None')}</option>${cs.map(c => `<option value="${c.id}" ${c.id === l.client_id ? 'selected' : ''}>${esc((c.icon ? c.icon + ' ' : '') + cdn_label(c))}</option>`).join('')}</select>${mng ? `<button type="button" class="btn sm" data-act="client-new">${ic('plus', 's')} ${tr('New client')}</button>` : ''}</div>`;
  if (formsOn() && mng) h += `<div class="row"><label>${tr('Forms')}</label><button type="button" class="btn sm" data-act="forms-open" data-lid="${id}">${ic('file', 's')} ${tr('Forms…')}</button><span class="muted">${tr('a link that creates tasks here')}</span></div>`;
  return h;
}
document.addEventListener('change', async e => {
  if (e.target.id !== 'l-client') return;
  const lid = +e.target.dataset.lid;
  const v = e.target.value ? +e.target.value : null;
  try { await api('PATCH', `/api/lists/${lid}`, {client_id: v}); await load(); render(); clReload(); toast(tr('Saved')); } catch { /* api() said it */ }
});

// ---- workload
async function wlLoad() {
  const seq = ++WLV.seq;
  WLV.loading = true;
  const q = new URLSearchParams({weeks: WLV.weeks, ...(WLV.start ? {start: WLV.start} : {}), ...(WLV.org ? {org: WLV.org} : {})});
  try { const j = await api('GET', '/api/workload?' + q); if (seq === WLV.seq) WLV.data = j; } catch { if (seq === WLV.seq) WLV.data = {error: true}; }
  WLV.loading = false;
  if (S.route.mod === 'workload' && seq === WLV.seq) { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, viewWorkload())); }
}
function viewWorkload() {
  if (WLV.tab === 'abs') return ab2_view();  // 2.50.0 (#1195): absences (absence.js)
  if (WLV.tab === 'dispo' && dp_on()) return dp_view();  // 2.50.0 (#1194): disposition (dispo.js)
  if (!WLV.data && !WLV.loading) setTimeout(wlLoad, 0);
  const d = WLV.data;
  if (!d) return `<div class="dash wload"><p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (d.error) return `<div class="dash wload"><div class="empty">${tr('The workload could not be loaded.')}</div></div>`;
  const wk = w => { const a = pd(w.start), b = pd(w.end); return `${a.toLocaleDateString(LOCALE(), {day: 'numeric', month: 'short'})} – ${b.toLocaleDateString(LOCALE(), {day: 'numeric', month: 'short'})}`; };
  const cell = (p, c, i) => {
    const h = c.minutes / 60, lv = c.level || 'none';
    const tip = tr('{0}: {1} of {2} h planned, {3}', p.display_name, fmtNum(h, 1), fmtNum(c.capacity_h ?? p.capacity_h, 1), trn('{0} task', '{0} tasks', c.tasks)) + (c.unestimated ? ' · ' + trn('{0} without an estimate', '{0} without an estimate', c.unestimated) : '')
      + (c.absent_days ? ' · ' + tr('Away: {0}', trn('{0} day', '{0} days', c.absent_days)) : '');  // 2.50.0 (#1195): the week's capacity after absences
    return `<td class="wlc lv-${lv}${c.absent_days ? ' ab2wl' : ''}"><button type="button" class="wlb" data-act="wl-cell" data-uid="${p.id}" data-w="${i}" ${c.tasks ? '' : 'disabled'} title="${esc(tip)}" aria-label="${esc(tip)}"><span class="wlbar"><i style="width:${Math.min(100, c.pct || 0)}%"></i></span><span class="wlt"><b>${fmtNum(h, 1)} h</b>${c.pct != null ? ` <small>${c.pct} %</small>` : ''}${c.unestimated ? ` <small class="muted">+${c.unestimated}</small>` : ''}</span></button></td>`;
  };
  const rows = d.people.map(p => `<tr><th scope="row"><span class="wlp">${av(p.id, p.display_name)}<span class="wln"><b>${esc(p.display_name)}</b><button type="button" class="linkbtn wlcap" data-act="wl-cap" data-uid="${p.id}" ${p.own || S.me?.is_admin ? '' : 'disabled'} title="${esc(tr('Hours per week'))}">${esc(tr('{0} h / week', fmtNum(p.capacity_h, 1)))}</button></span></span></th>${p.weeks.map((c, i) => cell(p, c, i)).join('')}<td class="wlc wlnd">${p.nodate.tasks ? `<button type="button" class="wlb" data-act="wl-cell" data-uid="${p.id}" data-w="nd"><span class="wlt">${esc(trn('{0} task', '{0} tasks', p.nodate.tasks))}</span></button>` : ''}</td></tr>`).join('');
  return `<div class="dash wload">${ab2_tabs('wl')}<div class="clhead"><span class="spacer"></span>
      ${d.orgs.length > 1 ? `<select id="wl-org" aria-label="${esc(tr('Organisation'))}">${d.orgs.map(o => `<option value="${o.id}" ${o.id === d.org_id ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>` : ''}
      <button class="iconbtn" data-act="wl-move" data-d="-1" aria-label="${esc(tr('Earlier'))}" title="${esc(tr('Earlier'))}">${ic('left', 's')}</button><button class="btn sm" data-act="wl-move" data-d="0">${tr('This week')}</button><button class="iconbtn" data-act="wl-move" data-d="1" aria-label="${esc(tr('Later'))}" title="${esc(tr('Later'))}">${ic('right', 's')}</button>
      <a class="btn sm" href="/api/workload/export.xlsx?${new URLSearchParams({weeks: WLV.weeks, ...(WLV.start ? {start: WLV.start} : {}), ...(WLV.org ? {org: WLV.org} : {})})}" download>${ic('download', 's')} ${tr('Excel (XLSX)')}</a></div>
    <p class="muted">${tr('Open tasks assigned to each person, by their planned start, else their due date (overdue ones count this week), with their duration as the estimate. Only what you can see.')}</p>
    <div class="wlwrap"><table class="wltable"><thead><tr><th scope="col">${tr('Person')}</th>${d.weeks.map(w => `<th scope="col">${esc(wk(w))}</th>`).join('')}<th scope="col">${tr('No date')}</th></tr></thead><tbody>${rows || `<tr><td colspan="${d.weeks.length + 2}" class="muted">${tr('Nobody to show.')}</td></tr>`}</tbody></table></div>
    <p class="muted wllegend"><span class="wlk lv-ok"></span>${tr('below 80 %')} <span class="wlk lv-warn"></span>${tr('80–100 %')} <span class="wlk lv-over"></span>${tr('over capacity')}</p></div>`;
}
async function wlCap(uid) {
  const p = WLV.data?.people.find(x => x.id === uid); if (!p) return;
  const v = await askPrompt(tr('Hours per week of {0}', p.display_name), fmtNum(p.capacity_h, 2), {body: tr('Empty = 5 × the hours per day of the server'), input: {placeholder: '40'}});
  if (v === null) return;
  try { await api('PUT', `/api/workload/capacity/${uid}`, {hours: v.trim() === '' ? null : v.trim().replace(',', '.')}); WLV.data = null; wlLoad(); } catch { /* api() said it */ }
}
function wlCellMenu(anchor, uid, w) {
  const p = WLV.data?.people.find(x => x.id === uid); if (!p) return;
  const c = w === 'nd' ? p.nodate : p.weeks[+w];
  const items = (c.ids || []).map(id => { const t = taskById(id); return t ? {label: t.title + (t.duration ? ` · ${fmtH(t.duration)}` : ''), icon: 'list', fn: () => openDetail(id)} : null; }).filter(Boolean);
  if (!items.length) { toast(tr('Only available online.')); return; }
  menu(anchor, items.slice(0, 30));
}

// ---- approvals (#463): a bar in the task panel
const APPROVAL_TXT = {pending: N_('Waiting for the approval of {0}'), approved: N_('Approved by {0}'), changes: N_('{0} asked for changes'), rejected: N_('Rejected by {0}')};
function approvalBar(t, ro) {
  if (!t?.approval || !collab()) return '';
  const who = t.approver_id === S.me?.id ? tr('you') : apName(t.approver_id);
  const mine = t.approval === 'pending' && t.approver_id === S.me?.id;
  const acts = mine ? `<span class="apacts"><button type="button" class="btn sm pri" data-act="ap-decide" data-k="approve" data-id="${t.id}">${thumbIc(true)} ${tr('Approve')}</button><button type="button" class="btn sm" data-act="ap-decide" data-k="changes" data-id="${t.id}">${ic('edit', 's')} ${tr('Ask for changes')}</button><button type="button" class="btn sm danger" data-act="ap-decide" data-k="reject" data-id="${t.id}">${thumbIc(false)} ${tr('Reject')}</button></span>`
    : t.approval === 'pending' && !ro ? `<button type="button" class="linkbtn" data-act="ap-cancel" data-id="${t.id}">${tr('Withdraw')}</button>`
      : t.approval === 'changes' && !ro && t.status === 0 ? `<button type="button" class="linkbtn" data-act="ap-request" data-id="${t.id}">${tr('Ask again')}</button>` : '';
  return `<div class="apbar ap-${t.approval}" role="status">${t.approval === 'approved' ? thumbIc(true) : t.approval === 'rejected' ? thumbIc(false) : ic('eye', 's')}<span class="apt">${esc(tr(APPROVAL_TXT[t.approval], who))}</span>${acts}</div>`;
}
const approvalChip = t => t?.approval === 'pending' && collab() ? `<span class="apchip" title="${esc(tr(APPROVAL_TXT.pending, apName(t.approver_id)))}">${ic('eye', 's')}${tr('Approval')}</span>` : '';
const apName = id => (S.lists.flatMap(l => l.members || []).find(m => m.user_id === id)?.name) || (S.lists.find(l => l.owner_id === id)?.owner_name) || (id === S.me?.id ? S.me.display_name : '?');
async function approvalRequest(id) {
  const t = taskById(id), l = t && listById(t.list_id); if (!t || !l) return;
  // 2.86.0 (N12): viewers cannot decide an approval, so they are not offered as approvers
  const ppl = [{id: l.owner_id, name: l.owner_name}, ...(l.members || []).filter(m => !m.agent && m.role !== 'view').map(m => ({id: m.user_id, name: m.name}))].filter((p, i, a) => p.id !== S.me?.id && a.findIndex(x => x.id === p.id) === i);
  if (!ppl.length) { toast(tr('Share the list first: the approver must be a person of the list')); return; }
  const md = modal(`<h3>${tr('Ask for approval')}</h3><p class="muted">${esc(t.title)}</p>
    <div class="row"><label for="ap-who">${tr('Who approves?')}</label><select id="ap-who">${ppl.map(p => `<option value="${p.id}" ${p.id === t.approver_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>
    <div class="row"><label for="ap-note">${tr('Note')}</label><textarea id="ap-note" rows="2" maxlength="2000" placeholder="${esc(tr('optional, e.g. by Friday'))}"></textarea></div>
    <div class="shint lhint keep">${tr('The task is assigned to them; they approve it (done), ask for changes (back to you) or reject it.')}</div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${ic('send', 's')} ${tr('Ask')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try { putTask(await api('POST', `/api/tasks/${id}/approval`, {action: 'request', approver_id: +$('#ap-who', md).value, note: $('#ap-note', md).value})); md.remove(); render(); if (S.sel === id) renderDetail(); toast(tr('Approval requested')); } catch { /* api() said it */ }
  });
}
async function approvalDecide(id, k) {
  let note = '';
  if (k !== 'approve') {
    const v = await askPrompt(k === 'changes' ? tr('What should change?') : tr('Why rejected?'), '', {body: tr('optional, the person who asked sees it'), input: {max: 2000}});
    if (v === null) return;
    note = v;
  }
  try { putTask(await api('POST', `/api/tasks/${id}/approval`, {action: k, note})); await load(); render(); if (S.sel === id) renderDetail(); toast({approve: tr('Approved'), changes: tr('Sent back for changes'), reject: tr('Rejected')}[k]); } catch { /* api() said it */ }
}

// ---- forms of a list (#463 / #341)
async function formsModal(lid) {
  // 2.102.0 C (#2208): the questions' part of the dialog (formq.js) loads with it
  let j; try { [j] = await Promise.all([api('GET', `/api/lists/${lid}/forms`), loadModule('formq', () => formsModal(lid))]); } catch { return; }
  const l = listById(lid), secs = S.sections.filter(s => s.list_id === lid);
  const row = f => `<div class="mrow fmrow ${f.live ? '' : 'off'}" data-fid="${f.id}"><span class="n"><b>${esc(f.title)}</b> <span class="muted">${esc(f.access === 'public' ? tr('anyone with the link') : tr('people of your organisation'))} · ${esc(trn('{0} sent', '{0} sent', f.count))}${f.live ? '' : ' · ' + esc(tr('off'))}</span></span>
    <button class="iconbtn" data-fm="copy" title="${esc(tr('Copy the link'))}" aria-label="${esc(tr('Copy the link of {0}', f.title))}">${ic('copy', 's')}</button><button class="iconbtn" data-fm="edit" title="${esc(tr('Edit form'))}" aria-label="${esc(tr('Edit {0}', f.title))}">${ic('edit', 's')}</button></div>`;
  const md = modal(`<div class="lhdr"><h3>${tr('Forms')} · ${esc(lname(l))}</h3><span class="spacer"></span><button class="iconbtn" data-m="close" aria-label="${tr('Close')}" title="${tr('Close')}">${ic('x')}</button></div>
    <p class="muted">${tr('A form is a link with a small page (subject, description, name, e-mail): what someone sends becomes a task in this list. Agents of the list sort it in.')}</p>
    <div class="members" id="fm-list">${j.forms.map(row).join('') || `<div class="muted mhint">${tr('No form yet.')}</div>`}</div>
    <div class="row"><button class="btn sm" data-fm="new">${ic('plus', 's')} ${tr('New form')}</button></div>`);
  const edit = f => {
    const ed = modal(`<h3>${f ? tr('Edit form') : tr('New form')}</h3>
      <div class="row"><label for="fm-title">${tr('Title')}</label><input id="fm-title" maxlength="120" value="${esc(f?.title || '')}" placeholder="${esc(tr('e.g. IT request, bug report'))}"></div>
      <div class="row"><label for="fm-intro">${tr('Intro')}</label><textarea id="fm-intro" rows="3" maxlength="2000">${esc(f?.intro || '')}</textarea></div>
      ${fq_dialogHtml(f)}
      <div class="row"><label for="fm-access">${tr('Who can send it')}</label><select id="fm-access"><option value="org">${tr('Signed-in people of your organisation')}</option><option value="public" ${f?.access === 'public' ? 'selected' : ''} ${j.public_links ? '' : 'disabled'}>${tr('Anyone with the link (no login)')}</option></select></div>
      ${secs.length ? `<div class="row"><label for="fm-sec">${tr('Section')}</label><select id="fm-sec"><option value="">${tr('None')}</option>${secs.map(s => `<option value="${s.id}" ${s.id === f?.section_id ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>` : ''}
      <div class="row"><label>${tr('E-mail')}</label><label class="chkl"><input type="checkbox" id="fm-email" ${f?.ask_email !== false ? 'checked' : ''} ${f?.portal ? 'disabled' : ''}> ${tr('Ask for an e-mail address (without login)')}</label></div>
      <div class="row"><label for="fm-ttype">${tr('Type of report')}</label><select id="fm-ttype"><option value="">${tr('None')}</option>${TTYPES.map(([k, n]) => `<option value="${k}" ${f?.ttype === k ? 'selected' : ''}>${tr(n)}</option>`).join('')}</select></div>
      <div class="row"><label>${tr('Attachment')}</label><label class="chkl"><input type="checkbox" id="fm-files" ${f?.files ? 'checked' : ''}> ${tr('Allow one file (at most 10 MB)')}</label></div>
      <div class="row"><label>${tr('Status link')}</label><label class="chkl"><input type="checkbox" id="fm-portal" ${f?.portal ? 'checked' : ''}> ${tr('The sender gets a link to the status')}</label></div>
      <p class="muted mhint frm-hint">${tr('Without login, the sender sees a link after sending and gets it by mail (e-mail becomes required). It shows only their report: title, status and the answers you send to them, never internal comments or your team.')}</p>
      ${f ? `<div class="row"><label>${tr('Status')}</label><label class="chkl"><input type="checkbox" id="fm-on" ${f.enabled ? 'checked' : ''}> ${tr('Open (accepts requests)')}</label></div>` : ''}
      ${f ? `<div class="row"><label>${tr('Link')}</label><input readonly value="${esc(f.url)}" aria-label="${esc(tr('Link'))}"><button type="button" class="btn sm" data-m="regen">${tr('New link')}</button></div>
      <div class="row qrrow"><label>${tr('QR code')}</label><button type="button" class="btn sm" data-m="qr">${ic('eye', 's')} ${tr('Show QR code')}</button></div>` : ''}
      <div class="aerr" role="alert"></div>
      <div class="foot">${f ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${f ? tr('Save') : tr('Create')}</button></div>`);
    // 2.63.0 (#1513): the status link goes by mail -> the e-mail field is on while it is
    fq_bind(ed, f);  // 2.98.0 B (#1954): the own questions (formq.js)
    $('#fm-portal', ed).addEventListener('change', e => { const m = $('#fm-email', ed); if (e.target.checked) m.checked = true; m.disabled = e.target.checked; });
    ed.addEventListener('click', async e => {
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
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-fm],[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    const f = j.forms.find(x => x.id === +b.closest('[data-fid]')?.dataset.fid);
    if (b.dataset.fm === 'new') edit(null);
    if (b.dataset.fm === 'edit' && f) edit(f);
    if (b.dataset.fm === 'copy' && f) { try { await navigator.clipboard.writeText(f.url); toast(tr('Copied')); } catch { toast(f.url, null, 8000); } }
  });
}
// a QR code made on the server (the forms' link: the sign-in link brings its own)
function qrModal(url, title, svg) {
  const md = modal(`<h3>${esc(title)}</h3><div class="qrbox">${svg ? `<img src="${esc(svg)}" alt="${esc(tr('QR code'))}" width="240" height="240">` : `<p class="muted">${esc(url)}</p>`}</div>
    <div class="row"><input id="qr-link" readonly value="${esc(url)}" aria-label="${esc(tr('Link'))}"><button type="button" class="btn" data-m="copy">${ic('copy', 's')} ${tr('Copy')}</button></div>
    <div class="foot"><span class="spacer"></span><button class="btn pri" data-m="close">${tr('Done')}</button></div>`);
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') md.remove();
    if (b.dataset.m === 'copy') { try { await navigator.clipboard.writeText(url); toast(tr('Copied')); } catch { $('#qr-link', md).select(); } }
  });
  if (!svg) api('POST', '/api/qr', {text: url}).then(j => { const box = $('.qrbox', md); if (box && j.qr) box.innerHTML = `<img src="${esc(j.qr)}" alt="${esc(tr('QR code'))}" width="240" height="240">`; }).catch(() => {});
}

// ---- #444: a sign-in link with its QR code (family members without e-mail)
async function signinLink(uid, name) {
  if (!await askConfirm(tr('A sign-in link for {0}?', name), tr('Opened on their device, it signs them in there without a password (once, within 7 days). An older link stops working.'), {ok: tr('Create link')})) return;
  try {
    const j = await api('POST', `/api/users/${uid}/signin-link`, {});
    qrModal(j.link, tr('Sign in: {0}', name), j.qr);
  } catch { /* api() said it */ }
}
// the page /#signin/<token>: signs in on this device
async function signinScreen(tok) {
  history.replaceState(null, '', location.pathname);
  const el = document.createElement('div');
  el.className = 'modal authscreen';
  el.innerHTML = `<div class="card"><div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b></div><p role="status">${tr('Signing in…')}</p></div>`;
  document.body.appendChild(el);
  $('#app')?.setAttribute('inert', '');
  try {
    const r = await fetch('/api/auth/link', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({token: tok})});
    const res = await r.json().catch(() => ({}));
    if (r.ok && res.ok) { location.replace('/'); return; }
    if (res.twofa) { await authTwofa(el, `<div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b></div>`, res.methods || ['totp']); return; }
    if (res.enrol) { await authEnrol(el, `<div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b></div>`); return; }  // 2.86.0 (N4): the admin's 2FA policy
    $('.card p', el).textContent = res.error || tr('Error {0}', r.status);
  } catch { $('.card p', el).textContent = tr('Server not reachable.'); }
  $('.card', el).insertAdjacentHTML('beforeend', `<button class="btn pri" type="button" data-au="login">${tr('To the login')}</button>`);
  el.addEventListener('click', e => { if (e.target.closest('[data-au="login"]')) location.replace('/'); });
}

// ---- clicks
document.addEventListener('click', async e => {
  const a = e.target.closest?.('[data-act^="client-"], [data-act^="wl-"], [data-act^="ap-"], [data-act="forms-open"]'); if (!a || a.disabled) return;
  e.preventDefault(); e.stopPropagation();
  const k = a.dataset.act, id = +a.dataset.id || 0;
  if (k === 'client-new') clientModal(null);
  else if (k === 'client-edit') { let c = CLV.data && CLV.data.id === id ? CLV.data : null; if (!c) { try { c = await api('GET', `/api/clients/${id}`); } catch { return; } } clientModal(c); }
  else if (k === 'client-month') { const cur = CLV.data?.stats?.month || today().slice(0, 7), d = pd(cur + '-01'); d.setMonth(d.getMonth() + +a.dataset.d); CLV.month = ds(d).slice(0, 7); clReload(); }
  else if (k === 'client-sheet') { let c = CLV.data && CLV.data.id === id ? CLV.data : null; if (!c) { try { c = await api('GET', `/api/clients/${id}${CLV.month ? '?month=' + CLV.month : ''}`); } catch { return; } } clientSheet(c); }
  else if (k === 'wl-move') { const d = +a.dataset.d; WLV.start = d === 0 ? null : addDays(WLV.data?.weeks?.[0]?.start || today(), 7 * d * WLV.weeks); WLV.data = null; wlLoad(); }
  else if (k === 'wl-cap') wlCap(+a.dataset.uid);
  else if (k === 'wl-cell') wlCellMenu(a, +a.dataset.uid, a.dataset.w);
  else if (k === 'ap-request') approvalRequest(id);
  else if (k === 'ap-decide') approvalDecide(id, a.dataset.k);
  else if (k === 'ap-cancel') { try { putTask(await api('POST', `/api/tasks/${id}/approval`, {action: 'cancel'})); render(); if (S.sel === id) renderDetail(); } catch { /* api() said it */ } }
  else if (k === 'forms-open') formsModal(+a.dataset.lid);
  else if (k === 'client-tvx') { S.tv.client = null; S.tv.key = ''; renderView(); }
});
document.addEventListener('change', e => { if (e.target.id === 'wl-org') { WLV.org = +e.target.value; WLV.data = null; wlLoad(); } });

// 2.36.2 (#1021, E): billing details of a client for office & finance (structured address, VAT ID, customer number, buyer
// reference, invoice e-mail, payment terms); folded away, the free address above stays
const OFX_CL_FIELDS = [['street', N_('Street'), 200], ['address_extra', N_('Address extra'), 200], ['zip', N_('Postcode'), 20], ['city', N_('City'), 120], ['country', N_('Country'), 2],
  ['vat_id', N_('VAT ID'), 20], ['customer_no', N_('Customer number'), 40], ['buyer_reference', N_('Buyer reference (e.g. routing ID)'), 60],
  ['email_invoice', N_('E-mail for invoices'), 200], ['payment_terms_days', N_('Payment terms (days)'), 3],
  ['peppol_id', N_('Peppol ID'), 90]];  // 2.154.0 B (#1960): e-invoices over the Peppol network
// 2.97.0 B (#1951): the address (street, extra line, postcode, city, country) stands in the form itself, the rest of the
// billing details below it; the free "Address" text is gone (the server keeps it in its column)
const CDN_ADDR = ['street', 'address_extra', 'zip', 'city', 'country'];
const cdn_fieldHtml = b => ([k, n, mx]) => (k === 'country' ? `<div class="row"><label for="clb-country-q">${esc(tr(n))}</label>${ctyField('clb-country', b.country, {attrs: 'data-clb="country"', label: tr(n)})}</div>` : `<div class="row"><label for="clb-${k}">${esc(tr(n))}</label><input id="clb-${k}" data-clb="${k}" maxlength="${mx}" value="${esc(b[k] ?? '')}" ${k === 'payment_terms_days' ? 'inputmode="numeric" class="numin"' : k === 'country' ? 'class="numin" autocapitalize="characters"' : k === 'email_invoice' ? 'type="email" autocomplete="off"' : ''}></div>`) + (typeof ofcII === 'function' ? ofcII('cl_' + k) : '');  // 2.40.0 (#1382): (i) of the terms
const cdn_addrHtml = b => `<div class="cdnaddr">${OFX_CL_FIELDS.filter(([k]) => CDN_ADDR.includes(k)).map(cdn_fieldHtml(b)).join('')}</div>`;
function ofxClientBillingHtml(b) {
  const rest = OFX_CL_FIELDS.filter(([k]) => !CDN_ADDR.includes(k));
  const filled = rest.some(([k]) => b[k] != null && b[k] !== '');
  return `<details class="clbill" ${filled ? 'open' : ''}><summary>${tr('Billing details')}</summary>${rest.map(cdn_fieldHtml(b)).join('')}</details>`;
}

// 2.66.0 B (#1835): the merges into a client (its detail / card): "Merged with X, Y - date, person" and Undo (30 days)
function clm_histHtml(c) {
  const hs = c.merges || [];
  if (!hs.length) return '';
  const row = h => `<li>${ic('collapse', 's')} <span>${esc(tr('Merged with {0}', h.merged.map(x => x.name).join(', ')))}<span class="muted"> – ${esc(fmtDateLoc((h.at || '').slice(0, 10)))}${h.by_name ? `, ${esc(h.by_name)}` : ''}${h.undone_at ? ` · ${tr('undone')}` : ''}</span></span>${h.undo === '' && h.can_undo ? `<button class="btn sm" data-clm-undo="${h.id}">${ic('undo', 's')} ${tr('Undo')}</button>` : ''}</li>`;
  return `<section class="stcard clmhist"><div class="sthead"><h3>${tr('History')}</h3></div><ul class="ctlinks">${hs.map(row).join('')}</ul></section>`;
}
async function clm_undo(rid) {
  let j; try { j = await rawFetch('POST', `/api/clients/merges/${rid}/undo`, {}); } catch (x) { toast(x.message || ''); return; }
  if (typeof ms_clAfter === 'function') await ms_clAfter(); else clReload();
  toast(j.target_gone ? tr('Merge undone. The client it went into was deleted since; the others are back.') : tr('Merge undone'));
}
document.addEventListener('click', e => {
  const b = e.target.closest('#view [data-clm-undo]'); if (!b) return;
  b.disabled = true; clm_undo(+b.dataset.clmUndo);
});
