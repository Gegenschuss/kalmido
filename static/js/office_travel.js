// 2.47.3 (#1022, part B): travel expenses in the office (tab "Travel expenses", admins of the office area only). Trips with
// their receipts (Kalmido keeps no receipt images: they live in DATEV, only the tick "in DATEV" + an optional DATEV number),
// the receipts still missing the tick, an evaluation by month / year / person / project / client / category (CSV) and billing
// receipts on to a draft quotation / invoice (purchase = amount, never twice). Server: kalmido/office/travel.py.
const rk_dv = () => typeof ofcFeat !== 'function' || ofcFeat('books.datev');  // 2.147.0 (#2460): DATEV on in this office
const RK = {data: null, loading: false, err: null, year: String(new Date().getFullYear()), filter: 'all', person: '', open: null, view: 'trips', by: 'month', rep: null, sel: new Set(), gen: 0};
OFC_TABS.splice(OFC_TABS.findIndex(t => t[0] === 'settings'), 0, ['travel', 'plane', N_('Travel expenses'), 1, () => rk_travelHtml()]);  // admins only
const RK_BY = [['month', N_('Month')], ['year', N_('Year')], ['person', N_('Person')], ['project', N_('Project')], ['client', N_('Client')], ['category', N_('Category')], ['purpose', N_('Purpose')]];  // 2.117.0 A (#2292): + purpose
const rk_reload = () => { RK.data = null; RK.rep = null; RK.gen++; ofcDraw(); };  // CI of the train: gen = a load running during a reload is fetched again
const rk_cat = k => (RK.data?.categories || []).find(c => c.key === k)?.label || k;
const rk_home = () => RK.data?.currency || ofcCur();
const rk_amt = (n, cur) => !cur || cur === rk_home() ? ofcMoney(n) : `${fmtNum(+n, 2)} ${esc(cur)}`;
const rk_trip = id => (RK.data?.trips || []).find(t => t.id === id);
const rk_span = t => t.date_to && t.date_to !== t.date_from ? `${fmtDateLoc(t.date_from)} – ${fmtDateLoc(t.date_to)}` : fmtDateLoc(t.date_from);
const rk_client = id => cdn_label((RK.data?.clients || []).find(c => c.id === id));  // 2.97.0 B (#1951)
// 2.117.0 A (#2291): the person filter: key u<id> (a person of the office) | n:<name> (a free name), like the server's
const rk_pkey = p => p.id ? `u${p.id}` : `n:${(p.name || '').toLowerCase()}`;
const rk_pq = () => RK.person ? `&person=${encodeURIComponent(RK.person)}` : '';
function rk_persons() {  // the people of the office + the free names of the loaded trips (+ the chosen one), by name
  const m = new Map((RK.data?.people || []).map(p => [rk_pkey(p), p.name]));
  for (const t of RK.data?.trips || []) for (const p of t.people || []) if (!m.has(rk_pkey(p))) m.set(rk_pkey(p), p.name);
  if (RK.person && !m.has(RK.person)) m.set(RK.person, RK.personName || RK.person.replace(/^[un]:?/, ''));
  return [...m].sort((a, b) => a[1].localeCompare(b[1], LOCALE()));
}
function rk_personSel() {  // hidden when only one person occurs (a person without an organisation, alone)
  const ps = rk_persons(); if (ps.length < 2) return '';
  return `<select id="rk-person" class="rkperson" aria-label="${esc(tr('Person'))}"><option value="">${esc(tr('All people'))}</option>${ps.map(([k, n]) => `<option value="${esc(k)}" ${k === RK.person ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
}
const rk_purpose = t => [t.purpose === 'acquisition' ? tr('Acquisition / research') : t.purpose && t.purpose !== 'job' ? t.purpose : '', rk_client(t.client_id), t.project].filter(Boolean).join(' · ');

async function rk_load() {
  if (RK.loading) return;
  RK.loading = true; const gen = RK.gen;
  try { RK.data = await api('GET', '/api/office/trips' + (RK.year ? `?year=${RK.year}` : '')); RK.err = null; if (RK.person && rk_persons().length < 2) RK.person = ''; }
  catch (x) { RK.data = null; RK.err = x.message || tr('unknown'); }
  RK.loading = false;
  if (gen !== RK.gen) { RK.data = null; return rk_load(); }  // its answer can predate the change (approve right after save: the list stayed a draft)
  ofcDraw();
}
async function rk_loadReport() {
  const y = RK.year, q = `by=${RK.by}` + (y ? `&from=${y}-01-01&to=${y}-12-31` : '') + (RK.filter === 'missing' ? '&missing=1' : '') + rk_pq();
  try { RK.rep = Object.assign(await api('GET', '/api/office/trips/report?' + q), {q}); } catch (x) { RK.rep = {error: x.message || tr('unknown'), q}; }
  ofcDraw();
}

// ---- the tab
function rk_travelHtml() {
  if (RK.oid !== OFC.info?.org_id) Object.assign(RK, {oid: OFC.info?.org_id, data: null, rep: null, open: null, err: null, sel: new Set(), person: ''});  // another office area (2.117.0 A #2291: + the person filter)
  const lfo = window.lf_rkOpen;  // 2.173.0 A (#2680): from a trip (life.js), once the office of its area is loaded
  if (lfo && OFC.info?.org_id === lfo.office) { Object.assign(RK, {open: lfo.trip, view: 'trips', year: '', data: null}); window.lf_rkOpen = null; }
  if (!ofcAdmin()) return `<div class="empty">${tr('Only for admins of the office.')}</div>`;
  if (RK.err) return `<div class="empty">${esc(RK.err)}</div>`;
  if (!RK.data) { if (!RK.loading) setTimeout(rk_load, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (RK.open && rk_trip(RK.open)) return rk_tripHtml(rk_trip(RK.open));
  const views = `<div class="seg" role="group" aria-label="${esc(tr('View'))}">${[['trips', tr('Trips')], ['logbook', tr('Logbook')], ['report', tr('Evaluation')]].map(([k, n]) => `<button type="button" data-rk="view" data-v="${k}" class="${RK.view === k ? 'on' : ''}" aria-pressed="${RK.view === k}">${n}</button>`).join('')}</div>`;  // 2.93.0 B (#1928): the logbook
  if (RK.view === 'logbook') return `<div class="ofcbar rkbar">${views}</div>` + lbHtml();
  const y0 = new Date().getFullYear(), years = [y0 + 1, y0, y0 - 1, y0 - 2, y0 - 3].map(String);
  const miss = RK.data.missing || 0;
  if (!rk_dv()) RK.filter = 'all';  // 2.147.0 (#2460): without DATEV there is no "not in DATEV"
  const bar = `<div class="ofcbar rkbar"><select id="rk-year" aria-label="${esc(tr('Year'))}"><option value="">${tr('All years')}</option>${years.map(y => `<option ${y === RK.year ? 'selected' : ''}>${y}</option>`).join('')}</select>
    ${rk_dv() ? `<div class="seg" role="group" aria-label="${esc(tr('Show'))}"><button type="button" data-rk="filter" data-v="all" class="${RK.filter === 'all' ? 'on' : ''}" aria-pressed="${RK.filter === 'all'}">${tr('All')}</button><button type="button" data-rk="filter" data-v="missing" class="${RK.filter === 'missing' ? 'on' : ''}" aria-pressed="${RK.filter === 'missing'}">${tr('Not in DATEV')}${miss ? ` <span class="rkbadge">${miss}</span>` : ''}</button></div>` : ''}
    ${rk_personSel()}${views}
    <span class="spacer"></span><button class="btn sm pri" data-rk="new">${ic('plus', 's')}<span>${tr('New trip')}</span></button></div>`;
  return bar + (RK.view === 'report' ? rk_reportHtml() : rk_listHtml());
}
function rk_listHtml() {
  let trips = RK.data.trips || [];
  if (RK.filter === 'missing') trips = trips.filter(t => t.missing);
  if (RK.person) { trips = trips.filter(t => (t.people || []).some(p => rk_pkey(p) === RK.person)); if (!trips.length) return `<div class="empty nempty">${tr('No trips of this person.')}</div>`; }  // 2.117.0 A (#2291)
  if (!trips.length) return `<div class="empty nempty eact">${ic('plane')}<span>${RK.filter === 'missing' ? tr('Every receipt is ticked as in DATEV.') : tr('No trips yet. Add the first one with its receipts.')}</span>${RK.filter === 'missing' ? '' : rk_impBtn()}</div>`;
  const rec = (RK.data.trips || []).some(t => (t.items || []).length);  // 2.114.4 D (#2286): receipt column only when there are receipts
  return `<ul class="ofclist rklist" role="list">${trips.map(t => `<li><button type="button" class="ofcrow" data-rk="open" data-id="${t.id}"><span class="ofcn"><b>${esc(t.dest || tr('Trip'))}</b>
    <small class="muted">${esc([rk_span(t), rk_purpose(t), (t.people || []).map(p => p.name).join(', ')].filter(Boolean).join(' · '))}</small></span>
    ${t.missing && rk_dv() ? `<span class="rotag rkmiss">${esc(trn('{0} not in DATEV', '{0} not in DATEV', t.missing))}</span>` : ''}${rk_vmaCols(t, rec)}</button>${rk_rowBtn(t)}</li>`).join('')}</ul>`;
}
function rk_tripHtml(t) {
  const its = RK.filter === 'missing' ? t.items.filter(i => !i.datev) : t.items, ro = !!t.own_ro;  // 2.187.1 B (#2735): entered by somebody else for me: read only
  const head = `<div class="ofcbar"><button class="btn sm ghost" data-rk="back">${ic('back', 's')}<span>${tr('All trips')}</span></button><span class="spacer"></span>
    ${ro ? '' : `<button class="btn sm" data-rk="edit" data-id="${t.id}">${ic('edit', 's')}<span>${tr('Edit trip')}</span></button>`}</div>
    ${ro ? `<p class="muted ofchint">${ic('lock', 's')} ${esc(tr('This trip was entered by somebody else: you can read it, but not change it.'))}</p>` : ''}
    <div class="rkhead"><h3>${esc(t.dest || tr('Trip'))}</h3><p class="muted">${esc([rk_span(t), t.overnight ? tr('with overnight stay') : '', rk_purpose(t)].filter(Boolean).join(' · '))}</p>
    ${(t.people || []).length ? `<p class="muted">${esc(tr('Participants'))}: ${esc(t.people.map(p => p.name).join(', '))}</p>` : ''}${t.km ? `<p class="muted">${esc(tr('{0} km', fmtNum(+t.km, 0)))}</p>` : ''}${t.note ? `<p class="rknote">${esc(t.note)}</p>` : ''}</div>`;
  const rows = its.map(i => `<li class="rkit">${ro ? '' : `<label class="rksel"><input type="checkbox" data-rk="sel" data-id="${i.id}" ${RK.sel.has(i.id) ? 'checked' : ''} ${i.billed ? 'disabled' : ''} aria-label="${esc(tr('Select'))}"></label>`}
    <button type="button" class="ofcrow" ${ro ? 'disabled' : ''} data-rk="item" data-id="${i.id}"><span class="ofcn"><b>${esc(rk_cat(i.category))}${i.text ? ` · ${esc(i.text)}` : ''}</b><small class="muted">${esc([fmtDateLoc(i.date), i.currency !== rk_home() ? `${fmtNum(+i.amount, 2)} ${i.currency}` : '', i.datev_no ? tr('DATEV receipt no. {0}', i.datev_no) : ''].filter(Boolean).join(' · '))}</small></span>
    ${i.billed ? `<span class="rotag">${esc(tr('Billed on {0}', i.billed.number || tr('Draft')))}</span>` : ''}<span class="rksum">${ofcMoney(i.amount_home)}</span></button>
    ${rk_dv() && !ro ? `<label class="chkl rkdatev"><input type="checkbox" data-rk="datev" data-id="${i.id}" ${i.datev ? 'checked' : ''}> ${tr('in DATEV')}</label>` : ''}</li>`).join('');
  const nsel = t.items.filter(i => RK.sel.has(i.id) && !i.billed).length;
  return head + rk_vmaCard(t) + `<div class="ofcbar"><b>${tr('Receipts')}</b><span class="muted">${ofcMoney(t.total)}</span><span class="spacer"></span>
    ${nsel ? `<button class="btn sm" data-rk="bill">${ic('receipt', 's')}<span>${esc(trn('Bill {0} receipt on', 'Bill {0} receipts on', nsel))}</span></button>` : ''}
    ${ro ? '' : `<button class="btn sm pri" data-rk="add" data-id="${t.id}">${ic('plus', 's')}<span>${tr('Add receipt')}</span></button>`}</div>`
    + (rows ? `<ul class="ofclist rkits" role="list">${rows}</ul>${rk_dv() ? `<div class="shint">${tr('Receipts themselves stay in DATEV; tick them here once they are uploaded there.')}</div>` : ''}` : `<div class="empty nempty">${tr('No receipts yet.')}</div>`);
}
function rk_reportHtml() {
  const q = `by=${RK.by}` + (RK.year ? `&from=${RK.year}-01-01&to=${RK.year}-12-31` : '') + (RK.filter === 'missing' ? '&missing=1' : '') + rk_pq();
  if (!RK.rep || RK.rep.q !== q) { setTimeout(rk_loadReport, 0); return `<p class="muted lempty">${tr('Loading…')}</p>`; }
  if (RK.rep.error) return `<div class="empty">${esc(RK.rep.error)}</div>`;
  const by = `<div class="seg wrap" role="group" aria-label="${esc(tr('Sums by'))}">${RK_BY.map(([k, n]) => `<button type="button" data-rk="by" data-v="${k}" class="${k === RK.by ? 'on' : ''}" aria-pressed="${k === RK.by}">${tr(n)}</button>`).join('')}</div>`;
  const lab = g => RK.by === 'month' ? rk_month(g.label) : RK.by === 'category' ? rk_cat(g.key) : g.label;
  const rows = RK.rep.rows.map(g => `<tr><td>${esc(lab(g))}</td><td class="num muted">${g.count}</td><td class="num">${ofcMoney(g.amount)}</td></tr>`).join('');
  if (!RK.rep.count) return rk_vmaRepHtml();  // 2.114.4 D (#2286): no receipts in the period -> no receipts block
  return rk_vmaRepHtml() + `<div class="ofcbar">${by}<span class="spacer"></span><a class="btn sm" href="/api/office/trips/report?${esc(q)}&format=csv" download>${ic('download', 's')} CSV</a></div>`
    + (RK.rep.rows.length ? `<table class="rktab"><thead><tr><th>${tr(RK_BY.find(x => x[0] === RK.by)[1])}</th><th class="num">${tr('Receipts')}</th><th class="num">${tr('Amount')}</th></tr></thead><tbody>${rows}</tbody>
      <tfoot><tr><th>${tr('Total')}</th><th class="num">${RK.rep.count}</th><th class="num">${ofcMoney(RK.rep.total)}</th></tr></tfoot></table>${RK.by === 'person' || RK.person ? `<div class="shint">${tr('A receipt is shared equally between the participants of its trip.')}</div>` : ''}`
      : `<div class="empty nempty">${tr('No receipts in this period.')}</div>`);
}
// 2.117.0 A (#2287): the arrow of a trip row opens the row menu (like the quotations); a tap on the row still opens the trip
const rk_rowBtn = t => `<button type="button" class="iconbtn ofdrmore rkmore" data-rk="rowmore" data-id="${t.id}" aria-haspopup="menu" aria-label="${esc(tr('More'))}" title="${esc(tr('More'))}">${ic('chev', 's')}</button>`;
function rk_rowMenu(id, anchor) {
  const t = rk_trip(+id); if (!t) return;
  const label = t.dest || rk_span(t), adm = ofcAdmin(), can = adm && !t.own_ro;  // 2.187.1 B (#2735): own_ro = read only
  menu(anchor, [
    {label: tr('Open'), icon: 'eye', fn: () => { RK.open = t.id; RK.sel.clear(); ofcDraw(); }},
    can ? {label: tr('Edit trip'), icon: 'edit', fn: () => rk_tripModal(t)} : null,
    adm ? {label: tr('Duplicate'), icon: 'copy', fn: () => rk_dup(t)} : null,
    can && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom()) ? {label: tr('Move to another workspace…'), icon: 'brief',
      fn: () => ofm_move({what: 'travel', ids: [t.id], from: ofm_officeFrom(), label: qn(label), after: async () => { RK.open = null; rk_reload(); }})} : null,
    can ? '-' : null,
    can ? {label: tr('Delete'), icon: 'trash', cls: 'danger', fn: async () => {
      if (!await askConfirm(tr('Delete the trip “{0}” with its receipts?', label), '', {ok: tr('Delete'), danger: true})) return;
      try {
        const j = await api('DELETE', `/api/office/trips/${t.id}`); rk_reload();
        toast(tr('Deleted'), async () => { await api('POST', '/api/office/trips', j.trip); rk_reload(); });
      } catch (x) { toast(x.message || tr('unknown')); }
    }} : null]);
}
async function rk_dup(t) {  // a new trip with the same data, without the receipts; opens it
  const keys = ['date_from', 'date_to', 'dest', 'overnight', 'people', 'purpose', 'client_id', 'project', 'km', 'note', 'country', 'place', 't_start', 't_end', 'vma_days', 'vma_off'];
  try {
    const j = await api('POST', '/api/office/trips', Object.fromEntries(keys.map(k => [k, t[k]])));
    RK.open = j.id; RK.sel.clear(); rk_reload();
    toast(tr('Copy created'), async () => { await api('DELETE', `/api/office/trips/${j.id}`); RK.open = null; rk_reload(); });
  } catch (x) { toast(x.message || tr('unknown')); }
}
document.addEventListener('contextmenu', e => {  // right click on a trip row: the same menu
  const r = e.target.closest?.('.rklist .ofcrow[data-rk="open"]'); if (!r) return;
  e.preventDefault(); rk_rowMenu(r.dataset.id, r);
});
// 2.117.0 A (#2292): own purposes. The choice: the two built-in ones, the own ones of the office (+ an old text of the trip),
// last "Add another purpose…" -> a field right below, Enter stores it as an own purpose and chooses it
function rk_purposeOpts(cur) {
  const own = (RK.data?.purposes || []).map(p => [p.name, p.name]);
  if (cur && !['job', 'acquisition'].includes(cur) && !own.some(o => o[0] === cur)) own.push([cur, cur]);
  return [['job', tr('Job for a client / project')], ['acquisition', tr('Acquisition / research')], ...own.sort((a, b) => a[1].localeCompare(b[1], LOCALE())), ['__add', tr('Add another purpose…')]];
}
const rk_purposeNewHtml = () => `<div class="row rkpnew" hidden><label for="rk-pnew">${tr('New purpose')}</label><input id="rk-pnew" maxlength="120" enterkeyhint="done" autocomplete="off" placeholder="${esc(tr('e.g. Trade fair'))}"></div>`;
function rk_purposeWire(md) {
  const sel = $('#rk-purpose', md), row = $('.rkpnew', md), inp = $('#rk-pnew', md); if (!sel || !row) return;
  sel.dataset.prev = sel.value;
  sel.addEventListener('change', () => { if (sel.value === '__add') { row.hidden = false; inp.focus(); } else { sel.dataset.prev = sel.value; row.hidden = true; } });
  inp.addEventListener('keydown', async e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); row.hidden = true; inp.value = ''; sel.value = sel.dataset.prev; sel.focus(); return; }
    if (e.key !== 'Enter' || e.isComposing) return;
    e.preventDefault(); e.stopPropagation();
    try { if (await rk_purposeTake(md)) sel.focus(); } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
async function rk_purposeTake(md) {  // the typed name -> an own purpose of the office, chosen in the dialog; '' when nothing is typed
  const sel = $('#rk-purpose', md), inp = $('#rk-pnew', md), name = inp.value.trim(); if (!name) return '';
  const j = await api('POST', '/api/office/trips/purposes', {name});
  if (RK.data) RK.data.purposes = [...(RK.data.purposes || []).filter(p => p.id !== j.id), {id: j.id, name: j.name}];
  if (![...sel.options].some(o => o.value === j.name)) $('option[value="__add"]', sel).insertAdjacentHTML('beforebegin', `<option value="${esc(j.name)}">${esc(j.name)}</option>`);
  sel.value = sel.dataset.prev = j.name; $('.rkpnew', md).hidden = true; inp.value = '';
  return j.name;
}
async function rk_purposeVal(md) {  // the purpose to save (a name still in the field is taken over)
  const v = $('#rk-purpose', md).value;
  return v !== '__add' ? v : (await rk_purposeTake(md)) || $('#rk-purpose', md).dataset.prev || 'job';
}
// the section "Travel expenses" in the office settings (admins): the own purposes, rename in place (saved on leaving the
// field), remove with undo, add with Enter; no save button
const RKP = {list: null, oid: null};
async function rk_purposesLoad() {
  RKP.oid = OFC.info?.org_id; RKP.list = [];
  try { RKP.list = (await api('GET', '/api/office/trips/purposes')).purposes || []; } catch (x) { RKP.list = []; toast(x.message || tr('unknown')); }
  const sec = $('.rkpset'); if (sec) sec.outerHTML = rk_settingsHtml();  // only this section: the settings form keeps what is typed there
}
function rk_settingsHtml() {
  if (!ofcAdmin()) return '';
  if (RKP.oid !== OFC.info?.org_id) { RKP.oid = OFC.info?.org_id; RKP.list = null; setTimeout(rk_purposesLoad, 0); }
  const ls = RKP.list;
  return `<section class="rkpset" data-fg-skip aria-labelledby="rkp-h"><h3 id="rkp-h">${tr('Travel expenses')}</h3>
    <div class="shint">${tr('Own purposes for trips, besides “Job for a client / project” and “Acquisition / research”. Trips keep the text they have when you rename or remove one.')}</div>
    ${!ls ? `<p class="muted">${tr('Loading…')}</p>` : `<ul class="rkplist" role="list">${ls.map(p => `<li><input value="${esc(p.name)}" maxlength="120" data-rkp="name" data-id="${p.id}" aria-label="${esc(tr('Purpose'))}"><button type="button" class="iconbtn" data-rkp="del" data-id="${p.id}" aria-label="${esc(tr('Remove {0}', p.name))}" title="${esc(tr('Remove'))}">${ic('trash', 's')}</button></li>`).join('')}</ul>
    <div class="lacts"><input id="rkp-new" maxlength="120" enterkeyhint="done" autocomplete="off" placeholder="${esc(tr('Add another purpose…'))}" aria-label="${esc(tr('New purpose'))}"><button type="button" class="btn sm" data-rkp="add">${ic('plus', 's')}<span>${tr('Add')}</span></button></div>`}</section>`;
}
async function rk_purposeAct(a, el) {
  const sec = el.closest('.rkpset');
  try {
    if (a === 'add') {
      const inp = $('#rkp-new', sec), name = inp.value.trim(); if (!name) { inp.focus(); return; }
      const j = await api('POST', '/api/office/trips/purposes', {name}); RK.data = null; await rk_purposesLoad(); $('#rkp-new')?.focus();
      toast(tr('Added'), async () => { await api('DELETE', `/api/office/trips/purposes/${j.id}`); RK.data = null; rk_purposesLoad(); });
    } else if (a === 'del') {
      const j = await api('DELETE', `/api/office/trips/purposes/${el.dataset.id}`); RK.data = null; await rk_purposesLoad();
      toast(tr('Removed'), async () => { await api('POST', '/api/office/trips/purposes', {name: j.purpose.name}); RK.data = null; rk_purposesLoad(); });
    } else if (a === 'name') {
      const old = (RKP.list || []).find(p => p.id === +el.dataset.id), name = el.value.trim(); if (!old || name === old.name) return;
      if (!name) { el.value = old.name; return; }
      const was = old.name;
      await api('PATCH', `/api/office/trips/purposes/${old.id}`, {name}); RK.data = null; old.name = name;
      toast(tr('Saved'), async () => { await api('PATCH', `/api/office/trips/purposes/${old.id}`, {name: was}); RK.data = null; rk_purposesLoad(); });
    }
  } catch (x) { if (a === 'name') { const o = (RKP.list || []).find(p => p.id === +el.dataset.id); if (o) el.value = o.name; } toast(x.message || tr('unknown')); }
}
document.addEventListener('click', e => { const b = e.target.closest?.('button[data-rkp]'); if (!b) return; e.preventDefault(); rk_purposeAct(b.dataset.rkp, b); });
document.addEventListener('change', e => { if (e.target.dataset?.rkp === 'name') rk_purposeAct('name', e.target); });
document.addEventListener('keydown', e => {
  const x = e.target; if (e.key !== 'Enter' || e.isComposing || !(x.id === 'rkp-new' || x.dataset?.rkp === 'name') || !x.closest?.('.rkpset')) return;
  e.preventDefault(); e.stopPropagation();  // never the settings form's submit
  if (x.id === 'rkp-new') rk_purposeAct('add', x); else x.blur();
}, true);
const rk_month = ym => { const [y, m] = String(ym).split('-').map(Number); return y && m ? new Date(y, m - 1, 1).toLocaleDateString(LOCALE(), {month: 'long', year: 'numeric'}) : ym; };

// ---- dialogs
function rk_tripModal(t) {
  const d = RK.data, ppl = new Set((t?.people || []).filter(p => p.id).map(p => p.id)), free = (t?.people || []).filter(p => !p.id).map(p => p.name).join(', ');
  const md = modal(`<h3>${t ? tr('Edit trip') : tr('New trip')}</h3>
    <div class="row"><label id="rk-fl">${tr('From')}</label>${dateIn('rk-from', t?.date_from || today(), {label: tr('From'), clear: false})}</div>
    <div class="row"><label id="rk-tl">${tr('To')}</label>${dateIn('rk-to', t?.date_to || '', {label: tr('To'), empty: tr('same day'), after: 'rk-from'})}</div>
    ${ofcRowF('rk-dest', tr('Destination / route'), ofcIn('rk-dest', t?.dest, {max: 300, ph: tr('e.g. Hamburg – Berlin')}))}
    ${ofcChk('rk-over', tr('Overnight stay'), t?.overnight)}
    ${rk_vmaDlgHtml(t)}
    <div class="row"><span class="rklab">${tr('Participants')}</span><div class="rkppl">${(d.people || []).map(p => `<label class="chkl"><input type="checkbox" data-pid="${p.id}" ${ppl.has(p.id) ? 'checked' : ''}> ${esc(p.name)}</label>`).join('')}</div></div>
    ${ofcRowF('rk-free', tr('Other people'), ofcIn('rk-free', free, {max: 600, ph: tr('Names, separated by commas')}))}
    ${ofcRowF('rk-purpose', tr('Purpose'), ofcSel('rk-purpose', t?.purpose || 'job', rk_purposeOpts(t?.purpose)))}${rk_purposeNewHtml()}
    ${ofcRowF('rk-client', tr('Client'), ofcSel('rk-client', t?.client_id || '', (d.clients || []).map(c => [c.id, cdn_label(c)]), tr('none')))}
    ${ofcRowF('rk-project', tr('Project'), ofcIn('rk-project', t?.project, {list: 'rk-projs'}))}<datalist id="rk-projs">${(d.projects || []).map(p => `<option value="${esc(p)}">`).join('')}</datalist>
    ${ofcRowF('rk-km', tr('Kilometres'), ofcIn('rk-km', t?.km != null ? fmtNum(+t.km, 0) : '', {num: true, ph: tr('optional')}))}
    <div class="row"><label for="rk-note">${tr('Note')}</label><textarea id="rk-note" rows="2" maxlength="2000">${esc(t?.note || '')}</textarea></div>
    <div class="aerr" role="alert"></div>
    <div class="foot">${t ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${t ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  if (t && typeof ofm_can === 'function' && ofm_can(ofm_officeFrom())) $('.foot .spacer', md)?.insertAdjacentHTML('beforebegin', `<button class="btn" data-m="move">${ic('brief', 's')} ${esc(tr('Move to another workspace…'))}</button>`);  // 2.97.0 C (#2049)
  const close = fgModal(md);
  rk_vmaDlgWire(md, t);  // 2.95.0 A (#1932)
  rk_purposeWire(md);  // 2.117.0 A (#2292)
  md.addEventListener('change', e => {  // 2.117.0 A (#2290): an end before the new start moves to the start
    if (e.target.id !== 'rk-from') return;
    const to = $('#rk-to', md), f = e.target.value; if (to && to.value && f && to.value < f) dpSet(to, f);
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'move') { md.remove(); ofm_move({what: 'travel', ids: [t.id], from: ofm_officeFrom(), label: qn(t.dest || rk_span(t)), after: async () => { RK.open = null; rk_reload(); }}); return; }  // 2.97.0 C (#2049)
      if (b.dataset.m === 'del') {
        if (!await askConfirm(tr('Delete the trip “{0}” with its receipts?', t.dest || rk_span(t)), '', {ok: tr('Delete'), danger: true})) return;
        const j = await api('DELETE', `/api/office/trips/${t.id}`); md.remove(); RK.open = null; rk_reload();
        toast(tr('Deleted'), async () => { await api('POST', '/api/office/trips', j.trip); rk_reload(); });
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const people = [...$$('[data-pid]', md).filter(x => x.checked).map(x => ({id: +x.dataset.pid})), ...v('#rk-free').split(',').map(s => s.trim()).filter(Boolean).map(name => ({name}))];
      const body = {date_from: v('#rk-from'), date_to: v('#rk-to'), dest: v('#rk-dest'), overnight: $('#rk-over', md).checked ? 1 : 0, people, purpose: await rk_purposeVal(md),
        client_id: +v('#rk-client') || null, project: v('#rk-project'), km: ofcNum(v('#rk-km')), note: v('#rk-note'), ...rk_vmaDlgBody(md)};
      if (t) {
        const old = {date_from: t.date_from, date_to: t.date_to, dest: t.dest, overnight: t.overnight, people: t.people, purpose: t.purpose, client_id: t.client_id, project: t.project, km: t.km, note: t.note,
          country: t.country, place: t.place, t_start: t.t_start, t_end: t.t_end, vma_days: t.vma_days, vma_off: t.vma_off};  // 2.95.0 A (#1932)
        await api('PATCH', `/api/office/trips/${t.id}`, body); md.remove(); rk_reload();
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/trips/${t.id}`, old); rk_reload(); });
      } else {
        const j = await api('POST', '/api/office/trips', body); md.remove(); RK.open = j.id; rk_reload();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/trips/${j.id}`); RK.open = null; rk_reload(); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}
function rk_itemModal(t, i) {
  const home = rk_home(), cur = i?.currency || home;
  const md = modal(`<h3>${i ? tr('Edit receipt') : tr('Add receipt')}</h3>
    <div class="row"><label id="rk-dl">${tr('Date')}</label>${dateIn('rk-date', i?.date || t.date_from || '', {label: tr('Date'), empty: tr('optional')})}</div>
    ${ofcRowF('rk-cat', tr('Category'), ofcSel('rk-cat', i?.category || 'train', (RK.data.categories || []).map(c => [c.key, c.label])))}
    ${ofcRowF('rk-amt', tr('Amount'), ofcIn('rk-amt', i ? fmtNum(+i.amount, 2) : '', {num: true}))}
    ${ofcRowF('rk-cur', tr('Currency'), ofcIn('rk-cur', cur, {max: 3, list: 'rk-curs'}))}<datalist id="rk-curs">${[home, ...(OFC.info?.pack?.currencies || ['EUR', 'USD', 'GBP', 'CHF'])].filter((x, k, a) => a.indexOf(x) === k).map(x => `<option value="${x}">`).join('')}</datalist>
    <div class="rkfx" ${cur === home ? 'hidden' : ''}>${ofcRowF('rk-fx', tr('Exchange rate (1 {0} = …)', home), ofcIn('rk-fx', i?.fx_rate ? fmtNum(+i.fx_rate, 4) : '', {num: true}))}
      <p class="muted ofchint rkfxout"></p></div>
    ${ofcRowF('rk-text', tr('Text'), ofcIn('rk-text', i?.text, {max: 300, ph: tr('e.g. ICE Hamburg – Berlin')}))}
    ${rk_dv() ? `${ofcChk('rk-datev', tr('Receipt is in DATEV'), i?.datev)}
    ${ofcRowF('rk-dno', tr('DATEV receipt number'), ofcIn('rk-dno', i?.datev_no, {max: 60, ph: tr('optional')}))}` : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot">${i ? `<button class="btn danger" data-m="del">${tr('Delete')}</button>` : ''}<span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${i ? tr('Save') : tr('Add')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  const fx = () => {
    const c = ($('#rk-cur', md).value || '').trim().toUpperCase(), box = $('.rkfx', md); box.hidden = !c || c === home;
    const a = ofcNum($('#rk-amt', md).value), r = ofcNum($('#rk-fx', md).value, true);
    $('.rkfxout', md).textContent = !box.hidden && a != null && r ? tr('= {0} in {1}', fmtNum(a / r, 2), home) : '';
  };
  md.addEventListener('input', fx); fx();
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    try {
      if (b.dataset.m === 'del') {
        const j = await api('DELETE', `/api/office/trips/${t.id}/items/${i.id}`); md.remove(); rk_reload();
        const o = j.item; toast(tr('Deleted'), async () => { await api('POST', `/api/office/trips/${t.id}/items`, {date: o.date, category: o.category, amount: o.amount, currency: o.currency, fx_rate: o.fx_rate, amount_home: o.amount_home, text: o.text, datev: o.datev, datev_no: o.datev_no}); rk_reload(); });
        return;
      }
      const v = id => $(id, md)?.value ?? '';
      const c = v('#rk-cur').trim().toUpperCase() || home;
      const body = {date: v('#rk-date'), category: v('#rk-cat'), amount: ofcNum(v('#rk-amt')), currency: c, text: v('#rk-text'), ...($('#rk-datev', md) ? {datev: $('#rk-datev', md).checked ? 1 : 0, datev_no: v('#rk-dno')} : {})};  // 2.147.0 (#2460): DATEV off = its marks stay as saved
      if (c !== home) body.fx_rate = ofcNum(v('#rk-fx'), true);
      if (i) {
        const old = {date: i.date, category: i.category, amount: i.amount, currency: i.currency, fx_rate: i.fx_rate, amount_home: i.amount_home, text: i.text, datev: i.datev, datev_no: i.datev_no};
        await api('PATCH', `/api/office/trips/${t.id}/items/${i.id}`, body); md.remove(); rk_reload();
        toast(tr('Saved'), async () => { await api('PATCH', `/api/office/trips/${t.id}/items/${i.id}`, old); rk_reload(); });
      } else {
        const j = await api('POST', `/api/office/trips/${t.id}/items`, body); md.remove(); rk_reload();
        toast(tr('Added'), async () => { await api('DELETE', `/api/office/trips/${t.id}/items/${j.item_id}`); rk_reload(); });
      }
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}
async function rk_billModal(t) {
  const ids = t.items.filter(i => RK.sel.has(i.id) && !i.billed).map(i => i.id); if (!ids.length) return;
  let docs = [];
  try { docs = (await api('GET', `/api/office/trips/bill-docs${t.client_id ? `?client_id=${t.client_id}` : ''}`)).docs || []; } catch (x) { toast(x.message || ''); return; }
  const kind = d => d.kind === 'invoice' ? tr('Invoice') : tr('Quotation');
  const md = modal(`<h3>${tr('Bill receipts on')}</h3>
    <p class="muted">${esc(trn('{0} receipt becomes a position with the amount as purchase price.', '{0} receipts become positions with the amount as purchase price.', ids.length))}</p>
    ${docs.length ? ofcRowF('rk-doc', tr('Quotation or invoice (draft)'), ofcSel('rk-doc', docs[0].id, docs.map(d => [d.id, [kind(d), d.number || tr('Draft'), d.project_title, d.client_id ? rk_client(d.client_id) : ''].filter(Boolean).join(' · ')])))
      : `<div class="empty nempty">${tr('There is no quotation or invoice in draft. Create one first.')}</div>`}
    ${ofcRowF('rk-mk', tr('Markup in %'), ofcIn('rk-mk', '', {num: true, ph: '0'}))}
    ${ids.length > 1 ? ofcChk('rk-one', tr('One position for all receipts'), false) : ''}
    <div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button>${docs.length ? `<button class="btn pri" data-m="save">${tr('Bill on')}</button>` : ''}</div>`);
  md.classList.add('ofcdlg');
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { md.remove(); return; }
    try {
      const j = await api('POST', '/api/office/trips/bill', {doc_id: +$('#rk-doc', md).value, item_ids: ids, markup_pct: ofcNum($('#rk-mk', md).value), one: $('#rk-one', md)?.checked ? 1 : 0});
      md.remove(); RK.sel.clear(); rk_reload();
      toast(tr('Billed on {0}', j.number || tr('Draft')), async () => { await api('POST', '/api/office/trips/unbill', {item_ids: j.items, positions: j.positions}); rk_reload(); });
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}

// ---- events
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-rk]'); if (!b || b.tagName === 'INPUT') return;
  const a = b.dataset.rk, t = RK.open ? rk_trip(RK.open) : null;
  if (a === 'new') rk_tripModal(null);
  else if (a === 'open') { RK.open = +b.dataset.id; RK.sel.clear(); ofcDraw(); }
  else if (a === 'rowmore') rk_rowMenu(b.dataset.id, b);  // 2.117.0 A (#2287)
  else if (a === 'back') { RK.open = null; RK.sel.clear(); ofcDraw(); }
  else if (a === 'edit' && t) rk_tripModal(t);
  else if (a === 'add' && t) rk_itemModal(t, null);
  else if (a === 'item' && t) { const i = t.items.find(x => x.id === +b.dataset.id); if (i) rk_itemModal(t, i); }
  else if (a === 'bill' && t) rk_billModal(t);
  else if (a === 'filter') { RK.filter = b.dataset.v; ofcDraw(); }
  else if (a === 'view') { RK.view = b.dataset.v; RK.open = null; ofcDraw(); }
  else if (a === 'by') { RK.by = b.dataset.v; ofcDraw(); }
  else return;
  e.preventDefault();
});
document.addEventListener('change', async e => {
  const x = e.target;
  if (x.id === 'rk-year') { RK.year = x.value; RK.open = null; rk_reload(); return; }
  if (x.id === 'rk-person') { RK.person = x.value; RK.personName = x.selectedOptions[0]?.textContent || ''; RK.rep = null; ofcDraw(); $('#rk-person')?.focus(); return; }  // 2.117.0 A (#2291)
  if (x.dataset?.rk === 'sel') { if (x.checked) RK.sel.add(+x.dataset.id); else RK.sel.delete(+x.dataset.id); ofcDraw(); return; }
  if (x.dataset?.rk !== 'datev' || !RK.open) return;
  const tid = RK.open, iid = +x.dataset.id, on = x.checked ? 1 : 0;
  try {
    await api('PATCH', `/api/office/trips/${tid}/items/${iid}`, {datev: on}); rk_reload();
    toast(on ? tr('Ticked as in DATEV') : tr('Tick removed'), async () => { await api('PATCH', `/api/office/trips/${tid}/items/${iid}`, {datev: on ? 0 : 1}); rk_reload(); });
  } catch (y) { x.checked = !on; toast(y.message || ''); }
});

// ---- 2.95.0 A (#1932): the per diem (Verpflegungsmehraufwand) of a trip and its report (part A fills this block; server
// kalmido/office/vma.py + vmareport.py). rk_vmaRepHtml: the per diem block at the top of the evaluation view.
const RKV = {rates: {}, rep: null, src: null, open: new Set()};
const rk_vmaEur = n => `${(+n).toLocaleString(LOCALE(), {minimumFractionDigits: 2, maximumFractionDigits: 2})} €`;
const rk_vmaN = n => `${fmtNum(+n, +n % 1 ? 2 : 0)} €`;
const rk_vmaCty = code => !code || code === 'DE' ? (ctyNames().DE || 'DE') : ctyNames()[code] || code;
function rk_vmaRates(year) {  // the countries / cities and rates of a year (cached; a year without a table: countries [])
  const y = String(year || '').slice(0, 4);
  if (!/^\d{4}$/.test(y)) return Promise.resolve(null);
  if (!RKV.rates[y]) RKV.rates[y] = api('GET', `/api/office/trips/vma-rates?year=${y}`).catch(() => { delete RKV.rates[y]; return null; });
  return RKV.rates[y];
}
function rk_vmaCtyOpts(r, cur, first) {  // Germany first, then the countries of the table by name (plus a stored code not in it); first: an option on top, selected when cur is ''
  const codes = (r?.countries || []).map(c => c.code);
  if (cur && cur !== 'DE' && !codes.includes(cur)) codes.push(cur);
  const names = codes.map(c => [c, rk_vmaCty(c)]).sort((a, b) => a[1].localeCompare(b[1], LOCALE()));
  return (first || '') + [['DE', rk_vmaCty('DE')], ...names].map(([c, n]) => `<option value="${esc(c)}" ${c === (cur || (first ? null : 'DE')) ? 'selected' : ''}>${esc(n)}</option>`).join('');
}
function rk_vmaPlaceOpts(r, code, cur) {  // '' = other places of the country; none when the country has no cities
  const pl = (r?.countries || []).find(c => c.code === code)?.places || [];
  if (pl.length < 2 && !cur) return '';
  const all = pl.includes(cur || '') ? pl : [...pl, cur];
  return all.map(p => `<option value="${esc(p)}" ${p === (cur || '') ? 'selected' : ''}>${esc(p || tr('Other places'))}</option>`).join('');
}
const rk_vmaNdays = (a, b) => { const d0 = Date.parse(a), d1 = Date.parse(b || a); return isNaN(d0) || isNaN(d1) ? 0 : Math.round((d1 - d0) / 864e5) + 1; };
function rk_vmaDlgHtml(t) {  // the section in the trip dialog
  const cty = t?.country || 'DE';
  return `<fieldset class="rkv-sec"><legend>${tr('Per diem')}</legend>
    ${ofcRowF('rk-cty', tr('Country'), `<select id="rk-cty">${rk_vmaCtyOpts(null, cty)}</select>`)}
    <div class="row rkv-pl" hidden><label for="rk-place">${tr('City')}</label><select id="rk-place"><option value="${esc(t?.place || '')}" selected>${esc(t?.place || tr('Other places'))}</option></select></div>
    <div class="rkv-tm" hidden><div class="row"><label id="rk-tsl">${tr('Start time')}</label>${timeIn('rk-ts', t?.t_start || '', {label: tr('Start time'), empty: tr('none')})}</div>
      <div class="row"><label id="rk-tel">${tr('End time')}</label>${timeIn('rk-te', t?.t_end || '', {label: tr('End time'), empty: tr('none')})}</div>
      <div class="shint">${tr('A trip without an overnight stay needs more than 8 hours for the per diem.')}</div></div>
    ${ofcChk('rk-voff', tr('No per diem'), t?.vma_off)}
    <p class="muted ofchint rkv-dh" hidden></p></fieldset>`;
}
function rk_vmaDlgWire(md, t) {
  let year = '';
  const sync = async () => {
    const from = $('#rk-from', md)?.value || '', to = $('#rk-to', md)?.value || from, n = rk_vmaNdays(from, to), off = $('#rk-voff', md).checked;
    $('.rkv-tm', md).hidden = off || !(n === 1 || (n === 2 && !$('#rk-over', md).checked));
    $('#rk-cty', md).disabled = off;
    if (from.slice(0, 4) === year) return;
    year = from.slice(0, 4);
    const r = await rk_vmaRates(year); if (!md.isConnected || year !== from.slice(0, 4)) return;
    const sel = $('#rk-cty', md), cur = sel.value;
    sel.innerHTML = rk_vmaCtyOpts(r, cur);
    const h = $('.rkv-dh', md); h.hidden = !(r && r.hint); h.textContent = r?.hint ? tr('No per diem rates for {0}', r.hint.year) : '';
    place();
  };
  const place = () => rk_vmaRates(year).then(r => {
    if (!md.isConnected) return;
    const ps = $('#rk-place', md), o = rk_vmaPlaceOpts(r, $('#rk-cty', md).value, ps.dataset.touched ? '' : ps.value);
    ps.innerHTML = o || '<option value="" selected></option>';
    ps.dataset.none = o ? '' : '1';  // 2.95.0 (#1932 review): the country has no cities (only then the city is cleared)
    $('.rkv-pl', md).hidden = !o || $('#rk-voff', md).checked;
  });
  md.addEventListener('change', e => {
    if (e.target.id === 'rk-cty') { $('#rk-place', md).dataset.touched = '1'; place(); }
    if (['rk-from', 'rk-to', 'rk-over', 'rk-voff'].includes(e.target.id)) { sync(); if (e.target.id === 'rk-voff') place(); }
  });
  sync();
}
function rk_vmaDlgBody(md) {
  const c = $('#rk-cty', md)?.value || 'DE', pl = $('#rk-place', md)?.dataset.none === '1' ? '' : $('#rk-place', md)?.value || '';  // review: kept while the cities load / with no per diem
  return {country: c === 'DE' ? '' : c, place: pl, t_start: $('#rk-ts', md)?.value || '', t_end: $('#rk-te', md)?.value || '', vma_off: $('#rk-voff', md)?.checked ? 1 : 0};
}
function rk_vmaHint(h) {
  if (h.key === 'off') return tr('No per diem for this trip');
  if (h.key === 'dates') return tr('The dates of the trip are not valid');
  if (h.key === 'times') return tr('Start and end time missing');
  if (h.key === 'short') return tr('8 hours or less: no per diem');
  if (h.key === 'year') return tr('No per diem rates for {0}', h.year);
  if (h.key === 'alias' || h.key === 'lu') return tr('Rate of {0} used for {1}', rk_vmaCty(h.used), rk_vmaCty(h.country));
  return h.key || '';
}
function rk_vmaBreak(lines) {  // "Greece: 2 × 24 € + 9 × 36 € = 372 €" per country (like the spreadsheet)
  const by = new Map();
  for (const l of lines || []) { const k = `${l.country}|${l.place}`; if (!by.has(k)) by.set(k, []); by.get(k).push(l); }
  return [...by.values()].map(ls => `${rk_vmaCty(ls[0].country)}${ls[0].place ? ` (${ls[0].place})` : ''}: ${ls.map(l => `${l.n} × ${rk_vmaN(l.rate)}`).join(' + ')} = ${rk_vmaN(ls.reduce((s, l) => s + +l.sum, 0))}`);
}
function rk_vmaTag(t) {  // the trip list: the per diem of all participants next to the receipts
  const v = t.vma; if (!v || t.vma_off) return '';
  if (v.total == null) return `<span class="rkv-tag rkv-none">${esc(tr('Per diem without amount'))}</span>`;
  return +v.total ? `<span class="rkv-tag" title="${esc(tr('Per diem'))}">${esc(tr('Per diem'))} ${rk_vmaEur(v.total)}</span>` : '';
}
function rk_vmaCols(t, rec) {  // 2.114.4 D (#2286): per diem as main amount, receipts column only when the year has receipts
  const v = !t.vma_off && t.vma, none = '<span class="muted">–</span>';
  const pd = !v ? none : v.total == null ? `<span class="rkv-none" title="${esc(tr('Per diem without amount'))}" aria-label="${esc(tr('Per diem without amount'))}">– <small>${esc(tr('Per diem without amount'))}</small></span>` : rk_vmaEur(v.total);
  const rc = (t.items || []).length ? ofcMoney(t.total) : none;
  if (!rec) return `<span class="rksum rkpd"><b>${pd}</b></span>`;
  return `<span class="rksum rkpd" title="${esc(tr('Per diem'))}"><small class="muted">${esc(tr('Per diem'))}</small> <b>${pd}</b></span><span class="rksum rkrc" title="${esc(tr('Receipts'))}"><small class="muted">${esc(tr('Receipts'))}</small> <b>${rc}</b></span>`;
}
function rk_vmaCard(t) {  // the trip view: amount per person (x participants), breakdown, hints, source, "Edit days"
  const v = t.vma || {}, hints = (v.hints || []).filter(h => h.key !== 'off');
  const amt = t.vma_off ? `<span class="muted">${esc(tr('No per diem'))}</span>` : v.amount == null ? `<span class="muted">${esc(tr('without amount'))}</span>` : `<b class="rksum">${rk_vmaEur(v.total)}</b>`;
  const per = !t.vma_off && v.amount != null && v.persons > 1 ? `<p class="muted">${esc(tr('{0} per person × {1}', rk_vmaEur(v.amount), v.persons))}</p>` : '';
  const br = t.vma_off ? [] : rk_vmaBreak(v.lines);
  if (!t.vma_off && +v.cut) br.push(tr('Meals provided: -{0}', rk_vmaN(v.cut)));
  const days = !t.vma_off && !t.own_ro && rk_vmaNdays(t.date_from, t.date_to) > 0;  // 2.187.1 B (#2735): + not read only
  return `<section class="rkv-card" aria-label="${esc(tr('Per diem'))}"><div class="rkv-top"><b>${tr('Per diem')}</b><span class="spacer"></span>${amt}</div>${per}
    ${br.length ? `<ul class="rkv-br" role="list">${br.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
    ${hints.length && !t.vma_off ? `<ul class="rkv-hints" role="list">${hints.map(h => `<li>${esc(rk_vmaHint(h))}</li>`).join('')}</ul>` : ''}
    ${(v.source || []).length ? `<p class="muted rkv-src">${esc(tr('Rates: {0}', v.source.join('; ')))}</p>` : ''}
    ${days ? `<div class="rkv-act"><button type="button" class="btn sm" data-rkv="days" data-id="${t.id}">${ic('cal', 's')}<span>${tr('Edit days')}</span></button></div>` : ''}</section>`;
}
async function rk_vmaDaysModal(t) {  // per day: country (+ city) and the meals provided; stores only the days that differ
  // 2.298.0 A2 (#3186): the cut of each meal stands on its tick, the country rule sits behind the (i) of the heading
  const n = rk_vmaNdays(t.date_from, t.date_to); if (!n || n > 400) return;
  const dates = Array.from({length: n}, (_, i) => addDays(t.date_from, i));  // 2.263.0 (#2978): local days
  const r = await rk_vmaRates(t.date_from), by = Object.fromEntries((t.vma_days || []).map(x => [x.date, x])), base = t.country || 'DE';
  const meal = (d, m, lab) => `<label class="chkl rkv-meal"><input type="checkbox" data-meal="${m}" ${by[d]?.[m] ? 'checked' : ''}> ${esc(lab)}</label>`;
  const rows = dates.map(d => { const o = by[d] || {}, c = o.country || '', pl = rk_vmaPlaceOpts(r, c || base, o.place || (c ? '' : t.place || ''));
    return `<li class="rkv-day" data-day="${d}"><b>${esc(fmtDateLoc(d))}</b>
      <div class="rkv-dsel"><select data-vc aria-label="${esc(tr('Country'))}">${rk_vmaCtyOpts(r, c, `<option value="" ${c ? '' : 'selected'}>${esc(tr('As the trip ({0})', rk_vmaCty(base)))}</option>`)}</select>
      <select data-vp aria-label="${esc(tr('City'))}" ${pl ? '' : 'hidden'}>${pl}</select></div>
      <div class="rkv-meals" role="group" aria-label="${esc(tr('Meals provided'))}">${meal(d, 'b', tr('Breakfast −20 %'))}${meal(d, 'l', tr('Lunch −40 %'))}${meal(d, 'd', tr('Dinner −40 %'))}</div></li>`; }).join('');
  const md = modal(`<h3>${tr('Edit days')}</h3><div class="shint">${esc(tr('Country = where you are before midnight; on the day you travel home, the last place abroad where you worked.'))}</div>
    <ul class="rkv-days" role="list">${rows}</ul><div class="aerr" role="alert"></div>
    <div class="foot"><span class="spacer"></span><button class="btn" data-m="close">${tr('Cancel')}</button><button class="btn pri" data-m="save">${tr('Save')}</button></div>`);
  md.classList.add('ofcdlg');
  const close = fgModal(md);
  md.addEventListener('change', e => {
    const s = e.target.closest('[data-vc]'); if (!s) return;
    const li = s.closest('.rkv-day'), p = $('[data-vp]', li), o = rk_vmaPlaceOpts(r, s.value || base, s.value ? '' : t.place || '');
    p.innerHTML = o; p.hidden = !o;
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('[data-m]'); if (!b) return;
    if (b.dataset.m === 'close') { close(); return; }
    const days = [];
    for (const li of $$('.rkv-day', md)) {
      const c = $('[data-vc]', li).value, p = $('[data-vp]', li), row = {date: li.dataset.day};
      if (c) row.country = c;
      if (!p.hidden && p.value && (c || p.value !== (t.place || ''))) row.place = p.value;
      for (const x of $$('[data-meal]', li)) if (x.checked) row[x.dataset.meal] = 1;
      if (Object.keys(row).length > 1) days.push(row);
    }
    const old = t.vma_days || [];
    try {
      await api('PATCH', `/api/office/trips/${t.id}`, {vma_days: days}); md.remove(); rk_reload();
      toast(tr('Saved'), async () => { await api('PATCH', `/api/office/trips/${t.id}`, {vma_days: old}); rk_reload(); });
    } catch (x) { const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
}
async function rk_vmaLoad(y) {
  const p = RK.person;  // 2.117.0 A (#2291)
  RKV.src = RK.data; RKV.rep = {y, p, loading: true};
  try { RKV.rep = Object.assign(await api('GET', `/api/office/trips/vma?year=${y}${rk_pq()}`), {y, p}); } catch (x) { RKV.rep = {y, p, error: x.message || tr('unknown')}; }
  ofcDraw();
}
function rk_vmaRepHtml() {  // the evaluation: per diem per person of the year (all years -> the current one), PDF / Excel / CSV
  const y = RK.year || String(new Date().getFullYear());
  if (!RKV.rep || RKV.rep.y !== y || RKV.rep.p !== RK.person || RKV.src !== RK.data) { if (!RKV.rep?.loading || RKV.rep.y !== y || RKV.rep.p !== RK.person) setTimeout(() => rk_vmaLoad(y), 0); return `<section class="rkv-rep"><p class="muted">${tr('Loading…')}</p></section>`; }
  const d = RKV.rep;
  if (d.loading) return `<section class="rkv-rep"><p class="muted">${tr('Loading…')}</p></section>`;
  if (d.error) return `<section class="rkv-rep"><div class="empty">${esc(d.error)}</div></section>`;
  // 2.187.1 B (#2735): the files need the special "export" (office groups); the level "own" does not import
  const dl = ext => ofr_noSp('travel', 'export') ? '' : `<a class="btn sm" href="/api/office/trips/vma.${ext}?year=${y}${esc(rk_pq())}" download>${ic('download', 's')}<span>${ext === 'xlsx' ? 'Excel' : ext.toUpperCase()}</span></a>`;
  const trip = x => `<li><span class="ofcn"><b>${esc([rk_span(x), x.dest].filter(Boolean).join(' · '))}</b><small class="muted">${esc(x.purpose || '')}</small>
    ${(x.amount != null ? x.breakdown : x.hints.map(rk_vmaHint)).map(l => `<small class="${x.amount != null ? '' : 'muted'}">${esc(l)}</small>`).join('')}</span>
    <span class="rksum">${x.amount != null ? rk_vmaEur(x.amount) : '–'}</span></li>`;
  const ppl = d.people.map(g => `<li><details data-rkv="person" data-k="${esc(g.key)}" ${RKV.open.has(g.key) ? 'open' : ''}><summary><span class="ofcn"><b>${esc(g.label)}</b>
    <small class="muted">${esc(trn('{0} trip', '{0} trips', g.trips.length))}${g.open ? ' · ' + esc(trn('{0} without amount', '{0} without amount', g.open)) : ''}</small></span><span class="rksum">${rk_vmaEur(g.total)}</span></summary>
    <ul class="rkv-trips" role="list">${g.trips.map(trip).join('')}</ul></details></li>`).join('');
  return `<section class="rkv-rep" aria-label="${esc(tr('Per diem allowances {0}', y))}"><div class="ofcbar"><b>${esc(tr('Per diem allowances {0}', y))}</b><span class="spacer"></span>${dl('pdf')}${dl('xlsx')}${dl('csv')}${ofr_lvOf('travel') === 'own' ? '' : rk_impBtn()}</div>
    ${d.people.length ? `<ul class="rkv-people" role="list">${ppl}</ul><div class="rkv-total"><b>${tr('Total')}</b><span class="spacer"></span><b class="rksum">${rk_vmaEur(d.total)}</b></div>`
      : `<div class="empty nempty">${esc(d.rates ? tr('No trips with a per diem in {0}.', y) : tr('No per diem rates for {0}', y))}</div>`}
    ${d.source.length ? `<p class="muted ofchint">${esc(tr('Rates: {0}', d.source.join('; ')))} · ${esc(tr('Kalmido does not replace tax advice.'))}</p>` : ''}</section>`;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-rkv="days"]'); if (!b) return;
  const t = rk_trip(+b.dataset.id); if (t) { e.preventDefault(); rk_vmaDaysModal(t); }
});
document.addEventListener('toggle', e => {
  const d = e.target; if (d?.dataset?.rkv !== 'person') return;
  if (d.open) RKV.open.add(d.dataset.k); else RKV.open.delete(d.dataset.k);
}, true);


// ---- 2.95.0 B (#1932): the import of a per diem spreadsheet (part B fills this block; server kalmido/office/vmaimport.py).
// rk_impBtn: the button that opens the import (empty list, evaluation view).
function rk_impBtn() { return `<button type="button" class="btn sm rki-btn" data-rki="pick">${ic('upload', 's')}<span>${tr('Take over from Excel')}</span></button>`; }
function rk_impPick() {
  const i = document.createElement('input'); i.type = 'file'; i.accept = '.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  i.onchange = () => { if (i.files[0]) rk_impPreview(i.files[0]); }; i.click();
}
async function rk_impPreview(file) {
  const fd = new FormData(); fd.append('file', file);
  let j;
  try {
    const r = await fetch('/api/office/trips/import/preview', {method: 'POST', body: fd, credentials: 'same-origin', headers: {'X-Requested-With': 'kalmido'}});
    j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
  } catch (x) { toast(x.message || tr('unknown')); return; }
  rk_impModal(j, file.name);
}
// a sheet = a person: a person of the office (u<id>) or the sheet's name as a free name (n)
function rk_impModal(j, name) {
  const sheets = j.sheets || [], ppl = j.people || [];
  sheets.forEach(s => { s.pv = s.person?.id ? `u${s.person.id}` : 'n'; });
  const md = modal(''), card = $('.card', md), ok = r => r.sel && r.status !== 'error';
  md.classList.add('ofcdlg', 'fcidlg', 'rki-dlg');
  const amt = v => v == null ? '–' : ofcMoney(v);
  const rowHtml = (r, si, i) => {
    const sub = [r.date_to && r.date_to !== r.date_from ? `${fmtDateLoc(r.date_from)} – ${fmtDateLoc(r.date_to)}` : (r.date_from ? fmtDateLoc(r.date_from) : tr('Row {0}', r.row)),
      r.t_start && r.t_end ? `${r.t_start}–${r.t_end}` : '', r.purpose === 'acquisition' ? tr('Acquisition / research') : r.purpose && r.purpose !== 'job' ? r.purpose : r.project].filter(Boolean).join(' · ');
    const why = (r.reasons || []).join(' · ');
    if (r.status === 'error') return `<li class="fcirow err"><span class="fcick" aria-hidden="true">${ic('x', 's')}</span><span class="ofcn"><b>${esc(r.dest || tr('Row {0}', r.row))}</b><small>${esc(tr('Row {0}', r.row))} · ${esc(why)}</small></span></li>`;
    return `<li class="fcirow rki-row ${r.sel ? 'on' : ''} ${r.status}"><label class="fcick"><input type="checkbox" data-rki="sel" data-s="${si}" data-i="${i}" ${r.sel ? 'checked' : ''} aria-label="${esc(tr('Take over {0}', r.dest || tr('Trip')))}"></label>
      <span class="ofcn"><b>${esc(r.dest || tr('Trip'))}</b><small class="muted">${esc(sub)}</small>${why ? `<small class="rki-why">${esc(why)}</small>` : ''}</span>
      <span class="fciamt"><span>${amt(r.amount)}</span><small class="muted">${esc(tr('Excel: {0}', r.excel == null ? '–' : ofcMoney(r.excel)))}</small></span></li>`;
  };
  const draw = () => {
    const n = sheets.reduce((a, s) => a + s.rows.filter(ok).length, 0), cnt = k => sheets.reduce((a, s) => a + s.rows.filter(r => r.status === k).length, 0);
    card.innerHTML = `<h3>${tr('Take over per diems from Excel')}</h3><p class="muted">${esc(name)} · ${esc([cnt('new') ? trn('{0} new', '{0} new', cnt('new')) : '', cnt('warn') ? trn('{0} with a hint', '{0} with a hint', cnt('warn')) : '', cnt('dup') ? trn('{0} already there', '{0} already there', cnt('dup')) : '', cnt('error') ? trn('{0} with an error', '{0} with an error', cnt('error')) : ''].filter(Boolean).join(' · '))}</p>
      ${sheets.map((s, si) => `<section class="rki-sheet"><div class="rki-head"><label class="rki-pl" for="rki-p${si}">${esc(s.sheet)}</label>
        <select id="rki-p${si}" data-rki="person" data-s="${si}">${ppl.map(p => `<option value="u${p.id}" ${s.pv === `u${p.id}` ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}<option value="n" ${s.pv === 'n' ? 'selected' : ''}>${esc(tr('As a free name: {0}', s.person?.name || s.sheet))}</option></select>
        <small class="muted rki-sum">${esc(tr('Sum: Excel {0}, calculated {1}', ofcMoney(s.sum_excel), ofcMoney(s.sum_calc)))}</small></div>
        <ul class="fcilist rki-list" role="list">${s.rows.map((r, i) => rowHtml(r, si, i)).join('')}</ul></section>`).join('')}
      <div class="aerr" role="alert"></div>
      <div class="foot"><span class="spacer"></span><button class="btn" data-rki="close">${tr('Cancel')}</button><button class="btn pri" data-rki="go" ${n ? '' : 'disabled'}>${esc(trn('Take over {0} trip', 'Take over {0} trips', n))}</button></div>`;
  };
  draw();
  md.addEventListener('change', e => {
    const t = e.target.closest('[data-rki]'); if (!t) return;
    const s = sheets[+t.dataset.s]; if (!s) return;
    if (t.dataset.rki === 'person') s.pv = t.value;
    else if (t.dataset.rki === 'sel') { const r = s.rows[+t.dataset.i]; if (r) r.sel = t.checked; }
    else return;
    const sel = t.dataset.rki === 'person' ? `#rki-p${t.dataset.s}` : `[data-rki="sel"][data-s="${t.dataset.s}"][data-i="${t.dataset.i}"]`;
    draw(); $(sel, md)?.focus();
  });
  md.addEventListener('click', async e => {
    const b = e.target.closest('button[data-rki]'); if (!b) return;
    if (b.dataset.rki === 'close') { md.remove(); return; }
    if (b.dataset.rki !== 'go') return;
    const trips = sheets.flatMap(s => s.rows.filter(ok).map(r => ({date_from: r.date_from, date_to: r.date_to, dest: r.dest, overnight: r.overnight,
      people: [s.pv === 'n' ? {name: s.person?.name || s.sheet} : {id: +s.pv.slice(1)}], purpose: r.purpose, project: r.project, note: r.note,
      country: r.country, place: r.place, t_start: r.t_start, t_end: r.t_end, vma_days: r.vma_days, ...(r.status === 'dup' ? {dup_ok: 1} : {})})));  // 2.269.0 D (#3046): dup_ok = ticked on purpose
    if (!await importTargetConfirm({what: trn('{0} trip', '{0} trips', trips.length), ws: ofcWs(), place: tr('Office')})) return;
    b.disabled = true;
    try {
      const k = await api('POST', '/api/office/trips/import', {trips});
      const ys = [...new Set(trips.map(t => t.date_from.slice(0, 4)))];
      md.remove(); Object.assign(RK, {open: null, filter: 'all', view: 'trips'});
      if (RK.year && !ys.includes(RK.year)) RK.year = ys.length === 1 ? ys[0] : '';  // show what came in
      rk_reload();
      toast(trn('{0} trip imported', '{0} trips imported', k.created), async () => { const u = await api('POST', '/api/office/trips/delete', {ids: k.ids}); rk_reload();
        const n = (u.kept || []).length + (u.skipped || []).length;  // 2.272.0 C (#3027): changed trips stay
        if (n) toast(trn('{0} trip stays: changed since the import', '{0} trips stay: changed since the import', n)); });
    } catch (x) { b.disabled = false; const el = $('.aerr', md); if (el) el.textContent = x.message || ''; }
  });
  return md;
}
document.addEventListener('click', e => {
  const b = e.target.closest?.('[data-rki="pick"]'); if (!b) return;
  e.preventDefault(); rk_impPick();
});
