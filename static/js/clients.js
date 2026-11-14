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
// 2.380.2 (#3407): the Einsatzplan follows the shown workspace: a company = that organisation (no picker), Private = not in
// the menus (one person, nothing to plan; a link or a notification still opens it), All = the picker as before
const wlWsOrg = () => { const ws = wsOn() ? wsCur() : 'all'; return ws.startsWith('org:') ? +ws.slice(4) : null; };
const wlOrg = () => wlWsOrg() || tm_want(null) || WLV.org;  // 2.543.0 (#4606): + the space open under "All"
const wlShown = () => workloadOn() && !(wsOn() && wsCur() === 'private');
if (typeof p61b_wsOn === 'function') p61b_wsOn('workload', after => { if (!after) return; WLV.data = null; if (S.route?.mod === 'workload' && WLV.tab === 'wl') wlLoad(); });
const formsOn = () => feat('forms');
const CLV = {data: null, id: null, loading: false, seq: 0, month: null};
const WLV = {data: null, start: null, weeks: 4, org: null, loading: false, seq: 0, tab: 'wl', wsp: ''};  // 2.543.0 (#4606): + wsp  // 2.50.0 (#1195, #1194): tab wl | abs | dispo
const clientById = id => (S.clients || []).find(c => c.id === id);
// 2.97.0 B (#1951): the name a client shows in pickers and lists: its display name, else its name ("name (city)" when two
// clients of one workspace share it, see team/clients.cdn_labels); documents keep the name. cdn_name: by id from S.clients
const cdn_label = c => !c ? '' : c.label || clientById(c.id)?.label || c.display_name || c.name || '';
const cdn_name = (id, name) => (id && clientById(id)?.label) || name || '';
const cdn_addrLine = c => { const b = c?.billing || {}; return [b.street, b.address_extra, [b.zip, b.city].filter(Boolean).join(' '), b.country].filter(Boolean).join(', '); };
// 2.1156.0 (#4280): the client dialog (clientModal) and the forms dialog of a list (formsModal) moved to clientdlg.js (loaded on demand, static/js/lazyload.js)
const clSymHtml = (v, cls = 's') => /^ic:[a-z]+$/.test(v || '') ? ic(v.slice(3), cls) : esc(v || '');
const clientIco = c => c.icon ? `<span class="sic ${c.icon.startsWith('ic:') ? '' : 'semo'}" aria-hidden="true">${clSymHtml(c.icon)}</span>` : `<span class="sic" aria-hidden="true"><span class="sw" style="${cssColor(c.color) ? 'background:' + cssColor(c.color) : ''}"></span></span>`;
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
async function clLoad(quiet) {  // 2.431.0 C (#3602): quietly for ms_clLive (no draw, a failure keeps the card)
  const seq = ++CLV.seq, id = S.route.client || null;
  CLV.loading = true;
  const q = CLV.month ? `?month=${CLV.month}` : '';
  try { const j = await api('GET', id ? `/api/clients/${id}${q}` : `/api/clients${q}`); if (seq === CLV.seq) { CLV.data = j; CLV.id = id; } }
  catch { if (seq === CLV.seq && !quiet) { CLV.data = {error: true}; CLV.id = id; } }
  CLV.loading = false;
  if (S.route.mod === 'clients' && seq === CLV.seq && !quiet) ms_clDraw();  // 2.431.0 C (#3598): the same draw (+ the columns' scroll)
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
  if (!clientsOn()) return `<div class="empty">${setLinkHtml(tr('Clients are off (Settings > Modules)'))}</div>`;
  return ms_clView();  // 2.47.3 (#1734): list + card like the contacts (clientpage.js) instead of the grid / the detail page
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
      <div class="clacts"><button class="btn pri" data-act="client-sheet" data-id="${c.id}" ${timeOn() ? '' : 'disabled'}>${ic('file', 's')} ${trh('Timesheet {0}', monthLabel(mon))}</button>
        <a class="btn" href="/api/time/export.csv?${esc(clientTimeQuery(c, mon))}" download ${timeOn() && c.lists.length ? '' : 'hidden'}>${ic('download', 's')} CSV</a>
        <a class="btn" href="/api/time/export.xlsx?${esc(clientTimeQuery(c, mon))}" download ${timeOn() && c.lists.length ? '' : 'hidden'}>${ic('download', 's')} ${tr('Excel (XLSX)')}</a></div>`,
    lists: `<section class="stcard"><div class="sthead"><h3>${tr('Projects')}</h3></div>
      ${lists ? `<table class="ttable cltable"><thead><tr><th>${tr('Project')}</th><th class="n">${tr('Estimate')}</th><th class="n">${tr('Actual')}</th><th class="n" title="${esc(tr('% of the estimate'))}"><span aria-hidden="true">%</span><span class="sr">${tr('% of the estimate')}</span></th><th class="n">${tr('Amount')}</th></tr></thead><tbody>${lists}</tbody></table>`
        : `<p class="muted">${tr('No project yet: open a project’s settings and select this client.')}</p>`}</section>`,
    note: c.note ? `<section class="stcard"><div class="sthead"><h3>${tr('Note')}</h3></div><div class="md">${renderMd(c.note)}</div></section>` : ''};
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

// 2.272.0 D (#3029): the text of a delete dialog from GET /api/clients/usage (u: null = unknown -> the general rule)
function cl_delText(u, n = 1) {
  const t = [u?.in_use === n ? tr('Clients used in quotations, invoices or contracts are archived instead. Their projects stay; they only lose the client.')
    : trashKeeps() ? tr('Deleted clients go to the trash and can be restored there.')  // 2.223.3 A (#2877): no period while nothing is deleted
    : trn('Deleted clients go to the trash and can be restored there for {0} day, then they are deleted permanently.', 'Deleted clients go to the trash and can be restored there for {0} days, then they are deleted permanently.', u?.trash_days || 30)];
  if (u?.in_use && u.in_use !== n) t.push(trn('{0} of them is used in quotations, invoices or contracts and is archived instead.', '{0} of them are used in quotations, invoices or contracts and are archived instead.', u.in_use));
  if (u?.text) t.push(tr('Linked: {0}.', u.text));
  return t.join(' ');
}
function clkRead(md) {
  for (const el of md.querySelectorAll('[data-clk]')) { const k = md._clk[+el.dataset.i]; if (k) k[el.dataset.clk] = el.type === 'radio' || el.type === 'checkbox' ? el.checked : el.value; }
}
function clkDraw(md) {
  const box = $('#cl-contacts', md); if (!box) return;
  const ks = md._clk;
  if (ks.length && !ks.some(k => k.is_default)) ks[0].is_default = true;
  const f = (i, k, label, v, mx, attrs = '') => `<label class="oimfl"><span>${esc(label)}</span><input data-clk="${k}" data-i="${i}" maxlength="${mx}" value="${esc(v || '')}" ${attrs}></label>`;
  box.innerHTML = ks.map((k, i) => `<div class="clkc"><div class="oimgrid">${f(i, 'name', tr('Name'), k.name, 120, 'autocomplete="off"')}${f(i, 'role', tr('Function or department'), k.role, 120)}${f(i, 'email', tr('E-mail'), k.email, 200, 'type="email" autocomplete="off"')}${f(i, 'phone', tr('Phone'), k.phone, 60, 'type="tel" autocomplete="off"')}</div>
    <div class="lacts"><label class="chkl"><input type="radio" name="cl-kdef" data-clk="is_default" data-i="${i}" ${k.is_default ? 'checked' : ''}> ${tr('Default')}</label>${clk_invOn() ? `<label class="chkl"><input type="checkbox" data-clk="gets_invoices" data-i="${i}" ${k.gets_invoices ? 'checked' : ''}> ${tr('Gets invoices')}</label>` : ''}${ckl_html(md, k, i)}<span class="spacer"></span><button type="button" class="btn sm ghost" data-clk-rm="${i}" aria-label="${esc(tr('Remove {0}', k.name || tr('contact person')))}">${ic('trash', 's')} ${tr('Remove')}</button></div></div>`).join('')
    + `<button type="button" class="btn sm" data-clk-add>${ic('plus', 's')} ${tr('Add contact person')}</button>`;
  box.dispatchEvent(new Event('change', {bubbles: true}));  // 2.552.0 (#4547): a row added / removed / linked is kept (fdDialog)
  if (!box._clkOn) {
    box._clkOn = true;
    box.addEventListener('click', e => {
      const add = e.target.closest('[data-clk-add]'), rm = e.target.closest('[data-clk-rm]');
      if (ckl_click(md, e)) return;  // 2.59.0 (#1735): from the address book / unlink
      if (!add && !rm) return;
      clkRead(md);
      if (add) md._clk.push({name: '', role: '', email: '', phone: '', is_default: !md._clk.length});
      else { const [k] = md._clk.splice(+rm.dataset.clkRm, 1); if (k?.id) md._clkRm.push(k.id); }
      clkDraw(md);
      if (add) $(`[data-clk="name"][data-i="${md._clk.length - 1}"]`, md)?.focus();
    });
    box.addEventListener('change', e => { if (e.target.dataset?.clk === 'is_default') { clkRead(md); } });
  }
}
// 2.433.0 (#3599): "Gets invoices" -- this contact person gets invoices and reminders in copy (with the office only)
const clk_invOn = () => typeof officeOn === 'function' && officeOn();
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
      : `<div class="muted">${esc(q ? tr('No contacts found') : tr('No contacts to select from: only the address books of the organisation of the client can be linked (without an organisation: your own).'))}</div>`;
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
function listDlgTeamHtml(l, id, part = '') {  // 2.352.0 C (#2751): part client | forms (the project dialog shows them apart)
  if (!id || l.is_inbox) return '';
  const mng = ['owner', 'admin'].includes(l.role || 'owner');
  const cs = (S.clients || []).filter(c => !c.archived || c.id === l.client_id);
  let h = '';
  if (part !== 'forms' && clientsOn() && (mng || l.client_id)) h += `<div class="row"><label for="l-client">${tr('Client')}</label><select id="l-client" data-lid="${id}" ${mng ? '' : 'disabled'}><option value="">${tr('None')}</option>${cs.map(c => `<option value="${c.id}" ${c.id === l.client_id ? 'selected' : ''}>${esc((c.icon && !c.icon.startsWith('ic:') ? c.icon + ' ' : '') + cdn_label(c))}</option>`).join('')}</select>${mng ? `<button type="button" class="btn sm" data-act="client-new">${ic('plus', 's')} ${tr('New client')}</button>` : ''}</div>`;
  if (part !== 'client' && formsOn() && mng) h += `<div class="row"><label>${tr('Forms')}</label><button type="button" class="btn sm" data-act="forms-open" data-lid="${id}">${ic('file', 's')} ${tr('Forms…')}</button></div><div class="shint lhint keep">${tr('a link that creates tasks here')}</div>`;  // 2.352.0 C (#2751): the hint under the button
  return h;
}
document.addEventListener('change', async e => {
  if (e.target.id !== 'l-client') return;
  const lid = +e.target.dataset.lid;
  const v = e.target.value ? +e.target.value : null;
  try { await api('PATCH', `/api/lists/${lid}`, {client_id: v}); await load(); render(); clReload(); savedTick('#l-client'); } catch { /* api() said it */ }  // 2.298.0 A1 (#3186): the quiet tick
});

// ---- workload
async function wlLoad() {
  const seq = ++WLV.seq;
  WLV.loading = true;
  const q = new URLSearchParams({weeks: WLV.weeks, ...(WLV.start ? {start: WLV.start} : {}), ...(wlOrg() ? {org: wlOrg()} : {})});
  WLV.wsp = tm_wsp();  // 2.543.0 (#4606): the space the rows belong to
  try { const j = await api('GET', '/api/workload?' + q); if (seq === WLV.seq) WLV.data = j; } catch { if (seq === WLV.seq) WLV.data = {error: true}; }
  WLV.loading = false;
  if (S.route.mod === 'workload' && seq === WLV.seq) { const el = $('#view'); if (el) keepFocus(el, () => setHtml(el, viewWorkload())); }
}
function viewWorkload() {
  if (WLV.tab === 'abs') return ab2_view();  // 2.50.0 (#1195): absences (absence.js)
  if (WLV.tab === 'dispo' && dp_on()) return dp_view();  // 2.50.0 (#1194): disposition (dispo.js)
  if (WLV.data && !WLV.loading && (WLV.wsp || '') !== tm_wsp()) WLV.data = null;  // 2.543.0 (#4606): another space opened
  if (!WLV.data && !WLV.loading) setTimeout(wlLoad, 0);
  const d = WLV.data;
  if (!d) return `<div class="dash wload"><p class="muted lempty">${tr('Loading…')}</p></div>`;
  if (d.error) return `<div class="dash wload"><div class="empty">${tr('The workload could not be loaded.')}</div></div>`;
  // 2.380.0 A (#3408): short two-line week heads (start above, "– end" below), never wider than the column
  const wd = x => pd(x).toLocaleDateString(LOCALE(), {day: 'numeric', month: 'numeric'});
  const wk = w => `<span class="wlw1">${esc(wd(w.start))}</span><span class="wlw2">– ${esc(wd(w.end))}</span>`;
  const cell = (p, c, i) => {
    const h = c.minutes / 60, lv = c.level || 'none';
    const tip = tr('{0}: {1} of {2} h planned, {3}', p.display_name, fmtNum(h, 1), fmtNum(c.capacity_h ?? p.capacity_h, 1), trn('{0} task', '{0} tasks', c.tasks)) + (c.unestimated ? ' · ' + trn('{0} without an estimate', '{0} without an estimate', c.unestimated) : '')
      + (c.absent_days ? ' · ' + tr('Away: {0}', trn('{0} day', '{0} days', c.absent_days)) : '');  // 2.50.0 (#1195): the week's capacity after absences
    return `<td class="wlc lv-${lv}${c.absent_days ? ' ab2wl' : ''}"><button type="button" class="wlb" data-act="wl-cell" data-uid="${p.id}" data-w="${i}" ${c.tasks ? '' : 'disabled'} title="${esc(tip)}" aria-label="${esc(tip)}"><span class="wlbar"><i style="width:${Math.min(100, c.pct || 0)}%"></i></span><span class="wlt"><b>${fmtNum(h, 1)} h</b>${c.pct != null ? ` <small>${c.pct} %</small>` : ''}${c.unestimated ? `<small class="muted wlun">${esc(trn('{0} without an estimate', '{0} without an estimate', c.unestimated))}</small>` : ''}</span></button></td>`;
  };
  const rows = d.people.map(p => `<tr><th scope="row"><span class="wlp">${av(p.id, p.display_name)}<span class="wln"><b>${esc(p.display_name)}</b><button type="button" class="linkbtn wlcap" data-act="wl-cap" data-uid="${p.id}" ${p.own || S.me?.is_admin ? '' : 'disabled'} title="${esc(tr('Hours per week'))}">${esc(tr('{0} h / week', fmtNum(p.capacity_h, 1)))}</button></span></span></th>${p.weeks.map((c, i) => cell(p, c, i)).join('')}<td class="wlc wlnd">${p.nodate.tasks ? `<button type="button" class="wlb" data-act="wl-cell" data-uid="${p.id}" data-w="nd"><span class="wlt">${esc(trn('{0} task', '{0} tasks', p.nodate.tasks))}</span></button>` : ''}</td></tr>`).join('');
  const th = tm_head(d);  // 2.543.0 (#4606)
  if (th?.ovr) return `<div class="dash wload">${ab2_tabs('wl')}${th.ovr}</div>`;
  return `<div class="dash wload">${ab2_tabs('wl')}${th?.crumb || ''}<div class="clhead"><span class="spacer"></span>
      ${d.orgs.length > 1 && !wlWsOrg() && !th ? `<select id="wl-org" aria-label="${esc(tr('Workspace'))}">${d.orgs.map(o => `<option value="${o.id}" ${o.id === d.org_id ? 'selected' : ''}>${esc(o.name)}</option>`).join('')}</select>` : ''}
      <button class="iconbtn" data-act="wl-move" data-d="-1" aria-label="${esc(tr('Earlier'))}" title="${esc(tr('Earlier'))}">${ic('left', 's')}</button><button class="btn sm" data-act="wl-move" data-d="0">${tr('This week')}</button><button class="iconbtn" data-act="wl-move" data-d="1" aria-label="${esc(tr('Later'))}" title="${esc(tr('Later'))}">${ic('right', 's')}</button>
      <a class="btn sm" href="/api/workload/export.xlsx?${new URLSearchParams({weeks: WLV.weeks, ...(WLV.start ? {start: WLV.start} : {}), ...(wlOrg() ? {org: wlOrg()} : {})})}" download>${ic('download', 's')} ${tr('Excel (XLSX)')}</a></div>
    <div class="muted wlnote">${tr('Only what you can see.')}<div class="shint">${tr('Open tasks assigned to each person, by their planned start, else their due date (overdue ones count this week), with their duration as the estimate.')}</div></div>
    <div class="wlwrap"><table class="wltable"><thead><tr><th scope="col">${tr('Person')}</th>${d.weeks.map(w => `<th scope="col" title="${esc(pd(w.start).toLocaleDateString(LOCALE(), {day: 'numeric', month: 'short'}) + ' – ' + pd(w.end).toLocaleDateString(LOCALE(), {day: 'numeric', month: 'short'}))}">${wk(w)}</th>`).join('')}<th scope="col">${tr('No date')}</th></tr></thead><tbody>${rows || `<tr><td colspan="${d.weeks.length + 2}" class="muted">${tr('Nobody to show.')}</td></tr>`}</tbody></table></div>
    <p class="muted wllegend"><span class="wlk lv-ok"></span>${tr('below 80 %')} <span class="wlk lv-warn"></span>${tr('80–100 %')} <span class="wlk lv-over"></span>${tr('over capacity')}</p></div>`;
}
async function wlCap(uid) {
  const p = WLV.data?.people.find(x => x.id === uid); if (!p) return;
  const v = await askPrompt(tr('Hours per week of {0}', p.display_name), fmtNum(p.capacity_h, 2), {body: tr('Empty = 5 × the hours per day of the server'), input: {placeholder: '40'}});
  if (v === null) return;
  try { await api('PUT', `/api/workload/capacity/${uid}`, {hours: numBody(v)}); WLV.data = null; wlLoad(); } catch { /* api() said it */ }
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
  if (!ppl.length) { toast(tr('Share the project first: the approver must be a person of the project')); return; }
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
    const post = sw => fetch('/api/auth/link', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({token: tok, switch: sw})});
    let r = await post(false), res = await r.json().catch(() => ({}));
    if (res.switch) {  // 2.190.0 A (#2496): another account is signed in on this device: ask before it is replaced
      if (!await askConfirm(tr('Sign in as {0}?', res.name), tr('{0} is signed in on this device. The link signs in {1} instead.', res.current, res.name), {ok: tr('Sign in')})) { location.replace('/'); return; }
      r = await post(true); res = await r.json().catch(() => ({}));
    }
    if (r.ok && res.ok) { location.replace('/'); return; }
    if (res.twofa) { await authTwofa(el, `<div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b></div>`, res.methods || ['totp']); return; }
    if (res.enrol) { await authEnrol(el, `<div class="alogo">${logoSvg(40)}<b>${wordSvg()}</b></div>`); return; }  // 2.86.0 (N4): the admin's 2FA policy
    $('.card p', el).textContent = res.error || httpErrText(r.status);
  } catch { $('.card p', el).textContent = tr('Server not reachable.'); }
  $('.card', el).insertAdjacentHTML('beforeend', `<button class="btn pri" type="button" data-au="login">${tr('Go to sign-in')}</button>`);
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
// ---- 2.149.0 F (#2518): absences, vacation and disposition (absence.js, leave.js, dispo.js) load on demand (lazyload.js module
// team). What the start needs stays here: the switch, the tabs of the workload view and their click, the kinds and the day
// hint of "Plan my day", the notification row; stand-ins draw the tabs' own "Loading…" and load the module
const dp_on = () => feat('dispo');
const AB2_KINDS = [['vacation', N_('Holiday')], ['sick', N_('Sick leave')], ['off', N_('Day off')], ['other', N_('Other absence')]];
const ab2_kindName = k => tr(AB2_KINDS.find(x => x[0] === k)?.[1] || 'Away');
// the tabs on top of the workload view: Workload | Absences | Disposition (2.50.0, #1194, when switched on)
function ab2_tabs(cur) {
  const t = (k, label) => `<button type="button" data-act="ab2-tab" data-v="${k}" class="${cur === k ? 'on' : ''}" aria-pressed="${cur === k}">${esc(tr(label))}</button>`;
  return `<div class="seg ab2tabs" role="group" aria-label="${esc(tr('Team'))}">${t('wl', N_('Workload'))}${t('abs', N_('Absences'))}${dp_on() ? t('dispo', N_('Disposition')) : ''}</div>`;
}
// ---- 2.543.0 (#4606): "All workspaces" with more than one area of the shown tab: Workload, Absences and Disposition show the
// overview of the areas (areas.js spo_html, like Knowledge and the file store) instead of a picker or silently one area; a tap
// opens #workload/s/<space> (the three tabs keep it), the path above it leads back. A workspace chosen = as before.
const tm_allOn = () => wsOn() && wsCur() === 'all';
const tm_wsp = () => tm_allOn() && S.route?.mod === 'workload' ? S.route.wsp || '' : '';
// the areas of a tab's answer: its organisations, for the absences also the personal area (Private)
const tm_rows = (d, priv) => [...(priv && d?.personal ? [['private', tr('Private|workspace'), wsIcon('private')]] : []), ...(d?.orgs || []).map(o => ['org:' + o.id, o.name, wsIcon('org:' + o.id)])];
// the area id to load for the open space (null = the server's choice); personal = the personal area's id once known
const tm_want = personal => { const w = tm_wsp(); return w === 'private' ? personal || null : /^org:\d+$/.test(w) ? +w.slice(4) : null; };
// the head of a tab under "All": {ovr} = the overview (no space open), {crumb} = the path back above the open one; null = as before
function tm_head(d, priv) {
  if (!tm_allOn()) return null;
  const rows = tm_rows(d, priv); if (rows.length < 2) return null;
  const open = rows.find(r => r[0] === tm_wsp());
  return open ? {crumb: spo_crumbHtml('workload', open[1])} : {ovr: spo_html('workload', rows)};
}
// "Plan my day" on a day away / a holiday: a hint instead of the proposal (the server leaves the proposal empty)
function ab2_dayHint(a) {
  if (!a) return '';
  const what = a.holiday ? tr('Public holiday: {0}', a.holiday) : a.half_day ? tr('You are away for half of this day ({0}).', ab2_kindName(a.kind)) : tr('You are away on this day ({0}). No plan is proposed.', ab2_kindName(a.kind));
  return `<div class="shint keep ab2hint" role="status">${ic('cal', 's')} ${esc(what)}</div>`;
}
document.addEventListener('click', e => {
  const a = e.target.closest?.('[data-act="ab2-tab"]'); if (!a || a.disabled) return;
  e.preventDefault(); e.stopPropagation();
  WLV.tab = a.dataset.v; const el = $('#view'); if (el) setHtml(el, viewWorkload());
});
window.ab2_view = () => { ld_later('team'); return `<div class="dash wload ab2">${ab2_tabs('abs')}<p class="muted lempty">${tr('Loading…')}</p></div>`; };
window.dp_view = () => { ld_later('team'); return `<div class="dash wload dp">${ab2_tabs('dispo')}<p class="muted lempty">${tr('Loading…')}</p></div>`; };
// assigning: the warning when the person is away (absence.js) - only where it can apply, so a solo user loads nothing
window.ab2_warnAssign = (uid, t) => { if (uid && collab() && (t?.due || t?.plan_start)) loadModule('team').then(() => ab2_warnAssign(uid, t), () => {}); };
// the notification row "leave" (account.js matrix): a new request (admins), the decision on my own
NOTIF_ROWS.push(['leave', N_('Holiday requests'), N_('admins: a new request; everybody: the decision on their own')]);
NM_NEWS_NEW.leave = 1; NM_PUSH.leave = 1;
