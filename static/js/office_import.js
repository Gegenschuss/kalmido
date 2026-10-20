// Office & finance (2.39.1, #1182): "Import legacy data" -- the page office/import (Settings > Import legacy data) and the
// archive list in the documents tab. A spreadsheet (.xlsx) becomes a preview of clients (split addresses with reasons,
// duplicates), services and equipment; the person corrects, deselects and confirms. Old invoices / quotations (PDF) get
// their key data proposed from the file name and are archived unchanged. Every confirmed import is a run that can be
// undone while nothing builds on it. Org admins only (the server checks); members read the archive.
const OIM = {pv: null, busy: false, filter: '', arch: [], archBusy: false, runs: null, counter: null, clients: null, list: null, listLoading: false};
const OIM_ACTS = [['contact', N_('Add as contact person to the client')], ['new', N_('Add as new client')], ['merge', N_('Merge into the existing client')], ['skip', N_('Skip')]];
// 2.40.0 (#1380): the actions a duplicate offers (in the file: no merge; "contact person" only with a contact name)
const oimActs = c => OIM_ACTS.filter(([v]) => (v !== 'merge' || c.dup?.kind === 'existing') && (v !== 'contact' || (c.contact || '').trim()));
if (typeof fgWatch === 'function') fgWatch(() => !!OIM.pv || OIM.arch.some(x => !x.done));  // 2.40.0 (#1371): an open preview asks before the page closes

async function oimLoad() {
  try { const j = await api('GET', '/api/office/legacy/runs'); OIM.runs = j.runs || []; } catch (x) { OIM.runs = []; }
  try { OIM.counter = await api('GET', '/api/office/legacy/counter'); } catch { OIM.counter = null; }
  await fx8a_oimClients();
}
// 2.80.0 (#1836): the client choice is read again on every visit of the import page and whenever the clients change
// (core.js), not only once per page load -- a client created meanwhile was missing until a reload
// (review: a state refresh takes the clients of the state, no extra request; a visit of the page asks the server)
async function fx8a_oimClients(fromState) {
  const mine = a => (a || []).filter(c => !c.archived && (c.org_id || null) === pb_clOrg());
  if (fromState) OIM.clients = mine(S.clients);
  else try { const j = await api('GET', '/api/clients'); OIM.clients = mine(j.clients); } catch { OIM.clients = []; }
  ofcDraw();
}
window.addEventListener('hashchange', () => { if (/^#office\/import\b/.test(location.hash) && OIM.runs !== null) fx8a_oimClients(); });
const oimClientOpts = cur => [['', tr('no client')], ...(OIM.clients || []).map(c => [c.id, cdn_label(c)])].map(([v, n]) => `<option value="${esc(v)}" ${String(v) === String(cur ?? '') ? 'selected' : ''}>${esc(n)}</option>`).join('');

// ---- the page
function oimHtml() {
  if (!ofcAdmin()) return `<div class="empty">${ic('lock')}<span>${tr('Only an admin of this organisation can do this')}</span></div>`;
  if (OIM.runs === null && !OIM.loading) { OIM.loading = true; setTimeout(async () => { await oimLoad(); OIM.loading = false; }, 0); }
  setTimeout(oim_jump, 0);  // 2.122.3 A (#2335)
  const back = `<div class="ofcbar"><a class="btn sm" href="#office/settings">${ic('back', 's')} ${tr('Settings')}</a></div>`;
  return `<div class="oim">${back}<h3>${tr('Import legacy data')}</h3><p class="muted">${tr('Take over your clients, services and equipment from a spreadsheet and keep old invoices and quotations as an archive. You see everything before it is saved; every import can be undone.')}</p>
    <section class="oimsec" id="oim-master"><h4>${ic('list', 's')} ${tr('Master data from a spreadsheet')}</h4>
    <p class="muted">${tr('An .xlsx file with the sheets or tables Contacts (one address per cell), Services and Equipment.')}</p>
    <div class="lacts"><input type="file" id="oim-xlsx" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" hidden><button type="button" class="btn sm pri" data-oim="pick-xlsx" ${OIM.busy ? 'disabled' : ''}>${ic('upload', 's')} ${tr('Choose file')}</button>${OIM.busy ? `<span class="muted">${tr('Reading…')}</span>` : ''}</div>
    ${OIM.pv ? oimPreviewHtml() : ''}</section>${oim_moreHtml()}
    <section class="oimsec" id="oim-archive"><h4>${ic('archive', 's')} ${tr('Old invoices and quotations')}</h4>
    <p class="muted">${tr('PDF files are archived unchanged: never renumbered, never sent again, no e-invoice. Key data come from the file name; please add amount and payment.')}</p>
    <div class="lacts"><input type="file" id="oim-pdf" accept="application/pdf,.pdf" multiple hidden><button type="button" class="btn sm" data-oim="pick-pdf" ${OIM.archBusy ? 'disabled' : ''}>${ic('upload', 's')} ${tr('Choose PDF files')}</button></div>
    ${oimArchHtml()}</section>
    <section class="oimsec"><h4>${ic('hash', 's')} ${tr('Number counters')}</h4>${oimCounterHtml()}</section>
    <section class="oimsec"><h4>${ic('clock', 's')} ${tr('Import runs')}</h4>${oimRunsHtml()}</section></div>`;
}

// 2.122.3 A (#2335): one-off imports of other office areas live here too (their preview dialogs stay in their modules);
// every section has an anchor: #office/import/<area> scrolls there and marks it briefly
function oim_moreHtml() {
  return `<section class="oimsec" id="oim-fixed"><h4>${ic('trend', 's')} ${tr('Fixed costs from a spreadsheet')}</h4>
    <p class="muted">${tr('An .xlsx file with name, net amount and due month; you see a preview before anything is saved.')}</p>
    <div class="lacts"><a class="btn sm ghost" href="/api/office/fixed-costs/import/template" download>${ic('download', 's')}<span>${tr('Download template')}</span></a><button type="button" class="btn sm" data-rkf="fimp">${ic('upload', 's')}<span>${tr('Import from Excel')}</span></button></div></section>
    <section class="oimsec" id="oim-leads"><h4>${ic('target', 's')} ${tr('Leads from a CSV file')}</h4>
    <p class="muted">${tr('A CSV file with name, company, e-mail and phone; leads with an e-mail that is already there are skipped.')}</p>
    <div class="lacts"><button type="button" class="btn sm" data-lead="import">${ic('upload', 's')}<span>${tr('Import CSV')}</span></button></div></section>`;
}
function oim_jump() {
  const m = /^#office\/import\/(\w+)/.exec(location.hash); if (!m) return;
  const el = document.getElementById('oim-' + m[1]); if (!el) return;
  if (OIM.jumped !== location.hash) {  // once per visit; the mark survives the redraws of the next 1.5 s (the page loads its runs)
    OIM.jumped = location.hash; OIM.flashTo = Date.now() + 1500;
    el.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    setTimeout(() => document.getElementById('oim-' + m[1])?.classList.remove('oimflash'), 1500);
  }
  if (Date.now() < OIM.flashTo) el.classList.add('oimflash');
}
window.addEventListener('hashchange', () => { OIM.jumped = null; });

function oimPreviewHtml() {
  const p = OIM.pv, cl = p.clients || [];
  const unsure = cl.filter(c => c.flags?.length).length, dups = cl.filter(c => c.dup).length;
  const n = bk_areasOn(p).reduce((a, k) => a + (p[k] || []).filter(s => s.action !== 'skip').length, 0);  // 2.46.1 (#1557): only the areas switched on
  const f = OIM.filter;
  const chips = `<div class="seg wrap oimf" role="tablist">${[['', tr('All ({0})', cl.length)], ['unsure', tr('Unsure ({0})', unsure)], ['dup', tr('Duplicates ({0})', dups)]].map(([k, t]) => `<button type="button" role="tab" data-oim="filter" data-f="${k}" aria-selected="${f === k}" class="${f === k ? 'on' : ''}">${esc(t)}</button>`).join('')}</div>`;
  const rows = cl.map((c, i) => [c, i]).filter(([c]) => !f || (f === 'unsure' ? c.flags?.length : c.dup));
  const other = Object.entries(p.other || {}).filter(([, v]) => v);
  const otherNames = {staff: N_('Staff'), freelancer: N_('Freelancers')};
  return `<div class="oimpv">
    ${cl.length ? `${bk_areaHead(p, 'clients', tr('Clients'))}${bk_off(p, 'clients') ? '' : `${chips}<ul class="oimcards" role="list">${rows.map(([c, i]) => oimClientCard(c, i)).join('')}</ul>`}` : `<p class="muted">${tr('No sheet Contacts found.')}</p>`}
    ${sr_area(p, 'roles', tr('Freelancer roles'), s => [s.cost_day != null ? `${tr('Purchase')} ${ofcMoney(s.cost_day)}/${tr('Day|unit')}` : '', s.cost_hour != null ? `${ofcMoney(s.cost_hour)}/${tr('h|unit')}` : ''])}
    ${sr_area(p, 'crew', tr('Crew'), s => [s.name_en, s.rate_day != null ? `${ofcMoney(s.rate_day)}/${tr('Day|unit')}` : '', s.intext === 'intern' ? tr('internal') : tr('external')])}
    ${(p.services || []).length ? `${bk_areaHead(p, 'services', tr('Services'))}${bk_off(p, 'services') ? '' : `<ul class="oimcards" role="list">${p.services.map((s, i) => oimSimpleCard('services', s, i, s.name_de, [s.category, s.unit === 'percent' ? (s.daily_rate != null ? `${fmtNum(s.daily_rate, 2)} %` : '') : s.daily_rate != null ? `${ofcMoney(s.daily_rate)}/${tr('Day|unit')}` : '', s.unit !== 'percent' && s.hourly_rate != null ? `${ofcMoney(s.hourly_rate)}/${tr('h|unit')}` : '', s.intext === 'shooting' ? tr('Shoot') : ''])).join('')}</ul>`}` : ''}
    ${(p.equipment || []).length ? `${bk_areaHead(p, 'equipment', tr('Equipment'))}${bk_off(p, 'equipment') ? '' : `<ul class="oimcards" role="list">${p.equipment.map((s, i) => oimSimpleCard('equipment', s, i, s.name, [s.name_en, s.category, s.daily_rate != null ? `${ofcMoney(s.daily_rate)}/${tr('Day|unit')}` : ''])).join('')}</ul>`}` : ''}
    ${other.length ? `<p class="muted">${esc(tr('Not imported (Kalmido has no master data for them yet): {0}', other.map(([k, v]) => `${tr(otherNames[k] || k)} (${v})`).join(', ')))}</p>` : ''}
    <div class="foot stfoot oimfoot"><span class="aerr" role="alert"></span><span class="spacer"></span><button type="button" class="btn" data-oim="cancel">${tr('Cancel')}</button><button type="button" class="btn pri" data-oim="import" ${n && !OIM.busy ? '' : 'disabled'}>${esc(trn('Import {0} entry', 'Import {0} entries', n))}</button></div></div>`;
}

// 2.46.1 (#1557): every area (clients, services, equipment) has a switch "Take over" and "Skip all"; an area switched off
// folds away, is not sent and not checked (a later import of the same file with only the equipment needs no address work)
const BK_AREAS = ['clients', 'roles', 'crew', 'services', 'equipment'];  // 2.47.0 (#1649): + roles, crew
const bk_off = (p, k) => !!p.off?.[k];
const bk_areasOn = p => BK_AREAS.filter(k => (p[k] || []).length && !bk_off(p, k));
function bk_areaHead(p, k, title) {
  const list = p[k] || [], on = !bk_off(p, k), take = list.filter(s => s.action !== 'skip').length, allSkip = !take;
  return `<div class="oimarea ${on ? '' : 'off'}"><h4>${esc(title)} <span class="muted">${on ? esc(tr('{0} of {1}', take, list.length)) : esc(tr('not taken over'))}</span></h4><span class="spacer"></span>
    ${on && (!allSkip || list.some(x => bk_back(x) !== 'skip')) ? `<button type="button" class="btn sm ghost" data-oim="area-skip" data-area="${k}">${esc(allSkip ? tr('Take over all') : tr('Skip all'))}</button>` : ''}
    <label class="chkl swl"><span class="swc"><input type="checkbox" role="switch" data-oim-area="${k}" ${on ? 'checked' : ''}><span class="swt" aria-hidden="true"></span></span><span>${esc(tr('Take over'))}</span></label></div>`;
}
const bk_back = x => x.was && x.was !== 'skip' ? x.was : x.dup ? sr_fillAct(x) : 'new';  // a duplicate stays skipped unless it was chosen before
function bk_skipAll(k) {  // "Skip all" of an area (and back: every row gets the action it had before, a duplicate its proposal)
  const list = OIM.pv?.[k] || [], any = list.some(s => s.action !== 'skip');
  for (const x of list) {
    if (any) { if (x.action !== 'skip') { x.was = x.action; x.action = 'skip'; } }
    else x.action = bk_back(x);
  }
  ofcDraw();
}

function oimClientCard(c, i) {
  const on = c.action !== 'skip';
  const fld = (k, label, mx, cls = '') => `<label class="oimfl ${cls}"><span>${esc(label)}</span><input data-oim-c="${i}" data-k="${k}" value="${esc(c[k] || '')}" maxlength="${mx}" ${on ? '' : 'disabled'}></label>`;
  const dup = c.dup ? `<p class="oimdup">${ic('copy', 's')} ${esc(c.dup.kind === 'existing' ? tr('Already a client: {0}', c.dup.name) : tr('Twice in the file (row {0})', c.dup.row))}</p>
    <select data-oim-act="${i}" aria-label="${esc(tr('What to do'))}">${oimActs(c).map(([v, n]) => `<option value="${v}" ${c.action === v ? 'selected' : ''}>${esc(tr(n))}</option>`).join('')}</select>` : '';
  return `<li class="oimcard ${on ? '' : 'off'} ${c.flags?.length ? 'warn' : ''}"><div class="oimhd"><label class="chkl"><input type="checkbox" data-oim-on="c" data-i="${i}" ${on ? 'checked' : ''}> <b>${esc(c.name || tr('(no name)'))}</b></label><span class="muted">${tr('row {0}', c.row)}</span></div>
    ${c.reasons?.length ? `<p class="oimwarn">${ic('alert', 's')} ${esc(c.reasons.join(' · '))}</p>` : ''}${dup}
    <div class="oimgrid">${fld('name', tr('Company'), 80, 'w2')}${fld('contact', tr('Contact person'), 120, 'w2')}${fld('street', tr('Street'), 200, 'w2')}${fld('zip', tr('Postcode'), 20)}${fld('city', tr('City'), 120)}<div class="oimfl"><span>${esc(tr('Country'))}</span>${ctyField('oim-cty-' + i, c.country, {attrs: `data-oim-c="${i}" data-k="country"`, dis: on ? '' : 'disabled', label: tr('Country')})}</div></div>
    <details class="oimraw"><summary>${tr('Original text')}</summary><pre>${esc(c.address || '')}</pre></details></li>`;
}

function oimSimpleCard(kind, s, i, title, sub) {
  const on = s.action !== 'skip';
  return `<li class="oimcard sm ${on ? '' : 'off'}"><div class="oimhd"><label class="chkl"><input type="checkbox" data-oim-on="${kind}" data-i="${i}" ${on ? 'checked' : ''}> <b>${esc(title)}</b></label>${s.dup ? `<span class="rotag">${tr('exists already')}</span>` : ''}</div><small class="muted">${esc(sub.filter(Boolean).join(' · '))}</small>${sr_fillHtml(kind, s, i)}</li>`;
}
// 2.47.0 (#1648): an existing entry with empty fields: "Fill empty fields" (the default) or "Skip"; the card says which
// fields get which value (the server decides again at the import and never overwrites a set value)
const SR_FILL_LABELS = {name_en: N_('Name (English)'), category: N_('Category'), sort: N_('Order'), daily_rate: N_('Daily rate'), hourly_rate: N_('Hourly rate'),
  raw_fee: N_('raw data'), producing: N_('producing'), role: N_('Freelancer role'), role_id: N_('Freelancer role'), cost_day: N_('Purchase per day'),
  cost_hour: N_('Purchase per hour'), rate_day: N_('Daily rate')};
const sr_fillAct = x => Object.keys(x.fill || {}).length ? 'fill' : 'skip';
function sr_fillHtml(kind, s, i) {
  if (!s.dup || !s.fill) return '';
  const f = Object.entries(s.fill).filter(([k]) => !(k === 'role_id' && 'role' in s.fill));
  if (!f.length) return `<p class="muted oimfill">${esc(tr('Nothing to fill: every field is set already'))}</p>`;
  const val = (k, v) => ['raw_fee', 'producing', 'sort'].includes(k) ? '' : ['daily_rate', 'hourly_rate', 'cost_day', 'cost_hour', 'rate_day'].includes(k) ? `: ${s.unit === 'percent' ? fmtNum(v, 2) + ' %' : ofcMoney(v)}` : `: ${v}`;
  return `<div class="oimfill"><select data-oim-sact="${kind}" data-i="${i}" aria-label="${esc(tr('What to do'))}"><option value="fill" ${s.action === 'fill' ? 'selected' : ''}>${esc(tr('Fill empty fields'))}</option><option value="skip" ${s.action === 'skip' ? 'selected' : ''}>${esc(tr('Skip'))}</option></select>
    <small class="muted">${esc(tr('Fills: {0}', f.map(([k, v]) => tr(SR_FILL_LABELS[k] || k) + val(k, v)).join(' · ')))}</small></div>`;
}
// 2.47.0 (#1649): the blocks Freelancer and Staff of the file = the areas roles and crew
const sr_area = (p, k, title, sub) => (p[k] || []).length ? `${bk_areaHead(p, k, title)}${bk_off(p, k) ? '' : `<ul class="oimcards" role="list">${p[k].map((s, i) => oimSimpleCard(k, s, i, s.name_de, sub(s))).join('')}</ul>`}` : '';

function oimArchHtml() {
  const a = OIM.arch;
  if (!a.length) return '';
  const kinds = [['invoice', tr('Invoice')], ['offer', tr('Quotation')]];
  const n = a.filter(x => !x.done).length;
  return `<ul class="oimcards" role="list">${a.map((x, i) => `<li class="oimcard ${x.done ? 'off' : ''} ${x.err || !x.sure || x.taken ? 'warn' : ''}"><div class="oimhd"><b>${esc(x.file_name)}</b>${x.done ? `<span class="rotag">${ic('check', 's')}${tr('Archived')}</span>` : `<button type="button" class="btn sm ghost" data-oim="arch-rm" data-i="${i}" aria-label="${esc(tr('Remove'))}">${ic('x', 's')}</button>`}</div>
    ${x.err ? `<p class="oimwarn">${ic('alert', 's')} ${esc(x.err)}</p>` : x.taken ? `<p class="oimwarn">${ic('alert', 's')} ${tr('This number is already used')}</p>` : !x.sure ? `<p class="oimwarn">${ic('alert', 's')} ${tr('File name not recognised: please check the fields')}</p>` : ''}
    <div class="oimgrid">
      <label class="oimfl"><span>${tr('Kind')}</span><select data-oim-a="${i}" data-k="kind" ${x.done ? 'disabled' : ''}>${kinds.map(([v, t]) => `<option value="${v}" ${x.kind === v ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>
      <label class="oimfl w2"><span>${tr('Number')}</span><input data-oim-a="${i}" data-k="number" value="${esc(x.number)}" maxlength="120" ${x.done ? 'disabled' : ''}></label>
      <div class="oimfl"><span>${tr('Date')}</span>${dateIn('oim-d-' + i, x.date || '', {label: tr('Date'), empty: tr('none'), ro: x.done, attrs: `data-oim-a="${i}" data-k="date"`})}</div>
      <label class="oimfl w2"><span>${tr('Client')}</span><select data-oim-a="${i}" data-k="client_id" ${x.done ? 'disabled' : ''}>${oimClientOpts(x.client_id)}</select></label>
      <label class="oimfl"><span>${tr('Amount')}</span><input data-oim-a="${i}" data-k="amount" value="${esc(x.amount ?? '')}" inputmode="decimal" class="numin" placeholder="${esc(x.kind === 'invoice' ? tr('gross') : tr('net'))}" ${x.done ? 'disabled' : ''}></label>
      <label class="chkl oimfl"><input type="checkbox" data-oim-a="${i}" data-k="paid" ${x.paid ? 'checked' : ''} ${x.done || x.kind !== 'invoice' ? 'disabled' : ''}> ${tr('Paid')}</label></div>${oimAddrHtml(x, i)}</li>`).join('')}</ul>
    <div class="foot stfoot oimfoot"><span class="spacer"></span><button type="button" class="btn" data-oim="arch-clear">${tr('Clear list')}</button><button type="button" class="btn pri" data-oim="arch-go" ${n && !OIM.archBusy ? '' : 'disabled'}>${OIM.archBusy ? esc(tr('Archiving…')) : esc(trn('Archive {0} document', 'Archive {0} documents', n))}</button></div>`;
}

// 2.40.0 (#1421): the recipient's address read from page 1 of the PDF and the proposals (each only with a tick)
function oimAddrHtml(x, i) {
  const r = x.addr;
  if (!r) return x.addrBusy ? `<p class="muted oimaddr">${tr('Reading the address…')}</p>` : '';
  if (r.status === 'no_text') return `<p class="muted oimaddr">${ic('info', 's')} ${tr('No text in the PDF (a scan?): the address is not read, there is no text recognition.')}</p>`;
  if (r.status === 'none') return `<p class="muted oimaddr">${ic('info', 's')} ${tr('No recipient address found on page 1.')}</p>`;
  if (r.status !== 'ok') return `<p class="muted oimaddr">${ic('info', 's')} ${tr('The PDF could not be read; the address stays empty.')}</p>`;
  const a = r.address || {}, dis = x.done ? 'disabled' : '';
  const line = [a.name, a.contact, a.street, [a.zip, a.city].filter(Boolean).join(' '), a.country].filter(Boolean).join(' · ');
  const box = (k, on, txt) => `<label class="chkl"><input type="checkbox" data-oim-p="${k}" data-i="${i}" ${on ? 'checked' : ''} ${dis}> ${esc(txt)}</label>`;
  return `<div class="oimaddr"><p><span class="muted">${tr('Address in the PDF')}:</span> ${esc(line)}</p>
    ${a.reasons?.length ? `<p class="oimwarn">${ic('alert', 's')} ${esc(a.reasons.join(' · '))}</p>` : ''}
    ${r.new_client ? box('new', x.pNew, tr('Create a new client: {0}', a.name)) : ''}
    ${r.add_contact ? box('contact', x.pContact, tr('Add as contact person to {1}: {0}', r.add_contact, r.client_name)) : ''}
    ${r.address_differs ? `<p class="muted">${ic('info', 's')} ${esc(tr('Address differs from the client card of {0}', r.client_name))}</p>` : ''}</div>`;
}
async function oimReadAddr(x) {
  x.addrBusy = true;
  const fd = new FormData(); fd.append('file', x.file, x.file_name); if (x.client_id) fd.append('client_id', x.client_id);
  try {
    const r = await fetch('/api/office/legacy/archive/address', {method: 'POST', body: fd, credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido'}});
    x.addr = r.ok ? await r.json() : {status: 'error'};
  } catch { x.addr = {status: 'error'}; }
  x.addrBusy = false;
  if (x.addr.status === 'ok') {
    x.pNew = !!x.addr.new_client && !x.addr.unsure; x.pContact = !!x.addr.add_contact && !x.addr.unsure;
    if (x.addr.client_id && !x.client_id) x.client_id = x.addr.client_id;
  }
}

function oimCounterHtml() {
  const c = OIM.counter;
  if (!c) return `<p class="muted">${tr('Loading…')}</p>`;
  return ['invoice', 'offer'].map(k => {
    const x = c[k];
    if (!x) return '';
    const name = k === 'invoice' ? tr('Invoices') : tr('Quotations');
    if (!x.highest) return `<p class="muted">${esc(name)}: ${esc(tr('next number {0}', x.next_now))}</p>`;
    const can = x.proposal > x.last;
    return `<div class="oimctr"><p><b>${esc(name)}</b>: ${esc(tr('highest number in the archive: {0} ({1})', x.highest, x.highest_number))}<br><span class="muted">${esc(tr('next number now: {0}', x.next_now))}</span></p>
      ${can ? `<button type="button" class="btn sm" data-oim="counter" data-kind="${k}" data-last="${x.proposal}">${esc(tr('Continue after the archive: next {0}', x.next_after))}</button>` : `<span class="muted">${tr('The counter already lies above the archive.')}</span>`}</div>`;
  }).join('');
}

// 2.46.1 (#1557): a data import with more than one area: undo one area alone ("Only undo the equipment"); an area undone shows so
const BK_UNDO = {clients: N_('Only undo the clients'), services: N_('Only undo the services'), equipment: N_('Only undo the equipment'),
  roles: N_('Only undo the freelancer roles'), crew: N_('Only undo the crew')};  // 2.47.0 (#1649)
const BK_UNDONE = {clients: N_('Clients undone'), services: N_('Services undone'), equipment: N_('Equipment undone'), roles: N_('Freelancer roles undone'), crew: N_('Crew undone')};
function bk_runAreas(x) {
  const a = Object.entries(x.areas || {});
  if (x.undone_at || a.length < 2) return '';
  return `<div class="oimrunareas">${a.map(([k, v]) => v.undone_at ? `<span class="rotag">${esc(tr(BK_UNDONE[k] || k))}</span>`
    : `<button type="button" class="btn sm ghost" data-oim="undo" data-id="${x.id}" data-kind="${k}">${ic('undo', 's')} ${esc(tr(BK_UNDO[k] || k))} <span class="muted">(${v.count})</span></button>`).join('')}</div>`;
}

function oimRunsHtml() {
  const r = OIM.runs;
  if (r === null) return `<p class="muted">${tr('Loading…')}</p>`;
  if (!r.length) return `<p class="muted">${tr('No imports yet.')}</p>`;
  const kn = {data: N_('Master data'), archive: N_('Archive|documents')};
  return `<ul class="ofclist" role="list">${r.map(x => `<li class="oimrun"><span class="ofcn"><b>${esc(tr(kn[x.kind] || x.kind))} · ${esc(trn('{0} entry', '{0} entries', x.total || 0))}</b><small class="muted">${esc([typeof ofdWhen === 'function' ? ofdWhen(x.created_at) : x.created_at, x.user_name].filter(Boolean).join(' · '))}</small></span>
    ${x.undone_at ? `<span class="rotag">${tr('undone')}</span>` : `<button type="button" class="btn sm" data-oim="undo" data-id="${x.id}">${ic('undo', 's')} ${tr('Undo')}</button>`}${bk_runAreas(x)}</li>`).join('')}</ul>`;
}

// ---- the archive in the documents tab (office_docs.js asks for it when the kind "Archive" is chosen)
async function oimLoadList() {
  if (OIM.listLoading) return;
  OIM.listLoading = true;
  try { OIM.list = await api('GET', '/api/office/legacy/archive'); } catch (x) { OIM.list = {items: [], error: x.message || tr('unknown')}; }
  OIM.listLoading = false;
  if (typeof ofdDraw === 'function') ofdDraw();
}
function oimArchiveListHtml(q) {
  if (!OIM.list) { setTimeout(oimLoadList, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  const items = (OIM.list.items || []).filter(r => (!q || [r.number, r.client, r.client_name, r.project].some(v => (v || '').toLowerCase().includes(q))) && (!OIM.cl || String(r.client_id) === OIM.cl));
  const sum = OIM.list.sum_invoices ? `<p class="muted oimsum">${esc(tr('Archived invoices: {0}, of which paid: {1}', ofcMoney(OIM.list.sum_invoices), ofcMoney(OIM.list.sum_paid)))}</p>` : '';
  const imp = ofcAdmin() ? `<a class="btn sm" href="#office/import/archive">${ic('upload', 's')} ${tr('Import legacy data')}</a>` : '';
  const sum0 = r81b_clFilter() + sum;  // 2.81.0 (#1834): the client filter above the list
  if (!items.length) return (OIM.cl ? sum0 : '') + `<div class="empty nempty eact">${ic('archive')}<span>${q || OIM.cl ? tr('Nothing matches.') : tr('No archived documents. Old invoices and quotations are added under Settings > Import legacy data.')}</span>${q ? '' : imp}</div>`;
  // 2.40.0 (#1366): the row shows the PDF in the browser, the button next to it downloads it
  return sum0 + `<ul class="ofclist ofdlist oimarch" role="list">${items.map(r => `<li><a class="ofcrow ofdrow" href="/api/office/legacy/archive/${r.id}/pdf" target="_blank" rel="noopener"${typeof pv_attr === 'function' ? pv_attr({url: `/api/office/legacy/archive/${r.id}/pdf`, name: (r.number || tr('Document')) + '.pdf', dlUrl: `/api/office/legacy/archive/${r.id}/pdf?download=1`}) : ''}>
    <span class="ofcn"><b>${esc(r.number || r.copy?.number || r.file_name)}${r.client || r.client_name ? ` · ${esc(r.client || r.client_name)}` : ''}</b><small class="muted">${esc([r.kind === 'offer' ? tr('Quotation') : tr('Invoice'), r.project, r.date ? fmtDateLoc(r.date) : ''].filter(Boolean).join(' · '))}</small></span>
    <span class="ofdsum"><b>${r.amount != null ? esc(ofcMoney(r.amount)) : ''}</b><small class="rotag">${ic('archive', 's')}${r.copy ? esc(oim_copyLabel(r.copy)) : tr('Archive|documents') + (r.kind === 'invoice' ? ' · ' + (r.paid ? tr('Paid') : tr('open')) : '')}</small></span>${ic('file', 's')}</a><a class="ib oimdl" href="/api/office/legacy/archive/${r.id}/pdf?download=1" download aria-label="${esc(tr('Download PDF'))}" title="${esc(tr('Download PDF'))}">${ic('download', 's')}</a>${r.copy ? '' : `<button type="button" class="ib oimdl" data-oim="arch-edit" data-id="${r.id}" aria-label="${esc(tr('Correct archived document'))}" title="${esc(tr('Correct archived document'))}">${ic('edit', 's')}</button>`}</li>`).join('')}</ul>` + `<div class="lacts">${imp}</div>`;
}

// 2.97.0 C (#2049): a read-only copy taken along by a move between offices (office/officemove.py): view and PDF only
const oim_copyLabel = cp => tr('Read-only copy from {0}', cp.from === 'private' ? tr('Private|workspace') : (cp.name || tr('Organisation')));

// ---- actions
async function oimPreview(file) {
  if (!file) return;
  OIM.busy = true; ofcDraw();
  const fd = new FormData(); fd.append('file', file);
  try {
    const r = await fetch('/api/office/legacy/preview', {method: 'POST', body: fd, credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido'}});
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    OIM.pv = j; OIM.filter = '';
  } catch (x) { toast(x.message || tr('unknown')); }
  OIM.busy = false; ofcDraw();
}
async function oimImport() {
  const p = OIM.pv; if (!p) return;
  const cl = (p.clients || []).map(c => ({row: c.row, name: c.name, contact: c.contact, street: c.street, zip: c.zip, city: c.city, country: (c.country || '').toUpperCase(), address: c.address,
    action: c.action, merge_id: (c.action === 'merge' || c.action === 'contact') && c.dup?.kind === 'existing' ? c.dup.id : undefined,
    contact_row: c.action === 'contact' && c.dup?.kind === 'file' ? c.dup.row : undefined}));
  // 2.87.9 (#1940): where the data goes, in words (the office of the shown workspace)
  if (!await importTargetConfirm({what: tr('the data of the file'), ws: ofcWs(), place: tr('Office')})) return;
  OIM.busy = true; ofcDraw();
  try {
    const areas = bk_areasOn(p), pick = k => areas.includes(k) ? (k === 'clients' ? cl : p[k] || []) : [];
    const j = await api('POST', '/api/office/legacy/import', {clients: pick('clients'), roles: pick('roles'), crew: pick('crew'), services: pick('services'), equipment: pick('equipment'), areas});
    const c = j.counts || {}, roles = (c.roles || 0) + (c.crew || 0), filled = ['services', 'equipment', 'roles', 'crew'].reduce((a, k) => a + (c[k + '_filled'] || 0), 0);
    toast(tr('Imported: {0} clients, {1} services, {2} devices', c.clients || 0, c.services || 0, c.equipment || 0) + (c.contacts ? ' · ' + trn('{0} contact person added', '{0} contact persons added', c.contacts) : '')
      + (roles ? ' · ' + trn('{0} role', '{0} roles', roles) : '') + (filled ? ' · ' + trn('{0} entry completed', '{0} entries completed', filled) : ''));  // 2.47.0 (#1648, #1649)
    OIM.pv = null; ofcReload('services'); ofcReload('equipment'); ofcReload('roles'); ofcReload('crew');
    if (c.clients && typeof load === 'function') await load();  // 2.80.0 (#1842): the documents' client field knows the imported clients
    await oimLoad();
  } catch (x) { const el = $('.oimpv .aerr'); if (el) el.textContent = x.message || ''; else toast(x.message || ''); }
  OIM.busy = false; ofcDraw();
}
async function oimPickPdf(files) {
  const fs = [...(files || [])];
  if (!fs.length) return;
  try {
    const j = await api('POST', '/api/office/legacy/archive/parse', {names: fs.map(f => f.name)});
    (j.items || []).forEach((x, i) => OIM.arch.push({...x, file: fs[i], amount: '', paid: x.kind === 'invoice' ? 1 : 0, done: false, err: '', addrBusy: true}));
  } catch (x) { toast(x.message || ''); }
  ofcDraw();
  for (const x of OIM.arch.filter(y => y.addrBusy && !y.addr)) { await oimReadAddr(x); ofcDraw(); }  // one after the other (the server reads one PDF per person at a time)
}
async function oimArchiveGo() {
  const todo = OIM.arch.filter(x => !x.done);
  if (!todo.length) return;
  OIM.archBusy = true; ofcDraw();
  let run;
  try { run = (await api('POST', '/api/office/legacy/archive/run')).run_id; } catch (x) { toast(x.message || ''); OIM.archBusy = false; ofcDraw(); return; }
  let ok = 0;
  for (const x of todo) {
    const fd = new FormData();
    fd.append('file', x.file, x.file_name);
    const amt = String(x.amount ?? '').trim().replace(/\s/g, '');
    for (const [k, v] of Object.entries({run_id: run, kind: x.kind, number: x.number, project_no: x.project_no, project: x.project, client_id: x.client_id || '', client_name: x.client_name, date: x.date, amount: amt, paid: x.paid ? 1 : 0})) fd.append(k, v ?? '');
    const ad = x.addr?.address;  // 2.40.0 (#1421): the ticked proposals
    if (ad && x.pNew && x.addr.new_client) fd.append('new_client', JSON.stringify({name: ad.name, contact: ad.contact, street: ad.street, zip: ad.zip, city: ad.city, country: ad.country}));
    if (x.pContact && x.addr?.add_contact) { fd.append('add_contact', x.addr.add_contact); if (!x.client_id) fd.set('client_id', x.addr.client_id || ''); }
    try {
      const r = await fetch('/api/office/legacy/archive', {method: 'POST', body: fd, credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido'}});
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.error || r.statusText);
      x.done = true; x.err = ''; ok++;
    } catch (e) { x.err = e.message || tr('unknown'); }
  }
  OIM.archBusy = false; OIM.list = null;
  toast(trn('{0} document archived', '{0} documents archived', ok));
  await oimLoad();
}

document.addEventListener('click', async e => {
  const b = e.target.closest?.('[data-oim]'); if (!b) return;
  const a = b.dataset.oim;
  if (a === 'pick-xlsx') { const i = $('#oim-xlsx'); if (i) { i.onchange = () => { oimPreview(i.files[0]); i.value = ''; }; i.click(); } }
  else if (a === 'pick-pdf') { const i = $('#oim-pdf'); if (i) { i.onchange = () => { oimPickPdf(i.files); i.value = ''; }; i.click(); } }
  else if (a === 'filter') { OIM.filter = b.dataset.f || ''; ofcDraw(); }
  else if (a === 'cancel') { OIM.pv = null; ofcDraw(); }
  else if (a === 'import') oimImport();
  else if (a === 'arch-rm') { OIM.arch.splice(+b.dataset.i, 1); ofcDraw(); }
  else if (a === 'arch-clear') { OIM.arch = []; ofcDraw(); }
  else if (a === 'arch-go') oimArchiveGo();
  else if (a === 'arch-edit') r81b_archEdit(+b.dataset.id);
  else if (a === 'counter') {
    try { await api('POST', '/api/office/legacy/counter', {kind: b.dataset.kind, last: +b.dataset.last}); toast(tr('Saved')); await oimLoad(); await ofcInfo(true); } catch (x) { toast(x.message || ''); }
  } else if (a === 'area-skip') bk_skipAll(b.dataset.area);
  else if (a === 'undo') {
    const kind = b.dataset.kind;  // 2.46.1 (#1557): one area only
    if (!await askConfirm(kind ? tr(BK_UNDO[kind]) + '?' : tr('Undo this import?'), kind ? tr('Only the entries of this area are removed, except what is in use by now. The rest of the import stays.') : tr('Everything it added is removed, except what is in use by now (a client with a quotation, a list or an archived document; a service in a document). Clients that were merged lose the fields the import filled in.'), {ok: tr('Undo'), danger: true})) return;
    try {
      const j = await api('POST', `/api/office/legacy/runs/${b.dataset.id}/undo`, kind ? {kinds: [kind]} : undefined);
      const k = j.kept || {}, kept = (k.clients || 0) + (k.services || 0) + (k.equipment || 0) + (k.roles || 0) + (k.crew || 0);
      toast(tr('Import undone') + (kept ? ' · ' + trn('{0} entry stays because it is in use', '{0} entries stay because they are in use', kept) : ''));
      OIM.list = null; ofcReload('services'); ofcReload('equipment'); ofcReload('roles'); ofcReload('crew'); await oimLoad();
    } catch (x) { toast(x.message || ''); }
  }
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.dataset?.oimArea && OIM.pv) { OIM.pv.off = {...OIM.pv.off, [t.dataset.oimArea]: !t.checked}; ofcDraw(); return; }  // 2.46.1 (#1557)
  if (t.dataset?.oimOn && OIM.pv) {
    const list = t.dataset.oimOn === 'c' ? OIM.pv.clients : OIM.pv[t.dataset.oimOn], x = list?.[+t.dataset.i];
    if (x) { if (!t.checked) { x.was = x.action; x.action = 'skip'; } else x.action = x.was && x.was !== 'skip' ? x.was : x.dup && Object.keys(x.fill || {}).length ? 'fill' : (x.dup && (x.contact || '').trim() ? 'contact' : 'new'); ofcDraw(); }
  } else if (t.dataset?.oimSact && OIM.pv) {  // 2.47.0 (#1648): fill / skip of an existing entry
    const x = OIM.pv[t.dataset.oimSact]?.[+t.dataset.i]; if (x) { x.action = t.value; ofcDraw(); }
  } else if (t.dataset?.oimAct && OIM.pv) {
    const x = OIM.pv.clients[+t.dataset.oimAct]; if (x) { x.action = t.value; ofcDraw(); }
  } else if (t.dataset?.oimP) {
    const x = OIM.arch[+t.dataset.i]; if (x) { if (t.dataset.oimP === 'new') x.pNew = t.checked; else x.pContact = t.checked; }
  } else if (t.dataset?.oimA) {
    const x = OIM.arch[+t.dataset.oimA]; if (!x) return;
    const k = t.dataset.k;
    x[k] = k === 'paid' ? (t.checked ? 1 : 0) : k === 'client_id' ? (+t.value || null) : t.value;
    if (k === 'kind' || k === 'number') { x.taken = false; ofcDraw(); }
  }
});
document.addEventListener('input', e => {
  const t = e.target;
  if (t.dataset?.oimC && OIM.pv) { const x = OIM.pv.clients[+t.dataset.oimC]; if (x) x[t.dataset.k] = t.value; }
  else if (t.dataset?.oimA && t.tagName === 'INPUT' && t.type !== 'checkbox') { const x = OIM.arch[+t.dataset.oimA]; if (x) x[t.dataset.k] = t.value; }
});

// ---- 2.81.0 (#1834): correct an archived document afterwards -- client, net + tax lines (Kalmido adds the gross), paid
// (invoices); number and PDF stay. Everybody who reads the archive may assign the client; amount and paid only an office
// admin (#1968, the server checks; members see them read-only); each save is one undo step and goes into the entry's
// history (shown folded in the dialog, a member's change marked "by member").
const R81B_TAX = [['19', '19 %'], ['7', '7 %'], ['0', '0 %'], ['rc', N_('Reverse charge')]];
const R81B_PCT = {19: 19, 7: 7, 0: 0, rc: 0};
function r81b_clFilter() {
  const seen = new Map();
  for (const r of OIM.list?.items || []) if (r.client_id && !seen.has(r.client_id)) seen.set(r.client_id, r.client || r.client_name || '#' + r.client_id);
  if (!seen.size && !OIM.cl) return '';
  const opts = [...seen].sort((a, b) => a[1].localeCompare(b[1])).map(([v, n]) => `<option value="${v}" ${String(v) === OIM.cl ? 'selected' : ''}>${esc(n)}</option>`).join('');
  return `<div class="ofcbar r81b-clf"><select id="oim-cl" aria-label="${esc(tr('Client'))}"><option value="">${esc(tr('All clients'))}</option>${opts}</select></div>`;
}
document.addEventListener('change', e => { if (e.target.id === 'oim-cl') { OIM.cl = e.target.value || ''; if (typeof ofdDraw === 'function') ofdDraw(); } });
const r81b_num = v => { const t = String(v ?? '').trim().replace(/\s|€/g, ''); if (!t) return null; const n = +(/,\d{1,2}$/.test(t) ? t.replace(/\./g, '').replace(',', '.') : t.replace(/,/g, '')); return Number.isFinite(n) ? n : NaN; };
const r81b_round = n => Math.round(n * 100) / 100;
function r81b_lineHtml(ln, i, n) {
  return `<div class="r81b-ln" data-i="${i}"><input class="numin" inputmode="decimal" data-r81b="net" value="${esc(ln.net != null && ln.net !== '' ? ofdNumIn(ln.net) : '')}" maxlength="16" aria-label="${esc(tr('Net'))}" placeholder="${esc(tr('Net'))}">
    <select data-r81b="tax" aria-label="${esc(tr('VAT rate'))}">${R81B_TAX.map(([v, t]) => `<option value="${v}" ${v === String(ln.tax) ? 'selected' : ''}>${esc(tr(t))}</option>`).join('')}</select>
    ${n > 1 ? `<button type="button" class="ib" data-r81b="rm" aria-label="${esc(tr('Remove'))}" title="${esc(tr('Remove'))}">${ic('x', 's')}</button>` : ''}</div>`;
}
function r81b_val(field, v) {
  if (field === 'paid') return v ? tr('Paid') : tr('open');
  if (field === 'client') return v ? v.name || '#' + v.id : tr('no client');
  if (!v || v.gross == null) return '–';
  return v.lines ? v.lines.map(l => `${ofcMoney(l.net)} ${l.tax === 'rc' ? tr('Reverse charge') : l.tax + ' %'}`).join(' + ') + ' = ' + ofcMoney(v.gross) : `${ofcMoney(v.gross)} (${tr('gross, tax unknown')})`;
}
async function r81b_archEdit(id) {
  let d;
  try { d = await api('GET', `/api/office/legacy/archive/${id}`); } catch (x) { toast(x.message || tr('unknown')); return; }
  if (OIM.clients === null && typeof fx8a_oimClients === 'function') await fx8a_oimClients(true);
  const cls = [...(OIM.clients || [])];
  if (d.client_id && !cls.some(c => c.id === d.client_id)) cls.push({id: d.client_id, name: d.client || '#' + d.client_id});
  let lines = d.tax_lines ? d.tax_lines.map(l => ({...l})) : [{net: '', tax: '19'}];
  const inv = d.kind === 'invoice', adm = d.admin !== false, lbl = {client: tr('Client'), amount: tr('Amount'), paid: tr('Paid')};
  const hist = (d.history || []).map(h => `<li><small class="muted">${esc([ofdWhen(h.at), h.user_name, h.by_member ? tr('by member') : ''].filter(Boolean).join(' · '))}</small><span>${esc(tr('{0}: {1} → {2}', lbl[h.field] || h.field, r81b_val(h.field, h.old), r81b_val(h.field, h.new)))}</span></li>`).join('');
  const body = `<p class="muted ofchint">${esc([d.kind === 'offer' ? tr('Quotation') : tr('Invoice'), d.number || d.file_name, d.date ? fmtDateLoc(d.date) : ''].filter(Boolean).join(' · '))}. ${esc(tr('Number and file stay unchanged.'))}</p>
    <div class="row"><label for="r81b-cl">${esc(tr('Client'))}</label><select id="r81b-cl">${[['', tr('no client')], ...cls.map(c => [c.id, c.name])].map(([v, n]) => `<option value="${esc(v)}" ${String(v) === String(d.client_id ?? '') ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></div>
    ${adm ? '' : `<div class="row"><span class="r81b-lbl">${esc(tr('Amount'))}</span><span>${esc(r81b_val('amount', {gross: d.amount, lines: d.tax_lines}))}</span></div>
    ${inv ? `<div class="row"><span class="r81b-lbl">${esc(tr('Paid'))}</span><span>${esc(r81b_val('paid', d.paid))}</span></div>` : ''}
    <p class="muted ofchint">${esc(tr('Only an admin of this organisation changes the amount and paid.'))}</p>`}
    ${adm ? `<div class="row"><span class="r81b-lbl">${esc(tr('Amount'))}</span>${!d.tax_lines && d.amount != null ? `<span class="muted ofchint">${esc(ofcMoney(d.amount) + ' (' + tr('gross, tax unknown') + ')')}</span>` : ''}
      <div id="r81b-lines"></div><button type="button" class="btn sm ghost" data-r81b="add">${ic('plus', 's')} ${esc(tr('Add tax rate'))}</button><p class="muted r81b-sum" id="r81b-sum" aria-live="polite"></p></div>
    ${inv ? `<label class="chkl r81b-paid"><input type="checkbox" id="r81b-paid" ${d.paid ? 'checked' : ''}> ${esc(tr('Paid'))}</label>` : ''}` : ''}
    <details class="r81b-hist"><summary>${esc(tr('History'))} (${(d.history || []).length})</summary>${hist ? `<ul role="list">${hist}</ul>` : `<p class="muted">${esc(tr('No changes yet.'))}</p>`}</details>`;
  const read = md => $$('.r81b-ln', md).map(el => ({net: $('[data-r81b="net"]', el).value, tax: $('[data-r81b="tax"]', el).value}));
  const paint = md => {
    const box = $('#r81b-lines', md); if (!box) return;  // a member: amount read-only
    box.innerHTML = lines.map((l, i) => r81b_lineHtml(l, i, lines.length)).join('');
    sum(md);
  };
  const sum = md => {
    const ls = read(md), nets = ls.map(l => r81b_num(l.net));
    const el = $('#r81b-sum', md);
    if (nets.some(n => n === null) && nets.every(n => n === null)) { el.textContent = ''; return; }
    if (nets.some(n => n === null || Number.isNaN(n))) { el.textContent = tr('Invalid value: {0}', tr('Net')); return; }
    const net = r81b_round(nets.reduce((a, b) => a + b, 0)), tax = r81b_round(ls.reduce((a, l, i) => a + r81b_round(nets[i] * R81B_PCT[l.tax] / 100), 0));
    el.textContent = tr('Net {0} + VAT {1} = gross {2}', ofcMoney(net), ofcMoney(tax), ofcMoney(r81b_round(net + tax)));
  };
  const md = ofdDlg(tr('Correct archived document'), body, tr('Save'), async m => {
    const ls = read(m), b = {}, old = {};
    const cid = $('#r81b-cl', m).value ? +$('#r81b-cl', m).value : null;
    if (cid !== (d.client_id || null)) { b.client_id = cid; old.client_id = d.client_id || null; }
    if (!adm) { /* a member: only the client (#1968) */ } else if (ls.some(l => String(l.net).trim())) {
      if (ls.some(l => !String(l.net).trim() || Number.isNaN(r81b_num(l.net)) || r81b_num(l.net) < 0)) throw new Error(tr('Invalid value: {0}', tr('Net')));
      const nl = ls.map(l => ({net: r81b_num(l.net), tax: l.tax}));
      if (JSON.stringify(nl) !== JSON.stringify((d.tax_lines || []).map(l => ({net: +l.net, tax: l.tax})))) {
        b.tax_lines = nl;
        if (d.tax_lines) old.tax_lines = d.tax_lines.map(l => ({net: l.net, tax: l.tax})); else old.amount = d.amount ?? '';
      }
    } else if (d.tax_lines) { b.amount = ''; old.tax_lines = d.tax_lines.map(l => ({net: l.net, tax: l.tax})); }  // all lines emptied: no amount
    if (inv && adm && $('#r81b-paid', m).checked !== !!d.paid) { b.paid = $('#r81b-paid', m).checked ? 1 : 0; old.paid = d.paid ? 1 : 0; }
    if (!Object.keys(b).length) return;
    const url = `/api/office/legacy/archive/${id}`, after = () => { OIM.list = null; if (typeof ofdDraw === 'function') ofdDraw(); return {}; };
    await api('PATCH', url, b);
    after();
    const name = d.number || d.file_name || '';
    offerUndo(tr('Saved'), histAdd({label: tr('Correct archived document') + (name ? ` “${name}”` : ''), undo: () => api('PATCH', url, old).then(after), redo: () => api('PATCH', url, b).then(after)}));
  });
  md.classList.add('r81b-dlg');
  paint(md);
  md.addEventListener('input', e => { if (e.target.dataset.r81b === 'net') sum(md); });
  md.addEventListener('change', e => { if (e.target.dataset.r81b === 'tax') sum(md); });
  md.addEventListener('click', e => {
    const b = e.target.closest('[data-r81b]'); if (!b || b.tagName === 'INPUT' || b.tagName === 'SELECT') return;
    lines = read(md);
    if (b.dataset.r81b === 'add') { lines.push({net: '', tax: lines.some(l => l.tax === '19') ? '7' : '19'}); paint(md); $$('[data-r81b="net"]', md).pop()?.focus(); }
    else if (b.dataset.r81b === 'rm') { lines.splice(+b.closest('.r81b-ln').dataset.i, 1); paint(md); }
  });
}
